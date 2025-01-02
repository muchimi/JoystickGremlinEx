
# -*- coding: utf-8; -*-

# Based on original work by Koseng and the MobiFlight team -  (C) EMCS 2024 and other contributors
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
from .Enum import *
import gremlin.config
from .MobiFlight import *
from .SimConnect import SimConnect
from PySide6 import QtWidgets, QtCore, QtGui
import threading

MOBIFLIGHT_MESSAGE_SIZE = 1024 # 1k is the default wasm module message size
MOBIFLIGHT_LVAR_MESSAGE_SIZE = 4096 # 4k is the default for the LVAR receive area
MOBIFLIGHT_STRINGVAR_ID_OFFSET = 10000
MOBIFLIGHT_STRINGVAR_SIZE = 128
MOBIFLIGHT_STRINGVAR_MAX_AMOUNT = 64
MOBIFLIGHT_STRINGVAR_DATA_AREA_SIZE = MOBIFLIGHT_STRINGVAR_SIZE * MOBIFLIGHT_STRINGVAR_MAX_AMOUNT
MOBIFLIGHT_CLIENT = "MobiFlight"
GREMLINEX_CLIENT = "GremlinEx"

class MobiFlightSimVariable:
    def __init__(self, id, name, float_value = None):
        self.id = id
        self.name = name
        self.float_value = float_value
        self.initialized = False
    def __str__(self):
        return f"Id={self.id}, value={self.float_value}, name={self.name}"
    
class MobiFlightClientData:
    ''' holds mobiflight client data '''
    def __init__(self, name : str, sm : SimConnect, offset : UINT = 0):
        self.NAME : str = None
        self.AREA_SIMVAR_ID : int = None
        self.AREA_COMMAND_ID : int = None
        self.AREA_RESPONSE_ID : int = None
        self.AREA_STRINGSIMVAR_ID : int = None
        self.DATA_DEFINITION_ID : int= None
        self.DATA_STRING_DEFINITION_ID : int = None
        self.registered = False # true if the client data areas have been registered
        self._generate(name, sm, offset)
        

    def _generate(self, name : str,  sm : SimConnect, offset : UINT = 0):
        ''' generates a unique client ID set '''
        self.NAME = name
        self.AREA_SIMVAR_ID = sm.new_client_data_id().value
        self.AREA_COMMAND_ID = sm.new_client_data_id().value
        self.AREA_RESPONSE_ID = sm.new_client_data_id().value
        self.AREA_STRINGSIMVAR_ID = sm.new_client_data_id().value
        self.DATA_DEFINITION_ID = sm.new_def_id().value
        self.RESPONSE_OFFSET : UINT = offset

        syslog = logging.getLogger("system")
        syslog.info(f"Simconnect: MobiFlight: create client {self.NAME}:")
        syslog.info(f"\tSimvar: client name {self.NAME}")
        syslog.info(f"\tSimvar: client area {self.AREA_SIMVAR_ID}")
        syslog.info(f"\tStringSimvar: client area {self.AREA_STRINGSIMVAR_ID}")
        syslog.info(f"\tCommand: client area {self.AREA_COMMAND_ID}")
        syslog.info(f"\tResponse: client area {self.AREA_RESPONSE_ID}")

        pass



class MobiFlightManager (QtCore.QObject):
    ''' mobiflight wasm module interface from gremlinEx'''

    lvars_updated = QtCore.Signal(object) # indicates LVARs were updated
    new_client_registered = QtCore.Signal(str) # triggers when the client is registered by MobiFlight, parameter = name of client registered
    core_alive = QtCore.Signal() # triggers when the core client responds to our initial ping
    value_changed = QtCore.Signal(str, float) # triggers when a floating point value is being returned

    def __init__(self, sm, client_name = GREMLINEX_CLIENT):
        super().__init__()
        self.verbose = gremlin.config.Configuration().verbose_mode_simconnect
        if self.verbose:
            self.syslog = logging.getLogger("system")
            self.syslog.info("Simconnect: Mobiflight variable request")
        self.sm = sm
        self.sim_vars = {}
        self.lvars = [] # list of received lvars
        self.sim_var_definition_id_map = {} # maps sim var index key is the definition_id, value is the index in sim_var
        self.sim_var_request_id_map = {} # map sim var id to request ID
        self.sim_var_name_to_id = {}

        # add our dispatch handler to simconnect
        self.sm.register_client_data_handler(self.client_data_callback_handler)

        

        self.CLIENT_NAME = client_name # name of the client registered with the wasm module
        self.core_client = MobiFlightClientData(MOBIFLIGHT_CLIENT, sm) # core client for mobiflight
        self.client = MobiFlightClientData(client_name, sm) # our local client
        self._connected = False # true if mobiflight found and the client registered with mobiflight to process commands
        self._connect_requested = False # true if a connection request is in progress
        self._client_added = False # true if client was added to mobiflight
        self._mobiflight_ok = False # true if mobiflight is installed
        self.response = ""

        self.core_alive.connect(self._core_alive_cb)
        self.new_client_registered.connect(self._client_registered_cb)
        self._command_queue = [] # command queue

    
    def queue_command(self, action):
        if self._connected:
            # run immediately
            action()
        else:
            # queue for later
            self._command_queue.append(action)


    def queue_execute(self):
        ''' executes command queue - this queue executes once the connection with mobiflight wasm is a success'''

        self.syslog.info(f"Simconnect: MobiFlight: queue execution: {len(self._command_queue)} actions found.")
        while self._command_queue:
            action = self._command_queue.pop(0)
            action()

        self.syslog.info("Simconnect: MobiFlight: queue execution complete")


    def add_to_client_data_definition(self, definition_id : int, offset : int, size : int):
        ''' register a client area data definition '''
        if self.verbose:
            self.syslog.info(f"Simconnect: Mobiflight add_to_client_data_definition definition_id={definition_id}, offset={offset}, size={size}")
        err = self.sm._dll.AddToClientDataDefinition(
            self.sm._hSimConnect,
            definition_id, # definition id
            offset, # offset of the data to set 
            size, # size of teh data to set 
            0,  # fEpsilon
            SIMCONNECT_UNUSED) # DatumId
        if not self.sm.IsHR(err, 0):
            self.syslog.error(f"Simconnect: Mobiflight add to client data definition error: {err}")


    
    def requestClientData(self, client_area_id : int, request_id : int, definition_id : int, periodic_flag = SIMCONNECT_CLIENT_DATA_PERIOD.SIMCONNECT_CLIENT_DATA_PERIOD_ON_SET):
        ''' asks simconnect to send us data whenever this data changes '''
        if self.verbose:
            self.syslog.info(f"Simconnect: Mobiflight subscribe_to_data_change data_area_id={client_area_id}, request_id={request_id}, definition_id={definition_id}")
        err = self.sm._dll.RequestClientData(
            self.sm._hSimConnect,
            client_area_id, # Specifies the ID of the client data area.
            request_id, # request ID
            definition_id,  # definition ID
            periodic_flag, # get data when value is set
            SIMCONNECT_CLIENT_DATA_REQUEST_FLAG.SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_CHANGED, # get data on value change
            0, # origin
            0, # interval
            0) # limit
        if not self.sm.IsHR(err, 0):
            self.syslog.error(f"Simconnect: Mobiflight subscribe data error: {err}")



    def sendCommand(self, command: str, client : MobiFlightClientData):
        ''' sends a command to mobi flight via the set client data area '''
        syslog = logging.getLogger("system")
        syslog.info(f"Simconnect: Mobiflight client {client.NAME} send command: {command} ")
        # convert the string to a byte array matching the size of the client data registered with Simconnect
        data_bytes_array = bytearray(command, "ascii")
        # pad if needed
        data_bytes_array.extend(bytearray(MOBIFLIGHT_MESSAGE_SIZE - len(data_bytes_array)))
        data_bytes = bytes(data_bytes_array)
        err = self.sm._dll.SetClientData(
            self.sm._hSimConnect,
            client.AREA_COMMAND_ID, 
            client.DATA_DEFINITION_ID,
            SIMCONNECT_CLIENT_DATA_REQUEST_FLAG.SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_DEFAULT,
            0, # dwReserved
            MOBIFLIGHT_MESSAGE_SIZE, 
            data_bytes)
        if not self.sm.IsHR(err, 0):
            self.syslog.error(f"Simconnect: Mobiflight send command error: {err}")

    def dummyCommand(self, client : MobiFlightClientData):
        ''' sends the dummy command to MobiFlight'''
        if not self.sm.ok:
            return
        self.sendCommand("MF.DummyCmd", client)

    def stop(self, client : MobiFlightClientData):
        ''' sends the clear command to MobiFlight'''
        self.queue_command(lambda : self.sendCommand("MF.SimVars.Clear", client) )
        

    def getLVarList(self, client : MobiFlightClientData):
        ''' sends the clear command to MobiFlight'''
        self.queue_command(lambda : self.sendCommand("MF.LVars.List", client))
        

    def ping(self, client : MobiFlightClientData):
        if not self.sm.ok:
            return
        self.sendCommand("MF.Ping", client)

    def setConfig(self, config_name : str, config_value : str, client : MobiFlightClientData):
        ''' sends configuration data '''
        if not self.sm.ok:
            return
        command = f"MF.Config.{config_name}.Set.{config_value}"
        self.sendCommand(command, client)

    def addAdditionalClient(self, client_name: str, client : MobiFlightClientData):
        if not self.sm.ok:
            return
        command = f"MF.Clients.Add.{client_name}"
        self.sendCommand(command, client)

    def setSimVar(self, sim_var_code : str, client : MobiFlightClientData):
        if not self.sm.ok:
            return
        command = f"MF.SimVars.Set.{sim_var_code}"
        self.sendCommand(command, client)
        self.dummyCommand(client)

    def addSimVar(self, sim_var_name : str, client : MobiFlightClientData):
        if not self.sm.ok:
            return
        command = f"MF.SimVars.Add.{sim_var_name}"
        self.sendCommand(command, client)

    def addStringSimVar(self, sim_var_name : str, client : MobiFlightClientData):
        if not self.sm.ok:
            return
        command = f"MF.SimVars.AddString.{sim_var_name}"
        self.sendCommand(command, client)

    def initializeClientDataAreas(self, client : MobiFlightClientData):
        ''' initialize the shared client area with the mobiflight wasm module '''
        if client.registered:
            # already done
            self.syslog.warning(f"Simconnect: MobiFlight: client {client.NAME} data areas already registered.")
            return 

        create_area = client.NAME != MOBIFLIGHT_CLIENT # only create data areas if not the core client registering
        self.syslog.warning(f"Simconnect: MobiFlight: register client {client.NAME} data areas")
        self.syslog.info(f"\tSimvar: client name {client.NAME}")
        self.syslog.info(f"\tSimvar: client area {client.AREA_SIMVAR_ID}")
        self.syslog.info(f"\tStringSimvar: client area {client.AREA_STRINGSIMVAR_ID}")
        self.syslog.info(f"\tCommand: client area {client.AREA_COMMAND_ID}")
        self.syslog.info(f"\tResponse: client area {client.AREA_RESPONSE_ID}")

        
        # register client data area for receiving LVARS
        FLAG_DEFAULT = SIMCONNECT_CREATE_CLIENT_DATA_FLAG.SIMCONNECT_CREATE_CLIENT_DATA_FLAG_DEFAULT
        err = self.sm._dll.MapClientDataNameToID(self.sm._hSimConnect, f"{client.NAME}.LVars".encode(), client.AREA_SIMVAR_ID)
        if not self.sm.IsHR(err, 0):
            self.syslog.error(f"Error mapping lvars: {err}")
        if create_area:
            self.sm._dll.CreateClientData(self.sm._hSimConnect,
                                        client.AREA_SIMVAR_ID,
                                        MOBIFLIGHT_LVAR_MESSAGE_SIZE,
                                        FLAG_DEFAULT)
            if not self.sm.IsHR(err, 0):
                self.syslog.info(f"Error create data lvars: {err}")

        # register client data area for sending commands
        err = self.sm._dll.MapClientDataNameToID(self.sm._hSimConnect, f"{client.NAME}.Command".encode(), client.AREA_COMMAND_ID)
        if not self.sm.IsHR(err, 0):
            self.syslog.error(f"Error mapping command: {err}")
        if create_area:
            self.sm._dll.CreateClientData(self.sm._hSimConnect,
                                        client.AREA_COMMAND_ID,
                                        MOBIFLIGHT_MESSAGE_SIZE,
                                        FLAG_DEFAULT)
            if not self.sm.IsHR(err, 0):
                self.syslog.info(f"Error create command: {err}")
        
        # register client data area for receiving responses
        err = self.sm._dll.MapClientDataNameToID(self.sm._hSimConnect, f"{client.NAME}.Response".encode(), client.AREA_RESPONSE_ID)
        if not self.sm.IsHR(err, 0):
            self.syslog.error(f"Error mmapping response: {err}")
        if create_area:
            self.sm._dll.CreateClientData(self.sm._hSimConnect,
                                        client.AREA_RESPONSE_ID,
                                        MOBIFLIGHT_MESSAGE_SIZE,
                                        FLAG_DEFAULT)
            if not self.sm.IsHR(err, 0):
                self.syslog.info(f"Error creating response lvars: {err}")


        # register client data area for receiving string vars
        err = self.sm._dll.MapClientDataNameToID(self.sm._hSimConnect, f"{client.NAME}.StringVars".encode(), client.AREA_STRINGSIMVAR_ID)
        if not self.sm.IsHR(err, 0):
            self.syslog.error(f"Error mmapping string simvar: {err}")
        if create_area:
            self.sm._dll.CreateClientData(self.sm._hSimConnect,
                                        client.AREA_STRINGSIMVAR_ID,
                                        MOBIFLIGHT_STRINGVAR_DATA_AREA_SIZE,
                                        FLAG_DEFAULT)
            if not self.sm.IsHR(err, 0):
                self.syslog.info(f"Error creating string simvar: {err}")

            
        # register our client response data area with simconnect
        self.add_to_client_data_definition(client.DATA_DEFINITION_ID, client.RESPONSE_OFFSET, MOBIFLIGHT_MESSAGE_SIZE)

        # ask for this data to update whenever it changes (set by MobiFlight)
        self.requestClientData(client.AREA_RESPONSE_ID, client.DATA_DEFINITION_ID, client.DATA_DEFINITION_ID)

        # indicate the client is now registered
        client.registered = True

        self.syslog.info(f"Client {client.NAME} data areas registered...")
        


    def start(self):
        ''' requests connection to MobiFlight wasm module '''
        if self._connected or self._connect_requested:
            return
        self._connect_requested = True
        self.initializeClientDataAreas(self.core_client)
        self.initializeClientDataAreas(self.client)

        # wake mobiflight up
        self.ping(self.core_client) # send an "Are you there" ping - the pong triggers the next step
        self.dummyCommand(self.core_client)

    def stop(self):
        ''' disconnect '''
        self.clear_sim_variables()
        

    @QtCore.Slot()
    def _core_alive_cb(self):
        # core client responded alive - add our client
        self.syslog.info(f"Simconnect: MobiFlight: core alive event - registering client {self.client.NAME} with MobiFlight WASM")
        

    @QtCore.Slot(str)
    def _client_registered_cb(self, client_name):
        ''' triggered when MobiFlight registered our client '''
        self._connected = True
        self.syslog.info(f"Simconnect: MobiFlight: client connected {client_name}")

        # execute any pending command waiting for the handshake
        self.queue_execute()



    @property
    def connected(self)->bool:
        ''' true if we are connected to mobiflight wasm '''
        return self._connected



    # simconnect library callback
    def client_data_callback_handler(self, pData):
        ''' processes received simconnect data to see if it came from mobiflight '''
        client_data = cast(pData, POINTER(SIMCONNECT_RECV_CLIENT_DATA)).contents
        syslog.info(f"client data callback: define id: {client_data.dwDefineID}")
        if client_data.dwDefineID == self.core_client.DATA_DEFINITION_ID:
            # mobiflight core client data received on MobiFlight client registration
            client_data = cast(pData, POINTER(SIMCONNECT_RECV_CLIENT_BYTE_DATA)).contents
            # find the terminating zero
            data = string_at(client_data.dwData).decode()
            syslog.info(f"core client: flags: {client_data.dwFlags} entry number: {client_data.dwentrynumber}  out of: {client_data.dwoutof} Define count: {client_data.dwDefineCount} data: {data}")
            self._mobiflight_ok = True
            if self.client.NAME in data:
                thread = threading.Thread(target = lambda : self.new_client_registered.emit(self.client.NAME))
                thread.start()
                

            elif data == "MF.Pong":
                # received are your there response
                if not self._client_added:
                    self._client_added = True
                    self.addAdditionalClient(self.client.NAME, self.core_client)

                self.syslog.info("Simconnect: MobiFlight: core pong received")
                



        elif client_data.dwDefineID == self.client.DATA_DEFINITION_ID:
            # client LVAR data being returned
            client_data = cast(pData, POINTER(SIMCONNECT_RECV_CLIENT_BYTE_DATA)).contents
            # find the terminating zero
            data = string_at(client_data.dwData).decode()
            syslog.info(f"client: flags: {client_data.dwFlags} entry number: {client_data.dwentrynumber}  out of: {client_data.dwoutof} Define count: {client_data.dwDefineCount} data: {data}")
            
            match data:
                case "MF.Pong":
                    self.syslog.info("Simconnect: MobiFlight: client pong received")
                case "MF.LVars.List.Start":
                    self.response = "LVars.List.Receiving"
                    self.lvars.clear()
                case "MF.LVars.List.End":
                    self.response = "LVars.List.Completed"
                    self.lvars.sort()
                    self.syslog.info(f"Simconnect: MobiFlight: received {len(self.lvars)} lvars")
                    for lvar in self.lvars:
                        self.syslog.info(f"\t{lvar}")
                    self.lvars_updated.emit(self.lvars)

            if self.response == "LVars.List.Receiving":
                # store the received LVAR
                self.lvars.append(data)

        elif client_data.dwDefineID in self.sim_vars:
            # floating point data received from MobiFlight
            id = client_data.dwDefineID
            data_bytes = struct.pack("I", client_data.dwData[0])
            float_data = struct.unpack('<f', data_bytes)[0]   # unpack delivers a tuple -> [0]
            value = round(float_data, 5)
            name = self.sim_vars[id].name
            self.sim_vars[id].float_value = value
            self.syslog.info(f"Simconnect: MobiFlight: received floating point value: {id} {self.sim_vars[id].name}:{value:0.5f}")
            self.value_changed.emit(name, value)

            
        else:
            if self.verbose:
                self.syslog.warning(f"Simconnect: Mobiflight client_data_callback_handler DefinitionID {client_data.dwDefineID} not found!")


    def getFloat(self, variable_string, client : MobiFlightClientData):
        ''' gets a floating point simvar value via an RPN execution code  '''
        if not self._connected:
            self.syslog.warning(f"Simconnect: Mobiflight: getFloat() client not connected")
            return
        if variable_string not in self.sim_var_name_to_id:
            # add new floating point variable definition to the list
            '''
            MF.SimVars.Add. 
            The "SimVars.Add." command needs to be extended with a gauge calculator script for reading a variable.
            Each added variable needs 4 reserved bytes to return its float value in the LVars channel.
            The bytes are allocated in the order of the LVars being added.
            The first variable starts at offset 0, the second at offset 4, the third at offset 8 and so on.
            To access each value, the external SimConnect clients needs a unique DataDefinitionId for each memory segment.
            It is recommended to start with ID 1000.
            '''
            id = len(self.sim_vars) + MOBIFLIGHT_STRINGVAR_ID_OFFSET # default ID starts at 10000
            self.sim_vars[id] = MobiFlightSimVariable(id, variable_string)
            self.sim_var_name_to_id[variable_string] = id # map of variable name to its registered simconnect ID
            # subscribe to variable data change
            offset = (id-MOBIFLIGHT_STRINGVAR_ID_OFFSET)*sizeof(FLOAT)
            self.add_to_client_data_definition(id, offset, sizeof(FLOAT))
            self.sendCommand("MF.SimVars.Add." + variable_string, client)

        # determine id and return value
        variable_id = self.sim_var_name_to_id[variable_string]
        sim_var = self.sim_vars[variable_id]
        wait_counter = 0
        while wait_counter < 50: # wait max 500ms
            if sim_var.float_value is None:
                sleep(0.01) # wait 10ms
                wait_counter = wait_counter + 1
            else:
                break
        if sim_var.float_value is None and sim_var.initialized:
            sim_var.float_value = 0.0
        if self.verbose:
            self.syslog.debug(f"get {variable_string}. wait_counter={wait_counter}, Return={sim_var.float_value}")
        return sim_var.float_value


    def set(self, variable_string: str, client : MobiFlightClientData):
        if self._connected:
            self.sendCommand(f"MF.SimVars.Set.{variable_string}", client)
        else:
            self.start()
            self.queue_command(lambda: self.sendCommand(f"MF.SimVars.Set.{variable_string}", client))
        
        
        
    def requestLvars(self):
        ''' requests LVARs from MobiFlight '''
        if self._connected:
            self.syslog.info("Get LVARS requested")
            self.getLVarList(self.client)
            self.dummyCommand(self.client)
            self.getFloat("(A:GROUND ALTITUDE,Meters)", self.client)

        else:
            self.start()
            self.queue_command(lambda: self.getLVarList(self.client))
            self.queue_command(lambda: self.dummyCommand(self.client))
            self.queue_command(lambda: self.getFloat("(A:GROUND ALTITUDE,Meters)", self.client))

            
            
    def clear_sim_variables(self):
        ''' removes sim variables '''
        if self.verbose:
            self.syslog.info("clear_sim_variables")
        self.sim_vars.clear()
        self.sim_var_name_to_id.clear()
        self.sim_var_definition_id_map.clear()
        self.sim_var_request_id_map.clear()
        self.sendCommand("MF.SimVars.Clear", self.client)
        

       