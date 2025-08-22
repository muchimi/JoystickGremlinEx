# -*- coding: utf-8; -*-

# MaptoState - maps to a state

from __future__ import annotations
import logging
import math
import os
from lxml import etree as ElementTree

from PySide6 import QtCore, QtWidgets, QtGui

import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
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

        widget, layout = gremlin.ui.ui_common.getHContainer(["Default:",self._default_on_widget, self._default_off_widget])
        main_layout.addWidget(widget)

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        widget, layout = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget],left_stretch=True)
        main_layout.addWidget(widget)


    @QtCore.Slot(bool)
    def _default_changed(self, checked):
        widget = self.sender()
        self.default_value = widget.data

    @QtCore.Slot()
    def _ok_button_cb(self):
        ''' ok button pressed '''
        state = self.state_widget.text()
        if not state:
            gremlin.ui.ui_common.MessageBox(title = "Invalid State", prompt = f"State cannot be blank", parent = self)
            return
        sd = gremlin.ui.state_device.StateData()
        if sd.exists(state):
            gremlin.ui.ui_common.MessageBox(title = "Duplicate State", prompt = f"State {state} already exists", parent = self)
            return
        sd.register(state, self.default_value, self.description_widget.text())
        self.accept()
        
    def _cancel_button_cb(self):
        ''' cancel button pressed '''
        self.reject()       

    

    @property
    def key(self) -> str:
        return self.state_widget.text()
    
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

        self.chkb_exec_on_release = QtWidgets.QCheckBox("Exec on release")
        self.chkb_exec_on_release.setChecked(self.action_data.exec_on_release)
        self.chkb_exec_on_release.clicked.connect(self._exec_on_release_changed)

        self.main_layout.addWidget(self.chkb_exec_on_release)

        self.populate_selector()

        self.container_hat_widget = None
        self._create_hat_mapping()

        gremlin.util.singleShot(self._update_ui)

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
        key = self.button_press_dialog.key
        description = self.button_press_dialog.description
        self.action_data.key = key
        self.populate_selector()


    def populate_selector(self):
        ''' updates the available states '''
        with QtCore.QSignalBlocker(self.state_selector):
            self.state_selector.clear()
            sd = gremlin.ui.state_device.StateData()
            for key, data in sd.getStates().items():
                self.state_selector.addItem(key, data)

            key = self.action_data.key
            if key:
                index = self.state_selector.findText(key)
                if index >= 0:
                    self.state_selector.setCurrentIndex(index)
            else:
                # pick the first as the default
                self.action_data.key = self.state_selector.currentText()
            
            if self.state_selector.count():
                data = self.state_selector.currentData()
                self.setDescription(data.description)
                

        
    def setDescription(self, value):
        self.state_description_widget.setText(value if value else "n/a")

    @QtCore.Slot()
    def _state_changed(self):
        data = self.state_selector.currentData()
        self.setDescription(data.description)
        self.action_data.key = data.key
       

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


    @QtCore.Slot(bool)
    def _exec_on_release_changed(self, checked):
        self.action_data.exec_on_release = checked
        

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
        
        # create the state if it doesn't exist
        self.sd = gremlin.ui.state_device.StateData()
        key = self.action_data.key
        if key and not self.sd.exists(key):
            description = self.action_data.description
            self.sd.register(key,False, description if description else "auto-created state")


    def profile_start(self):
        self.verbose = gremlin.config.Configuration().verbose_mode_outputs
        device_guid = self.action_data.hardware_device_guid
        input_id = self.action_data.hardware_input_id
        value = gremlin.joystick_handling.get_hat(device_guid, input_id)
        if value in vjoy.vjoy.Hat.to_continuous_position:
            self.hat_position = vjoy.vjoy.Hat.to_continuous_position[value]
        else:
            self.hat_position = (0,0)
        self.pressed_hat_buttons = {}
        self.pulse_worker_map = {}  # map of (state_name) to pulse worker object
        

        
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

        if event.event_type == InputType.JoystickButton:
            key = self.action_data.key
            mode = self.action_data.mode
            is_pressed = event.is_pressed
            trigger = (is_pressed and not self.action_data.exec_on_release) or \
                    (not is_pressed and self.action_data.exec_on_release) or \
                    mode in ("actual","pulse")
            if trigger:
    
                match mode:
                    case "actual":
                        if verbose: syslog.info(f"STATE: set [{key}] ACTUAL {is_pressed}")
                        self.sd.setValue(key, is_pressed)
                    case "press":
                        if verbose: syslog.info(f"STATE: set [{key}] ON")
                        self.sd.setValue(key, True)
                        
                    case "release":
                        if verbose: syslog.info(f"STATE: set [{key}] OFF")
                        self.sd.setValue(key, False)
                    case "toggle":
                        is_pressed = not self.sd.value(key)
                        if verbose: syslog.info(f"STATE: set [{key}] TOGGLE -> {'ON' if value else 'OFF'}")
                        self.sd.setValue(key, is_pressed)
                    case "pulse":
                        if is_pressed:
                            if verbose: syslog.info(f"STATE: trigger start range pulse state {key}")
                            repeat_interval =  self.action_data.pulse_repeat_delay/1000 if self.action_data.pulse_repeat else -1
                            self.pulse_start(key, self.action_data.pulse_delay/1000, repeat_interval)
                        else:
                            self.pulse_stop(key)

        elif event.event_type == InputType.JoystickHat:
            # hat button handling
            position = event.raw_value
            pressed_positions = list(self.pressed_hat_buttons.keys())
            is_pressed = event.is_pressed
            mode = self.action_data.hat_mode_map[position]

            state_name = self.action_data.hat_map[position]
            self.hat_position = position
            
            if state_name:
                match mode:
                    case ButtonOutputMode.Pulse:
                        if is_pressed:
                            if verbose: syslog.info(f"VJOY: trigger start pulse state {state_name} hat {position}")
                            repeat_interval =  self.action_data.pulse_repeat_delay/1000 if self.action_data.pulse_repeat else -1
                            self.pulse_start(state_name, self.action_data.pulse_delay/1000, repeat_interval)
                            
                        else:
                            if verbose: syslog.info(f"VJOY: trigger stop pulse state {state_name} hat {position}")
                            self.pulse_stop(state_name)

                            # threading.Timer(0.01, self._fire_pulse, [self.vjoy_device_id, input_id, self.pulse_delay/1000, self.action_data.pulse_repeat, self.action_data.pulse_repeat_delay/1000]).start()
                    case ButtonOutputMode.Hold:
                        if is_pressed:
                            # release the prior buttons
                            for pressed_position in pressed_positions:
                                if position == pressed_position:
                                    continue
                                release_input_id = self.pressed_hat_buttons[pressed_position]
                                if release_input_id > 0:
                                        self.sd.setValue(state_name, False)
                                del self.pressed_hat_buttons[pressed_position]

                    case ButtonOutputMode.Press:
                        is_pressed = True
                        if position in self.pressed_hat_buttons:
                            del self.pressed_hat_buttons[position]
                    case ButtonOutputMode.Release:
                        is_pressed = False # force a release on trigger
                        if position in self.pressed_hat_buttons:
                            del self.pressed_hat_buttons[position]
                    case ButtonOutputMode.NoOp:
                        # do nothing
                        return True
                    
                # set the new button
                self.pressed_hat_buttons[position] = state_name
                self.sd.setValue(state_name, is_pressed)


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
                    state_name = self.pressed_hat_buttons[pressed_position]
                    if state_name:
                        self.sd.setValue(state_name, False)

                    del self.pressed_hat_buttons[pressed_position]


        return True
    
        

class MapToState(gremlin.base_profile.AbstractAction):

    """Action data for the map to State action.

    Map to State allows controlling of the State cursor using either a joystick
    or a hat.
    """

    name = "Map to State"
    tag = "map_to_state"
    
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
        
        self.key = None # state key
        self.description = None # state description (used to recreate the state if needed)
        self.mode = "toggle" # valid modes are "pressed", "released", "toggle", "pulse"
        self.pulse_delay = 250 # delay for pulse mode in milliseconds
        self.pulse_repeat = False # true if the pulse repeats while down
        self.pulse_repeat_delay  = 250 # repeat delay for pulse mode in milliseconds
        self.exec_on_release = False # true if trigger should execute on input release event
        self.hat_map = {} # map of button id keyed by hat position tuple
        self.hat_positions = list(vjoy.vjoy.Hat.to_continuous_direction.keys())
        self.hat_mode_map = {} # bool table keyed by hat position

        for position in self.hat_positions:
            self.hat_map[position] = "" # not mapped by default
            if position == (0,0):
                self.hat_mode_map[position] = ButtonOutputMode.NoOp # center do nothing
            else:
                self.hat_mode_map[position] = ButtonOutputMode.Hold # hold by default
            


    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"[{self.key}]"

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
        if "key" in node.attrib:
            self.key = node.get("key")
        if "description" in node.attrib:
            self.description = node.get("description")
        if "mode" in node.attrib:
            self.mode = node.get("mode")
        if "delay" in node.attrib:
            self.pulse_delay = safe_read(node,"delay",int, 250)
        if "exec_on_release" in node.attrib:
            self.exec_on_release = safe_read(node,"exec_on_release",bool, False)
        if "repeat" in node.attrib:
            self.pulse_repeat = safe_read(node,"repeat",bool, False)
        if "repeat-delay" in node.attrib:
            self.pulse_repeat_delay = safe_read(node, "repeat-delay", int, 250)



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
            node.set("key", self.key)
            if self.description:
                node.set("description", self.description)
            node.set("mode", self.mode)
            node.set("delay", safe_format(self.pulse_delay, int))
            node.set("exec_on_release", safe_format(self.exec_on_release, bool))
            if self.pulse_repeat:
                node.set("repeat", safe_format(self.pulse_repeat, bool))
                node.set("repeat-delay", safe_format(self.pulse_repeat_delay, int))


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
        return bool(self.key) # key has to be set for this to be valid


version = 1
name = "map_to_state"
create = MapToState
