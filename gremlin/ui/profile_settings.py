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


from PySide6 import QtCore, QtWidgets

import gremlin.event_handler
import gremlin.input_item
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.config
from gremlin.types import DeviceType
from gremlin.ui.ui_common import QDataPushButton, getVContainer, getHContainer, QDataCheckbox, Buttons, QInfoBox
from dinput import DeviceSummary
import gremlin.util
from psygnal import Signal
from gremlin.ui.qdatawidget import QDataWidget
from shiboken6 import Shiboken
import gremlin.tabstate
from functools import partial

from gremlin.ui.ui_common import (
    Buttons,
    clear_layout,
    Color,
    ConfirmBox,
    get_text_width,
    getGridContainer,
    getHContainer,
    getLayoutWidgetHeight,
    getVContainer,
    Icons,
    InputListenerWidget,
    QArrowPairWidget,
    QAutoResizeStackedWidget,
    QAxisRepeaterProgressbar,
    QCurveWidget,
    QDataCheckbox,
    QDataComboBox,
    QDataLabel,
    QDataLineEdit,
    QDataPushButton,
    QDataRadioButton,
    QDataRadioButtonGroup,
    QDataWidget,
    QDelayWidget,
    QExecuteWidget,
    QFloatLineEdit,
    QFrameBox,
    QHatSelectorComboBox,
    QHorizontalLine,
    QHorizontalSeparator,
    QIconLabel,
    QIntLineEdit,
    QProgressBar,
    QShowAtCursorDialog,
    QSideBarContainer,
    QSyncModeWidget,
    QUsedPushButton,
    QWarningWidget,
    RemoteClientWidget,
    synchronize_grids,
    QFailoverWidget,
)
from gremlin.ui.ui_common import (
    ModeSelectorWidget,
    QButtonGrid,
    QRememberDialog,
)


class ProfileSettingsWidget(QDataWidget):
    """Widget allowing changing profile specific settings."""

    # Signal emitted when a change occurs
    changed = Signal()

    def __init__(self, profile_settings, parent=None):
        """Creates a new UI widget.

        :param profile_settings the settings of the profile
        :param parent the parent widget
        """
        super().__init__(parent)

        self.profile_settings = profile_settings

        self.main_layout = QtWidgets.QVBoxLayout(self)

        # Create required scroll UI elements
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout()

        # Configure the widget holding the layout with all the buttons
        self.scroll_widget.setLayout(self.scroll_layout)
        self.scroll_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        # Configure the scroll area
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)

        # Add the scroll area to the main layout
        self.main_layout.addWidget(self.scroll_area)

        self._create_ui()

    def isLoaded(self) -> bool:
        return True

    @property
    def inputCount(self) -> int:
        """number of inputs in the device"""
        return 0

    @property
    def inputWidgetCount(self) -> int:
        """number of input widgets currently in the device"""
        return 0

    def ensureLoaded(self):
        ts = gremlin.tabstate.TabState()
        data = ts.getData(gremlin.shared_state.settings_tab_id)
        if not data.populateEnabled:
            data.populateEnabled = True
            gremlin.util.InvokeUiMethod(self._refresh_ui, False)  # UI thread

    def _refresh_ui(self, emit=False):
        """reloads the tab"""

        clear_layout(self.scroll_layout)
        self._create_ui()
        if emit:
            self.changed.emit()

    def refresh(self, emit=True):
        gremlin.util.InvokeUiMethod(self._refresh_ui, emit)  # UI thread

    @QtCore.Slot(dict)
    def virtual_as_input_changed(self, virtual_map: dict):
        """Release vJoy handles so external applications can drive selected inputs."""
        for (device_type, index), enabled in virtual_map.items():
            if enabled and device_type == DeviceType.VJoy:
                vjoy = gremlin.joystick_handling.VJoyProxy()[index]
                vjoy.ensure_released()

    def _create_ui(self):
        """Creates the UI elements of this widget."""
        # Default start mode selection
        if not Shiboken.isValid(self):
            return

        ts = gremlin.tabstate.TabState()
        data = ts.getData(gremlin.shared_state.settings_tab_id)
        if not data or not data.populateEnabled:
            # do not populate the list
            return

        mode_widget = DefaultModeSelector(self.profile_settings)
        delay_widget = DefaultDelay(self.profile_settings)

        # Maestro input remains available when virtual output failover is on.
        virtual_as_input_widget = VirtualAsInputWidget(self.profile_settings)
        virtual_as_input_widget.changed.connect(self.virtual_as_input_changed)

        # vJoy axis initialization value setup
        widget = QtWidgets.QGroupBox("Profile Start Initial Values")
        box_layout = QtWidgets.QHBoxLayout()
        widget.setLayout(box_layout)

        grid_widget, grid_layout = getGridContainer()
        max_col = 5

        box_layout.addWidget(grid_widget)
        box_layout.addStretch()

        grid_layout.addWidget(QtWidgets.QWidget(), 0, max_col)
        grid_layout.setColumnStretch(max_col, 2)

        # Information label
        label_widget = QInfoBox("Select profile defaults and vJoy or Maestro joystick inputs. These values will be used when activating Gremlin.")

        self.scroll_layout.addWidget(label_widget)

        widgets = [mode_widget, delay_widget, virtual_as_input_widget, grid_widget, label_widget]

        # holds all the inputs in a vertical box
        widget = getVContainer(widgets, widget_only=True)

        # make the box only use the width needed to show
        container = getHContainer(widget, widget_only=True)

        self.scroll_layout.addWidget(container)

        self.scroll_layout.addStretch(1)


class DefaultDelay(QtWidgets.QWidget):
    """Configures the default delay used with macro executions."""

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        Parameters
        ==========
        profile_data : profile.Settings
            Profile settings data storing information
        parent : QtObject
            Parent of this widget
        """
        super().__init__(parent)

        self.profile_data = profile_data

        self.main_layout = QtWidgets.QHBoxLayout(self)

        self.delay_widget = QDelayWidget(
            max_value_seconds=10, value=self.profile_data.default_delay, callback=self._handle_delay_changed, show_zero=True
        )

        widget = getHContainer(["Default Macro Action Delay:", self.delay_widget], widget_only=True)
        self.main_layout.addWidget(widget)

    def _handle_delay_changed(self, value):
        """Updates the value of the delay with the user input.

        Parameters
        ==========
        value : float
            New delay value to use between macro actions
        """
        self.profile_data.default_delay = value


class DefaultModeSelector(QtWidgets.QWidget):
    """Allows selecting the mode in which Gremlin starts."""

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data profile settings managed by the widget
        :param parent the parent of this widget
        """
        super().__init__(parent)
        self.profile_data = profile_data
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins

        self.selector_widget = ModeSelectorWidget(text="Profile Start Mode:")
        self.selector_widget.setContentsMargins(0, 0, 0, 0)
        mode = gremlin.shared_state.current_profile.get_start_mode()
        self.selector_widget.setMode(mode)
        self.selector_widget.modeChanged.connect(self._handle_mode_changed)

        widget = getHContainer(self.selector_widget, widget_only=True)

        el = gremlin.event_handler.EventListener()
        el.profile_modes_changed.connect(self._handle_profile_modes_modified)

        self.main_layout.addWidget(widget)

    def _handle_profile_modes_modified(self):
        gremlin.util.InvokeUiMethod(self._handle_profile_modes_modified_ui)  # ensure on UI thread

    def _handle_profile_modes_modified_ui(self):
        mode = gremlin.shared_state.current_profile.get_start_mode()
        self.selector_widget.refresh(mode)

    def _handle_mode_changed(self, mode: str):
        gremlin.shared_state.current_profile.set_start_mode(mode)


class VjoyDefaultsDialog(QRememberDialog):
    def __init__(self, device, settings, parent=None):
        super().__init__(self.__class__.__name__, parent=parent)

        main_layout = QtWidgets.QVBoxLayout(self)
        self.setWindowTitle(f"VJoy {device.vjoy_id} Profile Default Editor")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.setModal(True)
        self._parent = parent  # list view parent

        self.axis_widget = VJoyAxisDefaultsWidget(device, settings)
        self.axis_widget.from_profile(gremlin.shared_state.current_profile)

        self.button_widget = VJoyButtonsDefaultsWidget(device, settings)
        self.button_widget.from_profile(gremlin.shared_state.current_profile)  # load current data

        # create axis tab
        self.tab_widget = QtWidgets.QTabWidget()
        self.tab_widget.addTab(self.axis_widget, "Axis Default")
        self.tab_widget.addTab(self.button_widget, "Button Default")

        self.device = device
        main_layout.addWidget(self.tab_widget)

        self.ok_widget = QDataPushButton("Ok", callback=self._ok_button_cb)
        self.cancel_widget = QDataPushButton("Cancel", callback=self._cancel_button_cb)

        widget = getHContainer(["||", self.ok_widget, self.cancel_widget], widget_only=True, auto_size=True)

        main_layout.addWidget(widget)

    def _ok_button_cb(self):
        """ok button pressed"""
        profile = gremlin.shared_state.current_profile
        # save the data to the profile
        self.axis_widget.to_profile(profile)
        self.button_widget.to_profile(profile)
        self.accept()

    def _cancel_button_cb(self):
        """cancel button pressed"""
        self.reject()


class VJoyButtonsDefaultsWidget(QtWidgets.QWidget):
    """UI widget allowing modification of button initialization values."""

    def __init__(self, device, settings, parent=None):
        super().__init__(parent)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.grid_widget = QButtonGrid(device)
        self.main_layout.addWidget(self.grid_widget)

        on_widget = QtWidgets.QPushButton("All On")
        on_widget.setToolTip("Sets all buttons to off")
        on_widget.clicked.connect(self._all_on)
        off_widget = QtWidgets.QPushButton("All Off")
        off_widget.setToolTip("Sets all buttons to off")
        off_widget.clicked.connect(self._all_off)

        button_container_widget = getHContainer([on_widget, off_widget], left_stretch=True, widget_only=True)
        self.main_layout.addWidget(button_container_widget)

    def _all_on(self):
        self.grid_widget.all_on()

    def _all_off(self):
        self.grid_widget.all_off()

    def from_profile(self, profile):
        """load data from the current profile"""
        self.grid_widget.from_profile(gremlin.shared_state.current_profile)

    def to_profile(self, profile):
        """save data to the current profile"""
        self.grid_widget.to_profile(gremlin.shared_state.current_profile)


class VJoyAxisDefaultsWidget(QtWidgets.QWidget):
    """UI widget allowing modification of axis initialization values."""

    def __init__(self, device, settings, parent=None):
        """Creates a new UI widget.

        :param joy_data JoystickDeviceData object containing device information
        :param profile_data profile settings managed by the widget
        :param parent the parent of this widget
        """
        super().__init__(parent)
        import dinput

        assert device.is_virtual and device.vjoy_id > 0, "Device provided is not a VJOY device"
        self.device: dinput.DeviceSummary = device
        self._device_guid = device.device_guid
        self._device_id = device.device_id
        self._axis_count = device.axis_count

        self.settings = settings

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.grid_layout = QtWidgets.QGridLayout(self)
        self.grid_layout.setColumnMinimumWidth(0, 100)
        self.grid_layout.setColumnStretch(2, 1)
        self._state = {}  # map of [axis: int] to float
        self._enabled_state = {}  # map of [axi: int] to bool, true if the widget is enabled

        self._grid_widgets = {}  # map of [axis: int] to floatinput widget
        self._grid_enabled = {}  # map of [axis: int] to enabled widget

        self._spin_boxes = []

        self.main_layout.addLayout(self.grid_layout)

        self._create_ui()

        # helper commands

        enabled_widget = QDataPushButton("All Enabled", callback=self._all_enabled, tooltip="Sets all axes to enabled")
        disabled_widget = QDataPushButton("All Disabled", callback=self._all_disabled, tooltip="Sets all axes to disabled")
        min_widget = QDataPushButton("All Min", callback=self._all_min, tooltip="Sets all axes to minimum")
        max_widget = QDataPushButton("All Max", callback=self._all_max, tooltip="Sets all axes to maximum")
        zero_widget = QDataPushButton("All Center", callback=self._all_zero, tooltip="Sets all axes to center")

        widgets = [enabled_widget, disabled_widget, " ", min_widget, zero_widget, max_widget]

        button_container_widget = getHContainer(widgets, left_stretch=True, widget_only=True, auto_size=True)
        self.main_layout.addWidget(button_container_widget)

    def _all_enabled(self):
        gremlin.util.InvokeUiMethod(self._all_enabled_ui)

    def _all_enabled_ui(self):
        for widget in self._grid_enabled.values():
            if Shiboken.isValid(widget):
                with QtCore.QSignalBlocker(widget):
                    widget.setChecked(True)
                    id = widget.data
                    self._enabled_state[id] = True

    def _all_disabled(self):
        gremlin.util.InvokeUiMethod(self._all_disabled_ui)

    def _all_disabled_ui(self):
        for widget in self._grid_enabled.values():
            if Shiboken.isValid(widget):
                with QtCore.QSignalBlocker(widget):
                    widget.setChecked(False)
                    id = widget.data
                    self._enabled_state[id] = False

    def _all_min(self):
        gremlin.util.InvokeUiMethod(self._all_min_ui)

    def _all_min_ui(self):
        for widget in self._grid_widgets.values():
            if Shiboken.isValid(widget):
                with QtCore.QSignalBlocker(widget):
                    widget.setValue(-1.0)
                    id = widget.data
                    self._state[id] = -1.0

    def _all_max(self):
        gremlin.util.InvokeUiMethod(self._all_max_ui)

    def _all_max_ui(self):
        for widget in self._grid_widgets.values():
            if Shiboken.isValid(widget):
                with QtCore.QSignalBlocker(widget):
                    widget.setValue(1.0)
                    id = widget.data
                    self._state[id] = 1.0

    def _all_zero(self):
        gremlin.util.InvokeUiMethod(self._all_zero_ui)

    def _all_zero_ui(self):
        for widget in self._grid_widgets.values():
            if Shiboken.isValid(widget):
                with QtCore.QSignalBlocker(widget):
                    widget.setValue(0.0)
                    id = widget.data
                    self._state[id] = 0.0

    def from_profile(self, profile):
        """reads the data from the current profile"""
        if not self.device:
            return
        self._state.clear()
        for id in range(1, self._axis_count + 1):
            value = profile.getStartAxisValue(self._device_id, id)
            if value is None:
                value = 0.0
            self._state[id] = value
            enabled = profile.getStartAxisEnabled(self._device_id, id)
            if enabled is not None:
                self._enabled_state[id] = enabled
        self._populate_grid()

    def to_profile(self, profile):
        """saves the data to the current profile"""
        if not self.device:
            return
        for id in range(1, self._axis_count + 1):
            if id in self._state:
                value = self._state[id]
            else:
                value = 0.0  # default
            profile.setStartAxisValue(self._device_id, id, value)
            if id in self._enabled_state:
                enabled = self._enabled_state[id]
            else:
                enabled = False
            profile.setStartAxisEnabled(self._device_id, id, enabled)

    def _create_ui(self):
        """Creates the UI elements."""
        if not Shiboken.isValid(self):
            return
        vjoy_proxy = gremlin.joystick_handling.VJoyProxy()
        self._spin_boxes.clear()
        row = 0
        vjoy_id = self.device.vjoy_id

        self._state.clear()
        self._grid_widgets.clear()
        self._grid_enabled.clear()
        gremlin.util.clear_layout(self.grid_layout)
        for input_id in self.device.axis_index_list():
            axis_name = self.device.get_axis_name(input_id)
            self.grid_layout.addWidget(QtWidgets.QLabel(axis_name), row, 0)

            value = self.settings.get_initial_vjoy_axis_value(self.device.vjoy_id, input_id)
            box = QFloatLineEdit()
            box.setRange(-1, 1)
            value = self.settings.get_initial_vjoy_axis_value(self.device.vjoy_id, input_id)
            box.setValue(value)
            box.data = input_id
            box.valueChanged.connect(self._create_value_cb(input_id))
            self._spin_boxes.append(box)

            self._state[input_id] = value
            self._grid_widgets[input_id] = box

            # frame.layout().addWidget(box)
            self.grid_layout.addWidget(box, row, 1)

            is_enabled = self.settings.get_vjoy_axis_enabled(vjoy_id, input_id)
            enabled_widget = QDataCheckbox("Enabled")
            enabled_widget.data = input_id
            enabled_widget.setChecked(is_enabled)
            enabled_widget.clicked.connect(self._enabled_changed)

            self._grid_enabled[input_id] = enabled_widget

            presets = [-1, -0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75, 1]

            container_widget = QtWidgets.QWidget()
            container_layout = QtWidgets.QHBoxLayout(container_widget)
            container_layout.addWidget(enabled_widget)
            for value in presets:
                widget = QDataPushButton(f"{value:0.3f}")
                widget.data = (row, value)  # (axis_id, value)
                widget.setToolTip(f"Sets to {value:0.3f}")
                widget.clicked.connect(self._handle_preset)
                container_layout.addWidget(widget)

            container_layout.addStretch()

            # self.grid_layout.addWidget(frame, row, 1)
            self.grid_layout.addWidget(container_widget, row, 2)
            row += 1
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 3)
        self.grid_layout.setColumnStretch(3, 2)
        vjoy_proxy.reset()

    def _populate_grid(self):
        """reload data into the widgets"""
        gremlin.util.InvokeUiMethod(self._populate_grid_ui)

    def _populate_grid_ui(self):
        """updates the usage grid based on current VJOY mappings"""
        for id in self._state:
            if Shiboken.isValid(self._grid_widgets[id]):
                with QtCore.QSignalBlocker(self._grid_widgets[id]):
                    value = self.getValue(id)
                    if value is not None:
                        self._grid_widgets[id].setValue(value)
            if Shiboken.isValid(self._grid_enabled[id]):
                with QtCore.QSignalBlocker(self._grid_enabled[id]):
                    enabled = self.getEnabled(id)
                    if enabled is None:
                        enabled = False
                    self._grid_enabled[id].setChecked(enabled)

    @QtCore.Slot(bool)
    def _enabled_changed(self, checked: bool):
        widget = self.sender()
        input_id = widget.data
        # self.settings.set_vjoy_axis_enabled(self.device.vjoy_id, input_id)
        self._enabled_state[input_id] = checked

    @QtCore.Slot()
    def _handle_preset(self):
        widget = self.sender()
        index, x = widget.data
        self._spin_boxes[index].setValue(x)

    def getValue(self, id: int) -> float:
        """gets the axis value"""
        if id in self._state:
            return self._state[id]
        return None

    def setValue(self, id: int, value: float):
        """sets the value of the axis"""
        gremlin.util.InvokeUiMethod(self._setValue_ui, id, value)

    def _setValue_ui(self, id: int, value: float):
        """sets the value of the axis - runs on UI thread"""
        if id in self._grid_widgets and Shiboken.isValid(self._grid_widgets[id]):
            self._grid_widgets[id].setValue(value)
            self._state[id] = value

    def getEnabled(self, id: int) -> bool:
        """get the enabled flag"""
        if id in self._enabled_state:
            return self._enabled_state[id]
        return None

    def setEnabled(self, id: int, value: bool):
        """sets the enabled state on the axis"""
        gremlin.util.InvokeUiMethod(self._setEnabled_ui, id, value)

    def _setEnabled_ui(self, id: int, value: bool):
        """sets enabled flag on widget - runs on ui thread"""
        self._enabled_state[id] = value
        if id in self._grid_enabled and Shiboken.isValid(self._grid_enabled[id]):
            with QtCore.QSignalBlocker(self._grid_enabled[id]):
                self._grid_enabled[id].setChecked(value)
                self._enabled_state[id] = value

    def _create_value_cb(self, axis_id):
        """Creates a callback function which updates axis values.

        :param axis_id id of the axis to change the value of
        :return callback customized for the given axis_id
        """
        return lambda x: self._update_axis_value(axis_id, x)

    def _update_axis_value(self, axis_id, value):
        """Updates an axis' default value.

        :param axis_id id of the axis to update
        :param value the value to update the axis to
        """

        self._state[axis_id] = value

        # self.settings.set_initial_vjoy_axis_value(
        #     self.device.vjoy_id,
        #     axis_id,
        #     value
        # )


class VirtualAsInputWidget(QtWidgets.QGroupBox):
    """Configure vJoy and Maestro virtual joysticks as profile inputs."""

    # Signal emitted when a change occurs
    changed = Signal(dict)  # (provider, device index) -> enabled

    def __init__(self, profile_settings, parent=None):
        """Creates a new instance.

        :param profile_data profile information read and modified by the
            widget
        :param parent the paren of this widget
        """
        super().__init__(parent)

        self.settings = profile_settings

        self.setTitle("Virtual as Input")
        self._virtual_widgets = {}  # (provider, device index) -> widget
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.virtual_layout = QtWidgets.QVBoxLayout()

        self._create_ui()

    def _create_ui(self):
        """Creates the UI to set physical input state."""
        if not Shiboken.isValid(self):
            return

        devices = gremlin.joystick_handling.virtual_input_candidates()
        for dev in sorted(devices, key=lambda dev: (dev.device_type, dev.name.casefold())):
            is_vjoy = dev.device_type == DeviceType.VJoy
            enabled = self.settings.getVirtualAsInput(dev)
            _, index = self.settings._virtual_input_key(dev, dev.device_type)
            label = f"{'vJoy' if is_vjoy else 'Maestro'}: {dev.name}"
            if isinstance(index, str):
                label += f" [{index}]"
            widget = QDataCheckbox(label, data=index, value=enabled, readonly=True)
            self._virtual_widgets[(dev.device_type, index)] = widget
            widget.setEnabled(enabled)
            if enabled and is_vjoy:
                settings = QDataPushButton("...", tooltip=f"Configure vJoy {index} settings", data=dev, callback=self._edit_dialog)
                self.virtual_layout.addWidget(getHContainer([widget, settings], widget_only=True))
            else:
                self.virtual_layout.addWidget(widget)

        self.virtual_layout.addWidget(QFailoverWidget())
        # Information label
        dialog_button = QDataPushButton(
            "Configure...", tooltip="Select vJoy and Maestro joysticks to use as inputs in this profile.", callback=self._open_dialog
        )
        self.virtual_layout.addWidget(getHContainer([dialog_button, "||"], widget_only=True))

        self.main_layout.addLayout(self.virtual_layout)

        self.main_layout.addStretch()

    def _edit_dialog(self, widget, device):
        """startup options for a given device"""
        self.dialog = VjoyDefaultsDialog(device, self.settings)
        self.dialog.exec()

    def _open_dialog(self):
        self._dialog = gremlin.input_item.VirtualAsInputDialog(self.settings, parent=self)
        self._dialog.accepted.connect(self._accepted)
        self._dialog.exec()

    def _accepted(self):
        virtual_map = self._dialog.virtual_map
        has_changes = False
        config = gremlin.config.Configuration()
        for (device_type, index), enabled in virtual_map.items():
            value = self.settings.getVirtualAsInput(index, device_type)
            if value != enabled:
                self.settings.setVirtualAsInput(index, enabled, device_type, emit=False)
                has_changes = True
                # if the device is newly enabled, force a device filter visibility update
                if enabled:
                    if device_type == DeviceType.VJoy:
                        dev = gremlin.joystick_handling.getDeviceFromVjoyId(index)
                    elif isinstance(index, str):
                        dev = gremlin.joystick_handling.getDevice(index)
                    else:
                        dev = gremlin.joystick_handling.maestro_info_from_index(index)
                    if dev:
                        config.setDeviceVisible(dev.device_guid, True)

        if has_changes:
            # Release vJoy handles before the shared event rebuilds the tabs.
            self.changed.emit(virtual_map)
            el = gremlin.event_handler.EventListener()
            el.virtual_as_input_changed.emit()
