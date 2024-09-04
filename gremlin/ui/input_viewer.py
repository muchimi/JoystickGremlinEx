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
import dinput

import gremlin
import gremlin.shared_state
from . import ui_common
from gremlin.input_types import InputType
from gremlin.types import VisualizationType



class VisualizationSelector(QtWidgets.QWidget):

    """Presents a list of possibly device and visualization widgets."""

    # Event emitted when the visualization configuration changes
    changed = QtCore.Signal(
        dinput.DeviceSummary,
        VisualizationType,
        bool
    )

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        devices = gremlin.joystick_handling.joystick_devices()
        
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

        self.main_layout = QtWidgets.QVBoxLayout(self)
        for dev in devices: # sorted(devices, key=lambda x: (x.name, x.vjoy_id)):
            # if dev.is_virtual:
            #     #box = QtWidgets.QGroupBox(f"{dev.name} #{dev.vjoy_id:d}")
            # else:
            
            box = QtWidgets.QGroupBox(dev.name)

            at_cb = QtWidgets.QCheckBox("Axes - Temporal")
            at_cb.clicked.connect(
                self._create_callback(dev, VisualizationType.AxisTemporal, at_cb)
            )

            ac_cb = QtWidgets.QCheckBox("Axes - Current")
            ac_cb.clicked.connect(
                self._create_callback(dev, VisualizationType.AxisCurrent, ac_cb)
            )
            bh_cb = QtWidgets.QCheckBox("Buttons + Hats")
            bh_cb.clicked.connect(
                self._create_callback(dev, VisualizationType.ButtonHat, bh_cb)
            )

            layout = QtWidgets.QVBoxLayout()
            layout.addWidget(at_cb)
            layout.addWidget(ac_cb)
            layout.addWidget(bh_cb)

            box.setLayout(layout)

            self.main_layout.addWidget(box)

    def _create_callback(self, device, vis_type, cb):
        """Creates the callback to trigger visualization updates.

        :param device the device being updated
        :param vis_type visualization type being updated
        """
        return lambda state: self.changed.emit(
                device,
                vis_type,
                cb.isChecked() #state == QtCore.Qt.Checked
            )


class InputViewerUi(ui_common.BaseDialogUi):

    """Main UI dialog for the input viewer."""

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._widget_storage = {}
        self.setMinimumHeight(800)

        self.devices = gremlin.joystick_handling.joystick_devices()
        self.main_layout = QtWidgets.QHBoxLayout()
        self.setLayout(self.main_layout)

        self.vis_selector = VisualizationSelector()
        self.vis_selector.changed.connect(self._add_remove_visualization_widget)

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

        
        self.scroll_selector_area.setMinimumWidth(300)
        self.scroll_selector_area.setWidgetResizable(True)
        self.scroll_selector_area.setWidget(self.scroll_selector_widget)

        self.scroll_selector_layout.addWidget(self.vis_selector)

        # Add the scroll area to the main layout
        self.main_layout.addWidget(self.scroll_selector_area)
        self.main_layout.addWidget(self.views)


    def _add_remove_visualization_widget(self, device, vis_type, is_active):
        """Adds or removes a visualization widget.

        :param device the device which is being updated
        :param vis_type the visualization type being updated
        :param is_active if True the visualization is added, if False it is
            removed
        """
        key = device, vis_type
        
        widget = ui_common.JoystickDeviceWidget(device, vis_type)
        if is_active:
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

