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

import importlib
import logging
import os
import random
import string
import sys


import dinput

import gremlin
from gremlin.input_types import InputType
import gremlin.keyboard
import gremlin.shared_state
import gremlin.types
from gremlin.types import DeviceType
import gremlin.plugin_manager
import gremlin.ui.state_device
import gremlin.windows_event_hook
import vjoy as vjoy_module
from vjoy import vjoy
import gremlin.config
import gremlin.event_handler
import gremlin.util
import gremlin.joystick_handling
import gremlin.macro
import gremlin.input_devices
import gremlin.user_plugin
import gremlin.sendinput as sendinput
import gremlin.execution_graph
import gremlin.ui
import gremlin.remote
import gremlin.base_profile

import traceback

syslog = logging.getLogger("system")


class CodeRunner:
    """Runs the actual profile code."""

    def __init__(self):
        """Creates a new code runner instance."""
        self.event_handler: gremlin.event_handler.EventHandler = gremlin.event_handler.EventHandler()
        self.event_handler.add_plugin(gremlin.input_devices.JoystickPlugin())
        self.event_handler.add_plugin(gremlin.input_devices.VJoyPlugin())
        self.event_handler.add_plugin(gremlin.input_devices.KeyboardPlugin())

        # self._sentry_timer = None
        # self._sentry_tick = 10 # tick timer in seconds

        eh = gremlin.event_handler.EventListener()
        eh.action_created.connect(self._action_created_cb)

        self._inheritance_tree = None
        # self._vjoy_curves = VJoyCurves()
        self._merge_axes = []
        self._startup_profile = None
        self._startup_mode = None
        self._actions = []  # tracks functors in this profile

    def _action_created_cb(self, action):
        if action not in self._actions:
            self._actions.append(action)

    def is_running(self):
        """Returns whether or not the code runner is executing code.

        :return True if code is being executed, False otherwise
        """
        return gremlin.shared_state.is_running

    def setUIState(self, enabled: bool):
        """enables/disables UI elements for run/edit modes"""
        ui = gremlin.shared_state.ui.ui
        ui.devices_tab_header_widget.setEnabled(enabled)  # tab header
        ui.tab_content_widget.setEnabled(enabled)  # content widget
        ui.actionNewProfile.setEnabled(enabled)
        ui.actionOpen.setEnabled(enabled)
        ui.actionLoadProfile.setEnabled(enabled)
        ui.actionRecent.setEnabled(enabled)
        ui.actionManageModes.setEnabled(enabled)
        ui.actionOptions.setEnabled(enabled)
        ui.actionCreate1to1Mapping.setEnabled(enabled)
        # ui.actionMergeAxis.setEnabled(enabled)
        # ui.actionSwapDevices.setEnabled(enabled)
        # ui.actionModifyProfile.setEnabled(enabled)

    def disableUi(self):
        """disables UI"""
        if not gremlin.config.Configuration().runtime_ui_active:
            self.setUIState(False)

    def enableUI(self):
        """enables UI"""
        self.setUIState(True)

    def start(self, inheritance_tree, settings, start_mode, profile) -> bool:
        """Starts listening to events and loads all existing callbacks.

        :param inheritance_tree tree encoding inheritance between the
            different modes
        :param settings profile settings to apply at launch
        :param start_mode the mode in which to start Gremlin
        :param profile the profile to use when generating all the callbacks
        :returns: True on success, False if the profile did not start (various reasons)
        """

        el = gremlin.event_handler.EventListener()
        eh = gremlin.event_handler.EventHandler()

        eh.reset()  # reset processing data before any new run
        vs = gremlin.joystick_handling.VjoyStart()
        vs.reset()  # reset the vjoy start data

        ec = gremlin.execution_graph.ExecutionContext()
        ec.reset(force_rebuild=True)  # rebuild the execution tree

        build_error = ec.getLastBuildError()
        if build_error:
            syslog.error("Error building execution tree - aborting start.")
            self.stop()
            return False

        config = gremlin.config.Configuration()

        gremlin.shared_state.profile_state = True  # assume profile start ok
        gremlin.shared_state.profile_message_issued = False  # no message issued

        self.disableUi()

        # gc.collect()

        # update hardware list for any missing devices
        gremlin.joystick_handling.scanDinput()

        # indicate we're in run mode
        gremlin.shared_state.is_running = True
        gremlin.windows_event_hook.setRunning(True)

        # Reset states to their default values
        self._inheritance_tree = inheritance_tree
        self._reset_state()

        # clear any startup routines
        gremlin.input_devices.start_registry.clear()
        gremlin.input_devices.stop_registry.clear()
        gremlin.input_devices.mode_registry.clear()

        config = gremlin.config.Configuration()
        verbose_detailed = config.verbose_mode_details
        verbose = config.verbose_mode_details

        # store the startup mode in the UI so it can be restored later
        self._startup_profile = gremlin.shared_state.current_profile
        self._startup_mode = gremlin.shared_state.current_mode

        # Check if we want to override the start mode as determined by the
        # heuristic

        if not start_mode:
            start_mode = gremlin.shared_state.current_profile.get_start_mode()

        syslog.info(f"Startup mode: {start_mode}")

        # Set default macro action delay
        gremlin.macro.MacroManager().default_delay = settings.default_delay

        # Retrieve list of current paths searched by Python
        system_paths = [os.path.normcase(os.path.abspath(p)) for p in sys.path]

        # Load the generated code
        try:
            # Populate custom module variable registry
            var_reg = gremlin.user_plugin.variable_registry
            for plugin in profile.plugins:
                # Perform system path mangling for import statements
                path, _ = os.path.split(os.path.normcase(os.path.abspath(plugin.file_name)))
                if path not in system_paths:
                    system_paths.append(path)

                # Load module specification so we can later create multiple
                # instances if desired
                spec = importlib.util.spec_from_file_location("".join(random.choices(string.ascii_lowercase, k=16)), plugin.file_name)

                _, plugin_basename = os.path.split(plugin.file_name)

                # Process each instance in turn
                for instance in plugin.instances:
                    # Skip all instances that are not fully configured
                    if not instance.is_configured():
                        syslog.warn(
                            f"Warning: User plugin '{plugin_basename}': instance '{instance.name}' reports not configured - skipping runtime activation"
                        )
                        continue

                    # Store variable values in the registry
                    for var in instance.variables.values():
                        var_reg.set(plugin.file_name, instance.name, var.name, var.value)

                    # Load the modules
                    if os.path.isfile(plugin.file_name):
                        tmp = importlib.util.module_from_spec(spec)
                        tmp.__gremlin_identifier = (plugin.file_name, instance.name)
                        spec.loader.exec_module(tmp)
                    else:
                        basename = os.path.basename(plugin.file_name)
                        gremlin.ui.ui_common.MessageBox(prompt=f"Plugin {basename} was not found and will not be loaded.")

            # Update system path list searched by Python
            sys.path = system_paths

            # master mode name
            master_mode = gremlin.shared_state.master_mode

            # Create callbacks fom the user code
            callback_count = 0
            for dev_id, modes in gremlin.input_devices.callback_registry.registry.items():
                for mode, events in modes.items():
                    for event, callback_list in events.items():
                        for callback in callback_list.values():
                            self.event_handler.addCallback(dev_id, mode, event, callback[0], callback[1])
                            callback_count += 1

            # Add a fake keyboard action which does nothing to the callbacks
            # in every mode in order to have empty modes be "present"
            for mode_name in gremlin.profile.mode_list():
                self.event_handler.addCallback(gremlin.joystick_handling.invalidDeviceGuid(), mode_name, None, lambda x: x, False)

            # reset functor latching
            container_plugins = gremlin.plugin_manager.ContainerPlugins()
            container_plugins.reset_functors()

            mode_source = gremlin.shared_state.current_profile.traverse_mode()
            mode_source.sort(key=lambda x: x[0])  # sort parent to child
            mode_list = [mode for (_, mode) in mode_source]  # parent mode first

            assert master_mode in mode_list, "master mode missing"

            # XXX todo: check that callbacks are setup for master mode on profile start as they are missing from the callback stack

            # ensure all profile modes are in the execution graph if they are defined - this is so we can search them
            graph_mode_nodes = {}
            for mode in mode_list:
                graph_mode_node = gremlin.execution_graph.ExecutionGraphModeNode(mode)
                graph_mode_node.parent = ec.graph
                graph_mode_nodes[mode] = graph_mode_node

            # Create input callbacks based on the profile's content
            # profile.sync()

            verbose = gremlin.config.Configuration().verbose_mode_exec
            device_node: gremlin.base_profile.ProfileDeviceNode
            for device_node in profile.devices.values():
                device_guid = device_node.device_guid
                device = gremlin.joystick_handling.getDevice(device_guid)
                if not device or device.disabled:
                    if verbose:
                        syslog.info("CALLBACK: skipping a device (this is normal if the device is disabled):")
                        syslog.info(f"\t{str(device_node)}")
                    continue

                if device.device_type == DeviceType.ModeControl:
                    pass
                device_name = device.name
                if verbose:
                    syslog.info(f"CALLBACK: device: {str(device_node)}")

                profile_mode_node: gremlin.base_profile.ProfileModeNode
                for mode_name, profile_mode_node in device_node.modes.items():
                    if mode_name not in graph_mode_nodes:
                        # special mode or mode not present in profile
                        continue

                    graph_mode_node = graph_mode_nodes[mode_name]

                    for input_type, input_map in profile_mode_node.config.items():
                        for input_item in input_map.values():
                            # Only add callbacks for input items that actually
                            # contain actions
                            if not input_item:
                                continue

                            if len(input_item.containers) == 0:
                                # no containers = no actions = skip
                                # if verbose: syslog.info(f"\t\tno containers")
                                continue

                            if verbose:
                                syslog.info(f"\t{input_item.display_name}")

                            self.event_handler.registerInputItem(mode_name, input_item)

                            event = gremlin.event_handler.Event(
                                event_type=input_type,
                                device_guid=device_guid,
                                mode=mode_name,
                                identifier=input_item.input_id,
                                extra_data={"input_item": input_item},
                            )

                            # Create possibly several callbacks depending
                            # on the input item's content
                            callbacks = []
                            for container in input_item.containers:
                                if not container.hasOutput():
                                    syslog.warning(f"CALLBACK: device: {device_name}: input: {input_item.display_name}: warning: zero output container ignored")
                                    continue
                                if not container.is_valid():
                                    continue

                                callbacks.extend(container.generate_callbacks(graph_mode_node))

                            for cb_data in callbacks:
                                if cb_data.event is None:
                                    if verbose:
                                        syslog.info("\t\tcallback: ")
                                        if not hasattr(cb_data.callback, "execution_graph"):
                                            continue
                                        for functor in cb_data.callback.execution_graph.functors:
                                            if hasattr(functor, "action_set"):
                                                for action in functor.action_set.functors:
                                                    if isinstance(action, gremlin.input_item.BaseActivationCondition):
                                                        syslog.info(f"\t\t\tActivation Condition: target :{action.target.name}")
                                                    else:
                                                        import action_plugins.map_to_simconnect

                                                        syslog.info(f"\t\t\tAction: {action._name}")
                                                        if isinstance(action, action_plugins.map_to_simconnect.MapToSimConnectFunctor):
                                                            syslog.info(f"\t\t\t\tCommand:: {action.command}")
                                            elif hasattr(functor, "action_sets"):
                                                for action_set in functor.action_sets:
                                                    if not isinstance(action_set, list):
                                                        action_set = [action_set]
                                                    for action_item in action_set:
                                                        for action in action_item.functors:
                                                            if isinstance(action, gremlin.input_item.BaseActivationCondition):
                                                                syslog.info(f"\t\t\tActivation Condition: target :{action.target.name}")
                                                            else:
                                                                import action_plugins.map_to_simconnect

                                                                syslog.info(f"\t\t\tAction: {action._name}")
                                                                if isinstance(action, action_plugins.map_to_simconnect.MapToSimConnectFunctor):
                                                                    syslog.info(f"\t\t\t\tCommand:: {action.command}")
                                            else:
                                                syslog.info(f"\t\t\tFunctor: {functor}")
                                    self.event_handler.addCallback(device_node.device_guid, mode_name, event, cb_data.callback, input_item.always_execute)
                                else:
                                    self.event_handler.addCallback(dinput.GUID_Virtual, mode_name, cb_data.event, cb_data.callback, input_item.always_execute)

            # handle multimode actions - ensure they are hooked - these actions are actions that can process data for multiple modes such as gated axis
            nodes = ec.findActions("gated-axis")
            multimode_functors = []
            for node in nodes:
                if hasattr(node.functors, "__iter__"):
                    multimode_functors.extend(node.functors)
                else:
                    multimode_functors.append(node.functors.functor)

            self._multimode_functors = multimode_functors

            for functor in self._multimode_functors:
                functor.profile_start()

            # Create merge axis callbacks
            try:
                if profile.merge_axes:
                    syslog.warning("CodeRunner: MERGE AXIS: detected legacy merge axis in profile - use merge feature in Vjoy remap instead.  ")

            except Exception as err:
                syslog.error("Error occured in CodeRunner MergeAxis - legacy merge axis disabled")
                syslog.error(f"{err}\n{traceback.format_exc()}")

            # setup callbacks for state data changes
            sd = gremlin.ui.state_device.StateData()
            state_device_guid = gremlin.shared_state.state_tab_guid

            for key, input_item in sd.getStates().items():
                callbacks = []
                for container in input_item.containers:
                    if not container.is_valid():
                        # test = container.is_valid()
                        syslog.warning(f"CALLBACK: device: {device_name}: input: {input_item.display_name}: warning: Incomplete container ignored")
                        continue
                    callbacks.extend(container.generate_callbacks())
                for cb_data in callbacks:
                    event = gremlin.event_handler.Event(
                        event_type=InputType.State, device_guid=state_device_guid, identifier=input_item.input_id, extra_data={"input_item": input_item}
                    )
                    self.event_handler.addCallback(state_device_guid, master_mode, event, cb_data.callback, input_item.always_execute)

            # Use inheritance to build input action lookup table
            self.event_handler.build_event_lookup(inheritance_tree)

            # list of vjoys as input
            input_vids = [vid for vid in range(1, 17) if gremlin.shared_state.current_profile.settings.vjoy_as_input.get(vid, False)]

            # list of vjoy device ID to force a release on
            for vid in input_vids:
                if vjoy.device_exists(vid):
                    vjoy_proxy = gremlin.joystick_handling.VJoyProxy()[vid]
                    vjoy_proxy.ensure_released()

            # set vjoy from profile defaults
            vjoy_devices = gremlin.joystick_handling.virtual_devices()
            for device_node in vjoy_devices:
                device_id = device_node.device_id

                # set axes
                for id in range(1, device_node.axis_count + 1):
                    enabled = profile.getStartAxisEnabled(device_id, id)
                    if enabled:
                        value = profile.getStartAxisValue(device_id, id)
                        if value is not None:
                            gremlin.joystick_handling.set_axis(device_id, id, value)

                # set buttons
                for id in range(1, device_node.button_count + 1):
                    value = profile.getStartButtonState(device_id, id)
                    if value is not None:
                        gremlin.joystick_handling.set_button(device_id, id, value)

            if verbose_detailed:
                self.event_handler.dump_callbacks()

            # hook vjoy debug data based on state
            vjoy_debug = vjoy.VjoyDebug()
            vjoy_debug.Hook()

            # Connect signals
            evt_listener = gremlin.event_handler.EventListener()

            # hook mouse events
            evt_listener.mouse_event.connect(self.event_handler.execute_event)

            # hook keyboard events
            evt_listener.keyboard_event.connect(self.event_handler.execute_event)

            # hook joystick input events
            evt_listener.joystick_event.connect(self.event_handler.execute_event)

            # hook virtual events
            evt_listener.virtual_event.connect(self.event_handler.execute_event)

            # hook midi events
            evt_listener.midi_event.connect(self.event_handler.execute_event)

            # hook osc events
            evt_listener.osc_event.connect(self.event_handler.execute_event)

            # hook stream deck plugin bridge events
            evt_listener.streamdeck_event.connect(self.event_handler.execute_event)

            # # hook state events
            # evt_listener.state_event.connect(self.event_handler.execute_event)

            # set keyboard startup state for numlock - use global numlock or profile numlock
            # determine numlock state
            global_numlock_off = config.numlock_off

            profile_numlock_off = profile.get_force_numlock()
            profile_numlock_on = profile.get_force_numlock_on()
            if verbose:
                syslog.info(f"NumLock off state: global: {global_numlock_off}  profile off: {profile_numlock_off} profile on: {profile_numlock_on}")

            numlock_off = global_numlock_off or profile_numlock_off
            numlock_on = not global_numlock_off and not profile_numlock_off and profile_numlock_on

            if numlock_on:
                state = gremlin.keyboard.KeyMap.numlock_state()
                if verbose:
                    syslog.info(f"Numlock state: {state}")
                if not state:
                    # toggle numlock on
                    if verbose:
                        syslog.info("Numlock state: Forcing On")
                    gremlin.keyboard.KeyMap.toggle_numlock()

            elif numlock_off:
                state = gremlin.keyboard.KeyMap.numlock_state()
                if verbose:
                    syslog.info(f"Numlock state: {state}")
                if state:
                    # toggle numlock off
                    if verbose:
                        syslog.info("Numlock state: Forcing Off")
                    gremlin.keyboard.KeyMap.toggle_numlock()

            # monitor keyboard input state
            kb = gremlin.input_devices.Keyboard()
            evt_listener.keyboard_event.connect(kb.keyboard_event)

            # mark active
            evt_listener.gremlin_active = True

            # ensure remote gremlin client connected
            gremlin.remote.remote_server.start()
            gremlin.remote.remote_client.start()

            # listen to MIDI
            if config.midi_enabled:
                evt_listener.request_midi.emit(True)

            # listen to OSC
            if config.osc_enabled:
                evt_listener.request_osc.emit(True)

            # Stream Deck plugin bridge
            if config.streamdeck_enabled:
                from gremlin.ui import streamdeck_device as streamdeck_ui

                streamdeck_ui.ensure_bridge_started()

            # hook mode change callbacks
            evt_listener.runtime_mode_changed.connect(gremlin.input_devices.mode_registry.runtime_mode_changed)

            # hook state change callbacks
            evt_listener.broadcast_changed.connect(gremlin.input_devices.state_registry.state_changed)

            # call start functions
            gremlin.input_devices.start_registry.start()
            gremlin.input_devices.periodic_registry.start()

            gremlin.macro.MacroManager().start()
            verbose = gremlin.config.Configuration().verbose

            # determine the profile start mode

            mode = start_mode
            if config.restore_profile_mode_on_start or profile.get_restore_mode():
                # restore the profile mode
                mode = profile.get_last_runtime_mode()
                syslog.info(
                    f"PROFILE START: Restoring the last active profile mode for this profile: '{mode}' - overriding profile start mode '{start_mode}' at user request"
                )

                if mode:
                    if mode not in mode_list:
                        syslog.error(f"Unable to restore profile mode: '{mode}' no longer exists - using '{start_mode}' instead.")
                        mode = start_mode
            else:
                syslog.info(f"PROFILE START: Restoring the last active profile mode for this profile: '{mode}'")

            sendinput.MouseController().start()

            if mode not in mode_list:
                syslog.error(f"Unable to select startup mode: '{mode}' no longer exists")
                mode = profile.get_default_mode()  # start the default mode instead

            # tell listener profiles are starting
            evt_listener.start()

            self.event_handler.resume()

            ec.registerCallbacks(eh.callbacks)

            # apply global start values
            for vjoy_id, vjoy_input_id, value in profile.settings.get_initial_vjoy_axis_value_list():
                vs.setStartValue(vjoy_id, vjoy_input_id, value)

            # applies profile start data
            # this will override global settings
            for vjoy_device in gremlin.joystick_handling.virtual_devices():
                vjoy_device_guid = vjoy_device.device_guid
                vjoy_id = vjoy_device.vjoy_id
                for vjoy_input_id in range(1, vjoy_device.axis_count + 1):
                    if profile.getStartAxisEnabled(vjoy_device_guid, vjoy_input_id):
                        value = profile.getStartAxisValue(vjoy_id, vjoy_input_id)
                        vs.setStartValue(vjoy_id, vjoy_input_id, value)
                for vjoy_input_id in range(1, vjoy_device.button_count + 1):
                    state = profile.getStartButtonState(vjoy_device_guid, vjoy_input_id)
                    vs.setStartState(vjoy_id, vjoy_input_id, state)

            # hook profiles - this tells all functors to hook runtime events
            el.profile_hook.emit()

            # tell GremlinEx the profile started
            # this will also apply default start data and override prior data
            el.profile_start.emit()
            load_state = gremlin.shared_state.profile_state
            if load_state:
                # profile state ok = profile started correctly
                el.profile_started.emit()  # started event

                # multimode functor started call
                for functor in self._multimode_functors:
                    functor.profile_started()

                el.profile_after_start.emit()  # after start event

            # change to the start mode
            syslog.info(f"PROFILE START: Using profile start mode: '{mode}'")
            self.event_handler.change_mode(mode, force_update=True)  # force change to execute any startup triggers

            return load_state

        except Exception:
            tb_msg = traceback.format_exc()
            # re-enable tabs
            self.enableUI()
            syslog.error("Unable to launch profile:")

            syslog.error(f"Traceback: {tb_msg}")

            gremlin.util.display_error(f"Unable to launch profile due to an error: {tb_msg}")
            return False

    def stop(self):
        """Stops listening to events and unloads all callbacks."""

        # if self._sentry_timer is not None:
        #     self._sentry_timer.cancel()
        #     self._sentry_timer = None

        if not gremlin.shared_state.is_running:
            return  # not running - nothing to do

        el = gremlin.event_handler.EventListener()
        eh = gremlin.event_handler.EventHandler()

        # tell components we're stopping
        el.profile_stopping.emit()  # about to stop
        el.profile_stop.emit()  # stop

        # multimode functor stop
        for functor in self._multimode_functors:
            functor.profile_stop()

        # unhook vjoy debug data
        vjoy_debug = vjoy.VjoyDebug()
        vjoy_debug.UnHook()

        # stop remote client
        # gremlin.remote.remote_client.stop()
        # gremlin.remote.remote_server.stop()

        # call stop function in plugins
        gremlin.input_devices.stop_registry.start()
        gremlin.input_devices.stop_registry.stop()
        gremlin.input_devices.stop_registry.clear()
        gremlin.input_devices.mode_registry.clear()

        # reset functor latching
        container_plugins = gremlin.plugin_manager.ContainerPlugins()
        container_plugins.reset_functors()

        # Disconnect all signals

        kb = gremlin.input_devices.Keyboard()
        el.mouse_event.disconnect(self.event_handler.execute_event)
        el.keyboard_event.disconnect(self.event_handler.execute_event)
        el.joystick_event.disconnect(self.event_handler.execute_event)
        el.virtual_event.disconnect(self.event_handler.execute_event)
        el.midi_event.disconnect(self.event_handler.execute_event)
        el.osc_event.disconnect(self.event_handler.execute_event)
        try:
            el.streamdeck_event.disconnect(self.event_handler.execute_event)
        except Exception:
            pass
        # el.state_event.disconnect(self.event_handler.execute_event)

        el.keyboard_event.disconnect(kb.keyboard_event)
        el.gremlin_active = False
        # self.event_handler.runtime_mode_changed.disconnect(
        #     self._vjoy_curves.runtime_mode_changed
        # )

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

        # restore the startup mode and profile
        gremlin.shared_state.is_running = False
        gremlin.windows_event_hook.setRunning(False)

        if self._startup_profile and gremlin.shared_state.current_profile != self._startup_profile:
            eh.change_profile(self._startup_profile)
        # change back to edit mode
        edit_mode = gremlin.shared_state.edit_mode
        eh.change_mode(edit_mode, emit=True, force_update=False)

        # hook profiles - this tells all functors to unhook runtime events
        el.profile_unhook.emit()

        el.profile_stopped.emit()  # stopped

        # re-enable tabs
        self.enableUI()

        # reload UI
        el.request_ui_refresh.emit()

        # update mode
        el.edit_mode_ui_update.emit(edit_mode)

        # clear execution context
        ec = gremlin.execution_graph.ExecutionContext()
        ec.clear()

        # gc.collect()

    # def _handle_sentry(self):
    #     ''' sentry event '''

    #     syslog.info("Sentry event")
    #     gc.collect()
    #     self._sentry_timer = threading.Timer(self._sentry_tick, self._handle_sentry)
    #     self._sentry_timer.start()

    def _reset_state(self):
        """Resets all states to their default values."""
        first_node = self._inheritance_tree.children[0].name
        self.event_handler.active_mode = first_node
        self.event_handler.previous_mode = first_node
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
                for aid, data in device.modes[mode_name].config[InputType.JoystickAxis].items():
                    # Get integer axis id in case an axis enum was used
                    axis_id = vjoy_module.vjoy.VJoy.axis_equivalence.get(aid, aid)
                    vjoy_id = gremlin.joystick_handling.vjoy_id_from_guid(guid)

                    if len(data.containers) > 0 and vjoy_id in vjoy and vjoy[vjoy_id].is_axis_valid(axis_id):
                        action = data.containers[0].action_sets[0][0]
                        if hasattr(action, "deadzone"):
                            vjoy[vjoy_id].axis(aid).set_deadzone(*action.deadzone)
                        vjoy[vjoy_id].axis(aid).set_response_curve(action.mapping_type, action.control_points)


class MergeAxis:
    """Merges inputs from two distinct axes into a single one."""

    def __init__(self, vjoy_id: int, input_id: int, operation: gremlin.types.MergeAxisOperation):
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
            value = gremlin.util.clamp(self.axis_values[0] + self.axis_values[1], -1.0, 1.0)
        else:
            raise gremlin.error.GremlinError(f'Invalid merge axis operation detected, "{str(self.operation)}"')

        gremlin.joystick_handling.VJoyProxy()[self.vjoy_id].axis(self.input_id).value = value

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
