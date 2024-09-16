# -*- coding: utf-8; -*-

# Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
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

import functools
import inspect
import logging
import time
import queue
from threading import Thread, Timer



import gremlin.joystick_handling
import gremlin.threading

from PySide6 import QtCore, QtWidgets

import dinput
import gremlin.config
from gremlin.input_types import InputType
import gremlin.shared_state


import gremlin.util
from . import config, joystick_handling, windows_event_hook

import gremlin.keyboard
import gremlin.ui
import gremlin.singleton_decorator


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
			value=None,
			virtual_code = 0,
			is_pressed=False,
			raw_value=None,
			force_remote = False,
			action_id = None,
			data = None,
			is_axis = False, # true if the input should be considered an axis (variable) input
			is_virtual = False, # true if the input is a virtual input (vjoy)
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
		self.event_type = event_type
		self.identifier = identifier
		self.device_guid = device_guid
		self.is_pressed = is_pressed
		self.value = value
		self.raw_value = raw_value
		self.force_remote = force_remote
		self.action_id = action_id # the current action id to load
		self.data = data # extra data passed along with the event
		self.is_axis = is_axis
		self.virtual_code = virtual_code # vk if a keyboard event (the identifier will be the key_id (scancode, extended))
		self.is_virtual = is_virtual # true if the item is a vjoy device input

	def clone(self):
		"""Returns a clone of the event.

		:return cloned copy of this event
		"""
		import copy
		return copy.deepcopy(self)


	def __eq__(self, other):
		return self.__hash__() == other.__hash__()

	def __ne__(self, other):
		return not (self == other)

	def __hash__(self):
		"""Computes the hash value of this event.

		The hash is comprised of the events type, identifier of the
		event source and the id of the event device. Events from the same
		input, e.g. axis, button, hat, key, with different values / states
		shall have the same hash.

		:return integer hash value of this event
		"""
		if self.event_type == InputType.Keyboard:
			data = (self.identifier.scan_code, self.identifier.is_extended) if isinstance(self.identifier, gremlin.keyboard.Key) else self.identifier
			return hash((
				self.device_guid,
				self.event_type.value,
				data,
				1 if data[1] else 0
			))
		else:
			return hash((
				self.device_guid,
				self.event_type.value,
				self.identifier,
				0
			))

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
	
	def __str__(self):
		if self.event_type == InputType.Mouse:
			return f"Event: Mouse - button {self.identifier} pressed: {self.is_pressed}"
		elif self.event_type == InputType.Keyboard:
			return f"Event: Keyboard - scan code, extended : {self.identifier}  vk: {self.virtual_code} (0x{self.virtual_code:X}) pressed: {self.is_pressed}"
		elif self.event_type == InputType.JoystickAxis or self.is_axis:
			return f"Event: Axis : {self.identifier} raw value: {self.raw_value} value: {self.value}"
		elif self.event_type == InputType.JoystickButton:
			return f"Event: Axis : {self.identifier} pressed: {self.is_pressed}"
		return f"Event: {self.event_type} identifier {self.identifier}"

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

class StateChangeEvent:
	''' sent when the state changes '''
	def __init__(self, is_local = False, is_remote = False, is_broadcast_enabled = False):
		self.is_local = is_local
		self.is_remote = is_remote
		self.is_broadcast_enabled = is_broadcast_enabled





@gremlin.singleton_decorator.SingletonDecorator
class EventListener(QtCore.QObject):

	"""Listens for keyboard and joystick events and publishes them
	via QT's signal/slot interface.
	"""

	# Signal emitted when joystick events are received
	joystick_event = QtCore.Signal(Event)
	# Signal emitted when keyboard events are received
	keyboard_event = QtCore.Signal(Event)
	# Signal emitted when mouse events are received
	mouse_event = QtCore.Signal(Event)
	# Signal emitted when virtual button events are received
	virtual_event = QtCore.Signal(Event)

	# signal emmitted when a MIDI input is received
	midi_event = QtCore.Signal(Event)

	# signal emitted when an OSC input is received
	osc_event = QtCore.Signal(Event)

	# Signal emitted when a joystick is attached or removed
	device_change_event = QtCore.Signal()

	# fires when the number of gamepad devices changes
	gamepad_change_event = QtCore.Signal()

	# called when a process device change should be handled
	_process_device_change = QtCore.Signal()
	
	# Signal emitted when the icon needs to be refreshed
	icon_changed = QtCore.Signal(DeviceChangeEvent)

	# Signal emitted when a profile is changed (to refresh UI)
	profile_changed = QtCore.Signal()
	
	# signal emitted when the selected hardware device changes
	profile_device_changed = QtCore.Signal(DeviceChangeEvent)

	# signal emitted when the selected hardware device changes
	profile_device_mapping_changed = QtCore.Signal(DeviceChangeEvent)

	# signal emitted when the UI tabs are loaded and profiles are loaded - some widgets use this for post-UI initialization update that needs to occur after the UI data is completely loaded
	tabs_loaded = QtCore.Signal()

	profile_reset = QtCore.Signal() # issues the reset signal (when runtime for a profile needs to reset)
	profile_start = QtCore.Signal() # issues the start signal (when a profile starts)
	profile_stop = QtCore.Signal() # issues the stop signal (when a profile stops)
	
	# occurs on broadcast configuration change
	config_changed =  QtCore.Signal()

	# occurs on broadcast mode change
	broadcast_changed = QtCore.Signal(StateChangeEvent)

	# occurs on mode edit/update/delete
	modes_changed = QtCore.Signal()

	# functor enable flag changed
	action_created = QtCore.Signal(object) # runs when an action is created - object = the object that triggered the event 



	def __init__(self):
		"""Creates a new instance."""
		QtCore.QObject.__init__(self)
		self.keyboard_hook = windows_event_hook.KeyboardHook()
		self.keyboard_hook.register(self._keyboard_handler)
		
		# if in debug mode - don't hook the mouse
		if not gremlin.config.Configuration().is_debug:
			self.mouse_hook = windows_event_hook.MouseHook()
			self.mouse_hook.register(self._mouse_handler)
		else:
			logging.getLogger("system").warning("************ DEBUG MODE - MOUSE HOOKS ARE DISABLED ")
			self.mouse_hook = None

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

		Thread(target=self._run).start()

	def _device_changed_cb(self):
		self._init_joysticks()

	def mouseEnabled(self):
		''' returns mouse hook status '''
		return self.mouse_hook is not None
	
	def enableMouse(self):
		if self.mouse_hook is None:
			self.mouse_hook = windows_event_hook.MouseHook()
			self.mouse_hook.register(self._mouse_handler)

	def disableMouse(self):
		if self.mouse_hook is not None:
			self.mouse_hook.stop()
			self.mouse_hook = None




	def _process_queue(self):
		''' processes an item the keyboard buffer queue '''
		item, is_pressed = self._keyboard_queue.get()
		verbose = gremlin.config.Configuration().verbose_mode_keyboard
		if verbose:
			logging.getLogger("system").info(f"process_queue: found item: {item} is presseD: {is_pressed}")

		if isinstance(item, int):
			virtual_code = item
			key = gremlin.keyboard.KeyMap.find_virtual(virtual_code)
			self._keyboard_buffer[virtual_code] = is_pressed
			key_id = key.index_tuple()
			
		else:
			
			key_id = item
			scan_code, is_extended = item
			key = gremlin.keyboard.KeyMap.find(scan_code, is_extended)
			virtual_code = key.virtual_code
			self._keyboard_buffer[key_id] = is_pressed
		if verbose:
			logging.getLogger("system").info(f"DEQUEUE KEY {gremlin.keyboard.KeyMap.keyid_tostring(key_id)} vk: {virtual_code} (0x{virtual_code:X}) name: {key.name} pressed: {is_pressed}")
		
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

		logging.getLogger("system").info("KBD: processing start")
		self._keyboard_buffer = {}
		self._key_listener_started = True
		while not self._keyboard_thread.stopped():
			if self._keyboard_queue.empty():
				time.sleep(0.01)
				continue
			self._process_queue()


		# done
		# process any straglers
		while not self._keyboard_queue.empty():
			self._process_queue()
		
		logging.getLogger("system").info("KBD: processing stop")
	

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
		if self.mouse_hook is not None:
			self.mouse_hook.start()
		self._key_listener_stop_requested = False
		self.start_key_listener()


	def stop(self):
		if self.mouse_hook is not None:
			self.mouse_hook.stop()
		self.stop_key_listener()


	def terminate(self):
		"""Stops the loop from running."""
		self._running = False
		self.keyboard_hook.stop()
		if self.mouse_hook:
			self.mouse_hook.stop()

	def reload_calibrations(self):
		"""Reloads the calibration data from the configuration file."""
		from gremlin.ui.ui_util import create_calibration_function
		cfg = config.Configuration()
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
		logging.getLogger("system").info("DILL: input start listen")
		dinput.DILL.set_device_change_callback(self._joystick_device_handler)
		dinput.DILL.set_input_event_callback(self._joystick_event_handler)
		while self._running:
			# Keep this thread alive until we are done
			time.sleep(0.1)
		logging.getLogger("system").info("DILL: input stop listen")

	def _joystick_event_handler(self, data):
		"""Callback for joystick events.

		The handler converts the event data into a signal which is then
		emitted.

		:param data the joystick event
		"""

		from gremlin.util import dill_hat_lookup
		verbose = config.Configuration().verbose_mode_joystick
		
		event = dinput.InputEvent(data)
		
		#breakpoint()
		device = gremlin.joystick_handling.device_info_from_guid(event.device_guid)
		
		is_virtual = device.is_virtual if device is not None else False
		if event.input_type == dinput.InputType.Axis:
			if verbose:
				logging.getLogger("system").info(event)
			
			
			self.joystick_event.emit(Event(
				event_type= InputType.JoystickAxis,
				device_guid=event.device_guid,
				identifier=event.input_index,
				value=self._apply_calibration(event),
				raw_value=event.value,
				is_axis = True,
				is_virtual = is_virtual
			))
		elif event.input_type == dinput.InputType.Button:
			self.joystick_event.emit(Event(
				event_type= InputType.JoystickButton,
				device_guid=event.device_guid,
				identifier=event.input_index,
				is_pressed=event.value == 1,
				is_virtual = is_virtual
			))
		elif event.input_type == dinput.InputType.Hat:
			self.joystick_event.emit(Event(
				event_type= InputType.JoystickHat,
				device_guid=event.device_guid,
				identifier=event.input_index,
				value = dill_hat_lookup[event.value],
				is_virtual = is_virtual
			))

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

		try:
			syslog = logging.getLogger("system")
			
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
			joystick_handling.reset_devices()

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
		# print (f"recorded key: {key_id} vk: {virtual_code} (0x{virtual_code:X})")

		# deal with any code translations needed
		key_id, virtual_code = gremlin.keyboard.KeyMap.translate(key_id) # modify scan codes if needed
		# print (f"translated key: {KeyMap.keyid_tostring(key_id)}  vk: {virtual_code} (0x{virtual_code:X})")

		is_pressed = event.is_pressed
		# if virtual_code > 0:
		# 	is_repeat = self._keyboard_state.get(virtual_code) and is_pressed
		# else:
		is_repeat = self._keyboard_state.get(key_id) and is_pressed

		if is_repeat:
			# ignore repeats
			return True

		# if virtual_code > 0:
		# 	self._keyboard_state[virtual_code] = is_pressed
		
		self._keyboard_state[key_id] = is_pressed
		# print (f"set state: {key_id} state: {is_pressed}")
		
		if gremlin.shared_state.is_running:
			# RUN mode - queue input events
			if not self._key_listener_started:
				return True
			
			# Only process the key if it's pressed the first time
			# released but not when it's being held down
			#if virtual_code > 0:
			# 	self._keyboard_queue.put((virtual_code, is_pressed))
			# else:
			self._keyboard_queue.put((key_id, is_pressed))
			
			# add to the processing queue
			if verbose:
				# key = gremlin.keyboard.KeyMap.find_virtual(virtual_code) if virtual_code > 0 else gremlin.keyboard.KeyMap.find(key_id[0],key_id[1])
				logging.getLogger("system").info(f"QUEUE KEY {gremlin.keyboard.KeyMap.keyid_tostring(key_id)} vk 0x{virtual_code:X} pressed {is_pressed}")

		else:
			# DESIGN mode - straight
			# print (f"FIRE KEY {key_id} {key.name} pressed {is_pressed}")
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

			# update keyboard state for that key
			key_id = (event.button_id.value + 0x1000, False)
			self._keyboard_state[key_id] = event.is_pressed

			if event.is_pressed:
				print(f"mouse pressed {event.button_id}")

			self.mouse_event.emit(Event(
				event_type= InputType.Mouse,
				device_guid=dinput.GUID_Keyboard,
				identifier=event.button_id,
				is_pressed=event.is_pressed,
				data = self._keyboard_state
			))
			# print (f"Mouse button state: {key_id}  {event.is_pressed}")
		# Allow the windows event to propagate further
		return True

	def _apply_calibration(self, event):
		from gremlin.util import axis_calibration
		key = (event.device_guid, event.input_index)
		if key in self._calibrations:
			return self._calibrations[key](event.value)
		else:
			return axis_calibration(event.value, -32768, 0, 32767)

	def _init_joysticks(self):
		"""Initializes joystick devices."""
		for dev_info in joystick_handling.joystick_devices():
			self._load_calibrations(dev_info)

	def _load_calibrations(self, device_info):
		"""Loads the calibration data for the given joystick.

		:param device_info information about the device
		"""
		from gremlin.util import create_calibration_function
		cfg = config.Configuration()
		for entry in device_info.axis_map:
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


@gremlin.singleton_decorator.SingletonDecorator
class EventHandler(QtCore.QObject):

	"""Listens to the inputs from multiple different input devices."""

	
	mode_changed = QtCore.Signal(str) # Signal emitted when the mode is changed at design time
	runtime_mode_changed = QtCore.Signal(str)  # mode change specific to runtime
	mode_status_update = QtCore.Signal() # tell the UI to update the mode status bar

	# signal emitted when the profile is changed
	profile_changed = QtCore.Signal(str)

	# Signal emitted when the application is pause / resumed
	is_active = QtCore.Signal(bool)

	last_action_changed = QtCore.Signal(object, str) # fires when the action changes in the selector (drop_down, name)
	last_container_changed = QtCore.Signal(object, str) # fires when the action changes in the selector (drop_down, name)

	

	def __init__(self):
		"""Initializes the EventHandler instance."""
		QtCore.QObject.__init__(self)
		self.plugins = {}
		self.reset()

	def reset(self):
		self.process_callbacks = True
		self.callbacks = {}
		self.latched_events = {}
		self.latched_callbacks = {}
		self.midi_callbacks = {}
		self.osc_callbacks = {}
		self._event_lookup = {}
		

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
		from types import FunctionType, MethodType

		verbose = gremlin.config.Configuration().verbose
		if not verbose:
			return
		
		get_device_name = gremlin.shared_state.get_device_name
		logger = logging.getLogger("system")
		for callbacks in self.callbacks[device_guid][mode][event]:
			for callback in callbacks:
				if not hasattr(callback,"execution_graph"):
					logger.debug(f"\tDevice ID: {device_guid} ({get_device_name(device_guid)}) mode: {mode} event: {event} - skip callback - missing execution graph - don't know how to handle {type(callback)} *********")
					continue
				
				for callback_functor in callback.execution_graph.functors:
					if hasattr(callback_functor,"action_set"):
						for functor in callback_functor.action_set.functors:
							action_data = functor.action_data if hasattr(functor, "action_data") else None
							logger.debug(f"\tDevice ID: {device_guid} ({get_device_name(device_guid)}) mode: {mode} event: {event} hash: {hash(event):X} type: {type(functor)}")
							if action_data:
								# dump member variables only
								logger.debug("\t\tData block:")
								for attr in dir(action_data):
									if not attr.startswith("_"):
										item = getattr(action_data,attr)
										
										if not (isinstance(item, FunctionType) or isinstance(item, MethodType) or inspect.isabstract(item) or inspect.isclass(item)):
											logger.debug(f"\t\t\t{attr}: {item}")
					else:
						logger.debug(f"\tFunctor '{type(callback_functor).__name__} does not define an action set")
					
								




	def dump_callbacks(self):
		# dump latched events
		import gremlin.ui.keyboard_device
		import gremlin.shared_state

		
		get_device_name = gremlin.shared_state.get_device_name
		logger = logging.getLogger("system")
		logger.debug("------------ Latched Events ----------------")
		for device_guid in self.latched_events.keys():
			for mode in self.latched_events[device_guid].keys():
				for key_pair in self.latched_events[device_guid][mode]:
					identifier = self.latched_events[device_guid][mode][key_pair]
					if isinstance(identifier, gremlin.ui.keyboard_device.KeyboardInputItem):
						if isinstance(key_pair, tuple):
							scan_code, is_extended = key_pair
							key_data = f"scan code: 0x{scan_code:X}  extended: {is_extended}"
						else:
							key_data = str(key_pair)
						logger.debug(f"\tDevice ID: {device_guid} ({get_device_name(device_guid)}) mode: {mode} pair: {key_data} data: {identifier.to_string()}")

		logger.debug("------------ Execution callbacks ----------------")
		for device_guid in self.callbacks.keys():
			for mode in self.callbacks[device_guid].keys():
				for event in self.callbacks[device_guid][mode]:
					self.dump_exectree(device_guid, mode, event)

				

	def add_callback(self, device_guid, mode, event, callback, permanent=False):
		"""Installs the provided callback for the given event.

		:param device_guid the GUID of the device the callback is
			associated with
		:param mode the mode the callback belongs to
		:param event the event for which to install the callback
		:param callback the callback function to link to the provided
			event
		:param permanent if True the callback is always active even
			if the system is paused
		"""
		import gremlin.config
		import gremlin.ui.keyboard_device
		import gremlin.keyboard
		
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
						logging.getLogger("system").info(f"Key latch registered by guid {device_guid}  mode: {mode} vk: {virtual_code} (0x{virtual_code:X}) source keyid: {gremlin.keyboard.KeyMap.keyid_tostring(keyid_source)} -> translated keyId: {gremlin.keyboard.KeyMap.keyid_tostring(keyid)} name: {key.name} -> {identifier.display_name}")
					

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
				verbose = gremlin.config.Configuration().verbose
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
			else:
				# regular event
				if device_guid not in self.callbacks:
					self.callbacks[device_guid] = {}
				if mode not in self.callbacks[device_guid]:
					self.callbacks[device_guid][mode] = {}
				if event not in self.callbacks[device_guid][mode]:
					self.callbacks[device_guid][mode][event] = []
				self.callbacks[device_guid][mode][event].append((
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
				logging.getLogger("system").info(f"matching mouse event {event.identifier} to {gremlin.keyboard.KeyMap.keyid_tostring(index)}")
		else:
			verbose = gremlin.config.Configuration().verbose_mode_keyboard
			device_guid = event.device_guid
			# index = event.virtual_code if event.virtual_code > 0 else event.identifier  # this is (scan_code, is_extended)
			index, _ = gremlin.keyboard.KeyMap.translate(event.identifier)
			verbose = gremlin.config.Configuration().verbose_mode_keyboard
			if verbose:
				logging.getLogger("system").info(f"matching key event {event.identifier} to {gremlin.keyboard.KeyMap.keyid_tostring(index)}")

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
		
		for parent, children in inheritance_tree.items():
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
								if event not in device_cb[child]:
									device_cb[child][event] = callbacks

			# Recurse until we've dealt with all modes
			self.build_event_lookup(children)

	def change_profile(self, new_profile):
		''' requests a profile load '''
		if new_profile != gremlin.shared_state.current_profile:
			self.profile_change.emit(new_profile)


	def set_mode(self, new_mode):
		''' sets the edit or runtime mode based on the state  '''
		if gremlin.shared_state.is_running:
			gremlin.shared_state.runtime_mode = new_mode
		else:
			gremlin.shared_state.edit_mode = new_mode

	def set_runtime_mode(self, new_mode):
		''' sets the active runtime mode '''
		gremlin.shared_state.runtime_mode = new_mode

	def set_edit_mode(self, new_mode):
		''' sets the active edit mode '''
		gremlin.shared_state.edit_mode = new_mode


	def change_mode(self, new_mode, emit = True, force_update = False):
		"""Changes the GremlinEx currently active mode.

		:param new_mode the new mode to use
		"""

		verbose = gremlin.config.Configuration().verbose
		current_profile = gremlin.shared_state.current_profile
		

		if verbose:
			logging.getLogger("system").debug(f"EVENT: change mode to [{new_mode}] requested - active mode: [{gremlin.shared_state.runtime_mode}]  current mode: [{gremlin.shared_state.current_mode}] profile '{current_profile.name}'")


		if new_mode == self.current_mode and not force_update:
			# already in this mode
			return
		
		mode_exists = new_mode in current_profile.get_modes()

		
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
			logging.getLogger("system").warning(
				f"The mode \"{new_mode}\" does not exist or has no associated callbacks - profile '{current_profile.name}'"
			)
			return

		if gremlin.shared_state.is_running:
			# runtime event (prevents UI from reloading)
			if self.runtime_mode != new_mode or force_update:
				self.previous_runtime_mode = self.runtime_mode
				gremlin.shared_state.runtime_mode = new_mode
				# remember the last mode for this profile
				current_profile.set_last_runtime_mode(self.runtime_mode)
				self.previous_runtime_mode = self.runtime_mode
				self.runtime_mode = new_mode
				logging.getLogger("system").debug(f"Profile: {current_profile.name} - Runtime Mode switch to: {new_mode}")
				if emit:
					self.runtime_mode_changed.emit(self.runtime_mode)
		else:
			# non-runtime

			if self.edit_mode != new_mode or force_update:
				gremlin.config.Configuration().set_profile_last_edit_mode(new_mode)
				gremlin.shared_state.edit_mode = new_mode
				self.edit_mode = new_mode
				logging.getLogger("system").debug(f"Profile: {current_profile.name} - Design time Mode switch to: {new_mode}")
				if emit:
					self.mode_changed.emit(self.edit_mode)

		# update the status bar
		self.mode_status_update.emit()


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
		self.latched_callbacks = {}
		self.midi_callbacks = {}
		self.osc_callbacks = {}

	@QtCore.Slot(Event)
	def process_event(self, event : Event):
		"""Processes a single event by passing it to all callbacks
		registered for this event.

		:param event the event to process
		"""

		
		import gremlin.config
		import gremlin.keyboard

		# list of callbacks
		m_list = []

		
		
		verbose = gremlin.config.Configuration().verbose_mode_inputs
		if verbose and event.event_type != InputType.JoystickAxis:
			logging.getLogger("system").info(f"process event - mode [{self.runtime_mode}] event: {str(event)}")

		# filter latched keyboard or mouse events
		if event.event_type in (InputType.Keyboard, InputType.KeyboardLatched, InputType.Mouse):
			verbose = gremlin.config.Configuration().verbose_mode_keyboard
			data = event.data # holds keyboard state info
			if event.event_type == InputType.Mouse:
				verbose = gremlin.config.Configuration().verbose_mode_mouse
			if verbose:
				logging.getLogger("system").info(f"process keyboard event: {event}")
				logging.getLogger("system").info(f"\tKeyboard state data:")
				for key in data.keys():
					logging.getLogger("system").info(f"\t\t{gremlin.keyboard.KeyMap.keyid_tostring(key)} {data[key]}")

			items = self._matching_event_keys(event)  # returns list of primary keys
			if items:
				if verbose:
					logging.getLogger("system").info(f"Matched keys for mode: [{self.runtime_mode}]  event {event} pressed: {event.is_pressed} keys: {len(items)} ")
					for index, input_item in enumerate(items):
						logging.getLogger("system").info(f"\t[{index}]: {input_item.name}")
				
				
				
				for input_item in items:
					if verbose:
						logging.getLogger("system").info("-"*50)
					is_latched = True
					latch_key = None
					# print (data)
					latched_keys = [input_item.key]
					latched_keys.extend(input_item.latched_keys)
					if verbose:
						logging.getLogger("system").info(f"Checking latching: {len(latched_keys)} key(s)")
					for k in latched_keys:
						index = k.index_tuple()
						found = index in data.keys()
						state = data[index] if found else False
						if verbose:
							logging.getLogger("system").info(f"\tcheck latched key: {gremlin.keyboard.KeyMap.keyid_tostring(index)} {k.name} found: {found} state: {state} {'*****' if state else ''}")
							if not found:
								logging.getLogger("system").info(f"\t\t* Key not found *")
						is_latched = is_latched and state

					if verbose:
						logging.getLogger("system").info(f"\tLatched state: {is_latched}")
					
					if is_latched:
						latch_key = input_item.key

					if latch_key:
						#print (f"Found latched key: {latch_key}")
						m_list = self._matching_latched_callbacks(event, latch_key)
						if m_list:
							if verbose:
								trigger_line = "***** TRIGGER " + "*"*30
								logging.getLogger("system").info(trigger_line)
								logging.getLogger("system").info(f"\tmode: [{self.runtime_mode}] Found latched key: Check key {latch_key.name} callbacks: {len(m_list)} event: {event}")
								logging.getLogger("system").info(trigger_line)
							self._trigger_callbacks(m_list, event)
							return
						# else:
						# 	print (f"No callbacks found for: {latch_key}")

			else:
				if verbose:
					logging.getLogger("system").info("No matching events")
			return
						
		elif event.event_type ==InputType.Midi:
			verbose = gremlin.config.Configuration().verbose_mode_details
			m_list = self._matching_midi_callbacks(event)
		elif event.event_type == InputType.OpenSoundControl:
			verbose = gremlin.config.Configuration().verbose_mode_details
			m_list = self._matching_osc_callbacks(event)
		elif event.event_type in (InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat):
			verbose = gremlin.config.Configuration().verbose_mode_joystick
			m_list = self._matching_callbacks(event)
		else:
			# other inputs
			verbose = gremlin.config.Configuration().verbose_mode_details
			m_list = self._matching_callbacks(event)

		

		
		if m_list:
			if verbose:
				logging.getLogger("system").info(f"TRIGGER: mode: [{self.runtime_mode}] callbacks: {len(m_list)} event: {event}")
			self._trigger_callbacks(m_list, event)


	def _trigger_callbacks(self, callbacks, event):
		#verbose = gremlin.config.Configuration().verbose'
		if event.event_type == InputType.JoystickAxis:
			pass
		for cb in callbacks:
			try:
				# if verbose:
				# 	logging.getLogger("system").info(f"CALLBACK: execute start")
				cb(event)
				# if verbose:
				# 	logging.getLogger("system").info(f"CALLBACK: execute done")
			except Exception as ex:
				logging.getLogger("system").error(f"CALLBACK: error {ex}")


	def _matching_midi_callbacks(self, event):
		''' returns list of callbacks matching the event '''
		callback_list = []
		if event.event_type == InputType.Midi:
			key = event.identifier.message_key
			import gremlin.ui.midi_device
			if event.identifier.command == gremlin.ui.midi_device.MidiCommandType.SysEx:
					pass
			if event.device_guid in self.midi_callbacks:
				callback_list = self.midi_callbacks[event.device_guid].get(
					self.runtime_mode, {}
				).get(key, [])

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
				callback_list = self.osc_callbacks[event.device_guid].get(
					self.runtime_mode, {}
				).get(key, [])

		# Filter events when the system is paused
		if not self.process_callbacks:
			return [c[0] for c in callback_list if c[1]]
		else:
			return [c[0] for c in callback_list]
			

	def _matching_callbacks(self, event):
		"""Returns the list of callbacks to execute in response to
		the provided event.

		:param event the event for which to search the matching
			callbacks
		:return a list of all callbacks registered and valid for the
			given event
		"""

		verbose = gremlin.config.Configuration().verbose_mode_details

		# Obtain callbacks matching the event
		callback_list = []
		device_guid = event.device_guid
		if device_guid in self.callbacks:
			mode = self.runtime_mode
			if mode in self.callbacks[device_guid].keys():
				if event in self.callbacks[device_guid][mode].keys():
					callback_list = self.callbacks[device_guid][mode][event]
					if verbose:
						self.dump_exectree(device_guid, mode, event)

		if verbose:
			logging.getLogger("system").debug(f"device: {gremlin.shared_state.get_device_name(event.device_guid)} mode: {self.runtime_mode} found: {len(callback_list)}")
			if callback_list:
				pass


		# Filter events when the system is paused
		if not self.process_callbacks:
			return [c[0] for c in callback_list if c[1]]
		else:
			return [c[0] for c in callback_list]
		

	def _matching_latched_callbacks(self, event, key):
		callback_list = []
		if event.device_guid in self.latched_callbacks:
			callback_list = self.latched_callbacks[event.device_guid].get(
				self.runtime_mode, {}
			).get(key, [])

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
