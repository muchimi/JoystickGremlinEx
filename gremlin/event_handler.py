# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2025 
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

from __future__ import annotations
import functools
import traceback
import inspect
import logging
import time
import queue
import threading
import anytree
from typing import NamedTuple, Optional
from threading import Thread, Timer
from typing import Callable
import math
import gremlin.base_classes
import gremlin.shared_state
import gremlin.threading

from PySide6 import QtCore, QtWidgets

import dinput
import gremlin.config
from gremlin.input_types import InputType
import gremlin.shared_state

import gremlin.util


import gremlin.keyboard
import gremlin.ui
import gremlin.singleton_decorator
import json

import psygnal
from psygnal import Signal


from gremlin.types import TabDeviceType



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

	def __init__(
			self,
			event_type,
			identifier,
			device_guid,
			value=None, # normal calibrated value that comes in
			virtual_code = 0,
			is_pressed=False,
			raw_value=None, # raw value that comes in from dinput
			curved_value = None, # value if curved
			force_remote = False,
			action_id = None,
			data = None,
			is_axis = False, # true if the input should be considered an axis (variable) input
			is_virtual = False, # true if the input is a virtual input (vjoy),
			mode = None, # mode to fire the event on - leave null for current mode,
			override_input_type = None,
			extra_data : dict = None, # extra data to pass on (dict)
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
		self._id = gremlin.util.get_guid() # unique ID for this event
		#self._event_type = event_type
		self.event_type = event_type
		self._identifier = identifier
		self.device_guid = device_guid
		self._is_pressed = is_pressed
		#self.is_pressed = is_pressed
		#self._value = value
		self.value = value
		self.raw_value = raw_value
		self._curve_value = curved_value
		self.force_remote = force_remote
		self.action_id = action_id # the current action id to load
		self.data = data # extra data passed along with the event
		self.is_axis = is_axis
		self.virtual_code = virtual_code # vk if a keyboard event (the identifier will be the key_id (scancode, extended))
		self.is_virtual = is_virtual # true if the item is a vjoy device input
		self.is_virtual_button = False # true if a virtual button
		self.is_custom = False # true if a custom event (should be processed)
		self.mode = mode # mode to act on, should be null for default
		self.is_repeater = False # True if the event is a repeater generated event
		self.override_input_type = override_input_type # override input type - used as the input type for actions 
		self.extra_data = extra_data

	@property
	def is_pressed(self):
		return self._is_pressed
	
	@is_pressed.setter
	def is_pressed(self, value):
		if not value and self.event_type == InputType.JoystickHat:
			pass
		self._is_pressed = value

	@property
	def curve_value(self) -> float:
		''' curve value is the modified event value passed to actions as filtered or curved'''
		return self._curve_value
	@curve_value.setter
	def curve_value(self, value : float):
		self._curve_value = value


	def clone(self):
		"""Returns a clone of the event.

		:return cloned copy of this event
		"""
		import copy
		if not isinstance(self.identifier, int):
			self.identifier = gremlin.base_classes.PickleTarget(self.identifier)
		dup = copy.deepcopy(self)
		dup._id = gremlin.util.get_guid() # unique ID for this event
		return dup
	
	def __deepcopy__(self, memo):
		import copy
		cls = self.__class__
		result = cls.__new__(cls)
		memo[id(self)] = result
		for k, v in self.__dict__.items():
			try:
				setattr(result, k, copy.deepcopy(v, memo))
			except:
				# cannot copy = do a shallow copy
				setattr(result, k, v)
		return result
	
	@property
	def device_id(self) -> str:
		''' id as a string '''
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



	def fake_button(self, is_pressed = True, clone = False):
		''' converts the event to a fake button '''
		e = self.clone() if clone else self
		if e.event_type in (InputType.JoystickAxis, InputType.JoystickHat):
			# convert axis/hat events to fake button events
			e.event_type = InputType.JoystickButton 
		e.identifier = 1
		e.is_axis = False # range exit is a button type event
		e.is_pressed = is_pressed
		return e
		
	def invert(self):
		''' flips pressed flag '''
		e = self.clone()
		e.is_pressed = not self.is_pressed
		return e

	def __eq__(self, other):
		return self.__hash__() == other.__hash__()

	def __ne__(self, other):
		return not (self == other)
	
	@property
	def callbackKey(self):
		''' unique key to use to identify the specific callback '''
		device_guid = self.device_guid
		if not isinstance(device_guid, str):
			device_guid = gremlin.util.normalize_guid(device_guid)
		if self.event_type == InputType.Keyboard:
			data = (self.identifier.scan_code, self.identifier.is_extended) if isinstance(self.identifier, gremlin.keyboard.Key) else self.identifier
			return (
				self.device_guid,
				self.event_type.value,
				data,
				1 if data[1] else 0
			)
		else:
			return (
				device_guid,
				self.event_type.value,
				self.identifier,
				0
			)

	def __hash__(self):
		"""Computes the hash value of this event.
		new in m58: use the unique ID of this event to uniquely identify it

		:return integer hash value of this event
		"""
		
	
		return hash(self._id)

	@property	
	def hardwareKey(self):
		''' unique key for the input'''
		return ((self.device_guid, self.event_type, self.identifier))
		

	@staticmethod
	def from_key(key):
		"""Creates an event object corresponding to the provided key.

		:param key the Key object from which to create the Event
		:return Event object corresponding to the provided key
		"""
		if hasattr(key,"scan_code") and hasattr(key,"is_extended"):
			return Event(
				event_type = InputType.Keyboard,
				identifier = (key.scan_code, key.is_extended),
				virtual_code = key.virtual_code,
				device_guid = dinput.GUID_Keyboard
			)
		
		raise ValueError(f"Unable to handle parameter - not a valid key: {key}")
	
	@staticmethod
	def from_vjoyEvent(ve : VjoyEvent):
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
				is_pressed = value != (0,0)

		return Event(
			event_type = ve.input_type,
			identifier = ve.input_id,
			device_guid = device_guid,
			is_pressed = is_pressed,
			is_axis = is_axis,
			value = value,
			curved_value= value,
			raw_value = value,
			extra_data={"loopback":True,
			   "vjoy" : ve.key} # store vjoy info for quick comparison
		)
	
	def __str__(self):
		if self.event_type == InputType.Mouse:
			return f"Event: {self._id} Mouse - button {self.identifier} pressed: {self.is_pressed}"
		elif self.event_type in  (InputType.Keyboard, InputType.KeyboardLatched):
			return f"Event: {self._id} Keyboard - scan code, extended : {self.identifier}  vk: {self.virtual_code} (0x{self.virtual_code:X}) pressed: {self.is_pressed}"
		elif self.event_type == InputType.JoystickAxis or self.is_axis:
			return f"Event: {self._id} Axis : {self.identifier} raw value: {self.raw_value} value: {self.value}"
		elif self.event_type == InputType.JoystickButton:
			return f"Event: {self._id} Button : {self.identifier} pressed: {self.is_pressed} value: {self.value}"
		elif self.event_type == InputType.ModeControl:
			return f"Event: {self._id} Mode Control : {self.identifier} pressed: {self.is_pressed} value: {self.value} mode: {self.mode}"
		elif self.event_type == InputType.JoystickHat:
			return f"Event: {self._id} Hat : {self.identifier} pressed: {self.is_pressed} value: {self.value}"
		elif self.event_type == InputType.Midi:
			return f"Event: {self._id} Midi : {self.identifier} value: {self.value}"
		elif self.event_type == InputType.OpenSoundControl:
			return f"Event: {self._id} OSC : {self.identifier} value: {self.value}"
		
		return f"Event: {self._id} {self.event_type} identifier {self.identifier}"

class DeviceChangeEvent:
	''' sent when a new device is selected '''
	def __init__(self):
		self.device_guid = None
		self.device_name = None
		self.device_input_id = 0
		self.device_input_type = 0
		self.input_type = 0
		self.vjoy_device_id = 0
		self.vjoy_input_id = 0
		self.source = None # object source responsible for the change, for example, the action
		

class StateChangeEvent:
	''' sent when the state changes '''
	def __init__(self, is_local = False, is_remote = False, is_broadcast_enabled = False):
		self.is_local = is_local
		self.is_remote = is_remote
		self.is_broadcast_enabled = is_broadcast_enabled

class VjoyEvent:
	def __init__(self, vjoy_id, input_type : InputType, input_id : int, value):
		self.vjoy_id = vjoy_id
		self.input_type = input_type
		self.input_id = input_id
		self.value = value

	@property
	def key(self) -> tuple:
		''' unique key for this event '''
		return (self.vjoy_id, self.input_type.value, self.input_id, self.value)


	def __str__(self):
		if self.input_type == InputType.JoystickAxis:
			value_stub = f"{self.value:0.3f}"
		else:
			value_stub = f"{self.value}"
		return f"VjoyEvent: vjoy [{self.vjoy_id}] type: [{self.input_type.name}] input: [{self.input_id}] value: [{value_stub}]"



@gremlin.singleton_decorator.SingletonDecorator
class EventListener:

	"""Listens for keyboard and joystick events and publishes them
	via QT's signal/slot interface.
	"""

	ui_ready = Signal() # tell the UI all is ready

	# Signal emitted when joystick events are received
	joystick_event = Signal(Event) # Signal(Event)
	
	# custom joystick event - this is a code based joystick event that mapping items can listen to when inside other containers
	custom_joystick_event = Signal(Event)


	hardware_input_event = Signal(object, object, object) # called for any input event (device_guid, input_type, input_id)

	vjoy_event = Signal(VjoyEvent) # Signal(VjoyEvent)


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
	state_name_change = Signal(str,str,object) # fires when a state changes names (old_name, new_name, StateInputItem)
	state_category_add = Signal(object) # fires when a state category is added (StateCategory)
	state_category_delete = Signal(object) # fires when a state category is removed (StateCategory)
	state_category_name_change = Signal(object) # fires when a state category name is changed (StateCategory)

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

	# Signal emitted when a profile is changed (to refresh UI)
	profile_changed = Signal()

	# profile loaded event
	profile_loaded =  Signal()

	# profile unloaded - trigger when a profile is being unloaded
	profile_unloaded = Signal()
	
	# signal emitted when the selected hardware device changes
	profile_device_changed = Signal(DeviceChangeEvent)

	# signal emitted when the selected hardware device changes
	profile_device_mapping_changed = Signal(DeviceChangeEvent)

	# signal emitted when the UI tabs are loaded and profiles are loaded - some widgets use this for post-UI initialization update that needs to occur after the UI data is completely loaded
	tabs_loaded = Signal()
	tab_filtered_changed = Signal(object, bool) # fires when tab filtering changes

	refresh_devices = Signal() # used to refresh the device list going into GremlinEx

	profile_reset = Signal() # profile reset signal (when runtime for a profile needs to reset)
	profile_hook = Signal() # hook functors - before profile start is emitted
	profile_unhook = Signal() # unhook functors - when profiles stop
	profile_start = Signal() # profile start signal (when a profile starts)
	profile_started = Signal() # profile started signal (after a profile starts and all process start functions are completed)
	profile_stop = Signal() # profile stop signal (when a profile stops)
	profile_stopping = Signal() # profile is about to stop (before a profile stops)
	profile_stopped = Signal() # profile stopped (after a profile stopped)

	profile_stop_toolbar = Signal() # profile stop signal (when a profile stops because the toolbar is pressed)
	profile_unload = Signal() # profile unload signal (when a profile is unloaded and a new profile loaded)
	request_profile_stop = Signal(str) # request the profile to stop (message to display: str)
	request_profile_reload = Signal(str, bool) # request a profile to load (str = profile file, bool = as new profile flag)
	request_reload = Signal() # request a reload of the current profile data
	
	process_monitor_changed = Signal() # process monitor options changed

	host_ip_changed = Signal(str) # indicates the local machines' host IP changed
	
	config_changed =  Signal() # occurs on broadcast configuration change
	config_option_changed = Signal() # occurs on broadcast configuration change

	options_changed = Signal() # occurs when the options dialog closes to have components check for any changes

	# occurs on broadcast mode change
	broadcast_changed = Signal(StateChangeEvent)

	# occurs on mode edit/update/delete of modes (edit time only)
	edit_mode_changed = Signal(str) # param: the mode that was changed to

	mode_name_changed = Signal(str, str) # runs when a mode name change occurs for the UI to update - param (old name, new name)
	mode_list_update = Signal() # runs when mode lists changes
	profile_modes_changed = Signal() # occurs when the hierarchy, or list of modes changed for a given profile (mode added, removed, changed or renamed)
	execution_context_changed = Signal() # occurs when execution context changes 

	runtime_mode_changed = Signal(str) # runs when the runtime profile mode changes (runtime mode only, when a profile has been started) - param - the mode changed to

	# functor enable flag changed
	action_created = Signal(object) # runs when an action is created - object = the object that triggered the event 

	# remove action
	action_delete = Signal(object, object, object) # fires when an action is about to be deleted, passes the (input_item, container, action) as a parameters

	virtual_button_changed = Signal(object, object, object) # runs when the action has modified its input mode (input_item, container, action) as parameters

	# called when vjoy button usage has changed in the profile so displays can update themselves
	button_usage_changed = Signal(int)  # (vjoy_id) fires when a vjoy device button has changed
	vjoy_button_usage = Signal(int, int, bool) # called when an action uses a vjoy button (vjoy_id, button_id, state)
	set_vjoy_button_usage = Signal(int, int, bool, str) # called when a button state should be set (vjoy_id, button_id, state, key)


	# selection event - tells the UI to show a different input
	select_input = Signal(object, object, object, bool, bool, bool) # selects a particular input (device_guid, input_type, input_id,  force_update, force_switch, tab_changed)
	select_input_completed = Signal(object, object, object) # indicates input selection is completed (device_guid, input_type, input_id)

	input_selected = Signal(object) # widget item was selected, parameter = InputItemWidget
	input_item_selected = Signal(object, int) # widget item was selected, parameter = InputItem, index of input item in the listview
	input_unselected = Signal(object) # widget item was unselected selected, parameter = InputItemWidget

	tab_selected = Signal(str) # tab selected, the device_guid (str) is passed as the parameter - this is triggered when a device tab is selected and made visible
	tab_unselected = Signal(str) # tab unselected, the device_guid (str) is passed as the parameter - this is triggered when a device tab is selected and made visible

	# mapping changed - either container or action added -
	mapping_changed = Signal(object) # fires when a container or action changes on an InputItem - passes the InputItem as the parameter
	
	# suspend keyboard input
	suspend_keyboard_input = Signal(bool) # arg = state, true = suspend, false = resume


	# called when a condition state changes - used to update the UI
	condition_redraw = Signal(object) # fires when a condition is redrawing
	condition_state_changed = Signal(object) # indicates the container state change  (container : AbstractContainer)
	condition_changed = Signal(object)  # indicates the container's conditions changed (container : AbstractContainer | AbstractAction)

	condition_added = Signal(object, str, object) # fires when a condition is added - params (input_item, mode, condition)
	condition_removed = Signal(object, str, object) # fires when a condition is removed - params (input_item, mode, condition)
	

	# container deleted 
	container_delete = Signal(object, object) # fires when a container is about to be deleted, passes the input item, container as parameters

	# update input curve icons
	update_input_icons = Signal() # fires when the UI needs to refresh input calibration and curve icons
	update_action_icons = Signal() # fires when the UI needs to update the action icons

	# occurs when input enabled state changes
	input_enabled_changed = Signal(object) # param - InputItem

	

	# occurs when a macro step completes
	macro_step_completed = Signal(int) # param - macro ID returned by the queue_macro function

	# request profile activate/deactivate
	request_activate = Signal(bool)  # param - flag - true to activate, false to deactivate

	# abort load
	abort = Signal() # tells loops/thread at active time to stop - called when a profile needs to stop due to a start error

	# request OSC start/stop
	request_osc = Signal(bool) # param - flag - true to start, false to stop
	osc_input_port_changed = Signal() # occurs when OSC input port is changed
	osc_output_port_changed = Signal() # occurs when OSC output port is changed
	osc_output_server_changed = Signal() # occurs when OSC server output IP is changed
	osc_loopback = Signal(object) # occurs when a loopback message is sent [osc_message]

	# request MIDI start/stop
	request_midi = Signal(bool) # param - flag - true to start, false to stop

	# # signals the need to register an OSC input item
	# register_osc_input = Signal(object) # param input_item being registered 
	

	# gremlin ex shutdown in progress
	shutdown = Signal() 

	# toggle highlighting mode state
	toggle_highlight = Signal(object, object, object) # param (axis,button)
	enable_highlight_changed = Signal(bool) # fires when highlight enable is turned on param(enabled)

	button_state_change = Signal(Event) # indicates a change in button state params: (device_guid, input_type, input_id, is_pressed)
	axis_state_change = Signal(Event) # indicates a change in axis state params: (device_guid, input_type, input_id, is_pressed)

	update_input_state = Signal(object) # request to update all axis and button input states in the UI for a given device: (device_guid) 
	
	# heartbeat
	heartbeat = Signal() # ticks every 30 seconds

	# autorepeat abort flag
	autorepeat_clear =  Signal() # fire this to abort any keyboard autorepeat actions

	# module status state notices
	module_state_change = Signal(str, object) # send a module state update, (key, state)
	module_state_register = Signal(str, str, object, object) # registers a module state (key, label, state, callback) - if callback is not None, sets up a button when clicked will execute the callback.  State = None, true/false, "on", "off", ""


	# notify when an input is selected (keep this a QT event for thread safety)
	input_selection_changed = Signal(object, object, object) # (device_guid, input_type, input_id)

	# request to paste a condition
	paste_condition = Signal(object, object) # (container, object_encoder)

	# request to copy a condition or activation condition
	copy_condition = Signal(object) # (condition or activation condition)

	show_container_id_changed = Signal() # fires when condition ID show on/off changed in configuration - this is to update affected widgets

	tts_change = Signal(bool) # fires when TTS enable/disabled changes

	device_mapping_changed = Signal(str) # fires when device mapping has changed (updates headers) - param = device_id as a string
	
	simconnect_show_options = Signal() # fires when the simconnect options dialog should be displayed 

	toolbar_changed = Signal() # fires when the toolbar configuration has changed 

	lock_inputs = Signal(object) # fires when all inputs should be locked, object = device_guid of the device to lock
	unlock_inputs = Signal(object) # fires when all inputs should be unlocked, object = device_guid of the device to unlock

	collapse_all_containers = Signal() # collapse all containers
	expand_all_containers = Signal() # expand all containers
	curve_added = Signal(object) # fires when a curve is added from an input item (InputItem)
	curve_deleted = Signal(object) # fires when a curve is deleted from an input item (InputItem)
	# occurs when calibration data changes
	calibration_added = Signal(object) # fires when a calibration is added from an input item (InputItem)
	calibration_deleted = Signal(object) # fires when a calibration is deleted from an input item (InputItem)
	calibration_changed = Signal(object) # param - CalibrationData object (InputItem)
	calibration_options_changed = Signal(object) # fires when calibration options are changed for the UI to update (InputItem)
	sync_input = Signal(object) # request to sync the input (InputItem)
	
	def __init__(self):
		"""Creates a new instance."""
		import gremlin.windows_event_hook

            
		self.keyboard_hook = gremlin.windows_event_hook.KeyboardHook()
		self.keyboard_hook.register(self._keyboard_handler)

		config = gremlin.config.Configuration()
		self._mouse_hook_stack = 0
		self.mouse_hook = None
		self.enable_mouse_hook = not config.is_debug  # disable mouse hooks while in debug mode
		self.enableMouse()

		# Calibration function for each axis of all devices
		self._calibrations = {}

		
		
		# Joystick device change update timeout timer
		self._device_update_timer = None
		
		self._running = True

		self._process_device_change_lock = False

		# keyboard input handling buffer
		self._keyboard_state = {}
		self._keyboard_queue = None
		self._key_listener_started = False # true if the key listener is started
		self.gremlin_active = False
		self._keyboard_thread = None
		self.keyboard_hook.start()

		self.device_change_event.connect(self._device_changed_cb)

		# internal event on process change
		self._process_device_change.connect(self._process_device_change_cb)

		# calibration data access
		self._calibrationManager = None
		self._verbose_dinput = False
		self._verbose_dinput_extra = False
		self._verbose_vjoy = False

		self._profile_started = False

		self.profile_start.connect(self._profile_start)
		self.profile_stopping.connect(self._profile_stopping_cb)
		self.profile_started.connect(self._profile_started_cb)
		self.options_changed.connect(self._options_changed)
		
		

		self._run_event = threading.Event()
		self._run_thread = Thread(target=self._run)
		self._run_thread.name ="EVENT run"
		self._run_thread.start()

		self._keep_alive_event = threading.Event()
		self._keep_alive_thread = threading.Thread(target = self._keep_alive, daemon=False)
		self._keep_alive_thread.name = "EVENT heartbeat"
		self._keep_alive_thread.start()

		self._vjoy_callbacks = []

		self._hat_state = {} # list of map positions (device_id, input_id), position_tuple, if blank - not set

		self.js = JoystickState()

		self.shutdown.connect(self._shutdown_handler)
		

		# TEST / POSSIBLE FUTURE WORK internal vjoy event handling for vjoy loopback cases
		self._vjoy_events = {} # map of processed events
		# self._vjoy_events_times = {} # map of processed events times
		self._vjoy_events_delay = 0.250 # quarter second delay for event loopback checking
		self._vjoy_events_use_time = False # config.vjoy_loopback_use_time
		self.vjoy_event.connect(self._handle_vjoy_event) # hook internal vjoy events generated whenever something is output to vjoy

	def registerVjoyCallback(self, callback):
		if not callback in self._vjoy_callbacks:
			self._vjoy_callbacks.append(callback)

	def unregisterVjoyCallback(self, callback):
		if callback in self._vjoy_callbacks:
			self._vjoy_callbacks.remove(callback)

	def vjoy_callback(self, event : VjoyEvent):
		for callback in self._vjoy_callbacks:
			callback(event)

	@QtCore.Slot()
	def _shutdown_handler(self):
		''' terminate threads '''
		import gremlin.windows_event_hook
		if self._keep_alive_thread:
			self._keep_alive_event.set()
			self._keep_alive_thread.join()
			self._keep_alive_thread = None

		if self._run_thread:
			self._run_event.set()
			self._run_thread.join()
			self._run_thread = None

		# shutdown keyboard hook if enabled
		kh = gremlin.windows_event_hook.KeyboardHook()
		kh.shutdown()

		# shutdown mouse hook if enabled
		mh = gremlin.windows_event_hook.MouseHook()
		mh.shutdown()

	@property
	def calibrationManager(self):
		from gremlin.ui.axis_calibration import CalibrationManager
		
		if not self._calibrationManager:
			self._calibrationManager = CalibrationManager()

		return self._calibrationManager
	
	def _fire_event_list(self, event_list):
		''' fires a series of events '''
		for event in event_list:
			self.joystick_event.emit(event)
	
	def _load_hat_states(self):
		''' loads current hats '''
		from gremlin.util import dill_hat_lookup
		import gremlin.joystick_handling
		self._hat_state = {}
		device_list = [dev for dev in gremlin.joystick_handling.joystick_devices() if dev.hat_count]
		event_list = []
		for device in device_list:
			for input_id in range(1, device.hat_count+1):
				key = (device.device_id, input_id)
				value = gremlin.joystick_handling.get_hat(device.device_guid, input_id)
				value = dill_hat_lookup[value]
				self._hat_state[key] = value
	
				event = Event(
					event_type= InputType.JoystickHat,
					device_guid= device.device_guid,
					identifier = input_id,
					is_pressed = True,
					is_virtual = device.is_virtual,
					value = value,
					raw_value= value
				)
				event_list.append(event)
		if event_list:
			for event in event_list:
				self.joystick_event.emit(event)
		#gremlin.util.singleShot(lambda: self._fire_event_list(event_list))


	def _options_changed(self):
		''' options were changed '''
		config = gremlin.config.Configuration()
		self._verbose_dinput = config.verbose_mode_joystick or config.verbose_mode_dinput
		self._verbose_dinput_extra = self._verbose_dinput and config.verbose_mode_extra
		self._verbose_vjoy = config.verbose_mode_vjoy

		
	def _profile_start(self):
		''' occurs on profile start EVENT LISTENER '''

		self._profile_started = False
		config = gremlin.config.Configuration()
		self._verbose_dinput = config.verbose_mode_joystick or config.verbose_mode_dinput
		self._verbose_dinput_extra = self._verbose_dinput and config.verbose_mode_extra
		self._verbose_vjoy = config.verbose_mode_vjoy
		self._verbose_vjoy_extra = self._verbose_vjoy and config.verbose_mode_extra

		# loopback configuration for vjoy events
		self._vjoy_events.clear() # map of processed events
		# self._vjoy_events_times.clear()# map of processed events times
		self._vjoy_events_delay = config.vjoy_loopback_delay / 1000 # quarter second delay for event loopback checking
		self._vjoy_events_use_time = config.vjoy_loopback_use_time

		# enable mouse hooks 
		self.enableMouse(True)

	def _profile_stopping_cb(self):
		# mode events
		self._profile_started = False
		device_guid = gremlin.shared_state.mode_tab_guid
		delay = 0.250 # delay in seconds between press/release events for mode control change
		master_mode = gremlin.shared_state.master_mode
		extra_data = {'mode' : master_mode} # override execution mode 

		event_stop_pressed = Event(InputType.ModeControl, 
						identifier = gremlin.ui.mode_device.ModeInputModeType.ModeProfileStop,
						device_guid= device_guid,
						is_pressed=True,
						extra_data = extra_data)
		
		event_stop_released = Event(InputType.ModeControl, 
						identifier = gremlin.ui.mode_device.ModeInputModeType.ModeProfileStop,
						device_guid= device_guid,
						is_pressed=False,
						extra_data = extra_data)
		

		eh = EventHandler()
		m2_list, f2_list = eh.execute_event(event_stop_pressed)
		start_release = Timer(delay, lambda : eh._execute_callbacks(event_stop_released, m2_list, f2_list))
		start_release.start()
		

		if not self.enable_mouse_hook:
			self.disableMouse()
		
	
	def _profile_started_cb(self):
		''' occurs on profile start '''
		device_guid = gremlin.shared_state.mode_tab_guid
		mode_enter = gremlin.ui.mode_device.ModeInputModeType.ModeEnter
		delay = 0.250 # delay in seconds between press/release events for mode control change
		new_mode = gremlin.shared_state.runtime_mode
		master_mode = gremlin.shared_state.master_mode
		extra_data = {'mode' : master_mode} # override execution mode 

		event_start_pressed = Event(InputType.ModeControl, 
						identifier = gremlin.ui.mode_device.ModeInputModeType.ModeProfileStart,
						device_guid= device_guid,
						is_pressed=True,
						extra_data = extra_data)
		
		event_start_released = Event(InputType.ModeControl, 
						identifier = gremlin.ui.mode_device.ModeInputModeType.ModeProfileStart,
						device_guid= device_guid,
						is_pressed=False,
						extra_data = extra_data)
		
		
		
		event_enter_pressed = Event(InputType.ModeControl, 
						identifier = mode_enter,
						device_guid= device_guid,
						is_pressed=True,
						extra_data = extra_data)
		event_enter_released = Event(InputType.ModeControl, 
						identifier = mode_enter,
						device_guid= device_guid,
						is_pressed=False,
						extra_data = extra_data)
		

		# read the starting hat states
		self._load_hat_states()

		self._profile_started = True 
		
		# fire mode change for mode enter (press + release)
		eh = EventHandler()


		m2_list, f2_list = eh.execute_event(event_start_pressed)
		start_release = Timer(delay, lambda : eh._execute_callbacks(event_start_released, m2_list, f2_list))
		start_release.start()

		m2_list, f2_list = eh.execute_event(event_enter_pressed)
		enter_release = Timer(delay, lambda : eh._execute_callbacks(event_enter_released, m2_list, f2_list))
		enter_release.start()

		

	def _device_changed_cb(self):
		self._init_joysticks()

	def mouseEnabled(self):
		''' returns mouse hook status '''
		return self.mouse_hook is not None
	
	def enableMouse(self, force = False):
		''' pushes the mouse hook stack - mouse hook is enabled the first time this is called (if options for that allow it) '''
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
				

	def disableMouse(self, reset = False):
		''' pops the mouse hook stack '''
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

	def pop_joystick(self, reset = False):
		gremlin.shared_state.pop_joystick(reset)

	def push_input_selection(self):
		gremlin.shared_state.push_input_selection()

	def pop_input_selection(self, reset = False):
		gremlin.shared_state.pop_input_selection(reset)		


	@property
	def joystick_input_suspended(self) -> bool:
		''' true if joystick input suspended '''
		return gremlin.shared_state.is_joystick_input_suspended

	@property
	def input_selection_suspended(self) -> bool:
		''' true if input selection is suspended '''
		return gremlin.shared_state.is_input_selection_suspended


	def _process_queue(self):
		''' processes an item the keyboard buffer queue '''
		item, is_pressed = self._keyboard_queue.get()
		verbose = gremlin.config.Configuration().verbose_mode_detailed
		is_error = False
		if verbose:
			syslog.info(f"process_queue: found item: {item} is presseD: {is_pressed}")

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
				syslog.info(f"DEQUEUE KEY {gremlin.keyboard.KeyMap.keyid_tostring(key_id)} id: {key_id} vk: {virtual_code} (0x{virtual_code:X}) name: {key.name} pressed: {is_pressed}")
			

			self.keyboard_event.emit(Event(
				event_type= InputType.Keyboard,
				device_guid=dinput.GUID_Keyboard,
				identifier=key_id,
				virtual_code = virtual_code,
				is_pressed=is_pressed,
				data = self._keyboard_buffer
			))

		# process the events
		QtWidgets.QApplication.processEvents()
		self._keyboard_queue.task_done()


	def _keyboard_processor(self):
		''' runs as a thread to process inbound keyboard events using a queue '''

		syslog.info("KBD: processing start")
		self._keyboard_buffer = {}
		self._key_listener_started = True
		threading.current_thread().reset()
		while not self._keyboard_thread.stopped():
			if self._keyboard_queue.empty():
				time.sleep(0.01)
				continue
			self._process_queue()


		# done
		# process any straglers
		while not self._keyboard_queue.empty():
			self._process_queue()
		
		syslog.info("KBD: processing stop")
	

	def start_key_listener(self):
		''' starts the key listener '''
		if not self._key_listener_started:
			self._keyboard_queue = queue.Queue()
			
			self._keyboard_thread = gremlin.threading.AbortableThread(target = self._keyboard_processor)
			self._keyboard_thread.start()

	def stop_key_listener(self):
		''' stops the key listener '''
		if self._key_listener_started:
			self._keyboard_thread.stop()
			self._keyboard_thread.join()
			# clear any remaining input queue items
			while not self._keyboard_queue.empty():
				self._keyboard_queue.get()
			self._keyboard_queue.join()
			self._key_listener_started = False

		

	def start(self):
		''' starts the non regular listener '''
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
		gremlin.shared_state.terminating = True # tell UI we're terminating to avoid uncessary updates if we're shutting down
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
		self.shutdown.emit()


	def reload_calibrations(self):
		"""Reloads the calibration data from the configuration file."""
		from gremlin.util import create_calibration_function
		cfg = gremlin.config.Configuration()
		for key in self._calibrations:
			limits = cfg.get_calibration(key[0], key[1])
			self._calibrations[key] = \
				create_calibration_function(
					limits[0],
					limits[1],
					limits[2]
				)

	def _run(self):
		"""Starts the event loop."""
		
		if not dinput.DILL.initalized:
			dinput.DILL.init()
		syslog.info("DILL: start listen")
		dinput.DILL.set_device_change_callback(self._joystick_device_handler)
		dinput.DILL.set_input_event_callback(self._dinput_event_handler)
		while self._running and not self._run_event.is_set():
			# Keep this thread alive until we are done
			time.sleep(0.05)
		syslog.info("DILL: shutdown")
		dinput.DILL.set_device_change_callback(None)
		dinput.DILL.set_input_event_callback(None)


	def _keep_alive(self):
		''' keep alive 30 second hearbeat '''
		notify_time = time.time()
		while not self._keep_alive_event.is_set():
			if time.time() >= notify_time:
				self.heartbeat.emit()
				notify_time = time.time() + 60*2 # 2 minutes
			time.sleep(1)

	def _handle_vjoy_event(self, vjoyevent : VjoyEvent):	
		''' handles internal loopback events 
		
		this is called whenever GremlinEx sends data to VJOY.
		If the vjoy device is also an input device, VJOY output may or may not trigger a DINPUT event
		and it's not reliable as it looks to be based on timing, thus not predictable.
		If VJOY doesn't trigger DINPUT, it will fail to trigger an input event from VJOY into GremlinEx.
		
		The workaround implemented here is to compare the last DINPUT event for VJOY changes to the expected
		state of the output, and manually trigger an input if different (this essentially fakes a DINPUT event).
		
		
		'''
		import gremlin.util
		vjoy_id = vjoyevent.vjoy_id
		verbose = self._verbose_vjoy
		#verbose = True # debug mode - force output for diagnostics regardless of user settings
		if self._profile_started and self.js.vjoyAsInput(vjoy_id):
			# profile is running and started, and the vjoy device is a loopback device (used as input)
			input_type = vjoyevent.input_type
			input_id = vjoyevent.input_id
			value = vjoyevent.value
			if verbose : syslog.info(f"VJOY EVENT:  [{vjoy_id}] [{input_type.name}] [{input_id}]  value: [{value}]")
			if self.shouldProcessVjoy(vjoy_id, input_type, input_id, value):
				# issue a loop back internal event
				if verbose : syslog.info(f"VJOY EVENT: loopback trigger (exec) {vjoyevent}")
				event = Event.from_vjoyEvent(vjoyevent)
				thread = threading.Thread(target = self._execute_loopback_callback, args = (event,))
				thread.name = "vjoy loopback"
				thread.start()
			else:
				if verbose : syslog.info(f"VJOY EVENT: looback filtered (skip) {vjoyevent}")


	def _execute_loopback_callback(self, event):
		''' executes a vjoy loopback event '''
		# if self._verbose_vjoy : syslog.info(f"VJOY LOOPBACK: trigger execute: {str(event)}")
		eh = EventHandler()
		verbose = self._verbose_vjoy
		# verbose = True # debug mode - force output for diagnostics regardless of user settings
		if verbose : syslog.info(f"VJOY EVENT THREAD: looback execute: {str(event)}")
		eh.execute_event(event)



	#def shouldProcessVjoy(self, vjoy_id : int, input_type : InputType, input_id : int, value, record_only : bool = False) -> bool:
	def shouldProcessVjoy(self, vjoy_id : int, input_type : InputType, input_id : int, value) -> bool:
		''' tracks vjoy events from directinput or internally triggered '''
		import gremlin.joystick_handling
		import gremlin.util
		# get current vjoy state
		
		verbose = self._verbose_vjoy_extra
		#verbose = True

		
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
		if not vjoy_id in self._vjoy_events:
			self._vjoy_events[vjoy_id] = {}
			# self._vjoy_events_times[vjoy_id] = {}
		if not input_type in self._vjoy_events[vjoy_id]:
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
			if verbose: syslog.info(f"\tprior event found")
			# t = self._vjoy_events_times[vjoy_id][input_type][input_id] + self._vjoy_events_delay
			last_value = self._vjoy_events[vjoy_id][input_type][input_id]
			if input_type == InputType.JoystickAxis:
				# account for floating point accuracy issues
				if verbose: syslog.info(f"VJOY LOOPBACK: compare vjoy [{vjoy_id}] [{input_type.name}] [{input_id}]  new value: [{current_value:0.3f}] old value [{last_value:0.3f}]")
				is_close = gremlin.util.is_close(last_value, current_value)
				# duplicated = is_close and t < now if self._vjoy_events_use_time else is_close
				duplicated = is_close
				if duplicated:
					if verbose: syslog.info("\tFAIL (skip event) (axis)")
					return False
				else:
					if verbose: syslog.info("\tSUCCEED (axis)")
			else:
				# button/hat
				current_value = value != 0
				if verbose: syslog.info(f"VJOY LOOPBACK: compare vjoy [{vjoy_id}] [{input_type.name}] [{input_id}]  new value: [{current_value}]  old value: [{last_value}]")
				
				#duplicated = last_value == current_value and t < now if self._vjoy_events_use_time else last_value == current_value
				duplicated = last_value == current_value
				if duplicated:
					if verbose: syslog.info("\tFAIL (skip event) (button)")
					return False # same state, nothing to do
				else:
					if verbose: syslog.info("\tSUCCEED (button)")
		else:
			if verbose: syslog.info(f"\tnew event registered")

		
		# update the data
		self._vjoy_events[vjoy_id][input_type][input_id] = value
		# self._vjoy_events_times[vjoy_id][input_type][input_id] = now
		#if verbose: syslog.info(f"VJOY LOOPBACK: record vjoy state: [{vjoy_id}] [{input_type.name}] [{input_id}]  value: [{value}]")

		return True # process
		

	def _dinput_event_handler(self, data):
		"""Callback for joystick events.

		The handler converts the event data into a signal which is then
		emitted.  IMPORTANT: Applies any calibration and curvature to the data before firing other events.

		:param data the joystick event
		"""

		import vjoy.vjoy

		if not gremlin.joystick_handling._joystick_initialized:
			# not initialized yet
			return 

		if gremlin.shared_state.is_joystick_suspended:
			# ignore if joystick input is suspended
			return


		from gremlin.util import dill_hat_lookup
		verbose = self._verbose_dinput
		verbose_extra = self._verbose_dinput_extra
		
		
		event = dinput.InputEvent(data)

		if verbose: syslog.info(f"DINPUT EVENT: {event}")
			

		event_list = []

		#breakpoint()
		device = gremlin.joystick_handling.device_info_from_guid(event.device_guid)
		if device is None:
			# device not initialized/not found = ignore
			return 
		
		is_virtual = device.is_virtual if device is not None else False
		if is_virtual:
			vjoy_id = device.vjoy_id
			if self.js.inputIgnored(data.device_guid):
				# ignore if the device is set to input ignore
				if verbose: syslog.info(f"Ignore input: {device.name} input: {event.input_index} type: {event.input_type}")
				return
		
			if self.js.vjoyAsInput(vjoy_id):
				# update the event tracker for loop back devices
				# we need to record the event because vjoy can sometimes trigger, or not trigger a DINPUT event when it's receiving commands.
				verbose_vjoy = self._verbose_vjoy
				input_id = event.input_index
				value = event.value
				if event.input_type == dinput.InputType.Axis:
					input_type = InputType.JoystickAxis
				elif event.input_type == dinput.InputType.Button:
					input_type = InputType.JoystickButton
					value = value != 0 # convert to boolean - true if pressed, false if not
				elif event.input_type == dinput.InputType.Hat:
					input_type = InputType.JoystickHat
					# convert value to tuple for hat value comparisons
					value = vjoy.vjoy.Hat.getDirection(value)
				else:
					if verbose_vjoy: syslog.error(f"DINPUT VJOY LOOPBACK: don't know how to handle input type: {event.input_type}")
					input_type = None

				if input_type:
					# track the input event
					if verbose_vjoy: syslog.info(f"DINPUT VJOY LOOPBACK: register vjoy [{vjoy_id}] [{input_type.name}] [{input_id}]  value: [{value}]")
					if not self.shouldProcessVjoy(vjoy_id, input_type, input_id, value):
						return # skip DINPUT event

		if event.input_type == dinput.InputType.Axis:
			if verbose and verbose_extra:
				syslog.info(f"DINPUT AXIS: {event}")

			# get the curved input if the input is curved
			raw_value = event.value
			
			value, should_process = self._apply_calibration(event, True)
			if not should_process:
				return
			
			curved_value = self._apply_curve_ex(event.device_guid, event.input_index, value)
			event = Event(
				event_type= InputType.JoystickAxis,
				device_guid=event.device_guid,
				identifier=event.input_index,
				value = value,
				curved_value = curved_value,
				raw_value= raw_value,
				is_axis = True,
				is_virtual = is_virtual
			)

			event_list.append(event)

			# notify axis change for tab switches
			if not gremlin.shared_state.is_running:
				if AxisState().shouldProcess(event,"state_change"):
					self.axis_state_change.emit(event)

			

		elif event.input_type == dinput.InputType.Button:
			if verbose:
				syslog.info(f"DINPUT BUTTON: {event}")
			is_pressed = event.value == 1
			event = Event(
				event_type= InputType.JoystickButton,
				device_guid= event.device_guid,
				identifier= event.input_index,
				is_pressed= is_pressed,
				is_virtual = is_virtual,
				value = is_pressed
			)
			
			if not gremlin.shared_state.is_running:
				# wrap event so it fires on UI thread
				#gremlin.util.singleShot(lambda : self.button_state_change.emit(event))
				self.button_state_change.emit(event)

			event_list.append(event)

			
		elif event.input_type == dinput.InputType.Hat:

			# hats trigger two events, one for the changed from the original position (release)
			# and the other for the move to the new position (press)

			device_id = str(event.device_guid)
			input_id = event.input_index
			value = dill_hat_lookup[event.value]

			key = (device_id, input_id)

			if not key in self._hat_state:
				self._hat_state[key] = False

			current = self._hat_state[key]
			if current != value:

				# update the new state
				self._hat_state[key] = value

				# release the old value
				new_event = Event(
					event_type= InputType.JoystickHat,
					device_guid = event.device_guid,
					identifier = event.input_index,
					is_pressed = False,
					is_virtual = is_virtual,
					value = value,
					raw_value= current
				)

				event_list.append(new_event)

				# press the new value
				new_event = Event(
					event_type= InputType.JoystickHat,
					device_guid = event.device_guid,
					identifier = event.input_index,
					is_pressed = True,
					is_virtual = is_virtual,
					value = value ,
					raw_value= value
				)

				event_list.append(new_event)
				
				if not gremlin.shared_state.is_running:
					for evt in event_list:
						gremlin.util.singleShot(lambda : self.button_state_change.emit(evt))



		if event_list:		
			for event in event_list:
				self.joystick_event.emit(event)
			

	def _joystick_device_handler(self, data, action):
		"""Callback for device change events.

		This is called when a device is added or removed from the system. This
		uses a timer to call the actual device update function to prevent
		the addition or removal of a multiple devices at the same time to
		cause repeat updates.

		:param data information about the device changing state
		:param action whether the device was added or removed
		"""

		# ignore if a VIGEM device - these are handled, for the moment, directly by the action
		if data.vendor_id == 0x045E and data.product_id == 0x28E and data.button_count == 10 and data.name == b'Controller (XBOX 360 For Windows)':
			return


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
		""" low level handler for callback for keyboard events.

		The handler converts the event data into a signal which is then
		emitted.

		:param event the keyboard event
		"""
		verbose = gremlin.config.Configuration().verbose_mode_keyboard

		# verbose = True
		virtual_code = event.virtual_code
		key_id = (event.scan_code, event.is_extended)
		is_pressed = event.is_pressed
		if verbose:
			syslog.info(f"Recorded key: {key_id:} sc: {event.scan_code:X} ex: {event.is_extended} vk: {virtual_code} (0x{virtual_code:X}) pressed: {is_pressed}")

		# deal with any code translations needed
		key_id = gremlin.keyboard.KeyMap.translate_lookup(key_id) # modify scan codes if needed	
		virtual_code = gremlin.keyboard.KeyMap.vk_lookup(key_id) # get virtual code
		if verbose:
			syslog.info(f"Translated key: {key_id:} sc: {event.scan_code:X} ex: {event.is_extended} vk: {virtual_code} (0x{virtual_code:X}) pressed: {is_pressed}")

		
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
			#print (f"FIRE KEY {key_id} pressed {is_pressed}")
			self.keyboard_event.emit(
				Event(	event_type= InputType.Keyboard,
						device_guid=dinput.GUID_Keyboard,
						identifier= key_id,
						virtual_code = virtual_code,
						is_pressed=is_pressed,
						data = self._keyboard_state.copy() # use a copy of the keyboard state at the time the key is sent
			))

			
		
		# Allow the windows event to propagate further
		return True
	
	def get_key_state(self, key: gremlin.keyboard.Key):
		''' returns the state of the given key '''
		return self._keyboard_state.get(key.index_tuple(), False)
	
	def get_shifted_state(self):
		''' returns true if either of the shift keys are down'''
		lshift_key = gremlin.keyboard.Key(scan_code = gremlin.keyboard.scan_codes.sc_shiftLeft)
		if self.get_key_state(lshift_key):
			return True
		rshift_key = gremlin.keyboard.Key(scan_code = gremlin.keyboard.scan_codes.sc_shiftRight)
		if self.get_key_state(rshift_key):
			return True
		return False
	
	def get_control_state(self):
		''' returns true if either of the control keys are down '''
		lctrl_key = gremlin.keyboard.Key(scan_code = gremlin.keyboard.scan_codes.sc_controlLeft)
		if self.get_key_state(lctrl_key):
			return True
		rctrl_key = gremlin.keyboard.Key(scan_code = gremlin.keyboard.scan_codes.sc_controlRight)
		if self.get_key_state(rctrl_key):
			return True
		return False


	def _mouse_handler(self, event):
		"""Callback for mouse events.

		The handler converts the event data into a signal which is then
		emitted.

		:param event the mouse event
		"""
		import gremlin.windows_event_hook
		
		# Ignore events we created via the macro system
		if not event.is_injected:
			if not self._running:
				return

			# translate mouse input to a keyboard input
			key = gremlin.keyboard.key_from_mousebutton(event.button_id)
			if key:
				evt = gremlin.windows_event_hook.KeyEvent(
					virtual_code = key.virtual_code, 
					scan_code = key.scan_code, 
					is_extended = key.is_extended,
					is_pressed = event.is_pressed,
					is_injected = event.is_injected)
				self._keyboard_handler(evt)
			# key_id = (event.button_id.value + 0x1000, False)
			# self._keyboard_state[key_id] = event.is_pressed

			# syslog.info(f"mouse event: {str(event)} key id: {key_id}")

			mouse_event = Event(
				event_type= InputType.Mouse,
				device_guid=dinput.GUID_Keyboard,
				identifier=event.button_id, # mouse handler is expecting a mouse ID, not a keyboard ID
				is_pressed=event.is_pressed,
				data = self._keyboard_state
			)

			self.mouse_event.emit(mouse_event)
			
		# Allow the windows event to propagate further
		return True

	def _apply_calibration(self, event, return_process : bool = False) -> tuple:
		''' applies calibration data to the vent
		:param event: the event data
		:returns: (value, should_process)

		'''
		return self._apply_calibration_ex(event.device_guid, event.input_index, event.value, return_process)
	
	def _apply_curve(self, event):
		''' applies input curves to the input '''
		return self._apply_curve_ex(event.device_guid, event.input_index, event.value)
		
	def _apply_calibration_ex(self, device_guid, input_id, value, filter : bool = False) -> tuple:
		''' applies calibration and deadzone data to the raw input - value -32768 to 32767, returns -1, +1 and optionally inverts the input, and sets the process flag '''
		calibration = self.calibrationManager.getCalibration(device_guid, input_id)
		verbose = gremlin.config.Configuration().verbose_mode_joystick
		new_value = calibration.getValue(value, filter = filter)
		if verbose:
			device = gremlin.joystick_handling.device_info_from_guid(device_guid)
			syslog.info(f"CALIBRATION: filter: device: [{device.name}] id: [{device_guid}] filter: [{filter}] in: {value:0.3f} out: {new_value[0]:0.3f}") 

		return new_value


	def getAxisValues(self, device_guid, input_id) -> AxisData:
		''' gets axis data values for the given axis '''
		return AxisState().getAxisValues(device_guid, input_id)
		
	def _apply_curve_ex(self, device_guid, input_id, value : float):
		''' applies a curve to the input axis '''
		curved_value = AxisState().applyCurve(device_guid, input_id, value)
		if curved_value is not None:
			verbose = gremlin.config.Configuration().verbose_mode_curve
			if verbose:
				device = gremlin.joystick_handling.device_info_from_guid(device_guid)
				syslog.info(f"APPLY CURVE: device: [{device.name}] id: [{device_guid}] in: {value:0.4f} out: {curved_value:0.4f}")
			return curved_value
		# no curve applied
		return value
	
	def apply_transforms(self, device_guid, input_id, raw_value):
		''' applies raw transforms to the data - input is expected in dinput range (-32K to +32k)'''
		calib_value = self._apply_calibration_ex(device_guid, input_id, raw_value)
		curved_value = self._apply_curve_ex(device_guid, input_id, calib_value)
		#print(f"Raw value: {raw_value:0.4f} filtered: {calib_value:0.4f} Curved value: {curved_value:0.4f}")
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
			limits = cfg.get_calibration(
				device_info.device_guid,
				entry.axis_index
			)
			self._calibrations[(device_info.device_guid, entry.axis_index)] = \
				create_calibration_function(
					limits[0],
					limits[1],
					limits[2]
				)


class TTSNotifyData():
	''' holds TTS data notification '''
	def __init__(self):
		self.profile = None
		self.mode = None

@gremlin.singleton_decorator.SingletonDecorator
class EventHandler(QtCore.QObject):

	"""Listens to the inputs from multiple different input devices."""


	mode_status_update = Signal() # tell the UI to update the mode status bar

	# signal emitted when the profile is changed
	profile_changed = Signal(str)

	# Signal emitted when the application is pause / resumed
	is_active = Signal(bool)

	last_action_changed = Signal(object, str) # fires when the action changes in the selector (drop_down, name)
	last_container_changed = Signal(object, str) # fires when the action changes in the selector (drop_down, name)

	


	def __init__(self):
		"""Initializes the EventHandler instance."""
		QtCore.QObject.__init__(self)
		self.plugins = {}
		self._mode_validator_callbacks = {}  # list of validators (callbacks) that return a boolean True if the mode change can occur - signature must be callable(str)->bool
		self._last_tts_data = TTSNotifyData() # last mode that triggered a TTS verbal notice
		
		el = EventListener()
		el.profile_start.connect(self._profile_start)
		el.profile_stop.connect(self._profile_stop)
		el.profile_started.connect(self._profile_started)
		el.runtime_mode_changed.connect(self._update_mode_change)
		self._lock = threading.Lock()
		self._started = False
		self._execute_queue = [] # list of items to execute
		self._execute_thread = None
		self._execute_running = False
		self.reset()
	
	# def _queue_start(self):
	# 	if not self._execute_running:
	# 		syslog.info("EVENT QUEUE: start")
	# 		self._execute_queue.clear()
	# 		self._execute_running = True
	# 		self._execute_thread = threading.Thread(target = self._execute_queue_runner)
	# 		self._execute_thread.name = "Execution queue runner"
	# 		self._execute_thread.start()


	# def _queue_stop(self):
	# 	if self._execute_running:
	# 		syslog.info("EVENT QUEUE: stopping...")
	# 		self._execute_running = False
	# 		self._execute_thread.join()
	# 		self._execute_thread = None
	# 		syslog.info("EVENT QUEUE: stopped")

	# def _queue_add(self, event, m_list, f_list):
	# 	''' add execution items to the list '''
	# 	if self._execute_running:
	# 		syslog.info(f"EVENT QUEUE: add: {str(event)}")
	# 		self._execute_queue.append((event, m_list, f_list)) # this is thread safe in Python
		
	
	# def _execute_queue_runner(self):
	# 	''' execution queue runner '''
	# 	while self._execute_running:
	# 		if self._execute_queue:
	# 			event, m_list, f_list = self._execute_queue.pop(0)
	# 			self._execute_callbacks(event, m_list, f_list)
	# 			time.sleep(0.01)
		
	# 	# stop executing requested = clear the queue
	# 	while self._execute_queue:
	# 		event, m_list, f_list = self._execute_queue.pop(0)
	# 		self._execute_callbacks(event, m_list, f_list)
	# 		time.sleep(0.01)
		

	def _profile_start(self):
		'''' profile start event - EVENT HANDLER '''
		if not self._started:
			self._started = True
			self._last_vjoy_event = None # reset vjoy loopback
			# self._queue_start()
			self._update_mode_change(gremlin.shared_state.runtime_mode)
			



	def _profile_started(self):
		''' occurs when profile has started - hook functors '''
		pass
	
	def _profile_stop(self):
		if self._started:
			# self._queue_stop() # finish up and stop the current execution queue
			self._started = False
			self._last_tts_notify = None
			self._last_tts_notify_time = None
	
	def registerModeValidator(self, callback):
		assert callable(callback)
		self._mode_validator_callbacks[callback] = callback

	def unregisterModeValidator(self, callback):
		if callback in self._mode_validator_callbacks:
			del self._mode_validator_callbacks[callback]

	def clearModeValidator(self):
		self._mode_validator_callbacks.clear()

	def runModeValidator(self, mode):
		''' runs through all current validators to see if a mode change can occur '''
		result = True # assume we can
		for callback in self._mode_validator_callbacks:
			result = result and callback(mode)
			if not result: 
				break

		return result

		

	def reset(self):
		''' reset even handling for runtime '''
		config =  gremlin.config.Configuration()
		verbose = config.verbose
		if verbose:
			syslog.info("EventHandler: reset()")
			
		self.process_callbacks = True
		self.callbacks = {}
		self.callback_key_map = {} # map of event callbackKey to event
		self.input_item_map = {} # map of input items keyed by device_guid, mode, input_type, input_id
		self.latched_events = {}
		self.latched_callbacks = {}
		self.midi_callbacks = {}
		self.osc_callbacks = {}
		self.state_callbacks = {}
		self._event_lookup = {}
		self.latched_functors = {}
		self.experimental = config.experimental
		self._last_vjoy_event = None # tracks the last VJOY event for loopback detection
		
		

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
		''' gets the current mode based on state '''
		return gremlin.shared_state.current_mode

	@property
	def previous_runtime_mode(self):
		''' returns the previous mode '''
		return gremlin.shared_state.previous_runtime_mode
	
	@previous_runtime_mode.setter
	def previous_runtime_mode(self, value):
		''' sets the active mode '''
		gremlin.shared_state.previous_runtime_mode = value


	def add_plugin(self, plugin):
		"""Adds a new plugin to be attached to event callbacks.

		:param plugin the plugin to add
		"""
		# Do not add the same type of plugin multiple times
		if plugin.keyword not in self.plugins:
			self.plugins[plugin.keyword] = plugin

	def dump_exectree(self, device_guid, mode, event):
		''' outputs the execution tree to the log '''
		from types import FunctionType, MethodType

		verbose = gremlin.config.Configuration().verbose
		if not verbose:
			return
		
		get_device_name = gremlin.shared_state.get_device_name
		device_name = gremlin.shared_state.get_device_name(device_guid)
		
		for callbacks in self.callbacks[device_guid][mode][event.callbackKey]:
			for callback in callbacks:
				if not hasattr(callback,"execution_graph"):
					syslog.debug(f"\tDevice ID: {device_name}  mode: {mode} event: {event} - skip callback - missing execution graph - don't know how to handle {type(callback)} *********")
					continue
				
				for callback_functor in callback.execution_graph.functors:
					if hasattr(callback_functor,"action_set"):
						for functor in callback_functor.action_set.functors:
							action_data = functor.action_data if hasattr(functor, "action_data") else None
							syslog.debug(f"\tDevice ID: {device_name} mode: {mode} event: {event} hash: {hash(event):X} type: {type(functor)}")
							if action_data:
								# dump member variables only
								syslog.debug("\t\tData block:")
								for attr in dir(action_data):
									if not attr.startswith("_"):
										item = getattr(action_data,attr)
										
										if not (isinstance(item, FunctionType) or isinstance(item, MethodType) or inspect.isabstract(item) or inspect.isclass(item)):
											syslog.debug(f"\t\t\t{attr}: {item}")
					else:
						syslog.debug(f"\tFunctor '{type(callback_functor).__name__} does not define an action set")
					
								




	def dump_callbacks(self):
		# dump latched events
		import gremlin.ui.keyboard_device
		import gremlin.shared_state

		
		get_device_name = gremlin.shared_state.get_device_name
		
		syslog.debug("------------ Latched Events ----------------")
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
						syslog.debug(f"\tDevice ID: {device_name} mode: {mode} pair: {key_data} data: {identifier.to_string()}")

		syslog.debug("------------ Execution callbacks ----------------")
		for device_guid in self.callbacks.keys():
			for mode in self.callbacks[device_guid].keys():
				for key in self.callbacks[device_guid][mode]:
					event = self.callback_key_map[key]
					self.dump_exectree(device_guid, mode, event)


	def add_latched_functor(self, device_guid, mode, event, functor):
		''' registers an extra latched functor on inputs if a functor uses multiple inputs '''
		# regular event
		if isinstance(device_guid, str):
			# convert to GUID
			device_guid = gremlin.util.parse_guid(device_guid)

		if device_guid not in self.latched_functors:
			self.latched_functors[device_guid] = {}
		if mode not in self.latched_functors[device_guid]:
			self.latched_functors[device_guid][mode] = {}
		key = event.callbackKey
		if not key in self.latched_functors[device_guid][mode]:
			self.latched_functors[device_guid][mode][key] = []
		existing_ids = [f.id for f in self.latched_functors[device_guid][mode][key]]
		if not functor.id in existing_ids:
			self.latched_functors[device_guid][mode][key].append(functor)
			verbose = gremlin.config.Configuration().verbose
			if verbose:
				device_name = gremlin.joystick_handling.device_name_from_guid(device_guid)
				syslog.info(f"Added latched functor: {device_name} mode: {mode} type: {event.event_type.name} input: {event.identifier}  key: {key}")

	def _matching_input_item(self, mode, event):
		''' gets the matching input item from the event '''
		
		device_guid = event.device_guid
		input_type = event.event_type
		if input_type == InputType.Keyboard:
			input_type = InputType.KeyboardLatched
		if input_type == InputType.KeyboardLatched:
			magic = json.dumps(event.identifier)
		else:
			magic = event.identifier
		
		if not device_guid in self.input_item_map:
			return None
		if not mode in self.input_item_map[device_guid]:
			return None
		if not input_type in self.input_item_map[device_guid][mode]:
			return None
		if  magic in self.input_item_map[device_guid][mode][input_type]:
			return self.input_item_map[device_guid][mode][input_type][magic]
		
		# syslog.info(f"No match: {input_type} {magic}")
		# for key in self.input_item_map[device_guid][mode][input_type].keys():
		# 	syslog.info(f"\t{key}")
		return None

		
	def registerInputItem(self, mode : str, input_item):
		''' registers an input item with the event handler '''
		item: gremlin.base_profile.InputItem = input_item
		device_guid = item.device_guid
		input_type = item.input_type
		if input_type == InputType.Keyboard:
			input_type = InputType.KeyboardLatched

		if input_type == InputType.KeyboardLatched:
			# use the key sequence as the magic key
			magic = json.dumps(input_item.input_id.key_tuple)
		else:
			magic = item.input_id
		
		if not device_guid in self.input_item_map:
			self.input_item_map[device_guid] = {}
		if not mode in self.input_item_map[device_guid]:
			self.input_item_map[device_guid][mode] = {}
		if not input_type in self.input_item_map[device_guid][mode]:
			self.input_item_map[device_guid][mode][input_type] = {}
		self.input_item_map[device_guid][mode][input_type][magic] = input_item

		verbose = gremlin.config.Configuration().verbose_mode_inputs
		if verbose: syslog.info(f"Register InputItem: {input_item.display_name} mode {mode} {input_type} magic: {magic}")
			

	def add_callback(self, device_guid, mode, event, callback, permanent=False, node = None):
		"""Installs the provided callback for the given event.

		:param device_guid the GUID of the device the callback is
			associated with
		:param mode the mode the callback belongs to
		:param event the event for which to install the callback
		:param callback the callback function to link to the provided
			event
		:param permanent if True the callback is always active even
			if the system is paused
		:node: the execution tree node
		"""
		import gremlin.config
		import gremlin.ui.keyboard_device
		import gremlin.keyboard

		assert callable(callback)
		
		if event:
			if event.event_type in (InputType.Keyboard, InputType.KeyboardLatched):
				verbose = gremlin.config.Configuration().verbose_mode_keyboard
				# keyboard latched event
				identifier = event.identifier
				primary_key = identifier.key
				



				# verbose = True
				
				# if the key can latch with multiple primary keys, build the table of all combinations
				key_list = [primary_key]
				if primary_key.is_latched:
					# multiple keys
					key_list.extend(primary_key._latched_keys)

				for key in key_list:
 					# the events will arrive as keyboard events - in any order - this makes sure latching is checked regardless of the order of key presses
					 
					
					virtual_code = key.virtual_code
					keyid_source = key.index_tuple() # use the scan code for now
					#index = virtual_code if virtual_code > 0 else keyid
					keyid, _ = gremlin.keyboard.KeyMap.translate(keyid_source)
						
					if device_guid not in self.latched_events.keys():
						self.latched_events[device_guid] = {}
				
					if mode not in self.latched_events[device_guid].keys():
						self.latched_events[device_guid][mode] = {}
					if keyid not in self.latched_events[device_guid][mode].keys():
						self.latched_events[device_guid][mode][keyid] = []
					self.latched_events[device_guid][mode][keyid].append(identifier)
					if verbose:
						syslog.info(f"Key latch registered by guid {device_guid}  mode: {mode} vk: {virtual_code} (0x{virtual_code:X}) source keyid: {gremlin.keyboard.KeyMap.keyid_tostring(keyid_source)} -> translated keyId: {gremlin.keyboard.KeyMap.keyid_tostring(keyid)} name: {key.name} -> {identifier.display_name}")
					

				if device_guid not in self.latched_callbacks.keys():
					self.latched_callbacks[device_guid] = {}
				if mode not in self.latched_callbacks[device_guid].keys():
					self.latched_callbacks[device_guid][mode] = {}
				if not key in self.latched_callbacks[device_guid][mode]:
					self.latched_callbacks[device_guid][mode][primary_key] = []
				data = self.latched_callbacks[device_guid][mode][primary_key]
				data.append((self._install_plugins(callback),permanent))
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
				if not key in self.midi_callbacks[device_guid][mode]:
					self.midi_callbacks[device_guid][mode][key] = []
				data = self.midi_callbacks[device_guid][mode][key]
				data.append((self._install_plugins(callback),permanent))
				if verbose: syslog.info(f"MIDI: register callback {mode} {key}")

			elif event.event_type == InputType.OpenSoundControl:
				# OSC event
				verbose = gremlin.config.Configuration().verbose
				osc_input = event.identifier
				key = osc_input.message_key
				if device_guid not in self.osc_callbacks.keys():
					self.osc_callbacks[device_guid] = {}
				if mode not in self.osc_callbacks[device_guid].keys():
					self.osc_callbacks[device_guid][mode] = {}
				if not key in self.osc_callbacks[device_guid][mode]:
					self.osc_callbacks[device_guid][mode][key] = []
				data = self.osc_callbacks[device_guid][mode][key]
				data.append((self._install_plugins(callback),permanent))

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
					if not key in self.state_callbacks[device_guid][mode]:
						self.state_callbacks[device_guid][mode][key] = []
					data = self.state_callbacks[device_guid][mode][key]
					data.append((self._install_plugins(callback),permanent))
			

			else:
				# regular event - events are stored by the event key
				if device_guid not in self.callbacks:
					self.callbacks[device_guid] = {}
				if mode not in self.callbacks[device_guid]:
					self.callbacks[device_guid][mode] = {}
				key = event.callbackKey
				if key not in self.callbacks[device_guid][mode]:
					self.callbacks[device_guid][mode][key] = []
					self.callback_key_map[key] = event
				self.callbacks[device_guid][mode][key].append((
					self._install_plugins(callback),
					permanent
				))



	def _matching_event_keys(self, event):
		''' gets the list of latched keys for this event '''
		if not event.event_type in (InputType.Keyboard, InputType.KeyboardLatched, InputType.Mouse):
			# not a keyboard event
			return []
		import gremlin.config
		import gremlin.keyboard

		# convert mouse events to keyboard event
		if event.event_type == InputType.Mouse:
			from gremlin.ui.keyboard_device import KeyboardDeviceTabWidget
			device_guid = KeyboardDeviceTabWidget.device_guid
			
			mouse_button = event.identifier
			# convert the mouse button to the virtual scan code we use for mouse events
			index = (mouse_button.value + 0x1000, False)
			verbose = gremlin.config.Configuration().verbose_mode_mouse
			if verbose:
				syslog.info(f"matching mouse event {event.identifier} to {gremlin.keyboard.KeyMap.keyid_tostring(index)}")
		else:
			verbose = gremlin.config.Configuration().verbose_mode_keyboard
			device_guid = event.device_guid
			# index = event.virtual_code if event.virtual_code > 0 else event.identifier  # this is (scan_code, is_extended)
			index, _ = gremlin.keyboard.KeyMap.translate(event.identifier)
			if verbose: syslog.info(f"matching key event {event.identifier} to {gremlin.keyboard.KeyMap.keyid_tostring(index)}")

		#event_key = Key(scan_code = identifier[0], is_extended = identifier[1], is_mouse = is_mouse, virtual_code= virtual_code)
		input_items = []

		
	
		if device_guid in self.latched_events:
			
			#print (f"found guid: {device_guid}")
			data = self.latched_events[event.device_guid]
			if self.runtime_mode in data.keys():
				data = data[self.runtime_mode]
				matching_keys = []
				if index in data.keys():
					#print ("found identifier")
					matching_keys = data[index]
				if not matching_keys:
					index_ex = (index[0], not index[1])
					if index_ex in data.keys():
						matching_keys = data[index_ex]

				for input_item in matching_keys:
					# key = input_item.key
					input_items.append(input_item)

				if verbose: syslog.info(f"KEY: found {len(input_items)} matching items")
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
		''' requests a profile load '''
		if new_profile != gremlin.shared_state.current_profile:
			self.profile_change.emit(new_profile)


	def set_mode(self, new_mode):
		''' sets the edit or runtime mode based on the state  '''
		assert new_mode,"Mode cannot be blank"
		if gremlin.shared_state.is_running:
			gremlin.shared_state.runtime_mode = new_mode
		else:
			gremlin.shared_state.edit_mode = new_mode

	def set_runtime_mode(self, new_mode):
		''' sets the active runtime mode '''
		assert new_mode,"Mode cannot be blank"
		gremlin.shared_state.runtime_mode = new_mode

	def set_edit_mode(self, new_mode):
		''' sets the active edit mode '''
		assert new_mode,"Mode cannot be blank"
		gremlin.shared_state.edit_mode = new_mode

	@QtCore.Slot(str)
	def _update_mode_change(self, mode):
		config = gremlin.config.Configuration()
		if config.initial_load_mode_tts and config.tts_mode_switch_enabled:
			# output verbal notification if requested
			data = self._last_tts_data
			profile = gremlin.shared_state.current_profile
			if data.mode is None or data.profile is None or data.mode != mode or data.profile != profile:
				self._last_tts_data.mode = mode
				self._last_tts_data.profile = profile
				tts = gremlin.tts.TextToSpeech()
				rate = gremlin.config.Configuration().initial_load_rate_tts
				tts.speak(f"New mode {mode}", rate) # default rate is 100

	def TTSNotify(self, text):
			''' outputs a notification only if TTS notifications are enabled and the profile/mode is different from the last message issued'''
			config = gremlin.config.Configuration()
			if config.initial_load_mode_tts and config.tts_mode_switch_enabled:
				data = self._last_tts_data
				profile = gremlin.shared_state.current_profile
				mode = gremlin.shared_state.current_mode
				if data.mode is None or data.profile is None or data.mode != mode or data.profile != profile:
					self._last_tts_data.mode = mode
					self._last_tts_data.profile = profile
					rate = config.initial_load_rate_tts
					tts = gremlin.tts.TextToSpeech()
					tts.speak(text, rate) # default rate is 100
	

	def change_mode(self, new_mode, emit = True, force_update = False, tts = True, validate = True):
		"""Changes the GremlinEx currently active mode.

		:param new_mode: the new mode to use
		:param emit: enables signal 
		:param force_update: forces a mode change even if already in the mode
		:param validate: validates change mode, set to false to remove validation
		"""

		import gremlin.ui.mode_device


		el = EventListener()
		try:
		

			gremlin.util.pushCursor()

			config = gremlin.config.Configuration()
			verbose = config.verbose
			current_profile = gremlin.shared_state.current_profile
			is_running = gremlin.shared_state.is_running
			

			if verbose:
				if is_running:
					syslog.debug(f"CHANGE MODE: (runtime) change mode to [{new_mode}] requested - active mode: [{gremlin.shared_state.runtime_mode}]  current mode: [{gremlin.shared_state.current_mode}] profile '{current_profile.name}'")	
				else:
					syslog.debug(f"CHANGE MODE: (edit time) change mode to [{new_mode}] requested - active mode: [{gremlin.shared_state.runtime_mode}]  current mode: [{gremlin.shared_state.current_mode}] profile '{current_profile.name}'")
			


			if new_mode == self.current_mode and not force_update:
				# already in this mode
				return
			
			el.push_input_selection()
			
			profile_modes = current_profile.get_modes()
			mode_exists = new_mode in profile_modes
			
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
				return

			if is_running:
				# runtime event (prevents UI from reloading)
				# if verbose:
				# 	syslog.debug(f"EVENT: (runtime) change mode to [{new_mode}] requested - active mode: [{gremlin.shared_state.runtime_mode}]  current mode: [{gremlin.shared_state.current_mode}] profile '{current_profile.name}'")


				if self.runtime_mode != new_mode or force_update:
					import gremlin.shared_state
					device_guid = gremlin.shared_state.mode_tab_guid
					mode_enter = gremlin.ui.mode_device.ModeInputModeType.ModeEnter
					mode_exit = gremlin.ui.mode_device.ModeInputModeType.ModeExit
					delay = 0.250 # delay in seconds between press/release events for mode control change

					# fire off any mode changes
					event_exit_pressed = Event(InputType.ModeControl, 
								identifier = mode_exit,
								device_guid= device_guid,
								is_pressed=True,
								mode = self.runtime_mode,
								override_input_type=InputType.JoystickButton)
					event_exit_released = Event(InputType.ModeControl, 
								identifier = mode_exit,
								device_guid= device_guid,
								is_pressed=False,
								mode = self.runtime_mode,
								override_input_type=InputType.JoystickButton)
					
					event_enter_pressed = Event(InputType.ModeControl, 
								identifier = mode_enter,
								device_guid= device_guid,
								is_pressed=True,
								mode = new_mode,
								override_input_type=InputType.JoystickButton)
					event_enter_released = Event(InputType.ModeControl, 
								identifier = mode_enter,
								device_guid= device_guid,
								is_pressed=False,
								mode = new_mode,
								override_input_type=InputType.JoystickButton)
					
					# fire mode change control for mode exit (press + release)
					m1_list, f1_list = self.execute_event(event_exit_pressed)
					exit_release = Timer(delay, lambda : self._execute_callbacks(event_exit_released, m1_list, f1_list))
					exit_release.start()
					
					if validate:
						result = self.runModeValidator(new_mode)
						if not result:
							syslog.warning(f"CHANGE MODE: {current_profile.name} - mode change request to {new_mode} not authorized by a module - request ignored")
							return


					self.previous_runtime_mode = self.runtime_mode
					gremlin.shared_state.runtime_mode = new_mode
					# remember the last mode for this profile
					
					current_profile.set_last_runtime_mode(self.runtime_mode)
					self.previous_runtime_mode = self.runtime_mode
					self.runtime_mode = new_mode
					if verbose: syslog.info(f"CHANGE MODE: [{current_profile.name}] - Runtime Mode switch to: {new_mode}")
					if emit:
						el.runtime_mode_changed.emit(new_mode)

					# fire mode change for mode enter (press + release)
					m2_list, f2_list = self.execute_event(event_enter_pressed)
					enter_release = Timer(delay, lambda : self._execute_callbacks(event_enter_released, m2_list, f2_list))
					enter_release.start()

			else:
				# non-runtime
				assert new_mode,"new mode cannot be blank"
				if self.edit_mode != new_mode or force_update:
					gremlin.config.Configuration().set_profile_last_edit_mode(new_mode)
					gremlin.shared_state.edit_mode = new_mode
					self.edit_mode = new_mode
					syslog.debug(f"Profile: {current_profile.name} - Design time Mode switch to: {new_mode}")
					if emit:
						el.edit_mode_changed.emit(self.edit_mode)
						
			el.pop_input_selection()

			# update the status bar
			self.mode_status_update.emit()

			# update the selection
			device_guid, input_type, input_id = gremlin.config.Configuration().get_last_input()
			if input_type and input_id:
				el.select_input.emit(device_guid, input_type, input_id, False, True, False)

			# fire the UI update on change mode      
			el.update_input_state.emit(device_guid)  # force a UI widget status update	
		finally:	
			gremlin.util.popCursor()

		



	

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
		

	def execute_event(self, event : Event):
		''' main execution (runtime) event handler - queues trigger callbacks on event input '''
		
		import gremlin.config
		import gremlin.keyboard

		
		config =  gremlin.config.Configuration()
		verbose = config.verbose_mode_inputs
		verbose_detailed = verbose and config.verbose_mode_extra
		
		try:
			
			#if verbose: syslog.info("EVENT EXECUTE: enter critical phase")

			# self._lock.acquire()
			
			# mode to act on
			mode = event.mode if event.mode else self.runtime_mode  


			if verbose and event.event_type != InputType.JoystickAxis:
				syslog.info(f"EVENT EXECUTE: process event - mode [{mode}] event: {str(event)}")


			# if event.extra_data and "vjoy" in event.extra_data:
			# 	# event is a vjoy event
			# 	syslog.info(f"EXEC EVENT: got vjoy event: {event.extra_data["vjoy"]}")
			# 	if self._last_vjoy_event:
			# 		k1 = event.extra_data["vjoy"]
			# 		k2 = self._last_vjoy_event.extra_data["vjoy"]
			# 		if k1 == k2:
			# 			syslog.info(f"EXEC EVENT: skipping duplicate vjoy event: {k1}")
			# 			return 
			# 	self._last_vjoy_event = event # record last vjoy event
			# 	syslog.info(f"EXEC EVENT: processing vjoy event: {event.extra_data["vjoy"]}")
					
			

			# list of callbacks
			m_list = []
			f_list = []




			input_item = self._matching_input_item(mode, event)
			if input_item is not None and not input_item.enabled:
				# input item registered but not enabled - ignore inputs that aren't registered or could not be found (latched keys for example)
				if verbose: syslog.info(f"Event: input disabled {str(event)}")
				return

			# filter latched keyboard or mouse events
			if event.event_type in (InputType.Keyboard, InputType.KeyboardLatched, InputType.Mouse):
				verbose = gremlin.config.Configuration().verbose_mode_detailed
				data = event.data # holds keyboard state info
				if event.event_type == InputType.Mouse:
					verbose = gremlin.config.Configuration().verbose_mode_mouse
				if verbose:
					syslog.info(f"process keyboard event: {event}")
					syslog.info(f"\tKeyboard state data:")
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
						if verbose: syslog.info("-"*50)
						is_latched = True
						latch_key = None
						# print (data)
						latched_keys = [input_item.key]
						latched_keys.extend(input_item.latched_keys)
						if verbose: syslog.info(f"KEY: Checking latching: {len(latched_keys)} key(s)")
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
									syslog.info(f"\tcheck latched key: {gremlin.keyboard.KeyMap.keyid_tostring(index)} {k.name} found: {found} state: {state} {'*****' if state else ''}")
									if not found:
										syslog.info(f"\t\t* Key not found *")
								is_latched = is_latched and state # make sure all latched keys are currently pressed (state = True)

						if verbose:	syslog.info(f"\tLatched state: {is_latched}")
						
						if is_latched:
							latch_key = input_item.key

					

						if latch_key:

							# override the event type to a keyboard so actions think we're using a keyboard when using a mouse click
							event.override_input_type = InputType.Keyboard

							#print (f"Found latched key: {latch_key}")
							m_list = self._matching_latched_callbacks(event, latch_key)
							if m_list:
								if verbose:
									trigger_line = "***** TRIGGER " + "*"*30
									syslog.info(trigger_line)
									syslog.info(f"\tmode: [{mode}] Found latched key: Check key {latch_key.name} callbacks: {len(m_list)} event: {event}")
									syslog.info(trigger_line)
								self._trigger_callbacks(m_list, event)
								return
							# else:
							# 	print (f"No callbacks found for: {latch_key}")
					verbose = gremlin.config.Configuration().verbose_mode_inputs
				else:
					if verbose:
						syslog.info("No matching events")
				return None, None
							
			elif event.event_type ==InputType.Midi:
				m_list = self._matching_midi_callbacks(event)
				if verbose_detailed and not (m_list or f_list): syslog.info(f"EVENT: [MIDI] no matching inputs for {str(event.identifier.message_key)} mode: {self.runtime_mode}")
						
			elif event.event_type == InputType.OpenSoundControl:
				m_list = self._matching_osc_callbacks(event)
				if verbose_detailed and not (m_list or f_list): syslog.info(f"EVENT: [OSC] no matching inputs for {event.identifier.message_key} mode: {self.runtime_mode}")
			elif event.event_type == InputType.State:
				m_list = self._matching_state_callbacks(event)
				if verbose_detailed and not (m_list or f_list): syslog.info(f"EVENT: [STATE] no matching inputs for {event.identifier.message_key} mode: {self.runtime_mode}")
			elif event.event_type == InputType.JoystickAxis:
				m_list = self._matching_callbacks(event)
				f_list = self._matching_functors(event)
				if verbose_detailed and not (m_list or f_list): syslog.info(f"EVENT: [Joystick] no matching inputs for {str(event.identifier)} mode: {self.runtime_mode}")
			elif event.event_type in (InputType.JoystickButton, InputType.JoystickHat, InputType.OctaviIfr1):
				
				m_list = self._matching_callbacks(event)
				f_list = self._matching_functors(event)
				
				
				if not (m_list or f_list): 
					if verbose_detailed: syslog.info(f"EVENT: [Joystick] no matching inputs for {str(event.identifier)} mode: {self.runtime_mode}")
				else:
					if verbose: syslog.info(f"EVENT: [Joystick] found callbacks for {str(event.identifier)} mode: {self.runtime_mode}  m: {len(m_list)} f: {len(f_list)}")
				# if verbose_detailed and not (m_list or f_list): syslog.info(f"EVENT: [Joystick] no matching inputs for {str(event.identifier)} mode: {self.runtime_mode}")
			else:
				# other inputs including control inputs
				
				m_list = self._matching_callbacks(event)
				f_list = self._matching_functors(event)
				if verbose_detailed and not (m_list or f_list): syslog.info(f"EVENT: [Generic] no matching inputs for {str(event.identifier)} mode: {self.runtime_mode}")

			if m_list or f_list:
				# self._queue_add(event, m_list, f_list)
				self._execute_callbacks(event, m_list, f_list)

			return m_list, f_list
		except Exception as err:
			syslog.error(f"EVENT EXECUTE: error: {err}\n{traceback.format_exc()}")
		finally:
			#if verbose: syslog.info("EVENT EXECUTE: exit critical phase")
			# self._lock.release()
			pass




	def _trigger_callbacks(self, callbacks, event):
		''' trigger regular callbacks '''
		#verbose = gremlin.config.Configuration().verbose'
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


	def _trigger_functor_callbacks(self, functors, event : Event):
		''' trigger functor callbacks '''
		#verbose = gremlin.config.Configuration().verbose'
		import gremlin.actions
		for functor in functors:
			try:
				functor.process_event(event, gremlin.actions.Value(event.value))
			except Exception as ex:
				syslog.error(f"FUNCTOR CALLBACK: error {ex}")				
				tb_msg = traceback.format_exc()
				syslog.error(tb_msg)



	def _execute_callbacks(self, event, m_list, f_list):
		''' triggers callbacks '''
		if m_list:
			self._trigger_callbacks(m_list, event)
			return # don't do f_list if m_list processed

		if f_list:
			self._trigger_functor_callbacks(f_list, event)



	def _matching_midi_callbacks(self, event):
		''' returns list of callbacks matching the event '''
		callback_list = []
		if event.event_type == InputType.Midi:
			key = event.identifier.message_key
			import gremlin.ui.midi_device
			# if event.identifier.command == gremlin.ui.midi_device.MidiCommandType.SysEx:
			# 		pass
			if event.device_guid in self.midi_callbacks:
				import gremlin.execution_graph
				ec = gremlin.execution_graph.ExecutionContext() # current execution context
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
		''' returns list of callbacks matching the event '''
		callback_list = []
		if event.event_type == InputType.OpenSoundControl:
			key = event.identifier.message_key
			if event.device_guid in self.osc_callbacks:
				import gremlin.execution_graph
				ec = gremlin.execution_graph.ExecutionContext() # current execution context
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
		''' returns list of callbacks matching the event '''
		import gremlin.config
		import gremlin.execution_graph
		callback_list = []
		if event.event_type == InputType.State:
			key = event.identifier.message_key
			if event.device_guid in self.state_callbacks:
				
				ec = gremlin.execution_graph.ExecutionContext() # current execution context
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
		''' gets the list of matching functors to call when an event occurs '''	
		functors_list = []
		device_guid = event.device_guid
		if device_guid in self.latched_functors:
			modes = gremlin.shared_state.current_profile.getModeHierarchy(self.runtime_mode)
			for mode in modes:
				if mode in self.latched_functors[device_guid].keys():
					key = event.callbackKey
					if key in self.latched_functors[device_guid][mode].keys():
						functors_list = self.latched_functors[device_guid][mode][key]
						if functors_list:
							break
		return functors_list
				




	def _matching_callbacks(self, event):
		"""Returns the list of callbacks to execute in response to
		the provided event.

		:param event the event for which to search the matching
			callbacks
		:return a list of all callbacks registered and valid for the
			given event
		"""

		config =  gremlin.config.Configuration()
		verbose = config.verbose_mode_details # or config.verbose_mode_condition
		mode = self.runtime_mode
		if event.extra_data:
			# look for options
			if 'mode' in event.extra_data:
				mode = event.extra_data['mode']
		

		# Obtain callbacks matching the event
		callback_list = []
		key = event.callbackKey
		device_guid = event.device_guid
		if device_guid in self.callbacks:
			
			if mode in self.callbacks[device_guid]:
				if key in self.callbacks[device_guid][mode]:
					callback_list = self.callbacks[device_guid][mode][key]
					if verbose:
						event = self.callback_key_map[key]
						self.dump_exectree(device_guid, mode, event)

		if verbose:
			syslog.debug(f"CALLBACK: device: {gremlin.shared_state.get_device_name(event.device_guid)} mode: {self.runtime_mode} found: {len(callback_list)}")


		# Filter events when the system is paused
		if callback_list:
			if not self.process_callbacks:
				return [c[0] for c in callback_list if c[1]]
			else:
				return [c[0] for c in callback_list]
		

	def _matching_latched_callbacks(self, event, key):
		from gremlin.ui.keyboard_device import KeyboardDeviceTabWidget
		callback_list = []
		if event.event_type in (InputType.KeyboardLatched, InputType.Keyboard, InputType.Mouse):
			device_guid = KeyboardDeviceTabWidget.device_guid
			if device_guid in self.latched_callbacks:
				import gremlin.execution_graph
				ec = gremlin.execution_graph.ExecutionContext() # current execution context
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
	grid_visible_changed = Signal(bool) # occurs when a grid was updated

	def __init__(self):
		super().__init__()
		self.grid_visible_changed.connect(self._visible_changed)

	@QtCore.Slot(bool)
	def _visible_changed(self, visible: bool):
		''' store setting for next time '''
		config = gremlin.config.Configuration()
		config.button_grid_visible = visible


_vjoy_remap_handler = VjoyRemapEventHandler()


@gremlin.singleton_decorator.SingletonDecorator
class JoystickState():
	''' holds joystick input/output state flags '''
	def __init__(self):
		self._input_ignored_device_list = {} # list of ignored devices (device_guid)
		self._output_ignored_device_list = {} # list of ignored devices (device_guid)
		self._vjoy_output_ignored_list = {} # list of ignored vjoy IDs for output (int)
		self._vjoy_as_input = {} # map of VJOY devices used as input by GremlinEx

	def hook(self):
		el = EventListener()
		el.vjoy_as_input_changed.connect(self._vjoy_as_input_changed) # hook vjoy as input changes
		el.profile_unload.connect(self.reset) # reset data on profile unload before a new profile is loaded
		

	def reset(self):
		''' resets the ignored device list '''
		import gremlin.joystick_handling
		import gremlin.shared_state
		import gremlin.config
		self._input_ignored_device_list.clear()
		self._output_ignored_device_list.clear()
		self._vjoy_output_ignored_list.clear()
		current_profile = gremlin.shared_state.current_profile
		verbose = gremlin.config.Configuration().verbose
		for dev in gremlin.joystick_handling.all_joystick_devices():
			device_guid = gremlin.util.normalize_guid(dev.device_guid)
			# Octavi IFR1 exception - this is ignored because the device also reports in as a game controller - however we read data from it using HID directly, not dinput
			#Vendor: 0x1240 Product: 0x59094
			if dev.product_id == 59094 and dev.vendor_id == 1240 and dev.name == 'IFR1':
				self.setInputIgnored(dev.device_guid, True)
				self.setOutputIgnored(device_guid, True)
			elif dev.is_virtual:
				is_input = current_profile.settings.vjoy_as_input.get(dev.vjoy_id, False)
				is_output = not is_input
				self.setInputIgnored(device_guid, is_output)
				self.setOutputIgnored(device_guid, is_input)
				self.setVjoyAsInput(dev.vjoy_id, is_input)

				if verbose: syslog.info(f"VJOY: {dev.name} [{dev.vjoy_id}] used as {'input' if is_input else 'output'}")
			else:
				self.setInputIgnored(device_guid, False)
				self.setOutputIgnored(device_guid, True)

	def setVjoyAsInput(self, vid : int, enabled : bool):
		self._vjoy_as_input[vid] = enabled


	def vjoyAsInput(self, vid: int) -> bool:
		''' true if vjoy device is also used as input '''
		if vid in self._vjoy_as_input:
			return self._vjoy_as_input[vid]
		return False
		


	def inputEnabled(self, device_guid) -> bool:
		''' true if device input is enabled '''
		return not self.inputIgnored(device_guid)

	def inputIgnored(self, device_guid) -> bool:
		''' true if the device input should be ignored '''
		id = gremlin.util.normalize_guid(device_guid) if not isinstance(device_guid, str) else device_guid
		if id in self._input_ignored_device_list:
			return self._input_ignored_device_list[id]
		return True # ignore input by default

	def vjoyOutputIgnored(self, vid : int) -> bool:
		''' true if VJOY output is ignored '''
		if vid in self._vjoy_output_ignored_list:
			return self._vjoy_output_ignored_list[vid]
		return False
	



	def outputIgnored(self, device_guid) -> bool:
		''' true if the device output should be ignored '''
		if not isinstance(device_guid, str):
			device_guid = gremlin.util.normalize_guid(device_guid)
		if device_guid in self._output_ignored_device_list:
			return self._output_ignored_device_list[device_guid]
		return False

	def setInputIgnored(self, device_guid, enabled : bool):
		''' marks a device as input ingnored '''
		import gremlin.config
		verbose = gremlin.config.Configuration().verbose_mode_vjoy
		if not isinstance(device_guid, str):
			device_guid = gremlin.util.normalize_guid(device_guid)
		if verbose:
			device = gremlin.joystick_handling.device_info_from_guid(device_guid)	
			syslog.info(f"VJOY: {device.name} input: {'off' if enabled else 'on'}")
		self._input_ignored_device_list[device_guid] = enabled
		if verbose: syslog.info("VJOY ")

	def setOutputIgnored(self, device_guid, enabled : bool):
		''' marks a device as output ignored '''
		import gremlin.joystick_handling
		import gremlin.config
		verbose = gremlin.config.Configuration().verbose_mode_vjoy
		if not isinstance(device_guid, str):
			device_guid = gremlin.util.normalize_guid(device_guid)
		self._output_ignored_device_list[device_guid] = enabled
		device = gremlin.joystick_handling.device_info_from_guid(device_guid)
		if verbose:
			syslog.info(f"VJOY: {device.name} output: {'off' if enabled else 'on'}")
		if device.is_virtual:
			self._vjoy_output_ignored_list[device.vjoy_id] = enabled
		

	def _vjoy_as_input_changed(self, vjoy_id : int, enabled : bool):
		dev = gremlin.joystick_handling.vjoy_info_from_vjoy_id(vjoy_id)
		if dev:
			# vjoy input is enabled, disable output to it
			device_guid = gremlin.util.normalize_guid(dev.device_guid)
			self.setOutputIgnored(device_guid, enabled) # vjoy used as input cannot be used as output
			self.setInputIgnored(device_guid, not enabled)
			self.setVjoyAsInput(vjoy_id, enabled)

class AxisValues(NamedTuple):
	#("AxisValue", "actual raw calibrated curved")
	actual : float
	raw : Optional[float] = None
	calibrated: Optional[float] = None
	curved: Optional[float] = None
	merged: Optional[list] = None # list of all merge components

	def toList(self, strip = True) -> list:
		''' converts to a list - if strip is enabled - returns the sparse value without NULL entries '''
		if strip:
			has_calibration = self.calibrated is not None
			has_curve = self.curved is not None
			if has_calibration and has_curve:
				return [self.raw, self.actual, self.calibrated, self. curved]  # 4 bars = raw, computed, calibrated only, curve only, raw is top channel
			if has_calibration or has_curve:
				return [self.raw, self.actual] # 2 bars (actual is calibrated or curved, second bar is raw input) - raw is top channel
			
			if self.merged:
				return [self.actual, self.merged] # merged data
			
			return [self.actual] # 1 bar no transforms
		
		return [self.raw, self.actual, self.calibrated, self.curved, self.merged] # all channels
	
class AxisData():
	''' holds axis data '''
	def __init__(self, device_guid, input_id):
		if not isinstance(device_guid, str):
			self.device_id = gremlin.util.normalize_guid(device_guid)
			self.device_guid = device_guid
		else:
			self.device_id = gremlin.util.normalize_guid(device_guid)
			self.device_guid = gremlin.util.parse_guid(device_guid)

		self.input_id = input_id
		self.actual_value = None # computed value from last query
		self.raw_value = None
		self.calibrated_value = None
		self.curve_value = None

	@property
	def device(self) -> dinput.DeviceSummary:
		import gremlin.joystick_handling
		return gremlin.joystick_handling.device_info_from_guid(self.device_guid)


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
		''' returns the calibration data for this axis if it has any '''
		import gremlin.ui.axis_calibration
		calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(self.device_guid, self.input_id)
		if calibration and calibration.hasData:
			return calibration
		return None

	
	def getAxisValues(self, value : float = None, action = None) -> AxisValues:
		''' gets the axis value as an AxisValues named tuple
		 
		:param value: optional - input value if known
		:param action: optiona - action requesting the value in case multiple curves are to be applied 
		  
		    '''
		import gremlin.ui.axis_calibration
		
		device_guid = self.device_guid
		input_id = self.input_id

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
			calibrated_value = calibration.getValue(raw_value, False) # do not normalize, input is already -1 to +1
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
			self.raw_value = None # remove the raw value unless we also have a calibrated or curve value - the repeater only displays one value that way

		

		if has_curve and has_calibration:
			data = AxisValues(
				actual = self.actual_value,
				raw = raw_value,
				calibrated = self.calibrated_value,
				curved = self.curve_value
			)		
			return data
			
		if has_calibration:
			data = AxisValues(
				actual = self.actual_value,
				raw = raw_value,
				calibrated = self.calibrated_value
			)
			return data
		if has_curve:
			data = AxisValues(
				actual = self.actual_value,
				raw = raw_value,
				curved = self.curve_value
			)
			return data
			
		# no curve, no calibration
		data = AxisValues(actual = self.actual_value)
		return data





@gremlin.singleton_decorator.SingletonDecorator
class AxisState():
	def __init__(self):
		self._data = {}

		# map of axis input items that could be curved
		self._joystick_input_item_map = {}
		self._last_axis_values = {} # last value
		self._last_axis_time = {} # time when last modified
		self._delay = 0 # delay in seconds for filter - 0 = disabled
		self._registered_devices = [] # guid of registered devices

		el = EventListener()
		el.profile_unload.connect(self.reset)
		el.profile_loaded.connect(self._update_inputs)


	def reset(self):
		''' resets the state data '''
		verbose = gremlin.config.Configuration().verbose_mode_joystick
		if verbose: 	
			syslog.info("AXIS STATE: reset")
		self._data.clear()
		self._registered_devices.clear()
		self._joystick_input_item_map.clear()
		profile = gremlin.shared_state.current_profile
		if profile:
			self._update_inputs()

	def _update_inputs(self):
		''' reload all axes on profile load '''
		# profile = gremlin.shared_state.current_profile
		# for device_guid in profile.devices:
		# 	for mode_name in profile.devices[device_guid].modes:
		# 		mode_object = profile.devices[device_guid].modes[mode_name]
		# 		for input_type in mode_object.config:
		# 			for input_item in mode_object.config[input_type].values():
		# 				self.registerAxisInputItem(input_item)
		import gremlin.joystick_handling
		for device in gremlin.joystick_handling.getDevices():
			if device.connected:
				self.registerDevice(device)
		config = gremlin.config.Configuration()
		verbose = config.verbose_mode_inputs or config.verbose_mode_joystick
		if verbose:
			syslog.info("Axis input list:")
			for (device_guid, input_id) in self._data:
				name = gremlin.joystick_handling.device_name_from_guid(device_guid)
				syslog.info(f"\t{name} axis [{input_id}]")



	def registerDevice(self, device : dinput.DeviceSummary):
		''' registers axes for a given device '''
		if device.axis_count:
			device_guid = device.device_guid
			device_id = gremlin.util.normalize_guid(device_guid)
			if not device_id in self._registered_devices:
				self._registered_devices.append(device_id)

			for index in range(device.axis_count):
				input_id = device.getAxisInputId(index)
				if input_id is None:
					continue # not valid
				key = self._get_key(device_guid, input_id)
				if not key in self._data:
					self._data[key] = AxisData(device_guid, input_id)

	def registerDeviceGuid(self, device_guid):
		import gremlin.joystick_handling
		device = gremlin.joystick_handling.device_info_from_guid(device_guid)
		config = gremlin.config.Configuration()
		verbose = config.verbose_mode_inputs or config.verbose_mode_joystick
		if verbose:
			syslog.info(f"AXIS STATE: register device: {device.name}")
		if device:
			self.registerDevice(device)
		else:
			syslog.warning(f"AXIS STATE: registerDeviceGUID: failed to find device for ID: [{device_guid}]")

	def isRegistered(self, device_guid) -> bool:
		''' true if the device is registered'''
		device_id = gremlin.util.normalize_guid(device_guid)
		return device_id in self._registered_devices
	

	
	def registerAxisInputItem(self, item):
		''' registers an axis input item '''
		if item.get_input_type() == InputType.JoystickAxis:
			verbose = gremlin.config.Configuration().verbose_mode_joystick
			device_guid = item.device_guid
			if not isinstance(device_guid, str):
				device_guid = gremlin.util.normalize_guid(device_guid)
			input_id = item.input_id
			key = self._get_key(device_guid, input_id)
			if not key in self._joystick_input_item_map:
				self._joystick_input_item_map[key] = item
		
			if not key in self._data:
				self._data[key] = AxisData(device_guid, input_id)

			if verbose: 	
				device = gremlin.joystick_handling.getDevice(device_guid)
				syslog.info(f"Register axis: {device.name} {device_guid} axis: {input_id}  {device.getAxisName(input_id)}")

	def queueAxisEvent(self, device_guid, input_id):
		''' queues a joystick update event to trigger UI updates for example '''
		values = self.getAxisValues(device_guid, input_id)
		if values:
			device_guid = gremlin.util.parse_guid(device_guid)
			event = Event(InputType.JoystickAxis, input_id, device_guid, is_axis = True, value = values.actual, extra_data={"queuedEvent" : True})
			el = EventListener()
			el.custom_joystick_event.emit(event)
			

	def _get_key(self, device_guid, input_id):
		if not isinstance(device_guid, str):
			device_guid = gremlin.util.normalize_guid(device_guid)
		return (device_guid, input_id)
	
	def getAxis(self, device_guid, input_id):
		''' gets the axis data block '''
		if device_guid:
			return self.register(device_guid, input_id)
		return None
	
	def getItem(self, device_guid, input_id):
		''' gets registered axis input item '''
		if device_guid:
			key = self._get_key(device_guid, input_id)
			if key in self._joystick_input_item_map:
				item = self._joystick_input_item_map[key]
				return item
		return None
	
	def getAxisData(self, device_guid, input_id):
		if device_guid:
			device_guid = gremlin.util.normalize_guid(device_guid)
			key = self._get_key(device_guid, input_id)
			if key in self._data:
				return self._data[key]
		return None
	

	def getAxisValues(self, device_guid, input_id, value : float = None) -> list:
		''' gets an axis input values, including actual, raw, calibrated and curved as a list of floating point values
			a value of None indicates the item is not used.
			the frist value is the computed value based on applied calibration

			if the value is not provided, the axis is queried for the current value
				
		'''
		if device_guid:
			data= self.getAxisData(device_guid, input_id)
			if data:
				return data.getAxisValues(value)
		return None
	
	def getRawAxisValue(self, device_guid, input_id):
		''' gets the raw axis input '''
		import gremlin.joystick_handling
		return gremlin.joystick_handling.get_axis(device_guid, input_id)
	
	def getAxisCurve(self, device_guid, input_id):
		''' returns the curve data if the axis has a curve applied '''
		if device_guid:
			item = self.getItem(device_guid, input_id)
			if item:
				return item.curve_data 
		return None
	
	def getAxisCalibration(self, device_guid, input_id):
		''' gets the axis calibration data '''
		if device_guid:
			item = self.getItem(device_guid, input_id)
			if item:
				return item.calibration
		return None

	
	def applyCalibration(self, device_guid, input_id, value : float, return_null : bool = True):
		''' applies an axis calibration to an input value '''
		if device_guid:
			item = self.getItem(device_guid, input_id)
			if item and item.calibration:
				calibrated_value = item.calibration.getValue(value)
				return calibrated_value
			if return_null:
				return None
		return value
	
	def applyCurve(self, device_guid, input_id, value : float, return_null : bool = True):
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

	
	def shouldProcess(self, event : Event, process_key = None):
		''' true if event should be filtered for an axis event 
		
		this is an anti-spam mechanism for noisy inputs
		
		'''
		if event.is_axis:
			key = event.callbackKey # unique key for this event, device, and input
			if process_key is not None:
				key = (key, process_key) # hook to that key only 

			current_value = event.value
			now = time.time()
			if key in self._last_axis_values:
				last_value = self._last_axis_values[key]
				last_modified = self._last_axis_time[key]
				if self._delay > 0 and (last_modified + self._delay) >= now:
					# fail: too soon
					return False
				if math.isclose(last_value, current_value, abs_tol = 0.001):
					# fail: same value as before
					self._last_axis_time[key]  = now
					return False
				
			self._last_axis_values[key] = current_value
			self._last_axis_time[key]  = now
		return True

