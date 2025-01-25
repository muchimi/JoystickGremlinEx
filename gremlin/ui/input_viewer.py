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

import copy
import enum
import time

from PySide6 import QtCore, QtGui, QtWidgets
import lxml.etree
import dinput

import gremlin
import gremlin.config
import gremlin.shared_state
from . import ui_common
from gremlin.input_types import InputType
from gremlin.types import VisualizationType
import os
from lxml import etree
import gremlin.singleton_decorator
import logging
import gremlin.ui.ui_common

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
                node.set("id",str(id))
                node.set("value", str(value))
                root.append(node)

        try:
            tree = etree.ElementTree(root)
            tree.write(fname, pretty_print=True,xml_declaration=True,encoding="utf-8")
        except:
            pass


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
        fname = os.path.join(gremlin.util.userprofile_path(), "inputViewer.xml")
        return fname
    
    
class VisualizationSelector(QtWidgets.QWidget):

    """Presents a list of devices and visualization widgets."""

    # Event emitted when the visualization configuration changes
    changed = QtCore.Signal(
        dinput.DeviceSummary,
        VisualizationType,
        bool
    )

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

        

        dev : dinput.DeviceSummary
        for dev in devices:
            
            box = QtWidgets.QGroupBox(dev.name)

            at_cb = gremlin.ui.ui_common.QDataCheckbox("Axes - Temporal", data = (VisualizationType.AxisTemporal, dev))
            callback = self._create_callback(dev, VisualizationType.AxisTemporal, at_cb)
            at_cb.clicked.connect(callback)
            self._selector_callbacks[at_cb] = callback

            ac_cb = gremlin.ui.ui_common.QDataCheckbox("Axes - Current",  data = (VisualizationType.AxisCurrent, dev))
            callback = self._create_callback(dev, VisualizationType.AxisCurrent, ac_cb)
            ac_cb.clicked.connect(callback)
            self._selector_callbacks[ac_cb] = callback

            bh_cb = gremlin.ui.ui_common.QDataCheckbox("Buttons + Hats",  data = (VisualizationType.ButtonHat, dev))
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
        
        
        for widget in self._selector_widgets:
            with QtCore.QSignalBlocker(widget):
                widget.setChecked(False)
            visualisation, dev = widget.data
            self._create_callback(dev, visualisation, widget)()
            
        

    @QtCore.Slot()
    def _select_real(self):
        ''' selects all hardware inputs '''
        for widget in self._selector_widgets:
            visualization, dev = widget.data
            if visualization != VisualizationType.AxisTemporal and not dev.is_virtual:
                with QtCore.QSignalBlocker(widget):
                    widget.setChecked(True)
                visualisation, dev = widget.data
            else:
                widget.setChecked(False)
            self._create_callback(dev, visualisation, widget)()


                    
        
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
        self.changed.emit(
                device,
                vis_type,
                checked
            )

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

        self.devices = gremlin.joystick_handling.joystick_devices()
        self.main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.main_layout)




        
        self.views = InputViewerArea()

        # configure the scroll area for the selectors
        self.scroll_selector_layout = QtWidgets.QHBoxLayout()
        self.scroll_selector_area = QtWidgets.QScrollArea()
        self.scroll_selector_widget = QtWidgets.QWidget()

        # Configure the widget holding the layout with all the buttons
        self.scroll_selector_widget.setLayout(self.scroll_selector_layout)
        self.scroll_selector_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding
        )
        self.scroll_selector_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.scroll_selector_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        
        self.scroll_selector_area.setMinimumWidth(200)
        self.scroll_selector_area.setWidgetResizable(True)
        self.scroll_selector_area.setWidget(self.scroll_selector_widget)


        


        self.vis_selector = VisualizationSelector(self._add_remove_visualization_widget)
        self.vis_selector.changed.connect(self._add_remove_visualization_widget)

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

        content_widget, _ = gremlin.ui.ui_common.getHContainer((self.scroll_selector_area, self.views))
        # Add the scroll area to the main layout
        self.main_layout.addWidget(content_widget)
        self.closed.connect(self._closed)

    @QtCore.Slot()
    def _closed(self):
        ''' save the config on close'''
        config = VisualizationConfig()
        config.save()

    def _add_remove_visualization_widget(self, device, vis_type, is_active):
        """Adds or removes a visualization widget.

        :param device the device which is being updated
        :param vis_type the visualization type being updated
        :param is_active if True the visualization is added, if False it is
            removed
        """
        key = device, vis_type
        
        if is_active:
            widget = ui_common.JoystickDeviceWidget(device, vis_type)
            self.views.add_widget(widget)
            self._widget_storage[key] = widget
        elif key in self._widget_storage:
            self.views.remove_widget(self._widget_storage[key])
            del self._widget_storage[key]

        
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
        widget.hide()
        del self.widgets[self.widgets.index(widget)]
        del widget

    def clear(self):
        ''' clears all widgets '''
        for widget in self.widget:
            self.scroll_layout.removeWidget(widget)
            widget.hide()
            del self.widgets[self.widgets.index(widget)]
            del widget


_visualization_config = VisualizationConfig()