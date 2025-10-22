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
from abc import abstractmethod, ABCMeta
import codecs
import collections
import copy
import logging
import os
import shutil
import uuid

#from xml.dom import minidom
import lxml
from lxml import etree
import gremlin.base_classes
import gremlin.base_profile

from PySide6 import QtCore

import dinput
import gremlin.config
import gremlin.shared_state
import gremlin.actions
from gremlin.util import *
from gremlin.input_types import InputType
from . import error, joystick_handling


syslog = logging.getLogger("system")

def mode_list(profile = None):
    """Returns a list of all modes based on the given node.

    :param node a node from a profile tree
    :return list of modes in the profile 
    """
    profile : gremlin.base_profile.Profile
    if not profile:
        profile = gremlin.shared_state.current_profile
    if profile:
        mode_names = profile.mode_list()
        return mode_names
    return []



class ProfileConverter:

    """Handle converting and checking profiles."""

    # Current profile version number
    current_version = 16

    def __init__(self):
        pass

    def is_current(self, fname):
        """Returns whether or not the provided profile is current.

        :param fname path to the profile to evaluate
        """
        if not os.path.isfile(fname):
            return True
        # file length
        if os.path.getsize(fname) == 0:
            return True
        
        tree = etree.parse(fname)
        root = tree.getroot()

        version = self._determine_version(root)
        return version == ProfileConverter.current_version # or version == 9
    
    def convert_to_ex(self, fname):
        ''' applies the options and converts the profile '''
        import gremlin.util

        try:
            tree = etree.parse(fname)
            root = tree.getroot()

            new_root = self._convert_to_ex(root, fname)
            tree = etree.tostring(new_root)
            tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")
        except:
            gremlin.util.m

    def convert_profile(self, fname):
        """Converts the provided profile to the current version.

        :param fname path to the profile to convert
        """
        # Load the profile
        tree = etree.parse(fname)
        root = tree.getroot()

        # Check if a conversion is required
        if self.is_current(fname):
            return

        conversion_map = {
            1: self._convert_from_v1,
            2: self._convert_from_v2,
            3: self._convert_from_v3,
            4: self._convert_from_v4,
            5: self._convert_from_v5,
            6: self._convert_from_v6,
            7: self._convert_from_v7,
            8: self._convert_from_v8,
            9: None,
            10: self._convert_from_v10,
            11: self._convert_from_v11,
            12: self._convert_from_v12,
            13: self._convert_from_v13,
            14: self._convert_from_v14,
            15: self._convert_from_v15,
            16: None,
        }

        # Create a backup of the outdated profile
        old_version = self._determine_version(root)
        shutil.copyfile(fname, f"{fname}.v{old_version:d}")

        # Convert the profile
        new_root = None
        converted = False
        while old_version < ProfileConverter.current_version:
            if old_version in conversion_map:
                convert = conversion_map[old_version]
                if convert:                
                    if new_root is None:
                        new_root = convert(root, fname=fname)
                    else:
                        new_root = convert(new_root, fname=fname)
                    converted = True
                old_version += 1
                    
            else:
                # syslog = logging.getLogger("system")
                syslog.warning(f"Unexpected version: {old_version} found in profile.  Some unsupported features may not have loaded correctly.")

        if converted:
            if new_root is not None:
                # Save converted version
                tree = etree.ElementTree(root)
                tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")
            else:
                raise error.ProfileError("Failed to convert profile")

    def _determine_version(self, root):
        """Returns the version of the provided profile.

        :param root root node of the profile to determine the version of
        :return version of the profile
        """
        if root.tag == "devices" and int(root.get("version")) == 1:
            return 1
        elif root.tag == "profile":
            return int(root.get("version"))
        else:
            raise error.ProfileError(
                "Invalid profile version encountered"
            )

    def _convert_from_v1(self, root, fname=None):
        """Converts v1 profiles to v2 profiles.

        :param root the v1 profile
        :return v2 representation of the profile
        """
        new_root = etree.Element("profile")
        new_root.set("version", "2")

        # Device entries
        devices = etree.Element("devices")
        for node in root.iter("device"):
            # Modify each node to include the correct type attribute
            if node.get("name") == "keyboard" and \
                    int(node.get("windows_id")) == 0:
                node.set("type", "keyboard")
            else:
                node.set("type", "joystick")
            devices.append(node)

        new_root.append(devices)

        # Module imports
        for node in root.iter("import"):
            new_root.append(node)

        return new_root

    def _convert_from_v2(self, root, fname=None):
        """Converts v2 profiles to v3 profiles.

        :param root the v2 profile
        :return v3 representation of the profile
        """
        # Get hardware ids of the connected devices
        device_name_map = {}
        for device in joystick_handling.all_joystick_devices():
            device_name_map[device.name] = device.device_guid

        # Fix the device entries in the provided document
        new_root = copy.deepcopy(root)
        new_root.set("version", "3")
        for device in new_root.iter("device"):
            if device.get("type") == "joystick":
                if device.get("name") in device_name_map:
                    device.set("id", str(device_name_map[device.get("name")]))
                else:
                    syslog.warning(
                        f"Device '{device.get("name")}' missing, no conversion performed, ID will be incorrect."
                    )
        return new_root

    def _convert_from_v3(self, root, fname=None):
        """Converts v3 profiles to v4 profiles.
        
        The following operations are performed in this conversion:
        - embed all actions in individual BasicContainer containers
        - remove button and keyboard conditions
        - move hat and axis condition from actions to containers
        - replace double macros for keyboard remaps with the new map to
          keyboard action
        
        :param root the v3 profile
        :return v4 representation of the profile
        """
        new_root = copy.deepcopy(root)
        new_root.set("version", "4")
        for mode in new_root.iter("mode"):
            for input_item in mode:

                # Check if macros are used to create what is now a
                # "map to keyboard" action
                press_and_release = [False, False]
                count = sum([1 for _ in input_item])
                for action in input_item:
                    if input_item.tag == "button":
                        if action.tag == "macro":
                            if "on-press" in action.keys():
                                press_and_release[0] = press_and_release[0] or \
                                    parse_bool(action.get("on-press"))
                            if "on-release" in action.keys():
                                press_and_release[1] = press_and_release[1] or \
                                    parse_bool(action.get("on-release"))

                # If this widget is purely a map to keyboard action then
                # replace the two macro widgets with a single one
                if count == 2 and all(press_and_release):
                    container = etree.Element("container")
                    container.set("type", "basic")

                    container.append(
                        self._p3_extract_map_to_keyboard(input_item)
                    )
                    for action in input_item[:]:
                        input_item.remove(action)
                    input_item.append(container)

                # The item contains a variety of actions simply convert one
                # after the other
                else:
                    # Wrap each existing action into a basic container
                    containers = []
                    items_to_remove = []
                    for action in input_item:
                        container = etree.Element("container")
                        container.set("type", "basic")

                        # Move conditions to the container and remove them from
                        # the action
                        if input_item.tag == "axis":
                            copy_condition = False
                            if action.tag == "remap":
                                if "button" in action.keys() or \
                                        "hat" in action.keys():
                                    copy_condition = True
                            elif gremlin.base_profile._is_curve_tag(action.tag):
                                pass
                            else:
                                copy_condition = True
                            if copy_condition:
                                cond = etree.Element("activation-condition")
                                cond.set("lower-limit", action.get("lower-limit"))
                                cond.set("upper-limit", action.get("upper-limit"))
                                container.append(cond)
                            if "lower-limit" in action.keys():
                                del action.attrib["lower-limit"]
                            if "upper-limit" in action.keys():
                                del action.attrib["upper-limit"]
                            if "is-active" in action.keys():
                                del action.attrib["is-active"]
                        elif input_item.tag == "button":
                            if "on-press" in action.keys():
                                del action.attrib["on-press"]
                            if "on-release" in action.keys():
                                del action.attrib["on-release"]
                        elif input_item.tag == "hat":
                            if "on-n" in action.keys():
                                cond = etree.Element("activation-condition")
                                keys = [
                                    ("on-n", "north"),
                                    ("on-ne", "north-east"),
                                    ("on-e", "east"),
                                    ("on-se", "south-east"),
                                    ("on-s", "south"),
                                    ("on-sw", "south-west"),
                                    ("on-w", "west"),
                                    ("on-nw", "north-west")
                                ]
                                for names in keys:
                                    if action.get(names[0]) == "True":
                                        cond.set(names[1], "True")
                                    if names[0] in action.keys():
                                        del action.attrib[names[0]]
                                container.append(cond)

                        # Macro actions have changed, update their layout
                        if action.tag == "macro":
                            actions_node = etree.Element("actions")
                            remove_key_nodes = []
                            for key_node in action:
                                actions_node.append(key_node)
                                remove_key_nodes.append(key_node)

                            for key_node in remove_key_nodes:
                                action.remove(key_node)

                            action.append(actions_node)
                            action.append(etree.Element("properties"))

                        container.append(action)
                        containers.append(container)
                        items_to_remove.append(action)

                    for action in items_to_remove:
                        input_item.remove(action)

                    for container in containers:
                        input_item.append(container)

        return new_root

    def _convert_from_v4(self, root, fname=None):
        """Converts v4 profiles to v5 profiles.

        The following operations are performed in this conversion:
        - Place individual actions inside action_sets

        :param root the v4 profile
        :return v5 representation of the profile
        """
        new_root = copy.deepcopy(root)
        new_root.set("version", "5")
        for container in new_root.iter("container"):
            actions_to_remove = []
            action_sets = []
            for action in container:
                # Handle virtual button setups
                if action.tag == "activation-condition":
                    action.tag = "virtual-button"
                    action_sets.append(action)
                    actions_to_remove.append(action)
                # Handle actions
                else:
                    action_set = etree.Element("action-set")
                    action_set.append(action)
                    action_sets.append(action_set)
                    actions_to_remove.append(action)

            for action in actions_to_remove:
                container.remove(action)
            for action_set in action_sets:
                container.append(action_set)

        return new_root

    def _convert_from_v5(self, root, fname=None):
        """Converts v5 profiles to v6 profiles.

        The following operations are performed in this conversion:
        - Combine axis remaps and response curves into a single basic container

        :param root the v5 profile
        :return v6 representation of the profile
        """
        new_root = copy.deepcopy(root)
        new_root.set("version", "6")
        search_list = [".[@type='basic']//remap[@axis]",
                       ".[@type='basic']//response-curve",
                       ".[@type='basic']//response-curve-ex",
                       ".[@type='basic']//curve-data"
                       ]
        for axis in new_root.iter("axis"):
            has_remap = False
            has_curve = False
            for container in axis:
                for exp in search_list:
                    has_remap |= container.find(exp) is not None

            # If we have both axis remap and response curve actions place them
            # all in a single basic container
            if has_remap and has_curve:
                new_container = etree.Element("container")
                new_container.set("type", "basic")
                new_actionset = etree.Element("action-set")

                # Copy all axis remaps and response curves into the new
                # action set
                containers_to_delete = []
                for container in axis:
                    remove_container = False
                    for exp in search_list:
                        for node in container.findall(exp):
                            new_actionset.append(node)
                            remove_container = True

                    if remove_container:
                        containers_to_delete.append(container)

                new_container.append(new_actionset)
                axis.append(new_container)

                # Delete containers of
                for container in containers_to_delete:
                    axis.remove(container)

        return new_root

    def _convert_from_v6(self, root, fname):
        """Convert from a V6 profile to V7.

        This conversion only requires to modify the custom module loading bit
        which requires turning the module name into the full path. This
        requires the path to the initial profile as the module has to be in
        the same subfolder.
        """
        base_path = os.path.normcase(os.path.dirname(os.path.abspath(fname)))

        root.attrib["version"] = "7"
        for module in root.findall("import/module"):
            module.attrib["name"] = os.path.normpath(f"{base_path}\\{module.attrib["name"]}.py")

        return root

    def _convert_from_v7(self, root, fname=None):
        """Convert from a V7 profile to V8.

        This updates map to mouse actions to the new format.

        Parameters
        ----------
        root : ElementTree
            Root of the XML tree being modified

        Returns
        -------
        ElementTree
            Modified XML root element
        """
        root.attrib["version"] = "8"

        for node in root.findall(".//map-to-mouse"):
            node.set("time-to-max-speed", node.get("acceleration", "1.0"))

            axis = node.get("axis")
            direction = node.get("direction", 0)
            if axis == "x":
                direction = 90
            elif axis == "y":
                direction = 0
            node.set("direction", str(direction))
            node.set("button_id", "1")
            node.set("motion_input", "True")

        return root
    
    def _convert_to_ex(self, root, fname = None):
        ''' converts to the EX version '''

        root.attrib["version"] = "100"
        # syslog = logging.getLogger("system")

        config = gremlin.config.Configuration()
        convert_response_curve = config.convert_response_curve
        convert_vjoy_remap = config.convert_vjoy_remap


        # convert all response-curve to response-curve EX
        if convert_response_curve:        
            nodes = root.xpath("//response-curve")
            nodes.extend(root.xpath("//curve-data"))
            for node in nodes:
                node.tag = "response-curve-ex"

        # convert all remap to vjoy remap if configured in options
        
        if convert_vjoy_remap:
            nodes = root.xpath("//remap")
            for node in nodes:
                node.tag = "vjoyremap"

        return root

    def _convert_from_noop(self, root, fname = None):
        ''' no op conversion '''
        pass

    def _convert_from_v8(self, root, fname=None):
        """Convert from a V8 profile to V9.

        Performs the following changes:
        - Merge axis attribut'es reworked
          - vjoy.device => vjoy.vjoy-id
          - vjoy.axis => vjoy.axis-id
          - lower/upper.id => lower/upper.device-guid
          - lower/upper.axis => lower/upper.axis-id
        - Macro attribute changes
          - macro.actions.joystick
            - device_id => device-guid
            - input_type => input-type
            - input_id => input-id
          - macro.actions.key
            - scan_code => scan-code
          - macro.actions.vjoy
            - vjoy_id => vjoy-id
            - input_type => input-type
            - input_id => input-id
        - Map to keyboard
          - map-to-keyboard.key
            - scan_code => scan-code
        - Map to mouse
          - map-to-mouse
              - motion_input => motion-input
              - button_id => button-id
        - Split axis
          - split-axis
            - device1 => device-low-vjoy-id
            - axis1 => device-low-axis
            - device2 => device-high-vjoy-id
            - axis2 => device-high-axis
        - Conditions
          - condition
            - scan_code => scan-code
            - range_low => range-low
            - range_high => range-high
            - device_name => device-name
            - device_id => removed
            - windows_id => removed
            - device-guid => added

        Parameters
        ----------
        root : ElementTree
            Root of the XML tree being modified

        Returns
        -------
        ElementTree
            Modified XML root element
        """
        root.attrib["version"] = "10"
        # syslog = logging.getLogger("system")

        class GUIDConverter:

            """Simplifies conversion from old device identifiers to the new
            GUID ones."""

            def __init__(self):
                """Initializes the converter by caching needed values."""
                # Map for old hardware id to new guid value
                self.hwid_to_guid = {}
                self.dev_info = {}
                for dev in joystick_handling.all_joystick_devices():
                    hwid = (dev.vendor_id << 16) + dev.product_id
                    self.hwid_to_guid[hwid] = str(dev.device_guid)
                    self.dev_info[str(dev.device_guid)] = dev
                self.vjoy_to_guid = {}
                for dev in joystick_handling.vjoy_devices():
                    self.vjoy_to_guid[dev.vjoy_id] = str(dev.device_guid)

            def axis_lookup(self, device_guid, linear_id):
                """Returns the axis id for the given linear index.

                :param device_guid GUID of the device of interest
                :param linear_id linear axis index to convert into axis index
                :return axis index corresponding to the linear index
                """
                if device_guid not in self.dev_info:
                    return linear_id

                device = self.dev_info[device_guid]
                if linear_id > device.axis_count or linear_id >= len(device.axismap_list):
                    syslog.error(
                        f"Invalid linear axis id received, {device.name} id = {linear_id}"
                    )
                    return linear_id

                return device.axismap_list[linear_id].axis_index

            def lookup(self, hardware_id, name=None):
                """Returns the GUID for the provided hardware id.

                This will create a random GUID if the device is not currently
                connected.

                :param hardware_id old style hardware id
                :param name name of the device if available
                :return GUID corresponding to the provided hardware id
                """
                try:
                    hardware_id = int(hardware_id)
                except (ValueError, TypeError):
                    syslog.warn(
                        f"Cannot convert {hardware_id} into a valid hardware id"
                    )
                    return f"{{{uuid.uuid4()}}}"

                if hardware_id not in self.hwid_to_guid:
                    syslog.warn(
                        f"GUID for device {"" if name is None else name} with hardware_id {hardware_id} is unknown."
                    )
                    self.hwid_to_guid[hardware_id] = f"{{{uuid.uuid4()}}}"

                return self.hwid_to_guid[hardware_id]

            def vjoy_lookup(self, vjoy_id):
                """Returns the GUID corresponding to a specific vjoy device.

                This will create a random GUID if the device is not currently
                connected.

                :param vjoy_id vjoy id of the device
                :return GUID corresponding to the vjoy device
                """
                try:
                    vjoy_id = int(vjoy_id)
                except (ValueError, TypeError):
                    syslog.warn(
                        f"Cannot convert {vjoy_id} into a valid vjoy id"
                    )
                    return f"{{{uuid.uuid4()}}}"

                if vjoy_id not in self.vjoy_to_guid:
                    syslog.warn(
                        f"GUID for vjoy {vjoy_id} is unknown"
                    )
                    self.vjoy_to_guid[vjoy_id] = f"{{{uuid.uuid4()}}}"

                return self.vjoy_to_guid[vjoy_id]

        # Initialize the GUID converter
        uuid_converter = GUIDConverter()

        for entry in root.findall("devices/device"):
            if entry.attrib.get("type", None) == "keyboard":
                entry.set("device-guid", str(dinput.GUID_Keyboard))
            else:
                entry.set(
                    "device-guid",
                    uuid_converter.lookup(
                        entry.attrib.get("id", None),
                        entry.attrib.get("name", "")
                    )
                )

            # Remove the now obsolete id and windows id attributes
            del entry.attrib["id"]
            del entry.attrib["windows_id"]

            for child in entry.findall("mode/axis"):
                child.set(
                    "id",
                    str(uuid_converter.axis_lookup(
                        entry.attrib["device-guid"],
                        int(child.attrib["id"])-1
                    ))
                )

        for entry in root.findall("vjoy-devices/vjoy-device"):
            entry.set("vjoy-id", entry.attrib["id"])
            entry.set(
                "device-guid",
                uuid_converter.vjoy_lookup(int(entry.attrib["id"]))
            )
            del entry.attrib["id"]
            del entry.attrib["windows_id"]

        for entry in root.findall(".//condition"):
            replacements = [
                ("scan_code", "scan-code"),
                ("range_low", "range-low"),
                ("range_high", "range-high"),
                ("device_name", "device-name")
            ]
            for rep in replacements:
                if rep[0] in entry.keys():
                    entry.set(rep[1], entry.attrib[rep[0]])
                    del entry.attrib[rep[0]]
            if "device_id" in entry.keys():
                entry.set(
                    "device-guid",
                    uuid_converter.lookup(entry.attrib.get("device_id", None))
                )
                del entry.attrib["device_id"]
                del entry.attrib["windows_id"]
            if entry.attrib["input"] == "action":
                entry.set("condition-type", "action")
            elif entry.attrib["input"] == "keyboard":
                entry.set("condition-type", "keyboard")
            elif entry.attrib["input"] in ["axis", "button", "hat"]:
                entry.set("condition-type", "joystick")

        for entry in root.findall(".//macro/actions/joystick"):
            entry.set(
                "device-guid",
                uuid_converter.lookup(entry.attrib.get("device_id", None))
            )
            entry.set("input-type", entry.attrib["input_type"])
            entry.set("input-id", entry.attrib["input_id"])
            del entry.attrib["device_id"]
            del entry.attrib["input_type"]
            del entry.attrib["input_id"]

        for entry in root.findall(".//macro/actions/key"):
            entry.set("scan-code", entry.attrib["scan_code"])
            del entry.attrib["scan_code"]

        for entry in root.findall(".//macro/actions/vjoy"):
            entry.set("vjoy-id", entry.attrib["vjoy_id"])
            entry.set("input-type", entry.attrib["input_type"])
            entry.set("input-id", entry.attrib["input_id"])
            del entry.attrib["vjoy_id"]
            del entry.attrib["input_type"]
            del entry.attrib["input_id"]

        for entry in root.findall(".//merge-axis/vjoy"):
            entry.set("vjoy-id", entry.attrib["device"])
            entry.set("axis-id", entry.attrib["axis"])
            del entry.attrib["device"]
            del entry.attrib["axis"]

        for entry in root.findall(".//merge-axis/lower"):
            entry.set(
                "device-guid",
                uuid_converter.lookup(entry.attrib.get("id", None))
            )
            entry.set("axis-id", entry.attrib["axis"])
            del entry.attrib["id"]
            del entry.attrib["axis"]
            del entry.attrib["windows_id"]

        for entry in root.findall(".//merge-axis/upper"):
            entry.set(
                "device-guid",
                uuid_converter.lookup(entry.attrib.get("id", None))
            )
            entry.set("axis-id", entry.attrib["axis"])
            del entry.attrib["id"]
            del entry.attrib["axis"]
            del entry.attrib["windows_id"]

        for entry in root.findall(".//map-to-keyboard/key"):
            entry.set("scan-code", entry.attrib["scan_code"])
            del entry.attrib["scan_code"]

        for entry in root.findall(".//map-to-mouse"):
            entry.set("motion-input", entry.attrib["motion_input"])
            entry.set("button-id", entry.attrib["button_id"])
            del entry.attrib["motion_input"]
            del entry.attrib["button_id"]

        for entry in root.findall(".//split-axis"):
            entry.set("device-low-vjoy-id", entry.attrib["device1"])
            entry.set("device-low-axis", entry.attrib["axis1"])
            entry.set("device-high-vjoy-id", entry.attrib["device2"])
            entry.set("device-high-axis", entry.attrib["axis2"])
            del entry.attrib["device1"]
            del entry.attrib["axis1"]
            del entry.attrib["device2"]
            del entry.attrib["axis2"]

        plugins_node = etree.Element("plugins")
        for entry in root.findall(".//import/module"):
            p_node = etree.Element("plugin")
            p_node.set("file-name", entry.attrib["name"])

            i_node = etree.Element("instance")
            i_node.set("name", "Default")

            p_node.append(i_node)
            plugins_node.append(p_node)
        root.append(plugins_node)

        for entry in root.findall("import"):
            root.remove(entry)

        return root

    def _convert_from_v10(self, root, fname = None):
        ''' convert from V10 - looks for profile start/stop and move to new master mode '''
        import gremlin.shared_state
        master_mode = gremlin.shared_state.master_mode

        root.attrib["version"] = "11" # change version

        # look for mode control input nodes
        nodes = root.xpath("//device[@type='mode']")
        if nodes:
            device_node = nodes[0]

            # locate the correct mode
            nodes = device_node.xpath(f"//mode[@name='{master_mode}']")
            if nodes:
                master_node = nodes[0]
                # remove any empty profile start/stop nodes
                nodes = master_node.xpath("modecontrol[not(*) and (@id='5' or @id='6')]")
                for node in nodes:
                    master_node.remove(node)
            else:
                # create it
                master_node = lxml.etree.Element("mode", name=master_mode, system='True')
                device_node.append(master_node)

            nodes = device_node.xpath("//modecontrol[@id='5' or @id='6']") # profile start or profile stop
            for node in nodes:
                mode_node = node.getparent()
                if mode_node != master_node:
                    # move the node to the correct parent
                    mode_node.remove(node)
                    master_node.append(node)
                    

        return root


    def _convert_from_v11(self, root, fname = None):
        ''' convert from V11 - convert from state keys to state key and IDs '''
        import gremlin.ui.state_device

        id_map = {}
        state_map = {}
        map_to_state_map = {}

        root.attrib["version"] = "12" # change version

        # calatog map to state nodes
        map_nodes = root.xpath("//map_to_state")
        for node in map_nodes:
            key = safe_read(node, "key", str, "")
            map_to_state_map[key] = node
        
        #root = node.getroottree().getroot()
        state_nodes = root.xpath("//profile/states/state")
        for node in state_nodes:
            id = safe_read(node,"id", str, "")
            key = safe_read(node,"key", str, "")
            if key:
                # state exists check for ID field
                if not id:
                    id = gremlin.util.getguid()
                    node.set("id", id)
                id_map[key] = id
                state_map[key] = node

        # identify any missing states (states referenced in map to state but not in states )
        missing_state_keys = [key for key in map_to_state_map if not key in state_map]
        
        # look for state nodes
        nodes = root.xpath("//profile/states")
        if nodes:
            state_root = nodes[0]
        else:
            # state root entry does not exist - create it
            nodes = root.xpath("//profile")
            profile_root = nodes[0]
            state_root = ElementTree.Element("states")
            profile_root.append(state_root)

        # add missing state keys 
        for key in missing_state_keys:
            state = gremlin.ui.state_device.StateInputItem(key)
            node = state.to_xml()
            state_root.append(node)
            state_map[key] = node
            

        
        # look for state entries under the states node
        for key in state_map:
            state = gremlin.ui.state_device.StateInputItem(key)
            node = state_map[key]
            state.from_xml(node)

            id = id_map[key]
            if state.id != id:
                state.id = id
                

        # look for map to state entries in the profile
        # and add the ID attribute if needed
        for node in map_nodes:
            key = safe_read(node,"key", str, "")
            id = safe_read(node,"state-id", str, "")
            if not id:
                # missing id in map to state - add it
                id = id_map[key]
                node.set("state-id",id)
                
        return root


        

    def _convert_from_v12(self, root, fname = None):
        ''' convert from V12 to V13 - convert master mode GUID to new format  '''
        import gremlin.util
        root.attrib["version"] = "13" # change version

        # calatog map to state nodes
        nodes = root.xpath("//mode")
        master_mode = gremlin.shared_state.master_mode
        for node in nodes:
            if "name" in node.attrib:
                name = node.get("name")
                if name == "{B3B159A0-4D06-4BD6-93F9-7583EC08B877}":
                    node.set("name", master_mode)

        # convert device GUIDs
        nodes = root.xpath("//devices/device")
        for node in nodes:
            if "device-guid" in node.attrib:
                id = node.get("device-guid")
                node.set("device_guid", gremlin.util.normalize_guid(id))



        return root
            
    def _convert_from_v13(self, root, fname = None):
        ''' convert from V13 to V14 - convert merge operation scale name changes '''
        import gremlin.util
        root.attrib["version"] = "14" # change version

        # calatog map to state nodes
        nodes = root.xpath("//merge-data")
        for node in nodes:
            if "operation" in node.attrib:
                operation = node.get("operation")
                if operation == "scalehalf":
                    node.set("operation","scalehalfc")
                elif operation == "scalefull":
                    node.set("operation","scalefullc")

        return root
            
            
    def _convert_from_v14(self, root, fname = None):
        ''' convert from V14 to V15 - ensure modes are in the Mode section due to change in how modes are read for a profile  '''
        import gremlin.util
        import gremlin.base_profile
        root.attrib["version"] = "15" # change version

        # calatog all modes in the profile 
        mode_map = {}
        nodes = root.xpath("//profile/modes")


        if nodes:
            # exists already
            return root # no changes 
    
        # create
        mode_root = etree.Element("modes")
        root.append(mode_root)

        # add any mode in the devices
        mode_nodes = root.xpath("//device/mode")
  
        for node_mode in mode_nodes:
            mode_name = node_mode.get("name")
            mode_object = gremlin.base_profile.ModeNode()
            mode_object.name = mode_name
            if not mode_name in mode_map:
                if "inherit" in node_mode.attrib:
                    parent_mode_name = node_mode.get("inherit")
                    mode_object.parent_name = parent_mode_name
                mode_map[mode_name] = mode_object

        # ensure the master mode exists
        master_mode = gremlin.shared_state.master_mode                
        if not master_mode in mode_map:
            mode_object = gremlin.base_profile.ModeNode()
            mode_object.name = master_mode
            mode_map[master_mode] = mode_object

        # write the update data out

        for mode_object in mode_map.values():
            mode_node = etree.Element("mode")
            mode_node.set("name", mode_object.name)
            if mode_object.parent_name:
                mode_node.set("inherit", mode_object.parent_name)
            # add the new node
            mode_root.append(mode_node)


        return root

    def _convert_from_v15(self, root, fname = None):
        ''' convert from V15 to V16 - convert macro button values from boolean to the new set to support toggle '''
        import gremlin.util
        root.attrib["version"] = "16" # change version

        syslog.info("PROFILE CONVERT: V16")

        # change value for button macro actions from boolean to actual action names
        nodes = root.xpath("//macro/actions/vjoy[@input-type='button']")
        for node in nodes:
            value = safe_read(node, "value", str, "")
            new_value = None
            match value.casefold():
                case "true":
                    new_value = "press"
                case "false":
                    new_value = "release"
            if new_value:
                node.set("value", new_value)

        return root
            
    
    def _p3_extract_map_to_keyboard(self, input_item):
        """Converts an old macro setup to a map to keyboard action.

        Previously a certain pattern was used to achieve a keyboard press
        forwarding. With the introduction of a dedicated action for this,
        actions following this pattern are being converted.

        :param input_item the InputItem containing the old macro definitions
        :return map to keyboard node representing the old macros
        """
        node = etree.Element("map-to-keyboard")

        for action in input_item:
            assert action.tag == "macro"

            for key in action:
                if key.tag == "key":
                    key_node = etree.Element("key")
                    key_node.set("scan_code", key.get("scan_code"))
                    key_node.set("extended", key.get("extended"))
                    node.append(key_node)
            break

        return node


class ProfileModifier:

    """Modifies profile contents and provides overview information."""

    def __init__(self, profile):
        """Creates a modifier for a specific profile.

        :param profile the profile to be modified
        """
        self.profile = profile

    def device_information_list(self):
        """Returns the list of device information present in the profile.

        :return list of devices used in the profile and information about them
        """
        import gremlin.base_conditions
        device_guids = []
        device_names = {}
        for guid, dev in self.profile.devices.items():
            device_guids.append(guid)
            device_names[guid] = dev.name
        for cond in self.all_conditions():
            if isinstance(cond, gremlin.base_conditions.JoystickCondition):
                device_guids.append(cond.device_guid)
                device_names[cond.device_guid] = cond.device_name
        for entry in self.profile.merge_axes:
            for key in ["lower", "upper"]:
                device_guids.append(entry[key]["device_guid"])

        device_info = []
        for device_guid in set(device_guids):
            device_info.append(gremlin.base_profile.ProfileDeviceInformation(
                device_guid,
                device_names.get(device_guid, "Unknown"),
                self.container_count(device_guid),
                self.condition_count(device_guid),
                self.merge_axis_count(device_guid)
            ))

        return device_info

    def container_count(self, device_guid):
        """Returns the number of containers associated with a device.

        :param device_guid GUID of the target device
        :return number of containers associated with the given device
        """
        count = 0
        for dev_guid, device in self.profile.devices.items():
            if dev_guid == device_guid:
                for mode in device.modes.values():
                    for input_items in mode.config.values():
                        for input_item in input_items.values():
                            count += len(input_item.containers)
        return count

    def condition_count(self, device_guid):
        """Returns the number of conditions associated with a device.

        :param device_guid GUID of the target device
        :return number of conditions associated with the given device
        """
        from gremlin.base_conditions import JoystickCondition
        count = 0
        for cond in self.all_conditions():
            if isinstance(cond, JoystickCondition) and \
                    cond.device_guid == device_guid:
                count += 1
        return count

    def merge_axis_count(self, device_guid):
        """Returns the number of merge axes associated with a device.

        :param device_guid GUID of the target device
        :return number of merge axes associated with the given device
        """
        count = 0
        for entry in self.profile.merge_axes:
            for key in ["lower", "upper"]:
                if entry[key]["device_guid"] == device_guid:
                    count += 1
        return count

    def change_device_guid(self, source_guid, target_guid):
        """Performs actions necessary to move all data from source to target.

        Moves all profile content from a given source device to the desired
        target device.

        :param source_guid identifier of the source device
        :param target_guid identifier of the target device
        """

        if source_guid == target_guid:
            syslog.warning(
                "Swap devices: Source and target device are identical"
            )
            return

        self.change_device_actions(source_guid, target_guid)
        self.change_conditions(source_guid, target_guid)
        self.change_merge_axis(source_guid, target_guid)

    def change_device_actions(self, source_guid, target_guid):
        """Moves actions from the source device to the target device.

        :param source_guid identifier of the source device
        :param target_guid identifier of the target device
        """
        source_dev = self._get_device(source_guid)
        target_dev = self._get_device(target_guid)

        # Can't move anything from a non-existent source device
        if source_dev is None:
            syslog.warning(
                "Swap devices: Specified a source device that doesn't exist"
            )
            return

        # Retrieve target device information structure to get its name and
        # properly initialize modes if needed
        target_hardware_device = None
        for dev in joystick_handling.all_joystick_devices():
            if dev.device_guid == target_guid:
                target_hardware_device = dev

        # If there is no target device configuration present we can rename
        # the source device configuration into the target device and avoid
        # copying and deleting things.
        if target_dev is None:
            if target_hardware_device is None:
                syslog.warning(
                    "Swap devices: Empty target device configuration found"
                )
                return
            source_dev.device_guid = target_guid
            source_dev.name = target_hardware_device.name
            return

        # Ensure modes present in the source device exist in the target device
        for mode_name in source_dev.modes:
            target_dev.ensure_mode_exists(mode_name, target_hardware_device)

        # Move container entries from source to target as long as there is a
        # matching input item available
        for mode in source_dev.modes.values():
            target_mode = target_dev.modes[mode.name]
            for input_items in mode.config.values():
                for input_item in input_items.values():
                    input_type = input_item.input_type
                    input_id = input_item.input_id

                    if input_id not in target_mode.config[input_type]:
                        syslog.warning(
                            "Swap devices: Source input id not present in "
                            "target device"
                        )
                        continue

                    # Move containers from source to target input item
                    target_input_item = target_mode.config[input_type][input_id]

                    for container in input_item.containers:
                        container.parent = target_input_item
                        target_mode.config[input_type] \
                            [input_id].containers.append(container)

                    # Remove all containers from the source device
                    input_item.containers.clear()

        # Remove the device entry completely
        del self.profile.devices[source_guid]


    def change_conditions(self, source_guid, target_guid):
        """Modifies conditions to use the target device instead of the
        source device.

        :param source_guid identifier of the source device
        :param target_guid identifier of the target device
        """
        # TODO: Does not ensure conditions are valid, i.e. missing inputs
        import gremlin.base_conditions
        target_hardware_device = None
        for dev in joystick_handling.all_joystick_devices():
            if dev.device_guid == target_guid:
                target_hardware_device = dev

        for condition in self.all_conditions():
            if isinstance(condition, gremlin.base_conditions.JoystickCondition):
                if condition.device_guid == source_guid:
                    condition.device_guid = target_guid
                    condition.device_name = target_hardware_device.name

    def change_merge_axis(self, source_guid, target_guid):
        """Modifies merge axis entries to use the target device instead of the
        source device.

        :param source_id identifier of the source device
        :param target_id identifier of the target device
        """
        # TODO: Does not ensure assignments are valid, i.e. missing axis
        for entry in self.profile.merge_axes:
            for key in ["lower", "upper"]:
                if entry[key]["device_guid"] == source_guid:
                    entry[key]["device_guid"] = target_guid

    def device_names(self):
        """Returns a mapping from hardware ids to device names.

        :return mapping of hardware ids to device names
        """
        import gremlin.base_conditions
        name_map = {}
        for device in self.profile.devices.values():
            name_map[device.device_guid] = device.name
        for cond in self.all_conditions():
            if isinstance(cond, gremlin.base_conditions.JoystickCondition):
                name_map[cond.device_guid] = cond.device_name
        return name_map

    def all_conditions(self):
        """Returns a list of all conditions.

        :return list of all conditions
        """
        all_conditions = []
        for device in self.profile.devices.values():
            for mode in device.modes.values():
                for input_items in mode.config.values():
                    for input_item in input_items.values():
                        for container in input_item.containers:
                            if container.activation_condition is not None:
                                all_conditions.extend(
                                    container.activation_condition.conditions
                                )
        return all_conditions

    def _get_device(self, device_guid):
        """Returns the device corresponding to a given identifier.

        :return device_guid matching the identifier if present
        """
        for dev_guid, device in self.profile.devices.items():
            if dev_guid == device_guid:
                return device
        return None

def parse_guid(value):
    # parses a GUID
    from gremlin.util import parse_guid
    return parse_guid(value)

