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
import gremlin.profile
from gremlin.util import *
from gremlin.input_types import InputType
from gremlin.types import *
from xml.dom import minidom
from xml.etree import ElementTree
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


# Data struct representing profile information of a device
ProfileDeviceInformation = collections.namedtuple(
    "ProfileDeviceInformation",
    ["device_guid", "name", "containers", "conditions", "merge_axis"]
)

CallbackData = collections.namedtuple("ContainerCallback", ["callback", "event"])

class ProfileData(metaclass=ABCMeta):

    """Base class for all items holding profile data.

    This is primarily used for containers and actions to represent their
    configuration and to easily load and store them.
    """

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the parent item of this instance in the profile tree
        """
        self.parent = parent
        self.code = None
        self._id = None  # unique ID for this entry

        generic_icon = os.path.join(os.path.dirname(__file__),"generic.png")
        if os.path.isfile(generic_icon):
            self._generic_icon = generic_icon
        else:
            self._generic_icon = None            

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
        item = self.parent
        while not isinstance(item, InputItem):
            item = item.parent
        return item.input_type

    def get_mode(self):
        """Returns the Mode this data entry belongs to.

        :return Mode instance this object belongs to
        """
        item = self.parent
        while not isinstance(item, Mode):
            item = item.parent
        return item

    def get_device_type(self):
        """Returns the DeviceType of this data entry.
        
        :return DeviceType of this entry
        """
        item = self.parent
        while not isinstance(item, Device):
            item = item.parent
        return item.type

    def get_settings(self):
        """Returns the Settings data of the profile.

        :return Settings object of this profile
        """

        item = self.parent
        while not isinstance(item, Profile):
            item = item.parent
        return item.settings

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

    def __init__(self, parent):
        """Creates a new instance.

        :parent the InputItem which is the parent to this action
        """
        super().__init__(parent)
        self.action_sets = []
        self.custom_action_sets = False # true if the container uses custom action sets (need a converter to product action_sets)
        self._condition_enabled = True
        self._virtual_button_enabled = True # determines if the callbacks can be virtualized or not - if not - the callback is "raw" to the functor
        self.activation_condition_type = None
        self.activation_condition = None
        self.virtual_button = None
        # Storage for the currently active view in the UI
        # FIXME: This is ugly and shouldn't be done but for now the least
        #   terrible option
        self.current_view_type = None

        # attached hardware device to this container
        self.device = self._get_hardware_device(parent)
        if self.device:
            self.device_guid = self.device.device_guid
            self.device_input_id = parent.input_id
            self.device_input_type = parent.input_type
        else:
            self.device_guid = None
            self.device_input_id = None
            self.device_input_type = None




    def _get_hardware_device(self, parent):
        ''' gets the hardware device attached to this action '''
        while parent and not isinstance(parent, Device):
            parent = parent.parent
        if parent:
            return parent
        return None
    
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
    def hardware_device(self):
        ''' gets the hardware device attached to this '''
        return self.device


    @property
    def hardware_device_guid(self):
        ''' gets the GUID of the mapped hardware device'''
        return self.device_guid
    
    @property
    def hardware_input_id(self):
        ''' gets the input id on the hardware device attached to this '''
        return self.device_input_id
    
    @property
    def hardware_input_type(self):
        ''' gets the type of hardware device attached to this '''
        return self.device_input_type
    


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

    def generate_callbacks(self):
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
                VirtualButtonProcess(self.virtual_button),
                None
            ))
            callbacks.append(CallbackData(
                VirtualButtonCallback(self),
                Event(
                    InputType.VirtualButton,
                    callbacks[-1].callback.virtual_button.identifier,
                    device_guid=dinput.GUID_Virtual,
                    is_pressed=True,
                    raw_value=True
                )
            ))
        else:
            callbacks.append(CallbackData(ContainerCallback(self),None))

        return callbacks

    def from_xml(self, node):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """
        super().from_xml(node)
        self._parse_action_set_xml(node)
        self._parse_virtual_button_xml(node)
        self._parse_activation_condition_xml(node)

    def to_xml(self):
        """Returns a XML node representing the instance's contents.

        :return XML node representing the state of this instance
        """
        node = super().to_xml()
        # Add activation condition if needed
        if self.virtual_button:
            node.append(self.virtual_button.to_xml())
        if self.activation_condition:
            condition_node = self.activation_condition.to_xml()
            if condition_node:
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
        for child in node:
            # if child.tag == "remap":
            #     child.tag = "vjoyremap"

            if child.tag not in action_name_map:
                logging.getLogger("system").warning(
                    f"Unknown node present: {child.tag}"
                )
                continue

            

            entry = action_name_map[child.tag](self)
            entry.from_xml(child)
            action_set.append(entry)

    def _parse_virtual_button_xml(self, node):
        """Parses the virtual button part of the XML data.

        :param node the XML node to process
        """
        vb_node = node.find("virtual-button")

        self.virtual_button = None
        if vb_node is not None:
            self.virtual_button = AbstractContainer.virtual_button_lut[
                self.get_input_type()
            ]()
            self.virtual_button.from_xml(vb_node)

    def _parse_activation_condition_xml(self, node):
        for child in node.findall("activation-condition"):
            self.activation_condition_type = "container"
            self.activation_condition = \
                ActivationCondition([], ActivationRule.All)
            cond_node = node.find("activation-condition")
            if cond_node is not None:
                self.activation_condition.from_xml(cond_node)

    def _is_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if configured properly, False otherwise
        """
        # Check state of the container
        state = self._is_container_valid()

        # Check state of all linked actions
        for actions in [a for a in self.action_sets if a is not None]:
            for action in actions:
                state = state & action.is_valid()
        return state
    

    def is_valid_for_save(self):
        """ true if the container can be saved to a profile """
        state = self._is_container_valid()

        # Check state of all linked actions
        for actions in [a for a in self.action_sets if a is not None]:
            for action in actions:
                state = state & action.is_valid_for_save()
        return state        
        

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

    """Stores the information about a single device including its modes."""

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the parent profile of this device
        """
        self.parent = parent
        self.name = None
        self.label = ""
        self.device_guid = None
        self.modes = {}
        self.type = None
        self.virtual = False # true if the device was found in the detected hardware list

    def ensure_mode_exists(self, mode_name, device=None):
        """Ensures that a specified mode exists, creating it if needed.

        :param mode_name the name of the mode being checked
        :param device a device to initialize for this mode if specified
        """
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

        for child in node:
            mode = Mode(self)
            mode.from_xml(child)
            self.modes[mode.name] = mode

    def to_xml(self):
        """Returns a XML node representing this device's contents.

        :return xml node of this device's contents
        """
        node_tag = "device" if self.type != DeviceType.VJoy else "vjoy-device"
        node = ElementTree.Element(node_tag)
        node.set("name", safe_format(self.name, str))
        node.set("label", safe_format(self.label, str))
        node.set("device-guid", write_guid(self.device_guid))
        device_type = DeviceType.to_string(self.type)
 
        node.set("type",device_type)
        for mode in sorted(self.modes.values(), key=lambda x: x.name):
            node.append(mode.to_xml())
        return node


class InputItem:

    """Represents a single input item such as a button or axis."""

    def __init__(self, parent):
        """Creates a new InputItem instance.

        :param parent the parent mode of this input item
        """
        self.parent = parent
        self._input_type = None
        self._input_id = None
        self.always_execute = False
        self.description = ""
        #self._containers = base_classes.TraceableList(callback = self._container_change_cb) # container
        self._containers = []
        self._selected = False # true if the item is selected


    @property
    def selected(self):
        return self._selected
    @selected.setter
    def selected(self, value):
        self._selected = value

    @property
    def containers(self):
        return self._containers
    
    @property
    def input_type(self):
        return self._input_type
    @input_type.setter
    def input_type(self, value):
        self._input_type = value

    @property
    def input_id(self):
        return self._input_id
    @input_id.setter
    def input_id(self, value):
        self._input_id = value

    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, value):
        self._data = value
        

    def from_xml(self, node):
        """Parses an InputItem node.

        :param node XML node to parse
        """

        container_node = node # node that holds the container information
        container_plugins = ContainerPlugins()
        container_name_map = container_plugins.tag_map
        if node.tag == "key":
            pass
        self.input_type = InputType.to_enum(node.tag)
        if "id" in node.attrib.keys():
            self.input_id = safe_read(node, "id", int)
        self.description = safe_read(node, "description", str)
        self.always_execute = read_bool(node, "always-execute", False)

        if self.input_type in (InputType.KeyboardLatched, InputType.Keyboard):
            from gremlin.ui.keyboard_device import KeyboardInputItem
            from gremlin.keyboard import Key
            input_item = KeyboardInputItem()

            # see if old style keyboard entry
            if "extended" in node.attrib:
                scan_code = self.input_id
                is_extended = read_bool(node, "extended")
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
            #container_node = child

                

        elif self.input_type == InputType.OpenSoundControl:
            # OSC data 
            from gremlin.ui.osc_device import OscInputItem
            osc_input_item = OscInputItem()
            for child in node:
                if child.tag == "input":
                    osc_input_item.parse_xml(child)
            self.input_id = osc_input_item

        assert self.input_id is not None,"Error processing input - check types"
            

        
        for child in container_node:
            if child.tag in ("latched", "input", "keylatched"):
                # ignore extra data
                continue
            container_type = child.attrib["type"]
            if container_type not in container_name_map:
                logging.getLogger("system").warning(
                    f"Unknown container type used: {container_type}"
                )
                continue
            entry = container_name_map[container_type](self)
            entry.from_xml(child)
            self.containers.append(entry)
            if hasattr(entry, "action_model"):
                entry.action_model = self.containers
            container_plugins.set_container_data(self, entry)


    def to_xml(self):
        """Generates a XML node representing this object's data.

        :return XML node representing this object
        """
        from gremlin.keyboard import Key
        node = ElementTree.Element(InputType.to_string(self.input_type))
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
                    child = ElementTree.Element("latched")
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

        if self.always_execute:
            node.set("always-execute", "True")

        if self.description:
            node.set("description", safe_format(self.description, str))
        else:
            node.set("description", "")
        
        for entry in self.containers:
            # gremlinex change: containers can still be saved if they are invalid if they are still being configured:
            valid = entry.is_valid_for_save()
            if valid:
                container_node.append(entry.to_xml())
            else:
                logging.getLogger("system").warning(f"SaveProfile: input: {self.input_type} input id: {self.input_id} container returned invalid configuration - won't save {entry.name}")

        return node

    def get_device_type(self):
        """Returns the DeviceType of this input item.

        :return DeviceType of this entry
        """
        item = self.parent
        while not isinstance(item, Device):
            item = item.parent
        return item.type

    def get_input_type(self):
        """Returns the type of this input.

        :return Type of this input
        """
        return self.input_type

    @property
    def display_name(self):
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
        return f"Unknown input: {self._input_type}"

    def __eq__(self, other):
        """Checks whether or not two InputItem instances are identical.

        :return True if they are identical, False otherwise
        """
        return self.__hash__() == other.__hash__()

    def __hash__(self):
        """Returns the hash of this input item.

        The hash takes into account to which device and mode the input item is
        bound.

        :return hash of this InputItem instance
        """
        return hash((
            self.parent.parent.device_guid,
            self.parent.name,
            self.input_type,
            self.input_id)
        )
    





class AbstractAction(ProfileData):

    """Base class for all actions that can be encoded via the XML and
    UI system."""

    # allow all input types by default
    input_types = InputType.to_list()

    def __init__(self, parent):
        """Creates a new instance.

        :parent the container which is the parent to this action
        """
        assert isinstance(parent, AbstractContainer)
        super().__init__(parent)

        self.activation_condition = None
        self._id = None
        self._action_type = None 

    @property
    def hardware_device(self):
        ''' gets the hardware device attached to this action '''
        return self.parent.hardware_device
    
    @property
    def hardware_input_id(self):
        ''' gets the input id on the hardware device attached to this '''
        return self.parent.hardware_input_id
    
    @property
    def hardware_input_type(self):
        ''' gets the type of hardware device attached to this '''
        return self.parent.hardware_input_type
    
    @property
    def hardware_device_guid(self):
        return self.parent.hardware_device_guid


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
    

    def from_xml(self, node):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """

        # set the action ID first as it can be read by subsequent code
        if "action_id" in node.attrib:
            self.action_id = safe_read(node, "action_id", str)


        super().from_xml(node)



        for child in node.findall("activation-condition"):
            self.parent.activation_condition_type = "action"
            self.activation_condition = \
                ActivationCondition(
                    [],
                    ActivationRule.All
                )
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
        if self.activation_condition:
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
        node = ElementTree.Element("settings")

        # Startup mode
        if self.startup_mode is not None:
            mode_node = ElementTree.Element("startup-mode")
            mode_node.text = safe_format(self.startup_mode, str)
            node.append(mode_node)

        # Default delay
        delay_node = ElementTree.Element("default-delay")
        delay_node.text = safe_format(self.default_delay, float)
        node.append(delay_node)

        # Process vJoy as input settings
        for vid, value in self.vjoy_as_input.items():
            if value is True:
                vjoy_node = ElementTree.Element("vjoy-input")
                vjoy_node.set("id", safe_format(vid, int))
                node.append(vjoy_node)

        # Process vJoy axis initial values
        for vid, data in self.vjoy_initial_values.items():
            vjoy_node = ElementTree.Element("vjoy")
            vjoy_node.set("id", safe_format(vid, int))
            for aid, value in data.items():
                axis_node = ElementTree.Element("axis")
                axis_node.set("id", safe_format(aid, int))
                axis_node.set("value", safe_format(value, float))
                vjoy_node.append(axis_node)
            node.append(vjoy_node)

        return node

    def from_xml(self, node):
        """Populates the data storage with the XML node's contents.

        :param node the node containing the settings data
        """
        if not node:
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
            if isinstance(action, gremlin.action_plugins.remap.Remap):
                remap_actions.append(action)
    return remap_actions


class Profile():

    """Stores the contents of an entire configuration profile.

    This includes configurations for each device's modes.
    """


    def __init__(self, parent = None):
        """Constructor creating a new instance."""

        
        self.devices = {}
        self.vjoy_devices = {}
        self.merge_axes = []
        self.plugins = []
        self.settings = Settings(self)
        self.parent = parent
        self.start_mode = None # startup mode for this profile

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

    def build_inheritance_tree(self):
        """Returns a tree structure encoding the inheritance between the
        various modes.

        :return tree encoding mode inheritance
        """
        tree = {}
        for dev_id, device in self.devices.items():
            for mode_name, mode in device.modes.items():
                if mode.inherit is None and mode_name not in tree:
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

    def get_root_modes(self):
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
    
    def get_modes(self):
        ''' get all profile modes '''
        modes = []
        for device in self.devices.values():
            if device.type != DeviceType.Keyboard:
                continue
            for mode_name, mode in device.modes.items():
                modes.append(mode_name)
        return list(set(modes))  # unduplicated
        

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

        # List all input types
        all_input_types = [
            InputType.JoystickAxis,
            InputType.JoystickButton,
            InputType.JoystickHat,
            InputType.Keyboard
        ]

        # Create a list of all used remap actions
        remap_actions = []
        for dev in self.devices.values():
            for mode in dev.modes.values():
                for input_type in all_input_types:
                    for item in mode.config[input_type].values():
                        for container in item.containers:
                            remap_actions.extend(
                                extract_remap_actions(container.action_sets)
                            )

        # Remove all remap actions from the list of available inputs
        for act in remap_actions:
            # Skip remap actions that have invalid configuration
            if act.input_type is None:
                continue

            type_name = InputType.to_string(act.input_type)
            if act.vjoy_input_id in [0, None] \
                    or act.vjoy_device_id in [0, None] \
                    or act.vjoy_input_id not in vjoy[act.vjoy_device_id][type_name]:
                continue

            idx = vjoy[act.vjoy_device_id][type_name].index(act.vjoy_input_id)
            del vjoy[act.vjoy_device_id][type_name][idx]

        return vjoy

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

        tree = ElementTree.parse(fname)
        root = tree.getroot()

        self._start_mode = None
        if "start_mode" in root.attrib:
            self._start_mode = root.get("start_mode")

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

        return profile_was_updated
    
    def get_default_mode(self):
        ''' gets the default mode for this profile '''
        modes = self.get_root_modes()
        if modes:
            return modes[0]

    def to_xml(self, fname):
        """Generates XML code corresponding to this profile.

        :param fname name of the file to save the XML to
        """
        # Generate XML document
        root = ElementTree.Element("profile")
        root.set("version", str(gremlin.profile.ProfileConverter.current_version))
        root.set("start_mode", self._start_mode)

        # Device settings
        devices = ElementTree.Element("devices")
        device_list = sorted(
            self.devices.values(),
            key=lambda x: str(x.device_guid)
        )
        for device in device_list:
            devices.append(device.to_xml())
        root.append(devices)

        # VJoy settings
        vjoy_devices = ElementTree.Element("vjoy-devices")
        for device in self.vjoy_devices.values():
            vjoy_devices.append(device.to_xml())
        root.append(vjoy_devices)

        # Merge axis data
        for entry in self.merge_axes:
            node = ElementTree.Element("merge-axis")
            node.set("mode", safe_format(entry["mode"], str))
            node.set("operation", safe_format(
                MergeAxisOperation.to_string(entry["operation"]),
                str
            ))
            for tag in ["vjoy"]:
                sub_node = ElementTree.Element(tag)
                sub_node.set(
                    "vjoy-id",
                    safe_format(entry[tag]["vjoy_id"], int)
                )
                sub_node.set("axis-id", safe_format(entry[tag]["axis_id"], int))
                node.append(sub_node)
            for tag in ["lower", "upper"]:
                sub_node = ElementTree.Element(tag)
                sub_node.set("device-guid", write_guid(entry[tag]["device_guid"]))
                sub_node.set("axis-id", safe_format(entry[tag]["axis_id"], int))
                node.append(sub_node)
            root.append(node)

        # Settings data
        root.append(self.settings.to_xml())

        # User plugins
        plugins = ElementTree.Element("plugins")
        for plugin in self.plugins:
            plugins.append(plugin.to_xml())
        root.append(plugins)

        # Serialize XML document
        ugly_xml = ElementTree.tostring(root, encoding="utf-8")
        dom_xml = minidom.parseString(ugly_xml)
        with codecs.open(fname, "w", "utf-8-sig") as out:
            out.write(dom_xml.toprettyxml(indent="    "))

    def get_device_modes(self, device_guid, device_type, device_name=None):
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
            InputType.Keyboard
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
        mode = self._start_mode
        # verify the mode is in the mode list
        modes = self.get_modes()
        if not mode in modes:
            mode = modes[0]
            self._start_mode = mode
        return self._start_mode
    
    def set_start_mode(self, value):
        ''' sets the start up mode '''
        self._start_mode = value




class Mode:

    """Represents the configuration of the mode of a single device."""

    def __init__(self, parent):
        """Creates a new DeviceConfiguration instance.

        :param parent the parent device of this mode
        """
        self.parent = parent
        self.inherit = None
        self.name = None

        self.config = {
            InputType.JoystickAxis: {},
            InputType.JoystickButton: {},
            InputType.JoystickHat: {},
            InputType.Keyboard: {},
            InputType.KeyboardLatched: {},
            InputType.OpenSoundControl: {},
            InputType.Midi: {}
        }

    def from_xml(self, node):
        """Parses the XML mode data.

        :param node XML node to parse
        """
        from gremlin.base_profile import InputItem
        self.name = safe_read(node, "name", str)
        self.inherit = node.get("inherit", None)
        for child in node:
            item = InputItem(self)
            item.from_xml(child)

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
        node = ElementTree.Element("mode")
        node.set("name", safe_format(self.name, str))
        if self.inherit is not None:
            node.set("inherit", safe_format(self.inherit, str))
        input_types = [
            InputType.JoystickAxis,
            InputType.JoystickButton,
            InputType.JoystickHat,
            InputType.Keyboard,
            InputType.KeyboardLatched,
            InputType.OpenSoundControl,
            InputType.Midi
        ]
        for input_type in input_types:
            item_list = sorted(
                self.config[input_type].values(),
                key=lambda x: x.input_id
            )
            for item in item_list:
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
        assert(input_type in self.config)

        if input_id not in self.config[input_type]:
            entry = InputItem(self)
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
        node = ElementTree.Element("plugin")
        node.set("file-name", safe_format(self.file_name, str))
        for instance in self.instances:
            if instance.is_configured():
                node.append(instance.to_xml())
        return node


class PluginInstance:

    """Instantiation of a custom module with its own set of parameters."""

    def __init__(self, parent):
        self.parent = parent
        self.name = None
        self.variables = {}

    def is_configured(self):
        is_configured = True
        for var in [var for var in self.variables.values() if not var.is_optional]:
            is_configured &= var.value is not None
        return is_configured

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
        self.name = safe_read(node, "name", str, "")
        for child in node.iter("variable"):
            variable = PluginVariable(self)
            variable.from_xml(child)
            self.variables[variable.name] = variable

    def to_xml(self):
        node = ElementTree.Element("instance")
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
        self.type = None
        self.value = None
        self.is_optional = False

    def from_xml(self, node):
        self.name = safe_read(node, "name", str, "")
        self.type = PluginVariableType.to_enum(
            safe_read(node, "type", str, "String")
        )
        self.is_optional = read_bool(node, "is-optional")

        # Read variable content based on type information
        if self.type == PluginVariableType.Int:
            self.value = safe_read(node, "value", int, 0)
        elif self.type == PluginVariableType.Float:
            self.value = safe_read(node, "value", float, 0.0)
        elif self.type == PluginVariableType.Selection:
            self.value = safe_read(node, "value", str, "")
        elif self.type == PluginVariableType.String:
            self.value = safe_read(node, "value", str, "")
        elif self.type == PluginVariableType.Bool:
            self.value = read_bool(node, "value", False)
        elif self.type == PluginVariableType.Mode:
            self.value = safe_read(node, "value", str, "")
        elif self.type == PluginVariableType.PhysicalInput:
            self.value = {
                "device_id": parse_guid(node.attrib["device-guid"]),
                "device_name": safe_read(node, "device-name", str, ""),
                "input_id": safe_read(node, "input-id", int, None),
                "input_type": InputType.to_enum(
                    safe_read(node, "input-type", str, None)
                )
            }
        elif self.type == PluginVariableType.VirtualInput:
            self.value = {
                "device_id": safe_read(node, "vjoy-id", int, None),
                "input_id": safe_read(node, "input-id", int, None),
                "input_type": InputType.to_enum(
                    safe_read(node, "input-type", str, None)
                )
            }

    def to_xml(self):
        if self.value is None:
            return None

        node = ElementTree.Element("variable")
        node.set("name", safe_format(self.name, str))
        node.set("type", PluginVariableType.to_string(self.type))
        node.set("is-optional", safe_format(self.is_optional, bool, str))

        # Write out content based on the type
        if self.type in [
            PluginVariableType.Int, PluginVariableType.Float,
            PluginVariableType.Mode, PluginVariableType.Selection,
            PluginVariableType.String,
        ]:
            node.set("value", str(self.value))
        elif self.type == PluginVariableType.Bool:
            node.set("value", "1" if self.value else "0")
        elif self.type == PluginVariableType.PhysicalInput:
            node.set("device-guid", write_guid(self.value["device_id"]))
            node.set("device-name", safe_format(self.value["device_name"], str))
            node.set("input-id", safe_format(self.value["input_id"], int))
            node.set("input-type", InputType.to_string(self.value["input_type"]))
        elif self.type == PluginVariableType.VirtualInput:
            node.set("vjoy-id", safe_format(self.value["device_id"], int))
            node.set("input-id", safe_format(self.value["input_id"], int))
            node.set("input-type", InputType.to_string(self.value["input_type"]))

        return node







class ContainerCallback:

    """Callback object that can perform the actions associated with an input.

    The object uses the concept of a execution graph to handle conditional
    and chained actions.
    """

    def __init__(self, container):
        """Creates a new instance based according to the given input item.

        :param container the container instance for which to build th
            execution graph base callback
        """
        self.execution_graph = ContainerExecutionGraph(container)

    def __call__(self, event):
        """Executes the callback based on the event's content.

        Creates a Value object from the event and passes the two through the
        execution graph until every entry has run or it is aborted.
        """
        if event.is_axis or event.event_type in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]:
            value = gremlin.actions.Value(event.value)
        elif event.event_type in [
            InputType.JoystickButton,
            InputType.Keyboard,
            InputType.KeyboardLatched,
            InputType.Mouse,
            InputType.Midi,
            InputType.OpenSoundControl,
            InputType.VirtualButton,
            
        ]:
            value = gremlin.actions.Value(event.is_pressed)
        else:
            raise error.GremlinError("Invalid event type")

        # Containers representing a virtual button get their individual
        # value instance, all others share one to propagate changes across
        shared_value = copy.deepcopy(value)

        if event == InputType.VirtualButton:
            # TODO: remove this at a future stage
            logging.getLogger("system").error(
                "Virtual button code path being used"
            )
        else:
            self.execution_graph.process_event(event, shared_value)


class VirtualButtonCallback:

    """VirtualButton event based callback class."""

    def __init__(self, container):
        """Creates a new instance.

        :param container the container to execute when called
        """
        self._execution_graph = ContainerExecutionGraph(container)

    def __call__(self, event):
        """Executes the container's content when called.

        :param event the event triggering the callback
        """
        self._execution_graph.process_event(
            event,
            gremlin.actions.Value(event.is_pressed)
        )


class VirtualButtonProcess:

    """Callback that is responsible for emitting press and release events
    for a virtual button."""

    def __init__(self, data):
        """Creates a new instance for the given container.

        :param container the container using a virtual button configuration
        """
        self.virtual_button = None

        if isinstance(data, gremlin.base_buttons.VirtualAxisButton):
            self.virtual_button = gremlin.actions.AxisButton(
                data.lower_limit,
                data.upper_limit,
                data.direction
            )
        elif isinstance(data, gremlin.base_buttons.VirtualHatButton):
            self.virtual_button = gremlin.actions.HatButton(
                data.directions
            )
        else:
            raise error.GremlinError("Invalid virtual button data provided")

    def __call__(self, event):
        """Processes the provided event through the virtual button instance.

        :param event the input event being processed
        """
        self.virtual_button.process_event(event)


class AbstractExecutionGraph(metaclass=ABCMeta):

    """Abstract base class for all execution graph type classes.

    An execution graph consists of nodes which represent actions to execute and
    links which are transitions between nodes. Each node's execution returns
    a boolean value, indicating success or failure. The links allow skipping
    of nodes based on the outcome of a node's execution.

    When there is no link for a given node and outcome combination the
    graph terminates.
    """

    def __init__(self, instance):
        """Creates a new execution graph based on the provided data.

        :param instance the object to use in order to generate the graph
        """
        self.functors = []
        self.transitions = {}
        self.current_index = 0

        self._build_graph(instance)

    def process_event(self, event, value):
        """Executes the graph with the provided data.

        :param event the raw event that caused the execution of this graph
        :param value the possibly modified value extracted from the event
        """
        

        # Processing an event twice is needed when a virtual axis button has
        # "jumped" over it's activation region without triggering it. Once
        # this is detected the "press" event is sent and the second run ensures
        # a "release" event is sent.
        process_again = False

        while self.current_index is not None and len(self.functors) > 0:
            functor = self.functors[self.current_index]

            result = functor.process_event(event, value)

            if isinstance(functor, gremlin.actions.AxisButton):
                process_again = functor.forced_activation

            self.current_index = self.transitions.get(
                (self.current_index, result),
                None
            )
        self.current_index = 0

        if process_again:
            time.sleep(0.05)
            self.process_event(event, value)

    @abstractmethod
    def _build_graph(self, instance):
        """Builds the graph structure based on the given object's content.

        :param instance the object to use in order to generate the graph
        """
        pass

    def _create_activation_condition(self, activation_condition):
        """Creates activation condition objects base on the given data.

        :param activation_condition data about activation condition to be
            used in order to generate executable nodes
        """
        conditions = []
        for condition in activation_condition.conditions:
            if isinstance(condition, KeyboardCondition):
                conditions.append(
                    gremlin.actions.KeyboardCondition(
                        condition.scan_code,
                        condition.is_extended,
                        condition.comparison, 
                        condition.input_item
                    )
                )
            elif isinstance(condition, JoystickCondition):
                conditions.append(
                    gremlin.actions.JoystickCondition(condition)
                )
            elif isinstance(condition, VJoyCondition):
                conditions.append(
                    gremlin.actions.VJoyCondition(condition)
                )
            elif isinstance(condition, InputActionCondition):
                conditions.append(
                    gremlin.actions.InputActionCondition(condition.comparison)
                )
            else:
                raise error.GremlinError("Invalid condition provided")

        return gremlin.actions.ActivationCondition(
            conditions,
            activation_condition.rule
        )

    def _contains_input_action_condition(self, activation_condition):
        """Returns whether or not an input action condition is present.

        :param activation_condition condition data to check for the existence
            of an input action
        :return return True if an input action is present, False otherwise
        """
        if activation_condition:
            return any([
                isinstance(cond, gremlin.actions.InputActionCondition)
                for cond in activation_condition.conditions
            ])
        else:
            return False

    def _create_transitions(self, sequence):
        """Creates node transition based on the node type sequence information.

        :param sequence the sequence of nodes
        """
        seq_count = len(sequence)
        self.transitions = {}
        for i, seq in enumerate(sequence):
            if seq == "Condition":
                # On success, transition to the next node of any type in line
                self.transitions[(i, True)] = i+1
                offset = i + 1
                # On failure, transition to the condition node after the
                # next action node
                while offset < seq_count:
                    if sequence[offset] == "Action":
                        if offset+1 < seq_count:
                            self.transitions[(i, False)] = offset+1
                            break
                    offset += 1
            elif seq == "Action" and i+1 < seq_count:
                # Transition to the next node irrespective of failure or success
                self.transitions[(i, True)] = i+1
                self.transitions[(i, False)] = i + 1


class ContainerExecutionGraph(AbstractExecutionGraph):

    """Execution graph for the content of a single container."""

    def __init__(self, container):
        """Creates a new instance for a specific container.

        :param container the container data from which to generate the
            execution graph
        """
        assert isinstance(container, AbstractContainer)
        super().__init__(container)

    def _build_graph(self, container):
        """Builds the graph structure based on the container's content.

        :param container data to use in order to generate the graph
        """
        sequence = []

        # Add virtual button transform as the first functor if present
        # if container.virtual_button:
        #     self.functors.append(self._create_virtual_button(container))
        #     sequence.append("Condition")

        # If container based conditions exist add them before any actions
        if container.activation_condition_type == "container":
            self.functors.append(
                self._create_activation_condition(container.activation_condition)
            )
            sequence.append("Condition")

        functor = container.functor(container)
        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        container_plugins.register_functor(functor)
        self.functors.append(functor)
        
        sequence.append("Action")

        self._create_transitions(sequence)


class ActionSetExecutionGraph(AbstractExecutionGraph):

    """Execution graph for the content of a set of actions."""

    comparison_map = {
        (True, True): "always",
        (True, False): "pressed",
        (False, True): "released"
    }

    def __init__(self, action_set):
        """Creates a new instance for a specific set of actions.

        :param action_set the set of actions from which to generate the
            execution graph
        """
        super().__init__(action_set)

    def _build_graph(self, action_set):
        """Builds the graph structure based on the content of the action set.

        :param action_set data to use in order to generate the graph
        """
        # The action set shouldn't be empty, but in case this happens
        # nonetheless we abort
        if len(action_set) == 0:
            return

        sequence = []

        condition_type = action_set[0].parent.activation_condition_type
        add_default_activation = True
        if condition_type is None:
            add_default_activation = True
        elif condition_type == "container":
            add_default_activation = not self._contains_input_action_condition(
                action_set[0].parent.activation_condition
            )

        # Reorder action set entries such that if any remap action is
        # present it is executed last
        ordered_action_set = []
        for action in action_set:
            # if not isinstance(action, action_plugins.remap.Remap):
            if not "remap" in action.tag :
                ordered_action_set.append(action)
        for action in action_set:
            # if isinstance(action, action_plugins.remap.Remap):
            if "remap" in action.tag:
                ordered_action_set.append(action)

        # Create functors
        for action in ordered_action_set:
            # Create conditions for each action if needed
            if action.activation_condition is not None:
                # Only add a condition if we truly have conditions
                if len(action.activation_condition.conditions) > 0:
                    self.functors.append(
                        self._create_activation_condition(
                            action.activation_condition
                        )
                    )
                    sequence.append("Condition")

            # Create default activation condition if needed
            has_input_action = self._contains_input_action_condition(
                action.activation_condition
            )

            if add_default_activation and not has_input_action:
                condition = gremlin.actions.InputActionCondition()
                condition.comparison = ActionSetExecutionGraph.comparison_map[
                    action.default_button_activation
                ]
                activation_condition = gremlin.actions.ActivationCondition(
                    [condition],
                    gremlin.actions.ActivationRule.All
                )
                self.functors.append(
                    self._create_activation_condition(activation_condition)
                )
                sequence.append("Condition")

            # Create action functor
            self.functors.append(action.functor(action))
            sequence.append("Action")

        self._create_transitions(sequence)


