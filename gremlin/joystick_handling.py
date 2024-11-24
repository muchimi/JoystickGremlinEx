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

import gremlin.base_classes
import gremlin.event_handler
import gremlin.shared_state

from . import common, error, util
from vjoy import vjoy
from dinput import DeviceSummary
from gremlin.input_types import InputType
import gremlin.config

from PySide6 import QtWidgets, QtCore, QtGui

# List of all joystick devices
_joystick_devices = [] # all devices

# map of physical devices by their GUID
_joystick_device_guid_map = {}

# Joystick initialization lock
_joystick_init_lock = threading.Lock()

# initialized flag
_joystick_initialized = False

class VJoyProxy:

    """Manages the usage of vJoy and allows shared access all callbacks."""

    vjoy_devices = {}

    def __getitem__(self, key):
        """Returns the requested vJoy instance.

        :param key id of the vjoy device
        :return the corresponding vjoy device
        """
        assert key is not None and key > 0 and key < 17,"Invalid VJOY device ID provided"
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
    device_list = [dev for dev in _joystick_devices if dev.vjoy_id != -1 and dev.is_virtual]
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

def get_hat(guid, index):
    ''' gets the current hat value '''
    return dinput.DILL.get_hat(guid, index)

    


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
    assert (_joystick_initialized)
    if isinstance(guid, str):
        guid = util.parse_guid(guid) # convert to dinput GUID 
    if guid in _joystick_device_guid_map.keys():
        return _joystick_device_guid_map[guid].name
    return None
    
def device_info_from_guid(guid : str | dinput.GUID) -> DeviceSummary:
    ''' gets physical device information '''
    assert (_joystick_initialized)
    if isinstance(guid, str):
        guid = util.parse_guid(guid) # convert to dinput GUID 
    if guid in _joystick_device_guid_map.keys():
        return _joystick_device_guid_map[guid]
    return None

def vjoy_info_from_vjoy_id(id : int ) -> DeviceSummary:
    ''' gets physical device info for a vjoy device '''
    assert (_joystick_initialized)
    for dev in vjoy_devices():
        if dev.vjoy_id == id:
            return dev
    return None

def is_device_connected(guid : str | dinput.GUID) -> bool:
    ''' true if the device is connected (reported in) '''
    assert (_joystick_initialized)
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

    import gremlin.util
    global _joystick_devices, _joystick_init_lock, _joystick_initialized, _joystick_device_guid_map

    _joystick_initialized = False
    
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
    _joystick_devices = []
    _joystick_device_guid_map = {}
    device_count = dinput.DILL.get_device_count()
    virtual_count = 0
    real_count = 0
    virtual_devices = {}
    for device_index in range(device_count):
        dev = dinput.DILL.get_device_information_by_index(device_index)
        devices.append(dev)
        syslog.info(f"\tindex: [{device_index}] {str(dev)}")
        _joystick_devices.append(dev)
        _joystick_device_guid_map[dev.device_guid] = dev
        if dev.is_virtual: 
            virtual_count += 1
            virtual_devices[dev.hashkey] = dev
        else:
            real_count += 1

    syslog.info(f"Found {real_count} hardware devices and {virtual_count} virtual devices")


    # Process all devices again to detect those that have been added and those
    # that have been removed since the last time this function ran.

    # Compare existing versus observed devices and only proceed if there
    # is a change to avoid unnecessary work.
    # device_added = False
    # device_removed = False
    # for new_dev in devices:
    #     if new_dev not in _joystick_devices:
    #         device_added = True
    #         if verbose:
    #             syslog.debug(f"Added: name={new_dev.name} guid={new_dev.device_guid}")
                
    # for old_dev in _joystick_devices:
    #     if old_dev not in devices:
    #         device_removed = True
    #         if verbose:
    #             syslog.debug(f"Removed: name={old_dev.name} guid={old_dev.device_guid}")

    # # Terminate if no change occurred
    # if not force_refresh and not device_added and not device_removed:
    #     _joystick_init_lock.release()
    #     return

    # In order to associate vJoy devices and their ids correctly with SDL
    # device ids a hash is constructed from the number of axes, buttons, and
    # hats. This information is used to attempt to find unambiguous mappings
    # between vJoy and SDL devices. If this is not possible Gremlin will
    # terminate as this is a non-recoverable error.

    vjoy_lookup = {}
    vjoy_wheel_lookup = {}
    
    should_terminate = False

    # get the vjoy device list from direct input
    # for dev in [dev for dev in devices if dev.is_virtual]:
    #     hash_value = (dev.axis_count, dev.button_count, dev.hat_count)
    #     hash_value_wheel = (dev.axis_count+1, dev.button_count, dev.hat_count)
    #     syslog.info("Virtual VJOY device summary:")
    #     syslog.debug(f"\tHash: {hash_value} {str(dev)}")

    #     # Only unique combinations of axes, buttons, and hats are allowed
    #     # for vJoy devices
    #     if hash_value in vjoy_lookup:
    #         syslog.error("\tFATAL: A VJOY device with the same axis, button and hat count was already found. ")
    #         should_terminate = True
    #         continue

    #     vjoy_lookup[hash_value] = dev
    #     vjoy_wheel_lookup[hash_value_wheel] = dev
        


    # Query all vJoy devices in sequence until all have been processed and
    # their matching SDL counterparts have been found.
    vjoy_hash_list = []
    vjoy_proxy = VJoyProxy()
    for vjoy_index in range(1,17):  # index 1 up to 16
        # Only process devices that actually exist 
        
        if not vjoy.device_exists(vjoy_index):
            syslog.info(f"Vjoy Interface: device {vjoy_index} not found")
            continue

        # Compute a hash for the vJoy device and match it against the SDL
        # device hashes

        axis_count = vjoy.axis_count(vjoy_index)
        button_count = vjoy.button_count(vjoy_index)
        hat_count = vjoy.hat_count(vjoy_index)
        
        hash_value = (axis_count,button_count,hat_count)
        hash_wheel_value = (axis_count+1,button_count,hat_count)

        syslog.info(f"Vjoy Interface: device index [{vjoy_index}] Hash: {hash_value} Hash wheel: {hash_wheel_value} Axis Count: {axis_count} Button count: {button_count} Hat count: {hat_count}")

        if hash_value in vjoy_hash_list:
            syslog.error("Fatal error: This device is not unique in terms of axis/button/hat counts.")
            should_terminate = True
            
        

        if hat_count > 0 and not vjoy.hat_configuration_valid(vjoy_index):
            error_string = f"VJoy id {vjoy_index:d}: Hats are set to discrete but have to be set as continuous."
            syslog.debug(error_string)
            util.display_error(error_string)

        # As we are ensured that no duplicate vJoy devices exist from
        # the previous step we can directly link the SDL and vJoy device
        if hash_value in vjoy_lookup:
            # found the vjoy interface index
            vjoy_lookup[hash_value].set_vjoy_id(vjoy_index)
            syslog.info(f"\tVjoy id {vjoy_index}: found in vjoy interface")
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
            syslog.warning(f"vjoy id {vjoy_index:d}: {hash_value} vJoy device exists but DILL does not see it - check HIDHide config if enabled and process is whitelisted.  This device cannot be used as input.")
            dev = DeviceSummary()
            dev.device_guid = gremlin.util.get_dinput_guid() # bogus ID
            dev.device_id = str(dev.device_guid)
            dev.vendor_id = 0x1234 # vjoy vendor
            dev.product_id = 0xBEAD # vjoy product ID
            dev.joystick_id = vjoy_index
            dev.name = f"VJOY {axis_count}/{button_count}/{hat_count} [{vjoy_index}]"
            dev.axis_count = axis_count
            dev.button_count = button_count
            dev.hat_count = hat_count
            dev.axis_map = []
            dev.usage_page = None
            dev.usage = None
            dev.axis_names = []
            dev.set_vjoy_id(vjoy_index)
            logical_count = 0
            for i in range(8):
                axis_map = dinput.AxisMap()
                axis_map.axis_index = i
                dev.axis_map.append(axis_map)
                axis_name = axis_map.getName()
                if not axis_name:
                    axis_name = f"({i+1})"
                else:
                    logical_count += 1
                dev.axis_names.append(axis_name)

            
            vjoy_lookup[hash_value] = dev
            _joystick_devices.append(dev)
            _joystick_device_guid_map[dev.device_guid] = dev
            syslog.info(f"Adding undetected VJOY device: [{vjoy_index}] {str(dev)}")
            

        if dev.is_virtual and dev.vjoy_id == -1:
            syslog.error(f"vJoy id {vjoy_index:} - VJOY device detected with an invalid ID")
            should_terminate = True

        # If the device can be acquired, configure the mapping from
        # vJoy axis id, which may not be sequential, to the
        # sequential SDL axis id
        if hash_value in vjoy_lookup:
            try:
                # register the vjoy device with the proxy
                vjoy_dev = vjoy_proxy[vjoy_index]
            except error.VJoyError as e:
                syslog.debug(f"vJoy id {vjoy_index:} can't be acquired")

    if not should_terminate:
        if len(_joystick_device_guid_map) == 0:
            syslog.error(f"Error (fatal): no usable VJOY devices found.")
            should_terminate = True

    if should_terminate:
        # exit gracefully
        syslog.error("A fatal error was encountered during the detection and mapping of input devices - see the log for errors.")
        app = QtWidgets.QApplication.instance()
        app.exit()
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

    _joystick_init_lock.release()
    _joystick_initialized = True

    syslog.info("Joystick input initialized")


MAX_VJOY_DEVICE = 16 # number of devices 1..16 supported by VJOY - this includes devices that may not be configured
MAX_VJOY_BUTTON = 128 # max number of buttons per VJOY device

@gremlin.singleton_decorator.SingletonDecorator
class VJoyUsageState():


  
    class MappingData:
        vjoy_device_id = None
        vjoy_input_type = None
        vjoy_input_id = None
        device_input_type = None
        device_guid = None
        device_name = None
        device_input_id = None

        def __init__(self, vjoy_device_id, input_type, vjoy_input_id, action):
            self.vjoy_device_id = vjoy_device_id
            self.vjoy_input_type = input_type
            self.vjoy_input_id = vjoy_input_id
            input_item = action.get_input_item()

            self.device_guid = input_item.device_guid
            self.device_name = input_item.device_name
            self.device_input_type = input_item.device_type
            self.device_input_id = input_item.input_id
            
    

    def __init__(self, profile = None):

        el = gremlin.event_handler.EventListener()
        el.profile_loaded.connect(self.ensure_profile)

        ''' tracks assigned VJOY functions '''
        self._free_inputs = None
        self._device_list = None
        self._profile = None
        self._load_list = []
        self._button_usage = {} # list of used buttons and by what action / input  index is the [vjoy_device_id][button_index] = true if used, false if not
        self._button_usage_map = {} # list of used buttons [vjoy_device_id][button_index] = [action, ...]
        

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
        self.ensure_vjoy()


    @QtCore.Slot(object, object, object)
    def _action_deleted_cb(self, input_item, container, action):
        ''' called when an action is deleted in the profile'''
        self.delete_action(action)

        
    @QtCore.Slot()
    def _profile_changed(self):
        ''' new profile - clear data '''
        self.ensure_vjoy(force_update = True)



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

            for device_id, input_type, input_id in self._load_list:
                # self.set_state(device_id, input_type, input_id, True)
                if input_type == InputType.JoystickButton:
                    self.set_usage_state(device_id, input_id, True)

            self._load_list.clear()


    def ensure_valid(self, vjoy_id : int, input_id : int):
        ''' checks vjoy button mapping exists '''
        if not vjoy_id in  self._button_usage:
            # create it
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


    def set_inverted(self, device_id, input_id, inverted):
        ''' sets the inversion flag for a given vjoy device '''
        if device_id in self._axis_invert_map:
            vjoy = self._axis_invert_map[device_id]
            if input_id in vjoy:
                vjoy[input_id] = inverted
        
    def is_inverted(self, device_id, input_id):
        ''' returns true if the specified device/axis is inverted '''
        return self._axis_invert_map[device_id][input_id]
    
    def toggle_inverted(self, device_id, input_id):
        ''' toggles inversion state of specified device/axis is inverted '''
        sylog = logging.getLogger("system")
        if input_id in self._axis_invert_map[device_id]:
            self._axis_invert_map[device_id][input_id] = not self._axis_invert_map[device_id][input_id]
            sylog.info(f"Vjoy Axis {device_id} {input_id} inverted state: {self._axis_invert_map[device_id][input_id]}")
        else:
            logging.getLogger("system").error(f"Vjoy Axis invert: {device_id} - axis {input_id} is not a valid output axis.")

    def set_range(self, device_id, input_id, min_range = -1.0, max_range = 1.0):
        ''' sets the axis min/max range for the active range computation '''
        if min_range > max_range:
            r = min_range
            min_range = max_range
            max_range = r
        if input_id in self._axis_invert_map[device_id]:
            self._axis_range_map[device_id][input_id] = [min_range, max_range]

    def get_range(self, device_id, input_id):
        ''' gets the current range for an axis (min,max)'''
        return self._axis_range_map[device_id][input_id]
    




    def set_profile(self, profile):
        ''' loads profile data and free input lists'''
        if profile != self._profile:
            self._profile = profile
            self._load_inputs()
            # self._free_inputs = self._profile.list_unused_vjoy_inputs()

            # for device_id in self._free_inputs.keys():
            #     used = []




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
        if emit_list and emit:
            el = gremlin.event_handler.EventListener()
            for vjoy_id in emit_list:
                el.button_usage_changed.emit(vjoy_id)
        


    def set_usage_state(self, vjoy_id : int, button_id : int, action, state : bool, emit = True):
        ''' sets the usage state for a vjoy button '''
        self.ensure_vjoy()
        self.ensure_valid(vjoy_id, button_id) # create entry if needed
        if state:
            if not action in self._button_usage_map[vjoy_id][button_id]:
                self._button_usage_map[vjoy_id][button_id].append(action)
        else:
            # remove the data
            action_list = self._button_usage_map[vjoy_id][button_id]
            if action in action_list:
                action_list.remove(action)

        current_state = self._button_usage[vjoy_id][button_id]
        new_state = len(self._button_usage_map[vjoy_id][button_id]) > 0
        

        if current_state != new_state:
            self._button_usage[vjoy_id][button_id] = new_state
            if emit:
                el = gremlin.event_handler.EventListener()
                el.button_usage_changed.emit(vjoy_id)


    def get_usage_state(self, vjoy_id : int, button_id : int) -> bool:
        ''' gets the usage state for a vjoy button '''
        self.ensure_vjoy()
        self.ensure_valid(vjoy_id, button_id) # create entry if needed - this can happen if the input vjoy device doesn't exist
        if vjoy_id in self._button_usage.keys() and button_id in self._button_usage[vjoy_id].keys():
            return self._button_usage[vjoy_id][button_id]
        return False
    

    def used_list(self, device_id, input_type):
        ''' returns a list of used joystick IDs for the specified vjoy'''
        self.ensure_profile()
        name = self.map_input_type(input_type)
        unused_list = self._free_inputs[device_id][name]
        count = self.get_count(device_id, input_type)
        if count > 0:
            return [id for id in range(1, count+1) if not id in unused_list]
        return []
    
    def unused_list(self, device_id, input_type):
        ''' returns a list of unused input IDs for the specified vjoy'''
        self.ensure_profile()
        name = self.map_input_type(input_type)
        unused_list = self._free_inputs[device_id][name]
        return unused_list

    @property
    def free_inputs(self):
        return self._free_inputs
    
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
        verbose = gremlin.config.Configuration().verbose

        vjoy_devices = gremlin.joystick_handling.vjoy_devices()
        devices = self._profile.devices
        # action_plugins = gremlin.plugin_manager.ActionPlugins()

        def extract_remap_actions(action_sets):
            """Returns a list of remap actions from a list of actions.

            :param action_sets set of actions from which to extract Remap actions
            :return list of Remap actions contained in the provided list of actions
            """
            import action_plugins
            remap_actions = []
            for actions in [a for a in action_sets if a is not None]:
                for action in actions:
                    if isinstance(action, action_plugins.remap.Remap) or isinstance(action, action_plugins.map_to_vjoy.VjoyRemap):
                        remap_actions.append(action)
            return remap_actions

        # List all input types
        all_input_types = InputType.to_list()

        # Create list of all inputs provided by the vjoy devices
        vjoy = {}
        for entry in vjoy_devices:
            vjoy[entry.vjoy_id] = {}
            for input_type in all_input_types:
                vjoy[entry.vjoy_id][InputType.to_string(input_type)] = []
            for i in range(entry.axis_count):
                vjoy[entry.vjoy_id]["axis"].append(
                    entry.axis_map[i].axis_index
                )
            for i in range(entry.button_count):
                vjoy[entry.vjoy_id]["button"].append(i+1)
            for i in range(entry.hat_count):
                vjoy[entry.vjoy_id]["hat"].append(i+1)



        # Create a list of all used remap actions
        remap_actions = []
        for dev in devices.values():
            for mode in dev.modes.values():
                for input_type in all_input_types:
                    for item in mode.config[input_type].values():
                        for container in item.containers:
                            action_list = extract_remap_actions(container.action_sets)
                            remap_actions.append([dev, input_type, item.input_id, action_list])
        
        action_map = {}
        # Remove all remap actions from the list of available inputs
        for dev, input_type, input_id, actions in remap_actions:
            # Skip remap actions that have invalid configuration
            if not actions:
                # no actions found
                continue


            
            for action in actions:
                type_name = InputType.to_string(action.input_type)
        
                    
                if action.vjoy_input_id in [0, None] \
                        or action.vjoy_device_id in [0, None] \
                        or action.vjoy_device_id not in vjoy \
                        or type_name not in vjoy[action.vjoy_device_id] \
                        or action.vjoy_input_id not in vjoy[action.vjoy_device_id][type_name]:
                    if verbose:
                        syslog = logging.getLogger("system")
                        if action.vjoy_device_id not in vjoy:
                            syslog.warning(f"Skipping vjoy device ID: vjoy id {action.vjoy_device_id} not found")
                        elif type_name not in vjoy[action.vjoy_device_id]:
                            syslog.warning(f"Skipping vjoy device ID: vjoy id {action.vjoy_device_id} type {type_name} not found")
                    
                    continue

                vjoy_device_id = action.vjoy_device_id
                vjoy_input_id = action.vjoy_input_id

                if not vjoy_device_id in action_map.keys():
                    action_map[vjoy_device_id] = {}
                if not input_type in action_map[vjoy_device_id].keys():
                    action_map[vjoy_device_id][input_type] = {}

                if not vjoy_input_id in action_map[vjoy_device_id][input_type].keys():
                    action_map[vjoy_device_id][input_type][vjoy_input_id] = []

                action_map[vjoy_device_id][input_type][vjoy_input_id].append([dev.device_guid, dev.name, input_type, input_id])

                idx = vjoy[action.vjoy_device_id][type_name].index(action.vjoy_input_id)
                del vjoy[action.vjoy_device_id][type_name][idx]

        self._free_inputs = vjoy
        self._action_map = action_map

    def get_action_map(self, vjoy_device_id, input_type, input_id):
        ''' gets what's mapped to a vjoy device by input type and input id '''
        #if not self._action_map:
        #self._load_inputs() # update the action map

        # if not vjoy_device_id in self._action_map.keys():
        #     # no mappings for this vjoy device
        #     return []
        # if not input_type in self._action_map[vjoy_device_id].keys():
        #     # no mappings for this type of input
        #     return []
        # if not input_id in self._button_usage_map[vjoy_device_id][input_type]:
        #     # no mapping for this specific id
        #     return []
        
        action_map = []
        for action_data in self._button_usage_map[vjoy_device_id][input_id]:
            data = self.MappingData(vjoy_device_id, input_type, input_id, action_data)
            action_map.append(data)

        return action_map




