# -*- coding: utf-8; -*-

# MaptoState - maps to a state

from __future__ import annotations
import logging
import math
import os
import traceback
from lxml import etree as ElementTree

from PySide6 import QtCore, QtWidgets, QtGui

import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
from gremlin.types import SyncMode
from gremlin.profile import read_bool, safe_read, safe_format
import gremlin.ui.state_device
import gremlin.ui.ui_common
import gremlin.ui.input_item

from gremlin import input_devices
from gremlin.types import ButtonOutputMode
import vjoy.vjoy
from gremlin.input_devices import VjoyAction, remote_state
import gremlin.joystick_handling
import psygnal
from psygnal import Signal
import enum, threading,time, random

import gremlin.util
from gremlin.util import *
import gremlin.ui.state_device
import html

syslog = logging.getLogger("system")


class StateAddDialog(gremlin.ui.ui_common.QRememberDialog):
    ''' add state dialog - allows state creation directly from the state mapper '''
    def __init__(self, parent = None):
        super().__init__(self.__class__.__name__, parent = parent)
        main_layout = QtWidgets.QVBoxLayout(self)
        self.setWindowTitle("Add State")
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        self.default_value = False

        widgets = []

        self.state_widget = gremlin.ui.ui_common.QDataLineEdit()
        widget, layout = gremlin.ui.ui_common.getGridContainer(["State:", self.state_widget])
        widgets.append(widget)

        self._state = None

        main_layout.addWidget(widget)

        self.description_widget = gremlin.ui.ui_common.QDataLineEdit()
        widget, layout = gremlin.ui.ui_common.getGridContainer(["Description:", self.description_widget])
        widgets.append(widget)



        main_layout.addWidget(widget)

        gremlin.ui.ui_common.synchronize_grids(widgets)


        self._default_on_widget = gremlin.ui.ui_common.QDataRadioButton("On", True)
        self._default_off_widget = gremlin.ui.ui_common.QDataRadioButton("Off", False)
        self._default_off_widget.setChecked(True)
        self._default_off_widget.clicked.connect(self._default_changed)    
        self._default_on_widget.clicked.connect(self._default_changed)

        widget, _ = gremlin.ui.ui_common.getHContainer(["Default:",self._default_on_widget, self._default_off_widget])
        main_layout.addWidget(widget)

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        widget, _ = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget],left_stretch=True)
        main_layout.addWidget(widget)


    @QtCore.Slot(bool)
    def _default_changed(self, checked):
        widget = self.sender()
        self.default_value = widget.data

    @QtCore.Slot()
    def _ok_button_cb(self):
        ''' ok button pressed '''
        key = self.state_widget.text()
        if not key:
            gremlin.ui.ui_common.MessageBox(title = "Invalid State", prompt = f"State cannot be blank", parent = self)
            return
        sd = gremlin.ui.state_device.StateData()
        if sd.exists(key):
            gremlin.ui.ui_common.MessageBox(title = "Duplicate State", prompt = f"State {key} already exists", parent = self)
            self._state = sd.getState(key)
            return
        self._state = sd.register(key, self.default_value, self.description_widget.text())
        
        self.accept()
        
    def _cancel_button_cb(self):
        ''' cancel button pressed '''
        self.reject()       

    

    @property
    def key(self) -> str:
        return self.state_widget.text()
    @property
    def state(self) -> gremlin.ui.state_device.StateInputItem:
        return self._state
    
    @property
    def description(self) -> str:
        return self.description_widget.text()
    
    
class MapToStateWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to modify a state  """

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, QtWidgets.QVBoxLayout, parent=parent)
        

    def _create_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        
        self.state_selector = gremlin.ui.ui_common.QComboBox()
        self.state_selector.currentIndexChanged.connect(self._state_changed)
        self.state_description_widget = QtWidgets.QLabel()

        self.add_widget = QtWidgets.QPushButton("Add")
        self.add_widget.setToolTip("Adds a new state")
        self.add_widget.clicked.connect(self._add_state)

        self.state_selector_widget,layout = gremlin.ui.ui_common.getHContainer(["State:", self.state_selector, self.add_widget])
        self.main_layout.addWidget(self.state_selector_widget)

        widget,layout = gremlin.ui.ui_common.getHContainer(["Description:", self.state_description_widget])
        self.main_layout.addWidget(widget)
 
        self.button_pulse_widget = gremlin.ui.ui_common.QDelayWidget()
        self.button_pulse_widget.setToolTip("Delay in milliseconds")
        self.button_pulse_widget.setValue(self.action_data.pulse_delay)
        self.button_pulse_widget.valueChanged.connect(self._value_changed)

        self.button_pulse_repeat_widget = gremlin.ui.ui_common.QDelayWidget()
        self.button_pulse_repeat_widget.setToolTip("Repeat delay in milliseconds")
        self.button_pulse_repeat_widget.setValue(self.action_data.pulse_repeat_delay)
        self.button_pulse_repeat_widget.valueChanged.connect(self._pulse_repeat_value_changed)

        self.button_repeat_widget = QtWidgets.QCheckBox("Pulse repeat")
        self.button_repeat_widget.setToolTip("When enabled, pulses are repeated while the input is triggered.")
        self.button_repeat_widget.setChecked(self.action_data.pulse_repeat)
        self.button_repeat_widget.clicked.connect(self._pulse_repeat_mode_changed)

        widgets = [
            self.button_pulse_widget,
            self.button_repeat_widget,
            self.button_pulse_repeat_widget,
        ]

        self.container_pulse_widget, _ = gremlin.ui.ui_common.getHContainer(widgets,"Pulse Options:")
        

        mode = self.action_data.mode
        widgets = []
        rb = gremlin.ui.ui_common.QDataRadioButton("Hold",data = "actual")
        rb.setToolTip("The state is set based on the pressed/release input state")
        if mode == "actual":
            rb.setChecked(True)
        rb.clicked.connect(self._mode_changed)
        widgets.append(rb)

        rb = gremlin.ui.ui_common.QDataRadioButton("Press (on)", data = "press")
        rb.setToolTip("Sets the state")
        if mode == "press":
            rb.setChecked(True)
        rb.clicked.connect(self._mode_changed)
        widgets.append(rb)
        rb = gremlin.ui.ui_common.QDataRadioButton("Release (off)", data = "release")
        rb.setToolTip("Releases the state")
        if mode == "release":
            rb.setChecked(True)
        rb.clicked.connect(self._mode_changed)
        widgets.append(rb)
        rb = gremlin.ui.ui_common.QDataRadioButton("Pulse", data = "pulse")
        rb.setToolTip("Pulses the state delay milliseconds (the state is set and released regardless of current state)")
        if mode == "pulse":
            rb.setChecked(True)
        rb.clicked.connect(self._mode_changed)
        widgets.append(rb)
        rb = gremlin.ui.ui_common.QDataRadioButton("Toggle", data = "toggle")
        rb.setToolTip("Toggles the state")
        if mode == "toggle":
            rb.setChecked(True)
        rb.clicked.connect(self._mode_changed)
        widgets.append(rb)

        self.mode_widget, self.mode_layout = gremlin.ui.ui_common.getHContainer(widgets,"Action:")
    
        self.main_layout.addWidget(self.mode_widget)

        self.main_layout.addWidget(self.container_pulse_widget)



        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        self._sync_widget = gremlin.ui.ui_common.QSyncModeWidget(mode = self.action_data.sync_mode, label = "State on profile start:", callback = self._sync_changed)

        self._reset_default_widget = gremlin.ui.ui_common.QDataCheckbox(label = "Reset to Default on stop",
                                                                        tooltip= "If enabled, state values will return to default values on profile stop",
                                                                        callback = self._handle_reset_default_changed,
                                                                        value = self.action_data.reset_default_on_stop
                                                                        )

        widgets = [self._execute_widget, self._reset_default_widget]
        widget, _ = gremlin.ui.ui_common.getHContainer(widgets)
        self.main_layout.addWidget(widget)

        widgets = [self._sync_widget]
        widget, _ = gremlin.ui.ui_common.getHContainer(widgets, left_margin =12)
        
        self.main_layout.addWidget(widget)

        self.populate_selector()

        self.container_hat_widget = None
        self._create_hat_mapping()

        gremlin.util.singleShot(self._update_ui)

    def _sync_changed(self, mode):
        self.action_data.sync_mode = mode

    @QtCore.Slot(bool)
    def _handle_reset_default_changed(self, checked : bool):
        self.action_data.reset_default_on_stop = checked

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked : bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked : bool):
        self.action_data.exec_on_release = checked        


    @QtCore.Slot(bool)
    def _pulse_repeat_mode_changed(self, checked : bool):
        self.action_data.pulse_repeat = checked
        self._update_ui()

    def _pulse_repeat_value_changed(self, value):
        ''' called when the pulse value changes '''
        if value >= 0:
            self.action_data.pulse_repeat_delay = value      

    @QtCore.Slot()
    def _add_state(self):
        ''' adds a new state '''
        self.button_press_dialog = StateAddDialog(self)
        self.button_press_dialog.accepted.connect(self._state_added)
        gremlin.util.centerDialog(self.button_press_dialog)
        self.button_press_dialog.show()        

    @QtCore.Slot()
    def _state_added(self):
        state = self.button_press_dialog.state
        self.action_data.state = state
        self.populate_selector()

    def _state_crud(self):
        # update the selector
        self.populate_selector()


    def populate_selector(self):
        gremlin.util.InvokeUiMethod(self._populate_selector_ui) # ensure on UI thread

    def _populate_selector_ui(self):
        ''' updates the available states '''
        with QtCore.QSignalBlocker(self.state_selector):
            self.state_selector.clear()
            sd = gremlin.ui.state_device.StateData()
            for key, data in sd.getStates().items():
                # syslog.info(f"found state: {key}")
                self.state_selector.addItem(key, data)

            state = self.action_data.state
            if state:
                index = self.state_selector.findText(state.key)
                if index != -1:
                    self.state_selector.setCurrentIndex(index)
                else:
                    syslog.warning(f"STATE: attempt to select state failed - [{state.key}] - state not found - defaulting to [{self.state_selector.currentText()}].")
                    
            else:
                key = self.action_data.key
                if key:
                    index = self.state_selector.findText(key)
                    if index != -1:
                        self.state_selector.setCurrentIndex(index)
                    else:
                        syslog.warning(f"STATE: attempt to select state failed - [{key}] - state not found - defaulting to [{self.state_selector.currentText()}].")
                else:
                    # pick the first as the default
                    self.action_data.state = self.state_selector.currentData()
            
            if self.state_selector.count():
                data = self.state_selector.currentData()
                self.setDescription(data.description)
                

        
    def setDescription(self, value):
        self.state_description_widget.setText(value if value else "n/a")

    @QtCore.Slot()
    def _state_changed(self):
        state = self.state_selector.currentData()
        self.setDescription(state.description)
        self.action_data.state = state
       

    def _populate_ui(self):
        """Populates the UI components."""
        pass

    @QtCore.Slot()
    def _mode_changed(self):
        widget = self.sender()
        mode = widget.data
        self.action_data.mode = mode
        self._update_ui()

    def _update_ui(self):
        if not Shiboken.isValid(self):
            return
        
        input_type = self._get_input_type()
        hat_visible = input_type == InputType.JoystickHat
        state_visible = not hat_visible
        repeat_visible = self.action_data.pulse_repeat
        pulse_visible = hat_visible or self.action_data.mode == "pulse"

        self.state_selector_widget.setVisible(state_visible)
        # self.button_pulse_widget.setVisible(state_visible and self.action_data.mode == "pulse")
        self.mode_widget.setVisible(state_visible)
        if self.container_hat_widget:
            self.container_hat_widget.setVisible(hat_visible)
            self.container_hat_options_widget.setVisible(hat_visible)
            self.container_hat_grid_widget.setVisible(hat_visible)


        self.container_pulse_widget.setVisible(pulse_visible)

        self.button_pulse_repeat_widget.setVisible(repeat_visible)


    @QtCore.Slot()
    def _value_changed(self, value):
        self.action_data.delay = value



    def _create_hat_mapping(self):


        if self._get_input_type() != InputType.JoystickHat:
            return

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
            vjoy_id = self.action_data.vjoy_id
            if vjoy_id in self.action_data:
                dev = self.action_data.vjoy_map[vjoy_id]
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
        state_name = cb.currentData()
        self.action_data.hat_map[position] = state_name

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
        
        sd = gremlin.ui.state_device.StateData()
        state_names = sd.getStateNames()
        positions = self.action_data.hat_positions
        for index, position in enumerate(positions):  # 9 positions - 8 cardinal and center push
            cb = self.cb_hat_list[index]
            with QtCore.QSignalBlocker(cb):
                cb.clear()
                cb.addItem("Not mapped", "")
                for state in state_names:
                    cb.addItem(state, state)

            mode = self.action_data.hat_mode_map[position]

            rb = self.rb_hat_list[position][int(mode)]
            with QtCore.QSignalBlocker(rb):
                rb.setChecked(True)

        self._load_hat_mapping()

    def _load_hat_mapping(self):
        ''' loads the hat data into the UI '''
        positions = self.action_data.hat_positions
        for index, position in enumerate(positions):  # 9 positions - 8 cardinal and center push
            state_name = self.action_data.hat_map[position] # 0 means disabled
            cb = self.cb_hat_list[index]
            state_index = cb.findData(state_name)
            if state_index != -1:
                with QtCore.QSignalBlocker(cb):
                    cb.setCurrentIndex(state_index)







class MapToStateFunctor(gremlin.base_profile.AbstractFunctor):

    """Implements the functionality required to move a State cursor.

    This moves the State cursor by issuing relative motion commands. This is
    only implemented for axis and hat inputs as they can control a cursor
    properly with a single input, at least partially.
    """

    # shared wiggle thread
    _wiggle_local_thread = None
    _wiggle_remote_thread = None
    _wiggle_local_stop_requested = False
    _wiggle_remote_stop_requested = False
    _State_controller = None


    def __init__(self, action : MapToState, parent = None):
        """Creates a new functor with the provided data.

        :param action contains parameters to use with the functor
        """
        super().__init__(action, parent)
        self.lock = threading.Lock()
        self._started = False
        
        # create the state if it doesn't exist
        self.sd = gremlin.ui.state_device.StateData()
        key = self.action_data.key

        self.hat_state_map = {} # holds the list of states to hat
        input_type = self.action_data.get_input_type()
        if input_type == InputType.JoystickHat:
            # load all the states we need to track
            positions = self.action_data.hat_positions
            for position in positions:  # 9 positions - 8 cardinal and center push
                state_name = self.action_data.hat_map[position]
                state : gremlin.ui.state_device.StateInputItem = self.sd.getState(state_name)
                self.hat_state_map[position] = state if not state.isExpression else None # don't set expression states

        
        if key and not self.sd.exists(key):
            description = self.action_data.description
            self.sd.register(key,False, description if description else "auto-created state")
        #self.debug_count = 0


    def profile_start(self):
        self.verbose = gremlin.config.Configuration().verbose_mode_state
        device_guid = self.action_data.hardware_device_guid
        input_id = self.action_data.hardware_input_id
        input_type = self.action_data.get_input_type()
        self.pressed_hat_buttons = {}
        is_pressed = False
        self.debug_count = 0
        match input_type:
            case InputType.JoystickHat:
                value = gremlin.joystick_handling.get_hat(device_guid, input_id)
                if value in vjoy.vjoy.Hat.to_continuous_position:
                    self.hat_position = vjoy.vjoy.Hat.to_continuous_position[value]
                else:
                    self.hat_position = (0,0)
                is_pressed = self.hat_position != (0,0)
                
            case InputType.JoystickButton:
                is_pressed = gremlin.joystick_handling.get_button(device_guid, input_id)

            case InputType.JoystickAxis:
                pass
        
        self.pulse_worker_map = {}  # map of (state_name) to pulse worker object
        if self.verbose:
            
            input_item = self.action_data.input_item
            syslog.info (f"STATE FUNCTOR PROFILE START SYNC: (map to state) [{self.action_data.state.key}] : mapped to input: {input_item.debug_display}")
            syslog.info (f"\tsync mode: [{self.action_data.sync_mode.name}]")


        # determine the startup state 
        match self.action_data.sync_mode:
            case SyncMode.Default:
                if self.verbose: syslog.info(f"\tset default : {self.action_data.state.default_value}")
                self.action_data.state.value = self.action_data.state.default_value
            case SyncMode.Input:
                if self.verbose: syslog.info(f"\t sync to input : {is_pressed}")
                
                if input_type == InputType.JoystickHat:
                    positions = self.action_data.hat_positions
                    for position in positions:  # 9 positions - 8 cardinal and center push
                        state = self.hat_state_map[position]
                        if state: # mapped
                            state.value = position == self.hat_position
                else:
                    # regular mapping
                    state = self.action_data.state
                    if state and not state.isExpression:
                        state.value = is_pressed
                    
       



                self.action_data.state.value = is_pressed
            case SyncMode.LastOrInput:
                last = self.action_data.state.lastValue
                if last is None:
                    if self.verbose: syslog.info(f"\tset last: use input value : {is_pressed}")
                    self.action_data.state.value = is_pressed
                else:
                    if self.verbose: syslog.info(f"\tset last: use last value : {last}")
                    self.action_data.state.value = last
            case SyncMode.LastOrDefault:
                last = self.action_data.state.lastValue
                if last is None:
                    if self.verbose: syslog.info(f"\tset last: use default value : {self.action_data.state.default_value}")
                    self.action_data.state.value = self.action_data.state.default_value
                else:
                    if self.verbose: syslog.info(f"\tset last: use last value : {last}")
                    self.action_data.state.value = last
            case SyncMode.Ignore:
                pass
                
        
    def profile_started(self):
        # occurs on profile start once profile start sequence is completed
        self._started = True

    def profile_stop(self):
        # occurs on profile stop
        self._started = False


        if self.action_data.reset_default_on_stop:
            if self.verbose: syslog.info("MAP TO STATE: reset state on profile stop enabled")
            # reset the state to the default position
            input_type = self.action_data.get_input_type()
            if input_type == InputType.JoystickHat:
                positions = self.action_data.hat_positions
                for position in positions:  # 9 positions - 8 cardinal and center push
                    state = self.hat_state_map[position]
                    if state: # mapped
                        state.value = state.default_value
                        if self.verbose: syslog.info(f"\t[{state.key}] -> {state.value}")
            else:
                # regular mapping
                state = self.action_data.state
                if state and not state.isExpression:
                    state.value = state.default_value
                    if self.verbose: syslog.info(f"\t[{state.key}] -> {state.value}")
                    
        

        
    def _pulse_on(self, data):
        ''' called when pulse is off '''
        state_name = data
        if self.verbose: syslog.info(f"Pulse ON {state_name}")
        self.sd.setValue(state_name, True)


    def _pulse_off(self, data):
        ''' called when pulse is off '''
        state_name = data
        if self.verbose: syslog.info(f"Pulse OFF {state_name}")
        self.sd.setValue(state_name, False)
        

    def pulse_start(self, key : str, duration : float, interval : float):
        ''' pulse setup '''
        if self.verbose: syslog.info(f"Pulse START state {key}duration: {duration:0.3f} interval: {interval:0.3f}")
        worker : gremlin.repeater.PulseWorker 
        if key in self.pulse_worker_map:
            worker = self.pulse_worker_map[key]
            if worker.is_running:
                # worker already running - ignore pulse request
                if self.verbose: syslog.info(f"\talready pulsing - ignored")
                return
        else:
            args = key
            worker = gremlin.repeater.PulseWorker(duration, interval, self._pulse_on, self._pulse_off, data = args)
            self.pulse_worker_map[key] = worker

        if self.verbose: syslog.info(f"\activate")
        worker.start()

    def pulse_stop(self, key: str):
        ''' request a pulse abort '''
        if self.verbose: syslog.info(f"Pulse STOP {key}")
        if key in self.pulse_worker_map:
            worker : gremlin.repeater.PulseWorker = self.pulse_worker_map[key]
            worker.stop()
            del self.pulse_worker_map[key]





    def process_event(self, event, value, extra_data = None):
        ''' processes an input event - must return True on success, False to abort the input sequence '''

        verbose = gremlin.config.Configuration().verbose_mode_state
        if verbose: syslog.info(f"STATE FUNCTOR: got event: [{key}] pressed: [{is_pressed}] trigger: [{trigger}] input type: [{input_type.name}] mode: [{mode}]")
    
        if not self._started:
            # trap events kicked off while profile start is going on
            if verbose: syslog.info(f"\tProfile not running - skipping")
            return False

        

        key = self.action_data.key
        mode = self.action_data.mode
        is_pressed = event.is_pressed
        trigger = (is_pressed and self.action_data.exec_on_press) or \
                (not is_pressed and self.action_data.exec_on_release) or \
                mode in ("actual","pulse")        



        input_type = event.getInputType()
        

  


        if trigger:
            # trigger mode (act as press)
            match input_type:
                case InputType.JoystickButton:
                    # button
                    match mode:
                        case "actual":
                            if verbose: syslog.info(f"STATE FUNCTOR: set [{key}] ACTUAL {is_pressed}")
                            self.sd.setValue(key, is_pressed)
                            
                        case "press":
                            if verbose: syslog.info(f"STATE FUNCTOR: set [{key}] ON")
                            self.sd.setValue(key, True)
                            
                        case "release":
                            if verbose: syslog.info(f"STATE FUNCTOR: set [{key}] OFF")
                            self.sd.setValue(key, False)
                            
                        case "toggle":
                            # current state
                            state = not self.sd.value(key)
                            if verbose: syslog.info(f"STATE FUNCTOR: set [{key}] TOGGLE -> {'ON' if state else 'OFF'}")
                            self.sd.setValue(key, state)
                            
                        case "pulse":
                            if is_pressed:
                                if verbose: syslog.info(f"STATE: trigger start range pulse state {key}")
                                repeat_interval =  self.action_data.pulse_repeat_delay/1000 if self.action_data.pulse_repeat else -1
                                self.pulse_start(key, self.action_data.pulse_delay/1000, repeat_interval)
                            else:
                                self.pulse_stop(key)


                case InputType.JoystickHat:
                    # hat button handling

                    if verbose and "comments" in event.extra_data:
                        syslog.info(f"STATE FUNCTOR: event comment: {event.extra_data["comments"]}")   

                    if event.extra_data and "old_position" in event.extra_data:
                        # hat press event has extra data to release
                        old_position = event.extra_data["old_position"]
                    else:
                        old_position = None
                    
                    # release the old position
                    if old_position:
                        if old_position in self.pressed_hat_buttons:
                            state_name = self.pressed_hat_buttons[old_position]
                            if state_name:
                                self.sd.setValue(state_name, False, force = True)
                            del self.pressed_hat_buttons[old_position]


                    position = event.raw_value
                    is_pressed = event.is_pressed
                    mode = self.action_data.hat_mode_map[position]

                    state_name = self.action_data.hat_map[position]
                    self.hat_position = position

                    if verbose: syslog.info(f"STATE FUNCTOR: received button hat event hat {position} pressed: {is_pressed}")

                    
                    if state_name:
                        match mode:
                            case ButtonOutputMode.Pulse:
                                if is_pressed:
                                    if verbose: syslog.info(f"STATE FUNCTOR: trigger start pulse state {state_name} hat {position}")
                                    repeat_interval =  self.action_data.pulse_repeat_delay/1000 if self.action_data.pulse_repeat else -1
                                    self.pulse_start(state_name, self.action_data.pulse_delay/1000, repeat_interval)
                                    
                                else:
                                    if verbose: syslog.info(f"STATE FUNCTOR: trigger stop pulse state {state_name} hat {position}")
                                    self.pulse_stop(state_name)

                                    # threading.Timer(0.01, self._fire_pulse, [self.vjoy_id, input_id, self.pulse_delay/1000, self.action_data.pulse_repeat, self.action_data.pulse_repeat_delay/1000]).start()
                            case ButtonOutputMode.Hold:
                                pass
                                
                            case ButtonOutputMode.Press:
                                if verbose: syslog.info(f"STATE FUNCTOR: state [{state_name}] press/on")
                                is_pressed = True
                                if position in self.pressed_hat_buttons:
                                    del self.pressed_hat_buttons[position]
                            case ButtonOutputMode.Release:
                                if verbose: syslog.info(f"STATE FUNCTOR: state [{state_name}] release/off")
                                is_pressed = False # force a release on trigger
                                if position in self.pressed_hat_buttons:
                                    del self.pressed_hat_buttons[position]
                            case ButtonOutputMode.NoOp:
                                # do nothing
                                return True
                            
                        # set the new button
                        if verbose: syslog.info(f"STATE FUNCTOR: state [{state_name}] set new state: {is_pressed}")
                        self.pressed_hat_buttons[position] = state_name
                        self.sd.setValue(state_name, is_pressed, force = True)


                    else:
                        # non trigger mode (release)
                        match mode:
                            case ButtonOutputMode.NoOp:
                                # do nothing
                                return True
                            case ButtonOutputMode.Press:
                                return True
                            case ButtonOutputMode.Release:
                                return True



        return True
    
        

class MapToState(gremlin.base_profile.AbstractAction):

    """Action data for the map to State action.

    Map to State allows controlling of the State cursor using either a joystick
    or a hat.
    """

    name = "Map to State"
    tag = "map_to_state"
    hint = "Sets, clear or toggles a state."
    
    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, True)

    functor = MapToStateFunctor
    widget = MapToStateWidget

    input_types = [
         InputType.JoystickButton,
         InputType.JoystickHat,
    ]

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent)
        self.parent = parent
        
        
        self.state : gremlin.ui.state_device.StateInputItem = None # mapped state for non-hat mappings
        self.description = None # state description (used to recreate the state if needed)
        self.mode = "toggle" # valid modes are "pressed", "released", "toggle", "pulse"
        self.pulse_delay = 250 # delay for pulse mode in milliseconds
        self.pulse_repeat = False # true if the pulse repeats while down
        self.pulse_repeat_delay  = 250 # repeat delay for pulse mode in milliseconds
        self.exec_on_press = True # true if trigger should execute on input press event
        self.exec_on_release = False # true if trigger should execute on input release event
        self.sync_mode = SyncMode.Ignore # ignore by default
        self.reset_default_on_stop = True # if set, when a profile stops, the state is reset to the default state value
        self.hat_map = {} # map of button id keyed by hat position tuple
        self.hat_positions = list(vjoy.vjoy.Hat.to_continuous_direction.keys())
        self.hat_mode_map = {} # bool table keyed by hat position

        for position in self.hat_positions:
            self.hat_map[position] = "" # not mapped by default
            if position == (0,0):
                self.hat_mode_map[position] = ButtonOutputMode.NoOp # center do nothing
            else:
                self.hat_mode_map[position] = ButtonOutputMode.Hold # hold by default
            

    @property
    def key(self) -> str:
        if self.state:
            return self.state.key
        return None

    def display_name(self):
        ''' returns a display string for the current configuration '''
        stub = ""
        if self.pulse_repeat:
            stub = f" (pulse) delay (ms): [{self.pulse_delay}] repeat (ms): [{self.pulse_repeat_delay}]"  
        return f"State: ({self.mode}]) [{self.key}] EOR: [{self.exec_on_release}]{stub}"

    def icon(self):
        """Returns the icon to use for this action.

        :return icon representing this action
        """
        return "mdi.state-machine"

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        # Need virtual buttons for button inputs on axes and hats
        return False

    def _parse_xml(self, node, data = None, extra_data = None):
        """Reads the contents of an XML node to populate this instance.

        :param node the node whose content should be used to populate this
            instance
        """
        sd = gremlin.ui.state_device.StateData()
        key = None
        state = None

        if "key" in node.attrib:
            key = node.get("key")
        if "state-id" in node.attrib:
            state_id = node.get("state-id")
            state = sd.getStateById(state_id)
        
        if not state and key:
            # grab state ID for legacy profiles
            state = sd.getState(key)

        if state:
            self.state = state
        else:
            # state not found - see if we can find the missing datas  
            syslog.warning(f"STATE: (map to state): [{key}] does not exist - creating state")
            state = sd._register(key)
            self.state = state


        if "description" in node.attrib:
            self.description = node.get("description")
        if "mode" in node.attrib:
            self.mode = node.get("mode")
        if "delay" in node.attrib:
            self.pulse_delay = safe_read(node,"delay",int, 250)
        if "exec_on_press" in node.attrib:
            self.exec_on_press = safe_read(node,"exec_on_press",bool, True)
        if "exec_on_release" in node.attrib:
            self.exec_on_release = safe_read(node,"exec_on_release",bool, False)
        if "repeat" in node.attrib:
            self.pulse_repeat = safe_read(node,"repeat",bool, False)
        if "repeat-delay" in node.attrib:
            self.pulse_repeat_delay = safe_read(node, "repeat-delay", int, 250)
        if "sync-mode" in node.attrib:
            self.sync_mode = SyncMode(safe_read(node,"sync-mode", int, 0))

        self.reset_default_on_stop = safe_read(node,"default-reset", bool, True)


        input_type = self.get_input_type()
        if input_type == InputType.JoystickHat:
            hat_nodes = gremlin.util.get_xml_child(node,"hat_to_button", multiple = True)
            for node_hat in hat_nodes:
                name = safe_read(node_hat,"name",str, "")
                position = vjoy.vjoy.Hat.name_to_direction[name]
                state_name = safe_read(node_hat,"input",str,"")
                self.hat_map[position] = state_name
                mode = safe_read(node_hat,"mode", str, "")
                match mode.casefold():
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
                        is_pulse = safe_read(node_hat,"pulse",bool, False)
                        mode = ButtonOutputMode.Pulse if is_pulse else ButtonOutputMode.Hold

                self.hat_mode_map[position] = mode        


    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(MapToState.tag)
        if self.key:
            node.set("key", html.escape(self.key))
            if self.state:
                node.set("state-id", self.state.id)
            if self.description:
                node.set("description", html.escape(self.description))
            node.set("mode", self.mode)
            node.set("delay", safe_format(self.pulse_delay, int))
            node.set("exec_on_press", safe_format(self.exec_on_press, bool))
            node.set("exec_on_release", safe_format(self.exec_on_release, bool))
            node.set("sync-mode", safe_format(self.sync_mode, int))
            if self.pulse_repeat:
                node.set("repeat", safe_format(self.pulse_repeat, bool))
                node.set("repeat-delay", safe_format(self.pulse_repeat_delay, int))

            node.set("default-reset", safe_format(self.reset_default_on_stop, bool))

            input_type = self.get_input_type()
            if input_type == InputType.JoystickHat:
                for position, state_name in self.hat_map.items():
                    node_hat = ElementTree.Element("hat_to_button")
                    name = vjoy.vjoy.Hat.direction_to_name[position]
                    node_hat.set("name",name)
                    if state_name:
                        node_hat.set("input", safe_format(state_name, str))
                    else:
                        node_hat.set("input", "")
                    mode = self.hat_mode_map[position]
                    node_hat.set("mode", mode.name)
                    #node_hat.set("pulse", safe_format(is_pulse, bool)) # legacy
                    node.append(node_hat)
                    
        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return True # bool(self.key) # key has to be set for this to be valid


    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell

        state = self.state
        if state:
            return state.to_html()
        return "N/A"

version = 1
name = "map_to_state"
create = MapToState
