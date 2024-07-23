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


import threading


"""Stores global state that needs to be shared between various
parts of the program.

This is ugly but the only sane way to do this at the moment.
"""

root_path = None # root path

# Flag indicating whether or not input highlighting should be
# prevented even if it is enabled by the user
_suspend_input_highlighting = False

# Timer used to disable input highlighting with a delay
_suspend_timer = None

# Holds the currently active profile
current_profile = None

current_mode = None

# holds the main UI reference
ui = None

# holds debug information for callbacks
_callback_map = {}

# true if a profile is running
is_running = False

# true if UI keyboard should be ignored (such as, when listening to keys)
_suspend_ui_keyinput = 0

# list of device names to their GUID
device_guid_to_name_map = {} 

def get_device_name(guid):
    ''' gets the device name from the UUID'''
    if not guid in device_guid_to_name_map.keys():
        return "[Unknown]"
    return device_guid_to_name_map[guid]

def ui_keyinput_suspended():
    global _suspend_ui_keyinput
    return _suspend_ui_keyinput > 0

def push_suspend_ui_keyinput():
    ''' suspends keyboard input to the UI'''
    global _suspend_ui_keyinput
    _suspend_ui_keyinput += 1

def pop_suspend_ui_keyinput():
    ''' restores keyboard input to the UI'''
    global _suspend_ui_keyinput
    if _suspend_ui_keyinput > 0:
        _suspend_ui_keyinput -= 1

def suspend_input_highlighting():
    """Returns whether or not input highlighting is suspended.

    :return True if input's are not automatically selected, False otherwise
    """
    return _suspend_input_highlighting


def set_suspend_input_highlighting(value):
    """Sets the input highlighting behaviour.

    :param value if True disables automatic selection of used inputs, if False
        inputs will automatically be selected upon use
    """
    global _suspend_input_highlighting, _suspend_timer
    if _suspend_timer is not None:
        _suspend_timer.cancel()
    _suspend_input_highlighting = value


def delayed_input_highlighting_suspension():
    """Disables input highlighting with a delay."""
    global _suspend_timer
    if _suspend_timer is not None:
        _suspend_timer.cancel()

    _suspend_timer = threading.Timer(
            2,
            lambda: set_suspend_input_highlighting(False)
    )
    _suspend_timer.start()


_icon_path_cache = {}

def _get_root_path():
    ''' gets the root path of the application '''    
    import sys
    import pathlib
    import os

    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # as exe via pyinstallaler
        application_path = sys._MEIPASS

        # other installer
        #application_path = os.path.dirname(sys.executable)
    else:
        #app = QtWidgets.QApplication.instance()
        # application_path = app.applicationDirPath()
        # as script (because common is a subfolder, return the parent folder)
        application_path = pathlib.Path(os.path.dirname(__file__)).parent
    global root_path
    root_path = application_path
    return application_path

_get_root_path()