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


from abc import abstractmethod, ABCMeta
from collections import namedtuple
import codecs
import collections
import os
import copy
import logging
import time

import gremlin.actions
import gremlin.base_buttons
import gremlin.config
import gremlin.curve_handler
import gremlin.event_handler
import gremlin.execution_graph
import gremlin.keyboard
import gremlin.profile
import gremlin.shared_state
import gremlin.ui.keyboard_device
import gremlin.ui.midi_device
import gremlin.ui.osc_device
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
from anytree import Node

syslog = logging.getLogger("system")

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
        if hasattr(parent,"parent"):
            parent = parent.parent
        else:
            parent = None
           
    if parent is not None:
        return parent
    return None

class ProfileData(metaclass=ABCMeta):

    """Base class for all items holding profile data.

    This is primarily used for containers and actions to represent their
    configuration and to easily load and store them.
    """

    def __init__(self, parent):
        """Creates a new instance.

        :param: parent the parent item of this instance in the profile tree (type: InputItem)
        """
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


    def from_xml(self, node):
        """Initializes this node's values based on the provided XML node.

        :param node the XML node to use to populate this instance
        """
        self._parse_xml(node)

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
    def hardware_input_type(self) -> InputType :
        ''' gets the type of hardware device attached to this '''
        if self.override_input_type is not None:
            return self.override_input_type
        return self.input_item.input_type if self.input_item else None
    
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
    def _parse_xml(self, node):
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
        self.action_sets = []
        self.action_model = None # set at creation by the parent of this container
        self.custom_action_sets = False # true if the container uses custom action sets (need a converter to product action_sets)
        self._condition_enabled = True
        self._virtual_button_enabled = True # determines if the callbacks can be virtualized or not - if not - the callback is "raw" to the functor
        self.activation_container_condition = ActivationCondition([],ActivationRule.All) # activation condition that applies to the container
        self.activation_condition = ActivationCondition([],ActivationRule.All) # activation condition that applies to the actions
        self.virtual_button = None
        self.current_view_type = None
        self.parent_node = node

        # attached hardware device to this container

        input_item = _get_input_item(parent)
        assert input_item is not None
        if input_item is not None:
            self.device_guid = input_item.device_guid
            self.device_input_id = input_item.input_id
            self.device_input_type = input_item.input_type
            self.device = gremlin.joystick_handling.device_info_from_guid(self.device_guid)
        else:
            self.device_guid = None
            self.device_input_id = None
            self.device_input_type = None
            self.device = None

        
    @property
    def has_conditions(self):
        ''' true if the container has conditions defined '''
        return self.activation_container_condition is not None and len(self.activation_container_condition.conditions) > 0

    @property
    def has_action_conditions(self):
        ''' true if the container has action conditions defined '''
        
        if self.activation_condition is not None:
            if len(self.activation_condition.conditions) == 0:
                self.refresh_conditions()
            return len(self.activation_condition.conditions) > 0
        return False
    
    def refresh_conditions(self):
        ''' updates action conditions '''
        if self.activation_condition is not None:
            self.activation_condition.conditions = []    
            for action_set in self.action_sets:
                action : AbstractAction
                if action_set:
                    for action in action_set:
                        condition = action.activation_condition
                        if condition:
                            if not condition in self.activation_condition.conditions:
                                self.activation_condition.conditions.append(condition)



                            
    

    @property
    def condition_count(self)->int:
        ''' gets the count of container conditions currently defined '''
        if self.activation_container_condition is not None:
            return len(self.activation_container_condition.conditions)
        return 0
    
    @property
    def action_condition_count(self) -> int:
        ''' gets the count of action conditions currently defined '''
        count = 0
        if self.activation_condition is not None:
            # check each action set for conditions
            for action_set in self.action_sets:
                action : AbstractAction
                if action_set:
                    for action in action_set:
                        if action.activation_condition:
                            count += len(action.activation_condition.conditions)
        return count                            

    @property
    def id(self):
        return self._id
    @id.setter
    def id(self, value):
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
    def virtual_button_enabled(self):
        ''' determines if virtual button tab is enabled and virtual buttons is enabled for functor callbacks'''
        return self._virtual_button_enabled
    @virtual_button_enabled.setter
    def virtual_button_enabled(self, value):
        ''' determines if virtual button tab is enabled and virtual buttons is enabled for functor callbacks'''
        self._virtual_button_enabled = value


  
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
                    self.virtual_button = vb()
            elif not isinstance(self.virtual_button,AbstractContainer.virtual_button_lut[self.parent.input_type]):
                self.virtual_button = \
                    AbstractContainer.virtual_button_lut[self.parent.input_type]()
        else:
            self.virtual_button = None

    def generate_callbacks(self, parent = None):
        """Returns a list of callback data entries.

        :return list of container callback entries
        """
        callbacks = []

        # For a virtual button create a callback that sends VirtualButton
        # events and another callback that triggers of these events
        # like a button would.
        from gremlin.event_handler import Event

        if self._virtual_button_enabled and self.virtual_button is not None:
            callbacks.append(CallbackData(
                gremlin.execution_graph.VirtualButtonProcess(self.virtual_button),
                None
            ))
            callbacks.append(CallbackData(
                gremlin.execution_graph.VirtualButtonCallback(self, parent),
                Event(
                    InputType.VirtualButton,
                    callbacks[-1].callback.virtual_button.identifier,
                    device_guid=dinput.GUID_Virtual,
                    is_pressed=True,
                    raw_value=True
                )
            ))
        else:
           
            callbacks.append(CallbackData(gremlin.execution_graph.ContainerCallback(self, parent),None))


        return callbacks

    def from_xml(self, node):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """
        super().from_xml(node)
        if "container_id" in node.attrib:
            self.id = node.get("container_id")

        self._parse_action_set_xml(node)
        self._parse_virtual_button_xml(node)
        self._parse_activation_condition_xml(node)

    def to_xml(self):
        """Returns a XML node representing the instance's contents.

        :return XML node representing the state of this instance
        """
        node = super().to_xml()
        node.set("container_id", self.id)
        # Add activation condition if needed
        if self.virtual_button:
            node.append(self.virtual_button.to_xml())
        
        # if self.activation_condition:
        #     condition_node = self.activation_condition.to_xml()
        #     if condition_node is not None:
        #         node.append(condition_node)

        if self.activation_container_condition:
            condition_node = self.activation_container_condition.to_xml()
            if condition_node is not None:
                node.append(condition_node)

        return node

    def _parse_action_set_xml(self, node):
        """Parses the XML content related to actions.

        :param node the XML node to process
        """
        self.action_sets = []
        for child in node:
            if child.tag == "virtual-button":
                continue
            elif child.tag == "action-set":
                action_set = []
                self._parse_action_xml(child, action_set)
                self.action_sets.append(action_set)
            # update 5/30/24 - EMCS remove warning as custom action sets won't be read here
            # else:
            #     logging.getLogger("system").warning(
            #         f"Unknown node present: {child.tag}"
            #     )

    def _parse_action_xml(self, node, action_set):
        """Parses the XML content related to actions in an action-set.

        :param node the XML node to process
        :param action_set storage for the processed action nodes
        """
        action_name_map = ActionPlugins().tag_map
        config = gremlin.config.Configuration()
        for child in node:
            
            if child.tag not in action_name_map:
                logging.getLogger("system").warning(
                    f"Unknown node present: {child.tag}"
                )
                continue

            # apply any conversions
            tag = child.tag
            if config.convert_response_curve and tag == "response-curve":
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
            entry.from_xml(child)
            action_set.append(entry)

    def _parse_virtual_button_xml(self, node):
        """Parses the virtual button part of the XML data.

        :param node the XML node to process
        """
        vb_node = node.find("virtual-button")

        self.virtual_button = None
        if vb_node is not None:
            item = AbstractContainer.virtual_button_lut[self.get_input_type()]
            if item is not None:
                self.virtual_button = item()
                self.virtual_button.from_xml(vb_node)

    def _parse_activation_condition_xml(self, node):
        ''' load the container condition '''
        self.activation_container_condition = ActivationCondition([], ActivationRule.All)
        for _ in node.findall("activation-condition"):
            condition_node = node.find("activation-condition")
            if condition_node is not None:
                self.activation_container_condition.from_xml(condition_node)

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
                    logging.getLogger("system").warning(f"Action warning: {type(action).__name__} reports invalid - hardware {self.hardware_device_name} input: {self.hardware_input_type_name}  {self.hardware_input_id}")
                state = state & action_valid
        return state
    

    def is_valid_for_save(self):
        """ true if the container can be saved to a profile """
        state = self._is_container_valid()

        action_count = 0
        
        # Check state of all linked actions
        for actions in [a for a in self.action_sets if a is not None]:
            action_count += len(actions)
            for action in actions:
                state = state & action.is_valid_for_save()
        return state and action_count > 0
    
    def latch_extra_inputs(self):
        ''' returns any extra inputs as a list of (device_guid, input_id) to latch to this action (trigger on change) '''
        return []
        

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
        

    @property
    def device_guid(self) -> dinput.GUID:
        ''' device ID as a GUID '''
        return self._device_guid
    
    @device_guid.setter
    def device_guid(self, value : dinput.GUID):
        assert isinstance(value, dinput.GUID) if value is not None else True
        self._device_guid = value
        self.connected = gremlin.joystick_handling.is_device_connected(value) if value is not None else False

    @property
    def device_id(self) -> str:
        ''' device ID a a string '''
        return str(self.device_guid)

    @property
    def device_type(self) -> DeviceType:
        return self._device_type        

    def ensure_mode_exists(self, mode_name, device=None):
        """Ensures that a specified mode exists, creating it if needed.

        :param mode_name the name of the mode being checked
        :param device a device to initialize for this mode if specified
        """
        # if not gremlin.shared_state.global_mode in self.modes:
        #     mode = Mode(self)
        #     mode.name = "Global Mode (internal)"
        #     self.modes[gremlin.shared_state.global_mode] = mode

        if mode_name in self.modes:
            mode = self.modes[mode_name]
        else:
            mode = Mode(self)
            mode.name = mode_name
            self.modes[mode.name] = mode

        if device is not None:
            for i in range(device.axis_count):
                if i >= len(device.axis_map):
                    logging.getLogger("system").error(
                        f"{device.name} invalid axis request {device.axis_count} < {i}"
                    )
                else:
                    mode.get_data(
                        InputType.JoystickAxis,
                        device.axis_map[i].axis_index
                    )
            for idx in range(1, device.button_count + 1):
                mode.get_data(InputType.JoystickButton, idx)
            for idx in range(1, device.hat_count + 1):
                mode.get_data(InputType.JoystickHat, idx)

    def from_xml(self, node):
        """Populates this device based on the xml data.

        :param node the xml node to parse to populate this device
        """
        self.name = node.get("name")
        self.label = safe_read(node, "label", default_value=self.name)
        self.type = DeviceType.to_enum(safe_read(node, "type", str))
        self.device_guid = parse_guid(node.get("device-guid"))
        self.connected = gremlin.joystick_handling.is_device_connected(self.device_guid)

        for child in node:
            mode = Mode(self)
            mode.from_xml(child)
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

    # allow all input types by default
    input_types = InputType.to_list()

    def __init__(self, parent):
        """Creates a new instance.

        :parent the container which is the parent to this action
        """
        # assert isinstance(parent, AbstractContainer)
        super().__init__(parent)

        self.activation_condition = None
        self._id = None
        self._action_type = None
        self._enabled = False # true if the action is enabled
        self.singleton = False # true if the action can only appear once in the input's mapping
        self.parent_container = parent # holds the reference to the parent container holding this action
        self._is_axis = False
        self._is_hardware = None

        eh = gremlin.event_handler.EventListener()
        eh.action_created.emit(self)
        eh.profile_unload.connect(self._cleanup)
        eh.action_delete.connect(self._action_delete)

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
        eh = gremlin.event_handler.EventListener()
        eh.profile_unload.disconnect(self._cleanup)
        eh.action_delete.disconnect(self._action_delete)


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
            logging.getLogger("system").info(f"Functor: {self.name} {type(self).__name__} enabled")

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
        if not self._id:
            # generate a new ID
            self._id = get_guid()
        return self._id
    @action_id.setter
    def action_id(self, value):
        ''' id setter'''
        self._id = value

    @property
    def action_type(self):
        ''' type name of this action '''
        return self._action_type
    
    

    def display_name(self):
        ''' display name for this action '''
        return "N/A"
    

    def from_xml(self, node):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """

        # set the action ID first as it can be read by subsequent code
        if "action_id" in node.attrib:
            self.action_id = safe_read(node, "action_id", str)


        super().from_xml(node)


        self.activation_condition = ActivationCondition([],ActivationRule.All)
        for _ in node.findall("activation-condition"):
            cond_node = node.find("activation-condition")
            if cond_node is not None:
                self.activation_condition.from_xml(cond_node)

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
            
        if index in self._item_data_map.keys():
            return self._item_data_map[index]
        return None

    def from_xml(self, node):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """

        super().from_xml(node)

        container_nodes = gremlin.util.get_xml_child(node,"action_containers", multiple = True)
        for child in container_nodes:

            # get the input item behind the parent action
            current = self.parent
            while current and not isinstance(current, InputItem):
                current = current.parent

            # setup a new input item for these containers and read from config the defined containers
            
            item_data = InputItem(parent = self)
            item_data._input_type = current._input_type
            item_data._device_guid = current._device_guid
            item_data._input_id = current._input_id

            if child is not None:
                child.tag = child.get("type")
                index = safe_read(child,"index",int,0)
                item_data.from_xml(child)

            self._item_data_map[index] = item_data

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
        self.item_data = InputItem(parent = self)
        


    
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
            for aid, value in data.items():
                axis_node = etree.Element("axis")
                axis_node.set("id", safe_format(aid, int))
                axis_node.set("value", safe_format(value, float))
                vjoy_node.append(axis_node)
            node.append(vjoy_node)

        return node

    def from_xml(self, node):
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
            vid = safe_read(vjoy_node, "id", int)
            self.vjoy_as_input[vid] = True

        # vjoy initialization values
        self.vjoy_initial_values = {}
        for vjoy_node in node.findall("vjoy"):
            vid = safe_read(vjoy_node, "id", int)
            self.vjoy_initial_values[vid] = {}
            for axis_node in vjoy_node.findall("axis"):
                aid = safe_read(axis_node, "id", int)
                value = safe_read(axis_node, "value", float, 0.0)
                self.vjoy_initial_values[vid][aid] = value



    def get_initial_vjoy_axis_value(self, vid, aid):
        """Returns the initial value a vJoy axis should use.

        :param vid the id of the virtual joystick
        :param aid the id of the axis
        :return default value for the specified axis
        """
        value = 0.0
        if vid in self.vjoy_initial_values:
            if aid in self.vjoy_initial_values[vid]:
                value = self.vjoy_initial_values[vid][aid]
        return value

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



class InputItem():

    """Represents a single input item such as a button or axis, containers and parameters/options associated with that input mapping """

    def __init__(self, custom_name_handler = None, parent = None):
        """Creates a new InputItem instance.
        :param custom_name_handler: handler() returns a string, whenever the input name is needed
        :param parent: the parent mode of this input item
        """
        self._id = gremlin.util.get_guid() # unique ID of this object
        self.parent = parent
        self._input_type = None
        self._device_guid = None # hardware input ID
        self._name = None # device name
        self._input_id = None # input Id on the hardware
        self._input_name = None # input name of the hardware (axis name if an axis)
        self._input_name_handler = custom_name_handler # custom handler 
        self.always_execute = False
        self._description = ""
        self._description_readonly = False # true if description is read/only (cannot be changed)
        #self._containers = base_classes.TraceableList(callback = self._container_change_cb) # container
        self._containers = []
        self._selected = False # true if the item is selected
        self._is_action = False # true if the object is a sub-item for a sub-action (GateHandler for example)
        self._device_type = None
        self._device_name = None
        self._is_axis = False # true if the item is an axis input
        self._is_button = False # true if the item is a button input
        self._calibration = None # calibration data if the item is an input axis
        self._curve_data = None # true if the item has its input curved
        self._profile_mode = None
        self._enabled = True # enabled flag
        if parent is not None:
            # find the missing properties from the parenting hierarchy
            self._is_action = isinstance(parent, AbstractAction)
            item = parent
            while True:
                if isinstance(item, Mode):
                    self._profile_mode = item.name
                elif isinstance(item, Device):
                    self._device_type = item.type
                    self._device_name = item.name
                    self._device_guid = item.device_guid
                if not hasattr(item, "parent"):
                    break
                item = item.parent

        self._message_key = None # message key for this input (device_guid, input_type, input_id)

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._profile_start)


    @property
    def hasCalibration(self):
        ''' for axis input devices, returns True if the device has an active calibration '''
        return self._calibration is not None and self._calibration.hasData
    
    @property
    def calibration(self):
        ''' for axis input devices, returns the calibration data '''
        return self.calibration
    

    @QtCore.Slot()
    def _profile_start(self):
        # enable the input at profile start 
        self._enabled = True

                
    @property
    def id(self):
        ''' id of the InputItem '''
        return self._id

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

    def remove_container(self, container):
        self._containers.remove(container)

    def get_containers(self):
        return self._containers
    
    @property
    def containers(self):
        return self._containers

    @property
    def input_type(self):
        return self._input_type
    @input_type.setter
    def input_type(self, value):
        self._input_type = value
        self._update_input()


    @property
    def input_id(self):
        return self._input_id
    @input_id.setter
    def input_id(self, value):
        self._input_id = value
        self._update_input()

            

    @property
    def device_guid(self):
        return self._device_guid
    @device_guid.setter
    def device_guid(self, value):
        self._device_guid = value
        self._update_input()

    @property
    def profile_mode(self):
        return self._profile_mode
    @profile_mode.setter
    def profile_mode(self, value):
        self._profile_mode = value
    
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
        for container in self._containers:
            if container.condition_count or container.action_condition_count:
                return True
        return False

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
        if input_id is not None and self._device_guid is not None:
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
                    self._input_name = key_from_code(input_id.scan_code, input_id.is_extended).name
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
    

    def from_xml(self, node):
        """Parses an InputItem node.

        :param node XML node to parse
        """

        container_node = node # node that holds the container information
        container_plugins = ContainerPlugins()
        container_tag_map = container_plugins.tag_map
        self.input_type = InputType.to_enum(node.tag)
        if "id" in node.attrib.keys():
            s_id = node.get("id")
            if s_id.isnumeric():
                self.input_id = safe_read(node, "id", int)
            else:
                self.input_id = s_id
        self._description = safe_read(node, "description", str)
        self.always_execute = read_bool(node, "always-execute", False)

        if self.input_type in (InputType.KeyboardLatched, InputType.Keyboard):
            from gremlin.ui.keyboard_device import KeyboardInputItem
            from gremlin.keyboard import Key
            input_item = KeyboardInputItem()

            # see if old style keyboard entry
            if "extended" in node.attrib:
                scan_code = self.input_id
                is_extended = read_bool(node, "extended", False)
                is_mouse = safe_read(node,"mouse", bool, False)
                key = Key(scan_code=scan_code, is_extended=is_extended, is_mouse = is_mouse)
                input_item.key = key
                for child in node:
                    if child.tag == "latched":
                        latched_key = Key(scan_code=safe_read(child,"id",int), is_extended= read_bool(child,"extended"))
                        if not latched_key in key.latched_keys:
                            key.latched_keys.append(latched_key)
            else:
                # new style
                for child in node:
                    if child.tag == "input":
                        input_item.parse_xml(child)
                        break
            self.input_type = InputType.KeyboardLatched # force new input type
            #logging.getLogger("system").info(f"Loaded key input: {input_item.display_name}")
            self.input_id = input_item



        elif self.input_type == InputType.Midi:
            # midi data
            from gremlin.ui.midi_device import MidiInputItem
            midi_input_item = MidiInputItem()
            for child in node:
                if child.tag == "input":
                    midi_input_item.parse_xml(child)
            self.input_id = midi_input_item
                

        elif self.input_type == InputType.OpenSoundControl:
            # OSC data
            from gremlin.ui.osc_device import OscInputItem
            osc_input_item = OscInputItem()
            for child in node:
                if child.tag == "input":
                    osc_input_item.parse_xml(child)
            self.input_id = osc_input_item
            

        elif self.input_type == InputType.ModeControl:
            # mode control entries - input id is the only item we need
            self.is_axis = False
            


        elif self.input_type == InputType.JoystickAxis:
            # check for curve data
            for child in node:
                if child.tag == "response-curve-ex":
                    self.curve_data = gremlin.curve_handler.AxisCurveData()
                    self.curve_data._parse_xml(child)
                    self.curve_data.calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(self.device_guid, self.input_id)
                    break
            self.is_axis = True

        assert self.input_id is not None,"Error processing input - check types"
            

        
        for child in container_node:
            if child.tag in ("latched", "input", "keylatched","response-curve","response-curve-ex"):
                # ignore extra data
                continue
            if not "type" in child.attrib:
                logging.getLogger("system").error(
                    f"XML {child.tag} is missing container 'type' attribute"
                )
                continue 
            container_type = child.get("type")
            
            if container_type not in container_tag_map:
                logging.getLogger("system").warning(
                    f"Unknown container type used: {container_type}"
                )
                continue
            entry = container_tag_map[container_type](self)
            entry.from_xml(child)
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


    def to_xml(self):
        """Generates a XML node representing this object's data.

        :return XML node representing this object
        """
        from gremlin.keyboard import Key
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
            node.append(child)
        else:
            node.set("id", safe_format(self.input_id, int))

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
                    logging.getLogger("system").info(f"SaveProfile: input: {self.input_type} {InputType.to_display_name(self.input_type)} input id: {self.input_id} container has no data - won't save {entry.name}")

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
            return f"Key {self._input_id}"
        elif self._input_type == InputType.OpenSoundControl:
            return f"OSC {self._input_id}"
        elif self._input_type == InputType.Midi:
            return f"Midi {self._input_id}"
        elif self._input_type == InputType.ModeControl:
            return f"{gremlin.ui.mode_device.ModeInputModeType.to_display_name(self._input_id)}"
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
    




class Profile():

    """Stores the contents of an entire configuration profile.

    This includes configurations for each device's modes.
    """


    def __init__(self, parent = None):
        """Constructor creating a new instance."""

        
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

        el = gremlin.event_handler.EventListener()
        el.modes_changed.connect(self._modes_changed_cb)
        
        self.initialize_regular_devices() # non joystick devices

    def setSimconnectMode(self, key, mode):
        ''' sets the simconnect startup mode for a given aicraft key - the key comes from the SimconnectAicraftDefinition for the aircraft'''
        self._simconnect_modes[key] = mode

    def getSimconnectMode(self, key):
        ''' gets the simconnect startup mode for a given aicraft key - the key comes from the SimconnectAicraftDefinition for the aircraft'''
        if key in self._simconnect_modes:
            return self._simconnect_modes[key]
        return None


    @QtCore.Slot()        
    def _modes_changed_cb(self):
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
                if i >= len(device.axis_map):
                    logging.getLogger("system").error(
                        f"{device.name,} invalid axis request { device.axis_count} < {i}"
                    )
                else:
                    new_mode.get_data(
                        InputType.JoystickAxis,
                        device.axis_map[i].axis_index
                    )
            for i in range(1, device.button_count+1):
                new_mode.get_data(InputType.JoystickButton, i)
            for i in range(1, device.hat_count+1):
                new_mode.get_data(InputType.JoystickHat, i)


    def initialize_regular_devices(self):
        ''' setup suported non joystick devices '''
        
        # Keyboard
        device_guid = gremlin.ui.keyboard_device.get_keyboard_device_guid()
        device_type = DeviceType.Keyboard
        new_device = Device(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        new_device.type = device_type
        self.devices[device_guid] = new_device

        # MIDI
        device_guid = gremlin.ui.midi_device.get_midi_device_guid()
        device_type = DeviceType.Midi
        new_device = Device(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        new_device.type = device_type
        self.devices[device_guid] = new_device

        # OSC
        device_guid = gremlin.ui.osc_device.get_osc_device_guid()
        device_type = DeviceType.Osc
        new_device = Device(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        new_device.type = device_type
        self.devices[device_guid] = new_device

        # mode control
        device_guid = gremlin.ui.mode_device.get_mode_device_guid()
        device_type = DeviceType.ModeControl
        new_device = Device(self)
        new_device.name = DeviceType.to_display_name(device_type)
        new_device.device_guid = device_guid
        new_device.type = device_type
        self.devices[device_guid] = new_device

    
    def build_inheritance_tree(self):
        """Returns a tree structure encoding the inheritance between the
        various modes.

        :return tree (dictionary keyed by mode name) encoding mode inheritance
        """
        tree = {}
        for _, device in self.devices.items():
            for mode_name, mode in device.modes.items():
                if mode.inherit is None and mode_name and mode_name not in tree:
                    tree[mode_name] = {}
                elif mode.inherit:
                    stack = [mode_name, ]
                    parent = device.modes[mode.inherit]
                    stack.append(parent.name)
                    while parent.inherit is not None:
                        parent = device.modes[parent.inherit]
                        stack.append(parent.name)

                    stack = list(reversed(stack))
                    branch = tree
                    for entry in stack:
                        if entry not in branch:
                            branch[entry] = {}
                        branch = branch[entry]
        return tree
    
    def _inheritance_tree_to_list(self, data, tree, level = 0):
        for mode, children in sorted(tree.items()):
            data.append((level, mode))
            self._inheritance_tree_to_list(data, children, level+1)
    
    def traverse_mode(self):
        ''' returns the current mode list as a list of (level, mode) '''
        tree = self.build_inheritance_tree()
        data = []
        self._inheritance_tree_to_list(data, tree)
        return data
    
    def mode_map(self):
        mode_list = self.traverse_mode()
        mode_list.reverse()
        data = {}
        max_index = len(mode_list) - 1
        for index, (level, mode) in enumerate(mode_list):
            if index < max_index:
                parent_level, parent_mode = mode_list[index+1]
                data[mode] = parent_mode
            else:
                data[mode] = None
        return data
    
    def get_root_mode(self):
        ''' gets the top mode from a profile - that would be the default startup mode - sorted by name of the root nodes'''
        tree = self.build_inheritance_tree()
        modes = sorted(tree.keys())
        if "Default" in modes:
            # return the default mode as that is what we start with
            return "Default"
        # pick the first sorted mode
        if modes:
            return modes[0]
        return None
        
    
    def set_last_runtime_mode(self, mode):
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
        # Get profile root node
        parent = self
        while parent.parent is not None:
            parent = parent.parent
        assert(type(parent) == Profile)
        # Generate list of modes
        mode_names = []
        for device in parent.devices.values():
            mode_names.extend(device.modes.keys())
        mode_names = [mode for mode in mode_names if mode is not None]
        if mode_names:
            mode_names = list(set(mode_names))
            mode_names.sort(key=lambda x: x.casefold())
        return mode_names



    def add_mode(self, name, inherited_name = None, emit = True):
        import gremlin.event_handler
        ''' adds a new mode parented to inherited_name'''
        if name in self.mode_list():
            logging.getLogger("system").warning(f"Add Mode: error: mode {name} already exists")
            return False
        for device in self.devices.values():
            new_mode = Mode(device)
            new_mode.name = name
            if inherited_name is not None:
                new_mode.inherit = inherited_name
            else:
                new_mode.inherit = self.get_default_mode()
            new_mode.parent = device
            device.modes[name] = new_mode

        if emit:
            eh = gremlin.event_handler.EventListener()
            eh.modes_changed.emit()
        return True
    

    def set_mode_parent(self, name, inherited_name, emit = True):
        ''' sets the parent of a current mode'''
        mode_list = self.mode_list()
        if name in mode_list and inherited_name in mode_list:
            for device in self.devices.values():
                 if name in device.modes.keys():
                    device.modes[name].inherit = inherited_name
            if emit:
                eh = gremlin.event_handler.EventListener()
                eh.modes_changed.emit()
            return True
        return False
    
    def mode_tree(self):
        ''' gets the parent/child hiearchy of modes - returns a map '''
        return self.build_inheritance_tree()
        


    
    def remove_mode(self, name, force = False):
        ''' removes a mode from this profile '''
        from PySide6.QtWidgets import QMessageBox
        import gremlin.event_handler
        mode_list = self.mode_list()
        if not name in self.mode_list():
            logging.getLogger("system").warning(f"Remove Mode: error: mode {name} not found")
            return False
                
        if not force and len(mode_list.keys()) == 1:
            QMessageBox.warning(self, "Warning","Cannot delete last mode - one mode must exist")
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

        eh = gremlin.event_handler.EventListener()
        eh.modes_changed.emit()

    def get_root_modes(self) -> list[str]:
        """Returns a list of root modes.

        :return list of root modes
        """
        root_modes = []
        for device in self.devices.values():
            if device.type != DeviceType.Keyboard:
                continue
            for mode_name, mode in device.modes.items():
                if mode.inherit is None:
                    root_modes.append(mode_name)
        return list(set(root_modes))  # unduplicated
    
    def get_modes(self, casefold = False) -> list[str]:
        ''' get all profile mode names '''
        modes = []
        for device in self.devices.values():
            if device.type != DeviceType.Keyboard:
                continue
            for _, mode in device.modes.items():
                if casefold:
                    modes.append(mode.name.casefold())    
                else:
                    modes.append(mode.name)
        return list(set(modes))  # unduplicated
    

    def is_mode(self, mode) -> bool:
        ''' true if the mode exists in the current profile '''
        modes = self.get_modes(True)
        mode = mode.casefold()
        return mode in modes
    

    def find_mode(self, mode_text) -> str:
        ''' finds a mode by name or value '''
        if not mode_text:
            return None
        for device in self.devices.values():
            if device.type != DeviceType.Keyboard:
                continue
            
            for mode_name, mode in device.modes.items():
                if mode_text == mode.name:
                    return mode.name
                if mode_text.casefold() == mode.name.casefold():
                    return mode.name
                if mode_text == mode_name:
                    return mode.name
                if mode_text.strip().casefold() == mode_name.strip().casefold():
                    return mode.name
        return None # not found


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
                    entry.axis_map[i].axis_index
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
            self._profile_fname = gremlin.util.fix_path(value)
    
    def get_default_mode(self):
        ''' gets the default mode for this profile - this is the mode used if the default startup mode is not specified '''
        modes = self.get_root_modes()
        if modes:
            return modes[0]
        
    

    def from_xml(self, fname):
        """Parses the global XML document into the profile data structure.

        :param fname the path to the XML file to parse
        """
        # Check for outdated profile structure and warn user / convert
        profile_converter = gremlin.profile.ProfileConverter()
        profile_was_updated = False
        if not profile_converter.is_current(fname):
            logging.getLogger("system").warning("Outdated profile, converting")
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




        # Parse each device into separate DeviceConfiguration objects
        for child in root.iter("device"):
            device = Device(self)
            device.from_xml(child)
            self.devices[device.device_guid] = device


        # Parse each vjoy device into separate DeviceConfiguration objects
        for child in root.iter("vjoy-device"):
            device = Device(self)
            device.from_xml(child)
            self.vjoy_devices[device.device_guid] = device

        # parse simconnect startup entries
        self._simconnect_modes = {}
        for child in root.iter("simconnect"):
            key_cp = safe_read(child,"key_cp",str)
            key_ap = safe_read(child,"key_ap",str)
            mode = safe_read(child,"mode")
            key = (key_cp, key_ap)
            self._simconnect_modes[key] = mode




        # Ensure that the profile contains an entry for every existing
        # device even if it was not part of the loaded XML and
        # replicate the modes present in the profile. This adds both entries
        # for physical and virtual joysticks.
        devices = gremlin.joystick_handling.joystick_devices()
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

                # Create required modes
                for mode in gremlin.profile.mode_list(new_device):
                    if mode not in new_device.modes:
                        new_device.modes[mode] = Mode(new_device)
                        new_device.modes[mode].name = mode

                # # global mode
                # mode = Mode(new_device)
                # mode.name ="Global mode (internal)"
                # new_device.modes[gremlin.shared_state.global_mode] = mode

        # Parse merge axis entries
        for child in root.iter("merge-axis"):
            self.merge_axes.append(self._parse_merge_axis(child))

        # Parse settings entries
        self.settings.from_xml(root.find("settings"))

        # Parse plugin entries
        for child in root.findall("plugins/plugin"):
            plugin = Plugin(self)
            plugin.from_xml(child)
            self.plugins.append(plugin)

        if not self._start_mode:
            # use a default mode
            self._start_mode = self.get_default_mode()

        self._profile_fname = gremlin.util.fix_path(fname)

        name, _ = os.path.splitext(os.path.basename(fname))
        self._profile_name = name

        # have config use updated profile settings
        config = gremlin.config.Configuration()
        config.ensure_profile(self)


        return profile_was_updated
    


    def to_xml(self, fname):
        """Generates XML code corresponding to this profile.

        :param fname name of the file to save the XML to
        """
        # Generate XML document
        root = etree.Element("profile")
        root.set("version", str(gremlin.profile.ProfileConverter.current_version))
        root.set("start_mode", self.get_start_mode())
        root.set("default_mode", self.get_default_start_mode())
        root.set("restore_last", str(self._restore_last_mode))
        root.set("force_numlock", str(self._force_numlock_off))


        # Device settings
        devices = etree.Element("devices")
        device_list = sorted(
            self.devices.values(),
            key=lambda x: str(x.device_guid)
        )
        for device in device_list:
            devices.append(device.to_xml())
        root.append(devices)

        # simconnect settings
        for key, mode in self._simconnect_modes.items():
            if key:
                child = etree.Element("simconnect")
                key_cp, key_ap = key
                
                child.set("key_cp",key_cp)
                child.set("key_ap",key_ap)
                child.set("mode", mode)
                root.append(child)

        # VJoy settings
        add_vjoy = False
        vjoy_devices = etree.Element("vjoy-devices")
        for device in self.vjoy_devices.values():
            if device.modes:
                vjoy_devices.append(device.to_xml())
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
                sub_node = etree.Element(tag)
                sub_node.set(
                    "vjoy-id",
                    safe_format(entry[tag]["vjoy_id"], int)
                )
                sub_node.set("axis-id", safe_format(entry[tag]["axis_id"], int))
                node.append(sub_node)
            for tag in ["lower", "upper"]:
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

        # Serialize XML document
        tree = etree.ElementTree(root)
        tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")

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
            InputType.OpenSoundControl
        ]

        # Process all devices
        for dev in self.devices.values():
            for mode in dev.modes.values():
                for input_type in all_input_types:
                    for item in mode.config[input_type].values():
                        is_empty &= len(item.containers) == 0

        # Process all vJoy devices
        for dev in self.vjoy_devices.values():
            for mode in dev.modes.values():
                for input_type in all_input_types:
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
        for tag in ["vjoy"]:
            entry[tag] = {
                "vjoy_id": safe_read(node.find(tag), "vjoy-id", int),
                "axis_id": safe_read(node.find(tag), "axis-id", int),
            }
        for tag in ["lower", "upper"]:
            entry[tag] = {
                "device_guid": parse_guid(node.find(tag).get("device-guid")),
                "axis_id": safe_read(node.find(tag), "axis-id", int)
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
        return mode
    
    def set_start_mode(self, value : str):
        ''' sets the profile auto-activated start up mode '''
        assert isinstance(value, str)
        self._start_mode = value
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            logging.getLogger("system").info(f"Profile {self.name}: set start mode to {value}")
        self.save()

    def set_default_start_mode(self, value : str):
        ''' sets the profile normal start up mode - this will only be used if the startup mode is not overwritten by the last mode - saving a default start mode also resets the last used start mode'''
        assert isinstance(value, str)
        self._default_start_mode = value
        self._start_mode = value
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            logging.getLogger("system").info(f"Profile {self.name}: set default start mode to {value}")
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
            logging.getLogger("system").info(f"Profile {self.name}: set auto-restore flag {value}")
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
            profile_path = gremlin.util.userprofile_path()
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

    """Represents the configuration of the mode of a single device."""

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

    def __init__(self, parent):
        """Creates a new DeviceConfiguration instance.

        :param parent the parent device of this mode
        """
        self.parent = parent
        self.inherit = None # name of the mode we inherit properties from
        self._name = None # name of the current mode
       
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

    def from_xml(self, node):
        """Parses the XML mode data.

        :param node XML node to parse
        """
        from gremlin.base_profile import InputItem
        name = safe_read(node, "name", str)
        name = name.strip()
        self._name = name

        self.inherit = node.get("inherit", None)
        for child in node:
            item = InputItem(parent = self)
            item.from_xml(child)
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
                

    def to_xml(self):
        """Generates XML code for this DeviceConfiguration.

        :return XML node representing this object's data
        """
        node = etree.Element("mode")
        node.set("name", safe_format(self.name, str))
        if self.inherit is not None:
            node.set("inherit", safe_format(self.inherit, str))
        input_types = Mode.SaveInputTypes
        for input_type in input_types:
            item_list = sorted(
                self.config[input_type].values(),
                key=lambda x: x.input_id
            )
            for item in item_list:
                if item.is_valid_for_save():
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
            entry = InputItem(parent = self)
            entry.input_type = input_type
            entry.input_id = input_id
            self.config[input_type][input_id] = entry
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

    def from_xml(self, node):
        self.file_name = safe_read(node, "file-name", str, None)
        for child in node.iter("instance"):
            instance = PluginInstance(self)
            instance.from_xml(child)
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

    def from_xml(self, node):
        verbose = gremlin.config.Configuration().verbose
        self.name = safe_read(node, "name", str, "")
        for child in node.iter("variable"):
            variable = PluginVariable(self)
            variable.from_xml(child)
            self.variables[variable.name] = variable
            if verbose:
                log = logging.getLogger("system")
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
            return self.value["device_id"] is not None
        
        if self.type != PluginVariableType.String:
            return self.value is not None
        
        return True
        
        

    def from_xml(self, node):
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
                    "input_id": safe_read(node, "input-id", int, None),
                    "input_type": InputType.to_enum(safe_read(node, "input-type", str, None))
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
                    "device_id": safe_read(node, "vjoy-id", int, None),
                    "input_id": safe_read(node, "input-id", int, None),
                    "input_type": InputType.to_enum(safe_read(node, "input-type", str, None))}

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
                    logging.getLogger("system").error(f"PROC MAP: Unable to open profile mapping: {profile}:\n{ex}")

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
                logging.getLogger("system").error(f"PROC MAP: Unable to open profile mapping: {profile}:\n{ex}")

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
        return os.path.join(userprofile_path(),"profile_map.xml")
  
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
                        logging.getLogger("system").info(f"PROC MAP: Registered mapping: {process} -> {profile}")
            except Exception as ex:
                logging.getLogger("system").error(f"PROC MAP: Unable to open profile mapping: {fname}:\n{ex}")
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
            logging.getLogger("system").info(f"PROC MAP: saved preferences to {fname}")

        except Exception as err:
            logging.getLogger("system").error(F"PROC MAP: failed to save preferences to {fname}: {err}")


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