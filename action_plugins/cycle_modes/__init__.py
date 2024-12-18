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


import os
from PySide6 import QtCore, QtGui, QtWidgets
from lxml import etree as ElementTree

from PySide6.QtGui import QIcon
from PySide6.QtCore import QModelIndex


import gremlin.base_profile 
import gremlin.event_handler
from gremlin.input_types import InputType
import gremlin.shared_state
import gremlin.ui.input_item
import gremlin.ui.ui_common



class CycleModeModel(QtCore.QAbstractItemModel):
    def __init__(self):
        super().__init__()
        self._data = {}
        
    def rowCount(self, parent = None):
        return len(self._data)

    def columnCount(self, parent = None):
        return 1
    
    def clear(self):
        self._data.clear()

    def addItem(self, display, mode):
        count = len(self._data)
        self.beginInsertRows(QModelIndex(), count, count)
        self._data[count] = (mode, display)
        self.endInsertRows()

    def data(self, index : QModelIndex, role = QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        
        if role == QtCore.Qt.DisplayRole:
            row = index.row()
            return self._data[row][1]
        return None
    
    def swap(self, index_a, index_b):
        ''' swaps two indices '''
        data_a = self._data[index_a]
        data_b = self._data[index_b]
        self._data[index_a] = data_b
        self._data[index_b] = data_a

    def moveUp(self, index):
        count = len(self._data)
        if index == 0 or count == 1:
            return
        index_a = index
        index_b = index - 1
        self.swap(index_a, index_b)

    def moveDown(self, index):
        count = len(self._data)
        if index == count or count == 1:
            return
        index_a = index
        index_b = index + 1
        self.swap(index_a, index_b)

    def remove(self, index):
        if index in self._data:
            del self._data[index]

    def modes(self):
        ''' gets the modes in the list'''
        return [data[0] for data in self._data.values()]
    
    def index(self, row, column, parent=QModelIndex()):
        if not row in self._data:
            return QModelIndex()

        return self.createIndex(row, column, row)
    
    def parent(self, index):
        return QModelIndex()

    def __len__(self):
        return len(self._data)

class CycleModesWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget allowing the configuration of a list of modes to cycle."""

    locked = False

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, CycleModes))



        

    def _create_ui(self):

        from gremlin.util import load_icon

        self.ec = gremlin.execution_graph.ExecutionContext()
        self.model = CycleModeModel()
        self.view = QtWidgets.QListView()
        self.view.setModel(self.model)
   
        self.view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        # Add widgets which allow modifying the mode list
        self.mode_list_widget = gremlin.ui.ui_common.NoWheelComboBox()
        self.add = QtWidgets.QPushButton(load_icon("list_add.svg"),  "Add") 
        self.add.clicked.connect(self._add_cb)
        self.delete = QtWidgets.QPushButton(load_icon("list_delete.svg"), "Delete")
        
        self.delete.clicked.connect(self._remove_cb)
        self.up = QtWidgets.QPushButton(load_icon("list_up.svg"), "Up")
        
        self.up.clicked.connect(self._up_cb)
        self.down = QtWidgets.QPushButton(load_icon("list_down.svg"), "Down")

        self.down.clicked.connect(self._down_cb)

        self.button_container_widget = QtWidgets.QWidget()
        self.button_container_layout = QtWidgets.QHBoxLayout(self.button_container_widget)
        self.button_container_layout.addWidget(QtWidgets.QLabel("Mode:"))
        self.button_container_layout.addWidget(self.mode_list_widget)
        self.button_container_layout.addStretch()
        self.button_container_layout.addWidget(self.add)
        self.button_container_layout.addWidget(self.delete)
        self.button_container_layout.addWidget(self.up)
        self.button_container_layout.addWidget(self.down)
        


        self.main_layout.addWidget(self.view)
        self.main_layout.addWidget(self.button_container_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        eh = gremlin.event_handler.EventListener()
        eh.modes_changed.connect(self._modes_changed)



    def _populate_ui(self):
        self._update_mode_list()

    def save_changes(self):
        """Saves UI state to the profile."""
        mode_list = self.model.modes()
        self.action_data.mode_list = mode_list
        self.action_modified.emit()

    def _update_mode_list(self):

        
        with QtCore.QSignalBlocker(self.mode_list_widget):
            self.mode_list_widget.clear()
            
            mode_data = self.ec.getModeNames(as_tuple=True)
            #modes = gremlin.shared_state.current_profile.get_modes()
            self.model.clear()
            for mode, display in mode_data:
                self.mode_list_widget.addItem(display, mode)

        # verify the modes in the cycle are valid
        mode_list = self.action_data.mode_list
        modes = gremlin.shared_state.current_profile.get_modes()
        for mode in mode_list:
            if not mode in modes:
                mode_list.remove(mode)
        self.model.clear()
        for mode in mode_list:
            node = self.ec.searchModeTree(mode)
            self.model.addItem(node.display, mode)
        
        
      
        

            
            

    @QtCore.Slot()
    def _modes_changed(self):
        ''' occurs when the modes are edited or changed '''
        self._update_mode_list()


    @QtCore.Slot()
    def _add_cb(self):
        """Adds the currently selected mode to the list of modes."""
        
        mode = self.mode_list_widget.currentData()
        display = self.mode_list_widget.currentText()
        
        self.model.addItem(display, mode)
        self.save_changes()

    @QtCore.Slot()
    def _up_cb(self):
        """Moves the currently selected mode upwards."""
        index = self.view.currentIndex().row()
        self.model.moveUp(index)
        self.save_changes()

    @QtCore.Slot()
    def _down_cb(self):
        """Moves the currently selected mode downwards."""
        index = self.view.currentIndex().row()
        self.model.moveDown(index)
        self.save_changes()

    @QtCore.Slot()
    def _remove_cb(self):
        """Removes the currently selected mode from the list of modes."""
        index = self.view.currentIndex().row()
        self.mode.remove(index)
        self.save_changes()


class CycleModesFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action, parent = None):
        super().__init__(action, parent)
        self.action_data : CycleModes = action
        

    def process_event(self, event, value):
        if event.is_pressed:
            mode_list = self.action_data.mode_list
            index = self.action_data.mode_index
            index += 1
            if index == len(mode_list):
                # loop around
                index = 0
            next_mode = mode_list[index]

            current_mode = gremlin.shared_state.current_mode
            if current_mode in mode_list and current_mode == next_mode:
                # find the next mode as the current mode is alredy the mode to cycle to so pick the next one
                index = mode_list.index(current_mode)
                index += 1
                if index == len(mode_list):
                    index = 0
                next_mode = self.action_data.mode_list[index]

            self.action_data.mode_index = index

            gremlin.event_handler.EventHandler().change_mode(next_mode)
            
        

    


        
        return True


class CycleModes(gremlin.base_profile.AbstractAction):

    """Action allowing the switching through a list of modes."""

    name = "Cycle Modes"
    tag = "cycle-modes"

    default_button_activation = (True, False)

    # override allowed input types if different from default
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard,
        
    # ]

    functor = CycleModesFunctor
    widget = CycleModesWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.mode_list = []
        self.mode_index = 0 # index of the current cycle mode

    def icon(self):
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node):
        for child in node:
            self.mode_list.append(child.get("name"))

    def _is_valid(self):
        return len(self.mode_list) > 0

    def _generate_xml(self):
        node = ElementTree.Element("cycle-modes")
        for mode_name in self.mode_list:
            child = ElementTree.Element("mode")
            child.set("name", mode_name)
            node.append(child)
        return node

    @property
    def priority(self):
        # priority relative to other actions in this sequence - 0 is the default for all actions unless specified - higher numbers run last
        return 999
    
version = 1
name = "cycle-modes"
create = CycleModes
