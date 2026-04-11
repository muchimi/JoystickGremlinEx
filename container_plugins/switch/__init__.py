# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026 
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
import time
from lxml import etree as ElementTree


from PySide6 import QtWidgets, QtCore, QtGui
import gremlin
import gremlin.actions
import gremlin.event_handler
import gremlin.ui.ui_common
import gremlin.ui.input_item
from gremlin.ui.input_item import AbstractContainerWidget, AbstractActionWidget
from gremlin.base_profile import AbstractContainer
import gremlin.base_conditions
import gremlin.joystick_handling
from gremlin.input_types import InputType
import enum
import gremlin.util    
from gremlin.util import safe_format, safe_read
import psygnal
from psygnal import Signal
from shiboken6 import Shiboken
import threading
import gremlin.config
from gremlin.types import SyncMode

syslog = logging.getLogger("system")

class SwitchModeType(enum.IntEnum):
    ''' possible switch modes '''
    NotSet = 0
    OnChange = 1
    OnPress = 2
    OnRelease = 3

    @staticmethod
    def to_display_name(value : SwitchModeType):
        return _switch_mode_to_display_lookup[value]
    
    @staticmethod
    def to_enum(value : str):
        return _switch_mode_to_enum_lookup[value]
    
    @staticmethod
    def to_string(value : SwitchModeType):
        return _switch_mode_to_string_lookup[value]
    
    @staticmethod
    def to_description(value : SwitchModeType):
        return _switch_mode_to_description_lookup[value]


_switch_mode_to_display_lookup = {
    SwitchModeType.NotSet: "Not set",
    SwitchModeType.OnChange: "On Change",
    SwitchModeType.OnPress: "On Press",
    SwitchModeType.OnRelease: "On Release"
}

_switch_mode_to_description_lookup = {
    SwitchModeType.NotSet: "",
    SwitchModeType.OnChange: "Action will execute when the input state changes",
    SwitchModeType.OnPress: "Actions will execute when the button is pressed",
    SwitchModeType.OnRelease: "Actions will execute when the button is released"
}

_switch_mode_to_string_lookup = {
    SwitchModeType.NotSet: "none",
    SwitchModeType.OnChange: "on_change",
    SwitchModeType.OnPress: "on_press",
    SwitchModeType.OnRelease: "on_release"
}

_switch_mode_to_enum_lookup = {
    "none" : SwitchModeType.NotSet ,
    "on_change" : SwitchModeType.OnChange,
    "on_press" : SwitchModeType.OnPress,
    "on_release" : SwitchModeType.OnRelease 
}


class SwitchWidget(QtWidgets.QWidget):
    ''' widget that holds the UI for a single switch position '''

    delete_item = Signal(object)

    def __init__(self, container : SwitchContainerWidget, profile_data : SwitchContainer, data : SwitchData, parent = None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.data = data
        self.profile_data = profile_data
        self.container = container


        # figure out the default device to use
        devices = list(self.profile_data.device_map.values())
        default_device = None
        selected_input_id = 1
        if data.device_id is not None:
            default_device = next((dev for dev in devices if dev.device_id == data.device_id), None)
            if default_device:
                if default_device.device_guid == data.device_guid:
                    # the merge device to pick is the same as the current device
                    if default_device.button_count == 1:
                        # there is only one input which is already used
                        self._selector_enabled = False

                if data.input_id is not None and data.input_id < default_device.button_count :
                    selected_input_id = data.input_id

        if not default_device:
            default_device = next((dev for dev in devices if dev.device_guid == self.profile_data.hardware_device_guid), None)
            if default_device:
                button_count = default_device.button_count
                if button_count == 1:
                    # there is only one input which is already used
                    self._selector_enabled = False

                else:
                    # pick a suitable input
                    input_id = data.input_id
                    if input_id < button_count:
                        # pick next if possoble
                        selected_input_id = input_id + 1
                    elif input_id > 1:
                        # pick one below if next not available
                        selected_input_id = input_id - 1        

        # allow buttons or hats as inputs to the switch
        input_types = [InputType.JoystickButton, InputType.JoystickHat]
        self.selector_widget = gremlin.ui.ui_common.QJoystickSelectorWidget(input_types,
                                                                            default_device,
                                                                            InputType.JoystickButton,
                                                                            selected_input_id,
                                                                            show_listen = True,
                                                                            callback = self._handle_input_changed
                                                                            )

        self.delete_button = gremlin.ui.ui_common.Buttons.getDeleteWidget(
            f"Delete position {data.index+1}",
            callback = self._delete_cb,
            tooltip = "Deletes this switch position"
            )

       
        widgets = []


        # switch mode selection widget
        mode_widgets = []

        for switch_type in SwitchModeType:
            if switch_type != SwitchModeType.NotSet:
                rb = gremlin.ui.ui_common.QDataRadioButton(
                    label = SwitchModeType.to_display_name(switch_type),\
                    data = switch_type,
                    value = data.mode == switch_type,
                    callbackEx = self._handle_switch_mode_changed)
                mode_widgets.append(rb)

        widget = gremlin.ui.ui_common.getHContainer(mode_widgets, widget_only = True)
        mode_widget = gremlin.ui.ui_common.getVContainer(
            [
                "Switch Execution Options:",
                widget
            ],
            widget_only = True)

        # header widget
        widget = gremlin.ui.ui_common.getHContainer(
            [
                gremlin.ui.ui_common.QFrameBox(f"<b>Position [{data.index+1}]</b>"),
                self.selector_widget,
                mode_widget,
                self.delete_button,
            ],
            use_vcontainers= True,
            widget_only = True)

        widgets.append(gremlin.ui.ui_common.QHorizontalLine())
        widgets.append(widget)
        

        # release mode options
        self.autorelease_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Auto Release",
            value = data.autoRelease,
             callback = self._handle_autorelease_changed)
        self.delay_widget = gremlin.ui.ui_common.QDelayWidget(
            value = data.releaseDelay,
            callback=self._handle_delay_changed
        )
        
        
        self.release_option_container = gremlin.ui.ui_common.getHContainer(
            [self.autorelease_widget, self.delay_widget], widget_only = True)
        
        widgets.append(self.release_option_container)


  
        # actions for this switch option
        action_set = next((action_set for i,action_set in enumerate(self.profile_data.action_sets) if i == data.index), None)
        if action_set is None:
            # add the action set
            self.profile_data.action_sets.append([])
            action_set = self.profile_data.action_sets[data.index]

        widget = self.container._create_action_set_widget(
            action_set, 
            view_type= gremlin.ui.ui_common.ContainerViewTypes.Action
        )
        widgets.append(widget)
        widget.redraw()
        widget.model.data_changed.connect(self._action_changed)
        self.action_widget = widget
        

        widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True)

        self.main_layout.addWidget(widget)


        self._update_ui()


    def _update_ui(self):
        ''' updates the Ui '''
        visible = self.data.mode == SwitchModeType.OnRelease
        self.release_option_container.setVisible(visible)
        delay_enabled = visible and self.data.autoRelease
        self.delay_widget.setEnabled(delay_enabled)

    @QtCore.Slot(bool)
    def _handle_autorelease_changed(self, checked : bool):
        self.data.autoRelease = checked
        self._update_ui()

    @QtCore.Slot(int)
    def _handle_delay_changed(self, value: int):
        self.data.releaseDelay = value


    def _handle_input_changed(self, device, input_id):
        ''' occurs when the input is changed '''
        self.data.device_guid = device.device_guid
        self.data.input_id = input_id

        
    @QtCore.Slot()
    def _delete_cb(self):
        if Shiboken.isValid(self):
            result = gremlin.ui.ui_common.ConfirmBox(f"Delete switch {self.data.index}?")
            if result:
                self.delete_item.emit(self.data)


    @QtCore.Slot()
    def _action_changed(self):
        ''' occurs when the action list changes '''
        if Shiboken.isValid(self):
            self.action_widget.redraw()
            self.container.container_modified.emit()


    @QtCore.Slot(object, bool)
    def _handle_switch_mode_changed(self, widget, checked : bool):
        ''' mode changed '''
        if Shiboken.isValid(self):
            if checked:
                mode = widget.data
                self.data.mode = mode

class SwitchContainerWidget(AbstractContainerWidget):

    """Container which holds a sequence of actions."""

    def __init__(self, profile_data : SwitchContainer, parent=None):
        """Creates a new instance.

        :param profile_data the profile data represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(profile_data, parent)
        self.action_data = profile_data

    def _update_ui(self):
        ''' redraws the entire switch content '''
        if not Shiboken.isValid(self):
            return

        self._create_action_ui()

    def _create_action_ui(self):
        """Creates the UI components."""
        if not Shiboken.isValid(self):
            return
        self._widget_map = {} # map of widgets by position index

        self.profile_data.create_or_delete_virtual_button()
        self.action_selector = gremlin.ui.ui_common.ActionSelector(
            self.profile_data.get_input_type(),
            self.profile_data.input_item,
        )

        self.action_selector.inputItem = self.profile_data.input_item
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.action_paste.connect(self._paste_action)

        self.header_widget = QtWidgets.QWidget()
        self.header_widget.setContentsMargins(0,0,0,0)
        self.header_layout = QtWidgets.QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(0,0,0,0)

        # positions
        self.header_layout.addWidget(QtWidgets.QLabel(f"<b>Defined Switch Positions: {self.profile_data.position_count}</b>"))
        
        # switch positions
        self.add_position_widget = gremlin.ui.ui_common.Buttons.getAddWidget(
            "Add a new switch position",
            tooltip="Adds a new switch position to the switch",
            callback = self._handle_add_position)
        
        self.header_layout.addWidget(self.add_position_widget)

        # sync option
        sync_modes = [SyncMode.Ignore, SyncMode.Input]
        sync_widget = gremlin.ui.ui_common.QSyncModeWidget(mode = self.profile_data.sync_mode, label = "State on profile start:", callback = self._handle_sync_changed, sync_modes= sync_modes)

        self.header_layout.addWidget(sync_widget)

        self.header_layout.addStretch()

        self.action_layout.addWidget(self.header_widget)


        ''' creates the switch entries '''
        data : SwitchData
        for data in self.profile_data.position_data.values():
            self._create_selector_ui(data)

    def _handle_sync_changed(self, mode):
        self.profile_data.sync_mode = mode        

    def _create_selector_ui(self, data : SwitchData):
        ''' creates the input selector '''
        # merge operations

        switch_widget = SwitchWidget(self, self.profile_data, data)
        switch_widget.delete_item.connect(self._delete_cb)
        self.action_layout.addWidget(switch_widget)
        self._widget_map[data.index] = switch_widget
        self.action_widget = switch_widget.action_widget
        self.action_widgets.append(switch_widget.action_widget)



    def _create_condition_ui(self):
        if self.profile_data.action_sets:
            for i, action in enumerate(self.profile_data.action_sets):
                widget = self._create_action_set_widget(
                    self.profile_data.action_sets[i],
                    f"Switch {i+1} Action(s):",
                    gremlin.ui.ui_common.ContainerViewTypes.Conditions
                )
                self.activation_condition_layout.addWidget(widget)
                widget.redraw()
                widget.model.data_changed.connect(self.container_modified.emit)

    def _add_action(self, action_name):
        """Adds a new action to the container.

        :param action_name the name of the action to add
        """
        gremlin.util.pushCursor()
        try:
            plugin_manager = gremlin.plugin_manager.ActionPlugins()
            action_item = plugin_manager.get_class(action_name)(self.profile_data)
            self.profile_data.add_action(action_item)
            self.container_modified.emit()
            self.action_widget.redraw()
        finally:
            gremlin.util.popCursor()

    def _handle_add_position(self):
        gremlin.util.InvokeUiMethod(self._handle_add_position_ui)

    def _handle_add_position_ui(self):
        index = len(self.profile_data.position_data)
        used_inputs = [data.input_id for data in self.profile_data.position_data.values()]
        device_id = self.profile_data.hardware_device_id
        device = self.profile_data.device_map[device_id]

        input_id = 0
        for id in range(device.button_count):
            if not id in used_inputs:
                input_id = id
                break

        self.profile_data.position_data[index] = SwitchData(index,self.profile_data.hardware_device_guid, input_id, SwitchModeType.OnChange)

        self._reload_ui()


    def _reload_ui(self):
        # reload the UI
        self.action_widgets.clear()
        syslog.info("reload")
        
        # re-create the layout and place it inside the dock widget
        Shiboken.delete(self.action_layout)
        self.action_layout = QtWidgets.QVBoxLayout(self.action_tab_widget)
        self._update_ui()


    def _delete_cb(self, data):
        del self.profile_data.position_data[data.index]
        gremlin.util.InvokeUiMethod(self._reload_ui)



    def _paste_action(self, action, container):
        ''' pastes an action '''
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action, self.profile_data)
        self.profile_data.add_action(action_item)
        self.container_modified.emit()

    def _handle_interaction(self, widget, action):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """
        # Find the index of the widget that gets modified
        index = self._get_widget_index(widget)

        if index == -1:
            syslog.warning(
                "Unable to find widget specified for interaction, not doing "
                "anything."
            )
            return

        # Perform action
        if action == gremlin.ui.input_item.ActionSetView.Interactions.Up:
            if index > 0:
                self.profile_data.action_sets[index],\
                    self.profile_data.action_sets[index-1] = \
                    self.profile_data.action_sets[index-1],\
                    self.profile_data.action_sets[index]
        if action == gremlin.ui.input_item.ActionSetView.Interactions.Down:
            if index < len(self.profile_data.action_sets) - 1:
                self.profile_data.action_sets[index], \
                    self.profile_data.action_sets[index + 1] = \
                    self.profile_data.action_sets[index + 1], \
                    self.profile_data.action_sets[index]
        if action == gremlin.ui.input_item.ActionSetView.Interactions.Delete:
            del self.profile_data.action_sets[index]

        self.container_modified.emit()

    def _get_window_title(self):
        """Returns the title to use for this container.

        :return title to use for the container
        """
        return f"Switch: {" -> ".join([", ".join([a.name for a in actions]) for actions in self.profile_data.action_sets])}"


class SwitchContainerFunctor(gremlin.base_profile.AbstractSelfTriggerFunctor):

    def __init__(self, container : SwitchContainer, parent = None):
        super().__init__(container, parent)
        self.action_data :  SwitchContainer = container

        self.index = 0
        self.last_execution = 0.0
        self.last_value = None

        # Determine if we need to switch the action index after a press or
        # release event. Only for container conditions this is necessary to
        # ensure proper cycling.
        self.switch_on_press = False
        if container.has_conditions:
            for cond in container.activation_condition.conditions:
                if isinstance(cond, gremlin.base_conditions.InputActionCondition):
                    if cond.comparison == "press":
                        self.switch_on_press = True

        self.verbose = False
        self.timer = None # autorelease timer
        self._last_data_pressed = None # id of data that was last pressed
        self._started = False

    def profile_start(self):
        ''' called on profile start '''

        if self._started:
            return
        
        self._started = True
        self.verbose = gremlin.config.Configuration().verbose_mode_switch

        data : SwitchData

        # reset the tracking state data
        for data in self.action_data.position_data.values():
            data.state = None # reset tracking state
            data.releaseEvent = None
            data.releaseValue = None
            data.releaseExtraData = None


    def profile_after_start(self):
        ''' occurs after the start is completed '''

        # check the sync - trigger on the first button pressed
        if self.action_data.sync_mode == SyncMode.Input:
            
            trigger = False
            # look for pressed input first
            for data in self.action_data.position_data.values():
                if not trigger:
                    if data.mode == SwitchModeType.OnPress:
                        device_guid = data.device_guid
                        input_id = data.input_id
                        input_type = data.input_type

                        match input_type:
                            case InputType.JoystickHat:
                                hat_position = gremlin.joystick_handling.get_hat_position(data.device_guid, data.input_id)
                                if hat_position != (0,0):
                                    event = gremlin.event_handler.Event(event_type = input_type,
                                                                    identifier = input_id,
                                                                    value = hat_position,
                                                                    is_pressed = True,
                                                                    device_guid = device_guid,
                                                                )
                                    if self.verbose: syslog.info(f"SWITCH: auto trigger due to input sync: pressed: [{is_pressed}]")
                                    self.process_event(event, event.value)
                                    trigger = True
                            case InputType.JoystickButton:
                                # sync and invert as needed
                                is_pressed = gremlin.joystick_handling.get_button(data.device_guid, data.input_id)
                                if is_pressed:
                                    event = gremlin.event_handler.Event(event_type = input_type,
                                                                    identifier = input_id,
                                                                    value = is_pressed,
                                                                    is_pressed = is_pressed,
                                                                    device_guid = device_guid,
                                                                )
                                    if self.verbose: syslog.info(f"SWITCH: auto trigger due to input sync: pressed: [{is_pressed}]")
                                    self.process_event(event, event.value)
                                    trigger = True

            if not trigger:
                # not triggered - look for the first released input as the sync position
                for data in self.action_data.position_data.values():
                    if not trigger:
                        if data.mode == SwitchModeType.OnRelease:
                            device_guid = data.device_guid
                            input_id = data.input_id
                            input_type = data.input_type

                            match input_type:
                                case InputType.JoystickHat:
                                    hat_position = gremlin.joystick_handling.get_hat_position(data.device_guid, data.input_id)
                                    if hat_position == (0,0):
                                        event = gremlin.event_handler.Event(event_type = input_type,
                                                                        identifier = input_id,
                                                                        value = hat_position,
                                                                        is_pressed = is_pressed,
                                                                        device_guid = device_guid,
                                                                    )
                                        if self.verbose: syslog.info(f"SWITCH: auto trigger due to input sync: pressed: [{is_pressed}]")
                                        self.process_event(event, event.value)
                                        trigger = True
                                        
                                case InputType.JoystickButton:
                                    # sync and invert as needed
                                    is_pressed = gremlin.joystick_handling.get_button(data.device_guid, data.input_id)
                                    if not is_pressed:
                                        event = gremlin.event_handler.Event(event_type = input_type,
                                                                        identifier = input_id,
                                                                        value = is_pressed,
                                                                        is_pressed = is_pressed,
                                                                        device_guid = device_guid,
                                                                    )
                                        if self.verbose: syslog.info(f"SWITCH: auto trigger due to input sync: pressed: [{is_pressed}]")
                                        self.process_event(event, event.value)
                                        trigger = True




    def profile_stop(self):
        ''' called on profile stop '''
        if self.timer:
            self.timer.cancel()
            self.timer = None

        self._started = False


    def latch_extra_inputs(self, container_condition_functors = None, action_condition_functors = None):
        ''' returns the list of extra devices to latch to this functor (device_guid, input_type, input_id) '''
        latch_list = []
        data : SwitchData
        for data in self.action_data.position_data.values():
            latch_list.append((data.device_guid, InputType.JoystickButton, data.input_id))
        return latch_list

    def process_event(self, event : gremlin.event_handler.Event, value : gremlin.actions.Value, extra_data = None):
        if event.is_axis:
            # not a switch
            return True
        elif event.event_type == InputType.JoystickHat:
            is_hat = True
            is_pressed = value.current != (0,0)
        else:
            is_pressed = event.is_pressed
            is_hat = False
        
        data : SwitchData
        
        # process each switch option
        for data in self.action_data.position_data.values():
            if data.device_guid != event.device_guid:
                continue
            if data.input_id != event.identifier:
                continue

            if self.verbose: syslog.info(f"SWITCH: position [{data.index + 1}] mode: [{data.mode.name}]")
            match data.mode:
                case SwitchModeType.OnChange:
                    # trigger on input change
                    if self.verbose: syslog.info(f"\tinput changed - pressed: [{is_pressed}]")
                    self._trigger(data.index, event, value, extra_data)
                    
                case SwitchModeType.OnPress:
                    # position triggers on press
                    
                    if is_pressed and data.state:
                        # already pressed
                        if self.verbose: syslog.info("\tskip: already pressed")
                        continue

  
                    if is_pressed:
                        if self.verbose: syslog.info("\ttrigger input press")
                        self._trigger_press(data, event.press_event(), value, extra_data)
                        break
                        
                    
                case SwitchModeType.OnRelease:
                    # position triggers on release
                    if is_pressed:
                        # not a release event
                        continue 
                    
                    if self.verbose: syslog.info("\ttrigger input release [press event]")
                    # trigger the press for the position
                    self._trigger_press(data, event.press_event(), value, extra_data)

                    # schedule a release if there's a delay
                    if data.autoRelease:
                        if self.verbose: syslog.info("\tschedule autorelease")
                        if self.timer:
                            self.timer.cancel()
                        self.timer = threading.Timer(interval = data.releaseDelay/1000,
                                                function = lambda : self._trigger_autorelease(data))
                        # trigger the release
                        self.timer.start()

                    
            
        
        return False # stop execution past this container
    
    def _trigger_press(self, data, event, value, extra_data : dict = None):
        ''' triggers the press trigger - this clears the other inputs '''
        if not data.state:
            self._trigger(data.index, event.press_event(), value, extra_data)
            data.state = True
            data.releaseEvent = event.release_event()
            data.releaseValue = value
            data.releaseExtraData = extra_data

            # release all the other positions
            data_list = [d for d in self.action_data.position_data.values() if d != data and d.state]
            for d in data_list:
                if self.verbose: syslog.info(f"\ttrigger input release for position [{data.index+1}]")
                self._trigger(d.index,
                                d.releaseEvent, 
                                d.releaseValue,
                                d.releaseExtraData
                                )
                d.state = False
        

    def _trigger_autorelease(self, data):
        if self.verbose: syslog.info("\tskip: trigger input release [autorelease event]")
        data.state = False # indicate released
        self._trigger(data.index,
                      data.releaseEvent,
                      data.releaseValue,
                      data.releaseExtraData)
        self.timer = None



class SwitchData():
    ''' data block for each switch position '''
    def __init__(self, index = -1, device_guid = None, input_type = None, input_id = None, mode : SwitchModeType = SwitchModeType.NotSet):
        self.index = index # sequence
        self.device_guid = device_guid
        self.input_id = input_id
        self.input_type = input_type
        self.mode = mode
        self.device_id = gremlin.util.normalize_guid(device_guid)
        self.action_set = None # data associated with this set
        self.state = None # true if the switch position was triggered (not persisted), None = no state
        self.autoRelease = False # autorelease the switch position if in release mode (this will automatically trigger a press/release after the delay) - default = do not autorelease
        self.releaseDelay = 250 # release delay in milliseconds if the switch is setup for a release

        self.releaseEvent = None # event data for the release
        self.releaseValue = None # value for the release
        self.releaseExtraData = None # extra data for the release

    @property
    def device(self) -> gremlin.ui.ui_common.DeviceSummary | None:
        ''' gets the device associated with this entry '''
        if self.device_guid:
            return gremlin.joystick_handling.getDevice(self.device_guid)
        return None

    def _generate_xml(self):
        ''' create xml data '''
        node = ElementTree.Element("switch")
        node.set("index", str(self.index))
        node.set("mode", SwitchModeType.to_string(self.mode))
        node.set("input_id", str(self.input_id))
        node.set("device_id", self.device_id)
        node.set("input-type", InputType.to_string(self.input_type))
        node.set("release-delay", safe_format(self.releaseDelay, int))
        node.set("auto-release", safe_format(self.autoRelease, bool))
        return node
    
    def _parse_xml(self, node, data = None, extra_data = None):
        ''' read xml data '''
        if node.tag == "switch":
            if "index" in node.attrib:
                self.index = safe_read(node, "index", int, -1)
            if "mode" in node.attrib:
                self.mode = SwitchModeType.to_enum(node.get("mode"))
            if "input_id" in node.attrib:
                # old style
                self.input_id = safe_read(node, "input_id", int, 0)
           
            if "device_id" in node.attrib:
                self.device_id = node.get("device_id")
                self.device_guid = gremlin.util.parse_guid(self.device_id)

            if "input-type" in node.attrib:
                self.input_type = InputType.to_enum(safe_read(node, "input-type", str, ""))
            else:
                # get a default
                device = gremlin.joystick_handling.getDevice(self.device_guid)
                # default to a button
                self.input_type = InputType.JoystickButton
                if device is not None:
                    if self.input_id < device.button_count:
                        self.input_type = InputType.JoystickButton
                    elif self.input_id < device.hat_count:
                        self.input_type = InputType.JoystickHat
                
            # release delay
            self.releaseDelay = safe_read(node,"release-delay", int, 250)
            self.autoRelease = safe_read(node,"auto-release", bool, True)
        
    

    

class SwitchContainer(AbstractContainer):

    """Represents a container which holds multiplier actions.

    The actions will trigger one after the other with subsequent activations.
    A timeout, if set, will reset the sequence to the beginning.
    """

    name = "Switch"
    tag = "switch"
    hint = '''Use this container to define multiple input triggers and perform them when the input changes, is pressed, or is released.
This feature is primarily intended for three way switches but can be used for any other use that requires an action to trigger on
an input toggle, press or release.  Multiple inputs can be specified for latching purposes.'''

    # override default allowed inputs here
    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat
    ]

    interaction_types = [
        # gremlin.ui.input_item.ActionSetView.Interactions.Up,
        # gremlin.ui.input_item.ActionSetView.Interactions.Down,
        gremlin.ui.input_item.ActionSetView.Interactions.Delete,
    ]

    functor = SwitchContainerFunctor
    widget = SwitchContainerWidget

    def __init__(self, parent=None, node = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node)
        self.timeout = 0.0
        self.sync_mode = SyncMode.Ignore # default sync mode on profile start

        self.position_data = {}  # data block indexed by position index
        self.position_data[0] = SwitchData(0, self.hardware_device_guid, self.hardware_input_type, self.hardware_input_id, SwitchModeType.OnPress)
        self.position_data[1] = SwitchData(1, self.hardware_device_guid,  self.hardware_input_type, self.hardware_input_id, SwitchModeType.OnRelease)

        self.device_map = {}  # device list and buttons keyed by device_id(str)
        self.device_button_map = {} 
        devices = sorted(gremlin.joystick_handling.button_input_devices(), key=lambda x: x.name)
    
        for dev in devices:
            self.device_map[dev.device_id] = dev

    @property
    def position_count(self) -> int:
        return len(self.position_data)

    def _parse_xml(self, node, data = None, extra_data = None):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """

        if "sync-mode" in node.attrib:
            self.sync_mode = SyncMode(safe_read(node,"sync-mode", int, 0))
        
        # get the switch nodes
        switch_nodes = gremlin.util.get_xml_child(node, "switch",True)
        
        

        for child in switch_nodes:
            data = SwitchData()
            data._parse_xml(child)
            self.position_data[data.index] = data
            self.action_sets.append([])
        

    def _generate_xml(self):
        """Returns an XML node representing this container's data.

        :return XML node representing the data of this container
        """
        node = ElementTree.Element("container")
        node.set("type", SwitchContainer.tag)
        node.set("sync-mode", safe_format(self.sync_mode, int))

        data : SwitchData
        for data in self.position_data.values():
            child = data._generate_xml()
            node.append(child)

        # save the actions (the load is done in the base class)
        for actions in self.action_sets:
            as_node = ElementTree.Element("action-set")
            for action in actions:
                as_node.append(action.to_xml())
            node.append(as_node)
        return node

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return True


# Plugin definitions
version = 1
name = "switch"
create = SwitchContainer
