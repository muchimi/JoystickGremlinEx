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

from __future__ import annotations
from abc import abstractmethod, ABCMeta
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import QThread
from lxml import etree
import os
import uuid
import time
import lxml.etree
import traceback
import collections
from typing import Callable
import html
import gremlin
import gremlin.config
import gremlin.event_handler
import gremlin.singleton_decorator


import gremlin.config
import gremlin.event_handler
import gremlin.shared_state
import gremlin.ui.axis_calibration
import gremlin.ui.ui_common
import gremlin.base_profile
import gremlin.input_item
import gremlin.base_buttons
import gremlin.worker
from dinput import DeviceSummary
from gremlin.util import (
    load_icon,
    load_pixmap,
    get_guid,
    safe_format,
    safe_read,
    read_bool,
    write_guid,
    read_guid,
    parse_bool,
    parse_guid,
)
import gremlin.util
from gremlin.input_types import InputType
from gremlin.base_buttons import *  # noqa: F403
from gremlin.types import DeviceType
import gremlin.plugin_manager
import gremlin.ui.ui_common as ui_common
from gremlin.clipboard import Clipboard, ObjectEncoder, EncoderType
import logging
from shiboken6 import Shiboken
from psygnal import Signal
import gremlin.hints
import gremlin.types
from gremlin.types import SendType, ActivationRule, ContainerViewTypes, Interactions

from gremlin.base_classes import AbstractInputItem, BaseProfileData
from gremlin.plugin_manager import ActionPlugins, ContainerPlugins


from gremlin.singleton_decorator import SingletonDecorator
from gremlin.base_classes import AbstractCallbackModel, _get_input_item, _is_curve_tag
import dinput

from gremlin.ui import virtual_button
import gremlin.error
from gremlin.worker import WorkManager


syslog = logging.getLogger("system")


CallbackData = collections.namedtuple("ContainerCallback", ["callback", "event"])


class InputIdentifier(QtCore.QObject):
    """Represents the identifier of a single input item."""

    def __init__(
        self,
        input_type,
        device_guid,
        input_id,
        device_type,
        input_name,
        is_axis=False,
        is_button=False,
        input_item: InputItem = None,  # noqa: F405
    ):
        """Creates a new instance.

        :param input_type: the type of input
        :param input_id: the identifier of the input
        :param device_type: the type of device this input belongs to
        :param input_name: the name to display
        :param is_axis: true if the input is an axis behavior
        :param is_button: true if the input is a button behavior
        """
        super().__init__()
        self._input_type = input_type
        self._device_guid = device_guid
        self._input_id = input_id
        self._device_type = device_type
        self._input_guid = get_guid()  # unique internal GUID for this entry
        self._input_name = input_name
        self._is_axis = is_axis
        self._input_item = input_item

    @property
    def input_item(self):
        return self._input_item

    @property
    def device_guid(self):
        return self._device_guid

    @property
    def device_type(self):
        return self._device_type

    @property
    def input_type(self):
        return self._input_type

    @property
    def input_id(self):
        return self._input_id

    @input_id.setter
    def input_id(self, value):
        if value == gremlin.ui.mode_device.ModeInputItemType.ModeProfileStart:
            pass
        if self._input_id_callback is not None:
            raise ValueError("cannot set input id in callback mode")
        self._input_id = value

    @property
    def input_name(self) -> str:
        return self._input_name

    @input_name.setter
    def input_name(self, value: str):
        self._input_name = value

    @property
    def guid(self):
        return self._input_guid

    @property
    def is_axis(self) -> bool:
        """true if this item is setup as an axis input (linear)"""
        if self._input_id and hasattr(self._input_id, "is_axis"):
            return self._input_id.is_axis
        return self._is_axis

    @property
    def is_button(self) -> bool:
        """true if this item is setup as an button input (momentary)"""
        return not self.is_axis

    @property
    def is_valid(self) -> bool:
        if hasattr(self._input_id, "is_valid"):
            return self._input_id.is_valid
        return True

    @property
    def is_status(self) -> bool:
        if hasattr(self._input_id, "is_status"):
            return self._input_id.is_status
        return True

    @property
    def is_hat(self) -> bool:
        """true if the item is a hat"""
        return self._input_type == InputType.JoystickHat

    def getInputItem(self):
        """gets the input item for this identifier"""
        profile = gremlin.shared_state.current_profile
        if self._device_type == DeviceType.State:
            mode = gremlin.shared_state.master_mode
            device_guid = gremlin.shared_state.state_tab_guid
        else:
            mode = gremlin.shared_state.edit_mode
            device_guid = self._device_guid

        if device_guid in profile.devices:
            if mode in profile.devices[device_guid].modes:
                if self._input_type in profile.devices[device_guid].modes[mode].config:
                    input_items = profile.devices[device_guid].modes[mode].config[self._input_type]
                    if self._input_id in input_items:
                        input_item = input_items[self._input_id]
                        return input_item

        return None  # not found


def getInputIdKey(input_id):
    """gets an input id key from a given input id"""
    if input_id is not None and hasattr(input_id, "message_key"):
        return input_id.message_key if input_id.message_key is not None else input_id.guid
    return input_id


class AbstractView(QtWidgets.QWidget):
    """
    base view for widget list type objects that show one or more content items.
    hooks the model when the model changes to trigger redraw updates as needed.

    """

    # Signal emitted when a entry is selected
    item_selected = QtCore.Signal(int, bool)  # index of the item being selected and selection flag
    item_edit = QtCore.Signal(object, int, object)  # widget, index, model data object
    item_edit_curve = QtCore.Signal(object, int, object)  # widget, index , model data object
    item_delete_curve = QtCore.Signal(object, int, object)  # widget, index , model data object
    item_closed = QtCore.Signal(object, int, object)  # widget, index, model data object

    def __init__(
        self,
        model: AbstractCallbackModel = None,
        callback: Callable = None,
        parent=None,
    ):
        """Creates a new view instance.
        :param model: the model to visualize
        :param callback: an optional callback called when the model changes - this is used by the container to trigger updates when the model changes subject to begin/end model change calls - more can be added with addCallback()
        :param interaction_callback: an optional callback called when the view is interacted with (such as an action moving up or down)
        :param parent: the parent of this view widget
        """
        super().__init__(parent)
        self._id = gremlin.util.get_uuid()
        assert isinstance(model, AbstractCallbackModel), "invalid model"
        self._model = model
        self._model.addCallback(self._handle_model_changed)  # hook changes to the model when the model changes

        self._redraw_suspended_stack = 0  # non 0 = redraw is suspended
        self._redraw_pending = True  # true if a redraw is pending while redraw is disabled - set to True initially to indicate a redraw is needed

        self._container = None
        if __debug__:
            if callback is not None and not callable(callback):
                raise TypeError("Callback must be callable")
        self._model_change_callbacks: list[Callable] = []
        if callback is not None:
            self._model_change_callbacks.append(callback)

        self._model_call_stack = 0  # stack to manage when the model change event is fired

    def addSelectionChangeCallback(self, callback: Callable):
        """adds a callback to be called when the model changes - this is used by the container
        :param callback: the callback to add
        """
        if __debug__ and callback is not None and not callable(callback):
            raise TypeError("Callback must be callable")
        if callback not in self._model_change_callbacks:
            self._model_change_callbacks.append(callback)

    def removeSelectionChangeCallback(self, callback: Callable):
        """removes a callback from the list of callbacks to be called when the model changes - this is used by the container
        :param callback: the callback to remove
        """
        if callback in self._model_change_callbacks:
            self._model_change_callbacks.remove(callback)

    def refreshModel(self, force=False):
        """forces a refresh of the view by refreshing a model if it changed"""
        self._model.refresh(force)  # triggers an update if the model was changed

    def pushSuspended(self):
        """disable redraw on model change"""
        self._redraw_suspended_stack += 1

    def popSuspended(self, reset=False, emit=True):
        """enable redraw on model change"""
        if reset:
            self._redraw_suspended_stack = 0
        if self._redraw_suspended_stack > 0:
            self._redraw_suspended_stack -= 1
        if emit and self._redraw_suspended_stack == 0 and self._redraw_pending:
            self._handle_model_changed()

    def _handle_model_changed(self, data=None, force=False):
        """Handles changes in the model."""

        if not Shiboken.isValid(self):
            # widget was destroyed - self unhook
            self._model_change_callbacks.clear()
            self._model.removeCallback(self._handle_model_changed)
            return

        if force or (self._model_call_stack == 0 and (self._model.modelChanged() or self._redraw_pending)):
            if self._redraw_suspended_stack > 0:
                # redraw call is suspended - place it in pending status
                self._redraw_pending = True
                return

            # notify the callbacks if any
            for callback in self._model_change_callbacks:
                callback()

            if gremlin.shared_state.is_redraw_suspended():
                # no redraw allowed currently
                self._redraw_pending = True
                return

            self.redraw()

    def beginModelChange(self):
        """call this before making a change to the model to prevent multiple change events from firing"""
        self._model_call_stack += 1

    def endModelChange(self, reset: bool = False):
        """call this after making a change to the model to trigger the change event if needed"""
        if reset:
            self._model_call_stack = 0

        if self._model_call_stack > 0:
            self._model_call_stack -= 1

        if self._model_call_stack == 0 and self._model_changed:
            self._handle_model_changed()

    @property
    def id(self):
        return self._id

    @property
    def model(self):
        return self._model

    @model.setter
    def model(self, model: AbstractCallbackModel):
        if model != self._model:
            self.setModel(model)

    def setModel(self, model: AbstractCallbackModel):
        """Sets the model to display with this view.

        :param model the model to visualize
        """
        if self._model:
            # ensure the callback is registered so when the model changes, the list view updates
            self._model.addCallback(self._handle_model_changed)
        if self._model != model:
            if self._model:
                self._model.removeCallback(self._handle_model_changed)
            assert isinstance(model, AbstractCallbackModel) if model is not None else True, "invalid model"
            self._model = model

    def modelChanged(self) -> bool:
        """true if the unrerlying model has changed - used in the context of begin/end to detect model changes if a redraw was suspended"""
        return self.model.modelChanged()

    def _select_item_ui(self, index):
        """Selects the item at the provided index

        :param index the index of the item to select
        """
        assert False, "select method not implemented in view subclass"

    def redraw(self, force: bool = False):
        """Redraws the view."""
        assert False, "Redraw method not implemented in view subclass"

    def __hash__(self):
        return hash(self._id)


class InputItem(gremlin.base_classes.AbstractInputItem):
    """Represents a single input item such as a button or axis, containers and parameters/options associated with that input mapping"""

    lockedChanged = Signal(object)  # (input_item) fires when the lock state changes - passes the input item as the parameter
    tooltipChanged = QtCore.Signal()  # fires when the tooltip changes

    def __init__(
        self,
        mode_node: str | gremlin.base_profile.ProfileModeNode,  # profile mode object (required)
        input_type: InputType,  # must be provided
        input_id=None,
        custom_name_handler: Callable = None,
        custom_mode_name_handler: Callable = None,
        custom_input_id_handler: Callable = None,
        override_input_type=None,
        device_guid: dinput.GUID | uuid.UUID | str = None,  # noqa: F405,
        description: str = None,
        description_readonly: bool = None,
        tooltip: str = None,
    ):
        """Creates a new InputItem instance.
        :param mode_node: profile mode node
        :param input_type : input type of the input item (do not use this if the input item has a callback to get that value)
        :param input_id : input id of the input item
        :param custom_name_handler: handler() returns a string, whenever the input name is needed
        :param custom_mode_name_handler: handler() returns a string, optional, to override the default mode for special inputs that use special modes
        :param custom_input_id_handler: handler() returns the input id, optional, to override the default input id handling
        :param description: optional description text
        :param description_readonly: optional flag to indicate if the description of the input can be user edited
        :param tooltip: optional tooltip text

        """
        import gremlin.base_profile
        import gremlin.shared_state
        import gremlin.joystick_handling

        assert isinstance(mode_node, str) or isinstance(mode_node, gremlin.base_profile.ProfileModeNode), (
            "Parent parameter must be a string or mode object, cannot be NULL"
        )
        if isinstance(mode_node, str):
            # convert to a mode object
            profile = gremlin.shared_state.current_profile
            assert device_guid is not None, "device_guid must be provided if mode provided as a name"
            mode_node = profile.getModeNode(device_guid, mode_node)

        if not device_guid:
            # grab the device from the mode object
            device_guid = mode_node.parent.device_guid

        assert device_guid is not None, "invalid device guid provided"

        assert input_type is not None, "input type must be provided"

        import gremlin.joystick_handling

        super().__init__(mode_node.name, None)

        # if input_type == InputType.ModeControl:
        #     syslog.info(f"create input item id: [{self.id}]")
        #     pass

        self.parent = mode_node  # mode object

        self._input_item_generating_xml = False  # xml nesting level
        self._override_input_type = override_input_type  # override input type for some types that are different

        self._input_type = input_type
        self._custom_input_id_handler = custom_input_id_handler  # custom handler for input id
        if self._custom_input_id_handler is not None and input_id is not None:
            raise ValueError("input_id should not be provided when a custom input id handler is set")
        self.setInputId(input_id)

        device = gremlin.joystick_handling.getDevice(device_guid)
        self._device_guid = device.device_guid if device else None  # hardware input ID
        self._device_id = device.device_id if device else None  # hardware input ID as a string
        self._device_name = device.name if device else f"Unknownd device: [{device_guid}]"
        self._device_type = device.device_type if device else DeviceType.NotSet

        self._name = None  # device name
        self._input_name = None  # input name of the hardware (axis name if an axis)
        if custom_name_handler is not None:
            assert callable(custom_name_handler), "Name handler must be callable "
        self._input_name_handler = custom_name_handler  # custom handler
        self.always_execute = False
        self._description = ""
        self._description_readonly = False  # true if description is read/only (cannot be changed)
        if custom_mode_name_handler is not None:
            assert callable(custom_mode_name_handler), "Mode name handler must be callable "
        self._profile_mode_callback = custom_mode_name_handler  # special callback to use to get the profile mode for this item (if special)
        self._containers = ContainerModel(self)  # holds the containers for this input
        # self._containers.addCallback(self._handle_containers_changed)  # called when containers are changed
        self._selected = False  # true if the item is selected
        self._is_action = False  # true if the object is a sub-item for a sub-action (GateHandler for example)



        self._is_axis = False  # true if the item is an axis input
        self._is_button = False  # true if the item is a button input
        self._calibration = None  # calibration data if the item is an input axis
        self._curve_data = None  # true if the item has its input curved
        self._locked = False  # true if the input is locked (cannot make mapping changes)

        self.mapping_widget_id = None  # ID of the mapping widget for this input

        self._input_widget = None  # reference to the input widget for this input
        self._mapping_widget = None  # reference to the mapping widget for this input

        self._tooltip = tooltip
        if description is not None:
            self._description = description
        if description_readonly is not None:
            self._description_readonly = description_readonly

        # self._profile_mode = None
        self._enabled = True  # enabled flag
        if mode_node is not None:
            # find the missing properties from the parenting hierarchy
            item = mode_node
            while True:
                # if isinstance(item, Mode):
                #    self._profile_mode = item.name
                if isinstance(item, gremlin.base_profile.ProfileDeviceNode):
                    self._device_type = item.type
                    self._device_name = item.name
                    self._device_guid = gremlin.util.to_guid(item.device_guid)
                    self._device_id = item.device_id
                if not hasattr(item, "parent"):
                    break
                item = item.parent

        self._message_key = None  # message key for this input (device_guid, input_type, input_id)

        self._custom_sort_callback = None

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._profile_start)
        el.reload_axis_state.connect(self._handle_axis_state_request)

    @property
    def input_id(self) -> int:
        """returns the input id for this input item"""
        if self._custom_input_id_handler is not None:
            return self._custom_input_id_handler()
        return self._input_id

    @input_id.setter
    def input_id(self, value: int):
        """sets the input id for this input item"""
        if self._custom_input_id_handler is not None:
            raise AttributeError("Cannot set input_id when a custom input id handler is set")
        self._input_id = value

    def getCurrentMode(self) -> str:
        """gets the current profile mode for this input item"""
        return gremlin.shared_state.current_mode if self._profile_mode_callback is None else self._profile_mode_callback()

    def setInputWidget(self, widget: InputItemWidget):
        self._input_widget = widget

    def getInputWidget(self) -> InputItemWidget:
        return self._input_widget

    def setMappingWidget(self, widget: InputItemMappingWidget):
        self._mapping_widget = widget

    def getMappingWidget(self) -> InputItemMappingWidget:
        return self._mapping_widget

    def setTooltip(self, tooltip: str):
        if tooltip != self._tooltip:
            self._tooltip = tooltip
            self.tooltipChanged.emit()

    @property
    def tooltip(self) -> str:
        """tooltip"""
        return self._tooltip

    def setContainers(self, containers: containerModel):
        """sets the container model for this input item"""
        self._containers = containers

    def setSortCallback(self, callback: Callable):
        """sets an optional callback to get the sort key for this item"""
        assert isinstance(callback, Callable) if callback is not None else True, "invalid callback"
        self._custom_sort_callback = callback

    def setInputNameHandler(self, callback: Callable):
        """sets the input name handler (optional)"""
        if callback is not None:
            assert callable(callback), "Callback must be a callable method"
        self._input_name_handler = callback

    def setProfileModeHandler(self, callback: Callable):
        if callback is not None:
            assert callable(callback), "Callback must be a callable method"
        self._profile_mode_callback = callback

    @property
    def containerModel(self) -> ContainerModel:  # noqa: F405
        """the container data for this input"""
        return self.containers

    @property
    def is_action(self) -> bool:
        return self._is_action

    @is_action.setter
    def is_action(self, value: bool):
        self._is_action = value

    def _handle_axis_state_request(self):
        """request to reload axis state with this input item"""
        if self._is_axis:
            astate = gremlin.event_handler.AxisState()
            astate.registerAxisInputItem(self)

    def toExtraData(self, extra_data=None) -> dict:
        """creates or adds properties of the input to create an extra data item"""
        if extra_data is None:
            extra_data = {}

        extra_data["device_guid"] = self.device_guid
        extra_data["device_type"] = self.device_type
        extra_data["input_id"] = self.input_id
        extra_data["mode"] = self.profile_mode

        return extra_data

    def setProfileModeCallback(self, callback):
        """sets an override callback to change profile mode return value for special cases"""
        self._profile_mode_callback = callback

    @property
    def profile_mode(self) -> str:
        """gets the mode object"""
        return self.parent.name

    @property
    def locked(self) -> bool:
        return self._locked

    @locked.setter
    def locked(self, value: bool):

        if self._locked != value:
            # changed in m76T102 by request - allow locking of any input regardless of mapping
            #     if value and not self.containers:
            #         return # cannot lock an input that has no mappings
            self._locked = value
            self.lockedChanged.emit(self)

    @property
    def message_key(self):
        """unique key for this input item, can be overriden in derived classes"""
        # joystick inputs only - returns id of axis or button
        # if self._input_id is not None and hasattr(self._input_id, "message_key"):
        #     return self._input_id.message_key
        if self._message_key:
            return self._message_key
        return self._input_id

    def callbackKey(self):
        """callback key unique to the input type, input id"""
        return (self._device_guid, self._input_type, self._input_id)

    @property
    def sortKey(self):
        """gets the sorting key for the particular input"""
        if self._custom_sort_callback:
            return self._custom_sort_callback(self)
        else:
            match self.input_type:
                case InputType.JoystickAxis:
                    key = (1, self.input_id)
                case InputType.JoystickButton:
                    key = (2, self.input_id)
                case InputType.JoystickHat:
                    key = (3, self.input_id)
                # case InputType.OpenSoundControl:
                #     key = (4, self.input_id)
                # case InputType.ModeControl:
                #     key = (5, self.input_id)
                # case InputType.State:
                #     key = (6, self.input_id)
                # case InputType.Key:
                #     key = (7, self.input_id)
                case _:
                    key = (10, self.message_key)
        return key

    @property
    def hasActions(self) -> bool:
        """true if the input item has at least one action"""
        for container in self.containers:
            for action_set in container.action_sets:
                if action_set:
                    return True
        return False

    @property
    def hasContainers(self) -> bool:
        """true if the input item has at least one container"""
        return len(self._containers) > 0

    @property
    def hasCalibration(self):
        """for axis input devices, returns True if the device has an active calibration"""
        if not self._calibration:
            import gremlin.ui.axis_calibration

            cm = gremlin.ui.axis_calibration.CalibrationManager()
            calibration = cm.getCalibration(self._device_guid, self._input_id)
            self._calibration = calibration

        return self._calibration is not None and self._calibration.hasData

    @property
    def calibration(self):
        """for axis input devices, returns the calibration data"""
        return self._calibration

    @QtCore.Slot()
    def _refresh_icons(self):
        """called when the UI wants to refresh input icons"""

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
        """true if description is readonly"""
        return self._description_readonly

    @descriptionReadOnly.setter
    def descriptionReadOnly(self, value: bool):
        self._description_readonly = value

    @property
    def input_name(self) -> str:
        """input name as computed based on device, type and input id"""
        if self._input_name_handler is not None:
            return self._input_name_handler(self)
        return self._input_name

    @property
    def selected(self) -> bool:
        """true if the item is selected"""
        return self._selected

    @selected.setter
    def selected(self, value: bool):
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
        """true if the item is action"""
        return self._is_action

    @is_action.setter
    def is_action(self, value: bool):
        self._is_action = value

    @property
    def is_axis(self) -> bool:
        """true if this item is setup as an axis input (linear)"""
        if self._input_id and hasattr(self._input_id, "is_axis"):
            return self._input_id.is_axis
        return self._is_axis or self._input_type == InputType.JoystickAxis

    @is_axis.setter
    def is_axis(self, value: bool):
        self._is_axis = value

    @property
    def is_button(self) -> bool:
        """true if this item is setup as an axis input (momentary)"""
        return not self.is_axis

    # def _handle_containers_changed(self):
    #     """tells the UI about the container change"""
    #     el = gremlin.event_handler.EventListener()
    #     el.mapping_changed.emit(self)

    def remove_container(self, container):

        if container not in self._containers:
            id = container.id
            for c in self._containers:
                if c.id == id:
                    self._containers.remove(c)
                    break
            return

        # notify every action in the container it's being removed in case some update needs to happen
        for action_set in container.action_sets:
            for action in action_set:
                if hasattr(action, "actionDeleted"):
                    action.actionDeleted()

        self._containers.remove(container)

        # tell the UI about the change
        el = gremlin.event_handler.EventListener()
        # el.mapping_changed.emit(self)

        if not len(self._containers):
            # only fire the update is the container list is empty
            el.input_used_changed.emit(self._device_guid, self._input_type, self._input_id, False)

    def get_containers(self):
        return self._containers

    @property
    def containers(self) -> ContainerModel:  # noqa: F405
        """containers defined for this input"""
        return self._containers

    @gremlin.base_classes.AbstractInputItem.input_type.setter
    def input_type(self, input_type: InputType):
        # override mode/state inputs for legacy profiles
        assert input_type is not None, "Invalid input type"
        if self._device_type == DeviceType.ModeControl:
            input_type = InputType.ModeControl
        elif self._device_type == DeviceType.State:
            input_type = InputType.State
        elif self._device_type == DeviceType.Osc:
            input_type = InputType.OpenSoundControl
        elif self._device_type == DeviceType.Midi:
            input_type = InputType.Midi
        elif self._device_type == DeviceType.State:
            input_type = InputType.State
        elif self._device_type == DeviceType.Keyboard:
            input_type = InputType.KeyboardLatched

        self._input_type = input_type
        self._update_input()

    def getInputType(self):
        """gets the input type or the override input type"""
        if hasattr(self._input_id, "getOverrideInputType"):
            override_input_type = self._input_id.getOverrideInputType()
        else:
            override_input_type = self.getOverrideInputType()
        return override_input_type

    def getRawInputType(self):
        """gets the input type or the override input type"""
        return self.input_type

    def setOverrideInputType(self, input_type):
        """sets the override input type"""
        self._override_input_type = input_type
        self._update_input()

    def getOverrideInputType(self):
        """gets the override input type - which defaults to the regular input type if no override is set"""
        if self._override_input_type:
            return self._override_input_type
        return self._input_type

    @property
    def device_guid(self):
        return self._device_guid

    @device_guid.setter
    def device_guid(self, value: dinput.GUID | uuid.UUID | str = None):  # noqa: F405
        if gremlin.util.compare_guid(self._device_guid, value):
            device = gremlin.joystick_handling.getDevice(value)
            assert device is not None, f"device not found for device GUID: [{value}]"
            self._device_guid = device.device_guid  # hardware input ID
            self._device_id = device.device_id  # hardware input ID as a string
            self._device_name = device.name
            self._device_type = device.device_type
            self._update_input()

    @property
    def device_id(self):
        return self._device_id

    @property
    def device_type(self):
        return self._device_type

    @property
    def device_name(self):
        return self._device_name

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value

    @property
    def curve_data(self) -> gremlin.curve_handler.AxisCurveData:
        """axis curve data"""
        return self._curve_data

    @curve_data.setter
    def curve_data(self, value: gremlin.curve_handler.AxisCurveData):
        """axis curve data"""
        self._curve_data = value
        self._update_input()

    @property
    def is_curve(self) -> bool:
        """true if the input is curved"""
        return self._curve_data is not None

    def hasAction(self, action_name: str) -> bool:
        """true if the specified action type is found in the containers"""
        plugins = ActionPlugins()
        action_type = plugins.get_class(action_name)
        if action_type is not None:
            container: AbstractContainer
            for container in self._containers:
                for action_set in container.action_sets:
                    action: gremlin.base_profile.AbstractAction
                    if action_set:
                        for action in action_set:
                            if isinstance(action, action_type):
                                return True
        return False

    def hasConditions(self):
        """true if the input item has conditions defined"""
        tracker = ConditionTracker()
        count = tracker.getInputItemConditionCount(self, self.profile_mode)  # gremlin.shared_state.current_mode)
        return count > 0

    def getConditions(self):
        """gets a list of conditions for this input"""
        tracker = ConditionTracker()
        return tracker.getInputItemConditions(self, self.profile_mode)  # gremlin.shared_state.current_mode)

    def get_valid_container_list(self):
        """Returns a list of valid containers for this input"""
        container_list = []
        for entry in gremlin.plugin_manager.ContainerPlugins().repository.values():
            input_type = self.input_type
            override_type = self.getOverrideInputType()
            if not entry.input_types or input_type in entry.input_types or override_type in entry.input_types:
                # if no input types provided, all are ok
                if entry.axis_only:
                    # container requires an axis
                    if not self.is_axis:
                        continue
                container_list.append(entry.name)
        return sorted(container_list)

    def _update_input(self):
        """updates input name and registers an axis input if needed"""
        from gremlin.keyboard import key_from_code

        input_id = self._input_id
        if input_id is not None and self._device_guid is not None:
            if isinstance(input_id, int):
                if self._input_type == InputType.JoystickAxis:
                    self.is_axis = True  # indicate we are an axis
                    self._is_button = False

                    # update the registration in case the input type changed
                    sdata = gremlin.event_handler.AxisState()
                    sdata.registerAxisInputItem(self)

                    info = gremlin.joystick_handling.getDevice(self._device_guid)
                    if info:
                        self._input_name = info.get_axis_name(input_id)
                    else:
                        self._input_name = f"Axis {input_id}"

                    el = gremlin.event_handler.EventListener()
                    el.update_input_icons.emit()
                elif self._input_type == InputType.JoystickButton:
                    self.is_axis = False
                    self._input_name = f"Button {input_id}"
                    self._is_button = True
                elif self._input_type == InputType.JoystickHat:
                    self.is_axis = False
                    self._input_name = f"Hat {input_id}"
                    self._is_button = True

            elif self._input_type in (InputType.Keyboard, InputType.KeyboardLatched):
                if isinstance(input_id, gremlin.keyboard.Key):
                    self._input_name = key_from_code(input_id.scan_code, input_id.is_extended).name
                elif isinstance(input_id, gremlin.ui.keyboard_device.KeyboardInputItem):
                    self._input_name = input_id.display_name
                else:
                    try:
                        self._input_name = key_from_code(input_id[0], input_id[1]).name
                    except Exception as err:
                        msg = f"Unable to parse type: {type(input_id).__name__}"
                        self._input_name(msg)
                        syslog.error(f"Unable to parse: {msg}")
                        syslog.error(f"{err}\n{traceback.format_exc()}")
            elif self._input_type == InputType.ModeControl:
                self._input_name = f"Mode [{gremlin.shared_state.edit_mode}] {'enter' if self._input_id == 0 else 'exit'} actions"
            elif self._input_type == InputType.OpenSoundControl:
                self._is_axis = self.input_id.is_axis
                self._is_button = self.input_id.is_button
            elif self._input_type == InputType.OctaviIfr1:
                self._is_axis = False
                self._is_button = True

            else:
                self._input_name = f"{InputType.to_string(self._input_type).capitalize()} {input_id}"

    def from_xml(self, node, data, extra_data: dict = None, skip_root=False):
        """Parses an InputItem node.

        :param node: xml element node to parse
        :param data: data object (context sensitive)
        :param extra_data: map object (context sensitive)
        :param skip_root: true if the child node should be processed only for containers (subclass dependent)
        """

        # assert data is not None, "InputItem must be provided"
        import gremlin.ui.octavi_device

        container_plugins = ContainerPlugins()
        container_tag_map = container_plugins.tag_map
        if extra_data and "input_type" in extra_data:
            self.input_type = extra_data["input_type"]
        else:
            try:
                self.input_type = InputType.to_enum(node.tag)
            except Exception:
                syslog.error(f"XML: unknown input type: [{node.tag}]")

        if not skip_root:  # skip header processing if set
            self._description = html.unescape(safe_read(node, "description", str, ""))
            self.always_execute = read_bool(node, "always-execute", False)

            if "locked" in node.attrib:
                self._locked = safe_read(node, "locked", bool, False)
            else:
                self._locked = False

            if self.input_type == InputType.JoystickAxis:
                # check for curve data
                for child in node:
                    if _is_curve_tag(child.tag):
                        self.curve_data = gremlin.curve_handler.AxisCurveData()
                        self.curve_data._parse_xml(child)
                        self.input_id = safe_read(node, "input_id", int, 0)
                        self.curve_data.calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(self.device_guid, self.input_id)
                        break
                if "id" in node.attrib:
                    str_id = node.get("id")
                    if not str_id.isnumeric():
                        self.input_id = gremlin.base_classes.SpecialInputItem(str_id)
                    else:
                        self.input_id = safe_read(node, "id", int, 0)
                self.is_axis = True

            elif self.input_type in (InputType.JoystickButton, InputType.JoystickHat):
                if "id" in node.attrib:
                    str_id = node.get("id")
                    if not str_id.isnumeric():
                        self.input_id = gremlin.base_classes.SpecialInputItem(str_id)
                    else:
                        self.input_id = safe_read(node, "id", int, 0)
            elif self.input_type == InputType.OctaviIfr1:
                if "id" in node.attrib:
                    button = safe_read(node, "id", int, 0)
                    self.input_id = gremlin.ui.octavi_device.OctaviButton(button)

        assert self.input_id is not None, "input id not found"

        # read containers for this input item
        self._containers.pushSuspend()  # stop updates
        self._containers.clear()  # remove any prior data
        container_nodes = node.xpath("./container")
        for child in container_nodes:
            if child.tag in ("latched", "input", "keylatched") or _is_curve_tag(child.tag):
                # ignore extra data
                continue
            if "type" not in child.attrib:
                # could be a blank container
                action_set_nodes = child.xpath("./action-set")
                if action_set_nodes:
                    # this is an error
                    syslog.error(f"XML {child.tag} is missing container 'type' attribute.  Offending line [{child.sourceline}]")
                continue
            container_type = child.get("type")

            if container_type not in container_tag_map:
                syslog.warning(f"Unknown container type used: {container_type}")
                continue
            entry = container_tag_map[container_type](self)
            mode_object = gremlin.base_profile.get_mode_object(node, extra_data)
            if extra_data is None:
                extra_data = {}
            if mode_object:
                extra_data["mode_object"] = mode_object
            extra_data["input_item"] = self
            entry.from_xml(child, data, extra_data)
            # verify the entry has data
            self._containers.add(entry)

            if hasattr(entry, "action_model"):
                entry.action_model = self.containers
            container_plugins.set_container_data(self, entry)

        self._containers.popSuspend()  # allow updates

    def is_valid_for_save(self) -> bool:
        """true if the item has something to save to a profile"""
        if self.input_type in (InputType.Keyboard, InputType.KeyboardLatched):
            # if isinstance(self.input_id, Key):
            #     # has a key definition, save
            return True
        elif self.input_type in (InputType.Midi, InputType.OpenSoundControl):
            return True
        elif hasattr(self.input_id, "to_xml"):
            # has a custom input that returns an XML node
            return True

        if not self._containers and not self._description and not self.always_execute:
            # has no containers, no description and execute flag is True (default)
            return False
        return True

    def to_xml(self, parent_node=None):
        """Generates a XML node representing this object's data.

        :return XML node representing this object
        """

        if self._input_item_generating_xml:
            syslog.error("INPUT ITEM XML: recursion detected")
        try:
            self._input_item_generating_xml = True

            if parent_node is None:
                node = etree.Element(InputType.to_string(self.input_type))

                container_node = node  # default container node to the input node
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
                node.set("description", html.escape(self._description))

            # lock state
            if self._locked:
                # only save if the flag is set
                node.set("locked", safe_format(self._locked, bool))

            for entry in self.containers:
                # write the containers
                child = entry.to_xml()
                if child is not None:
                    container_node.append(child)

            return node
        finally:
            self._input_item_generating_xml = False

    def get_device_type(self):
        """Returns the DeviceType of this input item.

        :return DeviceType of this entry
        """
        return self._device_type

    def get_input_type(self):
        """Returns the type of this input.

        :return Type of this input
        """
        if hasattr(self, "getOverrideInputType"):
            return self.getOverrideInputType()
        return self.input_type

    @property
    def display_name(self):
        """gets a display name for this input"""
        if self.is_action:
            return "this action"
        if self._input_id is None:
            return f"{self._input_type.name}"

        match self._input_type:
            case InputType.JoystickAxis:
                device = gremlin.joystick_handling.getDevice(self.device_guid)
                return f"{device.get_axis_name(self._input_id)}"
            case InputType.JoystickButton:
                return f"Button {self._input_id}"
            case InputType.JoystickHat:
                return f"Hat {self._input_id}"
            case InputType.Keyboard | InputType.KeyboardLatched:
                return f"Key {self._input_id.display_name}"
            case InputType.OpenSoundControl:
                return f"OSC {self._input_id.display_name}"
            case InputType.Midi:
                return f"Midi {self._input_id.display_name}"
            case InputType.ModeControl:
                return f"{gremlin.ui.mode_device.ModeInputModeType.to_display_name(self._input_id)}"
            case InputType.State:
                return f"State: {self._input_id}"
            case InputType.OctaviIfr1:
                return f"IFR1: {self._input_id.name}"
            case InputType.ModeControl:
                return f"ModeControl: {self._input_id}"

        return f"Unknown input: {self._input_type}"

    def save_container_to_template(self, fname: str):
        if fname:
            root = etree.Element("container_template")
            # get the xml for every container in the mapping
            for container in self.containers:
                node = container.to_xml()
                root.append(node)
            # save the xml
            tree = etree.ElementTree(root)
            try:
                if os.path.isfile(fname):
                    # blitz existing file
                    os.unlink(fname)
                tree.write(fname, pretty_print=True, xml_declaration=True, encoding="utf-8")
            except Exception as err:
                syslog.error(f"Error writing template to: [{fname}]")
                syslog.error(f"{err}\n{traceback.format_exc()}")
                return False
            return True

        return False

    def load_container_from_template(self, fname, extra_data=None):
        """loads new containers from a template - returns a list of containers"""
        if fname and os.path.isfile(fname):
            container_list = []
            plugin_manager = gremlin.plugin_manager.ContainerPlugins()
            parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
            msg_list = []
            try:
                tree = etree.parse(fname, parser=parser)
                root = tree.getroot()
                if root.tag == "container_template":
                    # get root containers only
                    nodes = root.xpath("//container[not(ancestor::container)]")
                    for node in nodes:
                        container_type = node.get("type")
                        container_plugins = gremlin.plugin_manager.ContainerPlugins()
                        container_tag_map = container_plugins.tag_map

                        # verify the container is valid for the input type
                        valid_containers_names = self.get_valid_container_list()
                        if container_type in container_tag_map:
                            container_name = container_tag_map[container_type].name
                            if container_name in valid_containers_names:
                                new_container = container_tag_map[container_type](self)
                                new_container.from_xml(node, self, extra_data)
                                new_container.generateGuids()  # replace IDs to avoid conflicts
                                container_list.append(new_container)
                        else:
                            msg = f"Container {container_type.name} is not valid for the current input"
                            msg_list.append(msg)
                            syslog.warning(msg)

                if msg_list:
                    prompt = "".join((msg + "\n" for msg in msg_list))
                    gremlin.ui.ui_common.MessageBox(title="Load Template", prompt=prompt)

            except Exception as err:
                syslog.error(f"Error loading template: [{fname}]:")
                syslog.error(f"{err}\n{traceback.format_exc()}")

            if container_list:
                for new_container in container_list:
                    if hasattr(new_container, "action_model"):
                        # new_container.action_model = self.action_model

                        plugin_manager.set_container_data(self, new_container)
                        # new_container.action_model.add_container(new_container)

            self.containers.extend(container_list)

            return container_list

    def generateGuids(self):
        """generate a set of new GUIDs for mapped items"""
        for container in self.containers:
            container.generateGuids()

    @property
    def debug_name(self):
        """debug string for this item"""
        mode = self.profile_mode
        if mode == gremlin.shared_state.master_mode:
            mode = gremlin.shared_state.master_mode_name

        return f"InputItem: device: [{self.device_name}] input: [{self.display_name}] mode: [{mode}]"

    def __eq__(self, other):
        """true if the input item are the same object"""
        if other is None:
            return False
        if not isinstance(other, InputItem):
            return False
        return self.id == other.id

    def __hash__(self):
        """make hashable"""
        return super().__hash__()


class InputItemMessage(InputItem):
    """represents a message associated with an input item"""

    message_key_changed = Signal(str)  # fires when message key changes (message_key)

    def __init__(
        self,
        mode_node: str | gremlin.base_profile.ProfileModeNode,  # str or profile mode object
        input_type: InputType,  # must be provided
        input_id=None,  #
        custom_name_handler: Callable = None,
        custom_mode_name_handler: Callable = None,
        override_input_type: Callable = None,
        custom_input_id_handler: Callable = None,
        device_guid: dinput.GUID | uuid.UUID | str = None,  # noqa: F405,
        description: str = None,
        description_readonly: bool = None,
        tooltip: str = None,
        on_message_key_changed: Callable = None,  # callback when the message key is changed (old_key, new_key)
    ):
        """Creates a new InputItem instance.
        :param mode_node: profile mode node
        :param input_type : input type of the input item
        :param input_id : input id of the input item
        :param custom_name_handler: handler() returns a string, whenever the input name is needed
        :param custom_mode_name_handler: handler() returns a string, optional, to override the default mode for special inputs that use special modes
        :param description: optional description text
        :param description_readonly: optional flag to indicate if the description of the input can be user edited
        :param tooltip: optional tooltip text

        """
        super().__init__(
            mode_node=mode_node,
            input_type=input_type,
            input_id=input_id,
            custom_name_handler=custom_name_handler,
            custom_mode_name_handler=custom_mode_name_handler,
            override_input_type=override_input_type,
            device_guid=device_guid,
            description=description,
            description_readonly=description_readonly,
            tooltip=tooltip,
            custom_input_id_handler=custom_input_id_handler,
        )

        self._message = None
        self._message_key: str = None
        self._title_name = "MIDI (not configured)"
        self._display_name = None
        self._display_tooltip = "Input configuration not set"
        self._on_message_key_changed = on_message_key_changed

        current_mode = gremlin.shared_state.current_mode
        tracker = gremlin.ui.ui_common.DeviceWidgetTracker()
        tracker.registerWidget(
            self,
            self._device_guid,
            current_mode,
            self._input_type,
            self.message_key,
            self._guid,
        )

    @property
    def message(self):
        return self._message

    @message.setter
    def message(self, value):
        self._message = value
        self._update()

    @property
    def message_key(self) -> str:
        return self._message_key if self._message_key else self._guid  # get a unique key

    def setMessageKey(self, message_key: str):
        """registers a new message key for this MIDI input item"""
        if message_key:
            if self._message_key != message_key:
                current_mode = gremlin.shared_state.current_mode
                tracker = gremlin.ui.ui_common.DeviceWidgetTracker()

                if self._on_message_key_changed:
                    # uregister the old
                    tracker.unregisterWidget(
                        self._device_guid,
                        current_mode,
                        self._input_type,
                        self._message_key,
                        self._guid,
                    )

                    self._on_message_key_changed(self._message_key, message_key)

                    tracker.registerWidget(
                        self,
                        self._device_guid,
                        current_mode,
                        self._input_type,
                        self._message_key,
                        self._guid,
                    )

                self.message_key_changed.emit(self._message_key)

    @abstractmethod
    def _update(self):

        pass

# class InputItemLayoutItem(QtWidgets.QLayoutItem):
#     def __init__(self, size: int):
#         super().__init__()
#         self._size = size
#         self._rect = QtCore.QRect()

#     def setGeometry(self, rect: QtCore.QRect):
#         # Center a strict square box inside whatever space the layout allocates
#         self._rect = rect

#     def geometry(self) -> QtCore.QRect:
#         return self._rect

#     def sizeHint(self) -> QtCore.QSize:
#         return QtCore.QSize(self._size, self._size)

#     def minimumSize(self) -> QtCore.QSize:
#         return QtCore.QSize(10, 10)

#     def maximumSize(self) -> QtCore.QSize:
#         return QtCore.QSize(self._size, self._size)

#     def isEmpty(self) -> bool:
#         return False
class InputItemContentLayout(QtWidgets.QLayout):
    """custom layout for input item widgets"""
    def __init__(self, widgets : dict = None, parent=None):
        super().__init__(parent)
        self._description_widget = None
        self._repeater_widget = None
        self._action_icons_widget = None
        self._status_widget = None
        self._items = {}
        self._index_map = {}
        self._computed_height = 0
        self._parent = parent
        self._next_index = 0

        if widgets:
            self.addWidgets(widgets)

    def addWidget(self, widget, key : str = None):
        widget._layout_key = key
        super().addWidget(widget)

    def addItem(self, item : QtWidgets.QLayoutItem):
        key = item.widget()._layout_key if hasattr(item.widget(), "_layout_key") else None
        if key is None:
            key = str(len(self._items))
        index = self._next_index
        self._items[key] = index
        self._index_map[index] = item
        self._next_index += 1


    def addWidgets(self, widgets: dict):
        for key, item in widgets.items():
            self.addWidget(item, key)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._index_map.get(index, None)

    def takeAt(self, index):
        return self._index_map.pop(index, None)


    def setGeometry(self, rect : QtCore.QRect):
        super().setGeometry(rect)

        spacing = self.spacing()

        margin = self.contentsMargins()

        x = rect.x()
        y = rect.y()

        x += margin.left()
        y += margin.top()

        for index, item in self._index_map.items():
            key = self._items[index]
            widget = item.widget()
            hint = widget.sizeHint()
            w = hint.width()
            h = hint.height()
            if w and h:
                # item has a size
                syslog.info(f"placing item [{key}] at x: {x}, y: {y}, w: {w}, h: {h}")
                item.setGeometry(QtCore.QRect(x, y, w, h))
                y += h + spacing  # add spacing

        self._computed_height = y + margin.bottom()

        return self._computed_height

    def sizeHint(self) -> QtCore.QSize:
        """Computes the ideal bounding footprint of the layout."""
        width = 230
        height =  self._computed_height
        return QtCore.QSize(width, height)

    def minimumSize(self) -> QtCore.QSize:
        """Prevents layout from crushing down to zero space."""
        return self.sizeHint()





class InputItemWidget(gremlin.ui.ui_common.QBoxFrame):
    """holds the input widget (left side of the interface) for available inputs that get mapped.

    this widget is used to represent an input mapping.  There are multiple variants of this for joysticks, vjoy (as input), keyboard, OSC and MIDI.

    Some of those use custom widget rendering based on their types.

    This event can be used to display input item specific customization
    widgets. This button also shows icons of the associated actions.
    """

    # Signal emitted whenever this button is pressed
    # selected_changed = Signal(InputIdentifier)

    # signal when button's close button is pressed
    closed = Signal(InputIdentifier)

    # signal when button's edit button is pressed
    edit = Signal(InputIdentifier)

    # signal when the edit curve button is pressed
    edit_curve = Signal(InputIdentifier)

    # signal when the clear curve button is pressed
    delete_curve = Signal(InputIdentifier)

    # signal input value changed
    input_value_changed = Signal(InputIdentifier, float)

    def __init__(
        self,
        input_item: InputItem,
        populate_ui_callback: Callable = None,
        populate_name_callback: Callable = None,
        selection_changed_callback: Callable = None,
        update_callback: Callable = None,
        confirm_delete_callback: Callable = None,
        get_state_callback: Callable = None,
        config_external=False,
        data=None,
        parent=None,
    ):
        """builds the widget
        :param input_item: The input item associated with this widget
        :param identifier: The input identifier associated with this widget
        :param parent: Optional parent widget
        :param populate_ui_callback: Optional callback to populate the UI
        :param populate_name_callback: Optional callback to populate the name
        :param selection_changed_callback: Optional callback for selection changes
        :param update_callback: Optional callback for updates
        :param confirm_delete_callback: Optional callback for confirming deletion
        :param get_state_callback: Optional callback to get the current state of the input
        :param config_external: True if the widget is configured externally
        :param data: Optional additional data

        """

        super().__init__(parent)

        self.parent = parent

        self.widget_width = None  # actual width in pixels
        self.widget_height = None  # actual height in pixels
        self._interact_enabled = True  # true if can be interacted with
        self._icons_dirty = True  # true if the icons need to be updated

        self._ui_loaded = False
        self.data = data
        self._selected = False
        self._confirm_delete_callback = confirm_delete_callback
        self.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

        self._debug_layout = False

        assert isinstance(input_item, InputItem), "invalid input item"

        self._input_item = None
        self._input_type = None
        self._device_guid = None
        self._input_id = None
        self.setInputItem(input_item)

        if hasattr(self._input_id, "input_mode_changed"):
            # hook identifiers that can change mode from axis to button or vice versa so the repeaters match - example OSC or MIDI
            self._input_id.input_mode_changed.connect(self._update_repeater)

        self._multi_row = populate_ui_callback is not None
        self.populate_ui = populate_ui_callback  # get custom content callback
        self.populate_name = populate_name_callback  # get name callback

        self._config_external = config_external  # true if the widget is a custom widget configured externally
        self._update_callback = update_callback  # callback to use when a specific widget index must be updated

        self._get_state_callback = get_state_callback  # store the callback to get the current state of the input

        self._selection_change_callbacks = []
        if selection_changed_callback:
            self.addSelectionChangeCallback(selection_changed_callback)

        self._title_icons = []  # title bar icons

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.setObjectName("main_layout")

        # main container
        self._container_widget  = QtWidgets.QWidget()
        self._container_layout = QtWidgets.QVBoxLayout(self._container_widget)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(0)
        self._container_widget.setObjectName("container_widget")

        self.main_layout.addWidget(self._container_widget)

        # lock icon
        icon_lock = gremlin.ui.ui_common.Icons.lockIcon()
        icon_unlock = gremlin.ui.ui_common.Icons.unlockIcon()
        self._lock_widget = gremlin.ui.ui_common.QIconCheckbox(icon_lock, icon_unlock, size=16)

        if input_item:
            input_item.lockedChanged.connect(self._handle_input_item_lock_changed)
            input_item.tooltipChanged.connect(self._handle_tooltip_changed)
        else:
            pass

        self._input_item = input_item

        if input_item:
            self._lock_widget.setChecked(input_item.locked)
        self._lock_widget.clicked.connect(self._handle_lock_changed)

        # top row
        # title bar
        self._title_bar_widget, self._title_bar_layout = gremlin.ui.ui_common.getVContainer()
        self._title_container_widget, self._title_container_layout = gremlin.ui.ui_common.getGridContainer()

        self._title_bar_widget.setContentsMargins(4, 0, 4, 0)  # title bar
        self._title_bar_layout.addWidget(self._title_container_widget)
        self._title_bar_widget.setObjectName("title_bar")
        self._title_bar_widget.setFixedHeight(32)


        # title bar left side

        self._title_text_widget = gremlin.ui.ui_common.QIconLabel()
        self._title_text_widget.setContentsMargins(0, 0, 0, 0)
        self._title_text_widget.setText(input_item.display_name)
        self._title_text_widget.setObjectName("title")
        if input_item.tooltip:
            self._title_text_widget.toolTip = input_item.tooltip

        self._title_text_container_widget = gremlin.ui.ui_common.getHContainer([self._lock_widget, self._title_text_widget], widget_only=True)

        # title bar right side - holds the icons
        self._title_icon_widget, self._title_icon_layout = gremlin.ui.ui_common.getHContainer()

        self._title_container_layout.addWidget(self._title_text_container_widget, 0, 0)
        self._title_container_layout.addWidget(QtWidgets.QWidget(), 0, 1)
        self._title_container_layout.addWidget(self._title_icon_widget, 0, 2, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        self._title_container_layout.setColumnStretch(1, 1)

        self._container_layout.addWidget(self._title_bar_widget)




        # icon setup
        size = self._getIconSize()  # icon size
        active_color = gremlin.ui.ui_common.Color.activeColor()
        normal_color = gremlin.ui.ui_common.Color.normalColor()
        self._curve_icon_inactive = load_icon("mdi.chart-bell-curve", qta_color=normal_color)
        self._curve_icon_active = load_icon("mdi.chart-bell-curve", qta_color=active_color)
        self._input_icon_inactive = load_icon("fa6s.power-off", qta_color=normal_color)
        self._input_icon_active = load_icon("fa6s.power-off", qta_color=active_color)
        self._calibration_icon_active = load_icon("mdi.arrow-expand-horizontal", qta_color=active_color)
        self._calibration_icon_inactive = load_icon("mdi.arrow-expand-horizontal", qta_color=normal_color)

        # action buttons
        self._edit_button_widget = None

        # input button on/off - added only via enable_edit()
        self._input_button_widget = None

        # close widget - added only via enable_close()
        self._close_button_widget = None

        # curve toolbar
        self.is_axis = input_item.is_axis

        # calibration button
        self._calibration_button_widget = None

        # input curve button
        self._curve_button_widget = None

        # clear input curve button
        self.clear_curve_widget = None


        self._toolbar_buttons = []

        if self.is_axis:
            # curve container (axis only)
            self._curve_container_widget, self._curve_container_layout = gremlin.ui.ui_common.getHContainer()
            self._title_icon_layout.addWidget(self._curve_container_widget)

            self._curve_container_layout.addStretch()


            css = gremlin.ui.ui_common.Color.cssInputHeaderButton()

            self._curve_button_widget = gremlin.ui.ui_common.QDataPushButton(icon=self._curve_icon_inactive, size=size,callback=self._curve_button_cb, tooltip="Input Curve", css=css)

            self._curve_container_layout.addWidget(self._curve_button_widget)
            self._toolbar_buttons.append(self._curve_button_widget)

            self._calibration_button_widget = gremlin.ui.ui_common.QDataPushButton(icon=self._calibration_icon_active, size=size,callback=self._calibration_button_cb, tooltip="Device calibration options", css=css)
            self._curve_container_layout.addWidget(self._calibration_button_widget)
            self._toolbar_buttons.append(self._calibration_button_widget)

            self.clear_curve_widget = gremlin.ui.ui_common.QDataPushButton(icon=load_icon("mdi.delete"), size=size, callback=self._clear_curve_cb, tooltip="Clear Curve", css=css)
            self._curve_container_layout.addWidget(self.clear_curve_widget)
            self._toolbar_buttons.append(self.clear_curve_widget)



        # description row
        self._description_widget = gremlin.ui.ui_common.AutoHideIconTextWidget(style="font-style: italic;", data = "description")
        self._description_icon = None


        # action icons
        self._action_icon_widget = gremlin.ui.ui_common.AutoHideStackedWidget(data = "action icons")


        # input description row
        self._input_description_widget = gremlin.ui.ui_common.AutoHideIconTextWidget(data = "input description")
        self._input_description_icon = None

        # custom widget row (used by some inputs to display custom UI elements like keyboard )
        self._custom_container_widget = gremlin.ui.ui_common.AutoHideStackedWidget(data = "custom content")

        # repeater
        self.axis_repeater_widget = None # axis repeater
        self.button_repeater_widget = None # button repeater
        self._repeater_container_widget = gremlin.ui.ui_common.AutoHideStackedWidget(data = "repeater")


        # comment row
        self._comment_widget = gremlin.ui.ui_common.AutoHideIconTextWidget(data = "comment")

        # status row
        self._status_widget = gremlin.ui.ui_common.AutoHideIconTextWidget(data = "status"  )

        # container ID row
        self._container_id_widget = gremlin.ui.ui_common.AutoHideStackedWidget()


        # item content setup below the title bar
        #self._content_widget = gremlin.ui.ui_common.AutohideContainer()
        self._content_widget = QtWidgets.QWidget()
        self._content_layout = QtWidgets.QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        self._content_layout.setSpacing(0)

        items = {
            # "top": QtWidgets.QLabel("top widget"),
            # "t1": QtWidgets.QLabel("t1"),
            # "t2": QtWidgets.QLabel("t2"),
            # "t3": QtWidgets.QLabel("t3"),

            "repeater": self._repeater_container_widget,
            "action_icons": self._action_icon_widget,
            "description": self._description_widget,
            "status": self._status_widget,
            "input_description": self._input_description_widget,
            "custom_content": self._custom_container_widget,
            "comment": self._comment_widget,
            "container_id": self._container_id_widget,
            # "bottom": QtWidgets.QLabel("bottom widget")
        }
        # self._content_widget.sizeChanged.connect(self._update_height)
        # self._content_widget.addWidgets(items)
        for key, widget in items.items():
            self._content_layout.addWidget(widget)


        #InputItemContentLayout(widgets = items, parent = self._content_widget)

        self._container_layout.addWidget(self._content_widget)

        self._ui_loaded = True

        # event filter
        self.installEventFilter(self)

        # hook mapping changed event
        self._connect_events()

        # update the defaults
        input_name = input_item.input_name
        self.setTitle(input_name)
        self.setDescription(input_item.description)

        # update mapping action icons
        self._update_repeater()  # create the correct repeater widget
        self._update_selected_ui()
        self._update_display_ui()

        if self.is_axis:
            # update axis input icons
            self._update_axis_icons_ui()

        self.ensureStyle()

        self._autohide_widgets = gremlin.util.get_widget_references(self, gremlin.ui.ui_common.AutoHideStackedWidget)
        self.widget_height= self.sizeHint().height()

    def resizeEvent(self, event):
        # update the size record when the widget is resized
        super().resizeEvent(event)
        size = self.size()
        self.widget_height = size.height()


    def setInputItem(self, input_item: InputItem):
        """sets the input item for this widget"""
        assert isinstance(input_item, InputItem), "invalid input item"
        if input_item == self._input_item:
            # already set
            return
        old_input_item = self._input_item
        if old_input_item:
            old_input_item.containers.removeCallback(self.handleMappingChanged)

        self._input_item = input_item

        self._input_item.containers.addCallback(self.handleMappingChanged)

        self._input_id = input_item.input_id
        self._device_guid = input_item.device_guid
        self._input_type = input_item.input_type
        if input_item and input_item.tooltip:
            self.setToolTip(input_item.tooltip)

    def handleMappingChanged(self, input_item: InputItem):
        """called when the input item changes"""
        assert isinstance(input_item, InputItem), "invalid input item"
        if input_item != self._input_item:
            # not ours
            return
        gremlin.util.InvokeUiMethod(self._mapping_changed_cb_ui, input_item)  # ensure on UI thread

    def setInteractable(self, interactable: bool):
        """sets whether the input item can be interacted with"""
        self._interact_enabled = interactable

    def getInteractable(self) -> bool:
        """gets whether the input item can be interacted with"""
        return self._interact_enabled and not gremlin.shared_state.is_running

    def setTooltip(self, tooltip: str):
        """sets the tooltip on the title bar for the input item"""
        self._title_text_widget.toolTip = tooltip

    def addSelectionChangeCallback(self, callback: Callable):
        """adds a callback to be called when selection flag changes passes the (widget)
        :param callback: the callback to add
        """
        if __debug__ and callback is not None and not callable(callback):
            raise TypeError("Callback must be callable")
        if callback not in self._selection_change_callbacks:
            self._selection_change_callbacks.append(callback)

    def removeSelectioChangeCallback(self, callback: Callable):
        """removes a callback from the list of callbacks to be called when the model changes - this is used by the container
        :param callback: the callback to remove
        """
        if callback in self._selection_change_callbacks:
            self._selection_change_callbacks.remove(callback)

    def _fireSelectionChangeCallbacks(self):
        """fires the selection change callbacks  callback(InputItemWidget) - the parameter is the widget that has changed state"""
        for callback in self._selection_change_callbacks:
            callback(self)

    def trigger(self):
        """triggers the widget to send the selection state again"""
        self._fireSelectionChangeCallbacks()



    @property
    def input_item(self) -> "InputItem":
        return self._input_item

    def eventFilter(self, widget, event):
        """UI event handler - trap mouse clicks for selection"""
        if self.getInteractable() and not self._selected:
            t = event.type()
            if t == QtCore.QEvent.Type.MouseButtonPress:
                button = event.buttons()
                if button == QtCore.Qt.LeftButton:
                    self.selected = True

        return super().eventFilter(widget, event)

    def getLayout(self):
        return self._custom_container_layout

    def addWidget(self, widget):
        """adds a widget to the container"""
        self._custom_container_widget.layout().addWidget(widget)

    def clearWidgets(self):
        """clears the custom container layout and hides it"""
        self._custom_container_widget.setWidget(None)

    def _handle_input_item_lock_changed(self, input_item):
        if input_item == self._input_item:
            gremlin.util.InvokeUiMethod(self._handle_input_item_lock_changed_ui, input_item)

    def _handle_tooltip_changed(self):
        if self.input_item and self.input_item.tooltip:
            self.setToolTip(self.input_item.tooltip)
        else:
            # clear
            self.setToolTip(None)

    def _handle_input_item_lock_changed_ui(self, input_item):

        if Shiboken.isValid(self._lock_widget):
            with QtCore.QSignalBlocker(self._lock_widget):
                self._lock_widget.setChecked(input_item.locked)

        # enable the delete button if not locked
        if self._close_button_widget and Shiboken.isValid(self._close_button_widget):
            self._close_button_widget.setEnabled(not input_item.locked)

    @QtCore.Slot(bool)
    def _handle_lock_changed(self, checked: bool):
        input_item = self.input_item
        input_item.locked = checked
        if input_item.locked != checked:
            # input cannot be locked/unlocked - undo the check
            with QtCore.QSignalBlocker(self._lock_widget):
                self._lock_widget.setChecked(not checked)

    def _update_title(self):
        """updates the title bar stylesheet based on the selection state"""
        css = gremlin.ui.ui_common.Color.cssSelectedInputHeader() if self._selected else gremlin.ui.ui_common.Color.cssUnselectedInputHeader()
        self._title_container_widget.setStyleSheet(css)

    def _update_container_id(self):
        gremlin.util.InvokeUiMethod(self._update_container_id_ui)  # on UI thread

    def _update_container_id_ui(self):
        """updates container ID display for associated containers with this input"""
        if not Shiboken.isValid(self._container_id_widget):
            return
        config = gremlin.config.Configuration()
        if config.show_container_id:
            width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
            grids = []

            # input id
            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setMinimumWidth(width)
            line_edit.setText(gremlin.util.idString(self.input_item.id))
            line_edit.setReadOnly(True)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Input ID:", widget_only=True)
            self._container_id_widget.setWidget(widget)
            grids.append(widget)

            container_count = len(self.input_item.containers)
            if container_count:
                for index, container in enumerate(self.input_item.containers):
                    line_edit = gremlin.ui.ui_common.QDataLineEdit()
                    line_edit.setMinimumWidth(width)
                    line_edit.setText(container.id)
                    line_edit.setReadOnly(True)
                    widget = gremlin.ui.ui_common.getGridContainer(line_edit, f"[{index}] {container.name}", widget_only=True)
                    self._container_id_widget.layout().addWidget(widget)
                    grids.append(widget)
            else:
                # no container
                line_edit = gremlin.ui.ui_common.QDataLineEdit()
                line_edit.setMinimumWidth(width)
                line_edit.setText("No container found")
                line_edit.setReadOnly(True)
                widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Mapping:", widget_only=True)
                self._container_id_widget.layout().addWidget(widget)
                grids.append(widget)

            gremlin.ui.ui_common.synchronize_grids(grids)

            # selected state
            self._container_id_widget.layout().addWidget(QtWidgets.QLabel(f"Selected: {self.selected}"))
        else:
            self._container_id_widget.setWidget(None) #hide


    def _connect_events(self):
        el = gremlin.event_handler.EventListener()
        el.curve_deleted.connect(self._curve_changed_cb)
        el.curve_added.connect(self._curve_changed_cb)
        el.calibration_added.connect(self._calibration_changed_cb)
        el.calibration_deleted.connect(self._calibration_changed_cb)
        # el.action_changed.connect(self._action_changed_cb)
        el.mapping_changed.connect(self._mapping_changed_cb)
        el.icon_changed.connect(self._icon_changed_cb)
        el.update_input_icons.connect(self._update_axis_icons)
        el.profile_loaded.connect(self._update_axis_icons)

    def _disconnect_events(self):
        el = gremlin.event_handler.EventListener()
        el.curve_deleted.disconnect(self._curve_changed_cb)
        el.curve_added.disconnect(self._curve_changed_cb)
        el.calibration_added.disconnect(self._calibration_changed_cb)
        el.calibration_deleted.disconnect(self._calibration_changed_cb)
        # el.action_changed.disconnect(self._action_changed_cb)
        el.mapping_changed.disconnect(self._mapping_changed_cb)
        el.icon_changed.disconnect(self._icon_changed_cb)
        el.update_input_icons.disconnect(self._update_axis_icons)
        el.profile_loaded.disconnect(self._update_axis_icons)

    def _cleanup_ui(self):
        """called when widget is removed"""

        self._disconnect_events()

        if self.input_item:
            self.input_item.setInputWidget(None)  # clear reference on the input

        self._status_widget.setWidget(None)
        self._description_widget.setWidget(None)
        self._input_description_widget.setWidget(None)
        # self._status_container_widget.setWidget(None)
        self._container_id_widget.setWidget(None)
        self._repeater_container_widget.setWidget(None)
        self._custom_container_widget.setWidget(None)

        gremlin.util.clear_widget_references(self)

        gremlin.util.clear_layout(self.main_layout)


    @property
    def content_layout(self):
        """gets the the content row"""
        return self._custom_container_layout

    def _getIconSize(self) -> int:
        return 16

    def _getRowHeight(self) -> int:
        return 28

    def _setWidgetHeight(self, widget: QtWidgets.QWidget | list[QtWidgets.QWidget], h):
        """sets fixed min/max height"""
        pass
        # if not hasattr(widget, "__iter__"):
        #     w_list = [widget]
        # else:
        #     w_list = widget
        # for widget in w_list:
        #     if widget == self._description_container_widget and h != 0:
        #         pass
        #     if Shiboken.isValid(widget):
        #         widget.setFixedHeight(h)

    def _update_repeater(self):
        """updates the repeaters based on the type of widget"""
        gremlin.util.assert_ui_thread()

        # use the override input type to determine button or axis repeater
        input_item = self.input_item
        input_type = input_item.getOverrideInputType()

        if input_item.input_type in (
            InputType.Keyboard,
            InputType.KeyboardLatched,
            InputType.ModeControl,
            InputType.State,
        ):
            # button only inputs
            self._repeater_container_widget.setWidget(None)
            self.axis_repeater_widget = None
            self.button_repeater_widget = None
            return

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_ui_level(2)

        widget = None  # widget created for the repeater

        if config.show_input_axis:

            input_item = self.input_item
            if (input_item.is_axis or input_item.is_button or input_item.is_hat) or input_type in (
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat,
            ):
                hook_id = gremlin.util.normalize_guid(input_item.device_guid)
                if input_item.is_axis:
                    # axis
                    if self._get_state_callback:
                        values = self._get_state_callback()
                    else:
                        device_guid = input_item.device_guid
                        device: dinput.DeviceSummary = gremlin.joystick_handling.getDevice(device_guid)
                        input_id = input_item.input_id
                        assert input_id in device.axis_id_map, f"invalid axis id: [{input_id}] for device: [{device.name}]"

                        astate = gremlin.event_handler.AxisState()
                        values = astate.getAxisValues(device_guid, input_id)

                    if not self.axis_repeater_widget or self._repeater_container_widget.widget() is None:
                        # create the repeater
                        widget = gremlin.ui.ui_common.QAxisRepeaterProgressbar(
                            input_item=self._input_item,
                            values=values,
                            callback=self._get_state_callback,
                            description=f"axis repeater for input item: {self.input_item.display_name}",
                        )

                        widget.setMaximumWidth(200)
                        self.axis_repeater_widget = widget
                        self._repeater_container_widget.setWidget(widget)

                        if verbose:
                            description = f"input repeater:  hook id: [{hook_id}] [{str(self.input_item.id)}] device [{gremlin.joystick_handling.getDeviceName(input_item.device_guid)}] axis id: [{input_item.input_id}] "
                            syslog.info(f"register repeater: {description}")

                    self.axis_repeater_widget.triggerUpdate()  # force an update
                else:
                    # button

                    if not self.button_repeater_widget:  # and input_type in (InputType.JoystickButton, InputType.JoystickHat):
                        widget = gremlin.ui.ui_common.QButtonStateWidget(
                            input_item=self._input_item,
                            callback=self._get_state_callback,
                            description=f"ButtonRepeater for: [{self._input_item.display_name}]",
                        )
                        self.button_repeater_widget = widget
                        self._repeater_container_widget.setWidget(widget)


    def _message_key_changed(self, old_message_key, new_message_key):
        state_tracker = gremlin.ui.ui_common.StateTracker()

        print(f"INPUT ITEM: message change {old_message_key} to {new_message_key}")

        if old_message_key:
            state_tracker.unregisterAxisState(self._device_guid, self._input_type, old_message_key)
            state_tracker.unregisterButtonState(self._device_guid, self._input_type, old_message_key)

        if self.axis_repeater_widget:
            state_tracker.registerAxisState(self.axis_repeater_widget, self._device_guid, self._input_type, new_message_key)
        if self.button_repeater_widget:
            state_tracker.registerButtonState(self.button_repeater_widget, self._device_guid, self._input_type, new_message_key)

    @QtCore.Slot(object)
    def _update_enabled_state(self, input_item):  # : InputItem
        """updates the enabled state"""
        if self.input_item == input_item:
            # ours
            if input_item.enabled:
                self._input_button_widget.setIcon(self._input_icon_active)
            else:
                self._input_button_widget.setIcon(self._input_icon_inactive)

    def _update_axis_icons(self):
        if not self._ui_loaded or not self.is_axis:
            return
        gremlin.util.InvokeUiMethod(self._update_axis_icons_ui)

    def _update_axis_icons_ui(self):
        """update titlebar icons - UI thread"""
        is_curve = self._input_item.is_curve
        if Shiboken.isValid(self._curve_button_widget):
            if is_curve:
                self._curve_button_widget.setIcon(self._curve_icon_active)
            else:
                self._curve_button_widget.setIcon(self._curve_icon_inactive)

        if Shiboken.isValid(self.clear_curve_widget):
            self.clear_curve_widget.setEnabled(is_curve)

        if Shiboken.isValid(self._calibration_button_widget):
            has_calibration = self._input_item.hasCalibration
            if has_calibration:
                self._calibration_button_widget.setIcon(self._calibration_icon_active)
            else:
                self._calibration_button_widget.setIcon(self._calibration_icon_inactive)

    def _update_action_icons(self):
        """updates the input item's action icon list"""
        gremlin.util.InvokeUiMethod(self._update_action_icons_ui)

    def _update_action_icons_ui(self):
        # update mapping icons
        self.create_action_icons(self.input_item)

    def _icon_changed_cb(self, event: gremlin.event_handler.DeviceChangeEvent):
        gremlin.util.InvokeUiMethod(self._icon_changed_cb_ui, event)

    def _icon_changed_cb_ui(self, event: gremlin.event_handler.DeviceChangeEvent):
        """updates the input item icons based on the actions it contains - UI thread"""
        if isinstance(event.source, gremlin.base_profile.AbstractAction):
            action = event.source
            if self.findAction(action):
                # update the action
                self._icons_dirty = True
                self.create_action_icons(self.input_item)
        elif isinstance(event.source, InputItem):
            if self.input_item == event.source:
                self._icons_dirty = True
                self.create_action_icons(self.input_item)

    @QtCore.Slot(object)
    def _action_changed_cb(self, event):
        """occurs when an action is added or changed"""
        if isinstance(event, gremlin.base_profile.AbstractAction):
            action = event
        elif isinstance(event, gremlin.event_handler.DeviceChangeEvent):
            action = event.source
        else:
            return
        if isinstance(action, gremlin.base_profile.AbstractAction):
            if self.findAction(action):
                # update the action
                self._icons_dirty = True
                self.create_action_icons(self.input_item)

    @QtCore.Slot(object, object, object)
    def _action_deleted_cb(self, item_dat, container, action):
        """occurs when an action is deleted"""
        if self.findAction(action) and Shiboken.isValid(self):
            # find the widget corresponding to this action
            gremlin.util.InvokeUiMethod(self.clear_action_icon, self.input_item, action)  # ensure on UI thread

    def _curve_changed_cb(self, input_item):
        """fires when a curve is added or deleted"""
        if input_item == self._input_item and Shiboken.isValid(self):
            gremlin.util.InvokeUiMethod(self._update_repeater)  # ensure on UI thread

    def _calibration_changed_cb(self, input_item: InputItem):
        """fires when a calibration is added or deleted"""
        assert isinstance(input_item, InputItem), "invalid input item"
        if input_item == self._input_item and Shiboken.isValid(self):
            gremlin.util.InvokeUiMethod(self._update_repeater)  # ensure on UI thread

    def _mapping_changed_cb(self, input_item: InputItem):
        """called when a mapping changes - sends the item being changed"""
        assert isinstance(input_item, InputItem), "invalid input item"
        if input_item == self.input_item and Shiboken.isValid(self):
            gremlin.util.InvokeUiMethod(self._mapping_changed_cb_ui, input_item)  # ensure on UI thread

    def _mapping_changed_cb_ui(self, input_item: InputItem):
        """update the widget on mapping change"""
        if input_item == self._input_item and Shiboken.isValid(self):
            self._update_container_id_ui()
            self._icons_dirty = True  # force a refresh
            self._update_action_icons_ui()

    def update_curve_icon(self, enabled: bool):
        """enables or disables curve buttons"""
        if self.is_axis:
            if enabled:
                self._curve_button_widget.setIcon(self._curve_icon_active)
            else:
                self._curve_button_widget.setIcon(self._curve_icon_inactive)
            self.clear_curve_widget.setEnabled(enabled)
            if self.input_item.input_type == InputType.JoystickAxis:
                if self.axis_repeater_widget is not None:  # will be null if input axes not displayed
                    self.axis_repeater_widget.show_curved = enabled

    @QtCore.Slot(float)
    def _input_value_changed(self, value):
        """called when the input changes"""
        self.input_value_changed.emit(self, value)

    @property
    def index(self):
        """assigned index"""
        return self._index

    @index.setter
    def index(self, value):
        self._index = value

    @property
    def config_external(self):
        return self._config_external

    @config_external.setter
    def config_external(self, value):
        self._config_external = value

    def setTitle(self, value):
        """sets the title of the input widget"""
        self._title_text_widget.setText(value)

    def setCustomContent(self, items: QtWidgets.QWidget | list[QtWidgets.QWidget]):
        """adds custom content to the input widget (vertical container)"""
        self._custom_container_widget.setWidget(None)
        layout = self._custom_container_widget.layout()
        widgets = items if hasattr(items, "__iter__") else [items]
        for widget in widgets:
            layout.addWidget(widget)


    def setInputDescription(self, description: str | None):
        """sets the input description for an input widget (optional)"""
        if description:
            self._input_description_widget.setText(description, self._input_description_icon)
        else:
            self._input_description_widget.setWidget(None)

    def setInputDescriptionIcon(self, icon_path, use_qta=True):
        """sets (or clears) the icon for the input description line"""
        if isinstance(icon_path, QtGui.QIcon):
            self._input_description_icon = icon_path
        else:
            self._input_description_icon = load_icon(icon_path, use_qta) if icon_path else None
        self._input_description_widget.setIcon(self._input_description_icon)

    def setStatus(self, status: str, icon=None):
        """sets the status"""
        self._status_widget.setText(status, icon)


    def setDescription(self, description: str | None):
        """sets the description of the input widget"""
        self._description_widget.setText(description)

    def setComment(self, value : str | None, icon=None):
        """sets the comment field of the input widget"""
        self._comment_widget.setText(value, icon)


    def setToolTip(self, tooltip):
        """sets the tooltip for the widget"""
        super().setToolTip(tooltip)

    def setIcon(self, icon_path, use_qta=True):
        """sets the widget's icon"""
        self._title_text_widget.setIcon(icon_path, use_qta)


    def update_display(self):
        gremlin.util.InvokeUiMethod(self._update_display_ui)

    def _update_display_ui(self):
        """updates the display text for the button, custom content and input enabled"""

        if gremlin.shared_state.is_running:
            return  # do not update UI at runtime

        if self._ui_loaded:
            config = gremlin.config.Configuration()
            power_visible = config.show_input_enable
            if power_visible:
                if not self._input_button_widget:
                    size = self._getIconSize()
                    self._input_button_widget = QtWidgets.QPushButton()
                    self._input_button_widget.setIcon(self._input_icon_active)
                    self._input_button_widget.setToolTip(
                        "Enables or disables this input.  If disabled, input from this specific input will be ignored.<br>The state can be changed by the control action as well."
                    )
                    self._input_button_widget.setFixedSize(size, size)
                    self._input_button_widget.clicked.connect(self._input_button_cb)
                    self._title_icon_layout.addWidget(self._input_button_widget)
            else:
                if self._input_button_widget and Shiboken.isValid(self._input_button_widget):
                    self._title_icon_layout.removeWidget(self._input_button_widget)
                    self._input_button_widget = None

            # description field
            self.setDescription(self.input_item.description)
            display_text = None
            if not self._config_external or self.populate_name is not None:
                display_text = self.populate_name(self, self.input_item) if self.populate_name is not None else self.input_item.input_name
            if not display_text:
                display_text = self.input_item.display_name

            assert display_text is not None, "display text cannot be None"
            self._title_text_widget.setText(display_text)

            self._update_axis_icons()

            # update selection css
            self._update_selected_ui()

            # populate the custom content
            if self._update_callback:
                self._update_callback(self, self._custom_container_widget)

            # # update repeater
            # if not self.input_item.is_valid:
            #     self._setWidgetHeight(self._repeater_container_widget, 0)

            # # update status
            # if not self.input_item.is_status:
            #     self._setWidgetHeight(self._status_container_widget, 0)

            # update repeater for this widget
            self._update_repeater()

    @property
    def selected(self) -> bool:
        """True if the item is currently selected"""
        return self._selected

    @selected.setter
    def selected(self, value: bool):
        self.setSelected(value)

    def setSelected(self, value: bool, emit=True):
        """marks the item as selected"""
        if value != self._selected:
            verbose = gremlin.config.Configuration().verbose_mode_ui
            if verbose:
                syslog.info(f"InputItemWidget: input item id [{self.input_item.id}] item: [{self.input_item.display_name}] set selected: [{value}]")
            self._selected = value
            self._update_selected()  # uptate widget style

            if emit:
                # notify of selection change
                self._fireSelectionChangeCallbacks()

    def _execute_selected(self, value: bool, emit: bool):
        # ensure the widget has the correct visual selection state
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose:
            syslog.info(f"ItemWidget: selected [{value}]")

        if emit:
            # self.selected_changed.emit(self)
            self._fireSelectionChangeCallbacks()

    def ensureStyle(self):
        """updates the visual selection"""
        self._update_selected()

    def _update_selected(self):
        """updates the widget style based on selection"""
        gremlin.util.InvokeUiMethod(self._update_selected_ui)

    def _update_selected_ui(self):
        """called whenever selection changes"""
        css_button = gremlin.ui.ui_common.Color.cssInputHeaderButton(self._selected)
        if self._selected:
            # css = gremlin.ui.ui_common.Color.cssItemSelected()
            css = f"background-color: {gremlin.ui.ui_common.Color.selectColor()};"
            self._container_widget.setStyleSheet(css)
            # css_bar = gremlin.ui.ui_common.Color.cssSelectedInputHeader()
            bar_color = gremlin.ui.ui_common.Color.getHoverColor(gremlin.ui.ui_common.Color.selectColor(), 1.05).name()
            css_bar = f"background-color: {bar_color}; border:none; padding: 0px; margin: 0px; border-radius: 0px;"

        else:
            css = f"background-color: {gremlin.ui.ui_common.Color.unselectedBackgroundColor()};"
            self._container_widget.setStyleSheet(css)

            self._default_style()
            # css_bar = gremlin.ui.ui_common.Color.cssUnselectedInputHeader()
            bar_color = gremlin.ui.ui_common.Color.inputTitleUnselectedColor()
            css_bar = f"background-color: {bar_color}; border:none;"

        # update style for title bar
        self._title_bar_widget.setStyleSheet(css_bar)

        # update the style for the buttons
        for widget in self._toolbar_buttons:
            widget.setStyleSheet(css_button)

        # update container
        self._update_container_id()
        QtWidgets.QApplication.processEvents()  # update style changes now

    def _default_style(self):
        """sets the default style"""
        # css = f"""
        #             #main_layout {{
        #                 background: {gremlin.ui.ui_common.Color.backgroundColor()};
        #                 border: 1px solid {gremlin.ui.ui_common.Color.borderColor()};
        #                 }}
        #                 """
        self.setStyleSheet(None)

    def enable_close(self):
        """enables the close button on the input widget (keyboard only usually)"""
        if self._close_button_widget:
            # already visible
            return
        size = self._getIconSize()
        icon = gremlin.ui.ui_common.load_icon("mdi.delete")
        self._close_button_widget = QtWidgets.QPushButton()
        self._close_button_widget.setIcon(icon)
        self._close_button_widget.setFixedSize(size, size)
        self._close_button_widget.clicked.connect(self._close_button_cb)
        # insert in last position
        self._title_icon_layout.addWidget(self._close_button_widget)

    def disable_close(self):
        """enables the close button on the input widget (keyboard only usually)"""
        if self._close_button_widget and Shiboken.isValid(self._close_button_widget):
            self._title_icon_layout.removeWidget(self._close_button_widget)
            self._close_button_widget = None

    def enable_repeater(self):
        # enables the repeater container
        self._repeater_enabled = True
        self._update_repeater()

    def disable_repeater(self):
        # disables the repeater container
        self._repeater_enabled = False
        self._update_repeater()

    def enable_edit(self):
        """enables the edit button on the input widget (keyboard only usually)"""

        # we avoid using setVisible() because of the QT event wiring
        if self._edit_button_widget:
            # already visible
            return
        size = self._getIconSize()
        icon = gremlin.ui.ui_common.Icons.gearIcon()
        self._edit_button_widget = QtWidgets.QPushButton()
        self._edit_button_widget.setIcon(icon)
        self._edit_button_widget.setToolTip("Configure")
        self._edit_button_widget.setFixedSize(size, size)
        self._edit_button_widget.clicked.connect(self._edit_button_cb)

        # insert next to last button
        index = len(gremlin.util.get_layout_widgets(self._title_icon_layout))
        if index > 0:
            index -= 1
        self._title_icon_layout.insertWidget(index, self._edit_button_widget)

    def disable_edit(self):
        """enables the edit button on the input widget (keyboard only usually)"""
        if self._edit_button_widget and Shiboken.isValid(self._edit_button_widget):
            # remove it
            self._title_icon_layout.removeWidget(self._edit_button_widget)
            self._edit_button_widget = None

    def create_action_icons(self, input_item: InputItem):
        """Creates the label of this instance.

        Renders the text representing the instance's name as well as
        icons of actions associated with it.

        :param profile_data the profile.InputItem object associated
            with this instance
        """

        if not self._icons_dirty:
            return

        self._icons_dirty = False

        assert isinstance(input_item, InputItem), "invalid input item"

        widget, layout = gremlin.ui.ui_common.getGridContainer()
        layout.addWidget(QtWidgets.QWidget(), 0, 0)
        layout.setColumnStretch(0, 1) # right align the icons
        self._action_icon_widget.setWidget(widget)

        if input_item.containers:
            # Create the actual icons

            # syslog.debug(f"creating action icons for input item: {input_item.display_name} [{input_item.id}] container model id: [{input_item.containers.id}] count: [{len(input_item.containers)}]")
            row = 0
            col = 1
            max_col = 5
            size = self._getIconSize()
            for container in input_item.containers:
                actions = container.getActions()
                for action in actions:
                    if action is not None:
                        widget = ui_common.ActionLabel(action)
                        widget.setMaximumWidth(size)
                        widget.setMaximumHeight(size)
                        layout.addWidget(widget, row, col)
                        col += 1
                        if col > max_col:
                            col = 1
                            row += 1

            # self._setWidgetHeight(self._action_container_widget, rh * (row + 1))

        else:
            label = QtWidgets.QLabel("∅", alignment=QtCore.Qt.AlignmentFlag.AlignRight)
            font = label.font()
            font.setPixelSize(24)
            label.setFont(font)
            label.setToolTip("No mappings found")
            layout.addWidget(label, 0, 1)
            #self._setWidgetHeight(self._action_container_widget, rh)

    def clear_action_icon(self, input_item, action_to_remove):
        """delete an action icon"""

        widget, layout = gremlin.ui.ui_common.getGridContainer()
        layout.addWidget(QtWidgets.QWidget(), 0, 0)
        layout.setColumnStretch(0, 1)
        self._action_icon_widget.setWidget(widget)
        row = 0
        col = 1
        max_col = 5
        # rh = self._getRowHeight()
        if input_item.containers:
            for container in input_item.containers:
                action_sets = container.get_action_sets()
                if action_sets:
                    for actions in [a for a in action_sets if a is not None]:
                        for action in actions:
                            if action is not None and action != action_to_remove:
                                layout.addWidget(ui_common.ActionLabel(action), row, col)
                                col += 1
                                if col > max_col:
                                    col = 1
                                    row += 1

                else:
                    for actions in [a for a in container.action_sets if a is not None]:
                        for action in actions:
                            if action is not None and action != action_to_remove:
                                layout.addWidget(ui_common.ActionLabel(action), row, col)
                                col += 1
                                if col > max_col:
                                    col = 1
                                    row += 1

            #self._setWidgetHeight(self._action_container_widget, rh * (row + 1))
        else:
            layout.addWidget(
                QtWidgets.QLabel("∅", alignment=QtCore.Qt.AlignmentFlag.AlignRight),
                0,
                1,
            )
            #self._setWidgetHeight(self._action_container_widget, rh)

    def findAction(self, action):
        """true if the action is found in our containers"""
        if self.input_item and self.input_item.containers:
            for container in self.input_item.containers:
                action_sets = container.get_action_sets()
                if action_sets:
                    for action_set in action_sets:
                        if action_set:
                            if action in action_set:
                                return True
        return False

    def mousePressEvent(self, event):
        """Emits the input_item_changed event when this instance is
        clicked on by the mouse.

        :param event the mouse event
        """
        if not self.selected:
            # request the item get selected
            el = gremlin.event_handler.EventListener()
            el.select_input.emit(self._input_item.device_guid, self._input_item.input_type, self._input_item.input_id, False, False, False, None)
            # self.setSelected(True)
            # self.selected = True
            # self.selected_changed.emit(self)

    QtCore.Slot()

    def _close_button_cb(self):
        """fires the closed event when the close button has been pressed"""

        if self._confirm_delete_callback:
            if not self._confirm_delete_callback(self._input_item):
                # request failed
                return

        # prompt
        ui = gremlin.shared_state.ui
        result = gremlin.ui.ui_common.ConfirmBox(prompt="Remove this input?", parent=ui)
        if not result:
            return

        # remove the tracker objects
        widget_tracker = gremlin.ui.ui_common.StateTracker()
        device_guid = self._device_guid
        input_type = self._input_type
        input_id = self._input_id
        widget_tracker.unregisterAxisState(device_guid, input_type, input_id)
        widget_tracker.unregisterButtonState(device_guid, input_type, input_id)

        self.closed.emit(self)

    QtCore.Slot()

    def _edit_button_cb(self):
        """edit button clicked"""
        self.edit.emit(self)

    QtCore.Slot()

    def _curve_button_cb(self, widget):
        self.edit_curve.emit(self)

    QtCore.Slot()

    def _input_button_cb(self):
        # toggle input state
        self.input_item.enabled = not self.input_item.enabled

    @QtCore.Slot()
    def _calibration_button_cb(self, widget):
        # open the calibration button for this input
        dialog = gremlin.ui.axis_calibration.CalibrationDialogEx(self.input_item)
        dialog.exec()
        self.input_item.calibration.copyFrom(dialog.action_data)
        self._update_axis_icons()

    QtCore.Slot()

    def _clear_curve_cb(self, widget):
        self.delete_curve.emit(self)


class InputItemListModel(AbstractCallbackModel):
    """Model storing a device's input item list."""

    def __init__(
        self,
        profile: gremlin.base_profile.Profile,
        device_guid,
        mode: str,
        allowed_types: list = None,
        custom_load_handler: Callable[[object], bool] = None,
        custom_remove_handler: Callable[[object], None] = None,
        custom_clear_handler: Callable = None,
        custom_filter_handler: Callable[[object], bool] = None,
        custom_delete_confirm_handler: Callable = None,
        custom_sort_handler: Callable[[object], tuple] = None,
        show_master_mode: bool = False,
        show_filtered_only: bool = False,
    ):
        """Creates a new instance.

        :param device_data the profile data managed by this model
        :param mode the mode this model manages
        :param custom_load_handler: handler for custom loading of the data
        :param show_master_mode: determines if master mode items are displayed in the model
        :param show_filtered_only: determines if only filtered items are shown in the model
        """
        import gremlin.base_profile
        import gremlin.joystick_handling

        if profile is None:
            raise ValueError("Profile cannot be None")
        assert isinstance(profile, gremlin.base_profile.Profile), "Invalid profile type"
        if device_guid is None:
            raise ValueError("Device guid cannot be None")
        if mode is None:
            raise ValueError("Mode cannot be None")

        device = gremlin.joystick_handling.getDevice(device_guid)
        super().__init__(
            allowed_types=(InputItem,),
            model_description=f"InputItemListModel for mode: [{mode}] device: [{device.name if device else 'n/a'}]",
            filter_callback=custom_filter_handler,
        )

        self._device_guid = device_guid
        self._profile = profile
        self._device_data = profile.getDeviceNode(device_guid)

        if device and device.device_type == DeviceType.Joystick:
            # ensure all possible inputs are pre-loaded for joysticks before filtered
            profile.ensureInputItems(device_guid)

        self._mode = mode
        self._show_master_mode = show_master_mode

        if __debug__:
            if custom_clear_handler is not None and not callable(custom_clear_handler):
                raise ValueError("custom_clear_handler must be a callable")
            if custom_load_handler is not None and not callable(custom_load_handler):
                raise ValueError("custom_update_handler must be a callable")
            if custom_remove_handler is not None and not callable(custom_remove_handler):
                raise ValueError("custom_remove_handler must be a callable")
            if custom_filter_handler is not None and not callable(custom_filter_handler):
                raise ValueError("custom_filter_handler must be a callable")
            if custom_sort_handler is not None and not callable(custom_sort_handler):
                raise ValueError("custom_sort_handler must be a callable")

        self._custom_load_handler = custom_load_handler
        self._custom_clear_handler = custom_clear_handler
        self._custom_remove_handler = custom_remove_handler
        self._custom_delete_confirm_handler = custom_delete_confirm_handler  # return true if the input can be deleted

        if custom_sort_handler:
            self.setSortCallback(custom_sort_handler)
            self._sort_enabled = True
        else:
            if device and device.device_type in (
                DeviceType.Keyboard,
                DeviceType.Midi,
                DeviceType.Osc,
                DeviceType.State,
            ):
                # enable input sorting for state, OSC, MIDI and keyboard only
                self.setSortCallback(self._handle_sort)  # also enables sort

        if device:
            self.refresh(False)

    def _handle_sort(self, items) -> tuple:
        """returns a sort list for the items if a custom handler was not provided"""
        # sort by input sortkey
        if self._can_sort:
            data = [(item, item.sortKey) for item in items]
            data.sort(key=lambda x: x[1])
            # sequence the list
            indices = (data.index(x) for x in data)
            return indices
        return None  # unchanged

    @property
    def display_name(self) -> str:
        """display name for the model"""
        device = gremlin.joystick_handling.getDevice(self._device_guid)
        return f"Input Item Model for: [{device.name}] - filtered inputs: [{len(self._filtered_index_map)}] total inputs: [{len(self._index_map)}]"

    def validate(self, input_item: AbstractInputItem):
        """validates input items as valid for the model based on options"""
        if not input_item:
            assert False, "Input item cannot be NULL"
        input_type = input_item.input_type
        if input_type not in self._allowed_input_types:
            assert False, (
                f"Invalid input item for allowed input types in model.  Got [{input_type.name} - allowed types: [{(it.name for it in self._allowed_input_types)}]"
            )
        match input_type:
            case InputType.State:
                assert isinstance(input_item, gremlin.ui.state_device.StateInputItem), "Invalid type for state input"
            case InputType.Keyboard | InputType.KeyboardLatched:
                assert isinstance(input_item, gremlin.ui.keyboard_device.KeyboardInputItem), "Invalid type for keyboard input"

    @property
    def show_filtered(self) -> bool:
        return self.isFilteredEnabled()

    @show_filtered.setter
    def show_filtered(self, value: bool):
        self.setFilteredEnabled(value)

    @property
    def mode(self):
        """Returns the mode handled by this model.

        :return the mode managed by the model
        """
        return self._mode

    @mode.setter
    def mode(self, mode):
        """Sets the mode managed by the model.

        :param mode the mode handled by the model
        """
        self._mode = mode
        self.refresh()

    def sortKey(self, input_item):
        match input_item.input_type:
            case InputType.JoystickAxis:
                key = (1, input_item.input_id)
            case InputType.JoystickButton:
                key = (2, input_item.input_id)
            case InputType.JoystickHat:
                key = (3, input_item.input_id)
            case _:
                key = (10, input_item.sortKey)
        return key

    def refresh(self, emit=True):
        """override - loads into the data model all the items for the current mode and device (subclass)"""
        import gremlin.base_profile
        import gremlin.config
        # load the items for this mode

        if self._custom_load_handler:
            # use our custom handler to update the model data
            self._custom_load_handler(self)
            return

        self.pushSuspend()
        try:
            registry = gremlin.shared_state.current_profile.registry
            device_guid = self._device_guid
            mode = self.mode

            source_index = 0

            device: dinput.DeviceSummary = gremlin.joystick_handling.getDevice(device_guid)

            # load initial inputs from the registry
            allowed_types = [
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat,
            ]

            input_items = registry.getInputItems(device_guid, mode, input_type=allowed_types)

            if input_items and device.device_type in (
                DeviceType.Joystick,
                DeviceType.VJoy,
            ):
                # sort by axes and buttons
                # for item in input_items:
                #     syslog.info(f"Input item: {item} key: {item.sortKey}")
                #     a,b = item.sortKey
                #     if b is None:
                #         pass

                input_items.sort(key=lambda x: self.sortKey(x))

            self.clear()  # rebuild the list
            source_index = 0
            for item in input_items:
                # process all possible inputs and build the filtered list vs the full list (source)
                self.setItemAt(source_index, item)
                source_index += 1
            if self._show_master_mode:
                master_mode = gremlin.shared_state.master_mode
                if master_mode in self._device_data.modes:
                    # older profile may not have master mode defined until saved
                    input_items = registry.getInputItems(device_guid, master_mode)
                    for input_item in input_items:
                        self.place(input_item, source_index)
                        source_index += 1

            # apply sort/filter
            self.applyFilter(emit=False)

        finally:
            self.popSuspend()

        assert len(self._index_map) == len(self._item_map), "Invalid mapping detected"

        if emit:
            self.trigger()

    def indexOfInputItem(self, input_item: InputItem):
        """gets the index of the input item in the model (unfiltered)"""
        return self.indexOf(input_item)

    def indexOfUnfilteredInputItem(self, input_item: InputItem):
        """gets the index of the input item in the model (filtered)"""
        return self.unfilteredItemAt(input_item)

    def hasInputItem(self, input_item: InputItem):
        """true if the model contains the input item (unfiltered)"""
        return self.unfilteredIndexOf(input_item) != -1

    def visibleInputItem(self, input_item: InputItem):
        """true if the filtered model contains the item"""
        return self.indexOf(input_item) != -1

    def getInputItemAt(self, index: int):
        """gets the input item as the given index"""
        if index in self._index_map:
            return self._index_map[index]
        return None

    def getInputItemIndices(self, input_item: InputItem) -> tuple[int, int]:
        """gets the filterd and unfiltered indices for the input = the returned index values are -1 if the item is not found"""
        filtered_index = self.indexOf(input_item)
        unfiltered_index = self.unfilteredIndexOf(input_item)
        return (filtered_index, unfiltered_index)

    def isIndexVisible(self, index: int) -> bool:
        """true if the item as the specified index should be visible (meaning, index is valid in filtered list)"""
        return self.itemAt(index) is not None

    def action_id_to_index(self, action_id):
        """get the model index containing the action id"""

        if action_id:
            # find the row by action_id
            for index in range(self.rows()):
                input_item: InputItem = self.itemAt(index)
                for container in input_item.containers:
                    for action_list in container.action_sets:
                        for action_data in action_list:
                            if action_data.action_id == action_id:
                                return index

        # not found
        return -1

    def event_to_index(self, event):
        """Converts an event to a model index.

        :param event the event to convert
        :return index corresponding to the event's input
        """

        input_items = self._device_data.modes[self._mode]

        offset_map = dict()
        offset_map[InputType.Keyboard] = 0
        offset_map[InputType.JoystickAxis] = len(input_items.config[InputType.Keyboard])
        offset_map[InputType.JoystickButton] = offset_map[InputType.JoystickAxis] + len(input_items.config[InputType.JoystickAxis])
        offset_map[InputType.JoystickHat] = offset_map[InputType.JoystickButton] + len(input_items.config[InputType.JoystickButton])
        offset_map[InputType.KeyboardLatched] = offset_map[InputType.JoystickHat] + len(input_items.config[InputType.JoystickHat])
        offset_map[InputType.OpenSoundControl] = offset_map[InputType.KeyboardLatched] + len(input_items.config[InputType.KeyboardLatched])
        offset_map[InputType.Midi] = offset_map[InputType.OpenSoundControl] + len(input_items.config[InputType.OpenSoundControl])

        if event.event_type in (
            InputType.JoystickAxis,
            InputType.JoystickButton,
            InputType.JoystickHat,
        ):
            # Generate a mapping from axis index to linear axis index
            # axis_index_to_linear_index = {}
            item: InputItem
            item_found: InputItem = None
            index: int

            for index, item in self.getFilteredMap():
                if item.input_type == event.event_type and item.input_id == event.identifier:
                    item_found = item
                    break
            if item_found:
                return index

            return 0

        else:
            return offset_map[event.event_type] + event.identifier - 1

    def __len__(self):
        return self.rows()


class InputItemListView(AbstractView):
    """View displaying the contents of an InputItemListModel. Used in the left panel of the main UI to display inputs."""

    updated = Signal()  # fires when the data is updated

    # Conversion from input type to a display name
    type_to_string = {
        InputType.JoystickAxis: "Axis",
        InputType.JoystickButton: "Button",
        InputType.JoystickHat: "Hat",
        InputType.Keyboard: "",
        InputType.KeyboardLatched: "(latched)",
        InputType.OpenSoundControl: "OSC",
        InputType.Midi: "Midi",
    }

    def __init__(
        self,
        parent=None,
        name="Not set",
        custom_widget_handler: Callable = None,
        selection_changed_handler: Callable[[InputItemWidget, InputItemWidget]] = None,
        device_guid: dinput.GUID | uuid.UUID | str = None,
        blank_message: str = "No data",
        enable_filter: bool = False,
        model: InputItemListModel = None,
    ):
        """Creates a new input item view instance

        :param parent: the parent of the widget
        :param name: name of the list
        :param custom_widget_handler: (list_view : InputItemListView, index : int, identifier : InputIdentifier, data, parent = None)
        :param selection_changed_handler: handler for widget selection changed (old_widget [none], new_widget [none])
        :param device_id: id of the device the list applies to (optional)
        :param blank_message: text to display if there are no rows in the list

        """
        super().__init__(model=model, parent=parent)

        # default visible supported input types
        self.shown_input_types = [
            InputType.JoystickAxis,
            InputType.JoystickButton,
            InputType.JoystickHat,
            InputType.Keyboard,
            InputType.KeyboardLatched,
            InputType.OpenSoundControl,
            InputType.Midi,
        ]

        if not device_guid:
            raise ValueError("device_guid is required for InputItemListView")
        assert isinstance(model, InputItemListModel), "invalid model for list view - must be an InputItemListModel base type"
        assert gremlin.util.is_ui_thread()

        self.pushSuspended()

        self.name = name
        self._device_guid = device_guid
        self._device = gremlin.joystick_handling.getDevice(device_guid)
        self._current_index = -1  # nothing selected
        self._requested_selected_index = -1  # selection requested (if -1 will use the current index instead
        self.custom_widget_handler = custom_widget_handler
        self._selection_change_callbacks = []

        self._last_selected_widget: InputItemWidget = None  # holds a reference to the last widget selected in the list

        self._blank_message = blank_message
        self._enable_filter = enable_filter
        self.setMinimumWidth(200)

        # Create required UI items
        self.main_layout = QtWidgets.QVBoxLayout(self)

        if enable_filter:
            self._warning_widget = gremlin.ui.ui_common.QWarningWidget(
                text="Some inputs are currently filtered",
                icon=gremlin.ui.ui_common.Icons.warningIcon(gremlin.ui.ui_common.Color.blueColor()),
                tooltip="One or more inputs in this list are currently filtered.  Change the filter settings to show them.",
            )
            self.main_layout.addWidget(self._warning_widget)
        else:
            self._warning_widget = None

        # use a stack to display either the inputs or no data
        self._stacked_widget = QtWidgets.QStackedWidget()
        self.main_layout.addWidget(self._stacked_widget)

        self._scroll_area = QtWidgets.QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        # self._scroll_area.verticalScrollBar().valueChanged.connect(self._on_scrollbar_value_changed)

        self._scroll_widget, self._scroll_layout = gremlin.ui.ui_common.getVContainer()
        self._scroll_widget.setContentsMargins(2, 2, 2, 2)

        # Configure the scroll area
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setWidget(self._scroll_widget)
        self._scroll_spacer_widget = None  # spacer widget to move items up if too few

        # Add the scroll area to the main layout
        self.main_layout.addWidget(self._scroll_area)

        el = gremlin.event_handler.EventListener()
        # el.mapping_changed.connect(self._mapping_changed)
        el.sync_input.connect(self._sync_input)

        self._drawn_once = False  # true if the list has been redrawn at least once
        self._redraw_lock = False

        self._widget_map = {}  # map of input item to input widget [model index : int] -> inputitemwidget
        self._input_item_map = {}  # map of input item to input widget [input_item] -> inputitemwidget

        self._blank_message_widget = gremlin.ui.ui_common.QFrameBox(blank_message, css=gremlin.ui.ui_common.Color.cssNormalBox())

        self._stacked_widget.addWidget(self._blank_message_widget)  # index 0
        self._stacked_widget.addWidget(self._scroll_area)  # index 1

        # initial display is blank
        self.showBlank()

        if selection_changed_handler:
            self.addSelectionChangeCallback(selection_changed_handler)

        # load data and update
        self.popSuspended(emit=False)

    def itemAt(self, index: int):
        """gets the input item as the specified index, None if the index is invalid or the model isn't set"""
        if self.model is not None:
            return self.model.itemAt(index)
        return None

    def indexOf(self, input_item: InputItem):
        """gets the index of the input item if in the model"""
        if self.model is not None:
            return self.model.indexOf(input_item)
        return -1

    def addSelectionChangeCallback(self, callback: Callable):
        """adds a selection change callback"""
        assert callable(callback), "invalid callback"
        if callback not in self._selection_change_callbacks:
            self._selection_change_callbacks.append(callback)

    def removeSelectionChangeCallback(self, callback: Callable):
        """removes a selection change callback"""
        if callback in self._selection_change_callbacks:
            self._selection_change_callbacks.remove(callback)

    def _fireSelectionChangeCallbacks(self, old_widget: InputItemWidget, new_widget: InputItemWidget, emit=True):
        """fires the selection change callbacks"""
        for callback in self._selection_change_callbacks:
            callback(old_widget, new_widget, emit)

    def count(self) -> int:
        """gets the number of input items displayed"""
        return len(self._widget_map)

    def setBlankMessage(self, message: str = None):
        """sets the blank message, set to None to disable"""
        gremlin.util.InvokeUiMethod(self._setblankMessage_ui, message)

    def _setBlankMessage_ui(self, message: str):
        self._blank_message = message
        self._blank_message_widget.setText(message or "")
        self._stacked_widget.setCurrentIndex(0 if message is not None else 1)

    def showBlank(self):
        """displays a blank page"""
        self._stacked_widget.setCurrentIndex(0)

    def showContent(self):
        """displays the content page"""
        self._stacked_widget.setCurrentIndex(1)

    def _sync_input(self, input_item):
        gremlin.util.InvokeUiMethod(self._sync_input_ui, input_item)

    def _sync_input_ui(self, input_item):
        if not Shiboken.isValid(self) or not Shiboken.isValid(self._scroll_layout):
            return

        # warning display for fitered inputs
        if self._model:
            if self._warning_widget:
                self._warning_widget.setVisible(self._model.isFiltered())
        else:
            # no model - nothing to do
            if self._warning_widget:
                self._warning_widget.setVisible(False)
            self._clear_widgets()
            return

        if self.model.hasInputItem(input_item):
            index = self.model.indexOfInputItem(input_item)

            self.scrollToIndex(index)

            # shenanigans to have the selected input visible in the scroll area of inputs
            # the size() on the widget returns the wrong size so each widget has an "actual size" function trapping the event
            # so we get the correct height as rendered
            # then we compute the pixel offset and tell the scroll area to scroll to that pixel height
            if self._widget_map:
                key = next(iter(self._widget_map))  # first widget
                widget = self._widget_map[key]  # gremlin.util.get_layout_widgets(self._scroll_layout)
                if hasattr(widget, "widget_height"):
                    # not in label mode
                    if widget.widget_height is not None:
                        h = 0
                        for i, widget in enumerate(self._widget_map.values()):
                            h += widget.widget_height
                            if i == index:
                                target_widget = widget
                                break
                        self._scroll_area.ensureVisible(0, h)
                        self._scroll_area.ensureWidgetVisible(target_widget)

    def scrollToInput(self, input_item):
        self._sync_input(input_item)

    @property
    def current_index(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int, emit=True):
        """sets the current index"""
        if self._current_index != index:
            widget = self.widget(index)
            if widget:
                self._select_item_ui(index, emit)

    @property
    def current_device(self):
        """gets the device associated with this list view"""
        return self._device

    def _mapping_changed(self, item_data):
        gremlin.util.InvokeUiMethod(self._mapping_changed_ui, item_data)  # to UI thread if needed

    def _mapping_changed_ui(self, item_data):
        """mapping changed"""
        for index in range(self.model.rows()):
            data = self.model.data(index)
            if data != item_data:
                continue
            self.redraw_index(index)

    def limit_input_types(self, types):
        """Limits the items shown to the given types.

        :param types list of input types to display
        """
        self.shown_input_types = types
        self.model.setAllowedInputTypes(types)  # changes the model to show only the selected types

    def removeRow(self, index):
        """removes the item at the given index"""
        if self.model.removeRow(index):
            # pick a new index if the item was selected
            rowcount = self.model.rows()
            if rowcount == 0:
                new_index = -1
            else:
                # reselect the item at the new index if possible
                new_index = index
                if new_index >= rowcount:
                    new_index = 0

            self._select_item_ui(new_index)

    def getWidgets(self):
        """gets the list of widgets in the list view"""
        if not Shiboken.isValid(self._scroll_layout):
            return
        widgets = gremlin.util.get_layout_widgets(self._scroll_layout)
        return widgets

    def widget(self, index):
        """gets a specific widgets at the given index"""
        if index != -1:
            if index in self._widget_map:
                return self._widget_map[index]
        return None

    def getWidgetForInputItem(self, input_item: InputItem):
        """gets the corresponding widget for the given input item"""
        index = self.model.indexOf(input_item)
        return self.widget(index)

    def getInputItemIndex(self, input_item: InputItem):
        """gets the index in the list of a particular input"""
        return self.model.indexOf(input_item)

    def getWidgetAt(self, index: int) -> InputItemWidget:
        """gets the widget at the given index"""
        return self.widget(index)

    def scrollToWidget(self, widget):
        """scrolls to a specific widget in the list"""
        if widget is not None:
            self._scroll_to_item(widget)

    def scrollToIndex(self, index):
        """scrolls to a specific index"""
        widget = self.widget(index)
        if widget is not None:
            self._scroll_to_item(widget)

    def _clear_widgets(self):
        """clears the scroll area widgets"""
        widgets = list(self._widget_map.values())
        self._widget_map.clear()
        self._input_item_map.clear()
        for widget in widgets:
            gremlin.util.delete_widget(widget)
        gremlin.util.clear_widget_references(self)

    def _cleanup_ui(self):
        """clears this list view"""
        self._clear_widgets()

    def create_ui(self):
        """creates or recreates the contents of the input list view (left side input selector)"""

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_ui_level(1)
        if verbose:
            syslog.info(f"InputItemListView: device:[{self.current_device.name}] create ui")
        try:
            # self.setUpdatesEnabled(False)
            # self.setUpdatesEnabled(False)  # disable updates

            # remember the currently selected input
            selected_input_item = self.getSelectedItem()

            with QtCore.QSignalBlocker(self):
                # clear the widgets
                # self._clear_widgets()

                # list of existing input items in the list view that have widgets
                existing_input_items = list(self._input_item_map.keys())
                self._widget_map.clear()  # rebuild the index to widget map

                if self.model is not None:
                    if verbose:
                        syslog.info(
                            f"ListView: create widgets for [{self.model.display_name}] - included: [{self.model.filteredCount()}] unincluded: [{self.model.unfilteredCount()}]"
                        )

                    data = list(self.model.getFilteredMap())
                    for model_index, input_item in data:
                        assert isinstance(input_item, InputItem), "invalid input item"
                        assert isinstance(model_index, int), "invalid index"
                        new_widget = True  # assume creating a new widget

                        if __debug__:
                            time_start = time.perf_counter()

                        # indicate input item is processed from the list of existing inputs
                        if input_item in existing_input_items:
                            existing_input_items.remove(input_item)
                            new_widget = False

                            # re-use existing
                            if input_item in self._input_item_map:
                                widget = self._input_item_map[input_item]
                                self._scroll_layout.removeWidget(
                                    widget
                                )  # remove the existing widget because position may have changed so it's added at the right spot

                        else:
                            # create new input widget
                            identifier = InputIdentifier(
                                input_item.input_type,
                                input_item.device_guid,
                                input_item.input_id,
                                input_item.device_type,
                                input_item.input_name or input_item.display_name,
                                is_axis=input_item.is_axis,
                                is_button=input_item.is_button,
                                input_item=input_item,
                            )

                            # syslog.info(f"\t[{model_index}]  {input_item.display_name}")

                            if self.custom_widget_handler:
                                # get the widget from the custom handler
                                widget: InputItemWidget = self.custom_widget_handler(
                                    self,
                                    model_index,
                                    identifier,
                                    input_item,
                                    parent=self._scroll_layout,
                                )
                                assert isinstance(widget, InputItemWidget), "custom handler returned an invalid widget "
                                widget.addSelectionChangeCallback(self._handle_widget_selection_changed)  # hook selection changes
                                widget.index = model_index
                                assert widget is not None, "Custom widget handler didn't return a widget"
                            else:
                                # create a standard input widget
                                widget = InputItemWidget(
                                    input_item,
                                    selection_changed_callback=self._handle_widget_selection_changed,
                                )
                                if input_item.input_type == InputType.JoystickAxis:
                                    prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
                                    widget.setIcon(f"{prefix}joystick.png")
                                elif input_item.input_type == InputType.JoystickButton:
                                    widget.setIcon("mdi.gesture-tap-button")
                                elif input_item.input_type == InputType.JoystickHat:
                                    widget.setIcon("ei.fullscreen")

                            input_item.setInputWidget(widget)  # keep a reference to the input widget

                        widget.index = model_index
                        if new_widget:
                            # handle new widget updates
                            widget.create_action_icons(input_item)
                            # set the description based on the mapping description
                            widget.setDescription(input_item.description)
                            # id update
                            widget._update_container_id()

                            widget.edit.connect(self._create_edit_callback(model_index))
                            widget.edit_curve.connect(self._create_edit_curve_callback(model_index))
                            widget.delete_curve.connect(self._create_delete_curve_callback(model_index))
                            widget.closed.connect(self._create_closed_callback(model_index))

                            if verbose:
                                syslog.info(
                                    f"\t added input for: [{model_index:02d}] type: {InputType.to_string(input_item.input_type)} input id: [{input_item.input_id}] id: {input_item.id}"
                                )

                            # add new widget to the input map
                            self._input_item_map[input_item] = widget

                        if verbose and __debug__:
                            time_end = time.perf_counter()
                            elapsed = time_end - time_start
                            syslog.info(
                                f"\t added input for: [{model_index:02d}] type: {InputType.to_string(input_item.input_type)} input id: [{input_item.input_id}] id: {input_item.id} time: [{elapsed:.6f}]"
                            )

                        # store a reference to this widget for the model
                        self._widget_map[model_index] = widget

                        self._scroll_layout.addWidget(widget)

                        widget.index = model_index  # assigned index from the model

                    if existing_input_items:
                        # some widgets were removed - delete them
                        for input_item in existing_input_items:
                            if input_item in self._input_item_map:
                                widget = self._input_item_map[input_item]
                                widget.hide()
                                self._scroll_layout.removeWidget(widget)
                                gremlin.util.delete_widget(widget)

                                del self._input_item_map[input_item]

                    # move the spacer to the bottom of the scroll area
                    if self._scroll_spacer_widget:
                        self._scroll_layout.removeItem(self._scroll_spacer_widget)
                    else:
                        # no spacer created yet
                        self._scroll_spacer_widget = QtWidgets.QSpacerItem(
                            0,
                            0,
                            QtWidgets.QSizePolicy.Expanding,
                            QtWidgets.QSizePolicy.Expanding,
                        )

                    # re-add at the bottom
                    self._scroll_layout.addSpacerItem(self._scroll_spacer_widget)

            count = len(self._widget_map)
            if count == 0:
                if verbose:
                    syslog.info("\tFound no content to display.")
                self.showBlank()
            else:
                self.showContent()

            # handle default selection on view population
            if self._widget_map:
                # has widgets
                index = self._requested_selected_index
                if index == -1:
                    index = self._current_index
                if index == -1:
                    index = 0
                self._select_item_ui(index)

        finally:
            if selected_input_item is not None:
                # select the old input that was previously selected before the update if it's still there
                index = self.indexOf(selected_input_item)
                if index != -1:
                    if self._current_index != index:
                        self.selectItemAt(index)

    def redraw(self, force: bool = False):
        # assert inspect.stack()[1].function == "_fireChanged", "redraw should only be called due to a model trigger"
        gremlin.util.InvokeUiMethod(self._redraw_ui, force)  # ensure on UI thread

    def _redraw_ui(self, force: bool = False):
        """Redraws the entire view.  must be on UI thread"""

        """Redraws the entire model.
        """

        if gremlin.shared_state.is_redraw_suspended():
            return  # don't redraw

        widget_count = 0  # number of displayed input item widgets
        try:
            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_ui or config.verbose_mode_inputs

            changed = self.modelChanged
            if not changed:
                # compare rows
                model_count = self.model.count()  # widgets that should be displayed
                widget_count = self.getInputItemWidgetCount()
                if model_count == widget_count:
                    # check to see if the widgets match the inputs
                    for input_item in self.model.getFilteredItems():
                        if input_item.id not in self._widget_map:
                            force = True
                            changed = True
                            break
                else:
                    changed = True

            if not force and not changed:
                return  # do not update

            if verbose:
                syslog.info("InputItemListView: redraw")

            if force or changed:
                # create if the first time or if the model changed
                self.create_ui()
                self._drawn_once = True
                widget_count = self.getInputItemWidgetCount()

            if __debug__:
                model_count = self.model.count()  # widgets that should be displayed
                assert self._drawn_once and (widget_count == model_count), "InputItemListView model and UI are not synchronized (mismatched items)"

            if self.current_index == -1 and model_count > 0:
                self.setCurrentIndex(0)  # pick the first item if nothing is selected now

            # reselect input and make visible
            widget = self.widget(self.current_index)
            if widget:
                if not widget.selected:
                    # ensure selected
                    widget.setSelected(True, emit=False)
                self.scrollToWidget(widget)
        finally:
            # toggle blank/content view
            if widget_count == 0:
                self.showBlank()
            else:
                self.showContent()

    def getInputItemWidgetCount(self):
        """gets the number of input widgets in the list"""
        return len(self._widget_map)

    def redraw_index(self, index: int):
        if not gremlin.shared_state.is_running:
            gremlin.util.InvokeUiMethod(self._redraw_index_ui, index)  # ensure on UI thread

    def _redraw_index_ui(self, index: int):
        """Redraws the view entry at the given index.

        :param index the index of the entry to redraw
        """

        if not Shiboken.isValid(self):
            # garbage collected
            return

        if gremlin.shared_state.is_redraw_suspended():
            return

        if self.model is None:
            return

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)

        data = self.model.data(index)
        if data is not None and data.id in self._widget_map:
            widget = self._widget_map[data.id]
            if self.custom_widget_handler:
                widget.update_display()
            else:
                widget.create_action_icons(data)
                widget.setDescription(data.description)
                widget.setInputDescription(data.display_name)

            if verbose:
                syslog.info(f"InputItemListView: redraw input item: index: [{index}] id: {data.id}")
        else:
            if verbose:
                syslog.info(f"InputItemListView: redraw input item: widget not found for index: [{index}]")

    def _create_edit_callback(self, index: int):
        """Creates a callback handling the edit action of an input widget

        :param index the index of the item to create the callback for
        :return callback to be triggered when the item at the provided index
            is selected
        """
        return lambda x: self._edit_item_cb(index)

    def _create_edit_curve_callback(self, index: int):
        return lambda: self._edit_curve_item_cb(index)

    def _create_delete_curve_callback(self, index: int):
        return lambda: self._delete_curve_item_cb(index)

    def _create_closed_callback(self, index: int):
        """Creates a callback handling the close action of an input widget

        :param index the index of the item to create the callback for
        :return callback to be triggered when the item at the provided index
            is selected
        """

        # get the index for this widget
        return lambda x: self._close_item_cb(index)

    def _close_item_cb(self, index):
        """remove a particular input"""

        widget: QtWidgets.QWidget = self.widget(index)
        if widget.receivers(widget.closed):
            # if isSignalConnected(widget, "closed(InputIdentifier)"):
            widget.closed.emit(self, index)
            return

        # select the widget if it's not selected
        data = self.model.data(index)
        if data and (data.containers or data.input_type == InputType.KeyboardLatched):
            # prompt confirm
            result = gremlin.ui.ui_common.ConfirmBox(
                "Delete confirmation",
                "This will delete associated actions for this entry.\nAre you sure?",
            )
            if result:
                self._confirmed_close(index)
        else:
            # no need to confirm
            self._confirmed_close(index)

    def _confirmed_close(self, index):
        self.removeRow(index)
        _el = gremlin.event_handler.EventListener()
        # el.device_mapping_changed.emit(self._device_guid)
        self.item_closed.emit(self, index, self.model.data(index))  # widget, index, data

        # select prior item
        if index > 0:
            index -= 1
            data = self.model.data(index)
            if data:
                self._select_item_ui(index)

    def _edit_item_cb(self, index: int):
        """emits the edit event along with the item being edited"""
        self.item_edit.emit(self, index, self.model.data(index))  # widget, index, data

    def _edit_curve_item_cb(self, index: int):
        input_item = self.model.data(index)
        self.item_edit_curve.emit(self, index, input_item)
        el = gremlin.event_handler.EventListener()
        el.curve_added.emit(input_item)

    def _delete_curve_item_cb(self, index: int):
        input_item = self.model.data(index)
        self.item_delete_curve.emit(self, index, self.model.data(index))
        el = gremlin.event_handler.EventListener()
        el.curve_deleted.emit(input_item)

    def _update_value_changed(self, index: int, value: float):
        self.item_input_value_changed.emit(self, index, self.model.data(index), value)

    def update_item(self, index):
        """update the widget with new data"""
        widget = self.widget(index)
        if not widget:
            self._select_item_ui(index)
            widget = self.widget(index)
        if widget:
            widget.update_display()

    def unselect_item(self, index):
        """unselects an item"""
        pass

    def _handle_widget_selection_changed(self, widget: InputItemWidget):
        # selection change can take a while if the UI has to create new components
        if widget.selected and widget.index != self._current_index:
            # only process selection if not selected and not already current
            wm = WorkManager()
            wm.submit(callback=self._handle_widget_selection_changed_worker, args=widget)

    def _handle_widget_selection_changed_worker(self, args):
        """called when a widget in the list changes selection state (selected or unselected)"""
        verbose = gremlin.config.Configuration().verbose_mode_ui_level(3)
        if verbose:
            syslog.info("select input start")
        self._selecting_flag = True
        gremlin.util.InvokeUiMethod(self._execute_widget_selection_changed, args)
        while self._selecting_flag:
            QThread.sleep(0)  # workers are on QThread, not regular threads
        if verbose:
            syslog.info("select input complete")

    def _execute_widget_selection_changed(self, widget: InputItemWidget):

        try:
            assert gremlin.util.is_ui_thread(), "must run on Ui thread"
            verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
            if verbose:
                syslog.info(
                    f"InputListView: input widget selected callback: [{widget.input_item.device_name}] [{widget.input_item.display_name}]  selected [{widget.selected}]"
                )

            if widget.selected:
                # handle selected
                config = gremlin.config.Configuration()
                verbose = config.verbose_mode_inputs or config.verbose_mode_ui
                index = widget.index
                # deselect the old item in the list
                if self._current_index != index:
                    old_widget = self._last_selected_widget
                    if old_widget:
                        old_widget.setSelected(False, False)  # de-select old
                        self.item_selected.emit(self._current_index, False)  # trigger the event

                    self._current_index = index  # update to the new selected index in the list
                    self._last_selected_widget = widget  # store the new reference
                    if verbose:
                        syslog.info(f"InputItemListView: trigger selection for index [{index}]")
                    self._fireSelectionChangeCallbacks(old_widget, widget, emit=False)  # handle callbacks for selection change
                    self.item_selected.emit(index, True)  # trigger the list selection
        finally:
            self._selecting_flag = False

    def selectItemAt(self, index, emit=True, force=False, user_selected=False):
        """selects an input by index"""
        gremlin.util.InvokeUiMethod(self._select_item_ui, index, emit, force, user_selected)

    def selectInputItem(self, input_item: InputItem, emit=True, force=False, user_selected=False):
        """selects the input"""
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_inputs or config.verbose_mode_ui
        filtered_index, index = self.getInputItemIndices(input_item)
        if filtered_index == -1:
            # auto-flip to index if it exists
            filtered_index = index
        if index != -1:  # found
            if verbose:
                syslog.info(f"InputItemListView: select input [{input_item.display_name}] index [{index}]")
            gremlin.util.InvokeUiMethod(self._select_item_ui, index, emit, force, user_selected)
        else:
            if verbose:
                syslog.info(f"InputItemListView: select input [{input_item.display_name}] FAIL - input not found in the list]")

    def _select_item_ui(self, index, emit=True, force=False, user_selected=False):
        """Handles selecting a specific item.  this is called whenever an input item is selected

        :param index:the index of the item being selected
        :param emit: flag indicating whether or not a signal is to be emitted when the item is being selected
        :param force: forces an update
        """

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_inputs or config.verbose_mode_ui_level(1)

        if verbose:
            syslog.info(f"InputItemListView: request to select input index: [{index}]")
        if not Shiboken.isValid(self._scroll_area):
            return

        model: InputItemListModel = self.model
        if not self._widget_map:
            # no widgets in the list to select - view not populated yet
            if verbose:
                syslog.infog(f"\tno widgets in the input list - requesting index [{index}] when the widgets are loaded")
            self._requested_selected_index = index  # requested selection for when the widget is redrawn
            return

        widget = None  # the widget to select

        # If the index is actually an event we have to correctly translate the
        # event into an index, taking the possible non-contiguous nature of
        # axes into account
        if isinstance(index, gremlin.event_handler.Event):
            event = index
            if event.action_id:
                index = self.mode.action_id_to_index(event.action_id)
            else:
                index = model.event_to_index(event)

        if index == -1:
            # always reset things if the index is the clear value of -1
            force = True

        if not force and self._current_index == index:
            if verbose:
                syslog.info(f"\tindex [{index}] is already selected")
            widget: InputItemWidget = self.widget(index)
            widget.trigger()
            return  # nothing to do if the current index is the same as the new index

        if index == -1:
            # get the first selected widget - if any
            widget = next((w for w in self.self._widget_map.values() if w.selected), None)
            if not widget:
                # select the first one
                widget = self.widget(0)
            if widget:
                index = widget.index

        if not model.isIndexVisible(index):
            if verbose:
                syslog.warning(f"\tindex [{index}] is not visible")
            return

        last_widget = self._last_selected_widget
        if self._current_index == -1 or self._current_index != index:
            if last_widget and Shiboken.isValid(last_widget):
                # deselect prior widget if it can be selected
                if verbose:
                    syslog.info(f"\tdeselect index [{self._current_index}]: {last_widget.input_item.display_name}")
                last_widget.setSelected(False, False)

            # widget to select
            if not widget:
                widget = self.widget(index)

            assert widget is not None, "widget not found in list"
            widget.setSelected(True, emit=True)  # this fires the updates and callbacks via the _handle_widget_selection_changed callback
            self._current_index = index
            self._requested_selected_index = -1  # indicate no more request
            self._last_selected_widget = widget
            self._fireSelectionChangeCallbacks(last_widget, widget)  # trigger updates on selection change if any


            self.ensureVisible(widget)  # ensure the selected widget is visible in the scroll area


        return widget

    def getSelectedItem(self) -> InputItem:
        """gets the currently selected input item"""
        return self.model.itemAt(self._current_index)

    def getSelectedWidget(self) -> InputItemWidget:
        """gets the currently selected input widget"""
        index = self._current_index
        if index in self._widget_map:
            return self._widget_map[index]
        return None

    def clearSelection(self, emit=True):
        widgets = [w for w in gremlin.util.get_layout_widgets(self._scroll_layout)]
        for w in widgets:
            w.setSelected(False, emit=emit)

    def currentIndex(self) -> int:
        """gets the currently selected index, -1 if no selection or list is empty"""
        return self._current_index

    def _create_scroll_callback(self, widget):
        return lambda: self._scroll_to_item(widget)

    def ensureVisible(self, widget):
        """makes the widget visible in the scroll area, if it is not already visible"""
        #gremlin.util.singleShot(self._create_scroll_callback(widget))
        if gremlin.util.is_ui_thread():
            self._scroll_to_item_ui(widget)
        else:
            gremlin.util.InvokeUiMethod(self._scroll_to_item_ui, widget)


    def ensureVisibleIndex(self, index):
        """makes the widget at the given index visible in the scroll area, if it is not already visible"""
        widget = self.widget(index)
        if widget:
            self.ensureVisible(widget)

    def _scroll_to_item(self, widget):
        gremlin.util.InvokeUiMethod(self._scroll_to_item_ui, widget)

    def _scroll_to_item_ui(self, widget):
        # runs on UI thread
        if Shiboken.isValid(self):
            # update layout just in case the widgets have changed size
            self._scroll_widget.layout().activate()

            count = len(self._widget_map)
            bar = self._scroll_area.verticalScrollBar()
            if bar:
                # compute the position of the widget
                y = 0
                for i in range(count):
                    w = self._widget_map[i]
                    if w == widget:
                        break
                    y += w.widget_height
                bar.setValue(y)

    # def _on_scrollbar_value_changed(self, value):
    #     """called when the scroll bar value changes"""
    #     syslog.info(f"scroll bar value changed: [{value}]")

    def __len__(self):
        return self.count()


class ConditionContainer:
    """holds conditions for containers"""

    def __init__(self):
        self._id = gremlin.util.get_guid()  # unique GUID of this container
        self.activation_condition = BaseActivationCondition(ConditionModel(self), ActivationRule.All)  # activation condition that applies to the container
        self.activation_condition.setContainer(self)
        # self._container = None

    @property
    def condition_count(self):
        return len(self.activation_condition.conditions)

    @property
    def id(self):
        return self._id

    def setId(self, value: str):
        """sets the ID"""
        self._id = value

    def setContainer(self, container: AbstractContainer):  # noqa: F405
        assert isinstance(container, AbstractContainer), "invalid container"
        self.activation_condition.setContainer(container)
        # self._container = container

    def get_container(self):
        return self.activation_condition.container
        # return self._container


class AbstractContainer(BaseProfileData, ConditionContainer):
    """Base class for action container related information storage."""

    virtual_button_lut = {
        InputType.JoystickAxis: gremlin.base_buttons.VirtualAxisButton,
        InputType.JoystickButton: None,
        InputType.JoystickHat: gremlin.base_buttons.VirtualHatButton,
        InputType.KeyboardLatched: None,
        InputType.Keyboard: None,
        InputType.OpenSoundControl: None,
        InputType.Midi: None,
    }

    # id_changed = Signal(str, str) # fires when id changes (old_id, new_id)

    # default allowed input types = all
    input_types = InputType.to_list()

    # by default the container works with either axis or momentary inputs
    axis_only = False

    def __init__(self, parent, node=None):
        """Creates a new instance.

        :parent the InputItem which is the parent to this action
        """
        super().__init__(parent)

        self.parent = parent

        self._abstract_container_generating_xml = False  # true if generating
        self._action_sets = ActionSets(self)  # containers contain one or more action sets, each action sets contains a list of action set object
        self.action_model: ContainerModel = None  # set at creation by the parent of this container
        self.custom_action_sets = False  # true if the container uses custom action sets (need a converter to produce action_sets)
        self._condition_enabled = True  # condition flag
        self._virtual_button_enabled = (
            True  # determines if the callbacks can be virtualized or not - if not - the callback is "raw" to the functor - action / container set
        )
        self._virtual_button_user_enabled = True  # determins if callbacks use the virtual button function - user set
        # self.activation_condition = BaseActivationCondition(ConditionModel(self),ActivationRule.All) # activation condition that applies to the container
        # self.activation_condition.setContainer(self)
        self.virtual_button = None
        self.current_view_type = None
        self.parent_node = node
        self.comment = None  # user comment
        self._description = None  # description
        self._callbacks_enabled = True  # callbacks are enabled by default for this container
        self._collapsed = False  # true if the container is collapsed
        self.actionsetParseCallback = None  # callback to use when parsing action set if it has additional data (node), returns an action set
        self.actionsetCustomParseCallback = None  # callback for the complete action set parsing
        self.definition_mode = self.get_mode()

        self._container_changed_callbacks = []  # list of callbacks called when this container changes

        el = gremlin.event_handler.EventListener()
        el.virtual_button_changed.connect(self._virtual_button_changed)

        self._action_sets_callback = None  # callback to return different action sets if needed for containers that do their own thing

        # attached hardware device to this container
        input_item = None
        if isinstance(parent, gremlin.profile_graph.ProfileContainerNode):
            input_item = _get_input_item(parent)
            if not input_item:
                input_item = _get_input_item(parent)

        if not input_item:
            input_item = _get_input_item(parent)
            if input_item is None:
                input_item = _get_input_item(parent)

        self._input_item = input_item
        assert input_item is not None
        # if input_item is not None:
        self.device_guid = input_item.device_guid
        self.device_input_id = input_item.input_id
        self.device_input_type = input_item.input_type
        self.device = gremlin.joystick_handling.getDevice(self.device_guid)

    def _fireChangeCallbacks(self):
        """fires the change callbacks for this container"""
        for callback in self._container_changed_callbacks:
            callback(self)

    def registerChangeCallback(self, callback: Callable):
        """registers a change callback for this container"""
        assert isinstance(callback, Callable), "invalid callback"
        if callback not in self._container_changed_callbacks:
            self._container_changed_callbacks.append(callback)

    def unregisterChangeCallback(self, callback: Callable):
        """unregisters a change callback for this container"""
        assert isinstance(callback, Callable), "invalid callback"
        if callback in self._container_changed_callbacks:
            self._container_changed_callbacks.remove(callback)

    def mapping_changed(self):
        """fires the mapping changed event to notify UI on mapping changes made to this container"""
        self._fireChangeCallbacks()

    @property
    def debug_name(self) -> str:
        """friendly display name"""
        return f"container: [{self.tag}] id: [{str(self.id)}] {self.input_item.debug_name}"

    def getActionsSets(self) -> ActionSets:  # noqa: F405
        return self._action_sets

    def ensureActionSets(self):
        """convert to an action set if needed"""
        if not isinstance(self._action_sets, ActionSets):
            self._action_sets = ActionSets(self)

    def setActionSets(self, value: ActionSets | list):  # noqa: F405
        """sets a custom action set"""
        assert value is not None, "actionsets must be provided"
        self._action_sets = value
        self.ensureActionSets()

    def resetActionSets(self):
        """resets actions sets - override in derived class if the action set default should be different"""
        if self.action_sets:
            # for action_set in self.action_sets:
            #     action_set.clear()
            self.action_sets.clear()

    def dumpActionSets(self, action_sets: list, label=None):
        """dumps the container's action sets to the output"""

        if label:
            syslog.info(f"Container action sets: {label}")
        else:
            syslog.info("Container action sets:")

        if not action_sets:
            syslog.info("\tno action sets found")

        for index, action_set in enumerate(action_sets):
            self.dumpActionSet(action_set, label=f"Action set [{index}]:", indent="\t")

    def dumpActionSet(self, action_set: list, label=None, indent=""):
        """dumps a single action set"""
        if label:
            syslog.info(f"{indent}{label}")
        else:
            syslog.info(f"{indent}Action set:")

        if not action_set:
            syslog.info(f"{indent}\tset is empty")
            return

        empty_sets = [action for action in action_set if not action]
        actions = [action for action in action_set if action]
        syslog.info(f"{indent}\tFound: {len(action_set)} actions, {len(empty_sets)} empty actions, {len(actions)} actions")

        action: AbstractAction
        for index, action in enumerate(action_set):
            if action:
                if hasattr(action, "display_name"):
                    display_name = action.display_name()
                else:
                    display_name = f"class: {action.__class__.__name__}"
                syslog.info(
                    f"{indent}\t\tAction [{index}]: {display_name} id: [{action.id}] priority: [{action.priority}] has conditions: [{action.has_conditions}] is axis: [{action.input_is_axis()}]  is button: [{action.input_is_button()}] enabled: [{action.enabled}]"
                )

    def clear(self):
        """removes all actions from this container"""
        self.action_sets.clear()

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @collapsed.setter
    def collapsed(self, value: bool):
        self._collapsed = value

    @QtCore.Slot(object, object, object)
    def _virtual_button_changed(self, input_item, container, action):
        """called when an action changes its virtual button setting"""
        if self.id == container.id:
            self.create_or_delete_virtual_button()
            el = gremlin.event_handler.EventListener()
            el.condition_changed.emit(self)

    def getActions(
        self,
        action_type_or_list: AbstractAction | list | tuple = None,  # noqa: F405
    ) -> list:
        """gets a list of all the actions in this container, of a particualr type if needed"""
        action_list = []
        action_type_list = []
        if action_type_or_list is not None:
            if hasattr(action_type_or_list, "__iter__"):
                action_type_list = action_type_or_list
            else:
                action_type_list = [action_type_or_list]
        for action_set in self.get_action_sets():
            for action in action_set:
                if action:
                    if action_type_list and type(action) not in action_type_list:
                        continue
                    action_list.append(action)

        return action_list

    def generateGuids(self):
        """called when GUIDs for this container need to be reset so they are unique, such as when pasting or importing. Actions and conditions IDs also need to be reset"""

        tracker = ConditionTracker()

        self._id = gremlin.util.get_guid()  # unique GUID of this container

        for action_set in self.get_action_sets():
            for action in action_set:
                action.setId(gremlin.util.get_guid())
                if hasattr(action, "generateGuids"):
                    action.generateGuids()  # action ID change

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
        """gets the associated input item for this container"""
        return _get_input_item(self.parent)

    @property
    def has_conditions(self):
        """true if the container has conditions defined"""
        return self.activation_condition is not None and len(self.activation_condition.conditions) > 0

    def hasConditions(self):
        """true if the container has a condition or contains actions with conditions"""
        return self.has_conditions or self.has_action_conditions

    @property
    def has_action_conditions(self):
        """true if the container has action conditions defined"""
        for action_set in self.action_sets:
            if action_set:
                for action in action_set:
                    if action.has_conditions:
                        return True

        return False

    @property
    def condition_count(self) -> int:
        """gets the count of container conditions currently defined"""
        if self.activation_condition is not None:
            return len(self.activation_condition.conditions)
        return 0

    @property
    def condition_enabled(self):
        """determines if condition tab is enabled"""
        return self._condition_enabled

    @condition_enabled.setter
    def condition_enabled(self, value):
        """determines if condition tab is enabled"""
        self._condition_enabled = value

    @property
    def virtual_button_enabled(self) -> bool:
        """determines if virtual button tab is enabled and virtual buttons is enabled for functor callbacks"""
        return self._virtual_button_enabled

    @virtual_button_enabled.setter
    def virtual_button_enabled(self, value: bool):
        """determines if virtual button tab is enabled and virtual buttons is enabled for functor callbacks"""
        self._virtual_button_enabled = value

    @property
    def virtual_button_user_enabled(self) -> bool:
        """flag for user enable of the virtual button functionality so the user can decide to use it or not"""
        return self._virtual_button_user_enabled

    @virtual_button_user_enabled.setter
    def virtual_button_user_enabled(self, value: bool):
        self._virtual_button_user_enabled = value

    @property
    def input_display_name(self):
        return f"{gremlin.shared_state.get_device_name(self.device_guid)} {InputType.to_display_name(self.device_input_type)} {self.device_input_id}"

    @property
    def display_name(self) -> str:
        return (
            f"[{self.input_display_name}] action count: [{self.action_model.count() if self.action_model is not None else 0}] description: [{self.description}]"
        )

    @property
    def description(self) -> str:
        return self._description

    @description.setter
    def description(self, value: str):
        self._description = value

    def add_action_set(self, action_set: "ActionSet") -> int:
        """Adds an action set to this container."""
        index = self.action_sets.add(action_set)
        self._fireChangeCallbacks()
        return index

    def add_action(self, action, index: int = None, create=True) -> int:
        """Adds an action to this container.

        :param action the action to add
        :param index the index of the action_set into which to insert the action, by default adds to the next available slot unless specified (0 based)
        :param auto_create: true if the action set should be created if it does not exist
        :returns int: the index of the action set
        """

        if not self.action_sets:
            # ensure there is at least 1 action set
            self.action_sets.add(ActionSet())

        if index is None:
            index = 0

        action_set = self.action_sets.itemAt(index)
        if action_set is None:
            # add a new action set to the container
            action_set = ActionSet()
            index = self.action_sets.add(action_set)

        action_set.append(action)

        # Create activation condition data if needed
        self.create_or_delete_virtual_button()

        # notify of changes to this container
        self._fireChangeCallbacks()

        return index

    def ensureActionSet(self, count: int):
        """ensures there are at least count action sets defined"""
        self.action_sets.ensureCount(count)

    @property
    def action_sets(self) -> ActionSets:  # noqa: F405
        """gets the action sets for this container"""
        if self._action_sets is None:
            self._action_sets = ActionSets(self)
        return self._action_sets

    def createActionSet(self, action_list, description: str = None, data=None) -> ActionSet:  # noqa: F405
        """creates an action set from a list of actions"""
        action_set = ActionSet(self, description, data)
        action_set.append(action_list)
        return action_set

    @action_sets.setter
    def action_sets(self, value):
        assert False, "Action set cannot be changed"

    @property
    def action_count(self):
        """returns the total count of defined actions in this container (all action sets)"""
        return self.action_sets.actionCount()

    def getFlatActionSetList(self, action_sets):
        """flattens the action set list if needed"""
        return self._flatten_list(action_sets)

    def _flatten_list(self, items):
        data = []
        if hasattr(items, "__iter__"):
            for item in items:
                data.extend(self._flatten_list(item))
        else:
            data.append(items)

        return data

    def create_or_delete_virtual_button(self):
        """Creates activation condition data as required."""
        need_virtual_button = False
        for actions in [a for a in self.action_sets if a is not None]:
            need_virtual_button = need_virtual_button or any([a.requires_virtual_button() for a in actions if a is not None])

        if need_virtual_button:
            if self.virtual_button is None:
                input_type = self.parent.input_type
                vb = AbstractContainer.virtual_button_lut.get(input_type, None)
                if vb:
                    self.virtual_button = vb(self)

            elif not isinstance(
                self.virtual_button,
                AbstractContainer.virtual_button_lut[self.parent.input_type],
            ):
                self.virtual_button = AbstractContainer.virtual_button_lut[self.parent.input_type](self)
        else:
            self.virtual_button = None

    @property
    def has_virtual_button(self) -> bool:
        """true if the container has a virtual button definition"""
        return self._virtual_button_enabled and self._virtual_button_user_enabled and self.virtual_button is not None

    def generate_callbacks(self, parent=None):
        """Returns a list of callback data entries.

        :param parent: optional parent execution graph node
        :return list of container callback entries

        """
        import gremlin.execution_graph

        if not self._callbacks_enabled:
            # callbacks handled a different way by this container
            return []

        callbacks = []

        assert isinstance(parent, gremlin.execution_graph.ExecutionGraphNode) if parent is not None else True, "invalid parent: parent must be graph node"

        # For a virtual button create a callback that sends VirtualButton
        # events and another callback that triggers of these events
        # like a button would.

        callbacks.append(CallbackData(gremlin.execution_graph.ContainerCallback(self, parent), None))

        return callbacks

    def from_xml(self, node, data=None, extra_data=None):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """

        super().from_xml(node, data, extra_data)

        if "container_id" in node.attrib:
            self._id = node.get("container_id")

        assert node.tag == "container", "Invalid container node"
        assert "type" in node.attrib, "Invalid container node"

        comment = None
        if "comment" in node.attrib:
            comment = node.get("comment")
        if comment:
            self.comment = comment

        self._collapsed = safe_read(node, "collapsed", bool, False)

        # read container specific data
        self._parse_xml(node, data, extra_data)
        # parse action seets for the container
        if not extra_data:
            extra_data = {}
        extra_data["container_type"] = node.get("type")
        self._parse_action_set_xml(node, data, extra_data)

        # parse virtual butotn settings for container
        self._parse_virtual_button_xml(node, data, extra_data)
        # parse activation conditions for the container
        self._parse_activation_condition_xml(node, data, extra_data)

    def to_xml(self):
        """Returns a XML node representing the instance's contents.

        :return XML node representing the state of this instance
        """

        if self._abstract_container_generating_xml:
            syslog.error("ABSTRACT CONTAINER XML: recursion detected")
            return None

        try:
            self._abstract_container_generating_xml = True

            node = self._generate_xml()  # call derived container
            if node is None:
                # not implemented by the derived class - create our own
                node = lxml.etree.Element("container")

            assert node is not None, "Container: failed to get an container node generated"
            if __debug__:
                # ensure old containers no longer create action sets
                nodes = node.xpath("./action-set")
                assert len(nodes) == 0, "old container is still generating action set data"

            # generate the action sets
            self._generate_action_set_xml(node)

            node.set("container_id", self.id)

            if self.comment:
                node.set("comment", self.comment)

            node.set("collapsed", safe_format(self._collapsed, bool))  # collapsed state

            # Add activation condition if needed
            if self.virtual_button:
                node.append(self.virtual_button.to_xml())

            if self.activation_condition:
                condition_node = self.activation_condition.to_xml()
                if condition_node is not None:
                    node.append(condition_node)

            return node
        finally:
            self._abstract_container_generating_xml = False

    def _generate_xml(self) -> lxml.etree.Element:
        """this should be overriden in derived containers to write custom data - default is do nothing"""
        assert hasattr(self, "tag"), "Invalid container instance - instance should be derived"

        node = lxml.etree.Element("container")
        node.set("container_id", write_guid(self.id))
        node.set("type", self.tag)
        return node

    def _generate_action_set_xml(self, parent_node: lxml.etree.Element):
        """generates the action set for the container, can be overriden"""
        self.ensureActionSets()
        action_sets = self.action_sets
        for action_set in action_sets:
            node = action_set.to_xml()
            node.set("set-guid", write_guid(self._id))
            if action_sets.description:
                node.set("set-description", html.escape(action_sets.description))
            node.set("set-guid", write_guid(action_sets.id))

            parent_node.append(node)

    def _parse_xml(self, node: lxml.etree.Element, data=None, extra_data=None):
        """this should be implemented by derived containers to read custom data - default is do nothing"""
        pass

    def _parse_action_set_xml(self, node, data=None, extra_data=None):
        """Parses the XML content related to actions.

        :param node the XML node to process
        """

        if self.actionsetCustomParseCallback:
            # handles the complete load via custom callback if the container implements it
            self.actionsetCustomParseCallback(node, data, extra_data)
            return

        model_prefix = None
        if extra_data:
            if "container_type" in extra_data:
                container_type = extra_data["container_type"]
            if "input_item" in extra_data:
                input_item: InputItem = extra_data["input_item"]
                input_name = f"{input_item.device_name} {input_item.display_name}"
                model_prefix = f"Action Set for [{input_name}] container: {container_type}"

        self.action_sets.clear()
        as_read = False
        as_nodes = node.xpath("./action-set")
        index = 0
        for child in as_nodes:
            action_set = None
            if self.actionsetParseCallback:
                # container needs special handling of action set nodes
                action_set = self.actionsetParseCallback(child)
            if action_set is None:
                action_set = ActionSet(model_description=model_prefix or "Action Set")
            self._parse_action_xml(child, action_set, data, extra_data)
            if action_set:
                if index == len(self.action_sets):
                    self.action_sets.append(action_set)
                else:
                    self.action_sets[index] = action_set
            if not as_read:
                as_read = True
                if "set-guid" in child.attrib:
                    self.action_sets.id = read_guid(child, "set-guid")
                if "set-description" in child.attrib:
                    self.action_sets.description = html.unescape(node.get("description"))

            index += 1

    def _parse_action_xml(
        self,
        node: lxml.etree.Element,
        action_set: ActionSet,  # noqa: F405
        input_item: InputItem = None,
        extra_data: dict = None,
        data=None,
    ):
        """Parses the XML content related to actions in an action-set.

        :param node the XML node to process
        :param action_set: storage for the processed action nodes (usually a list)
        :param input_item: input item this action is attached to
        :param extra_data: any data for extra XML processing
        :param data: data to set the loaded action to

        """
        action_name_map = ActionPlugins().tag_map
        config = gremlin.config.Configuration()

        # get the id of the action set
        if "set-guid" in node.attrib:
            action_set.id = read_guid(node, "guid")
        if "set-description" in node.attrib:
            action_set.description = html.unescape(node.get("set-description"))

        action_set.pushSuspend()  # stop notifications while we're adding
        for child in node:
            if child.tag not in action_name_map:
                syslog.warning(f"Unknown node present: {child.tag}")
                continue

            # apply any conversions
            tag = child.tag
            if config.convert_response_curve and _is_curve_tag(tag):
                tag = "response-curve-ex"
                if tag not in action_name_map:
                    # new mapper not found
                    tag = child.tag
            elif config.convert_vjoy_remap and tag == "remap":
                tag = "vjoyremap"
                if tag not in action_name_map:
                    # new mapper not found
                    tag = child.tag

            entry = action_name_map[tag](self)
            entry.from_xml(child, (input_item, self), extra_data)  # pass input item, container as a tuple
            action_set.append(entry)
            if data is not None:
                entry.data = data
        action_set.popSuspend(emit=False)  # allow notifications but don't update

    def _parse_virtual_button_xml(self, node, data=None, extra_data=None):
        """Parses the virtual button part of the XML data.

        :param node the XML node to process
        """
        vb_node = node.find("virtual-button")
        device_guid, input_type, input_id, mode = gremlin.util.get_xml_input_data(node)

        self.virtual_button = None
        if vb_node is not None:
            item = AbstractContainer.virtual_button_lut[self.get_input_type()]
            if item is not None:
                self.virtual_button = item(self)
                self.virtual_button.from_xml(vb_node, data, extra_data)

    def _parse_activation_condition_xml(self, node, data, extra_data=None):
        """load the container condition"""
        self.activation_condition = BaseActivationCondition(ConditionModel(self), ActivationRule.All)
        self.activation_condition.setContainer(self)
        input_item = data
        activation_node = gremlin.util.get_xml_child(node, "activation-condition")
        if activation_node is not None:
            self.activation_condition.from_xml(activation_node, (input_item, self), extra_data)

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
                    syslog.warning(
                        f"Action warning: {type(action).__name__} reports invalid - hardware {self.hardware_device_name} input: {self.hardware_input_type_name}  {self.hardware_input_id}"
                    )
                state = state & action_valid
        return state

    def is_valid_for_save(self):
        """true if the container can be saved to a profile"""
        state = self._is_container_valid()

        return state

    def latch_extra_inputs(self, container_condition_functors=None, action_condition_functors=None):
        """returns any extra inputs as a list of (device_guid, input_id) to latch to this action (trigger on change)"""
        latched_list = []
        for actions in [a for a in self.action_sets if a is not None]:
            for action in actions:
                if hasattr(action, "latch_extra_inputs"):
                    for key in action.latch_extra_inputs():
                        if key not in latched_list:
                            latched_list.append(key)

        return latched_list

    @abstractmethod
    def _is_container_valid(self):
        """Returns whether or not the container itself is valid.

        :return True container data is valid, False otherwise
        """
        pass

    def get_action_sets(self):
        """returns action sets - used for duplication (override if needed)"""
        return self.action_sets


class AbstractAction(BaseProfileData):
    """Base class for all actions that can be encoded via the XML and
    UI system."""

    # id_changed = Signal(str, str)  # triggers when the ID changes

    # allow all input types by default
    input_types = InputType.to_list()
    # data_changed = QtCore.Signal() # indicates the action data changed

    id_changed = Signal(str, str)  # triggers when the ID changes (old_id, new_id)
    icon_changed = Signal()  # triggers when the icon changes

    def __init__(self, parent):
        """Creates a new instance.

        :parent the container which is the parent to this action
        """
        # assert isinstance(parent, AbstractContainer)
        super().__init__(parent)

        self._abstract_action_generating_xml = False  # true if generating XML
        self.activation_condition = None  # stores the conditions attached to that action
        self._id = gremlin.util.get_guid()
        self._action_type = None
        self._enabled = False  # true if the action is enabled
        self.singleton = False  # true if the action can only appear once in the input's mapping
        self.parent_container = parent  # holds the reference to the parent container holding this action
        self._is_axis = False
        self._is_hardware = None
        self.comment = None  # user comments/notes
        self._priority = 5  # default priority
        self.data = None  # additional data for runtime purposes, context dependent used to tag actions at runtime for some purpose like action grouping
        self.data_ex = None  # additional data for
        self.condition_view = None  # holds the condition view object for this action
        self._is_multi_mode_action = False  # true if a multimode action
        self._send_mode = SendType.Normal  # normal send type

        # new T83 - remote control configuration object
        self.remote_config = gremlin.remote.RemoteConfig()  # this action does not allow local control

        self._hooked = False
        el = gremlin.event_handler.EventListener()
        el.profile_hook.connect(self.hook)
        el.profile_unhook.connect(self.unhook)
        el.profile_unload.connect(self._cleanup)

    @property
    def debug_name(self) -> str:
        """friendly display name"""
        return f"[action: {self.tag} id: {str(self.id)}] input: [{self.get_container().debug_name}]"

    def hook(self):
        if not self._hooked:
            self._hooked = True
            el = gremlin.event_handler.EventListener()
            el.profile_start.connect(self.profile_start)
            el.profile_started.connect(self.profile_started)
            el.profile_stop.connect(self.profile_stop)
            el.profile_after_start.connect(self.profile_post_start)

    def unhook(self):
        if not self._hooked:
            el = gremlin.event_handler.EventListener()
            el.profile_start.disconnect(self.profile_start)
            el.profile_started.disconnect(self.profile_started)
            el.profile_stop.disconnect(self.profile_stop)
            el.profile_after_start.disconnect(self.profile_post_start)
            self._hooked = False

    @property
    def sendMode(self) -> SendType:
        return self._send_mode

    @sendMode.setter
    def sendMode(self, value: SendType):
        self._send_mode = value

    def sendFlags(self) -> tuple:
        """returns a (is_local, is_remote) boolean tuple based on the action's current send mode"""

        match self._send_mode:
            case SendType.Normal:
                return self.remote_config.state
                # return gremlin.remote.remote_control.state
            case SendType.LocalAndRemote:
                return (True, True)
            case SendType.LocalOnly:
                return (True, False)
            case SendType.RemoteOnly:
                return (False, True)

        syslog.warning(f"Don't know how to handle sendmode: [{self._send_mode}]")
        return self.remote_config.state
        # return gremlin.remote.remote_control.state

    def isMultiMode(self) -> bool:
        """true if the action is a multimode action"""
        return self._is_multi_mode_action

    def profile_start(self):
        """start event - override in subclass as needed"""
        pass

    def profile_stop(self):
        """stop event - override in subclass as needed"""
        pass

    def profile_post_start(self):
        """post start event - occurs after profile started"""
        pass

    def profile_started(self):
        """started event - override in subclass as needed"""
        pass

    def getCurves(self) -> list:
        """gets action node siblings"""
        container = self.parent_container
        curve_list = []
        for action_set in container.action_sets:
            for action in action_set:
                if _is_curve_tag(action.tag):
                    curve_data = action.curve_data
                    if curve_data:
                        curve_data.curve_update()
                        curve_list.append(curve_data)
        return curve_list

    @property
    def id(self):
        """unique ID for this condition, persisted"""
        return self._id

    @id.setter
    def id(self, value: str):
        """sets the ID"""
        self.setId(value)

    def setId(self, value: str):
        """sets the ID"""
        if self._id != value:
            old_id = self._id
            self._id = value
            self.id_changed.emit(old_id, value)
        else:
            self._id = value

    @property
    def priority(self):
        return self._priority

    def setPriority(self, value: int):
        """sets the priority of the action, numeric"""
        value = gremlin.util.clamp(value, 0, 1000)
        self._priority = value

    @property
    def has_conditions(self):
        """true if the action has conditions defined"""
        return self.activation_condition is not None and len(self.activation_condition.conditions) > 0

    def actionDeleted(self):
        """called when the action is deleted"""
        el = gremlin.event_handler.EventListener()
        el.action_deleted.emit(self)
        self._cleanup()

    def _cleanup(self):
        """called when the action should clean itself up"""
        el = gremlin.event_handler.EventListener()
        event = gremlin.event_handler.DeviceChangeEvent()
        event.source = self
        el.icon_changed.emit(event)
        el.profile_unload.disconnect(self._cleanup)

    def get_input_item(self):
        """gets the input item owning this action"""
        input_item = _get_input_item(self.parent_container)
        return input_item

    def get_container(self) -> AbstractContainer:
        return self.parent_container

    def get_sibblings(self):
        """gets action sibblings in the same container"""
        container = self.get_container()
        return container.getActions()

    def setEnabled(self, value):
        """enables or disables the functor - a disabled functor will not receive the start profile event nor will the process_event be called

        This is done to make sure that functors only get called if the plugin is referenced in a profile's execution graph to avoid unecessary initializations

        """
        import gremlin.event_handler

        if self._enabled == value:
            return  # nothing to do
        self._enabled = value

        verbose = gremlin.config.Configuration().verbose_mode_details

        if verbose and value:
            syslog.info(f"ACTION: SET ENABLED STATE: Functor: {self.name} {type(self).__name__} enabled")

    def input_is_axis(self):
        """true if the input is an axis type input"""
        input_item = self.input_item

        if hasattr(input_item, "is_axis"):
            return input_item.is_axis
        is_axis = False

        if hasattr(self, "input_type"):
            input_type: InputType = self.input_type
            if input_type == InputType.JoystickAxis:
                return True

        if hasattr(self.hardware_input_id, "is_axis"):
            is_axis = self.hardware_input_id.is_axis
            return is_axis
        if hasattr(self.input_item, "is_axis") and hasattr(self._input_item, "axis_value"):
            is_axis = is_axis or self.input_item.is_axis

        return is_axis

    def input_is_button(self):
        """true if the input is a button"""
        is_button = False
        input_item = self.input_item
        input_type = input_item.input_type

        # check hat first
        hardware_input_type = self.hardware_raw_input_type

        if not input_type:
            if hasattr(self.parent_container, "get_input_type"):
                input_type = self.parent_container.get_input_type()  # container override input type

        if input_type:
            return input_type == InputType.JoystickButton

        if hardware_input_type == InputType.JoystickHat:
            return False

        if hasattr(input_item, "is_button"):
            is_button = input_item.is_button
            return is_button

        if hasattr(self, "hardware_input_type"):
            input_type: InputType = self.hardware_input_type
            return input_type == InputType.JoystickButton

        if hasattr(self.hardware_input_id, "is_button"):
            is_button = self.hardware_input_id.is_button

        if hasattr(self.hardware_input_id, "is_axis"):
            is_button = not self.hardware_input_id.is_axis

        return is_button

    def input_is_hardware(self):
        """true if the device is a hardware input device"""
        if self._is_hardware is None:
            self._is_hardware = gremlin.joystick_handling.is_hardware_device(self.hardware_device_guid)
        return self._is_hardware

    @property
    def enabled(self):
        return self._enabled

    @property
    def action_id(self):
        """id"""
        return self._id

    @property
    def action_type(self):
        """type name of this action"""
        return self._action_type

    def display_name(self):
        """display name for this action"""
        return "N/A"

    def icon_valid(self):
        """returns true if the action is valid"""
        return True

    def fireIconChanged(self):
        """fires the icon changed event"""
        self.icon_changed.emit()

    def from_xml(self, node, data=None, extra_data=None):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """

        # set the action ID first as it can be read by subsequent code
        _import_data = gremlin.base_profile.ProfileImportData()

        if "action_id" in node.attrib:
            self.id = node.get("action_id")

        if "send-mode" in node.attrib:
            mode_int = safe_read(node, "send-mode", int, 0)
            mode = SendType(mode_int)
            self._send_mode = mode

        comment = None
        if "comment" in node.attrib:
            comment = node.get("comment")
        if comment:
            self.comment = comment

        priority = 5  # default priority for actions
        if "priority" in node.attrib:
            priority = safe_read(node, "priority", int, 5)
            priority = gremlin.util.clamp(priority, 0, 1000)
            self._priority = priority

        if extra_data:
            # pickup any input types to use for this action
            if "override_input_type" in extra_data:
                self.input_type = extra_data["override_input_type"]

            elif "input_type" in extra_data:
                self.input_type = extra_data["input_type"]

        nodes = node.xpath(".//remote-config")
        if nodes:
            self.remote_config.from_xml(nodes[0])

        super().from_xml(node, data, extra_data)

        self.activation_condition = BaseActivationCondition(ConditionModel(self), ActivationRule.All)
        self.activation_condition.setContainer(self)
        for _ in node.findall("activation-condition"):
            cond_node = node.find("activation-condition")
            if cond_node is not None:
                self.activation_condition.from_xml(cond_node, data, extra_data)

        # record the type of this action
        self._action_name = node.tag

    def to_xml(self):
        """Returns a XML node representing the instance's contents.

        :return XML node representing the state of this instance
        """

        if self._abstract_action_generating_xml:
            syslog.error("ACTION XML: Recusion detected:")
            return None

        try:
            self._abstract_action_generating_xml = True

            node = super().to_xml()
            if self.has_conditions:
                # output the conditions
                node.append(self.activation_condition.to_xml())

            # output the ID
            node.set("action_id", self.action_id)

            # send mode
            if self._send_mode != SendType.Normal:
                # only save if not default
                node.set("send-mode", safe_format(self._send_mode.value, int))

            # output any notes
            if self.comment:
                node.set("comment", self.comment)

            node.set("priority", safe_format(self._priority, int))

            # remote configuration
            rc_node = self.remote_config.to_xml()
            node.append(rc_node)

            return node
        finally:
            self._abstract_action_generating_xml = False

    def requires_virtual_button(self):
        """Returns whether or not the action requires the use of a
        virtual button.

        :return True if a virtual button has to be used, False otherwise
        """
        raise gremlin.error.MissingImplementationError("AbstractAction.requires_virtual_button() not implemented")

    def _is_valid(self):
        raise gremlin.error.MissingImplementationError("AbstractAction._is_valid() not implemented")

    def is_valid_for_save(self):
        """indicates an action can be saved to a profile even if it's not configured - this allows in process profile saving"""
        return True

    def __str__(self):
        if hasattr(self, "display_name"):
            return self.display_name()
        return super().__str__()

    def __hash__(self):
        # index on the unique ID of each action
        return hash(self._id)


class ActionSet(AbstractCallbackModel):
    """holds action set data with a data and ID attribute - each action set contains a list of AbstractActions"""

    def __init__(self, data=None, model_description: str = None):
        super().__init__(
            allowed_types=(AbstractAction,),
            model_description=f"Action Set Model: [{model_description or 'n/a'}]",
        )
        self._data = data  # any special tag to identify the action set
        self.description: str = None  # description of the action set (optional)

    @staticmethod
    def fromList(source: list | tuple):
        """returns an action set from the source list"""
        action_set = ActionSet()
        action_set.pushSuspend()
        for item in source:
            action_set.add(item)
        action_set.popSuspend()
        return action_set

    def clear(self):
        """clears the action set"""
        for action in self:
            if hasattr(action, "actionDeleted"):
                action.actionDeleted()

        super().clear()

    def add_action(self, action : AbstractAction):
        """adds the given action to the set"""
        self.add(action)

    def remove_action(self, action : AbstractAction, delete=True):
        """removes the given action from the set
        :param action: the action
        :param delete: if true, deletes the action from the profile
        """
        if action not in self:
            return
        self.remove(action)
        if delete and hasattr(action, "actionDeleted"):
            action.actionDeleted()

    def removeAction(self, action: AbstractAction, delete=True):
        """removes the given action from the set
        :param action: the action
        :param delete: if true, deletes the action from the profile
        """
        if action not in self:
            return
        self.remove(action)
        if delete and hasattr(action, "actionDeleted"):
            action.actionDeleted()

    def to_xml(self):
        """writes the actions in the action set out"""
        node = lxml.etree.Element("action-set")
        node.set("guid", write_guid(self.id))
        if self.description:
            node.set("description", html.escape(self.description))
        for action in self:
            node.append(action.to_xml())
        return node

    def from_xml(
        self,
        node,
        container: AbstractContainer,
        input_item: InputItem = None,
        extra_data: dict = None,
        data=None,
    ):
        """reads an action set"""
        if node.tag == "action-set":
            if "guid" in node.attrib:
                self.id = read_guid(node, "guid")
            if "description" in node.attrib:
                self.description = html.unescape(node.get("description"))

        config = gremlin.config.Configuration()
        self.clear()

        # valid action names
        action_name_map = ActionPlugins().tag_map
        for child in node:
            if child.tag not in action_name_map:
                syslog.warning(f"ActionSet XML: don't know how to handle action: [{child.tag}]")
                continue

            if config.convert_response_curve and gremlin.base_classes._is_curve_tag(child.tag):
                tag = "response-curve-ex"
                if tag not in action_name_map:
                    # new mapper not found
                    tag = child.tag
            elif config.convert_vjoy_remap and tag == "remap":
                tag = "vjoyremap"
                if tag not in action_name_map:
                    # new mapper not found
                    tag = child.tag

            entry = action_name_map[tag](self)
            entry.from_xml(child, (input_item, self), extra_data)  # pass input item, container as a tuple
            self.add(entry)

            if data is not None:
                entry.data = data


class ActionSetModel(AbstractCallbackModel):
    """Model storing a set of actions."""

    def __init__(self, action_set: ActionSet | list = []):
        if not isinstance(action_set, ActionSet):
            # convert
            action_set = ActionSet.fromList(action_set)

        super().__init__(
            allowed_types=(ActionSet,),
            model_description=f"ActionSetModel: [{action_set.description}]",
        )

        assert isinstance(action_set, ActionSet), "Action set must be provided"
        # change the storage of the model
        self._items = action_set
        self.resetChanges()

    def add_action(self, action):
        """adds an action to the model"""
        self.add(action)
        self._fireIconChange(self, action)

    def _fireIconChange(self, action):
        # fire change event for action icons
        el = gremlin.event_handler.EventListener()
        event = gremlin.event_handler.DeviceChangeEvent()
        event.device_guid = action.hardware_device_guid
        event.device_input_id = action.hardware_input_id
        event.device_input_type = action.hardware_input_type
        event.source = action
        el.icon_changed.emit(event)

    def remove_action(self, action):
        """runs when an action should be deleted"""
        import gremlin.util

        if action in self._items:
            input_item = action.get_input_item()
            container: AbstractContainer = action.get_container()
            self.remove(action)

            # del self._items[self._items.index(action)]

            # # run action delete if the action supports it
            # if hasattr(action,"actionDeleted"):
            #     action.actionDeleted()

            # if hasattr(action,"_cleanup"):
            #     action._cleanup()

            # self._fireChanged()

            el = gremlin.event_handler.EventListener()
            el.action_delete.emit(input_item, container, action)  # tell the UI the action is being deleted

            self._fireIconChange(self, action)


# class BaseAbstractCondition(QtCore.QObject, metaclass=ABCMetaQObject):
class BaseAbstractCondition:
    """Base class of all individual condition representations."""

    # id_changed = Signal(str, str)  # triggers when the ID changes

    def __init__(self):
        """Creates a new condition."""
        # super().__init__()
        import gremlin.util

        self._id = gremlin.util.get_guid()
        self._comparison = ""
        self._activation_condition = None  # owning container
        self.delay = 0.0  # delay in seconds

    def setOwner(self, owner):
        self._activation_condition = owner

    @property
    def owner(self):
        return self._activation_condition

    @property
    def id(self):
        """unique ID for this condition, persisted"""
        return self._id

    def setId(self, value):
        self._id = value

    @property
    def comparison(self):
        return self._comparison

    @comparison.setter
    def comparison(self, value):
        self._comparison = value

    def from_xml(self, node, data=None, extra_data=None):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """
        _import_data = gremlin.base_profile.ProfileImportData()
        if "condition_id" in node.attrib:
            self._id = node.get("condition_id")
        self.delay = safe_read(node, "delay", float, 0.0)

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        node = lxml.etree.Element("condition")
        node.set("condition_id", self._id)
        node.set("delay", safe_format(self.delay, float))
        return node

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return self._comparison != ""


@SingletonDecorator
class ConditionTracker:
    """tracks conditions"""

    def __init__(self):
        import gremlin.event_handler

        self._cache = {}  # map of known conditions keyed by mode and condition ID
        self._owner_map = {}  # map of condition ID to its input item owner so we know which input item has which condition
        self._data_map = {}  # map of condition ID to tracker data
        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self.reset)
        el.profile_unloaded.connect(self.reset)

    @QtCore.Slot()
    def reset(self):
        """triggered on app exit or profile unload"""
        self._cache.clear()
        self._owner_map.clear()
        self._data_map.clear()

    def registerCondition(self, data: ConditionTrackerData):  # noqa: F405
        """registers a condition and its owner - owner is an input_item"""
        mode = data.mode
        condition = data.condition
        input_item = data.input_item
        if mode not in self._cache:
            self._cache[mode] = {}
        self._cache[mode][condition.id] = data
        self._owner_map[condition.id] = input_item
        self._data_map[condition.id] = data
        el = gremlin.event_handler.EventListener()
        el.condition_added.emit(input_item, mode, condition)
        el.condition_state_changed.emit(data.container)
        verbose = gremlin.config.Configuration().verbose_mode_condition
        if verbose:
            syslog = logging.getLogger("system")
            syslog.info(
                f"creating condition: {condition.id} for input: {data.input_item.display_name if hasattr(data.input_item, 'display_name') else data.input_item} mode: {data.mode}"
            )
        # data.condition.id_changed.connect(self._condition_id_changed)

    def unregisterCondition(self, condition: BaseAbstractCondition):
        """unregisters a condition"""
        syslog = logging.getLogger("system")
        syslog.info(f"delete condition: {condition.id}")
        id = condition.id
        for mode in self._cache:
            if id in self._cache[mode]:
                data = self._cache[mode][id]
                del self._cache[mode][id]
                del self._owner_map[id]
                # (input_item, mode, condition)
                el = gremlin.event_handler.EventListener()
                el.condition_removed.emit(data.input_item, data.mode, data.condition)
                if Shiboken.isValid(data.container):
                    el.condition_state_changed.emit(data.container)
                return

    def count(self):
        """gets a count of registered conditions"""
        return len(self._cache)

    def getInputItemConditionCount(self, input_item, mode: str = None):
        """gets a count of registered condition for a specific owner - owner is an input_item"""

        if not mode:
            mode = input_item.profile_mode
        if mode in self._cache:
            id_list = [item.condition.id for item in self._cache[mode].values() if item.input_item == input_item]
            return len(id_list)
        return 0

    def getInputItemConditions(self, input_item, mode: str = None):
        """gets the conditions for the specified input"""
        if not mode:
            mode = input_item.profile_mode
        if mode in self._cache:
            condition_list = [item.condition for item in self._cache[mode].values() if item.input_item == input_item]
            return condition_list
        return None

    def getContainerConditionCount(self, container, mode: str = None):
        """gets a count of registered condition for a specific owner - owner is an input_item"""

        if not mode:
            input_item = container.parent
            mode = input_item.profile_mode  # gremlin.shared_state.current_mode
        if mode in self._cache:
            id_list = [item.condition.id for item in self._cache[mode].values() if item.container == container]
            return len(id_list)
        else:
            # not in cache
            input_item = container.input_item

        return 0

    def getConditionInputItem(self, condition: BaseAbstractCondition):
        """gets the input item attached to a condition"""
        id = condition.id
        if id in self._owner_map:
            return self._owner_map[id]
        return None

    def getConditionsForInputItem(self, input_item, mode: str):
        """checks to see if conditions are defined for this input item"""
        import gremlin.shared_state

        if not mode:
            mode = gremlin.shared_state.current_mode
        if mode in self._cache:
            id_list = [id for id, item in self._owner_map[mode].items() if item == input_item]
            conditions = [self._cache[mode][id] for id in id_list]
            return conditions
        return None

    def getConditionForAction(self, action):
        """gets a condition for an action"""
        data: ConditionTrackerData = self.getActionData(action)
        if data:
            return data.condition
        return None

    def getRuleForAction(self, action):
        """gets the condition rule for an action"""
        data: ConditionTrackerData = self.getActionData(action)
        if data:
            return data.rule
        return None

    def owner(self, condition: BaseAbstractCondition):
        """what input item owns the condition"""
        if condition.id in self._cache:
            return self._owner_map[condition.id]
        return None

    def getData(self, condition: BaseAbstractCondition):
        """gets the condition tracking data"""
        if condition.id in self._data_map:
            return self._data_map[condition.id]
        return None

    def getActionData(self, action):
        if action.action_id in self._data_map:
            return self._data_map[action.action_id]
        return None


class AbstractCondition(metaclass=ABCMeta):
    """Represents an abstract condition.

    Conditions evaluate to either True or False and are given an event as well
    as possibly processed Value when being evaluated.
    """

    def __init__(self, comparison=None):
        """Creates a new condition with a specific comparision operation.

        :param comparison the comparison operation to perform when evaluated
        """
        self.comparison = comparison
        self.id = gremlin.util.get_guid()
        self.manual_callback = False
        self.delay = 0.0  # delay in seconds

    @abstractmethod
    def __call__(self, event, value, extra_data=None):
        """Evaluates the condition using the condition and provided data.

        :param event raw event that caused the condition to be evaluated
        :param value the possibly modified value
        :return True if the condition is satisfied, False otherwise
        """
        pass

    @abstractmethod
    def process_event(self, event, value, extra_data=None):
        pass

    def condition_name(self) -> str:
        return "condition_name() member not implemented: Condition not set"


class ABCMetaQObject(ABCMeta, type(QtCore.QObject)):
    pass


class BaseKeyboardCondition(BaseAbstractCondition):
    """Keyboard state based condition.

    The condition is for a single key and as such contains the key's scan
    code as well as the extended flag.
    """

    def __init__(self):
        """Creates a new instance."""
        super().__init__()
        self.input_item = None
        self.scan_code = None
        self.is_extended = None
        self.comparison = "pressed"

    def from_xml(self, node, data=None, extra_data=None):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """

        super().from_xml(node, data, extra_data)
        self.comparison = safe_read(node, "comparison", str, "")
        self.scan_code = safe_read(node, "scan-code", int, 0)
        self.is_extended = parse_bool(safe_read(node, "extended", str, ""))
        input_item = None
        for child in node:
            if child.tag == "input":
                from gremlin.ui.keyboard_device import KeyboardInputItem

                input_item = KeyboardInputItem()
                input_item.parse_xml(child, data)

        self.input_item = input_item

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        node = super().to_xml()  # lxml.etree.Element("condition")
        node.set("condition-type", "keyboard")
        node.set("input", "keyboard")
        node.set("comparison", str(self.comparison))
        node.set("scan-code", str(self.scan_code))
        node.set("extended", str(self.is_extended))

        if self.input_item:
            child = self.input_item.to_xml()
            node.append(child)

        return node

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return super().is_valid() and self.scan_code is not None and self.is_extended is not None

    def __str__(self):
        from gremlin.ui.keyboard_device import Key

        key = Key(scan_code=self.scan_code, is_extended=self.is_extended)
        return f"Keyboard condition: id: {self.id} comparison: {self.comparison} key {key.debug_name}"

    def to_html(self) -> str:
        """html output version"""
        from gremlin.reporting import ReportTable
        from gremlin.ui.keyboard_device import Key

        table = ReportTable(cellpadding=4)
        table.addField("Condition", "Keyboard")
        table.addField("Comparison", self.comparison)
        key = Key(scan_code=self.scan_code, is_extended=self.is_extended)
        table.addField("Key", key.name)
        return table.to_html()


class BaseJoystickCondition(BaseAbstractCondition):
    """Joystick state based condition.

    This condition is based on the state of a joystick axis, button, or hat.
    """

    def __init__(self):
        """Creates a new instance."""
        super().__init__()
        self.device_guid = 0  # use this as the invalid GUID
        self.input_type = None
        self.input_id = 0
        self.range = [0.0, 0.0]
        self.device_name = ""
        self.use_calibrated_data = True  # true if the input should use the calibrated data if any
        self.ignore_release = False  # true if the condition always succeeds on input release

    def from_xml(self, node, data=None, extra_data=None):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """

        super().from_xml(node, data, extra_data)

        self.input_type = InputType.to_enum(safe_read(node, "input", str, ""))
        comparison = safe_read(node, "comparison", str, "")
        if not comparison:
            match self.input_type:
                case InputType.JoystickAxis:
                    comparison = "inside"
                case InputType.JoystickButton:
                    comparison = "pressed"
                case InputType.JoystickHat:
                    comparison = "center"
        self.comparison = comparison

        self.input_id = safe_read(node, "id", int, 1)
        self.device_guid = parse_guid(node.get("device-guid"))
        self.device_name = safe_read(node, "device-name", str, "")
        self.range = [
            safe_read(node, "range-low", float, 0),
            safe_read(node, "range-high", float, 0),
        ]
        self.use_calibrated_data = safe_read(node, "use-calibrated", bool, False)
        self.ignore_release = safe_read(node, "ignore-release", bool, False)

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        # node = lxml.etree.Element("condition")
        node = super().to_xml()
        node.set("comparison", str(self.comparison))
        node.set("condition-type", "joystick")
        node.set("input", InputType.to_string(self.input_type))
        node.set("id", safe_format(self.input_id, int))
        node.set("device-guid", write_guid(self.device_guid))
        node.set("device-name", str(self.device_name))
        node.set("range-low", safe_format(self.range[0], float))
        node.set("range-high", safe_format(self.range[1], float))
        node.set("ignore-release", safe_format(self.ignore_release, bool))
        node.set("use-calibrated", safe_format(self.use_calibrated_data, bool))

        return node

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return self.input_type is not None  # super().is_valid() and self.input_type is not None

    def __str__(self):
        return f"Joystick Condition: id: {self.id} comparison: {self.comparison} input type: {self.input_type.name} device: {self.device_name} input id: {self.input_id}  range: [{self.range[0]:0.3f},{self.range[0]:0.3f}]  use calibrated: {self.use_calibrated_data}"

    def to_html(self) -> str:
        """html output version"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)
        table.addField("Condition", "Joystick")
        table.addField("Comparison", self.comparison)
        table.addField("Device", self.device_name)
        table.addField("Type", self.input_type.name)
        table.addField("ID", f"{self.input_id}")
        if self.input_type == InputType.JoystickAxis:
            table.addField("Range", f"[{self.range[0]:0.3f},{self.range[1]:0.3f}]")
            table.addField("Use calibrated data", "Yes" if self.use_calibrated_data else "No")

        table.addField("Ignore release", "Yes" if self.ignore_release else "No")
        return table.to_html()


class BaseStateCondition(BaseAbstractCondition):
    """state condition"""

    def __init__(self):
        super().__init__()

        self.key = None
        self.description = None
        self.comparison = "pressed"
        self.ignore_release = False

    def from_xml(self, node, data=None, extra_data=None):
        import gremlin.ui.state_device

        super().from_xml(node, data, extra_data)

        condition_type = node.get("condition-type")
        if condition_type != "state":
            return

        self.key = node.get("key")
        if "description" in node.attrib:
            self.description = html.unescape(node.get("description"))
        self.comparison = safe_read(node, "comparison", str, "")
        self.ignore_release = safe_read(node, "ignore-release", bool, False)
        sd = gremlin.ui.state_device.StateData()
        sd.register(self.key, description=self.description)

    def to_xml(self):
        node = super().to_xml()
        node.set("comparison", str(self.comparison))
        node.set("condition-type", "state")
        node.set("key", self.key)
        node.set("ignore-release", safe_format(self.ignore_release, bool))
        if self.description:
            node.set("description", html.escape(self.description))

        return node

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return super().is_valid() and bool(self.key)

    def __str__(self):
        return f"State Condition: [{self.key}] comparison: {self.comparison}"

    def to_html(self) -> str:
        """html output version"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)
        table.addField("Condition", "State")
        table.addField("Comparison", self.comparison)
        table.addField("State", self.key)
        table.addField("Ignore release", "Yes" if self.ignore_release else "No")
        if self.description:
            table.addField("Description", self.description)
        return table.to_html()


class BaseModeCondition(BaseAbstractCondition):
    """mode condition"""

    def __init__(self):
        super().__init__()

        self.description = None
        self.comparison = "equal"
        self.mode = gremlin.shared_state.edit_mode
        self.ignore_release = False

    def from_xml(self, node, data=None, extra_data=None):
        super().from_xml(node, data, extra_data)

        condition_type = node.get("condition-type")
        if condition_type != "mode":
            return
        assert "mode" in node.attrib
        self.mode = node.get("mode")

        if "description" in node.attrib:
            self.description = node.get("description")

        self.comparison = safe_read(node, "comparison", str, "")
        self.ignore_release = safe_read(node, "ignore-release", bool, False)

    def to_xml(self):
        node = super().to_xml()
        node.set("comparison", str(self.comparison))
        node.set("mode", self.mode if self.mode else "")
        node.set("condition-type", "mode")
        node.set("ignore-release", safe_format(self.ignore_release, bool))
        if self.description:
            node.set("description", self.description)

        return node

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return super().is_valid() and bool(self.mode)

    def __str__(self):
        return f"Mode Condition:  Mode: [{self.mode}] comparison: {self.comparison}"

    def to_html(self) -> str:
        """html output version"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)
        table.addField("Condition", "Mode")
        table.addField("Comparison", self.comparison)
        table.addField("Mode", self.mode)
        if self.description:
            table.addField("Description", self.description)
        return table.to_html()


class BaseVJoyCondition(BaseAbstractCondition):
    """vJoy device state based condition.

    This condition is based on the state of a vjoy axis, button, or hat.
    """

    def __init__(self):
        """Creates a new instance."""
        super().__init__()
        self.vjoy_id = 0
        self.input_type = None
        self.input_id = 0
        self.range = [0.0, 0.0]
        self.ignore_release = False

    def from_xml(self, node, data=None, extra_data=None):
        """Populates the object with data from an XML node.

        Parameters
        ==========
        node : lxml.etree.Element
            XML node to parse for data
        """

        super().from_xml(node, data, extra_data)
        self.comparison = safe_read(node, "comparison", str, "")
        if "input" not in node.attrib:
            syslog.error("VJOY XML: invalid input in XML - NULL ")
            return

        self.input_type = InputType.to_enum(safe_read(node, "input", str, ""))

        input_id = safe_read(node, "id", int, 0)
        vjoy_id = safe_read(node, "vjoy-id", int, 0)

        if input_id == 0 or vjoy_id == 0:
            syslog.error(f"VJOY XML: invalid input in XML: device: {vjoy_id}  input: {input_id}")
            return
        self.input_id = input_id
        self.vjoy_id = vjoy_id
        self.ignore_release = safe_read(node, "ignore-release", bool, False)
        self.range = [
            safe_read(node, "range-low", float, 0),
            safe_read(node, "range-high", float, 0),
        ]

    def to_xml(self):
        """Returns an XML node containing the objects data.

        Return
        ======
        lxml.etree.Element
            XML node containing the object's data
        """
        # node = lxml.etree.Element("condition")

        node = super().to_xml()
        node.set("comparison", str(self.comparison))
        node.set("condition-type", "vjoy")

        is_error = False
        if self.input_type is None:
            syslog.error("VJOY CONDITION: invalid data: bad input type (NULL)")
            is_error = True
        if self.input_id == 0:
            syslog.error("VJOY CONDITION: invalid data: bad input 0")
            is_error = True
        if self.vjoy_id == 0:
            syslog.error("VJOY CONDITION: invalid data: bad device ID 0")
            is_error = True

        if not is_error:
            node.set("input", InputType.to_string(self.input_type))
            node.set("id", safe_format(self.input_id, int))
            node.set("vjoy-id", write_guid(self.vjoy_id))
            node.set("range-low", safe_format(self.range[0], float))
            node.set("range-high", safe_format(self.range[1], float))
            node.set("ignore-release", safe_format(self.ignore_release, bool))
        return node

    def is_valid(self):
        """Returns whether or not a condition is fully specified.

        :return True if the condition is properly specified, False otherwise
        """
        return super().is_valid() and self.input_type is not None and self.vjoy_id > 0 and self.input_id > 0

    def __str__(self):
        return f"Vjoy Condition: id: {self.id} comparison: {self.comparison} input type: {self.input_type.name} vjoy device: {self.vjoy_id} input id: {self.input_id}  range: [{self.range[0]:0.3f},{self.range[1]:0.3f}]"

    def to_html(self) -> str:
        """html output version"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)
        table.addField("Condition", "VJoy")
        table.addField("Comparison", self.comparison)
        table.addField("Vjoy Device", self.vjoy_id)
        table.addField("Type", self.input_type.name)
        table.addField("ID", f"{self.input_id}")
        table.addField("Ignore release", "Yes" if self.ignore_release else "No")
        if self.input_type == InputType.JoystickAxis:
            table.addField("Range", f"[{self.range[0]:0.3f},{self.range[1]:0.3f}]")
        return table.to_html()


class BaseInputActionCondition(BaseAbstractCondition):
    """Input item press / release state based condition.

    The condition is for the current input item, triggering based on whether
    or not the input item is being pressed or released.
    """

    def __init__(self):
        """Creates a new instance."""
        super().__init__()
        self._comparison = "always"  # default comparison is press or release

    def from_xml(self, node, data=None, extra_data=None):
        """Populates the object with data from an XML node.

        :param node the XML node to parse for data
        """
        super().from_xml(node, data, extra_data)
        self.comparison = safe_read(node, "comparison", str, "")

    def to_xml(self):
        """Returns an XML node containing the objects data.

        :return XML node containing the object's data
        """
        # node = lxml.etree.Element("condition")
        node = super().to_xml()
        node.set("condition-type", "action")
        node.set("input", "action")
        node.set("comparison", str(self.comparison))
        return node

    def __str__(self):
        return f"Input Condition: id: [{self.id}] comparison: [{self.comparison}]"

    def to_html(self) -> str:
        """html output version"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)
        table.addField("Condition", "Input")
        table.addField("Comparison", self.comparison)

        return table.to_html()


class ConditionTrackerData:
    def __init__(self, mode, input_item, container, condition, rule):
        self.condition = condition
        self.container = container
        self.input_item = input_item
        self.mode = mode
        self.rule = rule


class ConditionModel(AbstractCallbackModel):
    """Stores and represents condition data."""

    def __init__(
        self,
        action_data: AbstractContainer | AbstractAction | ConditionContainer,
        condition_data: BaseActivationCondition = None,  # noqa: F405
    ):
        """Creates a new model to store condition data.

        :param action_data the condition data to represent (container, action or condition container)
        :param parent the parent of this object
        """

        super().__init__(allowed_types=(BaseAbstractCondition,), model_description="ConditionModel")
        self.condition_data = condition_data
        # self.action_data = action_data
        self.container = None
        if isinstance(action_data, AbstractContainer):
            self.container = action_data
        elif isinstance(action_data, AbstractAction):
            # find the container for the given action
            self.container = action_data.get_container()
        elif isinstance(action_data, ConditionContainer):
            self.container = action_data.get_container()

        assert self.container is not None, "invalid data"

    @property
    def input_item(self) -> InputItem:
        """input item the condition applies to"""
        return self.container.input_item

    def rows(self):
        """Returns the number of rows in the model.
        :return number of rows
        """
        return len(self.condition_data.conditions)

    def data(self, index):
        """Returns the data stored at the given index.

        :param index the index for which to return the data
        :return the data stored at the provided index
        """
        return self.condition_data.conditions[index]

    def add_condition(self, condition):
        """Adds a condition to to the model.

        :param condition_data the condition data to add
        """

        self.condition_data.conditions.append(condition)
        condition.setOwner(self.condition_data)
        tracker = ConditionTracker()
        mode = gremlin.shared_state.current_mode
        container = self.container
        input_item = self.input_item
        if input_item:
            data = ConditionTrackerData(mode, input_item, container, condition, rule=ActivationRule.All)
            tracker.registerCondition(data)
        self.data_changed.emit()
        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.emit(container)

    def delete_condition(self, condition):
        """Deletes a condition from the model.

        Attempts to locate the provided condition and deletes it, if it is
        present.

        :param condition the condition to remove.
        """
        if condition in self.condition_data.conditions:
            self.condition_data.conditions.remove(condition)

        if self.input_item:
            tracker = ConditionTracker()
            tracker.unregisterCondition(condition)

        container = self.container

        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.emit(container)
        self.data_changed.emit()

    @property
    def rule(self):
        """Returns the current application rule for the conditions.

        :return current application rule of conditions
        """
        return self.condition_data._rule

    @rule.setter
    def rule(self, rule):
        """Sets the application rule of the conditions.

        :param rule the new application type
        """
        self.condition_data._rule = rule


class BaseActivationCondition(gremlin.base_classes.BaseCallbacks):
    """Dictates under what circumstances an associated code can be executed."""

    activation_condition_modified = Signal()

    rule_lookup = {
        # String to enum
        "all": ActivationRule.All,
        "any": ActivationRule.Any,
        # Enum to string
        ActivationRule.All: "all",
        ActivationRule.Any: "any",
    }

    condition_lookup = {
        "keyboard": BaseKeyboardCondition,
        "joystick": BaseJoystickCondition,
        "vjoy": BaseVJoyCondition,
        "action": BaseInputActionCondition,
        "state": BaseStateCondition,
        "mode": BaseModeCondition,
    }

    def __init__(self, conditions: AbstractCallbackModel, rule):
        """Creates a new instance."""
        super().__init__()
        import gremlin.input_item

        assert isinstance(conditions, AbstractCallbackModel), "invalid condition model"

        self._rule = rule
        self.conditions = conditions
        self._id = gremlin.util.get_guid()
        self._container = None  # owning container

    def setContainer(self, container):
        """sets the owning container"""
        self._container = container

    @property
    def container(self):
        """gets the owning container of this activation condition"""
        return self._container

    @property
    def rule(self) -> ActivationRule:
        # rule for the activation condition
        return self._rule

    @rule.setter
    def rule(self, value: ActivationRule):
        self._rule = value

    @property
    def id(self):
        """unique ID for this condition, persisted"""
        return self._id

    def setId(self, value: str):
        """sets the ID"""
        self._id = value

    def from_xml(self, node, data=None, extra_data=None):
        """Extracts activation condition data from an XML node.

        :param node: the XML node to parse
        :param data: tuple containing (input_item, container) associated with this condition
        """
        # import gremlin.base_profile
        # import gremlin.ui.ui_common
        import gremlin.shared_state

        if "condition_id" in node.attrib:
            self._id = node.get("condition_id")

        rule = BaseActivationCondition.rule_lookup[safe_read(node, "rule", str, "")]
        tracker = ConditionTracker()
        mode_node = node
        while mode_node is not None and mode_node.tag not in ("mode", "state"):
            mode_node = mode_node.getparent()
        if mode_node is not None:
            if mode_node.tag == "state":
                mode = gremlin.shared_state.master_mode
            else:
                mode = mode_node.get("name")
        else:
            mode = gremlin.shared_state.edit_mode
        assert data is not None, f"XML: error: data not provided for activation condition - offending line: {node.sourceline}"
        input_item, container = data
        self.rule = rule

        for cond_node in node.findall("condition"):
            condition_type = safe_read(cond_node, "condition-type", str, "")
            condition = BaseActivationCondition.condition_lookup[condition_type]()
            condition.from_xml(cond_node, data)
            self.conditions.append(condition)
            condition.setOwner(self)
            if input_item:
                item = ConditionTrackerData(mode, input_item, container, condition, rule)
                tracker.registerCondition(item)

    def to_xml(self):
        """Returns an XML node containing the activation condition information.

        :return XML node containing information about the activation condition
        """
        node = lxml.etree.Element("activation-condition")
        node.set("rule", BaseActivationCondition.rule_lookup[self._rule])
        node.set("condition_id", self._id)

        for condition in self.conditions:
            # save the condition, valid or not so the data is saved
            condition_node = condition.to_xml()
            node.append(condition_node)
        return node

    def condition_name(self):
        return f"Activation Condition: [{self.id}] rule: {self._rule.name} contains: {len(self.conditions)} condition(s)"

    def __str__(self):
        return f"Activation Condition: [{self.id}] rule: {self._rule.name} contains: {len(self.conditions)} condition(s)"


class MultiModeAbstractAction(AbstractAction):
    """indicates the action works with multiple modes"""

    def __init__(self, parent):
        super().__init__(parent)
        self._is_multi_mode_action = True  # indicate this is a multimode action


class ActionSets(AbstractCallbackModel):
    """contains ActionSet objects for a container"""

    def __init__(self, container: AbstractContainer, description: str = None, data=None):
        assert isinstance(container, AbstractContainer), "Invalid container object"

        super().__init__(allowed_types=(ActionSet,), model_description=f"ActionSets model for container: [{container.debug_name}]", data=container)

        self._container = container
        self._input_item = self._container.input_item
        self._description = description
        self._data = data

        # add at least one action set object
        # load from container

        if self.count() == 0:
            # create at least one action set
            self.setItemAt(0, ActionSet())
        assert self.count()
        assert isinstance(self._input_item, InputItem), "Invalid input item for container"

    def append(self, item):
        """override for data checking"""
        if isinstance(
            item,
            (
                list,
                tuple,
            ),
        ):
            item = ActionSet.fromList(item)
        super().add(item)

    def ensureCount(self, count: int):
        """ensures the actions sets has at least count action set object"""
        if count > 0:
            while self.count() < count:
                self.append(ActionSet())

    def clear(self):
        """clears all the actions"""
        action_set: ActionSet
        for action_set in self:
            action_set.clear()
        super().clear()

    @property
    def description(self) -> str:
        return self._description

    @description.setter
    def description(self, value: str):
        self._description = value

    def actionCount(self) -> int:
        """returns the total number of actions in all action set"""
        return sum(action_set.count() for action_set in self)

    def getActions(self):
        """gets a list of all the actions in this actionsets"""
        return [action for action_set in self for action in action_set]

    def to_xml(self, parent_node: lxml.etree.Element):
        """writes the actions in the action set out"""

        for action_set in self:
            node = action_set.to_xml()
            node.set("set-guid", write_guid(self._id))
            if self._description:
                node.set("set-description", html.escape(self._description))
            parent_node.append(node)
        return parent_node

    def from_xml(self, node, extra_data: dict = None, data=None):
        """reads container actions sets"""
        self.clear()
        set_read = False
        for child in node.xpath("./action-set"):
            action_set = ActionSet(data)
            action_set.from_xml(child, self._container, self._input_item, extra_data, data)
            self.append(action_set)

            if not set_read:
                # read actions set info on first node
                if "s-guid" in node.attrib:
                    self._id = read_guid(node, "guid")
                    set_read = True
                if "s-description" in node.attrib:
                    self._description = html.unescape(node.get("description"))
                    set_read = True

        if not self.count():
            # add at least one action sett
            self.add(ActionSet())


class ActionSetsView(AbstractView):
    """widget that display container action sets"""

    def __init__(
        self,
        profile: gremlin.base_profile.Profile,
        container: AbstractContainer,
        view_mode: str | ContainerViewTypes = ContainerViewTypes.Action,
        interaction_callback: Callable = None,
        add_callback: Callable = None,
        paste_callback: Callable = None,
    ):
        """init

        :param profile: the profile to use
        :param container: the container to display actions sets for
        :param mode: the display mode of the view ("action","condition")
        :param interaction_callback: the callback to execute when the user interacts with the action order
        :param add_callback: handler for adding actions (leave blank unless custom)
        :param paste_callback: handler for pasting actions (leave blank unless custom)
        """

        assert isinstance(profile, gremlin.base_profile.Profile), "invalid profile"
        assert isinstance(container, AbstractContainer), "invalid container"
        assert isinstance(container.action_sets, ActionSets), "container does not have action sets model"
        assert isinstance(interaction_callback, Callable) if interaction_callback is not None else True, "invalid interaction callback"
        assert isinstance(add_callback, Callable) if add_callback is not None else True, "invalid add callback"
        assert isinstance(paste_callback, Callable) if paste_callback is not None else True, "invalid paste callback"
        assert view_mode in ("action", "condition", "virtual") if isinstance(view_mode, str) else True, (
            "invalid view mode - expecting 'action' or 'condition' or 'virtual' "
        )

        super().__init__(container.action_sets)

        self.profile = profile
        self.container = container
        self._widgets = []  # list of created widgets
        self._view_widgets = []  # list of all created view widgets
        self._mode = view_mode
        self.main_layout = QtWidgets.QVBoxLayout(self)

        self._interaction_callback = interaction_callback
        self._add_callback = add_callback
        self._paste_callback = paste_callback

        if isinstance(view_mode, str):
            match view_mode:
                case "action":
                    self._view_type = ContainerViewTypes.Action
                case "condition":
                    self._view_type = ContainerViewTypes.Conditions
                case "virtual":
                    self._view_type = ContainerViewTypes.VirtualButton
        else:
            self._view_type = view_mode

        self._create_ui()  # create the UI

    def _create_action_set_widget(
        self,
        model: ActionSet,
        label=None,
        view_type=ContainerViewTypes.Action,
        icon=None,
        icon_size=24,
    ):
        """Adds an action widget to the container widget.

        :param action_set_data: data of the actions which form the action set
        :param label the label:  to show in the title
        :param view_type visualization type
        :
        :return wrapped widget
        """

        gremlin.util.assert_ui_thread, "not on ui thread"

        assert isinstance(model, ActionSet), "invalid action set model provided"

        # if action_set_data in self._action_widget_map:
        #     return self._action_widget_map[action_set_data]

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info(f"ContainerWidget: created action set model: {model.debug_name}")

        action_set_view = ActionSetView(
            profile=gremlin.shared_state.current_profile,
            container=self.container,
            model=model,
            label=label,
            view_type=view_type,
            icon=icon,
            icon_size=icon_size,
            interaction_callback=self._interaction_callback,
            parent=self,
        )

        # action_set_view.interacted.connect(lambda x: self._handle_interaction(action_set_view, x))

        return action_set_view

    def _create_action_selector(self, target_actionset: ActionSet = None):
        """creates an action selector"""
        input_item = self.container.input_item
        device = gremlin.joystick_handling.getDevice(input_item.device_guid)
        input_type = gremlin.types.DeviceType.VJoy if device.is_virtual else input_item.input_type

        # not a vjoy device
        action_selector = ActionSelector(input_type=input_type, input_item=input_item, callback=self._handle_new_action, data=target_actionset)

        return action_selector

    def _handle_new_action(self, action: str | AbstractAction, mode: str, target_actionset: object):
        """handles new action"""
        match mode:
            case "add":
                self._add_action(action, target_actionset)
            case "paste":
                self._paste_action(action, self.container, target_actionset)

    def _handle_interaction(self, widget: ActionSetView, action: AbstractAction):
        """handles interactions such as moving actions up/down"""
        if self._interaction_callback:
            self._interaction_callback(widget, action)

    def _add_action(self, action_name: str, target_actionset: ActionSet = None):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """
        wm = WorkManager()
        wm.submit(callback=self._add_action_worker, args=(action_name, target_actionset))

    def _paste_action(self, action: AbstractAction | str, container: AbstractContainer, target_actionset: ActionSet = None):
        """paste action"""
        wm = WorkManager()
        wm.submit(callback=self._paste_action_worker, args=(action, container, target_actionset))

    def _paste_action_worker(self, args):
        action, container, target_actionset = args
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action = plugin_manager.duplicate(action, self.container)

        if target_actionset is not None:
            action_set: ActionSet = target_actionset
        else:
            action_set = self.model[0]  # first action set

        action_set.add(action)
        # container.add_action(action_item)

    def _add_action_worker(self, args):
        """worker object for adding actions"""
        from gremlin.clipboard import Clipboard

        action_data, target_actionset = args

        if action_data is None:
            return
        if not Shiboken.isValid(self):
            return

        if isinstance(action_data, str):
            action_name = action_data
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action = plugin_manager.get_class(action_name)(self.container)
        elif isinstance(action_data, Clipboard):
            # paste operation
            if action_data.is_action:
                # verify the action in the clipboard is appropriate for this input

                action = plugin_manager.duplicate(action_data.data, self.container)

        if target_actionset is not None:
            action_set: ActionSet = target_actionset
        else:
            action_set = self.model[0]  # first action set

        action_set.add(action)

        # self._container.add_action(action, 0) # for basic containers, add the action to action set 0

    def _create_ui(self):
        """recreates the UI to view action sets in a container"""
        self._view_widgets.clear()
        for widget in self._widgets:
            widget.hide()
            self.main_layout.removeWidget(widget)
            gremlin.util.delete_widget(widget)

        action_set: ActionSet
        for index, action_set in enumerate(self.model):
            widgets = [
                gremlin.ui.ui_common.QHorizontalLine(),
                QtWidgets.QLabel(action_set.description or f"Action Set [{index}]"),
            ]

            widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)
            self.main_layout.addWidget(widget)
            self._widgets.append(widget)

            widget = self._create_action_set_widget(model=action_set, label=self.container.name, view_type=self._view_type)

            # offset it
            widget.setContentsMargins(5, 0, 0, 0)
            self.main_layout.addWidget(widget)
            self._widgets.append(widget)
            self._view_widgets.append(widget)

            # widget = None

            # match self._view_type:
            #     case ContainerViewTypes.Action:
            #         # add a selector to add or paste a new action
            #         widget = self._create_action_selector()
            #     case ContainerViewTypes.Conditions:
            #         pass
            #         # widget = self._create_condition_selector()
            #     case ContainerViewTypes.VirtualButton:
            #         pass
            #         # widget = self._create_virtual_button_selector()

            # if widget:
            #     self.main_layout.addWidget(widget)
            #     self._widgets.append(widget)

            self.main_layout.addStretch()

    def redraw(self, force: bool = False):
        # assert inspect.stack()[1].function == "_fireChanged", "redraw should only be called due to a model trigger"
        gremlin.util.InvokeUiMethod(self._redraw_ui, force)  # ensure on UI thread

    def _redraw_ui(self, force: bool = False):
        """redraws the entire view - must be on UI thread"""
        if gremlin.shared_state.is_redraw_suspended():
            return  # don't redraw

        changed = force or self.modelChanged
        if changed:
            self._create_ui()


class ActionSetView(AbstractView):
    """widget that displays an action set defined in a container"""

    # Signal emitted when an interaction is triggered on an action
    interacted = Signal(Interactions)

    def __init__(
        self,
        profile: gremlin.base_profile.Profile,
        container: AbstractContainer,
        model: ActionSet,
        label: str = None,
        view_type=ContainerViewTypes.Action,
        icon=None,
        icon_size=24,
        interaction_callback: Callable = None,
        parent=None,
    ):
        """
        Creates a widget that contains all actions in a given action set and can be interacted with.  Displays actions, condition or virtual button setup.

        :param profile: current profile
        :param container: the container the action set belongs to
        :param model: the action set model to use for all the actions
        :param label: display label
        :param view_type: the view type, defaults to Action, can be Condition or Virtual button
        :param icon : optional icon to display
        :param icon_size: optional icon size in pixels
        :param interaction_callback: optional callback when the user interacts with the view sends (action_set: ActionSet, interaction: Interactions)

        """

        assert isinstance(profile, gremlin.base_profile.Profile), "invalid profile"
        assert isinstance(container, AbstractContainer), "invalid container"
        assert isinstance(model, ActionSet), "invalid model"
        assert isinstance(interaction_callback, Callable) if interaction_callback is not None else True, "invalid interaction callback"

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info(f"Create action set view for model: {model.debug_name}")

        super().__init__(model=model, parent=parent)

        self.pushSuspended()  # supend redraw

        self._interaction_callback = interaction_callback

        self._redraw_lock = False
        self.profile = profile
        self.container = container  # owning container
        self._widget_map = {}  # holds action widgets that were created

        self.has_edit_controls = False  # assume no edit controls
        self.view_type = view_type
        self._main_layout = QtWidgets.QVBoxLayout(self)

        self._main_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine(color=gremlin.ui.ui_common.Color.grayColor()))
        self._main_layout.addWidget(QtWidgets.QLabel("ActionSetView:"))

        self.allowed_interactions = container.interaction_types
        self.label = label
        self._selected = False  # true if the object is selected
        title = None

        if self.label:
            if icon:
                title = gremlin.ui.ui_common.QIconLabel(icon, icon_size=icon_size, text=f"{self.label} action:")
            else:
                title = QtWidgets.QLabel(f"{self.label} action:")
        elif icon:
            title = gremlin.ui.ui_common.QIconLabel(icon, icon_size=icon_size)

        if title:
            self._main_layout.addWidget(title)

        left_panel, left_layout = gremlin.ui.ui_common.getVContainer()
        right_panel, right_layout = gremlin.ui.ui_common.getVContainer()
        right_panel.setMaximumWidth(0)  # use no space by default unless needed

        action_container, action_layout = gremlin.ui.ui_common.getGridContainer()
        action_layout.addWidget(left_panel, 0, 0)
        action_layout.addWidget(right_panel, 0, 1)

        add_action_container, add_action_layout = gremlin.ui.ui_common.getVContainer()

        widgets = [action_container, add_action_container]
        content_widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)

        # self.collapsible_container.setContent(content_widget)
        self._main_layout.addWidget(content_widget)

        self.setObjectName(f"ActionSetView: {'n/a' if label is None else label}")

        verbose_ui = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose_ui:
            syslog.info(f"ActionSetView: create: {self.objectName()}")

        # Create group box contents
        self._action_widget, self._action_layout = gremlin.ui.ui_common.getVContainer()

        # Only show edit controls in the basic tab
        if self.view_type == ContainerViewTypes.Action:
            self._create_edit_controls()
            left_layout.addWidget(self._action_widget)
            if self.has_edit_controls:
                right_layout.addWidget(self.controls_widget)
                right_panel.setMaximumWidth(34)
                right_panel.setMinimumWidth(34)
        else:
            left_layout.addWidget(self._action_widget)

        # Only permit adding actions from the basic tab and if the tab is
        # not associated with a vJoy device

        if self.view_type == ContainerViewTypes.Action and container.get_device_type() != DeviceType.VJoy:
            input_type = None
            if hasattr(profile, "override_input_type"):
                # override specified
                input_type = container.override_input_type
            else:
                input_type = container.parent.getInputType()

            if input_type is None:
                input_type = container.input_item.get_input_type()

            self.action_selector = ActionSelector(input_type, container.input_item)
            self.action_selector.inputItem = container.input_item
            self.action_selector.action_added.connect(self._add_action)
            self.action_selector.action_paste.connect(self._paste_action)
            widget = gremlin.ui.ui_common.getHContainer(self.action_selector, widget_only=True)
            add_action_layout.addWidget(widget)

        self._left_layout = left_layout
        self._right_layout = right_layout

        self._widget_map = {}  # maps the model ID to the wrapper object created in the layout
        self._stacked_widget = QtWidgets.QStackedWidget()
        self._left_layout.addWidget(self._stacked_widget)

        self._blank_widget = QtWidgets.QLabel("Please add an action to this container.")
        widget = gremlin.ui.ui_common.getVContainer(self._blank_widget, widget_only=True)
        self._stacked_widget.addWidget(widget)  # index 0 / page 1 of the stacked widget

        # widget and layout that holds the action widgets on page 2 of the stacked widget
        self._container_widget = None
        self._container_layout = None

        self._drawn_once = False  # only load widgets on demand when a redraw is requested

        self.popSuspended()  # supend redraw

        self.refreshModel()  # load the data

    @property
    def selected(self) -> bool:
        """returns selected state"""
        return self._selected

    @selected.setter
    def selected(self, value: bool):
        """sets selected state"""
        if value and not self._selected:
            self._selected = True
            background_color = gremlin.ui.ui_common.Color.selectedDockTabBackgroundColor()
            self.setStyleSheet = f"background: {background_color};"
        elif not value and not self._selected:
            self._selected = False
            self.setStyleSheet("")

    def _get_action_widget(self, data: AbstractAction):
        """gets the action widget for the action"""
        if data.action_id not in self._widget_map:
            # create the action widget from the plugin
            widget = data.widget(data)

            widget.action_modified.connect(self.model.data_changed.emit)

            self._widget_map[data.action_id] = widget
        else:
            widget = self._widget_map[data.action_id]
        return widget

    def create_ui(self):
        """(re)creates the contents - content is displayed on page 2 of the stacked container"""
        import gremlin.config
        import gremlin.joystick_handling

        clipboard = gremlin.clipboard.Clipboard()
        clipboard.disable()

        try:
            if self._stacked_widget.count() == 2:
                self._action_widget = None
                self._widget_map.clear()
                widget = self._stacked_widget.widget(1)
                widget.hide()
                self._stacked_widget.removeWidget(widget)
                gremlin.util.delete_widget(widget)

            verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)

            self._container_widget, self._container_layout = gremlin.ui.ui_common.getVContainer()
            self._stacked_widget.addWidget(self._container_widget)  # index 1

            self._action_widget = self._container_widget

            with QtCore.QSignalBlocker(self.model):  # .data_changed.blocked():
                for model_index in range(self.model.rows()):
                    data = self.model.data(model_index)

                    # this will take a while potentially
                    # if not push_cursor:
                    #     gremlin.util.pushCursor()
                    #     push_cursor = True

                    if verbose:
                        object_name = self.objectName()
                        device = gremlin.joystick_handling.getDevice(self.container.hardware_device_guid)
                        syslog.info(
                            f"ActionSet: create {self.view_type.name} widget: device [{device.name}] input type: [{self.container.hardware_input_type.name}] input id: [{self.container.hardware_input_id}] start: {object_name} for action id [{data.id}]  "
                        )

                    match self.view_type:
                        case ContainerViewTypes.Action:
                            widget = self._get_action_widget(data)
                            wrapped_widget = BasicActionWrapper(widget)
                            wrapped_widget.closed.connect(self._create_closed_cb(widget))

                        case ContainerViewTypes.Conditions:
                            # create the action widget from the plugin
                            widget = self._get_action_widget(data)
                            wrapped_widget = ConditionActionWrapperWidget(widget)

                        case _:
                            syslog.error(f"Invalid view type in ActionSetview: don't know how to handle: {self.view_type}")
                            return

                    # save the reference widget
                    self._widget_map[data.id] = wrapped_widget
                    # add the new widget to the layout
                    self._container_layout.addWidget(wrapped_widget)

        finally:
            clipboard.enable()

    def _show_blank(self):
        if self._stacked_widget.currentIndex() != 0:
            verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
            if verbose:
                syslog.info(f"ActionSetView: show blank {self._input_display()}")
            self._stacked_widget.setCurrentIndex(0)

    def _show_content(self):
        if self._model.count() == 0:
            # no actions to show
            self._show_blank()
        else:
            if self._stacked_widget.currentIndex() != 1:
                verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
                if verbose:
                    syslog.info(f"ActionSetView: show content device {self._input_display()}")
                self._stacked_widget.setCurrentIndex(1)

    def _input_display(self) -> str:
        """display details for the mapped input"""
        return f"[device [{self.container.hardware_device_name}] type: [{self.container.hardware_input_type.name} input: [{self.container.hardware_input_id}] container: [{self.container.name}] id: [{self.container.id}]"

    def redraw(self):
        # assert inspect.stack()[1].function == "_fireChanged","redraw should only be called due to a model trigger"
        gremlin.util.InvokeUiMethod(self._redraw_ui)  # ensure on UI thread

    def _redraw_ui(self):
        """Redraws the entire view.  must be on UI thread"""
        import gremlin.clipboard

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info(f"ActionSetView: redraw {self._input_display()}")

        widget_count = len(self._widget_map)
        model_count = self.model.count()

        if not self._drawn_once or self.modelChanged() or widget_count != model_count:
            # redraw if first time, no container layout created, or model size is different
            if verbose:
                syslog.info(f"\tcreate UI for [{model_count}] actions")
            self.create_ui()
            self._drawn_once = True
            self._show_content()
            return  # done

        try:
            clipboard = gremlin.clipboard.Clipboard()
            clipboard.disable()
            verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)

            # if verbose:
            #     object_name = self.objectName()
            #     syslog.info(f"ActionSet: redraw start: {object_name}")

            assert len(self._widget_map) == self.model.count(), "ActionSetView model and UI are not synchronized"

            for model_index in range(self.model.rows()):
                # re-order the display if needed
                data = self.model.data(model_index)
                assert data.id in self._widget_map, f"ActionSetView model and UI are not synchronized: widget not found for action id [{data.id}]"

                widget = self._widget_map[data.id]
                widget_index = self._container_layout.indexOf(widget)
                if model_index != widget_index:
                    # reorder the display to match model index if needed
                    self._container_layout.removeWidget(widget)
                    self._container_layout.insertWidget(model_index, widget)

                if hasattr(widget, "redraw"):
                    widget.redraw()

            verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)

            # if verbose: syslog.info(f"ActionSet: redraw complete: {object_name}")

        finally:
            clipboard.enable()

    def _add_action(self, action_name):
        import gremlin.plugin_manager
        import gremlin.ui.ui_common

        plugin_manager = gremlin.plugin_manager.ActionPlugins()

        action = plugin_manager.get_class(action_name)(self.container)
        if action.singleton:
            input_item: InputItem = self.container.input_item
            if input_item.is_action:
                gremlin.ui.ui_common.MessageBox(prompt=f"Unable to add [{action_name}].  The action cannot be added to a sub-container.")
                return
            if input_item.hasAction(action_name):
                gremlin.ui.ui_common.MessageBox(prompt=f"Unable to add: [{action_name}]. The action can only appear once per input.")
                return

        self.model.add(action)

    def _paste_action(self, action, container):
        """handles action paste operation"""

        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        if isinstance(action, ObjectEncoder):
            oc = action
            if oc.encoder_type == EncoderType.Action:
                xml = oc.data
                node = lxml.etree.fromstring(xml)
                action_tag = node.tag
                action_tag_map = plugin_manager.tag_map
                new_action = action_tag_map[action_tag](self.container)
                new_action.from_xml(node)
                new_action.setId(get_guid())
                self.model.add_action(new_action)
        else:
            action_item = plugin_manager.duplicate(action, self.container)
            self.model.add(action_item)

    def _create_closed_cb(self, widget):
        """Create callbacks to remove individual containers from the model.

        :param widget the container widget to be removed
        :return callback function to remove the provided widget from the
            model
        """
        return lambda: self._remove_model_action_data(widget.action_data)

    def _remove_model_action_data(self, action_data):
        try:
            self.model.remove_action(action_data)
        except Exception:
            pass

    def _create_edit_controls(self):
        """Creates interaction controls based on the allowed interactions.

        :param allowed_interactions list of allowed interactions
        """
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColorConstants.Red)
        self.has_edit_controls = False

        self.controls_widget = QtWidgets.QWidget()
        self.controls_layout = QtWidgets.QVBoxLayout(self.controls_widget)
        prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
        if Interactions.Up in self.allowed_interactions:
            self.control_move_up = QtWidgets.QPushButton(load_icon(f"{prefix}button_up.png"), "")
            self.control_move_up.clicked.connect(lambda: self._handle_interaction(Interactions.Up))
            self.controls_layout.addWidget(self.control_move_up)
            self.has_edit_controls = True
        if Interactions.Down in self.allowed_interactions:
            self.control_move_down = QtWidgets.QPushButton(load_icon(f"{prefix}button_down.png"), "")
            self.control_move_down.clicked.connect(lambda: self._handle_interaction(Interactions.Down))
            self.controls_layout.addWidget(self.control_move_down)
            self.has_edit_controls = True
        if Interactions.Delete in self.allowed_interactions:
            self.control_delete = gremlin.ui.ui_common.Buttons.getDeleteWidget(
                callback=lambda: self.interacted.emit(Interactions.Delete),
                tooltip="Delete Actions",
            )
            self.controls_layout.addWidget(self.control_delete)
            self.has_edit_controls = True
        if Interactions.Edit in self.allowed_interactions:
            self.control_edit = gremlin.ui.ui_common.Buttons.getEditWidget(callback=lambda: self._handle_interaction(Interactions.Edit))
            self.controls_layout.addWidget(self.control_edit)
            self.has_edit_controls = True
        if Interactions.Copy in self.allowed_interactions:
            self.control_copy = gremlin.ui.ui_common.Buttons.getCopyWidget(callback=lambda: self._handle_interaction(Interactions.Copy))
            self.controls_layout.addWidget(self.control_copy)
            self.has_edit_controls = True

        self.controls_layout.addStretch(1)

    def _handle_interaction(self, interaction: Interactions):
        """called when the user interacts with the UI"""
        if self._interaction_callback:
            self._interaction_callback(interaction)
        self.interacted.emit(interaction)


class ActionSelector(QtWidgets.QWidget):
    """Widget permitting the selection of actions."""

    # Signal emitted when an action is going to be added
    action_added = QtCore.Signal(str)  # add button pressed
    action_paste = QtCore.Signal(object, object)  # paste button pressed ()


    def __init__(self, input_type : InputType,
                  input_item : InputItem,
                  data=None, callback: Callable = None,
                  callback_paste: Callable = None,
                  parent=None):
        """Creates a new selector instance.

        :param input_type the input type for which the action selector is being created
        :param input_item: the mapped input type
        :param callback: optional callback to register when an action is selected (add or paste)  (action_name : str, mode : str ("add","paste), data : object)  - the object is usually the target action set
        :param data: optional data object carried by the selector
        :param parent the parent of this widget
        """
        super().__init__(parent)

        # if not input_type in (InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat):
        #     pass

        assert isinstance(input_item, gremlin.input_item.InputItem), "expected an input item, wrong type passed"

        self._input_item = input_item
        self._input_item.lockedChanged.connect(self._handle_lock_changed)
        # self._input_type = input_type if input_type else self._input_item.getInputType()
        self._input_type = self._input_item.getInputType()
        self._callback_pasted = callback_paste

        self._callbacks = []  # holds callbacks when an action is selected (action_name : str, mode = ("add","paste"), data)
        if callback is not None:
            self.registerCallback(callback)

        self.action_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.action_dropdown.currentIndexChanged.connect(self._action_changed)
        self.refresh()

        self.add_button = gremlin.ui.ui_common.Buttons.getAddWidget(callback=self._handle_add_action, tooltip="Adds the selected action")

        # self.help_widget = Buttons.getHelpWidget(callback = self._handle_help)

        # clipboard
        self.paste_button = gremlin.ui.ui_common.Buttons.getPasteWidget(callback=self._handle_paste_action)
        self.paste_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Minimum)
        self.paste_button.setToolTip("Paste Action")

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.action_label = QtWidgets.QLabel("Actions:")

        widget, _ = gremlin.ui.ui_common.getHContainer(
            [
                self.action_label,
                self.action_dropdown,
                self.add_button,
                # self.help_widget,
                self.paste_button,

            ]
        )

        self.main_layout.addWidget(widget)
        eh = gremlin.event_handler.EventHandler()
        eh.last_action_changed.connect(self._last_action_changed)

        el = gremlin.event_handler.EventListener()
        el.request_action_list_refresh.connect(self._handle_action_list_refresh)

        self.data = data

        self._container = None

        self._handle_lock_changed_ui(self._input_item)  # initial lock state

    def registerCallback(self, callback: Callable):
        """registers a change callback"""
        assert isinstance(callback, Callable), "invalid callback"
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unregisterCallback(self, callback: Callable):
        """unregisters a change callback"""
        assert isinstance(callback, Callable), "invalid callback"
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _fireCallbacks(self, action_name: str, mode: str):
        for callback in self._callbacks:
            callback(action_name, mode, self.data)

    def _cleanup_ui(self):

        el = gremlin.event_handler.EventListener()
        el.request_action_list_refresh.disconnect(self._handle_action_list_refresh)

        eh = gremlin.event_handler.EventHandler()
        eh.last_action_changed.disconnect(self._last_action_changed)

    def _handle_action_list_refresh(self):
        gremlin.util.InvokeUiMethod(self._handle_action_list_refresh_ui)

    def _handle_action_list_refresh_ui(self):
        if Shiboken.isValid(self):
            self.refresh()

    def _handle_lock_changed(self, input_item):
        gremlin.util.InvokeUiMethod(self._handle_lock_changed_ui, input_item)  # ensure on UI thread

    def _handle_lock_changed_ui(self, input_item):
        if Shiboken.isValid(self):
            unlocked = not input_item.locked
            self.add_button.setEnabled(unlocked)
            self.paste_button.setEnabled(unlocked)

    def refresh(self):
        """reloads the selector based on the input"""
        with QtCore.QSignalBlocker(self.action_dropdown):
            self.action_dropdown.clear()
            action_list = self._valid_action_list(self._input_type)
            for name in action_list:
                self.action_dropdown.addItem(name)
            config = gremlin.config.Configuration()
            self.action_dropdown.setCurrentText(config.last_action)
            self.action_dropdown.autoSize()

    @property
    def inputItem(self):
        return self._input_item

    @inputItem.setter
    def inputItem(self, value):
        self._input_item = value

    @QtCore.Slot(object, str)
    def _last_action_changed(self, widget, name):
        if not Shiboken.isValid(self):
            return
        if not Shiboken.isValid(widget):
            return
        if widget != self.action_dropdown:
            with QtCore.QSignalBlocker(self.action_dropdown):
                self.action_dropdown.setCurrentText(name)

    def _action_changed(self):
        """remember the last selection"""

        if not Shiboken.isValid(self):
            return
        name = self.action_dropdown.currentText()
        config = gremlin.config.Configuration()
        config.last_action = name
        if config.sync_last_selection:
            eh = gremlin.event_handler.EventHandler()
            eh.last_action_changed.emit(self.action_dropdown, name)

    def _valid_action_list(self, input_type: InputType):
        """Returns a list of valid actions for this InputItemWidget.
           Get a list of valid actions for the input.
        :return list of valid action names
        """
        action_list = []
        # if self.input_type == InputType.JoystickAxis:
        #     action_list.append("Response Curve")
        # else:

        config = gremlin.config.Configuration()
        convert_vjoy = config.convert_vjoy_remap
        convert_curve = config.convert_response_curve
        _control_enabled = config.show_input_enable

        # all_entries = [entry.name for entry in gremlin.plugin_manager.ActionPlugins().repository.values()]
        for entry in gremlin.plugin_manager.ActionPlugins().repository.values():
            # if entry.tag == "gremlin-control":
            #     pass
            if not entry.input_types or input_type in entry.input_types:
                if convert_vjoy and entry.name == "Remap":
                    continue
                elif convert_curve and entry.name == "Response Curve":
                    continue
                # if entry.name == "Control" and not control_enabled:
                #     continue
                action_list.append(entry.name)
        return sorted(action_list)

    def _handle_help(self):
        """handles the help box on an action"""
        action_name = self.action_dropdown.currentText()
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action = plugin_manager.get_class(action_name)(self._input_item)
        if hasattr(action, "hint"):
            hint = action.hint
        else:
            hint = gremlin.hints.hint.get(action.tag, "")
        if hint:
            gremlin.ui.ui_common.gremlinMessageBox(
                title=f"About the {action_name} action:",
                prompt=hint,
                width=300,
                is_warning=False,
            )

    def _handle_add_action(self, clicked=False):
        """Handles selecting of an action to be added.

        :param clicked flag indicating whether or not the action resulted from
            a click
        """
        action_name = self.action_dropdown.currentText()
        self._fireCallbacks(action_name, "add")
        self.action_added.emit(action_name)



    def _handle_paste_action(self):
        """handle paste action"""
        import gremlin.plugin_manager

        container = None
        # find the container if we can
        parent = self
        while parent is not None:
            if hasattr(parent, "profile_data"):
                if isinstance(parent.profile_data, gremlin.input_item.AbstractContainer):
                    container = parent.profile_data
                    break
            parent = parent.parent()

        if container is None:
            if self.inputItem is None:
                gremlin.ui.ui_common.gremlinMessageBox(
                    title="Invalid paste operation",
                    prompt="Unable to paste action because it is not valid for the current input",
                )
                return
            # create a new basic container
            container_plugins = gremlin.plugin_manager.ContainerPlugins()
            container_tag_map = container_plugins.tag_map
            container = container_tag_map["basic"](self.inputItem)

        action_list = gremlin.plugin_manager.ActionPlugins().fromClipboard(container, self.inputItem)
        if not action_list:
            return

        valid_actions = self._valid_action_list(self._input_type)
        warning = False
        for action in action_list:
            if action.name in valid_actions:
                # valid action - clone it and add it
                # syslog.info("Clipboard paste action trigger...")
                self._fireCallbacks(action, "paste")
                self.action_paste.emit(action, container)

            else:
                warning = True

        if warning:
            gremlin.ui.ui_common.gremlinMessageBox(
                title="Invalid Action type",
                prompt="Unable to paste one or more actions because the action is invalid for the current input",
            )

    def _clipboard_changed(self, clipboard):
        """handles paste button state based on clipboard data"""
        self.paste_button.setEnabled(clipboard.is_action)
        """ updates the paste button tooltip with the current clipboard contents"""
        if clipboard.is_action:
            self.paste_button.setToolTip(f"Paste action ({clipboard.data.name})")
        else:
            self.paste_button.setToolTip("Paste action (not available)")


class ContainerSelector(QtWidgets.QWidget):
    """Allows the selection of a container type."""

    # Signal emitted when a container type is selected
    container_added = Signal(str)  # fires when a container is added (name of the container)
    container_copy = Signal()  # copy all containers
    container_paste = Signal(object, object)  # paste containers (clipboard data, extra_data [optional])
    container_delete = Signal()  # delete all containers
    container_from_template = Signal(dict)  # load a new container from template, passes a dictionary (can be null) of data items
    container_to_template = Signal(object)  # saves the mappings to a template, passes the input_item as the parameter

    def __init__(self, input_type, is_axis=False, data=None, parent=None):
        """Creates a new selector instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.input_type = input_type
        self.is_axis = is_axis
        self.data = data  # input item

        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.addWidget(QtWidgets.QLabel("Container"))

        self.container_dropdown = gremlin.ui.ui_common.QDataComboBox()

        self.add_container_widget = gremlin.ui.ui_common.Buttons.getAddWidget(tooltip="Adds the selected container", callback=self._add_container)

        # self.help_widget = gremlin.ui.ui_common.Buttons.getHelpWidget(callback = self._handle_help)

        self.save_template_widget = gremlin.ui.ui_common.Buttons.getSaveWidget(
            callback=self._save_container_to_template,
            tooltip="Save mappings to template",
        )

        self.load_template_widget = gremlin.ui.ui_common.Buttons.getFolderWidget(
            callback=self._load_container_from_template,
            tooltip="Load mappings from template",
        )

        self.data.lockedChanged.connect(self._handle_lock_changed)

        default_container = gremlin.config.Configuration().last_container
        self.container_dropdown.setCurrentText(default_container)
        self.container_dropdown.currentIndexChanged.connect(self._container_changed)

        # clipboard
        self.copy_button_widget = gremlin.ui.ui_common.Buttons.getCopyWidget(callback=self._copy_container, tooltip="Copy container(s)")
        self.paste_button_widget = gremlin.ui.ui_common.Buttons.getPasteWidget(callback=self._paste_container, tooltip="Paste container(s)")
        self.paste_button_widget.data = self.data  # input item doing the paste

        # delete all containers
        self.delete_button = gremlin.ui.ui_common.Buttons.getDeleteWidget(
            callback=self._delete_container,
            tooltip="Delete container(s)",
        )

        widgets = [
            self.container_dropdown,
            self.add_container_widget,
        ]

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.main_layout.addWidget(widget)

        # self.main_layout.addWidget(self.container_dropdown)
        # self.main_layout.addWidget(self.help_widget)
        # self.main_layout.addWidget(self.add_container_widget)

        self.main_layout.addWidget(self.save_template_widget)
        self.main_layout.addWidget(self.load_template_widget)
        self.main_layout.addWidget(self.copy_button_widget)
        self.main_layout.addWidget(self.paste_button_widget)
        self.main_layout.addWidget(self.delete_button)

        self.refresh(data)

        self._handle_lock_changed_ui(self.data)

        eh = gremlin.event_handler.EventHandler()
        eh.last_container_changed.connect(self._last_container_changed)

    def _handle_lock_changed(self, input_item):
        gremlin.util.InvokeUiMethod(self._handle_lock_changed_ui, input_item)  # ensure on UI thread

    def _handle_lock_changed_ui(self, input_item):
        if Shiboken.isValid(self):
            unlocked = not input_item.locked
            self.load_template_widget.setEnabled(unlocked)
            self.add_container_widget.setEnabled(unlocked)
            self.paste_button_widget.setEnabled(unlocked)
            self.delete_button.setEnabled(unlocked)

    def refresh(self, input_item):
        """reloads the selector based on the input"""
        self.input_type = input_item.input_type
        with QtCore.QSignalBlocker(self.container_dropdown):
            self.container_dropdown.clear()
            for name in input_item.get_valid_container_list():
                self.container_dropdown.addItem(name)
            config = gremlin.config.Configuration()
            self.container_dropdown.setCurrentText(config.last_container)

        enabled = self.data and len(self.data.containers) > 0
        self.save_template_widget.setEnabled(enabled)

    def _last_container_changed(self, widget, name):
        gremlin.util.InvokeUiMethod(self._last_container_changed_ui, widget, name)  # ensure on UI thread

    def _last_container_changed_ui(self, widget, name):
        if not Shiboken.isValid(self):
            return
        if widget != self.container_dropdown:
            with QtCore.QSignalBlocker(self.container_dropdown):
                self.container_dropdown.setCurrentText(name)

    def _container_changed(self):
        """remember the selection"""
        if not Shiboken.isValid(self):
            return
        name = self.container_dropdown.currentText()
        config = gremlin.config.Configuration()
        config.last_container = name
        if config.sync_last_selection:
            eh = gremlin.event_handler.EventHandler()
            eh.last_container_changed.emit(self.container_dropdown, name)

    def _valid_container_list(self, input_type: InputType):
        """Returns a list of valid actions for this InputItemWidget.

        :return list of valid action names
        """
        container_list = []

        for entry in gremlin.plugin_manager.ContainerPlugins().repository.values():
            if not entry.input_types or input_type in entry.input_types:
                if entry.axis_only:
                    # container requires an axis
                    if not self.is_axis:
                        continue
                container_list.append(entry.name)
        return sorted(container_list)

    @QtCore.Slot()
    def _add_container(self, clicked=False):
        """Handles add button events.

        :param clicked flag indicating whether or not the button was pressed
        """
        self.container_added.emit(self.container_dropdown.currentText())

    def _handle_help(self):
        """help button"""
        import gremlin.base_profile

        container_name = self.container_dropdown.currentText()
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()

        input_item = self.data
        container = plugin_manager.get_class(container_name)(input_item)
        if hasattr(container, "hint"):
            hint = container.hint
        else:
            hint = gremlin.hints.hint.get(container.tag, "")
        if hint:
            gremlin.ui.ui_common.MessageBox(
                title=f"About the {container_name} container:",
                prompt=hint,
                width=300,
                is_warning=False,
            )

    def _clipboard_changed(self, clipboard):
        """handles paste button state based on clipboard data"""
        self.paste_button_widget.setEnabled(clipboard.is_container)
        """ updates the paste button tooltip with the current clipboard contents"""
        if clipboard.is_container:
            self.paste_button_widget.setToolTip(f"Paste container ({clipboard.data.name})")
        else:
            self.paste_button_widget.setToolTip("Paste container (not available)")

    @QtCore.Slot()
    def _paste_container(self):
        """handle paste containern"""
        clipboard = Clipboard()
        widget = self.sender()
        input_item = widget.data
        extra_data = input_item.toExtraData()

        # validate the clipboard data is an action and is of the correct type for the input/container
        if clipboard.is_container:
            self.container_paste.emit(clipboard.data, extra_data)

    @QtCore.Slot()
    def _copy_container(self):
        """fires the copy container"""
        self.container_copy.emit()

    @QtCore.Slot()
    def _delete_container(self):
        """delete container"""
        self.container_delete.emit()

    @QtCore.Slot()
    def _save_container_to_template(self):
        """saves a complete mapping to a template"""
        input_item: InputItem = self.data
        self.container_to_template.emit(input_item)

    @QtCore.Slot()
    def _load_container_from_template(self):
        """loads container from template"""
        input_item: InputItem = self.data
        extra_data = input_item.toExtraData()
        self.container_from_template.emit(extra_data)


class ConditionTrackerInfo:
    def __init__(self, input_item, device_guid, input_id, container, widget):
        self.device_guid = device_guid
        self.input_id = input_id
        self.containerWidget = widget
        self.input_item = input_item
        self.container = container

    @property
    def dock_tabs(self):
        if self.containerWidget:
            return self.containerWidget.dock_tabs
        return None


@gremlin.singleton_decorator.SingletonDecorator
class ConditionStateTracker:
    def __init__(self):
        self._cache = {}  # maps input to condition tab
        self._widget_cache = {}  # tracks the dock tab widget for the registered input_item for this mode
        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.connect(self._condition_state_changed)
        el.condition_changed.connect(self._condition_changed)
        el.container_delete.connect(self._container_delete)
        # el.mapping_changed.connect(self._mapping_changed)
        self._icon_enabled = gremlin.util.load_icon(
            "mdi.checkbox-blank-circle",
            qta_color=gremlin.ui.ui_common.Color.activeColor(),
        )
        self._icon_disabled = gremlin.util.load_icon(
            "mdi.checkbox-blank-circle",
            qta_color=gremlin.ui.ui_common.Color.inactiveColor(),
        )

    def register(self, input_item, container, container_widget):
        """registers a condition tracker"""
        if not isinstance(container, AbstractContainer):
            return

        dock_tab: QtWidgets.QTabWidget = container_widget.dock_tabs

        device_guid = input_item.device_guid
        mode = input_item.profile_mode  # gremlin.shared_state.current_mode
        input_id = input_item.input_id
        if device_guid not in self._cache:
            self._cache[device_guid] = {}
        if mode not in self._cache[device_guid]:
            self._cache[device_guid][mode] = {}
        if input_id not in self._cache[device_guid][mode]:
            self._cache[device_guid][mode][input_id] = {}
        info = ConditionTrackerInfo(input_item, device_guid, input_id, container, container_widget)
        self._cache[device_guid][mode][input_id][container.id] = info

        enabled = info.input_item.hasConditions()
        self.set_condition_tab_state(dock_tab, enabled)

    def unregister(self, input_item, container):
        """unregisters a condition tracker"""
        if not isinstance(container, AbstractContainer):
            return
        assert isinstance(container, AbstractContainer)
        device_guid = input_item.device_guid
        mode = input_item.profile_mode  # gremlin.shared_state.current_mode
        input_id = input_item.input_id
        if device_guid in self._cache:
            if mode in self._cache[device_guid]:
                if input_id in self._cache[device_guid][mode]:
                    if container.id in self._cache[device_guid][mode][input_id]:
                        del self._cache[device_guid][mode][input_id][container.id]

    @QtCore.Slot(object)
    def _condition_state_changed(self, container):
        if not isinstance(container, AbstractContainer):
            return
        device_guid = container.hardware_device_guid
        input_id = container.hardware_input_id
        mode = gremlin.shared_state.current_mode
        if device_guid in self._cache:
            if mode in self._cache[device_guid]:
                if input_id in self._cache[device_guid][mode]:
                    if container.id in self._cache[device_guid][mode][input_id]:
                        info = self._cache[device_guid][mode][input_id][container.id]
                        enabled = info.input_item.hasConditions()

                        dock_tabs = info.dock_tabs
                        self.set_condition_tab_state(dock_tabs, enabled)

    @QtCore.Slot(object)
    def _condition_changed(self, container):
        device_guid = container.hardware_device_guid
        input_id = container.hardware_input_id
        mode = gremlin.shared_state.current_mode
        if device_guid in self._cache:
            if mode in self._cache[device_guid]:
                if input_id in self._cache[device_guid][mode]:
                    if container.id in self._cache[device_guid][mode][input_id]:
                        info = self._cache[device_guid][mode][input_id][container.id]
                        container_widget: AbstractContainerWidget = info.containerWidget
                        container_widget._update_condition_ui(container)
                        enabled = info.input_item.hasConditions()
                        dock_tabs = info.dock_tabs
                        self.set_condition_tab_state(dock_tabs, enabled)

    @QtCore.Slot(object, object)
    def _container_delete(self, input_item, container):
        if not isinstance(container, AbstractContainer):
            return
        self.unregister(input_item, container)

    @QtCore.Slot()
    def _mapping_changed(self):
        """called when a mapping is changed"""
        # ensure condition "state" is updated following the change

    def set_condition_tab_state(self, dock_tabs: QtWidgets.QTabWidget, enabled: bool):
        """marks the condition tab used or not"""
        if Shiboken.isValid(dock_tabs):
            try:
                for i in range(dock_tabs.count()):
                    if dock_tabs.tabText(i) == "Conditions":
                        tb = dock_tabs.tabBar()
                        icon = self._icon_enabled if enabled else self._icon_disabled
                        tb.setTabIcon(i, icon)
                        break
            except Exception:
                pass


class AbstractContainerWidget(QtWidgets.QDockWidget):
    """Base class for container widgets."""

    # Signal which is emitted whenever the widget is closed
    closed = QtCore.Signal(QtWidgets.QWidget)

    # fires when the container is about to be closed
    closing = QtCore.Signal()

    container_modified = QtCore.Signal()  # container contents changed

    # Maps virtual button data to virtual button widgets
    virtual_axis_to_widget = {
        gremlin.base_buttons.VirtualAxisButton: virtual_button.VirtualAxisButtonWidget,
        gremlin.base_buttons.VirtualHatButton: virtual_button.VirtualHatButtonWidget,
    }

    def __init__(self, input_item: InputItem, container: AbstractContainer, parent=None, view=False):
        """Creates a new container widget object.

        :param input_item: the input item to display containers for
        :param container: the specific container to display
        :param parent: the parent of the widget
        :param view: true if the container uses the new view model for its action sets
        """

        import gremlin.hints
        import gremlin.event_handler
        import gremlin.ui.ui_common
        import gremlin.shared_state

        assert isinstance(input_item, InputItem)
        assert isinstance(container, AbstractContainer)
        super().__init__(parent)

        self._action_widget_map = {}  # cache for action set [input_item] -> widget
        self._use_view = view

        background_color = gremlin.ui.ui_common.Color.containerBackgroundColor()
        css = f"background-color:{background_color}"
        self.setStyleSheet(css)

        (
            self._abstract_container_content_widget,
            self._abstract_container_content_layout,
        ) = gremlin.ui.ui_common.getVContainer(no_stretch=True)

        el = gremlin.event_handler.EventListener()
        el.condition_redraw.connect(
            self._condition_redraw
        )  # hook the condition redraw event so we can remove existing references to the UI going away on redraw
        el.condition_changed.connect(self._condition_changed)  # hook condition changed so we can update the UI

        # el.ui_ready.connect(self._ui_ready)
        self._icon_enabled = gremlin.util.load_icon(
            "mdi.checkbox-blank-circle",
            qta_color=gremlin.ui.ui_common.Color.activeColor(),
        )
        self._icon_disabled = gremlin.util.load_icon(
            "mdi.checkbox-blank-circle",
            qta_color=gremlin.ui.ui_common.Color.inactiveColor(),
        )

        self.container = container

        # register for container action set changes
        container.registerChangeCallback(self._handle_container_changed)

        self.input_item = input_item
        self.action_widgets: list[ActionSetView] = []

        mode = container.get_mode()
        if mode == gremlin.shared_state.master_mode:
            mode = "[Master]"
        if hasattr(container, "hint"):
            hint = container.hint
        else:
            hint = gremlin.hints.hint.get(self.container.tag, "")
        self._title_bar_widget = TitleBar(
            f"{self._get_window_title()} ({mode})",
            hint,
            self._container_remove,
            self._copy_container,
            data=container,
        )

        self.title_frame_widget = gremlin.ui.ui_common.QBorderWidget()
        self.title_frame_widget.addWidget(self._title_bar_widget)

        # self.title_frame_widget.setMaximumWidth(600)
        self.title_frame_widget.setMinimumWidth(200)

        self.title_frame_widget.setBackgroundColor(gremlin.ui.ui_common.Color.containerBackgroundColor())
        self.collapsible_widget = gremlin.ui.ui_common.QCollapsible(title_widget=self.title_frame_widget)
        self.collapsible_widget.toggled.connect(self._handle_toggled)

        # self.setTitleBarWidget(self._title_bar_widget)
        self.setTitleBarWidget(self.collapsible_widget)

        # Create tab widget to display various UI controls in
        self.dock_tabs = gremlin.ui.ui_common.QDataTab()
        self.dock_tabs.setStyleSheet(gremlin.ui.ui_common.Color.cssTab())
        # self.dock_tabs.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)

        background_color = gremlin.ui.ui_common.Color.selectedDockTabBackgroundColor()
        self.setStyleSheet = f"QDockWidget: {{ background-color: {background_color}; }}"

        self.dock_tabs.setStyleSheet(f"QTabBar::tab:selected {{ background-color: {background_color}; }}")

        self.dock_tabs.setTabPosition(QtWidgets.QTabWidget.East)

        self._abstract_container_content_layout.addWidget(self.dock_tabs)
        self.setWidget(self._abstract_container_content_widget)

        self.dock_tabs.data = self.container  # associated the data tab with the container
        self.activation_condition_widget = None

        # Create the individual tabs
        self._create_action_tab()
        # if self.container.get_device_type() != DeviceType.VJoy:
        if self.container.condition_enabled:
            self._create_activation_condition_tab()
        if self.container.virtual_button_enabled:
            self._create_virtual_button_tab()

        self.dock_tabs.currentChanged.connect(self._tab_changed)

        # Select appropriate tab
        self._select_tab(self.container.current_view_type)

        tracker = ConditionStateTracker()
        tracker.register(self.container.input_item, self.container, self)

        self.container.input_item.lockedChanged.connect(self._handle_lock_changed)

        save_widget = gremlin.ui.ui_common.Buttons.getSaveWidget(tooltip="Save this container to a template", callback=self._save_template)

        # self._title_bar_widget.extra_layout.addWidget(open_widget)
        self._title_bar_widget.extra_layout.addWidget(save_widget)

        # this is for CONTAINER CONDITIONS only (Action conditions are handled elsewhere) - this hooks the condition state tab to the conditions added to the container
        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.connect(self._update_container_ui)

        self.activation_count_widget = None
        # el.condition_state_changed.emit(self.container)

        self._handle_lock_changed_ui(self.container.input_item)

        gremlin.util.singleShot(self._config_visible)

        if self.container.collapsed:
            self.collapsible_widget.collapse(False)
        else:
            self.collapsible_widget.expand(False)

        self.collapsible_widget.setContent(self._abstract_container_content_widget, own=False)

        el = gremlin.event_handler.EventListener()
        el.collapse_all_containers.connect(self._handle_collapse)
        el.expand_all_containers.connect(self._handle_expand)

        # holds change callbacks for the container widget
        self._container_changed_callbacks = []

        self._update_container_ui(self.container)

    def _fireChangeCallbacks(self):
        """fires the change callbacks for this container"""
        for callback in self._container_changed_callbacks:
            callback(self)

    def registerChangeCallback(self, callback: Callable):
        """registers a change callback for this container"""
        assert isinstance(callback, Callable), "invalid callback"
        if callback not in self._container_changed_callbacks:
            self._container_changed_callbacks.append(callback)

    def unregisterChangeCallback(self, callback: Callable):
        """unregisters a change callback for this container"""
        assert isinstance(callback, Callable), "invalid callback"
        if callback in self._container_changed_callbacks:
            self._container_changed_callbacks.remove(callback)

    def _handle_container_changed(self, container):
        """handles a change in a container"""
        self._fireChangeCallbacks()
        self.redrawActionSets()

    def MappingChanged(self):
        self._handle_container_changed(self.container)

    @QtCore.Slot()
    def _handle_toggled(self):
        self.container.collapsed = self.collapsible_widget.isCollapsed()

    def _handle_collapse(self):
        gremlin.util.InvokeUiMethod(self._handle_collapse_ui)

    def _handle_collapse_ui(self):
        """collapse the container - ui thread"""
        self.collapsible_widget.collapse(False)

    def _handle_expand(self):
        gremlin.util.InvokeUiMethod(self._handle_expand_ui)

    def _handle_expand_ui(self):
        """expand the container - ui thread"""
        self.collapsible_widget.expand(False)

    def _config_visible(self):
        if not Shiboken.isValid(self):
            return
        config = gremlin.config.Configuration()
        self._title_bar_widget.setIdVisible(config.show_container_id)

    def _handle_lock_changed(self, input_item):
        """enable/disable based on lock state"""
        gremlin.util.InvokeUiMethod(self._handle_lock_changed_ui, input_item)  # ensure on UI thread

    def _handle_lock_changed_ui(self, input_item):
        """enable/disable based on lock state"""
        if Shiboken.isValid(self):
            self.setEnabled(not input_item.locked)

    @QtCore.Slot()
    def _open_template(self):
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Container template",
            gremlin.shared_state.data_path,
            "XML files (*.xml)",
        )
        if fname and os.path.isfile(fname):
            parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
            try:
                tree = etree.parse(fname, parser=parser)
                root = tree.getRoot()
                if root.tag == "container_template":
                    # get root containers only
                    nodes = root.xpath("//container[not(ancestor::container)]")
                    for node in nodes:
                        container_type = node.get("type")
                        container_plugins = gremlin.plugin_manager.ContainerPlugins()
                        container_tag_map = container_plugins.tag_map
                        valid_containers_names = self.container.get_valid_container_list()

                        # verify the container is valid for the input
                        if container_type in container_tag_map:
                            container_name = container_tag_map[container_type].name
                            if container_name in valid_containers_names:
                                new_container = container_tag_map[container_type](self.item_data)
                                new_container.from_xml(node, self.container)
                                new_container.generateGuids()
                                self.container = new_container
                                if Shiboken.isValid(self):
                                    self.container_modified.emit()

            except Exception:
                pass

    @QtCore.Slot()
    def _save_template(self):
        if not self.container:
            # no container to save
            return
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(
            None,
            "Container template",
            gremlin.shared_state.data_path,
            "XML files (*.xml)",
        )
        if fname:
            # get the container nodes
            node = self.container.to_xml()
            root = etree.Element("container_template")
            root.append(node)
            tree = etree.ElementTree(root)
            try:
                if os.path.isfile(fname):
                    # blitz existing file
                    os.unlink(fname)
                tree.write(fname, pretty_print=True, xml_declaration=True, encoding="utf-8")
            except Exception:
                syslog.error(f"Error writing template to: {fname}")
                return False
            return True

    @QtCore.Slot(object)
    def _update_container_ui(self, container):
        """update the condition icon in the RIGHT PANEL tab"""
        if not Shiboken.isValid(self.dock_tabs):
            return
        dock_tabs = self.dock_tabs
        if dock_tabs.data == container:
            # tracker = ConditionTracker()
            # input_item = container.input_item
            # count = tracker.getInputItemConditionCount(input_item)
            enabled = container.hasConditions()  # tracker.getContainerConditionCount(container) > 0
            # count = self.container.condition_count
            # enabled = count > 0 or enabled
            virtual_enabled = self.container.virtual_button_user_enabled
            try:
                for i in range(dock_tabs.count()):
                    if dock_tabs.tabText(i) == "Conditions":
                        tb = dock_tabs.tabBar()
                        icon = self._icon_enabled if enabled else self._icon_disabled
                        tb.setTabIcon(i, icon)

                    if dock_tabs.tabText(i) == "Virtual Button":
                        tb = dock_tabs.tabBar()
                        icon = self._icon_enabled if virtual_enabled else self._icon_disabled
                        tb.setTabIcon(i, icon)

            except Exception:
                pass

        if self.container == container and self.activation_condition_widget:
            self._update_counts()
            self.activation_condition_widget._update_conditions_ui()

    @QtCore.Slot(object, object)
    def _condition_changed(self, container):
        """called when conditions change"""
        if container.id == self.container.id and self.activation_condition_widget:
            self.activation_condition_widget._update_conditions_ui()

    @QtCore.Slot()
    def _condition_redraw(self, data):
        """occurs when a condition redraws"""

        if self.container == data:
            self._cleanup_ui()

    def _cleanup_ui(self):
        tracker = ConditionStateTracker()
        tracker.unregister(self.container.input_item, self.container)
        self.container.input_item.lockedChanged.disconnect(self._handle_lock_changed)
        self.container.unregisterChangeCallback(self._handle_container_changed)

    def _create_action_tab(self):
        """ create the widget for the container's action tab """
        self._action_tab_container_widget = QtWidgets.QWidget()
        self._action_tab_container_layout = QtWidgets.QVBoxLayout(self._action_tab_container_widget)

        self.action_tab_widget = QtWidgets.QWidget()
        # Create layout and place it inside the dock widget
        self.action_layout = QtWidgets.QVBoxLayout(self.action_tab_widget)

        self._action_tab_container_layout.addWidget(self.action_tab_widget)
        self._action_tab_container_layout.addStretch()

        # Create the actual UI
        self.dock_tabs.addTab(self._action_tab_container_widget, "Actions")
        self._create(self.container)

        if self._use_view:
            profile = gremlin.shared_state.current_profile
            self._action_view = ActionSetsView(profile, self.container, view_mode=ContainerViewTypes.Action)
            self.action_layout.addWidget(self._action_view)
        else:
            # container widget handles the display
            self._create_action_ui()  # ask to create the action UI

    def _create_activation_condition_tab(self):
        # Create widget to place inside the tab

        self.activation_condition_tab_widget = QtWidgets.QWidget()
        self.activation_condition_tab_layout = QtWidgets.QVBoxLayout(self.activation_condition_tab_widget)
        # self.activation_condition_tab_widget.setContentsMargins(0,0,0,0)
        # self.activation_condition_tab_layout.setContentsMargins(0,0,0,0)

        # Create container condition widget
        self.activation_condition_widget = ActivationConditionWidget(self.container)
        self.activation_condition_widget.activation_condition_modified.connect(self.container_modified.emit)

        # Put everything together
        self.activation_condition_tab_layout.addWidget(self.activation_condition_widget)
        self.condition_tab_index = self.dock_tabs.addTab(self.activation_condition_tab_widget, "Conditions")

        # conditions for the actions in the container
        self.action_condition_frame_widget = gremlin.ui.ui_common.QBoxFrame()
        self.action_condition_frame_widget.setContentsMargins(0, 0, 0, 0)

        border_color = gremlin.ui.ui_common.Color.borderColor()
        background_color = gremlin.ui.ui_common.Color.actionBackgroundColor()
        css = f"#frame {{ border 1px solid {border_color}; border-top: none; background-color:{background_color} }}"
        self.action_condition_frame_widget.setStyleSheet(css)

        self.activation_condition_layout = QtWidgets.QVBoxLayout(self.action_condition_frame_widget)
        self.activation_condition_layout.setContentsMargins(0, 0, 0, 0)

        self.activation_count_widget = QtWidgets.QLabel()
        self.activation_condition_layout.addWidget(self.activation_count_widget)

        self.activation_condition_tab_layout.addWidget(self.action_condition_frame_widget)

        # create the action container widget
        # widgets are placed in activation_condition_layout

        if self._use_view:
            profile = gremlin.shared_state.current_profile
            self._condition_view = ActionSetsView(profile, self.container, view_mode=ContainerViewTypes.Conditions)
            self.activation_condition_layout.addWidget(self._condition_view)
        else:
            self._create_condition_ui()
        self.activation_condition_layout.addStretch()
        self.activation_condition_tab_layout.addStretch()

        self._update_counts()

        self._update_selected(self.dock_tabs.currentIndex())

    def _update_condition_ui(self):
        """updates the condition UI tab only"""
        self.activation_condition_widget._update_conditions_ui()

    def _update_counts(self):
        """refreshes counts"""

        if self.activation_count_widget:  # can get called before all is loaded
            if self.container:
                self.activation_count_widget.setText(f"Container conditions ({self.container.condition_count} found):")
            else:
                # not a container
                self.activation_count_widget.setText("Container conditions (N/A):")

    def _create_virtual_button_tab(self):
        # Return if nothing is to be done
        if not self.container.virtual_button:
            return

        # Create widget to place inside the tab
        self.virtual_button_tab_widget = QtWidgets.QWidget()
        self.virtual_button_layout = QtWidgets.QVBoxLayout(self.virtual_button_tab_widget)

        # Create actual virtual button UI
        self.virtual_button_widget = AbstractContainerWidget.virtual_axis_to_widget[type(self.container.virtual_button)](self.container.virtual_button)

        # Put everything together
        self.virtual_button_layout.addWidget(self.virtual_button_widget)
        self.dock_tabs.addTab(self.virtual_button_tab_widget, "Virtual Button")

        self.virtual_button_layout.addStretch(10)

    def _select_tab(self, view_type):
        if view_type is None or self.dock_tabs is None:
            return

        try:
            tab_title = ContainerViewTypes.to_string(view_type).title()
            for i in range(self.dock_tabs.count()):
                if self.dock_tabs.tabText(i) == tab_title:
                    self.dock_tabs.setCurrentIndex(i)

        except gremlin.error.GremlinError:
            return

    def _update_selected(self, index):
        """selection state for the tab page"""
        widget: ActionSetView
        for i, widget in enumerate(self.action_widgets):
            widget.selected = i == index

    def _tab_changed(self, index):
        """called when a device tab is selected"""
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_device
        verbose_detailed = config.verbose_mode_details
        try:
            if verbose:
                syslog.info("Device change begin")
            tab_text = self.dock_tabs.tabText(index)
            self.container.current_view_type = ContainerViewTypes.to_enum(tab_text.lower())
            self._update_selected(index)

        except gremlin.error.GremlinError:
            return
        finally:
            if verbose_detailed:
                syslog.info("Device change end")

    def _get_widget_index(self, widget):
        """Returns the zero based index of the provided widget.

        :param widget the widget for which to return the index
        :return the index of the provided widget, -1 if not present
        """
        index = -1
        for i, entry in enumerate(self.action_widgets):
            if entry == widget:
                index = i
        return index

    def _create_action_set_widget(
        self,
        model: ActionSet,
        label=None,
        view_type=ContainerViewTypes.Action,
        icon=None,
        icon_size=24,
    ):
        """Adds an action widget to the action set (each step in the sequence is its own action set)
        :param action_set_data: data of the actions which form the action set
        :param label the label:  to show in the title
        :param view_type visualization type
        :
        :return wrapped widget
        """

        gremlin.util.assert_ui_thread, "not on ui thread"

        assert isinstance(model, ActionSet), "invalid action set model provided"

        # if action_set_data in self._action_widget_map:
        #     return self._action_widget_map[action_set_data]

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info(f"ContainerWidget: created action set model: {model.debug_name}")

        action_set_view = ActionSetView(
            profile=gremlin.shared_state.current_profile,
            container=self.container,
            model=model,
            label=label,
            view_type=view_type,
            icon=icon,
            icon_size=icon_size,
            parent=self,
        )

        action_set_view.interacted.connect(lambda x: self._handle_interaction(action_set_view, x))

        # Store the view widget so we can use it for interactions later on
        self.action_widgets.append(action_set_view)

        return action_set_view

    def _container_remove(self):
        """Emits the closed event when this widget is being closed."""
        self.closed.emit(self)

    def redrawActionSets(self):
        """redraws the action set widgets"""
        assert gremlin.util.is_ui_thread()
        for widget in self.action_widgets:
            # tell each widget to redraw itself
            if Shiboken.isValid(widget):
                widget._redraw_ui()

    def _copy_container(self, _):
        """Emits the copy clipboard when the widget is being copied"""
        clipboard = Clipboard()
        container = self.container

        # create a new container

        node = container.to_xml()

        xml = lxml.etree.tostring(node)
        encoder = ObjectEncoder(container, xml, container.name, EncoderType.Container)
        encoder.name = container.name
        clipboard.data = encoder
        # clipboard.data = self.container
        verbose = gremlin.config.Configuration().verbose
        if verbose:
            syslog.info(f"container {self.container.name} copied to clipboard")

    def _handle_interaction(self, widget, action):
        """Handles interaction with widgets inside the container.

        :param widget the widget on which the interaction is being carried out
        :param action the action being applied
        """
        raise gremlin.error.MissingImplementationError("AbstractContainerWidget._handle_interaction not implemented in subclass")

    def _create(self, container=None):
        # optional override by subclasses - called before _create_action_ui
        pass

    def _create_action_ui(self, container=None):
        """Creates the UI elements for the widget."""
        if not self._use_view:
            raise gremlin.error.MissingImplementationError("AbstractContainerWidget._create_action_ui not implemented in subclass")

    def _create_condition_ui(self, container=None):
        """Creates the UI elements for the widget."""
        if not self._use_view:
            raise gremlin.error.MissingImplementationError("AbstractContainerWidget._create_condition_ui not implemented in subclass")

    def _update_condition_ui(self):
        """updates the condition UI for the widget"""
        pass

    def _get_window_title(self):
        """Returns the title to show on the widget."""
        # container name
        return self.container.name


class AbstractActionWidget(QtWidgets.QFrame):
    """Base class for all widgets representing actions from the profile
    module."""

    # Signal which is emitted whenever the widget's contents change
    action_modified = Signal()

    def __init__(self, action_data, layout_type=QtWidgets.QVBoxLayout, parent=None):
        """Creates a new instance.

        :param action_data the sub-classed AbstractAction instance
            associated with this specific action.
        :param layout_type type of layout to use for the widget
        :param parent parent widget
        """

        import gremlin.ui.ui_common

        QtWidgets.QFrame.__init__(self, parent)

        css = f"background-color: {gremlin.ui.ui_common.Color.actionBackgroundColor()}"
        self.setStyleSheet(css)

        self.action_data = action_data

        self.main_layout = layout_type(self)

        el = gremlin.event_handler.EventListener()
        # eh.profile_unload.connect(self._cleanup_ui)
        el.action_deleted.connect(self._action_delete)

        self._create(action_data)
        self._create_ui()
        self._populate_ui()

    @QtCore.Slot(object)
    def _action_delete(self, action):
        if self.action_data == action and hasattr(self, "_cleanup_ui"):
            self._cleanup_ui()

    def _create(self, action_data=None):
        """called before create_UI if present"""
        pass

    def _create_ui(self):
        """Creates all the elements necessary for the widget."""
        raise gremlin.error.MissingImplementationError("AbstractActionWidget._create_ui not implemented in subclass")

    def _populate_ui(self):
        """Updates this widget's representation based on the provided
        AbstractAction instance.
        """
        raise gremlin.error.MissingImplementationError("ActionWidget._populate_ui not implemented in subclass")

    def _get_input_type(self):
        """Returns the input type this widget's action is associated with.

        :return InputType corresponding to this action
        """
        return self.action_data.hardware_input_type

    def _get_device_id(self):
        """returns the device ID of the input associated with the action"""
        return self.action_data.hardware_device_guid

    def _get_input_id(self):
        """gets the input id for the input associated with the action"""
        return self.action_data.hardware_input_id

    def _get_profile_root(self):
        """Returns the root of the entire profile.

        :return root Profile instance
        """

        return gremlin.shared_state.current_profile

    @property
    def is_running(self):
        """true if the profile is running"""
        return gremlin.shared_state.is_running


class AbstractActionWrapper(QtWidgets.QDockWidget):
    """Base class for all action widget wrappers.

    The specializations of this class will be used to contain an action
    widget while rendering the UI components needed for a specific view.
    """

    def __init__(self, action_widget, parent=None):
        """Wrapes a widget inside a docking container.

        :param action_widget the action widget to wrap
        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.action_widget = action_widget

        # Create widget sitting in the root of the dock element
        self.dock_widget = QtWidgets.QFrame()
        self.dock_widget.setFrameShape(QtWidgets.QFrame.Box)
        self.dock_widget.setObjectName("frame")
        border_color = gremlin.ui.ui_common.Color.borderColor()
        background_color = gremlin.ui.ui_common.Color.actionBackgroundColor()
        css = f"#frame {{ border 1px solid {border_color}; border-top: none; background-color:{background_color} }}"
        self.dock_widget.setStyleSheet(css)
        self.setWidget(self.dock_widget)

        # Create default layout
        self.main_layout = QtWidgets.QVBoxLayout(self.dock_widget)


class TitleBarButton(QtWidgets.QAbstractButton):
    """Button usable in the titlebar of dock widgets."""

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

    def sizeHint(self):
        """Returns the ideal size of this widget.

        :return ideal size of the widget
        """
        self.ensurePolished()

        size = 2 * self.style().pixelMetric(QtWidgets.QStyle.PM_DockWidgetTitleBarButtonMargin)

        if not self.icon().isNull():
            icon_size = self.style().pixelMetric(QtWidgets.QStyle.PM_SmallIconSize)
            sz = self.icon().actualSize(QtCore.QSize(icon_size, icon_size))
            size += max(sz.width(), sz.height())

        if size < 12:
            size = 12

        return QtCore.QSize(size, size)

    def enterEvent(self, event):
        """Handles the event of the widget being entered.

        :param event the event to handle
        """
        if self.isEnabled():
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Handles the event of leaving the widget.

        :param event the event to handle
        """
        if self.isEnabled():
            self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        """Render the widget based on its current state.

        :param event the rendering event
        """

        # syslog.info("title paint start")
        p = QtGui.QPainter(self)

        options = QtWidgets.QStyleOptionToolButton()
        options.initFrom(self)
        options.state |= QtWidgets.QStyle.State_AutoRaise

        if self.style().styleHint(QtWidgets.QStyle.SH_DockWidget_ButtonsHaveFrame):
            if self.isEnabled() and self.underMouse() and not self.isChecked() and not self.isDown():
                options.state |= QtWidgets.QStyle.State_Raised
            if self.isChecked():
                options.state |= QtWidgets.QStyle.State_On
            if self.isDown():
                options.state |= QtWidgets.QStyle.State_Sunken
            self.style().drawPrimitive(QtWidgets.QStyle.PE_PanelButtonTool, options, p, self)

        options.icon = self.icon()
        options.subControls = QtWidgets.QStyle.SC_None
        options.activeSubControls = QtWidgets.QStyle.SC_None
        options.features = QtWidgets.QStyleOptionToolButton.None_
        options.arrowType = QtCore.Qt.NoArrow
        size = self.style().pixelMetric(QtWidgets.QStyle.PM_SmallIconSize)
        if size < 12:
            size = 12
        options.iconSize = QtCore.QSize(size, size)
        self.style().drawComplexControl(QtWidgets.QStyle.CC_ToolButton, options, p, self)

        p.end()

        # syslog.info("title paint end")


class TitleBar(QtWidgets.QWidget):
    """Represents a titlebar for use with dock widgets.

    This titlebar behaves like the default DockWidget title bar with the
    exception that it has a "help" button which will display some information
    about the content of the widget.
    """

    def __init__(self, label, hint, close_callback, clipboard_cb=None, parent=None, data=None):
        """Creates a new instance.

        :param label the label of the title bar
        :param hint the hint to show if needed
        :param close_cb the function to call when closing the widget
        :param clipboard_cb the function to call for clipboard operations (optional)
        :param parent the parent of this widget
        """
        import gremlin.ui.ui_common
        import gremlin.config
        import gremlin.event_handler

        super().__init__(parent)

        el = gremlin.event_handler.EventListener()
        el.show_container_id_changed.connect(self._show_container_id_changed)

        config = gremlin.config.Configuration()

        self._id_value = None

        self.hint = hint
        width = gremlin.ui.ui_common.get_text_width(label)
        if width > 200:
            fm = QtGui.QFontMetrics(QtGui.QFont())
            e_label = fm.elidedText(label, QtCore.Qt.ElideRight, 200)
        else:
            e_label = label
        self.label = QtWidgets.QLabel(e_label)
        self._close_callback = close_callback
        size = 12

        widget, layout = gremlin.ui.ui_common.getHContainer()
        self.extra_widget = widget
        self.extra_layout = layout

        # help button
        self.help_button = TitleBarButton()

        icon_help = load_icon("mdi.help")
        pixmap_help = icon_help.pixmap(size, size)  # load_pixmap(icon_help)
        if not pixmap_help or pixmap_help.isNull():
            self.help_button.setText("?")
        else:
            icon = QtGui.QIcon()
            pixmap_help = pixmap_help.scaled(size, size, QtCore.Qt.KeepAspectRatio)
            icon.addPixmap(pixmap_help, QtGui.QIcon.Normal)
            self.help_button.setIcon(icon)
        self.help_button.setToolTip("Help")

        self.help_button.clicked.connect(self._show_hint)

        # close button
        self.close_button = TitleBarButton()
        close_icon = load_icon("mdi.delete")

        pixmap_close = close_icon.pixmap(size, size)  # load_pixmap("close.png")
        if not pixmap_close or pixmap_close.isNull():
            self.close_button.setText("X")
        else:
            icon = QtGui.QIcon()
            pixmap_close = pixmap_close.scaled(size, size, QtCore.Qt.KeepAspectRatio)
            icon.addPixmap(pixmap_close, QtGui.QIcon.Normal)
            self.close_button.setIcon(icon)
        self.close_button.setToolTip("Delete Mapping")

        self.close_button.clicked.connect(self._delete_cb)

        # clipboard copy button - only if a handler is given
        if clipboard_cb:
            self.copy_button = TitleBarButton()
            copy_icon = gremlin.ui.ui_common.Icons.copyIcon()
            pixmap_copy = load_pixmap(copy_icon)
            icon = QtGui.QIcon()
            pixmap_copy = pixmap_copy.scaled(size, size, QtCore.Qt.KeepAspectRatio)
            icon.addPixmap(pixmap_copy, QtGui.QIcon.Normal)
            self.copy_button.setIcon(icon)
            self.copy_button.clicked.connect(clipboard_cb)
            self.copy_button.setToolTip("Copy")

        if data is not None and hasattr(data, "id") and config.show_container_id:
            self.id_widget = gremlin.ui.ui_common.QDataLineEdit(width=100)
            self.id_widget.setReadOnly(True)
            self.id_widget.data = data
            self.setIdValue(data.id)
        else:
            self.id_widget = None

        self.comment_widget = gremlin.ui.ui_common.QDataLineEdit()
        self.comment_widget.data = data
        if hasattr(data, "comment"):
            self.comment_widget.setText(data.comment)
        self.comment_widget.textChanged.connect(self._comment_changed)

        if hasattr(data, "priority"):
            self.priority_widget = gremlin.ui.ui_common.QIntLineEdit(data, min_range=0, max_range=1000, value=data.priority, chars=4)
            self.priority_widget.setToolTip("Execution priority.  Lower priority runs first.")
            self.priority_widget.valueChanged.connect(self._priority_changed)
            self.priority_container = gremlin.ui.ui_common.getHContainer(
                self.priority_widget,
                "Priority",
                widget_only=True,
                right_stretch=False,
                left_stretch=False,
            )
        else:
            self.priority_widget = None
            self.priority_container = None

        widgets = [
            self.label,
            self.id_widget,
            "||",
            self.priority_container,
            "Notes:",
            self.comment_widget,
            self.extra_widget,
            self.copy_button if clipboard_cb else None,
            self.help_button,
            self.close_button,
        ]

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True, right_stretch=False, left_stretch=False)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(widget)

        # self.main_layout.setContentsMargins(5, 0, 5, 0)

        # self.main_layout.addWidget(self.label)
        # self.main_layout.addWidget(self.id_widget)
        # if self.priority_container:
        #     self.main_layout.addWidget(self.priority_container)
        # self.main_layout.addWidget(QtWidgets.QLabel("Notes:"))
        # self.main_layout.addWidget(self.comment_widget)
        # self.main_layout.addStretch()
        # self.main_layout.addWidget(self.extra_widget)

        # if clipboard_cb:
        #     self.main_layout.addWidget(self.copy_button)

        # self.main_layout.addWidget(self.help_button)
        # self.main_layout.addWidget(self.close_button)

        self._show_container_id_changed_ui()

    def setIdVisible(self, visible: bool):
        if self.id_widget and Shiboken.isValid(self.id_widget):
            if visible:
                self.id_widget.setText(self._id_value)
            else:
                self.id_widget.setText(None)

    def setIdValue(self, value: str):
        self._id_value = value
        self._show_container_id_changed()

    def _show_container_id_changed(self):
        gremlin.util.InvokeUiMethod(self._show_container_id_changed_ui)

    def _show_container_id_changed_ui(self):
        """display/hide container Ids on config change"""
        config = gremlin.config.Configuration()
        visible = config.show_container_id
        self.setIdVisible(visible)

    @QtCore.Slot()
    def _comment_changed(self):
        """called when comment text is changed"""
        widget = self.sender()
        data = widget.data
        data.comment = widget.text()

    def _priority_changed(self, value):
        widget = self.sender()
        data = widget.data
        data.setPriority(value)

    def _show_hint(self):
        """Displays a hint, explaining the purpose of the action."""
        QtWidgets.QWhatsThis.showText(self.help_button.mapToGlobal(QtCore.QPoint(0, 10)), self.hint)

    def _delete_cb(self):
        """called on delete button"""
        if self._close_callback:
            self._close_callback()


class BasicActionWrapper(AbstractActionWrapper):
    """Wraps an action widget and displays the basic config dialog."""

    # Signal which is emitted whenever the widget is closed
    closed = QtCore.Signal(QtWidgets.QWidget)

    def __init__(self, action_widget, parent=None):
        """Wraps an existing action widget.

        :param action_widget the action widget to wrap
        :param parent the parent of the widget
        """
        super().__init__(action_widget, parent)

        mode = action_widget.action_data.get_mode()
        self.action_widget = action_widget

        action = self.action_widget.action_data
        if hasattr(action, "hint"):
            hint = action.hint
        else:
            hint = gremlin.hints.hint.get(action.tag, "")

        self._title_bar_widget = TitleBar(
            f"{action_widget.action_data.name} ({mode})",
            hint,
            self._remove,
            self._clipboard_copy,
            data=action_widget.action_data,
        )

        self.title_frame_widget = gremlin.ui.ui_common.QBorderWidget()
        self.title_frame_widget.addWidget(self._title_bar_widget)

        self.title_frame_widget.setBackgroundColor(gremlin.ui.ui_common.Color.actionBackgroundColor())
        self.setTitleBarWidget(self.title_frame_widget)

        self.main_layout.addWidget(self.action_widget)

        # gremlin.util.singleShot(self._config_visible)

    def _config_visible(self):
        if not Shiboken.isValid(self):
            return
        config = gremlin.config.Configuration()
        self._title_bar_widget.setIdVisible(config.show_container_id)

    def _remove(self):
        """Emits the closed event when this widget is being closed."""
        self.closed.emit(self)

    def _cleanup_ui(self):
        """cleans the object"""
        # if hasattr(self.action_widget, "_cleanup_ui"):
        #     self.action_widget._cleanup_ui()
        gremlin.util.clear_layout(self.main_layout)

    def _clipboard_copy(self, _):
        """clipboard copy event"""
        clipboard = Clipboard()
        action = self.action_widget.action_data
        node = action.to_xml()
        xml = lxml.etree.tostring(node)
        encoded = ObjectEncoder(action, xml, action.name, EncoderType.Action)
        # clipboard.data = action
        clipboard.data = encoded
        syslog.info(f"copy to clipboard: {action.name}")


class ConditionActionWrapperWidget(AbstractActionWrapper):
    """Wraps an action widget and displays the condition config dialog."""

    def __init__(self, action_widget, parent=None):
        """Wraps an existing action widget.

        :param action_widget the action widget to wrap
        :param parent the parent of the widget
        """
        super().__init__(action_widget, parent)

        # Disable all dock features and give it a title
        self.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
        title = f"{action_widget.action_data.name}"
        if action_widget.action_data.comment:
            title += f" ({action_widget.action_data.comment})"
        self.setWindowTitle(title)

        # Setup activation condition UI
        container = self.action_widget.action_data
        # if action_data.parent.has_action_conditions:
        if container.activation_condition is None:
            container.activation_condition = BaseActivationCondition(ConditionModel(container), ActivationRule.All)
            container.activation_condition.setContainer(container)

        self.condition_model = ConditionModel(container, container.activation_condition)
        self.condition_view = ConditionView(self.condition_model)
        container.condition_view = self.condition_view
        self.condition_view.setContainer(container)
        self.condition_view.setModel(self.condition_model)
        self.condition_view.redraw()
        self.main_layout.addWidget(self.condition_view)
        # else:
        #     action_data.activation_condition = None


class ContainerModel(AbstractCallbackModel):
    """container model for input mapping widget"""

    def __init__(self, input_item, parent=None):
        """Creates a new instance.

        :param input_item:  the input item owning the container
        :param input_item_widget: the mapping widget displaying all containers
        :param input_type: the override input type if different from the input item configuration
        :param parent: the parent of this widget
        """
        assert isinstance(input_item, InputItem), "Invalid input item object"
        super().__init__(
            allowed_types=(AbstractContainer,),
            model_description=f"ContainerModel for input: [{input_item.device_name} {input_item.display_name}]",
            data=input_item,
        )

        self._input_item = input_item

    @property
    def input_item(self) -> InputItem:
        """gets the associated input item"""
        return self._input_item

    @property
    def input_type(self) -> InputType:
        """gets the associated input type"""
        return self._input_item.input_type

    def addContainer(self, container: AbstractContainer):
        """Adds a container to the model.

        :param container the container instance to be added
        """

        self.add(container)

    def clear(self):
        """clears all containers from the model"""
        for container in self:
            self.removeContainer(container)
        super().clear()

    def removeContainer(self, container: AbstractContainer):
        """Removes an existing container from the model.
        :param container the container instance to remove
        """

        # tell actions in this container they are being deleted
        for action_set in container.action_sets:
            action_set.clear()
        self.remove(container)

    def onItemChanged(self, model: ContainerModel, index: int, new_value: AbstractContainer, old_value: AbstractContainer, operation: str):
        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info(
                f"ContainerModel: container changed: operation: [{operation}] new: [{new_value.display_name if new_value else 'n/a'}]  old: [{old_value.display_name if old_value else 'n/a'}]"
            )
            pass


class ContainerView(AbstractView):
    """widget that displays container mappings for an input item"""

    def __init__(self, model: ContainerModel, parent=None):
        """Creates a new view instance.

        :param parent the parent of the widget
        """

        assert isinstance(model, ContainerModel), "invalid container model"
        input_item = model.input_item
        self._input_item = input_item
        self._model = model

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info(f"Creating container view for: {model.debug_name}")

        super().__init__(model, parent=parent)

        self.pushSuspended()  # suspend updates

        # Create required UI items
        self._main_layout = QtWidgets.QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._redraw_lock = False


        if verbose:
            self._main_layout.addWidget(QtWidgets.QLabel(f"ContainerView: [{input_item.display_name}]"))

        self._create_ui()

        self.popSuspended()  # allow updates

    @property
    def input_item(self):
        """gets the associated input item for the container view"""
        return self._input_item

    def _cleanup_ui(self):
        """widget cleanup"""
        self._clear_widgets()
        gremlin.util.clear_widget_references(self)

    def _clear_widgets(self):
        """clears the scroll area widgets"""
        widgets = list(self._widget_map.values())
        for widget in widgets:
            gremlin.util.delete_widget(widget)
        self._widget_map.clear()
        self._show_blank()

    def _create_ui(self):
        # use a two page widget - one that shows blank content, the other that shows the contents
        self._stacked_widget = QtWidgets.QStackedWidget()
        self._main_layout.addWidget(self._stacked_widget)

        # blank widget - index 0
        self._blank_widget = QtWidgets.QLabel("Please add a container or action.")
        widget = gremlin.ui.ui_common.getVContainer([self._blank_widget, "||", gremlin.ui.ui_common.QEmptyWidget(), "||"], widget_only=True)
        self._stacked_widget.addWidget(widget)

        self._scroll_area = QtWidgets.QScrollArea()

        # Configure the widget holding the layout with all the buttons
        self._scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._scroll_widget, self._scroll_layout = gremlin.ui.ui_common.getVContainer()
        self._scroll_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self._scroll_area.setWidget(self._scroll_widget)

        self._scroll_area.setWidgetResizable(True)

        # Add the scroll area to the main layout - index 1
        self._stacked_widget.addWidget(self._scroll_area)  # index 1

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info(f"create ContainerView [{self._input_item.display_name if self._input_item else 'no input'}]")

        self._widget_map = {}  # map of container ID to container widget

        self._show_blank()

        self._drawn_once = False  # draw on demand only on first redraw

    def create_ui(self):
        """creates the UI for the container contents"""
        import gremlin.util

        assert self._input_item is not None, "Input item not associated with container"
        assert self._model is not None, "Model must be associated with container"

        with QtCore.QSignalBlocker(self.model):
            verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
            if verbose:
                syslog.info(f"Draw container view for: {self.model.debug_name}")

            # update the blank message based on the input

            msg = f"Please add a container or action for <span style ='color: {gremlin.ui.ui_common.Color.textHighlightColor()}; font-weight: bold;'>{self.input_item.display_name}</span>."
            if verbose:
                syslog.info(f"container view create_ui: {msg}")
            self._blank_widget.setText(msg)

            self._clear_widgets()  # remove current widgets and recreate

            container_count = self.model.count()
            if verbose:
                syslog.info(f"ContainerView: found {container_count} to display")
            if container_count > 0:
                # has containers
                # display container widgets in the defined order
                for data in self.model:  # in range(container_count):
                    # data = self.model.data(model_index)

                    # create the container widget for that plugin
                    if verbose:
                        syslog.info(f"\tCreate container widget: [{data.name}]")
                    widget = data.widget(self.input_item, data)
                    widget.closed.connect(self._create_closed_cb(widget))
                    widget.container_modified.connect(self.model.data_changed.emit)
                    self._scroll_layout.addWidget(widget)
                    self._widget_map[data.id] = widget

                self._show_content()

            else:
                self._show_blank()

    def setBlankMessage(self, message: str = None):
        """updates the blank message"""
        if self._blank_widget:
            self._blank_widget.setText(message or "")
            self._blank_widget.setVisible(message is not None)

    def _show_blank(self):
        if self._stacked_widget.currentIndex() != 0:
            verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
            if verbose:
                syslog.info(f"ContainerView: show blank [{self._input_item.display_name if self._input_item else 'no input'}]")
            self._stacked_widget.setCurrentIndex(0)

    def _show_content(self):
        if self._model.count() == 0:
            # no containers to show
            self._show_blank()
        else:
            if self._stacked_widget.currentIndex() != 1:
                verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
                if verbose:
                    syslog.info(f"ContainerView: show content [{self._input_item.display_name if self._input_item else 'no input'}]")
                self._stacked_widget.setCurrentIndex(1)

    def redraw(self, force=False):
        # assert inspect.stack()[1].function == "_fireChanged","redraw should only be called due to a model trigger"
        gremlin.util.InvokeUiMethod(self._redraw_ui, force)  # ensure on UI thread

    def _redraw_ui(self, force=False):
        """Redraws the entire view.  must be on UI thread"""

        try:
            verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
            if verbose:
                syslog.info(f"ContainerView: redraw for [{self._input_item.display_name if self._input_item else 'no input'}]")

            widget_count = len(self._widget_map)
            model_count = self.model.count()

            if force or not self._drawn_once or self.modelChanged() or widget_count != model_count:
                if verbose:
                    syslog.info(f"\tcreate UI for [{model_count}] containers")
                self.create_ui()
                self._drawn_once = True
                self._show_content()
                return  # done

            with QtCore.QSignalBlocker(self.model):
                verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
                container_count = self.model.rows()

                if container_count > 0:
                    # has containers

                    if verbose:
                        syslog.info(f"\t[{container_count}] containers to display")
                    # display container widgets in the defined order
                    for model_index in range(container_count):
                        data = self.model.data(model_index)
                        assert data.id in self._widget_map, f"ContainerView model and UI are not synchronized: widget not found for container id [{data.id}]"

                        # widget already exist, re-order if needed
                        widget = self._widget_map[data.id]
                        widget_index = self._scroll_layout.indexOf(widget)
                        if model_index != widget_index:
                            # reorder
                            self._scroll_layout.removeWidget(widget)
                            self._scroll_layout.insertWidget(model_index, widget)

                        # redraw the action sets
                        widget.redrawActionSets()

                    self._show_content()

                else:
                    if verbose:
                        syslog.info("\tno containers to display")
                    msg = f"Please add a container or action for <span style ='color: {gremlin.ui.ui_common.Color.textHighlightColor()}; font-weight: bold;'>{self.input_item.display_name}</span>"
                    if verbose:
                        syslog.info(f"container view redraw ui: {msg}  input item id: {self.input_item.id}")
                    self._blank_widget.setText(msg)
                    self._show_blank()

        finally:
            assert len(self._widget_map) == self.model.count(), "ContainerView model and UI are not synchronized (mismatched items)"

    def _create_closed_cb(self, widget):
        """Create callbacks to remove individual containers from the model.

        :param widget the container widget to be removed
        :return callback function to remove the provided widget from the
            model
        """

        return lambda: self._delete_container(widget.container)

    def _delete_container(self, container):
        """called when delete container button clicked"""
        gremlin.util.InvokeUiMethod(self._delete_container_ui, container)

    def _delete_container_ui(self, container):
        if gremlin.ui.ui_common.ConfirmBox("Delete this container?"):
            container.clear()  # delete all actions in the container
            self.model.remove(container)
            self._redraw_ui()
            # el = gremlin.event_handler.EventListener()
            # el.update_action_icons.emit(self._input_item)


class InputItemMappingWidget(QtWidgets.QWidget):
    """right panel widget that displays mappings"""

    # Signal emitted when the description changes
    description_changed = Signal(str)  # indicates the description was changed
    description_clear = Signal()  # clear the description field
    expired = Signal(object, QtWidgets.QWidget)  # (key, widget) fires when the input mapping expires to notify the owner

    def __init__(
        self,
        input_item: InputItem,
        input_type: InputType = None,
        object_name: str = None,
        spacer_height=32,
        parent=None,
    ):
        """Creates a new object instance.

        :params:

        item_data =profile data associated with the item, can be none to display an empty box
        input_type = override input type if the input type is not that of the item_data (InputItem) - controls what containers/actions are available
        spacer_height = hack margin at top
        parent = the parent of this widget

        """
        super().__init__(parent)

        assert isinstance(input_item, InputItem), "invalid input type"
        if input_item.input_id is None:
            pass
        assert input_item.input_id is not None, "invalid input id on input item"
        assert input_item.input_type is not None, "input type cannot be derived be specified"

        if not input_type:
            input_type = input_item.input_type

        # remember the params for re-creation if needed
        self.params = (input_item, input_type, object_name, spacer_height, parent)

        assert input_item is not None, "Input Item must be provided"
        self._input_item = input_item
        self._input_type = input_type
        self._container_model = input_item.containerModel

        # self.setObjectName(object_name if object_name else "(object name not provided)")
        self.id = gremlin.util.get_guid()
        self.setObjectName(object_name if object_name else f"InputItemMappingWidget#{input_item.display_name}")

        self._main_layout = QtWidgets.QVBoxLayout(self)

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            self._main_layout.addWidget(QtWidgets.QLabel("InputItemMappingWidget"))

        self._stacked_widget = QtWidgets.QStackedWidget()
        self._main_layout.addWidget(self._stacked_widget)

        self._container_widget = None

        # blank mapping widget
        self._blank_widget = QtWidgets.QLabel("Please select an input.")
        widget = gremlin.ui.ui_common.getVContainer(self._blank_widget, widget_only=True)
        widget.setContentsMargins(4, 4, 4, 4)
        self._stacked_widget.addWidget(widget)  # index 0

        self._spacer_height = spacer_height

        self._container_view = None


        self._drawn_once = False

        self._show_blank()

    def fromParams(self, params) -> InputItemMappingWidget:  # noqa: F405
        """recreates the widget from self"""
        input_item, input_type, object_name, spacer_height, parent = params
        widget = InputItemMappingWidget(input_item, input_type, object_name, spacer_height, parent)
        input_item.setMappingWidget(widget)  # keep a reference

    def _mapping_changed(self, input_item: InputItem):
        """occurs when a device mapping changed through user interaction with the UI"""

        if input_item != self._input_item:
            # not ours
            return
        self.refresh()

    def isBlank(self):
        """true if not associated with any data (blank widget)"""
        return self._input_item is None

    def _cleanup_ui(self):
        """called when widget is deleted"""
        if self._container_view:
            self._container_view._cleanup_ui()
            self._container_view = None
        gremlin.util.clear_widget_references(self)

    @property
    def containerModel(self) -> ContainerModel:
        """gets the mapping container model"""
        return self.input_item.containers

    def refresh(self):
        """refreshes the current content with any changes"""
        pass

    @property
    def input_item(self) -> InputItem:
        """gets the associated item data"""
        return self._input_item

    def getInputItem(self):  # InputItem:
        """gets the associated item data"""
        return self._input_item

    def setInputItem(self, input_item: InputItem):
        """sets the item data and redraws the control"""

        if not Shiboken.isValid(self):
            return

        assert isinstance(input_item, InputItem), "invalid input type"
        assert input_item.input_type is not None, "input type cannot be derived be specified"
        if self._input_item.input_id == input_item.input_id:
            return  # no change

        old_input_item = self._input_item
        if old_input_item and old_input_item != input_item:
            # disconnect old signals
            self._input_item.containerModel.removeCallback(self._mapping_changed)

        self._input_item = input_item
        self._input_type = input_item.input_type
        self._drawn_once = False  # recreate the UI
        if input_item:
            self.profile_mode = self._input_item.profile_mode
            if hasattr(input_item, "input_type"):
                self._input_type = input_item.input_type
            self._show_content()
            self._input_item.containerModel.addCallback(self._mapping_changed)

        else:
            # no item selected
            # self._container_model = None
            self._show_blank()

    # def _handle_model_changed(self):
    #     """occurs when the container model changes"""
    #     el = gremlin.event_handler.EventListener()
    #     # el.mapping_changed.emit(self._input_item)
    #     syslog.info(f"item container model: {self.input_item.containers.id} contains {len(self.input_item.containers)} containers")
    #     self.notify_changed()

    #     # update icons
    #     el.update_action_icons.emit(self._input_item)

    def _show_blank(self):
        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info("InputItemMappingWidget: show blank")
        self._stacked_widget.setCurrentIndex(0)

    def _show_content(self):
        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog.info(f"InputItemMappingWidget: show content: [{self._input_item.display_name}]")
        self._stacked_widget.setCurrentIndex(1)

    def create_ui(self):
        """creates the UI for this input mapping widget"""

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_ui

        input_item: InputItem = self._input_item
        device = gremlin.joystick_handling.getDevice(input_item.device_guid)

        # delete any existing widget and re-create
        if self._stacked_widget.count() == 2:
            widget = self._stacked_widget.widget(1)
            self._container_view = None  # free up the widget reference
            widget.hide()
            self._stacked_widget.removeWidget(widget)
            widget.deleteLater()
            input_item.setMappingWidget(None)

        widgets = []

        # main widget container
        container_widget, container_layout = gremlin.ui.ui_common.getVContainer()

        if not input_item.is_action:
            # description header
            self._create_description(container_layout)

        # container toolbar
        if input_item.device_type == DeviceType.VJoy:
            self._create_vjoy_dropdowns(container_layout)
        else:
            self._create_mapping_toolbar(container_layout)

        if verbose:
            msg = f"InputMappingWidget: [{device.name}]: input type: [{input_item.input_type.name}] input [{input_item.input_id}] {input_item.display_name}"
            syslog.info(msg)
            container_layout.addWidget(QtWidgets.QLabel(msg))

        if config.show_container_id:
            # debug container type
            widgets = []
            label = QtWidgets.QLabel(f"Mode: [{self._input_item.profile_mode if self._input_item.profile_mode else 'N/A'}]")
            widgets.append(label)

            input_id = None
            if self._input_item:
                input_id = self._input_item.input_id
                raw_input_type = self._input_item.getRawInputType()
                input_type = self._input_item.getInputType()
                if raw_input_type != input_type:
                    # override used
                    label_name = f"Input Type: (override) {input_type.name}"
                else:
                    label_name = f"Input Type: {input_type.name}"

            else:
                label_name = "Input Type: N/A"

            label = QtWidgets.QLabel(label_name)
            widgets.append(label)

            if input_id is not None:
                width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
                line_edit = gremlin.ui.ui_common.QDataLineEdit()
                line_edit.setMinimumWidth(width)
                line_edit.setText(str(input_id) if isinstance(input_id, int) else gremlin.util.normalize_guid(input_id.id))
                line_edit.setReadOnly(True)
                widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Input Id:", widget_only=True)
                widgets.append(widget)

            widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

            name = self.objectName()
            css = "background: green;"
            if not name:
                if input_item:
                    name = f"InputItemConfig for: {self._input_item.display_name}"
                    css = "background: gray;"
            if not name:
                name = "(name not available)"
                css = "background: red;"

            label_name = QtWidgets.QLabel(name)

            id_label = QtWidgets.QLabel(f"({self.id})")
            label_name.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
            label_name.setStyleSheet(css)
            widgets.append(label_name)
            widgets.append(id_label)

            widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

            container_layout.addWidget(widget)

        # syslog.info(f"using container id: {self._input_item.containers.id} for input item: [{self._input_item.display_name}]")
        container_view_widget = ContainerView(self.input_item.containers, parent=self)

        container_layout.addWidget(container_view_widget)
        # reference the widget so we can update it
        self._container_view = container_view_widget

        container_view_widget.setContentsMargins(0, 0, 0, 0)

        # add to the stacked widget
        self._stacked_widget.addWidget(container_widget)
        index = self._stacked_widget.indexOf(container_widget)
        if verbose:
            syslog.info(f"InputItemMappingWidget: display widget index [{index}] container view for [{container_view_widget.input_item.display_name}]")
        self._stacked_widget.setCurrentIndex(index)

        # save a reference to the visualization of the input mapping
        input_item.setMappingWidget(container_view_widget)

        # setup the container widget reference
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        plugin_manager.set_widget(self._input_item, self)

        # update the container view contents
        container_view_widget.redraw()  # update the container view

    def getContainerView(self) -> ContainerView:
        """gets the container view"""
        return self._container_view

    def redraw(self, force=False):
        # assert inspect.stack()[1].function == "_fireChanged","redraw should only be called due to a model trigger"
        gremlin.util.InvokeUiMethod(self._redraw_ui, force)

    def _redraw_ui(self, force=False):

        if not Shiboken.isValid(self):
            # destroyed
            return

        assert self._input_item is not None, "invalid item data "

        if force or not self._drawn_once or self._container_view is None:
            if self._input_item is not None:
                # syslog.info(f"redraw input item id [{self._input_item.id}] container count: [{self._input_item.containers.count()}]")
                self._drawn_once = True  # indicate drawn at least once since creation
                self.create_ui()
                assert self._container_view is not None, "container view should be created after create_ui"

        # update page to display
        self._update_page()

    def _update_page(self):
        """updates the display page based on the containers defined in the input"""
        input_item: InputItem = self._input_item

        if input_item:
            # input has at least one container defined
            self._show_content()
            return

        # show no container display
        self._show_blank()

    def _add_action(self, action_name):
        """Adds a new action to the input item.

        :param action_name name of the action to be added
        """
        import container_plugins.basic
        import gremlin.plugin_manager
        import gremlin.ui.ui_common

        assert self._input_item is not None, "InputItemMappingWidget: input id not set while adding action"

        # If this is a vJoy item then do not permit adding an action if
        # there is already one present, as only response curves can be added
        # and only one of them makes sense to exist
        if self._input_item.get_device_type() == DeviceType.VJoy:
            if len(self._input_item.containers) > 0:
                return

        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        container = container_plugins.basic.BasicContainer(self._input_item)
        action = plugin_manager.get_class(action_name)(container)

        if action.singleton:
            # action can only exist once in the container list
            if self._input_item.is_action:
                gremlin.ui.ui_common.MessageBox(prompt=f"Unable to add [{action_name}].  The action cannot be added to a sub-container.")
                return
            if self._input_item.hasAction(action_name):
                gremlin.ui.ui_common.MessageBox(prompt=f"Unable to add: [{action_name}]. The action can only appear once per input.")
                return

        container.add_action(action)
        self._container_model.addContainer(container)

    def notify_changed(self):
        """notifies the item has changed"""

        el = gremlin.event_handler.EventListener()
        event = gremlin.event_handler.DeviceChangeEvent()
        event.device_guid = self._input_item.device_guid
        event.device_name = self._input_item.device_name
        event.device_input_type = self._input_item.input_type
        event.device_input_id = self._input_item.input_id
        event.vjoy_id = 0
        event.vjoy_input_id = 0
        event.source = self._input_item
        el.profile_device_changed.emit(event)
        el.icon_changed.emit(event)

    def _paste_action(self, data_or_action, container):
        """paste action to the input item"""
        import container_plugins.basic
        import gremlin.plugin_manager
        import gremlin.base_profile

        if self._input_item.get_device_type() == DeviceType.VJoy:
            if len(self._input_item.containers) > 0:
                return

        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_tag_map = plugin_manager.tag_map

        if isinstance(data_or_action, ObjectEncoder):
            oc = data_or_action
            if oc.encoder_type == EncoderType.Action:
                xml = oc.data
                node = lxml.etree.fromstring(xml)
                action_tag = node.tag
                if action_tag in action_tag_map:
                    action_name = action_tag_map[action_tag]
                    container = container_plugins.basic.BasicContainer(self._input_item)
                    action_item = action_name(container)
                    action_item.setId(gremlin.util.get_guid())
            else:
                # not an action type, ignore
                return

        elif isinstance(data_or_action, gremlin.base_profile.AbstractAction):
            action = data_or_action
            container = container_plugins.basic.BasicContainer(self._input_item)
            action_item = plugin_manager.duplicate(action, container)
        else:
            # nothing to do
            return

        # remap inputs
        action_item.update_inputs(self._input_item)
        container.add_action(action_item)

        if len(container.action_sets) > 0:
            self._container_model.addContainer(container)
        self._container_model.data_changed.emit()

        _eh = gremlin.event_handler.EventListener()
        # eh.mapping_changed.emit(self._input_item)
        self.notify_changed()

    def _add_container(self, container_name):
        """Adds a new container to the input item.

        :param container_name name of the container to be added
        """

        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        container = plugin_manager.get_class(container_name)(self._input_item)
        if hasattr(container, "action_model"):
            container.action_model = self._container_model
        self._container_model.addContainer(container)
        plugin_manager.set_container_data(self._input_item, container)

        _eh = gremlin.event_handler.EventListener()
        # eh.mapping_changed.emit(self._input_item)

        self.redraw()  # update

        return container

    def _copy_container(self):
        """copies all containers to the clipboard"""
        if len(self._input_item.containers) > 0:
            clipboard = Clipboard()

            root = lxml.etree.Element("multi_containers")
            for container in self._input_item.containers:
                node = container.to_xml()
                root.append(node)
            xml = lxml.etree.tostring(root)
            # debug
            # filename = gremlin.util.save_xml("copy_container.xml", root)
            # gremlin.util.display_file(filename)
            encoded = ObjectEncoder(self._input_item.containers, xml, "multi", EncoderType.MultiContainer)
            clipboard.data = encoded
            syslog.info("multi container copied to clipboard")

    def _save_container_to_template(self, item):
        input_item: InputItem = item
        """ saves a mapping set to a template """
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(None, "Save template", gremlin.util.userprofile_path(), "XML files (*.xml)")

        if fname:
            root = etree.Element("container_template")
            # get the xml for every container in the mapping
            for container in input_item.containers:
                node = container.to_xml()
                root.append(node)
            # save the xml
            tree = etree.ElementTree(root)
            try:
                if os.path.isfile(fname):
                    # blitz existing file
                    os.unlink(fname)
                tree.write(fname, pretty_print=True, xml_declaration=True, encoding="utf-8")
            except Exception:
                syslog.error(f"Error writing template to: {fname}")
                return False
            return True

        return False

    def _load_container_from_template(self, extra_data=None):
        """loads a container from a template"""
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Container template",
            gremlin.util.userprofile_path(),
            "XML files (*.xml)",
        )
        if fname and os.path.isfile(fname):
            container_list = []
            plugin_manager = gremlin.plugin_manager.ContainerPlugins()
            parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
            msg_list = []
            try:
                tree = etree.parse(fname, parser=parser)
                root = tree.getroot()
                if root.tag == "container_template":
                    # get root containers only
                    nodes = root.xpath("//container[not(ancestor::container)]")
                    for node in nodes:
                        container_type = node.get("type")
                        container_plugins = gremlin.plugin_manager.ContainerPlugins()
                        container_tag_map = container_plugins.tag_map

                        # verify the container is valid for the input type
                        valid_containers_names = self._input_item.get_valid_container_list()
                        if container_type in container_tag_map:
                            container_name = container_tag_map[container_type].name
                            if container_name in valid_containers_names:
                                new_container = container_tag_map[container_type](self._input_item)
                                new_container.from_xml(node, self._input_item, extra_data)
                                new_container.generateGuids()  # replace IDs to avoid conflicts
                                container_list.append(new_container)
                        else:
                            msg = f"Container {container_type.name} is not valid for the current input"
                            msg_list.append(msg)
                            syslog.warning(msg)

                if msg_list:
                    prompt = "".join((msg + "\n" for msg in msg_list))
                    gremlin.ui.ui_common.MessageBox(title="Load Template", prompt=prompt)

            except Exception:
                pass
            if container_list:
                for new_container in container_list:
                    if hasattr(new_container, "action_model"):
                        new_container.action_model = self._container_model

                        plugin_manager.set_container_data(self._input_item, new_container)
                        self._container_model.addContainer(new_container)

                _el = gremlin.event_handler.EventListener()
                # el.mapping_changed.emit(self._input_item)
                self.notify_changed()

    @QtCore.Slot(object)
    def _paste_container(self, container, extra_data=None):
        """Adds a new container to the input item.

        :param container container to be added
        """
        import gremlin.base_profile

        _el = gremlin.event_handler.EventListener()
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        container_list = []

        # tracker = ConditionTracker()
        import_data = gremlin.base_profile.ProfileImportData()
        verbose = gremlin.config.Configuration().verbose

        if not extra_data:
            extra_data = {}
        extra_data["paste"] = True  # indicate paste mode for xml readers

        if isinstance(container, ObjectEncoder):
            oc = container
            valid_containers_names = self._input_item.get_valid_container_list()
            container_tag_map = plugin_manager.tag_map
            if oc.encoder_type == EncoderType.Container:
                xml = oc.data
                node = lxml.etree.fromstring(xml)
                container_type = node.get("type")
                # verify the container is valid for the input
                if container_type in container_tag_map:
                    container_name = container_tag_map[container_type].name
                    if container_name in valid_containers_names:
                        new_container = container_tag_map[container_type](self._input_item)
                        new_container.from_xml(node, data=self._input_item, extra_data=extra_data)
                        new_container.generateGuids()
                        if new_container.id in import_data.used_ids:
                            new_id = gremlin.util.get_guid()
                            if verbose:
                                syslog.warning(f"PASTE: DUPLICATE ID:container {new_container.id} -> {new_id}")
                            new_container._id = new_id
                        import_data.used_ids[new_container.id] = new_container

                        container_list.append(new_container)

            elif oc.encoder_type == EncoderType.MultiContainer:
                xml = oc.data

                root = etree.fromstring(xml)

                for node in root:
                    container_type = node.get("type")

                    if container_type in container_tag_map:
                        container_name = container_tag_map[container_type].name
                        if container_name in valid_containers_names:
                            new_container = container_tag_map[container_type](self._input_item)
                            new_container.from_xml(node, data=self._input_item, extra_data=extra_data)
                            new_container.generateGuids()
                            if new_container.id in import_data.used_ids:
                                new_id = gremlin.util.get_guid()
                                if verbose:
                                    syslog.warning(f"PASTE: DUPLICATE ID:container {new_container.id} -> {new_id}")
                                new_container._id = new_id
                            import_data.used_ids[new_container.id] = new_container

                            container_list.append(new_container)

                            # debug
                            root = lxml.etree.Element("generate-guid-containers")
                            node = new_container.to_xml()
                            root.append(node)
                            # filename = gremlin.util.save_xml("container_new_id.xml", root)
                            # gremlin.util.display_file(filename)

        else:
            new_container = plugin_manager.duplicate(container, self._input_item)
            new_container.generateGuids()
            container_list.append(new_container)

        if container_list:
            for new_container in container_list:
                if hasattr(new_container, "action_model"):
                    new_container.action_model = self._container_model

                    plugin_manager.set_container_data(self._input_item, new_container)
                    self._container_model.addContainer(new_container)

            #  el.mapping_changed.emit(self._input_item)
            self.notify_changed()

            # update
            self.redraw()

        return container_list

    def _delete_container(self):
        """call to delete all containers"""
        if not self._input_item.containers:
            # nothing to do
            return
        # do a confirmation box just in case
        message_box = QtWidgets.QMessageBox()
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message_box.setText("This will remove the current container set and any actions.")
        message_box.setInformativeText("Are you sure?")
        message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Cancel | QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Cancel:
            return

        self._container_model.removeAllContainers()

        # update
        self.redraw()

    def _remove_container(self, container):
        """Removes an existing container from the InputItem.

        :param container the container instance to be removed
        """

        self._container_model.remove_container(container)

    def _create_description(self, layout: QtWidgets.QLayout):
        """Creates the description input for the input item."""
        self.description_layout = QtWidgets.QHBoxLayout()
        self.description_layout.addWidget(QtWidgets.QLabel("Mapping Description:"))
        self.description_field = QtWidgets.QLineEdit()
        self.description_field.setText(self._input_item.description)
        self.description_field.textChanged.connect(self._edit_description_cb)
        self.description_layout.addWidget(self.description_field)
        self.description_field.setReadOnly(self._input_item.descriptionReadOnly)
        self.description_clear_button = gremlin.ui.ui_common.Buttons.getEraserWidget(
            callback=self._delete_description_cb,
            tooltip="Reset description to default",
            width=20,
            height=20,
        )
        self.description_layout.addWidget(self.description_clear_button)

        layout.addLayout(self.description_layout)

    def _create_mapping_toolbar(self, layout: QtWidgets.QLayout):
        """Creates a drop down selection with actions that can be
        added to the current input item.
        """

        # check for an override for the inputs that can change types (such as OSC)
        input_type = self._input_item.getInputType()

        self.sync_widget = gremlin.ui.ui_common.Buttons.getListSyncWidget(callback=self._sync_list)

        # action selector for the toolbar
        self.action_selector = ActionSelector(None, self._input_item)
        self.action_selector.inputItem = self._input_item
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.action_paste.connect(self._paste_action)

        # container selector for the toolbar
        self.container_selector = ContainerSelector(input_type, self._input_item.is_axis, data=self._input_item)

        self.container_selector.container_added.connect(self._add_container)
        self.container_selector.container_copy.connect(self._copy_container)
        self.container_selector.container_paste.connect(self._paste_container)

        self.container_selector.container_from_template.connect(self._load_container_from_template)
        self.container_selector.container_to_template.connect(self._save_container_to_template)
        # self.container_selector.container_delete.connect(self._delete_container)
        self.always_execute = QtWidgets.QCheckBox("Always execute")
        self.always_execute.setToolTip("If enabled, the mapping continues to process triggers even if the profile is paused.")
        self.always_execute.setChecked(self._input_item.always_execute)
        self.always_execute.stateChanged.connect(self._always_execute_cb)

        self.collapse_all_widget = gremlin.ui.ui_common.Buttons.getCollapseAllWidget(callback=self._handle_collapse_all)
        self.expand_all_widget = gremlin.ui.ui_common.Buttons.getExpandAllWidget(callback=self._handle_expand_all)

        widgets = [
            self.sync_widget,
            self.action_selector,
            self.container_selector,
            self.collapse_all_widget,
            self.expand_all_widget,
            "|",
            self.always_execute,
        ]

        self.dropdown_widget, self.dropdown_layout = gremlin.ui.ui_common.getHContainer(widgets)
        layout.addWidget(self.dropdown_widget)
        desired_width = self.dropdown_widget.sizeHint().width()
        self.dropdown_widget.setMinimumWidth(desired_width)

    def _sync_list(self):
        input_item = self._input_item
        el = gremlin.event_handler.EventListener()
        el.sync_input.emit(input_item)

    def _handle_collapse_all(self):
        """collapses all containers"""
        el = gremlin.event_handler.EventListener()
        el.collapse_all_containers.emit()

    def _handle_expand_all(self):
        """expands all containers"""
        el = gremlin.event_handler.EventListener()
        el.expand_all_containers.emit()

    def updateSelectors(self, input_type, item_data):
        self.action_selector.refresh(input_type, item_data)
        self.container_selector.refresh(input_type, item_data)

    def _create_vjoy_dropdowns(self, layout: QtWidgets.QLayout):
        """Creates the action drop down selection for vJoy devices."""
        self.action_selector_widget = QtWidgets.QWidget()
        self.action_selector_layout = QtWidgets.QHBoxLayout(self.action_selector_widget)

        self.action_selector = ActionSelector(
            gremlin.types.DeviceType.VJoy,
            None,
            parent=self.action_selector_widget,
        )
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.action_paste.connect(self._paste_action)
        self.action_selector_layout.addWidget(self.action_selector)
        layout.addWidget(self.action_selector_widget)

    @QtCore.Slot()
    def _edit_description_cb(self, text):
        """Handles changes to the description text field.

        :param text the new contents of the text field
        """
        self._input_item.description = text
        self.description_changed.emit(text)

    @QtCore.Slot()
    def _delete_description_cb(self):
        """deletes the description text.

        :param text the new contents of the text field
        """
        self._input_item.description = None
        self.description_clear.emit()

    def _always_execute_cb(self, state):
        """Handles changes to the always execute checkbox.

        :param state the new state of the checkbox
        """
        self._input_item.always_execute = self.always_execute.isChecked()

    def _valid_action_names(self):
        """Returns a list of valid actions for this InputItemWidget.

        :return list of valid action names
        """
        action_names = []
        if self._input_item.input_type == gremlin.types.DeviceType.VJoy:
            entry = gremlin.plugin_manager.ActionPlugins().repository.get("response-curve-ex", None)
            if entry is not None:
                action_names.append(entry.name)
            else:
                raise gremlin.error.GremlinError("Response curve plugin is missing")
        else:
            for entry in gremlin.plugin_manager.ActionPlugins().repository.values():
                if self._input_item.input_type in entry.input_types:
                    action_names.append(entry.name)
        return sorted(action_names)

    def __eq__(self, other):
        if other is None:
            return False
        if hasattr(self, "item_data"):
            if not hasattr(other, "item_data"):
                return False
            if self._input_item and other.item_data:
                return self._input_item.callbackKey() == other.item_data.callbackKey()
        return self.id == other.id


@SingletonDecorator
class ConditionHelper:
    """helper class to manipulate conditions"""

    def __init__(self):
        el = gremlin.event_handler.EventListener()
        el.paste_condition.connect(self.paste_condition)
        el.copy_condition.connect(self.copy_condition)

    @QtCore.Slot(object, object)
    def paste_condition(self, container, oc):
        """pastes a condition to a container

        :param container: the container object receiving the condition
        :param oc: object encoder data to paste

        """
        from gremlin.clipboard import ObjectEncoder, EncoderType

        if isinstance(container, gremlin.base_profile.AbstractAction):
            input_item = container.parent.parent
        elif isinstance(container, AbstractContainer):
            input_item = container.parent
        else:
            assert False, "Pasted container is not a valid container type - expected AbstractContainer or AbstractAction"

        if isinstance(oc, ObjectEncoder):
            data = (input_item, container)  # (input item, container)
            tracker = ConditionTracker()
            mode = gremlin.shared_state.edit_mode

            if oc.encoder_type == EncoderType.ActivationCondition:
                xml = oc.data
                node = lxml.etree.fromstring(xml)
                if node.tag == "activation-condition":
                    # temporary activation condition
                    activation_condition = BaseActivationCondition(ConditionModel(self), ActivationRule.All)
                    rule = container.activation_condition.rule
                    activation_condition.from_xml(node, data)
                    for condition in activation_condition.conditions:
                        condition.setId(gremlin.util.get_guid())
                        # add the condition to the existing container
                        container.activation_condition.conditions.append(condition)
                        item = ConditionTrackerData(mode, input_item, container, condition, rule)
                        tracker.registerCondition(item)
                if isinstance(container, gremlin.base_profile.AbstractAction):
                    # we need to send the main container, not the action container for the update
                    self.update_condition_ui(container.parent)
                elif isinstance(container, AbstractContainer):
                    self.update_condition_ui(container)

            elif oc.encoder_type == EncoderType.Condition:
                xml = oc.data
                node = lxml.etree.fromstring(xml)
                if node.tag == "condition":
                    condition_type = safe_read(node, "condition-type", str, "")
                    condition = BaseActivationCondition.condition_lookup[condition_type]()
                    condition.from_xml(node, data)
                    condition.setId(gremlin.util.get_guid())

                    container.condition_view._add_condition(condition)
                    # container.activation_condition.conditions.append(condition)
                    condition.setOwner(container.activation_condition)
                    rule = container.activation_condition.rule
                    input_item = container.parent
                    item = ConditionTrackerData(mode, input_item, container, condition, rule)
                    tracker.registerCondition(item)
                    if isinstance(container, gremlin.base_profile.AbstractAction):
                        # we need to send the main container, not the action container for the update
                        self.update_condition_ui(container.parent)
                    elif isinstance(container, AbstractContainer):
                        self.update_condition_ui(container)

    def update_condition_ui(self, container):
        """asks the container UI to update"""

        el = gremlin.event_handler.EventListener()
        el.condition_changed.emit(container)

    @QtCore.Slot(object)
    def copy_condition(self, condition):
        """copies a condition or activation condition to the clipboard"""
        from gremlin.clipboard import Clipboard, ObjectEncoder, EncoderType

        clipboard = Clipboard()
        if isinstance(condition, gremlin.input_item.BaseActivationCondition):
            node = condition.to_xml()
            xml = lxml.etree.tostring(node)
            encoded = ObjectEncoder(condition, xml, "activation-condition", EncoderType.ActivationCondition)
            clipboard.data = encoded
            syslog.info("activation condition copied to clipboard")
        elif isinstance(condition, AbstractCondition):
            # regular condition
            node = condition.to_xml()
            xml = lxml.etree.tostring(node)
            encoded = ObjectEncoder(condition, xml, "condition", EncoderType.Condition)
            clipboard.data = encoded
            syslog.info("condition copied to clipboard")
        else:
            syslog.warning("Unable to copy data - unsupported condition type")


_condition_helper = ConditionHelper()


class AbstractConditionWidget(QtWidgets.QGroupBox):
    """Abstract class for condition ui widgets."""

    # Signal emitted when a condition is deleted
    # deleted = Signal(base_classes.AbstractCondition)
    deleted = Signal(object)

    def __init__(self, condition: AbstractCondition, parent=None):
        """Creates a new widget.

        :param condition_data the data to be represented by the widget
        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.condition = condition

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self._create_ui()

    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        pass

    @QtCore.Slot()
    def _copy_condition(self):
        helper = ConditionHelper()
        helper.copy_condition(self.condition)

    @QtCore.Slot()
    def _paste_condition(self):
        clipboard = gremlin.clipboard.Clipboard()
        helper = ConditionHelper()
        helper.paste_condition(self.condition.owner.container, clipboard.data)


class KeyboardConditionWidget(AbstractConditionWidget):
    """Widget allowing the configuration of a keyboard based condition."""

    def __init__(self, condition, parent=None):
        """Creates a new widget.

        :param condition_data the data to be represented by the widget
        :param parent the parent of this widget
        """
        super().__init__(condition, parent)
        self.setTitle("Keyboard Condition")

    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        if not Shiboken.isValid(self):
            return

        ui_common.clear_layout(self.main_layout)

        self.grid_widget = QtWidgets.QWidget()
        self.grid_layout = QtWidgets.QGridLayout(self.grid_widget)

        self.ui_container_widget = QtWidgets.QWidget()
        self.ui_container_layout = QtWidgets.QGridLayout(self.ui_container_widget)

        self.key_label = QtWidgets.QLabel("")
        if self.condition.input_item:
            self.key_label.setText(f"<b>{self.condition.input_item.display_name}</b>")

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback=self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback=self._paste_condition)

        self.record_button_widget = gremlin.ui.ui_common.Buttons.getEditWidget(label="Listen", callback=self._request_user_input)
        self.select_button_widget = gremlin.ui.ui_common.Buttons.getKeyboardWidget(label="Select Keys", callback=self._select_user_input)
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(
            callback=lambda: self.deleted.emit(self.condition),
            tooltip="Delete condition",
        )

        widgets, layout = gremlin.ui.ui_common.getHContainer(
            [
                self.copy_widget,
                self.paste_widget,
                self.record_button_widget,
                self.select_button_widget,
                self.delete_button_widget,
            ]
        )

        self.comparison_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.comparison_dropdown.addItem("Pressed")
        self.comparison_dropdown.addItem("Released")
        if self.condition.comparison:
            self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.currentTextChanged.connect(self._comparison_changed_cb)

        self.grid_layout.addWidget(QtWidgets.QLabel("Activate if"), 0, 0)
        self.grid_layout.addWidget(self.key_label, 0, 1)
        self.grid_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.grid_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.grid_layout.addWidget(widgets, 0, 5)
        self.grid_layout.setColumnStretch(4, 2)

        self.main_layout.addWidget(self.grid_widget)
        self.main_layout.addWidget(self.ui_container_widget)

    @QtCore.Slot(object)
    def _key_pressed_cb(self, key):
        """Updates the UI and model with the newly pressed key information.

        :param key the key that has been pressed
        """
        from gremlin.ui.keyboard_device import KeyboardInputItem

        input_item = KeyboardInputItem()
        if isinstance(key, list):
            key = key.pop()
        input_item.key = key
        self.condition.input_item = input_item
        self.condition.scan_code = key.scan_code
        self.condition.is_extended = key.is_extended
        self.condition.comparison = self.comparison_dropdown.currentText().lower()
        self.key_label.setText(f"<b>{input_item.display_name}</b>")

    @QtCore.Slot(str)
    def _comparison_changed_cb(self, text):
        """Updates the comparison operation to use.

        :param text the new comparison operation name
        """
        self.condition.comparison = text.lower()

    @QtCore.Slot()
    def _request_user_input(self):
        """Prompts the user for the input to bind to this item."""
        self.input_dialog = ui_common.InputListenerWidget(
            [
                InputType.Keyboard,
                InputType.KeyboardLatched,
            ],
            return_kb_event=False,
            multi_keys=False,
        )
        self.input_dialog.item_selected.connect(self._input_pressed_cb)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        self.input_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150,
        )
        self.input_dialog.show()

    @QtCore.Slot(object)
    def _input_pressed_cb(self, key):
        """Processes input events to update the UI and model.

        :param event the input event to process
        """

        self.condition.comparison = "pressed"

        self._key_pressed_cb(key)

    @QtCore.Slot()
    def _select_user_input(self):
        """brings up the keyboard to select keys from"""

        from gremlin.ui.virtual_keyboard import InputKeyboardDialog

        sequence = []
        if self.condition.input_item:
            sequence = self.condition.input_item.sequence
        self._keyboard_dialog = InputKeyboardDialog(sequence=sequence, parent=self, select_single=False, index=-1)
        self._keyboard_dialog.setModal(True)
        self._keyboard_dialog.accepted.connect(self._dialog_ok_cb)
        gremlin.util.centerDialog(self._keyboard_dialog)
        self._keyboard_dialog.showNormal()

    @QtCore.Slot()
    def _dialog_ok_cb(self):
        """callled when the dialog completes"""

        # grab a new data index as this is a new entry
        self._key_pressed_cb(self._keyboard_dialog.latched_key)


class ModeConditionWidget(AbstractConditionWidget):
    """mode condition UI"""

    def __init__(self, condition, parent=None):
        super().__init__(condition, parent)
        self.setTitle("Mode Condition")

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return

        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(
            callback=lambda: self.deleted.emit(self.condition),
            tooltip="Delete condition",
        )
        widget = gremlin.ui.ui_common.getHContainer(self.delete_button_widget, left_stretch=True, widget_only=True)
        self.main_layout.addWidget(widget)

        self.mode_selector = gremlin.ui.ui_common.QModeSelector()
        if not self.condition.mode:
            self.condition.mode = gremlin.shared_state.edit_mode
        self.mode_selector.setMode(self.condition.mode)

        self.mode_selector.modeChanged.connect(self._handle_mode_changed)

        self.comparison_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.comparison_dropdown.addItem("Equal", "equal")
        self.comparison_dropdown.addItem("Not Equal", "not_equal")
        if self.condition.comparison:
            index = self.comparison_dropdown.findData(self.condition.comparison)
            if index != -1:
                self.comparison_dropdown.setCurrentIndex(index)

        # if self.condition.comparison: self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.currentIndexChanged.connect(self._comparison_changed_cb)

        self.key_label = QtWidgets.QLabel("")

        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip(
            "When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events."
        )
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        widgets = [
            "Activate if current mode is",
            self.comparison_dropdown,
            "to",
            self.mode_selector,
            self.ignore_release_widget,
        ]

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.main_layout.addWidget(widget)

        self.description_widget = QtWidgets.QLabel()
        widget = gremlin.ui.ui_common.getHContainer(["Description:", self.description_widget], widget_only=True)
        self.main_layout.addWidget(widget)

    def _handle_mode_changed(self, mode):
        self.condition.mode = mode

    @QtCore.Slot(bool)
    def _ignore_release_cb(self, checked: bool):
        self.condition.ignore_release = checked

    def setDescription(self, value):
        self.description_widget.setText(value if value else "n/a")

    @QtCore.Slot(str)
    def _comparison_changed_cb(self, text):
        """update comparison"""
        self.condition.comparison = self.comparison_dropdown.currentData()


class StateConditionWidget(AbstractConditionWidget):
    """state condition UI"""

    def __init__(self, condition, parent=None):
        super().__init__(condition, parent)
        self.setTitle("State Condition")

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(
            callback=lambda: self.deleted.emit(self.condition),
            tooltip="Delete condition",
        )
        widget = gremlin.ui.ui_common.getHContainer(self.delete_button_widget, left_stretch=True, widget_only=True)
        self.main_layout.addWidget(widget)

        self.state_selector = gremlin.ui.ui_common.QDataComboBox()
        self.state_selector.currentIndexChanged.connect(self._state_changed)
        self.state_description_widget = QtWidgets.QLabel()
        widget = gremlin.ui.ui_common.getHContainer(["State:", self.state_selector], widget_only=True)
        self.main_layout.addWidget(widget)

        widget = gremlin.ui.ui_common.getHContainer(["Description:", self.state_description_widget], widget_only=True)
        self.main_layout.addWidget(widget)

        self.comparison_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.comparison_dropdown.addItem("Pressed")
        self.comparison_dropdown.addItem("Released")
        if self.condition.comparison:
            self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.currentTextChanged.connect(self._comparison_changed_cb)

        self.key_label = QtWidgets.QLabel("")

        self.grid_widget = QtWidgets.QWidget()
        self.grid_layout = QtWidgets.QGridLayout(self.grid_widget)
        self.grid_layout.addWidget(QtWidgets.QLabel("Activate if"), 0, 0)
        self.grid_layout.addWidget(self.key_label, 0, 1)
        self.grid_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.grid_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 4)

        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip(
            "When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events."
        )
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        self.grid_layout.addWidget(self.ignore_release_widget, 0, 5)

        self.grid_layout.setColumnStretch(5, 2)

        self.main_layout.addWidget(self.grid_widget)

        self.populate_selector()

    @QtCore.Slot(bool)
    def _ignore_release_cb(self, checked: bool):
        self.condition.ignore_release = checked

    def setDescription(self, value):
        self.state_description_widget.setText(value if value else "n/a")

    @QtCore.Slot()
    def _state_changed(self):
        if Shiboken.isValid(self.state_selector):
            data = self.state_selector.currentData()
            description = data.description
            self.setDescription(description)
            self.condition.key = data.key
            self.condition.description = description

    @QtCore.Slot(str)
    def _comparison_changed_cb(self, text):
        """Updates the comparison operation to use.

        :param text the new comparison operation name
        """
        self.condition.comparison = text.lower()

    def populate_selector(self):
        """updates the available states"""
        import gremlin.ui.state_device

        with QtCore.QSignalBlocker(self.state_selector):
            self.state_selector.clear()
            sd = gremlin.ui.state_device.StateData()
            for key, data in sd.getStates().items():
                self.state_selector.addItem(key, data)

            key = self.condition.key
            if key:
                index = self.state_selector.findText(key)
                if index >= 0:
                    self.state_selector.setCurrentIndex(index)
            else:
                # pick the first as the default
                self.condition.key = self.state_selector.currentText()

            if self.state_selector.count():
                data = self.state_selector.currentData()
                description = data.description
                self.setDescription(description)
                self.condition.description = description


class JoystickConditionWidget(AbstractConditionWidget):
    """Widget allowing the configuration of a joystick based condition."""

    def __init__(self, condition, parent=None):
        """Creates a new widget.

        :param condition_data the data to be represented by the widget
        :param parent the parent of this widget
        """
        self.input_event = None
        super().__init__(condition, parent)
        self.setTitle("Joystick Condition")

    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        if not Shiboken.isValid(self):
            return

        ui_common.clear_layout(self.main_layout)

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback=self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback=self._paste_condition)

        self.record_button_widget = gremlin.ui.ui_common.Buttons.getEditWidget(label="Listen", callback=self._request_user_input)
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(
            callback=lambda: self.deleted.emit(self.condition),
            tooltip="Delete condition",
        )

        widgets, layout = gremlin.ui.ui_common.getHContainer(
            [
                self.copy_widget,
                self.paste_widget,
                self.record_button_widget,
                self.delete_button_widget,
            ]
        )

        self.delay_widget = None

        self.main_layout.addWidget(QtWidgets.QLabel("Activate if:"))

        self.device_selector_widget = ui_common.QLimitedComboBox()
        self.device_selector_widget.currentIndexChanged.connect(self._device_selected)
        self.input_selector_widget = ui_common.QLimitedComboBox()
        self.input_selector_widget.currentIndexChanged.connect(self._input_selected)
        # self.axis_repeater_widget = ui_common.QAxisRepeaterProgressbar()  # todo: determin parameters for the axis repeater for conditions
        # self.axis_repeater_widget.valueChanged.connect(self._axis_value_changed)

        self.use_calibrated_input_widget = QtWidgets.QCheckBox("Use calibrated input")
        self.use_calibrated_input_widget.setToolTip(
            "When enabled, the condition will use as input the calibrated data if found.  When disabled, the condition will use the raw input."
        )
        self.use_calibrated_input_widget.setChecked(self.condition.use_calibrated_data)
        self.use_calibrated_input_widget.clicked.connect(self._use_calibrated_input_changed)

        self.selector_container_widget = QtWidgets.QWidget()
        self.selector_container_layout = QtWidgets.QGridLayout(self.selector_container_widget)
        self.selector_container_layout.addWidget(QtWidgets.QLabel("Device:"), 0, 0)
        self.selector_container_layout.addWidget(self.device_selector_widget, 0, 1)
        self.selector_container_layout.addWidget(QtWidgets.QLabel("Input:"), 1, 0)
        self.selector_container_layout.addWidget(self.input_selector_widget, 1, 1)
        # self.selector_container_layout.addWidget(self.axis_repeater_widget, 2, 1)

        self.selector_container_layout.addWidget(QtWidgets.QWidget(), 0, 2)  # spacer column

        self.selector_container_layout.addWidget(widgets, 0, 4)
        self.selector_container_layout.setColumnStretch(2, 2)

        self.range_status_widget = None

        self.ui_container_widget = QtWidgets.QWidget()
        self.ui_container_layout = QtWidgets.QGridLayout(self.ui_container_widget)

        self.options_container_widget = QtWidgets.QWidget()
        self.options_container_widget.setContentsMargins(0, 0, 0, 0)
        self.options_container_layout = QtWidgets.QHBoxLayout(self.options_container_widget)
        self.options_container_layout.setContentsMargins(0, 0, 0, 0)

        self.options_container_layout.addWidget(self.use_calibrated_input_widget)

        self.main_layout.addWidget(self.selector_container_widget)
        self.main_layout.addWidget(self.ui_container_widget)
        self.main_layout.addWidget(self.options_container_widget)

        self._populate_device_selector()
        self._populate_input_selector()

    @QtCore.Slot()
    def _device_selected(self):
        """device changed, update input list"""
        device = self.device_selector_widget.currentData()
        self.condition.device_guid = device.device_guid
        self._populate_input_selector()

    @QtCore.Slot()
    def _input_selected(self):

        device: gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()
        input_type, input_id = self.input_selector_widget.currentData()
        self.condition.device_guid = device.device_guid
        self.condition.input_type = input_type
        self.condition.input_id = input_id
        self.condition.device_name = device.name

        self._init_ui()

    def _populate_device_selector(self):
        device_guid = self.condition.device_guid
        current_index = None
        with QtCore.QSignalBlocker(self.device_selector_widget):
            self.device_selector_widget.clear()
            index = 0
            device: gremlin.joystick_handling.DeviceSummary
            for device in gremlin.joystick_handling.physical_devices():
                self.device_selector_widget.addItem(device.name, device)
                if current_index is None and device_guid and device.device_guid == device_guid:
                    current_index = index
                index += 1

            if current_index is not None:
                self.device_selector_widget.setCurrentIndex(current_index)

        # update condition for the selected device
        device: gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()
        self.condition.device_guid = device.device_guid

    def _populate_input_selector(self):

        input_id = self.condition.input_id
        input_type = self.condition.input_type
        device: gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()

        with QtCore.QSignalBlocker(self.input_selector_widget):
            self.input_selector_widget.clear()

            index = 0  # index of the entry
            current_index = None  # index of the input to select

            # axes - axes are not necessarily sequential
            for i in device.axis_index_list():
                axis_name = device.get_axis_name(i)
                self.input_selector_widget.addItem(axis_name, (InputType.JoystickAxis, i))
                if current_index is None and input_id == i and input_type == InputType.JoystickAxis:
                    current_index = index
                index += 1

            # buttons
            for i in range(device.button_count):
                button_name = device.get_button_name(i + 1)
                self.input_selector_widget.addItem(button_name, (InputType.JoystickButton, i + 1))
                if current_index is None and input_id == i + 1 and input_type == InputType.JoystickButton:
                    current_index = index
                index += 1

            # hats
            for i in range(device.hat_count):
                hat_name = f"Hat {i + 1}"
                self.input_selector_widget.addItem(hat_name, (InputType.JoystickHat, i + 1))
                if current_index is None and input_id == i + 1 and input_type == InputType.JoystickHat:
                    current_index = index
                index += 1

            if current_index is not None:
                self.input_selector_widget.setCurrentIndex(current_index)

            input_type, input_id = self.input_selector_widget.currentData()
            self.condition.input_type = input_type
            self.condition.input_id = input_id

            # update the other UI based on input type
            self._init_ui()

    def _init_ui(self):
        input_type = self.condition.input_type
        # axis_visible = False
        match input_type:
            case InputType.JoystickAxis:
                self._axis_ui()
                # self.axis_repeater_widget.setInput(
                #     device_guid = self.condition.device_guid,
                #     input_id = self.condition.input_id,
                # )
                # axis_visible = True

            case InputType.JoystickButton:
                self._button_ui()

            case InputType.JoystickHat:
                self._hat_ui()

        # self.axis_repeater_widget.setVisible(axis_visible)
        self._update_ui()

    def _update_ui(self):
        """updates UI based on input type"""
        gremlin.util.assert_ui_thread()
        # visible = False
        # self.axis_repeater_widget.setVisible(visible)

        if self.delay_widget:
            input_type = self.condition.input_type
            visible = input_type == InputType.JoystickButton and self.condition.comparison in ("notchangedin", "changedin")
            self.delay_widget.setVisible(visible)

    def _axis_ui(self):
        """Creates the UI needed to configure an axis based condition."""

        gremlin.util.clear_layout(self.ui_container_layout)
        self.lower_widget = ui_common.QFloatLineEdit()
        self.lower_widget.setMinimum(-1.0)
        self.lower_widget.setMaximum(1.0)

        self.grab_low_widget = ui_common.QDataPushButton()
        self.grab_low_widget.setIcon(ui_common.Icons.recordIcon())
        self.grab_low_widget.setMaximumWidth(20)
        self.grab_low_widget.clicked.connect(self._grab_low)
        self.grab_low_widget.setToolTip("Grab axis value")

        self.lower_widget.setValue(self.condition.range[0])
        self.lower_widget.valueChanged.connect(self._range_lower_changed_cb)

        self.upper_widget = ui_common.QFloatLineEdit()
        self.upper_widget.setMinimum(-1.0)
        self.upper_widget.setMaximum(1.0)

        self.upper_widget.setValue(self.condition.range[1])
        self.upper_widget.valueChanged.connect(self._range_upper_changed_cb)

        self.grab_high_widget = ui_common.QDataPushButton()
        self.grab_high_widget.setIcon(
            load_icon(
                "mdi.checkbox-blank-circle",
                qta_color=gremlin.ui.ui_common.Color.recordColor(),
            )
        )
        self.grab_high_widget.setMaximumWidth(20)
        self.grab_high_widget.clicked.connect(self._grab_high)
        self.grab_high_widget.setToolTip("Grab axis value")

        self.comparison_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.comparison_dropdown.addItem("Inside")
        self.comparison_dropdown.addItem("Outside")
        if self.condition.comparison not in ("inside", "outside"):
            self.condition.comparison = "inside"

        self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.setCallback(self._comparison_changed_cb)

        self.range_status_widget = ui_common.QIconLabel()
        self.range_status_widget.setIcon(
            "mdi.checkbox-marked-outline",
            color=gremlin.ui.ui_common.Color.activeColor(),
        )

        range_layout = QtWidgets.QHBoxLayout()
        range_layout.addWidget(self.comparison_dropdown)
        range_layout.addWidget(self.lower_widget)
        range_layout.addWidget(self.grab_low_widget)

        range_layout.addWidget(gremlin.ui.ui_common.QLabel("and"))
        range_layout.addWidget(self.upper_widget)
        range_layout.addWidget(self.grab_high_widget)
        range_layout.addWidget(self.range_status_widget)
        range_layout.addStretch()

        input_label = QtWidgets.QLabel(f"<b>{self.condition.device_name} Axis {self.condition.input_id:d}</b>")
        input_label.setWordWrap(True)
        self.ui_container_layout.addWidget(input_label, 0, 1)
        self.ui_container_layout.addWidget(gremlin.ui.ui_common.QLabel("is"), 0, 2)
        self.ui_container_layout.addLayout(range_layout, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.ui_container_layout.setColumnStretch(4, 2)

        if not self.condition.comparison:
            # update the comparison
            self.condition.comparison = self.comparison_dropdown.currentText()

        self._update_range_state(self._axis_value())

    def _axis_value(self):
        if self.condition.use_calibrated_data:
            value = gremlin.joystick_handling.get_axis(self.condition.device_guid, self.condition.input_id)
        else:
            value = gremlin.joystick_handling.get_curved_axis(self.condition.device_guid, self.condition.input_id)
        return value

    def _button_ui(self):
        """Creates the UI needed to configure a button based condition."""
        gremlin.util.clear_layout(self.ui_container_layout)
        self.comparison_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.comparison_dropdown.addItem("Pressed", "pressed")
        self.comparison_dropdown.addItem("Released", "released")
        self.comparison_dropdown.addItem("Changed In", "changedin")
        self.comparison_dropdown.addItem("Not Changed In", "notchangedin")
        if self.condition.comparison not in (
            "pressed",
            "released",
            "notchangedin",
            "changedin",
        ):
            self.condition.comparison = "pressed"
        index = self.comparison_dropdown.findData(self.condition.comparison)
        if index != -1:
            self.comparison_dropdown.setCurrentIndex(index)

        self.delay_widget = gremlin.ui.ui_common.QDelayWidget(
            self.condition.delay,
            is_seconds=True,
            show_shortcuts=False,
            label="Delay (s):",
            callback=self._handle_delay_changed,
        )

        self.comparison_dropdown.setCallback(self._comparison_changed_cb)

        self.ui_container_layout.addWidget(
            QtWidgets.QLabel(f"<b>{self.condition.device_name} Button {self.condition.input_id:d}</b>"),
            0,
            1,
        )
        self.ui_container_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)

        widgets = [self.comparison_dropdown, self.delay_widget]
        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.ui_container_layout.addWidget(widget, 0, 3, alignment=QtCore.Qt.AlignLeft)

        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)

        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip(
            "When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events."
        )
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        self.ui_container_layout.addWidget(self.ignore_release_widget, 0, 5)
        self.ui_container_layout.setColumnStretch(5, 2)

        if not self.condition.comparison:
            # update the comparison
            self.condition.comparison = self.comparison_dropdown.currentText()

        self._update_ui()

    def _handle_delay_changed(self, value: float):
        gremlin.util.InvokeUiMethod(self._handle_delay_changed_ui, value)

    def _handle_delay_changed_ui(self, value: float):
        self.condition.delay = value

    def _hat_ui(self):
        """Creates the UI needed to configure a hat based condition."""
        gremlin.util.clear_layout(self.ui_container_layout)
        directions = [
            "Center",
            "North",
            "North East",
            "East",
            "South East",
            "South",
            "South West",
            "West",
            "North West",
        ]

        self.comparison_dropdown = ui_common.QHatSelectorComboBox()
        if not self.condition.comparison or self.condition.comparison.capitalize() not in directions:
            self.condition.comparison = "center"

        self.comparison_dropdown.setValue(self.condition.comparison)
        self.comparison_dropdown.valueChanged.connect(self._comparison_changed_cb)

        input_name = f"<b>{self.condition.device_name} Hat {self.condition.input_id}</b>"

        self.ui_container_layout.addWidget(QtWidgets.QLabel(input_name), 0, 1)
        self.ui_container_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.ui_container_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)

        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip("When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.")
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        self.ui_container_layout.addWidget(self.ignore_release_widget, 0, 5)

        self.ui_container_layout.setColumnStretch(6, 2)

        if not self.condition.comparison:
            # update the comparison
            self.condition.comparison = self.comparison_dropdown.currentText()

    @QtCore.Slot(object)
    def _input_pressed_cb(self, event):
        """Processes input events to update the UI and model.

        :param event the input event to process
        """
        self.condition.device_guid = event.device_guid
        self.condition.input_type = event.event_type
        self.condition.input_id = event.identifier

        self.condition.device_name = gremlin.joystick_handling.device_name_from_guid(event.device_guid)  # input_devices.JoystickProxy()[event.device_guid].name
        if event.event_type == InputType.JoystickAxis:
            self.condition.comparison = "inside"
        elif event.event_type == InputType.JoystickButton:
            self.condition.comparison = "pressed"
        elif event.event_type == InputType.JoystickHat:
            self.condition.comparison = gremlin.util.hat_tuple_to_direction(event.value)
        self._create_ui()

    @QtCore.Slot()
    def _request_user_input(self):
        """Prompts the user for the input to bind to this item."""
        self.input_dialog = ui_common.InputListenerWidget(
            [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat],
            return_kb_event=False,
            multi_keys=False,
        )
        self.input_dialog.item_selected.connect(self._input_pressed_cb)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        self.input_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150,
        )
        self.input_dialog.show()

    @QtCore.Slot(float)
    def _range_lower_changed_cb(self, value):
        """Updates the lower part of an axis range.

        :param value the new value
        """
        self.condition.range[0] = value

    @QtCore.Slot(float)
    def _range_upper_changed_cb(self, value):
        """Updates the upper part of an axis range.

        :param value the new value
        """
        self.condition.range[1] = value

    @QtCore.Slot()
    def _grab_low(self):
        self.lower_widget.setValue(self._axis_value())  # also updates condition_data

    @QtCore.Slot()
    def _grab_high(self):
        self.upper_widget.setValue(self._axis_value())  # also updates condition_data

    @QtCore.Slot(bool)
    def _use_calibrated_input_changed(self, checked: bool):
        self.condition.use_calibrated_data = checked
        self._update_range_state(self._axis_value())

    @QtCore.Slot(float, float)
    def _axis_value_changed(self, value: float, curved_value: float):
        self._update_range_state(value)

    def _update_range_state(self, value):
        gremlin.util.InvokeUiMethod(self._update_range_state_ui, value)  # ensure UI thread

    def _update_range_state_ui(self, value):
        """updates the range flag based on the input value"""
        if not Shiboken.isValid(self.range_status_widget):
            return
        if self.range_status_widget:
            visible = False

            v1, v2 = self.condition.range
            in_range = gremlin.util.valueInRange(value, v1, v2)
            match self.condition.comparison:
                case "inside":
                    if in_range:
                        self.range_status_widget.setText("in range")
                        visible = True

                case "outside":
                    if not in_range:
                        self.range_status_widget.setText("outside of range")
                        visible = True

            self.range_status_widget.setVisible(visible)

    @QtCore.Slot(str)
    def _comparison_changed_cb(self, data):
        """Updates the comparison operation to use.

        :param text the new comparison operation name
        """
        if data:
            if self.condition.input_type == InputType.JoystickButton:
                self.condition.comparison = data
            elif self.condition.input_type == InputType.JoystickHat:
                self.condition.comparison = gremlin.types.HatDirection.to_string(data)
            elif self.condition.input_type == InputType.JoystickAxis:
                self.condition.comparison = data
                self._update_range_state(self._axis_value())
            else:
                syslog.warning(f"Invalid input type encountered: {self.condition.input_type}")

            self._update_ui()

    @QtCore.Slot(bool)
    def _ignore_release_cb(self, checked: bool):
        self.condition.ignore_release = checked


class VJoyConditionWidget(AbstractConditionWidget):
    """Widget allowing the configuration of a vJoy based condition."""

    def __init__(self, condition, parent=None):
        """Creates a new widget.

        Parameters
        ==========
        condition_data : VJoyCondition
            data to be represented by the widget
        parent : QObject
            parent of this widget
        """
        self.input_event = None
        super().__init__(condition, parent)
        self.setTitle("vJoy Condition")

        # Initialize UI fully
        self._modify_vjoy(self.vjoy_selector.get_selection())

    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        if not Shiboken.isValid(self):
            return
        ui_common.clear_layout(self.main_layout)

        self.grid_widget = QtWidgets.QWidget()
        self.grid_layout = QtWidgets.QGridLayout(self.grid_widget)

        self.vjoy_selector = ui_common.VJoySelector(
            self._modify_vjoy,
            [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat],
        )
        self.vjoy_selector.set_selection(self.condition.input_type, self.condition.vjoy_id, self.condition.input_id)

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback=self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback=self._paste_condition)

        self.record_button_widget = gremlin.ui.ui_common.Buttons.getEditWidget(label="Listen", callback=self._request_user_input)
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(
            callback=lambda: self.deleted.emit(self.condition),
            tooltip="Delete condition",
        )

        widget, layout = gremlin.ui.ui_common.getHContainer(
            [
                self.copy_widget,
                self.paste_widget,
                self.record_button_widget,
                self.delete_button_widget,
            ]
        )

        self.ui_container_widget = QtWidgets.QWidget()
        self.ui_container_layout = QtWidgets.QGridLayout(self.ui_container_widget)

        label = QtWidgets.QLabel("Activate if:")
        label.setStyleSheet("background: none")

        is_trigger = True
        if self.condition.input_type == InputType.JoystickAxis:
            is_trigger = False  # does not have a release mode
            self._axis_ui()
        elif self.condition.input_type == InputType.JoystickButton:
            self._button_ui()
        elif self.condition.input_type == InputType.JoystickHat:
            self._hat_ui()

        self.grid_layout.addWidget(self.vjoy_selector, 0, 0)
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 2)
        self.grid_layout.addWidget(widget, 0, 3)
        self.grid_layout.setColumnStretch(2, 2)

        if is_trigger:
            self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
            self.ignore_release_widget.setToolTip(
                "When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events."
            )
            self.ignore_release_widget.setChecked(self.condition.ignore_release)
            self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        self.main_layout.addWidget(label)
        self.main_layout.addWidget(self.grid_widget)
        self.main_layout.addWidget(self.ui_container_widget)

        if is_trigger:
            self.main_layout.addWidget(self.ignore_release_widget)

        input_type = self.condition.input_type
        match input_type:
            case InputType.JoystickAxis:
                self._axis_ui()
            case InputType.JoystickButton:
                self._button_ui()
            case InputType.JoystickHat:
                self._hat_ui()

    @QtCore.Slot(bool)
    def _ignore_release_cb(self, checked: bool):
        self.condition.ignore_release = checked

    @QtCore.Slot()
    def _request_user_input(self):
        self.input_dialog = ui_common.InputListenerWidget(
            [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat],
            return_kb_event=False,
            multi_keys=False,
            filter_func=self._filter_input,
        )
        self.input_dialog.item_selected.connect(self._input_pressed_cb)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        self.input_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150,
        )
        self.input_dialog.show()

    def _filter_input(self, event) -> bool:
        # only accept virtual events
        return event.is_virtual

    def _input_pressed_cb(self, event):
        """Processes input events to update the UI and model.

        :param event the input event to process
        """
        self.condition.device_guid = event.device_guid
        self.condition.input_type = event.event_type
        self.condition.input_id = event.identifier

        self.condition.device_name = gremlin.joystick_handling.device_name_from_guid(event.device_guid)  # input_devices.JoystickProxy()[event.device_guid].name
        if event.event_type == InputType.JoystickAxis:
            self.condition.comparison = "inside"
        elif event.event_type == InputType.JoystickButton:
            self.condition.comparison = "pressed"
        elif event.event_type == InputType.JoystickHat:
            self.condition.comparison = gremlin.util.hat_tuple_to_direction(event.value)
        self._create_ui()

    def _axis_ui(self):
        """Creates the UI needed to configure an axis based condition."""
        self.lower_widget = ui_common.QFloatLineEdit()
        self.lower_widget.setMinimum(-1.0)
        self.lower_widget.setMaximum(1.0)

        self.lower_widget.setValue(self.condition.range[0])
        self.lower_widget.valueChanged.connect(self._range_lower_changed_cb)
        self.upper_widget = ui_common.QFloatLineEdit()
        self.upper_widget.setMinimum(-1.0)
        self.upper_widget.setMaximum(1.0)

        self.upper_widget.setValue(self.condition.range[1])
        self.upper_widget.valueChanged.connect(self._range_upper_changed_cb)

        self.comparison_widget = gremlin.ui.ui_common.QDataComboBox()
        self.comparison_widget.addItem("Inside")
        self.comparison_widget.addItem("Outside")
        if self.condition.comparison not in ("inside", "outside"):
            self.condition.comparison = "inside"
        self.comparison_widget.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_widget.currentTextChanged.connect(self._comparison_changed_cb)

        range_layout = QtWidgets.QHBoxLayout()
        range_layout.addWidget(self.comparison_widget)
        range_layout.addWidget(self.lower_widget)
        range_layout.addWidget(QtWidgets.QLabel("and"))
        range_layout.addWidget(self.upper_widget)
        range_layout.addStretch()

        input_label = QtWidgets.QLabel(f"<b>vJoy {self.condition.vjoy_id:d} Axis {self.condition.input_id:d}</b>")
        input_label.setWordWrap(True)

        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(input_label)
        layout.addWidget(QtWidgets.QLabel("is"))
        layout.addLayout(range_layout)
        layout.addStretch()
        self.ui_container_layout.addLayout(layout, 0, 1)

    def _button_ui(self):
        """Creates the UI needed to configure a button based condition."""
        self.comparison_widget = gremlin.ui.ui_common.QDataComboBox()
        self.comparison_widget.addItem("Pressed")
        self.comparison_widget.addItem("Released")
        if self.condition.comparison not in ("pressed", "released"):
            self.condition.comparison = "pressed"
        self.comparison_widget.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_widget.currentTextChanged.connect(self._comparison_changed_cb)

        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(QtWidgets.QLabel(f"<b>vJoy {self.condition.vjoy_id:d} Button {self.condition.input_id:d}</b>"))
        layout.addWidget(QtWidgets.QLabel("is"))
        layout.addWidget(self.comparison_widget)
        layout.addStretch()

        self.ui_container_layout.addLayout(layout, 0, 1)

    def _hat_ui(self):
        """Creates the UI needed to configure a hat based condition."""
        directions = [
            "Center",
            "North",
            "North East",
            "East",
            "South East",
            "South",
            "South West",
            "West",
            "North West",
        ]
        self.comparison_widget = ui_common.QHatSelectorComboBox()
        if not self.condition.comparison or self.condition.comparison.capitalize() not in directions:
            self.condition.comparison = "center"
        self.comparison_widget.setValue(self.condition.comparison)
        self.comparison_widget.valueChanged.connect(self._comparison_changed_cb)

        layout = QtWidgets.QHBoxLayout()

        layout.addWidget(QtWidgets.QLabel(f"<b>vJoy {self.condition.vjoy_id:d} Hat {self.condition.input_id:d}</b>"))
        layout.addWidget(QtWidgets.QLabel("is"))
        layout.addWidget(self.comparison_widget)
        layout.addStretch()

        self.ui_container_layout.addLayout(layout, 0, 1)

    def _modify_vjoy(self, data):
        # fix: 5/29/24 EMCS don't override prior value if already a valid value to prevent a condition reset
        self.condition.vjoy_id = data["device_id"]
        self.condition.input_type = data["input_type"]
        self.condition.input_id = data["input_id"]

        if data["input_type"] == InputType.JoystickAxis:
            if self.condition.comparison not in ("inside", "outside"):
                self.condition.comparison = "inside"
        elif data["input_type"] == InputType.JoystickButton:
            if self.condition.comparison not in ("pressed", "released"):
                self.condition.comparison = "pressed"
        elif data["input_type"] == InputType.JoystickHat:
            directions = (
                "center",
                "north",
                "north-east",
                "east",
                "south-east",
                "south",
                "south-west",
                "west",
                "north-west",
            )
            if self.condition.comparison not in directions:
                self.condition.comparison = "center"
        self._create_ui()

    def _range_lower_changed_cb(self, value):
        """Updates the lower part of an axis range.

        :param value the new value
        """
        self.condition.range[0] = value

    def _range_upper_changed_cb(self, value):
        """Updates the upper part of an axis range.

        :param value the new value
        """
        self.condition.range[1] = value

    def _comparison_changed_cb(self, data):
        """Updates the comparison operation to use.

        :param text the new comparison operation name
        """
        if self.condition.input_type == InputType.JoystickButton:
            self.condition.comparison = data.casefold()
        elif self.condition.input_type == InputType.JoystickHat:
            self.condition.comparison = gremlin.types.HatDirection.to_string(data)
        elif self.condition.input_type == InputType.JoystickAxis:
            self.condition.comparison = data.casefold()
        else:
            syslog.warning(f"Invalid input type encountered: {self.condition.input_type}")


class InputActionConditionWidget(AbstractConditionWidget):
    """Creates the UI needed to configure an input action based condition."""

    def __init__(self, condition_data, parent=None):
        """Creates a new widget.

        :param condition_data the data to be represented by the widget
        :param parent the parent of this widget
        """
        super().__init__(condition_data, parent)
        self.setTitle("Action Condition")

    def _create_ui(self):
        """Creates the configuration UI for this widget."""
        if not Shiboken.isValid(self):
            return
        ui_common.clear_layout(self.main_layout)
        self.grid_widget = QtWidgets.QWidget()
        self.grid_layout = QtWidgets.QGridLayout(self.grid_widget)

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback=self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback=self._paste_condition)

        self.state_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.state_dropdown.addItem("Pressed")
        self.state_dropdown.addItem("Released")
        if self.condition.comparison:
            self.state_dropdown.setCurrentText(self.condition.comparison.capitalize())
        else:
            self.condition.comparison = "pressed"
        self.state_dropdown.currentTextChanged.connect(self._state_selection_changed)

        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback=lambda: self.deleted.emit(self.condition))
        widgets, layout = gremlin.ui.ui_common.getHContainer(
            [
                self.copy_widget,
                self.paste_widget,
                self.delete_button_widget,
            ]
        )

        self.grid_layout.addWidget(QtWidgets.QLabel("Activate when"), 0, 0)
        self.grid_layout.addWidget(QtWidgets.QLabel("<b>this input</b>"), 0, 1)
        self.grid_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.grid_layout.addWidget(self.state_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)

        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.grid_layout.addWidget(widgets, 0, 6)
        self.grid_layout.setColumnStretch(4, 2)
        self.main_layout.addWidget(self.grid_widget)

    def _state_selection_changed(self, label):
        """Updates the activation state of the condition.

        :param label the new activation state
        """
        self.condition.comparison = label.lower()


class ConditionView(AbstractView):
    """Widget visualizing a condition model instance."""

    # Mapping between data and ui classes

    condition_map = {
        "Keyboard": [BaseKeyboardCondition, KeyboardConditionWidget],
        "Joystick": [BaseJoystickCondition, JoystickConditionWidget],
        "vJoy": [BaseVJoyCondition, VJoyConditionWidget],
        "Action": [BaseInputActionCondition, InputActionConditionWidget],
        "State": [BaseStateCondition, StateConditionWidget],
        "Mode": [BaseModeCondition, ModeConditionWidget],
    }

    # Mapping between application rule label and enumeration
    rules_map = {
        "All": ActivationRule.All,
        "Any": ActivationRule.Any,
        ActivationRule.All: "All",
        ActivationRule.Any: "Any",
    }

    def __init__(self, model: ConditionModel, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        assert isinstance(model, ConditionModel), "invalid condition model"
        super().__init__(model=model, parent=parent)

        self._container = None
        self._draw_once = False

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.controls_layout = QtWidgets.QHBoxLayout()
        self.controls_layout.setSpacing(8)
        self.conditions_layout = QtWidgets.QVBoxLayout()

        self.main_layout.addLayout(self.controls_layout)
        self.main_layout.addLayout(self.conditions_layout)

        # Condition truth rules
        self.rule_selector = gremlin.ui.ui_common.QDataComboBox()
        self.rule_selector.addItem("All")
        self.rule_selector.addItem("Any")
        self.rule_selector.currentTextChanged.connect(self._rule_changed_cb)
        self.controls_layout.addWidget(QtWidgets.QLabel("Requires"))
        self.controls_layout.addWidget(self.rule_selector)
        self.controls_layout.addWidget(QtWidgets.QLabel("condition(s):"))

        self.controls_layout.addStretch()

        # Condition selector
        self.condition_selector = gremlin.ui.ui_common.QDataComboBox()
        self.condition_selector.addItem(
            "Keyboard Condition",
        )
        self.condition_selector.addItem("Joystick Condition")
        self.condition_selector.addItem("vJoy Condition")
        self.condition_selector.addItem("Action Condition")
        self.condition_selector.addItem("State Condition")
        self.condition_selector.addItem("Mode Condition")

        config = gremlin.config.Configuration()
        last_selector = config.condition_selector
        index = self.condition_selector.findText(last_selector)
        if index != -1:
            self.condition_selector.setCurrentIndex(index)
        self.condition_selector.currentIndexChanged.connect(self._change_condition_selector)
        self.condition_add_button = gremlin.ui.ui_common.Buttons.getAddWidget(tooltip="Adds a condition", callback=self._add_condition)

        self.controls_layout.addWidget(self.condition_selector)
        self.controls_layout.addWidget(self.condition_add_button)

        self.help_button = gremlin.ui.ui_common.Buttons.getHelpWidget(callback=self._show_hint)
        self.controls_layout.addWidget(self.help_button)

        copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget(callback=self._copy_condition)
        paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget(callback=self._paste_condition)

        self.controls_layout.addWidget(copy_widget)
        self.controls_layout.addWidget(paste_widget)

    def setContainer(self, container):
        """sets the container"""
        self._container = container

    @QtCore.Slot()
    def _copy_condition(self):
        helper = ConditionHelper()
        helper.copy_condition(self._container.activation_condition)

    @QtCore.Slot()
    def _paste_condition(self):
        clipboard = gremlin.clipboard.Clipboard()
        helper = ConditionHelper()
        helper.paste_condition(self._container, clipboard.data)

    @QtCore.Slot()
    def _change_condition_selector(self):
        config = gremlin.config.Configuration()
        config.condition_selector = self.condition_selector.currentText()

    def redraw(self, force=False):
        # assert inspect.stack()[1].function == "_fireChanged","redraw should only be called due to a model trigger"
        gremlin.util.InvokeUiMethod(self._redraw_ui, force)  # ensure on UI thread

    def _create_ui(self):
        """recreates the UI based on the model"""
        if not Shiboken.isValid(self):
            return

        gremlin.util.clear_layout(self.conditions_layout)

        # create a widget for each condition
        lookup = {}
        for entry in ConditionView.condition_map.values():
            lookup[entry[0]] = entry[1]

        condition_count = self.model.rows()
        for i in range(condition_count):
            data = self.model.data(i)
            condition_widget = lookup[type(data)](data)
            condition_widget.deleted.connect(lambda local_data: self.model.delete_condition(local_data))
            self.conditions_layout.addWidget(condition_widget)

    def _redraw_ui(self, force=False):
        """Redraws the entire view.  must be on UI thread"""

        if force or not self._draw_once or self._model.modelChanged:
            # only update the UI on model change
            self._create_ui()
            self._draw_once = True  # indicate drawn

    def _add_condition(self, condition=None):
        """Adds a condition to the view's model."""

        if not condition:
            data_type = ConditionView.condition_map[self.condition_selector.currentText().split()[0]][0]
            self.model.add_condition(data_type())
        else:
            self.model.add_condition(condition)

    def _rule_changed_cb(self, text):
        """Updates the rule of the model.

        :param text the new rule value
        """
        self.model.rule = ConditionView.rules_map[text]

    def _model_changed(self):
        """Updates the view when the model changes."""
        self.rule_selector.setCurrentText(ConditionView.rules_map[self.model.rule])
        self.redraw()

    def _show_hint(self, state):
        """Shows a help message regarding the condition types.

        :param state push button state
        """
        QtWidgets.QWhatsThis.showText(
            self.help_button.mapToGlobal(QtCore.QPoint(0, 10)),
            gremlin.hints.hint.get("cond:types", ""),
        )


class ActivationConditionWidget(QtWidgets.QWidget):
    """Widget displaying the UI used to configure activation conditions."""

    # Signal which is emitted whenever the widget's contents change
    activation_condition_modified = Signal()

    # Maps activation type name to index
    activation_type_to_index = {None: 0, "action": 1, "container": 2}

    def __init__(self, container: AbstractContainer, parent=None):
        """Creates a new instance.

        :param profile_data the profile data associated with the conditions
        :param parent the parent widget of this
        """
        assert isinstance(container, AbstractContainer), "invalid container"
        super().__init__(parent)
        self.container = container
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self._create_ui()

        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.connect(self._update_ui)

    def _create_ui(self):
        """Creates the configuration UI."""
        if not Shiboken.isValid(self):
            return
        self.help_button = gremlin.ui.ui_common.Buttons.getHelpWidget(callback=self._show_hint)

        self.controls_layout = QtWidgets.QHBoxLayout()
        self.controls_layout.setContentsMargins(0, 0, 0, 0)
        self.controls_layout.addWidget(QtWidgets.QLabel("Conditions Definitions:"))
        self.controls_layout.addWidget(self.help_button)
        self.controls_layout.addStretch()

        self.main_layout.addLayout(self.controls_layout)

        # conditions for the container

        self.container_condition_frame_widget = gremlin.ui.ui_common.QBoxFrame()
        self.container_condition_frame_widget.setContentsMargins(0, 0, 0, 0)
        self.container_condition_frame_layout = QtWidgets.QVBoxLayout(self.container_condition_frame_widget)

        self.activation_count_widget = QtWidgets.QLabel()
        self.container_condition_frame_layout.addWidget(self.activation_count_widget)
        self.container_condition_model = ConditionModel(self.container, self.container.activation_condition)

        self.container_condition_view = ConditionView(self.container_condition_model)
        self.container_condition_view.setContainer(self.container)
        self.container_condition_view.setModel(self.container_condition_model)

        self.container_condition_frame_layout.addWidget(self.container_condition_view)
        # self.container_condition_frame_layout.addStretch()

        self.main_layout.addWidget(self.container_condition_frame_widget)

        self.container_condition_view.redraw()

        self._update_counts()

    def _update_condition(self):
        gremlin.util.InvokeUiMethod(self._update_conditions_ui)

    @QtCore.Slot()
    def _update_conditions_ui(self):
        """updates the condition UI for this container"""
        # self.activation_condition_modified.emit()
        self.container_condition_view.redraw()

    @QtCore.Slot(object)
    def _update_ui(self, container):
        if self.container.id == container.id:
            self._update_counts()

    def _update_counts(self):
        """refreshes counts"""
        if not Shiboken.isValid(self.activation_count_widget):
            return
        if self.container:
            self.activation_count_widget.setText(f"Container action conditions ({self.container.condition_count} found):")
        else:
            # not a container
            self.activation_count_widget.setText("Conditions:")

    def _show_hint(self, state):
        """Shows a help message.

        :param state push button state
        """
        QtWidgets.QWhatsThis.showText(
            self.help_button.mapToGlobal(QtCore.QPoint(0, 10)),
            gremlin.hints.hint.get("cond:granularity", ""),
        )


class BaseDeviceTabWidget(gremlin.ui.ui_common.QSplitTabWidget):
    """Widget used to display the input joystick device."""

    # inputChanged = Signal(
    #     str, object, object
    # )  # indicates the input selection changed sends (device_guid string, input_type, input_id)

    def __init__(
        self,
        device: DeviceSummary,
        profile: gremlin.base_profile.Profile,
        mode: str,
        create_callback: Callable = None,  # custom create widget handler if needed
        object_name="Joystick",
        enable_filter=False,  # true if the widget supports input item filters
        model_empty_callback: Callable = None,  # optional, called if UI is ready and no data is visible in the model
        custom_input_widget_callback: Callable = None,  # custom input widget handler
        blank_input_message: str = "No inputs found.",
        data=None,
        parent=None,
    ):
        """Creates a new object instance.

        :param device device information about this widget's device
        :param profile profile data of the entire device
        :param mode the current mode to display
        :param object_name: display title
        :param create_callback: (input_item) -> widget, callback to create a mapping widget if needed
        :param parent the parent of this widget
        """

        assert device is not None, "Device must be provided"
        assert profile is not None, "Profile cannot be None"

        assert isinstance(profile, gremlin.base_profile.Profile), "Invalid profile type"
        assert mode is not None and mode != "", "Mode cannot be None or empty"

        super().__init__(
            object_name=object_name,
            device_guid=device.device_guid,
            enable_filter=enable_filter,
            parent=parent,
        )

        self.device = device
        self.profile = profile
        self.device_node = profile.getDeviceNode(device.device_guid)

        assert isinstance(custom_input_widget_callback, Callable) if custom_input_widget_callback is not None else True, (
            "Invalid custom input widget create callback"
        )
        self._custom_widget_handler = custom_input_widget_callback

        assert isinstance(model_empty_callback, Callable) if model_empty_callback is not None else True, "Invalid model empty callback"
        self._model_empty_callback = model_empty_callback

        self._ui_created = False  # true if UI was created for this widget

        self._input_item_list_view: InputItemListView = None
        self._input_item_list_model: InputItemListModel = None
        self._input_item_mapping_widget = None  # mapping display
        self._input_item_blank_message = blank_input_message

        # last index selected, -1 means none
        self._last_selected_index = -1  # last selected input index in the input list view
        self._last_selected_input_item: InputItem = None  # last selected input
        self._last_selected_widget: InputItemMappingWidget = None  # last selected input mapping widget

        if __debug__ and create_callback:
            assert callable(create_callback), "invalid create widget callback"
        self._create_widget_callback = create_callback
        self.addRegisteredWidgetCallback(self._handle_widget_registered)
        self.addUnregisteredWidgetCallback(self._handle_widget_unregistered)

        # global event handling
        el = gremlin.event_handler.EventListener()
        el.tab_selected.connect(self._handle_tab_changed)
        el.jump_to_mapped_input.connect(self._handle_jump_to_mapped_input)
        if self.filtersEnabled:
            el.input_filtered_change.connect(self._handle_input_filter_changed)

        # holds the header widgets above the list view in the left side
        self.left_panel_header_container = QtWidgets.QWidget()
        self.left_panel_header_layout = QtWidgets.QVBoxLayout(self.left_panel_header_container)

        self.addLeftPanelWidget(self.left_panel_header_container)

        # holds the input list on the left side below the header
        self.listview_container = QtWidgets.QStackedWidget()
        self.listview_container.addWidget(gremlin.ui.ui_common.QEmptyWidget())  # QtWidgets.QLabel("Not loaded"))  # index 0 = blank placeholder

        self.addLeftPanelWidget(self.listview_container)

    def itemAt(self, index: int):
        """gets the input item as the specified index, None if the index is invalid or the model isn't set"""
        if self._input_item_list_model is not None:
            return self._input_item_list_model.itemAt(index)
        return None

    def indexOf(self, input_item: InputItem):
        """gets the index of the input item if in the model"""
        if self._input_item_list_model is not None:
            return self._input_item_list_model.indexOf(input_item)
        return -1

    def addLeftPanelHeaderWidget(self, widget):
        """adds a widget to the left panel header (above the input list)"""
        assert isinstance(widget, QtWidgets.QWidget), "invalid widget"
        self.left_panel_header_layout.addWidget(widget)

    def clearLeftPanelHeaderWidget(self):
        """removes all the widgets in the left panel header"""
        gremlin.util.clear_layout(self.left_panel_header_layout)

    def _cleanup_ui(self):
        el = gremlin.event_handler.EventListener()

        # el.edit_mode_changed.disconnect(self._handle_edit_mode_changed)
        # el.config_changed.disconnect(self._config_changed_cb)
        el.lock_inputs.disconnect(self._handle_lock_inputs)
        el.unlock_inputs.disconnect(self._handle_unlock_inputs)

        el.jump_to_mapped_input.disconnect(self._handle_jump_to_mapped_input)
        if self.filtersEnabled:
            el.input_filtered_change.disconnect(self._handle_input_filter_changed)

        self.setInputItemListView(None)

    def ensureLoaded(self):
        """ensures the device has inputs loaded because the inputs are delay loaded until the tab is visible"""
        if gremlin.util.is_ui_thread():
            self._ensureLoaded_ui()
        else:
            gremlin.util.InvokeUiMethod(self._ensureLoaded_ui)

    def isLoaded(self) -> bool:
        """true if the widget is loaded"""
        return self._input_item_list_model is not None and self._input_item_list_view is not None

    def _ensureLoaded_ui(self):
        """ensures the data is loaded into the widget - runs on UI thread"""
        if self._input_item_list_view is None:
            self._create_ui()

        assert self._input_item_list_model is not None, "invalid model"
        assert self._input_item_list_view is not None, "invalid view"

        if self._input_item_list_model.rows() == 0:
            if self._model_empty_callback:
                self._model_empty_callback()
            else:
                self._input_item_list_model.trigger()

    def isInputListViewCreated(self) -> bool:
        """true if the input list view has been created"""
        return self._input_item_list_view is not None

    def onInputListViewCreated(self):
        """called when the input list view is created"""
        pass

    def onInputListViewRemoved(self):
        """called when the input list view is removed"""
        pass

    def _create_ui(self):
        """load the list view for the joystick device if not loaded yet"""
        # if there are no inputs in the model, pick the default filter for the devices
        assert not self._ui_created, "_create_ui should only be called once per widget life"
        assert self._input_item_list_model is not None, "invalid model"
        if self._input_item_list_model.count() == 0:
            # no inputs in the model
            if self._input_item_list_model.rows():
                # device has inputs
                model = self._input_item_list_model
                input_filter = self.getDefaultFilter()
                input_items = model.getUnfilteredItems()
                for device_guid in input_filter:
                    for input_type in input_filter[device_guid]:
                        for input_id in input_filter[device_guid][input_type]:
                            input_item: gremlin.input_item.InputItem
                            input_item = next(
                                (
                                    item
                                    for item in input_items
                                    if item.device_guid == device_guid and item.input_type == input_type and item.input_id == input_id
                                ),
                                None,
                            )
                            if input_item:
                                model.setItemFiltered(input_item, True, False)

                    device = gremlin.joystick_handling.getDevice(device_guid)
                    syslog.info(f"JOYSTICK: load defaults for device [{device.name}]")

        if self._input_item_list_view is None:
            device = self.device
            # view that displays all the inputs in the model, which can be filtered
            widget = InputItemListView(
                name=device.name,
                custom_widget_handler=self._custom_widget_handler,  # called when an input widget has to be created in the list view
                selection_changed_handler=self._handle_input_item_selected,  # called when the selected input changes
                device_guid=device.device_id,
                model=self._input_item_list_model,
                blank_message=self._input_item_blank_message,
            )

            self.setInputItemListView(widget)  # registers handlers

            self.listview_container.setCurrentIndex(1)  # display the list view in the stack widget

            # update the selection if nothing is selected
            selected_index = widget.currentIndex()
            if selected_index is not None and selected_index != -1:
                self.selectInputItemIndex(selected_index)

        # indicate created
        self._ui_created = True

        new_widget = self._input_item_list_view.getSelectedWidget()
        if new_widget:
            # a selection was found
            self._handle_input_item_selected_ui(None, new_widget)

    def _handle_create_widget(self, input_item: InputItem):

        index = self._input_item_list_model.indexOf(input_item)
        assert index != -1, "input item is not in the list"

        prefix = input_item.input_type.name
        widget = InputItemMappingWidget(input_item=input_item, object_name=f"{prefix}: {input_item.display_name}")
        device_name = gremlin.joystick_handling.device_name_from_guid(self.device_guid)
        widget.setObjectName(f"InputItemConfig for device {device_name} index: {index} input item: [{input_item.display_name}] ")
        widget.description_changed.connect(lambda x: self._description_changed_cb(index, x))
        widget.description_clear.connect(lambda: self._description_clear_cb(index, widget))
        input_item.setMappingWidget(widget)  # keep a reference to the mapping widget
        return widget

    def _description_changed_cb(self, index, text):
        """called when the description text of the widget changes to update the description on the input item

        :param: index = the index of the input widget to update with the new text

        """
        widget = self.inputItemListView.widget(index)
        if widget:
            assert hasattr(widget, "setDescription"), "invalid widget - missing setDescription method"
            widget.setDescription(text)
        else:
            syslog.error(f"set description (joystick input) failed: index: [{index}] does not exist.")

    def _description_clear_cb(self, index, widget):
        """delete description entry"""
        # with QtCore.QSignalBlocker(widget.description_field):
        #     widget.description_field.setText("")
        item_widget = self._input_item_list_view.widget(index)
        if item_widget:
            assert hasattr(item_widget, "setDescription"), "invalid widget - missing setDescription method"
            item_widget.setDescription(None)

    def _handle_tab_changed(self, device_guid):
        """occurs when a tab is made visible"""
        pass

    def _handle_widget_registered(self, key, index, widget):
        """called when a mapping widget is added"""

    def _handle_widget_unregistered(self, key, index, widget):
        """called when a mapping widget is removed"""
        if self._last_selected_widget == widget:
            # remove the reference
            self._last_selected_widget = None

    def _handle_jump_to_mapped_input(self):
        gremlin.util.InvokeUiMethod(self._handle_jump_to_mapped_input_ui)

    def _handle_jump_to_mapped_input_ui(self):
        """jumps to the first mapped input"""
        if Shiboken.isValid(self):
            for input_item in self.inputItemListModel.getFilteredItems():
                if input_item.hasContainers:
                    index = self.inputItemListModel.indexOfInputItem(input_item)
                    self._handle_input_item_selected(index)
                    break

    def _handle_input_filter_changed(self, device_guid):
        """called when input filter is changed"""
        if not gremlin.util.compare_guid(device_guid, self.device_guid) or self._input_dirty:
            # not ours
            return

        verbose = gremlin.config.Configuration().verbose_mode_filter
        if verbose:
            device = gremlin.joystick_handling.getDevice(device_guid)
            syslog.info(f"FILTER: [{device.name}] inputs marked dirty")

        self.inputItemListModel.refresh()  # indicate the list should be refreshed because it has changed

    def _handle_lock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_lock_inputs_ui, data)  # ensure on UI thread

    def _handle_unlock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_unlock_inputs_ui, data)  # ensure on UI thread

    def _handle_lock_inputs_ui(self, data):
        """lock all inputs event"""
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            # self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = True
            # self.setUpdatesEnabled(True)

    def _handle_unlock_inputs_ui(self, data):
        """unlock all inputs event"""
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            # self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = False
            # self.setUpdatesEnabled(True)

    @property
    def inputItemListModel(self) -> InputItemListModel:
        """input item model for the mapping widget (left tab)"""
        return self._input_item_list_model

    @inputItemListModel.setter
    def inputItemListModel(self, model: InputItemListModel):
        self.setInputItemListModel(model)

    def setInputItemListModel(self, model: InputItemListModel):
        """sets the model"""
        if self._input_item_list_model != model:
            self._input_item_list_model = model
        if self._input_item_list_view is not None:
            self._input_item_list_view.setModel(model)

    @property
    def inputItemListView(self) -> InputItemListView:
        """input item list view for the mapping widget (left tab)"""
        return self._input_item_list_view

    def setInputItemListView(self, widget):
        gremlin.util.InvokeUiMethod(self._set_input_list_view_ui, widget)

    def _set_input_list_view_ui(self, widget):
        verbose = gremlin.config.Configuration().verbose_mode_ui_level(3)
        current_widget = self._input_item_list_view
        if current_widget != widget:
            if current_widget:
                current_widget.removeSelectionChangeCallback(self._handle_input_item_selected)  # unhook selected callback
                self.onInputListViewRemoved()
                current_widget.hide()
                self.listview_container.removeWidget(current_widget)
                gremlin.util.delete_widget(current_widget)

        self._input_item_list_view = widget
        if widget is not None:
            if verbose:
                syslog.info(f"DeviceTabWidget: set input item view for device: [{widget.name}]")
            self._input_item_list_view.addSelectionChangeCallback(
                self._handle_input_item_selected
            )  # hook selected callback - called whenever an input is selected
            self.listview_container.addWidget(widget)
            self.onInputListViewCreated()
            self.inputItemListView.setModel(self.inputItemListModel)
            self.inputItemListView._redraw_ui(force=True)

    def setLastSelectedIndex(self, value: int):
        self._last_selected_index = value

    def setLastSelectedInputItem(self, input_item: InputItem):
        self._last_selected_input_item = input_item

    def setLastSelectedWidget(self, widget: InputItemMappingWidget):
        self._last_selected_widget = widget

    @property
    def lastSelectedInputItem(self) -> InputItem:
        return self._last_selected_input_item

    @property
    def lastSelectedIndex(self) -> int:
        """index of the last selected list view input"""
        return self._last_selected_index

    @property
    def lastSelectedWidget(self) -> InputItemMappingWidget:
        return self._last_selected_widget

    def getSelectedInputItem(self) -> gremlin.base_profile.input_item:
        """gets the last selected input item"""
        return self._last_selected_input_item

    @property
    def inputItemCount(self) -> int:
        """number of inputs in the device"""
        return self._input_item_list_model.rows()

    @property
    def inputWidgetCount(self) -> int:
        """number of input widgets currently in the device"""
        return len(self._input_item_list_view)

    def showBlank(self):
        self._right_panel_stacked_widget.setCurrentIndex(0)

    def showContent(self):
        """shows the mapping widget for the currently selected input"""
        input_item = self.getSelectedInputItem()
        if input_item:
            key = self.getInputItemWidgetKey(input_item)
            widget = self.getRegisteredWidget(key)
            if widget:
                index = self._right_panel_stacked_widget.indexOf(widget)
                if index != -1:
                    self._right_panel_stacked_widget.setCurrentIndex(index)
        else:
            # indicate no input is selected
            self.showBlank()

    def getInputItemMappingWidget(self, input_item: InputItem) -> InputItemMappingWidget:
        """gets the mapping widget associated with the input item - the widget is created if needed"""
        if input_item:
            key = self.getInputItemWidgetKey(input_item)
            widget = self.getRegisteredWidget(key)
            if widget is None:
                if self._create_widget_callback:
                    widget = self._create_widget_callback(input_item)
                else:
                    # create a new widget and register it (this adds it to the page)
                    widget = self._handle_create_widget(input_item)
                    self.registerWidget(key, widget)

            assert widget is not None, f"failed to get a widget for [{input_item.display_name}]"
            return widget
        return None

    def getInputItemMappingWidgetAt(self, index: int) -> InputItemMappingWidget:
        """gets the mapping widget for an input item at the given index"""
        return self.getInputItemMappingWidget(self.getInputItemAt(index))

    def getInputWidget(self, input_item: InputItem) -> InputItemWidget:
        """gets the input widget for a given input item"""
        return self._input_item_list_view.getWidgetForInputItem(input_item)

    def getInputWidgetAt(self, index: int) -> InputItemWidget:
        """gets the input widget by index"""
        return self._input_item_list_view.getWidgetAt(index)

    def getFilteredInputItemAt(self, index: int):
        """gets the input item as the specified position"""
        return self._input_item_list_model.itemAt(index)

    def getInputItemAt(self, index: int):
        """gets the input item at the specified postion - unfiltered"""
        return self._input_item_list_model.getInputItemAt(index)

    def selectInputItemMappingWidget(self, input_item: InputItem) -> InputItemMappingWidget:
        """activates the mapping widget for the given input item
        the widget is created if it doesn't exist or needs to be recreated
        """
        if input_item:
            widget = self.getInputItemMappingWidget(input_item)
            assert widget is not None, f"failed to get a widget for [{input_item.display_name}]"
            _key = self.getWidgetKeyForWidget(widget)
            self.selectRegisteredWidget(widget)  # make it visible
            self.setLastSelectedInputItem(input_item)
            self.setLastSelectedWidget(widget)
            widget.redraw()  # update if needed
            self._input_item_mapping_widget = widget

        return self._last_selected_widget

    def refresh(self, emit=False):
        if gremlin.shared_state.is_redraw_suspended():
            return
        if self._input_item_list_view is None:
            return  # not loaded yet
        if self.isInputListViewCreated():
            gremlin.util.InvokeUiMethod(self._refresh_ui, emit)  # ensure on UI thread

    def _refresh_ui(self, force=False, emit=False):
        """Refreshes the current selection, ensuring proper synchronization. - ensure on UI thread"""

        self.inputItemListModel.refresh()

        index = self._input_item_list_view.current_index
        if index == -1:
            # nothing selected
            if self.inputItemListModel.count():  # filtered count
                # has something to display
                index = 0  # pick the first one

        self.inputItemListModel.trigger(False)
        self.__handle_select_input_index_ui(index, force=force, emit=emit)

    def selectInputItem(self, input_item: InputItem, force=False, emit=True):
        """selects a specific input item"""
        index = self._input_item_list_view.getInputItemIndex(input_item)
        if index != -1:
            gremlin.util.InvokeUiMethod(self._handle_input_item_selected, index, force, emit)

    def selectInputItemIndex(self, index, force: bool = False, emit: bool = True):
        gremlin.util.InvokeUiMethod(self.__handle_select_input_index_ui, index, force, emit)

    def __handle_select_input_index_ui(self, index, force: bool = False, emit: bool = True):
        """selects an input by index"""
        verbose = gremlin.config.Configuration().verbose_mode_ui

        if index != -1:
            if verbose:
                syslog.info(f"DeviceTabWidget: select input index [{index}]")
            self._input_item_list_view.selectItemAt(index, force=force, emit=emit)
            self._input_item_list_view.ensureVisibleIndex(index)


        else:
            if verbose:
                syslog.info("DeviceTabWidget: select input index - nothing to select")

    def _handle_input_item_selected(self, old_widget: InputItemWidget, new_widget: InputItemWidget, emit=True):
        gremlin.util.InvokeUiMethod(self._handle_input_item_selected_ui, old_widget, new_widget, emit)

    def _handle_input_item_selected_ui(self, old_widget: InputItemWidget, widget: InputItemWidget, emit: bool = True):
        """called when an input is selected or deselected"""
        gremlin.util.assert_ui_thread()

        if not Shiboken.isValid(self):
            return

        if not widget or not widget.selected:
            # ignore deselects
            return

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_ui_level(1)

        input_item: InputItem = widget.input_item
        assert input_item is not None, "unexpected: widget should reference a valid input item"

        if self._last_selected_input_item == input_item:
            # same input - ignore reselect
            return

        if verbose:
            syslog.info(f"BaseDeviceTabWidget: input selected: [{input_item.display_name}] index: [{widget.index}]")

        if verbose:
            syslog.info("BaseDeviceWidget: widget selected start")

        device = gremlin.joystick_handling.getDevice(self.device_guid)

        current_mode = gremlin.shared_state.edit_mode

        if verbose:
            if input_item:
                syslog.info(f"Selecting input config item for {device.name} input index [{widget.index}] mode: {current_mode}: {input_item.debug_name}")
            else:
                syslog.info(f"Selecting input config item for {device.name} input index [{widget.index}] mode: {current_mode}: Empty content")

        # select the RIGHT panel item for the input
        device_guid = self.device_guid
        input_type = input_item.input_type
        input_id = input_item.input_id

        if config.debug_ui:
            self._debug_widget.setText(f"Contents for : {input_item.debug_name}")

        # make the mapping widget visible and redraw if needed
        self.selectInputItemMappingWidget(input_item)
        # update container display if blank
        self.updateContainerViewBlankMessage(input_item)

        # remember the last selection
        self._last_selected_input_item = input_item  # update selection

        if emit:
            el = gremlin.event_handler.EventListener()
            el.input_selection_changed.emit(device_guid, input_type, input_id)

            # self.inputChanged.emit(
            #     input_item.device_guid, input_item.input_type, input_item.input_id
            # )

        if verbose:
            syslog.info("BaseDeviceWidget: widget selected end")
