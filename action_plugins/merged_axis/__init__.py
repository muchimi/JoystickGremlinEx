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

        self.main_layout = QtWidgets.QGridLayout(self.main_widget)
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
        self.operation_selector = QtWidgets.QComboBox()
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
        self.configure_button_widget = QtWidgets.QPushButton(qta.icon("fa.gear"),"Actions") 
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
        self.main_layout.addWidget(
            QtWidgets.QLabel("<b><center>Lower Half</center></b>"), 0, 0
        )
        self.main_layout.addWidget(
            QtWidgets.QLabel("<b><center>Upper Half</center></b>"), 0, 1
        )
        
        self.main_layout.addWidget(
            QtWidgets.QLabel("<b><center>Operation</center></b>"), 0, 2
        )

        self.main_layout.addWidget(
            QtWidgets.QLabel("<b>Mapping</b>"), 0, 3
        )

        self.main_layout.addWidget(
            QtWidgets.QLabel("<b>Output</b>"), 0, 4
        )

        
        self.main_layout.addWidget(self.joy1_selector, 1, 0)
        self.main_layout.addWidget(self.joy2_selector, 1, 1)
        self.main_layout.addWidget(self.operation_container_widget, 1, 2)
        self.main_layout.addWidget(self.configure_button_widget, 1, 3)
        self.main_layout.addWidget(self.output_widget, 1, 4)
        
        self.main_layout.addWidget(QtWidgets.QLabel(" "), 1, 5)
        self.main_layout.setColumnStretch(5, 3)


    @QtCore.Slot(bool)
    def _invert_cb(self, checked):        
        self.action_data.invert_output = checked


    @QtCore.Slot()
    def _configure_cb(self):
        dialog = ActionContainerUi(self.action_data)
        dialog.exec()
        

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
        joy1_id = data["lower"]["device_guid"]
        joy2_id = data["upper"]["device_guid"]

        self.joy1_selector.set_selection(
            InputType.JoystickAxis,
            joy1_id,
            data["lower"]["axis_id"]
        )
        
        self.joy2_selector.set_selection(
            InputType.JoystickAxis,
            joy2_id,
            data["upper"]["axis_id"]
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

        self._joy1_value = gremlin.joystick_handling.get_axis(self.action_data.joy1_guid, self.action_data.joy1_input_id)
        self._joy2_value = gremlin.joystick_handling.get_axis(self.action_data.joy2_guid, self.action_data.joy2_input_id)


    def _event_handler(self, event):
        ''' called when a joystick input is detected '''
        if gremlin.shared_state.is_running or not event.is_axis:
            return
        
        device_guid = event.device_guid
        input_id = event.identifier

        update = False
        if device_guid == self.action_data.joy1_guid and input_id == self.action_data.joy1_input_id:
            joy1_value = scale_to_range(event.raw_value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1)
            self._joy1_value = joy1_value
            joy2_value = self._joy2_value
            update = True
        elif device_guid == self.action_data.joy2_guid and input_id == self.action_data.joy2_input_id:
            joy2_value = scale_to_range(event.raw_value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1) 
            self._joy2_value = joy2_value
            joy1_value = self._joy1_value
            update = True


        if update:
            self._update_axis(joy1_value, joy2_value)
          

    def _update_axis(self, joy1_value, joy2_value):
        operation = self.action_data.operation
        if operation == gremlin.types.MergeAxisOperation.Sum:
            value =  clamp(joy1_value + joy2_value,-1.0,1.0)
        elif operation == gremlin.types.MergeAxisOperation.Maximum:
            value = max(joy1_value, joy2_value)
        elif operation == gremlin.types.MergeAxisOperation.Minimum:
            value = min(joy1_value, joy2_value)
        elif operation == gremlin.types.MergeAxisOperation.Average:
            value = (joy1_value - joy2_value) / 2.0
        else:
            return
        
        if self.action_data.invert_output:
            r_min = -1.0
            r_max = 1.0
            target = -value
            value = r_min + (target + 1.0)*((r_max - r_min)/2.0)
        self.output_widget.setValue(value)

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

        
        self._joy1_value = gremlin.joystick_handling.get_axis(action_data.joy1_guid, action_data.joy1_input_id)
        self._joy2_value = gremlin.joystick_handling.get_axis(action_data.joy2_guid, action_data.joy2_input_id)
        self._update_axis(self._joy1_value, self._joy2_value)


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

        device_guid = event.device_guid
        input_id = event.identifier

        update = False
        if device_guid == self.action_data.joy1_guid and input_id == self.action_data.joy1_input_id:
            joy1_value = scale_to_range(event.raw_value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1)
            self._joy1_value = joy1_value
            joy2_value = self._joy2_value
            update = True
        elif device_guid == self.action_data.joy2_guid and input_id == self.action_data.joy2_input_id:
            joy2_value = scale_to_range(event.raw_value, source_min = -32767, source_max = 32767, target_min = -1, target_max = 1) 
            self._joy2_value = joy2_value
            joy1_value = self._joy1_value
            update = True
        
        if self.action_data.invert_output:
            r_min = -1.0
            r_max = 1.0
            target = -value
            value = r_min + (target + 1.0)*((r_max - r_min)/2.0)            


        if update:
            operation = self.action_data.operation
            if operation == gremlin.types.MergeAxisOperation.Sum:
                value =  clamp(joy1_value + joy2_value,-1.0,1.0)
            elif operation == gremlin.types.MergeAxisOperation.Maximum:
                value = max(joy1_value, joy2_value)
            elif operation == gremlin.types.MergeAxisOperation.Minimum:
                value = min(joy1_value, joy2_value)
            elif operation == gremlin.types.MergeAxisOperation.Average:
                value = (joy1_value - joy2_value) / 2.0            

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

        self._joy1_value = gremlin.joystick_handling.get_axis(self.action_data.joy1_guid, self.action_data.joy1_input_id)
        self._joy2_value = gremlin.joystick_handling.get_axis(self.action_data.joy2_guid, self.action_data.joy2_input_id)

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
        # inverted flag
        self.invert_output = False


        # set this to the current input
        joy1_input_id = self.hardware_input_id
        # get the device info
        info = gremlin.joystick_handling.device_info_from_guid(self.hardware_device_guid)
        joy2_input_id = joy1_input_id + 1
        if joy2_input_id == info.axis_count:
            joy2_input_id = joy1_input_id
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
        return True
    
   

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
