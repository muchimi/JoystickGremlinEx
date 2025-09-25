# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2025 
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


import gremlin.shared_state
import gremlin.types
from gremlin.types import DeviceType
import gremlin.hid
import gremlin.singleton_decorator
import gremlin.util



from . import common, error, util
from vjoy import vjoy
#from dinput import DeviceSummary
from gremlin.input_types import InputType
import gremlin.config

from PySide6 import QtWidgets, QtCore, QtGui

# List of all joystick devices
_joystick_devices = [] # detected devices only (including virtual devices that exist all the time like OSC or Modes)
_all_joystick_devices = [] # [DeviceSummary] of all devices, virtual, connected and disconnected
_vjoy_devices = [] # real vjoy devices

_joystick_device_guid_map = {}  # map of DeviceSummary objects keyed by dInput GUID



# Joystick initialization lock
_joystick_init_lock = threading.Lock()

# joystick linear axis names

class AxisNames:
    joystick_linear_axis_names = ["X","Y","Z","S1","S2","RX","RY","RZ"]

# initialized flag
_joystick_initialized = False

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
        assert vid is not None and vid > 0 and vid < 17,"Invalid VJOY device ID provided"
        if vid in VJoyProxy.vjoy_devices:
            return VJoyProxy.vjoy_devices[vid]
        else:
            if not isinstance(vid, int):
                raise error.GremlinError("Integer ID for vjoy device ID expected")

            try:
                # ok for output
                device = vjoy.VJoy(vid)
                VJoyProxy.vjoy_devices[vid] = device
                return device
            except error.VJoyError as e:
                msg = f"Failed accessing vJoy id={vid}, error is: {e}"
                syslog.error(msg)
                raise e

    @classmethod
    def reset(self):
        """Relinquishes control over all held VJoy devices."""
        devices = list(VJoyProxy.vjoy_devices.values())
        for device in devices:
            device.invalidate()
        VJoyProxy.vjoy_devices = {}

      
def joystick_devices(): # -> list[DeviceSummary]:
    """Returns the list of connected joystick like devices 
    :return list containing information about all joystick like devices
    """
    return _joystick_devices


def all_joystick_devices(): # -> list[DeviceSummary]:
    """Returns the list of connected and disconnected joystick like devices 
    :return list containing information about all joystick like devices
    """
    return _all_joystick_devices


def axis_input_devices(): # -> list[DeviceSummary]:
    ''' returns the list of input devices '''
    devices = [dev for dev in _joystick_devices if dev.axis_count]
    return devices
    
def button_input_devices(): # -> list[DeviceSummary]:
    devices = [dev for dev in _joystick_devices if dev.button_count]
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
    

def vjoy_devices(connected_only = True): # -> list[DeviceSummary]:
    """Returns the list of vJoy devices.

    :param connected_only: if set, filters VJOY devices that are detected only, if not, returns all 16 devices
    :return list of [DeviceSummary] holding the device configuration for every vjoy device
    """

    if connected_only:
        device_list = [dev for dev in _joystick_devices if dev.vjoy_id in _vjoy_devices and dev.is_virtual]
    else:
        device_list = [dev for dev in _all_joystick_devices if dev.vjoy_id != -1 and dev.is_virtual]
    
    return device_list

def get_device(guid): # -> DeviceSummary:
    ''' gets a device from its guid'''
    if isinstance(guid, int):
        # vjoy ID given
        return vjoy_info_from_vjoy_id(guid)
    if isinstance(guid, str):
        guid = gremlin.util.parse_guid(guid)
    if guid in _joystick_device_guid_map:
        return _joystick_device_guid_map[guid]
    return None


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


        
def get_axis_name(input_id):
    ''' gets the axis name based on the input # '''
    if input_id == 1:
        axis_name = "X"
    elif input_id == 2:
        axis_name = "Y"
    elif input_id == 3:
        axis_name = "Z"
    elif input_id == 4:
        axis_name = "RX"
    elif input_id == 5:
        axis_name = "RY"
    elif input_id == 6:
        axis_name = "RZ"
    elif input_id == 7:
        axis_name = "S1"
    elif input_id == 8:
        axis_name = "S2"
    else:
        axis_name = f"(unknown [{input_id}])"
    return axis_name     

def get_axis_curve_data(guid, identifier):
    ''' gets the curve data for an axis '''   


def get_curved_axis(guid, identifier):
    ''' returns curved/calibrated data same as the event handler '''
    import gremlin.ui.osc_device
    import gremlin.ui.midi_device
    import gremlin.config
    if isinstance(guid, str):
        guid = gremlin.util.parse_guid(guid)

    verbose = gremlin.config.Configuration().verbose_mode_curve

    device = get_device(guid)
    if not device.is_special:
        eh = gremlin.event_handler.EventListener()
        value = dinput.DILL.get_axis(guid, identifier)
        curved = eh.apply_transforms(guid, identifier, value)
        if verbose:
            syslog.info(f"APPLY CURVE: {device.name} axis: [{identifier}] input: {value:0.3f} curved: {curved:0.3f}")
        return curved
    
    else:
        if device.device_type == DeviceType.Osc and isinstance(identifier, gremlin.ui.osc_device.OscInputItem) and identifier.is_axis:
            osc = gremlin.ui.osc_device.InputOscClient()
            osc.start()
            data = osc.getData(identifier.message) # gets data arguments or None if no data
            if data is None:
                data = 0 # default is centered
            return data
        
    return None
            

def get_axis(guid, index, normalized = True):
    ''' gets the value of the specified axis
     
    :param: normalized  - if set - normalizes to -1.0 +1.0 floating point
       
    '''
    if isinstance(guid, str):
        guid = gremlin.util.parse_guid(guid)
    if is_hardware_device(guid):
        value = dinput.DILL.get_axis(guid, index)
        if normalized:
            return gremlin.util.scale_to_range(value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1)
    return 0.0

def get_hat(guid, index) -> int:
    ''' gets the current hat value '''
    if isinstance(guid, str):
        guid = gremlin.util.parse_guid(guid)
    device = get_device(guid)
    return device.get_hat(index)

def get_hat_position(guid, index) -> tuple:
    ''' gets the hat position as a position tuple '''
    direction = get_hat(guid, index)
    if direction in vjoy.Hat.to_continuous_position:
        return vjoy.Hat.to_continuous_position[direction]
    return (0,0)

def get_button(guid, index) -> bool:
    ''' gets the button pressed state '''
    
    if isinstance(guid, str):
        guid = gremlin.util.parse_guid(guid)
    device = get_device(guid)
    return device.get_button(index)
       


def set_button(guid, index : int, is_pressed : bool):
    ''' sets a vjoy device button if the index and guid exists '''
    import gremlin.event_handler
    sd = gremlin.event_handler.JoystickState()
    if isinstance(guid, str):
        guid = gremlin.util.parse_guid(guid)
    
    if sd.outputIgnored(guid):
        # output ignored 
        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        if verbose:
            device = device_info_from_guid(guid)
            syslog.info(f"VJOY SET BUTTON: {device.name} output ignored [{index}] pressed: {is_pressed}")
        return
    device = get_device(guid)
    if device and device.is_virtual:
        vjoy_id = device.vjoy_id
        if 0 < index <= device.button_count:
            proxy = gremlin.joystick_handling.VJoyProxy()
            proxy[vjoy_id].button(index).is_pressed = is_pressed
    
def set_axis(guid, index : int, value : float):
    ''' sets a vjoy axis '''
    import gremlin.event_handler
    sd = gremlin.event_handler.JoystickState()
    if sd.outputIgnored(guid):
        # output ignored 
        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        if verbose:
            device = device_info_from_guid(guid)
            syslog.info(f"VJOY SET AXIS: {device.name} output ignored [{index}] value: {value: 0.3f}")
        return
    device = get_device(guid)
    if device and device.is_virtual:
        vjoy_id = device.vjoy_id
        if 0 < index <= device.axis_count:
            proxy = gremlin.joystick_handling.VJoyProxy()
            proxy[vjoy_id].axis(index).value = value



def set_hat(guid, index : int, direction : tuple):
    if isinstance(guid, str):
        guid = gremlin.util.parse_guid(guid)
    proxy = gremlin.joystick_handling.VJoyProxy()
    device = get_device(guid)
    if device and device.is_virtual:
        vjoy_id = device.vjoy_id
        if 0 < index < device.hat_count:
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
        for dev in vjoy_devices():
            if dev.vjoy_id == guid:
                return guid # valid
        return not_found_id
    
    if isinstance(guid, str):
        guid = util.parse_guid(guid) # convert to dinput GUID 
    for dev in vjoy_devices():
        if gremlin.util.compare_guid(dev.device_guid, guid):
            return dev.vjoy_id

    syslog.error(f"Could not find vJoy matching guid {str(guid)}")
    return not_found_id


def registerSpecialDevice(dev):
    ''' adds a special device to the tracking list '''
    assert (_joystick_initialized)
    device_guid = dev.device_guid
    if not device_guid in _joystick_device_guid_map:
        _joystick_device_guid_map[device_guid] = dev
        syslog.info(f"SPECIAL DEVICE: {dev.device_id} / {dev.device_type.name} -> {dev.name}")


def removeDevice(dev):
    ''' removes a device from the tracking list'''
    global _all_joystick_devices, _vjoy_devices, _joystick_devices
    device_guid = dev.device_guid
    if device_guid in _joystick_device_guid_map:
        del _joystick_device_guid_map[device_guid]
        
        _all_joystick_devices = [d for d in _all_joystick_devices if d.device_guid != device_guid]
        if dev.device_type == DeviceType.VJoy:
            _vjoy_devices = [d for d in _vjoy_devices if d.device_guid != device_guid]
            
        _joystick_devices = [d for d in _joystick_devices if d.device_guid != device_guid]



def device_name_from_guid(device_guid) -> str:
    ''' gets device name from GUID '''
    assert (_joystick_initialized)
    if isinstance(device_guid, str):
        device_guid = gremlin.util.parse_guid(device_guid) # GUID expected
    if device_guid in _joystick_device_guid_map:
        return _joystick_device_guid_map[device_guid].name
    # not found - check for any updated devices
    joystick_devices_update()
    if device_guid in _joystick_device_guid_map:
        return _joystick_device_guid_map[device_guid].name

    return None
    
def known_devices() -> list:
    ''' gets the list of device GUID (strings) known to GremlinEx '''
    return [guid for guid in _joystick_device_guid_map.keys()]

def getKnownDevicesGuids() -> list:
    ''' gets a list of known device GUIDs '''
    return [gremlin.util.parse_guid(id) for id in known_devices()]

def getDevices() -> list[dinput.DeviceSummary]:
    ''' gets a list of known devices, physical and virtual '''
    return [dev for dev in _joystick_device_guid_map.values()]

def getDevice(device_guid):
    ''' gets a device summary '''
    return device_info_from_guid(device_guid)

def device_info_from_guid(device_guid): # -> DeviceSummary:
    ''' gets physical device information '''
    assert (_joystick_initialized)
    if isinstance(device_guid, str):
        device_guid = gremlin.util.parse_guid(device_guid)
    if device_guid in _joystick_device_guid_map:
        return _joystick_device_guid_map[device_guid]
    joystick_devices_update()
    if device_guid in _joystick_device_guid_map:
        return _joystick_device_guid_map[device_guid]

    return None

def vjoy_info_from_vjoy_id(id : int): # -> DeviceSummary:
    ''' gets physical device info for a vjoy device '''
    assert (_joystick_initialized)
    for dev in vjoy_devices():
        if dev.vjoy_id == id:
            return dev
    # syslog.warning(f"getVjoyInfo: vjoy {id} not found")
    # verbose = gremlin.config.Configuration().verbose
    # if verbose:
    #     syslog.info("\tKnown devices:")
    #     for dev in vjoy_devices():
    #         syslog.info(f"\t\t{str(dev.device_guid)} vjoy id: {dev.vjoy_id}")
    return None

def is_device_connected(device_guid) -> bool:
    ''' true if the device is connected (reported in) '''
    assert (_joystick_initialized)
    return device_guid in _joystick_device_guid_map.keys()



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
    return -1


def registerSpecialDevices():
    ''' registers special devices '''
    import gremlin.ui.octavi_device
    import gremlin.ui.osc_device
    import gremlin.ui.midi_device

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
            



def joystick_devices_initialization():
    """Initializes joystick device information.

    This function retrieves information about various joystick devices and
    associates them and collates their information as required.

    Amongst other things this also ensures that each vJoy device has a correct
    windows id assigned to it.
    """

    import gremlin.util
    import time
    global _joystick_devices, _joystick_init_lock, _joystick_initialized, _joystick_device_guid_map, _vjoy_devices, _all_joystick_devices

    _joystick_initialized = False
    config = gremlin.config.Configuration()
    verbose = config.verbose_mode_inputs
    verbose_detailed = verbose and config.verbose_mode_extra

    _joystick_init_lock.acquire()

    syslog = logging.getLogger("system")
    syslog.info("INIT: Initializing joystick devices")

    dinput.DILL.init()
    _hid = gremlin.hid.Hid()
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
        

    # Process all connected devices in order to properly initialize the device registry
    devices = []
    _joystick_devices = [] # [DeviceSummary] of connected devices only
    _all_joystick_devices = [] # [DeviceSummary] of all devices, virtual, connected and disconnected
    _vjoy_devices = []
    _joystick_device_guid_map.clear()
    virtual_count = 0
    real_count = 0
    virtual_devices = {}
    
    for device_index in range(device_count):
        # these are all connected devices
        dev = dinput.DILL.get_device_information_by_index(device_index)

        if dev.vendor_id == 0x4d8 and dev.product_id == 0xe6d6 and dev.button_count == 35:
            # IFR1 device, disable
            syslog.warning("INIT: Octavi IFR1 is disabled in GremlinEx as a regular joystick as it's handled at the HID level.")
            dev.disabled = True


        devices.append(dev)
        syslog.info(f"\tindex: [{device_index}] {str(dev)}")
        _joystick_devices.append(dev)
        _all_joystick_devices.append(dev)
        _joystick_device_guid_map[dev.device_guid] = dev # key by GUID
        _joystick_device_guid_map[dev.device_id] = dev # key by string ID
        if dev.is_virtual: 
            virtual_count += 1
            virtual_devices[dev.hashkey] = dev
            dev.device_type = DeviceType.VJoy
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
        
        is_connected =  vjoy.device_exists(vjoy_index)

        # Compute a hash for the vJoy device and match it against the SDL
        # device hashes

        if is_connected:
            axis_count = vjoy.axis_count(vjoy_index)
            button_count = vjoy.button_count(vjoy_index)
            hat_count = vjoy.hat_count(vjoy_index)
            if not button_count in used_counts:
                used_counts.append(button_count)
            config_map[vjoy_index] = (is_connected, axis_count, button_count, hat_count)
            _vjoy_devices.append(vjoy_index)
            vjoy.ensure_released(vjoy_index)
        else:
            disconnected_list.append(vjoy_index)
            

    # add missing vjoy devices that are disconnected or not configured so they are still available and marked disconnected
    for vjoy_index in disconnected_list:
        count = 128
        while count in used_counts:
            count-=1
        used_counts.append(count)
        config_map[vjoy_index] = (False, 8, count, 4) # fake configuration, varies by button count only
    

    for vjoy_index in range(1,17):  # list all possible vjoy devices index 1 up to 16
            
        is_connected, axis_count, button_count, hat_count = config_map[vjoy_index]
            
        hash_value = (axis_count,button_count,hat_count)
        hash_wheel_value = (axis_count+1,button_count,hat_count)


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
            dev = dinput.DeviceSummary()
            dev.setConnected(False)
            dev.device_guid = gremlin.util.get_dinput_guid() # bogus ID
            dev.device_id = str(dev.device_guid)
            dev.device_type = DeviceType.VJoy
            dev.vendor_id = 0x1234 # vjoy vendor
            dev.product_id = 0xBEAD # vjoy product ID
            dev.joystick_id = vjoy_index
            dev.name = f"VJOY {axis_count}/{button_count}/{hat_count} [{vjoy_index}]"
            dev.axis_count = axis_count
            dev.button_count = button_count
            dev.hat_count = hat_count
            dev.axismap_list = []
            dev.usage_page = None
            dev.usage = None
            dev.axis_names = []
            dev.set_vjoy_id(vjoy_index)
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
            

        if dev.is_virtual and dev.vjoy_id == -1:
            syslog.error(f"vJoy id {vjoy_index:} - VJOY device detected with an invalid ID")
            should_terminate = True

        # If the device can be acquired, configure the mapping from
        # vJoy axis id, which may not be sequential, to the
        # sequential SDL axis id
        if dev.connected and hash_value in vjoy_lookup:
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

    # register special devices
    registerSpecialDevices()

def joystick_initialized():
    
    return _joystick_initialized


def joystick_devices_update():
    ''' updates any missing dynamic devices like VIGEM '''
    device_count = dinput.DILL.get_device_count()
    if device_count > len( _joystick_devices):
        # add missing items
        for device_index in range(device_count):
            dev = dinput.DILL.get_device_information_by_index(device_index)
            if not dev.device_guid in _joystick_device_guid_map:
                if dev.connected:
                    _joystick_devices.append(dev)
                _all_joystick_devices.append(dev)
                _joystick_device_guid_map[dev.device_guid] = dev # key by GUID
                _joystick_device_guid_map[dev.device_id] = dev # key by string ID


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
        sylog = syslog
        if device_id in self._axis_invert_map:
            if input_id in self._axis_invert_map[device_id]:
                self._axis_invert_map[device_id][input_id] = not self._axis_invert_map[device_id][input_id]
                sylog.info(f"Vjoy Axis {device_id} {input_id} inverted state: {self._axis_invert_map[device_id][input_id]}")
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
        all_input_types = [input_type for input_type in InputType.to_list() if input_type != InputType.State]
        

        # Create list of all inputs provided by the vjoy devices
        vjoy = {}
        for entry in vjoy_devices:
            vjoy[entry.vjoy_id] = {}
            for input_type in all_input_types:
                vjoy[entry.vjoy_id][InputType.to_string(input_type)] = []
            for i in range(entry.axis_count):
                vjoy[entry.vjoy_id]["axis"].append(
                    entry.axismap_list[i].axis_index
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
                    if input_type in mode.config:
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




@gremlin.singleton_decorator.SingletonDecorator
class VjoyStart():
    ''' helper class to handle profile startup data for vjoy output '''

    def __init__(self):
        
        self._axis_data = {}  # map of start profile values indexed by [vjoyid][axis] = float
        self._button_data = {} # map of start profile buttons indexed by [vjoyid][axis] = bool
        self._connected = False # tracks event hook (we don't hook on init because of possible python import issue and load order)

    def setStartValue(self, device_id, id : int, value : float):
        ''' registers an axis start value '''
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
        remote_client = gremlin.input_devices.remote_client
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





