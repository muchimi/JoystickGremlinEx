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
import inspect

from PySide6 import QtCore
from typing import Callable, List, Any, Generic, TypeVar, Iterator

from attr import filters
from gremlin.input_types import InputType
from gremlin.types import DeviceType
from psygnal import Signal
import logging
import uuid
import dinput
from gremlin.util import TriggerDict
import _collections_abc
import gremlin.joystick_handling
import traceback


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

    def __init__(self, mode: str | object, device_guid: dinput.GUID | str, input_type: InputType):

        super().__init__()

        self._id = uuid.uuid4()  # GUID (unique) if loaded from XML - will reload that one
        self._guid = str(self.id).replace("-", "")

        device = gremlin.joystick_handling.getDevice(device_guid)
        if not device:
            raise ValueError(f"Device with GUID [{device_guid}] could not be found")

        self._device_guid = device.device_guid
        self._device_id = device.device_id
        self._device_name = device.name
        self._device_type  = device.device_type

        assert isinstance(input_type, InputType), "input_type must be an InputType enum value"

        self._input_id: int | any = None  # input Id on the hardware (can be a int or a class)
        self._input_id_readonly: bool = False  # true if the input id cannot be changed
        self._input_type: InputType = input_type  # input type (InputType)
        self._display_name: str = None
        self._description: str = None
        self._input_description: str = None
        self._axis_value: float = None
        self._button_value: bool = False  # true if the equivalent of "pressed"
        self._is_action: bool = False
        self._is_axis: bool = False
        self._is_button: bool = True

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
        # override mode/state inputs for legacy profiles
        if isinstance(value, InputType):
            input_type = value
        elif isinstance(value, DeviceType):
            match value:
                case DeviceType.ModeControl:
                    input_type = InputType.ModeControl
                case DeviceType.State:
                    input_type = InputType.State
                case DeviceType.Osc:
                    input_type = InputType.OpenSoundControl
                case DeviceType.Midi:
                    input_type = InputType.Midi
                case DeviceType.State:
                    input_type = InputType.State
                case DeviceType.Keyboard:
                    input_type = InputType.KeyboardLatched
                case DeviceType.Overlay:
                    input_type = InputType.OverlayButton
                case _:
                    raise ValueError(f"Unsupported source type: {value}")
        else:
            raise ValueError(f"Unsupported source type: {value}")

        assert isinstance(input_type, InputType), "Invalid input type"
        self._input_type = input_type

    @property
    def input_type(self) -> InputType:
        """gets the input type"""
        return self._input_type

    @input_type.setter
    def input_type(self, value: InputType):
        self.setInputType(value)

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
        if value is None:
            self._input_id = None
            return

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

    def __init__(self, name: str, mode, device_guid):
        super().__init__(mode, device_guid)
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

    def __init__(self, parent, extra_data: dict = None):
        """Creates a new instance.

        :param: parent the parent item of this instance in the profile tree (type: InputItem)
        """

        super().__init__()
        assert parent is not None
        self.code = None
        self._id = gremlin.util.get_guid(no_brackets=True)
        self._input_item: gremlin.input_item.InputItem = None
        self._hardware_input_id_callback: Callable = None
        if extra_data:
            if "input_item" in extra_data:
                self._input_item = extra_data["input_item"]
        else:
            self._input_item = gremlin.input_item._get_input_item(parent)
        assert self._input_item is not None, "input item not set for profile data"

        # reported device type to actions so they can configure themselves to a different hardware input type if needed
        if isinstance(parent, BaseProfileData):
            self.override_input_type = parent.override_input_type
            self.override_input_id = parent.override_input_id
        else:
            self.override_input_type = None
            self.override_input_id = None

    def notifyContentChanged(self, extra_data: dict = None, force: bool = False):
        if self._input_item:
            self._input_item.notifyContentChanged(extra_data=extra_data, force=force)

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
        # non special devices only
        if gremlin.joystick_handling.isSpecialDevice(item_data.device_guid):
            return
        try:
            self._input_item.setInputId(item_data.input_id)
            self._input_item.setInputType(item_data.get_input_type())
            self._input_item.device_guid = item_data.device_guid
            self._input_item.device_name = item_data.device_name
        except AttributeError:
            syslog.warning("Failed to update input item from item_data due to AttributeError")
            syslog.debug(f"Item data: {item_data}")
            syslog.warning(traceback.format_exc())


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

    def setHardwareInputIdCallback(self, callback: Callable):
        """Sets a callback to be invoked when a hardware input id is needed"""
        self._hardware_input_id_callback = callback

    def getHardwareInputIdCallback(self):
        """Gets the currently set hardware input id callback"""
        return self._hardware_input_id_callback

    @property
    def hardware_input_id(self):
        """gets the input id on the hardware device attached to this"""
        if self._hardware_input_id_callback is not None:
            return self._hardware_input_id_callback()
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
            input_item = self._input_item
            if hasattr(input_item, "getOverrideInputType"):
                self.override_input_type = input_item.getOverrideInputType()
                return self.override_input_type

            input_type = None
            input_id = self._input_item.input_id
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
        return True  # assume valid

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

    sorted = Signal()  # fires when the model is sorted

    DEFAULT_FILTER = "default"  # default filter name

    def __init__(
        self,
        change_callback: Callable = None,
        filter_callback: Callable = None,
        sort_callback: Callable = None,
        added_callback: Callable = None,
        removed_callback: Callable = None,
        content_callback: Callable = None,
        allowed_types: tuple = None,
        model_description: str = None,
        filtered_data_change_callback: Callable = None,
        item_changed_callback: Callable = None,
        data=None,
    ):
        """callback enabled model
        :param callback: optional initial callback
        :param filter_callback: optional filtering callback for models that are filtered, takes in an object and returns True if the item should be included in the filter
        :param sort_callback: optional sorting callback for models that need sorted data - sends the list of items in the model and the return should be a list of indices for each item in the order of appearance
        :param added_callback: optional callback when an item is added to the model (unfiltered) - returns (item, unfiltered index, filtered index) - index is -1 if not found
        :param removed_callback: optional callback when an item is removed from the model (unfiltered)
        :param content_callback: optional callback when the content of the model changes
        :param allowable types: optional list of allowable types in the model
        :param filter_change_callback: optional callback when the filtered data changes
        :param data_changed_callback: optional callback when the model data changes (onItemChanged (model, index, new_item, old_item, operation))
        :param data: optional initial data for the model

        """
        super().__init__()
        self._old_hash = None  # last change hash
        self._item_changed_callbacks = [self.onItemChanged]
        self._data_changed_callbacks = []
        self._content_callback = None
        self._filter_data_changed_callbacks = []
        if filtered_data_change_callback:
            self._filter_data_changed_callbacks.append(filtered_data_change_callback)
        self._initializing = True

        self._index_map = TriggerDict()  # map of input_id to index
        self._index_map.addCallback(self._handle_data_changed)  # only track one of the two maps as a change in one also changes the other
        self._item_map = TriggerDict()  # map of input_id to index
        self._extra_data = data

        self._filtered_index_map = {}  # map of [filter][index : int to item : object] - one per filter
        self._filtered_item_map = {}  # map of [filter][item : object to index : int] - one per filter

        self._filtered_callback_map: dict[str, list[Callable]] = {}
        self._sort_callback: Callable = None
        self._filtered_enabled: bool = filter_callback is not None
        self._sort_enabled: bool = sort_callback is not None
        self._suspend_stack = 1  # tracks suspension of change events (suspend while initializing)
        self._show_filtered_only = False
        self._change_pending = False  # true if a change is pending

        self.registerFilter(self.DEFAULT_FILTER)

        assert model_description, "model description not provided"
        self._model_description = model_description
        self._allowed_types = allowed_types

        assert isinstance(change_callback, Callable) if change_callback is not None else True, "Invalid change callback"
        assert isinstance(allowed_types, tuple) if allowed_types is not None else True, "allowed types must be a tuple"

        assert isinstance(added_callback, Callable) if added_callback is not None else True, "Invalid add callback"
        assert isinstance(removed_callback, Callable) if removed_callback is not None else True, "Invalid remove callback"

        self._add_callback = added_callback
        self._remove_callback = removed_callback

        self.setSortCallback(sort_callback)
        if filter_callback:
            self.setFilterCallback(filter_callback)

        if change_callback:
            self.addCallback(change_callback)

        if item_changed_callback:
            self.addOnItemChangedCallback(item_changed_callback)

        self.setContentCallback(content_callback)

        self._suspend_stack = 0  # allow change events to be processed
        self._initializing = False

    def registerFilter(self, filter: str, callback: Callable = None):
        """registers a new filtered data set in the model
        if the filter exists, the request is ignored

        parameters:
            filter: The name of the filter to register.
            callback: A callable to be invoked when filtered data changes (optional)

        """
        apply = False
        if filter not in self._filtered_index_map:
            self._filtered_index_map[filter] = TriggerDict()
            apply = True
        if filter not in self._filtered_item_map:
            self._filtered_item_map[filter] = TriggerDict()
            apply = True
        if callback is not None:
            if filter not in self._filtered_callback_map:
                self._filtered_callback_map[filter] = []
            if callback not in self._filtered_callback_map[filter]:
                self._filtered_callback_map[filter].append(callback)
            self._filtered_enabled = True  # enable filtering if a callback is provided
            apply = True
        if apply:
            self.applyFilter(filter=filter)

    def unregisterFilter(self, filter: str):
        """removes a filtered data set from the model, or a specific callback if provided"""

        # remove all callbacks for that filter
        if filter in self._filtered_callback_map:
            self._filtered_callback_map[filter].clear()

        if filter in self._filtered_index_map:
            del self._filtered_index_map[filter]
        if filter in self._filtered_item_map:
            del self._filtered_item_map[filter]
        if filter in self._filtered_callback_map:
            del self._filtered_callback_map[filter]  # clear any callbacks for that filter
            self._filtered_enabled = bool(self._filtered_callback_map)  # disable filtering if no callbacks remain


    def registerFilteredDataChangeCallback(self, callback: Callable):
        """registers a callback for when filtered data changes"""
        if callback and callback not in self._filter_data_changed_callbacks:
            self._filter_data_changed_callbacks.append(callback)

    def unregisterFilteredDataChangeCallback(self, callback: Callable):
        """unregisters a callback for when filtered data changes"""
        if callback and callback in self._filter_data_changed_callbacks:
            self._filter_data_changed_callbacks.remove(callback)

    def _fire_filtered_data_changed_callbacks(self):
        """calls all registered filtered data change callbacks"""
        for callback in self._filter_data_changed_callbacks:
            callback()

    def dispose(self):
        """disposes of the model and cleans up resources"""
        self._index_map.clearCallbacks()
        self._item_changed_callbacks.clear()
        self._data_changed_callbacks.clear()
        self._item_map.clear()
        self._index_map.clear()
        self._filtered_item_map.clear()
        self._filtered_index_map.clear()
        self._filtered_callback_map.clear()
        self._filter_data_changed_callbacks.clear()
        self._filtered_enabled = False
        self._content_callback = None

    def setContentCallback(self, callback: Callable):
        """sets the content changed callback for this model"""
        if __debug__:
            if callback:
                assert isinstance(callback, Callable), "invalid callback"
                sig = inspect.signature(callback)
                if len(sig.parameters) != 3:
                    raise TypeError("Content callback must accept exactly three parameters: data, force, and operation")

        current_callback = self._content_callback
        if current_callback != callback:
            # remove the old
            if current_callback is not None:
                self.removeCallback(current_callback)
        if not callback:
            pass
        self._content_callback = callback

        # propagate
        model_list = [item for item in self._item_map if hasattr(item, "setContentCallback")]
        for item in model_list:
            item.setContentCallback(callback)

    def _register_content(self, item):
        """registers the content for the item"""
        if hasattr(item, "setContentCallback"):
            item.setContentCallback(self._content_callback)

    def _unregister_content(self, item):
        """unregisters the content for the item"""
        if hasattr(item, "setContentCallback"):
            item.setContentCallback(None)

    def _notify_changed(self, data=None, force: bool = False, operation: str = "update"):
        if self._content_callback:
            self._content_callback(data, force, operation)

    def setItemAt(self, index: int, item, emit=True, filter: str = DEFAULT_FILTER):
        self._set_item_at(index, item, emit, "setItemAt", filter)

    def _set_item_at(self, index: int, item, emit=True, operation: str = "add", filter: str = DEFAULT_FILTER):
        """sets the item for the specific index"""
        # ensure the item is hashable
        assert isinstance(item, _collections_abc.Hashable), "item must be hashable"
        assert isinstance(index, int), "Index must be an integer"

        old_item = self._index_map[index] if index in self._index_map else None

        self._index_map[index] = item
        self._item_map[item] = index
        self._register_content(item)
        self.applyFilter(emit=emit, filter=filter)
        self._fireChanged()
        self._notify_changed(data=item, operation=operation)
        self.onItemChanged(self, index, item, old_item, operation)
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

    def setFilterCallback(self, callback, filter=DEFAULT_FILTER):
        """changes or clears the filter callback"""
        assert isinstance(callback, Callable) if callback is not None else True, "Invalid filter callback"
        self.addFilterCallback(filter, callback)
        self._filtered_enabled = True  # enable filtering
        # update
        self.applyFilter(filter=filter)

    def addFilterCallback(self, filter, callback):
        """adds a new filter callback for a specific filter"""
        assert isinstance(callback, Callable), "Invalid filter callback"
        assert filter is not None, "Filter must be specified"
        self.registerFilter(filter)
        if filter not in self._filtered_callback_map:
            self._filtered_callback_map[filter] = []
        if callback not in self._filtered_callback_map[filter]:
            self._filtered_callback_map[filter].append(callback)
            self._filtered_enabled = True  # enable filtering if a filter callback is added
            self.applyFilter(filter=filter)

    def removeFilterCallback(self, filter, callback: Callable):
        """removes a filter callback for a specific filter"""
        if filter in self._filtered_callback_map and callback in self._filtered_callback_map[filter]:
            self._filtered_callback_map[filter].remove(callback)

    def clearFilterCallbacks(self, filter):
        """removes all filter callback for a specific filter"""
        if filter in self._filtered_callback_map:
            self._filtered_callback_map[filter].clear()

    def setFilterEnabled(self, value: bool):
        """enables or disables filtering"""
        self._filtered_enabled = value

    def extend(self, items: list, emit=True):
        """extends the model with a list of items"""
        if not items:
            return
        for item in items:
            self.add(item, emit=False)
        if emit:
            self.applyFilter(emit=emit)
            self._fireChanged()



    def append(self, item) -> int:
        """
        Appends an item to the model
        :param item: the item to append to the model
        :returns int: inserted position
        """
        return self.add(item)

    def add(self, item: object, index=-1, emit=True) -> int:
        """
        Adds (appends) a new entry to the model, returns the position inserted
        :param item: the item to append to the model
        :param callback: optional, filtering callback, takes an item as a parameter and returns true if the item should be included in the filtered data
        :returns int: inserted position
        """
        if item is None:
            return -1

        items = item if isinstance(item, list) else [item]

        if index in self._index_map:
            # replacement logic if the index is already in the map
            old_item = self._index_map[index]
            if old_item == item:
                # nothing to do
                return index
            self.markDirty()
            self._set_item_at(index, item, emit=emit, operation="replace")
            return index

        for item in items:
            if self._allowed_types:
                if not isinstance(item, self._allowed_types):
                    raise ValueError(f"invalid data type for model - got [{type(item).__name__}] - expected one of {self._allowed_types}")
                assert isinstance(item, _collections_abc.Hashable), "item must be hashable"

            if item not in self._index_map:
                # not in the map
                self.markDirty()
                if index == -1:
                    # find the next available index
                    index = 0
                    while index in self._index_map:
                        index += 1
                self._set_item_at(index, item, emit=emit, operation="add")

            else:
                # item is already in the map - this is a move
                old_index = self._index_map[item]
                if old_index != index:
                    self.markDirty()
                    self._set_item_at(index, item, emit=emit, operation="move")

            return index
        return -1  # if the item was not added

    def _onItemChanged(self, model, index: int, new_item, old_item, operation):
        """override by derived classes as needed"""
        for callback in self._item_changed_callbacks:
            callback(model, index, new_item, old_item, operation)

    def onItemChanged(self, model, index: int, new_item, old_item, operation):
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
            for index in range(stop_index, start_index, -1):
                data = self._index_map[index]
                self._index_map[index + 1] = data
                self._item_map[data] = index + 1

        # insert the item
        self._index_map[i] = item
        self._item_map[item] = i

        self._register_content(item)
        self._notify_changed(data=item, operation="insert")

        self._onItemChanged(self, i, item, old_item, "insert")

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

        self._register_content(item)

        if apply_filter:
            self.applyFilter(emit=emit)
        if emit:
            self._fireChanged()
            self._notify_changed(data=item, operation="place")

        self._onItemChanged(self, index, item, old_item, "place")

    def _reindex(self, emit=True, filter=DEFAULT_FILTER):
        """reorders the indices in the model to be consecutive starting from 0"""
        for new_index, item in enumerate(self._index_map.values()):
            self._item_map[item] = new_index
        self._index_map = TriggerDict.copyFrom({new_index: item for new_index, item in enumerate(self._index_map.values())})
        self.applyFilter(emit=False, filter=filter)  # update filtered data as well
        verbose = gremlin.config.Configuration().verbose_mode_execution
        if verbose:
            syslog.info("Reindex results:")
            for index, item in self._filtered_index_map[filter].items():
                syslog.info(f"Filtered index [{index}] maps to item [{item}]")

        if emit:
            self._fireChanged()
            self._notify_changed(data=self, operation="reindex")

    def remove(self, item, emit=True):
        """Removes the given entry from the model."""

        if item in self._index_map:
            index = item
            item = self._index_map[index]
        elif item in self._item_map:
            index = self._item_map[item]
        else:
            index = -1

        if index != -1:
            # syslog.info(f"removing item {item.id} from model {self.id} current count: {self.count()}")

            if hasattr(item, "_cleanup"):
                item._cleanup()
            del self._item_map[item]
            del self._index_map[index]
            # reorder indices
            self._reindex(False)
            assert item not in self._item_map, "item not removed from model"
            # syslog.info(f"item {item.id} removed from model {self.id} new count: {self.count()}")
            if emit:
                self._fireChanged()
            self._notify_changed(data=item, operation="remove")
            self._unregister_content(item)
            self._onItemChanged(self, index, None, item, "remove")
        else:
            if __debug__:
                syslog.info(f"MODEL: Item not found in remove: {item} hash[{hash(item)}]")
                syslog.info(f"  Current item map: model size: {len(self._item_map)}")
                index = 0
                for key, item in self._item_map.items():
                    syslog.info(f"  [{index}] Item map key [{str(key)}] hash[{hash(key)}] maps to item [{str(item)}]")
                    index += 1
                pass

    def removeAt(self, index: int, emit=True, filter=DEFAULT_FILTER):
        """removes the entry at the given filteredmodel index"""
        if index in self._index_map:
            item = self._index_map[index]
            self._unregister_content(item)
            if hasattr(item, "_cleanup"):
                item._cleanup()
            del self._item_map[item]
            del self._index_map[index]
            self._reindex(emit=False, filter=filter)
            self._notify_changed(data=item, operation="remove")

            if emit:
                self._fireChanged()
            self._onItemChanged(self, index, None, item, "remove")
        else:
            if __debug__:
                syslog.info(f"MODEL: Index not found in removeAt: {index}")

    def removeRow(self, index: int, emit=True, filter=DEFAULT_FILTER):
        """removes the entry at the given model index"""
        self.removeAt(index, emit=emit, filter=filter)

    def clear(self, emit=True):
        """Removes all entries from the model."""
        if self._item_map:
            self.pushSuspend()
            for item in self._item_map:
                self._unregister_content(item)
            self._item_map.clear()
            self._index_map.clear()
            for filter in self._filtered_index_map:
                self._filtered_index_map[filter].clear()
                self._filtered_item_map[filter].clear()
            self.popSuspend()
            if emit:
                self._fireChanged()
            self._onItemChanged(self, -1, None, None, "clear")

    def data(self, index: int):
        """returns the item stored at the given index, None if not found
        :param index: the index
        """
        if index in self._index_map:
            return self._index_map[index]
        return None

    def filteredData(self, index: int, filter=DEFAULT_FILTER):
        """returns the filtered item at the given index, None if not found"""
        if filter in self._filtered_index_map and index in self._filtered_index_map[filter]:
            return self._filtered_index_map[filter][index]
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
        return self.unfilteredItemAt(index)

    def items(self, filter=DEFAULT_FILTER):
        """returns all items in the filtered model"""
        return self._filtered_index_map[filter].items()

    def filteredItemAt(self, index: int, filter=DEFAULT_FILTER):
        """gets the filtered item at the given index if it exists"""
        return self.filteredData(index, filter)

    def unfilteredItemAt(self, index: int):
        """gets the item at the given index of the unfiltered model, returns None if not found"""
        return self._index_map.get(index, None)

    def unfilteredItems(self):
        """returns all items in the unfiltered model"""
        return self._index_map.items()

    def unfilteredItemsList(self):
        """returns all items in the unfiltered model as a list"""
        return list(self._index_map.values())

    def indexOf(self, item, filter=DEFAULT_FILTER) -> int:
        """returns the index of the item (filtered model), -1 if not found"""
        if filter in self._filtered_item_map and item in self._filtered_item_map[filter]:
            return self._filtered_item_map[filter][item]
        if gremlin.config.Configuration().verbose_mode_ui_level(2):
            syslog.info(f"MODEL: Item not found in filtered item map: {item}")
            syslog.info(f"\tFiltered item map contents: item count: {len(self._filtered_item_map[filter])}")
            for key in self._filtered_item_map[filter]:
                syslog.info(f"\t\t[{key}]: {self._filtered_item_map[filter][key]}")

        return -1

    def pop(self, index: int, filter=DEFAULT_FILTER):
        """removes and returns the item at the given index, None if not found"""
        if index in self._index_map:
            item = self._index_map[index]
            self.removeAt(index, filter=filter)

            return item
        return None

    def push(self, item, filter=DEFAULT_FILTER):
        """adds the item to the model and returns its zero based index"""
        index = len(self._index_map) - 1
        self._index_map[index] = item
        self._item_map[item] = index

        self._filtered_index_map[filter][index] = item
        self._filtered_item_map[filter][item] = index
        return index

    def unfilteredIndexOf(self, item) -> int:
        """returns the index of the item (unfiltered model), -1 if not found"""
        if item in self._item_map:
            return self._item_map[item]
        return -1

    def swap(self, index1: int, index2: int, emit=True):
        """swaps the items at the given indices"""
        if index1 == index2:
            return
        if index1 in self._index_map and index2 in self._index_map:
            self._index_map[index1], self._index_map[index2] = self._index_map[index2], self._index_map[index1]
            self._item_map[self._index_map[index1]] = index1
            self._item_map[self._index_map[index2]] = index2
            self.applyFilter(emit=emit)
            if emit:
                self._fireChanged()

    def rows(self) -> int:
        """returns the size of the unfiltered model"""
        return len(self._index_map)

    def unfilteredCount(self) -> int:
        """returns the size of the unfiltered model"""
        return len(self._index_map)

    def count(self, filter=DEFAULT_FILTER) -> int:
        """returns the size of the filtered model"""
        return len(self._filtered_index_map[filter])

    def filteredCount(self, filter=DEFAULT_FILTER) -> int:
        """returns the size of the filtered model"""
        return len(self._filtered_index_map[filter])

    def clearFilter(self, filter=None):
        """clears all filters (none) or given filter"""
        if filter is None:
            # all filters
            filters_to_clear = list(self._filtered_index_map.keys())
        else:
            filters_to_clear = [filter] if filter in self._filtered_index_map else []

        for filter in filters_to_clear:
            if self._filtered_index_map[filter].id != self._index_map.id:
                self._filtered_index_map[filter].clearCallbacks()
                self._filtered_item_map[filter].clearCallbacks()
                self._filtered_index_map[filter] = TriggerDict.copyFrom(self._index_map)
                self._filtered_item_map[filter] = TriggerDict.copyFrom(self._item_map)

    @property
    def allowedInputTypes(self) -> tuple:
        """gets the allowed input types in the model, if any"""
        return self._allowed_types

    def applyFilter(self, sort=True, force=False, emit=True, filter=DEFAULT_FILTER):
        """Applies the filter to the source data
        :param filter: the filter to apply, None for all filters
        :param sort: true to sort the data after filtering (only has effect if a sorting callback was provided)
        :param emit: true to emit a data changed signal after filtering
        """

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(2)
        # verbose = True

        if filter is None:
            filters = list(self._filtered_index_map.keys())
        else:
            filters = [filter] if filter in self._filtered_index_map else []

        if not self._can_filter():
            # model is not filtered
            for filter in filters:
                self._filtered_index_map[filter] = TriggerDict.copyFrom(self._index_map)
                self._filtered_item_map[filter] = TriggerDict.copyFrom(self._item_map)

            self._fire_filtered_data_changed_callbacks() # fire data changed callbacks
            return

        if not self._filtered_enabled:
            # filters are not enabled - reset the filters

            for filter in filters:
                if verbose:
                    syslog.info(f"MODEL INPUT FILTER: resetting filter [{filter}]")
                if self._filtered_index_map[filter].id != self._index_map.id:
                    # reset filters if previously enabled
                    self._filtered_index_map[filter] = TriggerDict.copyFrom({key: value for key, value in self._index_map.items()})
                    self._filtered_item_map[filter] = TriggerDict.copyFrom({key: value for key, value in self._item_map.items()})

            self._fire_filtered_data_changed_callbacks() # fire data changed callbacks
            if emit:
                self._fireChanged()
                # fire the filter operation
                self._onItemChanged(self, -1, None, None, "filter")

            return

        # filtering enabled
        # force = False

        new_index_map = TriggerDict()
        new_item_map = TriggerDict()

        new_index = 0
        for item in self._index_map.values():
            # determine if the item should be included by calling the relevant callbacks - the first one that fails excludes the item
            include = True
            filter_callbacks = self.getFilterCallbacks(filter)
            for callback in filter_callbacks:
                include = callback(item, filter)
                if not include:
                    break

            if include:
                if verbose:
                    syslog.info(f"\t{item.display_name} -> ON")
                new_index_map[new_index] = item
                new_item_map[item] = new_index
                new_index += 1
                force = True
            else:
                if verbose:
                    syslog.info(f"\t{item.display_name} -> OFF")
        if verbose and new_index == 0:
            syslog.info("\tall inputs are filtered for this device")

        old_hashes = {f: self.hashKey(filter=f) for f in filters}  # before the maps are replaced
        maps_changed =  self._maps_different(self._index_map, new_index_map)
        has_changed = maps_changed or filter != self.DEFAULT_FILTER
        if has_changed:
            for filter in filters:
                self._filtered_index_map[filter] = new_index_map
                self._filtered_index_map[filter].addCallback(self._handle_data_changed)
                self._filtered_item_map[filter] = new_item_map
                force = True
        else:
            for filter in filters:
                self._filtered_index_map[filter] = TriggerDict.copyFrom(self._index_map)
                self._filtered_item_map[filter] = TriggerDict.copyFrom(self._item_map)
                force = True

        for filter in filters:
            self.applySort(emit=False, filter=filter)
            new_hash = self.hashKey(filter=filter)
            if old_hashes[filter] != new_hash or has_changed:
                # filter or sort changed the visible items
                has_changed = True

        if has_changed:
            # fire the data changed callbacks for filtered data
            self._fire_filtered_data_changed_callbacks()

        if emit or has_changed:
            if self._suspend_stack == 0:
                self._fireChanged(force)
                self._onItemChanged(self, -1, None, None, "filter")
            else:
                self._change_pending = True

    def setItemFiltered(self, item: object, value: bool, emit=True, filter=DEFAULT_FILTER) -> int:
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
                if item in self._filtered_item_map[filter]:
                    return self._filtered_item_map[filter][item]  # already filtered

                index = len(self._filtered_index_map[filter]) - 1  # zero based
                self.pushSuspend()

                self._filtered_index_map[filter][index] = item
                self._filtered_item_map[filter][item] = index
                self.popSuspend()
                if emit:
                    self._fireChanged()
                return index
            else:
                # remove from the filtered list
                if item in self._filtered_item_map[filter]:
                    self.pushSuspend()
                    index = self._filtered_item_map[filter][item]
                    del self._filtered_index_map[filter][index]
                    del self._filtered_item_map[filter][item]
                    self.popSuspend()
                    if emit:
                        self._fireChanged()

        return -1

    def applySort(self, emit=True, filter=DEFAULT_FILTER):
        """sorts the model based on the callback"""
        import gremlin.input_item

        if not self._can_sort():
            # nothing to do
            return
        items = list(self._filtered_item_map[filter].keys())
        if not items:
            return
        indices = self._sort_callback(items)
        if indices is None:
            # callback returning nothing means no sort - skip
            return
        # Materialize generators before validation / zip (do not consume twice).
        indices = list(indices)
        if not indices:
            return
        if __debug__:
            unique = set(indices)
            count = len(self._filtered_item_map[filter])

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
            self._filtered_index_map[filter][index] = item
            self._filtered_item_map[filter][item] = index
        if emit:
            self._fireChanged()

    def sort(self, callback=None, emit=True, filter=DEFAULT_FILTER):
        """Sort filtered items.

        Device tabs call ``model.sort(self._sort_callback)`` where the callback is
        ``callback(items: list) -> list`` of sorted items (sorted in place ok).

        Without a callback, uses the model's configured sort via :meth:`applySort`.
        """
        if callback is None:
            self.applySort(emit=emit)
            return

        items = list(self._filtered_index_map[filter].values())
        if not items:
            items = list(self._index_map.values())
        if not items:
            return

        sorted_items = callback(list(items))
        if sorted_items is None:
            return
        sorted_items = list(sorted_items)
        if not sorted_items:
            return

        self.pushSuspend()
        try:
            self._filtered_index_map[filter] = TriggerDict()
            self._filtered_item_map[filter] = TriggerDict()
            self._filtered_index_map[filter].addCallback(self._handle_data_changed)
            for index, item in enumerate(sorted_items):
                self._filtered_index_map[filter][index] = item
                self._filtered_item_map[filter][item] = index

            # Keep the unfiltered maps in the same visible order when they match 1:1.
            if len(self._index_map) == len(sorted_items):
                self._index_map = TriggerDict()
                self._item_map = TriggerDict()
                self._index_map.addCallback(self._handle_data_changed)
                for index, item in enumerate(sorted_items):
                    self._index_map[index] = item
                    self._item_map[item] = index
        finally:
            self.popSuspend()

        if emit:
            self._fireChanged()
            self.sorted.emit()
            self._notify_changed(data=self, operation="sort")

    def setFilteredEnabled(self, value: bool, emit=True):
        """enables or disables the filter - has no effect is no filtering is setup"""
        if self._filtered_callback_map and self._filtered_enabled != value:
            self._filtered_enabled = value
            self.applyFilter(emit=emit)

    def isFilteredEnabled(self) -> bool:
        """true if filtering is enabled"""
        return self._filtered_enabled

    def _can_filter(self) -> bool:
        """true if filtering can happen"""
        return bool(self._filtered_callback_map) and self._filtered_enabled

    def _can_sort(self) -> bool:
        """true if sorting can happen"""
        return self._sort_enabled and self._sort_callback is not None

    def isFiltered(self) -> bool:
        """true if the model is currently filtered"""
        return self._filtered_enabled and bool(self._filtered_callback_map) and self._maps_different(self._index_map, self._filtered_index_map)

    def getFilterCallbacks(self, filter=DEFAULT_FILTER) -> list[Callable]:
        """gets the model's filtering callbacks"""
        return self._filtered_callback_map[filter] if filter in self._filtered_callback_map else []

    def _maps_different(self, m1: TriggerDict, m2: TriggerDict):
        """ compare two trigger dicts looking for differences in the stored values

            returns False if the two trigger dicts are considered equal, True otherwise
        """
        if isinstance(m1, TriggerDict) and isinstance(m2, TriggerDict):
            if m1.id == m2.id:
                # same map = no filter applied
                return False

            if len(m1) != len(m2):
                # fast comparison on counts
                return True # different length

            # same count = compare actual contents
            diff = set(m1.items()) - set(m2.items())
            return bool(diff)

        # different by default
        return True

        # removed as it's now handled above

    def getFilteredIndices(self, filter=DEFAULT_FILTER):
        """returns the list of indices currently visible in the model"""
        return [index for index in self._filtered_index_map[filter]]

    def getUnfilteredIndices(self):
        """returns the list of indices currently visible in the model"""
        return [index for index in self._index_map]

    def getFilteredItems(self, filter=DEFAULT_FILTER):
        """returns the list of filtered items"""
        if filter not in self._filtered_index_map:
            return []
        return self._filtered_index_map[filter].values()

    def getUnfilteredItems(self):
        """returns the list of unfiltered items"""
        return self._index_map.values()

    def getSequentialItemIndex(self, index: int, filter=DEFAULT_FILTER):
        """returns the item by sequential index in the filtered list"""
        items = list(self._filtered_index_map[filter].values())
        if index >= 0 and index < len(items):
            return items[index]
        return None

    def getFilteredMap(self, filter=DEFAULT_FILTER):
        """gets index,input_item tuples for all filtered items in the model"""
        return self._filtered_index_map[filter].items()

    def getUnfilteredMap(self):
        """gets index,input_item tuples for all unfiltered items in the model"""
        return self._index_map.items()

    def refresh(self, emit=True):
        """trigger a data change if the model has changed - use this to prevent updates if the data didn't change"""
        self._fireChanged(emit=emit)

    def trigger(self, force=True, emit=True):
        """trigers a model change manually - use this to force a reload even if the data didn't change"""
        self._fireChanged(force=force, emit=emit)

    def pushSuspend(self, filter=DEFAULT_FILTER):
        """suspends change notifications"""
        if self._suspend_stack == 0:
            self._item_map.pushSuspend()
            self._index_map.pushSuspend()
            self._filtered_index_map[filter].pushSuspend()
            self._filtered_item_map[filter].pushSuspend()
        self._suspend_stack += 1

    def popSuspend(self, reset=False, emit=True, filter=DEFAULT_FILTER):
        """restores change notifications"""
        if reset and self._suspend_stack > 0:
            self._suspend_stack = 0
        if self._suspend_stack > 0:
            self._suspend_stack -= 1
        if self._suspend_stack == 0:
            self._item_map.popSuspend(reset)
            self._index_map.popSuspend(reset)
            self._filtered_index_map[filter].popSuspend(reset)
            self._filtered_item_map[filter].popSuspend(reset)
            self._fireChanged(force=self._change_pending, emit=emit)

    def hashKey(self, filter=DEFAULT_FILTER):
        """returns a hash key representing the current state of the model"""
        if filter not in self._filtered_item_map:
            return 0
        return hash(tuple(self._filtered_item_map[filter].keys()))

    def resetChanges(self):
        """resets any changes to the model"""
        self._suspend_stack = 0
        self._change_pending = False

    def addCallback(self, callback: Callable[[object, bool], None]):
        """adds a change callback to be called when the model data changes"""
        if __debug__:
            if callback is not None and not callable(callback):
                raise TypeError("Callback must be callable")
            # ensure the callback has the correct signature
            import inspect

            if callback:
                sig = inspect.signature(callback)
                if len(sig.parameters) != 2:
                    raise TypeError("Callback must accept exactly two parameters: data and force")

        if callback and callback not in self._data_changed_callbacks:
            self._data_changed_callbacks.append(callback)

    def addOnItemChangedCallback(self, callback: Callable[[object, int, object, object, str], None]):
        """adds a OnitemChanged callback that includes the operation and the old value, and new value as parameters

        operations:
            "add" - when an item is added
            "remove" - when an item is removed
            "update" - when an item is updated
            "clear" - when the model is cleared

        """

        if __debug__:
            if callback is not None and not callable(callback):
                raise TypeError("Callback must be callable")
            # ensure the callback has the correct signature
            import inspect

            if callback:
                sig = inspect.signature(callback)
                if len(sig.parameters) != 5:
                    raise TypeError("Callback must accept exactly five parameters: source, index, old_value, new_value, and operation")

        if callback and callback not in self._item_changed_callbacks:
            self._item_changed_callbacks.append(callback)

    def removeOnItemChangedCallback(self, callback: Callable):
        if callback in self._item_changed_callbacks:
            self._item_changed_callbacks.remove(callback)

    def removeCallback(self, callback: Callable):
        """removes a callback from the list of callbacks to be called when the model data changes"""
        if callback in self._data_changed_callbacks:
            self._data_changed_callbacks.remove(callback)

    def modelChanged(self) -> bool:
        """true if data has changed"""
        return self._change_pending or hash(self) != self._old_hash

    def _handle_data_changed(self, source, index, old_value, new_value, filter=DEFAULT_FILTER):
        """called when a storage data is changed"""
        if source.id == self._filtered_index_map[filter].id:
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

    def setModelDescription(self, description: str):
        self._model_description = description

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

        if self._initializing or (self._suspend_stack and self._change_pending and not force):
            # skip while initializing or if changes are suspended and not forced
            return
        if gremlin.shared_state.is_running:
            # auto-suspend at runtime
            return
        new_hash = self.hashKey()
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
                callback(self._extra_data, force=force)

            if emit:
                try:
                    self.data_changed.emit()  # @IgnoreException indicate the model changed
                except RuntimeError:
                    # underlying Qt object already deleted (e.g. during tab rebuild)
                    pass

        self._change_pending = False

    # dunder methods

    def __iter__(self):
        """iterator - gets an iterator to the contents"""
        return iter(self._filtered_index_map[self.DEFAULT_FILTER].values())

    def __len__(self):
        """number of items in the model (default filter)"""
        return len(self._filtered_item_map[self.DEFAULT_FILTER])

    def __getitem__(self, index: int):
        """subscribtable"""
        if index in self._filtered_index_map[self.DEFAULT_FILTER]:
            return self._filtered_index_map[self.DEFAULT_FILTER][index]
        raise IndexError("index out of range")

    def __setitem__(self, index: int, item):
        """sets an item at the specified index"""
        self._set_item_at(index, item, emit=True, operation="setItemAt")

    def __delitem__(self, index: int):
        """deletes an item at the specified index"""
        self.removeAt(index)

    def __missing__(self, key):
        raise KeyError(f"Key {key} not found in model")

    def __hash__(self):
        """unique hash value of model contents"""
        return hash((self.id, frozenset(self._index_map.values())))

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        if self.id != other.id:
            return False
        return  self._index_map == other._index_map

