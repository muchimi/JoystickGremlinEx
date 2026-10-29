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
from lxml import etree as ElementTree

from PySide6 import QtCore

import gremlin.base_profile
from gremlin.input_types import InputType
from gremlin.util import hat_tuple_to_direction, safe_read, safe_format
import gremlin.ui.ui_common
import gremlin.input_item
import gremlin.remote
import gremlin.keyboard
import gremlin.windows_event_hook
import win32con
import win32api
from gremlin.types import SyncMode
import gremlin.joystick_handling
import gremlin.event_handler
import gremlin.raw_input


syslog = logging.getLogger("system")


class KVMWidget(gremlin.input_item.AbstractActionWidget):
    """UI widget for mapping inputs to mouse motion or buttons."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)

    def _create(self, action_data):
        self.action_data: KVM = action_data

    def _create_ui(self):
        """Creates the UI components."""

        mouse_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Enable mouse",
            value=self.action_data.mouse_enabled,
            tooltip="Mouse data will be set (motion, wheel and buttons)",
            callback=self._handle_mouse_enabled_changed,
        )

        keyboard_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Enable keyboard", value=self.action_data.keyboard_enabled, tooltip="Keyboard data will be sent", callback=self._handle_keyboard_enabled_changed
        )

        invert_x_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Invert X", value=self.action_data.invert_x, tooltip="Inverts the x motion", callback=self._handle_invert_x_changed
        )

        invert_y_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Invert Y", value=self.action_data.invert_y, tooltip="Inverts the y motion", callback=self._handle_invert_y_changed
        )

        rotate_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Flip X/Y (rotation)", value=self.action_data.rotate, tooltip="Flips mouse x and y for rotated displays", callback=self._handle_rotation_changed
        )

        widgets = [
            "Mapping options:",
            invert_x_widget,
            invert_y_widget,
            rotate_widget,
        ]

        self.container_output_options = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True, left_margin=12)

        self.remote_widget = gremlin.ui.ui_common.RemoteClientWidget(self.action_data.remote_config)

        sync_modes = [SyncMode.Ignore, SyncMode.Input]
        sync_widget = gremlin.ui.ui_common.QSyncModeWidget(
            mode=self.action_data.sync_mode, label="State on profile start:", callback=self._sync_changed, sync_modes=sync_modes
        )

        info_widget = gremlin.ui.ui_common.QInfoBox(
            "Keyboard and mouse output follows the current remote control mode. "
            "Local input remains enabled in concurrent mode.<br>"
            "Press <i>left-shift + esc</i> to return local control if the input becomes blocked."
        )

        widgets = [
            mouse_widget,
            self.container_output_options,
            keyboard_widget,
            sync_widget,
            self.remote_widget,
            info_widget,
        ]

        widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)
        self.main_layout.addWidget(widget)

        self._update_ui()

        self.remote_widget.refreshClients()

    def _update_ui(self):
        visible = self.action_data.mouse_enabled
        self.container_output_options.setVisible(visible)

    @QtCore.Slot(bool)
    def _handle_mouse_enabled_changed(self, checked: bool):
        self.action_data.mouse_enabled = checked
        self._update_ui()

    @QtCore.Slot(bool)
    def _handle_invert_x_changed(self, checked: bool):
        self.action_data.invert_x = checked

    @QtCore.Slot(bool)
    def _handle_invert_y_changed(self, checked: bool):
        self.action_data.invert_y = checked

    @QtCore.Slot(bool)
    def _handle_rotation_changed(self, checked: bool):
        self.action_data.rotate = checked

    @QtCore.Slot(bool)
    def _handle_keyboard_enabled_changed(self, checked: bool):
        self.action_data.keyboard_enabled = checked

    def _sync_changed(self, mode):
        self.action_data.sync_mode = mode

    def _populate_ui(self):
        """Populates the UI components."""
        pass


class KVMFunctor(gremlin.base_profile.AbstractFunctor):
    """Routes physical keyboard and mouse input to the configured outputs."""

    def __init__(self, action, parent=None):
        """Creates a new functor with the provided data.

        :param action contains parameters to use with the functor
        """
        super().__init__(action, parent)

        self.config = action
        self._is_running = False  # true if kvm is active
        self._last_x = None  # last mouse position x
        self._last_y = None  # last mouse position y
        self.action_data: KVM = action
        self._raw_input_hooked = False
        self._mouse_suppressed = False
        self._keyboard_suppressed = False
        self._remote_output = False
        self._output_lock = threading.RLock()
        self._remote_keys = {}
        self._remote_buttons = set()
        self.client_list = [0]  # default list of clients = any

    def start(self):
        """start the kvm function"""
        with self._output_lock:
            if not self._is_running:
                self._is_running = True
                syslog.info("KVM: start")
                el = gremlin.event_handler.EventListener()
                el.remote_control_state_change.connect(self._update_output_state)
                el.config_changed.connect(self._update_output_state)
                self._update_output_state()

                if self.action_data.mouse_enabled:
                    # hook raw mouse movement
                    self.raw_hook()

                if self.action_data.keyboard_enabled:
                    kh = gremlin.windows_event_hook.KeyboardHook()
                    kh.register(self._keyboard_handler)

    def _update_output_state(self):
        """Apply routing changes while the KVM input remains active."""
        with self._output_lock:
            if not self._is_running:
                return

            is_local, is_remote = self.action_data.sendFlags()
            self._set_remote_output(is_remote)

            # Let physical input pass through locally instead of injecting a second
            # copy. Track our own suppression entries so concurrent KVM actions can
            # release their entries independently.
            suppress_mouse = self.action_data.mouse_enabled and not is_local
            if suppress_mouse != self._mouse_suppressed:
                mh = gremlin.windows_event_hook.MouseHook()
                if suppress_mouse:
                    mh.pushSuppress()
                else:
                    mh.popSuppress()
                self._mouse_suppressed = suppress_mouse

            suppress_keyboard = self.action_data.keyboard_enabled and not is_local
            if suppress_keyboard != self._keyboard_suppressed:
                kh = gremlin.windows_event_hook.KeyboardHook()
                if suppress_keyboard:
                    kh.pushSuppress()
                else:
                    kh.popSuppress()
                self._keyboard_suppressed = suppress_keyboard

    def _set_remote_output(self, enabled):
        if enabled == self._remote_output:
            return
        self._remote_output = enabled
        if not enabled:
            # Releases must reach the original targets even after remote output
            # is disabled, otherwise held keys and buttons would remain down.
            for (virtual_code, scan_code, _), flags in self._remote_keys.items():
                gremlin.remote.remote_client.send_kvm_keyboard(
                    virtual_code, scan_code, flags | win32con.KEYEVENTF_KEYUP, client_list=self.client_list
                )
            self._remote_keys.clear()
            for button_id in self._remote_buttons:
                gremlin.remote.remote_client.send_kvm_mouse_button(button_id, False, client_list=self.client_list)
            self._remote_buttons.clear()

        if self.action_data.mouse_enabled:
            if enabled:
                gremlin.remote.remote_client.send_kvm_mouse_motion_start(client_list=self.client_list)
            else:
                gremlin.remote.remote_client.send_kvm_mouse_motion_stop(client_list=self.client_list)

    def stop(self):
        """stop the kvm function"""
        with self._output_lock:
            if not self._is_running:
                return
            syslog.info("KVM: stop")
            self._is_running = False
            self._set_remote_output(False)
            if self._mouse_suppressed:
                mh = gremlin.windows_event_hook.MouseHook()
                mh.popSuppress()
                self._mouse_suppressed = False

            if self._keyboard_suppressed:
                kh = gremlin.windows_event_hook.KeyboardHook()
                kh.popSuppress()
                self._keyboard_suppressed = False

        el = gremlin.event_handler.EventListener()
        el.remote_control_state_change.disconnect(self._update_output_state)
        el.config_changed.disconnect(self._update_output_state)
        # Unhook outside the output lock: the raw input thread may be finishing
        # a callback while registerUnhook waits for it to exit.
        if self.action_data.mouse_enabled:
            self.raw_unhook()
        if self.action_data.keyboard_enabled:
            kh = gremlin.windows_event_hook.KeyboardHook()
            kh.unregister(self._keyboard_handler)

    def profile_started(self):
        """called on profile start"""
        super().profile_started()
        device_guid = self.action_data.hardware_device_guid
        input_id = self.action_data.hardware_input_id
        input_type = self.action_data.get_input_type()
        self.verbose = gremlin.config.Configuration().verbose_mode_remote

        # update current client list from detected network clients
        self.client_list = self.action_data.remote_config.getClientList()
        # current mouse position
        self._last_x, self._last_y = win32api.GetCursorPos()
        match self.action_data.sync_mode:
            case SyncMode.Input:
                match input_type:
                    case InputType.JoystickHat:
                        position = gremlin.joystick_handling.get_hat_position(device_guid, input_id)
                        container = self.action_data.get_container()
                        if container.has_virtual_button:
                            is_pressed = hat_tuple_to_direction(position) in container.virtual_button.directions
                        else:
                            is_pressed = position != (0, 0)
                    case InputType.JoystickButton:
                        is_pressed = gremlin.joystick_handling.get_button(device_guid, input_id)
                    case _:
                        return

                # Hats activate KVM as buttons after their configured directions
                # have been evaluated, just as they do in the execution graph.
                event = gremlin.event_handler.Event(
                    event_type=InputType.JoystickButton, identifier=input_id, value=is_pressed, is_pressed=is_pressed, device_guid=device_guid
                )
                self.process_event(event, is_pressed)

            case SyncMode.Ignore:
                pass

    def profile_stop(self):
        """called when profile stops"""
        self.stop()
        # ensure raw mode is off and mouse/keyboard suppression is turned off
        gremlin.raw_input.rawInputShutdown()
        mh = gremlin.windows_event_hook.MouseHook()
        mh.popSuppress(True)
        kh = gremlin.windows_event_hook.KeyboardHook()
        kh.popSuppress(True)

    def raw_hook(self):
        """sets up a fake window to capture raw inputs"""
        if not self._raw_input_hooked:
            self._raw_input_hooked = True
            gremlin.raw_input.registerHook(self._mouse_move_handler)

    def raw_unhook(self):
        if self._raw_input_hooked:
            gremlin.raw_input.registerUnhook(self._mouse_move_handler)
            self._raw_input_hooked = False

    def _mouse_button_handler(self, event: gremlin.windows_event_hook.MouseEvent):
        """handles a mouse button"""
        with self._output_lock:
            if not self._is_running or not self.action_data.mouse_enabled or event.is_injected:
                return
            self._update_output_state()
            if not self._remote_output:
                return
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info(f"KVM: mouse button {event.button_id} {event.is_pressed}")
            self._send_mouse_button(event.button_id, event.is_pressed)

    def _send_mouse_button(self, button_id, is_pressed):
        gremlin.remote.remote_client.send_kvm_mouse_button(button_id, is_pressed, client_list=self.client_list)
        if button_id <= 5:  # Wheel packets represent a single scroll, not a held button.
            if is_pressed:
                self._remote_buttons.add(button_id)
            else:
                self._remote_buttons.discard(button_id)

    def _mouse_move_handler(self, packets: list[gremlin.raw_input.RawInputData]):
        """handles mouse motion"""
        with self._output_lock:
            if not self._is_running or not self.action_data.mouse_enabled:
                return
            self._update_output_state()
            if not self._remote_output:
                return
            verbose = gremlin.config.Configuration().verbose_mode_remote
            for data in packets:
                match data.contentType:
                    case gremlin.raw_input.RawInputDataType.Motion:
                        dx = data.dx
                        dy = data.dy
                        if verbose:
                            syslog.info(f"KVM: motion {dx} {dy}")

                        # apply transforms if any
                        if self.action_data.invert_x:
                            dx = -dx
                        if self.action_data.invert_y:
                            dy = -dy
                        if self.action_data.rotate:
                            dx, dy = dy, dx

                        # send to remote client
                        gremlin.remote.remote_client.send_kvm_mouse_motion(0, 0, dx, dy, client_list=self.client_list)

                    case gremlin.raw_input.RawInputDataType.Button:
                        # button type
                        self._send_mouse_button(data.button_id, data.is_pressed)

    def _mouse_wheel_handler(self, delta: int, leftright: bool):
        """handles a mouse wheel event"""
        with self._output_lock:
            if not self._is_running or not self.action_data.mouse_enabled:
                return
            self._update_output_state()
            if not self._remote_output:
                return
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                syslog.info("KVM: wheel")
            gremlin.remote.remote_client.send_kvm_mouse_wheel(delta, leftright, client_list=self.client_list)

    def _keyboard_handler(self, event: gremlin.windows_event_hook.KeyEvent):
        """handles keyboard event"""
        with self._output_lock:
            if not self._is_running or not self.action_data.keyboard_enabled or event.is_injected:
                return
            self._update_output_state()
            if not self._remote_output:
                return

            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose:
                key = gremlin.keyboard.KeyMap.find(event.scan_code, event.is_extended)
                syslog.info(f"KVM: kbd key:  {key.debug_name} ")
            flags = win32con.KEYEVENTF_EXTENDEDKEY if event.is_extended else 0
            if not event.is_pressed:
                flags |= win32con.KEYEVENTF_KEYUP

            gremlin.remote.remote_client.send_kvm_keyboard(event.virtual_code, event.scan_code, flags, client_list=self.client_list)
            key_id = (event.virtual_code, event.scan_code, event.is_extended)
            if event.is_pressed:
                self._remote_keys[key_id] = flags
            else:
                self._remote_keys.pop(key_id, None)

    def process_event(self, event, value, extra_data=None):
        is_pressed = event.is_pressed
        if event.event_type == InputType.JoystickHat:
            # A raw hat event also presses its new centered position. Virtual
            # hat buttons arrive as button events and retain their chosen state.
            is_pressed = is_pressed and event.value != (0, 0)
        if is_pressed:
            self.start()
        else:
            self.stop()


class KVM(gremlin.input_item.AbstractAction):
    """Keyboard and mouse passthrough controlled by a joystick button or hat."""

    name = "KVM"
    tag = "kvm"
    hint = "Routes mouse and/or keyboard input using the current remote control mode"

    default_button_activation = (True, True)

    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
    ]

    functor = KVMFunctor
    widget = KVMWidget

    def __init__(self, parent, extra_data: dict = None):
        super().__init__(parent, extra_data=extra_data)
        self.parent = parent
        # Flag whether or not this is mouse motion or button press
        self.mouse_enabled = True
        self.keyboard_enabled = True
        self.sync_mode = SyncMode.Ignore  # ignore by default
        self.invert_x = False  # x mouse motion inversion
        self.invert_y = False  # y mouse motion inversion
        self.rotate = False  # flip x/y for non standard monitor orientations

        # Use the normal local/remote routing, including concurrent output.
        self.remote_config.remote = True

    def display_name(self):
        """returns a display string for the current configuration"""
        return "kvm"

    def icon(self):
        """icon"""
        return "mdi.remote-desktop"

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        return self.get_input_type() in [InputType.JoystickAxis, InputType.JoystickHat]

    def _parse_xml(self, node, data=None, extra_data=None):
        """Reads the contents of an XML node to populate this instance.

        :param node the node whose content should be used to populate this
            instance
        """
        self.mouse_enabled = safe_read(node, "mouse", bool, True)
        self.keyboard_enabled = safe_read(node, "keyboard", bool, True)
        if "sync-mode" in node.attrib:
            self.sync_mode = SyncMode(safe_read(node, "sync-mode", int, 0))
        self.invert_x = safe_read(node, "invert-x", bool, False)
        self.invert_y = safe_read(node, "invert-y", bool, False)
        self.rotate = safe_read(node, "rotate", bool, False)

    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(KVM.tag)

        node.set("keyboard", safe_format(self.keyboard_enabled, bool))
        node.set("mouse", safe_format(self.mouse_enabled, bool))
        node.set("sync-mode", safe_format(self.sync_mode, int))
        node.set("invert-x", safe_format(self.invert_x, bool))
        node.set("invert-y", safe_format(self.invert_y, bool))
        node.set("rotate", safe_format(self.rotate, bool))

        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return True

    def to_html(self) -> str:
        """returns reporting graphviz data for this action"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)

        table.addField("Mode", f"{self.mode}")

        return table.to_html()


version = 1
name = "kvm"
create = KVM
