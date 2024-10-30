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



''' profile importer

Adds the ability to import a mapping from an existing device.

'''


from __future__ import annotations
from collections import namedtuple
import os
import copy
import logging
import time
from typing import Union, Any
import gremlin.import_profile
import gremlin.joystick_handling
import gremlin.plugin_manager
import gremlin.util
import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
import gremlin.shared_state

import PySide6
from PySide6 import QtCore, QtGui, QtWidgets, QtMultimedia
# from gremlin.util import *
from gremlin.types import DeviceType
from gremlin.input_types import InputType
from gremlin.util import safe_read
from gremlin.ui import ui_common,midi_device,osc_device, keyboard_device
from gremlin.clipboard import Clipboard
# from gremlin.input_types import InputType
import dinput 
import uuid
import copy

#from xml.dom import minidom
from lxml import etree as ElementTree


NodeItem = namedtuple("NodeItem","device_name device_guid device_type node")
#_ContainerItem= namedtuple("ContainerItem","device_name device_guid device_type mode input_type input_id input_description container_nodes data")



class ContainerItem():
    ''' holds source profile input staging container data '''
    def __init__(self,
                device_name : str = None,
                device_guid : dinput.GUID = None,
                device_type : DeviceType = None,
                mode: str = None ,
                input_type : InputType = None,
                input_id : int = 0,
                input_description : str = None,
                container_nodes : list = [],
                data = None,
                ):
                 
        self.device_name : str = device_name
        self.device_guid : dinput.GUID = device_guid
        self.device_type : DeviceType = device_type
        self.mode: str = mode
        self.input_type : InputType = input_type
        self.input_id : int = input_id
        self.input_description : str = input_description
        self.container_nodes : list = container_nodes
        self.data = data

def find_dropdown(widget):
    ''' finds the drop down contained by the widget

    :returns: None if not found, or the combobox widget

    '''
    if widget is not None:
        # find the first combo box in the layout
        if not isinstance(widget, QtWidgets.QComboBox):
            # find it
            layout : QtWidgets.QWidget = widget.layout()
            widget = None
            if layout is not None:
                for index in range(layout.count()):
                    w = layout.itemAt(index)
                    if isinstance(w, QtWidgets.QComboBox):
                        widget = w
                        break
    return widget



class AbstractTreeItem():

    def __init__(self):
        super().__init__()
        self._id = gremlin.util.get_guid() # unique ID
        self._selected : bool = True # true if selected for import
        self.selected_widget = None # checkbox associated with this item
        self.map_to_widget = None # map to device widget - holds the mapping information from a drop down - the data member of the widget contains the mapping type
        self.parent = None # parent item

    @property
    def selected(self) -> bool:
        return self._selected

    def get_mapped_item(self):
        ''' returns the mapped_to item

        the map_to_widget is either a combobox or a layout containing a combo box with the selected mapped item

        :returns: the mapped item data, or None if not mapped

        '''
        widget = self.map_to_widget
        return find_dropdown(widget)


    @selected.setter
    def selected(self, value):
        self._selected = value

        if self.selected_widget:
            with QtCore.QSignalBlocker(self.selected_widget):
                self.selected_widget.setChecked(value)

        items = self.selectable_items()
        if items:
            for item in items:
                item.selected = value

    # override in derived classes
    def selectable_items(self):
        return []


    def __hash__(self):
        return hash(self._id)


class ImportContainerItem(AbstractTreeItem):
    ''' holds a single container data '''
    def __init__(self):
        super().__init__()
        self.container_id = None # id of the container
        self.container_type = None  # type of container this is
        self.container_name : str = None
        self.mode : str = None # mode for the container
        self.actions = [] # actions in the container
        self.action_names = [] # action names mapped in the container


    def selectable_items(self):
        return self.actions
    
    def __str__(self):
        return f"Import Container Item: {self.container_name} {self.container_id}"

class ImportInputItem(AbstractTreeItem):
    ''' holds the input data '''
    def __init__(self):
        super().__init__()
        self.device_guid = None # device the input belongs to
        self.input_id : int = 0
        self.input_description : str = None
        self.input_type : InputType = None
        self.input_name : str  = None
        self.mode : str = None # mode for this input
        self.parent_mode : str = None # parent mode
        self.containers : list[ImportContainerItem] = []  # list of ImportContainerItems
        self._selected : bool = True # true if selected for import
        self.data = None # data item

    def selectable_items(self):
        return self.containers


    def __str__(self):
        return f"{self.input_name} [{self.input_id}]"

class ImportModeItem(AbstractTreeItem):
    def __init__(self):
        super().__init__()
        self.mode : str = None # mode
        self.parent_mode : str = None # parent mode, None if no parent
        self.items : list[ImportInputItem] = []
        self.device_guid : dinput.GUID = None

    def selectable_items(self):
        return self.items


class ImportItem(AbstractTreeItem):
    ''' holds container data '''
    def __init__(self):
        super().__init__()
        self.device_name : str = None
        self.device_type : DeviceType = None  
        self.device_guid = None # input GUID
        self.mode_map : dict[str, ImportModeItem ] = {} # map keyed by mode of list of input_items


    def selectable_items(self):
        return list(self.mode_map.values())

class ImportProfileDialog(QtWidgets.QDialog):
    ''' dialog for import options '''


    def __init__(self, profile_path, parent=None):

        super().__init__(parent)

        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        syslog = logging.getLogger("system")

        # get the device information
        self.target_profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile

        # buid list of target devices in the current profile - these are devices that can be imported into
        self.target_devices_map = {}
        self.base_device_map = {}
        
        base_devices = self.target_profile.get_ordered_device_list()
        if len(base_devices) == 0:
            syslog.error("Import error: No mappable devices found in target profile")
            ui_common.MessageBox("Import error:","No mappable devices found in the target profile")
            self.close()
            return
        
        devices = []
        for base_device in base_devices:
            device = gremlin.joystick_handling.device_info_from_guid(base_device.device_guid)
            self.target_devices_map[base_device.device_guid] = device
            devices.append(device)
            self.base_device_map[base_device.device_guid] = base_device
        

     
        
        self._default_info_map = {}
        self._default_axis_map_info = None # holds (device_guid, input_id) default for axis type output 
        self._default_button_map_info = None # holds (device_guid, input_id) default for button type output
        self._default_hat_map_info = None # holds (device_guid, input_id) default for hat type output
        
        device : gremlin.joystick_handling.DeviceSummary
        for device in devices:
            if self._default_axis_map_info is None and not device.is_virtual:
                if device.axis_count > 0:
                    self._default_axis_map_info = (device.device_guid, 0) # default axis
                    self._default_info_map[InputType.JoystickAxis] = self._default_axis_map_info
                if device.button_count > 0:
                    self._default_button_map_info = (device.device_guid, 0) # default button
                    self._default_info_map[InputType.JoystickButton] = self._default_button_map_info
                if device.hat_count > 0:
                    self._default_hat_map_info = (device.device_guid, 0)
                    self._default_info_map[InputType.JoystickHat] = self._default_hat_map_info

        # default keyboard
        self.keyboard_device_guid = keyboard_device.get_keyboard_device_guid()
        self.midi_device_guid = midi_device.get_midi_device_guid()
        self.osc_device_guid = osc_device.get_osc_device_guid()
        self._default_info_map[InputType.Keyboard] = (self.keyboard_device_guid, None)
        self._default_info_map[InputType.KeyboardLatched] = (self.keyboard_device_guid, None)
        self._default_info_map[InputType.Midi] = (self.midi_device_guid, None)
        self._default_info_map[InputType.OpenSoundControl] = (self.keyboard_device_guid, None)


        self.profile_path = profile_path
        self._import_map = {} # import map from the import profile ([device_guid] ImportItems -> [mode] -> ImportInputItems -> [containers list] -> ImportContainerItem
        self._import_mode_list = [] # list of available modes in the import profile
        self._import_mode_selection_map  = {} # map of modes to the import selection - value = true if the mode is selected for import, false otherwise
        self._target_input_item_map = {}  # map of device GUID to available input items for that device - cached as needed
        self._map = {}  # map of source items to their mapped destination
        self._input_items_by_source_device_guid = {} # holds the data for input items based on device GUID
        self._input_device_guid_to_target_device_guid = {} # holds the map of source device guids to target device guid for mapping
        self._input_id_to_target_input_id = {} # map of input id maps keyed by import_item
        self._import_input_items = [] # list of imported input items


        self._tree_root_nodes = []
        self._tree_device_nodes = []
        self._tree_mode_nodes = []
        self._tree_container_nodes = []
        self._tree_input_nodes = []

        # Actual configuration object being managed
        self.config = gremlin.config.Configuration()

        # restore the position
        config = gremlin.config.Configuration()
        data = config.import_window_location
        if data is not None:
            x, y, w, h = data
            self.move(x,y)
            self.resize(w, h)
        


        self._create_ui() # create the dialog UI
        self._load_import_profile() # load and update the ui with the import profile



        # current list of import inputs
        #self._import_model = ImportItemListModel()


    def closeEvent(self, event):
        # save the position
        config = gremlin.config.Configuration()
        data = [self.pos().x(), self.pos().y(), self.size().width(), self.size().height()]
        config.import_window_location = data

    def _create_ui(self):
        from gremlin.ui import ui_common
        self.setMinimumWidth(600)

        self.main_layout = QtWidgets.QVBoxLayout(self)

        # path section
        self.container_path_widget = QtWidgets.QWidget()
        self.container_path_widget.setContentsMargins(0,0,0,0)
        self.container_path_layout = QtWidgets.QHBoxLayout(self.container_path_widget)
        self.container_path_layout.setContentsMargins(0,0,0,0)

        self.path_widget = ui_common.QPathLineItem("Profile source:",self.profile_path)
        self.path_widget.pathChanged.connect(self._load_import_profile)

        self.container_path_layout.addWidget(self.path_widget)
        self.container_path_layout.addStretch()

        # import options
        self.container_options_widget = QtWidgets.QWidget()
        self.container_options_widget.setContentsMargins(0,0,0,0)
        self.container_options_layout = QtWidgets.QHBoxLayout(self.container_options_widget)
        self.container_options_layout.setContentsMargins(0,0,0,0)


        self.container_mode_widget = QtWidgets.QWidget()
        self.container_mode_widget.setContentsMargins(0,0,0,0)
        self.container_mode_layout = QtWidgets.QHBoxLayout(self.container_mode_widget)
        self.container_mode_layout.setContentsMargins(0,0,0,0)


        self.create_mode_widget = QtWidgets.QCheckBox("Import modes")
        self.target_mode_label_widget = QtWidgets.QLabel("Target Mode:")

        self.target_mode_selector = ui_common.QComboBox()
        # populate the modes of the current device being imported into
        self.populate_mode_selector(self.target_mode_selector, self.target_profile)

        self.import_modes_widget = QtWidgets.QRadioButton("Import All Modes")
        self.import_modes_widget.setToolTip("Import all modes from profile and add them to the existing profile if they don't exist")
        self.import_single_mode_widget = QtWidgets.QRadioButton("Import single mode")
        self.import_single_mode_widget.setToolTip("Import specific mode")
        self.import_mode_selector = ui_common.QComboBox()

        self.import_mode_list_widget = QtWidgets.QListWidget()

        self.import_modes_widget.setChecked(True)
        self.import_modes_widget.clicked.connect(self._update_mode_options)
        self.import_single_mode_widget.clicked.connect(self._update_mode_options)
        self._update_mode_options()

        # mapping container

        self.import_input_tree_widget = QtWidgets.QTreeWidget()
        self.container_mappings_widget = QtWidgets.QWidget()
        self.container_mappings_widget.setContentsMargins(0,0,0,0)
        self.container_mappings_layout = QtWidgets.QVBoxLayout(self.container_mappings_widget)
        self.container_mappings_layout.setContentsMargins(0,0,0,0)


        self.import_input_list_widget = QtWidgets.QListWidget() # selection of inputs to import
        #self.import_input_list_widget.setModel(self._import_model)
        # self.container_mappings_layout.addWidget(self.import_input_list_widget,0,0)
        self.container_mappings_layout.addWidget(self.import_input_tree_widget)

        # header buttons
        self.container_command_header_widget = QtWidgets.QWidget()
        self.container_command_header_widget.setContentsMargins(0,0,0,0)
        self.container_command_header_layout = QtWidgets.QHBoxLayout(self.container_command_header_widget)
        self.container_command_header_layout.setContentsMargins(0,0,0,0)

        self.command_one_to_one_button_widget = QtWidgets.QPushButton("Map 1:1")
        self.command_one_to_one_button_widget.setToolTip("Maps inputs to outputs 1:1 if the input exists in the output.<br>If the output doesn't exist, the first available slot to import to will be used.")
        self.command_one_to_one_button_widget.clicked.connect(self._cmd_one_to_one)


        self.command_deselect_all_button_widget = QtWidgets.QPushButton("Select None")
        self.command_deselect_all_button_widget.setToolTip("Deselects all imports")
        self.command_deselect_all_button_widget.clicked.connect(self._cmd_deselect_all)


        self.command_select_all_button_widget = QtWidgets.QPushButton("Select All")
        self.command_select_all_button_widget.setToolTip("Selects all imports")
        self.command_select_all_button_widget.clicked.connect(self._cmd_select_all)



        width = ui_common.get_text_width("MMMM")

        # cmd_resize = QtWidgets.QPushButton("Resize")
        # cmd_resize.clicked.connect(self._resize_map)


        self.command_level_1_button_widget = QtWidgets.QPushButton("L1")
        self.command_level_1_button_widget.setToolTip("Expand/Collapse to Devices")
        self.command_level_1_button_widget.clicked.connect(lambda: self._cmd_set_level(1))
        self.command_level_1_button_widget.setMaximumWidth(width)

        self.command_level_2_button_widget = QtWidgets.QPushButton("L2")
        self.command_level_2_button_widget.setToolTip("Expand/Collapse to Modes")
        self.command_level_2_button_widget.clicked.connect(lambda: self._cmd_set_level(2))
        self.command_level_2_button_widget.setMaximumWidth(width)

        self.command_level_3_button_widget = QtWidgets.QPushButton("L3")
        self.command_level_3_button_widget.setToolTip("Expand/Collapse to Inputs")
        self.command_level_3_button_widget.clicked.connect(lambda: self._cmd_set_level(3))
        self.command_level_3_button_widget.setMaximumWidth(width)

        self.command_level_4_button_widget = QtWidgets.QPushButton("L4")
        self.command_level_4_button_widget.setToolTip("Expand/Collapse to Containers")
        self.command_level_4_button_widget.clicked.connect(lambda: self._cmd_set_level(4))
        self.command_level_4_button_widget.setMaximumWidth(width)


        self.container_command_header_layout.addWidget(self.command_one_to_one_button_widget)
        self.container_command_header_layout.addWidget(self.command_select_all_button_widget)
        self.container_command_header_layout.addWidget(self.command_deselect_all_button_widget)
        self.container_command_header_layout.addStretch()
        # self.container_command_header_layout.addWidget(cmd_resize)
        self.container_command_header_layout.addWidget(self.command_level_1_button_widget)
        self.container_command_header_layout.addWidget(self.command_level_2_button_widget)
        self.container_command_header_layout.addWidget(self.command_level_3_button_widget)
        self.container_command_header_layout.addWidget(self.command_level_4_button_widget)



        # buttons
        self.container_buttons_widget = QtWidgets.QWidget()
        self.container_buttons_widget.setContentsMargins(0,0,0,0)
        self.container_buttons_layout = QtWidgets.QHBoxLayout(self.container_buttons_widget)
        self.container_buttons_layout.setContentsMargins(0,0,0,0)

        self.import_button_widget = QtWidgets.QPushButton("Import")
        self.import_button_widget.setToolTip("Imports the mapped items into the current profile")
        self.import_button_widget.clicked.connect(self._execute_import)
        self.close_button_widget = QtWidgets.QPushButton("Close")
        self.close_button_widget.setToolTip("Closes the dialog")
        self.close_button_widget.clicked.connect(self._close_cb)

        self.container_buttons_layout.addStretch()
        self.container_buttons_layout.addWidget(self.import_button_widget)
        self.container_buttons_layout.addWidget(self.close_button_widget)

        self.container_mode_layout.addWidget(self.create_mode_widget)
        self.container_mode_layout.addWidget(self.target_mode_label_widget)
        self.container_mode_layout.addWidget(self.import_modes_widget)
        self.container_mode_layout.addWidget(self.import_single_mode_widget)
        self.container_mode_layout.addWidget(self.import_mode_selector)
        # self.container_mode_layout.addWidget(self.import_mode_list_widget)


        self.main_layout.addWidget(self.container_path_widget)
        self.main_layout.addWidget(self.container_command_header_widget)
        self.main_layout.addWidget(self.container_mappings_widget)
        self.main_layout.addWidget(self.container_buttons_widget)


    def _create_nodata_input_item(self):
        ''' creates a no data node for the input list '''
        item = ImportInputItem()
        item.input_description = "No input found"
        item.input_name = "No data"
        item.input_id = 0
        return item

    @property
    def current_import_mode(self):
        ''' current import mode selected '''
        return self.import_mode_selector.currentText()

    @property
    def current_import_device(self):
        ''' current import device '''
        if not self.source_profile:
            return None
        return self.source_device_selector.currentData()

    def _get_subtree_nodes(self, tree_widget_item):
        """Returns all QTreeWidgetItems in the subtree rooted at the given node."""
        nodes = []
        nodes.append(tree_widget_item)
        for i in range(tree_widget_item.childCount()):
            nodes.extend(self._get_subtree_nodes(tree_widget_item.child(i)))
        return nodes

    def _get_tree_items(self, widget):
        """ gets all tree widgets in the given tree"""
        nodes = []
        for index in range(widget.topLevelItemCount()):
            top_item = widget.topLevelItem(index)
            nodes.extend(self._get_subtree_nodes(top_item))
        return nodes

    def _update_ui(self):
        ''' updates the UI based on the profiles '''


        # populate the modes for the target
        #self.populate_mode_selector(self.import_mode_selector, self.source_profile)

        # update selectable import mode list
        self._device_change_cb()


    def _update_mode_options(self):
        ''' updates the mode options based on what is selected '''
        source_mode_enabled = self.import_single_mode_widget.isChecked()
        self.import_mode_selector.setVisible(source_mode_enabled)

        target_mode_enabled = self.create_mode_widget.isChecked()
        self.target_mode_selector.setEnabled(target_mode_enabled)
        self.target_mode_label_widget.setEnabled(target_mode_enabled)



    @QtCore.Slot()
    def _close_cb(self):
        gremlin.shared_state.ui.refresh()
        self.close()

    @QtCore.Slot()
    def _device_change_cb(self):
        ''' called when device selection changes'''

        # update selectable import mode list
        self._update_import_mode_list()

        # update input list
        self._update_map()


    def populate_mode_selector(self, selector : ui_common.QDataComboBox, profile : gremlin.base_profile.Profile):
        ''' populates profile modes for the specified profile

        :param: selector = the combo box to populate (will be cleared)
        :param: profile = the profile to load modes from

        '''
        while selector.count() > 0:
            selector.removeItem(0)

        mode_list = profile.get_modes()
        self.mode_list = [x[1] for x in mode_list]
        # Create mode name labels visualizing the tree structure
        inheritance_tree = profile.build_inheritance_tree()
        labels = []
        self._inheritance_tree_to_labels(labels, inheritance_tree, 0)

        # Filter the mode names such that they only occur once below
        # their correct parent
        mode_names = []
        display_names = []
        for entry in labels:
            if entry[0] in mode_names:
                idx = mode_names.index(entry[0])
                if len(entry[1]) > len(display_names[idx]):
                    del mode_names[idx]
                    del display_names[idx]
                    mode_names.append(entry[0])
                    display_names.append(entry[1])
            else:
                mode_names.append(entry[0])
                display_names.append(entry[1])

        # Add properly arranged mode names to the drop down list
        index = 0
        for display_name, mode_name in zip(display_names, mode_names):
            selector.addItem(display_name, mode_name)
            self.mode_list.append(mode_name)
            index += 1


    def _inheritance_tree_to_labels(self, labels, tree, level):
        """Generates labels to use in the dropdown menu indicating inheritance.

        :param labels the list containing all the labels
        :param tree the part of the tree to be processed
        :param level the indentation level of this tree
        """
        for mode, children in sorted(tree.items()):
            labels.append((mode,
                f"{"  " * level}{"" if level == 0 else " "}{mode}"))
            self._inheritance_tree_to_labels(labels, children, level+1)

    def _get_input_name(self, input_type: InputType, input_id):
        if input_type == InputType.JoystickAxis:
            return f"Axis {input_id}"
        elif input_type == InputType.JoystickButton:
            return f"Button {input_id}"
        elif input_type == InputType.JoystickHat:
            return f"Hat {input_id}"
        elif input_type == InputType.Keyboard:
            return f"Key {input_id}"
        elif input_type == InputType.KeyboardLatched:
            return f"KeyEx {input_id}"
        elif input_type == InputType.Midi:
            return f"MIDI {input_id}"
        elif input_type == InputType.OpenSoundControl:
            return f"OSC {input_id}"
        return f"unknown: {input_type} {input_id}"


    def _load_import_profile(self):
        ''' imports a profile to the specified target device ID matching by name

        :param: device_guid  the device to import to
        :path: the xml to import
        '''


        syslog = logging.getLogger("system")


        self.source_profile = gremlin.base_profile.Profile()
        self.source_profile.from_xml(self.profile_path)
        
        # read the xml
        tree = ElementTree.parse(self.profile_path)
        self.root = tree.getroot()

        # load the modes hierarchy for the source profile
        self.source_mode_tree = self.source_profile.mode_tree()

        # get all the device entries matching what we're looking for - by name or by GUID

        device_mode_pairs = [] # holds the list of seen device / mode pairs in case there are duplicates in an incorrect profile
        self._import_map = {}
        self._import_mode_item_map = {} # map of import items keyed by device guid
        self._input_items_by_source_device_guid = {}

        verbose = gremlin.config.Configuration().verbose
        syslog = logging.getLogger("system")

        item_list = []
        node_devices = self.root.xpath("//device")
        for node in node_devices:
            node_name = node.get("name")
            node_guid = gremlin.util.parse_guid(node.get("device-guid"))
            node_type = DeviceType.to_enum(node.get("type"))

            # node entry matches GUID or name
            item = NodeItem(node_name, node_guid, node_type, node)
            item_list.append(item)


        # map input profile modes and hiearchy
        mode_nodes = self.root.xpath("//device/mode")
        discovered_modes = set()
        self.parent_mode_map = {}
        for node_mode in mode_nodes:
            mode = node_mode.get("name")
            discovered_modes.add(mode)
            if "inherit" in node_mode.attrib:
                parent_mode = node_mode.get("inherit")
            else:
                parent_mode = None
            self.parent_mode_map[mode] = parent_mode
           
        
        import_list = []
        midi_index = 0
        osc_index = 0
        keyboard_index = 0
        item : NodeItem
        
        for item in item_list:
            node = item.node
            # get modes
            node_modes = gremlin.util.get_xml_child(node,"mode",True)
            for node_mode in node_modes:
                mode = node_mode.get("name")
                parent_mode = self.parent_mode_map[mode]
                
                import_mode_item = ImportModeItem()
                import_mode_item.mode = mode
                import_mode_item.parent_mode = parent_mode
                if not item.device_guid in self._import_mode_item_map:
                    self._import_mode_item_map[item.device_guid] = {}
                self._import_mode_item_map[item.device_guid][mode] = import_mode_item

                dm_pair = (item.device_guid, mode)
                if dm_pair in device_mode_pairs:
                    syslog.warning(f"Found duplicated device/mode entries in import profile - only the fist entry will be used: device {item.device_name} ID: {item.device_guid}")
                    continue
                device_mode_pairs.append(dm_pair)
                # read all mode node children - these are all the inputs by input type
                for node_input in node_mode:
                    node_containers = gremlin.util.get_xml_child(node_input,"container",multiple=True)
                    input_description = ""
                    if len(node_containers) == 0:
                        # no mapping - skip node
                        # if verbose:
                        #     syslog.info(f"Import: Device: {item.device_name} Skip input {node_input.tag} - no source container found")
                        continue
                    if node_input.tag == "axis":
                        # axis node
                        input_id = safe_read(node_input,"id",int, 0)
                        if "description" in node_input.attrib:
                            input_description = safe_read(node_input,"description",str,"")
                        data = ContainerItem(device_name=item.device_name,
                                            device_guid=item.device_guid,
                                            device_type=item.device_type,
                                            mode = mode,
                                            input_type = InputType.JoystickAxis,
                                            input_description = input_description,
                                            input_id=input_id,
                                            container_nodes = node_containers
                                            )
                        import_list.append(data)
                        

                    elif node_input.tag == "button":
                        # button node
                        input_id = safe_read(node_input,"id",int, 0)
                        if "description" in node_input.attrib:
                            input_description = safe_read(node_input,"description",str,"")
                        data = ContainerItem(device_name=item.device_name,
                                            device_guid=item.device_guid,
                                            device_type=item.device_type,
                                            mode = mode,
                                            input_type = InputType.JoystickButton,
                                            input_description = input_description,
                                            input_id=input_id,
                                            container_nodes = node_containers
                                            )
                        import_list.append(data)


                    elif node_input.tag == "hat":
                        # button node
                        input_id = safe_read(node_input,"id",int, 0)
                        if "description" in node_input.attrib:
                            input_description = safe_read(node_input,"description",str,"")
                        data = ContainerItem(device_name=item.device_name,
                                            device_guid=item.device_guid,
                                            device_type=item.device_type,
                                            mode = mode,
                                            input_type = InputType.JoystickHat,
                                            input_description = input_description,
                                            input_id=input_id,
                                            container_nodes = node_containers
                                            )
                        import_list.append(data)
                    elif node_input.tag in("keyboard","keylatched"):
                        keyboard_input_item = keyboard_device.KeyboardInputItem()
                        child_input_node = gremlin.util.get_xml_child(node_input,"input")
                        if "guid" in child_input_node.attrib:
                            input_id = gremlin.util.read_guid(child_input_node, "guid", default_value=uuid.uuid4())
                        else:
                            entries = self.source_profile.devices[import_item.device_guid].modes[mode].config[InputType.KeyboardLatched]
                            input_id = entries[keyboard_index].id
                        keyboard_index += 1                        
                        keyboard_input_item.parse_xml(child_input_node)
                        keyboard_input_item.id = input_id
                        if verbose:
                            syslog.info(f"Import: read KeyboardLatched node {input_id}")
                        if "description" in child_input_node.attrib:
                            input_description = safe_read(child_input_node,"description",str,"")
                        data = ContainerItem(device_name=item.device_name,
                                            device_guid=item.device_guid,
                                            device_type=item.device_type,
                                            mode = mode,
                                            input_type = InputType.KeyboardLatched,
                                            input_description = input_description,
                                            input_id=input_id,
                                            container_nodes = node_containers,
                                            data = keyboard_input_item
                                            )
                        import_list.append(data)

                    elif node_input.tag == "midi":

                        midi_input_item = midi_device.MidiInputItem()
                        child_input_node = gremlin.util.get_xml_child(node_input,"input")
                        if "guid" in child_input_node.attrib:
                            input_id = gremlin.util.read_guid(child_input_node, "guid", default_value=uuid.uuid4())
                        else:
                            entries = self.source_profile.devices[import_item.device_guid].modes[mode].config[InputType.Midi]
                            input_id = entries[midi_index].id
                        midi_index += 1
                        midi_input_item.parse_xml(child_input_node)
                        midi_input_item.id = input_id
                        if verbose:
                            syslog.info(f"Import: read MIDI node {input_id}")
                        if "description" in child_input_node.attrib:                            
                            input_description = safe_read(child_input_node,"description",str,"")
                        data = ContainerItem(device_name=item.device_name,
                                            device_guid=item.device_guid,
                                            device_type=item.device_type,
                                            mode = mode,
                                            input_type = InputType.Midi,
                                            input_description = input_description,
                                            input_id=input_id,
                                            container_nodes = node_containers,
                                            data = midi_input_item
                                            )
                        import_list.append(data)
                    elif node_input.tag == "osc":
                        osc_input_item = osc_device.OscInputItem()
                        child_input_node = gremlin.util.get_xml_child(node_input,"input")
                        if "guid" in child_input_node.attrib:
                            input_id = gremlin.util.read_guid(child_input_node, "guid", default_value=uuid.uuid4())
                        else:
                            entries = self.source_profile.devices[import_item.device_guid].modes[mode].config[InputType.OpenSoundControl]
                            input_id = entries[osc_index].id
                        osc_index += 1
                        osc_input_item.parse_xml(child_input_node)
                        osc_input_item.id = input_id
                        if "description" in child_input_node.attrib:                            
                            input_description = safe_read(child_input_node,"description",str,"")                        
                        if verbose:
                            syslog.info(f"Import: read OSC node {input_id}")
                        data = ContainerItem(device_name=item.device_name,
                                            device_guid=item.device_guid,
                                            device_type=item.device_type,
                                            mode = mode,
                                            input_type = InputType.OpenSoundControl,
                                            input_description = input_description,
                                            input_id=input_id,
                                            container_nodes = node_containers,
                                            data = osc_input_item
                                            )
                        import_list.append(data)


        if not import_list:
            syslog.warning(f"Import profile: warning: no data found")
            return



        # process each container and add to the target

        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        container_tag_map = container_plugins.tag_map
        mode_list = []

        item : ContainerItem

        for item in import_list:
            nodes = item.container_nodes
            input_id = item.input_id
            input_type = item.input_type
            input_description = item.input_description
            mode = item.mode
            parent_mode =  self.parent_mode_map[mode]


            if not mode in mode_list:
                mode_list.append(mode)

            # import (device) node - parents to nothing
            if not item.device_guid in self._import_map.keys():
                import_item = ImportItem()
                import_item.device_name = item.device_name
                import_item.device_guid = item.device_guid
                import_item.device_type = item.device_type
                import_item.input_id = input_id
                import_item.input_type = input_type
                import_item.input_description = input_description
                self._import_map[item.device_guid] = import_item
                import_item.parent = None

            else:
                import_item = self._import_map[item.device_guid]

            # mode node - parents to import (device) node
            if not mode in import_item.mode_map.keys():
                import_mode_item = ImportModeItem()
                import_mode_item.mode = mode
                import_mode_item.parent_mode = parent_mode
                import_mode_item.parent = import_item
                import_item.mode_map[mode] = import_mode_item
            else:
                import_mode_item = import_item.mode_map[mode]
            
            # input node - parents to mode node
            import_input_item = ImportInputItem()
            import_input_item.input_id = input_id
            import_input_item.input_description = input_description
            import_input_item.input_type = input_type

            if input_type in (InputType.Midi, InputType.OpenSoundControl, InputType.Keyboard, InputType.KeyboardLatched):
                import_input_item.input_name = f"{InputType.to_display_name(input_type)} {item.data.display_name}" 
            else:
                import_input_item.input_name = self._get_input_name(import_input_item.input_type, import_input_item.input_id)
            
            import_input_item.mode = mode
            import_input_item.data = item.data

            import_input_item.device_guid = import_item.device_guid
            if not import_item.device_guid in self._input_items_by_source_device_guid.keys():
                self._input_items_by_source_device_guid[import_item.device_guid] = [] # create list of ImportInputItems for that specific import device so we can find them easily
            self._input_items_by_source_device_guid[import_item.device_guid].append(import_input_item)

            import_mode_item.items.append(import_input_item)

            import_input_item.parent = import_mode_item

            profile_input_item = gremlin.base_profile.InputItem()
            profile_input_item._input_type = input_type
            profile_input_item._device_guid = import_item.device_guid
            profile_input_item._input_id = input_id
            self._import_input_items.append(profile_input_item)

            for index, node in enumerate(nodes):
                container_type = node.get("type")
                if container_type not in container_tag_map:
                    syslog.warning(f"\t\tUnknown container type used: {container_type}")
                    continue


                container = container_tag_map[container_type](profile_input_item)
                container.from_xml(node)

                # check for old profile format without container IDs - if not set - we need to find it from the profile so the generated IDs are in sync
                # the logical question is: why don't we just use that "loaded" profile to start with - the answer is - malformed XML profiles that have double entries and other old stuff in them a new profile would not load
                container_id = container.id
                if not "container_id" in node.attrib:
                    try:
                        
                        items = self.source_profile.devices[import_item.device_guid].modes[mode].config[input_type]
                        for key in items.keys():
                            if key == input_id:
                                containers = items[key].containers
                                container_id = containers[index].id
                                break

                        #containers = self.source_profile.devices[import_item.device_guid].modes[mode].config[input_type][input_id].containers
                        
                    except:
                        # not found - use the default ID
                        pass

                # container node - parents to input node
                import_container_item = ImportContainerItem()
                import_container_item.container_id = container_id
                import_container_item.container_name = container.name
                import_container_item.container_type = container_type
                import_container_item.parent = import_input_item
                import_container_item.mode = mode
                

                profile_input_item.containers.append(container)

                syslog.info(f"\tContainer: {container.tag} {container.id}")
                for action_set in container.action_sets:
                    for action in action_set:
                        syslog.info(f"\t\t\tImported container: {action.name} {action.display_name()}")
                        import_container_item.actions.append(action)
                        import_container_item.action_names.append(action.display_name())

                import_input_item.containers.append(import_container_item)




        # update the modes that have containers to import
        self._import_mode_list = mode_list

        syslog.info(f"Import modes with defined actions: {len(mode_list)}")
        for mode in mode_list:
            syslog.info(f"\t{mode}")



        self._update_ui() # refresh the ui with the source profile data

    def _update_import_mode_list(self):
        ''' updates the mode selection list '''
        self.import_mode_list_widget.clear()
        for mode in self._import_mode_list:
            item = QtWidgets.QListWidgetItem()
            self.import_mode_list_widget.addItem(item)
            widget = QtWidgets.QCheckBox(text=mode)
            widget.clicked.connect(self._import_mode_selection_cb)
            self.import_mode_list_widget.setItemWidget(item, widget)

    def _resize_map(self):
        ''' resize tree headers '''
        tree = self.import_input_tree_widget
        header = tree.header() # QHeaderView
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)


    def _find_target(self, source_device_guid : dinput.GUID,  device_guid : dinput.GUID, input_type : InputType, input_id) -> tuple:
        '''' gets at target guid and target input id for the requested input type
        : returns : (target_device_guid, target_input_id) 
          
            '''
        if device_guid in self.target_devices_map:
            target_device_guid = device_guid
            target_device = self.target_devices_map[device_guid]
        else:
            target_device_guid, input_id = self._default_info_map[input_type]
            target_device = self.target_devices_map[device_guid]


        if source_device_guid in self._input_device_guid_to_target_device_guid:
            target_device_guid = self._input_device_guid_to_target_device_guid[source_device_guid]

        match input_type:
            case InputType.JoystickAxis:
                if target_device.axis_count == 0:
                    # problem - change to the first target that has an axis
                    target_device_guid, input_id = self._default_info_map[input_type]
                
                if target_device.axis_count <= input_id:
                    target_input_id = 0
                else:
                    target_input_id = input_id
            case InputType.JoystickButton:
                if target_device.button_count == 0:
                    target_device_guid, input_id = self._default_info_map[input_type]
                if target_device.button_count <= input_id:
                    target_input_id = 0
                else:
                    target_input_id = input_id
            case InputType.JoystickHat:
                if target_device.hat_count == 0:
                    target_device_guid, input_id = self._default_info_map[input_type]
                if target_device.hat_count <= input_id:
                    target_input_id = 0
                else:
                    target_input_id = input_id
            case _:
                # all others
                target_input_id = input_id
                    
        return target_device_guid, target_input_id
            
                                
    def _update_map(self):
        ''' updates the mappings source to target '''

        self._map = {} # clear and rebuild the map

        tree = self.import_input_tree_widget
        with QtCore.QSignalBlocker(tree):
            tree.clear()
            tree.setColumnCount(4)
            tree.setHeaderLabels(["Device","Actions","Map To",""])
            
            
            syslog = logging.getLogger("system")

            self._tree_device_nodes = []
            self._tree_mode_nodes = []
            self._tree_container_nodes = []
            self._tree_input_nodes = []


            root_node = QtWidgets.QTreeWidgetItem(["Importable items"])
            self._tree_root_nodes = [root_node]
            tree.addTopLevelItem(root_node)

            import_item : ImportItem

            for import_item in self._import_map.values():

                source_device_guid = import_item.device_guid

                container_widget = QtWidgets.QWidget()
                container_widget.setContentsMargins(0,0,0,0)
                container_layout = QtWidgets.QHBoxLayout(container_widget)
                container_layout.setContentsMargins(0,0,0,0)

                device_node = QtWidgets.QTreeWidgetItem()
                device_node.setData(0,0, import_item)
                self._tree_device_nodes.append(device_node)
                root_node.addChild(device_node)

                cb = ui_common.QDataCheckbox(f"{import_item.device_name}")
                cb.data = import_item
                import_item.selected_widget = cb
                cb.setChecked(import_item.selected)
                cb.clicked.connect(self._select_import_item_cb)

                container_layout.addWidget(cb)
                # container_layout.addWidget(QtWidgets.QLabel(f"[{import_item.device_guid}]"))
                container_layout.addStretch()

                map_to_widget, target_widget = self._create_target_selection_widget(import_item.device_type)
                
                target_widget.data = import_item  # indicate which import_item holds this device mapping
                import_item.map_to_widget = target_widget

                self._map[import_item] = target_widget

                tree.setItemWidget(device_node, 0, container_widget)
                tree.setItemWidget(device_node, 2, map_to_widget)

                mode_item: ImportModeItem
                for mode_item in import_item.mode_map.values():

                
                    mode_node = QtWidgets.QTreeWidgetItem()
                    mode_node.setData(0,0,mode_item)
                    self._tree_mode_nodes.append(mode_node)

                    container_widget = QtWidgets.QWidget()
                    container_widget.setContentsMargins(0,0,0,0)
                    container_layout = QtWidgets.QHBoxLayout(container_widget)
                    container_layout.setContentsMargins(0,0,0,0)

                    map_to_widget, mode_widget = self._create_target_mode_widget()
                    mode_item.map_to_widget = mode_widget
                    mode_widget.data = mode_item
                    mode_index = mode_widget.findData(mode_item.mode)
                    if mode_index != -1:
                        mode_widget.setCurrentIndex(mode_index)
                    

                    cb = ui_common.QDataCheckbox(f"Mode: [{mode_item.mode}]")
                    cb.data = mode_item
                    mode_item.selected_widget = cb
                    cb.setChecked(import_item.selected)
                    cb.clicked.connect(self._select_import_item_cb)
                    device_node.addChild(mode_node)

                    container_layout.addWidget(cb)
                    container_layout.addStretch()

                    tree.setItemWidget(mode_node, 0, container_widget)
                    tree.setItemWidget(mode_node, 2, map_to_widget)
                    self._map[mode_item] = mode_widget

                    input_item : ImportInputItem
                    for input_item in mode_item.items:

                        # derive the target device
                        if not input_item.input_type in self._default_info_map:
                            syslog.warning(f"Import: unable to map {input_item.input_type} - no matching suitable device found ")
                            continue

                        default_target_device_guid, default_target_input_id = self._default_info_map[input_item.input_type ]

                        # if not import_item.device_guid in self._input_device_guid_to_target_device_guid:
                        #     data : import_item = widget.data
                        #     target_device_guid = widget.data.device_guid
                        #     self._input_device_guid_to_target_device_guid[import_item.device_guid] = target_device_guid
                        # else:
                        #     target_device_guid = self._input_device_guid_to_target_device_guid[import_item.device_guid]

                        # if target_device_guid is not None:
                        #     device = self.target_devices_map[target_device_guid] # device of the target device
                        #     index = widget.findData(device) # index in the drop down
                        #     if index == -1:
                        #         # selector error - the target is not found
                        #         syslog.error(f"Import: unable to map {input_item.input_type} - target device {target_device_guid} not populated in available device dropdown")
                        #         continue

    
                        # derive the target input

                        target_device_guid, target_input_id = self._find_target(source_device_guid, default_target_device_guid, input_item.input_type, input_item.input_id)
                        if target_device_guid is None:
                            target_device_guid = default_target_device_guid
                        if target_input_id is None:
                            target_device_guid = default_target_device_guid
                            target_input_id = default_target_input_id


                        self._input_device_guid_to_target_device_guid[source_device_guid] = target_device_guid
                        base_device = self.base_device_map[target_device_guid]
                        index = target_widget.findData(base_device)
                        with QtCore.QSignalBlocker(target_widget):
                                target_widget.setCurrentIndex(index)

      
                        input_node = QtWidgets.QTreeWidgetItem()
                        input_node.setData(0,0,input_item)
                        self._tree_input_nodes.append(input_node)

                        container_widget = QtWidgets.QWidget()
                        container_widget.setContentsMargins(0,0,0,0)
                        container_layout = QtWidgets.QHBoxLayout(container_widget)
                        container_layout.setContentsMargins(0,0,0,0)

                        cb = ui_common.QDataCheckbox(f"Input: {input_item.input_name}")
                        cb.data = input_item
                        input_item.selected_widget = cb
                        cb.clicked.connect(self._select_import_item_cb)
                        cb.setChecked(input_item.selected)
                        mode_node.addChild(input_node)

                        container_layout.addWidget(cb)
                        container_layout.addStretch()

                        map_to_input_widget, widget = self._create_target_input_widget(import_item, input_item, target_device_guid, target_input_id)

                        tree.setItemWidget(input_node, 0, container_widget)
                        if map_to_input_widget is not None:
                            tree.setItemWidget(input_node, 2, map_to_input_widget)

                        input_item.map_to_widget = widget
                        self._map[input_item] = widget

                        for container_item in input_item.containers:

                            container_node = QtWidgets.QTreeWidgetItem()
                            container_node.setData(0,0,container_item)
                            self._tree_container_nodes.append(container_node)
                            cb = ui_common.QDataCheckbox(f"Container: {container_item.container_name}")
                            cb.data = container_item
                            container_item.selected_widget = cb
                            cb.clicked.connect(self._select_import_item_cb)
                            cb.setChecked(container_item.selected)
                            input_node.addChild(container_node)


                            container_widget = QtWidgets.QWidget()
                            container_widget.setContentsMargins(0,0,0,0)
                            container_layout = QtWidgets.QHBoxLayout(container_widget)
                            container_layout.setContentsMargins(0,0,0,0)

                            container_layout.addWidget(cb)
                            container_layout.addStretch()

                            tree.setItemWidget(container_node, 0, container_widget)


                            # icons for the items
                            container_widget = QtWidgets.QWidget()
                            container_widget.setContentsMargins(0,0,0,0)
                            container_layout = QtWidgets.QHBoxLayout(container_widget)
                            container_layout.setContentsMargins(0,0,0,0)

                            #container_layout.addWidget(QtWidgets.QLabel("Actions:"))

                            for action in container_item.actions:
                                al = ui_common.ActionLabel(action)
                                al.setToolTip(action.display_name())
                                container_layout.addWidget(al)
                            container_layout.addStretch()


                            tree.setItemWidget(container_node, 1, container_widget)


            # set tree expansion level to the last selected level
            self._cmd_set_level(gremlin.config.Configuration().import_level)
            self._resize_map()


    def _find_map_item(self, widget):
        ''' finds which map item has the given widget as an output map widget

        :widget: the target mapped widget

        '''
        item = next((item for item in self._map.keys() if item.map_to_widget == widget), None)
        return item

    def _create_target_selection_widget(self, device_type):
        ''' create a combo box for the target '''

        container_widget = QtWidgets.QWidget()
        container_widget.setContentsMargins(0,0,0,0)
        container_layout = QtWidgets.QHBoxLayout(container_widget)
        container_layout.setContentsMargins(0,0,0,0)
        widget = ui_common.QDataComboBox()
        # limit drop down size
        widget.setMaxVisibleItems(20)
        widget.setStyleSheet("QComboBox { combobox-popup: 0; }")

        container_layout.addWidget(widget)
        assert len(self.base_device_map) > 0

        for device in self.base_device_map.values():
            if device.type == device_type:
                widget.addItem(device.name, device)
                

        widget.currentIndexChanged.connect(self._target_device_changed)
        return container_widget, widget

    def _create_target_mode_widget(self):
        ''' create a combo box for the mode mapping '''

        container_widget = QtWidgets.QWidget()
        container_widget.setContentsMargins(0,0,0,0)
        container_layout = QtWidgets.QHBoxLayout(container_widget)
        container_layout.setContentsMargins(0,0,0,0)
        widget = ui_common.QDataComboBox()
        container_layout.addWidget(widget)
        # limit drop down size
        widget.setMaxVisibleItems(20)
        widget.setStyleSheet("QComboBox { combobox-popup: 0; }")


        self.populate_mode_selector(widget, self.source_profile)

        return container_widget, widget

    def _create_target_input_widget(self, source_import_item : ImportItem, source_input_item : ImportInputItem, target_device_guid : dinput.GUID, target_input_id : int):
        ''' create a combo box for the mode mapping '''

        source_input_type = source_input_item.input_type
        if source_input_type == InputType.Keyboard:
            source_input_type = InputType.KeyboardLatched # move to GremlinEX keyboard device


        if not target_device_guid in self._target_input_item_map.keys():
            items = {} # map of possible target input items keyed by input type
            for _, input_type in enumerate(InputType):
                items[input_type] = []

                # build the list of target inputs
                if input_type == InputType.KeyboardLatched:
                    # keyboard input - single device
                    item = ImportInputItem()
                    item.input_type = input_type
                    item.device_guid = keyboard_device.get_keyboard_device_guid()
                    item.input_name = source_input_item.input_name
                    items[input_type].append(item)
                elif input_type == InputType.Midi:
                    # midi input - single device
                    item = ImportInputItem()
                    item.input_type = input_type
                    item.device_guid = midi_device.get_midi_device_guid()
                    item.input_name = source_input_item.input_name
                    items[input_type].append(item)
                elif input_type == InputType.OpenSoundControl:
                    # OSC input - single device
                    item = ImportInputItem()
                    item.input_type = input_type
                    item.device_guid = osc_device.get_osc_device_guid()
                    item.input_name = source_input_item.input_name
                    items[input_type].append(item)

                elif input_type == InputType.JoystickAxis:
                    info : gremlin.joystick_handling.DeviceSummary = gremlin.joystick_handling.device_info_from_guid(target_device_guid)
                    if info is not None:
                        # only create axis outputs that exist on the device
                        for index in range(info.axis_count):
                            item = ImportInputItem()
                            item.input_id = index + 1
                            item.input_type = input_type
                            item.input_name = self._get_input_name(item.input_type, item.input_id)
                            item.device_guid = target_device_guid
                            items[input_type].append(item)
                        
                elif input_type == InputType.JoystickButton:                        
                    info : gremlin.joystick_handling.DeviceSummary = gremlin.joystick_handling.device_info_from_guid(target_device_guid)
                    # only create button outputs that exist on the device
                    if info is not None:
                        for index in range(info.button_count):
                            item = ImportInputItem()
                            item.input_id = index + 1
                            item.input_type = input_type
                            item.input_name = self._get_input_name(item.input_type, item.input_id)
                            item.device_guid = target_device_guid
                            items[input_type].append(item)
                elif input_type == InputType.JoystickHat:                        
                    info : gremlin.joystick_handling.DeviceSummary = gremlin.joystick_handling.device_info_from_guid(target_device_guid)
                    # only create hat outputs that exist on the device
                    if info is not None:
                        for index in range(info.hat_count):
                            item = ImportInputItem()
                            item.input_id = index + 1
                            item.input_type = input_type
                            item.input_name = self._get_input_name(item.input_type, item.input_id)
                            item.device_guid = target_device_guid
                            items[item.input_type].append(item)

            # remember the list for next time - the map contains all possible mappings keyed by input type
            self._target_input_item_map[target_device_guid] = items
        

        # grab the list of mappings for the given device
        items = self._target_input_item_map[target_device_guid][source_input_type]

        container_widget = QtWidgets.QWidget()
        container_widget.setContentsMargins(0,0,0,0)
        container_layout = QtWidgets.QHBoxLayout(container_widget)
        container_layout.setContentsMargins(0,0,0,0)
        target_input_id_widget = ui_common.QDataComboBox()
        # limit drop down size
        target_input_id_widget.setMaxVisibleItems(20)
        target_input_id_widget.setStyleSheet("QComboBox { combobox-popup: 0; }")
        container_layout.addWidget(target_input_id_widget)

        index = None
        for i, item in enumerate(items):
            target_input_id_widget.addItem(item.input_name, item)
            if index is None and item.input_id == target_input_id:
                index = i
        if index is None:
            index = 0

        if not source_import_item in self._input_id_to_target_input_id:
            self._input_id_to_target_input_id[source_import_item]={}

        self._input_id_to_target_input_id[source_import_item][source_input_item] = target_input_id

        target_input_id_widget.setCurrentIndex(index)
        target_input_id_widget.currentIndexChanged.connect(self._input_id_changed)
        return container_widget, target_input_id_widget


    @QtCore.Slot()
    def _target_device_changed(self):
        ''' called when the target device for a source device changes '''
        widget = self.sender()
        import_item : ImportItem  = widget.data
        device = widget.currentData() # device
        target_device_guid = device.device_guid # new target device guid
        self._input_device_guid_to_target_device_guid[import_item.device_guid] = target_device_guid

        # repopulate the tree with the new data because a new device has different configurations
        self._update_map()

    @QtCore.Slot()
    def _input_id_changed(self):
        ''' called when the target input ID is changed '''
        widget = self.sender()
        import_item : ImportItem  = widget.data
        source_input_item = widget.data # device
        input_id = widget.currentData()
        self._input_id_to_target_input_id[import_item] = input_id
        self._input_id_to_target_input_id[import_item][source_input_item] = input_id




    @QtCore.Slot(bool)
    def _select_import_item_cb(self, checked):
        widget = self.sender()
        data = widget.data
        data.selected = checked

    @QtCore.Slot(bool)
    def _import_mode_selection_cb(self, checked):
        self._import_mode_selection_cb[self.sender().text()] = checked



    @QtCore.Slot()
    def _cmd_one_to_one(self):
        ''' maps the inputs one to one as best able to '''
        # get list of all input items

        input_items = [item for item in self._map.keys() if isinstance(item, ImportInputItem)]
        input_item : ImportInputItem
        for input_item in input_items:
            widget = self._map[input_item]
            widget = find_dropdown(widget)
            if widget is not None:
                # get the device guid for the mapped item
                data : ImportInputItem = widget.currentData()
                if data:
                    device_guid = data.device_guid
                    # get the list of possible inputs for that device
                    items_map = self._target_input_item_map[device_guid]
                    for input_type in items_map.keys():
                        items = items_map[input_type]
                        if items:
                            first = next((item for item in items if item.input_type == input_item.input_type and item.input_id == input_item.input_id), None)
                            if not first:
                                # id doesn't exist, match by type only
                                first = next((item for item in items if item.input_type == input_item.input_type), None)
                            if first:
                                index = widget.findData(first)
                                widget.setCurrentIndex(index)


    @QtCore.Slot()
    def _cmd_deselect_all(self):
        ''' deselects all nodes in the tree '''
        items = [item for item in self._map.keys() if isinstance(item, ImportItem)]
        for item in items:
            item.selected = False

    @QtCore.Slot()
    def _cmd_select_all(self):
        ''' selects all nodes in the tree '''
        items = [item for item in self._map.keys() if isinstance(item, ImportItem)]
        for item in items:
            item.selected = True


    @QtCore.Slot(int)
    def _cmd_set_level(self, level):
        ''' expand/collapse tree map to level
        0 = expand all
        1 = expand device
        2 = expand mode
        3 = expand container
        4 = expand input
        '''

        # save the level
        gremlin.config.Configuration().import_level = level

        expand_items = []
        expand_items.extend(self._tree_root_nodes)
        if level == 0:
            self.import_input_tree_widget.expandAll()
            return

        if level >= 1:
            expand_items.extend(self._tree_device_nodes)
        if level >= 2:
            expand_items.extend(self._tree_mode_nodes)
        if level >= 3:
            expand_items.extend(self._tree_input_nodes)
        if level >= 4:
            expand_items.extend(self._tree_container_nodes)


        self.import_input_tree_widget.collapseAll()
        for item in expand_items:
            item : QtWidgets.QTreeWidgetItem
            #item.setBackground(0, QtGui.QColor('green'))
            parent = item.parent()
            if parent:
                parent.setExpanded(True)
            #item.setExpanded(True)
            #self.import_input_tree_widget.expandItem(item)

    @QtCore.Slot()
    def _execute_import(self):
        ''' run the import based on the mapping options '''
        # only map the selected import items

        import_items = [item for item in self._map.keys() if isinstance(item, ImportItem) and item.selected]
        import_item : ImportItem

        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        container_tag_map = container_plugins.tag_map

        input_count = 0
        mode_count = 0
        container_count = 0
        action_count = 0

        verbose = gremlin.config.Configuration().verbose
        syslog = logging.getLogger("system")

        processed_mode_set = set()

        for import_item in import_items:
            # target output device
            target_device_guid = self._input_device_guid_to_target_device_guid[import_item.device_guid]
            target_device : gremlin.base_profile.Device = self.target_profile.devices[target_device_guid]
            source_device_guid = import_item.device_guid

            # get the modes mapped for this input
            mode_items = [item for item in self._map.keys() if isinstance(item, ImportModeItem) and item.parent == import_item and item.selected]
            mode_item : ImportModeItem
            for mode_item in mode_items:
                
                # current modes in existing profile
                mode_list = self.target_profile.get_modes()

                source_mode = mode_item.mode
                widget = mode_item.map_to_widget
                if widget:
                    # has a mode
                    target_mode = widget.currentData()
                    parent_mode = mode_item.parent_mode

                    # if the mode is not in the target profile, create that mode
                    if not target_mode in mode_list:
                        self.target_profile.add_mode(target_mode, parent_mode, emit=False)
                        
                        if verbose:
                            syslog.info(f"Adding non existing mode {target_mode} to target profile")

                    if parent_mode is not None:      
                        if not parent_mode in mode_list:
                            self.target_profile.add_mode(parent_mode, emit=False) # ensure the parent mode exists first
                        self.target_profile.set_mode_parent(target_mode, parent_mode, emit = False)
                    

                    if verbose:
                        syslog.info(f"Import mode [{source_mode}] to mode [{target_mode}] in target profile")

                    processed_mode_set.add(source_mode)

                    # get the list of source items to map to the target device for the target mode
                    input_items = [item for item in self._map.keys() if isinstance(item, ImportInputItem) and item.parent == mode_item and item.selected]
                    input_item : ImportInputItem
                    for input_item in input_items:
                        # get the target input for the source input
                        widget = input_item.map_to_widget
                        if widget:


                            input_input_id = input_item.input_id
                            input_input_type = input_item.input_type

                            # get the target input on that device
                            target_input_item : ImportInputItem = widget.currentData()
                            if not target_input_item:
                                continue
                            target_input_id = target_input_item.input_id
                            target_input_type = target_input_item.input_type

                            input_count += 1

                            container_items = input_item.containers # [item for item in input_item.containers if item.selected]
                            container_item : ImportContainerItem                            

                            # profile_input_item : gremlin.base_profile.InputItem
                            input_device : gremlin.base_profile.Device
                            input_device = next((device for device in self.source_profile.devices.values() if device.device_guid == source_device_guid), None)
                            input_profile_mode = input_device.modes[source_mode]                            
                            


                            if target_input_type == InputType.Midi:
                                # MIDI item source
                                source : midi_device.MidiInputItem = input_item.data
                                target = source.duplicate()

                                # add the entry to the profile
                                target_device.modes[target_mode].get_data(target_input_type, target)
                                profile_target_input_item = target_device.modes[target_mode].config[target_input_type][target]
                                key = next((key for key in input_profile_mode.config[input_input_type].keys() if key.id == source.id), None)
                                profile_source_input_item = input_profile_mode.config[input_input_type][key]
                                
                                
                            elif target_input_type == InputType.OpenSoundControl:
                                # OSC item source
                                source : osc_device.OscInputItem = input_item.data
                                target = source.duplicate() # osc_device.OscInputItem()

                                target_device.modes[target_mode].get_data(target_input_type, target) 
                                profile_target_input_item = target_device.modes[target_mode].config[target_input_type][target]
                                key = next((key for key in input_profile_mode.config[input_input_type].keys() if key.id == source.id), None)
                                profile_source_input_item = input_profile_mode.config[input_input_type][key]

                            elif target_input_type == InputType.KeyboardLatched:
                                # Keyboard OSC source
                                source : keyboard_device.KeyboardInputItem = input_item.data
                                target = source.duplicate()
                                
                                target_device.modes[target_mode].get_data(target_input_type, target) 
                                profile_target_input_item = target_device.modes[target_mode].config[target_input_type][target]
                                key = next((key for key in input_profile_mode.config[input_input_type].keys() if key.id == source.id), None)
                                profile_source_input_item = input_profile_mode.config[input_input_type][key]
                                #profile_source_input_item = input_profile_mode.config[input_input_type][source]


                            elif target_input_type in (InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat):
                                profile_target_mode : gremlin.base_profile.Mode = target_device.modes[target_mode]
                                profile_target_input_item : gremlin.base_profile.InputItem
                                profile_source_input_item = input_profile_mode.config[input_input_type][input_input_id]

                                # mode.config is a dictionary of [input_type][input_id] holding gremlin.base_profile.InputItem
                                # InputItems hold the containers for that input
                                target_device.modes[target_mode].get_data(target_input_type, target_input_id) 
                                profile_target_input_item = profile_target_mode.config[target_input_type][target_input_id]


                            for container_item in container_items:
                                # get the source container to import
                                profile_container = next((container for container in profile_source_input_item.containers if container_item.container_id == container.id),None)
                                if not profile_container:
                                    syslog.warning(f"Unable to find import container id: {str(container_item)}")
                                    continue
                                
                                # found the matching input item on the target profile
                                # use xml to serialize to avoid reference shenanigans
                                node = profile_container.to_xml() 
                                # change node actionIds to new Ids (not technically necessary but good to do)
                                action_nodes = node.xpath("//*[@action_id]")
                                for action_node in action_nodes:
                                    new_id = gremlin.util.get_guid(no_brackets=True)
                                    action_node.set("action_id",new_id)
                                # create a new container
                                container = container_tag_map[profile_container.tag](profile_target_input_item)
                                # configure the container from the serialized data
                                container.from_xml(node)
                                # generate a new container ID 
                                container.id = gremlin.util.get_guid(no_brackets=True)
                                if verbose:
                                    syslog.info(f"Adding container : {profile_container.tag} to input type {InputType.to_display_name(profile_target_input_item.input_type)} input {profile_target_input_item.input_id} {container.action_count} actions")

                                container_count +=1
                                action_count += container.action_count
                                profile_target_input_item.containers.append(container)



        mode_count = len(processed_mode_set)
        ui_common.MessageBox("Import results:",
            f"Imported {input_count:,} input(s)<br>{mode_count:,} mode(s)<br>{container_count:,} container(s)<br>{action_count:,} action(s)",
            is_warning=False)













def import_profile():
    ''' imports a profile - prompts the user for a profile to import into the specified device '''
    fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Profile to import",
            gremlin.util.userprofile_path(),
            "XML files (*.xml)"
        )
    if fname == "":
        return

    dialog = ImportProfileDialog(fname)
    dialog.exec()

    gremlin.shared_state.ui.refresh()