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
import os

from PySide6 import QtWidgets, QtCore, QtGui

import gremlin.base_profile
import gremlin.config
import gremlin.config
import gremlin.event_handler
import gremlin.execution_graph
from gremlin.input_types import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.macro
import gremlin.shared_state

import gremlin.shared_state
import gremlin.shared_state
import gremlin.singleton_decorator
import gremlin.ui.ui_common
import gremlin.ui.input_item
import gremlin.input_devices
#import gremlin.gated_handler
import enum
from gremlin.profile import safe_format, safe_read
import gremlin.util
from .SimConnectManager import *
import re
from lxml import etree
from lxml import etree as ElementTree
#from gremlin.gated_handler import *
from gremlin.ui.qdatawidget import QDataWidget
import gremlin.config
import gremlin.joystick_handling
import gremlin.actions
import gremlin.curve_handler
from gremlin.input_types import InputType
from action_plugins.map_to_simconnect.SimConnectManager import SimConnectManager

syslog = logging.getLogger("system")

class QHLine(QtWidgets.QFrame):
    def __init__(self, parent = None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)


class CommandValidator(QtGui.QValidator):
    ''' validator for command selection '''
    def __init__(self):
        super().__init__()
        self.commands = SimConnectManager().get_command_name_list()
        
        
    def validate(self, value, pos):
        clean_value = value.upper().strip()
        if not clean_value or clean_value in self.commands:
            # blank is ok
            return QtGui.QValidator.State.Acceptable
        # match all values starting with the text given
        try:
            r = re.compile(clean_value + "*")
            for _ in filter(r.match, self.commands):
                return QtGui.QValidator.State.Intermediate
        except:
            # invalid regex - probably a special char
            pass
        return QtGui.QValidator.State.Invalid
    
class LvarValidator(QtGui.QValidator):
    ''' validator for lvars selection '''
    def __init__(self):
        super().__init__()
        self.manager = SimConnectManager()
        
    def validate(self, value, pos):
        clean_value = value.strip().casefold()
        if not clean_value or clean_value in self.manager.lvars:
            # blank is ok
            return QtGui.QValidator.State.Acceptable
        # match all values starting with the text given
        try:
            r = re.compile(clean_value + "*", re.IGNORECASE)
            for _ in filter(r.match, self.manager.lvars):
                return QtGui.QValidator.State.Intermediate
        except:
            # invalid regex - probably a special char
            pass
        return QtGui.QValidator.State.Invalid    
    
    @property
    def lvars(self):
        return self.manager.lvars

    
class SimconnectSortMode(Enum):
    NotSet = auto()
    AicraftAscending = auto()
    AircraftDescending = auto()
    Mode = auto()

class SimConnectCommandMode(Enum):
    Simvar = 0 # simvar command mode
    Calculator = 1 # lvar command mode
    CalculatorParam = 2 # expression with parameter (axis)
    

    @staticmethod
    def to_string(value) -> str:
        return _simconnect_command_mode_to_string[value]
    
    @staticmethod
    def to_enum(value):
        return _simconnect_command_mode_to_enum[value]
    
    @staticmethod
    def to_display(value) -> str:
        return _simconnect_command_mode_to_display[value]
    
    @staticmethod
    def to_description(value) -> str:
        return _simconnect_command_mode_to_description[value]

_simconnect_command_mode_to_display = {
    SimConnectCommandMode.Simvar : "SimVar",
    SimConnectCommandMode.Calculator : "Calculator",
    SimConnectCommandMode.CalculatorParam : "Calculator (value)",
}

_simconnect_command_mode_to_description = {
    SimConnectCommandMode.Simvar : "Regular simVar",
    SimConnectCommandMode.Calculator : "Evaluated RPN expression and calculator code",
    SimConnectCommandMode.CalculatorParam : "Evaluated RPN expression and calculator code with axis parameter",
}

_simconnect_command_mode_to_string = {
    SimConnectCommandMode.Simvar : "simvar",
    SimConnectCommandMode.Calculator : "rpn",
    SimConnectCommandMode.CalculatorParam : "rpnparam",
}

_simconnect_command_mode_to_enum = {
    "simvar" : SimConnectCommandMode.Simvar,
    "lvar" : SimConnectCommandMode.Calculator,
    "rpn" : SimConnectCommandMode.Calculator,    
    "rpnparam" : SimConnectCommandMode.CalculatorParam,    
}



class SimconnectManualDefinition():
    ''' holds a manual entry for a mode '''
    def __init__(self, 
                 id = None,
                 sim_name = None,
                 mode = None):
        
        self.id = id if id else gremlin.util.get_guid()
        self.sim_name = sim_name
        self.mode = mode

        # runtime item (not saved or loaded)
        self.selected = False # for UI interation - selected mode
        self.error_status = None

    @property
    def display_name(self):
        return f"{self.sim_name}"
    
    @property
    def key(self):
        if self.sim_name:
            return self.sim_name.casefold()
        return ""



    
class SimconnectAicraftDefinition():
    ''' holds the data entry for a single aicraft from the MSFS config data '''
    class EntryType(IntEnum):
        Scan = 0 # entry is coming from the manual scan of the community folder
        Sim = 1 # entry is coming from the sim 
    def __init__(self, id = None, 
                 mode = None, # attached GremlinEx mode for this aicraft
                 icao_type = None, 
                 icao_manufacturer = None, 
                 icao_model = None, 
                 titles = [], 
                 path = None,
                 community_path = None, 
                 aircraft_path = None,
                 state_folder = None,
				 sim_name = None,
                 entry_type = None,
                 ):
        self.icao_type = icao_type
        self.icao_manufacturer = icao_manufacturer
        self.icao_model = icao_model
        self.titles = titles
        self.path = path.casefold() if path else ""
        self.state_folder = state_folder.casefold() if state_folder else ""
        self.mode = mode
        self.sim_name = sim_name
        self.id = id if id else gremlin.util.get_guid()
        self.entry_type = SimconnectAicraftDefinition.EntryType.Scan if entry_type is None else entry_type
        self.community_path = None
        self.aircraft_path = None
        if self.entry_type == SimconnectAicraftDefinition.EntryType.Scan:
            assert community_path and aircraft_path,"Community path and Aircraft path are primary keys and cannot be NULL"
            self.community_path = community_path.casefold()  # AP
            self.aircraft_path = aircraft_path.casefold() # CP
        
        # runtime item (not saved or loaded)
        self.selected = False # for UI interation - selected mode
        self.error_status = None


    @property
    def is_scanned(self) -> bool:
        ''' true if the entry was scanned from the community folder '''
        return self.entry_type == SimconnectAicraftDefinition.EntryType.Scan
    @property
    def is_scanned(self) -> bool:
        ''' true if the entry came from msfs user flyable data '''
        return self.entry_type == SimconnectAicraftDefinition.EntryType.Sim
    
    

    @property
    def display_name(self):
        if self.icao_manufacturer and self.icao_model:
            return f"{self.icao_manufacturer} {self.icao_model}"
        return self.sim_name
    
    @property
    def key(self):
        ''' key for this item (CP = community path, AP = aircraft path)'''
        match self.entry_type:
            case SimconnectAicraftDefinition.EntryType.Scan:
                return (self.community_path, self.aircraft_path) 
            case SimconnectAicraftDefinition.EntryType.Sim:
                return self.sim_name
        return None
        

    @property
    def valid(self):
        ''' true if the item contains valid data '''
        match self.entry_type:
            case SimconnectAicraftDefinition.EntryType.Scan:
                return not self.error_status and self.aircraft_path and self.mode
            case SimconnectAicraftDefinition.EntryType.Sim:
                return bool(self.sim_name) and not self.error_status
        return False
    
    def __hash__(self):
        return hash(self.id)
   
@gremlin.singleton_decorator.SingletonDecorator
class SimconnectOptions():

    ''' holds simconnect mapper options for all actions '''
    def __init__(self, manager : SimConnectManager):
        self._manager : SimConnectManager = manager

        el = gremlin.event_handler.EventListener()
        el.profile_loaded.connect(self._profile_loaded) # trap profile load to update modes
        el.profile_start.connect(self._profile_edit_mode_changed) # trap profile start to update modes
        el.edit_mode_changed.connect(self._profile_edit_mode_changed) # trap edit mode mode changes to update modes
        el.shutdown.connect(self.save) # save configuration on shutdown

        self._handler = SimConnectEventHandler()
        self._handler.simconnect_AircraftLiveriesReceived.connect(self._aircraft_list_loaded)

        


        # configuration file stored in the user's GremlinEx profile
        base_file = "simconnect_config.xml"
        user_source = os.path.join(gremlin.util.userprofile_path(), base_file)
        self._xml_source = user_source

        self._auto_mode_select = True # if set, autoloads the mode associated with the aircraft if such a mode exists, on by default
        self._auto_mode_lock = True # if set, mode changes other the mapped aicraft will be ignored
        self._aircraft_definition_map = {} # holds definitions by aircraft container name, [name] = SimconnectAicraftDefinition
        self._aircraft_manual_definitions = [] # holds manual aicraft entries 
        self._titles = []
        
        self._base_community_folder = None # base of community folder
        self._local_state_folder = None # local state folder for streaming data
        self._community_folder = gremlin.shared_state.community_folder
        self._update_folders()
        

        # last command mode for the UI
        self._last_command_mode = SimConnectCommandMode.Simvar

        self._sort_mode = SimconnectSortMode.NotSet

        self._mode_list = []

        self._simconnect = manager.simconnect

        self.parse_xml()

    @property
    def definitions(self) -> dict:
        return self._aircraft_definition_map

    def validateEntries(self) -> bool:
        ''' validates the manual entries to make sure they are unique '''
        sim_names = []
        for item in self._aircraft_manual_definitions:
            if item.sim_name and item.sim_name in sim_names:
                return False
            sim_names.append(item.sim_name)
        return True



    @QtCore.Slot(dict)
    def _aircraft_list_loaded(self, data):
        ''' triggered when simconnect sends aircraft data '''
        added = False
        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        name_list = [name for name in data.keys()]
        name_list.sort(key = lambda x: x.casefold()) # sort case insensitive
        for aircraft in name_list:
            key = aircraft.casefold()
            if "fsltl" in key or "passiveaircraft" in key:
                # skip FSLTL AI aircraft
                # skip passive aircraft
                continue
            if "a350" in key:
                pass
            if not key in self._aircraft_definition_map:
                item = SimconnectAicraftDefinition(sim_name = aircraft, 
                                                   entry_type=SimconnectAicraftDefinition.EntryType.Sim,
                                                   )
                self._aircraft_definition_map[key] = item
                if verbose: syslog.info(f"SIMCONNECT: add sim user aircraft: {aircraft}")
                added = True
        
        if added:
            # fire the event the data changed
            self._handler.AircraftDefinitionsChanged.emit()


    @QtCore.Slot()
    def _profile_loaded(self):
        ''' profile is loaded '''
        self._mode_list = self.profile.get_modes()

    @QtCore.Slot()
    def _profile_edit_mode_changed(self):
        ''' profile modes changed '''
        self._mode_list = self.profile.get_modes()

    @property
    def profile(self) -> gremlin.base_profile.Profile:
        return gremlin.shared_state.current_profile

    @property
    def current_aircraft_folder(self):
        return self._manager.current_aircraft_folder
    
    @property
    def current_aircraft_title(self):
        return self._manager.current_aircraft_title
    
    @property
    def community_folder(self) -> str:
        return self._community_folder
    @community_folder.setter
    def community_folder(self, value):
        if os.path.isdir(value) and value != self._community_folder:
            self._community_folder = value
            gremlin.shared_state.community_folder = value
            self._update_folders()

    @property
    def local_state_folder(self) -> str:
        return self._local_state_folder


    def _update_folders(self):
        ''' updates the folders from the community folder '''
        community_folder = self._community_folder
        if community_folder and os.path.isdir(community_folder):
            basedir = os.path.dirname(community_folder)
            base_folder = None
            while basedir:
                basename = os.path.basename(basedir)
                if basename.startswith("Microsoft.Limitless"):
                    base_folder = basedir
                    break
                basedir = os.path.dirname(basedir)

            if base_folder:
                self._base_community_folder = base_folder

                # setup the local state folder
                local_state_folder = os.path.join(base_folder, "MSFS2024 LocalState", "StreamedPackages")
                if os.path.isdir(local_state_folder):
                    self._local_state_folder = local_state_folder

            
    @property
    def last_command_mode(self) -> SimConnectCommandMode:
        return self._last_command_mode
    @last_command_mode.setter
    def last_command_mode(self, value: SimConnectCommandMode):
        self._last_command_mode = value

    def validate(self):
        ''' validates options are ok '''
        a_list = []
        valid = True
        for item in self._aircraft_definition_map.values():
            item.error_status = None
            if item.key in a_list:
                item.error_status = f"Duplicate entry found {item.display_name}"
                valid = False
                continue
            a_list.append(item.key)
            if not item.mode:
                item.error_status = f"Mode not selected"
                valid = False
                continue
            if not item.mode in self._mode_list:
                item.error_status = f"Invalid mode {item.mode}"
                valid = False
                continue
            if not item.display_name:
                item.error_status = f"Aircraft name cannot be blank"
                valid = False

        return valid
    
    def find_definition_by_state(self, state_string):
        ''' gets an item based on the state data which is a partial subfolder '''

        # example: SimObjects\\Airplanes\\FNX_320_IAE\\aircraft.CFG
        stub = os.path.dirname(state_string.casefold())

        item : SimconnectAicraftDefinition
        print (stub)
        for item in self._aircraft_definition_map.values():
            print (item.path)
            if item.path.endswith(stub):
                return item
        return None
    
    def dump(self):
        ''' dumps current data to the log file '''
        # syslog = logging.getLogger("system")
        syslog.info("Scanned entry mode configurations:")
        for item in self._aircraft_definition_map.values():
            syslog.info(f"\t{item.display_name} {item.sim_name} mode: {item.mode}")

        syslog.info("Manual entry mode configurations:")
        for item in self._aircraft_manual_definitions:
            syslog.info(f"\t{item.display_name} {item.sim_name} mode: {item.mode}")


    def find_definition_by_sim_name(self, key, is_scan = True, is_manual = True):
        ''' gets an item based on the state data which is a partial subfolder '''
        key = key.casefold()
        verbose = gremlin.config.Configuration().verbose_mode_details
        if verbose: self.dump()
        if is_scan:
            # lookup scanned entries
            if key in self._aircraft_definition_map:
                return self._aircraft_definition_map[key]
            
            return None
        if is_manual:
            # lookup manual entries
            item = next((item for item in self._aircraft_manual_definitions if item.sim_name == key), None)
            if item:
                return item
            return None


    def find_definition_by_aicraft(self, aircraft) -> SimconnectAicraftDefinition:
        ''' gets an item by aircraft name (not case sensitive)'''
        if not aircraft:
            return None
        key = aircraft.casefold().strip()
        item : SimconnectAicraftDefinition
        if key in self._aircraft_definition_map:
            return self._aircraft_definition_map[key]
        return None
    
    def find_definition_by_title(self, title) -> SimconnectAicraftDefinition:
        ''' finds aircraft data by the loaded aircraft title '''
        if not title:
            return None
        item = next((n for n in self._aircraft_definition_map.values() if n.title in item.titles), None)
        return item    

    def find_definition_by_aicraft_folder(self, folder) -> SimconnectAicraftDefinition:
        ''' gets an item by aircraft name (not case sensitive)'''
        if not folder:
            return None
        key = folder.casefold().strip()
        item : SimconnectAicraftDefinition
        item = next((n for n in self._aircraft_definition_map.values() if n.aircraft_path == key), None)
        return item
        
    
    @property
    def auto_mode_select(self):
        ''' true if automatic mode selection for aicraft is enabled '''
        return self._auto_mode_select
    @auto_mode_select.setter
    def auto_mode_select(self, value):
        self._auto_mode_select = value
        
    @property
    def auto_mode_lock(self):
        ''' true if mode locking is enabled '''
        return self._auto_mode_lock and self._auto_mode_select # both must be enabled to lock a profile
    @auto_mode_lock.setter
    def auto_mode_lock(self, value):
        self._auto_mode_lock = value
        


            



    def save(self):
        ''' saves the configuration data '''
        self.to_xml()

    def parse_xml(self, data = None):
        xml_source = self._xml_source
        if not os.path.isfile(xml_source):
            # options not saved yet - ignore
            return
        
    
        self._titles = []
        self._aircraft_manual_definitions = []
        self._aircraft_definition_map.clear()

        
        try:
            parser = etree.XMLParser(remove_blank_text=True)
            root = etree.parse(xml_source, parser)

            nodes = root.xpath('//options')
            for node in nodes:
                if "auto_mode_select" in node.attrib:
                    self._auto_mode_select = safe_read(node,"auto_mode_select",bool,True)
                if "auto_mode_lock" in node.attrib:
                    self._auto_mode_lock = safe_read(node,"auto_mode_lock",bool,True)
                if "community_folder" in node.attrib:
                    self._community_folder = safe_read(node,"community_folder", str, "")
                if "sort" in node.attrib:
                    try:
                        sort_mode = safe_read(node,"sort",int, SimconnectSortMode.NotSet.value)
                        self._sort_mode = SimconnectSortMode(sort_mode)
                    except:
                        self._sort_mode = SimconnectSortMode.NotSet
                        pass
                if "last_command_mode" in node.attrib:
                    self._last_command_mode = SimConnectCommandMode.to_enum(node.get("last_command_mode"))
                break

            # reference items scanned from MSFS
            node_items = None
            nodes = root.xpath("//items")
            for node in nodes:
                node_items = node
                break
            profile = gremlin.shared_state.current_profile
            default_mode = profile.get_default_mode() if profile else None
            if node_items is not None:
                for node in node_items:
                    icao_model = safe_read(node,"model", str, "")
                    icao_manufacturer = safe_read(node,"manufacturer", str, "")
                    icao_type = safe_read(node,"type", str, "")
                    path = safe_read(node,"path", str, "")
                    key = safe_read(node,"key", str, "")

                    if "mode" in node.attrib:
                        mode = node.get("mode")
                    else:
                        mode = default_mode
                    
                    id = safe_read(node,"id", str, "")
                    entry_type_int = safe_read(node,"entry_type",int,0)
                    entry_type = SimconnectAicraftDefinition.EntryType(entry_type_int)

                    state_folder = safe_read(node,"state_folder",str,"")
                    community_path = safe_read(node,"community_path",str,"")
                    aircraft_path = safe_read(node,"aircraft_path",str,"")
                    sim_name = None
                    if "sim_name" in node.attrib:
                        sim_name = node.get("sim_name")

                    if not key and sim_name:
                        key = sim_name.casefold()

                    # print (f"automatic: read mode: {mode} for item: {sim_name}")
                    titles = []
                    node_titles = None
                    for child in node:
                        node_titles = child

                    if node_titles is not None:
                        for child in node_titles:
                            titles.append(child.text)

                    item = SimconnectAicraftDefinition(id = id,
                                                        icao_model = icao_model,
                                                        icao_manufacturer = icao_manufacturer,
                                                        icao_type = icao_type,
                                                        titles = titles,
                                                        path = path,
                                                        mode = mode,
                                                        community_path=community_path,
                                                        aircraft_path=aircraft_path,
                                                        state_folder = state_folder,
                                                        sim_name = sim_name,
                                                        entry_type = entry_type)
                    if not key in self._aircraft_definition_map:
                        self._aircraft_definition_map[key] = item
                    

            node_user_items = root.xpath("//user_items/item")
            verbose = gremlin.config.Configuration().verbose_mode_details
            for node in node_user_items:
                mode = safe_read(node,"mode", str, "")
                id = safe_read(node,"id", str, "")
                sim_name = safe_read(node,"sim_name", str, "")
                item =SimconnectManualDefinition(id, sim_name, mode)
                self._aircraft_manual_definitions.append(item)
                
                if verbose: syslog.info (f"SIMCONNECT: manual: read mode: {mode} for item: {sim_name}")



            node_titles = None
            nodes = root.xpath("//titles")
            for node in nodes:
                node_titles = node
                break
            
            if node_titles is not None:
                for node in node_titles:
                    if node.tag == "title":
                        title = node.text
                        if title:
                            self._titles.append(title)

            # sort the entries according to the current sort mode
            self.sort()


        except Exception as err:
            syslog.error(f"Simconnect Config: XML read error: {xml_source}: {err}")
            return False

    def to_xml(self):
        ''' writes the simconnect options to the xml configuration file '''

        root = etree.Element("simconnect_config")

        node_options = etree.SubElement(root, "options")
        # selection mode
        node_options.set("auto_mode_select",str(self._auto_mode_select))
        # autolock mode
        node_options.set("auto_mode_lock", str(self._auto_mode_lock))

        if self._community_folder and os.path.isdir(self._community_folder):
            # save valid community folder
            node_options.set("community_folder", self._community_folder)
        node_options.set("sort", str(self._sort_mode.value))

        node_options.set("last_command_mode", SimConnectCommandMode.to_string(self._last_command_mode))

        # scanned aicraft titles (local content)
        if self._aircraft_definition_map:
            node_items = etree.SubElement(root,"items")
            for sim_name, item in self._aircraft_definition_map.items():
                node = etree.SubElement(node_items,"item")
                if item.icao_model:
                    node.set("model", item.icao_model)
                if item.icao_manufacturer:
                    node.set("manufacturer", item.icao_manufacturer)
                if item.icao_type:
                    node.set("type",item.icao_type)
                if item.path:
                    node.set("path", item.path)
                node.set("id", item.id)
                node.set("entry_type", str(item.entry_type.value))
                if item.state_folder:
                    node.set("state_folder", item.state_folder)

                if item.sim_name:
                    node.set("sim_name", item.sim_name)
                node.set("key", sim_name)
                

                if item.community_path:
                    node.set("community_path", item.community_path)
                if item.aircraft_path:
                    node.set("aircraft_path", item.aircraft_path)
                if item.mode:
                    node.set("mode", item.mode)
                if item.titles:
                    node_titles = etree.SubElement(node, "titles")
                    for title in item.titles:
                        child = etree.SubElement(node_titles, "title")
                        child.text = title

        # manual entries (usually for streamed entries) - this only has name and mode as we don't have any other info
        if self._aircraft_manual_definitions:
            node_items = etree.SubElement(root,"user_items")
            for item in self._aircraft_manual_definitions:
                node = etree.SubElement(node_items,"item")
                node.set("id", item.id)
                if item.sim_name:
                   node.set("sim_name", item.sim_name)
                else:
                    node.set("sim_name", "")
                    
                if item.mode:
                    node.set("mode", item.mode)
                else:
                    node.set("mode", "")

        
        try:
            # save the file
            tree = etree.ElementTree(root)
            tree.write(self._xml_source, pretty_print=True,xml_declaration=True,encoding="utf-8")
        except Exception as err:
            syslog.error(f"SimconnectData: unable to create XML simvars: {self._xml_source}: {err}")

    def get_community_folder(self):
        ''' looks for the community folder '''
        dir = QtWidgets.QFileDialog.getExistingDirectory(
            None,
            "Select Community Folder",
            dir = self.community_folder
        )
        if dir and os.path.isdir(dir):
            self.community_folder = dir
            return dir
        return None
    
    def _getCommunityFolder(self):
        ''' gets the active community folder - this is user configured in options as there can be multiple installs and versions '''
        from gremlin.ui import ui_common
        if not self._community_folder or not os.path.isdir(self._community_folder):
            folder = self.get_community_folder()
            if os.path.isdir(folder):
               folder = None
            
            self._community_folder = folder
        
        return self._community_folder


    def addManualEntry(self, sim_name: str, mode : str = None):
        ''' adds a manual entry '''
        assert sim_name
        if not mode:
            mode = gremlin.shared_state.current_profile.get_default_mode()
        sim_name = sim_name.casefold()
        item = SimconnectManualDefinition(sim_name = sim_name, mode = mode)
        self._aircraft_manual_definitions.append(item)

    def removeEntry(self, item):
        ''' deletes an entry, scanned or manual - returns True if the entry was deleted'''
        if item:
            if isinstance(item, SimconnectAicraftDefinition) and item in self._aircraft_definitions:
                self._aircraft_definitions.remove(item)
                return True
            if isinstance(item, SimconnectManualDefinition) and item in self._aircraft_manual_definitions:
                self._aircraft_manual_definitions.remove(item)
                return True
        return False

    def removeManualEntry(self, sim_name: str):
        ''' removes a manual entry '''
        assert sim_name
        sim_name = sim_name.casefold()
        item = next((item for item in self._aircraft_manual_definitions if item.sim_name == sim_name), None)
        if item:
            self._aircraft_manual_definitions.remove(item)


    def scan_entry(self, folder):
        ''' scans a single aicraft folder entry '''

        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_simconnect

        community_folder = self._getCommunityFolder()
        if not community_folder:
            syslog.error(f"SIMCONNECT: community folder not found: {community_folder}")
            return

        aicraft_folder = os.path.join(os.path.dirname(community_folder), folder)
        item = self._read_aicraft_config(aicraft_folder)
        if item:
            if verbose:
                syslog.error(f"SIMCONNECT: added aircraft definition: {item.display_name}")
        return item
        
        
    def _fix_entry(self, value):
        if "\"" in value:
            # remove double quotes
            matches = re.findall('"(.*?)"', value)
            if matches:
                value = matches.pop()
            # remove single quote
            matches = re.findall('(.*?)"', value)
            if matches:
                value = matches.pop()

        # value = re.sub(r'[^0-9a-zA-Z\s_-]+', '', value)
        
        return value.strip()

    def _read_aicraft_config(self, aircraft_cfg):
        ''' reads a configuration folder and extracts a configuration object '''
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_simconnect

        if not aircraft_cfg or not os.path.isfile(aircraft_cfg):
            syslog.error(f"SIMCONNECT: aicraft configuration file not found: {aircraft_cfg}")
            return

        cmp_icao_type =  r'(?i)icao_type_designator\s*=\s*\"?(.*?)\"?$'
        cmp_icao_manuf =  r'(?i)icao_manufacturer\s*=\s*\"?(.*?)\"?$'
        cmp_icao_model =  r'(?i)icao_model\s*=\s*\"?(.*?)\"?$'
        cmp_title = r"(?i)title\s*=\s*\"?(.*?)\"?$"


        titles = []
        icao_type = None
        icao_model = None
        icao_manuf = None

        if verbose:
            syslog.info(f"File: {aircraft_cfg}")

        with open(aircraft_cfg, "r", encoding="utf8") as f:
            for line in f.readlines():
                matches = re.findall(cmp_icao_type, line)
                if matches:
                    icao_type = self._fix_entry(matches.pop())
                    continue
                matches = re.findall(cmp_icao_manuf, line)
                if matches:
                    icao_manuf = self._fix_entry(matches.pop())
                    continue
                matches = re.findall(cmp_icao_model, line)
                if matches:
                    icao_model = self._fix_entry(matches.pop())
                    continue

                matches = re.findall(cmp_title, line)
                if matches:
                    titles.extend(matches)
                    
        # extract the root folder in the community folder 

        aircraft_path = os.path.dirname(aircraft_cfg) 
        airplane_path =  os.path.dirname(aircraft_path) 
        simobject_path = os.path.dirname(airplane_path) 
        community_path = os.path.dirname(simobject_path) 

        # rebuild the state folder returned by the sim when it has an active aicraft
        state_folder = os.path.join(community_path, simobject_path, airplane_path, aircraft_path, "aicraft.cfg")

        aircraft_name = os.path.basename(aircraft_path)
        community_name = os.path.basename(community_path)


        sim_name = None
        work_cfg = aircraft_cfg.replace("/", os.sep).casefold()			
        splits = work_cfg.split(os.sep)
        max_index = len(splits)
        index = 0
        while splits[index] != "simobjects" and index < max_index:
            index+=1
        index+=1
        if index < max_index:
            while splits[index] != "airplanes" and index < max_index:
                index+=1
        index+=1
        if index < max_index:
            sim_name = splits[index]
			
        
        if titles:
            titles = list(set(titles))
            titles = [self._fix_entry(t) for t in titles]
            titles.sort()
        if icao_model and icao_type and icao_manuf:
            path = os.path.dirname(aircraft_cfg)
            item = SimconnectAicraftDefinition(icao_type=icao_type,
                                                icao_manufacturer= icao_manuf,
                                                icao_model= icao_model,
                                                titles= titles,
                                                path = path,
                                                community_path = community_name,
                                                aircraft_path = aircraft_name,
                                                state_folder = state_folder,
                                                sim_name = sim_name
                                                )
            
            return item

        return None            


    def scan_aircraft_config(self, owner):
        ''' scans MSFS folders for the list of aircraft names '''
        

        #options = SimconnectOptions()

        community_folder = self.community_folder
        if not community_folder:
            return
        

        # scan for lvars
        #self._scan_lvars()
        
        progress = QtWidgets.QProgressDialog(parent = owner, labelText ="Scanning folders... (this can take a while)", cancelButtonText = "Cancel", minimum = 0, maximum= 100) #, flags = QtCore.Qt.FramelessWindowHint)
        progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress.setValue(0)
        progress.show()
        QtWidgets.QApplication.processEvents()

        # search_folder = os.path.dirname(community_folder)
        # source_files = gremlin.util.find_files(search_folder,"aircraft.cfg")
        # source_folders = [os.path.dirname(file) for file in source_files]

        search_folders = [community_folder]

        # if self._local_state_folder and os.path.isdir(self._local_state_folder):
        #     # add the streamd folders to the list
        #     search_folders.append(self._local_state_folder)


        source_files = []
        for root_folder in search_folders:
            folders = gremlin.util.find_folders(root_folder)


            for folder in folders: 
                # only process simobjects
                ac_root = os.path.join(folder, "SimObjects","Airplanes")
                if not os.path.isdir(ac_root):
                    continue
                ac_folders = gremlin.util.find_folders(ac_root)
                for sf in ac_folders:
                    ac_cfg = os.path.join(sf, "aircraft.cfg")
                    cp_cfg = os.path.join(sf, "cockpit.cfg")
                    if os.path.isfile(ac_cfg) and os.path.isfile(cp_cfg):
                        # valid configuration folder because it has an aicraft.cfg and is a player playable plane because it also has a cockpit.cfg
                        source_files.append(ac_cfg)





        file_count = len(source_files)

        progress.setLabelText = f"SIMCONNECT: Processing {file_count:,} aircraft..."
        verbose = gremlin.config.Configuration().verbose
        
        is_canceled = False
        items = []
        keys = []

        if verbose:
            syslog.info(f"SIMCONNECT: Processing {len(source_files):,}...")
        for count, ac_file in enumerate(source_files):

            
            progress.setValue(int(100 * count / file_count))
            if progress.wasCanceled():
                is_canceled  = True
                break

            item = self._read_aicraft_config(ac_file)
            if item and not item.key in keys:
                # avoid duplicate entries
                items.append(item)
                keys.append(item.key)
                if verbose:
                    syslog.info(f"\tFound: {item.display_name}  folder: {item.community_path} ac: {item.aircraft_path}")

        if not is_canceled:
            # update modes that exist already so they are preserved between scans
            mapped_modes = {}
            for item in self._aircraft_definitions:
                mapped_modes[item.key] = (item.id, item.mode)
            
            self._aircraft_definitions = items

            # sort
            self.sort()
        
            for item in self._aircraft_definitions:
                key = item.key
                if key in mapped_modes.keys():
                    item.id, item.mode = mapped_modes[key]

        self.save()
        progress.close()
        
        #gremlin.util.popCursor()
        
    def sort(self):
        ''' sorts definitions '''
        if self._sort_mode == SimconnectSortMode.AicraftAscending:
            self._aircraft_definitions.sort(key = lambda x: x.key)
            self._aircraft_manual_definitions.sort(key = lambda x: x.key)
        elif self._sort_mode == SimconnectSortMode.AircraftDescending:
            self._aircraft_definitions.sort(key = lambda x: x.key, reverse = True)
            self._aircraft_manual_definitions.sort(key = lambda x: x.key)
        elif self._sort_mode == SimconnectSortMode.Mode:
            self._aircraft_definitions.sort(key = lambda x: (x.mode.casefold(), x.key))
            self._aircraft_manual_definitions.sort(key = lambda x: (x.mode.casefold(), x.key))

@SingletonDecorator
class SimconnectMonitor():
    ''' simconnect monitor


    Monitors current aircraft for profile mode changes
    
    
    
    '''
    def __init__(self):
        # syslog = logging.getLogger("system")
        syslog.info("SCMonitor: listening")
        self._manager = SimConnectManager()
        #self._manager.sim_aircraft_loaded.connect(self._sim_aircraft_loaded)
        self._manager.sim_start.connect(self._sim_start)
        self._manager.sim_stop.connect(self._sim_stop)
        self._manager.registerAircraftChangeCallback(self._sim_aircraft_loaded)
        self._started = False
        self._startup_mode = {}
        self._verbose = gremlin.config.Configuration().verbose_mode_simconnect
        self._verbose_detailed = gremlin.config.Configuration().verbose_mode_details
        self._options = SimconnectOptions(self._manager)
        el= gremlin.event_handler.EventListener()
        el.profile_started.connect(self._profile_start) # trap profile start
        el.profile_stop.connect(self.stop) # trap profile stop
        el.abort.connect(self.stop)
        el.shutdown.connect(self._shutdown) # trap application shutdown
        #el.runtime_mode_changed.connect(self._mode_changed) # trap runtime mode changes - these occur post validation

        self._auto_reconnect_event = threading.Event() # controls reconnect thread exit
        self._enabled = False # default, not enabled - set by profile start event

        


    def getStartupMode(self, name : str = None):
        ''' gets the startup mode for the current aicraft '''

        if self._manager.connected:
            # sim is running

            profile = gremlin.shared_state.current_profile
            if not name:
                name = self._manager.current_aircraft_sim_name

            if name in self._startup_mode:
                return self._startup_mode[name]

            mode = None

            if name:
                #item = self._options.find_definition_by_state(state_folder)
                item = self._options.find_definition_by_sim_name(name)
                if item is not None:
                    # found the aicraft entry
                    key = item.key
                    
                    mode = profile.getSimconnectMode(key)
                    if not mode:
                        mode = item.mode
            if not mode:
                mode = profile.get_start_mode()
                                
            if self._verbose: syslog.info(f"SCMONITOR: Aircraft changed to: [{name}] - activating profile mode [{mode}]")
            self._startup_mode[name] = mode
            return mode
            
        return None
    
    @QtCore.Slot()
    def _profile_start(self):
        ''' occurs when a profile starts '''
        enabled = gremlin.shared_state.getSimConnectEnabled()
        self._startup_mode = {} # reset the mode cache
        self._enabled = enabled
        if enabled:
            syslog.info(f"SCMONITOR: Start")

            # change to the correct mode
            self._manager.request_loaded_aircraft()

            # eh = gremlin.event_handler.EventHandler()
            # eh.registerModeValidator(self._mode_change_validator) # filter mode change requests and discard them if needed to avoid interrupting Simconnect activities
            
            self.start()
        else:
            self.stop() # stop monitoring if it was
            syslog.info(f"SCMONITOR: no simconnect mappings found - start skipped")

    
    def start(self):
        ''' starts monitoring for aicraft changes '''
        if self._started:
            return
        
        # trap abort
        eh = gremlin.event_handler.EventListener()
        eh.abort.connect(self.stop)
        
        # start the reconnect thread
        self._auto_reconnect_thread = threading.Thread(target = self._auto_reconnect_loop, daemon=True)
        self._auto_reconnect_thread.setName("SCMONITOR: auto-reconnect")
        self._auto_reconnect_event.clear()
        self._auto_reconnect_thread.start()
        self._started = True


        self._manager.sim_connect()
        if self._options.auto_mode_select:
            if self._manager.connected:
                self._get_aircraft()
    
    
    def stop(self):
        ''' stop monitoring aircraft changes  '''
        if not self._started:
            return 
        self._auto_reconnect_event.set()
        self._auto_reconnect_thread.join()

        if self._options.auto_mode_select:
            # disconnect the aircraft change notification
            self._manager.sim_aircraft_loaded.disconnect(self._sim_aircraft_loaded)
        self._started = False

    

    def _auto_reconnect_loop(self):
        # in case the sim got restarted or we lost connection 
        while not self._auto_reconnect_event.is_set():
            if not self._manager.running:
                self._manager.ensure_running()
            time.sleep(1)


    def _get_aircraft_list(self):
        ''' requests the current list of aircraft known to the sim'''
        self._manager.request_aircraft_list()

    def _get_aircraft(self):
        ''' updates the current player aircraft in the sim'''
        self._manager.request_loaded_aircraft()



    def _shutdown(self):
        ''' program exit - cleanup monitoring '''
        # syslog = logging.getLogger("system")
        syslog.info("SCMONITOR: shutdown")

        # remove the validator 
        eh = gremlin.event_handler.EventHandler()
        eh.unregisterModeValidator(self._mode_change_validator) 

        # stop
        self.stop()

        # remove the handler for aircraft changes
        if self._options.auto_mode_select:
            self._manager.sim_aircraft_loaded.disconnect(self._sim_aircraft_loaded)

        self._manager = None

    @QtCore.Slot(str, str, str)
    def _sim_aircraft_loaded(self, folder : str, name : str, title : str):
        ''' called when a new aicraft has been detected '''
        # syslog = logging.getLogger("system")
        if title:
            if self._verbose: syslog.info(f"SCMONITOR: Aircraft loaded: [{title}]")
            self.changeModeForAicraft(title)
        

    def changeModeForAicraft(self, title : str):
        ''' changes the mode for the current aircraft '''
        mode = self.getStartupMode(title) # get the mode to use for this profile
        if mode and gremlin.shared_state.runtime_mode != mode:
            # suitable mode found - if this is the current mode - change_mode will do nothing
            self.change_mode(mode)
        return mode


    @QtCore.Slot()
    def _sim_start(self):
        ''' sim started event '''
        # syslog = logging.getLogger("system")
        if self._verbose: syslog.info(f"SCMONITOR: sim start")


    @QtCore.Slot()
    def _sim_stop(self):
        ''' sim stop event '''
        # syslog = logging.getLogger("system")
        if self._verbose: syslog.info(f"SCMONITOR: sim stop")
        eh = gremlin.event_handler.EventListener()
        eh.request_profile_stop.emit("Sim Stop")

    def _mode_change_validator(self, new_mode) -> bool:
        ''' hook called when a request for a mode change is made.
            this checks to see if the mode is locked by option '''
        if not gremlin.shared_state.is_running:
            # allow mode change while at edit/design time
            return True
        
        # syslog = logging.getLogger("system")
        if self._verbose: syslog.info(f"SCMONITOR: Profile mode change request to: {new_mode}")
        mode = self.getStartupMode()
        if mode and mode != new_mode and self._options.auto_mode_lock:
            # not allowed
            if self._verbose: syslog.warning(f"SCMONITOR: per option request denied - aicraft mode lock is enabled and locked to mode [{mode}]")
            return False
        
        # allowed
        return True

    def change_mode(self, mode):
        ''' force a mode change 
        This only changes the mode if we're not already in the mode and the mode exists.
        '''
        eh = gremlin.event_handler.EventHandler()
        eh.change_mode(mode, validate = False)

 


        




class SimconnectOptionsUi(gremlin.ui.ui_common.QRememberDialog):
    """UI to set individual simconnect  settings """

    def __init__(self, simconnect : SimConnect, parent=None):
        from gremlin.ui import ui_common
        super().__init__(self.__class__.__name__, parent = parent)

        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self._manager = SimConnectManager()
        self._manager.activate()
        self._manager.sim_aircraft_loaded.connect(self._aircraft_loaded)
        self._manager.sim_state.connect(self._sim_state)
        self._verbose = gremlin.config.Configuration().verbose_mode_simconnect
        
        self.options = SimconnectOptions(simconnect)
        self._data = None # sorted list of aircraft definitions

        self._handler = SimConnectEventHandler()
        self._handler.AircraftDefinitionsChanged.connect(self._aircraft_list_loaded)

        self._current_page = 0 # page number displayed
        self._page_size = 25 # how many entries to display at a time
        self._page_count = 0 # number of pages available
        self._start_index = 0
        self._end_index = 0
        self._page_number = 1


        self._mode_selector_map = {}
        self._selected_cb_map = {}
        self._manual_mode_selector_map = {}
        self._manual_selected_cb_map = {}



        self._content_widget = gremlin.ui.ui_common.QContentWidget()
        self._content_widget.resized.connect(self._content_resized)
        self._content_widget.setContentsMargins(0,0,0,0)

        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical, self._content_widget)

        self._top_panel_widget = QtWidgets.QWidget()
        self._top_panel_widget.setContentsMargins(0,0,0,0)
        self._top_panel_widget.setMinimumWidth(200)

        self._bottom_panel_widget = QtWidgets.QWidget()
        self._bottom_panel_widget.setContentsMargins(0,0,0,0)

        self._top_panel_layout = QtWidgets.QVBoxLayout(self._top_panel_widget)
        self._top_panel_layout.setContentsMargins(0,0,0,0)

        self._bottom_panel_layout = QtWidgets.QVBoxLayout(self._bottom_panel_widget)
        self._bottom_panel_layout.setContentsMargins(0,0,0,0)

        self._splitter.addWidget(self._top_panel_widget)
        self._splitter.addWidget(self._bottom_panel_widget)
        self._splitter.setStretchFactor(0,1)
        self._splitter.setStretchFactor(1,1)

   
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)

        # Actual configuration object being managed
        self.config = gremlin.config.Configuration()
        self.setMinimumWidth(600)


        self.mode_list = []
        self.profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        self.mode_list = self.profile.get_modes()
        

        # display name to mode pair list
        self.mode_pair_list = gremlin.ui.ui_common.get_mode_list(self.profile)

        is_dark = gremlin.shared_state.is_dark_theme   
        prefix = "dark_" if is_dark else ""

        self.setWindowTitle("Simconnect Options")
        self.installEventFilter(self) # trap some events

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self._auto_mode_switch = QtWidgets.QCheckBox("Change profile mode based on active aicraft")
        self._auto_mode_switch.setToolTip("When enabled, the profile mode will automatically change based on the mode associated with the active player aircraft in Flight Simulator")
        self._auto_mode_switch.setChecked(self.options.auto_mode_select)
        self._auto_mode_switch.clicked.connect(self._auto_mode_select_cb)

        self._auto_mode_lock = QtWidgets.QCheckBox("Lock the mode to the active aicraft")
        self._auto_mode_lock.setToolTip("When enabled, the profile mode mapped to the aircraft will stay locked in that mode and other mode changes will be ignored.\nThis prevents inadvertent loss of control due to other GremlinEx actions.")
        self._auto_mode_lock.setChecked(self.options.auto_mode_select)
        self._auto_mode_lock.clicked.connect(self._auto_mode_lock_cb)
        

        self._msfs_path_widget = ui_common.QPathLineItem(header="MSFS Community Folder", text = self.options.community_folder, dir_mode=True)
        self._msfs_path_widget.pathChanged.connect(self._community_folder_changed_cb)
        self._msfs_path_widget.open.connect(self._community_folder_open_cb)

        self._mode_from_aircraft_button_widget = QtWidgets.QPushButton("Mode from Aicraft")
        self._mode_from_aircraft_button_widget.clicked.connect(self._mode_from_aircraft_button_cb)

        # toolbar for map
        self.container_bar_widget = QtWidgets.QWidget()
        self.container_bar_layout = QtWidgets.QHBoxLayout(self.container_bar_widget)
        self.container_bar_layout.setContentsMargins(0,0,0,0)


        self.edit_mode_widget = QtWidgets.QPushButton()
        
        manage_modes_icon = "gfx/dark_manage_modes.svg" if is_dark else "gfx/manage_modes.svg"
        self.edit_mode_widget.setIcon(ui_common.load_icon(manage_modes_icon))
        self.edit_mode_widget.clicked.connect(self._manage_modes_cb)
        self.edit_mode_widget.setToolTip("Manage Modes")

        
        # self.scan_aircraft_widget = QtWidgets.QPushButton("Scan Aircraft")
        # self.scan_aircraft_widget.setIcon(gremlin.util.load_icon("mdi.magnify-scan"))
        # self.scan_aircraft_widget.clicked.connect(self._scan_aircraft_cb)
        # self.scan_aircraft_widget.setToolTip("Scan MSFS aicraft folders for aircraft names")

        line_entry_width = 250

        self.current_aircraft_widget = ui_common.QDataLineEdit()
        self.current_aircraft_widget.setReadOnly(True)
        self.current_aircraft_widget.setMinimumWidth(line_entry_width)


        self.current_aircraft_folder = None # holds the active aircraft data folder (from the sim)
        self.current_aircraft_title = None # holds the active aicraft title (from the sim)
        self.current_aircraft_name = None # holds the active aicraft name (from the sim)

        self.refresh_current_aircraft_widget = QtWidgets.QPushButton("Get Current Aircraft")
        self.refresh_current_aircraft_widget.clicked.connect(self._refresh_aircraft_cb)
        #self.refresh_current_aircraft_widget.setIcon(gremlin.util.load_icon("ei.refresh"))
        self.refresh_current_aircraft_widget.setToolTip("Queries the current aircraft loaded in the sim")
        #self.refresh_current_aircraft_widget.setMaximumWidth(24)


        self.add_current_aircraft_widget = QtWidgets.QPushButton("Add Current Aircraft")
        self.add_current_aircraft_widget.clicked.connect(self._add_current_aircraft_cb)
        self.add_current_aircraft_widget.setToolTip("Adds the aircraft to the manual list if it doesn't exist")

        # self.add_manual_entry_widget = QtWidgets.QPushButton("Add Manual Entry")
        # self.add_manual_entry_widget.setToolTip("Adds a manual entry")
        # self.add_manual_entry_widget.clicked.connect(self.add_entry_cb)

        self.paginator_widget = gremlin.ui.ui_common.QPaginator(page_size = self._page_size)
        self.paginator_widget.pageChanged.connect(self._handle_paginator)

        
        row_widgets = [QtWidgets.QLabel("Current Aircraft:"),
                       self.current_aircraft_widget,
                       self.add_current_aircraft_widget,
                       #self.add_manual_entry_widget,
                       #QtWidgets.QLabel(" "),
                       self.refresh_current_aircraft_widget,
                       self.edit_mode_widget
        ]

        widget, layout = gremlin.ui.ui_common.getGridContainer(row_widgets)
        self.container_bar_widget = widget
        self.container_bar_layout = layout



        self.filter_widget = QtWidgets.QLineEdit()
        self.filter_widget.returnPressed.connect(self._handle_search) # on enter, do the search
        self.filter_widget.setMinimumWidth(line_entry_width)
        
        self.apply_filter_widget = QtWidgets.QPushButton("Search")
        self.apply_filter_widget.clicked.connect(self._handle_search)
        self.apply_filter_widget.setToolTip("Search aicraft using the current filter")

        self.clear_filter_widget = QtWidgets.QPushButton("Clear Search")
        self.clear_filter_widget.clicked.connect(self._handle_clear_search)
        self.clear_filter_widget.setToolTip("Clears the search filter")

        self.filter_current_widget  = QtWidgets.QPushButton("Search Current")
        self.filter_current_widget.clicked.connect(self._handle_current_search)
        self.filter_current_widget.setToolTip("Search for current aircraft")


        self.refresh_aircraft_list_widget = QtWidgets.QPushButton("Refresh All")
        self.refresh_aircraft_list_widget.setToolTip("Refresh the available aircraft list from MSFS")
        self.refresh_aircraft_list_widget.setIcon(gremlin.util.load_icon("ei.refresh"))
        self.refresh_aircraft_list_widget.clicked.connect(self._handle_refresh_aircraft_list)
        

        row_widgets = [QtWidgets.QLabel("Filter:"), 
                        self.filter_widget,
                        self.apply_filter_widget,
                        self.clear_filter_widget,
                        self.filter_current_widget,
                        self.refresh_aircraft_list_widget,
                       ]
        
        widget, layout = gremlin.ui.ui_common.getGridContainer(row_widgets)
        self.container_navigation_widget = widget
        self.container_navigation_layout = layout

        self.grid_sync_widgets = [self.container_navigation_widget, self.container_bar_widget]

        page_sizes = [10, 25, 50, 100]
        widgets = [self.paginator_widget]
        for size in page_sizes:
            widget = ui_common.QDataPushButton(str(size),size)
            widget.clicked.connect(self._handle_page_size)
            widgets.append(widget)

        widget, layout = gremlin.ui.ui_common.getHContainer(widgets, left_stretch=True)
        self.container_paginator_widget = widget
        self.container_paginator_layout = layout
        
        

        # start scrolling container widget definition

        self.container_map_widget = QtWidgets.QWidget()
        self.container_map_layout = QtWidgets.QVBoxLayout(self.container_map_widget)
        self.container_map_layout.setContentsMargins(0,0,0,0)

        # self.manual_container_map_widget = QtWidgets.QWidget()
        # self.manual_container_map_layout = QtWidgets.QVBoxLayout(self.manual_container_map_widget)
        # self.manual_container_map_layout.setContentsMargins(0,0,0,0)

        # add aircraft map items
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()


        # add manual aircraft map items
        # self.manual_scroll_area = QtWidgets.QScrollArea()
        # self.manual_scroll_widget = QtWidgets.QWidget()
        # self.manual_scroll_layout = QtWidgets.QVBoxLayout()

        # Configure the widget holding the layout with all the buttons
        self.scroll_widget.setLayout(self.scroll_layout)
        self.scroll_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding
        )
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        # Configure the scroll area
        #self.scroll_area.setMinimumWidth(300)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)

        self.map_widget = QtWidgets.QWidget()
        self.map_layout = QtWidgets.QGridLayout(self.map_widget)
        self.map_layout.setContentsMargins(0,0,0,0)

        self.manual_map_widget = QtWidgets.QWidget()
        self.manual_map_layout = QtWidgets.QGridLayout(self.manual_map_widget)
        self.manual_map_layout.setContentsMargins(0,0,0,0)

        

        self.scroll_layout.addWidget(self.map_widget)
        self.scroll_layout.setContentsMargins(6,0,6,0)
        self.scroll_layout.addStretch()


        self.container_map_layout.addWidget(self.scroll_area)

        # end scrolling container widget definition

        
        self.close_button_widget = QtWidgets.QPushButton("Close")
        self.close_button_widget.clicked.connect(self.close_button_cb)
        
        # disables as MSFS 2024 doesn't have flight save/flight load in a working state currently
        # self.save_flight_widget = QtWidgets.QPushButton("Save Flight")
        # self.save_flight_widget.clicked.connect(self._handle_save_flight)
        

        # self.load_flight_widget = QtWidgets.QPushButton("Load Flight")
        # self.load_flight_widget.clicked.connect(self._handle_load_flight)

        button_bar_widget = QtWidgets.QWidget()
        button_bar_layout = QtWidgets.QHBoxLayout(button_bar_widget)

        # button_bar_layout.addWidget(self.save_flight_widget)
        # button_bar_layout.addWidget(self.load_flight_widget)
        button_bar_layout.addStretch()
        button_bar_layout.addWidget(self.close_button_widget)

        top_bar_container_widget = QtWidgets.QWidget()
        top_bar_container_layout = QtWidgets.QHBoxLayout(top_bar_container_widget)

        top_bar_container_layout.addWidget(self._auto_mode_switch)
        top_bar_container_layout.addWidget(self._auto_mode_lock)
        top_bar_container_layout.addStretch()
        
        self.main_layout.addWidget(top_bar_container_widget)
        self.main_layout.addWidget(self._msfs_path_widget)
        self.main_layout.addWidget(self.container_bar_widget)
        self.main_layout.addWidget(self.container_navigation_widget)
        self._top_panel_layout.addWidget(self.container_map_widget)
        self._top_panel_layout.addWidget(self.container_paginator_widget)
        #self._bottom_panel_layout.addWidget(self.manual_container_map_widget)


        warning_container = QtWidgets.QWidget()
        warning_layout = QtWidgets.QHBoxLayout(warning_container)
        warning_color = gremlin.ui.ui_common.Color.warningColor()
        self.warning_widget = gremlin.ui.ui_common.QIconLabel("ph.shield-warning-fill",use_qta=True,icon_color=QtGui.QColor(warning_color),text="Error goes here", use_wrap=False)
        self.warning_widget.setVisible(False)
        warning_layout.addWidget(self.warning_widget)
        warning_layout.addStretch()
        
        
        self.main_layout.addWidget(self._content_widget, stretch = 3)

        self.main_layout.addWidget(warning_container)

        self.main_layout.addWidget(button_bar_widget)
        

        
        

        # figure out the size of the header part of the control so things line up
        lbl = QtWidgets.QLabel("w")
        char_width = lbl.fontMetrics().averageCharWidth()
        headers = ["Aicraft:"]
        width = 0
        for header in headers:
            width = max(width, char_width*(len(header)))

        self._width = width
        self._char_width = char_width


        self._update_current_aircraft() # refresh sim data
        self._update_data() # update display
        

    @QtCore.Slot()
    def _profile_edit_mode_changed(self):
        ''' called when profile modes have been edited or changed '''
        self.mode_pair_list = gremlin.ui.ui_common.get_mode_list(self.profile)
        self._populate_ui()


    def _set_warning(self, message = None):
        ''' displays a warning in the UI, set to None to clear'''
        if message:
            self.warning_widget.setText(message)
            self.warning_widget.setVisible(True)
        else:
            self.warning_widget.setVisible(False)

    @QtCore.Slot(QtCore.QSize)
    def _content_resized(self, size : QtCore.QSize):
        ''' called when the container object is resized '''

        # resize the splitter to the container's size as it doesn't happen by itself for some reason
        width = self._content_widget.frameGeometry().width()
        height = self._content_widget.frameGeometry().height()
        if width > 0:
            self._splitter.setFixedWidth(width)
            self._splitter.setFixedHeight(height)        

    @QtCore.Slot()
    def _manage_modes_cb(self):
        import gremlin.shared_state
        gremlin.shared_state.ui.manage_modes()
        self._populate_ui()

    @QtCore.Slot(object)
    def _community_folder_open_cb(self, widget):
        ''' opens the profile list '''
        dir = self.options.get_community_folder()
        if dir:
            with QtCore.QSignalBlocker(widget):
                widget.setText(dir)

    @QtCore.Slot(object, str)
    def _community_folder_changed_cb(self, widget, text):
        if os.path.isdir(text):
            self.options.community_folder = text
             

    def closeEvent(self, event):
        ''' occurs on window close '''
        self.options.save()
        profile = gremlin.shared_state.current_profile
        if profile:
            profile.save()
        super().closeEvent(event)

    @QtCore.Slot(bool)
    def _auto_mode_select_cb(self, checked):
        ''' auto mode changed'''
        self.options.auto_mode_select = checked

    @QtCore.Slot(bool)
    def _auto_mode_lock_cb(self, checked):
        ''' auto mode lock changed'''
        self.options.auto_mode_lock = checked


    @QtCore.Slot()
    def _scan_aircraft_cb(self):
        if not self._manager.connected:
            self._manager.activate()
        if self._manager.connected:
            self._manager.request_aircraft_list() # get aircraft list

        # stop scanning community folder
        #self.options.scan_aircraft_config(self)

        # update the aicraft drop down choices
        #self._populate_ui()

    def _update_current_aircraft(self):
        ''' request an update from simconnect on the current aircraft '''
        if not self._manager.connected:
            self._manager.activate()
        if self._manager.connected:
            self._manager.request_loaded_aircraft() # will trigger the aircraft loaded callback 

    def _update_aircraft_list(self):
        if not self._manager.connected:
            self._manager.activate()
        if self._manager.connected:
            self._manager.request_aircraft_list() # get aircraft list
            

    @QtCore.Slot()
    def _refresh_aircraft_cb(self):
        ''' refreshes the current aircraft '''
        self._update_current_aircraft()
        

    @QtCore.Slot()
    def _add_current_aircraft_cb(self):
        ''' adds the current simconnect aircraft to the mode list '''
        name = self.current_aircraft_widget.text()
        folder = self.current_aircraft_folder

        if folder and os.path.isdir(folder):
            # local entry
            if not self.options.find_definition_by_sim_name(name, is_manual = False):
                self.options.scan_entry(folder)
                self._populate_ui()
            else:
                gremlin.ui.ui_common.MessageBox(title = "Duplicate Entry", prompt = f"Entry {name} already exists")
        else:
            # manual entry
            item = self.options.find_definition_by_sim_name(name, is_scan = False)
            if not item:
                # only add it if not there
                self.options.addManualEntry(name)
                self._populate_ui()
            else:
                gremlin.ui.ui_common.MessageBox(title = "Duplicate Entry", prompt = f"Entry {name} already exists")
            

    @QtCore.Slot()
    def _remove_current_aircraft_cb(self):
        ''' remove button '''
        widget = self.sender()
        item, _ = widget.data

        # confirm
        msgbox = gremlin.ui.ui_common.ConfirmBox(f"Remove {item.sim_name}?")
        result = msgbox.show()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            if item and self.options.removeEntry(item):
                self._populate_ui()

    def _validate_entries(self):
        ''' ensures the manual entries are unique '''
        valid = self.options.validateEntries()
        if not valid:
            self._set_warning("Warning: duplicate manual aicraft entries detected.  The first entry will be used.")
        else:
            self._set_warning()

    @QtCore.Slot(str,str,str)
    def _aircraft_loaded(self, folder, name, title):
        ''' triggered when simconnect sends aircraft data '''
        self.current_aircraft_widget.setText(title)
        self.current_aircraft_widget.setToolTip(title)
        self.current_aircraft_folder = folder
        self.current_aircraft_title = title
        self.current_aircraft_name = name
        add_enabled = bool(title)
        self.add_current_aircraft_widget.setEnabled(add_enabled)

    @QtCore.Slot()
    def _aircraft_list_loaded(self):
        ''' triggered when simconnect sends aircraft data '''
        self._update_data()        

    @QtCore.Slot()
    def _handle_page_size(self):
        widget = self.sender()
        count = widget.data
        self.paginator_widget.setPageSize(count)


    def _update_data(self):
        ''' re-index the data '''

        definitions = self.options.definitions
        item_count = len(definitions)
        if self.paginator_widget.itemCount != item_count:
            self.paginator_widget.setItemCount(item_count, False)
            self.paginator_widget.setPageNumber(1, False)

        data = [item for item in definitions.values()]
        # sort the data
        data.sort(key = lambda x: x.sim_name)
        self._data = data
        self._populate_ui()



    @QtCore.Slot(int, float, str)
    def _sim_state(self, int_data, float_data_, str_data):
        ''' triggered on state requests '''
        # the data will be returned as a partial subfolder so we need to match it to the actual aircraft

        item = self.options.find_definition_by_state(str_data)
        if item:
            self._aircraft_loaded(item.path, item.display_name)

    @QtCore.Slot()
    def add_entry_cb(self):
        item = SimconnectManualDefinition()
        self.options._aircraft_manual_definitions.append(item)
        self._update_manual_list()
        


    @QtCore.Slot()
    def close_button_cb(self):
        ''' called when close button clicked '''
        self.close()

    @QtCore.Slot()
    def _handle_save_flight(self):
        pass
        #self._manager.save_flight("c:\\gremlinex_test_flight.flt","test save","test description")

    @QtCore.Slot()
    def _handle_load_flight(self):
        pass
        #self._manager.load_flight("c:\\gremlinex_test_flight.flt")


    @QtCore.Slot()
    def _handle_clear_search(self):
        ''' clears the filter '''
        self.filter_widget.setText("")
        self._update_data()

    @QtCore.Slot()
    def _handle_refresh_aircraft_list(self):
        ''' refresh the list of aircraft '''
        self._update_aircraft_list()

    @QtCore.Slot()
    def _handle_current_search(self):
        ''' search on current aircraft entry '''
        filter = self.current_aircraft_widget.text()
        self.filter_widget.setText(filter)
        self._search(filter)

    def _search(self, filter : str):
        ''' handles the search '''
        if not filter:
            self._update_data()
        else:
            pattern = re.compile(filter,re.IGNORECASE)
            definitions = self.options.definitions
            data = [item for item in definitions.values() if pattern.search(item.sim_name)]
            data.sort(key = lambda x: x.sim_name)
            item_count = len(data)
            if self.paginator_widget.itemCount != item_count:
                self.paginator_widget.setItemCount(item_count, False)
                self.paginator_widget.setPageNumber(1, False)
            self._data = data
            self._populate_ui()


    @QtCore.Slot()
    def _handle_search(self):
        ''' handles a search '''
        filter = self.filter_widget.text()
        self._search(filter)
        




    @QtCore.Slot(int,int,int)
    def _handle_paginator(self, page_number, start_index, end_index):
        self._start_index = start_index
        self._end_index = end_index
        self._page_number = page_number
        self._populate_ui()

    def _update_scanned_list(self):
        ''' updates the regular scanned or sim list '''


        # clear the widgets
        gremlin.ui.ui_common.clear_layout(self.map_layout)

        # display one row per aicraft found
        if not self._data:
             missing = QtWidgets.QLabel("No mappings found.")
             missing.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
             self.map_layout.addWidget(missing)
             return

        gremlin.util.pushCursor()

        item : SimconnectAicraftDefinition

        self._mode_selector_map = {}
        self._selected_cb_map = {}
        self._manual_mode_selector_map = {}
        self._manual_selected_cb_map = {}

        row = 0
        display_width = self._width

        # current profile
        profile = gremlin.shared_state.current_profile
        default_mode = profile.get_default_mode()

        icon_color = gremlin.ui.ui_common.Color.normalColor()
        
        create_mode_icon = gremlin.util.load_icon("fa5.plus-square", qta_color=icon_color)
        
        start_index = self.paginator_widget.startIndex
        end_index = self.paginator_widget.endIndex
        for item in self._data[start_index:end_index]:

            # header row
            if row == 0:
      
                select_widget = QtWidgets.QCheckBox()
                select_widget.clicked.connect(self._global_selected_changed_cb)
                select_widget.setToolTip("Select/Deselect All")

                aircraft_header_widget = QtWidgets.QWidget()
                aircraft_header_layout = QtWidgets.QHBoxLayout(aircraft_header_widget)

                # sim_name_widget = QtWidgets.QLabel("Sim Name")

                self.display_header_widget = QtWidgets.QLabel("Aircraft")
                aircraft_header_layout.addWidget(self.display_header_widget)
                display_sort_up_widget = QtWidgets.QPushButton()

                display_sort_up_widget.setIcon(gremlin.util.load_icon("mdi.sort-ascending", qta_color=icon_color))
                display_sort_up_widget.setMaximumWidth(20)
                display_sort_up_widget.clicked.connect(self._sort_display_up_cb)
                display_sort_up_widget.setStyleSheet("border: none;")
                display_sort_up_widget.setToolTip("Sort aircraft ascending")

                display_sort_down_widget = QtWidgets.QPushButton()
                display_sort_down_widget.setIcon(gremlin.util.load_icon("mdi.sort-descending", qta_color=icon_color))
                display_sort_down_widget.setMaximumWidth(20)
                display_sort_down_widget.clicked.connect(self._sort_display_down_cb)
                display_sort_down_widget.setStyleSheet("border: none;")
                display_sort_down_widget.setToolTip("Sort aircraft descending")

                aircraft_header_layout.addStretch()
                aircraft_header_layout.addWidget(display_sort_up_widget)
                aircraft_header_layout.addWidget(display_sort_down_widget)

                mode_header_widget = QtWidgets.QWidget()
                mode_header_layout = QtWidgets.QHBoxLayout(mode_header_widget)

                mode_sort_up_widget = QtWidgets.QPushButton()
                mode_sort_up_widget.setIcon(gremlin.util.load_icon("mdi.sort-ascending", qta_color=icon_color))
                mode_sort_up_widget.setMaximumWidth(20)
                mode_sort_up_widget.clicked.connect(self._sort_mode_up_cb)
                mode_sort_up_widget.setStyleSheet("border: none;")
                mode_sort_up_widget.setToolTip("Sort by mode")

        
                mode_widget = QtWidgets.QLabel("Profile Mode")
                mode_header_layout.addWidget(mode_widget)
                mode_header_layout.addStretch()
                mode_header_layout.addWidget(mode_sort_up_widget)
                




                # manufacturer_widget = QtWidgets.QLabel("Manufacturer")

                # type_widget = QtWidgets.QLabel("Type")
                # model_widget = QtWidgets.QLabel("Model")
                # community_widget = QtWidgets.QLabel("Community Folder")
                # aircraft_widget = QtWidgets.QLabel("Aircraft Folder")


                row_selector = gremlin.ui.ui_common.QRowSelectorFrame()
                row_selector.setSelectable(False)
                spacer = QDataWidget()
                spacer.setMinimumWidth(3)
                self.map_layout.addWidget(row_selector, 0, 0, 1, -1)
                
                col = 1
                self.map_layout.addWidget(spacer, row, col)
                col+=1
                self.map_layout.addWidget(select_widget, 0, col)
                col+=1
                self.map_layout.addWidget(aircraft_header_widget, 0, col)
                # col+=1
                # self.map_layout.addWidget(sim_name_widget, 0, col)
                col+=2
                self.map_layout.addWidget(mode_header_widget, 0, col)
                # col+=1
                # self.map_layout.addWidget(manufacturer_widget, 0, col)
                # col+=1
                # self.map_layout.addWidget(model_widget, 0, col)
                # col+=1
                # self.map_layout.addWidget(type_widget, 0, col)
                # col+=1
                # self.map_layout.addWidget(community_widget, 0, col)
                # col+=1
                # self.map_layout.addWidget(aircraft_widget, 0, col)
                # col+=1

                row+=1
                

            
             # selector
            row_selector = gremlin.ui.ui_common.QRowSelectorFrame(selected = item.selected)
            row_selector.setMinimumHeight(30)
            row_selector.selected_changed.connect(self._row_selector_clicked_cb)
            selected_widget = gremlin.ui.ui_common.QDataCheckbox(data = (item, row_selector))
            selected_widget.setChecked(item.selected)
            selected_widget.checkStateChanged.connect(self._selected_changed_cb)
            row_selector.data = ((item, selected_widget))

            # aicraft display
            self.display_header_widget = gremlin.ui.ui_common.QDataLineEdit(data = (item, selected_widget))
            self.display_header_widget.setReadOnly(True)
            self.display_header_widget.setText(item.display_name)
            self.display_header_widget.setToolTip(item.display_name)
            self.display_header_widget.installEventFilter(self)
            w = len(item.display_name)* self._char_width
            if w > display_width:
                display_width = w


            name_widget = gremlin.ui.ui_common.QDataLineEdit(data = (item, selected_widget))
            name_widget.setReadOnly(True)
            if item.sim_name:
                name_widget.setText(item.sim_name)
            name_widget.installEventFilter(self)    

            # # manufacturer
            # manufacturer_widget = gremlin.ui.ui_common.QDataLineEdit(data = (item, selected_widget))
            # manufacturer_widget.setReadOnly(True)
            # manufacturer_widget.setText(item.icao_manufacturer if item.icao_manufacturer else "n/a")
            # manufacturer_widget.installEventFilter(self)

            # # model
            # model_widget = gremlin.ui.ui_common.QDataLineEdit(data = (item, selected_widget))
            # model_widget.setReadOnly(True)
            # model_widget.setText(item.icao_model if item.icao_model else "n/a")
            # model_widget.installEventFilter(self)

            # # type
            # type_widget = gremlin.ui.ui_common.QDataLineEdit(data = (item, selected_widget))
            # type_widget.setReadOnly(True)
            # type_widget.setText(item.icao_type if item.icao_type else "n/a")
            # type_widget.installEventFilter(self)


            # mode drop down
            mode_selector = gremlin.ui.ui_common.QDataComboBox(data = (item, selected_widget), wheel_enabled=False)

   

            for display_mode, mode in self.mode_pair_list:
                mode_selector.addItem(display_mode, mode)

            mode = profile.getSimconnectMode(item.key)
            if not mode:
                mode = item.mode
            if not mode:
                mode = default_mode

            index = mode_selector.findData(mode)
            mode_selector.setCurrentIndex(index)
            mode_selector.currentIndexChanged.connect(self._mode_selector_changed_cb)
            self._mode_selector_map[item] = mode_selector
            self._selected_cb_map[item] = selected_widget


            create_mode_widget = gremlin.ui.ui_common.QDataPushButton()
            create_mode_widget.setIcon(create_mode_icon)
            create_mode_widget.data = (item, select_widget)
            create_mode_widget.setMaximumWidth(24)
            create_mode_widget.clicked.connect(self._create_mode_cb)
            create_mode_widget.setToolTip(f"Create mode {item.sim_name}")
                

            self.map_layout.addWidget(row_selector, row ,0 , 1, -1)
            
            spacer = QDataWidget()
            spacer.setMinimumWidth(3)
            spacer.installEventFilter(self)
            
            col = 1
            self.map_layout.addWidget(spacer, row, col)
            col +=1
            self.map_layout.addWidget(selected_widget, row, col)
            col +=1
            self.map_layout.addWidget(self.display_header_widget, row, col)
            col +=1
            # self.map_layout.addWidget(name_widget, row, col)
            # col +=1
            self.map_layout.addWidget(create_mode_widget, row, col)
            col +=1
            self.map_layout.addWidget(mode_selector, row, col)
            # col +=1
            # self.map_layout.addWidget(manufacturer_widget,row, col)
            # col +=1
            # self.map_layout.addWidget(model_widget,row, col)
            # col +=1
            # self.map_layout.addWidget(type_widget,row, col)
            col +=1
            # self.map_layout.addWidget(community_widget,row, col)
            # col +=1
            # self.map_layout.addWidget(aircraft_widget,row, col)
            # col +=1

            spacer = QDataWidget()
            spacer.installEventFilter(self)
            spacer.setMinimumWidth(6)
            self.map_layout.addWidget(spacer, row, 8)


            row += 1


        self.map_layout.setColumnStretch(3,2)
        display_width = min(display_width, 250)
        self.map_layout.setColumnMinimumWidth(3, display_width)



    def _update_manual_list(self):
        ''' updates the manual user entries '''

        # manual entries
        # clear the widgets
        gremlin.ui.ui_common.clear_layout(self.manual_map_layout)
        if not self.options._aircraft_manual_definitions:
            missing = QtWidgets.QLabel("No manual mappings found.")
            missing.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
            self.manual_map_layout.addWidget(missing)
            return
        
        create_mode_icon = gremlin.util.load_icon("fa5.plus-square")

        profile = gremlin.shared_state.current_profile
        default_mode = profile.get_default_mode()

        # headers

        delete_icon = gremlin.util.load_icon("fa6.trash-can")
        row = 0
        for item in self.options._aircraft_manual_definitions:

            if row == 0:


                row_selector = gremlin.ui.ui_common.QRowSelectorFrame()
                row_selector.setSelectable(False)
                spacer = QDataWidget()
                spacer.setMinimumWidth(3)

                select_widget = QtWidgets.QCheckBox()
                select_widget.clicked.connect(self._global_selected_changed_cb)
                select_widget.setToolTip("Select/Deselect All")


                sim_name_widget = QtWidgets.QLabel("Manual Entry Sim Name")
                mode_widget = QtWidgets.QLabel("Mode")


                self.manual_map_layout.addWidget(row_selector, 0, 0, 1, -1)
                
                col = 1
                self.manual_map_layout.addWidget(spacer, 0, col)
                col += 2
                self.manual_map_layout.addWidget(sim_name_widget, 0, col)
                col += 2
                self.manual_map_layout.addWidget(mode_widget, 0, col)
                row +=1 
                



            # selector
            row_selector = gremlin.ui.ui_common.QRowSelectorFrame(selected = item.selected)
            row_selector.setMinimumHeight(30)
            row_selector.selected_changed.connect(self._row_selector_clicked_cb)
            selected_widget = gremlin.ui.ui_common.QDataCheckbox(data = (item, row_selector))
            selected_widget.setChecked(item.selected)
            selected_widget.checkStateChanged.connect(self._selected_changed_cb)
            row_selector.data = ((item, selected_widget))

            # name_widget = gremlin.ui.ui_common.QDataLineEdit(data = (item, selected_widget))
            # if item.sim_name:
            #     name_widget.setText(item.sim_name)
            # name_widget.valueChanged.connect(self._name_changed_cb)
            # name_widget.installEventFilter(self) 

            delete_widget = gremlin.ui.ui_common.QDataPushButton()
            delete_widget.setIcon(delete_icon)
            delete_widget.setMaximumWidth(24)
            delete_widget.data = (item, selected_widget)
            delete_widget.clicked.connect(self._remove_current_aircraft_cb)

            # mode drop down
            mode_selector = gremlin.ui.ui_common.QDataComboBox(data = (item, selected_widget))
   

            for display_mode, mode in self.mode_pair_list:
                mode_selector.addItem(display_mode, mode)

 
            
            mode = profile.getSimconnectMode(item.key)
            if not mode:
                mode = item.mode
            if not mode:
                mode = default_mode

            index = mode_selector.findData(mode)
            mode_selector.setCurrentIndex(index)


            mode_selector.currentIndexChanged.connect(self._mode_selector_changed_cb)
            self._manual_mode_selector_map[item] = mode_selector
            self._manual_selected_cb_map[item] = selected_widget

            create_mode_widget = gremlin.ui.ui_common.QDataPushButton()
            create_mode_widget.setIcon(create_mode_icon)
            create_mode_widget.data = (item, select_widget)
            create_mode_widget.setMaximumWidth(24)
            create_mode_widget.clicked.connect(self._create_mode_cb)
            create_mode_widget.setToolTip(f"Create mode {item.sim_name}")

            spacer = QDataWidget()
            spacer.setMinimumWidth(3)
            spacer.installEventFilter(self)
            
            self.manual_map_layout.addWidget(row_selector, row , 0 , 1, -1)
            col = 1
            self.manual_map_layout.addWidget(spacer, row, col)
            col +=1
            self.manual_map_layout.addWidget(selected_widget, row, col)
            col +=1
            # self.manual_map_layout.addWidget(name_widget, row, col)
            # col +=1
            self.manual_map_layout.addWidget(create_mode_widget, row, col)
            col +=1
            self.manual_map_layout.addWidget(mode_selector, row, col)
            col +=1
            self.manual_map_layout.addWidget(delete_widget, row, col)
            col +=1

            self._selected_cb_map[item] = selected_widget

            # next row
            row += 1
        
        # update any warnings
        self._validate_entries()

    @QtCore.Slot(str)
    def _name_changed_cb(self):
        widget = self.sender()
        data = widget.data
        item, _ = data
        item.sim_name = widget.text()
        self._validate_entries()

    def _populate_ui(self):
        ''' populates the map of aircraft to profile modes '''

        from gremlin.ui import ui_common
        self.options.validate()

        gremlin.util.pushCursor()

        self._update_scanned_list()
        # self._update_manual_list()


        # mode locking is only enabled if auto mode change enabled
        self._auto_mode_lock.setEnabled(self._auto_mode_switch.isChecked())

        # sync the grids
        gremlin.ui.ui_common.synchronize_grids(self.grid_sync_widgets)

        gremlin.util.popCursor(True)


    @QtCore.Slot()
    def _sort_display_up_cb(self):
        # sorts data by aicraft name
        self.options._sort_mode = SimconnectSortMode.AicraftAscending
        self.options.sort()
        self._populate_ui()
        self.scroll_area.ensureVisible(0,0)
        
    @QtCore.Slot()
    def _sort_display_down_cb(self):
        # sorts data by aicraft name reversed
        self.options._sort_mode = SimconnectSortMode.AircraftDescending
        self.options.sort()
        self._populate_ui()
        self.scroll_area.ensureVisible(0,0)

    @QtCore.Slot()
    def _sort_mode_up_cb(self):
        # sorts data by mode
        self.options._sort_mode = SimconnectSortMode.Mode
        self.options.sort()
        self._populate_ui()
        self.scroll_area.ensureVisible(0,0)
        

    @QtCore.Slot(bool)
    def _global_selected_changed_cb(self, checked):
        for item in self._selected_cb_map.keys():
            self._selected_cb_map[item].setChecked(checked)


    def _get_selected(self):
        ''' gets the items that are selected '''
        return [item for item in self._data if item.selected]


    @QtCore.Slot(bool)
    def _selected_changed_cb(self, state):
        widget = self.sender()
        item, row_selector = widget.data
        checked = widget.isChecked() # param is an enum - ignore
        item.selected = checked
        row_selector.selected = checked

    @QtCore.Slot()
    def _row_selector_clicked_cb(self):
        widget = self.sender()
        checked = widget.selected
        item, selector_widget = widget.data
        item.selected = checked
        with QtCore.QSignalBlocker(selector_widget):
            selector_widget.setChecked(checked)

            

    def eventFilter(self, widget, event):
        ''' ensure line changes are saved '''
        t = event.type()
        if t == QtCore.QEvent.Type.MouseButtonPress and hasattr(widget, "data"):
            item, selected_widget = widget.data
            selected_widget.setChecked(not selected_widget.isChecked())
            return True # handled

        elif t == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            if key == QtCore.Qt.Key.Key_Enter:
                if widget == self.filter_widget:
                    widget.returnPressed.emit()
                elif widget == self._msfs_path_widget:
                    self._community_folder_open_cb()
            return True # handled
        return super().eventFilter(widget, event)


    @QtCore.Slot()
    def _create_mode_cb(self):
        ''' create a mode in the profile for the aircraft '''
        widget = self.sender()
        item, _ = widget.data
        profile = gremlin.shared_state.current_profile
        if not profile.is_mode(item.sim_name):
            default_mode = profile.get_default_mode()
            profile.add_mode(item.sim_name, default_mode)
            # display the UI box
            dialog = gremlin.ui.dialogs.ModeManagerUi(profile)
            dialog.setWindowModality(QtCore.Qt.ApplicationModal)
            dialog.show()
        else:
            gremlin.ui.ui_common.MessageBox(prompt=f"Mode {item.sim_name} already exists in the profile.")
        

    @QtCore.Slot(int)
    def _mode_selector_changed_cb(self, selected_index):
        ''' occurs when the mode is changed on an entry '''
        profile = gremlin.shared_state.current_profile
        widget = self.sender()
        mode = widget.currentData()
        item, _ = widget.data
        items = self._get_selected()
        if not item in items:
            # include the current item if not in the selection
            items.append(item)
        mode_index = None
        for item in items:
            key = item.key
            if item in self._mode_selector_map:
                selector = self._mode_selector_map[item]
                with QtCore.QSignalBlocker(selector):
                    if mode_index is None:
                        mode_index = selector.findData(mode)
                    selector.setCurrentIndex(mode_index)
                item.mode = mode
                profile.setSimconnectMode(key, mode)
                print (f"set mode {mode} for {item.sim_name}")



    @QtCore.Slot()
    def _active_button_cb(self):
        widget = self.sender()
        sm = SimConnectManager()
        
        aircraft = sm.get_aircraft()
        if aircraft:
            item = widget.data
            item.aircraft = aircraft

        
    @QtCore.Slot()
    def _mode_from_aircraft_button_cb(self):
        ''' mode from aicraft button '''
        aircraft, model, title = self._sm_data.get_aircraft_data()
        if self._verbose: syslog.info(f"Aircraft: {aircraft} model: {model} title: {title}")
        if not title in self._mode_list:
            self.profile.add_mode(title)
            



            





class MapToSimConnectWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to keyboard key combinations - adds extra functionality to the base module ."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """

        # call super last because it will call create_ui and populate_ui so the vars must exist
        super().__init__(action_data, parent=parent)


    def _create(self, action_data):
        '''' initialize before createUI() '''
        
        self.action_data : MapToSimConnect = action_data
        self.action_data.events.range_changed.connect(self._action_range_changed)
        

        self._simconnect = SimConnectManager().simconnect

        # handler to update curve widget if displayed
        self.curve_update_handler = None
        self.input_type = self.action_data.hardware_input_type 
        self._is_axis = self.action_data.input_is_axis()
        self._current_value = 0 # value of the current axis input for the repeater

        self.manager = SimConnectManager()
        self.manager.lvars_updated.connect(self._lvars_udpated_cb)



    @QtCore.Slot()
    def _action_range_changed(self):
        ''' occurs when the range update to the action data caused another update '''
        self._update_ui()

    def _create_ui(self):
        """Creates the UI components."""
        #import gremlin.gated_handler

        verbose = gremlin.config.Configuration().verbose_mode_detailed
        # syslog = logging.getLogger("system")
        if verbose:
            syslog.info(f"Simconnect UI for: {self.action_data.hardware_input_type_name}  {self.action_data.hardware_device_name} input: {self.action_data.hardware_input_id}")

        warning_color = gremlin.ui.ui_common.Color.warningColor()
        self._warning_widget = gremlin.ui.ui_common.QIconLabel("ph.shield-warning-fill",use_qta=True,icon_color=QtGui.QColor(warning_color),text="Parameter Calculation requires a {#} marker in the expression where the output value goes.", use_wrap=False)

        # if the input is chained 
        self.chained_input = self.action_data.input_item.is_action

        # mode from aircraft button - grabs the aicraft name as a mode
        self._options_button_widget = QtWidgets.QPushButton("Simconnect Options")
        self._options_button_widget.setIcon(gremlin.util.load_icon("fa6s.gear"))
        self._options_button_widget.clicked.connect(self._show_options_dialog_cb)



      
        # holds type options - visible for manual entries
        self._type_container_widget = QtWidgets.QWidget()
        self._type_container_widget.setContentsMargins(0,0,0,0)
        self._type_container_layout = QtWidgets.QHBoxLayout(self._type_container_widget)
        self._type_container_layout.setContentsMargins(0,0,0,0)        


        # holds data entry mode options 
        data = [(SimConnectCommandMode.to_display(mode),
                 mode,
                 SimConnectCommandMode.to_description(mode)
                 ) for mode in SimConnectCommandMode]

        self._mode_container_widget, self._mode_container_layout = gremlin.ui.ui_common.getRadioContainer(data,
                                                                                self._command_mode_changed_cb,
                                                                                default =self.action_data.command_mode,
                                                                                label="Simconnect mode:")
        self._mode_container_layout.addWidget(self._options_button_widget)



        # type options
        self._type_is_calculator_widget = QtWidgets.QCheckBox("RPN (Calculator) code")

        self._type_is_settable_widget = QtWidgets.QCheckBox("Settable")

        self._type_datatype_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._type_units_widget = gremlin.ui.ui_common.QDataLineEdit()

        self._type_container_layout.addWidget(self._type_is_calculator_widget)
        self._type_container_layout.addWidget(self._type_is_settable_widget)
        self._type_container_layout.addWidget(QtWidgets.QLabel("Datatype:"))
        self._type_container_layout.addWidget(self._type_datatype_widget)
        self._type_container_layout.addWidget(QtWidgets.QLabel("Units:"))
        self._type_container_layout.addWidget(self._type_units_widget)
        self._type_container_layout.addStretch()


        
        # command selector
        self._command_container_widget = QtWidgets.QWidget()
        self._command_container_widget.setContentsMargins(0,0,0,0)
        self._command_container_layout = QtWidgets.QVBoxLayout(self._command_container_widget)
        self._command_container_layout.setContentsMargins(0,0,0,0)


        # actions elector 
        self._action_selector_widget = QtWidgets.QWidget()
        self._action_selector_widget.setContentsMargins(0,0,0,0)
        self._action_selector_layout = QtWidgets.QHBoxLayout(self._action_selector_widget)
        self._action_selector_layout.setContentsMargins(0,0,0,0)


        # calculator selector
        self._calculator_container_widget = QtWidgets.QWidget()
        self._calculator_container_widget.setContentsMargins(0,0,0,0)
        self._calculator_container_layout = QtWidgets.QVBoxLayout(self._calculator_container_widget)
        self._calculator_container_layout.setContentsMargins(0,0,0,0)

        # calculator release selector
        self._calculator_release_container_widget = QtWidgets.QWidget()
        self._calculator_release_container_widget.setContentsMargins(0,0,0,0)
        self._calculator_release_container_layout = QtWidgets.QVBoxLayout(self._calculator_release_container_widget)
        self._calculator_release_container_layout.setContentsMargins(0,0,0,0)

        # list of possible events to trigger
        self._command_selector_widget = gremlin.ui.ui_common.QComboBox()
        self._command_list = self.action_data._manager.get_command_name_list()
        self._command_selector_widget.setEditable(True)
        self._command_selector_widget.addItems(self._command_list)
        self._command_selector_widget.currentIndexChanged.connect(self._command_changed_cb)
        self._command_selector_widget.setValidator(CommandValidator())
        self._command_selector_widget.setMinimumWidth(200)

        # setup auto-completer for the command
        self._command_completer = QtWidgets.QCompleter(self._command_selector_widget.validator().commands, self)
        self._command_completer.setCaseSensitivity(QtGui.Qt.CaseSensitivity.CaseInsensitive)
        self._command_completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        self._command_selector_widget.setCompleter(self._command_completer)

        data = [("Block",SimConnectCommandType.SimVar),
                ("LVAR",SimConnectCommandType.LVar)]
        self._simvar_mode_container_widget, _ = gremlin.ui.ui_common.getRadioContainer(data, self._command_type_changed, default = self.action_data.command_type,label="Simvar mode:" )
        
        self._lvar_command_widget = QtWidgets.QLineEdit()
        self._lvar_command_widget.setText(self.action_data.command)
        self._lvar_command_widget.textChanged.connect(self._lvar_changed_cb)
        self._lvar_container_widget, _ = gremlin.ui.ui_common.getHContainer(self._lvar_command_widget,"Set LVAR:")

        self._command_container_layout.addWidget(self._simvar_mode_container_widget)
        self._command_container_layout.addWidget(self._action_selector_widget)
        self._command_container_layout.addWidget(self._lvar_container_widget)


        # lvar lookup container
        self._lvar_lookup_container_widget = QtWidgets.QWidget()
        self._lvar_lookup_container_widget.setContentsMargins(0,0,0,0)
        self._lvar_lookup_container_layout = QtWidgets.QHBoxLayout(self._lvar_lookup_container_widget)
        self._lvar_lookup_container_layout.setContentsMargins(0,0,0,0)

        self._refresh_lvar_widget = QtWidgets.QPushButton("Lvars")
        self._refresh_lvar_widget.setIcon(gremlin.util.load_icon("ei.refresh"))
        self._refresh_lvar_widget.clicked.connect(self._refresh_lvar_cb)


        # list of possible lvars to trigger
        self._lvar_selector_widget = gremlin.ui.ui_common.QComboBox()
        self._lvar_selector_widget.setEditable(True)
        self._lvar_selector_widget.addItems(self.manager.get_lvar_name_list())
        self._lvar_selector_widget.currentIndexChanged.connect(self._command_changed_cb)
        self._lvar_selector_widget.setValidator(LvarValidator())
        self._lvar_selector_widget.setMinimumWidth(200)
        self._lvar_selector_widget.setToolTip("LVAR lookup")

        self._lvar_button_widget = QtWidgets.QPushButton("Add")
        self._lvar_button_widget.setToolTip("Adds to the calculator expression")
        self._lvar_button_widget.clicked.connect(self._lvar_selected_cb)

        # setup auto-completer for the lvar
        self._lvar_completer = QtWidgets.QCompleter(self._lvar_selector_widget.validator().lvars, self)
        self._lvar_completer.setCaseSensitivity(QtGui.Qt.CaseSensitivity.CaseInsensitive)
        self._lvar_completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)

        self._lvar_selector_widget.setCompleter(self._lvar_completer)

        self._lvar_lookup_container_layout.addWidget(QtWidgets.QLabel("LVAR lookup:"))
        self._lvar_lookup_container_layout.addWidget(self._lvar_selector_widget)
        self._lvar_lookup_container_layout.addWidget(self._lvar_button_widget)
        self._lvar_lookup_container_layout.addWidget(self._refresh_lvar_widget)
        self._lvar_lookup_container_layout.addStretch()


        # calculator entry
        self._calculator_entry_widget = QtWidgets.QTextEdit()
        self._calculator_entry_widget.setAcceptRichText(False)
        self._calculator_entry_widget.setToolTip("RPN calculator expression sent to MSFS")
        self._calculator_entry_widget.setMinimumWidth(200)
        self._calculator_entry_widget.setPlainText(self.action_data.command)
        self._calculator_entry_widget.textChanged.connect(self._expression_changed_cb)


        self._calculator_release_entry_widget = QtWidgets.QTextEdit()
        self._calculator_release_entry_widget.setAcceptRichText(False)
        self._calculator_release_entry_widget.setToolTip("RPN calculator expression sent to MSFS on input release")
        self._calculator_release_entry_widget.setMinimumWidth(200)
        self._calculator_release_entry_widget.setPlainText(self.action_data.command_release)
        self._calculator_release_entry_widget.textChanged.connect(self._expression_release_changed_cb)

        self._calculator_container_layout.addWidget(QtWidgets.QLabel("RPN Expression:"))
        self._calculator_container_layout.addWidget(self._calculator_entry_widget)


        self._calculator_release_container_layout.addWidget(QtWidgets.QLabel("RPN Expression on release:"))
        self._calculator_release_container_layout.addWidget(self._calculator_release_entry_widget)

        
        self._autorepeat_container_widget = QtWidgets.QWidget()
        self._autorepeat_container_layout = QtWidgets.QHBoxLayout(self._autorepeat_container_widget)


        self._autorepeat_widget = QtWidgets.QCheckBox("Autorepeat")
        self._autorepeat_widget.setChecked(self.action_data.auto_repeat)
        self._autorepeat_widget.clicked.connect(self._auto_repeat_state_changed)
        self._autorepeat_widget.setToolTip("When enabled, the command will repeat at set interval while the input is pressed")

        self._autorepeat_delay_label = QtWidgets.QLabel("Repeat Interval (ms)")
        self._autorepeat_delay_widget = gremlin.ui.ui_common.QIntLineEdit()
        self._autorepeat_delay_widget.setRange(0, 20000)
        width = gremlin.ui.ui_common.get_char_width(8)
        self._autorepeat_delay_widget.setMaximumWidth(width)
        self._autorepeat_delay_widget.setValue(self.action_data.auto_repeat_interval)
        self._autorepeat_delay_widget.valueChanged.connect(self._auto_repeat_delay_changed)


        self._release_command_widget = QtWidgets.QCheckBox("Separate Release Expression")
        self._release_command_widget.setToolTip("If enabled, a separate expression will be sent on input release")
        self._release_command_widget.setChecked(self.action_data.is_release_command)
        self._release_command_widget.clicked.connect(self._is_release_command_changed)


        self._autorepeat_container_layout.addWidget(self._release_command_widget)
        self._autorepeat_container_layout.addWidget(self._autorepeat_widget)
        self._autorepeat_container_layout.addWidget(self._autorepeat_delay_label)
        self._autorepeat_container_layout.addWidget(self._autorepeat_delay_widget)
        self._autorepeat_container_layout.addStretch()



        self._calculator_container_layout.addWidget(self._autorepeat_container_widget)
        

        #self.action_selector_layout.addWidget(self.category_widget)
        self._action_selector_layout.addWidget(QtWidgets.QLabel("Selected command:"))
        self._action_selector_layout.addWidget(self._command_selector_widget)
        self._action_selector_layout.addStretch()

        
        self._action_selector_widget.setContentsMargins(0,0,0,0)
        

        self._output_mode_container_widget = QtWidgets.QWidget()
        self._output_mode_container_widget.setContentsMargins(0,0,0,0)
        self._output_mode_container_layout = QtWidgets.QHBoxLayout(self._output_mode_container_widget)
        self._output_mode_container_layout.setContentsMargins(0,0,0,0)
        self._output_mode_readonly_widget = QtWidgets.QRadioButton("Read/Only")
        self._output_mode_readonly_widget.setEnabled(False)
        

        # set range of values output mode (axis input only)
        self._output_mode_ranged_widget = QtWidgets.QRadioButton("Ranged")
        self._output_mode_ranged_widget.clicked.connect(self._mode_ranged_cb)
        self._output_mode_ranged_widget.setToolTip("Sets the output as a linear axis to the simconnect command.<br>The output is scaled to the specified output range as defined by the command or manually.")
        
        # trigger output mode (event trigger only)
        self._output_mode_trigger_widget = QtWidgets.QRadioButton("Trigger")
        self._output_mode_trigger_widget.clicked.connect(self._mode_trigger_cb)
        self._output_mode_trigger_widget.setToolTip("Triggers a simconnect command (for momentary inputs only like a button or a hat)")

        self._output_mode_description_widget = QtWidgets.QLabel()
        self._output_mode_container_layout.addWidget(QtWidgets.QLabel("Output mode:"))


        # set value output mode (output value only)
        self._output_mode_set_value_widget = QtWidgets.QRadioButton("Value")
        self._output_mode_set_value_widget.clicked.connect(self._mode_value_cb)
        self._output_mode_set_value_widget.setToolTip("Sends a single value to the simconnect command regardless of the input.")

        self._output_mode_container_layout.addWidget(self._output_mode_readonly_widget)
        self._output_mode_container_layout.addWidget(self._output_mode_trigger_widget)
        self._output_mode_container_layout.addWidget(self._output_mode_set_value_widget)
        self._output_mode_container_layout.addWidget(self._output_mode_ranged_widget)
        self._output_mode_container_layout.addStretch()

        self.output_readonly_status_widget = QtWidgets.QLabel("Read only")
        self._output_mode_container_layout.addWidget(self.output_readonly_status_widget)

        self._button_mode_container_widget = QtWidgets.QWidget()
        self._button_mode_container_layout = QtWidgets.QHBoxLayout(self._button_mode_container_widget)

        self._trigger_on_release_widget = QtWidgets.QCheckBox("Trigger on release")
        self._trigger_on_release_widget.setToolTip("When enabled, the action will trigger when the input is released.")
        self._trigger_on_release_widget.clicked.connect(self._trigger_on_release_cb)

        self._trigger_on_press_widget = QtWidgets.QCheckBox("Trigger on press")
        self._trigger_on_press_widget.setToolTip("When enabled, the action will trigger when the input is released.")
        self._trigger_on_press_widget.clicked.connect(self._trigger_on_press_cb)


        self._button_mode_container_layout.addWidget(self._trigger_on_press_widget)
        self._button_mode_container_layout.addWidget(self._trigger_on_release_widget)
        self._button_mode_container_layout.addStretch()




        # output data type UI
        self._output_data_type_widget = QtWidgets.QWidget()
        self._output_data_type_widget.setContentsMargins(0,0,0,0)
        self._output_data_type_layout = QtWidgets.QHBoxLayout(self._output_data_type_widget)
        self._output_data_2_type_widget = QtWidgets.QWidget()
        self._output_data_2_type_widget.setContentsMargins(0,0,0,0)
        self._output_data_2_type_layout = QtWidgets.QHBoxLayout(self._output_data_2_type_widget)


        self._output_data_type_layout.setContentsMargins(0,0,0,0)
        
        self._output_data_type_label_widget = QtWidgets.QLabel("Not Set")

        
        
        self._output_data_type_layout.addWidget(self._output_data_type_label_widget)
        self._output_data_type_layout.addWidget(self._output_mode_description_widget)
        self._output_data_type_layout.addStretch()

        self._output_data_2_type_layout.addWidget(QtWidgets.QLabel("<b>Output type:</b>"))
        self._output_data_2_type_layout.addStretch()
        


        # output range UI
        self._output_range_container_widget = QtWidgets.QWidget()
        self._output_range_container_widget.setContentsMargins(0,0,0,0)
        self._output_range_container_layout = QtWidgets.QVBoxLayout(self._output_range_container_widget)
        self._output_range_container_layout.setContentsMargins(0,0,0,0)

        # output value widget - displays a min/max range or a fixed value
        self._value_widget = gremlin.ui.ui_common.QJoystickRangeWidget(show_mode_change=False, 
                                                                       min_norm= self.action_data.normalized_min_range,
                                                                       max_norm= self.action_data.normalized_max_range,
                                                                       min_cmd= self.action_data.command_min_range,
                                                                       max_cmd= self.action_data.command_max_range,
                                                                       min_range=-16383,
                                                                       max_range=16384,
                                                                       parent = self)
        self._value_widget.valueChanged.connect(self._value_changed)
        self._value_widget.rangeChanged.connect(self._range_changed)
        self._value_widget.invertChanged.connect(self._inverted_changed)
        
        # output range buttons
        widget, layout = gremlin.ui.ui_common.getHContainer()
        self._range_button_container_widget = widget
        self._range_button_container_layout = layout

        self._output_range_ref_text_widget = QtWidgets.QLabel()
        self._output_range_container_layout.addWidget(self._value_widget)
        self._output_range_container_layout.addWidget(self._range_button_container_widget)

        w = gremlin.ui.ui_common.get_text_width("0000000.0000")


        self._reset_range_widget = QtWidgets.QPushButton("Reset")
        self._reset_range_widget.setToolTip("Reset the range to -1 +1")
        self._reset_range_widget.clicked.connect(self._reset_range)

        # output axis repeater
        self.container_repeater_widget = QtWidgets.QWidget()
        self.container_repeater_layout = QtWidgets.QHBoxLayout(self.container_repeater_widget)

         
        self.curve_button_widget = QtWidgets.QPushButton("Output Curve")
        active_color = gremlin.ui.ui_common.Color.activeColor()
        normal_color = gremlin.ui.ui_common.Color.normalColor()
        self.curve_icon_inactive = gremlin.util.load_icon("mdi.chart-bell-curve",qta_color=normal_color)
        self.curve_icon_active = gremlin.util.load_icon("mdi.chart-bell-curve",qta_color=active_color)
        
        self.curve_button_widget.setToolTip("Curve output")
        self.curve_button_widget.clicked.connect(self._curve_button_cb)

        self.curve_clear_widget = QtWidgets.QPushButton("Clear curve")
        delete_icon = gremlin.util.load_icon("mdi.delete")
        self.curve_clear_widget.setIcon(delete_icon)
        self.curve_clear_widget.setToolTip("Removes the curve output")
        self.curve_clear_widget.clicked.connect(self._curve_delete_button_cb)

        self._axis_repeater_widget = gremlin.ui.ui_common.AxisStateWidget(show_percentage=True,orientation=QtCore.Qt.Orientation.Horizontal)
        self._axis_value_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self._axis_value_widget.setRange(-16383, 16384)
        self._axis_value_widget.setReadOnly(True)
        self._axis_value_widget.setMinimumWidth(w)
        self._axis_value_widget.setDecimals(0)


        # self._axis_alt_repeater_widget = gremlin.ui.ui_common.AxisStateWidget(show_percentage=True,orientation=QtCore.Qt.Orientation.Horizontal)
        # self._axis_alt_value_widget = gremlin.ui.ui_common.QFloatLineEdit()
        # self._axis_alt_value_widget.setReadOnly(True)
        # self._axis_alt_value_widget.setMinimumWidth(w)
        # self._axis_alt_value_widget.setDecimals(0)

        self._calculator_value_widget = QtWidgets.QPlainTextEdit()
        self._calculator_value_widget.setReadOnly(True)


        self.container_repeater_layout.addWidget(self.curve_button_widget)
        self.container_repeater_layout.addWidget(self.curve_clear_widget)
        self.container_repeater_layout.addWidget(self._axis_repeater_widget)
        #self.container_repeater_layout.addWidget(self._axis_alt_repeater_widget)
        self.container_repeater_layout.addWidget(QtWidgets.QLabel("SimConnect Output:"))
        self.container_repeater_layout.addWidget(self._axis_value_widget)
        self.container_repeater_layout.addWidget(self._calculator_value_widget)
        self.container_repeater_layout.addStretch()
        self._update_curve_icon()


        if self.action_data.input_type == InputType.JoystickAxis:
            self._update_axis_widget()


        self._range_button_container_layout.addWidget(QtWidgets.QLabel("Presets:"))


        widget = gremlin.ui.ui_common.QDataPushButton("Percent", data = (0, 100))
        widget.clicked.connect(self._set_command_range)
        self._range_button_container_layout.addWidget(widget)

        
        widget = gremlin.ui.ui_common.QDataPushButton("-16K..+16K", data = (-16383, 16384))
        widget.clicked.connect(self._set_command_range)
        self._range_button_container_layout.addWidget(widget)

        
        widget = gremlin.ui.ui_common.QDataPushButton("0..16K", data = (0, 16384))
        widget.clicked.connect(self._set_command_range)
        self._range_button_container_layout.addWidget(widget)

        self._range_button_container_layout.addStretch()


        

        self._output_value_description_widget = QtWidgets.QLabel()
        
        self.command_header_container_widget = QtWidgets.QWidget()
        self.command_header_container_layout = QtWidgets.QVBoxLayout(self.command_header_container_widget)
        

        self.command_text_widget = QtWidgets.QLabel()
        self.command_header_container_layout.addWidget(QtWidgets.QLabel("<b>Command:</b>"))
        self.command_header_container_layout.addWidget(self.command_text_widget)


        self.description_text_widget = QtWidgets.QLabel()
        self.command_header_container_layout.addWidget(QtWidgets.QLabel("<b>Description</b>"))
        self.command_header_container_layout.addWidget(self.description_text_widget)
        self.command_header_container_layout.setContentsMargins(0,0,0,0)


        self.command_header_container_layout.addWidget(self._output_data_type_widget)
        self.command_header_container_layout.addWidget(self._output_data_2_type_widget)

        self.command_header_container_layout.addStretch(1)
               
        self._output_trigger_description_widget = QtWidgets.QLabel()


        self._output_trigger_bool_noop_widget = QtWidgets.QRadioButton("Trigger Only")
        self._output_trigger_bool_noop_widget.clicked.connect(self._trigger_noop_changed_cb)
        
        self._output_trigger_bool_toggle_widget = QtWidgets.QRadioButton("Toggle")
        self._output_trigger_bool_toggle_widget.clicked.connect(self._trigger_toggle_changed_cb)
        
        self._output_trigger_bool_on_widget = QtWidgets.QRadioButton("On")
        self._output_trigger_bool_on_widget.clicked.connect(self._trigger_turnon_cb)
        
        self._output_trigger_bool_off_widget = QtWidgets.QRadioButton("Off")
        self._output_trigger_bool_off_widget.clicked.connect(self._trigger_turnoff_cb)

        self._output_trigger_bool_input_value_widget = QtWidgets.QRadioButton("Input Value")
        self._output_trigger_bool_input_value_widget.clicked.connect(self._trigger_input_value_cb)


        self._output_trigger_bool_container_widget = QtWidgets.QWidget()
        self._output_trigger_bool_container_widget.setContentsMargins(0,0,0,0)
        self._output_trigger_bool_container_layout = QtWidgets.QHBoxLayout(self._output_trigger_bool_container_widget)
        self._output_trigger_bool_container_layout.setContentsMargins(0,0,0,0)

        self._output_trigger_bool_container_layout.addWidget(QtWidgets.QLabel("Trigger Mode:"))
        self._output_trigger_bool_container_layout.addWidget(self._output_trigger_bool_noop_widget)
        self._output_trigger_bool_container_layout.addWidget(self._output_trigger_bool_input_value_widget)
        self._output_trigger_bool_container_layout.addWidget(self._output_trigger_bool_toggle_widget)
        self._output_trigger_bool_container_layout.addWidget(self._output_trigger_bool_on_widget)
        self._output_trigger_bool_container_layout.addWidget(self._output_trigger_bool_off_widget)
        self._output_trigger_bool_container_layout.addWidget(self._output_trigger_description_widget)
        self._output_trigger_bool_container_layout.addStretch()

        # status widget
        self.status_text_widget = gremlin.ui.ui_common.QIconLabel()

       
        


        # output options container - shows below selector - visible when a command is selected and changes with the active mode
        widget, layout = gremlin.ui.ui_common.getVContainer()
        self._output_container_widget = widget
        self._output_container_layout = layout
        

        self._output_container_layout.addWidget(self.command_header_container_widget)
        self._output_container_layout.addWidget(QHLine())
        self._output_container_layout.addWidget(self._output_mode_container_widget)
        self._output_container_layout.addWidget(self._output_range_container_widget)
        self._output_container_layout.addWidget(self._output_trigger_bool_container_widget)
        self._output_container_layout.addWidget(self.status_text_widget)
        self._output_container_layout.addStretch()



        #self.main_layout.addWidget(self._toolbar_container_widget)

        warning_color = gremlin.ui.ui_common.Color.warningColor()
        warning_widget = gremlin.ui.ui_common.QIconLabel("ph.shield-warning-fill",use_qta=True,icon_color=QtGui.QColor(warning_color),text="This function is experimental and still in development, and not necessary feature complete", use_wrap=False)
        self.main_layout.addWidget(warning_widget)

        self.main_layout.addWidget(self._mode_container_widget)
        self.main_layout.addWidget(QHLine())
        self.main_layout.addWidget(self._command_container_widget)
        self.main_layout.addWidget(self._calculator_container_widget)
        self.main_layout.addWidget(self._calculator_release_container_widget)
        self.main_layout.addWidget(self._warning_widget)
        self.main_layout.addWidget(self._lvar_lookup_container_widget)
        self.main_layout.addWidget(self._type_container_widget)
        self.main_layout.addWidget(self._output_container_widget)
        self.main_layout.addWidget(self._button_mode_container_widget)
        self.main_layout.addWidget(self.container_repeater_widget)
            

        # hook the inputs and profile
        el = gremlin.event_handler.EventListener()
        el.custom_joystick_event.connect(self._joystick_event_handler)
        if not self.chained_input:
            el.joystick_event.connect(self._joystick_event_handler)
        el.profile_start.connect(self._profile_start)
        el.profile_stop.connect(self._profile_stop)
        # refresh the UI on profile mode changes
        el.edit_mode_changed.connect(self._populate_ui) 

        # update from ui
        self._update_ui()


    @QtCore.Slot()
    def _set_command_range(self):
        widget = self.sender()
        min_value, max_value = widget.data

        # set the range first
        self.action_data.command_min_range = min_value
        self.action_data.command_max_range = max_value
        self._value_widget.setRange(min_value, max_value)

        self._update_axis_widget(self._current_value)

    def _update_curve_icon(self):
        if self.action_data.curve_data:
            self.curve_button_widget.setIcon(self.curve_icon_active)
            self.curve_clear_widget.setEnabled(True)
        else:
            self.curve_button_widget.setIcon(self.curve_icon_inactive)
            self.curve_clear_widget.setEnabled(False)


    @QtCore.Slot()
    def _command_type_changed(self):
        widget = self.sender()
        command_type = widget.data
        self.action_data.command_type = command_type
        self._update_ui()

    @QtCore.Slot(bool)
    def _auto_repeat_state_changed(self, checked):
        self.action_data.auto_repeat = checked

    @QtCore.Slot(bool)
    def _is_release_command_changed(self, checked):
        self.action_data.is_release_command = checked
        self._update_visible()


    @QtCore.Slot()
    def _auto_repeat_delay_changed(self):
        self.action_data.auto_repeat_interval = self._autorepeat_delay_widget.value()

    @QtCore.Slot()
    def _command_mode_changed_cb(self):
        widget = self.sender()
        mode = widget.data
        self.action_data.command_mode = mode
        SimconnectOptions().last_command_mode = mode # remember for next time
        
        
        self._update_visible()
    
    @QtCore.Slot()
    def _lvar_selected_cb(self):
        lvar = self._lvar_selector_widget.currentText()
        if lvar:
            self._calculator_entry_widget.insertPlainText(lvar)

    @QtCore.Slot()
    def _expression_changed_cb(self):
        ''' expression changed '''
        self.action_data.command = self._calculator_entry_widget.toPlainText()
        warning_visible = self.action_data.command_mode == SimConnectCommandMode.CalculatorParam and not self.action_data._is_value_command()
        self._warning_widget.setVisible(warning_visible)

    @QtCore.Slot()
    def _expression_release_changed_cb(self):
        ''' expression changed '''
        self.action_data.command_release = self._calculator_release_entry_widget.toPlainText()
        warning_visible = self.action_data.command_mode == SimConnectCommandMode.CalculatorParam and not self.action_data._is_value_command()
        self._warning_widget.setVisible(warning_visible)

    QtCore.Slot()            
    def _reset_range(self):
        with QtCore.QSignalBlocker(self.action_data.events):
            self.action_data.output_min_range = -1.0
            self.action_data.output_max_range = 1.0
        self._value_widget.setRange(-1,1)
        self._update_repeater()
        
    QtCore.Slot(object)
    def _value_changed(self, data):
        # normalized value (-1 to +1)
        verbose = gremlin.config.Configuration().verbose
        if self._value_widget.isRange:
            min_value, max_value = data
            self.action_data.normalized_min_range = min_value
            self.action_data.normalized_max_range = max_value
            if verbose: syslog.info (f"Range Value (normalized): {min_value:0.3f} {max_value:0.3f}")
        else:
            # single mode
            min_value = data
            max_value = self.action_data.limit_max_range
            self.action_data.normalized_min_range = min_value

            if verbose: syslog.info(f"Single value (normalized): {min_value:0.3f}")
        
        self._update_repeater()
    
     
    QtCore.Slot(object)
    def _range_changed(self, data):
        verbose = gremlin.config.Configuration().verbose
        if self._value_widget.isRange:
            min_cmd, max_cmd = data
            self.action_data.command_min_range = min_cmd
            self.action_data.command_max_range = max_cmd
            if verbose: syslog.info (f"Set Range Value (command): {min_cmd:0.3f} {max_cmd:0.3f}")
        else:
            # single mode
            value = data
            self.action_data.command_min_range = value
            if verbose: syslog.info(f"Set single value (command): {value:0.3f}")
        
        self._update_repeater()


    QtCore.Slot()
    def _inverted_changed(self):
        self.action_data.inverted = self._value_widget.inverted
        self._update_repeater()


    @QtCore.Slot(object)
    def _command_range_changed(self, data):
        if self._value_widget.isRange:
            min_value, max_value = data
            self.action_data.command_min_range = min_value
            self.action_data.command_max_range = max_value
            self._update_repeater()

    QtCore.Slot()
    def _curve_button_cb(self):
        if not self.action_data.curve_data:
            curve_data = gremlin.curve_handler.AxisCurveData()
            curve_data.calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(self.action_data.hardware_device_guid, self.action_data.hardware_input_id)
            curve_data.curve_update()
            self.action_data.curve_data = curve_data
            
        dialog = gremlin.curve_handler.AxisCurveDialog(self.action_data.curve_data)
        gremlin.util.centerDialog(dialog, dialog.width(), dialog.height())
        self.curve_update_handler = dialog.curve_update_handler
        self._update_axis_widget(self._current_input_axis())

        # disable highlighting
        gremlin.shared_state.push_suspend_highlighting()
        dialog.exec()
        gremlin.shared_state.pop_suspend_highlighting()
        self.curve_update_handler = None

        self._update_curve_icon()



    QtCore.Slot()
    def _curve_delete_button_cb(self):
        ''' removes the curve data '''
        message_box = QtWidgets.QMessageBox()
        message_box.setText("Confirmation")
        message_box.setInformativeText("Delete curve data for this output?")
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
        )
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        is_cursor = gremlin.util.isCursorActive()
        if is_cursor:
            gremlin.util.popCursor()
        response = message_box.exec()
        if is_cursor:
            gremlin.util.pushCursor()
        if response == QtWidgets.QMessageBox.StandardButton.Ok:
            self.action_data.curve_data = None
            self._update_curve_icon()        


    def _profile_start(self):
        ''' called when the profile starts '''
        el = gremlin.event_handler.EventListener()
        el.custom_joystick_event.disconnect(self._joystick_event_handler)
        if not self.chained_input:
            el.joystick_event.disconnect(self._joystick_event_handler)
        
    def _profile_stop(self):
        ''' called when the profile stops'''
        self._update_axis_widget()
        el = gremlin.event_handler.EventListener()
        el.custom_joystick_event.connect(self._joystick_event_handler)
        if not self.chained_input:
            el.joystick_event.connect(self._joystick_event_handler)


    def _joystick_event_handler(self, event):
        ''' handles joystick events in the UI (functor handles the output when profile is running) so we see the output at design time '''
        if gremlin.shared_state.is_running:
            return 

        if not event.is_axis:
            return 
        
        value = None
        
        if event.device_guid != self.action_data.hardware_device_guid:
            return
        if event.identifier != self.action_data.hardware_input_id:
            return
        if event.is_custom:
            value = event.value
        
        self._update_axis_widget(value)            



    def _current_input_axis(self):
        ''' gets the current input axis value '''
        return gremlin.joystick_handling.get_curved_axis(self.action_data.hardware_device_guid, 
                                                  self.action_data.hardware_input_id) 

                

    
    def _update_axis_widget(self, value : float = None):
        ''' updates the axis output repeater with the value 
        
        :param value: the floating point normalized input value, if None uses the cached value -1 to +1 range
        
        '''
        # always read the current input as the value could be from another device for merged inputs


        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        
        if self.input_type == InputType.JoystickAxis:
            
            raw_value = self.action_data.get_raw_axis_value()
            if value is None:
                # filter and merge the data
                value = raw_value

            filtered_value = self.action_data.get_filtered_axis_value(value)
            if self.action_data.curve_data:
                filtered_value = self.action_data.get_local_curve_value(filtered_value)
            normalized = filtered_value
            value = filtered_value
                

            # if the output is ranged apply that range
            
            if self.action_data.mode == SimConnectActionMode.Ranged:
                # scale up to apply the block range
                filtered_value = self.action_data.get_filtered_axis_value(value)

                raw = filtered_value # -1 to +1
                normalized = raw 

                # apply local curve to the range -1 to + 1
                curved = self.action_data.get_local_curve_value(normalized)

                # compute the output value based on the range setup
                min_range = self.action_data.command_min_range
                max_range = self.action_data.command_max_range
                percent = gremlin.util.scale_to_range(curved, target_min = 0, target_max = 100)    
                output_value = gremlin.util.scale_to_range(curved, target_min = min_range, target_max = max_range, invert = self.action_data.inverted)
                                
                if verbose: syslog.info(f"SIMCONNECT UI: {value:0.3f} output range: [{self.action_data.output_min_range:0.3f}, {self.action_data.output_max_range:0.3f}] normalized range: [{self.action_data.normalized_min_range:0.4f}, {self.action_data.normalized_max_range:0.4f}] normalized {normalized:0.4f} curved {curved:0.3f} percent: {percent:0.3f} output: {output_value}")
            else:
                output_value = value
                percent = gremlin.util.scale_to_range(value, source_min = self.action_data.output_min_range, source_max = self.action_data.output_max_range, target_min=0, target_max=100) # convert to percent

            if self.action_data.curve_data is not None:
                # curve the data 
                self._axis_repeater_widget.show_curved = True
            else:
                self._axis_repeater_widget.show_curved = False

            self._axis_repeater_widget.setValue(normalized, percent_value=percent)
            self._current_value = normalized

            if self.action_data.command_mode == SimConnectCommandMode.Simvar:
                self._axis_value_widget.setValue(output_value)
                self._axis_value_widget.setVisible(True)
                self._calculator_value_widget.setVisible(False)
            else:
                # calculator mode
                if self.action_data.mode in (SimConnectActionMode.Ranged, SimConnectActionMode.SetValue):
                    command = self.action_data._get_value_command(output_value)
                else:
                    command = self.action_data.command
                self._calculator_value_widget.setPlainText(command)
                self._axis_value_widget.setVisible(False)
                self._calculator_value_widget.setVisible(True)

            if self.curve_update_handler is not None:
                # update curve dialog if it's open
                self.curve_update_handler(normalized)

            

    @QtCore.Slot()
    def _show_options_dialog_cb(self):
        ''' displays the simconnect options dialog'''
        from action_plugins.map_to_simconnect.SimConnectManager import SimConnectManager
        profile = gremlin.shared_state.current_profile
        profile_file = profile.profile_file
        if not profile_file or not os.path.isfile(profile_file):
            gremlin.ui.ui_common.MessageBox(prompt="Please save the current profile before accessing Simconnect options.")
            return 
        dialog = SimconnectOptionsUi(SimConnectManager().simconnect)
        dialog.exec()

    @QtCore.Slot()
    def _refresh_lvar_cb(self):
        ''' refreshes the list of lvars from the sim '''
        self.manager.refreshLvars()
        

    @QtCore.Slot(object)
    def _lvars_udpated_cb(self, lvars):
        ''' called when new LVARs are received '''
        with QtCore.QSignalBlocker(self._lvar_selector_widget):
            self._lvar_selector_widget.clear()
            self._lvar_selector_widget.addItems(self.manager.lvars)
            


    def _output_normalized_value_changed_cb(self):
        normalized = self._output_value_normalized_widget.value()
        if normalized:
            scaled = gremlin.util.scale_to_range(normalized, target_min = -16368, target_max = 16367)
            value = int(scaled)
            with QtCore.QSignalBlocker(self._output_value_widget):
                self._output_value_widget.setValue(value)
            self._update_output_value(normalized)

    def _output_value_changed_cb(self):
        ''' occurs when the output value has changed '''
        value = self._output_value_widget.value()
        if value is not None:
            normalized = gremlin.util.scale_to_range(value, -16368, 16367)
            with QtCore.QSignalBlocker(self._output_value_normalized_widget):
                self._output_value_normalized_widget.setValue(normalized)
            self._update_output_value(normalized)


    def _update_output_value(self, value):
        # store to profile
        self.action_data.value = value
        percent = gremlin.util.scale_to_range(value, target_min = 0.0, target_max = 100.0)
        with QtCore.QSignalBlocker(self._output_value_percent_widget):
            self._output_value_percent_widget.setValue(percent)
        


            

    def _update_repeater(self):
        value = gremlin.joystick_handling.get_axis(self.action_data.hardware_device_guid, self.action_data.hardware_input_id)
        self._update_axis_widget(value)

    def _update_max_range(self, value):
        # store to profile
        assert value >= -1.0 and value <= 1.0
        self.action_data.output_max_range = value

        percent = gremlin.util.scale_to_range(value, target_min = 0.0, target_max = 100.0)
        with QtCore.QSignalBlocker(self._output_max_percent_range_widget):
            self._output_max_percent_range_widget.setValue(percent)

    @QtCore.Slot(bool)
    def _output_invert_axis_cb(self, checked):
        self.action_data.inverted = checked
        self._axis_repeater_widget.setReverse(checked)
        # update the repeater
  
    @QtCore.Slot(bool)
    def _trigger_on_release_cb(self, checked):
        self.action_data.trigger_on_release = checked

    @QtCore.Slot(bool)
    def _trigger_on_press_cb(self, checked):
        self.action_data.trigger_on_press = checked
    

    def _command_changed_cb(self, index):
        ''' called when selected command changes '''
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        command = self._command_selector_widget.currentText()
        if verbose: syslog.info(f"Command changed to: {command}")
        if command:
            self.action_data.command = command
            self._update_ui()

    @QtCore.Slot()
    def _lvar_changed_cb(self):
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        command = self._lvar_command_widget.text()
        if verbose: syslog.info(f"Command changed to: {command}")
        self.action_data.command = command

        

    def _update_ui(self):
        ''' updates the UI with a data block '''

        with QtCore.QSignalBlocker(self._trigger_on_release_widget):
            self._trigger_on_release_widget.setChecked(self.action_data.trigger_on_release)
        with QtCore.QSignalBlocker(self._trigger_on_press_widget):
            self._trigger_on_press_widget.setChecked(self.action_data.trigger_on_press)


        # enabled = self.action_data._command_type == SimConnectCommandType.SimVar
        # self._action_selector_widget.setEnabled(enabled)
        # self._output_mode_container_widget.setEnabled(enabled)

        command = self.action_data.command
        block = self.manager.block(command)
        self.command_text_widget.setText(command)
        if block:
            # self.action_data.command_min_range = block.command_min_range
            # self.action_data.command_max_range = block.command_max_range
            self.description_text_widget.setText(block.description)
            
        else:
            
            self.description_text_widget.setText("No description found")


            
        
        output_mode = self.action_data.mode
        min_range = self.action_data.output_min_range
        max_range = self.action_data.output_max_range
        min_command_range = self.action_data.command_min_range
        max_command_range = self.action_data.command_max_range


        value = self.action_data.value
        inverted = self.action_data.inverted
        trigger_mode = self.action_data.trigger_mode




    
    
    
        # calculator mode
        with QtCore.QSignalBlocker(self._type_is_calculator_widget):
            self._type_is_calculator_widget.setChecked(self.action_data._command_type == SimConnectCommandType.Calculator)

        # settable flag
        with QtCore.QSignalBlocker(self._type_is_settable_widget):
            self._type_is_settable_widget.setChecked(not self.action_data.is_readonly)

        with QtCore.QSignalBlocker(self._type_datatype_widget):
            self._type_datatype_widget.setText(self.action_data.data_type)
        
        with QtCore.QSignalBlocker(self._type_units_widget):
            self._type_units_widget.setText(self.action_data.units)

    

        match output_mode:

            case SimConnectActionMode.Ranged:

                with QtCore.QSignalBlocker(self._output_mode_ranged_widget):
                    self._output_mode_ranged_widget.setChecked(True)

                with QtCore.QSignalBlocker(self._value_widget):
                    self._value_widget.isRange = True
                self._update_repeater()


            case SimConnectActionMode.SetValue:
                with QtCore.QSignalBlocker(self._output_mode_set_value_widget):
                    self._output_mode_set_value_widget.setChecked(True)
                
                with QtCore.QSignalBlocker(self._value_widget):
                    self._value_widget.isRange = False
                self._update_repeater()
                    

                
            case SimConnectActionMode.Trigger:

                with QtCore.QSignalBlocker(self._output_mode_trigger_widget):
                    self._output_mode_trigger_widget.setChecked(True)

                self.action_data.trigger_mode = trigger_mode
                    
        # trigger mode options
        match trigger_mode:
            case SimConnectTriggerMode.NotSet:
                with QtCore.QSignalBlocker(self._output_trigger_bool_toggle_widget):
                    self._output_trigger_bool_toggle_widget.setChecked(True)
            case SimConnectTriggerMode.Toggle:
                with QtCore.QSignalBlocker(self._output_trigger_bool_toggle_widget):
                    self._output_trigger_bool_toggle_widget.setChecked(True)
            case SimConnectTriggerMode.TurnOff:
                with QtCore.QSignalBlocker(self._output_trigger_bool_off_widget):
                    self._output_trigger_bool_off_widget.setChecked(True)
            case SimConnectTriggerMode.TurnOn:
                with QtCore.QSignalBlocker(self._output_trigger_bool_on_widget):
                    self._output_trigger_bool_on_widget.setChecked(True)
            case SimConnectTriggerMode.NoOp:
                with QtCore.QSignalBlocker(self._output_trigger_bool_on_widget):
                    self._output_trigger_bool_noop_widget.setChecked(True)
            case SimConnectTriggerMode.InputValue:
                with QtCore.QSignalBlocker(self._output_trigger_bool_input_value_widget):
                    self._output_trigger_bool_input_value_widget.setChecked(True)



       
        
        
        input_desc = ""
        input_type = self.action_data.input_type
        
        if input_type == InputType.JoystickAxis:
            input_desc = "axis"
        elif input_type in (InputType.JoystickButton, InputType.VirtualButton):
            input_desc = "button"
        elif input_type == InputType.JoystickHat:
            input_desc = "hat"
        elif input_type in (InputType.Keyboard, InputType.KeyboardLatched):
            input_desc = "key"
        elif input_type in (InputType.Midi, InputType.OpenSoundControl):
            input_desc = "button or slider"


        match output_mode:
            case SimConnectActionMode.Ranged:
                desc = f"Maps an input {input_desc} to a SimConnect ranged event, such as an axis"
            case SimConnectActionMode.Trigger:
                desc = f"Maps an input {input_desc} to a SimConnect triggered event, such as an on/off or toggle function."
            case SimConnectActionMode.SetValue:
                desc = f"Maps an input {input_desc} to a Simconnect event and sends it the specified value."
            case _:
                desc = ""

        self._output_mode_description_widget.setText(desc)

        # command description
        with QtCore.QSignalBlocker(self.command_text_widget):
            self.command_text_widget.setText(self.action_data.command)
       
        if input_type == InputType.JoystickAxis:
            # input drives the outputs
            self._output_mode_trigger_widget.setVisible(False)
            self._output_mode_ranged_widget.setVisible(True)
            self._trigger_on_release_widget.setVisible(False)

        else:
            # button or event intput
            self._output_mode_trigger_widget.setVisible(True)
            self._output_mode_ranged_widget.setVisible(False)
            self._trigger_on_release_widget.setVisible(True)


        
            self._output_container_widget.setVisible(True)
            self._output_mode_readonly_widget.setVisible(self.action_data.is_readonly)
            self.output_readonly_status_widget.setText("Block: read/only" if self.action_data.is_readonly else "Block: read/write")

            # display range information if the command is a ranged command
            self._output_range_container_widget.setVisible(self.action_data.is_ranged)

            # hook block events
            eh = SimConnectEventHandler()
            eh.range_changed.connect(self._range_changed_cb)



            # update UI based on block information ``
            self._output_data_type_label_widget.setText(self.action_data.data_type)
         
            self._update_visible()

        if not self.action_data.command:
            
            # clear the data
            self._output_container_widget.setVisible(False)
            self.status_text_widget.setText("Please select a command")

        if self.action_data.input_type == InputType.JoystickAxis:
            value = gremlin.joystick_handling.get_axis(self.action_data.hardware_device_guid, self.action_data.hardware_input_id)
            self._update_axis_widget(value)
    
        # update visibility
        self._update_visible()


    def _update_visible(self):
        ''' updates the UI based on the output mode selected '''

        mode = self.action_data.command_mode
        calc_visible = mode != SimConnectCommandMode.Simvar
        simvar_visible = not calc_visible
        warning_visible = mode == SimConnectCommandMode.CalculatorParam and not self.action_data._is_value_command()
        block_visible = mode == SimConnectCommandMode.Simvar
        

        release_command_visible = self.action_data.is_release_command
        
        lvar_lookup_visible = calc_visible
        if self.action_data.command_type == SimConnectCommandType.SimVar:
            # known simvar (block) mode
            self._action_selector_widget.setVisible(True)
            self._lvar_container_widget.setVisible(False)
        elif self.action_data.command_type == SimConnectCommandType.LVar:
            # lvar (non block) mode
            self._action_selector_widget.setVisible(False)
            self._lvar_container_widget.setVisible(True)
            lvar_lookup_visible = True
            block_visible = False

        self._command_selector_widget.setVisible(simvar_visible)
        self._lvar_lookup_container_widget.setVisible(lvar_lookup_visible)
        self._calculator_container_widget.setVisible(calc_visible)

        self._type_container_widget.setVisible(False) # disable for now as it doesn't serve a value until we have an edit / entry mode
        self._command_container_widget.setVisible(simvar_visible)
        self._calculator_release_container_widget.setVisible(release_command_visible and calc_visible)
        
        
        #self._button_mode_container_widget.setVisible(simvar_visible) # always visible

        input_type = self.action_data.input_type
        repeater_visible = False
        output_mode = self.action_data.mode
        trigger_visible = output_mode == SimConnectActionMode.Trigger
        if input_type == InputType.JoystickAxis:
            range_visible = output_mode in (SimConnectActionMode.Ranged, SimConnectActionMode.SetValue) or mode == SimConnectCommandMode.CalculatorParam
            repeater_visible = True
            
        else:
            # momentary
            range_visible = self.action_data.command_type == SimConnectCommandType.LVar
        
        range_visible = True

        self._output_container_widget.setVisible(simvar_visible or range_visible)
        self._output_range_container_widget.setVisible(simvar_visible or range_visible)
        self._output_trigger_bool_container_widget.setVisible(trigger_visible)
        

        self.container_repeater_widget.setVisible(repeater_visible)

        output_mode_enabled = not self.action_data.is_readonly
        
        self._output_mode_container_widget.setVisible(output_mode_enabled)
        self._output_mode_set_value_widget.setEnabled(output_mode_enabled)
        self._output_mode_trigger_widget.setEnabled(output_mode_enabled)
        self._output_data_type_label_widget.setText(self.action_data.data_type)

        self.output_readonly_status_widget.setText("(command is Read/Only)" if self.action_data.is_readonly else '')
        self.command_header_container_widget.setVisible(block_visible)
        self.output_readonly_status_widget.setVisible(block_visible)

        
        self._warning_widget.setVisible(warning_visible)



    @QtCore.Slot(bool)
    def _trigger_noop_changed_cb(self, checked):
        if checked:
            self.action_data.trigger_mode = SimConnectTriggerMode.NoOp
            

    @QtCore.Slot(bool)
    def _trigger_toggle_changed_cb(self, checked):
        if checked:
            self.action_data.trigger_mode = SimConnectTriggerMode.Toggle
            

    @QtCore.Slot(bool)
    def _trigger_turnon_cb(self, checked):
        if checked:
            self.action_data.trigger_mode = SimConnectTriggerMode.TurnOn
            

    @QtCore.Slot(bool)
    def _trigger_turnoff_cb(self, checked):
        if checked:
            self.action_data.trigger_mode = SimConnectTriggerMode.TurnOff
            

    @QtCore.Slot(bool)
    def _trigger_input_value_cb(self, checked):
        if checked:
            self.action_data.trigger_mode = SimConnectTriggerMode.InputValue
            


    @QtCore.Slot(object, object)
    def _range_changed_cb(self, block, event : RangeEvent):
        ''' called when range information changes on the current simconnect command block '''
        if block == self.action_data.block:
            self._output_min_range_widget.setValue(event.min)
            self._output_max_range_widget.setValue(event.max)
            self._output_min_range_widget.setValue(event.min_custom)
            self._output_max_range_widget.setValue(event.max_custom)
            

    @QtCore.Slot(bool)
    def _mode_ranged_cb(self, value):
        if value:
            self.action_data.output_mode = SimConnectActionMode.Ranged
            self.action_data.mode = SimConnectActionMode.Ranged
            self._value_widget.isRange = True # enable ranged mode
            self._update_visible()
            self._update_repeater()

    @QtCore.Slot(bool)
    def _mode_value_cb(self, value):
        if value:
            if self.action_data.block:
                self.action_data.block.output_mode = SimConnectActionMode.SetValue
            self.action_data.mode = SimConnectActionMode.SetValue
            self._value_widget.isRange = False # disable ranged mode
            self._update_visible()
            self._update_axis_widget(self._value_widget.getValue())
        
    @QtCore.Slot(bool)
    def _mode_trigger_cb(self, value):
        if value:
            if self.action_data.block:
                self.action_data.block.output_mode = SimConnectActionMode.Trigger
            self.action_data.mode = SimConnectActionMode.Trigger
            self._update_visible()

    def _readonly_cb(self):
        block : SimConnectBlock
        block = self.action_data.block
        
        readonly = block is not None and block.is_readonly
        checked = self.output_readonly_status_widget.isChecked()
        if readonly != checked:
            with QtCore.QSignalBlocker(self.output_readonly_status_widget):
                self.output_readonly_status_widget.setChecked(readonly)
        
        self.action_data.is_readonly = readonly

    def _populate_ui(self):
        """Populates the UI components."""
        
        command = self._command_selector_widget.currentText()

        if self.action_data.command != command:
            with QtCore.QSignalBlocker(self._command_selector_widget):
                index = self._command_selector_widget.findText(self.action_data.command)
                self._command_selector_widget.setCurrentIndex(index)
        

class MapToSimConnectFunctor(gremlin.base_profile.AbstractContainerActionFunctor):

    # macro_manager = gremlin.macro.MacroManager()

    def __init__(self, action, parent = None):
        
        super().__init__(action, parent)
        self.action_data : MapToSimConnect = action
        self.command = action.command # the command to execute
        self.value = action.value # the value to send (None if no data to send)
        self.manager : SimConnectManager = SimConnectManager()
        self.monitor : SimconnectMonitor = SimconnectMonitor()
        self.valid = False
        self._significant = gremlin.input_devices.JoystickInputSignificant()
        self._profile_started = False
        self._last_event = None
        
        self.reconnect_timeout = 5
        self.last_reconnect_time = None

        # self.action_data.gate_data.process_callback = self.process_gated_event
        if not self.command:
            syslog.error(f"Simconnect: invalid block: {self.command}")
            self.valid = False
            return
        
        self._auto_repeat_thread = None
        self._auto_repeat_event = threading.Event()
        self._auto_repeat_thread = threading.Thread(target = self._auto_repeat_command, daemon=True)
        
        self.valid = True

    
    def profile_start(self):
        ''' occurs when the profile starts '''


        if not self._profile_started:
        
            self._profile_started = True
            self.reconnect_timeout = 5
            self.last_reconnect_time = None
            
            self.manager.activate()

            # update the loaded aircraft so this sets the profile mode if needed
            name = self.manager.get_loaded_aircraft()
            if name:
                self.monitor.changeModeForAicraft(name)
            else:            
                self.manager.request_loaded_aircraft()
        


        



    def profile_stop(self):
        ''' occurs wen the profile stops'''
        if self._profile_started:
            self._profile_started = False
            self._auto_repeat_event.set()
            if self._auto_repeat_thread:
                # clear any running autorepeat
                if self._auto_repeat_thread.is_alive():
                    self._auto_repeat_thread.join()
                
            # unregister any prior requests
            self.manager.clearRequests()

            eh = SimConnectEventHandler()
            eh.request_disconnect.emit()

    
    
    
    def process_event(self, event, action_value : gremlin.actions.Value, extra_data = None) -> bool:
        ''' runs when a joystick event occurs like a button press or axis movement when a profile is running '''

        if not gremlin.shared_state.is_running or gremlin.shared_state.abort:
            return False

        if not self.valid:
            return False
        
        # if self._last_event and self._last_event == event:
        #     return False
        # self._last_event = event
        


        if not self.manager.is_running:
            # sim is not running - attempt to reconnect every few seconds
            syslog.info("SIMCONNECT: manager not running - connecting....")
            if self.last_reconnect_time is None or self.last_reconnect_time + self.reconnect_timeout > time.time():
                self.last_reconnect_time = time.time()
                eh = SimConnectEventHandler()
                eh.request_connect.emit()
            return True

        return self._process_event(event, action_value, extra_data)



    def _process_event(self, event, action_value : gremlin.actions.Value, extra_data = None):
        ''' handles default input data '''

        # execute the nested functors for this action
        super().process_event(event, action_value)
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_simconnect
        verbose_exec = config.verbose_mode_exec
        verbose_details = False # config.verbose_mode_details
        #verbose = True
        manager : SimConnectManager = self.manager
        
        # syslog.info(f"event: {str(event)} node: {extra_data["node"]}")

        if not self.manager.is_running:
            # sim is not running
            syslog.warning(f"Simconnect Functor: event ignored, simconnect not connected")
            return False
        
        if not self.manager.is_bridge_alive:
            # sim is not running
            syslog.warning(f"Simconnect Functor: event ignored, simconnect bridge not connected")
            return False
        
        if verbose:
            comment = ""
            if extra_data:
                if "node" in extra_data:
                    node = extra_data["node"]
                    comment += f"Node: [{node.id}] " 
                    
            comment += f"Input: {self.action_data.input_item.device_name} id: {self.action_data.input_item.input_id} mode: {self.action_data.input_item.profile_mode} | {self.action_data.comment if self.action_data.comment else ''} | "
            

                                
        
        block = self.action_data.block
        output_mode = self.action_data.mode
        
        command_mode = self.action_data.command_mode
        command_type = self.action_data.command_type

        trigger = self.action_data.trigger_on_press and event.is_pressed or self.action_data.trigger_on_release and not event.is_pressed

        if command_mode in (SimConnectCommandMode.Calculator, SimConnectCommandMode.CalculatorParam):
            # RPN modes
            if event.is_axis:
                
                if not self.action_data.command:
                    # nothing to calculate
                    return True
                
                process_input = self._significant.should_process_axis(event, 0.01)
                if process_input:
                    

                    command = None
                    if command_mode == SimConnectCommandMode.CalculatorParam:
                        if self.action_data.mode == SimConnectActionMode.Ranged:
                            # compute the output value based on the range setup
                            min_range = self.action_data.command_min_range
                            max_range = self.action_data.command_max_range
                            value = gremlin.util.scale_to_range(event.value, target_min = min_range, target_max = max_range, invert = self.action_data.inverted)
                            command = self.action_data._get_value_command(value)
                        elif self.action_data.mode == SimConnectActionMode.SetValue:
                            value = self.action_data.value
                            command = self.action_data._get_value_command(value)
                        else:
                            command = self.action_data.command
                    elif command_mode == SimConnectCommandMode.Calculator:
                        command = self.action_data.command
                    if command:
                        self.manager.calculate(command) # run RPN script
                return True
            
            else:
                # non axis command
                if self.action_data.auto_repeat:
                    if trigger:
                        # calculator expression
                        if not self._auto_repeat_thread.is_alive():
                            # command auto repeats while pressed - not started
                            if verbose_details: syslog.info(f"auto repeat start")
                            self._auto_repeat_thread.start()
                            return True
                
                if trigger:
                    # regular calculate
                    command = self.action_data.command
                    if command:
                        if verbose_details: syslog.info(f"Simconnect: {comment} calc: execute press command: {command}")
                        manager.calculate(command) # run RPN script
                else:
                    # release calculate auto repeat
                    if self.action_data.auto_repeat and self._auto_repeat_thread:
                        # released
                        if verbose_details: syslog.info(f"auto repeat stopping...")
                        self._auto_repeat_event.set()
                        self._auto_repeat_thread.join()
                        if verbose_details: syslog.info(f"auto repeat stopped")

                    if self.action_data.is_release_command:
                        # execute release command
                        command = self.action_data.command_release
                        if command:
                            if verbose_details: syslog.info(f"Simconnect: {comment} calc: execute release command: {command}")
                            manager.calculate(command) # run RPN script
        
        
        else: # command_mode == SimConnectCommandMode.Simvar 
            # non calc modes

            if command_type == SimConnectCommandType.SimVar:
                if block is None:
                    syslog.warning(f"SIMCONNECT: {comment} Error: Simvar Block not set")    
                    return True        
                if not block.valid:
                    # invalid command
                    syslog.warning(f"SIMCONNECT: {comment}  Error: invalid block: {block.command} type: {block.command_type}")
                    return True        
            
            if event.is_axis and output_mode in (SimConnectActionMode.Ranged, SimConnectActionMode.Gated):
                # value = self.action_data.get_filtered_axis_value(action_value.current)
                # process input options and any merge and curve operation

                process_input = True # self._significant.should_process_axis(event, 0.001)
                if process_input:


                    command = self.action_data.command
          
                    filtered_value = self.action_data.get_filtered_axis_value(action_value.current)
                    action_value = gremlin.actions.Value(filtered_value)

                    raw = filtered_value # -1 to +1
                    normalized = raw 

                    # apply local curve to the range -1 to + 1
                    curved = self.action_data.get_local_curve_value(normalized)


                    # compute the output value based on the range setup
                    
                    min_range = self.action_data.command_min_range
                    max_range = self.action_data.command_max_range
                    output_value = gremlin.util.scale_to_range(curved, target_min = min_range, target_max = max_range, invert = self.action_data.inverted)
                    
  
                    if verbose: 
                        if verbose_exec:
                            syslog.info(f"SIMCONNECT: {comment} send ({command_type.name}) (axis): {command} input: {action_value.current:0.3f} scaled: {normalized:0.3f} curved: {curved:0.3f} min: {self.action_data.output_min_range:0.3f} max: {self.action_data.output_max_range:0.3f} -> scaled: {output_value:0.3f}")
                        else:
                            syslog.info(f"SIMCONNECT: send {comment} {command} {output_value:0.3f}")

                    if command_type == SimConnectCommandType.LVar:
                        request = manager.registerRequest(command, "number", settable = True)
                        request.value = output_value
                        request.transmit()
                    else:
                        block.execute(output_value)

            elif output_mode == SimConnectActionMode.Trigger:
                if not event.is_axis:
                    value = 1 if self.action_data.trigger_mode != SimConnectTriggerMode.InputValue else action_value.current
                    trigger = (self.action_data.trigger_on_press and event.is_pressed) or \
                            self.action_data.trigger_on_release and not event.is_pressed
                    if trigger:
                        if command_type == SimConnectCommandType.LVar:
                            if verbose: syslog.info(f"SIMCONNECT: {comment} Trigger singleton {self.action_data.command}")
                            request = manager.registerRequest(self.action_data.command, "number", settable = True)
                            request.value = value
                            request.transmit()
                        else:
                            if verbose: syslog.info(f"SIMCONNECT: {comment} Trigger singleton {block.command}")
                            block.execute(value)

            elif output_mode == SimConnectActionMode.SetValue:
                # set value mode 
                output_value = self.action_data.value
                command = self.action_data.command
                
                trigger = (self.action_data.trigger_on_press and event.is_pressed) or \
                            self.action_data.trigger_on_release and not event.is_pressed
                if trigger:
                    if command_type == SimConnectCommandType.LVar:
                        if verbose: syslog.info(f"SIMCONNECT: {comment} send lvar fixed value (trigger): {command} {output_value:0.3f}")
                        request = manager.registerRequest(self.action_data.command, "number", settable = True)
                        request.value = output_value
                        request.transmit()
                    else:
                        if verbose: syslog.info(f"SIMCONNECT: {comment} send block: {block.command} fixed value: {output_value:0.3f}")
                        block.execute(output_value)   
                
            elif self.action_data.mode == SimConnectActionMode.Trigger:
                # trigger action 
                min_range = self.action_data.command_min_range
                max_range = self.action_data.command_max_range
                value = action_value.current
                output_value = gremlin.util.scale_to_range(value, target_min = min_range, target_max = max_range, invert = self.action_data.inverted)
                if verbose: syslog.info(f"SIMCONNECT: {comment} send block trigger: {block.command} input: {value:0.3f} min: {self.action_data.output_min_range:0.3f} max: {self.action_data.output_max_range:0.3f} -> scaled: {output_value:0.3f}")
                block.execute(output_value)

        return False
    
    def _auto_repeat_command(self):
        verbose_details = False
        while not self._auto_repeat_event.is_set():
            self.manager.calculate(self.action_data.command)
            time.sleep(self.action_data.auto_repeat_interval)

        # syslog = logging.getLogger("system")
        if verbose_details: syslog.info("autorepeat: thread stop")

    

class MapToSimConnectHelper(QtCore.QObject):
    range_changed = QtCore.Signal() # indicates the range was updated
    def __init__(self):
        super().__init__()



class MapToSimConnect(gremlin.base_profile.AbstractContainerAction):

    """Action data for the map to keyboard action.

    Map to keyboard presses and releases a set of keys in sync with another
    physical input being pressed or released.
    """
    
    

    name = "Map to SimConnect"
    tag = "map-to-simconnect"

    default_button_activation = (True, True)
    # override allowed input types if different from default
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = MapToSimConnectFunctor
    widget = MapToSimConnectWidget

    @property
    def priority(self):
        # default priority is 0 - the higher the number the earlier the action runs compared to others
        return 9

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """

        import gremlin.shared_state
        import gremlin.config

        super().__init__(parent)
        self.parent = parent
        self.events = MapToSimConnectHelper()
        self._verbose = gremlin.config.Configuration().verbose_mode_details

        #eh = SimConnectEventHandler()
        from .SimConnectManager import SimConnectManager
        self._manager = SimConnectManager()

        options = SimconnectOptions()

        self.input_type = self.get_input_type()

        self._command_type = SimConnectCommandType.SimVar
        self.units = "Number"
        self.data_type = "int"
        self.is_ranged = False # true if ranged data

        # the current command category if the command is an event
        self.category = SimConnectEventCategory.NotSet

        # the current command name
        self._command = None
        self._command_release = None # command on release if any provided
        self._command_mode = options.last_command_mode
        self.is_release_command = False # true if the action has a command to execute on release

        self.auto_repeat = False
        self.auto_repeat_interval = 250 # how often to repeat the command while pressed in ms

        # the value to output if any
        
        self._output_min_range = -16383 # min range for ranged output
        self._output_max_range = 16384 # max range for ranged output 
        self._normalized_min_range = -1 # normalized range min (-1 to +1)
        self._normalized_max_range = 1 # normalized range max (-1 to +1)
        self._command_min_range = -16383 # simconnect min range for the command (if known - can be manually input)
        self._command_max_range = 16384 # simconnect max range for the command (if known - can be manually input)
        self._percent_min_range = 0
        self._percent_max_range = 100
        self._limit_min_range = -16383
        self._limit_max_range = 16384

        self.inverted = False # inversion flag
        self.trigger_mode = SimConnectTriggerMode.NoOp # trigger only

        self.trigger_on_press = True # true if the action is triggered on a button press
        self.trigger_on_release = False # true if the action is triggered on a button release
        

        # curve data applied to a simconnect axis output
        self.curve_data = None # present if curve data is needed
        

        self._block = None # block loaded based on the command

        # output mode
        if self.input_type == InputType.JoystickAxis:
            # default is ranged output for axes
            self.mode = SimConnectActionMode.Ranged
        else:
            # default is set trigger for buttons
            self.mode = SimConnectActionMode.Trigger

        # readonly mode
        self.is_readonly = False

    def _get_value_command(self, value):
        ''' gets a value expression for the current command '''
        command = self.command
        if command:
            if "{#}" in command:
                command = command.replace("{#}", f"{value:0.3f}")
            else:
                command = f"{value:0.3f} {command}"
        return command

    def _is_value_command(self):
        ''' true if the command is a valid value expression '''
        command = self.command
        if command:
            result = "{#}" in command 
            if self.is_release_command:
                release_command = self._command_release
                if release_command:
                    result = result and "{#}" in release_command 
            return result
        return False
           

    @property
    def command_min_range(self) -> float:
        return self._command_min_range
    @command_min_range.setter
    def command_min_range(self, value: float):
        self._command_min_range = value
        if self._verbose: syslog.info(f"set command min: {value:0.3f}")

    @property
    def command_max_range(self) -> float:
        return self._command_max_range
    @command_max_range.setter
    def command_max_range(self, value: float):
        self._command_max_range = value
        if self._verbose: syslog.info(f"set command max: {value:0.3f}")

    @property
    def command_mode(self) -> SimConnectCommandMode:
        return self._command_mode
    
    @command_mode.setter
    def command_mode(self, value : SimConnectCommandMode):
        self._command_mode = value

    @property
    def command_type(self) -> SimConnectCommandType:
        return self._command_type
    
    @command_type.setter
    def command_type(self, value : SimConnectCommandType):
        self._command_type = value

    @property
    def command(self):
        ''' active simconnect command for this action '''
        return self._command
    
    @command.setter
    def command(self, value):
        if value != self._command:
            # update command and associated block
            
            self._command = value
            self.update_block()        

    @property
    def command_release(self):
        ''' active simconnect command for this action '''
        return self._command_release
    
    @command_release.setter
    def command_release(self, value):
        self._command_release = value
                             

    @property
    def command_description(self) -> str:
        if self.block:
            return self.block.display_block_type
        return ""
    

    def scale_output(self, value):
        ''' scales a NORMALIZED output value from a value -1 to +1 '''
        return gremlin.util.scale_to_range(value, target_min = self.command_min_range, target_max = self.command_max_range, invert=self.inverted)
    


    def get_filtered_axis_value(self, value : float = None) -> float:
        ''' computes the output value for the current configuration  '''

        if value is None:
            # filter input
            value = gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, 
                                                        self.hardware_input_id)

        return value
    
    def get_local_curve_value(self, value : float) -> float:
        # apply local curve if any
        if self.curve_data:
            value = self.curve_data.curve_value(value)
        return value


    def get_raw_axis_value(self):
        if self.input_is_hardware():
            return gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)
        return self.hardware_input_id.axis_value


    def display_name(self):
        ''' returns a string for this action for display purposes '''
        return self.block.display_name
      

    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        return "mdi.airplane"
    

    
    def update_block(self):
        ''' updates the data block with the current command '''
        if self._command is None:
            self._command = self._default_command()
        block : SimConnectBlock = self._manager.block(self._command)
        if block and not block.command_type:
            block.command_type = self.command_type # SimConnectCommandType.Event
        self._block = block
        if block:
            # set data
            #self.command = block.command
            # self.command_min_range = block.min_range
            # self.command_max_range = block.max_range
            self.category = block.category
            self.units = block.units
            self.is_ranged = block.is_ranged
            self._is_axis = block.is_axis

   
    
    @property
    def block(self):
        ''' returns the current data block '''
        if self._block is None:
            # create it for the current command
            self.update_block()

        return self._block
    
    @property
    def limit_min_range(self) -> float:
        return self._limit_min_range
    @property
    def limit_max_range(self) -> float:
        return self._limit_max_range
    
    @property
    def value(self) -> float:
        min_norm = self.normalized_min_range
        min_range = self.command_min_range
        max_range = self.command_max_range
        value = gremlin.util.scale_to_range(min_norm, target_min = min_range, target_max = max_range, invert = self.inverted)
        return value
    

    @property
    def output_min_range(self) -> float:
        return self._output_min_range
    @output_min_range.setter
    def output_min_range(self, value : float):
        self._output_min_range = value
        if self._verbose: syslog.info(f"set output min: {value:0.3f}")

    @property
    def output_max_range(self) -> float:
        return self._output_max_range
    @output_max_range.setter
    def output_max_range(self, value : float):
        self._output_max_range = value
        if self._verbose: syslog.info(f"set output max: {value:0.3f}")

    @property
    def normalized_min_range(self) -> float:
        return self._normalized_min_range
    
    def setNormalized(self, min_value : float, max_value : float, update = False):
        ''' set normalized values '''
        self._normalized_min_range = min_value
        self._normalized_max_range = max_value
        if update:
            self._update_from_normalized()

        if self._verbose: syslog.info(f"set norm min max: {min_value:0.3f} {max_value:0.3f}")
        
    
    @normalized_min_range.setter
    def normalized_min_range(self, value : float):
        ''' normalized output min -1 to +1 '''
        self._normalized_min_range = value
        if self._verbose: syslog.info(f"set norm min: {value:0.3f}")

    @property
    def normalized_max_range(self) -> float:
        return self._normalized_max_range
    
    @normalized_max_range.setter
    def normalized_max_range(self, value : float):
        ''' normalized output max -1 to +1 '''
        self._normalized_max_range = value
        if self._verbose: syslog.info(f"set norm min: {value:0.3f}")

    @property
    def percent_min_range(self) -> float:
        ''' percent output min 0 to 100 '''
        return self._percent_min_range
    
    @percent_min_range.setter
    def percent_min_range(self, value : float):
        self._percent_min_range = value
        if self._verbose: syslog.info(f"set percent min: {value:0.3f}")

    @property
    def percent_max_range(self) -> float:
        ''' percent output max 0 to 100 '''
        return self._percent_max_range
    
    @percent_max_range.setter
    def percent_max_range(self, value : float):
        self._percent_max_range = value
        if self._verbose: syslog.info(f"set percent max: {value:0.3f}")


    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        return False
    

    def _update_from_percent(self):
        ''' updates output data from percent min/max'''
        self.normalized_min_range =  gremlin.util.scale_to_range(self._normalized_min_range, source_min = 0, source_max = 100)
        self.normalized_max_range =  gremlin.util.scale_to_range(self._normalized_min_range, source_min = 0, source_max = 100)
        self._update_from_normalized()

    
    def _update_percent(self):
        ''' updates percent range from normalized data '''
        self.percent_min_range = gremlin.util.scale_to_range(self._normalized_min_range, target_min=0, target_max = 100)
        self.percent_max_range = gremlin.util.scale_to_range(self._normalized_max_range, target_min=0, target_max = 100)

    def _update_from_normalized(self):
        ''' updates output data from normalized min/max'''
        self.output_min_range = gremlin.util.scale_to_range(self._normalized_min_range, source_min = self._normalized_min_range, source_max = self._normalized_max_range, target_min=self._command_min_range, target_max = self._command_max_range)
        self.output_max_range = gremlin.util.scale_to_range(self._normalized_max_range, source_min = self._normalized_min_range, source_max = self._normalized_max_range, target_min=self._command_min_range, target_max = self._command_max_range)
        self._update_percent()

    def _update_from_output(self):
        ''' updates normalized range from the output range '''
        self.normalized_min_range = gremlin.util.scale_to_range(self._output_min_range, source_min = self._output_min_range, source_max = self._output_max_range)
        self.normalized_max_range = gremlin.util.scale_to_range(self._output_max_range, source_min = self._output_min_range, source_max = self._output_max_range)
        self._update_percent()


        
    def _parse_xml(self, node, data = None):
        """Reads the contents of an XML node to populate this instance.

        :param node the node whose content should be used to populate this
            instance
        """



        default_command = self._default_command()
        self._command = safe_read(node,"command",str, default_command)
        self._command_release = safe_read(node,"command_release",str, "")
        self.is_release_command = safe_read(node,"has_release", bool, False)
        self._block = SimConnectManager().block(self._command)
        

        # debug
        mode = self.get_mode()
        if mode == "duke" and self._command == "THROTTLE1_AXIS_SET_EX1":
            for attrib in node.attrib:
                print (f"{attrib}: {node.get(attrib)}")
            pass
                       


        update_from_output = False
        if "min_range" in node.attrib:
            # old profile 
            self.output_min_range = safe_read(node,"min_range", float)
            update_from_output = True
        else:
            self.output_min_range = safe_read(node,"output_min_range", float) if "output_min_range" in node.attrib else -16383

        

        if "max_range" in node.attrib:
            # old profile
            self.output_max_range = safe_read(node,"max_range", float)
            update_from_output = True
        else:
            self.output_max_range = safe_read(node,"output_max_range", float) if "output_max_range" in node.attrib else 16384

        if update_from_output:
            # old profile
            self._update_from_output()
        else:
            # read data
            norm_min = safe_read(node,"norm_min_range", float) if "norm_min_range" in node.attrib else -1.0
            norm_max = safe_read(node,"norm_max_range", float) if "norm_max_range" in node.attrib else 1.0

            if norm_min == norm_max or \
                not gremlin.util.valueInRange(norm_min,-1,1) or \
                not gremlin.util.valueInRange(norm_max,-1,1):
                # reset bad data
                syslog.error(f"RANGE ERROR: values for min {norm_min:0.3f} and max {norm_max:0.3f} range are identical - reset to -1,+1")
                norm_min = -1
                norm_max = +1

            self._normalized_min_range = norm_min
            self._normalized_max_range = norm_max

        
        min_value = safe_read(node,"command_min_range", float) if "command_min_range" in node.attrib else -16383
        max_value = safe_read(node,"command_max_range", float) if "command_max_range" in node.attrib else 16384
        self.command_min_range = min_value
        self.command_max_range = max_value


        s_mode = safe_read(node, "mode", str, "")
        if s_mode:
            self.mode = SimConnectActionMode.to_enum(s_mode)

        if "command_mode" in node.attrib:
            self._command_mode = SimConnectCommandMode.to_enum(node.get("command_mode"))

        if "type" in node.attrib:
            self._command_type = SimConnectCommandType.to_enum(node.get("type"))

        self.inverted = safe_read(node,"inverted",bool, False)
        if "trigger" in node.attrib:
            s_trigger = safe_read(node,"trigger",str,"")
            self.trigger_mode = SimConnectTriggerMode.to_enum(s_trigger)

        if "units" in node.attrib:
            self.units = safe_read(node,"units",str,"Number")

        if "data_type" in node.attrib:
            self.data_type= safe_read(node,"data_type",str,"int")

        if "delay" in node.attrib:
            self.auto_repeat_interval = safe_read(node, "delay", int, 250)

        if "autorepeat" in node.attrib:
            self.auto_repeat = safe_read(node,"autorepeat", bool, False)
        
        self.trigger_on_release = safe_read(node,"trigger_on_release", bool, False)
        self.trigger_on_press = safe_read(node,"trigger_on_press", bool, True)


        node_block =gremlin.util.get_xml_child(node,"block")
        if node_block is not None:
            if not self._block:
                self._block = SimConnectBlock()    
            self._block.from_xml(node_block, data)
            self._block.update()
        
        self.update_block()

        # curve data
        curve_node = gremlin.util.get_xml_child(node,"response-curve-ex")
        if curve_node is not None:
            self.curve_data = gremlin.curve_handler.AxisCurveData()
            self.curve_data._parse_xml(curve_node)
            self.curve_data.curve_update()


    def _default_command(self):
        ''' default command'''
        return "AXIS_THROTTLE_SET" if self.hardware_input_type == InputType.JoystickAxis else "LIGHT_BEACON"

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(MapToSimConnect.tag)
        if self.block:
            node_block = self.block.to_xml()
            node.append(node_block)

        command = self._command if self._command else ""
        command_release = self._command_release if self._command_release else ""
        if command == "THROTTLE1_AXIS_SET_EX1":
            pass

        node.set("command",safe_format(command, str))
        node.set("command_release",safe_format(command_release, str))
        node.set("mode", SimConnectActionMode.to_string(self.mode))
        node.set("command_mode", SimConnectCommandMode.to_string(self._command_mode))
        node.set("has_release", safe_format(self.is_release_command, bool))
        node.set("type", SimConnectCommandType.to_string(self._command_type))
        node.set("units", self.units)
        node.set("datatype", self.data_type)

        node.set("trigger_on_release", safe_format(self.trigger_on_release, bool))
        node.set("trigger_on_press", safe_format(self.trigger_on_press, bool))
        node.set("trigger", SimConnectTriggerMode.to_string(self.trigger_mode))
        node.set("autorepeat", safe_format(self.auto_repeat, bool))
        node.set("delay", safe_format(self.auto_repeat_interval, int))
        node.set("norm_min_range", safe_format(self.normalized_min_range, float)) 
        node.set("norm_max_range", safe_format(self.normalized_max_range, float)) 
        node.set("command_min_range", safe_format(self.command_min_range, float)) 
        node.set("command_max_range", safe_format(self.command_max_range, float)) 
        node.set("inverted", safe_format(self.inverted, bool))            

        if self.curve_data is not None:
            curve_node =  self.curve_data._generate_xml()
            curve_node.tag = "response-curve-ex"
            node.append(curve_node)                


        if self.is_ranged:
            comment = f"Computed range values: [{self.output_min_range:0.3f}, {self.output_max_range:0.3f}]  percentage: [{self.percent_min_range:0.3f}, {self.percent_max_range:0.3f}]"
        else:
            comment = f"Computed value: {self.output_min_range:0.3f} percentage: {self.percent_min_range:0.3f}"

        node_comment = etree.Comment(comment)
        node.append(node_comment)
        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return True
    

    def __getstate__(self):
        ''' serialization override '''
        state = self.__dict__.copy()
        # sm is not serialized, remove it
        del state["smd"]
        return state

    def __setstate__(self, state):
        ''' serialization override '''
        self.__dict__.update(state)
        # sm is not serialized, add it
        eh = SimConnectEventHandler()
        self._manager = eh.manager




version = 1
name = "map-to-simconnect"
create = MapToSimConnect


# listening monitor for profile and aicraft mode changes
monitor = SimconnectMonitor()