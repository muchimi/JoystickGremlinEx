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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.	If not, see <http://www.gnu.org/licenses/>.


from __future__ import annotations  # deprecated with python 3.14+


import dinput

import gremlin.util

import gremlin.singleton_decorator


from psygnal import Signal


from gremlin.types import TabDeviceType


class TabData:
    """holds tab information for a given device tab"""

    filteredChanged = Signal(bool)  # fires when the filtered property changes
    lockedChanged = Signal(bool)  # fires when the lock property changes

    def __init__(
        self,
        position: int,
        tab_type: TabDeviceType,
        device: dinput.DeviceSummary,
        filtered=False,
        dirty=True,
        locked=False,
    ):
        assert position >= 0, "invalid position"
        assert isinstance(device, dinput.DeviceSummary), "Invalid device"
        self._tab_type = tab_type
        self._device = device
        self._position = position

        self._filtered = filtered  # true if inputs are filtered by used inputs only
        self._dirty = dirty  # true if the tab is dirty and needs to be reloaded
        self._locked = locked
        self._populate_enabled = False  # true if the UI can be populated for this tab

    @property
    def position(self) -> int:
        return self._position

    def setPosition(self, value : int):
        self._position = value


    @property
    def device_guid(self) -> dinput.GUID:
        """gets the associated device GUID"""
        return self._device.device_guid

    @property
    def device_id(self) -> str:
        """gets the associated device GUID as a string"""
        return self.device_id

    @property
    def device_name(self) -> str:
        """gets the associated device name"""
        return self._device.name

    @property
    def tab_type(self) -> TabDeviceType:
        return self._tab_type

    @property
    def device(self) -> dinput.DeviceSummary:
        """device data"""
        return self._device

    @property
    def filtered(self) -> bool:
        return self._filtered

    @filtered.setter
    def filtered(self, value: bool):
        if value != self._included:
            self._filtered = value
            self.filteredChanged.emit(value)

    @property
    def dirty(self) -> bool:
        return self._dirty

    @dirty.setter
    def dirty(self, value: bool):
        self._dirty = value

    @property
    def locked(self) -> bool:
        return self._locked

    @locked.setter
    def locked(self, value: bool):
        if value != self._locked:
            self._locked = value
            self.lockedChanged.emit(value)

    @property
    def populateEnabled(self) -> bool:
        return self._populate_enabled

    @populateEnabled.setter
    def populateEnabled(self, value: bool):
        self._populate_enabled = value


@gremlin.singleton_decorator.SingletonDecorator
class TabState:
    """holds tab state data for all tabs"""

    def __init__(self):
        self._tab_map = {}
        import gremlin.event_handler

        el = gremlin.event_handler.EventListener()
        el.profile_unload.connect(self.reset)

    def reset(self):
        """resets the data"""
        self._tab_map.clear()

    def getTabIndex(self, device_guid) -> int:
        """gets the tab index for a specific tab, -1 if not found"""
        device_guid = gremlin.util.to_guid(device_guid)
        if device_guid in self._tab_map:
            return self._tab_map[device_guid].position
        return -1  # not found

    def setPosition(self, device_guid, position):
        """changes the position of the given device GUID"""
        device_guid = gremlin.util.to_guid(device_guid)
        if device_guid in self._tab_map:
            self._tab_map[device_guid].position = position

    def getData(self, device_guid) -> TabData:
        device_guid = gremlin.util.to_guid(device_guid)
        if device_guid in self._tab_map:
            return self._tab_map[device_guid]

        return None

    def addData(
        self,
        position: int,
        tab_type: TabDeviceType,
        device: dinput.DeviceSummary,
        filtered: bool = False,
        locked: bool = False,
    ):
        """adds a data block for tab
        :param position: the as built tab index
        :param tab_type: the type of the tab
        :param device: the device associated with the tab
        :param included: optional flag to track tab filtered status (on means not displayed)
        :parm locked: optionaal falg to track tab locking status
        """
        assert isinstance(device, dinput.DeviceSummary), "invalid device"
        device_guid = gremlin.util.to_guid(device.device_guid)
        if device_guid not in self._tab_map:
            data = TabData(
                position=position,
                tab_type=tab_type,
                device=device,
                filtered=filtered,
                locked=locked,
            )
            self._tab_map[device_guid] = data

        return self._tab_map[device_guid]
