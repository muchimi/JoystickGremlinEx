import importlib.util
import sys
import logging

import gremlin.event_handler
from vigem import vigem_gamepad as vg
from vigem.vigem_client import VigemClient as vc
import gremlin.config
from enum import Enum, auto



_gamepad_available = False
_gamepad_devices = {}

def gamepadAvailable():
    ''' checks that gamepads are available '''
    # check for the vgamepad package
    global _gamepad_available

    if _gamepad_available:
        return True

    syslog = logging.getLogger("system")
    try:
        pad = vg.VX360Gamepad()
        _gamepad_available = vc.initalized and pad.valid
        
        if _gamepad_available:
            syslog.info(f"gamepad: enabled")
        else:
            syslog.info(f"gamepad: not found")
    except:
        syslog.info("VIGEM not found or did not load correctly.  If you have VIGEM installed, check the version and ensure it is the 64 bit version.  This message is normal if VIGEM is not installed.")


   
    return _gamepad_available



def gamepad_initialization():
    ''' sets up the game pads '''
    gamepad_reset()

def gamepad_reset():
    ''' resets the number of game pads to the configured value '''
    device_count = gremlin.config.Configuration().vigem_device_count
    global _gamepad_available, _gamepad_devices
    current_count = len(_gamepad_devices)
    count_changed =current_count != device_count
    if _gamepad_available:
        if device_count == 0:
            keys = list(_gamepad_devices.keys())
            while keys:
                del _gamepad_devices[keys.pop()]
                keys = list(_gamepad_devices.keys())
        else:
            
            if current_count > device_count:
                # remove devices
                while len(_gamepad_devices) > device_count:
                    key = max(_gamepad_devices.keys())
                    del _gamepad_devices[key]
            else:
                while len(_gamepad_devices) != device_count:
                    pad = vg.VX360Gamepad()
                    _gamepad_devices[pad.get_index()-1] = pad
                
    if count_changed:
        # let items in the Ui know the device count changed
        el = gremlin.event_handler.EventListener()
        el.gamepad_change_event.emit()
    


def getGamepad(index):
    ''' gets a gamepad object '''
    global _gamepad_available, _gamepad_devices
    if index in _gamepad_devices.keys():
        return _gamepad_devices[index]
    return None

def gamepadDevices():
    ''' gets the gamepad devices '''
    global _gamepad_available, _gamepad_devices
    return _gamepad_devices.values()

