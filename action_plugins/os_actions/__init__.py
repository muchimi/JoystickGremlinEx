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


from __future__ import annotations  # deprecated with python 3.14+
import win32gui
import win32con
import win32api

import os
from PySide6 import QtWidgets, QtCore
from lxml import etree as ElementTree

import gremlin.actions
import gremlin.config
import html
import gremlin.base_profile
import gremlin.event_handler
from gremlin.input_types import InputType
import gremlin.input_item
from enum import IntEnum
from gremlin.profile import safe_format, safe_read
import threading
import gremlin.ui.ui_common
import time
import logging
from shiboken6 import Shiboken
import gremlin.process

syslog = logging.getLogger("system")


class OsActionMode(IntEnum):
    SetFocus = 0  # set the focus to a window

    @staticmethod
    def toDescription(value):
        match value:
            case OsActionMode.SetFocus:
                return "Sets the focus to a window"
            case _:
                return f"Don't know how to handle: [{value}]"


class OsActionWidget(gremlin.input_item.AbstractActionWidget):
    """Widget for the pause action."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, OsAction)

    def _create(self, action_data=None):
        self.action_data: OsAction = action_data

    def display_name(self):
        """returns a display string for the current configuration"""
        return "Pause Action"

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return

        items = [("Set Window Focus", OsActionMode.SetFocus)]

        self.action_selector = gremlin.ui.ui_common.QDataComboBox(
            value=self.action_data.action,
            source=items,
            callback=self._handle_action_changed,
            tooltip="Selected Action",
            auto_adjust=True,
        )

        widget = gremlin.ui.ui_common.getHContainer(self.action_selector, "Mode:", widget_only=True)
        self.action_selector.setMaximumWidth(300)
        self.main_layout.addWidget(widget)

        self.process_path_widget = gremlin.ui.ui_common.QPathLineItem(
            text=self.action_data.process_name,
            callback=self._handle_process_path_changed,
            callback_open=self._handle_find_window,
            button_label="Select Window...",
        )
        self.process_path_widget.setMaximumWidth(300)

        select_process = gremlin.ui.ui_common.QDataPushButton("Select Executable...", callback=self._handle_select_executable)

        container_process = gremlin.ui.ui_common.getHContainer([self.process_path_widget, select_process], widget_only=True)

        start_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Auto-start process if not running",
            value=self.action_data.start_process,
            callback=self._handle_autostart_changed,
            tooltip="Attemps to start the process if not running.",
        )

        self.timeout_widget = gremlin.ui.ui_common.QFloatLineEdit(
            value=self.action_data.start_timeout,
            min_range=1,
            max_range=1000,
            step=1.0,
            callback=self._handle_timeout_changed,
        )

        self.args_widget = gremlin.ui.ui_common.QLineEdit(
            self.action_data.process_args,
            callback=self._handle_args_changed,
            tooltip="Command line arguments to pass to the process (optional)",
        )

        margin = 12
        self.container_timeout = gremlin.ui.ui_common.getHContainer(
            self.timeout_widget,
            "Process start timeout (s):",
            widget_only=True,
            left_margin=margin,
        )
        self.container_args = gremlin.ui.ui_common.getHContainer(
            self.args_widget,
            "Process command line arguments:",
            widget_only=True,
            left_margin=margin,
        )

        widgets = [
            "Process Window:",
            container_process,
            start_widget,
            self.container_timeout,
            self.container_args,
        ]

        self.container_setfocus = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)
        self.main_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
        self.main_layout.addWidget(self.container_setfocus)

        self._update_ui()

    def _populate_ui(self):
        pass

    def _handle_timeout_changed(self, value: float):
        self.action_data.start_timeout = value

    def _handle_select_executable(self, widget):
        """opens the process executable"""
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(None, "Process", self.action_data.process_name, "Executable files (*.exe)")
        if fname and os.path.isfile(fname):
            self.action_data.process_name = fname
            with QtCore.QSignalBlocker(self.process_path_widget):
                self.process_path_widget.setText(fname)
            self._update_ui()

    @QtCore.Slot(bool)
    def _handle_autostart_changed(self, checked: bool):
        self.action_data.start_process = checked
        self._update_ui()

    @QtCore.Slot(str)
    def _handle_args_changed(self, value: str):
        self.action_data.process_args = value if value else None

    @QtCore.Slot(object)
    def _handle_find_window(self, widget):
        """show find window dialog"""
        self.dialog = gremlin.ui.ui_common.FindWindowDialog()
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
    def _handle_process_path_changed(self, widget, value: str):
        self.action_data.process_name = value

    @QtCore.Slot(str)
    def _handle_window_class_changed(self, value: str):
        self.action_data.window_class = value

    @QtCore.Slot(str)
    def _handle_window_title_changed(self, value: str):
        self.action_data.window_title = value

    def _update_ui(self):
        setfocus_visible = self.action_data.action == OsActionMode.SetFocus
        self.container_setfocus.setVisible(setfocus_visible)

        enabled = self.action_data.start_process
        self.container_args.setEnabled(enabled)
        self.container_timeout.setEnabled(enabled)


class OsActionFunctor(gremlin.base_profile.AbstractFunctor):
    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent)
        self.action_data: OsAction = action_data
        self._is_running = False
        self._lock = threading.Lock()
        self._thread = None

    def profile_stop(self):
        with self._lock:
            self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join()
            self._thread = None

    def process_event(
        self,
        event: gremlin.event_handler.Event,
        value: gremlin.actions.Value,
        extra_data=None,
    ):

        is_pressed = event.is_pressed
        verbose = gremlin.config.Configuration().verbose_mode_process
        # verbose = True
        if is_pressed:
            match self.action_data.action:
                case OsActionMode.SetFocus:
                    # set focus to a window
                    try:
                        pm = gremlin.process.ProcessHelper()
                        data = pm.getWindows()
                        info = next(
                            (item for item in data if item["process_path"].casefold() == self.action_data.process_name.casefold()),
                            None,
                        )

                        if not info and self.action_data.start_process:
                            """ attempt to autostart the process """
                            if not self._is_running:
                                self._thread = threading.Thread(target=self._exec_runner)
                                self._thread.name = "os action exec"

                                # wait for the process to load
                                with self._lock:
                                    self._is_running = True
                                self._thread.start()
                                return True

                        if info:
                            hwnd = info["hwnd"]
                            if verbose:
                                syslog.info(f"OSACTION: set focus: handle: [{hwnd}] process: [{info['process_name']}]")
                            self._set_focus(hwnd)

                    except Exception:
                        if verbose:
                            syslog.info(f"OSACTION: set focus: unable to find process window for [{self.action_data.process_name}]")

        return True

    def _exec_runner(self):
        """runs the process and waits to set the focus"""
        verbose = gremlin.config.Configuration().verbose_mode_process
        # execute the process
        self._execute(self.action_data.process_name, self.action_data.process_args)

        pm = gremlin.process.ProcessHelper()
        delay = self.action_data.start_timeout
        timeout = time.time() + delay
        info = None
        if verbose:
            syslog.info("OSACTION: waiting for process to start...")
        while self._is_running and time.time() < timeout:
            data = pm.getWindows()
            info = next(
                (item for item in data if item["process_path"].casefold() == self.action_data.process_name.casefold()),
                None,
            )
            if info:
                if verbose:
                    syslog.info("OSACTION: process started")
                break

            # wait for the process to start
            time.sleep(0.5)

        if info:
            hwnd = info["hwnd"]
            if verbose:
                syslog.info(f"OSACTION: set focus: handle: [{hwnd}] process: [{info['process_name']}]")
            self._set_focus(hwnd)

        elif not self._is_running:
            # only issue warning if not aborted
            syslog.warning("OSACTION: set focus: unable to find process window (timeout)")

        self._is_running = False

    def _set_focus(self, hwnd):
        """sets the focus to the given window handle"""
        if win32gui.IsIconic(hwnd):
            # restore the window if minimized
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        # enable setforeground if the process is not the current foreground exploiting a windows hack to send the alt key first, then setting the focus
        # in case gremlinEx is not the current foreground application (which it most invariably isn't at runtime)
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)  # Alt key down
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)  # Alt key up
        win32gui.SetForegroundWindow(hwnd)

    def _execute(self, path, args=None, args_per_line: bool = False):
        """executes the process"""

        if os.path.isfile(path):
            try:
                if args:
                    os.startfile(path, arguments=args)
                else:
                    os.startfile(path)

            except Exception as e:
                syslog.error(f"OSACTION: process start error: {e}")
        else:
            syslog.error(f"OSACTION: unable to find process: [{path}]")


class OsAction(gremlin.base_profile.AbstractAction):
    """Action for pausing the execution of callbacks."""

    name = "OS Action"
    tag = "os-action"
    hint = """Performs OS level actions"""

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
        self.process_name: str = None  # process name
        self.window_class: str = None  # window class
        self.window_title: str = None  # window title
        self.start_process = False  # if true, starts the process if it's not running
        self.process_args: str = None  # process start args (optional)
        self.start_timeout: float = 5  # number of seconds to wait for the process to start

    def icon(self):
        return "mdi.windows"

    def requires_virtual_button(self):
        return self.get_input_type() in [InputType.JoystickAxis, InputType.JoystickHat]

    def _parse_xml(self, node, data=None, extra_data=None):

        value = safe_read(node, "action", int, 0)
        try:
            self.action = OsActionMode(value)
        except Exception:
            pass
        if "window-class" in node.attrib:
            value = safe_read(node, "window-class", str, "")
            if value:
                try:
                    value = html.unescape(value)
                except Exception:
                    syslog.error(f"OSACTION: Unable to convert window class name: [{value}] due to invalid data.")
                    value = None
            self.window_class = value
        if "window-title" in node.attrib:
            self.window_title = node.get("window-title")
        if "process-name" in node.attrib:
            self.process_name = node.get("process-name")
        self.start_process = safe_read(node, "auto-start", bool, False)
        if "args" in node.attrib:
            args = node.get("args")
            if args:
                self.process_args = args
        self.start_timeout = safe_read(node, "timeout", float, 5.0)

    def _generate_xml(self):
        node = ElementTree.Element(self.tag)
        node.set("action", safe_format(self.action, int))
        if self.process_name:
            node.set("process-name", self.process_name)
        if self.window_class:
            try:
                escaped = html.escape(self.window_class)
                if escaped:
                    node.set("window-class", safe_format(escaped, str))
            except Exception:
                syslog.error(f"OSACTION: Unable to save window class name: [{self.window_class}] due to invalid data.")

        if self.window_title:
            node.set("window-title", self.window_title)
        node.set("auto-start", safe_format(self.start_process, bool))
        if self.process_args:
            node.set("args", self.process_args)
        node.set("timeout", safe_format(self.start_timeout, float))

        return node

    def _is_valid(self):
        return True


version = 1
name = "OS Action"
create = OsAction
