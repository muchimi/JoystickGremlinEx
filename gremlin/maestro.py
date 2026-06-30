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

"""HIDMaestro Python interface

This module lets GEX create and manage virtual controllers created through HIDMaestro.

https://github.com/hifihedgehog/HIDMaestro

This module interfaces with the .NET framework.

In general, the way it works is a buffer of bytes representing the axis, button and hat states of controllers created by GEX is kept in memory and output.
This buffer is changed whenever an axis, button or hat is output.
On startup, the buffer is synchronized with the directInput data.

GEX can create up to 16 devices mirroring VJOY setups each device with a default of 8 axes, 128 buttons and 4 hats.

To be able to create or remove devices, GEX must run in admin mode to get the rights.
This is predicated on HIDMaestro having been compiled on the current machine per the HIDMaestro instructions to allow an unsigned local non-kernel mode HID driver to manage these virtual devices.

"""

import logging
import os
import sys
import time
import threading

from sympy.physics.mechanics import System
import gremlin.util
import dinput

# os.environ["PYTHONNET_PYDLL"] = r"C:\Python\python313\python313.dll"


import gremlin
from gremlin.singleton_decorator import SingletonDecorator
import gremlin.config
import gremlin.util
from dinput import GEX_VID, GEX_ID_STRING, GEX_MAX_DEVICES, GEX_PID_BASE, GEX_VENDOR_STRING, GEX_PRODUCT_STRING

syslog = logging.getLogger("system")

# initialize Maestro context
try:
    # path to the HIDMaestro compiled distributables
    _maestro_initialized = False
    # config = gremlin.config.Configuration()
    # if not config.maestro_enabled:
    #     hid_maestro_path = config.maestro_dist_path
    #     if not os.path.exists(hid_maestro_path):
    #         syslog.info(f"HIDMaestro disabled: no distribution files found in path not found: {hid_maestro_path}")
    #     else:
    #         # load the .NET Core runtime using pythonnet
    #         from pythonnet import load
    #         load("coreclr")

    #         # ensure it can find the dependencies for the HIDMaestro assembly
    #         sys.path.append(hid_maestro_path)

    #         import clr

    #         clr.AddReference("HIDMaestro.Core")

    #         # .net imports
    #         import HIDMaestro
    #         from HIDMaestro import *
    #         from HIDMaestro import HMGamepadState
    #         import System
    #         from System.Collections.Generic import Dictionary

    #         _maestro_initialized = True


except Exception as e:
    syslog.error(f"Failed to initialize Maestro context: {e}")
    _maestro_initialized = False


@SingletonDecorator
class Maestro:
    def __init__(self):
        global _maestro_initialized
        self._controller_map = {}  # holds the created controllers by index (0 to GEX_MAX_DEVICES-1)
        self._device_map = {}  # map of the created devices by index to dinput.DeviceSummary device
        self._descriptor_map = {}  # map of the created descriptors by index
        self._buffer_map = {}  # map of the buffers for each device by index
        self.ctx = None  # maestro context
        self._dirty = False  # true if a controller was created and we need a resync
        self._sync_worker = None  # synchronization thread used to syn dinput devices with changed maestro devices
        self._sync_lock = threading.Lock()  # lock to synchronize access to the sync worker

        # self.ctx = HIDMaestro.HMContext()
        # self.removeAllControllers() # clean slate
        # sys.exit(0)

        config = gremlin.config.Configuration()
        self._maestro_enabled = config.maestro_enabled

        if not _maestro_initialized or not self._maestro_enabled:
            syslog.info("MAESTRO: disabled")
            return

        syslog.info("MAESTRO: starting...")
        maestro_count = config.maestro_device_count

        # supress device change notices
        el = gremlin.event_handler.EventListener()
        el.pushDeviceChangeSuppression()
        el.shutdown.connect(self._handle_shutdown)
        gremlin.shared_state.ui.pushSuspendTabUpdate()


        self.ctx = HIDMaestro.HMContext()
        self.removeAllControllers() # clean slate
        # map the existing devices
        for i in range(maestro_count):
            if i not in self._controller_map:
                self.createJoystickController()

        syslog.info(f"Maestro: devices created: {len(self._controller_map)}")

        # synchronize
        if not self.sync(force=True):
            # sync not required
            el.popDeviceChangeSuppression()
            gremlin.shared_state.ui.popSuspendTabUpdate()

    def _handle_shutdown(self):
        if self._maestro_enabled and self.ctx:
            syslog.info("MAESTRO: shutdown")
            self.ctx.Dispose() # cleanup

    def LoadActiveControllers(self):
        """loads the active maestro controllers"""
        if self._maestro_enabled and _maestro_initialized:
            for controller in self.ctx.ActiveControllers:
                if controller.Index not in self._controller_map:
                    self._controller_map[controller.Index] = controller

    def reset(self):
        """resets the maestro configuration"""

        if self._maestro_enabled and _maestro_initialized:
            if gremlin.util.is_user_admin():
                # self.removeAllControllers()

                # syslog.info("User is admin, creating device.")
                self.sync(True)
            else:
                syslog.warning("User is not admin, device creation skipped.")

    def sync(self, force=False) -> bool:
        """syncs dinput with maestro"""
        if self._dirty or force:
            diff = self._compare_list()
            if diff and self._sync_worker is None:
                with self._sync_lock:
                    self._sync_worker = threading.Thread(target=self._sync_worker_runner)
                self._sync_worker.start()
                return True
        return False  # sync not required

    def _sync_worker_runner(self):
        """worker thread to sync dinput devices with changed maestro devices"""
        el = gremlin.event_handler.EventListener()
        el.pushDeviceChangeSuppression()
        syslog.info("Maestro: Starting sync worker")
        timeout = time.time() + 20
        diff = self._compare_list()
        while diff and time.time() < timeout:
            self.syncControllers()
            diff = self._compare_list()
            syslog.info("waiting for sync...")

        if diff:
            syslog.warning("Maestro: sync worker timed out before all changes were applied")

        syslog.info("Maestro: sync completed")

        with self._sync_lock:
            self._sync_worker = None  # reset the sync worker when done

        # reload the joystick configuration
        gremlin.joystick_handling.joystick_devices_initialization()

        el.popDeviceChangeSuppression()
        gremlin.shared_state.ui.popSuspendTabUpdate()

    def _compare_list(self) -> bool:
        """compares the maestro device list to the dinput maestro list to see if all dinput devices are accounted for"""
        maestro_pid_set = set([controller.Profile.ProductId for controller in self._controller_map.values()])
        maestro_count = len(maestro_pid_set)
        if maestro_count == 0:
            # mo maestro devices yet
            return True
        device_pid_set = set([device.product_id for device in dinput.DILL.getMaestroDevices()])
        if len(device_pid_set) != maestro_count:
            # not the same
            return True

        diff = maestro_pid_set != device_pid_set
        return diff

    @property
    def initialized(self):
        global _maestro_initialized
        return _maestro_initialized

    @property
    def enabled(self) -> bool:
        config = gremlin.config.Configuration()
        return self.initialized and config.maestro_enabled

    def getController(self, key: tuple):
        """gets a created maestro controller"""
        return self._controller_map.get(key, None)

    def getAllDevices(self) -> list[HIDMaestro.HMController]:
        """gets the list of maestro devices we created"""
        devices = HIDMaestro.HMDeviceExtractor.ListDevices()
        return devices

    def syncControllers(self):
        """gets a list of defined controllers via direct input"""

        # acquire the sync lock to ensure thread safety while syncing controllers
        with self._sync_lock:
            all_devices = dinput.DILL.getMaestroDevices()
            for device in all_devices:
                syslog.info(f"Found GEX managed device: 0x{device.product_id:x}.0x{device.vendor_id:x} {device.name}")
                # check if we already have a controller for this device
                index = device.product_id - GEX_PID_BASE
                if index not in self._controller_map:
                    syslog.info(f"Creating controller for GEX managed device: 0x{device.product_id:x}.0x{device.vendor_id:x} {device.name}")
                    self.createJoystickController(at_index=index)
                self._device_map[index] = device

            self._dirty = False

    def addMissingControllers(self):
        """adds any missing controllers for GEX managed devices"""
        for i in range(4):
            if i not in self._controller_map:
                syslog.info(f"Creating missing controller for GEX managed device at index {i}")
                self.createJoystickController(at_index=i)

    def removeController(self, controller):
        """removes the given controller"""
        index = next((k for k, v in self._controller_map.items() if v == controller), None)
        if index is not None:
            del self._controller_map[index]
            del self._device_map[index]
        controller.Dispose()
        self._dirty = True

    def removeAllControllers(self):
        if not gremlin.util.is_user_admin():
            syslog.warning("Maestro: removing controllers requires GEX to run in admin mode")
            return
        self.ctx.RemoveAllVirtualControllers()
        self._controller_map.clear()
        self._descriptor_map.clear()
        self._device_map.clear()
        self._dirty = True
        syslog.info("Maestro: all devices removed.")

    def createJoystickController(self, axis_count: int = 8, button_count: int = 128, hat_count: int = 4, at_index: int = None):
        """creates a joystick controller with the specified number of axes, buttons, and hats.
        If at_index is specified, attempts to create the controller at the given index.

        :param axis_count: number of axes for the joystick
        :param button_count: number of buttons for the joystick
        :param hat_count: number of hats for the joystick
        :param at_index: if specified, attempts to create the controller at the given index
        """
        if not gremlin.util.is_user_admin():
            syslog.warning("Maestro: creating controllers requires GEX to run in admin mode")
            return None
        if at_index is not None:
            index = at_index
        else:
            index = len(self._controller_map)
        if index >= GEX_MAX_DEVICES:
            syslog.warning(f"Maestro: cannot create more than {GEX_MAX_DEVICES} devices.")
            return None
        pid = GEX_PID_BASE + index  # build the PID as an index
        product_string = f"{GEX_PRODUCT_STRING} {index}"



        try:
            # build a joystick descriptor for the HID device
            axis_data = [
                HIDMaestro.HMAxis.X,
                HIDMaestro.HMAxis.Y,
                HIDMaestro.HMAxis.Z,
                HIDMaestro.HMAxis.Rx,
                HIDMaestro.HMAxis.Ry,
                HIDMaestro.HMAxis.Rz,
                HIDMaestro.HMAxis.Slider,
                HIDMaestro.HMAxis.Dial,
            ][:axis_count]

            descriptor = HidDescriptorBuilder()
            # setup as a joystick
            descriptor = descriptor.Joystick()
            # add axes by role
            for role in axis_data:
                descriptor = descriptor.AddAxis(role, bits=16)  # use 16 bit resolution for the axis
            # add buttons
            descriptor = descriptor.AddButtons(button_count)
            # add hats
            for _ in range(hat_count):
                descriptor = descriptor.AddHat()

            descriptor = descriptor.AddPidFfbBlock()

            report_size = (axis_count * 16 + button_count + hat_count * 4) // 8  # 16 bits per axis, 1 bit per button, 4 bits per hat, convert to bytes

            profile = HMProfileBuilder()
            profile = profile.Id(GEX_ID_STRING)
            profile = profile.Name(product_string)
            profile = profile.Vendor(GEX_VENDOR_STRING)
            profile = profile.Vid(GEX_VID)
            profile = profile.Pid(pid)
            profile = profile.ProductString(product_string)
            profile = profile.Type("flightstick")
            profile = profile.FromDescriptorBuilder(descriptor)
            profile = profile.InputReportSize(report_size)  # 8 axes
            profile = profile.Build()

            controller: HMController = self.ctx.CreateControllerAt(index, profile)
            self._controller_map[index] = controller

            state = HMGamepadState()
            # set the initial state of each axis to center
            axis_values = Dictionary[HIDMaestro.HMAxis, System.Single]()
            for role in axis_data:
                axis_values[role] = 0.5  # 0.5 represents the center position for the axis

            # set button 4 to pressed
            buttons = 1 << 4  # set button 4 to pressed

            state.Axes = axis_values
            state.Buttons = HMButton(buttons)

            controller.SubmitState(state)  # update the controller with the initial state
            self._dirty = True


            return controller

        except Exception as e:
            syslog.error(f"Maestro: failed to create device: {e}")

    def getDevice(self, pid: int):
        """gets the dinput device for the given pid"""
        devices = dinput.DILL.getDevices()
        dev: dinput.DeviceSummary
        index = self.pidToIndex(pid)
        if self._dirty:
            self.syncControllers()
            self._dirty = False  # reset the dirty flag after syncing controllers
        if index in self._device_map:
            return self._device_map[index]

        max_pid = GEX_PID_BASE + GEX_MAX_DEVICES - 1
        for dev in devices:
            syslog.info(
                f"Maestro: checking device [{dev.name}] product: [0x{dev.product_id:04X}] vendor: [0x{dev.vendor_id:04X}] axis count: [{dev.axis_count}] button count: [{dev.button_count}] hat count: [{dev.hat_count}]"
            )
            if dev.vendor_id == GEX_VID and dev.product_id >= GEX_PID_BASE and dev.product_id <= max_pid:
                return dev
        return None

    def pidToIndex(self, pid: int) -> int:
        """converts a product id to a controller index"""
        index = pid - GEX_PID_BASE
        if index < 0 or index >= GEX_MAX_DEVICES:
            return -1
        return index

    def getBuffer(self, device_index):
        """gets a byte buffer for the given device"""
        if device_index in self._buffer_map:
            return self._buffer_map[device_index]
        if device_index in self._device_map:
            device: dinput.DeviceSummary = self._device_map[device_index]
            axis_count = device.axis_count
            button_count = device.button_count
            hat_count = device.hat_count
            report_size = (axis_count * 16 + button_count + hat_count * 4) // 8  # 16 bits per axis, 1 bit per button, 4 bits per hat, convert to bytes
            self._buffer_map[device_index] = bytearray(report_size)
            return self._buffer_map[device_index]
        return None

    def syncBuffer(self, device_index: int):
        """synchronizes a dinput device state with the report buffer"""
        buffer = self.getBuffer(device_index)
        device: dinput.DeviceSummary = self._device_map.get(device_index, None)
        if device is None or buffer is None:
            return
        axis_count = device.axis_count
        button_count = device.button_count
        hat_count = device.hat_count
        device_guid = device.device_guid

        for axis in range(1, axis_count + 1):
            value = gremlin.joystick_handling.getAxis(device_guid, axis)
            self._set_axis(buffer, axis, value)
        for button in range(1, button_count + 1):
            value = gremlin.joystick_handling.getButton(device_guid, button)
            self._set_button(buffer, button, value)
        for hat in range(1, hat_count + 1):
            value = gremlin.joystick_handling.getHat(device_guid, hat)
            self._set_hat(buffer, hat, value)

    def _set_axis(self, buffer, axis_index: int, value: float):
        axis_index -= 1  # convert to 0-based index
        scaled_value = gremlin.util.scale_to_range(value, -1.0, 1.0, 0, 1)
        # calculate the byte and bit offset for the axis
        byte_offset = axis_index * 2  # 16 bits per axis
        # little endian format
        buffer[byte_offset] = scaled_value & 0xFF
        buffer[byte_offset + 1] = (scaled_value >> 8) & 0xFF
        return buffer

    def setAxis(self, device_index: int, axis_index: int, value: float):
        """sets a maestro controller 16 bit axis
        :param device_index: the index of the maestro controller device
        :param axis_index: the index of the axis to set (1-based)
        :param value: the value to set the axis to (float between -1.0 and 1.0)
        """

        if device_index in self._controller_map:
            buffer = self.getBuffer(device_index)
            if buffer is None:
                return
            self._set_axis(buffer, axis_index - 1, value)  # convert to 0-based index
            # update the controller with the new buffer state

            controller: HIDMaestro.HMController = self._controller_map[device_index]
            controller.SubmitRawReport(buffer)

    def _set_button(self, device_index: int, button_index: int, is_pressed: bool):
        buffer = self.getBuffer(device_index)
        if buffer is None:
            return
        device: dinput.DeviceSummary = self._device_map.get(device_index, None)
        if device is None or buffer is None:
            return
        axis_count = device.axis_count
        button_offset = axis_count * 16 // 8  # calculate the byte offset where the button bytes start
        button_index -= 1  # 0 based button index
        byteOffset = button_index // 8  # calculate the byte offset for the button index
        bitOffset = button_index % 8  # calculate the bit offset within the byte for the button index
        targetByteIndex = button_offset + byteOffset  # calculate the target byte index within the report buffer
        mask = 1 << bitOffset  # calculate the bit mask for the button within the target byte

        # build the button mask
        if is_pressed:
            buffer[targetByteIndex] |= mask
        else:
            buffer[targetByteIndex] &= ~mask
        return buffer

    def setButton(self, device_index: int, button_index: int, is_pressed: bool):
        """sets a maestro controller button"""
        if device_index in self._device_map:
            buffer = self.getBuffer(device_index)
            if buffer is None:
                return
            buffer = self._set_button(device_index, button_index, is_pressed)
            controller: HIDMaestro.HMController = self._controller_map[device_index]
            controller.SubmitRawReport(buffer)
        else:
            button_count = self._device_map[device_index].button_count
            syslog.info(f"Error: button index {button_index} out of range (0-{button_count - 1})")

    def _set_hat(self, device_index: int, hat_index: int, value: int):
        buffer = self.getBuffer(device_index)
        if buffer is None:
            return
        device: dinput.DeviceSummary = self._device_map.get(device_index, None)
        if device is None or buffer is None:
            return
        axis_count = device.axis_count
        button_count = device.button_count

        hat_offset = (axis_count * 16 // 8) + (button_count // 8)  # calculate the byte offset where the hat bytes start
        hat_index -= 1  # 0 based hat index
        byteOffset = hat_index // 2  # calculate the byte offset for the hat index
        bitOffset = (hat_index % 2) * 4  # calculate the bit offset within the byte for the hat index (4 bits per hat)
        targetByteIndex = hat_offset + byteOffset  # calculate the target byte index within the report buffer
        # clear the existing hat bits
        buffer[targetByteIndex] &= ~(0xF << bitOffset)
        # set the new hat position
        buffer[targetByteIndex] |= (value & 0xF) << bitOffset
        return buffer

    def setHat(self, device_index: int, hat_index: int, position: tuple):
        """sets a maestro controller hat position using a GEX hat position"""
        if device_index in self._device_map:
            device: dinput.DeviceSummary = self._device_map[device_index]
            controller: HIDMaestro.HMController = self._controller_map[device_index]

            """HMHat enum values:
            None      = 0,
            North     = 1,
            NorthEast = 2,
            East      = 3,
            SouthEast = 4,
            South     = 5,
            SouthWest = 6,
            West      = 7,
            NorthWest = 8,
            """
            match position:
                case (0, 0):
                    hat_position = 0  # None

                case (0, 1):
                    hat_position = 1  # North

                case (1, 1):
                    hat_position = 2  # NorthEast

                case (1, 0):
                    hat_position = 3  # East

                case (1, -1):
                    hat_position = 4  # SouthEast

                case (0, -1):
                    hat_position = 5  # South

                case (-1, -1):
                    hat_position = 6  # SouthWest

                case (-1, 0):
                    hat_position = 7  # West

                case (-1, 1):
                    hat_position = 8  # NorthWest

                case _:
                    hat_position = 0  # Default to None if an unknown position is provided

            buffer = self._set_hat(device_index, hat_index, hat_position)
            controller: HIDMaestro.HMController = self._controller_map[device_index]
            controller.SubmitRawReport(buffer)

    def removeDevice(self):
        if hasattr(self, "controller") and self.controller is not None:
            self.ctx.RemoveController(self.controller)
            key = self.getControllerKey(self.controller)
            if key in self._controller_map:
                del self._controller_map[key]
            self.controller = None


left_vpc_json = """
{
  "id": "l-vpc-stick-warbrd",
  "name": "L-VPC Stick WarBRD",
  "vendor": "VIRPIL Controls 20240323",
  "vid": "0x3344",
  "pid": "0x80CB",
  "productString": "L-VPC Stick WarBRD",
  "manufacturerString": "VIRPIL Controls 20240323",
  "deviceDescription": "L-VPC Stick WarBRD",
  "type": "joystick",
  "connection": "usb",
  "descriptor": "05010904a101850109300931093409330936093215002760ea000075109506810275089508810305091901291f15002501750195808102c0",
  "inputReportSize": null,
  "notes": "Extracted by HMDeviceExtractor on 2026-05-30 23:04:31 UTC. Descriptor reconstructed from Windows preparsed data (HIDAPI algorithm); logically equivalent to the physical device's HID report descriptor but not guaranteed byte-identical."
}

"""

vjoy_128_json = """
{
  "id": "vjoy-virtual-joystick",
  "name": "vJoy - Virtual Joystick",
  "vendor": "Shaul Eizikovich",
  "vid": "0x1234",
  "pid": "0xBEAD",
  "productString": "vJoy - Virtual Joystick",
  "manufacturerString": "Shaul Eizikovich",
  "deviceDescription": "vJoy - Virtual Joystick",
  "type": "joystick",
  "connection": "usb",
  "descriptor": "05010904a1010901a100850109300931093209330934093509360937150026ff7f752095088102c009390939093909391500273c8c00003500473c8c000065147520950481020509190129801500250175019580450065008102c0",
  "inputReportSize": null,
  "notes": "Extracted by HMDeviceExtractor on 2026-05-30 23:06:56 UTC. Descriptor reconstructed from Windows preparsed data (HIDAPI algorithm); logically equivalent to the physical device's HID report descriptor but not guaranteed byte-identical."
}
"""
