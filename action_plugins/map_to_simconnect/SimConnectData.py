
import os
import lxml
from lxml import etree

from PySide6 import QtWidgets, QtCore, QtGui

import gremlin.base_classes
import gremlin.base_profile
import gremlin.config
import gremlin.macro
import gremlin.ui.ui_common
import gremlin.ui.input_item
import gremlin.util
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

class SimConnectActionMode(enum.Enum):
    ''' simconnect action output mode  '''
    NotSet = 0,
    Ranged = 1, # output varies with input axis
    Trigger = 2, # output is a trigger (no value sent)
    SetValue = 3, # output sets a number value
    Gated = 4, # output of axis is gated - the position of the axis is not linear

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
    SimConnectActionMode.SetValue: "Value"
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



class RangeEvent():
    def __init__(self):
        
        self.min = 0
        self.min_custom = 0
        self.max = 0
        self.max_custom = 0



class OutputType(enum.Enum):
    ''' output data type '''
    NotSet = 0
    FloatNumber = 1
    IntNumber = 2



class SimConnectCommandType(enum.Enum):
    NotSet = 0
    Event = 1
    Request = 2
    LVar = 3
    AVar = 4
    SimVar = 5

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
class SimConnectData(QtCore.QObject):
    ''' holds simconnect data '''

    aircraft_loaded = QtCore.Signal(str, str) # fires when aircraft title changes (param folder, title)
    _aircraft_loaded_internal = QtCore.Signal(str) # fires when aircraft title changes

    def __init__(self) -> None:
        QtCore.QObject.__init__(self)

        sm = SimConnect(auto_connect = False,
                        verbose = gremlin.config.Configuration().verbose_mode_simconnect,
                        sim_paused_callback=self._sim_paused_cb,
                        sim_running_callback = self._sim_running_cb,
                        aircraft_loaded_callback= self._aicraft_loaded_cb)
        self._sm = sm

        self._aircraft_events = AircraftEvents(self._sm)
        self._aircraft_requests = AircraftRequests(self._sm)
        self._aircraft_loaded_internal.connect(self._aircraft_loaded_internal_cb)


        self._aircraft_tile = None # current title from aircraft.cfg
        self._simvars_xml =  os.path.join(gremlin.util.userprofile_path(), "simconnect_simvars.xml")


        self._connect_attempts = 3 # number of connection attempts before giving up

        # list of all commands
        self._commands = []

        # list of command blocks
        self._block_map = {}

        self._is_paused = False
        self._is_running = False
        self._aircraft_folder = None
            
        # if the data file doesn't exist, create it in the user's profile folder from the built-in data
        if not os.path.isfile(self._simvars_xml):
            self._write_default_xml(self._simvars_xml)


        # load the data - including any user modifications/additions
        if os.path.isfile(self._simvars_xml):
            self._load_xml(self._simvars_xml)


        if len(self._block_map) > 0:
            # process lists
            self._commands = list(self._block_map.keys())
            self._commands.sort()

    @property
    def is_running(self):
        ''' true if the sim state is running '''
        return self._is_running
    
    def _sim_paused_cb(self, arg):
        self._is_paused = arg

    def _sim_running_cb(self, state):
        self._is_running = state


    def _aicraft_loaded_cb(self, folder):
        ''' occurs when a new aircraft is loaded '''
        if folder != self._aircraft_folder:
            self._aircraft_folder = folder
            self._aircraft_loaded_internal.emit(folder)

    def get_aircraft_title(self):
        ar = AircraftRequests(self._sm)
        trigger = ar.find("TITLE")
        title = trigger.get()
        if title:
            title = title.decode()
        self._aircraft_title = title
        return title

    def _aircraft_loaded_internal_cb(self, folder):
        # decode the data into useful bits
        title = self.get_aircraft_title()
        self.aircraft_loaded.emit(folder, title)

    @property
    def aircraft_title(self):
        ''' currently loaded aircraft - TITLE from the aircraft.cfg file '''
        return self._aircraft_tile

    @property
    def is_paused(self):
        return self._is_paused

    @property
    def current_aircraft_folder(self):
        ''' returns the path to the currently loaded folder '''
        return self._aircraft_folder


    def reset(self):
        ''' resets the connection '''
        self._connect_attempts = 3

    def is_running(self):
        ''' true if the sim is running '''
        return self._sm.running
    
    def is_connected(self):
        ''' true if connected'''
        return self._sm.is_connected()
    
    @property
    def ok(self):
        return self._sm.ok
    
    @property
    def sm(self):
        return self._sm

    def sim_connect(self):
        ''' connects to the sim (has to be different from connect() due to event processing )'''
        if self._sm.ok:
            return True
        
        # not connected
        try:
            if self._connect_attempts > 0:
                self._connect_attempts -= 1
                self._sm.connect()
        except:
            pass
        if not self._sm.ok:
            return False
        
        # on connection - grab the current aircraft da
        title = self.get_aircraft_title()
        self._aircraft_title = title


        return True # connected
    
    def sim_disconnect(self):
        if self._sm.ok:
            self._sm.exit()

    @property
    def valid(self):
        ''' true if block maps are valid '''
        return len(self._block_map) > 0
    
    def block(self, command):
        ''' gets the command block for a given Simconnect command '''
        if command in self._commands:
            return self._block_map[command]
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
                commands.append(data)
                aircraft_events_description_map[command] = description
                command_category_map[command] = category
                command_map[command] = ("e", data)


            # build request commands
            for data in self._aircraft_requests.list:
                for command, data in data.list.items():
                    self._command_map[command] = ("r", data)
            
        commands = list(self._command_map.keys())
        commands.sort()
        root = etree.Element("commands")
        for command in commands:
            data = self._command_map[command]

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


            category =  SimConnectEventCategory.to_string(self.get_command_category(command))
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
            logging.getLogger("system").error(f"SimconnectData: unable to create XML simvars: {xml_file}: {err}")

    def _load_xml(self, xml_source):
        ''' loads blocks from the XML file '''

        def get_attribute(node : etree._Element, attr, default = '', throw_on_missing = False) -> bool:
            ''' gets a node attribute checking for validity '''
            try:
                return node.attrib[attr]
            except:
                pass
            return default
        
        def get_bool_attribute(node : etree._Element, attr, default = False, throw_on_missing = False) -> bool:
            ''' gets a node attribute checking for validity '''
            value = get_attribute(node, attr).lower()
            if value in ("t","true","1","-1"):
                return True
            if value in ("f","false","0"):
                return False
            if throw_on_missing:
                raise ValueError(f"Bad or missing boolean XML attribute {attr} on node {node}")
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
        

        self._block_map = {}
        if not xml_source or not os.path.isfile(xml_source):
            logging.getLogger("system").error(f"SimconnectData: unable to load XML simvars: {xml_source}")
            return False

        try:
            parser = etree.XMLParser(remove_blank_text=True)
            root = etree.parse(xml_source, parser)

            nodes = root.xpath('//command')
            for node in nodes:
                is_ranged = False
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
                description = ""
                for child in node.getchildren():
                    if child.tag == "description":
                        description = get_attribute(child,"value")
                    elif child.tag == "range":
                        is_ranged = True
                        is_toggle = get_bool_attribute(child,"toggle",throw_on_missing=True)
                        min_range = get_int_attribute(child,"min",throw_on_missing=True)
                        max_range = get_int_attribute(child,"max",throw_on_missing=True)

                block = SimConnectBlock()
                block.command = simvar
                block.command_type = simvar_type
                block.output_data_type = data_type
                block.category = category
                block.units = units
                block.is_readonly = not settable
                block.is_axis = axis
                block.is_indexed = indexed
                block._description = description
                block._is_ranged = is_ranged
                block._min_range = min_range  # can be modified by the user
                block._max_range = max_range  # can be modified by the user
                block._command_min_range = min_range # original range - cannot be modified
                block._command_max_range = max_range # original range - cannot be modified
                block.is_toggle = is_toggle

                if simvar in self._block_map.keys():
                    logging.getLogger("system").error(f"SimconnectData: duplicate definition found: {simvar} in  {xml_source}")
                    self._block_map = {}
                    return False
                self._block_map[simvar] = block

            logging.getLogger("system").info(f"SimconnectData: loaded {len(self._block_map):,} simvars")

        except Exception as err:
            logging.getLogger("system").error(f"SimconnectData: XML simvars read error: {xml_source}: {err}")
            return False



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
        if not self._sm.ok:
            return False
        return self._sm.running
    
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
    
@gremlin.singleton_decorator.SingletonDecorator
class SimConnectEventHandler(QtCore.QObject):
    ''' handles events related to simconnect '''
    range_changed = QtCore.Signal(object, RangeEvent) # fires when the block range values change (block, event)
    value_changed = QtCore.Signal(object) # fires when the block output value changes (block)

    def __init__(self):
        super().__init__()




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
        self._set_value = False # true if the item can set a value
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
        self._is_ranged = False # true if the command is ranged
        self._is_toggle = False # true if the range valuers are either mix or max
        self._notify_enabled_count = 0 # true if notifications are enabled
        self._command = None
        self._units = ""
        self._is_axis = False # true if the block is axis output enabled

    @property
    def sm(self):
        ''' simconnect object '''
        return SimConnectData().sm

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
    def command(self):
        ''' the block command'''
        return self._command
    
    @command.setter
    def command(self, value):
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
    def output_mode(self):
        ''' output mode '''
        return self._output_mode
    
    @output_mode.setter
    def output_mode(self, value):
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
        return self._is_ranged
    @is_ranged.setter
    def is_ranged(self, value):
        self._is_ranged = value
    
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
        is_ranged = False
        if self._command in _simconnect_half_range:
            min_range = 0
            max_range = 16383
            is_ranged = True
        elif self._command in _simconnect_angle_range:
            min_range = 0
            max_range = 360
            is_ranged = True
        elif self._command in _simconnect_egt_range:
            min_range = 0
            max_range = 32767
            is_ranged = True
        elif self.command in _simconnect_full_range:
            min_range = -16383
            max_range = 16383
            is_ranged = True
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
        self._is_ranged = is_ranged
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
    
     
    def execute(self, value = None):
        ''' executes the command '''

        if not self._simconnect_data.is_connected():
            # not connected
            return False
        
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            logger = logging.getLogger("system")
        
        if self._command:
            if self._command_type ==  SimConnectCommandType.Event:
                ae = AircraftEvents(self.sm)
                trigger = ae.find(self._command)
                if trigger:
                    if self.is_readonly:
                        # no param to set
                        logger.info(f"Simconnect: trigger event: {self._command}")
                        trigger()
                    else:
                        logger.info(f"Simconnect: trigger event value: {self._command} {value}")
                        trigger(value)
                    return True
            elif self._command_type == SimConnectCommandType.SimVar:
                # set simvar
                ar = AircraftRequests(self.sm, _time=2000)
                if verbose:
                    logger.info(f"Simconnect: set simvar: {self._command} mode: {self.output_mode}")
                if self.output_mode == SimConnectActionMode.Trigger:
                    mode = self.trigger_mode
                    
                    if mode == SimConnectTriggerMode.Toggle:
                        # get the current state and flip it
                        state = ar.get(self._command)
                        value = 1 if state == 0 else 0
                        ar.set(self._command, value)
                        logger.info(f"\tToggle state: {state} -> {value}")
                    elif mode == SimConnectTriggerMode.TurnOff:
                        ar.set(self._command, 0)
                        logger.info(f"\tTurn off: 0")
                    elif mode == SimConnectTriggerMode.TurnOn:
                        ar.set(self._command, 1)
                        logger.info(f"\tTurn on: 1")
                    elif mode == SimConnectTriggerMode.NoOp:
                        logger.info(f"\tNo op:")
                        ar.set(self._command, 1)
                elif self.output_mode == SimConnectActionMode.SetValue:
                    ar.set(self._command, value)
                    logger.info(f"\tSet value: {value}")
                
                return True
                
                    



            elif self._command_type == SimConnectCommandType.Request and not self._readonly:
                ar = AircraftRequests(self.sm, _time=2000)
                ar.set(self._command, value)
                logger.info(f"Simconnect: set request {self._command} {value}")
                return True

        return False
                

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
            command = SimConnectData().get_default_command()
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

        




                

