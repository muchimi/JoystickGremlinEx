
# # -*- coding: utf-8; -*-

# # Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
# #
# # This program is free software: you can redistribute it and/or modify
# # it under the terms of the GNU General Public License as published by
# # the Free Software Foundation, either version 3 of the License, or
# # (at your option) any later version.
# #
# # This program is distributed in the hope that it will be useful,
# # but WITHOUT ANY WARRANTY; without even the implied warranty of
# # MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# # GNU General Public License for more details.
# #
# # You should have received a copy of the GNU General Public License
# # along with this program.  If not, see <http://www.gnu.org/licenses/>.

# from __future__ import annotations
# import logging

# from PySide6 import QtWidgets, QtCore, QtGui
# import threading
# import gremlin.base_classes
# import gremlin.config
# import gremlin.event_handler
# import gremlin.input_devices
# import gremlin.input_devices
# import gremlin.joystick_handling
# import gremlin.shared_state
# import gremlin.shared_state
# from gremlin.types import DeviceType
# from gremlin.input_types import InputType
# import gremlin.shared_state
# from gremlin.keyboard import Key
# import gremlin.ui.joystick_device
# import gremlin.base_profile
# import uuid
# from gremlin.singleton_decorator import SingletonDecorator
# import collections
# import logging
# import re
# import time
# from typing import overload, List, Union, Any, Generator, Tuple, Callable, Optional, DefaultDict, Iterator, Union, cast, Coroutine, NamedTuple
# import logging
# from typing import Any, Iterator, List, Union
# import asyncio
# from asyncio import BaseEventLoop
# import fnmatch
# import socketserver
# import socket
# from socket import socket as _socket
# import sys
# import os
# from collections.abc import Iterable
# import struct
# from datetime import datetime, timedelta, date

# import gremlin.ui.ui_common
# from gremlin.util import *
# from lxml import etree as ElementTree

# import enum
# #from gremlin.base_classes import AbstractInputItem
# import gremlin.util
# import vjoy
# import vjoy.vjoy
# import psygnal
# from psygnal import Signal
# import hid


# syslog = logging.getLogger("system")

# class VirpilProductInfo(enum.Enum):
#     ''' possible product info'''
#     CP1 = [0x0259] # control panel 1
#     CP2 = [0x025B, 0x825B] # control panel 2
#     CM2 = [0x8193] # CM2 throttle
#     CM3 = [0x0194, 0x8194] # CM3 throttle
#     ALPHA_RIGHT = [0x40CB]
#     ALPHA_LEFT = [0x80CB]

    

    

# class VirpilBoardType(enum.IntEnum):
#     ''' virpil board types as of September 2025 (byte) '''
#     Default = 0x64
#     AddBoard = 0x65
#     OnBoard = 0x66
#     SlaveBoard = 0x67
#     ExtraBoard = 0x68

# class VirpilIntensity(enum.IntEnum):
#     ''' virpil LED intensity (byte)'''
#     Off = 0x00
#     Low = 0x40
#     Medium = 0x80
#     High = 0xFF

# ''' VIRPIL HID interface for LED control '''
# @SingletonDecorator
# class VirpilInterface():

#     def __init__(self):
#         self._device_found = False
#         self._devices = {} # list of virpil HID devices
#         self._vendor_id = 0x3344 # virpil vendor ID
#         self.deviceFound() # true if the device is found
        

#     def deviceFound(self, refresh = False) -> bool:
#         ''' scans the HID devices to see if the device is found '''
#         if self._device_found:
#             return True
        
#         for data in hid.enumerate():
#             vid = data['vendor_id']
#             pid = data['product_id']
#             if vid == self._vendor_id:
#                 for pid_data in VirpilProductInfo:
#                     for p in pid_data.value:
#                         if pid == p:
#                             device = hid.Device(vid, pid)
#                             self._devices[pid] = device
#                             device.nonblocking = 1
                            
#                             break
                
#         self._device_found = len(self._devices) > 0
#         syslog.info("IFR1: not detected")
#         return False
    
#     def setLed(self, pid, led, r, g, b, board : VirpilBoardType = VirpilBoardType.Default):
#         ''' sets a virpil device LED 
        
#         pid: product ID (number)
#         led: led number
#         r = red component 0..255
#         g = green component 0.255
#         b = blue component 0.255
#         '''

#         device : hid.Device = self._find_device(pid)
#         if not device:
#             # device not found
#             return

#         data = [0 for i in range(38)] # 38 bytes
#         report = 2
#         data[0] = report
#         data[1] = board.value & 0xff # board value 
#         command = self._get_command(board, led)
#         if command is None:
#             # invalid data
#             return
#         data[2] = command

#         # convert dword to byte for color
#         color = 0b1000000
#         color = color | r
#         color = color | (g << 2)
#         color = color | (b << 4)
#         color = color & 0xff
#         data[led + 4] =  color
#         data[37] = 0xf0 # terminator
        
#         data_bytes = bytes(data)
#         device.send_feature_report(data_bytes)
#         pass
    
#     def _find_device(self, pid):
#         ''' finds a virpil device by its PID '''
#         if pid in self._devices:
#             return self._devices[pid]
#         return None

#     def _get_command(self, board : VirpilBoardType, led : int):
#         match board:
#             case VirpilBoardType.Default:
#                 return 0
#             case VirpilBoardType.AddBoard:
#                 return led
#             case VirpilBoardType.OnBoard:
#                 return led + 0x04
#             case VirpilBoardType.SlaveBoard:
#                 return led + 0x18
#             case VirpilBoardType.ExtraBoard:
#                 return led + 0x2C
            
#         return None
            

            

    
# # primary instance
# _virpil_interface = VirpilInterface()