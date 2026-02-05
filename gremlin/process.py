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

import ctypes
import ctypes.wintypes
import os
import time
import threading

from PySide6 import QtCore
import gremlin.shared_state
from gremlin.singleton_decorator import SingletonDecorator
import win32gui
import win32process
import logging
import gremlin.config
import gremlin.event_handler
import psygnal
from psygnal import Signal
from typing import Callable
import win32api,  win32gui, win32con
import psutil

# Definition of the flags for limited information queries
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

syslog = logging.getLogger("system")

@SingletonDecorator
class ProcessMonitor(QtCore.QObject):

    """Monitors the currently active window process.

    This class continuously monitors the active window and whenever
    it changes the path to the executable is retrieved and signaled
    to the rest of the system using Qt's signal / slot mechanism.
    """

    # Signal emitted when the active window changes
    process_changed = Signal(str)




    def __init__(self):
        """Creates a new instance."""
        QtCore.QObject.__init__(self)
        self._buffer = ctypes.create_string_buffer(1024)
        self._buffer_size = ctypes.wintypes.DWORD(1024)
        self._current_path = ""
        self._current_pid = -1
        self._running = False
        self._update_thread = None
        self.kernel32 = ctypes.windll.kernel32
        self._enabled = False
        # self._callback_map = {} # list of processes to monitor and their callback
        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self.stop)
        el.profile_start.connect(self.start)
        #el.profile_stop_toolbar.connect(self.stop) # stop listener only if manual toolbar button clicked
        el.process_monitor_changed.connect(self._check_monitor)




    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @enabled.setter
    def enabled(self, value : bool):
        self._enabled = value
        if not value and self._running:
            # stop the profile auto 
            self.stop()

    def _check_monitor(self):
        ''' executes when process monitoring related actions change '''
        config = gremlin.config.Configuration()
        option_auto_load = config.autoload_profiles
        option_auto_load_on_focus = config.activate_on_process_focus
        self.enabled = option_auto_load or option_auto_load_on_focus

        if option_auto_load_on_focus:
            # start monitoring processes if auto activating based on processes
            self.start()
        


    def start(self):
        """Starts monitoring the current process."""
        config = gremlin.config.Configuration()
        option_auto_load = config.autoload_profiles
        option_auto_load_on_focus = config.activate_on_process_focus
        syslog = logging.getLogger("system")
        
        if option_auto_load or option_auto_load_on_focus:
            self._enabled = True
            if not self._running:
                # verbose = gremlin.config.Configuration().verbose_mode_process
                syslog.info("PROC: start")
                self._running = True
                self._update_thread = threading.Thread(target=self._update, daemon=False)
                self._update_thread.name="process monitor"
                self._update_thread.start()
            

    def stop(self):
        """Stops monitoring the current process."""
        if not self._running:
            return # nothing to do
            
        self._running = False
        # verbose = gremlin.config.Configuration().verbose_mode_process
        syslog = logging.getLogger("system")
        syslog.info("PROC: shutdown")
        if self._update_thread is not None:
            if self._update_thread.is_alive():
                self._update_thread.join()
            self._update_thread = None

    def _update(self):
        """Monitors the active process for changes."""
        while self._running:
            if self._enabled:
                _, pid = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())

                if pid != self._current_pid:
                    self._current_pid = pid
                    handle = self.kernel32.OpenProcess(
                        PROCESS_QUERY_LIMITED_INFORMATION,
                        False,
                        pid
                    )

                    self._buffer_size = ctypes.wintypes.DWORD(1024)
                    self.kernel32.QueryFullProcessImageNameA(
                        handle,
                        0,
                        self._buffer,
                        ctypes.byref(self._buffer_size)
                    )
                    self.kernel32.CloseHandle(handle)

                    self._current_path = os.path.normpath(
                        str(self._buffer.value)[2:-1]
                    ).replace("\\", "/")
                    self.process_changed.emit(self.current_path)

            time.sleep(1.0)

    @property
    def current_path(self):
        """Returns the path to the currently active executable.

        :return path to the currently active executable
        """
        return self._current_path


    def list_current_processes(self):
        """Returns a list of executable paths to currently active processes.

        :return list of active process executable paths
        """
        from win32com.client import GetObject
        wmi = GetObject('winmgmts:')
        processes = wmi.InstancesOf("Win32_Process")
        process_list = []
        for entry in processes:
            executable = entry.Properties_("ExecutablePath").Value
            if executable is not None:
                process_list.append(os.path.normpath(executable).replace("\\", "/"))
        return sorted(set(process_list))

    def process_running(self, process_name : str | list):
        ''' checks if a process is currently running '''

        if not isinstance(process_name, list):
            process_names = [process_name]
        else:
            process_names = process_name

        process_names = [p.casefold() for p in process_names if p]

        process_list = self.list_current_processes()
        for item in process_list:
            _, exe = os.path.split(item)
            for process_name in process_names:
                if exe.casefold() == process_name:
                    return True
            
        return False
    

# main instance
_process_monitor = ProcessMonitor()


def list_current_processes():
    ''' gets alist of current processes '''
    return _process_monitor.list_current_processes()


          
class ProcessHelper:

    def __init__(self):
        self._lock = threading.Lock()
        self._is_running = False

    def getWindows(self):
        """
        Enumerates all visible top-level windows and returns a list of 
        (hwnd, title) tuples.
        """
        windows = []

        def callback(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd):
                window_title = win32gui.GetWindowText(hwnd)
                window_class = win32gui.GetClassName(hwnd)
                process_data = self.getProcessFromHwnd(hwnd)
                process_name = process_data["process_path"] if process_data else None
                process_path = process_data["process_path"] if process_data else None
                hwnd = process_data["hwnd"] if process_data else None
                
                if window_title:  # Only include windows with a non-empty title
                    data = {
                        "hwnd" : hwnd,
                        "process_path": process_path,
                        "process_name" : process_name,
                        "window_title": window_title,
                        "window_class": window_class
                    }
                    windows.append(data)
            return True # Continue enumeration

        win32gui.EnumWindows(callback, None)
        return windows
    
    def getProcessWindowHwnd(self, path : str):
        ''' gets the window handle for the given process '''
        if not path or not os.path.isfile(path):
            return None
        data = self.getWindows()
        info = next((item for item in data if item["process_path"].casefold() == path.casefold()), None)
        if info:
            return info["hwnd"]
        return None
    
    def getProcessFromHwnd(self, hwnd):
        """
        Retrieves the process ID and a process handle from a window handle.

        Args:
            hwnd (int): The window handle (HWND).

        Returns:
            dict: A dictionary containing the thread ID, process ID, process handle,
                and process name. Returns None if the process cannot be opened.
        """
        try:
            # 1. Get the Thread ID and Process ID from the window handle
            # The function returns the thread ID, and the second argument (pid) 
            # is filled with the process ID.
            thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
            
            # 2. Open the process to get a process handle
            # PROCESS_QUERY_LIMITED_INFORMATION (0x1000) is a required access right
            # False means inherit handle is not set.
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            process_handle = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
            process_path = None
            process_name = None
            
            
            # 3. Use psutil to get the process name (optional but helpful)
            try:
                process_name = psutil.Process(process_id).name()

                process = psutil.Process(process_id)
                process_name = process.name()
                process_path = process.exe()



            except psutil.NoSuchProcess:
                process_name = "N/A (Process not found)"
                

            return {
                "hwnd": hwnd,
                "thread_id": thread_id,
                "process_id": process_id,
                "process_handle": process_handle,
                "process_name": process_name,
                "process_path": process_path
            }

        except Exception as e:
            print(f"Error getting process info for HWND {hwnd}: {e}")
            return None
        

    def executeProcess(self, path : str, callback, args : str = None, timeout : float = 5, setfocus : bool = False):
        '''
        Docstring for executeProcess
        :param path: full path to the process to start
        :param args: arguments, optional
        :param callback: callback to call when process is started callback(bool) - true if the process started, false if not
        '''
        if path and os.path.isfile(path):
            hwnd = self.getProcessWindowHwnd(path)
            if hwnd:
                return True
            if not self._is_running:
                self._thread = threading.Thread(target = self._exec_runner, args = (path, args, timeout, callback, setfocus, ))
                self._thread.name = "MapToMouseEx autostart"
                with self._lock:
                    self._is_running = True
                self._thread.start()

        

           
    def _exec_runner(self, path : str , args : str, timeout : float, callback, setfocus : bool):
        ''' runs the process and waits to set the focus '''
        verbose = gremlin.config.Configuration().verbose_mode_process
        # execute the process
        self._execute(path, args)
                              
      
        path = path.casefold()
        expires = time.time() + timeout
        info = None
        if verbose: syslog.info("PROCESS: waiting for process to start...")
        while self._is_running and time.time() < expires:
            data = self.getWindows()
            info = next((item for item in data if item["process_path"].casefold() == path), None)
            if info:
                if verbose: syslog.info("PROCESS: process started")
                break
            
            # wait for the process to start
            time.sleep(0.5)

        if info:
            hwnd = info["hwnd"]
            if verbose: syslog.info(f"PROCESS: set focus: handle: [{hwnd}] process: [{info["process_name"]}]")
            if setfocus:
                self.setFocus(hwnd)
            if callback:
                callback(True)

        elif not self._is_running:
            # only issue warning if not aborted
            syslog.warning("PROCESS: start: timeout")
            if callback:
                callback(False)

        self._is_running = False
        

    
    def setFocus(self, hwnd):
        ''' sets the focus to the given window handle '''
        if win32gui.IsIconic(hwnd):
            # restore the window if minimized
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        # enable setforeground if the process is not the current foreground exploiting a windows hack to send the alt key first, then setting the focus
        # this prevents an access denied error
        # in case gremlinEx is not the current foreground application (which it most invariably isn't at runtime)
        try:
            win32api.keybd_event(win32con.VK_MENU, 0, 0, 0) # Alt key down
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0) # Alt key up
            win32gui.SetForegroundWindow(hwnd)
        except Exception as e:
            syslog.error(f"SETFOCUS: error: {e}")

    def _execute(self, path, args = None, args_per_line : bool = False):
        ''' executes the process '''
        import subprocess

        if os.path.isfile(path):
            try:
                cmd_list = [path]
                # if args:
                #     if args_per_line:
                #         args = args.splitlines()
                #     if isinstance(args,list) or isinstance(args,tuple):
                #         cmd_list.extend(arg for arg in args)
                #     else:
                #         cmd_list.append(args)
                if args:
                    os.startfile(path, arguments = args)
                else:
                    os.startfile(path)
                # attemp start (no wait) as a detached process with separate file descriptors
                # creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                # subprocess.Popen(cmd_list, creationflags = creationflags, close_fds = True)
            except:
                pass
        else:
            syslog.error(f"OSACTION: unable to find process: [{path}]")
