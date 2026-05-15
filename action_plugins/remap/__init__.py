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


import logging
import threading
import time
from lxml import etree as ElementTree
import traceback
import gremlin.joystick_handling
from gremlin.util import load_icon
from PySide6 import QtWidgets

from gremlin.input_types import InputType
from gremlin import input_devices, joystick_handling, util
from gremlin.error import ProfileError
import gremlin.plugin_manager
from gremlin.profile import safe_format, safe_read
from gremlin.ui import ui_common
import gremlin.input_item
import os
from gremlin.util import *
import gremlin.event_handler
import gremlin.util

syslog = logging.getLogger("system")

class RemapWidget(gremlin.input_item.AbstractActionWidget):

    """Dialog which allows the selection of a vJoy output to use as
    as the remapping for the currently selected input.
    """

    # Mapping from types to display names
    type_to_name_map = {
        InputType.JoystickAxis: "Axis",
        InputType.JoystickButton: "Button",
        InputType.JoystickHat: "Hat",
        InputType.Keyboard: "Button",
        InputType.Midi: "Button",
        InputType.Keyboard: "Button",
        InputType.OpenSoundControl: "Button",
    }
    name_to_type_map = {
        "Axis": InputType.JoystickAxis,
        "Button": InputType.JoystickButton,
        "Hat": InputType.JoystickHat,
    }

    def __init__(self, action_data, parent=None):
        """Creates a new RemapWidget.

        :param action_data profile data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)
        assert(isinstance(action_data, Remap))

    def _create_ui(self):
        """Creates the UI components."""
        import gremlin.shared_state
        if not Shiboken.isValid(self):
            return
        if not gremlin.shared_state.vjoy_enabled:
            self.main_layout.addWidget(QtWidgets.QLabel("VJOY is not available.  Ensure VJOY is installed and configured."))
            return

        self._last_input_type = self.action_data.input_type
        self._last_button_id = -1 # no last button selected

        input_types = {
            InputType.Keyboard: [
                InputType.JoystickButton
            ],
            InputType.KeyboardLatched: [
                InputType.JoystickButton
            ],
            InputType.Midi: [
                InputType.JoystickAxis,
                InputType.JoystickButton
            ],
            InputType.OpenSoundControl: [
                InputType.JoystickAxis,
                InputType.JoystickButton
            ],
            InputType.JoystickAxis: [
                InputType.JoystickAxis,
                InputType.JoystickButton
            ],
            InputType.JoystickButton: [
                InputType.JoystickButton
            ],
            InputType.JoystickHat: [
                InputType.JoystickButton,
                InputType.JoystickHat
            ]

        }
        input_type = self.action_data.get_input_type()

        self.vjoy_selector = ui_common.VJoySelector(
            lambda x: self.save_changes(),  # handler when selection changes
            input_types[input_type],
            self.action_data.get_settings().vjoy_as_input
        )

        self.vjoy_selector.input_changed.connect(self._input_changed)

        self.main_layout.addWidget(self.vjoy_selector)

        # Create UI widgets for absolute / relative axis modes if the remap
        # action is being added to an axis input type
        if self.action_data.is_axis:
            self.remap_type_widget = QtWidgets.QWidget()
            self.remap_type_layout = QtWidgets.QHBoxLayout(self.remap_type_widget)


            self.absolute_checkbox = QtWidgets.QRadioButton("Absolute")
            self.absolute_checkbox.setChecked(True)
            self.relative_checkbox = QtWidgets.QRadioButton("Relative")
            self.relative_scaling = ui_common.DynamicDoubleSpinBox()
            self.relative_scaling.setRange(0,1000)

            self.remap_type_layout.addStretch()
            self.remap_type_layout.addWidget(self.absolute_checkbox)
            self.remap_type_layout.addWidget(self.relative_checkbox)
            self.remap_type_layout.addWidget(self.relative_scaling)
            self.remap_type_layout.addWidget(QtWidgets.QLabel("Scale"))

            self.remap_type_widget.hide()
            self.main_layout.addWidget(self.remap_type_widget)

            # The widgets should only be shown when we actually map to an axis
            if self.action_data.input_type == InputType.JoystickAxis:
                self.remap_type_widget.show()

        # display a warning that this is a legacy mapper
        warning_container = QtWidgets.QWidget()
        warning_layout = QtWidgets.QHBoxLayout(warning_container)
        warning_color = gremlin.ui.ui_common.Color.warningColor()
        warning_widget = gremlin.ui.ui_common.QIconLabel("ph.shield-warning-fill",use_qta=True,icon_color=QtGui.QColor(warning_color),text="Legacy mapper - consider using <i>VJoy Remap</i> for additional functionality", use_wrap=False)
        warning_layout.addWidget(warning_widget)
        warning_layout.addStretch()
        self.main_layout.addWidget(warning_container)
        self.main_layout.setContentsMargins(0, 0, 0, 0)


    @QtCore.Slot()
    def _input_changed(self):
        ''' called when the input changed '''
        vjoy_data = self.vjoy_selector.get_selection()
        input_type = vjoy_data["input_type"]
        if input_type != self._last_input_type:

            self._last_input_type = input_type
            self.action_data.vjoy_id = vjoy_data["device_id"]
            self.action_data.vjoy_input_id = vjoy_data["input_id"]
            self.action_data.input_type = input_type

           # Signal changes
            self._notify_button_changed()



    def _populate_ui(self):
        """Populates the UI components."""
        # Get the appropriate vjoy device identifier
        vjoy_dev_id = 0
        if self.action_data.vjoy_id not in [0, None]:
            vjoy_dev_id = self.action_data.vjoy_id

        # Get the input type which can change depending on the container used
        input_type = self.action_data.input_type


        if self.action_data.parent.tag == "hat_buttons":
            input_type = InputType.JoystickButton

        # Handle obscure bug which causes the action_data to contain no
        # input_type information
        if input_type is None:
            input_type = InputType.JoystickButton
            log_sys_warn("None as input type encountered")

        # If no valid input item is selected get the next unused one
        if self.action_data.vjoy_input_id in [0, None]:
            free_inputs = self._get_profile_root().list_unused_vjoy_inputs()

            input_name = self.type_to_name_map[input_type].lower()
            input_type = self.name_to_type_map[input_name.capitalize()]
            if vjoy_dev_id == 0:
                vjoy_dev_id = sorted(free_inputs.keys())[0]
            if vjoy_dev_id in free_inputs and input_name in free_inputs[vjoy_dev_id]:
                input_list = free_inputs[vjoy_dev_id][input_name]
            else:
                input_list = []
            # If we have an unused item use it, otherwise use the first one
            if input_list:
                vjoy_input_id = input_list[0]
            else:
                vjoy_input_id = 1
        # If a valid input item is present use it
        else:
            vjoy_input_id = self.action_data.vjoy_input_id

        try:
            self.vjoy_selector.set_selection(
                input_type,
                vjoy_dev_id,
                vjoy_input_id
            )

            if self.action_data.is_axis:
                if self.action_data.axis_mode == "absolute":
                    self.absolute_checkbox.setChecked(True)
                else:
                    self.relative_checkbox.setChecked(True)
                self.relative_scaling.setValue(self.action_data.axis_scaling)

                self.absolute_checkbox.clicked.connect(self.save_changes)
                self.relative_checkbox.clicked.connect(self.save_changes)
                self.relative_scaling.valueChanged.connect(self.save_changes)

            # Save changes so the UI updates properly
            self.save_changes()
        except Exception as err:
            util.display_error(
                f"A needed vJoy device is not accessible:\n\n" +
                "Default values have been set for the input, but they are "
                "not what has been specified."
            )
            syslog.error(f"{err}\n{traceback.format_exc()}")

    def save_changes(self):
        """Saves UI contents to the profile data storage."""
        # Store remap data
        try:
            vjoy_data = self.vjoy_selector.get_selection()
            # input_type_changed = \
            #     self.action_data.input_type != vjoy_data["input_type"]

            current_id = self.action_data.vjoy_input_id
            vjoy_id = vjoy_data["device_id"]

            self.action_data.vjoy_id = vjoy_id
            self.action_data.vjoy_input_id = vjoy_data["input_id"]
            self.action_data.input_type = vjoy_data["input_type"]

            new_id = vjoy_data["input_id"]

            if self.action_data.is_axis:
                self.action_data.axis_mode = "absolute"
                if self.relative_checkbox.isChecked():
                    self.action_data.axis_mode = "relative"
                self.action_data.axis_scaling = self.relative_scaling.value()

            # Signal changes
            self._notify_button_changed()
            self.notify_device_changed(emit_profile_changed=False)

        except gremlin.error.GremlinError as e:
            log_sys_error(e)



    def _notify_button_changed(self):
          if self.action_data.input_type == InputType.JoystickButton:
                verbose = gremlin.config.Configuration().verbose_mode_vjoy
                button_id =self.action_data.vjoy_input_id
                vjoy_id = self.action_data.vjoy_id
                el = gremlin.event_handler.EventListener()

                if self._last_button_id != -1 and self._last_button_id != button_id:
                    # clear the old button if it was previously selected
                    if verbose: syslog.info(f"LEGACY MAP: send button clear {vjoy_id} {self._last_button_id} {self.action_data.id}")
                    el.set_vjoy_button_usage.emit(vjoy_id, self._last_button_id, False, self.action_data.id)
                # send select
                self._last_button_id = button_id
                if verbose: syslog.info(f"LEGACY MAP: send button select {vjoy_id} {button_id} {self.action_data.id}")
                el.set_vjoy_button_usage.emit(vjoy_id, button_id, True, self.action_data.id)


    def notify_device_changed(self, emit_profile_changed = True, emit_icon = True):
        state = gremlin.joystick_handling.VJoyUsageState()
        el = gremlin.event_handler.EventListener()
        event = gremlin.event_handler.DeviceChangeEvent()
        event.device_guid = state._active_device_guid
        event.device_name = state._active_device_name
        event.device_input_type = self.action_data.input_type
        event.device_input_id = state._active_device_input_id
        event.vjoy_id = self.action_data.vjoy_id
        event.vjoy_input_id = self.action_data.vjoy_input_id
        event.source = self.action_data
        if emit_profile_changed:
            el.profile_device_changed.emit(event)
        if emit_icon:
            el.icon_changed.emit(event)


class RemapFunctor(gremlin.base_profile.AbstractFunctor):

    """Executes a remap action when called."""

    def __init__(self, action, parent = None):
        super().__init__(action, parent)
        self.vjoy_id = action.vjoy_id
        self.vjoy_input_id = action.vjoy_input_id
        self.input_type = action.input_type
        self.axis_mode = action.axis_mode
        self.axis_scaling = action.axis_scaling
        self.is_axis = action.is_axis

        self.needs_auto_release = self._check_for_auto_release(action)
        self.thread_running = False
        self.should_stop_thread = False
        self.thread_last_update = time.time()
        self.thread = None
        self.axis_delta_value = 0.0
        self.axis_value = 0.0
        self.test = False

    def process_event(self, event, action_value, extra_data = None):
        input_type = event.getInputType()
        if event.is_axis:
            if event.curve_value is not None:
                value = event.curve_value
            else:
                value = action_value.current
            if event.is_repeater:
                value = event.value

            if self.axis_mode == "absolute":
                if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                    joystick_handling.VJoyProxy()[self.vjoy_id].axis(self.vjoy_input_id).value = value
            else:
                self.should_stop_thread = abs(event.value) < 0.05
                self.axis_delta_value = \
                    value.current * (self.axis_scaling / 1000.0)
                self.thread_last_update = time.time()
                if self.thread_running is False:
                    if isinstance(self.thread, threading.Thread):
                        self.thread.join()
                    self.thread = threading.Thread(target=self.relative_axis_thread, daemon=False)
                    self.thread.name = "REMAP relative axis"
                    self.thread.start()

        elif input_type == InputType.JoystickButton:
            if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                if event.event_type in [InputType.JoystickButton, InputType.Keyboard] \
                        and event.is_pressed \
                        and self.needs_auto_release:
                    input_devices.CallbackActions().register_button_release((self.vjoy_id, self.vjoy_input_id),event)
                    joystick_handling.VJoyProxy()[self.vjoy_id].button(self.vjoy_input_id).is_pressed = event.is_pressed



        elif input_type == InputType.JoystickHat:
            if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
                joystick_handling.VJoyProxy()[self.vjoy_id].hat(self.vjoy_input_id).direction = value.current

        return True

    def relative_axis_thread(self):
        if gremlin.joystick_handling.is_vjoy_connected(self.vjoy_id):
            self.thread_running = True
            vjoy_dev = joystick_handling.VJoyProxy()[self.vjoy_id]
            self.axis_value = vjoy_dev.axis(self.vjoy_input_id).value
            while self.thread_running:
                try:
                    # If the vjoy value has was changed from what we set it to
                    # in the last iteration, terminate the thread
                    change = vjoy_dev.axis(self.vjoy_input_id).value - self.axis_value
                    if abs(change) > 0.0001:
                        self.thread_running = False
                        self.should_stop_thread = True
                        return

                    self.axis_value = max(
                        -1.0,
                        min(1.0, self.axis_value + self.axis_delta_value)
                    )
                    vjoy_dev.axis(self.vjoy_input_id).value = self.axis_value

                    if self.should_stop_thread and \
                            self.thread_last_update + 1.0 < time.time():
                        self.thread_running = False
                    time.sleep(0.01)
                except gremlin.error.VJoyError:
                    self.thread_running = False




class Remap(gremlin.base_profile.AbstractAction):
    """Action remapping physical joystick inputs to vJoy inputs."""

    name = "Remap"
    tag = "remap"
    hint = '''Legacy VJOY mapper.
Use Vjoy Remap instead.'''

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, True)
    input_types = [
        InputType.JoystickAxis,
        InputType.OpenSoundControl,
        InputType.JoystickButton,
        InputType.JoystickHat,
        InputType.Keyboard,
        InputType.Midi,
    ]


    functor = RemapFunctor
    widget = RemapWidget

    def __init__(self, parent):
        """Creates a new instance.

        :param parent the container to which this action belongs
        """
        super().__init__(parent)

        self.setPriority(9)
        # Set vjoy ids to None so we know to pick the next best one
        # automatically
        self.parent = parent
        self._vjoy_id = 1
        self._vjoy_input_id = None
        input_type = self.get_input_type()
        self._input_type = input_type

        self.axis_mode = "absolute"
        self.axis_scaling = 1.0

    def actionDeleted(self):
        ''' called if the action is being deleted '''
        if self._input_type == InputType.JoystickButton:
            el = gremlin.event_handler.EventListener()
            el.set_vjoy_button_usage.emit(self._vjoy_id, self._vjoy_input_id, False, self.id)


    @property
    def vjoy_input_id(self) -> int:
        return self._vjoy_input_id
    @vjoy_input_id.setter
    def vjoy_input_id(self, value : int):
        if value != self._vjoy_input_id:
            if self._input_type == InputType.JoystickButton:
                el = gremlin.event_handler.EventListener()
                el.set_vjoy_button_usage.emit(self._vjoy_id, self._vjoy_input_id, False, self.id)
                self._vjoy_input_id = value
                el.set_vjoy_button_usage.emit(self._vjoy_id, self._vjoy_input_id, False, self.id)
            else:
                self._vjoy_input_id = value

    @property
    def vjoy_id(self) -> int:
        return self._vjoy_id
    @vjoy_id.setter
    def vjoy_id(self, value : int):
        if value != self._vjoy_id:
            if self._input_type == InputType.JoystickButton:
                el = gremlin.event_handler.EventListener()
                el.set_vjoy_button_usage.emit(self._vjoy_id, self._vjoy_input_id, False, self.id)
                self._vjoy_id = value
                el.set_vjoy_button_usage.emit(self._vjoy_id, self._vjoy_input_id, True, self.id)
            else:
                self._vjoy_id = value


    @property
    def is_axis(self):
        return self.input_is_axis()

    @property
    def input_type(self) -> InputType:
        return self._input_type
    @input_type.setter
    def input_type(self, value : InputType):
        if self._input_type != value:
            if self._input_type == InputType.JoystickButton:
                el = gremlin.event_handler.EventListener()
                el.vjoy_button_usage.emit(self.vjoy_id,  self._vjoy_input_id, False, self.id)

            self._input_type = value

            if self._input_type == InputType.JoystickButton:
                el = gremlin.event_handler.EventListener()
                el.vjoy_button_usage.emit(self.vjoy_id,  self._vjoy_input_id, True, self.id)


    def display_name(self):
        ''' returns a display string for the current configuration '''
        input_string = "Axis"
        if self.input_type == InputType.JoystickButton:
            input_string = "Button"
        elif self.input_type == InputType.JoystickHat:
            input_string = "Hat"
        return f"Remap (legacy): Vjoy [{self.vjoy_id}] Mode: [{input_string}] Output: [{self.vjoy_input_id}]"

    def icon(self):
        """Returns the icon corresponding to the remapped input.

        :return icon representing the remap action
        """
        import gremlin.shared_state
        is_dark = gremlin.shared_state.is_dark_theme
        # Do not return a valid icon if the input id itself is invalid



        if self.vjoy_input_id is None:
            input_string = None
        else:
            input_string = None
            dark_stub = "dark_" if is_dark else ""
            match self.input_type:
                case InputType.JoystickButton:
                    input_string = "button"
                    suffix = f"{self.vjoy_input_id:03d}"
                    fallback = "mdi.gesture-tap-button"

                case InputType.JoystickHat:
                    input_string = "hat"
                    input_string = "mdi.axis-arrow"
                    fallback = "mdi.axis-arrow"

                case InputType.JoystickAxis:
                    input_string = "axis"
                    match self._vjoy_input_id:
                        case 1:
                            suffix = "x"
                        case 2:
                            suffix = "y"
                        case 3:
                            suffix = "z"
                        case 4:
                            suffix = "rx"
                        case 5:
                            suffix = "ry"
                        case 6:
                            suffix = "rz"
                        case 7:
                            suffix = "s1"
                        case 8:
                            suffix = "s2"

            if input_string:
                icon_file = f"{dark_stub}icon_{input_string}_{suffix}.png"
                icon_path = gremlin.util.find_icon(icon_file)
                if os.path.isfile(icon_path):
                    return icon_file

            log_sys_warn(f"Icon file: {icon_file}")
            log_sys_warn(f"Warning: unable to determine icon type: {self.input_type} for id {self.vjoy_input_id}")
            return fallback
        return None



    def requires_virtual_button(self):
        """Returns whether or not the action requires an activation condition.

        :return True if a virtual button condition is required, False otherwise
        """
        mapped_input_type = self.get_input_type()



        if mapped_input_type in (InputType.JoystickButton, InputType.Keyboard):
            return False
        elif self.is_axis:
            if self.input_type == InputType.JoystickAxis:
                return False
            else:
                # button or hat requires a virtual button setup
                return True
        elif mapped_input_type == InputType.JoystickHat:
            if self.input_type == InputType.JoystickHat:
                return False
            else:
                return True

    def _parse_xml(self, node, data = None, extra_data = None):
        """Populates the data storage with data from the XML node.

        :param node XML node with which to populate the storage
        """
        try:

            self._vjoy_id = safe_read(node, "vjoy", int, 1)

            if "axis" in node.attrib:
                self.input_type = InputType.JoystickAxis
                self.vjoy_input_id = safe_read(node, "axis", int, 1)
            elif "button" in node.attrib:
                self.input_type = InputType.JoystickButton
                self.vjoy_input_id = safe_read(node, "button", int, 1)

            elif "hat" in node.attrib:
                self.input_type = InputType.JoystickHat
                self.vjoy_input_id = safe_read(node, "hat", int, 1)
            elif "keyboard" in node.attrib:
                self.input_type = InputType.Keyboard
                self.vjoy_input_id = safe_read(node, "button", int, 1)
            else:
                raise gremlin.error.GremlinError(
                    f"Invalid remap type provided: {node.attrib}"
                )


            if self.get_input_type() == InputType.JoystickAxis and self.input_type == InputType.JoystickAxis:
                self.axis_mode = safe_read(node, "axis-type", str, "absolute")
                self.axis_scaling = safe_read(node, "axis-scaling", float, 1.0)
        except ProfileError:
            self.vjoy_input_id = None
            self.vjoy_id = None

    def _generate_xml(self):
        """Returns an XML node encoding this action's data.

        :return XML node containing the action's data
        """
        node = ElementTree.Element("remap")
        node.set("vjoy", str(self.vjoy_id))
        if self.input_type == InputType.Keyboard:
            node.set(
                InputType.to_string(InputType.JoystickButton),
                str(self.vjoy_input_id)
            )
        else:
            node.set(
                InputType.to_string(self.input_type),
                str(self.vjoy_input_id)
            )

        if self.get_input_type() == InputType.JoystickAxis and \
                self.input_type == InputType.JoystickAxis:
            node.set("axis-type", safe_format(self.axis_mode, str))
            node.set("axis-scaling", safe_format(self.axis_scaling, float))

        return node

    def _is_valid(self):
        """Returns whether or not the action is configured properly.

        :return True if the action is configured correctly, False otherwise
        """
        return not(self.vjoy_id is None or self.vjoy_input_id is None)

    def _get_output_name(self) -> str:
        return InputType.to_display_name(self._input_type)


    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell

        table = ReportTable(cellpadding=4)
        table.addField("Vjoy Device", self.vjoy_id)
        table.addField("Output Type:", self._get_output_name())
        table.addField("Output ID", self.vjoy_input_id)


        return table.to_html()


version = 1
name = "remap"
create = Remap
