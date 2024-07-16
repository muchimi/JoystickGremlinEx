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
import gremlin.code_runner
import gremlin.keyboard
import gremlin.threading

from PySide6 import QtCore, QtWidgets

import dinput
import gremlin.config
from gremlin.input_types import InputType
import gremlin.shared_state
import gremlin.shared_state
from gremlin.singleton_decorator import SingletonDecorator
import gremlin.ui
import gremlin.util
from . import config, error, joystick_handling, windows_event_hook

from gremlin.keyboard import Key, KeyMap



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
			is_pressed=None,
			raw_value=None,
			force_remote = False,
			action_id = None,
			data = None,
			is_axis = False # true if the input should be considered an axis (variable) input
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
			data = (self.identifier.scan_code, self.identifier.is_extended) if isinstance(self.identifier, Key) else self.identifier
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





@SingletonDecorator
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
	
	# Signal emitted when the icon needs to be refreshed
	icon_changed = QtCore.Signal(DeviceChangeEvent)

	# Signal emitted when a profile is changed (to refresh UI)
	profile_changed = QtCore.Signal()
	
	# signal emitted when the selected hardware device changes
	profile_device_changed = QtCore.Signal(DeviceChangeEvent)

	# signal emitted when the selected hardware device changes
	profile_device_mapping_changed = QtCore.Signal(DeviceChangeEvent)

	profile_start = QtCore.Signal()
	profile_stop = QtCore.Signal()
	
	# occurs on broadcast configuration change
	config_changed =  QtCore.Signal()

	# occurs on broadcast mode change
	broadcast_changed = QtCore.Signal(StateChangeEvent)

	
		

	def __init__(self):
		"""Creates a new instance."""
		QtCore.QObject.__init__(self)
		self.keyboard_hook = windows_event_hook.KeyboardHook()
		self.keyboard_hook.register(self._keyboard_handler)
		self.mouse_hook = windows_event_hook.MouseHook()
		self.mouse_hook.register(self._mouse_handler)

		# Calibration function for each axis of all devices
		self._calibrations = {}

		
		# Joystick device change update timeout timer
		self._device_update_timer = None
		
		self._running = True

		# keyboard input handling buffer	
		self._keyboard_state = {}
		self._keyboard_queue = None
		self._key_listener_started = False # true if the key listener is started
		self.gremlin_active = False
		self._keyboard_thread = None
		self.keyboard_hook.start()

		Thread(target=self._run).start()



	def _process_queue(self):
		''' processes an item the keyboard buffer queue '''
		item, is_pressed = self._keyboard_queue.get()
		verbose = gremlin.config.Configuration().verbose_mode_keyboard
		print (f"process_queue: found item: {item} is presseD: {is_pressed}")

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
			logging.getLogger("system").info(f"DEQUEUE KEY {KeyMap.keyid_tostring(key_id)} vk: {virtual_code} (0x{virtual_code:X}) name: {key.name} pressed: {is_pressed}")
		
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
		self.mouse_hook.start()
		self._key_listener_stop_requested = False
		self.start_key_listener()


	def stop(self):
		self.mouse_hook.stop()
		self.stop_key_listener()


	def terminate(self):
		"""Stops the loop from running."""
		self._running = False
		self.keyboard_hook.stop()
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
		dinput.DILL.set_device_change_callback(self._joystick_device_handler)
		dinput.DILL.set_input_event_callback(self._joystick_event_handler)
		while self._running:
			# Keep this thread alive until we are done
			time.sleep(0.1)


	def _joystick_event_handler(self, data):
		"""Callback for joystick events.

		The handler converts the event data into a signal which is then
		emitted.

		:param data the joystick event
		"""

		from gremlin.util import dill_hat_lookup
		verbose = config.Configuration().verbose_mode_joystick
		
		if not self._running:
			return True
		
		event = dinput.InputEvent(data)
		if event.input_type == dinput.InputType.Axis:
			if verbose:
				logging.getLogger("system").info(event)
			self.joystick_event.emit(Event(
				event_type= InputType.JoystickAxis,
				device_guid=event.device_guid,
				identifier=event.input_index,
				value=self._apply_calibration(event),
				raw_value=event.value,
				is_axis = True
			))
		elif event.input_type == dinput.InputType.Button:
			self.joystick_event.emit(Event(
				event_type= InputType.JoystickButton,
				device_guid=event.device_guid,
				identifier=event.input_index,
				is_pressed=event.value == 1
			))
		elif event.input_type == dinput.InputType.Hat:
			self.joystick_event.emit(Event(
				event_type= InputType.JoystickHat,
				device_guid=event.device_guid,
				identifier=event.input_index,
				value = dill_hat_lookup[event.value]
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
		if self._device_update_timer is not None:
			self._device_update_timer.cancel()
		self._device_update_timer = Timer(0.2, self._run_device_list_update)
		self._device_update_timer.start()

	def _run_device_list_update(self):
		"""Performs the update of the devices connected."""
		joystick_handling.joystick_devices_initialization()
		self._init_joysticks()
		self.device_change_event.emit()

		
		


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
		print (f"recorded key: {key_id} vk: {virtual_code} (0x{virtual_code:X})")

		# deal with any code translations needed
		key_id, virtual_code = KeyMap.translate(key_id) # modify scan codes if needed 
		print (f"translated key: {KeyMap.keyid_tostring(key_id)}  vk: {virtual_code} (0x{virtual_code:X})")

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
				logging.getLogger("system").info(f"QUEUE KEY {KeyMap.keyid_tostring(key_id)} vk 0x{virtual_code:X} pressed {is_pressed}")

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
	
	def get_key_state(self, key: Key):
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


@SingletonDecorator
class EventHandler(QtCore.QObject):

	"""Listens to the inputs from multiple different input devices."""

	# Signal emitted when the mode is changed
	mode_changed = QtCore.Signal(str)

	# signal emitted when the profile is changed
	profile_changed = QtCore.Signal(str)

	# Signal emitted when the application is pause / resumed
	is_active = QtCore.Signal(bool)

	def __init__(self):
		"""Initializes the EventHandler instance."""
		QtCore.QObject.__init__(self)
		self.process_callbacks = True
		self.plugins = {}
		self.callbacks = {}
		self.latched_events = {}
		self.latched_callbacks = {}
		self.midi_callbacks = {}
		self.osc_callbacks = {}
		self._event_lookup = {}
		self._active_mode = None
		self._previous_mode = None

	@property
	def active_mode(self):
		"""Returns the currently active mode.

		:return name of the currently active mode
		"""
		return self._active_mode

	@property
	def previous_mode(self):
		"""Returns the previously active mode.

		:return name of the previously active mode
		"""
		return self._previous_mode

	def add_plugin(self, plugin):
		"""Adds a new plugin to be attached to event callbacks.

		:param plugin the plugin to add
		"""
		# Do not add the same type of plugin multiple times
		if plugin.keyword not in self.plugins:
			self.plugins[plugin.keyword] = plugin

	def dump_callbacks(self):
		# dump latched events
		import gremlin.ui.keyboard_device
		for device_guid in self.latched_events.keys():
			for mode in self.latched_events[device_guid].keys():
				for key_pair in self.latched_events[device_guid][mode]:
					identifier = self.latched_events[device_guid][mode][key_pair]
					if isinstance(identifier, gremlin.ui.keyboard_device.KeyboardInputItem):
						logging.getLogger("system").debug(f"Device ID: {device_guid} mode: {mode} pair: {key_pair} data: {identifier.to_string()}")



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
		import win32con
		
		if event:
			if event.event_type in (InputType.Keyboard, InputType.KeyboardLatched):
				verbose = gremlin.config.Configuration().verbose_mode_keyboard
				# keyboard latched event
				identifier = event.identifier
				primary_key : Key = identifier.key
				



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
					keyid, _ = KeyMap.translate(keyid_source)
						
					if device_guid not in self.latched_events.keys():
						self.latched_events[device_guid] = {}
				
					if mode not in self.latched_events[device_guid].keys():
						self.latched_events[device_guid][mode] = {}
					if keyid not in self.latched_events[device_guid][mode].keys():
						self.latched_events[device_guid][mode][keyid] = []
					self.latched_events[device_guid][mode][keyid].append(identifier)
					if verbose:
						logging.getLogger("system").info(f"Key latch registered by guid {device_guid}  mode: {mode} vk: {virtual_code} (0x{virtual_code:X}) source keyid: {KeyMap.keyid_tostring(keyid_source)} -> translated keyId: {KeyMap.keyid_tostring(keyid)} name: {key.name} -> {identifier.display_name}")
					

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

		# convert mouse events to keyboard event
		if event.event_type == InputType.Mouse:
			from gremlin.ui.keyboard_device import KeyboardDeviceTabWidget
			device_guid = KeyboardDeviceTabWidget.device_guid
			
			mouse_button = event.identifier
			# convert the mouse button to the virtual scan code we use for mouse events
			index = (mouse_button.value + 0x1000, False)
			verbose = gremlin.config.Configuration().verbose_mode_mouse
			if verbose:
				logging.getLogger("system").info(f"matching mouse event {event.identifier} to {KeyMap.keyid_tostring(index)}")
		else:
			verbose = gremlin.config.Configuration().verbose_mode_keyboard
			device_guid = event.device_guid
			# index = event.virtual_code if event.virtual_code > 0 else event.identifier  # this is (scan_code, is_extended)
			index, _ = KeyMap.translate(event.identifier)
			verbose = gremlin.config.Configuration().verbose_mode_keyboard
			if verbose:
				logging.getLogger("system").info(f"matching key event {event.identifier} to {KeyMap.keyid_tostring(index)}")

		#event_key = Key(scan_code = identifier[0], is_extended = identifier[1], is_mouse = is_mouse, virtual_code= virtual_code)
		input_items = []

		#found = False
		#print (f"looking for:  {identifier} mode: {self._active_mode}")
		# grab active modes and parent modes
	
		if device_guid in self.latched_events:
			
			#print (f"found guid: {device_guid}")
			data = self.latched_events[event.device_guid]
			if self._active_mode in data.keys():
				#print (f"found mode {self._active_mode}")
				data = data[self._active_mode]
				matching_keys = []
				# if virtual_code > 0:
				# 	if virtual_code in data.keys():
				# 		matching_keys = data[virtual_code]
				# else:
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

					# print (f"KEY INPUT MATCH: {input_item}")
					
				# if verbose:
				# 	logging.getLogger("system").info(f"MATCHED EVENTS: mode: [{self._active_mode}] {KeyMap.keyid_tostring(index)} -> found {len(input_items)} matching callback events")	
				# 	for key in input_items:
				# 		logging.getLogger("system").info(f"event: {key.name} latched: {key.latched}")

				return input_items
			# if not found:
			# 	print (f"did not find index {identifier} - available keys are:")
			# 	self.dump_callbacks()
			
			
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

	def change_mode(self, new_mode):
		"""Changes the currently active mode.

		:param new_mode the new mode to use
		"""

		current_profile = gremlin.shared_state.current_profile
		if new_mode == gremlin.shared_state.current_mode:
			# already in this mode
			return

		logging.getLogger("system").debug(f"EVENT: change mode to [{new_mode}] requested - profile '{current_profile.name}")

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
		


		
		if self._active_mode != new_mode:
			self._previous_mode = self._active_mode
			# remember the last mode for this profile
			current_profile.set_last_mode(self._active_mode)


		logging.getLogger("system").debug(f"Mode switch to: {new_mode}  Profile: {current_profile.name}")

		self._active_mode = new_mode
		self.mode_changed.emit(self._active_mode)
	

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
	def process_event(self, event):
		"""Processes a single event by passing it to all callbacks
		registered for this event.

		:param event the event to process
		"""

		from gremlin.util import display_error
		import gremlin.config

		# list of callbacks
		m_list = []

		
		
		verbose = False

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
					logging.getLogger("system").info(f"\t\t{KeyMap.keyid_tostring(key)} {data[key]}")					

			items = self._matching_event_keys(event)  # returns list of primary keys
			if items:
				# if verbose:
				# 	logging.getLogger("system").info(f"Matched keys for mode: [{self._active_mode}]  event {event} pressed: {event.is_pressed} keys: {len(items)} ")
				# 	for index, input_item in enumerate(items):
				# 		logging.getLogger("system").info(f"\t[{index}]: {input_item.name}")
				
				is_latched = True
				
				for input_item in items:
					latch_key = None
					# print (data)
					latched_keys = [input_item.key]
					latched_keys.extend(input_item.latched_keys)
					# if verbose:
					# 	logging.getLogger("system").info(f"Checking latching: {len(latched_keys)} key(s)")
					for k in latched_keys:
						index = k.index_tuple()
						found = index in data.keys()
						state = data[index] if found else False
						if verbose:
							logging.getLogger("system").info(f"\tcheck latched key: {KeyMap.keyid_tostring(index)} {k.name} state found: {found} pressed state: {state} {'*****' if state else ''}")
						is_latched = is_latched and state

					if verbose: 
						logging.getLogger("system").info(f"Final latched state: {is_latched}")
					
					if is_latched: 
						latch_key = input_item.key
						if verbose:
							logging.getLogger("system").info(f"Detect KEY PRESSED: mode: [{self._active_mode}] {input_item.key.name}")
					else:
						if verbose:
							logging.getLogger("system").info(f"Detect KEY RELEASED: {input_item.key.name}")
									
					if latch_key:
						print (f"Found latched key: {latch_key}")
						m_list = self._matching_latched_callbacks(event, latch_key)
						if m_list:
							if verbose:
								trigger_line = "***** TRIGGER " + "*"*30
								logging.getLogger("system").info(trigger_line)
								logging.getLogger("system").info(f"\tmode: [{self._active_mode}] Found latched key: Check key {latch_key.name} callbacks: {len(m_list)} event: {event}")
								logging.getLogger("system").info(trigger_line)
							self._trigger_callbacks(m_list, event)
							return
						else:
							print (f"No callbacks found for: {latch_key}")

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

		

		if verbose and m_list:
			logging.getLogger("system").info(f"TRIGGER: mode: [{self._active_mode}] callbacks: {len(m_list)} event: {event}")
		self._trigger_callbacks(m_list, event)			


	def _trigger_callbacks(self, callbacks, event):
		#verbose = gremlin.config.Configuration().verbose
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
					self._active_mode, {}
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
					self._active_mode, {}
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
		# Obtain callbacks matching the event
		callback_list = []
		if event.device_guid in self.callbacks:
			callback_list = self.callbacks[event.device_guid].get(
				self._active_mode, {}
			).get(event, [])

		# Filter events when the system is paused
		if not self.process_callbacks:
			return [c[0] for c in callback_list if c[1]]
		else:
			return [c[0] for c in callback_list]
		

	def _matching_latched_callbacks(self, event, key):
		callback_list = []
		if event.device_guid in self.latched_callbacks:
			callback_list = self.latched_callbacks[event.device_guid].get(
				self._active_mode, {}
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
