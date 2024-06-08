
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
    SimConnectEventCategory.Multiplayer :"Multiplayer"
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
    def ok(self):
        ''' true if simconnect is ok '''
        return self._sm.ok
    
    @property
    def running(self):
        ''' true if sim is running '''
        return self._sm.running
    
    @property
    def paused(self):
        ''' true if sim is paused '''
        return self._sm.paused
    
    @property
    def sm(self):
        ''' simconnect object'''
        return self._sm

    # def get_flight_control_commands(self):
    #     ''' gets flight control data '''
    #     return self.get_command_list(SimConnectEventCategory.FlightControls)
        
    
    # def get_command_list(self, category : SimConnectEventCategory = None):
    #     ''' gets the commands for a particular category'''
    #     data = self._command_map.keys()
    #     # if not category:
    #     #     data = [item[1] for item in self._commands]
    #     # else:
    #     #     data = [item[1] for item in self._category_commands[category]]
    #     data.sort()
    #     return data


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