# -*- coding: utf-8; -*-

# MaptoState - maps to a state

from __future__ import annotations
import logging
import math
import os
import traceback
import enum
from lxml import etree as ElementTree

from PySide6 import QtCore, QtWidgets, QtGui

import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
from gremlin.types import SyncMode, HatDirection
from gremlin.profile import read_bool, safe_read, safe_format
import gremlin.ui.state_device
import gremlin.ui.ui_common
import gremlin.ui.input_item

from gremlin import input_devices
from gremlin.types import ButtonOutputMode
import vjoy.vjoy
from gremlin.input_devices import VjoyAction, remote_state
import gremlin.joystick_handling
from psygnal import Signal
from shiboken6 import Shiboken

import gremlin.util
from gremlin.util import *

from gremlin.input_types import InputType
import gremlin.ui.ui_common

syslog = logging.getLogger("system")

class MapToTriggerWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget for the pause action."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, MapToTrigger))

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return        
        

        # self.action_selector_widget = gremlin.ui.ui_common.QDataComboBox(auto_adjust=True)
        # self.action_selector_widget.addItem("Joystick","joystick")

        self.device_selector_widget = gremlin.ui.ui_common.JoystickSelector(
            valid_types = [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat],
            callback = self._handle_device_selected
        )

        self.device_selector_widget.set_selection(
            device_id= self.action_data.device_id,
            input_type = self.action_data.input_type,
            input_id = self.action_data.input_id
            )
        
        
        
        margin = 12
        
        listen_widget = gremlin.ui.ui_common.Buttons.getListenWidget(callback = self._handle_listen_request)

        widgets = [ self.device_selector_widget, listen_widget]

        self.container_selector_widget, _ = gremlin.ui.ui_common.getHContainer(widgets)

        # button press widget
        self.button_release_widget = gremlin.ui.ui_common.QDataRadioButton("Released",
                                                                           value = not self.action_data.is_pressed,
                                                                           data = False,
                                                                           callback= self._handle_button_state_changed)
        self.button_press_widget = gremlin.ui.ui_common.QDataRadioButton("Pressed",
                                                                          value = self.action_data.is_pressed,
                                                                          data = True,
                                                                          callback= self._handle_button_state_changed,
                                                                        )
        # set button widgets
        widgets = [self.button_press_widget, self.button_release_widget]
        self.container_button_widget, _ = gremlin.ui.ui_common.getHContainer(widgets,"Set Button:", left_margin = margin)

        self.use_actual_widget =gremlin.ui.ui_common.QDataCheckbox("Use actual value",
                                                                   value = self.action_data.use_actual,
                                                                   callback = self._handle_use_actual_changed,
                                                                   tooltip = "When enabled, the virtual event will use the input value to determine the value of the trigger."
                                                                   )

        
        
        # set axis widgets
        self.value_widget = gremlin.ui.ui_common.QFloatLineEdit(value = self.action_data.value, callback=self._handle_value_changed)
        self.container_value_widget, _  = gremlin.ui.ui_common.getHContainer(self.value_widget,"Set Axis:", left_margin = margin)
        

        # set hat direction widgets
        self.direction_widget = gremlin.ui.ui_common.QHatSelectorComboBox(value = self.action_data.direction,
                                                                           callback = self._handle_direction_changed)
        
        self.container_direction_widget, _ = gremlin.ui.ui_common.getHContainer(self.direction_widget,"Set Position:", left_margin = margin)


        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        #self.main_layout.addWidget(self.action_selector_widget)
        
        self.main_layout.addWidget(self.container_selector_widget)

        self.main_layout.addWidget(self.use_actual_widget)
        self.main_layout.addWidget(self.container_button_widget)
        self.main_layout.addWidget(self.container_value_widget)
        self.main_layout.addWidget(self.container_direction_widget)

        self.main_layout.addWidget(self._execute_widget)

        self.warning_widget = gremlin.ui.ui_common.QWarningWidget()
        self.main_layout.addWidget(self.warning_widget)

        info_widget = gremlin.ui.ui_common.QInfoBox("This action will trigger a virtual event as if the input was triggered.")
        self.main_layout.addWidget(info_widget)

        

        self._update_ui()

    def _populate_ui(self):
        pass

    @QtCore.Slot(bool)
    def _handle_use_actual_changed(self, checked):
        self.action_data.use_actual = checked
        self._update_ui()


    def _handle_listen_request(self):
        ''' calls up a listen box to select the input '''
        dialog = gremlin.ui.ui_common.InputListenerWidget(
                [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat],
                callback = self._handle_listen_selection,
            )
        
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()
    
        dialog.setGeometry(
                int(geom.x() + geom.width() / 2 - 150),
                int(geom.y() + geom.height() / 2 - 75),
                300,
                150
            )
        
        dialog.show()

    def _handle_listen_selection(self, event):
        gremlin.util.InvokeUiMethod(self._handle_listen_selection_ui, event)

    def _handle_listen_selection_ui(self, event):
        dev : dinput.DeviceSummary = gremlin.joystick_handling.device_info_from_guid(event.device_guid)
        
        self.action_data.device_id = dev.device_id
        self.action_data.input_id = event.identifier
        self.action_data.input_type = event.event_type
        self.device_selector_widget.set_selection(
            device_id=self.action_data.device_id,
            input_type = self.action_data.input_type,
            input_id = self.action_data.input_id
            )
        
        self._update_ui()

              
    
    def _update_ui(self):
        ''' updates the UI based on the selected options '''
        input_type = self.action_data.get_input_type()



        axis_visible = False
        button_visible = False
        hat_visible = False
        exec_visible = False
        warning = None
        if not self.action_data.use_actual:
            
            match self.action_data.input_type:
                case InputType.JoystickAxis:
                    axis_visible = True
                case InputType.JoystickButton:
                    if input_type == InputType.JoystickAxis:
                        warning = "Axis input cannot be used to trigger buttons."
                    else:
                        button_visible = True
                        exec_visible = True
                case InputType.JoystickHat:
                    if input_type == InputType.JoystickAxis:
                        warning = "Axis input cannot be used to trigger hats."
                    else:
                        hat_visible = True
                        exec_visible = True
        
        else:
            # use actual - if a hat - select the hat position when the input is pressed
            
            if input_type == InputType.JoystickButton and self.action_data.input_type == InputType.JoystickHat:
                hat_visible = True

        self.container_value_widget.setVisible(axis_visible)
        self.container_button_widget.setVisible(button_visible)
        self.container_direction_widget.setVisible(hat_visible)
        self._execute_widget.setVisible(exec_visible)
        self.warning_widget.setText(warning)
        self.warning_widget.setVisible(warning is not None)



    def _handle_device_selected(self, data):
        #data = self.device_selector_widget.get_selection()

        
        self.action_data.device_id = gremlin.util.normalize_guid(data["device_id"])
        self.action_data.input_id = data["input_id"]
        self.action_data.input_type = data["input_type"]
        config = gremlin.config.Configuration()
        config.trigger_last_device_id = self.action_data.device_id
        config.trigger_last_input_id = self.action_data.input_id
        config.trigger_last_input_type = self.action_data.input_type

        dev = gremlin.joystick_handling.device_info_from_guid(self.action_data.device_id)
        syslog.info(f"received: {dev.name} [{dev.device_id}] input: {self.action_data.input_id} type: {self.action_data.input_type}")
        self._update_ui()

    def _handle_button_state_changed(self):
        widget = self.sender()
        self.action_data.is_pressed = widget.data

    def _handle_direction_changed(self, direction):
        self.action_data.direction = direction

    def _handle_value_changed(self, value : float):
        self.action_data.value = value

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked : bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked : bool):
        self.action_data.exec_on_release = checked            

    
class MapToTriggerFunctor(gremlin.base_profile.AbstractFunctor):

    def __init__(self, action_data, parent = None):
        super().__init__(action_data, parent)
        self.action_data = action_data
        

    def process_event(self, event : gremlin.event_handler.Event, value : gremlin.actions.Value, extra_data = None):
        
        use_actual = self.action_data.use_actual
        if use_actual:
            trigger = True
        else:
            trigger = (event.is_pressed and self.action_data.exec_on_press) \
                or (not event.is_pressed and self.action_data.exec_on_release)

        if trigger:

            el = gremlin.event_handler.EventListener()
            extra_data = {"trigger": True} # indicate the source of the event is a macro
            device_guid = gremlin.util.parse_guid(self.action_data.device_id)
            match self.action_data.input_type:
                case InputType.JoystickAxis:
                    if use_actual:
                        value = event.curve_value
                    else:
                        value = self.value
                    event = gremlin.event_handler.Event(
                        event_type= InputType.JoystickAxis,
                        device_guid= device_guid,
                        identifier=self.action_data.input_id,
                        value= value,
                        is_axis = True,
                        extra_data = extra_data
                    )
                case InputType.JoystickButton:
                    if event.is_axis:
                        # skip if the event is an axis
                        return True

                    if use_actual:
                        is_pressed = event.is_pressed
                    else:
                        is_pressed = self.action_data.is_pressed
                    event = gremlin.event_handler.Event(
                        event_type= InputType.JoystickButton,
                        device_guid= device_guid,
                        identifier=self.action_data.input_id,
                        value = is_pressed,
                        is_pressed = is_pressed,
                        extra_data = extra_data
                    )
                case InputType.JoystickHat:
                    if event.is_axis:
                        # skip if the event is an axis
                        return True
                    if use_actual:
                        input_type = self.action_data.get_input_type()
                        if input_type == InputType.JoystickHat:
                            position = event.value
                        else:
                            if event.is_pressed:
                                position = HatDirection.to_position(self.action_data.direction)            
                            else:
                                # release = center
                                position = HatDirection.Center.value

                    
                    event = gremlin.event_handler.Event(
                        event_type= InputType.JoystickHat,
                        device_guid= device_guid,
                        identifier=self.action_data.input_id,
                        value = position,
                        extra_data = extra_data
                    )

            event.is_virtual = True
            el.joystick_event.emit(event)

        return True

    
class MapToTrigger(gremlin.base_profile.AbstractAction):
    ''' map to trigger action '''
    name = "Trigger (Joystick)"
    tag = "trigger"
    hint = '''Triggers a joystick event'''


    input_types = [
         InputType.JoystickAxis,
         InputType.JoystickButton,
         InputType.JoystickHat,
    ]

    functor = MapToTriggerFunctor
    widget = MapToTriggerWidget


    def icon(self):
        return "mdi6.send"

    def requires_virtual_button(self):
        return False


    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent

    
        default_device = gremlin.joystick_handling.default_device()
        config = gremlin.config.Configuration()
        last_device_id = config.trigger_last_device_id
        dev = gremlin.joystick_handling.device_info_from_guid(last_device_id)
        if not dev:
            last_device_id = default_device.device_id
        
        last_input_id = config.trigger_last_input_id
        if not last_input_id:
            last_input_id = 1
                    
        last_input_type = config.trigger_last_input_type
        if not last_input_type:
            last_input_type = InputType.JoystickAxis
        

        self.device_id = last_device_id # id of the device to trigger
        self.input_type = last_input_type
        self.input_id = last_input_id
        self.action = "joystick" # trigger action "joystick" for now
        self.is_pressed = False # true if a button is pressed
        self.use_actual = False # true if the actual event value is used
        self.value = 0.0 # value if setting a joystick
        self.direction = HatDirection.Center # value if setting a hat
        
        self.exec_on_press = True # true if the mode should execute on input press
        self.exec_on_release = False # true if the mode should execute on input release
   

    def _generate_xml(self):
        ''' reads data from the profile '''
        node = ElementTree.Element("trigger")

        node.set("id", self._id)

        dev = gremlin.joystick_handling.device_info_from_guid(self.device_id)
        comment = f"Trigger device: {dev.name}  [{dev.device_id}]"
        node_comment = ElementTree.Comment(comment)
        node.append(node_comment)
        node.set("device", self.device_id)
        node.set("input-type", InputType.to_string(self.input_type))
        node.set("input", safe_format(self.input_id, int))
        node.set("exec-on-press", safe_format(self.exec_on_press, bool))
        node.set("exec-on-release", safe_format(self.exec_on_release, bool))
        node.set("actual", safe_format(self.use_actual, bool))
        
        match self.input_type:
            case InputType.JoystickAxis:
                node.set("value", safe_format(self.value,float))
            case InputType.JoystickButton:
                node.set("pressed", safe_format(self.is_pressed, bool))
            case InputType.JoystickHat:
                node.set("direction", self.direction.name)

        return node



    def _parse_xml(self, node, data = None, extra_data = None):
        input_type = safe_read(node,"input-type", str,"")
        if input_type:
            self.input_type = InputType.to_enum(input_type)
        self.input_id = safe_read(node,"input", int, 1)
        if "id" in node.attrib:
            self._id = node.get("id")
        self.device_id = safe_read(node,"device", str, "")
        action = safe_read(node,"action",str,"")
        if action:
            self.action = action

        self.use_actual = safe_read(node,"actual", bool, False)
        
        match self.input_type:
            case InputType.JoystickAxis:
                self.value = safe_read(node, "value", float, 0.0)
            case InputType.JoystickButton:
                self.is_pressed = safe_read(node,"pressed", bool, False)
            case InputType.JoystickHat:
                direction = safe_read(node,"direction", str, "Center")
                self.direction = HatDirection.to_enum(direction)

        self.exec_on_press = safe_read(node,"exec-on-press", bool, True)
        self.exec_on_release = safe_read(node,"exec-on-release", bool, False)

    
    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell
        table = ReportTable(cellpadding=4)    

        table.addField("Map to Trigger", self.mode.name)

        device : dinput.DeviceSummary = gremlin.joystick_handling.device_info_from_guid(self.device_id)
        if not device:
            table.addField("Unknown device", self.device_id)
        else:
            table.addField("Device", f"{device.name} [{device.device_id}]")
            match self.input_type:
                case InputType.JoystickAxis:
                    axis_name = device.getAxisName(self.input_id)
                    table.addField("Axis", f"{self.input_id} {axis_name}")
                    table.addField("Set value", f"{self.value:0.03f}")
                case InputType.JoystickButton:
                    table.addField("Button", f"{self.input_id}")
                    table.addField("Action", "Press" if self.is_pressed else "Release")
                case InputType.JoystickHat:
                    table.addField("Hat", f"{self.input_id}")
                    table.addField("Direction", self.direction.name)

        if self.exec_on_press:
            table.addField("Exec (press)", "Yes")
        if self.exec_on_release:
            table.addField("Exec (release)", "Yes")

        return table.to_html()
        

    def _is_valid(self):
        return True
  
        

version = 1
name = MapToTrigger.name
create = MapToTrigger
