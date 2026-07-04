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

import threading
from PySide6 import QtCore, QtWidgets

import dinput
import traceback
from shiboken6 import Shiboken
import gremlin
import gremlin.config
import gremlin.gamepad_handling
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.ui.virtual_keyboard
import gremlin.util
from . import ui_common
from gremlin.types import VisualizationType
import os
from lxml import etree
import gremlin.singleton_decorator
import logging
import gremlin.ui.ui_common
import gremlin.ui.state_device
from psygnal import Signal
from gremlin.types import DeviceType

syslog = logging.getLogger("system")


@gremlin.singleton_decorator.SingletonDecorator
class VisualizationConfig:
    """stores data"""

    def __init__(self):
        self._config = {}  # map of device guid, input_type, input_id - selected flag
        self.reload()
        self._lock = threading.Lock()

    def register(self, device_id, input_type: VisualizationType):
        """registers a configuration entry

        :param device_id: id (str) or guid - device id
        :param input_type: visualization type
        :value value:
        """
        if not isinstance(device_id, str):
            device_id = str(device_id)
        if device_id not in self._config:
            self._config[device_id] = {}
        if input_type not in self._config[device_id]:
            self._config[device_id][input_type] = None

    def save(self):
        gremlin.util.InvokeUiMethod(self._save_ui)  # ensure save on UI thread

    def _save_ui(self):
        with self._lock:
            try:
                """ saves to the config file """
                fname = self.get_config()

                syslog = logging.getLogger("system")
                verbose = gremlin.config.Configuration().verbose_mode_inputs
                if verbose:
                    syslog.info("INPUT VIEWER: save configuration")

                root = etree.Element("config")
                for device_id in self._config:
                    for id in self._config[device_id]:
                        value = self._config[device_id][id]
                        node = etree.Element("data")
                        node.set("device-guid", device_id)
                        node.set("id", gremlin.util.safe_format(id, int))  # visualization type
                        node.set("value", gremlin.util.safe_format(value, bool))
                        root.append(node)
                        if gremlin.joystick_handling.joystick_initialized():
                            device_name = gremlin.joystick_handling.device_name_from_guid(device_id)
                        else:
                            device_name = ""
                            input_type = VisualizationType(id).name
                            node_comment = etree.Comment(f"{device_name} {device_id} type: {input_type}")
                            node.addprevious(node_comment)

                try:
                    tree = etree.ElementTree(root)
                    tree.write(fname, pretty_print=True, xml_declaration=True, encoding="utf-8")
                except Exception as err:
                    syslog.error("VIZ CONFIG SAVE (write error):")
                    syslog.error(f"{err}\n{traceback.format_exc()}")
            except Exception as err:
                syslog.error("VIZ CONFIG SAVE")
                syslog.error(f"{err}\n{traceback.format_exc()}")

    def clear(self):
        """clears config selection"""
        self._config.clear()

    def setValue(self, device_id, input_id, value):
        """saves a viewer config item"""
        if not isinstance(device_id, str):
            device_id = str(device_id)
        self.register(device_id, input_id)
        self._config[device_id][input_id] = value
        self.save()

    def getValue(self, device_id, input_id, default_value=None):
        """gets a value"""
        if not isinstance(device_id, str):
            device_id = str(device_id)
        self.register(device_id, input_id)
        value = self._config[device_id][input_id]
        if value is None:
            value = default_value
        return value

    def getConfig(self):
        return self._config

    def reload(self):
        fname = self.get_config()
        load_successful = False
        if os.path.isfile(fname):
            try:
                parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
                t = etree.parse(fname, parser=parser)
                for node in t.findall(".//data"):
                    device_id = node.get("device-guid")
                    id = VisualizationType(gremlin.util.safe_read(node, "id", int, 0))
                    value = gremlin.util.safe_read(node, "value", bool, False)
                    self.register(device_id, id)
                    self._config[device_id][id] = value
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
    changed = Signal(dinput.DeviceSummary, VisualizationType, bool)
    clear = Signal()  # delete all

    def __init__(self, change_callback, viewer, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        devices = gremlin.joystick_handling.joystick_devices() + gremlin.joystick_handling.virtual_devices()

        self.viewer = viewer
        self._selector_widgets = []
        self._selector_callbacks = {} # maps (device_id, VisualizationType) to callback
        self._change_callback = change_callback
        self._callbacks = []  # list of registered callbacks in the selector
        self._view_map = {}  # list of visualizations by key

        # get the order of the devices as set by the user for the physical devices
        tab_map = gremlin.shared_state.ui._get_tab_map()
        tab_ids = list(tab_map.keys())
        d_list = []
        max_index = len(devices)
        for dev in devices:
            if dev.disabled:
                continue
            if dev.device_id in tab_ids:
                index = tab_ids.index(dev.device_id)
                d_list.append((index, dev))
            else:
                # add to the end (vjoy devices)
                d_list.append((max_index, dev))

        d_list.sort(key=lambda x: (x[0], x[1].virtual_id, x[1].name))
        self._devices = [dev for _, dev in d_list]

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

    def getCallabck(self, key):
        """ gets callback associated with the key"""
        return self._selector_callbacks.get(key, None)



    def getViewMap(self):
        return self._view_map

    def widgetAt(self, index):
        """gets the widget at the specified index"""
        try:
            return self._selector_widgets[index]
        except IndexError:
            return None

    def updateSelector(self):
        gremlin.util.InvokeUiMethod(self._update_selector_ui)  # ensure on UI thread

    def _update_selector_ui(self):
        """updates the selector with input options"""
        if not Shiboken.isValid(self):
            return

        combine_button_hats = gremlin.config.Configuration().input_viewer_combine_buttonhats
        config = VisualizationConfig()

        for widget in gremlin.util.get_layout_widgets(self.main_layout):
            self.main_layout.removeWidget(widget)
            gremlin.util.delete_widget(widget)

        # gremlin.util.clear_layout(self.main_layout)
        change_callback = self._change_callback

        bh_cb = None
        at_cb = None
        ac_cb = None
        bo_cb = None
        ho_cb = None

        index = 0

        device: dinput.DeviceSummary
        for device in self._devices:
            if device.disabled:
                continue  # skip disabled devices
            device_id = device.device_id

            box = QtWidgets.QGroupBox(device.name)
            layout = QtWidgets.QVBoxLayout()

            if device.axis_count:
                key = (device_id, VisualizationType.AxisTemporal)
                at_cb = gremlin.ui.ui_common.QDataCheckbox("Axes - Temporal", data=key)
                at_cb.setIgnoreKeyboard(True)
                callback = self._create_callback(device, VisualizationType.AxisTemporal, at_cb)
                at_cb.clicked.connect(callback)
                self._selector_callbacks[key] = callback
                layout.addWidget(at_cb)
                self._selector_widgets.append(at_cb)
                self._view_map[(device_id, VisualizationType.AxisTemporal)] = index
                index += 1

                key = (device_id, VisualizationType.AxisCurrent)
                ac_cb = gremlin.ui.ui_common.QDataCheckbox("Axes - Current", data=key )
                ac_cb.setIgnoreKeyboard(True)
                callback = self._create_callback(device, VisualizationType.AxisCurrent, ac_cb)
                ac_cb.clicked.connect(callback)
                self._selector_callbacks[key] = callback
                layout.addWidget(ac_cb)
                self._selector_widgets.append(ac_cb)
                self._view_map[(device_id, VisualizationType.AxisCurrent)] = index
                index += 1

            has_buttons = device.button_count > 0
            has_hats = device.hat_count > 0

            if combine_button_hats:
                # combination button/hat
                stub = ""
                if has_buttons:
                    stub = "Buttons"
                if has_hats:
                    if stub:
                        stub += " + "
                    stub += "Hats"

                if stub:
                    # has button or hats
                    key = (device_id, VisualizationType.ButtonHat)
                    bh_cb = gremlin.ui.ui_common.QDataCheckbox(stub, data=key)
                    bh_cb.setIgnoreKeyboard(True)
                    callback = self._create_callback(device, VisualizationType.ButtonHat, bh_cb)
                    bh_cb.clicked.connect(callback)
                    self._selector_callbacks[key] = callback
                    layout.addWidget(bh_cb)
                    self._selector_widgets.append(bh_cb)
                    self._view_map[(device_id, VisualizationType.ButtonHat)] = index
                    index += 1
            else:
                # buttons only
                if has_buttons:
                    key = (device_id, VisualizationType.Button)
                    bo_cb = gremlin.ui.ui_common.QDataCheckbox("Buttons", data=key)
                    bo_cb.setIgnoreKeyboard(True)
                    callback = self._create_callback(device, VisualizationType.Button, bo_cb)
                    bo_cb.clicked.connect(callback)
                    self._selector_callbacks[key] = callback
                    layout.addWidget(bo_cb)
                    self._selector_widgets.append(bo_cb)
                    self._view_map[(device_id, VisualizationType.Button)] = index
                    index += 1

                # hats only
                if has_hats:
                    key = (device_id, VisualizationType.Hat)
                    ho_cb = gremlin.ui.ui_common.QDataCheckbox("Hats", data=key)
                    ho_cb.setIgnoreKeyboard(True)
                    callback = self._create_callback(device, VisualizationType.Hat, ho_cb)
                    ho_cb.clicked.connect(callback)
                    self._selector_callbacks[key] = callback
                    layout.addWidget(ho_cb)
                    self._selector_widgets.append(ho_cb)
                    self._view_map[(device_id, VisualizationType.Hat)] = index
                    index += 1

            box.setLayout(layout)

            self.main_layout.addWidget(box)

            # update based on settings
            device_id = device.device_guid
            checked = config.getValue(device_id, VisualizationType.AxisTemporal, False)
            at_cb.setChecked(checked)
            if checked:
                change_callback(device, VisualizationType.AxisTemporal, True)

            checked = config.getValue(device_id, VisualizationType.AxisCurrent, False)
            ac_cb.setChecked(checked)
            if checked:
                change_callback(device, VisualizationType.AxisCurrent, True)

            if combine_button_hats:
                # combined button/hat
                checked = config.getValue(device_id, VisualizationType.ButtonHat, False)
                if bh_cb:
                    bh_cb.setChecked(checked)
                if checked:
                    change_callback(device, VisualizationType.ButtonHat, True)
            else:
                # button only
                if has_buttons:
                    checked = config.getValue(device_id, VisualizationType.Button, False)
                    if bo_cb:
                        bo_cb.setChecked(checked)
                    if checked:
                        change_callback(device, VisualizationType.ButtonHat, True)

                # hat only
                if has_hats:
                    checked = config.getValue(device_id, VisualizationType.Hat, False)
                    if ho_cb:
                        ho_cb.setChecked(checked)
                    if checked:
                        change_callback(device, VisualizationType.Hat, True)

        # fire all the callbacks to update
        for device, vis in self._callbacks:
            change_callback(device, vis, None)

    def closeWidget(self, key):
        """closes the widget associated with the given key"""
        if key in self._view_map:
            index = self._view_map[key]
            widget = self._selector_widgets[index]
            widget.setChecked(False)

    @QtCore.Slot()
    def _clear_selection(self):
        """clears the selection of all widgets"""
        self.clear.emit()
        for widget in self._selector_widgets:
            if not Shiboken.isValid(widget):
                continue
            with QtCore.QSignalBlocker(widget):
                widget.setChecked(False)

    @QtCore.Slot()
    def _select_real(self):
        """selects all hardware inputs"""
        for widget in self._selector_widgets:
            if not Shiboken.isValid(widget):
                continue
            visualization, dev = widget.data
            if visualization != VisualizationType.AxisTemporal and not dev.is_virtual:
                with QtCore.QSignalBlocker(widget):
                    widget.setChecked(True)
            else:
                widget.setChecked(False)
            self._create_callback(dev, visualization, widget)()

    @QtCore.Slot()
    def _select_vjoy(self):
        widget = self.sender()
        if not Shiboken.isValid(widget):
            return
        id = widget.data

        widgets = [w for w in self._selector_widgets]
        for widget in widgets:
            if Shiboken.isValid(widget):
                visualization, dev = widget.data
                if visualization != VisualizationType.AxisTemporal and dev.is_virtual and dev.vjoy_id == id:
                    with QtCore.QSignalBlocker(widget):
                        widget.setChecked(True)
                    self._create_callback(dev, visualization, widget)()
            else:
                self._selector_widgets.remove(widget)

    @QtCore.Slot()
    def _select_all(self):
        """selects all widgets"""

        widgets = [w for w in self._selector_widgets]
        for widget in widgets:
            if Shiboken.isValid(widget):
                with QtCore.QSignalBlocker(widget):
                    widget.setChecked(True)
                visualisation, dev = widget.data
                self._create_callback(dev, visualisation, widget)()
            else:
                self._selector_widgets.remove(widget)

    def _create_callback(self, device, vis_type, cb):
        """Creates the callback to trigger visualization updates.

        :param device the device being updated
        :param vis_type visualization type being updated
        """
        key = (device, vis_type)
        if key not in self._callbacks:
            self._callbacks.append(key)
        return lambda: self._callback(device, vis_type, cb)

    def _callback(self, device, vis_type, cb):

        checked = cb.isChecked()
        config = VisualizationConfig()
        config.setValue(device.device_id, vis_type, checked)
        self.changed.emit(device, vis_type, checked)


class InputViewerWidget(QtWidgets.QWidget):
    """Widget for the input viewer."""

    closed = QtCore.Signal(object)  # request close (sends the key)

    def __init__(self, key, widget=None, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)

        self._stacked_widget = gremlin.ui.ui_common.ResizingStackedWidget(zero_hide=True)
        # self._stacked_widget.setStyleSheet("background: red; border: 1px solid orange;")
        self._stacked_widget.heightChanged.connect(self._on_height_changed)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(self._stacked_widget)
        self._key = key
        self._widget = None

        # self._stacked_widget.addWidget(QtWidgets.QLabel(str(key)))
        blank_widget = QtWidgets.QWidget()
        blank_widget.setFixedHeight(0)
        self._stacked_widget.addWidget(blank_widget)  # blank widget

        if widget:
            self.setWidget(widget)

    def _on_height_changed(self, height):
        """called when the stacked widget changes size"""
        self.setFixedHeight(height)

    @property
    def key(self):
        return self._key

    @property
    def widget(self):
        """returns the current widget"""
        return self._widget

    def setWidget(self, widget):
        """sets the widget to display"""

        if widget is None:
            while self._stacked_widget.count() > 1:
                widget = self._stacked_widget.widget(1)
                self._stacked_widget.removeWidget(widget)
                gremlin.util.delete_widget(widget)
            self._stacked_widget.setCurrentIndex(0)  # blank
        else:
            close_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(size=20, tooltip="Close")
            close_widget.clicked.connect(lambda: self.closed.emit(self._key))
            widget_container = gremlin.ui.ui_common.getHContainer([(widget,100),"||",close_widget], widget_only=True, alignment=QtCore.Qt.AlignTop)
            container = gremlin.ui.ui_common.getVContainer([gremlin.ui.ui_common.QHorizontalLine(), widget_container], widget_only=True)
            self._stacked_widget.addWidget(container)
            self._stacked_widget.setCurrentWidget(container)
            self._stacked_widget.setCurrentIndex(self._stacked_widget.count() - 1)
            # ontainer.setStyleSheet("background: green; border: 1px solid yellow;")
            widget.show()
        self._widget = widget

    def hideWidget(self):
        """hides the widget"""
        self._stacked_widget.setCurrentIndex(0)  # blank

    def clearWidget(self):
        """clears the widget"""
        self.setWidget(None)


class InputViewerDialog(ui_common.BaseDialogUi):
    """Main UI dialog for the input viewer."""

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(self.__class__.__name__, parent)

        self.setStyleSheet("QGroupBox { border: 0px }")  # turn group box borders off

        self.vis_selector = VisualizationSelector(self._add_remove_visualization_widget, viewer=self)
        self.vis_selector.changed.connect(self._add_remove_visualization_widget)
        self.vis_selector.clear.connect(self._clear)

        self._widget_map = {}  # holds all the view items

        self._lock = threading.Lock()
        self.setMinimumHeight(800)

        v_config = VisualizationConfig()
        self._keyboard_visible = False
        self._state_visible = False

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
        self._state_filter_widget = None
        self._state_buttons = {}  # map of key widget
        self._state_category_filter = None
        self.keyboard_widget = None  # keyboard widget

        self.view_container_widget = QtWidgets.QWidget()
        self.view_container_layout = QtWidgets.QVBoxLayout(self.view_container_widget)
        self.views = InputViewerArea()
        self.view_container_layout.addWidget(self.views)

        # configure the scroll area for the selectors
        self.scroll_selector_layout = QtWidgets.QVBoxLayout()
        self.scroll_selector_area = QtWidgets.QScrollArea()
        self.scroll_selector_widget = QtWidgets.QWidget()

        # Configure the widget holding the layout with all the buttons
        self.scroll_selector_widget.setLayout(self.scroll_selector_layout)
        self.scroll_selector_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.scroll_selector_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.scroll_selector_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        self.scroll_selector_area.setMinimumWidth(200)
        self.scroll_selector_area.setWidgetResizable(True)
        self.scroll_selector_area.setWidget(self.scroll_selector_widget)

        checked = v_config.getValue(gremlin.shared_state.keyboard_tab_guid, VisualizationType.Keyboard, False)
        self.keyboard_widget_selector = gremlin.ui.ui_common.QDataCheckbox(
            "Keyboard/Mouse", value=checked, callback=self._toggle_keyboard_widget, tooltip="Toggle keyboard/mouse visualizer"
        )
        self.keyboard_widget_selector.setIgnoreKeyboard(True)

        show_keyboard = checked

        checked = v_config.getValue(gremlin.shared_state.state_tab_guid, VisualizationType.State, False)
        self.state_widget_selector = gremlin.ui.ui_common.QDataCheckbox(
            "State", value=checked, callback=self._toggle_state_widget, tooltip="Toggle state visualizer"
        )
        self.state_widget_selector.setIgnoreKeyboard(True)

        show_state = checked

        # option to combine hat/buttons
        config = gremlin.config.Configuration()
        self.combine_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Combine Button + Hats",
            callback=self._toggle_combine_button_hat,
            value=config.input_viewer_combine_buttonhats,
            tooltip="Uncheck to list buttons and hats as separate visuals",
        )
        self.combine_widget.setIgnoreKeyboard(True)

        options_widget = QtWidgets.QGroupBox("Options")
        options_layout = QtWidgets.QVBoxLayout(options_widget)
        options_layout.addWidget(self.combine_widget)
        options_layout.addStretch()

        system_selector_widget = QtWidgets.QGroupBox("System Inputs")
        system_selector_layout = QtWidgets.QVBoxLayout(system_selector_widget)

        system_selector_layout.addWidget(self.keyboard_widget_selector)
        system_selector_layout.addWidget(self.state_widget_selector)
        system_selector_layout.addStretch()

        self.scroll_selector_layout.addWidget(options_widget)
        self.scroll_selector_layout.addWidget(system_selector_widget)
        self.scroll_selector_layout.addWidget(self.vis_selector)

        clear_widget = gremlin.ui.ui_common.QDataPushButton("Clear")
        clear_widget.setToolTip("Clears the selection")
        clear_widget.clicked.connect(self._clear_all)

        select_all_widget = gremlin.ui.ui_common.QDataPushButton("Select All")
        select_all_widget.setToolTip("Selects all inputs")
        select_all_widget.clicked.connect(self._select_all)

        select_real_widget = gremlin.ui.ui_common.QDataPushButton("Select Hardware")
        select_real_widget.setToolTip("Selects all hardware inputs")
        select_real_widget.clicked.connect(self.vis_selector._select_real)

        widgets = [clear_widget, select_real_widget, select_all_widget]

        vjoy_ids = [dev.vjoy_id for dev in gremlin.joystick_handling.virtual_devices()]
        vjoy_ids = vjoy_ids[:3]
        for i in vjoy_ids:
            widget = gremlin.ui.ui_common.QDataPushButton(f"Select VJOY #{i}", data=i)
            widget.setToolTip(f"Select VJOY #{i} axis and buttons")
            widget.clicked.connect(self.vis_selector._select_vjoy)
            widgets.append(widget)

        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        options_widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        options_widget.setMaximumHeight(32)

        self.main_layout.addWidget(options_widget)
        self.main_layout.addWidget(self._splitter)

        self._left_panel_widget = QtWidgets.QWidget()
        self._left_panel_layout = QtWidgets.QVBoxLayout(self._left_panel_widget)
        self._left_panel_widget.setMinimumWidth(150)
        self._left_panel_widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Expanding)

        self._right_panel_widget = QtWidgets.QWidget()
        self._right_panel_layout = QtWidgets.QVBoxLayout(self._right_panel_widget)

        self._splitter.addWidget(self._left_panel_widget)
        self._splitter.addWidget(self._right_panel_widget)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 3)

        self._left_panel_layout.addWidget(self.scroll_selector_area)
        self._right_panel_layout.addWidget(self.view_container_widget)

        msg = """
Some visuals may capture the scrollwheel.<br>
Move the mouse to the scrollbar or off a visual to scroll the display if experiencing difficulty scrolling using the wheel.<br>
<br>
States can be toggled by clicking on the state button.  Expression states will update.

"""

        info_box = gremlin.ui.ui_common.QInfoBox(msg, wrap=True, hide_key="input_viewer")
        self.view_container_layout.addWidget(info_box)

        self.closed.connect(self._closed)
        self.installEventFilter(self)

        self._event_data = {}

        self.load_viewer_widgets()

        if show_state:
            self.showState()

        if show_keyboard:
            self.showKeyboard()

        # update the visualizer
        self.vis_selector.updateSelector()

        el = gremlin.event_handler.EventListener()
        el.profile_loaded.connect(self.refresh)
        el.profile_unhook.connect(self.reload)

    def closeSystemWidget(self, key):
        """closes the widget associated with the given key"""

        device_guid, visualization_type = key
        match visualization_type:
            case VisualizationType.State:
                self.state_widget_selector.setChecked(False)
            case VisualizationType.Keyboard:
                self.keyboard_widget_selector.setChecked(False)
            case _:
                self.vis_selector.closeWidget(key)
                callback = self.vis_selector.getCallabck(key)
                callback()


    def load_viewer_widgets(self):
        """loads the view widgets for all device inputs"""

        # build all possible visualizations for the devices - this is used to determine if a visualization is available for a device
        self.views.clear()
        self._widget_map = {}

        # special devices
        key = (gremlin.shared_state.state_tab_guid, VisualizationType.State)
        widget = InputViewerWidget(key)
        widget.closed.connect(lambda key: self.closeSystemWidget(key))
        self._widget_map[key] = widget

        key = (gremlin.shared_state.keyboard_tab_guid, VisualizationType.Keyboard)
        widget = InputViewerWidget(key)
        widget.closed.connect(lambda key: self.closeSystemWidget(key))
        self._widget_map[key] = widget

        devices = gremlin.joystick_handling.joystick_devices() + gremlin.joystick_handling.virtual_devices()
        verbose = False

        for device in devices:
            if device.disabled:
                continue
            if verbose:
                syslog.info(
                    f"INPUT VIEWER: load_viewer_widgets - device {device.name} ({device.device_id}) axes: {device.axis_count} buttons: {device.button_count} hats: {device.hat_count}"
                )
            if device.axis_count:
                self._widget_map[(device.device_id, VisualizationType.AxisTemporal)] = None
                if verbose:
                    syslog.info("\ttemporal axis")
                self._widget_map[(device.device_id, VisualizationType.AxisCurrent)] = None
                if verbose:
                    syslog.info("\tcurrent axis")
            if device.button_count or device.hat_count:
                self._widget_map[(device.device_id, VisualizationType.ButtonHat)] = None
                if verbose:
                    syslog.info("\tbutton hat")
            if device.button_count:
                self._widget_map[(device.device_id, VisualizationType.Button)] = None
                if verbose:
                    syslog.info("\tbutton")
            if device.hat_count:
                self._widget_map[(device.device_id, VisualizationType.Hat)] = None
                if verbose:
                    syslog.info("\that")

        for key in self._widget_map:
            widget = InputViewerWidget(key)
            widget.closed.connect(lambda key: self.closeSystemWidget(key))
            self.views.add_widget(widget)
            self._widget_map[key] = widget

        self.devices = devices



    def _clear_all(self):
        """clears all items"""
        self.vis_selector._clear_selection()
        config = VisualizationConfig()
        config.clear()
        config.setValue(gremlin.shared_state.state_tab_guid, VisualizationType.State, False)
        config.setValue(gremlin.shared_state.keyboard_tab_guid, VisualizationType.Keyboard, False)
        self.load_viewer_widgets()  # reload devices

    def _select_all(self):
        # select keyboard and state
        self._keyboard_visible = True
        self._state_visible = True
        self.vis_selector._select_all()

        config = VisualizationConfig()
        config.setValue(gremlin.shared_state.state_tab_guid, VisualizationType.State, True)
        config.setValue(gremlin.shared_state.keyboard_tab_guid, VisualizationType.Keyboard, True)

    @QtCore.Slot()
    def _font_size_cb(self):
        widget = self.sender()
        size = widget.data
        config = gremlin.config.Configuration()
        config.input_viewer_button_size = size

    @QtCore.Slot(str, object)
    def _config_changed(self, key, value):
        if key == "input_viewer_button_size":
            self.refreshState()

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
        """clean up"""
        el = gremlin.event_handler.EventListener()
        el.profile_loaded.disconnect(self.refresh)
        el.profile_unhook.disconnect(self.refresh)

        self._cleanup_joystick_widgets()

        gremlin.util.clear_layout(self.main_layout)
        self._state_filter_widget = None
        self._state_visualizer_widget = None
        self._state_buttons.clear()
        self._widget_map.clear()
        self._event_data.clear()

        sd = gremlin.ui.state_device.StateData()
        sd.crud.disconnect(self._state_crud)

    def _delete_widget(self, widget):
        gremlin.util.delete_widget(widget)

    @QtCore.Slot()
    def _clear(self):
        """clears all widgets"""
        assert gremlin.util.is_ui_thread()

        self._delete_widget(self._state_filter_widget)
        self._delete_widget(self._state_visualizer_widget)

        self._state_filter_widget = None
        self._state_visualizer_widget = None
        self._state_buttons.clear()

        self._delete_widget(self.keyboard_widget)
        self.keyboard_widget = None

        self._delete_widget(self._keyboard_visualizer_widget)
        self._keyboard_visualizer_widget = None

        self._cleanup_joystick_widgets()

        self.views.clear()

    def reload(self):
        """reloads the ui"""
        gremlin.util.InvokeUiMethod(self._reload_ui)  # refresh the visuals and selectors

    def _reload_ui(self):

        if self._state_visible:
            self.showState()
        if self._keyboard_visible:
            self.showKeyboard()
        self.vis_selector.updateSelector()

    def refresh(self):
        """refreshes the visualizers"""
        gremlin.util.InvokeUiMethod(self._refresh_ui)  # refresh the visuals and selectors

    def _refresh_ui(self):
        self._clear()

        self.vis_selector.updateSelector()

    def getVisualizerIndex(self, key):
        """returns the index of the visualizer in the view container"""
        view_map = self.vis_selector.getViewMap()
        if key in view_map:
            return view_map[key]
        return None

    @QtCore.Slot(dinput.DeviceSummary, VisualizationType, bool)
    def _add_remove_visualization_widget(self, device, visualization: VisualizationType, enabled: bool | None):
        """Adds or removes a visualization widget.

        :param device: the device which is being updated (DeviceSummary)
        :param visualization: the visualization type being updated
        :param enabled: the state - if None, uses the current state
        """
        assert gremlin.util.is_ui_thread()
        if not Shiboken.isValid(self):
            return

        key = (device.device_id, visualization)
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_ui
        # verbose = True
        combined_button_hat = config.input_viewer_combine_buttonhats
        if combined_button_hat:
            if visualization in (VisualizationType.Hat, VisualizationType.Button):
                # don't show separate button/hat if in combined mode
                return
        else:
            if visualization == VisualizationType.ButtonHat:
                # don't show combined button/hat if not in combined mode
                return

        if enabled is None:
            # use the existing value
            vconfig = VisualizationConfig()
            enabled = vconfig.getValue(device.device_id, visualization)
        if enabled:
            assert self._widget_map[key] is not None, f"widget map for {key} does not exist - did you call load_viewer_widgets() first?"

            widget = ui_common.JoystickDeviceWidget(device, visualization)
            viewer_widget = self._widget_map[key]
            viewer_widget.setWidget(widget)

            widget.hook()
            if visualization in (gremlin.types.VisualizationType.AxisCurrent, gremlin.types.VisualizationType.AxisTemporal):
                widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Preferred)

            if verbose:
                syslog.info(f"Create new vis: {device.name}: {visualization.name}  key: {key}")

        else:
            if key in self._widget_map:
                # remove the widget
                viewer_widget = self._widget_map[key]
                widget = viewer_widget.widget
                if widget:
                    widget.hide()
                    viewer_widget.clearWidget()
                    widget.unhook()
                    if verbose:
                        syslog.info(f"Remove existing vis: {device.name}: {visualization.name} key: {key}")
                    gremlin.util.delete_widget(widget)

    def populateState(self):
        """execute on UI thread"""
        gremlin.util.InvokeUiMethod(self._populateState_ui)

    def _populateState_ui(self, layout):
        self._reload_states()

    def _filter_data(self, state) -> bool:
        """custom filter handler - true if the data is included in the filter, false otherwise"""
        import fnmatch

        filter = self._state_filter_widget.filter
        if not filter:
            return True  # no filter = match
        key = state.key
        if not key:
            # no key = match
            return True

        key = state.key.casefold().strip()
        if filter in key:
            return True
        return fnmatch.fnmatch(key, filter)

    def _reload_states(self):
        gremlin.util.InvokeUiMethod(self._reload_states_ui)  # ensure on UI thread

    def _reload_states_ui(self):
        """loads or reloads states"""
        layout = self._state_button_layout
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_state
        i = 0
        sd = gremlin.ui.state_device.StateData()
        items = sd.getStates().items()
        gremlin.util.clear_layout(layout)
        cm = gremlin.ui.state_device.StateCategories()
        default_category = cm.default()
        category = None

        sd = gremlin.ui.state_device.StateData()

        is_filter = config.iv_state_filter_enabled
        if is_filter:
            category = self._state_filter_widget.category
            if not category:
                category = default_category
        if items:
            for key, state in items:
                if state.value is None:
                    syslog.warning(f"viewer state: bad state data for state: {state.name} id [{state.id}] - null value - skipping display")
                    continue
                if category:
                    # apply filter
                    item_category = state.category if state.category else default_category
                    if item_category != category:
                        continue  # filter out
                if is_filter and not self._filter_data(state):
                    continue

                # btn = gremlin.ui.ui_common.QDataPushButton(key)
                # btn.data = state # store the state with the button
                btn = gremlin.ui.ui_common.StateRepeaterButton(state, callback=self._state_toggle)

                # btn.setCheckable(True)

                # btn.setChecked(state.value)
                if verbose:
                    syslog.info(f"viewer state: {key}  value: {state.value}")
                # btn.clicked.connect(self._state_toggle)

                layout.addWidget(btn)

                state.changed.connect(lambda x: self._state_changed(x))

                if state.key in self._state_buttons:
                    # remove the prior button reference
                    gremlin.util.delete_widget(self._state_buttons[state.key])

                self._state_buttons[state.key] = btn
                i += 1

        else:
            icon = gremlin.ui.ui_common.Icons.warningIcon(gremlin.ui.ui_common.Color.yellowColor())
            widget = gremlin.ui.ui_common.QWarningWidget("No states found.", icon=icon, tooltip="There are no states to display.")
            layout.addWidget(widget)

    def showKeyboard(self):
        """keyboard device"""
        assert gremlin.util.is_ui_thread()
        if self._keyboard_visible:
            return

        viewer_widget = self._widget_map.get((gremlin.shared_state.keyboard_tab_guid, VisualizationType.Keyboard))
        assert viewer_widget is not None, "keyboard view widget not in list yet - did you call load_viewer_widgets() first?"

        if not self._keyboard_visualizer_widget:
            group_widget = QtWidgets.QGroupBox("Keyboard")
            layout = QtWidgets.QVBoxLayout(self._keyboard_visualizer_widget)
            group_widget.setLayout(layout)

            self.keyboard_widget = gremlin.ui.virtual_keyboard.QKeyboardWidget(release_wheel=True)
            self.keyboard_widget.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            self.keyboard_widget.setReadonly(True)
            layout.addWidget(self.keyboard_widget)

            self.keyboard_widget.hook()
            self._keyboard_visualizer_widget = gremlin.ui.ui_common.getHContainer(group_widget, widget_only=True)
            self._keyboard_visible = True

        viewer_widget.setWidget(self._keyboard_visualizer_widget)

        with QtCore.QSignalBlocker(self.keyboard_widget_selector):
            self.keyboard_widget_selector.setChecked(True)

        self._keyboard_visible = True

    def hideKeyboard(self):
        if self._keyboard_visible:
            key = (gremlin.shared_state.keyboard_tab_guid, VisualizationType.Keyboard)
            viewer_widget = self._widget_map.get(key)
            assert viewer_widget is not None, "keyboard view widget not in list yet - did you call load_viewer_widgets() first?"
            viewer_widget.clearWidget()
            self._keyboard_visualizer_widget = None

            with QtCore.QSignalBlocker(self.keyboard_widget_selector):
                self.keyboard_widget_selector.setChecked(False)
            self._keyboard_visible = False

    def showState(self):
        """state device"""

        if self._state_visible:
            return

        key = (gremlin.shared_state.state_tab_guid, VisualizationType.State)
        viewer_widget = self._widget_map.get(key)
        assert viewer_widget is not None, "state view widget not in list yet - did you call load_viewer_widgets() first?"

        if not self._state_visualizer_widget:
            self._state_visualizer_widget = QtWidgets.QGroupBox("States")
            layout = QtWidgets.QVBoxLayout(self._state_visualizer_widget)

            self._state_filter_widget = gremlin.ui.state_device.StateFilterWidget(is_iv=True)
            self._state_filter_widget.apply.connect(self._reload_states)
            self._state_filter_widget.changed.connect(self._category_filter_changed)
            self._state_filter_widget.enabledChanged.connect(self._reload_states)

            filter_container = gremlin.ui.ui_common.getHContainer([self._state_filter_widget], widget_only=True)

            widgets = [filter_container, gremlin.ui.ui_common.QHorizontalLine()]
            container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
            layout.addWidget(container)

            config = gremlin.config.Configuration()
            config.changed.connect(self._config_changed)
            current_size = config.input_viewer_button_size
            font_sizes = (("small", 12), ("medium", 16), ("large", 20))
            widgets = []
            for label, size in font_sizes:
                rb = gremlin.ui.ui_common.QDataRadioButton(label, size)
                if current_size == size:
                    rb.setChecked(True)
                rb.clicked.connect(self._font_size_cb)
                widgets.append(rb)

            widget = gremlin.ui.ui_common.getHContainer(widgets, "Button size:", widget_only=True)
            layout.addWidget(widget)

            self._state_button_layout = gremlin.ui.ui_common.QFlowLayout()
            layout.addLayout(self._state_button_layout)

        self.populateState()
        viewer_widget.setWidget(self._state_visualizer_widget)
        self._state_visible = True

    def hideState(self):
        """hides the state device"""
        if self._state_visible:
            key = (gremlin.shared_state.state_tab_guid, VisualizationType.State)
            viewer_widget = self._widget_map.get(key)
            assert viewer_widget is not None, "state view widget not in list yet - did you call load_viewer_widgets() first?"
            viewer_widget.clearWidget()
            self._state_visualizer_widget = None
            self._state_visible = False
            with QtCore.QSignalBlocker(self.state_widget_selector):
                self.state_widget_selector.setChecked(False)

    @QtCore.Slot(object)
    def _category_filter_changed(self, category):
        """called when the state category filter is changed"""
        self._reload_states()

    def refreshState(self):
        if self._state_visualizer_widget and Shiboken.isValid(self._state_visualizer_widget):
            self.populateState()

    def _state_changed(self, state):
        # state changed received - ensure on UI thread
        gremlin.util.InvokeUiMethod(self._state_changed_ui, state)

    def _state_changed_ui(self, state):
        """called on state changes"""
        verbose = gremlin.config.Configuration().verbose_mode_state
        if verbose:
            syslog.info(f"Viewer: state {state.key} changed {state.value}")
        if state.key in self._state_buttons:
            widget = self._state_buttons[state.key]
            if Shiboken.isValid(widget):
                widget.setState(state.value)
        else:
            if verbose:
                syslog.warning(f"Viewer: state {state.key} widget not found")

    @QtCore.Slot()
    def _state_toggle(self, widget):
        state = widget.data
        key = state.key
        verbose = gremlin.config.Configuration().verbose_mode_state
        if verbose:
            syslog.info("-" * 50)
            syslog.info(f"Viewer: state {state.key} toggle")
        sc = gremlin.ui.state_device.StateData()
        sc.toggle(key)

    @QtCore.Slot()
    def _state_crud(self):
        # called on state create/add/remove/edit
        self.refreshState()

    @QtCore.Slot(bool)
    def _toggle_keyboard_widget(self, checked: bool):
        if checked:
            self.showKeyboard()
        else:
            self.hideKeyboard()

        self._keyboard_visible = checked
        config = VisualizationConfig()
        config.setValue(gremlin.shared_state.keyboard_tab_guid, VisualizationType.Keyboard, checked)

    @QtCore.Slot(bool)
    def _toggle_state_widget(self, checked: bool):
        if checked:
            self.showState()
        else:
            self.hideState()

        self._state_visible = checked
        config = VisualizationConfig()
        config.setValue(gremlin.shared_state.state_tab_guid, VisualizationType.State, checked)

        checked = config.getValue(gremlin.shared_state.state_tab_guid, VisualizationType.State)
        syslog.info(f"state set to : {checked}")

    @QtCore.Slot(bool)
    def _toggle_combine_button_hat(self, checked: bool):
        config = gremlin.config.Configuration()
        config.input_viewer_combine_buttonhats = checked

        # remove the joystick widgets
        self._cleanup_joystick_widgets()

        self.vis_selector.updateSelector()

    def _cleanup_joystick_widgets(self):
        for viewer_widget in self._widget_map.values():
            widget = viewer_widget.widget
            if hasattr(widget, "unhook"):
                widget.unhook()
            if widget and Shiboken.isValid(widget):
                widget.hide()
                viewer_widget.clearWidget()
                gremlin.util.delete_widget(widget)
                self.views.remove_widget(viewer_widget)
                gremlin.util.delete_widget(viewer_widget)

        self.load_viewer_widgets()

    @QtCore.Slot(bool)
    def _toggle_flow_layout(self, checked: bool):
        config = gremlin.config.Configuration()
        config.input_viewer_flow_layout = checked
        self.views.updateLayout()


class InputViewerArea(QtWidgets.QWidget):
    """Holds individual input visualization widgets."""

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        # layout.setContentsMargins(4, 0, 4, 0)

        self.widgets = []

        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = gremlin.ui.ui_common.QScrollLayout(self.scroll_widget)
        self.scroll_widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)

        self.scroll_area.setWidget(self.scroll_widget)
        self.installEventFilter(self)

        layout.addWidget(self.scroll_area)

    def eventFilter(self, widget, event):
        if event.type() == QtCore.QEvent.Type.Wheel:
            # trap mouse wheel events and pass them to the hovered widget because the scroll area eats these events
            hovered_widget = QtWidgets.QApplication.widgetAt(event.globalPosition().toPoint())
            if hovered_widget and hasattr(hovered_widget, "handle_wheel_event"):
                hovered_widget.handle_wheel_event(event)
                return True
        return super().eventFilter(widget, event)

    def unhook(self):
        pass

    def add_widget(self, widget, index=None):
        """Adds the specified widget to the visualization area.

        :param widget the widget to add
        """
        assert gremlin.util.is_ui_thread()
        if not Shiboken.isValid(self):
            return

        self.widgets.append(widget)
        self.scroll_layout.addWidget(widget)

    def remove_widget(self, widget):
        """Removes a widget from the visualization area.

        :param widget the widget to remove
        """
        assert gremlin.util.is_ui_thread()
        if not Shiboken.isValid(self) or not Shiboken.isValid(widget):
            return
        if hasattr(widget, "unhook"):
            widget.unhook()
        self.scroll_layout.removeWidget(widget)

        if widget in self.widgets:
            self.widgets.remove(widget)

        gremlin.util.delete_widget(widget)

    def clear(self):
        """clears all widgets"""
        if not Shiboken.isValid(self):
            return
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item:
                widget = item.widget()
                if widget:
                    gremlin.util.delete_widget(widget)


_visualization_config = VisualizationConfig()
