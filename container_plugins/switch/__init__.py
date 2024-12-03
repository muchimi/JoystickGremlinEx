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
import gremlin.joystick_handling
from gremlin.input_types import InputType
import enum
import gremlin.util    
from gremlin.util import safe_format, safe_read

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

    delete_item = QtCore.Signal(object)

    def __init__(self, container : SwitchContainerWidget, profile_data : SwitchContainer, data : SwitchData, parent = None):
        super().__init__(parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.data = data
        self.profile_data = profile_data
        self.container = container

        device_widget = QtWidgets.QWidget()
        device_layout = QtWidgets.QHBoxLayout(device_widget)

        device_layout.addWidget(QtWidgets.QLabel(f"<b>Switch position [{data.index+1}]</b>"))

        self.selector_device_widget = gremlin.ui.ui_common.NoWheelComboBox()
        self.selector_input_widget = gremlin.ui.ui_common.NoWheelComboBox()

        device_layout.addWidget(QtWidgets.QLabel("Device:"))
        device_layout.addWidget(self.selector_device_widget)
        device_layout.addWidget(QtWidgets.QLabel("Button:"))
        device_layout.addWidget(self.selector_input_widget)

        self.listen_widget = gremlin.ui.ui_common.QDataPushButton("Listen")
        self.listen_widget.data = data
        self.listen_widget.clicked.connect(self._listen_cb)
        device_layout.addWidget(self.listen_widget)

        

        self.main_layout.addWidget(device_widget)


        # populate the selector with hardware inputs
        self._selector_enabled = True

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
        
        # Insert the action widgets for this switch 
        action_set = next((action_set for i,action_set in enumerate(self.profile_data.action_sets) if i == data.index), None)
        if action_set is None:
            # add the action set
            self.profile_data.action_sets.append([])
            action_set = self.profile_data.action_sets[data.index]

        widget = self.container._create_action_set_widget(
            action_set,
            f"Action {data.index:d}",
            gremlin.ui.ui_common.ContainerViewTypes.Action
        )
        self.main_layout.addWidget(widget)
        widget.redraw()
        widget.model.data_changed.connect(self._action_changed)
        self.action_widget = widget
            
                           
        
        if not self._selector_enabled:
            return

        if not default_device:
            # pick the first one if nothing else got selected
            default_device = devices[0]

        selected_device_index = devices.index(default_device)
        for dev in devices:
            self.selector_device_widget.addItem(dev.name, dev.device_id)

        self.selector_device_widget.currentIndexChanged.connect(self._device_changed_cb)
        self.selector_input_widget.currentIndexChanged.connect(self._input_changed_cb)


        # populate the buttons
        self.selector_device_widget.setCurrentIndex(selected_device_index)

        for switch_type in SwitchModeType:
            if switch_type != SwitchModeType.NotSet:
                rb = gremlin.ui.ui_common.QDataRadioButton(text = SwitchModeType.to_display_name(switch_type), data = switch_type)
                rb.data = switch_type
                device_layout.addWidget(rb)
                if data.mode == switch_type:
                    rb.setChecked(True)

                rb.clicked.connect(self._switch_mode_changed)


        # select the default device
        self.selector_device_widget.setCurrentIndex(selected_device_index)

        selected_input_index = self.selector_input_widget.findData(selected_input_id)
        if selected_input_index == -1:
            selected_input_index = 0
        self.selector_input_widget.setCurrentIndex(selected_input_index)



        self.delete_button = QtWidgets.QPushButton(
            gremlin.util.load_icon("gfx/button_delete.png"), "")
        self.delete_button.setToolTip("Delete this entry")
        self.delete_button.clicked.connect(self._delete_cb)
        device_layout.addStretch()
        device_layout.addWidget(self.delete_button)

        
    @QtCore.Slot()
    def _delete_cb(self):
        msgbox = gremlin.ui.ui_common.ConfirmBox(f"Delete switch {self.data.index}?")
        result = msgbox.show()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self.delete_item.emit(self.data)

    QtCore.Slot()
    def _listen_cb(self):
        ''' listen to an input for a button '''
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
        hardware_index = self.selector_device_widget.findData(event.device_id)
        self.selector_device_widget.setCurrentIndex(hardware_index)
        input_index = self.selector_input_widget.findData(event.identifier)
        self.selector_input_widget.setCurrentIndex(input_index)


    @QtCore.Slot()
    def _action_changed(self):
        ''' occurs when the action list changes '''
        self.action_widget.redraw()
        self.container.container_modified.emit()

    @QtCore.Slot()
    def _device_changed_cb(self):
        ''' merge device changed '''
        index = self.selector_device_widget.currentIndex()
        device_id = self.selector_device_widget.itemData(index)
        dev = self.profile_data.device_map[device_id]
        with QtCore.QSignalBlocker(self.selector_input_widget):
            self.selector_input_widget.clear()
            first_input_id = None
            for input_id in range(1, dev.button_count+1):
                self.selector_input_widget.addItem(f"Button {input_id}", input_id)
                if first_input_id is None:
                    first_input_id = input_id
        self.data.device_id = device_id
        self.data.input_id = first_input_id
        
        
    @QtCore.Slot()
    def _input_changed_cb(self):
        ''' merge input changed '''
        index = self.selector_input_widget.currentIndex()
        input_id = self.selector_input_widget.itemData(index)
        self.data.input_id = input_id

    @QtCore.Slot()
    def _switch_mode_changed(self):
        ''' mode changed '''
        widget = self.sender()
        mode = widget.data
        self.data.mode = mode

class SwitchContainerWidget(AbstractContainerWidget):

    """Container which holds a sequence of actions."""

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data the profile data represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(profile_data, parent)




    def _update_ui(self):
        ''' redraws the entire switch content '''
        self._widget_map.clear()
        self.action_widgets.clear()
        gremlin.util.clear_layout(self.action_layout)
        self._create_action_ui()

    def _create_action_ui(self):
        """Creates the UI components."""
        self._widget_map = {} # map of widgets by position index

        self.profile_data.create_or_delete_virtual_button()
        self.action_selector = gremlin.ui.ui_common.ActionSelector(
            self.profile_data.get_input_type()
        )

        
        self.action_selector.action_added.connect(self._add_action)
        self.action_selector.action_paste.connect(self._paste_action)

        self.header_widget = QtWidgets.QWidget()
        self.header_widget.setContentsMargins(0,0,0,0)
        self.header_layout = QtWidgets.QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(0,0,0,0)

        # positions
        self.header_layout.addWidget(QtWidgets.QLabel(f"<b>Switch positions: {self.profile_data.position_count}</b>"))
        
        # switch positions
        self.add_position = QtWidgets.QPushButton("Add Switch Position")
        self.add_position.clicked.connect(self._add_position)
        self.header_layout.addWidget(self.add_position)
        self.header_layout.addStretch()

        self.action_layout.addWidget(self.header_widget)


        ''' creates the switch entries '''
        data : SwitchData
        for data in self.profile_data.position_data.values():
            self._create_selector_ui(data)

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
        if self.profile_data.has_action_conditions:
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
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.get_class(action_name)(self.profile_data)
        self.profile_data.add_action(action_item)
        self.container_modified.emit()
        self.action_widget.redraw()

    def _add_position(self):
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

        self._update_ui()

    def _delete_cb(self, data):
        del self.profile_data.position_data[data.index]
        self._update_ui()


    def _paste_action(self, action):
        ''' pastes an action '''
        plugin_manager = gremlin.plugin_manager.ActionPlugins()
        action_item = plugin_manager.duplicate(action)
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
            logging.getLogger("system").warning(
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


class SwitchContainerFunctor(gremlin.base_conditions.AbstractFunctor):

    def __init__(self, container, parent = None):
        super().__init__(container, parent)
        self.profile_data :  SwitchContainer = container
        self.action_sets = []
        for action_set in container.action_sets:
            self.action_sets.append(
                gremlin.execution_graph.ActionSetExecutionGraph(action_set, parent)
            )
        self.timeout = container.timeout

        self.index = 0
        self.last_execution = 0.0
        self.last_value = None

        # Determine if we need to switch the action index after a press or
        # release event. Only for container conditions this is necessary to
        # ensure proper cycling.
        self.switch_on_press = False
        if container.has_conditions:
            for cond in container.activation_condition.conditions:
                if isinstance(cond, gremlin.base_classes.InputActionCondition):
                    if cond.comparison == "press":
                        self.switch_on_press = True


    def latch_extra_inputs(self):
        ''' returns the list of extra devices to latch to this functor (device_guid, input_type, input_id) '''
        latch_list = []
        data : SwitchData
        for data in self.profile_data.position_data.values():
            latch_list.append((data.device_guid, InputType.JoystickButton, data.input_id))
        return latch_list

    def process_event(self, event : gremlin.event_handler.Event, value : gremlin.actions.Value):
        if event.is_axis:
            return True
        if event.event_type == InputType.JoystickHat:
            is_hat = True
            is_pressed = value.current != (0,0)
        elif not isinstance(value.current, bool):
            logging.getLogger("system").warning(
                f"Invalid data type received in Switch container: {type(event.value)}"
            )
            return False
        else:
            is_hat = False
            is_pressed = value.current
        
        data : SwitchData
        
        for data in self.profile_data.position_data.values():
            if data.device_guid != event.device_guid:
                continue
            if data.input_id != event.identifier:
                continue
            match data.mode:
                case SwitchModeType.OnChange:
                    pass
                case SwitchModeType.OnPress:
                    if not is_pressed:
                        continue
                case SwitchModeType.OnRelease:
                    if is_pressed:
                        continue

            if value.current is None:
                value.current = (0,0) if is_hat else is_pressed

            

            self.action_sets[data.index].process_event(event, value)

        
        return True


class SwitchData():
    ''' data block for each switch position '''
    def __init__(self, index = -1, device_guid = None, input_id = None, mode : SwitchModeType = SwitchModeType.NotSet):
        self.index = index # sequence
        self.device_guid = device_guid
        self.input_id = input_id
        self.mode = mode
        self.device_id = str(device_guid)
        self.action_set = None # data associated with this set

    def _generate_xml(self):
        ''' create xml data '''
        node = ElementTree.Element("switch")
        node.set("index", str(self.index))
        node.set("mode", SwitchModeType.to_string(self.mode))
        node.set("input_id", str(self.input_id))
        node.set("device_id", self.device_id)

        return node
    
    def _parse_xml(self, node):
        ''' read xml data '''
        if node.tag == "switch":
            if "index" in node.attrib:
                self.index = safe_read(node, "index", int, -1)
            if "mode" in node.attrib:
                self.mode = SwitchModeType.to_enum(node.get("mode"))
            if "input_id" in node.attrib:
                self.input_id = safe_read(node, "input_id", int, 0)
            if "device_id" in node.attrib:
                self.device_id = node.get("device_id")
                self.device_guid = gremlin.util.parse_guid(self.device_id)
        
    

    

class SwitchContainer(AbstractContainer):

    """Represents a container which holds multiplier actions.

    The actions will trigger one after the other with subsequent activations.
    A timeout, if set, will reset the sequence to the beginning.
    """

    name = "Switch"
    tag = "switch"

    # override default allowed inputs here
    input_types = [
        InputType.JoystickButton,
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

        self.position_data = {}  # data block indexed by position index
        self.position_data[0] = SwitchData(0, self.hardware_device_guid, self.hardware_input_id, SwitchModeType.OnPress)
        self.position_data[1] = SwitchData(1, self.hardware_device_guid, self.hardware_input_id, SwitchModeType.OnRelease)

        self.device_map = {}  # device list and buttons keyed by device_id(str)
        self.device_button_map = {} 
        devices = sorted(gremlin.joystick_handling.button_input_devices(), key=lambda x: x.name)
        
        for dev in devices:
            self.device_map[dev.device_id] = dev

    @property
    def position_count(self) -> int:
        return len(self.position_data)

    def _parse_xml(self, node):
        """Populates the container with the XML node's contents.

        :param node the XML node with which to populate the container
        """
        
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
