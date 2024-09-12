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
# from gremlin.input_types import InputType

#from xml.dom import minidom
from lxml import etree as ElementTree

# from gremlin.plugin_manager import ContainerPlugins
# from gremlin.base_buttons import VirtualAxisButton, VirtualHatButton
# from gremlin.plugin_manager import ActionPlugins, ContainerPlugins


NodeItem = namedtuple("NodeItem","device_name device_guid device_type node")
ContainerItem= namedtuple("ContainerItem","device_name device_guid device_type mode input_type input_id input_description container_nodes")




class ImportContainerItem():
    container_type = None  # type of container this is
    container_name : str = None
    actions = [] # actions in the container
    action_names = [] # action names mapped in the container


class ImportInputItem():
    ''' holds the input data '''
    input_id : int = 0
    input_description : str = None
    input_type : InputType = None
    input_name : str  = None
    containers : list[ImportContainerItem] = []  # list of ImportContainerItems


class ImportItem():
    ''' holds container data '''
    device_name : str = None
    device_type : DeviceType = None
    device_guid = None
    mode_map : dict[str, list[ImportInputItem]] = {} # map keyed by mode of list of input_items

    

class ImportItemListModel(QtCore.QAbstractListModel):
    ''' model for mapped inputs '''
    def __init__(self):
        super().__init__()
        self._items : list[ImportItem] = []  # list of input items

    def data(self, index: Union[PySide6.QtCore.QModelIndex, PySide6.QtCore.QPersistentModelIndex],
                role: int = ...) -> Any:
            if role == QtCore.Qt.DisplayRole:
                model = self._items[index.row()]
                return model

    def rowCount(self, parent: Union[PySide6.QtCore.QModelIndex, PySide6.QtCore.QPersistentModelIndex] = ...) -> int:
        return len(self._items)
    
    @property
    def items(self):
        return self._items
    


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
        

        # get target capabilities
        self.target_device : gremlin.base_profile.Device = self.target_profile.devices[device_guid]
        self.device_name = self.target_device.name.casefold()
        self.target_hardware = gremlin.joystick_handling.device_info_from_guid(self.target_device.device_guid)
        self.profile_path = profile_path
        self._device_list = []  # list of devices from the profile
        self._import_map = {} # import map from the import profile
        self._import_mode_list = [] # list of available modes in the import profile 
        self._import_mode_selection_map  = {} # map of modes to the import selection - value = true if the mode is selected for import, false otherwise

        # Actual configuration object being managed
        self.config = gremlin.config.Configuration()


        self._create_ui() # create the dialog UI
        self._load_import_profile() # load and update the ui with the import profile
        

        self._import_model = ImportItemListModel()

      



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
        self._device_change_cb()

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
        
        # buttons
        self.container_buttons_widget = QtWidgets.QWidget()
        self.container_buttons_widget.setContentsMargins(0,0,0,0)
        self.container_buttons_layout = QtWidgets.QHBoxLayout(self.container_buttons_widget)
        self.container_buttons_layout.setContentsMargins(0,0,0,0)

        self.import_button_widget = QtWidgets.QPushButton("Import")
        self.import_button_widget.clicked.connect(self._import_cb)
        self.close_button_widget = QtWidgets.QPushButton("Close")
        self.close_button_widget.clicked.connect(self._close_cb)

        self.container_mode_layout.addWidget(self.create_mode_widget)
        self.container_mode_layout.addWidget(self.target_mode_label_widget)
        self.container_mode_layout.addWidget(self.import_modes_widget)
        self.container_mode_layout.addWidget(self.import_single_mode_widget)
        self.container_mode_layout.addWidget(self.import_mode_selector)

        self.main_layout.addWidget(self.container_path_widget)
        self.main_layout.addWidget(self.container_device_widget)


    def _update_ui(self):
        ''' updates the UI based on the profiles '''
        self.populate_mode_selector(self.import_mode_selector, self.source_profile)

        # available source devices
        device :  gremlin.base_profile.Device
        if self.target_device.type in (DeviceType.Joystick, DeviceType.VJoy):
            allowed_types = (DeviceType.Joystick, DeviceType.VJoy)
        else:
            allowed_types = (self.target_device.type)

        with QtCore.QSignalBlocker(self.source_device_selector):
            while self.source_device_selector.count() > 0:
                self.source_device_selector.removeItem(0)

            for device in self.source_profile.devices.values():
                if device.type in allowed_types:
                    self.source_device_selector.addItem(f"{DeviceType.to_display_name(device.type)} {device.name} [{device.device_guid}]", device)
    

        # update selectable import mode list
        self._update_import_mode_list()


    
    def _update_mode_options(self):
        ''' updates the mode options based on what is selected '''
        source_mode_enabled = self.import_single_mode_widget.isChecked()
        self.import_mode_selector.setVisible(source_mode_enabled)

        target_mode_enabled = self.create_mode_widget.isChecked()
        self.target_mode_selector.setEnabled(target_mode_enabled)
        self.target_mode_label_widget.setEnabled(target_mode_enabled)

    @QtCore.Slot()
    def _import_cb(self):
        pass

    @QtCore.Slot()
    def _close_cb(self):        
        gremlin.shared_state.ui.refresh()
        self.close()



    @QtCore.Slot()
    def _device_change_cb(self):
        ''' called when device selection changes'''
        self._source_device = self.source_device_selector.currentData()

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

        item_list = []
        node_devices = self.root.xpath("//device")
        for node in node_devices:
            node_name = node.get("name")
            node_guid = gremlin.util.parse_guid(node.get("device-guid"))
            node_type = DeviceType.to_enum(node.get("type"))
            if node_type != self.target_device.type:
                # device type does not match
                continue
            if node_guid == self.target_device.device_guid:
                # match by ID - ok
                pass
            elif node_name.casefold() == self.device_name:
                # match by name = ok
                pass
            else:
                continue

            # node entry matches GUID or name
            item = NodeItem(node_name, node_guid, node_type, node)
            item_list.append(item)

        self._import_map = {}
        

        import_list = []
        item : NodeItem
        for item in item_list:
            node = item.node
            node_mode = gremlin.util.get_xml_child(node,"mode")
            if node_mode is not None:
                mode = node_mode.get("name")

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

        item : self.ContainerItem
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

            else:
                import_data = self._import_map[item.device_guid]

            input_data = ImportInputItem()
            input_data.input_id = input_id
            input_data.input_description = input_description
            input_data.input_type = input_type
            input_data.input_name = target_input_item.display_name
            if not mode in import_data.mode_map.keys():
                import_data.mode_map[mode] = []
            import_data.mode_map[mode].append(input_data)

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

    @QtCore.Slot(bool)
    def _import_mode_selection_cb(self, checked):
        self._import_mode_selection_cb[self.sender().text()] = checked


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








    


