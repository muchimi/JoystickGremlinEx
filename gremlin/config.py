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

import json
import logging
import time
import os
import shutil
import re
import sys
import traceback
from PySide6 import QtCore, QtWidgets
import gremlin.config
import gremlin.input_types

import gremlin.shared_state
from gremlin.types import VerboseMode, DeviceType
from gremlin.input_types import InputType
from psygnal import Signal

from collections import deque
import gremlin.singleton_decorator

syslog = logging.getLogger("system")


@gremlin.singleton_decorator.SingletonDecorator
class Configuration(QtCore.QObject):
    """configuration data"""

    changed = Signal(
        str, object
    )  # fires on some configuration value changes, passes the method to get the value that has changed

    def get_config(self) -> str:
        """local config file (version based)"""
        if __debug__:
            dev_config_file = os.path.join(self.data_path(), "dev_config.json")
            config_file = os.path.join(self.data_path(), "config.json")
            if os.path.isfile(config_file) and not os.path.isfile(dev_config_file):
                shutil.copy(config_file, dev_config_file)

        config_file = dev_config_file if __debug__ else config_file
        return config_file

    def get_backup_config(self) -> str:
        import gremlin.util

        fname = gremlin.util.swap_ext(self.get_config(), suffix=".backup")
        return fname

    def get_profile_config(self):
        """profile specific config file"""
        if self._profile_fname:
            fname, ext = os.path.splitext(self._profile_fname)
            return fname + ".json"
        return None

    def __init__(self):
        """Creates a new instance, loading the current configuration."""
        import gremlin.util

        super().__init__()

        self._lock = False
        self._data = {}  # gremlin items - version specific
        self._profile_data = {}  # profile specific options
        self._profile_loaded = False
        self._profile_fname = None  # current profile to use for the conig
        self._profile_config_fname = None  # config file specific to the profile
        self._app_path = None  # path where data is stored
        self._profile_path = os.path.join(
            os.getenv("userprofile"), "Joystick Gremlin Ex"
        )  # default user profile
        self._visuals_hidden_map = None

        self._midi_enabled = None
        self._osc_enabled = None

        # commandline options
        self._auto_load_disabled = False

        fname = self.get_config()
        basedir = os.path.dirname(fname)
        if not os.path.isdir(basedir):
            if not gremlin.util.create_folder(basedir):
                msg = f"CONFIG: Unable to create data folder: {basedir}.\nCheck that you have the permissions to create this folder or create it manually."
                gremlin.util.display_error(msg)
                syslog.error(msg)

        if not os.path.isfile(fname):
            # create a stub - first time run
            syslog.info("CONFIG: no configuration found - creating default")
            self.save()

        gettrace = getattr(sys, "gettrace", None)
        frozen = getattr(sys, "frozen", False)
        if frozen:
            self._is_debug = False
        else:
            self._is_debug = gettrace is not None

        self._last_reload = None
        self._last_profile_reload = None
        data_path = self.data_path()
        gremlin.shared_state.data_path = data_path

        self.watcher = QtCore.QFileSystemWatcher([fname])

        self.reload()

        self.watcher.fileChanged.connect(self.reload)

    def setup_userprofile(self):
        """Initializes the data folder in the user's profile folder."""
        import gremlin.shared_state

        folder = gremlin.shared_state.data_path
        if not os.path.exists(folder):
            try:
                os.makedirs(folder)
            except Exception as err:
                syslog.error("Unable to create data folder:")
                syslog.error(f"{err}\n{traceback.format_exc()}")

        elif not os.path.isdir(folder):
            syslog.error(f"Unable to find data folder: {folder}")
            sys.exit(-1)

    def backup(self) -> bool:
        """backs the config up"""
        import gremlin.util

        backup_fname = self.get_backup_config()
        try:
            if os.path.isfile(backup_fname):
                # backup to an alternate file
                max_count = 5  # number of backups to maintain
                index = 1
                flist = [backup_fname]
                c1 = gremlin.util.swap_ext(backup_fname, suffix=f".{index}")
                while os.path.isfile(c1):
                    flist.append(c1)
                    index += 1
                    c1 = gremlin.util.swap_ext(backup_fname, suffix=f".{index}")

                count = len(flist)
                # cascade the backup files
                while count > max_count:
                    c2 = flist.pop()
                    os.unlink(c2)
                    count -= 1

                alt_backup = c1

                if alt_backup:
                    shutil.copy(backup_fname, alt_backup)
                os.unlink(backup_fname)

            self.save(backup_fname)
            gremlin.ui.ui_common.MessageBoxInfo(
                title="Backup Configuration", prompt="Backup saved"
            )
        except Exception:
            gremlin.ui.ui_common.MessageBoxWarning(
                title="Backup Configuration",
                prompt="The backup file could not be saved due to a file I/O error.",
            )
            return False
        return True

    def restore(self) -> bool:
        import gremlin.ui.ui_common

        backup_fname = self.get_backup_config()
        if os.path.isfile(backup_fname):
            fname = self.get_config()
            try:
                if os.path.isfile(fname):
                    os.unlink(fname)
                shutil.copy(backup_fname, fname)
                syslog.info("CONFIG: backup restored")
                self._reload()
                gremlin.ui.ui_common.MessageBoxInfo(
                    title="Restore Configuration", prompt="Backup restored"
                )
            except Exception:
                gremlin.ui.ui_common.MessageBoxWarning(
                    title="Restore Configuration",
                    prompt="The backup file could not be restored due to a file I/O error.",
                )
                return False
        else:
            gremlin.ui.ui_common.MessageBoxWarning(
                title="Restore Configuration",
                prompt="The backup file could not be restored.\nNo Backup found.",
            )

        return True

    def _clean_string(self, value):
        chars = ". "
        for char in chars:
            value = value.replace(char, "_")
        if value:
            return value.casefold().strip()
        return ""

    def _clean_version(self, app_main=None, app_base=None):
        import gremlin.version

        if not app_main:
            app_main = self._clean_string(gremlin.version.APPLICATION_MAIN)
        if not app_base:
            app_base = self._clean_string(
                gremlin.version.APPLICATION_BASE
            )  # can be blank
        return f"{app_main}_{app_base}" if app_base else app_main

    def data_path(self):
        """returns a path to the data folder for the current application version - this folder is located in the user profile
        and as of m74t5 depends on the user option to create a folder for each version of the software or not

        if a new version is detected, the contents of the most recent version folder is copied over

        """

        if not self._app_path:
            enable_version = self.enable_log_version
            user_profile_path = os.path.abspath(
                os.path.join(os.getenv("userprofile"), "Joystick Gremlin Ex")
            )
            self._profile_path = user_profile_path

            if enable_version:
                # store the log in a folder
                app_path = f"{user_profile_path}_{self._clean_version()}"
                if not os.path.isdir(app_path):
                    try:
                        os.makedirs(app_path)
                    except Exception:
                        print(
                            f"Error: unable to create application data folder: {app_path}",
                            file=sys.stderr,
                        )
                        sys.exit(-1)
            else:
                app_path = user_profile_path

            self._app_path = app_path

        return self._app_path

    def reload(self, force=False):

        if (
            not force
            and self._last_reload is not None
            and time.time() - self._last_reload < 1
        ):
            return

        self._reload()  #  load that first because it cascades values into local if not in local yet
        self._last_reload = time.time()

    def _init_data(self):
        """new data set"""
        return {"calibration": {}, "profiles": {}, "last_mode": {}}

    def _is_blank(self, fname):
        """true if the file is blank, does not exist or contains whitespaces"""
        if os.path.isfile(fname):
            file_size = os.path.getsize(fname)
            if file_size == 0:
                return True
            with open(fname, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.isspace():
                        return False

        return True

    def _reload(self):
        """Loads the configuration file's content.  flag = global or local (version specific) config"""

        fname = self.get_config()

        # Attempt to load the configuration file if this fails set
        # default empty values.
        load_successful = False
        if os.path.isfile(fname):
            if not self._is_blank(fname):
                with open(fname,"r", encoding="utf-8") as hdl:
                    try:
                        # decoder = json.JSONDecoder()
                        # decoder.decode(hdl.read())
                        data = json.load(hdl)
                        load_successful = True
                    except ValueError:
                        pass
        if not load_successful:
            data = self._init_data()

        # Ensure required fields are present and if they are missing
        # add empty ones.

        field_list = ["calibration", "profiles", "last_mode"]

        for field in field_list:
            if field not in data:
                data[field] = {}

        self._data = data

    def _get_data(self, field, default_value=None):
        """gets a value field either from local or global depending where it's defined"""

        # pull from local data first
        if field in self._data:
            return self._data.get(field, default_value)
        return default_value

    def _set_data(self, field, value):
        """save the value to the config file"""
        if field not in self._data or self._data[field] != value:
            self._data[field] = value
            self.save()

    def reload_profile(self):
        import gremlin.util

        if QtWidgets.QApplication.instance():
            gremlin.util.InvokeUiMethod(self._reload_profile_ui)  # ensure on UI thread
        else:
            self._reload_profile_ui()

    def _reload_profile_ui(self):
        """Loads the profile's configuration file's content."""
        if (
            self._last_profile_reload is not None
            and time.time() - self._last_profile_reload < 1
        ):
            return

        self._profile_data = {}

        fname = self._profile_config_fname
        if not fname:
            return  # nothing to load

        # Attempt to load the configuration file if this fails set
        # default empty values.
        if os.path.isfile(fname) and os.path.getsize(fname):
            with open(fname,"r", encoding="utf-8") as hdl:
                try:
                    # decoder = json.JSONDecoder()
                    # self._profile_data = decoder.decode(hdl.read())
                    self._profile_data = json.load(hdl)
                    _load_successful = True
                except ValueError:
                    pass

        # Save all data
        self._last_profile_reload = time.time()
        self.save_profile()

    def save(self, fname: str = None):
        import gremlin.util
        import gremlin.event_handler

        if QtWidgets.QApplication.instance():
            gremlin.util.InvokeUiMethod(self._save_ui, fname)  # ensure on UI thread
        else:
            self._save_ui(fname)

        # tell UI of config changes

        el = gremlin.event_handler.EventListener()
        el.config_option_changed.emit()

    def _save_ui(self, fname: str = None):
        """Writes the version specific configuration file to disk."""
        if self._lock:
            # ignore concurrent save requests (technically not necessary due to UI thread placement)
            return
        tmp = gremlin.util.getTemporaryFile(".json")
        is_error = False
        try:
            self._lock = True
            if not fname:
                fname = self.get_config()
            # get a temp file name
            with open(tmp, "w", encoding="utf-8") as hdl:
                encoder = json.JSONEncoder(sort_keys=True, indent=4)
                hdl.write(encoder.encode(self._data))
                hdl.flush()
                hdl.close()
        except Exception as ex:
            syslog.error(f"CONFIG: unable to save file: {fname}")
            syslog.error(ex)
            is_error = True
        finally:
            if not is_error:
                try:
                    if os.path.isfile(fname):
                        os.unlink(fname)
                    shutil.copy(tmp, fname)
                    os.unlink(tmp)
                except Exception as ex:
                    syslog.error(f"CONFIG: unable to overwrite file: {fname}")
                    syslog.error(ex)

            self._lock = False

    def save_profile(self):
        import gremlin.util

        if QtWidgets.QApplication.instance():
            gremlin.util.InvokeUiMethod(self._save_profile_ui)  # ensure on UI thread
        else:
            self._save_profile_ui()

    def _save_profile_ui(self):
        """saves to the profile specific config file"""
        if self._lock:
            # ignore concurrent save requests (technically not necessary due to UI thread placement)
            return
        try:
            self._lock = True
            fname = self._profile_config_fname
            if fname:
                with open(fname, "w", encoding="utf-8") as hdl:
                    encoder = json.JSONEncoder(sort_keys=True, indent=4)
                    hdl.write(encoder.encode(self._profile_data))
        except Exception as ex:
            syslog.error(f"CONFIG: unable to save profile: {fname}")
            syslog.error(ex)
        finally:
            self._lock = False

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
        item = self._get_data("last_mode", None)
        if not item:
            self._data["last_mode"] = {}
        self._data["last_mode"][profile_path] = mode_name
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_mode
        if verbose:
            syslog.info(
                f"CONFIG: storing last runtime profile mode: [{mode_name}] for profile [{os.path.basename(profile_path)}]"
            )
        self.save()

    def get_last_runtime_mode(self, profile_path):
        """Returns the last active mode of the given profile.

        :param profile_path profile path for which to return the mode
        :return name of the mode if present, None otherwise
        """
        profile_path = os.path.normpath(profile_path).casefold()
        item = self._get_data("last_mode", None)
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
        item = self._get_data("last_edit_mode", None)
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
        item = self._get_data("last_edit_mode", None)
        if not item:
            return None
        if profile_path in item:
            return item[profile_path]
        return None

    def set_profile_last_runtime_mode(self, mode_name):
        """sets the profile's last used mode"""
        fname = self.last_profile
        if fname:
            self.set_last_runtime_mode(fname, mode_name)

    def get_profile_last_runtime_mode(self):
        """gets the save last used profile mode"""
        fname = self.last_profile
        if fname:
            return self.get_last_runtime_mode(fname)
        return None

    def set_profile_last_edit_mode(self, mode_name):
        """sets the profile's last used mode"""
        fname = self.last_profile
        if fname:
            self.set_last_edit_mode(fname, mode_name)

    def get_profile_last_edit_mode(self):
        """gets the save last used profile mode"""
        fname = self.last_profile
        if fname:
            return self.get_last_edit_mode(fname)
        return None

    @property
    def initial_load_mode_tts(self):
        """if set, JGEX outputs a verbal readout of the current mode on profile load"""
        return self._get_data("initial_load_mode_tts", True)

    @initial_load_mode_tts.setter
    def initial_load_mode_tts(self, value):
        self._set_data("initial_load_mode_tts", value)

    @property
    def initial_load_rate_tts(self):
        """default TTS playback rate"""
        return self._get_data("initial_load_rate_tts", 100)

    @initial_load_rate_tts.setter
    def initial_load_rate_tts(self, value):
        self._set_data("initial_load_rate_tts", value)

    @property
    def initial_volume_tts(self):
        """default TTS volume"""
        return self._get_data("initial_volume_tts", 80)

    @initial_volume_tts.setter
    def initial_volume_tts(self, value):
        self._set_data("initial_volume_tts", value)

    @property
    def tts_enabled(self) -> bool:
        return self._get_data("tts_enabled", True)

    @tts_enabled.setter
    def tts_enabled(self, value: bool):
        self._set_data("tts_enabled", value)

    @property
    def tts_mode_switch_enabled(self) -> bool:
        return self._get_data(
            "tts_mode_switch_enabled", False
        )  # change in m77 default is to not speak mode changes by default

    @tts_mode_switch_enabled.setter
    def tts_mode_switch_enabled(self, value: bool):
        self._set_data("tts_mode_switch_enabled", value)

    @property
    def tts_suppress_duplicate(self) -> bool:
        return self._get_data("tts_suppress_duplicate", True)

    @tts_suppress_duplicate.setter
    def tts_suppress_duplicate(self, value: bool):
        self._set_data("tts_suppress_duplicate", value)

    @property
    def runtime_ui_update(self):
        """if set, JGEX will update the UI when a profile is activated"""
        return self._get_data("runtime_ui_update", False)

    @runtime_ui_update.setter
    def runtime_ui_update(self, value):
        self._set_data("runtime_ui_update", value)

    @property
    def reset_mode_on_process_activate(self):
        """if set, the mode is reset when the process is reactivated to the default mode"""
        return self._get_data("reset_mode_on_process_activate", False)

    @reset_mode_on_process_activate.setter
    def reset_mode_on_process_activate(self, value):
        self._set_data("reset_mode_on_process_activate", value)

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
            axis_name = f"axis_{i + 1}"
            self._data["calibration"][identifier][axis_name] = [
                limit[0],
                limit[1],
                limit[2],
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
        calibration_data = self._get_data("calibration", {})
        if identifier not in calibration_data:
            return [-32768, 0, 32767]
        if axis_name not in calibration_data[identifier]:
            return [-32768, 0, 32767]

        return calibration_data[identifier][axis_name]

    @property
    def last_options_tab(self):
        """index of the last option tab selected"""
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
        return list(sorted(self._data["profiles"].keys(), key=lambda x: x.lower()))

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
            syslog.info(f"Found exact match for {exec_path}, returning {profile_path}")
            return profile_path

        # Handle non files by treating them as regular expressions, returning
        # the first successful match.
        for key, value in sorted(
            self._data["profiles"].items(), key=lambda x: x[0].lower()
        ):
            # Ignore valid files
            if os.path.exists(key):
                continue

            # Treat key as regular expression and attempt to match it to the
            # provided executable path
            if re.search(key, exec_path) is not None:
                syslog.info(
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
        return self._get_data("last_profile", None)

    @last_profile.setter
    def last_profile(self, value):
        """Sets the last used profile.

        :param value path to the most recently used profile
        """
        self._data["last_profile"] = value

        # Update recent profiles
        if value is not None:
            value = os.path.normpath(value.casefold())  # normalize the profile path
            current = self.recent_profiles
            if value in current:
                current.remove(value)

            data = deque(maxlen=21)
            data.extend(current)

            # add the current item as the last item
            data.appendleft(value)

            # trim
            while len(data) > 20:
                data.pop()

            # normalize and remove duplicates
            current = []
            while data:
                current.append(os.path.normpath(data.popleft().casefold()))

            self._data["recent_profiles"] = current
        self.save()

    @property
    def recent_profiles(self):
        """Returns a list of recently used profiles.

        :return list of recently used profiles
        """
        return self._get_data("recent_profiles", [])

    @property
    def autoload_profiles(self):
        """Returns whether or not to automatically load profiles.

        This enables / disables the process based profile autoloading.

        :return True if auto profile loading is active, False otherwise
        """
        return self._get_data("autoload_profiles", False)

    @autoload_profiles.setter
    def autoload_profiles(self, value):
        """Sets whether or not to automatically load profiles.

        This enables / disables the process based profile autoloading.

        :param value Flag indicating whether or not to enable / disable the
            feature
        """
        if isinstance(value, bool):
            self._data["autoload_profiles"] = value
            self.save()
            el = gremlin.event_handler.EventListener()
            el.process_monitor_changed.emit()  # tell the UI the parameter changed

    @property
    def keep_profile_active_on_focus_loss(self):
        return self._get_data("keep_active_on_focus_loss", True)

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
        return self._get_data("keep_last_autoload", False)

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
        """determines if a profile mode, if it exists is restored when the profile is activated"""
        return self._get_data("restore_mode_on_start", False)

    @restore_profile_mode_on_start.setter
    def restore_profile_mode_on_start(self, value):
        self._set_data("restore_mode_on_start", value)

    @property
    def highlight_autoswitch(self):
        """true if in design mode and tab switching is allowed on input detect change"""
        return self._get_data("highlight_switch", False)

    @highlight_autoswitch.setter
    def highlight_autoswitch(self, value):

        if value != self.highlight_autoswitch:
            self._set_data("highlight_switch", value)

    @property
    def highlight_input_axis(self):
        """Returns whether or not to highlight inputs for an axis

        This enables / disables the feature where using a physical input
        automatically selects it in the UI.

        :return True if the feature is enabled, False otherwise
        """
        return self._get_data("highlight_input_axis", False)

    @highlight_input_axis.setter
    def highlight_input_axis(self, value):
        """Sets whether or not to highlight inputs for an axis

        This enables / disables the feature where using a physical input
        automatically selects it in the UI.

        :param value Flag indicating whether or not to enable / disable the
            feature
        """
        if value != self.highlight_input_axis:
            self._data["highlight_input_axis"] = value
            self.save()
            # indicate axis highlighting was changed
            self.changed.emit("highlight_input_axis", value)

    @property
    def highlight_input_buttons(self):
        """Returns whether or not to highlight inputs for a button

        This enables / disables the feature where using a physical input
        automatically selects it in the UI.

        :return True if the feature is enabled, False otherwise
        """
        return self._get_data("highlight_input_buttons", True)

    @highlight_input_buttons.setter
    def highlight_input_buttons(self, value):
        """Sets whether or not to highlight inputs for a button

        This enables / disables the feature where using a physical input
        automatically selects it in the UI.

        :param value Flag indicating whether or not to enable / disable the
            feature
        """
        if value != self.highlight_input_buttons:
            self._data["highlight_input_buttons"] = value
            self.save()
            self.changed.emit("highlight_input_buttons", value)

    @property
    def highlight_enabled(self):
        """Returns whether or not highlighting swaps device tabs.

        This enables / disables the feature where using a physical input
        automatically swaps to the correct device tab.

        :return True if the feature is enabled, False otherwise
        """
        return self._get_data("highlight_device", False)

    @highlight_enabled.setter
    def highlight_enabled(self, value) -> bool:
        """Sets whether or not to swap device tabs to highlight inputs.

        This enables / disables the feature where using a physical input
        automatically swaps to the correct device tab.

        :param value Flag indicating whether or not to enable / disable the
            feature
        """
        if value != self.highlight_enabled:
            self._data["highlight_device"] = value
            self.save()
            self.changed.emit("highlight_device", value)

    @property
    def highlight_hotkey_autoswitch(self):
        """when enabled - pressing the control or shift hotkeys to toggle axis / button highlight also allows tab switch"""
        return self._get_data("highlight_hotkey_autoswitch", False)

    @highlight_hotkey_autoswitch.setter
    def highlight_hotkey_autoswitch(self, value: bool):
        self._set_data("highlight_hotkey_autoswitch", value)

    @property
    def enable_remote_control(self):
        """enables or disables remote control from another gremlin instance on the network"""
        return self._get_data("allow_remote_control", False)

    @enable_remote_control.setter
    def enable_remote_control(self, value):
        if isinstance(value, bool):
            self._set_data("allow_remote_control", value)

    @property
    def enable_remote_broadcast(self):
        """enables gremlin to broadcast control changes over UDP multicast"""
        return self._get_data("enable_remote_broadcast", False)

    @enable_remote_broadcast.setter
    def enable_remote_broadcast(self, value):
        """remote broadcast master switch enable"""
        if (
            isinstance(value, bool)
            and self._get_data("enable_remote_broadcast", False) != value
        ):
            self._set_data("enable_remote_broadcast", value)

    @property
    def custom_host_name(self) -> str:
        """custom host name for the host"""
        return self._get_data("custom_host_name", None)

    @custom_host_name.setter
    def custom_host_name(self, value: str):
        self._set_data("custom_host_name", value)

    def remoteEnabled(self) -> bool:
        return self.enable_remote_broadcast or self.enable_remote_control

    @property
    def enable_broadcast_speech(self):
        """speech on broadcast change mode enable"""
        return self._get_data("enable_broadcast_speech", True)

    @enable_broadcast_speech.setter
    def enable_broadcast_speech(self, value):

        if self.enable_broadcast_speech != value:
            self._data["enable_broadcast_speech"] = value
            self.save()

    @property
    def server_port(self):
        """port number to use for the gremlin server"""
        return self._get_data("server_port", 6012)

    @server_port.setter
    def server_port(self, value):
        if isinstance(value, float):
            value = int(value)
        elif isinstance(value, str) and value.isnumeric():
            value = int(value)

        if isinstance(value, int):
            self._set_data("server_port", value)

    @property
    def broadcast_host_ip(self):
        """host for the broadcast server"""
        return self._get_data("broadcast_host_ip", "127.0.0.1")

    @broadcast_host_ip.setter
    def broadcast_host_ip(self, value: str):
        self._set_data("broadcast_host_ip", value)

    @property
    def broadcast_bind_all_ips(self):
        """true if bound to all IPs (default)"""
        return self._get_data("broadcast_bind_all_ips", True)

    @broadcast_bind_all_ips.setter
    def broadcast_bind_all_ips(self, value: bool):
        self._set_data("broadcast_bind_all_ips", value)

    @property
    def master(self) -> bool:
        return self._get_data("master", False)

    @master.setter
    def master(self, value: bool):
        self._set_data("master", value)

    @property
    def mode_change_message(self) -> bool:
        """Returns whether or not to show a windows notification on mode change.

        :return True if the feature is enabled, False otherwise
        """
        return self._get_data("mode_change_message", False)

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
        return self._get_data("activate_on_launch", False)

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
        return self._get_data("activate_on_process_focus", False)

    @activate_on_process_focus.setter
    def activate_on_process_focus(self, value):
        """Sets whether or not to activate the profile on launch."""
        self._data["activate_on_process_focus"] = bool(value)
        self.save()
        el = gremlin.event_handler.EventListener()
        el.process_monitor_changed.emit()  # tell the UI the process options changed

    @property
    def close_to_tray(self):
        """Returns whether or not to minimze the application when closing it.

        :return True if closing minimizes to tray, False otherwise
        """
        return self._get_data("close_to_tray", False)

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
        return self._get_data("start_minimized", False)

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
        return self._get_data("default_action", "Vjoy Remap")

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
        return self._get_data("last_action", Configuration().default_action)

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
        return self._get_data("last_container", "basic")

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
        return self._get_data("macro_axis_polling_rate", 0.1)

    @macro_axis_polling_rate.setter
    def macro_axis_polling_rate(self, value):
        self._data["macro_axis_polling_rate"] = value
        self.save()

    @property
    def macro_key_delay(self) -> int:
        return self._get_data("macro_key_delay", 250)

    @macro_key_delay.setter
    def macro_key_delay(self, value: int):
        self._data["macro_key_delay"] = value
        self.save()

    @property
    def macro_axis_minimum_change_rate(self):
        """Returns the minimum change in value required to record an axis event.

        :return minimum axis change required
        """
        return self._get_data("macro_axis_minimum_change_rate", 0.005)

    @macro_axis_minimum_change_rate.setter
    def macro_axis_minimum_change_rate(self, value):
        self._data["macro_axis_minimum_change_rate"] = value
        self.save()

    @property
    def macro_record_axis(self):
        return self._get_data("macro_record_axis", False)

    @macro_record_axis.setter
    def macro_record_axis(self, value):
        self._data["macro_record_axis"] = bool(value)
        self.save()

    @property
    def macro_record_button(self):
        return self._get_data("macro_record_button", True)

    @macro_record_button.setter
    def macro_record_button(self, value):
        self._data["macro_record_button"] = bool(value)
        self.save()

    @property
    def macro_record_hat(self):
        return self._get_data("macro_record_hat", True)

    @macro_record_hat.setter
    def macro_record_hat(self, value):
        self._data["macro_record_hat"] = bool(value)
        self.save()

    @property
    def macro_record_keyboard(self):
        return self._get_data("macro_record_keyboard", True)

    @macro_record_keyboard.setter
    def macro_record_keyboard(self, value):
        self._data["macro_record_keyboard"] = bool(value)
        self.save()

    @property
    def macro_record_mouse(self):
        return self._get_data("macro_record_mouse", False)

    @macro_record_mouse.setter
    def macro_record_mouse(self, value):
        self._data["macro_record_mouse"] = bool(value)
        self.save()

    @property
    def window_size(self):
        """Returns the size of the main Gremlin window.

        :return size of the main Gremlin window
        """
        return self._get_data("window_size", None)

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
        return self._get_data("window_location", None)

    @window_location.setter
    def window_location(self, value):
        """Sets the position of the main Gremlin window.

        :param value the position of the main Gremlin window
        """
        self._data["window_location"] = value
        self.save()

    @property
    def persist_clipboard(self):
        """true if clipboard data is persisted from one session to the next"""
        return self._get_data("persist_clipboard", False)

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
        """determines loging level"""
        if __debug__:
            return True
        value = self._get_data("verbose", VerboseMode.NotSet)
        if value is None:
            # not set - set other defaults
            self._data["verbose_mode"] = VerboseMode.NotSet
            self._data["verbose"] = False
            return False
        return value

    @verbose.setter
    def verbose(self, value):
        self._data["verbose"] = value
        self.save()

    @property
    def verbose_mode(self):
        """sub logging level"""
        if "verbose_mode" not in self._data:
            self._data["verbose_mode"] = VerboseMode.NotSet
            self.save()
        return VerboseMode(self._data["verbose_mode"])

    def setVerboseMode(self, value):
        ''' sets the verbose mode to a value '''
        self._data["verbose_mode"] = value
        self.save()

    def is_verbose_mode(self, mode):
        value = self.verbose_mode
        result = mode in value
        return result

    @verbose_mode.setter
    def verbose_mode(self, value):
        self._data["verbose_mode"] = value
        self.save()

    def verbose_set_mode(self, mode, enabled):
        """enables the specified verbose mode"""
        if "verbose_mode" not in self._data:
            self._data["verbose_mode"] = 0  # none
        value = self._data["verbose_mode"]
        if enabled:
            value |= mode
        else:
            value = value & ~mode
        self.verbose_mode = value

    @property
    def verbose_mode_inputitems(self):
        """true if verbose mode is in keyboard mode"""
        return self.verbose and VerboseMode.InputItems in self.verbose_mode

    @property
    def verbose_mode_keyboard(self):
        """true if verbose mode is in keyboard mode"""
        return self.verbose and VerboseMode.Keyboard in self.verbose_mode

    @property
    def verbose_mode_keyboard_extra(self):
        """true if verbose mode is in keyboard mode"""
        return (
            self.verbose
            and VerboseMode.Keyboard in self.verbose_mode
            and VerboseMode.Extra in self.verbose_mode
        )

    @property
    def verbose_mode_ui(self):
        return self.verbose and VerboseMode.UI in self.verbose_mode

    def verbose_mode_ui_level(self, level = 0):
        """true if verbose mode is in UI mode"""
        flag = self.verbose and VerboseMode.UI in self.verbose_mode
        return flag and (level == 0 \
            or (level >= 1 and VerboseMode.L1 in self.verbose_mode) \
            or (level >= 2 and VerboseMode.L2 in self.verbose_mode) \
            or (level >= 3 and VerboseMode.L3 in self.verbose_mode)
        )

    @property
    def verbose_mode_vjoy(self):
        """true if verbose mode is in UI mode"""
        return self.verbose and VerboseMode.VJoy in self.verbose_mode

    @property
    def verbose_mode_curve(self):
        """true if verbose mode is in UI mode"""
        return self.verbose and VerboseMode.Curve in self.verbose_mode

    @property
    def verbose_mode_joystick(self):
        """true if verbose mode is in joystick mode"""
        return self.verbose and VerboseMode.Joystick in self.verbose_mode

    @property
    def verbose_mode_inputs(self):
        """true if verbose mode is in inputs mode"""
        return self.verbose and VerboseMode.Inputs in self.verbose_mode

    @property
    def verbose_mode_inputs_extra(self):
        """true if verbose mode is in inputs mode"""
        return (
            self.verbose
            and VerboseMode.Inputs in self.verbose_mode
            and VerboseMode.Extra in self.verbose_mode
        )

    @property
    def verbose_mode_mouse(self):
        """true if verbose mode is in mouse mode"""
        return self.verbose and VerboseMode.Mouse in self.verbose_mode

    @property
    def verbose_mode_mouse_input(self):
        """true if verbose mode is in mouse mode"""
        return self.verbose and VerboseMode.MouseInput in self.verbose_mode

    @property
    def verbose_mode_details(self):
        """true if verbose mode is in detail mode"""
        return self.verbose and VerboseMode.Details in self.verbose_mode

    @property
    def verbose_mode_detailed(self):
        """true if verbose mode is in detail mode"""
        return self.verbose and VerboseMode.Details in self.verbose_mode

    @property
    def verbose_mode_device(self):
        """true if verbose mode is in device mode"""
        return self.verbose and VerboseMode.Device in self.verbose_mode

    @property
    def verbose_mode_simconnect(self):
        """true if verbose mode is in simconnect mode"""
        return self.verbose and VerboseMode.SimConnect in self.verbose_mode

    @property
    def verbose_mode_condition(self):
        """true if verbose mode is in condition/execution mode"""
        return self.verbose and VerboseMode.Condition in self.verbose_mode

    @property
    def verbose_mode_execution(self):
        """true if verbose mode is in exec"""
        return self.verbose and VerboseMode.Exec in self.verbose_mode

    @property
    def verbose_mode_state(self):
        """true if verbose mode is in state mode"""
        return self.verbose and VerboseMode.State in self.verbose_mode

    @property
    def verbose_mode_exec_detailed(self):
        """true if verbose mode is in exec detailed mode"""
        return (
            self.verbose
            and self.verbose_mode_exec
            and VerboseMode.ExecDetails in self.verbose_mode
        )

    @property
    def verbose_mode_osc(self):
        """true if verbose mode is in OSC mode"""
        return self.verbose and VerboseMode.OSC in self.verbose_mode

    @property
    def verbose_mode_midi(self):
        """true if verbose mode is in MIDI mode"""
        return self.verbose and VerboseMode.Midi in self.verbose_mode

    @property
    def verbose_mode_process(self):
        """true if verbose mode is in process mode"""
        return self.verbose and VerboseMode.Process in self.verbose_mode

    @property
    def verbose_mode_exec(self):
        """true if verbose mode is in Exec(ute) mode"""
        return self.verbose and VerboseMode.Exec in self.verbose_mode

    @property
    def verbose_mode_macro(self):
        """true if verbose mode is in macro mode"""
        return self.verbose and VerboseMode.Macro in self.verbose_mode

    @property
    def verbose_mode_gate(self):
        """true if verbose mode is in gated axis mode"""
        return self.verbose and VerboseMode.Gate in self.verbose_mode

    @property
    def verbose_mode_extra(self):
        return self.verbose and VerboseMode.Extra in self.verbose_mode

    @property
    def verbose_mode_outputs(self):
        """true if verbose mode is in output mode"""
        return self.verbose and VerboseMode.Outputs in self.verbose_mode

    @property
    def verbose_mode_container(self):
        """true if verbose mode is in container logic  mode"""
        return self.verbose and VerboseMode.Container in self.verbose_mode

    @property
    def verbose_mode_octavi(self):
        """true if verbose mode is in output mode"""
        return self.verbose and VerboseMode.Octavi in self.verbose_mode

    @property
    def verbose_mode_dinput(self):
        """true if verbose mode is in output mode"""
        return self.verbose and VerboseMode.dinput in self.verbose_mode

    @property
    def verbose_mode_output(self):
        return self.verbose_mode_outputs

    @property
    def verbose_mode_remote(self):
        """true if verbose mode is in output mode"""
        return self.verbose and VerboseMode.Remote in self.verbose_mode

    @property
    def verbose_mode_remote_extra(self):
        """true if extra remote verbose mode on"""
        return (
            self.verbose
            and VerboseMode.Remote in self.verbose_mode
            and VerboseMode.Extra in self.verbose_mode
        )

    @property
    def verbose_mode_tts(self):
        """true if verbose mode is in TTS mode"""
        return self.verbose and VerboseMode.TTS in self.verbose_mode

    @property
    def verbose_mode_sound(self):
        """true if verbose mode is in sound mode"""
        return self.verbose and VerboseMode.Sound in self.verbose_mode

    @property
    def verbose_mode_filter(self):
        """true if verbose mode is in input filter mode"""
        return self.verbose and VerboseMode.Filter in self.verbose_mode

    @property
    def verbose_mode_perf(self):
        return self.verbose and VerboseMode.Perf in self.verbose_mode


    def verbose_mode_perf_level(self, level = 0):
        """true if verbose mode for performance timing"""
        flag = self.verbose and VerboseMode.Perf in self.verbose_mode
        return flag and (level == 0 \
            or level == 1 and VerboseMode.L1 in self.verbose_mode \
            or level == 2 and VerboseMode.L2 in self.verbose_mode \
            or level >= 3 and VerboseMode.L3 in self.verbose_mode)

    @property
    def verbose_mode_timing(self):
        """true if verbose mode is in timing mode"""
        return self.verbose_mode_perf

    @property
    def verbose_mode_events(self):
        """true if verbose mode for performance timing"""
        return self.verbose and VerboseMode.Events in self.verbose_mode

    @property
    def verbose_mode_calib(self):
        """true if verbose mode for performance timing"""
        return self.verbose and VerboseMode.Calib in self.verbose_mode

    @property
    def verbose_mode_hooks(self):
        """true if verbose mode for performance timing"""
        return self.verbose and VerboseMode.Hooks in self.verbose_mode

    @property
    def verbose_mode_merge(self):
        """true if verbose mode is in merge mode"""
        return self.verbose and VerboseMode.Merge in self.verbose_mode

    @property
    def verbose_mode_sequence(self):
        """true if verbose mode is in sequence mode"""
        return self.verbose and VerboseMode.Sequence in self.verbose_mode

    @property
    def verbose_mode_select(self):
        """true if verbose mode is in select mode"""
        return self.verbose and VerboseMode.Select in self.verbose_mode

    @property
    def verbose_mode_switch(self):
        """true if verbose mode is in switch mode"""
        return self.verbose and VerboseMode.Switch in self.verbose_mode

    @property
    def verbose_mode_dev(self):
        return self.verbose and __debug__

    @property
    def verbose_mode_mode(self):
        """true if verbose mode is in Mode mode"""
        return self.verbose and VerboseMode.Mode in self.verbose_mode

    @property
    def verbose_mode_l1(self):
        """true if verbose mode level 3"""
        return self.verbose and VerboseMode.L1 in self.verbose_mode

    @property
    def verbose_mode_l2(self):
        """true if verbose mode level 2 """
        return self.verbose and VerboseMode.L2 in self.verbose_mode

    @property
    def verbose_mode_l3(self):
        """true if verbose mode level 3"""
        return self.verbose and VerboseMode.L3 in self.verbose_mode

    @property
    def midi_enabled(self):
        """true if MIDI module is enabled"""
        return self._get_data("midi_enabled", True)

    @midi_enabled.setter
    def midi_enabled(self, value):
        self._data["midi_enabled"] = value
        self.save()

    @property
    def osc_enabled(self):
        """true if osc module is enabled"""
        return self._get_data("osc_enabled", True)

    @osc_enabled.setter
    def osc_enabled(self, value):
        self._data["osc_enabled"] = value
        self.save()

    @property
    def osc_input_port(self):
        """OSC listen port"""
        port = self._get_data("osc_port", 8000)
        return port

    @osc_input_port.setter
    def osc_input_port(self, value):
        self._data["osc_port"] = value
        self.save()

    @property
    def osc_output_port(self):
        """OSC listen port"""
        port = self._get_data("osc_output_port", 8001)
        return port

    @osc_output_port.setter
    def osc_output_port(self, value):
        self._data["osc_output_port"] = value
        self.save()

    @property
    def osc_host(self):
        """OSC client host (this is the IP the machine GremlinEx sends OSC data to)"""
        host = self._get_data("osc_host", "127.0.0.1")
        return host

    @osc_host.setter
    def osc_host(self, value: str):
        self._data["osc_host"] = value
        self.save()

    @property
    def osc_no_arg_autorelease(self) -> bool:
        """if set, OSC input is set to autorelease if no args are present in the packet"""
        return self._get_data("osc_no_arg_autorelease", True)

    @osc_no_arg_autorelease.setter
    def osc_no_arg_autorelease(self, value: bool):
        self._set_data("osc_no_arg_autorelease", value)

    @property
    def osc_default_autorelease_delay(self) -> float:
        """autorelease delay in seconds"""
        return self._get_data("osc_default_autorelease_delay", 0.25)

    @osc_default_autorelease_delay.setter
    def osc_default_autorelease_delay(self, value: float):
        if value >= 0:
            self._set_data("osc_default_autorelease_delay", value)

    @property
    def show_scancodes(self):
        """hide/show scan codes for keyboard related inputs"""
        return self._get_data("show_scancodes", False)

    @show_scancodes.setter
    def show_scancodes(self, value):
        self._data["show_scancodes"] = value
        self.save()

    @property
    def show_input_axis(self):
        """shows input axis values for axis inputs"""
        return self._get_data("show_input_axis", True)

    @show_input_axis.setter
    def show_input_axis(self, value):
        current = self.show_input_axis
        if current != value:
            self._set_data("show_input_axis", value)
            self.changed.emit("show_input_axis", value)

    @property
    def input_viewer_disables_repeaters(self):
        return self._get_data("input_viewer_disables_repeaters", False)

    @input_viewer_disables_repeaters.setter
    def input_viewer_disables_repeaters(self, value):
        current = self.input_viewer_disables_repeaters
        if current != value:
            self._set_data("input_viewer_disables_repeaters", value)
            self.changed.emit("input_viewer_disables_repeaters", value)

    @property
    def tab_list(self):# -> dict[Any, TabData] | None:# -> dict[Any, TabData] | None:
        """tab order for the UI devices as set by the user dict[tab_index : int, data: TabData]"""
        data = self._get_data("tab_device_order", None)
        # if data:
        #     # convert to tab data
        #     import gremlin.tabstate
        #     tab_map = {key:gremlin.tabstate.TabData.from_json(item) for key, item in data.items()}
        #     return tab_map
        return data

    @tab_list.setter
    def tab_list(self, tab_map):
        # convert the tab map to something serializable
        #data = {key:item.to_json() for key, item in tab_map.items()}
        self._data["tab_device_order"] = tab_map
        self.save()




    @property
    def device_visible_map(self) -> dict[str, bool]:
        return self._get_data("device-visibility", {})
    @device_visible_map.setter
    def device_visible_map(self, value : dict[str, bool]):
        self._set_data("device-visibility", value)

    @property
    def show_output_vjoy(self):
        """determines if VJOY output devices are displayed on the device tabs"""
        return self._get_data("show_vjoy_ouput", False)

    @show_output_vjoy.setter
    def show_output_vjoy(self, value):
        self._data["show_vjoy_output"] = value
        self.save()

    @property
    def last_plugin_folder(self):
        """last folder used for plugins"""
        return self._get_data("last_plugin_folder", None)

    @last_plugin_folder.setter
    def last_plugin_folder(self, value):
        self._data["last_plugin_folder"] = value
        self.save()

    @property
    def last_sound_folder(self):
        """last folder used for sounds"""
        return self._get_data("last_sound_folder", None)

    @last_sound_folder.setter
    def last_sound_folder(self, value):
        self._data["last_sound_folder"] = value
        self.save()

    @property
    def partial_plugin_save(self):
        """true if partial plugin configuration saving is ok = false nothing will be saved - true partial values will be saved"""
        return self._get_data("partial_plugin_init_ok", True)

    @partial_plugin_save.setter
    def partial_plugin_save(self, value):
        self._data["partial_plugin_init_ok"] = value
        self.save()

    @property
    def runtime_ui_active(self):
        """keep UI enabled at runtime"""
        return False  # disable for now as it can create conflicts
        # return self._get_data("runtime_ui_active",False)

    @runtime_ui_active.setter
    def runtime_ui_active(self, value):
        self._data["runtime_ui_active"] = value
        self.save()

    @property
    def sync_last_selection(self):
        """synchronizes the actions and container drop downs when enabled"""
        return self._get_data("sync_last_selection", True)

    @sync_last_selection.setter
    def sync_last_selection(self, value):
        self._data["sync_last_selection"] = value
        self.save()

    @property
    def last_keyboard_mapper_pulse_value(self):
        return self._get_data("last_keyboard_mapper_pulse_value", 250)

    @last_keyboard_mapper_pulse_value.setter
    def last_keyboard_mapper_pulse_value(self, value):
        self._data["last_keyboard_mapper_pulse_value"] = value
        self.save()

    @property
    def last_keyboard_mapper_interval_value(self):
        return self._get_data("last_keyboard_mapper_interval_value", 250)

    @last_keyboard_mapper_interval_value.setter
    def last_keyboard_mapper_interval_value(self, value):
        self._data["last_keyboard_mapper_interval_value"] = value
        self.save()

    @property
    def runtime_ignore_device_change(self):
        """ignore device changes at runtime"""
        return self._get_data("runtime_ignore_device_change", True)

    @runtime_ignore_device_change.setter
    def runtime_ignore_device_change(self, value):
        self._data["runtime_ignore_device_change"] = value
        self.save()

    @property
    def vigem_device_count(self):
        """count of gamepads to create for VIGEM - default is 0 (not enabled)"""
        return self._get_data("vigem_device_count", 0)

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
        """import mapping expansion level 0 to 4"""
        return self._get_data("import_level", 1)

    @import_level.setter
    def import_level(self, value):
        self._data["import_level"] = value
        self.save()

    @property
    def import_window_location(self):
        """Returns the position of the import profile"""
        return self._get_data("import_window_location", None)

    @import_window_location.setter
    def import_window_location(self, value):
        """Sets the position of the import profile window"""
        self._data["import_window_location"] = value
        self.save()

    @property
    def last_device_guid(self):
        """gets the last selected device guid"""
        device_guid = self._profile_data.get(
            "last_device_guid", None
        )  # try the profile specific config first
        if not device_guid:
            device_guid = self._get_data("last_device_guid", None)
        return device_guid

    @property
    def last_dinput_device_guid(self):
        """last device guid as a dinput GUID instead of a string"""
        guid = self.last_device_guid
        if guid:
            return gremlin.util.parse_guid(guid)
        return None

    @last_device_guid.setter
    def last_device_guid(self, device_guid):
        """stores the last device GUID"""
        device_guid = gremlin.util.normalize_guid(device_guid)
        self._data["last_device_guid"] = device_guid  # general config
        self._profile_data["last_device_guid"] = device_guid  # profile specific config
        self.save()
        self.save_profile()

    def set_last_input(
        self,
        device_guid,
        input_type: InputType,
        input_id,
        mode=None,
    ):
        """stores the last input"""

        import gremlin.joystick_handling

        if gremlin.shared_state.is_save_input_suspended():
            # don't save while tabs are loading
            return

        el = gremlin.event_handler.EventListener()
        if el.input_selection_suspended:
            # ignore selection requests if selection is suspended
            return

        device_guid = gremlin.util.normalize_guid(device_guid)
        data: dict = self._profile_data.get("last_input", {})
        if mode is None:
            mode = gremlin.shared_state.current_mode

        verbose = self.verbose_mode_inputs

        if input_type != InputType.ModeControl and isinstance(
            input_id, gremlin.base_classes.AbstractInputItem
        ):
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
                    syslog.warning(
                        f"CONFIG: SetLastInput(): Don't know how to handle input_id [{input_id}] type: {type(input_id).__name__}"
                    )
                    input_id = None
        elif isinstance(input_id, gremlin.keyboard.Key):
            input_id = input_id.key_id
        else:
            syslog.warning(
                f"CONFIG: SetLastInput(): Don't know how to handle input_id [{input_id}] type: {type(input_id).__name__}"
            )
            input_id = None

        input_type = InputType.convert(input_type)
        if input_type is not None:
            data[device_guid] = (input_type, input_id)

            self._profile_data["last_input"] = data
            self._profile_data["last_device_guid"] = device_guid

            self._data["last_device_guid"] = device_guid
            self._data["last_input_type"] = InputType.to_string(input_type)
            self._data["last_input_id"] = input_id
            self._data["last_input_mode"] = mode

            if verbose:
                device_name = gremlin.joystick_handling.device_name_from_guid(
                    device_guid
                )
                syslog.info(
                    f"CONFIG: SetLastInput(): {device_name} {InputType.to_string(input_type)} {input_id}"
                )

            self.save_profile()
            self.save()

    def _get_input_id(self, dinput_device_guid, input_id) -> tuple:
        """converts input ID from the storage data to the actual input ID that isn't stored in the config
        :returns:
        (input_type, save_input_id, input_id)  # input type, the save input ID is a configuration "save" value for saving data, input_id is the object

        """
        import gremlin.joystick_handling

        save_input_id = input_id
        input_type = None
        # syslog = logging.getLogger("system")
        device_name = gremlin.joystick_handling.device_name_from_guid(
            dinput_device_guid
        )
        if dinput_device_guid not in gremlin.shared_state.device_type_map:
            # input is missing
            # syslog.warning(f"Config: get last input: Unable to determine input type:  Unable to find device {dinput_device_guid} {device_name} in device map")
            return (None, None, None)

        # if input_id is None:
        #     syslog.warning(f"Config: get last input: Unable to determine input type: NULL input id")
        #     return (None, None, None)

        device_type = gremlin.shared_state.device_type_map[dinput_device_guid]
        match device_type:
            case DeviceType.Joystick | DeviceType.VJoy:
                device_info = gremlin.joystick_handling.getDevice(dinput_device_guid)
                if device_info:
                    if device_info.axis_count > 0:
                        input_type = InputType.JoystickAxis
                        if input_id is None or input_id > device_info.axis_count:
                            input_id = 1
                    elif device_info.button_count > 0:
                        input_type = InputType.JoystickButton
                        if input_id is None or input_id > device_info.button_count:
                            input_id = 1
                    elif device_info.hat_count > 0:
                        input_type = InputType.JoystickHat
                        if input_id is None or input_id > device_info.hat_count:
                            input_id = 1

            case DeviceType.Keyboard | DeviceType.Midi | DeviceType.Osc | DeviceType.State:
                # grab the tab widget
                if device_type == DeviceType.Keyboard:
                    input_type = InputType.KeyboardLatched
                elif device_type == DeviceType.Midi:
                    input_type = InputType.Midi
                elif device_type == DeviceType.Osc:
                    input_type = InputType.OpenSoundControl
                elif device_type == DeviceType.State:
                    input_type = DeviceType.State

                widget = gremlin.shared_state.ui.getRegisteredWidget(dinput_device_guid)
                # if dinput_device_guid in gremlin.ui._widget_device_index_map: # gremlin.shared_state.device_widget_map:
                #     widget = gremlin.shared_state.device_widget_map[dinput_device_guid]
                if widget:
                    if input_id is None:
                        item = widget.itemAt(0)
                        if item is not None:
                            save_input_id = item.guid
                    else:
                        count = widget.inputItemListModel.rows()
                        #found = False
                        save_input_id = input_id

                        if count:
                            item = next((item for item in widget.inputItemListModel if item.guid == input_id), None)
                            if item:
                                input_id = item
                                save_input_id = input_id.guid

                        #items = list(widget.inputItemListModel)
                        # for item in items:
                        #     if item.guid == input_id:
                        #         input_id = item
                        #         save_input_id = input_id.guid
                        #         found = True
                        #         break
                        # if not found and count > 0:
                        #     item = items[0]
                        #     input_id = item
                        #     save_input_id = input_id.guid
            case DeviceType.ModeControl:
                save_input_id = input_id
                input_type = InputType.ModeControl
            case DeviceType.Settings:
                input_type = InputType.NotSet
                input_id = None
                save_input_id = None
            case DeviceType.OctaviIFR1:
                save_input_id = input_id
                input_type = InputType.OctaviIfr1

            case DeviceType.NotSet:
                # settings or other non input type page
                input_type = InputType.NotSet
                save_input_id = None
                input_id = None
            case _:
                assert False, (
                    f"Config: GetInputId() Don't know how to handle device type: {device_type}  {device_name}"
                )

        if input_type is None or input_id is None:
            # syslog.warning(f"Config: get last input: Unable to determine input type for device {dinput_device_guid} {device_name}")
            return (None, None, None)

        return (input_type, save_input_id, input_id)

    def get_last_input(
        self, device_guid=None, return_mode=False
    ) -> tuple:  # (device_guid, input_type, input_id, mode)
        """gets the last input for a given device

        :param device_guid: (optional) the device to look for - if None - uses the last known device
        :returns tuple: (device_guid, input_type, input_id)

        """

        # syslog = logging.getLogger("system")
        verbose = self.verbose_mode_details

        if device_guid is None:
            # get the last profile device guid saved to config

            device_guid = self._get_data("last_device_guid", None)
            input_type = self._get_data("last_input_type", None)
            if input_type:
                input_type = InputType.to_enum(input_type)
            input_id = self._get_data("last_input_id", None)

            if (
                device_guid is not None
                and input_type is not None
                and input_id is not None
            ):
                if return_mode:
                    mode = self._get_data("last_input_mode", None)
                    if mode is not None:
                        return (device_guid, input_type, input_id, mode)
                else:
                    return (device_guid, input_type, input_id)

            if device_guid is None:
                if not self._profile_config_fname:
                    self.ensure_profile(gremlin.shared_state.current_profile)
                device_guid = self._profile_data.get("last_device_guid", None)

        if device_guid is None:
            if return_mode:
                return (None, None, None, None)
            return (None, None, None)

        device = gremlin.joystick_handling.getDevice(device_guid)
        if not device:
            # device not found
            if return_mode:
                return (None, None, None, None)
            return (None, None, None)

        if verbose:
            device_name = device.name

        mode = gremlin.shared_state.edit_mode  # current mode
        dinput_device_guid = device.device_guid
        device_guid = device.device_id

        data: dict = self._profile_data.get("last_input", {})
        if device_guid in data:
            input_type, input_id = data[device_guid]

            try:
                input_type = InputType.to_enum(input_type)
            except Exception:
                syslog.error(
                    f"CONFIG: GetLastInput(): unable to convert input type {input_type} to a known type"
                )
                input_type = InputType.NotSet

            if input_id is not None and isinstance(input_id, int):
                if return_mode:
                    return (device_guid, input_type, input_id, mode)
                if verbose:
                    syslog.info(
                        f"CONFIG: GetLastInput(): {device_guid} {device_name} {input_type} {input_id}"
                    )
                return (device_guid, input_type, input_id)

            if input_id is not None:
                input_type, save_input_id, input_id = self._get_input_id(
                    dinput_device_guid, input_id
                )
                if input_type is None:
                    if verbose:
                        syslog.info(
                            f"CONFIG: GetLastInput(): nothing found for {device_guid} {device_name}"
                        )
                    if return_mode:
                        return (None, None, None, None)
                    return (None, None, None)
                if verbose:
                    syslog.info(
                        f"CONFIG: GetLastInput(): {device_guid} {device_name} {input_type} {input_id}"
                    )

                try:
                    input_type = InputType.to_enum(input_type)
                except Exception:
                    syslog.error(
                        f"CONFIG: GetLastInput(): unable to convert input type {input_type} to a known type"
                    )
                    input_type = InputType.NotSet
                if return_mode:
                    return (device_guid, input_type, input_id, mode)
                return (device_guid, input_type, input_id)

        # provide a suitable default for the input
        input_id = None
        if dinput_device_guid in gremlin.shared_state.device_type_map:
            input_type, save_input_id, input_id = self._get_input_id(
                dinput_device_guid, input_id
            )
            if input_type is not None and input_id is not None:
                # save the new defaults
                data[device_guid] = (input_type, save_input_id)
                self._profile_data["last_input"] = data
                self.save_profile()
                if verbose:
                    syslog.info(
                        f"CONFIG: GetLastInput(): {device_guid} {device_name} {input_type} {input_id}"
                    )

                if return_mode:
                    return (device_guid, input_type, input_id, mode)
                return (device_guid, input_type, input_id)

        if verbose:
            syslog.info(
                f"CONFIG: GetLastInput(): nothing found for {device_guid} {device_name}"
            )
        if return_mode:
            return (None, None, None, None)
        return (None, None, None)

    def get_last_device_guid(self):
        """gets the last selected device in the profile"""
        device_guid = self._profile_data.get("last_device_guid", None)
        if device_guid is None:
            device_guid = self._get_data("last_device_guid", None)
        return device_guid

    def get_last_input_for_device(self, device_guid) -> tuple:  # (input_type, input_id)
        """gets the last input for the device as a tuple (input_type, input_id)"""
        data = self.get_last_input(device_guid)
        if data:
            return (data[1], data[2])

        return None

    def ensure_profile(self, profile):
        """called when a new profile is created"""

        if not profile or not profile.profile_file:
            return  # nothing to do - no profile

        if self._profile_fname == profile.profile_file:
            return  # nothing to do - same profile

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
        return self._get_data("debug_ui", False)

    @debug_ui.setter
    def debug_ui(self, value):
        self._data["debug_ui"] = value
        self.save()

    @property
    def button_grid_visible(self) -> bool:
        """default state of the button grid in vjoy remap"""
        return self._get_data("button_grid_visible", False) # off by default

    @button_grid_visible.setter
    def button_grid_visible(self, value: bool):
        self._data["button_grid_visible"] = value
        self.save()

    @property
    def midi_enabled(self) -> bool:
        """true if MIDI support is enabled"""
        if self._midi_enabled is None:
            from gremlin.ui.midi_device import MidiInterface

            midi = MidiInterface()
            self._midi_enabled = midi.midi_enabled and self._get_data(
                "midi_enabled", True
            )
        return self._midi_enabled

    @midi_enabled.setter
    def midi_enabled(self, value: bool):
        self._data["midi_enabled"] = value
        self._midi_enabled = None  # force a re-read

    @property
    def osc_enabled(self) -> bool:
        """True if OSC support is enabled"""
        if self._osc_enabled is None:
            self._osc_enabled = self._get_data("osc_enabled", True)
        return self._osc_enabled

    @osc_enabled.setter
    def osc_enabled(self, value: bool):
        self._data["osc_enabled"] = value
        self._osc_enabled = None  # force a re-read

    @property
    def osc_pad_args(self) -> bool:
        """true if no arg commands should pad with a default arg value"""
        return self._get_data("osc_pad_args", True)

    @osc_pad_args.setter
    def osc_pad_args(self, value: bool):
        self._set_data("osc_pad_args", value)

    @property
    def osc_last_target_ip(self) -> str:
        return self._get_data("osc_last_target_ip", None)

    @osc_last_target_ip.setter
    def osc_last_target_ip(self, target_ip: str):
        self._set_data("osc_last_target_ip", target_ip)

    @property
    def osc_last_target_port(self) -> int:
        return self._get_data("osc_last_target_port", 0)

    @osc_last_target_port.setter
    def osc_last_target_port(self, port: int):
        self._set_data("osc_last_target_port", port)

    # @property
    # def splitter_pos(self) -> int:
    #     ''' splitter config  '''
    #     return self._get_data("splitter_config", 250)

    # @splitter_pos.setter
    # def splitter_pos(self, data : int):
    #     self._data["splitter_config"] = data

    @property
    def mapping_rollover_mode(self):
        return self._get_data("mapping_rollover_mode", 1)

    @mapping_rollover_mode.setter
    def mapping_rollover_mode(self, mode: int):
        self._data["mapping_rollover_mode"] = mode
        self.save()

    @property
    def mapping_vjoy_id(self):
        return self._get_data("mapping_vjoy_id", 1)

    @mapping_vjoy_id.setter
    def mapping_vjoy_id(self, id: int):
        self._data["mapping_vjoy_id"] = id
        self.save()

    @property
    def convert_response_curve(self):
        return self._get_data("convert_response_curve", True)

    @convert_response_curve.setter
    def convert_response_curve(self, value: bool):
        self._data["convert_response_curve"] = value
        self.save()

    @property
    def convert_vjoy_remap(self):
        return self._get_data("convert_vjoy_remap", False)

    @convert_vjoy_remap.setter
    def convert_vjoy_remap(self, value: bool):
        self._data["convert_vjoy_remap"] = value
        self.save()

    @property
    def numlock_off(self) -> bool:
        """force numlock off - global setting"""
        return self._get_data("numlock_off", True)

    @numlock_off.setter
    def numlock_off(self, value: bool):
        self._data["numlock_off"] = value
        self.save()

    @property
    def condition_selector(self) -> str:
        """last selected condition selector"""
        return self._get_data("condition_selector", "Joystick Condition")

    @condition_selector.setter
    def condition_selector(self, value: str):
        self._data["condition_selector"] = value
        self.save()

    @property
    def experimental(self) -> bool:
        """true if internal dev mode"""
        return self._get_data("experimental", False)

    @experimental.setter
    def experimental(self, value: bool):
        self._data["experimental"] = value
        self.save()

    @property
    def show_input_enable(self) -> bool:
        return self._get_data("show_input_enable", False)

    @show_input_enable.setter
    def show_input_enable(self, value: bool):
        # override as this is not implemented yet
        return False
        self._data["show_input_enable"] = value
        self.save()

    def getWindowSize(self, key: str):
        """gets window geometry size"""
        data = self._get_data("window_geo_size", {})
        if key in data:
            return data[key]
        return None

    def setWindowSize(self, key: str, width: int, height: int):
        """sets window geometry size"""
        data = self._get_data("window_geo_size", {})
        data[key] = [width, height]
        self._data["window_geo_size"] = data
        self.save()

    def getWindowLocation(self, key: str):
        """gets window geometry location"""
        data = self._get_data("window_geo_loc", {})
        if key in data:
            return data[key]
        return None

    def setWindowLocation(self, key: str, x: int, y: int):
        """sets window geometry location"""
        data = self._get_data("window_geo_loc", {})
        data[key] = [x, y]
        self._data["window_geo_loc"] = data
        self.save()

    def clearWindowData(self):
        """resets saved window data"""
        self._data["window_geo_loc"] = {}
        self._data["window_geo_size"] = {}
        self.save()

    @property
    def backup_count(self) -> int:
        return self._get_data("backup_count", 5)

    @backup_count.setter
    def backup_count(self, value: int):
        if value < 0:
            value = 0
        elif value > 50:
            value = 50
        self._data["backup_count"] = value
        self.save()

    @property
    def start_on_f5(self) -> bool:
        return self._get_data("start_on_f5", False)

    @start_on_f5.setter
    def start_on_f5(self, value: bool):
        self._data["start_on_f5"] = value
        self.save()

    @property
    def keyboard_repeater_invert_display(self) -> bool:
        return self._get_data("keyboard_repeater_invert_display", False)

    @keyboard_repeater_invert_display.setter
    def keyboard_repeater_invert_display(self, value: bool):
        self._data["keyboard_repeater_invert_display"] = value
        self.save()

    @property
    def keyboard_repeater_capture_mouse(self) -> bool:
        return self._get_data("keyboard_repeater_capture_mouse", False)

    @keyboard_repeater_capture_mouse.setter
    def keyboard_repeater_capture_mouse(self, value: bool):
        self._data["keyboard_repeater_capture_mouse"] = value
        self.save()

    @property
    def keyboard_repeater_show(self) -> bool:
        return self._get_data("keyboard_repeater_show", True)

    @keyboard_repeater_show.setter
    def keyboard_repeater_show(self, value: bool):
        self._data["keyboard_repeater_show"] = value
        self.save()

    @property
    def theme(self) -> str:
        return self._get_data("theme", "auto")

    @theme.setter
    def theme(self, value: str):
        if value:
            value = value.casefold()
            if value in ("auto", "light", "dark"):
                self._data["theme"] = value
                self.save()

    @property
    def keySize(self) -> int:
        """size of keys for the virtual keyboard"""
        return self._get_data("keySize", 1)

    @keySize.setter
    def keySize(self, value: int):
        self._data["keySize"] = value
        self.save()

    @property
    def splitJoystickRepeater(self) -> bool:
        return self._get_data("splitJoystickRepeater", False)

    @splitJoystickRepeater.setter
    def splitJoystickRepeater(self, value: bool):
        self._set_data("splitJoystickRepeater", value)

    @property
    def showJoystickRepeaterTooltip(self) -> bool:
        return self._get_data("showJoystickRepeaterTooltip", False)

    @showJoystickRepeaterTooltip.setter
    def showJoystickRepeaterTooltip(self, value: bool):
        self._set_data("showJoystickRepeaterTooltip", value)

    @property
    def hostIp(self) -> str:
        """host IP"""
        return self._get_data("host_ip", "")

    @hostIp.setter
    def hostIp(self, value: str):
        self._data["host_ip"] = value
        self.save()

    @property
    def mouse_wheel_autorelease_delay(self) -> float:
        """wheel event autorelease timeout in seconds"""
        return self._get_data("wheel_autorelease_delay", 0.5)

    @mouse_wheel_autorelease_delay.setter
    def mouse_wheel_autorelease_delay(self, value: float):
        assert value > 0
        self._data["wheel_autorelease_delay"] = value
        self.save()

    @property
    def show_container_id(self) -> bool:
        return self._get_data("show_container_id", False)

    @show_container_id.setter
    def show_container_id(self, value: bool):
        if value != self.show_container_id:
            self._data["show_container_id"] = value
            self.save()

            el = gremlin.event_handler.EventListener()
            el.show_container_id_changed.emit()

    @property
    def range_comparison_decimals(self) -> int:
        """decimals to use for range comparison comparing two floating point numbers"""
        return self._get_data("range_comparison_decimals", 3)

    @range_comparison_decimals.setter
    def range_comparison_decimals(self, value: int):
        assert value >= 0
        self._data["range_comparison_decimals"] = value
        self.save()

    def _get_key(self):
        """gets the gremlin registry entry"""
        import winreg

        software_key = winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, r"SOFTWARE\\")
        return winreg.CreateKey(software_key, "GremlinEx")

    def _set_registry(self, field, value):
        """writes a value to the windows registry for the app"""
        import winreg

        key = self._get_key()
        winreg.SetValueEx(key, field, 0, winreg.REG_SZ, str(value))
        winreg.CloseKey(key)

    def _get_registry(self, field, type_cast, default_value=None):
        """gets a value from the windows registry for the app"""
        import winreg
        import gremlin.util

        key = self._get_key()
        try:
            str_value, type = winreg.QueryValueEx(key, field)
            if str_value:
                if type_cast is bool:
                    value = gremlin.util.str_to_bool(str_value)
                else:
                    value = type_cast(str_value)
                return value
            return default_value
        except Exception:
            # not found
            return default_value
        finally:
            winreg.CloseKey(key)

    @property
    def enable_log_version(self) -> bool:
        value = self._get_registry("enable_log_version", bool, False)
        return value

    @enable_log_version.setter
    def enable_log_version(self, value: bool):
        self._set_registry("enable_log_version", value)

    @property
    def filter_axis_events(self) -> bool:
        """true if axis data filtering is enabled"""
        return self._get_data("filter_axis_events", False)

    @filter_axis_events.setter
    def filter_axis_events(self, value: bool):
        if value != self.filter_axis_events:
            self._data["filter_axis_events"] = value
            self.save()
            self.changed.emit("filter_axis_events", value)

    @property
    def filter_axis_threshold(self) -> float:
        """axis filter deviation threshold"""
        return self._get_data("filter_axis_threshold", 0.002)

    @filter_axis_threshold.setter
    def filter_axis_threshold(self, value: float):
        if self.filter_axis_threshold != value and value >= 0 and value <= 1.0:
            self._data["filter_axis_threshold"] = value
            self.save()
            self.changed.emit("filter_axis_threshold", value)

    @property
    def input_viewer_button_size(self) -> int:
        return self._get_data("input_viewer_button_size", 16)

    @input_viewer_button_size.setter
    def input_viewer_button_size(self, value: int):
        self._data["input_viewer_button_size"] = value
        self.save()
        self.changed.emit("input_viewer_button_size", value)

    # state device filter options

    @property
    def state_category_filter(self) -> str:
        """category filter for the state device"""
        return self._get_data("state_category_filter", None)

    @state_category_filter.setter
    def state_category_filter(self, value: str):
        self._data["state_category_filter"] = value
        self.save()

    @property
    def state_filter_enabled(self) -> bool:
        """enables state filtering in the state device"""
        return self._get_data("state_filter_enabled", False)

    @state_filter_enabled.setter
    def state_filter_enabled(self, value: bool):
        self._data["state_filter_enabled"] = value
        self.save()

    @property
    def state_filter(self) -> str:
        """state  filter for the state device"""
        return self._get_data("state_filter", None)

    @state_filter.setter
    def state_filter(self, value: str):
        self._data["state_filter"] = value
        self.save()

    # input viewer filter options for state

    @property
    def iv_state_category_filter(self) -> str:
        """category filter for the state device"""
        return self._get_data("iv_state_category_filter", None)

    @iv_state_category_filter.setter
    def iv_state_category_filter(self, value: str):
        self._data["iv_state_category_filter"] = value
        self.save()

    @property
    def iv_state_filter_enabled(self) -> bool:
        """enables state filtering in the state device"""
        return self._get_data("iv_state_filter_enabled", False)

    @iv_state_filter_enabled.setter
    def iv_state_filter_enabled(self, value: bool):
        self._data["iv_state_filter_enabled"] = value
        self.save()

    @property
    def iv_state_filter(self) -> str:
        """state  filter for the input viewer state device"""
        return self._get_data("iv_state_filter", None)

    @iv_state_filter.setter
    def iv_state_filter(self, value: str):
        self._data["iv_state_filter"] = value
        self.save()

    @property
    def state_last_search_term(self) -> str:
        """last search term for an state item"""
        return self._get_data("state_last_search_term", "")

    @state_last_search_term.setter
    def state_last_search_term(self, value: str):
        self._data["state_last_search_term"] = value
        self.save()

    @property
    def osc_filter(self) -> str:
        """message filter for the osc device"""
        return self._get_data("osc_filter", None)

    @osc_filter.setter
    def osc_filter(self, value: str):
        self._data["osc_filter"] = value
        self.save()

    @property
    def osc_last_search_term(self) -> str:
        """last search term for an OSC item"""
        return self._get_data("osc_last_search_term", "")

    @osc_last_search_term.setter
    def osc_last_search_term(self, value: str):
        self._data["osc_last_search_term"] = value
        self.save()

    @property
    def osc_filter_enabled(self) -> bool:
        """enables osc filtering in the osc device"""
        return self._get_data("osc_filter_enabled", False)

    @osc_filter_enabled.setter
    def osc_filter_enabled(self, value: bool):
        self._data["osc_filter_enabled"] = value
        self.save()

    @property
    def import_prompt_enabled(self) -> bool:
        """enables import prompt dialog box on missing devices"""
        return self._get_data("import_prompt_enabled", True)

    @import_prompt_enabled.setter
    def import_prompt_enabled(self, value: bool):
        self._data["import_prompt_enabled"] = value
        self.save()

    @property
    def auto_load_disabled(self) -> bool:
        return self._auto_load_disabled

    @auto_load_disabled.setter
    def auto_load_disabled(self, value):
        self._auto_load_disabled = value

    @property
    def show_simconnect_options_on_toolbar(self) -> bool:
        return self._get_data("show_simconnect_options_on_toolbar", False)

    @show_simconnect_options_on_toolbar.setter
    def show_simconnect_options_on_toolbar(self, value: bool):
        self._set_data("show_simconnect_options_on_toolbar", value)

    @property
    def simconnect_auto_mode_lock(self) -> bool:
        return self._get_data("simconnect_auto_mode_lock", True)

    @simconnect_auto_mode_lock.setter
    def simconnect_auto_mode_lock(self, value: bool):
        self._set_data("simconnect_auto_mode_lock", value)

    @property
    def simconnect_auto_mode_select(self) -> bool:
        return self._get_data("simconnect_auto_mode_select", True)

    @simconnect_auto_mode_select.setter
    def simconnect_auto_mode_select(self, value: bool):
        self._set_data("simconnect_auto_mode_select", value)

    @property
    def simconnect_stop_profile_on_sim_stop(self) -> bool:
        return self._get_data("simconnect_stop_profile_on_sim_stop", True)

    @simconnect_stop_profile_on_sim_stop.setter
    def simconnect_stop_profile_on_sim_stop(self, value: bool):
        self._set_data("simconnect_stop_profile_on_sim_stop", value)

    @property
    def simconnect_enabled(self) -> bool:
        return self._get_data("simconnect_enabled", False)

    @simconnect_enabled.setter
    def simconnect_enabled(self, value: bool):
        self._set_data("simconnect_enabled", value)

    @property
    def last_control_action(self):
        import gremlin.types

        value = self._get_data(
            "last_control_action", gremlin.types.ControlAction.TTSAbort
        )
        return gremlin.types.ControlAction(value)

    @last_control_action.setter
    def last_control_action(self, value):
        self._set_data("last_control_action", value)

    @property
    def hide_default_mode(self):
        return self._get_data("hide_default_mode", False)

    @hide_default_mode.setter
    def hide_default_mode(self, value: bool):
        self._set_data("hide_default_mode", value)

    @property
    def show_parent_mode(self):
        return self._get_data("show_parent_mode", False)

    @show_parent_mode.setter
    def show_parent_mode(self, value: bool):
        self._set_data("show_parent_mode", value)

    @property
    def allow_exec_tree_container_validation_fail(self):
        return self._get_data("allow_exec_tree_container_validation_fail", True)

    @allow_exec_tree_container_validation_fail.setter
    def allow_exec_tree_container_validation_fail(self, value: bool):
        self._set_data("allow_exec_tree_container_validation_fail", value)

    @property
    def vjoy_loopback_use_time(self):
        return self._get_data("vjoy_loopback_use_time", True)

    @vjoy_loopback_use_time.setter
    def vjoy_loopback_use_time(self, value: bool):
        self._set_data("vjoy_loopback_use_time", value)

    @property
    def vjoy_loopback_delay(self):
        return self._get_data("vjoy_loopback_delay", 250)

    @vjoy_loopback_delay.setter
    def vjoy_loopback_delay(self, value: int):
        self._set_data("vjoy_loopback_delay", value)

    @property
    def macro_last_device_id(self):
        """id of the last device selected as an input for macros"""
        return self._get_data("macro_last_device_id", "")

    @macro_last_device_id.setter
    def macro_last_device_id(self, id: str):
        self._set_data("macro_last_device_id", id)

    @property
    def macro_last_input_type(self):
        """id of the last device input type as an input for macros"""
        return self._get_data("macro_last_input_type", "")

    @macro_last_input_type.setter
    def macro_last_input_type(self, input_type):
        self._set_data("macro_last_input_type", input_type)

    @property
    def macro_last_input_id(self):
        """id of the last device input type as an input for macros"""
        return self._get_data("macro_last_input_id", "")

    @macro_last_input_id.setter
    def macro_last_input_id(self, id):
        self._set_data("macro_last_input_id", id)

    @property
    def vjoy_show_disconnected(self) -> bool:
        return self._get_data("vjoy_show_disconnected", False)

    @vjoy_show_disconnected.setter
    def vjoy_show_disconnected(self, value: bool):
        self._set_data("vjoy_show_disconnected", value)

    @property
    def show_disconnected(self) -> bool:
        return self._get_data("show_disconnected", False)

    @show_disconnected.setter
    def show_disconnected(self, value: bool):
        self._set_data("show_disconnected", value)

    @property
    def graphviz_executable(self) -> str:
        """path to graph viz executable"""
        return self._get_data("graphviz_executable", "")

    @graphviz_executable.setter
    def graphviz_executable(self, value: str):
        self._set_data("graphviz_executable", value)

    """ report options """

    @property
    def ReportPdfEnabled(self) -> bool:
        return self._get_data("ReportPdfEnabled", True)

    @ReportPdfEnabled.setter
    def ReportPdfEnabled(self, value: bool):
        self._set_data("ReportPdfEnabled", value)

    @property
    def ReportSvgEnabled(self) -> bool:
        return self._get_data("ReportSvgEnabled", False)

    @ReportSvgEnabled.setter
    def ReportSvgEnabled(self, value: bool):
        self._set_data("ReportSvgEnabled", value)

    @property
    def ReportOpenFilesEnabled(self) -> bool:
        return self._get_data("ReportOpenFilesEnabled", True)

    @ReportOpenFilesEnabled.setter
    def ReportOpenFilesEnabled(self, value: bool):
        self._set_data("ReportOpenFilesEnabled", value)

    @property
    def ReportShowFolder(self) -> bool:
        return self._get_data("ReportShowFolder", False)

    @ReportShowFolder.setter
    def ReportShowFolder(self, value: bool):
        self._set_data("ReportShowFolder", value)

    @property
    def TTSDefaultVoiceIndex(self) -> int:
        return self._get_data("TTSDefaultVoiceIndex", 0)

    @TTSDefaultVoiceIndex.setter
    def TTSDefaultVoiceIndex(self, value: int):
        self._set_data("TTSDefaultVoiceIndex", value)

    @property
    def trigger_last_device_id(self):
        """id of the last device selected as an input for triggers"""
        return self._get_data("trigger_last_device_id", "")

    @trigger_last_device_id.setter
    def trigger_last_device_id(self, id: str):
        self._set_data("trigger_last_device_id", id)

    @property
    def trigger_last_input_type(self):
        """id of the last device input type as an input for triggers"""
        return self._get_data("trigger_last_input_type", "")

    @trigger_last_input_type.setter
    def trigger_last_input_type(self, input_type):
        self._set_data("trigger_last_input_type", input_type)

    @property
    def trigger_last_input_id(self):
        """id of the last device input type as an input for triggers"""
        return self._get_data("trigger_last_input_id", 1)

    @trigger_last_input_id.setter
    def trigger_last_input_id(self, id):
        self._set_data("trigger_last_input_id", id)

    def _ensure_visual_hidden_map(self):
        if self._visuals_hidden_map is None:
            visuals = self._get_data("visuals_hide_map", None)
            if visuals is None:
                self._set_data("visuals_hide_map", {})
                visuals = {}
            self._visuals_hidden_map = visuals

    def visualHidden(self, key: str) -> bool:
        """true if the visual is marked hidden"""
        self._ensure_visual_hidden_map()
        if key in self._visuals_hidden_map:
            return self._visuals_hidden_map[key]
        return False

    def visualVisible(self, key: str) -> bool:
        """true if the visual is marked visible"""
        return not self.visualHidden(key)

    def setVisualHidden(self, key: str, value: bool):
        self._ensure_visual_hidden_map()
        self._visuals_hidden_map[key] = value
        self._set_data("visuals_hide_map", self._visuals_hidden_map)

    def resetVisualHidden(self):
        """resets all hidden visuals to visible"""
        self._set_data("visuals_hide_map", {})
        self._visuals_hidden_map = {}

    @property
    def input_viewer_combine_buttonhats(self) -> bool:
        """option to combine buttons and hats in the input viewer"""
        return self._get_data("input_viewer_combine_buttonhats", True)

    @input_viewer_combine_buttonhats.setter
    def input_viewer_combine_buttonhats(self, value: bool):
        self._set_data("input_viewer_combine_buttonhats", value)

    @property
    def input_viewer_flow_layout(self) -> bool:
        """option for the input viewer to show as a flow layout"""
        return self._get_data("input_viewer_flow_layout", False)

    @input_viewer_flow_layout.setter
    def input_viewer_flow_layout(self, value: bool):
        self._set_data("input_viewer_flow_layout", value)

    @property
    def device_filter_max_axis(self) -> int:
        return self._get_data("device_filter_max_axis", 4)

    @device_filter_max_axis.setter
    def device_filter_max_axis(self, value: int):
        self._set_data("device_filter_max_axis", value)

    @property
    def device_filter_max_button(self) -> int:
        return self._get_data("device_filter_max_button", 8)

    @device_filter_max_button.setter
    def device_filter_max_button(self, value: int):
        self._set_data("device_filter_max_button", value)

    @property
    def device_filter_max_hat(self) -> int:
        return self._get_data("device_filter_max_hat", 1)

    @device_filter_max_hat.setter
    def device_filter_max_hat(self, value: int):
        self._set_data("device_filter_max_hat", value)

    @property
    def axis_spam_delay(self) -> float:
        """axis filter delay"""
        return self._get_data("axis_spam_delay", 1 / 1000)

    @axis_spam_delay.setter
    def axis_spam_delay(self, value: float):
        if value < 0:
            value = 0
        self._set_data("axis_spam_delay", value)

    @property
    def axis_spam_delta(self) -> float:
        """axis filter delay"""
        return self._get_data("axis_spam_delta", 0.001)

    @axis_spam_delta.setter
    def axis_spam_delta(self, value: float):
        if value < 0:
            value = 0
        self._set_data("axis_spam_delta", value)

    @property
    def ai_tts_last_speaker(self) -> str:
        return self._get_data("ai_tts_last_speaker", None)

    @ai_tts_last_speaker.setter
    def ai_tts_last_speaker(self, value: str):
        self._set_data("ai_tts_last_speaker", value)

    @property
    def ai_tts_save_on_generate(self) -> str:
        return self._get_data("ai_tts_save_on_generate", None)

    @ai_tts_save_on_generate.setter
    def ai_tts_save_on_generate(self, value: str):
        self._set_data("ai_tts_save_on_generate", value)

    @property
    def ai_tts_use_word_filenames(self) -> str:
        return self._get_data("ai_tts_use_word_filenames", None)

    @ai_tts_use_word_filenames.setter
    def ai_tts_use_word_filenames(self, value: str):
        self._set_data("ai_tts_use_word_filenames", value)

    @property
    def ai_tts_overwrite_filenames(self) -> str:
        return self._get_data("ai_tts_overwrite_filenames", None)

    @ai_tts_overwrite_filenames.setter
    def ai_tts_overwrite_filenames(self, value: str):
        self._set_data("ai_tts_overwrite_filenames", value)

    @property
    def gated_axis_display_events(self) -> bool:
        """option for the gated axis action to show or hide events"""
        return self._get_data("gated_axis_display_events", True)

    @gated_axis_display_events.setter
    def gated_axis_display_events(self, value: bool):
        self._set_data("gated_axis_display_events", value)

    @property
    def gated_axis_last_gate_condition(self):
        import gremlin.gated_handler

        value = self._get_data(
            "gated_axis_last_gate_condition",
            gremlin.gated_handler.GateConditionType.OnCross.value,
        )
        return gremlin.gated_handler.GateConditionType(value)

    @gated_axis_last_gate_condition.setter
    def gated_axis_last_gate_condition(self, condition):
        self._set_data("gated_axis_last_gate_condition", condition.value)

    @property
    def gated_axis_last_range_condition(self):
        import gremlin.gated_handler

        value = self._get_data(
            "gated_axis_last_range_condition",
            gremlin.gated_handler.GateConditionType.InRange.value,
        )
        return gremlin.gated_handler.GateConditionType(value)

    @gated_axis_last_range_condition.setter
    def gated_axis_last_range_condition(self, condition):
        self._set_data("gated_axis_last_range_condition", condition.value)

    @property
    def auto_calibrate(self) -> bool:
        """option for auto calibration in the calibrate window"""
        return self._get_data("auto_calibrate", True)

    @auto_calibrate.setter
    def auto_calibrate(self, value: bool):
        self._set_data("auto_calibrate", value)

    @property
    def log_description(self) -> bool:
        """option to have the description action log an entry to the log file"""
        return self._get_data("log_description", False)

    @log_description.setter
    def log_description(self, value: bool):
        self._set_data("log_description", value)

    @property
    def max_concurrent_macro(self) -> int:
        """max number of macros that can execute at the same time"""
        return self._get_data("max_concurrent_macro", 0)

    @max_concurrent_macro.setter
    def max_concurrent_macro(self, value: int):
        self._set_data("max_concurrent_macro", value)

    @property
    def max_concurrent_sequence(self) -> int:
        """max number of sequences that can execute at the same time"""
        return self._get_data("max_concurrent_sequence", 0)

    @max_concurrent_sequence.setter
    def max_concurrent_sequence(self, value: int):
        self._set_data("max_concurrent_sequence", value)

    @property
    def macro_mode_affinity(self) -> bool:
        """controls macro mode affinity (attaches macros to a specific mode - if off, the macro will stop when the mode is changed)"""
        return self._get_data("macro_mode_affinity", True)

    @macro_mode_affinity.setter
    def macro_mode_affinity(self, value: bool):
        self._set_data("macro_mode_affinity", value)

    @property
    def mode_change_aborts_sequence(self) -> bool:
        """true if a mode change while a macro or sequence is running can abort the macro or executing sequence - if not set the mode change is delayed until all macros/sequences are done"""
        return self._get_data("mode_change_aborts_sequence", False)

    @mode_change_aborts_sequence.setter
    def mode_change_aborts_sequence(self, value: bool):
        self._set_data("mode_change_aborts_sequence", value)

    @property
    def macro_default_pause_value(self) -> float:
        """default pause value for the macro pause"""
        return self._get_data("macro_default_pause_value", 0.250)

    @macro_default_pause_value.setter
    def macro_default_pause_value(self, value: float):
        self._set_data("macro_default_pause_value", value)

    @property
    def pause_action_default_pause_value(self) -> float:
        """default pause value for the pause action"""
        return self._get_data("pause_action_default_pause_value", 0.250)

    @pause_action_default_pause_value.setter
    def pause_action_default_pause_value(self, value: float):
        self._set_data("pause_action_default_pause_value", value)

    @property
    def dropdown_use_mouse_wheel(self) -> bool:
        """true if UI combo boxes use the mouse wheel to change values"""
        return self._get_data("dropdown_use_mouse_wheel", False)

    @dropdown_use_mouse_wheel.setter
    def dropdown_use_mouse_wheel(self, value: bool):
        self._set_data("dropdown_use_mouse_wheel", value)

    @property
    def hid_list_enabled(self) -> bool:
        """true if GEX should enumerate HID devices"""
        return self._get_data("hid_list_enabled", False)

    @hid_list_enabled.setter
    def hid_list_enabled(self, value: bool):
        self._set_data("hid_list_enabled", value)

    @property
    def ui_max_input_maps(self) -> int:
        return self._get_data("ui_max_input_maps", 20)

    @ui_max_input_maps.setter
    def ui_max_input_maps(self, value: int):
        self._set_data("ui_max_input_maps", value)

    @property
    def ui_max_input_enabled(self) -> bool:
        return self._get_data("ui_max_input_enabled", True)

    @ui_max_input_enabled.setter
    def ui_max_input_enabled(self, value: bool):
        self._set_data("ui_max_input_enabled", value)


    @property
    def last_reorder_file(self) -> str:
        """last reorder file used for device tabs"""
        return self._get_data("last_reorder_file","")
    @last_reorder_file.setter
    def last_reorder_file(self, value: str):
        self._set_data("last_reorder_file", value)