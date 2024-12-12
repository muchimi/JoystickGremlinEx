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

# Definition of the flags for limited information queries
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

@SingletonDecorator
class ProcessMonitor(QtCore.QObject):

    """Monitors the currently active window process.

    This class continuously monitors the active window and whenever
    it changes the path to the executable is retrieved and signaled
    to the rest of the system using Qt's signal / slot mechanism.
    """

    # Signal emitted when the active window changes
    process_changed = QtCore.Signal(str)




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
        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self.start)
        el.profile_stop_toolbar.connect(self.stop) # stop listener only if manual toolbar button clicked
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
        


    def start(self):
        """Starts monitoring the current process."""
        config = gremlin.config.Configuration()
        option_auto_load = config.autoload_profiles
        option_auto_load_on_focus = config.activate_on_process_focus
        if option_auto_load or option_auto_load_on_focus:
            self._enabled = True
            if not self._running:
                syslog = logging.getLogger("system")
                verbose = gremlin.config.Configuration().verbose_mode_process
                if verbose: syslog.info("Process Monitor: start")
                self._running = True
                self._update_thread = threading.Thread(target=self._update)
                self._update_thread.start()

    def stop(self):
        """Stops monitoring the current process."""
        if not self._running:
            return # nothing to do
            
        self._running = False
        verbose = gremlin.config.Configuration().verbose_mode_process
        syslog = logging.getLogger("system")
        if verbose: syslog.info("Process Monitor: stop")
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


def list_current_processes():
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
