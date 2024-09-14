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
from gremlin.ui import ui_common
from gremlin.clipboard import Clipboard
# from gremlin.input_types import InputType

#from xml.dom import minidom
from lxml import etree as ElementTree


NodeItem = namedtuple("NodeItem","device_name device_guid device_type node")
ContainerItem= namedtuple("ContainerItem","device_name device_guid device_type mode input_type input_id input_description container_nodes")


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
        self.container_type = None  # type of container this is
        self.container_name : str = None
        self.actions = [] # actions in the container
        self.action_names = [] # action names mapped in the container
        

    def selectable_items(self):
        return self.actions

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
        self.containers : list[ImportContainerItem] = []  # list of ImportContainerItems
        self._selected : bool = True # true if selected for import
    
    def selectable_items(self):
        return self.containers


    def __str__(self):
        return f"{self.input_name} [{self.input_id}]"
    
class ImportModeItem(AbstractTreeItem):
    def __init__(self):
        super().__init__()
        self.mode = None # mode
        self.parent = None # parent (ImportItem)
        self.items : list[ImportInputItem] = []
    
    def selectable_items(self):
        return self.items


class ImportItem(AbstractTreeItem):
    ''' holds container data '''
    def __init__(self):
        super().__init__()
        self.device_name : str = None
        self.device_type : DeviceType = None
        self.device_guid = None
        self.mode_map : dict[str, ImportModeItem ] = {} # map keyed by mode of list of input_items

    
    def selectable_items(self):
        return list(self.mode_map.values())
    

class ImportProfileDialog(QtWidgets.QDialog):
    ''' dialog for import options '''


    def __init__(self, device_guid, profile_path, parent=None):
        
        super().__init__(parent)

        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        syslog = logging.getLogger("system")

        # get the device information
        self.target_profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        device_guids = list(self.target_profile.devices.keys())
        if not device_guid in device_guids:
            syslog.warning(f"Import profile: error: target device does not exist in current profile {device_guid}")
            self.close()
            return
        
        # buid list of target devices in the current profile - these are devices that can be imported into
        self.target_devices = []
        self.target_devices_map = {}
        self.target_devices = [device for device in self.target_profile.devices.values() if device.connected]
        for device in self.target_devices:
            self.target_devices_map[device.device_guid] = device

        
        self.target_device : gremlin.base_profile.Device = self.target_profile.devices[device_guid]
        self.device_name = self.target_device.name.casefold()
        self.target_hardware = gremlin.joystick_handling.device_info_from_guid(self.target_device.device_guid)
        self.profile_path = profile_path
        self._import_map = {} # import map from the import profile ([device_guid] ImportItems -> [mode] -> ImportInputItems -> [containers list] -> ImportContainerItem
        self._import_mode_list = [] # list of available modes in the import profile 
        self._import_mode_selection_map  = {} # map of modes to the import selection - value = true if the mode is selected for import, false otherwise
        self._target_input_item_map = {}  # map of device GUID to available input items for that device - cached as needed
        self._map = {}  # map of source items to their mapped destination
        self._input_items_by_source_device_guid = {} # holds the data for input items based on device GUID
        self._input_device_guid_to_target_device_guid = {} # holds the map of source device guids to target device guid for mapping

        # Actual configuration object being managed
        self.config = gremlin.config.Configuration()


        self._create_ui() # create the dialog UI
        self._load_import_profile() # load and update the ui with the import profile

        

        # current list of import inputs
        #self._import_model = ImportItemListModel()



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

        # device to import
        
        self.container_device_widget = QtWidgets.QWidget()
        self.container_device_widget.setContentsMargins(0,0,0,0)
        self.container_device_layout = QtWidgets.QHBoxLayout(self.container_device_widget)
        self.container_device_layout.setContentsMargins(0,0,0,0)

        self.source_device_selector = QtWidgets.QComboBox()
        self.source_device_selector.currentIndexChanged.connect(self._device_change_cb)
        self.container_device_layout.addWidget(self.source_device_selector)

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

        self.target_mode_selector = QtWidgets.QComboBox()
        # populate the modes of the current device being imported into 
        self.populate_mode_selector(self.target_mode_selector, self.target_profile)

        self.import_modes_widget = QtWidgets.QRadioButton("Import All Modes")
        self.import_modes_widget.setToolTip("Import all modes from profile and add them to the existing profile if they don't exist")
        self.import_single_mode_widget = QtWidgets.QRadioButton("Import single mode")
        self.import_single_mode_widget.setToolTip("Import specific mode")
        self.import_mode_selector = QtWidgets.QComboBox()

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

        



        self.container_command_header_layout.addWidget(self.command_one_to_one_button_widget)
        self.container_command_header_layout.addStretch()

        
        # buttons
        self.container_buttons_widget = QtWidgets.QWidget()
        self.container_buttons_widget.setContentsMargins(0,0,0,0)
        self.container_buttons_layout = QtWidgets.QHBoxLayout(self.container_buttons_widget)
        self.container_buttons_layout.setContentsMargins(0,0,0,0)

        self.import_button_widget = QtWidgets.QPushButton("Import")
        self.import_button_widget.clicked.connect(self._import_cb)
        self.close_button_widget = QtWidgets.QPushButton("Close")
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
        self.main_layout.addWidget(self.container_device_widget)
        #self.main_layout.addWidget(self.container_mode_widget)
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

    def _update_ui(self):
        ''' updates the UI based on the profiles '''

        # update the device list from the list of import devices
        with QtCore.QSignalBlocker(self.source_device_selector):
            self.source_device_selector.clear()
            item : ImportItem
            for item in self._import_map.values():
                self.source_device_selector.addItem(item.device_name, item)

        # populate the modes for the target
        self.populate_mode_selector(self.import_mode_selector, self.source_profile)

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
       

    def populate_mode_selector(self, selector : QtWidgets.QComboBox, profile : gremlin.base_profile.Profile):
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
        self._input_items_by_source_device_guid = {}

        item_list = []
        node_devices = self.root.xpath("//device")
        for node in node_devices:
            node_name = node.get("name")
            node_guid = gremlin.util.parse_guid(node.get("device-guid"))
            node_type = DeviceType.to_enum(node.get("type"))
            if node_type != self.target_device.type:
                # device type does not match
                continue
        
            # node entry matches GUID or name
            item = NodeItem(node_name, node_guid, node_type, node)
            item_list.append(item)


        import_list = []
        item : NodeItem
        for item in item_list:
            node = item.node
            node_mode = gremlin.util.get_xml_child(node,"mode")
            if node_mode is not None:
                mode = node_mode.get("name")
                dm_pair = (item.device_guid, mode)
                if dm_pair in device_mode_pairs:
                    syslog.warning(f"Found duplicated device/mode entries in import profile - only the fist entry will be used: device {item.device_name} ID: {item.device_guid}")
                    continue
                device_mode_pairs.append(dm_pair)
                for node_input in node_mode:
                    node_containers = gremlin.util.get_xml_child(node_input,"container",multiple=True)
                    if len(node_containers) == 0:
                        # no mapping - skip node
                        continue
                    if node_input.tag == "axis":
                        # axis node
                        input_id = safe_read(node_input,"id",int, 0)
                        input_description = safe_read(node_input,"description",str,"")
                        if input_id < self.target_hardware.axis_count:
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
                        input_description = safe_read(node_input,"description",str,"")
                        if input_id < self.target_hardware.button_count:
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
                        input_description = safe_read(node_input,"description",str,"")
                        if input_id < self.target_hardware.hat_count:
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
                
        

        if not import_list:
            syslog.warning(f"Import profile: warning: no matching GUID or names found {self.target_device.name} {self.device_guid}")
            return
        
                

        # process each container and add to the target

        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        container_name_map = container_plugins.tag_map
        mode_list = []

        item : ContainerItem
        syslog.info(f"Import to: '{self.target_device.name}' [{self.target_device.device_guid}]")
        for item in import_list:
            nodes = item.container_nodes
            input_id = item.input_id
            input_type = item.input_type
            input_description = item.input_description
            mode = item.mode


            if not mode in mode_list:
                mode_list.append(mode)

            target_mode = self.target_device.modes[mode]
            target_entry = target_mode.config[input_type]
            target_input_item : gremlin.base_profile.InputItem= target_entry[input_id]

            if not item.device_guid in self._import_map.keys():
                import_data = ImportItem()
                import_data.device_name = item.device_name
                import_data.device_guid = item.device_guid
                import_data.device_type = item.device_type
                import_data.input_id = input_id
                import_data.input_type = input_type
                import_data.input_description = input_description
                self._import_map[item.device_guid] = import_data
                import_data.parent = None



            else:
                import_data = self._import_map[item.device_guid]

            input_data = ImportInputItem()
            input_data.input_id = input_id
            input_data.input_description = input_description
            input_data.input_type = input_type
            input_data.input_name = target_input_item.display_name
            input_data.mode = mode
            input_data.parent = item
            input_data.device_guid = import_data.device_guid
            if not import_data.device_guid in self._input_items_by_source_device_guid.keys():
                self._input_items_by_source_device_guid[import_data.device_guid] = [] # create list of ImportInputItems for that specific import device so we can find them easily
            self._input_items_by_source_device_guid[import_data.device_guid].append(input_data)
            if not mode in import_data.mode_map.keys():
                mode_item = ImportModeItem()
                mode_item.mode = mode
                mode_item.parent = item
                import_data.mode_map[mode] = mode_item
            else:
                mode_item = import_data.mode_map[mode]
            mode_item.items.append(input_data)



            syslog.info(f"\t{target_input_item.display_name}")
            

            for node in nodes:
                container_type = node.get("type")
                if container_type not in container_name_map:
                    syslog.warning(f"\t\tUnknown container type used: {container_type}")
                    continue


                container = container_name_map[container_type](target_input_item)
                container.from_xml(node)

                container_data = ImportContainerItem()
                container_data.container_name = container.name
                container_data.container_type = container_type
                container_data.parent = input_data
                

                target_input_item.containers.append(container)

                syslog.info(f"\tContainer: {container_type}")
                for action_set in container.action_sets:
                    for action in action_set:
                        syslog.info(f"\t\t\tImported container: {action.name} {action.display_name()}")
                        container_data.actions.append(action)
                        container_data.action_names.append(action.display_name())

                input_data.containers.append(container_data)




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


    def _update_map(self):
        ''' updates the mappings source to target '''

        self._map = {} # clear and rebuild the map
        

        tree = self.import_input_tree_widget
        with QtCore.QSignalBlocker(tree):     
            tree.setColumnCount(4)
            tree.setHeaderLabels(["Device","Actions","Map To",""])
            tree.clear()
            header = tree.header()
            header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)


            root_node = QtWidgets.QTreeWidgetItem(["Importable items"])
            tree.addTopLevelItem(root_node)

            import_item : ImportItem
            
            for import_item in self._import_map.values():

                container_widget = QtWidgets.QWidget()
                container_widget.setContentsMargins(0,0,0,0)
                container_layout = QtWidgets.QHBoxLayout(container_widget)
                container_layout.setContentsMargins(0,0,0,0)

                device_node = QtWidgets.QTreeWidgetItem()
                root_node.addChild(device_node)

                cb = ui_common.QDataCheckbox(f"{import_item.device_name}")
                cb.data = import_item
                import_item.selected_widget = cb
                cb.setChecked(import_item.selected)
                cb.clicked.connect(self._select_import_item_cb)

                container_layout.addWidget(cb)
                # container_layout.addWidget(QtWidgets.QLabel(f"[{import_item.device_guid}]"))
                container_layout.addStretch()

                map_to_widget, widget = self._create_target_selection_widget(import_item.device_type)
                widget.data = import_item  # indicate which import_item holds this device mapping
                import_item.map_to_widget = widget

                if not import_item.device_guid in self._input_device_guid_to_target_device_guid.keys():
                    target_device_guid = widget.currentData().device_guid
                    self._input_device_guid_to_target_device_guid[import_item.device_guid] = target_device_guid
                else:
                    # select the saved target device for the output
                    target_device_guid = self._input_device_guid_to_target_device_guid[import_item.device_guid] # guid of the target device
                    device = self.target_devices_map[target_device_guid] # device of the target device
                    index = widget.findData(device) # index in the drop down
                    with QtCore.QSignalBlocker(widget):
                        widget.setCurrentIndex(index)  

                self._map[import_item] = widget

                tree.setItemWidget(device_node, 0, container_widget)
                tree.setItemWidget(device_node, 2, map_to_widget)
                
                mode_item: ImportModeItem
                for mode_item in import_item.mode_map.values():
                    mode_node = QtWidgets.QTreeWidgetItem()

                    container_widget = QtWidgets.QWidget()
                    container_widget.setContentsMargins(0,0,0,0)
                    container_layout = QtWidgets.QHBoxLayout(container_widget)
                    container_layout.setContentsMargins(0,0,0,0)

                    map_to_widget, widget = self._create_target_mode_widget()
                    mode_item.map_to_widget = widget

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
                    self._map[mode_item] = widget
                    
                    for input_item in mode_item.items:

                        input_node = QtWidgets.QTreeWidgetItem()

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

                        map_to_input_widget, widget = self._create_target_input_widget(input_item, target_device_guid)

                        tree.setItemWidget(input_node, 0, container_widget)
                        if map_to_input_widget is not None:
                            tree.setItemWidget(input_node, 2, map_to_input_widget)

                        input_item.map_to_widget = widget
                        self._map[input_item] = widget

                        for container_item in input_item.containers:

                            container_node = QtWidgets.QTreeWidgetItem()
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
                        

            tree.expandAll()
                    

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
        
        container_layout.addWidget(widget)
        
        for device in self.target_devices:
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
        
        self.populate_mode_selector(widget, self.target_profile)
        
        return container_widget, widget
    
    def _create_target_input_widget(self, source_input_item : ImportInputItem, device_guid):
        ''' create a combo box for the mode mapping '''

        items = []
        if not device_guid in self._target_input_item_map.keys():
            # build the list
            info : gremlin.joystick_handling.DeviceSummary = gremlin.joystick_handling.device_info_from_guid(device_guid)
            for index in range(info.axis_count):
                item = ImportInputItem()
                item.input_id = index + 1
                item.input_type = InputType.JoystickAxis
                item.input_name = f"Axis {index + 1}"
                item.device_guid = device_guid
                items.append(item)
            for index in range(info.button_count):
                item = ImportInputItem()
                item.input_id = index + 1
                item.input_type = InputType.JoystickButton
                item.input_name = f"Button {index + 1}"
                item.device_guid = device_guid
                items.append(item)
            for index in range(info.hat_count):
                item = ImportInputItem()
                item.input_id = index + 1
                item.input_type = InputType.JoystickHat
                item.input_name = f"Hat {index + 1}"
                item.device_guid = device_guid
                items.append(item)
            self._target_input_item_map[device_guid] = items
        else:
            items = self._target_input_item_map[device_guid]

        container_widget = QtWidgets.QWidget()
        container_widget.setContentsMargins(0,0,0,0)
        container_layout = QtWidgets.QHBoxLayout(container_widget)
        container_layout.setContentsMargins(0,0,0,0)
        widget = ui_common.QDataComboBox()
        container_layout.addWidget(widget)

        for item in items:
            widget.addItem(item.input_name, item)

        # match up by type and id if possible
        first = next((item for item in items if item.input_type == source_input_item.input_type and item.input_id == source_input_item.input_id), None)
        if not first:
            # id doesn't exist, match by type only
            first = next((item for item in items if item.input_type == source_input_item.input_type), None)
        if first:
            index = widget.findData(first)
            widget.setCurrentIndex(index)
            return container_widget, widget
        
        return None # no match exists
    
    
    @QtCore.Slot()
    def _target_device_changed(self):
        ''' called when the target device for a source device changes '''   
        widget = self.sender()
        import_item : ImportItem  = widget.data
        device = widget.currentData() # device
        target_device_guid = device.device_guid # new target device guid
        self._input_device_guid_to_target_device_guid[import_item.device_guid] = target_device_guid

        # repopulate the tree with the new data
        self._update_map()

            
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
                device_guid = data.device_guid
                # get the list of possible inputs for that device
                items = self._target_input_item_map[device_guid]
                first = next((item for item in items if item.input_type == input_item.input_type and item.input_id == input_item.input_id), None)
                if not first:
                    # id doesn't exist, match by type only
                    first = next((item for item in items if item.input_type == input_item.input_type), None)
                if first:
                    index = widget.findData(first)
                    widget.setCurrentIndex(index)

    @QtCore.Slot()
    def _import_cb(self):
        ''' run the import based on the mapping options '''
        # only map the selected import items

        import_items = [item for item in self._map.keys() if isinstance(item, ImportItem) and item.selected]
        import_item : ImportItem

        mode_list = self.target_profile.get_modes()
        target_profile = self.target_profile

        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        container_name_map = container_plugins.tag_map

        for import_item in import_items:
            # target output device
            target_device_guid = self._input_device_guid_to_target_device_guid[import_item.device_guid]
            target_device : gremlin.base_profile.Device = self.target_devices_map[target_device_guid]
            source_device_guid = import_item.device_guid

            # get the modes mapped for this input
            mode_items = [item for item in self._map.keys() if isinstance(item, ImportModeItem) and item.parent == import_item and item.selected]
            mode_item : ImportModeItem
            for mode_item in mode_items:
                source_mode = mode_item.mode
                widget = mode_item.map_to_widget
                if widget:
                    # has a mode
                    target_mode = widget.currentText()
                    # if the mode is not in the target profile, create that mode
                    if not target_mode in mode_list:
                        self.target_profile.add_mode(target_mode, emit=False)

                    # get the list of source items to map to the target device for the target mode
                    input_items = [item for item in self._map.keys() if isinstance(item, ImportInputItem) and item.parent == mode_item and item.selected]
                    input_item : ImportInputItem
                    for input_item in input_items:
                        # copy the containers
                        
                        widget = input_item.map_to_widget
                        if widget:
                            # get the target input on that device
                            target_input_item : ImportInputItem = widget.currentData()
                            
                            container_items = input_item.containers # [item for item in input_item.containers if item.selected]
                            container_item : ImportContainerItem
                            for container_item in container_items:
                                # get the source device 
                                device : gremlin.base_profile.Device
                                device = next((device for device in self.source_profile.devices.values() if device.device_guid == source_device_guid), None)
                                profile_mode = device.modes[source_mode]
                                for profile_input_items in profile_mode.config.values():
                                    profile_input_item : gremlin.base_profile.InputItem
                                    for profile_input_item in profile_input_items.values():
                                        if profile_input_item.input_id == input_item.input_id and profile_input_item.input_type == input_item.input_type:
                                            # matching profile input
                                            for profile_container in profile_input_item.containers:
                                                # copy the containers from the source input to the target input
                                                profile_target_mode : gremlin.base_profile.Mode = target_device.modes[target_mode]
                                                profile_target_input_item : gremlin.base_profile.InputItem
                                                for profile_target_input_item in profile_target_mode.config.values():
                                                    if profile_target_input_item.input_type == target_input_item.input_type and \
                                                        profile_target_input_item.input_id == target_input_item.input_id:
                                                        # found the matching input item on the target profile
                                                        node = profile_container.to_xml() # use xml to serialize to avoid reference shenanigans
                                                        # change node actionIds to new Ids (not technically necessary but good to do)
                                                        action_nodes = node.xpath("//*[@action_id]")
                                                        for action_node in action_nodes:
                                                            new_id = gremlin.util.get_guid().replace("{","").replace("}",'')
                                                            action_node.set("action_id",new_id)
                                                        # create a new container
                                                        container = container_name_map[profile_container.container_type](profile_target_input_item)
                                                        # configure the container from the serialized data
                                                        container.from_xml(node)

                                                        #profile_target_input_item.add_container(container)



                                            




                    




def import_profile(device_guid):
    ''' imports a profile - prompts the user for a profile to import into the specified device '''
    fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Profile to import",
            gremlin.util.userprofile_path(),
            "XML files (*.xml)"
        )
    if fname == "":
        return

    dialog = ImportProfileDialog(device_guid, fname)    
    dialog.exec()