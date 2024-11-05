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
from PySide6 import QtWidgets, QtGui, QtCore
from lxml import etree as ElementTree

import gremlin.base_profile
from gremlin.input_types import InputType
import gremlin.input_types
import gremlin.ui.input_item
import gremlin.shared_state
from gremlin.ui import ui_common
import gremlin.types
import logging
from gremlin.util import safe_format, safe_read, scale_to_range, clamp
import gremlin.event_handler
import gremlin.joystick_handling
from dinput import GUID
import qtawesome as qta
import gremlin.util
import gremlin.actions



class ActionContainerUi(QtWidgets.QDialog):
    """UI to setup the individual action trigger containers and sub actions """

    def __init__(self, action_data, parent=None):
        '''
        :param: data = the gate or range data block
        :item_data: the InputItem data block holding the container and input device configuration for this gated input
        :index: the gate number of the gated input - there will at least be two for low and high - index is an integer 
        '''
        
        super().__init__(parent)

        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        # Actual configuration object being managed
        self.setMinimumWidth(600)
        self.setMinimumHeight(800)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        
        from gremlin.ui.device_tab import InputItemConfiguration
        self.container_widget = InputItemConfiguration(action_data.item_data)
        self.main_layout.addWidget(self.container_widget)


class MergeAxisEntryWidget(QtWidgets.QDockWidget):

    """UI dialog which allows configuring how to merge two axes."""

    # Signal which is emitted whenever the widget is closed
    closed = QtCore.Signal(QtWidgets.QWidget)

    # Palette used to render widgets
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColorConstants.LightGray)

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param change_cb function to execute when changes occur
        :param parent the parent of this widget
        """
        QtWidgets.QDockWidget.__init__(self, parent)

        self.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)

        # tracking variables for output computations
       
        self.action_data = action_data

        # Setup the dock widget in which the entire dialog will sit
        self.main_widget = QtWidgets.QWidget()
        self.main_widget.setAutoFillBackground(True)
        self.main_widget.setPalette(MergeAxisEntryWidget.palette)

        self.main_layout = QtWidgets.QVBoxLayout(self.main_widget)
        self.grid_layout = QtWidgets.QGridLayout()
        self.main_layout.addLayout(self.grid_layout)

        self.setWidget(self.main_widget)


        # Selectors for both physical and virtual joystick axis for the
        # mapping selection
        
        self.joy1_selector = ui_common.JoystickSelector(
            lambda x: self._change_cb(),
            [InputType.JoystickAxis]
        )
        self.joy2_selector = ui_common.JoystickSelector(
            lambda x: self._change_cb(),
            [InputType.JoystickAxis]
        )


        # Operation selection
        self.operation_selector = ui_common.QComboBox()
        self.operation_selector.addItem("Average", gremlin.types.MergeAxisOperation.Average)
        self.operation_selector.addItem("Minimum", gremlin.types.MergeAxisOperation.Minimum)
        self.operation_selector.addItem("Maximum", gremlin.types.MergeAxisOperation.Maximum)
        self.operation_selector.addItem("Sum",gremlin.types.MergeAxisOperation.Sum)
        self.operation_selector.currentIndexChanged.connect(
            lambda x: self._change_cb()
        )

        self.operation_container_widget = QtWidgets.QWidget()
        self.operation_container_layout = QtWidgets.QVBoxLayout(self.operation_container_widget)

        # output widget
        self.output_widget = ui_common.AxisStateWidget(orientation=QtCore.Qt.Orientation.Horizontal, show_percentage=False)

        

        # configure button
        self.configure_icon_active = gremlin.util.load_icon("ei.cog-alt",qta_color="#365a75")
        self.configure_icon_inactive = gremlin.util.load_icon("fa.gear")

        self.configure_button_widget = QtWidgets.QPushButton("Actions") 

        self.configure_button_widget.setToolTip("Configure Actions")

        self.configure_button_widget.clicked.connect(self._configure_cb)

        # reverse checkbox 
        self.invert_widget = QtWidgets.QCheckBox(text="Reverse")
        self.invert_widget.setToolTip("Inverts the output of the merge")
        self.invert_widget.setChecked(self.action_data.invert_output)
        self.invert_widget.clicked.connect(self._invert_cb)


        self.operation_container_layout.addWidget(self.operation_selector)
        self.operation_container_layout.addWidget(self.invert_widget)


        # Assemble the complete ui
        self.grid_layout.addWidget(
            QtWidgets.QLabel("<b><center>Lower Half</center></b>"), 0, 0
        )
        self.grid_layout.addWidget(
            QtWidgets.QLabel("<b><center>Upper Half</center></b>"), 0, 1
        )
        
        self.grid_layout.addWidget(
            QtWidgets.QLabel("<b><center>Operation</center></b>"), 0, 2
        )

        self.grid_layout.addWidget(
            QtWidgets.QLabel("<b>Mapping</b>"), 0, 3
        )

        self.grid_layout.addWidget(
            QtWidgets.QLabel("<b>Output</b>"), 0, 4
        )

        self.status_widget = ui_common.QIconLabel("fa.warning",use_qta=True,icon_color=QtGui.QColor("yellow"), use_wrap=False)
        
        
        self.grid_layout.addWidget(self.joy1_selector, 1, 0)
        self.grid_layout.addWidget(self.joy2_selector, 1, 1)
        self.grid_layout.addWidget(self.operation_container_widget, 1, 2)
        self.grid_layout.addWidget(self.configure_button_widget, 1, 3)
        self.grid_layout.addWidget(self.output_widget, 1, 4)

        self.main_layout.addWidget(self.status_widget)
        
        self.grid_layout.addWidget(QtWidgets.QLabel(" "), 1, 5)
        self.grid_layout.setColumnStretch(5, 3)

        self.updateStatus()

        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_handler)
        el.profile_start.connect(self._profile_start)
        el.profile_stop.connect(self._profile_stop)

        
    def _profile_start(self):
        ''' called when the profile starts '''
        el = gremlin.event_handler.EventListener()
        el.joystick_event.disconnect(self._joystick_event_handler)

    def _profile_stop(self):
        ''' called when the profile stops'''
        self._update_axis_widget()
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._joystick_event_handler)

    def _joystick_event_handler(self, event):
        ''' handles joystick events in the UI (functor handles the output when profile is running) so we see the output at design time '''
        if gremlin.shared_state.is_running:
            return 

        if not event.is_axis:
            return 
        
        # merge - check two sets 
        if self.action_data.joy1_guid == self.action_data.joy2_guid:
            if self.action_data.joy1_input_id == self.action_data.joy2_input_id:
                # no action on same axis input
                return
            if event.identifier != self.action_data.joy1_input_id and event.identifier != self.action_data.joy2_input_id:
                # matches neither inputs
                return
        elif event.device_guid == self.action_data.joy1_guid and event.identifier != self.action_data.joy1_input_id: 
            # no match device 1
            return
        elif event.device_guid == self.action_data.joy2_guid and event.identifier != self.action_data.joy2_input_id: 
            # no match device 2
            return
        

        value = self.action_data.computeValue()
        eh = gremlin.event_handler.EventListener()
        custom_event = event.clone()
        custom_event.value = value
        custom_event.raw_value = gremlin.util.scale_to_range(value, target_min = -32768, target_max = 32767) # convert back to a raw value
        custom_event.device_guid = self.action_data.hardware_device_guid
        custom_event.identifier = self.action_data.hardware_input_id
        custom_event.is_custom = True
        eh.custom_joystick_event.emit(custom_event)
        self._update_axis_widget(value)       

    def _update_axis_widget(self, value : float = None): 
        ''' updates the repeater '''
        if value is None:
            value = self.action_data.computeValue()
        self.output_widget.setValue(value)

        


    def setStatus(self, text = ""):
        ''' sets the warning text '''
        self.status_widget.setText(text)
        visible = True if text else False
        self.status_widget.setVisible(visible)


    @QtCore.Slot(bool)
    def _invert_cb(self, checked):        
        self.action_data.invert_output = checked


    @QtCore.Slot()
    def _configure_cb(self):
        dialog = ActionContainerUi(self.action_data)
        dialog.exec()
        self.updateStatus()
        

    def closeEvent(self, event):
        """Emits the closed event when this widget is being closed.

        :param event the close event details
        """
        QtWidgets.QDockWidget.closeEvent(self, event)
        self.closed.emit(self)

    def select(self, data):
        """Selects the specified entries in all drop downs.

        :param data information about which entries to select
        """

        # Create correct physical device id

        joy1_guid = data["lower"]["device_guid"]
        joy2_guid = data["upper"]["device_guid"]
        joy1_input_id = data["lower"]["axis_id"]
        joy2_input_id = data["upper"]["axis_id"]
        
        self.joy1_selector.set_selection(
            InputType.JoystickAxis,
            joy1_guid,
            joy1_input_id,
        )
        
        self.joy2_selector.set_selection(
            InputType.JoystickAxis,
            joy2_guid,
            joy2_input_id,
        )


        self.operation_selector.setCurrentText(
            gremlin.types.MergeAxisOperation.to_string(
                data["operation"]
            ).capitalize()
        )

        # sync
        self.sync()


    def _change_cb(self):
        ''' occurs when a joystick device selection occurs '''
        
        joy1_sel = self.joy1_selector.get_selection()
        joy2_sel = self.joy2_selector.get_selection()

        self.action_data.joy1_guid = joy1_sel["device_id"]
        self.action_data.joy1_input_id = joy1_sel["input_id"]

        self.action_data.joy2_guid = joy2_sel["device_id"]
        self.action_data.joy2_input_id = joy2_sel["input_id"]

        self.action_data.operation = self.operation_selector.currentData()

        self._joy1_value = gremlin.joystick_handling.get_curved_axis(self.action_data.joy1_guid, self.action_data.joy1_input_id)
        self._joy2_value = gremlin.joystick_handling.get_curved_axis(self.action_data.joy2_guid, self.action_data.joy2_input_id)

        self.updateStatus()


    @QtCore.Slot()
    def profile_start(self):
        ''' stop processing joystick events when profile is running '''
        el = gremlin.event_handler.EventListener()
        el.joystick_event.disconnect(self._event_handler)

    @QtCore.Slot()
    def profile_stop(self):
        ''' process joystick events when profile is not running '''
        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._event_handler)

    def sync(self):
        ''' syncs the control to the data '''


        action_data : MergedAxis = self.action_data
        with QtCore.QSignalBlocker(self.invert_widget):
            self.invert_widget.setChecked(action_data.invert_output)
        self.joy1_selector.set_selection(gremlin.input_types.InputType.JoystickAxis, action_data.joy1_guid, action_data.joy1_input_id)
        self.joy2_selector.set_selection(gremlin.input_types.InputType.JoystickAxis, action_data.joy2_guid, action_data.joy2_input_id)

        index = self.operation_selector.findData(action_data.operation)
        self.operation_selector.setCurrentIndex(index)

        
        self._joy1_value = gremlin.joystick_handling.get_curved_axis(action_data.joy1_guid, action_data.joy1_input_id)
        self._joy2_value = gremlin.joystick_handling.get_curved_axis(action_data.joy2_guid, action_data.joy2_input_id)
        
        if not (action_data.joy1_guid == action_data.joy2_guid and action_data.joy1_input_id == action_data.joy2_input_id):
            self._update_axis_widget()

        self.updateStatus()
        

    def updateStatus(self):
        action_data : MergedAxis = self.action_data
        if action_data.joy1_guid == action_data.joy2_guid and action_data.joy1_input_id == action_data.joy2_input_id:
            self.setStatus("Merge axes must be different")
        else:
            self.setStatus()

        has_containers = len(action_data.item_data.containers) > 0
        if has_containers:
            self.configure_button_widget.setIcon(self.configure_icon_active)
        else:
            self.configure_button_widget.setIcon(self.configure_icon_inactive)


class MergedAxisWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget associated with the action of switching to the previous mode."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, MergedAxis))
        self.action_data = action_data

    def _create_ui(self):

        self.container_widget = QtWidgets.QWidget()
        self.container_layout = QtWidgets.QVBoxLayout(self.container_widget)
        self.container_widget.setContentsMargins(0,0,0,0)

        self.merge_layout = QtWidgets.QVBoxLayout()
        self.entry = MergeAxisEntryWidget(self.action_data)


        if not self.action_data.vjoy_valid:
            label = QtWidgets.QLabel(
                "No virtual devices available for axis merging. Either no "
                "vJoy devices are configured or all vJoy devices are defined "
                "as physical inputs."
            )
            label.setStyleSheet("QLabel { background-color : '#FFF4B0'; }")
            label.setWordWrap(True)
            label.setFrameShape(QtWidgets.QFrame.Box)
            label.setMargin(10)
            self.main_layout.addWidget(label)
        else:
            container_widget = QtWidgets.QWidget()
            container_layout = QtWidgets.QHBoxLayout(container_widget)
            container_layout.addStretch()


            
            # self.add_button = QtWidgets.QPushButton("Add Merged Axis")
            # self.add_button.clicked.connect(self.action_data._add_entry)

            # container_layout.addWidget(self.add_button)
            container_layout.addStretch()

            self.merge_layout.addWidget(self.entry)

            self.main_layout.addLayout(self.merge_layout)
            self.main_layout.addWidget(container_widget)    

       


    def _populate_ui(self):
        self.entry.sync()


 
class MergedAxisFunctor(gremlin.base_profile.AbstractContainerActionFunctor):

    def __init__(self, action):
        super().__init__(action)
        self.action_data = action
        self._joy1_value = 0
        self._joy2_value = 0
        self._callbacks = {}


    def process_event(self, event, value):
        ''' do nothing because the container will not be called through the normal hierarchy '''
        return True
    
    def _event_handler(self, event):
        ''' internal event on axis input - determine if we should fire an update or not '''

        if not event.is_axis:
            return 
            
        # merge - check two sets 
        if self.action_data.joy1_guid == self.action_data.joy2_guid:
            if self.action_data.joy1_input_id == self.action_data.joy2_input_id:
                # no action on same axis input
                return
            if event.identifier != self.action_data.joy1_input_id and event.identifier != self.action_data.joy2_input_id:
                # matches neither inputs
                return
        elif event.device_guid == self.action_data.joy1_guid and event.identifier != self.action_data.joy1_input_id: 
            # no match device 1
            return
        elif event.device_guid == self.action_data.joy2_guid and event.identifier != self.action_data.joy2_input_id: 
            # no match device 2
            return
        

        value = self.action_data.computeValue()

        event.raw_value = value
        shared_value = gremlin.actions.Value(value)

        containers = self.action_data.item_data.containers
        container: gremlin.base_profile.AbstractContainer
        for container in containers:
            if container in self._callbacks.keys():
                callbacks = self._callbacks[container]
                for cb in callbacks:
                    for functor in cb.callback.execution_graph.functors:
                        if functor.enabled:
                            functor.process_event(event, shared_value)

    @QtCore.Slot()
    def profile_start(self):
        ''' profile starts - build execution callbacks by defined container '''
        
        # build event callback maps from subcontainers in this gated axis
        callbacks_map = {}
        for container in self.action_data.item_data.containers:
            callbacks_map[container] = container.generate_callbacks()

        self._callbacks = callbacks_map  

        self._joy1_value = gremlin.joystick_handling.get_curved_axis(self.action_data.joy1_guid, self.action_data.joy1_input_id)
        self._joy2_value = gremlin.joystick_handling.get_curved_axis(self.action_data.joy2_guid, self.action_data.joy2_input_id)

        el = gremlin.event_handler.EventListener()
        el.joystick_event.connect(self._event_handler)


 
    @QtCore.Slot()
    def profile_stop(self):
        ''' profile stops - cleanup '''


        el = gremlin.event_handler.EventListener()
        el.joystick_event.disconnect(self._event_handler)

        # clean up callback map
        self._callbacks.clear()

        


class MergedAxis(gremlin.base_profile.AbstractAction):

    """ action data for the MergedAxis action """

    name = "Merged Axis"
    tag = "merged-axis"

    default_button_activation = (True, False)

    # override default allowed input types here if not all
    input_types = [
        InputType.JoystickAxis,
    ]

    functor = MergedAxisFunctor
    widget = MergedAxisWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent

        # this is a singleton action
        self.singleton = True

        # inverted flag
        self.invert_output = False
        self.action_valid = True


        # set this to the current input
        joy1_input_id = self.hardware_input_id
        # get the device info
        info = gremlin.joystick_handling.device_info_from_guid(self.hardware_device_guid)

        # validate bounds
        if info.axis_count == 0:
            self.action_valid = False
            joy1_input_id = 1
            joy2_input_id = 1
            self.vjoy_valid = False
        else:
            joy2_input_id = joy1_input_id + 1
            if joy2_input_id > info.axis_count:
                # roll over
                joy2_input_id = 1

            self.vjoy_valid = len(self._output_vjoy_devices()) > 0

        self.joy1_guid = self.hardware_device_guid
        self.joy1_input_id = joy1_input_id
        self.joy2_guid =  self.hardware_device_guid
        self.joy2_input_id = joy2_input_id
        self.operation = gremlin.types.MergeAxisOperation.Average



        # container holder for this action
        current_item_data = gremlin.base_profile._get_input_item(self)
        item_data = gremlin.base_profile.InputItem()
        item_data._input_type = current_item_data._input_type
        item_data._device_guid = current_item_data._device_guid
        item_data._input_id = current_item_data._input_id
        item_data._is_action = True
        item_data._profile_mode = current_item_data._profile_mode
        item_data._device_name = current_item_data._device_name
        self.item_data : gremlin.base_profile.InputItem = item_data


    def computeValue(self) -> float:
        ''' computes the output '''

        joy1_value = gremlin.joystick_handling.get_axis(self.joy1_guid, self.joy1_input_id)
        joy2_value = gremlin.joystick_handling.get_axis(self.joy2_guid, self.joy2_input_id)

        if self.invert_output:
            r_min = -1.0
            r_max = 1.0
            target = -value
            value = r_min + (target + 1.0)*((r_max - r_min)/2.0)            
    
        operation = self.operation
        if operation == gremlin.types.MergeAxisOperation.Sum:
            value =  clamp(joy1_value + joy2_value,-1.0,1.0)
        elif operation == gremlin.types.MergeAxisOperation.Maximum:
            value = max(joy1_value, joy2_value)
        elif operation == gremlin.types.MergeAxisOperation.Minimum:
            value = min(joy1_value, joy2_value)
        elif operation == gremlin.types.MergeAxisOperation.Average:
            value = (joy1_value - joy2_value) / 2.0            

        return value

    def icon(self):
        return "mdi.call-merge"

    def requires_virtual_button(self):
        return False

    def _parse_xml(self, node):
        # load gate data
        self.entries = []
        for entry_node in node:
            operation_str = safe_read(entry_node, "operation", str, "")
            operation = gremlin.types.MergeAxisOperation.to_enum(operation_str)

            joy1_guid = safe_read(entry_node, "joy1_device_id", str, None )
            if joy1_guid:
                self.joy1_guid = gremlin.util.parse_guid(joy1_guid)
            self.joy1_input_id = safe_read(entry_node, "joy1_axis_id",int,0)

            joy2_guid = safe_read(entry_node, "joy2_device_id", str, None )
            if joy2_guid:
                self.joy2_guid = gremlin.util.parse_guid(joy2_guid)
            self.joy2_input_id = safe_read(entry_node, "joy2_axis_id",int,0)
            
            invert_output = safe_read(entry_node, "reverse", bool, False)
            self.invert_output = invert_output
            self.operation = operation
            
            break
        item_node = gremlin.util.get_xml_child(node, "action_containers")
        if item_node is not None:
            item_node.tag = item_node.get("type")
            self.item_data.from_xml(item_node)
            

    def _generate_xml(self):
         # save gate data
        node = ElementTree.Element(MergedAxis.tag)
        #entry : MergeAxisEntryWidget = self.entry
        operation = self.operation # entry.operation_selector.currentData()
        operation_str = gremlin.types.MergeAxisOperation.to_string(operation)
        entry_node = ElementTree.SubElement(node,"entry")
        entry_node.set("operation", operation_str)
        entry_node.set("joy1_device_id", str(self.joy1_guid))
        entry_node.set("joy1_axis_id", str(self.joy1_input_id))
        entry_node.set("joy2_device_id", str(self.joy2_guid))
        entry_node.set("joy2_axis_id", str(self.joy2_input_id))
        entry_node.set("reverse", str(self.invert_output))

        # save the container information
        if self.item_data.containers:
            item_node = self.item_data.to_xml()
            item_node.set("type", item_node.tag)
            item_node.tag = "action_containers"
            node.append(item_node)

        return node

    def _is_valid(self):
        return self.action_valid
    
   

    def _output_vjoy_devices(self):
        output_devices = []
        profile = gremlin.shared_state.current_profile
        for dev in gremlin.joystick_handling.vjoy_devices():
            is_virtual = not profile.settings.vjoy_as_input.get(dev.vjoy_id,False)
            has_axes = dev.axis_count > 0
            if is_virtual and has_axes:
                output_devices.append(dev)
        return output_devices

  


version = 1
name = "merged-axis"
create = MergedAxis
