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


from __future__ import annotations
import hid

import logging
syslog = logging.getLogger("system")

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

        for device_map in hid.enumerate():
            keys = list(device_map.keys())
            keys.sort()
            hd = HidDevice()
            for key in keys:
                data = device_map[key]
                match key:
                    case "bus_type":
                        hd.BusType = data
                    case "interface_number":
                        hd.InterfaceNumber = data
                    case "path":
                        hd.Path = data
                    case "vendor_id":
                        hd.VendorId = data
                    case "product_id":
                        hd.ProductId = data
                    case "release_number":
                        hd.ReleaseNumber = data
                    case "manufacturer_string":
                        hd.Manufacturer = data
                    case "serial_number":
                        hd.Serial = data
                    case "usage":
                        hd.Usage = data
                    case "usage_page":
                        hd.UsagePage = data
                        

            syslog.info(f"HID device: Manufacturer: {hd.Manufacturer} Product: {hd.ProductString} VendorID: 0x{hd.VendorId:X} ProductID: 0x{hd.ProductId:X} Usage: {hd.Usage} Page: {hd.UsagePage} Interface: {hd.InterfaceNumber}")
            
                
                
        pass

        # vid = 0x046d	# Change it for your device
        # pid = 0xc534	# Change it for your device

        # with hid.Device(vid, pid) as h:
        #     syslog.info(f'Device manufacturer: {h.manufacturer}')
        #     syslog.info(f'Product: {h.product}')
        #     syslog.info(f'Serial Number: {h.serial}')
