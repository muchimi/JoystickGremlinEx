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


@gremlin.singleton_decorator.SingletonDecorator
class InputConfigurationWidgetCache():
    ''' caches the joystick input widget for each device/input combination  '''
    def __init__(self):
        self._widget_map = {}


    def register(self, key, widget):
        if not key in self._widget_map:
            self._widget_map[key] = widget
            
            
    def clear(self):
        ''' clears the cache '''
        self._widget_map.clear()


    def retrieve(self, key):
        if key in self._widget_map:
            return self._widget_map[key]
        return None
    
    def retrieve_by_data(self,item_data):
        if item_data:
            key = item_data.id
            return self.retrieve(key)
        return None

    def remove(self, key):
        if key in self._widget_map:
            del self._widget_map[key]

    def dump(self):
        ''' dumps the cache content to the log for debug purposes '''
        # syslog = logging.getLogger("system")
        items = list(self._widget_map.values())
        items.sort(key = lambda x: (x.item_data.profile_mode, x.item_data.device_guid, x.item_data.input_type, x.item_data.input_id))
        current_device_guid = None
        current_mode = None
        current_input_type = None
        
        syslog.info("-"*50)
        syslog.info("UI widget cache dump")
        for index, input_item_config in enumerate(items):
            item: gremlin.base_profile.InputItem = input_item_config.item_data
            if not current_mode or current_mode != item.profile_mode:
                current_mode = item.profile_mode
                syslog.info(f"Mode {current_mode}:")
            if not current_device_guid or current_device_guid != item.device_guid:
                device_name = gremlin.shared_state.get_device_name(item.device_guid)
                current_device_guid = item.device_guid
                syslog.info(f"\tDevice {device_name} id {str(item.device_guid)}:")
            if not current_input_type or current_input_type != item.input_type:
                current_input_type = item.input_type
                syslog.info(f"\t\tInput Type: {InputType.to_display_name(item.input_type)}")
            syslog.info(f"\t\t\tInput Id: {item.display_name} cache index [{index:,}]")

            

# primary cache instantiation to prevent GC
_cache = InputConfigurationWidgetCache()

class ActionContainerUi(gremlin.ui.ui_common.QRememberDialog):
    """UI to setup the individual action trigger containers and sub actions """

    delete_requested = Signal(GateInfo) # fired when the remove button is clicked - passes the GateData to blitz

    def __init__(self, gate_data : GateData, info_object : RangeInfo | GateInfo, action_data, input_type : InputType, parent=None):
        '''
        :param: data = the gate or range data block
        
        '''

        
        super().__init__(self.__class__.__name__, parent = parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self._id = gremlin.util.get_guid()

        self._range_info : RangeInfo = None
        self._gate_info : GateInfo = None
        is_range = isinstance(info_object, RangeInfo)
        self._gate_data : GateData = gate_data
        self._is_range = is_range
        self._action_data = action_data
        self._cache = InputConfigurationWidgetCache()
        self._tab_widgets = {} # holds the widgets for the tabs
        self._input_type = input_type # type of input for the container and action selectors

        # make modal
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        # Actual configuration object being managed
        self.setMinimumWidth(600)
        self.setMinimumHeight(800)
        
        self.trigger_container_widget = QtWidgets.QWidget()
        self.trigger_condition_layout = QtWidgets.QHBoxLayout(self.trigger_container_widget)


        
    
        

        # the tab container contains all possible trigger modes for the range or gate as a tab
        # each tab contains the mappings and options for that trigger condition
        self._condition_tab = QtWidgets.QTabWidget()
        self._condition_tab.currentChanged.connect(self._condition_changed_cb)
        self._condition_pages = {}  # map of condition pages keyed by GateCondition
        self.container_condition_widget = QtWidgets.QWidget()
        self.container_condition_widget.setContentsMargins(0,0,0,0)
        self.container_condition_layout = QtWidgets.QVBoxLayout(self.container_condition_widget)
        self.container_condition_layout.setContentsMargins(0,0,0,0)
        self.container_condition_layout.addWidget(self._condition_tab)

        self._icon_enabled = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color = gremlin.ui.ui_common.Color.activeColor())
        self._icon_disabled = gremlin.util.load_icon("mdi.checkbox-blank-circle", qta_color=gremlin.ui.ui_common.Color.inactiveColor())


        if is_range:
            # range has an output mode for how to handle the output value for the range

            range_info : RangeInfo = info_object
            self._range_info = range_info
            self.setWindowTitle("Gated Axis Range Configuration")
            self.trigger_condition_layout.addWidget(QtWidgets.QLabel(f"Range Configuration: {info_object.range_display()}"))

            self.range_description_widget = gremlin.ui.ui_common.QDataLineEdit()
            self.range_description_widget.setMinimumWidth(200)
            self.range_description_widget.setText(self._range_info.description)
            self.range_description_widget.textChanged.connect(self._range_description_changed)
            widget, layout = gremlin.ui.ui_common.getHContainer([QtWidgets.QLabel("Range Description:"), self.range_description_widget])
            self.trigger_condition_layout.addWidget(widget)
        

            # print (f"Range: configuration: {range_info.range_display_ex()}")
            
            self.slider_frame_widget = QtWidgets.QFrame()
            self.slider_frame_layout = QtWidgets.QVBoxLayout(self.slider_frame_widget)
            self.slider_frame_widget.setStyleSheet('.QFrame{background-color: transparent;}')
            self.slider = gremlin.ui.qsliderwidget.QSliderWidget(object_name = f"Slider for ActionContainer: {info_object.range_display()}") 
            self.slider.setMinimumHeight(48)
            self.slider.setRange(-1,1)
            self.slider_frame_layout.addWidget(self.slider)

            gh = GateEventHandler()

            self._gate_data.registerTriggerCallback(self._trigger_handler)
            gh.registerValueChangedCallback(self._id, self._input_value_changed_handler)

            # display two gates for a range
            values = [range_info.g1.value, range_info.g2.value]
            self.slider.setValue(values)
            self.slider.setReadOnly(True)



            self.axis_widget = gremlin.ui.ui_common.QHookedProgressBar(orientation = QtCore.Qt.Orientation.Horizontal)
            
            self.output_mode_widget = gremlin.ui.ui_common.QComboBox()
            self.output_container_widget = QtWidgets.QWidget()
            self.output_container_widget.setContentsMargins(0,0,0,0)
            self.output_container_layout = QtWidgets.QHBoxLayout(self.output_container_widget)
            self.output_container_layout.addWidget(QtWidgets.QLabel("Output Mode:"))
            self.output_container_layout.addWidget(self.output_mode_widget)
            self.output_container_layout.addWidget(QtWidgets.QLabel("Output Value:"))
            self.output_container_layout.addWidget(self.axis_widget)
            self.output_container_layout.addStretch()
            

            # populates and picks the default mode
            self._gate_data.populate_output_widget(self.output_mode_widget, default = self._range_info.mode)
            self.output_mode_widget.currentIndexChanged.connect(self._output_mode_changed_cb)

            # ranged data
            self.container_output_range_widget = QtWidgets.QWidget()
            self.container_output_range_layout = QtWidgets.QHBoxLayout(self.container_output_range_widget)
            self.container_output_range_widget.setContentsMargins(0,0,0,0)
            
            self.sb_range_min_widget = gremlin.ui.ui_common.QFloatLineEdit()
            self.sb_range_min_widget.setValue(info_object.output_range_min)
            self.sb_range_min_widget.valueChanged.connect(self._range_min_changed_cb)

            self.sb_range_max_widget = gremlin.ui.ui_common.QFloatLineEdit()
            self.sb_range_max_widget.setValue(info_object.output_range_max)

            self.sb_range_max_widget.valueChanged.connect(self._range_max_changed_cb)

            self.sb_fixed_value_widget = gremlin.ui.ui_common.QFloatLineEdit()
            if info_object.fixed_value is None:
                info_object.fixed_value = info_object.v1
            self.sb_fixed_value_widget.setValue(info_object.fixed_value)
            self.sb_fixed_value_widget.valueChanged.connect(self._fixed_value_changed_cb)

            label = QtWidgets.QLabel("Scaling options:")
            label.setToolTip("Scaling rescales the input range to the specified min/max scaled range.  This remaps the input value to a new value before the value is sent to the mapped actions/containers.")
            self.container_output_range_layout.addWidget(label)

            self.container_output_range_layout.addWidget(QtWidgets.QLabel("Range Min:"))
            self.container_output_range_layout.addWidget(self.sb_range_min_widget)
            self.container_output_range_layout.addWidget(QtWidgets.QLabel("Range Max:"))
            self.container_output_range_layout.addWidget(self.sb_range_max_widget)

            self.reset_range_button_widget = QtWidgets.QPushButton("Reset")
            self.reset_range_button_widget.setToolTip("Reset the scale to the default input range")
            self.reset_range_button_widget.clicked.connect(self._range_reset_cb)

            self.container_output_range_layout.addWidget(self.reset_range_button_widget)
            self.container_output_range_layout.addStretch()
            
            self.container_fixed_widget = QtWidgets.QWidget()
            self.container_fixed_widget.setContentsMargins(0,0,0,0)
            self.container_fixed_layout = QtWidgets.QHBoxLayout(self.container_fixed_widget)

            label = QtWidgets.QLabel("Fixed Value:")
            label.setToolTip("The fixed value will be the value sent to actions/containers while the input is within the current range.  Used the Filter mode if no data should be output.")
            self.container_fixed_layout.addWidget(label)
            self.container_fixed_layout.addWidget(self.sb_fixed_value_widget)
            self.container_fixed_layout.addStretch()

            self.container_range_data_widget = QtWidgets.QWidget()
            self.container_range_data_widget.setContentsMargins(0,0,0,0)
            self.container_range_data_layout = QtWidgets.QVBoxLayout(self.container_range_data_widget)
            self.container_range_data_layout.addWidget(self.container_output_range_widget)
            self.container_range_data_layout.addWidget(self.container_fixed_widget)

              
            # update the repeater
            self._update_axis_widget()

            
            self.main_layout.addWidget(self.slider_frame_widget)


        else:
            # gate configuration
            self.setWindowTitle("Gated Axis Gate Configuration")
            self._gate_info = info_object
            self.trigger_condition_layout.addWidget(QtWidgets.QLabel(f"Gate {self._gate_info.slider_index + 1} Configuration:"))

            self.gate_description_widget = gremlin.ui.ui_common.QDataLineEdit()
            self.gate_description_widget.setMinimumWidth(200)
            self.gate_description_widget.setText(self._gate_info.description)
            self.gate_description_widget.textChanged.connect(self._gate_description_changed)
            widget, layout = gremlin.ui.ui_common.getHContainer([QtWidgets.QLabel("Gate Description:"), self.gate_description_widget])
            self.trigger_condition_layout.addWidget(widget)

            
        # delay
        if self._gate_info:
            value = self._gate_info.delay
        else:
            value = self._range_info.delay

        self.delay_widget = gremlin.ui.ui_common.QDelayWidget(
            value = value,
            tooltip = "Delay in milliseconds between a press and release event for gate crossings or range enter/exit triggers",
            callback = self._delay_changed_cb,
            label = "Trigger Delay:",
            show_shortcuts=False
        )
    
        self.trigger_condition_layout.addStretch()
        self.trigger_condition_layout.addWidget(self.delay_widget, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        

            
        el = gremlin.event_handler.EventListener()
        el.mapping_changed.connect(self._mapping_changed_cb)
        
        
        self.main_layout.addWidget(self.trigger_container_widget)
        self.main_layout.addWidget(self.container_condition_widget)


        self._create_conditions_ui()
        self._update_ui()


        #self._condition_changed_cb()

    def closeEvent(self, event) -> None:
        
        
        # release tab widgets tracking items and widgets
        with QtCore.QSignalBlocker(self._condition_tab):
            self._tab_widgets.clear() 
            self._condition_pages.clear() 
            self._condition_tab.clear()

        el = gremlin.event_handler.EventListener()
        el.mapping_changed.disconnect(self._mapping_changed_cb)
        
        gh = GateEventHandler()

        self._gate_data.unregisterTriggerCallback(self._trigger_handler)
        gh.unregisterValueChangedCallback(self._id, self._input_value_changed_handler)

        self._cache.clear() # release cache objects
        self._range_info = None
        self._gate_info = None

    def _current_input_axis(self):
        ''' gets the current input axis value '''
        device_guid = self._action_data.hardware_device_guid
        input_id = self._action_data.hardware_input_id
        if gremlin.joystick_handling.is_hardware_device(device_guid):
            return gremlin.joystick_handling.get_curved_axis(device_guid, input_id)
        else:
            return input_id.axis_value


    def _trigger_handler(self, trigger: TriggerData):
        ''' process range output value '''

        if trigger.is_range and trigger.range == self._range_info \
            and trigger.mode == TriggerMode.ValueInRange:
            # value update for in-range 
            self.axis_widget.setValue(trigger.value)

    def _input_value_changed_handler(self, device_id, input_id, value : float):
        # update input value
        if gremlin.util.compare_guid(self._action_data, device_id) and input_id == self._action_data.input_id:
            self.slider.setMarkerValue(value)
            

    def _update_axis_widget(self, value : float = None):
        ''' updates the axis output repeater with the value 
        
        :param value: the floating point input value, if None uses the cached value
        
        '''
        if value is None:
            value = self._current_input_axis()
        range_info = self._range_info
        value = self._gate_data._get_filtered_range_value(range_info, value)
        if value is not None:
            self.axis_widget.setValue(value)

    def _delay_changed_cb(self, delay):
        ''' delay value changed for gates or ranges '''
        if self._gate_info:
            self._gate_info.delay = delay
        elif self._range_info:
            self._range_info.delay = delay

    QtCore.Slot()
    def _delete_gate_confirm_cb(self):
        ''' delete requested '''
        self._remove_gate(self._range_info)

    def _prompt_delete(self) -> bool:
        message_box = QtWidgets.QMessageBox()
        message_box.setText("Delete confirmation")
        message_box.setInformativeText("This will delete this entry.\nAre you sure?")
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

    def _remove_gate(self, data, prompt = True):
        if prompt and not self._prompt_delete():
            return
        self._delete_confirmed_cb(data)

    def _delete_confirmed_cb(self, data):
        self.delete_requested.emit(self._range_info)
        self.close()

    QtCore.Slot()
    def _range_min_changed_cb(self):
        value = self.sb_range_min_widget.value()
        self._range_info.output_range_min = value
        self._update_axis_widget()        

    QtCore.Slot()
    def _range_max_changed_cb(self):
        self._range_info.output_range_max = self.sb_range_max_widget.value()
        self._update_axis_widget()        

    @QtCore.Slot()
    def _range_reset_cb(self):
        ''' reset range '''
        info_object = self._range_info
        self.sb_range_min_widget.setValue(info_object.range_min)
        self.sb_range_max_widget.setValue(info_object.range_max)

    QtCore.Slot()
    def _fixed_value_changed_cb(self):
        self._range_info.fixed_value = self.sb_fixed_value_widget.value()
        # update the repeater
        self._update_axis_widget()

    @QtCore.Slot()
    def _output_mode_changed_cb(self):
        ''' change the output mode of a range'''
        value = self.output_mode_widget.currentData()
        self._range_info.mode = value
        verbose = gremlin.config.Configuration().verbose_mode_gate
        if verbose:
            syslog.info(f"Range: set output mode: {value} for range {self._range_info.range_display_ex()} {self._range_info.id}")
        self._update_ui()
    
    @QtCore.Slot()
    def _range_description_changed(self):
        self._range_info.description = self.range_description_widget.text()

    @QtCore.Slot()
    def _gate_description_changed(self):
        self._gate_info.description = self.gate_description_widget.text()

    @QtCore.Slot(int)
    def _condition_changed_cb(self, index):
        widget = self._condition_tab.widget(index)
        condition : GateConditionType = widget.data
        # remember the last selected page for next time
        if self._range_info:
            self._range_info.setLastCondition(condition)
        else:
            self._gate_info.setLastCondition(condition)



    def _update_ui(self):
        ''' updates controls based on the options '''
        if self._is_range:
            # range conditions
            fixed_visible = self._range_info.mode == GateRangeOutputMode.Fixed
            range_visible = self._range_info.mode == GateRangeOutputMode.Ranged

            self.container_fixed_widget.setVisible(fixed_visible)
            self.container_output_range_widget.setVisible(range_visible)

            # update the repeater
            self._update_axis_widget()


    def _create_conditions_ui(self):
        ''' creates the conditions UI'''

        if self._is_range:
            # valid range conditions
            conditions = (GateConditionType.InRange, GateConditionType.EnterRange, GateConditionType.ExitRange, GateConditionType.OutsideRange)
        else:
            # valid gate conditions
            conditions = (GateConditionType.OnCross, GateConditionType.OnCrossIncrease, GateConditionType.OnCrossDecrease)            


        with QtCore.QSignalBlocker(self._condition_tab):     
            
            self._condition_tab.clear()
            for condition in conditions:
                condition_container_widget = gremlin.ui.ui_common.QDataWidget()
                condition_container_widget.data = condition # store the condition as the data 
                condition_container_layout = QtWidgets.QVBoxLayout(condition_container_widget)
                self._condition_pages[condition] = condition_container_widget
                self._condition_tab.addTab(condition_container_widget, f"Condition: {GateConditionType.to_display_name(condition)}")
                description_widget = QtWidgets.QLabel(GateConditionType.to_description(condition))
                condition_container_layout.addWidget(description_widget)
                
                
        
                if self._is_range: # range action
                    if condition not in (GateConditionType.InRange, GateConditionType.OutsideRange):
                        autorelease_widget = gremlin.ui.ui_common.QDataCheckbox("Autorelease")
                        autorelease_widget.setChecked(self._range_info.autorelease_map[condition])
                        autorelease_widget.data = (self._range_info, condition)
                        condition_container_layout.addWidget(autorelease_widget)
                        autorelease_widget.clicked.connect(self._autorelease_changed)
                else:
                    autorelease_widget = gremlin.ui.ui_common.QDataCheckbox("Autorelease")
                    autorelease_widget.setChecked(self._gate_info.autorelease_map[condition])
                    autorelease_widget.data = (self._gate_info, condition)
                    condition_container_layout.addWidget(autorelease_widget)
                    autorelease_widget.clicked.connect(self._autorelease_changed)
                    
                

                # all conditions are button type conditions except the in-range which is an axis
                input_type = InputType.JoystickButton 
                # condition specific widgets
                if condition == GateConditionType.InRange:
                    condition_container_layout.addWidget(self.output_container_widget)
                    condition_container_layout.addWidget(self.container_range_data_widget)
                    input_type = InputType.JoystickAxis

                item_data = self._range_info.itemData(condition) if self._is_range else self._gate_info.itemData(condition)
                container_widget = self._cache.retrieve_by_data(item_data)        
                if not container_widget:
                    # create the container, cache it
                    container_widget = gremlin.ui.input_item.InputItemMappingWidget(item_data, input_type = input_type, object_name = f"Gate: {item_data.display_name}")
                    self._cache.register(item_data, container_widget)
                condition_container_layout.addWidget(container_widget)
                

            # pick the last used condition
            condition = self._range_info.condition if self._is_range else self._gate_info.condition
            index = conditions.index(condition)
            self._condition_tab.setCurrentIndex(index)

        self._update_tab_icons()

    @QtCore.Slot(bool)
    def _autorelease_changed(self, checked):
        ''' called when the autorelease checkbox is changed '''
        info, condition = self.sender().data
        info.autorelease_map[condition] = checked


    def _update_tab_icons(self):
        ''' updates the tab icons based on the container status '''
        
        for index in range(self._condition_tab.count()):
            widget = self._condition_tab.widget(index)
            condition = widget.data
            has_condition = self._range_info.hasContainers(condition) if self._is_range else self._gate_info.hasContainers(condition)
            self._condition_tab.setTabIcon(index, self._icon_enabled if has_condition else self._icon_disabled)
                
    QtCore.Slot(object)
    def _mapping_changed_cb(self, item_data : gremlin.ui.input_item.InputItemMappingWidget):
        ''' hooks a mapping change '''
        item_data_map = self._range_info.item_data_map if self._is_range else self._gate_info.item_data_map
        if item_data in item_data_map.values():
            # one of ours - update the icon status
            self._update_tab_icons()
            



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

    delete_requested = Signal(object) # fired when the remove button is clicked - passes the GateData to blitz
    duplicate_requested = Signal(object) # fired when the duplicate button is clicked - passes the GateData to duplicate
    configure_requested = Signal(object) # configure clicked
    configure_range_requested = Signal(object) # configure range - data = range object
    configure_gate_requested = Signal(object) # configure gate - data = gate object


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

        self.id = gremlin.util.get_guid() # unique ID for this widget

        self._deleted = False
        self._stack = [] # save stack for saved state
        self.setObjectName(f"{object_name} [{self.id}]" if object_name else f"GateAxisWidget: [{self.id}]")
        config = gremlin.config.Configuration()
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


        self.container_options_widget = QtWidgets.QWidget()
        self.container_options_widget.setContentsMargins(0,0,0,0)
        

        self.container_options_layout = QtWidgets.QHBoxLayout(self.container_options_widget)
        self.container_options_widget.setContentsMargins(0,0,0,0)

        self._use_default_range_widget = QtWidgets.QCheckBox("Use default range for axis output")
        self._use_default_range_widget.setChecked(self._gate_data.use_default_range)
        self._use_default_range_widget.clicked.connect(self._use_default_range_changed_cb)
        self._use_default_range_widget.setToolTip("When set, the axis output uses the default range setting for value output, sub-ranges can still be used to trigger actions based on entry/exit of ranges")

        self._display_label_widget = QtWidgets.QLabel("Display Mode:")
        self._display_mode_widget = gremlin.ui.ui_common.QComboBox()
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

        self.container_options_layout.addWidget(self._configure_trigger_widget)
        self.container_options_layout.addWidget(self._use_default_range_widget)
        self.container_options_layout.addWidget(self._display_label_widget)
        self.container_options_layout.addWidget(self._display_mode_widget)
        self.container_options_layout.addStretch()


        # holds gateinfo widgets
        self.container_gate_ui_widget, self.container_gate_ui_layout = gremlin.ui.ui_common.getVContainer()
        self.container_gate_ui_widget.setContentsMargins(8,0,0,0)
        
        css_table = "QTableWidget {border: none;}"

        self.container_gate_widget, self.container_gate_layout = gremlin.ui.ui_common.getVContainer()
        table = QtWidgets.QTableWidget()
        table.setStyleSheet(css_table)
        self.gate_table_widget = table


        self.gate_count_widget = QtWidgets.QLabel()
        self.container_gate_layout.addWidget(self.gate_count_widget)
        self.container_gate_layout.addWidget(self.gate_table_widget)
        
        self.container_range_widget, self.container_range_layout = gremlin.ui.ui_common.getVContainer()
        table = QtWidgets.QTableWidget()
        table.setStyleSheet(css_table)
        self.range_table_widget = table
        

        self.range_count_widget = QtWidgets.QLabel()
        self.container_range_layout.addWidget(self.range_count_widget)
        self.container_range_layout.addWidget(self.range_table_widget)
        
        self.container_gate_ui_layout.addWidget(self.container_gate_widget)
        self.container_gate_ui_layout.addWidget(self.container_range_widget)


        # steps container
        self._create_steps_ui()

        # ranged container
        self._create_output_ui()

        row = 1
        self.main_layout.addWidget(self.container_slider_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_steps_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_gate_ui_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_options_widget,row,0,1,-1)
        row+=1
        self.main_layout.addWidget(self.container_output_widget,row,0,1,-1)
        row+=1
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
        gh.slider_update_event.connect(self._handle_slider_update)


        # create range data 
              
        self._reload_gates()
        self._reload_widgets()


        # keyboard hook for undo key
        eh = gremlin.event_handler.EventListener()
        eh.keyboard_event.connect(self._keyboard_handler)

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
            # gh = GateEventHandler()
            # gh.unregisterValueChangedCallback(self.id, self._update_slider_marker)        


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
            # unhook first
            self.unhook()

        verbose = gremlin.config.Configuration().verbose_mode_gate
        if verbose:
            syslog.info(f"gate axis widget: hook {self.id} {self.action_data.input_display_name}")

        
        self._gate_data.hook()

        # hook events 
        gh = GateEventHandler()
        gh.gatedata_stepsChanged.connect(self._update_steps_cb)
        gh.gatedata_valueChanged.connect(self._update_values_cb)

        gh.gate_order_changed.connect(self._gate_order_changed_cb)
        gh.gate_value_changed.connect(self._gate_value_changed)
        gh.gates_changed.connect(self._gates_changed)
        gh.use_default_range_changed.connect(self._update_range_display)
        gh.gate_configuration_changed.connect(self._gate_configuration_changed)


        


        self._hooked = True

    def unhook(self):
        # unhook connections
        if self._hooked:
            verbose = gremlin.config.Configuration().verbose_mode_gate
            if verbose:
                syslog.info(f"gate axis widget: unhook {self.id} {self.action_data.input_display_name}")

            gh = GateEventHandler()

            gh.gatedata_stepsChanged.disconnect(self._update_steps_cb)
            gh.gatedata_valueChanged.disconnect(self._update_values_cb)

            gh.gate_order_changed.disconnect(self._gate_order_changed_cb)
            gh.gate_value_changed.disconnect(self._gate_value_changed)
            gh.gates_changed.disconnect(self._gates_changed)
            gh.use_default_range_changed.disconnect(self._update_range_display)
            gh.gate_configuration_changed.disconnect(self._gate_configuration_changed)
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
        gremlin.util.InvokeUiMethod(self._sort_gate_layout_ui)
    
    def _sort_gate_layout_ui(self):
        ''' updates and sorts the gate container layout '''
        if not Shiboken.isValid(self):
            return

        if not Shiboken.isValid(self.gate_table_widget):
            return

        self._gwi_map.clear()
        table = self.gate_table_widget
        table.clear()
        
        row = 0
        col = 0
        gate_list = self.gate_data.getUsedGates()
        gate_count = len(gate_list)

        max_col = self._max_col if gate_count > self._max_col else gate_count
        max_row = 1 + (len(gate_list) // max_col)
        max_col += (max_col-1) # spacer columns
        table.setColumnCount(max_col)
        table.setRowCount(max_row)
        verbose = gremlin.config.Configuration().verbose_mode_gate

        if verbose: syslog.info("Gate table:")
        for index, gate in enumerate(gate_list):
            # create a widget for this gate
            gate.slider_index = index
            widget = GateWidgetInfo(gate, self._configure_gate_cb,
                                self._delete_gate_confirm_cb,
                                self._grab_cb,
                                is_container=gate.hasAnyContainers(),
                                parent = table
                                )
            

            self._update_gate_icon(gate.slider_index, gate)
            widget.valueChanged.connect(self._gate_value_changed)

            table.setCellWidget(row, col, widget)
            self._gwi_map[gate] = ((row, col), widget)
            if verbose: syslog.info(f"\t{gate.to_display()} ({row},{col})")

            col += 1
            table.setCellWidget(row, col, QtWidgets.QLabel(" ")) # spacer
            col += 1
            

            
            if col >= max_col:
                col = 0
                row += 1
        
        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        table.horizontalHeader().setVisible(False)
        table.verticalHeader().setVisible(False)

        self.gate_count_widget.setText(f"Gates ({gate_count}):")

            
   
    def _reload_ranges(self):
        ''' when gates change, reload ranges '''
        if not Shiboken.isValid(self):
            return
        gremlin.util.assert_ui_thread()

        self._rwi_map.clear()

        table = self.range_table_widget
        table.clear()
        
        range_list = self._gate_data.updateRanges()
        range_count = len(range_list)
        
        max_col = self._max_col if range_count > self._max_col else range_count
        max_row = 1 + (len(range_list) // max_col)
        max_col += (max_col-1) # spacer columns
        table.setColumnCount(max_col)
        table.setRowCount(max_row)


        verbose = gremlin.config.Configuration().verbose_mode_gate
        if verbose: syslog.info(f"Reload range: found {len(range_list)} used ranges")
    
        index = 0
        row = 0
        col = 0
        decimals = self._gate_data.decimals
        if verbose: syslog.info("Range table:")
        for index, rng in enumerate(range_list):
            
            widget = RangeWidgetInfo(index + 1, 
                                rng,
                                decimals,
                                self._configure_range_cb,
                                parent = table
                                )
            
            table.setCellWidget(row, col, widget)
            
            if verbose: syslog.info(f"\tRange: {rng.to_display()} ({row},{col})")
            self._rwi_map[rng] = (row, col)
            
            col += 1
            table.setCellWidget(row, col, QtWidgets.QLabel(" ")) # spacer
            col += 1

            if col >= max_col:
                col = 0
                row += 1


        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        table.horizontalHeader().setVisible(False)
        table.verticalHeader().setVisible(False)

        self._update_range_display()

    def _update_range_display(self):
        ''' called when the range display mode changes '''
        if not Shiboken.isValid(self):
            return
        widgets = [self.get_range_widget(rwi) for rwi in self._rwi_map.keys()]
        # widgets = [widget for widget in widgets if widgets is not None]
        widget : RangeWidgetInfo
        if self._gate_data.use_default_range:
            # enable single range mode on the slider
            self._slider_widget.singleRange = True
            # hide the ranges
            range_count = 1
            for widget in widgets:
                widget.range_info.setUsed(False)
                widget.setVisible(False)
            self._gate_data.default_range.setUsed(True)
        else:
            
            range_count = len(widgets)
            # disable single range mode on the slider
            self._slider_widget.singleRange = False
            self._gate_data.default_range.setUsed(False)
            
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
        
        elif gate in self._gate_data.getGates():
            self._set_slider_gate_value(gate.slider_index, gate.value)

        

    def _gates_changed(self):
        gremlin.util.InvokeUiMethod(self._gates_changed_ui)

    def _gates_changed_ui(self):
        if not Shiboken.isValid(self):
            return
        for gate in self._gate_data.getGates():
            self._set_slider_gate_value(gate.slider_index, gate.value)
        # update icons on value change
        self._update_gate_icons()


    @QtCore.Slot(GateInfo)
    def _gate_configuration_changed(self, gate : GateInfo):
        ''' called when the gate configuration changes '''
        if gate in self._gate_data.getGates():
            self._update_gate_icon(gate.slider_index, gate)
        

    @QtCore.Slot()
    def _gate_order_changed_cb(self):
        ''' called when a gate value changed which may force a gate display re-order '''
        self._sort_gate_layout()
        

    # def _gate_order_callback(self, item : QtWidgets.QWidgetItem):
    #     gate : GateInfo = item.widget().data
    #     return gate.slider_index

    def get_gate_gwi(self, gate : GateInfo) -> GateWidgetInfo:
        ''' gets the gate widget info for a given gate '''
        if gate in self._gwi_map.keys():
            _, widget = self._gwi_map[gate]  # contains (row, col), widget
            if Shiboken.isValid(widget):
                return widget
        return None
    
    def get_gate_widget(self, gate : GateInfo) -> GateWidgetInfo:
        ''' returns the widget for the corresponding gate '''
        return self.get_gate_gwi(gate)
    
    def get_range_widget(self, rng : RangeInfo):
        ''' returns the widget for the corresponding range '''
        if rng in self._rwi_map.keys():
            row, col  = self._rwi_map[rng]
            widget = self.range_table_widget.cellWidget(row, col)
            return widget
        return None
    

    @QtCore.Slot(bool)
    def _use_default_range_changed_cb(self, checked):
        self._gate_data.use_default_range = checked
        eh = GateEventHandler()
        eh.use_default_range_changed.emit()
        

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
        
        count = len(self._gate_data.getGates())
        gate = self._gate_data.findGate(value)
        if not gate and count < 20:
            self._add_gate(value)
            self._update_ui()

    @QtCore.Slot(float)
    def _slider_range_configure_cb(self, value):
        ''' fired when the user clicked on the groove - adds a gate at that location '''
        rng = self._gate_data.findRangeByValue(value)
        if rng is not None:
            self._configure_range_exec(rng)
        
    @QtCore.Slot(int)
    def _slider_drag_start_cb(self, handle_index):
        ''' called when a handle is being dragged '''
        self._pushState()



    @QtCore.Slot(int, float)
    def _slider_value_changed_cb(self, index, value):
        ''' occurs when the slider values change '''
        gate : GateInfo = self._gate_data.getGateSliderIndex(index)
        if gate is not None:
            gate.setValue(value, emit = False)

    def _set_slider_gate_value(self, index, value):
        ''' sets a gate value on the slider '''
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
            
            if self.verbose_ui: syslog.info(f"GATE Widget: update slider : {self.objectName()} values: {values}")
            gremlin.util.assert_ui_thread()
            
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
    def _grab_cb(self):
        ''' grab the min value from the axis position '''


        gate : GateInfo
        gate, widget = self.sender().data  # the button's data field contains the widget to update
        gwi : GateWidgetInfo
        _, gwi = self._gwi_map[gate]
        if Shiboken.isValid(gwi):
            value = self._axis_value
            gwi.setValue(value)
            self._set_slider_gate_value(gate.slider_index, value)
        

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


    QtCore.Slot(object, GateInfo)
    def _delete_gate_confirm_cb(self):
        ''' delete requested '''
        widget = self.sender()
        gate = widget.data
        self._remove_gate(gate)

    def _remove_gate(self, gate, prompt = True):
        gremlin.util.InvokeUiMethod(self._remove_gate_ui, gate, prompt)

    def _remove_gate_ui(self, gate, prompt : bool):

        # ensure there are at least two gates left
        count = len(self._gate_data._gate_used_gates())
        if count <= 2:
            syslog.warning("Unable to delete gate: at least two gates must be defined.")
            gremlin.ui.ui_common.MessageBox(prompt="Unable to remove this gate.  At least two gates must be defined.")
            return # do not allow fewer than 2 gates

        if prompt and not self._prompt_delete():
            return
        
        self.deleteGate(gate)

    def _delete_confirmed_cb(self, gate):
         self.deleteGate(gate)

    def _delete_gate_cb(self, gate):
        ''' delete the gate '''
        self.deleteGate(gate)


    def _configure_range_cb(self):
        gremlin.util.InvokeUiMethod(self._configure_range_cb_ui)    
        
    @QtCore.Slot()
    def _configure_range_cb_ui(self):
        ''' open the configuration dialog for ranges '''
        widget = self.sender()  # the button's data field contains the widget to update
        rng = widget.data
        self._configure_range_exec(rng)


    def _configure_range_exec(self, rng : RangeInfo):
        connected = gremlin.util.isSignalConnected(self,"configure_range_requested")
        if connected:
            self.configure_range_requested.emit(rng)
        else:
            dialog = ActionContainerUi(gate_data = self._gate_data, info_object = rng, action_data = self.action_data, input_type = InputType.JoystickAxis)
            dialog.exec()
            gh = GateEventHandler()
            gh.range_configuration_changed.emit(rng)



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
        widget,_ = gremlin.ui.ui_common.getVContainer([QtWidgets.QLabel(msg),
                                                       line])

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
        widget,_ = gremlin.ui.ui_common.getVContainer([QtWidgets.QLabel(msg),
                                                       line])

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
        ''' handle right clicked - pass event along '''
        connected = gremlin.util.isSignalConnected(self, "configure_gate_requested")
        if connected:
            # event is connected
            self.configure_gate_requested.emit(gate)
        else:
            # default action = show dialog
            gate = self._gate_data.getGateSliderIndex(handle_index)
            dialog = ActionContainerUi(gate_data = self._gate_data, info_object = gate, action_data=self.action_data, input_type = InputType.JoystickButton)
            # gates can be deleted
            dialog.delete_requested.connect(self._delete_gate_cb)
            dialog.exec()
            

    
    def _configure_gate_cb(self):
        ''' gate configure button clicked '''
        widget = self.sender()  # the button's data field contains the widget to update
        gate = widget.data
        connected = gremlin.util.isSignalConnected(self,"configure_gate_requested")
        if connected:
            # call the handler
            self.configure_gate_requested.emit(gate)
        else:
            dialog = ActionContainerUi(gate_data = self._gate_data, info_object = gate, action_data = self.action_data, input_type=InputType.JoystickButton)
            dialog.delete_requested.connect(self._delete_gate_cb)
            dialog.exec()
            
        

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
                    self._update_output_value()

                if verbose_ui: syslog.info(f"GATE Widget: update slider marker completed")
        finally:
            self._lock = False

    def _create_filter_widgets(self):
        gremlin.util.clear_layout(self.container_filter_layout)
        self._filter_widgets = []
        row = 0
        col = 0
        for _, trigger in enumerate(TriggerMode):
            widget = gremlin.ui.ui_common.QDataCheckbox(TriggerMode.to_display_name(trigger), data = trigger)
            if not trigger in self._gate_data.filter_map.keys():
                self._gate_data.filter_map[trigger] = True
            widget.setChecked(self._gate_data.filter_map[trigger])
            widget.clicked.connect(self._filter_cb)
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

    @QtCore.Slot()
    def _clear_all_filters_cb(self):
        ''' clear all filters'''
        for widget in self._filter_widgets:
            widget.setChecked(False)            


    @QtCore.Slot(bool)
    def _filter_cb(self, checked):
        widget = self.sender()
        trigger : TriggerMode = widget.data
        self._gate_data.filter_map[trigger] = checked

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
        gate = self._gate_data.findGate(value) if check_exists else None
        if gate and gate.used:
            return gate
        
        if not gate:
            # get one of the available gates
            gate : GateInfo = self.gate_data.getUnusedGate()

        if not gate:
            # ran too many gates
            message_box = QtWidgets.QMessageBox()
            message_box.setText("Too many gates are defined")
            pixmap = gremlin.util.load_pixmap("warning.svg")
            pixmap = pixmap.scaled(32, 32, QtCore.Qt.KeepAspectRatio)
            message_box.setIconPixmap(pixmap)
            message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
            message_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Ok)
            gremlin.util.centerDialog(message_box)
            message_box.exec()
            return
        
        self._pushState() # for undo

        # mark it used
        gate.setUsed(True)
        gate.setValue(value, False)

        # update ranges
        self.gate_data._update_ranges()

        self._reload_widgets()

        return gate
    
    def _set_gate_count(self, gate_count):
        ''' sets the number of gates on the widget 

        :param gate_count: number of gates to set - if higher - gates are created - if lower - gates are removed 

        '''
        # add the missing steps only (re-use other steps so we don't lose their config)
        gates = self._gate_data.getUsedGates()
        max_gates = GateData.max_gates
        if gate_count > max_gates:
            gremlin.ui.ui_common.MessageBox(prompt = f"Unable to add the requested gates: The Maximum gate count is reached ({max_gates})")
            return
        

        current_steps = len(gates)
        ranges = self._gate_data.getUsedRanges()
        verbose = gremlin.config.Configuration().verbose_mode_gate
        if current_steps < gate_count:

            # how many gates to add
            steps = gate_count - current_steps

            if verbose:
                syslog.info(f"Set gate count: add {steps} gates")

            # add steps in the middle of existing ranges to spread them
            # if we run out of ranges, repeat with the new steps added
            while steps > 0:
                pairs = [r.range() for r in ranges]
                for pair in pairs:
                    v1,v2 = pair
                    value = (v1 + v2) / 2
                    self._add_gate(value, False)
                    steps -=1
                    if steps == 0:
                        break
            if steps > 0:
                # range approach failed, brute force add
                interval = 2.0 / steps
                value = -1 + interval
                while steps > 0:
                    self._add_gate(value, False)
                    value += interval
                    steps -=1


        elif current_steps > gate_count:
            # mark the items at unused
            # how many gates to add
            steps = current_steps - gate_count

            if verbose:
                syslog.info(f"Set gate count: reduce {steps} gates")

            # user was already prompted to confirm removal
            for index in range(gate_count, current_steps):
                gate = gates[index]
                self._remove_gate(gate, False)



    
        if verbose: 
            gates = self._gate_data.getUsedGates()
            syslog.info(f"Updated gates:")
            for gate in gates:
                syslog.info(f"\tGate: {gate.slider_index} {gate.value:0.{_decimals}f}")


        #self._gate_data._update_gate_index()
        self._gate_data._update_ranges()
        # update slider values
        values = self.gate_data.getGateValues()
        self._update_slider(values)
        eh = GateEventHandler()
        eh.gatedata_stepsChanged.emit(self) # indicate step data changed
        self._reload_gates()
    

    @QtCore.Slot()
    def _add_gate_cb(self):
        ''' adds a new gate at the current input position '''
        value = self._gate_data._axis_value
        count = len(self._gate_data.getGates())
        gate = self._gate_data.findGate(value)
        if not gate and count < 20:
            self._add_gate(value)
            self._update_ui()
        
        

    @QtCore.Slot()
    def _set_steps_cb(self):
        ''' sets the number of steps to set/reset when the set step button is clicked'''
        target_count = self.sb_steps_widget.value()
        gate_count = self._gate_data.steps
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
                widget._update_icon()


    def _update_output_value(self):
        gremlin.util.InvokeUiMethod(self._update_output_value_ui)

    def _update_output_value_ui(self):
        ''' updates triggers and UI when the slider input value changes '''
        if not Shiboken.isValid(self):
            return
        if self._gate_data is not None:
            self.output_range_trigger_widget.setPlainText(self._gate_data.trigger_range_text)
            # scroll to bottom
            vbar = self.output_range_trigger_widget.verticalScrollBar()
            vbar.setValue(vbar.maximum())

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
            self._update_output_value()

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
            self._update_output_value()

    
    def _update_ui(self):
        ''' updates visibility of UI components based on the active options '''
        if not Shiboken.isValid(self):
            return
        if Shiboken.isValid(self._slider_widget):
            self._update_slider(self._gate_data.getGateValues())
            self._update_output_value()

    def deleteGate(self, gate):
        gremlin.util.InvokeUiMethod(self._delete_gate_ui, gate)

    def _delete_gate_ui(self, gate : GateInfo):
        ''' remove a gate from this widget '''
        if not Shiboken.isValid(self):
            return
        gwi : GateWidgetInfo
        _, gwi = self._gwi_map[gate]
        gwi.setUsed(False)
        #self._gate_data.deleteGate(gwi)
        #self._gate_data._update_gate_index()
        self._gate_data._update_ranges()
        gwi._update_icon()
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
        if verbose_ui: syslog.info(f"Gated Axis Action: init : {object_name}")
        

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
        # all the work happens in the gate widget hook function 
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
        return f"Gated Axis: gates: [{len(self.gates)}]"

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
