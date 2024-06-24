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

import enum
from PySide6 import QtWidgets, QtCore, QtGui
import copy

import gremlin
import gremlin.ui.midi_device
from gremlin.util import load_icon, load_pixmap
from gremlin.input_types import InputType
from gremlin.base_buttons import *
from gremlin.types import DeviceType
import gremlin.util 
import gremlin.config
import gremlin.plugin_manager
from . import ui_activation_condition, ui_common
from functools import partial 
from  gremlin.clipboard import Clipboard
from gremlin.keyboard import Key
from gremlin.util import get_guid
import logging
syslog = logging.getLogger("system")
import qtawesome as qta
import gremlin.ui.input_item 
import gremlin.base_profile 
import gremlin.ui.ui_common

 
from gremlin.ui import virtual_button

class InputIdentifier:

    """Represents the identifier of a single input item."""

    def __init__(self, input_type, input_id, device_type):
        """Creates a new instance.

        :param input_type the type of input
        :param input_id the identifier of the input
        :param device_type the type of device this input belongs to
        """
        self._input_type = input_type
        self._input_id = input_id
        self._device_type = device_type
        self._input_guid = get_guid() # unique internal GUID for this entry

    @property
    def device_type(self):
        return self._device_type

    @property
    def input_type(self):
        return self._input_type

    @property
    def input_id(self):
        return self._input_id
    
    @property
    def guid(self):
        return self._input_guid


class InputItemListModel(ui_common.AbstractModel):

    """Model storing a device's input item list."""



    def __init__(self, device_data, mode, allowed_types = None):
        """Creates a new instance.

        :param device_data the profile data managed by this model
        :param mode the mode this model manages
        """
        super().__init__()
        self._device_data = device_data
        self._mode = mode
        self._index_map = {} # map of index to input item
        if allowed_types is not None:
            self._allowed_input_types  = gremlin.base_classes.TraceableList(allowed_types, self._filter_change_cb)
        else:
            # all types
            self._allowed_input_types = gremlin.base_classes.TraceableList(InputType.to_list(), self._filter_change_cb)
        self._update_data()


    def _filter_change_cb(self):
        ''' occurs when the input filter changes '''
        self._update_data()


    @property
    def allowed_input_types(self):
        ''' input type filter list '''
        return self._allowed_input_types
    

    @property
    def mode(self):
        """Returns the mode handled by this model.

        :return the mode managed by the model
        """
        return self._mode

    @mode.setter
    def mode(self, mode):
        """Sets the mode managed by the model.

        :param mode the mode handled by the model
        """
        self._mode = mode
        self._update_data()
        



    def _update_data(self, emit_change = True):
        ''' loads into the data model all the items for the current mode and device '''
        # load the items for this mode
        
        input_items = self._device_data.modes[self._mode]
        index = 0
        self._index_map = {}
        for input_type in self._allowed_input_types:
            if input_type in input_items.config.keys():
                sorted_keys = sorted(input_items.config[input_type].keys())
                for data_key in sorted_keys:
                    data = input_items.config[input_type][data_key]
                    self._index_map[index] = data
                    index += 1

        if emit_change:
            self.data_changed.emit()                    

    def refresh(self):
        ''' refreshes the mode data without '''
        self._update_data()


    def rows(self):
        """Returns the number of rows in the model.

        :return number of rows in the model
        """

        return len(self._index_map)


    def data(self, index):
        """Returns the data stored at the provided index.

        :param index the index for which to return the data
        :return data stored at the provided index
        """

        if not index in self._index_map.keys():
            # bad index
            logging.getLogger("system").error(f"InputItemListModel: bad index request {index} for mode: {self._mode} device: {self._device_data.name}") 
            return None
        
        return self._index_map[index]

       
            
    def removeRow(self, index):
        ''' removes the item at the specified index '''

        data = self.data(index)
        if data:
            input_type = data.input_type
            if not input_type in (InputType.Keyboard, InputType.KeyboardLatched, InputType.OpenSoundControl, InputType.Midi):
                # cannot remove other types
                return

            input_items = self._device_data.modes[self._mode]  
            sorted_keys = sorted(input_items.config[input_type].keys())           
            item_index = sorted_keys[index]
            del input_items.config[input_type][item_index]
            # refresh the data post delete
            self._update_data()

    
    def action_id_to_index(self, action_id):
        ''' get the model index containing the action id'''
        
        if action_id:
            # find the row by action_id
            for index in range(self.rows()):
                data = self.data(index)
                for container in data.containers:
                    for action_list in container.action_sets:
                        for action_data in action_list:
                            if action_data.action_id == action_id:
                                return index

        # not found       
        return -1

    def event_to_index(self, event):
        """Converts an event to a model index.

        :param event the event to convert
        :return index corresponding to the event's input
        """

        input_items = self._device_data.modes[self._mode]

        
        offset_map = dict()
        offset_map[InputType.Keyboard] = 0
        offset_map[InputType.JoystickAxis] =\
            len(input_items.config[InputType.Keyboard])
        offset_map[InputType.JoystickButton] = \
            offset_map[InputType.JoystickAxis] + \
            len(input_items.config[InputType.JoystickAxis])
        offset_map[InputType.JoystickHat] = \
            offset_map[InputType.JoystickButton] + \
            len(input_items.config[InputType.JoystickButton]) 
        offset_map[InputType.KeyboardLatched] = \
            offset_map[InputType.JoystickHat] + \
            len(input_items.config[InputType.JoystickHat])
        offset_map[InputType.OpenSoundControl] = \
            offset_map[InputType.KeyboardLatched] + \
            len(input_items.config[InputType.KeyboardLatched
            ])
        offset_map[InputType.Midi] = \
            offset_map[InputType.OpenSoundControl] + \
            len(input_items.config[InputType.OpenSoundControl
            ])
            
        

        if event.event_type == InputType.JoystickAxis:
            # Generate a mapping from axis index to linear axis index
            axis_index_to_linear_index = {}
            axis_keys = sorted(input_items.config[InputType.JoystickAxis].keys())
            for l_idx, a_idx in enumerate(axis_keys):
                axis_index_to_linear_index[a_idx] = l_idx

            return offset_map[event.event_type] + \
                   axis_index_to_linear_index[event.identifier]
        else:
            return offset_map[event.event_type] + event.identifier - 1
        
    def clear(self):
        ''' removes all input items for keyboard items data if keyboard 
            only keyboard inputs can be removed
        
        '''
        input_items = self._device_data.modes[self._mode]
        if InputType.Keyboard in input_items.config:
            input_items.config[InputType.Keyboard].clear()
        if InputType.KeyboardLatched in input_items.config:
            input_items.config[InputType.KeyboardLatched].clear()


class InputItemListView(ui_common.AbstractView):

    """View displaying the contents of an InputItemListModel."""

    # fires when the list view is redrawn
    updated = QtCore.Signal()

    # Conversion from input type to a display name
    type_to_string = {
        InputType.JoystickAxis: "Axis",
        InputType.JoystickButton: "Button",
        InputType.JoystickHat: "Hat",
        InputType.Keyboard: "",
        InputType.KeyboardLatched: "(latched)",
        InputType.OpenSoundControl: "OSC",
        InputType.Midi: "Midi"
    }

    def __init__(self, parent=None, name = "Not set", custom_widget_handler = None):
        """Creates a new input item view instance 

        :param parent the parent of the widget
        :name name of the list
        :custom_widget_handler handler to create a widget when needed - signature callback(index, data) -> widget
        """
        super().__init__(parent)

        # default visible supported input types
        self.shown_input_types = [
            InputType.JoystickAxis,
            InputType.JoystickButton,
            InputType.JoystickHat,
            InputType.Keyboard,
            InputType.KeyboardLatched,
            InputType.OpenSoundControl,
            InputType.Midi
        ]
        self.name = name
        self.current_index = None
        self.custom_widget_handler = custom_widget_handler

        # Create required UI items
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()

        # Configure the widget holding the layout with all the buttons
        self.scroll_widget.setLayout(self.scroll_layout)

        # Configure the scroll area
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)


        # Add the scroll area to the main layout
        self.main_layout.addWidget(self.scroll_area)

        el = gremlin.event_handler.EventListener()
        el.profile_device_mapping_changed.connect(self._profile_device_mapping_changed)

    @property
    def current_index(self):
        return self._current_index
    @current_index.setter
    def current_index(self, value):
        self._current_index = value

    @property
    def current_device(self):
        ''' gets the device associated with this list view '''
        return self.model._device_data


    def _profile_device_mapping_changed(self, event):
        if not event.device_guid:
            return
        for index in range(self.model.rows()):
            data = self.model.data(index)
            if data.input_type not in self.shown_input_types:
                continue
            if data.input_type != event.device_input_type:
                continue
            if data.input_id != event.device_input_id:
                continue
            self.redraw_index(index)



    def limit_input_types(self, types):
        """Limits the items shown to the given types.

        :param types list of input types to display
        """
        self.shown_input_types = types
        self.redraw()

    def redraw(self):
        """Redraws the entire model.
        
        This creates a fake listview where a vertical container just has InputItemButton widgets
        
        """
        verbose = gremlin.config.Configuration().verbose
        ui_common.clear_layout(self.scroll_layout)

        if self.model is None:
            return
        
        row_count = self.model.rows()
        device_name = self.current_device.name
        #if self.current_device.name == "keyboard":
        if self._current_index is None and row_count > 0:
            # select the first item by default
            self._current_index = 0


        for index in range(row_count):
            data = self.model.data(index)

            identifier = InputIdentifier(
                data.input_type,
                data.input_id,
                data.parent.parent.type
            )

            if self.custom_widget_handler:
                widget = self.custom_widget_handler(self, index, identifier, data)
                assert widget is not None, "Custom widget handler didn't return a widget"
            else:
                widget = InputItemWidget(identifier)
                if identifier.input_type == InputType.JoystickAxis:
                    widget.setIcon("joystick_no_frame.png",use_qta=False)
                elif identifier.input_type == InputType.JoystickButton:
                    widget.setIcon("mdi.gesture-tap-button")
                elif identifier.input_type == InputType.JoystickHat:
                    widget.setIcon("ei.fullscreen")
                widget.create_action_icons(data)
                widget.update_description(data.description)

            # hook the widget
            
            widget.selected_changed.connect(self._create_selection_callback(index))
            widget.edit.connect(self._create_edit_callback(index))
            widget.closed.connect(self._create_closed_callback(index))
                

            widget.selected = index == self._current_index                    
            
            #logging.getLogger("system").info(f"create widget: index {index} selected: {widget.selected}")                 
            self.scroll_layout.addWidget(widget)
            if verbose:
                logging.getLogger("system").info(f"LV: {device_name} [{index:02d}] type: {InputType.to_string(data.input_type)} name: {data.input_id}")
        self.scroll_layout.addStretch()

        self.updated.emit()
        


    def redraw_index(self, index):
        """Redraws the view entry at the given index.

        :param index the index of the entry to redraw
        """
        if self.model is None:
            return
        

        # logging.getLogger("system").info(f"redraw_index: {index}") 

        data = self.model.data(index)
        item = self.scroll_layout.itemAt(index)
        if item is not None:
            widget = self.scroll_layout.itemAt(index).widget()
            if widget is not None:
                widget.create_action_icons(data)
                widget.update_description(data.description)

    def _create_selection_callback(self, index):
        """Creates a callback handling the selection of items.

        :param index the index of the item to create the callback for
        :return callback to be triggered when the item at the provided index
            is selected
        """
        return lambda x: self.select_item(index)
    

    def _create_edit_callback(self, index):
        """Creates a callback handling the edit action of an input widget

        :param index the index of the item to create the callback for
        :return callback to be triggered when the item at the provided index
            is selected
        """
        return lambda x: self._edit_item_cb(index)
    
    
    def _create_closed_callback(self, index):
        """Creates a callback handling the close action of an input widget

        :param index the index of the item to create the callback for
        :return callback to be triggered when the item at the provided index
            is selected
        """
        return lambda x: self._close_item_cb(index)



    def select_input(self, input_type, identifier):
        ''' selects an entry based on input type and ID'''
        for index in range(self.model.rows()):
            data = self.model.data(index)
            if data.input_type != input_type:
                continue
            if data.input_id == identifier:
                self.select_item(index)
                return
            
    def selected_item(self):
        ''' returns the currently selected input in the list view '''
        
        index = self.current_index
        if not index:
            return None
        
        return self.model.data(index)
    
    def _close_item_cb(self, index):
        ''' remove a particular input '''

        # select the widget if it's not selected
        data = self.model.data(index)
        if data and data.containers:
            # prompt confirm
            message_box = QtWidgets.QMessageBox()
            message_box.setText("Delete confirmation")
            message_box.setInformativeText("This will delete associated actions for this entry.\nAre you sure?")
            pixmap = load_pixmap("warning.svg")
            pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio) 
            message_box.setIconPixmap(pixmap)
            message_box.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Ok |
                QtWidgets.QMessageBox.StandardButton.Cancel
                )
            message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
            result = message_box.exec()
            if result == QtWidgets.QMessageBox.StandardButton.Ok:
                self._confirmed_close(index)

    
    def _confirmed_close(self, index):
        self.model.removeRow(index)
        self.redraw()
        
    
    def _edit_item_cb(self, index):
        ''' emits the edit event along with the item being edited '''
        self.item_edit.emit(self, index, self.model.data(index).input_id) # widget, index, data

    def _closed_item_cb(self):
        ''' emits the edit event along with the item is closed '''
        index = self.current_index
        if not index:
            return None
        self.item_closed.emit(self, index, self.model.data(index)) # widget, index, data

    


    def select_item(self, index, emit_signal=True):
        """Handles selecting a specific item.  this is called whenever an input item is selected

        :param index the index of the item being selected
        :param emit_signal flag indicating whether or not a signal is to be
            emitted when the item is being selected
        """
        # If the index is actually an event we have to correctly translate the
        # event into an index, taking the possible non-contiguous nature of
        # axes into account
        if isinstance(index, gremlin.event_handler.Event):
            event = index
            if event.action_id:
                index = self.mode.action_id_to_index(event.action_id)
            else:
                index = self.model.event_to_index(event)

        if self.current_index != index:
            self.current_index = index

            # Go through all entries in the layout, deselecting those that are
            # actual widgets and selecting the previously selected one
            valid_index = False
            # height = 0
            for i in range(self.scroll_layout.count()):
                item = self.scroll_layout.itemAt(i)
                if item.widget():
                    widget = item.widget()
                    if i == index:
                        widget.selected = True
                        valid_index = True

                        # self.scroll_area.ensureVisible(x,height)
                        QtCore.QTimer.singleShot(0, partial(self.scroll_area.ensureWidgetVisible, widget))

                        # signal the hardware input device changed
                        el = gremlin.event_handler.EventListener()
                        event = gremlin.event_handler.DeviceChangeEvent()
                        data = self.model.data(index)
                        event.device_guid = self.model._device_data.device_guid
                        event.device_name = self.model._device_data.name
                        event.device_input_type = data.input_type if data else None
                        event.device_input_id = data.input_id if data else None
                        el.profile_device_changed.emit(event)
                    else:
                        # deselect unselected
                        if widget.selected:
                            widget.selected = False
                        

            if emit_signal and valid_index:
                self.item_selected.emit(index)

        # return the currently selected widget

        item = self.scroll_layout.itemAt(index)
        return item.widget
            
                


class ActionSetModel(ui_common.AbstractModel):

    """Model storing a set of actions."""

    def __init__(self, action_set=[]):
        super().__init__()
        assert isinstance(action_set, list),"Invalid action set provided"
        self._action_set = action_set

    def rows(self):
        return len(self._action_set)

    def data(self, index):
        return self._action_set[index]

    def add_action(self, action):
        self._action_set.append(action)
        self.data_changed.emit()

    def remove_action(self, action):
        if action in self._action_set:
            del self._action_set[self._action_set.index(action)]
        self.data_changed.emit()


class ActionSetView(ui_common.AbstractView):

    """View displaying the action set content."""

    class Interactions(enum.Enum):
        """Enumeration of possible interactions."""
        Up = 1
        Down = 2
        Delete = 3
        Edit = 4
        Add = 5
        Count = 6
        Copy = 7 # copy to clipboard

    # Signal emitted when an interaction is triggered on an action
    interacted = QtCore.Signal(Interactions)

    def __init__(
            self,
            profile_data,
            label,
            view_type=ui_common.ContainerViewTypes.Action,
            parent=None
    ):
        
        super().__init__(parent)
        self.view_type = view_type
        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.profile_data = profile_data
        self.allowed_interactions = profile_data.interaction_types
        self.label = label

        # Create a group box widget in which everything else will be placed
        self.group_widget = QtWidgets.QGroupBox(self.label)
        self.main_layout.addWidget(self.group_widget)

        # Create group box contents
        self.group_layout = QtWidgets.QGridLayout()
        self.group_widget.setLayout(self.group_layout)
        self.action_layout = QtWidgets.QVBoxLayout()

        # Only show edit controls in the basic tab
        if self.view_type == ui_common.ContainerViewTypes.Action:
            self._create_edit_controls()
            self.group_layout.addLayout(self.action_layout, 0, 0)
            self.group_layout.addLayout(self.controls_layout, 0, 1)
        else:
            self.group_layout.addLayout(self.action_layout, 0, 0)
        self.group_layout.setColumnStretch(0, 2)

        # Only permit adding actions from the basic tab and if the tab is
        # not associated with a vJoy device
        if self.view_type == ui_common.ContainerViewTypes.Action and \
                self.profile_data.get_device_type() != DeviceType.VJoy:
            self.action_selector = gremlin.ui.ui_common.ActionSelector(
                profile_data.parent.input_type
            )
            self.action_selector.action_added.connect(self._add_action)
            self.action_selector.action_paste.connect(self._paste_action)
            self.group_layout.addWidget(self.action_selector, 1, 0)

    

    def redraw(self):
        ui_common.clear_layout(self.action_layout)

        if self.model is None:
            return

        clipboard = Clipboard()
        clipboard.disable()
        if self.view_type == ui_common.ContainerViewTypes.Action:
            for index in range(self.model.rows()):
                data = self.model.data(index)
                widget = data.widget(data)
                widget.action_modified.connect(self.model.data_changed.emit)
                wrapped_widget = BasicActionWrapper(widget)
                wrapped_widget.closed.connect(self._create_closed_cb(widget))
                self.action_layout.addWidget(wrapped_widget)
        elif self.view_type == ui_common.ContainerViewTypes.Condition:
            for index in range(self.model.rows()):
                data = self.model.data(index)
                widget = data.widget(data)
                widget.action_modified.connect(self.model.data_changed.emit)
                wrapped_widget = ConditionActionWrapper(widget)
                self.action_layout.addWidget(wrapped_widget)

        clipboard.enable()

    def _add_action(self, action_name):
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.profile_data)
        self.model.add_action(action_item)

    def _paste_action(self, action):
        ''' handles action paste operation '''
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action)
        self.model.add_action(action_item)
        

    def _create_closed_cb(self, widget):
        """Create callbacks to remove individual containers from the model.

        :param widget the container widget to be removed
        :return callback function to remove the provided widget from the
            model
        """
        return lambda: self.model.remove_action(widget.action_data)
    

    def _create_edit_controls(self):
        """Creates interaction controls based on the allowed interactions.

        :param allowed_interactions list of allowed interactions
        """
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColorConstants.Red)

        self.controls_layout = QtWidgets.QVBoxLayout()
        if ActionSetView.Interactions.Up in self.allowed_interactions:
            self.control_move_up = QtWidgets.QPushButton(
                load_icon("gfx/button_up"), ""
            )
            self.control_move_up.clicked.connect(
                lambda: self.interacted.emit(ActionSetView.Interactions.Up)
            )
            self.controls_layout.addWidget(self.control_move_up)
        if ActionSetView.Interactions.Down in self.allowed_interactions:
            self.control_move_down = QtWidgets.QPushButton(
                load_icon("gfx/button_down"), ""
            )
            self.control_move_down.clicked.connect(
                lambda: self.interacted.emit(ActionSetView.Interactions.Down)
            )
            self.controls_layout.addWidget(self.control_move_down)
        if ActionSetView.Interactions.Delete in self.allowed_interactions:
            self.control_delete = QtWidgets.QPushButton(
                load_icon("gfx/button_delete"), ""
            )
            logging.getLogger("system").info(f"action: delete allowed")
            self.control_delete.clicked.connect(
                lambda: self.interacted.emit(ActionSetView.Interactions.Delete)
            )
            self.controls_layout.addWidget(self.control_delete)
        if ActionSetView.Interactions.Edit in self.allowed_interactions:
            self.control_edit = QtWidgets.QPushButton(
                load_icon("gfx/button_edit"), ""
            )
            self.control_edit.clicked.connect(
                lambda: self.interacted.emit(ActionSetView.Interactions.Edit)
            )
            self.controls_layout.addWidget(self.control_edit)
        if ActionSetView.Interactions.Copy in self.allowed_interactions:
            self.control_edit = QtWidgets.QPushButton(
                load_icon("gfx/button_copy"), ""
            )
            self.control_edit.clicked.connect(
                lambda: self.interacted.emit(ActionSetView.Interactions.Copy)
            )
            self.controls_layout.addWidget(self.control_edit)
        

        self.controls_layout.addStretch(1)


class InputItemWidget(QtWidgets.QFrame):

    """Creates a button like widget which emits an event when pressed.

    this widget is used to represent an input mapping

    This event can be used to display input item specific customization
    widgets. This button also shows icons of the associated actions.
    """

    # Signal emitted whenever this button is pressed
    selected_changed = QtCore.Signal(InputIdentifier)

    # signal when button's close button is pressed
    closed =  QtCore.Signal(InputIdentifier)

    # signal when button's edit button is pressed
    edit =  QtCore.Signal(InputIdentifier)


    def __init__(self, identifier, parent=None, populate_ui = None, populate_name = None, config_external = False):
        """Creates a new instance.

        :param identifier identifying information about the button
        :param parent the parent widget
        :param populate_ui  handler to custom input button content - this is created on a second row if it exists - signature populate_ui(inputbutton, container_widget)
        :param populate_name handler to custom display name - signature populate_name(identifier)
        """
        QtWidgets.QFrame.__init__(self, parent)

        self.container_widget = QtWidgets.QWidget(self)
        self.container_layout = QtWidgets.QGridLayout()

        self.container_widget.setLayout(self.container_layout)

        self.identifier = identifier
        self._selected = False
        
        self.populate_name = populate_name # callback to populate the name
        self._config_external = config_external # true if the widget is a custom widget configured externally

        
        self._title_widget = gremlin.ui.ui_common.QIconLabel()
        self._title_widget.setText("Input Not configured")
        self._title_widget.setObjectName("title")
        self._description_widget = QtWidgets.QLabel()
        self._description_widget.setObjectName("description")

        # line 2 input description - only displayed in multirow custom inputs
        self._input_description_widget = QtWidgets.QLabel()
        self._input_description_widget.setObjectName("input_description")
        self._input_description_widget.setStyleSheet("padding-left: 10px;")
        self._icon_layout = QtWidgets.QHBoxLayout()
        self._icons = []

        # top row 
        self._multi_row = populate_ui is not None
        self.populate_ui = populate_ui
            
        data_row = 1 if self._multi_row else 0 

        self.setFrameShape(QtWidgets.QFrame.Box)


        # background label to fix QT6 draw order - occupise the entire space
        self.label_selected = QtWidgets.QLabel()
        self.container_layout.addWidget(self.label_selected, 0, 0, -1, -1)
        self.label_selected.setMinimumHeight(30)

        # main container 

        self.container_layout.addWidget(QtWidgets.QLabel(" "), data_row, 0)
        self.container_layout.addWidget(self._title_widget, data_row, 1)
        self.container_layout.addWidget(self._description_widget, data_row, 2)
        self.container_layout.addLayout(self._icon_layout, data_row, 3)

        self._edit_button_widget = QtWidgets.QPushButton(qta.icon("fa.gear"),"")
        self._edit_button_widget.setToolTip("Configure")
        self._edit_button_widget.setFixedSize(24,16)
        self._edit_button_widget.clicked.connect(self._edit_button_cb)
        self._edit_button_widget.setVisible(False) # not visible by default
        self.container_layout.addWidget(self._edit_button_widget, data_row, 4)

        self._close_button_widget = QtWidgets.QPushButton(qta.icon("mdi.delete"),"")
        self._close_button_widget.setFixedSize(16,16)
        self._close_button_widget.clicked.connect(self._close_button_cb)
        self._close_button_widget.setVisible(False) # not visible by default


        self.container_layout.addWidget(self._close_button_widget, data_row, 5)
        self.container_layout.addWidget(QtWidgets.QLabel(" "), data_row, 6)

        if self._multi_row:

            self.container_layout.addWidget(QtWidgets.QWidget(), 0, 0, 1, -1) # top row margine
            self.custom_container_widget = QtWidgets.QWidget()
            self.container_layout.addWidget(self._input_description_widget, data_row + 1, 0, 1, -1 )
            self.container_layout.addWidget(self.custom_container_widget, data_row + 2, 0, -1, -1)
            self.populate_ui(self, self.custom_container_widget)


        #self.container_layout.setColumnMinimumWidth(0, 50)
        self.setMinimumWidth(300)

        self.main_layout = QtWidgets.QHBoxLayout()
        self.main_layout.setContentsMargins(0,0,0,0)
        self.setContentsMargins(2,2,2,2)
        self.setLayout(self.main_layout)
        self.main_layout.addWidget(self.container_widget)

        self.update_display()

    @property
    def config_external(self):
        return self._config_external
    
    @config_external.setter
    def config_external(self, value):
        self._config_external = value

    def setTitle(self, value):
        ''' sets the title of the input widget '''
        self._title_widget.setText(value)

    def setDescription(self, value):
        ''' sets the description of the input widget '''
        self._input_description_widget.setText(value)
    
    def setToolTip(self, tooltip):
        ''' sets the tooltip for the widget '''
        super().setToolTip(tooltip)
    

    def update_display(self):
        ''' updates the display text for the button '''
        if not self._config_external:
            display_text = self.populate_name(self, self.identifier) if self.populate_name else gremlin.common.input_to_ui_string( self.identifier.input_type,self.identifier.input_id)
            self._title_widget.setText(display_text)

    @property
    def selected(self) -> bool:
        return self._selected
    
    @selected.setter
    def selected(self, value):
        if value != self._selected:
            self._selected = value
            if value:
                style = "background-color:  #8FBC8F; border-width: 6px; border-color: #8FBC8F;" 
            else:
                style = "background-color: #E8E8E8; border-width: 6px; ; border-color: #E8E8E8;" 
            
            self.label_selected.setStyleSheet(style)   
            

    def setIcon(self, icon_path, use_qta = True):
        ''' sets the widget's icon '''
        self._title_widget.setIcon(icon_path, use_qta)

    def enable_close(self):
        ''' enables the close button on the input widget (keyboard only usually) '''
        self._close_button_widget.setVisible(True)

    def disable_close(self):
        ''' enables the close button on the input widget (keyboard only usually) '''
        self._close_button_widget.setVisible(False)        


    def enable_edit(self):
        ''' enables the edit button on the input widget (keyboard only usually) '''
        self._edit_button_widget.setVisible(True)

    def disable_edit(self):
        ''' enables the edit button on the input widget (keyboard only usually) '''
        self._edit_button_widget.setVisible(False)

                

    def update_description(self, description):
        """Updates the description of the button.

        :param description the description to use
        """
        self._description_widget.setText(f"<i>{description}</i>")

    def create_action_icons(self, profile_data):
        """Creates the label of this instance.

        Renders the text representing the instance's name as well as
        icons of actions associated with it.

        :param profile_data the profile.InputItem object associated
            with this instance
        """
        ui_common.clear_layout(self._icon_layout)

        # Create the actual icons
        # FIXME: this currently ignores the containers themselves
        self._icon_layout.addStretch(1)
        for container in profile_data.containers:
            for actions in [a for a in container.action_sets if a is not None]:
                for action in actions:
                    if action is not None:
                        self._icon_layout.addWidget(ActionLabel(action))

    def mousePressEvent(self, event):
        """Emits the input_item_changed event when this instance is
        clicked on by the mouse.

        :param event the mouse event
        """
        self.selected_changed.emit(self.identifier)

    def _close_button_cb(self):
        ''' fires the closed event when the close button has been pressed '''
        self.closed.emit(self.identifier)

    def _edit_button_cb(self):
        ''' edit button clicked '''
        self.edit.emit(self.identifier)


class ActionLabel(QtWidgets.QLabel):

    """Handles showing the correct icon for the given action."""

    def __init__(self, action_entry, parent=None):
        """Creates a new label for the given entry.

        :param action_entry the entry to create the label for
        :param parent the parent
        """
        QtWidgets.QLabel.__init__(self, parent)
        icon = action_entry.icon()
        if isinstance(icon, QtGui.QIcon):
            self.setPixmap(QtGui.QPixmap(icon.pixmap(20)))
        else:
            self.setPixmap(QtGui.QPixmap(icon))

        self.action_entry = action_entry

        el = gremlin.event_handler.EventListener()
        el.icon_changed.connect(self._icon_change)

    def _icon_change(self, event):
        icon = self.action_entry.icon()
        if isinstance(icon, QtGui.QIcon):
            self.setPixmap(QtGui.QPixmap(icon.pixmap(20)))
        else:
            self.setPixmap(QtGui.QPixmap(icon))


class ContainerSelector(QtWidgets.QWidget):

    """Allows the selection of a container type."""

    # Signal emitted when a container type is selected
    container_added = QtCore.Signal(str)
    container_paste = QtCore.Signal(object)

    def __init__(self, input_type, parent=None):
        """Creates a new selector instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.input_type = input_type

        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.addWidget(QtWidgets.QLabel("Container"))

        self.container_dropdown = QtWidgets.QComboBox()
        for name in self._valid_container_list():
            self.container_dropdown.addItem(name)
        self.add_button = QtWidgets.QPushButton("Add")
        self.add_button.clicked.connect(self._add_container)

        # clipboard
        self.paste_button = QtWidgets.QPushButton()
        icon = gremlin.util.load_icon("button_paste.svg")
        self.paste_button.setIcon(icon)
        self.paste_button.clicked.connect(self._paste_container)
        self.paste_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Minimum)
        self.paste_button.setToolTip("Paste container")

        clipboard = Clipboard()
        clipboard.clipboard_changed.connect(self._clipboard_changed)
        self._clipboard_changed(clipboard)
                

        self.main_layout.addWidget(self.container_dropdown)
        self.main_layout.addWidget(self.add_button)
        self.main_layout.addWidget(self.paste_button)
        

    def _valid_container_list(self):
        """Returns a list of valid actions for this InputItemWidget.

        :return list of valid action names
        """
        container_list = []
        for entry in gremlin.plugin_manager.ContainerPlugins().repository.values():
            if self.input_type in entry.input_types:
                container_list.append(entry.name)
        return sorted(container_list)

    def _add_container(self, clicked=False):
        """Handles add button events.

        :param clicked flag indicating whether or not the button was pressed
        """
        self.container_added.emit(self.container_dropdown.currentText())


    def _clipboard_changed(self, clipboard):
        ''' handles paste button state based on clipboard data '''
        self.paste_button.setEnabled(clipboard.is_container)    
        ''' updates the paste button tooltip with the current clipboard contents'''
        if clipboard.is_container:
            self.paste_button.setToolTip(f"Paste container ({clipboard.data.name})")
        else:
            self.paste_button.setToolTip(f"Paste container (not available)") 

    def _paste_container(self):
        ''' handle paste containern '''
        clipboard = Clipboard()
        # validate the clipboard data is an action and is of the correct type for the input/container
        if clipboard.is_container:
            container_name = clipboard.data.name
            if container_name in self._valid_container_list():
                # valid container - and add it
                # logging.getLogger("system").info("Clipboard paste action trigger...")
                self.container_paste.emit(clipboard.data)
            else:
                # dish out a message
                message_box = QtWidgets.QMessageBox(
                    QtWidgets.QSystemTrayIcon.MessageIcon.Warning,
                    f"Invalid container type ({container_name})",
                    "Unable to paste container because it is not valid for the current input")
                message_box.showNormal()


class AbstractContainerWidget(QtWidgets.QDockWidget):

    """Base class for container widgets."""

    # Signal which is emitted whenever the widget is closed
    closed = QtCore.Signal(QtWidgets.QWidget)

    # Signal which is emitted whenever the widget's contents change as well as
    # the UI tab that was active when the event was emitted
    container_modified = QtCore.Signal()

    # Palette used to render widgets
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColorConstants.LightGray)

    # Maps virtual button data to virtual button widgets
    virtual_axis_to_widget = {
        VirtualAxisButton: virtual_button.VirtualAxisButtonWidget,
        VirtualHatButton: virtual_button.VirtualHatButtonWidget
    }

    def __init__(self, profile_data, parent=None):
        """Creates a new container widget object.

        :param profile_data the data the container handles
        :param parent the parent of the widget
        """
        assert isinstance(profile_data, gremlin.base_profile.AbstractContainer)
        super().__init__(parent)
        self.profile_data = profile_data
        self.action_widgets = []

        self.setTitleBarWidget(TitleBar(
            self._get_window_title(),
            gremlin.hints.hint.get(self.profile_data.tag, ""),
            self._container_remove,
            self._container_copy,
        ))

        # Create tab widget to display various UI controls in
        self.dock_tabs = QtWidgets.QTabWidget()
        self.dock_tabs.setTabPosition(QtWidgets.QTabWidget.East)
        self.setWidget(self.dock_tabs)

        # Create the individual tabs
        self._create_action_tab()
        if self.profile_data.get_device_type() != DeviceType.VJoy:
            if self.profile_data.condition_enabled:
                self._create_activation_condition_tab()
            if self.profile_data.virtual_button_enabled:
                self._create_virtual_button_tab()

        self.dock_tabs.currentChanged.connect(self._tab_changed)

        # Select appropriate tab
        self._select_tab(self.profile_data.current_view_type)

    def _create_action_tab(self):
        # Create root widget of the dock element
        self.action_tab_widget = QtWidgets.QWidget()

        # Create layout and place it inside the dock widget
        self.action_layout = QtWidgets.QVBoxLayout(self.action_tab_widget)

        # Create the actual UI
        self.dock_tabs.addTab(self.action_tab_widget, "Action")
        self._create_action_ui()
        self.action_layout.addStretch(10)

    def _create_activation_condition_tab(self):
        # Create widget to place inside the tab
        self.activation_condition_tab_widget = QtWidgets.QWidget()
        self.activation_condition_layout = QtWidgets.QVBoxLayout(
            self.activation_condition_tab_widget
        )

        # Create activation condition UI widget
        self.activation_condition_widget = \
            ui_activation_condition.ActivationConditionWidget(self.profile_data)
        self.activation_condition_widget.activation_condition_modified.connect(
            self.container_modified.emit
        )

        # Put everything together
        self.activation_condition_layout.addWidget(
            self.activation_condition_widget
        )
        self.dock_tabs.addTab(
            self.activation_condition_tab_widget,
            "Condition"
        )

        self._create_condition_ui()
        self.activation_condition_layout.addStretch(10)

    def _create_virtual_button_tab(self):
        # Return if nothing is to be done
        if not self.profile_data.virtual_button:
            return

        # Create widget to place inside the tab
        self.virtual_button_tab_widget = QtWidgets.QWidget()
        self.virtual_button_layout = QtWidgets.QVBoxLayout(
            self.virtual_button_tab_widget
        )

        # Create actual virtual button UI
        self.virtual_button_widget = \
            AbstractContainerWidget.virtual_axis_to_widget[
                type(self.profile_data.virtual_button)
            ](self.profile_data.virtual_button)

        # Put everything together
        self.virtual_button_layout.addWidget(self.virtual_button_widget)
        self.dock_tabs.addTab(self.virtual_button_tab_widget, "Virtual Button")
        self.virtual_button_layout.addStretch(10)

    def _select_tab(self, view_type):
        if view_type is None:
            return

        try:
            tab_title = ui_common.ContainerViewTypes.to_string(view_type).title()
            for i in range(self.dock_tabs.count()):
                if self.dock_tabs.tabText(i) == tab_title:
                    self.dock_tabs.setCurrentIndex(i)
        except gremlin.error.GremlinError:
            return

    def _tab_changed(self, index):
        ''' called when a device tab is selected '''
        verbose = gremlin.config.Configuration().verbose
        try:
            if verbose:
                   logging.getLogger("system").info(f"Device change begin") 
            tab_text = self.dock_tabs.tabText(index)
            self.profile_data.current_view_type = ui_common.ContainerViewTypes.to_enum(tab_text.lower())
        except gremlin.error.GremlinError:
            return
        finally:
            if verbose:
                   logging.getLogger("system").info(f"Device change end") 

    def _get_widget_index(self, widget):
        """Returns the index of the provided widget.

        :param widget the widget for which to return the index
        :return the index of the provided widget, -1 if not present
        """
        index = -1
        for i, entry in enumerate(self.action_widgets):
            if entry == widget:
                index = i
        return index

    def _create_action_set_widget(self, action_set_data, label, view_type):
        """Adds an action widget to the container.

        :param action_set_data data of the actions which form the action set
        :param label the label to show in the title
        :param view_type visualization type
        :return wrapped widget
        """
        action_set_model = ActionSetModel(action_set_data)
        action_set_view = ActionSetView(
            self.profile_data,
            label,
            view_type
        )
        action_set_view.set_model(action_set_model)
        action_set_view.interacted.connect(
            lambda x: self._handle_interaction(action_set_view, x)
        )

        # Store the view widget so we can use it for interactions later on
        self.action_widgets.append(action_set_view)

        return action_set_view

    def _container_remove(self, _):
        """Emits the closed event when this widget is being closed."""
        self.closed.emit(self)

    def _container_copy(self, _):
        """Emits the copy clipboard when the widget is being copied """

        clipboard = Clipboard()
        clipboard.data = self.profile_data
        logging.getLogger("system").info(f"container {self.profile_data.name} copied to clipboard")

    def _handle_interaction(self, widget, action):
        """Handles interaction with widgets inside the container.

        :param widget the widget on which the interaction is being carried out
        :param action the action being applied
        """
        raise gremlin.error.MissingImplementationError(
            "AbstractContainerWidget._handle_interaction not "
            "implemented in subclass"
        )

    def _create_action_ui(self):
        """Creates the UI elements for the widget."""
        raise gremlin.error.MissingImplementationError(
            "AbstractContainerWidget._create_basic_ui not "
            "implemented in subclass"
        )

    def _create_condition_ui(self):
        """Creates the UI elements for the widget."""
        raise gremlin.error.MissingImplementationError(
            "AbstractContainerWidget._create_condition_ui not "
            "implemented in subclass"
        )

    def _get_window_title(self):
        """Returns the title to show on the widget."""
        return self.profile_data.name


class AbstractActionWidget(QtWidgets.QFrame):

    """Base class for all widgets representing actions from the profile
    module."""

    # Signal which is emitted whenever the widget's contents change
    action_modified = QtCore.Signal()

    def __init__(
            self,
            action_data,
            layout_type=QtWidgets.QVBoxLayout,
            parent=None
    ):
        """Creates a new instance.

        :param action_data the sub-classed AbstractAction instance
            associated with this specific action.
        :param layout_type type of layout to use for the widget
        :param parent parent widget
        """
        QtWidgets.QFrame.__init__(self, parent)

        self.action_data = action_data

        self.main_layout = layout_type(self)

        self._create_ui()
        self._populate_ui()

    def _create_ui(self):
        """Creates all the elements necessary for the widget."""
        raise gremlin.error.MissingImplementationError(
            "AbstractActionWidget._create_ui not implemented in subclass"
        )

    def _populate_ui(self):
        """Updates this widget's representation based on the provided
        AbstractAction instance.
        """
        raise gremlin.error.MissingImplementationError(
            "ActionWidget._populate_ui not implemented in subclass"
        )

    def _get_input_type(self):
        """Returns the input type this widget's action is associated with.
        
        :return InputType corresponding to this action
        """
        return self.action_data.parent.parent.input_type
        # if input_type == InputType.Midi:
        #     # change input type based on midi mode so action configures itself correctly for the type of input that will be sent
        #     input_item = self.action_data.parent.parent.input_id
        #     if input_item.mode == gremlin.ui.midi_device.MidiInputItem.InputMode.Axis:
        #         return InputType.JoystickAxis
        # return input_type

    def _get_profile_root(self):
        """Returns the root of the entire profile.
        
        :return root Profile instance
        """
        root = self.action_data
        while not isinstance(root, gremlin.profile.Profile):
            root = root.parent
        return root


class AbstractActionWrapper(QtWidgets.QDockWidget):

    """Base class for all action widget wrappers.

    The specializations of this class will be used to contain an action
    widget while rendering the UI components needed for a specific view.
    """

    def __init__(self, action_widget, parent=None):
        """Wrapes a widget inside a docking container.

        :param action_widget the action widget to wrap
        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.action_widget = action_widget

        # Create widget sitting in the root of the dock element
        self.dock_widget = QtWidgets.QFrame()
        self.dock_widget.setFrameShape(QtWidgets.QFrame.Box)
        self.dock_widget.setObjectName("frame")
        self.dock_widget.setStyleSheet(
            "#frame { border: 1px solid #949494; border-top: none; background-color: #afafaf; }"
        )
        self.setWidget(self.dock_widget)

        # Create default layout
        self.main_layout = QtWidgets.QVBoxLayout(self.dock_widget)


class TitleBarButton(QtWidgets.QAbstractButton):

    """Button usable in the titlebar of dock widgets."""

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

    def sizeHint(self):
        """Returns the ideal size of this widget.

        :return ideal size of the widget
        """
        self.ensurePolished()

        size = 2 * self.style().pixelMetric(
            QtWidgets.QStyle.PM_DockWidgetTitleBarButtonMargin
        )
        
        

        if not self.icon().isNull():
            icon_size = self.style().pixelMetric(
                QtWidgets.QStyle.PM_SmallIconSize
            )
            sz = self.icon().actualSize(QtCore.QSize(icon_size, icon_size))
            size += max(sz.width(), sz.height())

        if size < 12: size = 12            

        return QtCore.QSize(size, size)

    def enterEvent(self, event):
        """Handles the event of the widget being entered.

        :param event the event to handle
        """
        if self.isEnabled():
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Handles the event of leaving the widget.

        :param event the event to handle
        """
        if self.isEnabled():
            self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        """Render the widget based on its current state.

        :param event the rendering event
        """
        p = QtGui.QPainter(self)

        options = QtWidgets.QStyleOptionToolButton()
        options.initFrom(self)
        options.state |= QtWidgets.QStyle.State_AutoRaise

        if self.style().styleHint(QtWidgets.QStyle.SH_DockWidget_ButtonsHaveFrame):
            if self.isEnabled() \
                    and self.underMouse() \
                    and not self.isChecked() \
                    and not self.isDown():
                options.state |= QtWidgets.QStyle.State_Raised
            if self.isChecked():
                options.state |= QtWidgets.QStyle.State_On
            if self.isDown():
                options.state |= QtWidgets.QStyle.State_Sunken
            self.style().drawPrimitive(
                QtWidgets.QStyle.PE_PanelButtonTool,
                options,
                p,
                self
            )

        options.icon = self.icon()
        options.subControls = QtWidgets.QStyle.SC_None
        options.activeSubControls = QtWidgets.QStyle.SC_None
        options.features = QtWidgets.QStyleOptionToolButton.None_
        options.arrowType = QtCore.Qt.NoArrow
        size = self.style().pixelMetric(
            QtWidgets.QStyle.PM_SmallIconSize
        )
        if size < 12: size = 12
        options.iconSize = QtCore.QSize(size, size)
        self.style().drawComplexControl(
            QtWidgets.QStyle.CC_ToolButton, options, p, self
        )


class TitleBar(QtWidgets.QFrame):

    """Represents a titlebar for use with dock widgets.

    This titlebar behaves like the default DockWidget title bar with the
    exception that it has a "help" button which will display some information
    about the content of the widget.
    """

    def __init__(self, label, hint, close_cb, clipboard_cb = None, parent=None):
        """Creates a new instance.

        :param label the label of the title bar
        :param hint the hint to show if needed
        :param close_cb the function to call when closing the widget
        :param clipboard_cb the function to call for clipboard operations (optional)
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.hint = hint
        self.label = QtWidgets.QLabel(label)

        size = 12

        # help button
        self.help_button = TitleBarButton()
        pixmap_help = load_pixmap("gfx/help")
        if not pixmap_help or pixmap_help.isNull():
            self.help_button.setText("?")
        else:
            icon = QtGui.QIcon()
            pixmap_help = pixmap_help.scaled(size, size, QtCore.Qt.KeepAspectRatio) 
            icon.addPixmap(pixmap_help, QtGui.QIcon.Normal)
            self.help_button.setIcon(icon)
        self.help_button.setToolTip("Help")
            
        self.help_button.clicked.connect(self._show_hint)

        # close button
        self.close_button = TitleBarButton()
        pixmap_close = load_pixmap("gfx/close")
        if not pixmap_close or pixmap_close.isNull():
            self.close_button.setText("X")
        else:
            icon = QtGui.QIcon()
            pixmap_close = pixmap_close.scaled(size, size, QtCore.Qt.KeepAspectRatio) 
            icon.addPixmap(pixmap_close, QtGui.QIcon.Normal)
            self.close_button.setIcon(icon)
        self.close_button.setToolTip("Delete")
            
        self.close_button.clicked.connect(close_cb)

        # clipboard copy button - only if a handler is given
        if clipboard_cb:
            self.copy_button = TitleBarButton()
            pixmap_copy = load_pixmap("gfx/button_copy.svg")
            icon = QtGui.QIcon()
            pixmap_copy = pixmap_copy.scaled(size, size, QtCore.Qt.KeepAspectRatio) 
            icon.addPixmap(pixmap_copy, QtGui.QIcon.Normal)
            self.copy_button.setIcon(icon)
            self.copy_button.clicked.connect(clipboard_cb)
            self.copy_button.setToolTip("Copy")

        self.layout = QtWidgets.QHBoxLayout()
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(5, 0, 5, 0)

        self.layout.addWidget(self.label)
        self.layout.addStretch()
        if clipboard_cb:
            self.layout.addWidget(self.copy_button)

        self.layout.addWidget(self.help_button)
        self.layout.addWidget(self.close_button)


        self.setFrameShape(QtWidgets.QFrame.Box)
        self.setObjectName("frame")
        self.setStyleSheet(
            "#frame { border: 1px solid #949494; background-color: #dadada; }"
        )

        self.setLayout(self.layout)

    def _show_hint(self):
        """Displays a hint, explaining the purpose of the action."""
        QtWidgets.QWhatsThis.showText(
            self.help_button.mapToGlobal(QtCore.QPoint(0, 10)),
            self.hint
        )



class BasicActionWrapper(AbstractActionWrapper):

    """Wraps an action widget and displays the basic config dialog."""

    # Signal which is emitted whenever the widget is closed
    closed = QtCore.Signal(QtWidgets.QWidget)

    def __init__(self, action_widget, parent=None):
        """Wraps an existing action widget.

        :param action_widget the action widget to wrap
        :param parent the parent of the widget
        """
        super().__init__(action_widget, parent)

        self.setTitleBarWidget(TitleBar(
            action_widget.action_data.name,
            gremlin.hints.hint.get(self.action_widget.action_data.tag, ""),
            self._remove,
            self._clipboard_copy,
        ))

        self.main_layout.addWidget(self.action_widget)

    def _remove(self, _):
        """Emits the closed event when this widget is being closed."""
        self.closed.emit(self)

    def _clipboard_copy(self, _):
        ''' clipboard copy event '''
        clipboard = Clipboard()
        action =  self.action_widget.action_data
        clipboard.data = action
        logging.getLogger("system").info(f"copy to clipboard: {action.name}")


class ConditionActionWrapper(AbstractActionWrapper):

    """Wraps an action widget and displays the condition config dialog."""

    def __init__(self, action_widget, parent=None):
        """Wraps an existing action widget.

        :param action_widget the action widget to wrap
        :param parent the parent of the widget
        """
        super().__init__(action_widget, parent)

        # Disable all dock features and give it a title
        self.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
        self.setWindowTitle(action_widget.action_data.name)

        # Setup activation condition UI
        action_data = self.action_widget.action_data
        if action_data.parent.activation_condition_type == "action":
            if action_data.activation_condition is None:
                action_data.activation_condition = \
                    gremlin.base_classes.ActivationCondition(
                        [],
                        gremlin.base_classes.ActivationRule.All
                    )

            self.condition_model = ui_activation_condition.ConditionModel(
                action_data.activation_condition
            )
            self.condition_view = ui_activation_condition.ConditionView()
            self.condition_view.set_model(self.condition_model)
            self.condition_view.redraw()
            self.main_layout.addWidget(self.condition_view)
        else:
            action_data.activation_condition = None


    
