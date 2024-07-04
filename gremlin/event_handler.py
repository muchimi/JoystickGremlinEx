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
from threading import Thread, Timer

from PySide6 import QtCore

import dinput
import gremlin.config
from gremlin.input_types import InputType
import gremlin.keyboard
import gremlin.shared_state
import gremlin.shared_state
from gremlin.singleton_decorator import SingletonDecorator
from . import config, error, joystick_handling, windows_event_hook

from gremlin.keyboard import Key



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
				event_type= InputType.Keyboard,
				identifier=(key.scan_code, key.is_extended),
				device_guid=dinput.GUID_Keyboard
			)
		
		raise ValueError(f"Unable to handle parameter - not a valid key: {key}")
	
	def __str__(self):
		if self.event_type == InputType.Mouse:
			return f"Event: Mouse - button {self.identifier} pressed: {self.is_pressed}"
		elif self.event_type == InputType.Keyboard:
			return f"Event: Keyboard - scan code, extended : {self.identifier} pressed: {self.is_pressed}"
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
		self._keyboard_state = {}
		self.gremlin_active = False

		self.keyboard_hook.start()

		Thread(target=self._run).start()

	def start(self):
		''' starts the non regular listener '''
		self.mouse_hook.start()

	def stop(self):
		self.mouse_hook.stop()

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
		verbose = config.Configuration().verbose
		
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
		"""Callback for keyboard events.

		The handler converts the event data into a signal which is then
		emitted.

		:param event the keyboard event
		"""
		if not self._running:
			return True

		key_id = (event.scan_code, event.is_extended)
		is_pressed = event.is_pressed
		is_repeat = self._keyboard_state.get(key_id, False) and is_pressed
		# Only emit an event if they key is pressed for the first
		# time or released but not when it's being held down
		if not is_repeat:
			self._keyboard_state[key_id] = is_pressed
			self.keyboard_event.emit(Event(
				event_type= InputType.Keyboard,
				device_guid=dinput.GUID_Keyboard,
				identifier=key_id,
				is_pressed=is_pressed,
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
		verbose = gremlin.config.Configuration().verbose
		if event:
			if event.event_type in (InputType.Keyboard, InputType.KeyboardLatched):
				# keyboard latched event
				identifier = event.identifier
				primary_key : Key = identifier.key

				
				# if the key can latch with multiple primary keys, build the table of all combinations
				key_list = [primary_key]
				if primary_key.is_latched:
					# multiple keys 
					key_list.extend(primary_key._latched_keys)

				for key in key_list:
 					# the events will arrive as keyboard events - in any order - this makes sure latching is checked regardless of the order of key presses
					index = key.index_tuple() 
					if device_guid not in self.latched_events.keys():
						self.latched_events[device_guid] = {}
				
					if mode not in self.latched_events[device_guid].keys():
						self.latched_events[device_guid][mode] = {}
					if index not in self.latched_events[device_guid][mode].keys():
						self.latched_events[device_guid][mode][index] = []
					if not identifier in self.latched_events[device_guid][mode][index]:
						self.latched_events[device_guid][mode][index].append(identifier)
					if verbose:
						logging.getLogger("system").info(f"Key latch registered: guid {device_guid}  mode:  {mode} index: {index} name: {key.name} -> {identifier.display_name}")
					

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
		verbose = gremlin.config.Configuration().verbose
		# convert mouse events to keyboard event
		if event.event_type == InputType.Mouse:
			from gremlin.ui.keyboard_device import KeyboardDeviceTabWidget
			device_guid = KeyboardDeviceTabWidget.device_guid
			mouse_button = event.identifier
			# convert the mouse button to the virtual scan code we use for mouse events
			identifier = (mouse_button.value + 0x1000, False)
			is_mouse = True
			# logging.getLogger("system").info(f"matching mouse event {event.identifier} to {identifier}")
		else:
			device_guid = event.device_guid
			identifier = event.identifier  # this is (scan_code, is_extended)
			is_mouse = False

		event_key = Key(scan_code = identifier[0], is_extended = identifier[1], is_mouse = is_mouse)
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
				if identifier in data.keys():
					#print ("found identifier")
					matching_keys = data[identifier]
					for input_item in matching_keys:
						key = input_item.key
						if event.is_pressed:
							if key.is_latched and key.latched:
								input_items.append(input_item)
							elif not key.is_latched:
								input_items.append(input_item)
							
						else:
							# not pressed
							if not event_key in input_items:
								input_items.append(input_item)
							
					
					if verbose:
						logging.getLogger("system").info(f"MATCHED EVENTS: mode: [{self._active_mode}] {identifier} -> found {len(input_items)} matching callback events")	
						for key in input_items:
							logging.getLogger("system").info(f"event: {key.name} latched: {key.latched}")

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

	def change_mode(self, new_mode):
		"""Changes the currently active mode.

		:param new_mode the new mode to use
		"""

		logging.getLogger("system").debug(f"EVENT: change mode to [{new_mode}] requested")
		mode_exists = False
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
				f"The mode \"{new_mode}\" does not exist or has no associated callbacks"
			)
			return

		
		if self._active_mode != new_mode:
			self._previous_mode = self._active_mode

		cfg = config.Configuration()
		cfg.set_last_mode(cfg.last_profile, new_mode)

		logging.getLogger("system").debug(f"Mode switch to: {new_mode}")

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

		verbose = gremlin.config.Configuration().verbose

		# filter latched keyboard or mouse events
		if event.event_type in (InputType.Keyboard, InputType.KeyboardLatched, InputType.Mouse):
			if verbose:
				logging.getLogger("system").info(f"process keyboard event: {event}")
			keys = self._matching_event_keys(event)  # returns list of primary keys
			if keys:
				if verbose:
					logging.getLogger("system").info(f"Matched keys for mode: [{self._active_mode}]  event {event} keys: {len(keys)} ")
					for index, key in enumerate(keys):
						logging.getLogger("system").info(f"\t[{index}]: {key.name}")
				for key in keys:
					latch_key = None
					is_latched = key.latched

					if event.is_pressed:
						if is_latched: 
							latch_key = key.key
						if verbose:
							logging.getLogger("system").info(f"KEY PRESSED: mode: [{self._active_mode}] {key.key.name} -> latched {is_latched}")

					else:
						# any key in the latch sequence that isn't pressed breaks the press
						if not is_latched:
							latch_key = key.key
							if verbose:
								logging.getLogger("system").info(f"KEY RELEASED: {latch_key.name}")
									
					if latch_key:
						m_list = self._matching_latched_callbacks(event, latch_key)
						if verbose and m_list:
							logging.getLogger("system").info(f"TRIGGER: mode: [{self._active_mode}] Found latched key: Check key {latch_key.name} callbacks: {len(m_list)} event: {event}")
						self._trigger_callbacks(m_list, event)
			return
						
		elif event.event_type ==InputType.Midi:
			m_list = self._matching_midi_callbacks(event)
		elif event.event_type == InputType.OpenSoundControl:
			m_list = self._matching_osc_callbacks(event)
		else:			 
			# other inputs
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
