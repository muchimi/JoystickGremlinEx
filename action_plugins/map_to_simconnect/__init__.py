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
import gremlin.gated_handler
import enum
from gremlin.profile import safe_format, safe_read
import gremlin.util
from .SimConnectData import *
import re
from lxml import etree
from lxml import etree as ElementTree
from gremlin.gated_handler import *
from gremlin.ui.qdatawidget import QDataWidget
import gremlin.config


class QHLine(QtWidgets.QFrame):
    def __init__(self, parent = None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)


class CommandValidator(QtGui.QValidator):
    ''' validator for command selection '''
    def __init__(self):
        super().__init__()
        self.commands = SimConnectData().get_command_name_list()
        
        
    def validate(self, value, pos):
        clean_value = value.upper().strip()
        if not clean_value or clean_value in self.commands:
            # blank is ok
            return QtGui.QValidator.State.Acceptable
        # match all values starting with the text given
        r = re.compile(clean_value + "*")
        for _ in filter(r.match, self.commands):
            return QtGui.QValidator.State.Intermediate
        return QtGui.QValidator.State.Invalid
    
class SimconnectAicraftDefinition():
    ''' holds the data entry for a single aicraft from the MSFS config data '''
    def __init__(self, id = None, mode = None, icao_type = None, icao_manufacturer = None, icao_model = None, titles = [], path = None):
        self.icao_type = icao_type
        self.icao_manufacturer = icao_manufacturer
        self.icao_model = icao_model
        self.titles = titles
        self.path = path
        self.mode = mode
        self.key = self.display_name.lower()
        self.id = id if id else gremlin.util.get_guid()
        
        # runtime item (not saved or loaded)
        self.selected = False # for UI interation - selected mode
        self.error_status = None

    @property
    def display_name(self):
        return f"{self.icao_manufacturer} {self.icao_model}"

    @property
    def valid(self):
        ''' true if the item contains valid data '''
        return not self.error_status and self.aircraft and self.mode
    
    # def __eq__(self, other):
    #     ''' compares two objects '''
    #     return gremlin.util.compare_nocase(self.icao_type, other.icao_type) and \
    #         gremlin.util.compare_nocase(self.icao_manufacturer, other.icao_manufacturer) and \
    #         gremlin.util.compare_nocase(self.icao_manufacturer, other.icao_manufacturer) and \
    #         gremlin.util.compare_nocase(self.icao_model, other.icao_model)
    
    # def __hash__(self):
    #     return (self.icao_type.lower(), self.icao_manufacturer.lower(), self.icao_model.lower()).__hash__()
   
    
class SimconnectSortMode(Enum):
    NotSet = auto()
    AicraftAscending = auto()
    AircraftDescending = auto()
    Mode = auto()

@gremlin.singleton_decorator.SingletonDecorator
class SimconnectOptions(QtCore.QObject):


    ''' holds simconnect mapper options for all actions '''
    def __init__(self):
        super().__init__()
        self._profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        self._mode_list = self._profile.get_modes()
        self._xml_source = os.path.join(gremlin.util.userprofile_path(),"simconnect_config.xml")
        self._auto_mode_select = True # if set, autoloads the mode associated with the aircraft if such a mode exists
        self._aircraft_definitions = [] # holds aicraft entries
        self._titles = []
        self._community_folder = r"C:\Microsoft Flight Simulator\Community"
        self._sort_mode = SimconnectSortMode.NotSet
        self.parse_xml()


    @property
    def current_aircraft_folder(self):
        if self._sm.ok:
            return self._aircraft_folder
        return None
    
    @property
    def current_aircraft_title(self):
        if self._sm.ok:
            return self._aircraft_title
        return None
    
    @property
    def community_folder(self):
        return self._community_folder
    @community_folder.setter
    def community_folder(self, value):
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
                    mode = safe_read(node,"mode", str, "")
                    id = safe_read(node,"id", str, "")
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
                                                           mode = mode)
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


    def scan_aircraft_config(self, owner):
        ''' scans MSFS folders for the list of aircraft names '''
        
        def fix_entry(value):
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


        options = SimconnectOptions()

        from gremlin.ui import ui_common
        if not self._community_folder or not os.path.isdir(self._community_folder):
            self._community_folder = self.get_community_folder()
        if not self._community_folder or not os.path.isdir(self._community_folder):
            return
        #gremlin.util.pushCursor()

        progress = QtWidgets.QProgressDialog(parent = owner, labelText ="Scanning folders...", cancelButtonText = "Cancel", minimum = 0, maximum= 100) #, flags = QtCore.Qt.FramelessWindowHint)
        progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress.setValue(0)
        progress.show()
        QtWidgets.QApplication.processEvents()

        search_folder = os.path.dirname(self._community_folder)
        source_files = gremlin.util.find_files(search_folder,"aircraft.cfg")

        
        cmp_icao_type =  r'(?i)icao_type_designator\s*=\s*\"?(.*?)\"?$'
        cmp_icao_manuf =  r'(?i)icao_manufacturer\s*=\s*\"?(.*?)\"?$'
        cmp_icao_model =  r'(?i)icao_model\s*=\s*\"?(.*?)\"?$'
        cmp_title = r"(?i)title\s*=\s*\"?(.*?)\"?$"
        file_count = len(source_files)

        progress.setLabelText = f"Processing {file_count:,} aircraft..."
        is_canceled = False
        items = []
        keys = []
        for count, file in enumerate(source_files):

            progress.setValue(int(100 * count / file_count))
            if progress.wasCanceled():
                is_canceled  = True
                break
            
            base_dir = os.path.dirname(file)
            cockpit_file = os.path.join(base_dir, "cockpit.cfg")
            if not os.path.isfile(cockpit_file):
                # not a player flyable airplane, skip
                continue

            titles = []
            icao_type = None
            icao_model = None
            icao_manuf = None

            with open(file,"r",encoding="utf8") as f:
                for line in f.readlines():
                    matches = re.findall(cmp_icao_type, line)
                    if matches:
                        icao_type = fix_entry(matches.pop())
                        continue
                    matches = re.findall(cmp_icao_manuf, line)
                    if matches:
                        icao_manuf = fix_entry(matches.pop())
                        continue
                    matches = re.findall(cmp_icao_model, line)
                    if matches:
                        icao_model = fix_entry(matches.pop())
                        continue

                    matches = re.findall(cmp_title, line)
                    if matches:
                        titles.extend(matches)
                        

            
            if titles:
                titles = list(set(titles))
                titles = [fix_entry(t) for t in titles]
                titles.sort()
            if icao_model and icao_type and icao_manuf:
                path = os.path.dirname(file)
                item = SimconnectAicraftDefinition(icao_type=icao_type,
                                                   icao_manufacturer= icao_manuf,
                                                   icao_model= icao_model,
                                                   titles= titles,
                                                   path = path)
                if not item.display_name in keys:
                    # avoid duplicate entries
                    items.append(item)
                    keys.append(item.display_name)

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





class SimconnectOptionsUi(QtWidgets.QDialog):
    """UI to set individual simconnect  settings """

    def __init__(self, parent=None):
        from gremlin.ui import ui_common
        super().__init__(parent)

        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        # min_min_sp = QtWidgets.QSizePolicy(
        #     QtWidgets.QSizePolicy.Minimum,
        #     QtWidgets.QSizePolicy.Minimum
        # )
        # exp_min_sp = QtWidgets.QSizePolicy(
        #     QtWidgets.QSizePolicy.MinimumExpanding,
        #     QtWidgets.QSizePolicy.Minimum
        # )

        # Actual configuration object being managed
        self.config = gremlin.config.Configuration()
        self.setMinimumWidth(600)


        self.mode_list = []
        self.profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        self.mode_list = self.profile.get_modes()
        self.default_mode = self.profile.get_default_mode()

        # display name to mode pair list
        self.mode_pair_list = gremlin.ui.ui_common.get_mode_list(self.profile)

        self.options = SimconnectOptions()

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

        
        self.container_bar_layout.addWidget(self.edit_mode_widget)
        self.container_bar_layout.addWidget(self.scan_aircraft_widget)
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
        self.scroll_area.setMinimumWidth(300)
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





    @QtCore.Slot()
    def close_button_cb(self):
        ''' called when close button clicked '''
        self.close()

    

    def _populate_ui(self):
        ''' populates the map of aircraft to profile modes '''

        from gremlin.ui import ui_common
        self.options.validate()


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

       

            # mode drop down
            mode_selector = ui_common.QDataComboBox(data = (item, selected_widget))
            for display_mode, mode in self.mode_pair_list:
                mode_selector.addItem(display_mode, mode)
            if not item.mode:
                item.mode = self.default_mode
            if not item.mode in self.mode_list:
                item.mode = self.default_mode
            index = mode_selector.findData(item.mode)
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
        widget = self.sender()
        mode = widget.currentData()
        item, _ = widget.data
        items = self._get_selected()
        if not item in items:
            items.append(item)
        mode_index = None
        for item in items:
            if item.mode != mode:
                item.mode = mode
                selector = self._mode_selector_map[item]
                with QtCore.QSignalBlocker(selector):
                    if mode_index is None:
                        mode_index = selector.findData(mode)
                    selector.setCurrentIndex(mode_index)

    @QtCore.Slot()
    def _active_button_cb(self):
        widget = self.sender()
        sm = SimConnectData()
        
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
        
        self.action_data : MapToSimConnect = action_data
        self.options = SimconnectOptions()

        # call super last because it will call create_ui and populate_ui so the vars must exist
        super().__init__(action_data, parent=parent)

    

    def _create_ui(self):
        """Creates the UI components."""
        import gremlin.gated_handler

        verbose = gremlin.config.Configuration().verbose
        if verbose:
            log_info(f"Simconnect UI for: {self.action_data.hardware_input_type_name}  {self.action_data.hardware_device_name} input: {self.action_data.hardware_input_id}")


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
        self._command_selector_widget = QtWidgets.QComboBox()
        self._command_list = self.action_data.sm.get_command_name_list()
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

        self._output_mode_gated_widget =  QtWidgets.QRadioButton("Gated")
        self._output_mode_gated_widget.clicked.connect(self._mode_gated_cb)
        self._output_mode_gated_widget.setToolTip("Set the output as an axis to with or without gates.<br>The gate maps determine what axes and triggers occur based on the input axis value.")

        self._output_mode_sync_widget = QtWidgets.QPushButton("Sync")
        self._output_mode_sync_widget.clicked.connect(self._mode_sync_cb)
        self._output_mode_sync_widget.setToolTip("Synchronizes the command with the gate range")


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
        self._output_mode_container_layout.addWidget(self._output_mode_gated_widget)
        self._output_mode_container_layout.addWidget(self._output_mode_sync_widget)
        self._output_mode_container_layout.addStretch()

        self.output_readonly_status_widget = QtWidgets.QLabel("Read only")
        self._output_mode_container_layout.addWidget(self.output_readonly_status_widget)

        self._output_invert_axis_widget = QtWidgets.QCheckBox("Invert axis")
        self._output_invert_axis_widget.clicked.connect(self._output_invert_axis_cb)




        # output data type UI
        self._output_data_type_widget = QtWidgets.QWidget()
        self._output_data_type_widget.setContentsMargins(0,0,0,0)
        self._output_data_type_layout = QtWidgets.QHBoxLayout(self._output_data_type_widget)
        self._output_data_type_layout.setContentsMargins(0,0,0,0)
        
        self._output_data_type_label_widget = QtWidgets.QLabel("Not Set")

        
        self._output_data_type_layout.addWidget(QtWidgets.QLabel("<b>Output type:</b>"))
        self._output_data_type_layout.addWidget(self._output_data_type_label_widget)
        self._output_data_type_layout.addWidget(self._output_mode_description_widget)
        self._output_data_type_layout.addStretch()
        


        # output range UI
        self._output_range_container_widget = QtWidgets.QWidget()
        self._output_range_container_widget.setContentsMargins(0,0,0,0)
        self._output_range_container_layout = QtWidgets.QVBoxLayout(self._output_range_container_widget)
        self._output_range_container_layout.setContentsMargins(0,0,0,0)
        
        

        self._output_range_ref_text_widget = QtWidgets.QLabel()
        self._output_range_container_layout.addWidget(self._output_range_ref_text_widget)

        output_row_widget = QtWidgets.QWidget()
        output_row_layout = QtWidgets.QHBoxLayout(output_row_widget)
                
        self._output_min_range_widget = QtWidgets.QSpinBox()
        self._output_min_range_widget.setRange(-16383,16383)

        self._output_min_range_widget.valueChanged.connect(self._min_range_changed_cb)

        self._output_max_range_widget = QtWidgets.QSpinBox()
        self._output_max_range_widget.setRange(-16383,16383)
        self._output_max_range_widget.valueChanged.connect(self._max_range_changed_cb)

        
        self._output_axis_widget = ui_common.AxisStateWidget(show_percentage=False,orientation=QtCore.Qt.Orientation.Horizontal)
        if self.action_data.input_type == InputType.JoystickAxis:
            self._output_axis_widget.hookDevice(self.action_data.hardware_device_guid, self.action_data.hardware_input_id)


        output_row_layout.addWidget(self._output_invert_axis_widget)
        output_row_layout.addWidget(QtWidgets.QLabel("Range min:"))
        output_row_layout.addWidget(self._output_min_range_widget)
        output_row_layout.addWidget(QtWidgets.QLabel("Range max:"))
        output_row_layout.addWidget(self._output_max_range_widget)
        output_row_layout.addWidget(self._output_axis_widget)
        output_row_layout.addStretch(1)
        

        self._output_range_container_layout.addWidget(output_row_widget)

        # holds the output value if the output value is a fixed value
        self._output_value_container_widget = QtWidgets.QWidget()
        self._output_value_container_layout = QtWidgets.QHBoxLayout(self._output_value_container_widget)
        self._output_value_container_widget.setContentsMargins(0,0,0,0)
        self._output_value_widget = ui_common.QDataLineEdit()
        self._output_value_widget.textChanged.connect(self._output_value_changed_cb)
        self._output_value_description_widget = QtWidgets.QLabel()

        # holds the gated axis container
        self._output_gated_container_widget = QtWidgets.QWidget()
        self._output_gated_container_layout = QtWidgets.QVBoxLayout(self._output_gated_container_widget)
        self._output_gated_container_widget.setContentsMargins(0,0,0,0)
        
        self.command_header_container_widget = QtWidgets.QWidget()
        self.command_header_container_layout = QtWidgets.QHBoxLayout(self.command_header_container_widget)
        

        self.command_text_widget = QtWidgets.QLabel()
        self.command_header_container_layout.addWidget(QtWidgets.QLabel("<b>Command:</b>"))
        self.command_header_container_layout.addWidget(self.command_text_widget)


        self.description_text_widget = QtWidgets.QLabel()
        self.command_header_container_layout.addWidget(QtWidgets.QLabel("<b>Description</b>"))
        self.command_header_container_layout.addWidget(self.description_text_widget)
        self.command_header_container_layout.setContentsMargins(0,0,0,0)


        self.command_header_container_layout.addWidget(self._output_data_type_widget)

        self.command_header_container_layout.addStretch(1)

        self._output_value_container_widget.setContentsMargins(0,0,0,0)
        self._output_value_container_layout.setContentsMargins(0,0,0,0)
        self._output_value_container_layout.addWidget(QtWidgets.QLabel("Output value:"))
        self._output_value_container_layout.addWidget(self._output_value_widget)
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

        # show the gated axis widget only if the input is an axis
        self._gates_container_widget = None
        input_type = self.action_data.input_type
        if input_type == InputType.JoystickAxis:
            self._gates_container_widget = QtWidgets.QFrame()
            self._gates_container_widget.setFrameShape(QtWidgets.QFrame.Shape.Box)
            self._gates_container_widget.setStyleSheet('.QFrame{background-color: lightgray;}')
            self._gates_container_layout = QtWidgets.QVBoxLayout(self._gates_container_widget)
            self._gated_axis_widget = None # added later if needed
            
            

            self._output_gated_container_layout.addWidget(self._gates_container_widget)
        else:
            self._gates_container_widget = None
            self._gated_axis_widget = None
    

        # status widget
        self.status_text_widget = ui_common.QIconLabel()

        
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
        self._output_container_layout.addWidget(self._output_gated_container_widget)
        self._output_container_layout.addWidget(self._output_trigger_bool_container_widget)
        self._output_container_layout.addWidget(self.status_text_widget)
        self._output_container_layout.addStretch()


        #self.main_layout.addWidget(self._toolbar_container_widget)
        self.main_layout.addWidget(self._command_container_widget)
        self.main_layout.addWidget(self._output_container_widget)

        # update from ui
        self._ensure_gated()
        self._update_block_ui()
        self._update_axis_range()
        self._update_ui_container_visibility()

    def _ensure_gated(self):
        ''' adds a gated axis widget if the mode requires it - this is to only setup a gated axis if needed '''
        input_type = self.action_data.input_type
        
        if input_type == InputType.JoystickAxis and self._gated_axis_widget is None and self.action_data.block.output_mode == SimConnectActionMode.Gated:
            if gremlin.config.Configuration().verbose:
                 log_info(f"Adding gated input for: {self.action_data.hardware_input_type_name}  {self.action_data.hardware_device_name} input: {self.action_data.hardware_input_id}")
            self._gated_axis_widget = gremlin.gated_handler.GatedAxisWidget(action_data = self.action_data,
                                                                show_output_mode=True
                                                                )
            self._gates_container_layout.addWidget(self._gated_axis_widget)



    def _show_options_dialog_cb(self):
        ''' displays the simconnect options dialog'''
        dialog = SimconnectOptionsUi()
        dialog.exec()

    def _update_validator(self):
        block  : SimConnectBlock = self.action_data.block
        if block.output_mode == SimConnectActionMode.SetValue:
            if block.output_data_type == OutputType.IntNumber:
                self._output_value_widget.setValidator(QtGui.QIntValidator())
            elif block.output_data_type == OutputType.FloatNumber:
                self._output_value_widget.setValidator(QtGui.QDoubleValidator())
            


    def _output_value_changed_cb(self):
        ''' occurs when the output value has changed '''
        block: SimConnectBlock
        block = self.action_data.block
        if self._output_value_widget.hasAcceptableInput():
            if block.output_data_type == OutputType.IntNumber:
                value = int(self._output_value_widget.text())
            elif block.output_data_type == OutputType.FloatNumber:
                value = float(self._output_value_widget.text())
            block.disable_notifications()
            block.value = value
            block.enable_notifications()
            # store to profile
            self.action_data.value = value
            self.status_text_widget.setText("")
            self.status_text_widget.setIcon("")
        else:
            if block.output_data_type == OutputType.IntNumber:
                self.status_text_widget.setText("Expecting an integer value")
                self.status_text_widget.setIcon("fa.warning",True, color="red")
            elif block.output_data_type == OutputType.FloatNumber:
                self.status_text_widget.setText("Expecting a floating point value")
                self.status_text_widget.setIcon("fa.warning",True, color="red")

            
    @QtCore.Slot()
    def _mode_sync_cb(self):
        ''' sync mode clicked '''
        if self.action_data.block.output_mode == SimConnectActionMode.Gated:
            if self.action_data.block.min_range != self.action_data.block.command_min_range or \
                self.action_data.block.max_range != self.action_data.block.command_max_range:
                # change detected - restore the original range
                self.action_data.block.min_range = self.action_data.block.command_min_range
                self.action_data.block.max_range = self.action_data.block.command_max_range
                self._update_axis_range()
                self._update_block_ui()
                        

    def _update_axis_range(self):
        ''' updates the output range for the axis repeater'''
        if self.action_data.block.output_mode == SimConnectActionMode.Gated:
            # update decimals based on range
            min_range = self.action_data.block.min_range
            max_range = self.action_data.block.max_range
            #range = max_range - min_range

            # self._output_axis_widget.setRange(min_range, max_range)
            self._gated_axis_widget.setDisplayRange(min_range, max_range)


    def _min_range_changed_cb(self):
        value = self._output_min_range_widget.value()
        block: SimConnectBlock
        block = self.block
        if block:
            block.disable_notifications()
            block.min_range_custom = value
            block.enable_notifications()
            # store to profile
            self.action_data.min_range = value
            self._output_axis_widget.setMinimum(value)

    def _max_range_changed_cb(self):
        value = self._output_max_range_widget.value()
        block: SimConnectBlock
        block = self.block
        if block:
            block.disable_notifications()
            block.max_range_custom = value
            block.enable_notifications()
            # store to profile
            self.action_data.max_range = value
            self._output_axis_widget.setMaximum(value)

    @QtCore.Slot(bool)
    def _output_invert_axis_cb(self, checked):
        self.action_data.block.invert = checked
        self._output_axis_widget.setReverse(checked)
        # update the repeater
  

    

    def _command_changed_cb(self, index):
        ''' called when selected command changes '''
        command = self._command_selector_widget.currentText()
        self.action_data.command = command
        self._update_block_ui()
        

    def _update_block_ui(self):
        ''' updates the UI with a data block '''

        self._update_ui_container_visibility()

        block : SimConnectBlock = self.action_data.block
        

        enabled = block is not None
        self._action_selector_widget.setEnabled(enabled)
        self._output_mode_container_widget.setEnabled(enabled)

       


        if enabled:

            self._update_validator()

            input_type = self.action_data.input_type
            if block.output_mode == SimConnectActionMode.NotSet:
                if input_type == InputType.JoystickAxis:
                    block.output_mode = SimConnectActionMode.Ranged
                else:
                    block.output_mode = SimConnectActionMode.Trigger

                
            if block.output_mode == SimConnectActionMode.Gated:
                with QtCore.QSignalBlocker(self._output_mode_gated_widget):
                    self._output_mode_gated_widget.setChecked(True)
            elif block.output_mode == SimConnectActionMode.Ranged:
                with QtCore.QSignalBlocker(self._output_mode_ranged_widget):
                    self._output_mode_ranged_widget.setChecked(True)
            elif block.output_mode == SimConnectActionMode.SetValue:
                with QtCore.QSignalBlocker(self._output_mode_set_value_widget):
                    self._output_mode_set_value_widget.setChecked(True)
            elif block.output_mode == SimConnectActionMode.Trigger:
                with QtCore.QSignalBlocker(self._output_mode_trigger_widget):
                    self._output_mode_trigger_widget.setChecked(True)
            

            # sync output mode
            if self._output_max_range_widget.value() != block.max_range:
                with QtCore.QSignalBlocker(self._output_max_range_widget):
                    self._output_max_range_widget.setValue(block.max_range)
            if self._output_min_range_widget.value() != block.min_range:
                with QtCore.QSignalBlocker(self._output_min_range_widget):
                    self._output_min_range_widget.setValue(block.min_range)
                    
            s_value = str(block.value)
            if self._output_value_widget.text() != s_value:
                with QtCore.QSignalBlocker(self._output_value_widget):
                    self._output_value_widget.setText(s_value)

            # sync trigger mode data
            if block.trigger_mode == SimConnectTriggerMode.NotSet:
                with QtCore.QSignalBlocker(self._output_trigger_bool_toggle_widget):
                    self._output_trigger_bool_toggle_widget.setChecked(True)
                    block.trigger_mode = SimConnectTriggerMode.Toggle
            elif block.trigger_mode == SimConnectTriggerMode.Toggle:
                with QtCore.QSignalBlocker(self._output_trigger_bool_toggle_widget):
                    self._output_trigger_bool_toggle_widget.setChecked(True)
            elif block.trigger_mode == SimConnectTriggerMode.TurnOff:
                with QtCore.QSignalBlocker(self._output_trigger_bool_off_widget):
                    self._output_trigger_bool_off_widget.setChecked(True)
            elif block.trigger_mode == SimConnectTriggerMode.TurnOn:
                with QtCore.QSignalBlocker(self._output_trigger_bool_on_widget):
                    self._output_trigger_bool_on_widget.setChecked(True)
            elif block.trigger_mode == SimConnectTriggerMode.NoOp:
                with QtCore.QSignalBlocker(self._output_trigger_bool_on_widget):
                    self._output_trigger_bool_noop_widget.setChecked(True)


       
        
        
        input_desc = ""
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



        if self.action_data.mode == SimConnectActionMode.Ranged:
            desc = f"Maps an input {input_desc} to a SimConnect ranged event, such as an axis"
        elif self.action_data.mode == SimConnectActionMode.Trigger:
            desc = f"Maps an input {input_desc} to a SimConnect triggered event, such as an on/off or toggle function."
        elif self.action_data.mode == SimConnectActionMode.SetValue:
            desc = f"Maps an input {input_desc} to a Simconnect event and sends it the specified value."
        elif self.action_data.mode == SimConnectActionMode.Gated:
            desc = f"Maps a gated input {input_desc} to a Simconnect event and sends it the specified value."
        else:
            desc = ""

        self._output_mode_description_widget.setText(desc)

        if input_type == InputType.JoystickAxis:
            # input drives the outputs
            self._output_mode_trigger_widget.setVisible(False)
            self._output_mode_gated_widget.setVisible(True)
            self._output_mode_ranged_widget.setVisible(True)
            self._output_mode_sync_widget.setVisible(True)

        else:
            # button or event intput
            self._output_mode_trigger_widget.setVisible(True)
            self._output_mode_gated_widget.setVisible(False)
            self._output_mode_ranged_widget.setVisible(False)
            self._output_mode_sync_widget.setVisible(False)


        
        if block and block.valid:
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

            output_mode_enabled = not block.is_readonly

            
            trigger_bool_visible = False
            if input_type == InputType.JoystickAxis:
                if self.action_data.block.output_mode in (SimConnectActionMode.NotSet, SimConnectActionMode.Trigger):
                    # come up with a default mode for the selected command if not set
                    self.action_data.mode = SimConnectActionMode.Gated
                if self._gated_axis_widget is not None:
                    self._gated_axis_widget.setVisible(True)
                
                # self._output_mode_ranged_widget.setVisible(True)
                with QtCore.QSignalBlocker(self._output_invert_axis_widget):
                    self._output_invert_axis_widget.setChecked(self.action_data.block.invert_axis)

            else: # momentary input
                trigger_bool_visible = True
                if self.action_data.block.output_mode in (SimConnectActionMode.NotSet, SimConnectActionMode.Ranged, SimConnectActionMode.Gated):
                    # change from an axis mode to a triggered mode
                    if block.is_value:
                        self.action_data.mode = SimConnectActionMode.SetValue
                    else:
                        self.action_data.mode = SimConnectActionMode.Trigger

                    


            #self._output_trigger_container_widget.setVisible(trigger_mode_visible)
            self._output_trigger_bool_container_widget.setVisible(trigger_bool_visible)
            self._output_mode_container_widget.setVisible(output_mode_enabled)
            #self._output_mode_ranged_widget.setEnabled(output_mode_enabled)
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


            return
        
        # clear the data
        self._output_container_widget.setVisible(False)
        self.status_text_widget.setText("Please select a command")

        


    def _update_ui_container_visibility(self):
        ''' updates the UI based on the output mode selected '''
        input_type = self.action_data.input_type
        block : SimConnectBlock = self.action_data.block

        setvalue_visible = block.output_mode == SimConnectActionMode.SetValue
        trigger_visible = block.output_mode == SimConnectActionMode.Trigger
        if input_type == InputType.JoystickAxis:
            range_visible = block.output_mode == SimConnectActionMode.Ranged
            gated_visible = block.output_mode == SimConnectActionMode.Gated
            
        else:
            # momentary
            range_visible = False
            gated_visible = False
        
        self._output_range_container_widget.setVisible(range_visible)
        self._output_trigger_bool_container_widget.setVisible(trigger_visible)
        self._output_value_container_widget.setVisible(setvalue_visible)
        self._output_gated_container_widget.setVisible(gated_visible)




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
            self._update_ui_container_visibility()

    @QtCore.Slot(bool)
    def _mode_gated_cb(self, value):
        if value:
            self.action_data.block.output_mode = SimConnectActionMode.Gated
            self._ensure_gated()
            self._update_ui_container_visibility()

 

    @QtCore.Slot(bool)
    def _mode_value_cb(self, value):
        if value:
            self.action_data.block.output_mode = SimConnectActionMode.SetValue
            self._update_validator()
            self._update_ui_container_visibility()
        
    @QtCore.Slot(bool)
    def _mode_trigger_cb(self, value):
        if value:
            self.action_data.block.output_mode = SimConnectActionMode.Trigger
            self._update_ui_container_visibility()

    def _readonly_cb(self):
        block : SimConnectBlock
        block = self.block
        
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
        
        # self._update_block_ui()
        # self._update_ui_container_visibility()




class MapToSimConnectFunctor(gremlin.base_profile.AbstractContainerActionFunctor):

    manager = gremlin.macro.MacroManager()

    def __init__(self, action):
        super().__init__(action)
        self.action_data : MapToSimConnect = action
        self.command = action.command # the command to execute
        self.value = action.value # the value to send (None if no data to send)
        self.sm = None

    
    def profile_start(self):
        ''' occurs when the profile starts '''
        if self.action_data.enabled:
            if self.sm is None:
                self.sm = SimConnectData()
                self.block = self.sm.block(self.command)

            self.sm.sim_connect()
            self.action_data.gate_data.process_callback = self.process_gated_event
        

    def profile_stop(self):
        ''' occurs wen the profile stops'''
        if self.action_data.enabled:
            if not self.sm is None:
                self.sm.sim_disconnect()
    

    def scale_output(self, value):
        ''' scales an output value for the output range '''
        return gremlin.util.scale_to_range(value, target_min = self.action_data.block.min_range, target_max = self.action_data.block.max_range, invert=self.action_data.block.invert)
    
    def process_gated_event(self, event, value):
        ''' handles gated input data '''

        logging.getLogger("system").info(f"SC FUNCTOR: {event}  {value}")
        
        if not self.sm.ok:
            return True

        if not self.block or not self.block.valid:
            # invalid command
            return True
   
        if event.is_axis and self.block.is_axis:
            # axis event to axis block mapping
            
            if self.action_data.mode == SimConnectActionMode.Ranged:
                # come up with a default mode for the selected command if not set
                target = value.current
                output_value = gremlin.util.scale_to_range(target, target_min = self.action_data.min_range, target_max = self.action_data.max_range, invert=self.action_data.invert_axis)
                return self.block.execute(output_value)
                
            if self.action_data.mode == SimConnectActionMode.Trigger:
                pass
                    
            elif self.action_data.mode == SimConnectActionMode.SetValue:
                target = self.action_data.value
                return self.block.execute(target)
            
        elif value.is_pressed:
            # momentary trigger - trigger on press - such as from gate crossings
            return self.block.execute(value.is_pressed)
                    

    def process_event(self, event, value):
        ''' handles default input data '''

        # execute the nested functors for this action
        super().process_event(event, value)

        if not self.sm.ok:
            return True

        if not self.block or not self.block.valid:
            # invalid command
            return True
        
        if event.is_axis and self.action_data.block.output_mode in (SimConnectActionMode.Ranged, SimConnectActionMode.Gated):
            block_value = gremlin.util.scale_to_range(value.current, target_min = self.block.min_range, target_max = self.block.max_range)
            self.block.execute(block_value)
        elif self.action_data.block.output_mode == SimConnectActionMode.Trigger:
            if not event.is_axis and value.is_pressed:
                self.block.execute(value.current)
        return True
    



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
        self.sm = SimConnectData()
        self.parent = parent

        self.input_type = self.get_input_type()

        # the current command category if the command is an event
        self.category = SimConnectEventCategory.NotSet

        # the current command name
        self._command = None

        # the value to output if any
        self.value = None
        
        gate_data = GateData(profile_mode = gremlin.shared_state.current_mode, action_data=self)
        self.gates = [gate_data] # list of GateData objects
        self.gate_data = gate_data
    

        self._block = None


        # output mode
        self.mode = SimConnectActionMode.NotSet

        # readonly mode
        self.is_readonly = False


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
        self._block =self.sm.block(self._command)
    
    
    @property
    def block(self):
        ''' returns the current data block '''
        if self._block is None:
            # create it for the current command
            self.update_block()

        return self._block

        

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
        # if
        # value  = safe_read(node,"category", str)
        # self.category = SimConnectEventCategory.to_enum(value, validate=False)
        node_block =gremlin.util.get_xml_child(node,"block")
        if node_block is not None:
            self.block.from_xml(node_block)

        # load gate data
        gates = []
        gate_node = gremlin.util.get_xml_child(node,"gates")
        if not gate_node is None:
            for child in gate_node:
                gate_data = GateData(self, action_data = self)
                gate_data.from_xml(child)
                gates.append(gate_data)

        if gates:
            self.gates = gates
            self.gate_data = gates[0]

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
        node.set("command",safe_format(command, str) )

        # save gate data
        if self.gates:
            node_gate = ElementTree.SubElement(node, "gates")
            for gate_data in self.gates:
                child = gate_data.to_xml()
                node_gate.append(child)


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
        del state["sm"]
        return state

    def __setstate__(self, state):
        ''' serialization override '''
        self.__dict__.update(state)
        # sm is not serialized, add it
        self.sm = SimConnectData()

version = 1
name = "map-to-simconnect"
create = MapToSimConnect
