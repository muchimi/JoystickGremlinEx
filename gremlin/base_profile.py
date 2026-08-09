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

from __future__ import annotations  # deprecated with python 3.14+
import re
import sys
import collections
import os
import shutil
import copy
import logging
import traceback
import json
import time



from typing import Callable

import container_plugins
import gremlin.keyboard
import gremlin.profile
import gremlin.shared_state
from gremlin.types import KeyboardOutputMode, MergeAxisOperation, PlaybackMode, PluginVariableType, DeviceCategory, DeviceType, MouseButton
from uuid import UUID
from PySide6 import QtCore
from frozendict import frozendict
from gremlin.input_item import ActionSet, ActionSets


import gremlin.ui.mode_device
import gremlin.util
from gremlin.util import compare_path, read_bool, safe_format, safe_read, write_guid, parse_guid, read_guid, TriggerDict, get_guid, normalize_guid

from gremlin.input_types import InputType
import gremlin.types
from lxml import etree


import gremlin.input_item
import gremlin.joystick_handling
import gremlin.profile
import gremlin.plugin_manager
import gremlin.shared_state
from gremlin.singleton_decorator import SingletonDecorator
import gremlin.util
import gremlin.ui.ui_common
from gremlin.ui.ui_common import Ansi
import anytree
from anytree import Node
from PySide6.QtWidgets import QMessageBox
import gremlin.profile_graph
import gremlin.execution_graph
import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
from gremlin.input_item import InputItem, AbstractAction
import dinput
from psygnal import Signal
import html


syslog = logging.getLogger("system")


@SingletonDecorator
class ProfileImportData:
    def __init__(self):
        self.used_ids = {}  # used at load time to validate there are no duplicate container/action IDs in the profile


_import_data = ProfileImportData()

# Data struct representing profile information of a device
ProfileDeviceInformation = collections.namedtuple(
    "ProfileDeviceInformation",
    ["device_guid", "name", "containers", "conditions", "merge_axis"],
)


class ProfileDeviceNode:
    """device information"""

    def __init__(self, profile: Profile):  # noqa: F821
        """Creates a new instance.

        :param parent the parent profile of this device
        """
        self.id = gremlin.util.get_guid()  # unique ID of this node
        self.parent = profile  # profile
        self.label = ""
        self._device: dinput.DeviceSummary = None
        self._modes = TriggerDict()  # map of ProfileMode objects keyed by mode name (case sensitive)
        # self._modes.addCallback(self._handle_mode_node_changed)
        self._name: str = None
        self._device_guid: dinput.GUID = None
        self.masterMode = {}  # master mode

    def _handle_mode_node_changed(self, data_map, key, old_value: ProfileModeNode, new_value: ProfileModeNode):
        if self.device_type == DeviceType.ModeControl:
            syslog.info(f"mode change: key: [{key}] old_value: [{str(old_value)}] new value: [{str(new_value)}]")
            pass

    @property
    def profile(self) -> Profile:
        return self.parent

    @property
    def modes(self) -> dict[ProfileModeNode]:
        return self._modes

    def modeExists(self, mode: str) -> bool:
        """true if the mode node exists in the device modes"""
        return mode in self._modes

    @property
    def device(self) -> dinput.DeviceSummary:
        """returns the device summary object"""
        return self._device

    @device.setter
    def device(self, value: dinput.DeviceSummary):
        self._device = value

    @property
    def device_guid(self) -> dinput.GUID:
        """device I/D as a GUID"""
        if self._device:
            return self._device.device_guid
        return None

    @property
    def name(self) -> str:
        if self._name:
            return self._name
        if self._device:
            return self._device.name
        return None

    @name.setter
    def name(self, value: str):
        self._name = value

    @property
    def virtual(self) -> bool:
        if self._device:
            return self._device.is_virtual
        return False

    @property
    def device_type(self) -> DeviceType:
        if self._device:
            return self._device.device_type
        return DeviceType.NotSet

    @device_type.setter
    def device_type(self, value: DeviceType):
        assert False, "attribute is readonly - set device_guid instead"


    @property
    def type(self) -> DeviceType:
        """device type"""
        return self.device_type

    @device_guid.setter
    def device_guid(self, value: dinput.GUID):
        if not isinstance(value, dinput.GUID):
            value = dinput.GUID(value)
        assert isinstance(value, dinput.GUID) if value is not None else True
        self._device_guid = value
        device = gremlin.joystick_handling.getDevice(value)
        self._device = device


    @property
    def device_id(self) -> str:
        """device ID a a string"""
        if self._device:
            return self._device.device_id
        return str(self.device_guid)

    def getModeNode(self, mode: str, system: bool = None, autocreate=False):
        """gets the mode object for the given mode
        :param mode: the mode name (case sensitive)
        :param autocreate: flag to autocreate the node if it does not exist

        """
        if mode in self.modes:
            mode_node = self.modes[mode]
            # syslog.info(f"DeviceNode: found mode [{mode}] mode node id: [{mode_node.id}] device id: [{self.id}] profile id: [{self.profile.id}]")
            return mode_node
        if autocreate:
            mode_node = ProfileModeNode(name=mode, parent=self, system=system)
            self.modes[mode] = mode_node
            # syslog.info(
            #     f"ModeNode: CREATE mode [{mode}] mode node id: [{mode_node.id}] device id: [{self.id}] profile id: [{self.profile.id}] device: [{str(self)}]"
            # )
            return mode_node
        return None

    def hasInputItems(self, has_mappings=False) -> bool:
        """true if the device has defined inputs
        :param has_mappings: optional, if true checks for the inputs to have mappings defined instead of just input definitions
        """
        for mode_node in self.modes.values():
            if mode_node.hasInputItems(has_mappings):
                return True
        return False

    def ensure_mode_exists(self, mode_name: str, is_system=False) -> ProfileModeNode:  # noqa: F821
        """Ensures that a specified mode exists, creating it if needed.

        :param mode_name the name of the mode being checked
        :param device a device to initialize for this mode if specified
        :param is_system: true if the mode is a special system mode (not user defined)
        :returns: Mode object
        """
        assert mode_name is not None, "mode must be provided"
        mode_node = self.getModeNode(mode_name, autocreate=True)
        assert mode_node is not None, "unable to retrieve mode node"
        mode_node.system = is_system
        return mode_node

    def connected(self) -> bool:
        if self._device:
            return self._device.connected
        return False

    def from_xml(self, node, data=None, extra_data=None):
        """Populates this device based on the xml data.

        :param node the xml node to parse to populate this device
        """
        assert node.tag in ("device", "vjoy-device"), f"XML: ProfileDeviceNode: Expected 'device' or 'vjoy-device' tag, got '{node.tag}'  offending line: {node.sourceline}"
        self.name = node.get("name")

        if "guid" in node.attrib:
            self.id = normalize_guid(node.get("guid"))  # device node ID

        if "device-guid" in node.attrib:
            device_id = normalize_guid(node.get("device-guid"))
            device_guid = gremlin.util.to_guid(device_id)
            device = gremlin.joystick_handling.getDevice(device_guid)
            if device:
                self._device = device
            else:
                # device not found (could bedisconnected)
                syslog.info(f"DEVICE: Device with GUID [{device_guid}] not found for profile [{self.name}]")
                device = dinput.DeviceSummary()
                device.device_guid = device_guid
                device.device_id = device_id
                # for disconnectd devices, assume maximum axis and buttons to avoid problems
                device.axis_count = 8
                device.device_category = DeviceCategory.Physical # assume physical device if in a profile not under virtual sticks
                device_type_str = safe_read(node, "type", str, "")
                device_type = DeviceType.to_enum(device_type_str)
                device.setVirtual(device_type in (DeviceType.VJoy, DeviceType.Maestro))
                if device_type == DeviceType.VJoy:
                    vjoy_id = int(safe_read(node, "vjoy-id", int, -1))
                    if vjoy_id == -1:
                        # see if the vjoy # can be derived from the name
                        match = re.search(r'(\d+)\D*$', self.name)
                        if match:
                            vjoy_id = int(match.group(1))

                    device.vjoy_id = vjoy_id
                    device.virtual_id = device.vjoy_id


                # assume linear axis mapping for disconnected devices
                for axis_id in range(1, device.axis_count+1):
                    device.linear_id_map[axis_id] = axis_id
                    device.axis_id_map[axis_id] = axis_id
                    am = dinput.AxisMap()
                    am.linear_index = axis_id
                    am.axis_index = axis_id
                    device.axismap_list.append(am)
                    device.axis_names.append(am.getName())




                device.button_count = 128
                device.hat_count = 4
                device.name = safe_read(node, "name", str, "unknown")
                device.setConnected(False)
                gremlin.joystick_handling.registerDisconnectedDevice(device)
                if "type" in node.attrib:
                    dt = safe_read(node, "type", str, "")
                    device.device_type = DeviceType.to_enum(dt)
                else:
                    device.device_type = DeviceType.NotSet
                self._device = device

        self.label = safe_read(node, "label", str, self.name)
        nodes = node.xpath(".//mode")
        for child in nodes:
            assert child.tag == "mode", f"not a valid mode entry - offending line: {node.sourceline}"
            mode_name = html.unescape(safe_read(child, "name", str, "")).strip()
            assert mode_name != "", f"invalid mode name - offending line: {child.sourceline}"
            if mode_name == gremlin.shared_state.master_mode or self.device_type == DeviceType.ModeControl:
                # special handling of master mode
                # assert self.modeExists(mode_name), "master mode should already exist"
                mode_node = self.getModeNode(mode_name, autocreate=True)
                # assert len(mode_node._config) > 0, "master mode should have default entries already set"
            else:
                mode_node = self.getModeNode(mode_name, autocreate=True)
            assert mode_node is not None  # shuld always exist in the profile as it's created on start
            mode_node.from_xml(child, data, extra_data)
            # syslog.info(f"device xml: storing mode id [{mode_node.id}] to device id [{self.id}] mode name: [{mode_node.name}]")
            # pass

    def to_xml(self):
        """Returns a XML node representing this device's contents.

        :return xml node of this device's contents
        """

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)

        # skip writing if the device has no inputs defined
        persistable = DeviceType.isPersistable(self.device_type)
        hasinputs = self.hasInputItems()
        if verbose:
            syslog.info(
                f"device xml: generating XML for device id [{self.id}] name [{self.name}] persistable: [{persistable}] has inputs: [{hasinputs}] skipping: [{not (hasinputs and persistable)}]"
            )

        if persistable and hasinputs:
            node_tag = "device" if self.type != DeviceType.VJoy else "vjoy-device"
            node = etree.Element(node_tag)
            node.set("name", safe_format(self.name, str))
            node.set("label", safe_format(self.label, str))
            node.set("device-guid", write_guid(self.device_guid))  # device GUID
            node.set("guid", write_guid(self.id))  # node ID

            node.set("type", DeviceType.to_string(self.device_type))

            mode_list = sorted(self.modes.values(), key=lambda x: x.name)
            for mode in mode_list:
                mode_node = mode.to_xml()
                if mode_node is not None:
                    node.append(mode_node)

            return node

        return None

    def __str__(self):
        return f"Profile Device: [{self.device_id}] name: [{self.name}] type: [{self.device_type.name}] virtual: [{self.virtual}]"


class AbstractFunctor(QtCore.QObject):
    """Abstract base class defining the interface for functor like classes.

    These classes are used in the internal code execution system.
    """

    functor_complete = Signal()  # fires when a functor has completed its execution completely

    def __init__(self, action_data, parent=None):
        """Creates a new instance, extracting needed information.

        :param instance the object which contains the information needed to
            execute it later on
        """
        import gremlin.event_handler

        super().__init__()

        self._name = action_data.name
        self.enabled = True
        self.node = parent
        self.action_data = action_data
        self._id = action_data.id
        self.manual_callback = False  # functor uses automatic mode
        self._hooked = False
        el = gremlin.event_handler.EventListener()
        el.profile_hook.connect(self.hook)
        el.profile_unhook.connect(self.unhook)

    def hook(self):
        """called by the execution context before profile_start, profile_started gets called"""
        if not self._hooked:
            self._hooked = True
            el = gremlin.event_handler.EventListener()
            el.profile_start.connect(self.profile_start)
            el.profile_stop.connect(self.profile_stop)
            el.profile_stopping.connect(self.profile_stopping)
            el.profile_started.connect(self.profile_started)
            el.profile_after_start.connect(self.profile_after_start)
            el.abort.connect(self.profile_stop)  # abort also stops the profile
            el.runtime_mode_changed.connect(self.profile_mode_changed)

    def unhook(self):
        if self._hooked:
            el = gremlin.event_handler.EventListener()
            el.profile_start.disconnect(self.profile_start)
            el.profile_stop.disconnect(self.profile_stop)
            el.profile_stopping.disconnect(self.profile_stopping)
            el.profile_started.disconnect(self.profile_started)
            el.runtime_mode_changed.disconnect(self.profile_mode_changed)
            el.profile_after_start.disconnect(self.profile_after_start)
            el.abort.disconnect(self.profile_stop)  # abort also stops the profile
            self._hooked = False

    @property
    def id(self) -> str:
        return self._id

    def setId(self, value: str):
        """sets the ID"""
        self._id = value

    def process_event(self, event, value, extra_data=None) -> bool:
        """Processes the functor using the provided event and value data.

        :param event the raw event that caused the functor to be executed
        :param value the possibly modified value

        returns: True to continute the execution sequence, False to abort it

        """
        return True

    def profile_start(self):
        """called when the profile starts"""
        pass

    def profile_started(self):
        """called when the profile started (all other items completed)"""
        pass

    def profile_after_start(self):
        """called when the profile started (all other items completed)"""
        pass

    def profile_stop(self):
        """called when the profile stops"""
        pass

    def profile_stopping(self):
        """called before a profile stops"""
        pass

    def profile_mode_changed(self, mode: str) -> None:
        """called when the runtime mode changes"""
        pass

    @property
    def profile_mode(self) -> str:
        """gets the mode of this action"""
        return self.action_data.get_mode()

    @property
    def hardware_device_guid(self) -> dinput.GUID:
        """gets the currently attached hardware GUID"""
        return self.action_data.hardware_device_guid

    @property
    def hardware_device_id(self) -> str:
        """gets the currently attached hardware GUID"""
        return self.action_data.hardware_device_id

    @property
    def hardware_input_id(self):
        return self.action_data.hardware_input_id

    @property
    def hardware_input_type(self) -> InputType:
        return self.action_data.hardware_input_type

    def latch_extra_inputs(self, container_condition_functors=None, action_condition_functors=None):
        """returns any extra inputs as a list of (device_guid, input_id) to latch to this action (trigger on change)"""
        return []

    def getContainerNode(self):
        """gets the container node the action belongs to"""
        import gremlin.execution_graph

        if self.node:
            for node in self.node.ancestors:
                if node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.Container:
                    return node
        return None

    def getSiblings(self) -> list:
        """gets action node siblings"""
        import gremlin.execution_graph

        container_node = self.getContainerNode()
        nodes = []
        if container_node:
            # grab all the curve nodes attached to that container
            for node in container_node.descendants:
                if node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.Action:
                    nodes.append(node)
        return nodes

    def _check_for_auto_release(self, action):
        """auto release check for functors"""
        activation_condition = None
        if action.container.activation_condition:
            activation_condition = action.container.activation_condition
        elif action.activation_condition:
            activation_condition = action.activation_condition

        # If an input action activation condition is present the auto release
        # may have to be disabled
        needs_auto_release = True
        if activation_condition:
            for condition in activation_condition.conditions:
                if isinstance(condition, gremlin.input_item.BaseInputActionCondition):
                    # Remap like actions typically have an always activation
                    # condition associated with them
                    if condition.comparison != "always":
                        needs_auto_release = False

        return needs_auto_release

    def __str__(self):
        if self.action_data:
            return str(self.action_data)
        return "Plugin Functor"


class AbstractTriggerFunctor(AbstractFunctor):
    """functors that derive from this have the execution graph stop at that functor without processing downstream nodes further"""

    pass


class AbstractSelfTriggerFunctor(AbstractTriggerFunctor):
    """functor that has self trigger mechanisms to trigger its content"""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent)
        self._valid = False  # assume invalid

    @property
    def valid(self):
        """true if the action set nodes are loaded"""
        return self._valid

    def profile_started(self):
        super().profile_started()
        self._ec = gremlin.execution_graph.ExecutionContext()
        self.container_node = self._ec.find(self.action_data, gremlin.execution_graph.ExecutionGraphNodeType.Container)

        if not self.container_node:
            syslog.error(f"Unable to find this action in the execution tree: {str(self.action_data)}")
            self._valid = False
            return

        if self.container_node.nodeType != gremlin.execution_graph.ExecutionGraphNodeType.Container:
            syslog.error(f"Invalid container node type: [{self.container_node.nodeType.name}] found.  Expected [Container]")
            self._valid = False
            return

        if not self.container_node.children:
            syslog.error("Unable to find container group node for action in execution context.")
            self.action_set_nodes = []
            self._valid = False
            return

        group_node = self.container_node.children[0]  # group node is the only child of the container node
        self.action_set_nodes = [
            node
            for node in group_node.children
            if node.nodeType == gremlin.execution_graph.ExecutionGraphNodeType.ActionSet and node.action_set and node.has_actions
        ]

        self._valid = True

    def _trigger(self, index: int, event, value, extra_data: dict = None) -> bool:
        """executes an action set node

        :param index: the index of the action set, use None to execute all action sets, 0 based so index = 0 is the first action set of the container
        :param event: the event
        :param value: the action value
        :param extra_data : extra data dictionary, optional
        """
        if self.valid:
            return self._ec.execute_node(self.action_set_nodes[index], event, value, extra_data)
        return False

    def _execute(self, event, value, extra_data, verbose=None) -> bool:
        """executes all action set nodes

        :param event: the event
        :param value: the action value
        :param extra_data : extra data dictionary, optional
        """
        if verbose is None:
            verbose = gremlin.config.Configuration().verbose_mode_exec

        if self.valid:
            result = True  # assume ok
            for node in self.action_set_nodes:
                if verbose:
                    syslog.info(f"Trigger Functor: execute node ID: [{node.id}]")
                result = result and self._ec.execute_node(node, event, value, extra_data)
            return result
        return False


class AbstractContainerActionFunctor(AbstractFunctor):
    """used by action functors for actions that have containers"""

    def process_event(self, event, value, extra_data=None):
        """Processes the functor using the provided event"""
        result = True
        for functor in self.action_data.functors:
            # only fire the appropriate type
            if functor.enabled:
                # only fire if the functor is enabled (functor is enabled when the plugin is found in the execution structure when a profile starts)
                result = functor.process_event(event, value)
                if not result:
                    break

        return result


class AbstractContainerAction(AbstractAction):
    """abstract action that includes a subcontainers for sub-actions"""

    def __init__(self, parent=None):

        super().__init__(parent)
        self._abstract_container_action_generating_xml = False
        self._item_data_map = {}
        self._functors = []

    @property
    def item_data(self):
        """gets the default (first) data container block"""
        return self.get_item_data(0)

    def get_item_data(self, index, autocreate=True):
        """gets the specified data container block

        :param: autocreate - if set, creates a datablock if it does not exist

        """

        if autocreate and index not in self._item_data_map:
            # get the input item behind the parent action
            current = self.parent
            while current and not isinstance(current, InputItem):
                current = current.parent

            # setup a new input item for these containers and read from config the defined containers

            registry = gremlin.shared_state.current_profile.registry

            device_guid = current._device_guid
            input_type = current._input_type
            input_id = current._input_id
            mode_name = current.profile_mode

            input_item = registry.getInputItem(device_guid, mode_name, input_type, input_id)
            self._item_data_map[index] = input_item

        if index in self._item_data_map:
            return self._item_data_map[index]
        return None

    def from_xml(self, node, data=None, extra_data=None):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """

        super().from_xml(node, data, extra_data)
        container_nodes = gremlin.util.get_xml_child(node, "action_containers", multiple=True)

        # if hasattr(self,"command") and self.command == 'THROTTLE1_AXIS_SET_EX1':
        #     pass

        # get the input item behind the parent action
        current = self.parent
        while current:
            if isinstance(current, InputItem):
                # legacy instance
                break
            if isinstance(current, gremlin.profile_graph.ProfileInputItemNode):
                # graph instance
                current = current.input_item
                break
            current = current.parent

        assert current is not None, "Profile nesting error: unable to find InputItem"

        mode_object = get_mode_object(node, extra_data)
        assert mode_object is not None, "Unable to derive mode object"

        for child in container_nodes:
            # setup a new input item for these containers and read from config the defined containers

            device_guid = current._device_guid
            device_type = current._device_type
            input_id = current._input_id
            input_type = current._input_type

            input_item = InputItem(mode_object)
            input_item.setInputId(input_id)
            input_item.setInputType(input_type)
            input_item.device_guid = device_guid
            input_item.setDeviceType(device_type)
            input_item.is_action = True  # indicate this input item is a special action input item

            if child is not None:
                # has a node and the node contains data
                child.tag = child.get("type")
                index = safe_read(child, "index", int, 0)
                input_item.from_xml(child, data, extra_data)
                self._item_data_map[index] = input_item

    def to_xml(self):
        """writes node out to XML"""

        if self._abstract_container_action_generating_xml:
            syslog.error("CONTAINER ACTION XML: Recursion detected")
            return None
        try:
            self._abstract_container_action_generating_xml = True
            node = super().to_xml()

            for index, item_data in self._item_data_map.items():
                child = item_data.to_xml()
                child.set("type", child.tag)
                child.tag = "action_containers"
                child.set("index", str(index))
                node.append(child)
            return node
        finally:
            self._abstract_container_action_generating_xml = False

    # copy/paste exclusions
    def __getstate__(self):
        state = self.__dict__.copy()
        del state["item_data"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        input_item = InputItem(mode_node=self)
        self.item_data = input_item
        registry = gremlin.shared_state.current_profile.registry
        registry.registerInputItem(input_item)

    @property
    def functors(self):
        """gets the execution graphs for each sub container"""
        return self._functors

    def add_container(self, container_name):
        """adds a new container to the action"""
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        container = plugin_manager.get_class(container_name)(self.item_data)
        if hasattr(container, "action_model"):
            container.action_model = self.action_model
        self.action_model.add_container(container)
        plugin_manager.set_container_data(self.item_data, container)
        self._subcontainers.append(container)
        return container

    def _build_graph(self, parent_node=None):
        """builds the execution graph for the sub containers"""
        for container in self._subcontainers:
            eg = gremlin.execution_graph.ContainerExecutionGraph(container, parent_node)
            self._functors.extend(eg.functors)


class JoystickInputStats:
    """holds filtered information for device inputs"""

    def __init__(self, device_guid: UUID | dinput.GUID | str | int, input_filter: dict):
        assert isinstance(input_filter, dict), "invalid input filter"
        device = gremlin.joystick_handling.getDevice(device_guid)
        device_guid = device.device_guid if device else gremlin.util.to_guid(device_guid)
        self.input_filter = input_filter
        self.device_guid = device_guid
        self.device_counts = {}  # device count [input_type] -> int
        self.filtered_counts = {}  # filtered input count [input_type] -> int
        self.mapped_counts = {}  # mapped input count [input_type] -> int
        self.input_types = [
            InputType.JoystickAxis,
            InputType.JoystickButton,
            InputType.JoystickHat,
        ]
        self.mapped_mode = None  # mode used to filter the mappings, if None, uses all profile modes

        for input_type in self.input_types:
            self.device_counts[input_type] = 0
            self.mapped_counts[input_type] = 0
            self.filtered_counts[input_type] = 0

        if device:
            self.device_counts[InputType.JoystickAxis] = device.axis_count
            self.device_counts[InputType.JoystickButton] = device.button_count
            self.device_counts[InputType.JoystickHat] = device.hat_count
            self.updateFilters(input_filter)
            self.updateMappings()

    def setInputfilter(self, input_filter: dict):
        """sets the input filter"""
        self._input_filter = input_filter

    def setDefaultInputFilter(self, input_filter: dict):
        self._default_input_visible_map = input_filter

    def getInputFilter(self) -> dict:
        return self._input_filter

    @property
    def isFiltered(self) -> bool:
        """true if the device is filtered"""
        return sum(self.filtered_counts[input_type] for input_type in self.input_types) > 0

    @property
    def isMapped(self) -> bool:
        """true if the device is mapped"""
        return sum(self.mapped_counts[input_type] for input_type in self.input_types) > 0

    def getVisibleCount(self, input_type: InputType) -> int:
        """gets the count of visible (unfiltered) inputs in for the device based on current filter options"""
        if input_type in self.input_types:
            return self.filtered_counts[input_type]
        return 0

    @property
    def visible_axis_count(self) -> int:
        return self.getVisibleCount(InputType.JoystickAxis)

    @property
    def visible_button_count(self) -> int:
        return self.getVisibleCount(InputType.JoystickButton)

    @property
    def visible_hat_count(self) -> int:
        return self.getVisibleCount(InputType.JoystickHat)

    def updateMappings(self, mode: str = None, resync=False):
        """updates the mapping stats for the device
        :param mode: name of the mode to filter by, if None, looks at all profile modes

        """
        profile = gremlin.shared_state.current_profile

        registry = profile.registry
        if resync:
            registry.sync(profile)

        # device = gremlin.joystick_handling.getDevice(self.device_guid)
        devices = profile.devices
        device_guid = self.device_guid
        for input_type in self.input_types:
            self.mapped_counts[input_type] = 0
        self.mapped_mode = mode
        if device_guid in devices:
            device = profile.devices[device_guid]
            for mode_object in device.modes.values():
                if mode and mode_object.name != mode:
                    # mode filter
                    continue
                for input_type in mode_object.config:
                    if input_type in self.input_types:
                        self.mapped_counts[input_type] = sum(
                            [1 for input_item in mode_object.config[input_type] if isinstance(input_item, InputItem) and input_item.containers]
                        )

    def updateFilters(self, input_filter: dict):
        """updates the filter counts for the device"""
        verbose = gremlin.config.Configuration().verbose_mode_filter
        device_guid = gremlin.util.normalize_guid(self.device_guid)
        for input_type in self.input_types:
            self.filtered_counts[input_type] = 0



        if device_guid in input_filter:
            device = gremlin.joystick_handling.getDevice(device_guid)
            for input_type in input_filter[device_guid]:
                match input_type:
                    case InputType.JoystickAxis:
                        max_count = device.axis_count
                    case InputType.JoystickButton:
                        max_count = device.button_count
                    case InputType.JoystickHat:
                        max_count = device.hat_count
                    case _:
                        raise ValueError(f"don't know how to handle [{input_type}]")

                count = min(max_count, sum([1 for input_id in input_filter[device_guid][input_type] if input_filter[device_guid][input_type][input_id]]))

                self.filtered_counts[input_type] = count
                if verbose:
                    syslog.info(f"included: {input_type.name} count: {count}")

    def mapping_display(self):
        stub = "Mapped: "
        for input_type in self.input_types:
            count = self.device_counts[input_type]
            if count:
                stub += f"{InputType.to_name(input_type)} {count} "

        return stub

    def filtered_display(self):
        stub = "included: "
        for input_type in self.input_types:
            count = self.filtered_counts[input_type]
            if count:
                stub += f"{InputType.to_name(input_type)} {count} "

        return stub


class Settings:
    """holds profile settings including joystick filters"""

    filter_version = 1

    def __init__(self, profile) -> None:
        """Creates a new instance.

        :param parent the parent profile
        """
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose:
            syslog.info("profile settings init...")
        self.profile: Profile = profile
        self.vjoy_as_input = {}  # key by index : int, boolean, true if the vjoy device can be used as input to GEX
        self.maestro_as_input = {}  # key by index : int, boolean, true if the maestro device can be used as input to GEX
        self.vjoy_initial_values = {}
        self.startup_mode = None
        self.default_delay = 0.05
        self.input_visible_map = {}  # map of input filters for each device, [device_guid][input_type][input_id] = bool (true if visible, false if not) - no data = not visible
        self.default_input_visible_map = {}  # map of default input filters for devices [device_guid][input_type][input_id] = bool (true if visible, false if not) - no data = not visible/selected
        self.default_input_loaded_map = {}  # map of device id to flag indicating if defaults were loaded for the device already or not
        self.reset()  # this loads defaults

    def reset(self):
        """resets setting"""
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose:
            syslog.info("profile settings reset...")
        self.vjoy_as_input.clear()
        self.maestro_as_input.clear()
        self.vjoy_initial_values.clear()
        self.startup_mode = None
        self.default_delay = 0.05
        self.input_visible_map.clear()

        self.loadFilterDefaults()  # loads the default input filter
        fname = self.profile.profile_file
        if fname and os.path.isfile(fname):
            tree = etree.parse(fname)
            root = tree.getroot()
            settings_node = root.find("settings")
            self.from_xml(settings_node)

    def to_xml(self):
        """Returns an XML node containing the settings.

        :return XML node containing the settings
        """
        node = etree.Element("settings")

        # Startup mode
        if self.startup_mode is not None:
            mode_node = etree.Element("startup-mode")
            mode_node.text = safe_format(self.startup_mode, str)
            node.append(mode_node)

        # Default delay
        delay_node = etree.Element("default-delay")
        delay_node.text = safe_format(self.default_delay, float)
        node.append(delay_node)

        # Process vJoy as input settings
        for vid, visible in self.vjoy_as_input.items():
            if visible is True:
                vjoy_node = etree.Element("vjoy-input")
                vjoy_node.set("id", safe_format(vid, int))
                node.append(vjoy_node)

        # proces maestro as input settings
        for mid, visible in self.maestro_as_input.items():
            if visible is True:
                maestro_node = etree.Element("maestro-input")
                maestro_node.set("id", safe_format(mid, int))
                node.append(maestro_node)

        # Process vJoy axis initial values
        for vid, data in self.vjoy_initial_values.items():
            vjoy_node = etree.Element("vjoy")
            vjoy_node.set("id", safe_format(vid, int))
            for aid in data:
                enabled, visible = data[aid]
                axis_node = etree.Element("axis")
                axis_node.set("id", safe_format(aid, int))
                axis_node.set("value", safe_format(visible, float))
                axis_node.set("enabled", safe_format(enabled, bool))
                vjoy_node.append(axis_node)
            node.append(vjoy_node)

        # input visibility filters for the devices
        if self.input_visible_map:
            root_filter_node = etree.Element("input-filter")
            version_node = etree.Element("version")
            # version 0: legacy filter format, presence of filter node means filter on, no value needed
            # version 1: explicit filter value, presence of filter node means filter on, value
            version_node.set("version", "1")
            root_filter_node.append(version_node)
            node.append(root_filter_node)
            for device_guid in self.input_visible_map:
                device = gremlin.joystick_handling.getDevice(device_guid)
                if device:
                    device_id = device.device_id
                    device_node = etree.Element("device")
                    device_node.set("device", device_id)
                    device_node.set("name", device.name)
                    root_filter_node.append(device_node)

                    for input_type in self.input_visible_map[device_guid]:
                        for input_id in self.input_visible_map[device_guid][input_type]:
                            visible = self.input_visible_map[device_id][input_type][input_id]
                            # only save non filtered inputs (they are usually less than the filtered ones)
                            if visible:
                                filter_node = etree.Element("filter")
                                filter_node.set("type", InputType.to_string(input_type))
                                filter_node.set("id", safe_format(input_id, int))
                                filter_node.set("visible", safe_format(visible, bool))
                                device_node.append(filter_node)

        return node

    def vjoyAsInput(self, vid: int):
        """true if vjoy device is setup as input in the profile options"""
        return vid in self.vjoy_as_input

    def from_xml(self, node, data=None, extra_data=None):
        """Populates the data storage with the XML node's contents.

        :param node the node containing the settings data
        """

        if node is None:
            return

        sd = gremlin.event_handler.JoystickState()

        # Startup mode
        self.startup_mode = None
        if node.find("startup-mode") is not None:
            self.startup_mode = node.find("startup-mode").text

        # Default delay
        self.default_delay = 0.05
        if node.find("default-delay") is not None:
            self.default_delay = float(node.find("default-delay").text)

        # vJoy as input settings
        self.vjoy_as_input.clear()

        for vjoy_node in node.findall("vjoy-input"):
            vid = safe_read(vjoy_node, "id", int, 0)
            device = gremlin.joystick_handling.vjoy_info_from_vjoy_id(vid)
            if device:
                device_guid = device.device_guid
                sd.setOutputEnabled(device_guid, True)  # allow as output
                sd.setInputEnabled(device_guid, True)  # allow as input
            self.vjoy_as_input[vid] = True

        # maestro as input settings
        self.maestro_as_input.clear()
        for maestro_node in node.findall("maestro-input"):
            mid = safe_read(maestro_node, "id", int, 0)
            device = gremlin.joystick_handling.maestro_info_from_index(mid)
            if device:
                device_guid = device.device_guid
                sd.setOutputEnabled(device_guid, True)  # allow as output
                sd.setInputEnabled(device_guid, True)  # allow as input
            self.maestro_as_input[mid] = True

        # vjoy initialization values
        self.vjoy_initial_values = {}
        for vjoy_node in node.findall("vjoy"):
            vid = safe_read(vjoy_node, "id", int, 0)
            self.vjoy_initial_values[vid] = {}
            for axis_node in vjoy_node.findall("axis"):
                aid = safe_read(axis_node, "id", int, 0)
                value = safe_read(axis_node, "value", float, 0.0)
                enabled = False
                if "enabled" in axis_node.attrib:
                    enabled = safe_read(axis_node, "enabled", bool, True)

                self.vjoy_initial_values[vid][aid] = (enabled, value)

        # load input visibility saved in the profile

        version_node = node.find("./input-filter/version")
        if version_node is not None:
            version = safe_read(version_node, "version", int, Settings.filter_version)
        else:
            version = 0  # not set, assume legacy format

        self.input_visible_map = {}
        self.loadFilterDefaults()

        # read the device list as it will tell GEX that the device was previously viewed
        for device_node in node.xpath("./input-filter/device"):
            if "id" in device_node.attrib:
                device_id = safe_read(device_node, "id", str, "")
            elif "device" in device_node.attrib:
                device_id = safe_read(device_node, "device", str, "")
            else:
                raise ValueError("invalid device filter tag: missing tag [device]")

            self.input_visible_map[device_id] = {}
            device = gremlin.joystick_handling.getDevice(device_id)

            match version:
                case 0:
                    for filter_node in node.xpath("./input-filter/filter"):
                        device_id = safe_read(filter_node, "device", str, "")
                        input_type = InputType.to_enum(safe_read(filter_node, "type", str, ""))
                        input_id = safe_read(filter_node, "id", int, -1)
                        visible = safe_read(filter_node, "filter", bool, False)
                        self.setInputVisible(device_id, input_type, input_id, visible)
                case 1:
                    for filter_node in device_node.xpath(".//filter"):
                        input_type = InputType.to_enum(safe_read(filter_node, "type", str, ""))
                        input_id = safe_read(filter_node, "id", int, -1)
                        visible = safe_read(filter_node, "visible", bool, False)
                        self.setInputVisible(device_id, input_type, input_id, visible)

                case _:
                    raise ValueError(f"don't know how to handle filter version [{version}] in profile settings")

    def getDefaultFilterXmlFilename(self) -> str:
        """gets the file name for the default profile input filtering data"""
        return os.path.join(gremlin.util.userprofile_path(), "default_filter.xml")

    def setVjoyAsInput(self, vid, enabled=True):
        """enables a vjoy device as an input device"""
        self.vjoy_as_input[vid] = enabled
        sd = gremlin.event_handler.JoystickState()
        sd.setVjoyAsInput(vid, enabled)

    def get_vjoy_axis_enabled(self, vid, aid) -> bool:
        """true if the value is enabled for this axis"""
        if vid in self.vjoy_initial_values:
            if aid in self.vjoy_initial_values[vid]:
                enabled, value = self.vjoy_initial_values[vid][aid]
                return enabled
        return False

    def set_vjoy_axis_enabled(self, vid, aid, value=None) -> bool:
        """true if the value is enabled for this axis"""
        if vid not in self.vjoy_initial_values:
            self.vjoy_initial_values[vid] = {}
        if aid not in self.vjoy_initial_values[vid]:
            self.vjoy_initial_values[vid][aid] = (
                True,
                value if value is not None else 0.0,
            )
        else:
            if value is None:
                self.vjoy_initial_values[vid][aid][0] = True
            else:
                self.vjoy_initial_values[vid][aid][0] = (True, value)

    def get_initial_vjoy_axis_value_list(self):
        """gets all defined default values as a triplet (vjoy_id, axis_id, value)"""
        data = []
        for vid in self.vjoy_initial_values:
            for aid in self.vjoy_initial_values[vid]:
                enabled, value = self.vjoy_initial_values[vid][aid]
                if enabled:
                    data.append((vid, aid, value))

        return data

    def get_initial_vjoy_axis_value(self, vid, aid):
        """Returns the initial value a vJoy axis should use.

        :param vid the id of the virtual joystick
        :param aid the id of the axis
        :return default value for the specified axis
        """
        if vid in self.vjoy_initial_values:
            if aid in self.vjoy_initial_values[vid]:
                enabled, value = self.vjoy_initial_values[vid][aid]
                if enabled:
                    return value
        return 0.0

    def set_initial_vjoy_axis_value(self, vid, aid, value):
        """Sets the default value for a particular vJoy axis.

        :param vid the id of the virtual joystick
        :param aid the id of the axis
        :param value the default value to use with the specified axis
        """
        if vid not in self.vjoy_initial_values:
            self.vjoy_initial_values[vid] = {}
        self.vjoy_initial_values[vid][aid] = value

    def getDeviceFiltered(self, device_guid) -> bool:
        """true if the device can be input filtered"""
        assert device_guid is not None, "invalid device guid"
        device = gremlin.joystick_handling.getDevice(device_guid)
        if device is not None:
            return device.device_type in (
                DeviceType.Joystick,
                DeviceType.VJoy,
            )  # filter by default if a joystick device
        return False

    def isFiltered(self, device_guid: dinput.GUID | str | int) -> bool:
        """true if the device has inputs that are currently filtered"""
        assert device_guid is not None, "invalid device guid"
        device = gremlin.joystick_handling.getDevice(device_guid)
        if not device:
            syslog.warning(f"PROFILE IS FILTER: unknown device [{device_guid}]")
            return False
        device_guid = device.device_guid
        if device_guid not in self.input_visible_map:
            return False
        for input_type in self.input_visible_map[device_guid]:
            for input_id in self.input_visible_map[device_guid][input_type]:
                if self.input_visible_map[device_guid][input_type][input_id]:
                    return True
        return False

    def filterHash(self, input_filter) -> int:
        """computes a hash value for the specified input filter"""
        return hash(frozenset(input_filter.values()))

    def getInputFilter(self, device_guid: dinput.GUID | str | int) -> frozendict:
        """gets the stored input filter map for the given device"""

        input_filter = {}
        assert device_guid is not None, "invalid device guid"

        def setFilter(device_guid, input_type, input_id, value):
            nonlocal input_filter
            assert isinstance(device_guid, str), "input filter key must be a string"
            if device_guid not in input_filter:
                input_filter[device_guid] = {}
            if input_type not in input_filter[device_guid]:
                input_filter[device_guid][input_type] = {}
            input_filter[device_guid][input_type][input_id] = value

        if self.getDeviceFiltered(device_guid):
            device = gremlin.joystick_handling.getDevice(device_guid)
            device_guid = gremlin.util.normalize_guid(self.device_guid)  # key must be a string
            if device:
                input_type = InputType.JoystickAxis
                for index in range(device.axis_count):
                    input_id = device.axis_sequence_to_input_id(index)
                    included = self.getInputVisible(device_guid, input_type, input_id)
                    if included:
                        setFilter(device_guid, input_type, input_id, included)

                input_type = InputType.JoystickButton
                for input_id in range(1, device.button_count + 1):
                    included = self.getInputVisible(device_guid, input_type, input_id)
                    if included:
                        setFilter(device_guid, input_type, input_id, included)

        return input_filter

    def getInputFilterForDevice(self, device_guid: dinput.GUID | str | int):
        """gets filter data for a given device"""
        assert device_guid is not None, "invalid device guid"
        device_id = gremlin.util.normalize_guid(device_guid)
        data = {}
        if device_id not in self.input_visible_map:
            return data
        data[device_id] = {}
        for input_type in self.input_visible_map[device_id]:
            data[device_id][input_type] = {}
            for input_id in self.input_visible_map[device_id][input_type]:
                data[device_id][input_type][input_id] = self.input_visible_map[device_id][input_type][input_id]

        return data

    def getJoystickInputStats(self, device_guid: dinput.GUID | str | int) -> JoystickInputStats:
        """returns a stats object holding filtered data"""
        return JoystickInputStats(device_guid, self.input_visible_map)

    def _set_default_input_visible_list(self, device: dinput.DeviceSummary, input_type: InputType, max_count: int):
        """gets a default list of filtered inputs based on given parameters"""
        assert isinstance(device, dinput.DeviceSummary), "invalid device"
        device_guid = device.device_guid
        match input_type:
            case InputType.JoystickAxis:
                device_count = device.axis_count
                input_id_list = []
                for index in range(1, device_count + 1):
                    input_id = device.getAxisLinearId(index)
                    if input_id is None:
                        continue
                    if len(input_id_list) < max_count:
                        input_id_list.append(input_id)
                    else:
                        break

            case InputType.JoystickButton:
                device_count = min(max_count, device.button_count)
                input_id_list = [index + 1 for index in range(device_count)]
            case InputType.JoystickHat:
                device_count = min(max_count, device.hat_count)
                input_id_list = [index + 1 for index in range(device_count)]
            case _:
                # not an input type we care about
                return
        map_data = input_id_list

        self.clearDeviceFilters(device)  # clear current inputs
        # update with new defaults

        for input_id in map_data:
            self.setInputVisible(device_guid, input_type, input_id, True)

    def setMappedVisible(self, current_mode: str = None, additive=False):
        """includes all inputs for a specific mode or all modes"""
        for device in gremlin.joystick_handling.all_joystick_devices():
            self.setMappedVisibleDevice(device, current_mode, additive)

    def setMappedVisibleDevice(self, device: dinput.DeviceSummary, current_mode: str = None, additive=False):
        """includes all inputs for a specific mode or all modes"""
        assert isinstance(device, dinput.DeviceSummary), "invalid device"
        if not additive:
            self.clearDeviceFilters(device)  # clear any filters
        device_guid = device.device_guid
        for index in range(device.axis_count):
            input_id = device.axis_sequence_to_input_id(index)
            is_used = self.profile.isInputMapped(device_guid, InputType.JoystickAxis, input_id, current_mode)
            self.setInputVisible(device_guid, InputType.JoystickAxis, input_id, is_used)
        for index in range(device.button_count):
            input_id = index + 1
            is_used = self.profile.isInputMapped(device_guid, InputType.JoystickButton, input_id, current_mode)
            self.setInputVisible(device_guid, InputType.JoystickButton, input_id, is_used)
        for index in range(device.hat_count):
            input_id = index + 1
            is_used = self.profile.isInputMapped(device_guid, InputType.JoystickHat, input_id, current_mode)
            self.setInputVisible(device_guid, InputType.JoystickHat, input_id, is_used)

    def setAllVisibleDevice(self, device: dinput.DeviceSummary, additive=False):
        """sets all inputs to visible (unfiltered) for a specific device"""
        assert isinstance(device, dinput.DeviceSummary), "invalid device"
        if not additive:
            self.clearDeviceFilters(device)  # clear any filters
        device_guid = device.device_guid
        for index in range(device.axis_count):
            input_id = device.axis_sequence_to_input_id(index)
            self.setInputVisible(device_guid, InputType.JoystickAxis, input_id, True)
        for index in range(device.button_count):
            input_id = index + 1
            self.setInputVisible(device_guid, InputType.JoystickButton, input_id, True)
        for index in range(device.hat_count):
            input_id = index + 1
            self.setInputVisible(device_guid, InputType.JoystickHat, input_id, True)

    def setAllvisible(self):
        """sets all inputs to visible (unfiltered) for all devices"""
        for device in gremlin.joystick_handling.all_joystick_devices():
            self.setAllVisibleDevice(device)

    def setAllHiddenDevice(self, device: dinput.DeviceSummary):
        """sets all inputs to hidden (filtered) for a specific device"""
        assert isinstance(device, dinput.DeviceSummary), "invalid device"
        device_guid = device.device_guid
        for index in range(device.axis_count):
            input_id = device.axis_sequence_to_input_id(index)
            self.setInputVisible(device_guid, InputType.JoystickAxis, input_id, False)
        for index in range(device.button_count):
            input_id = index + 1
            self.setInputVisible(device_guid, InputType.JoystickButton, input_id, False)
        for index in range(device.hat_count):
            input_id = index + 1
            self.setInputVisible(device_guid, InputType.JoystickHat, input_id, False)

    def setallHidden(self):
        """sets all inputs to hidden (filtered) for all devices"""
        for device in gremlin.joystick_handling.all_joystick_devices():
            self.setAllHiddenDevice(device)

    def setAllDefault(self, additive=False):
        """sets the default filter to show all inputs that are mapped in any profile mode, then fills in remaining slots with unmapped inputs"""
        for device in gremlin.joystick_handling.all_joystick_devices():
            self.setDeviceDefault(device, additive)

    def setDeviceDefault(self, device: dinput.DeviceSummary, additive=False):
        """sets the default filter for a specific device to show all inputs that are mapped in any profile mode, then fills in remaining slots with unmapped inputs"""
        assert isinstance(device, dinput.DeviceSummary), "invalid device"
        # clear the existing device data
        if not additive:
            self.clearDeviceFilters(device)  # clear any filters
        self.setFilterDefaults(device.device_guid)

    def setInputTypeVisibleDevice(self, device: dinput.DeviceSummary, input_type: InputType, visible: bool, additive=False):
        """sets all inputs of the given type to visible for the given device"""
        assert isinstance(device, dinput.DeviceSummary), "invalid device"
        device_guid = device.device_guid
        if visible and not additive:
            self.clearDeviceFilters(device)
        match input_type:
            case InputType.JoystickAxis:
                for index in range(device.axis_count):
                    input_id = device.axis_sequence_to_input_id(index)
                    self.setInputVisible(device_guid, InputType.JoystickAxis, input_id, visible)
            case InputType.JoystickButton:
                for index in range(device.button_count):
                    input_id = index + 1
                    self.setInputVisible(device_guid, InputType.JoystickButton, input_id, visible)
            case InputType.JoystickHat:
                for index in range(device.hat_count):
                    input_id = index + 1
                    self.setInputVisible(device_guid, InputType.JoystickHat, input_id, visible)

    def getFilterMap(self):
        """gets a copy of the current input filter map"""
        return self.input_visible_map.copy()

    def getDefaultFilterMap(self):
        """gets a copy of the default device input filter map"""
        return self.default_input_visible_map.copy()

    def setFilterMap(self, input_map: dict):
        """saves the input map to the profile settings"""
        self.input_visible_map = input_map.copy()

    def setDefaultFilterMap(self, input_map: dict):
        """saves the default input map to the profile settings"""
        self.default_input_visible_map = input_map.copy()

    def setInputTypeVisible(self, input_type: InputType, visible: bool, additive=False):
        for device in gremlin.joystick_handling.all_joystick_devices():
            self.setInputTypeVisibleDevice(device, input_type, visible, additive)

    def clearDeviceFilters(self, device: dinput.DeviceSummary):
        """clears the filter for a specific device"""
        if device is None:
            # device not found
            return
        device_id = device.device_id
        if device_id in self.input_visible_map:
            del self.input_visible_map[device_id]

    def clearDefaultDeviceFilters(self, device: dinput.DeviceSummary):
        """clears the default filter for a specific device"""
        if device is None:
            # device not found
            return
        device_id = device.device_id
        if device_id in self.default_input_visible_map:
            del self.default_input_visible_map[device_id]

    def setAllDevicesDefault(self):
        """sets all inputs to their default visible state for all devices"""
        device_list = list(gremlin.joystick_handling.all_joystick_devices())
        for device in device_list:
            self.setDeviceDefault(device)

    def setAllVisible(self, mode: str):
        """set all joystick device filtered list based on requested mode
        :param mode: "default","mapped","hide_all","show_all"
        """
        match mode:
            case "default":
                # set all joystick devices to default
                self.setAllDevicesDefault()

            case "mapped":
                # set all joystick devices to show mapped inputs - specific profile mode
                current_mode = gremlin.shared_state.edit_mode
                self._set_all_used_visible(current_mode)

            case "mapped_all":
                # all profile modes '''
                self._set_all_used_visible()

            case "hide_all":
                # set all joystick devices to hidden (max performance)
                self.input_visible_map.clear()

            case "show_all":
                # set all joystick devices to visible (unfiltered)
                self.setAllVisible()

    def dump_visible_map(self, p_device_guid=None):
        """dumps the current input filter to the log file"""
        syslog.info("=" * 30)
        syslog.info("input filter dump")

        count = 0
        if p_device_guid is not None:
            device = gremlin.joystick_handling.getDevice(p_device_guid)
            p_device_id = gremlin.util.normalize_guid(p_device_guid)
        else:
            p_device_id = None

        if p_device_id not in self.input_visible_map:
            syslog.info(f"\tNo inputs defined in the filter map for device: {device.name} id {p_device_id}")
            return
        for device_id in self.input_visible_map:
            if p_device_id and device_id != p_device_id:
                continue

            syslog.info("=" * 30)
            device = gremlin.joystick_handling.getDevice(device_id)
            syslog.info(f"Profile input filter dump for {device.name}")
            visible_count = 0
            for input_type in self.input_visible_map[device_id]:
                for input_id in self.input_visible_map[device_id][input_type]:
                    visible = self.getInputVisible(device_id, input_type, input_id)
                    if input_type == InputType.JoystickAxis:
                        device = gremlin.joystick_handling.getDevice(device_id)
                        linear_id = device.getAxisLinearId(input_id)
                        syslog.info(f"\t{input_type.name} axis {id} L{linear_id} {{device.get_axis_name(input_id)}} visible: {visible}")
                    else:
                        syslog.info(f"\t{input_type.name} {input_id} visible: {visible}")
                    if visible:
                        visible_count += 1
                    count += 1

            syslog.info(f"\tVisible count: {visible_count}")
            syslog.info("-" * 30)
            syslog.info(f"Default Input filter dump for {device.name}")
            visible_count = 0
            if device_id in self.default_input_visible_map:
                for input_type in self.default_input_visible_map[device_id]:
                    for input_id in self.default_input_visible_map[device_id][input_type]:
                        visible = self.getDefaultInputVisible(device_id, input_type, input_id)
                        if visible:
                            visible_count += 1
                        syslog.info(f"\t{input_type.name} {input_id} visible: {visible}")

            syslog.info(f"\tDefault Visible count: {visible_count}")

        syslog.info(f"Found {count} total entries")

    def setInputVisible(
        self,
        device_guid: dinput.GUID | str | int,
        input_type: InputType,
        input_id: int,
        visible: bool,
        emit=False,
    ):
        """marks a joystick input as filtered or not

        filtered = included in the UI
        not filtered = not included in the UI (hidden)


        """
        device = gremlin.joystick_handling.getDevice(device_guid)
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_filter or config.verbose_mode_ui
        # verbose = True
        if not device:
            if verbose:
                syslog.warning(f"PROFILE SET FILTER: unknown device [{device_guid}]")
            return

        device_id = device.device_id  # key must be a string
        if device_id not in self.input_visible_map:
            self.input_visible_map[device_id] = {}
        if input_type not in self.input_visible_map[device_id]:
            self.input_visible_map[device_id][input_type] = {}

        self.input_visible_map[device_id][input_type][input_id] = visible
        if verbose:
            if input_type == InputType.JoystickAxis:
                syslog.info(f"Settings: set input visible: {device.name} {input_type.name} [{device.getAxisName(input_id)}] visible: {visible}")
            else:
                syslog.info(f"Settings: set input visible: {device.name} {input_type.name} [{input_id}] visible: {visible}")

        if emit:
            el = gremlin.event_handler.EventListener()
            el.input_filtered_change.emit(device_id)  # tell the widget the input list has changed

    def setDefaultInputVisible(
        self,
        device_guid: dinput.GUID | str | int,
        input_type: InputType,
        input_id: int,
        visible: bool,
    ):
        """marks a joystick input as default filtered or not"""
        device = gremlin.joystick_handling.getDevice(device_guid)
        if device:
            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_filter or config.verbose_mode_ui
            device_id = device.device_id  # key must be a string
            if device_id not in self.default_input_visible_map:
                self.default_input_visible_map[device_id] = {}
            if input_type not in self.default_input_visible_map[device_id]:
                self.default_input_visible_map[device_id][input_type] = {}

            self.default_input_visible_map[device_id][input_type][input_id] = visible

            if verbose:
                syslog.info(f"Settings: set default filter: [{device.name}] axis: [{input_id}] included: {visible}")

    def getVisibleCount(self, device_guid: dinput.GUID | str | int, input_map: dict, input_type: InputType | list[InputType] = None) -> int:
        """gets the count of visible (unfiltered) inputs for the device based on current filter options"""
        count = 0
        device_guid = gremlin.util.normalize_guid(device_guid)  # key must be a string
        if device_guid in input_map:
            if input_type is not None:
                # filter by specific input type
                if hasattr(input_type, "__iter__") and not isinstance(input_type, InputType):
                    # list of input types
                    for it in input_type:
                        if it in input_map[device_guid]:
                            count += sum(1 for input_id in input_map[device_guid][it] if input_map[device_guid][it][input_id])
                elif isinstance(input_type, InputType):
                    count += sum(1 for input_id in input_map[device_guid][input_type] if input_map[device_guid][input_type][input_id])
            else:
                # all types
                for input_type in input_map[device_guid]:
                    count += sum(1 for input_id in input_map[device_guid][input_type] if input_map[device_guid][input_type][input_id])
        return count

    def isDefaultFiltered(self, device_guid: dinput.GUID | str | int) -> bool:
        """true if the device has default filter data saved"""
        device_guid = gremlin.util.normalize_guid(device_guid)  # key must be a string
        return device_guid in self.default_input_visible_map

    def clearDefaultsFiltered(self, device_guid: dinput.GUID | str | int):
        device_guid = gremlin.util.normalize_guid(device_guid)  # key must be a string
        if device_guid in self.default_input_visible_map:
            del self.default_input_visible_map[device_guid]
            return self.saveFilterDefaults()
        return True

    def hasFilterDefinition(self, device_guid: dinput.GUID | str | int) -> bool:
        """true if the device has saved filter data"""
        device_guid = gremlin.util.normalize_guid(device_guid)  # key must be a string
        device = gremlin.joystick_handling.getDevice(device_guid)
        if device:
            if device_guid in self.input_visible_map:
                return True
            if device_guid in self.default_input_visible_map:
                return True
        return False

    def getVisibleInputCounts(
        self,
        device_guid: dinput.GUID | str | int,
        input_type: InputType | list[InputType],
        as_list : bool = False
    ) -> int:
        """gets the counts of filtered inputs in the device in the profile input filter settings - add multiple types by including them in the list"""

        input_type_list = input_type if hasattr(input_type, "__iter__") else [input_type]
        count = 0
        device_guid = gremlin.util.normalize_guid(device_guid)  # key must be a string
        item_list = []
        if device_guid in self.input_visible_map:
            for input_type in input_type_list:
                if input_type in self.input_visible_map[device_guid]:
                    filtered_count = sum(
                        1 if self.input_visible_map[device_guid][input_type][input_id] else 0 for input_id in self.input_visible_map[device_guid][input_type]
                    )
                    count += filtered_count
                    if as_list:
                        item_list.extend(
                            (device_guid, input_type, input_id) for input_id in self.input_visible_map[device_guid][input_type] if self.input_visible_map[device_guid][input_type][input_id]
                        )


        return item_list if as_list else count

    def getInputVisible(
        self,
        device_guid: dinput.GUID | str | int,
        input_type: InputType,
        input_id: int | object,
    ) -> bool:
        """gets the joystick input filtered state

        :returns bool: True if the item is visible in the model
        """
        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "invalid device"
        if device.disabled:
            # disabled devices
            return False
        device_id = device.device_id  # key must be a string
        # config = gremlin.config.Configuration()
        # verbose = config.verbose_mode_filter or config.verbose_mode_ui
        # # verbose = True
        device_guid = device.device_guid  # ensure a dinput.GUID

        visible = False

        # load default inputs for device if not in default map
        if device_id not in self.default_input_visible_map:
            # device not in active filter list - ensure we apply the defaults
            self.setFilterDefaults(device_guid)
            self.syncFilterDefaults(device_guid)

        if device_id not in self.input_visible_map:
            self.syncFilterDefaults(device_guid)
            if device_id not in self.input_visible_map:
                # no defaults applied
                self.input_visible_map[device_id] = {}

        if input_type not in self.input_visible_map[device_id]:
            self.input_visible_map[device_id][input_type] = {}

        if input_id not in self.input_visible_map[device_id][input_type]:
            self.input_visible_map[device_id][input_type][input_id] = False

        if not self.input_visible_map[device_id][input_type][input_id]:
            # override if input has a mapping
            mode = gremlin.shared_state.current_mode
            visible = self.profile.isInputMapped(device_guid, input_type, input_id, mode)
            if visible:
                self.input_visible_map[device_id][input_type][input_id] = True

        return self.input_visible_map[device_id][input_type][input_id]

    def getDefaultInputVisible(self, device_guid: dinput.GUID | str | int, input_type: InputType, input_id: int | object) -> bool:
        """gets the joystick input default filtered state

        :returns bool: True if the item is visible in the model
        """
        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "invalid device"
        device_guid = gremlin.util.normalize_guid(device.device_guid)  # key must be a string
        # load defaults if not already loaded

        if device_guid in self.default_input_visible_map:
            if input_type in self.default_input_visible_map[device_guid]:
                if input_id in self.default_input_visible_map[device_guid][input_type]:
                    return self.default_input_visible_map[device_guid][input_type][input_id]

        return False  # include in display if no entry

    def getInputVisibleMap(self):
        """gets the input filter"""
        return copy.deepcopy(self.input_visible_map)  # return a copy so settings are not mutable

    def applyFilter(self, input_filter: dict):
        """applies the filter data from the input filter"""
        for device_guid in input_filter:
            for input_type in input_filter[device_guid]:
                for input_id in input_filter[device_guid][input_type]:
                    filtered = input_filter[device_guid][input_type][input_id]
                    self.setInputVisible(device_guid, input_type, input_id, filtered, False)

    def applyFilterDefaults(self):
        """applies defaults to missing device if any"""

        # review defaults for all joystick devices
        device_list = gremlin.joystick_handling.getValidJoystickDevicesMap().values()
        device: dinput.DeviceSummary
        for device in device_list:
            # come up with a suitable default
            assert device is not None, "invalid device"
            assert device.device_type in (DeviceType.Maestro, DeviceType.Joystick,DeviceType.VJoy), "not a joystick axis"
            if device.disabled:
                # skip disabled devices
                continue
            self.setFilterDefaults(device.device_guid)

    def setFilterDefaults(self, device_guid: dinput.GUID, force=False):
        """sets the default visible inputs for a given joystick"""
        assert isinstance(device_guid, dinput.GUID), "invalid device"
        device = gremlin.joystick_handling.getDevice(device_guid)
        if not device:
            return

        if device.device_type not in (DeviceType.Maestro, DeviceType.Joystick, DeviceType.VJoy):
            # not a joystick axis
            return
        if device.disabled:
            # disabled device
            return

        device_id = device.device_id
        if force or device_id not in self.default_input_loaded_map:
            self.default_input_loaded_map[device_id] = True  # mark loaded
            config = gremlin.config.Configuration()
            cfg_max_axis = config.device_filter_max_axis
            cfg_max_button = config.device_filter_max_button
            cfg_max_hat = config.device_filter_max_hat

            max_axis = min(cfg_max_axis, device.axis_count)
            max_button = min(cfg_max_button, device.button_count)
            max_hat = min(cfg_max_hat, device.hat_count)
            data = [
                (InputType.JoystickAxis, max_axis),
                (InputType.JoystickButton, max_button),
                (InputType.JoystickHat, max_hat),
            ]
            # force an entry so settings knows we looked at this device already
            self.default_input_visible_map[device_id] = {}
            for input_type, count in data:
                if count:
                    for input_id in range(1, count + 1):
                        self.setDefaultInputVisible(device_guid, input_type, input_id, True)
                        self.setInputVisible(device_guid, input_type, input_id, True)

        pass

    def syncFilterDefaults(self, device_guid: dinput.GUID):
        """syncs default device input swith actual for a given joystick"""
        assert isinstance(device_guid, dinput.GUID), "invalid device"
        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "device not found"
        if device.device_type not in (DeviceType.Maestro, DeviceType.Joystick, DeviceType.VJoy):
            # not a joystick axis
            return

        device_id = device.device_id
        if device_id in self.default_input_visible_map:
            for input_type in self.default_input_visible_map[device_id]:
                for input_id in self.default_input_visible_map[device_id][input_type]:
                    visible = self.default_input_visible_map[device_id][input_type][input_id]
                    self.setInputVisible(device_guid, input_type, input_id, visible)

    def loadFilterDefaults(self) -> bool:
        """load default input filters from the configuration file"""
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose:
            syslog.info("profile settings load filter defaults...")
        self.default_input_visible_map.clear()
        self.default_input_loaded_map.clear()
        self.input_visible_map.clear()
        fname = self.getDefaultFilterXmlFilename()

        # start with default data for all devices, then override with saved data if it exists
        self.setAllDevicesDefault()

        # load specific defaults for the device if found
        if os.path.isfile(fname):
            parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
            tree = etree.parse(fname, parser=parser)
            root = tree.getroot()

            # version node
            version_node = root.find("version")
            version = safe_read(version_node, "version", int, 0) if version_node is not None else 0

            match version:
                case 0:
                    # load v0 nodes
                    if verbose:
                        syslog.info("Using version 0 for device filter defaults")
                    device_nodes = root.xpath("//input-filter/device")
                    for device_node in device_nodes:
                        device_guid = safe_read(device_node, "id", str, "")
                        self.default_input_visible_map[device_guid] = {}  # reset default for this device only
                        self.input_visible_map[device_guid] = {}  # reset visible list

                    filter_nodes = root.xpath("//input-filter/filter")

                    if filter_nodes:
                        for filter_node in filter_nodes:
                            device_id = safe_read(filter_node, "device", str, "")
                            device = gremlin.joystick_handling.getDevice(device_id)
                            input_type = InputType.to_enum(safe_read(filter_node, "type", str, ""))
                            input_id = safe_read(filter_node, "id", int, -1)
                            visible = safe_read(filter_node, "visible", bool, False)
                            if verbose:
                                if input_type == InputType.JoystickAxis:
                                    syslog.info(f"\t{input_type.name} [{device.getAxisName(input_id)}] visible: {visible}")
                                else:
                                    syslog.info(f"\t{input_type.name} [{input_id}] visible: {visible}")
                            self.setDefaultInputVisible(device_guid, input_type, input_id, visible)
                            self.setInputVisible(device_guid, input_type, input_id, visible)
                case 1:
                    # load v1 nodes
                    if verbose:
                        syslog.info("Using version 1 for device filter defaults")
                    device_nodes = root.xpath("//input-filter/device")
                    for device_node in device_nodes:
                        device_id = safe_read(device_node, "device", str, "")
                        device = gremlin.joystick_handling.getDevice(device_id)
                        if device is None or device.disabled:
                            # skip disconnected or disabled devices
                            continue

                        self.default_input_visible_map[device_id] = {}  # reset default for this device only
                        self.input_visible_map[device_id] = {}  # reset visible list

                        if verbose:
                            device = gremlin.joystick_handling.getDevice(device_id)
                            if device is None:
                                syslog.info(f"\tdevice {device_id} not connected - skipping")
                                continue

                            syslog.info(f"\tFound device: {device.name} [{device_id}]")

                        filter_nodes = device_node.xpath(".//filter")
                        for filter_node in filter_nodes:
                            input_type = InputType.to_enum(safe_read(filter_node, "type", str, ""))
                            input_id = safe_read(filter_node, "id", int, -1)
                            visible = safe_read(filter_node, "visible", bool, False)
                            self.setDefaultInputVisible(device_id, input_type, input_id, visible)
                            self.setInputVisible(device_id, input_type, input_id, visible)
                            if verbose:
                                if input_type == InputType.JoystickAxis:
                                    syslog.info(f"\t{input_type.name} [{device.getAxisName(input_id)}] visible: {visible}")
                                else:
                                    syslog.info(f"\t{input_type.name} [{input_id}] visible: {visible}")

                        pass

                case _:
                    raise ValueError(f"unexpected version [{version}] in device filter data")

        # self.dump_visible_map()

    def saveFilterDefaults(self, device_guid=None) -> bool:
        """saves the filter defaults to XML - can be device specific if the device id is provided"""
        # default data
        fname = self.getDefaultFilterXmlFilename()
        xml_version = 1  # current xml file version

        if self.default_input_visible_map:
            # load default input filters

            if device_guid is None:
                source = self.default_input_visible_map.keys()
            else:
                source = [gremlin.util.normalize_guid(device_guid)]

            # load existing file if it exists
            if os.path.isfile(fname):
                try:
                    parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
                    tree = etree.parse(fname, parser=parser)
                    root = tree.getroot()

                except Exception as ex:
                    # read error
                    syslog.error(f"Error loading device defaults: {ex}")
                    return False

            else:
                # file does not exist
                root = etree.Element("input-filter")

            # version node
            version_node = root.find("version")
            version = safe_read(version_node, "version", int, 0) if version_node is not None else 0

            for device_id in source:
                # filter by the device only
                device = gremlin.joystick_handling.getDevice(device_id)
                if device is None:
                    # leave that alone as it may be disconnected
                    continue

                if version == 0:
                    # old style devices

                    nodes = root.xpath(f"//device[@id='{device_id}']")
                    for node in nodes:
                        node.getparent().remove(node)

                    # remove existing nodes for the device
                    nodes = root.xpath(f"//filter[@device='{device_id}']")
                    for node in nodes:
                        node.getparent().remove(node)

                # remove device node (also removes all inputs in version >= 1
                nodes = root.xpath(f"//device[@device='{device_id}']")
                for node in nodes:
                    node.getparent().remove(node)

                if version_node is None:
                    # add a version node
                    version_node = etree.Element("version")
                    root.insert(0, version_node)

                # update to the current version
                version_node.set("version", safe_format(xml_version, int))

                # add new nodes
                if device_id in self.default_input_visible_map:
                    # device node
                    device_node = etree.Element("device")
                    device_node.set("device", device_id)
                    device = gremlin.joystick_handling.getDevice(device_id)
                    assert device is not None, "invalid device"
                    device_node.set("name", device.name)
                    root.append(device_node)

                    for input_type in self.default_input_visible_map[device_id]:
                        for input_id in self.default_input_visible_map[device_id][input_type]:
                            visible = self.default_input_visible_map[device_id][input_type][input_id]
                            if visible:
                                # only save visible entries
                                filter_node = etree.Element("filter")
                                filter_node.set("type", InputType.to_string(input_type))
                                filter_node.set("id", safe_format(input_id, int))
                                filter_node.set("visible", safe_format(visible, bool))
                                device_node.append(filter_node)

            # save the new defaults
            try:
                if os.path.isfile(fname):
                    # blitz existing
                    os.unlink(fname)
                tree.write(
                    fname,
                    pretty_print=True,
                    xml_declaration=True,
                    encoding="utf-8",
                )
            except Exception as ex:
                # read error
                syslog.error(f"Error saving device defaults: {ex}")
                return False

            return True


def extract_remap_actions(action_sets):
    """Returns a list of remap actions from a list of actions.

    :param action_sets set of actions from which to extract Remap actions
    :return list of Remap actions contained in the provided list of actions
    """
    remap_actions = []
    for actions in [a for a in action_sets if a is not None]:
        for action in actions:
            if hasattr(action, "name") and action.name in ("Remap", "Vjoy Remap"):
                remap_actions.append(action)
            # if isinstance(action, gremlin.action_plugins.remap.Remap):
            #     remap_actions.append(action)
    return remap_actions


class ProfileRegistry:
    """holds data about a profile in a central location for easier reference and to avoid duplication of object references in data structures"""

    def __init__(self, profile: Profile):
        assert isinstance(profile, Profile) or isinstance(profile, gremlin.profile_graph.ProfileRootNode), "invalid profile"
        self._profile = profile
        self._is_graph = isinstance(profile, gremlin.profile_graph.ProfileRootNode)
        # sync - this will populate entries from the profile to the registry

    def reset(self):
        """clear entries for a new profile"""
        pass

    def getInputIdKey(self, input_id) -> list:
        """gets an input id key from a given input id"""
        return gremlin.input_item.getInputIdKey(input_id)

    def getInputItem(
        self,
        device_guid: dinput.GUID | str,
        mode_name: str,
        input_type: InputType,
        input_id,
        override_input_type: InputType = None,
        custom_name_handler: Callable = None,
        custom_mode_name_handler: Callable = None,
        description: str = None,
        description_readonly: bool = None,
        tooltip: str = None,
        autocreate: bool = False,
        create_handler: Callable = None,
        created_handler: Callable = None,
    ):
        """
        Gets the input item - creates it if it does not exist

        :param device_guid: guid of the device (GUID or str)
        :param mode_name: mode to associate the input with
        :param input_type: type of input
        :param input_id: id of input
        :param custom_name_handler: optional handler for new inputs
        :param custom_mode_name_handler: optional handler for new inputs
        :param create_handler: optional handler called if the input should be created, returns an input_item, gets all the parameters except the create options
        :param created_handler: optional handler called when the input is created (if created)
        :param description: optional description
        :param description_readonly: flag to indicate if description can be user edite, passes the created input item (input_item) as the parameter
        :param tooltip: tooltip associated with the input item (on title bar) if the input is created
        :param create_handler: optional callback if the item does not exist, should return an input item.  Parameters passed are the same but without auto-create and the create handler
        """
        verbose = gremlin.config.Configuration().verbose_mode_inputitems
        device_guid = gremlin.util.parse_guid(device_guid)
        assert isinstance(device_guid, dinput.GUID), "invalid id"
        if input_type == InputType.ModeControl and input_id == gremlin.ui.mode_device.ModeInputModeType.ModeProfileStart:
            pass

        input_item = self._profile.getInputItem(device_guid=device_guid, mode_name=mode_name, input_type=input_type, input_id=input_id)

        # device node
        profile = self._profile
        device_node: ProfileDeviceNode = profile.getDeviceNode(device_guid, autocreate=True)
        assert device_node is not None, "device node not found in profile"

        if input_item is None and autocreate:
            # not found
            mode_node = device_node.getModeNode(mode_name, autocreate=True)
            assert mode_node is not None, "mode node not found in profile"
            assert mode_node.device_guid is not None, "mode node should have a device id"
            assert mode_name in device_node.modes, "mode not found in device modes"

            if create_handler:
                input_item = create_handler(
                    device_guid=device_guid, mode_name=mode_name, input_type=input_type, input_id=input_id, description=description, tooltip=tooltip
                )
                assert isinstance(input_item, InputItem), "invalid input item on custom callback"
                mode_config = mode_node.getConfig(input_item.input_type)
                assert mode_config is not None, f"failed to create mode config for mode [{input_type}]"
                mode_config[input_item.input_id] = input_item

            else:
                if not mode_node:
                    # create a mode
                    mode_node = self._profile.getModeNode(device_guid=device_guid, mode=mode_name, autocreate=True)
                    assert mode_node is not None, "mode node not found in profile"
                    assert mode_node.device_guid is not None, "mode node should have a device id"
                    device_node.modes[mode_name] = mode_node
                    mode_node.load(profile=self._profile, device_guid=device_node.device_guid, name=mode_name, inherit=True, parent=device_node)

                if mode_name not in device_node.modes:
                    device_node.modes[mode_name] = mode_node

                match input_type:
                    case InputType.State:
                        input_item = gremlin.ui.state_device.StateInputItem(key=input_id)

                    case InputType.Keyboard | InputType.KeyboardLatched:
                        input_item = gremlin.ui.keyboard_device.KeyboardInputItem(mode_node)
                        input_item.key = input_id
                        if custom_name_handler:
                            input_item.setInputNameHandler(custom_name_handler)

                    case InputType.OpenSoundControl:
                        input_item = gremlin.ui.osc_device.OscInputItem(mode_node)
                        if override_input_type:
                            input_item.setOverrideInputType(override_input_type)
                    case InputType.Midi:
                        input_item = gremlin.ui.midi_device.MidiInputItem(mode_node)
                        if override_input_type:
                            input_item.setOverrideInputType(override_input_type)

                    case InputType.ModeControl:
                        raise ValueError("mode control cannot be autocreated - use create handler")

                    case _:
                        input_item = InputItem(
                            mode_node=mode_node,
                            input_type = input_type,
                            input_id = input_id,
                            device_guid=device_guid,
                            override_input_type=override_input_type,
                            custom_name_handler=custom_name_handler,
                            custom_mode_name_handler=custom_mode_name_handler,
                        )
                        input_item.setSortCallback(self._handle_joystick_sort)

                input_item.setInputType(input_type)
                input_item.setInputId(input_id)
                if description is not None:
                    input_item.description = description
                if description_readonly is not None:
                    input_item.descriptionReadOnly = description_readonly
                if tooltip:
                    input_item.setTooltip(tooltip)

                self._profile.registerInputItem(input_item)

            if __debug__ and mode_node:
                config_map = mode_node._config
                assert input_item.input_type in config_map, "input type not found in mode configuration map"
                assert input_item.input_id in config_map[input_item.input_type], "input id not found in configuration map"
                assert input_item == config_map[input_item.input_type][input_item.input_id], "input item not found in configuration map"

            # run the callback
            if created_handler:
                created_handler(input_item)

        if verbose:
            syslog.info(f"REGISTRY GET INPUT ITEM [{input_item.display_name}] : register new input item:")
            syslog.info(f"\tid: {input_item.id}")
            syslog.info(f"\tinput mode: {input_item.profile_mode}")
            syslog.info(f"\tinput type: {input_item.input_type.name}")
            syslog.info(f"\tinput id: {str(input_item.input_id)}")

        return input_item

    def _handle_joystick_sort(self, input_item: InputItem):
        """gets the sort key for a joystick input item"""

        order = 0
        match input_item.input_type:
            case InputType.JoystickAxis:
                order = 1
            case InputType.JoystickButton:
                order = 2
            case InputType.JoystickHat:
                order = 3
            case _:
                return input_item.input_id

        return (order, input_item.input_id)

    def removeInputItem(self, input_item: InputItem):
        """removes a given input item from the registry"""
        self._profile.removeInputItem(input_item)

    def registerInputItem(self, input_item: InputItem, device_guid: dinput.GUID = None, input_type: InputType = None, input_id=None, overwrite=False):
        """registers an input item in the profile registry"""

        self._profile.registerInputItem(input_item, device_guid=device_guid, input_type=input_type, input_id=input_id)
        return input_item

    def loadInputItems(self, device_guid, mode: str):
        """loads the possible input items from the profile data into the registry"""
        pass

    def getInputItems(self, device_guid, mode_name, input_type: InputType | list[InputType] = None) -> list:
        """gets a list of all input items for a device and mode with optional filter on input type"""
        return self._profile.getInputItems(device_guid, mode_name, input_type)

    def dump(self):
        """dumps the profile content and registry contents"""

        syslog.info("Profile: input items dump:")
        profile = self._profile
        devices = profile.devices
        for device_guid in devices:
            device_node = self.devices[device_guid]
            for input_mode in device_node.modes:
                mode_node = device_node.modes[input_mode]
                for input_type in mode_node.config:
                    for input_id in mode_node.config[input_type]:
                        input_item = mode_node.config[input_type][input_id]
                        syslog.info(f"\t{input_item.display_name}")

    def sync(self):
        """synchronizes the input items in this registry with the profile devices"""
        pass


def get_mode_object(node, extra_data=None):  # -> Mode:
    """gets the mode object corresponding to a profile XML node

    :param node: lxml element to scan ancestors for, or a dictionary of parameters used to derive the mode object


    """

    if extra_data:
        if "mode_object" in extra_data:
            # object already stored
            return extra_data["mode_object"]
        if "mode" in extra_data and "device_guid" in extra_data and "device_type" in extra_data:
            # derive from compoments
            profile = gremlin.shared_state.current_profile
            device_guid = extra_data["device_guid"]
            device_type = extra_data["device_type"]

            mode = extra_data["mode"]

            device_modes = profile.get_device_modes(device_guid, device_type, DeviceType.to_string(device_type))
            mode_object = device_modes.ensure_mode_exists(mode)
            return mode_object

    if node is not None and isinstance(node, etree.Element):
        nodes = node.xpath("ancestor::state")
        if nodes:
            # state container
            device_guid = gremlin.shared_state.state_tab_guid
            device_type = DeviceType.State
            mode = gremlin.shared_state.master_mode
            profile = gremlin.shared_state.current_profile

            device_modes = profile.get_device_modes(device_guid, device_type, DeviceType.to_string(device_type))
            mode_object = device_modes.ensure_mode_exists(mode)
            return mode_object

        # xml node
        nodes = node.xpath("ancestor::mode")
        if not nodes:
            return None

        mode_node = nodes.pop()

        mode = safe_read(mode_node, "name", str, "")
        assert len(mode) > 0, "XML hierarchy error - parent mode not found"

        nodes = node.xpath("ancestor::device")

        if nodes:
            device_node = nodes.pop()
            device_id = safe_read(device_node, "device-guid", str, "")
            assert device_id, "XML hierarchy error - parent device not found"
            device_guid = gremlin.util.parse_guid(device_id)
            device_type = safe_read(device_node, "type", str, "")
            device_type = DeviceType.to_enum(device_type)

            profile: Profile = gremlin.shared_state.current_profile
            device_node = profile.getDeviceNode(device_guid, autocreate=True)
            mode_node = device_node.getModeNode(mode, autocreate=True)
            return mode_node

    return None


class ModeNode(anytree.NodeMixin):
    """mode tree node"""

    def __init__(self, name: str = None, mode_object=None, is_root=False):
        self.name = name
        self.mode_object = mode_object
        self.parent_name = None  # name of parent mode
        self.isModeRoot = is_root

    @property
    def parent_mode(self) -> str:
        """gets the parent mode name, None if none"""
        if self.parent and self.parent.name:
            return self.parent.name
        return None


class ActionTreeNode(anytree.NodeMixin):
    """holds an action tree node for the getActionTree() member function in Profile"""

    def __init__(self, name: str = None, data=None, tagdata=None):
        self.name = name
        self.data = data
        self.tagdata = None


class Profile:
    """Stores the contents of an entire configuration profile.

    This includes configurations for each device's modes.
    """

    def __init__(self, parent=None):
        """Constructor creating a new instance."""

        self.__sub_init__(parent)

    def __sub_init__(self, parent):
        import gremlin.ui.state_device

        self.id = get_guid()
        self._mode_tree = None  # holds the mode tree (anytree, m73 and later) - this holds the profile's mode hiarchy
        self.devices = TriggerDict(name="profile devices")  # holds devices for this profile keyed by guid -> Device
        self.devices.addCallback(self._handle_device_node_changed)
        self.vjoy_devices = {}
        self.merge_axes = []
        self.plugins = []
        self._profile_fname = None  # the file name of this profile (xml)
        self.settings = Settings(self)
        self.parent = parent

        self._profile_config_fname = None  # the configuration file name of this profile (json)
        self._profile_name = None  # the friendly name of this profile
        self._start_mode = "Default"  # startup mode for this profile (this will be either the default mode, or the last used mode)
        self._default_start_mode = "Default"  # default startup mode for this profile
        self._last_runtime_mode = "Default"  # last active mode
        self._last_edit_mode = "Default"
        self._restore_last_mode = False  # True if the profile should start with the last active mode (profile specific)
        self._dirty = False  # dirty flag - indicates the profile data was changed but not saved yet
        self._profile_data: Profile
        self._force_numlock_off = True  # if set, forces numlock to be off if it isn't so numpad keys report the correct scan codes
        self._force_numlock_on = False  # if set, forces numlock ON.  If a conflict, _force_numlock_off takes precedence.
        self._simconnect_modes = {}  # map of simconnect startup modes to aicraft - the key is the SimconnectAicraftDefinition key which is unique per aicraft that can be loaded by MSFS
        self._substitution_map = {}  # map of device GUID to any new device GUID for the load process
        self._profile_graph = gremlin.profile_graph.ProfileGraph()
        self._loaded = False
        self.state = gremlin.ui.state_device.StateData()
        self.state.clear()
        self._start_state = {}  # profile startup output state - index by [device_id (str)][buttons/axis (str)][id (int)] = value (float or bool)
        self._removed_devices = []  # list of removed devices from the profile, list of device_id (str)
        self._save_config_enabled = False  # true if profile config saving is enabled
        self._config_data_read = False
        self._config_data = {}

        self.override_start_mode = None  # override mode for profile startup if any (not persisted)
        el = gremlin.event_handler.EventListener()
        el.edit_mode_changed.connect(self._edit_mode_changed_cb)
        el.shutdown.connect(self._shutdown_handler)

        self._profile_registry = ProfileRegistry(self)
        self._joystick_inputs_loaded = {}  # map of [device_guid] to flag to indicate if all base inputs were loaded for this joystick device

        self.initialize_regular_devices()  # non joystick devices
        gremlin.ui.mode_device.ensureMasterInputItems(self)
        gremlin.ui.mode_device.ensureModeInputItems(self, "Default")

    def getProfileKey(self):
        """ unique key for this profile """
        self


    def _shutdown_handler(self):
        """handles shutdown events"""
        # ensure the profile config data is persisted
        config = gremlin.config.Configuration()
        config.save_profile()

    def _handle_device_node_changed(self, data_map, key, old_value: ProfileDeviceNode, new_value: ProfileDeviceNode):
        # def stub(node: ProfileDeviceNode) -> str:
        #     if node:
        #         return f"name: {node.name} id: {node.id} guid: {gremlin.util.normalize_guid(node.device_guid)}"
        #     return "n/a"

        # syslog.info(f"device map: key: [{key}] old value: [{stub(old_value)}] new value: [{stub(new_value)}]")
        pass

    @property
    def registry(self) -> ProfileRegistry:
        return self._profile_registry

    def __getstate__(self):
        """serialization override"""
        state = {}
        state["xml"] = self.to_xml()  # serialize to XML

        return state

    def __setstate__(self, state):
        """serialization override"""
        self.__sub_init__(None)
        xml = state["xml"]
        # write the xml to a temporary file in case it has to be converted formats
        tmp = gremlin.util.getTemporaryFile("xml")
        with open(tmp, "wb") as f:
            f.write(xml)

        self.from_xml(tmp)
        self._profile_fname = None
        os.unlink(tmp)

    def sync(self):
        """sync the profile with the profile registry"""
        self.registry.sync()

    def getInputIdKey(self, input_id) -> list:
        """gets an input id key from a given input id"""
        return gremlin.input_item.getInputIdKey(input_id)

    def registerInputItem(
        self,
        input_item: InputItem,
        device_guid: dinput.GUID = None,
        input_type: InputType = None,
        input_id=None,
        autocreate=False,
    ):
        """sets a profile model data"""
        assert isinstance(input_item, InputItem), "invalid input item"
        device_guid = input_item.device_guid if device_guid is None else device_guid
        assert isinstance(device_guid, dinput.GUID), "invalid device id"
        input_type = input_item.input_type if input_type is None else input_type
        input_id = input_item.input_id if input_id is None else input_id
        device = gremlin.joystick_handling.getDevice(device_guid)

        verbose = gremlin.config.Configuration().verbose_mode_ui
        mode_name = input_item.profile_mode
        mode_node = self.getModeNode(device_guid, mode_name, autocreate=True)

        if input_type not in mode_node._config:
            mode_node._config[input_type] = {}

        input_id_key = self.getInputIdKey(input_id)
        mode_node._config[input_type][input_id_key] = input_item
        if verbose:
            syslog.info(f"Profile: registered input: mode [{mode_name}] [{device.name}] [{input_item.display_name}]")

    def getInputItem(self, device_guid, mode_name: str, input_type: InputType, input_id):
        """gets an input item from the profile model data"""

        device = gremlin.joystick_handling.getDevice(device_guid)
        if device.disabled:
            # ignore joysticks that are disabled
            return None

        device_node = self.getDeviceNode(device_guid)
        if device_node:
            mode_node = device_node.getModeNode(mode_name)
            if mode_node:
                input_item = mode_node.getInputItem(input_type, input_id)
                return input_item
        return None

    def setFilterDefaults(self, device_guid: dinput.GUID, force=False):
        """sets default device inputs"""
        self.settings.setFilterDefaults(device_guid, force)

    def ensureInputItems(self, device_guid: dinput.GUID, force=False):
        """ensures input items are setup for joysticks"""
        assert isinstance(device_guid, dinput.GUID), "invalid device id format"

        device = gremlin.joystick_handling.getDevice(device_guid)
        if device.disabled:
            # ignore joysticks that are disabled
            return

        if device.device_type in (DeviceType.Maestro, DeviceType.Joystick, DeviceType.VJoy):
            # ensure all inputs are defined for joysticks
            loaded = device_guid in self._joystick_inputs_loaded and self._joystick_inputs_loaded[device_guid]
            if force or not loaded:
                profile_modes = self.get_modes()
                if device_guid not in self.devices:
                    device_node = ProfileDeviceNode(self)
                    device_node.device_guid = device_guid
                    device_node.name = device.name
                    self.devices[device_guid] = device_node
                else:
                    device_node = self.devices[device_guid]

                for input_mode in profile_modes:
                    if input_mode not in device_node.modes:
                        mode_node = ProfileModeNode(device_node)
                        mode_node.name = input_mode
                        device_node.modes[input_mode] = mode_node
                    else:
                        mode_node = device_node.modes[input_mode]

                        input_type_list = (InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat)
                        for input_type in input_type_list:
                            if input_type not in mode_node.config:
                                mode_node.config[input_type] = {}

                            input_id_list = None
                            match input_type:
                                case InputType.JoystickAxis:
                                    input_id_list = device.getAxisInputIdList()
                                case InputType.JoystickHat:
                                    input_id_list = range(1, device.hat_count + 1)
                                case InputType.JoystickButton:
                                    input_id_list = range(1, device.button_count + 1)

                            if input_id_list:
                                for input_id in input_id_list:
                                    if input_id not in mode_node.config[input_type]:
                                        mode_node.config[input_type][input_id] = None  # delay load but define the input id

                # mark loaded
                self._joystick_inputs_loaded[device_guid] = True

    def getInputItems(self, device_guid: dinput.GUID, mode: str, input_type: InputType | list[InputType] | tuple[InputType]) -> list:
        """gets input items of a specific type"""
        devices = self.devices
        device = gremlin.joystick_handling.getDevice(device_guid)
        if device.disabled:
            # ignore joysticks that are disabled
            return []
        input_type_list = input_type if hasattr(input_type, "__iter__") else [input_type]

        # ensure all inputs are defined for joysticks
        self.ensureInputItems(device_guid)

        input_list = []
        if device_guid in devices:
            device_node = devices[device_guid]
            if mode in device_node.modes:
                mode_node = device_node.modes[mode]
                for input_type in input_type_list:
                    if input_type in mode_node.config:
                        for input_id in mode_node.config[input_type]:
                            input_item = mode_node.config[input_type][input_id]
                            if not input_item:
                                # create delay loaded inputs
                                match input_type:
                                    case InputType.State:
                                        input_item = gremlin.ui.state_device.StateInputItem()
                                    case InputType.Keyboard | InputType.KeyboardLatched:
                                        input_item = gremlin.ui.keyboard_device.KeyboardInputItem(self)
                                    case InputType.OpenSoundControl:
                                        input_item = gremlin.ui.osc_device.OscInputItem(self)
                                    case InputType.Midi:
                                        input_item = gremlin.ui.midi_device.MidiInputItem(self)
                                    case InputType.JoystickAxis | InputType.JoystickButton | InputType.JoystickHat:
                                        input_item = InputItem(mode_node=mode_node, input_type=input_type)
                                    case InputType.ModeControl:
                                        input_item = gremlin.ui.mode_device.ModeInputItem(self)
                                    case _:
                                        raise ValueError(f"don't know how to handle input type: [{input_type}]")

                                input_item.setInputId(input_id)
                                mode_node.config[input_type][input_id] = input_item
                            input_list.append(input_item)
        return input_list

    def removeInputItem(self, input_item: InputItem):
        """removes an input item from the profile"""
        assert isinstance(input_item, InputItem), "invalid input item"
        device_guid = input_item.device_guid
        assert isinstance(device_guid, dinput.GUID), "invalid device id"
        input_type = input_item.input_type
        input_id = input_item.input_id
        input_mode = input_item.profile_mode
        verbose = gremlin.config.Configuration().verbose_mode_ui

        devices = self.devices
        if device_guid in devices:
            device_node = self.devices[device_guid]
            if input_mode in device_node.modes:
                mode_node = device_node.modes[input_mode]
                if input_type in mode_node.config:
                    if input_id in mode_node.config[input_type]:
                        if mode_node.config[input_type][input_id] == input_item:
                            del mode_node.config[input_type][input_id]
                            if verbose:
                                syslog.info(f"Profile: remove input item: {input_item.display_name}")
                            return

        if verbose:
            syslog.warning(f"Profile: warning: input item: {input_item.display_name} not found in profile")

    def unload(self):
        """unloads the current profile - clears all references and unhooks events"""
        el = gremlin.event_handler.EventListener()
        el.edit_mode_changed.disconnect(self._edit_mode_changed_cb)
        self.devices: dict[ProfileDeviceNode] = {}  # holds devices attached to this profile
        self.vjoy_devices = {}
        self.merge_axes = []
        self.plugins = []
        self._simconnect_modes = {}  # map of simconnect startup modes to aicraft - the key is the SimconnectAicraftDefinition key which is unique per aicraft that can be loaded by MSFS
        self._substitution_map = {}  # map of device GUID to any new device GUID for the load process
        self._profile_graph = None
        self.state.clear()
        self._loaded = False
        self.settings.reset()  # reset settings

    @property
    def loaded(self) -> bool:
        """true if the profile loaded ok"""
        return self._loaded

    def setLoaded(self, value: bool):
        """marks the profile as loaded"""
        self._loaded = value

    @property
    def graph(self) -> gremlin.profile_graph.ProfileGraph:
        """gets the current profile graph"""
        return self._profile_graph

    def _evaluate_hash(self, obj, path):
        print(path)
        return False

    def getMappingHash(self):
        """gets the hash value of the device mapping"""
        xml = self.to_xml()
        return hash(xml)

    # startup state
    def getStartButtonState(self, device_id: str, id: int) -> bool:
        """returns the startup button state for that device/button"""
        if device_id in self._start_state:
            if "buttons" in self._start_state[device_id]:
                if id in self._start_state[device_id]["buttons"]:
                    return self._start_state[device_id]["buttons"][id]
        return False

    def setStartButtonState(self, device_id: str, id: int, state: bool):
        if device_id not in self._start_state:
            self._start_state[device_id] = {}
        if "buttons" not in self._start_state[device_id]:
            self._start_state[device_id]["buttons"] = {}
        self._start_state[device_id]["buttons"][id] = state

    def getStartAxisValue(self, device_id: str, id: int) -> float:
        """returns the startup axis value for that device/axis, returns None if not set"""
        if device_id in self._start_state:
            verbose = gremlin.config.Configuration().verbose_mode_output
            if "axis" in self._start_state[device_id]:
                if id in self._start_state[device_id]["axis"]:
                    value = self._start_state[device_id]["axis"][id]
                    if verbose:
                        device = gremlin.joystick_handling.get_device(device_id)
                        syslog.info(f"Default axis value GET: vjoy: {device.vjoy_id} axis: {id} value: {value:0.3f}")
                    return value

        return None

    def setStartAxisValue(self, device_id: str, id: int, value: float):
        """sets a start value for a given vjoy device / id"""
        if device_id not in self._start_state:
            self._start_state[device_id] = {}
        if "axis" not in self._start_state[device_id]:
            self._start_state[device_id]["axis"] = {}
        self._start_state[device_id]["axis"][id] = value
        verbose = gremlin.config.Configuration().verbose_mode_output
        if verbose:
            device = gremlin.joystick_handling.get_device(device_id)
            syslog.info(f"Default axis value: vjoy SET: {device.vjoy_id} axis: {id} value: {value:0.3f}")

    def getStartAxisEnabled(self, device_id: str, id: int) -> bool:
        """returns the startup axis value for that device/axis is enabled  returns None if not set"""
        if device_id in self._start_state:
            verbose = gremlin.config.Configuration().verbose_mode_output
            if "enabled" in self._start_state[device_id]:
                if id in self._start_state[device_id]["enabled"]:
                    enabled = self._start_state[device_id]["enabled"][id]
                    if verbose:
                        device = gremlin.joystick_handling.get_device(device_id)
                        syslog.info(f"Default axis value enabled GET: vjoy: {device.vjoy_id} axis: {id} value: {enabled}")
                    return enabled
        return None

    def setStartAxisEnabled(self, device_id: str, id: int, enabled: bool):
        """sets a start value enabled flag for a given vjoy device / id"""
        if device_id not in self._start_state:
            self._start_state[device_id] = {}
        if "enabled" not in self._start_state[device_id]:
            self._start_state[device_id]["enabled"] = {}
        verbose = gremlin.config.Configuration().verbose_mode_output
        if verbose:
            device = gremlin.joystick_handling.get_device(device_id)
            syslog.info(f"Default axis value enabled SET: vjoy: {device.vjoy_id} axis: {id} value: {enabled}")
        self._start_state[device_id]["enabled"][id] = enabled

    def setDefaultAudioDevice(self, name):
        """sets the default audio device for all play actions"""

        def _apply_default_sound(action, extra_data: dict = None) -> bool:
            action.audio_device = name
            return True

        self.filter_actions("play-sound", _apply_default_sound)

    def setSimconnectMode(self, key, mode):
        """sets the simconnect startup mode for a given aicraft key - the key comes from the SimconnectAicraftDefinition for the aircraft"""
        # key is  (item.id, item.mode)
        # assert len(key) == 2
        # key_ap, key_cp = key
        # assert key_ap,"Invalid AP key"
        # assert key_cp,"Invalid CP key"
        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        if verbose:
            syslog.info(f"Profile: SimConnectMode: associating [{key}] with profile mode [{mode}]")

        if not isinstance(key, tuple):
            key = key.casefold()
            key = (key, key)  # make it a tuple
        else:
            a, b = key
            key = (a.casefold(), b.casefold())

        self._simconnect_modes[key] = mode

    def hasSimconnectMode(self, key) -> bool:
        """true if the profile has a simconnect mapping for this key"""
        if isinstance(key, tuple):
            return key in self._simconnect_modes
        # single key mode
        key = key.casefold()
        keys = [k.casefold() for (_, k) in self._simconnect_modes]
        return key in keys

    def getSimconnectMode(self, key):
        """gets the simconnect startup mode for a given aicraft key - the key comes from the SimconnectAicraftDefinition for the aircraft"""
        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        if not isinstance(key, tuple):
            key = key.casefold()
            key = (key, key)
        if key in self._simconnect_modes:
            mode = self._simconnect_modes[key]
            if verbose:
                syslog.info(f"Profile: SimConnectMode: found [{key}] with profile mode [{mode}]")
            return mode
        if verbose:
            syslog.info(f"Profile: SimConnectMode: no saved mode found for [{key}]")
        return None

    def _edit_mode_changed_cb(self):
        """available mode list has changed - check data"""

        # remove any merged axis data using a missing mode
        modes = self.get_modes()
        valid_list = []
        for entry in self.merge_axes:
            if entry["mode"] in modes:
                valid_list.append(entry)
        self.merge_axes = valid_list

        # update vjoy device list
        remove_list = []
        for device in self.vjoy_devices.values():
            for mode in device.modes:
                if mode not in modes:
                    remove_list.append(mode)

            for mode in remove_list:
                if mode in device.modes:
                    del device.modes[mode]

        # check default startup mode
        mode = self._default_start_mode
        if mode not in modes:
            self._default_start_mode = self.get_default_mode()

    def getDeviceLabel(self, device_guid):
        """gets the display label for a given device guid"""
        if device_guid in self.devices:
            return self.devices[device_guid].name
        return None

    def setDeviceLabel(self, device_guid, name):
        """sets the display label for a given device guid"""
        if device_guid in self.devices:
            self.devices[device_guid].name = name
            return True
        return False

    @property
    def dirty(self):
        return self._dirty

    @property
    def name(self):
        return self._profile_name

    def get_ordered_device_list(self) -> list[ProfileDeviceNode]:
        """gets the devices ordered by the current UI order"""

        if gremlin.shared_state.ui is not None:
            id_list = gremlin.shared_state.ui.get_ordered_device_guid_list()
        else:
            id_list = [device.device_guid for device in self.devices.values()]
        device_list = []
        for id in id_list:
            if id in self.devices:
                device_list.append(self.devices[id])
        return device_list

    def ensure_mode_exists(self, mode_name: str, is_system=False):
        """ensures a mode exists in the profile"""
        for device_guid in self.devices:
            _ = self.getModeNode(device_guid, mode=mode_name, is_system=is_system, autocreate=True)

    def initialize_joystick_device(self, device, modes):
        """Ensures a joystick is properly initialized in the profile.

        :param device the device to initialize
        :param modes the list of modes to be present
        """
        new_device = ProfileDeviceNode(self)
        new_device.device = device
        self.devices[device.device_guid] = new_device

        for mode in modes:
            new_device.ensure_mode_exists(mode_name=mode)

    def initialize_regular_devices(self):
        """setup suported non joystick devices"""

        # Keyboard
        device_guid = gremlin.shared_state.keyboard_tab_guid
        device_type = DeviceType.Keyboard
        new_device = ProfileDeviceNode(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        self.devices[device_guid] = new_device

        # MIDI
        device_guid = gremlin.shared_state.midi_tab_guid
        device_type = DeviceType.Midi
        new_device = ProfileDeviceNode(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        self.devices[device_guid] = new_device

        # OSC
        device_guid = gremlin.shared_state.osc_tab_guid
        device_type = DeviceType.Osc
        new_device = ProfileDeviceNode(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        self.devices[device_guid] = new_device

        # mode control
        device_guid = gremlin.shared_state.mode_tab_guid
        device_type = DeviceType.ModeControl
        new_device = ProfileDeviceNode(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        self.devices[device_guid] = new_device

        # state data
        self.state = gremlin.ui.state_device.StateData()
        device_guid = gremlin.shared_state.state_tab_guid
        device_type = DeviceType.State
        new_device = ProfileDeviceNode(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        self.devices[device_guid] = new_device

    def modeTree(self) -> Node:
        """returns an anytree node - nodes contain the name of the mode"""
        self._ensure_mode_tree()
        return self._mode_tree

    def _inheritance_tree_to_labels(self, labels, tree, level):
        """Generates labels to use in the dropdown menu indicating inheritance.

        :param labels the list containing all the labels
        :param tree the part of the tree to be processed
        :param level the indentation level of this tree
        """
        # skip the root node
        show_parent = gremlin.config.Configuration().show_parent_mode
        for child in tree.children:
            for pre, fill, node in anytree.RenderTree(child, style=anytree.ContStyle()):  # style=gremlin.ui.ui_common.ModeStyle()):
                #'└''─'
                # pre = '' if node.parent.is_root else '└'
                # fill = '─' * (node.depth-1)
                if node.parent.name and show_parent:
                    labels.append((node.name, f"{pre} {node.name} (↑{node.parent.name})"))
                else:
                    labels.append((node.name, f"{pre} {node.name}"))

    def get_mode_display_list(self) -> list:
        """gets a pairs (display_name, mode)"""

        mode_list = []

        hide_default_mode = gremlin.config.Configuration().hide_default_mode
        if hide_default_mode:
            mode_objects = self.get_mode_objects("Default")
            root_modes = self.get_root_modes()
            master_mode = gremlin.shared_state.master_mode
            if master_mode in root_modes:
                root_modes.remove(master_mode)
            if len(root_modes) == 1:
                # only one root mode
                hide_default_mode = False
            else:
                # more than one root mode exists
                for mode_object in mode_objects:
                    if mode_object.is_root and mode_object.hasMappings:
                        hide_default_mode = False  # don't hide because it has mappings
                        break

        # Create mode name labels visualizing the tree structure
        inheritance_tree = self.build_inheritance_tree()
        labels = []

        self._inheritance_tree_to_labels(labels, inheritance_tree, 0)

        # Filter the mode names such that they only occur once below
        # their correct parent
        mode_names = [n[0] for n in labels]
        display_names = [n[1] for n in labels]

        # Add properly arranged mode names to the drop down list
        master_mode = gremlin.shared_state.master_mode
        for display_name, mode_name in zip(display_names, mode_names):
            if hide_default_mode and mode_name == "Default":
                continue
            if mode_name == master_mode:
                continue  # special mode
            mode_list.append((display_name, mode_name))

        return mode_list

    def _ensure_mode_tree(self, reset: bool = False):

        if not self._mode_tree or reset:
            self._mode_tree = ModeNode(is_root=True)  # root node

            # read from the profile configuration
            mode_map = {}
            if self._loaded:
                for device in self.devices.values():
                    for mode_name in device.modes:
                        mode_node = device.modes[mode_name]
                        if mode_name not in mode_map:
                            node = ModeNode(mode_name)
                            parent_name = mode_node.inherit
                            node.parent = mode_map[parent_name] if parent_name in mode_map else self._mode_tree

            # add default mode
            if "Default" not in mode_map:
                self.add_mode("Default", emit=False, validate=False)

            # add master mode
            master_mode = gremlin.shared_state.master_mode
            if master_mode not in mode_map:
                self.add_mode(master_mode, emit=False, validate=False)

    def dumpModeTree(self, tabs=""):
        """dumps the current mode tree"""
        syslog.info("PROFILE MODES:")
        for pre, _, node in anytree.RenderTree(self._mode_tree, style=anytree.AsciiStyle()):
            syslog.info(f"{tabs}{pre}{gremlin.shared_state.translateMode(node.name) if node.name else '[Profile Root]'}")

    def build_inheritance_tree(self, as_tree=False):
        """returns the mode tree (new in m73)"""
        self._ensure_mode_tree()
        return self._mode_tree

    def getModeTree(self):
        """gets the current mode tree as an anytree root"""
        self.build_inheritance_tree()

    def getModeHierarchy(self, mode: str):
        """gets the mode hierarchy for a given mode"""
        self._ensure_mode_tree()
        if mode:
            node = anytree.find(self._mode_tree, lambda node: self._compare_mode(node, mode))
            if node:
                mode_list = [node.name]
                mode_list.extend([n.name for n in node.ancestors if n.name])
                return mode_list
        return []

    def getModeDescendants(self, mode: str):
        """gets the list of modes that are descendants to the specified mode"""
        self._ensure_mode_tree()
        if mode:
            node = anytree.find(self._mode_tree, lambda node: self._compare_mode(node, mode))
            if node:
                mode_list = [node.name]
                mode_list.extend([n.name for n in node.descendants if n.name])
                return mode_list
        return []

    def traverse_mode(self):
        """returns the current mode list as a list of (level, mode)"""
        # self.dumpModeTree()
        nodes = [(node.depth - 1, node.name) for node in anytree.PreOrderIter(self._mode_tree) if node.name]
        return nodes

    def mode_map(self):
        """converts the mode tree to a map [mode] = [children modes]"""
        data = {}
        for node in anytree.PreOrderIter(self._mode_tree):
            if node.name:
                data[node.name] = [n.name for n in node.children]
        return data

    def get_root_mode(self):
        """gets the top mode from a profile - that would be the default startup mode - sorted by name of the root nodes"""

        if self._mode_tree:
            return next((node.name for node in self._mode_tree.children), None)
        return None

    def get_mode_ancestors(self, mode: str, include_self=False):
        """gets a list of parent modes starting with the current mode"""
        node = anytree.find(self._mode_tree, lambda node: node.name == mode)
        if node is None:
            return []
        mode_list = [node.name] if include_self else []
        mode_list.extend([n.name for n in node.ancestors if n.name])
        return mode_list

    def get_mode_descendants(self, mode: str, include_self=False):
        """gets a list of child modes starting with the current mode"""
        node = anytree.find(self._mode_tree, lambda node: node.name == mode)
        if node is None:
            return []
        mode_list = [node.name] if include_self else []
        mode_list.extend([n.name for n in node.descendants if n.name])
        return mode_list

    def set_last_runtime_mode(self, mode: str):
        """sets the last used mode - this is persisted in the configuration"""
        if mode != self._last_runtime_mode:
            self._last_runtime_mode = mode
            config = gremlin.config.Configuration()
            self._last_runtime_mode = mode
            config.set_last_runtime_mode(self._profile_fname, mode)
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                syslog.info(f"PROFILE: [{self._profile_name}] store last runtime mode: [{mode}]")

    def get_last_runtime_mode(self):
        """gets the last used mode"""
        config = gremlin.config.Configuration()
        mode = config.get_profile_last_runtime_mode()
        if mode is not None:
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                syslog.info(f"PROFILE: [{self._profile_name}] get last runtime mode: [{mode}]")
            self._last_runtime_mode = mode
        return self._last_runtime_mode

    def set_last_edit_mode(self, mode):
        """sets the last used mode - this is persisted in the configuration"""
        if mode != self._last_edit_mode:
            self._last_edit_mode = mode
            config = gremlin.config.Configuration()
            self._last_edit_mode = mode
            config.set_profile_last_edit_mode(mode)
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                syslog.info(f"PROFILE: [{self._profile_name}] store last edit mode: [{mode}]")

    def get_last_edit_mode(self):
        """gets the last used mode"""
        if self._last_edit_mode is None:
            config = gremlin.config.Configuration()
            mode = config.get_profile_last_edit_mode()
            if mode is not None:
                verbose = gremlin.config.Configuration().verbose
                if verbose:
                    syslog.info(f"PROFILE: [{self._profile_name}] get last edit mode: [{mode}]")
                    self._last_edit_mode = mode
        return self._last_edit_mode

    def get_force_numlock(self) -> bool:
        return self._force_numlock_off

    def set_force_numlock(self, value: bool):
        self._force_numlock_off = value

    def get_force_numlock_on(self) -> bool:
        return self._force_numlock_on

    def set_force_numlock_on(self, value: bool):
        self._force_numlock_on = value

    def mode_list(self):
        """Returns a list of all modes based on the given node.

        :param node a node from a profile tree
        :return list of mode names
        """

        if self._mode_tree:
            modes = self.get_modes()
            return modes
        return []

    def add_mode(self, name, parent_name=None, emit=True, validate=True) -> bool:
        """adds a new mode parented to inherited_name

        :param name: the name of the mode to add (case sensitive)
        :param parent_name: the name of the parent mode, can be none if the mode is a root mode
        :param emit: if set, fires an event that updates the UI
        :returns: True on


        """
        if not name:
            return False

        name = name.strip()
        if name in self.mode_list():
            if validate:
                syslog.warning(f"Add Mode: error: mode {name} already exists")
                QMessageBox.warning(
                    self,
                    title="Warning",
                    text=f"Cannot add mode [{name}]: a mode by that name already exists",
                )
            return False

        device_node: ProfileDeviceNode

        for device_node in self.devices.values():
            # autocreate = device_node.device_type != DeviceType.ModeControl
            new_mode = device_node.getModeNode(name, autocreate=True)
            assert new_mode is not None, f"Failed to create or retrieve mode {name}"
            if parent_name is not None:
                new_mode.inherit = parent_name
            else:
                new_mode.inherit = None  # self.get_default_mode() # make this a root mode

        if self._mode_tree:
            # add the mode
            node = ModeNode(name)
            parent_node = self._mode_tree
            if parent_name:
                existing_parent_node = next(
                    (node for node in self._mode_tree.descendants if node.name == parent_name),
                    None,
                )
                if existing_parent_node:
                    parent_node = existing_parent_node

            node.parent = parent_node

        if emit:
            import gremlin.event_handler

            eh = gremlin.event_handler.EventListener()
            eh.edit_mode_changed.emit(name)
        return True

    def set_mode_parent(self, name, inherited_name, emit=True) -> bool:
        """sets the parent of a current mode"""

        root = self._mode_tree

        node = anytree.find(root, lambda node: node.name == name)
        if node is None:
            return

        if inherited_name == "None":
            inherited_name = None

        node_parent = anytree.find(self._mode_tree, lambda node: node.name == inherited_name)

        if node_parent is None:
            node_parent = root

        node.parent = node_parent

        mode_list = self.mode_list()
        if name in mode_list and (inherited_name is None or inherited_name in mode_list):
            for device in self.devices.values():
                if name in device.modes:
                    device.modes[name].inherit = inherited_name
        if emit:
            eh = gremlin.event_handler.EventListener()
            eh.edit_mode_changed.emit(name)
        return True

    def mode_tree(self, as_tree=False):
        """gets the parent/child hiearchy of modes - returns a map or an anytree"""
        if as_tree and self._mode_tree:
            return self._mode_tree
        return self.build_inheritance_tree(as_tree)

    def isRemovedDevice(self, id):
        """true if a device was removed by the user and should not be displayed"""
        id = gremlin.util.normalize_guid(id)
        return id in self._removed_devices

    def removedDeviceMap(self) -> dict:
        """returns the list of devices removed"""
        result = {}
        for id in self._removed_devices:
            device = gremlin.joystick_handling.getDevice(id)
            result[id] = device

        return result

    def setDeviceRemoved(self, id, removed: bool):
        """marks a profile device removed or not"""
        if removed and id not in self._removed_devices:
            self._removed_devices.append(id)
        elif not removed and id in self._removed_devices:
            self._removed_devices.remove(id)

    def hasMapping(self, device_guid, any_mode=False) -> bool:
        """true if the device has mappings"""
        if isinstance(device_guid, str):
            device_guid = gremlin.util.parse_guid(device_guid)
        profile = self  # gremlin.shared_state.current_profile
        edit_mode = gremlin.shared_state.edit_mode
        devices = profile.devices
        look_for_containers = True
        # special devices
        if device_guid == gremlin.shared_state.state_tab_guid:
            # state
            sd = gremlin.ui.state_device.StateData()
            names = sd.getStateNames()
            return len(names) > 0
        elif device_guid == gremlin.shared_state.settings_tab_guid:
            return True
        elif device_guid == gremlin.shared_state.plugins_tab_guid:
            # plugins
            plugins = gremlin.shared_state.current_profile.plugins
            return len(plugins) > 0
        elif device_guid == gremlin.shared_state.keyboard_tab_guid:
            look_for_containers = False

        if device_guid in devices:
            device_data = devices[device_guid]
            mode_list = [mode for mode in device_data.modes] if any_mode else ([edit_mode] if edit_mode in device_data.modes else [])
            for mode_name in mode_list:
                mode_data = device_data.modes[mode_name]
                for input_type, input_items in mode_data.config.items():
                    for input_item in input_items.values():
                        if look_for_containers:
                            if input_item.containers:
                                return True
                        else:
                            # input count indicates content
                            return True
        return False

    def remove_device(self, device: dinput.DeviceSummary):
        """removes the specified device from the profile"""

        if device.device_type not in (DeviceType.Maestro, DeviceType.Joystick, DeviceType.VJoy):
            syslog.error(f"PROFILE: cannot remove non-joystick/maestro device: {device.name}")
            return

        if device.device_id not in self._removed_devices:
            self._removed_devices.append(device.device_id)

        ec = gremlin.execution_graph.ExecutionContext()
        ec.reset(True)  # reset and rebuild data around the profile

        el = gremlin.event_handler.EventListener()
        el.request_reload.emit()

    def remove_mode(self, name, force=False, emit=True):
        """removes a mode from this profile"""

        import gremlin.event_handler

        mode_list = self.mode_list()
        if name not in self.mode_list():
            syslog.warning(f"Remove Mode: error: mode {name} not found")
            return False

        if not force and len(mode_list) == 1:
            QMessageBox.warning(
                self,
                title="Warning",
                text=f"Cannot delete mode [{name}]: The profile must have at least one mode",
            )
            return False

        parent_of_deleted = None
        for mode in list(self.devices.values())[0].modes.values():
            if mode.name == name:
                parent_of_deleted = mode.inherit

        # Assign the inherited mode of the the deleted one to all modes that
        # inherit from the mode to be deleted
        for device in self.devices.values():
            for mode in device.modes.values():
                if mode.inherit == name:
                    mode.inherit = parent_of_deleted

        # Remove the mode from the profile
        for device in self.devices.values():
            del device.modes[name]

        if self._mode_tree:
            node = next(
                (node for node in self._mode_tree.descendants if node.name == name),
                None,
            )
            if node:
                # reparent children
                for child in node.children:
                    child.parent = node.parent
                node.parent = None  # delete the node

        if emit:
            eh = gremlin.event_handler.EventListener()
            eh.edit_mode_changed.emit()

        return True

    def get_root_modes(self) -> list[str]:
        """Returns a list of root modes.

        :return list of root modes
        """
        if self._mode_tree:
            root_modes = [node.name for node in self._mode_tree.children]
            return root_modes

        root_modes = []
        for device in self.devices.values():
            if device.type != DeviceType.Keyboard:
                continue
            for mode_name, mode in device.modes.items():
                if mode.inherit is None:
                    root_modes.append(mode_name)
        return list(set(root_modes))  # unduplicated

    def modeExists(self, mode: str, force=True) -> bool:
        """true if the profile mode exists"""
        mode_list = self.get_modes()
        if mode not in mode_list:
            # force a data reload if mode not found
            self._ensure_mode_tree(True)
            return mode_list in self.get_modes()
        return True

    def get_modes(self, casefold=False) -> list[str]:
        """get all profile mode names as a list"""

        self._ensure_mode_tree()

        master_mode = gremlin.shared_state.master_mode

        if casefold:
            modes = [node.name.casefold() for node in self._mode_tree.descendants if node.name != master_mode]
        else:
            modes = [node.name for node in self._mode_tree.descendants if node.name != master_mode]

        if not modes:
            modes = ["Default"]
            self._mode_tree = Node("")
            default_node = Node("Default")
            default_node.parent = self._mode_tree

        return modes  # unduplicated

    def get_xml_modes(self, node, casefold=False) -> list[str]:
        """reads profile modes from an XML mode"""
        root = node.getroottree().getroot()
        mode_nodes = root.xpath("./modes/mode")
        if mode_nodes is not None:
            if casefold:
                mode_list = [gremlin.shared_state.translateMode(child.get("name")).casefold() for child in mode_nodes if child is not None]
            else:
                mode_list = [gremlin.shared_state.translateMode(child.get("name")) for child in mode_nodes if child is not None]
            return mode_list
        return []

    def get_mode_object(self, mode_name):
        """gets the mode object for the specified mode"""
        if mode_name:
            o_list = self.get_mode_objects(mode_name)
            if o_list:
                return o_list.pop()
        return None

    def get_mode_objects(self, mode_name=None):  # -> list[Mode]:
        """gets the mode objects in the device list"""
        modes = []
        for device in self.devices.values():
            for mode in device.modes.values():
                if mode_name is None or mode_name == mode.name:
                    modes.append(mode)
            break

        return modes

    def get_mode_used(self, mode_name) -> bool:
        """true if the mode contains mapping information somewhere"""
        for device in self.devices.values():
            for mode_object in device.modes.values():
                if mode_object.name != mode_name:
                    continue
                for input_type in mode_object.config:
                    for input_item in mode_object.config[input_type].values():
                        if input_item.containers:
                            return True
        return False

    def isInputMapped(
        self,
        device_guid: dinput.GUID | str | int,
        input_type: InputType,
        input_id: int | object,
        mode: str = None,
    ) -> bool:
        """scans the profile to see if the specified input is mapped somewhere

        :param device_guid: device id
        :param input_type: the type of input we're looking for
        :param input_id: the input index or identifier
        :param mode: the specific profile mode to filter to, optional - if None applies to all profile modes

        """
        if device_guid in self.devices:
            device = self.devices[device_guid]
            for mode_object in device.modes.values():
                if mode and not mode_object.name == mode:
                    continue  # skip the particular mode
                if input_type in mode_object.config:
                    input_item = next(
                        (item for item in mode_object.config[input_type].values() if item is not None and input_id == item.input_id),
                        None,
                    )
                    if input_item and input_item.containers:
                        return True
        return False

    def isInputFiltered(
        self,
        device_guid: dinput.GUID | str | int,
        input_type: InputType,
        input_id: int | object,
    ) -> bool:
        """scans the profile to see if the specified input is mapped somewhere

        :returns bool: True if the item is visible, False if not

        """
        return self.settings.getInputVisible(device_guid, input_type, input_id)

    def get_selectable_modes(self):
        """gets the list of all selectable modes in the profile"""
        self._ensure_mode_tree()
        modes = [node.name for node in self._mode_tree.descendants]
        hide_default = gremlin.config.Configuration().hide_default_mode
        master_mode = gremlin.shared_state.master_mode
        if master_mode in modes:
            modes.remove(master_mode)
        if hide_default and len(modes) > 1 and "Default" in modes:
            modes.remove("Default")
        return modes

    def get_mode_map(self, casefold=False) -> dict:
        """gets profile modes as a map of profiles, keyed by name, holds the parent name"""

        mode_map = {}
        self._ensure_mode_tree()
        if self._mode_tree:
            if casefold:
                _modes = [node.name.casefold() for node in self._mode_tree.descendants]
            else:
                _modes = [node.name for node in self._mode_tree.descendants]

        for node in anytree.PreOrderIter(self._mode_tree):
            mode_name = node.name
            if mode_name:
                if casefold:
                    mode_name = mode_name.casefold()

                parent_node = node.parent
                parent_name = None
                if parent_node:
                    parent_name = parent_node.name
                    if parent_name and casefold:
                        parent_name = parent_name.casefold()

                mode_map[mode_name] = parent_name
        return mode_map

    def get_mode_branch(self, mode: str, ancestors: bool = True, descendants: bool = False) -> list:
        """gets the mode branch for the current mode - this is the list of the mode, and all parent modes"""
        self._ensure_mode_tree()
        mode_node = self.find_mode_node(mode)
        if mode_node:
            branch = [mode]
            if ancestors:
                branch.extend([node.name for node in mode_node.ancestors if node.name])
            if descendants:
                branch.extend([node.name for node in mode_node.descendants])
            return branch
        return None

    def reload_modes(self, update_devices=False):
        """reloads the mode tree from the device data

        :param update_devices: if set, updates the device to new modes to complete any missing mode sets (do this when loading from XML only)

        """
        # self._mode_tree = Node("") # root node
        self._ensure_mode_tree(True)

        mode_list = []
        node_map = {}
        node_map[""] = self._mode_tree
        inherit_map = {}

        mode_list = self._profile_graph.getModeList()

        # mode_nodes = [node for node in self._profile_graph.root.descendants if node.nodeType == gremlin.profile_graph.ProfileNodeType.Mode]
        for mode_name in mode_list:
            m_node = anytree.find_by_attr(self._mode_tree, mode_name)
            if not m_node:
                m_node = Node(mode_name)
                m_node.parent = self._mode_tree  # default parent node
            node_map[mode_name] = m_node
            mode_node = self._profile_graph.getModeNode(mode_name)
            inherit_map[mode_name] = mode_node.inherit

        for mode_name in mode_list:
            m_node = node_map[mode_name]
            parent_mode_name = inherit_map[mode_name]
            if parent_mode_name:
                m_parent_node = node_map[parent_mode_name]
                m_node.parent = m_parent_node

        # verbose = gremlin.config.Configuration().verbose
        # if verbose: self.dumpModeTree()
        # pass

    def rename_mode(self, old_mode: str, new_mode: str, emit=False) -> bool:
        """renames an existing mode to a new mode"""
        syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose
        if old_mode == new_mode:
            if verbose:
                syslog.warning(f"PROFILE: rename [{old_mode}] and [{new_mode}] are the same, skip")
            return False

        # mode tree
        node = anytree.find(self._mode_tree, lambda node: node.name == old_mode)
        if not node:
            if verbose:
                syslog.error(f"PROFILE: rename [{old_mode}] to [{new_mode}] - [{old_mode}] not found in the profile")
            return False

        new_node = anytree.find(self._mode_tree, lambda node: node.name == new_mode)
        if new_node:
            # already exist
            if verbose:
                syslog.error(f"PROFILE: rename [{old_mode}] to [{new_mode}] - [{old_mode}] already exists in the profile")
            return False

        node.name = new_mode

        # mode device objects
        mode: ProfileModeNode
        for device in self.devices.values():
            for mode in device.modes.values():
                if mode.name == old_mode:
                    # if verbose: syslog.info(f"PROFILE: rename [{old_mode}] to [{new_mode}]")
                    mode.name = new_mode

        return True

    def getDeviceNode(self, device_guid, autocreate=False, disconnected=False) -> ProfileDeviceNode:
        """gets a device node for this profile
        :param device_guid: the guid of the device to get a device profile for
        :param autocreate: autocreate the entry if it does not exist in the current profile and the device exists/is connected
        :returns: the device object, or None if does not exist
        """
        verbose = gremlin.config.Configuration().verbose_mode_execution
        device_guid = gremlin.util.parse_guid(device_guid)
        if device_guid not in self.devices:
            if autocreate:
                device = gremlin.joystick_handling.getDevice(device_guid)
                if device and not device.disabled:
                    device_node = ProfileDeviceNode(self)
                    device_node.device = device
                    self.devices[device_guid] = device_node
                    if verbose:
                        syslog.info(f"Profile: CREATE device node: [{str(device_node)}] profile id: [{self.id}]")
                    return device_node
                elif disconnected:
                    device_node = ProfileDeviceNode(self)
                    device_node.device = dinput.DeviceSummary()
                    device_node.device.connected = False

                    self.devices[device_guid] = device_node

                    if verbose:
                        syslog.info(f"Profile: CREATE disconnected device node: [{str(device_node)}] profile id: [{self.id}]")
                    return device_node
            return None

        return self.devices[device_guid]

    def readDeviceNode(self, node : etree.Element) -> ProfileDeviceNode:
        """gets a disconnected device node"""
        verbose = gremlin.config.Configuration().verbose_mode_execution
        device_node = ProfileDeviceNode(self)
        device_node.from_xml(node)
        if verbose:
            syslog.info(f"Profile: CREATE disconnected device node: [{str(device_node)}] profile id: [{self.id}]")
        return device_node



    def getModeNode(self, device_guid, mode: str, is_system: bool = False, autocreate=False):
        """gets a mode node
        :param device_guid: id of the device containing the mode node
        :param mode: the mode name (case sensitive)
        :param autocreate: flag to autocreate the node if it does not exist
        """
        device_node = self.getDeviceNode(device_guid, autocreate)
        if device_node:
            return device_node.getModeNode(mode, is_system, autocreate)
        return None

    def getModeNodeConfig(self, device_guid, mode: str, input_type: InputType, input_id, autocreate=False):
        """gets the configuration for the given mode"""
        device_node = self.getDeviceNode(device_guid, autocreate)
        if device_node:
            mode_node = device_node.getModeNode(mode, is_system=False, autocreate=autocreate)
            if mode_node:
                mode_config = mode_node.getConfig(input_type)
                if mode_config is not None:
                    if input_id in mode_config:
                        return mode_config[input_id]
                    mode_config[input_id] = None
                    return mode_config[input_id]

    def is_mode(self, mode) -> bool:
        """true if the mode exists in the current profile"""
        node = anytree.find(self._mode_tree, lambda node: self._compare_mode(node, mode))
        return node is not None

    def _compare_mode(self, node, mode: str):
        """comparator for modes in the mode tree"""

        if mode and node.name:
            mode_text = mode.casefold().strip()
            return node.name.casefold() == mode_text
        return False

    def find_mode(self, mode) -> str:
        """finds a mode by name or value"""
        self._ensure_mode_tree()
        if self._mode_tree is not None:
            node = anytree.find(self._mode_tree, lambda node: self._compare_mode(node, mode))
            if node:
                return node.name
        return None  # not found

    def find_mode_node(self, mode: str) -> ModeNode:
        """gets the graph mode node for the given name"""
        self._ensure_mode_tree()
        return anytree.find(self._mode_tree, lambda node: self._compare_mode(node, mode))

    def getMode(self, device_guid : dinput.GUID, mode: str) -> ProfileModeNode:
        """gets the profile mode node for the given name"""
        mode = mode.strip().casefold()
        device_node = self.getDeviceNode(device_guid, autocreate=False)
        if device_node:
            for mode_name in device_node.modes:
                if mode_name.casefold() == mode:
                    return device_node.modes[mode_name]
        return None


    def find_input(self, device_guid, input_id):
        """finds the input item for the give device_guid, input_id"""
        device_guid = gremlin.util.normalize_guid(device_guid)
        for dev_guid in self.devices:
            id = gremlin.util.normalize_guid(dev_guid)
            if id != device_guid:
                continue
            dev = self.devices[dev_guid]
            for mode_name in dev.modes:
                mode = dev.modes[mode_name]
                for input_type in mode.config:
                    for input_item in mode.config[input_type].values():
                        if input_item and input_item.input_id == input_id:
                            return input_item

        return None

    def find_inputs_by_type(self, device_guid, input_type: InputType):
        """gets inputs by type"""
        device_guid = gremlin.util.normalize_guid(device_guid)
        _input_list = []
        for dev_guid in self.devices:
            id = gremlin.util.normalize_guid(dev_guid)
            if id != device_guid:
                continue
            dev = self.devices[dev_guid]
            for mode_name in dev.modes:
                mode = dev.modes[mode_name]
                for _input_type in mode.config:
                    if _input_type == input_type:
                        return list[mode.config[input_type].values()]

        return None

    def first_input(self, device_guid):
        """finds the first input item for the give device_guid"""
        device_guid = gremlin.util.normalize_guid(device_guid)
        for dev_guid in self.devices:
            id = gremlin.util.normalize_guid(dev_guid)
            if id != device_guid:
                continue
            dev = self.devices[dev_guid]
            for mode_name in dev.modes:
                mode = dev.modes[mode_name]
                for input_type in mode.config:
                    for input_item in mode.config[input_type].values():
                        return input_item

        return None

    def getActionTree(self, lookup_action) -> ActionTreeNode:
        """finds the action in the current profile"""
        for dev_guid in self.devices:
            dev = self.devices[dev_guid]
            for mode_name in dev.modes:
                mode_object = dev.modes[mode_name]
                for input_type in mode_object.config:
                    for item in mode_object.config[input_type].values():
                        for container in item.containers:
                            for actions in [a for a in container.action_sets if a is not None]:
                                for action in actions:
                                    if lookup_action == action:
                                        # build the hierarchy
                                        root = ActionTreeNode()
                                        dev_node = ActionTreeNode(name="device", data=dev_guid)
                                        dev_node.parent = root
                                        mode_node = ActionTreeNode(name="mode", data=mode_object)
                                        mode_node.parent = dev_node
                                        input_item_node = ActionTreeNode(name="input_item", data=item)
                                        input_item_node.parent = mode_node
                                        container_node = ActionTreeNode(name="container", data=container)
                                        container_node.parent = input_item_node
                                        action_node = ActionTreeNode(name="action", data=action, tagdata=actions)
                                        action_node.parent = container_node
                                        root.data = action_node
                                        return root

            return None  # not found

    def list_actions(self):
        """lists all actions in the current profile"""
        # Create a list of all used remap actions

        self.registry.sync()

        remap_actions = []
        for dev_guid in self.devices:
            dev = self.devices[dev_guid]
            for mode_name in dev.modes:
                mode = dev.modes[mode_name]
                for input_type in mode.config:
                    for item in mode.config[input_type].values():
                        for container in item.containers:
                            remap_actions.extend(extract_remap_actions(container.action_sets))

        return remap_actions

    def list_unused_vjoy_inputs(self):
        """Returns a list of unused vjoy inputs for the given profile.

        :return dictionary of unused inputs for each input type  [vjoy_dev_id: int]["axis" | "button" | "hat"] = list[input_id : int]
        """
        vjoy_devices = gremlin.joystick_handling.virtual_devices()

        # Create list of all inputs provided by the vjoy devices
        vjoy = {}
        for entry in vjoy_devices:
            vjoy[entry.vjoy_id] = {"axis": [], "button": [], "hat": []}
            for i in range(entry.axis_count):
                vjoy[entry.vjoy_id]["axis"].append(entry.axismap_list[i].axis_index)
            for i in range(entry.button_count):
                vjoy[entry.vjoy_id]["button"].append(i + 1)
            for i in range(entry.hat_count):
                vjoy[entry.vjoy_id]["hat"].append(i + 1)

        # Create a list of all used remap actions
        remap_actions = self.list_actions()

        # Remove all remap actions from the list of available inputs
        for act in remap_actions:
            # Skip remap actions that have invalid configuration
            if act.input_type is None or act.input_type not in (
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat,
            ):
                continue

            type_name = InputType.to_string(act.input_type)
            virtual_id = act.virtual_id
            if virtual_id not in vjoy or act.vjoy_input_id in [0, None] or virtual_id in [0, None] or act.vjoy_input_id not in vjoy[virtual_id][type_name]:
                continue

            idx = vjoy[virtual_id][type_name].index(act.vjoy_input_id)
            del vjoy[virtual_id][type_name][idx]

        return vjoy

    @property
    def profile_file(self):
        """gets the profile file name normalized for a PC case insentitive"""

        return self._profile_fname

    def setProfileFile(self, value):
        """sets the profile save file xml"""
        if value:
            self._profile_fname = gremlin.util.fix_path(value)
            self._profile_config_fname = gremlin.util.swap_ext(self._profile_fname, "json")
        else:
            self._profile_fname = None
            self._profile_config_fname = None

    def get_default_mode(self):
        """gets the default mode for this profile - this is the mode used if the default startup mode is not specified"""
        modes = self.get_selectable_modes()
        if modes:
            return modes[0]

    def from_xml(self, fname, data=None, extra_data=None, fname_is_xml: bool = False):
        """Parses the profile XML document into the profile data structure.

        :param fname the path to the XML file to parse
        """
        # Check for outdated profile structure and warn user / convert
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_ui
        import_data = ProfileImportData()
        import_data.used_ids = {}  # reset used list
        profile_was_updated = False
        self.registry.reset()  # clear registry on profile load

        if extra_data is None:
            extra_data = {}

        if fname_is_xml:
            # fname is an xml stream
            root = etree.fromstring(fname)
        else:
            profile_converter = gremlin.profile.ProfileConverter()

            if not profile_converter.is_current(fname):
                syslog.warning("Outdated profile, converting")
                profile_converter.convert_profile(fname)
                profile_was_updated = True
            tree = etree.parse(fname)
            root = tree.getroot()

        if verbose:
            syslog.info(f"XML: parsing profile [{gremlin.util.toUrl(fname)}]")

        # profile id
        if "guid" in root.attrib:
            self.id = normalize_guid(root.get("guid"))
        else:
            # regenerate the profile
            root.set("guid", self.id)
            tree.write(fname, encoding="utf-8", xml_declaration=True) # update the file with the new profile ID if it's missing

        self._start_mode = None
        if "start_mode" in root.attrib:
            self._start_mode = root.get("start_mode")

        if "default_start_mode" in root.attrib:
            # older version of profile
            self._default_start_mode = root.get("default_start_mode")
        if "default_mode" in root.attrib:
            self._default_start_mode = root.get("default_mode")

        self._restore_last_mode = False
        if "restore_last" in root.attrib:
            self._restore_last_mode = safe_read(root, "restore_last", bool, False)

        if "force_numlock" in root.attrib:
            self._force_numlock_off = safe_read(root, "force_numlock", bool, False)
        if "force_numlock_on" in root.attrib:
            self._force_numlock_on = safe_read(root, "force_numlock_on", bool, False)

        # settings data
        self.settings.from_xml(root.find("settings"), data, extra_data)

        # state data - read first because states can be referenced by nodes
        mode_nodes = root.xpath("//states")
        if not mode_nodes:
            # not found
            self.state.clear()
        for node in mode_nodes:
            self.state.from_xml(node)

        # removed devices
        self._removed_devices.clear()

        # moved to display options
        # removed_nodes = root.xpath("//removed-devices/device")
        # for node in removed_nodes:
        #     id = node.get("id")
        #     self._removed_devices.append(id)

        # Parse each device into separate DeviceConfiguration objects
        device_nodes = root.xpath("//profile/devices/device")
        for child in device_nodes:
            if "type" in child.attrib:
                device_type = DeviceType.to_enum(child.get("type"))
                if device_type == DeviceType.OctaviIFR1:
                    continue  # skip this device

            if "device-guid" not in child.attrib:
                syslog.warning(f"XML: missing device-guid attribute for device - offending line {child.sourceline}")
                continue

            device_guid = parse_guid(child.get("device-guid"))

            if device_guid is None:
                syslog.warning(f"XML: invalid ID format for device: device-guid [{child.get('device-guid')}] - offending line {child.sourceline}")
                continue

            # special case - mode control device
            if device_guid == gremlin.ui.mode_device.ModeDeviceTabWidget.device_guid:
                device_node = self.getDeviceNode(device_guid)
                assert device_node is not None, "mode control device should already exist in profile"
            else:
                device_node = self.getDeviceNode(device_guid, autocreate=True)
            if device_node is None:
                # disconnected device most likely
                device_node = self.readDeviceNode(child)
                self.devices[device_guid] = device_node

            if device_node is None:
                syslog.warning(f"XML: unrecognized device id [{str(device_guid)}] line : {child.sourceline} - skipping this entry")
                continue
            extra_data["device_node"] = device_node
            if device_node.connected():
                # disconnected nodes are already read
                device_node.from_xml(child, data, extra_data)

            dd: dinput.DeviceSummary = gremlin.joystick_handling.getDevice(device_node.device_guid)
            if not dd:
                name = safe_read(child, "name", str, "n/a")
                syslog.warning(f"Profile: unable to find device [{device_node.device_guid}] - name: [{name}] - XML source line: {child.sourceline}")
            elif dd.is_virtual:
                # vjoy as input
                self.settings.setVjoyAsInput(dd.vjoy_id, True)
                if verbose:
                    syslog.info(f"PROFILE: enable vjoy as input device [{dd.vjoy_id}]")

        # Parse each vjoy device into separate DeviceConfiguration objects
        if not extra_data:
            extra_data = {}
        dummy = ProfileModeNode()
        dummy.load(profile=self, name="*placeholder*", device_guid=gremlin.joystick_handling.invalidDeviceGuid())
        extra_data["mode_object"] = dummy

        vjoy_nodes = root.xpath("//profile/devices/vjoy-device")
        for child in vjoy_nodes:
            device_node = ProfileDeviceNode(self)
            device_node.from_xml(child, data, extra_data)
            self.vjoy_devices[device_node.device_guid] = device_node

        # parse simconnect startup entries
        self._simconnect_modes = {}
        for child in root.iter("simconnect"):
            key_cp = safe_read(child, "key_cp", str, "")
            key_ap = safe_read(child, "key_ap", str, "")
            mode_name = safe_read(child, "mode", str, "")
            key = (key_cp.casefold(), key_ap.casefold())
            self._simconnect_modes[key] = mode_name

        # extract the mode list
        mode_node_map = {}  # list of xml mode nodes keyed by mode name
        mode_tree_nodes = {}  # list of mode nodes for the mode tree
        mode_tree_root = ModeNode(is_root=True)  # root mode of the tree
        mode_tree_root.isModeRoot = True
        mode_tree_nodes[""] = mode_tree_root
        master_mode_name = gremlin.shared_state.master_mode

        node_list = root.xpath("//profile/modes")
        if not node_list:
            # old style profiles that do not have a separate mode interface
            node_list = root.xpath("//devices/device/mode")
        if node_list:
            mode_nodes = node_list[0]
            for mode_node in mode_nodes:
                mode_name = html.unescape(mode_node.get("name"))
                # if verbose: syslog.info(f"PROFILE MODE: [{mode_name}] ")
                if mode_name in mode_node_map:
                    continue  # already known

                if mode_name not in mode_node_map:
                    mode_tree_node = ModeNode(mode_name)
                    mode_tree_nodes[mode_name] = mode_tree_node
                mode_node_map[mode_name] = mode_node

                if "inherit" in mode_node.attrib:
                    parent_mode_name = html.unescape(mode_node.get("inherit"))
                    # Guard against the old bool-serialization bug ("True"/"False").
                    if parent_mode_name in ("True", "False"):
                        parent_mode_name = None

                    if parent_mode_name is not None:
                        if parent_mode_name not in mode_node_map:
                            tree_parent_mode = ModeNode(parent_mode_name)
                            mode_tree_nodes[parent_mode_name] = tree_parent_mode

                        mode_tree_node.parent_name = parent_mode_name

        # link parent nodes in the tree
        for mode_name in mode_tree_nodes:
            if not mode_name:
                continue  # root
            tree_node = mode_tree_nodes[mode_name]
            parent_name = tree_node.parent_name
            if parent_name:
                parent_tree_node = mode_tree_nodes[parent_name]
                tree_node.parent = parent_tree_node
            else:
                # no parent - parent to root
                tree_node.parent = mode_tree_root

        if master_mode_name not in mode_node_map:
            # add new master mode for old profiles for manual edits in case the converter didn't catch it
            master_tree_mode = ModeNode(master_mode_name)
            master_tree_mode.parent = mode_tree_root
            mode_tree_nodes[master_mode_name] = mode_tree_root

        mode_list = list(mode_node_map.keys())

        # Ensure that the profile contains an entry for every existing
        # device even if it was not part of the loaded XML and
        # replicate the modes present in the profile. This adds both entries
        # for physical and virtual joysticks.
        device_list = gremlin.joystick_handling.all_joystick_devices()
        for dev in device_list:
            if dev.disabled:
                # ignore disabled devices
                continue
            add_device = False
            if dev.is_virtual and dev.device_guid not in self.vjoy_devices:
                add_device = True
            elif not dev.is_virtual and dev.device_guid not in self.devices:
                add_device = True

            if add_device:
                new_device = self.getDeviceNode(dev.device_guid, autocreate=True)

                if new_device.virtual:
                    self.vjoy_devices[dev.device_guid] = new_device


        # Parse merge axis entries
        for child in root.iter("merge-axis"):
            self.merge_axes.append(self._parse_merge_axis(child))

        # Parse plugin entries
        for child in root.findall("plugins/plugin"):
            plugin = Plugin(self)
            plugin.from_xml(child, data, extra_data)
            self.plugins.append(plugin)

        if not self._start_mode:
            # use a default mode
            self._start_mode = self.get_default_mode()

        if fname_is_xml:
            self._profile_fname = None
            self._profile_config_fname = None
        else:
            self._profile_fname = gremlin.util.fix_path(fname)
            self._profile_config_fname = gremlin.util.swap_ext(self._profile_fname, "json")
            name, _ = os.path.splitext(os.path.basename(fname))
            self._profile_name = name

        # update missing modes from devices
        for device_node in self.devices.values():
            device_modes = [mode.name for mode in device_node.modes.values()]
            missing_mode_names = [name for name in mode_list if name not in device_modes]
            for mode_name in missing_mode_names:
                mode_object = ProfileModeNode(name=mode_name, parent=device_node)
                device_node.modes[mode_name] = mode_object
                mode_tree_node = mode_tree_nodes[mode_name]
                if mode_tree_node.parent_name:
                    mode_object.inherit = mode_tree_node.parent_name

        # read button and axis startup data
        node_devices = root.xpath("//profile/start/devices/device")
        self._start_state.clear()
        for node_device in node_devices:
            device_id = node_device.get("device-guid")
            self._start_state[device_id] = {}
            for node in node_device:
                id = safe_read(node, "id", int, 0)
                if not id:
                    continue
                if node.tag == "button":
                    state = safe_read(node, "value", bool, False)
                    if "buttons" not in self._start_state[device_id]:
                        self._start_state[device_id]["buttons"] = {}
                    self._start_state[device_id]["buttons"][id] = state
                elif node.tag == "axis":
                    if "axis" not in self._start_state[device_id]:
                        self._start_state[device_id]["axis"] = {}
                    if "enabled" not in self._start_state[device_id]:
                        self._start_state[device_id]["enabled"] = {}
                    value = safe_read(node, "value", float, 0.0)
                    self._start_state[device_id]["axis"][id] = value
                    enabled = safe_read(node, "enabled", bool, False)
                    self._start_state[device_id]["enabled"][id] = enabled

        # have config use updated profile settings
        config = gremlin.config.Configuration()
        config.ensure_profile(self)

        # load the profile graph
        self._profile_graph = gremlin.profile_graph.ProfileGraph()
        self._profile_graph.from_xml(fname, fname_is_xml=fname_is_xml)

        # load the mode tree
        self.reload_modes(update_devices=True)

        if verbose:
            self.dumpModeTree()
            if config.verbose_mode_ui:
                # full profile dump
                self.dumpTree()
            syslog.info(f"XML: profile loaded: {gremlin.util.toUrl(fname)}")

        # clear used memory
        import_data.used_ids = {}  # reset used list

        return profile_was_updated

    def dumpTree(self):
        """dumps the profile tree from the current profile graph"""
        graph = gremlin.profile_graph.ProfileGraph.fromProfile(self)
        graph.dump()

    def to_xml(self, fname: str = None):
        """Generates XML code corresponding to this profile.

        :param fname: name of the file to save the XML to, if None the function returns the XML string of the profile
        """

        # ensure registry and model are synchronized before saving
        self.sync()

        # Generate XML document
        root = etree.Element("profile")
        root.set("version", str(gremlin.profile.ProfileConverter.current_version))
        root.set("start_mode", self.get_start_mode())
        root.set("default_mode", self.get_default_start_mode())
        root.set("restore_last", str(self._restore_last_mode))
        root.set("force_numlock", str(self._force_numlock_off))
        root.set("force_numlock_on", str(self._force_numlock_on))
        root.set("guid",self.id) # profile ID

        # mode list

        mode_tree_root = self.mode_tree(True)
        root_mode_node = etree.Element("modes")
        root.append(root_mode_node)

        # new as of m73 - new mode node for mode hieararchy
        nodes = {}
        for tree_node in anytree.PreOrderIter(mode_tree_root):
            mode = tree_node.name
            if not mode:
                continue  # root node
            node = etree.Element("mode")  # new xml child
            node.set("name", html.escape(mode))  # set mode value
            if tree_node.parent:
                parent_mode = tree_node.parent.name
                if parent_mode:
                    node.set("inherit", html.escape(parent_mode))

            nodes[mode] = node  # track it
            parent_mode = tree_node.parent.name if tree_node.parent else None
            root_mode_node.append(node)

        # moved to display preferences - removed as of m76t101
        # new as m76t101 - removed mode list
        # this is the list of devices removed by the user
        # if self._removed_devices:
        #     removed_device_node = etree.Element("removed-devices")
        #     for id in self._removed_devices:
        #         id_node = etree.Element("device")
        #         id_node.set("id", id)
        #         removed_device_node.append(id_node)
        #     root.append(removed_device_node)

        # sync registry
        self.registry.sync()

        # Device settings
        devices = etree.Element("devices")
        device_list = sorted(self.devices.values(), key=lambda x: str(x.device_guid))

        # strip the unused nodes that don't contain any data where possible to reduce the size of the profile
        for device in device_list:
            node = device.to_xml()
            if node is None:
                continue  # skip devices that do not produce an XML node

            depth = gremlin.util.xmlNodeDepth(node)
            if device.device_type in (
                DeviceType.Joystick,
                DeviceType.VJoy,
                DeviceType.State,
                DeviceType.ModeControl,
            ):
                # remove empty nodes
                if depth > 0:
                    devices.append(node)

            else:
                # check for inputs
                if device.device_type in (
                    DeviceType.Keyboard,
                    DeviceType.Osc,
                    DeviceType.Midi,
                ):
                    has_inputs = node.xpath("//input")
                    if has_inputs:
                        devices.append(node)
                else:
                    devices.append(node)

        root.append(devices)

        # simconnect settings
        for key, mode in self._simconnect_modes.items():
            if key:
                if isinstance(key, tuple):
                    key_cp, key_ap = key
                    assert key_cp, "invalid CP key found"
                    assert key_ap, "invalid AP key found"
                else:
                    # single key
                    key_cp = key
                    key_ap = key

                child = etree.Element("simconnect")
                child.set("key_cp", key_cp)
                child.set("key_ap", key_ap)
                child.set("mode", mode)
                root.append(child)

        # VJoy settings
        add_vjoy = False
        vjoy_devices = etree.Element("vjoy-devices")
        for device_node in self.vjoy_devices.values():
            node = device_node.to_xml()
            if node is None:
                continue  # skip VJoy devices that do not produce an XML node
            has_container = node.xpath("./container")
            if has_container:
                vjoy_devices.append(node)
                add_vjoy = True
            if device_node.device:
                node.set("vjoy-id", safe_format(device_node.device.vjoy_id, int))



        if add_vjoy:
            root.append(vjoy_devices)

        # Merge axis data
        for entry in self.merge_axes:
            node = etree.Element("merge-axis")
            node.set("mode", safe_format(entry["mode"], str))
            node.set(
                "operation",
                safe_format(MergeAxisOperation.to_string(entry["operation"]), str),
            )
            for tag in ["vjoy"]:
                if tag in entry:
                    sub_node = etree.Element(tag)
                    sub_node.set("vjoy-id", safe_format(entry[tag]["vjoy_id"], int))
                    sub_node.set("axis-id", safe_format(entry[tag]["axis_id"], int))
                    node.append(sub_node)
            for tag in ["lower", "upper"]:
                if tag in entry:
                    sub_node = etree.Element(tag)
                    sub_node.set("device-guid", write_guid(entry[tag]["device_guid"]))
                    sub_node.set("axis-id", safe_format(entry[tag]["axis_id"], int))
                    node.append(sub_node)
            root.append(node)

        # Settings data
        root.append(self.settings.to_xml())

        # User plugins
        plugins = etree.Element("plugins")
        for plugin in self.plugins:
            plugins.append(plugin.to_xml())
        root.append(plugins)

        # startup device button and axis values data
        node_start = etree.SubElement(root, "start")
        node_devices = etree.SubElement(node_start, "devices")
        dn = {}
        for device_id in self._start_state:
            node_device = None
            for id in self._start_state[device_id]:
                if "buttons" in self._start_state[device_id]:
                    # only write non default values for buttons
                    for id in self._start_state[device_id]["buttons"]:
                        state = self._start_state[device_id]["buttons"][id]
                        if state:
                            if device_id not in dn:
                                node_device = etree.SubElement(node_devices, "device")
                                node_device.set("device-guid", device_id)
                                dn[device_id] = node_device
                            node_button = etree.SubElement(node_device, "button")
                            node_button.set("id", safe_format(id, int))
                            node_button.set("value", safe_format(state, bool))

                if "axis" in self._start_state[device_id]:
                    for id in self._start_state[device_id]["axis"]:
                        if device_id not in dn:
                            node_device = etree.SubElement(node_devices, "device")
                            node_device.set("device-guid", device_id)
                            dn[device_id] = node_device

                        node_axis = etree.SubElement(node_device, "axis")
                        node_axis.set("id", safe_format(id, int))
                        value = self._start_state[device_id]["axis"][id]
                        node_axis.set("value", safe_format(value, float))

                        enabled = self._start_state[device_id]["enabled"][id]
                        node_axis.set("enabled", safe_format(enabled, bool))

        # state data
        node = self.state.to_xml()
        root.append(node)

        # Serialize XML document
        tree = etree.ElementTree(root)
        if fname:
            tree.write(fname, pretty_print=True, xml_declaration=True, encoding="utf-8")
        else:
            # return the xml string
            return etree.tostring(tree)

    def get_device_modes(self, device_guid: dinput.GUID, device_type: DeviceType, device_name: str = None) -> ProfileDeviceNode:
        """Returns the modes associated with the given device.

        :param device_guid the device's GUID
        :param device_type the type of the device being queried
        :param device_name the name of the device
        :return all modes for the specified device
        """
        if device_type == DeviceType.VJoy:
            if device_guid not in self.vjoy_devices:
                # Create the device
                device = ProfileDeviceNode(self)
                device.name = device_name
                device.device_guid = device_guid
                device.type = DeviceType.VJoy
                self.vjoy_devices[device_guid] = device
            return self.vjoy_devices[device_guid]

        else:
            if device_guid not in self.devices:
                # Create the device
                device = ProfileDeviceNode(self)
                device.name = device_name
                device.device_guid = device_guid

                self.devices[device_guid] = device
            return self.devices[device_guid]

    def empty(self):
        """Returns whether or not a profile is empty.

        :return True if the profile is empty, False otherwise
        """
        is_empty = True
        is_empty &= len(self.merge_axes) == 0

        # Enumerate all input devices
        all_input_types = [
            InputType.JoystickAxis,
            InputType.JoystickButton,
            InputType.JoystickHat,
            InputType.Keyboard,
            InputType.Midi,
            InputType.OpenSoundControl,
            InputType.State,
        ]

        # Process all devices
        for dev in self.devices.values():
            for mode in dev.modes.values():
                for input_type in all_input_types:
                    if input_type in mode.config:
                        for item in mode.config[input_type].values():
                            is_empty &= item is None or len(item.containers) == 0

        # Process all vJoy devices
        for dev in self.vjoy_devices.values():
            for mode in dev.modes.values():
                for input_type in all_input_types:
                    if input_type in mode.config:
                        for item in mode.config[input_type].values():
                            is_empty &= item is None or len(item.containers) == 0

        return is_empty

    def _parse_merge_axis(self, node):
        """Parses merge axis entries.

        :param node the node to process
        :return merge axis data structure parsed from the XML node
        """
        entry = {
            "mode": node.get("mode", None),
            "operation": MergeAxisOperation.to_enum(safe_read(node, "operation", str, "average")),
        }
        # TODO: apply safe reading to these
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
                    "axis_id": safe_read(n, "axis-id", int, 1),
                }

        return entry

    def get_start_mode(self):
        """gets the start mode for this profile"""
        mode = self.find_mode(self._start_mode)
        # verify the mode is in the mode list
        if not mode:
            modes = self.get_modes()
            mode = modes[0]
            self._start_mode = mode
        if not mode:
            return self.get_default_start_mode()
        return mode

    def set_start_mode(self, value: str):
        """sets the profile auto-activated start up mode"""
        assert isinstance(value, str)
        self._start_mode = value
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            syslog.info(f"Profile {self.name}: set start mode to {value}")
        self.save()

    def set_default_start_mode(self, value: str):
        """sets the profile normal start up mode - this will only be used if the startup mode is not overwritten by the last mode - saving a default start mode also resets the last used start mode
        the mode saved here should be the mode dialog default
        """
        assert isinstance(value, str)
        self._default_start_mode = value
        self._start_mode = value
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            syslog.info(f"Profile {self.name}: set default start mode to {value}")
        self.save(backup=False)

    def get_default_start_mode(self):
        """gets the profile's default startup mode"""
        if not self._default_start_mode:
            # use the default mode if not setup
            self._default_start_mode = self.get_default_mode()
        mode = self._default_start_mode
        modes = self.get_modes()
        if mode not in modes:
            self._default_start_mode = self.get_root_mode()
        return self._default_start_mode

    def get_restore_mode(self) -> bool:
        """gets the start mode for this profile"""
        return self._restore_last_mode

    def set_restore_mode(self, value: bool):
        """sets the start up mode"""
        self._restore_last_mode = value
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            syslog.info(f"Profile {self.name}: set auto-restore flag {value}")
        self.save(backup=False)

    def save(self, save_as_name=None, backup=True):
        """saves the profile"""

        verbose = gremlin.config.Configuration().verbose
        if save_as_name is None:
            if self._profile_fname is None:
                gremlin.ui.ui_common.MessageBox(prompt="File is not set, please save the profile first")
                return

            assert self._profile_fname, "File name is not set"

            use_name = self._profile_fname
        else:
            use_name = save_as_name

        # do a backup
        backup_max = gremlin.config.Configuration().backup_count
        if backup_max > 0 and backup and os.path.isfile(use_name):
            backup_count = 1
            base_name = os.path.basename(use_name)
            base_name = gremlin.util.strip_ext(base_name)
            backup_files = []

            # get the backup number
            pattern = f"{base_name}.*.xml"
            profile_path = gremlin.shared_state.data_path
            backup_path = os.path.join(profile_path, gremlin.shared_state.application_version)
            if not os.path.isdir(backup_path):
                try:
                    os.makedirs(backup_path)
                except Exception as err:
                    syslog.error(f"BACKUP: unable to create backup folder {backup_path}:")
                    syslog.error(f"{err}\n{traceback.format_exc()}")

            if os.path.isdir(backup_path):
                backup_files = gremlin.util.find_files(backup_path, pattern)
                start_count = 0
                modified_data = []
                for backup_file in backup_files:
                    modified = os.path.getmtime(backup_file)
                    f_name = os.path.basename(backup_file)
                    splits = f_name.split(".")
                    s_count = splits[1]
                    if s_count.isnumeric():
                        count = int(s_count)
                        if count > start_count:
                            start_count = count

                    modified_data.append((modified, backup_file))

                # keep the count of files in check
                if len(backup_files) > backup_max:
                    modified_data.sort(key=lambda x: x[0])
                    _, oldest_file = modified_data[0]
                    try:
                        os.unlink(oldest_file)
                    except Exception as err:
                        syslog.error(f"BACKUP: save error: Unable to remove oldest backup profile: {oldest_file}:")
                        syslog.error(f"{err}\n{traceback.format_exc()}")

                # next file
                backup_count = start_count + 1
                backup_file = os.path.join(backup_path, f"{base_name}.{backup_count}.xml")
                try:
                    shutil.copyfile(use_name, backup_file)
                    # verbose = gremlin.config.Configuration().verbose
                    # if verbose:
                    syslog.info(f"BACKUP: Saved backup profile: {gremlin.util.toUrl(backup_file)}")
                except Exception as err:
                    syslog.error(f"BACKUP: save error: Unable to backup profile: [{gremlin.util.toUrl(backup_file)}]")
                    syslog.error(f"{err}\n{traceback.format_exc()}")
                    return

        if use_name:
            try:
                self.to_xml(use_name)
                if verbose:
                    syslog.info(f"SAVE: [{gremlin.util.toUrl(self._profile_fname)}]")

            except Exception as err:
                syslog.error(f"SAVE: error: [{gremlin.util.toUrl(self._profile_fname)}]")
                syslog.error(f"{err}\n{traceback.format_exc()}")
        else:
            self._profile_fname = None
            self._dirty = False

    def _readConfig(self) -> dict:
        """reads the profile config, ensuring it is done on the UI thread"""
        completed = False

        def nonlocal_set(var, value):
            nonlocal completed
            var = value  # noqa: F841
            completed = True

        if gremlin.util.is_ui_thread():
            return self._readConfig_ui()
        else:
            result = None
            time_max = time.time() + 2.0  # maximum wait time of 5 seconds
            gremlin.util.InvokeUiMethod(lambda: nonlocal_set(result, self._readConfig_ui()))
            while not completed and time.time() < time_max:
                time.sleep(0.01)
            if not completed:
                syslog.warning("Profile config read timed out")
            return result




    def _readConfig_ui(self) -> dict:
        """reads the profile config"""
        fname = self._profile_config_fname
        if self._config_data_read:
            return self._config_data

        assert gremlin.util.is_ui_thread(), "Profile config read must be done on the UI thread"

        data = {}
        if fname and os.path.isfile(fname):
            try:
                verbose = gremlin.config.Configuration().verbose
                if verbose:
                    syslog.info(f"Profile: read profile configuration: {gremlin.util.toUrl(fname)}")

                with open(fname, "r", encoding="utf-8") as hdl:
                    decoder = json.JSONDecoder()
                    data = decoder.decode(hdl.read())

            except Exception:
                # failed to read
                pass

        self._config_data = data
        self._config_data_read = True

        return data

    def _writeConfig(self, data: dict):
        fname = self._profile_config_fname
        if fname:
            try:
                with open(fname, "w") as hdl:
                    encoder = json.JSONEncoder(sort_keys=True, indent=4)
                    hdl.write(encoder.encode(data))
                    hdl.flush()
                    hdl.close()
            except Exception:
                pass

        self._config_data = data

    def _setConfig(self, key, value):
        """sets a configuration value and saves to the profile config file"""

        data = self._readConfig()  # get the profile config
        data[key] = value
        self._writeConfig(data)

    @property
    def saveConfigEnabled(self) -> bool:
        """true if the profile can save the configuration"""
        return self._save_config_enabled

    @saveConfigEnabled.setter
    def saveConfigEnabled(self, value: bool):
        self._save_config_enabled = value

    def setLastInput(self, device_guid, input_type, input_id):
        """sets the last profile input"""
        if self._save_config_enabled:
            data = self._readConfig()  # get the profile config
            if device_guid is None:
                # remove existing device, input and id
                if "last_device_guid" in data:
                    del data["last_device_guid"]
                if "last_input_id" in data:
                    del data["last_input_id"]
                if "last_input_type" in data:
                    del data["last_input_id"]

            else:
                data["last_device_guid"] = gremlin.util.normalize_guid(device_guid)
                if "selection_map" not in data:
                    data["selection_map"] = {}
                data["selection_map"]["device_guid"] = {}

                if input_id is None:
                    # remove any existing input_id and input_type
                    if "last_input_id" in data:
                        del data["last_input_id"]
                    if "last_input_type" in data:
                        del data["last_input_type"]
                    if "input_id" in data["selection_map"]["device_guid"]:
                        del data["selection_map"]["device_guid"]["input_id"]
                    if "input_type" in data["selection_map"]["device_guid"]:
                        del data["selection_map"]["device_guid"]["input_type"]
                else:
                    # id provided
                    if not isinstance(input_id, int) or isinstance(input_id, float):
                        # complex input id like a key, state, osc command
                        if hasattr(input_id, "message_key"):
                            data["last_input_id"] = input_id.message_key
                        else:
                            data["last_input_id"] = input_id
                    else:
                        data["last_input_id"] = input_id

                    data["selection_map"]["device_guid"]["input_id"] = data["last_input_id"]

                    if input_type is None:
                        if "last_input_type" in data:
                            del data["last_input_type"]
                        if "input_type" in data["selection_map"]["device_guid"]:
                            del data["selection_map"]["device_guid"]["input_type"]

                    else:
                        data["last_input_type"] = InputType.to_string(input_type)
                        data["selection_map"]["device_guid"]["input_type"] = data["last_input_type"]

            self._writeConfig(data)

    def getLastInput(self, device_guid=None) -> tuple:
        """gets the last input for this profile (device_guid, input_type, input_id)"""
        data = self._readConfig()  # get the profile config
        if data is None:
            return (None, None, None)

        input_id = None
        input_type = None
        if device_guid is not None and "selection_map" in data:
            device_guid = gremlin.util.normalize_guid(device_guid)
            if device_guid in data["selection_map"]:
                if "input_id" in data["selection_map"]["device_guid"]:
                    input_id = data["last_input_id"]
                if "input_type" in data["selection_map"]["device_guid"]:
                    input_type = InputType.convert(data["last_input_type"])

        if device_guid is None:
            if "last_device_guid" in data:
                device_guid = data["last_device_guid"]
            if "last_input_type" in data:
                input_type = InputType.convert(data["last_input_type"])
            if "last_input_id" in data:
                input_id = data["last_input_id"]

            if device_guid is None:
                # not found
                config = gremlin.config.Configuration()
                device_guid, input_type, input_id = config.get_last_input()

        return (device_guid, input_type, input_id)

    def copy_devices(self, source_guid, target_guid):
        """copies data between two devices"""
        if not source_guid or not target_guid or target_guid == source_guid:
            # nothing to do
            return

        if isinstance(source_guid, str):
            source_guid = gremlin.util.parse_guid(source_guid)

        if isinstance(target_guid, str):
            target_guid = gremlin.util.parse_guid(target_guid)

        source_device = gremlin.joystick_handling.getDevice(source_guid)
        if not source_device or target_guid not in self.devices:
            syslog.warning(f"DEVICE COPY: source device [{source_guid}] not found")
            return
        target_device = gremlin.joystick_handling.getDevice(target_guid)
        if not target_device or target_guid not in self.devices:
            syslog.warning(f"DEVICE COPY: target device [{target_guid}] not found")

        _copy_axis = True
        _copy_buttons = True
        tmp_file = gremlin.util.getTemporaryFile(".xml")

        updated = False
        for mode_name in self.devices[source_guid].modes:
            # find the corresponding mode
            source_mode_object = self.devices[source_guid].modes[mode_name]
            target_mode_object = self.devices[target_guid].modes[mode_name]
            for input_type in source_mode_object.config:
                if input_type in target_mode_object.config:
                    # matching input type
                    if input_type in target_mode_object.config:
                        for input_id in source_mode_object.config[input_type]:
                            if input_id in target_mode_object.config[input_type]:
                                source_input_item = source_mode_object.config[input_type][input_id]
                                if source_input_item.containers:
                                    # source has mappings
                                    target_input_item = target_mode_object.config[input_type][input_id]
                                    source_input_item.save_container_to_template(tmp_file)
                                    target_input_item.load_container_from_template(tmp_file)
                                    updated = True

        # cleanup after ourselves
        if os.path.isfile(tmp_file):
            os.unlink(tmp_file)

        if updated:
            # indicate the profile has to be reloaded
            el = gremlin.event_handler.EventListener()
            el.request_reload.emit()

    def _filter_actions_input_item(
        self,
        input_item,
        tag_or_list: str | list[str],
        callback,
        extra_data: dict = None,
    ) -> bool:
        """intermediate call for every input item in the profile with a mapping"""

        if not input_item or not input_item.containers:
            return False

        if hasattr(tag_or_list, "__iter__"):
            tag_list = tag_or_list
        else:
            tag_list = [tag_or_list]


        for container in input_item.containers:
            for action_set in container.action_sets:
                for action in action_set:
                    if action.tag == "gated-axis":
                        # special handling for gated axis
                        gate_data: gremlin.gated_handler.GateData = action.gate_data
                        gate: gremlin.gated_handler.GateInfo
                        for gate in gate_data.getGates():
                            # gate containers
                            for condition, item in gate.item_data_map.items():
                                result = self._filter_actions_input_item(item, tag_or_list, callback, extra_data)
                                if not result:
                                    return False

                        rng: gremlin.gated_handler.RangeInfo
                        for rng in gate_data.getRanges():
                            # gate containers
                            for condition, item in rng.item_data_map.items():
                                result = self._filter_actions_input_item(item, tag_or_list, callback, extra_data)
                                if not result:
                                    return False

                    if action.tag in tag_list:
                        result = callback(action, extra_data)
                        if not result:
                            return False
        return True

    def filter_actions(self, tag_or_list: str | list[str], callback, extra_data: dict = None):
        """issues a callback for every matching action tag found in the profile callback(action)"""
        self.sync()
        for dev_guid in self.devices:
            dev = self.devices[dev_guid]
            if dev.device_type == gremlin.types.DeviceType.State:
                # state device (modeless) - special handling of state input items
                state_data = gremlin.shared_state.current_profile.state
                input_items = [state_data[key] for key in state_data]
                for item in input_items:
                    result = self._filter_actions_input_item(item, tag_or_list, callback, extra_data)
                    if not result:
                        return
            else:
                for mode_name in dev.modes:
                    mode_object = dev.modes[mode_name]
                    for input_type in mode_object.config:
                        for item in mode_object.config[input_type].values():
                            result = self._filter_actions_input_item(item, tag_or_list, callback, extra_data)
                            if not result:
                                return

    def _filter_conditions_input_item(self, input_item: InputItem, callback, extra_data: dict = None) -> bool:
        """extracts all conditions from the profile and executes the callback for each condition found - if the callback returns false, the chain exits"""

        # condition_list = input_item.getConditions()
        # if condition_list:
        #     for condition in condition_list:
        #         result = callback(condition)
        #         if not result:
        #             return # stop

        # look for sub conditions
        for container in input_item.containers:
            if container.has_conditions:
                for condition in container.activation_condition.conditions:
                    result = callback(input_item, container, condition)
                    if not result:
                        return

            for action_set in container.action_sets:
                for action in action_set:
                    for condition in action.activation_condition.conditions:
                        result = callback(input_item, action, condition)
                        if not result:
                            return
                    if action.tag == "gated-axis":
                        # special handling for gated axis
                        gate_data: gremlin.gated_handler.GateData = action.gate_data
                        gate: gremlin.gated_handler.GateInfo
                        for gate in gate_data.getGates():
                            # gate containers
                            for condition, item in gate.item_data_map.items():
                                result = self._filter_conditions_input_item(item, callback, extra_data)
                                if not result:
                                    return False

                        rng: gremlin.gated_handler.RangeInfo
                        for rng in gate_data.getRanges():
                            # gate containers
                            for condition, item in rng.item_data_map.items():
                                result = self._filter_conditions_input_item(item, callback, extra_data)
                                if not result:
                                    return False

        return True

    def filter_conditions(self, callback, extra_data: dict = None):
        """filters conditions in the profile - the callback is called for every condition found in the profile"""
        for dev_guid in self.devices:
            dev = self.devices[dev_guid]
            if dev.device_type == gremlin.types.DeviceType.State:
                # state device (modeless) - special handling of state input items
                state_data = gremlin.shared_state.current_profile.state
                input_items = [state_data[key] for key in state_data]
                for item in input_items:
                    result = self._filter_conditions_input_item(item, callback, extra_data)
                    if not result:
                        return
            else:
                for mode_name in dev.modes:
                    mode_object = dev.modes[mode_name]
                    for input_type in mode_object.config:
                        for item in mode_object.config[input_type].values():
                            result = self._filter_conditions_input_item(item, callback, extra_data)
                            if not result:
                                return

    def _findInputitemAction(self, input_item, action_id) -> AbstractAction:
        """locates an action by its id in an input item"""
        for container in input_item.containers:
            for action_set in container.action_sets:
                for action in action_set:
                    if action.tag == "gated-axis":
                        # special handling for gated axis
                        gate_data: gremlin.gated_handler.GateData = action.gate_data
                        gate: gremlin.gated_handler.GateInfo
                        for gate in gate_data.getGates():
                            # gate containers
                            for condition, item in gate.item_data_map.items():
                                a = self._findInputitemAction(item, action_id)
                                if a:
                                    return a

                        rng: gremlin.gated_handler.RangeInfo
                        for rng in gate_data.getRanges():
                            # gate containers
                            for condition, item in rng.item_data_map.items():
                                a = self._findInputitemAction(item, action_id)
                                if a:
                                    return a

                    if action.id == action_id:
                        return action
        return None

    def findAction(self, action_id) -> AbstractAction:
        """gets an action in the profile by its action id"""
        for dev_guid in self.devices:
            dev = self.devices[dev_guid]
            if dev.device_type == gremlin.types.DeviceType.State:
                # state device (modeless) - special handling of state input items
                state_data = gremlin.shared_state.current_profile.state
                input_items = [state_data[key].input_item for key in state_data]
                for item in input_items:
                    action = self._findInputitemAction(item, action_id)
                    if action:
                        return action
            else:
                for mode_name in dev.modes:
                    mode_object = dev.modes[mode_name]
                    for input_type in mode_object.config:
                        for item in mode_object.config[input_type].values():
                            action = self._findInputitemAction(item, action_id)
                            if action:
                                return action
        return None

    def apply_voice(self, voice_index=None, voice_volume=None, voice_rate=None) -> int:
        """applies this voice to all profile TTS entries - returns the count of entries impacted"""

        count = 0

        if voice_index is not None or voice_volume is not None or voice_rate is not None:

            def _apply_voice_callback(action, extra_data: dict = None) -> bool:
                nonlocal count
                updated = False
                if voice_index is not None and voice_index != action.voice_index:
                    action.voice_index = voice_index
                    updated = True
                if voice_volume is not None and voice_volume != action.volume:
                    action.volume = voice_volume
                    updated = True
                if voice_rate is not None and voice_rate != action.rate:
                    action.rate = voice_rate
                    updated = True

                if updated:
                    count += 1

                return True

            self.filter_actions("text-to-speech", _apply_voice_callback)

        if count:
            # indicate the profile has to be reloaded
            el = gremlin.event_handler.EventListener()
            el.request_reload.emit()

        return count

    def convertTTSToPlaySound(self):
        """converts profile TTS entries to playsound entries - prompt the user and saves to a new profile """
        fname = self.profile_file
        if not fname or not os.path.isfile(fname):
            return False

        from gremlin.types import PlayMode
        import gremlin.tts
        import gremlin.ui.ui_common
        from PySide6 import QtWidgets

        tree = etree.parse(fname)
        root = tree.getroot()

        nodes = list(root.xpath("//text-to-speech"))
        if not nodes:
            gremlin.ui.ui_common.MessageBox(informative_text="No TTS entries found in the profile.")
            return None

        result = gremlin.ui.ui_common.ConfirmBox(informative_text ="Do you want to convert all TTS entries to lay sound entries?\nThis will save to a new profile.")
        if not result:
            return None

        # get a profile to save to
        save_fname, _ = QtWidgets.QFileDialog.getSaveFileName(None, "Save Profile As...", gremlin.shared_state.data_path, "XML files (*.xml)")
        if not save_fname:
            return None


        for node in nodes:

            # read the node
            voice_id = None
            tts = gremlin.tts.TextToSpeech()
            if "voice_id" in node.attrib:
                voice_id = node.get("voice_id")
                if voice_id.isdigit():
                    voice_id = int(voice_id)
                else:
                    voice_id = 0

                voices = tts.getVoices()
                if voices and voice_id < len(voices):
                    voice = voices[voice_id]
                    speaker = voice.name
            else:
                # get a default voice
                default_voice = next(
                    (voice for voice in self.voices if "David Desktop" in voice.name), None
                )
                speaker = default_voice.name


            if "volume" in node.attrib:
                volume = safe_read(node, "volume", int, 50)
            else:
                volume = 50  # default

            volume = gremlin.util.clamp(volume, 0, 100)
            rate = safe_read(node, "rate", int, 100)
            if rate == 0:
                rate = 100  # default
            rate = gremlin.util.clamp(
                rate, tts.rate_offset_min, tts.rate_offset_max
            )
            if "text" in node.attrib:
                text = node.get("text")
            else:
                text = None

            # clearQueue = safe_read(node, "clear-queue", bool, False)
            # _abort = safe_read(node, "abort", bool, False)
            exec_on_press = safe_read(node, "exec_on_press", bool, True)
            exec_on_release = safe_read(node, "exec_on_release", bool, False)
            # override_suppress = safe_read(node, "override-suppress", bool, False)


            # replace with new play sound node

            randomize_sound_file = True
            ptts_speed = rate
            ptts_volume = volume
            loops = 1
            playback_ms = 0
            playback_rate = 1.0
            fadein_ms = 0
            fadeout_ms = 0
            stop_previous = False
            playback_mode = PlaybackMode.RoundRobin
            mode = PlayMode.PyTTS
            auto_generate = True

            node.attrib.clear()

            node.tag = "play-sound"
            node.set("mode", PlayMode.to_string(mode))
            node.set("type", "playsound")
            node.set("randomize", safe_format(randomize_sound_file, bool))


            node.set("speaker", speaker)
            node.set("volume", safe_format(volume, int))
            node.set("text", html.escape(text))
            node.set("ptts_speed", safe_format(ptts_speed, int))
            node.set("ptts_volume", safe_format(ptts_volume, int))
            node.set("exec_on_press", safe_format(exec_on_press, bool))
            node.set("exec_on_release", safe_format(exec_on_release, bool))
            node.set("loops", safe_format(loops, int))
            node.set("playback-ms", safe_format(playback_ms, float))
            node.set("playback-rate", safe_format(playback_rate, float))
            node.set("fadein-ms", safe_format(fadein_ms, int))
            node.set("fadeout-ms", safe_format(fadeout_ms, int))
            node.set("stop-previous", safe_format(stop_previous, bool))
            node.set("playback-mode", safe_format(playback_mode.name, str))
            node.set("auto-generate", safe_format(auto_generate, bool))



        tree.write(save_fname, encoding="utf-8", xml_declaration=True, pretty_print=True)
        return save_fname


    def convertMacroToSequence(self):
        """ converts macro entries to sequence container entries """
        fname = self.profile_file
        if not os.path.isfile(fname):
            return False

        from gremlin.types import PlayMode
        import gremlin.tts
        import gremlin.ui.ui_common
        from PySide6 import QtWidgets

        tree = etree.parse(fname)
        root = tree.getroot()

        nodes = list(root.xpath("//macro"))

        if not nodes:
            gremlin.ui.ui_common.MessageBox(informative_text="No Macro entries found in the profile.")
            return None

        result = gremlin.ui.ui_common.ConfirmBox(informative_text ="Do you want to convert all Macro entries to sequence containers??\nThis will save to a new profile.")
        if not result:
            return None

        # get a profile to save to
        save_fname, _ = QtWidgets.QFileDialog.getSaveFileName(None, "Save Profile As...", gremlin.shared_state.data_path, "XML files (*.xml)")
        if not save_fname:
            return None

        macro_actions = []
        def _apply_macro(action, extra_data: dict = None) -> bool:
            nonlocal macro_actions
            macro_actions.append(action)
            return True

        # get all macro entries in the current profile
        self.filter_actions("macro", _apply_macro)



        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        container_plugins = gremlin.plugin_manager.ContainerPlugins()



        from action_plugins.macro import Macro
        from action_plugins.map_to_vjoy import VjoyRemap
        from action_plugins.map_to_keyboard_ex import MapToKeyboardEx
        from action_plugins.map_to_mouse_ex import MapToMouseEx
        from action_plugins.map_to_state import MapToState
        from container_plugins.sequence import SequenceContainer
        import gremlin.macro


        action : Macro
        input_item_map = {}
        for action in macro_actions:
            input_item = action.input_item
            if input_item not in input_item_map:
                container : SequenceContainer = container_plugins.get_class("Sequence")(input_item=input_item)
                input_item_map[input_item] = container
                input_item.containers.append(container)
            else:
                container = input_item_map[input_item]


            action_set = ActionSet()
            container.add_action_set(action_set)
            for macro_action in action.sequence:
                if isinstance(macro_action, gremlin.macro.JoystickAction):
                    new_action = VjoyRemap(container)
                    new_action.vjoy_input_id = macro_action.input_id
                    new_action.vjoy_value = macro_action.value
                    match macro_action.input_type:
                        case InputType.JoystickAxis:
                            new_action.vjoy_axis = macro_action.axis
                        case InputType.JoystickButton:
                            new_action.vjoy_button = macro_action.button
                    action_set.add_action(new_action)
                elif isinstance(macro_action, gremlin.macro.KeyAction):
                    new_action = MapToKeyboardEx(container)
                    key = macro_action.key
                    new_action.keys.append(key)
                    new_action.mode = KeyboardOutputMode.Hold
                    action_set.add_action(new_action)
                elif isinstance(macro_action, gremlin.macro.MouseButtonAction):
                    new_action = MapToKeyboardEx(container)
                    button : MouseButton = macro_action.button
                    key =  key = gremlin.keyboard.key_from_mousebutton(button.value)
                    new_action.keys.append(key)
                    action_set.add_action(new_action)
                elif isinstance(macro_action, gremlin.macro.MouseMotionAction):
                    new_action = MapToMouseEx(container)
                    x = macro_action.x
                    y = macro_action.y
                    new_action.mouse_x = x
                    new_action.mouse_y = y
                    action_set.add_action(new_action)
                elif isinstance(macro_action, gremlin.macro.StateAction):
                    new_action = MapToState(container)
                    state = macro_action.state
                    new_action.state = state
                    action_set.add_action(new_action)








""" END PROFILE """


class ProfileModeNode:
    """mode object - represents the configuration of the mode of a single device."""

    # list of input types to save for each mode
    SaveInputTypes = [
        InputType.JoystickAxis,
        InputType.JoystickButton,
        InputType.JoystickHat,
        InputType.Keyboard,
        InputType.KeyboardLatched,
        InputType.OpenSoundControl,
        InputType.Midi,
        InputType.ModeControl,
        InputType.OctaviIfr1,
    ]

    def __init__(self, name: str = None, system: bool = None, parent: ProfileDeviceNode = None):
        self._config = {}
        self.id = get_guid()
        self.parent = parent
        self.system = system if system is not None else False
        self.inherit = False
        self._name: str = name  # mode name

    def load(self, profile: Profile, device_guid: dinput.GUID, name: str, inherit: str = None, system=False, parent: ProfileDeviceNode = None):
        assert isinstance(profile, Profile), "invalid profile"
        assert isinstance(device_guid, dinput.GUID), "invalid id"
        assert isinstance(inherit, str) if inherit is not None else True, "invalid inherit mode"
        self._name = name
        self.inherit = inherit  # name of the mode we inherit properties from
        self._name = name  # name of the current mode
        self.system = system
        if parent is not None:
            self.parent = parent

    def getInputItem(self, input_type: InputType, input_id):
        """gets the input item for a given entry"""
        if input_type not in self._config:
            self._config[input_type] = {}
        input_id_key = self.registry.getInputIdKey(input_id)
        if input_id_key not in self._config[input_type]:
            # syslog.info(
            #     f"input type: [{input_type.name}] create input id [{input_id_key}] mode node id: [{self.id}] mode name: [{self.name}]  device id: [{self.parent.id}] device name: [{self.parent.name}] profile id: [{self.profile.id}]"
            # )
            self._config[input_type][input_id_key] = None
        return self._config[input_type][input_id_key]

    def hasInputItems(self, has_mappings=False):
        """true if the mode node contains defined inputs
        :param has_mappings: optional, if true checks for the inputs to have mappings defined instead of just input definitions
        """
        for input_type in self._config:
            if self._config[input_type]:
                if has_mappings:
                    for input_item in self._config[input_type]:
                        if input_item and len(input_item.containers) > 0:
                            return True
                else:
                    return True
        return False

    def addInputItem(self, input_item: InputItem):
        """stores the input item in this mode node"""
        assert input_item is not None, "invalid input item"
        input_type = input_item.input_type
        input_id = input_item.input_id
        # if input_id == gremlin.ui.mode_device.ModeInputModeType.ModeProfileStart:
        #     pass
        input_id_key = self.registry.getInputIdKey(input_id)
        assert input_id is not None, "invalid input id"
        mode_config = self.getConfig(input_type)
        mode_config[input_id_key] = input_item
        # syslog.info(
        #     f"store input item in mode: input item id: {Ansi.YELLOW}[{input_item.id}]{Ansi.RESET} input type: [{input_type.name}] input id {Ansi.GREEN}[{input_id_key}]{Ansi.RESET} mode node id: [{self.id}] mode name: [{self.name}]  device id: [{self.parent.id}] device name: [{self.parent.name}] profile id: [{self.profile.id}]"
        # )

    def getConfig(self, input_type: InputType) -> dict:
        """gets the configuration list for a given input type"""
        assert isinstance(input_type, InputType), f"invalid input type: {input_type}"
        if input_type not in self._config:
            self._config[input_type] = {}
        return self._config[input_type]

    @property
    def profile(self) -> Profile:
        return self.parent.profile

    @property
    def config(self) -> TriggerDict:
        return self._config

    @property
    def device_guid(self) -> dinput.GUID:
        """device GUID"""
        if self.parent:
            return self.parent.device_guid
        return None

    @property
    def device_type(self) -> DeviceType:
        """device type"""
        if self.parent:
            return self.parent.device_type
        return None

    @property
    def registry(self) -> ProfileRegistry:
        return self.profile.registry

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str):
        self._name = value.strip() if value else ""

    @property
    def parent_mode(self) -> ProfileModeNode:
        """parent mode name, None if the root mode"""
        if self.inherit:
            if self.inherit in self.parent.modes:
                return self.parent_mode.modes[self.inherit]
        return None

    @property
    def is_root(self) -> bool:
        """true if the mode is a root level mode"""
        return self.inherit is None

    def setName(self, value: str):
        self._name = value.strip() if value else ""

    @property
    def hasMappings(self) -> bool:
        """True if the mode contains inputs that are mapped to a container"""
        for input_type in self._config:
            for input_item in self._config[input_type].values():
                if input_item.containers:
                    return True

        return False

    def from_xml(self, node, data=None, extra_data=None):
        """Parses the XML mode data.

        :param node XML node to parse
        """
        from gremlin.base_profile import InputItem
        import gremlin.ui.state_device
        import gremlin.ui.keyboard_device
        import gremlin.ui.midi_device
        import gremlin.ui.osc_device
        import gremlin.joystick_handling
        import gremlin.ui.mode_device

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_ui
        # verbose = True
        assert node.tag == "mode", f"not a valid mode entry - offending line: {node.sourceline}"

        if not self._name:
            mode_name = html.unescape(safe_read(node, "name", str, ""))
            mode_name = mode_name.strip()
            self._name = mode_name
        else:
            mode_name = self._name

        if "system" in node.attrib:
            self.system = safe_read(node, "system", bool, False)
        else:
            self.system = False

        if "guid" in node.attrib:
            self.id = normalize_guid(node.get("guid"))  # mode node ID

        device_guid = self.device_guid
        assert device_guid is not None, "parenting problem: mode should be parented to a valid device before reading from XML"
        device = gremlin.joystick_handling.getDevice(device_guid)

        # parent mode, optional
        if "inherit" in node.attrib:
            inherit_value = html.unescape(node.get("inherit"))
            # Older versions serialized inherit as a bool, corrupting the parent
            # mode name into the literal "True"/"False". Treat these as "no
            # inheritance" rather than failing validation downstream.
            if inherit_value in ("True", "False"):
                self.inherit = None
            else:
                self.inherit = inherit_value
        else:
            self.inherit = None

        child: etree.Element
        index = 0  # sorting index - order read in from the profile

        for child in node:
            # convert to the appropriate input item based on type
            input_item = None
            try:
                if child.tag == "input":
                    # walk the chain for the input type
                    parent_node = child.getparent()
                    while parent_node is not None and "type" not in parent_node.attrib:
                        parent_node = parent_node.getparent()
                    input_type = InputType.to_enum(parent_node.get("type"))
                else:
                    input_type = InputType.to_enum(child.tag)

                match input_type:
                    case InputType.State:
                        item = gremlin.ui.state_device.StateInputItem()
                    case InputType.Keyboard | InputType.KeyboardLatched:
                        item = gremlin.ui.keyboard_device.KeyboardInputItem(self)
                    case InputType.OpenSoundControl:
                        item = gremlin.ui.osc_device.OscInputItem(self)
                    case InputType.Midi:
                        item = gremlin.ui.midi_device.MidiInputItem(self)
                    case InputType.JoystickAxis | InputType.JoystickButton | InputType.JoystickHat:
                        item = InputItem(mode_node=self, input_type=input_type)
                    case InputType.ModeControl:
                        item = gremlin.ui.mode_device.ModeInputItem(self)
                        # syslog.info(
                        #     f"load mode input id: input item id: {Ansi.YELLOW}[{item.id}]{Ansi.RESET} mode name: [{self.name}] input id: {Ansi.GREEN}[{item.input_id.name}/{item.input_id}]{Ansi.RESET}"
                        # )
                        # pass
                    case _:
                        message = f"XML: Parse Mode: unhandled input type [{input_type}] - offending line: [{child.sourceline}]"
                        syslog.error(message)
                        syslog.error(f"\t{etree.tostring(child, encoding='unicode')}]")
                        continue

                if extra_data is None:
                    extra_data = {}
                extra_data["input_type"] = input_type

                item.from_xml(child, item, extra_data)  # send owner item to sub components as the data member

                assert item.input_id is not None, f"XML: invalid input id on load: source line: [{child.sourceline}] xml: [{etree.tostring(child, encoding='unicode')}]"

                input_item = self.getInputItem(item.input_type, item.input_id)


                if input_item is not None:
                    input_item.setContainers(item.containers)

                if input_item is None:
                    input_item = item
                    self.addInputItem(item)
                    self.profile.registry.registerInputItem(input_item = input_item,
                                                            device_guid = self.device_guid,
                                                            input_type = input_type,
                                                            input_id = item.input_id)

                if __debug__:
                    test = self.profile.registry.getInputItem(device_guid=self.device_guid, mode_name=self.name, input_type=input_type, input_id=item.input_id)
                    assert test == input_item

            except Exception as e:
                syslog.error(f"XML: unknown input type: [{node.tag}] - offending line: [{node.sourceline}]  contents: [{etree.tostring(node, encoding='unicode')}")
                syslog.error(f"\texception occurred: {str(e)}\n{traceback.format_exc()}")

            # sorting index
            if input_item is not None:
                input_item.index = index
                if verbose:
                    syslog.info(
                        f"Profile MODE XML: load [{index}] input item id: {Ansi.YELLOW}[{input_item.id}]{Ansi.RESET} [{input_item.display_name}] input id: \x1b[1;32m[{input_item.input_id}]\033[0m containers: [{input_item.containers.count()}] mode node id: [{self.id}] mode: [{self.name}] device: [{device.name}] device id: [{self.parent.id}] input type: [{input_type.name}] input item: id [{input_item.id}] [{input_item.input_id.display_name if hasattr(input_item.input_id, 'display_name') else input_item.input_id}] profile id: [{self.profile.id}]"
                    )
            # else:
            #     syslog.error(f"Profile MODE XML: failed to load input item for index [{index}] in mode [{self.name}] for device [{device.name}]")
            #     syslog.error(f"Offending line: [{node.sourceline}]")
            index += 1

    def to_xml(self):
        """Generates XML code for this DeviceConfiguration.

        :return XML node representing this object's data
        """
        node = etree.Element("mode")
        node.set("name", safe_format(html.escape(self.name), str))
        if self.system:
            node.set("system", safe_format(True, bool))

        # inherit is the NAME of the parent mode (a string) or None/False for
        # no inheritance. It defaulted to bool and was serialized as bool, which
        # turned the parent mode name into the literal "True" and corrupted the
        # profile. Only write it when it is an actual mode-name string.
        if isinstance(self.inherit, str):
            node.set("inherit", safe_format(self.inherit, str, escape=True))

        node.set("guid", self.id)  # unique mode ID

        input_types = ProfileModeNode.SaveInputTypes
        include = False
        for input_type in input_types:
            item_list = list(item for item in self._config[input_type].values() if item is not None) if input_type in self._config else []
            if item_list:
                item_list.sort(key=lambda item: item.index)  # sort by index
                # item_list = [item for item in item_list if item.description or item.containers]
            if item_list and input_type in (InputType.OpenSoundControl, InputType.Keyboard, InputType.KeyboardLatched):
                pass
            for input_item in item_list:
                # if item.is_valid_for_save():
                item_node = input_item.to_xml()
                # _index = input_item.index
                # syslog.info(f"xml write [{index}] = [{input_item.input_id.display_name if hasattr(input_item.input_id, "display_name") else input_item.input_id}]")

                # include the item in the xml if it has attributes we need to save to the profile
                do_include = False
                if input_item.locked:
                    do_include = True
                depth = gremlin.util.xmlNodeDepth(item_node)
                match input_item.device_type:
                    case DeviceType.Maestro | DeviceType.Joystick | DeviceType.VJoy:
                        if input_item.description or depth > 1:
                            do_include = True
                    case DeviceType.OctaviIFR1:
                        do_include = depth > 1
                    case DeviceType.ModeControl:
                        do_include = depth > 1
                    case _:
                        # other nodes = ok
                        do_include = True

                if do_include:
                    # syslog.info(f"Mode: {self.name} include input: {item.input_name}")
                    node.append(item_node)
                    include = True

        if include:
            return node
        # syslog.info(f"Mode: {self.name} exclude XML:")
        # syslog.info(etree.tostring(node, pretty_print = True))
        # syslog.info("----")
        return None

    def delete_data(self, input_type, input_id):
        """Deletes the data associated with the provided
        input item entry.

        :param input_type the type of the input
        :param input_id the index of the input
        """
        registry = ProfileRegistry()
        input_id_key = registry.getInputIdKey(input_id)
        if input_id_key in self._config[input_type]:
            del self._config[input_type][input_id_key]

    def set_data(self, input_type, input_id, data):
        """Sets the data of an InputItem.

        :param input_type the type of the InputItem
        :param input_id the id of the InputItem
        :param data the data of the InputItem
        """
        assert input_type in self._config
        registry = ProfileRegistry()
        input_id_key = registry.getInputIdKey(input_id)
        self._config[input_type][input_id_key] = data

    def get_data(self, input_type, input_id):

        return self.getInputItem(input_type, input_id)

    def has_data(self, input_type, input_id):
        """Returns True if data for the given input exists, False otherwise.

        :param input_type the type of the InputItem
        :param input_id the id of the InputItem
        :return True if data exists, False otherwise
        """
        registry = ProfileRegistry()
        input_id_key = registry.getInputIdKey(input_id)
        return input_id_key in self._config[input_type]

    def all_input_items(self):
        for input_type in self._config.values():
            for input_item in input_type.values():
                yield input_item

    def __str__(self):
        return f"ProfileModeNode: id [{self.id}] name: [{self.name}] config size: [{len(self._config)}] contents: [{self._config}] ]"


class Plugin:
    """Custom module."""

    def __init__(self, parent):
        self.parent = parent
        self.file_name = None
        self.instances = []

    def from_xml(self, node, data=None, extra_data=None):
        self.file_name = safe_read(node, "file-name", str, None)
        for child in node.iter("instance"):
            instance = PluginInstance(self)
            instance.from_xml(child, data)
            self.instances.append(instance)

    def to_xml(self):
        node = etree.Element("plugin")
        node.set("file-name", safe_format(self.file_name, str))
        for instance in self.instances:
            if instance.is_configured():
                node.append(instance.to_xml())
        return node


class PluginInstance:
    """Instantiation of a custom module with its own set of parameters."""

    def __init__(self, parent):
        self.parent = parent  # parent holds the module instance
        self.name = None
        self.variables = {}

    def is_configured(self):

        # get the configuration flag for edit mode
        if not gremlin.shared_state.is_running:
            partial_plugin_ok = gremlin.config.Configuration().partial_plugin_save
            if partial_plugin_ok:
                return True
        for var in [var for var in self.variables.values() if not var.is_optional]:
            if not var.is_configured:
                return False
        return True

    def has_variable(self, name):
        return name in self.variables

    def set_variable(self, name : str, variable : PluginVariable):
        syslog.info(f"Plugin: set variable {name} to variable {variable} value: {variable.value}")
        self.variables[name] = variable

    def get_variable(self, name : str):
        verbose = gremlin.config.Configuration().verbose_mode_plugin
        if name not in self.variables:
            var = PluginVariable(self)
            var.name = name
            self.variables[name] = var
            if verbose:
                syslog.info(f"Plugin: get variable {name} not found, creating new variable with default value: {var.value}")
        else:
            if verbose:
                syslog.info(f"Plugin: get variable {name} found with value: {self.variables[name].value}")

        return self.variables[name]

    def from_xml(self, node, data=None, extra_data=None):
        verbose = gremlin.config.Configuration().verbose
        self.name = safe_read(node, "name", str, "")
        for child in node.iter("variable"):
            variable = PluginVariable(self)
            variable.from_xml(child, data)
            self.variables[variable.name] = variable
            if verbose:
                log = syslog
                log.info(str(variable))

    def to_xml(self):
        node = etree.Element("instance")
        node.set("name", safe_format(self.name, str))
        for variable in self.variables.values():
            variable_node = variable.to_xml()
            if variable_node is not None:
                node.append(variable_node)
        return node


class PluginVariable:
    """A single variable of a custom module instance."""

    def __init__(self, parent):
        self.parent = parent
        self.name = None
        self._type = None
        self._value = None
        self.is_optional = False

    def duplicate(self):
        dup = PluginVariable(self.parent)
        dup.name = self.name
        dup._type = self._type
        dup._value = self._value
        dup.is_optional = self.is_optional
        return dup

    @property
    def type(self) -> PluginVariableType:  # noqa: F821
        return self._type

    @type.setter
    def type(self, value: PluginVariableType):  # noqa: F821
        if value is None:
            pass
        self._type = value

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        if v is None:
            pass
        self._value = v

    @property
    def is_configured(self):
        """true if the variable is configured"""
        if self.type is None or self.name is None:
            return False
        if self.type == PluginVariableType.PhysicalInput:
            if self.value and "device_id" in self.value:
                return self.value["device_id"] is not None
            return False

        if self.type != PluginVariableType.String:
            return self.value is not None

        return True

    def from_xml(self, node, data=None, extra_data=None):
        """save user plugin variable data"""
        self.name = safe_read(node, "name", str, "")
        self.type = PluginVariableType.to_enum(safe_read(node, "type", str, "String"))
        self.is_optional = read_bool(node, "is-optional")

        # Read variable content based on type information
        if self.type == PluginVariableType.Int:
            value = safe_read(node, "value", str, "none")
            if value == "none":
                self.value = 0
            else:
                self.value = int(value)
        elif self.type == PluginVariableType.Float:
            value = safe_read(node, "value", str, "none")
            if value == "none":
                self.value = 0
            else:
                self.value = float(value)
        elif self.type == PluginVariableType.Selection:
            self.value = safe_read(node, "value", str, "")
        elif self.type == PluginVariableType.String:
            self.value = safe_read(node, "value", str, "")
        elif self.type == PluginVariableType.Bool:
            self.value = read_bool(node, "value", False)
        elif self.type == PluginVariableType.Mode:
            self.value = safe_read(node, "value", str, "")
        elif self.type == PluginVariableType.PhysicalInput:
            if "device-guid" not in node.attrib:
                # partial data save
                self.value = {
                    "device_id": None,
                    "device_name": "",
                    "input_id": None,
                    "input_type": None,
                }
            else:
                self.value = {
                    "device_id": parse_guid(node.attrib["device-guid"]),
                    "device_name": safe_read(node, "device-name", str, ""),
                    "input_id": safe_read(node, "input-id", int, 1),
                    "input_type": InputType.to_enum(safe_read(node, "input-type", str, "")),
                }

        elif self.type == PluginVariableType.VirtualInput:
            if "vjoy-id" not in node.attrib:
                # partial data save
                self.value = {"device_id": None, "input_id": None, "input_type": None}
            else:
                self.value = {
                    "device_id": safe_read(node, "vjoy-id", int, 1),
                    "input_id": safe_read(node, "input-id", int, 1),
                    "input_type": InputType.to_enum(safe_read(node, "input-type", str, "")),
                }

    def to_xml(self):
        """read user plugin saved variable data"""

        node = etree.Element("variable")
        node.set("name", safe_format(self.name, str))
        node.set("type", PluginVariableType.to_string(self.type))
        node.set("is-optional", safe_format(self.is_optional, bool, str))

        # Write out content based on the type
        if self.type in [
            PluginVariableType.Int,
            PluginVariableType.Float,
            PluginVariableType.Mode,
            PluginVariableType.Selection,
            PluginVariableType.String,
        ]:
            node.set("value", "none" if self.value is None else str(self.value))
        elif self.type == PluginVariableType.Bool:
            value = False if self.value is None else self.value
            node.set("value", "1" if value else "0")
        elif self.type == PluginVariableType.PhysicalInput:
            if self.value is not None:
                device_id = self.value.get("device_id", None)
                if device_id:
                    node.set("device-guid", write_guid(device_id))
                    node.set("device-name", safe_format(self.value["device_name"], str))
                    node.set("input-id", safe_format(self.value["input_id"], int))
                    node.set("input-type", InputType.to_string(self.value["input_type"]))
        elif self.type == PluginVariableType.VirtualInput:
            if self.value is not None:
                node.set("vjoy-id", safe_format(self.value["device_id"], int))
                node.set("input-id", safe_format(self.value["input_id"], int))
                node.set("input-type", InputType.to_string(self.value["input_type"]))

        return node

    def __str__(self):
        return f"Plugin variable: name: {self.name}  type: {self.type} value: {self.value}"


class ProfileOptionsData:
    """data block returned by the get_profile_data function"""

    def __init__(self):
        self.mode_list = []
        self.default_mode = None
        self.start_mode = None
        self.force_numlock_off = True
        self.restore_last = False


class ProfileMapItem:
    """holds a mapping of a profile xml to an exe"""

    def __init__(self, profile=None, process=None):
        self._profile = profile
        self._process = process
        self._modes = []
        self._default_mode = None  # default mode for the profile (user defined) - if not set - this is the first root mode in the profile
        self._last_mode = None  # last moded used by the profile (start mode)
        self._restore_mode_on_auto_activate = False
        self._index = -1
        self._warning = None
        self._valid = True  # assume valid
        # self._force_numlock_off = True
        self._data = None
        self._update()

    @property
    def profile(self):
        return self._profile if self._profile else ""

    @profile.setter
    def profile(self, value):
        if value:
            # uniformly store paths
            value = value.replace("\\", "/").lower().strip()
        self._profile = value

    @property
    def process(self):
        return self._process if self._process else ""

    @process.setter
    def process(self, value):
        if value:
            # uniformly store paths
            value = value.replace("\\", "/").lower().strip()
        self._process = value

    @property
    def index(self):
        return self._index

    @index.setter
    def index(self, value):
        self._index = value

    @property
    def restore_last_mode_on_auto_activate(self) -> bool:
        """true if the profile has the restore last used mode flag set"""
        return self._restore_mode_on_auto_activate

    @restore_last_mode_on_auto_activate.setter
    def restore_last_mode_on_auto_activate(self, value):
        self._restore_mode_on_auto_activate = value
        self.save()

    @property
    def default_mode(self) -> str:
        """profile default mode (this is the startup mode unless the option is to restore a previously used mode)"""
        return self._default_mode

    @default_mode.setter
    def default_mode(self, value):
        self._default_mode = value

    @property
    def last_mode(self) -> str:
        """last mode used by the profile"""
        return self._last_mode

    @last_mode.setter
    def last_mode(self, value):
        self._last_mode = value

    def _get_profile_data(self) -> ProfileOptionsData:
        """gets the list of profile modes in a given profile
        :returns tuple (mode_list, default_mode, last_mode, restore_mode_flag)
        """

        mode_list = set()  # avoids duplications as some nodes may have duplicate mode info when parsing
        default_mode = None
        restore_last = None
        start_mode = None

        current_profile: Profile = gremlin.shared_state.current_profile
        profile = self.profile
        force_numlock_off = True
        pd = ProfileOptionsData()

        if profile and current_profile:
            if current_profile.profile_file == profile:
                # current profile loaded - use that profile data since it's loaded and changes may not be saved yet to XML
                pd.mode_list = current_profile.get_modes()
                pd.default_mode = current_profile.get_default_start_mode()
                pd.start_mode = current_profile.get_start_mode()
                pd.restore_last = current_profile.get_restore_mode()
                pd.force_numlock_off = current_profile.get_force_numlock()
                return pd

            # profile not loaded - grab the info from the profile xml
            if os.path.isfile(profile):
                try:
                    parser = etree.XMLParser(remove_blank_text=True)
                    tree = etree.parse(profile, parser)
                    for element in tree.xpath("//mode"):
                        mode = element.get("name")
                        mode_list.add(mode)
                    mode_list = list(mode_list)

                    for element in tree.xpath("//profile"):
                        # <profile version="10" start_mode="Default" restore_last="True">
                        if not default_mode:
                            default_mode = safe_read(
                                element,
                                "default_mode",
                                str,
                                mode_list[0] if mode_list else "",
                            )
                        if not start_mode:
                            start_mode = safe_read(
                                element,
                                "start_mode",
                                str,
                                mode_list[0] if mode_list else "",
                            )
                        restore_last = safe_read(element, "restore_last", bool, False)
                        force_numlock_off = safe_read(element, "force_numlock", bool, True)

                    if restore_last is not None:
                        for element in tree.xpath("//startup-mode"):
                            start_mode = element.text
                            break

                    if restore_last is not None:
                        restore_last = False  # default value

                    pd.mode_list = mode_list
                    pd.default_mode = default_mode
                    pd.start_mode = start_mode
                    pd.restore_last = restore_last
                    pd.force_numlock_off = force_numlock_off

                except Exception as err:
                    syslog.error(f"PROC MAP: Unable to open profile mapping: {profile}:\n")
                    syslog.error(f"{err}\n{traceback.format_exc()}")

        return pd

    def save(self):
        """saves default and restore mode flags to the profile xml"""

        profile = self.profile
        if not self._last_mode:
            self._last_mode = self._default_mode

        current_profile: Profile = gremlin.shared_state.current_profile
        if not current_profile:
            # nothing to save
            return
        if compare_path(current_profile.profile_file, profile):
            current_profile.set_restore_mode(self._restore_mode_on_auto_activate)
            if self._default_mode:
                current_profile.set_start_mode(self._default_mode)
            # current_profile.set_force_numlock(self._force_numlock_off)
            current_profile.save()

            return

        if os.path.isfile(profile):
            # write the xml
            try:
                parser = etree.XMLParser(remove_blank_text=True)
                tree = etree.parse(profile, parser)
                for element in tree.xpath("//profile"):
                    element.set("restore_last", str(self._restore_mode_on_auto_activate))
                    if self._default_mode:
                        element.set("default_mode", self._default_mode)
                    element.set("start_mode", self.last_mode)
                    # element.set("force_numlock", str(self._force_numlock_off))
                    profile_node = element
                    break

                settings_node = None
                startup_node = None
                for element in tree.xpath("//settings"):
                    settings_node = element
                    break

                for element in tree.xpath("//settings/startup-mode"):
                    startup_node = element
                    break

                if startup_node is None:
                    # add the settings node

                    if settings_node is None:
                        settings_node = etree.SubElement(profile_node, "settings")

                    startup_node = etree.SubElement(settings_node, "startup-mode")
                    startup_node.text = str(self._default_mode)

                tree.write(profile, pretty_print=True, xml_declaration=True, encoding="utf-8")

            # save the profile map

            except Exception as err:
                syslog.error(f"PROC MAP: Unable to open profile mapping: [{profile}]:")
                syslog.error(f"{err}\n{traceback.format_exc()}")

    def _update(self):
        pd = self._get_profile_data()
        self._data = pd
        self._modes = pd.mode_list
        self._default_mode = pd.default_mode
        self._last_mode = pd.start_mode
        self._restore_mode_on_auto_activate = pd.restore_last
        # self._force_numlock_off = pd.force_numlock_off

    @property
    def valid(self):
        return self._valid

    @valid.setter
    def valid(self, value):
        self._valid = value

    @property
    def warning(self):
        return self._warning

    @warning.setter
    def warning(self, value):
        self._warning = value

    def __str__(self):
        return f"ProfileItem: process: {self.process}  profile: {self.profile}  default mode: {self.default_mode}  valid: {self.valid}"


@SingletonDecorator
class ProfileMap:
    """manages the profile to process maps"""

    def __init__(self):
        self._items = []  # list of items
        self._process_map = {}  # mapps process to ProcessMapItem
        self._valid = True
        self.load_profile_map()  # load the existing map

    def get_profile_map_file(self):
        """gets the profile file name"""
        return os.path.join(gremlin.shared_state.data_path, "profile_map.xml")

    def load_profile_map(self):
        """loads the mapping of profile xmls to processes"""
        verbose = gremlin.config.Configuration().verbose_mode_inputs
        fname = self.get_profile_map_file()
        self._items = []
        if os.path.isfile(fname):
            # read the xml
            try:
                parser = etree.XMLParser(remove_blank_text=True)
                tree = etree.parse(fname, parser)
                for element in tree.xpath("//map"):
                    process = element.get("process")
                    profile = element.get("profile")
                    restore = safe_read(element, "restore_mode", bool, False)
                    item = gremlin.base_profile.ProfileMapItem(profile, process)
                    if "startup_mode" in element.attrib:
                        mode = element.get("startup_mode")
                        item.default_mode = mode
                        item.restore_last_mode_on_auto_activate = restore

                    self._items.append(item)
                    if verbose:
                        syslog.info(f"PROC MAP: Registered mapping: {process} -> {profile}")
            except Exception as err:
                syslog.error(f"PROC MAP: Unable to open profile mapping: [{fname}]")
                syslog.error(f"{err}\n{traceback.format_exc()}")
        self._update()

    def save_profile_map(self):
        gremlin.util.InvokeUiMethod(self._save_profile_map_ui)

    def _save_profile_map_ui(self):
        """saves the profile configuration"""
        self.validate()
        fname = self.get_profile_map_file()
        if os.path.isfile(fname):
            # blitz
            os.unlink(fname)

        root = etree.Element("mappings")
        for item in self._items:
            if item.valid:
                # print (f"Saving item: process: {item.process} profile: {item.profile}")
                etree.SubElement(
                    root,
                    "map",
                    profile=item.profile,
                    process=item.process,
                    startup_mode=item.default_mode,
                    restore_mode=str(item.restore_last_mode_on_auto_activate),
                )

        try:
            # save the file
            tree = etree.ElementTree(root)
            tree.write(fname, pretty_print=True, xml_declaration=True, encoding="utf-8")
            syslog.info(f"PROC MAP: saved preferences to {fname}")

        except Exception as err:
            syslog.error(f"PROC MAP: failed to save preferences to [{fname}]")
            syslog.error(f"{err}\n{traceback.format_exc()}")

    @property
    def profile_map(self):
        return self._profile_map

    def register(self, item):
        """registers a new item"""
        self._items.append(item)
        if item.valid:
            self._process_map[item.process] = item
        self._update()

    def get_map(self, process) -> ProfileMapItem:
        """returns the gremlin profile"""
        process = process.replace("\\", "/").lower().strip()
        if process in self._process_map:
            return self._process_map[process]
        return None

    def _update(self):
        """updates the process map from the item registrations"""
        item_list = [item for item in self._items if item.process and item.profile]
        self._process_map = {}
        for item in item_list:
            self._process_map[item.process] = item

    def sort_profile(self):
        """sorts the items by profile"""
        self._items.sort(key=lambda x: (os.path.basename(x.profile), os.path.basename(x.process)))

    def sort_process(self):
        """sorts items by process"""
        self._items.sort(key=lambda x: (os.path.basename(x.process), os.path.basename(x.profile)))

    def get_process_list(self):
        """gets a list of mapped processes"""
        return list(self._process_map.keys())

    def items(self):
        """gets a list of registered process to profile map items"""
        return self._items

    def remove(self, item):
        """removes a mapping"""
        if item in self._items:
            self._items.remove(item)

    def validate(self):
        """validates the mappings"""

        # validate the processes are unique
        process_list = []
        self._valid = True  # assume valid
        item: ProfileMapItem
        for item in self._items:
            valid = True
            warning = None
            if item.process in process_list:
                valid = False
                warning = f"Process '{os.path.basename(item.process)}' is duplicated - a process can only have one mapping."
                self._valid = False
            else:
                process_list.append(item.process)

            if not (item.process or item.profile):
                valid = False
                warning = "Mapping incomplete"
                self._valid = False

            pd = item._get_profile_data()
            if pd.mode_list:
                if item.default_mode is not None and item.default_mode not in pd.mode_list:
                    valid = False
                    warning = f"Startup mode '{item.default_mode}' does not exist for this profile"
                    self._valid = False

            # print (f"Validation: Item process: {item.process} profile: {item.profile} valid: {valid}")
            item.valid = valid
            item.warning = warning

    @property
    def valid(self):
        return self._valid



