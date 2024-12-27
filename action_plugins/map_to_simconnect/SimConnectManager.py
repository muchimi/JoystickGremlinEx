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

from __future__ import annotations
import os
import lxml
from lxml import etree

from PySide6 import QtWidgets, QtCore, QtGui

import gremlin.base_classes
import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
import gremlin.macro
import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.ui.input_item
import gremlin.util
from .SimConnect import *
from .SimConnect.SimConnect import *
from .SimConnect.Enum import *
from gremlin.singleton_decorator import SingletonDecorator
import enum
import time
import threading


syslog = logging.getLogger("system")

class DataThreadingEvent(threading.Event):
    ''' a threading event that can support a data value'''
    def __init__(self):
        super().__init__()
        self.data = None


class SimconnectCommand(enum.IntEnum):
    ''' internal commands '''
    SyncAircraftMode = auto() # synchronizes the profile mode with the current aircraft 

    @staticmethod
    def to_enum(value):
        return _simconnect_command_to_enum[value]
    
    @staticmethod
    def to_string(value):
        return _simconnect_command_to_string[value]
    
    @staticmethod
    def to_display_name(value):
        return _simconnect_command_description[value]
   

_simconnect_command_to_enum = {
    "sync_aicraft" : SimconnectCommand.SyncAircraftMode,
}

_simconnect_command_description = {
    SimconnectCommand.SyncAircraftMode: "Synchronize profile mode with aircraft"
}

_simconnect_command_to_string = {
    SimconnectCommand.SyncAircraftMode: "sync_aircraft",
}


''' full axis range commands -16883 to + 16383 '''
_simconnect_full_range = [
                        "AXIS_THROTTLE_SET",
                        "AXIS_THROTTLE1_SET",
                        "AXIS_THROTTLE2_SET",
                        "AXIS_THROTTLE3_SET",
                        "AXIS_THROTTLE4_SET",
                        "AXIS_LEFT_BRAKE_SET",
                        "AXIS_RIGHT_BRAKE_SET",
                        "AXIS_MIXTURE_SET",
                        "AXIS_MIXTURE1_SET",
                        "AXIS_MIXTURE2_SET",
                        "AXIS_MIXTURE3_SET",
                        "AXIS_MIXTURE4_SET",
                        "AXIS_PROPELLER_SET",
                        "AXIS_PROPELLER1_SET",
                        "AXIS_PROPELLER2_SET",
                        "AXIS_PROPELLER3_SET",
                        "AXIS_PROPELLER4_SET",
                        "AXIS_ELEVATOR_SET",
                        "AXIS_AILERONS_SET",
                        "AXIS_RUDDER_SET",
                        "AXIS_ELEV_TRIM_SET",
                        "AXIS_SPOILER_SET",
                        "AXIS_FLAPS_SET",
                        "AXIS_SLEW_AHEAD_SET",
                        "AXIS_SLEW_SIDEWAYS_SET",
                        "AXIS_SLEW_HEADING_SET",
                        "AXIS_SLEW_ALT_SET",
                        "AXIS_SLEW_BANK_SET",
                        "AXIS_SLEW_PITCH_SET",
                        "AXIS_PAN_PITCH",
                        "AXIS_PAN_HEADING",
                        "AXIS_PAN_TILT",
]

''' half axis range commands 0..16384'''
_simconnect_half_range = ["THROTTLE1_SET",
                      "THROTTLE2_SET",
                      "THROTTLE3_SET",
                      "THROTTLE4_SET",
                      "AXIS_THROTTLE_SET",
                      "THROTTLE_SET",
                      "MIXTURE1_SET",
                      "MIXTURE2_SET",
                      "MIXTURE3_SET",
                      "MIXTURE4_SET",
                      "PROP_PITCH1_SET",
                      "PROP_PITCH2_SET",
                      "PROP_PITCH3_SET",
                      "PROP_PITCH4_SET",
                      "SPOILERS_SET",
                      "FLAPS_SET",
                      "ELEVATOR_TRIM_SET",
                      ]

''' angle range commands 0..360'''
_simconnect_angle_range = ["VOR1_SET",
                           "VOR2_SET",
                           "ADF_CARD_SET",
                           "KEY_TUG_HEADING",
                           ]

''' EGT range comamnds 0..32767 '''
_simconnect_egt_range = ["EGT1_SET",
                         "EGT2_SET",
                         "EGT3_SET",
                         "EGT4_SET",
                         "EGT_SET"
]

class SimConnectActionMode(enum.Enum):
    ''' simconnect action output mode  '''
    NotSet = 0,
    Ranged = 1, # output varies with input axis
    Trigger = 2, # output is a trigger (no value sent)
    SetValue = 3, # output sets a number value
    Gated = 4, # output of axis is gated - the position of the axis is not linear
    GetValue = 4, # gets a value from simconnect

    @staticmethod
    def to_string(value):
        if value in _simconnect_action_mode_to_string_lookup.keys():
            return _simconnect_action_mode_to_string_lookup[value]
        return "none"
    @staticmethod
    def to_enum(value, validate = True):
        if value is None:
            return SimConnectActionMode.NotSet
        if value in _simconnect_action_mode_to_enum_lookup.keys():
            return _simconnect_action_mode_to_enum_lookup[value]
        if validate:
            raise gremlin.error.GremlinError(f"Invalid type in action mode lookup: {value}")
        return SimConnectActionMode.NotSet

    @staticmethod
    def to_display(value):
        return _simconnect_action_mode_to_display_lookup[value]

_simconnect_action_mode_to_display_lookup = {
    SimConnectActionMode.NotSet: "N/A",
    SimConnectActionMode.Gated: "Gated",
    SimConnectActionMode.Ranged: "Ranged",
    SimConnectActionMode.Trigger: "Trigger",
    SimConnectActionMode.SetValue: "SetValue",
    SimConnectActionMode.GetValue: "GetValue"
}

class SimConnectTriggerMode(enum.Enum):
    ''' trigger modes for boolean actions '''
    NotSet = 0 # not set
    TurnOn = 1 # enable or turn on
    TurnOff = 2 # disable or turn off
    Toggle = 3 # toggle
    NoOp = 4 # send nothing (trigger command only)

    @staticmethod
    def to_string(value):
        if value in _trigger_mode_to_string.keys():
            return _trigger_mode_to_string[value]
        return "none"
    @staticmethod
    def to_enum(value, validate = True):
        if value in _trigger_mode_to_enum.keys():
            return _trigger_mode_to_enum[value]
        if validate:
            raise gremlin.error.GremlinError(f"Invalid type in trigger lookup: {value}")
        return SimConnectTriggerMode.NotSet

    @staticmethod
    def to_display(value):
        return _trigger_mode_to_display[value]

_trigger_mode_to_string = {
    SimConnectTriggerMode.NotSet : "none",
    SimConnectTriggerMode.Toggle : "toggle",
    SimConnectTriggerMode.TurnOff : "off",
    SimConnectTriggerMode.TurnOn : "on",
    SimConnectTriggerMode.NoOp: "noop"
}


_trigger_mode_to_display = {
    SimConnectTriggerMode.NotSet : "N/A",
    SimConnectTriggerMode.Toggle : "Toggle",
    SimConnectTriggerMode.TurnOff : "Off",
    SimConnectTriggerMode.TurnOn : "On",
    SimConnectTriggerMode.NoOp: "NoOp"

}

_trigger_mode_to_enum = {
    "none" : SimConnectTriggerMode.NotSet,
    "toggle" : SimConnectTriggerMode.Toggle,
    "off" : SimConnectTriggerMode.TurnOff,
    "on" : SimConnectTriggerMode.TurnOn,
    "noop" : SimConnectTriggerMode.NoOp
}





class OutputType(enum.Enum):
    ''' output data type '''
    NotSet = 0
    FloatNumber = 1
    IntNumber = 2



class SimConnectCommandType(enum.Enum):
    NotSet = 0
    Event = 1 # request event
    Request = 2 # request data
    LVar = 3 # set lvar
    AVar = 4 # set avar
    SimVar = 5 # set simvar

    @staticmethod
    def from_string(value):
        value = value.lower()
        if value in _command_type_to_string_map.keys():
            return _command_type_to_string_map[value]
        return None



_command_type_to_string_map = {
    "notset": SimConnectCommandType.NotSet,
    "event": SimConnectCommandType.Event,
    "request" : SimConnectCommandType.Request,
    "lvar": SimConnectCommandType.LVar,
    "avar": SimConnectCommandType.AVar,
    "simvar" : SimConnectCommandType.SimVar
}









_simconnect_action_mode_to_string_lookup = {
    SimConnectActionMode.NotSet : "none",
    SimConnectActionMode.Ranged : "ranged",
    SimConnectActionMode.Trigger : "trigger",
    SimConnectActionMode.SetValue : "value",
    SimConnectActionMode.Gated : "gated",
}

_simconnect_action_mode_to_enum_lookup = {
    "none" : SimConnectActionMode.NotSet,
    "ranged" : SimConnectActionMode.Ranged,
    "trigger" : SimConnectActionMode.Trigger,
    "value" :SimConnectActionMode.SetValue ,
    "gated" : SimConnectActionMode.Gated,
}

class SimConnectEventCategory(enum.Enum):
    ''' command categories for events '''
    NotSet = 0,
    Engine = 1,
    FlightControls = 2,
    AutoPilot = 3,
    FuelSystem = 4,
    FuelSelection = 5,
    Instruments = 6,
    Lights = 7,
    Failures = 8,
    MiscellaneousSystems = 9,
    NoseWheelSteering = 10,
    CabinPressure = 11,
    Catapult = 12,
    Helicopter = 13,
    SlingsAndHoists = 14,
    SlewSystem = 15,
    ViewSystem = 16,
    FreezingPosition = 17,
    MissionKeys = 18,
    ATC = 19,
    Multiplayer = 20

    @staticmethod
    def to_string(value):
        try:
            return _simconnect_event_category_to_string_lookup[value]
        except KeyError:
            raise gremlin.error.GremlinError(f"Invalid type in lookup: {value}")

    @staticmethod
    def to_enum(value, validate = True):
        if value in _simconnect_event_category_to_enum_lookup.keys():
            return _simconnect_event_category_to_enum_lookup[value]
        if validate:
            raise gremlin.error.GremlinError(f"Invalid type in lookup: {value}")
        return SimConnectEventCategory.NotSet

    @staticmethod
    def to_list():
        ''' generates all categories as a list '''
        return [item for item in SimConnectEventCategory]

    @staticmethod
    def to_list_tuple():
        return [(SimConnectEventCategory.to_string(item), item) for item in SimConnectEventCategory]


_simconnect_event_category_to_string_lookup = {
    SimConnectEventCategory.NotSet : "None",
    SimConnectEventCategory.Engine : "Engine",
    SimConnectEventCategory.FlightControls : "Flight Controls",
    SimConnectEventCategory.AutoPilot : "Autopilot",
    SimConnectEventCategory.FuelSystem : "Fuel System",
    SimConnectEventCategory.FuelSelection : "Fuel Selection",
    SimConnectEventCategory.Instruments : "Instruments",
    SimConnectEventCategory.Lights : "Lights",
    SimConnectEventCategory.Failures: "Failures",
    SimConnectEventCategory.MiscellaneousSystems: "Miscellaneous Systems",
    SimConnectEventCategory.NoseWheelSteering: "Nosewheel Steering",
    SimConnectEventCategory.CabinPressure : "Cabin Pressure",
    SimConnectEventCategory.Catapult : "Catapult",
    SimConnectEventCategory.Helicopter : "Helicopter",
    SimConnectEventCategory.SlingsAndHoists : "Slings and Hoists",
    SimConnectEventCategory.SlewSystem : "Slew System",
    SimConnectEventCategory.ViewSystem : "View System",
    SimConnectEventCategory.FreezingPosition : "Freezing Position",
    SimConnectEventCategory.MissionKeys : "Mission Keys",
    SimConnectEventCategory.ATC : "ATC",
    SimConnectEventCategory.Multiplayer :"Multiplayer",
}

_simconnect_event_category_to_enum_lookup = {
    "None" : SimConnectEventCategory.NotSet,
    "Engine" :SimConnectEventCategory.Engine  ,
    "Flight Controls" : SimConnectEventCategory.FlightControls,
    "Autopilot" : SimConnectEventCategory.AutoPilot,
    "Fuel System" : SimConnectEventCategory.FuelSystem,
    "Fuel Selection" : SimConnectEventCategory.FuelSelection,
    "Instruments" : SimConnectEventCategory.Instruments,
    "Lights" : SimConnectEventCategory.Lights,
    "Failures" : SimConnectEventCategory.Failures,
    "Miscellaneous Systems" : SimConnectEventCategory.MiscellaneousSystems,
    "Nosewheel Steering" : SimConnectEventCategory.NoseWheelSteering,
    "Cabin Pressure" : SimConnectEventCategory.CabinPressure,
    "Catapult" : SimConnectEventCategory.Catapult,
    "Helicopter" : SimConnectEventCategory.Helicopter,
    "Slings and Hoists" : SimConnectEventCategory.SlingsAndHoists,
    "Slew System" : SimConnectEventCategory.SlewSystem,
    "View System" : SimConnectEventCategory.ViewSystem,
    "Freezing Position" : SimConnectEventCategory.FreezingPosition,
    "Mission Keys" : SimConnectEventCategory.MissionKeys,
    "ATC" : SimConnectEventCategory.ATC ,
    "Multiplayer" : SimConnectEventCategory.Multiplayer
}







@SingletonDecorator
class SimConnectManager(QtCore.QObject):
    ''' holds simconnect data and manages simconnect '''

    sim_aircraft_loaded = QtCore.Signal(str, str, str) # fires when aircraft title changes (param folder, name, title)
    sim_start = QtCore.Signal() # fires when the sim starts
    sim_stop = QtCore.Signal() # fires when the sim stops
    sim_running = QtCore.Signal(bool) # fires when the sim is running
    sim_paused = QtCore.Signal(bool) # fires when sim is paused or unpaused (state = pause state)
    
    
    sim_state = QtCore.Signal(int, float, str) # fires when sim state data changes (depends on the state )
    _aircraft_loaded_internal = QtCore.Signal(str, str) # fires when aircraft (name, title)

    def __init__(self) -> None:
        ''' manages simconnect connections and interactions 
        
        :param handler: handler that responds to simconnect events
        :param force_update: flag to update the default data if it has been modified
        
        '''
        QtCore.QObject.__init__(self)

        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self._shutdown) # trap application shutdown

        self.verbose = gremlin.config.Configuration().verbose_mode_simconnect

        self._sm = None

        handler = SimConnectEventHandler()
        
        sm = SimConnect(handler, auto_connect = False)
        self._sm : SimConnect = sm

        handler.simconnect_aircraft_loaded.connect(self._aicraft_loaded_cb)
        handler.simconnect_connected.connect(self._connected_cb)
        handler.simconnect_disconnected.connect(self._disconnected_cb)
        handler.simconnect_sim_paused.connect(self._sim_paused_cb)
        # handler.simconnect_sim_paused.connect(self._paused)
        # handler.simconnect_sim_unpaused.connect(self._unpaused)
        handler.simconnect_sim_running.connect(self._running_cb)
        handler.simconnect_sim_start.connect(self._start_cb)
        handler.simconnect_sim_stop.connect(self._stop_cb)
        

        self._aircraft_events = AircraftEvents(self._sm)
        self._aircraft_requests = AircraftRequests(self._sm)
        self._aircraft_loaded_internal.connect(self._aircraft_loaded_internal_cb)
        


        self._aircraft_tile = None # current title from aircraft.cfg
        self._aircraft_name = None # current name from aicraft cfg path
        self._simvars_xml =  os.path.join(gremlin.util.userprofile_path(), "simconnect_simvars.xml")
        self._lvars_xml = os.path.join(gremlin.util.userprofile_path(), "simconnect_lvars.xml")


        self._connect_attempts = 3 # number of connection attempts before giving up


        self._is_started = False
        self._is_paused = False
        self._is_connected = False
        self._is_running = False
        self._aircraft_folder = None
        self._aircraft_title = None

        self._registered_feed_blocks = {}
        self._registered_requests = {}
        self._registered_events = {}

        # load simconnect data
        self.reload()

        # load internal commands
        self.load_internal()

    @QtCore.Slot()
    def _shutdown(self):
        ''' application shutdown '''
        syslog.info("SIMCONNECT: shutdown")
        self.sim_disconnect()




    def load_internal(self):
        ''' loads GremlinEx simconnect internal commands '''


    def reload(self, force_update = False):
                # if the data file doesn't exist, create it in the user's profile folder from the built-in data

        # list of all commands
        self._commands = []

        # list of command blocks
        self._block_map = {}

        



                
        if force_update and os.path.isfile(self._simvars_xml):
            os.unlink(self._simvars_xml)

        if not os.path.isfile(self._simvars_xml):
            self._write_default_xml(self._simvars_xml)


        self._block_map = {}

        # load the data - including any user modifications/additions
        if os.path.isfile(self._simvars_xml):
            self._load_xml(self._simvars_xml)

        # load any LVAR definitions defined by the user
        if not os.path.isfile(self._lvars_xml):
            # create an lvar sample file
            xml = '''<?xml version='1.0' encoding='UTF-8'?>
<commands>
	<command value="L:A32NX_FCU_EFIS_L_DISPLAY_BARO_MODE" type="lvar" datatype="int" units="Number" category="none" settable="true" axis="false" indexed="false">
		<description value="Flybywire A320 neo set left FCU baro position STD 0 QNH 1 QFE 2"/> 
	</command>
	<command value="L:A32NX_FCU_EFIS_R_DISPLAY_BARO_MODE" type="lvar" datatype="int" units="Number" category="none" settable="true" axis="false" indexed="false">
		<description value="Flybywire A320 neo set right FCU baro position STD 0 QNH 1 QFE 2"/> 
	</command>
</commands>'''
            try:
                with open(self._lvars_xml,"w") as f:
                    f.write(xml)
                    f.flush()
            except:
                syslog.warning(f"Unable to write sample LVAR file to {self._lvars_xml}")
        if os.path.isfile(self._lvars_xml):
            self._load_xml(self._lvars_xml)



        


        if len(self._block_map) > 0:
            # process lists
            #b = SimConnectBlock
            self._commands = [b.command for b in self._block_map.values()]
            self._commands.sort()



    def _register_feed(self, command):
        if not command in self._registered_feed_blocks:
            block = SimConnectBlock()
            block.command = command
            block.command_type = SimConnectCommandType.Request
            block.is_periodic = True
            self._registered_feed_blocks[command] = block
            
    def _enable_feed(self):
        ''' enables the data feed '''
        block : SimConnectBlock
        for block in self._registered_feed_blocks.values():
            block.execute()

    def _disable_feed(self):
        ''' disable the data feed '''
        block : SimConnectBlock
        for block in self._registered_feed_blocks.values():
            block.stop()
        self._registered_feed_blocks = {}

    def RegisterFeed(self, command):
        ''' registers a data feed '''
        self._register_feed(command)

    def _init_feed(self):
        ''' setup the default data feed events, if any '''
        pass
        # self._register_feed("AIRSPEED_INDICATED")
        # self._register_feed("PLANE_ALT_ABOVE_GROUND")
        # self._register_feed("BRAKE_PARKING_INDICATOR")

    def setFeedEnabled(self, enabled):
        ''' enables or disables data feed '''
        if enabled:
            self._init_feed()
            self._enable_feed()
        else:
            self._disable_feed()

    def registerRequest(self, command, datatype, settable : bool = False) -> Request:
        ''' registers a request '''

        # see if the request is already registered
        block = self.block(command)
        if block:
            # found it, use that one
            return block.request

        s_command, b_command = gremlin.util.to_byte_string(command)
        key = s_command.casefold()
        s_datatype, b_datatype = gremlin.util.to_byte_string(datatype)
        if not key in self._registered_requests:
            request = Request((b_command, b_datatype), self.sm, settable)
            request._ensure_def()
            self._registered_requests[key] = request
        
        return self._registered_requests[key]
    
            

    def setSimvar(self, command, datatype, value):
        ''' sets a simvar without using a data block '''
        request = self.registerRequest(command, datatype, True)
        request.value = value
        request.transmit()

    def sendEvent(self, command):
        ''' sends an event to Simconnect '''
        if command in self._block_map:
            block = self._block_map[command]
            syslog.info(f"Simconnect: send Event {command}")
            return block.execute(1)
        syslog.error(f"Simconnect: event not found: {command}")
        

    @QtCore.Slot()
    def _connected_cb(self):
        self._is_connected = True
        if self.verbose:
            syslog.info(f"Simconnect Event: connected")

        self.setFeedEnabled(True)

    @QtCore.Slot()
    def _disconnected_cb(self):
        self._is_connected = False
        if self.verbose:
            syslog.info(f"Simconnect Event: disconnected")

        self.setFeedEnabled(False)



    @QtCore.Slot(bool)
    def _paused_state_cb(self, state):
        self._is_paused = state
        self.sim_paused.emit(state)

    @QtCore.Slot()
    def _paused_cb(self):
        self._is_paused = True
        if self.verbose:
            syslog.info(f"Simconnect Event: paused")

    @QtCore.Slot()
    def _unpaused_cb(self):
        if self.verbose:
            self._is_paused = False
            syslog.info(f"Simconnect Event: unpaused")

    @QtCore.Slot()
    def _start_cb(self):
        if self.verbose:
            syslog.info(f"Simconnect Event: started")
            self._is_started = True
            self.sim_start.emit()
            # update the aircraft
            self.request_loaded_aircraft()

    @QtCore.Slot()
    def _stop_cb(self):
        if self.verbose:
            syslog.info(f"Simconnect Event: stopped")
            self._is_started = False
            self.sim_stop.emit()

    @QtCore.Slot(bool)
    def _running_cb(self, state: bool):
        if self.verbose:
            syslog.info(f"Simconnect Event: running: {state}")
            self._is_running = state
            self.sim_running.emit(state)
            if state:
                self.sim_start.emit()
            else:
                self.sim_stop.emit()


    @property
    def is_connected(self):
        return self._is_connected

    @property
    def is_started(self):
        return self._is_started
    
    @property
    def is_paused(self):
        return self._is_paused
    
    @property
    def current_aircraft_title(self):
        ''' currently loaded aircraft - TITLE from the aircraft.cfg file '''
        return self._aircraft_tile
    
    @property
    def current_aircraft_sim_name(self):
        ''' currently loaded aircraft - TITLE from the aircraft.cfg file '''
        return self._aircraft_name
    
    @property
    def current_aircraft_folder(self):
        ''' returns the path to the currently loaded folder '''
        return self._aircraft_folder    


    @property
    def is_running(self):
        ''' true if the sim state is running '''
        return self._is_running

    def _sim_paused_cb(self, arg):
        self._is_paused = arg

    def _sim_running_cb(self, state):
        self._is_running = state


    def _aicraft_loaded_cb(self, folder, name):
        ''' called when a new aircraft is loaded '''
        if folder != self._aircraft_folder:
            self._aircraft_folder = folder
            self._aircraft_name = name
            self._aircraft_loaded_internal.emit(folder, name)

    def _state_data_cb(self, int_data, float_data, str_data):
        ''' occurs when state data is requested '''
        if gremlin.util.is_binary_string(str_data):
            str_data = str_data.decode('utf-8')
        str_data = str_data.casefold()
        if "aircraft.cfg" in str_data:
            self._aircraft_folder = str_data
            #self.sim_aircraft_loaded.emit(str_data,None)

        self.sim_state.emit(int_data, float_data, str_data)


    def get_aircraft_title(self, force_update = False):
        if not self._aircraft_tile or force_update:
            self._aircraft_title = None
            ar = AircraftRequests(self._sm)
            trigger = ar.find("TITLE")
            title = trigger.get()
            if title:
                title = title.decode()
            self._aircraft_title = title
        return self._aircraft_title
    
    def request_loaded_aircraft(self):
        ''' gets the current aircraft data '''
        if self._aircraft_name:
            return self._aircraft_name
        self._sm.requestAircraftLoaded()



    def _aircraft_loaded_internal_cb(self, folder, name):
        # decode the data into useful bits
        syslog = logging.getLogger("system")
        title = self.get_aircraft_title(True)
        self._aircraft_tile = title
        self._aircraft_folder = folder
        self._aircraft_name = name
        syslog.info(f"Simconnect (mgr): sim aircraft loaded event: {title}/{name}")
        self.sim_aircraft_loaded.emit(folder, name, title)




    def reset(self):
        ''' resets the connection '''
        if self._sm.ok:
            if self._sm.is_connected():
                self.disconnect()
            
        self._connect_attempts = 3



    @property
    def ok(self):
        if not self._sm.ok:
            # attempt to reconnect
            self.reconnect(True)
        return self._sm.ok
    
    @property
    def connected(self) -> bool:
        ''' true if GremlinEx is connected to the simulator '''
        return self._sm.ok

    @property
    def simconnect(self) -> SimConnect:
        ''' returns the simconnect interface instance'''
        return self._sm
    

    def reconnect(self, force_retry = False):
        # not connected
        if not self.connected:
            try:
                if force_retry or self._connect_attempts > 0:
                    if self._connect_attempts > 0:
                        self._connect_attempts -= 1
                        time.sleep(0.5)
                    self._sm.connect()
               
            except:
                pass

            if not self._sm.ok:
                if self._connect_attempts == 0 and gremlin.shared_state.is_running:
                    syslog.error("Simconnect: failed to connect to simulator - terminating profile")
                    # request the profile to stop
                    eh = gremlin.event_handler.EventListener()
                    eh.request_profile_stop.emit()
                return False
            
            else:
                syslog.info("Simconnect: connected to simulator")




        return True # connected  

    def sim_connect(self):
        ''' connects to the sim (has to be different from connect() due to event processing )'''
        if self._sm.is_connected():
            return True
        
        return self.reconnect()

    def sim_disconnect(self):
        if self._sm.ok:
            for request in self._registered_requests.values():
                self._sm.clear(request)
            self._sm.exit()

    @property
    def valid(self):
        ''' true if block maps are valid '''
        return len(self._block_map) > 0

    def block(self, command, clone = True) -> SimConnectBlock:
        ''' gets the command block for a given Simconnect command '''
        s_command, b_command = gremlin.util.to_byte_string(command)
        key = s_command.casefold()
        for cmd in self._commands:
            if key in cmd.casefold():
                block = self._block_map[key]
                if clone:
                    return block.clone()
                return block
            

        return None

    def get_aircraft_data(self):
        ''' returns the current aircraft information
            (aircraft, model, title)
        '''


        ar = AircraftRequests(self._sm)
        trigger = ar.find("ATC_TYPE")
        aircraft_type = trigger.get()
        if aircraft_type:
            aircraft_type = aircraft_type.decode() # binary string to regular string
        trigger = ar.find("ATC_MODEL")
        aircraft_model = trigger.get()
        if aircraft_model:
            aircraft_model = aircraft_model.decode()# binary string to regular string
        trigger = ar.find("TITLE")
        title = trigger.get()
        if title:
            title = title.decode()
        return (aircraft_type, aircraft_model, title)

    def get_aircraft(self):
        ''' gets the aircraft title '''
        ar = AircraftRequests(self._sm)
        trigger = ar.find("TITLE")
        title = trigger.get()
        if title:
            title = title.decode()
        return title
    

        

    def _write_default_xml(self, xml_file):
        ''' writes a default XML file from the base data in the simconnect module '''

        # list of aircraft names
        aircraft_events_description_map = {}
        aircraft_events_scope_map = {}

        # map of categories to commands under this category as a tuple (binary command, command, description, scope)
        category_commands = {}

        # map of a command to its category
        command_category_map = {}
        command_map = {}

        for category in SimConnectEventCategory.to_list():
            if category == SimConnectEventCategory.Engine:
                source = self._aircraft_events.Engine.list
            elif category == SimConnectEventCategory.FlightControls:
                source = self._aircraft_events.Flight_Controls.list
            elif category == SimConnectEventCategory.AutoPilot:
                source = self._aircraft_events.Autopilot.list
            elif category == SimConnectEventCategory.FuelSystem:
                source = self._aircraft_events.Fuel_System.list
            elif category == SimConnectEventCategory.FuelSelection:
                source = self._aircraft_events.Fuel_Selection_Keys.list
            elif category == SimConnectEventCategory.Instruments:
                source = self._aircraft_events.Instruments.list
            elif category == SimConnectEventCategory.Lights:
                source = self._aircraft_events.Lights.list
            elif category == SimConnectEventCategory.Failures:
                source = self._aircraft_events.Failures.list
            elif category == SimConnectEventCategory.MiscellaneousSystems:
                source = self._aircraft_events.Miscellaneous_Systems.list
            elif category == SimConnectEventCategory.NoseWheelSteering:
                source = self._aircraft_events.Nose_wheel_steering.list
            elif category == SimConnectEventCategory.CabinPressure:
                source = self._aircraft_events.Cabin_pressurization.list
            elif category == SimConnectEventCategory.Catapult:
                source = self._aircraft_events.Catapult_Launches.list
            elif category == SimConnectEventCategory.Helicopter:
                source = self._aircraft_events.Helicopter_Specific_Systems.list
            elif category == SimConnectEventCategory.SlingsAndHoists:
                source = self._aircraft_events.Slings_and_Hoists.list
            elif category == SimConnectEventCategory.SlewSystem:
                source = self._aircraft_events.Slew_System.list
            elif category == SimConnectEventCategory.ViewSystem:
                source = self._aircraft_events.View_System.list
            elif category == SimConnectEventCategory.FreezingPosition:
                source = self._aircraft_events.Freezing_position.list
            elif category == SimConnectEventCategory.MissionKeys:
                source = self._aircraft_events.Mission_Keys.list
            elif category == SimConnectEventCategory.ATC:
                source = self._aircraft_events.ATC.list
            elif category == SimConnectEventCategory.Multiplayer:
                source = self._aircraft_events.Multiplayer.list
            else:
                continue



            category_commands[category] = []
            for b_command, description, scope in source:
                command = b_command.decode('ascii')
                aircraft_events_description_map[command] = description
                aircraft_events_scope_map[command] = scope
                data = (b_command, command, description, scope)
                category_commands[category].append(data)
                #commands.append(data)
                aircraft_events_description_map[command] = description
                command_category_map[command] = category
                command_map[command] = ("e", data)


            # build request commands
            for data in self._aircraft_requests.list:
                for command, data in data.list.items():
                    command_map[command] = ("r", data)

        commands = list(command_map.keys())
        commands.sort()
        root = etree.Element("commands")
        for command in commands:
            data = command_map[command]

            command_node = etree.SubElement(root,"command", value = command)

            value_types = ["(0","16383"]
            units = ""
            is_range = False # assume command has no range specified
            is_toggle = False # true if range is a toggle range (either value of the range)
            min_range = 0
            max_range = 0
            if data[0] == "e":
                simvar_type = "event"
                description = data[1][2]
                units = ""
                for v in value_types:
                    if v in description:
                        units = "int"
                        # get min and max range
                        break

                if "(-16383" in description:
                    min_range = -16383
                    is_range = True
                if "16383)" in description:
                    max_range = 16383
                    is_range = True
                if "(1,0)" in description or "(0,1)" in description:
                    min_range = 0
                    max_range = 1
                    is_toggle = True
                    is_range = True
                if "(1 or 2)" in description:
                    min_range = 1
                    max_range = 2
                    is_toggle = True
                    is_range = True
                if "0 to 65535" in description:
                    min_range = 0
                    max_range = 65535
                    is_range = True
                if "0 to 4294967295" in description:
                    min_range = 0
                    max_range = 4294967295
                    is_range = True
                settable = True

            elif data[0] == "r":
                simvar_type = "simvar"
                description = data[1][0]
                units = data[1][2].decode('ascii')
                settable = data[1][3] == 'Y'

            command_category =self.get_command_category(command)
            if command_category is None:
                command_category = SimConnectEventCategory.NotSet
            category =  SimConnectEventCategory.to_string(command_category)
            is_axis = "AXIS_" in command
            if is_axis:
                min_range = -16383
                max_range = 16383
                is_range = True
            is_indexed = ":index" in command

            # simvar index : https://docs.flightsimulator.com/html/Programming_Tools/SimVars/Simulation_Variables.htm#h

            command_node.attrib['type'] = simvar_type
            command_node.attrib["datatype"] = "int"
            command_node.attrib["units"] = units
            command_node.attrib["category"] = category
            command_node.attrib["settable"] = str(settable)
            command_node.attrib["axis"] = str(is_axis)
            command_node.attrib["indexed"] = str(is_indexed)
            description_node = etree.SubElement(command_node,"description", value = description)
            if is_range:
                range_node = etree.SubElement(command_node,"range")
                range_node.attrib["min"] = str(min_range)
                range_node.attrib["max"] = str(max_range)
                range_node.attrib["toggle"] = str(is_toggle)

        try:
            # save the file
            tree = etree.ElementTree(root)
            tree.write(xml_file, pretty_print=True,xml_declaration=True,encoding="utf-8")
        except Exception as err:
            syslog.error(f"SimconnectData: unable to create XML simvars: {xml_file}: {err}")

    def _load_xml(self, xml_source):
        ''' loads blocks from the XML file '''

        def get_attribute(node : etree._Element, attr, default = '', throw_on_missing = False) -> bool:
            ''' gets a node attribute checking for validity '''
            if attr in node.attrib:
                return node.attrib[attr]
            elif throw_on_missing:
                raise ValueError(f"Bad or missing boolean XML attribute {attr} on node {node}")
            return str(default)

        def get_bool_attribute(node : etree._Element, attr, default = False, throw_on_missing = False) -> bool:
            ''' gets a node attribute checking for validity '''
            value = get_attribute(node, attr, throw_on_missing).lower()
            if value in ("t","true","1","-1"):
                return True
            if value in ("f","false","0"):
                return False
            return default

        def get_int_attribute(node : etree._Element, attr, default = 0, throw_on_missing = False) -> int:
            value = get_attribute(node, attr).lower()
            if value != '':
                try:
                    return int(value)
                except:
                    if throw_on_missing:
                        raise ValueError(f"Bad or missing int XML attribute {attr} on node {node}")

            return default

        def get_float_attribute(node : etree._Element, attr, default = 0.0, throw_on_missing = False) -> float:
            value = get_attribute(node, attr).lower()
            if value != '':
                try:
                    return float(value)
                except:
                    if throw_on_missing:
                        raise ValueError(f"Bad or missing float XML attribute {attr} on node {node}")

            return default



        if not xml_source or not os.path.isfile(xml_source):
            syslog.error(f"SimconnectData: unable to load XML simvars: {xml_source}")
            return False

        try:
            parser = etree.XMLParser(remove_blank_text=True)
            root = etree.parse(xml_source, parser)

            nodes = root.xpath('//command')
            for node in nodes:
                
                max_range = 0
                min_range = 0
                is_toggle = False
                value = get_attribute(node,"datatype")
                if value == "int":
                    data_type = OutputType.IntNumber
                elif value == "float":
                    data_type = OutputType.FloatNumber
                else:
                    data_type == OutputType.NotSet
                simvar = get_attribute(node,"value",throw_on_missing=True)
                simvar_type = get_attribute(node,"type",throw_on_missing=True)
                units = get_attribute(node,"units",throw_on_missing=True)
                category = get_attribute(node,"category")
                settable = get_bool_attribute(node,"settable",throw_on_missing=True)
                axis = get_bool_attribute(node,"axis",throw_on_missing=True)
                indexed = get_bool_attribute(node,"indexed",throw_on_missing=True)
                invert =get_bool_attribute(node,"invert",throw_on_missing=False)

                description = ""
                for child in node.getchildren():
                    if child.tag == "description":
                        description = get_attribute(child,"value")
                    elif child.tag == "range":
                        
                        is_toggle = get_bool_attribute(child,"toggle",throw_on_missing=True)
                        min_range = get_int_attribute(child,"min",throw_on_missing=True)
                        max_range = get_int_attribute(child,"max",throw_on_missing=True)

                block = SimConnectBlock()
                s_simvar, b_simvar = gremlin.util.to_byte_string(simvar)

                block.command = simvar
                block.command_type = simvar_type
                block.output_data_type = data_type
                block.category = category
                block.units = units
                block.is_readonly = not settable
                block.is_axis = axis
                block.is_indexed = indexed
                block._description = description
                block._invert = invert
                
                block._min_range = min_range  # can be modified by the user
                block._max_range = max_range  # can be modified by the user
                block._command_min_range = min_range # original range - cannot be modified
                block._command_max_range = max_range # original range - cannot be modified
                block.is_toggle = is_toggle
                key = s_simvar.casefold()
                if key in self._block_map.keys():
                    syslog.error(f"SimconnectData: duplicate definition found: {s_simvar} in  {xml_source}")
                    self._block_map = {}
                    return False
                self._block_map[key] = block

            if self.verbose:
                syslog.info(f"SimconnectData: loaded {len(self._block_map):,} simvars")

        except Exception as err:
            syslog.error(f"SimconnectData: XML simvars read error: {xml_source}: {err}")
            return False



    def get_event_description(self, command):
        ''' maps the description to the given simconnect command name '''
        if command in self._aircraft_events_description_map.keys():
            return self._aircraft_events_description_map[command]
        return "Not found"
    
    def get_command_type(self, command) -> SimConnectCommandType:
        ''' maps to the type of command'''
        if self._aircraft_events.find(command):
            return SimConnectCommandType.Event
        if self._aircraft_requests.find(command):
            return SimConnectCommandType.SimVar
        return SimConnectCommandType.NotSet


    @property
    def AircraftEvents(self):
        ''' gets a list of aicraft events '''
        return self._aircraft_events

    @property
    def ok(self) -> bool:
        ''' true if simconnect is ok '''
        return self._sm.ok

    @property
    def running(self) -> bool:
        ''' true if sim is running '''
        return self._sm.running

    @property
    def paused(self) -> bool:
        ''' true if sim is paused '''
        return self._sm.paused

    @property
    def sm(self) -> SimConnect:
        ''' simconnect object'''
        return self._sm

    def ensure_running(self):
        ''' ensure simconnect is connected '''
        return self._sm.is_connected()

    def get_category_list(self):
        ''' returns the list of supported command categories '''
        categories = self._command_category_map.keys()
        categories.sort()
        return categories

    def get_command_name_list(self):
        ''' gets all possible command names '''
        return self._commands

    def get_default_command(self):
        ''' gets the default command '''
        if self.valid:
            return self._block_map[0].command
        return None

    def get_command_category(self, command):
        ''' for a given command, find the category of that command '''
        if self.valid and command in self._block_map.keys():
            block = self._block_map[command]
            return block.category
        return SimConnectEventCategory.NotSet
    

    def sendReadbackEvent(self, command, value, readback_command, readback_value, timeout = 4):
        ''' sends an event and waits for a return value to match the readback value, or timeout '''
        
        # simconnect events have to be in byte strings
        s_command, b_command = gremlin.util.to_byte_string(command)
        _, b_readback = gremlin.util.to_byte_string(readback_command)
        
        key = s_command.casefold()
        if not key in self._registered_events:
            self._registered_events[key] = self._sm.map_to_sim_event(b_command)
        
        if key in self._registered_events:
            event_id = self._registered_events[key]
            if event_id == 0:
                syslog.error(f"Simconnect: unable to register event for {s_command}")
                return False # bad event

        # send event and wait for readback value or a timeout
        event = DataThreadingEvent()
        thread = threading.Thread(target=self._send_readback_event_worker(event, event_id, value, b_readback, readback_value, timeout))
        thread.start()
        event.wait()

        if event.data and self.verbose: syslog.info(f"SimConnect: event readback completed OK {command} value: {value}")
        return event.data # data contains the return code
        

    def _send_readback_event_worker(self, event, event_id, value, readback, readback_value, timeout):
        ''' readback worker to send the event, then compare the expected value to the return value within the timeout period '''
        
        
        # send the event
        retval = self._sm.send_event(event_id, value)

        # read the data back to confirm it was processed
        retval = False
        
        block = self.block(readback)
        if block:
       

            value = block.read()
            if value == readback_value:
                retval = True
            else:
                max_time = time.time() + timeout
                # wait for the value to show up on readback or a timeout
                while time.time() < max_time:
                    if value == readback_value:
                        # found the data we're looking for
                        retval = True
                        break
                    time.sleep(0.250)
                    value = block.read()
        else:
            syslog.error(f"Simconnect: event readback FAILED: readback command {readback} not found")
    
        # done    
        event.data = retval
        event.set()

class SimConnectBlock():
    ''' holds simconnect block information '''

    def __init__(self):
        ''' creates a simconnect block object

        the block auto-configures itself based on the command, and determines
        range, values and options, and what type of command it is.

        :param simconnect The simconnect object

        '''

        self._command_type = SimConnectCommandType.NotSet
        self._description = None
        self._value_type = OutputType.NotSet
        self._category = SimConnectEventCategory.NotSet
        self._output_data_type = OutputType.NotSet
        self._output_mode = SimConnectActionMode.NotSet
        self._command = None # the command text
        self._is_set_value = False # true if the item can set a value
        self._readonly = False # if readonly - the request cannot be triggered
        self._is_axis = False # true if the output is an axis variable
        self._is_indexed = False # true if the output is indexed using the :index
        self._min_range = -16383 # user modifieable range
        self._max_range = 16383
        self._command_min_range = -16383 # command range (cannot be modified)
        self._command_max_range = 16383
        self._trigger_mode = SimConnectTriggerMode.NoOp # default for on/off type blocks
        self._invert = False # true if the axis output should be inverted
        self._value = 0 # output value
        self._is_value = False # true if the command supports an output value
        
        self._is_toggle = False # true if the range valuers are either mix or max
        self._notify_enabled_count = 0 # true if notifications are enabled
        self._command = None
        self._units = ""
        self._is_axis = False # true if the block is axis output enabled
        self._is_periodic = False # true if we're requesting period data from the sim when the data changes
        self._request : Request = None # holds any current aircraft request (request commands only )
        config = gremlin.config.Configuration()
        self.verbose = config.verbose_mode_simconnect
        self.verbose_detailed = config.verbose_mode_detailed

    @property
    def sm(self) -> SimConnect:
        ''' simconnect object '''

        return SimConnectManager().sm
    
    @property
    def request(self):
        ''' gets any active aicraft request '''
        if not self._request:
            # create a request for this block
            self.register()

        return self._request

    def enable_notifications(self, force = False):
        ''' enables data notifications from this block '''
        if self._notify_enabled_count > 0:
            self._notify_enabled_count -= 1
        if force:
            self._notify_enabled_count = 0

    def disable_notifications(self):
        ''' disables data notifications from this block '''
        self._notify_enabled_count -= 1

    @property
    def notifications_enabled(self):
        ''' true if notifications are enabled'''
        return self._notify_enabled_count == 0
    
    @property
    def is_periodic(self) -> bool:
        ''' determines if the data should be sent when it changes (true) or just one time (false)'''
        return self._is_periodic
    
    @is_periodic.setter
    def is_periodic(self, value: bool):
        self._is_periodic = value

    @property
    def command(self):
        ''' the block command'''
        return self._command

    @command.setter
    def command(self, value):
        if value != self._command:
            self._command = value
            # update flags
            self.is_axis = value in _simconnect_full_range
            


    @property
    def is_axis(self):
        ''' true if the command supports axis output '''
        return self._is_axis

    @property
    def is_request(self) -> bool:
        ''' true if the block is a request '''
        return self._command_type == SimConnectCommandType.Request

    @property
    def is_event(self) -> bool:
        ''' true if the block is an event '''
        return self._command_type == SimConnectCommandType.Event

    @property
    def is_value(self):
        ''' true if the command supports a value output to simconnect '''
        return self._is_value

    @property
    def command_type(self) -> SimConnectCommandType:
        ''' returns the command type '''
        return self._command_type
    @command_type.setter
    def command_type(self, value : SimConnectCommandType):
        if isinstance(value, str):
            value = SimConnectCommandType.from_string(value)
        elif isinstance(value, int):
            value = SimConnectCommandType(value)
        self._command_type = value

    @property
    def display_block_type(self) -> str:
        ''' returns the display string for the block type '''

        if self._command_type == SimConnectCommandType.Request:
            return "Simconnect Request"
        elif self._command_type == SimConnectCommandType.Event:
            return "Simconnect Event"
        return F"Unknown command type: {self._command_type}"

    @property
    def output_mode(self) -> SimConnectActionMode:
        ''' output mode '''
        return self._output_mode

    @output_mode.setter
    def output_mode(self, value : SimConnectActionMode):
        if value == SimConnectActionMode.Trigger:
            pass
        self._output_mode = value

    @property
    def output_data_type(self):
        ''' block output data type'''
        return self._output_data_type

    @output_data_type.setter
    def output_data_type(self, value):
        self._output_data_type = value

    @property
    def category(self) -> str:
        ''' command category '''
        return self._category
    @category.setter
    def category(self, value):
        self._category = value

    @property
    def is_readonly(self) -> bool:
        ''' true if readonly - based on the command type '''
        return self._readonly

    @is_readonly.setter
    def is_readonly(self, value):
        self._readonly = value

    @property
    def is_axis(self) -> bool:
        ''' true if axis - based on the command type '''
        return self._axis

    @is_axis.setter
    def is_axis(self, value):
        self._axis = value

    @property
    def is_indexed(self) -> bool:
        ''' true if readonly - based on the command type '''
        return self._indexed

    @is_indexed.setter
    def is_indexed(self, value):
        self._indexed = value

    @property
    def units(self) -> str:
        ''' given units '''
        return self._units
    @units.setter
    def units(self, value):
        self._units = value

    @property
    def display_data_type(self) -> str:
        ''' returns a displayable data type even if none is set '''
        if self._value_type == OutputType.IntNumber:
            return "Number (int)"
        elif self._value_type == OutputType.FloatNumber:
            return "Number (float)"
        return "N/A"

    @property
    def invert_axis(self):
        ''' inverts output (axis input only) '''
        return self._invert
    @invert_axis.setter
    def invert_axis(self, value):
        self._invert = value

    @property
    def min_range(self):
        ''' current min range '''
        return self._min_range

    @min_range.setter
    def min_range(self, value):
        self._min_range = value

    @property
    def max_range(self):
        ''' current max range '''
        return self._max_range

    @max_range.setter
    def max_range(self, value):
        self._max_range = value

    @property
    def command_min_range(self):
        ''' current min range '''
        return self._command_min_range


    @property
    def command_max_range(self):
        ''' current max range '''
        return self._command_max_range


    @property
    def trigger_mode(self) -> SimConnectTriggerMode:
        ''' block trigger mode if the action mode is in trigger mode  '''
        return self._trigger_mode

    @trigger_mode.setter
    def trigger_mode(self, value : SimConnectTriggerMode):
        self._trigger_mode = value

    @property
    def is_toggle(self):
        ''' true if the range output is only two values - min or max'''
        return self._is_toggle
    @is_toggle.setter
    def is_toggle(self, value):
        self._is_toggle = value

    def custom_range_sync(self):
        ''' makes custom range the same as the default range '''
        self._min_range_custom = self._min_range
        self._max_range_custom = self._max_range_custom
        self._notify_range_update()


    def _notify_range_update(self):
        ''' fires a range changed event '''

        if self.notifications_enabled:
            event = RangeEvent()
            event.max = self._max_range
            event.max_custom = self._max_range_custom
            event.min = self._min_range
            event.min_custom = self._min_range_custom

            eh = SimConnectEventHandler()
            eh.range_changed.emit(self, event)


    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, number):
        ''' sets the output value'''
        if number != self._value:
            self._value = number
            if self.notifications_enabled:
                eh = SimConnectEventHandler()
                eh.value_changed.emit(self)

    @property
    def is_ranged(self):
        ''' true if the command is a ranged command (suitable for a range of values)'''
        return self._output_mode == SimConnectActionMode.Ranged
    
    @property
    def description(self) -> str:
        ''' returns the command description'''
        return self._description

    @description.setter
    def description(self, value):
        self._description = value

    @property
    def valid(self) -> bool:
        return self._command is not None

    @property
    def display_name(self) -> str:
        ''' returns a readable form of the block '''
        stub =  f"Command:{self.command} Mode: {SimConnectActionMode.to_display(self.output_mode)}"
        if self.output_mode == SimConnectActionMode.SetValue:
            stub += f" Value: {self.value}"
        elif self.output_mode == SimConnectActionMode.Ranged:
            stub += f" Output range: {self.min_range}, {self.max_range}"
        elif self.output_mode == SimConnectActionMode.Trigger:
            if self.trigger_mode != SimConnectTriggerMode.NotSet:
                stub += f" {SimConnectTriggerMode.to_display(self.trigger_mode)}"

        return stub


    def _set_range(self):
        ''' sets the data range from the current command '''
        
        if self._command in _simconnect_half_range:
            min_range = 0
            max_range = 16383
            
        elif self._command in _simconnect_angle_range:
            min_range = 0
            max_range = 360
            
        elif self._command in _simconnect_egt_range:
            min_range = 0
            max_range = 32767
            
        elif self.command in _simconnect_full_range:
            min_range = -16383
            max_range = 16383
            
        else:
            # default
            min_range = -16383
            max_range = 16383

        changed = False
        if self._min_range != min_range:
            self._min_range = min_range
            changed = True
        if self._max_range != max_range:
            self._max_range = max_range
            changed = True
        
        if changed:
            self._notify_range_update()

    def map_range(self, value: float) -> int:
        ''' maps the input float value -1 to +1 to the command's range '''
        if value < -1.0: value = -1.0
        if value > 1.0: value = 1.0
        r_min = self._min_range
        r_max = self._max_range
        return round(r_min + (value + 1.0)*((r_max - r_min)/2.0))


    @staticmethod
    def from_command(self, command):
        ''' '''
        block = SimConnectBlock(command)
        return block
    

    def register(self):
        ''' registers a block command '''
        if not self.sm.is_connected():
            # not connectedkl
            return False

        if self._command:
            
            if self._command_type ==  SimConnectCommandType.Event:
                ae = AircraftEvents(self.sm)
                trigger = ae.find(self._command)
                if trigger:
                    return True
                else:
                    syslog.error(f"Simconnect: event: '{self._command}' not found")
            elif self._command_type == SimConnectCommandType.SimVar:
                # set simvar
                ar = AircraftRequests(self.sm, time=2000)
                self._request = ar.request(self._command)
                if self.verbose:
                    syslog.info(f"Simconnect: register simvar: '{self._command}' mode: {self.output_mode}")
                return True

            elif self._command_type == SimConnectCommandType.Request and not self._readonly:
                ar = AircraftRequests(self.sm, time=2000)
                self._request = ar.request(self._command)
                if self._request:
                    self._request._ensure_def()    
                    self._request.callback = self.request_changed_callback
                    if self.is_periodic:
                        self.sm._request_periodic_data(self._request)
                    else:
                        self.sm._request_data(self._request)
                    if self.verbose:
                        syslog.info(f"Simconnect: get request {self._command}")
                else:
                    syslog.error(f"Simmconnect: unknown command '{self._command}'")
                return True

        return False        

    def read(self):
        ''' gets a value from simconnect '''
        if not self.sm.is_connected():
            # not connected
            return None
        return self.execute(mode = SimConnectActionMode.GetValue)

    def execute(self, value = None, mode : SimConnectActionMode = None):
        ''' executes the command '''

        if not self.sm.is_connected():
            # not connected
            return False

        if self._command:
            if self._command_type ==  SimConnectCommandType.Event:
                ae = AircraftEvents(self.sm)
                trigger = ae.find(self._command)
                if trigger:
                    if self.is_readonly:
                        # no param to set
                        if self.verbose:
                            syslog.info(f"Simconnect: trigger Simconnect Event: {self._command}")
                        trigger()
                    else:
                        if self.verbose:
                            syslog.info(f"Simconnect: trigger event value: {self._command} {value}")
                        trigger(value)
                    return True
                else:
                    syslog.error(f"Simconnect: event: '{self._command}' not found")
            elif self._command_type == SimConnectCommandType.SimVar:
                # set simvar
                ar = AircraftRequests(self.sm, time=2000)
                if self.verbose:
                    syslog.info(f"Simconnect: set simvar: '{self._command}' mode: {self.output_mode}")
                if mode is None:
                    mode = self.output_mode
                if mode == SimConnectActionMode.Trigger:
                    mode = self.trigger_mode

                    if mode == SimConnectTriggerMode.Toggle:
                        # get the current state and flip it
                        state = ar.get(self._command)
                        value = 1 if state == 0 else 0
                        ar.set(self._command, value)
                        if self.verbose:
                            syslog.info(f"\tToggle state: {state} -> {value}")
                    elif mode == SimConnectTriggerMode.TurnOff:
                        ar.set(self._command, 0)
                        if self.verbose:
                            syslog.info(f"\tTurn off: 0")
                    elif mode == SimConnectTriggerMode.TurnOn:
                        ar.set(self._command, 1)
                        if self.verbose:
                            syslog.info(f"\tTurn on: 1")
                    elif mode == SimConnectTriggerMode.NoOp:
                        if self.verbose:
                            syslog.info(f"\tNo op:")
                        ar.set(self._command, 1)
                elif mode == SimConnectActionMode.SetValue:
                    ar.set(self._command, value)
                    if self.verbose:
                        syslog.info(f"\tSet value: {value}")
                elif mode == SimConnectActionMode.GetValue:
                    value = ar.get(self._command)
                    if self.verbose:
                        syslog.info(f"\tGet value: {value}")
                    return value

                return True





            elif self._command_type == SimConnectCommandType.Request and not self._readonly:
                ar = AircraftRequests(self.sm, time=2000)
                self._request = ar.request(self._command)
                if self._request:
                    self._request._ensure_def()    
                    self._request.callback = self.request_changed_callback
                    if self.is_periodic:
                        self.sm._request_periodic_data(self._request)
                    else:
                        self.sm._request_data(self._request)
                    if self.verbose:
                        syslog.info(f"Simconnect: set request {self._command} {value}")
                else:
                    syslog.error(f"Simmconnect: unknown command '{self._command}'")
                return True

        return False
    
    def request_changed_callback(self):
        ''' called when the request receives data '''
        sh = SimConnectEventHandler()
        if self.verbose_detailed:
            syslog.info(f"Simconnect block: {self._command}  Received data: {self._request.buffer}  data type: {type(self._request.buffer).__name__}")
        event = SimConnectEvent(self._command, self._request.buffer)
        sh.simconnect_event.emit(event)
    
    def stop(self):
        ''' stops a periodic request '''
        request = self._request
        if request is not None: # request was made
            if self.is_periodic: # request is periodic 
                self.sm.stop_periodic_data(request) # tell the sim to stop sending data 
            self.sm.clear(request) # remove the definition

    def to_xml(self):
        ''' writes to an xml node block '''
        node = etree.Element("block")

        node.set("command",self.command)
        node.set("trigger", SimConnectTriggerMode.to_string(self.trigger_mode))
        node.set("mode", SimConnectActionMode.to_string(self.output_mode))
        node.set("invert", str(self.invert_axis))
        value = self.value if self.value else 0.0
        node.set("value", gremlin.util.safe_format(value, float))
        node.set("min_range", gremlin.util.safe_format(self.min_range, float))
        node.set("max_range", gremlin.util.safe_format(self.max_range, float))

        return node

    def from_xml(self, node):
        ''' reads from an xml node block '''
        command = gremlin.util.safe_read(node,"command", str)
        if not command:
            command = SimConnectManager().get_default_command()
        self.command = command
        self.value = gremlin.util.safe_read(node,"value", float, 0)
        mode = gremlin.util.safe_read(node,"mode", str, "none")
        output_mode = SimConnectActionMode.to_enum(mode)
        if output_mode is None:
            output_mode = SimConnectActionMode.NotSet
        self.output_mode = output_mode

        # trigger mode for singleton vars
        trigger_mode = gremlin.util.safe_read(node,"trigger", str, "none")
        self.trigger_mode = SimConnectTriggerMode.to_enum(trigger_mode)

        # axis inversion
        self.invert_axis = gremlin.util.safe_read(node,"invert", bool, False)

        self.min_range = gremlin.util.safe_read(node,"min_range", float, -16383)
        self.max_range = gremlin.util.safe_read(node,"max_range", float, 16383)
        


        ''' updates missing values '''
    def update(self):
        if self._command_type == SimConnectCommandType.NotSet:
            sm = SimConnectManager()
            self._command_type = sm.get_command_type(self._command)
        # update command data

    def clone(self):
        import copy
        # return a clone
        return copy.deepcopy(self)



_manager = SimConnectManager()