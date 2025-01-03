
# -*- coding: utf-8; -*-
# Based on example at: https://github.com/theomessin/jetbridge
# (C) EMCS 2024 and other contributors
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

# Adapted from: https://github.com/odwdinc/Python-SimConnect  Credit for original code goes to the authors of the Python-SimConnect project

from __future__ import annotations
import logging
import struct
from time import sleep
from ctypes import *
from ctypes.wintypes import FLOAT

import gremlin.shared_state
from .Enum import *
import gremlin.config
from .SimConnect import SimConnect
from PySide6 import QtWidgets, QtCore, QtGui
import threading
import os
import glob
from gremlin.singleton_decorator import SingletonDecorator
import copy

kPacketDefinition = 6124
kPublicDownlinkArea = 6125
kPublicUplinkArea = 6126
kUplinkRequest = 6125
kDownlinkRequest = 6126
kPacketDataSize = 1024

class BridgeCommands(IntEnum):
    ExecuteCalculatorCode = 0
    GetNamedVariable = 1
    GetVariableList = 2



kPublicDownlinkChannel = b"muchimi.gremlinex.downlink"
kPublicUplinkChannel = b"muchimi.gremlinex.uplink"


class BRIDGE_PACKET(Structure):
	_fields_ = [
		("id", INT), # id - integer 
        ("code", INT), # command code
        ("data", c_char * kPacketDataSize),  # string max KPacketSize 
	]


class BRIDGE_PACKET_DOUBLE(Structure):
	_fields_ = [
		("id", INT), # id - integer 
        ("code", INT), # command code
        ("data", DOUBLE),  # floating point value return data
	]    


kPacketSize = sizeof(BRIDGE_PACKET)

class SimConnectBridge(QtCore.QObject):
    ''' Simconnect bridge for GremlinEx '''

    lvars_loaded = QtCore.Signal(object) # sent when lvars are received

    def __init__(self, sm : SimConnect):
        super().__init__()

        self.sm = sm
        # add our dispatch handler to simconnect
        
        self._started = False
        self._id = 0 
        self._lvars = [] # list of received lvars 
        self._state = None # response state
        self._wait_event = threading.Event() # wait event

    def start(self):
        if self._started:
            return
        self.sm.register_client_data_handler(self.client_data_callback_handler)
        
        self.sm._dll.AddToClientDataDefinition(self.sm._hSimConnect, kPacketDefinition, 0, kPacketSize, 0.0, SIMCONNECT_UNUSED)
        self.sm._dll.MapClientDataNameToID(self.sm._hSimConnect, kPublicDownlinkChannel, kPublicDownlinkArea)
        self.sm._dll.MapClientDataNameToID(self.sm._hSimConnect, kPublicUplinkChannel, kPublicUplinkArea)    
        self.sm._dll.RequestClientData(self.sm._hSimConnect,
                                       kPublicDownlinkArea,
                                       kDownlinkRequest,
                                       kPacketDefinition,
                                       SIMCONNECT_CLIENT_DATA_PERIOD.SIMCONNECT_CLIENT_DATA_PERIOD_ON_SET,
                                       SIMCONNECT_CLIENT_DATA_REQUEST_FLAG.SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_CHANGED,
                                       0,
                                       0,
                                       0)
        syslog = logging.getLogger("system")
        syslog.info(f"Bridge: data areas registered...")
        self._started = True


    def stop(self):
        if not self._started:
            return
        syslog = logging.getLogger("system")
        syslog.info("Bridge: stop")
        self.sm.unregister_client_data_handler(self.client_data_callback_handler)
        self.sm._dll.RequestClientData(self.sm._hSimConnect, kPublicDownlinkArea, kDownlinkRequest, kPacketDefinition,
                                  SIMCONNECT_CLIENT_DATA_PERIOD.SIMCONNECT_CLIENT_DATA_PERIOD_NEVER,
                                  SIMCONNECT_CLIENT_DATA_REQUEST_FLAG.SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_DEFAULT, 0,0,0)
        
        self._started = False

    def _get_next_id(self):
        # gets the next packet ID
        id = self._id
        self._id += 1
        if self._id > 32765:
            self._id = 0
        return id



        

    @property
    def connected(self):
        return self._started

    # simconnect library callback
    def client_data_callback_handler(self, pData):
        ''' processes received simconnect data to see if it came from mobiflight '''
        syslog = logging.getLogger("system")
        client_data = cast(pData, POINTER(SIMCONNECT_RECV_CLIENT_BYTE_DATA)).contents
        #client_data = copy.deepcopy(data)


        syslog.info(f"client data callback: define id: {client_data.dwDefineID}")
        if client_data.dwRequestID  == kDownlinkRequest:
            # mobiflight core client data received on MobiFlight client registration
            packet = cast(client_data.dwData, POINTER(BRIDGE_PACKET)).contents

            if packet.code == BridgeCommands.GetNamedVariable:
                # named variable
                packet = cast(client_data.dwData, POINTER(BRIDGE_PACKET_DOUBLE)).contents
                value = packet.data # double
                syslog.info(f"Bridge: received mobiflight value:: {value}")
                
            elif packet.code == BridgeCommands.GetVariableList:
                data = packet.data.decode()
                if data == "#lvar_begin#":
                    self._lvars.clear()
                    self._state = "loading"

                elif data == "#lvar_end#":
                    self._state = "complete"

                elif self._state == "loading":
                    self._lvars.append(data)  
                                      
                if self._state == "complete":
                    thread = threading.Thread(target = lambda: self.lvars_loaded.emit(self._lvars))
                    thread.start()
                    self._state = None
                    
            elif packet.code == BridgeCommands.ExecuteCalculatorCode:
                # mark done executing the command
                self._wait_event.set()  

            
            # find the terminating zero

            data = packet.data
            syslog.info(f"Bridge: received mobiflight data: {data}")
            


                
    def execute_calculator_code(self, command):
        ''' executes an RPN expression '''
        syslog = logging.getLogger("system")
        if self._wait_event.is_set():
            # currently executing another command - ignore
            syslog.info("execute: already executing")
            return
        id = self._get_next_id() # id is sequential so it's unique for each call and will roundrobin
        data = command.encode("ascii")
        packet = BRIDGE_PACKET(id, BridgeCommands.ExecuteCalculatorCode, data)
        packet_pointer = cast(pointer(packet), c_void_p)
        
        syslog.info("execute: start")
        self._wait_event.clear()
        self.sm._dll.SetClientData(
            self.sm._hSimConnect,
            kPublicUplinkArea, 
            kPacketDefinition,
            SIMCONNECT_CLIENT_DATA_REQUEST_FLAG.SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_DEFAULT,
            0, # dwReserved
            kPacketSize, 
            packet_pointer)
        
        syslog = logging.getLogger("system")
        syslog.info(f"Bridge: send calculator: {command}")
        # wait for the event
        self._wait_event.wait(0.5)
        syslog.info("execute: completed")
        self._wait_event.clear()

    def get_variable(self, command):
        ''' gets a named variables '''
        id = self._get_next_id() # id is sequential so it's unique for each call and will roundrobin
        data = command.encode("ascii")
        packet = BRIDGE_PACKET(id, BridgeCommands.GetNamedVariable, data)
        packet_pointer = cast(pointer(packet), c_void_p)
        self.sm._dll.SetClientData(
            self.sm._hSimConnect,
            kPublicUplinkArea, 
            kPacketDefinition,
            SIMCONNECT_CLIENT_DATA_REQUEST_FLAG.SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_DEFAULT,
            0, # dwReserved
            kPacketSize, 
            packet_pointer)
        
        syslog = logging.getLogger("system")
        syslog.info(f"Bridge: get named variable: {command}")

    

    def get_lvars(self):
        ''' gets the list of lvars from the sim '''
        id = self._get_next_id() # id is sequential so it's unique for each call and will roundrobin
        packet = BRIDGE_PACKET(id, BridgeCommands.GetVariableList, b"")
        packet_pointer = cast(pointer(packet), c_void_p)
        self.sm._dll.SetClientData(
            self.sm._hSimConnect,
            kPublicUplinkArea, 
            kPacketDefinition,
            SIMCONNECT_CLIENT_DATA_REQUEST_FLAG.SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_DEFAULT,
            0, # dwReserved
            kPacketSize, 
            packet_pointer)
        
        syslog = logging.getLogger("system")
        syslog.info(f"Bridge: get variable list")