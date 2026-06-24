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


import copy
import ctypes
import ctypes.wintypes as ctwt
from enum import Enum
import os
import uuid
import logging
import traceback
from gremlin.types import DeviceType, DeviceCategory

MAESTRO_VID = 0x1209 # vendor ID for GEX managed devices
GEX_VID = MAESTRO_VID # vendor ID for GEX managed devices
MAESTRO_PID_BASE = 0x1000 # base product ID for Maestro devices
GEX_PID_BASE = MAESTRO_PID_BASE # base product id (sequential) for GEX managed devices
GEX_ID_STRING = "GEX"
GEX_VENDOR_STRING = "GEX"  # vendor string for GEX managed devices
GEX_PRODUCT_STRING = "GEX Custom Device"
GEX_MAX_DEVICES = 16  # maximum number of GEX managed devices
VJOY_VID = 0x1234 # vendor ID for vJoy devices
VJOY_PID = 0x5678 # product ID for vJoy devices

syslog = logging.getLogger("system")


class DILLError(Exception):
    """Exception raised when an error occurs within the DILL module."""

    def __init__(self, value):
        super().__init__(value)


class _GUID(ctypes.Structure):
    """Strcture mapping C information into a set of Python readable values."""

    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_uint8 * 8),
    ]

    def toId(self):
        """converts to short string lowercase format - no dashes or brackets"""
        s = f"{self.Data1:08x}{self.Data2:04x}{self.Data3:04x}"
        for b in self.Data4:
            s += f"{b:02x}"
        return s

    def toInt(self) -> int:
        guid = uuid.UUID(self.toId())
        return guid.int


_GUID_SysKeyboard = _GUID()
_GUID_SysKeyboard.Data1 = 0x6F1D2B61
_GUID_SysKeyboard.Data2 = 0xD5A0
_GUID_SysKeyboard.Data3 = 0x11CF
_GUID_SysKeyboard.Data4[0] = 0xBF
_GUID_SysKeyboard.Data4[1] = 0xC7
_GUID_SysKeyboard.Data4[2] = 0x44
_GUID_SysKeyboard.Data4[3] = 0x45
_GUID_SysKeyboard.Data4[4] = 0x53
_GUID_SysKeyboard.Data4[5] = 0x54
_GUID_SysKeyboard.Data4[6] = 0x00
_GUID_SysKeyboard.Data4[7] = 0x00

_GUID_Virtual = _GUID()
_GUID_Virtual.Data1 = 0x89D5E905
_GUID_Virtual.Data2 = 0x1E26
_GUID_Virtual.Data3 = 0x4C52
_GUID_Virtual.Data4[0] = 0xAD
_GUID_Virtual.Data4[1] = 0x46
_GUID_Virtual.Data4[2] = 0x7B
_GUID_Virtual.Data4[3] = 0xCC
_GUID_Virtual.Data4[4] = 0x06
_GUID_Virtual.Data4[5] = 0xDF
_GUID_Virtual.Data4[6] = 0x4C
_GUID_Virtual.Data4[7] = 0x20

_GUID_Invalid = _GUID()
_GUID_Invalid.Data1 = 0x00000000
_GUID_Invalid.Data2 = 0x0000
_GUID_Invalid.Data3 = 0x0000
_GUID_Invalid.Data4[0] = 0x00
_GUID_Invalid.Data4[1] = 0x00
_GUID_Invalid.Data4[2] = 0x00
_GUID_Invalid.Data4[3] = 0x00
_GUID_Invalid.Data4[4] = 0x00
_GUID_Invalid.Data4[5] = 0x00
_GUID_Invalid.Data4[6] = 0x00
_GUID_Invalid.Data4[7] = 0x00


class _JoystickInputData(ctypes.Structure):
    """Mapping for the JoystickInputData C structure."""

    _fields_ = [
        ("device_guid", _GUID),
        ("input_type", ctypes.c_uint8),
        ("input_index", ctypes.c_uint8),
        ("value", ctwt.LONG),
    ]


class _AxisMap(ctypes.Structure):
    """Mapping for the AxisMap C structure."""

    _fields_ = [("linear_index", ctwt.DWORD), ("axis_index", ctwt.DWORD)]


class _DeviceSummary(ctypes.Structure):
    """Mapping for the DeviceSummary C structure."""

    _fields_ = [
        ("device_guid", _GUID),
        ("vendor_id", ctwt.DWORD),
        ("product_id", ctwt.DWORD),
        ("joystick_id", ctwt.DWORD),
        ("name", ctypes.c_char * ctwt.MAX_PATH),
        ("axis_count", ctwt.DWORD),
        ("button_count", ctwt.DWORD),
        ("hat_count", ctwt.DWORD),
        ("axis_map", _AxisMap * 8),
        ("usage_page", ctwt.WORD),
        ("usage", ctwt.WORD),
    ]


class GUID:
    """Python GUID class."""

    def __init__(self, guid):
        """Creates a new instance.

        Parameters
        ==========
        guid : _GUID
            Mapping of a C struct representing a device GUID
        """

        if isinstance(guid, str):
            try:
                guid = uuid.UUID(guid)
                guid_int = guid.int
                guid = _GUID(guid_int)  # convert to internal _GUID
            except Exception:
                syslog.error(f"GUID: Unable to convert ID {guid} to UUID")
                return None
        elif isinstance(guid, GUID):
            guid_int = guid._guid_int
        elif isinstance(guid, uuid.UUID):
            # convert to ctypes structure using the integer value if the class is given a regular python UUID
            guid_int = guid.int
            guid = _GUID(guid_int)  # convert to internal _GUID
        elif isinstance(guid, int):
            guid = _GUID(guid)
            guid_int = guid.int


        else:
            assert isinstance(guid, _GUID)
            guid_int = guid.toInt()
        self._ctypes_guid = copy.deepcopy(guid)
        self.guid = (
            guid.Data1,
            guid.Data2,
            guid.Data3,
            (guid.Data4[0] << 8) + guid.Data4[1],
            (guid.Data4[2] << 40) + (guid.Data4[3] << 32) + (guid.Data4[4] << 24) + (guid.Data4[5] << 16) + (guid.Data4[6] << 8) + guid.Data4[7],
        )

        self._guid_int: int = guid_int  # for fast hash

    @property
    def valid(self):
        """true if the GUID is valid"""
        return not (self._ctypes_guid.Data1 == 0 and self._ctypes_guid.Data2 == 0 and self._ctypes_guid.Data3 == 0 and self._ctypes_guid.Data4 == 0)

    @property
    def ctypes(self):
        """Returns the object mapping the C structure.

        Returns
        =======
        _GUID
            Mapping of a C GUID structure
        """
        return self._ctypes_guid

    def toId(self):
        return str(self)
        # return f"{self.guid[0]:08x}{self.guid[1]:04x}{self.guid[2]:04x}{self.guid[3]:04x}{self.guid[4]:012x}"

    def __str__(self):
        """Returns a string representation of the GUID. No dashes or brackets, lowercase"""
        return f"{self.guid[0]:08x}{self.guid[1]:04x}{self.guid[2]:04x}{self.guid[3]:04x}{self.guid[4]:012x}"

    def __eq__(self, other):
        if isinstance(other, uuid.UUID):
            return other.int == self._guid_int
        return hash(self) == hash(other)

    def __lt__(self, other):
        """Returns the result of the < operator.

        Parameters
        ==========
        other : GUID
            Instance with which to perform the equality comparison

        Returns
        =======
        bool
            True if this instance is < other, False otherwise
        """
        return str(self) < str(other)

    def __hash__(self):
        """hash value"""
        return self._guid_int
        # return hash((
        #     self._ctypes_guid.Data1,
        #     self._ctypes_guid.Data2,
        #     self._ctypes_guid.Data3,
        #     self._ctypes_guid.Data4[0],
        #     self._ctypes_guid.Data4[1],
        #     self._ctypes_guid.Data4[2],
        #     self._ctypes_guid.Data4[3],
        #     self._ctypes_guid.Data4[4],
        #     self._ctypes_guid.Data4[5],
        #     self._ctypes_guid.Data4[6],
        #     self._ctypes_guid.Data4[7]
        # ))

    def to_dict(self):
        return {"guid": str(self)}

    @classmethod
    def from_dict(cls, data):
        return cls(data.get("guid"))


GUID_Keyboard = GUID(_GUID_SysKeyboard)
GUID_Virtual = GUID(_GUID_Virtual)
GUID_Invalid = GUID(_GUID_Invalid)


class InputType(Enum):
    """Enumeration of valid input types that can be reported."""

    Axis = (1,)
    Button = (2,)
    Hat = 3

    @staticmethod
    def from_ctype(value):
        """Returns the enum type corresponding to the provided value.

        Parameters
        ==========
        value : int
            The integer value representing the input type according to DILL

        Returns
        =======
        InputType
            Enum value representing the correct InputType
        """

        from gremlin.util import log_sys_error

        if value == 1:
            return InputType.Axis
        elif value == 2:
            return InputType.Button
        elif value == 3:
            return InputType.Hat

        log_sys_error(f"Invalid DLL input type value received: {value:d}")
        return None


class DeviceActionType(Enum):
    """Represents the state change of a device."""

    Connected = 1
    Disconnected = 2

    @staticmethod
    def from_ctype(value):
        """Returns the enum type corresponding to the provided value.

        Parameters
        ==========
        value : int
            The integer value representing the action type according to DILL

        Returns
        =======
        DeviceActionType
            Enum value representing the correct DeviceAction
        """
        if value == 1:
            return DeviceActionType.Connected
        elif value == 2:
            return DeviceActionType.Disconnected
        else:
            raise DILLError(f"Invalid device action type {value:d}")


class InputEvent:
    """Holds information about a single event.

    An event is an axis, button, or hat changing its state. The type of
    input, the index, and the new value as well as device GUID are reported.
    """

    def __init__(self, data):
        """Creates a new instance.

        Parameters
        ==========
        data : _JoystickInputData
            The data received from DILL and to be held by this instance

        fix: if the type is not recognized, use a 0 Guid and handle nicely instead of throwing an error

        """

        input_type = InputType.from_ctype(data.input_type)
        if input_type:
            self.device_guid = GUID(data.device_guid)
            self.input_type = input_type
            self.input_index = int(data.input_index)
            self.value = int(data.value)
        else:
            self.device_guid = GUID.InvalidGuid()
            self.input_type = InputType.Button
            self.input_index = 0
            self.value = 0

    def __str__(self) -> str:
        return f"InputEvent: GUID [{self.device_guid}] type: [{self.input_type}] index: [{self.input_index}] value: [{self.value}]"


class AxisMap:
    """Holds information about a single axis map entry.

    An AxisMap holds a mapping from an axis' sequential index to the actual
    descriptive DirectInput axis index.
    """

    def __init__(self, data=None):
        """Creates a new instance.

        Parameters
        ==========
        data : _AxisMap
            The data received from DILL and to be held by this instance
        """

        self.linear_index = 0
        self.axis_index = 0
        if data is not None:
            self.linear_index = data.linear_index
            self.axis_index = data.axis_index

    def getName(self) -> str:
        """gets the name of the axis based on its axis index"""
        axis_index = self.axis_index
        match axis_index:
            case 0:
                return ""
            case 1:
                return "(1) X"
            case 2:
                return "(2) Y"
            case 3:
                return "(3) Z"
            case 4:
                return "(4) RX"
            case 5:
                return "(5) RY"
            case 6:
                return "(6) RZ"
            case 7:
                return "(7) S1"
            case 8:
                return "(8) S2"

        return f"Invalid: {self.axis_index}"


class DeviceSummary:
    """Holds information about a single device.

    This summary holds static information about a single device's layout.
    """

    def __init__(self, data=None):
        """Creates a new instance.

        Parameters
        ==========
        data : _DeviceSummary
            The data received from DILL and to be held by this instance
        """
        import gremlin.util
        import gremlin.types

        self._connected = False  # true if device is connected
        self._disabled = False  # true if the device is disabled in GremlinEx
        self._hard_disabled = False  # true if the device is out of spec or otherwise excluded by GEX
        self.axis_count = 0
        self.button_count = 0
        self.hat_count = 0
        self._is_virtual = None
        self.linear_id_map = {}  # map of linear ID to axis ID
        self.usage_page = 0  # HID usage page
        self.usage = 0  # HID usage
        self.axis_names = []
        self.axismap_list = []
        self.axis_id_map = {}  # map of axis ID to linear ID
        self.input_enabled = False
        self.vjoy_id = -1
        self.vendor_id = 0  # vendor ID
        self.product_id = 0  # product ID
        self.name = None
        self._device_type = gremlin.types.DeviceType.NotSet
        self._device_category = gremlin.types.DeviceCategory.NotSet
        self.data = {}  # tracked data for this device, example, stepped index data for an axis
        self._get_button_callback = None  # custom callback to read a button value from this device if a special device
        self._get_axis_callback = None  # custom callback to read an axis value from this device if a special device
        self._get_hat_callback = None  # custom callback to read a hat value if this device is a special device
        self.visible = True # device is visible by default in the UI
        if data is not None:
            self.device_guid = GUID(data.device_guid)
            self.device_id = gremlin.util.normalize_guid(self.device_guid)
            self._device_type = gremlin.types.DeviceType.Joystick
            self.vendor_id = data.vendor_id
            self.product_id = data.product_id
            self.joystick_id = data.joystick_id

            # try various encodings of the byte string as it can be finicky
            encodings = ["utf-8", "unicode_escape", "latin-1"]
            self.name = ""
            for encoding in encodings:
                try:
                    name = data.name.decode(encoding, errors="replace")
                    self.name = name.replace("\ufffd", "")  # remove junk characters
                    break
                except Exception:
                    pass
            if not self.name:
                syslog.error(f"Unable to decode device name: {data.name} - contains invalid characters.  Defaulting.")
                self.name = f"Unable to decode {self.device_id} "

            self.axis_count = data.axis_count
            self.button_count = data.button_count
            self.hat_count = data.hat_count
            self.usage_page = data.usage_page
            self.usage = data.usage

            logical_count = 0
            self.input_enabled = True  # allow usage as an input device by default for special and physical devices
            index = 0
            for am in data.axis_map:
                index += 1
                if am.axis_index == 0:
                    # no axis
                    continue

                axis_map = AxisMap(am)
                self.axismap_list.append(axis_map)
                axis_name = axis_map.getName()
                self.axis_id_map[am.axis_index] = am.linear_index
                self.linear_id_map[am.linear_index] = am.axis_index

                if not axis_name:
                    # axis name is not reporting in via directinput
                    axis_name = f"{index}"
                else:
                    logical_count += 1

                # syslog.info(f"\tAxis [{am.linear_index}] -> {axis_name}")
                self.axis_names.append(axis_name)

            # auto disable invalid joystick devices that are not in spec
            self._hard_disabled = self.axis_count > 8 or self.button_count > 128 or self.hat_count > 4
            if self._hard_disabled:
                syslog.warning(f"JOY: auto disabling device [{self.name}] id [{self.device_id}]: out of spec")

            self._connected = True  # if dinput data is provided, the device is marked as connected

    def setAxisCallback(self, callback):
        """sets a custom axis callback to get an axis value (parameter is the axis number)"""
        self._get_axis_callback = callback

    def setButtonCallback(self, callback):
        """sets a custom button callback to get a button value (parameter is the button number)"""
        self._get_button_callback = callback

    def setHatCallback(self, callback):
        """sets a custom hat callback to get a hat value (parameter is the hat number)"""
        self._get_hat_callback = callback

    def get_button(self, button):
        """gets a button for this device"""
        if self._get_button_callback:
            return self._get_button_callback(button)
        if self.is_special:
            return False
        return DILL.get_button(self.device_guid, button)

    def get_axis(self, axis):
        """gets an axis for this device"""
        if self._get_axis_callback:
            return self._get_axis_callback(axis)
        return DILL.get_axis(self.device_guid, axis)

    def get_hat(self, hat):
        """gets a hat position for this device"""
        if self._get_hat_callback:
            return self._get_hat_callback(hat)
        return DILL.get_hat(self.device_guid, hat)

    def linear_index_from_assigned(self, index: int):
        """converts an assigned (display) axis index to the linear DINPUT axis"""
        assert index in self.axis_id_map, "invalid axis index"
        return self.axis_id_map[index]  # to linear

    def assigned_index_from_linear_(self, index: int):
        """converts from a linear DiNPUT axis to the display axis index"""
        assert index in self.linear_id_map, "invalid index"
        return self.linear_id_map[index]  # to axis

    def axis_sequence_to_input_id(self, index: int):
        """zero based index to input ID for axes
        :param index: zero based index to convert to an input ID
        """
        linear_id = index + 1 # linear is 1 based
        if self.is_virtual:
            # vjoy devices
            return linear_id
        if linear_id in self.linear_id_map:
            # mapped devices
            return self.linear_id_map[linear_id]


    @property
    def device_type(self):
        """device type"""
        return self._device_type

    @property
    def device_name(self) ->str:
        return self.name

    @device_type.setter
    def device_type(self, value):
        self._device_type = value

    @property
    def device_category(self):
        """device category"""
        return self._device_category

    @device_category.setter
    def device_category(self, value):
        self._device_category = value

    @property
    def is_special(self) -> bool:
        """true if the device is a special device"""
        return self._device_category in (DeviceCategory.Special, DeviceCategory.Config)

    @property
    def is_config(self) -> bool:
        """true if the device is a configuration device"""
        return self._device_category == DeviceCategory.Config

    @property
    def disabled(self) -> bool:
        """true if the device is disabled manually or excluded by GEX logic"""
        return self._hard_disabled or self._disabled

    @disabled.setter
    def disabled(self, value: bool):
        self._disabled = value

    @property
    def connected(self) -> bool:
        """true if the device is connected"""
        if self.is_special:
            # special devices are always connected
            return True
        return self._connected

    def setConnected(self, value: bool):
        self._connected = value

    @property
    def is_virtual(self):
        """determins if a device is virtual.

        Returns
        =======
        bool
            True if the device is a virtual vJoy device, False otherwise
        """
        if self._is_virtual is None:
            self._is_virtual = self.vendor_id in (VJOY_VID, GEX_VID)
        return self._is_virtual

    def set_vjoy_id(self, vjoy_id):
        """Sets the vJoy id for this device summary.

        Settings the vJoy device id is necessary, as DILL cannot know these
        ids, and as such this has to be entered when DirectInput devices and
        vJoy devices are linked.

        Parameters
        ==========
        vjoy_id : int
            Index of the vJoy device corresponding to this DirectInput device
        """
        assert self.is_virtual is True
        self.vjoy_id = vjoy_id
        self.name = f"VJoy {self.axis_count}/{self.button_count}/{self.hat_count} ({vjoy_id:d})"

    def get_axis_name(self, index : int, is_linear=False, short_name=False):
        """gets the axis name based on the input #


        """
        assert isinstance(index, int) and index > 0,f"invalid index: {index} - should be a 1 based integer"
        if is_linear:
            input_id = self.getAxisLinearId(index)
        else:
            input_id = index

        if not short_name:
            return f"Axis {self.getAxisName(input_id)}"

        match input_id:
            case 1:
                axis_name = "X"
            case 2:
                axis_name = "Y"
            case 3:
                axis_name = "Z"
            case 4:
                axis_name = "RX"
            case 5:
                axis_name = "RY"
            case 6:
                axis_name = "RZ"
            case 7:
                axis_name = "S1"
            case 8:
                axis_name = "S2"
            case _:
                axis_name = f"(unknown [{input_id}])"

        return axis_name

    def get_button_name(self, input_id):
        return f"Button {input_id}"

    def get_hat_name(self, input_id):
        import gremlin.util

        if isinstance(input_id, int):
            data = gremlin.util.hat_index_to_tuple(input_id)
        else:
            data = input_id  # tuple
        return gremlin.util.hat_tuple_to_direction(data)

    def axis_index_list(self) -> list:
        """returns the list of valid axis indices"""
        index_list = [data.axis_index for data in self.axismap_list if data.axis_index > 0]
        return index_list

    def getValidLinearIndices(self):
        """gets a list of valid linear axis indices for this device"""
        if self.axismap_list:
            return list(range(len(self.axismap_list)))
        return []

    def getAxisInputIdList(self):
        """gets the list of valid axis inputs"""
        return [input_id for input_id in self.axis_id_map]

    def getAxisInputId(self, linear_id: int, throw_on_missing = True):
        """Gets the input for the linear index
        :param index: 1 based linear index to get the mapped input ID for
        """
        assert linear_id > 0,"invalid linear id - must be 1 based"
        if linear_id in self.linear_id_map:
            return self.linear_id_map[linear_id]
        if throw_on_missing:
            raise ValueError(f"invalid linear axis id: {linear_id} for device {self.name}")
        return None

    def getAxisLinearId(self, axis_id: int):
        """gets the linear index for a given non linear axis id
         :param axis_id: axis id to get the linear index for"""
        assert axis_id > 0,"invalid axis id - must be 1 based"
        if axis_id in self.axis_id_map:
            return self.axis_id_map[axis_id]
        return None

    def update(self):
        """updates device connectivity"""
        if self.is_special:
            # nothing to update on special devices
            return

        # connection state
        if self.device_guid is not None:
            self._connected = DILL.device_exists(self.device_guid)
        else:
            self._connected = False

    def getAxisName(self, index: int, is_linear=False):
        """gets the name of the axis for a given axis index

        :param index: index
        :param is_linear: true if the index is the linear axis index (range 0 to axis_count), false if the axis identifier

        """
        assert isinstance(index, int) and index > 0,f"invalid index: {index} - should be a 1 based integer"
        try:
            am: AxisMap
            stub = ""
            if is_linear:
                if index in self.linear_id_map:
                    stub = f" L{index}"
                for am in self.axismap_list:
                    if am.linear_index == index:
                        return am.getName() + stub
            else:
                if self.connected:
                    if not self.axis_id_map or index not in self.axis_id_map:
                        return f"Axis[{index}]"
                    try:
                        if index in self.axis_id_map:
                            linear_id = self.axis_id_map[index]
                            stub = f" L{linear_id}"
                    except Exception:
                        return f"Axis [{index}]"

                    for am in self.axismap_list:
                        if not hasattr(am, "axis_index"):
                            syslog.error(f"Invalid data found for device : {self.name}")
                            syslog.error(f"axis map contains: {self.axismap_list}")
                            return None
                        if am.axis_index == index:
                            return am.getName() + stub
                else:
                    return f"(disc. device) axis {index}"
        except Exception as e:
            syslog.error(f"GET AXIS NAME: unable to get axis name for device : {self.name}")
            syslog.error(f"{str(e)}")
            syslog.error(f"{traceback.format_exc()}")

        return None

    def getAxisData(self):
        """gets the axis name pairs (input_id, axis_name, linear_index) for this device"""
        am: AxisMap
        pairs = []
        for am in self.axismap_list:
            pairs.append((am.axis_index, am.getName(), am.linear_index))
            pairs.sort(key=lambda x: x[2])  # sort by linear index
        return pairs

    def getValidAxisInputIds(self):
        """gets the list of valid axis input IDs for the given device"""
        return [am.axis_index for am in self.axismap_list if am.axis_index > 0]

    def __hash__(self):
        return hash((self.device_guid, self.axis_count, self.button_count, self.hat_count))

    @property
    def hashkey(self):
        """gets the hash key for virtual devices"""
        return (self.axis_count, self.button_count, self.hat_count)

    def __str__(self):
        vjoy_stub = f"VjoyID: {self.vjoy_id}" if self.vjoy_id != -1 else ""
        vendor_string = f"0x{self.vendor_id:x}" if self.vendor_id else "N/A"
        product_string = f"0x{self.product_id:x}" if self.product_id else "N/A"
        return f"Device: {self.name} {self.device_id} Type: [{self.device_type.name}]  Connected: {self.connected} Axis: {self.axis_count} Buttons: {self.button_count} Hats: {self.hat_count} Vendor: {vendor_string} Product: {product_string} Virtual: {self.is_virtual} {vjoy_stub}"


C_EVENT_CALLBACK = ctypes.CFUNCTYPE(None, _JoystickInputData)
C_DEVICE_CHANGE_CALLBACK = ctypes.CFUNCTYPE(None, _DeviceSummary, ctypes.c_uint8)


class DILL:
    """Exposes functions of the DILL library in an easy to use manner."""

    # Attempt to find the correct location of the dll for development
    # and installed use cases.
    _dll = None
    version = None

    # true if initialized

    initalized = False

    # Storage for the callback functions
    device_change_callback_fn = None
    input_event_callback_fn = None

    # Declare argument and return types for all the functions
    # exposed by the dll
    api_functions = {
        "init": {"arguments": [], "returns": None},
        "set_input_event_callback": {"arguments": [C_EVENT_CALLBACK], "returns": None},
        "set_device_change_callback": {
            "arguments": [C_DEVICE_CHANGE_CALLBACK],
            "returns": None,
        },
        "get_device_information_by_index": {
            "arguments": [ctypes.c_uint],
            "returns": _DeviceSummary,
        },
        "get_device_information_by_guid": {
            "arguments": [_GUID],
            "returns": _DeviceSummary,
        },
        "get_device_count": {"arguments": [], "returns": ctypes.c_uint},
        "device_exists": {"arguments": [_GUID], "returns": ctypes.c_bool},
        "get_axis": {"arguments": [_GUID, ctwt.DWORD], "returns": ctwt.LONG},
        "get_button": {"arguments": [_GUID, ctwt.DWORD], "returns": ctypes.c_bool},
        "get_hat": {"arguments": [_GUID, ctwt.DWORD], "returns": ctwt.LONG},
    }

    @staticmethod
    def init():
        """Initializes the DILL library.

        This has to be called before any other DILL interactions can take place.
        """
        from pathlib import Path
        from gremlin.util import display_error, get_dll_version

        syslog = logging.getLogger("system")

        if DILL._dll is None:
            dll_folder = os.path.dirname(__file__)
            dll_file = "dill.dll"
            _dll_path = os.path.join(dll_folder, dll_file)
            if not os.path.isfile(_dll_path):
                # look one level up for packaging in 3.12
                parent = Path(dll_folder).parent
                _dll_path = os.path.join(parent, dll_file)
                if not os.path.isfile(_dll_path):
                    msg = f"Unable to continue - missing dll: {_dll_path}"
                    display_error(msg)
                    syslog.critical(msg)
                    os._exit(1)
                dll_folder = parent

            # truncate the debug file (it gets large otherwise)

            # blits all files starting with dill_debug

            debug_file = "dill_debug.txt"
            debug_path = os.path.join(dll_folder, debug_file)

            # debug_files = [f for f in Path(dll_folder).glob("**/dill_debug*.txt")]
            # index = 1
            # for f in debug_files:
            #     try:
            #         os.unlink(f)
            #     except Exception:
            #         syslog.error(f"DILL: unable to truncate debug file: {f}")

            if os.path.isfile(debug_path):
                # blitz it
                try:
                    os.unlink(debug_path)
                except Exception:
                    syslog.error(f"DILL: unable to truncate debug file: {debug_path}")
                    exit(1)

                    # syslog.error(f"DILL: unable to truncate debug file: {debug_path}")
                    # while os.path.isfile(debug_path):
                    #     debug_path = f"dill_debug_{index}.txt"
                    #     index += 1

            dll_version = get_dll_version(_dll_path)
            DILL.version = dll_version

            try:
                _di_listener_dll = ctypes.cdll.LoadLibrary(_dll_path)

            except Exception as error:
                msg = f"Unable to load DirectInput interface dll: {_dll_path}\nThis could be due to UAC (try running in Administrator mode) or {error}"
                display_error(msg)
                syslog.critical(msg)
                os._exit(1)

            try:
                _di_listener_dll.get_device_information_by_index.argtypes = [ctypes.c_uint]
                _di_listener_dll.get_device_information_by_index.restype = _DeviceSummary
                DILL._dll = _di_listener_dll
                DILL._dll.init()
            except Exception as error:
                msg = f"Unable to initialize DirectInput: {_dll_path}\n{error}"
                display_error(msg)
                syslog.critical(msg)
                os._exit(1)

            DILL.initalized = True

    @staticmethod
    def reset():
        """force a DINPUT re-enumeration"""
        DILL.dumpDevices()

    @staticmethod
    def dumpDevices():
        """reload devices if count was 0"""
        syslog = logging.getLogger("system")
        device_count = DILL.get_device_count()
        syslog.info("DILL: device detection summary")
        for index in range(device_count):
            dev = DILL.get_device_information_by_index(index)
            syslog.info(f"\tIndex: [{index}] {str(dev)}")
        syslog.info("DILL: end device detection summary")

    @staticmethod
    def getDevices() -> list[DeviceSummary]:
        '''gets the maestro devices created by GEX'''
        device_list = []
        device_count = DILL.get_device_count()
        for index in range(device_count):
            dev = DILL.get_device_information_by_index(index)
            device_list.append(dev)
        return device_list

    @staticmethod
    def getMaestroDevices() -> list[DeviceSummary]:
        '''gets the maestro devices created by GEX'''
        device_list = []
        device_count = DILL.get_device_count()
        for index in range(device_count):
            dev = DILL.get_device_information_by_index(index)
            if dev.vendor_id == GEX_VID and GEX_PID_BASE <= dev.product_id < GEX_PID_BASE + GEX_MAX_DEVICES:
                device_list.append(dev)
        return device_list

    @staticmethod
    def getVjoyDeviceMap() -> dict:
        """does a re-read of vjoy devices from the DINPUT api
        returns a dictionary keyed by vjoyid holding the vjoy device detected
        """
        device_count = DILL.get_device_count()
        vjoy_map = {}
        for index in range(device_count):
            dev = DILL.get_device_information_by_index(index)
            if dev.is_virtual and dev.vjoy_id >= 0:
                vjoy_map[dev.vjoy_id] = dev

        return vjoy_map

    @staticmethod
    def set_input_event_callback(callback):
        """Sets the callback function to use for input events.

        The provided callback function will be executed whenever an event
        occurs by the DILL library providing and InputEvent object to said
        callback.

        Parameters
        ==========
        callback : callable
            Function to execute when an event occurs.
        """
        if callback is None:
            DILL.input_event_callback_fn = None
            DILL._dll.set_input_event_callback(C_EVENT_CALLBACK())
        else:
            DILL.input_event_callback_fn = C_EVENT_CALLBACK(callback)
            DILL._dll.set_input_event_callback(DILL.input_event_callback_fn)

    @staticmethod
    def set_device_change_callback(callback):
        """Sets the callback function to use for device change events.

        The provided function will be executed whenever the status of a
        device changes, providing a DeviceSummary object to the callback.

        Parameters
        ==========
        callback : callable
            Function to execute when an event occurs.
        """
        if callback is None:
            DILL.device_change_callback_fn = None
            DILL._dll.set_device_change_callback(C_DEVICE_CHANGE_CALLBACK())
        else:
            DILL.device_change_callback_fn = C_DEVICE_CHANGE_CALLBACK(callback)
            DILL._dll.set_device_change_callback(DILL.device_change_callback_fn)

    @staticmethod
    def get_device_count():
        """Returns the number of connected devices.

        Return
        ======
        int
            The number of devices connected.
        """
        return DILL._dll.get_device_count()

    @staticmethod
    def get_device_information_by_index(index):
        """Returns device information for the given index.

        Parameters
        ==========
        index : int
            The index of the device for which to return information.

        Return
        ======
        DeviceSummary
            Structure containing detailed information about the desired device.
        """
        return DeviceSummary(DILL._dll.get_device_information_by_index(index))

    @staticmethod
    def get_device_information_by_guid(guid):
        """Returns device information for the given GUID.

        Parameters
        ==========
        guid : GUID
            The GUID of the device for which to return information.

        Return
        ======
        DeviceSummary
            Structure containing detailed information about the desired device.
        """
        return DeviceSummary(DILL._dll.get_device_information_by_guid(guid.ctypes))

    @staticmethod
    def get_axis(guid, index):
        """Returns the state of the specified axis for a specific device.

        Parameters
        ==========
        guid : GUID
            GUID of the device of interest.
        index : int
            Index of the axis to return the value of.

        Return
        ======
        float
            Current value of the specific axis for the desired device.
        """

        return DILL._dll.get_axis(guid.ctypes, index)

    @staticmethod
    def get_button(guid, index):
        """Returns the state of the specified button for a specific device.

        Parameters
        ==========
        guid : GUID
            GUID of the device of interest.
        index : int
            Index of the button to return the value of.

        Return
        ======
        bool
            Current value of the specific button for the desired device.
        """
        return DILL._dll.get_button(guid.ctypes, index)

    @staticmethod
    def get_hat(guid, index):
        """Returns the state of the specified hat for a specific device.

        Parameters
        ==========
        guid : GUID
            GUID of the device of interest.
        index : int
            Index of the hat to return the value of.

        Return
        ======
        int
            Current value of the specific hat for the desired device.
        """
        return DILL._dll.get_hat(guid.ctypes, index)

    @staticmethod
    def get_device_name(guid):
        """Returns the name of the device specified by the provided GUID.

        Parameters
        ==========
        guid : GUID
            GUID of the device of which to return the name

        Return
        ======
        str
            Name of the specified device.
        """
        info = DeviceSummary(DILL._dll.get_device_information_by_guid(guid.ctypes))
        return info.name

    @staticmethod
    def device_exists(guid):
        """Returns whether or not a specific device is connected.

        Parameters
        ==========
        guid : GUID
            GUID of the device to check whether or not it is connected

        Return
        ======
        bool
            True if the device is connected, False otherwise.
        """
        return DILL._dll.device_exists(guid.ctypes)

    @staticmethod
    def initialize_capi():
        """Initializes the functions as class methods."""
        for fn_name, params in DILL.api_functions.items():
            dll_fn = getattr(DILL._dll, fn_name)
            if "arguments" in params:
                dll_fn.argtypes = params["arguments"]
            if "returns" in params:
                dll_fn.restype = params["returns"]
