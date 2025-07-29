# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2025 
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
import queue
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
import win32gui, win32con
import psygnal
from psygnal import Signal
from shiboken6 import Shiboken
import inspect


from . import error





# Table storing which modules have been imported already
g_loaded_modules = {}

syslog = logging.getLogger("system")


class FileWatcher(QtCore.QObject):

    """Watches files in the filesystem for changes."""

    # Signal emitted when the watched file is modified
    file_changed = Signal(str)

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
        self._watch_thread = threading.Thread(target=self._monitor, daemon=False)
        self._watch_thread.name = "file watcher"
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
                syslog.info(f"First run - copied Joystick Gremlin profiles to to Joystick Gremlin Ex")
            except Exception as error:
                syslog.error(f"Unable to copy profile from Joystick Gremlin to Joystick Gremlin Ex:\n{error}")
        if not os.path.isdir(path):
            try:
                # just create it
                os.mkdir(path)
            except Exception as error:
                syslog.error(f"Unable to create profile folder for Joystick Gremlin Ex:\n{error}")
                
        if not os.path.isdir(path):
                from gremlin.error import GremlinError
                raise GremlinError(f"Critical error: Unable to create profile folder: {path}")
            

    return os.path.normcase(path)



def copy_tree_if_newer(src, dst):
    """Copies a directory tree from src to dst, only if the source files 
    are newer than the destination files or if the destination file does not exist.
    """
    if os.path.exists(dst):
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            if os.path.isdir(s):
                copy_tree_if_newer(s, d)
            else:
                if not os.path.exists(d) or os.stat(s).st_mtime > os.stat(d).st_mtime:
                    shutil.copy2(s, d) # copy with metadata
    else:
        shutil.copytree(src, dst)



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

    QtWidgets.QApplication.restoreOverrideCursor()

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
    syslog.debug(str(msg))

def log_info(msg):
    ''' logs to the system log '''
    syslog.info(str(msg))

def log_sys_warn(msg):
    ''' logs to the system log '''
    syslog.warning(str(msg))

def log_sys_error(msg):
    ''' logs to the system error log'''
    syslog.error(str(msg))

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


def clamp(value, min_val = -1.0, max_val = 1.0):
    """Returns the value clamped to the provided range.

    :param value the input value
    :param min_val minimum value
    :param max_val maximum value
    :return the input value clamped to the provided range
    """
    if min_val > max_val:
        min_val, max_val = max_val, min_val
    if value > max_val:
        value = max_val
    elif value < min_val:
        value = min_val
    return value


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

def hat_index_to_tuple(index):
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
    keys = list(lookup.keys())
    if index < len(keys):
        return lookup[keys[index]]
    return None

def hat_tuples():
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
    return list(lookup.keys())


def hat_direction_to_name(value):
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
    if value in lookup:
        return lookup[value]
    return None


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
    value = value.casefold()
    if value in lookup:
        return lookup[value]
    return None



_logtabs = ""
_cleaned_widgets = []

def clear_layout(layout):
    """Removes all items from the given layout.

    :param layout the layout from which to remove all items
    """
    # global _logtabs,_cleaned_widgets
    
    # _logtabs += " "
    if not Shiboken.isValid(layout):
        return
    if layout is None:
        return    
    if isinstance(layout, QtWidgets.QWidget):
        widget = layout
        layout = widget.layout()
    while layout.count() > 0:
        child = layout.takeAt(0)
        if child.layout():
            clear_layout(child.layout())
        elif child.widget():
            widget = child.widget()
            if hasattr(widget,"_cleanup_ui"):
                widget._cleanup_ui()
            if hasattr(widget, "layout"):
                clear_layout(widget.layout())
            widget.hide()
            widget.deleteLater()
        layout.removeItem(child)


def get_layout_horizontal_size(layout : QtWidgets.QLayout) -> QtCore.QSize:
    ''' gets the desired size of a layout '''
    widgets = get_layout_widgets(layout)
    size = QtCore.QSize()
    h = 0
    widget : QtWidgets.QWidget
    for widget in widgets:
        w_size = widget.sizeHint()
        wh = w_size.height()
        if wh > h:
            h = wh
        w_size.setHeight(0)
        size += w_size
    size.setHeight(h)
    return size

def get_layout_widgets(layout : QtWidgets.QLayout) -> list:
    ''' returns a list of layout widgets '''
    widgets = []
    if layout:
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

def dumpWidgets(widget, title = None):
        ''' outputs layout contents to the log file '''
        layout = widget.layout() if isinstance(widget, QtWidgets.QWidget) else widget
        if layout:
            widgets = get_layout_widgets(layout)
            if title:
                syslog.info(f"---------------- widget dump for {title}--------------------")    
            else:
                syslog.info("---------------- widget dump --------------------")
            if widgets:
                for widget in widgets:
                    w_text = widget.text() if hasattr(widget,"text") else ""
                    w_value = str(widget.value()) if hasattr(widget,"value") else ""
                    w_name = widget.objectName()
                    syslog.info(f"\tWidget: [{type(widget)}] name: [{w_name}] text: [{w_text}] value: [{w_value}]")
            else:
                syslog.info("\tNo widgets.")
            


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
   
    try:
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
    except:
        syslog = logging.getLogger("system")
        syslog.warning(f"Unable to get file version information due to an OS error for: {path} ")
        return None


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

def get_dinput_guid():
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

def compare_guid(first, other):
    ''' compares GUIDs DINPUT or str - True if equal'''
    if first is None and other is None:
        return True
    if first is None:
        return False
    if other is None:
        return False
    first = str(first).casefold()
    other = str(other).casefold()
    return first == other
    
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
    
import gremlin.singleton_decorator

@gremlin.singleton_decorator.SingletonDecorator
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
    circuit_breaker = 1000
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
            syslog.info(f"Find_files() - found : {found_path} for {file_path}")
        return found_path
    
    if circuit_breaker == 0:
        syslog.error(f"Find_files() - search exceeded maximum when searching for: {file_path}")
    
    if verbose or circuit_breaker == 0:
        syslog.error(f"Find_files() failed for: {file_path}")
    return None




def get_icon_path(path):
        '''
        gets an icon path
           
        '''

        from gremlin.config import Configuration
        verbose = Configuration().verbose_mode_details
        
        import gremlin.shared_state

        # be aware of runtime environment
        if path:
            the_path = path.casefold()
        else:
            # no path provided
            return None
        
        root_path = gremlin.shared_state.root_path
        
        if the_path in gremlin.shared_state._icon_path_cache.keys():
            return gremlin.shared_state._icon_path_cache[the_path]

   
        # syslog.info(f"icon path: {the_path}  root: {root_path}")
        icon_file = os.path.join(root_path, the_path)
        icon_file = icon_file.replace("/",os.sep).lower()
        if icon_file:
            if os.path.isfile(icon_file):
                if verbose:
                    syslog.info(f"Icon file (straight) found: {icon_file}")
                gremlin.shared_state._icon_path_cache[the_path] = icon_file
                return icon_file
            if not icon_file.endswith(".png"):
                icon_file_png = icon_file + ".png"
                if os.path.isfile(icon_file_png):
                    if verbose:
                        syslog.info(f"Icon file (png) found: {icon_file_png}")
                    gremlin.shared_state._icon_path_cache[the_path] = icon_file_png
                    return icon_file_png
            if not icon_file.endswith(".svg"):
                icon_file_svg = icon_file + ".svg"
                if os.path.isfile(icon_file_svg):
                    if verbose:
                        syslog.info(f"Icon file (svg) found: {icon_file_svg}")
                    gremlin.shared_state._icon_path_cache[the_path] = icon_file_svg
                    return icon_file_svg
            brute_force = find_file(the_path)
            if brute_force and os.path.isfile(brute_force):
                gremlin.shared_state._icon_path_cache[the_path] = brute_force
                return brute_force
        
        syslog.error(f"Icon file not found: {icon_file}")
    
        return None

def load_pixmap(path, size = 24):
    ''' gets a pixmap from the path '''
    import gremlin.ui.ui_common

    desired_size = QtCore.QSize(size, size)
    
    if isinstance(path, QtGui.QIcon):
        return  path.pixmap(desired_size)
    
    the_path = get_icon_path(path)
    if the_path:
        #syslog.info(f"load_pixmap(): {the_path}")
        pixmap = QtGui.QPixmap(the_path)
        if pixmap.isNull():
            syslog.warning(f"load_pixmap(): pixmap failed: {the_path}")
            return None
        return pixmap
    
    # return a dummy pixmap so the code doesn't blow up
    syslog.error(f"load_pixmap(): invalid path: {the_path} {path}")
    icon : QtGui.QIcon = load_icon("ri.error-warning-line", qta_color=gremlin.ui.ui_common.Color.warningColor())
    return icon.pixmap(desired_size)


def load_icon(*paths, use_qta = False, qta_color = None):
    ''' gets an icon (returns a QIcon) - uses the qtawesome library or does a raw file search '''
    import gremlin.config 
    import gremlin.shared_state
    import gremlin.ui.ui_common
    verbose = gremlin.config.Configuration().verbose_mode_details

    is_dark = gremlin.shared_state.is_dark_theme

    the_path = paths[0]
    _ , ext = os.path.splitext(the_path.casefold())

    if ext == ".svg":
        if not os.path.isfile(the_path):
            the_path = find_file(the_path)
        if os.path.isfile(the_path):
            if is_dark:
                dark_path = dark_file(the_path)
                if not os.path.isfile(dark_path):
                    # create the dark version automatically
                    create_dark_svg(the_path, dark_path)
                if os.path.isfile(dark_path):
                    # load the dark equivalent
                    the_path = dark_path 
        
    icon = None
    if ext == "" or not (ext in (".png",".ico",".svg")) or use_qta:
        # assume a QTA icon if no extension
        try:
            if not qta_color:
                qta_color = gremlin.ui.ui_common.Color.normalColor()
            if isinstance(qta_color, str):
                assert qta_color.startswith("#") and len(qta_color) == 7
            icon = QtGui.QIcon(qta.icon(the_path, color = qta_color))
        except:
            pass
    if not icon:
        pixmap = load_pixmap(*paths)
        if not pixmap or pixmap.isNull():
            if verbose:
                syslog.info(f"LoadIcon() using generic icon - failed to locate: {paths}")
            return get_generic_icon()

        icon = QtGui.QIcon()
        icon.addPixmap(pixmap, QtGui.QIcon.Normal)
        if verbose:
            syslog.info(f"LoadIcon() found icon: {paths}")
    return icon


def dark_file(image_path):
    ''' gets the dark file name for an icon, if it exists '''
    the_path = image_path.casefold()
    dirname, basefile = os.path.split(the_path)
    basename, ext = os.path.splitext(basefile)
    if not basename.startswith("dark_"):
        return os.path.join(dirname, f"dark_{basename}{ext}")
    return image_path



def create_dark_svg(source_path, dark_path, hexcolor = ""):
    if os.path.isfile(source_path):
        if not os.path.isfile(dark_path):
            new_color = "#CCCCCC"
            new_gray_color = "#AAAAAA"
            new_stroke = "#666666"
            with open(source_path,"r") as fin:
                with open(dark_path,"w") as fout:
                    for line in fin.readlines():
                        
                        line = line.replace("#ffffff",new_stroke)
                        line = line.replace("#666666",new_gray_color)
                        line = line.replace("#000000",new_color)
                        line = line.replace("#000005;",new_color)
                        
                        fout.write(line)
                    fout.flush()
                    fout.close()
                fin.close()




def recolor_icon_pixmap(image_path, color = "red"):
    ''' recolors non-transparent pixels in an icon image 
    :Returns: pixmap of the recolored item
    '''
    syslog.info(f"Recolor pixmap: {image_path}")
    the_path = get_icon_path(image_path)
    if the_path:
        tmp = QtGui.QImage(the_path)
        if tmp:
            tmp = tmp.convertToFormat(QtGui.QImage.Format.Format_ARGB32)
            if tmp:
                c = QtGui.QColor(color)
                for y in range(tmp.height()):
                    for x in range (tmp.width()):
                        c.setAlpha(tmp.pixelColor(x,y).alpha())
                        tmp.setPixelColor(x,y,color)

                pixmap = QtGui.QPixmap.fromImage(tmp)    
                syslog.info("Recolor complete")            
                return pixmap
    return None

            

def load_image(*paths):
    ''' loads an image '''
    import gremlin.config 
    verbose = gremlin.config.Configuration().verbose_mode_details
    the_path = get_icon_path(*paths)
    if the_path:
        if verbose:
            syslog.info(f"LoadImage() found image: {paths}")
        return QtGui.QImage(the_path)
    if verbose:
            syslog.info(f"LoadImage() failed to locate: {paths}")
    return None
        
    
        

def get_generic_icon():
    ''' gets a generic icon'''
    import gremlin.shared_state
    root_path = gremlin.shared_state.root_path
    generic_icon = os.path.join(root_path, "gfx/generic.png")
    if generic_icon and os.path.isfile(generic_icon):
        pixmap = QtGui.QPixmap(generic_icon)
        if pixmap.isNull():
            syslog.warning(f"load_icon(): generic pixmap failed: {generic_icon}")
            return None
        icon = QtGui.QIcon()
        icon.addPixmap(pixmap, QtGui.QIcon.Normal)
        return icon
    syslog.warning(f"load_icon(): generic icon file not found: {generic_icon}")
    return None



def write_guid(guid):
    """Returns the string representation of a GUID object.

    :param guid the GUID object to turn into a string
    :return string representation of the guid object
    """
    return str(guid)


def safe_read(node, key, type_cast, default_value):
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
    syslog = logging.getLogger("system")
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
            syslog.error(msg)
            raise error.ProfileError(msg)
    else:
        value = node.get(key)
        

    if type_cast is not None:
        try:
            if type_cast == bool and isinstance(value,str):
                    value = value.strip().casefold()
                    value = value == "true"
            else:
                if value == "none":
                    value = None
                elif value == "special":
                    value = 0
                else:
                    try:
                        if type_cast == int and isinstance(value, str) and isNumeric(value):
                            value = int(float(value))
                        elif type_cast == float and isinstance(value, str) and isNumeric(value):
                            value = float(value)
                        else:
                            value = type_cast(value)
                    except:
                        syslog.error(f"XML: safe read - unable to convert type: {type_cast} value: [{value}] - using default: {default_value}")
                        value = default_value

        except ValueError:
            msg = f"XML: Failed casting '{value}' to type '{str(type_cast)}'"
            syslog.error(msg)
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
    elif data_type is bool:
        if isinstance(value, str) and isNumeric(value):
            value = float(value) != 0
        else:
            return formatter(bool(value))
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

def get_xml_parent(node, tag : str):
    ''' gets the first parent node of that tag '''
    value = tag.casefold()
    parent = node.getparent()
    while parent is not None:
        if parent.tag.casefold() == tag:
            return parent
        parent = parent.getparent()
    return None

def get_xml_mode(node):
    ''' gets the mode from a parent xml node '''
    # grab the mode
    mode_node = node
    while mode_node is not None and mode_node.tag != "mode":
        mode_node = mode_node.getparent()

    if mode_node is not None:
        mode = mode_node.get("name")
        return mode
    
    return None

def get_xml_input_data(node):
    ''' for a given XML node, find in the parent hierarchy of a profile the device_guid, mode, input_type and input_id 
    
    :param node: the child node
    :returns: (device_guid, input_type, input_id, mode)
    
    '''
    from gremlin.input_types import InputType

    device_guid = None
    input_id = None
    mode = None
    input_type = None

    device_node = node
    while device_node is not None and device_node.tag != "device":
        device_node = device_node.getparent()

    if device_node is not None:
        device_guid = parse_guid(device_node.get("device-guid"))

    # grab the mode
    mode_node = node
    while mode_node is not None and mode_node.tag != "mode":
        mode_node = mode_node.getparent()

    if mode_node is not None:
        mode = mode_node.get("name")

    # grab the input type and input id this applies to
    input_node = node
    tags = ["axis","button","hat","osc","midi"]

    while input_node is not None and not input_node.tag in tags:
        input_node = input_node.getparent()


    if input_node is not None:
        match input_node.tag:
            case "axis":
                input_type = InputType.JoystickAxis
                input_id = safe_read(input_node,"id",int, 0)
            case "button":
                input_type = InputType.JoystickButton
                input_id = safe_read(input_node,"id",int, 0)
            case "hat":
                input_type = InputType.JoystickHat
                input_id = safe_read(input_node,"id",int, 0)
            case "osc":
                child = get_xml_child(input_node, "input")
                input_type = InputType.OpenSoundControl
                input_id = str(parse_guid(child.get("guid")))
            case "midi":
                child = get_xml_child(input_node, "input")
                input_type = InputType.Midi
                input_id = str(parse_guid(child.get("guid")))
            


    



    return (device_guid, input_type, input_id, mode)


def parse_guid(value):
    """Reads a string GUID representation into the internal data format.

    This transforms a GUID of the form {B4CA5720-11D0-11E9-8002-444553540000}
    into the underlying raw and exposed objects used within Gremlin.

    :param value the string representation of the GUID
    :param dinput.GUID object representing the provided value
    """
    import dinput
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
    
    if source_min == source_max:
        syslog.warning("SCALE: scaling failed: source range is identical")
        return value
    
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

def floatlist_to_csv(data, decimals = 3) -> str:
    ''' converts an input list to a CSV stream  - returns a single row '''
    if not data:
        return ""
    assert isinstance(data, tuple) or isinstance(data, list)
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([f'{x:.{decimals}f}' if isinstance(x, float) else x for x in data])
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
            syslog.error(f"Unable to convert data stream {value} to a list")
    return []

def csv_to_floatlist(value) -> list:
    ''' converts a single row csv input to a list of floating point values '''
    if value:
        import csv
        import io
        input = io.StringIO(value)
        try:
            reader = csv.reader(input, delimiter=',')
            for row in reader:
                values = [float(v) for v in row]
                return values
        except:
            syslog.error(f"Unable to convert data stream {value} to a list")
    return []


def waitCursor():
    ''' sets the app to a wait cursor '''
    pushCursor()

_cursor_push = 0
_cursor_level = []

def pushCursor():
    global _cursor_push
    if _cursor_push == 0:
        #win32gui.LoadCursor(0, win32con.IDC_WAIT)
        QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor))
        QtWidgets.QApplication.processEvents()
    _cursor_push += 1

def popCursor(reset = False):
    ''' restores form wait cusor '''
    global _cursor_push
    if _cursor_push > 0:
        _cursor_push -= 1
    if _cursor_push == 0 or reset:
        #win32gui.LoadCursor(0, win32con.IDC_ARROW)
        QtWidgets.QApplication.restoreOverrideCursor()
        QtWidgets.QApplication.processEvents()

def isWaitCursor() -> bool:
    ''' true if the cursor is an hourglass '''
    global _cursor_push
    return _cursor_push > 0

def pushCursorLevel(pop = True):
    ''' saves the cursor level '''
    global _cursor_push, _cursor_level
    _cursor_level.append(_cursor_push)
    if pop:
        popCursor(True)
    

def popCursorLevel():
    ''' restores the last saved cursor level '''
    global _cursor_push, _cursor_level
    if _cursor_level:
        _cursor_push = _cursor_level.pop()
        if _cursor_push > 0:
            QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor))
    
        

def popCursorTemporary(pop = True):
    ''' restore cursor temporarily without changing the stack - use for dialog boxes/prompt
    
    :param pop: when true, restores the arrow, when false, shows the wait cursor if it was displayed
    
    '''
    global _cursor_push
    if _cursor_push > 0:
        if pop:
            QtWidgets.QApplication.restoreOverrideCursor()  
        else:
            QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor))
        


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




def centerDialog(dialog : QtWidgets.QDialog, width : int = None, height : int = None, parent = None):
    ''' centers the dialog on top of the UI '''
    # Display the dialog centered in the middle of the UI
    import gremlin.shared_state
    if gremlin.shared_state.ui is None:
        return # no UI yet
    root = dialog

    if width is None:
        width = dialog.width()
    if height is None:
        height = dialog.height()

    if parent:
        geom = parent.geometry() 
    else:
        if not root.parent():
            if gremlin.shared_state.ui is not None:
                geom = gremlin.shared_state.ui.geometry()
            else:
                geom = QtWidgets.QApplication.desktop().screen().rect()
        else:
            while root.parent():
                root = root.parent()
            geom = root.geometry()

    dialog.move(geom.center()- dialog.rect().center())



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
        syslog.error(f"DISPLAYFILE: warning: file not found: {path}")


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
    if a is None and b is None:
        return True
    if a is None and b is not None:
        return False
    return math.isclose(a, b, abs_tol=tolerance)

class InvokeUiMethod(QtCore.QObject):
    ''' invokes a call on the UI thread as QT is not thread safe '''
    _called = QtCore.Signal(object, object, object, object, object, object)
    def __init__(self, method: Callable, p0 = None, p1 = None, p2 = None, p3 = None, p4 = None, p5 = None):
        ''' Invokes a method on the main ui thread. 
        
        :params: method: lambda expression
        
        '''

        

        super().__init__()

        assert method is not None,"Method not provided"
        current_thread = QtCore.QThread.currentThread()
        ui_thread = QtWidgets.QApplication.instance().thread() # QT thread
        if current_thread != ui_thread:
            # non on UI thread, move it to the UI thread
            self.moveToThread(ui_thread)
            self.setParent(QtWidgets.QApplication.instance())
            self._called.connect(self._execute)
            self.method = method           
            self._called.emit(p0, p1, p2, p3, p4, p5)     
        else:   
            self._exec(method, p0, p1, p2, p3, p4, p5)


    def _exec(self, method, p0, p1, p2, p3, p4, p5):
        sig = inspect.signature(method)
        pcount = len(sig.parameters)


        # pcount = 0
        # if p5 is not None:
        #     pcount +=1
        # if p4 is not None:
        #     pcount +=1
        # if p3 is not None:
        #     pcount +=1
        # if p2 is not None:
        #     pcount +=1
        # if p1 is not None:
        #     pcount +=1
        # if p0 is not None:
        #     pcount +=1

        match pcount:
            case 0:
                method()
            case 1:
                method(p0)
            case 2:
                method(p0, p1)
            case 3:
                method(p0,p1,p2)
            case 4:
                method(p0,p1,p2,p3)
            case 5:
                method(p0,p1,p2,p3,p4)
            case 6:
                method(p0,p1,p2,p3,p4,p5)




    @QtCore.Slot(object)
    def _execute(self, p0 = None, 
                 p1 = None,
                 p2 = None,
                 p3 = None,
                 p4 = None,
                 p5 = None
                 ):
       
        self._exec(self.method, p0, p1, p2, p3, p4, p5)
        
        # trigger garbage collector
        self.setParent(None)


def is_ui_thread():
    ''' true if the current thread is the UI thread '''
    current_thread = QtCore.QThread.currentThread()
    ui_thread = QtWidgets.QApplication.instance().thread() # UI thread
    return current_thread == ui_thread

def assert_ui_thread():
    ''' throws an assertion if not running on UI thread which is needed for QT '''
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
    v = clamp(v * factor, 0, 255)
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


def getHostIp() -> list:
    ''' gets the list of the current machine's IP address '''
    import socket

    # get the local, non VPN, non loopback address
    
    try:
        # this can blow up on some systems
        hostname = socket.getfqdn()
        ip_list = socket.gethostbyname_ex(hostname)[2]
        return [ipa for ipa in ip_list if not ipa.startswith("127.")]
    except:
        pass
    # use the old method
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        s.connect(('10.254.254.254', 1)) # dummy address
        host_ip = s.getsockname()[0]
    except Exception:
        host_ip= '127.0.0.1'
    finally:
        s.close()

    return [host_ip]


def to_byte_string(source) -> tuple:
    ''' converts a byte string or regular string to (string, bytestring) '''
    if source is None:
        return (None, None)
    if isinstance(source, bytes):
        return (source.decode(), source)
    return (source, source.encode('utf-8'))
    

def singleShot(callback):
    ''' fires callback in a thread - returns immediately to caller '''
    thread = threading.Thread(target = callback)
    thread.name = "SingleShot"
    thread.start()

def cubic_progression(num_points, start, end):
    ''' computes a cubic progression between two numbers'''
    progression = []
    for i in range(num_points):
        t = i / (num_points - 1)  # Normalized parameter from 0 to 1
        value = start + (end - start) * (3 * t**2 - 2 * t**3)
        progression.append(value)

    return progression    


class ResetTimer(threading.Thread):
    ''' a reusable/resettable timer '''

    def __init__(self, interval, target, args = None, kwargs = None):
        super().__init__()
        self.interval = interval
        self.function = target
        self.args = args if args is not None else []
        self.kwargs = kwargs if kwargs is not None else {}
        self.finished = threading.Event()
        self._is_reset = True
        self._started = False
        
    def cancel(self):
        ''' stops the timer '''
        self.finished.set()

    @property
    def started(self) -> bool:
        return self._started


    def run(self):
        self._started = True
        while self._is_reset:
            self._is_reset = False
            self.finished.wait(self.interval)

        if not self.finished.isSet():
            self.function(*self.args, **self.kwargs)
        self.finished.set()
        self._started = False

    def reset(self, interval=None):
        """ Reset the timer """

        if interval is not None:
            self.interval = interval

        self._is_reset = True
        self.finished.set()
        self.finished.clear()



def getPythonVersion() -> str:
    ''' gets the python environment version as a string '''
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def decode(data) -> str:
    ''' decodes data and handles invalid characters '''
    if data:
        text = data.decode('ascii',errors='replace')
        return text.replace('\ufffd','') # remove junk characters
    return ''

def valueInRange(value : float, r1 : float, r2 : float, exclusive : bool = False) -> bool:
    ''' true if the value is within bounds, inclusive of boundaries
    :param value: the floating point value to compare
    :param r1: floating point value, first bound
    :param r2: floating point value, second bound
    :param exclusive: include the boundaries in the comparison or not
    :returns: true if in range, false if not
     
    '''
    import gremlin.config


    if value is None or r1 is None or r2 is None:
        return False
    if r1 > r2:
        # swap
        r2, r1 = r1, r2
    
    if exclusive:
        # do not include boundaries in the comparison
        return value > r1 and value < r2
    
    # include boundaries in the comparison
    
    if value > r1 and value < r2:
        # in range
        return True
    
    # handle floating point comparison resolution at boundary conditions
    decimals = gremlin.config.Configuration().range_comparison_decimals
    # floating point evaluation for tolerance at boundary conditions
    if not decimals:
        return False
    
    tolerance = 1/(10**decimals)
    low = math.isclose(value, r1, abs_tol=tolerance)
    if low:
        return True
    high = math.isclose(value, r2, abs_tol=tolerance)
    return high


def validateIp(ip_address : str) -> bool:
    import ipaddress
    try:
        ip = ipaddress.ip_address(ip_address)
        return True
    except:
        pass
    return False
 

def create_folder(path) -> bool:
    ''' creates a folder if it doesn't exist - returns True on ok'''
    if not os.path.isdir(path):    
        try:
            os.makedirs(path)
        except OSError as err:
            syslog.error('Error: Creating directory.' +  path,-1) 
            syslog.error(">> {}".format(err))
            return False
    return True


def str_to_bool(str_value) -> bool:
    ''' converts a boolean string value to a bool because for some reason bool('false') returns True in python... '''
    if str_value:
        str_value = str_value.casefold()
        if str_value == "true":
            return True
        if str_value == "false":
            return False
        if str_value == "1":
            return True
        if str_value == "0":
            return False
        if str_value.isnumeric():
            return int(str_value) > 0
    return False
            


def isNumeric(input_string):
    ''' since str.isnumeric is broken, borrowed this from : https://nextjournal.com/avidrucker/detecting-valid-number-strings-in-python '''

    def is_period(input_char):
        return input_char == "."

    def is_hyphen(input_char):
        return input_char == "-"

    def is_zero(input_char):
        return input_char == "0"

    def xs_in_string(pred, input_string):
        return list(filter(pred, input_string))

    def count_xs(pred, input_string):
        return len(xs_in_string(pred, input_string))
    
    is_digit = str.isdigit
  
    if(input_string is None or len(input_string) == 0):
        return False
    
    for char in input_string:
        if ((char != "-") and (char != ".") and (not char.isdigit())):
            return False
        
    
    if (count_xs(is_hyphen, input_string) > 1):
        return False
    
    
    if ((count_xs(is_hyphen, input_string) == 1) and (input_string[0] != "-")):
        return False
    
    
    if (count_xs(is_digit, input_string) == 0): # post-refactor
        return False
    

    if((input_string[0] == ".") or (input_string[-1] == ".")):
        return False
    
    if (count_xs(is_period, input_string) > 1):
        return False
    
    if((input_string[0] == "-") and (input_string[1] == ".")):
        return False
    
    if((len(input_string) > 1) and 
        (((input_string[0] == "0") and
        (input_string[1] != ".")) # eg. "05" number starts with a zero and is followed by another digit (i.e. not a period)
        or (len(input_string) > 2) and 
        ((input_string[0] == "-") and
        (input_string[1] == "0") and 
        (input_string[2] != ".")))): # eg. -01 number starts with a hyphen, followed by a zero, followed by another digit (i.e. not a period)
        return False
    
    
    if((input_string[0] == "-") and (count_xs(is_digit, input_string) == count_xs(is_zero, input_string))):
        return False
    
    
    return True


def normalize_guid(device_guid) -> str:
    ''' normalizes a device GUID to a string'''
    if not isinstance(device_guid, str):
        device_guid = str(device_guid)
    return device_guid.casefold().replace("-","")

def compare_guid(id1, id2) -> bool:
    ''' compares two GUIDs and returns true if equal '''
    if id1 is None and id2 is None: return True
    if id1 is None or id2 is None: return False
    id1 = normalize_guid(id1)
    id2 = normalize_guid(id2)
    return id1 == id2

def getTemporaryFile(ext = None):
    ''' gets a temporary file '''
    tmp_file = os.path.join(userprofile_path(), get_guid())
    if ext:
        if not ext.startswith("."):
            tmp_file += "."
        tmp_file += ext
    return tmp_file

def compare_float_lists(l1 : list, l2 : list):
    ''' compares two lists of floats - returns True if the lists are different '''
    if l1 is None and l2 is None:
        return False
    if l1 is None or l2 is None:
        return True
    count = len(l1)
    if count != len(l2):
        return True
    for index in range(count):
        v1 = l1[index]
        v2 = l2[index]
        if not is_close(v1, v2):
            return True
    return False

