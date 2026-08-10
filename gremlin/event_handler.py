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


import functools
import traceback
import inspect
import logging
import time
import threading
import collections
from typing import Optional
from threading import Thread, Timer
from typing import Callable
import math
import gremlin.base_classes
from gremlin.base_classes import FastQueue
import gremlin.shared_state
import gremlin.threading


from PySide6 import QtCore, QtWidgets

import dinput
import gremlin.config
from gremlin.input_types import InputType
from gremlin.types import DeviceType, EventSourceType
import gremlin.shared_state

import gremlin.util

import gremlin.keyboard
import gremlin.ui
import gremlin.singleton_decorator
import json

from psygnal import Signal
from gremlin.profiler import ignore_function
from gremlin.types import CallbackMode

syslog = logging.getLogger("system")


class Event:
    """Represents a single event captured by the system.

    An event can originate from the keyboard or joystick which is
    indicated by the EventType value. The value of the event has to
    be interpreted based on the type of the event.

    Keyboard and JoystickButton events have a simple True / False
    value stored in is_pressed indicating whether or not the key has
    been pressed. For JoystickAxis the value indicates the axis value
    in the range [-1, 1] stored in the value field. JoystickHat events
    represent the hat position as a unit tuple (x, y) representing
    deflection in cartesian coordinates in the value field.

    The extended field is used for Keyboard events only to indicate
    whether or not the key's scan code is extended one.
    """

    # m76T128 - performance pass - use slots
    __slots__ = [
        "event_type",
        "_id",
        "_identifier",
        "device_guid",
        "is_pressed",
        "value",
        "raw_value",
        "_curve_value",
        "force_remote",
        "action_id",
        "data",
        "is_axis",
        "virtual_code",
        "is_virtual",
        "is_virtual_button",
        "is_custom",
        "mode",
        "is_repeater",
        "override_input_type",
        "extra_data",
        "timestamp",
        "is_remote",
        "source",
        "client_list",
    ]

    def __init__(
        self,
        event_type,
        identifier,
        device_guid,
        value=None,  # normal calibrated value that comes in
        virtual_code=0,
        is_pressed=False,
        raw_value=None,  # raw value that comes in from dinput
        curved_value=None,  # value if curved
        force_remote=False,
        action_id=None,
        data=None,
        is_axis=False,  # true if the input should be considered an axis (variable) input
        is_virtual=False,  # true if the input is a virtual input (vjoy),
        mode=None,  # mode to fire the event on - leave null for current mode,
        override_input_type=None,
        extra_data: dict = None,  # extra data to pass on (dict)
        is_remote: bool = False,  # true if remote
        client_list=None,  # list of remote clients if remote
        source: EventSourceType = EventSourceType.Any,  # source of the event
    ):
        """Creates a new Event object.

        :param event_type the type of the event, one of the EventType
                values
        :param identifier the identifier of the event source
        :param device_guid Device GUID identifying the device causing this event
        :param value the value of a joystick axis or hat
        :param is_pressed boolean flag indicating if a button or key
        :param raw_value the raw SDL value of the axis
        :param force_remote flag that indicates if the action should be executed on the remote only
        :param action_id the ID of the action to execute or that generated the event
                is pressed
        """
        self._id = gremlin.util.get_guid()  # unique ID for this event
        self.event_type = event_type
        self._identifier = identifier
        self.device_guid = device_guid
        self.is_pressed = is_pressed
        self.value = value
        self.raw_value = raw_value
        self._curve_value = curved_value
        self.force_remote = force_remote
        self.action_id = action_id  # the current action id to load
        self.data = data  # extra data passed along with the event
        self.is_axis = is_axis
        self.virtual_code = virtual_code  # vk if a keyboard event (the identifier will be the key_id (scancode, extended))
        self.is_virtual = is_virtual  # true if the item is a vjoy device input
        self.is_virtual_button = False  # true if a virtual button
        self.is_custom = False  # true if a custom event (should be processed)
        self.mode = mode  # mode to act on, should be null for default
        self.is_repeater = False  # True if the event is a repeater generated event
        self.override_input_type = override_input_type  # override input type - used as the input type for actions
        self.extra_data = extra_data
        self.timestamp = time.time()
        self.is_remote = is_remote
        self.client_list = client_list
        self.source = source  # source of the event (dinput, vjoy, midi, osc)

    @property
    def curve_value(self) -> float:
        """curve value is the modified event value passed to actions as filtered or curved"""
        return self._curve_value

    @curve_value.setter
    def curve_value(self, value: float):
        self._curve_value = value

    @property
    def id(self) -> str:
        """event ID"""
        return self._id

    def clone(self):
        """Returns a clone of the event.

        :return cloned copy of this event
        """
        import copy

        if not isinstance(self.identifier, int):
            self.identifier = gremlin.base_classes.PickleTarget(self.identifier)
        dup = copy.deepcopy(self)
        dup._id = gremlin.util.get_guid()  # unique ID for this event
        return dup

    def release_event(self):
        """gets a cloned event that is released"""
        new_event = self.clone()
        new_event.is_pressed = False
        return new_event

    def press_event(self):
        """gets a cloned event that is released"""
        new_event = self.clone()
        new_event.is_pressed = True
        return new_event

    def set_extra_data(self, key: str, value: any):
        if not self.extra_data:
            self.extra_data = {}
        self.extra_data[key] = value

    def __deepcopy__(self, memo):
        import copy
        from itertools import chain

        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result
        slots = chain.from_iterable(getattr(s, "__slots__", []) for s in self.__class__.__mro__)
        for var in slots:
            if var in ("data", "extra_data"):
                # shallow copy
                setattr(result, var, copy.copy(getattr(self, var)))
            else:
                # deep copy
                setattr(result, var, copy.deepcopy(getattr(self, var)))
        return result

    @property
    def device_id(self) -> str:
        """id as a string"""
        return str(self.device_guid)

    @property
    def identifier(self):
        if isinstance(self._identifier, gremlin.base_classes.PickleTarget):
            self._identifier = self._identifier.item
        return self._identifier

    @identifier.setter
    def identifier(self, value):
        self._identifier = value

    def getInputType(self):
        if self.override_input_type:
            return self.override_input_type
        return self.event_type

    def fake_button(self, is_pressed=True, clone=False):
        """converts the event to a fake button"""
        e = self.clone() if clone else self
        if e.event_type in (InputType.JoystickAxis, InputType.JoystickHat):
            # convert axis/hat events to fake button events
            e.event_type = InputType.JoystickButton
        e.identifier = 1
        e.is_axis = False  # range exit is a button type event
        e.is_pressed = is_pressed
        return e

    def invert(self):
        """flips pressed flag"""
        e = self.clone()
        e.is_pressed = not self.is_pressed
        return e

    def __eq__(self, other):
        return self.__hash__() == other.__hash__()

    def __ne__(self, other):
        return not (self == other)

    @property
    def callbackKey(self):
        """unique key to use to identify the specific callback"""
        device_guid = self.device_guid
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
        if self.event_type == InputType.Keyboard:
            data = (self.identifier.scan_code, self.identifier.is_extended) if isinstance(self.identifier, gremlin.keyboard.Key) else self.identifier
            return (self.device_guid, self.event_type.value, data, 1 if data[1] else 0)
        else:
            return (device_guid, self.event_type.value, self.identifier, 0)

    def __hash__(self):
        """Computes the hash value of this event.
        new in m58: use the unique ID of this event to uniquely identify it

        :return integer hash value of this event
        """

        return hash(self._id)

    @property
    def hardwareKey(self):
        """unique key for the input"""
        return (self.device_guid, self.event_type, self.identifier)

    @staticmethod
    def from_key(key):
        """Creates an event object corresponding to the provided key.

        :param key the Key object from which to create the Event
        :return Event object corresponding to the provided key
        """
        if hasattr(key, "scan_code") and hasattr(key, "is_extended"):
            return Event(
                event_type=InputType.Keyboard,
                identifier=(key.scan_code, key.is_extended),
                virtual_code=key.virtual_code,
                device_guid=dinput.GUID_Keyboard,
            )

        raise ValueError(f"Unable to handle parameter - not a valid key: {key}")

    @staticmethod
    def from_vjoyEvent(ve: VjoyEvent):  # noqa: F821
        import gremlin.joystick_handling

        device_guid = gremlin.joystick_handling.vjoy_guid_from_id(ve.vjoy_id)
        input_type = ve.input_type
        is_pressed = False
        is_axis = False
        value = ve.value
        match input_type:
            case InputType.JoystickButton:
                is_pressed = value
            case InputType.JoystickAxis:
                is_axis = True
            case InputType.JoystickHat:
                is_pressed = value != (0, 0)

        return Event(
            event_type=ve.input_type,
            identifier=ve.input_id,
            device_guid=device_guid,
            is_pressed=is_pressed,
            is_axis=is_axis,
            value=value,
            curved_value=value,
            raw_value=value,
            extra_data={
                "loopback": True,
                "vjoy": ve.key,
            },  # store vjoy info for quick comparison
        )

    def __str__(self):
        import gremlin.joystick_handling

        if self.device_guid:
            device = gremlin.joystick_handling.getDevice(self.device_guid)
            device_stub = device.name if device else f" unknown {str(self.device_guid)}"
        else:
            device_stub = "n/a"

        if self.event_type == InputType.Mouse:
            stub = f"Mouse - button {self.identifier} pressed: {self.is_pressed}"
        elif self.event_type in (InputType.Keyboard, InputType.KeyboardLatched):
            stub = f"Keyboard - scan code, extended : {self.identifier}  vk: {self.virtual_code} (0x{self.virtual_code:X}) pressed: {self.is_pressed}"
        elif self.event_type == InputType.JoystickAxis or self.is_axis:
            stub = f"Axis : {self.identifier} raw value: {self.raw_value} value: {self.value}"
        elif self.event_type == InputType.JoystickButton:
            stub = f"Button : {self.identifier} pressed: {self.is_pressed} value: {self.value}"
        elif self.event_type == InputType.ModeControl:
            stub = f"Mode Control : {self.identifier} pressed: {self.is_pressed} value: {self.value} mode: {self.mode}"
        elif self.event_type == InputType.JoystickHat:
            stub = f"Hat : {self.identifier} pressed: {self.is_pressed} value: {self.value}"
        elif self.event_type == InputType.Midi:
            stub = f"Midi : {self.identifier} value: {self.value}"
        elif self.event_type == InputType.OpenSoundControl:
            stub = f"OSC : {self.identifier} value: {self.value}"
        elif self.event_type == InputType.State:
            stub = f"STATE : {str(self.identifier)} value: {self.value}"
        else:
            stub = f"{self.event_type} : {str(self.identifier)} value: {self.value}"

        return f"Event: [{self._id}] device: [{device_stub}] {stub}"

    # serialize
    def __getstate__(self):
        state = {}
        state["id"] = self._id
        state["event_type"] = self.event_type
        state["identifier"] = self.identifier
        state["device_guid"] = self.device_guid
        state["value"] = self.value
        state["virtual_code"] = self.virtual_code
        state["curved_value"] = self.curve_value
        state["raw_value"] = self.raw_value
        state["mode"] = self.mode
        state["is_axis"] = self.is_axis
        state["is_virtual"] = self.is_virtual
        state["is_pressed"] = self.is_pressed
        state["action_id"] = self.action_id
        state["force_remote"] = self.force_remote
        return state

    # deserialize
    def __setstate__(self, state):
        self._id = state["id"]
        self.event_type = state["event_type"]
        self.identifier = state["identifier"]
        self.device_guid = state["device_guid"]
        self.value = state["value"]
        self.virtual_code = state["virtual_code"]
        self.curve_value = state["curved_value"]
        self.raw_value = state["raw_value"]
        self.mode = state["mode"]
        self.is_axis = state["is_axis"]
        self.is_virtual = state["is_virtual"]
        self.is_pressed = state["is_pressed"]
        self.action_id = state["action_id"]
        self.force_remote = state["force_remote"]


# class JoystickEventQueue(FastQueue):
#     """represents a unique event queue

#     only one event type can be stored

#     """

#     def __init__(self, name: str = None):
#         super().__init__()
#         self.name = name

#     def putData(self, data):
#         """plain data add"""
#         # with self._lock:
#         self.put(data)

#     def getData(self):
#         return self.get()



class DeviceChangeEvent:
    """sent when a new device is selected"""

    __slots__ = [
        "device_guid",
        "device_name",
        "device_input_id",
        "device_input_type",
        "input_type",
        "vjoy_id",
        "vjoy_input_id",
        "source",
    ]

    def __init__(self):
        self.device_guid = None
        self.device_name = None
        self.device_input_id = 0
        self.device_input_type = 0
        self.input_type = 0
        self.vjoy_id = 0
        self.vjoy_input_id = 0
        self.source = None  # object source responsible for the change, for example, the action


class StateChangeEvent:
    """sent when the state changes"""

    __slots__ = ["is_local", "is_remote", "is_broadcast_enabled"]

    def __init__(self, is_local=False, is_remote=False, is_broadcast_enabled=False):
        self.is_local = is_local
        self.is_remote = is_remote
        self.is_broadcast_enabled = is_broadcast_enabled


class VjoyEvent:
    __slots__ = ["vjoy_id", "input_type", "input_id", "value"]

    def __init__(self, vjoy_id, input_type: InputType, input_id: int, value):
        self.vjoy_id = vjoy_id
        self.input_type = input_type
        self.input_id = input_id
        self.value = value

    @property
    def key(self) -> tuple:
        """unique key for this event"""
        return (self.vjoy_id, self.input_type.value, self.input_id, self.value)

    @property
    def device_guid(self):
        return gremlin.joystick_handling.vjoy_guid_from_id(self.vjoy_id)

    def __str__(self):
        if self.input_type == InputType.JoystickAxis:
            value_stub = f"{self.value:0.3f}"
        else:
            value_stub = f"{self.value}"
        return f"VjoyEvent: vjoy [{self.vjoy_id}] type: [{self.input_type.name}] input: [{self.input_id}] value: [{value_stub}]"


@gremlin.singleton_decorator.SingletonDecorator
class EventListener(QtCore.QObject):
    """Listens for keyboard and joystick events and publishes them
    via QT's signal/slot interface.
    """

    ui_ready = Signal()  # tell the UI all is ready

    ui_initialized = Signal()  # signal to tell the UI to refresh

    # Signal emitted when joystick events are received
    joystick_event = Signal(Event)  # Signal(Event)

    # ui joystick event = event fired at edit time to edit UI based on the joystick event - use QT for this to the event is on the UI thread


    # custom joystick event - this is a code based joystick event that mapping items can listen to when inside other containers
    custom_joystick_event = Signal(Event)

    hardware_input_event = Signal(object, object, object)  # called for any input event (device_guid, input_type, input_id)

    vjoy_event = Signal(VjoyEvent)  # Signal(VjoyEvent)
    vjoy_output_event = Signal(VjoyEvent)  # sent on button output

    joystick_event_ui = QtCore.Signal(Event)  # ui thread joystick input event
    vjoy_output_event_ui = QtCore.Signal(VjoyEvent)  # ui thread vjoy output event

    # Signal emitted when keyboard events are received
    keyboard_event = Signal(Event)
    # Signal emitted when mouse events are received
    mouse_event = Signal(Event)
    # Signal emitted when virtual button events are received
    virtual_event = Signal(Event)

    # signal emmitted when a MIDI input is received
    midi_event = Signal(Event)

    # signal emitted when an OSC input is received
    osc_event = Signal(Event)

    # state event
    state_event = Signal(Event)

    state_name_change = Signal(str, str, object)  # fires when a state changes names (old_name, new_name, StateInputItem)
    state_category_add = Signal(object)  # fires when a state category is added (StateCategory)
    state_category_delete = Signal(object)  # fires when a state category is removed (StateCategory)
    state_category_name_change = Signal(object)  # fires when a state category name is changed (StateCategory)

    # Signal emitted when a joystick is attached or removed
    device_change_event = Signal()

    # fires when vjoy input state changes, parameter is the id of the vjoy and what it's changing to
    vjoy_as_input_changed = Signal(int, bool)

    # fires when the number of gamepad devices changes
    gamepad_change_event = Signal()

    # called when a process device change should be handled
    _process_device_change = Signal()

    # Signal emitted when the icon needs to be refreshed
    icon_changed = Signal(DeviceChangeEvent)

    feature_changed = Signal(object)  # fires when a feature changes (Feature)

    # Signal emitted when a profile is changed (to refresh UI)
    profile_changed = Signal()

    # signal emitted when the selected hardware device changes
    profile_device_changed = Signal(DeviceChangeEvent)

    # signal emitted when the selected hardware device changes
    profile_device_mapping_changed = Signal(DeviceChangeEvent)

    # signal emitted when the UI tabs are loaded and profiles are loaded - some widgets use this for post-UI initialization update that needs to occur after the UI data is completely loaded
    tabs_loaded = Signal()
    tab_filtered_changed = Signal(object, bool)  # fires when tab filtering changes
    input_filtered_change = Signal(object)  # fires when input filter for joystick devices is changed (device_guid)

    refresh_devices = Signal()  # used to refresh the device list going into GremlinEx

    profile_reset = Signal()  # profile reset signal (when runtime for a profile needs to reset)
    profile_hook = Signal()  # hook functors - before profile start is emitted
    profile_unhook = Signal()  # unhook functors - when profiles stop
    profile_start = Signal()  # profile start signal (when a profile starts)
    profile_started = Signal()  # profile started signal (after a profile starts and all process start functions are completed)
    profile_after_start = Signal()  # occurs after the profile started signal

    profile_stop = Signal()  # profile stop signal (when a profile stops)
    profile_stopping = Signal()  # profile is about to stop (before a profile stops)
    profile_stopped = Signal()  # profile stopped (after a profile stopped)

    profile_stop_toolbar = Signal()  # profile stop signal (when a profile stops because the toolbar is pressed)
    profile_unload = Signal()  # profile unload signal (when a profile is unloaded and a new profile loaded)
    profile_loading = Signal()  # fires when a profile is being loaded
    profile_loading_completed = Signal()  # fires when profile loading is completed (with or without errors)
    profile_loaded = Signal()  # fires after a profile was loaded (no errors)

    # profile unloaded - trigger when a profile is being unloaded
    profile_unloaded = Signal()

    request_profile_stop = Signal(str)  # request the profile to stop (message to display: str)
    request_profile_reload = Signal(str, bool)  # request a profile to load (str = profile file, bool = as new profile flag)
    request_reload = Signal()  # request a reload of the current profile data
    request_ui_refresh = Signal()  # request a UI refresh

    process_monitor_changed = Signal()  # process monitor options changed

    host_ip_changed = Signal(str)  # indicates the local machines' host IP changed

    config_changed = Signal()  # occurs on broadcast configuration change
    config_option_changed = Signal()  # occurs on broadcast configuration change

    options_changed = Signal()  # occurs when the options dialog closes to have components check for any changes

    # occurs on broadcast mode change
    broadcast_changed = Signal(StateChangeEvent)

    # occurs on mode edit/update/delete of modes (edit time only)
    edit_mode_changed = Signal(str)  # param: the mode that was changed to
    edit_mode_ui_update = Signal(str)  # param: the mode to update the UI to (note: this only updates the UI visually to ensure inputs are in sync)

    mode_name_changed = Signal(str, str)  # runs when a mode name change occurs for the UI to update - param (old name, new name)
    mode_list_update = Signal()  # runs when mode lists changes
    profile_modes_changed = Signal()  # occurs when the hierarchy, or list of modes changed for a given profile (mode added, removed, changed or renamed)
    execution_context_changed = Signal()  # occurs when execution context changes
    runtime_mode_changed = Signal(
        str
    )  # runs when the runtime profile mode changes (runtime mode only, when a profile has been started) - param - the mode changed to
    update_mode_status_bar = Signal(str)  # request to update the mode status bar (mode)

    # functor enable flag changed
    action_created = Signal(object)  # runs when an action is created - object = the object that triggered the event

    # remove action
    action_delete = Signal(object, object, object)  # fires when an action is about to be deleted, passes the (input_item, container, action) as a parameters
    action_deleted = Signal(object) # fires when an action is deleted, passes the action as a parameter
    action_crud = Signal(object,object)  # fires when an action is created, updated or deleted, passes the (action_set, action) as a parameter


    virtual_button_changed = Signal(object, object, object)  # runs when the action has modified its input mode (input_item, container, action) as parameters

    # called when vjoy button usage has changed in the profile so displays can update themselves
    button_usage_changed = Signal(DeviceType, int)  # (device_type : DeviceType, virtual_id : int) fires when a vjoy device button has changed
    vjoy_button_usage = Signal(int, int, bool)  # called when an action uses a vjoy button (vjoy_id, button_id, state)
    set_virtual_button_usage = Signal(dinput.DeviceSummary, int, bool, object)  # called when a button state should be set (device_guid, virtual_id : int, state : bool, key) - the key is the action key

    # selection event - tells the UI to show a different input
    select_input = Signal(
        object, object, object, bool, bool, bool, Callable
    )  # selects a particular input (device_guid, input_type, input_id,  force_update, force_switch, tab_changed)
    select_input_completed = Signal(object, object, object)  # indicates input selection is completed (device_guid, input_type, input_id)

    input_selected = Signal(object)  # widget item was selected, parameter = InputItemWidget
    input_item_selected = Signal(object, int)  # widget item was selected, parameter = InputItem, index of input item in the listview
    input_unselected = Signal(object)  # widget item was unselected selected, parameter = InputItemWidget
    input_deleted = Signal(object)  # called when an input item is deleted, parameter = InputItem

    tab_selected = Signal(
        str
    )  # tab selected, the device_guid (str) is passed as the parameter - this is triggered when a device tab is selected and made visible
    tab_unselected = Signal(
        str
    )  # tab unselected, the device_guid (str) is passed as the parameter - this is triggered when a device tab is selected and made visible

    # mapping changed - either container or action added -
    mapping_changed = Signal(object)  # fires when a container or action changes on an InputItem - passes the InputItem as the parameter

    # suspend keyboard input
    suspend_keyboard_input = Signal(bool)  # arg = state, true = suspend, false = resume

    # called when a condition state changes - used to update the UI
    condition_redraw = Signal(object)  # fires when a condition is redrawing
    condition_state_changed = Signal(object)  # indicates the container state change  (container : AbstractContainer)
    condition_changed = Signal(object)  # indicates the container's conditions changed (container : AbstractContainer | AbstractAction)

    condition_added = Signal(object, str, object)  # fires when a condition is added - params (input_item, mode, condition)
    condition_removed = Signal(object, str, object)  # fires when a condition is removed - params (input_item, mode, condition)

    # container deleted
    container_delete = Signal(object, object)  # fires when a container is about to be deleted, passes the input item, container as parameters




    # update input curve icons
    update_input_icons = Signal()  # fires when the UI needs to refresh input calibration and curve icons
    update_action_icons = Signal()  # fires when the UI needs to update the action icons

    # occurs when input enabled state changes
    input_enabled_changed = Signal(object)  # param - InputItem
    input_used_changed = Signal(object, object, object, bool)  # when input usage is changed, fires this (device_guid, input_type, input_id, used : bool)

    # occurs when a macro step completes
    macro_step_completed = Signal(int)  # param - macro ID returned by the queue_macro function

    # request profile activate/deactivate
    request_activate = Signal(bool)  # param - flag - true to activate, false to deactivate

    # abort load
    abort = Signal()  # tells loops/thread at active time to stop - called when a profile needs to stop due to a start error

    # request OSC start/stop
    request_osc = Signal(bool)  # param - flag - true to start, false to stop
    osc_input_port_changed = Signal()  # occurs when OSC input port is changed
    osc_output_port_changed = Signal()  # occurs when OSC output port is changed
    osc_output_server_changed = Signal()  # occurs when OSC server output IP is changed
    osc_loopback = Signal(object)  # occurs when a loopback message is sent [osc_message]

    # request MIDI start/stop
    request_midi = Signal(bool)  # param - flag - true to start, false to stop

    # # signals the need to register an OSC input item
    # register_osc_input = Signal(object) # param input_item being registered

    # gremlin ex shutdown in progress
    shutdown = Signal()

    # toggle highlighting mode state
    toggle_highlight = Signal(object, object, object)  # param (axis,button)
    enable_highlight_changed = Signal(bool)  # fires when highlight enable is turned on param(enabled)

    button_state_change = Signal(Event)  # indicates a change in button state params: (event)
    axis_state_change = Signal(Event)  # indicates a change in axis state params: (event)

    update_input_state = Signal(object)  # request to update all axis and button input states in the UI for a given device: (device_guid)

    # heartbeat
    heartbeat = Signal()  # ticks every 30 seconds

    # autorepeat abort flag
    autorepeat_clear = Signal()  # fire this to abort any keyboard autorepeat actions

    # module status state notices
    module_state_change = Signal(str, object)  # send a module state update, (key, state)
    module_state_register = Signal(
        str, str, object, object
    )  # registers a module state (key, label, state, callback) - if callback is not None, sets up a button when clicked will execute the callback.  State = None, true/false, "on", "off", ""

    # notify when an input is selected (keep this a QT event for thread safety)
    input_selection_changed = Signal(object, object, object)  # (device_guid, input_type, input_id)

    # request to paste a condition
    paste_condition = Signal(object, object)  # (container, object_encoder)

    # request to copy a condition or activation condition
    copy_condition = Signal(object)  # (condition or activation condition)

    show_container_id_changed = Signal()  # fires when condition ID show on/off changed in configuration - this is to update affected widgets

    tts_change = Signal(bool)  # fires when TTS enable/disabled changes

    device_mapping_changed = Signal(str)  # fires when device mapping has changed (updates headers) - param = device_id as a string

    simconnect_show_options = Signal()  # fires when the simconnect options dialog should be displayed

    toolbar_changed = Signal()  # fires when the toolbar configuration has changed

    lock_inputs = Signal(object)  # fires when all inputs should be locked, object = device_guid of the device to lock
    unlock_inputs = Signal(object)  # fires when all inputs should be unlocked, object = device_guid of the device to unlock
    jump_to_mapped_input = Signal()  # fires when the input list should select the first mapped input

    collapse_all_containers = Signal()  # collapse all containers
    expand_all_containers = Signal()  # expand all containers
    curve_added = Signal(object)  # fires when a curve is added from an input item (InputItem)
    curve_deleted = Signal(object)  # fires when a curve is deleted from an input item (InputItem)
    curve_edit = Signal(int, object)  # fires when a curve is edited from an input item (InputItem)
    curve_delete = Signal(int,object)  # fires when a curve is deleted from an input item (InputItem)

    # occurs when calibration data changes
    calibration_added = Signal(object)  # fires when a calibration is added from an input item (InputItem)
    calibration_deleted = Signal(object)  # fires when a calibration is deleted from an input item (InputItem)
    calibration_changed = Signal(object)  # param - CalibrationData object (InputItem)
    calibration_options_changed = Signal(object)  # fires when calibration options are changed for the UI to update (InputItem)
    sync_input = Signal(object)  # request to sync the input (InputItem)

    remote_control_enable = Signal()  # request to enable remote control
    remote_control_disable = Signal()  # request to disable remote control
    remote_control_changed = Signal(bool)  # tell the UI the remote control is ON (bool), True = enabled

    request_vjoy_axis_change = Signal(object, int, float)  # request to change axis for VJOY (device, axis_id, value)

    process_manual_event = Signal(object, object, object)  # fires when a manual event should be processed (event, value, extra_data)

    reload_axis_state = Signal()  # sent when input items should re-register their axes with AxisState

    request_action_list_refresh = Signal()  # ask action drop downs to refresh their lists

    remote_control_client_change = Signal()  # emits when the list of network clients changes via network activity (clients reporting in)
    remote_config_client_change = Signal()  # emits when list of configured clients changes
    remote_control_state_change = Signal()  # called when the remote control server status changes
    remote_control_identify = Signal()  # emits when a client needs to get a current list of clients on the network (this will update all clients)
    remote_control_socket_timeout = Signal()  # emits when the socket times out
    remote_control_socket_error = Signal()  # emits when the socket has an error

    find_next = Signal()  # find next event

    # container_modified = Signal(object) # indicates a container was modified
    # data_changed = Signal(object) # indicates a model was changed


    def postInit(self):
        """Post-initialization hook for the event handler"""
        import gremlin.windows_event_hook
        import gremlin.threading


        config = gremlin.config.Configuration()
        self._mouse_hook_stack = 0
        self.mouse_hook = None
        self.enable_mouse_hook = not config.mouse_hook_disabled # False if __debug__ else not config.is_debug  # disable mouse hooks while in debug mode
        self.enableMouse()

        self.keyboard_hook = gremlin.windows_event_hook.KeyboardHook()
        self.keyboard_hook.register(self._keyboard_handler)



        # Calibration function for each axis of all devices
        self._calibrations = {}

        # Joystick device change update timeout timer
        self._device_update_timer = None
        self._device_change_suppressed = 0  # suppression counter for device change events
        self._device_change_pending = False  # true if a device change occured while suppressed

        self._running = True

        self._process_device_change_lock = False

        # keyboard input handling buffer
        self._keyboard_state = {}
        self._keyboard_queue = None
        self._key_listener_started = False  # true if the key listener is started
        self.gremlin_active = False
        self._keyboard_thread = None
        self.keyboard_hook.start()

        self.device_change_event.connect(self._device_changed_cb)

        # internal event on process change
        self._process_device_change.connect(self._process_device_change_cb)

        # calibration data access
        self._calibrationManager = None
        self._profile_started = False

        self.profile_start.connect(self._handle_profile_start)
        self.profile_stopping.connect(self._handle_profile_stopping)
        self.profile_after_start.connect(self._handle_profile_started)
        self.config_option_changed.connect(self._handle_options_changed)

        self._run_event = threading.Event()
        self._run_thread = Thread(target=self._run)
        self._run_thread.name = "EVENT run"
        self._run_thread.start()

        self._keep_alive_event = threading.Event()
        self._keep_alive_thread = threading.Thread(target=self._keep_alive, daemon=False)
        self._keep_alive_thread.name = "EVENT heartbeat"
        self._keep_alive_thread.start()

        self._vjoy_callbacks = []
        self._debounce_map = {}

        self._hat_state = {}  # list of map positions (device_id, input_id), position_tuple, if blank - not set

        self.js = JoystickState()

        self.shutdown.connect(self._shutdown_handler)

        # TEST / POSSIBLE FUTURE WORK internal vjoy event handling for vjoy loopback cases
        self._vjoy_events = {}  # map of processed events
        # self._vjoy_events_times = {} # map of processed events times
        self._vjoy_events_delay = 0.250  # quarter second delay for event loopback checking
        self._vjoy_events_use_time = False  # config.vjoy_loopback_use_time
        self.vjoy_event.connect(self._handle_vjoy_event)  # hook internal vjoy events generated whenever something is output to vjoy

        self._ui_joystick_event_callbacks = []  # callbacks for joystick event runner

        # setup the event queue for joystick events
        self._event_queue : FastQueue[Event] = FastQueue[Event](name ="event listener queue")  # queue.Queue() # holds the queue of events waiting to be processed
        self._valid_device_map = gremlin.joystick_handling.getValidJoystickDevicesMap()
        self._event_thread = gremlin.threading.AbortableThreadX(target=self._event_runner, eh=self)
        self._event_thread.name = "EVENTLISTENER listener"
        self._event_thread.start()
        self.joystick_event_ui.connect(self._fireUIJoystickEventCallbacks_ui, QtCore.Qt.ConnectionType.QueuedConnection)  # no wait signal for speed

        self.profile_unload.connect(self.reset)  # reset data on profile unload before a new profile is loaded

        self._handle_options_changed()  # load verbose modes

    def pushDeviceChangeSuppression(self):
        """increments the device change suppression counter"""
        self._device_change_suppressed += 1

    def popDeviceChangeSuppression(self, force=False):
        """decrements the device change suppression counter"""
        if force:
            self._device_change_suppressed = 0
        elif self._device_change_suppressed > 0:
            self._device_change_suppressed -= 1
        if self._device_change_suppressed == 0 and self._device_change_pending:
            self._device_change_pending = False
            self.device_change_event.emit()  # trigger the pending device change event

    def addUIJoystickEventCallback(self, callback):
        """adds a callback to update UI when a joystick event arrives"""
        if callback not in self._ui_joystick_event_callbacks:
            self._ui_joystick_event_callbacks.append(callback)

    def removeUIJoystickEventCallback(self, callback):
        """removes a callback to update UI when a joystick event arrives"""
        if callback in self._ui_joystick_event_callbacks:
            self._ui_joystick_event_callbacks.remove(callback)

    def registerVjoyCallback(self, callback):
        if callback not in self._vjoy_callbacks:
            self._vjoy_callbacks.append(callback)

    def unregisterVjoyCallback(self, callback):
        if callback in self._vjoy_callbacks:
            self._vjoy_callbacks.remove(callback)

    def vjoy_callback(self, event: VjoyEvent):
        for callback in self._vjoy_callbacks:
            callback(event)

    def queueJoystickEvent(self, event):
        """queues a single joystick event"""
        if event.device_guid in self._valid_device_map:
            if self._verbose_queue:
                syslog.info(f"EVENTLISTEN: QUEUE event {event.id}")
            self._event_queue.put(event)

    def queueJoystickEventList(self, event_list):
        """queues a list of joystick events"""
        for event in event_list:
            self._event_queue.put(event)

    # @ignore_function
    def _event_runner(self) -> None:
        """Process inbound joystick events."""

        event_queue = self._event_queue
        event_thread = self._event_thread

        joystick_event_emit = self.joystick_event.emit
        joystick_event_ui_emit = self.joystick_event_ui.emit
        axis_state_change_emit = self.axis_state_change.emit
        button_state_change_emit = self.button_state_change.emit

        while not event_thread.stopped():
            event_list = event_queue.getNowait()
            if not event_list:
                time.sleep(0)
                continue
            for event in event_list:
                joystick_event_emit(event)
                joystick_event_ui_emit(event)

                if not gremlin.shared_state.is_running:
                    if event.is_axis:
                        axis_state_change_emit(event)
                    else:
                        button_state_change_emit(event)
                time.sleep(0)

    def _fireUIJoystickEventCallbacks(self, event):
        # run the UI callbacks on the UI thread
        if self._ui_joystick_event_callbacks:
            gremlin.util.InvokeUiMethod(self._fireUIJoystickEventCallbacks_ui, event)

    def _fireUIJoystickEventCallbacks_ui(self, event):
        """runs the UI update oriented joystick event callbacks on the UI thread to avoid constant switching"""
        for callback in self._ui_joystick_event_callbacks:
            callback(event)

    def reset(self):
        self._vjoy_events.clear()
        self._vjoy_callbacks.clear()

        # clear the event queue
        self._event_queue.clear()
        # while not self._event_queue.empty():
        #     self._event_queue.get()

    def disconnect(self, signal : Signal | QtCore.Signal, slot : Callable):
        """ attempts to disconnect a slot from a signal safely """
        try:
            if isinstance(signal, Signal) and slot in signal:
                signal.disconnect(slot)
            elif isinstance(signal, QtCore.Signal):
                signal.disconnect(slot)
        except Exception as e:
            pass



    @QtCore.Slot()
    def _shutdown_handler(self):
        """terminate threads"""
        import gremlin.windows_event_hook

        config = gremlin.config.Configuration()


        verbose = config.verbose_mode_inputs
        if self._keep_alive_thread:
            self._keep_alive_event.set()
            self._keep_alive_thread.join()
            self._keep_alive_thread = None

        if self._run_thread:
            self._run_event.set()
            self._run_thread.join()
            self._run_thread = None

        # event runner
        if self._event_thread.is_alive():
            if verbose:
                syslog.info("EVENTLISTENER: listen stop")
            self._event_thread.stop()
            self._event_thread.join()
            self._event_thread = None

        # mark all events processed
        self._event_queue.clear()

        # shutdown keyboard hook if enabled
        kh = gremlin.windows_event_hook.KeyboardHook()
        kh.shutdown()

        # shutdown mouse hook if enabled
        mh = gremlin.windows_event_hook.MouseHook()
        mh.shutdown()

        # terminate vjoy
        from vjoy.vjoy_interface import VJoyInterface
        VJoyInterface.shutdown()


        # manual atexit
        #atexit._run_exitfuncs()

    @property
    def calibrationManager(self):
        from gremlin.ui.axis_calibration import CalibrationManager

        if not self._calibrationManager:
            self._calibrationManager = CalibrationManager()

        return self._calibrationManager

    def _fire_event_list(self, event_list):
        """fires a series of events"""
        self.queueJoystickEventList(event_list)

    def _load_hat_states(self):
        """loads current hats"""
        from gremlin.util import dill_hat_lookup
        import gremlin.joystick_handling

        self._hat_state = {}

        device_list = [dev for dev in gremlin.joystick_handling.joystick_devices() if dev.hat_count > 0]
        event_list = []
        for device in device_list:
            for input_id in range(1, device.hat_count + 1):
                key = (device.device_id, input_id)
                value = gremlin.joystick_handling.get_hat(device.device_guid, input_id)
                if value in dill_hat_lookup:
                    value = dill_hat_lookup[value]
                else:
                    # invalid value received for the hat position
                    syslog.warning(
                        f"HAT STATE: received an invalid hat value: device: {device.name} id [{device.device_id}] - got hat position: [{value}] for hat [{input_id}] - forcing (0,0)"
                    )
                    value = (0, 0)

                self._hat_state[key] = value

                event = Event(
                    event_type=InputType.JoystickHat,
                    device_guid=device.device_guid,
                    identifier=input_id,
                    is_pressed=True,
                    is_virtual=device.is_virtual,
                    value=value,
                    raw_value=value,
                )
                event_list.append(event)

        if event_list:
            self.queueJoystickEventList(event_list)

    def _handle_options_changed(self):
        """options were changed"""
        import gremlin.config

        config = gremlin.config.Configuration()
        self._verbose_dinput = config.verbose_mode_dinput
        self._verbose_perf = config.verbose_mode_perf
        self._verbose_dinput_extra = self._verbose_dinput and config.verbose_mode_extra
        self._verbose_vjoy = config.verbose_mode_vjoy
        self._verbose_vjoy_extra = self._verbose_vjoy and config.verbose_mode_extra
        self._verbose_queue = self._verbose_dinput
        self._verbose_inputs = config.verbose_mode_inputs
        self._verbose_extra = config.verbose_mode_extra

        self._vjoy_events_delay = config.vjoy_loopback_delay / 1000  # quarter second delay for event loopback checking
        self._vjoy_events_use_time = config.vjoy_loopback_use_time

        import gremlin.windows_event_hook

        hook = gremlin.windows_event_hook.KeyboardHook()
        hook.updateVerbose()

    def _handle_profile_start(self):
        """occurs on profile start EVENT LISTENER"""
        import gremlin.windows_event_hook

        self._profile_started = False
        self._handle_options_changed()

        # loopback configuration for vjoy events
        self._vjoy_events.clear()  # map of processed events
        # self._vjoy_events_times.clear()# map of processed events times

        # update valid device map on profile start
        self._valid_device_map = gremlin.joystick_handling.getValidJoystickDevicesMap()

        # enable mouse hooks
        self.enableMouse(True)

        # reset keyboard suppression
        gremlin.windows_event_hook.MouseHook().popSuppress(True)
        gremlin.windows_event_hook.KeyboardHook().popSuppress(True)

    def _handle_profile_stopping(self):
        """called when profile is stopping"""
        import gremlin.windows_event_hook

        # clear the current event queue
        syslog.info(f"EXEC: clear event queue: size: {len(self._event_queue)}")
        self._event_queue.clear()

        self._profile_started = False
        device_guid = gremlin.shared_state.mode_tab_guid
        delay = 0.250  # delay in seconds between press/release events for mode control change
        master_mode = gremlin.shared_state.master_mode
        extra_data = {"mode": master_mode}  # override execution mode

        event_stop_pressed = Event(
            InputType.ModeControl,
            identifier=gremlin.ui.mode_device.ModeInputModeType.ModeProfileStop,
            mode=gremlin.shared_state.master_mode,  # runs on master mode
            device_guid=device_guid,
            is_pressed=True,
            extra_data=extra_data,
            override_input_type=InputType.JoystickButton,
        )

        event_stop_released = Event(
            InputType.ModeControl,
            identifier=gremlin.ui.mode_device.ModeInputModeType.ModeProfileStop,
            mode=gremlin.shared_state.master_mode,  # runs on master mode
            device_guid=device_guid,
            is_pressed=False,
            extra_data=extra_data,
            override_input_type=InputType.JoystickButton,
        )

        eh = EventHandler()
        m2_list, f2_list = eh.execute_event(event_stop_pressed)
        start_release = Timer(delay, lambda: eh._execute_callbacks(event_stop_released, m2_list, f2_list))
        start_release.start()

        if not self.enable_mouse_hook:
            self.disableMouse()

        # reset keyboard suppression
        gremlin.windows_event_hook.MouseHook().popSuppress(True)
        gremlin.windows_event_hook.KeyboardHook().popSuppress(True)

    def _handle_profile_started(self):
        """occurs on profile start - sets profile defaults and executes start mappings"""
        device_guid = gremlin.shared_state.mode_tab_guid
        mode_enter = gremlin.ui.mode_device.ModeInputModeType.ModeEnter
        delay = 0.250  # delay in seconds between press/release events for mode control change
        _new_mode = gremlin.shared_state.runtime_mode
        master_mode = gremlin.shared_state.master_mode
        extra_data = {"mode": master_mode, "target_mode": _new_mode}  # override execution mode

        # profile start event
        event_start_pressed = Event(
            InputType.ModeControl,
            identifier=gremlin.ui.mode_device.ModeInputModeType.ModeProfileStart,
            mode=gremlin.shared_state.master_mode,  # runs on master mode
            device_guid=device_guid,
            is_pressed=True,
            extra_data=extra_data,
            override_input_type=InputType.JoystickButton,
        )

        event_start_released = Event(
            InputType.ModeControl,
            identifier=gremlin.ui.mode_device.ModeInputModeType.ModeProfileStart,
            mode=gremlin.shared_state.master_mode,  # runs on master mode
            device_guid=device_guid,
            is_pressed=False,
            extra_data=extra_data,
            override_input_type=InputType.JoystickButton,
        )

        # mode enter events
        event_enter_pressed = Event(
            InputType.ModeControl,
            identifier=mode_enter,
            device_guid=device_guid,
            is_pressed=True,
            extra_data=extra_data,
            override_input_type=InputType.JoystickButton,
        )
        event_enter_released = Event(
            InputType.ModeControl,
            identifier=mode_enter,
            device_guid=device_guid,
            is_pressed=False,
            extra_data=extra_data,
            override_input_type=InputType.JoystickButton,
        )

        # read the starting hat states
        self._load_hat_states()

        self._profile_started = True

        # executes profile start events - fire mode change for mode enter (press + release)
        eh = EventHandler()

        m2_list, f2_list = eh.execute_event(event_start_pressed)
        start_release = Timer(delay, lambda: eh._execute_callbacks(event_start_released, m2_list, f2_list))
        start_release.start()

        m2_list, f2_list = eh.execute_event(event_enter_pressed)
        enter_release = Timer(delay, lambda: eh._execute_callbacks(event_enter_released, m2_list, f2_list))
        enter_release.start()

    def _device_changed_cb(self):
        self._init_joysticks()

    def mouseEnabled(self):
        """returns mouse hook status"""
        return self.mouse_hook is not None

    def enableMouse(self, force=False):
        """pushes the mouse hook stack - mouse hook is enabled the first time this is called (if options for that allow it)"""
        if self.enable_mouse_hook or force:
            if not self._mouse_hook_stack:
                import gremlin.windows_event_hook

                syslog.info("MOUSE HOOK: enabled")
                if self.mouse_hook is None:
                    self.mouse_hook = gremlin.windows_event_hook.MouseHook()
                    self.mouse_hook.register(self._mouse_handler)
                    self.mouse_hook.start()
            self._mouse_hook_stack += 1
        else:
            syslog.warning("MOUSE HOOK: ************ DEBUG MODE: disabled")

    def disableMouse(self, reset=False):
        """pops the mouse hook stack"""
        if reset:
            # force a stack reset
            self._mouse_hook_stack = 0
        else:
            if self._mouse_hook_stack > 1:
                self._mouse_hook_stack -= 1
                return
        if self._mouse_hook_stack == 0:
            if self.mouse_hook is not None:
                self.mouse_hook.shutdown()
                self.mouse_hook.unregister(self._mouse_handler)
                self.mouse_hook = None

    def push_joystick(self):
        gremlin.shared_state.push_joystick()

    def pop_joystick(self, reset=False):
        gremlin.shared_state.pop_joystick(reset)

    def push_input_selection(self):
        gremlin.shared_state.push_input_selection()

    def pop_input_selection(self, reset=False):
        gremlin.shared_state.pop_input_selection(reset)

    @property
    def joystick_input_suspended(self) -> bool:
        """true if joystick input suspended"""
        return gremlin.shared_state.is_joystick_input_suspended

    @property
    def input_selection_suspended(self) -> bool:
        """true if input selection is suspended"""
        return gremlin.shared_state.is_input_selection_suspended

    def _process_queue(self):
        """processes an item the keyboard buffer queue"""
        if self._keyboard_queue.empty():
            return
        items = list(self._keyboard_queue.getall())
        for item, is_pressed in items:
            if not self._keyboard_thread_running:
                break
            verbose = gremlin.config.Configuration().verbose_mode_detailed
            is_error = False
            if verbose:
                syslog.info(f"process_queue: found item: {item} is pressed: {is_pressed}")

            if isinstance(item, int):
                virtual_code = item
                key = gremlin.keyboard.KeyMap.find_virtual(virtual_code)
                self._keyboard_buffer[virtual_code] = is_pressed
                key_id = key.index_tuple()
            else:
                key_id = item
                scan_code, is_extended = item
                key = gremlin.keyboard.KeyMap.find(scan_code, is_extended)

                if key is None:
                    syslog.error(f"DEQUEUE KEY: don't know how to handle scancode: {scan_code:x} extended: {is_extended}")
                    is_error = True
                else:
                    virtual_code = key.virtual_code
                    self._keyboard_buffer[key_id] = is_pressed

            if not is_error:
                if verbose:
                    syslog.info(
                        f"DEQUEUE KEY {gremlin.keyboard.KeyMap.keyid_tostring(key_id)} id: {key_id} vk: {virtual_code} (0x{virtual_code:X}) name: {key.name} pressed: {is_pressed}"
                    )

                self.keyboard_event.emit(
                    Event(
                        event_type=InputType.Keyboard,
                        device_guid=dinput.GUID_Keyboard,
                        identifier=key_id,
                        virtual_code=virtual_code,
                        is_pressed=is_pressed,
                        data=self._keyboard_buffer,
                    )
                )

            # process the events
            time.sleep(0)  # yield to other threads

        item, is_pressed = self._keyboard_queue.get()
        verbose = gremlin.config.Configuration().verbose_mode_detailed
        is_error = False
        if verbose:
            syslog.info(f"process_queue: found item: {item} is pressed: {is_pressed}")

        if isinstance(item, int):
            virtual_code = item
            key = gremlin.keyboard.KeyMap.find_virtual(virtual_code)
            self._keyboard_buffer[virtual_code] = is_pressed
            key_id = key.index_tuple()
        else:
            key_id = item
            scan_code, is_extended = item
            key = gremlin.keyboard.KeyMap.find(scan_code, is_extended)

            if key is None:
                syslog.error(f"DEQUEUE KEY: don't know how to handle scancode: {scan_code:x} extended: {is_extended}")
                is_error = True
            else:
                virtual_code = key.virtual_code
                self._keyboard_buffer[key_id] = is_pressed

        if not is_error:
            if verbose:
                syslog.info(
                    f"DEQUEUE KEY {gremlin.keyboard.KeyMap.keyid_tostring(key_id)} id: {key_id} vk: {virtual_code} (0x{virtual_code:X}) name: {key.name} pressed: {is_pressed}"
                )

            self.keyboard_event.emit(
                Event(
                    event_type=InputType.Keyboard,
                    device_guid=dinput.GUID_Keyboard,
                    identifier=key_id,
                    virtual_code=virtual_code,
                    is_pressed=is_pressed,
                    data=self._keyboard_buffer,
                )
            )

        # process the events
        time.sleep(0)  # yield to other threads
        # QtWidgets.QApplication.processEvents()
        # self._keyboard_queue.task_done()

    def _keyboard_runner(self):
        """runs as a thread to process inbound keyboard events using a queue"""

        syslog.info("KBD: processing start")
        self._keyboard_buffer = {}
        self._key_listener_started = True
        while self._keyboard_thread_running:
            if self._keyboard_queue.empty():
                time.sleep(0)
                continue
            if self._keyboard_thread_running:
                self._process_queue()
                time.sleep(0)  # yield to other threads

        syslog.info("KBD: stopped")

    def start_key_listener(self):
        """starts the key listener"""
        if not self._key_listener_started:
            self._key_listener_started = True
            self._keyboard_thread_running = True
            self._keyboard_queue : FastQueue[Event] = FastQueue(name="keyboard_queue") # queue.Queue()
            self._keyboard_thread = threading.Thread(target=self._keyboard_runner, daemon=True)
            # self._keyboard_thread = gremlin.threading.AbortableThread(target=self._keyboard_runner)
            self._keyboard_thread.start()


    def stop_key_listener(self):
        """stops the key listener"""
        if self._key_listener_started:

            syslog.info("KEY THREAD: stopping...")
            self._keyboard_queue.clear()
            self._keyboard_thread_running = False
            self._keyboard_thread.join(timeout=1)


            syslog.info(f"KEY THREAD: clearing remaining items in queue: size: {len(self._keyboard_queue)}")

            syslog.info("KEY THREAD: stopped")
            self._key_listener_started = False

    def start(self):
        """starts the non regular listener"""
        self.enableMouse()
        self._key_listener_stop_requested = False
        self.start_key_listener()

    def stop(self):
        self.disableMouse()
        self.stop_key_listener()

    def terminate(self):
        """Stops the loop from running."""

        # syslog = logging.getLogger("system")
        syslog.info("EVENT: shutdown requested")
        gremlin.shared_state.terminating = True  # tell UI we're terminating to avoid uncessary updates if we're shutting down
        self._running = False
        self.disableMouse()

        # send the shutdown trigger to all code parts
        if self._run_thread is not None:
            # terminate run thread
            self._run_event.set()
            self._run_thread.join()

        # stop heart beat
        self._keep_alive_event.set()
        self._keep_alive_thread.join()

        self.request_activate.emit(False)
        try:
            self.shutdown.emit()
        except Exception as e:
            syslog.error(f"EVENT: error during shutdown: {e}")

    def reload_calibrations(self):
        """Reloads the calibration data from the configuration file."""
        from gremlin.util import create_calibration_function

        cfg = gremlin.config.Configuration()
        for key in self._calibrations:
            limits = cfg.get_calibration(key[0], key[1])
            self._calibrations[key] = create_calibration_function(limits[0], limits[1], limits[2])

    def _run(self):
        """Starts the event loop."""

        if not dinput.DILL.initalized:
            dinput.DILL.init()
        syslog.info("DILL: start listen")
        dinput.DILL.set_device_change_callback(self._dinput_device_change_handler)
        dinput.DILL.set_input_event_callback(self._dinput_event_handler)  # DINPUT event handler
        while self._running and not self._run_event.is_set():
            # Keep this thread alive until we are done
            time.sleep(0)
        syslog.info("DILL: shutdown")
        dinput.DILL.set_device_change_callback(None)
        dinput.DILL.set_input_event_callback(None)

    @ignore_function
    def _keep_alive(self):
        """keep alive 30 second hearbeat"""
        delay = 60 * 2  # delay in seconds
        notify_time = time.time()
        while not self._keep_alive_event.is_set():
            if time.time() >= notify_time:
                self.heartbeat.emit()
                notify_time = time.time() + delay  # 2 minutes
            time.sleep(5)  # do other stuff

    def _handle_vjoy_event(self, vjoyevent: VjoyEvent):
        """handles internal loopback events

        this is called whenever GremlinEx sends data to VJOY.
        If the vjoy device is also an input device, VJOY output may or may not trigger a DINPUT event
        and it's not reliable as it looks to be based on timing, thus not predictable.
        If VJOY doesn't trigger DINPUT, it will fail to trigger an input event from VJOY into GremlinEx.

        The workaround implemented here is to compare the last DINPUT event for VJOY changes to the expected
        state of the output, and manually trigger an input if different (this essentially fakes a DINPUT event).


        """
        vjoy_id = vjoyevent.vjoy_id
        verbose = self._verbose_vjoy
        # verbose = True # debug mode - force output for diagnostics regardless of user settings
        if self._profile_started and self.js.vjoyAsInput(vjoy_id):
            # profile is running and started, and the vjoy device is a loopback device (used as input)
            input_type = vjoyevent.input_type
            input_id = vjoyevent.input_id
            value = vjoyevent.value
            if verbose:
                syslog.info(f"VJOY EVENT:  [{vjoy_id}] [{input_type.name}] [{input_id}]  value: [{value}]")

            # if self.shouldProcessVjoy(vjoy_id, input_type, input_id, value):
            if AxisState().shouldProcess(vjoyevent):
                # issue a loop back internal event
                if verbose:
                    syslog.info(f"VJOY EVENT: loopback trigger (exec) {vjoyevent}")
                event = Event.from_vjoyEvent(vjoyevent)
                self.queueJoystickEvent(event)

                # thread = threading.Thread(target = self._execute_loopback_callback, args = (event,))
                # thread.name = "vjoy loopback"
                # thread.start()
            else:
                if verbose:
                    syslog.info(f"VJOY EVENT: looback filtered (skip) {vjoyevent}")

    def shouldProcessVjoy(self, vjoy_id: int, input_type: InputType, input_id: int, value) -> bool:
        """tracks vjoy events from directinput or internally triggered"""
        import gremlin.joystick_handling
        import gremlin.util
        # get current vjoy state

        verbose = self._verbose_vjoy_extra
        # verbose = True

        if verbose:
            match input_type:
                case InputType.JoystickAxis:
                    syslog.info(f"VJOY LOOPBACK: got axis event [{vjoy_id}] [{input_type.name}] axis [{input_id}]  value: [{value:0.3f}]")
                case InputType.JoystickButton:
                    syslog.info(f"VJOY LOOPBACK: got button event [{vjoy_id}] [{input_type.name}] btn [{input_id}] value: [{value != 0}]")
                case InputType.JoystickHat:
                    syslog.info(f"VJOY LOOPBACK: got hat event [{vjoy_id}] [{input_type.name}] hat [{input_id}]  value: [{value}]")

        # now = time.time()
        # setup the tracking data structure to look for changes
        if vjoy_id not in self._vjoy_events:
            self._vjoy_events[vjoy_id] = {}
            # self._vjoy_events_times[vjoy_id] = {}
        if input_type not in self._vjoy_events[vjoy_id]:
            self._vjoy_events[vjoy_id][input_type] = {}
            # self._vjoy_events_times[vjoy_id][input_type] = {}

        # read current value
        if value is None:
            match input_type:
                case InputType.JoystickAxis:
                    current_value = gremlin.joystick_handling.VJoyProxy()[vjoy_id].axis(input_id).value
                case InputType.JoystickButton:
                    current_value = gremlin.joystick_handling.VJoyProxy()[vjoy_id].button(input_id).is_pressed
                case InputType.JoystickHat:
                    current_value = gremlin.joystick_handling.VJoyProxy()[vjoy_id].hat(input_id).direction
                case _:
                    syslog.error(f"VJOY LOOPBACK: don't know how to handle input type: {input_type}")
                    return False
        else:
            current_value = value

        if input_id in self._vjoy_events[vjoy_id][input_type]:
            if verbose:
                syslog.info("\tprior event found")
            # t = self._vjoy_events_times[vjoy_id][input_type][input_id] + self._vjoy_events_delay
            last_value = self._vjoy_events[vjoy_id][input_type][input_id]
            if input_type == InputType.JoystickAxis:
                # account for floating point accuracy issues
                if verbose:
                    syslog.info(
                        f"VJOY LOOPBACK: compare vjoy [{vjoy_id}] [{input_type.name}] [{input_id}]  new value: [{current_value:0.3f}] old value [{last_value:0.3f}]"
                    )
                is_close = gremlin.util.is_close(last_value, current_value)
                # duplicated = is_close and t < now if self._vjoy_events_use_time else is_close
                duplicated = is_close
                if duplicated:
                    if verbose:
                        syslog.info("\tFAIL (skip event) (axis)")
                    return False
                else:
                    if verbose:
                        syslog.info("\tSUCCEED (axis)")
            else:
                # button/hat
                current_value = value != 0
                if verbose:
                    syslog.info(
                        f"VJOY LOOPBACK: compare vjoy [{vjoy_id}] [{input_type.name}] [{input_id}]  new value: [{current_value}]  old value: [{last_value}]"
                    )

                # duplicated = last_value == current_value and t < now if self._vjoy_events_use_time else last_value == current_value
                duplicated = last_value == current_value
                if duplicated:
                    if verbose:
                        syslog.info("\tFAIL (skip event) (button)")
                    return False  # same state, nothing to do
                else:
                    if verbose:
                        syslog.info("\tSUCCEED (button)")
        else:
            if verbose:
                syslog.info("\tnew event registered")

        # update the data
        self._vjoy_events[vjoy_id][input_type][input_id] = value
        # self._vjoy_events_times[vjoy_id][input_type][input_id] = now
        # if verbose: syslog.info(f"VJOY LOOPBACK: record vjoy state: [{vjoy_id}] [{input_type.name}] [{input_id}]  value: [{value}]")

        return True  # process

    def _dinput_event_filter(self, device: dinput.DeviceSummary, event: dinput.InputEvent) -> bool:
        """filters dinput events
        :return: True if the event should be filtered out, False otherwise
        """

        if device.disabled:
            # filter disabled inputs
            return True

        vendor_id = device.vendor_id
        product_id = device.product_id
        input_type = event.input_type.value
        # if isinstance(input_type, Enum):
        #     input_type = input_type.value[0]
        # try:
        #     input_type = event.input_type.value[0]
        # except Exception:
        #     input_type = event.input_type
        input_id = event.input_index
        if vendor_id not in self._debounce_map:
            self._debounce_map[vendor_id] = {}
            self._debounce_map[vendor_id][product_id] = {}
            self._debounce_map[vendor_id][product_id][input_type] = {}
            self._debounce_map[vendor_id][product_id][input_type][input_id] = DInputData()

        elif product_id not in self._debounce_map[vendor_id]:
            self._debounce_map[vendor_id][product_id] = {}
            self._debounce_map[vendor_id][product_id][input_type] = {}
            self._debounce_map[vendor_id][product_id][input_type][input_id] = DInputData()

        elif input_type not in self._debounce_map[vendor_id][product_id]:
            self._debounce_map[vendor_id][product_id][input_type] = {}
            self._debounce_map[vendor_id][product_id][input_type][input_id] = DInputData()

        elif input_id not in self._debounce_map[vendor_id][product_id][input_type]:
            self._debounce_map[vendor_id][product_id][input_type][input_id] = DInputData()

        data: DInputData = self._debounce_map[vendor_id][product_id][input_type][input_id]

        if not data.debounce:
            # do not filter
            return False

        now = time.perf_counter()

        # filter axis on deviation and buttons on time
        if data.value is None:
            # initial button/hat event - do not filter
            data.last_time = now
            data.value = event.value
            return False

        # if event.input_type != dinput.InputType.Axis:
        #     syslog.info(f"Event: [{device.name}]: {event}")

        value = event.value
        match event.input_type:
            case dinput.InputType.Axis:  # joystick
                value_threshold = 0.01
                if abs(value - data.value) >= value_threshold:
                    # axis deviation sufficient to trigger
                    data.time = now
                    data.value = value
                    return False

            case dinput.InputType.Button | dinput.InputType.Hat:
                # button or hat

                lapsed = now - data.last_time
                time_threshold = 0.01
                # syslog.info(f"event: {event} lapsed time: {lapsed} threshold: {time_threshold} value changed: {value != data.value} lapsed: {lapsed > time_threshold}")
                if value != data.value and lapsed > time_threshold:
                    # button changed and sufficient time passed
                    data.time = now
                    data.value = value
                    # syslog.info("\tnot filtered")
                    return False

        # filter

        return True

    def _dinput_event_handler(self, data):
        """Callback for joystick events.

        The handler converts the event data into a signal which is then
        emitted.  IMPORTANT: Applies any calibration and curvature to the data before firing other events.

        :param data the joystick event
        """

        import vjoy.vjoy

        if not gremlin.joystick_handling.joystick_initialized():
            # not initialized yet
            return

        if gremlin.shared_state.is_joystick_suspended:
            # ignore if joystick input is suspended
            return

        from gremlin.util import dill_hat_lookup

        verbose = self._verbose_dinput  # or (self._verbose_perf and self._verbose_extra)
        verbose_extra = self._verbose_dinput_extra

        dinput_event = dinput.InputEvent(data)
        device: dinput.DeviceSummary = gremlin.joystick_handling.getDevice(dinput_event.device_guid)

        if device is None:
            if verbose:
                syslog.info(f"DINPUT EVENT: device not found: [{device.name}]: {dinput_event}")
            return

        if self._dinput_event_filter(device, dinput_event):
            # filtered out
            if verbose:
                syslog.info(f"DINPUT EVENT: event filtered: [{device.name}]: {dinput_event}")
            return

        # if device.vendor_id == 0x31e3 and event.input_type.value[0] == 2 and event.input_index > 16:
        #     # wooting keyboard button spam filter
        #     return

        if verbose:
            syslog.info(f"DINPUT EVENT: device [{device.name}] data: {dinput_event}")

        event_list = []
        astate = AxisState()
        dstate = DInputState()

        is_virtual = device.is_virtual if device is not None else False
        if is_virtual:
            input_type = None
            vjoy_id = device.vjoy_id
            if self.js.inputIgnored(data.device_guid):
                # ignore if the device is set to input ignore
                if verbose:
                    syslog.info(f"Ignore input: {device.name} input: {dinput_event.input_index} type: {dinput_event.input_type}")
                return

            if self.js.vjoyAsInput(vjoy_id):
                # update the event tracker for loop back devices
                # we need to record the event because vjoy can sometimes trigger, or not trigger a DINPUT event when it's receiving commands.
                verbose_vjoy = self._verbose_vjoy
                input_id = dinput_event.input_index
                value = dinput_event.value
                if dinput_event.input_type == dinput.InputType.Axis:
                    input_type = InputType.JoystickAxis
                elif dinput_event.input_type == dinput.InputType.Button:
                    input_type = InputType.JoystickButton
                    value = value != 0  # convert to boolean - true if pressed, false if not
                elif dinput_event.input_type == dinput.InputType.Hat:
                    input_type = InputType.JoystickHat
                    # convert value to tuple for hat value comparisons
                    value = vjoy.vjoy.Hat.getDirection(value)
                else:
                    if verbose_vjoy:
                        syslog.error(f"DINPUT VJOY LOOPBACK: don't know how to handle input type: {dinput_event.input_type}")
                    input_type = None

            if input_type:
                # track the input event
                if verbose_vjoy:
                    syslog.info(f"DINPUT VJOY LOOPBACK: register vjoy [{vjoy_id}] [{input_type.name}] [{input_id}]  value: [{value}]")

                # if not astate.shouldProcess(event):
                if not self.shouldProcessVjoy(vjoy_id, input_type, input_id, value):
                    return  # skip DINPUT event

        if dinput_event.input_type == dinput.InputType.Axis:
            if verbose and verbose_extra:
                syslog.info(f"DINPUT AXIS: {dinput_event}")

            # normalize dinput to GEX range -1.0 to 1.0
            raw_value = gremlin.util.scale_to_range(dinput_event.value, source_min=-32768, source_max=32767, target_min=-1.0, target_max=1.0)
            value = raw_value

            # apply spam filter
            if not astate.shouldProcess(dinput_event):
                # filtered out
                return

            extra_data = {}

            if self._has_calibration(dinput_event.device_guid, dinput_event.input_index):
                # apply input calibration
                value, _ = self._apply_calibration(dinput_event, True)
                extra_data["calibrated"] = True
                extra_data["calibrated_value"] = value

            # apply input curve on calibrated data if any
            curved_value, has_curve = self._apply_curve_ex(dinput_event.device_guid, dinput_event.input_index, value)
            if has_curve:
                extra_data["curved"] = True

            dinput_event = Event(
                event_type=InputType.JoystickAxis,
                device_guid=dinput_event.device_guid,
                identifier=dinput_event.input_index,
                value=value,
                curved_value=curved_value,
                raw_value=raw_value,
                is_axis=True,
                is_virtual=is_virtual,
                extra_data=extra_data,
            )

            event_list.append(dinput_event)

            # notify axis change for tab switches
            if not gremlin.shared_state.is_running:
                # if AxisState().shouldProcess(event,"state_change"):
                self.axis_state_change.emit(dinput_event)

        elif dinput_event.input_type == dinput.InputType.Button:
            if verbose:
                syslog.info(f"DINPUT BUTTON: {dinput_event}")

            # apply spam filter
            if not dstate.shouldProcess(dinput_event):
                # filtered out
                return
            is_pressed = dinput_event.value == 1
            dinput_event = Event(
                event_type=InputType.JoystickButton,
                device_guid=dinput_event.device_guid,
                identifier=dinput_event.input_index,
                is_pressed=is_pressed,
                is_virtual=is_virtual,
                value=is_pressed,
            )

            event_list.append(dinput_event)

        elif dinput_event.input_type == dinput.InputType.Hat:
            # hats trigger two events, one for the changed from the original position (release)
            # and the other for the move to the new position (press)

            device_id = str(dinput_event.device_guid)
            input_id = dinput_event.input_index
            value = dill_hat_lookup[dinput_event.value]

            key = (device_id, input_id)

            if key not in self._hat_state:
                self._hat_state[key] = False

            current = self._hat_state[key]
            if current != value:
                # update the new state
                self._hat_state[key] = value

                # release the old value
                release_event = Event(
                    event_type=InputType.JoystickHat,
                    device_guid=dinput_event.device_guid,
                    identifier=dinput_event.input_index,
                    is_pressed=False,
                    is_virtual=is_virtual,
                    value=current,
                    raw_value=current,
                    extra_data={"comments": f"Hat release event for position: {current}"},
                )

                event_list.append(release_event)

                extra_data = {}
                extra_data["comments"] = f"Hat press event - prior hat position: {current}  new position: {value}"
                extra_data["old_position"] = current

                # press the new value
                new_event = Event(
                    event_type=InputType.JoystickHat,
                    device_guid=dinput_event.device_guid,
                    identifier=dinput_event.input_index,
                    is_pressed=True,
                    is_virtual=is_virtual,
                    value=value,
                    raw_value=value,
                    extra_data=extra_data,
                )

                event_list.append(new_event)

        if event_list:
            self.queueJoystickEventList(event_list)

        time.sleep(0)  # yield to other threads

    def _dinput_device_change_handler(self, data, action):
        """Callback for device change events.

        This is called when a device is added or removed from the system. This
        uses a timer to call the actual device update function to prevent
        the addition or removal of a multiple devices at the same time to
        cause repeat updates.

        :param data information about the device changing state
        :param action whether the device was added or removed
        """

        if self._device_change_suppressed:
            self._device_change_pending = True  # mark that a device change occurred while suppressed
            return

        # ignore if a VIGEM device - these are handled, for the moment, directly by the action
        if data.vendor_id == 0x045E and data.product_id == 0x28E and data.button_count == 10 and data.name == b"Controller (XBOX 360 For Windows)":
            return

        self.device_change_event.emit()

        if self._device_update_timer is not None:
            self._device_update_timer.cancel()
        self._device_update_timer = Timer(0.5, self._run_device_list_update)
        self._device_update_timer.start()

    def _run_device_list_update(self):
        """Performs the update of the devices connected."""
        self._process_device_change.emit()

    def _process_device_change_cb(self):

        if self._process_device_change_lock:
            return

        self._process_device_change_lock = True
        # syslog = logging.getLogger("system")

        try:
            is_running = gremlin.shared_state.is_running
            gremlin.shared_state.has_device_changes = True
            if is_running:
                if gremlin.config.Configuration().runtime_ignore_device_change:
                    syslog.warning("\tRuntime device change detected - ignoring due to options")
                    return
                else:
                    syslog.warning("\tChange detected at runtime - stopping profile")
                    gremlin.shared_state.ui.activate(False)

            # reset devices and fire off the device change event
            gremlin.joystick_handling.reset_devices()

        finally:
            self._process_device_change_lock = False

    def _keyboard_handler(self, event):
        """low level handler for callback for keyboard events.

        The handler converts the event data into a signal which is then
        emitted.

        :param event the keyboard event
        """
        verbose = gremlin.config.Configuration().verbose_mode_detailed

        # verbose = True
        virtual_code = event.virtual_code
        key_id = (event.scan_code, event.is_extended)
        is_pressed = event.is_pressed
        if verbose:
            syslog.info(
                f"Recorded key: {key_id:} sc: {event.scan_code:X} ex: {event.is_extended} vk: {virtual_code} (0x{virtual_code:X}) pressed: {is_pressed}"
            )

        # deal with any code translations needed
        key_id = gremlin.keyboard.KeyMap.translate_lookup(key_id)  # modify scan codes if needed
        virtual_code = gremlin.keyboard.KeyMap.vk_lookup(key_id)  # get virtual code
        if verbose:
            syslog.info(
                f"Translated key: {key_id:} sc: {event.scan_code:X} ex: {event.is_extended} vk: {virtual_code} (0x{virtual_code:X}) pressed: {is_pressed}"
            )

        is_repeat = self._keyboard_state.get(key_id) and is_pressed

        if is_repeat:
            # ignore repeats
            return True

        self._keyboard_state[key_id] = is_pressed

        if gremlin.shared_state.is_running:
            # RUN mode - queue input events
            if not self._key_listener_started:
                return True

            self._keyboard_queue.put((key_id, is_pressed))

            # add to the processing queue
            if verbose:
                syslog.info(f"QUEUE KEY {gremlin.keyboard.KeyMap.keyid_tostring(key_id)} vk 0x{virtual_code:X} pressed {is_pressed}")

        else:
            # DESIGN mode - straight
            # print (f"FIRE KEY {key_id} pressed {is_pressed}")
            self.keyboard_event.emit(
                Event(
                    event_type=InputType.Keyboard,
                    device_guid=dinput.GUID_Keyboard,
                    identifier=key_id,
                    virtual_code=virtual_code,
                    is_pressed=is_pressed,
                    data=self._keyboard_state.copy(),  # use a copy of the keyboard state at the time the key is sent
                )
            )

        # Allow the windows event to propagate further
        return True

    def get_key_state(self, key: gremlin.keyboard.Key):
        """returns the state of the given key"""
        return self._keyboard_state.get(key.index_tuple(), False)

    def get_shifted_state(self):
        """returns true if either of the shift keys are down"""
        lshift_key = gremlin.keyboard.Key(scan_code=gremlin.keyboard.scan_codes.sc_shiftLeft)
        if self.get_key_state(lshift_key):
            return True
        rshift_key = gremlin.keyboard.Key(scan_code=gremlin.keyboard.scan_codes.sc_shiftRight)
        if self.get_key_state(rshift_key):
            return True
        return False

    def get_control_state(self):
        """returns true if either of the control keys are down"""
        lctrl_key = gremlin.keyboard.Key(scan_code=gremlin.keyboard.scan_codes.sc_controlLeft)
        if self.get_key_state(lctrl_key):
            return True
        rctrl_key = gremlin.keyboard.Key(scan_code=gremlin.keyboard.scan_codes.sc_controlRight)
        if self.get_key_state(rctrl_key):
            return True
        return False

    def get_control_shift_state(self):
        """true if control + shift states active"""
        return self.get_control_state() and self.get_shifted_state()

    def get_alt_state(self):
        """returns true if either of the alt keys are down"""
        lalt_key = gremlin.keyboard.Key(scan_code=gremlin.keyboard.scan_codes.sc_altLeft)
        if self.get_key_state(lalt_key):
            return True
        ralt_key = gremlin.keyboard.Key(scan_code=gremlin.keyboard.scan_codes.sc_altRight)
        if self.get_key_state(ralt_key):
            return True
        return False

    def _mouse_handler(self, event):
        """Callback for mouse events.

        The handler converts the event data into a signal which is then
        emitted.

        :param event the mouse event
        """

        # Ignore events we created via the macro system
        if not event.is_injected:
            if not self._running:
                return

            mouse_event = Event(
                event_type=InputType.Mouse,
                device_guid=dinput.GUID_Keyboard,
                identifier=event.button_id,  # mouse handler is expecting a mouse ID, not a keyboard ID
                is_pressed=event.is_pressed,
                data=self._keyboard_state,
            )

            self.mouse_event.emit(mouse_event)

        # Allow the windows event to propagate further
        return True

    def _apply_calibration(self, event: dinput.InputEvent, return_process: bool = False, return_calibrated: bool = False) -> tuple:
        """applies calibration data to the vent
        :param event: the event data
        :param return_process: if set, returns an additional process flag if the axis should be processed
        :param return_calibrated, if set, returns an additional flag if the axis was calibrated
        :returns: (value, should_process)

        """
        return self._apply_calibration_ex(event.device_guid, event.input_index, event.value, return_process, return_calibrated)

    def _apply_curve(self, event: Event) -> tuple:
        """applies input curves to the input
        :param event:
        :returns (value:float, has_curve:bool): computed curve data"""
        return self._apply_curve_ex(event.device_guid, event.input_index, event.value)

    def _apply_calibration_ex(self, device_guid, input_id, value, return_process: bool = False, return_calibrated: bool = False) -> tuple:
        """applies calibration and deadzone data to the raw input - value -32768 to 32767, returns -1, +1 and optionally inverts the input, and sets the process flag"""
        calibration = self.calibrationManager.getCalibration(device_guid, input_id)
        verbose = gremlin.config.Configuration().verbose_mode_joystick
        new_value = calibration.getValue(value, filter=return_process)
        if verbose:
            device = gremlin.joystick_handling.getDevice(device_guid)
            nv = new_value[0] if hasattr(new_value, "__iter__") else new_value
            syslog.info(f"CALIBRATION: filter: device: [{device.name}] id: [{device_guid}] filter: [{return_process}] in: {value:0.3f} out: {nv:0.3f}")

        return new_value

    def getAxisValues(self, device_guid: dinput.GUID, input_id: int) -> AxisData:  # noqa: F821
        """gets axis data values for the given axis"""
        return AxisState().getAxisValues(device_guid, input_id)

    def _apply_curve_ex(self, device_guid, input_id, value: float) -> tuple:
        """applies a curve to the input axis
        :param device_guid: device ID (dinput.GUID)
        :param input_id: axis ID (int)
        :returns tuple(value:float, has_curve:bool)

        """
        curved_value = AxisState().applyCurve(device_guid, input_id, value)
        if curved_value is not None:
            verbose = gremlin.config.Configuration().verbose_mode_curve
            if verbose:
                device = gremlin.joystick_handling.getDevice(device_guid)
                syslog.info(f"APPLY CURVE: device: [{device.name}] id: [{device_guid}] in: {value:0.4f} out: {curved_value:0.4f}")
            return curved_value, True  # applied
        # no curve applied
        return value, False  # not applied

    def apply_transforms(self, device_guid: dinput.GUID, input_id: int, raw_value: float) -> float:
        """applies raw transforms to the data - input is expected in dinput range (-32K to +32k)"""
        calib_value = self._apply_calibration_ex(device_guid, input_id, raw_value)
        curved_value, has_curve = self._apply_curve_ex(device_guid, input_id, calib_value)
        # print(f"Raw value: {raw_value:0.4f} included: {calib_value:0.4f} Curved value: {curved_value:0.4f}")
        return curved_value

    def _init_joysticks(self):
        """Initializes joystick devices."""
        for dev_info in gremlin.joystick_handling.joystick_devices():
            self._load_calibrations(dev_info)

    def _load_calibrations(self, device_info):
        """Loads the calibration data for the given joystick.

        :param device_info information about the device
        """

        from gremlin.util import create_calibration_function

        cfg = gremlin.config.Configuration()
        for entry in device_info.axismap_list:
            limits = cfg.get_calibration(device_info.device_guid, entry.axis_index)
            self._calibrations[(device_info.device_guid, entry.axis_index)] = create_calibration_function(limits[0], limits[1], limits[2])

    def _get_calibration_key(self, event: Event) -> tuple:
        """gets the calibration key for an event"""
        return (event.device_guid, event.identifier)

    def _has_calibration(self, device_guid: dinput.GUID, input_id: int) -> bool:
        """true if an input has calibration data"""
        key = (device_guid, input_id)
        return key in self._calibrations


class TTSNotifyData:
    """holds TTS data notification"""

    def __init__(self):
        self.profile = None
        self.mode = None


@gremlin.singleton_decorator.SingletonDecorator
class EventHandler(QtCore.QObject):
    """Listens to the inputs from multiple different input devices."""

    mode_status_update = Signal()  # tell the UI to update the mode status bar

    # signal emitted when the profile is changed
    profile_changed = Signal(str)

    # Signal emitted when the application is pause / resumed
    is_active = Signal(bool)

    last_action_changed = Signal(object, str)  # fires when the action changes in the selector (drop_down, name)
    last_container_changed = Signal(object, str)  # fires when the action changes in the selector (drop_down, name)

    def __init__(self):
        """Initializes the EventHandler instance."""
        QtCore.QObject.__init__(self)
        self.plugins = {}
        self._mode_validator_callbacks = {}  # list of validators (callbacks) that return a boolean True if the mode change can occur - signature must be callable(str)->bool
        self._last_tts_data = TTSNotifyData()  # last mode that triggered a TTS verbal notice
        self._change_mode_callback = None  # change mode handler
        el = EventListener()
        el.runtime_mode_changed.connect(self._update_mode_change)
        el.profile_start.connect(self._profile_start)
        el.profile_stop.connect(self._profile_stop)
        el.profile_started.connect(self._profile_started)

        self.registry = EventRegistry()

        self._lock = threading.Lock()
        self._started = False
        self._execute_queue = []  # list of items to execute
        self._execute_thread = None
        self._execute_running = False

        # map of callbacks evaluated to see if a mode change can occur keyed by a unique key
        # actions that need to approve a mode change register a callback hook and unique ID that succeeds (bool = True) if the mode change is allowed
        self._mode_change_hooks = {}

        # holds the mode change requests that are queued up
        # a queue is used to delay a mode change if a sequence/macro is running and needs to finish before the mode change
        self._change_mode_queue = collections.deque()
        self._mode_queue_enabled = not gremlin.config.Configuration().mode_change_aborts_sequence

        self._mode_change_callbacks = []  # holds callbacks to validate if mode changes should occur

        self.reset()

    def _profile_start(self):
        """' profile start event - EVENT HANDLER"""
        if not self._started:
            self._started = True
            self._last_vjoy_event = None  # reset vjoy loopback
            # self._queue_start()
            self._update_mode_change(gremlin.shared_state.runtime_mode)
            self._mode_queue_enabled = not gremlin.config.Configuration().mode_change_aborts_sequence

            self._execute_thread = gremlin.threading.AbortableThreadX(target=self._execute_runner)
            self._execute_thread.name = "execute runner"
            self._execute_thread.start()
            syslog.info("EXEC: start")

    def _profile_started(self):
        """occurs when profile has started - hook functors"""
        pass

    def _profile_stop(self):
        if self._started:
            # self._queue_stop() # finish up and stop the current execution queue
            self._started = False
            self._last_tts_notify = None
            self._last_tts_notify_time = None

            # save the last profile mode
            current_profile = gremlin.shared_state.current_profile
            last_mode = gremlin.shared_state.runtime_mode
            current_profile.set_last_runtime_mode(last_mode)

            if self._execute_thread.is_alive():
                syslog.info("EXEC: stopping execute runner thread")
                self._execute_thread.stop()
                syslog.info("EXEC: execute runner thread stopped")
                self._execute_thread.join()
                syslog.info("EXEC: stop")

    def registerModeValidator(self, callback: Callable):
        assert callback is not None and callable(callback), "Callback must provided and be a callable "
        self._mode_validator_callbacks[callback] = callback

    def unregisterModeValidator(self, callback):
        if callback in self._mode_validator_callbacks:
            del self._mode_validator_callbacks[callback]

    def clearModeValidator(self):
        self._mode_validator_callbacks.clear()

    def runModeValidator(self, mode):
        """runs through all current validators to see if a mode change can occur"""
        result = True  # assume we can
        for callback in self._mode_validator_callbacks:
            result = result and callback(mode)
            if not result:
                break

        return result

    def reset(self):
        """reset even handling for runtime"""
        config = gremlin.config.Configuration()
        verbose = config.verbose
        if verbose:
            syslog.info("EventHandler: reset()")

        self.process_callbacks = True
        self.callbacks = {}
        self.callback_key_map = {}  # map of event callbackKey to event
        self.input_item_map = {}  # map of input items keyed by device_guid, mode, input_type, input_id
        self.latched_events = {}
        self.latched_callbacks = {}
        self.midi_callbacks = {}
        self.osc_callbacks = {}
        self.state_callbacks = {}
        self._event_lookup = {}
        self.latched_functors = {}
        self.experimental = config.experimental
        self._last_vjoy_event = None  # tracks the last VJOY event for loopback detection

    @property
    def runtime_mode(self):
        """Returns the currently active mode.

        :return name of the currently active mode
        """
        return gremlin.shared_state.runtime_mode

    @runtime_mode.setter
    def runtime_mode(self, value):
        gremlin.shared_state.runtime_mode = value

    @property
    def edit_mode(self):
        return gremlin.shared_state.edit_mode

    @edit_mode.setter
    def edit_mode(self, value):
        gremlin.shared_state.edit_mode = value

    @property
    def current_mode(self):
        """gets the current mode based on state"""
        return gremlin.shared_state.current_mode

    @property
    def previous_runtime_mode(self):
        """returns the previous mode"""
        return gremlin.shared_state.previous_runtime_mode

    @previous_runtime_mode.setter
    def previous_runtime_mode(self, value):
        """sets the active mode"""
        gremlin.shared_state.previous_runtime_mode = value

    def add_plugin(self, plugin):
        """Adds a new plugin to be attached to event callbacks.

        :param plugin the plugin to add
        """
        # Do not add the same type of plugin multiple times
        if plugin.keyword not in self.plugins:
            self.plugins[plugin.keyword] = plugin

    def dump_exectree(self, device_guid, mode, event):
        """outputs the execution tree to the log"""
        from types import FunctionType, MethodType

        verbose = gremlin.config.Configuration().verbose
        if not verbose:
            return

        _get_device_name = gremlin.shared_state.get_device_name
        device_name = gremlin.shared_state.get_device_name(device_guid)

        for callbacks in self.callbacks[device_guid][mode][event.callbackKey]:
            for callback in callbacks:
                if not hasattr(callback, "execution_graph"):
                    syslog.info(
                        f"\tDevice ID: {device_name}  mode: {mode} event: {event} - skip callback - missing execution graph - don't know how to handle {type(callback)} *********"
                    )
                    continue

                for callback_functor in callback.execution_graph.functors:
                    if hasattr(callback_functor, "action_set"):
                        for functor in callback_functor.action_set.functors:
                            action_data = functor.action_data if hasattr(functor, "action_data") else None
                            syslog.info(f"\tDevice ID: {device_name} mode: {mode} event: {event} hash: {hash(event):X} type: {type(functor)}")
                            if action_data:
                                # dump member variables only
                                syslog.info("\t\tData block:")
                                for attr in dir(action_data):
                                    if not attr.startswith("_"):
                                        item = getattr(action_data, attr)

                                        if not (
                                            isinstance(item, FunctionType) or isinstance(item, MethodType) or inspect.isabstract(item) or inspect.isclass(item)
                                        ):
                                            syslog.info(f"\t\t\t{attr}: {item}")
                    else:
                        syslog.info(f"\tFunctor '{type(callback_functor).__name__} does not define an action set")

    def dump_callbacks(self):
        # dump latched events
        import gremlin.ui.keyboard_device
        import gremlin.shared_state

        _get_device_name = gremlin.shared_state.get_device_name

        syslog.info("------------ Latched Events ----------------")
        for device_guid in self.latched_events.keys():
            device_name = gremlin.shared_state.get_device_name(device_guid)
            for mode in self.latched_events[device_guid].keys():
                for key_pair in self.latched_events[device_guid][mode]:
                    identifier = self.latched_events[device_guid][mode][key_pair]
                    if isinstance(identifier, gremlin.ui.keyboard_device.KeyboardInputItem):
                        if isinstance(key_pair, tuple):
                            scan_code, is_extended = key_pair
                            key_data = f"scan code: 0x{scan_code:X}  extended: {is_extended}"
                        else:
                            key_data = str(key_pair)
                        syslog.info(f"\tDevice ID: {device_name} mode: {mode} pair: {key_data} data: {identifier.to_string()}")

        syslog.info("------------ Execution callbacks ----------------")
        for device_guid in self.callbacks.keys():
            for mode in self.callbacks[device_guid].keys():
                for key in self.callbacks[device_guid][mode]:
                    event = self.callback_key_map[key]
                    self.dump_exectree(device_guid, mode, event)

    def add_latched_functor(self, device_guid, mode, event, functor):
        """registers an extra latched functor on inputs if a functor uses multiple inputs"""
        # regular event
        if isinstance(device_guid, str):
            # convert to GUID
            device_guid = gremlin.util.parse_guid(device_guid)

        if device_guid not in self.latched_functors:
            self.latched_functors[device_guid] = {}
        if mode not in self.latched_functors[device_guid]:
            self.latched_functors[device_guid][mode] = {}
        key = event.callbackKey
        if key not in self.latched_functors[device_guid][mode]:
            self.latched_functors[device_guid][mode][key] = []
        existing_ids = [f.id for f in self.latched_functors[device_guid][mode][key]]
        if functor.id not in existing_ids:
            self.latched_functors[device_guid][mode][key].append(functor)
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                device_name = gremlin.joystick_handling.device_name_from_guid(device_guid)
                syslog.info(f"Added latched functor: {device_name} mode: {mode} type: {event.event_type.name} input: {event.identifier}  key: {key}")

    def _matching_input_item(self, mode, event):
        """gets the matching input item from the event"""

        device_guid = event.device_guid
        input_type = event.event_type
        if input_type == InputType.Keyboard:
            input_type = InputType.KeyboardLatched
        if input_type == InputType.KeyboardLatched:
            magic = json.dumps(event.identifier)
        else:
            magic = event.identifier

        if device_guid not in self.input_item_map:
            return None
        if mode not in self.input_item_map[device_guid]:
            return None
        if input_type not in self.input_item_map[device_guid][mode]:
            return None
        if magic in self.input_item_map[device_guid][mode][input_type]:
            return self.input_item_map[device_guid][mode][input_type][magic]

        # syslog.info(f"No match: {input_type} {magic}")
        # for key in self.input_item_map[device_guid][mode][input_type].keys():
        # 	syslog.info(f"\t{key}")
        return None

    def registerInputItem(self, mode: str, input_item):
        """registers an input item with the event handler"""
        item: gremlin.input_item.InputItem = input_item
        device_guid = item.device_guid
        input_type = item.input_type
        if input_type == InputType.Keyboard:
            input_type = InputType.KeyboardLatched

        if input_type == InputType.KeyboardLatched:
            # use the key sequence as the magic key
            magic = json.dumps(input_item.key_tuple)
        else:
            magic = item.input_id

        if device_guid not in self.input_item_map:
            self.input_item_map[device_guid] = {}
        if mode not in self.input_item_map[device_guid]:
            self.input_item_map[device_guid][mode] = {}
        if input_type not in self.input_item_map[device_guid][mode]:
            self.input_item_map[device_guid][mode][input_type] = {}
        self.input_item_map[device_guid][mode][input_type][magic] = input_item

        verbose = gremlin.config.Configuration().verbose_mode_inputs
        if verbose:
            syslog.info(f"Register InputItem: {input_item.display_name} mode {mode} {input_type} magic: {magic}")

    def addCallback(self, device_guid: dinput.GUID, mode: str, event: Event, callback: Callable, permanent=False, node=None):
        """Installs the provided callback for the given event.

        :param device_guid the GUID of the device the callback is
                associated with
        :param mode the name of the mode the callback belongs to
        :param event the event for which to install the callback
        :param callback the callback function to link to the provided
                event
        :param permanent if True the callback is always active even
                if the system is paused
        :node: the execution tree node
        """
        import gremlin.config
        import gremlin.keyboard
        import gremlin.ui.keyboard_device

        assert isinstance(device_guid, dinput.GUID), "invalid device GUID"
        assert isinstance(callback, Callable), "Callback must be provided and be a callable"
        assert mode is not None and mode != "", "invalid mode"
        assert isinstance(event, Event) if event is not None else True, "invalid event"

        valid_devices_map = gremlin.joystick_handling.getValidJoystickDevicesMap()  # list of valid joystick devices

        if event:
            if event.event_type in (InputType.Keyboard, InputType.KeyboardLatched):
                verbose = gremlin.config.Configuration().verbose_mode_keyboard
                # keyboard latched event
                identifier = event.identifier  # Key()
                if isinstance(identifier, gremlin.ui.keyboard_device.KeyboardInputItem):
                    primary_key = identifier.key
                elif isinstance(identifier, gremlin.keyboard.Key):
                    primary_key = identifier
                else:
                    syslog.error(f"AddCallback: Unexpected keyboard identifier type: {type(identifier)}, expecting Key or KeyboardInputItem")
                    raise ValueError(f"Unexpected keyboard identifier type: {type(identifier)}, expecting Key or KeyboardInputItem")




                # verbose = True
                # if the key can latch with multiple primary keys, build the table of all combinations
                key_list = [primary_key]
                if primary_key.is_latched:
                    # multiple keys
                    key_list.extend(primary_key._latched_keys)

                for key in key_list:
                    # the events will arrive as keyboard events - in any order - this makes sure latching is checked regardless of the order of key presses
                    virtual_code = key.virtual_code
                    keyid_source = key.index_tuple()  # use the scan code for now
                    # index = virtual_code if virtual_code > 0 else keyid
                    keyid = gremlin.keyboard.KeyMap.translate(keyid_source)

                    if device_guid not in self.latched_events.keys():
                        self.latched_events[device_guid] = {}

                    if mode not in self.latched_events[device_guid].keys():
                        self.latched_events[device_guid][mode] = {}
                    if keyid not in self.latched_events[device_guid][mode].keys():
                        self.latched_events[device_guid][mode][keyid] = []
                    self.latched_events[device_guid][mode][keyid].append(identifier)
                    if verbose:
                        syslog.info(
                            f"Key latch registered by guid {device_guid}  mode: {mode} vk: {virtual_code} (0x{virtual_code:X}) source keyid: [{gremlin.keyboard.KeyMap.keyid_tostring(keyid_source)}]-> translated keyId: [{gremlin.keyboard.KeyMap.keyid_tostring(keyid)}] name: {key.name} -> {identifier.display_name}  Primary key: [{primary_key}]"
                        )

                if device_guid not in self.latched_callbacks.keys():
                    self.latched_callbacks[device_guid] = {}
                if mode not in self.latched_callbacks[device_guid].keys():
                    self.latched_callbacks[device_guid][mode] = {}
                if key not in self.latched_callbacks[device_guid][mode]:
                    self.latched_callbacks[device_guid][mode][primary_key] = []
                data = self.latched_callbacks[device_guid][mode][primary_key]
                data.append((self._install_plugins(callback), permanent))
                return

            elif event.event_type == InputType.Midi:
                # MIDI event
                verbose = gremlin.config.Configuration().verbose_mode_midi
                midi_input = event.identifier
                key = midi_input.message_key
                if device_guid not in self.midi_callbacks.keys():
                    self.midi_callbacks[device_guid] = {}
                if mode not in self.midi_callbacks[device_guid].keys():
                    self.midi_callbacks[device_guid][mode] = {}
                if key not in self.midi_callbacks[device_guid][mode]:
                    self.midi_callbacks[device_guid][mode][key] = []
                data = self.midi_callbacks[device_guid][mode][key]
                data.append((self._install_plugins(callback), permanent))
                if verbose:
                    syslog.info(f"MIDI: register callback {mode} {key}")

            elif event.event_type == InputType.OpenSoundControl:
                # OSC event
                verbose = gremlin.config.Configuration().verbose
                osc_input = event.identifier
                key = osc_input.message_key
                if device_guid not in self.osc_callbacks.keys():
                    self.osc_callbacks[device_guid] = {}
                if mode not in self.osc_callbacks[device_guid].keys():
                    self.osc_callbacks[device_guid][mode] = {}
                if key not in self.osc_callbacks[device_guid][mode]:
                    self.osc_callbacks[device_guid][mode][key] = []
                data = self.osc_callbacks[device_guid][mode][key]
                data.append((self._install_plugins(callback), permanent))

            elif event.event_type == InputType.State:
                verbose = gremlin.config.Configuration().verbose
                state_input = event.identifier
                key = state_input.message_key
                if device_guid not in self.state_callbacks.keys():
                    self.state_callbacks[device_guid] = {}
                # these callbacks work in multi modes
                modes = gremlin.shared_state.current_profile.get_modes()
                for mode in modes:
                    if mode not in self.state_callbacks[device_guid].keys():
                        self.state_callbacks[device_guid][mode] = {}
                    if key not in self.state_callbacks[device_guid][mode]:
                        self.state_callbacks[device_guid][mode][key] = []
                    data = self.state_callbacks[device_guid][mode][key]
                    data.append((self._install_plugins(callback), permanent))

            else:
                # regular event - events are stored by the event key
                verbose = gremlin.config.Configuration().verbose
                if event.event_type != InputType.ModeControl and device_guid not in valid_devices_map:
                    device = gremlin.joystick_handling.getDevice(device_guid)
                    if verbose:
                        syslog.info(f"CALLBACK: device [{device.name}] [{device.device_id}] is disabled in callbacks ")
                    return

                if device_guid not in self.callbacks:
                    self.callbacks[device_guid] = {}
                if mode not in self.callbacks[device_guid]:
                    self.callbacks[device_guid][mode] = {}
                key = event.callbackKey
                if key not in self.callbacks[device_guid][mode]:
                    self.callbacks[device_guid][mode][key] = []
                    self.callback_key_map[key] = event
                self.callbacks[device_guid][mode][key].append((self._install_plugins(callback), permanent))

    def _matching_event_keys(self, event):
        """gets the list of latched keys for this event"""
        if event.event_type not in (
            InputType.Keyboard,
            InputType.KeyboardLatched,
            InputType.Mouse,
        ):
            # not a keyboard event
            return []
        import gremlin.config
        import gremlin.keyboard

        config = gremlin.config.Configuration()

        # convert mouse events to keyboard event
        if event.event_type == InputType.Mouse:
            from gremlin.ui.keyboard_device import KeyboardDeviceTabWidget

            device_guid = KeyboardDeviceTabWidget.device_guid

            mouse_button = event.identifier
            # convert the mouse button to the virtual scan code we use for mouse events
            index = ((mouse_button.value + 0x1000, False), 0)
            verbose = config.verbose_mode_mouse_input and config.verbose_mode_inputs
            if verbose:
                syslog.info(f"matching mouse event {event.identifier} to {gremlin.keyboard.KeyMap.keyid_tostring(index)}")
        else:
            # keyboard event
            verbose = config.verbose_mode_keyboard and config.verbose_mode_inputs
            device_guid = event.device_guid
            # index = event.virtual_code if event.virtual_code > 0 else event.identifier  # this is (scan_code, is_extended)
            index = gremlin.keyboard.KeyMap.translate(event.identifier)
            if verbose:
                syslog.info(f"matching key event {event.identifier} to {gremlin.keyboard.KeyMap.keyid_tostring(index)}")

        # event_key = Key(scan_code = identifier[0], is_extended = identifier[1], is_mouse = is_mouse, virtual_code= virtual_code)
        input_items = []

        if device_guid in self.latched_events:
            # print (f"found guid: {device_guid}")
            data = self.latched_events[event.device_guid]
            if self.runtime_mode in data.keys():
                data = data[self.runtime_mode]
                matching_keys = []
                # ensure index is the correct format
                (a, b), c = index
                if a == 0x1000 + 2:
                    pass
                if index in data:
                    # print ("found identifier")
                    matching_keys = data[index]

                if not matching_keys:
                    index_ex = (index[0], not index[1])
                    if index_ex in data.keys():
                        matching_keys = data[index_ex]

                for input_item in matching_keys:
                    # key = input_item.key
                    input_items.append(input_item)

                if verbose:
                    syslog.info(f"KEY: found {len(input_items)} matching items")
                return input_items

        return []

    def build_event_lookup(self, inheritance_tree):
        """Builds the lookup table linking event to callback.

        This takes mode inheritance into account.

        :param inheritance_tree the tree of parent and children in the
                inheritance structure
        """
        # Propagate events from parent to children if the children lack
        # handlers for the available events
        callbacks_list = [self.callbacks, self.latched_callbacks, self.latched_events]

        # build the inheritance modes
        node = inheritance_tree
        if node.name:
            parent = node.name
            children = [n.name for n in node.children]

            # Each device is treated separately
            for callback_items in callbacks_list:
                for device_guid in callback_items:
                    # Only attempt to copy handlers if we have any available in
                    # the parent mode
                    if parent in callback_items[device_guid]:
                        device_cb = callback_items[device_guid]
                        parent_cb = device_cb[parent]
                        # Copy the handlers into each child mode, unless they
                        # have their own handlers already defined
                        for child in children:
                            if child not in device_cb:
                                device_cb[child] = {}
                            for event, callbacks in parent_cb.items():
                                if isinstance(event, gremlin.event_handler.Event):
                                    key = event.callbackKey
                                else:
                                    key = event
                                if key not in device_cb[child]:
                                    device_cb[child][key] = callbacks

        # Recurse until we've dealt with all modes
        for child in node.children:
            self.build_event_lookup(child)

    def change_profile(self, new_profile):
        """requests a profile load"""
        if new_profile != gremlin.shared_state.current_profile:
            self.profile_change.emit(new_profile)

    def set_mode(self, new_mode):
        """sets the edit or runtime mode based on the state"""
        assert new_mode, "Mode cannot be blank"
        if gremlin.shared_state.is_running:
            gremlin.shared_state.runtime_mode = new_mode
        else:
            gremlin.shared_state.edit_mode = new_mode

    def set_runtime_mode(self, new_mode):
        """sets the active runtime mode"""
        assert new_mode, "Mode cannot be blank"
        gremlin.shared_state.runtime_mode = new_mode
        el = EventListener()
        el.update_mode_status_bar.emit(new_mode)

    def set_edit_mode(self, new_mode):
        """sets the active edit mode"""
        assert new_mode, "Mode cannot be blank"
        gremlin.shared_state.edit_mode = new_mode
        el = EventListener()
        el.update_mode_status_bar.emit(new_mode)

    @QtCore.Slot(str)
    def _update_mode_change(self, mode):
        config = gremlin.config.Configuration()
        if config.tts_mode_switch_enabled:
            # output verbal notification if requested
            data = self._last_tts_data
            profile = gremlin.shared_state.current_profile
            if data.mode is None or data.profile is None or data.mode != mode or data.profile != profile:
                self._last_tts_data.mode = mode
                self._last_tts_data.profile = profile
                tts = gremlin.tts.TextToSpeech()
                rate = gremlin.config.Configuration().initial_load_rate_tts
                tts.speak(f"New mode {mode}", rate)  # default rate is 100

    def TTSNotify(self, text):
        """outputs a notification only if TTS notifications are enabled and the profile/mode is different from the last message issued"""
        config = gremlin.config.Configuration()
        if config.tts_mode_switch_enabled:
            data = self._last_tts_data
            profile = gremlin.shared_state.current_profile
            mode = gremlin.shared_state.current_mode
            if data.mode is None or data.profile is None or data.mode != mode or data.profile != profile:
                self._last_tts_data.mode = mode
                self._last_tts_data.profile = profile
                rate = config.initial_load_rate_tts
                tts = gremlin.tts.TextToSpeech()
                tts.speak(text, rate)  # default rate is 100

    def registerModeChangeHook(self, id: str, callback):
        """adds a callback hook for mode changes"""
        self._mode_change_hooks[id] = callback

    def unregisterModeChangeHook(self, id: str):
        """removes a change mode callback hook"""
        if id in self._mode_change_hooks:
            del self._mode_change_hooks[id]

    def ModeChangeAllowed(self) -> bool:
        """true if a mode change is not suspended"""
        return self._mode_change_allowed()

    def ModeChangeSuspended(self) -> bool:
        """true if a mode change is suspended"""
        return not self._mode_change_allowed()

    def _mode_change_allowed(self) -> bool:
        """checks if a mode change is allowed right now"""
        if self._mode_change_hooks:
            for id, callback in self._mode_change_hooks.items():
                result = callback(id)
                if not result:
                    return False
            return True
        return True

    def queueModeChange(self, new_mode: str, args: tuple):
        """request a mode change using the mode stack"""
        with self._lock:
            self._change_mode_queue.append((new_mode, args))
            config = gremlin.config.Configuration()
            if config.verbose_mode_macro or config.verbose_mode_sequence:
                syslog.info(f"MODE QUEUE: queue mode [{new_mode}] queue depth: [{len(self._change_mode_queue)}]")

    def _execute_runner(self):
        """mode change runner - watches for mode change requests and changes mode if a mode change is allowed"""
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_macro or config.verbose_mode_sequence
        while not self._execute_thread.stopped():
            if len(self._change_mode_queue):
                if self.ModeChangeAllowed():
                    with self._lock:
                        # get the most recent mode pushed on the queue
                        new_mode, args = self._change_mode_queue.popleft()
                        self._change_mode_queue.clear()  # remove all items

                    if verbose:
                        syslog.info(f"MODE QUEUE RUNNER: deqeue mode [{new_mode}]")
                    # clear the queue of all other mode changes that accumulated

                    # run the mode change
                    if new_mode != self.current_mode:
                        self._change_mode(new_mode, args)

            else:
                time.sleep(0.05)

    def change_mode(self, new_mode, emit=True, force_update=False, tts=True, validate=True):
        args = (emit, force_update, tts, validate)
        if gremlin.shared_state.is_running and self._mode_queue_enabled:
            # runtime - queue the request based on options
            self.queueModeChange(new_mode, args)
        else:
            # do not queue the request
            self._change_mode(new_mode, args)

    def registerModeChangeCallback(self, callback: Callable[[str, str], bool]):
        """registers a mode change callback"""
        if callback not in self._mode_change_callbacks:
            self._mode_change_callbacks.append(callback)

    def unregisterModeChangeCallback(self, callback: Callable[[str, str], bool]):
        """removes a registered mode change callback"""
        if callback in self._mode_change_callbacks:
            self._mode_change_callbacks.remove(callback)

    def clearModeChangeCallbacks(self):
        """clears all mode change callbacks"""
        self._mode_change_callbacks.clear()

    def _update_mode_selectors(self, mode: str):
        """updates UI drop downs"""

        # if not is_running:
        # check the UI is updated to the correct mode
        el = EventListener()
        verbose = gremlin.config.Configuration().verbose_mode_ui
        if verbose:
            syslog.info(f"Mode: update selector to: [{mode}]")
        el.edit_mode_ui_update.emit(mode)

    def _change_mode(self, new_mode: str, args: tuple = None):
        """Changes the GremlinEx currently active mode.

        :param new_mode: the new mode to use
        :param emit: enables signal
        :param force_update: forces a mode change even if already in the mode
        :param validate: validates change mode, set to false to remove validation
        """

        import gremlin.ui.mode_device

        emit, force_update, tts, validate = args

        is_running = gremlin.shared_state.is_running

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_ui or config.verbose_mode_mode
        verbose_detail = verbose and config.verbose_mode_detailed
        current_profile = gremlin.shared_state.current_profile

        if verbose_detail:
            if is_running:
                syslog.info(
                    f"CHANGE MODE: (runtime) change mode to [{new_mode}] requested - active mode: [{gremlin.shared_state.runtime_mode}]  current mode: [{gremlin.shared_state.current_mode}] profile '{current_profile.name}'"
                )
            else:
                syslog.info(
                    f"CHANGE MODE: (edit time) change mode to [{new_mode}] requested - active mode: [{gremlin.shared_state.runtime_mode}]  current mode: [{gremlin.shared_state.current_mode}] profile '{current_profile.name}'"
                )

        try:
            if new_mode == self.current_mode and not force_update:
                # already in this mode
                return

            # run through mode change callbacks
            if is_running and self._mode_change_callbacks:
                for callback in self._mode_change_callbacks:
                    if not callback(new_mode, self.current_mode):
                        if verbose:
                            syslog.info(f"CHANGE MODE: (runtime): ignore request to change to mode [{new_mode}]: validation callback failed")
                        return

            try:
                el = EventListener()
                el.push_input_selection()

                # find the mode in the profile
                mode_exists = current_profile.modeExists(new_mode)

                if not mode_exists:
                    for device in self.callbacks.values():
                        if new_mode in device:
                            mode_exists = True

                if not mode_exists:
                    for device in self.osc_callbacks.values():
                        if new_mode in device:
                            mode_exists = True

                if not mode_exists:
                    for device in self.midi_callbacks.values():
                        if new_mode in device:
                            mode_exists = True

                if not mode_exists:
                    for device in self.latched_callbacks.values():
                        if new_mode in device:
                            mode_exists = True

                if not mode_exists:
                    # import gremlin.config
                    # verbose = gremlin.config.Configuration().verbose
                    # if verbose:
                    syslog.warning(
                        f"CHANGE MODE: Mode Change Error: The mode \"{new_mode}\" does not exist or has no associated callbacks - profile '{current_profile.name}'"
                    )
                    syslog.warning("\tValid profile modes:")
                    current_profile.dumpModeTree("\t\t")
                    return

                if is_running:
                    # runtime event (prevents UI from reloading)
                    # if verbose:
                    # 	syslog.info(f"EVENT: (runtime) change mode to [{new_mode}] requested - active mode: [{gremlin.shared_state.runtime_mode}]  current mode: [{gremlin.shared_state.current_mode}] profile '{current_profile.name}'")

                    if self.runtime_mode != new_mode or force_update:
                        import gremlin.shared_state

                        device_guid = gremlin.shared_state.mode_tab_guid
                        mode_enter = gremlin.ui.mode_device.ModeInputModeType.ModeEnter
                        mode_exit = gremlin.ui.mode_device.ModeInputModeType.ModeExit
                        delay = 0.250  # delay in seconds between press/release events for mode control change

                        # fire off any mode changes
                        event_old_mode_exit_pressed = Event(
                            InputType.ModeControl,
                            identifier=mode_exit,
                            device_guid=device_guid,
                            is_pressed=True,
                            mode=self.runtime_mode,
                            override_input_type=InputType.JoystickButton,
                        )
                        event_old_mode_exit_released = Event(
                            InputType.ModeControl,
                            identifier=mode_exit,
                            device_guid=device_guid,
                            is_pressed=False,
                            mode=self.runtime_mode,
                            override_input_type=InputType.JoystickButton,
                        )

                        event_new_mode_enter_pressed = Event(
                            InputType.ModeControl,
                            identifier=mode_enter,
                            device_guid=device_guid,
                            is_pressed=True,
                            mode=new_mode,
                            override_input_type=InputType.JoystickButton,
                        )
                        event_new_mode_enter_released = Event(
                            InputType.ModeControl,
                            identifier=mode_enter,
                            device_guid=device_guid,
                            is_pressed=False,
                            mode=new_mode,
                            override_input_type=InputType.JoystickButton,
                        )

                        # fire mode change control for mode exit (press + release)
                        m1_list, f1_list = self.execute_event(event_old_mode_exit_pressed)
                        if m1_list or f1_list:
                            # callback = self._create_change_mode_callback(event_old_mode_exit_pressed, m1_list, f1_list)
                            # mode_exit_press = Timer(delay, callback)
                            # mode_exit_press.start()

                            callback = self._create_change_mode_callback(event_old_mode_exit_released, m1_list, f1_list)
                            mode_exit_release = Timer(delay, callback)
                            mode_exit_release.start()

                        # CHANGE THE MODE

                        if validate:
                            result = self.runModeValidator(new_mode)
                            if not result:
                                syslog.warning(
                                    f"CHANGE MODE: {current_profile.name} - mode change request to {new_mode} not authorized by a module - request ignored"
                                )
                                return

                        self.previous_runtime_mode = self.runtime_mode
                        gremlin.shared_state.runtime_mode = new_mode
                        # remember the last mode for this profile

                        self.previous_runtime_mode = self.runtime_mode
                        self.runtime_mode = new_mode
                        if verbose:
                            syslog.info(f"CHANGE MODE: [{current_profile.name}] - Runtime Mode switch to: {new_mode}")
                        if emit:
                            el.runtime_mode_changed.emit(new_mode)
                            el.update_mode_status_bar.emit(new_mode)

                        # fire mode change for mode enter (press + release)
                        m2_list, f2_list = self.execute_event(event_new_mode_enter_pressed)
                        if m2_list or f2_list:
                            # callback = self._create_change_mode_callback(event_new_mode_enter_pressed, m2_list, f2_list)
                            # mode_enter_press = Timer(delay, callback)
                            # mode_enter_press.start()

                            callback = self._create_change_mode_callback(event_new_mode_enter_released, m2_list, f2_list)
                            mode_enter_release = Timer(delay, callback)
                            mode_enter_release.start()

                else:
                    # non-runtime
                    assert new_mode, "new mode cannot be blank"
                    if self.edit_mode != new_mode or force_update:
                        gremlin.config.Configuration().set_profile_last_edit_mode(new_mode)
                        gremlin.shared_state.edit_mode = new_mode
                        self.edit_mode = new_mode
                        if verbose:
                            syslog.info(f"Profile: {current_profile.name} - Design time Mode switch to: {new_mode}")
                        if emit:
                            el.edit_mode_changed.emit(self.edit_mode)

                # update the status bar
                self.mode_status_update.emit()

                # update the selection
                device_guid, input_type, input_id = gremlin.config.Configuration().get_last_input()
                if input_type and input_id:
                    el.select_input.emit(device_guid, input_type, input_id, False, True, False, None)

                # fire the UI update on change mode
                el.update_input_state.emit(device_guid)  # force a UI widget status update
            finally:
                el.pop_input_selection()

        finally:
            # sync visual selectors
            self._update_mode_selectors(self.current_mode)

    def _create_change_mode_callback(self, event, m_list, f_list):
        """gets a return callback for mode changes"""
        return lambda: self._execute_callbacks(event, m_list, f_list)

    def resume(self):
        """Resumes the processing of callbacks."""
        self.process_callbacks = True
        self.is_active.emit(self.process_callbacks)

    def pause(self):
        """Stops the processing of callbacks."""
        self.process_callbacks = False
        self.is_active.emit(self.process_callbacks)

    def toggle_active(self):
        """Toggles the processing of callbacks on or off."""
        self.process_callbacks = not self.process_callbacks
        self.is_active.emit(self.process_callbacks)

    def clear(self):
        """Removes all attached callbacks."""
        self.callbacks = {}
        self.callback_key_map.clear()
        self.latched_callbacks = {}
        self.midi_callbacks = {}
        self.osc_callbacks = {}
        self.state_callbacks = {}

    def execute_event(self, event: Event, skip_execute=False):
        """main execution (runtime) event handler - queues trigger callbacks on event input

        :param event: the event to run callbacks for
        :param skip_execute: optional, prevents callback execution if they are executed another way
        :returns: tuple list of callbacks

        """

        import gremlin.config
        import gremlin.keyboard

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_inputs or config.verbose_mode_exec
        verbose_detailed = verbose and config.verbose_mode_extra

        self.registry.update(event)  # record the event

        try:
            # if verbose: syslog.info("EVENT EXECUTE: enter critical phase")

            # self._lock.acquire()

            # mode to act on
            mode = event.mode if event.mode else self.runtime_mode

            if verbose and event.event_type != InputType.JoystickAxis:
                syslog.info(f"EVENT EXECUTE: process event - mode [{mode}] event: {str(event)}")
                if event.event_type == InputType.JoystickButton:
                    pass

            # list of callbacks
            m_list = []
            f_list = []

            input_item = self._matching_input_item(mode, event)
            if input_item is not None and not input_item.enabled:
                # input item registered but not enabled - ignore inputs that aren't registered or could not be found (latched keys for example)
                if verbose:
                    syslog.info(f"Event: input disabled {str(event)}")
                return

            # filter latched keyboard or mouse events
            if event.event_type in (
                InputType.Keyboard,
                InputType.KeyboardLatched,
                InputType.Mouse,
            ):
                verbose = gremlin.config.Configuration().verbose_mode_detailed
                data = event.data  # holds keyboard state info
                if event.event_type == InputType.Mouse:
                    verbose = gremlin.config.Configuration().verbose_mode_mouse
                if verbose:
                    syslog.info(f"process keyboard event: {event}")
                    syslog.info("\tKeyboard state data:")
                    keys = list(data.keys())
                    for key in keys:
                        syslog.info(f"\t\t{gremlin.keyboard.KeyMap.keyid_tostring(key)} {data[key]}")

                items = self._matching_event_keys(event)  # returns list of primary keys
                if items:
                    if verbose:
                        syslog.info(f"Matched keys for mode: [{mode}]  event {event} pressed: {event.is_pressed} keys: {len(items)} ")
                        for index, input_item in enumerate(items):
                            syslog.info(f"\t[{index}]: {input_item.name}")

                    for input_item in items:
                        if verbose:
                            syslog.info("-" * 50)
                        is_latched = True
                        latch_key = None
                        # print (data)
                        latched_keys = [input_item]
                        latched_keys.extend(input_item.latched_keys)
                        if verbose:
                            syslog.info(f"KEY: Checking latching: {len(latched_keys)} key(s)")
                        if len(latched_keys) > 1:
                            # key is latched - check the other keys are also pressed
                            for k in latched_keys:
                                index = k.index_tuple()
                                found = index in data.keys()
                                if not found:
                                    # try the reverse translate
                                    r_index = gremlin.keyboard.KeyMap.reverse_translate(index)
                                    if r_index is not None:
                                        found = r_index in data.keys()
                                        if found:
                                            index = r_index

                                state = data[index] if found else False
                                if verbose:
                                    syslog.info(
                                        f"\tcheck latched key: {gremlin.keyboard.KeyMap.keyid_tostring(index)} {k.name} found: {found} state: {state} {'*****' if state else ''}"
                                    )
                                    if not found:
                                        syslog.info("\t\t* Key not found *")
                                is_latched = is_latched and state  # make sure all latched keys are currently pressed (state = True)

                        if verbose:
                            syslog.info(f"\tLatched state: {is_latched}")

                        if is_latched:
                            latch_key = input_item.key

                        if latch_key:
                            # override the event type for keyboard so actions treat mouse/kbd input as a joystick button for mapping purposes
                            import gremlin.keyboard
                            assert isinstance(latch_key, gremlin.keyboard.Key), f"invalid key type, got {type(latch_key)} - expecting [gremlin.keyboard.Key]"
                            event.override_input_type = InputType.JoystickButton

                            m_list = self._matching_latched_callbacks(event, latch_key)

                            if m_list:
                                if verbose:
                                    trigger_line = "***** TRIGGER " + "*" * 30
                                    syslog.info(trigger_line)
                                    syslog.info(f"\tmode: [{mode}] Found latched key: Check key {latch_key.name} callbacks: {len(m_list)} event: {event}")
                                    syslog.info(trigger_line)
                                self._trigger_callbacks(m_list, event)
                            return

                    verbose = gremlin.config.Configuration().verbose_mode_inputs
                else:
                    if verbose:
                        syslog.info("No matching events")
                return None, None

            elif event.event_type == InputType.Midi:
                m_list = self._matching_midi_callbacks(event)
                if verbose_detailed and not (m_list or f_list):
                    syslog.info(f"EVENT: [MIDI] no matching inputs for {str(event.identifier.message_key)} mode: {self.runtime_mode}")

            elif event.event_type == InputType.OpenSoundControl:
                m_list = self._matching_osc_callbacks(event)
                if verbose_detailed and not (m_list or f_list):
                    syslog.info(f"EVENT: [OSC] no matching inputs for {event.identifier.message_key} mode: {self.runtime_mode}")
            elif event.event_type == InputType.State:
                m_list = self._matching_state_callbacks(event)
                if verbose_detailed and not (m_list or f_list):
                    syslog.info(f"EVENT: [STATE] no matching inputs for {event.identifier.message_key} mode: {self.runtime_mode}")
            elif event.event_type == InputType.JoystickAxis:
                m_list = self._matching_callbacks(event)
                f_list = self._matching_functors(event)
                if verbose_detailed and not (m_list or f_list):
                    syslog.info(f"EVENT: [Joystick] no matching inputs for {str(event.identifier)} mode: {self.runtime_mode}")
            elif event.event_type in (
                InputType.JoystickButton,
                InputType.JoystickHat,
                InputType.OctaviIfr1,
                InputType.ModeControl,
            ):

                m_list = self._matching_callbacks(event)
                f_list = self._matching_functors(event)

                if not (m_list or f_list):
                    if verbose_detailed:
                        syslog.info(f"EVENT: [Joystick] no matching inputs for {str(event.identifier)} mode: {self.runtime_mode}")
                else:
                    if verbose:
                        syslog.info(
                            f"EVENT: [Joystick] found callbacks for {str(event.identifier)} mode: {self.runtime_mode}  m: {len(m_list)} f: {len(f_list)}"
                        )
                # if verbose_detailed and not (m_list or f_list): syslog.info(f"EVENT: [Joystick] no matching inputs for {str(event.identifier)} mode: {self.runtime_mode}")
            else:
                # other inputs including control inputs

                m_list = self._matching_callbacks(event)
                f_list = self._matching_functors(event)

                if verbose_detailed and not (m_list or f_list):
                    syslog.info(f"EVENT: [Generic] no matching inputs for {str(event.identifier)} mode: {self.runtime_mode}")

            if not skip_execute and (m_list or f_list):
                # self._queue_add(event, m_list, f_list)
                self._execute_callbacks(event, m_list, f_list)

            return m_list, f_list
        except Exception as err:
            syslog.error(f"EVENT EXECUTE: error: {err}\n{traceback.format_exc()}")
        finally:
            # if verbose: syslog.info("EVENT EXECUTE: exit critical phase")
            # self._lock.release()
            pass

    def _trigger_callbacks(self, callbacks, event):
        """trigger regular callbacks"""
        # verbose = gremlin.config.Configuration().verbose'
        # if event.event_type == InputType.State and event.is_pressed == False:
        # 	pass
        for cb in callbacks:
            try:
                # if verbose:
                # 	syslog.info(f"CALLBACK: execute start")
                cb(event)
                # if verbose:
                # 	syslog.info(f"CALLBACK: execute done")
            except Exception as ex:
                syslog.error(f"CALLBACK: error {ex}")
                tb_msg = traceback.format_exc()
                syslog.error(tb_msg)

    def _trigger_functor_callbacks(self, functors, event: Event):
        """trigger functor callbacks"""
        # verbose = gremlin.config.Configuration().verbose'
        import gremlin.actions

        for functor in functors:
            try:
                value = gremlin.actions.Value(event.value)
                functor.process_event(event, value)
            except Exception as ex:
                syslog.error(f"FUNCTOR CALLBACK: error {ex}")
                tb_msg = traceback.format_exc()
                syslog.error(tb_msg)

    def _execute_callbacks(self, event, m_list, f_list):
        """triggers callbacks"""
        if m_list:
            self._trigger_callbacks(m_list, event)

        if f_list:
            # latched
            self._trigger_functor_callbacks(f_list, event)

    def _matching_midi_callbacks(self, event):
        """returns list of callbacks matching the event"""
        callback_list = []
        if event.event_type == InputType.Midi:
            key = event.identifier.message_key
            # if event.identifier.command == gremlin.ui.midi_device.MidiCommandType.SysEx:
            # 		pass
            if event.device_guid in self.midi_callbacks:
                import gremlin.execution_graph

                ec = gremlin.execution_graph.ExecutionContext()  # current execution context
                # search callbacks for mode hierarchy
                callback_list = ec.getCallbacks(self.midi_callbacks[event.device_guid], key, self.runtime_mode)
                # callback_list = self.midi_callbacks[event.device_guid].get(
                # 	self.runtime_mode, {}
                # ).get(key, [])

        # Filter events when the system is paused
        if not self.process_callbacks:
            return [c[0] for c in callback_list if c[1]]
        else:
            return [c[0] for c in callback_list]

    def _matching_osc_callbacks(self, event):
        """returns list of callbacks matching the event"""
        callback_list = []
        if event.event_type == InputType.OpenSoundControl:
            key = event.identifier.message_key
            if event.device_guid in self.osc_callbacks:
                import gremlin.execution_graph

                ec = gremlin.execution_graph.ExecutionContext()  # current execution context
                # search callbacks for mode hierarchy
                callback_list = ec.getCallbacks(self.osc_callbacks[event.device_guid], key, self.runtime_mode)

            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_osc and config.verbose_mode_extra
            if verbose and not callback_list:
                # syslog = logging.getLogger("system")
                syslog.info(f"EVENT: OSC: no callbacks found for key: [{key}] mode: [{self.runtime_mode}]. This is normal if OSC input has no mappings.")

        # Filter events when the system is paused
        if not self.process_callbacks:
            return [c[0] for c in callback_list if c[1]]
        else:
            return [c[0] for c in callback_list]

    def _matching_state_callbacks(self, event):
        """returns list of callbacks matching the event"""
        import gremlin.execution_graph

        callback_list = []
        if event.event_type == InputType.State:
            key = event.identifier.message_key
            if event.device_guid in self.state_callbacks:
                ec = gremlin.execution_graph.ExecutionContext()  # current execution context
                # search callbacks for mode hierarchy
                callback_list = ec.getCallbacks(self.state_callbacks[event.device_guid], key, self.runtime_mode)

            # verbose = gremlin.config.Configuration().verbose_mode_state
            # if verbose and not callback_list:
            # 	syslog.info(f"STATE: state: [{key}] mode: [{self.runtime_mode}] has no callbacks. This is normal if state has no mappings.")

        # Filter events when the system is paused
        if not self.process_callbacks:
            return [c[0] for c in callback_list if c[1]]
        else:
            return [c[0] for c in callback_list]

    def _matching_functors(self, event) -> list:
        """gets the list of matching functors to call when an event occurs"""
        functors_list = []

        # mode we're looking for
        run_mode = event.mode if event.mode else self.runtime_mode

        mode_list = [run_mode]
        if event.extra_data:
            if "mode" in event.extra_data:
                mode_list = [event.extra_data["mode"]]
            if "target_mode" in event.extra_data:
                # override
                mode_list.append(event.extra_data["target_mode"])
        if event.extra_data and "mode" in event.extra_data:
            # override
            run_mode = event.extra_data["mode"]

        device_guid = event.device_guid
        if device_guid in self.latched_functors:
            for run_mode in mode_list:
                modes = gremlin.shared_state.current_profile.getModeHierarchy(run_mode)
                for mode in modes:
                    if mode in self.latched_functors[device_guid]:
                        key = event.callbackKey
                        if key in self.latched_functors[device_guid][mode]:
                            functors_list = self.latched_functors[device_guid][mode][key]
                            if functors_list:
                                break
        return functors_list

    def _matching_callbacks(self, event: Event):
        """Returns the list of callbacks to execute in response to
        the provided event.

        :param event the event for which to search the matching
                callbacks
        :return a list of all callbacks registered and valid for the
                given event
        """

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_details  # or config.verbose_mode_condition
        mode = event.mode if event.mode else self.runtime_mode  # mode we're looking for
        mode_list = [mode]
        if event.extra_data:
            if "mode" in event.extra_data:
                # override
                mode_list = [event.extra_data["mode"]]
            if "target_mode" in event.extra_data:
                # override
                mode_list.append(event.extra_data["target_mode"])

        # Obtain callbacks matching the event
        callback_list = []
        key = event.callbackKey
        device_guid = event.device_guid
        if device_guid in self.callbacks:
            for mode in mode_list:
                if mode in self.callbacks[device_guid]:
                    if key in self.callbacks[device_guid][mode]:
                        callback_list = self.callbacks[device_guid][mode][key]
                        if verbose:
                            event = self.callback_key_map[key]
                            self.dump_exectree(device_guid, mode, event)

        if verbose:
            syslog.info(f"CALLBACK: device: {gremlin.shared_state.get_device_name(event.device_guid)} mode: {self.runtime_mode} found: {len(callback_list)}")

        # Filter events when the system is paused
        if callback_list:
            if not self.process_callbacks:
                return [c[0] for c in callback_list if c[1]]
            else:
                return [c[0] for c in callback_list]

    def _matching_latched_callbacks(self, event, key):
        from gremlin.ui.keyboard_device import KeyboardDeviceTabWidget
        import gremlin.keyboard

        assert isinstance(key, gremlin.keyboard.Key), f"invalid key type, got {type(key)} - expecting [gremlin.keyboard.Key]"
        callback_list = []
        if event.event_type in (
            InputType.KeyboardLatched,
            InputType.Keyboard,
            InputType.Mouse,
        ):
            device_guid = KeyboardDeviceTabWidget.device_guid
            if device_guid in self.latched_callbacks:
                import gremlin.execution_graph

                ec = gremlin.execution_graph.ExecutionContext()  # current execution context
                # search callbacks for mode hierarchy
                callback_list = ec.getCallbacks(self.latched_callbacks[device_guid], key, self.runtime_mode)

        # Filter events when the system is paused
        if not self.process_callbacks:
            return [c[0] for c in callback_list if c[1]]
        else:
            return [c[0] for c in callback_list]

    def _install_plugins(self, callback):
        """Installs the current plugins into the given callback.

        :param callback the callback function to install the plugins into
        :return new callback with plugins installed
        """
        signature = inspect.signature(callback).parameters
        for keyword, plugin in self.plugins.items():
            if keyword in signature:
                callback = plugin.install(callback, functools.partial)
        return callback


@gremlin.singleton_decorator.SingletonDecorator
class VjoyRemapEventHandler(QtCore.QObject):
    grid_visible_changed = Signal(bool)  # occurs when a grid was updated

    def __init__(self):
        super().__init__()
        self.grid_visible_changed.connect(self._visible_changed)

    @QtCore.Slot(bool)
    def _visible_changed(self, visible: bool):
        """store setting for next time"""
        config = gremlin.config.Configuration()
        config.button_grid_visible = visible


_vjoy_remap_handler = VjoyRemapEventHandler()


@gremlin.singleton_decorator.SingletonDecorator
class JoystickState:
    """holds joystick input/output state flags"""

    def __init__(self):
        self._input_ignored_device_list = {}  # list of ignored devices (device_guid)
        self._output_ignored_device_list = {}  # list of ignored devices (device_guid)
        self._vjoy_output_ignored_list = {}  # list of ignored vjoy IDs for output (int)
        self._vjoy_as_input = {}  # map of VJOY devices used as input by GremlinEx

    def hook(self):
        el = EventListener()
        el.vjoy_as_input_changed.connect(self._vjoy_as_input_changed)  # hook vjoy as input changes
        el.profile_loaded.connect(self.reset)  # reset data on profile unload before a new profile is loaded

    def reset(self):
        """resets the ignored device list"""
        import gremlin.joystick_handling
        import gremlin.shared_state
        import gremlin.config

        self._input_ignored_device_list.clear()
        self._output_ignored_device_list.clear()
        self._vjoy_output_ignored_list.clear()
        self._vjoy_as_input.clear()

        """ reload on new profile """
        current_profile = gremlin.shared_state.current_profile
        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        for dev in gremlin.joystick_handling.all_joystick_devices():
            device_guid = gremlin.util.normalize_guid(dev.device_guid)
            # Octavi IFR1 exception - this is ignored because the device also reports in as a game controller - however we read data from it using HID directly, not dinput
            # Vendor: 0x1240 Product: 0x59094
            if dev.product_id == 59094 and dev.vendor_id == 1240 and dev.name == "IFR1":
                self.setInputEnabled(dev.device_guid, False)
                self.setOutputEnabled(device_guid, True)
            elif dev.is_virtual:
                is_input_enabled = current_profile.settings.vjoy_as_input.get(dev.vjoy_id, False) if current_profile else False
                is_output_enabled = True  # not is_input
                self.setInputEnabled(device_guid, is_output_enabled)
                self.setOutputEnabled(device_guid, is_input_enabled)
                self.setVjoyAsInput(dev.vjoy_id, is_input_enabled)

                if verbose:
                    syslog.info(f"VJOY: {dev.name} [{dev.vjoy_id}] used as {'input' if is_input_enabled else 'output'}")
            else:
                self.setInputEnabled(device_guid, False)
                self.setOutputEnabled(device_guid, True)

    def setVjoyAsInput(self, vid: int, enabled: bool):
        self._vjoy_as_input[vid] = enabled

    def vjoyAsInput(self, vid: int) -> bool:
        """true if vjoy device is also used as input"""
        if vid in self._vjoy_as_input:
            return self._vjoy_as_input[vid]
        return False

    def inputEnabled(self, device_guid) -> bool:
        """true if device input is enabled"""
        return not self.inputIgnored(device_guid)

    def inputIgnored(self, device_guid) -> bool:
        """true if the device input should be ignored"""
        id = gremlin.util.normalize_guid(device_guid) if not isinstance(device_guid, str) else device_guid
        if id in self._input_ignored_device_list:
            return self._input_ignored_device_list[id]
        return True  # ignore input by default

    def vjoyOutputIgnored(self, vid: int) -> bool:
        """true if VJOY output is ignored"""
        if vid in self._vjoy_output_ignored_list:
            return self._vjoy_output_ignored_list[vid]
        return False

    def outputIgnored(self, device_guid) -> bool:
        """true if the device output should be ignored"""
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
        if device_guid in self._output_ignored_device_list:
            return self._output_ignored_device_list[device_guid]
        return False

    def setInputEnabled(self, device_guid, enabled: bool):
        """marks a device as input ingnored"""
        import gremlin.config

        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
        if verbose:
            device = gremlin.joystick_handling.getDevice(device_guid)
            syslog.info(f"VJOY: {device.name} input: {'off' if enabled else 'on'}")
        self._input_ignored_device_list[device_guid] = not enabled
        if verbose:
            syslog.info("VJOY ")

    def setOutputEnabled(self, device_guid, enabled: bool):
        """marks a device as output ignored"""
        import gremlin.joystick_handling
        import gremlin.config

        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)
        self._output_ignored_device_list[device_guid] = not enabled
        device = gremlin.joystick_handling.getDevice(device_guid)
        if verbose:
            syslog.info(f"VJOY: {device.name} output: {'off' if enabled else 'on'}")
        if device.is_virtual:
            self._vjoy_output_ignored_list[device.vjoy_id] = not enabled

    def _vjoy_as_input_changed(self, vjoy_id: int, enabled: bool):
        dev = gremlin.joystick_handling.vjoy_info_from_vjoy_id(vjoy_id)
        if dev:
            # vjoy input is enabled, disable output to it
            device_guid = gremlin.util.normalize_guid(dev.device_guid)
            self.setOutputEnabled(device_guid, enabled)  # vjoy used as input cannot be used as output
            self.setInputEnabled(device_guid, not enabled)
            self.setVjoyAsInput(vjoy_id, enabled)


class AxisValues:
    """holds axis values"""

    __slots__ = ["actual", "raw", "calibrated", "curved", "merged"]

    def __init__(
        self, actual: float, raw: Optional[float] = None, calibrated: Optional[float] = None, curved: Optional[float] = None, merged: Optional[float] = None
    ):

        self.actual = actual
        self.raw = raw
        self.calibrated = calibrated
        self.curved = curved
        self.merged = merged

    @staticmethod
    def fromEvent(event: Event):
        """gets a new AxisValue object populated with event data"""
        data = AxisValues(event.value)
        extra_data = event.extra_data
        if extra_data is not None:
            if "calibrated" in extra_data and extra_data["calibrated"]:
                # has calibration data
                data.calibrated = extra_data["calibrated_value"]

            if "curved" in extra_data and extra_data["curved"]:
                # has a curve applied
                data.curved = event.curve_value

        return data

    def toList(self, strip=True) -> list:
        """converts to a value list - if strip is enabled - returns the sparse value without NULL entries"""
        if strip:
            has_calibration = self.calibrated is not None
            has_curve = self.curved is not None
            if has_calibration and has_curve:
                return [
                    self.raw,
                    self.actual,
                    self.calibrated,
                    self.curved,
                ]  # 4 bars = raw, computed, calibrated only, curve only, raw is top channel
            if has_calibration or has_curve:
                return [
                    self.raw,
                    self.actual,
                ]  # 2 bars (actual is calibrated or curved, second bar is raw input) - raw is top channel

            if self.merged:
                return [self.actual, self.merged]  # merged data

            return [self.actual]  # 1 bar no transforms

        return [
            self.raw,
            self.actual,
            self.calibrated,
            self.curved,
            self.merged,
        ]  # all channels

    def __getitem__(self, key):
        return self.toList()[key]

    def __str__(self):
        actual_stub = f"{self.actual:0.3f}" if self.actual is not None else "None"
        raw_stub = f"{self.raw:0.3f}" if self.raw is not None else "None"
        calibrated_stub = f"{self.calibrated:0.3f}" if self.calibrated is not None else "None"
        curved_stub = f"{self.curved:0.3f}" if self.curved is not None else "None"
        merged_stub = f"{self.merged:0.3f}" if self.merged is not None else "None"
        return f"AxisValues: actual: {actual_stub} raw: {raw_stub} calibrated: {calibrated_stub} curved: {curved_stub} merged: {merged_stub}"


class AxisData:
    """holds axis data"""

    def __init__(self, device_guid: str | dinput.GUID, input_id: int):
        """
        param: device_guid: the device guid for this axis
        param: input_id: the non linear input id for this axis (axis index)"""
        import gremlin.joystick_handling

        self.device_id = None
        self.device_guid = None
        self._device = None
        self.device_type = None

        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, "invalid device"
        assert input_id in device.axis_id_map, f"invalid axis input id [{input_id}] for device {device.name}"
        self.device_id = device.device_id
        self.device_guid = device.device_guid
        self._device = device
        self.device_type = device.device_type

        self.linear_id = device.getAxisLinearId(input_id)
        assert self.linear_id in device.linear_id_map, f"invalid axis linear id [{self.linear_id}] for input id [{input_id}] for device {device.name}"
        self.input_id = input_id
        self.actual_value = None  # computed value from last query
        self.raw_value = None
        self.calibrated_value = None
        self.curve_value = None

    @property
    def device(self) -> dinput.DeviceSummary:
        return self._device

    @property
    def hasCurve(self) -> bool:
        return self.curve_value is not None

    @property
    def hasCalibrated(self) -> bool:
        return self.calibrated_value is not None

    @property
    def hasValue(self) -> bool:
        return self.raw_value is not None

    @property
    def calibration(self):
        """returns the calibration data for this axis if it has any"""
        import gremlin.ui.axis_calibration

        calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(self.device_guid, self.linear_id)
        if calibration and calibration.hasData:
            return calibration
        return None

    def getAxisValues(self, value: float = None) -> AxisValues:
        """gets the axis value as an AxisValues named tuple

        :param value: optional - input value if known
        :param action: optiona - action requesting the value in case multiple curves are to be applied

        """
        import gremlin.ui.axis_calibration
        import gremlin.joystick_handling

        device_guid = self.device_guid
        input_id = self.input_id

        if not device_guid:
            return None

        # OSC input data

        # input value (raw value from stick)
        raw_value = value if value is not None else gremlin.joystick_handling.get_axis(device_guid, input_id)
        actual_value = raw_value
        self.raw_value = raw_value

        calibrated_value = None
        curve_value = None
        has_calibration = False
        has_curve = False

        calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(device_guid, input_id)
        if calibration and calibration.hasData:
            calibrated_value = calibration.getValue(raw_value, False)  # do not normalize, input is already -1 to +1
            actual_value = calibrated_value
            has_calibration = True

        astate = AxisState()
        curve_data = astate.getAxisCurve(device_guid, input_id)
        if curve_data:
            curve_value = curve_data.curve_value(actual_value)
            actual_value = curve_value
            has_curve = True

        self.actual_value = actual_value
        self.curve_value = curve_value
        self.calibrated_value = calibrated_value
        if not curve_data and not has_calibration:
            self.raw_value = None  # remove the raw value unless we also have a calibrated or curve value - the repeater only displays one value that way

        if has_curve and has_calibration:
            data = AxisValues(
                actual=self.actual_value,
                raw=raw_value,
                calibrated=self.calibrated_value,
                curved=self.curve_value,
            )
            return data

        if has_calibration:
            data = AxisValues(
                actual=self.actual_value,
                raw=raw_value,
                calibrated=self.calibrated_value,
            )
            return data
        if has_curve:
            data = AxisValues(actual=self.actual_value, raw=raw_value, curved=self.curve_value)
            return data

        # no curve, no calibration
        data = AxisValues(actual=self.actual_value)
        return data

    def __str__(self):
        return f"AxisData: device: {self.device.name} input_id: {self.input_id} linear_id: {self.linear_id} actual: {self.actual_value} raw: {self.raw_value} calibrated: {self.calibrated_value} curve: {self.curve_value}"


class DInputData:
    """holds dinput signaling data"""

    def __init__(self):
        self.last_time = None
        self.value = None
        self.debounce = True


@gremlin.singleton_decorator.SingletonDecorator
class DInputState:
    """tracks button states for DINPUT"""

    def __init__(self):
        self._data = {}  # keypair of device_id/input_type/id
        el = EventListener()
        el.profile_unload.connect(self.reset)
        el.profile_start.connect(self.reset)
        el.profile_stop.connect(self.reset)

    def shouldProcess(self, event: dinput.InputEvent):
        key = self.getKey(event)
        # import gremlin.joystick_handling
        # device_name = gremlin.joystick_handling.getDeviceName(event.device_guid)

        if self._data:
            if key in self._data:
                # compare values
                cevent: dinput.InputEvent = self._data[key]
                # syslog.info(f"dinput cache: {device_name}  input: {event.input_index} last value: {cevent.value} new: {event.value}  skip: {cevent.value == event.value}")
                self._data[key] = event
                return cevent.value != event.value
        else:
            # syslog.info(f"dinput cache: {device_name}  new input: {event.input_index} value: {event.value}")
            self._data[key] = event
        return True

    def getKey(self, event: dinput.InputEvent):
        return (event.device_guid, event.input_type, event.input_index)

    def reset(self):
        self._data.clear()


@gremlin.singleton_decorator.SingletonDecorator
class AxisState:
    """traxks axis state for DINPUT"""

    def __init__(self):
        self._data = {}  # keypair of device_id [str]/linear axis id (int)

        # map of axis input items that could be curved
        self._joystick_input_item_map = {}
        self._last_axis_values = {}  # last value
        self._last_axis_time = {}  # time when last modified

        self._registered_devices = []  # guid of registered devices
        self.usage_data = gremlin.joystick_handling.VirtualDeviceUsageState()
        self.perf = gremlin.config.Configuration().verbose_mode_perf
        self._delay = 1 / 1000  # delay in seconds for filter - 0 = disabled
        self._delta = 0.001  # delta to trigger a difference
        self._skip_count = {}  # event skip count
        self._receive_count = {}  # event receive count

        el = EventListener()
        el.profile_unload.connect(self.reset)
        el.profile_loaded.connect(self._update_inputs)
        el.config_option_changed.connect(self._handle_config_changed)

        self._handle_config_changed()  # read config

    def _handle_config_changed(self):
        config = gremlin.config.Configuration()
        self.perf = config.verbose_mode_perf
        self._delay = config.axis_spam_delay
        self._delta = config.axis_spam_delta

    def reset(self):
        """resets the state data"""
        verbose = gremlin.config.Configuration().verbose_mode_joystick
        if verbose:
            syslog.info("AXIS STATE: reset...")
        self._data.clear()
        self._registered_devices.clear()
        self._joystick_input_item_map.clear()
        profile = gremlin.shared_state.current_profile
        if profile:
            self._update_inputs()
        if verbose:
            syslog.info("\taxis data reset complete")

    def _update_inputs(self):
        """reload all axes on profile load"""

        import gremlin.joystick_handling

        for device in gremlin.joystick_handling.getDevices():
            if device.connected:
                self.registerDevice(device)

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_inputs or config.verbose_mode_joystick
        if verbose:
            syslog.info("Axis input list:")
            for device_guid, input_id in self._data:
                name = gremlin.joystick_handling.device_name_from_guid(device_guid)
                syslog.info(f"\t{name} axis [{input_id}]")

    def registerDevice(self, device: dinput.DeviceSummary):
        """registers axes for a given device"""
        if device.axis_count:
            device_id = device.device_id
            if device_id not in self._registered_devices:
                self._registered_devices.append(device_id)

            for axis_id in device.axis_id_map:
                key = self._get_key(device_id, axis_id)
                if key not in self._data:
                    self._data[key] = AxisData(device_id, axis_id)

    def registerDeviceGuid(self, device_guid):
        import gremlin.joystick_handling

        device = gremlin.joystick_handling.getDevice(device_guid)
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_inputs or config.verbose_mode_joystick
        if verbose:
            syslog.info(f"AXIS STATE: register device: {device.name}")
        if device:
            self.registerDevice(device)
        else:
            syslog.warning(f"AXIS STATE: registerDeviceGUID: failed to find device for ID: [{device_guid}]")

    def isRegistered(self, device_guid) -> bool:
        """true if the device is registered"""
        device_id = gremlin.util.normalize_guid(device_guid)
        return device_id in self._registered_devices

    def registerAxisInputItem(self, input_item):
        """registers an axis input item"""
        import gremlin.input_item
        assert isinstance(input_item, gremlin.input_item.InputItem), "input_item must be an instance of AxisInputItem"
        if input_item.get_input_type() == InputType.JoystickAxis:
            verbose = gremlin.config.Configuration().verbose_mode_joystick
            device_id: str = gremlin.util.normalize_guid(input_item.device_guid)
            input_id: int = input_item.input_id
            key = self._get_key(device_id, input_id)
            self._joystick_input_item_map[key] = input_item
            self._data[key] = AxisData(device_id, input_id)
            verbose = gremlin.config.Configuration().verbose_mode_events

            if verbose:
                device = gremlin.joystick_handling.getDevice(device_id)
                syslog.info(f"Register axis: {device.name} {device_id} axis: {input_id}  {device.getAxisName(input_id)}")

    def queueAxisEvent(self, device_guid, axis_id):
        """queues a joystick update event to trigger UI updates for example"""
        assert device_guid is not None, "invalid device id"
        values = self.getAxisValues(device_guid, axis_id)
        if values:
            if not isinstance(device_guid, dinput.GUID):
                device_guid = gremlin.util.parse_guid(device_guid)
            event = Event(
                InputType.JoystickAxis,
                axis_id,
                device_guid,
                is_axis=True,
                value=values.actual,
                extra_data={"queuedEvent": True},
            )
            el = EventListener()
            el.custom_joystick_event.emit(event)

    def _get_key(self, device_guid, axis_id):
        assert device_guid is not None, "invalid device id"
        if not isinstance(device_guid, str):
            device_guid = gremlin.util.normalize_guid(device_guid)  # ensure key is a string
        return (device_guid, axis_id)

    def getAxis(self, device_guid, axis_id):
        """gets the axis data block"""
        if device_guid:
            return self.register(device_guid, axis_id)
        return None

    def getItem(self, device_guid, axis_id):
        """gets registered axis input item"""
        if not self._joystick_input_item_map:
            # data was reset, ask for a reload
            el = EventListener()
            el.reload_axis_state.emit()

        if device_guid:
            key = self._get_key(device_guid, axis_id)
            if key in self._joystick_input_item_map:
                item = self._joystick_input_item_map[key]
                return item
        return None

    def getAxisData(self, device_guid, axis_id) -> AxisData:
        """gets the cached axis data"""
        if device_guid:
            key = self._get_key(device_guid, axis_id)
            if key in self._data:
                return self._data[key]
        return None

    def setAxisData(self, device_guid: str | dinput.GUID, input_id: int, value: float) -> AxisData:
        """sets the axis data"""
        assert device_guid is not None, "invalid ID "
        import gremlin.joystick_handling

        device = gremlin.joystick_handling.getDevice(device_guid)
        assert device is not None, f"device not found for ID: {device_guid}"
        assert input_id in device.axis_id_map, f"invalid axis input id [{input_id}] for device {device.name}"

        key = self._get_key(device_guid, input_id)
        if key not in self._data:
            data = AxisData(device_guid, input_id)
            data.raw_value = value
            self._data[key] = data
        return self._data[key]

    def getAxisValues(self, device_guid, input_id: int, value: float = None) -> list:
        """gets an axis input values, including actual, raw, calibrated and curved as a list of floating point values
        a value of None indicates the item is not used.
        the fiest value is the computed value based on applied calibration
        if the value is not provided, the axis is queried for the current value

        :param device_guid: id of the device
        :param input_id: axis index, linear or axis id based on the flag
        :param value: default value if needed

        """
        import gremlin.types
        import gremlin.ui.osc_device
        import gremlin.joystick_handling

        assert device_guid is not None, "invalid device id"
        dev: dinput.DeviceSummary = gremlin.joystick_handling.getDevice(device_guid)
        if not dev:
            syslog.warning(f"device not found: [{str(device_guid)}]")
            return AxisValues(0, 0)

        if dev.axis_count:
            assert input_id in dev.axis_id_map, "invalid input id"

        # special handling of OSC input devices
        if dev.device_type == DeviceType.Osc:
            osc = gremlin.ui.osc_device.InputOscClient()
            osc.start()  # ensure started
            data = osc.getData(input_id.message)  # gets data arguments or None if no data
            if data is None:
                value = 0
            else:
                value = data
            values = AxisValues(value, value)
            return values
        elif dev.device_type == DeviceType.Midi:
            # special handling of MIDI input devices
            midi = gremlin.ui.midi_device.InputMidiClient()
            midi.start()  # ensure started
            data = midi.getData(input_id.message)  # gets data arguments or None if no data
            if data is None:
                value = 0
            else:
                value = data
            values = AxisValues(value, value)
            return values

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)

        data = self.getAxisData(device_guid, input_id)
        if data is None:
            # no data in the state yet, read it
            value = gremlin.joystick_handling.get_axis(device_guid, input_id)  # axis id is already linear
            data = self.setAxisData(device_guid, input_id, value)

        if data is not None:
            values = data.getAxisValues(value)
            if not values:
                syslog.error(f"AXIS STATE: no axis data found for device {dev.name} ID: {input_id}")
                return None
            return values
        else:
            if verbose:
                if hasattr(input_id, "display_name"):
                    input_stub = input_id.display_name
                else:
                    input_stub = f"{input_id}"
                syslog.error(f"AXIS STATE: no axis data found for device {dev.name} ID: {input_stub}")
                known_axes = [i for (d, i) in self._data if d == dev.device_id]
                syslog.info(f"\tknown list: {known_axes}")
        return None

    def getRawAxisValue(self, device_guid, input_id):
        """gets the raw axis input"""
        import gremlin.joystick_handling

        return gremlin.joystick_handling.get_axis(device_guid, input_id)

    def getAxisCurve(self, device_guid, input_id):
        """returns the curve data if the axis has a curve applied"""
        if device_guid:
            item = self.getItem(device_guid, input_id)
            if item:
                return item.curve_data
        return None

    def getAxisCalibration(self, device_guid, input_id):
        """gets the axis calibration data"""
        if device_guid:
            item = self.getItem(device_guid, input_id)
            if item:
                return item.calibration
        return None

    def applyCalibration(self, device_guid, input_id: int, value: float, return_null: bool = True):
        """applies an axis calibration to an input value"""
        if device_guid:
            item = self.getItem(device_guid, input_id)
            if item and item.calibration:
                calibrated_value = item.calibration.getValue(value)
                return calibrated_value
            if return_null:
                return None
        return value

    def applyCurve(self, device_guid, input_id, value: float, return_null: bool = True):
        if device_guid:
            item = self.getItem(device_guid, input_id)
            if item and item.curve_data:
                curved_value = item.curve_data.curve_value(value)
                return curved_value

            # no curve to apply
            if return_null:
                return None
            return value
        return None

    def shouldProcess(
        self,
        event: dinput.InputEvent | Event | VjoyEvent,
        process_key: str = None,
        delay: float = None,
        delta: float = None,
    ):
        """anti-spam filter for axis events to throttle event input for noisy inputs in particular.

        :param event: the axis event (dinput or GEX event)
        :param process_key: optional, additional key for data tracking to uniquely identify this filter
        :param delay: delay in seconds, if not provided uses the default delay
        :param delta: value delta, 0 or positive, event values values below this threshold are ignored

        """
        import gremlin.joystick_handling

        if isinstance(event, dinput.InputEvent):
            if event.input_type != dinput.InputType.Axis:
                # not an axis
                return True
            key = (event.device_guid, event.input_type, event.input_index)
            # convert to -1 to +1
            current_value = gremlin.util.scale_to_range(event.value, source_min=-32767, source_max=32767)
            input_id = event.input_index
        elif isinstance(event, Event):
            if not event.is_axis:
                # not an axis
                return True
            key = event.callbackKey
            current_value = event.value
            input_id = event.identifier
        elif isinstance(event, VjoyEvent):
            device_guid = gremlin.joystick_handling.getVjoyDeviceGuid(event.vjoy_id)
            key = (device_guid, event.input_type, event.input_id)
            current_value = event.value

        if process_key:
            key = (key, process_key)  # hook to that key only

        if self.perf:
            if key not in self._receive_count:
                self._receive_count[key] = 0
            self._receive_count[key] += 1
            reason = ""

        now = time.time()
        delay = delay or self._delay
        result = True
        if key in self._last_axis_values:
            last_value = self._last_axis_values[key]
            last_modified = self._last_axis_time[key]

            delta = delta or self._delta
            if delta and math.isclose(last_value, current_value, abs_tol=delta):
                # fail: value within the delta change
                self._last_axis_time[key] = now
                if self.perf:
                    reason = "too close"
                result = False

            if not result and delay and (last_modified + delay) >= now:
                # fail: value too soon
                if self.perf:
                    if key not in self._skip_count:
                        self._skip_count[key] = 0
                    self._skip_count[key] += 1
                    device = gremlin.joystick_handling.getDevice(event.device_guid)
                    reason = "too frequent"

                result = False

        if not result:
            if self.perf:
                if key not in self._skip_count:
                    self._skip_count[key] = 0
                self._skip_count[key] += 1
                config = gremlin.config.Configuration()
                verbose = config.verbose_mode_perf and config.verbose_mode_extra
                if verbose:
                    device = gremlin.joystick_handling.getDevice(event.device_guid)
                    device_stub = device.name if device else f"Unknown device: {str(event.device_guid)}"
                    percent = 100 * self._skip_count[key] / self._receive_count[key]
                    stub = f"skip total: {self._skip_count[key]:,} evt received: {self._receive_count[key]:,} {percent:0.2f}% "
                    syslog.info(f"PERF: AXIS FILTER: {device_stub} input [{input_id}] {reason} value: {current_value:0.5f} {stub}")
            return False

        self._last_axis_values[key] = current_value
        self._last_axis_time[key] = now
        return True

class JoystickCallback:
    __slots__ = [
        "hook_id",
        "callback",
        "id",
        "device_guid",
        "input_type",
        "input_id",
        "ui_only",
        "persist",
        "description",
        "ui_thread",
    ]

    def __init__(
        self,
        hook_id,
        callback,
        device_guid=None,
        input_type=None,
        input_id=None,
        ui_only=False,
        persist=False,  # persist on reset
        description=None,
        ui_thread=False,  # true if the callback should run on the UI thread
    ):
        self.id = gremlin.util.get_guid()  # id of this callback block
        self.hook_id = hook_id
        self.device_guid = gremlin.util.parse_guid(device_guid)  # store as dinput.GUID as events use GUIDs
        self.input_type = input_type
        self.input_id = input_id
        self.callback = callback
        self.ui_only = ui_only
        self.persist = persist
        self.description = description
        self.ui_thread = ui_thread

    def __str__(self):
        import gremlin.joystick_handling

        if self.device_guid:
            device = gremlin.joystick_handling.getDevice(self.device_gudd)
            device_stub = device.name if device else f" unknown {str(self.device_guid)}"
        else:
            device_stub = "n/a"
        return f"callback: id[{self.hook_id}] device: [{device_stub}] input type: [{self.input_type.name}] input id: {self.input_id} {self.description or ''}"


@gremlin.singleton_decorator.SingletonDecorator
class JoystickEventProcessor:
    """sets up a threaded queue for handling and distributing joystick events, optionally filtering them
    the callbacks are called on the UI thread
    """

    def __init__(self):
        self._callbacks = {
            False: {},
            True: {},
        }  # map of callbacks [ui_thread_flag][device_guid][input_type][input_id][callback] = callback data
        self._cb_list = {}  # list of all CBs in the registry keyed by hook_id
        self._generic_callbacks = {
            False: {},
            True: {},
        }  # holds callbacks without filters,
        self._event_queue = FastQueue[Event](name="event dispatcher queue")  # holds the queue of events waiting to be processed
        self._ui_event_queue = FastQueue[Event](name="ui event dispatcher queue")

        self._listener_callbacks = {}  # map of repeater callbacks [device_guid:dinput.GUID][input_type][input_id] -> callback(event)
        self._callback_map = {}  # map of callback to the registered device
        self._event_cache = {}  # cache of prior values

        self._count = 0  # number of items in the fire queue
        self._callback_count = 0  # number of registered callbacks
        self._event_thread = None
        self._started = False
        self._is_running = gremlin.shared_state.is_running
        el = EventListener()
        el.shutdown.connect(self.handle_shutdown)
        el.profile_unload.connect(self.profile_unload)
        el.profile_loading.connect(self.profile_loading)
        el.config_option_changed.connect(self.handle_config_changed)
        self._axis_state = AxisState()  # axis tracker
        self._dinput_state = DInputState()  # dinput state tracker
        self._lock = threading.RLock()
        self.handle_config_changed()  # setup verbose flags

        # hook joystick events for the UI
        el.joystick_event_ui.connect(self.process_event_ui)  # ui thread joystick input event
        el.vjoy_output_event_ui.connect(self.process_vjoy_ui)  # ui thread vjoy output event

        # self.start()

    def getInputIdKey(self, input_id):
        """gets an input id key from a given input id"""
        import gremlin.input_item

        return gremlin.input_item.getInputIdKey(input_id)

    def registerListenerUICallback(
        self, device_guid: str | dinput.GUID, input_type: InputType, input_id: int, callback: Callable = None, mode=CallbackMode.Edit, source = EventSourceType.Any
    ):
        """register a joystick listener

        :param device_guid: the id of the device
        :param input_type: the input type
        :param input_id: the input id, -1 for any of that type
        :param callback: the handler to call  callback(event)
        :param edit_mode_only: true if the callback is only called when in edit mode
        :param source: the source of the event to listen for (dinput, vjoy, midi, osc)

        """

        import gremlin.input_item

        assert gremlin.input_item is not None, "gremlin.input_item module not available"
        assert isinstance(device_guid, (str, dinput.GUID)), "invalid device_guid"

        assert isinstance(input_type, InputType), "invalid input_type"

        if not device_guid:
            # nothing to do
            return

        assert isinstance(callback, Callable), "invalid callback"

        input_id_key = gremlin.input_item.getInputIdKey(input_id)

        assert input_id_key is not None, "invalid input id"

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(3)

        key = (source, mode, device_guid, input_type, input_id_key)

        mode_list = [CallbackMode.Edit, CallbackMode.Run] if mode == CallbackMode.All else [mode]

        if callback in self._callback_map:
            if key in self._callback_map[callback]:
                syslog.info("callback already registered for input, skipping")
                return
        else:
            self._callback_map[callback] = []
        self._callback_map[callback].append(key)
        if source not in self._listener_callbacks:
            self._listener_callbacks[source] = {}
        for mode in mode_list:
            if mode not in self._listener_callbacks[source]:
                self._listener_callbacks[source][mode] = {}
            if device_guid not in self._listener_callbacks[source][mode]:
                self._listener_callbacks[source][mode][device_guid] = {}
            if input_type not in self._listener_callbacks[source][mode][device_guid]:
                self._listener_callbacks[source][mode][device_guid][input_type] = {}
            if input_id_key not in self._listener_callbacks[source][mode][device_guid][input_type]:
                self._listener_callbacks[source][mode][device_guid][input_type][input_id_key] = []
            if callback not in self._listener_callbacks[source][mode][device_guid][input_type][input_id_key]:
                self._listener_callbacks[source][mode][device_guid][input_type][input_id_key].append(callback)

        if verbose:
            device_name = gremlin.joystick_handling.getDeviceName(device_guid) if device_guid else "N/A"
            if hasattr(input_id,"message_key"):
                key = input_id.message_key
            else:
                key = input_id
            syslog.info(
                f"JEP: add listener: device: [{device_name}] input type: [{input_type}] mode: [{mode}] input_id: [{input_id}] key: [{key}] source: [{source.name}]"
            )


    def unregisterListenerUICallback(
        self,
        device_guid: str | dinput.GUID = None,
        input_type: InputType = None,
        input_id: int = None,
        callback: Callable = None,
        source: EventSourceType = EventSourceType.Any,
    ):
        """removes a registered callback - if input data is provided only looks for that one - if not provided, removes all inputs associated with the callback
        :param device_guid: the id of the device
        :param input_type: the input type
        :param input_id: the input id, -1 for any of that type
        :param callback: the handler to call  callback(event)
        :param source: the source of the event to listen for (dinput, vjoy, midi, osc)

        """
        assert isinstance(callback, Callable), "invalid callback"
        if __debug__:
            if input_type is not None:
                assert isinstance(input_type, InputType), "invalid input type"
                # assert is
                # match input_type:
                #     case InputType.Midi:
                #         assert isinstance(input_id, gremlin.ui.midi_device.MidiInputItem), "invalid midi input item"
                #     case InputType.OpenSoundControl:
                #         assert isinstance(input_id, gremlin.ui.osc_device.OscInputItem), "invalid osc input item"
                #     case _:
                #         assert isinstance(input_id, int), "invalid input id"

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(3)


        input_id_key = gremlin.input_item.getInputIdKey(input_id)

        if device_guid is not None:
            if not isinstance(device_guid, dinput.GUID):
                device_guid = gremlin.util.to_guid(device_guid)
            assert isinstance(device_guid, dinput.GUID), "invalid device guid"

        if callback in self._callback_map and self._callback_map[callback]:
            for l_source in self._listener_callbacks:
                if l_source != source and l_source != EventSourceType.Any:
                    continue
                for l_mode in self._listener_callbacks[source]:
                    for l_device_guid in self._listener_callbacks[source][l_mode]:
                        for l_input_type in self._listener_callbacks[source][l_mode][l_device_guid]:
                            for l_input_id in self._listener_callbacks[source][l_mode][l_device_guid][l_input_type]:
                                if callback in self._listener_callbacks[source][l_mode][l_device_guid][l_input_type][l_input_id]:
                                    if device_guid is not None and input_type is not None and input_id_key is not None:
                                        if not (l_device_guid == device_guid and l_input_type == input_type and l_input_id == input_id_key):
                                            continue

                                    self._listener_callbacks[source][l_mode][l_device_guid][l_input_type][l_input_id].remove(callback)
                                    key = (l_device_guid, l_input_type, l_input_id)
                                    if key in self._callback_map[callback]:
                                        self._callback_map[callback].remove(key)

                                    if verbose:
                                        syslog.info(f"JEP: remove listener: source: [{source.name}] callback: [{callback.__module__}.{callback.__self__.__class__.__name__}.{callback.__name__}]")
                                        obj = callback.__self__
                                        if hasattr(obj, "_description"):
                                            syslog.info(f"\t{obj._description}")

            if not self._callback_map[callback]:
                del self._callback_map[callback]

    def _fireCallbacks(self, event: Event):
        """first all the callbacks on the UI thread"""
        gremlin.util.InvokeUiMethod(self._fireCallbacks_ui, event)

    def _fireCallbacks_ui(self, event: Event):
        """fires all the registered callbacks (ui thread)"""
        gremlin.util.assert_ui_thread()

        device_guid = event.device_guid
        input_type = event.getInputType()
        input_id = event.identifier
        input_id_key = gremlin.input_item.getInputIdKey(input_id)
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_events or config.verbose_mode_ui_level(3)
        mode = CallbackMode.Run if gremlin.shared_state.is_running else CallbackMode.Edit
        source = event.source


        if verbose:
            if hasattr(input_id,"message_key"):
                key = input_id.message_key
            else:
                key = input_id
            syslog.info(f"JEP: fire callbacks: event: {str(event)} input_type: [{input_type}] input_id: [{input_id}] key: [{key}] source: [{source}]")


        if source in self._listener_callbacks:
            if mode in self._listener_callbacks[source]:
                if device_guid in self._listener_callbacks[source][mode]:
                    if input_type in self._listener_callbacks[source][mode][device_guid]:
                        if -1 in self._listener_callbacks[source][mode][device_guid][input_type]:
                            for callback in self._listener_callbacks[source][mode][device_guid][input_type][-1]:
                                if verbose:
                                    syslog.info(f"\texec: [{callback.__module__}.{callback.__self__.__class__.__name__}.{callback.__name__}] event: {str(event)}")
                                callback(event)
                                time.sleep(0)

                        if input_id_key in self._listener_callbacks[source][mode][device_guid][input_type]:
                            for callback in self._listener_callbacks[source][mode][device_guid][input_type][input_id_key]:
                                if verbose:
                                    syslog.info(f"\texec: [{callback.__module__}.{callback.__self__.__class__.__name__}.{callback.__name__}] event: {str(event)}")
                                callback(event)
                                time.sleep(0)

    @QtCore.Slot(Event)
    def process_event_ui(self, event: Event):
        """process received joystick event - UI thread"""
        self._fireCallbacks_ui(event)

    @QtCore.Slot(Event)
    def process_vjoy_ui(self, event: Event):
        """process received joystick event - UI thread"""
        # if event.is_axis:
        #     input_id = event.identifier
        #     syslog.info(f"got vjoy axis event for input_id: {input_id} with value: {event.value:0.3f}")
        self._fireCallbacks_ui(event)

    def handle_config_changed(self):
        pass
        # config = gremlin.config.Configuration()
        # self.verbose = config.verbose_mode_perf and config.verbose_mode_events  # or config.verbose_mode_hooks

    def profile_unload(self):
        self.reset()

    def reset(self):
        with self._lock:
            self._callbacks[True].clear()  # these items run on the UI thread
            self._callbacks[False].clear()  # these items do not run on the UI thread
            self._cb_list.clear()
            self._generic_callbacks[True].clear()
            self._generic_callbacks[False].clear()
            self._listener_callbacks.clear()

    def handle_shutdown(self):
        self.reset()

    def profile_loading(self):
        # prevent processing while loading a profile
        self.reset()

    def getCallbackKey(self, device_guid, input_type, input_id):
        """gets a callback key for the joystick"""
        return (gremlin.util.normalize_guid(device_guid), input_type, input_id)

    def registerCallback(
        self,
        hook_id,
        callback,
        device_guid=None,
        input_type=None,
        input_id=None,
        ui_only=True,
        persist=False,
        description=None,
        ui_thread=False,
    ):
        """registers a callback, with optional filter
        :param hook_id: unique key for this registration
        :param callback: the callback the processor will call when joystick data changes - this can be (event) or (values)  if a value trigger [value triggers sends all axis information based on configuraiton options]
        :param device_guid: guid of the device in GUID form
        :param input_type: the input type [joystick, hat or button]
        :param input_id: the input id of the axis, button or hat
        :param ui_only: true if the trigger only happens at edit time
        :param persist: if set, the callback is persisted on reset
        :param description: optional description for the callback for diagnostics purposes

        """

        if self.verbose:
            syslog.info(f"JEP: register hook: [{hook_id}]")

        with self._lock:
            if device_guid is None:
                # not using a filter
                if hook_id not in self._generic_callbacks:
                    self._generic_callbacks[ui_thread][hook_id] = callback

            else:
                assert input_type is not None, "Input type must be provided if device GUID is given"
                assert input_id is not None, "Input id must be provided if device GUID is given"

            device_guid = gremlin.util.parse_guid(device_guid)  # ensure a GUID becaus event device guids are GUIDs
            # device_id = gremlin.util.normalize_guid(device_guid)

            callbacks = self._callbacks[ui_thread]  # select UI or nonUI thread callbacks

            key = self.getCallbackKey(device_guid, input_type, input_id)  # storage key

            if key not in callbacks:
                callbacks[key] = {}  # keyed by hook_id

            if hook_id not in callbacks[key]:
                cb = JoystickCallback(
                    hook_id,
                    callback,
                    device_guid,
                    input_type,
                    input_id,
                    ui_only,
                    description=description,
                    ui_thread=ui_thread,
                )
                callbacks[key][hook_id] = cb
                self._cb_list[hook_id] = cb
                self._callback_count += 1

            if self.verbose:
                device = gremlin.joystick_handling.getDevice(device_guid)
                syslog.info(
                    f"DISPATCH: register callback: [{self._callback_count}] id [{hook_id}] [{device.name if device else 'unknown:' + str(device_guid)}] [{input_type.name}] id: [{input_id}] "
                )

    def getCallbackList(self):
        # gets the list of callbacks by (non_ui_thread, ui_thread)
        return (self._callbacks[False], self._callbacks[True])

    def unregisterCallback(self, hook_id):
        """removes a callback"""

        if self.verbose:
            syslog.info(f"JEP: unregister hook: [{hook_id}]")

        with self._lock:
            if hook_id in self._generic_callbacks[False]:
                self._generic_callbacks[False].remove(hook_id)
            elif hook_id in self._generic_callbacks[True]:
                self._generic_callbacks[True].remove(hook_id)

            if hook_id in self._cb_list:
                cb = self._cb_list[hook_id]
                key = self.getCallbackKey(cb.device_guid, cb.input_type, cb.input_id)  # storage key
                for callbacks in self.getCallbackList():
                    if key in callbacks:
                        if cb.hook_id in callbacks[key]:
                            self._callback_count -= 1
                            if self.verbose:
                                device = gremlin.joystick_handling.getDevice(cb.device_guid)
                                syslog.info(
                                    f"DISPATCH: unregister callback: [{self._callback_count}] hook id: [{cb.hook_id}] [{device.name if device else 'unknown:' + str(cb.device_guid)}] [{cb.input_type.name}] id: [{cb.input_id}]"
                                )
                            del callbacks[key][hook_id]
                del self._cb_list[hook_id]  # remove from the list of callbacks

    def _fire_callback_ex(self, cb_data):
        """fires events on the event thread"""
        for cb, event, values in cb_data:
            cb.callback(event, values)

    def _fire_callback(self, cb: JoystickCallback, event, values):

        if self.verbose:
            start_time = time.time()
            gremlin.util.InvokeUiMethod(cb.callback, event, values)
            lapsed = time.time() - start_time
            stub = f" callback: [{cb.description}]" if cb.description else "n/a"
            syslog.info(f"DISPATCH: {stub} event {str(event)} queue depth: {self._count:,} runtime (ms): {lapsed * 1000:0.3f}")
            self._count -= 1
        else:
            gremlin.util.InvokeUiMethod(cb.callback, event, values)


@gremlin.singleton_decorator.SingletonDecorator
class EventRegistry:
    """tracks events"""

    def __init__(self):
        self._registry = {}  # holds [event_type][device_guid][input_id] = event
        el = EventListener()
        el.profile_start.connect(self._reset)
        el.profile_stop.connect(self._reset)
        self._lock = threading.Lock()

    def _reset(self):
        with self._lock:
            self._registry.clear()

    def getInputIdKey(self, input_id):
        return gremlin.input_item.getInputIdKey(input_id)

    def update(self, event: Event):
        input_type = event.event_type
        device_guid = event.device_guid
        input_id = event.identifier

        with self._lock:
            if input_type not in self._registry:
                self._registry[input_type] = {}
            if device_guid not in self._registry[input_type]:
                self._registry[input_type][device_guid] = {}
            input_item_key = self.getInputIdKey(input_id)

            self._registry[input_type][device_guid][input_item_key] = event.timestamp

    def lastEvent(self, event: Event) -> Event | None:
        """gets the last event"""
        input_type = event.event_type
        device_guid = event.device_guid
        input_id = event.identifier
        return self.getLastEvent(device_guid, input_type, input_id)

    def getLastEvent(self, device_guid, input_type, input_id) -> Event | None:
        with self._lock:
            if input_type not in self._registry:
                return None
            if device_guid not in self._registry[input_type]:
                return None
            input_item_key = self.getInputIdKey(input_id)
            if input_item_key not in self._registry[input_type][device_guid]:
                return None
            return self._registry[input_type][device_guid][input_item_key]
