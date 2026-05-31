
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

import clr
import sys

from gremlin.singleton_decorator import SingletonDecorator


left_vpc_json = '''
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

'''

vjoy_128_json = '''
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
'''

@SingletonDecorator
class HIDMaestro():
  def __init__(self):
    root = "C:\\HIDMaestro\\build"
    sys.path.append(root)
    clr.AddReference("HIDMaestro")
    import HIDMaestro
    self.ctx = HIDMaestro.HMContext()
    self.createDevice()

  def createDevice(self, axis_count : int = 8, button_count : int = 128, hat_count : int = 4, vid = 0x1209, pid = 0x1000):

      descriptor = HIDMaestro.HidDescriptorBuilder()
      descriptor = descriptor.Joystick()
      descriptor = descriptor.AddStick("X", bits = 16)
      descriptor = descriptor.AddStick("Y", bits = 16)
      descriptor = descriptor.AddStick("Z", bits = 16)
      descriptor = descriptor.AddStick("RX", bits = 16)
      descriptor = descriptor.AddStick("RY", bits = 16)
      descriptor = descriptor.AddStick("RZ", bits = 16)
      descriptor = descriptor.AddStick("S1", bits = 16)
      descriptor = descriptor.AddStick("S2", bits = 16)
      descriptor = descriptor.AddButtons(128)
      descriptor = descriptor.AddHat()
      descriptor = descriptor.AddHat()
      descriptor = descriptor.AddHat()
      descriptor = descriptor.AddHat()
      descriptor = descriptor.AddPidFfbBlock()


      device = HIDMaestro.HMProfileBuilder()
      device.Id = "gex device"
      device.Name = "GEX Custom device"
      device.vendor = "GEX"
      device.Vid = vid
      device.ProductString = "custom device 1"
      device.Pid = pid
      device.ManufacturerString = "GremlinEx"
      device.Type = "flightstick"
      device.Connection = "usb"
      device.FromDescriptorBuilder(descriptor)
      device.Build()

      self.controller : HIDMaestro.HMController = self.ctx.CreateController(device)


