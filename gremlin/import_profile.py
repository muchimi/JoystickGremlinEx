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
    
    _import_profile(device_guid, fname)

    # refresh the UI with the new data
    gremlin.shared_state.ui.refresh()


def _import_profile(device_guid, path, clear_target = False):
    ''' imports a profile to the specified target device ID matching by name
    
    :param: device_guid  the device to import to
    :path: the xml to import
    '''
    syslog = logging.getLogger("system")
    if not os.path.isfile(path):
        syslog.warning(f"Import profile: error: file not found: {path}")
        return
    
    target_profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile

    # get the device information
    device_guids = list(target_profile.devices.keys())
    if not device_guid in device_guids:
        syslog.warning(f"Import profile: error: target device does not exist in current profile {device_guid}")
        return
    
    target_device : gremlin.base_profile.Device
    source_device : gremlin.base_profile.Device

    target_device = target_profile.devices[device_guid]
    
    # get the profile modes in the file
    source_profile = gremlin.base_profile.Profile()
    source_profile.from_xml(path)

    # read the xml
    tree = ElementTree.parse(path)
    root = tree.getroot()

    device_name = target_device.name.casefold()

    # get target capabilities
    target_hardware = gremlin.joystick_handling.device_info_from_guid(target_device.device_guid)

    # get all the device entries matching what we're looking for - by name or by GUID
    NodeItem = namedtuple("NodeItem","device_name device_guid device_type node")
    ContainerItem= namedtuple("ContainerItem","device_name device_guid device_type mode input_type input_id input_description container_nodes")
    item_list = []
    node_devices = root.xpath("//device")
    for node in node_devices:
        node_name = node.get("name")
        node_guid = gremlin.util.parse_guid(node.get("device-guid"))
        node_type = DeviceType.to_enum(node.get("type"))
        if node_type !=target_device.type:
            # device type does not match
            continue
        if node_guid == device_guid:
            # match by ID - ok
            pass
        elif node_name.casefold() == device_name:
            # match by name = ok
            pass
        else:
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
            for node_input in node_mode:
                node_containers = gremlin.util.get_xml_child(node_input,"container",multiple=True)
                if len(node_containers) == 0:
                    # no mapping - skip node
                    continue
                if node_input.tag == "axis":
                    # axis node
                    input_id = safe_read(node_input,"id",int, 0)
                    input_description = safe_read(node_input,"description",str,"")
                    if input_id < target_hardware.axis_count:
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
                    if input_id < target_hardware.button_count:
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
                    if input_id < target_hardware.hat_count:
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
        syslog.warning(f"Import profile: warning: no matching GUID or names found {target_device.name} {device_guid}")
        return
    
    # get the modes hierarchy of the imported profile
    mode_tree = source_profile.mode_tree()
    for source_dev in import_list:
        # match modes
        for mode_name in mode_tree.keys():
            _load_modes(source_profile,
                        target_profile,
                        source_dev,
                        target_device,
                        mode_name,
                        None,
                        mode_tree,
                        clear_target)
            

    # process each container and add to the target

    container_plugins = gremlin.plugin_manager.ContainerPlugins()
    container_name_map = container_plugins.tag_map

    item : ContainerItem
    syslog.info(f"Import to: '{target_device.name}' [{target_device.device_guid}]")
    for item in import_list:
        nodes = item.container_nodes
        input_id = item.input_id
        input_type = item.input_type
        input_description = item.input_description
        mode = item.mode

        target_mode = target_device.modes[mode]
        target_entry = target_mode.config[input_type]
        target_input_item : gremlin.base_profile.InputItem= target_entry[input_id]

        syslog.info(f"\t{target_input_item.display_name}")

        for node in nodes:
            container_type = node.get("type")
            if container_type not in container_name_map:
                syslog.warning(f"\t\tUnknown container type used: {container_type}")
                continue


            container = container_name_map[container_type](target_input_item)
            container.from_xml(node)

            target_input_item.containers.append(container)

            syslog.info(f"\tContainer: {container_type}")
            for action_set in container.action_sets:
                for action in action_set:
                    syslog.info(f"\t\t\tImported container: {action.name} {action.display_name()}")

    
            
def _load_modes(source_profile : gremlin.base_profile.Profile,
                target_profile : gremlin.base_profile.Profile,
                source_device : gremlin.base_profile.Device,
                target_device: gremlin.base_profile.Device,
                current_mode_name : str,
                inherited_mode_name : str,
                mode_tree : map,
                clear_target = False):
    ''' recursive load operation - transfer specific mode between source and target devices
    :param: source_profile the profile being copied from
    :param: target_profile the profile being copied to
    :param: source_device the source device being copied from in the source profile
    :param: target_device the target device being copied to in the target profile
    :param: current_mode_name the name of the mode being copied
    :param: inherited_mode_name the name of the mode being inherited from (if inherited)
    :param: mode_tree the mode hierachy - a map of modes by inheritance


    '''
    syslog = logging.getLogger("system")
    if not current_mode_name in target_profile.mode_list():
        target_profile.add_mode(current_mode_name, inherited_mode_name, emit = False )

    for child_mode_name in mode_tree[current_mode_name].keys():
        _load_modes(source_profile, target_profile, source_device, target_device, child_mode_name, current_mode_name, mode_tree)

    # # process the mappings for this mode
    # mode = source_device.modes[current_mode_name]
    # target_mode = target_device.modes[current_mode_name]
    # target_hardware = gremlin.joystick_handling.device_info_from_guid(target_device.device_guid)
    # for input_type in mode.config.keys():
    #     source_entry = mode.config[input_type]
    #     if source_entry:
    #         # if not input_type in target_mode.config.keys():
    #         #     target_mode.config[input_type] = {}
    #         target_entry = target_mode.config[input_type]
    #         source_input_item : gremlin.base_profile.InputItem
            
    #         for input_id, source_input_item in source_entry.items():
    #                 if source_input_item.containers:
    #                     # source has containers mapped - figure out where they go
    #                     if source_input_item.input_type == InputType.JoystickAxis and input_id < target_hardware.axis_count:
    #                         pass
    #                     elif source_input_item.input_type == InputType.JoystickButton and input_id < target_hardware.button_count:
    #                         pass
    #                     elif source_input_item.input_type == InputType.JoystickHat and input_id < target_hardware.hat_count:
    #                         pass
    #                     else:
    #                         syslog.info(f"Import mode: input {InputType.to_display_name(source_input_item.input_type)} id {input_id} not found in target device {target_device.name} - skipping entry")
    #                         continue

    #                     syslog.info(f"Import mode: input {InputType.to_display_name(source_input_item.input_type)} id {input_id} importing:")
    #                     # duplicate containers
    #                     for container in source_input_item.containers:
    #                         # duplicate the container
    #                         dup_container = copy.deepcopy(container)
    #                         for action_set in dup_container.get_action_sets():
    #                             for action in action_set:
    #                                 action.action_id = gremlin.util.get_guid()

    #                     # add the container to the output device
    #                     target_input_item : gremlin.base_profile.InputItem= target_entry[input_id]
    #                     if clear_target:
    #                         target_input_item.containers.clear()

    #                     target_input_item.containers.extend(dup_container)
                        
                    
        
            





    


