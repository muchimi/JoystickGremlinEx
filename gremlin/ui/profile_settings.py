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


from PySide6 import QtCore, QtWidgets

import gremlin.event_handler
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.util
import psygnal
from psygnal import Signal
from gremlin.ui.qdatawidget import QDataWidget
from shiboken6 import Shiboken
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
        self.scroll_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Expanding)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        # Configure the scroll area
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)

        # Add the scroll area to the main layout
        self.main_layout.addWidget(self.scroll_area)

        self._create_ui()

    def refresh_ui(self, emit=False):
        """Refreshes the entire UI."""
        gremlin.ui.ui_common.clear_layout(self.scroll_layout)
        self._create_ui()
        if emit:
            self.changed.emit()

    def refresh(self, emit = True):
        self.refresh_ui(emit)

    @QtCore.Slot(int, bool)
    def vjoy_as_input_changed(self, vid : int, enabled : bool):
        ''' ask the UI to add a new tab for the vjoy device that was enabled '''
        if enabled:
            # ensure the VJOy device is released so another app can trigger UI events here
            vjoy = gremlin.joystick_handling.VJoyProxy()[vid]
            vjoy.ensure_released()
        el = gremlin.event_handler.EventListener()
        el.vjoy_as_input_changed.emit(vid, enabled)
        el.device_change_event.emit()
        


    def _create_ui(self):
        """Creates the UI elements of this widget."""
        # Default start mode selection
        if not Shiboken.isValid(self):
            return

        from functools import partial
        self.scroll_layout.addWidget(DefaultModeSelector(self.profile_settings))

        # Default macro delay
        self.scroll_layout.addWidget(DefaultDelay(self.profile_settings))

        # vJoy devices as inputs
        vjoy_as_input_widget = VJoyAsInputWidget(self.profile_settings)
        self.scroll_layout.addWidget(vjoy_as_input_widget)
        vjoy_as_input_widget.changed.connect(self.vjoy_as_input_changed)

        # vJoy axis initialization value setup
        widget = QtWidgets.QGroupBox(f"Profile Start Initial Values")
        box_layout = QtWidgets.QHBoxLayout()
        widget.setLayout(box_layout)

        grid_widget, grid_layout = gremlin.ui.ui_common.getGridContainer()
        max_col = 5
        row = 0
        col = 0

        box_layout.addWidget(grid_widget)
        box_layout.addStretch()

        for dev in sorted(gremlin.joystick_handling.vjoy_devices(), key=lambda x: x.vjoy_id):
            # Only show devices that are not treated as inputs
            if not dev.connected:
                # device is disconnected
                continue
            if self.profile_settings.vjoy_as_input.get(dev.vjoy_id) is True:
                continue


            dialog_widget = gremlin.ui.ui_common.Buttons.getEditWidget(callback = partial(self._edit_dialog, dev), label = f"Edit {dev.name} #{dev.vjoy_id}")
            grid_layout.addWidget(dialog_widget, row, col)
            col +=1
            if col == max_col:
                row+=1
                col = 0

            self.scroll_layout.addWidget(widget)

        grid_layout.addWidget(QtWidgets.QWidget(), 0, max_col)
        grid_layout.setColumnStretch(max_col, 2)
        

        self.scroll_layout.addStretch(1)

        # Information label
        label = QtWidgets.QLabel(
            "This tab allows setting default initialization of vJoy axis "
            "values. These values will be used when activating Gremlin."
        )
        background_color = gremlin.ui.ui_common.Color.highlightBackgroundColor()
        label.setStyleSheet(f"QLabel {{ background-color : {background_color}; }}")
        label.setWordWrap(True)
        label.setFrameShape(QtWidgets.QFrame.Box)
        label.setMargin(10)
        self.scroll_layout.addWidget(label)

    def _edit_dialog(self, device):
        self.dialog = VjoyDefaultsDialog(device, self.profile_settings)
        self.dialog.accepted.connect(self._accept_edit)
        self.dialog.rejected.connect(self._reject_edit)
        self.dialog.show()

    def _accept_edit(self):
        pass
    def _reject_edit(self):
        pass


class DefaultDelay(QtWidgets.QGroupBox):

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
        self._create_ui()

    def _create_ui(self):
        """Creates the UI of this widget."""
        if not Shiboken.isValid(self):
            return
        self.setTitle("Default Macro Action Delay")

        self.delay_value = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self.delay_value.setRange(0.0, 10.0)
        self.delay_value.setSingleStep(0.05)
        self.delay_value.setValue(self.profile_data.default_delay)
        self.delay_value.valueChanged.connect(self._update_delay)

        self.main_layout.addWidget(self.delay_value)
        self.main_layout.addStretch()

    def _update_delay(self, value):
        """Updates the value of the delay with the user input.

        Parameters
        ==========
        value : float
            New delay value to use between macro actions
        """
        self.profile_data.default_delay = value


class DefaultModeSelector(QtWidgets.QGroupBox):

    """Allows selecting the mode in which Gremlin starts."""

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data profile settings managed by the widget
        :param parent the parent of this widget
        """
        super().__init__(parent)

        self.profile_data = profile_data

        self.main_layout = QtWidgets.QHBoxLayout(self)
        self._create_ui()

    def _create_ui(self):
        """Creates the UI used to configure the startup mode."""
        if not Shiboken.isValid(self):
            return
        self.setTitle("Startup Mode")

        self.dropdown = gremlin.ui.ui_common.QComboBox()
        # self.dropdown.addItem("Use Heuristic")
        for mode in gremlin.profile.mode_list():
            self.dropdown.addItem(mode)
        start_mode = gremlin.shared_state.current_profile.get_start_mode()
        if start_mode:
            self.dropdown.setCurrentText(start_mode)
        self.dropdown.currentIndexChanged.connect(self._update_cb)

        self.main_layout.addWidget(self.dropdown)
        self.main_layout.addStretch()

    def _update_cb(self, index):
        """Handles changes in the mode selection drop down.

        :param index the index of the entry selected
        """
        mode = self.dropdown.currentText()
        gremlin.shared_state.current_profile.set_start_mode(mode)


class VjoyDefaultsDialog(gremlin.ui.ui_common.QRememberDialog):

    def __init__(self, device, settings, parent=None):
        super().__init__(self.__class__.__name__,parent = parent)

        main_layout = QtWidgets.QVBoxLayout(self)
        self.setWindowTitle(f"VJoy {device.vjoy_id} Profile Default Editor")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self._parent = parent # list view


        self.axis_widget = VJoyAxisDefaultsWidget(device, settings)
        self.axis_widget.from_profile(gremlin.shared_state.current_profile)


        self.button_widget = VJoyButtonsDefaultsWidget(device, settings)
        self.button_widget.from_profile(gremlin.shared_state.current_profile) # load current data



        # create axis tab
        self.tab_widget = QtWidgets.QTabWidget()
        self.tab_widget.addTab(self.axis_widget, "Axis Default")
        self.tab_widget.addTab(self.button_widget, "Button Default")

        self.device = device
        main_layout.addWidget(self.tab_widget)

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        widget, layout = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget], left_stretch=True)
        
        main_layout.addWidget(widget)

             
    def _ok_button_cb(self):
        ''' ok button pressed '''
        profile = gremlin.shared_state.current_profile
        # save the data to the profile
        self.axis_widget.to_profile(profile)
        self.button_widget.to_profile(profile)
        self.accept()   

    def _cancel_button_cb(self):
        ''' cancel button pressed '''
        self.reject()        


class VJoyButtonsDefaultsWidget(QtWidgets.QWidget):

    """UI widget allowing modification of button initialization values."""

    def __init__(self, device, settings, parent=None):
        super().__init__(parent)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.grid_widget = gremlin.ui.ui_common.QButtonGrid(device)
        self.main_layout.addWidget(self.grid_widget)


        on_widget = QtWidgets.QPushButton("All On")
        on_widget.setToolTip("Sets all buttons to off")
        on_widget.clicked.connect(self._all_on)
        off_widget = QtWidgets.QPushButton("All Off")
        off_widget.setToolTip("Sets all buttons to off")
        off_widget.clicked.connect(self._all_off)
        
        button_container_widget, _ = gremlin.ui.ui_common.getHContainer([on_widget, off_widget], left_stretch=True)
        self.main_layout.addWidget(button_container_widget)
        

    def _all_on(self):
        self.grid_widget.all_on()

    def _all_off(self):
        self.grid_widget.all_off()

    def from_profile(self, profile):
        ''' load data from the current profile '''
        self.grid_widget.from_profile(gremlin.shared_state.current_profile)

    def to_profile(self, profile):
        ''' save data to the current profile'''
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

        assert device.is_virtual and device.vjoy_id > 0,"Device provided is not a VJOY device"
        self.device : dinput.DeviceSummary = device
        self._device_guid = device.device_guid
        self._device_id = device.device_id
        self._axis_count = device.axis_count
        
        self.settings = settings

        self.main_layout = QtWidgets.QVBoxLayout(self)


        self.grid_layout = QtWidgets.QGridLayout(self)
        self.grid_layout.setColumnMinimumWidth(0, 100)
        self.grid_layout.setColumnStretch(2, 1)
        self._state = {}  # map of [axis: int] to float 
        self._enabled_state = {} # map of [axi: int] to bool, true if the widget is enabled

        self._grid_widgets = {} # map of [axis: int] to floatinput widget
        self._grid_enabled = {} # map of [axis: int] to enabled widget

        self._spin_boxes = []

        self.main_layout.addLayout(self.grid_layout)


        self._create_ui()


        # helper commands 

        enabled_widget = QtWidgets.QPushButton("All Enabled")
        enabled_widget.setToolTip("Sets all axes to enabled")
        enabled_widget.clicked.connect(self._all_enabled)

        disabled_widget = QtWidgets.QPushButton("All Disabled")
        disabled_widget.setToolTip("Sets all axes to disabled")
        disabled_widget.clicked.connect(self._all_disabled)

        min_widget =  QtWidgets.QPushButton("All Min")
        min_widget.setToolTip("Sets all axes to minimum")
        min_widget.clicked.connect(self._all_min)

        max_widget =  QtWidgets.QPushButton("All Max")
        max_widget.setToolTip("Sets all axes to maximum")
        max_widget.clicked.connect(self._all_max)

        zero_widget = QtWidgets.QPushButton("All Center")
        zero_widget.setToolTip("Sets all axes to center")
        zero_widget.clicked.connect(self._all_zero)


        widgets = [enabled_widget, 
                   disabled_widget,
                   " ",
                   min_widget,
                   zero_widget,
                   max_widget]  

        button_container_widget, _ = gremlin.ui.ui_common.getHContainer(widgets, left_stretch=True)
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
        ''' reads the data from the current profile '''
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
        ''' saves the data to the current profile '''
        if not self.device:
            return
        for id in range(1, self._axis_count + 1):
            if id in self._state:
                value = self._state[id]
            else:
                value = 0.0 # default 
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
            frame = gremlin.ui.ui_common.QBoxFrame()
            frame.setStyleSheet(f"border: 2px solid {gremlin.ui.ui_common.Color.selectColor()};")
            frame.setLayout(QtWidgets.QHBoxLayout())

            box = gremlin.ui.ui_common.QFloatLineEdit()
            box.setRange(-1, 1)
            value = self.settings.get_initial_vjoy_axis_value(self.device.vjoy_id, input_id)
            box.setValue(value)
            box.data = input_id
            box.valueChanged.connect(self._create_value_cb(input_id))
            self._spin_boxes.append(box)

            self._state[input_id] = value
            self._grid_widgets[input_id] = box
            

            frame.layout().addWidget(box)

            is_enabled = self.settings.get_vjoy_axis_enabled(vjoy_id, input_id)
            enabled_widget = gremlin.ui.ui_common.QDataCheckbox("Enabled")
            enabled_widget.data = input_id
            enabled_widget.setChecked(is_enabled)
            enabled_widget.clicked.connect(self._enabled_changed)

            self._grid_enabled[input_id] = enabled_widget
            

            presets = [-1,-0.75,-0.5,-0.25,0,0.25,0.5,0.75,1]

            container_widget = QtWidgets.QWidget()
            container_layout = QtWidgets.QHBoxLayout(container_widget)
            container_layout.addWidget(enabled_widget)
            for value in presets:
                widget = gremlin.ui.ui_common.QDataPushButton(f"{value:0.3f}")
                widget.data = (row, value) # (axis_id, value)
                widget.setToolTip(f"Sets to {value:0.3f}")
                widget.clicked.connect(self._handle_preset)
                container_layout.addWidget(widget)
                

            container_layout.addStretch()

            self.grid_layout.addWidget(frame, row, 1)
            self.grid_layout.addWidget(container_widget, row, 2)
            row += 1
        self.grid_layout.addWidget(QtWidgets.QWidget(), 0, 3)
        self.grid_layout.setColumnStretch(3,2)
        vjoy_proxy.reset()

    def _populate_grid(self):
        ''' reload data into the widgets '''
        gremlin.util.InvokeUiMethod(self._populate_grid_ui)

    def _populate_grid_ui(self):
        ''' updates the usage grid based on current VJOY mappings '''
        for id in self._state:
            if Shiboken.isValid(self._grid_widgets[id]):
                with QtCore.QSignalBlocker(self._grid_widgets[id]):
                    value = self.getValue(id)
                    if not value is None:
                        self._grid_widgets[id].setValue(value)
            if Shiboken.isValid(self._grid_enabled[id]):
                with QtCore.QSignalBlocker(self._grid_enabled[id]):
                    enabled = self.getEnabled(id)
                    if enabled is None:
                        enabled = False
                    self._grid_enabled[id].setChecked(enabled)

        


    @QtCore.Slot(bool)
    def _enabled_changed(self, checked):
        widget = self.sender()
        input_id = widget.data
        # self.settings.set_vjoy_axis_enabled(self.device.vjoy_id, input_id)
        self._enabled_state[input_id] = checked

    @QtCore.Slot()
    def _handle_preset(self):
        widget = self.sender()
        index, x = widget.data
        self._spin_boxes[index].setValue(x)
        
    def getValue(self, id : int) -> float:
        ''' gets the axis value '''
        if id in self._state:
            return self._state[id]
        return None
    
    
    def setValue(self, id : int, value : float):
        ''' sets the value of the axis '''
        gremlin.util.InvokeUiMethod(self._setValue_ui, id, value)
    
    def _setValue_ui(self, id : int, value : float):
        ''' sets the value of the axis - runs on UI thread '''
        if id in self._grid_widgets and Shiboken.isValid(self._grid_widgets[id]):
            self._grid_widgets[id].setValue(value)
            self._state[id] = value

    def getEnabled(self, id : int) -> bool:
        ''' get the enabled flag '''
        if id in self._enabled_state:
            return self._enabled_state[id]
        return None
    
    def setEnabled(self, id: int, value : bool):
        ''' sets the enabled state on the axis '''
        gremlin.util.InvokeUiMethod(self._setEnabled_ui, id, value)
    
    def _setEnabled_ui(self, id: int, value : bool):
        ''' sets enabled flag on widget - runs on ui thread'''
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


class VJoyAsInputWidget(QtWidgets.QGroupBox):

    """Configures which vJoy devices are treated as physical inputs."""

    # Signal emitted when a change occurs
    changed = Signal(int, bool) # (vid, enabled)

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data profile information read and modified by the
            widget
        :param parent the paren of this widget
        """
        super().__init__(parent)

        self.profile_data = profile_data

        self.setTitle("vJoy as Input")
        self.main_layout = QtWidgets. QHBoxLayout(self)
        self.vjoy_layout = QtWidgets.QVBoxLayout()

        self._create_ui()

    def _create_ui(self):
        """Creates the UI to set physical input state."""
        if not Shiboken.isValid(self):
            return
        
        for dev in sorted(gremlin.joystick_handling.vjoy_devices(),key=lambda x: x.vjoy_id):
            widget = gremlin.ui.ui_common.QDataCheckbox(dev.name, data = dev.vjoy_id)
            if self.profile_data.vjoy_as_input.get(dev.vjoy_id, False):
                widget.setChecked(True)
            widget.clicked.connect(self._state_changed)
            self.vjoy_layout.addWidget(widget)

        # Information label
        label = QtWidgets.QLabel(
            "Declaring a vJoy device as an input device will allow it to be"
            "used like a physical device , i.e. it can be forwarded to other"
            "vJoy devices. However, this also means that it won't be available"
            " as an output device."
        )

        background_color = gremlin.ui.ui_common.Color.highlightBackgroundColor()
        label.setStyleSheet(f"QLabel {{ background-color : {background_color}; }}")
        
        label.setWordWrap(True)
        label.setFrameShape(QtWidgets.QFrame.Box)
        label.setMargin(10)
        label.setMinimumWidth(300)

        widget, layout = gremlin.ui.ui_common.getVContainer(label)

        self.main_layout.addLayout(self.vjoy_layout)
        self.main_layout.addWidget(widget)
        self.main_layout.addStretch()

    @QtCore.Slot(bool)
    def _state_changed(self, checked : bool):
        widget = self.sender()
        vid : int = widget.data
        self.profile_data.vjoy_as_input[vid] = checked
        self.changed.emit(vid, checked)
    
    