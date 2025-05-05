# -*- coding: utf-8; -*-

# MaptoState - maps to a state

from __future__ import annotations
import logging
import math
import os
from lxml import etree as ElementTree

from PySide6 import QtCore, QtWidgets

import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
from gremlin.profile import read_bool, safe_read, safe_format
import gremlin.ui.state_device
import gremlin.ui.ui_common
import gremlin.ui.input_item

from gremlin import input_devices


import enum, threading,time, random

import gremlin.util


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
        

        self.state_selector = gremlin.ui.ui_common.QComboBox()
        self.state_selector.currentIndexChanged.connect(self._state_changed)
        self.state_description_widget = QtWidgets.QLabel()

        self.add_widget = QtWidgets.QPushButton("Add")
        self.add_widget.setToolTip("Adds a new state")
        self.add_widget.clicked.connect(self._add_state)

        widget,layout = gremlin.ui.ui_common.getHContainer(["State:", self.state_selector, self.add_widget])
        self.main_layout.addWidget(widget)

        widget,layout = gremlin.ui.ui_common.getHContainer(["Description:", self.state_description_widget])
        self.main_layout.addWidget(widget)
 
        self.delay_widget = gremlin.ui.ui_common.QDelayWidget()
        self.delay_widget.setToolTip("Delay in milliseconds")
        self.delay_widget.setValue(self.action_data.delay)
        self.delay_widget.valueChanged.connect(self._value_changed)

        mode = self.action_data.mode
        widgets = []
        rb = gremlin.ui.ui_common.QDataCheckbox("Press (on)",data = "press")
        rb.setToolTip("Sets the state")
        if mode == "press":
            rb.setChecked(True)
        rb.clicked.connect(self._mode_changed)
        widgets.append(rb)
        rb = gremlin.ui.ui_common.QDataCheckbox("Release (off)",data = "release")
        rb.setToolTip("Releases the state")
        if mode == "release":
            rb.setChecked(True)
        rb.clicked.connect(self._mode_changed)
        widgets.append(rb)
        rb = gremlin.ui.ui_common.QDataCheckbox("Pulse",data = "pulse")
        rb.setToolTip("Pulses the state delay milliseconds (the state is set and released regardless of current state)")
        if mode == "pulse":
            rb.setChecked(True)
        rb.clicked.connect(self._mode_changed)
        widgets.append(rb)
        rb = gremlin.ui.ui_common.QDataCheckbox("Toggle",data = "toggle")
        if mode == "toggle":
            rb.setChecked(True)
        rb.clicked.connect(self._mode_changed)
        widgets.append(rb)

        self.mode_widget, self.mode_layout = gremlin.ui.ui_common.getHContainer(widgets,"Action:")
    
        self.main_layout.addWidget(self.mode_widget)

        self.main_layout.addWidget(self.delay_widget)

        self.chkb_exec_on_release = QtWidgets.QCheckBox("Exec on release")
        self.chkb_exec_on_release.setChecked(self.action_data.exec_on_release)
        self.chkb_exec_on_release.clicked.connect(self._exec_on_release_changed)

        self.main_layout.addWidget(self.chkb_exec_on_release)

        self.populate_selector()

        gremlin.util.singleShot(self._update_ui)

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
        self.delay_widget.setVisible(self.action_data.mode == "pulse")


    @QtCore.Slot(bool)
    def _exec_on_release_changed(self, checked):
        self.action_data.exec_on_release = checked
        

    @QtCore.Slot()
    def _value_changed(self):
        self.action_data.delay = self.delay_widget.value()    

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
        sd = gremlin.ui.state_device.StateData()
        key = self.action_data.key
        if key and not sd.exists(key):
            description = self.action_data.description
            sd.register(key,False, description if description else "auto-created state")



    def _fire_pulse(self, key : str, delay : int):
        ''' pulses the state on/off '''
        self.lock.acquire()
        sd = gremlin.ui.state_device.StateData()
        value = sd.value(key) # current value
        sd.setValue(key, not value)
        time.sleep(delay/1000) # to seconds
        sd.setValue(key, value)
        self.lock.release()

        

    def process_event(self, event, value, extra_data = None):
        ''' processes an input event - must return True on success, False to abort the input sequence '''

        verbose = gremlin.config.Configuration().verbose
        if event.event_type == InputType.JoystickButton:
            trigger = (event.is_pressed and not self.action_data.exec_on_release) or \
                    (not event.is_pressed and self.action_data.exec_on_release)
            if trigger:
                sd = gremlin.ui.state_device.StateData()
                key = self.action_data.key
                mode = self.action_data.mode
                match mode:
                    case "press":
                        if verbose: syslog.info(f"STATE: set [{key}] ON")
                        sd.setValue(key, True)
                        
                    case "release":
                        if verbose: syslog.info(f"STATE: set [{key}] OFF")
                        sd.setValue(key, False)
                    case "toggle":
                        value = not sd.value(key)
                        if verbose: syslog.info(f"STATE: set [{key}] TOGGLE -> {'ON' if value else 'OFF'}")
                        sd.setValue(key, value)
                    case "pulse":
                        if verbose: syslog.info(f"STATE: set [{key}] PULSE")
                        if not self.lock.locked():
                            # wait for prior pulse to finish
                            threading.Timer(0.01, lambda: self._fire_pulse(key, self.action_data.delay)).start()
                

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

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container this action is part of
        """
        super().__init__(parent)
        self.parent = parent
        
        self.key = None # state key
        self.description = None # state description (used to recreate the state if needed)
        self.mode = "toggle" # valid modes are "pressed", "released", "toggle", "pulse"
        self.delay = 250 # delay for pulse mode in milliseconds
        self.exec_on_release = False # true if trigger should execute on input release event

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
        return True

    def _parse_xml(self, node, data = None):
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
            self.delay = safe_read(node,"delay",int, 250)
        if "exec_on_release" in node.attrib:
            self.exec_on_release = safe_read(node,"exec_on_release",bool, False)


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
            node.set("delay", safe_format(self.delay, int))
            node.set("exec_on_release", safe_format(self.exec_on_release, bool))
        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return bool(self.key) # key has to be set for this to be valid


version = 1
name = "map_to_state"
create = MapToState
