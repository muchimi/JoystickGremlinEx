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

import os
from collections.abc import MutableSequence
from abc import abstractmethod, ABCMeta
from PySide6 import QtCore
from typing import Callable

from psygnal import Signal
import logging
import uuid

syslog = logging.getLogger("system")


class TraceableList(MutableSequence):
    ''' implements a custom list that can be traced when it changes  '''

    def __init__(self, initlist=None, callback = None):
        MutableSequence.__init__(self)

        self.data = []
        self._callbacks = []
        if callback:
            self._callbacks.append(callback)
        if initlist is not None:
            if isinstance(initlist, list):
                self.data[:] = initlist

            elif isinstance(initlist, TraceableList):
                self.data[:] = initlist.data[:]

            else:
                self.data = list(initlist)

    def add_callback(self, callback : Callable):
        ''' adds a callback - signature (action: str, index: int, value [optional object])'''
        assert callable(callback), "Callback must be a callable method"
        if not callback in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback : Callable):
        ''' removes a callback '''
        assert callable(callback), "Callback must be a callable method"
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def clear_callbacks(self):
        ''' removes all callbacks '''
        self._callbacks.clear()

    def _trigger(self, action, index = None, value = None):
        for callback in self._callbacks:
            callback(self, action, index, value)


    def __repr__(self):
        return """<{} data: {}>""".format(self.__class__.__name__, repr(self.data))

    def __lt__(self, other):
        return self.data < self.__cast(other)

    def __le__(self, other):
        return self.data <= self.__cast(other)

    def __eq__(self, other):
        return self.data == self.__cast(other)

    def __gt__(self, other):
        return self.data > self.__cast(other)

    def __ge__(self, other):
        return self.data >= self.__cast(other)

    def __cast(self, other):
        return other.data if isinstance(other, TraceableList) else other

    def __contains__(self, value):
        return value in self.data

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            return self.__class__(self.data[idx])
        return self.data[idx]

    def __iter__(self):
        return self.data.__iter__()

    def __next__(self):
        return self.data.__next__()

    def __setitem__(self, idx, value):
        # optional: self._acl_check(val)
        self.data[idx] = value
        self._trigger("setitem", idx, value)

    def __delitem__(self, idx):
        self._trigger("delitem", idx)
        del self.data[idx]

    def __add__(self, other):
        if isinstance(other, TraceableList):
            return self.__class__(self.data + other.data)

        elif isinstance(other, type(self.data)):
            return self.__class__(self.data + other)

        return self.__class__(self.data + list(other))

    def __radd__(self, other):
        if isinstance(other, TraceableList):
            return self.__class__(other.data + self.data)

        elif isinstance(other, type(self.data)):
            return self.__class__(other + self.data)

        return self.__class__(list(other) + self.data)

    def __iadd__(self, other):
        if isinstance(other, TraceableList):
            self.data += other.data

        elif isinstance(other, type(self.data)):
            self.data += other

        else:
            self.data += list(other)

        return self

    def __mul__(self, nn):
        return self.__class__(self.data * nn)

    __rmul__ = __mul__

    def __imul__(self, nn):
        self.data *= nn
        return self

    def __copy__(self):
        inst = self.__class__.__new__(self.__class__)
        inst.__dict__.update(self.__dict__)

        # Create a copy and avoid triggering descriptors
        inst.__dict__["data"] = self.__dict__["data"][:]

        return inst

    def append(self, value):
        self.data.append(value)
        if self._callbacks:
            self._trigger("append",value)


    def insert(self, idx, value):
        if self._callbacks:
            self._trigger("insert",value)
        self.data.insert(idx, value)

    def pop(self, idx=-1):
        if self._callbacks:
            self._trigger("pop",idx)
        return self.data.pop(idx)

    def remove(self, value):
        self.data.remove(value)

    def clear(self):
        if self._callbacks:
            self._trigger("clear")
        self.data.clear()

    def copy(self):
        if self._callbacks:
            self._trigger("copy")
        return self.__class__(self)

    def count(self, value):
        return self.data.count(value)

    def index(self, idx, *args):
        return self.data.index(idx, *args)

    def reverse(self):
        self.data.reverse()

    def sort(self, /, *args, **kwds):
        self.data.sort(*args, **kwds)

    def extend(self, other):
        data = other.data if isinstance(other, TraceableList) else other
        self.data.extend(data)
        self._trigger("extend", value = data)

    def to_list(self):
        return self.data

def empty_copy(obj):
    class Empty(obj.__class__):
        def __init__(self): pass
    newcopy = Empty(  )
    newcopy.__class__ = obj.__class__
    return newcopy

class DataList(list):
    ''' a list if a data member to track information about the list '''
    def __init__(self, data = None):
        super().__init__()
        self.data = data


class ABCMetaQObject(ABCMeta, type(QtCore.QObject)):
    pass



class AbstractInputItem(QtCore.QObject, metaclass=ABCMetaQObject):

    ''' base class for input items for MIDI, OSC, KEYBOARD and STATE items '''

    input_type_change = Signal(object) # fires when an input item needs to refresh the output mapping due to input type changed

    def __init__(self, mode : str | object, device_guid):

        super().__init__()
        self._id =  uuid.uuid4() # GUID (unique) if loaded from XML - will reload that one
        self._guid = str(self.id).replace("-","")
        self._device_guid = device_guid
        self._input_id : int | any = None # input Id on the hardware (can be a int or a class)
        self._input_type : InputType = InputType.NotSet
        self._display_name : str = None
        self._description : str = None
        self._input_description : str = None
        self._axis_value : float = None
        self._button_value : bool = False # true if the equivalent of "pressed"
        self._is_action : bool = False
        self._is_axis : bool = False
        self._is_button : bool = True
        self._input_type : InputType = None
        if isinstance(mode, str):
            self._profile_mode : str = mode # profile mode
        else:
            # using Mode object
            self._profile_mode = mode.name
        self._sort_index : int = None # sorting index (int)
        self._input_id_callback = None # optional callback


    def setInputIdCallback(self, callback : Callable):
        ''' callback to use (optional) to get the input id '''
        if callback is not None:
            assert callable(callback), "Callback must be a callable method"
        self._input_id_callback = callback


    @property
    def descriptionReadOnly(self) -> bool:
        ''' true if description is readonly'''
        return self._description_readonly

    @descriptionReadOnly.setter
    def descriptionReadOnly(self, value: bool):
        self._description_readonly = value

    @property
    def guid(self):
        ''' id in string format '''
        return self._guid

    @property
    def id(self):
        return self._id
    # has no setter by design

    def setId(self, value):
        assert isinstance(value, uuid.UUID),"Invalid ID - must be a UUID"
        self._id = value
        self._guid = str(value).replace("-","")

    @property
    def display_name(self):
        ''' display name for this input '''
        return self._display_name

    def setDisplayName(self, value : str):
        self._display_name = value

    @property
    def description(self) -> str:
        return self._description

    @description.setter
    def description(self, value) -> str:
        self._description = value

    def setDescription(self, value : str):
        if value != self._description:
            self._description = value

    @property
    def input_description(self) -> str:
        ''' gets the description for this input if any '''
        return self._input_description

    @property
    def input_type(self) -> InputType:
        ''' gets the type for this input '''
        return self._input_type

    def setInputType(self, value : InputType):
        ''' force a different input type '''
        self._input_type = value

    def setInputDescription(self, value : str):
        self._input_description = value


    @property
    def axis_value(self) -> float:
        ''' gets the current axis value '''
        return self.getAxisValue()

    def getAxisValue(self):
        if self._axis_value is None:
            return 0.0
        return self._axis_value

    def setAxisValue(self, value : float):
        ''' sets the axis value and triggers a joystick input event

        :param value: the floating point value to set (-1 to +1)
        :param emit: flag to trigger a joystick event if the value is set

        '''
        if self.axis_value is None or value != self._axis_value:
            self._axis_value = value


    def getOverrideInputType(self):
        # override input type
        return None

    @property
    def button_value(self) -> bool:
        return self._button_value

    def setButtonValue(self, value: bool):
        self._button_value = value

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
        return self._is_axis or self._input_type == InputType.JoystickAxis
    @is_axis.setter
    def is_axis(self, value : bool):
        self._is_axis = value

    @property
    def is_button(self) -> bool:
        ''' true if this item is setup as an axis input (momentary) '''
        return not self.is_axis


    @property
    def message_key(self):
        assert False,"message_key property must be implemented by subclass"

    @property
    def input_id(self):
        if self._input_id_callback:
            return self._input_id_callback()
        return self._input_id

    @input_id.setter
    def input_id(self, value):
        self.setInputId(value)

    def setInputId(self, value):
        if value != self._input_id:
            assert isinstance(value, int) or isinstance(value, AbstractInputItem),f"Invalid input id: {value}"
            self._input_id = value


    @property
    def input_type(self) -> InputType:
        ''' input type '''
        return self._input_type

    @input_type.setter
    def input_type(self, value : InputType):
        self._input_type = value

    @property
    def device_guid(self):
        ''' device guid '''
        return self._device_guid

    @property
    def profile_mode(self) -> str:
        return self._profile_mode
    @profile_mode.setter
    def profile_mode(self, mode : str):
        self._profile_mode = mode

    @property
    def index(self) -> int:
        ''' input index within the mode and input type '''
        if self._sort_index is None:
            # index not set
            if isinstance(self._input_id, int):
                # use input ID if the index is numeric
                return self._input_id
            return -1 # not set
        return self._sort_index

    @index.setter
    def index(self, value : int):
        self._sort_index = value


    @abstractmethod
    def to_xml(self):
        ''' must implement '''
        pass

    @abstractmethod
    def parse_xml(self, data = None):
        ''' must implement '''
        pass

    def __getstate__(self):
        ''' manual pickle to XML '''
        return self.to_xml()

    def __setstate__(self, data):
        ''' manual unpickle '''
        self.parse_xml(data)

    def __hash__(self):
        # unique ID
        return hash(self._id)


class SpecialInputItem(AbstractInputItem):
    ''' specialized input item '''
    def __init__(self, name):
        super().__init__()
        self._display_name = name
        self._description = "Special Virtual Input"

    @property
    def message_key(self):
        return self.display_name

    def __str__(self):
        return "special"


pickle_targets = {}

class PickleTarget():
    ''' helper class to pickle objects that don't want to be pickled

    The way this works is we store the object to pickle in a local cache, give it a unique ID, and use that as the pickled value because the ID does pickle.
    When the object is unpickled, we retrieve the object from the cache, remove it from the cache and return the original.

    Pickling is automatic and occurs when cloning objects for example.

    '''

    def __init__(self, item):
        self._item = item

    def __getstate__(self):
        ''' pickle '''
        from gremlin.util import get_guid
        id = get_guid()
        pickle_targets[id] = self.item
        self.id = id
        #print (f"pickled to id: {id}")
        return self.id

    def __setstate__(self, id):
        ''' unpickle '''
        #print (f"pickled from id: {id}")
        if id in pickle_targets:
            #print ("target found")
            self.item = pickle_targets[id]
            del pickle_targets[id]
        return self

    @property
    def item(self):
        return self._item

    @item.setter
    def item(self, value):
        self._item = value


from gremlin.input_types import InputType
import gremlin.joystick_handling
import gremlin.event_handler


class BaseCallbacks(QtCore.QObject):
    ''' base class implementing callback functionality'''

    def __init__(self):
        super().__init__()
        self._callbacks = []

    def registerCallback(self, callback):
        if not callback in self._callbacks:
            self._callbacks.append(callback)

    def unregisterCallback(self, callback):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def clearCallbacks(self):
        self._callbacks.clear()

    def DoCallbacks(self):
        ''' runs the callbacks '''
        for callback in self._callbacks:
            callback(self)

class ABCMetaQObject(ABCMeta, type(QtCore.QObject)):
    pass



def _get_input_item(parent):
    ''' gets the InputItem parent hierarchy if it exists '''
    import gremlin.input_item
    import gremlin.profile_graph
    while parent is not None:
        if isinstance(parent, gremlin.input_item.InputItem):
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


class BaseProfileData(QtCore.QObject, metaclass=ABCMetaQObject):

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
        self._input_item : gremlin.input_item.InputItem = _get_input_item(parent)


        generic_icon = os.path.join(os.path.dirname(__file__),"generic.png")
        if os.path.isfile(generic_icon):
            self._generic_icon = generic_icon
        else:
            self._generic_icon = None

        # reported device type to actions so they can configure themselves to a different hardware input type if needed
        if isinstance(parent, BaseProfileData):
            self.override_input_type = parent.override_input_type
            self.override_input_id = parent.override_input_id
        else:
            self.override_input_type = None
            self.override_input_id = None


    def icon(self):
        ''' gets the default icon'''
        from gremlin.util import get_generic_icon
        return get_generic_icon()


    def from_xml(self, node, data = None, extra_data = None):
        """Initializes this node's values based on the provided XML node.

        :param node the XML node to use to populate this instance
        """
        self._parse_xml(node, data, extra_data)

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
            return self._input_item.get_input_type()
        return None

    def get_input_id(self):
        ''' gets the input id'''
        if self.override_input_id is not None:
            return self.override_input_id
        if self._input_item is not None:
            return self._input_item.input_id
        return None

    def get_input_item(self):
        ''' gets the input item '''
        return self._input_item


    def update_inputs(self, item_data):
        ''' updates inputs from another profile entry '''
        self._input_item.setInputId(item_data.input_id)
        self._input_item.device_guid = item_data.device_guid
        self._input_item.device_name = item_data.device_name
        self._input_item.device_type = item_data.device_type


    def get_mode(self):
        """Returns the Mode this data entry belongs to.

        :return Mode instance this object belongs to
        """
        if self._input_item is not None:
            mode = self._input_item.profile_mode
            if mode == gremlin.shared_state.master_mode:
                return gremlin.shared_state.master_mode_name
            return mode
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
        if device_guid in profile.devices:
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
    def _parse_xml(self, node, data = None, extra_data = None):
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


