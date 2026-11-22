# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
#
# Written for Gremlin Ex by Muchimi
# Some portions are derived from the original 2019 Joystick Gremlin by Lionel Ott and other contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""action that manages the remote control profile state at runtime"""

from lxml import etree
from PySide6 import QtCore

import gremlin.base_profile
import gremlin.input_item
from gremlin.event_handler import Event
from gremlin.input_devices import CallbackActions
from gremlin.input_types import InputType
from gremlin.remote import (
    ClientOperation,
    OutputMode,
    RemoteClientOptionsWidget,
    SelectionBehavior,
    read_client_selection,
    remote_control,
    write_client_selection,
)
from gremlin.ui.ui_common import QExecuteWidget
from gremlin.util import safe_format, safe_read


class RemoteClientWidget(gremlin.input_item.AbstractActionWidget):
    def _create_ui(self):
        action = self.action_data
        self._options = RemoteClientOptionsWidget(
            action.operation, action.output_mode, action.selection, self, behavior=action.behavior
        )
        self._options.changed.connect(self._options_changed)
        self.main_layout.addWidget(self._options)
        self._execute_widget = QExecuteWidget(action.exec_on_press, action.exec_on_release)
        self._execute_widget.setToolTip("Hold always starts on press and ends on release.")
        self._execute_widget.valueChanged.connect(self._execute_changed)
        self.main_layout.addWidget(self._execute_widget)

    def _populate_ui(self):
        self._execute_widget.setEnabled(not self.action_data.holds_client_filter)

    @QtCore.Slot()
    def _options_changed(self):
        action = self.action_data
        had_output = action.hasOutput()
        action.operation = self._options.operation
        action.output_mode = self._options.output_mode
        action.selection = self._options.selection
        action.behavior = self._options.behavior
        self._populate_ui()
        self._notify_modified(had_output)

    @QtCore.Slot(bool, bool)
    def _execute_changed(self, on_press, on_release):
        action = self.action_data
        had_output = action.hasOutput()
        action.exec_on_press = on_press
        action.exec_on_release = on_release
        self._notify_modified(had_output)

    def _notify_modified(self, had_output):
        if self.action_data.hasOutput() != had_output:
            self.action_data.fireIconChanged()
        self.action_modified.emit()


class RemoteClientFunctor(gremlin.base_profile.AbstractFunctor):
    def __init__(self, action, parent=None):
        super().__init__(action, parent)
        self._press_hold = None
        self._toggle_hold = None

    def process_event(self, event, value, extra_data=None):
        action = self.action_data
        operation = action.operation
        # Raw hats emit a release for the old position and a press for the new
        # one, including neutral. Only actual directions are triggers.
        if event.event_type == InputType.JoystickHat and event.value in (False, (0, 0)):
            self._release_press(self._press_hold)
            return True
        pressed = event.is_pressed
        if not pressed:
            self._release_press(self._press_hold)

        if action.holds_client_filter:
            if not pressed:
                return True
            addresses = None
            if operation is ClientOperation.Select:
                addresses = action.selection or None
            elif operation is ClientOperation.DisableAll:
                addresses = frozenset()
            self._start_override(event, extra_data, addresses)
        elif not (action.exec_on_press if pressed else action.exec_on_release):
            return True
        elif operation is ClientOperation.Select and action.behavior is SelectionBehavior.Toggle:
            if pressed:
                self._start_override(event, extra_data, action.selection or None, toggle=True)
            else:
                self._toggle_override(object(), action.selection or None)
        else:
            remote_control.applyClientOperation(operation, action.selection)
        remote_control.applyOutputMode(action.output_mode)
        return True

    def _start_override(self, event, extra_data, addresses, *, toggle=False):
        if self._press_hold is not None:
            return
        hold = object()
        self._press_hold = hold

        if toggle:
            self._toggle_override(hold, addresses)
        else:
            remote_control.beginClientOverride(hold, addresses)

        def release():
            self._release_press(hold)

        # Also register the physical release in case a condition or a mode change
        # prevents the release from reaching the action graph.
        callbacks = CallbackActions()
        latched_key = (extra_data or event.extra_data or {}).get("latched_key")
        if latched_key:
            for key in latched_key.getKeys():
                callbacks.register_callback(release, Event.from_key(key))
        else:
            if event.is_virtual_button and self.action_data.hardware_raw_input_type == InputType.JoystickHat:
                event = event.clone()
                event.event_type = InputType.JoystickHat
                event.identifier = self.action_data.hardware_input_id
            callbacks.register_callback(release, event)

    def _toggle_override(self, hold, addresses):
        if self._toggle_hold is not None:
            self._clear_toggle()
        else:
            remote_control.beginClientOverride(hold, addresses)
            self._toggle_hold = hold

    def _release_press(self, hold):
        if hold is not None and hold is self._press_hold:
            self._press_hold = None
            if hold is not self._toggle_hold:
                remote_control.endClientOverride(hold)

    def _clear_toggle(self):
        if self._toggle_hold is not None:
            remote_control.endClientOverride(self._toggle_hold)
            self._toggle_hold = None

    def profile_stop(self):
        self._release_press(self._press_hold)
        self._clear_toggle()


class RemoteClientAction(gremlin.input_item.AbstractAction):
    name = "Remote Control"
    tag = "remote-client"
    hint = "Choose active remote clients and set the profile's local and remote output routing."
    default_button_activation = (True, True)
    input_types = [InputType.JoystickButton, InputType.JoystickHat, InputType.Keyboard, InputType.KeyboardLatched]  # noqa: RUF012
    functor = RemoteClientFunctor
    widget = RemoteClientWidget

    def __init__(self, parent, extra_data=None):
        super().__init__(parent, extra_data=extra_data)
        self.selection: frozenset[str] | None = None
        self.operation = ClientOperation.Select
        self.output_mode = OutputMode.Unchanged
        self.behavior = SelectionBehavior.Permanent
        self.exec_on_press = True
        self.exec_on_release = False
        self.setPriority(899)  # run before most other actions so the output selection happens before other actions in the same group

    @property
    def holds_client_filter(self):
        return self.operation is not ClientOperation.Unchanged and self.behavior is SelectionBehavior.Temporary

    def icon(self):
        return "fa6s.network-wired"

    def requires_virtual_button(self):
        return False

    def _parse_xml(self, node, data=None, extra_data=None):
        self.selection = read_client_selection(node.find("clients"))
        self.exec_on_press = safe_read(node, "exec_on_press", bool, True)
        self.exec_on_release = safe_read(node, "exec_on_release", bool, False)
        legacy_output = next(
            (mode for mode in OutputMode if mode is not OutputMode.Unchanged and mode.value == node.get("operation")), None
        )
        if legacy_output is not None:
            self.operation = ClientOperation.Unchanged
        else:
            self.operation = safe_read(node, "operation", ClientOperation, None) or ClientOperation.Select
        self.output_mode = safe_read(node, "output-mode", OutputMode, None) or legacy_output or OutputMode.Unchanged
        behavior = safe_read(node, "behavior", SelectionBehavior, None)
        if self.operation in (ClientOperation.EnableAll, ClientOperation.DisableAll) and behavior in (None, SelectionBehavior.Toggle):
            # Older all-client actions always took effect only while held.
            behavior = SelectionBehavior.Temporary
        self.behavior = behavior or SelectionBehavior.Permanent
        legacy_client = node.get("solo-client", "").strip().rstrip(".").casefold()
        if self.operation is ClientOperation.Select and node.get("solo", "").casefold() == "true" and legacy_client:
            self.selection = frozenset({legacy_client})

    def _generate_xml(self):
        node = etree.Element(self.tag)
        write_client_selection(node, "clients", self.selection)
        if self.operation is not ClientOperation.Select:
            node.set("operation", self.operation.value)
        if self.output_mode is not OutputMode.Unchanged:
            node.set("output-mode", self.output_mode.value)
        if self.operation in (ClientOperation.EnableAll, ClientOperation.DisableAll) or self.behavior is not SelectionBehavior.Permanent:
            node.set("behavior", self.behavior.value)
        node.set("exec_on_press", safe_format(self.exec_on_press, bool))
        node.set("exec_on_release", safe_format(self.exec_on_release, bool))
        return node

    def _is_valid(self):
        return True

    def hasOutput(self) -> bool:
        """Exclude this action if it does nothing"""
        if not (self.holds_client_filter or self.exec_on_press or self.exec_on_release):
            return False
        if self.operation is ClientOperation.Select and self.selection is not None and not self.selection:
            # no clients
            return False
        # no changes
        return self.operation is not ClientOperation.Unchanged or self.output_mode is not OutputMode.Unchanged


version = 1
name = RemoteClientAction.name
create = RemoteClientAction
