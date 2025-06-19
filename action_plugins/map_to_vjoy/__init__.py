# -*- coding: utf-8; -*-

# Based on original concept / code by Lionel Ott - Copyright (C) 2015 - 2019 Lionel Ott
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
import logging
import threading
import time
from lxml import etree as ElementTree

from PySide6 import QtWidgets, QtCore, QtGui
import gremlin.actions
import gremlin.base_conditions
import gremlin.config
import gremlin.event_handler
import gremlin.execution_graph
import gremlin.input_types
import gremlin.joystick_handling
import gremlin.keyboard
import gremlin.repeater
import gremlin.singleton_decorator
import gremlin.ui.osc_device
import gremlin.ui.qsliderwidget
from gremlin.util import load_icon

from gremlin.base_conditions import InputActionCondition
from gremlin.input_types import InputType
from gremlin import input_devices, joystick_handling, util
from gremlin.error import ProfileError
from gremlin.util import safe_format, safe_read
import gremlin.ui.ui_common
import gremlin.ui.input_item
import os
import enum
from gremlin.input_devices import VjoyAction, remote_state
from gremlin.util import *
import gremlin.util
import vjoy.vjoy
from functools import partial


IdMapToButton = -2 # map to button special ID
import gremlin.ui.input_item
import gremlin.base_profile
import gremlin.shared_state
import gremlin.curve_handler

from gremlin.types import ButtonOutputMode




syslog = logging.getLogger("system")

@gremlin.singleton_decorator.SingletonDecorator
class StepWidgetGroup():
    def __init__(self):
        self.group = QtWidgets.QButtonGroup()

    def clear(self):
        self.group = QtWidgets.QButtonGroup()




class StepWidget(gremlin.ui.ui_common.QDataWidget):
    defaultChanged = QtCore.Signal(int, bool) # fires when default flag changes (index, flag)
    valueChanged = QtCore.Signal(int, float) # fires when value changes (index, value)
    deleteRequested = QtCore.Signal(int) # fires when delete is requested

    def __init__(self, index, value):
        super().__init__()
        self.index = index
        layout = QtWidgets.QHBoxLayout(self)
        
        self.value_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.value_widget.setValue(value)
        self.value_widget.valueChanged.connect(self._step_value_changed)
        self.default_cb = gremlin.ui.ui_common.QDataRadioButton("")
        bg = StepWidgetGroup()
        bg.group.addButton(self.default_cb)
        
        self.default_cb.setToolTip("Set as profile start value")
        self.default_cb.clicked.connect(self._step_default_changed)

        self.delete_widget = QtWidgets.QPushButton()
        self.delete_widget.setToolTip("Delete step")
        self.delete_widget.setIcon(load_icon("mdi.delete"))
        self.delete_widget.setMaximumWidth(20)
        self.delete_widget.clicked.connect(self._delete)

        layout.addWidget(self.value_widget)
        layout.addWidget(self.delete_widget)
        layout.addWidget(self.default_cb)
        layout.addStretch()


    @QtCore.Slot(bool)
    def _step_default_changed(self, checked):
        self.defaultChanged.emit(self.index, checked)

    @QtCore.Slot()
    def _step_value_changed(self):
        self.valueChanged.emit(self.index, self.value_widget.value())

    @QtCore.Slot()
    def _delete(self):
        self.deleteRequested.emit(self.index)

    def value(self) -> float:
        return self.value_widget.value()
    
    def setValue(self, value: float):
        with QtCore.QSignalBlocker(self.value_widget):
            self.value_widget.setValue(value)

    def setDefault(self, value:bool):
        ''' enable or disable default state '''
        bg = StepWidgetGroup()
        bg.group.buttons()[self.index].setChecked(value)
    
    
    

class MergeOperationType (enum.IntEnum):
    ''' merge operation method'''
    NotSet = 0
    Add = 1 # the two inputs are added
    Average = 2 # the two inputs are averaged
    Center = 3 # centered (left - right)/2
    Min = 4 # min of two axes
    Max = 5 # max of two axes

    @staticmethod
    def to_display_name(value : MergeOperationType):
        return _merge_operation_display_lookup[value]

    @staticmethod
    def to_enum(value : str):
        return _merge_operation_to_enum_lookup[value]

    @staticmethod
    def to_string(value : MergeOperationType):
        return _merge_operation_to_string_lookup[value]

    @staticmethod
    def to_description(value : MergeOperationType):
        return _merge_operation_to_description_lookup[value]


_merge_operation_to_enum_lookup = {
    "none" : MergeOperationType.NotSet,
    "add" : MergeOperationType.Add,
    "average" : MergeOperationType.Average,
    "center" : MergeOperationType.Center,
    "min" : MergeOperationType.Min,
    "max" : MergeOperationType.Max,

}

_merge_operation_to_string_lookup = {
    MergeOperationType.NotSet : "none",
    MergeOperationType.Add : "add",
    MergeOperationType.Average : "average",
    MergeOperationType.Center : "center",
    MergeOperationType.Min : "min",
    MergeOperationType.Max : "max",
}


_merge_operation_display_lookup = {
    MergeOperationType.NotSet : "N/A",
    MergeOperationType.Add : "Add",
    MergeOperationType.Average : "Average",
    MergeOperationType.Center : "Center",
    MergeOperationType.Min : "Minimum",
    MergeOperationType.Max : "Maximum",
}

_merge_operation_to_description_lookup = {
    MergeOperationType.NotSet : "Not set",
    MergeOperationType.Add : "A + B",
    MergeOperationType.Average : "Average (A+B)/2",
    MergeOperationType.Center : "Centered (A-B)/2",
    MergeOperationType.Min : "Min(A, B)",
    MergeOperationType.Max : "Max(A, B)",

}


class GridClickWidget(QtWidgets.QWidget):
    ''' implements a widget that reponds to a mouse click '''
    pressPos = None
    clicked = QtCore.Signal()

    def __init__(self, vjoy_device_id, input_type, vjoy_input_id, parent = None):
        super(GridClickWidget, self).__init__(parent=parent)
        self.vjoy_device_id = vjoy_device_id
        self.input_type = input_type
        self.vjoy_input_id = vjoy_input_id


    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton :
            self.pressPos = event.pos()

    def mouseReleaseEvent(self, event):
        # ensure that the left button was pressed *and* released within the
        # geometry of the widget; if so, emit the signal;
        if self.pressPos is not None and event.button() == QtCore.Qt.LeftButton:
            pos = event.pos()
            rect = self.rect()
            if  rect.contains(pos):
                self.clicked.emit()
        self.pressPos = None

class GridButton(QtWidgets.QPushButton):
    def __init__(self, action):
        super(GridButton,self).__init__()
        self.action = action

    def _clicked(self):
        pass


class GridPopupWindow(gremlin.ui.ui_common.QRememberDialog):
    def __init__(self, vjoy_device_id, input_type, vjoy_input_id, parent = None):
        super().__init__(self.__class__.__name__, parent = parent)

        self.vjoy_device_id = vjoy_device_id
        self.input_type = input_type
        self.vjoy_input_id = vjoy_input_id

        self.setWindowTitle("Mapping Details")

        usage_data = gremlin.joystick_handling.VJoyUsageState()
        action_map = usage_data.get_action_map(vjoy_device_id, input_type, vjoy_input_id)
        if not action_map:
            self.close()

        box = QtWidgets.QVBoxLayout()
        box.setContentsMargins(0,0,0,0)
        self.layout = box


        source =  QtWidgets.QWidget()
        source.setContentsMargins(0,0,0,0)
        source_box = QtWidgets.QHBoxLayout(source)
        source_box.setContentsMargins(0,0,0,0)
        source_box.addWidget(QtWidgets.QLabel(f"Vjoy {vjoy_device_id} Button {vjoy_input_id} mapped by:"))
        box.addWidget(source)

        for action in action_map:
            item = QtWidgets.QWidget()
            item_box = QtWidgets.QHBoxLayout(item)
            item_box.addWidget(QtWidgets.QLabel(action.device_name))
            if action.device_input_type == InputType.JoystickAxis:
                name = f"Axis {action.device_input_id}"
            elif action.device_input_type in VJoyRemapWidget.input_type_buttons:
                name = f"Button {action.device_input_id}"
            elif action.device_input_type == InputType.JoystickHat:
                name = f"Hat {action.device_input_id}"
            item_box.addWidget(QtWidgets.QLabel(name))
            #item_box.addWidget(GridButton(action))
            box.addWidget(item)


        self.setLayout(box)



class VJoyRemapWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Dialog which allows the selection of a vJoy output to use as
    as the remapping for the currently selected input.
    """
    locked = False



    # all button type inputs (hat is handled separately as is axis)
    input_type_buttons = [InputType.JoystickButton,
                          InputType.Keyboard,
                          InputType.KeyboardLatched,
                          InputType.OpenSoundControl,
                          InputType.Midi,
                          InputType.ModeControl,
                          ]

    def __init__(self, action_data, parent=None):
        """Creates a new VjoyRemapWidget.

        :param action_data profile data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, VjoyRemap))

    def _create(self, action_data):
        pass



    def _create_ui(self):
        """Creates the UI components."""

        config = gremlin.config.Configuration()
        self.verbose_inputs = config.verbose_mode_inputs
        self.verbose = config.verbose
        self.verbose_details = config.verbose_mode_inputs_extra
        self.last_merge_device_id = None # id of the last populated merge axis target

        self.container_height = 42


        if VJoyRemapWidget.locked:
            return
        
        el = gremlin.event_handler.EventListener()
        
        
        self._ui_loaded = False
        
        if not gremlin.shared_state.vjoy_enabled:
            self.main_layout.addWidget(QtWidgets.QLabel("VJOY is not available.  Ensure VJOY is installed and configured."))
            return

        
        veh = gremlin.event_handler.VjoyRemapEventHandler()
        veh.grid_visible_changed.connect(self.grid_visible_changed)

        try:
            VJoyRemapWidget.locked = True

            self.valid_types = [
                    InputType.JoystickAxis,
                    InputType.JoystickButton,
                    InputType.JoystickHat,
                    InputType.Midi,
                    InputType.OpenSoundControl,
                ]

            self._axis_tracking_enabled = False
            self.grid_visible_widget = None
            self.is_button_mode = False  # true if the action is mapping to a button
            self._grid_widgets = {} # list of checkboxes in the button grid indexed by button id (1...max_button)
            self.slider_widget = None # slider for stepped setup 

            self.usage_state = gremlin.joystick_handling.VJoyUsageState()

            self.main_layout.setSpacing(0)

            self._merge_enabled = False # disable merging by default


            # Create UI widgets for absolute / relative axis modes if the remap

            self.input_type = self.action_data.get_input_type()

            # init default widget tracking
            self.button_grid_widget  = None
            self.container_axis_widget = None

            # handler to update curve widget if displayed
            self.curve_update_handler = None

            self._is_axis = self.action_data.input_is_axis()

            # if the input is chained
            self.chained_input = self.action_data.input_item.is_action

            # create UI components

            self._create_override_input_type()
            self._create_selector()
            self._create_input_axis()
            self._create_range_widgets()
            self._create_button_modes()
            self._create_hat_mapping()
            self._create_output_range()
            self._create_merge_ui()
            self._create_step_ui()
            self._create_info()
            self._create_repeater()
            self._create_input_grid()


            self._update_axis_widget()


            self.main_layout.setContentsMargins(0, 0, 0, 0)


            eh = gremlin.event_handler.EventListener()
            eh.button_usage_changed.connect(self._button_usage_changed)


            # set the action type from the input type
            self.load_actions_from_input_type()

        finally:
            VJoyRemapWidget.locked = False
            self._ui_loaded = True



    def _event_handler(self, event):
        ''' event handler:  type of event: gremlin.event_handler.VjoyEvent '''
        match self.action_data.action_mode:
            case VjoyAction.VJoyAxis:
                # straight axis
                curves = self.getCurveData(event, action_value)
                value = self.action_data.get_filtered_axis_value(curves = curves)
                value = self.action_data.get_ranged_axis_value(value)

                

            case VjoyAction.VJoyAxisToButton:
                device_guid = self.action_data.hardware_device_guid
                input_id = self.action_data.hardware_input_id
                value = joystick_handling.get_curved_axis(device_guid, input_id)
                action_value = gremlin.actions.Value(value)
                event = gremlin.event_handler.Event(gremlin.input_types.InputType.JoystickAxis,
                                                    device_guid = device_guid,
                                                    identifier=input_id,
                                                    is_axis=True,
                                                    value = action_value)
                self.process_event(event, action_value)


    @QtCore.Slot(int)
    def _button_usage_changed(self, vjoy_id):
        ''' button state changed somewhere '''
        if vjoy_id == self.action_data.vjoy_device_id:
            # update if it's our device
            self.refresh_grid()


    def _get_selector_input_type(self):
        ''' gets a modified input type based on the current mode '''
        input_type = self.action_data.get_input_type()

        if input_type in VJoyRemapWidget.input_type_buttons and \
                        self.action_data.action_mode in (VjoyAction.VJoySetAxis,
                                                         VjoyAction.VJoyInvertAxis,
                                                         VjoyAction.VJoyRangeAxis,
                                                         VjoyAction.VJoySetAxisStepped):
            return InputType.JoystickAxis
        return input_type
        
    def _update_range_text(self):
        v1 = self.action_data.button_range_min
        v2 = self.action_data.button_range_max
        self._range_text =  f"[{v1:0.3f},{v2:0.3f}]"

    def _create_repeater(self):
        ''' creates an input repeater '''

        self._repeater_axis_widget = gremlin.ui.ui_common.AxisStateWidget(orientation = QtCore.Qt.Orientation.Horizontal,  show_percentage=False, show_label=False, show_value = True, decimals = 3)
        #self._repeater_button_widget = gremlin.ui.ui_common.ButtonStateWidget()
        widgets = [
            self._repeater_axis_widget,
            #self._repeater_button_widget,
        ]
        self.container_repeater_widget, _ = gremlin.ui.ui_common.getHContainer(widgets, min_height = self.container_height)
        self.main_layout.addWidget(self.container_repeater_widget)
        


    def _update_repeater(self, value = None):
        ''' updates the input repeater '''
        range_widget_visible = False
        axis_widget_visible = False
        if self.action_data.input_is_axis():
            if value is None:
                value = self.get_axis_value()

            if value is None:
                return # nothing to update
            match self.action_data.action_mode:
                case VjoyAction.VJoyAxisToButton:
                    range_widget_visible = True
                    v1 = self.action_data.button_range_min
                    v2 = self.action_data.button_range_max
                    in_range = gremlin.util.valueInRange(value, v1, v2)
                    if in_range:
                        self._repeater_range_widget.setText(f"In range ({value:0.3f} in {self._range_text})")
                        self._repeater_range_widget.setIcon(gremlin.ui.ui_common.Icons.validIcon())
                        #self._repeater_button_widget.setValue(True)
                    else:
                        self._repeater_range_widget.setText(f"Out of range ({value:0.3f} not in {self._range_text})")
                        self._repeater_range_widget.setIcon(gremlin.ui.ui_common.Icons.invalidIcon())
                        #self._repeater_button_widget.setValue(False)
                case VjoyAction.VJoyAxis:
                    axis_widget_visible = True
                    self._repeater_axis_widget.setValue(value)
           
            


        self._repeater_range_widget.setVisible(range_widget_visible)
        self._repeater_axis_widget.setVisible(axis_widget_visible)

    def _create_range_widgets(self):

        self.button_range_min_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.button_range_min_widget.setValue(self.action_data.button_range_min)
        self.button_range_min_widget.valueChanged.connect(self._button_range_min_changed_cb)

        self.button_range_max_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.button_range_max_widget.setValue(self.action_data.button_range_max)
        self.button_range_max_widget.valueChanged.connect(self._button_range_max_changed_cb)

        self.button_grab_min_widget = gremlin.ui.ui_common.Buttons.getGrabWidget(tooltip = "Grab minimum value", callback = self._grab_min)
        self.button_grab_max_widget = gremlin.ui.ui_common.Buttons.getGrabWidget(tooltip = "Grab maximum value", callback = self._grab_max)

        self._update_range_text()
        self._repeater_range_widget = gremlin.ui.ui_common.QIconLabel()


        widgets = [QtWidgets.QLabel("Axis to Button Range Min:"), 
                    self.button_range_min_widget,
                    self.button_grab_min_widget,
                    QtWidgets.QLabel("Range Max:"),
                    self.button_range_max_widget,
                    self.button_grab_max_widget,
                    self._repeater_range_widget
                    ]

        self.container_axis_to_button_range_widget, _ =  gremlin.ui.ui_common.getHContainer(widgets, min_height = self.container_height)
        self.container_axis_to_button_range_widget.setToolTip("Button to axis range parameters. The button will be output if the input axis in this range.")
        self.main_layout.addWidget(self.container_axis_to_button_range_widget)

        

    @QtCore.Slot()
    def _grab_min(self):
        ''' grabs min range value '''
        value = self.get_axis_value()
        self.button_range_min_widget.setValue(value)

    @QtCore.Slot()
    def _grab_max(self):
        ''' grabs max range value '''
        value = self.get_axis_value()
        self.button_range_max_widget.setValue(value)


    def _create_hat_mapping(self):
        ''' creates the 8 way hat inputs based on the hat input value '''
        self.container_hat_widget = QtWidgets.QWidget()
        self.container_hat_widget.setContentsMargins(0,0,0,0)

        self.container_hat_layout = QtWidgets.QVBoxLayout(self.container_hat_widget)
        self.container_hat_layout.setContentsMargins(0,0,0,0)

        self.container_hat_grid_widget = QtWidgets.QWidget()
        self.container_hat_grid_layout = QtWidgets.QGridLayout(self.container_hat_grid_widget)

        self.container_hat_options_widget = QtWidgets.QWidget()
        self.container_hat_options_widget.setContentsMargins(0,0,0,0)
        self.container_hat_options_layout = QtWidgets.QHBoxLayout(self.container_hat_options_widget)

        self.main_layout.addWidget(self.container_hat_widget)



        self.cb_hat_list = []
        self.rb_hat_list = {}
        #self.rb_hat_pulse_list = []

        self.hat_pulse_widget = QtWidgets.QPushButton("All Pulse")
        self.hat_pulse_widget.setToolTip("Sets all mappings to pulse mode")
        self.hat_hold_widget = QtWidgets.QPushButton("All Hold")
        self.hat_hold_widget.setToolTip("Sets all mappings to hold mode")

        self.hat_press_widget = QtWidgets.QPushButton("All Press")
        self.hat_press_widget.setToolTip("Sets all mappings to press mode")

        self.hat_release_widget = QtWidgets.QPushButton("All Release")
        self.hat_release_widget.setToolTip("Sets all mappings to release mode")

        self.hat_noop_widget = QtWidgets.QPushButton("All NoOp")
        self.hat_noop_widget.setToolTip("Sets all mappings to NoOp (do nothing) mode")


        self.hat_unmap_widget =  QtWidgets.QPushButton("Clear Buttons")
        self.hat_unmap_widget.setToolTip("Clears all mappings")
        self.hat_map_widget =  QtWidgets.QPushButton("Map Buttons")
        self.hat_map_widget.setToolTip("Maps all positions sequentially using the first button as the reference if set.")

        self.hat_hold_widget.clicked.connect(self._set_all_hold)
        self.hat_pulse_widget.clicked.connect(self._set_all_pulse)
        self.hat_press_widget.clicked.connect(self._set_all_press)
        self.hat_release_widget.clicked.connect(self._set_all_release)
        self.hat_noop_widget.clicked.connect(self._set_all_noop)

        self.hat_unmap_widget.clicked.connect(self._clear_map)
        self.hat_map_widget.clicked.connect(self._auto_map)

        self.container_hat_options_layout.addWidget(self.hat_hold_widget)
        self.container_hat_options_layout.addWidget(self.hat_pulse_widget)
        self.container_hat_options_layout.addWidget(self.hat_press_widget)
        self.container_hat_options_layout.addWidget(self.hat_release_widget)
        self.container_hat_options_layout.addWidget(self.hat_noop_widget)
        self.container_hat_options_layout.addWidget(self.hat_unmap_widget)
        self.container_hat_options_layout.addWidget(self.hat_map_widget)
        self.container_hat_options_layout.addStretch()


        positions = self.action_data.hat_positions


        self.container_hat_layout.addWidget(self.container_hat_options_widget)
        self.container_hat_layout.addWidget(self.container_hat_grid_widget)

        row = 0
        for position in positions: # 9 positions - 8 cardinal and center push
            cb = gremlin.ui.ui_common.NoWheelComboBox()
            cb.data = position
            name = vjoy.vjoy.Hat.direction_to_name[position]
            icon = vjoy.vjoy.Hat.direction_to_icon[position]
            lbl = gremlin.ui.ui_common.QIconLabel(icon_path=icon, text = f"{name}:", use_wrap= False, icon_color=QtGui.QColor(gremlin.ui.ui_common.Color.activeColor()),icon_size=32, use_qta=True)

            lbl.setIcon(icon)
            self.container_hat_grid_layout.addWidget(lbl, row, 0)
            self.container_hat_grid_layout.addWidget(cb, row,1)
            self.cb_hat_list.append(cb)
            cb.currentIndexChanged.connect(self._hat_mapping_changed)

            mode_container_widget = QtWidgets.QWidget()
            mode_container_widget.setContentsMargins(0,0,0,0)
            mode_container_layout = QtWidgets.QHBoxLayout(mode_container_widget)

            rb_hold = gremlin.ui.ui_common.QDataRadioButton("Hold")
            rb_hold.setToolTip("Output will match the current state of the input.")
            rb_hold.data = position
            rb_pulse = gremlin.ui.ui_common.QDataRadioButton("Pulse")
            rb_pulse.setToolTip("Output will pulse on (pressed), wait a delay, and turn off (released) when triggered.")
            rb_pulse.data = position
            rb_press = gremlin.ui.ui_common.QDataRadioButton("Press")
            rb_press.setToolTip("Output will be turned on (pressed) when triggered.")
            rb_press.data = position
            rb_release = gremlin.ui.ui_common.QDataRadioButton("Release")
            rb_release.setToolTip("Output will be turned off (released) when triggered.")
            rb_release.data = position
            rb_noop = gremlin.ui.ui_common.QDataRadioButton("NoOp")
            rb_noop.setToolTip("No output.")
            rb_noop.data = position

            rb_hold.clicked.connect(self._hat_hold_changed)
            rb_pulse.clicked.connect(self._hat_pulse_changed)
            rb_press.clicked.connect(self._hat_press_changed)
            rb_release.clicked.connect(self._hat_release_changed)
            rb_noop.clicked.connect(self._hat_noop_changed)

            mode_container_layout.addWidget(rb_hold)
            mode_container_layout.addWidget(rb_pulse)
            mode_container_layout.addWidget(rb_press)
            mode_container_layout.addWidget(rb_release)
            mode_container_layout.addWidget(rb_noop)

            self.container_hat_grid_layout.addWidget(mode_container_widget, row, 2)

            # must match enum sequence
            self.rb_hat_list[position] = [rb_hold, rb_pulse, rb_press, rb_release, rb_noop]
            

            row += 1


        self.container_hat_grid_layout.addWidget(QtWidgets.QLabel(), 0, 4)
        self.container_hat_grid_layout.setColumnStretch(4,3)
        self._update_hat_mapping()


    @QtCore.Slot(bool)
    def _hat_sticky_changed(self, checked : bool):
        self.action_data.hat_sticky = checked

    @QtCore.Slot(bool)
    def _pulse_repeat_mode_changed(self, checked : bool):
        self.action_data.pulse_repeat = checked
        self._update_ui()

    def _set_all_mode(self, mode : ButtonOutputMode):
        positions = self.action_data.hat_positions
        for position in positions:
            self.action_data.hat_mode_map[position] = mode
        self._update_hat_mapping()

    @QtCore.Slot()
    def _set_all_hold(self):
        ''' sets all mappings to hold mode '''
        self._set_all_mode(ButtonOutputMode.Hold)
        

    @QtCore.Slot()
    def _set_all_pulse(self):
        ''' sets all mappings to pulse mode '''
        self._set_all_mode(ButtonOutputMode.Pulse)

    @QtCore.Slot()
    def _set_all_press(self):
        ''' sets all mappings to pulse mode '''
        self._set_all_mode(ButtonOutputMode.Press)

    @QtCore.Slot()
    def _set_all_release(self):
        ''' sets all mappings to pulse mode '''
        self._set_all_mode(ButtonOutputMode.Release)        

    @QtCore.Slot()
    def _set_all_noop(self):
        ''' sets all mappings to pulse mode '''
        self._set_all_mode(ButtonOutputMode.NoOp)                


    @QtCore.Slot()
    def _clear_map(self):
        ''' sets all mappings to pulse mode '''
        msgbox = gremlin.ui.ui_common.ConfirmBox(prompt = "Clear all hat button mappings?")
        result = msgbox.show()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            positions = self.action_data.hat_positions
            for position in positions:
                self.action_data.hat_map[position] = 0
            self._update_hat_mapping()

    @QtCore.Slot()
    def _auto_map(self):
        ''' sets all mappings to pulse mode '''
        msgbox = gremlin.ui.ui_common.ConfirmBox(prompt = "Remap all hat button mappings?")
        result = msgbox.show()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            positions = self.action_data.hat_positions
            dev = self.action_data.vjoy_map[self.action_data.vjoy_device_id]
            button_count = dev.button_count
            for index, position in enumerate(positions):
                if index == 0:
                    button_id = self.action_data.hat_map[position]
                    if button_id == 0:
                        # default if first button is not set
                        button_id = 1

                self.action_data.hat_map[position] = button_id

                button_id += 1
                if button_id > button_count:
                    # wrap around
                    button_id = 1

            self._update_hat_mapping()


    @QtCore.Slot()
    def _hat_mapping_changed(self):
        ''' updates a hat button mapping selection '''
        cb = self.sender()
        position = cb.data
        button_id = cb.currentData()
        self.action_data.hat_map[position] = button_id

    def _hat_mode_changed(self, widget, mode : ButtonOutputMode):
        if widget.isChecked():
            position = widget.data
            self.action_data.hat_mode_map[position] = mode


    @QtCore.Slot()
    def _hat_hold_changed(self):
        ''' updates a hat button mapping selection '''
        self._hat_mode_changed(self.sender(), ButtonOutputMode.Hold)
        

    @QtCore.Slot()
    def _hat_pulse_changed(self):
        ''' updates a hat button mapping selection '''
        self._hat_mode_changed(self.sender(), ButtonOutputMode.Pulse)

    @QtCore.Slot()
    def _hat_press_changed(self):
        ''' updates a hat button mapping selection '''
        self._hat_mode_changed(self.sender(), ButtonOutputMode.Press)
        
    @QtCore.Slot()
    def _hat_release_changed(self):
        ''' updates a hat button mapping selection '''
        self._hat_mode_changed(self.sender(), ButtonOutputMode.Release)
        
    @QtCore.Slot()
    def _hat_noop_changed(self):
        ''' updates a hat button mapping selection '''
        self._hat_mode_changed(self.sender(), ButtonOutputMode.NoOp)
                


    def _update_hat_mapping(self):
        ''' updates the hat button options for hat to button mapping '''
        
        dev = self.action_data.vjoy_map[self.action_data.vjoy_device_id]
        count = dev.button_count
        positions = self.action_data.hat_positions
        for index, position in enumerate(positions):  # 9 positions - 8 cardinal and center push
            cb = self.cb_hat_list[index]
            with QtCore.QSignalBlocker(cb):
                cb.clear()
                cb.addItem("Not mapped", 0)
                for id in range(1, count+1):
                    cb.addItem(f"Button {id}",id)

            mode = self.action_data.hat_mode_map[position]
            rb = self.rb_hat_list[position][int(mode)]
            with QtCore.QSignalBlocker(rb):
                rb.setChecked(True)

        self._load_hat_mapping()

    def _load_hat_mapping(self):
        ''' loads the hat data into the UI '''
        positions = self.action_data.hat_positions
        for index, position in enumerate(positions):  # 9 positions - 8 cardinal and center push
            button_id = self.action_data.hat_map[position] # 0 means disabled
            button_index = button_id
            cb = self.cb_hat_list[index]
            if button_index < cb.count():
                with QtCore.QSignalBlocker(cb):
                    cb.setCurrentIndex(button_index)







    def _create_input_axis(self):
        ''' creates the axis input widget '''


        self.absolute_checkbox = QtWidgets.QRadioButton("Absolute")
        self.absolute_checkbox.setChecked(self.action_data.axis_mode == "absolute")
        self.relative_checkbox = QtWidgets.QRadioButton("Relative")
        self.relative_checkbox.setChecked(self.action_data.axis_mode == "relative")

        self.reverse_checkbox = QtWidgets.QCheckBox("Reverse Axis")
        self.reverse_checkbox.setToolTip("When enabled, inverts the input")
        self.reverse_checkbox.setChecked(self.action_data.reverse)
        self.reverse_checkbox.clicked.connect(self._axis_reverse_changed)



        self.b_min_value = QtWidgets.QPushButton("-1")
        w = 32
        self.set_width(self.b_min_value,w)
        self.b_center_value = QtWidgets.QPushButton("0")

        self.set_width(self.b_center_value,w)
        self.b_max_value = QtWidgets.QPushButton("+1")
        self.set_width(self.b_max_value,w)
     
        self._axis_start_value_enabled_widget = QtWidgets.QCheckBox("Start Value:")
        self._axis_start_value_enabled_widget.setChecked(self.action_data.axis_start_value_enabled)
        self._axis_start_value_enabled_widget.clicked.connect(self._axis_start_value_enabled)
        self._axis_start_value_enabled_widget.setToolTip("When set, sets the axis to the specified startup value on profile start.\nIf not set, uses the current axis input value on start.")
        


        self.sb_start_value = gremlin.ui.ui_common.DynamicDoubleSpinBox(parent = self.container_axis_widget)
        # w = 100
        # self.set_width(self.sb_start_value,w)
        self.sb_start_value.setMinimum(-1.0)
        self.sb_start_value.setMaximum(1.0)
        self.sb_start_value.setDecimals(3)


        self.relative_scaling_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.relative_scaling_widget.setMinimum(0)
        self.relative_scaling_widget.setMaximum(1000.0)
        self.relative_scaling_widget.setDecimals(3)

        

        self.container_reverse_widget, _ = gremlin.ui.ui_common.getHContainer(self.reverse_checkbox, min_height = self.container_height)
        self.main_layout.addWidget(self.container_reverse_widget)

        widgets = [
            self.absolute_checkbox,
            self.relative_checkbox,
        ]
        self.container_output_mode_widget, _ = gremlin.ui.ui_common.getHContainer(widgets, "Output mode:", min_height = self.container_height)
        self.main_layout.addWidget(self.container_output_mode_widget)

        # # absolute mode options
        # self.container_absolute_widget, _ = gremlin.ui.ui_common.getHContainer(min_height = self.container_height)
        # self.main_layout.addWidget(self.container_absolute_widget)

        # relative mode options
        widgets = [
            self._axis_start_value_enabled_widget,
            "Start Value:",
            self.sb_start_value,
            "Min:",
            self.b_min_value,
            "Center:",
            self.b_center_value, 
            "Max:",
            self.b_max_value,
            "Relative scale:",
            self.relative_scaling_widget
        ]

        self.container_relative_widget, _ = gremlin.ui.ui_common.getHContainer(widgets, "Relative mode options:", min_height = self.container_height)

        
        self.main_layout.addWidget(self.container_relative_widget)
        
        self.absolute_checkbox.clicked.connect(self._axis_mode_changed)
        self.relative_checkbox.clicked.connect(self._axis_mode_changed)
        self.relative_scaling_widget.valueChanged.connect(self._axis_scaling_changed)

        self.sb_start_value.valueChanged.connect(self._axis_start_value_changed)
        self.b_min_value.clicked.connect(self._b_min_start_value_clicked)
        self.b_center_value.clicked.connect(self._b_center_start_value_clicked)
        self.b_max_value.clicked.connect(self._b_max_start_value_clicked)

        # hook the inputs and profile
        self._enable_axis_tracking()
        
    def _create_output_range(self):
        ''' creates the output range widget '''

        self.curve_button_widget = QtWidgets.QPushButton("Output Curve")

        active_color = gremlin.ui.ui_common.Color.activeColor()
        normal_color = gremlin.ui.ui_common.Color.normalColor()
        self.curve_icon_inactive = util.load_icon("mdi.chart-bell-curve",qta_color=normal_color)
        self.curve_icon_active = util.load_icon("mdi.chart-bell-curve",qta_color=active_color)
        self.curve_button_widget.setToolTip("Curve output")
        self.curve_button_widget.clicked.connect(self._curve_button_cb)

        self.curve_clear_widget = QtWidgets.QPushButton("Clear curve")
        delete_icon = load_icon("mdi.delete")
        self.curve_clear_widget.setIcon(delete_icon)
        self.curve_clear_widget.setToolTip("Removes the curve output")
        self.curve_clear_widget.clicked.connect(self._curve_delete_button_cb)

        self.output_range_min_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.output_range_min_widget.setValue(self.action_data.output_range_min)
        self.output_range_min_widget.valueChanged.connect(self._output_range_min_changed_cb)

        self.output_range_max_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.output_range_max_widget.setValue(self.action_data.output_range_max)

        self.output_range_max_widget.valueChanged.connect(self._output_range_max_changed_cb)

        reset_widget = QtWidgets.QPushButton("Reset")
        reset_widget.setToolTip("Resets the output range to default")
        reset_widget.clicked.connect(self._reset_output_range)

        widgets = [
            self.curve_button_widget,
            self.curve_clear_widget,
        ]
        
        self.container_output_curve_widget, _ = gremlin.ui.ui_common.getHContainer(widgets,"Output Curve Options", min_height = self.container_height)
        self.main_layout.addWidget(self.container_output_curve_widget)

        widgets = [
            QtWidgets.QLabel("Range Min:"), 
            self.output_range_min_widget,
            QtWidgets.QLabel("Range Max:"),
            self.output_range_max_widget,
            reset_widget]
        

        self.container_output_range_widget, self.container_output_range_layout = gremlin.ui.ui_common.getHContainer(widgets, "Output Scale:", min_height = self.container_height)
        self.container_output_range_widget.setToolTip("Allows you to set limits to the output range of an axis to constrain the output to a particular reduced range from normal.")

        

        self._update_curve_icon()
        self.main_layout.addWidget(self.container_output_range_widget)


    def _enable_axis_tracking(self):
        if not self._axis_tracking_enabled:
            self._axis_tracking_enabled = True
            el = gremlin.event_handler.EventListener()
            el.custom_joystick_event.connect(self._joystick_event_handler)
            if not self.chained_input:
                el.joystick_event.connect(self._joystick_event_handler)
            el.profile_start.connect(self._profile_start)
            el.profile_stop.connect(self._profile_stop)

    def _disable_axis_tracking(self):
        ''' disables tracking '''
        if self._axis_tracking_enabled:
            el = gremlin.event_handler.EventListener()
            el.custom_joystick_event.disconnect(self._joystick_event_handler)
            if not self.chained_input:
                el.joystick_event.disconnect(self._joystick_event_handler)
            self._axis_tracking_enabled = False


    def _create_merge_ui(self):
        ''' creates the axis merging UI components '''
        # merge operations
        self.container_merge_widget = QtWidgets.QWidget()
        self.container_merge_layout = QtWidgets.QVBoxLayout(self.container_merge_widget)

        self.merge_selector_device_widget = gremlin.ui.ui_common.NoWheelComboBox()
        self.merge_selector_input_widget = gremlin.ui.ui_common.NoWheelComboBox()

        device_widget = QtWidgets.QWidget()
        device_layout = QtWidgets.QGridLayout(device_widget)
        device_layout.addWidget(QtWidgets.QLabel("Merge Device:"),0,0)
        device_layout.addWidget(self.merge_selector_device_widget,0,1)
        device_layout.addWidget(QtWidgets.QLabel(" "),0,2)
        device_layout.addWidget(QtWidgets.QLabel("Merge Axis:"),1,0)
        device_layout.addWidget(self.merge_selector_input_widget,1,1)

        self.merge_device_listen_widget = gremlin.ui.ui_common.Buttons.getListenWidget(callback = self._listen_cb, tooltip = "Listen for axis to merge")
        device_layout.addWidget(self.merge_device_listen_widget, 0, 2)
        device_layout.setColumnStretch(3,2)

        self.container_merge_layout.addWidget(device_widget)

        self.merge_selector_device_widget.currentIndexChanged.connect(self._merged_device_changed_cb)
        self.merge_selector_input_widget.currentIndexChanged.connect(self._merged_input_changed_cb)

        # populate the selector with hardware inputs
        self.merge_device_map = {} # holds the device information keyed by device_id (str)
        self.merge_input_map = {} # holds the list of axes for the given device by device_id(str)
        devices = sorted(joystick_handling.axis_input_devices(),key=lambda x: x.name)

        self._merge_enabled = len(devices) > 0 # assume enabled

        # figure out the default device to use
        default_device = None
        selected_input_id = 1
        if self.action_data.merge_device_id:
            default_device : dinput.DeviceSummary = next((dev for dev in devices if dev.device_id == self.action_data.merge_device_id), None)
            if default_device:

                if default_device.device_guid == self.action_data.hardware_device_guid:
                    # the merge device to pick is the same as the current device
                    if default_device.axis_count == 1:
                        # there is only one input which is already used
                        self._merge_enabled = False

                valid_input_ids = default_device.getValidAxisInputIds()
                if self.action_data.merge_input_id and self.action_data.merge_input_id in valid_input_ids:
                    selected_input_id = self.action_data.merge_input_id

        if not default_device:
            default_device = next((dev for dev in devices if dev.device_guid == self.action_data.hardware_device_guid), None)
            if default_device:
                axis_count = default_device.axis_count
                if axis_count == 1:
                    # there is only one input which is already used
                    self._merge_enabled = False

                else:
                    # pick a suitable input
                    input_id = self.action_data.hardware_input_id
                    if input_id < axis_count:
                        # pick next if possoble
                        selected_input_id = input_id + 1
                    elif input_id > 1:
                        # pick one below if next not available
                        selected_input_id = input_id - 1


        if not self._merge_enabled:
            return

        if not default_device:
            # pick the first one if nothing else got selected
            default_device = devices[0]




        selected_device_index = devices.index(default_device)

        for dev in devices:
            self.merge_device_map[dev.device_id] = dev
            axis_list = {}
            for input_id in range(1, dev.axis_count+1):
                if dev.device_guid == self.action_data.hardware_device_guid and \
                    input_id == self.action_data.hardware_input_id:
                    # skip self as a possible input
                    continue
                axis_name = self.get_axis_name(input_id)
                axis_list[input_id] = f"Axis {input_id} ({axis_name})"

            if axis_list:
                self.merge_input_map[dev.device_id] = axis_list
                self.merge_selector_device_widget.addItem(dev.name, dev.device_id)

                

        self._update_axis_list(default_device.device_id, selected_input_id)


        # merge operation mode

        self._merge_widgets_map = {}
        
        widgets = []
        for merge_type in MergeOperationType:
            if merge_type != MergeOperationType.NotSet:
                rb = gremlin.ui.ui_common.QDataRadioButton(text = MergeOperationType.to_display_name(merge_type), data = merge_type)
                widgets.append(rb)
                self._merge_widgets_map[merge_type] = rb
                if merge_type == self.action_data.merge_mode:
                    rb.setChecked(True)
                rb.clicked.connect(self._merge_mode_changed_cb)

        

        self.merge_invert_widget = QtWidgets.QCheckBox("Invert")
        self.merge_invert_widget.setChecked(self.action_data.merge_invert)
        self.merge_invert_widget.clicked.connect(self._merge_invert_changed_cb)
        widgets.append(self.merge_invert_widget)

        self.container_merge_options_widget, _ = gremlin.ui.ui_common.getHContainer(widgets,"Merge Operation:")

        self.container_merge_layout.addWidget(self.container_merge_options_widget)

        self.main_layout.addWidget(self.container_merge_widget)

        # select the default device
        self.merge_selector_device_widget.setCurrentIndex(selected_device_index)

        selected_input_index = self.merge_selector_input_widget.findData(selected_input_id)
        if selected_input_index == -1:
            selected_input_index = 0
        self.merge_selector_input_widget.setCurrentIndex(selected_input_index)




    QtCore.Slot()
    def _listen_cb(self):
        ''' listen to an input for a button '''
        self.axis_listen_dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.JoystickAxis],
            return_kb_event=False,
            filter_func=self._filter_input
        )

        self.axis_listen_dialog.item_selected.connect(self._update_merged_axis)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        self.axis_listen_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150
        )
        self.axis_listen_dialog.show()


    def _filter_input(self, event : gremlin.event_handler.Event) -> bool:
        # only accept axes different from the current input axis
        if gremlin.util.compare_guid(event.device_id, self.action_data.hardware_device_id) \
            and event.identifier == self.action_data.get_input_id():
            # don't listen to the same input as the current input for merged axis
            return False
        return True
    
    def _update_merged_axis(self, event : gremlin.event_handler.Event):
        ''' merged axis selected via the listen button '''
        self.axis_listen_dialog.item_selected.disconnect(self._update_merged_axis) # stop listening
        device_id = event.device_id
        input_id = event.identifier
        self._select_merge_target(device_id, input_id)

    def _select_merge_target(self, device_id, input_id):
        ''' selects a given merge axis'''
        index = self.merge_selector_device_widget.findData(device_id)
        if index != -1:
            if index != self.merge_selector_device_widget.currentIndex():
                with QtCore.QSignalBlocker(self.merge_selector_device_widget):
                    self.merge_selector_device_widget.setCurrentIndex(index) # this also updates the axis list if needed
                    self._update_axis_list(device_id, input_id)
                    self.action_data.merge_device_id = device_id

            index = self.merge_selector_input_widget.findData(input_id)
            if index != -1:
                if index != self.merge_selector_input_widget.currentIndex():
                    with QtCore.QSignalBlocker(self.merge_selector_input_widget):
                        self.merge_selector_input_widget.setCurrentIndex(index)
                        self.action_data.merge_input_id = input_id

    def _update_curve_icon(self):
        if self.action_data.curve_data:
            self.curve_button_widget.setIcon(self.curve_icon_active)
            self.curve_clear_widget.setEnabled(True)
        else:
            self.curve_button_widget.setIcon(self.curve_icon_inactive)
            self.curve_clear_widget.setEnabled(False)

    QtCore.Slot()
    def _curve_button_cb(self):
        if not self.action_data.curve_data:
            curve_data = gremlin.curve_handler.AxisCurveData()
            curve_data.calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(self.action_data.hardware_device_guid, self.action_data.hardware_input_id)
            curve_data.curve_update()
            self.action_data.curve_data = curve_data

        dialog = gremlin.curve_handler.AxisCurveDialog(self.action_data.curve_data)
        util.centerDialog(dialog, dialog.width(), dialog.height())
        self.curve_update_handler = dialog.curve_update_handler
        self._update_axis_widget()

        # disable highlighting
        gremlin.shared_state.push_suspend_highlighting()
        dialog.exec()
        gremlin.shared_state.pop_suspend_highlighting()
        self.curve_update_handler = None

        self._update_curve_icon()

    QtCore.Slot()
    def _curve_delete_button_cb(self):
        ''' removes the curve data '''
        message_box = QtWidgets.QMessageBox()
        message_box.setText("Confirmation")
        message_box.setInformativeText("Delete curve data for this output?")
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
        )
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        is_cursor = isCursorActive()
        if is_cursor:
            popCursor()
        response = message_box.exec()
        if is_cursor:
            pushCursor()
        if response == QtWidgets.QMessageBox.StandardButton.Ok:
            self.action_data.curve_data = None
            self._update_curve_icon()

    QtCore.Slot()
    def _reset_output_range(self):
        ''' resets the output range '''
        self.output_range_min_widget.setValue(-1.0)
        self.output_range_max_widget.setValue(1.0)


    QtCore.Slot()
    def _output_range_min_changed_cb(self):
        value = self.output_range_min_widget.value()
        self.action_data.output_range_min = value
        self._update_axis_widget()

    QtCore.Slot()
    def _output_range_max_changed_cb(self):
        self.action_data.output_range_max = self.output_range_max_widget.value()
        self._update_axis_widget()


    QtCore.Slot()
    def _button_range_min_changed_cb(self):
        ''' button min range value changed '''
        self.action_data.button_range_min = self.button_range_min_widget.value()
        self._update_range_text()
        self._update_axis_widget()

    QtCore.Slot()
    def _button_range_max_changed_cb(self):
        ''' button max range value changed '''
        self.action_data.button_range_max = self.button_range_max_widget.value()
        self._update_range_text()
        self._update_axis_widget()        

    @QtCore.Slot()
    def _merged_device_changed_cb(self):
        ''' merge device changed '''
        index = self.merge_selector_device_widget.currentIndex()
        device_id = self.merge_selector_device_widget.itemData(index)
        input_id = self.action_data.merge_input_id
        
        self._update_axis_list(device_id, input_id)
        self.action_data.merge_device_id = device_id
        self.action_data.merge_input_id = self.merge_selector_input_widget.currentData()
        self.action_modified.emit()

    def _update_axis_list(self, device_id, select_input_id = None):
        ''' updates the axis list for a merge input '''

        if self.last_merge_device_id and gremlin.util.compare_guid(self.last_merge_device_id,device_id):
            return
        
        device = joystick_handling.device_info_from_guid(device_id)
        input_device_id = self.action_data.get_device_guid()
        input_input_id = self.action_data.get_input_id()
        
        with QtCore.QSignalBlocker(self.merge_selector_input_widget):
            self.merge_selector_input_widget.clear()
            if not device:
                return
            index = 0
            select_index = None

            valid_input_ids = device.getValidAxisInputIds()
            for input_id in valid_input_ids:
                if gremlin.util.compare_guid(device.device_guid, input_device_id) and input_id == input_input_id:
                    # skip current input as a merge target
                    continue
                axis_name = device.getAxisName(input_id)
                self.merge_selector_input_widget.addItem(axis_name, input_id)
                if select_index is None and input_id == select_input_id:
                    select_index = index
                index += 1

            if select_index is not None:
                self.merge_selector_input_widget.setCurrentIndex(select_index)
            
            self.last_merge_device_id = device.device_id



    @QtCore.Slot()
    def _merged_input_changed_cb(self):
        ''' merge input changed '''
        index = self.merge_selector_input_widget.currentIndex()
        input_id = self.merge_selector_input_widget.itemData(index)
        self.action_data.merge_input_id = input_id
        self.action_modified.emit()




    def _profile_start(self):
        ''' called when the profile starts '''
        self._disable_axis_tracking()

    def _profile_stop(self):
        ''' called when the profile stops'''
        self._update_axis_widget()
        self._enable_axis_tracking()
        

    def _joystick_event_handler(self, event):
        ''' handles joystick events in the UI (functor handles the output when profile is running) so we see the output at design time '''
        if gremlin.shared_state.is_running:
            return
        
        

        if not event.is_axis:
            return
        
        value = event.value

        if self.action_data.action_mode == VjoyAction.VJoyMergeAxis:
            # merge - check two sets
            if event.device_guid == self.action_data.hardware_device_guid and event.device_guid == self.action_data.merge_device_guid:
                # merge hardware is the same as current input - accept only the two input itds
                if event.identifier != self.action_data.hardware_input_id and event.identifier != self.action_data.merge_input_id:
                    return
            else:
                # not the same:
                if event.device_guid == self.action_data.hardware_device_guid and event.identifier != self.action_data.hardware_input_id:
                    return
                if event.device_guid == self.action_data.merge_device_guid and event.identifier != self.action_data.merge_input_id:
                    return

            # compute the merged value    
            value = self.action_data.get_filtered_axis_value(value)



        else:
            if event.device_id != self.action_data.hardware_device_id:
                # event not for us
                return
            if event.identifier != self.action_data.hardware_input_id:
                # event not for us
                return

        self._update_axis_widget()


    def _current_input_axis(self):
        ''' gets the current input axis value '''
        return gremlin.joystick_handling.get_curved_axis(self.action_data.hardware_device_guid,
                                                  self.action_data.hardware_input_id)


    def _update_axis_widget(self):
        ''' updates the axis output repeater with the value

        :param value: the floating point input value, if None uses the cached value

        '''
        # always read the current input as the value could be from another device for merged inputs
        if self.action_data.input_is_axis(): # == InputType.JoystickAxis:
            curves = [self.action_data.curve_data] if self.action_data.curve_data else None
            value = self.action_data.get_filtered_axis_value(curves = curves)
            
            # update the curved window if displayed
            if self.curve_update_handler is not None:
                self.curve_update_handler(value) # use the current axis input value, not the curved value

            self._update_repeater()



    @QtCore.Slot(bool)
    def _merge_invert_changed_cb(self, checked):
        self.action_data.merge_invert = checked
        self._update_axis_widget()

    @QtCore.Slot(bool)
    def _merge_mode_changed_cb(self, checked):
        ''' merge mode selection change '''
        widget = self.sender()
        self.merge_type = widget.data

    @property
    def merge_type(self) -> MergeOperationType:
        return self.action_data.merge_type

    @merge_type.setter
    def merge_type(self, value : MergeOperationType):
        if self.action_data.merge_mode != value:
            self.action_data.merge_mode = value
            widget = self._merge_widgets_map[value]
            with QtCore.QSignalBlocker(widget):
                widget.setChecked(True)
            self._update_axis_widget()



    def get_axis_name(self, input_id):
        ''' gets the axis name based on the input # '''
        if input_id == 1:
            axis_name = "X"
        elif input_id == 2:
            axis_name = "Y"
        elif input_id == 3:
            axis_name = "Z"
        elif input_id == 4:
            axis_name = "RX"
        elif input_id == 5:
            axis_name = "RY"
        elif input_id == 6:
            axis_name = "RZ"
        elif input_id == 7:
            axis_name = "S1"
        elif input_id == 8:
            axis_name = "S2"
        else:
            axis_name = f"(unknown [{input_id}])"
        return axis_name

    def _create_info(self):
        ''' shows what device is currently selected '''
        state = gremlin.joystick_handling.VJoyUsageState()
        header  =  QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(header)
        box.addWidget(QtWidgets.QLabel(state._active_device_name))
        input_type = self.action_data.get_input_type() # self.action_data.hardware_input_type # state._active_device_input_type
        input_id = self.action_data.hardware_input_id  # state._active_device_input_id
        
        vjoy_device_id = self.action_data.vjoy_device_id
        vjoy_input_id = self.action_data.vjoy_input_id


        # command modes
        value = self.action_data.action_mode
        if value in (
                VjoyAction.VJoyDisableLocal,
                VjoyAction.VJoyDisableRemote,
                VjoyAction.VJoyEnableLocalOnly,
                VjoyAction.VJoyEnableRemoteOnly,
                VjoyAction.VJoyEnableLocalAndRemote,
                VjoyAction.VJoyEnableLocal,
                VjoyAction.VJoyEnableRemote,
                VjoyAction.VJoyToggleRemote,
                ):
            action_name = "GremlinEx Command"
        else:
            action_name = None

        match self.action_data.action_mode:
            case VjoyAction.VJoyAxisToButton:
                action_name = f"Vjoy device {vjoy_device_id} button {vjoy_input_id}"


        is_axis = self.action_data.input_is_axis()
        if is_axis:
            if not action_name:
                action_name = f"Vjoy device {vjoy_device_id} axis {vjoy_input_id} ({self.get_axis_name(vjoy_input_id)})"
            if input_type != InputType.JoystickAxis:
                name = f"Input axis -> {action_name}"
            else:
                axis_name = self.get_axis_name(input_id)
                name = f"Axis {input_id} ({axis_name}) -> {action_name}"
        elif input_type in VJoyRemapWidget.input_type_buttons:
            if not action_name:
                action_name = f"Vjoy device {vjoy_device_id} button {vjoy_input_id}"
            name = f"Button {input_id} -> {action_name}"
        elif input_type == InputType.JoystickHat:
            if not action_name:
                action_name = f"Vjoy device {vjoy_device_id} hat {vjoy_input_id}"
            name = f"Hat {input_id} -> {action_name}"
        else:
            if not action_name:
                action_name = f"Vjoy device {vjoy_device_id} button {vjoy_input_id}"
            name = f"Input trigger -> {action_name}"


        box.addWidget(QtWidgets.QLabel(name))
        box.addStretch()

        self.main_layout.addWidget(header)


    def set_width(self, widget, width, height = 22):
        widget.setFixedSize(width, height)


    def _create_override_input_type(self):
        ''' creates a manual input type override '''
        
        current_input_type = self.action_data.get_input_type()
        self._override_enabled_widget = QtWidgets.QCheckBox(f"Override input type ({InputType.to_display_name(current_input_type)})")
        input_type = self.action_data.override_input_type
        self._override_enabled_widget.setChecked(input_type is not None)
        self._override_enabled_widget.clicked.connect(self._update_override)
        self._override_axis_widget = gremlin.ui.ui_common.QDataRadioButton("Axis", InputType.JoystickAxis)
        self._override_axis_widget.clicked.connect(self._update_override_changed)
        self._override_button_widget = gremlin.ui.ui_common.QDataRadioButton("Button", InputType.JoystickButton)
        self._override_button_widget.clicked.connect(self._update_override_changed)
        self._override_hat_widget = gremlin.ui.ui_common.QDataRadioButton("Hat", InputType.JoystickHat)
        self._override_hat_widget.clicked.connect(self._update_override_changed)
        

        widgets = [self._override_enabled_widget, self._override_axis_widget, self._override_button_widget, self._override_hat_widget]

        self.container_override_widget, _= gremlin.ui.ui_common.getHContainer(widgets, min_height = self.container_height)
        self._update_override()
        self.main_layout.addWidget(self.container_override_widget)
    
    @QtCore.Slot()
    def _update_override(self):
        ''' updates the override widget '''
        enabled = self._override_enabled_widget.isChecked()
        self._override_axis_widget.setEnabled(enabled)
        self._override_button_widget.setEnabled(enabled)
        self._override_hat_widget.setEnabled(enabled)
        input_type = self.action_data.override_input_type
        with QtCore.QSignalBlocker(self._override_axis_widget):
            self._override_axis_widget.setChecked(input_type == InputType.JoystickAxis)
        with QtCore.QSignalBlocker(self._override_button_widget):
            self._override_button_widget.setChecked(input_type == InputType.JoystickButton)
        with QtCore.QSignalBlocker(self._override_hat_widget):
            self._override_hat_widget.setChecked(input_type == InputType.JoystickHat)

    @QtCore.Slot(bool)
    def _update_override_changed(self, checked):
        widget = self.sender()
        input_type = widget.data
        if self.action_data.override_input_type != input_type:
            self.action_data.override_input_type = input_type
            self._update_override()
        

    def _create_button_modes(self):
        ''' button output options '''
        self.button_rb_hold = gremlin.ui.ui_common.QDataRadioButton("Hold")
        self.button_rb_hold.setToolTip("Output will be pressed (on) while the input is in range.")
        self.button_rb_hold.data = ButtonOutputMode.Hold
        self.button_rb_hold.setChecked(self.action_data.button_mode == ButtonOutputMode.Hold)
        
        self.button_rb_pulse = gremlin.ui.ui_common.QDataRadioButton("Pulse")
        self.button_rb_pulse.setToolTip("Output will pulse on (pressed), wait a delay, and turn off (released) when the range is entered")
        self.button_rb_pulse.data = ButtonOutputMode.Pulse
        self.button_rb_pulse.setChecked(self.action_data.button_mode == ButtonOutputMode.Pulse)
        
        self.button_rb_press = gremlin.ui.ui_common.QDataRadioButton("Press")
        self.button_rb_press.setToolTip("Output will be turned on (pressed) and stay on if the range is entered.")
        self.button_rb_press.data = ButtonOutputMode.Press
        self.button_rb_press.setChecked(self.action_data.button_mode == ButtonOutputMode.Press)
        
        self.button_rb_release = gremlin.ui.ui_common.QDataRadioButton("Release")
        self.button_rb_release.setToolTip("Output will be turned off (released) and stay off is the range is entered.")
        self.button_rb_release.data = ButtonOutputMode.Release
        self.button_rb_release.setChecked(self.action_data.button_mode == ButtonOutputMode.Release)
        
        self.button_rb_noop = gremlin.ui.ui_common.QDataRadioButton("NoOp")
        self.button_rb_noop.setToolTip("No output.")
        self.button_rb_noop.data = ButtonOutputMode.NoOp
        self.button_rb_noop.setChecked(self.action_data.button_mode == ButtonOutputMode.NoOp)


        self.button_pulse_widget = gremlin.ui.ui_common.QDelayWidget()
        self.button_pulse_widget.setToolTip("Pulse Delay in milliseconds")
        self.button_pulse_widget.setValue(self.action_data.pulse_delay)
        self.button_pulse_widget.valueChanged.connect(self._pulse_value_changed)

        self.button_pulse_repeat_widget = gremlin.ui.ui_common.QDelayWidget()
        self.button_pulse_repeat_widget.setToolTip("Repeat delay in milliseconds")
        self.button_pulse_repeat_widget.setValue(self.action_data.pulse_repeat_delay)
        self.button_pulse_repeat_widget.valueChanged.connect(self._pulse_repeat_value_changed)

        self.button_repeat_widget = QtWidgets.QCheckBox("Pulse repeat")
        self.button_repeat_widget.setToolTip("When enabled, pulses are repeated while the input is triggered.")
        self.button_repeat_widget.setChecked(self.action_data.pulse_repeat)
        self.button_repeat_widget.clicked.connect(self._pulse_repeat_mode_changed)


        widgets = [
            self.button_rb_hold,
            self.button_rb_pulse,
            self.button_rb_press,
            self.button_rb_release,
            self.button_rb_noop,
            
        ]


        self.container_button_mode_widget, _ = gremlin.ui.ui_common.getHContainer(widgets,"Output Mode:", min_height = self.container_height)

        widgets = [
            self.button_pulse_widget,
            self.button_repeat_widget,
            self.button_pulse_repeat_widget,
        ]

        self.container_pulse_widget, _ = gremlin.ui.ui_common.getHContainer(widgets,"Pulse Options:", min_height = self.container_height)


        self.button_rb_hold.clicked.connect(self._button_mode_changed)
        self.button_rb_pulse.clicked.connect(self._button_mode_changed)
        self.button_rb_press.clicked.connect(self._button_mode_changed)
        self.button_rb_release.clicked.connect(self._button_mode_changed)
        self.button_rb_noop.clicked.connect(self._button_mode_changed)

        self.main_layout.addWidget(self.container_button_mode_widget)
        self.main_layout.addWidget(self.container_pulse_widget)
        

    @QtCore.Slot()
    def _button_mode_changed(self):
        widget = self.sender()
        mode = widget.data
        self.action_data.button_mode = mode
        self._update_ui()
        
        

    def _create_selector(self):
        ''' creates the button option panel '''


        self.selector_widget =  QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(self.selector_widget)
        grid.setColumnStretch(3,1)


        # behavior combo box  - lets the user select the output behavior
        self.cb_action_list = gremlin.ui.ui_common.NoWheelComboBox()
        self.cb_action_list.currentIndexChanged.connect(self._action_mode_changed)
        lbl = QtWidgets.QLabel("Mode:")

        row = 0
        grid.addWidget(lbl,row,0)
        grid.addWidget(self.cb_action_list, row, 1)

        self.action_label = QtWidgets.QLabel()
        grid.addWidget(self.action_label,row,2,1,3)


        # vjoy device selection - display vjoy target ID and vjoy target input - the input changes based on the behavior


        row += 1
        self.lbl_vjoy_device_selector = QtWidgets.QLabel("Device:")
        grid.addWidget(self.lbl_vjoy_device_selector,row,0)
        self.cb_vjoy_device_selector = gremlin.ui.ui_common.NoWheelComboBox()
        grid.addWidget(self.cb_vjoy_device_selector,row,1)
        for dev in self.action_data.vjoy_map.values():
            self.cb_vjoy_device_selector.addItem(dev.name, dev.vjoy_id)



        row += 1
        self.cb_vjoy_input_selector = gremlin.ui.ui_common.NoWheelComboBox()
        self.lbl_vjoy_input_selector = QtWidgets.QLabel("Output:")
        grid.addWidget(self.lbl_vjoy_input_selector,row,0)
        grid.addWidget(self.cb_vjoy_input_selector,row,1)


        warning_color = gremlin.ui.ui_common.Color.warningColor()
        self.warning_widget = gremlin.ui.ui_common.QIconLabel("ph.shield-warning-fill",use_qta=True,icon_color=QtGui.QColor(warning_color),text="", use_wrap=False)
        self.container_warning_widget,_ = gremlin.ui.ui_common.getHContainer(self.warning_widget, min_height = self.container_height)
 
        self.chkb_exec_on_release = QtWidgets.QCheckBox("Exec on release")
        self.chkb_exec_on_release.setToolTip("If enabled, the trigger will execute on input release")
        #self.chkb_exec_on_release.setStyleSheet(css)
        
        self.chkb_ignore_release = QtWidgets.QCheckBox("Ignore release")
        self.chkb_ignore_release.setToolTip("If enabled, the action will ignore release triggers (this is input and container dependent) - normal is OFF")
        self.chkb_ignore_release.setStyleSheet("")
        
        self.chkb_paired = QtWidgets.QCheckBox("Paired Group Member")
        #self.chkb_paired.setStyleSheet(css)
        self.chkb_paired.setToolTip("Paired groups with a remote client - when enabled - sends a remote signal and a local signal (this is seldom used).")
        


        self.chkb_auto_release_widget = QtWidgets.QCheckBox("Auto Release")
        self.chkb_auto_release_widget.setToolTip("Autorelease will trigger a release action when the input is released if the input does not issue one and that is the desired behavior.")
        self.chkb_auto_release_widget.setChecked(self.action_data.auto_release)

        self.start_widget = QtWidgets.QWidget()
        self.start_button_group = QtWidgets.QButtonGroup()

        start_layout = QtWidgets.QHBoxLayout(self.start_widget)
        self.rb_start_released = QtWidgets.QRadioButton("Released")
        self.rb_start_pressed = QtWidgets.QRadioButton("Pressed")

        self.start_button_group.addButton(self.rb_start_released)
        self.start_button_group.addButton(self.rb_start_pressed)

        self.start_button_group.setId(self.rb_start_released, 0)
        self.start_button_group.setId(self.rb_start_pressed, 1)

        if self.action_data.start_pressed:
            self.rb_start_pressed.setChecked(True)
        else:
            self.rb_start_released.setChecked(True)

        self.grid_visible_widget = QtWidgets.QCheckBox("Show button grid")
        self.grid_visible_widget.setToolTip("Sets the button grid visibility, use ctrl+ to enable/disable globally")
        self.grid_visible_widget.setChecked(self.action_data.grid_visible)
        self.grid_visible_widget.clicked.connect(self._grid_visible_cb)


        widgets = [
            "Start mode:",
            self.rb_start_released,
            self.rb_start_pressed,
            gremlin.ui.ui_common.QHorizontalSeparator(),
            self.chkb_exec_on_release,
            self.chkb_ignore_release,
            self.chkb_paired,
            self.chkb_auto_release_widget,
            gremlin.ui.ui_common.QHorizontalSeparator(),
            self.grid_visible_widget,

            ]   

        self.container_options_widget, _ = gremlin.ui.ui_common.getHContainer(widgets, min_height = self.container_height)

        

        # selector hooks
        self.cb_vjoy_device_selector.currentIndexChanged.connect(self._vjoy_device_id_changed)
        self.cb_vjoy_input_selector.currentIndexChanged.connect(self._vjoy_input_id_changed)

          # set axis range widget
        self.axis_range_container_widget = QtWidgets.QWidget()
        box = QtWidgets.QHBoxLayout(self.axis_range_container_widget)
        self.sb_button_range_low = gremlin.ui.ui_common.QFloatLineEdit()
        self.sb_button_range_low.setMinimum(-1.0)
        self.sb_button_range_low.setMaximum(1.0)
        self.sb_button_range_low.setDecimals(3)
        self.sb_button_range_high = gremlin.ui.ui_common.QFloatLineEdit()
        self.sb_button_range_high.setMinimum(-1.0)
        self.sb_button_range_high.setMaximum(1.0)
        self.sb_button_range_high.setDecimals(3)
        self.b_range_reset = QtWidgets.QPushButton("Reset")
        self.b_range_half = QtWidgets.QPushButton("Half")
        self.b_range_lhalf = QtWidgets.QPushButton("L-Half")
        self.b_range_hhalf = QtWidgets.QPushButton("H-Half")
        self.b_range_top = QtWidgets.QPushButton("Top")
        self.b_range_bottom = QtWidgets.QPushButton("Bot")


        box.addWidget(QtWidgets.QLabel("Range Min:"))
        box.addWidget(self.sb_button_range_low)
        box.addWidget(QtWidgets.QLabel("Max:"))
        box.addWidget(self.sb_button_range_high)
        box.addWidget(self.b_range_reset)
        box.addWidget(self.b_range_half)
        box.addWidget(self.b_range_lhalf)
        box.addWidget(self.b_range_hhalf)
        box.addWidget(self.b_range_bottom)
        box.addWidget(self.b_range_top)
        box.addStretch()

        # button to axis value widget
        self.target_value_container_widget = QtWidgets.QWidget()
        self.target_value_container_layout = QtWidgets.QHBoxLayout(self.target_value_container_widget)
        self.button_to_axis_value_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.button_to_axis_value_widget.setValue(self.action_data.target_value)
        self.button_to_axis_value_widget.valueChanged.connect(self._button_to_axis_value_changed)

        
        self.target_is_relative = QtWidgets.QCheckBox("Relative")
        self.target_is_relative.setToolTip("When enabled, the value is added to the current axis (relative value)")
        self.target_is_relative.setChecked(self.action_data.target_is_relative)
        self.target_is_relative.clicked.connect(self._target_relative_changed)


        self.target_value_container_layout.addWidget(QtWidgets.QLabel("Set Value:"))
        self.target_value_container_layout.addWidget(self.button_to_axis_value_widget)
        self.target_value_container_layout.addWidget(self.target_is_relative)
        self.target_value_container_layout.addStretch()

        self.main_layout.addWidget(self.selector_widget)
        self.main_layout.addWidget(self.container_options_widget)
        #self.main_layout.addWidget(self.pulse_widget)
        self.main_layout.addWidget(self.start_widget)
        self.main_layout.addWidget(self.axis_range_container_widget)
        self.main_layout.addWidget(self.target_value_container_widget)

        

        # hook events


        self.chkb_exec_on_release.clicked.connect(self._exec_on_release_changed)
        self.chkb_ignore_release.clicked.connect(self._ignore_release_changed)
        self.chkb_paired.clicked.connect(self._paired_changed)
        self.chkb_auto_release_widget.clicked.connect(self._autorelease_changed)
        
        
        self.start_button_group.buttonClicked.connect(self._start_changed)
        self.sb_button_range_low.valueChanged.connect(self._button_range_low_changed)
        self.sb_button_range_high.valueChanged.connect(self._button_range_high_changed)
        self.button_to_axis_value_widget.valueChanged.connect(self._button_to_axis_value_changed)


        self.b_range_reset.clicked.connect(self._b_range_reset_clicked)
        self.b_range_half.clicked.connect(self._b_range_half_clicked)
        self.b_range_lhalf.clicked.connect(self._b_range_lhalf_clicked)
        self.b_range_hhalf.clicked.connect(self._b_range_hhalf_clicked)
        self.b_range_bottom.clicked.connect(self._b_range_bot_clicked)
        self.b_range_top.clicked.connect(self._b_range_top_clicked)


    def setWarning(self, text):
        ''' updates warning'''
        self.warning_widget.setText(text)
        if self.warning_widget.parent(): self.warning_widget.setVisible(text is not None and len(text))

    def update_steps(self):
        ''' updates the stepped list widgets '''
        steps = len(self.action_data.target_step_list)
        enabled = steps > 0
        self.step_start_index_widget.setEnabled(enabled)
        self.step_start_value_widget.setEnabled(enabled)

        self.latched_device_widget.setEnabled(self.action_data._stepped_latched)

        index = self.step_start_index_widget.value()
        if steps > 0:
            index = gremlin.util.clamp(index, 1, steps)

            with QtCore.QSignalBlocker(self.step_start_index_widget):
                self.step_start_index_widget.setValue(index)
                self.step_start_index_widget.setRange(1, steps+1)
            self.action_data.target_step_list.sort()

            with QtCore.QSignalBlocker(self.step_list_widget):
                csv = gremlin.util.floatlist_to_csv(self.action_data.target_step_list, decimals = 3)
                self.step_list_widget.setText(csv)

            # updates individual step widgets and layout
            self._ensure_step_widgets()

            with QtCore.QSignalBlocker(self.step_count_widget):
                self.step_count_widget.setValue(steps)

            self.action_data : VjoyRemap
            if not self.action_data.target_step_start_index in self.action_data.target_step_list:
                # reset the default if no longer in the list
                self.action_data.target_step_start_index = 0

            self.step_start_value_widget.setValue(self.action_data.target_step_list[self.action_data.target_step_start_index])

            self.slider_widget.setTickMarks(self.action_data.target_step_list)

            self._update_start_value()



    def _create_step_widget(self, id, value):
        ''' creates a step widget for the step value '''
        widget = StepWidget(id, value)
        widget.valueChanged.connect(self._step_value_changed)
        widget.defaultChanged.connect(self._step_default_changed)
        widget.deleteRequested.connect(self._step_delete)
        return widget
    

    def _ensure_step_widgets(self):
        ''' ensures we have a widget for each defined step value '''
        widgets = []
        self.target_step_index_map.clear()
        bg = StepWidgetGroup()
        bg.clear()
        for index, value in enumerate(self.action_data.target_step_list):
            widget = self._create_step_widget(index, value)
            widgets.append((index, widget))

        for index, widget in widgets:
            self.target_step_index_map[index] = widget

        # redo the layout in sorted order if needed
        self._update_step_widget_layout()



    


    def _update_step_widget_layout(self):
        ''' ensures the step widgets appear in the step sort order '''
        gremlin.ui.ui_common.clear_layout(self.step_widget_layout)
        row = 0
        col = 0
        max_col = 5
        for index, widget in self.target_step_index_map.items():
            self.step_widget_layout.addWidget(widget, row, col)
            col+=1
            if col > max_col:
                row+=1
                col = 0

        
            
        

    @QtCore.Slot()
    def _add_step(self):
        ''' adds new step '''
        data = self.action_data.target_step_list
        count = len(data)
        if count >= 20:
            # syslog = logging.getLogger("system")
            syslog.error(f"VJOY: unable to add more than 20 steps.")
            return
        if count > 1:
            v1 = data[0]
            v2 = data[1]
        elif count == 0:
            v1 = -1
            v2 = 1
        elif count == 1:
            v1 = data[0]
            if v1 > -1:
                v2 = -1
            elif v1 < 1:
                v2 = 1

        value = (v1 + v2) / 2
        self.action_data.target_step_list.append(value)
        self.action_data.target_step_list.sort()
        self.update_steps()

    @QtCore.Slot()
    def _step_count_changed(self):
        ''' called when the count of steps changes '''
        import random
        target_count = self.step_count_widget.value()
        current_count = len(self.action_data.target_step_list)
        if target_count < current_count:
            # need fewer points
            while len(self.action_data.target_step_list) > target_count:
                self.action_data.target_step_list.pop()
        else:
            count = len(self.action_data.target_step_list)
            while count < target_count:
                value = random.randrange(-100,100) / 100
                while value in self.action_data.target_step_list:
                    value = random.randrange(-100,100) / 100
                
                self.action_data.target_step_list.append(value)
                count = len(self.action_data.target_step_list)

        self.update_steps()

    @QtCore.Slot(bool)
    def _step_direction_changed(self, checked):
        self.action_data.target_step_direction = -1 if checked else 1
        pass

    @QtCore.Slot(bool)
    def _step_latched_changed(self, checked):
        self.action_data._stepped_latched = checked
        self.update_steps()

    @QtCore.Slot()
    def _step_start_index_changed(self):
        index = self.step_start_index_widget.value()
        count = len(self.action_data.target_step_list)
        new_index = gremlin.util.clamp(index, 1, count)
        if new_index != index:
            with QtCore.QSignalBlocker(self.step_start_index_widget):
                self.step_start_index_widget.setValue(new_index)
            index = new_index
    
        self.action_data.target_step_start_index = index-1
        value = self.action_data.target_step_list[self.action_data.target_step_start_index]
        self.step_start_value_widget.setText(f"{value:0.3f}")
        self.update_steps()

    @QtCore.Slot()
    def _step_list_changed(self):
        steps = gremlin.util.csv_to_floatlist(self.step_list_widget.text())
        if steps is None:
            steps = []
        self.action_data.target_step_list = steps
        self.update_steps()


    @QtCore.Slot(int, float)
    def _step_value_changed(self, index : int, value: float):
        # reorder the widgets if the value changed

        self.action_data.target_step_list[index] = value
        self.action_data.target_step_list.sort()

        # re-order the widgets based on the sorted steps
        self.update_steps()
        

   

    @QtCore.Slot(int, bool)
    def _step_default_changed(self, index : int, flag: bool):
        if flag:
            self.action_data.target_step_start_index = index
            self._update_start_value()


    @QtCore.Slot(int)
    def _step_delete(self, index: int):
        ''' delete requested '''
        msgbox = gremlin.ui.ui_common.ConfirmBox(f"Delete step {index}?")
        result = msgbox.show()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            del self.action_data.target_step_list[index]
            self._ensure_step_widgets() # redo the layout
            self.slider_widget.setTickMarks(self.action_data.target_step_list)
    


    def _create_step_ui(self):
        ''' creates the axis step mode UI components '''
        # stepped output 

        self.target_step_index_map = {} # map of step index to step widget ID keyed by index in the step list

        self.container_stepped_widget = QtWidgets.QWidget()
        self.container_stepped_layout = QtWidgets.QVBoxLayout(self.container_stepped_widget)

        self.step_value_container_widget = QtWidgets.QWidget()
        self.step_value_container_layout = QtWidgets.QHBoxLayout(self.step_value_container_widget)

        self.progression_container_widget = QtWidgets.QWidget()
        self.progression_container_layout = QtWidgets.QHBoxLayout(self.progression_container_widget)

        self.step_start_index_widget = gremlin.ui.ui_common.QIntLineEdit()
        self.step_count_widget = gremlin.ui.ui_common.QIntLineEdit()
        self.step_count_widget.setRange(0,100)
        self.step_count_widget.valueChanged.connect(self._step_count_changed)
        self.step_start_value_widget = gremlin.ui.ui_common.QFloatLineEdit()
        self.step_start_value_widget.setReadOnly(True)
        value = self.action_data.target_step_list[self.action_data.target_step_start_index]
        self.step_start_value_widget.setValue(value)

        # self.step_direction_widget = QtWidgets.QCheckBox("Invert direction")
        # self.step_direction_widget.setToolTip("When set, inverts the direction of the stepping so up becomes down, and down becomes up.")
        # self.step_direction_widget.setChecked(self.action_data.target_step_direction == -1)
        # self.step_direction_widget.clicked.connect(self._step_direction_changed)
        
        self.step_latched_enabled_widget = QtWidgets.QCheckBox("Latch secondary input for reverse action")
        self.step_latched_enabled_widget.setToolTip("If enabled, allows binding of another input to trigger a down step")
        self.step_latched_enabled_widget.setChecked(self.action_data._stepped_latched)
        self.step_latched_enabled_widget.clicked.connect(self._step_latched_changed)


        direction = self.action_data.target_step_direction
        self_step_direction_up_widget = gremlin.ui.ui_common.QDataRadioButton("Up",data = 1)
        self_step_direction_up_widget.setChecked(direction == 1)
        self_step_direction_up_widget.clicked.connect(self._step_direction_changed)

        self_step_direction_down_widget = gremlin.ui.ui_common.QDataRadioButton("Down", data = -1)
        self_step_direction_down_widget.setChecked(direction == -1)
        self_step_direction_down_widget.clicked.connect(self._step_direction_changed)
        

        self.step_direction_widget, _ = gremlin.ui.ui_common.getHContainer([
            self_step_direction_up_widget,
            self_step_direction_down_widget
        ],"Step direction:", min_height = self.container_height)

        self.step_start_index_widget.setRange(1,100)
        self.step_start_index_widget.valueChanged.connect(self._step_start_index_changed)

        self.step_list_widget = gremlin.ui.ui_common.QDataLineEdit()
        self.step_list_widget.lostFocus.connect(self._step_list_changed)

        self.add_step_widget = QtWidgets.QPushButton("Add Step")
        self.add_step_widget.setToolTip("Adds a new step")
        self.add_step_widget.clicked.connect(self._add_step)

        self.slider_widget = gremlin.ui.qsliderwidget.QSliderWidget(object_name = f"Slider for VjoyWidget: {self.action_data.input_display_name}")
        self.slider_widget.setRange(-1,1)   
        self.slider_widget.setReadOnly(True)
        self.slider_widget.setDrawHandles(False)
        self.slider_widget.setMinimumWidth(200)
        self.slider_widget.setMarkerVisible(False)

        self.container_stepped_layout.addWidget(self.slider_widget)

        # self.step_value_container_layout.addWidget(QtWidgets.QLabel("Steps (CSV):"))
        # self.step_value_container_layout.addWidget(self.step_list_widget)

        self.normalize_widget = QtWidgets.QPushButton("Normalize")
        self.normalize_widget.setToolTip("Normalizes steps to be evenly spaced")
        self.normalize_widget.clicked.connect(self._normalize_steps)

        self.low_progression_widget = QtWidgets.QPushButton("Low")
        self.low_progression_widget.setToolTip("Steps follow a linear progression from the low range.  Most steps are in the lower half.")
        self.low_progression_widget.clicked.connect(self._low_progression_steps)

        self.high_progression_widget = QtWidgets.QPushButton("High")
        self.high_progression_widget.setToolTip("Steps follow a linear progression from the high range.  Most steps are in the higher half.")
        self.high_progression_widget.clicked.connect(self._high_progression_steps)

        self.cubic_progression_low_widget = QtWidgets.QPushButton("Geometric Low")
        self.cubic_progression_low_widget.setToolTip("Steps follow a geometric (log) progression.")
        self.cubic_progression_low_widget.clicked.connect(self._geometric_progression_steps_low)

        self.cubic_progression_high_widget = QtWidgets.QPushButton("Geometric High")
        self.cubic_progression_high_widget.setToolTip("Steps follow a geometric (log) progression.")
        self.cubic_progression_high_widget.clicked.connect(self._geometric_progression_steps_high)
        

        #self.step_value_container_layout.addWidget(self.grab_widget)
        self.step_value_container_layout.addWidget(self.add_step_widget)
        self.step_value_container_layout.addWidget(QtWidgets.QLabel("Start index:"))
        self.step_value_container_layout.addWidget(self.step_start_index_widget)
        self.step_value_container_layout.addWidget(QtWidgets.QLabel("Start value:"))
        self.step_value_container_layout.addWidget(self.step_start_value_widget)
        self.step_value_container_layout.addWidget(QtWidgets.QLabel("Steps:"))
        self.step_value_container_layout.addWidget(self.step_count_widget)
        self.step_value_container_layout.addWidget(self.step_direction_widget)
        
        self.step_value_container_layout.addStretch()

        self.progression_container_layout.addWidget(QtWidgets.QLabel("Distribution:"))
        self.progression_container_layout.addWidget(self.normalize_widget)
        self.progression_container_layout.addWidget(self.low_progression_widget)
        self.progression_container_layout.addWidget(self.high_progression_widget)
        self.progression_container_layout.addWidget(self.cubic_progression_low_widget)
        self.progression_container_layout.addWidget(self.cubic_progression_high_widget)
        self.progression_container_layout.addStretch()

        self.step_widget_container = QtWidgets.QWidget()
        self.step_widget_layout = QtWidgets.QGridLayout(self.step_widget_container)
        self.step_widget_layout.addWidget(QtWidgets.QWidget(),0,6)
        self.step_widget_layout.setColumnStretch(6,2)

        self.stepped_selector_device_widget = gremlin.ui.ui_common.NoWheelComboBox()
        self.stepped_selector_input_widget = gremlin.ui.ui_common.NoWheelComboBox()

        listen_widget = gremlin.ui.ui_common.Buttons.getListenWidget(callback = self._stepped_listen)

        self.latched_device_widget = QtWidgets.QWidget()
        device_layout = QtWidgets.QGridLayout(self.latched_device_widget)

        row = 0
        device_layout.addWidget(QtWidgets.QLabel("Down Device:"),row,0)
        device_layout.addWidget(self.stepped_selector_device_widget,row,1)
        device_layout.addWidget(listen_widget,row,3)
        device_layout.addWidget(QtWidgets.QLabel(" "),row,4)

        row+=1
        device_layout.addWidget(QtWidgets.QLabel("Down Input:"),row,0)
        device_layout.addWidget(self.stepped_selector_input_widget,row,1)
        device_layout.setColumnStretch(4,2)


        self.container_stepped_layout.addWidget(self.step_latched_enabled_widget)
        self.container_stepped_layout.addWidget(self.latched_device_widget)
        self.container_stepped_layout.addWidget(self.step_value_container_widget)
        self.container_stepped_layout.addWidget(self.progression_container_widget)
        self.container_stepped_layout.addWidget(self.step_widget_container)

        #self.container_stepped_layout.addWidget(self.container_stepped_widget)


        self.stepped_selector_device_widget.currentIndexChanged.connect(self._stepped_device_changed_cb)
        self.stepped_selector_input_widget.currentIndexChanged.connect(self._stepped_input_changed_cb)


        self.stepped_device_map = {} # holds the device information keyed by device_id (str)
        self.stepped_input_map = {} # holds the list of buttons for the given device by device_id(str)
        devices = sorted(joystick_handling.button_input_devices(),key=lambda x: x.name)

        # default device
        device_guid = self.action_data.hardware_device_guid if self.action_data.stepped_device_id is None else self.action_data.stepped_device_id
        device_index = None
        current_index = 0

        for dev in devices:
            self.stepped_device_map[dev.device_id] = dev
            button_list = {}
            for input_id in range(1, dev.button_count+1):
                if dev.device_guid == self.action_data.hardware_device_guid and \
                    input_id == self.action_data.hardware_input_id:
                    # skip self as a possible input
                    continue
                button_list[input_id] = f"Button {input_id}"

            if button_list:
                self.stepped_input_map[dev.device_id] = button_list
                self.stepped_selector_device_widget.addItem(dev.name, dev.device_id)
                if device_index is None and dev.device_id == device_guid:
                    device_index = current_index
                current_index +=1

        if device_index is not None:
            self.stepped_selector_device_widget.setCurrentIndex(device_index)

        
        self.main_layout.addWidget(self.container_stepped_widget)
        self._enable_axis_tracking()
        self.update_steps()


    def get_axis_value(self):
        ''' gets the current axis value'''
        #value = gremlin.joystick_handling.get_curved_axis(self.action_data.hardware_device_guid, self.action_data.hardware_input_id)
        value = self.action_data.get_filtered_axis_value()
        return value
    
    def _update_start_value(self):
        ''' updates the start value widget repeater '''
        index = self.action_data.target_step_start_index
        value = self.action_data.target_step_list[index]
        self.step_start_value_widget.setValue(value)


        # check the correct widget
        widget = self.target_step_index_map[index]
        widget.setDefault(True)
        

    @QtCore.Slot()
    def _normalize_steps(self):
        ''' normalizes the steps '''
        count = len(self.action_data.target_step_list)
        if count == 0:
            return
        elif count == 2:
            data = [-1,1]
        elif count == 1:
            data = [0]
        else:
            data = []
            interval = 2 / (count-1)
            x = -1
            for _ in range(count):
                data.append(x)
                x += interval
            

        self.action_data.target_step_list = data
        self.update_steps()

    @QtCore.Slot()
    def _low_progression_steps(self):
        count = len(self.action_data.target_step_list)
        if count == 0:
            return
        elif count == 2:
            data = [-1,1]
        elif count == 1:
            data = [0]
        else:
            data = []
            interval = 1
            x = 1
            for _ in range(count):
                data.append(x)
                x -= interval
                interval /= 2
        self.action_data.target_step_list = data
        self.update_steps()   

    @QtCore.Slot()
    def _high_progression_steps(self):
        count = len(self.action_data.target_step_list)
        if count == 0:
            return
        elif count == 2:
            data = [-1,1]
        elif count == 1:
            data = [0]
        else:
            data = []
            interval = 1
            x = -1
            for _ in range(count):
                data.append(x)
                x += interval
                interval /= 2
        self.action_data.target_step_list = data
        self.update_steps()   

    @QtCore.Slot()
    def _geometric_progression_steps_low(self):
        self._geometric_progression(False)

    
    @QtCore.Slot()
    def _geometric_progression_steps_high(self):
        self._geometric_progression(True)

    def _geometric_progression(self, inverted = False):
        import numpy as np
        count = len(self.action_data.target_step_list)
        if count == 0:
            return
        elif count == 2:
            data = [-1,1]
        elif count == 1:
            data = [0]
        else:
            data = []
            progression = np.geomspace(1,10,count)
            for n in progression:
                value = gremlin.util.scale_to_range(float(n), source_min = 1, source_max = 10, invert=inverted)
                
                data.append(value)
            data.sort()


        self.action_data.target_step_list = data
        self.update_steps()           

    @QtCore.Slot()
    def _grab_handler(self):
        ''' grab the min value from the axis position '''
        value = gremlin.joystick_handling.get_curved_axis(self.action_data.hardware_device_guid, self.action_data.hardware_input_id)
        if not value in self.action_data.target_step_list:
            self.action_data.target_step_list.append(value)
            self.action_data.target_step_list.sort()
            self._ensure_step_widgets()

    @QtCore.Slot()        
    def _stepped_listen(self):
        ''' listens for the button to use as the down step '''
        button_press_dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.JoystickButton],
            return_kb_event=False
        )

        button_press_dialog.item_selected.connect(self._update_button)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        button_press_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150
        )
        button_press_dialog.show()

    @QtCore.Slot()
    def _update_button(self, event : gremlin.event_handler.Event):
        ''' called when a button input is selected '''
        hardware_index = self.stepped_selector_device_widget.findData(event.device_id)
        self.stepped_selector_device_widget.setCurrentIndex(hardware_index)
        input_index = self.stepped_selector_input_widget.findData(event.identifier)
        self.stepped_selector_input_widget.setCurrentIndex(input_index)



    @QtCore.Slot()
    def _stepped_device_changed_cb(self):
        ''' stepped device changed '''
        index = self.stepped_selector_device_widget.currentIndex()
        device_id = self.stepped_selector_device_widget.itemData(index)
        active_input_id = self.action_data.stepped_input_id
        current_index = 0
        selected_input_index = None
        with QtCore.QSignalBlocker(self.stepped_selector_input_widget):
            self.stepped_selector_input_widget.clear()
            first_input_id = None
            for input_id, button_name in self.stepped_input_map[device_id].items():
                self.stepped_selector_input_widget.addItem(button_name, input_id)
                if first_input_id is None:
                    first_input_id = input_id
                if selected_input_index is None and input_id == active_input_id:
                    selected_input_index = current_index
                current_index +=1 

            if selected_input_index is not None:
                index = self.stepped_selector_input_widget.findData(selected_input_index)
                if index != -1:
                    self.stepped_selector_input_widget.setCurrentIndex(selected_input_index)
                else:
                    self.action_data.stepped_input_id = first_input_id
            else:
                self.action_data.stepped_input_id = first_input_id
                

        self.action_data.stepped_device_id = device_id
        
        

    @QtCore.Slot()
    def _stepped_input_changed_cb(self):
        ''' stepped input changed '''
        index = self.stepped_selector_input_widget.currentIndex()
        input_id = self.stepped_selector_input_widget.itemData(index)
        self.action_data.stepped_input_id = input_id
        # self.action_modified.emit()        

    def load_actions_from_input_type(self):
        ''' occurs when the type of input is changed '''
        with QtCore.QSignalBlocker(self.cb_action_list):
            self.cb_action_list.clear()

            actions = ()
            if self.action_data.input_is_axis():
                # axis can only set an axis
                actions = (VjoyAction.VJoyAxis, VjoyAction.VJoyAxisToButton, VjoyAction.VJoyMergeAxis)


            elif self.action_data.input_is_button():
                # various button modes
                actions = ( 
                            VjoyAction.VJoyButton,
                            VjoyAction.VJoyButtonPress,
                            VjoyAction.VJoyButtonRelease,
                            VjoyAction.VJoyPulse,
                            VjoyAction.VJoyToggle,
                            VjoyAction.VJoyInvertAxis,
                            VjoyAction.VJoySetAxis,
                            VjoyAction.VJoySetAxisStepped,
                            VjoyAction.VJoyRangeAxis,
                            VjoyAction.VJoyMergeAxis,
                            VjoyAction.VJoyEnableLocalOnly,
                            VjoyAction.VJoyEnableRemoteOnly,
                            VjoyAction.VJoyEnableLocal,
                            VjoyAction.VJoyEnableRemote,
                            VjoyAction.VJoyEnableLocalAndRemote,
                            VjoyAction.VJoyDisableLocal,
                            VjoyAction.VJoyDisableRemote,
                            VjoyAction.VJoyToggleRemote,
                            VjoyAction.VJoyEnablePairedRemote,
                            VjoyAction.VJoyDisablePairedRemote,

                )

            elif self.action_data.input_type == InputType.JoystickHat:
                # hat actions
                actions = [VjoyAction.VJoyHat, VjoyAction.VJoyHatToButton]

            else:
                log_sys_warn(f"VJOYREMAP: don't know what actions to load for input type: {self.action_data.input_type}")

            for action in actions:
                self.cb_action_list.addItem(VjoyAction.to_name(action), action)

    def _vjoy_device_id_changed(self, index):
        ''' occurs when the vjoy output device is changed '''
        with QtCore.QSignalBlocker(self.cb_vjoy_device_selector):
            device_id = self.cb_vjoy_device_selector.itemData(index)
            self.action_data.vjoy_device_id = device_id
            self._update_vjoy_device_input_list()
            self._update_hat_mapping()
            self.notify_device_changed()


    def _vjoy_input_id_changed(self, index):
        ''' occurs when the vjoy output input ID is changed '''
        with QtCore.QSignalBlocker(self.cb_vjoy_input_selector):
            input_id = self.cb_vjoy_input_selector.itemData(index)
            self.action_data.set_input_id(input_id)

            if self.is_button_mode:
                self.select_button(self.action_data.vjoy_device_id, input_id)

            #self._populate_grid(self.action_data.vjoy_device_id, input_id)
            self.notify_device_changed()

    def refresh_grid(self):
        ''' refreshes the grid '''
        self._populate_grid(self.action_data.vjoy_device_id, self.action_data.vjoy_input_id )

    def notify_device_changed(self):
        state = gremlin.joystick_handling.VJoyUsageState()
        el = gremlin.event_handler.EventListener()
        event = gremlin.event_handler.DeviceChangeEvent()
        event.device_guid = state._active_device_guid
        event.device_name = state._active_device_name
        event.device_input_type = self.action_data.input_type
        event.device_input_id = state._active_device_input_id
        event.vjoy_device_id = self.action_data.vjoy_device_id
        event.vjoy_input_id = self.action_data.vjoy_input_id
        event.source = self.action_data
        el.profile_device_changed.emit(event)
        el.icon_changed.emit(event)


    def _update_vjoy_device_input_list(self):
        ''' loads a list of valid outputs for the current vjoy device based on the mode '''
        with QtCore.QSignalBlocker(self.cb_vjoy_input_selector):

            self.cb_vjoy_input_selector.clear()
            input_type = self._get_selector_input_type()
            action_mode = self._get_action_mode()
            self.setWarning(None) # clear any warnings

            if not self.action_data.vjoy_device_id in self.action_data.vjoy_map:
                self.action_data.refresh_vjoy()
                if not self.action_data.vjoy_device_id in self.action_data.vjoy_map:
                    self.setWarning(f"VJOY configuration has changed and GremlinEx is unable to find the requested Vjoy device # {self.action_data.vjoy_device_id}")
                    return


            dev = self.action_data.vjoy_map[self.action_data.vjoy_device_id]
            if action_mode in (VjoyAction.VJoySetAxis, VjoyAction.VJoySetAxisStepped, VjoyAction.VJoyRangeAxis, VjoyAction.VJoyAxis, VjoyAction.VJoyInvertAxis, VjoyAction.VJoyMergeAxis):
                count = dev.axis_count
                for id in range(1, count+1):
                    axis_name = dev.axis_names[id-1]
                    self.cb_vjoy_input_selector.addItem(f"Axis {axis_name}",id)
                    #self.cb_vjoy_input_selector.addItem(f"Axis {id} ({self.get_axis_name(id)})",id)
            elif input_type in VJoyRemapWidget.input_type_buttons or action_mode in (VjoyAction.VJoyButtonPress, VjoyAction.VJoyButtonRelease, VjoyAction.VJoyPulse, VjoyAction.VJoyToggle, VjoyAction.VJoyAxisToButton, VjoyAction.VJoyHatToButton):
                count = dev.button_count
                for id in range(1, count+1):
                    self.cb_vjoy_input_selector.addItem(f"Button {id}",id)
                input_id = self.action_data.vjoy_input_id
                if input_id < 1 or input_id > count:
                    self.setWarning(f"VJOY configuration has changed and GremlinEx is unable to find the requested Vjoy button # {input_id}")
                    return
            elif input_type == InputType.JoystickHat:
                count = dev.hat_count
                for id in range(1, count+1):
                    self.cb_vjoy_input_selector.addItem(f"Hat {id}",id)
                input_id = self.action_data.vjoy_input_id
                if input_id < 1 or input_id > count:
                    self.setWarning(f"VJOY configuration has changed and GremlinEx is unable to find the requested Vjoy hat # {input_id}")
                    return
            else:
                # keyboard, latched keyboard, midi and OSC
                pass

            index = self.cb_vjoy_input_selector.findData(self.action_data.vjoy_input_id)
            if index != -1:
                self.cb_vjoy_input_selector.setCurrentIndex(index)
            self._populate_grid(self.action_data.vjoy_device_id, self.action_data.vjoy_input_id)


    @QtCore.Slot(float)
    def _target_value_changed(self, value):
        ''' called when the value box changes '''
        if value.isnumeric():
            value = float(value)
            self.action_data.target_value = value
            self.target_value_valid = True
        else:
            self.target_value_valid = False


    @QtCore.Slot(bool)
    def _target_relative_changed(self, checked):
        self.action_data.target_is_relative = checked

    def _update_ui(self):
        ''' updates ui based on the current action requested to show/hide needed components '''

        if not self._ui_loaded:
            return

        action_data = self.action_data

        action = action_data.action_mode
        input_type = action_data.input_type

        start_value_enabled = action_data.axis_start_value_enabled
        axis_visible = False
        pulse_visible = False
        repeat_visible = self.action_data.pulse_repeat
        start_visible = False
        grid_visible = False
        show_grid_visible = True
        output_range_visible = False
        button_range_visible = False
        output_mode_visible = False # output mode for button output
        output_curve_visible = False
        
        override_visible = False
        relative_visible = False

        hat_visible = False
        input_selector_visible = True

        exec_on_release_visible = False
        paired_visible = False
        merge_visible =  False

        stepped_visible = False
        reverse_visible = False

        self.chkb_auto_release_widget.setVisible(input_type in (InputType.KeyboardLatched, InputType.Keyboard, InputType.Midi, InputType.OpenSoundControl))


        is_axis = self.action_data.input_is_axis() #input_type == InputType.JoystickAxis

        if is_axis:

            grid_visible = action == VjoyAction.VJoyAxisToButton
            output_range_visible = action == VjoyAction.VJoyRangeAxis
            button_range_visible = action == VjoyAction.VJoyAxisToButton
            pulse_visible = self.action_data.button_mode == ButtonOutputMode.Pulse
            
            axis_visible = not (grid_visible or output_range_visible) # or hardware_widget_visible)
            merge_visible = action == VjoyAction.VJoyMergeAxis and axis_visible
            reverse_visible = True
            relative_visible = self.action_data.axis_mode == "relative"
            output_curve_visible = action in (VjoyAction.VJoyAxis, VjoyAction.VJoyMergeAxis, VjoyAction.VJoyRangeAxis)

        elif input_type in VJoyRemapWidget.input_type_buttons:
            pulse_visible = action == VjoyAction.VJoyPulse
            start_visible = action in (VjoyAction.VJoyButtonPress, VjoyAction.VJoyButtonRelease)
            if action in (VjoyAction.VJoyPulse, VjoyAction.VJoyButtonPress, VjoyAction.VJoyToggle, VjoyAction.VJoyButtonRelease):
                grid_visible = True
                start_visible = True
            paired_visible = action == VjoyAction.VJoyButtonPress
            exec_on_release_visible =  action_data.input_type in VJoyRemapWidget.input_type_buttons
            
        elif input_type == InputType.JoystickHat:
            if action == VjoyAction.VJoyHatToButton:
                grid_visible = False
                hat_visible = True
                show_grid_visible = False
            start_visible = True
            input_selector_visible = not hat_visible
            




        match action:
            case VjoyAction.VJoyAxis:
                output_mode_visible = True
            case VjoyAction.VJoyRangeAxis:
                grid_visible = False
            case VjoyAction.VJoySetAxis:
                output_range_visible = False
                relative_visible = True
                output_mode_visible = True
            case VjoyAction.VJoySetAxisStepped:
                output_range_visible
                grid_visible = False
                stepped_visible = True
            case VjoyAction.VJoyAxisToButton:
                output_range_visible = False
                start_visible = True
                grid_visible = True
                
            case VjoyAction.VJoyPulse:
                pulse_visible = True
                


        absolute_visible = not relative_visible

        is_command = VjoyAction.is_command(action)
        selector_visible = not is_command

        button_to_axis_visible = action == VjoyAction.VJoySetAxis
        axis_steps_visible = action == VjoyAction.VJoySetAxisStepped

        grid_visible = grid_visible and self.action_data.grid_visible

        #self.pulse_widget.setVisible(pulse_visible)
        self.start_widget.setVisible(start_visible)
        self.grid_visible_widget.setVisible(show_grid_visible)

        if self.button_grid_widget:
            self.button_grid_widget.setVisible(grid_visible)
        if self.container_axis_widget:
            self.container_axis_widget.setVisible(axis_visible)

        # merge axis options
        if self._merge_enabled:
            self.container_merge_widget.setVisible(merge_visible)

        self.container_stepped_widget.setVisible(stepped_visible)

        # self.hardware_input_container_widget.setVisible(hardware_widget_visible)
        self.axis_range_container_widget.setVisible(output_range_visible)
        self.chkb_exec_on_release.setVisible(exec_on_release_visible)
        self.chkb_paired.setVisible(paired_visible)
        self.target_value_container_widget.setVisible(button_to_axis_visible)
        self.step_value_container_widget.setVisible(axis_steps_visible)

        self.lbl_vjoy_device_selector.setVisible(selector_visible)
        self.cb_vjoy_device_selector.setVisible(selector_visible)
        self.cb_vjoy_input_selector.setVisible(selector_visible)
        self.lbl_vjoy_input_selector.setVisible(selector_visible)

        self.is_button_mode = grid_visible

        self.action_label.setText(VjoyAction.to_description(action))

        self.button_grid_widget.setVisible(self.action_data.grid_visible)
        self.button_grid_widget.setVisible(grid_visible)

        self.container_hat_widget.setVisible(hat_visible)

        self.cb_vjoy_input_selector.setVisible(input_selector_visible)
        self.lbl_vjoy_input_selector.setVisible(input_selector_visible)

        self.sb_start_value.setEnabled(start_value_enabled)

        self.container_axis_to_button_range_widget.setVisible(button_range_visible)
        self.container_button_mode_widget.setVisible(button_range_visible)
        #self.container_absolute_widget.setVisible(absolute_visible)
        self.container_relative_widget.setVisible(relative_visible)
        self.container_output_range_widget.setVisible(output_range_visible)
        self.container_output_curve_widget.setVisible(output_curve_visible)
        self.container_output_mode_widget.setVisible(output_mode_visible)
        self.container_reverse_widget.setVisible(reverse_visible)
        self.container_override_widget.setVisible(override_visible)

        self.container_pulse_widget.setVisible(pulse_visible)
        self.button_pulse_widget.setVisible(pulse_visible)
        self.button_pulse_repeat_widget.setVisible(repeat_visible)
        



    def _action_mode_changed(self, index):
        ''' called when the drop down value changes '''
        with QtCore.QSignalBlocker(self.cb_action_list):
            action : VjoyAction = self.cb_action_list.itemData(index)
            self.action_data.action_mode = action
            self.action_data.input_id = self.action_data.get_input_id()
            self._update_ui()
            self._update_vjoy_device_input_list()
            self._update_repeater()
            self.notify_device_changed()

    def _get_action_mode(self):
        ''' returns the action mode '''
        index = self.cb_action_list.currentIndex()
        action = self.cb_action_list.itemData(index)
        return action

    @QtCore.Slot(int)
    def _pulse_value_changed(self, value):
        ''' called when the pulse value changes '''
        if value >= 0:
            self.action_data.pulse_delay = value

    @QtCore.Slot(int)
    def _pulse_repeat_value_changed(self, value):
        ''' called when the pulse value changes '''
        if value >= 0:
            self.action_data.pulse_repeat_delay = value            


    def _start_changed(self, rb):
        ''' called when the start mode is changed '''
        id = self.start_button_group.checkedId()
        self.action_data.start_pressed = id == 1



    def _create_input_grid(self):
        ''' create a grid of buttons for easy selection'''

        if not self.action_data.vjoy_device_id in self.action_data.vjoy_map:
                self.action_data.refresh_vjoy()
                if not self.action_data.vjoy_device_id in self.action_data.vjoy_map:
                    gremlin.ui.ui_common.MessageBox(prompt=f"VJOY configuration has changed and GremlinEx is unable to find the requested Vjoy device # {self.action_data.vjoy_device_id}")
                    return

       
        self.button_grid_widget = QtWidgets.QWidget()


        # link all radio buttons
        self.button_group = QtWidgets.QButtonGroup()
        self.button_group.buttonClicked.connect(self._select_changed)
        self.icon_map = {}

        self.active_id = -1


        vjoy_device_id = self.action_data.vjoy_device_id
        input_type = self._get_selector_input_type()
        dev = self.action_data.vjoy_map[vjoy_device_id]
        count = dev.button_count
        grid = QtWidgets.QGridLayout(self.button_grid_widget)
        grid.setSpacing(2)
        self.remap_type_layout = grid

        max_col = 16
        col = 0
        row = 0

        vjoy_device_id = dev.vjoy_id
        input_type = self.action_data.input_type


        for id in range(1, count+1):
            # container for the vertical box
            v_cont = QtWidgets.QWidget()
            #v_cont.setFixedWidth(32)
            v_box = QtWidgets.QVBoxLayout(v_cont)
            v_box.setContentsMargins(0,0,0,5)
            v_box.setAlignment(QtCore.Qt.AlignCenter)

            # line 1
            h_cont = QtWidgets.QWidget()
            h_cont.setFixedWidth(36)
            h_box = QtWidgets.QHBoxLayout(h_cont)
            h_box.setContentsMargins(0,0,0,0)
            h_box.setAlignment(QtCore.Qt.AlignCenter)
            cb = gremlin.ui.ui_common.QDataRadioButton()

            self.button_group.addButton(cb)
            self.button_group.setId(cb, id)
            cb.data = id # data has the button id

            name = str(id)
            h_box.addWidget(cb)
            v_box.addWidget(h_cont)

            # line 2
            line2_cont = GridClickWidget(vjoy_device_id, input_type, id)
            line2_cont.setFixedWidth(36)
            h_box = QtWidgets.QHBoxLayout(line2_cont)
            h_box.setContentsMargins(0,0,0,0)
            h_box.setSpacing(0)


            icon_lbl = QtWidgets.QLabel()

            lbl = QtWidgets.QLabel(name)
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)


            self.icon_map[id] = icon_lbl

            h_box.addWidget(icon_lbl)
            h_box.addWidget(lbl)
            v_box.addWidget(line2_cont)

            line2_cont.clicked.connect(self._grid_button_clicked)


            grid.addWidget(v_cont, row, col)
            col+=1
            if col == max_col:
                row+=1
                col=0

        self.main_layout.addWidget(self.button_grid_widget)


    @QtCore.Slot(bool)
    def _grid_visible_cb(self, checked):
        self.action_data.grid_visible = checked
        self._update_ui()

        el = gremlin.event_handler.EventListener()
        if el.get_control_state():
            veh = gremlin.event_handler.VjoyRemapEventHandler()
            veh.grid_visible_changed.emit(checked)

    @QtCore.Slot(bool)
    def grid_visible_changed(self, visible):
        ''' global grid visible change event '''
        self.action_data.grid_visible = visible
        self._update_ui()


    @QtCore.Slot()
    def _grid_button_clicked(self):
        sender = self.sender()
        vjoy_device_id = sender.vjoy_device_id
        input_type = sender.input_type
        vjoy_input_id = sender.vjoy_input_id

        popup = GridPopupWindow(vjoy_device_id, input_type, vjoy_input_id)
        popup.exec()


    def select_button(self, vjoy_id, button_id, emit = False):
        ''' selects a button '''


        if self.active_id != -1:
            # clear the old button if it was previously selected
            self.usage_state.set_usage_state(vjoy_id, self.active_id, state = False, action = self.action_data, emit = False)

        if self.active_id == button_id:
            # already selected
            return

        # set the new
        self.active_id = button_id
        self.action_data.set_input_id(button_id)

        # update the selector
        with QtCore.QSignalBlocker(self.cb_vjoy_input_selector):
            self.cb_vjoy_input_selector.setCurrentIndex(button_id-1)

        # update the grid
        if button_id in self._grid_widgets:
            cb = self._grid_widgets[button_id]
            with QtCore.QSignalBlocker(cb):
                cb.setChecked(True)

        self.usage_state.set_usage_state(vjoy_id, self.active_id, state = True, action = self.action_data, emit=True)

        # update the UI when a state change occurs
        if emit:
            self.notify_device_changed()


    def _select_changed(self, rb):
        # called when a button is toggled
        vjoy_id = self.action_data.vjoy_device_id
        button_id = self.button_group.checkedId()
        self.select_button(vjoy_id, button_id)



    def _populate_ui(self):
        """Populates the UI components."""
        # Get the appropriate vjoy device identifier
        vjoy_dev_id = 0

        #log_sys(f"populate vjoy data for action id: {self.action_data.action_id}  action mode: {self.action_data.action_mode}  vjoy: {self.action_data.vjoy_device_id}")
        if self.action_data.vjoy_device_id not in [0, None]:
            vjoy_dev_id = self.action_data.vjoy_device_id

        # Get the input type which can change depending on the container used
        input_type = self.action_data.input_type


        if self.action_data.parent.tag == "hat_buttons":
            input_type = InputType.JoystickButton

        # Handle obscure bug which causes the action_data to contain no
        # input_type information
        if input_type is None:
            input_type = InputType.JoystickButton
            syslog.warning("None as input type encountered")

        # If no valid input item is selected get the next unused one
        if self.action_data.vjoy_input_id in [0, None]:
            free_inputs = self._get_profile_root().list_unused_vjoy_inputs()

            input_name = self.type_to_name_map[input_type].lower()
            input_type = self.name_to_type_map[input_name.capitalize()]
            if vjoy_dev_id == 0:
                vjoy_dev_id = sorted(free_inputs.keys())[0]
            input_list = free_inputs[vjoy_dev_id][input_name]
            # If we have an unused item use it, otherwise use the first one
            if len(input_list) > 0:
                vjoy_input_id = input_list[0]
            else:
                vjoy_input_id = 1
        # If a valid input item is present use it
        else:
            vjoy_input_id = self.action_data.vjoy_input_id

        is_button_mode = False
        button_id = None



        try:
            with QtCore.QSignalBlocker(self.cb_vjoy_device_selector):
                index = self.cb_vjoy_device_selector.findData(vjoy_dev_id)
                if index != -1:
                    self.cb_vjoy_device_selector.setCurrentIndex(index)
            with QtCore.QSignalBlocker(self.cb_vjoy_input_selector):
                index = self.cb_vjoy_input_selector.findData(vjoy_input_id)
                if index != -1:
                    self.cb_vjoy_input_selector.setCurrentIndex(index)


            index = self.cb_action_list.findData(self.action_data.action_mode)
            if index == -1:
                #log_sys_warn(f"Mode not found in drop down: {self.action_data.action_mode.name} - resetting to default mode")
                self.action_data.action_mode = self.cb_action_list.itemData(0)
                index = 0
            else:
                self.cb_action_list.setCurrentIndex(index)

            is_axis = self._is_axis
            if is_axis and self.action_data.action_mode == VjoyAction.VJoyAxis:

                with QtCore.QSignalBlocker(self.reverse_checkbox):
                    self.reverse_checkbox.setChecked(self.action_data.reverse)

                with QtCore.QSignalBlocker(self.absolute_checkbox):
                    with QtCore.QSignalBlocker(self.relative_checkbox):
                        if self.action_data.axis_mode == "absolute":
                            self.absolute_checkbox.setChecked(True)
                        else:
                            self.relative_checkbox.setChecked(True)

                with QtCore.QSignalBlocker(self.sb_start_value):
                    self.sb_start_value.setValue(self.action_data.axis_start_value)

                with QtCore.QSignalBlocker(self.relative_scaling_widget):
                    self.relative_scaling_widget.setValue(self.action_data.axis_scaling)

            elif self.action_data.input_type in VJoyRemapWidget.input_type_buttons:
                is_button_mode = True

            if self.action_data.action_mode == VjoyAction.VJoyAxisToButton:
                is_button_mode = True
                with QtCore.QSignalBlocker(self.sb_button_range_low):
                    self.sb_button_range_low.setValue(self.action_data.button_range_min)
                with QtCore.QSignalBlocker(self.sb_button_range_high):
                    self.sb_button_range_high.setValue(self.action_data.button_range_max)

                with QtCore.QSignalBlocker(self.button_to_axis_value_widget):
                    self.button_to_axis_value_widget.setValue(self.action_data.target_value)

            if is_button_mode:
                #self.pulse_widget.setValue(self.action_data.pulse_delay)
                self.button_pulse_widget.setValue(self.action_data.pulse_delay)
                if self.action_data.start_pressed:
                    self.rb_start_pressed.setChecked(True)
                else:
                    self.rb_start_released.setChecked(True)


                with QtCore.QSignalBlocker(self.sb_button_range_low):
                    self.sb_button_range_low.setValue(self.action_data.button_range_min)

                with QtCore.QSignalBlocker(self.sb_button_range_high):
                    self.sb_button_range_high.setValue(self.action_data.button_range_max)

                with QtCore.QSignalBlocker(self.chkb_exec_on_release):
                    self.chkb_exec_on_release.setChecked(self.action_data.exec_on_release)

                with QtCore.QSignalBlocker(self.chkb_exec_on_release):
                    self.chkb_ignore_release.setChecked(self.action_data.ignore_release)                    

                with QtCore.QSignalBlocker(self.chkb_paired):
                    self.chkb_paired.setChecked(self.action_data.paired)





            # # populate hardware devices if in merge mode
            # self._populate_hardware()
            # self._populate_hardware_axis()

            # update based on current mode

            self._populate_grid(vjoy_dev_id, button_id)
            self._update_vjoy_device_input_list()


            if is_button_mode:
                self.select_button(vjoy_dev_id, vjoy_input_id, emit = False)

            self._update_ui()

        except gremlin.error.GremlinError as e:
            util.display_error(
                f"A needed vJoy device is not accessible: {e}\n\n" +
                "Default values have been set for the input, but they are "
                "not what has been specified."
            )
            syslog.error(str(e))

    @QtCore.Slot(bool)
    def _axis_reverse_changed(self, checked):
        self.action_data.reverse = checked

    @QtCore.Slot()
    def _axis_mode_changed(self):
        self.action_data.axis_mode = 'absolute' if self.absolute_checkbox.isChecked() else "relative"
        self._update_ui()

    @QtCore.Slot()
    def _axis_scaling_changed(self):
        self.action_data.axis_scaling = self.relative_scaling_widget.value()

    @QtCore.Slot()
    def _axis_range_low_changed(self):
        self.action_data.output_range_min = self.sb_axis_range_low_widget.value()
        self._update_range_text()

    @QtCore.Slot(bool)
    def _axis_start_value_enabled(self, checked):
        self.action_data.axis_start_value_enabled = checked
        self._update_ui()


    @QtCore.Slot()
    def _axis_range_high_changed(self):
        self.action_data.output_range_max = self.sb_axis_range_high_widget.value()
        self._update_range_text()

    @QtCore.Slot()
    def _axis_start_value_changed(self):
        self.action_data.axis_start_value = self.sb_start_value.value()

    @QtCore.Slot()
    def _button_range_low_changed(self):
        self.action_data.button_range_min = self.sb_button_range_low.value()

    @QtCore.Slot()
    def _button_range_high_changed(self):
        self.action_data.button_range_max = self.sb_button_range_high.value()

    @QtCore.Slot()
    def _button_to_axis_value_changed(self):
        self.action_data.target_value = self.button_to_axis_value_widget.value()
    
    @QtCore.Slot()
    def _b_range_reset_clicked(self, value):
        self.sb_button_range_low.setValue(-1.0)
        self.sb_button_range_high.setValue(1.0)

    @QtCore.Slot()
    def _b_range_half_clicked(self, value):
        self.sb_button_range_low.setValue(-0.5)
        self.sb_button_range_high.setValue(0.5)

    @QtCore.Slot()
    def _b_range_lhalf_clicked(self, value):
        self.sb_button_range_low.setValue(-1.0)
        self.sb_button_range_high.setValue(0.0)

    @QtCore.Slot()
    def _b_range_hhalf_clicked(self, value):
        self.sb_button_range_low.setValue(0.0)
        self.sb_button_range_high.setValue(1.0)

    @QtCore.Slot()
    def _b_range_bot_clicked(self):
        self.sb_button_range_low.setValue(-1.0)
        self.sb_button_range_high.setValue(-0.75)

    @QtCore.Slot()
    def _b_range_top_clicked(self):
        self.sb_button_range_low.setValue(0.75)
        self.sb_button_range_high.setValue(1.0)

    @QtCore.Slot()
    def _b_min_start_value_clicked(self):
        self.sb_start_value.setValue(-1.0)

    @QtCore.Slot()
    def _b_center_start_value_clicked(self):
        self.sb_start_value.setValue(0.0)

    @QtCore.Slot()
    def _b_max_start_value_clicked(self):
        self.sb_start_value.setValue(1.0)

    @QtCore.Slot(bool)
    def _exec_on_release_changed(self, checked):
        self.action_data.exec_on_release = checked

    @QtCore.Slot(bool)
    def _ignore_release_changed(self, checked):
        self.action_data.ignore_release = checked

    @QtCore.Slot(bool)
    def _paired_changed(self, checked):
        self.action_data.paired = checked # self.chkb_paired.isChecked()

    @QtCore.Slot(bool)
    def _autorelease_changed(self, checked):
        self.action_data.auto_release = checked


    def _populate_grid(self, device_id, button_id):
        ''' updates the usage grid based on current VJOY mappings '''

        used_pixmap = load_pixmap("used.png")
        unused_pixmap = load_pixmap("unused.png")
        self._grid_widgets = {}

        for cb in self.button_group.buttons():
            id = self.button_group.id(cb)
            self._grid_widgets[id] = cb

            used = self.usage_state.get_usage_state(device_id,id)

            if id == button_id:
                with QtCore.QSignalBlocker(cb):
                    cb.setChecked(True)

            lbl = self.icon_map[id]
            lbl.setPixmap(used_pixmap if used else unused_pixmap)





class VJoyRemapFunctor(gremlin.base_conditions.AbstractFunctor):

    """Executes a remap action when called."""

    def findMainWindow(self):
        # Global function to find the (open) QMainWindow in application
        app = QtWidgets.QApplication.instance()
        for widget in app.topLevelWidgets():
            if isinstance(widget, QtWidgets.QMainWindow):
                return widget
        return None

    def __init__(self, action_data : VjoyRemap, parent = None):
        super().__init__(action_data, parent)
        self.verbose = gremlin.config.Configuration().verbose_mode_vjoy
        self.vjoy_device_id = action_data.vjoy_device_id
        self.vjoy_input_id = action_data.vjoy_input_id
        self.input_type = action_data.get_input_type()
        self.axis_mode = action_data.axis_mode
        self.axis_scaling = action_data.axis_scaling
        self.action_mode = action_data.action_mode
        self.pulse_delay = action_data.pulse_delay
        self.start_pressed = action_data.start_pressed
        self.target_value = action_data.target_value
        self.target_is_relative = action_data.target_is_relative
        self.target_value_valid = action_data.target_value_valid
        self.step_index = action_data.target_step_start_index
        v1 = action_data.button_range_min
        v2 = action_data.button_range_max
        if v1 > v2:
                # swap range so v1 < v2
                v1,v2 = v2, v1
        self.range_low = v1
        self.range_high = v2


        self.exec_on_release = action_data.exec_on_release
        self.paired = action_data.paired

        self.needs_auto_release = self._check_for_auto_release(action_data)
        if self.action_data.get_input_type() in (InputType.Keyboard, InputType.KeyboardLatched, InputType.Midi, InputType.OpenSoundControl):
            self.action_data.auto_release = self.action_data.auto_release or self.action_data.auto_release
        self.thread_running = False
        self.should_stop_thread = False
        self.thread_last_update = time.time()
        self.thread = None
        self.axis_delta_value = 0.0
        self.axis_value = 0.0
        self.axis_start_value = action_data.axis_start_value
        self.curve_actions = None # list of curve actions that apply to our input

        self.remote_client = input_devices.remote_client
        self.hat_position = (0,0)
        self.in_range = False # true when in axis to button mode and the axis was in range
        self.lock = threading.Lock()
        
        self.pulse_worker_map = {}  # map of (device_id, input_id) to pulse worker object

        


    def getCurveActions(self):
        ''' finds curve action siblings to this remap action '''
        actions = []
        nodes = []
        for node in self.getSiblings():
            if gremlin.base_profile._is_curve_tag(node.action.tag): 
                nodes.append(node)


        # sort the list in reverse priority order (highest prority runs first)
        if nodes:
            nodes.sort(key = lambda x: x.priority)
            nodes.reverse()
            for node in nodes:
                action = node.action
                actions.append(action)
        return actions

    def getCurveData(self, event, value):
        ''' returns active curve data that applies to the container through included response curve actions '''
        actions = self.getCurveActions()
        curves = []
        if actions:
            for action in actions:
                if action.curve_data:
                    # see if the curve should apply
                    if self.shouldExecute(event, value, action):
                        curves.append(action.curve_data)

        # add self
        if self.action_data.curve_data is not None:
            curves.append(self.action_data.curve_data)

        return curves

    def _convert_condition(self, condition):
        ''' converts a base condition to an action condition '''
        if isinstance(condition, gremlin.base_conditions.KeyboardCondition):
                return gremlin.actions.KeyboardCondition(
                        condition.scan_code,
                        condition.is_extended,
                        condition.comparison
                    )

        elif isinstance(condition, gremlin.base_conditions.JoystickCondition):
            return gremlin.actions.JoystickCondition(condition)

        elif isinstance(condition, gremlin.base_conditions.VJoyCondition):
            return gremlin.actions.VJoyCondition(condition)

        elif isinstance(condition, gremlin.base_conditions.InputActionCondition):
            return gremlin.actions.InputActionCondition(condition.comparison)

        assert False, f"Invalid base condition to convert: {type(condition).__name__}"


    def _create_activation_condition(self, activation_condition, target):
        """Creates activation condition objects base on the given data.

        :param activation_condition data about activation condition to be
            used in order to generate executable nodes
        """
        conditions = []
        for condition in activation_condition.conditions:
            if isinstance(condition, gremlin.base_conditions.ActivationCondition):
                for sub_condition in condition.conditions:
                    conditions.append(self._convert_condition(sub_condition))
            else:
                conditions.append(self._convert_condition(condition))

        return gremlin.actions.ActivationCondition(
            conditions,
            activation_condition.rule,
            target
        )

    def shouldExecute(self, event, value, action) -> bool:
        ''' determines if the given action should execute or not: returns True if the condition is satisfied '''

        activation_condition : gremlin.actions.ActivationCondition =  action.activation_condition
        if activation_condition is None or not activation_condition.conditions:
            # no condition
            return True

        functor = self._create_activation_condition(activation_condition, self.action_data)

        return gremlin.actions.ActivationCondition.rule_function[functor._rule](
            [partial(c, event, value) for c in functor._conditions]
        )




    def applyContainerCurves(self, value : float):
        ''' applies the container curve data to the curve '''
        for action in self.curve_actions:
            if action.curve_data:
                value = action.curve_data.curve_value(value)

        return value


    @property
    def reverse(self):
        # axis reversed state
        usage_data = gremlin.joystick_handling.VJoyUsageState()
        return usage_data.is_inverted(self.vjoy_device_id, self.vjoy_input_id)

    def toggle_reverse(self):
        # toggles reverse mode for the axis
        usage_data = gremlin.joystick_handling.VJoyUsageState()
        value = usage_data.is_inverted(self.vjoy_device_id, self.vjoy_input_id)
        usage_data.set_inverted(self.vjoy_device_id, self.vjoy_input_id, not value)
        log_sys(f"toggle reverse: {self.vjoy_device_id} {self.vjoy_input_id} new state: {self.reverse}")

    def latch_extra_inputs(self):
        ''' returns the list of extra devices to latch to this functor (device_guid, input_type, input_id) '''
        if self.action_data.action_mode == VjoyAction.VJoyMergeAxis:
            return [(self.action_data.merge_device_guid, self.action_data.merge_input_type, self.action_data.merge_input_id)]
        if self.action_data.action_mode == VjoyAction.VJoySetAxisStepped:
            return [(self.action_data.stepped_device_guid, self.action_data.stepped_input_type, self.action_data.stepped_input_id)]
        return []


    def profile_start(self):
        # setup initial state
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_outputs
        device_guid = self.action_data.hardware_device_guid
        input_id = self.action_data.hardware_input_id
        raw_input_type = self.action_data.hardware_raw_input_type
        
        if self.input_type in VJoyRemapWidget.input_type_buttons:
            # set start button state
            joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = self.start_pressed
        if self.input_type == InputType.JoystickAxis:
            # send initial axis values to the output

            usage_data = gremlin.joystick_handling.VJoyUsageState()
            usage_data.set_range(self.vjoy_device_id, self.vjoy_input_id, self.range_low, self.range_high)
            # print(f"Axis start value: vjoy: {self.vjoy_device_id} axis: {self.vjoy_input_id}  value: {self.axis_start_value}")



            match self.action_mode:
                case VjoyAction.VJoyAxis:
                    # straight axis
                    value = None
                    if self.action_data.axis_start_value_enabled:
                        value = self.axis_start_value
                    else:
                        # read the current value
                        raw_value = None
                        if raw_input_type == InputType.JoystickAxis:
                            raw_value = joystick_handling.get_axis(device_guid, input_id)
                        elif raw_input_type == InputType.OpenSoundControl:
                            message = input_id.message_key
                            raw_value = gremlin.ui.osc_device.osc_client.getData(message)
                        if raw_value is not None:
                            fake_event = gremlin.event_handler.Event(self.hardware_input_type, self.hardware_input_id, device_guid = self.hardware_device_guid,value = raw_value,is_axis = True)
                            action_value = gremlin.actions.Value(raw_value)
                            curves = self.getCurveData(fake_event, action_value)
                            value = self.action_data.get_filtered_axis_value(raw_value, curves = curves)
                            value = self.action_data.get_ranged_axis_value(value)

                    if value is not None:
                        if verbose: syslog.info(f"Profile start - sync axis: vjoy ID: [{self.vjoy_device_id}] axis [{self.vjoy_input_id}] value: {value:0.3f}")
                        joystick_handling.VJoyProxy()[self.vjoy_device_id].axis(self.vjoy_input_id).value = value
                        self.remote_client.send_axis(self.vjoy_device_id, self.vjoy_input_id, value)

                case VjoyAction.VJoyAxisToButton:
                    value = joystick_handling.get_curved_axis(device_guid, input_id)
                    action_value = gremlin.actions.Value(value)
                    event = gremlin.event_handler.Event(self.input_type,
                                                        device_guid = device_guid,
                                                        identifier=input_id,
                                                        is_axis=True,
                                                        value = action_value)
                    self.process_event(event, action_value)

        elif self.input_type == InputType.JoystickHat and self.action_mode == VjoyAction.VJoyHatToButton:
            
            value = joystick_handling.get_hat(device_guid, input_id)
            if value in vjoy.vjoy.Hat.to_continuous_position:
                self.hat_position = vjoy.vjoy.Hat.to_continuous_position[value]
            else:
                self.hat_position = (0,0)
            self.pressed_hat_buttons = {}
            event = gremlin.event_handler.Event(self.input_type,
                                                device_guid = device_guid,
                                                identifier = input_id,
                                                raw_value=self.hat_position,
                                                value = self.hat_position,
                                                )
            
            self.process_event(event, action_value)

        elif self.input_type == InputType.JoystickButton:
            is_pressed = None
            match self.action_mode:
                case VjoyAction.VJoyButton:
                    is_pressed = joystick_handling.get_button(device_guid, input_id)
                case VjoyAction.VJoyButton.VJoyButtonPress:
                    is_pressed = True
                case VjoyAction.VJoyButton.VJoyButtonRelease:
                    is_pressed = False

            if is_pressed is not None:
                action_value = gremlin.actions.Value(0,0,is_pressed = is_pressed)
                if verbose: syslog.info(f"Profile start - sync button: vjoy ID: [{self.vjoy_device_id}] axis [{self.vjoy_input_id}] pressed: {is_pressed}")
                event = gremlin.event_handler.Event(self.input_type,
                                            device_guid = device_guid,
                                            identifier = input_id,
                                            is_pressed=is_pressed,
                                            value = is_pressed
                )
                
                
                self.process_event(event, action_value)
            

        if self.action_mode == VjoyAction.VJoySetAxisStepped:
            # initial stepped axis value

            self.step_index = self.action_data.target_step_start_index
            value = self.action_data.target_step_list[self.step_index]
            syslog.info(f"VJOY: step mode initial value: {value:0.3f}")
            joystick_handling.VJoyProxy()[self.vjoy_device_id].axis(self.vjoy_input_id).value = value


    def profile_stop(self):
        ''' called when profile stops '''

        # clear any pulse workers still active
        worker : gremlin.repeater.PulseWorker
        for worker in self.pulse_worker_map.values():
            worker.stop()
        self.pulse_worker_map.clear()

    def _pulse_on(self, data):
        ''' called when pulse is on '''
        device_id, input_id, is_local, is_remote, force_remote = data
        if self.verbose: syslog.info(f"Pulse ON {device_id} button {input_id}")
        if is_local:
            joystick_handling.VJoyProxy()[device_id].button(input_id).is_pressed = True
        if is_remote:
            self.remote_client.send_button(device_id, True, False, force_remote = force_remote)


    def _pulse_off(self, data):
        ''' called when pulse is off '''
        
        device_id, input_id, is_local, is_remote, force_remote = data
        if self.verbose: syslog.info(f"Pulse OFF {device_id} button {input_id}")
        if is_local:
            joystick_handling.VJoyProxy()[device_id].button(input_id).is_pressed = False
        if is_remote:
            self.remote_client.send_button(device_id, input_id, False, force_remote = force_remote)

    def pulse_start(self, device_id : int, input_id : int, duration : float, interval : float, is_local : bool = True, is_remote : bool = False, force_remote : bool = False):
        ''' pulse setup '''
        if self.verbose: syslog.info(f"Pulse START vjoy {device_id} button {input_id} duration: {duration:0.3f} interval: {interval:0.3f}")
        key = (device_id, input_id)
        worker : gremlin.repeater.PulseWorker 
        if key in self.pulse_worker_map:
            worker = self.pulse_worker_map[key]
            if worker.is_running:
                # worker already running - ignore pulse request
                if self.verbose: syslog.info(f"\talready pulsing - ignored")
                return
        else:
            args = (device_id, input_id, is_local, is_remote, force_remote)
            worker = gremlin.repeater.PulseWorker(duration, interval, self._pulse_on, self._pulse_off, data = args)
            self.pulse_worker_map[key] = worker

        if self.verbose: syslog.info(f"\activate")
        worker.start()

    def pulse_stop(self, device_id : int, input_id : int):
        ''' request a pulse abort '''
        if self.verbose: syslog.info(f"Pulse STOP {device_id} button {input_id}")
        key = (device_id, input_id)
        if key in self.pulse_worker_map:
            worker : gremlin.repeater.PulseWorker = self.pulse_worker_map[key]
            del self.pulse_worker_map[key]
            worker.stop()

        





    # # async routine to pulse a button
    # def _fire_pulse(self, *args):

    #     self.lock.acquire()
    #     vjoy_device_id, vjoy_input_id, duration = args
        
    
    #     button = joystick_handling.VJoyProxy()[vjoy_device_id].button(vjoy_input_id)
    #     button.is_pressed = True
    #     self.remote_client.send_button(vjoy_device_id, vjoy_input_id, True)
    #     time.sleep(duration)
    #     button.is_pressed = False
    #     self.remote_client.send_button(vjoy_device_id, vjoy_input_id, False)
    #     self.lock.release()
    #     self.functor_complete.emit() # indicate completed

    # def smooth(self, value, reverse = False, power = 3):
    #     '''
    #         int smoothIt(int from, int to, int val, int power, int reverse) {
    #         float to2;
    #         to2 = to - from;
    #         int ret;
    #         if (reverse == 1) {
    #             ret = (pow((val - from) / to2 - 1, power) + 1) * to2 + from; //
    #             return ret;
    #         } else {
    #             ret = pow((val - from) / to2, power) * to2 + from; //
    #             return ret;
    #         }
    #         }

    #     '''
    #     v_end = 1.0
    #     v_start = 0.0
    #     power = 3
    #     if reverse:
    #         return (pow((value - v_start) / v_end - 1, power) + 1) * v_end + v_start
    #     return pow((value - v_start) / v_end, power) * v_end + v_start


    def process_event(self, event, action_value : gremlin.actions.Value, extra_data = None):
        ''' runs when a joystick event occurs like a button press or axis movement when a profile is running '''
        # if self.action_data.merged and event.is_axis:
        #     # merged axis data is handled by the internal hook - ignore
        #     return True
        if event.is_axis:
            # process input options and any merge and curve operation - the current value will already be curved by the input curve if one exists



            if event.is_repeater:
                # use the repeater value
                value = event.value
            else:

                # raw_value = gremlin.joystick_handling.get_axis(self.action_data.hardware_device_guid, self.action_data.hardware_input_id)
                # received = action_value.current

                # get list of curves that applies to this input
                curves = self.getCurveData(event, action_value)

                # this handles axis merging and applies any curves
                value = self.action_data.get_filtered_axis_value(action_value.current, curves = curves)

                value = self.action_data.get_ranged_axis_value(value)

                if value is None:
                    value = event.value

                # # syslog = logging.getLogger("system")
                # syslog.info(f"VjoyRemap: raw {raw_value:0.3f} received: {received:0.3f}  computed: {value:0.3f}  ")

            action_value = gremlin.actions.Value(value = value, raw = event.raw_value, is_pressed = event.is_pressed)
            event.curve_value = value

        return self._process_event(event, action_value, extra_data)

    def _process_event(self, event : gremlin.event_handler.Event, action_value : gremlin.actions.Value, extra_data):
        ''' runs when a joystick even occurs like a button press or axis movement when a profile is running '''
        (is_local, is_remote) = input_devices.remote_state.state
        usage_data = gremlin.joystick_handling.VJoyUsageState()
        verbose = gremlin.config.Configuration().verbose_mode_vjoy
        # syslog = logging.getLogger("system")
        if event.force_remote:
            # force remote mode on if specified in the event
            is_remote = True
            is_local = False
        
        force_remote = event.force_remote

        auto_complete = True # assume the functor completes this pass

        self.action_data : VjoyRemap
        

        input_type = event.getInputType()
        result = True # assume functor executes

        if event.is_axis: # self.input_type == InputType.JoystickAxis:
            # axis response mode

            if verbose: syslog.info(f"Value raw: {action_value.raw:0.3f}  current {action_value.current}  Event raw: {event.raw_value}  value: {event.value} curve: {event.curve_value}")

            # read the valuy from the extra data if set
            if extra_data is not None and "value" in extra_data:
                value = extra_data["value"]
            else:
                # use curve value if any
                value = self.action_data.get_filtered_axis_value() # event.curve_value
                if value is None:
                    # use regular value if any
                    value = event.value
                
                if value is None:
                    return True
                
            if value is None or not isinstance(value, float):
                if verbose: syslog.error(f"VJOYREMAP: invalid value {value} for axis")
                return 

            # axis mode
            match self.action_mode:
                case VjoyAction.VJoyAxisToButton:
                    v1 = self.range_low
                    v2 = self.range_high
                    in_range = gremlin.util.valueInRange(value, v1, v2)
                    # syslog.info(f"axis: {value:0.3f}")
                    is_pressed = None
                    match self.action_data.button_mode:
                        case ButtonOutputMode.Hold:
                            if in_range:
                                
                                if not self.in_range:
                                    # toggle ON
                                    self.in_range = True
                                    is_pressed = True
                                    if verbose: syslog.info(f"AXIS TO BUTTON: ON in range vjoy {self.vjoy_device_id} button {self.vjoy_input_id}")
                                    

                            else:
                                # not in range
                                if self.in_range:
                                    # toggle OFF
                                    if verbose: syslog.info(f"AXIS TO BUTTON: OFF out of range vjoy {self.vjoy_device_id} button {self.vjoy_input_id}")
                                    self.in_range = False
                                    is_pressed = False

                        case ButtonOutputMode.Pulse:
                            input_id = self.vjoy_input_id
                            device_id = self.vjoy_device_id
                            if in_range:
                                if not self.in_range:
                                    self.in_range = True
                                    if verbose: syslog.info(f"VJOY: trigger start range pulse vjoy {device_id} hat {input_id}")
                                    repeat_interval =  self.action_data.pulse_repeat_delay/1000 if self.action_data.pulse_repeat else -1
                                    self.pulse_start(device_id, input_id, self.pulse_delay/1000, repeat_interval, is_local, is_remote, force_remote)
                                    auto_complete = False
                            else:
                                if self.in_range:
                                    self.in_range = False
                                    if verbose: syslog.info(f"VJOY: trigger stop range pulse vjoy {device_id} hat {input_id}")
                                    self.pulse_stop(device_id, input_id)
                            return True

                                    
                        case ButtonOutputMode.Press:
                            is_pressed = True

                        case ButtonOutputMode.Release:
                            is_pressed = False

                        case _:
                            # do nothing
                            return True

                    if is_pressed is not None:
                        if is_local:
                            joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = is_pressed
                        if is_remote:
                            self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, is_pressed)

                case _:
                    if self.axis_mode == "absolute":
                        # apply any range function to the raw position


                        if verbose: syslog.info(f"AXIS ABSOLUTE: send vjoy {self.vjoy_device_id} axis {self.vjoy_input_id} range: [{self.range_low:0.3f},{self.range_high:0.3f}] scale: {self.axis_scaling:0.3f} value: {value:0.3f}")

                        if is_local:
                            joystick_handling.VJoyProxy()[self.vjoy_device_id].axis(self.vjoy_input_id).value = value
                        
                        
                        if is_remote:
                            self.remote_client.send_axis(self.vjoy_device_id, self.vjoy_input_id, value)
                    else:
                        #value = -target if self.reverse else target
                        self.should_stop_thread = abs(event.value) < 0.05
                        self.axis_delta_value = value * (self.axis_scaling / 1000.0)

                        self.thread_last_update = time.time()
                        if self.thread_running is False:
                            if isinstance(self.thread, threading.Thread):
                                self.thread.join()
                            auto_complete = False
                            self.thread = threading.Thread(target=self.relative_axis_thread, daemon=False)
                            self.thread.start()

        elif self.action_mode == VjoyAction.VJoyHatToButton:
            position = action_value.current

            pressed_positions = list(self.pressed_hat_buttons.keys())
            is_pressed = event.is_pressed # position != (0,0)
            mode = self.action_data.hat_mode_map[position]

            input_id = self.action_data.hat_map[position]
            device_id =self.vjoy_device_id
            # sticky = self.action_data.hat_sticky
            if input_id > 0:

                match mode:
                    case ButtonOutputMode.Pulse:
                        if is_pressed:
                            if verbose: syslog.info(f"VJOY: trigger start pulse vjoy {device_id} hat {input_id}")
                            repeat_interval =  self.action_data.pulse_repeat_delay/1000 if self.action_data.pulse_repeat else -1
                            self.pulse_start(device_id, input_id, self.pulse_delay/1000, repeat_interval, is_local, is_remote, force_remote)
                            auto_complete = False
                        else:
                            if verbose: syslog.info(f"VJOY: trigger stop pulse vjoy {device_id} hat {input_id}")
                            self.pulse_stop(device_id, input_id)

                            # threading.Timer(0.01, self._fire_pulse, [self.vjoy_device_id, input_id, self.pulse_delay/1000, self.action_data.pulse_repeat, self.action_data.pulse_repeat_delay/1000]).start()
                    case ButtonOutputMode.Hold:
                        if is_pressed:
                            # release the prior buttons
                            for pressed_position in pressed_positions:
                                if position == pressed_position:
                                    continue
                                release_input_id = self.pressed_hat_buttons[pressed_position]
                                if release_input_id > 0:
                                    if is_local:
                                        joystick_handling.VJoyProxy()[device_id].button(release_input_id).is_pressed = False
                                    if is_remote:
                                        self.remote_client.send_button(device_id, release_input_id, False)

                                del self.pressed_hat_buttons[pressed_position]
                    case ButtonOutputMode.Press:
                        is_pressed = True
                        if input_id in self.pressed_hat_buttons:
                            del self.pressed_hat_buttons[input_id]
                    case ButtonOutputMode.Release:
                        is_pressed = False
                        if input_id in self.pressed_hat_buttons:
                            del self.pressed_hat_buttons[input_id]
                    case ButtonOutputMode.NoOp:
                        # do nothing
                        return True
                    
                # press the new button
                self.pressed_hat_buttons[position] = input_id
                if is_local:
                    joystick_handling.VJoyProxy()[device_id].button(input_id).is_pressed = is_pressed
                if is_remote:
                    self.remote_client.send_button(device_id, input_id, is_pressed)


            else:
                # release
                match mode:
                    case ButtonOutputMode.NoOp:
                        # do nothing
                        return True
                    case ButtonOutputMode.Press:
                        return True
                    case ButtonOutputMode.Release:
                        return True


                for pressed_position in pressed_positions:
                    input_id = self.pressed_hat_buttons[pressed_position]
                    if input_id > 0:
                        if is_local:
                            joystick_handling.VJoyProxy()[self.vjoy_device_id].button(input_id).is_pressed = False
                        if is_remote:
                            self.remote_client.send_button(self.vjoy_device_id, input_id, False)

                    del self.pressed_hat_buttons[pressed_position]




            self.hat_position = position

        elif input_type in VJoyRemapWidget.input_type_buttons:
            is_paired = remote_state.paired
            force_remote = event.force_remote or is_paired

            # determine if event should be fired based on release mode
            fire_event =  (self.exec_on_release and not event.is_pressed) or (not self.exec_on_release and event.is_pressed)
            is_pressed = event.is_pressed

            if self.action_mode == VjoyAction.VJoyButton:
                # normal default behavior
                if verbose: syslog.info(f"VJOY: trigger on button press {self.vjoy_input_id} pressed: {event.is_pressed}")
                if self.exec_on_release:
                    if not is_pressed:
                        if is_local:
                            joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = True
                        if is_remote or is_paired:
                            self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, True, force_remote = force_remote )
                else:
                    auto_release = False
                    if is_pressed and not self.action_data.ignore_release:
                        if extra_data and "autorelease" in extra_data:
                            auto_release = extra_data["autorelease"]
                        else:
                            auto_release = event.event_type in [InputType.Keyboard, InputType.KeyboardLatched, InputType.Midi, InputType.OpenSoundControl] and self.needs_auto_release 
                        if auto_release:
                            if verbose: syslog.info(f"VjoyRemap: autorelease enabled for {str(event)}")
                            input_devices.ButtonReleaseActions().register_button_release(
                                (self.vjoy_device_id, self.vjoy_input_id),
                                event,
                                is_local = is_local,
                                is_remote = is_remote,
                                force_remote = force_remote,
                                activate_on = False # released
                            )

                    if verbose: syslog.info(f"\t{self.vjoy_input_id} pressed: {is_pressed}  ignore release: {self.action_data.ignore_release}")
                    trigger = is_pressed or (not auto_release and not is_pressed)  # trigger on press, or on release unless an auto-release was already registered for the release action to avoid double releases
                    if not is_pressed and self.action_data.ignore_release:
                        # ignore release action on press/release modes
                        if verbose: syslog.info("\tignoring release")
                        trigger = False
  
                    if trigger:
                        if verbose: syslog.info(f"\tTrigger {self.vjoy_input_id} pressed: {event.is_pressed}")
                        if is_local:
                            joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = is_pressed
                        if is_remote or is_paired:
                            self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, is_pressed, force_remote = is_paired )
                    else:
                        # indicate no execution
                        result = False 


            elif self.action_mode == VjoyAction.VJoyButtonPress:
                # press button (no auto release)
                if verbose: syslog.info(f"VJOY: trigger on button press {self.vjoy_input_id} pressed: {event.is_pressed}")

                if is_pressed:
                    if is_local:
                        joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = True
                    if is_remote or is_paired:
                        self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, True, force_remote = is_paired )


            elif self.action_mode == VjoyAction.VJoyButtonRelease:
                # release button (no auto release)
                if verbose: syslog.info(f"VJOY: trigger on button release {self.vjoy_input_id} pressed: {event.is_pressed}")

                if is_pressed:
                    if is_local:
                        joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = False
                    if is_remote or is_paired:
                        self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, False, force_remote = is_paired )




            elif self.action_mode == VjoyAction.VJoyToggle:
                # toggle action
                if verbose: syslog.info(f"VJOY: trigger button toggle {self.vjoy_input_id} pressed: {event.is_pressed}")
                if fire_event:
                    if event.event_type in [InputType.JoystickButton, InputType.Keyboard] \
                            and event.is_pressed:
                        if is_local:
                            button = joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id)
                            button.is_pressed = not button.is_pressed
                        if is_remote:
                            self.remote_client.toggle_button(self.vjoy_device_id, self.vjoy_input_id)


            elif self.action_mode == VjoyAction.VJoyPulse:
                input_id = self.vjoy_input_id
                device_id = self.vjoy_device_id
                if verbose: syslog.info(f"VJOY: trigger start pulse vjoy {device_id} button {input_id}")
                # pulse action
                if is_pressed:
                    auto_complete = False
                    repeat_interval =  self.action_data.pulse_repeat_delay/1000 if self.action_data.pulse_repeat else -1
                    self.pulse_start(device_id, input_id, self.pulse_delay/1000, repeat_interval, is_local, is_remote, force_remote)
                else:
                    if verbose: syslog.info(f"VJOY: trigger stop pulse vjoy {device_id} button {input_id}")
                    self.pulse_stop(self.vjoy_device_id, input_id)
            elif self.action_mode == VjoyAction.VJoyInvertAxis:
                # invert the specified axis
                if fire_event:
                    self.toggle_reverse()


            elif self.action_mode == VjoyAction.VJoySetAxis:
                # set the value on the specified axis
                

                if self.target_value_valid and fire_event:
                    if is_local:
                        if self.target_is_relative:
                            value = joystick_handling.VJoyProxy()[self.vjoy_device_id].axis(self.vjoy_input_id).value
                            value = gremlin.util.clamp(value + self.target_value, -1.0, 1.0)
                        else:
                            value = self.target_value
                        joystick_handling.VJoyProxy()[self.vjoy_device_id].axis(self.vjoy_input_id).value = value
                    if is_remote:
                        self.remote_client.send_axis(self.vjoy_device_id, self.vjoy_input_id, None, self.target_value)


            elif self.action_mode == VjoyAction.VJoyRangeAxis:
                # changes the output range on the target device / axis
                if fire_event:
                    usage_data.set_range(self.vjoy_device_id, self.vjoy_input_id, self.range_low, self.range_high)

            elif VjoyAction.is_command(self.action_mode):
                # update remote control mode
                if fire_event:
                    remote_state.mode = self.action_mode

            elif self.action_mode == VjoyAction.VJoySetAxisStepped:
                latched = self.action_data._stepped_latched and event.device_guid == self.action_data.stepped_device_guid and event.identifier == self.action_data.stepped_input_id
                primary = event.device_guid == self.hardware_device_guid and event.identifier == self.hardware_input_id
           
                if primary or latched:
                    trigger = False
                    trigger = (event.is_pressed and not self.action_data.exec_on_release) or (not event.is_pressed and self.action_data.exec_on_release)
                    if trigger:
                        trigger = False
                        key = ("stepped-axis",self.vjoy_input_id)
                        device = gremlin.joystick_handling.vjoy_info_from_vjoy_id(self.vjoy_device_id)
                        if not key in device.data:
                            device.data[key] = self.action_data.target_step_start_index
                        start_index = device.data[key]
                        index = start_index
                        direction = self.action_data.target_step_direction
                     
                        if primary:
                            # up direction
                            if verbose: syslog.info(f"STEPPED AXIS: Step {'up' if direction == 1 else 'down'}")
                            index += direction
                            trigger = True
                        elif latched:
                            # down direction
                            if verbose: syslog.info(f"STEPPED AXIS: Step {'down' if direction == 1 else 'up'}")
                            index -= direction
                            trigger = True

                        if trigger:
                            
                            count = len(self.action_data.target_step_list)
                            index = gremlin.util.clamp(index, 0, count-1)
                            value = self.action_data.target_step_list[index]
                            if is_local:
                                joystick_handling.VJoyProxy()[self.vjoy_device_id].axis(self.vjoy_input_id).value = value
                            if is_remote:
                                self.remote_client.send_axis(self.vjoy_device_id, self.vjoy_input_id, value)

                            device.data[key] = index
                            if verbose: syslog.info(f"STEPPED AXIS: start index: {start_index} new index: {index} step value: {value:0.3f}")
                            pass
                else:
                    # wrong input
                    result = False


            else:
                # basic handling of the button

                if fire_event:
                    if is_local:
                        joystick_handling.VJoyProxy()[self.vjoy_device_id].button(self.vjoy_input_id).is_pressed = action_value.current
                    if is_remote:
                        self.remote_client.send_button(self.vjoy_device_id, self.vjoy_input_id, action_value.current)



        elif input_type == InputType.JoystickHat:
            if is_local:
                joystick_handling.VJoyProxy()[self.vjoy_device_id].hat(self.vjoy_input_id).direction = action_value.current
            if is_remote:
                self.remote_client.send_hat(self.vjoy_device_id, self.vjoy_input_id, action_value.current)


        if auto_complete:
            self.functor_complete.emit() # indicate completed
        return result

    def relative_axis_thread(self):
        self.thread_running = True
        vjoy_dev = joystick_handling.VJoyProxy()[self.vjoy_device_id]
        self.axis_value = vjoy_dev.axis(self.vjoy_input_id).value
        (is_local, is_remote) = input_devices.remote_state.state
        while self.thread_running:
            try:
                # If the vjoy value has was changed from what we set it to
                # in the last iteration, terminate the thread
                change = vjoy_dev.axis(self.vjoy_input_id).value - self.axis_value
                if abs(change) > 0.0001:
                    self.thread_running = False
                    self.should_stop_thread = True
                    return

                self.axis_value = max(
                    -1.0,
                    min(1.0, self.axis_value + self.axis_delta_value)
                )

                if is_local:
                    vjoy_dev.axis(self.vjoy_input_id).value = self.axis_value
                if is_remote:
                    self.remote_client.send_axis(self.vjoy_device_id, self.vjoy_input_id, self.axis_value)

                if self.should_stop_thread and \
                        self.thread_last_update + 1.0 < time.time():
                    self.thread_running = False
                time.sleep(0.01)
            except gremlin.error.VJoyError:
                self.thread_running = False

        self.functor_complete.emit() # indicate completed



class VjoyRemap(gremlin.base_profile.AbstractAction):

    """Action remapping physical joystick inputs to vJoy inputs."""

    name = "Vjoy Remap"
    tag = "vjoyremap"

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, True)

    functor = VJoyRemapFunctor
    widget = VJoyRemapWidget

    def __init__(self, parent):
        """ vjoyremap action block """
        super().__init__(parent)
        self.parent = parent
        self.setPriority(9)
        # Set vjoy ids to None so we know to pick the next best one
        # automatically
        self._vjoy_device_id : int = 1
        self._vjoy_input_id : int  = 1
        self.input_type : InputType = self.get_input_type()
        if self.input_type in (InputType.ModeControl, InputType.VirtualButton):
            self.input_type = InputType.JoystickButton

        # default hat map table setup and default mapping for new hats
        self.hat_map = {} # map of button id keyed by hat position tuple
        self.hat_positions = list(vjoy.vjoy.Hat.to_continuous_direction.keys())
        #self.hat_positions.remove((0,0)) # remove center position
        self.hat_mode_map = {} # bool table keyed by hat position
        self.hat_sticky = False # determines if hats are sticky or not - sticky means all positions are active until all returns to the center position
        button_id = 1
        for position in self.hat_positions:
            self.hat_map[position] = button_id
            if position == (0,0):
                self.hat_mode_map[position] = ButtonOutputMode.NoOp # center do nothing
            else:
                
                self.hat_mode_map[position] = ButtonOutputMode.Hold # hold by default
            button_id += 1

        self.vjoy_axis_id = 1
        self.vjoy_button_id = 1
        self.vjoy_hat_id = 1
        self.vjoy_device_guid = None

        self._reverse : bool = False
        self.axis_mode = "absolute"
        self.axis_scaling : float  = 1.0
        self.axis_start_value : float = 0 # start value
        self.axis_start_value_enabled = False
        self.curve_data = None # present if curve data is needed

        config = gremlin.config.Configuration()
        self._grid_visible = config.button_grid_visible # true if the button grid is visible

        self._exec_on_release : bool = False
        self._paired : bool = False

        self.auto_release = False # true if we should do an auto-release (only means anything on momentary inputs)
        self.ignore_release = False # true if the button release should be ignored

        self._merge_device_id : str = None # input guid (str) of the merged device
        self._merge_device_guid : dinput.GUID = None # input guid for the merge device
        self.merge_input_id : int = None # input id of the merged input
        self.merge_input_type : gremlin.input_types.InputType =  gremlin.input_types.InputType.JoystickAxis # only merging axes at this point
        self._merge_mode : MergeOperationType = MergeOperationType.Center # default merge method
        self.output_range_min : float = -1.0 # min for merged output
        self.output_range_max : float = 1.0 # max for merged output
        self.merge_invert : bool = False # inversion flag for merged output
        self.merged = False

        # default mode
        self._action_mode = VjoyAction.VJoyButton

        self.button_range_min = -1.0 # axis to button range min
        self.button_range_max = 1.0 # axis to button range max
        self.button_mode = ButtonOutputMode.Hold


        is_axis = self.input_is_axis()

        # pick an appropriate default action set for the type of input this is
        if is_axis:
                # input is setup as an axis
                self._action_mode = VjoyAction.VJoyAxis
        elif self.input_type in VJoyRemapWidget.input_type_buttons:
            self._action_mode = VjoyAction.VJoyButton
        elif self.input_type == InputType.JoystickHat:
            self._action_mode = VjoyAction.VJoyHat

        self.current_state = 0 # toggle value for the input 1 means set, any other value means not set for buttons
        self.pulse_delay = 250 # pulse delay
        self.pulse_repeat_delay = 250 # pulse repeat delay (time between pulses)
        self.pulse_repeat = False  # true if pulses repeat
        self.start_pressed = False # true if a button starts as pressed when the profile is loaded
        self.target_value = 0.0
        self.target_step_list = [-1,-0.5,0,0.5,1] # list of values to send - if empty - uses the fixed target_value
        
        self._current_step_index = 0 # index of last value sent
        self._target_step_start_index = 0 # start index when profile is loaded (initial step)
        self._target_step_direction = 1 # direction of stepping, +1 or -1
        self._stepped_latched = True # true if the step down latching is enabled
        self.target_value_valid = True
        self.target_is_relative = False # true if the set value axis is a relative value (+ or -)
        self._stepped_device_id : str = None # device of the down step action to latch
        self._stepped_device_guid : dinput.GUID = None # device GUID of the down step device
        self.stepped_input_type = gremlin.input_types.InputType.JoystickButton
        self.stepped_input_id : int = None # input of the down step action to latch

        self.override_input_type = None # manual input type override



        self.vjoy_map = {}  # list of vjoy devices by their vjoy index ID
        self.refresh_vjoy()
       
    @property
    def target_step_direction(self) -> int:
        return self._target_step_direction
    @target_step_direction.setter
    def target_step_direction(self, value : int):
        self._target_step_direction = value
    
    @property
    def target_step_start_index(self) -> int:
        return self._target_step_start_index
    @target_step_start_index.setter
    def target_step_start_index(self, value : int):
        self._target_step_start_index = value
        self._current_step_index = value


    def is_scaled(self):
        ''' true if the axis output is scaled '''
        return abs(self.output_range_min - self.output_range_max) != 2.0

    def get_input_type(self, override = True):
        if override and self.override_input_type is not None:
            return self.override_input_type
        return super().get_input_type()
    
    def refresh_vjoy(self):
        ''' updates vjoy devices device map  '''
        self.vjoy_map = {} # holds the map of devices keyed by VJOYID
        devices = sorted(joystick_handling.vjoy_devices(),key=lambda x: x.vjoy_id)
        for dev in devices:
            self.vjoy_map[dev.vjoy_id] = dev



    def get_raw_axis_value(self):
        if self.input_is_hardware():
            return gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)
        return self.hardware_input_id.getAxisValue()

    def get_filtered_axis_value(self, value : float = None, curves : list = None) -> float:
        ''' computes the output value for the current configuration - applies curves if curves are provided  '''

        verbose_details = gremlin.config.Configuration().verbose_mode_inputs_extra

        axis_value = gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)

        if axis_value is None:
            # not an axis type 
            return None
        
        if isinstance(axis_value, list) and axis_value:
            axis_value = axis_value[0]
        
        value = axis_value

        if curves:
            for curve_data in curves:
                value = curve_data.curve_value(value)

        if self.action_mode == VjoyAction.VJoyAxis:
            # plain axis 
            if curves:
                for curve_data in curves:
                    value = curve_data.curve_value(value)

            # apply scale or invert to input
            is_scaled = self.is_scaled()
            is_reverse = self.reverse
            if is_scaled or is_reverse:
                value = scale_to_range(value,
                        target_min=self.output_range_min,
                        target_max=self.output_range_max,
                        invert = is_reverse)
                if verbose_details: syslog.info(f"VJOY REMAP: Axis input: {axis_value:0.3f}  scaled: {is_scaled} reversed: {is_reverse} Filtered: {value:0.3f}")    
            else:
                if verbose_details: syslog.info(f"VJOY REMAP: Axis input: {axis_value:0.3f} Filtered: {value:0.3f}")
                



        elif self.action_mode == VjoyAction.VJoyMergeAxis and self.merge_mode != MergeOperationType.NotSet:
            if self.merge_device_id and self.merge_input_id:
                # always read v1 and v2 because the input value may be of either inputs
                v1 = None
                v2 = None
                if gremlin.joystick_handling.is_hardware_device(self.hardware_device_guid):
                    v1 = gremlin.joystick_handling.get_curved_axis(self.hardware_device_guid, self.hardware_input_id)
                else:
                    v1 = self.hardware_input_id.axis_value

                if gremlin.joystick_handling.is_hardware_device(self.merge_device_guid):
                    v2 = gremlin.joystick_handling.get_curved_axis(self.merge_device_guid, self.merge_input_id)
                else:
                    # find the merged device
                    ec = gremlin.execution_graph.ExecutionContext()
                    input_item = ec.findInputItem(self.merge_device_guid, self.merge_input_id)
                    if input_item:
                        v2 = input_item.axis_value

                if v1 is None or v2 is None:
                    # something wasn't found
                    syslog.error("VjoyRemap: merge: unable to get an axis value, one of the inputs was not found.")
                    return 0.0

                # apply any local curves to the values
                if curves:
                    for curve_data in curves:
                        v1 = curve_data.curve_value(v1)
                        v2 = curve_data.curve_value(v2)



                match self.merge_mode:
                    case MergeOperationType.Add:
                        value = scale_to_range(v1+v2,
                                            target_min=self.output_range_min,
                                            target_max=self.output_range_max,
                                            invert = self.merge_invert)
                    case MergeOperationType.Average:
                        value = scale_to_range((v1+v2)/2,
                                                target_min=self.output_range_min,
                                                target_max=self.output_range_max,
                                                invert = self.merge_invert)
                    case MergeOperationType.Center:
                        value = scale_to_range((v1-v2)/2,
                                                target_min=self.output_range_min,
                                                target_max=self.output_range_max,
                                                invert = self.merge_invert)
                    case MergeOperationType.Min:
                        value = scale_to_range(min(v1,v2),
                                                target_min=self.output_range_min,
                                                target_max=self.output_range_max,
                                                invert = self.merge_invert)
                    case MergeOperationType.Max:
                        value = scale_to_range(max(v1,v2),
                                                target_min=self.output_range_min,
                                                target_max=self.output_range_max,
                                                invert = self.merge_invert)

        return value
    
    def get_ranged_axis_value(self, value : float) -> float:
        ''' get scaled and ranged and inverted axis value'''
        if value is None:
            return value
        v1 = self.output_range_min
        v2 = self.output_range_max
        if v1 > v2:
            v1, v2 = v2, v1
        s = self.axis_scaling
        inverted = self.reverse
        if v1 != -1.0 or v2 != 1.0 or s != 1.0:
            value = gremlin.util.scale_to_range(value*s,target_min=v1,target_max=v2, invert=inverted)        
        elif inverted:
            value = gremlin.util.scale_to_range(value, invert=True)
        return value

    @property
    def merge_mode(self) -> MergeOperationType:
        return self._merge_mode
    @merge_mode.setter
    def merge_mode(self, value : MergeOperationType):
        self._merge_mode = value
        self.merged = value != MergeOperationType.NotSet

    @property
    def merge_device_id(self) -> str:
        return self._merge_device_id

    @merge_device_id.setter
    def merge_device_id(self, value : str | dinput.GUID):
        if value is None:
            self._merge_device_id = None
            self._merge_device_guid = None
            return
        if not isinstance(value, str):
            value = str(value)
        self._merge_device_id = value
        self._merge_device_guid = util.parse_guid(value)

    @property
    def merge_device_guid(self) -> dinput.GUID:
        return self._merge_device_guid
    @merge_device_guid.setter
    def merge_device_guid(self, value : dinput.GUID):
        if value is None:
            self._merge_device_id = None
            self._merge_device_guid = None
            return
        self._merge_device_guid = value
        self._merge_device_id = str(value)


    @property
    def stepped_device_id(self) -> str:
        return self._stepped_device_id

    @stepped_device_id.setter
    def stepped_device_id(self, value : str | dinput.GUID):
        if value is None:
            self._stepped_device_id = None
            self._stepped_device_guid = None
            return
        if not isinstance(value, str):
            value = str(value)
        self._stepped_device_id = value
        self._stepped_device_guid = util.parse_guid(value)

    @property
    def stepped_device_guid(self) -> dinput.GUID:
        return self._stepped_device_guid
    @stepped_device_guid.setter
    def stepped_device_guid(self, value : dinput.GUID):
        if value is None:
            self._stepped_device_id = None
            self._stepped_device_guid = None
            return
        self._stepped_device_guid = value
        self._stepped_device_id = str(value)




    def display_name(self):
        ''' display name for this action '''
        if self.action_mode == VjoyAction.VJoyAxis:
            return f"VJoy #{self._vjoy_device_id} Axis: {self.vjoy_axis_id}"
        elif self.action_mode == VjoyAction.VJoyButtonPress:
            return f"VJoy #{self._vjoy_device_id} Button: {self.vjoy_button_id}"
        elif self.action_mode in (VjoyAction.VJoyHat, VjoyAction.VJoyHatToButton):
            return f"VJoy #{self._vjoy_device_id} Hat: {self.vjoy_hat_id}"
        else:
            return f"VJoy #{self._vjoy_device_id} Mode: {self.action_mode}"




    @property
    def exec_on_release(self):
        return self._exec_on_release

    @exec_on_release.setter
    def exec_on_release(self, value):
        self._exec_on_release = value

    @property
    def paired(self):
        return self._paired

    @paired.setter
    def paired(self, value):
        self._paired = value

    @property
    def vjoy_device_id(self):
        return self._vjoy_device_id

    @vjoy_device_id.setter
    def vjoy_device_id(self, value):
        self._vjoy_device_id = value

    @property
    def vjoy_input_id(self):
        return self._vjoy_input_id
    @vjoy_input_id.setter
    def vjoy_input_id(self, value):
        self._vjoy_input_id = value

    @property
    def action_mode(self) -> VjoyAction:
        if not self._action_mode:
            input_type = self.get_input_type()
            if input_type in VJoyRemapWidget.input_type_buttons:
                default_action_mode = VjoyAction.VJoyButtonPress
            elif input_type == InputType.JoystickHat:
                default_action_mode = VjoyAction.VJoyHat
            elif input_type == InputType.JoystickAxis:
                default_action_mode = VjoyAction.VJoyAxis
            else:
                default_action_mode = VjoyAction.VJoyButtonPress
            self.action_mode = default_action_mode
        
        return self._action_mode

    @action_mode.setter
    def action_mode(self, value : VjoyAction):
        self._action_mode = value
        # print (f"action mode set to : {value}")

        # sync the button mode with drop down style mode
        match self.action_mode:
            case VjoyAction.VJoyPulse:
                self.button_mode == ButtonOutputMode.Pulse
            case VjoyAction.VJoyButtonPress:
                self.button_mode == ButtonOutputMode.Press
            case VjoyAction.VJoyButton:
                self.button_mode == ButtonOutputMode.Hold
            case VjoyAction.VJoyButtonRelease:
                self.button_mode == ButtonOutputMode.Release


    @property
    def reverse(self):
        # axis reversed state
        return self._reverse
        # usage_data = gremlin.joystick_handling.VJoyUsageState()
        # return usage_data.is_inverted(self.vjoy_device_id, self.vjoy_axis_id) or self._reverse

    @reverse.setter
    def reverse(self,value):
        usage_data = gremlin.joystick_handling.VJoyUsageState()
        usage_data.set_inverted(self.vjoy_device_id, self.vjoy_axis_id, value)
        self._reverse = value

    def toggle_reverse(self):
        # toggles reverse mode for the axis
        self.reverse = not self.reverse


    @property
    def reverse_configured(self) -> bool:
        ''' returns the configured reverse value rather than the live mode '''
        return  self._reverse

    @property
    def grid_visible(self) -> bool:
        return self._grid_visible
    @grid_visible.setter
    def grid_visible(self, value : bool):
        self._grid_visible = value
        config = gremlin.config.Configuration()
        config.button_grid_visible = value

    def icon(self):
        """Returns the icon corresponding to the remapped input.

        :return icon representing the remap action
        """
        import gremlin.shared_state
        is_dark = gremlin.shared_state.is_dark_theme
        prefix = "dark_" if is_dark else ""

        fallback = f"{prefix}joystick.png"
        if self.action_mode in (VjoyAction.VJoySetAxis, VjoyAction.VJoyInvertAxis, VjoyAction.VJoyAxis):
            input_string = "axis"
        elif self.action_mode == VjoyAction.VJoyHat:
            input_string = "hat"
            fallback = "mdi.axis-arrow"
        elif self.action_mode in (VjoyAction.VJoyButtonPress, VjoyAction.VJoyButtonRelease, VjoyAction.VJoyPulse, VjoyAction.VJoyHatToButton):
            input_string = "button"
            fallback = "mdi.gesture-tap-button"
        else:
            input_string = None
            #log_sys_warn(f"VjoyRemap: don't know how to handle action mode: {self.action_mode}")

        
        icon_path = f"{prefix}icon_{input_string}_{self.vjoy_input_id:03d}.png" if input_string else fallback
        icon_file = get_icon_path(icon_path)
        if icon_file and os.path.isfile(icon_file):
            return icon_file

        return fallback

        #return super().icon()





    def requires_virtual_button(self):
        """Returns whether or not the action requires an activation condition.

        :return True if an activation condition is required, False otherwise
        """
        input_type = self.input_type

        if input_type in VJoyRemapWidget.input_type_buttons:
            return False
        elif input_type == InputType.JoystickAxis:
            if self.input_type == InputType.JoystickAxis:
                return False
            else:
                return True
        elif input_type == InputType.JoystickHat:
            return False
        else:
            return True

    def set_input_id(self, index):
        if self.action_mode in (VjoyAction.VJoyAxis, VjoyAction.VJoyInvertAxis, VjoyAction.VJoySetAxis):
                self.vjoy_axis_id = index
        elif self.action_mode == VjoyAction.VJoyHat:
            self.vjoy_hat_id = index
        else:
            self.vjoy_button_id = index
        self.vjoy_input_id = index

    def get_input_id(self):
        ''' returns input id based on the action mode '''
        if self.action_mode in (VjoyAction.VJoyAxis, VjoyAction.VJoyInvertAxis, VjoyAction.VJoySetAxis):
            return self.vjoy_axis_id
        elif self.action_mode == VjoyAction.VJoyHat:
            return self.vjoy_hat_id
        else:
            return self.vjoy_button_id



    def _parse_xml(self, node, data = None):
        """Populates the data storage with data from the XML node.

        :param node XML node with which to populate the storage
        """

        try:


            vjoy_id = safe_read(node, "vjoy", int, 1)
            if not vjoy_id in self.vjoy_map:
                self.refresh_vjoy() # ensure we have the latest device list

            if not vjoy_id in self.vjoy_map:
                syslog.error(f"Profile load: vjoy device {vjoy_id} was not found in the list of valid VJOY devices")
                self.vjoy_axis_id = 1
                self.vjoy_button_id = 1
                self.vjoy_hat_id = 1
                return


            self.vjoy_device_id = vjoy_id

            if "input" in node.attrib:
                index = safe_read(node,"input", int, 1)
                self.set_input_id(index)


            #valid = False
            for input_type in InputType.to_list():
                attrib_name = InputType.to_string(input_type)
                if attrib_name in node.attrib:
                    self.input_type = input_type
                    self.vjoy_input_id = safe_read(node, attrib_name, int, 1)
                    self.vjoy_axis_id = self.vjoy_input_id
                    self.vjoy_button_id = self.vjoy_input_id
                    #valid = True
                    break

            # if not valid:
            #     raise gremlin.error.GremlinError(f"VJOYREMAP: Invalid remap type provided: {node.attrib}")



            self.pulse_delay = 250
            self.merge_input_id = None
            self.merge_device_id = None

            if "mode" in node.attrib:
                value = node.attrib['mode']
                self.action_mode = VjoyAction.from_string(value)
            else:
                if self.input_type in VJoyRemapWidget.input_type_buttons:
                    default_action_mode = VjoyAction.VJoyButtonPress
                elif self.input_type == InputType.JoystickHat:
                    default_action_mode = VjoyAction.VJoyHat
                elif self.input_type == InputType.JoystickAxis:
                    default_action_mode = VjoyAction.VJoyAxis
                self.action_mode = default_action_mode


            # hack to sync all loaded profile setups with the status grid
            usage_data = gremlin.joystick_handling.VJoyUsageState()
            if self.input_type == InputType.JoystickButton:
                usage_data.set_usage_state(self.vjoy_device_id, self.vjoy_input_id, state = True, action = self, emit = False)
                #usage_data.push_load_list(self.vjoy_device_id,self.input_type,self.vjoy_input_id)
            elif self.input_type == InputType.JoystickAxis:
                # check action mode for special case axis to button
                if self.action_mode == VjoyAction.VJoyAxisToButton:
                    usage_data.set_usage_state(self.vjoy_device_id, self.vjoy_input_id, state = True, action = self, emit = False)


            if "reverse" in node.attrib:
                self.reverse = safe_read(node,"reverse",bool,False)

            if "axis-type" in node.attrib:
                self.axis_mode = safe_read(node, "axis-type", str, "absolute")
            if "axis-scaling" in node.attrib:
                self.axis_scaling = safe_read(node, "axis-scaling", float, 1.0)

            if "pulse_delay" in node.attrib:
                value = safe_read(node,"pulse_delay", int, 250)
                self.pulse_delay = value
            if "start_pressed" in node.attrib:
                self.start_pressed = safe_read(node,"start_pressed", bool, False)

            if "target_value" in node.attrib:
                self.target_value  = safe_read(node,"target_value", float, 0.0)
                self.target_value_valid = True

            if "target_relative" in node.attrib:
                self.target_is_relative = safe_read(node,"target_relative", bool, False)

            if "range_low" in node.attrib:
                self.button_range_min = safe_read(node,"range_low", float, -1.0)

            if "range_high" in node.attrib:
                self.button_range_max = safe_read(node,"range_high", float, 1.0)

            if "range_mode" in node.attrib:
                mode = safe_read(node,"range_mode", str, "")
                mode = mode.casefold()
                match mode:
                    case "noop":
                        mode = ButtonOutputMode.NoOp
                    case "hold":
                        mode = ButtonOutputMode.Hold
                    case "pulse":
                        mode = ButtonOutputMode.Pulse
                    case "press":
                        mode = ButtonOutputMode.Press
                    case "release":
                        mode = ButtonOutputMode.Release
                    case _:
                        # legacy mode
                        is_pulse = safe_read(node,"pulse",bool, False)
                        mode = ButtonOutputMode.Pulse if is_pulse else ButtonOutputMode.Hold
                self.button_mode = mode

            if "output_range_low" in node.attrib:
                self.output_range_min = safe_read(node,"output_range_low", float, -1.0)

            if "output_range_high" in node.attrib:
                self.output_range_max = safe_read(node,"output_range_high", float, 1.0)                

            if "axis_start_value" in node.attrib:
                self.axis_start_value = safe_read(node,"axis_start_value", float, -1.0)

            if "axis_start_value_enabled" in node.attrib:
                self.axis_start_value_enabled = safe_read(node,"axis_start_value_enabled", bool, False)
            

            if "exec_on_release" in node.attrib:
                self.exec_on_release = safe_read(node,"exec_on_release",bool, False)


            if "paired" in node.attrib:
                self.paired = safe_read(node,"paired", bool, False)

            if "merge_device_id" in node.attrib:
                self.merge_device_id = node.get("merge_device_id")

            if "merge_input_id" in node.attrib:
                self.merge_input_id = safe_read(node,"merge_input_id", int, 0)

            if "merge_input_type" in node.attrib:
                merge_input_type = safe_read(node,"merge_input_type", str, "")
                self.merge_input_type = gremlin.input_types.InputType.to_enum(merge_input_type)

            if "merge_mode" in node.attrib:
                mode = node.get("merge_mode")
                try:
                    merge_mode = MergeOperationType.to_enum(mode)
                    self.merge_mode = merge_mode
                except:
                    pass
            if "merge_invert" in node.attrib:
                self.merge_invert = safe_read(node,"merge_invert", bool, False)
            if "merge_min" in node.attrib:
                self.output_range_min = safe_read(node,"merge_min", float, -1.0)
            if "merge_max" in node.attrib:
                self.output_range_max = safe_read(node,"merge_max", float, 1.0)

            if "grid_visible" in node.attrib:
                self.grid_visible = safe_read(node,"grid_visible", bool, True)

            if "auto_release" in node.attrib:
                self.auto_release = safe_read(node,"auto_release",bool, False)

            if "ignore-release" in node.attrib:
                self.ignore_release = safe_read(node,"ignore-release",bool, False)

            if "step-dir" in node.attrib:
                self.target_step_direction = safe_read(node,"step-dir", int, 1)

            if "steps" in node.attrib:
                csv = node.get("steps")
                self.target_step_list = gremlin.util.csv_to_floatlist(csv)

            self._stepped_latched = safe_read(node,"latched", bool, True)

            if "step-start-index" in node.attrib:
                self.target_step_start_index = safe_read(node,"step-start-index", int, 0)
            if "stepped-device-id" in node.attrib:
                self.stepped_device_id = node.get("stepped-device-id")

            if "stepped-input-id" in node.attrib:
                self.stepped_input_id = safe_read(node,"stepped-input-id", int, 0)
            
            if "override-input-type" in node.attrib:
                input_type = safe_read(node, "override-input-type", str, '')
                self.override_input_type = gremlin.input_types.InputType.to_enum(input_type)

            if "pulse-delay" in node.attrib:
                self.pulse_delay = safe_read(node, "pulse-delay", int, 250)
            if "repeat" in node.attrib:
                self.pulse_repeat = safe_read(node,"repeat",bool, False)
            if "repeat-delay" in node.attrib:
                self.pulse_repeat_delay = safe_read(node, "repeat-delay", int, 250)


            # curve data

            curve_node = util.get_xml_child(node,"curve-data")
            if curve_node is None:
                # older style
                curve_node = util.get_xml_child(node,"response-curve-ex")
                if curve_node is None:
                    curve_node = util.get_xml_child(node,"response-curve")

            
            if curve_node is not None:
                self.curve_data = gremlin.curve_handler.AxisCurveData()
                self.curve_data.calibration = gremlin.ui.axis_calibration.CalibrationManager().getCalibration(self.hardware_device_guid, self.hardware_input_id)
                self.curve_data._parse_xml(curve_node)
                self.curve_data.curve_update()

            # hat buttons
            if self.action_mode == VjoyAction.VJoyHatToButton:
                hat_nodes = util.get_xml_child(node,"hat_to_button", multiple = True)
                for node_hat in hat_nodes:
                    name = safe_read(node_hat,"name",str, "")
                    position = vjoy.vjoy.Hat.name_to_direction[name]
                    button_id = safe_read(node_hat,"input",int,1)
                    self.hat_map[position] = button_id
                    mode = safe_read(node_hat,"mode", str, "")
                    match mode.casefold():
                        case "hold":
                            mode = ButtonOutputMode.Hold
                        case "pulse":
                            mode = ButtonOutputMode.Pulse
                        case "press":
                            mode = ButtonOutputMode.Press
                        case "release":
                            mode = ButtonOutputMode.Release
                        case _:
                            # legacy mode
                            is_pulse = safe_read(node_hat,"pulse",bool, False)
                            mode = ButtonOutputMode.Pulse if is_pulse else ButtonOutputMode.Hold

                    self.hat_mode_map[position] = mode

                if "hat_sticky" in node.attrib:
                    self.hat_sticky = safe_read(node,"hat_sticky",bool, False)







        except ProfileError:
            self.vjoy_input_id = None
            self.vjoy_device_id = None

    def _generate_xml(self):
        """Returns an XML node encoding this action's data.

        :return XML node containing the action's data
        """
        node = ElementTree.Element(VjoyRemap.tag)
        node.set("vjoy", str(self.vjoy_device_id))

        save_exec_on_release = VjoyAction.is_command(self.action_mode) or \
                               self.action_mode in (VjoyAction.VJoyButtonPress,
                                                    VjoyAction.VJoyInvertAxis,
                                                    VjoyAction.VJoySetAxis,
                                                    VjoyAction.VJoyPulse)

        node.set(
            InputType.to_string(self.input_type),
            str(self.vjoy_input_id)
        )

        node.set("mode", safe_format(VjoyAction.to_string(self.action_mode), str))

        write_node_input = True

        if self.override_input_type is not None:
            node.set("override-input-type", gremlin.input_types.InputType.to_string(self.override_input_type))

        match self.action_mode:
            case VjoyAction.VJoyAxis:
                node.set("axis-type", safe_format(self.axis_mode, str))
                node.set("axis-scaling", safe_format(self.axis_scaling, float))
                node.set("axis_start_value", safe_format(self.axis_start_value, float))
                node.set("axis_start_value_enabled", safe_format(self.axis_start_value_enabled, bool))
                node.set("range_low", safe_format(self.button_range_min, float))
                node.set("range_high", safe_format(self.button_range_max, float))
                node.set("output_range_low", safe_format(self.output_range_min, float))
                node.set("output_range_high", safe_format(self.output_range_max, float))
                reverse = safe_format(self.reverse_configured, bool)
                node.set("reverse", reverse)

            case VjoyAction.VJoyButtonPress:
                # button, command or
                node.set("start_pressed", safe_format(self.start_pressed, bool))
                node.set("paired", safe_format(self.paired, bool))

            case VjoyAction.VJoySetAxis:
                node.set("target_value", safe_format(self.target_value, float))
                node.set("target_relative", safe_format(self.target_is_relative, bool))

            case VjoyAction.VJoyMergeAxis:
                node.set("merge_mode", MergeOperationType.to_string(self.merge_mode))
                if self.merge_device_id:
                    node.set("merge_device_id", self.merge_device_id)
                if self.merge_input_id:
                    node.set("merge_input_id", str(self.merge_input_id))
                node.set("merge_invert", safe_format(self.merge_invert, bool))
                node.set("merge_min", safe_format(self.output_range_min, float))
                node.set("merge_max", safe_format(self.output_range_max, float))
                node.set("merge_input_type", gremlin.input_types.InputType.to_string(self.merge_input_type))


            case VjoyAction.VJoyPulse:
                # uses button mode below
                node.set("pulse_delay", safe_format(self.pulse_delay, int))
                if self.pulse_repeat:
                    node.set("repeat", safe_format(self.pulse_repeat, bool))
                    node.set("repeat-delay", safe_format(self.pulse_repeat_delay, int))


            case VjoyAction.VJoyAxisToButton:
                node.set("range_low", safe_format(self.button_range_min, float))
                node.set("range_high", safe_format(self.button_range_max, float))
                node.set("range_mode", safe_format(self.button_mode.name, str))

            case VjoyAction.VJoyHatToButton:
                for position, button_id in self.hat_map.items():
                    node_hat = ElementTree.Element("hat_to_button")
                    name = vjoy.vjoy.Hat.direction_to_name[position]
                    node_hat.set("name",name)
                    node_hat.set("input", safe_format(button_id, int))
                    mode = self.hat_mode_map[position]
                    node_hat.set("mode", mode.name)
                    #node_hat.set("pulse", safe_format(is_pulse, bool)) # legacy
                    node.append(node_hat)
                    write_node_input = False

                node.set("hat_sticky", safe_format(self.hat_sticky, bool))

            case VjoyAction.VJoySetAxisStepped:
                node.set("step-dir", safe_format(self.target_step_direction, int))
                node.set("steps", gremlin.util.floatlist_to_csv(self.target_step_list))
                node.set("step-start-index", safe_format(self.target_step_start_index, int))
                node.set("latched", safe_format(self._stepped_latched, bool))
                if self.stepped_device_id:
                    node.set("stepped-device-id", self.stepped_device_id)
                if self.stepped_input_id:
                    node.set("stepped-input-id", str(self.stepped_input_id))

        node.set("auto_release", safe_format(self.auto_release,bool))
        node.set("ignore-release",safe_format(self.ignore_release,bool)) 
        
        if self.button_mode == ButtonOutputMode.Pulse:
            node.set("pulse-delay", safe_format(self.pulse_delay, int))
            if self.pulse_repeat:
                node.set("repeat", safe_format(self.pulse_repeat, bool))
                node.set("repeat-delay", safe_format(self.pulse_repeat_delay, int))

        if self.curve_data is not None:
            curve_node =  self.curve_data._generate_xml()
            node.append(curve_node)

        if VjoyAction.is_command(self.action_mode) or self.action_mode:
            node.set("start_pressed", safe_format(self.start_pressed, bool))
            node.set("paired", safe_format(self.paired, bool))

        if save_exec_on_release:
            node.set("exec_on_release", safe_format(self.exec_on_release, bool))

        node.set("grid_visible", safe_format(self.grid_visible, bool))

        if write_node_input:
            node.set("input", safe_format(self.vjoy_input_id, int))

        return node

    def _is_valid(self):
        """Returns whether or not the action is configured properly.

        :return True if the action is configured correctly, False otherwise
        """

        if self.vjoy_device_id is None or self.vjoy_input_id is None:
            return False
        return True


    def __str__(self):
        if self.action_mode in (VjoyAction.VJoySetAxis, VjoyAction.VJoyInvertAxis, VjoyAction.VJoyAxis):
            input_string = "axis"
        elif self.action_mode == VjoyAction.VJoyHat:
            input_string = "hat"
        elif self.action_mode in (VjoyAction.VJoyButtonPress, VjoyAction.VJoyButtonRelease, VjoyAction.VJoyPulse, VjoyAction.VJoyHatToButton):
            input_string = "button"
        elif self.action_mode == VjoyAction.VJoyMergeAxis:
            input_string = "merge axis"
        elif self.action_mode == VjoyAction.VJoySetAxisStepped:
            input_string = "stepped axis"
        else:
            input_string = f"unhandled: [{self.action_mode.name}]"
        return f"VjoyRemap: VJOY device: {self.vjoy_device_id} {input_string}: {self.vjoy_input_id}"
version = 1
name = "Vjoy Remap"
create = VjoyRemap


