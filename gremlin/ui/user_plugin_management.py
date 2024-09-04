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

import logging

from PySide6 import QtCore, QtGui, QtWidgets


from gremlin.common import PluginVariableType
import gremlin.config
from gremlin.util import load_icon, userprofile_path
import gremlin.base_profile
from gremlin.input_types import InputType
import gremlin.user_plugin
import gremlin.ui.ui_common
import os

import gremlin.util



class ModuleManagementController(QtCore.QObject):

    def __init__(self, profile_data, parent=None):
        super().__init__(parent)

        # This is essentially the model
        self.profile_data = profile_data

        # The view managed by the controller
        self.view = ModuleManagementView()

        # stores a map of instance widgets by instance
        self.instance_widget_map = {}

        self.view.add_module.connect(self.new_module)
        self.refresh_module_list()

    def module_list(self):
        return [module.file_name for module in self.profile_data.plugins]

    def new_module(self, fname):
        if fname != "":
            # Only add a new entry if the module doesn't exist yet
            if fname not in [v.file_name for v in self.profile_data.plugins]:
                # Update the model
                module = gremlin.base_profile.Plugin(self.profile_data)
                module.file_name = fname

                # Create new data instance
                instance = self._create_module_instance("Default", module)

                self.profile_data.plugins.append(module)

                # Update the view
                self.view.module_list.add_module(
                    self._create_module_widget(self.profile_data.plugins[-1])
                )

    def remove_module(self, file_name):
        # Remove the module from the model
        for i, module in enumerate(self.profile_data.plugins):
            if module.file_name == file_name:
                del self.profile_data.plugins[i]
                break

        # Remove corresponding UI element
        for module_widget in self.view.module_list.widget_list:
            if module_widget.get_module_name() == file_name:
                self.view.module_list.remove_module(module_widget)

    def create_new_module_instance(self, module_widget, module_data):
        # Create new data instance
        instance = self._create_module_instance("New Instance", module_data)

        # Create the UI side of things
        instance_widget = InstanceWidget(instance.name)
        self._connect_instance_signals(instance, instance_widget)
        module_widget.add_instance(instance_widget)

    def refresh_module_list(self):
        # Empty module list and then add one module at a time
        self.view.module_list.clear()
        for plugin in self.profile_data.plugins:
            self.view.module_list.add_module(
                self._create_module_widget(plugin)
            )

    def remove_instance(self, instance, widget):
        # Remove model
        del instance.parent.instances[instance.parent.instances.index(instance)]
        # Remove view
        widget.parent().remove_instance(widget)

    def rename_instance(self, instance, widget, name):
        instance.name = name
        widget.label_name.setText(name)

    def copy_instance(self, instance, widget):
        ''' copy to a new instance '''
        import re
        gremlin.util.pushCursor()
        module_data = instance.parent
        new_instance =  gremlin.base_profile.PluginInstance(module_data)
        
        not_unique = True

        if instance.name.endswith("copy"):
            name_stub = instance.name
            index = 1
            copy_name = name_stub + f" {index}"
        else:
            m = re.search(r'copy \d+$', instance.name)
            if m is None:
                # does not end in numerical sequence
                index = 0
                name_stub = instance.name + " copy"
                copy_name = name_stub
            else:
                # ends in sequence
                stub = m.group()
                seq = stub.split()[-1]
                index = int(seq) + 1
                name_stub = instance.name[:-len(seq)].strip()
                copy_name = name_stub + f" {index}"
            
            
        while not_unique:
            for item in instance.parent.instances:
                if item.name == copy_name:
                    index+=1
                    copy_name = name_stub + f" {index}"
                    break
                not_unique = False
        new_instance.name = copy_name
        for var in instance.variables.values():
            new_var = var.duplicate()
            new_instance.set_variable(new_var.name, new_var)

        module_data.instances.append(new_instance)
        module_widget = widget.module_widget
        new_instance_widget =  InstanceWidget(new_instance.name)
        new_instance_widget.module_widget = module_widget
        

        module_widget.add_instance(new_instance_widget)
        self._connect_instance_signals(new_instance, new_instance_widget)
        gremlin.util.popCursor()


    def configure_instance(self, instance, widget):
        # Get data from the custom module itself
        variables = gremlin.user_plugin.get_variable_definitions(
            instance.parent.file_name
        )

        layout = self.view.right_panel.layout()
        gremlin.ui.ui_common.clear_layout(layout)


        # add the name of the instance being configured
        header_container_widget = QtWidgets.QWidget()
        header_container_layout = QtWidgets.QHBoxLayout(header_container_widget)
        header_container_widget.setContentsMargins(0,0,0,0)
        header_container_layout.setContentsMargins(0,0,0,0)


        instance_name_widget = gremlin.ui.ui_common.QDataLineEdit(text=instance.name)
        instance_name_widget.setStyleSheet("border-style: solid;border-width: 1px;")
        instance_name_widget.data = instance
        instance_name_widget.textChanged.connect(self._update_instance_name_cb)
        header_container_layout.addWidget(QtWidgets.QLabel("Instance:"))
        header_container_layout.addWidget(instance_name_widget)
        #header_container_layout.addStretch()

        layout.addWidget(header_container_widget)
        layout.addWidget(gremlin.ui.ui_common.QHLine())
        verbose = gremlin.config.Configuration().verbose


        if verbose:
            log = logging.getLogger("system")
            log.info(f"Configure instance: {instance.name}")
        for var in variables:
            # if verbose:
            #     log.info(f"\t{str(var)}")
            if var.variable_type is not None:
                # Create basic profile variable instance if it does not exist
                if not instance.has_variable(var.label):
                    profile_var = gremlin.base_profile.PluginVariable(instance)
                    profile_var.name = var.label
                    profile_var.type = var.variable_type
                    profile_var.value = var.value

                # Update profile variable properties if needed
                profile_var = instance.get_variable(var.label)
                if profile_var.type is None:
                    profile_var.is_optional = var.is_optional
                    profile_var.type = var.variable_type
                    profile_var.value = var.value
                    instance.set_variable(var.label, profile_var)

                if verbose:
                    log.info(f"\t{str(profile_var)}")
                

                ui_element = var.create_ui_element(profile_var.value)
                var.value_changed.connect(
                    self._create_value_changed_cb(
                        profile_var,
                        ui_element,
                        self._update_value_variable
                    )
                )
                layout.addLayout(ui_element)
            else:
                logging.getLogger("system").error(
                    "Invalid variable type encountered in user "
                    f"plugin {instance.parent.file_name} : {var.label}"
                )
                layout.addWidget(QtWidgets.QLabel(var.label))
        layout.addStretch()

    @QtCore.Slot()
    def _update_instance_name_cb(self):
        widget = self.sender()
        instance = widget.data
        name = widget.text()
        instance_widget = self.instance_widget_map[instance]
        self.rename_instance(instance, instance_widget, name )

    def _update_value_variable(self, data, widget, variable):
        if variable.type in [
            PluginVariableType.Bool,
            PluginVariableType.Float,
            PluginVariableType.Int,
            PluginVariableType.Mode,
            PluginVariableType.Selection,
            PluginVariableType.String,
        ]:
            variable.value = data["value"]
        elif variable.type == PluginVariableType.VirtualInput:
            variable.value = data
        elif variable.type == PluginVariableType.PhysicalInput:
            variable.value = data
            button = widget.itemAtPosition(0, 1).widget()
            input_id = f"{data["input_id"]:d}"
            if data["input_type"] == InputType.JoystickAxis:
                input_id = gremlin.types.AxisNames.to_string(
                    gremlin.types.AxisNames(data["input_id"])
                )
            button.setText(
                f"{data["device_name"]} {InputType.to_string(data["input_type"]).capitalize()} {input_id}"
                )

        variable.is_valid = True

    def _create_value_changed_cb(self, variable, widget, callback):
        return lambda data: callback(data, widget, variable)

    def _create_module_widget(self, module_data):
        # Create the module widget
        module_widget = ModuleWidget(module_data.file_name)
        self.instance_widget_map.clear()
        for instance in module_data.instances:
            instance_widget = InstanceWidget(instance.name)
            instance_widget.module_widget = module_widget
            self._connect_instance_signals(instance, instance_widget)
            module_widget.add_instance(instance_widget)
            self.instance_widget_map[instance] = instance_widget

        module_widget.btn_delete.clicked.connect(
            lambda x: self.remove_module(module_data.file_name)
        )
        if module_widget.has_variables:
            module_widget.btn_add_instance.clicked.connect(
                lambda: self.create_new_module_instance(module_widget, module_data)
            )

        return module_widget

    def _connect_instance_signals(self, instance, widget):
        widget.renamed.connect(
            lambda x: self.rename_instance(instance, widget, x)
        )
        widget.btn_delete.clicked.connect(
            lambda x: self.remove_instance(instance, widget)
        )
        widget.btn_configure.clicked.connect(
            lambda x: self.configure_instance(instance, widget)
        )
        widget.btn_copy.clicked.connect(
            lambda x: self.copy_instance(instance, widget)
        )

    def _create_module_instance(self, name, module_data):
        # Create the model data side of things
        instance = gremlin.base_profile.PluginInstance(module_data)
        instance.name = name

        # Properly populate the new instance with default values for all
        # variables
        variables = gremlin.user_plugin.get_variable_definitions(
            instance.parent.file_name
        )
        for var in variables:
            ivar = instance.get_variable(var.label)
            ivar.name = var.label
            ivar.type = var.variable_type
            ivar.value = var.value
            ivar.is_valid = var.value is not None

        module_data.instances.append(instance)

        return instance


class ModuleManagementView(QtWidgets.QSplitter):

    add_module = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.controller = None
        

        # Create the left panel showing the modules and their instances
        self.left_panel = QtWidgets.QWidget()
        self.left_panel.setLayout(QtWidgets.QVBoxLayout())

        # Displays the various modules and instances associated with them
        self.module_list = ModuleListWidget()


        # Button to add a new module
        self.btn_add_module = QtWidgets.QPushButton(load_icon("gfx/list_add.svg"), "Add Plugin")
        
        self.btn_add_module.clicked.connect(self._prompt_user_for_module)

        self.left_panel.layout().addWidget(self.module_list)
        self.left_panel.layout().addWidget(self.btn_add_module)

        # Create the right panel which will show the parameters of a
        # selected module instance
        self.right_panel = QtWidgets.QWidget()
        self.right_panel.setLayout(QtWidgets.QVBoxLayout())

        self.addWidget(self.left_panel)
        self.addWidget(self.right_panel)

    def refresh_ui(self):
        # TODO: stupid refresh code needs changing
        pass

    def _prompt_user_for_module(self):
        """Asks the user to select the path to the module to add."""
        import gremlin.config
        config = gremlin.config.Configuration()
        dir = config.last_plugin_folder
        if dir is None or not os.path.isdir(dir):
            dir = userprofile_path()
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Path to Python plugin",
            dir,
            "Python (*.py)"
        )
        if os.path.isfile(fname):
            dirname,_ = os.path.split(fname)
            config.last_plugin_folder = dirname


            
        self.add_module.emit(fname)


class ModuleListWidget(QtWidgets.QScrollArea):

    """Displays a list of loaded modules."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.widget_list = []
        self.setWidgetResizable(True)

        self.content = QtWidgets.QWidget()
        self.content_layout = QtWidgets.QVBoxLayout()
        self.content_layout.addStretch()
        self.stretch_item = self.content_layout.itemAt(0).spacerItem()
        self.content.setLayout(self.content_layout)
        self.setWidget(self.content)

    def add_module(self, module_widget):
        # Insert provided widget as the last one in the list above the
        # stretcher item
        self.widget_list.append(module_widget)
        self.content_layout.insertWidget(
            self.content_layout.count() - 1,
            module_widget
        )

    def remove_module(self, module_widget):
        module_widget.hide()
        self.content_layout.removeWidget(module_widget)

        del self.widget_list[self.widget_list.index(module_widget)]
        del module_widget

    def clear(self):
        self.widget_list = []
        gremlin.ui.ui_common.clear_layout(self.content_layout)
        self.content.layout().addStretch()


class ModuleWidget(QtWidgets.QFrame):

    def __init__(self, module_name, parent=None):
        super().__init__(parent)

        variables = gremlin.user_plugin.get_variable_definitions(
            module_name
        )
        self.has_variables = len(variables) > 0

        layout = QtWidgets.QVBoxLayout(self)

        self.setStyleSheet("QFrame { background-color : '#ffffff'; }")
        self.setFrameShape(QtWidgets.QFrame.Box)

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.addWidget(QtWidgets.QLabel(module_name))
        header_layout.addStretch()

        if self.has_variables:
            self.btn_add_instance = QtWidgets.QPushButton(
                load_icon("gfx/button_add.png"),""
            )
            header_layout.addWidget(self.btn_add_instance)

        self.btn_delete = QtWidgets.QPushButton(
            load_icon("gfx/button_delete.png"),"")
        header_layout.addWidget(self.btn_delete)

        self.instance_layout = QtWidgets.QVBoxLayout()

        layout.addLayout(header_layout)
        layout.addLayout(self.instance_layout)

    def get_module_name(self):
        header_layout = self.layout().itemAt(0)
        return header_layout.itemAt(0).widget().text()

    def add_instance(self, widget):
        self.instance_layout.addWidget(widget)

    def remove_instance(self, widget):
        widget.hide()
        self.instance_layout.removeWidget(widget)
        del widget


class InstanceWidget(QtWidgets.QWidget):

    """Shows the controls for a particular module instance."""

    renamed = QtCore.Signal(str)


    def __init__(self, name, parent=None):
        super().__init__(parent)

        self.name = name
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(20, 0, 0, 0)
        self._create_ui()

    def _create_ui(self):
        self.label_name = QtWidgets.QLabel(self.name)

        self.btn_rename = QtWidgets.QPushButton(
            load_icon("gfx/button_edit.png"), ""
        )
        self.btn_rename.setToolTip("Rename this instance")

        self.btn_rename.clicked.connect(self.rename_instance)
        self.btn_configure = QtWidgets.QPushButton(
            load_icon("fa.gear"), ""
        )
        self.btn_configure.setToolTip("Configure this instance")
        self.btn_delete = QtWidgets.QPushButton(
             load_icon("gfx/button_delete.png"), ""
        )
        self.btn_delete.setToolTip("Delete this instance")
        self.btn_copy = QtWidgets.QPushButton(load_icon("gfx/button_copy.svg"),"")
        self.btn_copy.setToolTip("Copy this instance")

        self.main_layout.addWidget(self.label_name)
        self.main_layout.addStretch()
        self.main_layout.addWidget(self.btn_rename)
        self.main_layout.addWidget(self.btn_configure)
        self.main_layout.addWidget(self.btn_delete)
        self.main_layout.addWidget(self.btn_copy)

    def rename_instance(self):
        name, user_input = QtWidgets.QInputDialog.getText(
                self,
                "Instance name",
                "New name for this instance",
                QtWidgets.QLineEdit.Normal,
                self.name
        )

        if user_input:
            self.renamed.emit(name)

    @property
    def module_widget(self):
        return self._module_widget
    @module_widget.setter
    def module_widget(self, value):
        self._module_widget = value