# -*- coding: utf-8; -*-

# Based on original Joystick Gremlin work by Lionel Ott and other contributors - Joystick Gremlin Ex is (C) EMCS 2025 
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


import os
from PySide6 import QtWidgets, QtCore
from lxml import etree as ElementTree
import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
import gremlin.ui.dialogs
import gremlin.ui.input_item
import gremlin.ui.ui_common
import gremlin.util
from gremlin.util import safe_read, safe_format
import subprocess
import logging

syslog = logging.getLogger("system")


class RunProcessWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget which allows the configuration of TTS actions."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, RunProcess)

    def _create_ui(self):

        
        
        self.process_widget = gremlin.ui.ui_common.QPathLineItem("Process:",self.action_data.process, self.action_data)
        self.process_widget.pathChanged.connect(self._process_changed_cb)
        self.process_widget.open.connect(self._process_open_cb)
        self.process_widget.installEventFilter(self)

        self.args_widget = QtWidgets.QPlainTextEdit()
        self.args_widget.setPlainText(self.action_data.arguments)
        self.args_widget.textChanged.connect(self._args_changed_cb)
        self.args_widget.installEventFilter(self)


      
        self.run_widget = QtWidgets.QPushButton("Test")
        self.run_widget.setIcon(gremlin.util.load_icon("fa6s.play",qta_color = gremlin.ui.ui_common.Color.activeColor()))
        self.run_widget.setToolTip("Runs the process")
        self.run_widget.clicked.connect(self._run_process)

        self.chkb_exec_on_release = QtWidgets.QCheckBox("Exec on release")
        self.chkb_exec_on_release.setChecked(self.action_data.exec_on_release)
        self.chkb_exec_on_release.setToolTip("Execute the command on input release instead of input press")
        self.chkb_exec_on_release.clicked.connect(self._exec_on_release_changed)

        
        self.options_container_widget = QtWidgets.QWidget()
        self.options_container_widget.setContentsMargins(0,0,0,0)
        self.options_container_layout = QtWidgets.QHBoxLayout(self.options_container_widget)
        self.options_container_layout.setContentsMargins(0,0,0,0)

        
        self.args_by_line_widget = QtWidgets.QCheckBox("Argument per line")
        self.args_by_line_widget.setChecked(self.action_data.args_per_line)
        self.args_by_line_widget.setToolTip("When enabled, each line in the argument list will be passed as a separate argument to the process")
        self.args_by_line_widget.clicked.connect(self._args_per_line_changed)

        self.options_container_layout.addWidget(QtWidgets.QLabel("Arguments:"))
        self.options_container_layout.addStretch()
        self.options_container_layout.addWidget(self.args_by_line_widget)
        

        self.container_widget = QtWidgets.QWidget()
        self.container_layout = QtWidgets.QHBoxLayout(self.container_widget)
        

        self.container_layout.addWidget(self.run_widget)
        self.container_layout.addWidget(self.chkb_exec_on_release)

        self.container_layout.addStretch()


        self.main_layout.addWidget(self.process_widget)
        self.main_layout.addWidget(self.options_container_widget)
        self.main_layout.addWidget(self.args_widget)
        self.main_layout.addWidget(self.container_widget)

        self._update_ui()

    def _process_open_cb(self, widget):
        ''' opens the process executable '''
        fname = widget.data.process
        self.executable_dialog = gremlin.ui.dialogs.ProcessWindow(fname)
        self.executable_dialog.setWindowModality(QtCore.Qt.ApplicationModal)
        self.executable_dialog.data = widget
        self.executable_dialog.process_selected.connect(self._select_executable)
        self.executable_dialog.show()

    def _select_executable(self, fname):
        """Adds the provided executable to the list of configurations.

        :param fname the executable for which to add a mapping
        """
        widget = self.sender()
        w = widget.data
        item = w.data
        item.process = fname
        with QtCore.QSignalBlocker(w):
            w.setText(fname)
        self.action_data.process = fname
        self._update_ui()
        
    @QtCore.Slot(bool)
    def _args_per_line_changed(self, checked):
        self.action_data.args_per_line = checked

    def _exec_on_release_changed(self, checked):
        self.action_data.exec_on_release = checked

    @QtCore.Slot(object, str)
    def _process_changed_cb(self, widget, text):
        self.action_data.process = text
        self._update_ui()

    def eventFilter(self, widget, event):
        t = event.type()
        if t == QtCore.QEvent.Type.FocusOut:
            if widget == self.args_widget:
                self.action_data.arguments = self.args_widget.toPlainText()
            elif widget == self.process_widget:
                self._update_ui()
        return False
    
    def _update_ui(self):
        text = self.process_widget.text()
        if "\"" or "\\" in text:
            # convert windows format to python format
            text = text.replace("\"","").replace("\\","/")
            with QtCore.QSignalBlocker(self.process_widget):
                self.process_widget.setText(text)
            self.action_data.process = text
        enabled = os.path.isfile(self.action_data.process)
        self.run_widget.setEnabled(enabled)

    @QtCore.Slot()
    def _args_changed_cb(self):
        self.action_data.arguments = self.args_widget.toPlainText()


    def _populate_ui(self):
        pass



    @QtCore.Slot()
    def _run_process(self):
        self.action_data.execute()


class RunProcessFunctor(gremlin.base_profile.AbstractFunctor):
    
    

    def __init__(self, action, parent = None):
        super().__init__(action, parent)
        self.action_data = action

    
    def process_event(self, event, value, extra_data = None):
        execute = False
        if self.action_data.exec_on_release and not event.is_pressed:
            execute = True
        elif event.is_pressed:
            execute = True
        if execute:
            self.action_data.execute()

            
        return True
        


class RunProcess(gremlin.base_profile.AbstractAction):

    """Action representing a single TTS entry."""

    name = "Run Process"
    tag = "run-process"

    default_button_activation = (True, False)
    # override default allowed inputs here
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = RunProcessFunctor
    widget = RunProcessWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.process = "" # process to run
        self.arguments = "" # args to send
        self.args_per_line = True # one arg per line
        self.exec_on_release = False # exec on release vs press


    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"Run Process: [{self.process}]  Args: [{self.arguments}]" 

    def icon(self):
        return "fa6s.bolt"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node, data = None):
        if "process" in node.attrib:
            self.process = node.get("process")
        if "args" in node.attrib:
            self.arguments = node.get("args")
        self.args_per_line = safe_read(node,"line_per_arg",bool, True)
        self.exec_on_release = safe_read(node,"exec_on_release",bool, False)
            

    def _generate_xml(self):
        node = ElementTree.Element(self.tag)
        node.set("process", self.process)
        node.set("args", self.arguments)
        node.set("line_per_arg", str(self.args_per_line))
        node.set("exec_on_release", str(self.exec_on_release))
        return node

    def _is_valid(self):
        return len(self.process) and os.path.isfile(self.process)
    
    def execute(self):
        ''' executes the process '''
        try:
            if self.args_per_line:
                args = self.arguments.splitlines()
            else:
                args = self.arguments
            cmd_list = [self.process]
            cmd_list.extend(arg for arg in args)
            process = subprocess.Popen(cmd_list,stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = process.communicate()
            syslog.info(f"PROC: execute process: {self.process} {args}")
            if out:
                syslog.info(f"\toutput: {out.decode()}")
            if err:
                syslog.warning(f"\terror: {err.decode()}")

        except:
            pass


version = 1
name = "run-process"
create = RunProcess
