# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2025 
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
import os
from PySide6 import QtWidgets, QtCore, QtGui
from lxml import etree as ElementTree
import threading

import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
from gremlin.input_types import InputType
import gremlin.shared_state
import gremlin.ui.input_item
import gremlin.gated_handler
import gremlin.shared_state
import logging
from shiboken6 import Shiboken
from gremlin.gated_handler import GateInfo, RangeInfo, DisplayMode, GateData, GateEventHandler, GateWidgetInfo, RangeWidgetInfo, GateConditionType,TriggerData, TriggerMode, GateRangeOutputMode
import gremlin.ui.qsliderwidget
import gremlin.ui.ui_common
import gremlin.util
import psygnal
from psygnal import Signal

syslog = logging.getLogger("system")

MAX_UNDO = 20 # number of steps on the UNDO stack

_decimals = 5
_single_step = 0.001



class GatedAxisInstructions(gremlin.ui.ui_common.QRememberDialog):
    '''
    Dialog box for instructions
    '''
    def __init__(self, parent = None):
        super().__init__(self.__class__.__name__, parent = parent)
        self.setWindowTitle("Gated Axis Mapper Instructions")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        #self._view = QtWebEngineWidgets.QWebEngineView()
        self._view = QtWidgets.QTextEdit()
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._view)

        


    def load(self, location):
        if location is not None and os.path.isfile(location):
            with open(location,"+rt") as f:
                md = f.read()
            self._view.setMarkdown(md)
            return True
        return False
            


class QGatedAxisWidget(QtWidgets.QWidget):
    ''' a widget that represents a single gate on an axis input and what should happen in that gate
    
        a gate has a min/max value, an optional output range and can trigger different actions based on conditions applied to the input axis value
    
    '''

    delete_requested = QtCore.Signal(object) # fired when the remove button is clicked - passes the GateData to blitz
    duplicate_requested = QtCore.Signal(object) # fired when the duplicate button is clicked - passes the GateData to duplicate
    configure_requested = QtCore.Signal(object) # configure clicked
    configure_range_requested = QtCore.Signal(object) # configure range - data = range object
    configure_gate_requested = QtCore.Signal(object) # configure gate - data = gate object


    def __init__(self, action_data, show_configuration = False, show_output_mode = False, object_name = None, parent = None):
        '''
        
        :param: action_data = the AbstractContainerAction derived object holding the configuration data for the action
        :param: gate_data = the gated axis configuration object
        :param: process_callback = the optional callback when the gated axis receives input at runtime (similar to process_events for functors)


        The callback is necessary because the gate widget does not use the usual event handler method for GremlinEx because it has special handling of sub-actions specific to an axis input.
        The control will automatically process input from the hardware axis it's attached do and call the callback because it may have different values based on the options setup on the gated axis.

        
        '''

        import gremlin.event_handler
        import gremlin.joystick_handling
        import gremlin.ui.ui_common

        super().__init__(parent)
        self._sort_lock = False
        self._loaded = False

        self.id = gremlin.util.get_guid() # unique ID for this widget

        self._deleted = False
        self._stack = [] # save stack for saved state
        self.setObjectName(f"{object_name} [{self.id}]" if object_name else f"GateAxisWidget: [{self.id}]")
        config = gremlin.config.Configuration()

        # hook config changes
        el = gremlin.event_handler.EventListener()
        el.config_option_changed.connect(self._options_changed)
        self._option_display_events = config.gated_axis_display_events
		
        
        self.verbose_ui = config.verbose_mode_ui
        self.verbose_extra = config.verbose_mode_extra

        if self.verbose_ui: syslog.info(f"GATE Widget: init : {object_name}")


        self.valid = True
        #self.lock = threading.Lock()
        self._lock = False

        

        self.action_data = action_data
        self._gate_data : GateData = action_data.gate_data

        self._hooked = False
        self._max_col = 4 # max number of columns in range or gate tables
        self._rwi_map = {} # map of range info objects to (row, col) in the range table
        self._gwi_map = {} # map of gate info objects to (row, col) in the gate table

        self._helper = gremlin.ui.ui_common.QHelper()
        

        self.single_step = 0.001 # amount of a single step when scrolling
        
        self._output_value = 0

        self._range_filter = set() # filter set for ranges

        self.main_layout = QtWidgets.QGridLayout(self)

        is_axis = action_data.input_is_axis()
        if not is_axis:
            missing = QtWidgets.QLabel("Invalid input type - joystick axis expected")
            self.main_layout.addWidget(missing)
            return

        self._grab_icon = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color = gremlin.ui.ui_common.Color.recordColor())
        self._setup_icon = gremlin.ui.ui_common.Icons.gearIcon(qta_color = gremlin.ui.ui_common.Color.inactiveColor())
        self._setup_container_icon = gremlin.ui.ui_common.Icons.gearIcon(qta_color = gremlin.ui.ui_common.Color.activeContentColor())
        
        # get the curent axis normalized value -1 to +1
        if  action_data.input_is_hardware():
            value = gremlin.joystick_handling.get_curved_axis(action_data.hardware_device_guid, action_data.hardware_input_id)
        else:
            # virtual device
            value = self.action_data.hardware_input_id.axis_value
            
        self._axis_value = value

        # axis input gate widget

        self.slider_frame_widget = QtWidgets.QFrame()
        self.slider_frame_layout = QtWidgets.QHBoxLayout(self.slider_frame_widget)
        background_color = gremlin.ui.ui_common.Color.sliderBackgroundColor()
        self.slider_frame_widget.setStyleSheet(f'.QFrame{{background-color: {background_color}; border-radius: 10px;}}')
        self._slider_widget = gremlin.ui.qsliderwidget.QSliderWidget(parent = self.slider_frame_widget, object_name = f"Slider for {self.objectName()} [{self.id}]")
     
        #self._slider.setOrientation(QtCore.Qt.Horizontal)
        self._slider_widget.setRange(-1, 1)
        self._slider_widget.setMarkerValue(value)
        self._slider_widget.valueChanged.connect(self._slider_value_changed_cb)
        self._slider_widget.handleDoubleClicked.connect(self._slider_gate_configure_cb) # calls up gate actions
        self._slider_widget.rangeRightClicked.connect(self._slider_range_context_cb) # calls up range context menuy
        self._slider_widget.rangeDoubleClicked.connect(self._slider_range_configure_cb) # calls up range actions
        self._slider_widget.handleDragStart.connect(self._slider_drag_start_cb)
        self._slider_widget.handleRightClicked.connect(self._slider_gate_context_cb) # calls up gate context menu

        

        self.slider_frame_layout.addWidget(self._slider_widget)
        help_button = QtWidgets.QPushButton()
        help_icon = gremlin.util.load_icon("mdi.help-circle-outline")
        help_button.setIcon(help_icon)
        help_button.setToolTip("Help")
        help_button.setFlat(True)
        help_button.setStyleSheet("QPushButton { background-color: transparent }")
        help_button.setMaximumWidth(32)
        
        help_button.clicked.connect(self._show_help)

        self.slider_frame_layout.addWidget(help_button)
      
        self.container_slider_widget = QtWidgets.QWidget()
        
        self.container_slider_layout = QtWidgets.QGridLayout(self.container_slider_widget)
        self.container_slider_layout.addWidget(self.slider_frame_widget,0,0,-1,1)
        self.container_slider_layout.addWidget(QtWidgets.QLabel(" "),0,6)
        self.container_slider_layout.setColumnStretch(0,3)
        self.container_slider_widget.setContentsMargins(0,0,0,0)

        # configure trigger button
        self._configure_trigger_widget = QtWidgets.QPushButton("Configure")
        self._configure_trigger_widget.setIcon(self._setup_icon)
        self._configure_trigger_widget.clicked.connect(self._trigger_cb)
        self._show_configuration = show_configuration
        self._configure_trigger_widget.setVisible(show_configuration)

        # manual and grab value widgets

        display_event_widget = gremlin.ui.ui_common.QDataCheckbox(
            value = self._option_display_events,
            callback = self._handle_display_event_changed,
            tooltip = "Hide or show events",
            label = "Show events"

        )

        display_event_container = gremlin.ui.ui_common.getHContainer(display_event_widget, bottom_margin = 6, widget_only=True)

        self._display_label_widget = QtWidgets.QLabel("Display Mode:")
        self._display_mode_widget = gremlin.ui.ui_common.QDataComboBox()
        

        self._show_output_mode = show_output_mode
        if show_output_mode:
            self._display_mode_widget.addItem("Output range", userData = DisplayMode.Normal)
            self._display_mode_widget.addItem("[-1, +1]", userData = DisplayMode.OneOne)
        else:
            self._display_mode_widget.addItem("Normal", userData = DisplayMode.OneOne)
        self._display_mode_widget.addItem("Percent", userData = DisplayMode.Percent)
        index = self._display_mode_widget.findData(self._gate_data.display_mode)
        if index == -1:
            self._gate_data.display_mode = DisplayMode.OneOne
            index = self._display_mode_widget.findData(self._gate_data.display_mode)
        self._display_mode_widget.setCurrentIndex(index)
        self._display_mode_widget.currentIndexChanged.connect(self._display_mode_changed_cb)

        self._display_mode_widget.setWidthToContent()

        widgets = [
            self._configure_trigger_widget,
            self._display_label_widget,
            self._display_mode_widget,
        ]


        self.container_options_widget = gremlin.ui.ui_common.getHContainer(widgets, left_margin=12, widget_only = True)


        # holds gateinfo widgets
        self.container_gate_ui_widget, self.container_gate_ui_layout = gremlin.ui.ui_common.getVContainer()
        self.container_gate_ui_widget.setContentsMargins(8,0,0,0)
        
        self.container_gate_widget, self.container_gate_layout = gremlin.ui.ui_common.getVContainer()

        

        self.gate_count_widget = QtWidgets.QLabel()
        self.container_gate_ui_layout.addWidget(self.gate_count_widget)

        self.gate_flow_widget, self.gate_flow_layout = gremlin.ui.ui_common.getFlowContainer()
        self.container_gate_ui_layout.addWidget(self.gate_flow_widget)

        #self.container_gate_layout.addWidget(self.gate_table_widget)
        

        self.range_flow_widget, self.range_flow_layout = gremlin.ui.ui_common.getFlowContainer()
        self.container_range_widget, self.container_range_layout = gremlin.ui.ui_common.getVContainer()
        self.container_range_layout.setContentsMargins(6,6,6,6)


        self.range_count_widget = QtWidgets.QLabel()
        self.container_range_layout.addWidget(self.range_count_widget)
        self.container_range_layout.addWidget(self.range_flow_widget)
        
        self.container_gate_ui_layout.addWidget(self.container_gate_widget)
        self.container_gate_ui_layout.addWidget(self.container_range_widget)


        # steps container
        self._create_steps_ui()

        # ranged container
        self._create_output_ui()

        msg = """Removing gates may cause a loss of mapping information for the gates and their related ranges.
It is recommended to configure and finalize the general number of gates before adding mappings.
It is also possible to save existing mappings via action duplication to the same or different container, saving the mappings to templates or the clipboard before
making changes that impact the order of gates or ranges."""


        warning_widget = gremlin.ui.ui_common.QInfoBox(text = msg, hide_key="gated_axis")

        self.main_layout.addWidget(QtWidgets.QLabel())
        self.main_layout.addWidget(warning_widget)        

        row = 1
        self.main_layout.addWidget(self.container_slider_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_steps_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_gate_ui_widget,row,0,1,-1)
        row+=1
        # spacer
        widgets = [QtWidgets.QLabel(" "), gremlin.ui.ui_common.QHorizontalLine()]
        widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True)
        self.main_layout.addWidget(widget,row,0,1,-1)
        
        row+=1
        self.main_layout.addWidget(display_event_container,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_options_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_output_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(warning_widget,row,0,1,-1)
        #self.main_layout.addWidget(self.container_warning_widget,row,0,1,-1)
        self.main_layout.setVerticalSpacing(0)
        self.main_layout.setRowStretch(row, 3)
        

  

        # update visible container for the current mode
        #self._update_conditions()
        self._update_ui()
        self._update_values_cb(self._gate_data)
        verbose = gremlin.config.Configuration().verbose_mode_gate

        if verbose:
            syslog.info(f"gate axis widget: init {self.id} {self.action_data.input_display_name}")

        self.hook()

        gh = GateEventHandler()
        gh.display_mode_changed.connect(self._handle_display_mode_changed)
        gh.gate_configuration_changed.connect(self._handle_gate_configuration_changed)
        gh.gate_display_changed.connect(self._gate_value_changed)
        gh.gate_index_changed.connect(self._handle_gate_index_changed)
        gh.gate_order_changed.connect(self._gate_order_changed_cb)
        gh.gate_request_delete.connect(self._handle_gate_request_delete)
        gh.gate_trigger_display.connect(self._handle_gate_trigger_display)
        gh.gate_value_changed.connect(self._handle_gate_value_changed)
        gh.gatedata_stepsChanged.connect(self._update_steps_cb)
        gh.gatedata_valueChanged.connect(self._update_values_cb)
        gh.gates_changed.connect(self._gates_changed)
        gh.range_configuration_changed.connect(self._handle_range_configuration_changed) # called when range data changes
        gh.range_trigger_display.connect(self._handle_range_trigger_display)
        gh.slider_update_event.connect(self._handle_slider_update)


        # create range data 
              
        self._reload_gates()
        self._reload_widgets()


        # keyboard hook for undo key
        el = gremlin.event_handler.EventListener()
        el.keyboard_event.connect(self._keyboard_handler)

        self._update_filter() # update filters based on current selection
        self._update_event_ui()

 

    def _handle_display_event_changed(self, checked):
        config = gremlin.config.Configuration()
        config.gated_axis_display_events = checked

    def _update_event_ui(self):
        visible = self._option_display_events
        if Shiboken.isValid(self):
            self.container_options_widget.setVisible(visible)
            self.container_output_widget.setVisible(visible)

    def _options_changed(self):
        ''' options were changed '''
        config = gremlin.config.Configuration()
        self._option_display_events = config.gated_axis_display_events
        self._update_event_ui()


    def _handle_display_mode_changed(self, display_mode):
        # update all ranges
        gremlin.util.InvokeUiMethod(self._handle_display_mode_changed_ui, display_mode)
        
    def _handle_display_mode_changed_ui(self, display_mode):

        # update all gates
        gates = [g for g in self._gwi_map]
        for gate in gates:
            gwi = self._gwi_map[gate]
            if Shiboken.isValid(gwi):
                gwi.update_display()
            else:
                # remove defunct widget
                del self._gwi_map[gate]


        # update all ranges
        ranges = [r for r in self._rwi_map]
        for range_info in ranges:
            rwi = self._rwi_map[range_info]
            if Shiboken.isValid(rwi):
                rwi.update_value()
            else:
                # remove defunct widget
                del self._rwi_map[range_info]

        for rwi in self._rwi_map.values():
            if Shiboken.isValid(rwi):
                rwi.update_value()



    def _handle_range_configuration_changed(self, range_info):
        gremlin.util.InvokeUiMethod(self._handle_range_configuration_changed_ui, range_info)

    def _handle_range_configuration_changed_ui(self, range_info):
        if range_info in self._rwi_map:
            rwi = self._rwi_map[range_info]
            if Shiboken.isValid(rwi):
                rwi.update_icon()
            else:
                # remove defunct widget
                del self._rwi_map[range_info]

    def _handle_gate_value_changed(self, gate):
        gremlin.util.InvokeUiMethod(self._handle_gate_value_changed_ui, gate)

    def _handle_gate_value_changed_ui(self, gate):
        ''' handles a gate value change'''
        if gate in self._gwi_map:
            # find the widget for the gate that was changed
            gwi = self._gwi_map[gate]
            if Shiboken.isValid(gwi):
                gwi.update_value_ui(gate.value)
                gh = GateEventHandler()
                gh.gate_order_changed.emit() # indicate the gate order may have                
            
                # update the range widget for the impacted ranges
                ranges = [r for r in self._rwi_map]
                for range_info in ranges:
                    # update impacted range values
                    if range_info.g1 == gate or range_info.g2 == gate:
                        rwi = self._rwi_map[range_info]
                        if Shiboken.isValid(rwi):
                            rwi.update_value_ui()
                        else:
                            # remove defunct widget
                            del self._rwi_map[range_info]
            else:
                # remove defunct widget
                del self._gwi_map[gate]


    def _handle_gate_request_delete(self, gate : GateInfo):
        gremlin.util.InvokeUiMethod(self._remove_gate_ui, gate)


    def _handle_range_configuration_request(self, range : RangeInfo):
        ''' range configuration request '''
        gremlin.util.InvokeUiMethod(self._configure_range_cb_ui, range)
 
    def _handle_gate_configuration_changed(self, gate : GateInfo):
        gremlin.util.InvokeUiMethod(self._handle_gate_configuration_changed_ui, gate)

    def _handle_gate_configuration_changed_ui(self, gate : GateInfo):
        ''' called when the gate configuration changes'''
        if gate in self._gwi_map:
            # find the widget for the gate that was changed
            gwi = self._gwi_map[gate]
            if Shiboken.isValid(gwi):
                # widget is not garbage collected yet by QT
                gwi.update_icon()
            else:
                # remove defunct widget
                del self._gwi_map[gate]


        if gate in self._gate_data.getGates():
            self._update_gate_icon(gate.slider_index, gate)            
    
    def _handle_gate_index_changed(self, gate : GateInfo):
        gremlin.util.InvokeUiMethod(self._handle_gate_index_changed, gate)

    def _handle_gate_index_changed_ui(self, gate : GateInfo):
        if gate in self._gwi_map:
            # find the widget for the gate that was changed
            gwi = self._gwi_map[gate]
            if Shiboken.isValid(gwi):
                # widget is not garbage collected yet by QT
                gwi.update_icon()
                gwi.update_gate_label()
            else:
                # remove defunct widget
                del self._gwi_map[gate]
            
       

    def _cleanup_ui(self):
        if not Shiboken.isValid(self):
            return
        if not self._deleted:
            verbose_ui = gremlin.config.Configuration().verbose_mode_ui
            if verbose_ui: syslog.info(f"GATE Widget: {self.objectName()} cleanup")
            self.unhook()
            self._gate_data.unhook()
            gremlin.util.clear_layout(self.main_layout)
            self._deleted = True


    def _pushState(self):
        ''' saves the current gate data to the stack '''

        if len(self._stack) >= MAX_UNDO:
            # remove the oldest state
            self._stack.pop(0)
            
        
        verbose = gremlin.config.Configuration().verbose
        if verbose: syslog.info("GATE: state saved")
        node = ElementTree.Element("gate-state")
        node.set("mode",self._gate_data.profile_mode)

        gate_node = self._gate_data.to_xml()
        node.append(gate_node)
        self._stack.append(node)

    def _popState(self):
        ''' restores the data from the stack '''
        if self._stack:
            verbose = gremlin.config.Configuration().verbose
            if verbose: syslog.info("GATE: state restore")
            node = self._stack.pop()
            profile_mode = node.get("mode")
            gate_node = node[0]
            gate_data = GateData(profile_mode, self.action_data)
            gate_data.from_xml(gate_node)
            self.action_data.gate_data = gate_data
            self._gate_data = gate_data
            
            # reload the data
            self._update_ui()
            self._reload_gates()
            self._reload_widgets()


    def _undo(self):
        ''' undo last action '''
        self._popState()
        
    @QtCore.Slot(object)
    def _keyboard_handler(self, event):
        import gremlin.keyboard
        import gremlin.shared_state
        key = gremlin.keyboard.KeyMap.from_event(event)
        if key is None or gremlin.shared_state.is_running or gremlin.shared_state.ui_keyinput_suspended():
            return
        if key.lookup_name == "Z":
            eh = gremlin.event_handler.EventListener()
            if eh.get_control_state():
                # undo requested
                self._undo()






    @QtCore.Slot()
    def _show_help(self):
        location = gremlin.util.find_file("gated_handler_instructions.md", gremlin.shared_state.root_path)
        if location is not None and os.path.isfile(location):
            dialog = GatedAxisInstructions(self)
            dialog.load(location)
            w = 600
            h = 400
            geom = self.geometry()
            dialog.setGeometry(
                int(geom.x() + geom.width() / 2 - w/2),
                int(geom.y() + geom.height() / 2 - h/2),
                w,
                h
            )
            
            gremlin.util.centerDialog(dialog,w,h)
            dialog.show()
        else:
            gremlin.ui.ui_common.MessageBox(prompt ="Unable to locate help file")


    def hook(self):
        ''' enables connections '''
        # hook the joystick input for axis input repeater
        if self._hooked:
            return

        self._hooked = True
        verbose = gremlin.config.Configuration().verbose_mode_gate
        if verbose:
            syslog.info(f"gate axis widget: hook {self.id} {self.action_data.input_display_name}")

        
        self._gate_data.hook()

        # hook events 
       

        self._hooked = True

    def unhook(self):
        # unhook connections
        if self._hooked:
            verbose = gremlin.config.Configuration().verbose_mode_gate
            if verbose:
                syslog.info(f"gate axis widget: unhook {self.id} {self.action_data.input_display_name}")

            gh = GateEventHandler()
            gh.display_mode_changed.disconnect(self._handle_display_mode_changed)
            gh.gate_configuration_changed.disconnect(self._handle_gate_configuration_changed)
            gh.gate_display_changed.disconnect(self._gate_value_changed)
            gh.gate_index_changed.disconnect(self._handle_gate_index_changed)
            gh.gate_order_changed.disconnect(self._gate_order_changed_cb)
            gh.gate_request_delete.disconnect(self._handle_gate_request_delete)
            gh.gate_trigger_display.disconnect(self._handle_gate_trigger_display)
            gh.gate_value_changed.disconnect(self._handle_gate_value_changed)
            gh.gatedata_stepsChanged.disconnect(self._update_steps_cb)
            gh.gatedata_valueChanged.disconnect(self._update_values_cb)
            gh.gates_changed.disconnect(self._gates_changed)
            gh.range_configuration_changed.disconnect(self._handle_range_configuration_changed) # called when range data changes
            gh.range_trigger_display.disconnect(self._handle_range_trigger_display)
            gh.slider_update_event.disconnect(self._handle_slider_update)


            el = gremlin.event_handler.EventListener()
            el.options_changed.disconnect(self._options_changed)
            self._hooked = False
            

    @property
    def gate_data(self) -> GateData:
        return self._gate_data
    
    def ConfigurationVisible(self):
        return self._show_configuration
    
    def setConfigurationVisible(self, value):
        self._show_configuration = value
        self._configure_trigger_widget.setVisible(value)



    @QtCore.Slot()
    def _profile_stop_cb(self):
        ''' profile stops - reconnect widget '''
        pass
        

    @QtCore.Slot()
    def _profile_start_cb(self):
        ''' profile stops - disconnect widget '''
        pass

    def setDisplayRange(self, range_min, range_max):
        ''' sets/updates the slider's range - updates any existing gates to the new range based on prior position'''
        if range_min > range_max:
            range_max, range_min = range_min, range_max
        verbose = gremlin.config.Configuration().verbose_mode_details
        if verbose:
            syslog.info(f"Gate widget: set display range {range_min, range_max}")
        
        self._gate_data.setDisplayRange(range_min, range_max)

    @property
    def min_range(self):
        return self._slider_widget.minimum()
    
    @property
    def max_range(self):
        return self._slider_widget.maximum()

    

    def _reload_widgets(self):
        ''' reloads gates and range repeater widgets'''
        gremlin.util.assert_ui_thread()
        
        self._reload_gates()
        self._reload_ranges()
        

    def _reload_gates(self):
        gremlin.util.assert_ui_thread()
        # sort the gates and update the display
        self._sort_gate_layout()

    
    def _sort_gate_layout(self):
        if self._sort_lock:
            return
        self._sort_lock = True
        try:
            gremlin.util.InvokeUiMethod(self._sort_gate_layout_ui)
        finally:
            self._sort_lock = False
    
    def _sort_gate_layout_ui(self):
        ''' updates and sorts the gate container layout '''
        gremlin.util.assert_ui_thread()
        if not Shiboken.isValid(self):
            return

        self._gwi_map.clear()

        
        flow_layout= self.gate_flow_layout
        gremlin.util.clear_layout(flow_layout)

        gate_list = self.gate_data.getUsedGates()
        gate_count = len(gate_list)

        verbose = gremlin.config.Configuration().verbose_mode_gate

        if verbose: syslog.info("Gate table:")
        for index, gate in enumerate(gate_list):
            # create a widget for this gate
            assert isinstance(gate,GateInfo)
            gate.setIndex(index, False)
            widget = GateWidgetInfo(gate,
                                    None,
                                    self.create_delete_callback(gate),
                                    is_container=gate.hasAnyContainers(),
                                    action_data = self.action_data,
                                    parent = self.gate_flow_widget,
                                    )

            widget.requestGrab.connect(self._grab_cb)
            
            # determine min/max for this gate
            index = gate_list.index(gate)

            offset = 0.001
            if index > 0 and index < (gate_count-1):
                g1 = gate_list[index-1]
                g2 = gate_list[index+1]
                v1 = g1.value + offset
                v2 = g2.value - offset
            elif index == 0:
                # first gate
                g1 = gate
                g2 = gate_list[index+1]
                v1 = -1.0
                v2 = g2.value - offset
            else:
                # last
                g1 = gate_list[index-1]
                g2 = gate
                v1 = g1.value + offset
                v2 = 1.0

            if v1 > v2:
                v1,v2 = v2, v1
            
            widget.setRange(v1,v2)
            

            self._update_gate_icon(gate.slider_index, gate)

            flow_layout.addWidget(widget)
            self._gwi_map[gate] = widget # ((row, col), widget)



        self.gate_count_widget.setText(f"Gates ({gate_count}):")

            
    def create_delete_callback(self, gate : GateInfo):
        return lambda : self._remove_gate_ui(gate)
    

    def _reload_ranges(self):
        ''' when gates change, reload ranges '''
        if not Shiboken.isValid(self):
            return
        gremlin.util.assert_ui_thread()

        # delete all range widgets

        for rng in self._rwi_map:
            widget = self._rwi_map[rng]
            self.range_flow_layout.removeWidget(widget)
            self._rwi_map[rng] = None
            gremlin.util.delete_widget(widget)

        self._rwi_map.clear()

        gremlin.util.clear_layout(self.range_flow_layout)
        
        range_list = self._gate_data.updateRanges()
        range_count = len(range_list)
        assert range_count > 0, "Invalid gate data - no ranges are defined "

        verbose = gremlin.config.Configuration().verbose_mode_gate
        if verbose: syslog.info(f"Reload range: found {len(range_list)} used ranges")
    
        index = 0
        decimals = self._gate_data.decimals
        if verbose: syslog.info("Range table:")
        for index, rng in enumerate(range_list):
            
            widget = RangeWidgetInfo(index + 1, 
                                rng,
                                decimals,
                                self._configure_range_cb_ui,
                                parent = self.range_flow_widget
                                )

            self.range_flow_layout.addWidget(widget)

            # track the widget so we can find it
            self._rwi_map[rng] = widget # (row, col)
            
            if verbose: syslog.info(f"\tRange: {rng.to_display()}")
            

        self._update_range_display()

    def _handle_request_configure(self, range_info):
        self._configure_range_exec(range_info)

    def _update_range_display(self):
        ''' called when the range display mode changes '''
        if not Shiboken.isValid(self):
            return
        if not self._option_display_events:
            return
        widgets = [self.get_range_widget(rwi) for rwi in self._rwi_map.keys()]
        widget : RangeWidgetInfo
        range_count = len(widgets)
        # disable single range mode on the slider
        self._slider_widget.singleRange = False
        
        for widget in widgets:
            widget.range_info.setUsed(True)
            widget.setVisible(True)
        
        self._slider_widget.UseAlternateColor = range_count > 1
        self.range_count_widget.setText(f"Ranges ({range_count}):")
        self.container_range_layout.update()


    def _gate_value_changed(self, gate):
        gremlin.util.InvokeUiMethod(self._gate_value_changed_ui, gate)
    
    def _gate_value_changed_ui(self, gate):
        ''' called when a gate value changes '''
        if not Shiboken.isValid(self):
            return
        # verbose = gremlin.config.Configuration().verbose_mode_gate
        # if verbose: syslog.info(f"Gate [{gate.index}] slider index [{gate.slider_index}] update slider {gate.value:0.3f}")

        # update adjoining ranges
        self._update_range(gate)
        self._set_slider_gate_value(gate.slider_index, gate.value)

  
        
    def _update_range(self, gate):
        ''' updates the allowed range for a given gate, and that of its sibblings so movement of the gates is bound by the next gate over'''
        
        w = self.get_gate_widget(gate)
        if w:
            g1, g2 = self.gate_data.getGateSiblings(gate)
            offset = 0.001
            v = gate.value

            if g1:
                w1 = self.get_gate_widget(g1)
                w1.setMaximum(v-offset)
                v1 = g1.value + offset
                w.setMinimum(v1)
            
            if g2:
                w2 = self.get_gate_widget(g2)
                w2.setMinimum(v+offset)
                v2 = g2.value - offset
                w.setMaximum(v2)



    def _gates_changed(self):
        gremlin.util.InvokeUiMethod(self._gates_changed_ui)

    def _gates_changed_ui(self):
        if not Shiboken.isValid(self):
            return
        for gate in self._gate_data.getGates():
            self._set_slider_gate_value(gate.slider_index, gate.value)
        # update icons on value change
        self._update_gate_icons()


    
        

    @QtCore.Slot()
    def _gate_order_changed_cb(self):
        ''' called when a gate value changed which may force a gate display re-order '''
        self._sort_gate_layout()
        


    def get_gate_gwi(self, gate : GateInfo) -> GateWidgetInfo:
        ''' gets the gate widget info for a given gate '''
        if gate in self._gwi_map.keys():
            widget = self._gwi_map[gate]  # contains (row, col), widget
            if Shiboken.isValid(widget):
                return widget
        return None
    
    def get_gate_widget(self, gate : GateInfo) -> GateWidgetInfo:
        ''' returns the widget for the corresponding gate '''
        return self.get_gate_gwi(gate)
    
    def get_range_widget(self, rng : RangeInfo):
        ''' returns the widget for the corresponding range '''
        if rng in self._rwi_map.keys():
            widget = self._rwi_map[rng]
            if Shiboken.isValid(widget):
                return widget
        
        return None

        

    @QtCore.Slot()
    def _display_mode_changed_cb(self):
        self._gate_data.display_mode = self._display_mode_widget.currentData()
        eh = GateEventHandler()
        eh.display_mode_changed.emit(self._gate_data.display_mode)
        

    @QtCore.Slot()
    def _trigger_cb(self):
        ''' configure clicked '''
        self.configure_requested.emit(self._gate_data)


        

    @QtCore.Slot(float)
    def _slider_range_add_gate_cb(self, value):
        ''' fired when the user clicked on the groove - adds a gate at that location '''
        if Shiboken.isValid(self):
            count = len(self._gate_data.getGates())
            gate = self._gate_data.findGate(value)
            if not gate and count < 20:
                self._add_gate(value)
                self._update_ui()



    def _slider_range_configure_cb(self, value):
        gremlin.util.InvokeUiMethod(self._slider_range_configure_cb_ui, value)
    
    def _slider_range_configure_cb_ui(self, value):
        ''' fired when the user clicked on the groove - adds a gate at that location '''
        if Shiboken.isValid(self):
            rng = self._gate_data.findRangeByValue(value)
            if rng is not None:
                self._configure_range_exec(rng)
        
    @QtCore.Slot(int)
    def _slider_drag_start_cb(self, handle_index):
        ''' called when a handle is being dragged '''
        if Shiboken.isValid(self):        
            self._pushState()



    @QtCore.Slot(int, float)
    def _slider_value_changed_cb(self, index, value):
        ''' occurs when the slider values change '''
        if Shiboken.isValid(self):
            gate : GateInfo = self._gate_data.getGateSliderIndex(index)
            if gate is not None:
                gate.setValue(value, emit = False)

    def _set_slider_gate_value(self, index, value):
        ''' sets a gate value on the slider '''
        if Shiboken.isValid(self):
            values = self.gate_data.getGateValues(as_dict = True)
            #values = list(self._slider.value())
            values[index] = value
            self._update_slider(values)

    def _convert(self, values):
        ''' converts values to a list '''
        if isinstance(values, dict):
            keys = [index for index in values.keys()]
            keys.sort()
            values = [values[index] for index in keys]
        return values

    def _update_slider(self, values : list[float] | tuple[float] | dict):
        '''
        Updates the slider handle values (gates)

        Arguments:
            values -- tuple of values -1.0 to 1.0, list of values, or dict of values indexed by gate position (zero based)
        '''
        if not Shiboken.isValid(self) or not Shiboken.isValid(self._slider_widget):
            return
        if self._lock:
            return
        
        #self.lock.acquire() # critical path
        self._lock = True

        try:
            values = self._convert(values)
            if self.verbose_extra:
                sv = "Slider: "
                for idx, v in enumerate(values):
                    sv += f"[{idx}] {v:0.{self._gate_data.decimals}f} "
                syslog.info(sv)
            with QtCore.QSignalBlocker(self._slider_widget):
                self._slider_widget.setValue(values)
                self._update_gate_tooltips()

            if self.verbose_ui: syslog.info(f"GATE Widget: update slider completed")
        finally:
            #self.lock.release()
            self._lock = False

    @QtCore.Slot()
    def _grab_cb(self, gate):
        ''' grab the min value from the axis position '''
        value = self._axis_value
        gate.setValue(value)
        

    def _prompt_delete(self) -> bool:
        message_box = QtWidgets.QMessageBox()
        message_box.setText("Delete confirmation")
        message_box.setInformativeText("This will delete one or more gates.\nAre you sure?")
        pixmap = gremlin.ui.ui_common.Icons.to_pixmap(gremlin.ui.ui_common.Icons.warningIcon())
        #pixmap = gremlin.util.load_pixmap("warning.svg")
        #pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
        message_box.setIconPixmap(pixmap)
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel
            )
        message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        return result == QtWidgets.QMessageBox.StandardButton.Ok

    def _remove_gate_ui(self, gate : GateInfo, prompt : bool = None):
        ''' removes a gate - if the prompt is not given - the prompt is automatically derived based on container contents '''
        assert isinstance(gate,GateInfo)
        # ensure there are at least two gates left
        count = len(self._gate_data.getGates())
        if count <= 2:
            syslog.warning("Unable to delete gate: at least two gates must be defined.")
            gremlin.ui.ui_common.MessageBox(prompt="Unable to remove this gate.  At least two gates must be defined.")
            return # do not allow fewer than 2 gates
        
        # only prompt if deleting the gate would remove mappings either in the gate or the associated ranges
        if prompt is None:
            prompt = False
            if gate.hasAnyContainers():
                prompt = True
            else:
                # gate has no containers - check its ranges
                ranges = self._gate_data.getRangesForGate(gate)
                for r in ranges:
                    if r and r.hasAnyContainers():
                        prompt = True
                        break
            
        if prompt and not self._prompt_delete():
            return
        
        self.deleteGate(gate)

    def _delete_confirmed_cb(self, gate : GateInfo):
         self.deleteGate(gate)

    def _delete_gate_cb(self, gate : GateInfo ):
        ''' delete the gate '''
        self.deleteGate(gate)


    def _configure_range_cb(self, rng : RangeInfo):
        gremlin.util.InvokeUiMethod(self._configure_range_cb_ui, rng)    
        
    def _configure_range_cb_ui(self, rng : RangeInfo):
        ''' open the configuration dialog for ranges '''
        self._configure_range_exec(rng)


    def _configure_range_exec(self, rng : RangeInfo):
        connected = gremlin.util.isSignalConnected(self,"configure_range_requested")
        if connected:
            self.configure_range_requested.emit(rng)
        else:
            gremlin.shared_state.push_suspend_highlighting()
            dialog = gremlin.gated_handler.ActionContainerUi(gate_data = self._gate_data, info_object = rng, action_data = self.action_data, input_type = InputType.JoystickAxis)
            dialog.exec()
            gh = GateEventHandler()
            gh.range_configuration_changed.emit(rng)
            gremlin.shared_state.pop_suspend_highlighting()



    def _slider_range_context_cb(self, value):
        gremlin.util.InvokeUiMethod(self._slider_range_context_cb_ui, value) # ensure on Ui thread
        
    def _slider_range_context_cb_ui(self, value):
        ''' right click on range = show context menu '''
        menu = QtWidgets.QMenu(self)
        rng = self._gate_data.findRangeByValue(value)
        msg = f"<b>Range {rng.to_display()}</b>"
        line = gremlin.ui.ui_common.QHLine()
        color = gremlin.ui.ui_common.Color.menuSeparatorColor()
        line.setStyleSheet(f"QFrame {{ color: {color}; background-color: {color};}} ")
        widget = gremlin.ui.ui_common.getVContainer([QtWidgets.QLabel(msg),
                                                       line], widget_only = True)

        action_range_info = QtWidgets.QWidgetAction(menu)
        action_range_info.setDefaultWidget(widget)

        action_add_gate = QtGui.QAction("Add Gate...", self, triggered = self._trigger_add_gate)
        action_add_gate.setData(value)

        action_configure = QtGui.QAction("Configure...", self, triggered = self._trigger_configure_range)
        action_configure.setIcon(gremlin.ui.ui_common.Icons.gearIcon())
        action_configure.setData(value)
   

        menu.addAction(action_range_info)
        menu.addAction(action_configure)
        menu.addAction(action_add_gate)
        
        menu.exec_(QtGui.QCursor.pos())
            
    

    def _slider_gate_context_cb(self, handle_index):
        gremlin.util.InvokeUiMethod(self._slider_gate_context_cb_ui, handle_index) # ensure on UI thread

    def _slider_gate_context_cb_ui(self, handle_index):
        ''' right click on gate = show context menu '''

        menu = QtWidgets.QMenu(self)

        

        gate = self._gate_data.getGateSliderIndex(handle_index)
        msg = f"<b>Gate [{handle_index+1}]</b> {gate.value:0.{_decimals}f}"
        line = gremlin.ui.ui_common.QHLine()
        color = gremlin.ui.ui_common.Color.menuSeparatorColor()
        line.setStyleSheet(f"QFrame {{ color: {color}; background-color: {color};}} ")
        widget = gremlin.ui.ui_common.getVContainer([QtWidgets.QLabel(msg),
                                                       line], widget_only = True)

        action_gate_info = QtWidgets.QWidgetAction(menu)
        action_gate_info.setDefaultWidget(widget)

        action_configure = QtGui.QAction("Configure...", self, triggered = self._trigger_configure_gate)
        action_configure.setIcon(gremlin.ui.ui_common.Icons.gearIcon())
        action_configure.setData(handle_index)

        action_delete = QtGui.QAction("Delete Gate", self, triggered = self._trigger_delete_gate)
        action_delete.setIcon(gremlin.ui.ui_common.Icons.trashIcon())
        action_delete.setData(handle_index)

        
                
        
        menu.addAction(action_gate_info)
        menu.addAction(action_configure)
        menu.addAction(action_delete)
        menu.exec_(QtGui.QCursor.pos())

    def _trigger_add_gate(self):
        ''' context menu add gate trigger '''
        action = self.sender()
        value = action.data()
        self._slider_range_add_gate_cb(value)

    def _trigger_configure_range(self):
        ''' context menu configure range trigger '''
        action = self.sender()
        value = action.data()
        rng = self._gate_data.findRangeByValue(value)
        self._configure_range_exec(rng)

    def _trigger_delete_gate(self):
        ''' context menu delete gate trigger '''
        action = self.sender()
        handle_index = action.data()
        gate = self._gate_data.getGateSliderIndex(handle_index)
        self._remove_gate(gate) # prompts
        
    def _trigger_configure_gate(self):
        ''' context menu configure gate trigger '''
        action = self.sender()
        handle_index = action.data()
        self._slider_gate_configure_cb(handle_index)

    
    def _slider_gate_configure_cb(self, handle_index):
        ''' called on double click on slider '''
        gremlin.util.assert_ui_thread()
        gate = self._gate_data.getGateSliderIndex(handle_index)
        gremlin.util.assert_ui_thread()
        dialog = gremlin.gated_handler.ActionContainerUi(gate_data = gate.parent, info_object = gate, action_data = self.action_data, input_type=InputType.JoystickButton)
        #dialog.delete_requested.connect(self._delete_gate_cb)
        dialog.exec()
        #dialog.delete_requested.disconnect(self._delete_gate_cb)
    
 

    QtCore.Slot()
    def _delete_cb(self):
        ''' delete requested '''
        self.delete_requested.emit(self._gate_data)

    QtCore.Slot()
    def _duplicate_cb(self):
        ''' duplicate requested '''
        self.duplicate_requested.emit(self._gate_data)

    def _handle_slider_update(self, event):
        if not event.is_axis:
            return
        if not gremlin.util.compare_guid(self.action_data.hardware_device_id, event.device_guid) or event.identifier != self.action_data.hardware_input_id:
            return # not ours
        gremlin.util.InvokeUiMethod(self._update_slider_marker, event.value)
            
    
    #def _update_slider_marker(self, device_id, input_id, value : float):
    def _update_slider_marker(self,  value : float):
        ''' updates the slider value '''
        # print (f"update marker: {value} input id: {self.action_data.hardware_input_id}")
        if not Shiboken.isValid(self):
            return
        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if self._deleted:
            if verbose_ui: syslog.info(f"GATE Widget: update slider marker : {self.objectName()} ignored - object marked deleted ")
            return
        
        if self._lock:
            return
        
        
        try:
            self._lock = True    
            self._axis_value = value
            if Shiboken.isValid(self._slider_widget):
                verbose_ui = gremlin.config.Configuration().verbose_mode_ui
                if verbose_ui: syslog.info(f"GATE Widget: update slider marker : {self.objectName()} value: {value:0.3f}")
                gremlin.util.assert_ui_thread()

                with QtCore.QSignalBlocker(self._slider_widget):
                    self._slider_widget.setMarkerValue(value)
                    

                if verbose_ui: syslog.info(f"GATE Widget: update slider marker completed")
        finally:
            self._lock = False

    def _create_filter_widgets(self):
        gremlin.util.clear_layout(self.container_filter_layout)
        self._filter_widgets = []
        row = 0
        col = 0
        for _, trigger in enumerate(TriggerMode):
            if not trigger in self._gate_data.filter_map.keys():
                self._gate_data.filter_map[trigger] = True
            widget = gremlin.ui.ui_common.QDataCheckbox(
                label = TriggerMode.to_display_name(trigger),
                data = trigger,
                callbackEx = self._filter_cb,
                value = self._gate_data.filter_map[trigger])
            
            
            self.container_filter_layout.addWidget(widget, row, col)
            col +=1
            if col > 5:
                row+=1
                col= 0
            self._filter_widgets.append(widget)
        
        row += 1
        col = 0
        select_all_widget = QtWidgets.QPushButton("All")
        select_all_widget.clicked.connect(self._select_all_filters_cb)
        clear_all_widget = QtWidgets.QPushButton("None")
        clear_all_widget.clicked.connect(self._clear_all_filters_cb)
        self.container_filter_layout.addWidget(select_all_widget, row, col)
        col+=1
        self.container_filter_layout.addWidget(clear_all_widget, row, col)

        col = 6
        self.container_filter_layout.addWidget(QtWidgets.QWidget(), row, col)        
        self.container_filter_layout.setColumnStretch(col, 2)

    
        

    @QtCore.Slot()
    def _select_all_filters_cb(self):
        ''' select all filter'''
        for widget in self._filter_widgets:
            widget.setChecked(True)
        self._update_filter()

    @QtCore.Slot()
    def _clear_all_filters_cb(self):
        ''' clear all filters'''
        for widget in self._filter_widgets:
            widget.setChecked(False)
        self._update_filter()

    def _update_filter(self):
        filtered = False
        for widget in self._filter_widgets:
            if widget.isChecked():
                filtered = True
                break
        self._is_filtered = filtered

    @QtCore.Slot(bool)
    def _filter_cb(self, widget, checked):
        trigger : TriggerMode = widget.data
        self._gate_data.filter_map[trigger] = checked
        self._update_filter()

    def _create_output_ui(self):
        ''' creates the output line ui options '''

        # holds the output value
        self.output_range_trigger_widget = QtWidgets.QPlainTextEdit()
        self.output_range_trigger_widget.setReadOnly(True)
        self.output_gate_trigger_widget = QtWidgets.QPlainTextEdit()
        self.output_gate_trigger_widget.setReadOnly(True)
        

        
        self.container_output_widget = QtWidgets.QWidget()
        self.container_output_widget.setContentsMargins(0,0,0,0)
        self.container_output_layout = QtWidgets.QGridLayout(self.container_output_widget)

        self.container_filter_widget = QtWidgets.QWidget()
        self.container_filter_widget.setContentsMargins(0,0,0,0)
        self.container_filter_layout = QtWidgets.QGridLayout(self.container_filter_widget)
        self.container_filter_layout.setContentsMargins(0,0,0,0)

        self._create_filter_widgets()
        
        row = 0
        self.container_output_layout.addWidget(self.container_filter_widget,row,0,1,-1)
        row+=1
        self.container_output_layout.addWidget(QtWidgets.QLabel("Range events:"),row,0)
        self.container_output_layout.addWidget(QtWidgets.QLabel("Gate events:"),row,1)
        row+=1
        self.container_output_layout.addWidget(self.output_range_trigger_widget,row,0)
        self.container_output_layout.addWidget(self.output_gate_trigger_widget,row,1)


    def _create_steps_ui(self):
        ''' creates the steps UI '''
        self.sb_steps_widget = QtWidgets.QSpinBox()
        self.sb_steps_widget.setRange(2, GateData.max_gates) # min steps is 2 to max
        count = self._gate_data.steps
        if count < 2:
            # gates may not be created yet
            count = 2
        self.sb_steps_widget.setValue(count)

        self.add_gate_widget = QtWidgets.QPushButton("Add")
        self.add_gate_widget.setToolTip("Adds a gate at the current input position")
        self.add_gate_widget.setIcon(self._grab_icon)
        self.add_gate_widget.clicked.connect(self._add_gate_cb)

        self.set_steps_widget = QtWidgets.QPushButton("Set")
        self.set_steps_widget.setToolTip("Sets the number of gates")
        self.set_steps_widget.clicked.connect(self._set_steps_cb)

        self.normalize_widget = QtWidgets.QPushButton("Normalize")
        self.normalize_widget.setToolTip("Normalizes the position of gates evenly on the existing range")
        self.normalize_widget.clicked.connect(self._normalize_cb)

        self.normalize_reset_widget = QtWidgets.QPushButton("Normalize (reset)")
        self.normalize_reset_widget.setToolTip("Normalizes the position of gates evenly using the full range and resets to min/max to full range")
        self.normalize_reset_widget.clicked.connect(self._normalize_reset_cb)



        self.container_steps_widget = QtWidgets.QWidget()
        self.container_steps_layout = QtWidgets.QHBoxLayout(self.container_steps_widget)
        self.container_steps_widget.setContentsMargins(0,0,0,0)


        self.container_steps_layout.addWidget(self.add_gate_widget)
        label = QtWidgets.QLabel("Set gate count:")
        label.setToolTip("Determines the number of gates that will be added when pressing the 'set' button.")
        self.container_steps_layout.addWidget(label)
        self.container_steps_layout.addWidget(self.sb_steps_widget)
        
        self.container_steps_layout.addWidget(self.set_steps_widget)
        self.container_steps_layout.addWidget(self.normalize_widget)
        self.container_steps_layout.addWidget(self.normalize_reset_widget)
        self.container_steps_layout.addWidget(QtWidgets.QLabel("Right-click range to add new gate, right click gate for configuration"))
        self.container_steps_layout.addStretch()

    def _add_gate(self, value, check_exists = True):
        ''' adds gate '''
        gate_count = self._gate_data.gateCount()
        if gate_count > self._gate_data.max_gates:
            gremlin.ui.ui_common.MessageBox(prompt =f"Too many gates are defined.  Maximumn is {self._gate_data.max_gates}.")
            return
        if check_exists:
            gate = self._gate_data.findGate(value)
            if gate:
                gremlin.ui.ui_common.MessageBox(prompt ="A gate already exists at this location")
                return
        gate = self._gate_data.addGate(value, update = False)
        if not gate:
            # ran too many gates
            gremlin.ui.ui_common.MessageBox(prompt =f"Unable to add gate.  Check the log.")
            return
        
        self._pushState() # for undo
        self._reload_widgets()

        return gate
    
    def _set_gate_count(self, gate_count):
        ''' sets the number of gates on the widget 

        :param gate_count: number of gates to set - if higher - gates are created - if lower - gates are removed 

        '''

        # add the missing steps only (re-use other steps so we don't lose their config)
        max_gates = GateData.max_gates
        if gate_count > max_gates:
            gremlin.ui.ui_common.MessageBox(prompt = f"Unable to add the requested gates: The Maximum gate count is reached ({max_gates})")
            return
        
        self.gate_data.setGateCount(gate_count)

        values = self.gate_data.getGateValues()
        self._update_slider(values)
        eh = GateEventHandler()
        eh.gatedata_stepsChanged.emit(self) # indicate step data changed
        self._reload_gates()
        self._reload_ranges()
        self._update_ui()

    @QtCore.Slot()
    def _add_gate_cb(self):
        ''' adds a new gate at the current input position (record button) '''
        value = self._slider_widget.markerValue()[0]
        gate = self._add_gate(value)
        if gate:
            self._reload_gates()
            self._reload_ranges()
            self._update_ui()
        
        

    @QtCore.Slot()
    def _set_steps_cb(self):
        ''' sets the number of steps to set/reset when the set step button is clicked'''
        target_count = self.sb_steps_widget.value()
        gate_count = self._gate_data.gateCount()
        if gate_count > target_count:
            # if reducing gates - warn
            message_box = QtWidgets.QMessageBox()
            message_box.setText("Reduce gate confirmation")
            message_box.setInformativeText("This will reduce gates, delete gate configurations and normalize gates.\nAre you sure?")
            # pixmap = gremlin.util.load_pixmap("warning.svg")
            # pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
            pixmap = gremlin.ui.ui_common.Icons.to_pixmap(gremlin.ui.ui_common.Icons.warningIcon())
            message_box.setIconPixmap(pixmap)
            message_box.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Ok |
                QtWidgets.QMessageBox.StandardButton.Cancel
                )
            message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
            gremlin.util.centerDialog(message_box)
            result = message_box.exec()
            if result == QtWidgets.QMessageBox.StandardButton.Ok:
                self._set_steps_confirm_cb(target_count)
            return

        if gate_count < target_count:
            # increase
            self._set_gate_count(target_count)

        self._reload_ranges()
        self._update_ui()
        
            
    
    def _set_steps_confirm_cb(self, value):
        if not Shiboken.isValid(self):
            return
        self._pushState()
        self._set_gate_count(value)
        self._normalize_cb(save_state = False)
            

    @QtCore.Slot()
    def _normalize_cb(self, save_state = True):
        ''' normalize button  '''
        #value = self.sb_steps_widget.value()
        #self._gate_data.gates = value
        if not Shiboken.isValid(self):
            return
        if save_state: self._pushState()
        self._gate_data.normalize_steps(True)
        self._update_values_cb(self._gate_data, save_state)


    def _normalize_reset_cb(self, save_state = True):
        ''' normalize reset button  '''
        #value = self.sb_steps_widget.value()
        #self._gate_data.gates = value
        if not Shiboken.isValid(self):
            return
        if save_state: self._pushState()
        self._gate_data.normalize_steps(False)
        self._update_values_cb(self._gate_data, save_state)


    @QtCore.Slot(object)
    def _update_steps_cb(self, gate_data):
        ''' updates gate steps on the widget and their positions '''
        if not Shiboken.isValid(self):
            return
        if self._gate_data == gate_data:
            self._update_values_cb(self._gate_data)
        

    @QtCore.Slot(object)
    def _update_values_cb(self, gate_data, save_state = True):
        ''' called when gate data values are changed '''
        if not Shiboken.isValid(self):
            return
        if self._gate_data == gate_data:
            values = self._gate_data.getGateValues()
            if values != self._slider_widget.value():
                if save_state: self._pushState() 
                with QtCore.QSignalBlocker(self._slider_widget):
                    self._update_slider(values)
                    
            

    def _update_gate_tooltips(self):
        '''
        Updates gate tooltip values 
        '''
        return # avoid tooltips due to right context menu context 
    
        # gates = self._gate_data.getGates()
        # gate : GateInfo
        # if Shiboken.isValid(self._slider_widget):
        #     for index, gate in enumerate(gates):
        #         self._slider_widget.setHandleTooltip(index, f"Gate {gate.value:0.{_decimals}f}")            

    def _update_gate_icons(self):
        if not Shiboken.isValid(self):
            return
        gates = self._gate_data.getGates()
        gate : GateInfo
        conflicts_map = {}
        for index, gate in enumerate(gates):
            gate.isError = False # assume no error
            value = f"{gate.value:0.4f}"
            if not value in conflicts_map:
                conflicts_map[value] = []
            conflicts_map[value].append(gate)

        # process maps
        for conflicts in conflicts_map.values():
            if len(conflicts) > 1: # more than one gate with that value = conflict
                for gate in conflicts:
                    gate.isError = True

        for index, gate in enumerate(gates):
            self._update_gate_icon(index, gate)




    def _update_gate_icon(self, index : int, gate : GateInfo):
        ''' updates the icon for a single gate '''
        if not Shiboken.isValid(self):
            return
        if Shiboken.isValid(self._slider_widget):
            if gate is None:
                self._slider_widget.setHandleIcon(index, None)
            elif gate.hasAnyContainers():
                self._slider_widget.setHandleIcon(index, 'fa6s.gear', True, gremlin.ui.ui_common.Color.activeContentColor())
            else:
                self._slider_widget.setHandleIcon(index, "fa6s.gear",True,gremlin.ui.ui_common.Color.inactiveColor() )

        # find the widgets for the gate
        if gate in self._gwi_map:
            widget : GateWidgetInfo = self.get_gate_widget(gate)
            if widget:
                widget.update_icon()


    def _handle_range_trigger_display(self):
        ''' updates the range trigger display '''
        if not self._is_filtered or not self._option_display_events:
            return # nothing to display 
        gremlin.util.InvokeUiMethod(self._handle_range_trigger_display_ui) # ensure UI thread

    def _handle_range_trigger_display_ui(self):
        ''' updates the range trigger display '''
        if not Shiboken.isValid(self):
            return
        
        

        self.output_range_trigger_widget.setPlainText(self._gate_data.trigger_range_text)
        # scroll to bottom
        vbar = self.output_range_trigger_widget.verticalScrollBar()
        vbar.setValue(vbar.maximum())

    def _handle_gate_trigger_display(self):
        ''' updates the gate trigger display'''
        if not self._is_filtered or not self._option_display_events:
            return # nothing to display 
        gremlin.util.InvokeUiMethod(self._handle_gate_trigger_display_ui) # ensure UI thread

    def _handle_gate_trigger_display_ui(self):
        ''' updates the gate trigger display'''
        if not Shiboken.isValid(self):
            return
        self.output_gate_trigger_widget.setPlainText(self._gate_data.trigger_gate_text)
        # scroll to bottom
        vbar = self.output_gate_trigger_widget.verticalScrollBar()
        vbar.setValue(vbar.maximum())

        


    QtCore.Slot()
    def _min_changed_cb(self):
        if not Shiboken.isValid(self):
            return
        if Shiboken.isValid(self._slider_widget):
            value = self.sb_min_widget.value()
            self._gate_data.min = value
            lv = list(self._slider_widget.value())
            lv[0] = value
            with QtCore.QSignalBlocker(self._slider_widget):
                self._set_slider(lv)
                
            
            self._update_steps_cb()
            

    QtCore.Slot()
    def _max_changed_cb(self):
        if not Shiboken.isValid(self):
            return
        if Shiboken.isValid(self._slider_widget):
            value = self.sb_max_widget.value()
            self._gate_data.max = value
            lv = list(self._slider_widget.value())
            lv[1] = value
            with QtCore.QSignalBlocker(self._slider_widget):
                self._set_slider(lv)
            self._update_steps_cb()
            


    
    def _update_ui(self):
        ''' updates visibility of UI components based on the active options '''
        if not Shiboken.isValid(self):
            return
        if Shiboken.isValid(self._slider_widget):
            self._update_slider(self._gate_data.getGateValues())
            

    def deleteGate(self, gate : GateInfo):
        gremlin.util.InvokeUiMethod(self._delete_gate_ui, gate)

    def _delete_gate_ui(self, gate : GateInfo):
        ''' remove a gate from this widget '''

        self._gate_data.deleteGate(gate) # remove the gate data
        
        # delete the gate widget
        if gate in self._gwi_map:
            widget = self._gwi_map[gate]
            self.gate_flow_layout.removeWidget(widget)
            del self._gwi_map[gate]
            gremlin.util.delete_widget(widget)
            
        
        self._reload_widgets()
        self._update_ui()

  


class GatedAxisWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget associated with the action of switching to the previous mode."""

    def __init__(self, action_data, parent=None):
        self.action_data = action_data
        super().__init__(action_data, parent=parent)
        

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        self._deleted = False
        
        self.container_widget = QtWidgets.QWidget()
        self.container_layout = QtWidgets.QVBoxLayout(self.container_widget)
        self.container_widget.setContentsMargins(0,0,0,0)

        object_name = f"GatedAxisWidget: {self.action_data.input_display_name}"
        self.setObjectName(object_name)

        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if verbose_ui: 
            syslog.info(f"Create gate widget for {object_name} profile mode:  {self.action_data.profile_mode}")
        

        
        self.gate_widget = QGatedAxisWidget(action_data = self.action_data,
                                            show_configuration=False,
                                            parent=self,
                                            object_name = object_name
                                            )
        
        
        #cache.register(self.action_data, widget)
        self.main_layout.addWidget(self.gate_widget)


        el = gremlin.event_handler.EventListener()
        el.profile_unload.connect(self._cleanup_ui)
    

    def _populate_ui(self):
        pass

    def _cleanup_ui(self):
        ''' cleanup the UI and widget hooks '''
        if not Shiboken.isValid(self):
            return
        if not self._deleted:
            verbose_ui = gremlin.config.Configuration().verbose_mode_ui
            if verbose_ui: syslog.info(f"Gated Axis Action: cleanup : {self.objectName()}")
            self._deleted = True
            if self.gate_widget and Shiboken.isValid(self.gate_widget):
                self.gate_widget._cleanup_ui()
                self.gate_widget.hide()
                self.gate_widget.setParent(None)
                self.gate_widget.deleteLater()
                self.gate_widget = None

    


class GatedAxisFunctor(gremlin.base_profile.AbstractContainerActionFunctor):

    def __init__(self, action_data, parent = None):
        super().__init__(action_data, parent)
        self.manual_callback = True # indicate this functor only uses manual callbacks

    def profile_start(self):
        ''' register the gated functor'''
        #self.action_data.gate_data.setActionId(self.action_data.id)
        self.action_data.gate_data.start()

    def profile_stop(self):
        self.action_data.gate_data.stop()

    def process_event(self, event, value, extra_data = None):
        #all the work happens in the gate widget hook function 
        return True






class GatedAxis(gremlin.base_profile.AbstractAction):

    """ action data for the GatedAxis action """

    name = "Gated Axis"
    tag = "gated-axis"
    hint = '''Advanced axis (linear) input splitter.
Splits an axis into customizable gates and ranges.
Contains containers and actions that can trigger when 
the input is in a specific range of values, or crosses gates.
'''

    default_button_activation = (True, False)
    # override default allowed input types here if not all
    input_types = [
        InputType.JoystickAxis,
    ]

    functor = GatedAxisFunctor
    widget = GatedAxisWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.singleton = True # this action can only appear once per input

        # gate data
        self.gate_data = gremlin.gated_handler.GateData(profile_mode = gremlin.shared_state.current_mode, action_data=self)
        self.gate_data.id = self.id # use the same ID as the action so it's unique
        self.gates = [self.gate_data]
 

        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if verbose_ui: syslog.info(f"GatedAxis Action: cleanup: [{self.id}]")

        gremlin.util.singleShot(self.gate_data.hook)
    

    def display_name(self):
        return f"Gated Axis: [{self.id}]"

    def _cleanup_ui(self):
        ''' clean ourselves up '''
        verbose_ui = gremlin.config.Configuration().verbose_mode_ui
        if verbose_ui: syslog.info(f"GatedAxis Action: cleanup: [{self.id}]")
        if self.gates:
            self.gates.clear()
        if self.gate_data:
            self.gate_data.unhook()
            self.gate_data = None


    def icon(self):
        return "ph.sliders"

    def requires_virtual_button(self):
        return False

    def _parse_xml(self, node, data = None, extra_data = None):
        # load gate data
        import gremlin.util

        if extra_data and "paste" in extra_data:
            paste_mode = extra_data["paste"]
        else:
            paste_mode = False
        
        gates = []
        gate_node = gremlin.util.get_xml_child(node,"gates")

        input_item = self.get_input_item()
        profile_mode = input_item.profile_mode

        if not gate_node is None:
            for child in gate_node:
                gate_data = gremlin.gated_handler.GateData(profile_mode, action_data = self)
                gate_data.from_xml(child, data, extra_data)
                gate_data.profile_mode = profile_mode
                gates.append(gate_data)

        if gates:
            self.gates = gates
            self.gate_data = gates[0]


        # override profile mode to use current mode this action is attached to
        self.gate_data.profile_mode = profile_mode


    def _generate_xml(self):
         # save gate data
        node = ElementTree.Element(GatedAxis.tag)
        if self.gates:
            node_gate = ElementTree.SubElement(node, "gates")
            for gate_data in self.gates:
                child = gate_data.to_xml()
                node_gate.append(child)
        return node

    def _is_valid(self):
        return True
    

    
    
    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell
        import html
        table = ReportTable(cellpadding=4)    
        gate_count = len(self.gate_data.getUsedGates())
        range_count = len(self.gate_data.getRanges())
        table.addField("Gates", f"{gate_count}")
        table.addField("Ranges",f"{range_count}")
        return table.to_html()

version = 1
name = "gated-axis"
create = GatedAxis
