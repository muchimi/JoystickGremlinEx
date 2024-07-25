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
import gremlin.event_handler
from gremlin.input_types import InputType
from gremlin.input_devices import ButtonReleaseActions
import gremlin.macro
import gremlin.shared_state
import gremlin.shared_state
import gremlin.shared_state
import gremlin.shared_state
import gremlin.singleton_decorator
import gremlin.ui.ui_common
import gremlin.ui.input_item
import enum
from gremlin.profile import safe_format, safe_read
from .SimConnectData import *
import re
from lxml import etree
from xml.etree import ElementTree
6



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
    


class SimconnectMapItem():
    ''' holds data for an aircraft and options to mode mapping '''
    def __init__(self, id = None, aircraft = "", mode = ""):
        self.aircraft = aircraft
        self.mode = mode
        self.id = id if id else gremlin.util.get_guid() # unique ID
        self.key = aircraft.lower().strip() if aircraft else self.id
        self.error_status = None

    @property
    def valid(self):
        ''' true if the item contains valid data '''
        return not self.error_status and self.aircraft and self.mode
    

class SimconnectAicraftCfgData():
    ''' holds the data entry for a single aicraft from the MSFS config data '''
    def __init__(self, icao_type = None, icao_manufacturer = None, icao_model = None, titles = [], path = None):
        self.icao_type = icao_type
        self.icao_manufacturer = icao_manufacturer
        self.icao_model = icao_model
        self.titles = titles
        self.path = path

    @property
    def display_name(self):
        return f"{self.icao_manufacturer} {self.icao_model}"

@gremlin.singleton_decorator.SingletonDecorator
class SimconnectOptions():
    ''' holds simconnect mapper options for all actions '''
    def __init__(self):
        self._profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        self._mode_list = self._profile.get_modes()
        self._xml_source = os.path.join(gremlin.util.userprofile_path(),"simconnect_config.xml")
        self._auto_mode_select = True # if set, autoloads the mode associated with the aircraft if such a mode exists
        self._aircraft_map = {} # list of SimconnectMapItem keyed by ID
        self._aircraft_entries = [] # holds aicraft entries
        self._titles = []
        self._community_folder = r"C:\Microsoft Flight Simulator\Community"
        self.parse_xml()

    def validate(self):
        ''' validates options are ok '''
        a_list = []
        valid = True
        for item in self._aircraft_map.values():
            item.error_status = None
            if item.key in a_list:
                item.error_status = f"Duplicate entry found {item.aircraft}"
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
            if not item.aircraft:
                item.error_status = f"Aircraft name cannot be blank"
                valid = False

        return valid

    def find(self, aircraft):
        ''' gets an item by aircraft name (not case sensitive)'''
        if not aircraft:
            return None
        key = aircraft.lower().trim()
        for item in self._aircraft_map.values():
            if item.key == key:
                return item
        return None
    
    def get_aircraft_mode(self, aircraft):
        ''' gets the mode associated with this aicraft, and the default mode if not a valid mode '''
        item = self.find(aircraft)
        if item:
            if item.mode:
                return item.mode
        return self._profile.get_default_mode()

    
    def set_aircraft_mode(self, aircraft, mode):
        ''' saves a mode with a particular aircraft '''
        aircraft = aircraft.strip().lower()
        self._aircraft_map[aircraft] = mode

    def remove_aircraft_mode(self, aircraft):
        aircraft = aircraft.strip().lower()
        if aircraft in self._aircraft_map.keys():
            del self._aircraft_map[aircraft]
            
    
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
        self._aircraft_map.clear()
        try:
            parser = etree.XMLParser(remove_blank_text=True)
            root = etree.parse(xml_source, parser)

            nodes = root.xpath('//options')
            for node in nodes:
                if "auto_mode_select" in node.attrib:
                    self._auto_mode_select = safe_read(node,"auto_mode_select",bool,True)
                if "community_folder" in node.attrib:
                    self._community_folder = safe_read(node,"community_folder", str, "")
                break

            node_mode_map = None
            nodes = root.xpath("//mode_map")
            for node in nodes:
                node_mode_map = node
                break

            if node_mode_map is not None:
                for node in node_mode_map:
                    aircraft = safe_read(node,"aicraft", str, "")
                    mode = safe_read(node,"mode", str, "")
                    id = safe_read(node,"id", str, "")
                    item = SimconnectMapItem(id, aircraft, mode)
                    self._aircraft_map[item.id] = item

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
                    titles = []
                    node_titles = None
                    for child in node:
                        node_titles = child

                    if node_titles is not None:
                        for child in node_titles:
                            titles.append(child.text)

                    if icao_model and icao_manufacturer and icao_type:
                        item = SimconnectAicraftCfgData(icao_model=icao_model, 
                                                 icao_manufacturer=icao_manufacturer, 
                                                 icao_type=icao_type, 
                                                 titles=titles,
                                                 path = path)
                        self._aircraft_entries.append(item)

            

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

        # mode maps
        node_mode_map = etree.SubElement(root,"mode_map")
        for item in self._aircraft_map.values():
            node = etree.SubElement(node_mode_map,"map")
            node.set("aicraft", item.aircraft)
            node.set("mode", item.mode)
            node.set("id", item.id)

        # scanned aicraft titles 
        if self._aircraft_entries:
            node_items = etree.SubElement(root,"items")
            for item in self._aircraft_entries:
                node = etree.SubElement(node_items,"item")
                node.set("model", item.icao_model)
                node.set("manufacturer", item.icao_manufacturer)
                node.set("type",item.icao_type)
                node.set("path", item.path)
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
        folder = QtWidgets.QFileDialog.getExistingDirectory()
        if folder and os.path.isdir(folder):
            return folder
        return None


    def scan_aircraft_config(self, owner):
        ''' scans MSFS folders for the list of aircraft names '''
        
        def fix_entry(value):
            value = re.sub(r'[^0-9a-zA-Z\s]+', '', value)
            return value.strip()


        from gremlin.ui import ui_common
        if not self._community_folder or not os.path.isdir(self._community_folder):
            self._community_folder = self.get_community_folder()
        if not self._community_folder or not os.path.isdir(self._community_folder):
            return
        #gremlin.util.pushCursor()

        progress = QtWidgets.QProgressDialog(parent = owner, labelText ="Scanning folders...", cancelButtonText = "Cancel", minimum = 0, maximum= 100, flags = QtCore.Qt.FramelessWindowHint)
        progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress.setValue(0)
        progress.show()
        QtWidgets.QApplication.processEvents()

        # progress.percent = 0
        # progress.message = "Scanning Folders..."

        search_folder = os.path.dirname(self._community_folder)
        source_files = gremlin.util.find_files(search_folder,"aircraft.cfg")

      
        
        self._aircraft_entries.clear()
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
                titles.sort()
            if icao_model and icao_type and icao_manuf:
                path = os.path.dirname(file)
                item = SimconnectAicraftCfgData(icao_type, icao_manuf, icao_model, titles, path)
                if not item.display_name in keys:
                    # avoid duplicate entries
                    items.append(item)
                    keys.append(item.display_name)

        if not is_canceled:
            self._aircraft_entries = items
        progress.close()
        
        #gremlin.util.popCursor()
        

class SimConnectAircraftSearchDialog(QtWidgets.QDialog):
    ''' shows a search box for aicraft '''
    
    def __init__(self, options : SimconnectOptions, data = None, parent=None):
        super().__init__(parent)

        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)


        self.main_layout = QtWidgets.QVBoxLayout(self)

        self._selector_widget = QtWidgets.QComboBox()
        self._selector_widget.setEditable(True)
        item : SimconnectAicraftCfgData
        self._data = data
        current_index = 0
        aircraft = data.aircraft.lower()
        for index,item in enumerate(options._aircraft_entries):
            if data and aircraft == item.display_name.lower():
                current_index = index
            self._selector_widget.addItem(item.display_name, item)
        self.main_layout.addWidget(self._selector_widget)
        self._aircraft_list = [item.display_name for item in options._aircraft_entries]

        # setup auto-completer for the command 
        completer = QtWidgets.QCompleter(self._aircraft_list, self)
        completer.setCaseSensitivity(QtGui.Qt.CaseSensitivity.CaseInsensitive)

        self._selector_widget.setCompleter(completer)
        

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        self.button_widget = QtWidgets.QWidget()
        self.button_layout = QtWidgets.QHBoxLayout(self.button_widget)
        

        self.button_layout.addStretch()
        self.button_layout.addWidget(self.ok_widget)
        self.button_layout.addWidget(self.cancel_widget)

        self.main_layout.addWidget(self.button_widget)

        self._selector_widget.setCurrentIndex(current_index)
        self._selected =  self._selector_widget.itemData(current_index)

        self._selector_widget.currentIndexChanged.connect(self._selector_change_cb)

    def _ok_button_cb(self):
        ''' ok button pressed '''
        self.accept()
        
    def _cancel_button_cb(self):
        ''' cancel button pressed '''
        self.reject()        


    @QtCore.Slot(int)
    def _selector_change_cb(self, index):
        self._selected = self._selector_widget.itemData(index)

    @property
    def selected(self):
        # returns the selected cfg object
        return self._selected
    
    @property
    def data(self):
        ''' returns the map item'''
        return self._data


        



class SimconnectOptionsUi(QtWidgets.QDialog):
    """UI to set individual simconnect  settings """

    def __init__(self, parent=None):
        super().__init__(parent)

        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        min_min_sp = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Minimum,
            QtWidgets.QSizePolicy.Minimum
        )
        exp_min_sp = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding,
            QtWidgets.QSizePolicy.Minimum
        )        

        # Actual configuration object being managed
        self.config = gremlin.config.Configuration()
        self.setMinimumWidth(400)

        self.mode_list = []
        self.profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        self.mode_list = self.profile.get_modes()
        self.options = SimconnectOptions()

        self.setWindowTitle("Simconnect Options")

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self._auto_mode_switch = QtWidgets.QCheckBox("Change profile mode based on active aicraft")
        self._auto_mode_switch.setToolTip("When enabled, the profile mode will automatically change based on the mode associated with the active player aircraft in Flight Simulator")
        self._auto_mode_switch.setChecked(self.options.auto_mode_select)
        self._auto_mode_switch.clicked.connect(self._auto_mode_select_cb)

        self._mode_from_aircraft_button_widget = QtWidgets.QPushButton("Mode from Aicraft")
        self._mode_from_aircraft_button_widget.clicked.connect(self._mode_from_aircraft_button_cb)

        # toolbar for map
        self.container_bar_widget = QtWidgets.QWidget()
        self.container_bar_layout = QtWidgets.QHBoxLayout(self.container_bar_widget)

        self.add_map_widget = QtWidgets.QPushButton("Add mapping")
        self.add_map_widget.setIcon(gremlin.util.load_icon("button_add.png"))
        self.add_map_widget.clicked.connect(self._add_map_cb)
        self.add_map_widget.setToolTip("Adds a new aircraft to profile mode mapping entry")

        self.scan_aircraft_widget = QtWidgets.QPushButton("Scan Aircraft")
        self.scan_aircraft_widget.setIcon(gremlin.util.load_icon("mdi.magnify-scan"))
        self.scan_aircraft_widget.clicked.connect(self._scan_aircraft_cb)
        self.scan_aircraft_widget.setToolTip("Scan MSFS aicraft folders for aircraft names")



        self.container_bar_layout.addWidget(self.add_map_widget)
        self.container_bar_layout.addWidget(self.scan_aircraft_widget)
        self.container_bar_layout.addStretch()

        self.container_map_widget = QtWidgets.QWidget()
        self.container_map_layout = QtWidgets.QVBoxLayout(self.container_map_widget)

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
        self.map_layout = QtWidgets.QGridLayout()
        self.map_layout.setContentsMargins(0,0,0,0)
        self.map_widget.setLayout(self.map_layout)

        self.scroll_layout.addWidget(self.map_widget)
        self.scroll_layout.setContentsMargins(6,0,6,0)
        self.scroll_layout.addStretch()
        self.container_map_layout.addWidget(self.scroll_area)

        
        self.close_button_widget = QtWidgets.QPushButton("Close")
        self.close_button_widget.clicked.connect(self.close_button_cb)


        button_bar_widget = QtWidgets.QWidget()
        button_bar_layout = QtWidgets.QHBoxLayout(button_bar_widget)
        button_bar_layout.addStretch()
        button_bar_layout.addWidget(self.close_button_widget)

        self.main_layout.addWidget(self._auto_mode_switch)
        self.main_layout.addWidget(self.container_bar_widget)
        self.main_layout.addWidget(self.container_map_widget)
        self.main_layout.addWidget(button_bar_widget)
        
        self.populate_map()

    def closeEvent(self, event):
        ''' occurs on window close '''
        self.options.save()
        super().closeEvent(event)

    @QtCore.Slot(bool)
    def _auto_mode_select_cb(self, checked):
        ''' auto mode changed'''
        self.options.auto_mode_select = checked

    @QtCore.Slot()
    def _add_map_cb(self):
        ''' adds a new mapping entry '''
        item = SimconnectMapItem()
        self.options._aircraft_map[item.id] = item
        self.populate_map()

    @QtCore.Slot()
    def _scan_aircraft_cb(self):
        self.options.scan_aircraft_config(self)

        # update the aicraft drop down choices
        self.populate_map()



    @QtCore.Slot()
    def close_button_cb(self):
        ''' called when close button clicked '''
        self.close()

    def populate_map(self):
        ''' populates the map of aircraft to profile modes '''

        from gremlin.ui import ui_common
        self.options.validate()


        # figure out the size of the header part of the control so things line up
        lbl = QtWidgets.QLabel("w")
        char_width = lbl.fontMetrics().averageCharWidth()
        headers = ["Aicraft:", "Mode:"]
        width = 0
        for header in headers:
            width = max(width, char_width*(len(header)))


        # gets a pair list of display/value for modes with hierarchy
        mode_pairs_list = gremlin.ui.ui_common.get_mode_list(self.profile)

        # clear the widgets
        ui_common.clear_layout(self.map_layout)


        if not self.options._aircraft_map:
             missing = QtWidgets.QLabel("No mappings found.")
             missing.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
             self.map_layout.addWidget(missing, 0, 0)
             return


        

        for index, item in enumerate(self.options._aircraft_map.values()):

            aircraft_widget = None
            mode_selector_widget = None
            aircraft = item.aircraft
            mode = item.mode

            if item:
                # add a new item if it exists and either one of the profile/process entries are refined

                row = 0

                container_widget = QtWidgets.QWidget()
                container_layout = QtWidgets.QGridLayout()
                container_layout.setColumnStretch(0,2)
                container_layout.setColumnStretch(1,2)
                container_layout.setContentsMargins(0,6,0,0)
                container_widget.setLayout(container_layout)

                aircraft_label = QtWidgets.QLabel("Aicraft:")
                aircraft_label.setMaximumWidth(width)
                aircraft_widget =ui_common.QDataLineEdit(aircraft, item)
                aircraft_widget.installEventFilter(self)
                

                select_button = ui_common.QDataPushButton(data = item)
                select_button.setIcon(gremlin.util.load_icon("fa.search"))
                select_button.clicked.connect(self._aircraft_search_cb)
                select_button.setMaximumWidth(20)
                select_button.setToolTip("Aircraft lookup")
                container_layout.addWidget(aircraft_label,row,0)
                container_layout.addWidget(aircraft_widget,row,1)
                container_layout.addWidget(select_button,row,2)
                row+=1

                # add mode selector widget for this aircraft
                mode_label = QtWidgets.QLabel("Mode:")
                mode_label.setMaximumWidth(width)
                mode_selector_widget = ui_common.QDataComboBox(data=item)

                # populate mode data
                mode_index = 0
                current_index = 0
                for display_name, mode_name in mode_pairs_list:
                    mode_selector_widget.addItem(display_name, mode_name)
                    if mode_name == mode:
                        current_index = mode_index
                    mode_index +=1

                mode_selector_widget.setCurrentIndex(current_index)
                # self._mode_map_aircraft_widgets[index] = aircraft_widget
                # self._mode_map_mode_selector_widgets[index] = mode_selector_widget

                mode_selector_widget.currentIndexChanged.connect(self._mode_selector_changed_cb)
                container_layout.addWidget(mode_label,row,0)
                container_layout.addWidget(mode_selector_widget,row,1)
                row+=1

                active_button = ui_common.QDataPushButton()
                active_button.setIcon(gremlin.util.load_icon("mdi.airplane"))
                active_button.clicked.connect(self._active_button_cb)
                active_button.data = item


                clear_button = ui_common.QDataPushButton()
                clear_button.setIcon(gremlin.util.load_icon("mdi.delete"))
                clear_button.setMaximumWidth(20)
                clear_button.data = item
                clear_button.clicked.connect(self._mapping_delete_cb)
                clear_button.setToolTip("Removes this entry")
                container_layout.addWidget(clear_button, 0, 4)

                duplicate_button = ui_common.QDataPushButton()
                duplicate_button.setIcon(gremlin.util.load_icon("mdi.content-duplicate"))
                duplicate_button.setMaximumWidth(20)
                duplicate_button.data = aircraft
                duplicate_button.clicked.connect(self._mapping_duplicate_cb)
                duplicate_button.setToolTip("Duplicates this entry")
                container_layout.addWidget(duplicate_button, 1, 4)
                if not item.valid:
                    status_widget = ui_common.QIconLabel("fa.warning", use_qta=True,text=item.error_status)
                    container_layout.addWidget(status_widget,row,0,1,-1)
                    row+=1

                container_layout.addWidget(ui_common.QHLine(),row,0,1, -1)

                self.map_layout.addWidget(container_widget, index, 0)


    def eventFilter(self, widget, event):
        ''' ensure line changes are saved '''
        t = event.type()
        if t == QtCore.QEvent.Type.FocusOut:
            item = widget.data
            text = widget.text()
            if text != item.aircraft:
                item.aircraft = text
                self.populate_map()
        return False


    @QtCore.Slot()
    def _aircraft_search_cb(self):
        ''' search button clicked '''
        widget = self.sender()
        map_item = widget.data
        dialog = SimConnectAircraftSearchDialog(self.options, data = map_item, parent = self)
        dialog.accepted.connect(self._dialog_ok_cb)
        dialog.rejected.connect(self._dialog_close_cb)
        dialog.setModal(True)
        dialog.showNormal()  

    def _dialog_close_cb(self):
        self.close()

    def _dialog_ok_cb(self):
        ''' callled when the dialog completes ''' 
        widget = self.sender()
        item = widget.selected
        map_item = widget.data
        map_item.aircraft = item.display_name
        self.populate_map()




    @QtCore.Slot(int)
    def _mode_selector_changed_cb(self, selected_index):
        ''' occurs when the mode is changed on an entry '''
        widget = self.sender()
        mode = widget.currentData()
        item = widget.data
        if item.mode != mode:
            item.mode = mode
            self.populate_map()
        
    @QtCore.Slot()
    def _active_button_cb(self):
        widget = self.sender()
        sm = SimConnectData()
        
        aircraft = sm.get_aircraft()
        if aircraft:
            item = widget.data
            item.aircraft = aircraft

    def _mapping_duplicate_cb(self):
        ''' duplicates the current entry '''
        widget = self.sender()
        item = widget.data
        dup = SimconnectMapItem(None, item.aircraft, item.mode)
        self.options._aircraft_map[dup.id] = dup
        self.populate_map()

    def _mapping_delete_cb(self):
        widget = self.sender()
        item = widget.data
        message_box = QtWidgets.QMessageBox()
        message_box.setText("Delete confirmation")
        message_box.setInformativeText("This will delete this association.\nAre you sure?")
        pixmap = gremlin.util.load_pixmap("warning.svg")
        pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        message_box.setIconPixmap(pixmap)
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
            )
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self._delete_confirmed_cb(item)


    def _delete_confirmed_cb(self, item):
        del self.options._aircraft_map[item.id]
        self.populate_map()

        
    @QtCore.Slot()
    def _mode_from_aircraft_button_cb(self):
        ''' mode from aicraft button '''
        aircraft, model, title = self._sm_data.get_aircraft_data()
        logging.getLogger("system").info(f"Aircraft: {aircraft} model: {model} title: {title}")
        if not title in self._mode_list:
            profile.add_mode(title)
            
        


class MapToSimConnectWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to keyboard key combinations - adds extra functionality to the base module ."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        
        self.action_data : MapToSimConnect = action_data
        self.block = None
        self._sm_data = SimConnectData()
        self.options = SimconnectOptions()

        # call super last because it will call create_ui and populate_ui so the vars must exist
        super().__init__(action_data, parent=parent)

                



    def _create_ui(self):
        """Creates the UI components."""


        # mode from aircraft button - grabs the aicraft name as a mode
        self._options_button_widget = QtWidgets.QPushButton("Simconnect Options")
        self._options_button_widget.setIcon(gremlin.util.load_icon("fa.gear"))
        self._options_button_widget.clicked.connect(self._show_options_dialog_cb)
        
        # self._toolbar_container_widget = QtWidgets.QWidget()
        # self._toolbar_container_layout = QtWidgets.QHBoxLayout(self._toolbar_container_widget)
        # self._toolbar_container_layout.addWidget(self._options_button_widget)
        # self._toolbar_container_layout.addStretch()

        # command selector
        self._action_container_widget = QtWidgets.QWidget()
        self._action_container_layout = QtWidgets.QVBoxLayout(self._action_container_widget)

        self._action_selector_widget = QtWidgets.QWidget()
        self._action_selector_layout = QtWidgets.QHBoxLayout(self._action_selector_widget)

        # list of possible events to trigger
        self._command_selector_widget = QtWidgets.QComboBox()
        self._command_list = self._sm_data.get_command_name_list()
        self._command_selector_widget.setEditable(True)
        self._command_selector_widget.addItems(self._command_list)
        self._command_selector_widget.currentIndexChanged.connect(self._command_changed_cb)

        self._command_selector_widget.setValidator(CommandValidator())

        # setup auto-completer for the command 
        command_completer = QtWidgets.QCompleter(self._command_list, self)
        command_completer.setCaseSensitivity(QtGui.Qt.CaseSensitivity.CaseInsensitive)

        self._command_selector_widget.setCompleter(command_completer)

        #self.action_selector_layout.addWidget(self.category_widget)
        self._action_selector_layout.addWidget(QtWidgets.QLabel("Selected command:"))
        self._action_selector_layout.addWidget(self._command_selector_widget)
        self._action_selector_layout.addStretch()
        self._action_selector_layout.addWidget(self._options_button_widget)
        

        # output container - below selector - visible when a command is selected 
        self._output_container_widget = QtWidgets.QWidget()
        self._output_container_layout = QtWidgets.QVBoxLayout(self._output_container_widget)
        

        self._output_mode_widget = QtWidgets.QWidget()
        self._output_mode_layout = QtWidgets.QHBoxLayout(self._output_mode_widget)
        
        self._output_mode_readonly_widget = QtWidgets.QRadioButton("Read/Only")
        self._output_mode_readonly_widget.setEnabled(False)

        # set range of values output mode (axis input only)
        self._output_mode_ranged_widget = QtWidgets.QRadioButton("Ranged")
        self._output_mode_ranged_widget.clicked.connect(self._mode_ranged_cb)


        # trigger output mode (event trigger only)
        self._output_mode_trigger_widget = QtWidgets.QRadioButton("Trigger")
        self._output_mode_trigger_widget.clicked.connect(self._mode_trigger_cb)

        self._output_mode_description_widget = QtWidgets.QLabel()
        self._output_mode_layout.addWidget(QtWidgets.QLabel("Output mode:"))


        # set value output mode (output value only)
        self._output_mode_set_value_widget = QtWidgets.QRadioButton("Value")
        self._output_mode_set_value_widget.clicked.connect(self._mode_value_cb)

        self._output_mode_layout.addWidget(self._output_mode_readonly_widget)
        self._output_mode_layout.addWidget(self._output_mode_ranged_widget)
        self._output_mode_layout.addWidget(self._output_mode_trigger_widget)
        self._output_mode_layout.addWidget(self._output_mode_set_value_widget)
        self._output_mode_layout.addStretch()

        self.output_readonly_status_widget = QtWidgets.QLabel("Read only")
        self._output_mode_layout.addWidget(self.output_readonly_status_widget)

        self._output_invert_axis_widget = QtWidgets.QCheckBox("Invert axis")
        self._output_invert_axis_widget.setChecked(self.action_data.invert_axis)
        self._output_invert_axis_widget.clicked.connect(self._output_invert_axis_cb)




        # output data type UI 
        self._output_data_type_widget = QtWidgets.QWidget()
        self._output_data_type_layout = QtWidgets.QHBoxLayout(self._output_data_type_widget)
        
        self._output_data_type_label_widget = QtWidgets.QLabel("Not Set")

        # self._output_block_type_description_widget = QtWidgets.QLabel()

        self._output_data_type_layout.addWidget(QtWidgets.QLabel("Output type:"))
        self._output_data_type_layout.addWidget(self._output_data_type_label_widget)
        self._output_data_type_layout.addWidget(self._output_mode_description_widget)
        self._output_data_type_layout.addStretch()


        # output range UI
        self._output_range_container_widget = QtWidgets.QWidget()
        self._output_range_container_layout = QtWidgets.QVBoxLayout(self._output_range_container_widget)
        

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
        output_row_layout.addWidget(self._output_invert_axis_widget)
        output_row_layout.addWidget(QtWidgets.QLabel("Range min:"))
        output_row_layout.addWidget(self._output_min_range_widget)
        output_row_layout.addWidget(QtWidgets.QLabel("Range max:"))
        output_row_layout.addWidget(self._output_max_range_widget)
        output_row_layout.addStretch(1)
        

        self._output_range_container_layout.addWidget(output_row_widget)

        # holds the output value if the output value is a fixed value
        self._output_value_container_widget = QtWidgets.QWidget()
        self._output_value_container_layout = QtWidgets.QHBoxLayout(self._output_value_container_widget)
        self.output_value_widget = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.output_value_widget.valueChanged.connect(self._output_value_changed_cb)
        self.output_value_description_widget = QtWidgets.QLabel()

        self.command_header_container_widget = QtWidgets.QWidget()
        self.command_header_container_layout = QtWidgets.QHBoxLayout(self.command_header_container_widget)
        

        self.command_text_widget = QtWidgets.QLabel()
        self.command_header_container_layout.addWidget(QtWidgets.QLabel("<b>Command:</b>"))
        self.command_header_container_layout.addWidget(self.command_text_widget)

        self.description_text_widget = QtWidgets.QLabel()
        self.command_header_container_layout.addWidget(QtWidgets.QLabel("<b>Description</b>"))
        self.command_header_container_layout.addWidget(self.description_text_widget)

        self.command_header_container_layout.addStretch(1)


        self._output_value_container_layout.addWidget(QtWidgets.QLabel("Output value:"))
        self._output_value_container_layout.addWidget(self.output_value_widget)
        self._output_value_container_layout.addWidget(self.output_value_description_widget)
        self._output_value_container_layout.addStretch(1)

        # trigger mode (sends the command )
        self.output_trigger_container_widget = QtWidgets.QWidget()
        self.output_trigger_container_layout = QtWidgets.QHBoxLayout()
        self.output_trigger_container_widget.setLayout(self.output_trigger_container_layout)
                

        self._output_container_layout.addWidget(self.command_header_container_widget)
        self._output_container_layout.addWidget(QHLine())
        self._output_container_layout.addWidget(self._output_mode_widget)                
        self._output_container_layout.addWidget(self._output_data_type_widget)
        self._output_container_layout.addWidget(self._output_range_container_widget)
        self._output_container_layout.addWidget(self._output_value_container_widget)
        self._output_container_layout.addWidget(self.output_trigger_container_widget)
        self._output_container_layout.addStretch(1)


        # input repeater widgets (shows joystick axis values)
        self._input_axis_widget = gremlin.ui.ui_common.AxisStateWidget(show_label = False, orientation=QtCore.Qt.Orientation.Horizontal, show_percentage=False)
        self._output_axis_widget = gremlin.ui.ui_common.AxisStateWidget(show_label = False, orientation=QtCore.Qt.Orientation.Horizontal, show_percentage=False)
        self._output_axis_widget.setRange(self.action_data.min_range, self.action_data.max_range)
        self._input_axis_value_widget = QtWidgets.QLabel()
        self._output_axis_value_widget = QtWidgets.QLabel()
        self._input_container_widget = QtWidgets.QWidget()
        self._input_container_layout = QtWidgets.QGridLayout(self._input_container_widget)
        self._input_container_layout.addWidget(self._input_axis_widget,0,0)
        self._input_container_layout.addWidget(self._output_axis_widget,0,1)
        self._input_container_layout.addWidget(self._input_axis_value_widget,1,0)
        self._input_container_layout.addWidget(self._output_axis_value_widget,1,1)


        # status widget
        self.status_text_widget = QtWidgets.QLabel()

        
        self._action_container_layout.addWidget(self._action_selector_widget)


        # hide output layout by default until we have a valid command
        self._output_container_widget.setVisible(False)

        #self.main_layout.addWidget(self._toolbar_container_widget)
        self.main_layout.addWidget(self._action_container_widget)
        self.main_layout.addWidget(self._output_container_widget)
        self.main_layout.addWidget(self._input_container_widget)
        self.main_layout.addWidget(self.status_text_widget)

        self.main_layout.addStretch(1)

        # hook the joystick input for axis input repeater
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_cb)


    def _show_options_dialog_cb(self):
        ''' displays the simconnect options dialog'''
        dialog = SimconnectOptionsUi()
        dialog.exec()

    @QtCore.Slot(Event)
    def _joystick_event_cb(self, event):
        if self.is_running or not event.is_axis:
            # ignore if not an axis event and if the profile is running, or input for a different device
            return
        
        if self.action_data.hardware_device_guid != event.device_guid:
            # print (f"device mis-match: {str(self.action_data.hardware_device_guid)}  {str(event.device_guid)}")
            return
            
        if self.action_data.hardware_input_id != event.identifier:
            # print (f"input mismatch: {self.action_data.hardware_input_id} {event.identifier}")
            return
        
        # axis value
        #if self.action_data.mode == SimConnectActionMode.Ranged:
        # ranged mode
        raw_value = event.raw_value
        input_value = gremlin.util.scale_to_range(raw_value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1) + 0 # removes negative zero in python
        self._input_axis_widget.setValue(input_value)
        output_value = gremlin.util.scale_to_range(input_value, target_min = self.action_data.min_range, target_max = self.action_data.max_range, invert= self.action_data.invert_axis) 
        self._output_axis_widget.setValue(output_value)
        self._input_axis_value_widget.setText(f"{input_value:0.2f}")
        self._output_axis_value_widget.setText(f"{output_value:0.2f}")








    def _output_value_changed_cb(self):
        ''' occurs when the output value has changed '''
        value = self.output_value_widget.value()
        block: SimConnectBlock
        block = self.block
        if block:
            block.disable_notifications()
            block.value = value
            block.enable_notifications()
            # store to profile
            self.action_data.value = value


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
        self.action_data.invert_axis = checked
        

    def _command_changed_cb(self, index):
        ''' called when selected command changes '''
        command = self._command_selector_widget.currentText()
        
        block = self._sm_data.block(command)
        self._update_block_ui(block)

        # store command to profile
        self.action_data.command = command

    def _update_block_ui(self, block : SimConnectBlock):
        ''' updates the UI with a data block '''
        if self.block and self.block != block:
            # unhook block events
            self.block.range_changed.disconnect(self._range_changed_cb)

        self.block = block

        input_type = self.action_data.get_input_type()
        
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
        else:
            desc = ""

        self._output_mode_description_widget.setText(desc)

        
        if block and block.valid:
            self._output_container_widget.setVisible(True)


            self.output_readonly_status_widget.setText("Block: read/only" if block.is_readonly else "Block: read/write")

            self.status_text_widget.setText("Command selected")

            if input_type == InputType.JoystickAxis:
                # input drives the outputs
                self.output_value_widget.setVisible(False)
            else:
                # button or event intput
                self.output_value_widget.setVisible(block.is_value)

            # display range information if the command is a ranged command
            self._output_range_container_widget.setVisible(block.is_ranged)

            # hook block events
            block.range_changed.connect(self._range_changed_cb)   

            # command description
            self.command_text_widget.setText(block.command)
            self.description_text_widget.setText(block.description)

            # update UI based on block information ``
            self._output_data_type_label_widget.setText(block.display_block_type)

            output_mode_enabled = not block.is_readonly

            if self.action_data.mode == SimConnectActionMode.NotSet:
                # come up with a default mode for the selected command if not set
                if input_type == InputType.JoystickAxis:
                    self.action_data.mode = SimConnectActionMode.Ranged
                else:
                    if block.is_value:
                        self.action_data.mode = SimConnectActionMode.SetValue
                    else:    
                        self.action_data.mode = SimConnectActionMode.Trigger            

            if not output_mode_enabled:
                self._output_mode_readonly_widget.setChecked(True)
                self.action_data.mode = SimConnectActionMode.NotSet
            elif self._output_mode_readonly_widget.isChecked():
                if input_type == InputType.JoystickAxis:
                    self.action_data.mode = SimConnectActionMode.Ranged
                elif block.is_value:
                    self.action_data.mode = SimConnectActionMode.SetValue
        
            self._output_mode_ranged_widget.setEnabled(output_mode_enabled)
            self._output_mode_set_value_widget.setEnabled(output_mode_enabled)
            self._output_mode_trigger_widget.setEnabled(output_mode_enabled)

                
            if self.action_data.mode == SimConnectActionMode.Trigger:
                with QtCore.QSignalBlocker(self._output_mode_trigger_widget):
                    self._output_mode_trigger_widget.setChecked(True)
            elif self.action_data.mode == SimConnectActionMode.SetValue:
                with QtCore.QSignalBlocker(self._output_mode_set_value_widget):
                    self._output_mode_set_value_widget.setChecked(True)
            elif self.action_data.mode == SimConnectActionMode.Ranged:
                with QtCore.QSignalBlocker(self._output_mode_ranged_widget):
                    self._output_mode_ranged_widget.setChecked(True)
            
            self._output_data_type_label_widget.setText(block.display_data_type)
            self.output_readonly_status_widget.setText("(command is Read/Only)" if block.is_readonly else '')

            is_ranged = block.is_ranged
            if is_ranged:
                self._output_range_ref_text_widget.setText(f"Command output range: {block.min_range:+}/{block.max_range:+}")
                if self.action_data.min_range < block.min_range:
                    self.action_data.min_range = block.min_range
                if self.action_data.max_range > block.max_range:
                    self.action_data.max_range = block.max_range
                if self.action_data.max_range > self.action_data.min_range:
                    self.action_data.max_range = block.max_range
                if self.action_data.min_range > self.action_data.min_range:
                    self.action_data.min_range = block.min_range

                with QtCore.QSignalBlocker(self._output_min_range_widget):
                    self._output_min_range_widget.setValue(self.action_data.min_range)  
                with QtCore.QSignalBlocker(self._output_max_range_widget):
                    self._output_max_range_widget.setValue(self.action_data.max_range)  

                # update the output data type
            if block.output_data_type == SimConnectBlock.OutputType.FloatNumber:
                self._output_data_type_label_widget.setText("Number (float)")
            elif block.output_data_type == SimConnectBlock.OutputType.IntNumber:
                self._output_data_type_label_widget.setText("Number (int)")
            else:
                self._output_data_type_label_widget.setText("N/A")



            return
        
        # clear the data
        self._output_container_widget.setVisible(False)
        self.status_text_widget.setText("Please select a command")


    def _update_ui(self):
        ''' updates the UI based on the output mode selected '''
        range_visible = self.action_data.mode == SimConnectActionMode.Ranged
        trigger_visible = self.action_data.mode == SimConnectActionMode.Trigger
        setvalue_visible = self.action_data.mode == SimConnectActionMode.SetValue

        

        self._output_range_container_widget.setVisible(range_visible)
        self.output_trigger_container_widget.setVisible(trigger_visible)
        self._output_value_container_widget.setVisible(setvalue_visible)

    def _range_changed_cb(self, event : SimConnectBlock.RangeEvent):
        ''' called when range information changes on the current simconnect command block '''
        self._output_min_range_widget.setValue(event.min)
        self._output_max_range_widget.setValue(event.max)
        self._output_min_range_widget.setValue(event.min_custom)
        self._output_max_range_widget.setValue(event.max_custom)

    def _mode_ranged_cb(self):
        value = self._output_mode_ranged_widget.isChecked()
        if value:
            self.action_data.mode = SimConnectActionMode.Ranged
            self._update_ui()

    def _mode_value_cb(self):
        value = self._output_mode_set_value_widget.isChecked()
        if value:
            self.action_data.mode = SimConnectActionMode.SetValue
            self._update_ui()
        
    def _mode_trigger_cb(self):
        value = self._output_mode_trigger_widget.isChecked()
        if value:
            self.action_data.mode = SimConnectActionMode.Trigger
            self._update_ui()

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

        self.block = self._sm_data.block(self.action_data.command)
        self._update_block_ui(self.block)
        self._update_ui()




class MapToSimConnectFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action):
        super().__init__(action)
        self.action_data : MapToSimConnect = action
        self.command = action.command # the command to execute
        self.value = action.value # the value to send (None if no data to send)
        self.sm = SimConnectData()
        self.block = self.sm.block(self.command)
    
    def profile_start(self):
        ''' occurs when the profile starts '''
        self.sm.connect()
        

    def profile_stop(self):
        ''' occurs wen the profile stops'''
        self.sm.disconnect()
    

    def process_event(self, event, value):

        logging.getLogger("system").info(f"SC FUNCTOR: {event}  {value}")

        if not self.sm.ok:
            return True

        if not self.block or not self.block.valid:
            # invalid command
            return True
        
        
        
   
        if event.is_axis and self.block.is_axis:
            # value is a ranged input value
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
                pass
            
        elif value.current:
            # non joystick input (button)
            if not self.block.is_axis: 
                return self.block.execute(self.value)
        
        return True
    



class MapToSimConnect(gremlin.base_profile.AbstractAction):

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
        return 9

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent)
        self.sm = SimConnectData()

        # the current command category if the command is an event
        self.category = SimConnectEventCategory.NotSet

        # the current command name
        self.command = None

        # the value to output if any
        self.value = None

        # the block for the command
        self.min_range = -16383
        self.max_range = 16383

        # output mode
        self.mode = SimConnectActionMode.NotSet

        # readonly mode
        self.is_readonly = False

        # invert axis input (axis inputs only)
        self.invert_axis = False

      

    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        return "mdi.airplane"
        

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
        # if 
        # value  = safe_read(node,"category", str)
        # self.category = SimConnectEventCategory.to_enum(value, validate=False)
        command = safe_read(node,"command", str)
        if not command:
            command = SimConnectData().get_default_command()
        self.command = command
        self.value = safe_read(node,"value", float, 0)
        mode = safe_read(node,"mode", str, "none")
        self.mode = SimConnectActionMode.to_enum(mode)

        # axis inversion
        self.invert_axis = safe_read(node,"invert", bool, False)

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(MapToSimConnect.tag)

        # simconnect command
        command = self.command if self.command else ""
        node.set("command",safe_format(command, str) )

        # fixed value
        value = self.value if self.value else 0.0
        node.set("value",safe_format(value, float))

        # action mode
        mode = SimConnectActionMode.to_string(self.mode)
        node.set("mode",safe_format(mode, str))

        # axis inversion
        node.set("invert",str(self.invert_axis))


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
