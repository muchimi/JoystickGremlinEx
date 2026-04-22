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
import traceback

import dinput
import time


import gremlin.config
import gremlin.types

import gremlin.shared_state
import gremlin.types
from gremlin.types import DeviceType
import gremlin.hid
import gremlin.singleton_decorator
import gremlin.util
import gremlin.types


from . import common, error, util
from vjoy import vjoy
#from dinput import DeviceSummary
from gremlin.input_types import InputType
import gremlin.config

from PySide6 import QtWidgets, QtCore, QtGui

# List of all joystick devices
_joystick_devices = [] # detected devices only (including virtual devices that exist all the time like OSC or Modes)
_all_joystick_devices = [] # [DeviceSummary] of all devices, virtual, connected and disconnected
_vjoy_devices_map = {} #  connected vjoy devices (int) -> device
_all_vjoy_devices_map = {}# all vjoy devices (int) -> device

_joystick_device_guid_map = {}  # map of DeviceSummary objects keyed by dInput GUID


# Joystick initialization lock
_joystick_init_lock = threading.Lock()

# joystick linear axis names

class AxisNames:
    joystick_linear_axis_names = ["X","Y","Z","S1","S2","RX","RY","RZ"]

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


def joystick_devices(): # -> list[DeviceSummary]:
    """Returns the list of CONNECTED joysticks """
    return _joystick_devices


def all_joystick_devices(): # -> list[DeviceSummary]:
    """Returns the list of CONNECTED AND DISCONNECTED  devices  """
    return _all_joystick_devices


def axis_input_devices(): # -> list[DeviceSummary]:
    ''' returns the list of devices that has axes '''
    devices = [dev for dev in _joystick_devices if dev.axis_count]
    return devices

def button_input_devices(): # -> list[DeviceSummary]:
    ''' returns the list of devices that have buttons'''
    devices = [dev for dev in _joystick_devices if dev.button_count]
    return devices

def hat_input_devices(): # -> list[DeviceSummary]:
    ''' returns the list of devices that define hats '''
    devices = [dev for dev in _joystick_devices if dev.hat_count]
    return devices

def filtered_input_devices(input_type_list = [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat], virtual_only = False):
    ''' gets a list of devices filtered by axis, button or hat '''
    def filter_func(dev : dinput.DeviceSummary):
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

def  is_hardware_device(device_guid) -> bool:
    ''' true if the device is a hardware device '''
    info = device_info_from_guid(device_guid)
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
    ''' true if the device is a vjoy device '''
    info = device_info_from_guid(device_guid)
    if info:
        return info.is_virtual
    return False

def is_vjoy_connected(vjoy_id : int) -> bool:
    ''' true if the vjoy device is connected '''
    global _vjoy_devices_map
    return vjoy_id in _vjoy_devices_map

def is_vjoy_guid_connected(device_guid) -> bool:
    vjoy_id = vjoy_id_from_guid(device_guid, None)
    if vjoy_id is not None:
        return is_vjoy_connected(vjoy_id)
    return False



def vjoy_devices(connected_only = True): # -> list[DeviceSummary]:
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



def get_axis_name(axis_id):
    ''' gets the axis name based on the input # '''
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

def get_axis_curve_data(guid, identifier):
    ''' gets the curve data for an axis '''


def get_curved_axis(device_guid, axis_id):
    ''' returns curved/calibrated data same as the event handler '''
    import gremlin.ui.osc_device
    import gremlin.ui.midi_device
    import gremlin.config
    import gremlin.util

    verbose = gremlin.config.Configuration().verbose_mode_curve

    device = get_device(device_guid)
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
            data = osc.getData(axis_id.message) # gets data arguments or None if no data
            if data is None:
                data = 0 # default is centeredv
            return data

    return None

def get_device(guid : int | str | dinput.GUID, show_error = True) -> dinput.DeviceSummary:
    ''' gets the device for the given ID - issues error message if not found '''
    return device_info_from_guid(guid, show_error)


def get_axis(guid, index, normalized = True, linear = False):
    ''' gets the value of the specified axis

    :param: normalized  - if set - normalizes to -1.0 +1.0 floating point

    '''
    dev : dinput.DeviceSummary = get_device(guid)
    if dev and dev.axis_count:
        axis_id = dev.linear_id_map[index] if linear else index
        value = dinput.DILL.get_axis(dev.device_guid, axis_id)
        if normalized:
            value = gremlin.util.scale_to_range(value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1)
        return value

    return 0.0

def get_hat(guid, index) -> int:
    ''' gets the current hat value '''
    dev : dinput.DeviceSummary = get_device(guid)
    if dev and dev.hat_count:
        return dev.get_hat(index)
    return -1 # center

def get_hat_position(guid, index) -> tuple:
    ''' gets the hat position as a position tuple '''
    direction = get_hat(guid, index)
    if direction in vjoy.Hat.to_continuous_position:
        return vjoy.Hat.to_continuous_position[direction]
    return (0,0) # centered

def get_button(guid, input_id) -> bool:
    ''' gets the button pressed state if the button and device exists - defaults to FALSE if not found'''
    dev : dinput.DeviceSummary = get_device(guid)
    if dev and input_id:
        if dev.button_count:
            if dev.is_virtual and dev.vjoy_id:
                # query the vjoy interface rather than dinput
                button = VJoyProxy()[dev.vjoy_id].button(input_id)
                if button:
                    return button.is_pressed
                else:
                    syslog.warning(f"GetButton(): invalid vjoy [{dev.vjoy_id}] button [{input_id}] not found")
                # invalid button
                return False
            # physical device
            return dev.get_button(input_id)
        else:
            if dev.device_type == DeviceType.Osc:

                if hasattr(input_id, "message"):
                    # OSC device
                    import gremlin.ui.osc_device
                    osc = gremlin.ui.osc_device.InputOscClient()
                    osc.start() # ensure started
                    data = osc.getData(input_id.message) # gets data arguments or None if no data
                    if data:
                        return data
                return False # not received, assume not set


    else:
        syslog.error(f"JOYSTICK: unable to get button state for device for id [{guid}] index [{input_id}]")
    return False



def set_button(guid, index : int, is_pressed : bool, update_remote : bool = False):
    ''' sets a vjoy device button if the index and guid exists

    :param guid: vjoy device ID
    :param index: button id
    :param is_pressed: state of the button to set
    :param update_remote: if enabled, and remote control is enabled, also updates the remote client

    '''
    import gremlin.event_handler
    import gremlin.remote
    sd = gremlin.event_handler.JoystickState()
    device = get_device(guid)
    if not device:
        syslog.error(f"VJOY SET BUTTON: Don't know device [{guid}]")
        return

    if not device.is_virtual and sd.outputIgnored(guid):
        # output ignored
        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        if verbose:
            device = device_info_from_guid(guid)
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


def set_axis(guid, index : int, value : float, update_remote : bool = False):
    ''' sets a vjoy axis '''
    import gremlin.event_handler
    sd = gremlin.event_handler.JoystickState()
    device = get_device(guid)
    if not device:
        syslog.error(f"VJOY SET AXIS: Don't know device [{guid}]")
        return
    if not device.is_virtual and sd.outputIgnored(guid):
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



def set_hat(guid, index : int, direction : tuple):
    ''' sets the device hat '''
    device = get_device(guid)
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
    ''' gets the default device '''
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
            return {
                "device_id": dev.vjoy_id,
                "input_type": InputType.JoystickAxis,
                "input_id": dev.axismap_list[0].axis_index
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


def vjoy_id_from_guid(guid, not_found_id = 1):
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
                return guid # valid
        return not_found_id

    if isinstance(guid, str):
        guid = util.parse_guid(guid) # convert to dinput GUID

    for dev in _all_vjoy_devices_map.values():
        if gremlin.util.compare_guid(dev.device_guid, guid):
            return dev.vjoy_id

    syslog.error(f"Could not find vJoy matching guid {str(guid)}")
    return not_found_id

def vjoy_guid_from_id(vid: int):
    ''' gets the vjoy GUID from a vjoy integer id '''
    for dev in vjoy_devices():
        if dev.vjoy_id == vid:
            return dev.device_guid
    return None


def registerSpecialDevice(dev):
    ''' adds a special device to the tracking list '''
    device_guid = dev.device_guid
    if not device_guid in _joystick_device_guid_map:
        _joystick_device_guid_map[device_guid] = dev
        syslog.info(f"\tid: [{dev.device_id}] type: [{dev.device_type.name}] name: [{dev.name}]")


def removeDevice(dev : dinput.DeviceSummary):
    ''' removes a device from the tracking list'''
    global _all_joystick_devices, _vjoy_devices_map, _joystick_devices
    device_guid = dev.device_guid
    if device_guid in _joystick_device_guid_map:
        del _joystick_device_guid_map[device_guid]

        _all_joystick_devices = [d for d in _all_joystick_devices if d.device_guid != device_guid]
        if dev.device_type == DeviceType.VJoy:
            _vjoy_devices_map = {d.vjoy_id: d for d in _vjoy_devices_map if d.device_guid != device_guid}

        _joystick_devices = [d for d in _joystick_devices if d.device_guid != device_guid]


def device_name_from_guid(device_guid) -> str:
    ''' gets device name from GUID '''

    dev = get_device(device_guid, False)
    if not dev:
        # not found - check for any updated devices
        refresh_devices()
        dev = get_device(device_guid)
    if dev:
        return dev.name
    return ""



def known_devices() -> list:
    ''' gets the list of device GUID (strings) known to GremlinEx '''
    return [guid for guid in _joystick_device_guid_map.keys()]

def getKnownDevicesGuids() -> list:
    ''' gets a list of known device GUIDs '''
    return [gremlin.util.parse_guid(id) for id in known_devices()]

def getDevices() -> list[dinput.DeviceSummary]:
    ''' gets a list of known devices, physical and virtual '''
    return [dev for dev in _joystick_device_guid_map.values()]

def getPhysicalDevices() -> list[dinput.DeviceSummary]:
    return [dev for dev in _joystick_device_guid_map.values() if dev.device_type == DeviceType.Joystick and not dev.is_virtual]


def getDevice(device_guid : int | str | dinput.GUID):
    ''' gets a device summary '''
    return device_info_from_guid(device_guid)

def getDeviceName(device_guid : int | str | dinput.GUID):
    ''' gets the device name'''
    device = getDevice(device_guid)
    if device:
        return device.name
    return f"unknown: {str(device_guid)}"

def getVjoyDeviceGuid(vid):
    ''' gets the vjoy device by the given vjoy id'''
    dev = next((dev for dev in vjoy_devices() if dev.vjoy_id == vid), None)
    if dev:
        return dev.device_guid

    refresh_devices() # do a device reload if the GUID is not found
    dev = next((dev for dev in vjoy_devices() if dev.vjoy_id == vid), None)
    if dev:
        return dev.device_guid


    return None # not found




def getVjoyDeviceMap()->dict:
    ''' gets a map of vjoy devices keyed by the vjoy id, holds a DeviceSummary'''
    return dinput.DILL.getVjoyDeviceMap()




def device_info_from_guid(device_guid : int | str | dinput.GUID, show_error = False) -> dinput.DeviceSummary:
    ''' gets the device for the given ID - issues error message if not found '''
    if device_guid in _joystick_device_guid_map:
        return  _joystick_device_guid_map[device_guid]
    if device_guid in _all_joystick_devices:
        return _all_joystick_devices[device_guid]

    guid = None
    if isinstance(device_guid, int):
        # vjoy ID
        guid = vjoy_guid_from_id(device_guid)
    elif isinstance(device_guid, str):
        guid = gremlin.util.parse_guid(device_guid)
    elif isinstance(device_guid, dinput.GUID):
        guid = device_guid
    elif guid is None:
        if show_error: syslog.error(f"JOY: GET DEVICE: identifier is not specified")
        return None
    else:
        syslog.error(f"JOY: GET DEVICE: don't know how to handle identifier: [{device_guid}]")
        return None

    if guid in _joystick_device_guid_map:
        return  _joystick_device_guid_map[guid]
    if guid in _all_joystick_devices:
        return _all_joystick_devices[guid]


    if show_error: syslog.error(f"JOY: GET DEVICE: Device not found: [{device_guid}]")
    return None



def vjoy_info_from_vjoy_id(vjoy_id : int, connected_only = True): # -> DeviceSummary:
    ''' gets physical device info for a vjoy device

    :param vjoy_id: id of vjoy device 1 to 16
    :param connected_only: true to filter by connected vjoys only
    '''

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

def vjoy_device_map() -> dict:
    ''' returns all vjoy devices indexed by vjoy_id -> device '''
    global _all_vjoy_devices_map
    return _all_vjoy_devices_map.copy()



def is_device_connected(device_guid) -> bool:
    ''' true if the device is connected (reported in) '''

    if device_guid in _joystick_device_guid_map:
        device : dinput.DeviceSummary = _joystick_device_guid_map[device_guid]
        return device.connected
    return False




def linear_axis_index(axis_map, axis_index : int) -> int:
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
    syslog.info("Joystick device change detected - re-initializing joysticks")
    joystick_devices_initialization()
    el = gremlin.event_handler.EventListener()

    el.device_change_event.emit()

def noOpCallback(self, value):
    ''' dummy callback for special devices that don't have a particular axis, hat or button '''
    return None

def noOpHatCallback(self, value):
    ''' dummy callback for special devices that don't have a hat (returns neutral position)'''
    return -1 # center position


def registerSpecialDevices():
    ''' registers special devices '''
    import gremlin.ui.octavi_device
    # import gremlin.ui.osc_device
    # import gremlin.ui.midi_device

    syslog.info("Special devices:")

    # keyboard
    device_guid = str(gremlin.shared_state.keyboard_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "Keyboard"
    device.device_guid = gremlin.shared_state.keyboard_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.Keyboard
    device.is_special = True

    registerSpecialDevice(device)

    # MIDI
    device_guid = str(gremlin.shared_state.midi_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "MIDI"
    device.device_guid = gremlin.shared_state.midi_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.Midi
    device.is_special = True
    registerSpecialDevice(device)

    # OSC
    device_guid = str(gremlin.shared_state.osc_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "OSC"
    device.device_guid = gremlin.shared_state.osc_tab_guid
    device.device_id = device_guid
    device.is_special = True
    device.device_type = DeviceType.Osc
    registerSpecialDevice(device)

    # Octavi IFR1
    device_guid = str(gremlin.shared_state.octavi_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "Octavi IFR1"
    device.device_guid = gremlin.shared_state.octavi_tab_guid
    device.device_id = device_guid
    device.is_special = True
    device.device_type = DeviceType.OctaviIFR1
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
    device.is_special = True
    registerSpecialDevice(device)

    # state
    device_guid = str(gremlin.shared_state.state_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "State"
    device.device_guid = gremlin.shared_state.state_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.State
    device.is_special = True
    registerSpecialDevice(device)

    # plugin
    device_guid = str(gremlin.shared_state.plugins_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "Plugins"
    device.device_guid = gremlin.shared_state.plugins_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.Plugins
    device.is_special = True
    registerSpecialDevice(device)

    # settings
    device_guid = str(gremlin.shared_state.settings_tab_guid)
    device = dinput.DeviceSummary()
    device.name = "Settings"
    device.device_guid = gremlin.shared_state.settings_tab_guid
    device.device_id = device_guid
    device.device_type = DeviceType.Settings
    device.is_special = True
    registerSpecialDevice(device)


def _scan_dinput():
    ''' rescans dinput devices '''

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
        if not dev.device_guid in _joystick_device_guid_map:
            syslog.info(f"\tindex: [{device_index}] {str(dev)}")
            _joystick_devices.append(dev)
            _joystick_device_guid_map[dev.device_guid] = dev # key by GUID


def _create_vjoy_device(vjoy_index : int):
    ''' creates a fake vjoy device '''
    device = dinput.DeviceSummary()
    device.device_id = gremlin.util.get_guid() # random GUID
    device.device_guid = gremlin.util.parse_guid(device.device_id)
    device.device_type = DeviceType.VJoy
    device.name = "vJoy Device"
    device.vendor_id = 0x1234 # vjoy vendor
    device.product_id = 0xBEAD # vjoy product ID
    device.setConnected(False)
    device.axis_count = 8
    device.button_count = 128
    device.hat_count = 4
    device.input_enabled = False
    device.joystick_id = vjoy_index - 1
    device.vjoy_id = vjoy_index
    device.axismap_list = []
    device.usage_page = None
    device.usage = None
    device.axis_names = []
    return device

def joystick_devices_initialization():
    """Initializes joystick device information.

    This function retrieves information about various joystick devices and
    associates them and collates their information as required.

    Amongst other things this also ensures that each vJoy device has a correct
    windows id assigned to it.
    """

    import gremlin.util
    import time
    global _joystick_devices, _joystick_init_lock, _joystick_initialized, _joystick_device_guid_map, _vjoy_devices_map, _all_joystick_devices, _invalid_device_guid, _all_vjoy_devices_map

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

            device_count = 0 #

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
                syslog.warning(f"INIT: DirectX reports no hardware devices detected")

        else:
            max_retries = 10
            attempt = 1
            last_count = 0
            while attempt <= max_retries:
                device_count = dinput.DILL.get_device_count()
                if last_count != device_count:
                    attempt += 1
                    last_count = device_count
                    time.sleep(0.5)
                else:
                    break


        # Process all connected devices in order to properly initialize the device registry
        devices = []
        _joystick_devices = [] # [DeviceSummary] of connected devices only
        _all_joystick_devices = [] # [DeviceSummary] of all devices, virtual, connected and disconnected
        _joystick_device_guid_map.clear()
        _all_vjoy_devices_map.clear()
        _vjoy_devices_map.clear()
        virtual_count = 0
        real_count = 0
        virtual_devices = {}
        dinput_vjoy_device_map = {} # map of vjoy devices by vjoy ID

        syslog.info("DINPUT device list:")
        for device_index in range(device_count):
            # these are all connected devices
            dev = dinput.DILL.get_device_information_by_index(device_index)
            syslog.info(f"\tDevice: {dev.name} ID {dev.device_id}  Type: {dev.device_type.name}")
            if dev.vendor_id == 0x4d8 and dev.product_id == 0xe6d6 and dev.button_count == 35:
                # IFR1 device, disable
                syslog.warning("\t\tOctavi IFR1 is disabled in GremlinEx as a regular joystick as it's handled at the HID level.")
                dev.disabled = True

            if dev.axis_count:
                syslog.info(f"\t\tAxis definitions: {dev.axis_count} found")
                for i in range(dev.axis_count):
                    linear = i + 1
                    axis_id = dev.linear_id_map[linear]
                    axis_name = dev.get_axis_name(axis_id)
                    syslog.info(f"\t\t\tAxis {axis_name} A{axis_id} L{linear} {"(sequential)" if linear == axis_id else "(non-sequential)"}")


            devices.append(dev)
            syslog.info(f"\t\tIndex: [{device_index}] {str(dev)}")
            _joystick_devices.append(dev)
            _all_joystick_devices.append(dev)
            _joystick_device_guid_map[dev.device_guid] = dev # key by GUID
            # _joystick_device_guid_map[dev.device_id] = dev # key by string ID
            if dev.is_virtual:
                virtual_count += 1
                virtual_devices[dev.hashkey] = dev
                dev.device_type = DeviceType.VJoy
                dinput_vjoy_device_map[dev.hashkey] = dev
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
        for vjoy_index in range(1,17):  # index 1 up to 16
            # Only process devices that actually exist
            is_connected =  vjoy.device_available(vjoy_index)
            if is_connected:
                # device reports as available via the VJOY interface
                axis_count = vjoy.axis_count(vjoy_index)
                button_count = vjoy.button_count(vjoy_index)
                hat_count = vjoy.hat_count(vjoy_index)
                if not button_count in used_counts:
                    used_counts.append(button_count)
                config_map[vjoy_index] = (is_connected, axis_count, button_count, hat_count)
                vjoy.ensure_released(vjoy_index)

                dinput_key = (axis_count, button_count, hat_count) #(input_vjoy_device_map[dev.vjoy_id] = dev
                # see if the device was detected in DINPUT
                if not dinput_key in dinput_vjoy_device_map:
                    syslog.warning(f"VJOY device [{vjoy_index}] exists in the VJOY API but was not detected by DINPUT indicating a possible configuration or conflict problem.  This VJOY will be disabled.")
                    disconnected_list.append(vjoy_index)
                    # fake device
                    device = _create_vjoy_device(vjoy_index)
                    _all_vjoy_devices_map[vjoy_index] = device
                    _joystick_device_guid_map[device.device_guid] = device # key by GUID
                    _joystick_device_guid_map[device.device_id] = device # key by string ID

                else:
                    device : dinput.DeviceSummary = dinput_vjoy_device_map[dinput_key]
                    device.vjoy_id = vjoy_index
                    device.setConnected(True) # connected means the VJOY device is not only shown in the API but also with DINPUT.
                    syslog.info(f"VJOY device [{vjoy_index}] matched to DINPUT device [{device.device_id}]")
                    _all_vjoy_devices_map[vjoy_index] = device
                    _vjoy_devices_map[vjoy_index] = device
            else:
                # device reports as not available from the vjoy interface
                disconnected_list.append(vjoy_index)
                device = _create_vjoy_device(vjoy_index)
                _all_vjoy_devices_map[vjoy_index] = device
                _joystick_device_guid_map[device.device_guid] = device # key by GUID
                _joystick_device_guid_map[device.device_id] = device # key by string ID
                if verbose:
                    syslog.warning(f"VJOY device [{vjoy_index}] is not detected or not enabled in the VJOY API. This VJOY will be disabled.")

        # add missing vjoy devices that are disconnected or not configured so they are still available and marked disconnected
        for vjoy_index in disconnected_list:
            count = 128
            while count in used_counts:
                count-=1
            used_counts.append(count)
            config_map[vjoy_index] = (False, 8, count, 4) # fake configuration, varies by button count only
            device = _all_vjoy_devices_map[vjoy_index]
            device.button_count = count # update unique button count for disconnected devices
            device.name = f"Vjoy {device.axis_count}/{device.button_count}/{device.hat_count} ({vjoy_index})"


        for vjoy_index in range(1,17):  # list all possible vjoy devices index 1 up to 16

            is_connected, axis_count, button_count, hat_count = config_map[vjoy_index]

            hash_value = (axis_count,button_count,hat_count)
            hash_wheel_value = (axis_count+1,button_count,hat_count)

            if verbose:
                syslog.info(f"Vjoy Interface: device index [{vjoy_index}] Hash: {hash_value} Hash wheel: {hash_wheel_value} Axis Count: {axis_count} Button count: {button_count} Hat count: {hat_count}  Connected: {is_connected}")

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
                el.terminate() # terminates and sends the relevant shutdown triggers
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
                hash_value = (axis_count,button_count,hat_count)
                hash_wheel_value = (axis_count+1,button_count,hat_count)
                if verbose_detailed: syslog.info(f"vjoy id {vjoy_index:d}: {hash_value} vJoy device exists but DILL does not see it - check HIDHide config if enabled and process is whitelisted.  This device cannot be used as input.  This message is normal if the device is not configured in VJOY.")

                dev = _all_vjoy_devices_map[vjoy_index]
                logical_count = 0
                for i in range(8):
                    axis_map = dinput.AxisMap()
                    axis_map.axis_index = i
                    dev.axismap_list.append(axis_map)
                    axis_name = axis_map.getName()
                    if not axis_name:
                        axis_name = f"({i+1})"
                    else:
                        logical_count += 1
                    dev.axis_names.append(axis_name)


                vjoy_lookup[hash_value] = dev
                _all_joystick_devices.append(dev)
                _joystick_device_guid_map[dev.device_guid] = dev
                if verbose_detailed: syslog.info(f"Adding undetected VJOY device: [{vjoy_index}] {str(dev)}")



            # If the device can be acquired, configure the mapping from
            # vJoy axis id, which may not be sequential, to the
            # sequential SDL axis id
            if dev.connected and hash_value in vjoy_lookup:
                try:
                    # register the vjoy device with the proxy
                    vjoy_dev = vjoy_proxy[vjoy_index]
                except error.VJoyError as e:
                    syslog.error(f"vJoy id {vjoy_index:} can't be acquired")

        if not should_terminate:
            if len(_joystick_device_guid_map) == 0:
                syslog.error(f"Error (fatal): no usable VJOY devices found.")
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
        vjoy_devices_list = [dev for dev in _joystick_devices if dev.is_virtual]
        vjoy_devices_list.sort(key = lambda x: x.vjoy_id)
        for dev in regular_devices_list:
            syslog.info(f"\tDevice: (regular) {str(dev)}")
        for dev in vjoy_devices_list:
            syslog.info(f"\tDevice: (vjoy) {str(dev)}")

        _joystick_initialized = True
        syslog.info("Joystick input initialized")

    # register special devices
    registerSpecialDevices()

    # update calibration on initial joystick device load
    mgr = gremlin.ui.axis_calibration.CalibrationManager()
    mgr.reload()

def joystick_initialized():
    global _joystick_initialized
    return _joystick_initialized


def refresh_devices():
    ''' updates any missing dynamic devices like VIGEM or VJOY from directInput '''
    joystick_devices_initialization()



MAX_VJOY_DEVICE = 16 # number of devices 1..16 supported by VJOY - this includes devices that may not be configured
MAX_VJOY_BUTTON = 128 # max number of buttons per VJOY device

KEEP_ALIVE_DELAY = 120 # keep alive pulse in second

@gremlin.singleton_decorator.SingletonDecorator
class VJoyUsageState():



    class MappingData:
        def __init__(self, vjoy_id, input_type, vjoy_input_id, action_id):
            self.vjoy_id = vjoy_id
            self.vjoy_input_type = input_type
            self.vjoy_input_id = vjoy_input_id
            self.device_guid = None
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



    def __init__(self, profile = None):
        import gremlin.threading
        el = gremlin.event_handler.EventListener()
        el.profile_loaded.connect(self.ensure_profile)


        ''' tracks assigned VJOY functions '''

        self._device_list = None
        self._profile = None
        self._load_list = []
        self._button_usage = {} # list of used buttons and by what action / input  index is the [vjoy_id][button_index] = true if used, false if not
        self._button_usage_map = {} # list of used buttons [vjoy_id][button_index] = [action, ...]


        # holds the mapping by vjoy device, input and ID to a list of raw hardware defining the mapping
        self._action_map = None

        # list of users buttons by vjoy device ID
        self._used_map = {}
        # list of unused buttons by vjoy device ID
        self._unused_map = {}

        self._active_device_guid = None # guid of the hardware device
        self._active_device_name = None # name of the hardware device
        self._active_device_input_type = 0 # type of selected hardware input (axis, button or hat)
        self._active_device_input_id = 0 # id of the function on the hardware device (button #, hat # or axis #)

        self._axis_invert_map = {} # holds map of inverted axes for output
        self._axis_range_map = {} # holds active axis range maps

        if profile:
            profile = gremlin.shared_state.current_profile
            self.set_profile(profile)

        if not self._device_list:
            self._device_list = vjoy_devices()

        # listen for active device changes
        el = gremlin.event_handler.EventListener()
        el.profile_device_changed.connect(self._profile_device_changed)
        el.action_delete.connect(self._action_deleted_cb)
        el.profile_unloaded.connect(self._profile_changed)
        el.set_vjoy_button_usage.connect(self._handle_request_button_change)
        el.shutdown.connect(self._handle_shutdown)
        self.ensure_vjoy()



    def _handle_shutdown(self):
        pass


    def _handle_request_button_change(self, vjoy_id, button_id, state, key):
        ''' handles request for button changes '''
        self.set_usage_state(vjoy_id, button_id, key, state)


    @QtCore.Slot(object, object, object)
    def _action_deleted_cb(self, input_item, container, action):
        ''' called when an action is deleted in the profile'''
        self.delete_action(action)



    def _profile_changed(self):
        ''' new profile - clear data '''
        self.ensure_vjoy(force_update = True)

        # initialize states based on usage
        self.ensure_profile()



    @QtCore.Slot(object)
    def _profile_device_changed(self, event):
        self._active_device_guid = event.device_guid
        self._active_device_name = event.device_name
        self._active_device_input_type = event.device_input_type
        self._active_device_input_id = event.device_input_id


    def push_load_list(self, device_id, input_type, input_id):
        ''' ensure data loaded by this profile is updated the first time through '''
        self._load_list.append((device_id, input_type, input_id))

    def ensure_profile(self):
        if not self._profile or gremlin.shared_state.current_profile != self._profile:
            self.set_profile(gremlin.shared_state.current_profile)



    def ensure_valid(self, vjoy_id : int, input_id : int):
        ''' checks vjoy button mapping exists '''
        if not vjoy_id in self._button_usage:
            self._button_usage[vjoy_id] = {}
            self._button_usage_map[vjoy_id] = {}
        if not input_id in self._button_usage[vjoy_id]:
            self._button_usage[vjoy_id][input_id] = False
            self._button_usage_map[vjoy_id][input_id] = []



    def ensure_vjoy(self, force_update = False):
        ''' ensures the inversion map is loaded '''
        devices = vjoy_devices()
        if not devices:
            return
        if not self._axis_invert_map or force_update:
            self._axis_invert_map = {}
            self._axis_range_map = {}

            for dev in devices:
                dev_id = dev.vjoy_id
                self._axis_invert_map[dev_id] = {}
                self._axis_range_map[dev_id] = {}
                for axis_id in range(1, dev.axis_count+1):
                    self._axis_invert_map[dev_id][axis_id] = False
                    self._axis_range_map[dev_id][axis_id] = [-1.0, 1.0]

        # ensure the button maps are setup for each defined vjoy
        if not self._button_usage or force_update:
            self._button_usage = {}
            self._button_usage_map = {}
            for dev in devices:
                dev_id = dev.vjoy_id
                self._button_usage[dev_id] = {}
                self._button_usage_map[dev_id] = {}

                info = device_info_from_guid(dev.device_guid)
                for button in range(1, info.button_count+1):
                    self._button_usage[dev_id][button] = False
                    self._button_usage_map[dev_id][button] = []

    def _ensure_maps(self, device_guid, input_id):
        ''' automatically registers new inputs if needed '''
        if not device_guid in self._axis_invert_map:
             self._axis_invert_map[device_guid] = {}
        if not input_id in self._axis_invert_map[device_guid]:
            self._axis_invert_map[device_guid][input_id] = False

        if not device_guid in self._axis_range_map:
             self._axis_range_map[device_guid] = {}
        if not input_id in self._axis_range_map[device_guid]:
            self._axis_range_map[device_guid][input_id] =  [-1.0, 1.0]

        if not device_guid in self._button_usage:
             self._button_usage[device_guid] = {}
             self._button_usage_map[device_guid] = {}

        if not input_id in self._button_usage[device_guid]:
            self._button_usage[device_guid][input_id] = False
            self._button_usage_map[device_guid][input_id] = []



    def set_inverted(self, device_id, input_id, inverted):
        ''' sets the inversion flag for a given vjoy device '''
        if device_id in self._axis_invert_map:
            vjoy = self._axis_invert_map[device_id]
            if input_id in vjoy:
                vjoy[input_id] = inverted
                return
        self._ensure_maps(device_id, input_id)

    def is_inverted(self, device_id, input_id):
        ''' returns true if the specified device/axis is inverted '''
        if device_id in self._axis_invert_map:
            if input_id in self._axis_invert_map[device_id]:
                return self._axis_invert_map[device_id][input_id]
        self._ensure_maps(device_id, input_id)
        return False

    def toggle_inverted(self, device_id, input_id):
        ''' toggles inversion state of specified device/axis is inverted '''
        if device_id in self._axis_invert_map:
            if input_id in self._axis_invert_map[device_id]:
                self._axis_invert_map[device_id][input_id] = not self._axis_invert_map[device_id][input_id]
                verbose = gremlin.config.Configuration().verbose_mode_vjoy
                if verbose: syslog.info(f"Vjoy Axis {device_id} {input_id} inverted state: {self._axis_invert_map[device_id][input_id]}")
                return

        self._ensure_maps(device_id, input_id)
        self._axis_invert_map[device_id][input_id] = True # toggle

    def set_range(self, device_id, input_id, min_range = -1.0, max_range = 1.0):
        ''' sets the axis min/max range for the active range computation '''
        if min_range > max_range:
            min_range, max_range = max_range, min_range
        if device_id in self._axis_range_map:
            if input_id in self._axis_invert_map[device_id]:
                self._axis_range_map[device_id][input_id] = [min_range, max_range]
                return
        self._ensure_maps(device_id, input_id)
        self._axis_range_map[device_id][input_id] = [min_range, max_range] # new entry


    def get_range(self, device_id, input_id):
        ''' gets the current range for an axis (min,max)'''
        if device_id in self._axis_range_map:
            if input_id in self._axis_range_map[device_id]:
                return self._axis_range_map[device_id][input_id]
        self._ensure_maps(device_id, input_id)
        return [-1.0, 1.0]





    def set_profile(self, profile):
        ''' loads profile data and free input lists'''
        if profile != self._profile:
            self._profile = profile
            self._button_usage.clear()
            self._button_usage_map.clear() # blits state data on profile change
            self._load_inputs() # load mappings from the profile



    def map_input_type(self, input_type) -> str:
        if isinstance(input_type, InputType):
            if input_type in [InputType.JoystickButton,
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

    def get_count(self, device_id, input_type):
        self.ensure_profile()
        name = self.map_input_type(input_type)
        dev = next((d for d in self._device_list if d.vjoy_id == device_id), None)
        if dev:
            if name == "axis":
                return dev.axis_count
            elif name == "button":
                return dev.button_count
            elif name == "hat":
                return dev.hat_count
        return 0


    def delete_action(self, action, emit = True):
        ''' updates the usage list if the action is removed from the profile '''
        emit_list = set()
        for vjoy_id in self._button_usage_map.keys():
            for button_id in self._button_usage_map[vjoy_id]:
                if action in self._button_usage_map[vjoy_id][button_id]:
                    self._button_usage_map[vjoy_id][button_id].remove(action)
                    current_state = self._button_usage[vjoy_id][button_id]
                    new_state = len(self._button_usage_map[vjoy_id][button_id]) > 0
                    if current_state != new_state:
                        self._button_usage[vjoy_id][button_id] = new_state
                        emit_list.add(vjoy_id)
        if emit_list and emit and not gremlin.shared_state.is_running:
            el = gremlin.event_handler.EventListener()
            for vjoy_id in emit_list:
                el.button_usage_changed.emit(vjoy_id)



    def set_usage_state(self, vjoy_id : int, button_id : int, key : str, state : bool, emit = True):
        ''' sets the usage state for a vjoy button '''
        self.ensure_vjoy()
        self.ensure_valid(vjoy_id, button_id) # create entry if needed
        if vjoy_id in self._button_usage and button_id in self._button_usage_map[vjoy_id]:

            current_state = len(self._button_usage_map[vjoy_id][button_id]) > 0
            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_vjoy and config.verbose_mode_extra
            #verbose = True
            if verbose: syslog.info(f"Set usage state: [{vjoy_id}] [{button_id}] [{state}]  current state [{current_state}] from {key}")
            if state:
                if not key in self._button_usage_map[vjoy_id][button_id]:
                    self._button_usage_map[vjoy_id][button_id].append(key)
            else:
                # remove the data
                if key in self._button_usage_map[vjoy_id][button_id]:
                    self._button_usage_map[vjoy_id][button_id].remove(key)

            new_state = len(self._button_usage_map[vjoy_id][button_id]) > 0

            if current_state != new_state:
                self._button_usage[vjoy_id][button_id] = new_state
                if emit and not gremlin.shared_state.is_running:
                    el = gremlin.event_handler.EventListener()
                    el.button_usage_changed.emit(vjoy_id)
                    el.vjoy_button_usage.emit(vjoy_id, button_id, new_state)
                    if verbose: syslog.info(f"Button used tracker: vjoy {vjoy_id} button {button_id} used: {new_state}")
                    el.input_used_changed.emit(vjoy_id, InputType.JoystickButton, button_id, new_state)


    def get_usage_state(self, vjoy_id : int, button_id : int) -> bool:
        ''' gets the usage state for a vjoy button '''
        self.ensure_vjoy()
        self.ensure_valid(vjoy_id, button_id) # create entry if needed - this can happen if the input vjoy device doesn't exist
        if vjoy_id in self._button_usage:
            return self._button_usage[vjoy_id][button_id]
        return False



    def used_button_list(self, vjoy_id) -> list[int]:
        ''' gets the list of used buttons'''
        used_list = []
        if vjoy_id in self._button_usage_map:
            used_list = [button_id for button_id in self._button_usage_map[vjoy_id] if self._button_usage[vjoy_id][button_id]]

        return used_list


    @property
    def device_list(self):
        return self._device_list

    @property
    def input_count(self, device_id, input_type):
        ''' returns the number of input counts for a given vjoy ID and type (axis, button or hat)

        :device_id:
            device ID, first VJOY is index 1

        :input_type: InputType enum


        '''
        return self.get_count(device_id,input_type)



    def _load_inputs(self):
        """Returns a list of unused vjoy inputs for the given profile.

        :return dictionary of unused inputs for each input type
        """
        import action_plugins
        import gremlin.input_devices
        verbose = gremlin.config.Configuration().verbose
        profile = gremlin.shared_state.current_profile
        if not profile:
            return # nothing to load yet

        devices = profile.devices
        self.ensure_vjoy() # ensure the vjoy devices data objects are populated

        # Create a list of all used remap actions
        for device_guid in devices:
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
                                        if isinstance(action, action_plugins.remap.Remap) or isinstance(action, action_plugins.map_to_vjoy.VjoyRemap):
                                            if hasattr(action,"action_mode"):
                                                action_mode = action.action_mode # vjoy remap
                                                trigger = gremlin.types.VjoyAction.is_button_action(action_mode)
                                                button_id = action.vjoy_button_id
                                            else:
                                                # legacy remap
                                                trigger = action.input_type == InputType.JoystickButton
                                                button_id = action.vjoy_input_id


                                            if trigger:
                                                vjoy_id = action.vjoy_id
                                                if not vjoy_id in self._button_usage:
                                                    syslog.error(f"Profile action id [{action.id}] references a vjoy device [{vjoy_id}] that is no longer found.")
                                                else:
                                                    self._button_usage[vjoy_id][button_id] = True
                                                    self._button_usage_map[vjoy_id][button_id].append(action.id)



    def get_action_map(self, vjoy_id, input_type, input_id):
        ''' gets what's mapped to a vjoy device by input type and input id '''
        action_map = []
        for action_data in self._button_usage_map[vjoy_id][input_id]:
            data = self.MappingData(vjoy_id, input_type, input_id, action_data)
            action_map.append(data)

        return action_map




@gremlin.singleton_decorator.SingletonDecorator
class VjoyStart():
    ''' helper class to handle profile startup data for vjoy output '''

    def __init__(self):

        self._axis_data = {}  # map of start profile values indexed by [vjoyid][axis] = float
        self._button_data = {} # map of start profile buttons indexed by [vjoyid][axis] = bool
        self._connected = False # tracks event hook (we don't hook on init because of possible python import issue and load order)

    def setStartValue(self, device_id , id : int, value : float):
        ''' registers an axis start value '''
        import gremlin.event_handler
        import gremlin.util
        if not isinstance(device_id, int):
            vjoy_id = vjoy_id_from_guid(device_id)
        else:
            vjoy_id = device_id # integer ID

        if vjoy_id is None:
            syslog.error(f"VJOY SET START: : vjoy device [{device_id}] not available")
            return

        if not self._connected:
            # trap profile started event
            el = gremlin.event_handler.EventListener()
            el.profile_started.connect(self.apply)
            self._connected = True

        if not vjoy_id in self._axis_data:
            self._axis_data[vjoy_id] = {}
        self._axis_data[vjoy_id][id] = value

    def setStartState(self, device_id, id : int, state : bool):
        ''' registers a button start value '''
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

        if not vjoy_id in self._button_data:
            self._button_data[vjoy_id] = {}
        self._button_data[vjoy_id][id] = state

    def reset(self):
        ''' resets the start data '''
        self.clear()

    def clear(self):
        ''' resets the start data '''
        self._axis_data = {}
        self._button_data = {}

    def apply(self):
        ''' applies the startup data '''
        import gremlin.input_devices
        remote_client = gremlin.remote.remote_client
        for device_id in self._axis_data:
            for id in self._axis_data[device_id]:
                value = self._axis_data[device_id][id]
                if value is not None:
                    set_axis(device_id, id, value)
                    remote_client.send_axis(device_id, id, value)

        for device_id in self._axis_data:
            for id in self._button_data[device_id]:
                state = self._button_data[device_id][id]
                if state is None:
                    state = False
                set_button(device_id, id, state)
                remote_client.send_button(device_id, id, state)



# instance
_vjoy_start = VjoyStart()





