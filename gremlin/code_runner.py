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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import importlib
import logging
import os
import random
import string
import sys
import time

import dinput

import gremlin
# from gremlin import event_handler, input_devices, \
#     joystick_handling, macro, sendinput, user_plugin, util


from gremlin.input_types import InputType
import gremlin.shared_state
import gremlin.types
import gremlin.plugin_manager
import vjoy as vjoy_module
import gremlin.config
import gremlin.event_handler
import gremlin.util
import gremlin.joystick_handling
import gremlin.macro
import gremlin.input_devices
import gremlin.user_plugin
import gremlin.sendinput as sendinput

syslog = logging.getLogger("system")

class CodeRunner:

    """Runs the actual profile code."""

    def __init__(self):
        """Creates a new code runner instance."""
        self.event_handler = gremlin.event_handler.EventHandler()
        self.event_handler.add_plugin(gremlin.input_devices.JoystickPlugin())
        self.event_handler.add_plugin(gremlin.input_devices.VJoyPlugin())
        self.event_handler.add_plugin(gremlin.input_devices.KeyboardPlugin())

        self._inheritance_tree = None
        self._vjoy_curves = VJoyCurves()
        self._merge_axes = []
        self._running = False
        self._startup_profile = None
        self._startup_mode = None

    def is_running(self):
        """Returns whether or not the code runner is executing code.

        :return True if code is being executed, False otherwise
        """
        return self._running
    


    def start(self, inheritance_tree, settings, start_mode, profile):
        """Starts listening to events and loads all existing callbacks.

        :param inheritance_tree tree encoding inheritance between the
            different modes
        :param settings profile settings to apply at launch
        :param start_mode the mode in which to start Gremlin
        :param profile the profile to use when generating all the callbacks
        """
        # Reset states to their default values
        self._inheritance_tree = inheritance_tree
        self._reset_state()

        # clear any startup routines
        gremlin.input_devices.start_registry.clear()
        gremlin.input_devices.stop_registry.clear()
        gremlin.input_devices.mode_registry.clear()

        config = gremlin.config.Configuration()

        # store the startup mode in the UI so it can be restored later
        self._startup_profile = gremlin.shared_state.current_profile
        self._startup_mode = gremlin.shared_state.current_mode

        # Check if we want to override the start mode as determined by the
        # heuristic

        start_mode = gremlin.shared_state.current_profile.get_start_mode()
        logging.getLogger("system").info(f"Startup mode: {start_mode}")
        
        # Set default macro action delay
        gremlin.macro.MacroManager().default_delay = settings.default_delay

        # Retrieve list of current paths searched by Python
        system_paths = [os.path.normcase(os.path.abspath(p)) for p in sys.path]

        # Load the generated code
        try:
            # Populate custom module variable registry
            var_reg =gremlin.user_plugin.variable_registry
            for plugin in profile.plugins:
                # Perform system path mangling for import statements
                path, _ = os.path.split(
                    os.path.normcase(os.path.abspath(plugin.file_name))
                )
                if path not in system_paths:
                    system_paths.append(path)

                # Load module specification so we can later create multiple
                # instances if desired
                spec = importlib.util.spec_from_file_location(
                    "".join(random.choices(string.ascii_lowercase, k=16)),
                    plugin.file_name
                )

                # Process each instance in turn
                for instance in plugin.instances:
                    # Skip all instances that are not fully configured
                    if not instance.is_configured():
                        continue

                    # Store variable values in the registry
                    for var in instance.variables.values():
                        var_reg.set(
                            plugin.file_name,
                            instance.name,
                            var.name,
                            var.value
                        )

                    # Load the modules
                    tmp = importlib.util.module_from_spec(spec)
                    tmp.__gremlin_identifier = (plugin.file_name, instance.name)
                    spec.loader.exec_module(tmp)
           
            

            # Update system path list searched by Python
            sys.path = system_paths

            # Create callbacks fom the user code
            callback_count = 0
            for dev_id, modes in gremlin.input_devices.callback_registry.registry.items():
                for mode, events in modes.items():
                    for event, callback_list in events.items():
                        for callback in callback_list.values():
                            self.event_handler.add_callback(
                                dev_id,
                                mode,
                                event,
                                callback[0],
                                callback[1]
                            )
                            callback_count += 1

            # Add a fake keyboard action which does nothing to the callbacks
            # in every mode in order to have empty modes be "present"
            for mode_name in gremlin.profile.mode_list(profile):
                self.event_handler.add_callback(
                    0,
                    mode_name,
                    None,
                    lambda x: x,
                    False
                )


            # reset functor latching
            container_plugins = gremlin.plugin_manager.ContainerPlugins()
            container_plugins.reset_functors()

            mode_source = gremlin.shared_state.current_profile.traverse_mode()
            mode_source.sort(key = lambda x: x[0]) # sort parent to child
            mode_list = [mode for (_,mode) in mode_source] # parent mode first

            # Create input callbacks based on the profile's content
            for device in profile.devices.values():
                for mode in device.modes.values():
                    for input_items in mode.config.values():
                        for input_item in input_items.values():
                            # Only add callbacks for input items that actually
                            # contain actions

                            
                            if len(input_item.containers) == 0:
                                # no containers = no actions = skip
                                continue

                            event = gremlin.event_handler.Event(
                                event_type=input_item.input_type,
                                device_guid=device.device_guid,
                                identifier=input_item.input_id
                            )

                            # Create possibly several callbacks depending
                            # on the input item's content
                            callbacks = []
                            for container in input_item.containers:
                                if not container.is_valid():
                                    logging.getLogger("system").warning(
                                        "Incomplete container ignored"
                                    )
                                    continue
                                callbacks.extend(container.generate_callbacks())

                            for cb_data in callbacks:
                                if cb_data.event is None:
                                    self.event_handler.add_callback(
                                        device.device_guid,
                                        mode.name,
                                        event,
                                        cb_data.callback,
                                        input_item.always_execute
                                    )
                                else:
                                    self.event_handler.add_callback(
                                        dinput.GUID_Virtual,
                                        mode.name,
                                        cb_data.event,
                                        cb_data.callback,
                                        input_item.always_execute
                                    )

                            verbose = config.verbose
                            if verbose:
                                self.event_handler.dump_callbacks()

            # Create merge axis callbacks
            for entry in profile.merge_axes:
                merge_axis = MergeAxis(
                    entry["vjoy"]["vjoy_id"],
                    entry["vjoy"]["axis_id"],
                    entry["operation"]
                )
                self._merge_axes.append(merge_axis)

                # Lower axis callback
                event = gremlin.event_handler.Event(
                    event_type=InputType.JoystickAxis,
                    device_guid=entry["lower"]["device_guid"],
                    identifier=entry["lower"]["axis_id"]
                )
                self.event_handler.add_callback(
                    event.device_guid,
                    entry["mode"],
                    event,
                    merge_axis.update_axis1,
                    False
                )

                # Upper axis callback
                event = gremlin.event_handler.Event(
                    event_type=InputType.JoystickAxis,
                    device_guid=entry["upper"]["device_guid"],
                    identifier=entry["upper"]["axis_id"]
                )
                self.event_handler.add_callback(
                    event.device_guid,
                    entry["mode"],
                    event,
                    merge_axis.update_axis2,
                    False
                )

            # Create vJoy response curve setups
            self._vjoy_curves.profile_data = profile.vjoy_devices
            self.event_handler.mode_changed.connect(
                self._vjoy_curves.mode_changed
            )

            # Use inheritance to build input action lookup table
            self.event_handler.build_event_lookup(inheritance_tree)

            # Set vJoy axis default values
            for vid, data in settings.vjoy_initial_values.items():
                vjoy_proxy = gremlin.joystick_handling.VJoyProxy()[vid]
                for aid, value in data.items():
                    vjoy_proxy.axis(linear_index=aid).set_absolute_value(value)

            # Connect signals
            evt_listener = gremlin.event_handler.EventListener()

           
            # hook mouse events
            evt_listener.mouse_event.connect(
                self.event_handler.process_event
            )

            # hook keyboard events
            evt_listener.keyboard_event.connect(
                self.event_handler.process_event
            )

            # hook joystick input events 
            evt_listener.joystick_event.connect(
                self.event_handler.process_event
            )

            # hook virtual events
            evt_listener.virtual_event.connect(
                self.event_handler.process_event
            )

            # hook midi events
            evt_listener.midi_event.connect(
                self.event_handler.process_event
            )

            # hook osc events
            evt_listener.osc_event.connect(
                self.event_handler.process_event
            )
            
            
            # monitor keyboard input state
            kb = gremlin.input_devices.Keyboard()
            evt_listener.keyboard_event.connect(kb.keyboard_event)

            # mark active
            evt_listener.gremlin_active = True

            # connect remote gremlin client
            gremlin.input_devices.remote_server.start()
            gremlin.input_devices.remote_client.start()

            # listen to MIDI 
            if config.midi_enabled:
                gremlin.input_devices.midi_client.start()

            # listen to OSC
            if config.osc_enabled:
                gremlin.input_devices.osc_client.start()
            
            #evt_listener.remote_event.connect(self.event_handler.process_event)


            # hook mode change callbacks
            self.event_handler.mode_changed.connect(
                gremlin.input_devices.mode_registry.mode_changed
            )

            # hook state change callbacks
            evt_listener.broadcast_changed.connect(
                gremlin.input_devices.state_registry.state_changed
            )


            # call start functions
            gremlin.input_devices.start_registry.start()
            gremlin.input_devices.periodic_registry.start()     



            gremlin.macro.MacroManager().start()

            # determine the profile start mode
            verbose = True
            mode = start_mode
            if config.restore_profile_mode_on_start or profile.get_restore_mode():
                # restore the profile mode 
                if verbose:
                    logging.getLogger("system").error(f"Restore last active profile mode: '{mode}'")
                mode = profile.get_last_mode()

                if mode:
                    if not mode in mode_list:
                        logging.getLogger("system").error(f"Unable to restore profile mode: '{mode}' no longer exists - using '{start_mode}' instead.")
                        mode = start_mode

            
            if not mode in mode_list:
                logging.getLogger("system").error(f"Unable to select startup mode: '{mode}' no longer exists")
            else:                
                if verbose:
                    logging.getLogger("system").info(f"Using profile start mode: '{mode}'")
                self.event_handler.change_mode(mode)
                
            self._running = True
            gremlin.shared_state.is_running = True

            sendinput.MouseController().start()

            # start listen
            evt_listener.start()

            # tell listener profiles are starting
            el = gremlin.event_handler.EventListener()
            el.profile_start.emit()

            #print ("resume!")
            self.event_handler.resume()



        except Exception as e:
            msg = f"Unable to launch user plugin due to an error: {e}"
            syslog.debug(msg)
            gremlin.util.display_error(msg)
            

    def stop(self):
        """Stops listening to events and unloads all callbacks."""

        el = gremlin.event_handler.EventListener()
        eh = gremlin.event_handler.EventHandler()

        # stop listen
        el.stop()

        el.profile_stop.emit()

        # stop midi client
        gremlin.input_devices.midi_client.stop()

        # stop OSC client
        gremlin.input_devices.osc_client.stop()

        # stop remote client
        gremlin.input_devices.remote_client.stop()
        gremlin.input_devices.remote_server.stop()

        # call stop function in plugins
        gremlin.input_devices.stop_registry.start()
        gremlin.input_devices.stop_registry.stop()
        gremlin.input_devices.stop_registry.clear()
        gremlin.input_devices.mode_registry.clear()
        
        # reset functor latching
        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        container_plugins.reset_functors()        

        # Disconnect all signals

        is_running = self._running
        if is_running:
            evt_lst = gremlin.event_handler.EventListener()

            # tell listeners profile is stopping
            evt_lst.profile_stop.emit()

            kb = gremlin.input_devices.Keyboard()
            evt_lst.keyboard_event.disconnect(self.event_handler.process_event)
            evt_lst.joystick_event.disconnect(self.event_handler.process_event)
            evt_lst.virtual_event.disconnect(self.event_handler.process_event)
            evt_lst.midi_event.disconnect(self.event_handler.process_event)
            evt_lst.osc_event.disconnect(self.event_handler.process_event)

            evt_lst.keyboard_event.disconnect(kb.keyboard_event)
            evt_lst.gremlin_active = False
            self.event_handler.mode_changed.disconnect(
                self._vjoy_curves.mode_changed
            )
            


        self._running = False
        gremlin.shared_state.is_running = False


        # Empty callback registry
        gremlin.input_devices.callback_registry.clear()
        self.event_handler.clear()

        # Stop periodic events and clear registry
        gremlin.input_devices.periodic_registry.stop()
        gremlin.input_devices.periodic_registry.clear()

        # stop
        gremlin.input_devices.start_registry.stop()
        gremlin.input_devices.start_registry.clear()


        gremlin.macro.MacroManager().stop()
        sendinput.MouseController().stop()

        # Remove all claims on VJoy devices
        gremlin.joystick_handling.VJoyProxy.reset()

        # restore any mode 
        if self._startup_profile and gremlin.shared_state.current_profile != self._startup_profile:
            eh.change_profile(self._startup_profile)
        if self._startup_mode:
            eh.change_mode(self._startup_mode)


    def _reset_state(self):
        """Resets all states to their default values."""
        self.event_handler._active_mode =\
            list(self._inheritance_tree.keys())[0]
        self.event_handler._previous_mode =\
            list(self._inheritance_tree.keys())[0]
        gremlin.input_devices.callback_registry.clear()


class VJoyCurves:

    """Handles setting response curves on vJoy devices."""

    def __init__(self):
        """Creates a new instance"""
        self.profile_data = None

    def mode_changed(self, mode_name):
        """Called when the mode changes and updates vJoy response curves.

        :param mode_name the name of the new mode
        """
        if not self.profile_data:
            return

        vjoy = gremlin.joystick_handling.VJoyProxy()
        for guid, device in self.profile_data.items():
            if mode_name in device.modes:
                for aid, data in device.modes[mode_name].config[
                        InputType.JoystickAxis
                ].items():
                    # Get integer axis id in case an axis enum was used
                    axis_id = vjoy_module.vjoy.VJoy.axis_equivalence.get(aid, aid)
                    vjoy_id = gremlin.joystick_handling.vjoy_id_from_guid(guid)

                    if len(data.containers) > 0 and \
                            vjoy[vjoy_id].is_axis_valid(axis_id):
                        action = data.containers[0].action_sets[0][0]
                        vjoy[vjoy_id].axis(aid).set_deadzone(*action.deadzone)
                        vjoy[vjoy_id].axis(aid).set_response_curve(
                            action.mapping_type,
                            action.control_points
                        )


class MergeAxis:

    """Merges inputs from two distinct axes into a single one."""

    def __init__(
            self,
            vjoy_id: int,
            input_id: int,
            operation: gremlin.types.MergeAxisOperation
    ):
        self.axis_values = [0.0, 0.0]
        self.vjoy_id = vjoy_id
        self.input_id = input_id
        self.operation = operation

    def _update(self):
        """Updates the merged axis value."""
        value = 0.0
        if self.operation == gremlin.types.MergeAxisOperation.Average:
            value = (self.axis_values[0] - self.axis_values[1]) / 2.0
        elif self.operation == gremlin.types.MergeAxisOperation.Minimum:
            value = min(self.axis_values[0], self.axis_values[1])
        elif self.operation == gremlin.types.MergeAxisOperation.Maximum:
            value = max(self.axis_values[0], self.axis_values[1])
        elif self.operation == gremlin.types.MergeAxisOperation.Sum:
            value = gremlin.util.clamp(
                self.axis_values[0] + self.axis_values[1],
                -1.0,
                1.0
            )
        else:
            raise gremlin.error.GremlinError(
                f"Invalid merge axis operation detected, \"{str(self.operation)}\""
            )

        gremlin.joystick_handling.VJoyProxy()[self.vjoy_id]\
            .axis(self.input_id).value = value

    def update_axis1(self, event: gremlin.event_handler.Event):
        """Updates information for the first axis.

        :param event data event for the first axis
        """
        self.axis_values[0] = event.value
        self._update()

    def update_axis2(self, event: gremlin.event_handler.Event):
        """Updates information for the second axis.

        :param event data event for the second axis
        """
        self.axis_values[1] = event.value
        self._update()