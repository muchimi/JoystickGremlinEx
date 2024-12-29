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

import ctypes
import importlib
import logging
import math
import os
import re
import sys
import threading
import time
import shutil
import uuid
import dinput
import qtawesome as qta
from lxml import etree as ElementTree
from typing import Callable
from types import FunctionType, MethodType

from PySide6 import QtCore, QtWidgets, QtGui
from win32api import GetFileVersionInfo, LOWORD, HIWORD
from PySide6.QtGui import QColor

from . import error

from gremlin.singleton_decorator import SingletonDecorator

# Table storing which modules have been imported already
g_loaded_modules = {}


class FileWatcher(QtCore.QObject):

    """Watches files in the filesystem for changes."""

    # Signal emitted when the watched file is modified
    file_changed = QtCore.Signal(str)

    def __init__(self, file_names, parent=None):
        """Creates a new instance.

        :param file_names list of files to watch
        :param parent parent of this object
        """
        QtCore.QObject.__init__(self, parent)
        self._file_names = file_names
        self._last_size = {}
        for fname in self._file_names:
            self._last_size[fname] = 0

        self._is_running = True
        self._watch_thread = threading.Thread(target=self._monitor)
        self._watch_thread.start()

    def stop(self):
        """Terminates the thread monitoring files."""
        self._is_running = False
        if self._watch_thread.is_alive():
            self._watch_thread.join()

    def _monitor(self):
        """Continuously monitors files for change."""
        while self._is_running:
            for fname in self._file_names:
                stats = os.stat(fname)
                if stats.st_size != self._last_size[fname]:
                    self._last_size[fname] = stats.st_size
                    self.file_changed.emit(fname)
            time.sleep(1)


def is_user_admin():
    """Returns whether or not the user has admin privileges.

    :return True if user has admin rights, False otherwise
    """
    return ctypes.windll.shell32.IsUserAnAdmin() == 1


def axis_calibration(value, minimum, center, maximum):
    """Returns the calibrated value for a normal style axis.

    :param value the raw value to process range -1 to +1
    :param minimum the minimum value of the axis
    :param center the center value of the axis
    :param maximum the maximum value of the axis
    :return the calibrated value in [-1, 1] corresponding to the
        provided raw value
    """

    value = clamp(value, -1.0, 1.0)

    if center is None:
        # if no center provided, use the slider function with no center
        return slider_calibration(value, minimum, maximum)
    
    

    
    if value < center:
        div = float(center - minimum) 
        if div == 0.0:
            return 0.0
        return (value - center) / div + 0.0
    else:
        div = float(maximum - center)
        if div == 0.0:
            return 0.0
        return (value - center) / div + 0.0


def slider_calibration(value, minimum, maximum):
    """Returns the calibrated value for a slider type axis.

    :param value the raw value to process
    :param minimum the minimum value of the axis
    :param maximum the maximum value of the axis
    :return the calibrated value in [-1, 1] corresponding to the
        provided raw value
    """
    value = scale_to_range(value, minimum, maximum)
    return value



def create_calibration_function(minimum, center, maximum):
    """Returns a calibration function appropriate for the provided data.

    :param minimum the minimal value ever reported
    :param center the value in the neutral position
    :param maximum the maximal value ever reported
    :return function which returns a value in [-1, 1] corresponding
        to the provided raw input value
    """
    if center is None or  minimum == center or maximum == center:
        return lambda x: slider_calibration(x, minimum, maximum)
    else:
        return lambda x: axis_calibration(x, minimum, center, maximum)


def truncate(text, left_size, right_size):
    """Returns a truncated string matching the specified character counts.

    :param text the text to truncate
    :param left_size number of characters on the left side
    :param right_size number of characters on the right side
    :return string truncated to the specified character counts if required
    """
    if len(text) < left_size + right_size:
        return text

    return f"{text[:left_size]}...{text[-right_size:]}"


def script_path():
    """Returns the path to the scripts location.

    :return path to the scripts location
    """
    return os.path.normcase(
        os.path.dirname(os.path.abspath(os.path.realpath(sys.argv[0])))
    )


def userprofile_path():
    """Returns the path to the user's profile folder, %userprofile%."""
    path = os.path.abspath(os.path.join(os.getenv("userprofile"),"Joystick Gremlin Ex"))
    if not os.path.isdir(path):
        # profile folder does not exist - see if we can create it from the original profile
        source_path = os.path.abspath(os.path.join(os.getenv("userprofile"),"Joystick Gremlin"))
        if os.path.isdir(source_path):
            try:
                # copy from original profile
                shutil.copytree(source_path, path)
                logging.getLogger("system").info(f"First run - copied Joystick Gremlin profiles to to Joystick Gremlin Ex")
            except Exception as error:
                logging.getLogger("system").error(f"Unable to copy profile from Joystick Gremlin to Joystick Gremlin Ex:\n{error}")
        if not os.path.isdir(path):
            try:
                # just create it
                os.mkdir(path)
            except Exception as error:
                logging.getLogger("system").error(f"Unable to create profile folder for Joystick Gremlin Ex:\n{error}")
                
        if not os.path.isdir(path):
                from gremlin.error import GremlinError
                raise GremlinError(f"Critical error: Unable to create profile folder: {path}")
            

    return os.path.normcase(path)



def resource_path(relative_path):
    """ Get absolute path to resource, handling development and pyinstaller
    based usage.

    :param relative_path the relative path to the file of interest
    :return properly normalized resource path
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            base_path = script_path()
    except Exception:
        base_path = script_path()

    return os.path.normcase(os.path.join(base_path, relative_path))








def display_error(msg):
    """Displays the provided error message to the user.

    :param msg the error message to display
    """

    # verify an application exist
    app = QtWidgets.QApplication.instance()
    app_created = False
    if not app:
        app = QtWidgets.QApplication()
        app_created = True

    box = QtWidgets.QMessageBox(
        QtWidgets.QMessageBox.Critical,
        "Joystick Gremlin Ex Error",
        msg,
        QtWidgets.QMessageBox.Ok
    )
    box.exec()

    if app_created:
        app.quit()


def log(msg):
    """Logs the provided message to the user log file.

    :param msg the message to log
    """
    logging.getLogger("user").debug(str(msg))

def log_sys(msg):
    ''' logs to the system log '''
    logging.getLogger("system").debug(str(msg))

def log_info(msg):
    ''' logs to the system log '''
    logging.getLogger("system").info(str(msg))

def log_sys_warn(msg):
    ''' logs to the system log '''
    logging.getLogger("system").warning(str(msg))

def log_sys_error(msg):
    ''' logs to the system error log'''
    logging.getLogger("system").error(str(msg))

def format_name(name):
    """Returns the name formatted as valid python variable name.

    :param name the name to format
    :return name formatted to be suitable as a python variable name
    """
    return re.sub("[^A-Za-z]", "", name.lower()[0]) + \
        re.sub("[^A-Za-z0-9]", "", name.lower()[1:])


def valid_python_identifier(name):
    """Returns whether a given name is a valid python identifier.

    :param name the name to check for validity
    :return True if the name is a valid identifier, False otherwise
    """
    return re.match(r"^[^\d\W]\w*\Z", name) is not None


def clamp(value, min_val, max_val):
    """Returns the value clamped to the provided range.

    :param value the input value
    :param min_val minimum value
    :param max_val maximum value
    :return the input value clamped to the provided range
    """
    if min_val > max_val:
        min_val, max_val = max_val, min_val
    return min(max_val, max(min_val, value))


def hat_tuple_to_direction(value):
    """Converts a hat event direction value to it's textual equivalent.

    :param value direction tuple from a hat event
    :return textual equivalent of the event tuple
    """
    lookup = {
        ( 0,  0): "center",
        ( 0,  1): "north",
        ( 1,  1): "north-east",
        ( 1,  0): "east",
        ( 1, -1): "south-east",
        ( 0, -1): "south",
        (-1, -1): "south-west",
        (-1,  0): "west",
        (-1,  1): "north-west",
    }
    return lookup[value]


def hat_direction_to_tuple(value):
    """Converts a direction string to a tuple value.

    :param value textual representation of a hat direction
    :return tuple corresponding to the textual direction
    """
    lookup = {
        "center": (0, 0),
        "north": (0, 1),
        "north-east": (1, 1),
        "east": (1, 0),
        "south-east": (1, -1),
        "south": (0, -1),
        "south-west": (-1, -1),
        "west": (-1, 0),
        "north-west": (-1, 1)
    }
    return lookup[value]


def setup_userprofile():
    """Initializes the data folder in the user's profile folder."""
    folder = userprofile_path()
    if not os.path.exists(folder):
        try:
            os.mkdir(folder)
        except Exception as e:
            raise error.GremlinError(
                f"Unable to create data folder: {str(e)}"
            )
    elif not os.path.isdir(folder):
        raise error.GremlinError(
            "Data folder exists but is not a folder"
        )


def clear_layout(layout):
    """Removes all items from the given layout.

    :param layout the layout from which to remove all items
    """

    while layout.count() > 0:
        child = layout.takeAt(0)
        if child.layout():
            clear_layout(child.layout())
        elif child.widget():
            if hasattr(child,"_cleanup_ui"):
                child._cleanup_ui()
            child.widget().hide()
            child.widget().deleteLater()
        layout.removeItem(child)

def get_layout_widgets(layout : QtWidgets.QLayout) -> list:
    ''' returns a list of layout widgets '''
    widgets = []
    index = layout.count()
    while index >= 0:
        child = layout.itemAt(index)
        if child is not None:
            if child.layout():
                widgets.extend(get_layout_widgets(child.layout()))
            elif child.widget():
                widgets.append(child.widget())
        index -= 1

    return widgets

def layout_contains(layout, widget):
    ''' true if widget is contained in the given layout '''
    while layout.count() > 0:
        child = layout.takeAt(0)
        if child.layout():
            # sublayout
            if layout_contains(child.layout(), widget):
                return True
        if widget == child:
            return True
    return False

def layout_remove(layout, widget):
    ''' removes widget from the layout if the layout includes that widget '''
    while layout.count() > 0:
        child = layout.takeAt(0)
        if child.layout():
            # sublayout
            if layout_contains(child.layout(), widget):
                return True
        if widget == child:
            layout.removeWidget(widget)
            return True
    return False


dill_hat_lookup = {
    -1: (0, 0),
    0: (0, 1),
    4500: (1, 1),
    9000: (1, 0),
    13500: (1, -1),
    18000: (0, -1),
    22500: (-1, -1),
    27000: (-1, 0),
    31500: (-1, 1)
}


def load_module(name):
    """Imports  the given module.

    :param name the name of the module
    :return the loaded module
    """
    global g_loaded_modules
    if name in g_loaded_modules:
        importlib.reload(g_loaded_modules[name])
    else:
        g_loaded_modules[name] = importlib.import_module(name)
    return g_loaded_modules[name]


def deg2rad(angle):
    """Returns radian value of the provided angle in degree.

    :param angle angle in degrees
    :return angle in radian
    """
    return angle * (math.pi / 180.0)


def rad2deg(angle):
    """Returns degree value of the provided angle in radian.

    :param angle angle in radian
    :return angle in degree
    """
    return angle * (180.0 / math.pi)



def get_dll_version(path, as_string = True):
    ''' gets the dll file version number
    
    :param path - the full path to the file
    :returns file major, file minor, product version major, product version minor as integers
    '''
    if not os.path.isfile(path):
        if as_string:
            return None
        return (0,0,0,0)
   
    info = GetFileVersionInfo (path, "\\")
    ms = info['FileVersionMS']
    ls = info['FileVersionLS']

    f_major = HIWORD (ms)
    f_minor = LOWORD (ms)
    p_major = HIWORD (ls)
    p_minor = LOWORD (ls)
    
    if as_string:
        return f"{f_major}.{f_minor}.{p_major}.{p_minor}"
    return (f_major, f_minor, p_major, p_minor)


# def get_vjoy_driver_version() -> str:
#     ''' gets the vjoy driver version on the current machine '''
#     import subprocess, sys
#     p = subprocess.Popen(["powershell.exe",
#                 "Get-WmiObject Win32_PnPSignedDriver | select devicename, driverversion | ConvertTo-CSV"],
#                 stdout=subprocess.PIPE,
#                 startupinfo=subprocess.STARTUPINFO(dwFlags=subprocess.STARTF_USESHOWWINDOW, wShowWindow=subprocess.SW_HIDE,)
#     )
#     p_out, p_err = p.communicate()

#     if not p_out:
#         return None
#     p_out = p_out.decode('ascii').lower() # binary string to regular string
#     # convert to dict
#     for line in p_out.split("\n"):
#         # if "vjoy" in line:
#         #     pass
#         if  "vjoy device" in line:
#             _, version = line.split(",")
#             return version.replace("\r","").replace("\"","")
#     return None

def version_valid(v, v_req):
    ''' compares two versions
    
    :param v - version as string in x.x.x.x format
    :param r - version required as string in x.x.x.x format
    
    '''
    def compare_version(version1, version2):
        def parse_version(version):
            version_parts = version.split('.')
            version_ints = [int(part) for part in version_parts]
            return version_ints
        v1_parts = parse_version(version1)
        v2_parts = parse_version(version2)
        for i in range(max(len(v1_parts), len(v2_parts))):
            v1_num = v1_parts[i] if i < len(v1_parts) else 0
            v2_num = v2_parts[i] if i < len(v2_parts) else 0

            if v1_num < v2_num:
                return -1  # version1 is smaller
            elif v1_num > v2_num:
                return 1   # version2 is smaller
        return 0 # equal

    return compare_version(v, v_req) >= 0


def grouped(iterable, n):
    ''' returns n items for a given iterable item '''
    return zip(*[iter(iterable)]*n)

def get_dinput_guid() -> dinput.GUID:
    ''' gets a DirectInput compatible GUID'''
    return parse_guid(get_guid(strip=False,no_brackets=True))

def get_guid(strip=True,no_brackets = False) -> str:
    ''' generates a reasonably lowercase unique guid string '''
    import uuid
    guid = f"{uuid.uuid4()}"
    if strip:
        guid = guid.replace("-",'')
    if no_brackets:
        guid = guid.replace("{",'').replace("}",'')
    return guid
    
def find_files(root_folder, source_pattern = "*") -> list:
    ''' runs native file search to find files without blowing up on borked sym links in windows unlike rglob - returns full paths to the found file pattern '''
    import subprocess
    if not os.path.isdir(root_folder):
        return []
    
    wd = os.getcwd()
    os.chdir(root_folder)
    process = subprocess.Popen(["cmd", "/c", "dir", source_pattern, "/b","/s"],stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = process.communicate()
    os.chdir(wd)
    encoding = 'utf-8'
    # the link will be in square brackets
    if out:
        lines = str(out,encoding)
        if lines:
            lines = lines.replace('\r','')
            lines = lines.split('\n')
            lines = [l for l in lines if l]
            return lines

    return []


def find_folders(root_folder, source_pattern = "*") -> list:
    ''' looks for a subfolder off the root folder '''
    import subprocess
    if not os.path.isdir(root_folder):
        return []
    
    folders = os.listdir(root_folder)
    return [os.path.join(root_folder, folder) for folder in folders]
    


@SingletonDecorator
class SearchCache():
    ''' file search cache service '''
    def __init__(self):
        self.cache = {}

    def find_file(self, file_path, root_folder = None):
        if not file_path in self.cache:
            item = _find_file(file_path, root_folder)
            if item is not None:
                self.cache[file_path] = item
            return item
        return self.cache[file_path]
            
def find_file(file_path, root_folder = None):
    cache = SearchCache()
    return cache.find_file(file_path, root_folder)


def find_package_file(file_path):
    ''' find a package file '''
    syslog = logging.getLogger("system")
    # get the execution folder
    root_folder = None
    if getattr(sys, 'frozen', False):
        app = QtWidgets.QApplication.instance()
        root_folder = app.applicationDirPath()
    elif __file__:
        root_folder = os.path.dirname(__file__)
    
    syslog.info(f"Application Execution folder: {root_folder}")
    return find_file(file_path, root_folder)



def _find_file(file_path, root_folder = None):
    ''' finds a file '''

    


    from pathlib import Path
    from gremlin.config import Configuration
    import gremlin.shared_state
    verbose = Configuration().verbose_mode_details

    file_path = file_path.lower().replace("/",os.sep)
    sub_folders = None
    folders = []

    if not root_folder:
        root_folder = gremlin.shared_state.root_path
    if not os.path.isdir(root_folder):
        return None
    
    if os.sep in file_path:
        # we have folders
        splits = file_path.split(os.sep)
        folders = splits[:-1]
        file_path = splits[-1]
        sub_folders = os.path.join("", *folders)

    files = []
    if not os.path.isfile(file_path):
        # path not found
        file_root, ext = os.path.splitext(file_path)
        if ext:
            extensions = [ext]
        else:
            extensions = [".svg",".png"]
        circuit_breaker = 1000
        for dirpath, _, filenames in os.walk(root_folder):
            last = os.path.basename(dirpath)
            if last.startswith("."):
                # ignore hidden folders
                continue
            circuit_breaker-=1
            if circuit_breaker == 0:
                break
            if sub_folders and not dirpath.endswith(sub_folders):
                continue
            for filename in [f.lower() for f in filenames]:
                for ext in extensions:
                    if filename.endswith(ext) and filename.startswith(file_root):
                        files.append(os.path.join(dirpath, filename))
                    
    if files:
        files.sort(key = lambda x: len(x)) # shortest to largest
        found_path = files.pop(0) # grab the first one
        if verbose:
            logging.getLogger("system").info(f"Find_files() - found : {found_path} for {file_path}")
        return found_path
    
    if circuit_breaker == 0:
        logging.getLogger("system").error(f"Find_files() - search exceeded maximum when searching for: {file_path}")
    
    if verbose or circuit_breaker == 0:
        logging.getLogger("system").error(f"Find_files() failed for: {file_path}")
    return None




def get_icon_path(*paths):
        '''
        gets an icon path
           
        '''

        from gremlin.config import Configuration
        verbose = Configuration().verbose_mode_details
        
        import gremlin.shared_state

        # be aware of runtime environment
        root_path = gremlin.shared_state.root_path
        try:
            the_path = os.path.join(*paths).lower()
        except:
            # no path provided
            return None
        
        if the_path in gremlin.shared_state._icon_path_cache.keys():
            return gremlin.shared_state._icon_path_cache[the_path]

   
        # logging.getLogger("system").info(f"icon path: {the_path}  root: {root_path}")
        icon_file = os.path.join(root_path, the_path)
        icon_file = icon_file.replace("/",os.sep).lower()
        if icon_file:
            if os.path.isfile(icon_file):
                if verbose:
                    logging.getLogger("system").info(f"Icon file (straight) found: {icon_file}")
                gremlin.shared_state._icon_path_cache[the_path] = icon_file
                return icon_file
            if not icon_file.endswith(".png"):
                icon_file_png = icon_file + ".png"
                if os.path.isfile(icon_file_png):
                    if verbose:
                        logging.getLogger("system").info(f"Icon file (png) found: {icon_file_png}")
                    gremlin.shared_state._icon_path_cache[the_path] = icon_file_png
                    return icon_file_png
            if not icon_file.endswith(".svg"):
                icon_file_svg = icon_file + ".svg"
                if os.path.isfile(icon_file_svg):
                    if verbose:
                        logging.getLogger("system").info(f"Icon file (svg) found: {icon_file_svg}")
                    gremlin.shared_state._icon_path_cache[the_path] = icon_file_svg
                    return icon_file_svg
            brute_force = find_file(the_path)
            if brute_force and os.path.isfile(brute_force):
                gremlin.shared_state._icon_path_cache[the_path] = brute_force
                return brute_force
        
        logging.getLogger("system").error(f"Icon file not found: {icon_file}")
    
        return None

def load_pixmap(*paths):
    ''' gets a pixmap from the path '''
    the_path = get_icon_path(*paths)
    if the_path:
        pixmap = QtGui.QPixmap(the_path)
        if pixmap.isNull():
            logging.getLogger("system").warning(f"load_pixmap(): pixmap failed: {the_path}")
            return None
        return pixmap
    
    logging.getLogger("system").error(f"load_pixmap(): invalid path")
    return None

   

def load_icon(*paths, use_qta = False, qta_color = None):
    ''' gets an icon (returns a QIcon) - uses the qtawesome library or does a raw file search '''
    from gremlin.config import Configuration
    verbose = Configuration().verbose_mode_details
    
    (the_path,) = paths
    _, ext = os.path.splitext(the_path.lower())
    icon = None
    if ext == "" or not (ext in (".png",".ico",".svg")) or use_qta:
        # assume a QTA icon if no extension
        try:
            if qta_color:
                icon = QtGui.QIcon(qta.icon(the_path, color = qta_color))
            else:
                icon = QtGui.QIcon(qta.icon(the_path))
        except:
            pass
    if not icon:
        pixmap = load_pixmap(*paths)
        if not pixmap or pixmap.isNull():
            if verbose:
                logging.getLogger("system").info(f"LoadIcon() using generic icon - failed to locate: {paths}")
            return get_generic_icon()

        icon = QtGui.QIcon()
        icon.addPixmap(pixmap, QtGui.QIcon.Normal)
        if verbose:
            logging.getLogger("system").info(f"LoadIcon() found icon: {paths}")
    return icon

def load_image(*paths):
    ''' loads an image '''
    from gremlin.config import Configuration
    verbose = Configuration().verbose_mode_details
    the_path = get_icon_path(*paths)
    if the_path:
        if verbose:
            logging.getLogger("system").info(f"LoadImage() found image: {paths}")
        return QtGui.QImage(the_path)
    if verbose:
            logging.getLogger("system").info(f"LoadImage() failed to locate: {paths}")
    return None
        
    
        

def get_generic_icon():
    ''' gets a generic icon'''
    import gremlin.shared_state
    root_path = gremlin.shared_state.root_path
    generic_icon = os.path.join(root_path, "gfx/generic.png")
    if generic_icon and os.path.isfile(generic_icon):
        pixmap = QtGui.QPixmap(generic_icon)
        if pixmap.isNull():
            logging.getLogger("system").warning(f"load_icon(): generic pixmap failed: {generic_icon}")
            return None
        icon = QtGui.QIcon()
        icon.addPixmap(pixmap, QtGui.QIcon.Normal)
        return icon
    logging.getLogger("system").warning(f"load_icon(): generic icon file not found: {generic_icon}")
    return None



def write_guid(guid):
    """Returns the string representation of a GUID object.

    :param guid the GUID object to turn into a string
    :return string representation of the guid object
    """
    return str(guid)


def safe_read(node, key, type_cast=None, default_value=None):
    """Safely reads an attribute from an XML node.

    If the attempt at reading the attribute fails, due to the attribute not
    being present, an exception will be thrown.

    :param node the XML node from which to read an attribute
    :param key the attribute to read
    :param type_cast the type to which to cast the read value, if specified
    :param default_value value to return in case the key is not present
    :return the value stored in the node with the given key
    """
    # Attempt to read the value and if present use the provided default value
    # in case reading fails
    value = default_value
    if not key in node.keys():
        if default_value is None:
            match type_cast:
                case str():
                    default_value = ""
                case int():
                    default_value = 0
                case float():
                    default_value = 0.0
                case bool():
                    default_value = False
                case _:
                    pass
        if default_value is None:
            msg = f"Attempted to read attribute '{key}' which does not exist and no default value is provided."
            logging.getLogger("system").error(msg)
            raise error.ProfileError(msg)
    else:
        value = node.get(key)
        

    if type_cast is not None:
        try:
            if type_cast == bool and isinstance(value,str):
                    value = value.strip().lower()
                    value = value == "true"
            else:
                if value == "none":
                    value = None
                else:
                    value = type_cast(value)
        except ValueError:
            msg = f"Failed casting '{value}' to type '{str(type_cast)}'"
            logging.getLogger("system").error(msg)
            raise error.ProfileError(msg)
    return value


def safe_format(value, data_type, formatter=str):
    """Returns a formatted value ensuring type correctness.

    This function ensures that the value being formatted is of correct type
    before attempting formatting. Raises an exception on non-matching data
    types.

    :param value the value to format
    :param data_type expected data type of the value
    :param formatter function to format value with
    :return value formatted according to formatter
    """
    if value is None:
        return "none"
    if data_type is int:
        return str(value)
    elif data_type is float:
        value = float(value)
        return f"{value:0.8f}"
    if isinstance(value, data_type):
        return formatter(value)
    else:
        raise error.ProfileError(
            f"Value \"{value}\" has type {type(value)} when {data_type} is expected"
        )


def get_xml_child(node, tag : str, multiple = False):
    ''' gets a specific xml child node by tag - None if not found
    
    :param: multiple - if set, returns all matching subnodes as a list, blank list if nothing found - if not set, returns None or the first node found
    
    '''

    value = tag.casefold()
    if multiple:
        nodes = []
        for child in list(node):
            if not child.tag is ElementTree.Comment:
                if child.tag.casefold() == value:
                    nodes.append(child)
        return nodes

    for child in list(node):
        if child.tag is ElementTree.Comment:
            continue
        if child.tag.casefold() == value:

            return child
    return None


def parse_guid(value):
    """Reads a string GUID representation into the internal data format.

    This transforms a GUID of the form {B4CA5720-11D0-11E9-8002-444553540000}
    into the underlying raw and exposed objects used within Gremlin.

    :param value the string representation of the GUID
    :param dinput.GUID object representing the provided value
    """
    if value is None or value == "None" or not value:
        return None
    if isinstance(value, dinput.GUID):
        return value
    try:
        tmp = uuid.UUID(value)
        raw_guid = dinput._GUID()
        raw_guid.Data1 = int.from_bytes(tmp.bytes[0:4], "big")
        raw_guid.Data2 = int.from_bytes(tmp.bytes[4:6], "big")
        raw_guid.Data3 = int.from_bytes(tmp.bytes[6:8], "big")
        for i in range(8):
            raw_guid.Data4[i] = tmp.bytes[8 + i]

        return dinput.GUID(raw_guid)
    except (ValueError, AttributeError) as e:
        raise error.ProfileError(
            f"Failed parsing GUID from value {value}"
        )


def parse_bool(value, default_value=False):
    """Returns the boolean representation of the provided value.

    :param value the value as string to parse
    :param default_value value to return in case no valid value was provided
    :return representation of value as either True or False
    """
    # Terminate early if the value is None to start with, i.e. we know it will
    # fail
    if value is None:
        return default_value

    # Attempt to parse the value
    try:
        if value.isnumeric():
            int_value = int(value)
            if int_value in [0, 1]:
                return int_value == 1
            else:
                raise error.ProfileError(
                    f"Invalid bool value used: {value}"
                )
        else:
            value = value.lower()
            if value in ["true", "false"]:
                return value == "true"
            else:
                raise error.ProfileError(
                    f"Invalid bool value used: {value}"
                )
    except ValueError:
        value = value.lower()
        if value in ["true", "false"]:
            return value == "true"
        else:
            raise error.ProfileError(
                f"Invalid bool value used: {value}"
            )
    except TypeError:
        raise error.ProfileError(
            f"Invalid type provided: {type(value)}"
        )

def read_guid(node, key, default_value = None):
    ''' reads a GUID '''
    if key in node.attrib:
        try:
            s_guid = node.get(key)
            return uuid.UUID(s_guid)
        except:
            pass
    return default_value
    

def read_bool(node, key, default_value=False):
    """Attempts to read a boolean value.

    If there is an error when reading the given field from the node
    the default value is returned instead.

    :param node the node from which to read the value
    :param key the key to read from the node
    :param default_value the default value to return in case of errors
    """
    if key in node.attrib:
        return parse_bool(node.get(key), default_value)
    return default_value

def byte_string_to_list(value : str) -> list:
    ''' converts a text string of sequential bytes separated by a space'''
    tokens = value.split()
    data = []
    for token in tokens:
        try:
            value = int(token, 16) # expecting a hexadecimal number
            data.append(value)
        except:
            raise ValueError(f"Unable to convert byte string to list, offending value: {token}")
    
    return data

def byte_list_to_string(data, as_hex = True):
    ''' converts a byte list to a string '''
    result = ''
    for value in data:
        if as_hex:
            result += f"{value:02x} "
        else:
            result += f"{value} "

    # strip the last space
    result = result[:-1]
    return result

def scale_to_range(value, source_min = -1.0, source_max = 1.0, target_min = -1.0, target_max = 1.0, invert = False):
    ''' scales a value on one range to the new range
    
    value: the value to scale
    r_min: the source value's min range
    r_max: the source value's max range
    new_min: the new range's min
    new_max: the new range's max
    invert: true if the value should be reversed
    '''
    if value is None:
        return None
    
    assert source_min != source_max, "Invalid source range - cannot be the same"
    # bracket value to input range if outside that range
    if value < source_min: 
        value = source_min
    elif value > source_max:
        value = source_max
    
    if invert:
        result = (((source_max - value) * (target_max - target_min)) / (source_max - source_min)) + target_min
    else:
        result = (((value - source_min) * (target_max - target_min)) / (source_max - source_min)) + target_min
    return result + 0

def list_to_csv(data) -> str:
    ''' converts an input list to a CSV stream  - returns a single row '''
    if not data:
        return ""
    assert isinstance(data, tuple) or isinstance(data, list)
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(data)
    return output.getvalue().strip() # remove new lines


def csv_to_list(value) -> list:
    ''' converts a single row csv input to a list '''
    if value:
        import csv
        import io
        input = io.StringIO(value)
        try:
            reader = csv.reader(input, delimiter=',')
            for row in reader:
                return row
        except:
            logging.getLogger("system").error(f"Unable to convert data stream {value} to a list")
    return []



def waitCursor():
    ''' sets the app to a wait cursor '''
    pushCursor()

_cursor_push = 0

def pushCursor():
    global _cursor_push
    if _cursor_push == 0:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        QtWidgets.QApplication.processEvents()
    _cursor_push+=1

def popCursor(reset = False):
    ''' restores form wait cusor '''
    global _cursor_push
    if _cursor_push > 0:
        _cursor_push -= 1
    if _cursor_push == 0 or reset:
        QtWidgets.QApplication.restoreOverrideCursor()
        QtWidgets.QApplication.processEvents()

def isCursorActive():
    ''' true if the cursor stack is not empty '''
    global _cursor_push
    return _cursor_push > 0
    

def compare_path(a, b):
    ''' compare two paths '''
    if a is None and b is None:
        return True
    if a is None:
        return False
    if b is None:
        return False
    af = a.replace("\\","/").casefold().strip()
    bf = b.replace("\\","/").casefold().strip()
    return af == bf

def fix_path(a):
    if a:
        return a.replace("\\","/").casefold().strip()
    return a

def compare_nocase(a : str, b : str):
    ''' compares two strings - not case sensitive '''
    if a is None and b is None:
        return True
    if a == "" and b == "":
        return True
    return a.casefold() == b.casefold()

def getSignal (oObject : QtCore.QObject, signal_name : str):
    ''' gets a reference to an object signal  '''
    oMetaObj = oObject.metaObject()
    for i in range (oMetaObj.methodCount()):
        oMetaMethod = oMetaObj.method(i)
        if not oMetaMethod.isValid():
            continue
        if oMetaMethod.methodType () == QtCore.QMetaMethod.Signal and \
            oMetaMethod.name() == signal_name:
            return oMetaMethod
    return None

def isSignalConnected(oObject : QtCore.QObject, signal_name : str):
    ''' true if a signal is connected '''
    mm = getSignal(oObject, signal_name)
    return mm is not None and oObject.isSignalConnected(mm)




def centerDialog(dialog, width = 300, height = 150):
    ''' centers the dialog on top of the UI '''
    # Display the dialog centered in the middle of the UI
    import gremlin.shared_state
    if gremlin.shared_state.ui is None:
        return # no UI yet
    root = dialog
    if not root.parent():
        geom = gremlin.shared_state.ui.geometry()
    else:
        while root.parent():
            root = root.parent()
        geom = root.geometry()
    dialog.setGeometry(
        int(geom.x() + geom.width() / 2 - width/2),
        int(geom.y() + geom.height() / 2 - height/2),
        width,
        height
    )


def swapext(path, ext = None, prefix= '', suffix = ''):
    ''' replaces a file extension with a different one with an additional prefix / suffix'''
    dirname, filename = os.path.split(path)
    base, old_ext = os.path.splitext(filename)
    if ext:
        if ext != '' and not ext.startswith('.'):
            ext = "." + ext
    else:
        ext = old_ext
    if dirname:
        return os.path.join(dirname, prefix + base + suffix + ext).lower()
    return (prefix + base + suffix + ext).lower()

def get_ext(path):
    # gets an extension
    _, filename = os.path.split(path)
    _, ext = os.path.splitext(filename)
    if ext:
        return ext.lower()
    return None

def strip_ext(path):
    if path:
        tokens = path.split(".")
        return tokens[0]
    return ''

def swap_ext(path, ext = None, prefix= '', suffix = ''):
    return swapext(path, ext, prefix, suffix)


def display_file(path):
    ''' opens a file in the current editor associated with the extension '''
    import subprocess
    import webbrowser
    if os.path.isfile(path):
        webbrowser.open(path)
    else:
        logging.getLogger("system").error(f"DISPLAYFILE: warning: file not found: {path}")


def debug_pickle(instance, exception=None, string='', first_only=True):
    """
    Recursively go through all attributes of instance and return a list of whatever
    can't be pickled.

    Set first_only to only print the first problematic element in a list, tuple or
    dict (otherwise there could be lots of duplication).
    """
    problems = []
    import dill
    if isinstance(instance, tuple) or isinstance(instance, list):
        for k, v in enumerate(instance):
            try:
                dill.dumps(v)
            except BaseException as e:
                problems.extend(debug_pickle(v, e, string + f'[{k}]'))
                if first_only:
                    break
    elif isinstance(instance, dict):
        for k in instance:
            try:
                dill.dumps(k)
            except BaseException as e:
                problems.extend(debug_pickle(
                    k, e, string + f'[key type={type(k).__name__}]'
                ))
                if first_only:
                    break
        for v in instance.values():
            try:
                dill.dumps(v)
            except BaseException as e:
                problems.extend(debug_pickle(
                    v, e, string + f'[val type={type(v).__name__}]'
                ))
                if first_only:
                    break
    else:
        try:
            for k, v in instance.__dict__.items():
                try:
                    dill.dumps(v)
                except BaseException as e:
                    print (k)
                    problems.extend(debug_pickle(v, e, string + '.' + k))
        except:
            # ignore types that have no attributes
            pass
        

    # if we get here, it means pickling instance caused an exception (string is not
    # empty), yet no member was a problem (problems is empty), thus instance itself
    # is the problem.
    if string != '' and not problems:
        problems.append(
            string + f" (Type '{type(instance).__name__}' caused: {exception})"
        )

    return problems


def is_close(a, b, tolerance = 0.0001):
    ''' compares two floating point numbers with approximate precision '''
    return math.isclose(a, b, abs_tol=tolerance)

class InvokeUiMethod(QtCore.QObject):
    ''' invokes a call on the UI thread as QT is not thread safe '''
    def __init__(self, method: Callable):
        ''' Invokes a method on the main ui thread. 
        
        :params: method: lambda expression
        
        '''
        super().__init__()
        current_thread = QtCore.QThread.currentThread()
        ui_thread = QtWidgets.QApplication.instance().thread() # QT thread
        if current_thread != ui_thread:
            self.moveToThread(ui_thread)
            self.setParent(QtWidgets.QApplication.instance())
            self.method = method
            self.called.connect(self.execute)
            self.called.emit()
        else:
            method()

    called = QtCore.Signal()

    @QtCore.Slot()
    def execute(self):
        self.method()
        # trigger garbage collector
        self.setParent(None)


def assert_ui_thread():
    current_thread = QtCore.QThread.currentThread()
    ui_thread = QtWidgets.QApplication.instance().thread() # UI thread
    if current_thread != ui_thread:
        assert False,"call not on UI thread"


def highlight_qcolor(color : QColor, factor : float = 1.1) -> QColor:
    '''
    computes a highlight color from a QT color object

    :param color: a QT color
    :param factor: optional, factor
    :returns: the new QColor object
    
    '''
    h,s,v,a = color.getHsv()
    v = v * factor
    new_color = color.fromHsv(h, s, v, a)
    return new_color



def highlight_color(hex_color:str, factor : float = 1.1):
    ''''
    computes a highlight color from a hex color

    :param hex_color: a hex color in the format "#aabbcc
    :param factor: optional, factor
    :returns: the new hex color as a string 
    '''
    import colorsys
    hex_color = hex_color.lstrip('#')
    r, g, b = tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    #luminance = 0.299 * r + 0.587 * g + 0.114 * b
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    v = v * factor
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return f"#{r:02x}{g:02x}{b:02x}"

a_90 = math.radians(90)
a_45 = math.radians(45)

def snap_to_grid(x : float, y: float, grid_size : int = 50, 
                 ref_x : float= None, ref_y : float = None, 
                 ) -> tuple[float, float]:
    ''' snaps a coordinate 0 to 1 to a grid '''
    spacing = 1/grid_size
    gx = spacing * round(x / spacing)
    gy = spacing * round(y / spacing)

    sx = gx
    sy = gy

    # get the rotational snaps 
    if ref_x is not None and ref_y is not None:
        # reference point provided
        dx = x - ref_x
        dy = y - ref_y
        d = math.dist([ref_x, ref_y],[x,y])
        signed_a = math.atan2(dy, dx)
        a = abs(signed_a)
        factor = 1 if signed_a > 0 else -1
        a_t = math.radians(3)
        
        if a <= a_t:
            # snap horizontal
            sy = ref_y
            sx = x
        elif a_t >= (a_90 - a_t):
            # snap vertical
            sx = ref_x
            sy = y
            pass
        elif a >= a_45 - a_t and a <= a_45 + a_t:
            # snap 45 degrees    
            sy = ref_y + d * math.sin(a_45) * factor
            sy = ref_x + d * math.cos(a_45) * factor


    return (sx,sy)


            

def float_to_xml(value : float, decimals = 5) -> str:
    ''' converts a float to a string for xml saving'''
    return f"{value:0.{decimals}f}"


def is_binary_string(data):
  ''' true if the string is a binary string '''
  if data is None:
      return False
  return isinstance(data, bytes)


def getHostIp():
    ''' gets the current machine's IP address '''
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        s.connect(('10.254.254.254', 1)) # dummy address
        host_ip = s.getsockname()[0]
    except Exception:
        host_ip= '127.0.0.1'
    finally:
        s.close()

    return host_ip


def to_byte_string(source) -> tuple:
    ''' converts a byte string or regular string to (string, bytestring) '''
    if source is None:
        return (None, None)
    if isinstance(source, bytes):
        return (source.decode(), source)
    return (source, source.encode('utf-8'))
    