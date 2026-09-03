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

import json
import threading
from PySide6 import QtCore, QtWidgets
from PySide6.QtGui import QResizeEvent
from typing import Callable

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
from gremlin.util import safe_read
from gremlinEx import DeviceSummary
from . import ui_common
from gremlin.types import DeviceType, VisualizationType
import os
from lxml import etree
import gremlin.singleton_decorator
import logging
import gremlin.ui.ui_common
import gremlin.ui.state_device
from psygnal import Signal
from gremlin.types import DeviceType

syslog = logging.getLogger("system")
QWIDGETSIZE_MAX = 16777215


@gremlin.singleton_decorator.SingletonDecorator
class VisualizationConfig:
    """stores data"""

    def __init__(self):
        self._config = {}  # map of device guid, input_type, input_id - selected flag
        self._device_map = {}  # map of key to device for mapping
        self.reload()
        self._lock = threading.Lock()

        # special keys
        device_id = gremlin.shared_state.state_tab_id
        self.state_key = (device_id, VisualizationType.State)

        device_id = gremlin.shared_state.keyboard_tab_id
        self.keyboard_key = (device_id, VisualizationType.Keyboard)

    def register(self, key, device: DeviceSummary, visualization: VisualizationType):
        """registers a configuration entry

        :param key: key for the configuration entry
        :param device: device summary object
        :param visualization: visualization type
        """

        assert isinstance(key, tuple), "key must be a tuple"
        assert gremlin.util.isHashable(key), "key must be hashable"
        if key not in self._config:
            self._config[key] = {}
        if visualization not in self._config[key]:
            self._config[key][visualization] = None
        self._device_map[key] = device

    def registerKey(self, key: tuple, device: DeviceSummary):
        """registers a key to device mapping"""
        assert isinstance(key, tuple), "key must be a tuple"
        assert gremlin.util.isHashable(key), "key must be hashable"
        self._device_map[key] = device

    def getDevice(self, key: tuple):
        """returns the device for a given key"""

        assert isinstance(key, tuple), "key must be a tuple"
        assert gremlin.util.isHashable(key), "key must be hashable"

        return self._device_map.get(key, None)

    def getKey(self, device: DeviceSummary, visualization: VisualizationType):
        """returns the key for a given device and input_id"""
        assert isinstance(device, DeviceSummary), "invalid device object"
        return (device.key, visualization)

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
                for key in self._config:
                    assert isinstance(key, tuple), "key must be a tuple"
                    device = self.getDevice(key)
                    if not device:
                        continue
                    device_id = device.device_id
                    for vis in self._config[key]:
                        value = self._config[key][vis]
                        if not value:
                            continue  # don't save unselected items
                        node = etree.Element("data")
                        json_value = json.dumps(key)
                        node.set("device-guid", device_id)
                        node.set("vis", VisualizationType.toString(vis))
                        node.set("id", gremlin.util.safe_format(vis, int))  # visualization type
                        node.set("value", gremlin.util.safe_format(value, bool))
                        node.set("key", json_value)
                        node.set("description", f"{device.name}")
                        root.append(node)
                        if gremlin.joystick_handling.joystick_initialized():
                            device
                            device_name = gremlin.joystick_handling.device_name_from_guid(device_id)
                        else:
                            device_name = ""
                            input_type = VisualizationType(vis).name
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

    def setValue(self, key, device: DeviceSummary, input_id, value):
        """saves a viewer config item"""
        assert isinstance(key, tuple), "key must be a tuple"
        if key[1] in (VisualizationType.State, VisualizationType.Keyboard):
            key = (None, key[1])
        self.register(key, device, input_id)
        self._config[key][input_id] = value
        self.save()

    def getValue(self, key, device: DeviceSummary, visualization: VisualizationType, default_value=False):
        """gets a value"""
        assert isinstance(key, tuple) if key is not None else True, "key must be a tuple"

        if not self._config:
            self.reload()

        if key is None or key not in self._config:
            # old style data
            if visualization in (VisualizationType.State, VisualizationType.Keyboard):
                for k, v in self._config.keys():
                    if v == visualization:
                        key = (k, v)
                        break

        if key not in self._config:
            return default_value
        if visualization not in self._config[key]:
            return default_value
        value = self._config[key][visualization]
        if value is None:
            value = default_value
        return value

    def getConfig(self):
        return self._config

    def reload(self):
        fname = self.get_config()
        load_successful = False
        self._config.clear()
        if os.path.isfile(fname):
            try:
                parser = etree.XMLParser(remove_comments=True, remove_blank_text=True)
                t = etree.parse(fname, parser=parser)
                for node in t.findall(".//data"):
                    if "key" not in node.attrib:
                        # old format, ignore
                        continue
                    key_json = node.get("key")
                    device_id = node.get("device-guid")
                    device = gremlin.joystick_handling.getDevice(device_id)
                    if device is None:
                        # not longer exists
                        continue

                    visualization = VisualizationType(safe_read(node, "id", int, 0))
                    value = safe_read(node, "value", bool, False)
                    key_map = json.loads(key_json)
                    key = (tuple(key_map[0]) if isinstance(key_map[0], list) else key_map[0], key_map[1])
                    assert isinstance(key, tuple), "key must be a tuple"
                    assert gremlin.util.isHashable(key), "key must be hashable"
                    self.register(key, device, visualization)
                    self._config[key][visualization] = value
                load_successful = True
            except ValueError:
                pass

        if not load_successful:
            self._config = {}

    def get_config(self):
        fname = os.path.join(gremlin.shared_state.data_path, "inputViewer.xml")
        return fname


class VisualizationSelector(QtWidgets.QWidget):
    """Presents a list of devices and visualization widgets."""

    # Event emitted when the visualization configuration changes
    changed = Signal(DeviceSummary, VisualizationType, bool)
    clear = Signal()  # delete all
    focus = Signal(DeviceSummary, VisualizationType, bool)  # focus on a specific device or visualization

    def __init__(self, change_callback: Callable, viewer, parent=None, focus_icon=None, unfocus_icon=None, focus_icon_size=16):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.focus_icon = focus_icon or gremlin.ui.ui_common.Icons.circleArrowRight()
        self.unfocus_icon = unfocus_icon or gremlin.ui.ui_common.Icons.circleArrowLeft()
        self.focus_icon_size = focus_icon_size

        devices = gremlin.joystick_handling.getVisibleJoystickDevices()

        self.viewer = viewer
        self._selector_widgets = {}  # created input checkbox widgets by key - if not in this list or None, not created
        self._selector_callbacks = {}  # maps (device_id, VisualizationType) to callback
        self._change_callback = change_callback
        self._callbacks = {}  # list of registered callbacks in the selector
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

    def getCallback(self, key):
        """gets callback associated with the key"""
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

        for widget in gremlin.util.get_layout_widgets(self.main_layout):
            self.main_layout.removeWidget(widget)
            gremlin.util.delete_widget(widget)

        bh_cb = None
        at_cb = None
        ac_cb = None
        bo_cb = None
        ho_cb = None

        index = 0
        vc = VisualizationConfig()
        vc.reload()

        focus_icon_size = self.focus_icon_size

        device: dinput.DeviceSummary
        for device in self._devices:
            if device.disabled:
                continue  # skip disabled devices



            device_name = gremlin.joystick_handling.getDeviceName(device.device_guid)
            box = QtWidgets.QGroupBox(device_name)
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 4)

            if device.axis_count:
                # has axes
                key = (device.key, VisualizationType.AxisTemporal)
                value = vc.getValue(key, device, VisualizationType.AxisTemporal)
                at_cb = gremlin.ui.ui_common.QActionCheckbox(
                    "Axes - Temporal", data=key, value=value, action_size=focus_icon_size, action_callback=self._handle_visualizer_action
                )
                at_cb.setIgnoreKeyboard(True)
                callback = self._create_callback(device, VisualizationType.AxisTemporal, at_cb)
                at_cb.clicked.connect(callback)
                self._selector_callbacks[key] = callback
                layout.addWidget(at_cb)
                self._selector_widgets[key] = at_cb
                self._view_map[key] = index
                index += 1

                if "left" in device.name.casefold():
                    pass

                key = (device.key, VisualizationType.AxisCurrent)
                value = vc.getValue(key, device, VisualizationType.AxisCurrent)
                ac_cb = gremlin.ui.ui_common.QActionCheckbox(
                    "Axes - Current", data=key, value=value, action_size=focus_icon_size, action_callback=self._handle_visualizer_action
                )
                ac_cb.setIgnoreKeyboard(True)
                callback = self._create_callback(device, VisualizationType.AxisCurrent, ac_cb)
                ac_cb.clicked.connect(callback)
                self._selector_callbacks[key] = callback
                layout.addWidget(ac_cb)
                self._selector_widgets[key] = ac_cb
                self._view_map[key] = index

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
                    key = (device.key, VisualizationType.ButtonHat)
                    value = vc.getValue(key, device, VisualizationType.ButtonHat)
                    bh_cb = gremlin.ui.ui_common.QActionCheckbox(
                        stub, data=key, value=value, action_size=focus_icon_size, action_callback=self._handle_visualizer_action
                    )
                    bh_cb.setIgnoreKeyboard(True)
                    callback = self._create_callback(device, VisualizationType.ButtonHat, bh_cb)
                    bh_cb.clicked.connect(callback)
                    self._selector_callbacks[key] = callback
                    layout.addWidget(bh_cb)
                    self._selector_widgets[key] = bh_cb
                    self._view_map[key] = index

                    index += 1
            else:
                # buttons only
                if has_buttons:
                    key = (device.key, VisualizationType.Button)
                    value = vc.getValue(key, device, VisualizationType.Button)
                    bo_cb = gremlin.ui.ui_common.QActionCheckbox(
                        "Buttons", data=key, value=value, action_size=focus_icon_size, action_callback=self._handle_visualizer_action
                    )
                    bo_cb.setIgnoreKeyboard(True)
                    callback = self._create_callback(device, VisualizationType.Button, bo_cb)
                    bo_cb.clicked.connect(callback)
                    self._selector_callbacks[key] = callback
                    layout.addWidget(bo_cb)
                    self._selector_widgets[key] = bo_cb
                    self._view_map[key] = index

                    index += 1

                # hats only
                if has_hats:
                    key = (device.key, VisualizationType.Hat)
                    value = vc.getValue(key, device, VisualizationType.Hat)
                    ho_cb = gremlin.ui.ui_common.QActionCheckbox(
                        "Hats", data=key, value=value, action_size=focus_icon_size, action_callback=self._handle_visualizer_action
                    )
                    ho_cb.setIgnoreKeyboard(True)
                    callback = self._create_callback(device, VisualizationType.Hat, ho_cb)
                    ho_cb.clicked.connect(callback)
                    self._selector_callbacks[key] = callback
                    layout.addWidget(ho_cb)
                    self._selector_widgets[key] = ho_cb
                    self._view_map[key] = index

                    index += 1

            box.setLayout(layout)

            self.main_layout.addWidget(box)





            for key, widget in self._selector_widgets.items():
                if Shiboken.isValid(widget):
                    checked = widget.isChecked()
                    if checked:
                        callback = self._selector_callbacks.get(key, None)
                        if callback:
                            callback()





    def _handle_visualizer_action(self, widget):
        if not Shiboken.isValid(widget):
            return
        key = widget.data
        device_id, visualization = key
        if isinstance(device_id, tuple):
            device = gremlin.joystick_handling.getDeviceFromVjoyId(device_id[0])
        else:
            device = gremlin.joystick_handling.getDevice(device_id)
        if not device:
            return
        checked = not widget.isChecked()
        widget.setChecked(checked)
        self.focus.emit(device, visualization, checked)
        if self._change_callback:
            self._change_callback(device, visualization, checked)

    def closeWidget(self, key):
        """closes the widget associated with the given key"""
        if key in self._view_map:
            widget = self._selector_widgets[key]
            widget.setChecked(False)

    @QtCore.Slot()
    def _clear_selection(self):
        """clears the selection of all widgets"""
        self.clear.emit()
        for key, widget in self._selector_widgets.items():
            if not Shiboken.isValid(widget):
                continue
            with QtCore.QSignalBlocker(widget):
                widget.setChecked(False)

    @QtCore.Slot()
    def _select_real(self):
        """selects all hardware inputs"""
        result = gremlin.ui.ui_common.ConfirmBox(
            "Select all hardware inputs?",
            "This will select all non-temporal hardware inputs.<br>This could be extremely memory and performance intensive.<br>Are you sure you want to select all?",
            parent=self,
        )
        if not result:
            return
        for key, widget in self._selector_widgets.items():
            if not Shiboken.isValid(widget):
                continue
            device_id, visualization = key  # key (device_id, visualization)
            if isinstance(device_id, tuple):
                # vjoy input device, vjoyid is in the first element of the tuple
                device = gremlin.joystick_handling.getDeviceFromVjoyId(device_id[0])
            else:
                device = gremlin.joystick_handling.getDevice(device_id)
            if not device:
                # device not found or no longer connected
                continue

            if visualization != VisualizationType.AxisTemporal and not device.is_virtual:
                with QtCore.QSignalBlocker(widget):
                    widget.setChecked(True)
            else:
                widget.setChecked(False)
            self._create_callback(device, visualization, widget)()

    @QtCore.Slot()
    def _select_vjoy(self):
        widget = self.sender()
        if not Shiboken.isValid(widget):
            return
        id = widget.data
        device = gremlin.joystick_handling.getDeviceFromVjoyId(id)
        if device:
            keys = [(device.key, visualization) for visualization in VisualizationType]
            for key, widget in self._selector_widgets.items():
                if key in keys and Shiboken.isValid(widget):
                    _, visualization = key  # key (device, visualization)
                    if visualization != VisualizationType.AxisTemporal and device.is_virtual and device.vjoy_id == id:
                        with QtCore.QSignalBlocker(widget):
                            widget.setChecked(True)
                        self._create_callback(device, visualization, widget)()

    @QtCore.Slot()
    def _select_all(self):
        """selects all widgets"""
        vc = VisualizationConfig()
        for key, widget in self._selector_widgets.items():
            if Shiboken.isValid(widget):
                with QtCore.QSignalBlocker(widget):
                    widget.setChecked(True)
                _, visualization = key  # key (device.key, visualization)
                # skip temporal axes as that could kill performance fast
                if visualization == VisualizationType.AxisTemporal:
                    continue
                device = vc.getDevice(key)
                if device is None:
                    device_id = key[0]
                    if isinstance(device_id, tuple):
                        # vjoy device
                        vjoy_id = device_id[0]
                        device = gremlin.joystick_handling.getDeviceFromVjoyId(vjoy_id)
                    else:
                        device = gremlin.joystick_handling.getDevice(device_id)
                    if not device:
                        continue
                    vc.register(key, device, visualization)
                assert device is not None, "unregistered device in widget"
                self._create_callback(device, visualization, widget)()

    def _create_callback(self, device: dinput.DeviceSummary, visualization: VisualizationType, widget: QtWidgets.QWidget) -> Callable:
        """Creates the callback to trigger visualization updates.

        :param device_id the device ID being updated
        :param visualization visualization type being updated
        """
        assert isinstance(device, DeviceSummary), "invalid device object"
        assert isinstance(visualization, VisualizationType), "invalid visualization type"
        assert isinstance(widget, QtWidgets.QWidget), "invalid widget"

        key = (device.key, visualization)
        if key not in self._callbacks:
            self._callbacks[key] = lambda: self._callback(device, visualization, widget)
        return self._callbacks[key]

    def _callback(self, device: dinput.DeviceSummary, visualization: VisualizationType, widget: QtWidgets.QWidget):

        assert isinstance(device, DeviceSummary), "invalid device object"
        assert isinstance(visualization, VisualizationType), "invalid visualization type"
        assert isinstance(widget, QtWidgets.QWidget), "invalid widget"
        if not Shiboken.isValid(widget):
            # removed already in the C++ layer
            return

        checked = widget.isChecked()
        config = VisualizationConfig()
        key = (device.key, visualization)
        config.setValue(key, device, visualization, checked)
        self.changed.emit(device, visualization, checked)
        if self._change_callback:
            self._change_callback(device, visualization, checked)

    def setSelector(self, key, enabled: bool):
        """sets the selector checkbox for the given key"""
        widget = self._selector_widgets.get(key, None)
        if widget and Shiboken.isValid(widget) and widget.isChecked() != enabled:
            with QtCore.QSignalBlocker(widget):
                widget.setChecked(enabled)


class VisualizerWidget(QtWidgets.QWidget):
    """visualizer widget for the input viewer."""

    closed = QtCore.Signal(object)  # request close (sends the key)

    def __init__(self, key, device: DeviceSummary, vis: VisualizationType, widget=None, parent=None, description: str = None):
        """Creates a new instance.

        :param parent the parent of this widget
        :param key the key associated with this visualizer
        :param device the device summary
        :param vis the visualization type
        :param widget the content widget to display
        :param description optional description of the visualizer
        """
        super().__init__(parent)
        self._id = gremlin.util.get_guid()


        self._debug_visuals = False
        self._parent_width = None
        self._parent_height = None

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(4, 0, 4, 0)

        # self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum)
        # self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.main_layout.setSizeConstraint(QtWidgets.QVBoxLayout.SetFixedSize)

        self._key = key
        self._device = device
        self._vis = vis
        self._widget = None  # content widget to show
        self._container = None  # container for the widget to show

        if self._debug_visuals:
            self.blank_widget = QtWidgets.QLabel(
                f"<font color='gray'>HIDE {key} {description if description else 'n/a'} id: {self._id} device: [{self._device.name}] visualization: [{self._vis.name}] </font> "
            )
            self.main_layout.addWidget(self.blank_widget)

        self._description = description
        self.setWidget(widget)

    @property
    def id(self):
        """widget id"""
        return self._id

    @property
    def key(self):
        return self._key

    @property
    def widget(self):
        """returns the current widget"""
        return self._widget

    def setWidget(self, widget: QtWidgets.QWidget):
        """sets the widget to display - returns True if success"""

        result = True
        if widget and not Shiboken.isValid(widget):
            self._widget = None
            result = False
            widget = None

        if widget is None:
            # hide the widget
            if self._container:
                self._container.hide()
                self.main_layout.removeWidget(self._container)
                gremlin.util.delete_widget(self._container)
                self._container = None

        else:
            # show the widget

            close_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(size=20, tooltip="Close")
            close_widget.clicked.connect(lambda: self.closed.emit(self._key))

            # give the widget a 100x expansion ratio so it fills most of the available space horizontally
            widget.setFixedWidth(600)
            self._widget_container = gremlin.ui.ui_common.getHContainer([(widget, 100), "||", close_widget], widget_only=True, alignment=QtCore.Qt.AlignTop)

            container_widget = QtWidgets.QWidget()
            container_layout = QtWidgets.QVBoxLayout(container_widget)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
            container_layout.addWidget(self._widget_container)
            self._container = container_widget

            if self._debug_visuals:
                self.blank_widget.setText(
                    f"<font color='green'>SHOW {self._key} {self._description if self._description else 'n/a'} id: {self._id} device: [{self._device.name}] visualization: [{self._vis.name}] </font>"
                )

            self.main_layout.addWidget(self._container)

            widget.show()

        self._widget = widget
        self._update_layout()

        return result

    def resizeEvent(self, event):
        super().resizeEvent(event)
        parent_size = self.parent().size() if self.parent() else None
        if parent_size:
            w = parent_size.width()
            h = parent_size.height()
            if w != self._parent_width or h != self._parent_height:
                self._parent_width = w
                self._parent_height = h
                self._update_layout()

    def _update_layout(self):
        if Shiboken.isValid(self):
            if self._widget and Shiboken.isValid(self._widget):
                match self._vis:
                    case VisualizationType.Button | VisualizationType.ButtonHat:
                        button_widget = self._widget.buttonWidget()
                        w = button_widget.width() if button_widget else self._widget.width()

                        count = self._device.button_count
                        bw = 38 + 8  # width + margin of 4
                        cols = w // bw
                        rows = (count + cols - 1) // cols
                        h = rows * bw

                        if self._vis == VisualizationType.ButtonHat:
                            # account for hat visual
                            hat_height = self._widget.hatWidget().height() if self._widget.hatWidget() else 0
                            h = max(h, hat_height)

                        self._widget_container.setFixedHeight(h + bw)
                        self._container.updateGeometry()

                        h = self._container.sizeHint().height()
                        self.setFixedHeight(h)

                    case VisualizationType.State:
                        # handle state widget
                        # self.setFixedHeight(self.layout().sizeHint().height())
                        h = self._container.sizeHint().height()
                        self.setFixedHeight(h)

                        # self._widget.updateLayout()
                        # gremlin.ui.ui_common.resetWidgetSize(self)
                    case _:
                        # all others - free size
                        gremlin.ui.ui_common.resetWidgetSize(self)
                return
            else:
                # hide
                self.setFixedHeight(0)

    def hideWidget(self):
        """hides the widget"""
        self.blank_widget.setText(f"<font color='gray'>SHOW {self._key} {self._description if self._description else 'n/a'} id: {self._id}</font>")

    def clearWidget(self):
        """clears the widget"""
        self.setWidget(None)


class InputViewerDialog(ui_common.BaseDialogUi):
    """Main UI dialog for the input viewer."""

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(self.__class__.__name__, parent =  parent)

        self.setStyleSheet("QGroupBox { border: 0px }")  # turn group box borders off

        self.focus_icon_size = 20
        self.focus_icon = gremlin.ui.ui_common.Icons.focusIcon()

        self.vis_selector = VisualizationSelector(
            change_callback=self._add_remove_visualization_widget, viewer=self, focus_icon=self.focus_icon, focus_icon_size=self.focus_icon_size
        )
        # self.vis_selector.changed.connect(self._add_remove_visualization_widget)
        self.vis_selector.clear.connect(self._clear)
        self._visualizer_widgets = {}  # created joystick visualizer widgets by key - if not in this list or None, not created - excludes state and keyboard visualizers
        self._visualizer_width: int = None  # width of the visualizers
        self._viewer_widget_map = {}  # holds all the view items

        self._lock = threading.Lock()
        self.setMinimumHeight(800)

        vc = VisualizationConfig()
        self._keyboard_visible = False
        self._state_visible = False

        self.setWindowTitle("GremlinEx Input Viewer")
        self.setWindowFlag(QtCore.Qt.WindowMaximizeButtonHint, True)
        self.setWindowFlag(QtCore.Qt.WindowMinimizeButtonHint, True)

        # sd = gremlin.ui.state_device.StateData()
        # sd.crud.connect(self._state_crud)

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

        # self.views = InputViewerArea()
        self.views = InputViewerArea(callback=self._handle_view_resized)
        self.view_container_layout.addWidget(self.views)

        # configure the scroll area for the selectors (left side of the dialog)
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

        device = gremlin.joystick_handling.getDevice(gremlin.shared_state.keyboard_tab_guid)
        key = vc.keyboard_key
        vc.registerKey(key, device)

        checked = vc.getValue(None, None, VisualizationType.Keyboard, False)
        self.keyboard_widget_selector = gremlin.ui.ui_common.QActionCheckbox(
            "Keyboard/Mouse",
            value=checked,
            callback=self._toggle_keyboard_widget,
            action_size=self.focus_icon_size,
            action_callback=self._handle_keyboard_action,
            tooltip="Toggle keyboard/mouse visualizer",
            data=key,
        )
        self.keyboard_widget_selector.setIgnoreKeyboard(True)
        self._visualizer_widgets[key] = self.keyboard_widget_selector

        show_keyboard = checked

        device = gremlin.joystick_handling.getDevice(gremlin.shared_state.state_tab_guid)
        key = vc.state_key
        vc.registerKey(key, device)
        checked = vc.getValue(None, None, VisualizationType.State, False)
        self.state_widget_selector = gremlin.ui.ui_common.QActionCheckbox(
            "State",
            value=checked,
            callback=self._toggle_state_widget,
            action_size=self.focus_icon_size,
            action_callback=self._handle_state_action,
            tooltip="Toggle state visualizer",
            data=key,
        )
        self.state_widget_selector.setIgnoreKeyboard(True)
        self._visualizer_widgets[key] = self.state_widget_selector

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
        select_all_widget.setToolTip("Selects all (non temporal) inputs")
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
        self._left_panel_widget.setMinimumWidth(200)
        self._left_panel_widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Expanding)

        self._right_panel_widget = QtWidgets.QWidget()
        self._right_panel_layout = QtWidgets.QVBoxLayout(self._right_panel_widget)

        self._splitter.addWidget(self._left_panel_widget)
        self._splitter.addWidget(self._right_panel_widget)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 3)

        self._stacked_widget = QtWidgets.QStackedWidget()  # gremlin.ui.ui_common.QStackedWidgetSizeReporting(resize_callback=self._handle_view_resized)
        self._blank_widget = QtWidgets.QLabel("Please select a visualizer.")
        widget = gremlin.ui.ui_common.getVContainer([self._blank_widget, "||", gremlin.ui.ui_common.QEmptyWidget(), "||"], widget_only=True)
        widget.setContentsMargins(4, 4, 4, 4)
        widget.setProperty("cssClass", "box_frame")
        self._stacked_widget.setContentsMargins(0, 0, 0, 0)
        self._stacked_widget.addWidget(widget)  # index 0

        self._stacked_widget.addWidget(self.view_container_widget)  # index 1

        self._left_panel_layout.addWidget(self.scroll_selector_area)
        self._right_panel_layout.addWidget(self._stacked_widget)

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

        self._update_ui()

        el = gremlin.event_handler.EventListener()
        el.profile_loaded.connect(self.refresh)
        el.profile_unhook.connect(self.reload)

    @property
    def visualizerWidth(self) -> int:
        """returns the width of the visualizer widgets"""
        if not self._visualizer_width:
            self.views.adjustSize()
            self.views.update()
            width = self.views.width()
            self._visualizer_width = width

        return self._visualizer_width

    def _handle_view_resized(self, old_size: QtCore.QSize, new_size: QtCore.QSize):

        size = new_size
        margins = self.views.contentsMargins()
        bar_width = self.views.bar().width()
        offset = margins.left() + margins.right() + 2 * bar_width
        width = new_size.width() - offset
        # syslog.info(
        #     f"INPUT VIEWER: _handle_view_resized new width: {new_size.width()} offset: [{offset}] margins: {margins} bar_width: {bar_width} corrected width: {width}"
        # )
        size.setWidth(width)  # account for scroll bar
        self._update_layout(size)
        self._visualizer_width = width  # store for new visualizers that are added later

    def _handle_keyboard_action(self):
        """handles the focus action for keyboard selectors"""
        vc = VisualizationConfig()
        key = vc.keyboard_key
        self.keyboard_widget_selector.setChecked(not self.keyboard_widget_selector.isChecked())
        if self.keyboard_widget_selector.isChecked():
            self.scrollToVisualizer(key)

    def _handle_state_action(self):
        """handles the focus action for state and keyboard selectors"""
        vc = VisualizationConfig()
        key = vc.state_key
        self.state_widget_selector.setChecked(not self.state_widget_selector.isChecked())
        if self.state_widget_selector.isChecked():
            self.scrollToVisualizer(key)

    def scrollToVisualizer(self, key):
        """scrolls to the visualizer associated with the given key"""
        self.views.scrollToVisualizer(key)

    def _visualizer_count(self):
        """returns the number of visualizer widgets"""
        count = sum(1 for w in self._visualizer_widgets.values() if w is not None)
        if self._state_visible:
            count += 1
        if self._keyboard_visible:
            count += 1
        return count

    def _update_ui(self):
        """updates the UI elements"""
        if not Shiboken.isValid(self):
            return
        if not Shiboken.isValid(self._stacked_widget):
            return

        if self._visualizer_count():
            # display visualizers
            self._stacked_widget.setCurrentIndex(1)
        else:
            # display empty
            self._stacked_widget.setCurrentIndex(0)

    def closeSystemWidget(self, key):
        """closes the widget associated with the given key"""

        _, visualization_type = key
        match visualization_type:
            case VisualizationType.State:
                self.state_widget_selector.setChecked(False)
            case VisualizationType.Keyboard:
                self.keyboard_widget_selector.setChecked(False)
            case _:
                self.vis_selector.closeWidget(key)
                callback = self.vis_selector.getCallback(key)
                callback()

    def load_viewer_widgets(self):
        """loads the view widgets for all device inputs"""

        # build all possible visualizations for the devices - this is used to determine if a visualization is available for a device
        self.views.clear()
        self._viewer_widget_map = {}
        self._device_key_map = {}

        # state visualizer
        device = gremlin.joystick_handling.getDevice(gremlin.shared_state.state_tab_guid)
        self._add_widget(device, VisualizationType.State, description="State")

        # keyboard visualizer
        device = gremlin.joystick_handling.getDevice(gremlin.shared_state.keyboard_tab_guid)
        self._add_widget(device, VisualizationType.Keyboard, description="Keyboard")

        # joystic visualizers
        devices = gremlin.joystick_handling.all_joystick_devices()
        verbose = False

        for device in devices:
            if device.disabled:
                continue
            # Unconfigured vJoy slots (13-16 when only 1-12 exist) are internal placeholders.
            if device.device_type == DeviceType.VJoy and not device.connected:
                continue
            if verbose:
                syslog.info(
                    f"INPUT VIEWER: load_viewer_widgets - device {device.name} ({device.device_id}) axes: {device.axis_count} buttons: {device.button_count} hats: {device.hat_count}"
                )
            if device.axis_count:
                self._add_widget(device, VisualizationType.AxisTemporal, description="Temporal Axis")
                if verbose:
                    syslog.info("\ttemporal axis")
                self._add_widget(device, VisualizationType.AxisCurrent, description="Current Axis")
                if verbose:
                    syslog.info("\tcurrent axis")
            if device.button_count or device.hat_count:
                self._add_widget(device, VisualizationType.ButtonHat, description="ButtonHat")
                if verbose:
                    syslog.info("\tbutton hat")
            if device.button_count:
                self._add_widget(device, VisualizationType.Button, description="Button")

                if verbose:
                    syslog.info("\tbutton")
            if device.hat_count:
                self._add_widget(device, VisualizationType.Hat, description="Hat")

                if verbose:
                    syslog.info("\that")

        self.devices = devices

    def ensureWidget(self, device: DeviceSummary, visualization: VisualizationType):
        """ensures the widget is created for the given device and visualization type"""
        vc = VisualizationConfig()
        key = vc.getKey(device, visualization)
        if key not in self._viewer_widget_map:
            self._add_widget(device, visualization)

    def _update_layout(self, size: QtCore.QSize = None):
        widget: QtWidgets.QWidget
        margin = 8
        if size:
            width = size.width()
        else:
            width = self.views.width()

        if self._state_visualizer_widget:
            self._state_visualizer_widget.setFixedWidth(width)
        if self._keyboard_visualizer_widget:
            self._keyboard_visualizer_widget.setFixedWidth(width)
        for widget in self._viewer_widget_map.values():
            sub_widget = widget.widget
            # widget.setFixedWidth(width)
            if sub_widget:
                sub_widget.setFixedWidth(width - margin)

    def _add_widget(self, device: DeviceSummary, visualization: VisualizationType, description: str = None):
        vc = VisualizationConfig()
        key = vc.getKey(device, visualization)
        if key in self._viewer_widget_map:
            return

        widget = VisualizerWidget(key, device=device, vis=visualization, description=description)

        # widget.layout().addWidget(QtWidgets.QLabel(f"visualizer widget for device: [{device.name}] visualization: [{visualization.name}]"))
        widget.closed.connect(lambda key: self.closeSystemWidget(key))
        self._viewer_widget_map[key] = widget
        self._device_key_map[key] = device
        self.views.add_widget(key, widget)

        return widget

    def _clear_all(self):
        """clears all items"""


        vc = VisualizationConfig()
        for key in self._viewer_widget_map:
            device = vc.getDevice(key)
            _, visualization = key
            vc.setValue(key, device, visualization, False)

        self.vis_selector._clear_selection()
        self.saveKeyboardState(False)
        self.saveStateState(False)
        self.load_viewer_widgets()  # reload devices

    def saveKeyboardState(self, value : bool = None):
        """saves the keyboard state"""
        vc = VisualizationConfig()
        device = gremlin.joystick_handling.getDevice(gremlin.shared_state.keyboard_tab_guid)
        if value is None:
            value = self._keyboard_visible
        vc.setValue(vc.keyboard_key, device, VisualizationType.Keyboard, value)

    def saveStateState(self, value : bool = None):
        """saves the state visualizer state"""
        vc = VisualizationConfig()
        device = gremlin.joystick_handling.getDevice(gremlin.shared_state.state_tab_guid)
        if value is None:
            value = self._state_visible
        vc.setValue(vc.state_key, device, VisualizationType.State, value)

    def _select_all(self):
        # select keyboard and state

        result = gremlin.ui.ui_common.ConfirmBox(
            "Select all non-temporal inputs?",
            "This will select all non-temporal inputs.<br>This could be extremely memory and performance intensive.<br>Are you sure you want to select all?",
            parent=self,
        )
        if not result:
            return

        self._keyboard_visible = True
        self._state_visible = True
        self.vis_selector._select_all()

        vc = VisualizationConfig()
        device = gremlin.joystick_handling.getDevice(gremlin.shared_state.state_tab_guid)
        vc.setValue(vc.state_key, device, VisualizationType.State, True)
        device = gremlin.joystick_handling.getDevice(gremlin.shared_state.keyboard_tab_guid)
        vc.setValue(vc.keyboard_key, device, VisualizationType.Keyboard, True)
        self.showState()
        self.showKeyboard()

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
        # self._state_buttons.clear()
        self._viewer_widget_map.clear()
        self._device_key_map.clear()
        self._event_data.clear()
        self._visualizer_widgets.clear()

        # sd = gremlin.ui.state_device.StateData()
        # sd.crud.disconnect(self._state_crud)

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
        # self._state_buttons.clear()

        self._delete_widget(self.keyboard_widget)
        self.keyboard_widget = None

        self._delete_widget(self._keyboard_visualizer_widget)
        self._keyboard_visualizer_widget = None

        self._cleanup_joystick_widgets()

        self.views.clear()
        self._visualizer_widgets.clear()
        self._update_ui()

    def reload(self):
        """reloads the ui"""
        if Shiboken.isValid(self):
            gremlin.util.InvokeUiMethod(self._reload_ui)  # refresh the visuals and selectors

    def _reload_ui(self):
        self._reload_states_ui()
        if self._state_visible:
            self.showState()
        if self._keyboard_visible:
            self.showKeyboard()
        self.vis_selector.updateSelector()
        self._update_ui()

    def refresh(self):
        """refreshes the visualizers"""
        gremlin.util.InvokeUiMethod(self._reload_ui)  # refresh the visuals and selectors

    def _refresh_ui(self):
        self._clear()

        self.vis_selector.updateSelector()
        self._update_ui()

    def getVisualizerIndex(self, key):
        """returns the index of the visualizer in the view container"""
        view_map = self.vis_selector.getViewMap()
        if key in view_map:
            return view_map[key]
        return None

    @QtCore.Slot(DeviceSummary, VisualizationType, bool)
    def _add_remove_visualization_widget(self, device: DeviceSummary, visualization: VisualizationType, enabled: bool | None):
        """Adds or removes a visualization widget.

        :param device: the device which is being updated (DeviceSummary)
        :param visualization: the visualization type being updated
        :param enabled: the state - if None, uses the current state
        """

        verbose = gremlin.config.Configuration().verbose_mode_ui
        assert gremlin.util.is_ui_thread()
        if not Shiboken.isValid(self):
            if verbose:
                syslog.info("InputViewer: add/remove widget - C++ GC - dialog no longer valid")
            return

        if verbose:
            syslog.info(f"InputViewer: add/remove widget - device: {device.name} visualization: {visualization.name} enabled: {enabled}")

        vc = VisualizationConfig()
        assert isinstance(device, DeviceSummary), "invalid device object"

        key = vc.getKey(device, visualization)
        if key not in self._viewer_widget_map:
            self._add_widget(device, visualization)
        assert key in self._viewer_widget_map, "visual not registered"
        assert device is not None, "invalid device"
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

        vc = VisualizationConfig()

        if enabled is None:
            # use the existing value
            enabled = vc.getValue(device.key, device, visualization)
            if enabled is None:
                enabled = False

        if enabled:
            widget = self._visualizer_widgets.get(key, None)
            if widget is None or not Shiboken.isValid(widget):
                # widget does not exist, create
                if verbose:
                    syslog.info(f"\tCreating new vis: {device.name}: {visualization.name}  key: {key}")

                widget = ui_common.JoystickDeviceWidget(device, visualization)
                visualizer_widget = self._viewer_widget_map[key]
                visualizer_widget.setWidget(widget)
                visualizer_widget.setFixedWidth(self.visualizerWidth)
                if verbose:
                    syslog.info(f"Setting widget for {device.name}: {visualization.name} key: {key}  viewer widget key: [{visualizer_widget.key}]")

                widget.hook()
                if verbose:
                    syslog.info(f"Create new vis: {device.name}: {visualization.name}  key: {key}")

                self._visualizer_widgets[key] = widget

        else:
            if verbose:
                syslog.info(f"\tRemove vis: {device.name}: {visualization.name}  key: {key}")
            if key in self._viewer_widget_map:
                # displayed
                if verbose:
                    syslog.info(f"Remove existing vis: {device.name}: {visualization.name} key: {key}")

                viewer_widget = self._viewer_widget_map[key]
                widget = viewer_widget.widget
                if widget:
                    viewer_widget.setWidget(None)
                    if Shiboken.isValid(widget):
                        widget.unhook()
                        gremlin.util.delete_widget(widget)

                # remove the widget
                if key in self._visualizer_widgets:
                    del self._visualizer_widgets[key]

        # synchronize with selector checkbox
        self.vis_selector.setSelector(key, enabled)

        # store the data
        vc.setValue(key, device, visualization, enabled)

        self._update_ui()

    def populateState(self):
        """execute on UI thread"""
        if Shiboken.isValid(self) and Shiboken.isValid(self._state_visualizer_widget):
            gremlin.util.InvokeUiMethod(self._populateState_ui)

    def _populateState_ui(self, layout):
        self._reload_states_ui()

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
        if not self._state_visualizer_widget or not Shiboken.isValid(self._state_visualizer_widget):
            return

        self._state_visualizer_widget.reloadStates()

    def showKeyboard(self):
        """keyboard device"""
        assert gremlin.util.is_ui_thread()
        if self._keyboard_visible:
            return
        vc = VisualizationConfig()
        key = vc.keyboard_key
        viewer_widget = self._viewer_widget_map.get(key, None)

        if not viewer_widget or not Shiboken.isValid(viewer_widget):
            # check for C++ GC and/or need to create viewer slot
            device = gremlin.joystick_handling.getDevice(gremlin.shared_state.keyboard_tab_guid)
            viewer_widget = self._add_widget(device, VisualizationType.Keyboard)

        assert viewer_widget is not None, "keyboard view widget not in list yet - did you call load_viewer_widgets() first?"

        widget = self._keyboard_visualizer_widget
        if widget and not Shiboken.isValid(widget):
            # check for C++ GC
            self._keyboard_visualizer_widget = None
            widget = None

        if not widget:
            widget = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(widget)
            layout.addWidget(QtWidgets.QLabel("Keyboard/Mouse Visualizer:"))

            self.keyboard_widget = gremlin.ui.virtual_keyboard.QKeyboardWidget(release_wheel=True)
            # self.keyboard_widget.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            self.keyboard_widget.setReadonly(True)
            layout.addWidget(self.keyboard_widget)

            self.keyboard_widget.hook()
            self._keyboard_visualizer_widget = widget # gremlin.ui.ui_common.getHContainer(widget, widget_only=True)
            self._keyboard_visible = True

            # if self._visualizer_width:
            #     widget.setFixedWidth(self._visualizer_width)

        viewer_widget.setWidget(self._keyboard_visualizer_widget)

        with QtCore.QSignalBlocker(self.keyboard_widget_selector):
            self.keyboard_widget_selector.setChecked(True)

        width = self.visualizerWidth
        viewer_widget.setFixedWidth(width)
        widget.setFixedWidth(width)
        self._keyboard_visible = True
        self._update_ui()

        # save keyboard state
        self.saveKeyboardState()

    def hideKeyboard(self):
        if self._keyboard_visible:
            vc = VisualizationConfig()
            key = vc.keyboard_key
            if key in self._viewer_widget_map:
                viewer_widget = self._viewer_widget_map.get(key)
                viewer_widget.clearWidget()
                self._keyboard_visualizer_widget = None

            with QtCore.QSignalBlocker(self.keyboard_widget_selector):
                self.keyboard_widget_selector.setChecked(False)
            self._keyboard_visible = False
            self._update_ui()

            # store the state
            self.saveKeyboardState()

    def showState(self):
        """state device"""

        if self._state_visible:
            return

        vc = VisualizationConfig()
        key = vc.state_key

        widget = self._state_visualizer_widget
        if widget and not Shiboken.isValid(widget):
            # check for C++ GC
            self._state_visualizer_widget = None
            widget = None

        # widget holding state information
        if not widget:
            widget = gremlin.ui.ui_common.StateVisualizerWidget()
            self._state_visualizer_widget = widget

        viewer_widget = self._viewer_widget_map.get(key, None)
        if not viewer_widget or not Shiboken.isValid(viewer_widget):
            # check for C++ GC and/or need to create viewer slot
            device = gremlin.joystick_handling.getDevice(gremlin.shared_state.state_tab_guid)
            viewer_widget = self._add_widget(device, VisualizationType.State)

        assert viewer_widget is not None, "state view widget not in list yet - did you call load_viewer_widgets() first?"

        # self.populateState()
        viewer_widget.setWidget(widget)
        width = self.visualizerWidth
        viewer_widget.setFixedWidth(width)
        widget.setFixedWidth(viewer_widget.contentsRect().width())

        self._state_visible = True
        self._state_visualizer_widget.populateState()
        self._update_ui()
        #self.views.updateGeometry()

        # store the state
        self.saveStateState()

    def hideState(self):
        """hides the state device"""
        if self._state_visible:
            vc = VisualizationConfig()
            key = vc.state_key

            if key in self._viewer_widget_map:
                viewer_widget = self._viewer_widget_map.get(key)
                assert viewer_widget is not None, "state view widget not in list yet - did you call load_viewer_widgets() first?"
                viewer_widget.clearWidget()
                gremlin.util.delete_widget(self._state_visualizer_widget)
                self._state_visualizer_widget = None

            self._state_visible = False
            with QtCore.QSignalBlocker(self.state_widget_selector):
                self.state_widget_selector.setChecked(False)
            self._update_ui()

            # store the state
            self.saveStateState()

    @QtCore.Slot(bool)
    def _toggle_keyboard_widget(self, checked: bool):
        if checked:
            self.showKeyboard()
        else:
            self.hideKeyboard()

        self._keyboard_visible = checked
        vc = VisualizationConfig()
        device = gremlin.joystick_handling.getDevice(gremlin.shared_state.keyboard_tab_guid)
        key = vc.keyboard_key
        vc.setValue(key, device, VisualizationType.State, checked)

    @QtCore.Slot(bool)
    def _toggle_state_widget(self, checked: bool):
        if checked:
            self.showState()
        else:
            self.hideState()

        self._state_visible = checked
        vc = VisualizationConfig()
        key = vc.state_key
        device = gremlin.joystick_handling.getDevice(gremlin.shared_state.state_tab_guid)
        vc.setValue(key, device, VisualizationType.State, checked)

    @QtCore.Slot(bool)
    def _toggle_combine_button_hat(self, checked: bool):
        config = gremlin.config.Configuration()
        config.input_viewer_combine_buttonhats = checked

        # remove the joystick widgets
        self._cleanup_joystick_widgets()

        self.vis_selector.updateSelector()

    def _cleanup_joystick_widgets(self):
        for key in self._viewer_widget_map:
            widget = self._viewer_widget_map[key]
            if hasattr(widget, "unhook"):
                widget.unhook()
            if widget and Shiboken.isValid(widget):
                widget.hide()
                self.views.remove_widget(key)
                gremlin.util.delete_widget(widget)
        self._viewer_widget_map.clear()

    @QtCore.Slot(bool)
    def _toggle_flow_layout(self, checked: bool):
        config = gremlin.config.Configuration()
        config.input_viewer_flow_layout = checked
        self.views.updateLayout()


class InputViewerArea(QtWidgets.QWidget):
    """Holds individual input visualization widgets."""

    def __init__(self, callback: Callable[[QtCore.QSize, QtCore.QSize], None] = None, parent=None):
        """Creates a new instance.

        :param parent the parent of this widget
        """
        super().__init__(parent)
        # self._size_changed_callback = callback
        layout = QtWidgets.QVBoxLayout(self)
        # layout.setContentsMargins(4, 0, 4, 0)

        self._viewer_widgets = {}  # holds view widgets by key

        self.scroll_area = gremlin.ui.ui_common.QScrollAreaResizeCallback(callback)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = gremlin.ui.ui_common.QScrollLayout(self.scroll_widget)
        self.scroll_widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)

        self.scroll_area.setWidget(self.scroll_widget)
        self.installEventFilter(self)

        layout.addWidget(self.scroll_area)

    # def resizeEvent(self, event: QResizeEvent):
    #     super().resizeEvent(event)
    #     old_size = event.oldSize()
    #     new_size = event.size()

    #     if self._size_changed_callback:
    #         self._size_changed_callback(old_size, new_size)

    def bar(self):
        """returns the vertical scroll bar"""
        return self.scroll_area.verticalScrollBar()

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

    def add_widget(self, key: tuple, widget, index=None):
        """Adds the specified widget to the visualization area.

        :param widget the widget to add
        """
        assert gremlin.util.is_ui_thread()
        if not Shiboken.isValid(self):
            return

        if key in self._viewer_widgets:
            # remove it first
            current_widget = self._viewer_widgets.get(key)
            if widget == current_widget:
                # same - no need to remove and re-add
                return
            self.remove_widget(key)

        self._viewer_widgets[key] = widget
        self.scroll_layout.addWidget(widget)

    def remove_widget(self, key: tuple):
        """Removes a widget from the visualization area.

        :param widget the widget to remove
        """
        assert gremlin.util.is_ui_thread()
        if key in self._viewer_widgets:
            widget = self._viewer_widgets[key]
            if not Shiboken.isValid(self) or not Shiboken.isValid(widget):
                return
            if hasattr(widget, "unhook"):
                widget.unhook()
            self.scroll_layout.removeWidget(widget)
            del self._viewer_widgets[key]

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
        self._viewer_widgets.clear()

    def scrollToVisualizer(self, key: tuple):
        if key in self._viewer_widgets:
            self.scroll_area.ensureWidgetVisible(self._viewer_widgets[key])


_visualization_config = VisualizationConfig()
