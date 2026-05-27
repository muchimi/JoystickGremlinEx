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


import threading
import sys
import uuid
import time

import gremlin.joystick_handling
import gremlin.shared_state
from gremlin.types import DeviceType
import logging
from PySide6 import QtCore
import gremlin.util

syslog = logging.getLogger("system")

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
initialized = False # true if app is initialized

data_path = None # application data path

vjoy_enabled = True # assume vjoy enabled
is_dark_theme = False # true if windows is in dark theme

# Flag indicating whether or not input highlighting should be
# prevented even if it is enabled by the user
_suspend_input_highlighting = False
_suspend_input_highlighting_enabled = 0

# Timer used to disable input highlighting with a delay
_suspend_timer = None

application_version = "0.0" # application version (set at runtime)

application_start_time = time.time() # application start time

abort = False # global abort flag - used to mark a profile start should abort - used along with the abort signal

# key of the global mode used internally for some global mappings
# global_mode = "__internal_global__"

ui_ready = False

# profile state status = ok - all components loaded, false an error occured
profile_state = True

# true if a profile message was issued (used for start errors)
profile_message_issued = False

# true if profile is loading
profile_loading = False

# holds the main UI reference
ui = None



# width of a single chart (this can be expensive to compute so we store it here once)
char_width = 10

# true if a profile is running
is_running = False

# stack - if non zero, keyboard input should be ignored (such as, when listening to keys)
_suspend_ui_keyinput = 0

# stack = if non zero, saving input should be suspended
_suspend_save_input = 0

# list of device names to their GUID
_virtual_device_guid_to_name_map = {}

# UUID of the plugins tab (plungins special device)
plugins_tab_guid = gremlin.util.parse_guid('dbce0add-460c-480f-9912-31f905a84247')
plugins_tab_id = gremlin.util.normalize_guid(plugins_tab_guid)

# UUID of the settings tab (settings special device)
settings_tab_guid = gremlin.util.parse_guid('5b70b5ba-bded-41a8-bd91-d8a209b8e981')
settings_tab_id = gremlin.util.normalize_guid(settings_tab_guid)

# UUID of the MIDI tab (midi device)
midi_tab_guid = gremlin.util.parse_guid('1b56ecf7-0624-4049-b7b3-8d9b7d8ed7e0')
midi_tab_id = gremlin.util.normalize_guid(midi_tab_guid)

# UUID of the OSC tab (osc device)
osc_tab_guid = gremlin.util.parse_guid('ccb486e8-808e-4b3f-abe7-bcb380f39aa4')
osc_tab_id = gremlin.util.normalize_guid(osc_tab_guid)

# UUID of the keyboard tab (keyboard device)
keyboard_tab_guid = gremlin.util.parse_guid('6f1d2b61-d5a0-11cf-bfc7-444553540000')
keyboard_tab_id = gremlin.util.normalize_guid(keyboard_tab_guid)

# UUID of the mode tab (mode device)
mode_tab_guid = gremlin.util.parse_guid('b3b159a0-4d06-4bd6-93f9-7583ec08b877')
mode_tab_id = gremlin.util.normalize_guid(mode_tab_guid)

# UUID of the state tab (state special device)
state_tab_guid = gremlin.util.parse_guid('72bbc0f4-31a8-4a41-b528-868dc7fcedfa')
state_tab_id = gremlin.util.normalize_guid(state_tab_guid)

# UUID of the octavi device
octavi_tab_guid = gremlin.util.parse_guid('e04aaf53-4838-4763-bc60-d5c7f8e653a1')
octavi_tab_id = gremlin.util.normalize_guid(octavi_tab_guid)

# fake GUID for fake inputs
fake_tab_guid = gremlin.util.parse_guid('f7cbbba2-a490-4401-b2bb-1f7f541d9e45')
fake_tab_id = gremlin.util.normalize_guid(fake_tab_guid)

master_mode = str(mode_tab_guid)
master_mode_name = "Master"

def translateMode(mode: str) -> str:
    ''' translate master mode name '''
    return master_mode_name if mode == master_mode else mode


# holds the current selected device guid (string) for a tab
current_tab_device_guid = None

def isDeviceTabActive(device_guid):
    ''' compares the given device and returns True if it's the current selected tab
    :param device_guid: what to look for, GUID or str

    '''
    global current_tab_device_guid
    return gremlin.util.compare_guid(device_guid, current_tab_device_guid)


# map of virtual devics to their input types
virtual_device_guid_type_map = [
    (plugins_tab_guid, DeviceType.NotSet),
    (settings_tab_guid, DeviceType.Settings),
    (midi_tab_guid, DeviceType.Midi),
    (osc_tab_guid, DeviceType.Osc),
    (mode_tab_guid, DeviceType.ModeControl)
]

virtual_device_guid = None

# setup default device names that are not hardware devices
def _init_special_device_guids():
    ''' setup the non HID hardware device name maps '''
    import dinput
    global _virtual_device_guid_to_name_map, virtual_device_guid
    _virtual_device_guid_to_name_map[str(keyboard_tab_guid).casefold()] = "Keyboard"
    _virtual_device_guid_to_name_map[str(osc_tab_guid).casefold()] = "OSC"
    _virtual_device_guid_to_name_map[str(midi_tab_guid).casefold()] = "MIDI"
    _virtual_device_guid_to_name_map[str(settings_tab_guid).casefold()] = "Settings"
    _virtual_device_guid_to_name_map[str(plugins_tab_guid).casefold()] = "Plugins"
    _virtual_device_guid_to_name_map[str(mode_tab_guid).casefold()] = "Modes"

    virtual_device_guid = str(dinput.GUID_Virtual).casefold()
    _virtual_device_guid_to_name_map[virtual_device_guid] = "(VirtualButton)"
    _virtual_device_guid_to_name_map[str(dinput.GUID_Invalid).casefold()] = "(Invalid)"




_init_special_device_guids()



def get_virtual_device_name(device_guid):
    ''' gets a device name - expect a string or a GUID'''
    if not isinstance(device_guid, str):
        device_guid = gremlin.util.normalize_guid(device_guid)
    device_guid = device_guid.casefold()
    if device_guid in _virtual_device_guid_to_name_map:
        return _virtual_device_guid_to_name_map[device_guid]
    return None

def get_device_name(device_guid):
    ''' gets the name corresponding to a hardware or virtual device '''
    if not isinstance(device_guid, str):
        device_guid = gremlin.util.normalize_guid(device_guid)
    device_name = gremlin.joystick_handling.device_name_from_guid(device_guid)
    if not device_name:
        device_name = get_virtual_device_name(device_guid)
    if not device_name:
        syslog.error(f"Unable to find device name for id: {device_guid}")
        return None
    return device_name


_simconnect_enabled = None

def getSimConnectEnabled():
    ''' gets the simconnect enabled flag '''
    global _simconnect_enabled
    config = gremlin.config.Configuration()
    enabled = config.simconnect_enabled
    if enabled:
        from action_plugins.map_to_simconnect import MapToSimConnect
        ec = gremlin.execution_graph.ExecutionContext()
        enabled = len(ec.findActionPlugin(MapToSimConnect.name)) > 0
        syslog = logging.getLogger("system")
        syslog.info(f"State: SimConnect usage {'is' if enabled else 'not'} detected.  SimConnect is {'enabled' if enabled else 'disabled'}.")
    _simconnect_enabled = enabled
    return _simconnect_enabled

# map of device type to hardware GUID (DeviceType enum)
device_type_map = {}

def reload_device_map():
    # setup device types
    global device_type_map
    device_type_map = {}
    for device in gremlin.joystick_handling.all_joystick_devices():
        gremlin.shared_state.device_type_map[device.device_guid] = device.device_type
    # virtual devices
    for device_guid, device_type in gremlin.shared_state.virtual_device_guid_type_map:
        gremlin.shared_state.device_type_map[device_guid] = device_type


# map of device profiles - indexed by hardware GUID
device_profile_map = {}

# map of device widgets by hardware GUID (widget)
#device_widget_map = {}

# Holds the currently active profile
current_profile = None


# holds the active (runtime) mode
runtime_mode : str = None

# terminating flag - set when the application is terminating
terminating : bool = False

# holds the edit mode
edit_mode : str = "Default"

# true if a device change occurs when a profile is running
has_device_changes : bool = False

# previous runtime mode
previous_runtime_mode : str = None

# import prompt count on import
import_prompt_stack = 0



@module_property
def _current_mode() -> str:
    if is_running:
        #print(f"current mode is: runtime {runtime_mode}")
        return runtime_mode
    #print(f"current mode is: edit {edit_mode}")
    return edit_mode

def resetState():
    device_profile_map.clear()
    _current_profile = None
    _runtime_mode = None
    _edit_mode = None
    _previous_runtime_mode = None



# controls repeater updates in the UI
_repeater_suspended = 0


def push_repeater():
    global _repeater_suspended
    _repeater_suspended += 1

def is_repeater_suspended():
    global _repeater_suspended
    return _repeater_suspended > 0

def pop_repeater(reset = False):
    global _repeater_suspended
    if _repeater_suspended > 0:
        _repeater_suspended -= 1
    if reset:
        _repeater_suspended = 0



def ui_keyinput_suspended():
    global _suspend_ui_keyinput
    return _suspend_ui_keyinput > 0

def push_suspend_ui_keyinput():
    ''' suspends keyboard input to the UI'''
    import gremlin.event_handler
    global _suspend_ui_keyinput

    if _suspend_ui_keyinput == 0:
        eh = gremlin.event_handler.EventListener()
        eh.suspend_keyboard_input.emit(True)

    _suspend_ui_keyinput += 1

def push_suspend_save_input():
    global _suspend_save_input
    _suspend_save_input += 1

def pop_suspend_save_input(reset = False):
    global _suspend_save_input
    if reset:
       _suspend_save_input = 0
       return
    if _suspend_save_input > 0:
        _suspend_save_input -= 1

def is_save_input_suspended() -> bool:
    global _suspend_save_input
    return _suspend_save_input > 0

_suspend_redraw = 0
def push_redraw():
    ''' pushes UI redraw suspend state '''
    global _suspend_redraw
    _suspend_redraw += 1

def pop_redraw(reset = False):
    ''' pops UI redraw state '''
    global _suspend_redraw
    if reset:
        _suspend_redraw = 0
    if _suspend_redraw > 0:
        _suspend_redraw -= 1

def is_redraw_suspended() -> bool:
    ''' true if UI redraw is currently suspended'''
    global _suspend_redraw
    return _suspend_redraw > 0


def pop_suspend_ui_keyinput():
    ''' restores keyboard input to the UI'''
    import gremlin.event_handler
    global _suspend_ui_keyinput
    if _suspend_ui_keyinput > 0:
        _suspend_ui_keyinput -= 1
    if _suspend_ui_keyinput == 0:
        eh = gremlin.event_handler.EventListener()
        eh.suspend_keyboard_input.emit(False)

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

# true if tabs are loading
is_tab_loading = False

def set_last_input_id(device_guid, input_type, input_id):
    if not is_tab_loading:
        import gremlin.config
        config = gremlin.config.Configuration()
        config.set_last_input(device_guid, input_type, input_id)

        if current_profile:
            current_profile.setLastInput(device_guid, input_type, input_id)



def get_last_input_id():
    import gremlin.config
    config = gremlin.config.Configuration()
    device_guid = config.get_last_device_guid()
    if device_guid:
        return gremlin.config.Configuration().get_last_input(device_guid)
    return (None, None, None)


def last_input_id(device_guid):
    ''' retrieves the last input id for a given input guid (input_type, input_id) of the last selection for this device '''
    import gremlin.config
    if device_guid:
        device_guid, input_type, input_id = gremlin.config.Configuration().get_last_input(device_guid, widget_only = True)
        return (input_type, input_id)
    return (None, None)


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


# simconnect community folders
community_folder = None
def _get_simconnect_community_folder():
    # Steam version
    #self._community_folder = r"C:\Microsoft Flight Simulator\Community"
    # Microsoft store version MSFS 2024: %appdata%\Local\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community
    import os
    app_data = os.getenv("LOCALAPPDATA")
    global community_folder
    # C:\Users\XXXXXX\AppData\Local\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community
    community_folder = os.path.join(app_data, "Packages","Microsoft.Limitless_8wekyb3d8bbwe","LocalCache","Packages","Community")


_get_simconnect_community_folder()


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

class ProfileStateMonitor():
    ''' monitors various state related settings '''
    def __init__(self):
        import gremlin.event_handler
        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._profile_start)
        el.profile_stop.connect(self._profile_stop)

    @QtCore.Slot()
    def _profile_start(self):
        gremlin.shared_state._simconnect_enabled = None # force an update


    @QtCore.Slot()
    def _profile_stop(self):
        gremlin.shared_state._simconnect_enabled = None # force an udpate


_log_nesting_level = 0


# log nesting level management
def pushLog():
    global _log_nesting_level
    _log_nesting_level +=1

def popLog(reset = False):
    global _log_nesting_level
    if _log_nesting_level > 0:
        _log_nesting_level -=1
    if reset:
        _log_nesting_level = 0

def logTabs(showLevel = False):
    ''' gets the log prefix tab based on nesting levels '''
    global _log_nesting_level
    tabs ="\t" * _log_nesting_level
    if showLevel:
        return f"Nesting [{_log_nesting_level}]{tabs}"
    return tabs

_joystick_suspend_count = 0
_input_selection_suspend_count = 0

def push_joystick():
    ''' suspends joystick input '''
    global _joystick_suspend_count
    _joystick_suspend_count += 1

def pop_joystick():
    ''' restores joystick input '''
    global _joystick_suspend_count
    if _joystick_suspend_count > 0:
       _joystick_suspend_count -= 1

def push_input_selection():
    global _input_selection_suspend_count
    _input_selection_suspend_count += 1

def pop_input_selection(reset : bool = False):
    global _input_selection_suspend_count
    if reset:
        _input_selection_suspend_count = 0
        return
    if _input_selection_suspend_count > 0:
       _input_selection_suspend_count -= 1




@module_property
def _is_joystick_suspended()->bool:
    global _joystick_suspend_count
    return _joystick_suspend_count > 0

@module_property
def _is_input_selection_suspended()->bool:
    global _input_selection_suspend_count
    return _input_selection_suspend_count > 0

_active_device_guid_value : uuid.UUID = None # guid of the active device, None if not set
@module_property
def _active_device_guid():
    ''' gets the active device id'''
    global _active_device_guid_value
    return _active_device_guid_value

def setActiveDeviceGuid(device_guid):
    global _active_device_guid_value
    _active_device_guid_value = device_guid

_get_root_path()


