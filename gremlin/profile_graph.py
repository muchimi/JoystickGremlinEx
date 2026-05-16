# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
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



''' profile tree module

Implements the various tree functions to manipulate a profile using a graph data structure

'''


# from __future__ import annotations # deprecated with python 3.14+


from collections import namedtuple
import os
import copy
import logging
import time
from typing import Union, Any


import gremlin.joystick_handling
import dinput
import enum
from enum import auto
import anytree
from anytree import NodeMixin

import gremlin.joystick_handling
import gremlin.plugin_manager
import gremlin.types
import gremlin.ui
import gremlin.ui.ui_common
import gremlin.util
import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
import gremlin.shared_state
from gremlin.singleton_decorator import SingletonDecorator

import PySide6
from PySide6 import QtCore, QtGui, QtWidgets, QtMultimedia
# from gremlin.util import *
from gremlin.types import DeviceType, TabDeviceType
from gremlin.input_types import InputType
import gremlin.util
from gremlin.util import safe_read
from gremlin.ui import ui_common
from gremlin.clipboard import Clipboard
# from gremlin.input_types import InputType
import dinput
import uuid
import copy

import dinput
from dinput import DeviceSummary
import gremlin.base_classes
import gremlin.base_profile
import gremlin.event_handler
import gremlin.shared_state
from vjoy import vjoy

import gremlin.config
from gremlin.ui import ui_common
from gremlin.util import parse_guid, safe_format, safe_read, get_guid, write_guid, read_bool
import gremlin.import_profile

#from xml.dom import minidom
import lxml
from lxml import etree
from lxml.etree import _Element as Element

from abc import ABC, abstractmethod
import sys
import psygnal
from psygnal import Signal
import html

syslog = logging.getLogger("system")


class ProfileNodeType(enum.Enum):
    ''' node types '''
    Profile = auto() # root node
    Device = auto()
    Mode = auto()
    Input = auto()
    Container = auto()
    Action = auto()
    MergedAxis = auto()


class ProfileBaseNode(ABC, NodeMixin):
    ''' abstract class for a profile node '''
    def __init__(self, node_type : ProfileNodeType):
        super().__init__()
        self.nodeType = node_type
        self.id = get_guid()
        self._description = None # descriptive text for this node

    @abstractmethod
    def from_xml(self, node, data = None, extra_data = None):
        ''' '''
        pass

    @abstractmethod
    def to_xml(self):
        ''' returns a XML node '''
        pass



class ProfileRootNode(ProfileBaseNode):
    ''' device node '''
    def __init__(self, source_xml : str = None):
        super().__init__(ProfileNodeType.Profile)
        self.start_mode = None # profile start mode
        self.default_start_mode = None # profile default start mode
        self.restore_last_mode = False # true if last mode is restored
        self.force_numlock_off = True # true if numlock should be forced off on profile start
        self.devices = {} # map of device to device node, keyed by device_guid
        self.simconnect_modes = {} # map of simconnect key to profile mode
        self.source_xml = source_xml # source file
        self._graph_modes = {} # list of mode definitions in the graph
        self._load_default_devices()




    def from_xml(self, node, data = None, extra_data = None):
        self._start_mode = None
        if "start_mode" in node.attrib:
            self.start_mode = node.get("start_mode")

        if "default_start_mode" in node.attrib:
            # older version of profile
            self.default_start_mode = node.get("default_start_mode")
        if "default_mode" in node.attrib:
            self.default_start_mode = node.get("default_mode")

        self.restore_last_mode = False
        if "restore_last" in node.attrib:
            self.restore_last_mode = safe_read(node, "restore_last", bool, False)

        if "force_numlock" in node.attrib:
            self.force_numlock_off = safe_read(node, "force_numlock", bool, True)

        # parse modes
        node_list = node.xpath("//profile/modes")
        self._graph_modes.clear()
        if node_list:
            mode_nodes = node_list[0]
            for mode_node in mode_nodes:
                profile_mode_node = ProfileModeNode()
                profile_mode_node.from_xml(mode_node)
                self._graph_modes[profile_mode_node.name] = profile_mode_node

        for mode_name in self._graph_modes:
            profile_mode_node = self._graph_modes[mode_name]
            parent_name = profile_mode_node.inherit
            if parent_name:
                parent_mode_node = self._graph_modes[parent_name]
                profile_mode_node.parent = parent_mode_node


        # Parse each device
        self.devices = {}
        for child in node.iter("device"):
            if not "type" in child.attrib:
                # not a device node we are looking for
                continue

            device_node = ProfileDeviceNode(parent = self)
            device_node.from_xml(child, data)
            self.devices[device_node.device_guid] = device_node


        # Parse each vjoy device into separate DeviceConfiguration objects
        self.vjoy_devices = {}
        for child in node.iter("vjoy-device"):
            device_node = ProfileDeviceNode(parent = self)
            device_node.from_xml(child, data)
            self.vjoy_devices[device_node.device_guid] = device_node

        for child in node.iter("simconnect"):
            key_cp = safe_read(child,"key_cp", str, "")
            key_ap = safe_read(child,"key_ap", str, "")
            mode = safe_read(child,"mode", str, "")
            key = (key_cp, key_ap)
            self.simconnect_modes[key] = mode

        # legacy merge axis
        for child in node.iter("merge-axis"):
            merged_node = ProfileMergedAxisNode(self)
            merged_node.from_xml(child)

    def _load_default_devices(self):
        ''' loads default devices '''
        devices = gremlin.joystick_handling.physical_devices()
        device: dinput.DeviceSummary
        for device in devices:
             device_node = ProfileDeviceNode(device, parent = self)
             self.devices[device_node.device_guid] = device_node



    def to_xml(self):
        ''' writes a profile node '''

        node = etree.Element("profile")
        node.set("version", str(gremlin.profile.ProfileConverter.current_version))
        if not self.start_mode:
            self.start_mode = gremlin.shared_state.edit_mode
        node.set("start_mode", self.start_mode)
        node.set("default_mode", self.default_start_mode)
        node.set("restore_last", str(self.restore_last_mode))
        node.set("force_numlock", str(self.force_numlock_off))

        for child in self.children:
            child_node = child.to_xml()
            if child_node is not None:
                node.append(child_node)

        return node


class RemapData():
    ''' holds remap information '''
    def __init__(self, source_device, target_device, device_node):
        self.source_device : DeviceSummary = source_device # source device from the input
        self.target_device : DeviceSummary = target_device # target device to remap to
        self.device_node : ProfileDeviceNode = device_node  # source device node


class DeviceCopyDialogUI(ui_common.QShowAtCursorDialog):
    def __init__(self, device_guid = None, parent = None):
        super().__init__(self.__class__.__name__, parent)

        self.setWindowTitle("Device Assignment Copy")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.main_layout = QtWidgets.QVBoxLayout(self)

        warning_widget = gremlin.ui.ui_common.QWarningWidget("This is an experimental feature.")
        self.main_layout.addWidget(warning_widget)

        self.source_device = gremlin.joystick_handling.device_info_from_guid(device_guid)
        if not self.source_device:
            syslog.error(f"Device copy: source [{device_guid}] device not found")
            self.close()

        self.device_selector = gremlin.ui.ui_common.QDataComboBox()
        devices = gremlin.joystick_handling.all_joystick_devices()
        devices = [dev for dev in devices if dev.device_guid != self.source_device.device_guid and dev.device_type == self.source_device.device_type]

        if not devices:
            syslog.error("Device copy: no valid target devices found.")
            self.close()

        for device in devices:
            self.device_selector.addItem(device.name, device)


        self.target_device = self.device_selector.currentData()
        self.device_selector.currentIndexChanged.connect(self._device_changed)

        widget = gremlin.ui.ui_common.getHContainer(["Target Device:", self.device_selector], widget_only = True)
        self.main_layout.addWidget(widget)

        self.main_layout.addWidget(QtWidgets.QWidget()) # separator
        ok_button_widget =  QtWidgets.QPushButton("Ok")
        ok_button_widget.clicked.connect(self._execute_cb)
        cancel_button_widget = QtWidgets.QPushButton("Cancel")
        cancel_button_widget.clicked.connect(self._close_cb)
        button_container_widget = gremlin.ui.ui_common.getHContainer([ok_button_widget, cancel_button_widget], left_stretch=True, widget_only = True)

        self.main_layout.addWidget(button_container_widget)

    @QtCore.Slot()
    def _device_changed(self):
        self.target_device = self.device_selector.currentData()


    @QtCore.Slot()
    def _execute_cb(self):
        self.setResult(QtWidgets.QDialog.DialogCode.Accepted)
        self.close()



    @QtCore.Slot()
    def _close_cb(self):
        self.setResult(QtWidgets.QDialog.DialogCode.Rejected)
        self.close()


class DeviceRemapDialogUI(ui_common.BaseDialogUi):
    ''' dialog box to handle a profile remap between like devices '''
    def __init__(self, graph : ProfileGraph, parent=None, device_guid = None):
        super().__init__(self.__class__.__name__, parent)

        self._remap_map = {} # map of profile device node ID to RemapData object holding the configured mapping information

        self.setWindowTitle("Device Remap Manager")
        #self.setModal(True)

        self.main_layout = QtWidgets.QVBoxLayout(self)

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

        self.scroll_layout.addWidget(self.map_widget)
        self.scroll_layout.addStretch()

        self._graph = graph

          # Add header information
        header_widget, layout = ui_common.getHContainer(QtWidgets.QLabel("Joystick Device Mappings:"))

        ok_button_widget =  QtWidgets.QPushButton("Ok")
        ok_button_widget.clicked.connect(self._execute_cb)
        cancel_button_widget = QtWidgets.QPushButton("Cancel")
        cancel_button_widget.clicked.connect(self._close_cb)
        button_container_widget, button_container_layout = gremlin.ui.ui_common.getHContainer(
            [ok_button_widget, cancel_button_widget], left_stretch=True)

        profile_node = graph.root

        self.main_layout.addWidget(header_widget)
        self.main_layout.addWidget(self.scroll_area)
        self.main_layout.addWidget(button_container_widget)

        self._device_nodes, self._source_map = self._derive_source_device_data(profile_node, device_guid)

        self.update_ui(profile_node)

        gremlin.util.popCursorTemporary(True)


    @QtCore.Slot()
    def _execute_cb(self):
        if self.remap():
            self.close()

    @QtCore.Slot()
    def _close_cb(self):
        self.close()

    def closeEvent(self, event):

        # clear any remaining callbacks
        device_node: ProfileDeviceNode
        for device_node in self._device_nodes:
            device_node.enable_changed_callback = None

        gremlin.util.popCursorTemporary()
        return super().closeEvent(event)

    def _derive_source_device_data(self, profile_node : ProfileRootNode, device_guid = None):
        ''' looks at the profile tree to grab capabilities of the mapped input devices
        :param profile_node: root profile node
        :param device_guid: optional if limits the list to that specific device

        :returns (node_list, source_map[device_guid] = DeviceSummary of the source )

            '''
        self._source_map = {} # map of source devices keyed by device_guid -> DeviceSummary object
        device_node : ProfileDeviceNode
        mode_node : ProfileModeNode
        input_node : ProfileInputNode

        device_nodes = [node for node in profile_node.children if node.nodeType == ProfileNodeType.Device]

        if device_guid:
            # remap a single device
            device_id = gremlin.util.normalize_guid(device_guid) if not isinstance(device_guid, str) else device_guid
            device_nodes = [node for node in device_nodes if node.device_id == device_id]
        else:
            # remap all disconnected devices
            device_nodes = [node for node in device_nodes if not node.connected]

        source_map = {}
        for device_node in device_nodes:
            axis_set = set()
            button_set = set()
            hat_set = set()

            for mode_node in device_node.children:
                for input_node in mode_node.children:
                    input_id = input_node.input_id
                    match input_node.input_type:
                        case InputType.JoystickAxis:
                            axis_set.add(input_id)
                        case InputType.JoystickButton:
                            button_set.add(input_id)
                        case InputType.JoystickHat:
                            hat_set.add(input_id)

            source_device = DeviceSummary()
            source_device.axis_count = len(axis_set)
            source_device.button_count = len(button_set)
            source_device.hat_count = len(hat_set)
            source_device.name = device_node.device_name
            source_device.device_guid = device_node.device_guid
            source_device.device_type = device_node.device_type

            source_map[device_node.device_guid] = source_device

        return device_nodes, source_map


    def update_ui(self, profile_node):
        ''' populates the UI mapping for joysticks only - the other devices always map 1:1 '''
        map_layout = self.map_layout
        ui_common.clear_layout(map_layout)
        device_nodes = self._device_nodes
        row = 0

        self._target_device_type_map = {}
        self._target_device_guid_map = {}
        self._enabled_widget_map = {} # holds the map of check boxes keyed by node

        device_node : ProfileDeviceNode

        select_all_widget = QtWidgets.QPushButton("Select All")
        select_all_widget.clicked.connect(self._select_all)
        select_none_widget = QtWidgets.QPushButton("Select None")
        select_none_widget.clicked.connect(self._select_none)

        widget, layout = ui_common.getHContainer([select_all_widget, select_none_widget])
        map_layout.addWidget(widget, row, 0, 1 , 2, alignment = QtCore.Qt.AlignmentFlag.AlignLeft)
        map_layout.addWidget(QtWidgets.QLabel(""),row,2)
        row+=1


        for device_node in device_nodes:
            if device_node.device_type in (DeviceType.Joystick, DeviceType.VJoy):

                source_device : DeviceSummary = self._source_map[device_node.device_guid]

                enable_widget = ui_common.QDataCheckbox("Enable", data = device_node)
                enable_widget.setToolTip("Enables remap")
                enable_widget.setChecked(device_node.enabled)
                enable_widget.clicked.connect(self._enabled_changed)
                self._enabled_widget_map[device_node] = enable_widget
                device_node.enable_changed_callback = self._enable_change_cb

                map_layout.addWidget(enable_widget, row, 0)
                row+=1

                source_device_name_widget = ui_common.QDataLineEdit(device_node.device_name)
                source_device_name_widget.setReadOnly(True)

                source_device_guid_widget = ui_common.QDataLineEdit(device_node.device_id)
                source_device_guid_widget.setReadOnly(True)

                source_device_type_widget = ui_common.QDataLineEdit(device_node.device_type.name)
                source_device_type_widget.setReadOnly(True)

                target_device_list_widget = ui_common.QDataComboBox(data = (source_device, device_node))
                self._populate_devices(target_device_list_widget, device_node)
                target_device : DeviceSummary = target_device_list_widget.currentData()


                target_id = target_device.device_id
                target_device_guid_widget = ui_common.QDataLineEdit(target_id)
                target_device_guid_widget.setReadOnly(True)

                self._target_device_guid_map[device_node.id] = target_device_guid_widget


                target_device_type_widget = ui_common.QDataLineEdit(target_device.device_type.name)
                target_device_type_widget.setReadOnly(True)
                self._target_device_type_map[device_node.id] = target_device_type_widget

                target_device_list_widget.currentIndexChanged.connect(self._target_device_changed)


                col = 0
                map_layout.addWidget(QtWidgets.QLabel("Source Device:"), row, col)
                col+=1
                map_layout.addWidget(source_device_name_widget, row, col)

                col+=1
                map_layout.addWidget(QtWidgets.QLabel("Target Device:"), row, col)
                col+=1
                map_layout.addWidget(target_device_list_widget, row, col)

                row +=1
                col = 0
                map_layout.addWidget(QtWidgets.QLabel("Source GUID:"), row, col)
                col +=1
                map_layout.addWidget(source_device_guid_widget, row, col)

                col+=1
                map_layout.addWidget(QtWidgets.QLabel("Target GUID:"), row, col)
                col+=1
                map_layout.addWidget(target_device_guid_widget, row, col)


                row +=1
                col = 0
                map_layout.addWidget(QtWidgets.QLabel("Source Type:"), row, col)
                col +=1
                map_layout.addWidget(source_device_type_widget, row, col)

                col +=1
                map_layout.addWidget(QtWidgets.QLabel("Target Type:"), row, col)
                col +=1
                map_layout.addWidget(target_device_type_widget, row, col)

                # row separator
                row+=1
                map_layout.addWidget(QtWidgets.QLabel(" "), row, 0)

                row+=1


    @QtCore.Slot()
    def _select_all(self):
        ''' deselects all mappings '''
        device_nodes = self._device_nodes
        for device in device_nodes:
            device.enabled = True

    @QtCore.Slot()
    def _select_none(self):
        ''' selects all mappings '''
        device_nodes = self._device_nodes
        for device in device_nodes:
            device.enabled = False

    def _enable_change_cb(self, device_node : ProfileDeviceNode):
        ''' callback when the device changes '''
        widget = self._enabled_widget_map[device_node]
        with QtCore.QSignalBlocker(widget):
            widget.setChecked(device_node.enabled)


    @QtCore.Slot(bool)
    def _enabled_changed(self, checked : bool):
        ''' individual mapping select for remap '''
        widget = self.sender()
        node = widget.data
        node.enabled = checked

    def _populate_devices(self, widget : QtWidgets.QComboBox, device_node : ProfileDeviceNode):
        ''' populates available devices to map to '''
        widget.clear()
        selected_index = None
        device_id = device_node.device_id
        match device_node.device_type:
            case DeviceType.Joystick:
                devices = gremlin.joystick_handling.all_joystick_devices()
                device : DeviceSummary
                for index, device in enumerate(devices):
                    widget.addItem(device.name, device)
                    if device.device_id == device_id:
                        selected_index = index

            case DeviceType.VJoy:
                devices = gremlin.joystick_handling.vjoy_devices()
                device : DeviceSummary
                for index, device in enumerate(devices):
                    widget.addItem(device.name, device)
                    if device.device_id == device_id:
                        selected_index = index

        if selected_index is not None:
            widget.setCurrentIndex(selected_index)

    @QtCore.Slot()
    def _target_device_changed(self):
        ''' target changed '''
        widget = self.sender()
        device_node : ProfileDeviceNode
        source_device : DeviceSummary
        source_device, device_node = widget.data
        target_device : DeviceSummary = widget.currentData() # the device being mapped
        target_id = target_device.device_id
        source_id = source_device.device_id
        node_id = device_node.id

        data = RemapData(source_device, target_device, device_node)
        self._remap_map[node_id] = data

        self._target_device_guid_map[node_id].setText(target_id)
        self._target_device_type_map[node_id].setText(target_device.device_type.name)



    def _merge_node(self, parent_node, node):
        ''' adds or merges a node recursively '''
        merge_node = None
        match node.nodeType:
            case ProfileNodeType.Mode:
                merge_node = next((n for n in parent_node.children if n.nodeType == ProfileNodeType.Mode and n.name == node.name),None)
            case ProfileNodeType.Input:
                merge_node = next((n for n in parent_node.children if n.nodeType == ProfileNodeType.Input and n.name == node.name),None)

        if merge_node:
            # merge node exists, re-use
            for child in node.children:
                self._merge_node(merge_node, child)
        else:
            # new node, just attach it
            node.parent = parent_node

    def _dump(self):
        ''' dumps the graph '''
        syslog.info(f"Profile Graph Tree:")
        root = self._graph.root
        if root:
            for pre, fill, node in anytree.RenderTree(root, style=anytree.AsciiStyle()):
                syslog.info(f"{pre}{str(node)}")

    def _get_device_node(self, device_guid):
        return self._graph.get_device_node(device_guid)

    def remap(self) -> bool:
        gremlin.util.pushCursor()
        data : RemapData
        has_changes = False
        self._dump()
        for data in self._remap_map.values():
            device_node = data.device_node
            if not device_node.enabled:
                # not enabled by the user - skip remap
                continue
            if data.source_device.device_guid != data.target_device.device_guid:
                # remap the device

                target_node = self._get_device_node(data.target_device.device_guid)
                source_node =self._get_device_node(data.source_device.device_guid)

                # merge the mode nodes
                for node in source_node.children:
                    self._merge_node(target_node, node)

                # remove the source node
                source_node.parent = None

                # device_node = data.device_node
                # device_node.device_name = data.target_device.name
                # device_node.device_id = data.target_device.device_id
                # device_node.device_guid = data.target_device.device_guid
                # device_node.device_type = data.target_device.device_type
                has_changes = True

        if has_changes:

            tmp_file = gremlin.util.getTemporaryFile(".xml") #os.path.join(os.getenv("temp"), gremlin.util.get_guid() + ".xml")
            if self._graph.to_xml(tmp_file):
                # load it
                config = gremlin.config.Configuration()
                verbose =config.verbose_mode_extra and config.verbose
                if verbose: gremlin.util.display_file(tmp_file)
                gremlin.shared_state.ui.registerTemporaryProfileLoadFile(tmp_file)
                el = gremlin.event_handler.EventListener()
                el.request_profile_reload.emit(tmp_file, True)

        gremlin.util.popCursor()
        return True



class ProfileDeviceNode(ProfileBaseNode):
    ''' device node '''
    def __init__(self, device = None, parent = None):
        super().__init__(ProfileNodeType.Device)
        self.modes = [] # list of defined modes for this node
        self.parent = parent
        self._device = device
        self._enabled = True # flag to enable/disable the mapping
        self.enable_changed_callback = None # callback when the enabled changed flag changes - callback gets the node as a parameter callback(node)
        self.label = None

    @property
    def enabled(self) -> bool:
        return self._enabled
    @enabled.setter
    def enabled(self, value: bool):
        if self._enabled != value:
            self._enabled = value
            if self.enable_changed_callback:
                self.enable_changed_callback(self)

    @property
    def device_name(self) -> str:
        if self._device:
            return self._device.name
        return None

    @device_name.setter
    def device_name(self, value : str):
        if self._device:
            self._device.name = value

    @property
    def device_id(self) -> str:
        if self._device:
            return self._device.device_id
        return None
    @device_id.setter
    def device_id(self, value : str):
        if self._device:
            self._device.device_id = value
            self._device.device_guid = gremlin.util.parse_guid(value)

    @property
    def device_guid(self) -> dinput.GUID:
        if self._device:
            return self._device.device_guid
        return None
    @device_guid.setter
    def device_guid(self, value : dinput.GUID):
        if self._device:
            self._device.device_guid = value
            self._device.device_id = str(value)

    @property
    def virtual(self) -> bool:
        return self._device.is_virtual
    @virtual.setter
    def virtual(self, value : bool):
        self._device.is_virtual = value

    @property
    def device_type(self) -> DeviceType:
        if self._device is not None:
            return self._device.device_type
        return None
    @device_type.setter
    def device_type(self, value : DeviceType):
        if self._device:
            if value is None:
                pass
            self._device.device_type = value

    @property
    def connected(self) -> bool:
        ''' true if the device is connected '''
        return self._device.connected



    def remap(self, device : DeviceSummary):
        ''' changes the device to another device '''
        self._device = device


    def isDevice(self, device : DeviceSummary) -> bool:
        ''' returns true if the device is the same '''
        return self.device_guid == device.device_guid





    def from_xml(self, node : Element, data = None, extra_data = None):
        """Populates this device based on the xml data.

        :param node the xml node to parse to populate this device
        """

        device_name = node.get('name')
        device_guid_str = node.get("device-guid")
        device_guid = parse_guid(device_guid_str)
        #device_id = str(self.device_guid)

        dt = safe_read(node, "type", str, "")
        if not dt:
            dt = DeviceType.NotSet
        device_type = DeviceType.to_enum(dt)
        self._device = self._get_device(device_name, device_guid, device_type)

        if "label" in node.attrib:
            self.label = safe_read(node, "label", str, "")
        else:
            self.label = None
        #self.connected = gremlin.joystick_handling.is_device_connected(self.device_guid)

        self.modes = []


        # load modes
        child : Element
        for child in node:
            mode_node = ProfileModeNode(self)
            mode_node.from_xml(child, data)
            mode_name = mode_node.name
            if not mode_name in self.modes:
                self.modes.append(mode_name)


    def to_xml(self) -> Element:
        """Returns a XML node representing this device's contents.

        :return xml node of this device's contents
        """
        device_type = self.device_type
        if device_type is None:
            device_type = DeviceType.Joystick
        node_tag = "device" if device_type != DeviceType.VJoy else "vjoy-device"
        node = etree.Element(node_tag)
        node.set("name", safe_format(self.device_name, str))
        if self.label:
            node.set("label", self.label)
        node.set("device-guid", write_guid(self.device_guid))
        device_type = DeviceType.to_string(device_type)

        node.set("type",device_type)

        for mode_node in self.children:
            node.append(mode_node.to_xml())
        return node

    def _get_device(self, device_name : str, device_guid : dinput.GUID, device_type : DeviceType = DeviceType.Joystick):
        ''' gets an existing device or creates a new device '''
        device = gremlin.joystick_handling.device_info_from_guid(device_guid) if device_guid else None
        if not device:
            # create a fake device
            device = DeviceSummary()
            device.device_guid = device_guid
            device.device_id = gremlin.util.normalize_guid(device_guid)
            device.name = device_name
            assert device_type is not None,"Invalid device type provided"
            device.device_type = device_type
            # default to max DInput as we don't know the capabilities
            device.axis_count = 8
            device.axis_names = gremlin.joystick_handling.AxisNames.joystick_linear_axis_names
            device.axismap_list = {}
            for i in range(device.axis_count):
                am = dinput.AxisMap()
                am.axis_index = i+1
                am.linear_index = i+1
                device.axismap_list[i] = am
            device.button_count = 128
            device.hat_count = 4
            device.input_enabled = True # enable as input
            device._connected = False
        if device.device_type is None:
            device.device_type = DeviceType.Joystick
        assert device.device_type is not None
        return device



    @property
    def device(self) -> DeviceSummary:
        return self._device

    @device.setter
    def device(self, value : DeviceSummary):
        assert value is not None and value.device_type is not None,"Invalid device"
        self._device = value

    def __str__(self):
        return f"{self.nodeType.name}: device: {self.device_name} id: {self.device_id} virtual: {self.virtual} remap enabled: {self.enabled}"




class ProfileModeNode(ProfileBaseNode):
    ''' mode node '''
    def __init__(self, mode_name = None, parent_mode_name = None, parent : ProfileDeviceNode = None):
        super().__init__(ProfileNodeType.Mode)
        self.name = mode_name # mode name
        self.inherit = parent_mode_name # parent mode name
        self.parent = parent

    def from_xml(self, node : Element, data = None, extra_data = None):
        """Parses the XML mode data.

        :param node XML node to parse
        """
        from gremlin.base_profile import InputItem
        name = safe_read(node, "name", str, "")
        name = name.strip()
        self.name = name
        self.inherit = safe_read(node, "inherit", str, "")

        if self.parent:
            child : Element
            for child in node:
                input_node = ProfileInputNode(device_node = self.parent, parent = self)
                input_node.from_xml(child, data)

    def to_xml(self) -> Element:
        """Generates XML code for this DeviceConfiguration.

        :return XML node representing this object's data
        """
        node = etree.Element("mode")
        node.set("name", safe_format(self.name, str))
        if self.inherit is not None:
            node.set("inherit", safe_format(self.inherit, str))

        input_node : ProfileInputNode
        for input_node in self.children:
            child_node = input_node.to_xml()
            node.append(child_node)

        return node

    def __str__(self):
        return f"{self.nodeType.name}: mode: {self.name}  parent: {self.inherit}"




class ProfileInputNode(ProfileBaseNode):
    ''' input node - represents an input for a device '''
    def __init__(self, device_node : ProfileDeviceNode, parent : ProfileModeNode):
        super().__init__(ProfileNodeType.Input)
        assert device_node is not None,"device node must be provided"
        self.device_node  = device_node # link to the device node this input belongs to

        self.input_type : InputType = InputType.NotSet # input type
        self.input_id = None # input id, numeric for a joystick or button, or an object for a keyboard, MIDI, OSC item
        self._calibration = None # calibration data if the input has calibration data
        self.curve_data = None # curve data if the input is curved
        self.always_execute = False
        self.parent = parent
        self.input_entry = None # the identifier
        self._input_item = None # the profile input item

        if device_node.device_type == DeviceType.ModeControl:
            # create the special input item

            profile = gremlin.shared_state.current_profile
            device_modes = profile.get_device_modes(
                gremlin.shared_state.mode_tab_guid,
                DeviceType.ModeControl,
                DeviceType.to_string(DeviceType.ModeControl)
            )

            current_mode = gremlin.shared_state.edit_mode
            mode_object = device_modes.ensure_mode_exists(current_mode)


            self._input_item = gremlin.input_item.InputItem(mode_object = mode_object)
            self._input_item.device_type = DeviceType.ModeControl
            self._input_item.setInputId(0)


    @property
    def input_item(self) -> gremlin.input_item.InputItem:
        if self._input_item is None:
            registry = gremlin.base_profile.ProfileRegistry()
            self._input_item = registry.getInputItem(self.device_guid, self.input_type, self.input_id)
        return self._input_item

    @input_item.setter
    def input_item(self, value: gremlin.input_item.InputItem):

        self._input_item = value

    @property
    def device_guid(self):
        ''' device guid '''
        if self.device_node:
            return self.device_node.device_guid
        return None

    @property
    def message_key(self):
        # joystick inputs only - returns id of axis or button
        return self._input_id

    def callbackKey(self):
        ''' callback key unique to the input type, input id '''
        return (self.device_guid, self.input_type, self.input_id)

    @property
    def hasCalibration(self):
        ''' for axis input devices, returns True if the device has an active calibration '''
        return self._calibration is not None and self._calibration.hasData

    @property
    def calibration(self):
        ''' for axis input devices, returns the calibration data '''
        return self._calibration


    def from_xml(self, node : Element, data = None, extra_data = None):
        ''' reads an input node '''
        import gremlin.ui.octavi_device
        self.input_type = InputType.to_enum(node.tag)
        self.description = html.unescape(safe_read(node, "description", str, ""))
        self.always_execute = read_bool(node, "always-execute", False)

        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        container_tag_map = container_plugins.tag_map

        mode_object = gremlin.base_profile.get_mode_object(node, extra_data)
        assert mode_object is not None,"Unable to derive mode object"


        input_entry = None
        if self.input_type in (InputType.KeyboardLatched, InputType.Keyboard):
            from gremlin.ui.keyboard_device import KeyboardInputItem
            from gremlin.keyboard import Key
            input_entry = KeyboardInputItem(mode_object)

            if "id" in node.attrib and node.tag == "key":
                # legacy format
                scan_code = safe_read(node, "id", int, 0)
                key = Key(scan_code=scan_code, is_extended=False, is_mouse = False)
                input_entry.key = key
            else:
                # see if old style keyboard entry
                if "extended" in node.attrib:
                    scan_code = self.input_id
                    is_extended = read_bool(node, "extended", False)
                    is_mouse = safe_read(node,"mouse", bool, False)
                    key = Key(scan_code=scan_code, is_extended=is_extended, is_mouse = is_mouse)
                    input_entry.key = key
                    for child in node:
                        if child.tag == "latched":
                            latched_key = Key(scan_code=safe_read(child,"id",int,0), is_extended= read_bool(child,"extended"))
                            if not latched_key in key.latched_keys:
                                key.latched_keys.append(latched_key)
                else:
                    # new style
                    for child in node:
                        if child.tag == "input":
                            input_entry.parse_xml(child, input_entry)
                            break
            self.input_type = InputType.KeyboardLatched # force new input type
            #syslog.info(f"Loaded key input: {input_item.display_name}")

            self.input_id = input_entry



        elif self.input_type == InputType.Midi:
            # midi data
            from gremlin.ui.midi_device import MidiInputItem
            midi_input_item = MidiInputItem(mode_object)
            for child in node:
                if child.tag == "input":
                    midi_input_item.parse_xml(child, midi_input_item)
            self.input_id = midi_input_item


        elif self.input_type == InputType.OpenSoundControl:
            # OSC data
            from gremlin.ui.osc_device import OscInputItem
            osc_input_item = OscInputItem(mode_object)
            for child in node:
                if child.tag == "input":
                    osc_input_item.parse_xml(child, osc_input_item)
            self.input_id = osc_input_item


        elif self.input_type == InputType.ModeControl:
            # mode control entries - input id is the only item we need
            self.is_axis = False
            self.input_id = safe_read(node,"id",int,0)




        elif self.input_type == InputType.JoystickAxis:
            # check for curve data
            for child in node:
                if gremlin.input_item._is_curve_tag(child.tag):
                    self.curve_data = gremlin.curve_handler.AxisCurveData()
                    self.curve_data._parse_xml(child)
                    self.curve_data.calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(self.device_guid, self.input_id)
                    break
            if "id" in node.attrib:
                str_id = node.get("id")
                if not str_id.isnumeric():
                    self.input_id = gremlin.base_classes.SpecialInputItem(str_id)
                else:
                    self.input_id = safe_read(node,"id",int,0)
            self.is_axis = True

        elif self.input_type in (InputType.JoystickButton, InputType.JoystickHat):
            if "id" in node.attrib:
                str_id = node.get("id")
                if not str_id.isnumeric():
                    self.input_id = gremlin.base_classes.SpecialInputItem(str_id)
                else:
                    self.input_id = safe_read(node,"id",int,0)
        elif self.input_type == InputType.ModeControl:
            # special mode
            if "id" in node.attrib:
                self.input_id = safe_read(node,"id",int,0)
        elif self.input_type == InputType.OctaviIfr1:
            if "id" in node.attrib:
                button = safe_read(node,"id", int, 0)
                button = gremlin.ui.octavi_device.OctaviButton(button)
                self.input_id = button

        registry = gremlin.base_profile.ProfileRegistry()
        if not self.input_item:
            input_item = registry.getInputItem(self.device_guid, self.input_type, self.input_id)
            self.input_item = input_item
        else:
            input_item = self.input_item



        # add container nodes to the input node
        child: Element
        for child in node:
            if child.tag in ("latched", "input", "keylatched") or gremlin.input_item._is_curve_tag(child.tag):
                # not a container
                continue
            if not "type" in child.attrib:
                syslog.error(f"XML {node.tag} is missing container 'type' attribute")
                continue
            container_type = child.get("type")
            if container_type not in container_tag_map:
                syslog.warning(f"Unknown container type used: {container_type}")
                continue

            container_node = ProfileContainerNode(parent = self)
            container_node.from_xml(child, input_item)




    def to_xml(self):
        """Generates a XML node representing this object's data.

        :return XML node representing this object
        """
        from gremlin.keyboard import Key
        node = etree.Element(InputType.to_string(self.input_type))

        if self.input_type in (InputType.Keyboard, InputType.KeyboardLatched):
            if isinstance(self.input_id, Key):
                # keyboard key item
                key : Key
                key = self.input_id
                node.set("id", safe_format(key.scan_code, int))
                node.set("extended", safe_format(key.is_extended, bool))
                for latched_key in key.latched_keys:
                    # latched keys
                    child = etree.Element("latched")
                    child.set("id", safe_format(latched_key.scan_code, int))
                    child.set("extended", safe_format(latched_key.is_extended, bool))
                    node.append(child)
            elif hasattr(self.input_id,"to_xml"):
                child = self.input_id.to_xml()
                node.append(child)
            else:
                node.set("id", safe_format(self.input_id[0], int))
                node.set("extended", safe_format(self.input_id[1], bool))
        elif self.input_type in (InputType.Midi, InputType.OpenSoundControl):
            # write midi or OSC nodes
            child = self.input_id.to_xml()
            node.append(child)
        else:
            node.set("id", safe_format(self.input_id, int))

        if self.curve_data is not None:
            curve_node = self.curve_data._generate_xml()
            node.append(curve_node)


        if self.always_execute:
            node.set("always-execute", "True")

        if self.description:
            node.set("description", html.escape(safe_format(self._description, str)))
        else:
            node.set("description", "")

        # process child nodes
        for child in self.children:
            child_node = child.to_xml()
            node.append(child_node)
        return node

    def __str__(self):
        container_nodes = [node for node in self.children if node.nodeType == ProfileNodeType.Container]
        container_stub = f"{len(container_nodes)}"
        return f"{self.nodeType.name}: input type: {self.input_type.name} input id: {self.input_id} containers: {container_stub} "

class ProfileContainerNode(ProfileBaseNode):
    ''' input node - represents a container for an input '''
    def __init__(self, parent = None):
        super().__init__(ProfileNodeType.Container)
        self.container = None
        self.parent = parent



    def from_xml(self, node : Element, data = None, extra_data = None):
        ''' reads container data from the profile xml'''
        container_type = node.get("type")


        input_node : ProfileInputNode = self.parent

        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        container_tag_map = container_plugins.tag_map
        entry = container_tag_map[container_type](self)
        entry.from_xml(node, data)

        if hasattr(entry, "action_model"):
            entry.action_model = input_node.input_item.containers
        container_plugins.set_container_data(self, entry)
        self.container = entry

    def to_xml(self) -> Element:
        if self.container:
            return self.container.to_xml()

    def __str__(self):
        return f"{self.nodeType.name}: {str(self.container)}"



class ProfileMergedAxisNode(ProfileBaseNode):
    ''' device node '''
    def __init__(self, parent = None):
        super().__init__(ProfileNodeType.MergedAxis)
        self.entry = None
        self.parent = parent

    def from_xml(self, node, data = None, extra_data = None):
        entry = {
            "mode": node.get("mode", None),
            "operation": gremlin.types.MergeAxisOperation.to_enum(safe_read(node, "operation", str, "average"))
        }
        tag = "vjoy"
        n = node.find(tag)
        if n is not None and "vjoy_id" in n.attrib and "axis_id" in n.attrib:
            entry[tag] = {
                "vjoy_id": safe_read(n, "vjoy-id", int, 1),
                "axis_id": safe_read(n, "axis-id", int, 1),
            }
        for tag in ["lower", "upper"]:
            n = node.find(tag)
            if n is not None and "device_guid" in n.attrib and "axis_id" in n.attrib:
                entry[tag] = {
                    "device_guid": parse_guid(safe_read(n, "device-guid", str, "")),
                    "axis_id": safe_read(n, "axis-id", int, 1)
                }

        self.entry = entry

    def to_xml(self):
        entry= self.entry
        node = etree.Element("merge-axis")
        if entry:
            node.set("mode", safe_format(entry["mode"], str))
            node.set("operation", safe_format(
                gremlin.types.MergeAxisOperation.to_string(entry["operation"]),str))
            for tag in ["vjoy"]:
                sub_node = etree.Element(tag)
                sub_node.set("vjoy-id",safe_format(entry[tag]["vjoy_id"], int))
                sub_node.set("axis-id", safe_format(entry[tag]["axis_id"], int))
                node.append(sub_node)
            for tag in ["lower", "upper"]:
                sub_node = etree.Element(tag)
                sub_node.set("device-guid", write_guid(entry[tag]["device_guid"]))
                sub_node.set("axis-id", safe_format(entry[tag]["axis_id"], int))
                node.append(sub_node)

        return node

    def __str__(self):
        return f"{self.nodeType.name}"





class ProfileGraph():
    ''' holds the profile graph '''

    def __init__(self):
        self._root = ProfileRootNode()
        self._source_xml = None # source XML loaded
        self._remap_prompt_issued = False



    def getModeList(self) -> list[str]:
        ''' gets the list of defined modes in the profile '''
        return list(self._root._graph_modes.keys())

    def getModeNode(self, mode_name) -> ProfileModeNode:
        ''' gets the profile graph mode for the specific mode ='''
        if mode_name in self._root._graph_modes:
            return self._root._graph_modes[mode_name]
        return None # not found

    def get_device_node(self, device_guid) -> ProfileDeviceNode:
        ''' gets the profile device node for the given device_guid, None if not found '''
        device_id = gremlin.util.normalize_guid(device_guid) if not isinstance(device_guid, str) else device_guid
        return next((node for node in self._root.children if node.nodeType == ProfileNodeType.Device and node.device_id == device_id),None)



    def _dump(self):
        ''' dumps the graph '''
        syslog.info(f"Profile Graph Tree:")
        root = self._root
        if root:
            for pre, fill, node in anytree.RenderTree(root, style=anytree.AsciiStyle()):
                syslog.info(f"{pre}{str(node)}")

    def from_xml(self, source_xml : str, data = None, fname_is_xml : bool = False):
        ''' reads a profile from XML '''
        parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
        if fname_is_xml:
            root = etree.fromstring(source_xml, parser)
        else:
            tree = etree.parse(source_xml, parser)
            root = tree.getroot()

        #self._root = ProfileRootNode(source_xml) # root node
        self._root.from_xml(root, data)

        self._source_xml = source_xml
        verbose = gremlin.config.Configuration().verbose_mode_device

        # add detected devices
        device : dinput.DeviceSummary
        active_devices = gremlin.joystick_handling.all_joystick_devices()

        for device in active_devices:
            if not self.get_device_node(device.device_guid):
                device_node = ProfileDeviceNode(device = device, parent = self._root)


        if verbose: self._dump()

        # # prompt for mapping if a device is not found

        config = gremlin.config.Configuration()


    def to_xml(self, target_xml : str) -> bool:
        ''' writes the profile graph to XML'''
        root = self._root.to_xml()
        # strip singleton devices that have no nodes
        device_nodes = root.xpath("//device")
        remove_nodes = []
        for node in device_nodes:
            children = node.getchildren()
            if not len(children):
                remove_nodes.append(node)

        for node in remove_nodes:
            node.getparent().remove(node)


        try:
            # save the file
            tree = etree.ElementTree(root)
            tree.write(target_xml, pretty_print=True,xml_declaration=True,encoding="utf-8")
            return True
        except Exception as err:
            syslog.error(f"ProfileGraph: unable to create XML: {target_xml}: {err}")
        return False

    def has_unknowns(self) -> bool:
        ''' true if the loaded profile has one or more joystick devices that aren't currently connected '''

        # get devices
        device_nodes = [node for node in self._root.children if node.nodeType == ProfileNodeType.Device]
        device_guids = [node.device_guid for node in device_nodes if node.device_type == DeviceType.Joystick]
        for device_guid in device_guids:
            info = gremlin.joystick_handling.device_info_from_guid(device_guid)
            if not info:
                return True
        return False

    def joystick_devices(self) -> list[DeviceSummary]:
        ''' gets a list of joystick devices defined in the profile '''
        device_nodes = [node for node in self._root.children if node.nodeType == ProfileNodeType.Device]
        device_list = [node.device for node in device_nodes if node.device_type in (DeviceType.Joystick, DeviceType.VJoy) and not node.device.disabled]
        return device_list






    def remap(self):
        ''' show the remap dialog '''
        dialog = DeviceRemapDialogUI(self)
        gremlin.util.centerDialog(dialog)
        dialog.exec()

    @property
    def root(self):
        ''' root node '''
        return self._root
