
import os
from xml.etree import ElementTree

from PySide6 import QtWidgets, QtCore, QtGui

from gremlin.base_classes import AbstractAction, AbstractFunctor
from gremlin.common import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.macro
import gremlin.ui.common
import gremlin.ui.input_item
from .SimConnect import *
from .SimConnect.Enum import *
from gremlin.singleton_decorator import SingletonDecorator
import enum

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

class SimConnectEventCategory(enum.Enum):
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
            raise gremlin.error.GremlinError("Invalid type in lookup")

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


class SimConnectBlockType(enum.Enum):
    NotSet = 0,
    Event = 1,
    Request = 2,


    
        

@SingletonDecorator
class SimConnectData():
    ''' holds simconnect data '''

    def __init__(self) -> None:
        self._sm = SimConnect(auto_connect =False)
        self._aircraft_events = AircraftEvents(self._sm)
        self._aircraft_requests = AircraftRequests(self._sm)

        # list of aircraft names
        self._aircraft_events_description_map = {}
        self._aircraft_events_scope_map = {}

        # map of categories to commands under this category as a tuple (binary command, command, description, scope)
        self._category_commands = {}

        # list of all commands
        self._commands = [] 

        # map of a command to its category
        self._command_category_map = {}
        self._command_map = {}

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

            self._category_commands[category] = []
            for b_command, description, scope in source:
                command = b_command.decode('ascii')
                self._aircraft_events_description_map[command] = description
                self._aircraft_events_scope_map[command] = scope
                data = (b_command, command, description, scope)
                self._category_commands[category].append(data)
                self._commands.append(data)
                self._aircraft_events_description_map[command] = description
                self._command_category_map[command] = category
                self._command_map[command] = ("e", data)


            # build request commands
            for data in self._aircraft_requests.list:
                for command, data in data.list.items():
                    self._command_map[command] = ("r", data)
                



    def get_event_description(self, command):
        ''' maps the description to the given simconnect command name '''
        if command in self._aircraft_events_description_map.keys():
            return self._aircraft_events_description_map[command]
        return "Not found"

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
        if self._sm.ok:
            if not self._sm.running:
                self._sm.connect()
            return self._sm.running
        return False

    def get_category_list(self):
        ''' returns the list of supported command categories '''

    
    def get_command_name_list(self):
        ''' gets all possible command names '''
        #commands = [item[0] for item in self._commands]
        commands = list(self._command_map.keys())
        commands.sort()
        return commands
    
    def get_command_data(self, command):
        ''' gets the data associated with the command '''
        if command in self._command_map.keys():
            return self._command_map[command]
        return None

        
    def get_default_command(self):
        ''' gets the default command '''
        item = self._commands[0]
        return item[1]
    
    def get_command_category(self, command):
        ''' for a given command, find the category of that command '''
        if command in self._command_category_map.keys():
            return self._command_category_map[command]
        return SimConnectEventCategory.NotSet

    def get_request_name_list(self):
        ''' returns a list of all possible requests '''
        request_names = []
        for data in self._aircraft_requests.list:
            request_names.extend(list(data.list.keys()))
        request_names.sort()
        return request_names
    
    def get_request_data(self, request):
        ''' gets request parameter data '''
        if request in self._requests:
            return self._aircraft_requests.find(request)



class SimConnectBlock():
    ''' holds simconnect block information '''
    def __init__(self, command = None):
        ''' creates a simconnect block object
        
        the block auto-configures itself based on the command, and determines
        range, values and options, and what type of command it is.

        :param command The simconnect command (event or request)
        
        '''
        self._block_type = SimConnectBlockType.NotSet
        self._description = None
        self._value_type = None
        self._category = SimConnectEventCategory.NotSet
        self._command = None
        self._set_value = False # true if the item can set a value
        self._readonly = False # if readonly - the request cannot be triggered
        self._data_type = None
        self._is_angle = False # true if the value is an angle 0 360, if false use axis values
        self._min_range = -16383
        self._max_range = 16383
        self._is_ranged = False # true if the command is ranged
        self._command = command
        if command:
            self._update()

    @property
    def command(self):
        ''' the block command'''
        return self._command
    
    @command.setter
    def command(self, value):
        self._command = value
        self._update()

    @property
    def is_request(self) -> bool:
        ''' true if the block is a request '''
        return self._block_type == SimConnectBlockType.Request
    
    @property
    def is_event(self) -> bool:
        ''' true if the block is an event '''
        return self._block_type == SimConnectBlockType.Event
    
    @property
    def block_type(self):
        ''' returns the block type '''
        return self._block_type
    
    @property
    def display_block_type(self) -> str:
        ''' returns the display string for the block type '''
        if self._block_type == SimConnectBlockType.Request:
            return "Request"
        elif self._block_type == SimConnectBlockType.Event:
            return "Event"
        return ""
    
    @property
    def category(self) -> str:
        ''' command category '''
        return self._category
    
    @property
    def readonly(self) -> bool:
        ''' true if readonly '''
        return self._readonly
    
    @property
    def data_type(self) -> str:
        ''' Simconnect datatype '''
        return self._data_type
    
    @property
    def display_data_type(self) -> str:
        ''' returns a displayable data type even if none is set '''
        return self._data_type if self._data_type else 'N/A'
    
    @property
    def min_range(self):
        ''' current min range '''
        return self._min_range
    
    @property
    def max_range(self):
        ''' current max range '''
        return self._max_range
    
    @property
    def is_ranged(self):
        ''' true if the command is a ranged command '''
        return self._is_ranged
    
    @property
    def description(self):
        ''' returns the command description'''
        return self._description
    
    @property
    def valid(self) -> bool:
        return self._command is not None


    
    def _set_range(self):
        ''' sets the data range from the current command '''
        is_ranged = False
        if self._command in _simconnect_half_range:
            self._min_range = 0
            self._max_range = 16383
            is_ranged = True
        elif self._command in _simconnect_angle_range:
            self._min_range = 0
            self._max_range = 360
            is_ranged = True
        elif self._command in _simconnect_egt_range:
            self._min_range = 0
            self._max_range = 32767
            is_ranged = True
        elif self.command in _simconnect_full_range:
            self._min_range = -16383
            self._max_range = 16383
            is_ranged = True
        else:
            # default
            self._min_range = -16383
            self._max_range = 16383
        self._is_ranged = is_ranged

    def _update(self):
        ''' updates on new command '''
        smdata = SimConnectData()
        command = self._command
        data = smdata.get_command_data(command)   
        if data:
            self._data = data
            if data[0] == "e":
                self._block_type = SimConnectBlockType.Event
                self._description = data[1][2]
                self._value_type = ""
                self._category = smdata.get_command_category(command)
                self._readonly = False # can trigger events

            elif data[0] == "r":
                self._block_type = SimConnectBlockType.Event
                self._description = data[1][0]
                self._value_type = data[1][2].decode('ascii')
                self._category = smdata.get_command_category(command)
                self._readonly = data[1][3] != 'Y'

            self._set_range()
        
    
    @staticmethod
    def from_command(self, command, smdata : SimConnectData):
        ''' '''
        block = SimConnectBlock(smdata, command)
        return block
    
    def execute(self, value = None):
        ''' executes the command '''
        if self._command and self._sm_data.ensure_running():
            if self._block_type == SimConnectBlockType.Event:
                ae = AircraftEvents(self._sm_data.sm)
                trigger = ae.find(self._command)
                if trigger:
                    if self._set_value:
                        trigger(value)
                    else:
                        trigger()

            elif self._block_type == SimConnectBlockType.Request and not self._readonly:
                ar = AircraftRequests(self._sm_data.sm, _time=2000)
                ar.set(self._command, value)

            return True
        return False
                

                

