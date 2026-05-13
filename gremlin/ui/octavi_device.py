
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

from __future__ import annotations
import logging

from PySide6 import QtWidgets, QtCore, QtGui
import threading
import gremlin.base_classes
import gremlin.config
import gremlin.event_handler
import gremlin.input_devices
import gremlin.input_devices
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.shared_state
from gremlin.types import DeviceType
from gremlin.input_types import InputType
import gremlin.shared_state
from gremlin.keyboard import Key
import gremlin.ui.joystick_device
import gremlin.base_profile
import uuid
from gremlin.singleton_decorator import SingletonDecorator
import collections
import logging
import re
import time
from typing import overload, List, Union, Any, Generator, Tuple, Callable, Optional, DefaultDict, Iterator, Union, cast, Coroutine, NamedTuple
import logging
from typing import Any, Iterator, List, Union
import asyncio
from asyncio import BaseEventLoop
import fnmatch
import socketserver
import socket
from socket import socket as _socket
import sys
import os
from collections.abc import Iterable
import struct
from datetime import datetime, timedelta, date

import gremlin.ui.ui_common
from gremlin.util import *
from lxml import etree as ElementTree

import enum
#from gremlin.base_classes import AbstractInputItem
import gremlin.util
import vjoy
import vjoy.vjoy
import psygnal
from psygnal import Signal
import hid

syslog = logging.getLogger("system")

''' device input for Octavi IFR1 device '''



class OctaviButton(enum.IntEnum):
    MODEAP = 1 # bottom AP button
    MODEHDG = 2
    MODENAV = 3
    MODEAPR = 4
    MODEALT = 5
    MODEVS = 6
    COM1 = 7
    COM2 = 8
    NAV1 = 9
    NAV2 = 10
    FMS1 = 11
    FMS2 = 12
    AP = 13 # AP button below FMS1
    XPDR = 14
    DIRECT = 15
    MENU = 16
    CLR = 17
    ENT = 18
    EXC = 19 # exchange button
    PRESS = 20 # knob press
    INNER = 21 # inner knob value
    OUTER = 22 # outer knob value
    INNER_DEC = 23 # inner knob decrement
    INNER_INC = 24 # inner knob increment
    OUTER_DEC = 25 # outer knob decrement
    OUTER_INC = 26 # outer knob increment

    @staticmethod
    def to_tooltip(button : OctaviButton):
        match button:
            case OctaviButton.MODEAP:
                return "AP button (lower bar)"
            case OctaviButton.MODEHDG:
                return "HDG button (lower bar)"
            case OctaviButton.MODENAV:
                return "NAV button (lower bar)"
            case OctaviButton.MODEAPR:
                return "APR button (lower bar)"
            case OctaviButton.MODEALT:
                return "ALT button (lower bar)"
            case OctaviButton.MODEVS:
                return "VS button (lower bar)"
            case OctaviButton.COM1:
                return "COM1 selector"
            case OctaviButton.COM2:
                return "COM2 selector"
            case OctaviButton.NAV1:
                return "NAV1 selector"
            case OctaviButton.NAV2:
                return "NAV2 selector"
            case OctaviButton.FMS1:
                return "FMS1 selector"
            case OctaviButton.FMS2:
                return "FMS2 selector"
            case OctaviButton.AP:
                return "AP selector"
            case OctaviButton.XPDR:
                return "XPDR selector"
            case OctaviButton.DIRECT:
                return "DCT button"
            case OctaviButton.MENU:
                return "MENU button"
            case OctaviButton.CLR:
                return "CLR button"
            case OctaviButton.ENT:
                return "ENT button"
            case OctaviButton.EXC:
                return "SQWAP button"
            case OctaviButton.PRESS:
                return "Knob push"
            case OctaviButton.INNER:
                return "INNER knob direction, -1, 0 or +1"
            case OctaviButton.OUTER:
                return "Outer knob direction, -1, 0 or +1"
            case OctaviButton.INNER_DEC:
                return "Inner knob rotate left (counterclockwise)"
            case OctaviButton.INNER_INC:
                return "Inner knob rotate right (clockwise)"
            case OctaviButton.OUTER_DEC:
                return "Outer knob rotate left (counterclockwise)"
            case OctaviButton.OUTER_INC:
                return "Outer knob rotate right (clockwise)"

        return f"Don't know how to handle: {button}"

    @staticmethod
    def to_display_name(button: OctaviButton):
        match button:
            case OctaviButton.MODEAP:
                return "AP (bottom)"
            case OctaviButton.MODEHDG:
                return "HDG (bottom)"
            case OctaviButton.MODENAV:
                return "NAV (bottom)"
            case OctaviButton.MODEAPR:
                return "APR (bottom)"
            case OctaviButton.MODEALT:
                return "ALT (bottom)"
            case OctaviButton.MODEVS:
                return "VS (bottom)"
            case OctaviButton.COM1:
                return "COM1"
            case OctaviButton.COM2:
                return "COM2"
            case OctaviButton.NAV1:
                return "NAV1"
            case OctaviButton.NAV2:
                return "NAV2"
            case OctaviButton.FMS1:
                return "FMS1"
            case OctaviButton.FMS2:
                return "FMS2"
            case OctaviButton.AP:
                return "AP"
            case OctaviButton.XPDR:
                return "XPDR"
            case OctaviButton.DIRECT:
                return "DCT"
            case OctaviButton.MENU:
                return "MENU"
            case OctaviButton.CLR:
                return "CLR"
            case OctaviButton.ENT:
                return "ENT"
            case OctaviButton.EXC:
                return "SQWAP"
            case OctaviButton.PRESS:
                return "Knob press"
            case OctaviButton.INNER:
                return "INNER knob "
            case OctaviButton.OUTER:
                return "Outer knob"
            case OctaviButton.INNER_DEC:
                return "Inner knob"
            case OctaviButton.INNER_INC:
                return "Inner knob"
            case OctaviButton.OUTER_DEC:
                return "Outer knob"
            case OctaviButton.OUTER_INC:
                return "Outer knob"
            case _:
                return "N/A"
    @staticmethod
    def get_icon(button : OctaviButton):

        match button:
            case OctaviButton.MODEAP:
                return "fa5s.minus-square"
            case OctaviButton.MODEHDG:
                return "fa5s.minus-square"
            case OctaviButton.MODENAV:
                return "fa5s.minus-square"
            case OctaviButton.MODEAPR:
                return "fa5s.minus-square"
            case OctaviButton.MODEALT:
                return "fa5s.minus-square"
            case OctaviButton.MODEVS:
                return "fa5s.minus-square"
            case OctaviButton.COM1:
                return "ph.rectangle-fill"
            case OctaviButton.COM2:
                return "ph.rectangle-fill"
            case OctaviButton.NAV1:
                return "ph.rectangle-fill"
            case OctaviButton.NAV2:
                return "ph.rectangle-fill"
            case OctaviButton.FMS1:
                return "ph.rectangle-fill"
            case OctaviButton.FMS2:
                return "ph.rectangle-fill"
            case OctaviButton.AP:
                return "ph.rectangle-fill"
            case OctaviButton.XPDR:
                return "ph.rectangle-fill"
            case OctaviButton.DIRECT:
                return "fa6s.arrow-right-to-bracket"
            case OctaviButton.MENU:
                return "ph.rectangle-fill"
            case OctaviButton.CLR:
                return "ph.rectangle-fill"
            case OctaviButton.ENT:
                return "ph.rectangle-fill"
            case OctaviButton.EXC:
                return "ri.swap-box-line"
            case OctaviButton.PRESS:
                return "fa6.circle-down"
            case OctaviButton.INNER:
                return "fa6s.arrows-rotate"
            case OctaviButton.OUTER:
                return "fa6s.arrows-rotate"
            case OctaviButton.INNER_DEC:
                return "fa6s.arrow-rotate-left"
            case OctaviButton.INNER_INC:
                return "fa6s.arrow-rotate-right"
            case OctaviButton.OUTER_DEC:
                return "fa6s.arrow-rotate-left"
            case OctaviButton.OUTER_INC:
                return "fa6s.arrow-rotate-right"
            case _:
                return "mdi.help-rhombus"


@SingletonDecorator
class OctaviInterface():

    def __init__(self):
        self._device_found = False # true if the device is found
        self._device = None
        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self._stop)
        self._running = False
        self._buttons = {} # map of [OctaviButton] to bool
        self._last_buttons = {} # last buttons
        self._core_buttons = [button for button in OctaviButton if button < OctaviButton.INNER]
        self._timers = {}
        self._device_guid = gremlin.shared_state.octavi_tab_guid
        self._last_led = 0 # last status LED
        for button in OctaviButton:
            self._buttons[button] = False
            self._last_buttons[button] = False


        self._autorelease_delay = 0.25 # delay for autorelease
        if self.deviceFound():
            self._start()

    def get_button(self, button : OctaviButton):
        ''' gets the current button state '''
        if button in self._buttons:
            return self._buttons[button]
        return False

    @property
    def delay(self) -> float:
        ''' autorelease delay in seconds '''
        return self._autorelease_delay

    @delay.setter
    def delay(self, value : float):
        ''' autorelease delay in seconds '''
        if value >= 0:
            self._autorelease_delay = value

    def _start(self):
        ''' opens the device '''
        if not self.deviceFound():
            return False
        if self._running:
            return True

        verbose = gremlin.config.Configuration().verbose_mode_octavi
        if verbose: syslog.info("IFR1: start")

        self._running = True
        self._thread = threading.Thread(target = self._run)
        self._thread.name = "IFR1 Poll"
        self._thread.start()


        return True



    def _run(self):
        ''' data poll '''
        while self._running:
            data = list(self._device.read(8)) # returns an array of 8 bytes

            if data:
                changed_data = {}


                # 0 byte0, 1 buttons0, 2 buttons1, 3 buttons2, 4 byte5, 5 knob0, 6 knob1, 7 mode_val
                b0 = data[1]
                b1 = data[2]
                b2 = data[3]
                k1 = data[5]
                k2 = data[6]
                mode = data[7]

                verbose = gremlin.config.Configuration().verbose_mode_octavi
                if verbose:
                    stub = ""
                    for item in data:
                        stub += f"0x{item:x} ({item}), "
                    syslog.info(stub)



                # byte 1 buttons
                self._buttons[OctaviButton.DIRECT] = (b0 & 0x10) > 0
                self._buttons[OctaviButton.MENU] = (b0 & 0x20) > 0
                self._buttons[OctaviButton.CLR] = (b0 & 0x40) > 0
                self._buttons[OctaviButton.ENT] = (b0 & 0x80) > 0

                # byte 2 buttons
                self._buttons[OctaviButton.EXC] = (b1 & 0x01) > 0
                self._buttons[OctaviButton.PRESS] = (b1 & 0x02) > 0
                self._buttons[OctaviButton.MODEAP] = (b1 & 0x40) > 0
                self._buttons[OctaviButton.MODEHDG] = (b1 & 0x80) > 0

                # byte 3 buttons
                self._buttons[OctaviButton.MODENAV] = (b2 & 0x01) > 0
                self._buttons[OctaviButton.MODEAPR] = (b2 & 0x02) > 0
                self._buttons[OctaviButton.MODEALT] = (b2 & 0x04) > 0
                self._buttons[OctaviButton.MODEVS] = (b2 & 0x08) > 0

                # knob rotation
                v1 = self._knob_value(k1)
                v2 = self._knob_value(k2)
                self._buttons[OctaviButton.OUTER] = v1
                self._buttons[OctaviButton.INNER] = v2

                timers = []

                if v1 > 0:
                    button = OctaviButton.OUTER_INC
                    callback =self._autorelease_outer_inc
                elif v1 < 0:
                    button = OctaviButton.OUTER_DEC
                    callback =self._autorelease_outer_dec

                if v1:
                    changed_data[button] = True
                    if button in self._timers:
                        timer = self._timers[button]
                        timer.cancel()

                    timer = threading.Timer(self._autorelease_delay, callback) # autorelease
                    self._timers[button] = timer
                    timers.append(timer)

                if v2 > 0:
                    button = OctaviButton.INNER_INC
                    callback =self._autorelease_inner_inc
                elif v2 < 0:
                    button = OctaviButton.INNER_DEC
                    callback =self._autorelease_inner_dec

                if v2:
                    changed_data[button] = True
                    if button in self._timers:
                        timer = self._timers[button]
                        timer.cancel()

                    timer = threading.Timer(self._autorelease_delay, callback) # autorelease
                    self._timers[button] = timer
                    timers.append(timer)

                # other buttons
                self._buttons[OctaviButton.COM1] = mode == 0
                self._buttons[OctaviButton.COM2] = mode == 1
                self._buttons[OctaviButton.NAV1] = mode == 2
                self._buttons[OctaviButton.NAV2] = mode == 3
                self._buttons[OctaviButton.FMS1] = mode == 4
                self._buttons[OctaviButton.FMS2] = mode == 5
                self._buttons[OctaviButton.AP] = mode == 6
                self._buttons[OctaviButton.XPDR] = mode == 7





                if self._last_buttons:
                    # prior data set = do a diffential of what's changed

                    for button in self._core_buttons:
                        if not button in self._buttons:
                            continue
                        value = self._buttons[button]
                        if self._last_buttons[button] != value:
                            changed_data[button] = value
                            self._last_buttons[button] = value

                    if changed_data:
                        self._process_input(changed_data)

                    for timer in timers:
                        timer.start()


                else:
                    self._process_input(self._buttons)

                    # copy the data over
                    for button in self._buttons:
                        self._last_buttons[button] = self._buttons[button]




            time.sleep(0.2)

        # done running

    def _autorelease_inner_dec(self):
        self._autorelease_knobs(OctaviButton.INNER_DEC)
    def _autorelease_inner_inc(self):
        self._autorelease_knobs(OctaviButton.INNER_INC)
    def _autorelease_outer_dec(self):
        self._autorelease_knobs(OctaviButton.OUTER_DEC)
    def _autorelease_outer_inc(self):
        self._autorelease_knobs(OctaviButton.OUTER_INC)


    def _autorelease_knobs(self, button : OctaviButton):
        ''' called when timer lapses after a knob trigger '''
        changed_data = {}
        syslog.info(f"autorelease knob : {button.name}")
        self._buttons[button] = False
        changed_data[button] = False
        self._process_input(changed_data)



    def _process_input(self, data):
        ''' handles octavi input events and convert them to joystick events '''
        verbose = gremlin.config.Configuration().verbose_mode_octavi
        if verbose: self._dump(data)
        el = gremlin.event_handler.EventListener()

        is_running = gremlin.shared_state.is_running
        for button in data:
            is_pressed = data[button]
            event = gremlin.event_handler.Event(InputType.OctaviIfr1, button, self._device_guid, is_pressed = is_pressed, value = is_pressed, raw_value = is_pressed, override_input_type=InputType.JoystickButton)
            if not is_running:
                el.joystick_event.emit(event)
                gremlin.util.singleShot(self._create_button_change_callback(event))
            else:
                gremlin.util.singleShot(self._create_execute_callback(event))



    def _create_execute_callback(self, event):
        return lambda: self._execute_event(event)

    def _create_button_change_callback(self, event):
        return lambda: self._button_change(event)

    def _execute_event(self, event):
        eh = gremlin.event_handler.EventHandler()
        eh.execute_event(event)

    def _button_change(self, event):
        el = gremlin.event_handler.EventListener()
        el.button_state_change.emit(event)


    def _dump(self, data):
        ''' dump to the log file '''
        for button in data:
            syslog.info(f"{button.name} -> {data[button]}")

    def _stop(self):
        if self._running:
            self._running = False
            # wait for the thread to finishi
            self._thread.join()
            self._thread = None
            syslog.info("OCTAVI: shutdown")


    def _knob_value(self, byte_value):
        return byte_value - 256 if byte_value > 127 else byte_value


    def close(self):
        ''' closes the device '''
        pass

    def setLed(self, button : OctaviButton, action : str):
        ''' turn LED on or off '''
        if not self._device:
            return # device not found
        match button:
            case gremlin.ui.octavi_device.OctaviButton.MODEAP:
                mask = 1
            case gremlin.ui.octavi_device.OctaviButton.MODEHDG:
                mask = 2
            case gremlin.ui.octavi_device.OctaviButton.MODENAV:
                mask = 4
            case gremlin.ui.octavi_device.OctaviButton.MODEAPR:
                mask = 8
            case gremlin.ui.octavi_device.OctaviButton.MODEALT:
                mask = 16
            case gremlin.ui.octavi_device.OctaviButton.MODEVS:
                mask = 64
            case _:
                return # don't know how to handle a different button


        led = self._last_led
        match action:
            case "on":
                # flip bit on
                led = led | mask
            case "off":
                # flip bit off
                mask = ~mask
                led = led & mask
            case "toggle":
                # toggle bit
                led = led ^ mask

        if led != self._last_led:
            # report number 11, LED value
            self._device.write(bytes([11, led]))
            self._last_led = led


    def deviceFound(self, refresh = False) -> bool:
        ''' scans the HID devices to see if the device is found '''
        if self._device_found:
            return True
        vid = 0x4d8 # vendor ID
        pid = 0xe6d6 # product ID
        try:
            device = hid.Device(vid, pid)
            if device:
                self._device_found = True
                self._device = hid.Device(vid, pid)
                self._device.nonblocking = 1
                syslog.info("IFR1: detected")
                return True
        except:
            pass

        # hid_devices = list(hid.enumerate())
        # data = next((hid for hid in hid_devices if hid["vendor_id"] == vid and data["product_id"] == pid), None)
        # if data:
        #     vid = data['vendor_id']
        #     pid = data['product_id']
        #     self._device_found = True
        #     self._device = hid.Device(vid, pid)
        #     self._device.nonblocking = 1
        #     syslog.info("IFR1: detected")
        #     return True

        self._device_found = False
        self._device = None
        syslog.info("IFR1: not detected")
        return False


# main instance
_octavi_device = OctaviInterface()


class OctaviInputItemListModel(gremlin.ui.input_item.InputItemListModel):

    ''' model for mode input items '''

    def __init__(self, profile : gremlin.base_profile.Profile, mode : str, custom_filter_handler = None):
        ''' creates a new model for mode input items

        :param profile: the profile data for the device this model represents
        :param mode: the current mode to display inputs for
        :param custom_filter_handler: a handler that takes an input item and returns true if it should be filtered (not displayed) or false if it should be visible
        '''
        
        super().__init__(profile = profile,
                         device_guid = OctaviDeviceTabWidget.device_guid,
                         mode = mode,
                         allowed_types = [InputType.ModeControl],
                         custom_filter_handler = custom_filter_handler,
                         show_master_mode=True)   
        

class OctaviInputItemListView(gremlin.ui.input_item.InputItemListView):

    ''' list view for mode input items '''
    def __init__(self, custom_widget_handler, model : OctaviInputItemListModel, parent = None):
        ''' creates a new list view for mode input items

        :param custom_widget_handler a handler that creates a widget for an input item
        :param model the model for the list view
        :param parent the parent widget of this view
        '''
        super().__init__(name = "Octavi IFR1",
                         custom_widget_handler = custom_widget_handler,
                         device_guid = OctaviDeviceTabWidget.device_guid,
                         model = model,
                         parent = parent)
   


class OctaviDeviceTabWidget(gremlin.ui.input_item.BaseDeviceTabWidget):

    """Widget used to configure open sound control (OSC) inputs """

    # IMPORTANT: MUST BE A DID FORMATTED ID ON CUSTOM INPUTS
    device_guid = gremlin.shared_state.octavi_tab_guid

    def __init__(
            self,
            profile : gremlin.base_profile.Profile,
            mode : str,
            object_name = "Octavi IFR1",
            parent=None
            ):

        device = gremlin.joystick_handling.getDevice(self.device_guid)
        super().__init__(
                    device = device,
                    profile = profile,
                    mode = mode,
                    object_name = object_name,
                    parent = parent
                    )


        # Store parameters
        self.profile = profile
        profile.ensure_mode_exists(mode)
        self.device_profile = profile.getDevice(self.device_guid)
        self.device_profile.ensure_mode_exists(mode)
        self.widget_storage = {}

        # List of inputs
        self.inputItemListModel = OctaviInputItemListModel(
            profile = profile,
            mode = mode,
        )


        self.ensureInputItems()

        # update the display names

        self.inputItemListView = OctaviInputItemListView(
            custom_widget_handler=self._custom_widget_handler,
            model = self.inputItemListModel,
        )

        # lock widget
        lock_widget = gremlin.ui.ui_common.QInputLockWidget(data = self.device_guid)
        widget = gremlin.ui.ui_common.getHContainer(lock_widget, left_stretch=True, widget_only = True)
        self.addLeftPanelWidget(widget)


        config = gremlin.config.Configuration()
        if config.show_container_id:
            device = gremlin.joystick_handling.get_device(self.device_guid)
            width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.device_id)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device ID:", widget_only = True)
            self.addLeftPanelWidget(widget)
            w1 = widget

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.name)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Name:", widget_only = True)
            self.addLeftPanelWidget(widget)
            w2 = widget

            gremlin.ui.ui_common.synchronize_grids([w1, w2])

        self.addLeftPanelWidget(self.inputItemListView)


        el = gremlin.event_handler.EventListener()
        el.lock_inputs.connect(self._handle_lock_inputs)
        el.unlock_inputs.connect(self._handle_unlock_inputs)

        # last index selected, -1 means none
        self._last_selected_index = -1

        # Select default entry
        selected_index = self.inputItemListView.currentIndex()
        if selected_index is not None:
            self.selectInputItemIndex(selected_index)

    @property
    def inputCount(self) -> int:
        ''' number of inputs in the device '''
        return self.inputItemListModel.rows()

    @property
    def inputWidgetCount(self) -> int:
        ''' number of input widgets currently in the device '''
        return self.inputItemListView.count()

    def _handle_lock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_lock_inputs_ui, data) # ensure on UI thread

    def _handle_unlock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_unlock_inputs_ui, data) # ensure on UI thread

    def _handle_lock_inputs_ui(self, data):
        ''' lock all inputs event'''
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = True
            self.setUpdatesEnabled(True)

    def _handle_unlock_inputs_ui(self, data):
        ''' unlock all inputs event '''
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = False
            self.setUpdatesEnabled(True)

    def find_input(self, device_guid, input_type, input_id):
        ''' finds the given input '''
        if compare_guid(device_guid, OctaviDeviceTabWidget.device_guid):
            if input_type == InputType.JoystickButton:
                index = self.inputItemListModel.indexOf(input_id)
                if index != -1:
                    return self.inputItemListModel.data(index)
        return None



    @QtCore.Slot(str)
    def _edit_mode_changed_cb(self, mode : str):
        ''' occurs when a new mode is selected '''
        self.set_mode(mode)


    def _mode_name_changed(self, name):
        gremlin.util.InvokeUiMethod(self._mode_name_changed_ui) # ensure on UI thread

    def _mode_name_changed_ui(self, name):
        ''' occurs when there's a mode name change '''
        self.inputItemListModel.refresh()


    def _config_changed_cb(self):
        ''' called when configuraition has changed '''
        self.refresh()

    def ensureInputItems(self, refresh = False):
        ''' ensures we have input items for the current mode
        :param refresh: True if list view should be updated if changes are made
        :returns: True if changes were made

        '''
        current_mode = gremlin.shared_state.edit_mode
        mode_object = self.device_profile.ensure_mode_exists(current_mode)
        config = mode_object.config

        changed = False
        input_type = InputType.OctaviIfr1

        for button in OctaviButton:
            if button in (OctaviButton.INNER, OctaviButton.OUTER):
                continue # skip direction knobs

            if not button in config[input_type]:
                input_item = gremlin.base_profile.InputItem(mode_object = mode_object)
                input_item.setInputId(button)
                input_item.input_type = input_type
                input_item.description = OctaviButton.to_display_name(button)
                config[input_type][button] = input_item
                changed = True
            else:
                input_item = config[input_type][button]

            input_item.setOverrideInputType(InputType.JoystickButton)

        if changed or refresh:
            self.inputItemListModel.refresh()

        return changed

    def _custom_widget_handler(self, list_view, index : int, identifier, data, parent = None):
        ''' creates a widget for the input

        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item

        '''
        import gremlin.ui.input_item

        widget = gremlin.ui.input_item.InputItemWidget(identifier = identifier, populate_ui_callback = self._populate_input_widget_ui, update_callback = self._update_input_widget, config_external=True, parent = parent, data = data)
        widget.data = data
        widget.create_action_icons(data)
        icon_name = OctaviButton.get_icon(data.input_id)
        widget.setIcon(icon_name)


        # remember what widget is at what index
        widget.index = index
        return widget


    def _update_input_widget(self, input_widget, container_widget):
        ''' called when the widget has to update itself on a data change '''
        data : gremlin.base_profile.InputItem = input_widget.identifier
        button = data.input_id
        name = OctaviButton.to_display_name(button)
        tooltip = OctaviButton.to_tooltip(button)
        input_widget.setTitle(name)
        input_widget.setInputDescription(None)
        input_widget.setToolTip(tooltip)


    def _populate_input_widget_ui(self, input_widget, container_widget, data):
        ''' called when a button is created for custom content '''
        layout = QtWidgets.QVBoxLayout(container_widget)
        status_widget = gremlin.ui.ui_common.QIconLabel()
        status_widget.setObjectName("status")
        layout.addWidget(status_widget)
        self._update_input_widget(input_widget, container_widget)

    def _select_input_item_cb(self, input_item, emit = True):
        ''' select by input '''
        input_id = input_item.input_id
        index = self.inputItemListModel.indexOf(input_id)
        if index == -1:
            self.clearFilter()
            index = self.inputItemListModel.indexOf(input_id)
        if index != -1:
            self.selectInputItemIndex(index)

    # def _select_item_cb(self, index, emit = True):
    #     """Handles the selection of an input item.

    #     :param index the index of the selected item
    #     """
    #     import gremlin.ui.input_item
    #     import gremlin.shared_state

    #     if not Shiboken.isValid(self.inputItemListView):
    #         return

    #     # self._last_selected_index = index
    #     input_item = None

    #     if index == -1:
    #         index = self._last_selected_index

    #     if index == -1:
    #         # select the first item
    #         if self.inputItemListModel.rows():
    #             input_item = self.inputItemListModel.data(0)
    #             index = 0
    #         else:
    #             self._blank_input()
    #             return
    #     else:
    #         input_item = self.inputItemListModel.data(index)


    #     device_guid = self.device_guid
    #     input_id = input_item.input_id if input_item else None
    #     input_type = InputType.OctaviIfr1

    #     if input_item:
    #         device_guid = self.device_guid
    #         key = self.getWidgetKey(input_type, input_id)
    #         widget = self.getRegisteredWidget(key)
    #         if not widget:
    #             widget = gremlin.ui.input_item.InputItemMappingWidget(input_item = input_item, object_name=f"IFR1: {input_item.display_name}")
    #             self.registerWidget(key, widget)
    #             widget.redraw() # load the data

    #         # Create new configuration widget

    #         change_cb = self._create_change_cb(index)
    #         widget._container_model.data_changed.connect(change_cb)
    #         widget.description_changed.connect(change_cb)

    #         self.selectRegisteredWidget(key)
    #         self.inputItemListView.scrollToIndex(index)
    #     else:
    #         profile = gremlin.shared_state.current_profile
    #         device_guid = gremlin.shared_state.octavi_tab_guid
    #         device_modes =  profile.get_device_modes(device_guid, DeviceType.to_string(DeviceType.Joystick))
    #         mode_object = device_modes.ensure_mode_exists(gremlin.shared_state.current_mode)
    #         input_item = gremlin.base_profile.InputItem(mode_object)
    #         widget = gremlin.ui.input_item.InputItemMappingWidget(input_item = input_item, object_name="IFR1 Blank InputConfigItem (no item data)")
    #         widget.redraw() # load the data

    #     #self.setRightPanelWidget(widget)

    #     self._last_selected_index = index
    #     self._item_data = widget
    #     self._last_selected_input_item = input_item


    #     # ensure visible


    #     if emit:
    #         el = gremlin.event_handler.EventListener()
    #         el.input_selection_changed.emit(device_guid, input_type, input_id)

    def _create_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.inputItemListView.redraw_index(index)

    def set_mode(self, mode):
        ''' changes the mode of the tab '''
        self.current_mode = mode
        self.device_profile.ensure_mode_exists(self.current_mode)
        self.inputItemListModel.mode = mode

        #self.inputItemListView.select_item(-1)
        if gremlin.shared_state.isDeviceTabActive(self.device_guid):
            self.inputItemListModel.refresh()
            self.selectInputItemIndex(self._last_selected_index)



    def refresh(self, emit = True):
        """Refreshes the current selection, ensuring proper synchronization."""
        self.inputItemListView.redraw(force = True)
        self.selectInputItemIndex(self.inputItemListView.current_index, emit)
