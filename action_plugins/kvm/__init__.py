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
import math
import os
from lxml import etree as ElementTree

from PySide6 import QtCore, QtWidgets, QtGui

import gremlin.base_profile
from gremlin.input_types import InputType
from gremlin.types import MouseButton
from gremlin.profile import read_bool, safe_read, safe_format
from gremlin.util import rad2deg
import gremlin.util
import gremlin.ui.ui_common
import gremlin.ui.input_item
import gremlin.sendinput
from gremlin import input_devices
import psygnal
from psygnal import Signal
from shiboken6 import Shiboken
import gremlin.remote
import threading
import gremlin.keyboard
import gremlin.windows_event_hook
import win32con, win32api
from gremlin.types import SyncMode
import gremlin.joystick_handling
import gremlin.ui.osc_device
import gremlin.event_handler

syslog = logging.getLogger("system")

class KVMWidget(gremlin.ui.input_item.AbstractActionWidget):

    """UI widget for mapping inputs to mouse motion or buttons."""

    def __init__(self, action_data, parent=None):
        """Creates a new instance.

        :param action_data the data managed by this widget
        :param parent the parent of this widget
        """
        super().__init__(action_data, parent=parent)

    def _create(self, action_data):
        self.action_data : KVM = action_data

    def _create_ui(self):
        """Creates the UI components."""
        

        mouse_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Enable mouse",
            value = self.action_data.mouse_enabled,
            tooltip = "Mouse data will be set (motion, wheel and buttons)",
            callback = self._handle_mouse_enabled_changed
        )

        keyboard_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Enable keyboard",
            value = self.action_data.keyboard_enabled,
            tooltip = "Keyboard data will be sent",
            callback = self._handle_keyboard_enabled_changed
        )

        sync_modes = [SyncMode.Ignore, SyncMode.Input]
        sync_widget = gremlin.ui.ui_common.QSyncModeWidget(mode = self.action_data.sync_mode, label = "State on profile start:", callback = self._sync_changed, sync_modes= sync_modes)

        info_widget = gremlin.ui.ui_common.QInfoBox("Press <i>left-shift + esc</i> to return local control if the input becomes blocked.")

        
        widgets = [
            mouse_widget,
            keyboard_widget,
            sync_widget,
            info_widget,
        ]

        widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True)
        self.main_layout.addWidget(widget)            


    @QtCore.Slot(bool)
    def _handle_mouse_enabled_changed(self, checked : bool):
        self.action_data.mouse_enabled = checked
        
    @QtCore.Slot(bool)
    def _handle_keyboard_enabled_changed(self, checked : bool):
        self.action_data.keyboard_enabled = checked

    def _sync_changed(self, mode):
        self.action_data.sync_mode = mode        
   
    def _populate_ui(self):
        """Populates the UI components."""
        pass




class KVMFunctor(gremlin.base_profile.AbstractFunctor):

    """Implements the functionality required to move a mouse cursor.

    This moves the mouse cursor by issuing relative motion commands. This is
    only implemented for axis and hat inputs as they can control a cursor
    properly with a single input, at least partially.
    """

    def __init__(self, action, parent = None):
        """Creates a new functor with the provided data.

        :param action contains parameters to use with the functor
        """
        super().__init__(action, parent)

        self.config = action
        self._is_running = False # true if kvm is active
        self._last_x = None # last mouse position x
        self._last_y = None # last mouse position y

    def start(self):
        ''' start the kvm function '''
        if not self._is_running:
            self._is_running = True
            syslog.info("KVM: start")
            if self.action_data.mouse_enabled:
                mh = gremlin.windows_event_hook.MouseHook()
                mh.register(self._mouse_button_handler)
                mh.registerMouseMove(self._mouse_move_handler)
                mh.registerMouseWheel(self._mouse_wheel_handler)
                gremlin.remote.remote_client.send_kvm_mouse_motion_start()
                mh.pushSuppress()
            
            kh = gremlin.windows_event_hook.KeyboardHook()
            kh.register(self._keyboard_handler)

            if self.action_data.keyboard_enabled:
                # supress local keyboard output
                kh.pushSuppress()
            
            
   

    def stop(self):
        ''' stop the kvm function '''
        if self._is_running:
            syslog.info("KVM: stop")
            self._is_running = False
            if self.action_data.mouse_enabled:
                mh = gremlin.windows_event_hook.MouseHook()
                mh.popSuppress()
                mh.unregister(self._mouse_button_handler)
                mh.unregisterMouseMove(self._mouse_move_handler)
                mh.unregisterMouseWheel(self._mouse_wheel_handler)
                gremlin.remote.remote_client.send_kvm_mouse_motion_stop()
            
            kh = gremlin.windows_event_hook.KeyboardHook()
            kh.unregister(self._keyboard_handler)

            if self.action_data.keyboard_enabled:
                kh.popSuppress()
            
            
    def profile_start(self):
        ''' called on profile start '''
        device_guid = self.action_data.hardware_device_guid
        input_id = self.action_data.hardware_input_id
        input_type = self.action_data.get_input_type()
        self.verbose = gremlin.config.Configuration().verbose_mode_remote
        # current mouse position 
        self._last_x, self._last_x = win32api.GetCursorPos()
        match self.action_data.sync_mode:
            case SyncMode.Input:
                match input_type:
                    case InputType.JoystickHat:
                        pass
                    case InputType.JoystickAxis:
                        pass
                    case InputType.JoystickButton:
                        is_pressed = gremlin.joystick_handling.get_button(device_guid, input_id)
                
                        # construct the input event to sync
                        event = gremlin.event_handler.Event(event_type = input_type,
                                                            identifier = input_id,
                                                            value = is_pressed,
                                                            is_pressed = is_pressed,
                                                            device_guid = device_guid)
                        self.process_event(event, is_pressed)
                  
            case SyncMode.Ignore:
                pass


    def _mouse_button_handler(self, event : gremlin.windows_event_hook.MouseEvent):
        ''' handles a mouse button '''
        verbose = gremlin.config.Configuration().verbose_mode_remote
        if verbose: syslog.info(f"KVM: mouse button {event.button_id} {event.is_pressed}")
        gremlin.remote.remote_client.send_kvm_mouse_button(event.button_id, event.is_pressed)

    


    def _mouse_move_handler(self, x, y):
        ''' handles mouse motion '''
        verbose = gremlin.config.Configuration().verbose_mode_remote
        if verbose: syslog.info(f"KVM: motion {x} {y}")
        if self._last_x is None or self._last_y is None:
            # get init mouse position if not set this session
            self._last_x, self._last_y = win32api.GetCursorPos()
        # hwnd = win32api.MonitorFromPoint((x, y), win32con.MONITOR_DEFAULTTONEAREST)
        # orientation, orientation_name = gremlin.util.getMonitorOrientation(hwnd)
                                
        dx = self._last_x - x
        dy = self._last_y - y
        self._last_x = x
        self._last_y = y
        gremlin.remote.remote_client.send_kvm_mouse_motion(x, y, dx, dy)
        

    def _mouse_wheel_handler(self, delta : int, leftright : bool):
        ''' handles a mouse wheel event '''
        verbose = gremlin.config.Configuration().verbose_mode_remote
        if verbose: syslog.info("KVM: wheel")
        gremlin.remote.remote_client.send_kvm_mouse_wheel(delta, leftright)

    def _keyboard_handler(self, event : gremlin.windows_event_hook.KeyEvent):
        ''' handles keyboard event '''
        
        key = gremlin.keyboard.KeyMap.find(event.scan_code, event.is_extended)

        if self.action_data.keyboard_enabled:
            verbose = gremlin.config.Configuration().verbose_mode_remote
            if verbose: syslog.info(f"KVM: kbd key:  {key.debug_name} ")
            flags = win32con.KEYEVENTF_EXTENDEDKEY if event.is_extended else 0
            if not event.is_pressed:
                flags |= win32con.KEYEVENTF_KEYUP

            gremlin.remote.remote_client.send_kvm_keyboard(event.virtual_code, event.scan_code, flags)



    def process_event(self, event, value, extra_data = None):
        is_pressed = event.is_pressed
        if is_pressed:
            self.start()
        else:
            self.stop()

  
class KVM(gremlin.base_profile.AbstractAction):

    """Action data for the map to mouse action.

    Map to mouse allows controlling of the mouse cursor using either a joystick
    or a hat.
    """

    name = "KVM"
    tag = "kvm"
    hint = "Sends mouse and/or keyboard data to the remote clients"

    
    default_button_activation = (True, True)
    
    input_types = [
         InputType.JoystickButton,
         InputType.JoystickHat,
    ]

    functor = KVMFunctor
    widget = KVMWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        # Flag whether or not this is mouse motion or button press
        self.mouse_enabled = True
        self.keyboard_enabled = True
        self.sync_mode = SyncMode.Ignore # ignore by default
        
       

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return "kvm"
    
    def icon(self):
        ''' icon '''
        return "mdi.remote-desktop"
        

    def requires_virtual_button(self):
        """Returns whether or not an activation condition is needed.

        :return True if an activation condition is required for this particular
            action instance, False otherwise
        """
        # Need virtual buttons for button inputs on axes and hats
        if self.get_input_type() in [InputType.JoystickAxis, InputType.JoystickHat]:
            return not self.motion_input
        return False
    


    def _parse_xml(self, node, data = None, extra_data = None):
        """Reads the contents of an XML node to populate this instance.

        :param node the node whose content should be used to populate this
            instance
        """
        self.mouse_enabled= safe_read(node,"mouse",bool, True)
        self.keyboard_enabled= safe_read(node,"keyboard",bool, True)
        if "sync-mode" in node.attrib:
            self.sync_mode = SyncMode(safe_read(node,"sync-mode", int, 0))


    def _generate_xml(self):
        """Returns an XML node containing this instance's information.

        :return XML node containing the information of this  instance
        """
        node = ElementTree.Element(KVM.tag)

        node.set("keyboard", safe_format(self.keyboard_enabled, bool))
        node.set("mouse", safe_format(self.mouse_enabled, bool))
        node.set("sync-mode", safe_format(self.sync_mode, int))

        return node

    def _is_valid(self):
        """Returns whether or not this action is valid.

        :return True if the action is configured correctly, False otherwise
        """
        return True
  
    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell
        table = ReportTable(cellpadding=4)    

        table.addField("Mode", f"{self.mode}")

        return table.to_html()


version = 1
name = "kvm"
create = KVM
