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

import json
import logging
import time
import os
import re
import sys

from PySide6 import QtCore
import gremlin.base_classes
import gremlin.event_handler
import gremlin.input_types
import gremlin.joystick_handling
import gremlin.shared_state
from gremlin.types import VerboseMode
import gremlin.types
import gremlin.util


import gremlin.singleton_decorator
@gremlin.singleton_decorator.SingletonDecorator
class Configuration:

    """Responsible for loading and saving configuration data."""

    def get_config(sef):
        fname = os.path.join(gremlin.util.userprofile_path(), "config.json")
        return fname
    
    def get_profile_config(self):
        ''' profile specific config file '''
        if self._profile_fname:
            fname, ext = os.path.splitext(self._profile_fname)
            return fname + ".json"
        return None

    def __init__(self):
        """Creates a new instance, loading the current configuration."""

        self._data = {} # gremlin items 
        self._profile_data = {}  # profile specific options 
        self._profile_loaded = False
        self._profile_fname = None # current profile to use for the conig
        self._profile_config_fname = None # config file specific to the profile



        self._midi_enabled = None
        self._osc_enabled = None

        fname = self.get_config()
        if not os.path.isfile(fname):
            # create a stub - first time run
            self.save()

            
        gettrace = getattr(sys, 'gettrace', None)
        frozen = getattr(sys, 'frozen', False)
        if frozen:
            self._is_debug = False
        else:
            self._is_debug = gettrace is not None

        
        self._last_reload = None
        self._last_profile_reload = None
        self.reload()



        self.watcher = QtCore.QFileSystemWatcher([
            os.path.join(gremlin.util.userprofile_path(), "config.json")
        ])
        
        self.watcher.fileChanged.connect(self.reload)
        

    
  
        
    


    def reload(self):
        """Loads the configuration file's content."""
        if self._last_reload is not None and \
                time.time() - self._last_reload < 1:
            return

        fname = self.get_config()
        # Attempt to load the configuration file if this fails set
        # default empty values.
        load_successful = False
        if os.path.isfile(fname):
            with open(fname) as hdl:
                try:
                    decoder = json.JSONDecoder()
                    self._data = decoder.decode(hdl.read())
                    load_successful = True
                except ValueError:
                    pass
        if not load_successful:
            self._data = {
                "calibration": {},
                "profiles": {},
                "last_mode": {}
            }

        # Ensure required fields are present and if they are missing
        # add empty ones.
        for field in ["calibration", "profiles", "last_mode"]:
            if field not in self._data:
                self._data[field] = {}

        # Save all data
        self._last_reload = time.time()
        self.save()

    def reload_profile(self):
        """Loads the profile's configuration file's content."""
        if self._last_profile_reload is not None and \
                time.time() - self._last_profile_reload < 1:
            return
        
        self._profile_data = {}

        fname = self._profile_config_fname
        if not fname:
            return # nothing to load
        

        
        # Attempt to load the configuration file if this fails set
        # default empty values.
        if os.path.isfile(fname):
            with open(fname) as hdl:
                try:
                    decoder = json.JSONDecoder()
                    self._profile_data = decoder.decode(hdl.read())
                    load_successful = True
                except ValueError:
                    pass

        # Save all data
        self._last_profile_reload = time.time()
        self.save_profile()


    def save(self):
        """Writes the configuration file to disk."""
        fname = self.get_config()
        with open(fname, "w") as hdl:
            encoder = json.JSONEncoder(
                sort_keys=True,
                indent=4
            )
            hdl.write(encoder.encode(self._data))


    def save_profile(self):
        ''' saves to the profile specific config file '''
        fname = self._profile_config_fname
        if fname:
            with open(fname, "w") as hdl:
                encoder = json.JSONEncoder(
                    sort_keys=True,
                    indent=4
                )
                hdl.write(encoder.encode(self._profile_data))

    
    @property
    def is_debug(self):
        return self._is_debug
    
    def set_last_runtime_mode(self, profile_path, mode_name):
        """Stores the last active mode of the given profile.

        :param profile_path profile path for which to store the mode
        :param mode_name name of the active mode
        """
        if profile_path is None or mode_name is None:
            return
        
        profile_path = os.path.normpath(profile_path).casefold()
        item = self._data.get("last_mode", None)
        if not item:
            self._data["last_mode"] = {}
        self._data["last_mode"][profile_path] = mode_name
        syslog = logging.getLogger("system")
        syslog.info(f"CONFIG: storing last runtime profile mode: [{mode_name}] for profile [{os.path.basename(profile_path)}]")
        self.save()

    def get_last_runtime_mode(self, profile_path):
        """Returns the last active mode of the given profile.

        :param profile_path profile path for which to return the mode
        :return name of the mode if present, None otherwise
        """
        profile_path = os.path.normpath(profile_path).casefold()
        item = self._data.get("last_mode", None)
        if not item:
            return None
        if profile_path in item:
            return item[profile_path]
        return None
    

    def set_last_edit_mode(self, profile_path, mode_name):
        """Stores the last active mode of the given profile.

        :param profile_path profile path for which to store the mode
        :param mode_name name of the active mode
        """
        if profile_path is None or mode_name is None:
            return
        
        profile_path = os.path.normpath(profile_path).casefold()
        item = self._data.get("last_edit_mode", None)
        if not item:
            self._data["last_edit_mode"] = {}
        self._data["last_edit_mode"][profile_path] = mode_name
        self.save()

    def get_last_edit_mode(self, profile_path):
        """Returns the last active mode of the given profile.

        :param profile_path profile path for which to return the mode
        :return name of the mode if present, None otherwise
        """
        
        profile_path = os.path.normpath(profile_path).casefold()
        item = self._data.get("last_edit_mode", None)
        if not item:
            return None
        if profile_path in item:
            return item[profile_path]
        return None

    def set_profile_last_runtime_mode(self, mode_name):
        ''' sets the profile's last used mode '''
        fname = self.last_profile
        if fname:
            self.set_last_runtime_mode(fname, mode_name)

    def get_profile_last_runtime_mode(self):
        ''' gets the save last used profile mode '''
        fname = self.last_profile
        if fname:
            return self.get_last_runtime_mode(fname)
        return None
    
    def set_profile_last_edit_mode(self, mode_name):
        ''' sets the profile's last used mode '''
        fname = self.last_profile
        if fname:
            self.set_last_edit_mode(fname, mode_name)

    def get_profile_last_edit_mode(self):
        ''' gets the save last used profile mode '''
        fname = self.last_profile
        if fname:
            return self.get_last_edit_mode(fname)
        return None
    
    
    @property
    def initial_load_mode_tts(self):
        ''' if set, JGEX outputs a verbal readout of the current mode on profile load '''
        return self._data.get("initial_load_mode_tts", True)
    
    @initial_load_mode_tts.setter
    def initial_load_mode_tts(self, value):
        self._data["initial_load_mode_tts"] = value
        self.save()

    @property
    def runtime_ui_update(self):
        ''' if set, JGEX will update the UI when a profile is activated '''
        return self._data.get("runtime_ui_update", False)
    
    @runtime_ui_update.setter
    def runtime_ui_update(self, value):
        self._data["runtime_ui_update"] = value
        self.save()


    @property
    def reset_mode_on_process_activate(self):
        ''' if set, the mode is reset when the process is reactivated to the default mode '''
        return self._data.get("reset_mode_on_process_activate", False)
    
    @reset_mode_on_process_activate.setter
    def reset_mode_on_process_activate(self, value):
        self._data["reset_mode_on_process_activate"] = value
        self.save()

    def set_calibration(self, dev_id, limits):
        """Sets the calibration data for all axes of a device.

        :param dev_id the id of the device
        :param limits the calibration data for each of the axes
        """
        identifier = str(dev_id)
        if identifier in self._data["calibration"]:
            del self._data["calibration"][identifier]
        self._data["calibration"][identifier] = {}

        for i, limit in enumerate(limits):
            if limit[2] - limit[0] == 0:
                continue
            axis_name = f"axis_{i+1}"
            self._data["calibration"][identifier][axis_name] = [
                limit[0], limit[1], limit[2]
            ]
        self.save()

    def get_calibration(self, dev_id, axis_id):
        """Returns the calibration data for the desired axis.

        :param dev_id the id of the device
        :param axis_id the id of the desired axis
        :return the calibration data for the desired axis
        """
        identifier = str(dev_id)
        axis_name = f"axis_{axis_id}"
        if identifier not in self._data["calibration"]:
            return [-32768, 0, 32767]
        if axis_name not in self._data["calibration"][identifier]:
            return [-32768, 0, 32767]

        return self._data["calibration"][identifier][axis_name]
    
    # @property
    # def legacy_calibration_imported(self)->bool:
    #     return self._data.get("legacy_calibration_imported",False)
    
    # @legacy_calibration_imported.setter
    # def legacy_calibration_imported(self, value : bool):
    #     self._data["legacy_calibration_imported"] = value
    

    @property
    def last_options_tab(self):
        ''' index of the last option tab selected'''
        key = "last_options_tab"
        if key in self._data.keys():
            index = self._data[key]
        else:
            index = 0
        return index
    
    @last_options_tab.setter
    def last_options_tab(self, value):
        self._data["last_options_tab"] = value
        self.save()
    


    def get_executable_list(self):
        """Returns a list of all executables with associated profiles.

        :return list of executable paths
        """
        return list(sorted(
            self._data["profiles"].keys(),
            key=lambda x: x.lower())
        )

    def remove_profile(self, exec_path):
        """Removes the executable from the configuration.

        :param exec_path the path to the executable to remove
        """
        if self._has_profile(exec_path):
            del self._data["profiles"][exec_path]
            self.save()

    def get_profile(self, exec_path):
        """Returns the path to the profile associated with the given executable.

        :param exec_path the path to the executable for which to
            return the profile
        :return profile associated with the given executable
        """
        return self._data["profiles"].get(exec_path, None)

    def get_profile_with_regex(self, exec_path):
        """Returns the path to the profile associated with the given executable.

        This considers all path entries that do not resolve to an actual file
        in the system as a regular expression. Regular expressions will be
        searched in order after true files have been checked.

        :param exec_path the path to the executable for which to
            return the profile
        :return profile associated with the given executable
        """
        # Handle the normal case where the path matches directly
        profile_path = self.get_profile(exec_path)
        if profile_path is not None:
            logging.getLogger("system").info(
                f"Found exact match for {exec_path}, returning {profile_path}"
            )
            return profile_path

        # Handle non files by treating them as regular expressions, returning
        # the first successful match.
        for key, value in sorted(
                self._data["profiles"].items(),
                key=lambda x: x[0].lower()
        ):
            # Ignore valid files
            if os.path.exists(key):
                continue

            # Treat key as regular expression and attempt to match it to the
            # provided executable path
            if re.search(key, exec_path) is not None:
                logging.getLogger("system").info(
                    f"Found regex match in {key} for {exec_path}, returning {value}"
                )
                return value

    def set_profile(self, exec_path, profile_path):
        """Stores the executable and profile combination.

        :param exec_path the path to the executable
        :param profile_path the path to the associated profile
        """
        self._data["profiles"][exec_path] = profile_path
        self.save()

    
    def set_start_mode(self, profile_path, mode_name):
        """Stores the last active mode of the given profile.

        :param profile_path profile path for which to store the mode
        :param mode_name name of the active mode
        """
        if profile_path is None or mode_name is None:
            return
        self._data["start_mode"][profile_path] = mode_name
        self.save()

    def get_start_mode(self, profile_path):
        """Returns the last active mode of the given profile.

        :param profile_path profile path for which to return the mode
        :return name of the mode if present, None otherwise
        """
        return self._data["start_mode"].get(profile_path, None)


    def _has_profile(self, exec_path):
        """Returns whether or not a profile exists for a given executable.

        :param exec_path the path to the executable
        :return True if a profile exists, False otherwise
        """
        return exec_path in self._data["profiles"]

    @property
    def last_profile(self):
        """Returns the last used profile.

        :return path to the most recently used profile
        """
        return self._data.get("last_profile", None)

    @last_profile.setter
    def last_profile(self, value):
        """Sets the last used profile.

        :param value path to the most recently used profile
        """
        self._data["last_profile"] = value

        # Update recent profiles
        if value is not None:
            value = os.path.normpath(value.casefold()) # normalize the profile path
            current = self.recent_profiles
            if value in current:
                del current[current.index(value)]
            current.insert(0, value)
            # normalize and remove duplicates
            current = list(set([os.path.normpath(item.casefold()) for item in current]))
            current = current[0:14] # remember up to 15

            
            self._data["recent_profiles"] = current
        self.save()

    @property
    def recent_profiles(self):
        """Returns a list of recently used profiles.

        :return list of recently used profiles
        """
        return self._data.get("recent_profiles", [])

    @property
    def autoload_profiles(self):
        """Returns whether or not to automatically load profiles.

        This enables / disables the process based profile autoloading.

        :return True if auto profile loading is active, False otherwise
        """
        return self._data.get("autoload_profiles", False)

    @autoload_profiles.setter
    def autoload_profiles(self, value):
        """Sets whether or not to automatically load profiles.

        This enables / disables the process based profile autoloading.

        :param value Flag indicating whether or not to enable / disable the
            feature
        """
        if type(value) == bool:
            self._data["autoload_profiles"] = value
            self.save()
            el = gremlin.event_handler.EventListener()
            el.process_monitor_changed.emit() # tell the UI the parameter changed

    @property
    def keep_profile_active_on_focus_loss(self):
        return self._data.get("keep_active_on_focus_loss",True)
    @keep_profile_active_on_focus_loss.setter
    def keep_profile_active_on_focus_loss(self, value):
        self._data["keep_active_on_focus_loss"] = value
        self.save()

    @property
    def keep_last_autoload(self):
        """Returns whether or not to keep last autoloaded profile active when it would otherwise
        be automatically disabled.

        This setting prevents unloading an autoloaded profile when not changing to another one.

        :return True if last profile keeping is active, False otherwise
        """
        return self._data.get("keep_last_autoload", False)

    @keep_last_autoload.setter
    def keep_last_autoload(self, value):
        """Sets whether or not to keep last autoloaded profile active when it would otherwise
        be automatically disabled.

        This setting prevents unloading an autoloaded profile when not changing to another one.

        :param value Flag indicating whether or not to enable / disable the
            feature
        """
        assert isinstance(value, bool)
        self._data["keep_last_autoload"] = value
        self.save()

    
    @property
    def restore_profile_mode_on_start(self):
        ''' determines if a profile mode, if it exists is restored when the profile is activated '''
        return self._data.get("restore_mode_on_start", False)
    
    @restore_profile_mode_on_start.setter
    def restore_profile_mode_on_start(self, value):
        self._data["restore_mode_on_start"] = value
        self.save()

    @property
    def highlight_autoswitch(self):
        ''' true if in design mode and tab switching is allowed on input detect change '''
        return self._data.get("highlight_switch", False)
    @highlight_autoswitch.setter
    def highlight_autoswitch(self, value):
        self._data["highlight_switch"] = value
        self.save()


    @property
    def highlight_input_axis(self):
        """Returns whether or not to highlight inputs for an axis

        This enables / disables the feature where using a physical input
        automatically selects it in the UI.

        :return True if the feature is enabled, False otherwise
        """
        return self._data.get("highlight_input_axis", False)

    @highlight_input_axis.setter
    def highlight_input_axis(self, value):
        """Sets whether or not to highlight inputs for an axis

        This enables / disables the feature where using a physical input
        automatically selects it in the UI.

        :param value Flag indicating whether or not to enable / disable the
            feature
        """
        if type(value) == bool:
            self._data["highlight_input_axis"] = value
            self.save()

    @property
    def highlight_input_buttons(self):
        """Returns whether or not to highlight inputs for a button

        This enables / disables the feature where using a physical input
        automatically selects it in the UI.

        :return True if the feature is enabled, False otherwise
        """
        return self._data.get("highlight_input_buttons", True)

    @highlight_input_buttons.setter
    def highlight_input_buttons(self, value):
        """Sets whether or not to highlight inputs for a button 

        This enables / disables the feature where using a physical input
        automatically selects it in the UI.

        :param value Flag indicating whether or not to enable / disable the
            feature
        """
        if type(value) == bool:
            self._data["highlight_input_buttons"] = value
            self.save()


    @property
    def highlight_enabled(self):
        """Returns whether or not highlighting swaps device tabs.

        This enables / disables the feature where using a physical input
        automatically swaps to the correct device tab.

        :return True if the feature is enabled, False otherwise
        """
        return self._data.get("highlight_device", False)

    @highlight_enabled.setter
    def highlight_enabled(self, value) -> bool:
        """Sets whether or not to swap device tabs to highlight inputs.

        This enables / disables the feature where using a physical input
        automatically swaps to the correct device tab.

        :param value Flag indicating whether or not to enable / disable the
            feature
        """
        if type(value) == bool:
            self._data["highlight_device"] = value
            self.save()

    @property
    def highlight_hotkey_autoswitch(self):
        ''' when enabled - pressing the control or shift hotkeys to toggle axis / button highlight also allows tab switch '''
        return self._data.get("highlight_hotkey_autoswitch", False)
    
    @highlight_hotkey_autoswitch.setter
    def highlight_hotkey_autoswitch(self, value : bool):
        self._data["highlight_hotkey_autoswitch"] = value


    @property
    def enable_remote_control(self):
        ''' enables or disables remote control from another gremlin instance on the network '''
        return self._data.get("allow_remote_control",False)
    
    @enable_remote_control.setter
    def enable_remote_control(self, value):
        if type(value) == bool:
            self._data["allow_remote_control"] = value
            self.save()

    @property
    def enable_remote_broadcast(self):
        ''' enables gremlin to broadcast control changes over UDP multicast '''
        return self._data.get("enable_remote_broadcast",False)

    @enable_remote_broadcast.setter
    def enable_remote_broadcast(self, value):
        ''' remote broadcast master switch enable '''
        import gremlin.event_handler
        if type(value) == bool and self._data.get("enable_remote_broadcast",False)!= value:
            self._data["enable_remote_broadcast"] = value
            self.save()

            eh = gremlin.event_handler.EventListener()
            eh.config_changed.emit()

    @property
    def enable_broadcast_speech(self):
        ''' speech on broadcast change mode enable'''
        return self._data.get("enable_broadcast_speech",True)
    
    @enable_broadcast_speech.setter
    def enable_broadcast_speech(self, value):

        if type(value) == bool and self._data.get("enable_broadcast_speech",True) != value:
            self._data["enable_broadcast_speech"] = value
            self.save()




    @property
    def server_port(self):
        ''' port number to use for the gremlin server '''
        return self._data.get("server_port",6012)
    
    @server_port.setter
    def server_port(self, value):
        if type(value) == float:
            value = int(value)
        elif type(value) == str and value.isnumeric():
            value = int(value)

        if type(value) == int:
            self._data["server_port"] = value
            self.save()

    @property
    def mode_change_message(self):
        """Returns whether or not to show a windows notification on mode change.

        :return True if the feature is enabled, False otherwise
        """
        return self._data.get("mode_change_message", False)

    @mode_change_message.setter
    def mode_change_message(self, value):
        """Sets whether or not to show a windows notification on mode change.

        :param value True to enable the feature, False to disable
        """
        self._data["mode_change_message"] = bool(value)
        self.save()

    @property
    def activate_on_launch(self):
        """Returns whether or not to activate the profile on launch.

        :return True if the profile is to be activate on launch, False otherwise
        """
        return self._data.get("activate_on_launch", False)

    @activate_on_launch.setter
    def activate_on_launch(self, value):
        """Sets whether or not to activate the profile on launch.

        :param value aactivate profile on launch if True, or not if False
        """
        self._data["activate_on_launch"] = bool(value)
        self.save()


    @property
    def activate_on_process_focus(self):
        """Returns whether or not to activate the profile on process focus."""
        return self._data.get("activate_on_process_focus", False)

    @activate_on_process_focus.setter
    def activate_on_process_focus(self, value):
        """Sets whether or not to activate the profile on launch."""
        self._data["activate_on_process_focus"] = bool(value)
        self.save()
        el = gremlin.event_handler.EventListener()
        el.process_monitor_changed.emit() # tell the UI the process options changed



    @property
    def close_to_tray(self):
        """Returns whether or not to minimze the application when closing it.

        :return True if closing minimizes to tray, False otherwise
        """
        return self._data.get("close_to_tray", False)

    @close_to_tray.setter
    def close_to_tray(self, value):
        """Sets whether or not to minimize to tray instead of closing.

        :param value minimize to tray if True, close if False
        """
        self._data["close_to_tray"] = bool(value)
        self.save()

    @property
    def start_minimized(self):
        """Returns whether or not to start Gremlin minimized.

        :return True if starting minimized, False otherwise
        """
        return self._data.get("start_minimized", False)

    @start_minimized.setter
    def start_minimized(self, value):
        """Sets whether or not to start Gremlin minimized.

        :param value start minimized if True and normal if False
        """
        self._data["start_minimized"] = bool(value)
        self.save()

    @property
    def default_action(self):
        """Returns the default action to show in action drop downs.

        :return default action to show in action selection drop downs
        """
        return self._data.get("default_action", "Remap")

    @default_action.setter
    def default_action(self, value):
        """Sets the default action to show in action drop downs.

        :param value the name of the default action to show
        """
        self._data["default_action"] = str(value)
        self.save()

    @property
    def last_action(self):
        """Returns the default action to show in action drop downs.

        :return default action to show in action selection drop downs
        """
        return self._data.get("last_action", Configuration().default_action)
    
    @last_action.setter
    def last_action(self, value):
        """Sets the default action to show in action drop downs.

        :param value the name of the default action to show
        """
        self._data["last_action"] = str(value)
        self.save()

    @property
    def last_container(self):
        """Returns the last container to show in container drop downs."""
        return self._data.get("last_container", "basic")
    
    @last_container.setter
    def last_container(self, value):
        """Sets the last container to show in container drop downs.

        :param value the name of the default container to show
        """
        self._data["last_container"] = str(value)
        self.save()


    @property
    def macro_axis_polling_rate(self):
        """Returns the polling rate to use when recording axis macro actions.

        :return polling rate to use when recording a macro with axis inputs
        """
        return self._data.get("macro_axis_polling_rate", 0.1)

    @macro_axis_polling_rate.setter
    def macro_axis_polling_rate(self, value):
        self._data["macro_axis_polling_rate"] = value
        self.save()

    @property
    def macro_axis_minimum_change_rate(self):
        """Returns the minimum change in value required to record an axis event.

        :return minimum axis change required
        """
        return self._data.get("macro_axis_minimum_change_rate", 0.005)

    @macro_axis_minimum_change_rate.setter
    def macro_axis_minimum_change_rate(self, value):
        self._data["macro_axis_minimum_change_rate"] = value
        self.save()

    @property
    def macro_record_axis(self):
        return self._data.get("macro_record_axis", False)

    @macro_record_axis.setter
    def macro_record_axis(self, value):
        self._data["macro_record_axis"] = bool(value)
        self.save()

    @property
    def macro_record_button(self):
        return self._data.get("macro_record_button", True)

    @macro_record_button.setter
    def macro_record_button(self, value):
        self._data["macro_record_button"] = bool(value)
        self.save()

    @property
    def macro_record_hat(self):
        return self._data.get("macro_record_hat", True)

    @macro_record_hat.setter
    def macro_record_hat(self, value):
        self._data["macro_record_hat"] = bool(value)
        self.save()

    @property
    def macro_record_keyboard(self):
        return self._data.get("macro_record_keyboard", True)

    @macro_record_keyboard.setter
    def macro_record_keyboard(self, value):
        self._data["macro_record_keyboard"] = bool(value)
        self.save()

    @property
    def macro_record_mouse(self):
        return self._data.get("macro_record_mouse", False)

    @macro_record_mouse.setter
    def macro_record_mouse(self, value):
        self._data["macro_record_mouse"] = bool(value)
        self.save()

    @property
    def window_size(self):
        """Returns the size of the main Gremlin window.

        :return size of the main Gremlin window
        """
        return self._data.get("window_size", None)

    @window_size.setter
    def window_size(self, value):
        """Sets the size of the main Gremlin window.

        :param value the size of the main Gremlin window
        """
        self._data["window_size"] = value
        self.save()

    @property
    def window_location(self):
        """Returns the position of the main Gremlin window.

        :return position of the main Gremlin window
        """
        return self._data.get("window_location", None)

    @window_location.setter
    def window_location(self, value):
        """Sets the position of the main Gremlin window.

        :param value the position of the main Gremlin window
        """
        self._data["window_location"] = value
        self.save()


    @property
    def persist_clipboard(self):
        ''' true if clipboard data is persisted from one session to the next '''
        return self._data.get("persist_clipboard", False)
    
    @persist_clipboard.setter
    def persist_clipboard(self, value):
        self._data["persist_clipboard"] = value
        self.save()

        if not value:
            # remove from disk any old data
            from gremlin.clipboard import Clipboard
            clipboard = Clipboard()
            clipboard.clear_persisted()

    @property
    def verbose(self):
        ''' determines loging level '''
        value = self._data.get("verbose", None)
        if value is None:
            # not set - set other defaults
            self._data["verbose_mode"] = 0
            self._data["verbose"] = False
            return False
        return value

    @verbose.setter
    def verbose(self, value):
        self._data["verbose"] = value
        self.save()

    @property
    def verbose_mode(self):
        ''' sub logging level '''
        if not "verbose_mode" in self._data:
            self._data["verbose_mode"] = VerboseMode.All
            self.save()
        return VerboseMode(self._data["verbose_mode"])
    
    def is_verbose_mode(self, mode):
        value = self.verbose_mode
        result = mode in value
        return result
    
    @verbose_mode.setter
    def verbose_mode(self, value):
        self._data["verbose_mode"] = value
        self.save()

    def verbose_set_mode(self, mode, enabled):
        ''' enables the specified verbose mode '''
        if not "verbose_mode" in self._data:
            self._data["verbose_mode"] = 0 # none
        value = self._data["verbose_mode"]
        if enabled:
            value |= mode
        else:
            value = value & ~mode
        self.verbose_mode = value
        



    @property
    def verbose_mode_keyboard(self):
        ''' true if verbose mode is in keyboard mode '''
        return self.verbose and VerboseMode.Keyboard in self.verbose_mode
    
    @property
    def verbose_mode_joystick(self):
        ''' true if verbose mode is in joystick mode '''
        return self.verbose and VerboseMode.Joystick in self.verbose_mode
    
    @property
    def verbose_mode_inputs(self):
        ''' true if verbose mode is in inputs mode '''
        return self.verbose and VerboseMode.Inputs in self.verbose_mode

    @property
    def verbose_mode_mouse(self):
        ''' true if verbose mode is in inputs mode '''
        return self.verbose and VerboseMode.Mouse in self.verbose_mode
    
    @property
    def verbose_mode_details(self):
        ''' true if verbose mode is in inputs mode '''
        return self.verbose and VerboseMode.Details in self.verbose_mode
    
    @property
    def verbose_mode_detailed(self):
        ''' true if verbose mode is in inputs mode '''
        return self.verbose and VerboseMode.Details in self.verbose_mode

    @property
    def verbose_mode_simconnect(self):
        ''' true if verbose mode is in simconnect mode '''
        return self.verbose and VerboseMode.SimConnect in self.verbose_mode
    
    @property
    def verbose_mode_condition(self):
        ''' true if verbose mode is in condition/execution mode '''
        return self.verbose and VerboseMode.Condition in self.verbose_mode
    
    @property
    def verbose_mode_execution(self):
        ''' true if verbose mode is in condition/execution mode '''
        return self.verbose and VerboseMode.Condition in self.verbose_mode
    
    @property
    def verbose_mode_osc(self):
        ''' true if verbose mode is in OSC mode '''
        return self.verbose and VerboseMode.OSC in self.verbose_mode
    
    @property
    def verbose_mode_process(self):
        ''' true if verbose mode is in OSC mode '''
        return self.verbose and VerboseMode.Process in self.verbose_mode
    
    @property
    def verbose_mode_exec(self):
        ''' true if verbose mode is in Exec(ute) mode '''
        return self.verbose and VerboseMode.Exec in self.verbose_mode
    
    @property
    def midi_enabled(self):
        ''' true if MIDI module is enabled '''
        return self._data.get("midi_enabled", True)
    
    @midi_enabled.setter
    def midi_enabled(self, value):
        self._data["midi_enabled"] = value
        self.save()

    @property
    def osc_enabled(self):
        ''' true if osc module is enabled '''
        return self._data.get("osc_enabled", True)
    
    @osc_enabled.setter
    def osc_enabled(self, value):
        self._data["osc_enabled"] = value
        self.save()

    @property
    def osc_port(self):
        ''' OSC listen port '''
        port = self._data.get("osc_port", 8000)
        return port
    @osc_port.setter
    def osc_port(self, value):
        self._data["osc_port"] = value
        self.save()

    @property
    def osc_output_port(self):
        ''' OSC listen port '''
        port = self._data.get("osc_output_port", 8001)
        return port
    @osc_output_port.setter
    def osc_output_port(self, value):
        self._data["osc_output_port"] = value
        self.save()
    
    @property
    def osc_host(self):
        ''' OSC client host (this is the IP the client sends OSC data to)'''
        host = self._data.get("osc_host", "127.0.0.1")
        return host
    
    @osc_host.setter
    def osc_host(self, value : str):
        self._data["osc_host"] = value
        self.save()

    @property
    def show_scancodes(self):
        ''' hide/show scan codes for keyboard related inputs '''
        return self._data.get("show_scancodes", False)
    
    @show_scancodes.setter
    def show_scancodes(self, value):
        self._data["show_scancodes"] = value
        self.save()

    @property
    def show_input_axis(self):
        ''' shows input axis values for axis inputs '''
        return self._data.get("show_input_axis",True)
    
    @show_input_axis.setter
    def show_input_axis(self, value):
        self._data["show_input_axis"] = value
        self.save()




    @property
    def tab_list(self):
        ''' tab order for the UI devices as set by the user '''
        return self._data.get("tab_order", None)
    @tab_list.setter
    def tab_list(self, value):
        self._data["tab_order"] = value
        self.save()

    @property
    def show_output_vjoy(self):
        ''' determines if VJOY output devices are displayed on the device tabs '''
        return self._data.get("show_vjoy_ouput", False)
    @show_output_vjoy.setter
    def show_output_vjoy(self, value):
        self._data["show_vjoy_output"] = value
        self.save()

    @property
    def last_plugin_folder(self):
        ''' last folder used for plugins '''
        return self._data.get("last_plugin_folder",None)
    @last_plugin_folder.setter
    def last_plugin_folder(self, value):
        self._data["last_plugin_folder"]=value
        self.save()

    @property
    def last_sound_folder(self):
        ''' last folder used for sounds '''
        return self._data.get("last_sound_folder",None)
    @last_sound_folder.setter
    def last_sound_folder(self, value):
        self._data["last_sound_folder"] = value
        self.save()
           
    @property
    def partial_plugin_save(self):
        ''' true if partial plugin configuration saving is ok = false nothing will be saved - true partial values will be saved '''
        return self._data.get("partial_plugin_init_ok",True)
    
    @partial_plugin_save.setter
    def partial_plugin_save(self, value):
        self._data["partial_plugin_init_ok"] = value
        self.save()


    @property
    def runtime_ui_active(self):
        ''' keep UI enabled at runtime '''
        return self._data.get("runtime_ui_active",False)
    
    @runtime_ui_active.setter
    def runtime_ui_active(self, value):
        self._data["runtime_ui_active"] = value
        self.save()

    @property
    def sync_last_selection(self):
        ''' synchronizes the actions and container drop downs when enabled '''
        return self._data.get("sync_last_selection",True)
    
    @sync_last_selection.setter
    def sync_last_selection(self, value):
        self._data["sync_last_selection"] = value
        self.save()
        

    @property
    def last_keyboard_mapper_pulse_value(self):
        return self._data.get("last_keyboard_mapper_pulse_value", 250)
    @last_keyboard_mapper_pulse_value.setter
    def last_keyboard_mapper_pulse_value(self, value):
        self._data["last_keyboard_mapper_pulse_value"] = value
        self.save()


    @property
    def last_keyboard_mapper_interval_value(self):
        return self._data.get("last_keyboard_mapper_interval_value", 250)
    @last_keyboard_mapper_interval_value.setter
    def last_keyboard_mapper_interval_value(self, value):
        self._data["last_keyboard_mapper_interval_value"] = value
        self.save()

    @property
    def runtime_ignore_device_change(self):
        ''' ignore device changes at runtime '''
        return self._data.get("runtime_ignore_device_change", True)
    @runtime_ignore_device_change.setter
    def runtime_ignore_device_change(self, value):
        self._data["runtime_ignore_device_change"] = value
        self.save()


    @property
    def vigem_device_count(self):
        ''' count of gamepads to create for VIGEM - default is 1 '''
        return self._data.get("vigem_device_count",1)
    @vigem_device_count.setter
    def vigem_device_count(self, value):
        if value < 0:
            value = 0
        elif value > 3:
            value = 3
        self._data["vigem_device_count"] = value
        self.save()

    @property
    def import_level(self):
        ''' import mapping expansion level 0 to 4 '''
        return self._data.get("import_level",1)

    @import_level.setter
    def import_level(self, value):
        self._data["import_level"] = value
        self.save()


    @property
    def import_window_location(self):
        """Returns the position of the import profile """
        return self._data.get("import_window_location", None)

    @import_window_location.setter
    def import_window_location(self, value):
        """Sets the position of the import profile window """
        self._data["import_window_location"] = value
        self.save()

    @property
    def last_device_guid(self):
        ''' gets the last selected device guid'''
        device_guid = self._profile_data.get("last_device_guid", None)  # try the profile specific config first
        if not device_guid:
            device_guid = self._data.get("last_device_guid", None)
        return device_guid
    
    @property
    def last_dinput_device_guid(self):
        ''' last device guid as a dinput GUID instead of a string '''
        guid = self.last_device_guid
        if guid:
            return gremlin.util.parse_guid(guid)
        return None
    
    @last_device_guid.setter
    def last_device_guid(self, device_guid):
        ''' stores the last device GUID '''
        device_guid = str(device_guid)
        self._data["last_device_guid"] = device_guid # general config 
        self._profile_data["last_device_guid"] = device_guid # profile specific config
        self.save()
        self.save_profile()

    def set_last_input(self, device_guid, input_type : gremlin.input_types.InputType, input_id ):
        ''' stores the last input '''
        if gremlin.shared_state.is_tab_loading:
            # don't save while tabs are loading
            return 
        
        el = gremlin.event_handler.EventListener()
        if el.input_selection_suspended:
            # ignore selection requests if selection is suspended
            return

        
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        data : dict = self._profile_data.get("last_input", {})
        
        verbose = self.verbose_mode_details
        # verbose = True
        if verbose:
            syslog = logging.getLogger("system") 
        
        if input_type != gremlin.input_types.InputType.ModeControl and isinstance(input_id, gremlin.base_classes.AbstractInputItem):
            # convert to an ID we can use
            input_id = input_id.guid
        elif input_id is None:
            # no data is ok
            pass
        elif isinstance(input_id, int):
            pass
        elif isinstance(input_id, str):
            if input_id.isnumeric():
                input_id = int(input_id)
            else:
                guid = gremlin.util.parse_guid(input_id)
                if guid is not None:
                    input_id = str(guid)
                else:
                    syslog.warning(f"SetLastInput(): Don't know how to handle input_id [{input_id}] type: {type(input_id).__name__}")
                    input_id = None
        else:
            syslog.warning(f"SetLastInput(): Don't know how to handle input_id [{input_id}] type: {type(input_id).__name__}")
            input_id = None

        input_type = gremlin.input_types.InputType.convert(input_type)
        if input_type is not None:
            data[device_guid] = (input_type, input_id)

            self._profile_data["last_input"] = data
            self._data["last_device_guid"] = device_guid
            self._profile_data["last_device_guid"] = device_guid
        
            self.save_profile()

            if verbose:
                device_name = gremlin.shared_state.get_device_name(device_guid)
                syslog.info(f"Saving last input selection: {device_guid} {device_name} {input_type} {input_id}")
                pass



    def get_last_device_guid(self):
        ''' gets the last selected device in the profile '''
        device_guid = self._profile_data.get("last_device_guid",None)
        if device_guid is None:
            device_guid = self._data.get("last_device_guid",None)
        if device_guid is None:
            # get the first device available
            if len(gremlin.shared_state.device_guid_to_name_map):
                devices = list(gremlin.shared_state.device_guid_to_name_map.keys())
                device_guid = devices[0]
        return device_guid
        

    def _get_input_id(self, dinput_device_guid, input_id) -> tuple: 
        ''' converts input ID from the storage data to the actual input ID that isn't stored in the config 
        :returns:
        (input_type, save_input_id, input_id)  # input type, the save input ID is a configuration "save" value for saving data, input_id is the object
        
        '''
        save_input_id = input_id
        if not dinput_device_guid in gremlin.shared_state.device_type_map:
            # input is missing
            logging.getLogger("system").warning(f"Config: get last input: Unable to find device {dinput_device_guid} in device map")
            return (None, None, None)
        device_type = gremlin.shared_state.device_type_map[dinput_device_guid]
        if device_type == gremlin.types.DeviceType.Joystick:
            device_info = gremlin.joystick_handling.device_info_from_guid(dinput_device_guid)
            if device_info:
                if device_info.axis_count > 0:
                    input_type = gremlin.input_types.InputType.JoystickAxis
                    if input_id is None or input_id > device_info.axis_count:
                        input_id = 1
                elif device_info.button_count > 0:
                    input_type = gremlin.input_types.InputType.JoystickButton
                    if input_id is None or input_id > device_info.button_count:
                        input_id = 1
        elif device_type in (gremlin.types.DeviceType.Keyboard, gremlin.types.DeviceType.Midi, gremlin.types.DeviceType.Osc):
            # grab the tab widget
            if device_type == gremlin.types.DeviceType.Keyboard:
                input_type = gremlin.input_types.InputType.KeyboardLatched
            elif device_type == gremlin.types.DeviceType.Midi:
                input_type = gremlin.input_types.InputType.Midi
            elif device_type == gremlin.types.DeviceType.Osc:
                input_type = gremlin.input_types.InputType.OpenSoundControl
            elif device_type == gremlin.types.DeviceType.ModeControl:
                input_type = gremlin.input_types.InputType.ModeControl

            if dinput_device_guid in gremlin.shared_state.device_widget_map:
                widget = gremlin.shared_state.device_widget_map[dinput_device_guid]
                if input_id is None:
                    item = widget.itemAt(0)
                    if item is not None:
                        save_input_id = item.identifier.guid
                else:
                    count = widget.input_item_list_model.rows()
                    found = False
                    save_input_id = input_id
                    for index in range(count):
                        item = widget.input_item_list_model.data(index)
                        if item.input_id.guid == input_id:
                            input_id = item.input_id
                            save_input_id = input_id.guid
                            found = True
                            break
                    if not found and count > 0:
                        item = widget.input_item_list_model.data(0)
                        input_id = item.input_id
                        save_input_id = input_id.guid
        elif device_type == gremlin.types.DeviceType.ModeControl:
            save_input_id = input_id
            input_type = gremlin.input_types.InputType.ModeControl
            
                    
        else:
            assert False, f"Config: GetInputId() Don't know how to handle device type: {device_type}"

        return (input_type, save_input_id, input_id)


    def get_last_input(self, device_guid = None) -> tuple: # (device_guid, input_type, input_id)
        ''' gets the last input for a given device
         
        :param device_guid: (optional) the device to look for - if None - uses the last known device
        :returns tuple: (device_guid, input_type, input_id)
           
        '''

        syslog = logging.getLogger("system")

        if device_guid is None:
            # get the last profile device guid
            device_guid = self._profile_data.get("last_device_guid", None)
            if not device_guid:
                return (None, None, None)
        
            

        verbose = self.verbose_mode_details
        # verbose = True
        if verbose:
            device_name = gremlin.shared_state.get_device_name(device_guid)
        if not isinstance(device_guid, str):
            dinput_device_guid = device_guid
            device_guid = str(device_guid)
        else:
            dinput_device_guid = gremlin.util.parse_guid(device_guid)
        data : dict = self._profile_data.get("last_input", {})
        if device_guid in data:
            input_type, input_id = data[device_guid]
            try:
                input_type = gremlin.input_types.InputType.to_enum(input_type)
            except:
                syslog.error(f"GetLastInput(): unable to convert input type {input_type} to a known type")
                input_type = gremlin.input_types.InputType.NotSet

            if input_id is not None and isinstance(input_id, int):
                return (device_guid, input_type, input_id)
            
            if input_id is not None:
                input_type, save_input_id, input_id = self._get_input_id(dinput_device_guid, input_id)
                if input_type is None:
                    if verbose:
                        syslog.info(f"Loading input selection: nothing found for {device_guid} {device_name}")
                    return (None, None, None)
                if verbose:
                    syslog.info(f"Loading saved input selection: {device_guid} {device_name} {input_type} {input_id}")

                try:
                    input_type = gremlin.input_types.InputType.to_enum(input_type)
                except:
                    syslog.error(f"GetLastInput(): unable to convert input type {input_type} to a known type")
                    input_type = gremlin.input_types.InputType.NotSet
                return (device_guid, input_type, input_id)
        # provide a suitable default for the input
        input_id = None
        if dinput_device_guid in gremlin.shared_state.device_type_map:
            input_type, save_input_id, input_id = self._get_input_id(dinput_device_guid,  input_id)             

            # save the new defaults
            data[device_guid] = (input_type, save_input_id)
            self._profile_data["last_input"] = data
            self.save_profile()
            if verbose:
                logging.getLogger("system").info(f"Loading default input selection: {device_guid} {device_name} {input_type} {input_id}")
            return (device_guid, input_type, input_id)
            

        if verbose:
            logging.getLogger("system").info(f"Loading input selection: nothing found for {device_guid} {device_name}")
        return (None, None, None)
        


        

    def ensure_profile(self, profile):
        ''' called when a new profile is created '''

        if not profile or not profile.profile_file:
            return # nothing to do - no profile
        
        if self._profile_fname == profile.profile_file:
            return # nothing to do - same profile        
        
        self._profile_fname = profile.profile_file
        fname = self.get_profile_config()
        
        
        
        self._profile_config_fname = fname
        self.reload_profile()            

        # hook profile load
        if not self._profile_loaded:
            eh = gremlin.event_handler.EventListener()
            eh.profile_changed.connect(self._profile_changed_cb)
            self._profile_loaded = True
        

        if self._profile_fname and not os.path.isfile(self._profile_fname):
            self.save_profile()


    @QtCore.Slot()
    def _profile_changed_cb(self):
        self._last_profile_reload = None
        self.reload_profile()

    @property
    def debug_ui(self):
        return self._data.get("debug_ui",False)
    @debug_ui.setter
    def debug_ui(self, value):
        self._data["debug_ui"] = value
        self.save()

    @property
    def button_grid_visible(self) -> bool:
        ''' default state of the button grid in vjoy remap '''
        return self._data.get("button_grid_visible", True)
    @button_grid_visible.setter
    def button_grid_visible(self, value : bool):
        self._data["button_grid_visible"] = value
        self.save()

    @property
    def midi_enabled(self) -> bool:
        ''' true if MIDI support is enabled '''
        if self._midi_enabled is None:
            from gremlin.ui.midi_device import MidiInterface
            midi = MidiInterface()
            self._midi_enabled = midi.midi_enabled and self._data.get("midi_enabled", True)
        return self._midi_enabled
    
    @midi_enabled.setter
    def midi_enabled(self, value : bool):
        self._data["midi_enabled"] = value
        self._midi_enabled = None # force a re-read 
        


    @property
    def osc_enabled(self) -> bool:
        ''' True if OSC support is enabled'''
        if self._osc_enabled is None:
            self._osc_enabled = self._data.get("osc_enabled", True)
        return self._osc_enabled
    
        
    @osc_enabled.setter
    def osc_enabled(self, value : bool):
        self._data["osc_enabled"] = value
        self._osc_enabled = None # force a re-read 


    # @property
    # def splitter_pos(self) -> int:
    #     ''' splitter config  '''
    #     return self._data.get("splitter_config", 250)
    
    # @splitter_pos.setter
    # def splitter_pos(self, data : int):
    #     self._data["splitter_config"] = data

    @property 
    def mapping_rollover_mode(self):
        return self._data.get("mapping_rollover_mode",1)
    
    @mapping_rollover_mode.setter
    def mapping_rollover_mode(self, mode : int):
        self._data["mapping_rollover_mode"] = mode
        self.save()

    @property 
    def mapping_vjoy_id(self):
        return self._data.get("mapping_vjoy_id",1)

    @mapping_vjoy_id.setter
    def mapping_vjoy_id(self, id : int):
        self._data["mapping_vjoy_id"] = id
        self.save()        

    @property 
    def convert_response_curve(self):
        return self._data.get("convert_response_curve", True)

    @convert_response_curve.setter
    def convert_response_curve(self, value : bool):
        self._data["convert_response_curve"] = value
        self.save()   

    @property 
    def convert_vjoy_remap(self):
        return self._data.get("convert_vjoy_remap", False)

    @convert_vjoy_remap.setter
    def convert_vjoy_remap(self, value: bool):
        self._data["convert_vjoy_remap"] = value
        self.save()   


    @property
    def numlock_off(self) -> bool:
        ''' force numlock off - global setting '''
        return self._data.get("numlock_off", True)
    
    @numlock_off.setter
    def numlock_off(self, value: bool):
        self._data["numlock_off"] = value
        self.save()

    @property
    def condition_selector(self) -> str:
        ''' last selected condition selector '''
        return self._data.get("condition_selector","Joystick Condition")
    
    @condition_selector.setter
    def condition_selector(self, value: str):
        self._data["condition_selector"] = value
        self.save()


    @property
    def experimental(self) -> bool:
        ''' true if internal dev mode '''
        return self._data.get("experimental",False)
    
    @experimental.setter
    def experimental(self, value: bool):
        self._data["experimental"] = value
        self.save()

    @property
    def show_input_enable(self) -> bool:
        return self._data.get("show_input_enable",False)
    @show_input_enable.setter
    def show_input_enable(self, value: bool):
        self._data["show_input_enable"] = value
        self.save()



    def getWindowSize(self, key : str):
        ''' gets window geometry size'''
        data = self._data.get("window_geo_size",{})
        if key in data:
            return data[key]
        return None 

    def setWindowSize(self, key : str, width : int, height : int):
        ''' sets window geometry size '''
        data = self._data.get("window_geo_size",{})
        data[key] = [width, height]
        self._data["window_geo_size"] = data
        self.save()


    def getWindowLocation(self, key : str):
        ''' gets window geometry location '''
        data = self._data.get("window_geo_loc",{})
        if key in data:
            return data[key]
        return None 

    def setWindowLocation(self, key : str, x : int, y : int):
        ''' sets window geometry location '''
        data = self._data.get("window_geo_loc",{})
        data[key] = [x, y]
        self._data["window_geo_loc"] = data
        self.save()


    def clearWindowData(self):
        ''' resets saved window data '''
        self._data["window_geo_loc"] = {}
        self._data["window_geo_size"] = {}
        self.save()

    
