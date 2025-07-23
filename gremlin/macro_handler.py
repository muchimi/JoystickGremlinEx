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


import collections
import logging
import os
import pickle
import time
from PySide6 import QtCore, QtGui, QtWidgets
import gremlin.config
from gremlin.input_types import InputType
from gremlin.input_devices import VjoyAction
from gremlin.keyboard import key_from_code, key_from_name
import gremlin.types
import psygnal
from psygnal import Signal


syslog = logging.getLogger("system")

class MacroListModel(QtCore.QAbstractListModel):

    """Model representing a Macro.

    This model supports model modification.
    """

    gfx_path = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "gfx"
    )
    icon_lookup = {}
    

    value_format = {
        InputType.JoystickAxis:
            lambda entry: f"{entry.value:.3f}",
        InputType.JoystickButton:
            lambda entry: "pressed" if entry.value else "released",
        InputType.JoystickHat:
            lambda entry: gremlin.common.direction_tuple_lookup[entry.value]
    }

    def __init__(self, data_storage, parent=None):
        """Creates a new instance.

        :param parent parent widget
        """
        QtCore.QAbstractListModel.__init__(self, parent)
        from gremlin.util import load_icon

        prefix = "dark_" if gremlin.shared_state.is_dark_theme else ""

        MacroListModel.icon_lookup =  {
            "press": load_icon(f"{prefix}press.svg"),
            "release": load_icon(f"{prefix}release.svg"),
            "pause": load_icon(f"{prefix}pause.svg")
        }

        self._data = data_storage

    def rowCount(self, parent=None):
        """Returns the number of rows in the model.

        :param parent the parent of the model
        :return number of rows in the model
        """
        count = len(self._data)
        return count


    def data(self, index, role):
        """Return the data of the index for the specified role.

        :param index the index into the model which is queried
        :param role the role for which the data is to be formatted
        :return data formatted for the given role at the given index
        """


        if not index.isValid():
            return None

        idx = index.row()
        if idx >= len(self._data):
            return ""

        entry = self._data[idx]
        
        if role == QtCore.Qt.SizeHintRole:
            # size hint
            return QtCore.QSize(200, 26)
        elif role == QtCore.Qt.UserRole:
            return entry
        elif role == QtCore.Qt.DecorationRole:
            if isinstance(entry, gremlin.macro.PauseAction):
                return MacroListModel.icon_lookup["pause"]
            elif isinstance(entry, gremlin.macro.KeyAction):
                action = "press" if entry.is_pressed else "release"
                return MacroListModel.icon_lookup[action]
            elif isinstance(entry, gremlin.macro.MouseButtonAction):
                action = "press" if entry.is_pressed else "release"
                return MacroListModel.icon_lookup[action]
            else:
                return None
        elif role == QtCore.Qt.DisplayRole:
            if isinstance(entry, gremlin.macro.JoystickAction):
                device_name = "Unknown"
                for joy in gremlin.joystick_handling.joystick_devices():
                    if joy.device_guid == entry.device_guid:
                        device_name = joy.name
                display =  f"{device_name} {InputType.to_string(entry.input_type).capitalize()} {entry.input_id} - {MacroListModel.value_format[entry.input_type](entry)}"
            elif isinstance(entry, gremlin.macro.KeyAction):
                display =  f"{'Press' if entry.is_pressed else 'Release'} key {entry.key.name}"
            elif isinstance(entry, gremlin.macro.MouseButtonAction):
                if entry.button in [
                    gremlin.types.MouseButton.WheelDown,
                    gremlin.types.MouseButton.WheelUp,
                ]:
                    display =  f"{gremlin.types.MouseButton.to_string(entry.button)}"
                else:
                    display =  f"{'Press' if entry.is_pressed else 'Release'} {gremlin.types.MouseButton.to_string(entry.button)} mouse button"
            elif isinstance(entry, gremlin.macro.MouseMotionAction):
                display =  f"Move mouse by x: {entry.dx:d} y: {entry.dy:d}"
            elif isinstance(entry, gremlin.macro.PauseAction):
                msg = f"Pause for {entry.duration:.3f} s"
                if entry.duration_max != 0:
                    msg += f" to {entry.duration_max:.3f} s"
                if entry.is_random:
                    msg += " (random)"
                display = msg


            elif isinstance(entry, gremlin.macro.VJoyMacroAction):
                display =  f"vJoy {entry.vjoy_id} {InputType.to_string(entry.input_type).capitalize()} {entry.input_id} - {MacroListModel.value_format[entry.input_type](entry)}"

            elif isinstance(entry, gremlin.macro.RemoteControlAction):
                display = f"Remote control: {VjoyAction.to_name(entry.command)}"
            elif isinstance(entry, gremlin.macro.StateAction):
                if gremlin.config.Configuration().show_container_id:
                    if entry.state:
                        display = f"Set state [{entry.state.key}] [{entry.state.id}] {'On' if entry.value else 'Off'}"    
                    else:
                        display = f"Set state [...] {'On' if entry.value else 'Off'}"
            else:
                raise gremlin.error.GremlinError("Unknown macro action")
            
            
            #syslog.debug(display)
            return display
        elif role == QtCore.Qt.FontRole:
            font = QtGui.QFont()
            return font
        elif role == QtCore.Qt.ToolTipRole:
            return "Macro entry"
        elif role == QtCore.Qt.TextAlignmentRole:
            return QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft


        return None
    

    def mimeTypes(self):
        """Returns the MIME types supported by this model for drag & drop.

        :return supported MIME types
        """
        return ["data/macro-action"]

    def mimeData(self, index_list):
        """Returns encoded data for the provided indices.

        :param index_list list of indices to encode
        :return encoded content
        """
        assert len(index_list) == 1
        data = QtCore.QMimeData()
        data.setData(
            "data/macro-action",
            pickle.dumps((self._data[index_list[0].row()], index_list[0].row()))
        )
        return data

    def dropMimeData(self, data, action, row, column, parent):
        """Handles the drop event using the provided MIME encoded data.

        :param data MIME encoded data being dropped
        :param action type of drop action being requested
        :param row the row in which to insert the data
        :param column the column in which to insert the data
        :param parent the parent in the model under which the data is inserted
        :return True if data was processed, False otherwise
        """
        if action != QtCore.Qt.MoveAction:
            return False

        if row == -1:
            return False

        action, old_id = pickle.loads(data.data("data/macro-action"))
        self._data.insert(row, action)

        if old_id > row:
            old_id += 1
        del self._data[old_id]
        return True

    def flags(self, index):
        """Returns the flags of an item.

        :param index the index of the item for which to return the flags
        :return flags of an item
        """
        # Allow dragging of valid entries but disallow dropping on them while
        # invalid indices are valid drop locations, i.e. in between existing
        # entries.
        if index.isValid():
            return super().flags(index) | \
                    QtCore.Qt.ItemIsSelectable | \
                    QtCore.Qt.ItemIsDragEnabled | \
                    QtCore.Qt.ItemIsEnabled | \
                    QtCore.Qt.ItemNeverHasChildren
        else:
            return QtCore.Qt.ItemIsSelectable | \
                    QtCore.Qt.ItemIsDragEnabled | \
                    QtCore.Qt.ItemIsDropEnabled | \
                    QtCore.Qt.ItemIsEnabled | \
                    QtCore.Qt.ItemNeverHasChildren

    def supportedDropActions(self):
        """Return the drop actions supported by this model.

        :return Drop actions supported by this model
        """
        return QtCore.Qt.MoveAction

    def get_entry(self, index):
        """Returns the action entry at the given index.

        :param index the index of the entry to return
        :return entry stored at the given index
        """
        if not 0 <= index < len(self._data):
            syslog.error(
                "Attempted to retrieve macro entry at invalid index"
            )
            return None
        return self._data[index]

    def set_entry(self, entry, index):
        """Sets the entry at the given index to the given value.

        :param entry the new entry object to store
        :param index the index at which to store the entry
        """
        from functools import partial
        if not 0 <= index < len(self._data):
            syslog.error(
                "Attempted to set an entry with index greater "
                "then number of elements"
            )
            return

        if index in self._data:
            old_entry = self._data[index]
            old_entry.changed.disconnect(self._data_changed)
        self._data[index] = entry
        entry.changed.connect(partial(self._data_changed, index, entry))

    def _data_changed(self, index, entry):
        # changed # dataChanged(QModelIndex,QModelIndex,QList<int>); dataChanged(QModelIndex,QModelIndex)
        qindex = self.createIndex(index,0, index)
        self.dataChanged.emit(qindex, qindex)



    def remove_entry(self, index):
        """Removes the entry at the provided index.

        If the index is invalid nothing happens.

        :param index the index of the entry to remove
        """
        if 0 <= index < len(self._data):
            self.beginRemoveRows(self.index(0, 0), index, index)
            del self._data[index]
            self.endRemoveRows()
    
    def add_entry(self, index, entry):
        """Adds the given entry at the provided index.

        :param index the index at which to insert the new entry
        :param entry the entry to insert
        """
        self.beginInsertRows(QtCore.QModelIndex(), index, index)
        self._data.insert(index + 1, entry)
        self.endInsertRows()

    def swap(self, id1, id2):
        """Swaps the entries pointed to by the two indices.

        If either of the indices is invalid nothing happens.

        :param id1 first index
        :param id2 second index
        """
        if -1 < id1 < len(self._data) and -1 < id2 < len(self._data):
            self._data[id1], self._data[id2] = \
                self._data[id2], self._data[id1]
            self.dataChanged.emit(self.index(id1, 0), self.index(id2, 0))

    def update(self, index):
        """Emits a signal indicating the given index was updated.

        :param index the index which has been updated
        """
        self.dataChanged.emit(index, index)
