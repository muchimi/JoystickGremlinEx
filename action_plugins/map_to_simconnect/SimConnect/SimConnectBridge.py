
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

import gremlin.event_handler
import gremlin.shared_state
from .Enum import *
import gremlin.config
from .SimConnect import SimConnect, SimConnectEventHandler
from PySide6 import QtWidgets, QtCore, QtGui
import threading
import os
import glob
from gremlin.singleton_decorator import SingletonDecorator
import copy
import time
import psygnal
from psygnal import Signal

kPacketDefinition = 6124
kPublicDownlinkArea = 6125
kPublicUplinkArea = 6126
kUplinkRequest = 6125
kDownlinkRequest = 6126
kPacketDataSize = 1024

syslog = logging.getLogger("system")

class BridgeCommands(IntEnum):
    ExecuteCalculatorCode = 0
    GetNamedVariable = 1
    GetVariableList = 2
    Ping = 3
    GetAircraftList = 4
    SimConnectError = 5 # occurs when a simconnect error occurs inside the WASM module



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

    lvars_loaded = Signal(object) # sent when lvars are received
    aircraft_list_loaded = Signal(object) # sends the aircraft list (map of [aircraft][list of liveries] )
    alive = Signal() # sent when pong is received (alive signal)

    def __init__(self, sm : SimConnect):
        super().__init__()

        self.sm = sm
        # add our dispatch handler to simconnect
        handler = SimConnectEventHandler()
        handler.status_callback_clicked.connect(self._sync_bridge)
        self._started = False
        self._alive = False # true if alive (pong command received)
        self._id = 0 
        self._lvars = [] # list of received lvars 
        self._aircraft_map = {} # list of aicrafts keyed by aircraft name, holds liveries as a list
        self._state = None # response state
        self._wait_event = threading.Event() # wait event
        self._wait_alive_event = threading.Event() # alive wait event when sending a ping
        el = gremlin.event_handler.EventListener()
        self._alive_thread = None
        self._connect_in_progress = False
        el.shutdown.connect(self._shutdown)

    def start(self):
        if self._started:
            if not self._alive:
                # attempt a ping in case the first one didn' work
                self.ping()
            return
        
        # syslog = logging.getLogger("system")
        try:
            syslog.info(f"SIMCONNECT BRIDGE: starting...")
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
            
            
            self._started = True

            # send the ping command 
            self._alive = False
            self.ping()


        except Exception as err:
            syslog.error(f"SIMCONNECT BRIDGE: start error: {err}")
            pass

    @property
    def is_alive(self)->bool:
        ''' true if connnected '''
        return self._alive


    def stop(self):
        if not self._started:
            return
        if self.sm.is_connected and self._alive:
            # syslog = logging.getLogger("system")
            syslog.info("SIMCONNECT BRIDGE: stop")
            try:
                self.sm.unregister_client_data_handler(self.client_data_callback_handler)
                if self.sm._dll:
                    self.sm._dll.RequestClientData(self.sm._hSimConnect, kPublicDownlinkArea, kDownlinkRequest, kPacketDefinition,
                                    SIMCONNECT_CLIENT_DATA_PERIOD.SIMCONNECT_CLIENT_DATA_PERIOD_NEVER,
                                    SIMCONNECT_CLIENT_DATA_REQUEST_FLAG.SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_DEFAULT, 0,0,0)
            except:
                pass
        
            self._started = False
            self._connect_in_progress = False # if we are aborting
        
    def _get_next_id(self):
        # gets the next packet ID
        id = self._id
        self._id += 1
        if self._id > 32765:
            self._id = 0
        return id

    @QtCore.Slot()
    def _shutdown(self):
        ''' terminate issued '''

        self.stop()

    @QtCore.Slot()
    def _sync_bridge(self):
        ''' request to sync the bridge '''
        # syslog = logging.getLogger("system")
        syslog.info("SIMCONNECT BRIDGE: sync requested")
        if not self.connected:
            # not started or alive
            self.start()


    @property
    def connected(self):
        return self._started and self._alive

    # simconnect library callback
    def client_data_callback_handler(self, pData):
        ''' processes received simconnect data to see if it came from mobiflight '''
        # syslog = logging.getLogger("system")
        client_data = cast(pData, POINTER(SIMCONNECT_RECV_CLIENT_BYTE_DATA)).contents
        #client_data = copy.deepcopy(data)


        #syslog.info(f"client data callback: define id: {client_data.dwDefineID}")
        if client_data.dwRequestID  == kDownlinkRequest:
            # mobiflight core client data received on MobiFlight client registration
            packet = cast(client_data.dwData, POINTER(BRIDGE_PACKET)).contents

            match packet.code:
                case BridgeCommands.SimConnectError:
                    data = packet.data.decode('ascii',errors='replace')
                    data = data.replace('\ufffd','')
                    syslog.error(f"WASM: error: {data}")

                case BridgeCommands.Ping:
                    data = packet.data.decode('ascii',errors='replace')
                    data = data.replace('\ufffd','') # remove junk characters
                    if data == "#pong#":
                        syslog.info(f"SIMCONNECT BRIDGE: received pong alive")
                        if self._alive_thread and self._alive_thread.is_alive():
                            self._connect_in_progress = False
                            self._alive_thread.join() # wait for it to finish
                            self._alive_thread = None
                            self._alive = True
                            self.alive.emit() # report the bridge is alive

                case BridgeCommands.GetNamedVariable:
                    # named variable
                    packet = cast(client_data.dwData, POINTER(BRIDGE_PACKET_DOUBLE)).contents
                    value = packet.data # double
                    #syslog.info(f"SIMCONNECT BRIDGE: received value: {value}")
                    
                case BridgeCommands.GetVariableList:
                    data = packet.data.decode()


                    if data == "#lvar_begin#":
                        self._lvars.clear()
                        self._state = "loading"

                    elif data == "#lvar_end#":
                        self._state = "complete"

                    elif self._state == "loading":
                        self._lvars.append(data)  
                                        
                    if self._state == "complete":
                        thread = threading.Thread(target = lambda: self.lvars_loaded.emit(self._lvars), daemon=False)
                        thread.name = "simconnect bridge"
                        thread.start()
                        self._state = None
                        
                case BridgeCommands.ExecuteCalculatorCode:
                    # mark done executing the command
                    self._wait_event.set()  


                case BridgeCommands.GetAircraftList:
                    # gets aircraft data in the format aircraft_name###livery
                    data = packet.data.decode('ascii',errors='replace')
                    if data == "#ac_begin#":
                        self._aircraft_map.clear()
                        self._state = "loading"

                    elif data == "#ac_end#":
                        self._state = "complete"
                        thread = threading.Thread(target = lambda: self.aircraft_list_loaded.emit(self._aircraft_map), daemon=False)
                        thread.name ="simconnect ac list"
                        thread.start()

                    elif self._state == "loading":
                        splits = data.split("###")
                        aircraft = splits[0]
                        livery = splits[1]
                        if not aircraft in self._aircraft_map:
                            self._aircraft_map[aircraft] = []
                        self._aircraft_map[aircraft].append(livery)
                        



            
            # find the terminating zero

            data = packet.data
            #syslog.info(f"SIMCONNECT BRIDGE: received data: {data}")
            
            


                
    def execute_calculator_code(self, command):
        ''' executes an RPN expression '''
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        #verbose = False
        # if self._wait_event.is_set():
        #     # currently executing another command - ignore
        #     if verbose: syslog.info("execute: already executing")
        #     return
        try:
            id = self._get_next_id() # id is sequential so it's unique for each call and will roundrobin
            data = command.encode("ascii")
                

            packet = BRIDGE_PACKET(id, BridgeCommands.ExecuteCalculatorCode, data)
            packet_pointer = cast(pointer(packet), c_void_p)
            
            if verbose: syslog.info(f"SIMCONNECT BRIDGE: exec calculator code: [{command}]")
            self._wait_event.clear()
            self.sm._dll.SetClientData(
                self.sm._hSimConnect,
                kPublicUplinkArea, 
                kPacketDefinition,
                SIMCONNECT_CLIENT_DATA_REQUEST_FLAG.SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_DEFAULT,
                0, # dwReserved
                kPacketSize, 
                packet_pointer)
                        
            # wait for the event
            # self._wait_event.wait(0.1)
            if verbose: syslog.info(f"SIMCONNECT BRIDGE: {command} sent")
            #self._wait_event.clear()
        except:
            syslog.error(f"SIMCONNECT BRIDGE: error executing calculator code: {command}")

    def get_variable(self, command):
        ''' gets a named variables '''
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        try:
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
            
            if verbose: syslog.info(f"SIMCONNECT BRIDGE: get named variable: {command}")
        except:
            syslog.error(f"SIMCONNECT BRIDGE: error getting named variable: {command}")

    def ping(self):
        ''' sends the ping command '''
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        if self._alive:
            # already alive, ignore
            return
        if not self._connect_in_progress:
            if verbose: syslog.info("SIMCONNECT BRIDGE: handshake initiated...")
            self._connect_in_progress = True
            self._alive_thread = threading.Thread(target = self._ping_runner, daemon=False)
            self._alive_thread.name = "SIMCONNECT wasm ping runner"
            self._alive_thread.start()

    def _ping_runner(self):
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        try:
            while self._connect_in_progress:    
                if verbose: syslog.info(f"SIMCONNECT BRIDGE: (alive thread) send ping request")
                id = self._get_next_id() # id is sequential so it's unique for each call and will roundrobin
                packet = BRIDGE_PACKET(id, BridgeCommands.Ping)
                packet_pointer = cast(pointer(packet), c_void_p)
                self.sm._dll.SetClientData(
                    self.sm._hSimConnect,
                    kPublicUplinkArea, 
                    kPacketDefinition,
                    SIMCONNECT_CLIENT_DATA_REQUEST_FLAG.SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_DEFAULT,
                    0, # dwReserved
                    kPacketSize, 
                    packet_pointer)
                time.sleep(0.1) # give it time to respond

            if verbose:
                if verbose: syslog.info(f"SIMCONNECT BRIDGE: handhake completed")
        except:
            syslog.error(f"SIMCONNECT BRIDGE: error sending ping")
            self._connect_in_progress = False
            self._alive = False


        
    def _request_data(self, bridge_command : BridgeCommands):
        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        try:
            id = self._get_next_id() # id is sequential so it's unique for each call and will roundrobin
            packet = BRIDGE_PACKET(id, bridge_command, b"")
            packet_pointer = cast(pointer(packet), c_void_p)
            self.sm._dll.SetClientData(
                self.sm._hSimConnect,
                kPublicUplinkArea, 
                kPacketDefinition,
                SIMCONNECT_CLIENT_DATA_REQUEST_FLAG.SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_DEFAULT,
                0, # dwReserved
                kPacketSize, 
                packet_pointer)
            syslog.info(f"SIMCONNECT BRIDGE: get bridge data: {bridge_command.name}")
        except:
            syslog.error(f"SIMCONNECT BRIDGE: error getting variable list: {bridge_command.name}")
        

    def get_lvars(self):
        ''' gets the list of lvars from the sim '''
        self._request_data(BridgeCommands.GetVariableList)
            

    def getAircraftList(self):
        ''' gets the list of aircraft and liveries available to the user '''
        self._request_data(BridgeCommands.GetAircraftList)