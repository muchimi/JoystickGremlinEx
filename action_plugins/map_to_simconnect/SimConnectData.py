
import os
import lxml
from lxml import etree

from PySide6 import QtWidgets, QtCore, QtGui

from gremlin.base_classes import AbstractAction, AbstractFunctor
from gremlin.common import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.macro
import gremlin.ui.common
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




    
        

@SingletonDecorator
class SimConnectData():
    ''' holds simconnect data '''

    def __init__(self) -> None:
        self._sm = SimConnect(auto_connect =False)
        self._aircraft_events = AircraftEvents(self._sm)
        self._aircraft_requests = AircraftRequests(self._sm)

        self._simvars_xml =  os.path.join(gremlin.util.userprofile_path(), "simconnect_simvars.xml")


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

        # list of command blocks
        self._block_map = {}

    
            
        # if the data file doesn't exist, create it in the user's profile folder
        if not os.path.isfile(self._simvars_xml):
            self._write_default_xml(self._simvars_xml)


        # load the data
        if os.path.isfile(self._simvars_xml):
            self._load_xml(self._simvars_xml)

                    
    def _write_default_xml(self, xml_file):
        ''' writes a default XML file from the base data in the simconnect module '''

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
            
        commands = list(self._command_map.keys())
        commands.sort()
        root = etree.Element("commands")
        for command in commands:
            data = self._command_map[command]

            command_node = etree.SubElement(root,"command", value = command)

            value_types = ["(0","16383"]

            if data[0] == "e":
                simvar_type = "event"
                description = data[1][2]
                units = ""
                for v in units:
                    if v in command:
                        units = "int"
                        break
                category = self.get_command_category(command)
                units = ""
                settable = True

            elif data[0] == "r":
                simvar_type = "simvar"
                description = data[1][0]
                units = data[1][2].decode('ascii')
                category = self.get_command_category(command)
                settable = data[1][3] == 'Y'                        

            is_axis = "AXIS_" in command
            is_indexed = ":index" in command

            # simvar index : https://docs.flightsimulator.com/html/Programming_Tools/SimVars/Simulation_Variables.htm#h
            
            command_node.attrib['type'] = simvar_type
            command_node.attrib["units"] = units
            command_node.attrib["category"] = category
            command_node.attrib["settable"] = str(settable)
            command_node.attrib["axis"] = str(is_axis)
            command_node.attrib["indexed"] = str(is_indexed)
            description_node = etree.SubElement(command_node,"description", value = description)

        try:
            # save the file
            tree = etree.ElementTree(root)
            tree.write(xml_file, pretty_print=True,xml_declaration=True,encoding="utf-8")
        except Exception as err:
            logging.getLogger("system").error(f"SimconnectData: unable to create XML simvars: {xml_file}")

    def _load_xml(self, xml_source):
        ''' loads blocks from the XML file '''

        def has_attribute(node : etree._Element, attr) -> bool:
            ''' true if the element has the given attribute '''
            if node is None:
                return False
            return attr in node.attrib.keys()

        self._block_map = {}
        if not xml_source or not os.path.isfile(xml_source):
            logging.getLogger("system").error(f"SimconnectData: unable to load XML simvars: {xml_source}")  
            return False

        try:
            parser = etree.XMLParser(remove_blank_text=True)
            root = etree.parse(xml_source, parser)

            nodes = root.xpath('//command')
            for node in nodes:
                simvar = node.value
                simvar_type = node["type"] if has_attribute(node,"type") else ""
                units = node["units"] if has_attribute(node,"units") else ""
                category = node["category"] if has_attribute(node,"category") else ""
                settable = bool(node["settable"]) if has_attribute(node,"settable") else False
                axis = bool(node["axis"]) if has_attribute(node,"axis") else False
                indexed = bool(node["indexed"]) if has_attribute(node,"indexed") else False
                for child in node:
                    if node.tag == "description":
                        description = node.value
                        break

                block = SimConnectBlock()
                block.command = simvar
                block.command_type = simvar_type
                block.output_data_type = units
                block.category = category
                block.units = units
                block.is_readonly = not settable
                block.is_axis = axis
                block.is_indexed = indexed
                block.description = description

                self._block_map[simvar] = block

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
        if self._sm.ok:
            if not self._sm.running:
                self._sm.connect()
            return self._sm.running
        return False

    def get_category_list(self):
        ''' returns the list of supported command categories '''
        # TODO
        pass
    
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



class SimConnectBlock(QtCore.QObject):
    ''' holds simconnect block information '''
    
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
        




    range_changed = QtCore.Signal(RangeEvent) # fires when the block range values change
    value_changed = QtCore.Signal() # fires when the block output value changes

    def __init__(self, command = None):
        ''' creates a simconnect block object
        
        the block auto-configures itself based on the command, and determines
        range, values and options, and what type of command it is.

        :param command The simconnect command (event or request)
        
        '''
        super().__init__()
        self._command_type = SimConnectBlock.SimConnectCommandType.NotSet
        self._description = None
        self._value_type = SimConnectBlock.OutputType.NotSet
        self._category = SimConnectEventCategory.NotSet
        self._command = None
        self._set_value = False # true if the item can set a value
        self._readonly = False # if readonly - the request cannot be triggered
        self._is_axis = False # true if the output is an axis variable
        self._is_indexed = False # true if the output is indexed using the :index 
        self._min_range = -16383
        self._max_range = 16383
        self._min_range_custom = -16383
        self._max_range_custom = 16383
        self._value = 0 # output value
        self._is_value = False # true if the command supports an output value
        self._is_ranged = False # true if the command is ranged
        self._notify_enabled_count = 0 # true if notifications are enabled
        self._command = command
        self._units = ""
        if command:
            self._update()

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
        self._update()

    @property
    def is_request(self) -> bool:
        ''' true if the block is a request '''
        return self._command_type == SimConnectBlock.SimConnectCommandType.Request
    
    @property
    def is_event(self) -> bool:
        ''' true if the block is an event '''
        return self._command_type == SimConnectBlock.SimConnectCommandType.Event
    
    
    @property
    def is_value(self):
        ''' true if the command supports a value output to simconnect '''
        return self._is_value
    
    
    @property
    def command_type(self):
        ''' returns the command type '''
        return self._command_type
    
    @property
    def display_block_type(self) -> str:
        ''' returns the display string for the block type '''
        if self._command_type == SimConnectBlock.SimConnectCommandType.Request:
            return "Request"
        elif self._command_type == SimConnectBlock.SimConnectCommandType.Event:
            return "Event"
        return ""
    
    @property
    def output_data_type(self):
        ''' block output data type'''
        return SimConnectBlock.OutputType.IntNumber
        
    
    @property
    def category(self) -> str:
        ''' command category '''
        return self._category
    
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
    def data_type(self) -> str:
        ''' Simconnect datatype '''
        return self._output_data_type
    
    @property
    def display_data_type(self) -> str:
        ''' returns a displayable data type even if none is set '''
        if self._value_type == SimConnectBlock.OutputType.IntNumber:
            return "Number (int)"
        elif self._value_type == SimConnectBlock.OutputType.FloatNumber:
            return "Number (float)"
        return "N/A"
        
    
    @property
    def min_range(self):
        ''' current min range '''
        return self._min_range
    
    @property
    def max_range(self):
        ''' current max range '''
        return self._max_range
    
    @property
    def min_range_custom(self):
        ''' custom min range '''

    @min_range_custom.setter
    def min_range_custom(self, value):
        if value < self._min_range:
            value = self._min_range
        if value > self._max_range_custom:
            value = self._max_range_custom
        if value != self._min_range_custom:
            self._min_range_custom = value
            self._notify_range_update()    
        
    
    @property
    def max_range_custom(self):
        ''' custom max range '''
        return self._max_range_custom
    
    @max_range_custom.setter
    def max_range_custom(self, value):
        if value < self._min_range_custom:
            value = self._min_range_custom
        if value > self._max_range:
            value = self._max_range
        if value != self._max_range_custom:
            self._max_range_custom = value
            self._notify_range_update()

    def custom_range_sync(self):
        ''' makes custom range the same as the default range '''
        self._min_range_custom = self._min_range
        self._max_range_custom = self._max_range_custom
        self._notify_range_update()


    def _notify_range_update(self):
        ''' fires a range changed event '''

        if self.notifications_enabled:
            event = SimConnectBlock.RangeEvent()
            event.max = self._max_range
            event.max_custom = self._max_range_custom
            event.min = self._min_range
            event.min_custom = self._min_range_custom
            self.range_changed.emit(event)

    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, number):
        ''' sets the output value'''
        if number != self._value:
            self._value = number
            if self.notifications_enabled:
                self.value_changed.emit()
    
    @property
    def is_ranged(self):
        ''' true if the command is a ranged command (suitable for a range of values)'''
        return self._is_ranged
    
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
        if self._min_range_custom < min_range:
            self._min_range_custom = min_range
            changed = True
        if self._max_range != max_range:
            self._max_range = max_range
            changed = True
        if self._max_range_custom > max_range:
            self._max_range_custom = max_range
            changed = True
        self._is_ranged = is_ranged
        if changed:
            self._notify_range_update()

    # def _update(self):
    #     ''' updates on new command '''
    #     smdata = SimConnectData()
    #     command = self._command
    #     data = smdata.get_command_data(command)   
    #     if data:
    #         self._data = data
    #         if data[0] == "e":
    #             self._command_type = SimConnectBlockType.Event
    #             self._description = data[1][2]
    #             self._value_type = "AXIS_" in command
    #             self._category = smdata.get_command_category(command)
    #             self._readonly = False # can trigger events

    #         elif data[0] == "r":
    #             self._command_type = SimConnectBlockType.Event
    #             self._description = data[1][0]
    #             self._value_type = data[1][2].decode('ascii')
    #             self._category = smdata.get_command_category(command)
    #             self._readonly = data[1][3] != 'Y'

    #         self._set_range()
    #         self._is_value = self._value_type != ""

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
        # if self._command and self._sm_data.ensure_running():
        #     if self._command_type == SimConnectBlockType.Event:
        #         ae = AircraftEvents(self._sm_data.sm)
        #         trigger = ae.find(self._command)
        #         if trigger:
        #             if self._set_value:
        #                 trigger(value)
        #             else:
        #                 trigger()

        #     elif self._command_type == SimConnectBlockType.Request and not self._readonly:
        #         ar = AircraftRequests(self._sm_data.sm, _time=2000)
        #         ar.set(self._command, value)

        #     return True
        return False
                

                

