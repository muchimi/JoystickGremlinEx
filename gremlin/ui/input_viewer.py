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

import copy
import enum
import time

from PySide6 import QtCore, QtGui, QtWidgets
import lxml.etree
import dinput

import gremlin
import gremlin.config
import gremlin.gamepad_handling
import gremlin.joystick_handling
import gremlin.keyboard
import gremlin.shared_state
import gremlin.ui.virtual_keyboard
import gremlin.util
from . import ui_common
from gremlin.input_types import InputType
from gremlin.types import VisualizationType
import os
from lxml import etree
import gremlin.singleton_decorator
import logging
import gremlin.ui.ui_common
from vigem import vigem_gamepad as vg
import gremlin.ui.state_device

syslog = logging.getLogger("system")

@gremlin.singleton_decorator.SingletonDecorator
class VisualizationConfig():
    ''' stores data '''
    def __init__(self):
        self._config = {}  # map of device guid, input_type, input_id - selected flag
        self.reload()

    def getValue(self, device_guid, input_type : VisualizationType) -> bool:
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if device_guid in self._config:
            id = int(input_type)
            if id in self._config[device_guid]:
                return self._config[device_guid][id]
        return False
    
    def setValue(self, device_guid, input_type : VisualizationType, value):
        if not isinstance(device_guid, str):
            device_guid = str(device_guid)
        if not device_guid in self._config:
            self._config[device_guid] = {}
        id = int(input_type)
        self._config[device_guid][id] = value


    def save(self):
        ''' saves to the config file '''
        fname = self.get_config()

        syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose
        if verbose: 
            syslog.info("INPUT VIEWER: save configuration")

        root = etree.Element("config")
        for device_guid in self._config:
            for id in self._config[device_guid]:
                value = self._config[device_guid][id]
                node = etree.Element("data")
                node.set("device-guid", device_guid)
                node.set("id",str(id)) # visualization type
                node.set("value", str(value))
                root.append(node)
                device_name = gremlin.joystick_handling.device_name_from_guid(device_guid)
                input_type = VisualizationType(id).name
                node_comment = etree.Comment(f"{device_name}  {device_guid} type: {input_type}")
                node.addprevious(node_comment)


        try:
            tree = etree.ElementTree(root)
            tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")
        except:
            pass

    def clear(self):
        ''' clears config selection '''
        self._config.clear()


    def reload(self):
        fname = self.get_config()
        load_successful = False
        if os.path.isfile(fname):
            try:
                parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
                t = etree.parse(fname, parser=parser)
                for node in t.findall(".//data"):
                    device_guid = node.get("device-guid")
                    id = int(node.get("id"))
                    value = bool(node.get("value"))
                    self.setValue(device_guid, id, value)
                load_successful = True
            except ValueError:
                pass

        if not load_successful:
            self._config = {}



    def get_config(sef):
        fname = os.path.join(gremlin.shared_state.data_path, "inputViewer.xml")
        return fname
    
    
class VisualizationSelector(QtWidgets.QWidget):

    """Presents a list of devices and visualization widgets."""

    # Event emitted when the visualization configuration changes
    changed = QtCore.Signal(dinput.DeviceSummary,VisualizationType,bool)
    clear = QtCore.Signal() # delete all

    def __init__(self, change_callback, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        devices = gremlin.joystick_handling.joystick_devices()

        self._selector_widgets = []
        self._selector_callbacks = {}

        
        # get the order of the devices as set by the user for the physical devices
        tab_map = gremlin.shared_state.ui._get_tab_map()
        tab_ids = [device_id for device_id, _, _, _ in tab_map.values()]
        d_list = []
        max_index = len(devices)
        for dev in devices:
            if dev.device_id in tab_ids:
                index = tab_ids.index(dev.device_id)
                d_list.append((index, dev))
            else:
                # add to the end (vjoy devices)
                d_list.append((max_index, dev))


        d_list.sort(key=lambda x: (x[0], x[1].vjoy_id, x[1].name))
        devices = [dev for _, dev in d_list]


        config = VisualizationConfig()

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        

        dev : dinput.DeviceSummary
        for dev in devices:
            
            box = QtWidgets.QGroupBox(dev.name)

            at_cb = gremlin.ui.ui_common.QDataCheckbox("Axes - Temporal", data = (VisualizationType.AxisTemporal, dev))
            at_cb.setIgnoreKeyboard(True)
            callback = self._create_callback(dev, VisualizationType.AxisTemporal, at_cb)
            at_cb.clicked.connect(callback)
            self._selector_callbacks[at_cb] = callback

            ac_cb = gremlin.ui.ui_common.QDataCheckbox("Axes - Current",  data = (VisualizationType.AxisCurrent, dev))
            ac_cb.setIgnoreKeyboard(True)
            callback = self._create_callback(dev, VisualizationType.AxisCurrent, ac_cb)
            ac_cb.clicked.connect(callback)
            self._selector_callbacks[ac_cb] = callback

            bh_cb = gremlin.ui.ui_common.QDataCheckbox("Buttons + Hats",  data = (VisualizationType.ButtonHat, dev))
            bh_cb.setIgnoreKeyboard(True)
            callback = self._create_callback(dev, VisualizationType.ButtonHat, bh_cb)
            bh_cb.clicked.connect(callback)
            self._selector_callbacks[bh_cb] = callback



            layout = QtWidgets.QVBoxLayout()
            layout.addWidget(at_cb)
            layout.addWidget(ac_cb)
            layout.addWidget(bh_cb)

            self._selector_widgets.append(at_cb)
            self._selector_widgets.append(ac_cb)
            self._selector_widgets.append(bh_cb)

            box.setLayout(layout)

            self.main_layout.addWidget(box)

            # update based on settings
            device_guid = dev.device_guid
            checked = config.getValue(device_guid, VisualizationType.AxisTemporal)
            at_cb.setChecked(checked)
            if checked: change_callback(dev, VisualizationType.AxisTemporal,True)

            checked = config.getValue(device_guid, VisualizationType.AxisCurrent)
            ac_cb.setChecked(checked)
            if checked: change_callback(dev, VisualizationType.AxisCurrent, True)

            checked = config.getValue(device_guid, VisualizationType.ButtonHat)
            bh_cb.setChecked(checked)
            if checked: change_callback(dev, VisualizationType.ButtonHat, True)


    @QtCore.Slot()
    def _clear_selection(self):
        ''' clears the selection of all widgets '''
        self.clear.emit()
        for widget in self._selector_widgets:
            with QtCore.QSignalBlocker(widget):
                widget.setChecked(False)

    @QtCore.Slot()
    def _select_real(self):
        ''' selects all hardware inputs '''
        for widget in self._selector_widgets:
            visualization, dev = widget.data
            if visualization != VisualizationType.AxisTemporal and not dev.is_virtual:
                with QtCore.QSignalBlocker(widget):
                    widget.setChecked(True)
            else:
                widget.setChecked(False)
            self._create_callback(dev, visualization, widget)()


                    
        
    @QtCore.Slot()
    def _select_all(self):
        ''' selects all widgets '''
        
        for widget in self._selector_widgets:
            with QtCore.QSignalBlocker(widget):
                widget.setChecked(True)
            visualisation, dev = widget.data
            self._create_callback(dev, visualisation, widget)()
            


    


    def _create_callback(self, device, vis_type, cb):
        """Creates the callback to trigger visualization updates.

        :param device the device being updated
        :param vis_type visualization type being updated
        """
        return lambda : self._callback(device,vis_type,cb)
    
    def _callback(self, device, vis_type, cb):

        checked = cb.isChecked()
        config = VisualizationConfig()
        config.setValue(device.device_guid, vis_type, checked)
        self.changed.emit(device,vis_type,checked)

class InputViewerUi(ui_common.BaseDialogUi):

    """Main UI dialog for the input viewer."""

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(self.__class__.__name__, parent)

        self._widget_storage = {}
        self.setMinimumHeight(800)

        self.setWindowTitle("GremlinEx Input Viewer")
        self.setWindowFlag(QtCore.Qt.WindowMaximizeButtonHint, True)
        self.setWindowFlag(QtCore.Qt.WindowMinimizeButtonHint, True)

        sd = gremlin.ui.state_device.StateData()
        sd.crud.connect(self._state_crud)

        self.devices = gremlin.joystick_handling.joystick_devices()
        self.gamepad_devices = gremlin.gamepad_handling.gamepadDevices()

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self._keyboard_visualizer_widget = None
        self._state_visualizer_widget = None
        self._state_buttons = {} # map of key widget
        self.keyboard_widget = None # keyboard widget

        
        widget, layout = gremlin.ui.ui_common.getVContainer()
        self.view_container_widget = widget
        self.view_container_layout = layout
        self.views = InputViewerArea()

        self.view_container_layout.addWidget(self.views)


        # configure the scroll area for the selectors
        self.scroll_selector_layout = QtWidgets.QVBoxLayout()
        self.scroll_selector_area = QtWidgets.QScrollArea()
        self.scroll_selector_widget = QtWidgets.QWidget()

        # Configure the widget holding the layout with all the buttons
        self.scroll_selector_widget.setLayout(self.scroll_selector_layout)
        self.scroll_selector_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Expanding)
        self.scroll_selector_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.scroll_selector_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        
        self.scroll_selector_area.setMinimumWidth(200)
        self.scroll_selector_area.setWidgetResizable(True)
        self.scroll_selector_area.setWidget(self.scroll_selector_widget)

        config = VisualizationConfig()

        self.keyboard_widget_selector = gremlin.ui.ui_common.QDataCheckbox("Keyboard")
        self.keyboard_widget_selector.setIgnoreKeyboard(True)
        checked = config.getValue(gremlin.shared_state.keyboard_tab_guid, VisualizationType.Keyboard)
        self.keyboard_widget_selector.setChecked(checked)
        self.keyboard_widget_selector.clicked.connect(self._toggle_keyboard_widget)

        self.state_widget_selector = gremlin.ui.ui_common.QDataCheckbox("State")
        self.state_widget_selector.setIgnoreKeyboard(True)
        checked = config.getValue(gremlin.shared_state.state_tab_guid, VisualizationType.State)
        self.state_widget_selector.setChecked(checked)
        self.state_widget_selector.clicked.connect(self._toggle_state_widget)


        self.vis_selector = VisualizationSelector(self._add_remove_visualization_widget)
        self.vis_selector.changed.connect(self._add_remove_visualization_widget)
        self.vis_selector.clear.connect(self._clear)


        system_selector_widget =  QtWidgets.QGroupBox("System Inputs")
        system_selector_layout = QtWidgets.QHBoxLayout(system_selector_widget)
    
        system_selector_layout.addWidget(self.keyboard_widget_selector)
        system_selector_layout.addWidget(self.state_widget_selector)

        self.scroll_selector_layout.addWidget(system_selector_widget)
        self.scroll_selector_layout.addWidget(self.vis_selector)


                
        clear_widget = QtWidgets.QPushButton("Clear")
        clear_widget.setToolTip("Clears the selection")
        clear_widget.clicked.connect(self.vis_selector._clear_selection)

        select_all_widget = QtWidgets.QPushButton("Select All")
        select_all_widget.setToolTip("Selects all inputs")
        select_all_widget.clicked.connect(self.vis_selector._select_all)

        select_real_widget = QtWidgets.QPushButton("Select Hardware")
        select_real_widget.setToolTip("Selects all hardware inputs")
        select_real_widget.clicked.connect(self.vis_selector._select_real)

        options_widget, _ = gremlin.ui.ui_common.getHContainer((clear_widget, select_real_widget, select_all_widget))

        self.main_layout.addWidget(options_widget)

        content_widget, _ = gremlin.ui.ui_common.getHContainer((self.scroll_selector_area, self.view_container_widget))
        # Add the scroll area to the main layout
        self.main_layout.addWidget(content_widget)
        self.closed.connect(self._closed)


        config = VisualizationConfig()
        self._keyboard_visible = config.getValue(gremlin.shared_state.keyboard_tab_guid, VisualizationType.Keyboard)
        self._toggle_keyboard_widget(self._keyboard_visible)

        self._state_visible = config.getValue(gremlin.shared_state.state_tab_guid, VisualizationType.State)
        self._toggle_state_widget(self._state_visible)


        self.installEventFilter(self)

    def eventFilter(self, widget, event):
        # filter events for keys so the window hotkeys don't interfere with the keyboard repeater
        if self._keyboard_visible:
            # keyboard visible - filter keys
            t = event.type()
            if t in (QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.KeyRelease): 
                return True
        return super().eventFilter(widget, event)
        



    @QtCore.Slot()
    def _closed(self):
        ''' save the config on close'''
        if self.keyboard_widget:
            self.keyboard_widget.unhook()
        config = VisualizationConfig()
        config.save()

    @QtCore.Slot()
    def _clear(self):
        ''' clears all widgets '''
        widget_list = [widget for widget in self._widget_storage.values()]
        for widget in widget_list:
            if widget == self.keyboard_widget:
                with QtCore.QSignalBlocker(self.keyboard_widget_selector):
                    self.keyboard_widget_selector.setChecked(False)
            if hasattr(widget,"unhook"):
                widget.unhook()
            widget.setParent(None)
            
        self._widget_storage.clear()
        self.hideKeyboard()
        config = VisualizationConfig()
        config.clear()
        config.save()



    @QtCore.Slot(dinput.DeviceSummary,VisualizationType,bool)
    def _add_remove_visualization_widget(self, device, visualization : VisualizationType, is_active : bool):
        """Adds or removes a visualization widget.

        :param device the device which is being updated
        :param vis_type the visualization type being updated
        :param is_active if True the visualization is added, if False it is
            removed
        """
        key = (device, visualization)
        if is_active:
            widget = ui_common.JoystickDeviceWidget(device, visualization)

            self.views.add_widget(widget)
            self._widget_storage[key] = widget
            widget.hook()
        elif key in self._widget_storage:
            widget = self._widget_storage[key]
            widget.unhook()
            self.views.remove_widget(widget)
            del self._widget_storage[key]

        self._update_view()

        
    def showKeyboard(self):
        ''' keyboard device '''
        if not self._keyboard_visualizer_widget:
            
            self._keyboard_visualizer_widget =  QtWidgets.QGroupBox("Keyboard")
            self.keyboard_visualizer_layout = QtWidgets.QVBoxLayout(self._keyboard_visualizer_widget)
            self.keyboard_widget = gremlin.ui.virtual_keyboard.QKeyboardWidget()
            self.keyboard_widget.setReadonly(True)
            self.keyboard_visualizer_layout.addWidget(self.keyboard_widget)
            self.keyboard_widget.hook()
            self.views.add_widget(self._keyboard_visualizer_widget)
            key = (gremlin.shared_state.keyboard_tab_guid, VisualizationType.Keyboard)
            self._widget_storage[key] = self._keyboard_visualizer_widget
            self._keyboard_visible = True
        with QtCore.QSignalBlocker(self.keyboard_widget_selector):
            self.keyboard_widget_selector.setChecked(True)

    def hideKeyboard(self):
        if self._keyboard_visualizer_widget:
            self.keyboard_widget.unhook()
            self.views.remove_widget(self._keyboard_visualizer_widget)
            self.keyboard_widget = None
            key = (gremlin.shared_state.keyboard_tab_guid, VisualizationType.Keyboard)
            if key in self._widget_storage:
                del self._widget_storage[key]
            self._keyboard_visualizer_widget = None
            self._keyboard_visible = False
            
        with QtCore.QSignalBlocker(self.keyboard_widget_selector):
            self.keyboard_widget_selector.setChecked(False)

        self._update_view()


    def populateState(self, layout):
        if self._state_visualizer_widget:
            gremlin.util.clear_layout(layout)
            self._state_buttons.clear()
            sd = gremlin.ui.state_device.StateData()
            css = gremlin.ui.ui_common.Color.cssStateButton()
            i = 0
            for key, data in sd.getStates().items():
                btn = gremlin.ui.ui_common.QDataPushButton(key, data)
                btn.setStyleSheet(css)
                btn.setDisabled(True)
                btn.setDown(data.value)
                layout.addWidget(btn, int(i / 10), int(i % 10))
                data.changed.connect(self._state_changed)
                self._state_buttons[data.key] = btn
                i+=1
            layout.setColumnStretch(10,1)

    def showState(self):
        ''' state device '''
        if not self._state_visualizer_widget:
            self._state_visualizer_widget = QtWidgets.QGroupBox("States")
            button_layout = QtWidgets.QGridLayout()
            self.populateState(button_layout)
            self._state_visualizer_widget.setLayout(button_layout)
                
            self.views.add_widget(self._state_visualizer_widget)

    def hideState(self):
        ''' hides the state device '''
        if self._state_visualizer_widget:
            self.views.remove_widget(self._state_visualizer_widget)
        self._update_view()

    def refreshState(self):
        if self._state_visualizer_widget:
            layout = self._state_visualizer_widget.layout()
            self.populateState(layout)
        

    @QtCore.Slot()
    def _state_changed(self):
        data = self.sender()
        key = data.key
        if key in self._state_buttons:
            self._state_buttons[key].setDown(data.value)

    @QtCore.Slot()
    def _state_crud(self):
        # called on state create/add/remove/edit
        self.refreshState()

    
    @QtCore.Slot(bool)
    def _toggle_keyboard_widget(self, checked):
        if checked:
            self.showKeyboard()
        else:
            self.hideKeyboard()

        config = VisualizationConfig()
        config.setValue(gremlin.shared_state.keyboard_tab_guid, VisualizationType.Keyboard, checked)

    @QtCore.Slot(bool)
    def _toggle_state_widget(self, checked):
        if checked:
            self.showState()
        else:
            self.hideState()

        config = VisualizationConfig()
        config.setValue(gremlin.shared_state.state_tab_guid, VisualizationType.State, checked)
           

    def _update_view(self):
        ''' rebuids the view '''
        self.view_container_layout.removeWidget(self.views)
        self.views = InputViewerArea()
        self.view_container_layout.addWidget(self.views)

        for widget in self._widget_storage.values():
            self.views.add_widget(widget)
        
class InputViewerArea(QtWidgets.QScrollArea):

    """Holds individual input visualization widgets."""

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.widgets = []
        
        self.setWidgetResizable(True)
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()
        self.scroll_layout.addStretch()
        self.scroll_widget.setLayout(self.scroll_layout)

        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        self.setWidget(self.scroll_widget)

    def add_widget(self, widget):
        """Adds the specified widget to the visualization area.

        :param widget the widget to add
        """
        self.widgets.append(widget)
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, widget)
        widget.show()

        width = 0
        height = 0
        for widget in self.widgets:
            hint = widget.minimumSizeHint()
            height = max(height, hint.height())
            width = max(width, hint.width())
        self.setMinimumWidth(width+40)
        # self.setMinimumSize(QtCore.QSize(width+40, height))

    def remove_widget(self, widget):
        """Removes a widget from the visualization area.

        :param widget the widget to remove
        """
        self.scroll_layout.removeWidget(widget)
        if widget is self.widgets:
            index = self.widgets.index(widget)
            del self.widgets[index]
            del widget

    def clear(self):
        ''' clears all widgets '''

        for widget in self.widgets:
            self.scroll_layout.removeWidget(widget)    
            widget.unhook()
            del self.widgets[self.widgets.index(widget)]
            del widget
        self.widgets.clear()


_visualization_config = VisualizationConfig()