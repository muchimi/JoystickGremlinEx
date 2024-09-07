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
import sys
import uuid

def module_property(func):
    """Decorator to turn module functions into properties.
    Function names must be prefixed with an underscore."""
    module = sys.modules[func.__module__]

    def base_getattr(name):
        raise AttributeError(
            f"module '{module.__name__}' has no attribute '{name}'")

    old_getattr = getattr(module, '__getattr__', base_getattr)

    def new_getattr(name):
        if f'_{name}' == func.__name__:
            return func()
        else:
            return old_getattr(name)

    module.__getattr__ = new_getattr
    return func


"""Stores global state that needs to be shared between various
parts of the program.

This is ugly but the only sane way to do this at the moment.
"""

root_path = None # root path

# Flag indicating whether or not input highlighting should be
# prevented even if it is enabled by the user
_suspend_input_highlighting = False
_suspend_input_highlighting_enabled = 0

# Timer used to disable input highlighting with a delay
_suspend_timer = None


ui_ready = False

# holds the main UI reference
ui = None


# true if a profile is running
is_running = False

# true if UI keyboard should be ignored (such as, when listening to keys)
_suspend_ui_keyinput = 0

# list of device names to their GUID
device_guid_to_name_map = {}

# map of device profiles - indexed by hardware GUID
device_profile_map = {}

# Holds the currently active profile
current_profile = None

# holds the active (runtime) mode
runtime_mode = None

# holds the edit mode
edit_mode = None

# true if a device change occurs when a profile is running
has_device_changes = False

# previous runtime mode
previous_runtime_mode = None

@module_property
def _current_mode() -> str:
    if is_running:
        #print(f"current mode is: runtime {runtime_mode}")
        return runtime_mode
    #print(f"current mode is: edit {edit_mode}")
    return edit_mode

def resetState():
    device_guid_to_name_map.clear()
    device_profile_map.clear()
    current_profile = None
    runtime_mode = None
    edit_mode = None
    previous_runtime_mode = None

    

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

def is_highlighting_suspended():
    """Returns whether or not input highlighting is suspended.

    :return True if input highlighting is SUSPENDED
    """
    global _suspend_input_highlighting, _suspend_input_highlighting_enabled
    suspended = not ui_ready and _suspend_input_highlighting or _suspend_input_highlighting_enabled > 0
    return suspended


def _set_input_highlighting_state(value):
    """Sets the input highlighting behaviour.

    :param value if True disables automatic selection of used inputs, if False
        inputs will automatically be selected upon use
    """
    global _suspend_input_highlighting, _suspend_timer
    if _suspend_timer is not None:
        _suspend_timer.cancel()
    _suspend_input_highlighting = value



def push_suspend_highlighting():
    ''' push a suspend state '''
    global _suspend_input_highlighting_enabled
    if _suspend_input_highlighting_enabled == 0:
        _set_input_highlighting_state(False)
    _suspend_input_highlighting_enabled += 1
    

def pop_suspend_highlighting(force = False):
    ''' pops a suspend state
     
    :param: force = forces a reset (enables)
       
    '''
    global _suspend_input_highlighting_enabled
    if _suspend_input_highlighting_enabled > 0:
        _suspend_input_highlighting_enabled -= 1
    if force:
        _suspend_input_highlighting_enabled = 0
    if _suspend_input_highlighting_enabled == 0:
        _set_input_highlighting_state(False)
    


    

def delayed_input_highlighting_suspension():
    """Disables input highlighting with a delay."""
    global _suspend_timer
    if _suspend_timer is not None:
        _suspend_timer.cancel()

    _suspend_timer = threading.Timer(
            2,
            lambda: pop_suspend_highlighting()
    )
    _suspend_timer.start()


_tab_input_map = {}

def update_last_selection(device_guid, input_type, input_id):
    ''' tracks the last selection per device guid '''
    key = str(device_guid)
    _tab_input_map[key] = (input_type, input_id)

def last_input_id(device_guid):
    ''' retrieves the last input id for a given input guid (input_type, input_id) of the last selection for this device '''
    key = str(device_guid)
    if key in _tab_input_map.keys():
        return _tab_input_map[key]
    return None, None


# pickle farm - allows to pickle an object to memory and recall it without actually pickling it

_pickle_data = {}

def save_state(data):
    id = str(uuid.uuid4())
    _pickle_data[id] = data
    return id

def load_state(id):
    if id in _pickle_data.keys():
        data = _pickle_data[id]
        del _pickle_data[id]
        return data
    return None

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


