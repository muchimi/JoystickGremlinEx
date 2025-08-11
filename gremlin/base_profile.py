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
from collections import namedtuple
import codecs
import collections
import os
import copy
import logging
import time

#import gremlin.base_classes

import gremlin.keyboard
import gremlin.profile
import gremlin.shared_state

import gremlin.ui.keyboard_device

import gremlin.ui.mode_device
from gremlin.util import *
from gremlin.input_types import InputType
from gremlin.types import *
from lxml import etree
from gremlin.types import DeviceType
from gremlin.plugin_manager import ContainerPlugins
from gremlin.base_conditions import *
from gremlin.base_buttons import VirtualAxisButton, VirtualHatButton
from gremlin.input_types import InputType
from gremlin.plugin_manager import ActionPlugins, ContainerPlugins
import gremlin.joystick_handling
import gremlin.profile
import gremlin.input_devices
import gremlin.plugin_manager
import gremlin.shared_state
from gremlin.singleton_decorator import SingletonDecorator
import gremlin.util
import gremlin.ui.ui_common
import anytree
from anytree import Node
from PySide6.QtWidgets import QMessageBox
import gremlin.profile_graph
import gremlin.execution_graph
import gremlin.base_classes
import gremlin.base_profile
import gremlin.config
import gremlin.curve_handler
import gremlin.event_handler

syslog = logging.getLogger("system")



@SingletonDecorator
class ProfileImportData():
    def __init__(self):
        self.used_ids = {} # used at load time to validate there are no duplicate container/action IDs in the profile

_import_data = ProfileImportData()

# Data struct representing profile information of a device
ProfileDeviceInformation = collections.namedtuple(
    "ProfileDeviceInformation",
    ["device_guid", "name", "containers", "conditions", "merge_axis"]
)

CallbackData = collections.namedtuple("ContainerCallback", ["callback", "event"])


def _get_input_item(parent):
    ''' gets the InputItem parent hierarchy if it exists '''
    while parent is not None:
        if isinstance(parent, InputItem):
            break
        if isinstance(parent, gremlin.profile_graph.ProfileInputNode):
            return parent.input_item
        if hasattr(parent,"parent"):
            parent = parent.parent
        else:
            parent = None
           
    if parent is not None:
        return parent
    return None

def _is_curve_tag(tag):
     ''' true if a curve tag'''
     if tag:
        return tag.casefold() in ("curve-data","response-curve","response-curve-ex")
     return False

class ABCMetaQObject(ABCMeta, type(QtCore.QObject)):
    pass


class ProfileData(QtCore.QObject, metaclass=ABCMetaQObject):

    """Base class for all items holding profile data.

    This is primarily used for containers and actions to represent their
    configuration and to easily load and store them.
    """

    def __init__(self, parent):
        """Creates a new instance.

        :param: parent the parent item of this instance in the profile tree (type: InputItem)
        """

        super().__init__()
        assert parent is not None
        self.code = None
        self._id = gremlin.util.get_guid(no_brackets=True)
        self._input_item : gremlin.base_profile.InputItem = _get_input_item(parent)
        
        
        generic_icon = os.path.join(os.path.dirname(__file__),"generic.png")
        if os.path.isfile(generic_icon):
            self._generic_icon = generic_icon
        else:
            self._generic_icon = None

        # reported device type to actions so they can configure themselves to a different hardware input type if needed
        if isinstance(parent, ProfileData):
            self.override_input_type = parent.override_input_type
            self.override_input_id = parent.override_input_id
        else:
            self.override_input_type = None
            self.override_input_id = None


    def icon(self):
        ''' gets the default icon'''
        from gremlin.util import get_generic_icon
        return get_generic_icon()


    def from_xml(self, node, data = None):
        """Initializes this node's values based on the provided XML node.

        :param node the XML node to use to populate this instance
        """
        self._parse_xml(node, data)

    def to_xml(self):
        """Returns the XML representation of this instance.

        :return XML representation of this instance
        """
        return self._generate_xml()

    def is_valid(self):
        """Returns whether or not an instance is fully specified.
        
        :return True if all required variables are set, False otherwise
        """
        return self._is_valid()

    def get_input_type(self):
        """Returns the InputType of this data entry.
        
        :return InputType of this entry
        """
        if self.override_input_type is not None:
            return self.override_input_type
        if self._input_item is not None:
            return self._input_item.input_type
        return None

    def get_input_id(self):
        ''' gets the input id'''
        if self.override_input_id is not None:
            return self.override_input_id
        if self._input_item is not None:
            return self._input_item.input_id
        return None


    def update_inputs(self, item_data):
        ''' updates inputs from another profile entry '''
        self._input_item.input_id = item_data.input_id
        self._input_item.device_guid = item_data.device_guid
        self._input_item.device_name = item_data.device_name
        self._input_item.device_type = item_data.device_type
        

    def get_mode(self):
        """Returns the Mode this data entry belongs to.

        :return Mode instance this object belongs to
        """
        if self._input_item is not None:
            return self._input_item.profile_mode
        return None

    def get_device_type(self):
        """Returns the DeviceType of this data entry.
        
        :return DeviceType of this entry
        """
        if self._input_item is not None:
            return self._input_item.device_type
        return None

    def get_device_guid(self):
        """Returns the DeviceType of this data entry.
        
        :return DeviceType of this entry
        """
        if self._input_item is not None:
            return self._input_item.device_guid
        return None
    
    def get_device_name(self):
        ''' returns the name of the currently attached device '''
        if self._input_item is not None:
            return self._input_item.device_name
        return None
    
    @property
    def input_display_name(self):
        ''' gets a config display string for the input '''
        return f"{gremlin.shared_state.get_device_name(self.get_device_guid())} {InputType.to_display_name(self.get_input_type())} {self.get_input_id()}"
    


    def get_settings(self):
        """Returns the Settings data of the profile.

        :return Settings object of this profile
        """

        return gremlin.shared_state.current_profile.settings

        # item = self.parent
        # while not isinstance(item, Profile):
        #     item = item.parent
        # return item.settings


    @property
    def input_item(self):
        return self._input_item
    
    @property
    def hardware_device(self):
        ''' gets the hardware device attached to this action or container '''
        profile : gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        device_guid = self.hardware_device_guid
        if device_guid in profile.devices.keys():
            return profile.devices[device_guid]
        return None
    
    @property
    def hardware_input_id(self):
        ''' gets the input id on the hardware device attached to this '''
        if self.override_input_id is not None:
            return self.override_input_id
        return self.input_item.input_id if self.input_item else None
    
    @property
    def hardware_raw_input_type(self) -> InputType:
        return self._input_item.input_type if self._input_item else None
    
    @property
    def hardware_input_type(self) -> InputType :
        ''' gets the type of hardware device attached to this '''
        if self._input_item:
            input_id = self._input_item.input_id
            input_type = None
            if hasattr(input_id, "getOverrideInputType"):
                self.override_input_type = input_id.getOverrideInputType()
            else:
                self.override_input_type = input_type
        if self.override_input_type is not None:
            return self.override_input_type
        return self._input_item.input_type if self._input_item else None

    
    @property
    def hardware_input_type_name(self) -> str:
        ''' gets the type name of hardware device attached to this '''
        return InputType.to_display_name(self.hardware_input_type)

    

    
    @property 
    def profile_mode(self) -> str:
        ''' gets the mode of this action '''
        return self.get_mode()
    
    @property
    def hardware_device_guid(self) -> dinput.GUID:
        ''' gets the currently attached hardware GUID '''
        return self.input_item.device_guid if self.input_item else None
    
    
    @property
    def hardware_device_id(self) -> str:
        ''' gets the currently attached hardware GUID '''
        return str(self.input_item.device_guid) if self.input_item else None
    
    @property
    def hardware_device_name(self) -> str:
        ''' gets the currently attached hardware name '''
        return self.get_device_name()

    @abstractmethod
    def _parse_xml(self, node, data = None):
        """Implementation of the XML parsing.

        :param node the XML node to use to populate this instance
        """
        pass

    @abstractmethod
    def _generate_xml(self):
        """Implementation of the XML generation.

        :return XML representation of this instance
        """
        pass

    @abstractmethod
    def _is_valid(self):
        """Returns whether or not an instance is fully specified.
        
        :return True if all required variables are set, False otherwise
        """
        pass

    #@abstractmethod
    def _sanitize(self):
        pass


class ActionSet(list):
    ''' holds action set data with a data attribute '''
    def __init__(self, data = None):
        self.data = data # any special tag to identify the action set



class AbstractContainer(ProfileData):

    """Base class for action container related information storage."""

    virtual_button_lut = {
        InputType.JoystickAxis: VirtualAxisButton,
        InputType.JoystickButton: None,
        InputType.JoystickHat: VirtualHatButton,
        InputType.KeyboardLatched: None,
        InputType.Keyboard: None,
        InputType.OpenSoundControl: None,
        InputType.Midi: None,
    }

    #id_changed = Signal(str, str) # fires when id changes (old_id, new_id)

    # default allowed input types = all
    input_types = InputType.to_list()

    # by default the container works with either axis or momentary inputs
    axis_only = False

    def __init__(self, parent, node = None):
        """Creates a new instance.

        :parent the InputItem which is the parent to this action
        """
        super().__init__(parent)

        self.parent = parent
        self._id = gremlin.util.get_guid() # unique GUID of this container
        self._action_sets = []
        self.action_model = None # set at creation by the parent of this container
        self.custom_action_sets = False # true if the container uses custom action sets (need a converter to produce action_sets)
        self._condition_enabled = True
        self._virtual_button_enabled = True # determines if the callbacks can be virtualized or not - if not - the callback is "raw" to the functor - action / container set
        self._virtual_button_user_enabled = True # determins if callbacks use the virtual button function - user set 
        self.activation_condition = ActivationCondition([],ActivationRule.All) # activation condition that applies to the container
        self.activation_condition.setContainer(self)
        self.virtual_button = None
        self.current_view_type = None
        self.parent_node = node
        self.comment = None # user comment
        self._callbacks_enabled = True # callbacks are enabled by default for this container

        el = gremlin.event_handler.EventListener()
        el.virtual_button_changed.connect(self._virtual_button_changed)
        

        self._action_sets_callback = None # callback to return different action sets if needed for containers that do their own thing

        # attached hardware device to this container
        input_item = None
        if isinstance(parent, gremlin.profile_graph.ProfileContainerNode):
            input_item = _get_input_item(parent)
            if not input_item:
                input_item = _get_input_item(parent)

        if not input_item:
            input_item = _get_input_item(parent)

        self._input_item = input_item
        assert input_item is not None
        # if input_item is not None:
        self.device_guid = input_item.device_guid
        self.device_input_id = input_item.input_id
        self.device_input_type = input_item.input_type
        self.device = gremlin.joystick_handling.device_info_from_guid(self.device_guid)
        # else:
        #     self.device_guid = None
        #     self.device_input_id = None
        #     self.device_input_type = None
        #     self.device = None

    @QtCore.Slot(object, object, object)
    def _virtual_button_changed(self, input_item, container, action):
        ''' called when an action changes its virtual button setting '''
        if self.id == container.id:
            self.create_or_delete_virtual_button()
            el = gremlin.event_handler.EventListener()
            el.condition_changed.emit(self)

    def mapping_changed(self):
        ''' fires the mapping changed event to notify UI on mapping changes made to this container '''
        # tell the UI about the change
        el = gremlin.event_handler.EventListener()
        el.mapping_changed.emit(self._input_item)

    def generateGuids(self):
        ''' called when GUIDs for this container, actions and conditions need to be re-set '''

        tracker = ConditionTracker()

        self._id = gremlin.util.get_guid() # unique GUID of this container
        
        for action_set in self.get_action_sets():
            for action in action_set:
                action.setId(gremlin.util.get_guid())

        if self.activation_condition:
            self.activation_condition.setId(gremlin.util.get_guid())
            for condition in self.activation_condition.conditions:
                data = tracker.getData(condition)
                condition.setId(gremlin.util.get_guid())
                if data:
                    new_data = ConditionTrackerData(data.mode, data.input_item, self, condition, data.rule)
                    tracker.registerCondition(new_data)


            el = gremlin.event_handler.EventListener()
            el.condition_state_changed.emit(self)
        




    @property
    def input_item(self):
        ''' gets the associated input item for this container '''
        return _get_input_item(self.parent)

    @property
    def has_conditions(self):
        ''' true if the container has conditions defined '''
        return self.activation_condition is not None and len(self.activation_condition.conditions) > 0

    @property
    def has_action_conditions(self):
        ''' true if the container has action conditions defined '''
        
        if self.activation_condition is not None:
            # if len(self.activation_condition.conditions) == 0:
            #     self.refresh_conditions()
            return len(self.activation_condition.conditions) > 0
        return False
    

    @property
    def condition_count(self)->int:
        ''' gets the count of container conditions currently defined '''
        if self.activation_condition is not None:
            return len(self.activation_condition.conditions)
        return 0
    
    @property
    def id(self):
        return self._id

    def setId(self, value : str):
        ''' sets the ID '''
        self._id = value    
    
    @property
    def condition_enabled(self):
        ''' determines if condition tab is enabled '''
        return self._condition_enabled
    @condition_enabled.setter
    def condition_enabled(self, value):
        ''' determines if condition tab is enabled '''
        self._condition_enabled = value

    @property
    def virtual_button_enabled(self) -> bool:
        ''' determines if virtual button tab is enabled and virtual buttons is enabled for functor callbacks'''
        return self._virtual_button_enabled 
    @virtual_button_enabled.setter
    def virtual_button_enabled(self, value : bool):
        ''' determines if virtual button tab is enabled and virtual buttons is enabled for functor callbacks'''
        self._virtual_button_enabled = value

    @property
    def virtual_button_user_enabled(self) -> bool:
        ''' flag for user enable of the virtual button functionality so the user can decide to use it or not '''
        return self._virtual_button_user_enabled
    @virtual_button_user_enabled.setter
    def virtual_button_user_enabled(self, value : bool):
        self._virtual_button_user_enabled = value

  
    @property
    def input_display_name(self):
        return f"{gremlin.shared_state.get_device_name(self.device_guid)} {InputType.to_display_name(self.device_input_type)} {self.device_input_id}"
    
    def add_action(self, action, index=-1):
        """Adds an action to this container.

        :param action the action to add
        :param index the index of the action_set into which to insert the
            action. A value of -1 indicates that a new set should be
            created.
        """
        
        if index == -1:
            self.action_sets.append([])
            index = len(self.action_sets) - 1
        self.action_sets[index].append(action)

        # Create activation condition data if needed
        self.create_or_delete_virtual_button()

        # tell the UI about the change
        el = gremlin.event_handler.EventListener()
        el.mapping_changed.emit(self._input_item)

    @property
    def action_sets(self):
        ''' gets the action sets for this container '''
        return self._action_sets
    
    @action_sets.setter
    def action_sets(self, value):
        self._action_sets = value

    @property
    def action_count(self):
        ''' returns the count of defined actions in this container '''
        count = sum(len(action_list) for action_list in self.action_sets)
        return count
        

    def create_or_delete_virtual_button(self):
        """Creates activation condition data as required."""
        need_virtual_button = False
        for actions in [a for a in self.action_sets if a is not None]:
            need_virtual_button = need_virtual_button or \
                any([a.requires_virtual_button() for a in actions if a is not None])


        if need_virtual_button:
            if self.virtual_button is None:
                input_type = self.parent.input_type
                vb = AbstractContainer.virtual_button_lut.get(input_type, None)
                if vb:
                    self.virtual_button = vb(self)
                    
            elif not isinstance(self.virtual_button,AbstractContainer.virtual_button_lut[self.parent.input_type]):
                self.virtual_button = \
                    AbstractContainer.virtual_button_lut[self.parent.input_type](self)
        else:
            self.virtual_button = None


    @property
    def has_virtual_button(self) -> bool:
        ''' true if the container has a virtual button definition '''
        return self._virtual_button_enabled and self._virtual_button_user_enabled and self.virtual_button is not None

    def generate_callbacks(self, parent = None):
        """Returns a list of callback data entries.

        :return list of container callback entries
        """
        if not self._callbacks_enabled:
            # callbacks handled a different way by this container 
            return []
        
        callbacks = []

        # For a virtual button create a callback that sends VirtualButton
        # events and another callback that triggers of these events
        # like a button would.
        from gremlin.event_handler import Event


        callbacks.append(CallbackData(gremlin.execution_graph.ContainerCallback(self, parent),None))


        return callbacks
    

    def from_xml(self, node, data = None):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """
        
        super().from_xml(node, data)
        

        if "container_id" in node.attrib:
            self._id = node.get("container_id")

        # import_data = gremlin.base_profile.ProfileImportData()    
        # if self._id in import_data.used_ids:
        #     new_id = gremlin.util.get_guid()
        #     verbose = gremlin.config.Configuration().verbose
        #     if verbose: syslog.warning(f"PROFILE: duplicate ID found - Container: [{id}] - assigning new id: [{new_id}]")
        #     self._id = new_id
        
        # import_data.used_ids[self._id] = self


        comment = None
        if "comment" in node.attrib:
            comment = node.get("comment")
        if comment:
            self.comment = comment
        self._parse_action_set_xml(node, data)
        self._parse_virtual_button_xml(node, data)
        self._parse_activation_condition_xml(node, data)


    def to_xml(self):
        """Returns a XML node representing the instance's contents.

        :return XML node representing the state of this instance
        """
        node = super().to_xml()
        node.set("container_id", self.id)

        if self.comment:
            node.set("comment", self.comment)

        # Add activation condition if needed
        if self.virtual_button:
            node.append(self.virtual_button.to_xml())
        
        if self.activation_condition:
            condition_node = self.activation_condition.to_xml()
            if condition_node is not None:
                node.append(condition_node)

        return node

    def _parse_action_set_xml(self, node, data = None):
        """Parses the XML content related to actions.

        :param node the XML node to process
        """
        self.action_sets = []
        for child in node:
            if child.tag == "virtual-button":
                continue
            elif child.tag == "action-set":
                action_set = ActionSet()
                self._parse_action_xml(child, action_set, data)
                self.action_sets.append(action_set)
 
    def _parse_action_xml(self, node, action_set, data = None):
        """Parses the XML content related to actions in an action-set.

        :param node the XML node to process
        :param action_set storage for the processed action nodes
        """
        action_name_map = ActionPlugins().tag_map
        config = gremlin.config.Configuration()
        for child in node:
            
            if child.tag not in action_name_map:
                syslog.warning(f"Unknown node present: {child.tag}")
                continue

            # apply any conversions
            tag = child.tag
            if config.convert_response_curve and gremlin.base_profile._is_curve_tag(tag):
                tag = "response-curve-ex"
                if not tag in action_name_map:
                    # new mapper not found
                    tag = child.tag
            elif config.convert_vjoy_remap and tag == "remap":
                tag = "vjoyremap"
                if not tag in action_name_map:
                    # new mapper not found
                    tag = child.tag


            entry = action_name_map[tag](self)
            input_item = data
            entry.from_xml(child, (input_item, self)) # pass input item, container as a tuple
            action_set.append(entry)



    def _parse_virtual_button_xml(self, node, data = None):
        """Parses the virtual button part of the XML data.

        :param node the XML node to process
        """
        vb_node = node.find("virtual-button")
        device_guid, input_type, input_id, mode = get_xml_input_data(node)

        self.virtual_button = None
        if vb_node is not None:
            item = AbstractContainer.virtual_button_lut[self.get_input_type()]
            if item is not None:
                self.virtual_button = item(self)
                self.virtual_button.from_xml(vb_node, data)

    def _parse_activation_condition_xml(self, node, data):
        ''' load the container condition '''
        self.activation_condition = ActivationCondition([], ActivationRule.All)
        self.activation_condition.setContainer(self)
        input_item = data
        activation_node = gremlin.util.get_xml_child(node,"activation-condition")
        if activation_node is not None:
            self.activation_condition.from_xml(activation_node, (input_item, self))


    def _is_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if configured properly, False otherwise
        """
        # Check state of the container
        state = self._is_container_valid()

        # Check state of all linked actions
        for actions in [a for a in self.action_sets if a is not None]:
            for action in actions:
                action_valid = action.is_valid()
                if not action_valid:
                    syslog.warning(f"Action warning: {type(action).__name__} reports invalid - hardware {self.hardware_device_name} input: {self.hardware_input_type_name}  {self.hardware_input_id}")
                state = state & action_valid
        return state
    

    def is_valid_for_save(self):
        """ true if the container can be saved to a profile """
        state = self._is_container_valid()

        return state

        # action_count = 0
        
        # # Check state of all linked actions
        # for actions in [a for a in self.action_sets if a is not None]:
        #     action_count += len(actions)
        #     for action in actions:
        #         state = state & action.is_valid_for_save()
        # return state and action_count > 0
    
    def latch_extra_inputs(self):
        ''' returns any extra inputs as a list of (device_guid, input_id) to latch to this action (trigger on change) '''
        latched_list = []
        for actions in [a for a in self.action_sets if a is not None]:
            for action in actions:
                if hasattr(action, "latch_extra_inputs"):
                    for key in action.latch_extra_inputs():
                        if not key in latched_list:
                            latched_list.append(key)

        return latched_list
        

    @abstractmethod
    def _is_container_valid(self):
        """Returns whether or not the container itself is valid.

        :return True container data is valid, False otherwise
        """
        pass

    def get_action_sets(self):
        """ returns action sets - used for duplication (override if needed) """
        return self.action_sets




class Device:
    ''' device information '''
    def __init__(self, parent):
        """Creates a new instance.

        :param parent the parent profile of this device
        """
        self.parent = parent  # profile
        self.name = None
        self.label = ""
        self._device_guid = None
        self.modes = {}
        self.type = None # device type
        self.virtual = False # true if the device is virtual (vjoy)
        self.connected = False # true if the device was found in the detected hardware list
        self.masterMode = {} # master mode
        

    @property
    def device_guid(self) -> dinput.GUID:
        ''' device ID as a GUID '''
        return self._device_guid
    
    @device_guid.setter
    def device_guid(self, value : dinput.GUID):
        assert isinstance(value, dinput.GUID) if value is not None else True
        self._device_guid = value
        


    @property
    def device_id(self) -> str:
        ''' device ID a a string '''
        return str(self.device_guid)

    @property
    def device_type(self) -> DeviceType:
        return self.type 

    def get_mode_object(self, mode_name):
        ''' gets the mode object for the given mode'''
        if mode_name in self.modes:
            return self.modes[mode_name]       
        return None

    def ensure_mode_exists(self, mode_name, device : dinput.DeviceSummary =None, is_system = False) -> Mode:
        """Ensures that a specified mode exists, creating it if needed.

        :param mode_name the name of the mode being checked
        :param device a device to initialize for this mode if specified
        :param is_system: true if the mode is a special system mode (not user defined)
        :returns: Mode object 
        """
        if mode_name in self.modes:
            mode = self.modes[mode_name]
        else:
            mode = Mode(self, is_system)
            mode.name = mode_name
            self.modes[mode.name] = mode

        if device is not None:
            for i in range(device.axis_count):
                count = len(device.axismap_list)
                if i > count:
                    syslog.error(f"{device.name} invalid axis request {device.axis_count} < {i}")
                else:
                    mode.get_data(
                        InputType.JoystickAxis,
                        device.axismap_list[i].axis_index
                    )
            for idx in range(1, device.button_count + 1):
                mode.get_data(InputType.JoystickButton, idx)
            for idx in range(1, device.hat_count + 1):
                mode.get_data(InputType.JoystickHat, idx)

        return mode

    def from_xml(self, node, data = None):
        """Populates this device based on the xml data.

        :param node the xml node to parse to populate this device
        """
        self.name = node.get("name")
        self.label = safe_read(node, "label", str, self.name)
        dt = safe_read(node, "type", str, "")
        if not dt:
            dt = DeviceType.NotSet
        self.type = DeviceType.to_enum(dt)
        device_id = node.get("device-guid")
        if not device_id:
            syslog.error(f"Device XML: unable to parse device GUID: [{device_id}]")
            sys.exit(-1)
            
        
        self.device_guid = parse_guid(device_id)
        self.connected = gremlin.joystick_handling.is_device_connected(self.device_guid)

        verbose = gremlin.config.Configuration().verbose_mode_device
        if verbose:
            syslog.info(f"XML Device: read [{device_id}] Device currently connected: {self.connected}")

        for child in node:
            mode = Mode(self)
            mode.from_xml(child, data)
            self.modes[mode.name] = mode


    def to_xml(self):
        """Returns a XML node representing this device's contents.

        :return xml node of this device's contents
        """
        node_tag = "device" if self.type != DeviceType.VJoy else "vjoy-device"
        node = etree.Element(node_tag)
        node.set("name", safe_format(self.name, str))
        node.set("label", safe_format(self.label, str))
        node.set("device-guid", write_guid(self.device_guid))
        device_type = DeviceType.to_string(self.type)
 
        node.set("type",device_type)
        for mode in sorted(self.modes.values(), key=lambda x: x.name):
            node.append(mode.to_xml())
        return node






class AbstractAction(ProfileData):

    """Base class for all actions that can be encoded via the XML and
    UI system."""

    #id_changed = Signal(str, str)  # triggers when the ID changes

    # allow all input types by default
    input_types = InputType.to_list()

    def __init__(self, parent):
        """Creates a new instance.

        :parent the container which is the parent to this action
        """
        # assert isinstance(parent, AbstractContainer)
        super().__init__(parent)

        self.activation_condition = None # stores the conditions attached to that action
        self._id = gremlin.util.get_guid()
        self._action_type = None
        self._enabled = False # true if the action is enabled
        self.singleton = False # true if the action can only appear once in the input's mapping
        self.parent_container = parent # holds the reference to the parent container holding this action
        self._is_axis = False
        self._is_hardware = None
        self.comment = None # user comments/notes
        self._priority = 0 # default priority
        self.data = None # additional data for runtime purposes, context dependent used to tag actions at runtime for some purpose like action grouping

        el = gremlin.event_handler.EventListener()
        el.action_created.emit(self)
        el.profile_unload.connect(self._cleanup)
        el.action_delete.connect(self._action_delete)
        el.profile_start.connect(self.profile_start)
        el.profile_stop.connect(self.profile_stop)

    def profile_start(self):
        ''' start event - override in subclass as needed '''
        pass

    def profile_stop(self):
        ''' stop event - override in subclass as needed '''
        pass


    @property
    def id(self):
        ''' unique ID for this condition, persisted '''
        return self._id
    
    def setId(self, value : str):
        ''' sets the ID '''
        self._id = value
    
    @property
    def priority(self):
        return self._priority

    def setPriority(self, value : int):
        ''' sets the priority of the action, numeric'''
        self._priority = value   

    @property
    def has_conditions(self):
        ''' true if the action has conditions defined '''
        return self.activation_condition is not None and len(self.activation_condition.conditions) > 0
        
    def _action_delete(self, input_item, container, action):
        if self._id == action._id:
            if not input_item.is_action:
                self._cleanup()

    def _cleanup(self):
        ''' called when the action should clean itself up '''
        el = gremlin.event_handler.EventListener()
        event = gremlin.event_handler.DeviceChangeEvent()
        event.source = self
        el.icon_changed.emit(event)
        el.profile_unload.disconnect(self._cleanup)
        el.action_delete.disconnect(self._action_delete)
        

    


    def get_input_item(self):
        ''' gets the input item owning this action '''
        input_item = _get_input_item(self.parent_container)
        return input_item
    
    def get_container(self):
        return self.parent_container
        

    def setEnabled(self, value):
        ''' enables or disables the functor - a disabled functor will not receive the start profile event nor will the process_event be called
        
        This is done to make sure that functors only get called if the plugin is referenced in a profile's execution graph to avoid unecessary initializations
        
        '''
        import gremlin.event_handler
        
        if self._enabled == value:
            return # nothing to do
        self._enabled = value
        
        verbose = gremlin.config.Configuration().verbose_mode_details

        if verbose and value:
            syslog.info(f"Functor: {self.name} {type(self).__name__} enabled")

    def input_is_axis(self):
        ''' true if the input is an axis type input '''

        is_axis = False
        if hasattr(self, "hardware_input_type"):
            input_type : InputType = self.hardware_input_type
            if input_type == InputType.JoystickAxis:
                return True
                
        if hasattr(self.hardware_input_id, "is_axis"):
            is_axis = self.hardware_input_id.is_axis
            return is_axis
        if hasattr(self.input_item,"is_axis") and hasattr(self._input_item,"axis_value"):
            is_axis = is_axis or self.input_item.is_axis
        
        return is_axis
    
    def input_is_button(self):
        ''' true if the input is a button '''
        is_button = False
        if hasattr(self, "hardware_input_type"):
            input_type : InputType = self.hardware_input_type
            return input_type == InputType.JoystickButton
                
        if hasattr(self.hardware_input_id, "is_axis"):
            is_button = not self.hardware_input_id.is_axis
        
        return is_button

    
    def input_is_hardware(self):
        ''' true if the device is a hardware input device '''
        if self._is_hardware is None:
            self._is_hardware =  gremlin.joystick_handling.is_hardware_device(self.hardware_device_guid)
        return self._is_hardware

    @property
    def enabled(self):
        return self._enabled
        

    @property
    def action_id(self):
        ''' id '''
        return self._id
    

    @property
    def action_type(self):
        ''' type name of this action '''
        return self._action_type
    
    

    def display_name(self):
        ''' display name for this action '''
        return "N/A"
    

    def from_xml(self, node, data = None):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """

        # set the action ID first as it can be read by subsequent code
        import_data = gremlin.base_profile.ProfileImportData()

        if "action_id" in node.attrib:
            self._id = node.get("action_id")

        # if self._id in import_data.used_ids:
        #     new_id = gremlin.util.get_guid()
        #     verbose = gremlin.config.Configuration().verbose
        #     if verbose: syslog.warning(f"PROFILE: duplicate ID found - Action: [{id}] - assigning new id: [{new_id}]")
        #     self.id = new_id
    
        # import_data.used_ids[self._id] = self
        
            

        comment = None
        if "comment" in node.attrib:
            comment = node.get("comment")
        if comment:
            self.comment = comment


        super().from_xml(node, data)


        self.activation_condition = ActivationCondition([],ActivationRule.All)
        self.activation_condition.setContainer(self)
        for _ in node.findall("activation-condition"):
            cond_node = node.find("activation-condition")
            if cond_node is not None:
                self.activation_condition.from_xml(cond_node, data)
                

        # record the type of this action
        self._action_name = node.tag

    def to_xml(self):
        """Returns a XML node representing the instance's contents.

        :return XML node representing the state of this instance
        """
        node = super().to_xml()
        if self.has_conditions:
            # output the conditions
            node.append(self.activation_condition.to_xml())

        # output the ID
        node.set("action_id", self.action_id)

        # output any notes
        if self.comment:
            node.set("comment", self.comment)

        return node

    def requires_virtual_button(self):
        """Returns whether or not the action requires the use of a
        virtual button.

        :return True if a virtual button has to be used, False otherwise
        """
        raise error.MissingImplementationError(
            "AbstractAction.requires_virtual_button() not implemented"
        )
    
    def _is_valid(self):
        raise error.MissingImplementationError(
            "AbstractAction._is_valid() not implemented"
        )
    
    def is_valid_for_save(self):
        ''' indicates an action can be saved to a profile even if it's not configured - this allows in process profile saving '''
        return True
    

    def __str__(self):
        if hasattr(self,"display_name"):
            return self.display_name()
        return super().__str__()

class AbstractContainerAction(AbstractAction):
    ''' abstract action that includes a subcontainers for sub-actions '''
    def __init__(self, parent = None):
        
        super().__init__(parent)

        self._item_data_map = {}
        self._functors = []
    
    @property
    def item_data(self):
        ''' gets the default (first) data container block '''
        return self.get_item_data(0)
    
    def get_item_data(self, index, autocreate = True):
        ''' gets the specified data container block
        
        :param: autocreate - if set, creates a datablock if it does not exist
        
        '''
        
        if autocreate and not index in self._item_data_map.keys():
            # get the input item behind the parent action
            current = self.parent
            while current and not isinstance(current, InputItem):
                current = current.parent

            # setup a new input item for these containers and read from config the defined containers
            
            item_data = InputItem(parent = self)
            item_data._input_type = current._input_type
            item_data._device_guid = current._device_guid
            item_data._input_id = current._input_id
            self._item_data_map[index] = item_data
            registry = ProfileRegistry()
            registry.registerInputItem(item_data)
            
        if index in self._item_data_map.keys():
            return self._item_data_map[index]
        return None

    def from_xml(self, node, data = None):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """

        super().from_xml(node, data)
        registry = ProfileRegistry()
        container_nodes = gremlin.util.get_xml_child(node,"action_containers", multiple = True)

        # if hasattr(self,"command") and self.command == 'THROTTLE1_AXIS_SET_EX1':
        #     pass


        # get the input item behind the parent action
        current = self.parent
        while current:
            if isinstance(current, InputItem):
                # legacy instance
                break
            if isinstance(current, gremlin.profile_graph.ProfileInputNode):
                # graph instance
                current = current.input_item
                break
            current = current.parent

        assert current is not None,"Profile nesting error: unable to find InputItem"

        mode_object = get_mode_object(node)


        for child in container_nodes:

            

            # setup a new input item for these containers and read from config the defined containers
            
            input_item = InputItem(parent = mode_object)
            input_item._input_type = current._input_type
            input_item._device_guid = current._device_guid
            input_item._input_id = current._input_id

            
            registry.registerInputItem(input_item)

            if child is not None:
                child.tag = child.get("type")
                index = safe_read(child,"index",int,0)
                input_item.from_xml(child, data)

            self._item_data_map[index] = input_item

    def to_xml(self):
        ''' writes node out to XML '''
        node = super().to_xml()

        for index, item_data in self._item_data_map.items():
            child = item_data.to_xml()
            child.set("type", child.tag)
            child.tag = "action_containers"
            child.set("index",str(index))
            node.append(child)
        return node

    # copy/paste exclusions
    def __getstate__(self):
        state = self.__dict__.copy()
        del state["item_data"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        input_item = InputItem(parent = self)
        self.item_data = input_item
        registry = ProfileRegistry()
        registry.registerInputItem(input_item)
    
    @property
    def functors(self):
        ''' gets the execution graphs for each sub container '''
        return self._functors

    def add_container(self, container_name):
        ''' adds a new container to the action '''
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        container = plugin_manager.get_class(container_name)(self.item_data)
        if hasattr(container, "action_model"):
            container.action_model = self.action_model
        self.action_model.add_container(container)
        plugin_manager.set_container_data(self.item_data, container)
        self._subcontainers.append(container)
        return container
    
    def _build_graph(self, parent_node = None):
        ''' builds the execution graph for the sub containers '''
        for container in self._subcontainers:
            eg = gremlin.execution_graph.ContainerExecutionGraph(container, parent_node)
            self._functors.extend(eg.functors)

        


class Settings:

    """Stores general profile specific settings."""

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the parent profile
        """
        self.parent = parent
        self.vjoy_as_input = {}
        self.vjoy_initial_values = {}
        self.startup_mode = None
        self.default_delay = 0.05


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
        for vid, value in self.vjoy_as_input.items():
            if value is True:
                vjoy_node = etree.Element("vjoy-input")
                vjoy_node.set("id", safe_format(vid, int))
                node.append(vjoy_node)

        # Process vJoy axis initial values
        for vid, data in self.vjoy_initial_values.items():
            vjoy_node = etree.Element("vjoy")
            vjoy_node.set("id", safe_format(vid, int))
            for aid in data:
                enabled, value = data[aid]
                axis_node = etree.Element("axis")
                axis_node.set("id", safe_format(aid, int))
                axis_node.set("value", safe_format(value, float))
                axis_node.set("enabled", safe_format(enabled, bool))
                vjoy_node.append(axis_node)
            node.append(vjoy_node)

        return node

    def from_xml(self, node, data = None):
        """Populates the data storage with the XML node's contents.

        :param node the node containing the settings data
        """
        if node is None:
            return

        # Startup mode
        self.startup_mode = None
        if node.find("startup-mode") is not None:
            self.startup_mode = node.find("startup-mode").text

        # Default delay
        self.default_delay = 0.05
        if node.find("default-delay") is not None:
            self.default_delay = float(node.find("default-delay").text)

        # vJoy as input settings
        self.vjoy_as_input = {}
        for vjoy_node in node.findall("vjoy-input"):
            vid = safe_read(vjoy_node, "id", int, 0)
            self.vjoy_as_input[vid] = True

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


    def get_vjoy_axis_enabled(self, vid, aid) -> bool:
        ''' true if the value is enabled for this axis '''
        if vid in self.vjoy_initial_values:
            if aid in self.vjoy_initial_values[vid]:
                enabled, value = self.vjoy_initial_values[vid][aid]
                return enabled
        return False
    
    def set_vjoy_axis_enabled(self, vid, aid, value = None) -> bool:
        ''' true if the value is enabled for this axis '''
        if not vid in self.vjoy_initial_values:
            self.vjoy_initial_values[vid] = {}
        if not aid in self.vjoy_initial_values[vid]:
            self.vjoy_initial_values[vid][aid] = (True, value if value is not None else 0.0)
        else:
            if value is None:
                self.vjoy_initial_values[vid][aid][0] = True
            else:
                self.vjoy_initial_values[vid][aid][0] = (True, value)
    

    def get_initial_vjoy_axis_value_list(self):
        ''' gets all defined default values as a triplet (vjoy_id, axis_id, value)'''
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


def extract_remap_actions(action_sets):
    """Returns a list of remap actions from a list of actions.

    :param action_sets set of actions from which to extract Remap actions
    :return list of Remap actions contained in the provided list of actions
    """
    remap_actions = []
    for actions in [a for a in action_sets if a is not None]:
        for action in actions:
            if hasattr(action,"name") and action.name in ("Remap", "Vjoy Remap"):
                remap_actions.append(action)
            # if isinstance(action, gremlin.action_plugins.remap.Remap):
            #     remap_actions.append(action)
    return remap_actions

@SingletonDecorator
class ProfileRegistry():
    ''' holds data about a profile in a central location for easier reference and to avoid duplication of object references in data structures '''
    def __init__(self):
        self._input_item_registry = {} # references created input items in a profile, keyed by device_guid, input_type, input_id
        self._device_registry = {} # references the devices in the profile

    def reset(self):
        ''' clear entries for a new profile '''
        self._input_item_registry.clear()
        self._device_registry.clear()

    def registerDevice(self, device : Device):
        self._device_registry[device.device_guid] = device

    def getDevice(self, device_guid) -> Device:
        ''' gets a registered device '''
        if device_guid in self._device_registry:
            return self._device_registry[device_guid]
        return None

    def registerInputItem(self, input_item):
        ''' registers an input item in the profile registry '''
        assert input_item is not None and \
            input_item.device_guid is not None \
            and input_item.input_type is not None \
            and input_item.input_id is not None \
            , "Registration error: input item is invalid"
        
        device_guid = input_item.device_guid
        input_type = input_item.input_type
        input_id = input_item.input_id
        input_id_key = hash(input_id)
        key = (device_guid, input_type, input_id_key)
        self._input_item_registry[key] = input_item

    def getInputItem(self, device_guid, input_type, input_id) -> InputItem:
        ''' retrieves a stored input item '''
        
        input_id_key = hash(input_id)
        key = (device_guid, input_type, input_id_key)
        if key in self._input_item_registry:
            return self._input_item_registry[key]
        return None # not found
    

def get_mode_object(node):
    ''' gets the mde object corresponding to a profile XML node 
    
    :param node: lxml element to scan ancestors for 
    
    '''

    nodes = node.xpath("ancestor::mode")
    mode_node = nodes.pop()
    mode = safe_read(mode_node, "name", str, "")
    assert len(mode) > 0, "XML hierarchy error - parent mode not found"

    nodes = node.xpath("ancestor::device")
    device_node = nodes.pop()
    device_id = safe_read(device_node, "device-guid", str, "")
    assert device_id, "XML hierarchy error - parent device not found"
    device_guid = gremlin.util.parse_guid(device_id)
    device_type = safe_read(device_node,"type", str, "")
    device_type = DeviceType.to_enum(device_type)
    
    profile = gremlin.shared_state.current_profile
    device_modes = profile.get_device_modes(device_guid,device_type,DeviceType.to_string(device_type))
    mode_object = device_modes.ensure_mode_exists(mode)    

    return mode_object


class InputItem(gremlin.base_classes.AbstractInputItem):

    """Represents a single input item such as a button or axis, containers and parameters/options associated with that input mapping """

    def __init__(self, custom_name_handler = None, custom_mode_name_handler = None, parent = None):
        """Creates a new InputItem instance.
        :param custom_name_handler: handler() returns a string, whenever the input name is needed
        :param custom_mode_name_handler: handler() returns a string, optional, to override the default mode for special inputs that use special modes
        :param parent: the parent mode object of this input item
        """
        # self._id = gremlin.util.get_guid() # unique ID of this object
        # self._guid = gremlin.util.parse_guid(self._id)

        super().__init__()

        assert isinstance(parent, gremlin.base_profile.Mode), "Parent parameter must be a mode object"

        
        self.parent = parent # mode object
        self._input_type = None
        self._override_input_type = None # override input type for some types that are different
        self._device_guid = None # hardware input ID
        self._device_id = None # hardware input ID as a string
        self._name = None # device name
        self._input_id = None # input Id on the hardware
        self._input_name = None # input name of the hardware (axis name if an axis)
        self._input_name_handler = custom_name_handler # custom handler 
        self.always_execute = False
        self._description = ""
        self._description_readonly = False # true if description is read/only (cannot be changed)
        self._profile_mode_callback = custom_mode_name_handler # special callback to use to get the profile mode for this item (if special)
        self._containers = []
        self._selected = False # true if the item is selected
        self._is_action = False # true if the object is a sub-item for a sub-action (GateHandler for example)
        self._device_type = None
        self._device_name = None
        self._is_axis = False # true if the item is an axis input
        self._is_button = False # true if the item is a button input
        self._calibration = None # calibration data if the item is an input axis
        self._curve_data = None # true if the item has its input curved
        # self._profile_mode = None
        self._enabled = True # enabled flag
        if parent is not None:
            # find the missing properties from the parenting hierarchy
            self._is_action = isinstance(parent, AbstractAction)
            item = parent
            while True:
                # if isinstance(item, Mode):
                #    self._profile_mode = item.name
                if isinstance(item, Device):
                    self._device_type = item.type
                    self._device_name = item.name
                    self._device_guid = item.device_guid
                    self._device_id = item.device_id
                if not hasattr(item, "parent"):
                    break
                item = item.parent

        self._message_key = None # message key for this input (device_guid, input_type, input_id)

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._profile_start)

    def setProfileModeCallback(self, callback):
        ''' sets an override callback to change profile mode return value for special cases '''
        self._profile_mode_callback = callback


    @property
    def profile_mode(self) -> str:
        if self._input_type == InputType.ModeControl:
            if self._input_id in (gremlin.ui.mode_device.ModeInputModeType.ModeProfileLoad,
                                  gremlin.ui.mode_device.ModeInputModeType.ModeProfileStart,
                                  gremlin.ui.mode_device.ModeInputModeType.ModeProfileStop):
                return gremlin.shared_state.master_mode

        if self._profile_mode_callback:
            return self._profile_mode_callback(self)
        mode : Mode = self.parent
        if mode:
            return mode.name
        return None
    
        
      

    @property
    def message_key(self):
        # joystick inputs only - returns id of axis or button
        if self._input_id is not None and hasattr(self._input_id,"message_key"):
            return self._input_id.message_key
        return self._input_id
    
    def callbackKey(self):
        ''' callback key unique to the input type, input id '''
        return (self._device_guid, self._input_type, self._input_id)

    @property
    def hasCalibration(self):
        ''' for axis input devices, returns True if the device has an active calibration '''
        return self._calibration is not None and self._calibration.hasData
    
    @property
    def calibration(self):
        ''' for axis input devices, returns the calibration data '''
        return self._calibration
    
    @QtCore.Slot()
    def _refresh_icons(self):
        ''' called when the UI wants to refresh input icons '''


    @QtCore.Slot()
    def _profile_start(self):
        # enable the input at profile start 
        self._enabled = True

    @property
    def description(self):
        if self._description is None:
            # see if there is a container
            if self.containers:
                for container in self.containers:
                    if container.action_sets:
                        action_list = container.action_sets[0]
                        if action_list:
                            action = action_list[0]
                            if hasattr(action, "display_name"):
                                return action.display_name()

        return self._description
    
    @description.setter
    def description(self, value):
        if not self._description_readonly:
            self._description = value

    @property
    def descriptionReadOnly(self) -> bool:
        ''' true if description is readonly'''
        return self._description_readonly
    
    @descriptionReadOnly.setter
    def descriptionReadOnly(self, value: bool):
        self._description_readonly = value
        
    @property
    def input_name(self) -> str:
        ''' input name as computed based on device, type and input id'''
        if self._input_name_handler is not None:
            return self._input_name_handler(self)
        return self._input_name

    @property
    def selected(self) -> bool:
        ''' true if the item is selected'''
        return self._selected
    @selected.setter
    def selected(self, value : bool):
        self._selected = value

    @property
    def enabled(self) -> bool:
        return self._enabled
    @enabled.setter
    def enabled(self, value: bool):
        if value != self.enabled:
            self._enabled = value
            # fire off the change event
            el = gremlin.event_handler.EventListener()
            el.input_enabled_changed.emit(self)


    @property
    def is_action(self) -> bool:
        ''' true if the item is action '''
        return self._is_action
    @is_action.setter
    def is_action(self, value : bool):
        self._is_action = value

    @property
    def is_axis(self) -> bool:
        ''' true if this item is setup as an axis input (linear) '''
        if self._input_id and hasattr(self._input_id,"is_axis"):
            return self._input_id.is_axis
        return self._is_axis or self._input_type == InputType.JoystickAxis
    @is_axis.setter
    def is_axis(self, value : bool):
        self._is_axis = value

    @property
    def is_button(self) -> bool:
        ''' true if this item is setup as an axis input (momentary) '''
        return not self.is_axis
    

    def add_container(self, container):
        self._containers.append(container)
        
        # tell the UI about the change
        el = gremlin.event_handler.EventListener()
        el.mapping_changed.emit(self)

    def remove_container(self, container):
        if not container in self._containers:
            id = container.id
            for c in self._containers:
                if c.id == id:
                    self._containers.remove(c)
                    break
            return
                
        self._containers.remove(container)

        # tell the UI about the change
        el = gremlin.event_handler.EventListener()
        el.mapping_changed.emit(self)

    def get_containers(self):
        return self._containers
    
    @property
    def containers(self):
        return self._containers

    @property
    def input_type(self):
        return self._input_type
    @input_type.setter
    def input_type(self, input_type):
        # override mode/state inputs for legacy profiles
        if self._device_type == DeviceType.ModeControl:
            input_type = InputType.ModeControl
        elif self._device_type == DeviceType.State:
            input_type = InputType.State
        elif self._device_type == DeviceType.Osc:
            input_type = InputType.OpenSoundControl
        elif self._device_type == DeviceType.Midi:
            input_type = InputType.Midi
        self._input_type = input_type
        self._update_input()

    def getInputType(self):
        ''' gets the input type or the override input type'''
        if self._override_input_type:
            return self._override_input_type
        return self.input_type
    
    def getRawInputType(self):
        ''' gets the input type or the override input type'''
        return self.input_type
    
    def setOverrideInputType(self, input_type):
        ''' sets the override input type '''
        self._override_input_type = input_type
        self._update_input()

    def getOverrideInputType(self):
        ''' gets the override input type - which defaults to the regular input type if no override is set '''
        if self._override_input_type:
            return self._override_input_type
        return self._input_type


    @property
    def input_id(self):
        return self._input_id
    @input_id.setter
    def input_id(self, value):
        from gremlin.base_classes import AbstractInputItem
        assert value == None or isinstance(value, int) or isinstance(value, AbstractInputItem)
        self._input_id = value
        self._update_input()

            

    @property
    def device_guid(self):
        return self._device_guid
    @device_guid.setter
    def device_guid(self, value):
        self._device_guid = value
        self._device_id = str(value)
        self._update_input()

    @property
    def device_id(self):
        return self._device_id
    @device_id.setter
    def device_id(self, value):
        self._device_id = value
        self._device_guid = gremlin.util.parse_guid(value)
        self._update_input()


    @property
    def device_type(self):
        return self._device_type
    @device_type.setter
    def device_type(self, value):
        if value != self._device_type:
            self._device_type = value
            self._device_name = DeviceType.to_display_name(value)
    
    @property
    def device_name(self):
        return self._device_name
    @device_name.setter
    def device_name(self, value):
        self._device_name = value

    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self._data = value
        
    
    @property
    def curve_data(self) -> gremlin.curve_handler.AxisCurveData:
        ''' axis curve data '''
        return self._curve_data
    
    @curve_data.setter
    def curve_data(self, value : gremlin.curve_handler.AxisCurveData):
        ''' axis curve data'''
        self._curve_data = value
        self._update_input()

    @property
    def is_curve(self) -> bool:
        ''' true if the input is curved '''
        return self._curve_data is not None
    
    def hasAction(self, action_name : str) -> bool:
        ''' true if the specified action type is found in the containers '''
        plugins = ActionPlugins()
        action_type = plugins.get_class(action_name)
        if action_type is not None:
            container : AbstractContainer
            for container in self._containers:
                for action_set in container.action_sets:
                    action : AbstractAction
                    if action_set:
                        for action in action_set:
                            if type(action) == action_type:
                                return True
        return False
    
    def hasConditions(self):
        ''' true if the input item has conditions defined '''
        tracker = ConditionTracker()
        count = tracker.getInputItemConditionCount(self, self.profile_mode) # gremlin.shared_state.current_mode)
        return count > 0
        # for container in self._containers:
        #     if container.condition_count or container.action_condition_count:
        #         return True
        # return False

    def get_valid_container_list(self):
        """Returns a list of valid containers for this input  """
        container_list = []
        for entry in gremlin.plugin_manager.ContainerPlugins().repository.values():
            if not entry.input_types or self.input_type in entry.input_types:
                # if no input types provided, all are ok
                if entry.axis_only:
                    # container requires an axis
                    if not self.is_axis:
                        continue
                container_list.append(entry.name)
        return sorted(container_list)

    def _update_input(self):
        ''' updates input name and registers an axis input if needed '''
        from gremlin.keyboard import key_from_code
        
        input_id = self._input_id
        self.is_axis = False
        if input_id is not None  and self._device_guid is not None:
            if isinstance(input_id, int):
                if self._input_type == InputType.JoystickAxis:
                    self.is_axis = True # indicate we are an axis
                    self._is_button = False
                    el = gremlin.event_handler.EventListener()
                    el.registerInput(self)
                    info = gremlin.joystick_handling.device_info_from_guid(self._device_guid)
                    if info:
                        self._input_name = f"Axis {info.axis_names[input_id-1]}"
                    else:
                        self._input_name = f"Axis {input_id}"


                    mgr = gremlin.ui.axis_calibration.CalibrationManager()
                    self._calibration = mgr.getCalibration(self._device_guid, self._input_id)


                    el.update_input_icons.emit()
                elif self._input_type == InputType.JoystickButton:
                    self._input_name = f"Button {input_id}"
                elif self._input_type == InputType.JoystickHat:
                    self._input_name = f"Hat {input_id}"
                elif self._input_type in (InputType.JoystickButton, InputType.JoystickHat):
                    self._is_axis = False
                    self._is_button = True
                    

            elif self._input_type in (InputType.Keyboard, InputType.KeyboardLatched):
                if isinstance(input_id, gremlin.keyboard.Key):
                    self._input_name =  key_from_code(input_id.scan_code, input_id.is_extended).name
                elif isinstance(input_id, gremlin.ui.keyboard_device.KeyboardInputItem):
                    self._input_name = input_id.display_name
                else:
                    try:
                        self._input_name =  key_from_code(input_id[0],input_id[1]).name
                    except:
                        self._input_name(f"Unable to parse type: {type(input_id).__name__}")
            elif self._input_type == InputType.ModeControl:
                self._input_name = f"Mode [{gremlin.shared_state.edit_mode}] {'enter' if self._input_id == 0 else 'exit'} actions"
            elif self._input_type == InputType.OpenSoundControl:
                self._is_axis = self.input_id.is_axis
                self._is_button = self.input_id.is_button
                
            else:
                self._input_name = f"{InputType.to_string(self._input_type).capitalize()} {input_id}"
    

    def from_xml(self, node, data, skip_root = False):
        """Parses an InputItem node.

        :param node XML node to parse
        """

        #assert data is not None, "InputItem must be provided"

        container_node = node # node that holds the container information
        container_plugins = ContainerPlugins()
        container_tag_map = container_plugins.tag_map
        self.input_type = InputType.to_enum(node.tag)

        if not skip_root: # skip header processing if set

            self._description = safe_read(node, "description", str, "")
            self.always_execute = read_bool(node, "always-execute", False)

            
       
            mode_object = get_mode_object(node)
            assert mode_object is not None,"Mode object could not be derived"

            if self.input_type in (InputType.KeyboardLatched, InputType.Keyboard):
                from gremlin.ui.keyboard_device import KeyboardInputItem
                from gremlin.keyboard import Key
                input_item = KeyboardInputItem()

                if "id" in node.attrib and node.tag == "key":
                    # legacy format
                    scan_code = safe_read(node, "id", int, 0)
                    key = Key(scan_code=scan_code, is_extended=False, is_mouse = False)
                    input_item.key = key
                else:
                    # see if old style keyboard entry
                    if "extended" in node.attrib:
                        scan_code = self.input_id
                        is_extended = read_bool(node, "extended", False)
                        is_mouse = safe_read(node,"mouse", bool, False)
                        key = Key(scan_code=scan_code, is_extended=is_extended, is_mouse = is_mouse)
                        input_item.key = key
                        for child in node:
                            if child.tag == "latched":
                                latched_key = Key(scan_code=safe_read(child,"id",int,0), is_extended= read_bool(child,"extended"))
                                if not latched_key in key.latched_keys:
                                    key.latched_keys.append(latched_key)
                    else:
                        # new style
                        for child in node:
                            if child.tag == "input":
                                input_item.parse_xml(child, data)
                                break
                self.input_type = InputType.KeyboardLatched # force new input type
                #syslog.info(f"Loaded key input: {input_item.display_name}")
                self.setOverrideInputType(InputType.JoystickButton)
                self.input_id = input_item



            elif self.input_type == InputType.Midi:
                # midi data
                from gremlin.ui.midi_device import MidiInputItem
                midi_input_item = MidiInputItem(parent = mode_object)
                for child in node:
                    if child.tag == "input":
                        midi_input_item.parse_xml(child, data)
                self.input_id = midi_input_item
                if midi_input_item.is_axis:
                    self.setOverrideInputType(InputType.JoystickAxis)
                else:
                    self.setOverrideInputType(InputType.JoystickButton)                
                    

            elif self.input_type == InputType.OpenSoundControl:
                # OSC data
                from gremlin.ui.osc_device import OscInputItem
                osc_input_item = OscInputItem(parent = mode_object)
                for child in node:
                    if child.tag == "input":
                        osc_input_item.parse_xml(child, data)
                self.input_id = osc_input_item
                if osc_input_item.is_axis:
                    self.setOverrideInputType(InputType.JoystickAxis)
                else:
                    self.setOverrideInputType(InputType.JoystickButton)
                

            elif self.input_type == InputType.ModeControl:
                # mode control entries - input id is the only item we need
                self.is_axis = False
                input_id = safe_read(node,"id",int,0)
                self.input_id = gremlin.ui.mode_device.ModeInputModeType(input_id)
                self.setOverrideInputType(InputType.JoystickButton)
                self.descriptionReadOnly = True

            elif self.input_type == InputType.State:
                # state defaults to a button type
                self.setOverrideInputType(InputType.JoystickButton)
            
                


            elif self.input_type == InputType.JoystickAxis:
                # check for curve data
                for child in node:
                    if gremlin.base_profile._is_curve_tag(child.tag):
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
            

            assert self.input_id is not None,"Error processing input - check types"
                

        
        for child in container_node:
            if child.tag in ("latched", "input", "keylatched") or gremlin.base_profile._is_curve_tag(child.tag):
                # ignore extra data
                continue
            if not "type" in child.attrib:
                syslog.error(
                    f"XML {child.tag} is missing container 'type' attribute"
                )
                continue 
            container_type = child.get("type")
            
            if container_type not in container_tag_map:
                syslog.warning(
                    f"Unknown container type used: {container_type}"
                )
                continue
            entry = container_tag_map[container_type](self)
            entry.from_xml(child, data)
            self.add_container(entry)
            if hasattr(entry, "action_model"):
                entry.action_model = self.containers
            container_plugins.set_container_data(self, entry)

        # register joystic axis items

    def is_valid_for_save(self) -> bool:
        ''' true if the item has something to save to a profile '''
        from gremlin.keyboard import Key
        if self.input_type in (InputType.Keyboard, InputType.KeyboardLatched):
            # if isinstance(self.input_id, Key):
            #     # has a key definition, save
            return True
        elif self.input_type in (InputType.Midi, InputType.OpenSoundControl):
            return True
        elif hasattr(self.input_id,"to_xml"):
            # has a custom input that returns an XML node
            return True
            
        if not self._containers and not self._description and not self.always_execute:
            # has no containers, no description and execute flag is True (default)
            return False
        return True


    def to_xml(self, parent_node = None):
        """Generates a XML node representing this object's data.

        :return XML node representing this object
        """
        from gremlin.keyboard import Key
        if parent_node is None:
            if self.input_type == InputType.ModeControl:
                pass
                
            node = etree.Element(InputType.to_string(self.input_type))
            container_node = node # default container node to the input node
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
                if child is not None:
                    node.append(child)
            else:
                node.set("id", safe_format(self.input_id, int))
        else:
            node = parent_node
            container_node = node

        if self.curve_data is not None:
            curve_node = self.curve_data._generate_xml()
            node.append(curve_node)


        if self.always_execute:
            node.set("always-execute", "True")

        if self._description:
            node.set("description", safe_format(self._description, str))
        else:
            node.set("description", "")
        
        for entry in self.containers:
            # gremlinex change: containers can still be saved if they are invalid if they are still being configured:
            valid = entry.is_valid_for_save()
            if valid:
                container_node.append(entry.to_xml())
            else:
                if gremlin.config.Configuration().verbose:
                    syslog.info(f"SaveProfile: input: {self.input_type} {InputType.to_display_name(self.input_type)} input id: {self.input_id} container has no data - won't save {entry.name}")

        return node

    def get_device_type(self):
        """Returns the DeviceType of this input item.

        :return DeviceType of this entry
        """
        return self._device_name

    def get_device_type(self):
        """Returns the DeviceType of this input item.

        :return DeviceType of this entry
        """
        return self._device_type
        

    def get_input_type(self):
        """Returns the type of this input.

        :return Type of this input
        """
        if hasattr(self,"getOverrideInputType"):
            return self.getOverrideInputType()
        return self.input_type

    @property
    def display_name(self):
        if self.is_action:
            return "this action"
        ''' gets a display name for this input '''
        if self._input_type == InputType.JoystickAxis:
            return f"Axis {self._input_id}"
        elif self._input_type == InputType.JoystickButton:
            return f"Button {self._input_id}"
        elif self._input_type == InputType.JoystickHat:
            return f"Hat {self._input_id}"
        elif self._input_type in (InputType.Keyboard, InputType.KeyboardLatched):
            return f"Key {self._input_id.display_name}"
        elif self._input_type == InputType.OpenSoundControl:
            return f"OSC {self._input_id.message if self._input_id.message else '(undefined)'}"
        elif self._input_type == InputType.Midi:
            return f"Midi {self._input_id.display_name}"
        elif self._input_type == InputType.ModeControl:
            return f"{gremlin.ui.mode_device.ModeInputModeType.to_display_name(self._input_id)}"
        elif self._input_type == InputType.State:
            return f"State: {self._input_id}"
        return f"Unknown input: {self._input_type}"
    

    

    @property
    def debug_display(self):
        ''' debug string for this item'''
        return f"InputItem: {gremlin.shared_state.get_device_name(self.device_guid)} Input: {InputType.to_display_name(self.input_type)} Type: {self.display_name} mode: {self.profile_mode}"

    # def __eq__(self, other):
    #     """Checks whether or not two InputItem instances are identical.

    #     :return True if they are identical, False otherwise
    #     """
    #     return self.__hash__() == other.__hash__()

    def __hash__(self):
        """Returns the hash of this input item.

        The hash takes into account to which device and mode the input item is
        bound.

        :return hash of this InputItem instance
        """
        if not self._name and not self._device_guid:
            current = self.parent
            while current:
                if self._device_guid is None and hasattr(current,"device_guid"):
                    self._device_guid = current.device_guid
                if self._name is None and hasattr(current, "name"):
                    self._name = current.name
                if self._name and self._device_guid:
                    break
                current = current.parent
        return hash((
            self._device_guid,
            self._name,
            self.input_type,
            self.input_id)
        )
    

class ModeNode(anytree.NodeMixin):
    ''' mode tree node '''
    def __init__(self, name : str = None, mode_object = None):
        self.name = name
        self.mode_object = mode_object

    @property
    def parent_mode(self) -> str:
        ''' gets the parent mode name, None if none'''
        if self.parent and self.parent.name:
            return self.parent.name
        return None

class Profile():

    """Stores the contents of an entire configuration profile.

    This includes configurations for each device's modes.
    """


    def __init__(self, parent = None):
        """Constructor creating a new instance."""
        import gremlin.ui.state_device

        self._mode_tree = None # holds the mode tree (anytree, m73 and later) - this holds the profile's mode hiarchy
        self.devices : dict[Device] = {} # holds devices attached to this profile
        self.vjoy_devices = {}
        self.merge_axes = []
        self.plugins = []
        self.settings = Settings(self)
        self.parent = parent
        self._profile_fname = None # the file name of this profile
        self._profile_name = None # the friendly name of this profile
        self._start_mode = "Default" # startup mode for this profile (this will be either the default mode, or the last used mode)
        self._default_start_mode = "Default"  # default startup mode for this profile
        self._last_runtime_mode = "Default" # last active mode
        self._last_edit_mode = "Default"
        self._restore_last_mode = False # True if the profile should start with the last active mode (profile specific)
        self._dirty = False # dirty flag - indicates the profile data was changed but not saved yet
        self._profile_data : Profile
        self._force_numlock_off = True # if set, forces numlock to be off if it isn't so numpad keys report the correct scan codes
        self._simconnect_modes = {} # map of simconnect startup modes to aicraft - the key is the SimconnectAicraftDefinition key which is unique per aicraft that can be loaded by MSFS
        self._substitution_map = {} # map of device GUID to any new device GUID for the load process
        self._profile_graph = gremlin.profile_graph.ProfileGraph()
        self._loaded = False
        self.state = gremlin.ui.state_device.StateData()
        self.state.clear()
        self._start_state = {}  # profile startup output state - index by [device_id (str)][buttons/axis (str)][id (int)] = value (float or bool)

        el = gremlin.event_handler.EventListener()
        el.edit_mode_changed.connect(self._edit_mode_changed_cb)
        
        self.initialize_regular_devices() # non joystick devices

    def unload(self):
        ''' unloads the current profile - clears all references and unhooks events '''
        el = gremlin.event_handler.EventListener()
        el.edit_mode_changed.disconnect(self._edit_mode_changed_cb)
        self.devices : dict[Device] = {} # holds devices attached to this profile
        self.vjoy_devices = {}
        self.merge_axes = []
        self.plugins = []
        self._simconnect_modes = {} # map of simconnect startup modes to aicraft - the key is the SimconnectAicraftDefinition key which is unique per aicraft that can be loaded by MSFS
        self._substitution_map = {} # map of device GUID to any new device GUID for the load process
        self._profile_graph = gremlin.profile_graph.ProfileGraph()
        self.state.clear()
        self._loaded = False
        
    @property
    def loaded(self) -> bool:
        ''' true if the profile loaded ok '''
        return self._loaded

    def setLoaded(self, value: bool):
        ''' marks the profile as loaded '''
        self._loaded = value

    @property
    def graph(self) -> gremlin.profile_graph.ProfileGraph:
        return self._profile_graph

    def _evaluate_hash(self, obj, path):
        print (path)
        return False

    def getMappingHash(self):
        ''' gets the hash value of the device mapping '''
        xml = self.to_xml()
        return hash(xml)
    
    # startup state
    def getStartButtonState(self, device_id : str, id : int ) -> bool:
        ''' returns the startup button state for that device/button '''
        if device_id in self._start_state:
            if "buttons" in self._start_state[device_id]:
                if id in self._start_state[device_id]["buttons"]:
                    return self._start_state[device_id]["buttons"][id]
        return False
    
    def setStartButtonState(self, device_id : str, id : int, state : bool):
        if not device_id in self._start_state:
            self._start_state[device_id] = {}
        if not "buttons" in self._start_state[device_id]:
            self._start_state[device_id]["buttons"] = {}
        self._start_state[device_id]["buttons"][id] = state

    def getStartAxisValue(self, device_id : str, id : int ) -> float:
        ''' returns the startup axis value for that device/axis, returns None if not set '''
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
    
    def setStartAxisValue(self, device_id : str, id : int, value : float):
        ''' sets a start value for a given vjoy device / id'''
        if not device_id in self._start_state:
            self._start_state[device_id] = {}
        if not "axis" in self._start_state[device_id]:
            self._start_state[device_id]["axis"] = {}
        self._start_state[device_id]["axis"][id] = value
        verbose = gremlin.config.Configuration().verbose_mode_output
        if verbose:
            device = gremlin.joystick_handling.get_device(device_id)
            syslog.info(f"Default axis value: vjoy SET: {device.vjoy_id} axis: {id} value: {value:0.3f}")


    def getStartAxisEnabled(self, device_id : str, id : int ) -> bool:
        ''' returns the startup axis value for that device/axis is enabled  returns None if not set '''
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
    
    def setStartAxisEnabled(self, device_id : str, id : int, enabled : bool):
        ''' sets a start value enabled flag for a given vjoy device / id'''
        if not device_id in self._start_state:
            self._start_state[device_id] = {}
        if not "enabled" in self._start_state[device_id]:
            self._start_state[device_id]["enabled"] = {}
        verbose = gremlin.config.Configuration().verbose_mode_output
        if verbose:
            device = gremlin.joystick_handling.get_device(device_id)
            syslog.info(f"Default axis value enabled SET: vjoy: {device.vjoy_id} axis: {id} value: {enabled}")
        self._start_state[device_id]["enabled"][id] = enabled
    

    def setSimconnectMode(self, key, mode):
        ''' sets the simconnect startup mode for a given aicraft key - the key comes from the SimconnectAicraftDefinition for the aircraft'''
        # key is  (item.id, item.mode)
        # assert len(key) == 2
        # key_ap, key_cp = key
        # assert key_ap,"Invalid AP key"
        # assert key_cp,"Invalid CP key"
        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        if verbose: syslog.info(f"Profile: SimConnectMode: associating [{key}] with profile mode [{mode}]")
        if not isinstance(key, tuple):
            key = (key, key) # make it a tuple
        self._simconnect_modes[key] = mode

    def hasSimconnectMode(self, key) -> bool:
        ''' true if the profile has a simconnect mapping for this key '''
        if isinstance(key, tuple):
            return key in self._simconnect_modes
        # single key mode
        key = key.casefold()
        keys = [k for (_, k) in self._simconnect_modes.keys()]
        return key in keys


    def getSimconnectMode(self, key):
        ''' gets the simconnect startup mode for a given aicraft key - the key comes from the SimconnectAicraftDefinition for the aircraft'''
        verbose = gremlin.config.Configuration().verbose_mode_simconnect
        if not isinstance(key, tuple):
            key = key.casefold()
            key = (key, key)
        if key in self._simconnect_modes:
            mode = self._simconnect_modes[key]
            if verbose: syslog.info(f"Profile: SimConnectMode: found [{key}] with profile mode [{mode}]")
            return mode
        if verbose: syslog.info(f"Profile: SimConnectMode: no saved mode found for [{key}]")
        return None


    @QtCore.Slot()        
    def _edit_mode_changed_cb(self):
        ''' available mode list has changed - check data '''

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
            for mode in device.modes.keys():
                if not mode in modes:
                    remove_list.append(mode)

            for mode in remove_list:
                if mode in device.modes:
                    del device.modes[mode]

        # check default startup mode
        mode = self._default_start_mode
        if not mode in modes:
            self._default_start_mode = self.get_default_mode()
            

    @property
    def dirty(self):
        return self._dirty

    @property
    def name(self):
        return self._profile_name
    

    def get_ordered_device_list(self) -> list[Device]:
        ''' gets the devices ordered by the current UI order '''

        if gremlin.shared_state.ui is not None:
            id_list = gremlin.shared_state.ui.get_ordered_device_guid_list()
        else:
            id_list = [device.device_guid for device in self.devices.values()]
        device_list = []
        for id in id_list:
            if id in self.devices.keys():
                device_list.append(self.devices[id])
        return device_list
    

    def initialize_joystick_device(self, device, modes):
        """Ensures a joystick is properly initialized in the profile.

        :param device the device to initialize
        :param modes the list of modes to be present
        """
        new_device = Device(self)
        new_device.name = device.name
        new_device.device_guid = device.device_guid
        new_device.type = DeviceType.Joystick
        self.devices[device.device_guid] = new_device

        for mode in modes:
            new_device.ensure_mode_exists(mode)
            new_mode = new_device.modes[mode]
            # Touch every input to ensure it gets default initialized
            for i in range(device.axis_count):
                if i >= len(device.axismap_list):
                    syslog.error(
                        f"{device.name,} invalid axis request { device.axis_count} < {i}"
                    )
                else:
                    new_mode.get_data(
                        InputType.JoystickAxis,
                        device.axismap_list[i].axis_index
                    )
            for i in range(1, device.button_count+1):
                new_mode.get_data(InputType.JoystickButton, i)
            for i in range(1, device.hat_count+1):
                new_mode.get_data(InputType.JoystickHat, i)


    def initialize_regular_devices(self):
        ''' setup suported non joystick devices '''
        
        # Keyboard
        device_guid = gremlin.shared_state.keyboard_tab_guid
        device_type = DeviceType.Keyboard
        new_device = Device(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        new_device.type = device_type
        self.devices[device_guid] = new_device

        # MIDI
        device_guid = gremlin.shared_state.midi_tab_guid
        device_type = DeviceType.Midi
        new_device = Device(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        new_device.type = device_type
        self.devices[device_guid] = new_device

        # OSC
        device_guid = gremlin.shared_state.osc_tab_guid
        device_type = DeviceType.Osc
        new_device = Device(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        new_device.type = device_type
        self.devices[device_guid] = new_device

        # mode control
        device_guid = gremlin.shared_state.mode_tab_guid
        device_type = DeviceType.ModeControl
        new_device = Device(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        new_device.type = device_type
        self.devices[device_guid] = new_device

        # state data
        self.state = gremlin.ui.state_device.StateData()
        device_guid = gremlin.shared_state.state_tab_guid
        device_type = DeviceType.State
        new_device = Device(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        new_device.type = device_type
        self.devices[device_guid] = new_device


    def modeTree(self) -> Node:
        ''' returns an anytree node - nodes contain the name of the mode '''
        self._ensure_mode_tree()
        return self._mode_tree
    
    def _inheritance_tree_to_labels(self, labels, tree, level):
        """Generates labels to use in the dropdown menu indicating inheritance.

        :param labels the list containing all the labels
        :param tree the part of the tree to be processed
        :param level the indentation level of this tree
        """
        # skip the root node
        for child in tree.children:
            for pre, _, node in anytree.RenderTree(child, style=gremlin.ui.ui_common.ModeStyle()):
                labels.append((node.name,f"{pre}{node.name}"))

    def get_mode_display_list(self) -> list:
        ''' gets a pairs (display_name, mode) '''
        
        mode_list = []
        
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
            if mode_name == master_mode:
                continue # special mode
            mode_list.append((display_name, mode_name))


        return mode_list
    
    def _ensure_mode_tree(self):
        
        if not self._mode_tree:
            self._mode_tree = ModeNode()
        
            # add default mode
            default_mode = ModeNode("Default")
            default_mode.parent = self._mode_tree

            # add master mode
            master_mode_name = gremlin.shared_state.master_mode
            master_mode = ModeNode(master_mode_name)
            master_mode.parent = self._mode_tree

    
    def dumpModeTree(self):
        ''' dumps the current mode tree '''
        for pre, fill, node in anytree.RenderTree(self._mode_tree, style=anytree.AsciiStyle()):
            syslog.info(f"{pre}{node.name if node.name else "root"}")


    def build_inheritance_tree(self, as_tree = False):
        ''' returns the mode tree (new in m73)'''
        self._ensure_mode_tree()
        return self._mode_tree
    

        
    def getModeHierarchy(self, mode: str):
        ''' gets the mode hierarchy for a given mode'''
        self._ensure_mode_tree()
        if mode:
            node = anytree.find(self._mode_tree, lambda node: self._compare_mode(node, mode))
            if node:
                mode_list = [node.name]
                mode_list.extend([n.name for n in node.ancestors if n.name])
                return mode_list
        return []
            



    
    def traverse_mode(self):
        ''' returns the current mode list as a list of (level, mode) '''
        nodes = [(node.depth-1, node.name) for node in anytree.PreOrderIter(self._mode_tree) if node.name]
        return nodes
    
    def mode_map(self):
        ''' converts the mode tree to a map [mode] = [children modes]'''
        data = {}
        for node in anytree.PreOrderIter(self._mode_tree):
            if node.name:
                data[node.name] = [n.name for n in node.children]
        return data


    
    def get_root_mode(self):
        ''' gets the top mode from a profile - that would be the default startup mode - sorted by name of the root nodes'''

        if self._mode_tree:
            return next((node.name for node in self._mode_tree.children), None)
        return None

    def get_mode_ancestors(self, mode : str, include_self = False):
        ''' gets a list of parent modes starting with the current mode '''
        node = anytree.find(self._mode_tree, lambda node: node.name == mode)
        if node is None:
            return []
        mode_list = [node.name] if include_self else []
        mode_list.extend([n.name for n in node.ancestors if n.name])
        return mode_list
    
    
    def get_mode_descendants(self, mode : str, include_self = False):
        ''' gets a list of child modes starting with the current mode '''
        node = anytree.find(self._mode_tree, lambda node: node.name == mode)
        if node is None:
            return []
        mode_list = [node.name] if include_self else []
        mode_list.extend([n.name for n in node.descendants if n.name])
        return mode_list
    
    def set_last_runtime_mode(self, mode : str):
        ''' sets the last used mode - this is persisted in the configuration  '''
        if mode != self._last_runtime_mode:
            self._last_runtime_mode = mode
            config = gremlin.config.Configuration()
            self._last_runtime_mode = mode
            config.set_last_runtime_mode(self._profile_fname, mode)
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                syslog.info(f"PROFILE: [{self._profile_name}] store last runtime mode: [{mode}]")

    def get_last_runtime_mode(self):
        ''' gets the last used mode '''
        config = gremlin.config.Configuration()
        mode = config.get_profile_last_runtime_mode()
        if mode is not None:
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                syslog.info(f"PROFILE: [{self._profile_name}] get last runtime mode: [{mode}]")
            self._last_runtime_mode = mode
        return self._last_runtime_mode
    
    def set_last_edit_mode(self, mode):
        ''' sets the last used mode - this is persisted in the configuration  '''
        if mode != self._last_edit_mode:
            self._last_edit_mode = mode
            config = gremlin.config.Configuration()
            self._last_edit_mode = mode
            config.set_profile_last_edit_mode(mode)
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                syslog.info(f"PROFILE: [{self._profile_name}] store last edit mode: [{mode}]")


    def get_last_edit_mode(self):
        ''' gets the last used mode '''
        if self._last_edit_mode is None:
            config = gremlin.config.Configuration()
            mode = config.get_profile_last_edit_mode()
            if mode is not None:
                verbose = gremlin.config.Configuration().verbose
                if verbose:
                    syslog.info(f"PROFILE: [{self._profile_name}] get last edit mode: [{mode}]")
                    self._last_edit_mode = mode
        return self._last_edit_mode



    def get_force_numlock(self):
        return self._force_numlock_off
    
    def set_force_numlock(self, value):
        self._force_numlock_off = value
    

    def mode_list(self):
        """Returns a list of all modes based on the given node.

        :param node a node from a profile tree
        :return list of mode names
        """

        if self._mode_tree:
            modes = self.get_modes()
            return modes
        return []


    def add_mode(self, name, parent_name = None, emit = True) -> bool:
        import gremlin.event_handler
        ''' adds a new mode parented to inherited_name
        
        :param name: the name of the mode to add (case sensitive)
        :param parent_name: the name of the parent mode, can be none if the mode is a root mode
        :param emit: if set, fires an event that updates the UI
        :returns: True on
        
        
        '''
        if not name:
            return False
        
        name = name.strip()
        if name in self.mode_list():
            syslog.warning(f"Add Mode: error: mode {name} already exists")
            QMessageBox.warning(self, title = "Warning", text = f"Cannot add mode [{name}]: a mode by that name already exists")
            return False
            
        
        for device in self.devices.values():
            new_mode = Mode(device)
            new_mode.name = name
            if parent_name is not None:
                new_mode.inherit = parent_name
            else:
                new_mode.inherit = self.get_default_mode()
            new_mode.parent = device
            device.modes[name] = new_mode

        if self._mode_tree:
            # add the mode 
            node = ModeNode(name)
            parent_node = self._mode_tree
            if parent_name:
                existing_parent_node = next((node for node in self._mode_tree.descendants if node.name == parent_name), None)
                if existing_parent_node:
                    parent_node = existing_parent_node
                
            node.parent = parent_node
                    



        if emit:
            eh = gremlin.event_handler.EventListener()
            eh.edit_mode_changed.emit(name)
        return True
    

    def set_mode_parent(self, name, inherited_name, emit = True) -> bool:
        ''' sets the parent of a current mode'''

        node = anytree.find(self._mode_tree, lambda node: node.name == name)
        if node is None:
            return
        
        node_parent = anytree.find(self._mode_tree, lambda node: node.name == inherited_name)
        if node_parent is None:
            return
        
        node.parent = node_parent

        mode_list = self.mode_list()
        if name in mode_list and inherited_name in mode_list:
            for device in self.devices.values():
                 if name in device.modes.keys():
                    device.modes[name].inherit = inherited_name
        if emit:
            eh = gremlin.event_handler.EventListener()
            eh.edit_mode_changed.emit(name)
        return True
        
    
    def mode_tree(self, as_tree = False):
        ''' gets the parent/child hiearchy of modes - returns a map or an anytree '''
        if as_tree and self._mode_tree:
            return self._mode_tree
        return self.build_inheritance_tree(as_tree)
        

    def rename_mode(self, current_name, new_name, emit = True):
        if new_name in self.mode_list():
            QMessageBox.warning(self, title= "Warning",text = f"Cannot rename mode [{current_name}] to [{new_name}]: [{new_name}] already exists")
            return False
        
        self._ensure_mode_tree()
        node = anytree.find(self._mode_tree, lambda node: node.name == current_name)
        if not node:
            QMessageBox.warning(self, title= "Warning",text = f"Cannot rename mode [{current_name}] to [{new_name}]: [{current_name}] not found")
            return False
        
        node.name = new_name

        for device in self.devices.values():

            device.modes[new_name] = device.modes[current_name]
            device.modes[new_name].name = new_name
            del device.modes[current_name]
      

            # Update inheritance information
            for mode in device.modes.values():
                if mode.inherit == current_name:
                    mode.inherit = new_name

            self._profile.reload_modes()

            # rename the startup mode if it's the same
            if current_name == gremlin.shared_state.current_profile.get_start_mode():
                self._profile.set_start_mode(new_name)

        if gremlin.shared_state.edit_mode == current_name:
            gremlin.shared_state.edit_mode = new_name

        if gremlin.shared_state.runtime_mode == current_name:
            gremlin.shared_state.runtime_mode = new_name                

        # tell the UI of the name change
        if emit:
            el = gremlin.event_handler.EventListener()
            el.mode_name_changed.emit(current_name, new_name)

        return True
    
    def remove_device(self, device : dinput.DeviceSummary):
        ''' removes the specified device from the profile '''
        if device.connected:
            syslog.error(f"PROFILE: cannot remove a connected device: {device.name}")
            return
        
        gremlin.util.pushCursor()
        device_guid = device.device_guid
        if device_guid in self.devices:
            del self.devices[device_guid]

        gremlin.joystick_handling.removeDevice(device)

        node = self.graph.get_device_node(device.device_guid)
        if node is not None:
            node.parent = None

        ec = gremlin.execution_graph.ExecutionContext()
        ec.reset(True) # reset and rebuild data around the profile
        
        el = gremlin.event_handler.EventListener()
        el.request_reload.emit()
        gremlin.util.popCursor()


    def remove_mode(self, name, force = False, emit = True):
        ''' removes a mode from this profile '''
        
        import gremlin.event_handler
        mode_list = self.mode_list()
        if not name in self.mode_list():
            syslog.warning(f"Remove Mode: error: mode {name} not found")
            return False
                
        if not force and len(mode_list) == 1:
            QMessageBox.warning(self, title= "Warning",text = f"Cannot delete mode [{name}]: The profile must have at least one mode")
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
            node = next((node for node in self._mode_tree.descendants if node.name == name), None)
            if node:
                # reparent children
                for child in node.children:
                    child.parent = node.parent
                node.parent = None # delete the node

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
    
    def get_modes(self, casefold = False) -> list[str]:
        ''' get all profile mode names as a list '''

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
    
    def get_mode_objects(self) -> list[Mode]:
        ''' gets the mode objects in the device list '''
        modes = []
        for device in self.devices.values():
            for mode in device.modes.values():
                modes.append(mode)
            break

        return modes

    
    def get_mode_map(self, casefold = False) -> dict:
        ''' gets profile modes as a map of profiles, keyed by name, holds the parent name '''

        mode_map = {}
        self._ensure_mode_tree()
        if self._mode_tree:
            if casefold:
                modes = [node.name.casefold() for node in self._mode_tree.descendants]    
            else:
                modes = [node.name for node in self._mode_tree.descendants]

        
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
    
    def get_mode_branch(self, mode : str, ancestors : bool = True, descendants : bool = False) -> list:
        ''' gets the mode branch for the current mode - this is the list of the mode, and all parent modes'''
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
        
    
    def reload_modes(self, update_devices = False):
        ''' reloads the mode tree from the device data 
        
        :param update_devices: if set, updates the device to new modes to complete any missing mode sets (do this when loading from XML only)
        
        '''
        self._mode_tree = Node("") # root node
        
        mode_list = []
        node_map = {}
        node_map[""] = self._mode_tree
        inherit_map = {}

        mode_nodes = [node for node in self._profile_graph.root.descendants if node.nodeType == gremlin.profile_graph.ProfileNodeType.Mode]
        for node in mode_nodes:
            mode_name = node.name
            if not mode_name in mode_list:
                m_node = Node(mode_name)
                m_node.parent = self._mode_tree # default parent node
                node_map[mode_name] = m_node
                mode_list.append(mode_name)
                inherit_map[mode_name] = node.inherit

        for mode_name in mode_list:
            m_node = node_map[mode_name]
            parent_mode_name = inherit_map[mode_name]
            if parent_mode_name:
                m_parent_node = node_map[parent_mode_name]
                m_node.parent = m_parent_node
        
        verbose = gremlin.config.Configuration().verbose
        if verbose: self.dumpModeTree()
            
    
    def rename_mode(self, old_mode:str, new_mode:str, emit = False) -> bool:
        ''' renames an existing mode to a new mode '''
        syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose
        if old_mode == new_mode:
            if verbose: syslog.warning(f"PROFILE: rename [{old_mode}] and [{new_mode}] are the same, skip")   
            return False
        

        # mode tree
        node = anytree.find(self._mode_tree, lambda node: node.name == old_mode)
        if not node:
            if verbose: syslog.error(f"PROFILE: rename [{old_mode}] to [{new_mode}] - [{old_mode}] not found in the profile")
            return False
        
        new_node = anytree.find(self._mode_tree, lambda node: node.name == new_mode)
        if new_node:
            # already exist
            if verbose: syslog.error(f"PROFILE: rename [{old_mode}] to [{new_mode}] - [{old_mode}] already exists in the profile")
            return False
        
        node.name = new_mode

        # mode device objects
        mode : Mode
        for device in self.devices.values():
            for mode in device.modes.values():
                if mode.name == old_mode:
                    #if verbose: syslog.info(f"PROFILE: rename [{old_mode}] to [{new_mode}]")
                    mode.name = new_mode

        return True


    

    def is_mode(self, mode) -> bool:
        ''' true if the mode exists in the current profile '''
        node = anytree.find(self._mode_tree, lambda node: self._compare_mode(node, mode))
        return node is not None
    

    def _compare_mode(self, node, mode : str):
        ''' comparator for modes in the mode tree '''
        
        if mode and node.name:
            mode_text = mode.casefold().strip()
            return node.name.casefold() == mode_text
        return False

    

    def find_mode(self, mode) -> str:
        ''' finds a mode by name or value '''
        if self._mode_tree is not None:
            node = anytree.find(self._mode_tree, lambda node: self._compare_mode(node, mode))
            if node:
                return node.name
        return None # not found
    
    def find_mode_node(self, mode : str) -> ModeNode:
        ''' gets the graph mode node for the given name '''
        return anytree.find(self._mode_tree, lambda node: self._compare_mode(node, mode))



    def list_actions(self):
        ''' lists all actions in the current profile '''
        # Create a list of all used remap actions
        remap_actions = []
        for dev_guid in self.devices.keys():
            dev = self.devices[dev_guid]
            for mode_name in dev.modes.keys():
                mode = dev.modes[mode_name]
                for input_type in mode.config.keys():
                    for item in mode.config[input_type].values():
                        for container in item.containers:
                            remap_actions.extend(
                                extract_remap_actions(container.action_sets)
                            )

        return remap_actions

    def list_unused_vjoy_inputs(self):
        """Returns a list of unused vjoy inputs for the given profile.

        :return dictionary of unused inputs for each input type
        """
        vjoy_devices = gremlin.joystick_handling.vjoy_devices()

        # Create list of all inputs provided by the vjoy devices
        vjoy = {}
        for entry in vjoy_devices:
            vjoy[entry.vjoy_id] = {"axis": [], "button": [], "hat": []}
            for i in range(entry.axis_count):
                vjoy[entry.vjoy_id]["axis"].append(
                    entry.axismap_list[i].axis_index
                )
            for i in range(entry.button_count):
                vjoy[entry.vjoy_id]["button"].append(i+1)
            for i in range(entry.hat_count):
                vjoy[entry.vjoy_id]["hat"].append(i+1)

        # Create a list of all used remap actions
        remap_actions = self.list_actions()

        # Remove all remap actions from the list of available inputs
        for act in remap_actions:
            # Skip remap actions that have invalid configuration
            if act.input_type is None or act.input_type not in (InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat):
                continue
            

            type_name = InputType.to_string(act.input_type)
            if act.vjoy_input_id in [0, None] \
                    or act.vjoy_device_id in [0, None] \
                    or act.vjoy_input_id not in vjoy[act.vjoy_device_id][type_name]:
                continue

            idx = vjoy[act.vjoy_device_id][type_name].index(act.vjoy_input_id)
            del vjoy[act.vjoy_device_id][type_name][idx]

        return vjoy
    

    
    
    @property
    def profile_file(self):
        ''' gets the profile file name normalized for a PC case insentitive '''
        
        return self._profile_fname
    
    def setProfileFile(self, value):
            ''' sets the profile save file xml '''
            if value:
                self._profile_fname = gremlin.util.fix_path(value)
            else:
                self._profile_fname = None
    
    def get_default_mode(self):
        ''' gets the default mode for this profile - this is the mode used if the default startup mode is not specified '''
        modes = self.get_root_modes()
        if modes:
            return modes[0]


    def from_xml(self, fname, data = None):
        """Parses the profile XML document into the profile data structure.

        :param fname the path to the XML file to parse
        """
        # Check for outdated profile structure and warn user / convert
        verbose = gremlin.config.Configuration().verbose
        import_data = ProfileImportData()
        import_data.used_ids = {} # reset used list
        
        profile_converter = gremlin.profile.ProfileConverter()
        profile_was_updated = False
        if not profile_converter.is_current(fname):
            syslog.warning("Outdated profile, converting")
            profile_converter.convert_profile(fname)
            profile_was_updated = True

        tree = etree.parse(fname)
        root = tree.getroot()

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
            self._force_numlock_off = safe_read(root, "force_numlock", bool, True)

        # state data - read first because states can be referenced by nodes
        nodes = root.xpath("//states")
        if not nodes:
            # not found
            self.state.clear()
        for node in nodes:
            self.state.from_xml(node)




        # Parse each device into separate DeviceConfiguration objects
        devices = root.xpath("//profile/devices/device")
        for child in devices:
            device = Device(self)
            device.from_xml(child, data)
            self.devices[device.device_guid] = device


        # Parse each vjoy device into separate DeviceConfiguration objects
        for child in root.iter("vjoy-device"):
            device = Device(self)
            device.from_xml(child, data)
            self.vjoy_devices[device.device_guid] = device

        # parse simconnect startup entries
        self._simconnect_modes = {}
        for child in root.iter("simconnect"):
            key_cp = safe_read(child,"key_cp",str, "")
            key_ap = safe_read(child,"key_ap",str, "")
            mode = safe_read(child,"mode", str, "")
            key = (key_cp, key_ap)
            self._simconnect_modes[key] = mode


        # extract the mode list
        mode_node_map = {}
        nodes = {}
        mode_root = ModeNode("")  # root mode
        nodes[""] = mode_root
        master_mode_name = gremlin.shared_state.master_mode
        mode_nodes = root.xpath("//device//mode")
        for mode_node in mode_nodes:
            mode = mode_node.get("name")
            if mode in mode_node_map:
                continue # already known

            if "inherit" in mode_node.attrib:
                parent_mode = mode_node.get("inherit")
                if not parent_mode in mode_node_map:
                    tree_parent_mode = ModeNode(parent_mode)
                    nodes[parent_mode] = tree_parent_mode
                    mode_node_map[parent_mode] = tree_parent_mode
                    tree_parent_mode.parent = mode_root
            else:
                parent_mode = None

            if not mode in mode_node_map:
                tree_node = ModeNode(mode)
                mode_node_map[mode] = tree_node
                nodes[mode] = tree_node
                if parent_mode:
                    parent_tree_node = nodes[parent_mode]
                    tree_node.parent = parent_tree_node
                    continue
            
                # no parent - parent to root
                tree_node.parent = mode_root

        if not master_mode_name in mode_node_map:
            # add new master mode for old profiles for manual edits in case the converter didn't catch it
            master_mode = ModeNode(master_mode_name)
            master_mode.parent = mode_root
            mode_node_map[master_mode_name] = mode_root
            nodes[master_mode_name] = master_mode


        mode_list = list(mode_node_map.keys())

        # Ensure that the profile contains an entry for every existing
        # device even if it was not part of the loaded XML and
        # replicate the modes present in the profile. This adds both entries
        # for physical and virtual joysticks.
        devices = gremlin.joystick_handling.all_joystick_devices()
        for dev in devices:
            add_device = False
            if dev.is_virtual and dev.device_guid not in self.vjoy_devices:
                add_device = True
            elif not dev.is_virtual and dev.device_guid not in self.devices:
                add_device = True

            if add_device:
                new_device = Device(self)
                new_device.name = dev.name
                new_device.virtual = True
                if dev.is_virtual:
                    new_device.type = DeviceType.VJoy
                    new_device.device_guid = dev.device_guid
                    self.vjoy_devices[dev.device_guid] = new_device
                else:
                    new_device.type = DeviceType.Joystick
                    new_device.device_guid = dev.device_guid
                    self.devices[dev.device_guid] = new_device

                      

        # Parse merge axis entries
        for child in root.iter("merge-axis"):
            self.merge_axes.append(self._parse_merge_axis(child))

        # Parse settings entries
        self.settings.from_xml(root.find("settings"), data)

        # Parse plugin entries
        for child in root.findall("plugins/plugin"):
            plugin = Plugin(self)
            plugin.from_xml(child, data)
            self.plugins.append(plugin)

        if not self._start_mode:
            # use a default mode
            self._start_mode = self.get_default_mode()

        self._profile_fname = gremlin.util.fix_path(fname)

        name, _ = os.path.splitext(os.path.basename(fname))
        self._profile_name = name

        # update missing modes from devices
        for device in self.devices.values():
            device_modes = [mode.name for mode in device.modes.values()]
            missing_modes = [mode for mode in mode_list if not mode in device_modes]
            for mode_name in missing_modes:
                mode = Mode(device)
                mode.name = mode_name
                node = nodes[mode_name]
                if node.parent and node.parent.name:
                    mode.inherit = node.parent.name
                device.modes[mode_name] = mode


        # read button and axis startup data
        node_devices = root.xpath("//profile/start/devices/device")
        self._start_state.clear()
        for node_device in node_devices:
            device_id = node_device.get("device-guid")
            self._start_state[device_id] = {}
            for node in node_device:
                id = safe_read(node,"id", int, 0)
                if not id:
                    continue
                if node.tag == "button":
                    state = safe_read(node,"value",bool, False)
                    if not "buttons" in self._start_state[device_id]:
                        self._start_state[device_id]["buttons"] = {}
                    self._start_state[device_id]["buttons"][id] = state
                elif node.tag == "axis":
                    if not "axis" in self._start_state[device_id]:
                        self._start_state[device_id]["axis"] = {}
                    if not "enabled" in self._start_state[device_id]:
                        self._start_state[device_id]["enabled"] = {}
                    value = safe_read(node,"value", float, 0.0)
                    self._start_state[device_id]["axis"][id] = value
                    enabled = safe_read(node,"enabled", bool, False)
                    self._start_state[device_id]["enabled"][id] = enabled
                    






        # have config use updated profile settings
        config = gremlin.config.Configuration()
        config.ensure_profile(self)


        # load the profile graph
        self._profile_graph = gremlin.profile_graph.ProfileGraph()
        self._profile_graph.parse_xml(fname)



        # load the mode tree
        self.reload_modes(update_devices = True)

        # clear used memory
        import_data.used_ids = {} # reset used list

        return profile_was_updated
    


    def to_xml(self, fname : str = None):
        """Generates XML code corresponding to this profile.

        :param fname: name of the file to save the XML to, if None the function returns the XML string of the profile
        """
        # Generate XML document
        root = etree.Element("profile")
        root.set("version", str(gremlin.profile.ProfileConverter.current_version))
        root.set("start_mode", self.get_start_mode())
        root.set("default_mode", self.get_default_start_mode())
        root.set("restore_last", str(self._restore_last_mode))
        root.set("force_numlock", str(self._force_numlock_off))

        # mode list
        
        mode_tree_root = self.mode_tree(True)
        root_mode_node = etree.Element("modes")
        root.append(root_mode_node)

        # new as of m73 - new mode node for mode hieararchy
        nodes = {}
        for tree_node in anytree.PreOrderIter(mode_tree_root):
            mode = tree_node.name
            if not mode:
                continue # root node
            node = etree.Element("mode") # new xml child
            node.set("name",mode) # set mode value
            if tree_node.parent:
                parent_mode = tree_node.parent.name
                if parent_mode:
                    node.set("inherit", parent_mode)

            nodes[mode] = node # track it
            parent_mode = tree_node.parent.name if tree_node.parent else None
            root_mode_node.append(node)

        # Device settings
        devices = etree.Element("devices")
        device_list = sorted(
            self.devices.values(),
            key=lambda x: str(x.device_guid)
        )
        # strip the unused nodes that don't contain any data where possible to reduce the size of the profile
        for device in device_list:
            node = device.to_xml()
            if device.device_type == DeviceType.Joystick:
                # remove empty nodes
                for axis_node in node.xpath("//axis"):
                    if not list(axis_node):
                         axis_node.getparent().remove(axis_node)
                for button_node in node.xpath("//button"):
                    if not list(button_node):
                         button_node.getparent().remove(button_node)
                has_container = node.xpath("//container")
                if has_container:
                    devices.append(node)
            elif device.device_type == DeviceType.VJoy:
                has_container = node.xpath("//container")
                if has_container:
                    devices.append(node)
            else:
                # check for inputs
                if device.device_type in (DeviceType.Keyboard, DeviceType.Osc, DeviceType.Midi):
                    has_inputs = node.xpath("//input")
                    if has_inputs:
                        devices.append(node)
                else:
                    devices.append(node)
            
        root.append(devices)

        # simconnect settings
        for key, mode in self._simconnect_modes.items():
            if key:
                if isinstance(key,tuple):
                    key_cp, key_ap = key
                    assert key_cp,"invalid CP key found"
                    assert key_ap,"invalid AP key found"
                else:
                    # single key
                    key_cp = key
                    key_ap = key

                child = etree.Element("simconnect")
                child.set("key_cp",key_cp)
                child.set("key_ap",key_ap)
                child.set("mode", mode)
                root.append(child)

        # VJoy settings
        add_vjoy = False
        vjoy_devices = etree.Element("vjoy-devices")
        for device in self.vjoy_devices.values():
            node = device.to_xml()
            has_container = node.xpath("//container")
            if has_container:
                vjoy_devices.append(node)
                add_vjoy = True
            
        if add_vjoy:
            root.append(vjoy_devices)

        # Merge axis data
        for entry in self.merge_axes:
            node = etree.Element("merge-axis")
            node.set("mode", safe_format(entry["mode"], str))
            node.set("operation", safe_format(
                MergeAxisOperation.to_string(entry["operation"]),
                str
            ))
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
                            if not device_id in dn:
                                node_device = etree.SubElement(node_devices,"device")
                                node_device.set("device-guid", device_id)
                                dn[device_id] = node_device
                            node_button = etree.SubElement(node_device,"button")
                            node_button.set("id", safe_format(id, int))
                            node_button.set("value", safe_format(state,bool))

                if "axis" in self._start_state[device_id]:
                    for id in self._start_state[device_id]["axis"]:
                        if not device_id in dn:
                            node_device = etree.SubElement(node_devices,"device")
                            node_device.set("device-guid", device_id)
                            dn[device_id] = node_device

                        node_axis = etree.SubElement(node_device,"axis")
                        node_axis.set("id", safe_format(id, int))
                        value = self._start_state[device_id]["axis"][id]
                        node_axis.set("value", safe_format(value,float))

                        enabled = self._start_state[device_id]["enabled"][id]
                        node_axis.set("enabled", safe_format(enabled, bool))

                



        # state data
        node = self.state.to_xml()
        root.append(node)

        # Serialize XML document
        tree = etree.ElementTree(root)
        if fname:
            tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")
        else:
            # return the xml string
            return etree.tostring(tree)
        

    def get_device_modes(self, device_guid : dinput.GUID,
                               device_type : DeviceType,
                               device_name : str =None) -> Device:
        """Returns the modes associated with the given device.

        :param device_guid the device's GUID
        :param device_type the type of the device being queried
        :param device_name the name of the device
        :return all modes for the specified device
        """
        if device_type == DeviceType.VJoy:
            if device_guid not in self.vjoy_devices:
                # Create the device
                device = Device(self)
                device.name = device_name
                device.device_guid = device_guid
                device.type = DeviceType.VJoy
                self.vjoy_devices[device_guid] = device
            return self.vjoy_devices[device_guid]

        else:
            if device_guid not in self.devices:
                # Create the device
                device = Device(self)
                device.name = device_name
                device.device_guid = device_guid

                # Set the correct device type
                device.type = device_type
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
            InputType.State
        ]

        # Process all devices
        for dev in self.devices.values():
            for mode in dev.modes.values():
                for input_type in all_input_types:
                    if input_type in mode.config:
                        for item in mode.config[input_type].values():
                            is_empty &= len(item.containers) == 0

        # Process all vJoy devices
        for dev in self.vjoy_devices.values():
            for mode in dev.modes.values():
                for input_type in all_input_types:
                    if input_type in mode.config:
                        for item in mode.config[input_type].values():
                            is_empty &= len(item.containers) == 0

        return is_empty

    def _parse_merge_axis(self, node):
        """Parses merge axis entries.

        :param node the node to process
        :return merge axis data structure parsed from the XML node
        """
        entry = {
            "mode": node.get("mode", None),
            "operation": MergeAxisOperation.to_enum(
                safe_read(node, "operation", str, "average")
            )
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
                    "axis_id": safe_read(n, "axis-id", int, 1)
                }

        return entry

    def get_start_mode(self):
        ''' gets the start mode for this profile '''
        mode = self.find_mode(self._start_mode)
        # verify the mode is in the mode list
        if not mode:        
            modes = self.get_modes()
            mode = modes[0]
            self._start_mode = mode
        if not mode:
            return self.get_default_start_mode()
        return mode
    
    def set_start_mode(self, value : str):
        ''' sets the profile auto-activated start up mode '''
        assert isinstance(value, str)
        self._start_mode = value
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            syslog.info(f"Profile {self.name}: set start mode to {value}")
        self.save()

    def set_default_start_mode(self, value : str):
        ''' sets the profile normal start up mode - this will only be used if the startup mode is not overwritten by the last mode - saving a default start mode also resets the last used start mode
            the mode saved here should be the mode dialog default
        '''
        assert isinstance(value, str)
        self._default_start_mode = value
        self._start_mode = value
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            syslog.info(f"Profile {self.name}: set default start mode to {value}")
        self.save(backup = False)

    def get_default_start_mode(self):
        ''' gets the profile's default startup mode '''
        if not self._default_start_mode:
            # use the default mode if not setup
            self._default_start_mode = self.get_default_mode()
        mode = self._default_start_mode
        modes = self.get_modes()
        if not mode in modes:
            self._default_start_mode = self.get_root_mode()
        return self._default_start_mode
    

    def get_restore_mode(self) -> bool:
        ''' gets the start mode for this profile '''
        return self._restore_last_mode
    
    def set_restore_mode(self, value : bool):
        ''' sets the start up mode '''
        self._restore_last_mode = value
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            syslog.info(f"Profile {self.name}: set auto-restore flag {value}")
        self.save(backup = False)

    def save(self, save_as_name = None, backup = True):
        ''' saves the profile '''

        if save_as_name is None:
            if self._profile_fname is None:
                gremlin.ui.ui_common.MessageBox(prompt = "File is not set, please save the profile first")
                return
            
            assert self._profile_fname,"File name is not set"

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
                    syslog.error(f"BACKUP: unable to create backup folder {backup_path}:  {err}")
                
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
                    modified_data.sort(key = lambda x: x[0])
                    _, oldest_file = modified_data[0]
                    try:
                        os.unlink(oldest_file)
                    except Exception as err:
                        syslog.error(f"BACKUP: save error: Unable to remove oldest backup profile: {oldest_file}:  {err}")    

                # next file
                backup_count=start_count + 1
                backup_file = os.path.join(backup_path, f"{base_name}.{backup_count}.xml")
                try:
                    shutil.copyfile(use_name, backup_file)
                    syslog.error(f"BACKUP: backup profile: {backup_file}")
                except Exception as err:
                    syslog.error(f"BACKUP: save error: Unable to backup profile: {err}")
                    return
                
        if use_name:
            self.to_xml(use_name)
        else:
            self._profile_fname = None
            self._dirty = False

        


class Mode:

    """ mode object - represents the configuration of the mode of a single device."""

    # list of input types to save for each mode
    SaveInputTypes =  [
            InputType.JoystickAxis,
            InputType.JoystickButton,
            InputType.JoystickHat,
            InputType.Keyboard,
            InputType.KeyboardLatched,
            InputType.OpenSoundControl,
            InputType.Midi,
            InputType.ModeControl,
        ]

    def __init__(self, device : Device, is_system = False):
        """Creates a new DeviceConfiguration instance.

        :param device : the device that owns this mode
        :param is_system : true if the mode is a system mode (not user defined) 
        """
        self.parent = device
        self.inherit = None # name of the mode we inherit properties from
        self._name = None # name of the current mode
        self.isSystem = is_system
       
        self.config = {
            InputType.JoystickAxis: {},
            InputType.JoystickButton: {},
            InputType.JoystickHat: {},
            InputType.Keyboard: {},
            InputType.KeyboardLatched: {},
            InputType.OpenSoundControl: {},
            InputType.Midi: {},
            InputType.ModeControl: {}
        }

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str):
        self._name = value.strip() if value else ""

    def setName(self, value : str):
        self._name = value.strip() if value else ""

    def from_xml(self, node, data = None):
        """Parses the XML mode data.

        :param node XML node to parse
        """
        from gremlin.base_profile import InputItem
        name = safe_read(node, "name", str, "")
        if "system" in node.attrib:
            self.isSystem = safe_read(node,"system", bool, False)
        else:
            self.isSystem = False

        name = name.strip()
        self._name = name

        registry = ProfileRegistry()

        self.inherit = node.get("inherit", None)
        
        for child in node:
            item = InputItem(parent = self)
            item.from_xml(child, item) # send owner item to sub components as the data member
            item.device_guid = self.parent.device_guid

            store_item = True
            # This can fail if the device in question is not connected, in
            # which case we'll simply save the action item without
            # verification.
            if item.input_type == InputType.JoystickAxis \
                    and dinput.DILL.device_exists(self.parent.device_guid):
                joy = gremlin.input_devices.JoystickProxy()[self.parent.device_guid]
                if joy is not None:
                    store_item = joy.is_axis_valid(item.input_id)

            if store_item:
                self.config[item.input_type][item.input_id] = item

            registry.registerInputItem(item)
                

    def to_xml(self):
        """Generates XML code for this DeviceConfiguration.

        :return XML node representing this object's data
        """
        node = etree.Element("mode")
        node.set("name", safe_format(self.name, str))
        if self.isSystem:
            node.set("system", safe_format(True, bool))

        if self.inherit is not None:
            node.set("inherit", safe_format(self.inherit, str))
        input_types = Mode.SaveInputTypes
        for input_type in input_types:
            item_list = sorted(
                self.config[input_type].values(),
                key=lambda x: x.input_id
            )
            for item in item_list:
                #if item.is_valid_for_save():
                node.append(item.to_xml())
        return node

    def delete_data(self, input_type, input_id):
        """Deletes the data associated with the provided
        input item entry.

        :param input_type the type of the input
        :param input_id the index of the input
        """
        if input_id in self.config[input_type]:
            del self.config[input_type][input_id]

    def get_data(self, input_type, input_id):
        """Returns the configuration data associated with the provided
        InputItem entry.

        :param input_type the type of input
        :param input_id the id of the given input type
        :return InputItem corresponding to the provided combination of
            type and id
        """
        from gremlin.base_profile import InputItem

        assert input_type in self.config, f"Check configuration initialization - missing new type {input_type} in setup definition"

        if input_id not in self.config[input_type]:
            input_item = InputItem(parent = self)
            input_item.input_type = input_type
            input_item.input_id = input_id
            self.config[input_type][input_id] = input_item
            registry = ProfileRegistry()
            registry.registerInputItem(input_item)
        return self.config[input_type][input_id]

    def set_data(self, input_type, input_id, data):
        """Sets the data of an InputItem.

        :param input_type the type of the InputItem
        :param input_id the id of the InputItem
        :param data the data of the InputItem
        """
        assert(input_type in self.config)
        self.config[input_type][input_id] = data

    def has_data(self, input_type, input_id):
        """Returns True if data for the given input exists, False otherwise.

        :param input_type the type of the InputItem
        :param input_id the id of the InputItem
        :return True if data exists, False otherwise
        """
        return input_id in self.config[input_type]

    def all_input_items(self):
        for input_type in self.config.values():
            for input_item in input_type.values():
                yield input_item




class Plugin:

    """Custom module."""

    def __init__(self, parent):
        self.parent = parent
        self.file_name = None
        self.instances = []

    def from_xml(self, node, data = None):
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
        self.parent = parent # parent holds the module instance
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

    def set_variable(self, name, variable):
        self.variables[name] = variable

    def get_variable(self, name):
        if name not in self.variables:
            var = PluginVariable(self)
            var.name = name
            self.variables[name] = var

        return self.variables[name]

    def from_xml(self, node, data = None):
        verbose = gremlin.config.Configuration().verbose
        self.name = safe_read(node, "name", str, "")
        for child in node.iter("variable"):
            variable = PluginVariable(self)
            variable.from_xml(child, data)
            self.variables[variable.name] = variable
            if verbose:
                log = syslog
                log.info(str(variable))
        pass
            

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
    def type(self) -> PluginVariableType:
        return self._type
    @type.setter
    def type(self, value : PluginVariableType):
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
        ''' true if the variable is configured'''
        if self.type is None or self.name is None:
            return False
        if self.type == PluginVariableType.PhysicalInput:
            if self.value and "device_id" in self.value:
                return self.value["device_id"] is not None
            return False
        
        if self.type != PluginVariableType.String:
            return self.value is not None
        
        return True
        
        

    def from_xml(self, node, data = None):
        ''' save user plugin variable data '''
        self.name = safe_read(node, "name", str, "")
        self.type = PluginVariableType.to_enum(
            safe_read(node, "type", str, "String")
        )
        self.is_optional = read_bool(node, "is-optional")

        # Read variable content based on type information
        if self.type == PluginVariableType.Int:
            value = safe_read(node,"value", str, "none")
            if value == "none":
                self.value = 0
            else:
                self.value = int(value)
        elif self.type == PluginVariableType.Float:
            value = safe_read(node,"value", str, "none")
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
            if not "device-guid" in node.attrib:
                # partial data save
                self.value = {
                    "device_id": None,
                    "device_name": "",
                    "input_id": None,
                    "input_type": None}
            else:
                self.value = {
                    "device_id": parse_guid(node.attrib["device-guid"]),
                    "device_name": safe_read(node, "device-name", str, ""),
                    "input_id": safe_read(node, "input-id", int, 1),
                    "input_type": InputType.to_enum(safe_read(node, "input-type", str, ""))
                }

        elif self.type == PluginVariableType.VirtualInput:
            if not "vjoy-id" in node.attrib:
                # partial data save
                self.value = {
                "device_id": None,
                "input_id": None,
                "input_type": None
                  }
            else:
                self.value = {
                    "device_id": safe_read(node, "vjoy-id", int, 1),
                    "input_id": safe_read(node, "input-id", int, 1),
                    "input_type": InputType.to_enum(safe_read(node, "input-type", str, ""))}

    def to_xml(self):
        ''' read user plugin saved variable data '''

        node = etree.Element("variable")
        node.set("name", safe_format(self.name, str))
        node.set("type", PluginVariableType.to_string(self.type))
        node.set("is-optional", safe_format(self.is_optional, bool, str))

        # Write out content based on the type
        if self.type in [
            PluginVariableType.Int, PluginVariableType.Float,
            PluginVariableType.Mode, PluginVariableType.Selection,
            PluginVariableType.String,
        ]:
            node.set("value", "none" if self.value is None else str(self.value))
        elif self.type == PluginVariableType.Bool:
            value = False if self.value is None else self.value
            node.set("value", "1" if value else "0")
        elif self.type == PluginVariableType.PhysicalInput:
            if self.value is not None:
                node.set("device-guid", write_guid(self.value["device_id"]))
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





class ProfileOptionsData():
    ''' data block returned by the get_profile_data function'''
    def __init__(self):
        self.mode_list = []
        self.default_mode = None
        self.start_mode = None
        self.force_numlock_off = True
        self.restore_last = False


class ProfileMapItem():
    ''' holds a mapping of a profile xml to an exe '''

    def __init__(self, profile = None, process = None):
        self._profile = profile
        self._process = process
        self._modes = []
        self._default_mode = None # default mode for the profile (user defined) - if not set - this is the first root mode in the profile
        self._last_mode = None # last moded used by the profile (start mode)
        self._restore_mode_on_auto_activate = False
        self._index = -1
        self._warning = None
        self._valid = True # assume valid
        #self._force_numlock_off = True
        self._data = None
        self._update()

    @property
    def profile(self):
        return self._profile if self._profile else ""
    @profile.setter
    def profile(self, value):
        if value:
            # uniformly store paths
            value = value.replace("\\","/").lower().strip()
        self._profile = value

    @property
    def process(self):
        return self._process if self._process else ""

    @process.setter
    def process(self, value):
        if value:
            # uniformly store paths
            value = value.replace("\\","/").lower().strip()
        self._process = value

    @property
    def index(self):
        return self._index
    @index.setter
    def index(self, value):
        self._index = value

    @property
    def valid(self):
        return self._process and self.profile
    
    @property
    def restore_last_mode_on_auto_activate(self) -> bool:
        ''' true if the profile has the restore last used mode flag set '''
        return self._restore_mode_on_auto_activate
    
    @restore_last_mode_on_auto_activate.setter
    def restore_last_mode_on_auto_activate(self, value):
        self._restore_mode_on_auto_activate = value
        self.save()

    @property
    def default_mode(self) -> str:
        ''' profile default mode (this is the startup mode unless the option is to restore a previously used mode) '''
        return self._default_mode
    
    @default_mode.setter
    def default_mode(self, value):
        self._default_mode = value

    @property
    def last_mode(self) -> str:
        ''' last mode used by the profile '''
        return self._last_mode
    @last_mode.setter
    def last_mode(self, value):
        self._last_mode = value

    def _get_profile_data(self) -> ProfileOptionsData:
        ''' gets the list of profile modes in a given profile
        :returns tuple (mode_list, default_mode, last_mode, restore_mode_flag)
        '''

        mode_list = set() # avoids duplications as some nodes may have duplicate mode info when parsing
        default_mode = None
        restore_last = None
        start_mode = None


        current_profile : Profile = gremlin.shared_state.current_profile
        profile = self.profile
        force_numlock_off = True
        pd = ProfileOptionsData()

        if profile:
        
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
                            default_mode = safe_read(element, "default_mode", str, mode_list[0] if mode_list else '')
                        if not start_mode:
                            start_mode = safe_read(element, "start_mode", str, mode_list[0] if mode_list else '')
                        restore_last = safe_read(element, "restore_last", bool, False)
                        force_numlock_off = safe_read(element,"force_numlock", bool, True)

                    if not restore_last is None:
                        for element in tree.xpath("//startup-mode"):
                            start_mode = element.text
                            break
                    

                    if not restore_last is None:
                        restore_last = False # default value

                    
                    pd.mode_list = mode_list
                    pd.default_mode = default_mode
                    pd.start_mode = start_mode
                    pd.restore_last = restore_last
                    pd.force_numlock_off = force_numlock_off

                except Exception as ex:
                    syslog.error(f"PROC MAP: Unable to open profile mapping: {profile}:\n{ex}")

        return pd
    
    def save(self):
        ''' saves default and restore mode flags to the profile xml '''

        profile = self.profile
        if not self._last_mode:
            self._last_mode = self._default_mode
        
        current_profile : Profile = gremlin.shared_state.current_profile
        if compare_path(current_profile.profile_file, profile):
            current_profile.set_restore_mode(self._restore_mode_on_auto_activate)
            if self._default_mode:
                current_profile.set_start_mode(self._default_mode)
            #current_profile.set_force_numlock(self._force_numlock_off)
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
                    #element.set("force_numlock", str(self._force_numlock_off))
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

                    startup_node = etree.SubElement(settings_node,"startup-mode")
                    startup_node.text = str(self._default_mode)


                tree.write(profile, pretty_print=True,xml_declaration=True,encoding="utf-8")

            # save the profile map

            except Exception as ex:
                syslog.error(f"PROC MAP: Unable to open profile mapping: {profile}:\n{ex}")

    def _update(self):
        pd = self._get_profile_data()
        self._data = pd
        self._modes = pd.mode_list
        self._default_mode = pd.default_mode
        self._last_mode = pd.start_mode
        self._restore_mode_on_auto_activate = pd.restore_last
        #self._force_numlock_off = pd.force_numlock_off

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
class ProfileMap():
    ''' manages the profile to process maps '''

    def __init__(self):
        self._items = [] # list of items
        self._process_map = {} # mapps process to ProcessMapItem
        self._valid = True
        self.load_profile_map() # load the existing map

    def get_profile_map_file(self):
        ''' gets the profile file name '''
        return os.path.join(gremlin.shared_state.data_path, "profile_map.xml")
  
    def load_profile_map(self):
        ''' loads the mapping of profile xmls to processes '''
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
            except Exception as ex:
                syslog.error(f"PROC MAP: Unable to open profile mapping: {fname}:\n{ex}")
        self._update()

    def save_profile_map(self):
        ''' saves the profile configuration '''
        self.validate()
        fname = self.get_profile_map_file()
        if os.path.isfile(fname):
            # blitz
            os.unlink(fname)
        
        root = etree.Element("mappings")
        for item in self._items:
            if item.valid:
                # print (f"Saving item: process: {item.process} profile: {item.profile}")
                etree.SubElement(root,"map", 
                                 profile = item.profile, 
                                 process = item.process, 
                                 startup_mode = item.default_mode, 
                                 restore_mode=str(item.restore_last_mode_on_auto_activate)
                                 )

        try:
            # save the file
            tree = etree.ElementTree(root)
            tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")
            syslog.info(f"PROC MAP: saved preferences to {fname}")

        except Exception as err:
            syslog.error(F"PROC MAP: failed to save preferences to {fname}: {err}")


    @property
    def profile_map(self):
        return self._profile_map
    
    def register(self, item):
        ''' registers a new item '''
        self._items.append(item)
        if item.valid:
            self._process_map[item.process] = item
        self._update()
    
    def get_map(self, process) -> ProfileMapItem:
        ''' returns the gremlin profile '''
        process = process.replace("\\","/").lower().strip()
        if process in self._process_map.keys():
            return self._process_map[process]
        return None

    def _update(self):
        ''' updates the process map from the item registrations '''
        item_list = [item for item in self._items if item.process and item.profile]
        self._process_map = {}
        for item in item_list:
            self._process_map[item.process] = item

    def sort_profile(self):
        ''' sorts the items by profile '''
        self._items.sort(key = lambda x: (os.path.basename(x.profile), os.path.basename(x.process)))

    def sort_process(self):
        ''' sorts items by process'''
        self._items.sort(key = lambda x: (os.path.basename(x.process), os.path.basename(x.profile)))



    def get_process_list(self):
        ''' gets a list of mapped processes '''
        return list(self._process_map.keys())
    
    def items(self):
        ''' gets a list of registered process to profile map items'''
        return self._items
    
    def remove(self, item):
        ''' removes a mapping '''
        if item in self._items:
            self._items.remove(item)

    def validate(self):
        ''' validates the mappings '''
        
        # validate the processes are unique
        process_list = []
        self._valid = True # assume valid
        item : ProfileMapItem
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
                warning = f"Mapping incomplete"
                self._valid = False

            pd = item._get_profile_data()
            if pd.mode_list:
                if item.default_mode is not None and not item.default_mode in pd.mode_list:
                    valid = False
                    warning = f"Startup mode '{item.default_mode}' does not exist for this profile"
                    self._valid = False

            # print (f"Validation: Item process: {item.process} profile: {item.profile} valid: {valid}")
            item.valid = valid
            item.warning = warning

    @property
    def valid(self):
        return self._valid
    
# global registry instance
_profile_registry = ProfileRegistry()