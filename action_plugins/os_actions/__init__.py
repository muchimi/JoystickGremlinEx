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


from __future__ import annotations
import win32gui
import win32con
import win32api
import win32process
import psutil

import os
from PySide6 import QtWidgets, QtCore
from lxml import etree as ElementTree

import gremlin.actions
import gremlin.config
import gremlin.base_profile
import gremlin.event_handler
from gremlin.input_types import InputType
import gremlin.ui.input_item
from enum import IntEnum
from gremlin.profile import safe_format, safe_read, parse_guid, write_guid
import threading
import gremlin.ui.ui_common
import time
import logging
import psygnal
from psygnal import Signal
from shiboken6 import Shiboken

syslog = logging.getLogger("system")


class OsActionMode (IntEnum):
    SetFocus = 0 # set the focus to a window

    @staticmethod
    def toDescription(value):
        match value:
            case OsActionMode.SetFocus:
                return "Sets the focus to a window"
            case _:
                return f"Don't know how to handle: [{value}]"
            
class ProcessHelper:
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

class FindWindowDialog(gremlin.ui.ui_common.BaseDialogUi):
    def __init__(self, parent = None):
        super().__init__(self.__class__.__name__, parent)
        self.setWindowTitle("Find Process Window")
        self.setModal(True)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.data = [] # tuples of (class : str, title : str)
        self.selected_index = None # nothing selected
        
        refresh_widget = gremlin.ui.ui_common.Buttons.getRefreshWidget("Refresh", callback = self._update_data)

        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()
        self.table = QtWidgets.QTableWidget()
        self.table.setSortingEnabled(True)

        self.scroll_widget.setLayout(self.scroll_layout)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        # Configure the scroll area
        self.scroll_area.setMinimumWidth(400)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)

        self.scroll_layout.addWidget(self.table)

        self.main_layout.addWidget(self.scroll_area)

        headers = [
                "Process",
                "Window Title",
                "Process Path",
        ]

        self.table.setColumnCount(len(headers))
        self.table.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows) # select the entire row
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection) # select a single row at a time
        self.table.currentItemChanged.connect(self._handle_row_changed)
        
        # self.table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        # self.table.customContextMenuRequested.connect(self._context_menu_cb)
        # self.table.viewport().installEventFilter(self)


        self.ok_button = QtWidgets.QPushButton("Ok")
        self.ok_button.clicked.connect(self._handle_ok)

        close_button = QtWidgets.QPushButton("Cancel")
        close_button.clicked.connect(self._handle_cancel)

        widgets = [
            refresh_widget,
            "||",
            self.ok_button,
            close_button
            ]
        
        widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)
        self.main_layout.addWidget(widget)


        self._update_data()

    def _handle_row_changed(self, current, previous):
        if current is not None:
            self.selected_index = current.row()
        self.ok_button.setEnabled(self.selected_index is not None)

    def getSelectedRow(table_widget):
        row = table_widget.currentRow()
        if row > -1:  # Check if a row is actually selected
            row_data = []
            for column in range(table_widget.columnCount()):
                item = table_widget.item(row, column)
                if item is not None:
                    row_data.append(item.text())
                else:
                    row_data.append("") # Handle empty cells
            return row_data
        return None        


   

    def _update_data(self):
        ''' updates the list of windows '''
        pm = ProcessHelper()
        self.data = pm.getWindows()
        self.selected_index = None

        self.table.clearContents()
        self.table.setRowCount(len(self.data))
        for i, item in enumerate(self.data):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(item["process_name"]))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(item["window_title"]))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(item["process_path"]))
                               

        # resize
        self.table.resizeColumnsToContents()

        # ok button
        self.ok_button.setEnabled(self.selected_index is not None)

    def _handle_ok(self):
        self.selected = self.data[self.selected_index]
        self.close()

    def _handle_cancel(self):
        self.selected = None
        self.close()


class OsActionWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget for the pause action."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, OsAction))
    
    def _create(self, action_data=None):
        self.action_data : OsAction = action_data


    def display_name(self):
        ''' returns a display string for the current configuration '''
        return "Pause Action"

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
       
        items = [
            ("Set Window Focus", OsActionMode.SetFocus)
        ]

        grid_widgets = []

        self.action_selector = gremlin.ui.ui_common.QDataComboBox(
            value = self.action_data.action,
            source = items,
            callback = self._handle_action_changed,
            tooltip="Selected Action",
            auto_adjust=True,
        )

        widget = gremlin.ui.ui_common.getHContainer(self.action_selector, "Mode:", widget_only=True)
        self.action_selector.setMaximumWidth(300)
        self.main_layout.addWidget(widget)

        
        self.process_path_widget = gremlin.ui.ui_common.QPathLineItem(text = self.action_data.process_name,
                                                callback = self._handle_process_path_changed,
                                                callback_open= self._handle_find_window,
                                                button_label = "Select Window...")
        self.process_path_widget.setMaximumWidth(300)

        select_process = gremlin.ui.ui_common.QDataPushButton("Select Executable...", callback=self._handle_select_executable)

        container_process = gremlin.ui.ui_common.getHContainer([self.process_path_widget, select_process], widget_only = True)

        start_widget = gremlin.ui.ui_common.QDataCheckbox("Auto-start process if not running",
                                                    value = self.action_data.start_process,
                                                    callback = self._handle_autostart_changed,
                                                    tooltip = "Attemps to start the process if not running.")
        
        self.timeout_widget = gremlin.ui.ui_common.QFloatLineEdit(value = self.action_data.start_timeout,
                                                           min_range=1,
                                                           max_range = 1000,
                                                           step = 1.0,
                                                           callback = self._handle_timeout_changed
                                                           )
        
        self.args_widget = gremlin.ui.ui_common.QLineEdit(self.action_data.process_args,
                                                    callback = self._handle_args_changed,
                                                    tooltip = "Command line arguments to pass to the process (optional)")
        
        margin = 12
        self.container_timeout = gremlin.ui.ui_common.getHContainer(self.timeout_widget,"Process start timeout (s):", widget_only = True, left_margin = margin)
        self.container_args = gremlin.ui.ui_common.getHContainer(self.args_widget,"Process command line arguments:", widget_only = True, left_margin = margin)
        
        
        widgets = [
            "Process Window:",
            container_process,
            start_widget,
            self.container_timeout,
            self.container_args
        ]


        self.container_setfocus = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True)
        self.main_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
        self.main_layout.addWidget(self.container_setfocus)

        self._update_ui()

    def _populate_ui(self):
        pass

    def _handle_timeout_changed(self, value : float):
        self.action_data.start_timeout = value

    def _handle_select_executable(self, widget):
        ''' opens the process executable '''
        import gremlin.ui.dialogs
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Process",
            self.action_data.process_name,
            "Executable files (*.exe)"
        )
        if fname and os.path.isfile(fname):
            self.action_data.process_name = fname
            with QtCore.QSignalBlocker(self.process_path_widget):
                self.process_path_widget.setText(fname)
            self._update_ui()


    @QtCore.Slot(bool)
    def _handle_autostart_changed(self, checked : bool):
        self.action_data.start_process = checked
        self._update_ui()

    @QtCore.Slot(str)
    def _handle_args_changed(self, value : str):
        self.action_data.process_args = value if value else None
        
    @QtCore.Slot(object)
    def _handle_find_window(self, widget):
        ''' show find window dialog '''
        self.dialog = FindWindowDialog()
        self.dialog.closed.connect(self._handle_dialog_closed)
        self.dialog.exec()

    @QtCore.Slot()
    def _handle_dialog_closed(self):
        selected = self.dialog.selected
        if selected:
            self.action_data.process_name = selected["process_path"]
            self.action_data.window_class = selected["window_class"]
            self.action_data.window_title = selected["window_title"]

            with QtCore.QSignalBlocker(self.process_path_widget):
                self.process_path_widget.setText(self.action_data.process_name)
        

    def _handle_action_changed(self, value):
        self.action_data.action = value
        self._update_ui()

    @QtCore.Slot(str)
    def _handle_process_path_changed(self, widget, value : str):
        self.action_data.process_name = value

    @QtCore.Slot(str)
    def _handle_window_class_changed(self, value : str):
        self.action_data.window_class = value


    @QtCore.Slot(str)
    def _handle_window_title_changed(self, value : str):
        self.action_data.window_title = value

        
    def _update_ui(self):
        setfocus_visible = self.action_data.action == OsActionMode.SetFocus
        self.container_setfocus.setVisible(setfocus_visible)

        enabled = self.action_data.start_process
        self.container_args.setEnabled(enabled)
        self.container_timeout.setEnabled(enabled)




class OsActionFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action_data, parent = None):
        super().__init__(action_data, parent)
        self.action_data : OsAction = action_data
        self._is_running = False
        self._lock = threading.Lock()
        self._thread = None

    def profile_stop(self):
        with self._lock:
            self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join()
            self._thread = None
        

    def process_event(self, event : gremlin.event_handler.Event, value : gremlin.actions.Value, extra_data = None):
        
        is_pressed = event.is_pressed
        verbose = gremlin.config.Configuration().verbose_mode_process
        # verbose = True
        if is_pressed:
            match self.action_data.action:
                case OsActionMode.SetFocus:
                    # set focus to a window 
                    try:
                        pm = ProcessHelper()
                        data = pm.getWindows()
                        info = next((item for item in data if item["process_path"].casefold() == self.action_data.process_name.casefold()), None)

                        if not info and self.action_data.start_process:
                            ''' attempt to autostart the process '''
                            if not self._is_running:
                                self._thread = threading.Thread(target = self._exec_runner)
                                self._thread.name = "os action exec"

                                
                                # wait for the process to load
                                with self._lock:
                                    self._is_running = True
                                self._thread.start()
                                return True

                        if info:
                            hwnd = info["hwnd"]
                            if verbose: syslog.info(f"OSACTION: set focus: handle: [{hwnd}] process: [{info["process_name"]}]")
                            self._set_focus(hwnd)
                        

                    except:
                        if verbose: syslog.info(f"OSACTION: set focus: unable to find process window for [{self.action_data.process_name}]")

                
        return True
    
    def _exec_runner(self):
        ''' runs the process and waits to set the focus '''
        verbose = gremlin.config.Configuration().verbose_mode_process
        # execute the process
        self._execute(self.action_data.process_name, self.action_data.process_args)
                              
        pm = ProcessHelper()
        delay = self.action_data.start_timeout
        timeout = time.time() + delay
        info = None
        if verbose: syslog.info("OSACTION: waiting for process to start...")
        while self._is_running and time.time() < timeout:
            data = pm.getWindows()
            info = next((item for item in data if item["process_path"].casefold() == self.action_data.process_name.casefold()), None)
            if info:
                if verbose: syslog.info("OSACTION: process started")
                break
            
            # wait for the process to start
            time.sleep(0.5)

        if info:
            hwnd = info["hwnd"]
            if verbose: syslog.info(f"OSACTION: set focus: handle: [{hwnd}] process: [{info["process_name"]}]")
            self._set_focus(hwnd)

        elif not self._is_running:
            # only issue warning if not aborted
            syslog.warning("OSACTION: set focus: unable to find process window (timeout)")

        self._is_running = False

    
    def _set_focus(self, hwnd):
        ''' sets the focus to the given window handle '''
        if win32gui.IsIconic(hwnd):
            # restore the window if minimized
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        # enable setforeground if the process is not the current foreground exploiting a windows hack to send the alt key first, then setting the focus
        # in case gremlinEx is not the current foreground application (which it most invariably isn't at runtime)
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0) # Alt key down
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0) # Alt key up
        win32gui.SetForegroundWindow(hwnd)

    def _execute(self, path, args = None, args_per_line : bool = False):
        ''' executes the process '''
        import subprocess

        if os.path.isfile(path):
            try:
                cmd_list = [path]
                if args:
                    if args_per_line:
                        args = args.splitlines()
                    if isinstance(args,list) or isinstance(args,tuple):
                        cmd_list.extend(arg for arg in args)
                    else:
                        cmd_list.append(args)
                # attemp start (no wait)
                subprocess.Popen(cmd_list)
            except:
                pass
        else:
            syslog.error(f"OSACTION: unable to find process: [{path}]")



class OsAction(gremlin.base_profile.AbstractAction):

    """Action for pausing the execution of callbacks."""

    name = "OS Action"
    tag = "os-action"
    hint = '''Performs OS level actions'''

    default_button_activation = (True, False)
    
    input_types = [
         InputType.JoystickButton,
         InputType.JoystickHat,
    ]

    functor = OsActionFunctor
    widget = OsActionWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.action = OsActionMode.SetFocus
        self.process_name : str = None # process name
        self.window_class : str = None # window class
        self.window_title : str = None # window title
        self.start_process = False # if true, starts the process if it's not running
        self.process_args : str = None # process start args (optional)
        self.start_timeout : float = 5 # number of seconds to wait for the process to start


    def icon(self):
        return "mdi.windows"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node, data = None, extra_data = None):

        value = safe_read(node, "action", int, 0)
        try:
            self.action = OsActionMode(value)
        except:
            pass
        if "window-class" in node.attrib:
            self.window_class = node.get("window-class")
        if "window-title" in node.attrib:
            self.window_title = node.get("window-title")
        if "process-name" in node.attrib:
            self.process_name = node.get("process-name")
        self.start_process = safe_read(node,"auto-start", bool, False)
        if "args" in node.attrib:
            args = node.get("args")
            if args:
                self.process_args = args
        self.start_timeout = safe_read(node,"timeout", float, 5.0)

    def _generate_xml(self):
        node = ElementTree.Element(self.tag)
        node.set("action", safe_format(self.action, int))
        if self.process_name:
            node.set("process-name", self.process_name)
        if self.window_class:
            node.set("window-class", self.window_class)
        if self.window_title:
            node.set("window-title", self.window_title)
        node.set("auto-start",safe_format(self.start_process, bool))
        if self.process_args:
            node.set("args", self.process_args)
        node.set("timeout", safe_format(self.start_timeout, float))

            
        return node

    def _is_valid(self):
        return True


version = 1
name = "OS Action"
create = OsAction
