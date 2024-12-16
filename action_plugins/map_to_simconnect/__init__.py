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

from PySide6 import QtWidgets, QtCore, QtGui

import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
from gremlin.input_types import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.macro
import gremlin.shared_state

import gremlin.shared_state
import gremlin.singleton_decorator
import gremlin.ui.ui_common
import gremlin.ui.input_item
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
    
class SimconnectAicraftDefinition():
    ''' holds the data entry for a single aicraft from the MSFS config data '''
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
                 ):
        self.icao_type = icao_type
        self.icao_manufacturer = icao_manufacturer
        self.icao_model = icao_model
        self.titles = titles
        self.path = path.casefold() if path else ""
        self.state_folder = state_folder.casefold() if state_folder else ""
        self.mode = mode
        
        self.id = id if id else gremlin.util.get_guid()

        assert community_path and aircraft_path,"Community path and Aircraft path are primary keys and cannot be NULL"
        self.community_path = community_path.casefold() 
        self.aircraft_path = aircraft_path.casefold()

        
        
        # runtime item (not saved or loaded)
        self.selected = False # for UI interation - selected mode
        self.error_status = None

    @property
    def display_name(self):
        return f"{self.icao_manufacturer} {self.icao_model} ({self.aircraft_path})"
    
    @property
    def key(self):
        return (self.community_path, self.aircraft_path)  # unique key

    @property
    def valid(self):
        ''' true if the item contains valid data '''
        return not self.error_status and self.aircraft and self.mode
   
    
class SimconnectSortMode(Enum):
    NotSet = auto()
    AicraftAscending = auto()
    AircraftDescending = auto()
    Mode = auto()

@gremlin.singleton_decorator.SingletonDecorator
class SimconnectOptions(QtCore.QObject):


    ''' holds simconnect mapper options for all actions '''
    def __init__(self, simconnect : SimConnect):
        super().__init__()
        self._profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        self._mode_list = self._profile.get_modes()
        base_file = "simconnect_config.xml"
        user_source = os.path.join(gremlin.util.userprofile_path(),base_file)
        self._xml_source = user_source
        
        self._auto_mode_select = True # if set, autoloads the mode associated with the aircraft if such a mode exists
        self._aircraft_definitions = [] # holds aicraft entries
        self._titles = []
        # Steam version
        #self._community_folder = r"C:\Microsoft Flight Simulator\Community"
        # Microsoft store version MSFS 2024: %appdata%\Local\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community
        app_data = os.getenv("appdata")
        self._community_folder = os.path.join(app_data, "Local","Packages","Microsoft.Limitless_8wekyb3d8bbwe","LocalCache","Packages","Community")

        self._sort_mode = SimconnectSortMode.NotSet
        self.parse_xml()
        self._simconnect = simconnect
       

    @property
    def current_aircraft_folder(self):
        if self._simconnect.ok:
            return self._aircraft_folder
        return None
    
    @property
    def current_aircraft_title(self):
        if self._simconnect.ok:
            return self._aircraft_title
        return None
    
    @property
    def community_folder(self):
        return self._community_folder
    @community_folder.setter
    def community_folder(self, value):
        if os.path.isdir(value) and value != self._community_folder:
            self._community_folder = value
        

    def validate(self):
        ''' validates options are ok '''
        a_list = []
        valid = True
        for item in self._aircraft_definitions:
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
        for item in self._aircraft_definitions:
            print (item.path)
            if item.path.endswith(stub):
                return item
        return None




    def find_definition_by_aicraft(self, aircraft) -> SimconnectAicraftDefinition:
        ''' gets an item by aircraft name (not case sensitive)'''
        if not aircraft:
            return None
        key = aircraft.lower().strip()
        item : SimconnectAicraftDefinition
        for item in self._aircraft_definitions:
            if item.key == key:
                return item
        return None
    
    def find_definition_by_title(self, title) -> SimconnectAicraftDefinition:
        ''' finds aircraft data by the loaded aircraft title '''
        if not title:
            return None
        for item in self._aircraft_definitions:
            if title in item.titles:
                return item
            
        return None
    

        
    
    @property
    def auto_mode_select(self):
        return self._auto_mode_select
    @auto_mode_select.setter
    def auto_mode_select(self, value):
        self._auto_mode_select = value
        
    


            



    def save(self):
        ''' saves the configuration data '''
        self.to_xml()

    def parse_xml(self):
        xml_source = self._xml_source
        if not os.path.isfile(xml_source):
            # options not saved yet - ignore
            return
        
    
        self._titles = []

        default_mode = gremlin.shared_state.current_profile.get_default_mode()
        
        
        try:
            parser = etree.XMLParser(remove_blank_text=True)
            root = etree.parse(xml_source, parser)

            nodes = root.xpath('//options')
            for node in nodes:
                if "auto_mode_select" in node.attrib:
                    self._auto_mode_select = safe_read(node,"auto_mode_select",bool,True)
                if "community_folder" in node.attrib:
                    self._community_folder = safe_read(node,"community_folder", str, "")
                if "sort" in node.attrib:
                    try:
                        sort_mode = safe_read(node,"sort",int, SimconnectSortMode.NotSet.value)
                        self._sort_mode = SimconnectSortMode(sort_mode)
                    except:
                        self._sort_mode = SimconnectSortMode.NotSet
                        pass
                break

            # reference items scanned from MSFS
            node_items = None
            nodes = root.xpath("//items")
            for node in nodes:
                node_items = node
                break

            if node_items is not None:
                for node in node_items:
                    icao_model = safe_read(node,"model", str, "")
                    icao_manufacturer = safe_read(node,"manufacturer", str, "")
                    icao_type = safe_read(node,"type", str, "")
                    path = safe_read(node,"path", str, "")
                    mode = safe_read(node,"mode", str, default_mode)
                    id = safe_read(node,"id", str, "")
                    state_folder = safe_read(node,"state_folder",str,"")
                    community_path = safe_read(node,"community_path",str,"")
                    aircraft_path = safe_read(node,"aircraft_path",str,"")
                    titles = []
                    node_titles = None
                    for child in node:
                        node_titles = child

                    if node_titles is not None:
                        for child in node_titles:
                            titles.append(child.text)

                    if icao_model and icao_manufacturer and icao_type:
                        item = SimconnectAicraftDefinition(id = id,
                                                           icao_model = icao_model,
                                                           icao_manufacturer = icao_manufacturer,
                                                           icao_type = icao_type,
                                                           titles = titles,
                                                           path = path,
                                                           mode = mode,
                                                           community_path=community_path,
                                                           aircraft_path=aircraft_path,
                                                           state_folder = state_folder)
                        self._aircraft_definitions.append(item)

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
            logging.getLogger("system").error(f"Simconnect Config: XML read error: {xml_source}: {err}")
            return False

    def to_xml(self):
        # writes the configuration to xml

        root = etree.Element("simconnect_config")

        node_options = etree.SubElement(root, "options")
        # selection mode
        node_options.set("auto_mode_select",str(self._auto_mode_select))
        if self._community_folder and os.path.isdir(self._community_folder):
            # save valid community folder
            node_options.set("community_folder", self._community_folder)
        node_options.set("sort", str(self._sort_mode.value))

        # scanned aicraft titles
        if self._aircraft_definitions:
            node_items = etree.SubElement(root,"items")
            for item in self._aircraft_definitions:
                node = etree.SubElement(node_items,"item")
                node.set("model", item.icao_model)
                node.set("manufacturer", item.icao_manufacturer)
                node.set("type",item.icao_type)
                node.set("path", item.path)
                node.set("id", item.id)
                node.set("state_folder", item.state_folder)
                
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
        
        try:
            # save the file
            tree = etree.ElementTree(root)
            tree.write(self._xml_source, pretty_print=True,xml_declaration=True,encoding="utf-8")
        except Exception as err:
            logging.getLogger("system").error(f"SimconnectData: unable to create XML simvars: {self._xml_source}: {err}")

    def get_community_folder(self):
        ''' community folder '''
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
        ''' gets the active community folder '''
        from gremlin.ui import ui_common
        if not self._community_folder or not os.path.isdir(self._community_folder):
            folder = self.get_community_folder()
            if os.path.isdir(folder):
               folder = None
            
            self._community_folder = folder
        
        return self._community_folder





    def scan_entry(self, folder):
        ''' scans a single aicraft folder entry '''

        syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_simconnect

        community_folder = self._getCommunityFolder()
        if not community_folder:
            syslog.error(f"SIMCONNECT: community folder not found: {community_folder}")
            return

        aicraft_folder = os.path.join(os.path.dirname(community_folder), folder)
        item = self._read_folder(aicraft_folder)
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
        syslog = logging.getLogger("system")
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
                                                state_folder = state_folder
                                                )
            
            self._aircraft_definitions.append(item)
            return item

        return None            


    def scan_aircraft_config(self, owner):
        ''' scans MSFS folders for the list of aircraft names '''
        

        #options = SimconnectOptions()

        community_folder = self.community_folder
        if not community_folder:
            return
        

        # scan for lvars
        self._scan_lvars()
        
        progress = QtWidgets.QProgressDialog(parent = owner, labelText ="Scanning folders... (this can take a while)", cancelButtonText = "Cancel", minimum = 0, maximum= 100) #, flags = QtCore.Qt.FramelessWindowHint)
        progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress.setValue(0)
        progress.show()
        QtWidgets.QApplication.processEvents()

        # search_folder = os.path.dirname(community_folder)
        # source_files = gremlin.util.find_files(search_folder,"aircraft.cfg")
        # source_folders = [os.path.dirname(file) for file in source_files]

        root_folder = community_folder
        folders = gremlin.util.find_folders(root_folder)
        #folders = os.listdir(root_folder)

        source_files = []

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
                mapped_modes[item.display_name.lower()] = (item.id, item.mode)
            
            self._aircraft_definitions = items

            # sort
            self.sort()
        
            for item in self._aircraft_definitions:
                display_name = item.display_name.lower()
                if display_name in mapped_modes.keys():
                    item.id, item.mode = mapped_modes[display_name]

        self.save()
        progress.close()
        
        #gremlin.util.popCursor()
        
    def sort(self):
        ''' sorts definitions '''
        if self._sort_mode == SimconnectSortMode.AicraftAscending:
            self._aircraft_definitions.sort(key = lambda x: x.key)
        elif self._sort_mode == SimconnectSortMode.AircraftDescending:
            self._aircraft_definitions.sort(key = lambda x: x.key, reverse = True)
        elif self._sort_mode == SimconnectSortMode.Mode:
            self._aircraft_definitions.sort(key = lambda x: (x.mode.lower(), x.key))

@SingletonDecorator
class SimconnectMonitor():
    ''' helper class '''
    def __init__(self):
        syslog = logging.getLogger("system")
        syslog.info("SCMonitor: listening")
        self._manager = SimConnectManager()
        self._manager.aircraft_loaded.connect(self._aircraft_loaded)
        self._started = False
        self._mode_change_enabled = False
        el= gremlin.event_handler.EventListener()
        el.profile_started.connect(self._profile_start) # occurs after a profile has started to change the default mode if needed
        el.profile_stop.connect(self.stop)
        el.shutdown.connect(self._shutdown)


    def getStartupMode(self):
        ''' gets the startup mode for the current aicraft '''

        if self._manager.is_running:
            # sim is running
            options = SimconnectOptions(self._manager.simconnect)
            state_folder = self._manager.current_aircraft_folder

            if state_folder:
                item = options.find_definition_by_state(state_folder)
                if item is not None:
                    # found the aicraft entry
                    key = item.key
                    profile = gremlin.shared_state.current_profile
                    mode = profile.getSimconnectMode(key)
                    syslog = logging.getLogger("system")
                    syslog.info(f"SCMONITOR: Aircraft changed profile mode select: {mode}")
                    return mode
            
        return None
    
    @QtCore.Slot()
    def _profile_start(self):
        ''' occurs when a profile starts '''
        import gremlin.execution_graph
        ec = gremlin.execution_graph.ExecutionContext()
        if ec.findActionPlugin(MapToSimConnect.name):
            logging.getLogger("system").info(f"SCMONITOR: Start")
            self.start()
        else:
            self.stop() # stop monitoring if it was
            logging.getLogger("system").info(f"SCMONITOR: no simconnect mappings found - start skipped")

    
    def start(self):
        ''' starts monitoring for aicraft changes '''
        if self._started:
            return
        if not self._manager.is_running:
            self._manager.reconnect() # connect if we're not connected
        if not self._manager.is_running:
            syslog = logging.getLogger("system")
            syslog.error("SCMONITOR: Unable to start monitor, sim is not running")
            return
        self._started = True
        options = SimconnectOptions(self._manager.simconnect)
        # see if we need to change modes automatically
        self._mode_change_enabled = options.auto_mode_select
        if self._mode_change_enabled:
            self._manager.aircraft_loaded.connect(self._aircraft_loaded)
            # request the current aircraft
            self._manager.update_aircraft_folder()
        
        
            



    def stop(self):
        ''' stop monitorin  '''
        if not self._started:
            return 
        if self._mode_change_enabled:
            self._manager.aircraft_loaded.disconnect(self._aircraft_loaded)
        self._started = False

    def _shutdown(self):
        ''' program exit '''
        syslog = logging.getLogger("system")
        syslog.info("SCMonitor: shutdown")
        self.stop()
        if self._mode_change_enabled:
            self._manager.aircraft_loaded.disconnect(self._aircraft_loaded)
        self._manager = None

    @QtCore.Slot(str, str)
    def _aircraft_loaded(self, folder, title):
        syslog = logging.getLogger("system")
        syslog.info(f"SCMONITOR: Aircraft changed detected: {title}")
        mode = self.getStartupMode()
        if mode:
            # request a mode change 
            eh = gremlin.event_handler.EventHandler()
            eh.change_mode(mode)


        




class SimconnectOptionsUi(gremlin.ui.ui_common.QRememberDialog):
    """UI to set individual simconnect  settings """

    def __init__(self, simconnect : SimConnect, parent=None):
        from gremlin.ui import ui_common
        super().__init__(self.__class__.__name__, parent)

        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.smmgr = SimConnectManager()
        self.smmgr.reconnect()
        self.smmgr.aircraft_loaded.connect(self._aircraft_loaded)
        self.smmgr.sim_state.connect(self._sim_state)


        # Actual configuration object being managed
        self.config = gremlin.config.Configuration()
        self.setMinimumWidth(600)


        self.mode_list = []
        self.profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        self.mode_list = self.profile.get_modes()
        

        # display name to mode pair list
        self.mode_pair_list = gremlin.ui.ui_common.get_mode_list(self.profile)

        self.options = SimconnectOptions(simconnect)

        self.setWindowTitle("Simconnect Options")

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self._auto_mode_switch = QtWidgets.QCheckBox("Change profile mode based on active aicraft")
        self._auto_mode_switch.setToolTip("When enabled, the profile mode will automatically change based on the mode associated with the active player aircraft in Flight Simulator")
        self._auto_mode_switch.setChecked(self.options.auto_mode_select)
        self._auto_mode_switch.clicked.connect(self._auto_mode_select_cb)

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
        self.edit_mode_widget.setIcon(gremlin.util.load_icon("manage_modes.svg"))
        self.edit_mode_widget.clicked.connect(self._manage_modes_cb)
        self.edit_mode_widget.setToolTip("Manage Modes")

        
        self.scan_aircraft_widget = QtWidgets.QPushButton("Scan Aircraft")
        self.scan_aircraft_widget.setIcon(gremlin.util.load_icon("mdi.magnify-scan"))
        self.scan_aircraft_widget.clicked.connect(self._scan_aircraft_cb)
        self.scan_aircraft_widget.setToolTip("Scan MSFS aicraft folders for aircraft names")

        self.current_aircraft_widget = ui_common.QDataLineEdit()
        self.current_aircraft_widget.setReadOnly(True)


        self.current_aircraft_folder = None # holds the active aircraft data folder


        self.add_current_aircraft_widget = QtWidgets.QPushButton("Add Current Aircraft")
        self.add_current_aircraft_widget.clicked.connect(self._add_current_aircraft_cb)

        
        self.container_bar_layout.addWidget(self.edit_mode_widget)
        self.container_bar_layout.addWidget(self.scan_aircraft_widget)
        self.container_bar_layout.addWidget(QtWidgets.QLabel("Current Aircraft:"))
        self.container_bar_layout.addWidget(self.current_aircraft_widget)
        self.container_bar_layout.addWidget(self.add_current_aircraft_widget)
        self.container_bar_layout.addStretch()

        # start scrolling container widget definition

        self.container_map_widget = QtWidgets.QWidget()
        self.container_map_layout = QtWidgets.QVBoxLayout(self.container_map_widget)
        self.container_map_layout.setContentsMargins(0,0,0,0)

        # add aircraft map items
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()

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
        

        self.scroll_layout.addWidget(self.map_widget)
        self.scroll_layout.setContentsMargins(6,0,6,0)
        self.scroll_layout.addStretch()
        self.container_map_layout.addWidget(self.scroll_area)

        # end scrolling container widget definition

        
        self.close_button_widget = QtWidgets.QPushButton("Close")
        self.close_button_widget.clicked.connect(self.close_button_cb)


        button_bar_widget = QtWidgets.QWidget()
        button_bar_layout = QtWidgets.QHBoxLayout(button_bar_widget)
        button_bar_layout.addStretch()
        button_bar_layout.addWidget(self.close_button_widget)


        self.main_layout.addWidget(self._auto_mode_switch)
        self.main_layout.addWidget(self._msfs_path_widget)
        self.main_layout.addWidget(self.container_bar_widget)
        self.main_layout.addWidget(self.container_map_widget)
        self.main_layout.addWidget(button_bar_widget)


        
        self._populate_ui()

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

    @QtCore.Slot()
    def _scan_aircraft_cb(self):
        self.options.scan_aircraft_config(self)

        # update the aicraft drop down choices
        self._populate_ui()

    def _update_current_aircraft(self):
        ''' request an update from simconnect on the current aircraft '''
        self.smmgr.update_aircraft_folder() # will trigger the aircraft loaded callback 



    @QtCore.Slot()
    def _add_current_aircraft_cb(self):
        ''' adds the current simconnect aircraft to the mode list '''
        title = self.current_aircraft_widget.text()
        folder = self.current_aircraft_folder
        if os.path.isdir(folder):
            if not self.options.find_definition_by_title(title):
                self.options.scan_entry(folder)

        

    @QtCore.Slot(str,str)
    def _aircraft_loaded(self, folder, title):
        ''' triggered when simconnect sends aircraft data '''
        self.current_aircraft_widget.setText(title)
        self.current_aircraft_folder = folder
        add_enabled = bool(title)
        self.add_current_aircraft_widget.setEnabled(add_enabled)

    @QtCore.Slot(int, float, str)
    def _sim_state(self, int_data, float_data_, str_data):
        ''' triggered on state requests '''
        # the data will be returned as a partial subfolder so we need to match it to the actual aircraft

        item = self.options.find_definition_by_state(str_data)
        if item:
            self._aircraft_loaded(item.path, item.display_name)



    @QtCore.Slot()
    def close_button_cb(self):
        ''' called when close button clicked '''
        self.close()

    

    def _populate_ui(self):
        ''' populates the map of aircraft to profile modes '''

        from gremlin.ui import ui_common
        self.options.validate()

        # current aircraft
        self._update_current_aircraft()


        # figure out the size of the header part of the control so things line up
        lbl = QtWidgets.QLabel("w")
        char_width = lbl.fontMetrics().averageCharWidth()
        headers = ["Aicraft:"]
        width = 0
        for header in headers:
            width = max(width, char_width*(len(header)))


        # clear the widgets
        ui_common.clear_layout(self.map_layout)

        # display one row per aicraft found
        if not self.options._aircraft_definitions:
             missing = QtWidgets.QLabel("No mappings found.")
             missing.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
             self.map_layout.addWidget(missing)
             return

        gremlin.util.pushCursor()

        item : SimconnectAicraftDefinition

        self._mode_selector_map = {}
        self._selected_cb_map = {}
        row = 0
        display_width = width

        # current profile
        profile = gremlin.shared_state.current_profile
        default_mode = profile.get_default_mode()
        

        for item in self.options._aircraft_definitions:

            # header row
            if row == 0:
      
                select_widget = QtWidgets.QCheckBox()
                select_widget.clicked.connect(self._global_selected_changed_cb)
                select_widget.setToolTip("Select/Deselect All")

                aircraft_header_widget = QtWidgets.QWidget()
                aircraft_header_layout = QtWidgets.QHBoxLayout(aircraft_header_widget)

                self.display_header_widget = QtWidgets.QLabel("Aicraft")
                aircraft_header_layout.addWidget(self.display_header_widget)
                display_sort_up_widget = QtWidgets.QPushButton()
                display_sort_up_widget.setIcon(gremlin.util.load_icon("fa.sort-asc"))
                display_sort_up_widget.setMaximumWidth(20)
                display_sort_up_widget.clicked.connect(self._sort_display_up_cb)
                display_sort_up_widget.setStyleSheet("border: none;")
                display_sort_up_widget.setToolTip("Sort aircraft ascending")

                display_sort_down_widget = QtWidgets.QPushButton()
                display_sort_down_widget.setIcon(gremlin.util.load_icon("fa.sort-desc"))
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
                mode_sort_up_widget.setIcon(gremlin.util.load_icon("fa.sort-asc"))
                mode_sort_up_widget.setMaximumWidth(20)
                mode_sort_up_widget.clicked.connect(self._sort_mode_up_cb)
                mode_sort_up_widget.setStyleSheet("border: none;")
                mode_sort_up_widget.setToolTip("Sort by mode")


                mode_widget = QtWidgets.QLabel("Mode")
                mode_header_layout.addWidget(mode_widget)
                mode_header_layout.addStretch()
                mode_header_layout.addWidget(mode_sort_up_widget)
                




                manufacturer_widget = QtWidgets.QLabel("Manufacturer")

                type_widget = QtWidgets.QLabel("Type")
                model_widget = QtWidgets.QLabel("Model")
                community_widget = QtWidgets.QLabel("Community Folder")
                aircraft_widget = QtWidgets.QLabel("Aircraft Folder")


                row_selector = ui_common.QRowSelectorFrame()
                row_selector.setSelectable(False)
                spacer = QDataWidget()
                spacer.setMinimumWidth(3)
                self.map_layout.addWidget(row_selector, 0, 0, 1, -1)
                
                self.map_layout.addWidget(spacer, 0, 1)
                self.map_layout.addWidget(select_widget, 0, 2)
                self.map_layout.addWidget(aircraft_header_widget, 0, 3)
                self.map_layout.addWidget(mode_header_widget, 0, 4)
                self.map_layout.addWidget(manufacturer_widget, 0, 5)
                self.map_layout.addWidget(model_widget, 0, 6)
                self.map_layout.addWidget(type_widget, 0, 7)
                self.map_layout.addWidget(community_widget,0,8)
                self.map_layout.addWidget(aircraft_widget,0,9)

                row+=1
                continue

            
             # selector
            row_selector = ui_common.QRowSelectorFrame(selected = item.selected)
            row_selector.setMinimumHeight(30)
            row_selector.selected_changed.connect(self._row_selector_clicked_cb)
            selected_widget = ui_common.QDataCheckbox(data = (item, row_selector))
            selected_widget.setChecked(item.selected)
            selected_widget.checkStateChanged.connect(self._selected_changed_cb)
            row_selector.data = ((item, selected_widget))

            # aicraft display
            self.display_header_widget = ui_common.QDataLineEdit(data = (item, selected_widget))
            self.display_header_widget.setReadOnly(True)
            self.display_header_widget.setText(item.display_name)
            self.display_header_widget.installEventFilter(self)
            w = len(item.display_name)*char_width
            if w > display_width:
                display_width = w

            # manufacturer
            manufacturer_widget = ui_common.QDataLineEdit(data = (item, selected_widget))
            manufacturer_widget.setReadOnly(True)
            manufacturer_widget.setText(item.icao_manufacturer)
            manufacturer_widget.installEventFilter(self)

            # model
            model_widget = ui_common.QDataLineEdit(data = (item, selected_widget))
            model_widget.setReadOnly(True)
            model_widget.setText(item.icao_model)
            model_widget.installEventFilter(self)

            # type
            type_widget = ui_common.QDataLineEdit(data = (item, selected_widget))
            type_widget.setReadOnly(True)
            type_widget.setText(item.icao_type)
            type_widget.installEventFilter(self)

            # community folder
            community_widget = ui_common.QDataLineEdit(data = (item, selected_widget))
            community_widget.setReadOnly(True)
            community_widget.setText(item.community_path)
            community_widget.installEventFilter(self)

            # aircraft folder
            aircraft_widget = ui_common.QDataLineEdit(data = (item, selected_widget))
            aircraft_widget.setReadOnly(True)
            aircraft_widget.setText(item.aircraft_path)
            aircraft_widget.installEventFilter(self)

            
       

            # mode drop down
            mode_selector = ui_common.QDataComboBox(data = (item, selected_widget))

   

            for display_mode, mode in self.mode_pair_list:
                mode_selector.addItem(display_mode, mode)

            mode = profile.getSimconnectMode(item.key)
            if not mode:
                mode = default_mode

            index = mode_selector.findData(mode)
            mode_selector.setCurrentIndex(index)
            mode_selector.currentIndexChanged.connect(self._mode_selector_changed_cb)
            self._mode_selector_map[item] = mode_selector
            self._selected_cb_map[item] = selected_widget

            self.map_layout.addWidget(row_selector, row ,0 , 1, -1)
            
            spacer = QDataWidget()
            spacer.setMinimumWidth(3)
            spacer.installEventFilter(self)
            
            self.map_layout.addWidget(spacer, row, 1)
            self.map_layout.addWidget(selected_widget, row, 2)
            self.map_layout.addWidget(self.display_header_widget, row, 3 )
            self.map_layout.addWidget(mode_selector, row, 4 )
            self.map_layout.addWidget(manufacturer_widget,row, 5 )
            self.map_layout.addWidget(model_widget,row, 6)
            self.map_layout.addWidget(type_widget,row, 7)
            self.map_layout.addWidget(community_widget,row, 8)
            self.map_layout.addWidget(aircraft_widget,row, 9)

            spacer = QDataWidget()
            spacer.installEventFilter(self)
            spacer.setMinimumWidth(6)
            self.map_layout.addWidget(spacer, row, 8)


            row += 1


        self.map_layout.setColumnStretch(3,2)
        self.map_layout.setColumnMinimumWidth(3, display_width)


        gremlin.util.popCursor()


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
        return [item for item in self.options._aircraft_definitions if item.selected]


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
        if t == QtCore.QEvent.Type.MouseButtonPress:
            item, selected_widget = widget.data
            selected_widget.setChecked(not selected_widget.isChecked())


        return False


    @QtCore.Slot(int)
    def _mode_selector_changed_cb(self, selected_index):
        ''' occurs when the mode is changed on an entry '''
        profile = gremlin.shared_state.current_profile
        widget = self.sender()
        mode = widget.currentData()
        item, _ = widget.data
        items = self._get_selected()
        if not item in items:
            items.append(item)
        mode_index = None
        for item in items:
            key = item.key
            profile.setSimconnectMode(key, mode)
            selector = self._mode_selector_map[item]
            with QtCore.QSignalBlocker(selector):
                if mode_index is None:
                    mode_index = selector.findData(mode)
                selector.setCurrentIndex(mode_index)

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
        logging.getLogger("system").info(f"Aircraft: {aircraft} model: {model} title: {title}")
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
        

        handler = SimConnectEventHandler()
        self._simconnect = handler.simconnect

        # handler to update curve widget if displayed
        self.curve_update_handler = None
        self.input_type = self.action_data.hardware_input_type 
        self._is_axis = self.action_data.input_is_axis()


    @QtCore.Slot()
    def _action_range_changed(self):
        ''' occurs when the range update to the action data caused another update '''
        self._update_block_ui()

    def _create_ui(self):
        """Creates the UI components."""
        #import gremlin.gated_handler

        verbose = gremlin.config.Configuration().verbose_mode_detailed
        syslog = logging.getLogger("system")
        if verbose:
            syslog.info(f"Simconnect UI for: {self.action_data.hardware_input_type_name}  {self.action_data.hardware_device_name} input: {self.action_data.hardware_input_id}")



        # if the input is chained 
        self.chained_input = self.action_data.input_item.is_action

        # mode from aircraft button - grabs the aicraft name as a mode
        self._options_button_widget = QtWidgets.QPushButton("Simconnect Options")
        self._options_button_widget.setIcon(gremlin.util.load_icon("fa.gear"))
        self._options_button_widget.clicked.connect(self._show_options_dialog_cb)
        
        # command selector
        self._command_container_widget = QtWidgets.QWidget()
        self._command_container_widget.setContentsMargins(0,0,0,0)
        self._command_container_layout = QtWidgets.QVBoxLayout(self._command_container_widget)
        self._command_container_layout.setContentsMargins(0,0,0,0)
        


        self._action_selector_widget = QtWidgets.QWidget()
        self._action_selector_widget.setContentsMargins(0,0,0,0)
        self._action_selector_layout = QtWidgets.QHBoxLayout(self._action_selector_widget)
        self._action_selector_layout.setContentsMargins(0,0,0,0)

        # list of possible events to trigger
        self._command_selector_widget = gremlin.ui.ui_common.QComboBox()
        self._command_list = self.action_data.smd.get_command_name_list()
        self._command_selector_widget.setEditable(True)
        self._command_selector_widget.addItems(self._command_list)
        self._command_selector_widget.currentIndexChanged.connect(self._command_changed_cb)

        self._command_selector_widget.setValidator(CommandValidator())

        # setup auto-completer for the command
        command_completer = QtWidgets.QCompleter(self._command_list, self)
        command_completer.setCaseSensitivity(QtGui.Qt.CaseSensitivity.CaseInsensitive)
        command_completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)

        self._command_selector_widget.setCompleter(command_completer)

        #self.action_selector_layout.addWidget(self.category_widget)
        self._action_selector_layout.addWidget(QtWidgets.QLabel("Selected command:"))
        self._action_selector_layout.addWidget(self._command_selector_widget)
        self._action_selector_layout.addStretch()
        self._action_selector_layout.addWidget(self._options_button_widget)
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

        self._output_invert_axis_widget = QtWidgets.QCheckBox("Invert axis")
        self._output_invert_axis_widget.clicked.connect(self._output_invert_axis_cb)

        self._button_mode_container_widget = QtWidgets.QWidget()
        self._button_mode_container_layout = QtWidgets.QHBoxLayout(self._button_mode_container_widget)

        self._trigger_on_release_widget = QtWidgets.QCheckBox("Trigger on release")
        self._trigger_on_release_widget.clicked.connect(self._trigger_on_release_cb)

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
        
        

        self._output_range_ref_text_widget = QtWidgets.QLabel()
        self._output_range_container_layout.addWidget(self._output_range_ref_text_widget)

        output_data_entry_widget = QtWidgets.QWidget()
        output_data_entry_layout = QtWidgets.QHBoxLayout(output_data_entry_widget)
                
        self._output_min_range_widget = gremlin.ui.ui_common.QIntLineEdit()
        self._output_min_range_widget.setRange(-16383,16383)
        self._output_min_range_widget.valueChanged.connect(self._min_range_changed_cb)

        self._output_max_range_widget = gremlin.ui.ui_common.QIntLineEdit()
        self._output_max_range_widget.setRange(-16383,16383)
        self._output_max_range_widget.valueChanged.connect(self._max_range_changed_cb)

        self._output_min_normalized_range_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self._output_min_normalized_range_widget.valueChanged.connect(self._min_normalized_range_changed_cb)

        self._output_max_normalized_range_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self._output_max_normalized_range_widget.valueChanged.connect(self._max_normalized_range_changed_cb)


        self._output_min_percent_range_widget = gremlin.ui.ui_common.QFloatLineEdit(decimals=2)
        self._output_min_percent_range_widget.setReadOnly(True)

        self._output_max_percent_range_widget = gremlin.ui.ui_common.QFloatLineEdit(decimals=2)
        self._output_max_percent_range_widget.setReadOnly(True)


        self._reset_range_widget = QtWidgets.QPushButton("Reset")
        self._reset_range_widget.setToolTip("Reset the range to -1 +1")
        self._reset_range_widget.clicked.connect(self._reset_range)



        # output axis repeater
        self.container_repeater_widget = QtWidgets.QWidget()
        self.container_repeater_layout = QtWidgets.QHBoxLayout(self.container_repeater_widget)

         
        self.curve_button_widget = QtWidgets.QPushButton("Output Curve")
        self.curve_icon_inactive = gremlin.util.load_icon("mdi.chart-bell-curve",qta_color="gray")
        self.curve_icon_active = gremlin.util.load_icon("mdi.chart-bell-curve",qta_color="blue")
        self.curve_button_widget.setToolTip("Curve output")
        self.curve_button_widget.clicked.connect(self._curve_button_cb)

        self.curve_clear_widget = QtWidgets.QPushButton("Clear curve")
        delete_icon = gremlin.util.load_icon("mdi.delete")
        self.curve_clear_widget.setIcon(delete_icon)
        self.curve_clear_widget.setToolTip("Removes the curve output")
        self.curve_clear_widget.clicked.connect(self._curve_delete_button_cb)

        self._axis_repeater_widget = gremlin.ui.ui_common.AxisStateWidget(show_percentage=True,orientation=QtCore.Qt.Orientation.Horizontal)


        self.container_repeater_layout.addWidget(self.curve_button_widget)
        self.container_repeater_layout.addWidget(self.curve_clear_widget)
        self.container_repeater_layout.addWidget(self._axis_repeater_widget)
        self.container_repeater_layout.addStretch()
        self._update_curve_icon()


        if self.action_data.input_type == InputType.JoystickAxis:
            self._update_axis_widget()


        output_data_entry_layout.addWidget(self._output_invert_axis_widget)
        output_data_entry_layout.addWidget(QtWidgets.QLabel("Range min:"))
        output_data_entry_layout.addWidget(self._output_min_range_widget)
        output_data_entry_layout.addWidget(QtWidgets.QLabel("Max:"))
        output_data_entry_layout.addWidget(self._output_max_range_widget)

        output_data_entry_layout.addWidget(QtWidgets.QLabel("Norm. min:"))
        output_data_entry_layout.addWidget(self._output_min_normalized_range_widget)
        output_data_entry_layout.addWidget(QtWidgets.QLabel("Max:"))
        output_data_entry_layout.addWidget(self._output_max_normalized_range_widget)
        output_data_entry_layout.addWidget(self._reset_range_widget)
        
        # percent output
        output_data_entry_layout.addWidget(QtWidgets.QLabel("%Min:"))
        output_data_entry_layout.addWidget(self._output_min_percent_range_widget)
        output_data_entry_layout.addWidget(QtWidgets.QLabel("%Max:"))
        output_data_entry_layout.addWidget(self._output_max_percent_range_widget)
        
        output_data_entry_layout.addStretch()
        

        self._output_range_container_layout.addWidget(output_data_entry_widget)

        # holds the output value if the output value is a fixed value
        self._output_value_container_widget = QtWidgets.QWidget()
        self._output_value_container_layout = QtWidgets.QHBoxLayout(self._output_value_container_widget)
        self._output_value_container_widget.setContentsMargins(0,0,0,0)
        # msfs value display for -16368 +16367
        self._output_value_widget = gremlin.ui.ui_common.QIntLineEdit()
        self._output_value_widget.textChanged.connect(self._output_value_changed_cb)
        self._output_value_widget.setRange(-16368, 16367)
        # scaled value display for data entered -1 to +1
        self._output_value_normalized_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self._output_value_normalized_widget.valueChanged.connect(self._output_normalized_value_changed_cb)

        self._output_value_percent_widget = gremlin.ui.ui_common.QFloatLineEdit(decimals=3)
        self._output_value_percent_widget.setReadOnly(True)



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

        self._output_value_container_widget.setContentsMargins(0,0,0,0)
        self._output_value_container_layout.setContentsMargins(0,0,0,0)
        self._output_value_container_layout.addWidget(QtWidgets.QLabel("Output value:"))
        self._output_value_container_layout.addWidget(self._output_value_widget)
        self._output_value_container_layout.addWidget(QtWidgets.QLabel("Norm:"))
        self._output_value_container_layout.addWidget(self._output_value_normalized_widget)
        self._output_value_container_layout.addWidget(QtWidgets.QLabel("Percent:"))
        self._output_value_container_layout.addWidget(self._output_value_percent_widget)
        self._output_value_container_layout.addWidget(self._output_value_description_widget)
        self._output_value_container_layout.addStretch(1)
               
        self._output_trigger_description_widget = QtWidgets.QLabel()


        self._output_trigger_bool_noop_widget = QtWidgets.QRadioButton("Trigger Only")
        self._output_trigger_bool_noop_widget.clicked.connect(self._trigger_noop_changed_cb)
        self._output_trigger_bool_toggle_widget = QtWidgets.QRadioButton("Toggle")
        self._output_trigger_bool_toggle_widget.clicked.connect(self._trigger_toggle_changed_cb)
        self._output_trigger_bool_on_widget = QtWidgets.QRadioButton("On")
        self._output_trigger_bool_on_widget.clicked.connect(self._trigger_turnon_cb)
        self._output_trigger_bool_off_widget = QtWidgets.QRadioButton("Off")
        self._output_trigger_bool_off_widget.clicked.connect(self._trigger_turnoff_cb)


        self._output_trigger_bool_container_widget = QtWidgets.QWidget()
        self._output_trigger_bool_container_widget.setContentsMargins(0,0,0,0)
        self._output_trigger_bool_container_layout = QtWidgets.QHBoxLayout(self._output_trigger_bool_container_widget)
        self._output_trigger_bool_container_layout.setContentsMargins(0,0,0,0)

        self._output_trigger_bool_container_layout.addWidget(QtWidgets.QLabel("Trigger Mode:"))
        self._output_trigger_bool_container_layout.addWidget(self._output_trigger_bool_noop_widget)
        self._output_trigger_bool_container_layout.addWidget(self._output_trigger_bool_toggle_widget)
        self._output_trigger_bool_container_layout.addWidget(self._output_trigger_bool_on_widget)
        self._output_trigger_bool_container_layout.addWidget(self._output_trigger_bool_off_widget)
        self._output_trigger_bool_container_layout.addWidget(self._output_trigger_description_widget)
        self._output_trigger_bool_container_layout.addStretch()

        # status widget
        self.status_text_widget = gremlin.ui.ui_common.QIconLabel()

        
        self._command_container_layout.addWidget(self._action_selector_widget)


        # output options container - shows below selector - visible when a command is selected and changes with the active mode
        self._output_container_widget = QtWidgets.QWidget()
        self._output_container_widget.setContentsMargins(0,0,0,0)
        self._output_container_layout = QtWidgets.QVBoxLayout(self._output_container_widget)
        self._output_container_layout.setContentsMargins(0,0,0,0)

        self._output_container_layout.addWidget(self.command_header_container_widget)
        self._output_container_layout.addWidget(QHLine())
        self._output_container_layout.addWidget(self._output_mode_container_widget)
        self._output_container_layout.addWidget(self._output_range_container_widget)
        self._output_container_layout.addWidget(self._output_value_container_widget)
        self._output_container_layout.addWidget(self._output_trigger_bool_container_widget)
        self._output_container_layout.addWidget(self.status_text_widget)
        self._output_container_layout.addStretch()



        #self.main_layout.addWidget(self._toolbar_container_widget)

        warning_widget = gremlin.ui.ui_common.QIconLabel("fa.warning",use_qta=True,icon_color=QtGui.QColor("orange"),text="This function is experimental and still in development, and not necessary feature complete", use_wrap=False)
        self.main_layout.addWidget(warning_widget)

        self.main_layout.addWidget(self._command_container_widget)
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


    

        # update from ui
        self._update_block_ui()
        self._update_visible()




    def _update_curve_icon(self):
        if self.action_data.curve_data:
            self.curve_button_widget.setIcon(self.curve_icon_active)
            self.curve_clear_widget.setEnabled(True)
        else:
            self.curve_button_widget.setIcon(self.curve_icon_inactive)
            self.curve_clear_widget.setEnabled(False)


    QtCore.Slot()            
    def _reset_range(self):
        with QtCore.QSignalBlocker(self.action_data.events):
            self.action_data.min_range = -1.0
            self.action_data.max_range = 1.0
        self._update_block_ui()

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
        
        :param value: the floating point input value, if None uses the cached value
        
        '''
        # always read the current input as the value could be from another device for merged inputs
        if self.input_type == InputType.JoystickAxis:
            
            raw_value = self.action_data.get_raw_axis_value()
            if value is None:
                # filter and merge the data
                filtered_value = self.action_data.get_filtered_axis_value(raw_value)
                if self.action_data.curve_data:
                    filtered_value = self.action_data.get_local_curve_value(filtered_value)
                normalized = filtered_value
                value = filtered_value

            # if the output is ranged apply that range
            
            if self.action_data.mode == SimConnectActionMode.Ranged:
                # scale up to apply the block range
                raw = value # -1 to +1
                normalized = gremlin.util.scale_to_range(raw, target_min=self.action_data.min_range, target_max = self.action_data.max_range, invert = self.action_data.inverted) # scale to mapped range
                percent = gremlin.util.scale_to_range(normalized,target_min=0, target_max=100)
                value = int(gremlin.util.scale_to_range(normalized, source_min = -16368, source_max = 16367))
                #print (f"raw {raw:0.3f} scaled {value} normalized {normalized:0.3f} percent: {percent:0.3f}")

            if self.action_data.curve_data is not None:
                # curve the data 
                curved_value = self.action_data.curve_data.curve_value(normalized)
                self._axis_repeater_widget.show_curved = True

                self._axis_repeater_widget.setValue(normalized, curved_value, percent)
            else:
                self._axis_repeater_widget.show_curved = False
                self._axis_repeater_widget.setValue(normalized, percent_value=percent)

            # update the curved window if displayed
            if self.curve_update_handler is not None:
                self.curve_update_handler(normalized)

    def _show_options_dialog_cb(self):
        ''' displays the simconnect options dialog'''
        profile = gremlin.shared_state.current_profile
        profile_file = profile.profile_file
        if not profile_file or not os.path.isfile(profile_file):
            gremlin.ui.ui_common.MessageBox(prompt="Please save the current profile before accessing Simconnect options.")
            return 
        dialog = SimconnectOptionsUi(self._simconnect)
        dialog.exec()


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
        self._output_value_percent_widget.setValue(percent)
        


    def _min_normalized_range_changed_cb(self):
        normalized = self._output_min_normalized_range_widget.value()
        if normalized is not None:
            value = gremlin.util.scale_to_range(normalized, target_min= -16368, target_max = +16367)
            value = int(value)
            with QtCore.QSignalBlocker(self._output_min_range_widget):
                self._output_min_range_widget.setValue(value)
            self._update_min_range(normalized)

    def _min_range_changed_cb(self):
        value = self._output_min_range_widget.value()
        if value is not None:
            normalized = gremlin.util.scale_to_range(value, -16368, +16367)  # scale to -1 +1
            with QtCore.QSignalBlocker(self._output_min_normalized_range_widget):
                self._output_min_normalized_range_widget.setValue(normalized)
            self._update_min_range(normalized)

        

    def _update_min_range(self, value):
        # store to profile
        assert value >= -1.0 and value <= 1.0
        self.action_data.min_range = value

        percent = gremlin.util.scale_to_range(value, target_min = 0.0, target_max = 100.0)
        self._output_min_percent_range_widget.setValue(percent)


    def _max_normalized_range_changed_cb(self):
        normalized = self._output_max_normalized_range_widget.value()
        if normalized is not None:
            value = gremlin.util.scale_to_range(normalized, target_min= -16368, target_max = +16367)
            value = int(value)
            with QtCore.QSignalBlocker(self._output_max_range_widget):
                self._output_max_range_widget.setValue(value)
            self._update_max_range(normalized)

    def _max_range_changed_cb(self):
        value = self._output_max_range_widget.value()
        if value is not None:
            normalized = gremlin.util.scale_to_range(value, -16368, +16367) # scale to -1 +1
            with QtCore.QSignalBlocker(self._output_max_normalized_range_widget):
                self._output_max_normalized_range_widget.setValue(normalized)
            self._update_max_range(normalized)

    def _update_max_range(self, value):
        # store to profile
        assert value >= -1.0 and value <= 1.0
        self.action_data.max_range = value

        percent = gremlin.util.scale_to_range(value, target_min = 0.0, target_max = 100.0)
        self._output_max_percent_range_widget.setValue(percent)

    @QtCore.Slot(bool)
    def _output_invert_axis_cb(self, checked):
        self.action_data.inverted = checked
        self._axis_repeater_widget.setReverse(checked)
        # update the repeater
  
    @QtCore.Slot(bool)
    def _trigger_on_release_cb(self, checked):
        self.action_data.trigger_on_release = checked

    

    def _command_changed_cb(self, index):
        ''' called when selected command changes '''
        command = self._command_selector_widget.currentText()
        self.action_data.command = command
        self._update_block_ui()
        

    def _update_block_ui(self):
        ''' updates the UI with a data block '''

        self._update_visible()


        

        with QtCore.QSignalBlocker(self._trigger_on_release_widget):
            self._trigger_on_release_widget.setChecked(self.action_data.trigger_on_release)


        enabled = self.action_data.block is not None
        self._action_selector_widget.setEnabled(enabled)
        self._output_mode_container_widget.setEnabled(enabled)
        
        output_mode = self.action_data.mode
        min_range = self.action_data.min_range
        max_range = self.action_data.max_range
        value = self.action_data.value
        inverted = self.action_data.inverted
        trigger_mode = self.action_data.trigger_mode
        block = self.action_data.block
    


        if enabled:

 

            match output_mode:

                case SimConnectActionMode.Ranged:
                    with QtCore.QSignalBlocker(self._output_mode_ranged_widget):
                        self._output_mode_ranged_widget.setChecked(True)
                    self._output_min_normalized_range_widget.setValue(min_range)
                    self._output_max_normalized_range_widget.setValue(max_range)

                    with QtCore.QSignalBlocker(self._output_invert_axis_widget):
                        self._output_invert_axis_widget.setChecked(inverted)
                case SimConnectActionMode.SetValue:
                    with QtCore.QSignalBlocker(self._output_mode_set_value_widget):
                        self._output_mode_set_value_widget.setChecked(True)
                    self._output_value_normalized_widget.setValue(value)
                    
                case SimConnectActionMode.Trigger:
                    with QtCore.QSignalBlocker(self._output_mode_trigger_widget):
                        self._output_mode_trigger_widget.setChecked(True)

                    self.action_data.block.trigger_mode = trigger_mode
                    
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


        
        if enabled:
            self._output_container_widget.setVisible(True)
            self._output_mode_readonly_widget.setVisible(block.is_readonly)
            self.output_readonly_status_widget.setText("Block: read/only" if block.is_readonly else "Block: read/write")

            # display range information if the command is a ranged command
            self._output_range_container_widget.setVisible(block.is_ranged)

            # hook block events
            eh = SimConnectEventHandler()
            eh.range_changed.connect(self._range_changed_cb)

            # command description
            self.command_text_widget.setText(block.command)
            self.description_text_widget.setText(block.description)

            # update UI based on block information ``
            self._output_data_type_label_widget.setText(block.display_block_type)
         
            self._update_visible()

            return
        
        # clear the data
        self._output_container_widget.setVisible(False)
        self.status_text_widget.setText("Please select a command")

        

        


    def _update_visible(self):
        ''' updates the UI based on the output mode selected '''

        input_type = self.action_data.input_type
        block : SimConnectBlock = self.action_data.block
        repeater_visible = False
        output_mode = self.action_data.mode
        setvalue_visible = output_mode == SimConnectActionMode.SetValue
        trigger_visible = output_mode == SimConnectActionMode.Trigger
        if input_type == InputType.JoystickAxis:
            range_visible = output_mode == SimConnectActionMode.Ranged and not setvalue_visible
            
            # gated_visible = block.output_mode == SimConnectActionMode.Gated
            repeater_visible = True
            
        else:
            # momentary
            range_visible = False
            #gated_visible = False
        
        self._output_range_container_widget.setVisible(range_visible)
        self._output_trigger_bool_container_widget.setVisible(trigger_visible)
        self._output_value_container_widget.setVisible(setvalue_visible)

        self.container_repeater_widget.setVisible(repeater_visible)

        output_mode_enabled = not block.is_readonly
        trigger_bool_visible = False
        invert_visible = False
        if input_type == InputType.JoystickAxis:
            invert_visible = True
            with QtCore.QSignalBlocker(self._output_invert_axis_widget):
                self._output_invert_axis_widget.setChecked(self.action_data.block.invert_axis)


        self._output_invert_axis_widget.setVisible(invert_visible)
        self._output_mode_container_widget.setVisible(output_mode_enabled)
        self._output_mode_set_value_widget.setEnabled(output_mode_enabled)
        self._output_mode_trigger_widget.setEnabled(output_mode_enabled)
        self._output_data_type_label_widget.setText(block.display_data_type)
        self.output_readonly_status_widget.setText("(command is Read/Only)" if block.is_readonly else '')

        # update the output data type
        if block.output_data_type == OutputType.FloatNumber:
            self._output_data_type_label_widget.setText("Number (float)")
        elif block.output_data_type == OutputType.IntNumber:
            self._output_data_type_label_widget.setText("Number (int)")
        else:
            self._output_data_type_label_widget.setText("N/A")





    @QtCore.Slot(bool)
    def _trigger_noop_changed_cb(self, checked):
        if checked:
            self.action_data.block.trigger_mode = SimConnectTriggerMode.NoOp

    @QtCore.Slot(bool)
    def _trigger_toggle_changed_cb(self, checked):
        if checked:
            self.action_data.block.trigger_mode = SimConnectTriggerMode.Toggle

    @QtCore.Slot(bool)
    def _trigger_turnon_cb(self, checked):
        if checked:
            self.action_data.block.trigger_mode = SimConnectTriggerMode.TurnOn

    @QtCore.Slot(bool)
    def _trigger_turnoff_cb(self, checked):
        if checked:
            self.action_data.block.trigger_mode = SimConnectTriggerMode.TurnOff


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
            self.action_data.block.output_mode = SimConnectActionMode.Ranged
            self.action_data.mode = SimConnectActionMode.Ranged
            self._update_visible()

    @QtCore.Slot(bool)
    def _mode_value_cb(self, value):
        if value:
            self.action_data.block.output_mode = SimConnectActionMode.SetValue
            self.action_data.mode = SimConnectActionMode.SetValue
            self._update_visible()
        
    @QtCore.Slot(bool)
    def _mode_trigger_cb(self, value):
        if value:
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

    manager = gremlin.macro.MacroManager()

    def __init__(self, action, parent = None):
        super().__init__(action, parent)
        self.action_data : MapToSimConnect = action
        self.command = action.command # the command to execute
        self.value = action.value # the value to send (None if no data to send)
        eh = SimConnectEventHandler()
        self.manager : SimConnectManager = eh.manager
        self.valid = False

    
    def profile_start(self):
        ''' occurs when the profile starts '''


        eh = SimConnectEventHandler()
        eh.request_connect.emit()
        self.reconnect_timeout = 5
        self.last_reconnect_time = None
        
        # self.action_data.gate_data.process_callback = self.process_gated_event
        if self.action_data.block is None or not self.action_data.block.command_type != SimConnectCommandType.NotSet:
            syslog.error(f"Simconnect: invalid block: {self.command}")
            self.valid = False
            return
        
        self.valid = True


        



    def profile_stop(self):
        ''' occurs wen the profile stops'''

        eh = SimConnectEventHandler()
        eh.request_disconnect.emit()
        
        

    def scale_output(self, value):
        ''' scales an output value for the output range -1 to 1 to action range  '''
        return gremlin.util.scale_to_range(value, target_min = self.action_data.min_range, target_max = self.action_data.max_range, invert=self.action_data.inverted)
    
    def process_event(self, event, action_value : gremlin.actions.Value):
        ''' runs when a joystick event occurs like a button press or axis movement when a profile is running '''

        if not self.valid:
            return

        if not self.manager.is_running:
            # sim is not running - attempt to reconnect every few seconds
            if self.last_reconnect_time is None or self.last_reconnect_time + self.reconnect_timeout > time.time():
                self.last_reconnect_time = time.time()
                eh = SimConnectEventHandler()
                eh.request_connect.emit()
            return True

        return self._process_event(event, action_value)                    

    def _process_event(self, event, action_value : gremlin.actions.Value):
        ''' handles default input data '''

        # execute the nested functors for this action
        super().process_event(event, action_value)

        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        #verbose = True

        if not self.manager.is_running:
            # sim is not running
            return
        
        block = self.action_data.block
        output_mode = self.action_data.mode

        if not block or not block.valid:
            # invalid command
            return True        
        if event.is_axis and output_mode in (SimConnectActionMode.Ranged, SimConnectActionMode.Gated):
            # value = self.action_data.get_filtered_axis_value(action_value.current)
            # process input options and any merge and curve operation
            filtered_value = self.action_data.get_filtered_axis_value(action_value.current)
            action_value = gremlin.actions.Value(filtered_value)


            raw = filtered_value # -1 to +1
            ranged = gremlin.util.scale_to_range(raw, target_min=self.action_data.min_range, target_max = self.action_data.max_range, invert= self.action_data.inverted) # scale to mapped range

            # apply local curve to the range
            curved = self.action_data.get_local_curve_value(ranged)


            scaled = int(gremlin.util.scale_to_range(curved, target_min= -16368, target_max = 16367)) # scale up to full range

            
            #block_value = gremlin.util.scale_to_range(filtered_value, target_min = block.min_range, target_max = block.max_range, invert= block.invert_axis)
            if verbose: 
                percent = gremlin.util.scale_to_range(ranged, target_min=0, target_max = 100)
                syslog.info(f"Send block axis: {block.command} range min {self.action_data.min_range:0.3f} max: {self.action_data.max_range:0.3f} raw: {action_value.current:0.3f} ranged: {ranged:0.3f} local curve: {curved:0.3f} inverted: {self.action_data.inverted} mode: {gremlin.shared_state.runtime_mode} msfs: {scaled} % {percent:0.3f}")
            block.execute(scaled)
        elif output_mode == SimConnectActionMode.Trigger:
            if not event.is_axis and action_value.is_pressed:
                block.execute(action_value.current)
        elif output_mode == SimConnectActionMode.SetValue:
            # set value mode 
            value = self.action_data.value
            scaled = int(gremlin.util.scale_to_range(value, target_min= -16368, target_max = 16367))

            if self.action_data.trigger_on_release and not event.is_pressed:
                if verbose:
                    percent = gremlin.util.scale_to_range(value, target_min=0, target_max = 100)
                    syslog.info(f"Send block set value axis (release trigger): {block.command}  raw: {value:0.3f} mode: {gremlin.shared_state.runtime_mode} scaled: {scaled} percent: {percent:0.3f}")
                block.execute(scaled)
            elif not self.action_data.trigger_on_release and event.is_pressed:
                if verbose:
                    percent = gremlin.util.scale_to_range(value, target_min=0, target_max = 100)
                    syslog.info(f"Send block set value axis (press trigger): {block.command}  raw: {value:0.3f} mode: {gremlin.shared_state.runtime_mode} scaled: {scaled} percent: {percent:0.3f}")
                block.execute(scaled)
        elif self.action_data.mode == SimConnectActionMode.Trigger:
            # trigger action 
            block.execute(action_value.value)
        return True
    

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

        super().__init__(parent)
        self.parent = parent
        self.events = MapToSimConnectHelper()

        eh = SimConnectEventHandler()
        self.smd  = eh.manager


        self.input_type = self.get_input_type()

        # the current command category if the command is an event
        self.category = SimConnectEventCategory.NotSet

        # the current command name
        self._command = None

        # the value to output if any
        self.value = 0.0
        self._min_range = -1.0 # min range for ranged output
        self._max_range = 1.0 # max range for ranged output 
        self.inverted = False # inversion flag
        self.trigger_mode = SimConnectTriggerMode.NoOp # trigger only

        self.trigger_on_release = False # true if this is triggered on release when the action is tied to a button or hat intput
        
        #gate_data = GateData(profile_mode = gremlin.shared_state.current_mode, action_data=self)
        # self.gates = [gate_data] # list of GateData objects
        # self.gate_data = gate_data

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
        return gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)        


    def display_name(self):
        ''' returns a string for this action for display purposes '''
        return self.block.display_name
      

    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        return "mdi.airplane"
    
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
    
    def update_block(self):
        ''' updates the data block with the current command '''
        if self._command is None:
            self._command = self._default_command()
        self._block = self.smd.block(self._command)

   
    
    @property
    def block(self):
        ''' returns the current data block '''
        if self._block is None:
            # create it for the current command
            self.update_block()

        return self._block

    @property
    def min_range(self) -> float:
        return self._min_range
    @min_range.setter
    def min_range(self, value : float):
        emit = False
        v_min = value
        v_max = self._max_range
        if v_min > v_max:
            v_min, v_max = v_max, v_min
            self._max_range = v_max
            emit = True
        self._min_range = v_min
        if emit:
            self.events.range_changed.emit()

    @property
    def max_range(self) -> float:
        return self._max_range
    @max_range.setter
    def max_range(self, value : float):
        emit = False
        v_max = value
        v_min = self._min_range
        if v_min > v_max:
            v_min, v_max = v_max, v_min
            self._min_range = v_min
            emit = True
        self._max_range = v_max
        if emit:
            self.events.range_changed.emit()

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        return False

    def _parse_xml(self, node):
        """Reads the contents of an XML node to populate this instance.

        :param node the node whose content should be used to populate this
            instance
        """

        default_command = self._default_command()
        self._command = safe_read(node,"command",str, default_command)
        self._block = SimConnectManager().block(self._command)
        self.value = safe_read(node,"value", float, 0.0) # normalized
        self.min_range = safe_read(node,"min_range", float, -1.0) # normalized
        self.max_range = safe_read(node,"max_range", float, 1.0) # normalized
        s_mode = safe_read(node, "mode", str, "")
        if s_mode:
            self.mode = SimConnectActionMode.to_enum(s_mode)
        self.inverted = safe_read(node,"inverted",bool, False)
        s_trigger = safe_read(node,"trigger",str,"")
        if s_trigger:
            self.trigger_mode = SimConnectTriggerMode.to_enum(s_trigger)
        
        self.trigger_on_release = safe_read(node,"trigger_on_release", bool, False)

        node_block =gremlin.util.get_xml_child(node,"block")
        if node_block is not None:
            assert self._block is not None,"Block should not be null"
            self._block.from_xml(node_block)
            self._block.update()

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

        node_block = self.block.to_xml()
        node.append(node_block)

        # simconnect command
        command = self.command if self.command else ""
        node.set("command",safe_format(command, str))
        node.set("value", safe_format(self.value, float)) # normalized
        node.set("mode", SimConnectActionMode.to_string(self.mode))
        node.set("trigger_on_release", safe_format(self.trigger_on_release, bool))
        node.set("min_range", safe_format(self.min_range, float)) # normalized
        node.set("max_range", safe_format(self.max_range, float)) # normalized
        node.set("inverted", safe_format(self.inverted, bool))
        node.set("trigger", SimConnectTriggerMode.to_string(self.trigger_mode))

        if self.curve_data is not None:
            curve_node =  self.curve_data._generate_xml()
            curve_node.tag = "response-curve-ex"
            node.append(curve_node)                


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
        self.smd = eh.manager

version = 1
name = "map-to-simconnect"
create = MapToSimConnect


# listening monitor for profile and aicraft mode changes
monitor = SimconnectMonitor()