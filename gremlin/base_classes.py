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
import collections
import time
import threading
from abc import abstractmethod, ABCMeta
from PySide6 import QtCore
from typing import Callable, List, Any
from gremlin.input_types import InputType
from gremlin.types import DeviceType
from psygnal import Signal
import logging
import uuid
import dinput
from gremlin.util import TriggerDict
import _collections_abc
import gremlin.joystick_handling


syslog = logging.getLogger("system")


def _get_input_item(parent):
    """gets the InputItem parent hierarchy if it exists"""
    import gremlin.input_item
    import gremlin.profile_graph

    while parent is not None:
        if isinstance(parent, gremlin.input_item.InputItem):
            break
        if isinstance(parent, gremlin.profile_graph.ProfileInputItemNode):
            return parent.input_item
        if hasattr(parent, "parent"):
            parent = parent.parent
        else:
            parent = None

    if parent is not None:
        return parent
    return None


def _is_curve_tag(tag):
    """true if a curve tag"""
    if tag:
        return tag.casefold() in ("curve-data", "response-curve", "response-curve-ex")
    return False


class TraceableList(MutableSequence):
    """implements a custom list that can be traced when it changes"""

    def __init__(self, initlist=None, callback=None):
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

    def add_callback(self, callback: Callable):
        """adds a callback - signature (action: str, index: int, value [optional object])"""
        assert callable(callback), "Callback must be a callable method"
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable):
        """removes a callback"""
        assert callable(callback), "Callback must be a callable method"
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def clear_callbacks(self):
        """removes all callbacks"""
        self._callbacks.clear()

    def _trigger(self, action, index=None, value=None):
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
            self._trigger("append", value)

    def insert(self, idx, value):
        if self._callbacks:
            self._trigger("insert", value)
        self.data.insert(idx, value)

    def pop(self, idx=-1):
        if self._callbacks:
            self._trigger("pop", idx)
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
        self._trigger("extend", value=data)

    def to_list(self):
        return self.data


def empty_copy(obj):
    class Empty(obj.__class__):
        def __init__(self):
            pass

    newcopy = Empty()
    newcopy.__class__ = obj.__class__
    return newcopy


class DataList(list):
    """a list if a data member to track information about the list"""

    def __init__(self, data=None):
        super().__init__()
        self.data = data


class ABCMetaQObject(ABCMeta, type(QtCore.QObject)):
    pass


class AbstractInputItem(QtCore.QObject, metaclass=ABCMetaQObject):
    """base class for input items for MIDI, OSC, KEYBOARD and STATE items"""

    input_type_change = Signal(object)  # fires when an input item needs to refresh the output mapping due to input type changed

    def __init__(self, mode: str | object, device_guid):

        super().__init__()
        self._id = uuid.uuid4()  # GUID (unique) if loaded from XML - will reload that one
        self._guid = str(self.id).replace("-", "")
        self._device_guid = device_guid
        self._device_guid = DeviceType.NotSet
        if device_guid is not None:
            device = gremlin.joystick_handling.getDevice(device_guid)
            assert device is not None, "device does not exist"
            self._device_type = device.device_type
        self._input_id: int | any = None  # input Id on the hardware (can be a int or a class)
        self._input_id_readonly: bool = False  # true if the input id cannot be changed
        self._input_type: InputType = InputType.NotSet
        self._display_name: str = None
        self._description: str = None
        self._input_description: str = None
        self._axis_value: float = None
        self._button_value: bool = False  # true if the equivalent of "pressed"
        self._is_action: bool = False
        self._is_axis: bool = False
        self._is_button: bool = True
        self._input_type: InputType = None
        if isinstance(mode, str):
            self._profile_mode: str = mode  # profile mode
        else:
            # using Mode object
            self._profile_mode = mode.name
        self._sort_index: int = None  # sorting index (int)
        self._input_id_callback = None  # optional callback

    def setInputIdCallback(self, callback: Callable):
        """callback to use (optional) to get the input id"""
        if callback is not None:
            assert callable(callback), "Callback must be a callable method"
        self._input_id_callback = callback

    def setInputIdReadOnly(self, value: bool):
        self._input_id_readonly = value

    @property
    def descriptionReadOnly(self) -> bool:
        """true if description is readonly"""
        return self._description_readonly

    @descriptionReadOnly.setter
    def descriptionReadOnly(self, value: bool):
        self._description_readonly = value

    @property
    def guid(self):
        """id in string format"""
        return self._guid

    @property
    def id(self):
        return self._id

    # has no setter by design

    def setId(self, value):
        assert isinstance(value, uuid.UUID), "Invalid ID - must be a UUID"
        self._id = value
        self._guid = str(value).replace("-", "")

    @property
    def display_name(self):
        """display name for this input"""
        return self._display_name

    def setDisplayName(self, value: str):
        self._display_name = value

    @property
    def description(self) -> str:
        return self._description

    @description.setter
    def description(self, value) -> str:
        self._description = value

    def setDescription(self, value: str):
        if value != self._description:
            self._description = value

    @property
    def input_description(self) -> str:
        """gets the description for this input if any"""
        return self._input_description

    def setInputType(self, value: InputType):
        """force a different input type"""
        self._input_type = value

    def setDeviceType(self, value: DeviceType):
        self._device_type = value

    def setInputDescription(self, value: str):
        self._input_description = value

    @property
    def axis_value(self) -> float:
        """gets the current axis value"""
        return self.getAxisValue()

    def getAxisValue(self):
        if self._axis_value is None:
            return 0.0
        return self._axis_value

    def setAxisValue(self, value: float):
        """sets the axis value and triggers a joystick input event

        :param value: the floating point value to set (-1 to +1)
        :param emit: flag to trigger a joystick event if the value is set

        """
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
        """true if the item is action"""
        return self._is_action

    @is_action.setter
    def is_action(self, value: bool):
        self._is_action = value

    @property
    def is_axis(self) -> bool:
        """true if this item is setup as an axis input (linear)"""
        return self._is_axis or self._input_type == InputType.JoystickAxis

    @is_axis.setter
    def is_axis(self, value: bool):
        self._is_axis = value

    @property
    def is_button(self) -> bool:
        """true if this item is setup as an axis input (momentary)"""
        return not self.is_axis

    @property
    def message_key(self):
        assert False, "message_key property must be implemented by subclass"

    @property
    def input_id(self):
        if self._input_id_callback:
            return self._input_id_callback()
        return self._input_id

    @input_id.setter
    def input_id(self, value):
        if self._input_id_callback:
            raise ValueError("Input id is readonly (callback)")
        self.setInputId(value)

    def setInputId(self, value):
        if self._input_id_readonly:
            raise ValueError("Input id is readonly")
        if self._input_id_callback:
            raise ValueError("Input id is readonly (callback)")
        if __debug__ and self._device_guid:
            from gremlin.types import DeviceType

            device = gremlin.joystick_handling.getDevice(self._device_guid)
            if device.device_type == DeviceType.Joystick and self._input_type == InputType.JoystickAxis:
                assert value in device.axis_id_map, "invalid axis for device"

        if value != self._input_id:
            assert isinstance(value, int) or isinstance(value, AbstractInputItem), f"Invalid input id: {value}"
            assert isinstance(value, _collections_abc.Hashable), f"Invalid input id - must be hashable:  {value} "

            self._input_id = value

    @property
    def input_type(self) -> InputType:
        """input type"""
        return self._input_type

    # @input_type.setter
    # def input_type(self, value: InputType):
    #     self._input_type = value

    @property
    def device_guid(self):
        """device guid"""
        return self._device_guid

    @property
    def profile_mode(self) -> str:
        return self._profile_mode

    @profile_mode.setter
    def profile_mode(self, mode: str):
        self._profile_mode = mode

    @property
    def index(self) -> int:
        """input index within the mode and input type"""
        if self._sort_index is None:
            # index not set
            if isinstance(self._input_id, int):
                # use input ID if the index is numeric
                return self._input_id
            return -1  # not set
        return self._sort_index

    @index.setter
    def index(self, value: int):
        self._sort_index = value

    @abstractmethod
    def to_xml(self):
        """must implement"""
        pass

    @abstractmethod
    def parse_xml(self, data=None):
        """must implement"""
        pass

    def __getstate__(self):
        """manual pickle to XML"""
        return self.to_xml()

    def __setstate__(self, data):
        """manual unpickle"""
        self.parse_xml(data)

    def __hash__(self):
        # unique ID
        return hash((self._device_guid, self._input_type, self._input_id))
        # return hash(self._id)


class SpecialInputItem(AbstractInputItem):
    """specialized input item"""

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


class PickleTarget:
    """helper class to pickle objects that don't want to be pickled

    The way this works is we store the object to pickle in a local cache, give it a unique ID, and use that as the pickled value because the ID does pickle.
    When the object is unpickled, we retrieve the object from the cache, remove it from the cache and return the original.

    Pickling is automatic and occurs when cloning objects for example.

    """

    def __init__(self, item):
        self._item = item

    def __getstate__(self):
        """pickle"""
        from gremlin.util import get_guid

        id = get_guid()
        pickle_targets[id] = self.item
        self.id = id
        # print (f"pickled to id: {id}")
        return self.id

    def __setstate__(self, id):
        """unpickle"""
        # print (f"pickled from id: {id}")
        if id in pickle_targets:
            # print ("target found")
            self.item = pickle_targets[id]
            del pickle_targets[id]
        return self

    @property
    def item(self):
        return self._item

    @item.setter
    def item(self, value):
        self._item = value


class BaseCallbacks(QtCore.QObject):
    """base class implementing callback functionality"""

    def __init__(self):
        super().__init__()
        self._callbacks = []

    def registerCallback(self, callback):
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unregisterCallback(self, callback):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def clearCallbacks(self):
        self._callbacks.clear()

    def DoCallbacks(self):
        """runs the callbacks"""
        for callback in self._callbacks:
            callback(self)


class ABCMetaQObject(ABCMeta, type(QtCore.QObject)):
    pass


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
        self._input_item: gremlin.input_item.InputItem = gremlin.input_item._get_input_item(parent)

        # reported device type to actions so they can configure themselves to a different hardware input type if needed
        if isinstance(parent, BaseProfileData):
            self.override_input_type = parent.override_input_type
            self.override_input_id = parent.override_input_id
        else:
            self.override_input_type = None
            self.override_input_id = None

    def icon(self):
        """gets the default icon"""
        from gremlin.util import get_generic_icon

        return get_generic_icon()

    def from_xml(self, node, data=None, extra_data=None):
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
        """gets the input id"""
        if self.override_input_id is not None:
            return self.override_input_id
        if self._input_item is not None:
            return self._input_item.input_id
        return None

    def get_input_item(self):
        """gets the input item"""
        return self._input_item

    def update_inputs(self, item_data):
        """updates inputs from another profile entry"""
        self._input_item.setInputId(item_data.input_id)
        self._input_item.device_guid = item_data.device_guid
        self._input_item.device_name = item_data.device_name

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
        """returns the name of the currently attached device"""
        if self._input_item is not None:
            return self._input_item.device_name
        return None

    @property
    def input_display_name(self):
        """gets a config display string for the input"""
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
        """gets the hardware device attached to this action or container"""
        profile: gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        device_guid = self.hardware_device_guid
        if device_guid in profile.devices:
            return profile.devices[device_guid]
        return None

    @property
    def hardware_input_id(self):
        """gets the input id on the hardware device attached to this"""
        if self.override_input_id is not None:
            return self.override_input_id
        return self.input_item.input_id if self.input_item else None

    @property
    def hardware_raw_input_type(self) -> InputType:
        return self._input_item.input_type if self._input_item else None

    @property
    def hardware_input_type(self) -> InputType:
        """gets the type of hardware device attached to this"""
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
        """gets the type name of hardware device attached to this"""
        return InputType.to_display_name(self.hardware_input_type)

    @property
    def profile_mode(self) -> str:
        """gets the mode of this action"""
        return self.get_mode()

    @property
    def hardware_device_guid(self) -> dinput.GUID:
        """gets the currently attached hardware GUID"""
        return self.input_item.device_guid if self.input_item else None

    @property
    def hardware_device_id(self) -> str:
        """gets the currently attached hardware GUID"""
        return str(self.input_item.device_guid) if self.input_item else None

    @property
    def hardware_device_name(self) -> str:
        """gets the currently attached hardware name"""
        return self.get_device_name()

    @abstractmethod
    def _parse_xml(self, node, data=None, extra_data=None):
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

    # @abstractmethod
    def _sanitize(self):
        pass


class AbstractModel(QtCore.QAbstractItemModel):
    """Base class for MVC models."""

    data_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.id = uuid.uuid4()  # unique ID of this model

    def rows(self):
        """Returns the number of rows in the model.

        :return number of rows
        """
        pass

    def count(self):
        return self.rows()

    def __iter__(self):
        """generator"""
        assert False, "method must be implemented in the derived class"

    def data(self, index: int):
        """Returns the data entry stored at the provided index.

        :param index the index for which to return data
        :return data stored at the given index
        """
        assert False, "method must be implemented in the derived class"

    def add(self, data):
        """Adds a new entry to the model."""
        assert False, "method must be implemented in the derived class"

    def remove(self, data):
        """Removes the given entry from the model."""
        assert False, "method must be implemented in the derived class"

    def clear(self, data):
        """Removes all the given entry from the model."""
        assert False, "method must be implemented in the derived class"

    def refresh(self, force=False, emit=True):
        """
        Refreshes the model, triggering a data changed event if the model data was changed and not emitted yet
        """
        assert False, "method must be implemented in the derived class"

    def modelChanged(self) -> bool:
        """true if the model changed since the last change event was fired"""
        assert False, "method must be implemented in the derived class"


class AbstractCallbackModel(AbstractModel):
    """adds callbacks and propagation on change to a regular model

    supports filtered model data to show a subset of items in the model

    """

    def __init__(
        self,
        change_callback: Callable = None,
        filter_callback: Callable = None,
        sort_callback: Callable = None,
        added_callback: Callable = None,
        removed_callback: Callable = None,
        allowed_types: tuple = None,
        model_description: str = None,
        data=None,
    ):
        """callback enabled model
        :param callback: optional initial callback
        :param filter_callback: optional filtering callback for models that are filtered, takes in an object and returns True if the item should be included in the filter
        :param sort_callback: optional sorting callback for models that need sorted data - sends the list of items in the model and the return should be a list of indices for each item in the order of appearance
        :param added_callback: optional callback when an item is added to the model (unfiltered) - returns (item, unfiltered index, filtered index) - index is -1 if not found
        :param removed_callback: optional callback when an item is removed from the model (unfiltered)
        :param allowable types: optiona list of allowable types in the model

        """
        super().__init__()
        self._old_hash = None  # last change hash
        self._data_changed_callbacks = []

        self._index_map = TriggerDict()  # map of input_id to index
        self._index_map.addCallback(self._handle_data_changed)  # only track one of the two maps as a change in one also changes the other
        self._item_map = TriggerDict()  # map of input_id to index
        self._extra_data = data  # optional data to store with the model

        # assume no filters
        self._filtered_index_map = TriggerDict()
        self._filtered_item_map = TriggerDict()

        self._filtered_callback: Callable = None
        self._sort_callback: Callable = None
        self._filtered_enabled: bool = None
        self._sort_enabled: bool = None

        assert isinstance(change_callback, Callable) if change_callback is not None else True, "Invalid change callback"
        assert isinstance(allowed_types, tuple) if allowed_types is not None else True, "allowed types must be a tuple"

        assert isinstance(added_callback, Callable) if added_callback is not None else True, "Invalid add callback"
        assert isinstance(removed_callback, Callable) if removed_callback is not None else True, "Invalid remove callback"

        self._add_callback = added_callback
        self._remove_callback = removed_callback

        self.setSortCallback(sort_callback)
        self.setFilterCallback(filter_callback)

        self._show_filtered_only = False

        assert model_description, "model description not provided"
        self._model_description = model_description

        self._allowed_types = allowed_types
        self._suspend_stack = 0  # tracks suspension of change events
        self._change_pending = False  # true if a change is pending

        if change_callback:
            self.addCallback(change_callback)

    def setItemAt(self, index: int, item):
        """sets the item for the specific index"""
        # ensure the item is hashable
        assert isinstance(item, _collections_abc.Hashable), "item must be hashable"
        assert isinstance(index, int), "Index must be an integer"

        old_item = self._index_map[index] if index in self._index_map else None

        self._index_map[index] = item
        self._item_map[item] = index
        self._filtered_index_map[index] = item
        self._filtered_item_map[item] = index
        self.onItemChanged(self, index, item, old_item, "setItemAt")
        self.markDirty()

    def setSortCallback(self, callback):
        """changes or clears the sort callback"""
        assert isinstance(callback, Callable) if callback is not None else True, "Invalid sort callback"
        self._sort_callback = callback
        if self._sort_enabled is None:
            # not set
            self._sort_enabled = callback is not None

    def setSortEnabled(self, value: bool):
        self._sort_enabled = value

    def setFilterCallback(self, callback):
        """changes or clears the filter callback"""
        assert isinstance(callback, Callable) if callback is not None else True, "Invalid filter callback"
        self._filtered_callback = callback
        if self._filtered_enabled is None:
            self._filtered_enabled = callback is not None  # filter enabled by default if a filtering callback is provided

    def setFilterEnabled(self, value: bool):
        """enables or disables filtering"""
        self._filtered_enabled = value

    def __iter__(self):
        """iterator - gets an iterator to the contents"""
        return iter(self._filtered_index_map.values())

    def __len__(self):
        """number of items in the model"""
        return len(self._filtered_item_map)

    def __getitem__(self, index: int):
        """subscribtable"""
        if index in self._filtered_index_map:
            return self._filtered_index_map[index]
        raise IndexError("index out of range")

    def append(self, item) -> int:
        """
        Appends an item to the model
        :param item: the item to append to the model
        :returns int: inserted position
        """
        return self.add(item)

    def add(self, item: object, index=-1) -> int:
        """
        Adds (appends) a new entry to the model, returns the position inserted
        :param item: the item to append to the model
        :param callback: optional, filtering callback, takes an item as a parameter and returns true if the item should be included in the filtered data
        :returns int: inserted position
        """
        if self._allowed_types:
            if not isinstance(item, self._allowed_types):
                raise ValueError(f"invalid data type for model - got [{type(item).__name__}] - expected one of {self._allowed_types}")
        assert isinstance(item, _collections_abc.Hashable), "item must be hashable"

        if item not in self._index_map:
            self.markDirty()
            if index == -1:
                # find the next available index
                index = 0
                while index in self._index_map:
                    index += 1
            old_item = self.itemAt(index)
            self.setItemAt(index, item)
            self.onItemChanged(self, index, item, old_item, "add")
            self.applyFilter()
            self._fireChanged()

            return index
        return -1

    def onItemChanged(self, model, index: int, new_item, old_item, operation):
        """override by derived classes as needed"""
        pass

    def insert(self, i, item, emit=True):
        """inserts an item
        :param i: index to place the item at (other items are shifted)
        :param item: the item to append to the model
        :param callback: optional, filtering callback, takes an item as a parameter and returns true if the item should be included in the filtered data
        """
        if self._allowed_types:
            if not isinstance(item, self._allowed_types):
                raise ValueError(f"invalid data type for model - got [{type(item).__name__}] - expected one of {self._allowed_types}")
        old_item = self.itemAt(i)
        if i in self._index_map:
            # bump all the items down 1
            start_index = i
            stop_index = len(self._index_map)
            for index in range(stop_index, start_index, step=-1):
                data = self._index_map[index]
                self._index_map[index + 1] = data
                self._item_map[data] = index + 1

        # insert the item
        self._index_map[i] = item
        self._item_map[item] = i

        self.onItemChanged(self, index, item, old_item, "insert")

        self.applyFilter(emit=emit)
        if emit:
            self._fireChanged()

    def place(self, item, index: int, apply_filter=True, emit=True):
        """places an item at a given index - no checking"""
        old_item = self.itemAt(index)
        if item in self._item_map:
            i = self._index_map[index]
            if i == index:
                # already there
                return
            # remove the old entry from the model
            del self._index_map[i]

        self._index_map[index] = item
        self._item_map[item] = index
        if apply_filter:
            self.applyFilter(emit=emit)
        if emit:
            self._fireChanged()

        self.onItemChanged(self, index, item, old_item, "place")

    def remove(self, item, emit=True):
        """Removes the given entry from the model."""
        if item in self._item_map:
            syslog.info(f"removing item {item.id} from model {self.id} current count: {self.count()}")
            index = self._item_map[item]
            if hasattr(item, "_cleanup"):
                item._cleanup()
            del self._item_map[item]
            del self._index_map[index]
            self.applyFilter(emit=emit)
            assert item not in self._item_map, "item not removed from model"
            syslog.info(f"item {item.id} removed from model {self.id} new count: {self.count()}")
            if emit:
                self._fireChanged()
        self.onItemChanged(self, index, None, item, "remove")

    def removeAt(self, index: int, emit=True):
        """removes the entry at the given model index"""
        if index in self._index_map:
            item = self._index_map[index]
            if hasattr(item, "_cleanup"):
                item._cleanup()
            del self._item_map[item]
            del self._index_map[index]
            self.applyFilter(emit=emit)
            if emit:
                self._fireChanged()
            self.onItemChanged(self, index, None, item, "removeAt")

    def removeRow(self, index: int, emit=True):
        """removes the entry at the given model index"""
        self.removeAt(index, emit=emit)

    def clear(self, emit=True):
        """Removes all the given entry from the model."""
        if self._item_map:
            self.pushSuspend()
            self._item_map.clear()
            self._index_map.clear()
            self._filtered_index_map.clear()
            self._filtered_item_map.clear()
            self.popSuspend()
            if emit:
                self._fireChanged()
            self.onItemChanged(self, -1, None, None, "clear")

    def data(self, index: int):
        """returns the item stored at the given index, None if not found
        :param index: the index
        """
        if index in self._index_map:
            return self._index_map[index]
        return None


    @property
    def extraData(self):
        """returns the item stored at the given index, None if not found (same as data)"""
        return self._extra_data

    @extraData.setter
    def extraData(self, value):
        """sets the extra data for the model"""
        self._extra_data = value



    def itemAt(self, index: int):
        """gets the filtered item at the given index if it exists"""
        return self.data(index)

    def items(self):
        """returns all items in the filtered model"""
        return self._filtered_index_map.items()

    def filteredItemAt(self, index: int):
        """gets the filtered item at the given index if it exists"""
        return self.data(index)

    def unfilteredItemAt(self, index: int):
        """gets the item at the given index of the unfiltered model, returns None if not found"""
        if index in self._index_map:
            return self._index_map[index]
        return None

    def unfilteredItems(self):
        """returns all items in the unfiltered model"""
        return self._index_map.items()

    def indexOf(self, item) -> int:
        """returns the index of the item (filtered model), -1 if not found"""
        if item in self._filtered_item_map:
            return self._filtered_item_map[item]
        return -1

    def pop(self, index: int):
        """removes and returns the item at the given index, None if not found"""
        if index in self._index_map:
            item = self._index_map[index]
            self.removeAt(index)
            return item
        return None

    def push(self, item):
        """adds the item to the model and returns its index"""
        index = len(self._index_map)
        self._index_map[index] = item
        self._item_map[item] = index
        self._filtered_index_map[index] = item
        self._filtered_item_map[item] = index
        return index

    def unfilteredIndexOf(self, item) -> int:
        """returns the index of the item (unfiltered model), -1 if not found"""
        if item in self._item_map:
            return self._item_map[item]
        return -1

    def rows(self) -> int:
        """returns the size of the unfiltered model"""
        return len(self._index_map)

    def unfilteredCount(self) -> int:
        """returns the size of the unfiltered model"""
        return len(self._index_map)

    def count(self) -> int:
        """returns the size of the filtered model"""
        return len(self._filtered_index_map)

    def filteredCount(self) -> int:
        """returns the size of the filtered model"""
        return len(self._filtered_index_map)

    def clearFilter(self):
        """clears any filters"""
        if self._filtered_index_map.id != self._index_map.id:
            self._filtered_index_map.clearCallbacks()
            self._filtered_item_map.clearCallbacks()
            self._filtered_index_map = TriggerDict.copyFrom(self._index_map)
            self._filtered_item_map = TriggerDict.copyFrom(self._item_map)

    @property
    def allowedInputTypes(self) -> tuple:
        """gets the allowed input types in the model, if any"""
        return self._allowed_types

    def applyFilter(self, sort=True, emit=True):
        """Applies the filter to the source data
        :param callback: the evaluation callback that passes each item to determine inclusion, true to include, false to exclude
        :param sort: true to sort the data after filtering (only has effect if a sorting callback was provided)
        :param emit: true to emit a data changed signal after filtering
        """

        if not self._can_filter():
            # model is not filtered
            self._filtered_index_map = TriggerDict.copyFrom(self._index_map)
            self._filtered_item_map = TriggerDict.copyFrom(self._item_map)
            return

        if not self._filtered_enabled:
            if self._filtered_index_map.id != self._index_map.id:
                # reset filters if previously enabled
                self._filtered_index_map = {key: value for key, value in self._index_map.items()}
                self._filtered_item_map = {key: value for key, value in self._item_map.items()}
                if emit:
                    self._fireChanged()
            return

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            device = gremlin.joystick_handling.getDevice(self._device_guid)
            syslog.info(f"MODEL INPUT FILTER: for [{device.name}]")

        # filtering enabled
        force = False

        new_index_map = TriggerDict()
        new_item_map = TriggerDict()

        new_index = 0
        for item in self._index_map.values():
            include = self._filtered_callback(item)
            if include:
                if verbose:
                    syslog.info(f"\t{item.display_name} -> ON")
                new_index_map[new_index] = item
                new_item_map[item] = new_index
                new_index += 1
                force = True
        if verbose and new_index == 0:
            syslog.info("\tall inputs are filtered for this device")

        is_included = self._compare_maps(self._index_map, new_index_map)
        if is_included:
            self._filtered_index_map = new_index_map
            self._filtered_index_map.addCallback(self._handle_data_changed)
            self._filtered_item_map = new_item_map
            force = True
        else:
            self._filtered_index_map = TriggerDict.copyFrom(self._index_map)
            self._filtered_item_map = TriggerDict.copyFrom(self._item_map)
            force = True

        # resort the data
        self.applySort(False)

        if force and emit:
            self._fireChanged(force)

    def setItemFiltered(self, item: object, value: bool, emit=True) -> int:
        """sets an item filtered or not filtered (no effect if the model is not filtered)
        :param item: the object to change (must be in the model)
        :param value: filtered state
        :param emit: true if a change trigger should fire on change
        :returns int: the index, or -1 if not found
        """
        import gremlin.input_item

        assert isinstance(item, gremlin.input_item.InputItem)

        if self._can_filter() and item and item in self._item_map:
            # item is in the model
            if not self.isFiltered():
                # create a filtered set if model is not yet filtered
                self.applyFilter(emit=False)

            if value:
                if item in self._filtered_item_map:
                    return self._filtered_item_map[item]  # already filtered

                index = len(self._filtered_index_map)
                self.pushSuspend()

                self._filtered_index_map[index] = item
                self._filtered_item_map[item] = index
                self.popSuspend()
                if emit:
                    self._fireChanged()
                return index
            else:
                # remove from the filtered list
                if item in self._filtered_item_map:
                    self.pushSuspend()
                    index = self._filtered_item_map[item]
                    del self._filtered_index_map[index]
                    del self._filtered_item_map[item]
                    self.popSuspend()
                    if emit:
                        self._fireChanged()

        return -1

    def applySort(self, emit=True):
        """sorts the model based on the callback"""
        import gremlin.input_item

        if not self._can_sort():
            # nothing to do
            return
        items = self._filtered_item_map.keys()  # iterable
        indices = self._sort_callback(items)
        if indices is None:
            # callback returning nothing means no sort - skip
            return
        if __debug__:
            # check the data
            if not indices:
                return  # no data = nothing to do
            unique = set(indices)  # ensure unique
            # ensure unduplicated
            count = len(self._filtered_item_map)

            if len(unique) != count:
                # invalid list
                syslog.warning(f"ModelSort: sorted data has incorrect indices, expecting [{count}] got [{len(unique)}]")
                return
            # verify each index is valid
            invalid = [i for i in indices if i < 0 or i >= count]
            if invalid:
                # invalid list
                syslog.warning("ModelSort: sorted data has incorrect indices, indices are missing")
                return
        # valid
        for item, index in zip(items, indices):
            assert isinstance(item, gremlin.input_item.InputItem)
            assert isinstance(index, int)
            self._filtered_index_map[index] = item
            self._filtered_item_map[item] = index
        if emit:
            self._fireChanged()

    def setFilteredEnabled(self, value: bool, emit=True):
        """enables or disables the filter - has no effect is no filtering is setup"""
        if self._filtered_callback and self._filtered_enabled != value:
            self._filtered_enabled = value
            self.applyFilter(emit)

    def isFilteredEnabled(self) -> bool:
        """true if filtering is enabled"""
        return self._filtered_enabled

    def _can_filter(self) -> bool:
        """true if filtering can happen"""
        return self._filtered_enabled and self._filtered_callback is not None

    def _can_sort(self) -> bool:
        """true if sorting can happen"""
        return self._sort_enabled and self._sort_callback is not None

    def isFiltered(self) -> bool:
        """true if the model is currently filtered"""
        return self._filtered_enabled and self._filtered_callback is not None and self._compare_maps(self._index_map, self._filtered_index_map)

    def getFilterCallback(self) -> Callable:
        """gets the model's filtering callback"""
        return self._filtered_callback

    def _compare_maps(self, m1: TriggerDict, m2: TriggerDict):
        # look for differences in the stored values
        if m1.id == m2.id:
            # same map = no filter applied
            return True
        if len(m1) != len(m2):
            # fast comparison on counts
            return True
        # same count = compare actual contents
        return hash(m1) != hash(m2)

    def getFilteredIndices(self):
        """returns the list of indices currently visible in the model"""
        return [index for index in self._filtered_index_map]

    def getUnfilteredIndices(self):
        """returns the list of indices currently visible in the model"""
        return [index for index in self._index_map]

    def getFilteredItems(self):
        """returns the list of filtered items"""
        return self._filtered_index_map.values()

    def getUnfilteredItems(self):
        """returns the list of unfiltered items"""
        return self._index_map.values()

    def getFilteredMap(self):
        """gets index,input_item tuples for all filtered items in the model"""
        return self._filtered_index_map.items()

    def getUnfilteredMap(self):
        """gets index,input_item tuples for all unfiltered items in the model"""
        return self._index_map.items()

    def refresh(self, emit=True):
        """trigger a data change if the model has changed - use this to prevent updates if the data didn't change"""
        self._fireChanged(emit=emit)

    def trigger(self, force=True, emit=True):
        """trigers a model change manually - use this to force a reload even if the data didn't change"""
        self._fireChanged(force=force, emit=True)

    def pushSuspend(self):
        """suspends change notifications"""
        if self._suspend_stack == 0:
            self._item_map.pushSuspend()
            self._index_map.pushSuspend()
            self._filtered_index_map.pushSuspend()
            self._filtered_item_map.pushSuspend()
        self._suspend_stack += 1

    def popSuspend(self, reset=False, emit=True):
        """restores change notifications"""
        if reset and self._suspend_stack > 0:
            self._suspend_stack = 0
        if self._suspend_stack > 0:
            self._suspend_stack -= 1
        if self._suspend_stack == 0:
            self._item_map.popSuspend(reset)
            self._index_map.popSuspend(reset)
            self._filtered_index_map.popSuspend(reset)
            self._filtered_item_map.popSuspend(reset)
            self._fireChanged(force=self._change_pending, emit=emit)

    def resetChanges(self):
        """resets any changes to the model"""
        self._suspend_stack = 0
        self._change_pending = False

    def addCallback(self, callback: Callable):
        """adds a change callback to be called when the model data changes"""
        if __debug__ and callback is not None and not callable(callback):
            raise TypeError("Callback must be callable")
        if callback not in self._data_changed_callbacks:
            self._data_changed_callbacks.append(callback)

    def removeCallback(self, callback: Callable):
        """removes a callback from the list of callbacks to be called when the model data changes"""
        if callback in self._data_changed_callbacks:
            self._data_changed_callbacks.remove(callback)

    def modelChanged(self) -> bool:
        """true if data has changed"""
        return self._change_pending or hash(self) != self._old_hash

    def _handle_data_changed(self, source, index, old_value, new_value):
        """called when a storage data is changed"""
        if source.id == self._filtered_index_map.id:
            # notify on filtered items only
            if new_value is None and old_value is not None and self._remove_callback:
                # delete operation received
                self._remove_callback(old_value, index)

            if new_value is not None and self._add_callback:
                # add operation received
                self._add_callback(new_value, index)

        self._change_pending = True

    @property
    def modelDescription(self) -> str:
        return self._model_description

    def markDirty(self):
        # mark the model changed for the next update
        self._change_pending = True

    @property
    def debug_name(self) -> str:
        """gets a debug string for the model contents"""
        return f"[{self.modelDescription} items: [{len(self._index_map)}] included: [{len(self._filtered_index_map)}] callbacks: [{len(self._data_changed_callbacks)}]"

    def _fireChanged(self, force=False, emit=False):
        """fires a data changed signal if the data has changed or if force is true"""
        import gremlin.shared_state
        if self._suspend_stack and self._change_pending and not force:
            return
        if gremlin.shared_state.is_running:
            # auto-suspend at runtime
            return
        new_hash = hash(self)
        if self._suspend_stack and not force:
            # firing changes currently suspended
            self._change_pending = new_hash != self._old_hash
            return

        if new_hash != self._old_hash or force or self._change_pending:
            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_ui_level(2)
            if verbose:
                syslog.info(f"MODEL CHANGE TRIGGER: {self.debug_name} ")

            self._old_hash = new_hash

            for callback in self._data_changed_callbacks:
                callback(self._extra_data)

            if emit:
                self.data_changed.emit()  # indicate the model changed

        self._change_pending = False

    def __hash__(self):
        """unique hash value of model contents"""
        return hash((self.id, frozenset(self._index_map.values())))





class FastQueue:
    """ custom fast queue for high-performance hook handling """

    class Full(Exception):
        """Exception raised by put() when queue is full."""
        pass

    class Empty(Exception):
        """Exception raised by get() when queue is empty."""
        pass

    def __init__(self, maxsize: int = 0):
        self.maxsize = maxsize
        self._queue = collections.deque()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

    @staticmethod
    def fromList(items: list, maxsize: int = 0):
        """Creates a FastQueue from a list of items."""
        queue = FastQueue(maxsize)
        for item in items:
            queue.put(item)
        return queue

    def put(self, item, block: bool = True, timeout: float = None) -> bool:
        """Add an item to the queue.

        Returns True if successful, raises FastQueue.Full exception if space is unavailable.
        """
        with self._condition:
            if self.maxsize > 0:
                if not block:
                    if len(self._queue) >= self.maxsize:
                        raise FastQueue.Full("Queue is full")
                else:
                    # Wait until space opens up or timeout expires
                    end_time = time.time() + timeout if timeout is not None else 0
                    while len(self._queue) >= self.maxsize:
                        if timeout is not None:
                            remaining = end_time - time.time()
                            if remaining <= 0:
                                raise FastQueue.Full("Queue is full (timeout)")
                            self._condition.wait(remaining)
                        else:
                            self._condition.wait()

            self._queue.append(item)
            self._condition.notify()  # Awaken waiting consumers
            return True

    def append(self, item : Any):
        """Alias for put() to maintain compatibility with list-like behavior."""
        return self.put(item)

    def push(self, item : Any):
        """Alias for put() to maintain compatibility with stack-like behavior."""
        return self.put(item)

    def pop(self, block: bool = True, timeout: float = None):
        """Remove and return an item from the front of the queue.

        Raises FastQueue.Empty exception if data is unavailable.
        """
        return self.get(block, timeout)

    def popleft(self, block: bool = True, timeout: float = None):
        """Remove and return an item from the front of the queue.

        Raises FastQueue.Empty exception if data is unavailable.
        """
        return self.get(block, timeout)

    def popback(self, block: bool = True, timeout: float = None):
        """Remove and return an item from the back of the queue.

        Raises FastQueue.Empty exception if data is unavailable.
        """
        with self._condition:
            if not block:
                if not self._queue:
                    raise FastQueue.Empty("Queue is empty")
            else:
                # Wait until data arrives or timeout expires
                end_time = time.time() + timeout if timeout is not None else 0
                while not self._queue:
                    if timeout is not None:
                        remaining = end_time - time.time()
                        if remaining <= 0:
                            raise FastQueue.Empty("Queue is empty (timeout)")
                        self._condition.wait(remaining)
                    else:
                        self._condition.wait()

            item = self._queue.pop()
            self._condition.notify()  # Awaken waiting producers
            return item

    def get(self, block: bool = True, timeout: float = None):
        """Remove and return an item from the queue.

        Raises FastQueue.Empty exception if data is unavailable.
        """
        with self._condition:
            if not block:
                if not self._queue:
                    raise FastQueue.Empty("Queue is empty")
            else:
                # Wait until data arrives or timeout expires
                end_time = time.time() + timeout if timeout is not None else 0
                while not self._queue:
                    if timeout is not None:
                        remaining = end_time - time.time()
                        if remaining <= 0:
                            raise FastQueue.Empty("Queue is empty (timeout)")
                        self._condition.wait(remaining)
                    else:
                        self._condition.wait()

            item = self._queue.popleft()
            self._condition.notify()  # Awaken waiting producers
            return item

    def getbatch(self, max_batch_size: int, block: bool = True, timeout: float = None) -> List[Any]:
        """Extract up to max_batch_size items from the front of the queue in a single lock.

        If block is True, it will wait until AT LEAST one item is available before
        grabbing as many as possible up to max_batch_size.

        Raises Empty exception if block is False and queue is empty, or if timeout expires.
        """
        if max_batch_size <= 0:
            return []

        with self._condition:
            if not block:
                if not self._queue:
                    raise FastQueue.Empty("Queue is empty")
            else:
                # Wait until there is at least one item to harvest
                end_time = time.time() + timeout if timeout is not None else 0
                while not self._queue:
                    if timeout is not None:
                        remaining = end_time - time.time()
                        if remaining <= 0:
                            raise FastQueue.Empty("Queue is empty (timeout)")
                        self._condition.wait(remaining)
                    else:
                        self._condition.wait()

            # Determine the slice size safely within boundaries
            batch_size = min(len(self._queue), max_batch_size)
            batch = [self._queue.popleft() for _ in range(batch_size)]

            # Since multiple slots just freed up, awaken all potentially blocked producers
            if batch_size > 0:
                self._condition.notify_all()

            return batch

    def getall(self, block: bool = True, timeout: float = None) -> List[Any]:
        """Atomically drain, clear, and return all items currently in the queue.

        If block is True, it waits until AT LEAST one item is present before clearing.
        If block is False and the queue is empty, it raises an Empty exception.
        """
        with self._condition:
            if not block:
                if not self._queue:
                    raise FastQueue.Empty("Queue is empty")
            else:
                # Wait until there is something to consume
                end_time = time.time() + timeout if timeout is not None else 0
                while not self._queue:
                    if timeout is not None:
                        remaining = end_time - time.time()
                        if remaining <= 0:
                            raise FastQueue.Empty("Queue is empty (timeout)")
                        self._condition.wait(remaining)
                    else:
                        self._condition.wait()

            # Fast O(1) transfer of data structure reference
            items = list(self._queue)
            self._queue.clear()

            # Wake up all producers since the queue is entirely empty
            self._condition.notify_all()
            return items

    def qsize(self) -> int:
        """Return the approximate size of the queue."""
        with self._lock:
            return len(self._queue)

    def remove(self, item: Any, failOnMissing: bool = False) -> bool:
        """Remove the first occurrence of an item from the queue.

        Raises ValueError if the item is not present.
        Awakens waiting producers since space has freed up.

        :returns: True if the item was removed, False if not found, or exception
        """
        with self._condition:
            try:
                # deque.remove() is optimized in C, but shifts memory under the hood
                self._queue.remove(item)
                result = True
            except ValueError:
                if failOnMissing:
                    raise ValueError("item not in queue")
                result = False

            # Notify any blocked producers that a slot has opened up
            self._condition.notify()
        return result

    def removeCallback(self, callback: Callable[[Any], None]):
        """ remove items based on a callback - the callback gets the item and returns true if the item should be removed """
        result = False
        with self._condition:
            for item in self._queue:
                if callback(item):
                    # deque.remove() is optimized in C, but shifts memory under the hood
                    self._queue.remove(item)
                    result = True

                # Notify any blocked producers that a slot has opened up
            if result:
                self._condition.notify()
        return result


    def clear(self):
        """Clear all items from the queue."""
        with self._condition:
            self._queue.clear()
            self._condition.notify_all()  # Notify all waiting threads

    @property
    def __items__(self) -> List[Any]:
        """Return a point-in-time snapshot list of all items currently in the queue."""
        with self._lock:
            return list(self._queue)

    def __len__(self) -> int:
        """Return the current size of the queue using len()."""
        with self._lock:
            return len(self._queue)

    def __contains__(self, item: Any) -> bool:
        """Check if an item exists in the queue using the 'in' operator."""
        with self._lock:
            return item in self._queue

    def __iter__(self):
        """Return a snapshot iterator over the current items without holding the lock."""
        return iter(self.__items__)


    def empty(self) -> bool:
        """Return True if the queue is empty, False otherwise."""
        with self._lock:
            return not self._queue

    def full(self) -> bool:
        """Return True if the queue is full, False otherwise."""
        with self._lock:
            return self.maxsize > 0 and len(self._queue) >= self.maxsize

