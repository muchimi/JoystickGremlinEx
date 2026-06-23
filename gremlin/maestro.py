
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
import os
import sys
import gremlin.util
# os.environ["PYTHONNET_PYDLL"] = r"C:\Python\python313\python313.dll"
from pythonnet import load

import gremlin
from gremlin.singleton_decorator import SingletonDecorator

syslog = logging.getLogger("system")

@SingletonDecorator
class Maestro():
  def __init__(self):


    # root = r"C:\HIDMaestro\dist"
    # sys.path.append(root)
    # clr.AddReference("HIDMaestro")

    # 1. Path to your HIDMaestro release folder
    hid_maestro_path = r"C:\HIDMaestro\dist"

    # 2. Configure pythonnet to use CoreCLR with HIDMaestro's runtime configuration
    runtime_config = os.path.join(hid_maestro_path, "HidMaestro.Core.runtimeconfig.")
    load("coreclr") #, runtime_config=runtime_config)

    # 3. Append the folder to the path so pythonnet can find the assembly dependencies
    sys.path.append(hid_maestro_path)
    import clr
    clr.AddReference("HIDMaestro.Core")


    import HIDMaestro

    self.ctx = HIDMaestro.HMContext()

    if gremlin.util.is_user_admin():
      syslog.info("User is admin, creating device.")
      self.createDevice()
    else:
      syslog.warning("User is not admin, device creation skipped.")

  def createDevice(self, axis_count : int = 8, button_count : int = 128, hat_count : int = 4, vid = 0x1209, pid = 0x1000):



      import HIDMaestro
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



      builder = HIDMaestro.HMProfileBuilder()
      builder = builder.Id("gex device") # .Id("gex device").name("GEX Custom Device").vendor("GEX").Vid(0x1209).Pid(0x1000).ProductString("GEX Custom Device").Type("flightstick").Build()
      builder = builder.Name("GEX Custom Device")
      builder = builder.Vendor("GEX")
      builder = builder.Vid(0x1209)
      builder = builder.Pid(0x1000)
      builder = builder.ProductString("GEX Custom Device")
      builder = builder.Type("flightstick")
      builder = builder.FromDescriptorBuilder(descriptor)
      builder = builder.Build()


      # builder = HIDMaestro.HMProfileBuilder().
      # builder.Id = "gex device"
      # builder.Name = "GEX Custom device"
      # builder.vendor = "GEX"
      # builder.Vid = 0x045E
      # builder.ProductString = "custom device 1"
      # builder.Pid = pid
      # builder.ManufacturerString = "GremlinEx"
      # builder.Type = "flightstick"
      # builder.Connection = "usb"
      # builder.ButtonCount = 16
      # builder.AxisCount = 8

      # builder.FromDescriptorBuilder(descriptor)
      # builder.Build()

      self.controller : HIDMaestro.HMController = self.ctx.CreateController(builder)






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