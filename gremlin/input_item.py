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

import enum
from PySide6 import QtWidgets, QtCore, QtGui
from lxml import etree
import lxml.etree
import traceback
import gc
import collections
import gremlin
import gremlin.config
import gremlin.event_handler
import gremlin.singleton_decorator
import gremlin.types
import gremlin.base_conditions
import gremlin.config
import gremlin.event_handler
import gremlin.shared_state
import gremlin.ui.axis_calibration
import gremlin.ui.ui_common
import gremlin.base_profile
import gremlin.input_item
from dinput import DeviceSummary
from gremlin.util import load_icon, load_pixmap, get_guid, TriggerDict
import gremlin.util
from gremlin.input_types import InputType
from gremlin.base_buttons import *
from gremlin.types import DeviceType, TabDeviceType
import gremlin.plugin_manager
import gremlin.ui.ui_common as ui_common
from gremlin.ui.ui_common import QBoxFrame
from functools import partial
from  gremlin.clipboard import Clipboard, ObjectEncoder, EncoderType
import logging
import lxml
from shiboken6 import Shiboken
import psygnal
from psygnal import Signal
import copy
import gremlin.tabstate
import gremlin.hints
from gremlin.types import SendType, ActivationRule

from gremlin.base_classes import AbstractInputItem, BaseProfileData
from gremlin.plugin_manager import ActionPlugins, ContainerPlugins
from gremlin.base_conditions import ConditionTracker

from gremlin.singleton_decorator import SingletonDecorator
import gremlin.actions



from gremlin.ui import virtual_button

syslog = logging.getLogger("system")

CallbackData = collections.namedtuple("ContainerCallback", ["callback", "event"])

class InputIdentifier(QtCore.QObject):

    """Represents the identifier of a single input item."""

    def __init__(self, input_type, device_guid, input_id, device_type, input_name, is_axis = False, is_button = False, input_item : InputItem = None):
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
        self._input_guid = get_guid() # unique internal GUID for this entry
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
        self._input_id = value

    @property
    def input_name(self) -> str:
        return self._input_name
    @input_name.setter
    def input_name(self, value : str):
        self._input_name = value

    @property
    def guid(self):
        return self._input_guid

    @property
    def is_axis(self) -> bool:
        ''' true if this item is setup as an axis input (linear) '''
        if self._input_id and hasattr(self._input_id, "is_axis"):
            return self._input_id.is_axis
        return self._is_axis

    @property
    def is_button(self) -> bool:
        ''' true if this item is setup as an button input (momentary) '''
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
        ''' true if the item is a hat '''
        return self._input_type == InputType.JoystickHat

    def getInputItem(self):
        ''' gets the input item for this identifier '''
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

        return None # not found


class AbstractModel(QtCore.QAbstractItemModel):

    """Base class for MVC models."""

    data_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

    def rows(self):
        """Returns the number of rows in the model.

        :return number of rows
        """
        pass

    def count(self):
        return self.rows()

    def data(self, index):
        """Returns the data entry stored at the provided index.

        :param index the index for which to return data
        :return data stored at the given index
        """
        assert False, "data method not implemented in model subclass" 

    def add(self, data):
        """Adds a new entry to the model. """
        assert False, "Add method not implemented in model subclass"

    def remove(self, data):
        """Removes the given entry from the model."""
        assert False, "Remove method not implemented in model subclass" 

    def clear(self, data):
        """Removes all the given entry from the model."""
        assert False, "Remove method not implemented in model subclass" 

    def refresh(self, emit = True):
        """Refreshes the model, triggering a data changed event.""" 
        assert False, "Refresh method not implemented in model subclass"


class AbstractView(QtWidgets.QWidget):

    """Base class for MVC views."""

    # Signal emitted when a entry is selected
    item_selected = QtCore.Signal(int, bool) # index of the item being selected and selection flag 
    item_edit = QtCore.Signal(object, int, object)  # widget, index, model data object
    item_edit_curve = QtCore.Signal(object, int, object) # widget, index , model data object
    item_delete_curve = QtCore.Signal(object, int, object) # widget, index , model data object
    item_closed = QtCore.Signal(object, int, object)  # widget, index, model data object
    

    def __init__(self, model : AbstractModel =None, callback : Callable = None, parent=None):
        """Creates a new view instance.
        :param model: the model to visualize
        :param callback: an optional callback to be called when the model changes - this is used by the container to trigger updates when the model changes subject to begin/end model change calls
        :param parent: the parent of this view widget
        """
        super().__init__(parent)
        self._id = gremlin.util.get_uuid()
        if model is not None and not isinstance(model, AbstractModel):
            raise TypeError("Invalid model type")  
        self._model = model

        self._redraw_suspended_stack = 0 # non 0 = redraw is suspended
        self._redraw_pending = False # true if a redraw is pending while redraw is disabled
        
        self._container = None
        if __debug__:
            if callback is not None and not callable(callback):
                raise TypeError("Callback must be callable")
        self._model_change_callbacks : list[Callable] = []
        if callback is not None:
            self._model_change_callbacks.append(callback)

        self._model_call_stack = 0 # stack to manage when the model change event is fired

    def addCallabck(self, callback : Callable):
        ''' adds a callback to be called when the model changes - this is used by the container
        :param callback: the callback to add
        '''
        if __debug__ and callback is not None and not callable(callback):
            raise TypeError("Callback must be callable")
        if not callback in self._model_change_callbacks:
            self._model_change_callbacks.append(callback)  

    def removeCallback(self, callback : Callable):
        ''' removes a callback from the list of callbacks to be called when the model changes - this is used by the container
        :param callback: the callback to remove
        '''
        if callback in self._model_change_callbacks:
            self._model_change_callbacks.remove(callback)

    def refreshModel(self):
        ''' forces a refresh of the view by refreshing a model if it changed '''
        if self._model:
            self.pushSuspended()
            self._model.refresh()
            self._redraw_pending = True # force an update
            self.popSuspended()
            
        
    def pushSuspended(self):
        ''' disable redraw on model change '''
        self._redraw_suspended_stack += 1

    def popSuspended(self, reset = False):
        ''' enable redraw on model change '''
        if reset:
            self._redraw_suspended_stack = 0
        if self._redraw_suspended_stack > 0:
            self._redraw_suspended_stack -= 1
        if self._redraw_suspended_stack == 0 and self._redraw_pending:
            self._handle_model_changed()
            
    def _handle_model_changed(self, force = False):
        """Handles changes in the model."""
        
        if not force and (self._model_changed and self._model_call_stack == 0) or self._redraw_pending:
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
            
            self.redraw(force = True)
            self._model_changed = False

    def beginModelChange(self):
        ''' call this before making a change to the model to prevent multiple change events from firing '''
        self._model_call_stack += 1

    def endModelChange(self, reset : bool = False):
        ''' call this after making a change to the model to trigger the change event if needed '''
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
    def model(self, value):
        
        if value != self._model:
            
            if self._model:
                self._model.data_changed.disconnect(self._model_changed)
            if __debug__ and value is not None and not isinstance(value, AbstractModel):
                raise TypeError("Invalid model type")
            self._model = value
            if self._model:
                self._model.data_changed.connect(self._model_changed)
            self._model_changed()

    def setModelChangeCallback(self, callback : Callable):
        ''' sets a callback to be called when the model changes - this is used by the container '''
        if __debug__ and callback is not None and not callable(callback):
            raise TypeError("Callback must be callable")
        self._model_change_callback = callback

    def _model_changed(self):
        self._model_changed = True
        if self._model_call_stack == 0:
            self._handle_model_changed()

    
    def setModel(self, model):
        """Sets the model to display with this view.

        :param model the model to visualize
        """
        self.model = model

   

    def modelChanged(self) -> bool:
        ''' returns whether the model has changed - used in the context of begin/end to detect model changes '''
        return self._model_changed

    def _select_item(self, index):
        """Selects the item at the provided index

        :param index the index of the item to select
        """
        pass

    def redraw(self, force : bool = False):
        """Redraws the view."""
        assert False, "Redraw method not implemented in view subclass"

class InputItem(gremlin.base_classes.AbstractInputItem):

    """Represents a single input item such as a button or axis, containers and parameters/options associated with that input mapping """

    lockedChanged = Signal(object) # (input_item) fires when the lock state changes - passes the input item as the parameter

    def __init__(self, mode_object : str | gremlin.base_profile.Mode, custom_name_handler : Callable = None, custom_mode_name_handler : Callable = None, override_input_type = None, device_guid = None):
        """Creates a new InputItem instance.
        :param mode_parent: the parent mode object of this input item (gremlin.base_profile.Mode) - required
        :param custom_name_handler: handler() returns a string, whenever the input name is needed
        :param custom_mode_name_handler: handler() returns a string, optional, to override the default mode for special inputs that use special modes

        """
        assert isinstance(mode_object, str) or isinstance(mode_object, gremlin.base_profile.Mode), "Parent parameter must be a string or mode object"
        if isinstance(mode_object, str):
            # convert to a mode object
            profile = gremlin.shared_state.current_profile
            mode_object = profile.get_mode_object(mode_object)

        super().__init__(mode_object.name, None)

        self.parent = mode_object # mode object
        self._input_item_generating_xml = False # xml nesting level
        self._override_input_type = override_input_type # override input type for some types that are different
        self._device_guid = device_guid # hardware input ID
        self._device_id = None # hardware input ID as a string
        self._name = None # device name

        self._input_name = None # input name of the hardware (axis name if an axis)
        if custom_name_handler is not None:
            assert callable(custom_name_handler), "Name handler must be callable "
        self._input_name_handler = custom_name_handler # custom handler
        self.always_execute = False
        self._description = ""
        self._description_readonly = False # true if description is read/only (cannot be changed)
        if custom_mode_name_handler is not None:
            assert callable(custom_mode_name_handler), "Mode name handler must be callable "
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
        self._locked = False # true if the input is locked (cannot make mapping changes)

        self.mapping_widget_id = None # ID of the mapping widget for this input


        # self._profile_mode = None
        self._enabled = True # enabled flag
        if mode_object is not None:
            # find the missing properties from the parenting hierarchy
            item = mode_object
            while True:
                # if isinstance(item, Mode):
                #    self._profile_mode = item.name
                if isinstance(item, gremlin.base_profile.Device):
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
        el.reload_axis_state.connect(self._handle_axis_state_request)

    def setInputNameHandler(self, callback : Callable):
        ''' sets the input name handler (optional) '''
        if callback is not None:
            assert callable(callback), "Callback must be a callable method"
        self._input_name_handler = callback

    def setProfileModeHandler(self, callback : Callable):
        if callback is not None:
            assert callable(callback), "Callback must be a callable method"
        self._profile_mode_callback = callback


    @property
    def is_action(self) -> bool:
        return self._is_action
    @is_action.setter
    def is_action(self, value : bool):
        self._is_action = value

    def _handle_axis_state_request(self):
        ''' request to reload axis state with this input item '''
        if self._is_axis:
            astate = gremlin.event_handler.AxisState()
            astate.registerAxisInputItem(self)

    def toExtraData(self, extra_data = None) -> dict:
        ''' creates or adds properties of the input to create an extra data item '''
        if extra_data is None:
            extra_data = {}

        extra_data["device_guid"] = self.device_guid
        extra_data["device_type"] = self.device_type
        extra_data["input_id"] = self.input_id
        extra_data["mode"] = self.profile_mode

        return extra_data

    def setProfileModeCallback(self, callback):
        ''' sets an override callback to change profile mode return value for special cases '''
        self._profile_mode_callback = callback


    @property
    def profile_mode(self) -> str:
        mode = None
        if self._input_type == InputType.ModeControl:
            if self._input_id in (gremlin.ui.mode_device.ModeInputModeType.ModeProfileLoad,
                                  gremlin.ui.mode_device.ModeInputModeType.ModeProfileStart,
                                  gremlin.ui.mode_device.ModeInputModeType.ModeProfileStop):
                mode = gremlin.shared_state.master_mode
        elif self._input_type == InputType.State:
            mode = gremlin.shared_state.master_mode
        if not mode:
            if self._profile_mode_callback:
                mode = self._profile_mode_callback(self)
            else:
                mode_object = self.parent
                if mode_object:
                    mode = mode_object.name

        return mode


    @property
    def locked(self) -> bool:
        return self._locked
    @locked.setter
    def locked(self, value : bool):

        if self._locked != value:
            # changed in m76T102 by request - allow locking of any input regardless of mapping
            #     if value and not self.containers:
            #         return # cannot lock an input that has no mappings
            self._locked = value
            self.lockedChanged.emit(self)

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
    def sortKey(self):
        ''' gets the sorting key for the particular input '''
        if isinstance(self.input_id, int) or isinstance(self.input_id, float) or isinstance(self.input_id, str):
            return self.input_id
        return self.message_key

    @property
    def hasActions(self) -> bool:
        ''' true if the input item has at least one action '''
        for container in self.containers:
            for action_set in container.action_sets:
                if action_set:
                    return True
        return False

    @property
    def hasContainers(self) -> bool:
        ''' true if the input item has at least one container '''
        return len(self._containers) > 0

    @property
    def hasCalibration(self):
        ''' for axis input devices, returns True if the device has an active calibration '''
        if not self._calibration:
            import gremlin.ui.axis_calibration
            cm = gremlin.ui.axis_calibration.CalibrationManager()
            calibration = cm.getCalibration(self._device_guid, self._input_id)
            self._calibration = calibration

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
        el.input_used_changed.emit(self._device_guid, self._input_type, self._input_id, True)

    def remove_container(self, container):

        if not container in self._containers:
            id = container.id
            for c in self._containers:
                if c.id == id:
                    self._containers.remove(c)
                    break
            return


        # notify every action in the container it's being removed in case some update needs to happen
        for action_set in container.action_sets:
            for action in action_set:
                if hasattr(action,"actionDeleted"):
                    action.actionDeleted()



        self._containers.remove(container)




        # tell the UI about the change
        el = gremlin.event_handler.EventListener()
        el.mapping_changed.emit(self)

        if not len(self._containers):
            # only fire the update is the container list is empty
            el.input_used_changed.emit(self._device_guid, self._input_type, self._input_id, False)

    def get_containers(self):
        return self._containers

    @property
    def containers(self):
        return self._containers

    def setContainers(self, containers):
        self._containers = containers


    @gremlin.base_classes.AbstractInputItem.input_type.setter
    def input_type(self, input_type : InputType):
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
        self._input_type = input_type
        self._update_input()

    def getInputType(self):
        ''' gets the input type or the override input type'''
        if hasattr(self._input_id, "getOverrideInputType"):
            override_input_type = self._input_id.getOverrideInputType()
        else:
            override_input_type = self.getOverrideInputType()
        return override_input_type

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
            container : gremlin.input_item.AbstractContainer
            for container in self._containers:
                for action_set in container.action_sets:
                    action : gremlin.base_profile.AbstractAction
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

    def getConditions(self):
        ''' gets a list of conditions for this input '''
        tracker = ConditionTracker()
        return tracker.getInputItemConditions(self, self.profile_mode) # gremlin.shared_state.current_mode)



    def get_valid_container_list(self):
        """Returns a list of valid containers for this input  """
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
        ''' updates input name and registers an axis input if needed '''
        from gremlin.keyboard import key_from_code

        input_id = self._input_id
        if input_id is not None  and self._device_guid is not None:
            if isinstance(input_id, int):
                if self._input_type == InputType.JoystickAxis:
                    self.is_axis = True # indicate we are an axis
                    self._is_button = False

                    # update the registration in case the input type changed
                    sdata = gremlin.event_handler.AxisState()
                    sdata.registerAxisInputItem(self)

                    info = gremlin.joystick_handling.device_info_from_guid(self._device_guid)
                    if info:
                        self._input_name =  info.get_axis_name(input_id)
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
                    self._input_name =  key_from_code(input_id.scan_code, input_id.is_extended).name
                elif isinstance(input_id, gremlin.ui.keyboard_device.KeyboardInputItem):
                    self._input_name = input_id.display_name
                else:
                    try:
                        self._input_name =  key_from_code(input_id[0],input_id[1]).name
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


    def from_xml(self, node, data, extra_data = None, skip_root = False):
        """Parses an InputItem node.

        :param node XML node to parse
        """

        #assert data is not None, "InputItem must be provided"
        import gremlin.ui.octavi_device

        container_node = node # node that holds the container information
        container_plugins = ContainerPlugins()
        container_tag_map = container_plugins.tag_map
        if extra_data and "input_type" in extra_data:
            self.input_type = extra_data["input_type"]
        else:
            try:
                self.input_type = InputType.to_enum(node.tag)
            except:
                syslog.error(f"XML: unknown input type: [{node.tag}]")



        if not skip_root: # skip header processing if set

            self._description = html.unescape(safe_read(node, "description", str, ""))
            self.always_execute = read_bool(node, "always-execute", False)

            if "locked" in node.attrib:
                self._locked = safe_read(node,"locked", bool, False)
            else:
                self._locked = False

            if self.input_type == InputType.ModeControl:
                # mode control entries - input id is the only item we need
                self.is_axis = False
                self.input_id = gremlin.ui.mode_device.ModeInputModeType(safe_read(node,"id",int,0))
                self.setOverrideInputType(InputType.JoystickButton)
                self.descriptionReadOnly = True


            elif self.input_type == InputType.JoystickAxis:
                # check for curve data
                for child in node:
                    if gremlin.base_profile._is_curve_tag(child.tag):
                        self.curve_data = gremlin.curve_handler.AxisCurveData()
                        self.curve_data._parse_xml(child)
                        self.input_id = safe_read(node,"input_id",int, 0)
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
            elif self.input_type == InputType.OctaviIfr1:
                if "id" in node.attrib:
                    button = safe_read(node,"id",int,0)
                    self.input_id = gremlin.ui.octavi_device.OctaviButton(button)


        assert self.input_id is not None,"input id not found"


        # read containers for this input item
        container_nodes = node.xpath("./container")
        for child in container_nodes:
            if child.tag in ("latched", "input", "keylatched") or gremlin.base_profile._is_curve_tag(child.tag):
                # ignore extra data
                continue
            if not "type" in child.attrib:
                # could be a blank container
                action_set_nodes = child.xpath("./action-set")
                if action_set_nodes:
                    # this is an error
                    syslog.error(f"XML {child.tag} is missing container 'type' attribute.  Offending line [{child.sourceline}]")
                continue
            container_type = child.get("type")

            if container_type not in container_tag_map:
                syslog.warning(
                    f"Unknown container type used: {container_type}"
                )
                continue
            entry = container_tag_map[container_type](self)
            mode_object = gremlin.base_profile.get_mode_object(node, extra_data)
            if mode_object:
                if extra_data is None:
                    extra_data = {}
                extra_data["mode_object"] = mode_object


            entry.from_xml(child, data, extra_data)
            # verify the entry has data
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

        if self._input_item_generating_xml:
            syslog.error("INPUT ITEM XML: recursion detected")
        try:
            self._input_item_generating_xml = True

            if parent_node is None:
                node = etree.Element(InputType.to_string(self.input_type))

                container_node = node # default container node to the input node
                # if self.input_type in (InputType.Keyboard, InputType.KeyboardLatched):
                #     if isinstance(self.input_id, Key):
                #         # keyboard key item
                #         key : Key
                #         key = self.input_id
                #         node.set("id", safe_format(key.scan_code, int))
                #         node.set("extended", safe_format(key.is_extended, bool))
                #         for latched_key in key.latched_keys:
                #             # latched keys
                #             child = etree.Element("latched")
                #             child.set("id", safe_format(latched_key.scan_code, int))
                #             child.set("extended", safe_format(latched_key.is_extended, bool))
                #             node.append(child)
                #     elif hasattr(self.input_id,"to_xml"):
                #         child = self.input_id.to_xml()
                #         node.append(child)
                #     else:
                #         node.set("id", safe_format(self.input_id[0], int))
                #         node.set("extended", safe_format(self.input_id[1], bool))
                # elif self.input_type in (InputType.Midi, InputType.OpenSoundControl):
                #     # write midi or OSC nodes
                #     child = self.input_id.to_xml()
                #     if child is not None:
                #         node.append(child)
                # else:
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
                # gremlinex change: containers can still be saved if they are invalid if they are still being configured:
                # valid = entry.is_valid_for_save()
                # if valid:
                child = entry.to_xml()
                if child is None:
                    child = entry.to_xml()
                    # pass
                if child is not None:
                    container_node.append(entry.to_xml())

                # else:
                #     if gremlin.config.Configuration().verbose:
                #         syslog.info(f"SaveProfile: input: {self.input_type} {InputType.to_display_name(self.input_type)} input id: {self.input_id} container has no data - won't save {entry.name}")

            return node
        finally:
            self._input_item_generating_xml = False




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
            device = gremlin.joystick_handling.getDevice(self.device_guid)
            return f"{device.get_axis_name(self._input_id)}"
        elif self._input_type == InputType.JoystickButton:
            return f"Button {self._input_id}"
        elif self._input_type == InputType.JoystickHat:
            return f"Hat {self._input_id}"
        elif self._input_type in (InputType.Keyboard, InputType.KeyboardLatched):
            return f"Key {self._input_id.display_name}"
        elif self._input_type == InputType.OpenSoundControl:
            return f"OSC {self._input_id.display_name}"
        elif self._input_type == InputType.Midi:
            return f"Midi {self._input_id.display_name}"
        elif self._input_type == InputType.ModeControl:
            return f"{gremlin.ui.mode_device.ModeInputModeType.to_display_name(self._input_id)}"
        elif self._input_type == InputType.State:
            return f"State: {self._input_id}"
        elif self._input_type == InputType.OctaviIfr1:
            return f"IFR1: {self._input_id.name}"
        return f"Unknown input: {self._input_type}"

    def save_container_to_template(self, fname : str):
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
                tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")
            except Exception as err:
                syslog.error(f"Error writing template to: [{fname}]")
                syslog.error(f"{err}\n{traceback.format_exc()}")
                return False
            return True

        return False





    def load_container_from_template(self, fname, extra_data = None):
        ''' loads new containers from a template - returns a list of containers '''
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
                                new_container.generateGuids() # replace IDs to avoid conflicts
                                container_list.append(new_container)
                        else:
                            msg = f"Container {container_type.name} is not valid for the current input"
                            msg_list.append(msg)
                            syslog.warning(msg)


                if msg_list:
                    prompt = "".join((msg + "\n" for msg in msg_list))
                    gremlin.ui.ui_common.MessageBox(title="Load Template", prompt = prompt)

            except Exception as err:
                syslog.error(f"Error loading template: [{fname}]:")
                syslog.error(f"{err}\n{traceback.format_exc()}")

            if container_list:
                for new_container in container_list:
                    if hasattr(new_container, "action_model"):
                        #new_container.action_model = self.action_model

                        plugin_manager.set_container_data(self, new_container)
                        #new_container.action_model.add_container(new_container)

            self.containers.extend(container_list)

            return container_list

    def generateGuids(self):
        ''' generate a set of new GUIDs for mapped items '''
        for container in self.containers:
            container.generateGuids()

    @property
    def debug_display(self):
        ''' debug string for this item'''
        mode = self.profile_mode
        if mode == gremlin.shared_state.master_mode:
            mode = gremlin.shared_state.master_mode_name
        return f"InputItem: [{gremlin.shared_state.get_device_name(self.device_guid)}] Input: [{InputType.to_display_name(self.input_type)}] Type: [{self.display_name}] mode: [{mode}]"

    def __eq__(self, other):
        ''' true if the input item are the same object '''
        if other is None:
            return False
        if not isinstance(other, InputItem):
            return False
        return self.id == other.id


    def __hash__(self):
        return super().__hash__()



class InputItemWidget(QBoxFrame):
    """ holds the input widget (left side of the interface) for available inputs that get mapped.

    this widget is used to represent an input mapping.  There are multiple variants of this for joysticks, vjoy (as input), keyboard, OSC and MIDI.

    Some of those use custom widget rendering based on their types.

    This event can be used to display input item specific customization
    widgets. This button also shows icons of the associated actions.
    """

    # Signal emitted whenever this button is pressed
    selected_changed = Signal(InputIdentifier)

    # fires when unselected
    unselected = Signal(InputIdentifier)

    # signal when button's close button is pressed
    closed =  Signal(InputIdentifier)

    # signal when button's edit button is pressed
    edit =  Signal(InputIdentifier)

    # signal when the edit curve button is pressed
    edit_curve = Signal(InputIdentifier)

    # signal when the clear curve button is pressed
    delete_curve = Signal(InputIdentifier)

    # signal input value changed
    input_value_changed = Signal(InputIdentifier, float)

    def __init__(self,
                  identifier : InputIdentifier,
                  parent=None,
                  populate_ui_callback : Callable = None,
                  populate_name_callback : Callable = None,
                  selection_changed_callback : Callable = None,
                  update_callback : Callable = None,
                  confirm_delete_callback: Callable = None,
                  config_external = False,
                  data = None):
        ''' builds the widget '''

        super().__init__(parent)


        self.parent = parent
        self.widget_width = None # actual width in pixels
        self.widget_height = None # actual height in pixels

        self._ui_loaded = False
        self.data = data
        self._selected = False
        self._confirm_delete_callback = confirm_delete_callback
        self.setContentsMargins(0,0,0,0)

        self._debug_layout = False

        self.identifier = identifier
        self._input_id = identifier.input_id
        self._device_guid = identifier.device_guid
        self._input_type = identifier.input_type

        if hasattr(self._input_id, "input_mode_changed"):
            # hook identifiers that can change mode from axis to button or vice versa so the repeaters match - example OSC or MIDI
            self._input_id.input_mode_changed.connect(self._update_repeater)

        self._multi_row = populate_ui_callback is not None
        self.populate_ui = populate_ui_callback # get custom content callback
        self.populate_name = populate_name_callback # get name callback

        self._config_external = config_external # true if the widget is a custom widget configured externally
        self._update_callback = update_callback # callback to use when a specific widget index must be updated

        self._selection_change_callbacks = [selection_changed_callback] if selection_changed_callback is not None else [] # list of callbacks for input selection


        self._data = data # InputItem
        self._title_icons = [] # title bar icons

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.main_layout.setSpacing(0)
        self.setObjectName("main_layout")


        # main container
        self._container_widget, self._container_layout = gremlin.ui.ui_common.getVContainer()
        self._container_widget.setContentsMargins(4,0,4,0)
        self._container_layout.setSpacing(0)
        self.main_layout.addWidget(self._container_widget)

        # lock icon
        icon_lock = gremlin.ui.ui_common.Icons.lockIcon()
        icon_unlock = gremlin.ui.ui_common.Icons.unlockIcon()
        self._lock_widget = gremlin.ui.ui_common.QIconCheckbox(icon_lock, icon_unlock, size = 16)




        if isinstance(data, InputItem):
            input_item = data
        else:
            input_item = identifier.getInputItem()
        if input_item:
            input_item.lockedChanged.connect(self._handle_input_item_lock_changed)
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
        self._title_bar_widget.setContentsMargins(4,2,4,2) # title bar
        self._title_bar_layout.addWidget(self._title_container_widget)
        self._title_bar_widget.setObjectName("title_bar")



        # title bar left side

        self._title_text_widget = gremlin.ui.ui_common.QIconLabel()
        self._title_text_widget.setContentsMargins(0,0,0,0)
        self._title_text_widget.setText("Input not configured")
        self._title_text_widget.setObjectName("title")


        self._title_text_container_widget = gremlin.ui.ui_common.getHContainer([
                                                                            self._lock_widget,
                                                                            self._title_text_widget
                                                                        ], widget_only = True)


        # title bar right side - holds the icons
        self._title_icon_widget, self._title_icon_layout = gremlin.ui.ui_common.getHContainer()


        self._title_container_layout.addWidget(self._title_text_container_widget, 0, 0)
        self._title_container_layout.addWidget(QtWidgets.QWidget(), 0, 1)
        self._title_container_layout.addWidget(self._title_icon_widget, 0, 2, alignment = QtCore.Qt.AlignmentFlag.AlignRight)
        self._title_container_layout.setColumnStretch(1,1)


        self._container_layout.addWidget(self._title_bar_widget)


        # icon setup
        size = self._getIconSize() # icon size
        active_color = gremlin.ui.ui_common.Color.activeColor()
        normal_color = gremlin.ui.ui_common.Color.normalColor()
        self._curve_icon_inactive = load_icon("mdi.chart-bell-curve",qta_color=normal_color)
        self._curve_icon_active = load_icon("mdi.chart-bell-curve",qta_color=active_color)
        self._input_icon_inactive = load_icon("fa6s.power-off",qta_color=normal_color)
        self._input_icon_active = load_icon("fa6s.power-off",qta_color=active_color)
        self._calibration_icon_active = load_icon("mdi.arrow-expand-horizontal",qta_color=active_color)
        self._calibration_icon_inactive = load_icon("mdi.arrow-expand-horizontal",qta_color=normal_color)


        # action buttons
        self._edit_button_widget = None

        # input button on/off - added only via enable_edit()
        self._input_button_widget = None

        # close widget - added only via enable_close()
        self._close_button_widget = None

        # curve toolbar
        self.is_axis = self.data.is_axis if self.data else False

        # calibration button
        self._calibration_button_widget = None

        # input curve button
        self._curve_button_widget = None

        # clear input curve button
        self.clear_curve_widget = None

        if self.is_axis:

            # curve container (axis only)
            self._curve_container_widget, self._curve_container_layout = gremlin.ui.ui_common.getHContainer()
            self._title_icon_layout.addWidget(self._curve_container_widget)

            self._curve_container_layout.addStretch()

            self._curve_button_widget = QtWidgets.QPushButton()
            self._curve_button_widget.setIcon(self._curve_icon_active)
            self._curve_button_widget.setToolTip("Input Curve")
            self._curve_button_widget.setFixedSize(size,size)
            self._curve_button_widget.clicked.connect(self._curve_button_cb)
            self._curve_container_layout.addWidget(self._curve_button_widget)

            self._calibration_button_widget = QtWidgets.QPushButton()
            self._calibration_button_widget.setIcon(self._calibration_icon_active)
            self._calibration_button_widget.setToolTip("Device calibration options")
            self._calibration_button_widget.setFixedSize(size,size)
            self._calibration_button_widget.clicked.connect(self._calibration_button_cb)
            self._curve_container_layout.addWidget(self._calibration_button_widget)

            self.clear_curve_widget = QtWidgets.QPushButton()
            self.clear_curve_widget.setToolTip("Clear Curve")
            self.clear_curve_widget.setIcon(load_icon("mdi.delete"))
            self.clear_curve_widget.setFixedSize(size,size)
            self.clear_curve_widget.clicked.connect(self._clear_curve_cb)
            self._curve_container_layout.addWidget(self.clear_curve_widget)


        # axis repeater object
        self.axis_widget = None

        # button repeater object
        self.button_widget = None

        hide_widgets = []


        # description row
        self._description_widget = gremlin.ui.ui_common.QIconLabel()
        self._description_widget.setStyleSheet("font-style: italic;")
        self._description_widget.setToolTip("Mapping Description")
        self._description_container_widget, self._description_container_layout = gremlin.ui.ui_common.getHContainer(self._description_widget)
        self._description_icon = None
        hide_widgets.append(self._description_container_widget)

        if self._debug_layout: self._description_container_widget.setStyleSheet("background: blue;")
        self._container_layout.addWidget(self._description_container_widget)


        # container icons
        self._action_container_widget, self._action_container_layout = gremlin.ui.ui_common.getVContainer()
        self._action_container_widget.setObjectName("action_container")
        if self._debug_layout: self._action_container_widget.setStyleSheet("#action_container { background: yellow; }")
        self._action_icons_container_widget, self._action_icons_container_layout = gremlin.ui.ui_common.getGridContainer()
        self._action_container_layout.addWidget(self._action_icons_container_widget)
        hide_widgets.append(self._action_container_widget)


        self._container_layout.addWidget(self._action_container_widget)

        # input description row
        self._input_description_widget = gremlin.ui.ui_common.QIconLabel()
        self._input_description_container_widget, self._input_description_container_layout = gremlin.ui.ui_common.getHContainer(self._input_description_widget)
        self._input_description_icon = None
        hide_widgets.append(self._input_description_container_widget)

        if self._debug_layout: self._description_container_widget.setStyleSheet("background: brown;")
        self._container_layout.addWidget(self._input_description_container_widget)

        # custom widget row (used by some inputs to display custom UI elements like keyboard )
        self._custom_container_widget, self._custom_container_layout = gremlin.ui.ui_common.getVContainer()
        self._custom_container_layout.setContentsMargins(4,0,0,0)
        hide_widgets.append(self._custom_container_widget)

        if self._debug_layout: self._custom_container_widget.setStyleSheet("background: cyan; ")
        self._container_layout.addWidget(self._custom_container_widget)


        # repeater
        self._repeater_container_widget, self._repeater_container_layout = gremlin.ui.ui_common.getVContainer()
        self._repeater_container_widget.setContentsMargins(0,0,0,2)

        if self._debug_layout: self._repeater_container_widget.setStyleSheet("background: red;")
        self._container_layout.addWidget(self._repeater_container_widget)


        # comment row
        self._comment_container_widget, self._comment_container_layout = gremlin.ui.ui_common.getHContainer()
        hide_widgets.append(self._comment_container_widget)

        if self._debug_layout: self._comment_container_widget.setStyleSheet("background: orange;")
        self._container_layout.addWidget(self._comment_container_widget)

        # custom content row
        self._custom_container_widget, self._custom_container_layout = gremlin.ui.ui_common.getVContainer()
        self._custom_container_widget.setContentsMargins(0,0,0,4) # give room below
        hide_widgets.append(self._custom_container_widget)


        if self._debug_layout:self._custom_container_widget.setStyleSheet("background: cyan;")
        self._container_layout.addWidget(self._custom_container_widget)

        # status row
        self._status_container_widget, self._status_container_layout = gremlin.ui.ui_common.getVContainer()
        hide_widgets.append(self._status_container_widget)
        if self._debug_layout:self._status_container_widget.setStyleSheet("background: gray;")


        self._status_widget = None
        self._container_layout.addWidget(self._status_container_widget)

        # container ID row
        self._container_id_widget, self._container_id_layout = gremlin.ui.ui_common.getVContainer()
        if self._debug_layout:self._container_id_widget.setStyleSheet("background: magenta;")
        hide_widgets.append(self._container_id_widget)


        self._container_layout.addWidget(self._container_id_widget)
        spacer = QtWidgets.QWidget()
        spacer.setFixedHeight(4)
        self._container_layout.addWidget(spacer)

        #self._container_layout.addStretch(2)


        self._ui_loaded = True

        self._setWidgetHeight(hide_widgets, 0)

        # event filter
        self.installEventFilter(self)

        # hook mapping changed event
        el = gremlin.event_handler.EventListener()
        # el.mapping_changed.connect(self._mapping_changed_cb)
        el.curve_deleted.connect(self._curve_changed_cb)
        el.curve_added.connect(self._curve_changed_cb)
        el.calibration_added.connect(self._calibration_changed_cb)
        el.calibration_deleted.connect(self._calibration_changed_cb)
        el.icon_changed.connect(self._icon_changed_cb)
        el.update_input_icons.connect(self._update_axis_icons)
        el.profile_loaded.connect(self._update_axis_icons) # update icons after profile load as calibration data load order is not guaranteed

        # update the defaults
        input_item = identifier.input_item
        input_name = identifier.input_name or input_item.input_name
        self.setTitle(input_name)
        self.setDescription(input_item.description)

        # update mapping action icons
        self._update_repeater() # create the correct repeater widget
        self._update_selected_ui()
        self._update_display_ui()

        if self.is_axis:
            # update axis input icons
            self._update_axis_icons_ui()

        self.ensureStyle()

    def addSelectionChangeCallback(self, callback : Callable):
        ''' adds a callback to be called when selection flag changes passes the (widget)
        :param callback: the callback to add
        '''
        if __debug__ and callback is not None and not callable(callback):
            raise TypeError("Callback must be callable")
        if not callback in self._selection_change_callbacks:
            self._selection_change_callbacks.append(callback)  

    def removeSelectioChangeCallback(self, callback : Callable):
        ''' removes a callback from the list of callbacks to be called when the model changes - this is used by the container
        :param callback: the callback to remove
        '''
        if callback in self._selection_change_callbacks:
            self._selection_change_callbacks.remove(callback)        

    def _fireSelectionChangeCallbacks(self):
        ''' fires the selection change callbacks  callback(InputItemWidget) - the parameter is the widget that has changed state'''
        for callback in self._selection_change_callbacks:
            callback(self)



    def resizeEvent(self, event):
        size = self.size()
        self.widget_width = size.width()
        self.widget_height = size.height()
        return super().resizeEvent(event)

    @property
    def input_item(self):
        return self._input_item

    def eventFilter(self, widget, event):
        # trap mouse click
        if not self._selected:
            t = event.type()
            if t == QtCore.QEvent.Type.MouseButtonPress:
                button = event.buttons()
                if button == QtCore.Qt.LeftButton:
                    self.selected = True

        return super().eventFilter(widget, event)

    def getLayout(self):
        return self._custom_container_layout

    def addWidget(self, widget):
        ''' adds a widget to the container '''
        self._custom_container_layout.addWidget(widget)
        h = sum(w.height() for w in gremlin.util.get_layout_widgets(self._custom_container_layout))
        self._custom_container_widget.setMaximumHeight(h + 5)

    def clearWidgets(self):
        ''' clears the custom container layout and hides it '''
        gremlin.util.clear_layout(self._custom_container_layout)
        self._custom_container_widget.setMaximumHeight(0)


    def _handle_input_item_lock_changed(self, input_item):
        if input_item == self._input_item:
            gremlin.util.InvokeUiMethod(self._handle_input_item_lock_changed_ui, input_item)

    def _handle_input_item_lock_changed_ui(self, input_item):

        if Shiboken.isValid(self._lock_widget):
            with QtCore.QSignalBlocker(self._lock_widget):
                self._lock_widget.setChecked(input_item.locked)

        # enable the delete button if not locked
        if self._close_button_widget and Shiboken.isValid(self._close_button_widget):
            self._close_button_widget.setEnabled(not input_item.locked)

    @QtCore.Slot(bool)
    def _handle_lock_changed(self, checked : bool):
        self.data.locked = checked
        if self.data.locked != checked:
            # input cannot be locked/unlocked - undo the check
            with QtCore.QSignalBlocker(self._lock_widget):
                self._lock_widget.setChecked(not checked)





    def _update_title(self):
        ''' updates the title bar stylesheet based on the selection state '''
        css = gremlin.ui.ui_common.Color.cssInputHeader() if self._selected else gremlin.ui.ui_common.Color.cssUnselectedInputHeader()
        self._title_container_widget.setStyleSheet(css)

    def _update_container_id(self):
        gremlin.util.InvokeUiMethod(self._update_container_id_ui) # on UI thread

    def _update_container_id_ui(self):
        ''' updates container ID display for associated containers with this input '''
        if not Shiboken.isValid(self._container_id_widget):
            return
        config = gremlin.config.Configuration()
        gremlin.util.clear_layout(self._container_id_layout)
        if config.show_container_id:
            width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
            grids = []
            rh = self._getRowHeight()


            if self.data:
                # input id
                line_edit = gremlin.ui.ui_common.QDataLineEdit()
                line_edit.setMinimumWidth(width)
                line_edit.setText(gremlin.util.idString(self.data.id))
                line_edit.setReadOnly(True)
                widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Input ID:", widget_only = True)
                self._container_id_layout.addWidget(widget)
                grids.append(widget)

                container_count = len(self.data.containers)
                if container_count:
                    for index, container in enumerate(self.data.containers):
                        line_edit = gremlin.ui.ui_common.QDataLineEdit()
                        line_edit.setMinimumWidth(width)
                        line_edit.setText(container.id)
                        line_edit.setReadOnly(True)
                        widget = gremlin.ui.ui_common.getGridContainer(line_edit, f"[{index}] {container.name}", widget_only = True)
                        self._container_id_layout.addWidget(widget)
                        grids.append(widget)
                else:
                    # no container
                    line_edit = gremlin.ui.ui_common.QDataLineEdit()
                    line_edit.setMinimumWidth(width)
                    line_edit.setText("No container found")
                    line_edit.setReadOnly(True)
                    widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Mapping:", widget_only = True)
                    self._container_id_layout.addWidget(widget)
                    grids.append(widget)


            h = rh * (len(grids) + 1)
            self._setWidgetHeight(self._container_id_widget, h)
            gremlin.ui.ui_common.synchronize_grids(grids)

            # selected state
            self._container_id_layout.addWidget(QtWidgets.QLabel(f"Selected: {self.selected}"))
        else:
            self._setWidgetHeight(self._container_id_widget, 0)


    def _cleanup_ui(self):
        ''' called when widget is removed '''
        el = gremlin.event_handler.EventListener()
        el.action_created.disconnect(self._action_changed_cb)
        el.action_delete.disconnect(self._action_deleted_cb)
        el.icon_changed.disconnect(self._icon_changed_cb)
        el.mapping_changed.disconnect(self._mapping_changed_cb)
        el.update_input_icons.disconnect(self._update_axis_icons)
        el.input_enabled_changed.disconnect(self._update_enabled_state)
        el.profile_loaded.disconnect(self._update_axis_icons)
        gremlin.util.clear_layout(self.main_layout)
        self._deleted = True

    @property
    def deleted(self):
        # true if the cleanup function was found and the widget should be deleted
        return self._deleted


    @property
    def content_layout(self):
        ''' gets the the content row '''
        return self._custom_container_layout

    def _getIconSize(self) -> int:
        return 16

    def _getRowHeight(self) -> int:
        return 28

    def _setWidgetHeight(self, widget : QtWidgets.QWidget | list [QtWidgets.QWidget] , h):
        ''' sets fixed min/max height'''
        if not hasattr(widget,"__iter__"):
            w_list = [widget]
        else:
            w_list = widget
        for widget in w_list:
            if widget == self._description_container_widget and h != 0:
                pass
            if Shiboken.isValid(widget):
                widget.setFixedHeight(h)


    def unhook(self):
        hook_id = gremlin.util.normalize_guid(self.data.id)
        if self.axis_widget:
            verbose = gremlin.config.Configuration().verbose_mode_perf
            if verbose:
                description = f"input repeater:  hook id: [{hook_id}] [{str(self.input_item.id)}] device [{gremlin.joystick_handling.getDeviceName(self.identifier.device_guid)}] axis id: [{self.identifier.input_id}] "
                syslog.info(f"Unregister repeater: {description}")
            self.axis_widget.unhookDevice()
            self.axis_widget.setParent(None)
            self.axis_widget.deleteLater()
            self.axis_widget = None
        if self.button_widget:
            self.button_widget.setParent(None)
            self.button_widget.deleteLater()
            self.button_widget = None




    def _update_repeater(self):
        ''' updates the repeaters based on the type of widget '''

        if self._input_type in (InputType.Keyboard, InputType.KeyboardLatched, InputType.ModeControl, InputType.State):
            gremlin.util.clear_layout(self._repeater_container_layout)
            self._setWidgetHeight(self._repeater_container_widget, 0) # turn off repeater for non axis widgets
            self.axis_widget = None
            self.button_widget = None
            return

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_perf

        widget = None # widget created for the repeater

        # if self.identifier.input_type in (InputType.Keyboard, InputType.KeyboardLatched):
        #     pass
        input_type = self.identifier.input_type

        if config.show_input_axis:

            self.axis_widget = None
            self.button_widget = None
            gremlin.util.clear_layout(self._repeater_container_layout)

            if (self.identifier.is_axis or self.identifier.is_button or self.identifier.is_hat) or \
                input_type in (InputType.JoystickAxis, InputType.JoystickButton,  InputType.JoystickHat, InputType.OpenSoundControl, InputType.Midi):

                if self.identifier.is_valid:
                    hook_id = gremlin.util.normalize_guid(self.data.id)
                    if self.identifier.is_axis:
                        # axis
                        device_guid = self.identifier.device_guid
                        input_id = self.identifier.input_id
                        astate = gremlin.event_handler.AxisState()
                        values = astate.getAxisValues(device_guid, input_id)
                        widget = gremlin.ui.ui_common.QHookedProgressBar(orientation=QtCore.Qt.Orientation.Horizontal, value = values)

                        widget.unhooked.connect(self._axis_widget_unhooked)
                        widget.sizeChanged.connect(self._repeater_size_changed)
                        widget.data = self
                        self.axis_widget = widget
                        self._repeater_container_layout.addWidget(widget)
                        self._repeater_container_layout.addStretch()

                        widget.setMaximumWidth(200)
                        if self._debug_layout:
                            widget.setStyleSheet("background: purple;")

                        description = f"input repeater:  hook id: [{hook_id}] [{str(self.input_item.id)}] device [{gremlin.joystick_handling.getDeviceName(self.identifier.device_guid)}] axis id: [{self.identifier.input_id}] "
                        if verbose: syslog.info(f"register repeater: {description}")
                        widget.hookDevice(hook_id, self.identifier.device_guid, self.identifier.input_type, self.identifier.input_id, ui_only = True, description = description)
                        height = widget.sizeHint().height() + 4
                        self._setWidgetHeight(self._repeater_container_widget, height)

                        self.axis_widget.triggerUpdate() # force an update
                    else:
                        # button
                        widget = gremlin.ui.ui_common.ButtonStateWidget()
                        widget.unhooked.connect(self._button_widget_unhooked)
                        widget.hookDevice(hook_id, self.identifier.device_guid, self.identifier.input_type, self.identifier.input_id)
                        #widget.hookDevice(self._device_guid, input_type, self._input_id )
                        self.button_widget = widget
                        self._repeater_container_layout.addWidget(widget)
                        widget.updateState()

                        self._repeater_container_layout.addStretch()
                        if self._debug_layout:
                            widget.setStyleSheet("background: purple;")
                        height = widget.sizeHint().height() + 4
                        self._setWidgetHeight(self._repeater_container_widget, height)




    def _button_widget_unhooked(self):
        self.button_widget = None # force a new button widget
        gremlin.util.clear_layout(self._repeater_container_layout)

    def _axis_widget_unhooked(self):
        self.axis_widget = None
        gremlin.util.clear_layout(self._repeater_container_layout)



    def _repeater_size_changed(self):
        widget = self.sender()
        height = widget.sizeHint().height() + 4
        self._setWidgetHeight(self._repeater_container_widget, height)


    def _message_key_changed(self, old_message_key, new_message_key):
        state_tracker = gremlin.ui.ui_common.StateTracker()

        print (f"INPUT ITEM: message change {old_message_key} to {new_message_key}")

        if old_message_key:
            state_tracker.unregisterAxisState(self._device_guid, self._input_type, old_message_key)
            state_tracker.unregisterButtonState(self._device_guid, self._input_type,old_message_key)

        if self.axis_widget:
            state_tracker.registerAxisState(self.axis_widget, self._device_guid, self._input_type, new_message_key)
        if self.button_widget:
            state_tracker.registerButtonState(self.button_widget, self._device_guid, self._input_type, new_message_key)

    @QtCore.Slot(object)
    def _update_enabled_state(self, input_item ): # : InputItem
        ''' updates the enabled state '''
        if self.data == input_item:
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
        ''' update titlebar icons - UI thread'''
        is_curve = self.data.is_curve
        if Shiboken.isValid(self._curve_button_widget):
            if is_curve:
                self._curve_button_widget.setIcon(self._curve_icon_active)
            else:
                self._curve_button_widget.setIcon(self._curve_icon_inactive)

        if Shiboken.isValid(self.clear_curve_widget):
           self.clear_curve_widget.setEnabled(is_curve)

        if Shiboken.isValid(self._calibration_button_widget):
            has_calibration = self.data.hasCalibration
            if has_calibration:
                self._calibration_button_widget.setIcon(self._calibration_icon_active)
            else:
                self._calibration_button_widget.setIcon(self._calibration_icon_inactive)


    def _update_action_icons(self):
        ''' updates the input item's action icon list '''
        gremlin.util.InvokeUiMethod(self._update_action_icons_ui)

    def _update_action_icons_ui(self):
        # update mapping icons
        self.create_action_icons(self.data)


    def _icon_changed_cb(self, event : gremlin.event_handler.DeviceChangeEvent):
        gremlin.util.InvokeUiMethod(self._icon_changed_cb_ui, event)

    def _icon_changed_cb_ui(self, event : gremlin.event_handler.DeviceChangeEvent):
        ''' updates the input item icons based on the actions it contains - UI thread '''
        if isinstance(event.source, gremlin.base_profile.AbstractAction):
            action = event.source
            if self.findAction(action):
                # update the action
                self.create_action_icons(self.data)
        elif isinstance(event.source, InputItem):
            if self.data and self.data == event.source:
                self.create_action_icons(self.data)


    @QtCore.Slot(object)
    def _action_changed_cb(self, event):
        ''' occurs when an action is added or changed '''
        if isinstance(event,gremlin.base_profile.AbstractAction):
            action = event
        elif isinstance(event,gremlin.event_handler.DeviceChangeEvent):
            action = event.source
        else:
            return
        if isinstance(action, gremlin.base_profile.AbstractAction):
            if self.findAction(action):
                # update the action
                self.create_action_icons(self.data)

    @QtCore.Slot(object, object, object)
    def _action_deleted_cb(self, item_dat, container, action):
        ''' occurs when an action is deleted '''
        if self.findAction(action) and Shiboken.isValid(self):
            # find the widget corresponding to this action
            gremlin.util.InvokeUiMethod(self.clear_action_icon, self.data, action) # ensure on UI thread

    def _curve_changed_cb(self, input_item):
        ''' fires when a curve is added or deleted '''
        if input_item == self._input_item and Shiboken.isValid(self):
            gremlin.util.InvokeUiMethod(self._update_repeater) # ensure on UI thread

    def _calibration_changed_cb(self, input_item):
        ''' fires when a calibration is added or deleted '''
        if input_item == self._input_item and Shiboken.isValid(self):
            gremlin.util.InvokeUiMethod(self._update_repeater) # ensure on UI thread

    def _mapping_changed_cb(self, item_data):
        ''' called when a mapping changes - sends the item being changed '''
        if item_data == self.data and Shiboken.isValid(self):
            gremlin.util.InvokeUiMethod(self._mapping_changed_cb_ui, item_data) # ensure on UI thread

    def _mapping_changed_cb_ui(self, item_data):
            ''' update the widget on mapping change '''
            if Shiboken.isValid(self):
                self._update_container_id_ui()
                self._update_action_icons_ui()



    def update_curve_icon(self, enabled : bool):
        ''' enables or disables curve buttons '''
        if self.is_axis:
            if enabled:
                self._curve_button_widget.setIcon(self._curve_icon_active)
            else:
                self._curve_button_widget.setIcon(self._curve_icon_inactive)
            self.clear_curve_widget.setEnabled(enabled)
            if self.identifier.input_type == InputType.JoystickAxis:
                if self.axis_widget is not None: # will be null if input axes not displayed
                    self.axis_widget.show_curved = enabled


    @QtCore.Slot(float)
    def _input_value_changed(self, value):
        ''' called when the input changes '''
        self.input_value_changed.emit(self, value)


    @property
    def data(self):
        ''' gets any data object associated with this widget '''
        return self._data
    @data.setter
    def data(self, value):
        self._data = value

    @property
    def index(self):
        ''' assigned index '''
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
        ''' sets the title of the input widget '''
        self._title_text_widget.setText(value)

    def setCustomContent(self, items : QtWidgets.QWidget | list [QtWidgets.QWidget]):
        ''' adds custom content to the input widget (vertical container)'''
        gremlin.util.clear_layout(self._custom_container_layout)
        if not items:
            self._setWidgetHeight(self._custom_container_widget, 0)
        if not hasattr(items, "__iter__"):
            widgets = [items]
        else:
            widgets = items
        rh = 0
        widget : QtWidgets.QWidget
        for widget in widgets:
            self._custom_container_layout.addWidget(widget)
            rh += widget.sizeHint().height()

        self._setWidgetHeight(self._custom_container_widget, rh + 4)


    def setInputDescription(self, description : str | None):
        ''' sets the input description for an input widget (optional) '''

        if description:
            rh = self._getRowHeight()
            self._input_description_widget.setText(description)
            self._input_description_widget.setIcon(self._input_description_icon)
            self._setWidgetHeight(self._input_description_container_widget, rh)
        else:
            self._input_description_widget.setText(None)
            self._input_description_widget.setIcon(None)
            self._setWidgetHeight(self._input_description_container_widget, 0)





    def setInputDescriptionIcon(self, icon_path, use_qta = True):
        ''' sets (or clears) the icon for the input description line '''
        if isinstance(icon_path, QtGui.QIcon):
            self._input_description_icon = icon_path
        else:
            self._input_description_icon = load_icon(icon_path, use_qta) if icon_path else None
        if Shiboken.isValid(self._input_description_widget):
            self._input_description_widget.setIcon(self._input_description_icon)

    def setStatus(self, status: str, icon = None):
        ''' sets the status'''
        if not self._ui_loaded: return
        gremlin.util.clear_layout(self._status_container_layout)
        if status:
            self._status_widget = gremlin.ui.ui_common.QIconLabel(icon, status)
            self._setWidgetHeight(self._status_container_widget, self._getRowHeight())
        else:
            self._setWidgetHeight(self._status_container_widget, 0)



    def setDescription(self, description : str | None):
        ''' sets the description of the input widget '''
        if description:
            rh = self._getRowHeight()
            self._description_widget.setText(description)
            self._description_widget.setIcon(self._input_description_icon)
            self._setWidgetHeight(self._description_container_widget, rh)
        else:
            self._description_widget.setText(None)
            self._description_widget.setIcon(None)
            self._setWidgetHeight(self._description_container_widget, 0)


    def setComment(self, value, icon = None):
        ''' sets the comment field of the input widget '''
        if value:
            gremlin.util.clear_layout(self._comment_container_layout)
            widget = gremlin.ui.ui_common.QIconLabel(icon_path = icon, text = f"<i>{value}</i>")
            self._comment_container_layout.addWidget(widget)
            self._setWidgetHeight(self._comment_container_widget, self._getRowHeight())
        else:
            self._setWidgetHeight(self._comment_container_widget, 0)
        self.updateHeight()

    def setToolTip(self, tooltip):
        ''' sets the tooltip for the widget '''
        super().setToolTip(tooltip)

    def setIcon(self, icon_path, use_qta = True):
        ''' sets the widget's icon '''
        self._title_text_widget.setIcon(icon_path, use_qta)


    # def addWidget(self, widget):
    #     ''' adds a widget to the contents '''
    #     self._container_layout.addWidget(widget,self._row_custom_content,0) # custom container

    def update_display(self):
        gremlin.util.InvokeUiMethod(self._update_display_ui)


    def _update_display_ui(self):
        ''' updates the display text for the button, custom content and input enabled '''


        if gremlin.shared_state.is_running:
            return # do not update UI at runtime


        if self._ui_loaded:
            config = gremlin.config.Configuration()
            power_visible = config.show_input_enable
            if power_visible:
                if not self._input_button_widget:

                    size = self._getIconSize()
                    self._input_button_widget = QtWidgets.QPushButton()
                    self._input_button_widget.setIcon(self._input_icon_active)
                    self._input_button_widget.setToolTip("Enables or disables this input.  If disabled, input from this specific input will be ignored.<br>The state can be changed by the control action as well.")
                    self._input_button_widget.setFixedSize(size,size)
                    self._input_button_widget.clicked.connect(self._input_button_cb)
                    self._title_icon_layout.addWidget(self._input_button_widget)
            else:
                if self._input_button_widget and Shiboken.isValid(self._input_button_widget):
                    self._title_icon_layout.removeWidget(self._input_button_widget)
                    self._input_button_widget = None

            # description field
            self.setDescription(self.data.description)


            if not self._config_external or self.populate_name is not None:
                #display_text = self.populate_name(self, self.identifier) if self.populate_name else gremlin.common.input_to_ui_string( self.identifier.input_type,self.identifier.input_id)
                display_text = self.populate_name(self, self.identifier) if self.populate_name is not None else self.identifier.input_name
                self._title_text_widget.setText(display_text)

            self._update_axis_icons()

            # update selection css
            self._update_selected_ui()

            # populate the custom content
            if self._update_callback:
                self._update_callback(self, self._custom_container_widget)

            # update repeater
            if not self.identifier.is_valid:
                self._setWidgetHeight(self._repeater_container_widget, 0)

            # update status
            if not self.identifier.is_status:
                self._setWidgetHeight(self._status_container_widget, 0)

            # update repeater for this widget
            self._update_repeater()

    @property
    def selected(self) -> bool:
        ''' True if the item is currently selected '''
        return self._selected

    @selected.setter
    def selected(self, value : bool):
        self.setSelected(value)

    def setSelected(self, value : bool, emit = True):
        ''' marks the item as selected '''
        push_cursor = False
        try:
            if value != self._selected:
                self._selected = value
                if emit:
                    push_cursor = True
                    gremlin.util.pushCursor()
                    if not value:
                        self.unselected.emit(self)
                    self.selected_changed.emit(self)

                    self._fireSelectionChangeCallbacks()


            # ensure the widget has the correct visual selection state
            self._update_selected() # uptate widget style

        finally:
            if push_cursor:
                gremlin.util.popCursor()





    def ensureStyle(self):
        ''' updates the visual selection '''
        self._update_selected()

    def _update_selected(self):
        ''' updates the widget style based on selection '''
        gremlin.util.InvokeUiMethod(self._update_selected_ui)

    def _update_selected_ui(self):
        ''' called whenever selection changes '''
        if self._selected:
            style = f'''
                    #main_layout {{
                        background: {gremlin.ui.ui_common.Color.selectColor()};
                        border: 2px solid {gremlin.ui.ui_common.Color.selectBorderColor()};
                    }}
                '''
            self.setStyleSheet(style)
            css = gremlin.ui.ui_common.Color.cssInputHeader()
        else:
            self._default_style()
            css = gremlin.ui.ui_common.Color.cssUnselectedInputHeader()

        # update style for title bar
        self._title_bar_widget.setStyleSheet(css)

        # update container
        self._update_container_id()


    def _default_style(self):
        ''' sets the default style'''
        style = f'''
                    #main_layout {{
                        background: {gremlin.ui.ui_common.Color.backgroundColor()};
                        border: 1px solid {gremlin.ui.ui_common.Color.borderColor()};
                        }}
                        '''
        self.setStyleSheet(style)

    def enable_close(self):
        ''' enables the close button on the input widget (keyboard only usually) '''
        if self._close_button_widget:
            # already visible
            return
        size = self._getIconSize()
        icon = gremlin.ui.ui_common.load_icon("mdi.delete")
        self._close_button_widget = QtWidgets.QPushButton()
        self._close_button_widget.setIcon(icon)
        self._close_button_widget.setFixedSize(size,size)
        self._close_button_widget.clicked.connect(self._close_button_cb)
        # insert in last position
        self._title_icon_layout.addWidget(self._close_button_widget)




    def disable_close(self):
        ''' enables the close button on the input widget (keyboard only usually) '''
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
        ''' enables the edit button on the input widget (keyboard only usually) '''

        # we avoid using setVisible() because of the QT event wiring
        if self._edit_button_widget:
            # already visible
            return
        size = self._getIconSize()
        icon = gremlin.ui.ui_common.Icons.gearIcon()
        self._edit_button_widget = QtWidgets.QPushButton()
        self._edit_button_widget.setIcon(icon)
        self._edit_button_widget.setToolTip("Configure")
        self._edit_button_widget.setFixedSize(size,size)
        self._edit_button_widget.clicked.connect(self._edit_button_cb)

        # insert next to last button
        index = len(gremlin.util.get_layout_widgets(self._title_icon_layout))
        if index > 0:
            index -= 1
        self._title_icon_layout.insertWidget(index, self._edit_button_widget)


    def disable_edit(self):
        ''' enables the edit button on the input widget (keyboard only usually) '''
        if self._edit_button_widget and Shiboken.isValid(self._edit_button_widget):
            # remove it
            self._title_icon_layout.removeWidget(self._edit_button_widget)
            self._edit_button_widget = None


    def create_action_icons(self, profile_data):
        """Creates the label of this instance.

        Renders the text representing the instance's name as well as
        icons of actions associated with it.

        :param profile_data the profile.InputItem object associated
            with this instance
        """

        if not Shiboken.isValid(self._action_icons_container_layout):
            return

        if profile_data is None or self.data.id != profile_data.id:
            return

        ui_common.clear_layout(self._action_icons_container_layout)
        self._action_icons_container_layout.addWidget(QtWidgets.QWidget(),0,0)
        self._action_icons_container_layout.setColumnStretch(0,1)
        rh = self._getRowHeight()

        if profile_data.containers:
            # Create the actual icons
            row = 0
            col = 1
            max_col = 5
            size = self._getIconSize()
            for container in profile_data.containers:
                action_sets = container.get_action_sets()
                if action_sets:
                    for actions in [a for a in action_sets if a is not None]:
                        for action in actions:
                            if action is not None:
                                widget = ui_common.ActionLabel(action)
                                widget.setMaximumWidth(size)
                                widget.setMaximumHeight(size)
                                self._action_icons_container_layout.addWidget(widget, row, col)
                                col +=1
                                if col > max_col:
                                    col = 1
                                    row +=1

                else:
                    for actions in [a for a in container.action_sets if a is not None]:
                        for action in actions:
                            if action is not None:
                                widget = ui_common.ActionLabel(action)
                                widget.setMaximumWidth(size)
                                widget.setMaximumHeight(size)
                                self._action_icons_container_layout.addWidget(widget, row, col)
                                col+=1
                                if col > max_col:
                                    col = 1
                                    row +=1

            self._setWidgetHeight(self._action_container_widget, rh * (row + 1))

        else:
            label = QtWidgets.QLabel("∅", alignment=QtCore.Qt.AlignmentFlag.AlignRight)
            font = label.font()
            font.setPixelSize(24)
            label.setFont(font)
            label.setToolTip("No mappings found")
            self._action_icons_container_layout.addWidget(label,0,1)
            self._setWidgetHeight(self._action_container_widget, rh)



    def clear_action_icon(self, profile_data, action_to_remove):
        ''' delete an action icon '''
        ui_common.clear_layout(self._action_icons_container_layout)
        self._action_icons_container_layout.addWidget(QtWidgets.QWidget(),0,0)
        self._action_icons_container_layout.setColumnStretch(0,1)
        row = 0
        col = 1
        max_col = 5
        rh = self._getRowHeight()
        if profile_data.containers:
            for container in profile_data.containers:
                action_sets = container.get_action_sets()
                if action_sets:
                    for actions in [a for a in action_sets if a is not None]:
                        for action in actions:
                            if action is not None and action != action_to_remove:
                                self._action_icons_container_layout.addWidget(ui_common.ActionLabel(action), row, col)
                                col += 1
                                if col > max_col:
                                    col = 1
                                    row +=1


                else:
                    for actions in [a for a in container.action_sets if a is not None]:
                        for action in actions:
                            if action is not None and action != action_to_remove:
                                self._action_icons_container_layout.addWidget(ui_common.ActionLabel(action), row, col)
                                col +=1
                                if col > max_col:
                                    col = 1
                                    row +=1

            self._setWidgetHeight(self._action_container_widget, rh * (row + 1))
        else:
            self._action_icons_container_layout.addWidget(QtWidgets.QLabel("∅", alignment=QtCore.Qt.AlignmentFlag.AlignRight),0,1)
            self._setWidgetHeight(self._action_container_widget, rh)





    def findAction(self, action):
        ''' true if the action is found in our containers '''
        if self.data and self.data.containers:
            for container in self.data.containers:
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
            self.selected_changed.emit(self)

    QtCore.Slot()
    def _close_button_cb(self):
        ''' fires the closed event when the close button has been pressed '''

        if self._confirm_delete_callback:
            if not self._confirm_delete_callback(self._input_item):
                # request failed
                return

        # prompt
        ui = gremlin.shared_state.ui
        result =gremlin.ui.ui_common.ConfirmBox(prompt = "Remove this input?", parent = ui)
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
        ''' edit button clicked '''
        self.edit.emit(self)

    QtCore.Slot()
    def _curve_button_cb(self):
        self.edit_curve.emit(self)

    QtCore.Slot()
    def _input_button_cb(self):
        # toggle input state
        self.data.enabled = not self.data.enabled

    @QtCore.Slot()
    def _calibration_button_cb(self):
        # open the calibration button for this input
        dialog = gremlin.ui.axis_calibration.CalibrationDialogEx(self.data)
        dialog.exec()
        self.data.calibration.copyFrom(dialog.action_data)
        self._update_axis_icons()


    QtCore.Slot()
    def _clear_curve_cb(self):
        self.delete_curve.emit(self)



class InputItemListModel(AbstractModel):

    """Model storing a device's input item list."""

    def __init__(self,
                 profile : gremlin.base_profile.Profile,
                 device_guid,
                 mode : str,
                 allowed_types : list = None,
                 custom_load_handler : Callable[[object], bool] = None,
                 custom_remove_handler : Callable[[object], None] = None,
                 custom_clear_handler : Callable = None,
                 custom_filter_handler : Callable[[object], bool] = None,
                 custom_delete_confirm_handler = None,
                 show_master_mode : bool = False,
                 show_filtered_only : bool = False,
                 ):
        """Creates a new instance.

        :param device_data the profile data managed by this model
        :param mode the mode this model manages
        :param custom_load_handler: handler for custom loading of the data
        :param show_master_mode: determines if master mode items are displayed in the model
        :param show_filtered_only: determines if only filtered items are shown in the model
        """
        import gremlin.base_profile
        super().__init__()

        if profile is None:
            raise ValueError("Profile cannot be None")
        assert isinstance(profile, gremlin.base_profile.Profile), "Invalid profile type"
        if device_guid is None:
            raise ValueError("Device guid cannot be None")
        if mode is None:
            raise ValueError("Mode cannot be None")
        

        self._device_guid = device_guid
        self._profile = profile
        self._device_data = profile.getDevice(device_guid)

       
        self._mode = mode
        self._show_master_mode = show_master_mode
        self._show_filtered_only = show_filtered_only
        self._is_filtered = False # true if the data should be filtered
        self._data_changed = False # flag to track if data membership has changed 
        self._data_changed_callbacks = [] # list of callbacks when data changes

        
        self._index_map = TriggerDict() # map of input_id to index
        self._index_map.addCallback(self._handle_model_changed)

        self._item_map = TriggerDict() # map of input_id to index
        self._item_map.addCallback(self._handle_model_changed)

        self._filtered_item_map = TriggerDict() # map of items to index after filters are applied
        self._filtered_item_map.addCallback(self._handle_model_changed)

        self._filtered_index_map = TriggerDict()
        self._filtered_index_map.addCallback(self._handle_model_changed)


        if allowed_types is not None:
            self._allowed_input_types  = gremlin.base_classes.TraceableList(allowed_types, self._filter_change_cb)
        else:
            # all types
            self._allowed_input_types = gremlin.base_classes.TraceableList(InputType.to_list(), self._filter_change_cb)

        if __debug__:
            if custom_clear_handler is not None and not callable(custom_clear_handler):
                raise ValueError("custom_clear_handler must be a callable")
            if custom_load_handler is not None and not callable(custom_load_handler):
                raise ValueError("custom_update_handler must be a callable")
            if custom_remove_handler is not None and not callable(custom_remove_handler):
                raise ValueError("custom_remove_handler must be a callable")
            if custom_filter_handler is not None and not callable(custom_filter_handler):
                raise ValueError("custom_filter_handler must be a callable")    
        
        self._custom_load_handler = custom_load_handler
        self._custom_clear_handler = custom_clear_handler
        self._custom_remove_handler = custom_remove_handler
        self._custom_filter_handler = custom_filter_handler # handles entries, return true to include, false to exclude
        self._custom_delete_confirm_handler = custom_delete_confirm_handler # return true if the input can be deleted

        self.refresh(False)

    @property
    def display_name(self) -> str:
        ''' display name for the model'''
        device = gremlin.joystick_handling.getDevice(self._device_guid)
        return f"Input Item Model for: [{device.name}] - filtered inputs: [{len(self._filtered_index_map)}] total inputs: [{len(self._index_map)}]"
      
    def addCallback(self, callback : Callable):
        ''' adds a callback to be called when the model data changes '''
        if __debug__ and callback is not None and not callable(callback):
            raise TypeError("Callback must be callable")
        if not callback in self._data_changed_callbacks:
            self._data_changed_callbacks.append(callback)

    def removeCallback(self, callback : Callable):
        ''' removes a callback from the list of callbacks to be called when the model data changes '''
        if callback in self._data_changed_callbacks:
            self._data_changed_callbacks.remove(callback)

    def setFiltered(self, value : bool):
        ''' sets whether the model is filtered or not, updates the model data '''
        if self._show_filtered_only != value:
            self._show_filtered_only = value
            self.refresh()


    def setAllowedInputTypes(self, types : list):
        ''' sets the allowed input types for this model, updates the model data '''
        self._allowed_input_types = gremlin.base_classes.TraceableList(types, self._filter_change_cb)
        self.refresh()

    def _handle_model_changed(self, source, key, old_value, new_value):
        if key is not None and not isinstance(key,int):
            self.validate(key)
        if old_value is not None and not isinstance(old_value, int):
            self.validate(old_value)
        if new_value is not None and not isinstance(new_value, int):
            self.validate(new_value)
        self._data_changed = True # indicate the data has changed

    def validate(self, input_item : AbstractInputItem):
        ''' validates input items as valid for the model based on options'''
        if not input_item:
            assert False,"Input item cannot be NULL"
        input_type = input_item.input_type
        if not input_type in self._allowed_input_types:
            assert False,f"Invalid input item for allowed input types in model.  Got [{input_type.name} - allowed types: [{(it.name for it in self._allowed_input_types)}]"
        match input_type:
            case InputType.State:
                assert isinstance(input_item, gremlin.ui.state_device.StateInputItem), "Invalid type for state input"
            case InputType.Keyboard | InputType.KeyboardLatched:
                assert isinstance(input_item, gremlin.ui.keyboard_device.KeyboardInputItem), "Invalid type for keyboard input"



    @property
    def show_filtered(self) -> bool:
        return self._show_filtered_only
    @show_filtered.setter
    def show_filtered(self, value : bool):
        if self._show_filtered_only != value:
            self._show_filtered_only = value
            self.refresh()


    def _filter_change_cb(self):
        ''' occurs when the input filter changes '''
        self.refresh()


    @property
    def allowed_input_types(self):
        ''' input type filter list '''
        return self._allowed_input_types


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


    def _filter_data(self, emit = True):
        ''' Applies the filter to the source data 
        :param emit: true to emit a data changed signal after filtering
        '''
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose:
            device = gremlin.joystick_handling.getDevice(self._device_guid)
            syslog.info(f"MODEL INPUT FILTER: for [{device.name}]")
            if "left" in device.name.casefold():
                pass
        self._is_filtered = False
        if self._show_filtered_only:
            # filtering enabled
            if self._custom_filter_handler:
                # apply filter if filtering is enabled
        
                new_index_map = TriggerDict()
                new_index_map.addCallback(self._handle_model_changed)
                new_item_map = TriggerDict()
                new_item_map.addCallback(self._handle_model_changed)

                new_index = 0
                for input_item in self._index_map.values():
                    if self._custom_filter_handler(input_item):
                        if verbose: syslog.info(f"\t{input_item.display_name} -> ON")
                        new_index_map[new_index] = input_item
                        new_item_map[input_item] = new_index
                        new_index +=1
                    if verbose and new_index == 0:
                        syslog.info(f"\tall inputs are filtered for this device")


                self._filtered_index_map = new_index_map
                self._filtered_item_map = new_item_map
                self._data_changed = True 
                self._is_filtered = True

        if not self._is_filtered:
            # no filter - the filter is the sanme
            self._filtered_index_map = self._index_map.copy()
            self._filtered_item_map = self._item_map.copy()
            self._data_changed = True
            

        if emit:
            self._fireChanged()

    def modelChanged(self)-> bool:
        ''' true if the model has changed '''
        return self._data_changed

    def _fireChanged(self, force = False):
        ''' fires a data changed signal if the data has changed or if force is true '''
        if self._data_changed or force:
            for callback in self._data_changed_callbacks:
                callback()
            self.data_changed.emit() # indicate the model changed
            self._data_changed = False

    def isFiltered(self) -> bool:
        ''' true if the model is currently filtered '''
        return len(self._index_map) != len(self._filtered_index_map)

    def getFilteredIndices(self):
        ''' returns the list of indices currently visible in the model '''
        return [index for index in self._index_map]

    def getFilteredItems(self):
        ''' returns the list of filtered items '''
        return self._filtered_index_map.values()
    
    def getFilteredMap(self):
        ''' gets index,input_item tuples for all filtered items in the model '''
        return self._filtered_index_map.items()

    def getItems(self):
        ''' returns the list of unfiltered items '''
        return self._index_map.values()
    
    def getItemsMap(self):
        ''' gets index,input_item tuples for all items in the model '''
        return self._index_map.items()
    
    def ensureInputItemIsFiltered(self, input_item : InputItem) -> int:
        ''' adds an index to the filter 
        :param input_item: the input item to add to the filter
        :returns int: the new filter index (or the existng filter index)
        
        '''
        if input_item and input_item in self._item_map:
            if not input_item in self._filtered_item_map:
                filter_index = len(self._filtered_index_map)
                self._filtered_index_map[filter_index] = input_item
                self._filtered_item_map[input_item] = filter_index
            else:
                filter_index = self._filtered_item_map[input_item]
            return filter_index
        return -1

            


    def _update_source(self):
        ''' updates source data (unfiltered) '''
        self._filtered_index_map = self._index_map.copy()
        self._filtered_item_map = self._item_map.copy()

  

    def _next_source_index(self):
        ''' gets the next index for a source map '''
        i_list = [i for i in self._filtered_index_map]
        i_list.sort()
        index = 0
        while index in i_list:
            index+=1
        return index

    def _next_index(self):
        ''' gets the next index for a source map '''
        i_list = [i for i in self._index_map]
        i_list.sort()
        index = 0
        while index in i_list:
            index+=1
        return index

    def refresh(self, emit = True):
        ''' loads into the data model all the items for the current mode and device (subclass)'''
        import gremlin.base_profile
        import gremlin.config
        # load the items for this mode

        if self._custom_load_handler:
            # use our custom handler to update the model data
            if self._custom_load_handler(self):
                self._update_source()
                if self.applyFilter: self._filter_data(False) # apply filter
                self._fireChanged()
            return

        registry = gremlin.base_profile.ProfileRegistry()
        device_guid = self._device_guid
        mode = self.mode

        filtered_index = 0
        source_index = 0

        profile = gremlin.shared_state.current_profile
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_filter or config.verbose_mode_ui


        self._index_map.clear() # map of index to value
        self._item_map.clear()  # map of values to their index
        self._filtered_index_map.clear() # map of index to value
        self._filtered_item_map.clear()  # map of values to their index

        device : dinput.DeviceSummary = gremlin.joystick_handling.getDevice(device_guid)

        # load initial inputs from the registry
        input_items = registry.getInputItems(device_guid, mode, input_type = self._allowed_input_types)

        if input_items and device.device_type in (DeviceType.Joystick, DeviceType.VJoy):
            # sort by axes and buttons
            input_items.sort(key = lambda x: x.sortKey)


        for input_item in input_items:
            # process all possible inputs and build the filtered list vs the full list (source)
            
            # complete list of inputs in the device
            self._index_map[source_index] = input_item
            self._item_map[input_item] = source_index    
            source_index +=1

            if self._show_filtered_only or device.device_type in (DeviceType.Joystick, DeviceType.VJoy):
                filtered = profile.settings.getFiltered(input_item.device_guid, input_item.input_type, input_item.input_id)
            else:
                filtered = False


            if filtered:
                continue
                
            if verbose: syslog.info(f"Input {device.name} : {input_item.input_type.name} {input_item.input_id} visible")

            # holds inputs that are visible only
            self._filtered_index_map[filtered_index] = input_item
            self._filtered_item_map[input_item] = filtered_index
            filtered_index += 1



        if self._show_master_mode:
            master_mode = gremlin.shared_state.master_mode
            if master_mode in self._device_data.modes:
                # older profile may not have master mode defined until saved
                input_items = registry.getInputItems(device_guid, master_mode)
                for input_item in input_items:

                    if self._show_filtered_only or device.device_type in (DeviceType.Joystick, DeviceType.VJoy):
                        filtered = profile.settings.getFiltered(input_item.device_guid, input_item.input_type, input_item.input_id)
                    else:
                        filtered = False

                    if not input_item in self._filtered_index_map:
                        self._filtered_index_map[source_index] = input_item
                        self._filtered_item_map[input_item] = source_index    
                        source_index +=1

                    if filtered:
                        continue
                    
                    if verbose: syslog.info(f"Input {device.name} : {input_item.input_type.name} {input_item.input_id} visible")

                    if not input_item in self._item_map:
                        self._index_map[filtered_index] = input_item
                        self._item_map[input_item] = filtered_index
                        filtered_index += 1


        assert len(self._index_map) == len(self._item_map),"Invalid mapping detected"

        if emit:
            self._fireChanged()


    def indexOf(self, input_item : InputItem):
        ''' gets the index of the input item in the model (unfiltered)'''
        if input_item in self._item_map:
            return self._item_map[input_item]
        return -1
    
    def indexOfInputItem(self, input_item: InputItem):
        ''' gets the index of the input item in the model (unfiltered)'''
        return self.indexOf(input_item)
    
    def indexOfFilteredInputItem(self, input_item: InputItem):
        ''' gets the index of the input item in the model (filtered)'''
        if input_item in self._filtered_item_map:
            return self._filtered_item_map[input_item]
        return -1
    

    def hasInputItem(self, input_item: InputItem):
        ''' true if the model contains the input item (unfiltered)'''
        return input_item in self._index_map.values()

    def getInputItemAt(self, index : int):
        ''' gets the input item as the given index '''
        if index in self._index_map:
            return self._index_map[index]
        return None
    
    def getInputItemIndices(self, input_item: InputItem) -> tuple[int,int]:
        ''' gets the filterd and unfiltered indices for the input = the returned index values are -1 if the item is not found '''
        index = self._item_map[input_item] if input_item in self._item_map else -1
        filtered_index = self._filtered_item_map[input_item] if input_item in self._filtered_item_map else -1
        return (filtered_index, index)

    def isIndexVisible(self, index : int) -> bool:
        ''' true if the index is visible in the list view '''
        return index in self._filtered_index_map
        
    
    def getFilteredInputItemAt(self, index):
        ''' gets the filtered input item as the given index (will not find items that are filtered out)'''
        if index in self._filtered_index_map:
            return self._filtered_index_map[index]
        return None

    def triggerChange(self, force = False):
        ''' triggers an update'''
        self._fireChanged(force)


    def sort(self, sort_callback : Callable):
        ''' sorts the data using a sorting callback - the callback takes a list of input items, and returns a list of input items '''

        assert callable(sort_callback), "sort_callback must be a callable"

        syslog.info("Before sort:----------------------------")
        for index, input_item in self._filtered_index_map.items():
            syslog.info(f"[{index}] = [{input_item.input_id.display_name}]")

        syslog.info("After sort:----------------------------")

        item_list = [item for item in self._filtered_index_map.values()]
        item_list = sort_callback(item_list) # returns a sorted list specific to the device




        if __debug__:
            new_index_map = TriggerDict()
            new_index_map.addCallback(self._handle_model_changed)
            new_item_map = TriggerDict()
            new_item_map.addCallback(self._handle_model_changed)
            new_source_item_map = TriggerDict()
            new_source_item_map.addCallback(self._handle_model_changed)
            new_source_index_map = TriggerDict()
            new_source_index_map.addCallback(self._handle_model_changed)
        else:
            new_index_map = {}
            new_item_map = {}
            new_source_item_map = {}
            new_source_index_map = {}

        # item : InputItem
        for index, input_item in enumerate(item_list):
            if input_item in self._item_map:
                new_index_map[index] = input_item
                new_item_map[input_item] = index
            new_source_index_map[index] = input_item
            new_source_item_map[input_item] = index
            input_item.index = index # update the sorting index
            syslog.info(f"sorted [{index}] = [{input_item.input_id.display_name}]")

        self._index_map = new_index_map if new_index_map else new_source_index_map
        self._item_map = new_item_map if new_item_map else new_source_item_map
        self._filtered_index_map = new_source_index_map
        self._filtered_item_map = new_source_item_map

        self._fireChanged()

        assert len(self._index_map) == len(self._item_map),"Invalid mapping detected"


    def applyFilter(self, emit = True):
        ''' applies the filters only (does not load new data)'''
        self._filter_data(emit)

    def clearFilter(self):
        ''' removes any filtering '''
        self.refresh(apply_filter = False)

    def rows(self) -> int:
        ''' number of FILTERED rows in the model '''
        return len(self._filtered_index_map)
    
    def filteredRows(self) -> int:
        ''' number of filtered rows '''
        return self.rows()
    
    def filteredCount(self) -> int:
        ''' number of filtered rows '''
        return self.rows()
    
    def unfilteredCount(self) -> int:
        ''' gets the total input items in the model '''
        return len(self._index_map)
    


    def dataModel(self):
        ''' gets all the items'''
        return self._filtered_index_map


    def data(self, index):
        """Returns the data stored at the provided index.

        :param index the index for which to return the data
        :return data stored at the provided index
        """
        if not index in self._filtered_index_map:
            return None

        return self._filtered_index_map[index]

    def setData(self, index, value):
        ''' sets the model data '''
        if __debug__: self.validate(value)

        self._filtered_index_map[index] = value
        self._filtered_item_map[value] = index
        self._index_map[index] = value
        self._item_map[value] = index


    def filteredData(self, index):
        """Returns the data stored at the provided index.

        :param index the index for which to return the data
        :return data stored at the provided index
        """

        if not index in self._index_map:
            return None

        return self._index_map[index]



    def add(self, input_item : AbstractInputItem):
        ''' adds a new input item to the model, returns the index it was added to (subclass)'''


        if not input_item in self._index_map:
            new_index = len(self._index_map)

            # ensure index is unique
            while new_index in self._index_map.keys():
                new_index +=1

            self._item_map[input_item] = new_index
            self._index_map[new_index] = input_item

            # add to the registry
            registry = gremlin.base_profile.ProfileRegistry()
            registry.registerInputItem(input_item)
            registry.sync()

            self._update_source()
            self._filter_data(emit = False) # apply any filter 

            input_item.index = new_index

            assert len(self._index_map) == len(self._item_map),"Invalid mapping detected"

            self._fireChanged()

            return new_index
        else:
            # return the index of the existing item
            return self._item_map[input_item]

    def remove(self, index):
        ''' removes the item at the specified index (subclass)'''
        import gremlin.base_profile

        if self._custom_remove_handler:
            if self._custom_remove_handler(self, index):
                self._fireChanged()
                return True
            return False

        input_item = self.filteredData(index)
        if input_item:
            input_type = input_item.input_type
            if not input_type in (InputType.Keyboard, InputType.KeyboardLatched, InputType.OpenSoundControl, InputType.Midi, InputType.State):
                # cannot remove other types
                return False

            input_id = input_item.input_id

            source_index = self._item_map[input_item]

            # remove the row from the model
            
            del self._filtered_index_map[index]
            del self._filtered_item_map[input_item]

            del self._index_map[source_index]
            del self._item_map[input_item]
            

            registry = gremlin.base_profile.ProfileRegistry()
            input_id_key = registry.getInputIdKey(input_id)

            input_items = self._device_data.modes[self._mode]
            if input_type in input_items.config and input_id_key in input_items.config[input_type]:
                del input_items.config[input_type][input_id_key]
            registry.removeInputItem(input_item)

            # sync with profile data
            registry.sync()

            self._fireChanged()
            return True # data removed
        
        return False # no data removed
    

    def clear(self):
        ''' clears all items from the model (subclass)'''
        if self._index_map:
            # not empty
            self._index_map.clear()
            self._item_map.clear()
            self._filtered_index_map.clear()
            self._filtered_item_map.clear()
            self._fireChanged(True)
                   



    def action_id_to_index(self, action_id):
        ''' get the model index containing the action id'''

        if action_id:
            # find the row by action_id
            for index in range(self.rows()):
                data = self.data(index)
                for container in data.containers:
                    for action_list in container.action_sets:
                        for action_data in action_list:
                            if action_data.action_id == action_id:
                                return index

        # not found
        return -1

    def input_id_index(self, item):
        ''' gets the model index based on the input id content '''
        if item and item in self._item_map.keys():
            return self._item_map[item]
        return -1

    def event_to_index(self, event):
        """Converts an event to a model index.

        :param event the event to convert
        :return index corresponding to the event's input
        """

        input_items = self._device_data.modes[self._mode]


        offset_map = dict()
        offset_map[InputType.Keyboard] = 0
        offset_map[InputType.JoystickAxis] =\
            len(input_items.config[InputType.Keyboard])
        offset_map[InputType.JoystickButton] = \
            offset_map[InputType.JoystickAxis] + \
            len(input_items.config[InputType.JoystickAxis])
        offset_map[InputType.JoystickHat] = \
            offset_map[InputType.JoystickButton] + \
            len(input_items.config[InputType.JoystickButton])
        offset_map[InputType.KeyboardLatched] = \
            offset_map[InputType.JoystickHat] + \
            len(input_items.config[InputType.JoystickHat])
        offset_map[InputType.OpenSoundControl] = \
            offset_map[InputType.KeyboardLatched] + \
            len(input_items.config[InputType.KeyboardLatched
            ])
        offset_map[InputType.Midi] = \
            offset_map[InputType.OpenSoundControl] + \
            len(input_items.config[InputType.OpenSoundControl
            ])


        if event.event_type in (InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat):
            # Generate a mapping from axis index to linear axis index
            # axis_index_to_linear_index = {}
            item: InputItem
            item_found: InputItem = None
            index : int

            for index, item in self._index_map.items():
                if item.input_type == event.event_type and item.input_id == event.identifier:
                    item_found = item
                    break
            if item_found:
                return index

            return 0

        else:
            return offset_map[event.event_type] + event.identifier - 1

    def clear(self, emit = True):
        ''' removes all currently filtered inputs'''
        self._reset(emit, filtered_only = True)

    def clearAll(self, emit = True):
        ''' removes all inputs regardless of filter type '''
        self._reset(emit, filtered_only = False)
        

    def _reset(self, emit = False, filtered_only = True):
        ''' clears all data '''
        import gremlin.base_profile
        if self._custom_clear_handler:
            self._custom_clear_handler(self)
        else:
            # normal internal handling
            if filtered_only:
                # delete filtered inputs only
                input_list = self._filtered_index_map.values()
            else:
                # delete all inputs
                input_list = self._index_map.values()

            
            if input_list:
                input_list = list(input_list) 
                
                if self._custom_clear_handler:
                    self._custom_clear_handler(self)
                else:
                    # remove the input items in the filtered list
                    registry = gremlin.base_profile.ProfileRegistry()
                    for input_item in input_list:
                        registry.removeInputItem(input_item)

                        # delete from the main model       
                        if input_item in self._item_map:
                            index = self._item_map[input_item]
                            del self._index_map[index]
                            del self._item_map[input_item]

                        if input_item in self._filtered_item_map:
                            index = self._filtered_item_map[input_item]
                            del self._filtered_index_map[index]
                            del self._filtered_item_map[input_item]

                    # sync deletions with the profile
                    registry.sync()

                # remove the filtered input from the source data    
                if emit:
                    self._fireChanged(True)

    def __len__(self):
        return self.rows()




class InputItemListView(AbstractView):

    """View displaying the contents of an InputItemListModel. Used in the left panel of the main UI to display inputs."""
    updated = Signal() # fires when the data is updated
  
    # Conversion from input type to a display name
    type_to_string = {
        InputType.JoystickAxis: "Axis",
        InputType.JoystickButton: "Button",
        InputType.JoystickHat: "Hat",
        InputType.Keyboard: "",
        InputType.KeyboardLatched: "(latched)",
        InputType.OpenSoundControl: "OSC",
        InputType.Midi: "Midi"
    }

    def __init__(self, parent=None,
                 name = "Not set",
                 custom_widget_handler : Callable = None,
                 selection_changed_handler : Callable[[InputItemWidget, InputItemWidget]] = None,
                 device_guid : str = None,
                 blank_message : str = "No data", 
                 enable_filter : bool = False,
                 model : InputItemListModel = None):
        """Creates a new input item view instance

        :param parent: the parent of the widget
        :param name: name of the list
        :param custom_widget_handler: (list_view : InputItemListView, index : int, identifier : InputIdentifier, data, parent = None)
        :param selection_changed_handler: handler for widget selection changed (old_widget [none], new_widget [none])
        :param device_id: id of the device the list applies to (optional)
        :param blank_message: text to display if there are no rows in the list

        """
        super().__init__(model=model, parent= parent)

        # default visible supported input types
        self.shown_input_types = [
            InputType.JoystickAxis,
            InputType.JoystickButton,
            InputType.JoystickHat,
            InputType.Keyboard,
            InputType.KeyboardLatched,
            InputType.OpenSoundControl,
            InputType.Midi
        ]

        if not device_guid:
            raise ValueError("device_guid is required for InputItemListView")
        assert isinstance(model, InputItemListModel), "invalid model for list view - must be an InputItemListModel base type"
        
        self.pushSuspended()

        self.name = name
        self._device_guid = device_guid
        self._device = gremlin.joystick_handling.getDevice(device_guid)
        self._current_index = -1 # nothing selected
        self.custom_widget_handler = custom_widget_handler
        self._selection_change_callbacks = [selection_changed_handler] if selection_changed_handler else []
        self._last_selected_widget : InputItemWidget = None # holds a reference to the last widget selected in the list
        
        self._deleted = False
        self._blank_message = blank_message
        self._enable_filter = enable_filter
        self.setMinimumWidth(230)


        # Create required UI items
        self.main_layout = QtWidgets.QVBoxLayout(self)

        if enable_filter:
            self._warning_widget = gremlin.ui.ui_common.QWarningWidget(
                text="Some inputs are currently filtered",
                icon = gremlin.ui.ui_common.Icons.warningIcon(gremlin.ui.ui_common.Color.blueColor()),
                tooltip="One or more inputs in this list are currently filtered.  Change the filter settings to show them.")
            self.main_layout.addWidget(self._warning_widget)
        else:
            self._warning_widget = None

        # use a stack to display either the inputs or no data
        self._stacked_widget = QtWidgets.QStackedWidget()
        self.main_layout.addWidget(self._stacked_widget)

        self._scroll_area = QtWidgets.QScrollArea()
        self._scroll_area.setWidgetResizable(True)

        self._scroll_widget, self._scroll_layout = gremlin.ui.ui_common.getVContainer()
        self._scroll_widget.setContentsMargins(2,2,2,2)

        # Configure the scroll area
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setWidget(self._scroll_widget)


        # Add the scroll area to the main layout
        self.main_layout.addWidget(self._scroll_area)


        el = gremlin.event_handler.EventListener()
        # el.mapping_changed.connect(self._mapping_changed)
        el.sync_input.connect(self._sync_input)

        self._drawn_once = False # true if the list has been redrawn at least once
        self._redraw_lock = False

        self._widget_map = {} # map of input item to input widget
        self._blank_message_widget = gremlin.ui.ui_common.QFrameBox(blank_message, css = gremlin.ui.ui_common.Color.cssNormalBox())

        self._stacked_widget.addWidget(self._blank_message_widget) # index 0
        self._stacked_widget.addWidget(self._scroll_area) # index 1

        self.showBlank()

        # load data and update
        self.popSuspended()

        # hook model changes to update the list view with model changes
        self.model.data_changed.connect(self.redraw)

    def addCallback(self, callback: Callable):
        ''' adds a selection change callback '''
        assert callable(callback),"invalid callback"
        if not callback in self._selection_change_callbacks:
            self._selection_change_callbacks.append(callback)

    def removeCallback(self, callback: Callable):
        ''' removes a selection change callback '''
        if callback in self._selection_change_callbacks:
            self._selection_change_callbacks.remove(callback)

    def _fireSelectionChangeCallbacks(self, old_widget: InputItemWidget, new_widget : InputItemWidget):
        ''' fires the selection change callbacks '''
        for callback in self._selection_change_callbacks:
            callback(old_widget, new_widget)


    def count(self) -> int:
        ''' gets the number of input items displayed '''
        return len(self._widget_map)

    def setBlankMessage(self, message : str = None):
        ''' sets the blank message, set to None to disable'''
        gremlin.util.InvokeUiMethod(self._setblankMessage_ui, message)

    def _setBlankMessage_ui(self, message : str):
        self._blank_message = message
        self._blank_message_widget.setText(message or "")
        self._stacked_widget.setCurrentIndex(0 if message is not None else 1)

    def showBlank(self):
        ''' displays a blank page '''
        self._stacked_widget.setCurrentIndex(0)

    def showContent(self):
        ''' displays the content page'''
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

                key = next(iter(self._widget_map)) # first widget
                widget = self._widget_map[key] #gremlin.util.get_layout_widgets(self._scroll_layout)
                if hasattr(widget,"widget_height"):
                    # not in label mode
                    if widget.widget_height is not None:
                        h = 0
                        for i, widget in enumerate(self._widget_map.values()):
                            h += widget.widget_height
                            if i == index:
                                target_widget = widget
                                break
                        self._scroll_area.ensureVisible(0,h)
                        self._scroll_area.ensureWidgetVisible(target_widget)

    def scrollToInput(self, input_item):
        self._sync_input(input_item)

    def scrollToWidget(self, widget):
        ''' scrolls the list view to the specified widget '''
        if widget in self._widget_map.values():
            self._scroll_area.ensureWidgetVisible(widget)


    @property
    def current_index(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index : int, emit = True):
        ''' sets the current index '''
        if self._current_index != index:
            widget = self.widget(index)
            if widget:
                self._select_item(index, emit)




    @property
    def current_device(self):
        ''' gets the device associated with this list view '''
        return self._device

    def _mapping_changed(self, item_data):
        gremlin.util.InvokeUiMethod(self._mapping_changed_ui, item_data) # to UI thread if needed

    def _mapping_changed_ui(self, item_data):
        ''' mapping changed '''
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
        self.model.setAllowedInputTypes(types) # changes the model to show only the selected types
        

    def removeRow(self, index):
        ''' removes the item at the given index '''
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

            self._select_item(new_index)

    def getWidgets(self):
        ''' gets the list of widgets in the list view '''
        if not Shiboken.isValid(self._scroll_layout):
            return
        widgets = gremlin.util.get_layout_widgets(self._scroll_layout)
        return widgets
   
    def widget(self, index):
        ''' gets a specific widgets at the given index '''
        if index != -1:
            model : InputItemListModel = self.model
            input_item = model.getFilteredInputItemAt(index)
            if input_item and input_item in self._widget_map:
                widget = self._widget_map[input_item]
                return widget
        return None

    def getWidgetForInputItem(self, input_item : InputItem):
        ''' gets the corresponding widget for the given input item '''
        index = self.model.indexOfInputItem(input_item)
        return self.widget(index)
    
    def getInputItemIndex(self, input_item : InputItem):
        ''' gets the index in the list of a particular input'''
        return self.model.indexOfInputItem(input_item)
        
    def getWidgetAt(self, index : int) -> InputItemWidget:
        ''' gets the widget at the given index '''
        return self.widget(index)


    def scrollToWidget(self, widget):
        ''' scrolls to a specific widget in the list '''
        if widget is not None:
            self._scroll_to_item(widget)

    def indexOf(self, input_item):
        ''' gets the index of the widget, -1 if not found'''
        return self.model.indexOfInputItem(input_item)


    def scrollToIndex(self, index):
        ''' scrolls to a specific index '''
        widget = self.widget(index)
        if widget is not None:
            self._scroll_to_item(widget)

    def _clear_widgets(self):
        ''' clears the scroll area widgets '''
        for widget in self._widget_map.values():
            widget.hide()
            self._scroll_layout.removeWidget(widget)
            if hasattr(widget,"_cleanup_ui"):
                widget._cleanup_ui()
            widget.deleteLater()
        self._widget_map.clear()

        # remove spacers
        gremlin.util.clear_layout(self._scroll_layout)


    def create_ui(self):
        ''' creates or recreates the contents of the input list view (left side input selector) '''

        push_cursor = True
        gremlin.util.pushCursor()

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_ui or config.verbose_mode_inputs
        if verbose:
            syslog.info(f"InputItemListView: device:[{self.current_device.name}] create ui")
        try:


            # self.setUpdatesEnabled(False)

            with QtCore.QSignalBlocker(self):
                # clear the widgets
                self._clear_widgets()

                if self.model is not None:
                    syslog.info(f"ListView: create widgets for [{self.model.display_name}] - filtered: [{self.model.filteredCount()}] unfiltered: [{self.model.unfilteredCount()}]")
                    
                    for model_index, input_item in self.model.getFilteredMap():
                        identifier = InputIdentifier(
                            input_item.input_type,
                            input_item.device_guid,
                            input_item.input_id,
                            input_item.device_type,
                            input_item.input_name or input_item.display_name,
                            is_axis = input_item.is_axis,
                            is_button = input_item.is_button,
                            input_item = input_item
                        )

                        syslog.info(f"\t[{model_index}]  {input_item.display_name}")


                        if self.custom_widget_handler:
                            # get the widget from the custom handler
                            widget : InputItemWidget = self.custom_widget_handler(self, model_index, identifier, input_item, parent = self._scroll_layout)
                            assert isinstance(widget, InputItemWidget), "custom handler returned an invalid widget "
                            widget.addSelectionChangeCallback(self._handle_widget_selection_changed) # hook selection changes
                            widget.index = model_index
                            assert widget is not None, "Custom widget handler didn't return a widget"
                        else:
                            # create a standard input widget
                            widget = InputItemWidget(identifier, self._handle_widget_selection_changed)
                            if input_item.input_type == InputType.JoystickAxis:
                                prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""
                                widget.setIcon(f"{prefix}joystick.png")
                            elif input_item.input_type == InputType.JoystickButton:
                                widget.setIcon("mdi.gesture-tap-button")
                            elif input_item.input_type == InputType.JoystickHat:
                                widget.setIcon("ei.fullscreen")

                        widget.index = model_index
                        widget.create_action_icons(input_item)
                        
                            

                        # store a reference to this widget for the model
                        self._widget_map[input_item] = widget

                        # set the description based on the mapping description
                        widget.setDescription(input_item.description)
                        # id update
                        widget._update_container_id()

                        self._scroll_layout.addWidget(widget)

                        # hook the widget
                        widget.index = model_index # assigned index

                        widget.edit.connect(self._create_edit_callback(model_index))
                        widget.edit_curve.connect(self._create_edit_curve_callback(model_index))
                        widget.delete_curve.connect(self._create_delete_curve_callback(model_index))
                        widget.closed.connect(self._create_closed_callback(model_index))

                        if verbose:
                            syslog.info(f"\t added input for: [{model_index:02d}] type: {InputType.to_string(input_item.input_type)} input id: [{input_item.input_id}] id: {input_item.id}")
                    
                    # bump input contents to the top 
                    self._scroll_layout.addStretch(10) # stretch at the bottom in case we have fewer items
                
            count = len(self._widget_map)
            if count == 0:
                if verbose: syslog.info("\tFound no content to display.")
                self.showBlank()
            else:
                self.showContent()

        finally:

            if push_cursor:
                gremlin.util.popCursor()
            
            # self.setUpdatesEnabled(True)
            self.update()


    def redraw(self, force : bool = False):
        gremlin.util.InvokeUiMethod(self._redraw_ui, force) # ensure on UI thread

    def _redraw_ui(self, force :bool = False):
        """Redraws the entire view.  must be on UI thread"""

        """Redraws the entire model.
        """
        if not Shiboken.isValid(self):
            return
        
        if gremlin.shared_state.is_redraw_suspended():
            return # don't redraw

        widget_count = 0 # number of displayed input item widgets
        try:
            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_ui or config.verbose_mode_inputs

            changed = False
            model_count = self.model.filteredRows() # widgets that should be displayed
            widget_count = self.getInputItemWidgetCount()
            if model_count == widget_count:
                # check to see if the widgets match the inputs
                for input_item in self.model.getFilteredItems():
                    if not input_item.id in self._widget_map:
                        force = True
                        changed = True
                        break
            else:
                changed = True

   

            if not force and not changed:
                return # do not update
            
                # ts = gremlin.tabstate.TabState()
                # data = ts.getData(self._device_guid)
                # if not data or not data.populateEnabled:
                #     # do not populate the list yet
                #     return
                
            if verbose:
                syslog.info("InputItemListView: redraw")

    
            if force or changed:
                # create if the first time or if the model changed
                self.create_ui()
                self._drawn_once = True
                widget_count = self.getInputItemWidgetCount()

            if __debug__:
                model_count = self.model.filteredRows() # widgets that should be displayed
                assert self._drawn_once and (widget_count == model_count), "InputItemListView model and UI are not synchronized (mismatched items)"


            

            if self.current_index == -1 and model_count > 0:
                self.setCurrentIndex(0) # pick the first item if nothing is selected now

            # reselect input and make visible
            widget = self.widget(self.current_index)
            if widget:
                if not widget.selected:
                    # ensure selected
                    widget.setSelected(True, emit = False)
                self.scrollToWidget(widget)
        finally:
            # toggle blank/content view
            if widget_count == 0:
                self.showBlank()
            else:
                self.showContent()     


    def getInputItemWidgetCount(self):
        ''' gets the number of input widgets in the list '''
        return len(self._widget_map)

    def redraw_index(self, index : int):
        if not gremlin.shared_state.is_running:
            gremlin.util.InvokeUiMethod(self._redraw_index_ui, index) # ensure on UI thread


    def _redraw_index_ui(self, index : int):
        """Redraws the view entry at the given index.

        :param index the index of the entry to redraw
        """

        if not Shiboken.isValid(self):
            # garbage collected
            return

        if gremlin.shared_state.is_redraw_suspended():
            return

        if self.model is None or self._deleted:
            return

        verbose = gremlin.config.Configuration().verbose_mode_ui

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



    def _create_edit_callback(self, index : int):
        """Creates a callback handling the edit action of an input widget

        :param index the index of the item to create the callback for
        :return callback to be triggered when the item at the provided index
            is selected
        """
        return lambda x: self._edit_item_cb(index)


    def _create_edit_curve_callback(self, index : int):
        return lambda : self._edit_curve_item_cb(index)

    def _create_delete_curve_callback(self, index : int):
        return lambda : self._delete_curve_item_cb(index)


    def _create_closed_callback(self, index : int):
        """Creates a callback handling the close action of an input widget

        :param index the index of the item to create the callback for
        :return callback to be triggered when the item at the provided index
            is selected
        """

        # get the index for this widget
        return lambda x: self._close_item_cb(index)





    def _close_item_cb(self, index):
        ''' remove a particular input '''
        from PySide6.QtCore import QMetaMethod

        widget = self.widget(index)
        if isSignalConnected(widget,"closed(InputIdentifier)"):
            widget.closed.emit(self, index)
            return

        # select the widget if it's not selected
        data = self.model.data(index)
        if data and (data.containers or data.input_type == InputType.KeyboardLatched):
            # prompt confirm
            result = gremlin.ui.ui_common.ConfirmBox("Delete confirmation","This will delete associated actions for this entry.\nAre you sure?")
            if result:
                self._confirmed_close(index)
        else:
            # no need to confirm
            self._confirmed_close(index)

    def _confirmed_close(self, index):
        self.removeRow(index)
        el = gremlin.event_handler.EventListener()
        el.device_mapping_changed.emit(self._device_guid)
        self.item_closed.emit(self, index, self.model.data(index)) # widget, index, data
        
        # select prior item
        if index > 0:
            index-=1
            data = self.model.data(index)
            if data:
                self._select_item(index)

    def _edit_item_cb(self, index : int):
        ''' emits the edit event along with the item being edited '''
        self.item_edit.emit(self, index, self.model.data(index)) # widget, index, data

    def _edit_curve_item_cb(self, index : int):
        input_item = self.model.data(index)
        self.item_edit_curve.emit(self, index, input_item)
        el = gremlin.event_handler.EventListener()
        el.curve_added.emit(input_item)

    def _delete_curve_item_cb(self, index : int):
        input_item = self.model.data(index)
        self.item_delete_curve.emit(self, index, self.model.data(index))
        el = gremlin.event_handler.EventListener()
        el.curve_deleted.emit(input_item)

    def _update_value_changed(self, index : int, value : float):
        self.item_input_value_changed.emit(self, index, self.model.data(index), value)



    def update_item(self, index):
        ''' update the widget with new data '''
        widget = self.widget(index)
        if not widget:
            self._select_item(index)
            widget = self.widget(index)
        if widget:
            widget.update_display()


    def unselect_item(self, index):
        ''' unselects an item '''
        pass
    

    
    def _handle_widget_selection_changed(self, widget : InputItemWidget):
        ''' called when a widget changes selection '''
        if widget.selected:
            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_inputs or config.verbose_mode_ui
            index = widget.index
            if self._current_index != index:
                old_widget = self._last_selected_widget
                if old_widget:
                    if Shiboken.isValid(old_widget):
                        old_widget.setSelected(False, False) # de-select old
                    self.item_selected.emit(self._current_index, False) # trigger the event

                
                self._current_index = index # update to the new selected index in the list
                self._last_selected_widget = widget # store the new reference
                if verbose: syslog.info(f"InputItemListView: trigger selection for index [{index}]")
                self._fireSelectionChangeCallbacks(old_widget, widget) # process selection change callbacks - sends the old (deselected) and new widget (selected) if any
                self.item_selected.emit(index, True) # trigger the event

    

    def selectItemAt(self, index, emit = True, force = False, user_selected = False):
        ''' selects an input by index '''
        gremlin.util.InvokeUiMethod(self._select_item, index, emit, force, user_selected)

    def selectInputItem(self, input_item: InputItem, emit = True, force = False, user_selected = False):
        ''' selects the input '''
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_inputs or config.verbose_mode_ui
        filtered_index, index = self.getInputItemIndices(input_item)
        if filtered_index == -1:
            # auto-flip to index if it exists 
            filtered_index = index
        if index != -1: # found
            if verbose: syslog.info(f"InputItemListView: select input [{input_item.display_name}] index [{index}]")
            gremlin.util.InvokeUiMethod(self._select_item, index, emit, force, user_selected)
        else:
            if verbose: syslog.info(f"InputItemListView: select input [{input_item.display_name}] FAIL - input not found in the list]")
        
        

    def _select_item(self, index, emit=True, force = False, user_selected = False):
        """Handles selecting a specific item.  this is called whenever an input item is selected

        :param index:the index of the item being selected
        :param emit: flag indicating whether or not a signal is to be emitted when the item is being selected
        :param force: forces an update
        """

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_inputs or config.verbose_mode_ui
        
        if verbose: syslog.info(f"InputItem: request to select input index: [{index}]")
        if not Shiboken.isValid(self._scroll_area):
            if verbose: syslog.warning("\tshiboken invalid")
            return


        model : InputItemListModel = self.model

      
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
            if verbose: syslog.warning(f"\tindex [{index}] is already selected")
            return # nothing to do if the current index is the same as the new index


        if index == -1:
            for item in self._scroll_layout.children():
                widget = item.widget()
                if widget:
                    if widget.selected:
                        index = widget.index
                        break
                    
        
                    
        if not model.isIndexVisible(index):
            if verbose: syslog.warning(f"\tindex [{index}] is not visible")
            return



        last_widget = self._last_selected_widget
        if self._current_index != index:
            if last_widget and Shiboken.isValid(last_widget):
                # deselect prior widget if it can be selected
                if verbose: syslog.info(f"\tdeselect index [{self._current_index}]: {last_widget.input_item.display_name}")
                last_widget.setSelected(False, False)
            
            # widget to select
            widget = self.widget(index)
            assert widget is not None,"widget not found in list"
            widget.setSelected(True) # this fires the updates and callbacks via the _handle_widget_selection_changed callback

        return widget

    def clearSelection(self, emit = True):
        widgets = [w for w in gremlin.util.get_layout_widgets(self._scroll_layout)]
        for w in widgets:
            w.setSelected(False, emit = emit)

    
    def currentIndex(self) -> int:
        ''' gets the currently selected index, -1 if no selection or list is empty '''
        return self._current_index


    def _create_scroll_callback(self, widget):
        return lambda : self._scroll_to_item(widget)

    def ensureVisible(self, widget):
        gremlin.util.singleShot(self._create_scroll_callback(widget))

    def _scroll_to_item(self, widget):
        gremlin.util.InvokeUiMethod(self._scroll_to_item_ui, widget)

    def _scroll_to_item_ui(self, widget):
        # runs on UI thread
        QtWidgets.QApplication.processEvents()
        if Shiboken.isValid(self._scroll_area) and Shiboken.isValid(widget):
            self._scroll_area.ensureWidgetVisible(widget)

    def __len__(self):
        return self.count()


class ActionSetModel(AbstractModel):

    """Model storing a set of actions."""

    def __init__(self, action_set=[]):
        super().__init__()
        assert isinstance(action_set, list),"Invalid action set provided"
        self._action_set = action_set

    def rows(self):
        return len(self._action_set)

    def data(self, index):
        return self._action_set[index]

    def add_action(self, action):
        self._action_set.append(action)

        el = gremlin.event_handler.EventListener()
        event = gremlin.event_handler.DeviceChangeEvent()
        event.device_guid = action.hardware_device_guid
        event.device_input_id = action.hardware_input_id
        event.device_input_type = action.hardware_input_type
        event.source = action

        el.icon_changed.emit(event)

        container : gremlin.input_item.AbstractContainer = action.get_container()
        container.mapping_changed() # tell the UI about the change

        # blows up in QT 6.11
        # try:
        #     self.data_changed.emit()
        # except:
        #     pass # ignore signal issues



    def remove_action(self, action):
        ''' runs when an action should be deleted '''
        import gremlin.util
        try:
            gremlin.util.pushCursor()
            if action in self._action_set:
                input_item = action.get_input_item()
                container : gremlin.input_item.AbstractContainer = action.get_container()
                del self._action_set[self._action_set.index(action)]

                # run action delete if the action supports it
                if hasattr(action,"actionDeleted"):
                    action.actionDeleted()

                el = gremlin.event_handler.EventListener()
                el.action_delete.emit(input_item, container, action) # tell the UI the action is being deleted
                if hasattr(action,"_cleanup"):
                    action._cleanup()

                event = gremlin.event_handler.DeviceChangeEvent()
                event.source = input_item
                event.device_input_id = input_item
                el.icon_changed.emit(event)

                container.mapping_changed() # tell the UI about the change


            # try:
            #     self.data_changed.emit()
            # except:
            #     pass
        finally:
            gremlin.util.popCursor()

    def refresh(self, emit=True):
        # refresh the action set
        pass


class AbstractAction(BaseProfileData):

    """Base class for all actions that can be encoded via the XML and
    UI system."""

    #id_changed = Signal(str, str)  # triggers when the ID changes

    # allow all input types by default
    input_types = InputType.to_list()
    # data_changed = QtCore.Signal() # indicates the action data changed

    def __init__(self, parent):
        """Creates a new instance.

        :parent the container which is the parent to this action
        """
        # assert isinstance(parent, AbstractContainer)
        super().__init__(parent)

        self._abstract_action_generating_xml = False # true if generating XML
        self.activation_condition = None # stores the conditions attached to that action
        self._id = gremlin.util.get_guid()
        self._action_type = None
        self._enabled = False # true if the action is enabled
        self.singleton = False # true if the action can only appear once in the input's mapping
        self.parent_container = parent # holds the reference to the parent container holding this action
        self._is_axis = False
        self._is_hardware = None
        self.comment = None # user comments/notes
        self._priority = 5 # default priority
        self.data = None # additional data for runtime purposes, context dependent used to tag actions at runtime for some purpose like action grouping
        self.data_ex = None # additional data for
        self.condition_view = None # holds the condition view object for this action
        self._is_multi_mode_action = False # true if a multimode action
        self._send_mode = SendType.Normal # normal send type

        # new T83 - remote control configuration object
        self.remote_config = gremlin.remote.RemoteConfig() # this action does not allow local control



        self._hooked = False
        el = gremlin.event_handler.EventListener()
        el.profile_hook.connect(self.hook)
        el.profile_unhook.connect(self.unhook)
        el.action_created.emit(self)
        el.profile_unload.connect(self._cleanup)
        el.action_delete.connect(self._action_delete)


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
    def sendMode(self, value : SendType):
        self._send_mode = value

    def sendFlags(self) -> tuple:
        ''' returns a (is_local, is_remote) boolean tuple based on the action's current send mode '''


        match self._send_mode:
            case SendType.Normal:
                return self.remote_config.state
                #return gremlin.remote.remote_control.state
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
        ''' true if the action is a multimode action'''
        return self._is_multi_mode_action

    def profile_start(self):
        ''' start event - override in subclass as needed '''
        pass

    def profile_stop(self):
        ''' stop event - override in subclass as needed '''
        pass

    def profile_post_start(self):
        ''' post start event - occurs after profile started '''
        pass

    def profile_started(self):
        ''' started event - override in subclass as needed '''
        pass

    def getCurves(self) -> list:
        ''' gets action node siblings'''
        container = self.parent_container
        curve_list = []
        for action_set in container.action_sets:
            for action in action_set:
                 if gremlin.base_profile._is_curve_tag(action.tag):
                    curve_data = action.curve_data
                    if curve_data:
                        curve_data.curve_update()
                        curve_list.append(curve_data)
        return curve_list



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
        value = gremlin.util.clamp(value,0, 1000)
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
        input_item = self._get_input_item(self.parent_container)
        return input_item

    def get_container(self):
        return self.parent_container


    def get_sibblings(self):
        ''' gets action sibblings in the same container '''
        container = self.get_container()
        return container.getActions()

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
            syslog.info(f"ACTION: SET ENABLED STATE: Functor: {self.name} {type(self).__name__} enabled")

    def enabled(self)-> bool:
        return self._enabled

    def input_is_axis(self):
        ''' true if the input is an axis type input '''
        input_item = self.input_item
        if hasattr(input_item, "is_axis"):
            return input_item.is_axis
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
        input_item = self.input_item
        # check hat first
        hardware_input_type = self.hardware_raw_input_type

        input_type = None
        if hasattr(self.parent_container,"get_input_type"):
            input_type = self.parent_container.get_input_type() # container override input type

        if input_type:
            return input_type == InputType.JoystickButton

        if hardware_input_type == InputType.JoystickHat:
            return False

        if hasattr(input_item, "is_button"):
            is_button = input_item.is_button
            return is_button

        if hasattr(self, "hardware_input_type"):
            input_type : InputType = self.hardware_input_type
            return input_type == InputType.JoystickButton

        if hasattr(self.hardware_input_id, "is_button"):
            is_button = self.hardware_input_id.is_button

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




    def from_xml(self, node, data = None, extra_data = None):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """

        # set the action ID first as it can be read by subsequent code
        import_data = gremlin.base_profile.ProfileImportData()

        if "action_id" in node.attrib:
            self._id = node.get("action_id")

        if "send-mode" in node.attrib:
            mode_int = safe_read(node, "send-mode", int, 0)
            mode = SendType(mode_int)
            self._send_mode = mode


        comment = None
        if "comment" in node.attrib:
            comment = node.get("comment")
        if comment:
            self.comment = comment

        priority = 5 # default priority for actions
        if "priority" in node.attrib:
            priority = safe_read(node, "priority",int, 5)
            priority = gremlin.util.clamp(priority,0, 1000)
            self._priority = priority


        nodes = node.xpath(".//remote-config")
        if nodes:
            self.remote_config.from_xml(nodes[0])



        super().from_xml(node, data, extra_data)


        self.activation_condition = gremlin.actions.ActivationCondition([],ActivationRule.All)
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

    def __hash__(self):
        # index on the unique ID 
        return hash(self._id)


class MultiModeAbstractAction(AbstractAction):
    ''' indicates the action works with multiple modes '''
    def __init__(self, parent):
        super().__init__(parent)
        self._is_multi_mode_action = True # indicate this is a multimode action


class ConditionContainer():
    ''' holds conditions for containers '''

    def __init__(self):
        self._id = gremlin.util.get_guid() # unique GUID of this container
        self.activation_condition = gremlin.base_conditions.BaseActivationCondition([],ActivationRule.All) # activation condition that applies to the container
        self.activation_condition.setContainer(self)
        self._container = None

    @property
    def condition_count(self):
        return len(self.activation_condition.conditions)

    @property
    def id(self):
        return self._id

    def setId(self, value : str):
        ''' sets the ID '''
        self._id = value

    def setContainer(self, container):
        self._container = container

    def get_container(self):
        return self._container


class AbstractContainer(BaseProfileData, ConditionContainer):

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

        self._abstract_container_generating_xml = False # true if generating
        self._action_sets = ActionSets(self)
        self.action_model = None # set at creation by the parent of this container
        self.custom_action_sets = False # true if the container uses custom action sets (need a converter to produce action_sets)
        self._condition_enabled = True # condition flag
        self._virtual_button_enabled = True # determines if the callbacks can be virtualized or not - if not - the callback is "raw" to the functor - action / container set
        self._virtual_button_user_enabled = True # determins if callbacks use the virtual button function - user set
        # self.activation_condition = ActivationCondition([],ActivationRule.All) # activation condition that applies to the container
        # self.activation_condition.setContainer(self)
        self.virtual_button = None
        self.current_view_type = None
        self.parent_node = node
        self.comment = None # user comment
        self._callbacks_enabled = True # callbacks are enabled by default for this container
        self._collapsed = False # true if the container is collapsed
        self.actionsetParseCallback = None # callback to use when parsing action set if it has additional data (node), returns an action set
        self.actionsetCustomParseCallback = None # callback for the complete action set parsing
        self.definition_mode = self.get_mode()

        el = gremlin.event_handler.EventListener()
        el.virtual_button_changed.connect(self._virtual_button_changed)


        self._action_sets_callback = None # callback to return different action sets if needed for containers that do their own thing

        # attached hardware device to this container
        input_item = None
        if isinstance(parent, gremlin.profile_graph.ProfileContainerNode):
            input_item = self._get_input_item(parent)
            if not input_item:
                input_item = self._get_input_item(parent)

        if not input_item:
            input_item = self._get_input_item(parent)
            if input_item is None:
                input_item = self._get_input_item(parent)

        self._input_item = input_item
        assert input_item is not None
        # if input_item is not None:
        self.device_guid = input_item.device_guid
        self.device_input_id = input_item.input_id
        self.device_input_type = input_item.input_type
        self.device = gremlin.joystick_handling.device_info_from_guid(self.device_guid)

    def _get_input_item(self, parent):
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

    @property
    def action_sets(self):
        return self._action_sets
    
    # @action_sets.setter
    # def action_sets(self, value):
    #     pass

    def getActionsSets(self) -> ActionSets:
        return self._action_sets


    def setActionSets(self, data : ActionSets):
        ''' sets a custom action set'''

        if isinstance(data, ActionSets):
            # already an object?
            self._action_sets = data
            return
        
        # default style action set definitions provided as lists
        action_sets = ActionSets(self)
        for item in data:
            if hasattr(item,"__iter__"):
                if not item:
                    # blank list = create an action set
                    action_sets.add(ActionSet())
                else:
                    assert isinstance(item, ActionSet)
                    action_sets.append(item)
        else:
            # single action set
            action_sets.append(ActionSet())

        self._action_sets = action_sets


    def resetActionSets(self):
        ''' resets actions sets - override in derived class if the action set default should be different '''
        if self.action_sets:
            for action_set in self.action_sets:
                action_set.clear()



    def dumpActionSets(self, action_sets : list, label = None):
        ''' dumps the container's action sets to the output '''

        if label:
            syslog.info(f"Container action sets: {label}")
        else:
            syslog.info("Container action sets:")

        if not action_sets:
            syslog.info("\tno action sets found")

        for index, action_set in enumerate(action_sets):
            self.dumpActionSet(action_set, label = f"Action set [{index}]:", indent = "\t")



    def dumpActionSet(self, action_set : list, label = None, indent = ""):
        ''' dumps a single action set'''
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
                syslog.info(f"{indent}\t\tAction [{index}]: {display_name} id: [{action.id}] priority: [{action.priority}] has conditions: [{action.has_conditions}] is axis: [{action.input_is_axis()}]  is button: [{action.input_is_button()}] enabled: [{action.enabled}]")








    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @collapsed.setter
    def collapsed(self, value: bool):
        self._collapsed = value

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

    def getActions(self, action_type_or_list : AbstractAction | list | tuple = None) -> list:
        ''' gets a list of all the actions in this container, of a particualr type if needed '''
        action_list = []
        action_type_list = []
        if not action_type_or_list is None:
            if hasattr(action_type_or_list,"__iter__"):
                action_type_list = action_type_or_list
            else:
                action_type_list = [action_type_or_list]
        for action_set in self.get_action_sets():
            for action in action_set:
                if action:
                    if action_type_list and not type(action) in action_type_list:
                        continue
                    action_list.append(action)

        return action_list



    def generateGuids(self):
        ''' called when GUIDs for this container need to be reset so they are unique, such as when pasting or importing. Actions and conditions IDs also need to be reset '''

        tracker = ConditionTracker()

        self._id = gremlin.util.get_guid() # unique GUID of this container

        for action_set in self.get_action_sets():
            for action in action_set:
                action.setId(gremlin.util.get_guid())
                if hasattr(action,"generateGuids"):
                    action.generateGuids() # action ID change

        if self.activation_condition:
            self.activation_condition.setId(gremlin.util.get_guid())
            for condition in self.activation_condition.conditions:
                data = tracker.getData(condition)
                condition.setId(gremlin.util.get_guid())
                if data:
                    new_data = gremlin.base_conditions.ConditionTrackerData(data.mode, data.input_item, self, condition, data.rule)
                    tracker.registerCondition(new_data)


            el = gremlin.event_handler.EventListener()
            el.condition_state_changed.emit(self)






    @property
    def input_item(self):
        ''' gets the associated input item for this container '''
        return self._get_input_item(self.parent)

    @property
    def has_conditions(self):
        ''' true if the container has conditions defined '''
        return self.activation_condition is not None and len(self.activation_condition.conditions) > 0

    def hasConditions(self):
        ''' true if the container has a condition or contains actions with conditions '''
        return self.has_conditions or self.has_action_conditions

    @property
    def has_action_conditions(self):
        ''' true if the container has action conditions defined '''
        for action_set in self.action_sets:
            if action_set:
                for action in action_set:
                    if action.has_conditions:
                        return True

        return False


    @property
    def condition_count(self)->int:
        ''' gets the count of container conditions currently defined '''
        if self.activation_condition is not None:
            return len(self.activation_condition.conditions)
        return 0



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
        if index > len(self.action_sets):
            while len(self.action_sets) <= index:
                self.action_sets.append([])
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


    def getFlatActionSetList(self, action_sets):
        ''' flattens the action set list if needed '''
        return self._flatten_list(action_sets)


    def _flatten_list(self, items):
        data = []
        if isinstance(items, list):
            for item in items:
                data.extend(self._flatten_list(item))
        else:
            data.append(items)

        return data




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


    def from_xml(self, node, data = None, extra_data = None):
        """Populates the instance with data from the given XML node.

        :param node the XML node to populate fields with
        """

        super().from_xml(node, data, extra_data)


        if "container_id" in node.attrib:
            self._id = node.get("container_id")


        comment = None
        if "comment" in node.attrib:
            comment = node.get("comment")
        if comment:
            self.comment = comment

        self._collapsed = safe_read(node,"collapsed",bool, False)

        # read container specific data 
        self._parse_xml(node, data, extra_data)
        # parse action seets for the container 
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

            node = self._generate_xml() # call derived container 
            if node is None:
                # not implemented by the derived class - create our own
                node = ElementTree.Element("container")

            assert node is not None,"Container: failed to get an container node generated"
            if __debug__:
                # ensure old containers no longer create action sets
                nodes = node.xpath("./action-set")
                assert len(nodes) == 0, "old container is still generating action set data"

            # generate the action sets
            self._generate_action_set_xml(node)

            node.set("container_id", self.id)

            if self.comment:
                node.set("comment", self.comment)

            node.set("collapsed", safe_format(self._collapsed, bool)) # collapsed state

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

    def _generate_xml(self) -> ElementTree.Element:
        ''' this should be overriden in derived containers to write custom data - default is do nothing '''
        node = ElementTree.Element("container")
        return node
    
    def _generate_action_set_xml(self, parent_node: ElementTree.Element):
        ''' generates the action set for the container, can be overriden '''
        for action_set in self.action_sets:
            node = action_set.to_xml()
            node.set("set-guid", write_guid(self._id))
            if self._description:
                node.set("set-description", html.escape(self._description))
            node.set("set-guid", write_guid(action_set.id))
            if action_set.description:
                node.set("set-description", html.escape(action_set.description))
        parent_node.append(node)

        
    
    def _parse_xml(self, node : ElementTree.Element, data=None, extra_data=None):
        ''' this should be implemented by derived containers to read custom data - default is do nothing'''
        pass
        




    def _parse_action_set_xml(self, node, data = None, extra_data = None):
        """Parses the XML content related to actions.

        :param node the XML node to process
        """

        if self.actionsetCustomParseCallback:
            # handles the complete load via custom callback if the container implements it
            self.actionsetCustomParseCallback(node, data, extra_data)
            return

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
                action_set = ActionSet()
            self._parse_action_xml(child, action_set, data, extra_data)
            if action_set:
                if index == len(self.action_sets):
                    self.action_sets.append([])
                self.action_sets[index] = action_set
            if not as_read:
                as_read = True
                if "set-guid" in child.attrib:
                    self.actions_sets.id = read_guid(child,"set-guid")
                if "set-description" in child.attrib:
                    self.action_sets.description = html.unescape(node.get("description"))
                
            index += 1





    def _parse_action_xml(self, node, action_set, input_item = None, extra_data = None, data = None):
        """Parses the XML content related to actions in an action-set.

        :param node the XML node to process
        :param action_set: storage for the processed action nodes (usually a list)
        :param input_item: input item this action is attached to
        :param extra_data: any data for extra XML processing
        :param data: data to set the loaded action to

        """
        action_name_map = ActionPlugins().tag_map
        config = gremlin.config.Configuration()

        # get the id
        if "id" in node.attrib:
            action_set.id = read_guid(node, "id")
            
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
            entry.from_xml(child, (input_item, self), extra_data) # pass input item, container as a tuple
            action_set.append(entry)
            if data is not None:
                entry.data = data



    def _parse_virtual_button_xml(self, node, data = None, extra_data = None):
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
                self.virtual_button.from_xml(vb_node, data, extra_data)

    def _parse_activation_condition_xml(self, node, data, extra_data = None):
        ''' load the container condition '''
        self.activation_condition = gremlin.actions.ActivationCondition([], ActivationRule.All)
        self.activation_condition.setContainer(self)
        input_item = data
        activation_node = gremlin.util.get_xml_child(node,"activation-condition")
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
                    syslog.warning(f"Action warning: {type(action).__name__} reports invalid - hardware {self.hardware_device_name} input: {self.hardware_input_type_name}  {self.hardware_input_id}")
                state = state & action_valid
        return state


    def is_valid_for_save(self):
        """ true if the container can be saved to a profile """
        state = self._is_container_valid()

        return state


    def latch_extra_inputs(self, container_condition_functors = None, action_condition_functors = None):
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



class ActionSet(list):
    ''' holds action set data with a data and ID attribute '''
    def __init__(self, data = None):
        self.data = data # any special tag to identify the action set
        self._id = uuid.uuid4() # unique ID of this action set
        

    @property
    def id(self):
        return self._id
    
    @id.setter
    def id(self, value):
        self._id = value

    def to_xml(self):
        ''' writes the actions in the action set out '''
        node = ElementTree.Element("action-set")
        node.set("guid", write_guid(self._id))
        for action in self:
            node.append(action.to_xml())
        return node
    
    def from_xml(self, node, container: AbstractContainer, input_item : InputItem = None, extra_data : dict = None, data = None):
        ''' reads an action set '''
        if node.tag == "action-set":
            if "guid" in node.attrib:
                self._id = read_guid(node, "guid")

        config = gremlin.config.Configuration()
        self.clear()

        # valid action names
        action_name_map = ActionPlugins().tag_map
        for child in node:
            if not child.tag in action_name_map:
                syslog.warning(f"ActionSet XML: don't know how to handle action: [{child.tag}]")
                continue

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
            entry.from_xml(child, (input_item, self), extra_data) # pass input item, container as a tuple
            self.append(entry)

            if data is not None:
                entry.data = data
    
    def __hash__(self):
        return hash(self._id)

class ActionSets(list):
    ''' holds a list of ActionSet objects for a container '''
    def __init__(self, container: AbstractContainer, description : str = None, data = None):
        self.data = data # any special tag to identify the action set
        self._id = uuid.uuid4() # unique ID of this action set
        assert isinstance(container, AbstractContainer),"Invalid container object"
        self._container = container
        self._input_item = self._container.input_item
        self._description = description
        assert isinstance(self._input_item, InputItem),"Invalid input item for container"

    def clear(self):
        super().clear()
        self._id = uuid.uuid4() # unique ID of this action set
        self._description = None

    @property
    def id(self):
        return self._id
    
    @property
    def description(self) -> str:
        return self._description
    @description.setter
    def description(self, value : str):
        self._description = value

    
    @id.setter
    def id(self, value):
        self._id = value

    def to_xml(self, parent_node : ElementTree.Element):
        ''' writes the actions in the action set out '''
        
        for action_set in self:
            node = action_set.to_xml()
            node.set("set-guid", write_guid(self._id))
            if self._description:
                node.set("set-description", html.escape(self._description))
            parent_node.append(node)
        return parent_node
    
    
    def from_xml(self, node, extra_data : dict = None, data = None):
        ''' reads container actions sets '''
        self.clear()
        set_read=False
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


    


class ActionSetView(AbstractView):
    ''' widget that displays actions defined in a container '''
    class Interactions(enum.Enum):
        """Enumeration of possible interactions."""
        Up = 1
        Down = 2
        Delete = 3
        Edit = 4
        Add = 5
        Count = 6
        Copy = 7 # copy to clipboard

    # Signal emitted when an interaction is triggered on an action
    interacted = Signal(Interactions)

    def __init__(
            self,
            profile : gremlin.base_profile.Profile,
            container : gremlin.input_item.AbstractContainer,
            model : ActionSetModel,
            label = None,
            view_type=ui_common.ContainerViewTypes.Action,
            icon = None,
            icon_size = 24,
            parent=None
    ):
        

        assert isinstance(profile, gremlin.base_profile.Profile), "invalid profile"
        assert isinstance(container, gremlin.input_item.AbstractContainer), "invalid container"
        assert isinstance(model, ActionSetModel),"invalid model"



        super().__init__(model= model, parent = parent)
        
        self.pushSuspended() # supend redraw


        self._redraw_lock = False
        self.profile = profile
        self.container = container # owning container

        self.has_edit_controls = False # assume no edit controls
        self.view_type = view_type
        self._main_layout = QtWidgets.QVBoxLayout(self)

        self._main_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine(color = gremlin.ui.ui_common.Color.grayColor()))
        self._main_layout.addWidget(QtWidgets.QLabel("ActionSetView:"))

        
        self.allowed_interactions = container.interaction_types
        self.label = label
        self._selected = False # true if the object is selected
        title = None

        if self.label:
            if icon:
                title = gremlin.ui.ui_common.QIconLabel(icon, icon_size = icon_size, text = f"{self.label} action:")
            else:
                title = QtWidgets.QLabel(f"{self.label} action:")
        elif icon:
            title = gremlin.ui.ui_common.QIconLabel(icon, icon_size = icon_size)

        if title:
            self._main_layout.addWidget(title)


        left_panel, left_layout = gremlin.ui.ui_common.getVContainer()
        right_panel, right_layout = gremlin.ui.ui_common.getVContainer()
        right_panel.setMaximumWidth(0) # use no space by default unless needed

        action_container, action_layout = gremlin.ui.ui_common.getGridContainer()
        action_layout.addWidget(left_panel, 0, 0)
        action_layout.addWidget(right_panel, 0, 1)

        add_action_container, add_action_layout = gremlin.ui.ui_common.getVContainer()

        widgets = [action_container, add_action_container]
        content_widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True)

        #self.collapsible_container.setContent(content_widget)
        self._main_layout.addWidget(content_widget)


        self.setObjectName(f"ActionSetView: {'n/a' if label is None else label}")

        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if verbose_ui: syslog.info(f"ActionSetView: create: {self.objectName()}")


        # Create group box contents
        self._action_widget, self._action_layout = gremlin.ui.ui_common.getVContainer()


        # Only show edit controls in the basic tab
        if self.view_type == ui_common.ContainerViewTypes.Action:
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

        if self.view_type == ui_common.ContainerViewTypes.Action and \
                container.get_device_type() != DeviceType.VJoy:
            input_type = None
            if hasattr(profile,"override_input_type"):
                # override specified
                input_type = container.override_input_type
            else:
                input_type = container.parent.getInputType()

            if input_type is None:
                input_type = container.input_item.get_input_type()

            self.action_selector = gremlin.ui.ui_common.ActionSelector(
                input_type,
                container.input_item
            )
            self.action_selector.inputItem = container.input_item
            self.action_selector.action_added.connect(self._add_action)
            self.action_selector.action_paste.connect(self._paste_action)
            widget = gremlin.ui.ui_common.getHContainer(self.action_selector, widget_only = True)
            add_action_layout.addWidget(widget)


        self._left_layout = left_layout
        self._right_layout = right_layout

        self._widget_map = {} # maps the model ID to the wrapper object created in the layout
        self._stacked_widget = QtWidgets.QStackedWidget()
        self._left_layout.addWidget(self._stacked_widget)


        self._blank_widget = QtWidgets.QLabel("Please add an action to this container.")
        widget = gremlin.ui.ui_common.getVContainer(self._blank_widget, widget_only = True)
        self._stacked_widget.addWidget(widget) # index 0 / page 1 of the stacked widget

        # widget and layout that holds the action widgets on page 2 of the stacked widget
        self._container_widget = None
        self._container_layout = None

        self._drawn_once = False # only load widgets on demand when a redraw is requested

        self.popSuspended() # supend redraw
        self.refreshModel()


    def setSelected(self, value:bool):
        ''' sets selected state'''
        if value and not self._selected:
            self._selected = True
            background_color = gremlin.ui.ui_common.Color.selectedDockTabBackgroundColor()
            self.setStyleSheet = f"background: {background_color};"
        elif not value and not self._selected:
            self._selected = False
            self.setStyleSheet("")

    def create_ui(self):
        ''' (re)creates the contents - content is displayed on page 2 of the stacked container  '''
        import gremlin.config
        import gremlin.joystick_handling


        push_cursor = False
        clipboard = gremlin.clipboard.Clipboard()
        clipboard.disable()

        try:
            if self._stacked_widget.count() == 2:
                # remove the prior content
                if not push_cursor:
                    gremlin.util.pushCursor()
                    push_cursor = True
                self._action_widget = None
                self._widget_map.clear()
                widget = self._stacked_widget.widget(1)
                self._stacked_widget.removeWidget(widget)
                widget.hide()
                if hasattr(widget,"_cleanup_ui"):
                    widget._cleanup_ui()
                widget.deleteLater()


            verbose = gremlin.config.Configuration().verbose_mode_ui

            self._container_widget, self._container_layout = gremlin.ui.ui_common.getVContainer()
            self._stacked_widget.addWidget(self._container_widget) # index 1

            self._action_widget = self._container_widget



            with QtCore.QSignalBlocker(self.model): # .data_changed.blocked():

                for model_index in range(self.model.rows()):
                    data = self.model.data(model_index)

                    # this will take a while potentially
                    if not push_cursor:
                        gremlin.util.pushCursor()
                        push_cursor = True

                    if verbose:
                        object_name = self.objectName()
                        device = gremlin.joystick_handling.getDevice(self.container.hardware_device_guid)
                        syslog.info(f"ActionSet: create {self.view_type.name} widget: device [{device.name}] input type: [{self.container.hardware_input_type.name}] input id: [{self.container.hardware_input_id}] start: {object_name} for action id [{data.id}]  ")

                    match self.view_type:
                        case ui_common.ContainerViewTypes.Action:

                            # create the action widget from the plugin
                            widget = data.widget(data)

                            widget.action_modified.connect(self.model.data_changed.emit)
                            wrapped_widget = BasicActionWrapper(widget)
                            wrapped_widget.closed.connect(self._create_closed_cb(widget))


                        case ui_common.ContainerViewTypes.Conditions:
                            # create the action widget from the plugin
                            widget = data.widget(data)
                            wrapped_widget = ConditionActionWrapper(widget)

                        case _:
                            syslog.error(f"Invalid view type in ActionSetview: don't know how to handle: {self.view_type}")
                            return

                    # save the reference widget
                    self._widget_map[data.id] = wrapped_widget
                    # add the new widget to the layout
                    self._container_layout.addWidget(wrapped_widget)
        finally:
            clipboard.enable()
            if push_cursor:
                gremlin.util.popCursor()


    def _show_blank(self):
        if self._stacked_widget.currentIndex() != 0:
            verbose = gremlin.config.Configuration().verbose_mode_ui
            if verbose: syslog.info(f"ActionSetView: show blank {self._input_display()}")
            self._stacked_widget.setCurrentIndex(0)

    def _show_content(self):
        if self._model.count() == 0:
            # no actions to show
            self._show_blank()
        else:
            if self._stacked_widget.currentIndex() != 1:
                verbose = gremlin.config.Configuration().verbose_mode_ui
                if verbose: syslog.info(f"ActionSetView: show content device {self._input_display()}")
                self._stacked_widget.setCurrentIndex(1)

    def _input_display(self) -> str:
        ''' display details for the mapped input '''
        return f"[device [{self.container.hardware_device_name}] type: [{self.container.hardware_input_type.name} input: [{self.container.hardware_input_id}] container: [{self.container.name}] id: [{self.container.id}]"


    def redraw(self, force = False):
        gremlin.util.InvokeUiMethod(self._redraw_ui, force) # ensure on UI thread

    def _redraw_ui(self, force = False):
        """Redraws the entire view.  must be on UI thread"""
        import gremlin.clipboard
        import gremlin.shared_state

        if not Shiboken.isValid(self):
            return

        if self.model is None:
            return

        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose:
            syslog.info(f"ActionSetView: redraw {self._input_display()}")




        if self._redraw_lock:
            return

        widget_count = len(self._widget_map)
        model_count = self.model.count()

        if not self._drawn_once or self.modelChanged() or widget_count != model_count:
            # redraw if first time, no container layout created, or model size is different
            if verbose: syslog.info(f"\tcreate UI for [{model_count}] actions")
            self.create_ui()
            self._drawn_once = True
            self._show_content()
            return # done

        try:
            self._redraw_lock = True

            clipboard = gremlin.clipboard.Clipboard()
            clipboard.disable()
            verbose = gremlin.config.Configuration().verbose_mode_ui

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

                if hasattr(widget,"redraw"):
                    widget.redraw()

            verbose = gremlin.config.Configuration().verbose_mode_ui

            # if verbose: syslog.info(f"ActionSet: redraw complete: {object_name}")

        finally:
            clipboard.enable()
            self._redraw_lock = False

            # gc.collect()

    def _add_action(self, action_name):
        import gremlin.plugin_manager
        import gremlin.base_profile
        import gremlin.ui.ui_common

        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()

            action = plugin_manager.get_class(action_name)(self.container)
            if action.singleton:
                input_item : InputItem = self.container.input_item
                if input_item.is_action:
                    gremlin.ui.ui_common.MessageBox(prompt=f"Unable to add [{action_name}].  The action cannot be added to a sub-container.")
                    return
                if input_item.hasAction(action_name):
                    gremlin.ui.ui_common.MessageBox(prompt=f"Unable to add: [{action_name}]. The action can only appear once per input.")
                    return


            self.model.add_action(action)




        finally:
            gremlin.util.popCursor()

    def _paste_action(self, action, container):
        ''' handles action paste operation '''


        try:
            gremlin.util.pushCursor()
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
                action_item = plugin_manager.duplicate(action,self.container)
                self.model.add_action(action_item)
        finally:
            gremlin.util.popCursor()


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
        except:
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
        if ActionSetView.Interactions.Up in self.allowed_interactions:
            self.control_move_up = QtWidgets.QPushButton(
                load_icon(f"{prefix}button_up.png"), ""
            )
            self.control_move_up.clicked.connect(
                lambda: self.interacted.emit(ActionSetView.Interactions.Up)
            )
            self.controls_layout.addWidget(self.control_move_up)
            self.has_edit_controls = True
        if ActionSetView.Interactions.Down in self.allowed_interactions:
            self.control_move_down = QtWidgets.QPushButton(
                load_icon(f"{prefix}button_down.png"), ""
            )
            self.control_move_down.clicked.connect(
                lambda: self.interacted.emit(ActionSetView.Interactions.Down)
            )
            self.controls_layout.addWidget(self.control_move_down)
            self.has_edit_controls = True
        if ActionSetView.Interactions.Delete in self.allowed_interactions:

            self.control_delete = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.interacted.emit(ActionSetView.Interactions.Delete), tooltip = "Delete Actions")
            self.controls_layout.addWidget(self.control_delete)
            self.has_edit_controls = True
        if ActionSetView.Interactions.Edit in self.allowed_interactions:
            self.control_edit = gremlin.ui.ui_common.Buttons.getEditWidget(callback = lambda: self.interacted.emit(ActionSetView.Interactions.Edit))
            self.controls_layout.addWidget(self.control_edit)
            self.has_edit_controls = True
        if ActionSetView.Interactions.Copy in self.allowed_interactions:
            self.control_edit = gremlin.ui.ui_common.Buttons.getCopyWidget(callback = lambda: self.interacted.emit(ActionSetView.Interactions.Copy))
            self.controls_layout.addWidget(self.control_edit)
            self.has_edit_controls = True


        self.controls_layout.addStretch(1)





class ContainerSelector(QtWidgets.QWidget):

    """Allows the selection of a container type."""

    # Signal emitted when a container type is selected
    container_added = Signal(str) # fires when a container is added (name of the container)
    container_copy =  Signal() # copy all containers
    container_paste = Signal(object, object) # paste containers (clipboard data, extra_data [optional])
    container_delete = Signal() # delete all containers
    container_from_template = Signal(dict) # load a new container from template, passes a dictionary (can be null) of data items
    container_to_template = Signal(object) # saves the mappings to a template, passes the input_item as the parameter

    def __init__(self, input_type, is_axis = False, data = None, parent=None):
        """Creates a new selector instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.input_type = input_type
        self.is_axis = is_axis
        self.data = data # input item


        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.addWidget(QtWidgets.QLabel("Container"))

        self.container_dropdown = gremlin.ui.ui_common.QDataComboBox()

        self.add_container_widget = gremlin.ui.ui_common.Buttons.getAddWidget(tooltip = "Adds the selected container", callback = self._add_container)

        # self.help_widget = gremlin.ui.ui_common.Buttons.getHelpWidget(callback = self._handle_help)

        self.save_template_widget =  gremlin.ui.ui_common.Buttons.getSaveWidget(callback =self._save_container_to_template,
                                                                                  tooltip = "Save mappings to template")

        self.load_template_widget =  gremlin.ui.ui_common.Buttons.getFolderWidget(callback =self._load_container_from_template,
                                                                                  tooltip = "Load mappings from template")

        self.data.lockedChanged.connect(self._handle_lock_changed)

        default_container = gremlin.config.Configuration().last_container
        self.container_dropdown.setCurrentText(default_container)
        self.container_dropdown.currentIndexChanged.connect(self._container_changed)


        # clipboard
        self.copy_button_widget = gremlin.ui.ui_common.Buttons.getCopyWidget(callback = self._copy_container, tooltip = "Copy container(s)")
        self.paste_button_widget = gremlin.ui.ui_common.Buttons.getPasteWidget(callback = self._paste_container, tooltip = "Paste container(s)")
        self.paste_button_widget.data = self.data # input item doing the paste

        # delete all containers
        self.delete_button =  gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = self._delete_container, tooltip = "Delete container(s)",)

        widgets = [self.container_dropdown,
                   self.add_container_widget,
                  ]

        widget = gremlin.ui.ui_common.getHContainer(widgets,widget_only = True)
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
        gremlin.util.InvokeUiMethod(self._handle_lock_changed_ui, input_item) # ensure on UI thread

    def _handle_lock_changed_ui(self, input_item):
        if Shiboken.isValid(self):
            unlocked = not input_item.locked
            self.load_template_widget.setEnabled(unlocked)
            self.add_container_widget.setEnabled(unlocked)
            self.paste_button_widget.setEnabled(unlocked)
            self.delete_button.setEnabled(unlocked)



    def refresh(self, input_item):
        ''' reloads the selector based on the input '''
        self.input_type = input_item.input_type
        with QtCore.QSignalBlocker(self.container_dropdown):
            self.container_dropdown.clear()
            for name in input_item.get_valid_container_list():
                self.container_dropdown.addItem(name )
            config = gremlin.config.Configuration()
            self.container_dropdown.setCurrentText(config.last_container)

        enabled = self.data and len(self.data.containers) > 0
        self.save_template_widget.setEnabled(enabled)

    def _last_container_changed(self, widget, name):
        gremlin.util.InvokeUiMethod(self._last_container_changed_ui, widget, name) # ensure on UI thread

    def _last_container_changed_ui(self, widget, name):
        if not Shiboken.isValid(self):
            return
        if widget != self.container_dropdown:
            with QtCore.QSignalBlocker(self.container_dropdown):
                self.container_dropdown.setCurrentText(name)

    def _container_changed(self):
        ''' remember the selection '''
        if not Shiboken.isValid(self):
            return
        name = self.container_dropdown.currentText()
        config = gremlin.config.Configuration()
        config.last_container = name
        if config.sync_last_selection:
            eh = gremlin.event_handler.EventHandler()
            eh.last_container_changed.emit(self.container_dropdown, name)

    def _valid_container_list(self, input_type : InputType):
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
        ''' help button '''
        import gremlin.base_profile
        container_name = self.container_dropdown.currentText()
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()

        input_item = self.data
        container = plugin_manager.get_class(container_name)(input_item)
        if hasattr(container,"hint"):
            hint = container.hint
        else:
            hint = gremlin.hints.hint.get(container.tag, "")
        if hint:
            gremlin.ui.ui_common.MessageBox(title = f"About the {container_name} container:", prompt = hint, width = 300, is_warning = False)


    def _clipboard_changed(self, clipboard):
        ''' handles paste button state based on clipboard data '''
        self.paste_button_widget.setEnabled(clipboard.is_container)
        ''' updates the paste button tooltip with the current clipboard contents'''
        if clipboard.is_container:
            self.paste_button_widget.setToolTip(f"Paste container ({clipboard.data.name})")
        else:
            self.paste_button_widget.setToolTip(f"Paste container (not available)")

    @QtCore.Slot()
    def _paste_container(self):
        ''' handle paste containern '''
        clipboard = Clipboard()
        widget = self.sender()
        input_item = widget.data
        extra_data = input_item.toExtraData()

        # validate the clipboard data is an action and is of the correct type for the input/container
        if clipboard.is_container:
            self.container_paste.emit(clipboard.data, extra_data)

    @QtCore.Slot()
    def _copy_container(self):
        ''' fires the copy container '''
        self.container_copy.emit()

    @QtCore.Slot()
    def _delete_container(self):
        ''' delete container '''
        self.container_delete.emit()

    @QtCore.Slot()
    def _save_container_to_template(self):
        ''' saves a complete mapping to a template '''
        input_item : InputItem = self.data
        self.container_to_template.emit(input_item)

    @QtCore.Slot()
    def _load_container_from_template(self):
        ''' loads container from template '''
        input_item : InputItem = self.data
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
class ConditionStateTracker():
    def __init__(self):
        self._cache = {} # maps input to condition tab
        self._widget_cache = {} # tracks the dock tab widget for the registered input_item for this mode
        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.connect(self._condition_state_changed)
        el.condition_changed.connect(self._condition_changed)
        el.container_delete.connect(self._container_delete)
        el.mapping_changed.connect(self._mapping_changed)
        self._icon_enabled = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color=gremlin.ui.ui_common.Color.activeColor())
        self._icon_disabled = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color=gremlin.ui.ui_common.Color.inactiveColor())

    def register(self, input_item, container, container_widget):
        ''' registers a condition tracker '''
        if not isinstance(container, gremlin.input_item.AbstractContainer):
            return

        dock_tab : QtWidgets.QTabWidget = container_widget.dock_tabs
        device_guid = input_item.device_guid
        mode =input_item.profile_mode # gremlin.shared_state.current_mode
        input_id = input_item.input_id
        if not device_guid in self._cache:
            self._cache[device_guid] = {}
        if not mode in self._cache[device_guid]:
            self._cache[device_guid][mode] = {}
        if not input_id in self._cache[device_guid][mode]:
            self._cache[device_guid][mode][input_id] = {}
        info = ConditionTrackerInfo(input_item, device_guid, input_id, container, container_widget)
        self._cache[device_guid][mode][input_id][container.id] = info

        enabled = info.input_item.hasConditions()
        self.set_condition_tab_state(dock_tab, enabled)

    def unregister(self, input_item, container):
        ''' unregisters a condition tracker '''
        if not isinstance(container, gremlin.input_item.AbstractContainer):
            return
        assert isinstance(container, gremlin.input_item.AbstractContainer)
        device_guid = input_item.device_guid
        mode = input_item.profile_mode # gremlin.shared_state.current_mode
        input_id = input_item.input_id
        if device_guid in self._cache:
            if mode in self._cache[device_guid]:
                if input_id in self._cache[device_guid][mode]:
                    if container.id in self._cache[device_guid][mode][input_id]:
                            del self._cache[device_guid][mode][input_id][container.id]


    @QtCore.Slot(object)
    def _condition_state_changed(self, container):
        if not isinstance(container, gremlin.input_item.AbstractContainer):
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
                        container_widget : AbstractContainerWidget = info.containerWidget
                        container_widget._update_condition_ui(container)
                        enabled = info.input_item.hasConditions()
                        dock_tabs = info.dock_tabs
                        self.set_condition_tab_state(dock_tabs, enabled)


    @QtCore.Slot(object, object)
    def _container_delete(self, input_item, container):
        if not isinstance(container, gremlin.input_item.AbstractContainer):
            return
        self.unregister(input_item, container)

    @QtCore.Slot()
    def _mapping_changed(self):
        ''' called when a mapping is changed '''
        # ensure condition "state" is updated following the change




    def set_condition_tab_state(self, dock_tabs : QtWidgets.QTabWidget, enabled : bool):
        ''' marks the condition tab used or not '''
        if Shiboken.isValid(dock_tabs):
            try:
                for i in range(dock_tabs.count()):
                    if dock_tabs.tabText(i) == "Conditions":
                        tb = dock_tabs.tabBar()
                        icon = self._icon_enabled if enabled else self._icon_disabled
                        tb.setTabIcon(i, icon)
                        break
            except:
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
        VirtualAxisButton: virtual_button.VirtualAxisButtonWidget,
        VirtualHatButton: virtual_button.VirtualHatButtonWidget
    }

    def __init__(self, input_item : InputItem, container : gremlin.input_item.AbstractContainer, parent=None):
        """Creates a new container widget object.

        :param profile_data the data the container handles
        :param parent the parent of the widget
        """

        import gremlin.hints
        import gremlin.event_handler
        import gremlin.ui.ui_common
        import gremlin.shared_state

        assert isinstance(input_item, InputItem)
        assert isinstance(container, AbstractContainer)
        super().__init__(parent)


        self._action_widget_map = {} # cache for action set [input_item] -> widget
        
        background_color = gremlin.ui.ui_common.Color.containerBackgroundColor()
        css = f"background-color:{background_color}"
        self.setStyleSheet(css)

        self._abstract_container_content_widget, self._abstract_container_content_layout = gremlin.ui.ui_common.getVContainer(no_stretch=True)

        el = gremlin.event_handler.EventListener()
        el.condition_redraw.connect(self._condition_redraw) # hook the condition redraw event so we can remove existing references to the UI going away on redraw
        el.condition_changed.connect(self._condition_changed) # hook condition changed so we can update the UI

        #el.ui_ready.connect(self._ui_ready)
        self._icon_enabled = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color=gremlin.ui.ui_common.Color.activeColor())
        self._icon_disabled = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color=gremlin.ui.ui_common.Color.inactiveColor())

        self.container = container
        self.input_item = input_item
        self.action_widgets = []

        mode = container.get_mode()
        if mode == gremlin.shared_state.master_mode:
            mode = "[Master]"
        if hasattr(container,"hint"):
            hint = container.hint
        else:
            hint = gremlin.hints.hint.get(self.container.tag, "")
        self._title_bar_widget = TitleBar(
            f"{self._get_window_title()} ({mode})",
            hint,
            self._container_remove,
            self._copy_container,
            data = container)

        self.title_frame_widget = gremlin.ui.ui_common.QBorderWidget()
        self.title_frame_widget.addWidget(self._title_bar_widget)

        # self.title_frame_widget.setMaximumWidth(600)
        self.title_frame_widget.setMinimumWidth(200)


        self.title_frame_widget.setBackgroundColor(gremlin.ui.ui_common.Color.containerBackgroundColor())
        self.collapsible_widget = gremlin.ui.ui_common.QCollapsible(title_widget = self.title_frame_widget)
        self.collapsible_widget.toggled.connect(self._handle_toggled)

        #self.setTitleBarWidget(self._title_bar_widget)
        self.setTitleBarWidget(self.collapsible_widget)


        # Create tab widget to display various UI controls in
        self.dock_tabs =  gremlin.ui.ui_common.QDataTab()
        # self.dock_tabs.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)

        background_color = gremlin.ui.ui_common.Color.selectedDockTabBackgroundColor()
        self.setStyleSheet = f"QDockWidget: {{ background-color: {background_color}; }}"

        self.dock_tabs.setStyleSheet(f"QTabBar::tab:selected {{ background-color: {background_color}; }}")

        self.dock_tabs.setTabPosition(QtWidgets.QTabWidget.East)

        self._abstract_container_content_layout.addWidget(self.dock_tabs)
        self.setWidget(self._abstract_container_content_widget)

        self.dock_tabs.data = self.container # associated the data tab with the container
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

        save_widget = gremlin.ui.ui_common.Buttons.getSaveWidget(tooltip="Save this container to a template", callback = self._save_template)

        #self._title_bar_widget.extra_layout.addWidget(open_widget)
        self._title_bar_widget.extra_layout.addWidget(save_widget)

        # this is for CONTAINER CONDITIONS only (Action conditions are handled elsewhere) - this hooks the condition state tab to the conditions added to the container
        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.connect(self._update_container_ui)

        self.activation_count_widget = None
        #el.condition_state_changed.emit(self.container)

        self._handle_lock_changed_ui(self.container.input_item)

        gremlin.util.singleShot(self._config_visible)

        if self.container.collapsed:
            self.collapsible_widget.collapse(False)
        else:
            self.collapsible_widget.expand(False)


        self.collapsible_widget.setContent(self._abstract_container_content_widget, own = False)

        el = gremlin.event_handler.EventListener()
        el.collapse_all_containers.connect(self._handle_collapse)
        el.expand_all_containers.connect(self._handle_expand)

        self._update_container_ui(self.container)





    @QtCore.Slot()
    def _handle_toggled(self):
        self.container.collapsed = self.collapsible_widget.isCollapsed()


    def _handle_collapse(self):
        gremlin.util.InvokeUiMethod(self._handle_collapse_ui)

    def _handle_collapse_ui(self):
        ''' collapse the container - ui thread'''
        self.collapsible_widget.collapse(False)

    def _handle_expand(self):
        gremlin.util.InvokeUiMethod(self._handle_expand_ui)

    def _handle_expand_ui(self):
        ''' expand the container - ui thread '''
        self.collapsible_widget.expand(False)

    def _config_visible(self):
        if not Shiboken.isValid(self):
            return
        config = gremlin.config.Configuration()
        self._title_bar_widget.setIdVisible(config.show_container_id)

    def _handle_lock_changed(self, input_item):
        ''' enable/disable based on lock state '''
        gremlin.util.InvokeUiMethod(self._handle_lock_changed_ui, input_item) # ensure on UI thread

    def _handle_lock_changed_ui(self, input_item):
        ''' enable/disable based on lock state '''
        if Shiboken.isValid(self):
            self.setEnabled(not input_item.locked)


    @QtCore.Slot()
    def _open_template(self):
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Container template",
            gremlin.shared_state.data_path,
            "XML files (*.xml)"
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

            except:
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
            "XML files (*.xml)"
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
                tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")
            except:
                syslog.error(f"Error writing template to: {fname}")
                return False
            return True



    @QtCore.Slot(object)
    def _update_container_ui(self, container):
        ''' update the condition icon in the RIGHT PANEL tab '''
        if not Shiboken.isValid(self.dock_tabs):
            return
        dock_tabs = self.dock_tabs
        if dock_tabs.data == container:
            # tracker = gremlin.base_conditions.ConditionTracker()
            #input_item = container.input_item
            # count = tracker.getInputItemConditionCount(input_item)
            enabled = container.hasConditions() # tracker.getContainerConditionCount(container) > 0
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

            except:
                pass

        if self.container == container and self.activation_condition_widget:
            self._update_counts()
            self.activation_condition_widget._update_conditions_ui()


    @QtCore.Slot(object, object)
    def _condition_changed(self, container):
        ''' called when conditions change '''
        if container.id == self.container.id and self.activation_condition_widget:
            self.activation_condition_widget._update_conditions_ui()

    @QtCore.Slot()
    def _condition_redraw(self, data):
        ''' occurs when a condition redraws '''

        if self.container == data:
            self._cleanup_ui()



    def _cleanup_ui(self):
        tracker = ConditionStateTracker()
        tracker.unregister(self.container.input_item, self.container)
        self.container.input_item.lockedChanged.disconnect(self._handle_lock_changed)



    def _create_action_tab(self):
        # Create root widget of the dock element
        self.action_tab_widget = QtWidgets.QWidget()
        # Create layout and place it inside the dock widget
        self.action_layout = QtWidgets.QVBoxLayout(self.action_tab_widget)

        # Create the actual UI
        self.dock_tabs.addTab(self.action_tab_widget, "Action")
        self._create(self.container)
        self._create_action_ui()


    def _create_activation_condition_tab(self):
        # Create widget to place inside the tab

        self.activation_condition_tab_widget = QtWidgets.QWidget()
        self.activation_condition_tab_layout = QtWidgets.QVBoxLayout(self.activation_condition_tab_widget)
        #self.activation_condition_tab_widget.setContentsMargins(0,0,0,0)
        #self.activation_condition_tab_layout.setContentsMargins(0,0,0,0)

        # Create container condition widget
        self.activation_condition_widget = ActivationConditionWidget(self.container)
        self.activation_condition_widget.activation_condition_modified.connect(self.container_modified.emit)

        # Put everything together
        self.activation_condition_tab_layout.addWidget(self.activation_condition_widget)
        self.condition_tab_index = self.dock_tabs.addTab(self.activation_condition_tab_widget,"Conditions")


        # conditions for the actions in the container
        self.action_condition_frame_widget = gremlin.ui.ui_common.QBoxFrame()
        self.action_condition_frame_widget.setContentsMargins(0,0,0,0)


        border_color = gremlin.ui.ui_common.Color.borderColor()
        background_color = gremlin.ui.ui_common.Color.actionBackgroundColor()
        css = f"#frame {{ border 1px solid {border_color}; border-top: none; background-color:{background_color} }}"
        self.action_condition_frame_widget.setStyleSheet(css)

        self.activation_condition_layout = QtWidgets.QVBoxLayout(self.action_condition_frame_widget)
        self.activation_condition_layout.setContentsMargins(0,0,0,0)

        self.activation_count_widget = QtWidgets.QLabel()
        self.activation_condition_layout.addWidget(self.activation_count_widget)

        self.activation_condition_tab_layout.addWidget(self.action_condition_frame_widget)

        # create the action container widget
        # widgets are placed in activation_condition_layout
        self._create_condition_ui()
        self.activation_condition_layout.addStretch()
        self.activation_condition_tab_layout.addStretch()

        self._update_counts()

        self._update_selected(self.dock_tabs.currentIndex())

    def _update_condition_ui(self):
        ''' updates the condition UI tab only '''
        self.activation_condition_widget._update_conditions_ui()


    def _update_counts(self):
        ''' refreshes counts '''

        if self.activation_count_widget:  # can get called before all is loaded
            if self.container:
                self.activation_count_widget.setText(f"Container conditions ({self.container.condition_count} found):")
            else:
                # not a container
                self.activation_count_widget.setText(f"Container conditions (N/A):")




    def _create_virtual_button_tab(self):
        # Return if nothing is to be done
        if not self.container.virtual_button:
            return

        # Create widget to place inside the tab
        self.virtual_button_tab_widget = QtWidgets.QWidget()
        self.virtual_button_layout = QtWidgets.QVBoxLayout(
            self.virtual_button_tab_widget
        )

        # Create actual virtual button UI
        self.virtual_button_widget =  AbstractContainerWidget.virtual_axis_to_widget[type(self.container.virtual_button)](self.container.virtual_button)

        # Put everything together
        self.virtual_button_layout.addWidget(self.virtual_button_widget)
        self.dock_tabs.addTab(self.virtual_button_tab_widget, "Virtual Button")

        self.virtual_button_layout.addStretch(10)

    def _select_tab(self, view_type):
        if view_type is None or self.dock_tabs is None:
            return

        try:
            tab_title = ui_common.ContainerViewTypes.to_string(view_type).title()
            for i in range(self.dock_tabs.count()):
                if self.dock_tabs.tabText(i) == tab_title:
                    self.dock_tabs.setCurrentIndex(i)

        except gremlin.error.GremlinError:
            return

    def _update_selected(self, index):
        ''' selection state for the tab page'''
        widget : ActionSetView
        for i, widget in enumerate(self.action_widgets):
            widget.setSelected(i == index)

    def _tab_changed(self, index):
        ''' called when a device tab is selected '''
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_device
        verbose_detailed = config.verbose_mode_details
        try:
            if verbose: syslog.info(f"Device change begin")
            tab_text = self.dock_tabs.tabText(index)
            self.container.current_view_type = ui_common.ContainerViewTypes.to_enum(tab_text.lower())
            self._update_selected(index)



        except gremlin.error.GremlinError:
            return
        finally:
            if verbose_detailed:
                syslog.info(f"Device change end")



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

    def _create_action_set_widget(self, action_set_data, label = None, view_type= ui_common.ContainerViewTypes.Action, icon = None, icon_size = 24):
        """Adds an action widget to the container.

        :param action_set_data: data of the actions which form the action set
        :param label the label:  to show in the title
        :param view_type visualization type
        :
        :return wrapped widget
        """

        assert_ui_thread, "not on ui thread"

        assert action_set_data is not None, "Action set data must be provided"


        # if action_set_data in self._action_widget_map:
        #     return self._action_widget_map[action_set_data]

        action_set_model = ActionSetModel(action_set_data)

        action_set_view = ActionSetView(
            profile = gremlin.shared_state.current_profile,
            container = self.container,
            model = action_set_model,
            label = label,
            view_type = view_type,
            icon = icon,
            icon_size = icon_size,
            parent = self
        )

        action_set_view.interacted.connect(lambda x: self._handle_interaction(action_set_view, x))

        # Store the view widget so we can use it for interactions later on
        self.action_widgets.append(action_set_view)

        # self._action_widget_map[action_set_data] = action_set_view

        return action_set_view

    def _container_remove(self):
        """Emits the closed event when this widget is being closed."""
        self.closed.emit(self)

    def redrawActionSets(self):
        ''' redraws the action set widgets '''
        for widget in self.action_widgets:
            if Shiboken.isValid(widget):
                widget.redraw()

    def _copy_container(self, _):
        """Emits the copy clipboard when the widget is being copied """
        clipboard = Clipboard()
        container = self.container

        # create a new container

        node = container.to_xml()


        xml = lxml.etree.tostring(node)
        encoder = ObjectEncoder(container, xml, container.name, EncoderType.Container)
        encoder.name = container.name
        clipboard.data = encoder
        #clipboard.data = self.container
        verbose = gremlin.config.Configuration().verbose
        if verbose: syslog.info(f"container {self.container.name} copied to clipboard")

    def _handle_interaction(self, widget, action):
        """Handles interaction with widgets inside the container.

        :param widget the widget on which the interaction is being carried out
        :param action the action being applied
        """
        raise gremlin.error.MissingImplementationError(
            "AbstractContainerWidget._handle_interaction not "
            "implemented in subclass"
        )

    def _create(self, action_data = None):
        # optional override by subclasses - called before _create_action_ui
        pass

    def _create_action_ui(self):
        """Creates the UI elements for the widget."""
        raise gremlin.error.MissingImplementationError(
            "AbstractContainerWidget._create_basic_ui not "
            "implemented in subclass"
        )

    def _create_condition_ui(self):
        """Creates the UI elements for the widget."""
        raise gremlin.error.MissingImplementationError(
            "AbstractContainerWidget._create_condition_ui not "
            "implemented in subclass"
        )

    def _update_condition_ui(self):
        ''' updates the condition UI for the widget '''
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

    def __init__(
            self,
            action_data,
            layout_type=QtWidgets.QVBoxLayout,
            parent=None
    ):
        """Creates a new instance.

        :param action_data the sub-classed AbstractAction instance
            associated with this specific action.
        :param layout_type type of layout to use for the widget
        :param parent parent widget
        """

        import gremlin.ui.ui_common
        import gremlin.util
        QtWidgets.QFrame.__init__(self, parent)

        css = f"background-color: {gremlin.ui.ui_common.Color.actionBackgroundColor()}"
        self.setStyleSheet(css)

        self.action_data = action_data

        self.main_layout = layout_type(self)

        eh = gremlin.event_handler.EventListener()
        # eh.profile_unload.connect(self._cleanup_ui)
        eh.action_delete.connect(self._action_delete)


        self._create(action_data)
        self._create_ui()
        self._populate_ui()

    @QtCore.Slot(object)
    def _action_delete(self, input_item, container, action):
        if self.action_data._id is not None and self.action_data._id == action._id and hasattr(self, "_cleanup_ui"):
            self._cleanup_ui()

    def _create(self, action_data = None):
        ''' called before create_UI if present '''
        pass


    def _create_ui(self):
        """Creates all the elements necessary for the widget."""
        raise gremlin.error.MissingImplementationError(
            "AbstractActionWidget._create_ui not implemented in subclass"
        )


    def _populate_ui(self):
        """Updates this widget's representation based on the provided
        AbstractAction instance.
        """
        raise gremlin.error.MissingImplementationError(
            "ActionWidget._populate_ui not implemented in subclass"
        )

    def _get_input_type(self):
        """Returns the input type this widget's action is associated with.

        :return InputType corresponding to this action
        """
        return self.action_data.hardware_input_type

    def _get_device_id(self):
        ''' returns the device ID of the input associated with the action '''
        return self.action_data.hardware_device_guid

    def _get_input_id(self):
        ''' gets the input id for the input associated with the action '''
        return self.action_data.hardware_input_id




    def _get_profile_root(self):
        """Returns the root of the entire profile.

        :return root Profile instance
        """

        return gremlin.shared_state.current_profile


    @property
    def is_running(self):
        ''' true if the profile is running '''
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

        size = 2 * self.style().pixelMetric(
            QtWidgets.QStyle.PM_DockWidgetTitleBarButtonMargin
        )



        if not self.icon().isNull():
            icon_size = self.style().pixelMetric(
                QtWidgets.QStyle.PM_SmallIconSize
            )
            sz = self.icon().actualSize(QtCore.QSize(icon_size, icon_size))
            size += max(sz.width(), sz.height())

        if size < 12: size = 12

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
            if self.isEnabled() \
                    and self.underMouse() \
                    and not self.isChecked() \
                    and not self.isDown():
                options.state |= QtWidgets.QStyle.State_Raised
            if self.isChecked():
                options.state |= QtWidgets.QStyle.State_On
            if self.isDown():
                options.state |= QtWidgets.QStyle.State_Sunken
            self.style().drawPrimitive(
                QtWidgets.QStyle.PE_PanelButtonTool,
                options,
                p,
                self
            )

        options.icon = self.icon()
        options.subControls = QtWidgets.QStyle.SC_None
        options.activeSubControls = QtWidgets.QStyle.SC_None
        options.features = QtWidgets.QStyleOptionToolButton.None_
        options.arrowType = QtCore.Qt.NoArrow
        size = self.style().pixelMetric(
            QtWidgets.QStyle.PM_SmallIconSize
        )
        if size < 12: size = 12
        options.iconSize = QtCore.QSize(size, size)
        self.style().drawComplexControl(
            QtWidgets.QStyle.CC_ToolButton, options, p, self
        )

        p.end()

        # syslog.info("title paint end")


class TitleBar(QtWidgets.QWidget):

    """Represents a titlebar for use with dock widgets.

    This titlebar behaves like the default DockWidget title bar with the
    exception that it has a "help" button which will display some information
    about the content of the widget.
    """

    def __init__(self, label, hint, close_callback, clipboard_cb = None, parent=None, data = None):
        """Creates a new instance.

        :param label the label of the title bar
        :param hint the hint to show if needed
        :param close_cb the function to call when closing the widget
        :param clipboard_cb the function to call for clipboard operations (optional)
        :param parent the parent of this widget
        """
        import gremlin.ui.ui_common
        import gremlin.shared_state
        import gremlin.config
        import gremlin.event_handler
        import gremlin.util
        super().__init__(parent)

        el = gremlin.event_handler.EventListener()
        el.show_container_id_changed.connect(self._show_container_id_changed)

        config = gremlin.config.Configuration()

        self._id_value = None

        self.hint = hint
        width = gremlin.ui.ui_common.get_text_width(label)
        if width > 200:
            fm =  QtGui.QFontMetrics(QtGui.QFont())
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
        pixmap_help = icon_help.pixmap(size, size) # load_pixmap(icon_help)
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

        pixmap_close = close_icon.pixmap(size,size) # load_pixmap("close.png")
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

        if data is not None and hasattr(data,"id") and config.show_container_id:
            self.id_widget = gremlin.ui.ui_common.QDataLineEdit(width=100)
            self.id_widget.setReadOnly(True)
            self.id_widget.data = data
            self.setIdValue(data.id)
        else:
            self.id_widget = None


        self.comment_widget = gremlin.ui.ui_common.QDataLineEdit()
        self.comment_widget.data = data
        if hasattr(data,"comment"):
            self.comment_widget.setText(data.comment)
        self.comment_widget.textChanged.connect(self._comment_changed)


        if hasattr(data,"priority"):
            self.priority_widget = gremlin.ui.ui_common.QIntLineEdit(data,min_range=0, max_range=1000,value = data.priority,chars=4)
            self.priority_widget.setToolTip("Execution priority.  Lower priority runs first.")
            self.priority_widget.valueChanged.connect(self._priority_changed)
            self.priority_container = gremlin.ui.ui_common.getHContainer(self.priority_widget,"Priority", widget_only = True, right_stretch=False, left_stretch=False)
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
            self.close_button
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

    def setIdVisible(self, visible : bool):
        if self.id_widget and Shiboken.isValid(self.id_widget):
            if visible:
                self.id_widget.setText(self._id_value)
            else:
                self.id_widget.setText(None)

    def setIdValue(self, value : str):
        self._id_value = value
        self._show_container_id_changed()

    def _show_container_id_changed(self):
        gremlin.util.InvokeUiMethod(self._show_container_id_changed_ui)

    def _show_container_id_changed_ui(self):
        ''' display/hide container Ids on config change'''
        config = gremlin.config.Configuration()
        visible = config.show_container_id
        self.setIdVisible(visible)


    @QtCore.Slot()
    def _comment_changed(self):
        ''' called when comment text is changed '''
        widget = self.sender()
        data = widget.data
        data.comment = widget.text()

    def _priority_changed(self, value):
        widget = self.sender()
        data = widget.data
        data.setPriority(value)


    def _show_hint(self):
        """Displays a hint, explaining the purpose of the action."""
        QtWidgets.QWhatsThis.showText(
            self.help_button.mapToGlobal(QtCore.QPoint(0, 10)),
            self.hint
        )

    def _delete_cb(self):
        ''' called on delete button '''
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
        if hasattr(action,"hint"):
            hint = action.hint
        else:
            hint = gremlin.hints.hint.get(action.tag, "")

        self._title_bar_widget = TitleBar(
            f"{action_widget.action_data.name} ({mode})",
            hint,
            self._remove,
            self._clipboard_copy,
            data = action_widget.action_data)


        self.title_frame_widget = gremlin.ui.ui_common.QBorderWidget()
        self.title_frame_widget.addWidget(self._title_bar_widget)


        self.title_frame_widget.setBackgroundColor(gremlin.ui.ui_common.Color.actionBackgroundColor())
        self.setTitleBarWidget(self.title_frame_widget)

        self.main_layout.addWidget(self.action_widget)

        gremlin.util.singleShot(self._config_visible)

    def _config_visible(self):
        if not Shiboken.isValid(self):
            return
        config = gremlin.config.Configuration()
        self._title_bar_widget.setIdVisible(config.show_container_id)

    def _remove(self):
        """Emits the closed event when this widget is being closed."""
        self.closed.emit(self)

    def _cleanup_ui(self):
        ''' cleans the object '''
        # if hasattr(self.action_widget, "_cleanup_ui"):
        #     self.action_widget._cleanup_ui()
        gremlin.util.clear_layout(self.main_layout)

    def _clipboard_copy(self, _):
        ''' clipboard copy event '''
        clipboard = Clipboard()
        action =  self.action_widget.action_data
        node = action.to_xml()
        xml = lxml.etree.tostring(node)
        encoded =  ObjectEncoder(action, xml, action.name, EncoderType.Action)
        #clipboard.data = action
        clipboard.data = encoded
        syslog.info(f"copy to clipboard: {action.name}")


class ConditionActionWrapper(AbstractActionWrapper):

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
            container.activation_condition = gremlin.base_conditions.BaseActivationCondition([],gremlin.types.ActivationRule.All)
            container.activation_condition.setContainer(container)

        self.condition_model = ConditionModel(
            container,
            container.activation_condition
        )
        self.condition_view = ConditionView()
        container.condition_view = self.condition_view
        self.condition_view.setContainer(container)
        self.condition_view.setModel(self.condition_model)
        self.condition_view.redraw()
        self.main_layout.addWidget(self.condition_view)
        # else:
        #     action_data.activation_condition = None




class ContainerModel(AbstractModel):

    """ container model for input mapping widget """

    def __init__(self, input_item, input_item_widget : InputItemMappingWidget = None, input_type: InputType = None, parent=None):
        """Creates a new instance.

        :param input_item:  the input item owning the container
        :param input_item_widget: the mapping widget displaying all containers
        :param input_type: the override input type if different from the input item configuration
        :param parent: the parent of this widget
        """
        super().__init__(parent)
        self._containers = input_item.containers
        self._input_item_widget = input_item_widget
        self._input_type = input_type if input_type is not None else input_item_widget._input_type

    @property
    def item_data(self) -> InputItemMappingWidget:
        ''' get the item data associated with this action container '''
        return self._input_item_widget

    @property
    def input_type(self) -> InputType:
        return self._input_type

    def rows(self):
        """Returns the number of rows in the model.

        :return number of rows in the model
        """
        return len(self._containers)
    
    def refresh(self, emit=True):
        ''' refresh the model '''
        pass
        

    def data(self, index):
        """Returns the data stored at the given location.

        :param index the location for which to return data
        :return the data stored at the requested location
        """
        assert len(self._containers) > index
        return self._containers[index]

    def add_container(self, container):
        """Adds a container to the model.

        :param container the container instance to be added
        """
        if not container in self._containers:
            self._containers.append(container)
            self.data_changed.emit()

    def remove_container(self, container):
        """Removes an existing container from the model.

        :param container the container instance to remove
        """
        el = gremlin.event_handler.EventListener()
        if container in self._containers:
            # notify actions that the container is closing
            for action_set in container.action_sets:
                if action_set:
                    for action in action_set:
                        if hasattr(action,"actionDeleted"):
                            action.actionDeleted()
                        el.action_delete.emit(self._input_item_widget, container, action)


            self._containers.remove(container)

            # self._input_item.remove_container(container)

            self.data_changed.emit()
            el.container_delete.emit(self.item_data, container)
            el.mapping_changed.emit(self.item_data)


    def remove_all_containers(self):
        """Removes an existing container from the model.

        :param container the container instance to remove
        """
        el = gremlin.event_handler.EventListener()
        container_list = [container for container in self._containers]
        for container in container_list:
            # notify actions that the container is closing
            for action_set in container.action_sets:
                for action in action_set:
                    # if hasattr(action, "_cleanup"):
                    #     action._cleanup()
                    el.action_delete.emit(self._input_item_widget, container, action)

            el.container_delete.emit(self.item_data, container)
            del self._containers[self._containers.index(container)]

        self.data_changed.emit()
        el.mapping_changed.emit(self.item_data)



class ContainerView(AbstractView):

    ''' widget that displays container mappings for an input item '''

    def __init__(self, input_item : AbstractInputItem, action_model : ActionSetModel, parent = None):
        """Creates a new view instance.

        :param parent the parent of the widget
        """

        if __debug__:
            if input_item is None and not isinstance(input_item, AbstractInputItem):
                raise ValueError("ContainerView requires an AbstractInputItem")
            if action_model is None and not isinstance(action_model, ActionSetModel):
                raise ValueError("ContainerView requires an ActionSetModel")
            
               
        super().__init__(model = action_model, parent=parent)

        self.pushSuspended() # suspend updates

        # Create required UI items
        self._main_layout = QtWidgets.QVBoxLayout(self)
        self._main_layout.setContentsMargins(0,0,0,0)
        self._redraw_lock = False
        self._deleted = False


        assert input_item is not None,"input item must be provided"
        assert action_model is not None, "action model must be provided"

        self._input_item = input_item
       

        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose: self._main_layout.addWidget(QtWidgets.QLabel("ContainerView:"))

        # use a two page widget - one that shows blank content, the other that shows the contents
        self._stacked_widget = QtWidgets.QStackedWidget()
        self._main_layout.addWidget(self._stacked_widget)

        # blank widget - index 0
        self._blank_widget = QtWidgets.QLabel("Please add a container or action.")
        widget = gremlin.ui.ui_common.getVContainer(self._blank_widget, widget_only=True)
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
        self._stacked_widget.addWidget(self._scroll_area) # index 1


        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose:
            syslog.info(f"create ContainerView [{input_item.debug_display if input_item else 'no input'}]")

        self._widget_map = {} # map of container ID to container widget

        self._show_blank()

        self._drawn_once = False # draw on demand only on first redraw

        self.popSuspended() # allow updates
        self.refreshModel()


    @property
    def input_item(self):
        ''' gets the associated input item for the container view '''
        return self._input_item


    def _cleanup_ui(self):
        ''' widget cleanup '''
        self._deleted = True
        self._clear_widgets()

    def _clear_widgets(self):
        ''' clears the scroll area widgets '''
        for widget in self._widget_map.values():
            widget.hide()
            self._scroll_layout.removeWidget(widget)
            if hasattr(widget,"_cleanup_ui"):
                widget._cleanup_ui()
            widget.deleteLater()
        self._widget_map.clear()
        self._show_blank()



    def create_ui(self):
        ''' creates the UI for the container contents '''
        import gremlin.util
        assert self._input_item is not None, "Input item not associated with container"
        assert self._model is not None, "Model must be associated with container"

        push_cursor = False
        try:

            with QtCore.QSignalBlocker(self.model):
                verbose = gremlin.config.Configuration().verbose_mode_ui

                # update the blank message based on the input
                item_data = self.input_item
                msg = f"Please add a container or action for {item_data.display_name}."
                self._blank_widget.setText(msg)

                self._clear_widgets() # remove current widgets and recreate

                container_count = self.model.rows()
                if verbose: syslog.info(f"ContainerView: found {container_count} to display")
                if container_count > 0:
                    # has containers
                    # display container widgets in the defined order
                    for model_index in range(container_count):
                        data = self.model.data(model_index)

                        # create the container widget and add to the layout
                        if not push_cursor:
                            push_cursor = True
                            gremlin.util.pushCursor()

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


        finally:
            if push_cursor:
                gremlin.util.popCursor()

    def setBlankMessage(self, message : str = None):
        ''' updates the blank message '''
        if self._blank_widget:
            self._blank_widget.setText(message or '')
            self._blank_widget.setVisible(message is not None)

    def _show_blank(self):
        if self._stacked_widget.currentIndex() != 0:
            verbose = gremlin.config.Configuration().verbose_mode_ui
            if verbose: syslog.info(f"ContainerView: show blank [{self._input_item.display_name if self._input_item else 'no input'}]")
            self._stacked_widget.setCurrentIndex(0)

    def _show_content(self):
        if self._model.count() == 0:
            # no containers to show
            self._show_blank()
        else:
            if self._stacked_widget.currentIndex() != 1:
                verbose = gremlin.config.Configuration().verbose_mode_ui
                if verbose: syslog.info(f"ContainerView: show content [{self._input_item.display_name if self._input_item else 'no input'}]")
                self._stacked_widget.setCurrentIndex(1)


    def redraw(self, force = False):
        gremlin.util.InvokeUiMethod(self._redraw_ui, force) # ensure on UI thread

    def _redraw_ui(self, force = False):
        """Redraws the entire view.  must be on UI thread"""
        import gremlin.util
        import gremlin.shared_state

        if not Shiboken.isValid(self):
            return
        
        if self._redraw_lock:
            return
        
        self._redraw_lock = True
        push_cursor = False
        try:

            verbose = gremlin.config.Configuration().verbose_mode_ui
            if verbose:
                syslog.info(f"ContainerView: redraw for [{self._input_item.display_name if self._input_item else 'no input'}]")

            widget_count = len(self._widget_map)
            model_count = self.model.count()

            if force or not self._drawn_once or self.modelChanged() or widget_count != model_count:
                if verbose: syslog.info(f"\tcreate UI for [{model_count}] containers")
                self.create_ui()
                self._drawn_once = True
                self._show_content()
                return # done

          


        
            with QtCore.QSignalBlocker(self.model):
                verbose = gremlin.config.Configuration().verbose_mode_ui
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
                    item_data = self.input_item
                    # device = gremlin.joystick_handling.getDevice(item_data.device_guid)
                    msg = f"Please add a container or action for {item_data.display_name}"
                    self._blank_widget.setText(msg)
                    self._show_blank()



        finally:
            assert len(self._widget_map) == self.model.count(), "ContainerView model and UI are not synchronized (mismatched items)"
            self._redraw_lock = False
            if push_cursor:
                gremlin.util.popCursor()


    def _create_closed_cb(self, widget):
        """Create callbacks to remove individual containers from the model.

        :param widget the container widget to be removed
        :return callback function to remove the provided widget from the
            model
        """

        return lambda: self._delete_container(widget.profile_data)

    def _delete_container(self, profile_data):
        ''' called when delete container button clicked'''
        gremlin.util.InvokeUiMethod(self._delete_container_ui, profile_data)

    def _delete_container_ui(self, profile_data):
        if gremlin.ui.ui_common.ConfirmBox("Delete this container?"):
            self.model.remove_container(profile_data)
            self._redraw_ui()





class InputItemMappingWidget(QtWidgets.QWidget):

    """ right panel widget that displays mappings  """

    # Signal emitted when the description changes
    description_changed = Signal(str) # indicates the description was changed
    description_clear = Signal() # clear the description field
    expired = Signal(object, QtWidgets.QWidget) # (key, widget) fires when the input mapping expires to notify the owner

    def __init__(self, input_item, input_type = None, object_name : str = None, spacer_height = 32, parent=None):
        """Creates a new object instance.

        :params:

        item_data =profile data associated with the item, can be none to display an empty box
        input_type = override input type if the input type is not that of the item_data (InputItem) - controls what containers/actions are available
        spacer_height = hack margin at top
        parent = the parent of this widget

        """
        super().__init__(parent)

        assert isinstance(input_item, InputItem), "invalid input type"
        assert input_item.input_type is not None, "input type cannot be derived be specified"

        if not input_type:
            input_type = input_item.input_type

        # remember the params for re-creation if needed
        self.params = (input_item, input_type, object_name, spacer_height, parent)

        assert input_item is not None,"Input Item must be provided"
        self._input_item = input_item
        self._input_type = input_type
        self._container_model = ContainerModel(input_item, self, input_type)
        

        # self.setObjectName(object_name if object_name else "(object name not provided)")
        self.id = gremlin.util.get_guid()
        self.setObjectName(object_name if object_name else f"InputItemMappingWidget#{input_item.display_name}")

        self._main_layout = QtWidgets.QVBoxLayout(self)

        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose: self._main_layout.addWidget(QtWidgets.QLabel("InputItemMappingWidget"))

        self._stacked_widget = QtWidgets.QStackedWidget()
        self._main_layout.addWidget(self._stacked_widget)

        self._container_widget = None

        # blank mapping widget
        self._blank_widget = QtWidgets.QLabel("Please select an input.")
        widget = gremlin.ui.ui_common.getVContainer(self._blank_widget, widget_only = True)
        widget.setContentsMargins(4,4,4,4)
        self._stacked_widget.addWidget(widget) # index 0

        self._spacer_height = spacer_height

        self._container_view = None

        self._deleted = False
        self._drawn_once = False
        
        self._show_blank()


    def fromParams(self, params) -> InputItemMappingWidget:
        ''' recreates the widget from self '''
        item_data, input_type, object_name, spacer_height, parent = params
        return InputItemMappingWidget(item_data, input_type, object_name, spacer_height, parent)



    def _mapping_changed(self, input_item : InputItem):
        ''' occurs when a device mapping changed through user interaction with the UI '''
        
        if input_item != self._input_item:
            # not ours
            return
        self.refresh()

        el = gremlin.event_handler.EventListener()
        el.update_action_icons.emit(input_item)





    def isBlank(self):
        ''' true if not associated with any data (blank widget)'''
        return self._input_item is None

    def _cleanup_ui(self):
        ''' called when widget is deleted '''
        self._deleted = True
        if self._container_view:
            self._container_view._cleanup_ui()
            self._container_view = None

    @property
    def deleted(self):
        return self._deleted
    
    @property
    def containerModel(self):
        ''' gets the mapping container model '''
        return self._container_model


    def refresh(self):
        ''' refreshes the current content with any changes '''
        

    @property
    def input_item(self) -> InputItem:
        ''' gets the associated item data '''
        return self._input_item

    def getInputItem(self): # InputItem:
        ''' gets the associated item data '''
        return self._input_item

    def setInputItem(self, input_item : InputItem):
        ''' sets the item data and redraws the control  '''


        if not Shiboken.isValid(self):
            return
        
        assert isinstance(input_item, InputItem), "invalid input type"
        assert input_item.input_type is not None, "input type cannot be derived be specified"

        if self._input_item != input_item:
            
            self._input_item = input_item
            self._input_type = input_item.input_type
            self._drawn_once = False # recreate the UI
            if input_item:
                self.profile_mode = self._input_item.profile_mode
                if hasattr(input_item,"input_type"):
                    self._input_type = input_item.input_type
                self._container_model = ContainerModel(input_item, self)

            else:
                # no item selected
                self._container_model = None
                self._show_blank()


    def _show_blank(self):
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose: syslog.info(f"InputItemMappingWidget: show blank")
        self._stacked_widget.setCurrentIndex(0)

    def _show_content(self):
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose: syslog.info(f"InputItemMappingWidget: show content: [{self._input_item.display_name}]")
        self._stacked_widget.setCurrentIndex(1)


    def create_ui(self):
        ''' creates the UI for this input mapping widget  '''

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_ui

        item_data : InputItem = self._input_item
        device = gremlin.joystick_handling.getDevice(item_data.device_guid)





        # delete any existing widget and re-create
        if self._stacked_widget.count() == 2:
            widget = self._stacked_widget.widget(1)
            self._container_view = None # free up the widget reference
            widget.hide()
            self._stacked_widget.removeWidget(widget)
            widget.deleteLater()
            item_data.mapping_widget_id = None # clear the reference ID


        widgets = []

        # main widget container
        container_widget, container_layout = gremlin.ui.ui_common.getVContainer()

        if not item_data.is_action:
            # description header
            self._create_description(container_layout)

        # container toolbar
        if item_data.device_type == DeviceType.VJoy:
            self._create_vjoy_dropdowns(container_layout)
        else:
            self._create_mapping_toolbar(container_layout)

        if verbose:
            msg = f"InputMappingWidget: [{device.name}]: input type: [{item_data.input_type.name}] input [{item_data.input_id}] {item_data.display_name}"
            syslog.info(msg)
            container_layout.addWidget(QtWidgets.QLabel(msg))


        if config.show_container_id:
            # debug container type
            widgets = []
            label = QtWidgets.QLabel(f"Mode: [{self._input_item.profile_mode if self._input_item.profile_mode else "N/A"}]")
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
                label_name = f"Input Type: N/A"


            label = QtWidgets.QLabel(label_name)
            widgets.append(label)

            if input_id is not None:
                width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
                line_edit = gremlin.ui.ui_common.QDataLineEdit()
                line_edit.setMinimumWidth(width)
                line_edit.setText(str(input_id) if isinstance(input_id, int) else gremlin.util.normalize_guid(input_id.id))
                line_edit.setReadOnly(True)
                widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Input Id:", widget_only = True)
                widgets.append(widget)

            widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)

            name = self.objectName()
            css = "background: green;"
            if not name:
                if item_data:
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


        container_view = ContainerView(self._input_item, self._container_model, parent = self)

        container_layout.addWidget(container_view)
        # reference the widget so we can update it
        self._container_view = container_view

        container_view.setContentsMargins(0,0,0,0)



        self._stacked_widget.addWidget(container_widget)


        item_data.mapping_widget_id = container_view.id # remember the ID of the container widget

        # setup the container widget reference
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        plugin_manager.set_widget(self._input_item, self)

        

    def getContainerView(self) -> ContainerView:
        ''' gets the container view '''
        return self._container_view


    def redraw(self, force = False):
        gremlin.util.InvokeUiMethod(self._redraw_ui, force)



    def _redraw_ui(self, force = False):


        assert self._input_item is not None, "invalid item data "
        

        if not self._drawn_once or self._container_view is None:
            if self._input_item is not None:
                self._drawn_once = True # indicate drawn at least once since creation
                self.create_ui()
                self._show_content()
                assert self._container_view is not None, "container view should be created after create_ui"
            return


        item_data : InputItem = self._input_item

        # widget_cache = gremlin.ui.ui_common.WidgetManager()

        if item_data is None:
            # show blank display
            self._stacked_widget.setCurrentIndex(0) # make visible
            return

        self._stacked_widget.setCurrentIndex(1)
        self._container_view._redraw_ui(force)




    def _add_action(self, action_name):
        """Adds a new action to the input item.

        :param action_name name of the action to be added
        """
        import container_plugins.basic
        import gremlin.plugin_manager
        import gremlin.ui.ui_common

        gremlin.util.pushCursor(True)

        assert self._input_item is not None,"InputItemMappingWidget: input id not set while adding action"

        try:

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

            if len(container.action_sets) > 0:
                self._container_model.add_container(container)

            # update the visual on action change
            self.redraw()

            # fire update events
            self._container_model.data_changed.emit()
            el = gremlin.event_handler.EventListener()
            el.mapping_changed.emit(self._input_item)
            self.notify_changed()

            # update icons
            el.update_action_icons.emit(self._input_item)


        finally:

            gremlin.util.popCursor()

    def notify_changed(self):
        ''' notifies the item has changed'''

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
        """ paste action to the input item """
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
            action_item = plugin_manager.duplicate(action, container )
        else:
            # nothing to do
            return

        # remap inputs
        action_item.update_inputs(self._input_item)
        container.add_action(action_item)

        if len(container.action_sets) > 0:
            self._container_model.add_container(container)
        self._container_model.data_changed.emit()

        eh = gremlin.event_handler.EventListener()
        eh.mapping_changed.emit(self._input_item)
        self.notify_changed()

    def _add_container(self, container_name):
        """Adds a new container to the input item.

        :param container_name name of the container to be added
        """

        gremlin.util.pushCursor(True)
        try:

            plugin_manager = gremlin.plugin_manager.ContainerPlugins()
            container = plugin_manager.get_class(container_name)(self._input_item)
            if hasattr(container, "action_model"):
                container.action_model = self._container_model
            self._container_model.add_container(container)
            plugin_manager.set_container_data(self._input_item, container)

            eh = gremlin.event_handler.EventListener()
            eh.mapping_changed.emit(self._input_item)

            self.redraw() # update
        finally:
            gremlin.util.popCursor()

        return container

    def _copy_container(self):
        ''' copies all containers to the clipboard '''
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
            syslog.info(f"multi container copied to clipboard")


    def _save_container_to_template(self, item):
        input_item : InputItem = item
        ''' saves a mapping set to a template '''
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(
            None,
            "Save template",
            gremlin.util.userprofile_path(),
            "XML files (*.xml)"
        )

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
                tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")
            except:
                syslog.error(f"Error writing template to: {fname}")
                return False
            return True

        return False





    def _load_container_from_template(self, extra_data = None):
        ''' loads a container from a template '''
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Container template",
            gremlin.util.userprofile_path(),
            "XML files (*.xml)"
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
                                new_container.generateGuids() # replace IDs to avoid conflicts
                                container_list.append(new_container)
                        else:
                            msg = f"Container {container_type.name} is not valid for the current input"
                            msg_list.append(msg)
                            syslog.warning(msg)


                if msg_list:
                    prompt = "".join((msg + "\n" for msg in msg_list))
                    gremlin.ui.ui_common.MessageBox(title="Load Template", prompt = prompt)

            except:
                pass
            if container_list:
                for new_container in container_list:
                    if hasattr(new_container, "action_model"):
                        new_container.action_model = self._container_model

                        plugin_manager.set_container_data(self._input_item, new_container)
                        self._container_model.add_container(new_container)



                el = gremlin.event_handler.EventListener()
                el.mapping_changed.emit(self._input_item)
                self.notify_changed()


    @QtCore.Slot(object)
    def _paste_container(self, container, extra_data = None):
        """Adds a new container to the input item.

        :param container container to be added
        """
        import gremlin.base_profile
        el = gremlin.event_handler.EventListener()
        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        container_list = []

        # tracker = gremlin.base_conditions.ConditionTracker()
        import_data = gremlin.base_profile.ProfileImportData()
        verbose = gremlin.config.Configuration().verbose

        if not extra_data:
            extra_data = {}
        extra_data["paste"] = True # indicate paste mode for xml readers

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
                        new_container.from_xml(node, data = self._input_item, extra_data = extra_data)
                        new_container.generateGuids()
                        if new_container.id in import_data.used_ids:
                            new_id = gremlin.util.get_guid()
                            if verbose: syslog.warning(f"PASTE: DUPLICATE ID:container {new_container.id} -> {new_id}")
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
                            new_container.from_xml(node, data = self._input_item, extra_data = extra_data)
                            new_container.generateGuids()
                            if new_container.id in import_data.used_ids:
                                new_id = gremlin.util.get_guid()
                                if verbose: syslog.warning(f"PASTE: DUPLICATE ID:container {new_container.id} -> {new_id}")
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
                    self._container_model.add_container(new_container)





            el.mapping_changed.emit(self._input_item)
            self.notify_changed()

            # update
            self.redraw()


        return container_list








    def _delete_container(self):
        ''' call to delete all containers '''
        if not self._input_item.containers:
            # nothing to do
            return
        # do a confirmation box just in case
        message_box = QtWidgets.QMessageBox()
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message_box.setText("This will remove the current container set and any actions.")
        message_box.setInformativeText("Are you sure?")
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Cancel |
            QtWidgets.QMessageBox.StandardButton.Ok
        )
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Cancel:
            return

        self._container_model.remove_all_containers()

        # update
        self.redraw()


    def _remove_container(self, container):
        """Removes an existing container from the InputItem.

        :param container the container instance to be removed
        """

        self._container_model.remove_container(container)



    def _create_description(self, layout : QtWidgets.QLayout):
        """Creates the description input for the input item."""
        self.description_layout = QtWidgets.QHBoxLayout()
        self.description_layout.addWidget(
            QtWidgets.QLabel("Mapping Description:")
        )
        self.description_field = QtWidgets.QLineEdit()
        self.description_field.setText(self._input_item.description)
        self.description_field.textChanged.connect(self._edit_description_cb)
        self.description_layout.addWidget(self.description_field)
        self.description_field.setReadOnly(self._input_item.descriptionReadOnly)
        self.description_clear_button = gremlin.ui.ui_common.Buttons.getEraserWidget(callback = self._delete_description_cb, tooltip="Reset description to default", width = 20, height = 20)
        self.description_layout.addWidget(self.description_clear_button)

        layout.addLayout(self.description_layout)


    def _create_mapping_toolbar(self, layout : QtWidgets.QLayout):
        """Creates a drop down selection with actions that can be
        added to the current input item.
        """
        import gremlin.input_item as input_item
        import gremlin.ui.ui_common as ui_common



        # check for an override for the inputs that can change types (such as OSC)
        input_type = self._input_item.getInputType()


        self.sync_widget = gremlin.ui.ui_common.Buttons.getListSyncWidget(callback = self._sync_list)

        self.action_selector = ui_common.ActionSelector(None, self._input_item)
        self.action_selector.inputItem = self._input_item
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.action_paste.connect(self._paste_action)

        self.container_selector = input_item.ContainerSelector(input_type, self._input_item.is_axis, data = self._input_item)

        self.container_selector.container_added.connect(self._add_container)
        self.container_selector.container_copy.connect(self._copy_container)
        self.container_selector.container_paste.connect(self._paste_container)

        self.container_selector.container_from_template.connect(self._load_container_from_template)
        self.container_selector.container_to_template.connect(self._save_container_to_template)
        self.container_selector.container_delete.connect(self._delete_container)
        self.always_execute = QtWidgets.QCheckBox("Always execute")
        self.always_execute.setToolTip("If enabled, the mapping continues to process triggers even if the profile is paused.")
        self.always_execute.setChecked(self._input_item.always_execute)
        self.always_execute.stateChanged.connect(self._always_execute_cb)

        self.collapse_all_widget = gremlin.ui.ui_common.Buttons.getCollapseAllWidget(callback = self._handle_collapse_all)
        self.expand_all_widget = gremlin.ui.ui_common.Buttons.getExpandAllWidget(callback = self._handle_expand_all)

        widgets = [
                   self.sync_widget,
                   self.action_selector,
                   self.container_selector,
                   self.collapse_all_widget,
                   self.expand_all_widget,
                   "|",
                   self.always_execute
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
        ''' collapses all containers '''
        el = gremlin.event_handler.EventListener()
        el.collapse_all_containers.emit()

    def _handle_expand_all(self):
        ''' expands all containers '''
        el = gremlin.event_handler.EventListener()
        el.expand_all_containers.emit()

    def updateSelectors(self, input_type, item_data):
        self.action_selector.refresh(input_type, item_data)
        self.container_selector.refresh(input_type, item_data)


    def _create_vjoy_dropdowns(self, layout : QtWidgets.QLayout):
        """Creates the action drop down selection for vJoy devices."""
        self.action_selector_widget = QtWidgets.QWidget()
        self.action_selector_layout = QtWidgets.QHBoxLayout(self.action_selector_widget)

        self.action_selector = gremlin.ui.ui_common.ActionSelector(
            gremlin.types.DeviceType.VJoy,
            None,
            parent = self.action_selector_widget,

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
        """ deletes the description text.

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
            entry = gremlin.plugin_manager.ActionPlugins().repository.get(
                "response-curve-ex",
                None
            )
            if entry is not None:
                action_names.append(entry.name)
            else:
                raise gremlin.error.GremlinError(
                    "Response curve plugin is missing"
                )
        else:
            for entry in gremlin.plugin_manager.ActionPlugins().repository.values():
                if self._input_item.input_type in entry.input_types:
                    action_names.append(entry.name)
        return sorted(action_names)

    def __eq__(self, other):
        if other is None:
            return False
        if hasattr(self,"item_data"):
            if not hasattr(other,"item_data"):
                return False
            if self._input_item and other.item_data:
                return self._input_item.callbackKey() == other.item_data.callbackKey()
        return self.id == other.id


class ConditionModel(AbstractModel):

    """Stores and represents condition data."""

    def __init__(self, action_data, condition_data, parent=None):
        """Creates a new model to store condition data.

        :param condition_data the condition data to represent
        :param parent the parent of this object
        """
        super().__init__(parent)
        self.condition_data = condition_data
        self.action_data = action_data
        self.input_item = None
        self.container = None
        if isinstance(action_data, gremlin.input_item.AbstractContainer):
            self.container = action_data
            self.input_item = action_data.input_item
        elif isinstance(action_data, gremlin.base_profile.AbstractAction):
            # find the container for the given action
            self.container = action_data.get_container()
        elif isinstance(action_data, gremlin.input_item.ConditionContainer):
            self.container = action_data.get_container()

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
        tracker = gremlin.base_conditions.ConditionTracker()
        mode = gremlin.shared_state.current_mode
        container = self.container
        input_item = self.input_item
        if input_item:
            data = gremlin.base_conditions.ConditionTrackerData(mode, input_item, container, condition, rule = gremlin.base_conditions.ActivationRule.All)
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
            tracker = gremlin.base_conditions.ConditionTracker()
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

@SingletonDecorator
class ConditionHelper:
    ''' helper class to manipulate conditions '''

    def __init__(self):
        el = gremlin.event_handler.EventListener()
        el.paste_condition.connect(self.paste_condition)
        el.copy_condition.connect(self.copy_condition)


    @QtCore.Slot(object, object)
    def paste_condition(self, container, oc):
        ''' pastes a condition to a container 
        
        :param container: the container object receiving the condition
        :param oc: object encoder data to paste
        
        '''
        from gremlin.clipboard import ObjectEncoder, EncoderType
        if isinstance(container, gremlin.base_profile.AbstractAction):
            input_item = container.parent.parent
        elif isinstance(container, gremlin.input_item.AbstractContainer):
            input_item = container.parent
        else:
            assert False,"Pasted container is not a valid container type - expected AbstractContainer or AbstractAction"

        if isinstance(oc, ObjectEncoder):
            
            data = (input_item, container) # (input item, container)
            tracker = gremlin.base_conditions.ConditionTracker()
            mode = gremlin.shared_state.edit_mode
            
            if oc.encoder_type == EncoderType.ActivationCondition:
                xml = oc.data
                node = lxml.etree.fromstring(xml)    
                if node.tag == 'activation-condition':
                    # temporary activation condition
                    activation_condition = gremlin.base_conditions.BaseActivationCondition([], gremlin.base_conditions.ActivationRule.All)
                    rule = container.activation_condition.rule
                    activation_condition.from_xml(node, data)
                    for condition in activation_condition.conditions:
                        condition.setId(gremlin.util.get_guid())
                        # add the condition to the existing container
                        container.activation_condition.conditions.append(condition)
                        item = gremlin.base_conditions.ConditionTrackerData(mode, input_item, container, condition, rule)
                        tracker.registerCondition(item)
                if isinstance(container, gremlin.base_profile.AbstractAction):
                    # we need to send the main container, not the action container for the update
                    self.update_condition_ui(container.parent)
                elif isinstance(container, gremlin.input_item.AbstractContainer):
                    self.update_condition_ui(container)        
        

            elif oc.encoder_type == EncoderType.Condition:
                xml = oc.data
                node = lxml.etree.fromstring(xml)
                if node.tag == 'condition':
                    condition_type = safe_read(node, "condition-type",str, "")
                    condition = gremlin.base_conditions.BaseActivationCondition.condition_lookup[condition_type]()
                    condition.from_xml(node, data)
                    condition.setId(gremlin.util.get_guid())

                    container.condition_view._add_condition(condition)
                    #container.activation_condition.conditions.append(condition)
                    condition.setOwner(container.activation_condition)
                    rule = container.activation_condition.rule
                    input_item = container.parent
                    item = gremlin.base_conditions.ConditionTrackerData(mode, input_item, container, condition, rule)
                    tracker.registerCondition(item)
                    if isinstance(container, gremlin.base_profile.AbstractAction):
                        # we need to send the main container, not the action container for the update
                        self.update_condition_ui(container.parent)
                    elif isinstance(container, gremlin.input_item.AbstractContainer):
                        self.update_condition_ui(container)
                    
                    
    def update_condition_ui(self, container):
        ''' asks the container UI to update '''

        el = gremlin.event_handler.EventListener()
        el.condition_changed.emit(container)

                    


    @QtCore.Slot(object)
    def copy_condition(self, condition):
        ''' copies a condition or activation condition to the clipboard  '''
        from gremlin.clipboard import Clipboard, ObjectEncoder, EncoderType
        clipboard = Clipboard()
        if isinstance(condition, gremlin.actions.ActivationCondition):
            node = condition.to_xml()
            xml = lxml.etree.tostring(node)
            encoded = ObjectEncoder(condition, xml, "activation-condition", EncoderType.ActivationCondition)
            clipboard.data = encoded
            syslog.info(f"activation condition copied to clipboard")
        elif isinstance(condition, gremlin.base_conditions.AbstractCondition):
            # regular condition
            node = condition.to_xml()
            xml = lxml.etree.tostring(node)
            encoded = ObjectEncoder(condition, xml, "condition", EncoderType.Condition)
            clipboard.data = encoded
            syslog.info(f"condition copied to clipboard")
        else:
            syslog.warning("Unable to copy data - unsupported condition type")


_condition_helper = ConditionHelper()
class AbstractConditionWidget(QtWidgets.QGroupBox):

    """Abstract class for condition ui widgets."""

    # Signal emitted when a condition is deleted
    #deleted = Signal(base_classes.AbstractCondition)
    deleted = Signal(object)

    def __init__(self, condition : gremlin.base_conditions.AbstractCondition, parent=None):
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

        self.grid_widget =  QtWidgets.QWidget()
        self.grid_layout =  QtWidgets.QGridLayout(self.grid_widget)

        self.ui_container_widget = QtWidgets.QWidget()
        self.ui_container_layout = QtWidgets.QGridLayout(self.ui_container_widget)


        self.key_label = QtWidgets.QLabel("")
        if self.condition.input_item:
            self.key_label.setText(f"<b>{self.condition.input_item.display_name}</b>")

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback = self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback = self._paste_condition)

        self.record_button_widget = gremlin.ui.ui_common.Buttons.getEditWidget(label = "Listen", callback = self._request_user_input)
        self.select_button_widget = gremlin.ui.ui_common.Buttons.getKeyboardWidget(label = "Select Keys", callback = self._select_user_input)
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.deleted.emit(self.condition), tooltip = "Delete condition")


        widgets,layout = gremlin.ui.ui_common.getHContainer([self.copy_widget,
                                                             self.paste_widget,
                                                             self.record_button_widget,
                                                             self.select_button_widget,
                                                             self.delete_button_widget,
                                                             ])


        self.comparison_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.comparison_dropdown.addItem("Pressed")
        self.comparison_dropdown.addItem("Released")
        if self.condition.comparison:self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.currentTextChanged.connect(self._comparison_changed_cb)



        self.grid_layout.addWidget(QtWidgets.QLabel("Activate if"), 0, 0)
        self.grid_layout.addWidget(self.key_label, 0, 1)
        self.grid_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.grid_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.grid_layout.addWidget(widgets, 0, 5)
        self.grid_layout.setColumnStretch(4,2)

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
        self.condition.comparison = \
            self.comparison_dropdown.currentText().lower()
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
            multi_keys=False
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
            150
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
        """ brings up the keyboard to select keys from """

        from gremlin.ui.virtual_keyboard import InputKeyboardDialog
        sequence = []
        if self.condition.input_item:
            sequence = self.condition.input_item.sequence
        self._keyboard_dialog = InputKeyboardDialog(sequence = sequence, parent = self, select_single = False, index = -1)
        self._keyboard_dialog.setModal(True)
        self._keyboard_dialog.accepted.connect(self._dialog_ok_cb)
        gremlin.util.centerDialog(self._keyboard_dialog)
        self._keyboard_dialog.showNormal()

    @QtCore.Slot()
    def _dialog_ok_cb(self):
        ''' callled when the dialog completes '''

        # grab a new data index as this is a new entry
        self._key_pressed_cb(self._keyboard_dialog.latched_key)


class ModeConditionWidget(AbstractConditionWidget):
    ''' mode condition UI '''
    def __init__(self, condition, parent=None):
        super().__init__(condition, parent)
        self.setTitle("Mode Condition")

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return

        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.deleted.emit(self.condition), tooltip = "Delete condition")
        widget = gremlin.ui.ui_common.getHContainer(self.delete_button_widget, left_stretch=True, widget_only = True)
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

        #if self.condition.comparison: self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.currentIndexChanged.connect(self._comparison_changed_cb)

        self.key_label = QtWidgets.QLabel("")



        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip("When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events.")
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)


        widgets = [
            "Activate if current mode is",
            self.comparison_dropdown,
            "to",
            self.mode_selector,
            self.ignore_release_widget
        ]

        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)
        self.main_layout.addWidget(widget)

        self.description_widget = QtWidgets.QLabel()
        widget = gremlin.ui.ui_common.getHContainer(["Description:", self.description_widget], widget_only = True)
        self.main_layout.addWidget(widget)

    def _handle_mode_changed(self, mode):
        self.condition.mode = mode

    @QtCore.Slot(bool)
    def _ignore_release_cb(self, checked : bool):
        self.condition.ignore_release = checked

    def setDescription(self, value):
        self.description_widget.setText(value if value else "n/a")


    @QtCore.Slot(str)
    def _comparison_changed_cb(self, text):
        ''' update comparison '''
        self.condition.comparison = self.comparison_dropdown.currentData()


class StateConditionWidget(AbstractConditionWidget):
    ''' state condition UI '''
    def __init__(self, condition, parent=None):
        super().__init__(condition, parent)
        self.setTitle("State Condition")

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.deleted.emit(self.condition), tooltip = "Delete condition")
        widget = gremlin.ui.ui_common.getHContainer(self.delete_button_widget, left_stretch=True, widget_only = True)
        self.main_layout.addWidget(widget)

        self.state_selector = gremlin.ui.ui_common.QDataComboBox()
        self.state_selector.currentIndexChanged.connect(self._state_changed)
        self.state_description_widget = QtWidgets.QLabel()
        widget = gremlin.ui.ui_common.getHContainer(["State:", self.state_selector], widget_only = True)
        self.main_layout.addWidget(widget)




        widget = gremlin.ui.ui_common.getHContainer(["Description:", self.state_description_widget], widget_only = True)
        self.main_layout.addWidget(widget)

        self.comparison_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.comparison_dropdown.addItem("Pressed")
        self.comparison_dropdown.addItem("Released")
        if self.condition.comparison:self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.currentTextChanged.connect(self._comparison_changed_cb)

        self.key_label = QtWidgets.QLabel("")

        self.grid_widget =  QtWidgets.QWidget()
        self.grid_layout =  QtWidgets.QGridLayout(self.grid_widget)
        self.grid_layout.addWidget(QtWidgets.QLabel("Activate if"), 0, 0)
        self.grid_layout.addWidget(self.key_label, 0, 1)
        self.grid_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.grid_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 4)

        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip("When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events.")
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        self.grid_layout.addWidget(self.ignore_release_widget, 0, 5)

        self.grid_layout.setColumnStretch(5,2)

        self.main_layout.addWidget(self.grid_widget)

        self.populate_selector()

    @QtCore.Slot(bool)
    def _ignore_release_cb(self, checked : bool):
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
        ''' updates the available states '''
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

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback = self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback = self._paste_condition)


        self.record_button_widget = gremlin.ui.ui_common.Buttons.getEditWidget(label = "Listen", callback = self._request_user_input)
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.deleted.emit(self.condition), tooltip = "Delete condition")


        widgets,layout = gremlin.ui.ui_common.getHContainer([self.copy_widget,
                                                             self.paste_widget,
                                                             self.record_button_widget,
                                                             self.delete_button_widget,
                                                             ])



        self.delay_widget = None

        self.main_layout.addWidget(QtWidgets.QLabel("Activate if:"))


        self.device_selector_widget = ui_common.QLimitedComboBox()
        self.device_selector_widget.currentIndexChanged.connect(self._device_selected)
        self.input_selector_widget = ui_common.QLimitedComboBox()
        self.input_selector_widget.currentIndexChanged.connect(self._input_selected)
        self.axis_repeater_widget = ui_common.QHookedProgressBar(orientation=QtCore.Qt.Orientation.Horizontal)
        self.axis_repeater_widget.valueChanged.connect(self._axis_value_changed)

        self.use_calibrated_input_widget = QtWidgets.QCheckBox("Use calibrated input")
        self.use_calibrated_input_widget.setToolTip("When enabled, the condition will use as input the calibrated data if found.  When disabled, the condition will use the raw input.")
        self.use_calibrated_input_widget.setChecked(self.condition.use_calibrated_data)
        self.use_calibrated_input_widget.clicked.connect(self._use_calibrated_input_changed)

        self.selector_container_widget = QtWidgets.QWidget()
        self.selector_container_layout = QtWidgets.QGridLayout(self.selector_container_widget)
        self.selector_container_layout.addWidget(QtWidgets.QLabel("Device:"), 0, 0)
        self.selector_container_layout.addWidget(self.device_selector_widget, 0, 1)
        self.selector_container_layout.addWidget(QtWidgets.QLabel("Input:"), 1, 0)
        self.selector_container_layout.addWidget(self.input_selector_widget, 1, 1)
        self.selector_container_layout.addWidget(self.axis_repeater_widget, 2, 1)

        self.selector_container_layout.addWidget(QtWidgets.QWidget(), 0, 2) # spacer column

        self.selector_container_layout.addWidget(widgets, 0, 4)
        self.selector_container_layout.setColumnStretch(2,2)

        self.range_status_widget = None

        self.ui_container_widget = QtWidgets.QWidget()
        self.ui_container_layout = QtWidgets.QGridLayout(self.ui_container_widget)

        self.options_container_widget = QtWidgets.QWidget()
        self.options_container_widget.setContentsMargins(0,0,0,0)
        self.options_container_layout = QtWidgets.QHBoxLayout(self.options_container_widget)
        self.options_container_layout.setContentsMargins(0,0,0,0)

        self.options_container_layout.addWidget(self.use_calibrated_input_widget)


        self.main_layout.addWidget(self.selector_container_widget)
        self.main_layout.addWidget(self.ui_container_widget)
        self.main_layout.addWidget(self.options_container_widget)

        self._populate_device_selector()
        self._populate_input_selector()



    @QtCore.Slot()
    def _device_selected(self):
        ''' device changed, update input list'''
        device = self.device_selector_widget.currentData()
        self.condition.device_guid = device.device_guid
        self._populate_input_selector()

    @QtCore.Slot()
    def _input_selected(self):

        device : gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()
        input_type,  input_id = self.input_selector_widget.currentData()
        self.condition.device_guid = device.device_guid
        self.condition.input_type = input_type
        self.condition.input_id =  input_id
        self.condition.device_name = device.name

        self._init_ui()


    def _populate_device_selector(self):
        device_guid = self.condition.device_guid
        current_index = None
        with QtCore.QSignalBlocker(self.device_selector_widget):
            self.device_selector_widget.clear()
            index = 0
            device : gremlin.joystick_handling.DeviceSummary
            for device in gremlin.joystick_handling.physical_devices():
                self.device_selector_widget.addItem(device.name, device)
                if current_index is None and device_guid and device.device_guid == device_guid:
                    current_index = index
                index +=1

            if current_index is not None:
                self.device_selector_widget.setCurrentIndex(current_index)

        # update condition for the selected device
        device : gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()
        self.condition.device_guid = device.device_guid

    def _populate_input_selector(self):
        import gremlin.util
        input_id = self.condition.input_id
        input_type = self.condition.input_type
        device : gremlin.joystick_handling.DeviceSummary = self.device_selector_widget.currentData()



        with QtCore.QSignalBlocker(self.input_selector_widget):
            self.input_selector_widget.clear()


            index = 0 # index of the entry
            current_index = None # index of the input to select

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
                if current_index is None and input_id == i + 1  and input_type == InputType.JoystickButton:
                    current_index = index
                index += 1



            # hats
            for i in range(device.hat_count):
                hat_name = f"Hat {i+1}"
                self.input_selector_widget.addItem(hat_name, (InputType.JoystickHat, i + 1))
                if current_index is None and input_id == i + 1 and input_type == InputType.JoystickHat:
                    current_index = index
                index+=1


            if current_index is not None:
                self.input_selector_widget.setCurrentIndex(current_index)

            input_type, input_id = self.input_selector_widget.currentData()
            self.condition.input_type = input_type
            self.condition.input_id = input_id

            # update the other UI based on input type
            self._init_ui()



    def _init_ui(self):
        input_type = self.condition.input_type
        self.axis_repeater_widget.hookDevice(self.condition.id, self.condition.device_guid, self.condition.input_type, self.condition.input_id)

        match input_type:
            case InputType.JoystickAxis:
                self._axis_ui()
                visible = True

            case InputType.JoystickButton:
                self._button_ui()

            case InputType.JoystickHat:
                self._hat_ui()

        self._update_ui()



    def _update_ui(self):
        ''' updates UI based on input type'''
        gremlin.util.assert_ui_thread()
        visible = False


        self.axis_repeater_widget.setVisible(visible)

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
        self.grab_high_widget.setIcon(load_icon("mdi.checkbox-blank-circle",qta_color = gremlin.ui.ui_common.Color.recordColor()))
        self.grab_high_widget.setMaximumWidth(20)
        self.grab_high_widget.clicked.connect(self._grab_high)
        self.grab_high_widget.setToolTip("Grab axis value")


        self.comparison_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.comparison_dropdown.addItem("Inside")
        self.comparison_dropdown.addItem("Outside")
        if not self.condition.comparison in ("inside","outside"):
            self.condition.comparison = "inside"

        self.comparison_dropdown.setCurrentText(self.condition.comparison.capitalize())
        self.comparison_dropdown.setCallback(self._comparison_changed_cb)

        self.range_status_widget = ui_common.QIconLabel()
        self.range_status_widget.setIcon("mdi.checkbox-marked-outline", color = gremlin.ui.ui_common.Color.activeColor())


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
        self.ui_container_layout.setColumnStretch(4,2)

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
        self.comparison_dropdown.addItem("Pressed","pressed")
        self.comparison_dropdown.addItem("Released","released")
        self.comparison_dropdown.addItem("Changed In","changedin")
        self.comparison_dropdown.addItem("Not Changed In","notchangedin")
        if not self.condition.comparison in ("pressed","released", "notchangedin","changedin"):
             self.condition.comparison = "pressed"
        index = self.comparison_dropdown.findData(self.condition.comparison)
        if index != -1:
            self.comparison_dropdown.setCurrentIndex(index)

        self.delay_widget = gremlin.ui.ui_common.QDelayWidget(self.condition.delay, is_seconds = True, show_shortcuts=False,label="Delay (s):", callback=self._handle_delay_changed)

        self.comparison_dropdown.setCallback(self._comparison_changed_cb)

        self.ui_container_layout.addWidget(
            QtWidgets.QLabel(
                f"<b>{self.condition.device_name} Button {self.condition.input_id:d}</b>"
                ),
            0,
            1
        )
        self.ui_container_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)

        widgets = [self.comparison_dropdown, self.delay_widget]
        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)
        self.ui_container_layout.addWidget(widget, 0, 3, alignment=QtCore.Qt.AlignLeft)

        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)

        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip("When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events.")
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        self.ui_container_layout.addWidget(self.ignore_release_widget, 0, 5)
        self.ui_container_layout.setColumnStretch(5,2)

        if not self.condition.comparison:
            # update the comparison
            self.condition.comparison = self.comparison_dropdown.currentText()

        self._update_ui()


    def _handle_delay_changed(self, value : float):
        gremlin.util.InvokeUiMethod(self._handle_delay_changed_ui, value)

    def _handle_delay_changed_ui(self, value : float):
        self.condition.delay = value

    def _hat_ui(self):
        """Creates the UI needed to configure a hat based condition."""
        gremlin.util.clear_layout(self.ui_container_layout)
        directions = [
            "Center", "North", "North East", "East", "South East",
            "South", "South West", "West", "North West"
        ]

        self.comparison_dropdown = ui_common.QHatSelectorComboBox()
        if not self.condition.comparison or not self.condition.comparison.capitalize() in directions:
            self.condition.comparison = "center"

        self.comparison_dropdown.setValue(self.condition.comparison)
        self.comparison_dropdown.valueChanged.connect(self._comparison_changed_cb)

        input_name = f"<b>{self.condition.device_name} Hat {self.condition.input_id}</b>"

        self.ui_container_layout.addWidget(QtWidgets.QLabel(input_name),0,1)
        self.ui_container_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.ui_container_layout.addWidget(self.comparison_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)
        self.ui_container_layout.addWidget(QtWidgets.QWidget(), 0, 4)




        self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
        self.ignore_release_widget.setToolTip("When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.")
        self.ignore_release_widget.setChecked(self.condition.ignore_release)
        self.ignore_release_widget.clicked.connect(self._ignore_release_cb)

        self.ui_container_layout.addWidget(self.ignore_release_widget,0,5)


        self.ui_container_layout.setColumnStretch(6,2)


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

        self.condition.device_name = gremlin.joystick_handling.device_name_from_guid(event.device_guid) # input_devices.JoystickProxy()[event.device_guid].name
        if event.event_type == InputType.JoystickAxis:
            self.condition.comparison = "inside"
        elif event.event_type == InputType.JoystickButton:
            self.condition.comparison = "pressed"
        elif event.event_type == InputType.JoystickHat:
            self.condition.comparison =  gremlin.util.hat_tuple_to_direction(event.value)
        self._create_ui()

    @QtCore.Slot()
    def _request_user_input(self):
        """Prompts the user for the input to bind to this item."""
        self.input_dialog = ui_common.InputListenerWidget(
            [
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat
            ],
            return_kb_event=False,
            multi_keys=False
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
            150
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
        self.lower_widget.setValue(self._axis_value()) # also updates condition_data


    @QtCore.Slot()
    def _grab_high(self):
        self.upper_widget.setValue(self._axis_value()) # also updates condition_data

    @QtCore.Slot(bool)
    def _use_calibrated_input_changed(self, checked : bool):
        self.condition.use_calibrated_data = checked
        self._update_range_state(self._axis_value())

    @QtCore.Slot(float, float)
    def _axis_value_changed(self, value : float, curved_value : float):
        self._update_range_state(value)

    def _update_range_state(self, value):
        gremlin.util.InvokeUiMethod(self._update_range_state_ui, value) # ensure UI thread

    def _update_range_state_ui(self, value):
        ''' updates the range flag based on the input value '''
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
                syslog.warning(
                    f"Invalid input type encountered: {self.condition.input_type}"
                )


            self._update_ui()

    @QtCore.Slot(bool)
    def _ignore_release_cb(self, checked : bool):
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

        self.grid_widget =  QtWidgets.QWidget()
        self.grid_layout =  QtWidgets.QGridLayout(self.grid_widget)

        self.vjoy_selector = ui_common.VJoySelector(
            self._modify_vjoy,
            [
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat
            ]
        )
        self.vjoy_selector.set_selection(
            self.condition.input_type,
            self.condition.vjoy_id,
            self.condition.input_id
        )

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback = self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback = self._paste_condition)

        self.record_button_widget = gremlin.ui.ui_common.Buttons.getEditWidget(label = "Listen", callback = self._request_user_input)
        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.deleted.emit(self.condition), tooltip="Delete condition")

        widget,layout = gremlin.ui.ui_common.getHContainer([self.copy_widget,
                                                            self.paste_widget,
                                                            self.record_button_widget,
                                                            self.delete_button_widget])


        self.ui_container_widget = QtWidgets.QWidget()
        self.ui_container_layout = QtWidgets.QGridLayout(self.ui_container_widget)

        label = QtWidgets.QLabel("Activate if:")
        label.setStyleSheet("background: none")


        is_trigger = True
        if self.condition.input_type == InputType.JoystickAxis:
            is_trigger = False # does not have a release mode
            self._axis_ui()
        elif self.condition.input_type == InputType.JoystickButton:
            self._button_ui()
        elif self.condition.input_type == InputType.JoystickHat:
            self._hat_ui()

        self.grid_layout.addWidget(self.vjoy_selector, 0, 0)
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 2)
        self.grid_layout.addWidget(widget, 0, 3)
        self.grid_layout.setColumnStretch(2,2)

        if is_trigger:
            self.ignore_release_widget = QtWidgets.QCheckBox("Apply condition on press only")
            self.ignore_release_widget.setToolTip("When enabled, the condition will only apply to a press (on) event and always succeed on a release (off) event.\nThis option only has meaning on press events.")
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
    def _ignore_release_cb(self, checked : bool):
        self.condition.ignore_release = checked


    @QtCore.Slot()
    def _request_user_input(self):
        self.input_dialog = ui_common.InputListenerWidget(
            [
                InputType.JoystickAxis,
                InputType.JoystickButton,
                InputType.JoystickHat
            ],
            return_kb_event=False,
            multi_keys=False,
            filter_func=self._filter_input
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
            150
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

        self.condition.device_name = gremlin.joystick_handling.device_name_from_guid(event.device_guid) # input_devices.JoystickProxy()[event.device_guid].name
        if event.event_type == InputType.JoystickAxis:
            self.condition.comparison = "inside"
        elif event.event_type == InputType.JoystickButton:
            self.condition.comparison = "pressed"
        elif event.event_type == InputType.JoystickHat:
            self.condition.comparison =  gremlin.util.hat_tuple_to_direction(event.value)
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
        if not self.condition.comparison in ("inside","outside"):
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
        if not self.condition.comparison in ("pressed","released"):
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
            "Center", "North", "North East", "East", "South East",
            "South", "South West", "West", "North West"
        ]
        self.comparison_widget = ui_common.QHatSelectorComboBox()
        if not self.condition.comparison or not self.condition.comparison.capitalize() in directions:
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
            if not self.condition.comparison in ("inside","outside"):
                self.condition.comparison = "inside"
        elif data["input_type"] == InputType.JoystickButton:
            if not self.condition.comparison in ("pressed","released"):
                self.condition.comparison = "pressed"
        elif data["input_type"] == InputType.JoystickHat:
            directions = ("center", "north", "north-east", "east", "south-east","south", "south-west", "west", "north-west")
            if not self.condition.comparison in directions:
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
            syslog.warning(
                f"Invalid input type encountered: {self.condition.input_type}"
            )


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
        self.grid_widget =  QtWidgets.QWidget()
        self.grid_layout =  QtWidgets.QGridLayout(self.grid_widget)

        self.copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget("Copy Condition", callback = self._copy_condition)
        self.paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget("Paste Condition", callback = self._paste_condition)


        self.state_dropdown = gremlin.ui.ui_common.QDataComboBox()
        self.state_dropdown.addItem("Pressed")
        self.state_dropdown.addItem("Released")
        if self.condition.comparison:
            self.state_dropdown.setCurrentText(self.condition.comparison.capitalize())
        else:
            self.condition.comparison = "pressed"
        self.state_dropdown.currentTextChanged.connect(self._state_selection_changed)

        self.delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = lambda: self.deleted.emit(self.condition))
        widgets,layout = gremlin.ui.ui_common.getHContainer([self.copy_widget,
                                                             self.paste_widget,
                                                             self.delete_button_widget,
                                                             ])

        self.grid_layout.addWidget(QtWidgets.QLabel("Activate when"), 0, 0)
        self.grid_layout.addWidget(QtWidgets.QLabel("<b>this input</b>"),0,1)
        self.grid_layout.addWidget(QtWidgets.QLabel("is"), 0, 2)
        self.grid_layout.addWidget(self.state_dropdown, 0, 3, alignment=QtCore.Qt.AlignLeft)


        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 4)
        self.grid_layout.addWidget(widgets, 0, 6)
        self.grid_layout.setColumnStretch(4,2)
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
        "Keyboard":
            [gremlin.base_conditions.BaseKeyboardCondition, KeyboardConditionWidget],
        "Joystick":
            [gremlin.base_conditions.BaseJoystickCondition, JoystickConditionWidget],
        "vJoy":
            [gremlin.base_conditions.BaseVJoyCondition, VJoyConditionWidget],
        "Action":
            [gremlin.base_conditions.BaseInputActionCondition, InputActionConditionWidget],
        "State":
            [gremlin.base_conditions.BaseStateCondition, StateConditionWidget],
        "Mode":
            [gremlin.base_conditions.BaseModeCondition, ModeConditionWidget]
    }

    # Mapping between application rule label and enumeration
    rules_map = {
        "All": gremlin.base_conditions.ActivationRule.All,
        "Any": gremlin.base_conditions.ActivationRule.Any,
        gremlin.base_conditions.ActivationRule.All: "All",
        gremlin.base_conditions.ActivationRule.Any: "Any"
    }

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._container = None
        self._redraw_lock = False

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
        self.condition_selector.addItem("Keyboard Condition", )
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
        self.condition_add_button = gremlin.ui.ui_common.Buttons.getAddWidget(tooltip = "Adds a condition", callback = self._add_condition)

        self.controls_layout.addWidget(self.condition_selector)
        self.controls_layout.addWidget(self.condition_add_button)

        self.help_button = gremlin.ui.ui_common.Buttons.getHelpWidget(callback = self._show_hint)
        self.controls_layout.addWidget(self.help_button)

        copy_widget = gremlin.ui.ui_common.Buttons.getCopyWidget(callback = self._copy_condition)
        paste_widget = gremlin.ui.ui_common.Buttons.getPasteWidget(callback = self._paste_condition)

        self.controls_layout.addWidget(copy_widget)
        self.controls_layout.addWidget(paste_widget)




    def setContainer(self, container):
        ''' sets the container '''
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

    def redraw(self):
        gremlin.util.InvokeUiMethod(self._redraw_ui) # ensure on UI thread

    def _redraw_ui(self):
        """Redraws the entire view.  must be on UI thread"""

        if not Shiboken.isValid(self):
            return
        if self._redraw_lock:
            return

        try:
            self._redraw_lock = True


            gremlin.util.clear_layout(self.conditions_layout)

            # create a widget for each condition
            lookup = {}
            for entry in ConditionView.condition_map.values():
                lookup[entry[0]] = entry[1]

            condition_count = self.model.rows()
            for i in range(condition_count):
                data = self.model.data(i)
                condition_widget = lookup[type(data)](data)
                condition_widget.deleted.connect(
                    lambda local_data: self.model.delete_condition(local_data)
                )
                self.conditions_layout.addWidget(condition_widget)

        finally:
            self._redraw_lock = False





    def _add_condition(self, condition = None):
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
        self.rule_selector.setCurrentText(
            ConditionView.rules_map[self.model.rule]
        )
        self.redraw()




    def _show_hint(self, state):
        """Shows a help message regarding the condition types.

        :param state push button state
        """
        QtWidgets.QWhatsThis.showText(
            self.help_button.mapToGlobal(QtCore.QPoint(0, 10)),
            gremlin.hints.hint.get("cond:types", "")
        )


class ActivationConditionWidget(QtWidgets.QWidget):

    """Widget displaying the UI used to configure activation conditions."""

    # Signal which is emitted whenever the widget's contents change
    activation_condition_modified = Signal()

    # Maps activation type name to index
    activation_type_to_index = {
        None: 0,
        "action": 1,
        "container": 2
    }

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data the profile data associated with the conditions
        :param parent the parent widget of this
        """
        super().__init__(parent)
        self.profile_data = profile_data
        #if isinstance(profile_data, gremlin.input_item.AbstractContainer) or isinstance(profile_data, gremlin.input_item.ConditionContainer):
        if isinstance(profile_data, gremlin.input_item.ConditionContainer):
            self.container = profile_data
        else:
            self.container = None

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self._create_ui()


        el = gremlin.event_handler.EventListener()
        el.condition_state_changed.connect(self._update_ui)



    def _create_ui(self):
        """Creates the configuration UI."""
        if not Shiboken.isValid(self):
            return
        self.help_button = gremlin.ui.ui_common.Buttons.getHelpWidget(callback = self._show_hint)

        self.controls_layout = QtWidgets.QHBoxLayout()
        self.controls_layout.setContentsMargins(0,0,0,0)
        self.controls_layout.addWidget(QtWidgets.QLabel("Conditions Definitions:"))
        self.controls_layout.addWidget(self.help_button)
        self.controls_layout.addStretch()



        self.main_layout.addLayout(self.controls_layout)

        # conditions for the container


        self.container_condition_frame_widget = gremlin.ui.ui_common.QBoxFrame()
        self.container_condition_frame_widget.setContentsMargins(0,0,0,0)
        self.container_condition_frame_layout = QtWidgets.QVBoxLayout(self.container_condition_frame_widget)


        self.activation_count_widget = QtWidgets.QLabel()
        self.container_condition_frame_layout.addWidget(self.activation_count_widget)
        self.container_condition_model = ConditionModel(self.profile_data, self.profile_data.activation_condition)


        self.container_condition_view = ConditionView()
        self.container_condition_view.setContainer(self.profile_data)
        self.container_condition_view.setModel(self.container_condition_model)

        self.container_condition_frame_layout.addWidget(self.container_condition_view)
        #self.container_condition_frame_layout.addStretch()


        self.main_layout.addWidget(self.container_condition_frame_widget)

        self.container_condition_view.redraw()

        self._update_counts()

    def _update_condition(self):
        gremlin.util.InvokeUiMethod(self._update_conditions_ui)

    @QtCore.Slot()
    def _update_conditions_ui(self):
        ''' updates the condition UI for this container '''
        #self.activation_condition_modified.emit()
        self.container_condition_view.redraw()



    @QtCore.Slot(object)
    def _update_ui(self, container):
       if self.container.id == container.id:
            self._update_counts()



    def _update_counts(self):
        ''' refreshes counts '''
        if not Shiboken.isValid(self.activation_count_widget):
            return
        if self.container:
            self.activation_count_widget.setText(f"Container action conditions ({self.container.condition_count} found):")
        else:
            # not a container
            self.activation_count_widget.setText(f"Conditions:")


    def _show_hint(self, state):
        """Shows a help message.

        :param state push button state
        """
        QtWidgets.QWhatsThis.showText(
            self.help_button.mapToGlobal(QtCore.QPoint(0, 10)),
            gremlin.hints.hint.get("cond:granularity", "")
        )




class BaseDeviceTabWidget(gremlin.ui.ui_common.QSplitTabWidget):

    """Widget used to display the input joystick device."""

    inputChanged = Signal(str, object, object) # indicates the input selection changed sends (device_guid string, input_type, input_id)

    def __init__(
            self,
            device : DeviceSummary,
            profile : gremlin.base_profile.Profile,
            mode : str,
            create_callback : Callable = None, # custom create widget handler if needed
            object_name = "Joystick",
            enable_filter = False , # true if the widget supports input item filters
            data = None,
        
            parent=None
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
        assert mode is not None and mode != '', "Mode cannot be None or empty"

        super().__init__(object_name= object_name,
                         device_guid = device.device_guid,
                         enable_filter=enable_filter,
                         parent = parent)

        self.device = device
        self.profile = profile
        self.profile.ensure_mode_exists(mode)
        self.device_profile = profile.getDevice(device.device_guid)
        
        self._input_item_list_view = None
        self._input_item_list_model = None
        self._input_item_mapping_widget = None # mapping display

        # last index selected, -1 means none
        self._last_selected_index = -1 # last selected input index in the input list view
        self._last_selected_input_item : InputItem = None # last selected input
        self._last_selected_widget : InputItemMappingWidget = None # last selected input mapping widget

        if __debug__ and create_callback: assert callable(create_callback),"invalid create widget callback"
        self._create_widget_callback = create_callback
        self.addRegisteredWidgetCallback(self._handle_widget_registered)
        self.addUnregisteredWidgetCallback(self._handle_widget_unregistered)

        # global event handling
        el = gremlin.event_handler.EventListener()
        el.tab_selected.connect(self._handle_tab_changed)
        el.jump_to_mapped_input.connect(self._handle_jump_to_mapped_input)
        if self.filtersEnabled:
            el.input_filtered_change.connect(self._handle_input_filter_changed)

    def _cleanup_ui(self):
        el = gremlin.event_handler.EventListener()

        # el.edit_mode_changed.disconnect(self._handle_edit_mode_changed)
        # el.config_changed.disconnect(self._config_changed_cb)
        el.lock_inputs.disconnect(self._handle_lock_inputs)
        el.unlock_inputs.disconnect(self._handle_unlock_inputs)

        el.jump_to_mapped_input.disconnect(self._handle_jump_to_mapped_input)
        if self.filtersEnabled:
            el.input_filtered_change.disconnect(self._handle_input_filter_changed)


        self.inputItemListView.setParent(None)
        self.inputItemListView.deleteLater()

    def _handle_create_widget(self, input_item : InputItem):
        index = self.inputItemListView.indexOf(input_item)
        assert index != -1,"input item is not in the list"
        
        prefix = input_item.input_type.name
        widget = InputItemMappingWidget(input_item = input_item, object_name=f"{prefix}: {input_item.display_name}")
        device_name = gremlin.joystick_handling.device_name_from_guid(self.device_guid)
        widget.setObjectName(f"InputItemConfig for device {device_name} index: {index} ")
        widget.description_changed.connect(lambda x: self._description_changed_cb(index, x))
        widget.description_clear.connect(lambda: self._description_clear_cb(index,widget))
        return widget 
    
    def _description_changed_cb(self, index, text):
        ''' called when the description text of the widget changes to update the description on the input item

        :param: index = the index of the input widget to update with the new text

        '''
        widget = self.inputItemListView.widget(index)
        if widget:
            widget.data.description = text
            widget.setDescription(text)
        else:
            syslog.error(f"set description (joystick input) failed: index: [{index}] does not exist.")

    def _description_clear_cb(self, index, widget):
        ''' delete description entry '''
        with QtCore.QSignalBlocker(widget.description_field):
            widget.description_field.setText('')
        item_widget = self.inputItemListView.widget(index)
        item_widget.data.description = None
        item_widget.setDescription('')


    def _handle_tab_changed(self, device_guid):
        ''' occurs when a tab is made visible '''
        pass

    def _handle_widget_registered(self, key, index, widget):
        ''' called when a mapping widget is added '''

    def _handle_widget_unregistered(self, key, index, widget):
        ''' called when a mapping widget is removed '''
        if self._last_selected_widget == widget:
            # remove the reference
            self._last_selected_widget = None

    def _handle_jump_to_mapped_input(self):
        gremlin.util.InvokeUiMethod(self._handle_jump_to_mapped_input_ui)

    def _handle_jump_to_mapped_input_ui(self):
        ''' jumps to the first mapped input '''
        if Shiboken.isValid(self):
            for input_item in self.inputItemListModel.getFilteredItems():
                if input_item.hasContainers:
                    index = self.inputItemListModel.indexOfInputItem(input_item)
                    self._handle_input_item_selected(index)
                    break

    def _handle_input_filter_changed(self, device_guid):
        ''' called when input filter is changed '''
        if not gremlin.util.compare_guid(device_guid, self.device_guid) or self._input_dirty:
            # not ours
            return

        verbose = gremlin.config.Configuration().verbose_mode_filter
        if verbose:
            device = gremlin.joystick_handling.getDevice(device_guid)
            syslog.info(f"FILTER: [{device.name}] inputs marked dirty")
        
        self.inputItemListModel.refresh() # indicate the list should be refreshed because it has changed

    def _handle_lock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_lock_inputs_ui, data) # ensure on UI thread

    def _handle_unlock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_unlock_inputs_ui, data) # ensure on UI thread

    def _handle_lock_inputs_ui(self, data):
        ''' lock all inputs event'''
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = True
            self.setUpdatesEnabled(True)

    def _handle_unlock_inputs_ui(self, data):
        ''' unlock all inputs event '''
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = False
            self.setUpdatesEnabled(True)


    

    @property 
    def inputItemListModel(self) -> InputItemListModel:
        ''' input item model for the mapping widget (left tab)'''
        return self._input_item_list_model
    
    @inputItemListModel.setter
    def inputItemListModel(self, value : InputItemListModel):
        self._input_item_list_model = value       
        
 

    @property
    def inputItemListView(self) -> InputItemListView:
        ''' input item list view for the mapping widget (left tab)'''
        return self._input_item_list_view
    
    @inputItemListView.setter
    def inputItemListView(self, value : InputItemListView):
        if self._input_item_list_view != value:
            if self._input_item_list_view:
                self._input_item_list_view.removeCallback(self._handle_input_item_selected) # unhook selected callback
                
        self._input_item_list_view = value
        if value is not None:
            self._input_item_list_view.addCallback(self._handle_input_item_selected) # hook selected callback - called whenever an input is selected
   


    def setLastSelectedIndex(self, value : int):
        self._last_selected_index = value

    def setLastSelectedInputItem(self, input_item: InputItem):
        self._last_selected_input_item = input_item

    def setLastSelectedWidget(self, widget : InputItemMappingWidget):
        self._last_selected_widget = widget

    @property
    def lastSelectedInputItem(self) -> InputItem:
        return self._last_selected_input_item

    @property
    def lastSelectedIndex(self) -> int:
        ''' index of the last selected list view input '''
        return self._last_selected_index
    
    @property
    def lastSelectedWidget(self) -> InputItemMappingWidget:
        return self._last_selected_widget
    
    def getSelectedItem(self) -> gremlin.base_profile.input_item:
        ''' gets the last selected input item'''
        return self._last_selected_input_item
    
    def indexOf(self, input_item : InputItem) -> int:
        ''' gets the index of the input item if in the list, -1 if not found'''
        return self._input_item_list_view.indexOf(input_item)

    
    @property
    def inputItemCount(self) -> int:
        ''' number of inputs in the device '''
        return self._input_item_list_model.rows()

    @property
    def inputWidgetCount(self) -> int:
        ''' number of input widgets currently in the device '''
        return len(self._input_item_list_view)
    
    
    def getInputItemMappingWidget(self, input_item : InputItem) -> InputItemMappingWidget:
        ''' gets the mapping widget associated with the input item - the widget is created if needed '''
        if input_item:
            key = self.getInputItemWidgetKey(input_item)
            widget = self.getRegisteredWidget(key)
            if widget is None:
                gremlin.util.pushCursor()
                if self._create_widget_callback:
                    widget = self._create_widget_callback(input_item)
                else:
                    widget = self._handle_create_widget(input_item)
                gremlin.util.popCursor()
            assert widget is not None, f"failed to get a widget for [{input_item.display_name}]"
            return widget
        return None
    
    def getInputItemMappingWidgetAt(self, index : int) -> InputItemMappingWidget:
        ''' gets the mapping widget for an input item at the given index '''
        return self.getInputItemMappingWidget(self.getInputItemAt(index))
        
    def getInputWidget(self, input_item : InputItem) -> InputItemWidget:
        ''' gets the input widget for a given input item '''
        return self._input_item_list_view.getWidgetForInputItem(input_item)
    
    def getInputWidgetAt(self, index : int) -> InputItemWidget:
        ''' gets the input widget by index '''
        return self._input_item_list_view.getWidgetAt(index)
    
    def getFilteredInputItemAt(self, index : int):
        ''' gets the input item as the specified position '''
        return self._input_item_list_model.getFilteredInputItemAt(index)
    
    def getInputItemAt(self, index : int):
        ''' gets the input item at the specified postion - unfiltered '''
        return self._input_item_list_model.getInputItemAt(index)

        


    def selectInputItemMappingWidget(self, input_item : InputItem) -> InputItemMappingWidget:
        ''' activates the mapping widget for the given input item
            the widget is created if it doesn't exist or needs to be recreated
        '''
        if input_item:
            if input_item != self._last_selected_input_item:
                widget = self.getInputItemMappingWidget(input_item)
                assert widget is not None, f"failed to get a widget for [{input_item.display_name}]"
                key = self.getWidgetKeyForWidget(widget)
                self.registerWidget(key, widget)
                self.selectRegisteredWidget(widget) # make it visible
                self.setLastSelectedInputItem(input_item)
                self.setLastSelectedWidget(widget)
                widget.redraw() # update if needed
                self._input_item_mapping_widget = widget
            
        return self._last_selected_widget
    
    def refresh(self, emit = False):
        gremlin.util.InvokeUiMethod(self._refresh_ui, emit) # ensure on UI thread

    def _refresh_ui(self, force_update = False, emit = False):
        """Refreshes the current selection, ensuring proper synchronization. - ensure on UI thread """

        if gremlin.shared_state.is_redraw_suspended():
            return
        
        index = self.inputItemListView.current_index
        if index == -1:
            # nothing selected
            if self.inputItemListModel.filteredCount():
                # has something to display
                index = 0 # pick the first one
        
        self.__handle_select_input_index_ui(index, force = force_update, emit = emit)


    def selectInputItem(self, input_item : InputItem, force = False, emit = True):
        ''' selects a specific input item '''
        index = self.inputItemListView.getInputItemIndex(input_item)
        if index != -1:
            gremlin.util.InvokeUiMethod(self._handle_input_item_selected, index, force, emit)    

    def selectInputItemIndex(self, index, force : bool = False, emit : bool = True):
        gremlin.util.InvokeUiMethod(self.__handle_select_input_index_ui, index, force, emit)

    def __handle_select_input_index_ui(self, index, force : bool = False, emit : bool = True):
        ''' selects an input by index '''
        verbose = gremlin.config.Configuration().verbose_mode_ui
        
        if index != -1:
            if verbose: syslog.info(f"DeviceWidget: select input index [{index}]")
            widget = self.getInputWidgetAt(index)
            if not widget:
                self.inputItemListView.redraw()
            widget = self.getInputWidgetAt(index)
            if widget and not widget.selected:
                # widget found and not already selected
                widget.setSelected(True, emit)
        else:
            if verbose: syslog.info(f"DeviceWidget: select input index - nothing to select")




    def _handle_input_item_selected(self, old_widget : InputItemWidget, new_widget : InputItemWidget):
        gremlin.util.InvokeUiMethod(self._handle_input_item_selected_ui, old_widget, new_widget)

    def _handle_input_item_selected_ui(self, old_widget : InputItemWidget, widget : InputItemWidget, emit : bool = False):
        ''' input item selection handler '''
        gremlin.util.assert_ui_thread()

        if not Shiboken.isValid(self):
            return
        
        if not widget or not widget.selected:
            # ignore deselects
            return 

        device = gremlin.joystick_handling.getDevice(self.device_guid)

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_ui
        current_mode = gremlin.shared_state.edit_mode
        input_item : InputItem = widget.input_item
        if verbose: syslog.info(f"BaseDeviceTabWidget: input selected: [{input_item.display_name}] index: [{widget.index}]")


        # get the current mapped widget
        if input_item is None:
            return
        



        # if input_item == self._last_selected_input_item:
        #     # already selected and input widget created
        #     return

        if verbose:
            if input_item:
                syslog.info(f"Selecting input config item for {device.name} input index [{widget.index}] mode: {current_mode}: {input_item.debug_display}")
            else:
                syslog.info(f"Selecting input config item for {device.name} input index [{widget.index}] mode: {current_mode}: Empty content")
        

        if input_item is not None:

            # select the RIGHT panel item for the input
            device_guid = self.device_guid
            input_type = input_item.input_type
            input_id = input_item.input_id

            # update container display if blank
            self.updateContainerViewBlankMessage(input_item)

            if config.debug_ui:
                self._debug_widget.setText(f"Contents for : {input_item.debug_display}")

            # make the mapping widget visible and redraw if needed
            self.selectInputItemMappingWidget(input_item)

            # mapped_widget = self.getInputItemMappingWidget(input_item)
            # if mapped_widget:
            #     mapped_widget._redraw_ui()            


            if input_item and emit:
                el = gremlin.event_handler.EventListener()
                el.input_selection_changed.emit(device_guid, input_type, input_id)


        if input_item and emit:
            self.inputChanged.emit(input_item.device_guid,
                                   input_item.input_type,
                                   input_item.input_id)
            
        


    def ensureLoaded(self):
        ts = gremlin.tabstate.TabState()
        data = ts.getData(self._device_id)
        if not data.populateEnabled:
            data.populateEnabled = True # enable data loading
            verbose = gremlin.config.Configuration().verbose_mode_ui
            if verbose:
                device_name = gremlin.joystick_handling.device_name_from_guid(self._device_id)
                syslog.info(f"UI: enable device data population [{device_name}] [{self._device_id}]")

            gremlin.util.InvokeUiMethod(self._ensureLoaded_ui)

    def _ensureLoaded_ui(self):
        ''' ensures the data is loaded into the widget - runs on UI thread '''
        if self._input_item_list_model.rows() == 0:
            self._input_item_list_model.refresh()

        
            

       
    

