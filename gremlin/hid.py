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


from __future__ import annotations
import os
from pathlib import Path
import logging
import ctypes
syslog = logging.getLogger("system")

dll_folder = os.path.dirname(__file__)
dll_file = "hidapi.dll"
dll_path = os.path.join(dll_folder, dll_file )
if not os.path.isfile(dll_path):
    # look one level up for packaging in 3.12
    parent = Path(dll_folder).parent
    dll_path = os.path.join(parent, dll_file)
    if not os.path.isfile(dll_path):
        msg = f"Unable to continue - missing dll: {dll_path}"
        syslog.critical(msg)
        os._exit(1)
    dll_folder = parent


ctypes.CDLL(dll_path)

import hid



from gremlin.singleton_decorator import SingletonDecorator

class HidDevice():
    ''' holds data for an HID device '''
    def __init__(self):
        self.BusType = None
        self.Manufacturer = None
        self.Path = None
        self.ProductId = None
        self.VendorId = None
        self.ProductString = None
        self.Serial = None
        self.InterfaceNumber = None
        self.ReleaseNumber = None
        self.Usage = None
        self.UsagePage = None

    def isJoystick(self):
        return self.Usage is not None and self.Usage == 4 # game controllers report as HD usage 4


@SingletonDecorator
class Hid():
    def __init__(self):
        import gremlin.config
        enabled = gremlin.config.Configuration().hid_list_enabled
        self._devices = []
        self._all_devices = []
        index = 0
        if enabled:
            syslog.info("HID: locate HID devices...")
            hid_devices = hid.enumerate()
            syslog.info("HID: done locating HID devices")
            for device_map in hid_devices:
                keys = list(device_map.keys())
                keys.sort()
                device = HidDevice()
                for key in keys:
                    data = device_map[key]
                    match key:
                        case "bus_type":
                            device.BusType = data
                        case "interface_number":
                            device.InterfaceNumber = data
                        case "path":
                            device.Path = data
                        case "vendor_id":
                            device.VendorId = data
                        case "product_id":
                            device.ProductId = data
                        case "release_number":
                            device.ReleaseNumber = data
                        case "manufacturer_string":
                            device.Manufacturer = data
                        case "serial_number":
                            device.Serial = data
                        case "usage":
                            device.Usage = data
                        case "usage_page":
                            device.UsagePage = data

                if device.Usage in (4, 5) and device.UsagePage == 1:
                    # devices 4,5 are controllers, require usage page 1
                    syslog.info(f"HID device: [{index}] Manufacturer: {device.Manufacturer} Product: {device.ProductString} VendorID: 0x{device.VendorId:X}({device.VendorId}) ProductID: 0x{device.ProductId:X}({device.ProductId}) Usage: {device.Usage} Page: {device.UsagePage} Interface: {device.InterfaceNumber}")
                    index +=1
                    self._devices.append(device)
                self._all_devices.append(device)
        else:
            syslog.info("HID: device check disabled in options")

    def get_controller_count(self):
        ''' returns the number of visible controllers (HID device type 4) '''

        # HID usage pages: https://www.usb.org/sites/default/files/hut1_6.pdf
        return len(self._devices)