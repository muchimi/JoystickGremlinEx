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

"""GEX HIDMaestro Bridge service and interface.


The GEX Maestro Bridge Service is a background Windows service that lets GEX communicate with HIDMaestro devices without
requiring direct administrator privileges.  The Bridge Service is a separate open source project on GitHub written in C#.

Details on the Maestro Bridge Service: https://github.com/muchimi/GEXMaestroBridgeService

Details on the HIDMaestro open source project: https://github.com/hifihedgehog/HIDMaestro

In order to use HIDMaestro devices with GEX, the bridge service must be installed and running on the machine that will use Maestro virtual devices.
This can be the same machine as GEX, or a different machine on the same network.

The bridge service talks to GEX over the OSC protocol using IPv4 UDP.  This allows relatively simple, readable and low
overhead two way binary communication between GEX (Python/C++) and the bridge service (HIDMaestro/C#).

The use of the OSC protocol is distinct from the OSC device support in GEX, so runs on a separate IP/Port/Channel.

This design eliminates the need for GEX to talk directly to .NET, and the OSC protocol offers easier cross-language communication.
The use of OSC is similar to the OSC commands used by other OSC devices to exchange data with GEX so will be familiar.
The translation layer that maps GEX mapping actions to VJOY is identical for Maestro devices.
In other words, from GEX's perspective, a Maestro device behaves just like a Vjoy device.

The GEX is able, via this module and the bridge service, to:
- Enumerate available HIDMaestro profiles, definitions, and devices.
- Create, activate, rename, and remove joystick and gamepad (xbox 360 wireless emulated) devices via Maestro.
- Output via vjoy remap to a Maestro gamepad device automatically maps the corresponding axes, buttons, and hats to the gamepad controller.
- Query and manage connected HIDMaestro devices.
- Obtain axis, button and hat states from connected HIDMaestro devices.
- Send axis, button and hat states to connected HIDMaestro devices asynchronously.
- Provides an interface to manage these services in the GEX user interface.

This is managed from within GEX's Maestro devices option dialog so that GEX is aware of Maestro devices it can use.
Mapping to Maestro devices is done via the usual vjoy remap and the bridge service handles all the necessary translations.
This is designed so a Maestro device looks exactly like a Vjoy device.

Firewall rules must allow the UDP traffice on the given port.

To test connectivity on a different machine, use ncat (nmap) with the appropriate IP and port.
- on the machine listening to a port (8010), run the command from a command line:
  `ncat -lu 8010`

- on the machine sending to the port (8010), run the command from a command line:
  `ncat -u <IP_OF_LISTENING_MACHINE> 8010`

- Flip the roles on the machine to test the reverse direction of communication (8011 default)
  - on the machine listening to a port (8011), run the command from a command line:
    `ncat -lu 8011`

  - on the machine sending to the port (8011), run the command from a command line:
    `ncat -u <IP_OF_LISTENING_MACHINE> 8011`




HIDMaestro - Default Embedded Profile Catalog
Retrieved: November 3, 2026
Repository: https://github.com/hifihedgehog/HIDMaestro
Branch snapshot: master
Commit: 77c4ddbad6cff428e79bc5f76d84eeef85cc8c7f
Profile count: 337

Profile ID                                 | Display name                                                | Vendor                         | Device type
-------------------------------------------+-------------------------------------------------------------+--------------------------------+------------
8bitdo-pro-2                               | 8BitDo Pro 2                                                | 8BitDo                         | gamepad
8bitdo-retro-mechanical-keyboard           | 8BitDo Retro Mechanical Keyboard                            | 8BitDo                         | keyboard
8bitdo-sn30-pro                            | 8BitDo SN30 Pro                                             | 8BitDo                         | gamepad
8bitdo-ultimate-wired                      | 8BitDo Ultimate Wired Controller                            | 8BitDo                         | gamepad
p5general-activtor                         | P5 General (PS5-compatible Activtor)                        | Activtor                       | gamepad
circuitpython-gamepad                      | Adafruit CircuitPython Standard Gamepad                     | Adafruit                       | gamepad
amazon-luna-ble                            | Amazon Luna Controller (Bluetooth LE)                       | Amazon                         | gamepad
amazon-luna-usb                            | Amazon Luna Controller (USB)                                | Amazon                         | gamepad
apple-keyboard-a1243                       | Apple Keyboard A1243                                        | Apple                          | keyboard
apple-magic-keyboard-a1644                 | Apple Magic Keyboard A1644 (USB)                            | Apple                          | keyboard
apple-magic-keyboard-touch-id-numeric      | Apple Magic Keyboard with Touch ID and Numeric Keypad (USB) | Apple                          | keyboard
apple-pro-mouse                            | Apple Pro Mouse                                             | Apple                          | mouse
apple-wireless-keyboard                    | Apple Wireless Keyboard (Bluetooth)                         | Apple                          | keyboard
asetek-forte-pedals                        | Asetek SimSports Forte Pedals                               | Asetek                         | pedals
asetek-forte                               | Asetek SimSports Forte Wheelbase                            | Asetek                         | wheel
asetek-invicta-pedals                      | Asetek SimSports Invicta Pedals                             | Asetek                         | pedals
asetek-invicta                             | Asetek SimSports Invicta Wheelbase                          | Asetek                         | wheel
asetek-la-prima                            | Asetek SimSports La Prima Wheelbase                         | Asetek                         | wheel
asetek-tony-kanaan                         | Asetek SimSports Tony Kanaan Wheelbase                      | Asetek                         | wheel
asus-rog-gladius                           | ASUS ROG Gladius                                            | ASUS                           | mouse
asus-rog-spatha                            | ASUS ROG Spatha                                             | ASUS                           | mouse
cammus-c12                                 | Cammus C12 Wheelbase                                        | Cammus                         | wheel
cammus-c5                                  | Cammus C5 Wheelbase                                         | Cammus                         | wheel
ch-combatstick                             | CH Products Combatstick                                     | CH Products                    | joystick
ch-f16-combat-stick                        | CH Products F-16 Combat Stick                               | CH Products                    | joystick
ch-fighterstick                            | CH Products Fighterstick                                    | CH Products                    | joystick
ch-flight-sim-yoke                         | CH Products Flight Sim Yoke                                 | CH Products                    | other
ch-pro-pedals                              | CH Products Pro Pedals                                      | CH Products                    | pedals
ch-pro-throttle                            | CH Products Pro Throttle                                    | CH Products                    | other
ch-throttle-quadrant                       | CH Products Throttle Quadrant                               | CH Products                    | other
cherry-g83-rs6000                          | Cherry G83 (RS 6000)                                        | Cherry                         | keyboard
cherry-kc-6000-slim                        | Cherry KC 6000 Slim                                         | Cherry                         | keyboard
cherry-strait-3                            | Cherry Strait 3.0                                           | Cherry                         | keyboard
cooler-master-ck352                        | Cooler Master CK352                                         | Cooler Master                  | keyboard
corsair-harpoon-rgb-wireless               | Corsair Harpoon RGB Wireless                                | Corsair                        | mouse
corsair-k55-rgb-pro-xt                     | Corsair K55 RGB PRO XT                                      | Corsair                        | keyboard
corsair-k70-rgb-mk2-low-profile            | Corsair K70 RGB MK.2 Low Profile                            | Corsair                        | keyboard
corsair-k70-rgb-rapidfire                  | Corsair K70 RGB RAPIDFIRE                                   | Corsair                        | keyboard
corsair-k95-rgb-platinum-xt                | Corsair K95 RGB Platinum XT                                 | Corsair                        | keyboard
corsair-m65-rgb-ultra                      | Corsair M65 RGB Ultra                                       | Corsair                        | mouse
corsair-scimitar-rgb-elite                 | Corsair Scimitar RGB Elite                                  | Corsair                        | mouse
corsair-strafe-rgb                         | Corsair STRAFE RGB                                          | Corsair                        | keyboard
daemonbite-nes                             | DaemonBite NES Controller Adapter                           | DaemonBite                     | gamepad
daemonbite-genesis                         | DaemonBite Sega Genesis/Saturn Controller Adapter           | DaemonBite                     | gamepad
daemonbite-snes                            | DaemonBite SNES Controller Adapter                          | DaemonBite                     | gamepad
dell-ms116                                 | Dell MS116                                                  | Dell                           | mouse
dragonrise-dvtech-js19                     | DragonRise DVTech JS19 Gamepad                              | DragonRise                     | gamepad
dragonrise-0006                            | DragonRise Generic Gamepad (PC TWIN SHOCK)                  | DragonRise                     | gamepad
dragonrise-twin-shock-0006                 | DragonRise PC TWIN SHOCK Gamepad                            | DragonRise                     | gamepad
retrolink-snes-0011                        | Retrolink/DragonRise SNES USB Controller                    | DragonRise                     | gamepad
drevo-blademaster-te                       | DREVO BladeMaster TE                                        | DREVO                          | keyboard
ducky-dk2108                               | Ducky DK2108                                                | Ducky                          | keyboard
fanatec-clubsport-handbrake                | Fanatec ClubSport Handbrake V1.5                            | Fanatec                        | other
fanatec-clubsport-pedals-v3                | Fanatec ClubSport Pedals V3                                 | Fanatec                        | pedals
fanatec-clubsport-shifter                  | Fanatec ClubSport Shifter SQ V1.5                           | Fanatec                        | other
fanatec-clubsport-v2                       | Fanatec ClubSport V2 Wheelbase                              | Fanatec                        | wheel
fanatec-clubsport-v25                      | Fanatec ClubSport V2.5 Wheelbase                            | Fanatec                        | wheel
fanatec-csl-dd                             | Fanatec CSL DD Wheelbase                                    | Fanatec                        | wheel
fanatec-csl-elite-pedals-lc                | Fanatec CSL Elite Pedals LC V1                              | Fanatec                        | pedals
fanatec-csl-elite-ps4                      | Fanatec CSL Elite PS4 Wheelbase                             | Fanatec                        | wheel
fanatec-csl-elite-pedals-v2                | Fanatec CSL Elite V2 Pedals                                 | Fanatec                        | pedals
fanatec-csl-elite                          | Fanatec CSL Elite Wheelbase                                 | Fanatec                        | wheel
fanatec-csl-pedals                         | Fanatec CSL Pedals                                          | Fanatec                        | pedals
fanatec-csr-elite                          | Fanatec CSR Elite Wheelbase                                 | Fanatec                        | wheel
fanatec-podium-dd1                         | Fanatec Podium DD1                                          | Fanatec                        | wheel
fanatec-podium-dd2                         | Fanatec Podium DD2                                          | Fanatec                        | wheel
ffbeast-joystick                           | FFBeast Force Feedback Joystick                             | FFBeast                        | joystick
ffbeast-rudder                             | FFBeast Force Feedback Rudder                               | FFBeast                        | pedals
ffbeast-wheel                              | FFBeast Force Feedback Wheel                                | FFBeast                        | wheel
vader-4-pro                                | Flydigi Vader 4 Pro                                         | Flydigi                        | gamepad
generic-dinput-gamepad                     | Generic DirectInput USB Gamepad                             | Generic                        | gamepad
mpg-hid-gamepad                            | MPG/FeralAI HID Gamepad (Hori FC Clone)                     | Generic                        | gamepad
ps3-alt-gamepad                            | PS3-compatible Alt Gamepad (GP2040-CE)                      | Generic                        | gamepad
tinyusb-generic-gamepad                    | TinyUSB Generic Gamepad (RP2040/ESP32)                      | Generic                        | gamepad
tinyusb-gamepad-no-reportid                | TinyUSB Standard Gamepad (No Report ID)                     | Generic                        | gamepad
nicohood-arduino-gamepad                   | NicoHood Arduino HID Gamepad (Generic)                      | Generic/Arduino                | gamepad
genius-gila                                | Genius Gila                                                 | Genius                         | mouse
genius-imperator                           | Genius Imperator                                            | Genius                         | keyboard
glorious-gmmk-pro                          | Glorious GMMK Pro                                           | Glorious                       | keyboard
stadia-controller-bt                       | Google Stadia Controller (Bluetooth)                        | Google                         | gamepad
stadia-controller-usb                      | Google Stadia Controller (USB)                              | Google                         | gamepad
simucube-1                                 | Simucube 1                                                  | Granite Devices                | wheel
simucube-2-pro                             | Simucube 2 Pro                                              | Granite Devices                | wheel
simucube-2-sport                           | Simucube 2 Sport                                            | Granite Devices                | wheel
simucube-2-ultimate                        | Simucube 2 Ultimate                                         | Granite Devices                | wheel
heusinkveld-handbrake-v2                   | Heusinkveld Handbrake V2                                    | Heusinkveld                    | other
heusinkveld-sequential-shifter             | Heusinkveld Sequential Shifter                              | Heusinkveld                    | other
heusinkveld-sprint-pedals                  | Heusinkveld Sprint Pedals                                   | Heusinkveld                    | pedals
heusinkveld-ultimate-pedals                | Heusinkveld Ultimate Pedals                                 | Heusinkveld                    | pedals
honeycomb-alpha                            | Honeycomb Alpha Flight Controls (Yoke)                      | Honeycomb                      | other
honeycomb-bravo                            | Honeycomb Bravo Throttle Quadrant                           | Honeycomb                      | other
hori-fighting-stick-alpha                  | HORI Fighting Stick Alpha (PS5)                             | HORI                           | arcadestick
hori-pcengine-mini                         | HORI PC Engine Mini Pad                                     | HORI                           | gamepad
hori-pokken-controller                     | HORI POKKEN Controller (Switch)                             | HORI                           | gamepad
hori-racing-wheel-apex                     | HORI Racing Wheel Apex                                      | HORI                           | wheel
hori-rap-v-kai                             | HORI Real Arcade Pro V Kai (Xbox)                           | HORI                           | arcadestick
hori-horipad-switch                        | HORIPAD for Nintendo Switch                                 | HORI                           | gamepad
hori-horipad-steam                         | HORIPAD Steam Controller                                    | HORI                           | gamepad
hp-usb-keyboard                            | HP USB Keyboard                                             | HP                             | keyboard
hyperx-alloy-elite-rgb                     | HyperX Alloy Elite RGB                                      | HyperX                         | keyboard
hyperx-pulsefire-dart                      | HyperX Pulsefire Dart (cable)                               | HyperX                         | mouse
hyperx-pulsefire-dart-receiver             | HyperX Pulsefire Dart (receiver)                            | HyperX                         | mouse
ibuffalo-snes                              | iBuffalo Classic USB SNES Gamepad                           | iBuffalo                       | gamepad
joypad-generic-hid                         | Joypad-OS Generic HID Gamepad                               | Joypad                         | gamepad
joypad-steam-input                         | Joypad-OS Steam Input Gamepad                               | Joypad                         | gamepad
joypad-xac                                 | Joypad-OS XAC-compatible Gamepad                            | Joypad                         | gamepad
kensington-slimblade                       | Kensington Slimblade Trackball                              | Kensington                     | mouse
keychron-q6                                | Keychron Q6                                                 | Keychron                       | keyboard
lenovo-thinkpad-compact-bluetooth-keyboard | Lenovo ThinkPad Compact Bluetooth Keyboard with TrackPoint  | Lenovo                         | keyboard
lenovo-ultraslim-wireless-combo            | Lenovo Ultraslim Wireless Combo (keyboard)                  | Lenovo                         | keyboard
leo-bodnar-pedals                          | Leo Bodnar SLI-M Pedals                                     | Leo Bodnar                     | pedals
logitech-bolt-receiver-keyboard            | Logitech Bolt Receiver (keyboard)                           | Logitech                       | keyboard
logitech-bolt-receiver-mouse               | Logitech Bolt Receiver (mouse)                              | Logitech                       | mouse
logitech-driving-force                     | Logitech Driving Force                                      | Logitech                       | wheel
logitech-driving-force-gt                  | Logitech Driving Force GT                                   | Logitech                       | wheel
logitech-driving-force-pro                 | Logitech Driving Force Pro                                  | Logitech                       | wheel
logitech-extreme-3d-pro                    | Logitech Extreme 3D Pro                                     | Logitech                       | joystick
logitech-formula-vibration                 | Logitech Formula Vibration Feedback Wheel                   | Logitech                       | wheel
logitech-g-pro-ps                          | Logitech G PRO Racing Wheel (PlayStation)                   | Logitech                       | wheel
logitech-g-pro-xbox                        | Logitech G PRO Racing Wheel (Xbox)                          | Logitech                       | wheel
logitech-g25                               | Logitech G25 Racing Wheel                                   | Logitech                       | wheel
logitech-g27                               | Logitech G27 Racing Wheel                                   | Logitech                       | wheel
logitech-g29                               | Logitech G29 Driving Force Racing Wheel                     | Logitech                       | wheel
logitech-g29-ps4                           | Logitech G29 Driving Force Racing Wheel (PS4 mode)          | Logitech                       | wheel
logitech-g403-hero                         | Logitech G403 HERO                                          | Logitech                       | mouse
logitech-g5                                | Logitech G5                                                 | Logitech                       | mouse
logitech-g500s                             | Logitech G500s                                              | Logitech                       | mouse
logitech-g502-hero                         | Logitech G502 HERO                                          | Logitech                       | mouse
logitech-g502-x                            | Logitech G502 X                                             | Logitech                       | mouse
logitech-g710                              | Logitech G710                                               | Logitech                       | keyboard
logitech-g810                              | Logitech G810                                               | Logitech                       | keyboard
logitech-g815                              | Logitech G815                                               | Logitech                       | keyboard
logitech-g903-lightspeed                   | Logitech G903 LIGHTSPEED                                    | Logitech                       | mouse
logitech-g920                              | Logitech G920 Driving Force Racing Wheel                    | Logitech                       | wheel
logitech-g923-ps                           | Logitech G923 Racing Wheel (PlayStation)                    | Logitech                       | wheel
logitech-g923-xbox                         | Logitech G923 Racing Wheel (Xbox)                           | Logitech                       | wheel
logitech-f310                              | Logitech Gamepad F310                                       | Logitech                       | gamepad
logitech-gaming-mouse-g502                 | Logitech Gaming Mouse G502                                  | Logitech                       | mouse
logitech-gt-force                          | Logitech GT Force (WingMan FFG)                             | Logitech                       | wheel
logitech-m557                              | Logitech M557 (Bluetooth)                                   | Logitech                       | mouse
logitech-momo-racing                       | Logitech MOMO Racing (Black)                                | Logitech                       | wheel
logitech-momo-force                        | Logitech MOMO Racing Force (Red)                            | Logitech                       | wheel
logitech-mx-anywhere-3s                    | Logitech MX Anywhere 3S (Bluetooth)                         | Logitech                       | mouse
logitech-mx-master-3s                      | Logitech MX Master 3S (Bluetooth)                           | Logitech                       | mouse
logitech-mx510                             | Logitech MX510                                              | Logitech                       | mouse
logitech-mx518                             | Logitech MX518                                              | Logitech                       | mouse
logitech-rs-pedals                         | Logitech RS Pedals (Standalone)                             | Logitech                       | pedals
logitech-speed-force-wireless              | Logitech Speed Force Wireless (Wii)                         | Logitech                       | wheel
logitech-unifying-receiver-keyboard        | Logitech Unifying Receiver (keyboard)                       | Logitech                       | keyboard
logitech-unifying-receiver-mouse           | Logitech Unifying Receiver (mouse)                          | Logitech                       | mouse
logitech-usb-optical-mouse                 | Logitech USB Optical Mouse                                  | Logitech                       | mouse
logitech-usb-receiver-c52e-keyboard        | Logitech USB Receiver C52E (keyboard)                       | Logitech                       | keyboard
logitech-usb-trackball                     | Logitech USB Trackball                                      | Logitech                       | mouse
logitech-wingman-formula-gp                | Logitech WingMan Formula GP                                 | Logitech                       | wheel
logitech-f710                              | Logitech Wireless Gamepad F710                              | Logitech                       | gamepad
saitek-x52                                 | Saitek X52 Flight Control System                            | Logitech (Saitek)              | hotas
saitek-x52-pro                             | Saitek X52 Pro Flight Control System                        | Logitech (Saitek)              | hotas
microsoft-transceiver-v9-mouse             | Microsoft 2.4GHz Transceiver v9.0 (mouse)                   | Microsoft                      | mouse
microsoft-classic-intellimouse             | Microsoft Classic IntelliMouse                              | Microsoft                      | mouse
microsoft-designer-keyboard                | Microsoft Designer Keyboard (Bluetooth)                     | Microsoft                      | keyboard
microsoft-natural-ergonomic-4000           | Microsoft Natural Ergonomic Keyboard 4000                   | Microsoft                      | keyboard
microsoft-notebook-optical-mouse           | Microsoft Notebook Optical Mouse                            | Microsoft                      | mouse
microsoft-optical-mouse-tilt-wheel         | Microsoft Optical Mouse with Tilt Wheel                     | Microsoft                      | mouse
microsoft-sculpt-touch-mouse               | Microsoft Sculpt Touch Mouse (Bluetooth)                    | Microsoft                      | mouse
microsoft-wired-keyboard-600               | Microsoft Wired Keyboard 600                                | Microsoft                      | keyboard
sidewinder-force-feedback-2                | SideWinder Force Feedback 2 Joystick                        | Microsoft                      | joystick
xbox-360-arcade-stick                      | Xbox 360 Arcade Stick                                       | Microsoft                      | arcadestick
xbox-360-wired                             | Xbox 360 Controller (Wired)                                 | Microsoft                      | gamepad
xbox-360-type2                             | Xbox 360 Controller Type 2                                  | Microsoft                      | gamepad
xbox-360-dance-pad                         | Xbox 360 Dance Pad                                          | Microsoft                      | other
xbox-360-flight-stick                      | Xbox 360 Flight Stick                                       | Microsoft                      | flightstick
xbox-360-guitar-v1                         | Xbox 360 Guitar Controller v1                               | Microsoft                      | other
xbox-360-guitar-v2                         | Xbox 360 Guitar Controller v2                               | Microsoft                      | other
xbox-360-wheel-v1                          | Xbox 360 Racing Wheel v1                                    | Microsoft                      | wheel
xbox-360-wheel-v2                          | Xbox 360 Racing Wheel v2                                    | Microsoft                      | wheel
xbox-360-wireless                          | Xbox 360 Wireless Controller                                | Microsoft                      | gamepad
xbox-adaptive                              | Xbox Adaptive Controller                                    | Microsoft                      | gamepad
xbox-elite-v2-bt                           | Xbox Elite Series 2 Controller (Bluetooth)                  | Microsoft                      | gamepad
xbox-elite-v2-bt-v2                        | Xbox Elite Series 2 Controller (Bluetooth, PID 0x0B22)      | Microsoft                      | gamepad
xbox-elite-v1                              | Xbox Elite Wireless Controller Series 1                     | Microsoft                      | gamepad
xbox-elite-v2                              | Xbox Elite Wireless Controller Series 2                     | Microsoft                      | gamepad
xbox-one-original                          | Xbox One Controller (Original, Model 1537)                  | Microsoft                      | gamepad
xbox-one-rev1                              | Xbox One Controller (Rev 1, Model 1697)                     | Microsoft                      | gamepad
xbox-one-s-bt                              | Xbox One S Controller (Bluetooth)                           | Microsoft                      | gamepad
xbox-one-s-bt-full                         | Xbox One S Controller (Bluetooth): Full                     | Microsoft                      | gamepad
xbox-one-s                                 | Xbox One S Controller (Model 1708)                          | Microsoft                      | gamepad
xbox-series-xs-bt                          | Xbox Series X|S Controller (Bluetooth)                      | Microsoft                      | gamepad
xbox-series-xs                             | Xbox Series X|S Controller (Model 1914)                     | Microsoft                      | gamepad
mmos-ffb                                   | MMOS Force Feedback Wheel                                   | MMOS                           | wheel
moza-r12                                   | MOZA R12 Racing Wheelbase                                   | MOZA                           | wheel
moza-r16                                   | MOZA R16/R21 Racing Wheelbase                               | MOZA                           | wheel
moza-r3                                    | MOZA R3 Racing Wheelbase                                    | MOZA                           | wheel
moza-r5                                    | MOZA R5 Racing Wheelbase                                    | MOZA                           | wheel
moza-r9                                    | MOZA R9 Racing Wheelbase                                    | MOZA                           | wheel
nacon-bigben-ps4                           | BigBen Game Pad for PS3                                     | Nacon                          | gamepad
gamecube-adapter-hid                       | GameCube Controller Adapter (HID)                           | Nintendo                       | gamepad
gamecube-adapter                           | GameCube Controller Adapter (Wii U / Switch): Full          | Nintendo                       | gamepad
joypad-gc-adapter                          | Joypad-OS GameCube Adapter (HID)                            | Nintendo                       | gamepad
n64-nso                                    | N64 Controller (Nintendo Switch Online)                     | Nintendo                       | gamepad
switch2-joycon-l                           | Nintendo Switch 2 Joy-Con (L)                               | Nintendo                       | gamepad
switch2-joycon-r                           | Nintendo Switch 2 Joy-Con (R)                               | Nintendo                       | gamepad
switch2-pro-controller                     | Nintendo Switch 2 Pro Controller                            | Nintendo                       | gamepad
switch2-pro-controller-composite           | Nintendo Switch 2 Pro Controller: Full                      | Nintendo                       | gamepad
joycon-l                                   | Nintendo Switch Joy-Con (L)                                 | Nintendo                       | gamepad
joycon-r                                   | Nintendo Switch Joy-Con (R)                                 | Nintendo                       | gamepad
joycon-charging-grip                       | Nintendo Switch Joy-Con Charging Grip                       | Nintendo                       | gamepad
switch-pro                                 | Nintendo Switch Pro Controller                              | Nintendo                       | gamepad
switch-pro-usb                             | Nintendo Switch Pro Controller (USB)                        | Nintendo                       | gamepad
genesis-nso                                | Sega Genesis Controller (Nintendo Switch Online)            | Nintendo                       | gamepad
snes-nso                                   | SNES Controller (Nintendo Switch Online)                    | Nintendo                       | gamepad
obins-anne-pro-2                           | Obins Anne Pro 2                                            | Obins                          | keyboard
oddor-handbrake                            | Oddor USB Handbrake                                         | Oddor                          | other
openffboard                                | OpenFFBoard (Open-Source FFB Wheel)                         | OpenFFBoard                    | wheel
hhkb-classic                               | HHKB Classic                                                | PFU                            | keyboard
hhkb-professional                          | HHKB Professional (Topre)                                   | PFU                            | keyboard
hhkb-professional-jp                       | HHKB Professional JP                                        | PFU                            | keyboard
hhkb-studio                                | HHKB Studio (Bluetooth)                                     | PFU                            | keyboard
phoenixrc-pxrc                             | PhoenixRC 8-Axis Flight Controller                          | PhoenixRC                      | flightstick
pulsar-xlite-wireless                      | Pulsar Xlite Wireless                                       | Pulsar                         | mouse
pxn-v10                                    | PXN V10 Racing Wheel                                        | PXN                            | wheel
pxn-v12-lite                               | PXN V12 Lite Racing Wheel                                   | PXN                            | wheel
pxn-v12                                    | PXN V12 Racing Wheel                                        | PXN                            | wheel
pxn-vd6                                    | PXN VD6 WAS Bundle Racing Wheel                             | PXN                            | wheel
litestar-gt987                             | Lite Star GT987 Racing Wheel                                | PXN/Lite Star                  | wheel
rapoo-m50-plus-silent                      | Rapoo M50 Plus Silent                                       | Rapoo                          | mouse
raspberry-pi-400-keyboard                  | Raspberry Pi 400 Keyboard                                   | Raspberry Pi                   | keyboard
razer-basilisk-v2                          | Razer Basilisk V2                                           | Razer                          | mouse
razer-basilisk-v3-pro                      | Razer Basilisk V3 Pro                                       | Razer                          | mouse
razer-basilisk-v3-x-hyperspeed             | Razer Basilisk V3 X HyperSpeed                              | Razer                          | mouse
razer-blackwidow-v3-mini                   | Razer BlackWidow V3 Mini                                    | Razer                          | keyboard
razer-blackwidow-v4-pro                    | Razer BlackWidow V4 Pro                                     | Razer                          | keyboard
razer-blackwidow-v4-x                      | Razer BlackWidow V4 X                                       | Razer                          | keyboard
razer-cobra                                | Razer Cobra                                                 | Razer                          | mouse
razer-cynosa-chroma-pro                    | Razer Cynosa Chroma Pro                                     | Razer                          | keyboard
razer-deathadder-v2                        | Razer DeathAdder V2                                         | Razer                          | mouse
razer-deathadder-v3                        | Razer DeathAdder V3                                         | Razer                          | mouse
razer-deathadder-v3-pro                    | Razer DeathAdder V3 Pro                                     | Razer                          | mouse
razer-deathstalker-v2-pro                  | Razer DeathStalker V2 Pro                                   | Razer                          | keyboard
razer-huntsman-v3-pro                      | Razer Huntsman V3 Pro                                       | Razer                          | keyboard
razer-naga-trinity                         | Razer Naga Trinity                                          | Razer                          | mouse
razer-ornata-v3                            | Razer Ornata V3                                             | Razer                          | keyboard
razer-orochi-v2                            | Razer Orochi V2                                             | Razer                          | mouse
razer-panthera-ps4                         | Razer Panthera (PS4 Mode)                                   | Razer                          | arcadestick
razer-pro-type-ultra                       | Razer Pro Type Ultra                                        | Razer                          | keyboard
razer-viper-mini                           | Razer Viper Mini                                            | Razer                          | mouse
razer-viper-ultimate                       | Razer Viper Ultimate                                        | Razer                          | mouse
razer-viper-v3-pro                         | Razer Viper V3 Pro                                          | Razer                          | mouse
razer-wolverine-v3-pro                     | Razer Wolverine V3 Pro (Wired)                              | Razer                          | gamepad
redragon-m690-pro                          | Redragon M690 PRO                                           | Redragon                       | mouse
royuan-gamakay-lk67                        | GamaKay LK67                                                | Royuan                         | keyboard
sega-astro-city-mini                       | Sega Astro City Mini Controller                             | Sega                           | gamepad
sega-mega-drive-mini                       | Sega Mega Drive Mini Gamepad                                | Sega                           | gamepad
shanwan-gioteck-ps3                        | ShanWan/Gioteck PS3 Wireless Controller                     | ShanWan                        | gamepad
simagic-alpha                              | Simagic Alpha Wheelbase                                     | Simagic                        | wheel
simagic-gt-neo                             | Simagic GT Neo / EVO                                        | Simagic                        | wheel
snk-neogeo-mini                            | SNK Neo Geo Mini Controller                                 | SNK                            | gamepad
dualsense                                  | DualSense (PS5)                                             | Sony                           | gamepad
dualsense-composite                        | DualSense (PS5): Full                                       | Sony                           | gamepad
dualsense-bt                               | DualSense (PS5, Bluetooth, Launch Firmware)                 | Sony                           | gamepad
dualsense-edge                             | DualSense Edge (PS5)                                        | Sony                           | gamepad
dualsense-edge-composite                   | DualSense Edge (PS5): Full                                  | Sony                           | gamepad
dualsense-edge-bt                          | DualSense Edge (PS5, Bluetooth)                             | Sony                           | gamepad
dualshock-3                                | DualShock 3 (SIXAXIS)                                       | Sony                           | gamepad
dualshock-3-full                           | DualShock 3 (SIXAXIS): Full                                 | Sony                           | gamepad
dualshock-4-v1-full                        | DualShock 4 v1 (Console Pairing)                            | Sony                           | gamepad
dualshock-4-v1                             | DualShock 4 v1 (CUH-ZCT1)                                   | Sony                           | gamepad
dualshock-4-v2-bt                          | DualShock 4 v2 (Bluetooth)                                  | Sony                           | gamepad
dualshock-4-v2                             | DualShock 4 v2 (CUH-ZCT2)                                   | Sony                           | gamepad
dualshock-4-v2-composite                   | DualShock 4 v2 (CUH-ZCT2): Full                             | Sony                           | gamepad
ps3-remote                                 | PlayStation 3 Blu-ray Remote                                | Sony                           | other
ps-classic                                 | PlayStation Classic Controller                              | Sony                           | gamepad
ps-move                                    | PlayStation Move Motion Controller                          | Sony                           | other
dualsense-bt-full                          | DualSense (PS5, Bluetooth, Current Firmware)                | Sony Interactive Entertainment | gamepad
steelseries-kana                           | SteelSeries Kana                                            | SteelSeries                    | mouse
steelseries-rival                          | SteelSeries Rival                                           | SteelSeries                    | mouse
steelseries-rival-600                      | SteelSeries Rival 600                                       | SteelSeries                    | mouse
steelseries-srws1                          | SteelSeries SRW-S1 Steering Wheel                           | SteelSeries                    | wheel
taito-egret-ii-mini                        | Taito Egret II Mini Controller                              | Taito                          | gamepad
thrustmaster-t-flight-hotas-x              | Thrustmaster T-Flight HOTAS X                               | Thrustmaster                   | hotas
thrustmaster-t-gt                          | Thrustmaster T-GT Racing Wheel                              | Thrustmaster                   | wheel
thrustmaster-t-lcm-pedals                  | Thrustmaster T-LCM Pedals                                   | Thrustmaster                   | pedals
thrustmaster-t-rudder-pedals               | Thrustmaster T-Rudder Pedals                                | Thrustmaster                   | pedals
thrustmaster-t16000m                       | Thrustmaster T.16000M Joystick                              | Thrustmaster                   | joystick
thrustmaster-t-flight-hotas-4              | Thrustmaster T.Flight HOTAS 4                               | Thrustmaster                   | hotas
thrustmaster-t-flight-hotas-one            | Thrustmaster T.Flight HOTAS One                             | Thrustmaster                   | hotas
thrustmaster-t-flight-rudder-pedals        | Thrustmaster T.Flight Rudder Pedals                         | Thrustmaster                   | pedals
thrustmaster-t150                          | Thrustmaster T150 Racing Wheel                              | Thrustmaster                   | wheel
thrustmaster-t248                          | Thrustmaster T248 Racing Wheel                              | Thrustmaster                   | wheel
thrustmaster-t300rs-ps3-adv                | Thrustmaster T300RS (PS3 Advanced/F1 Mode)                  | Thrustmaster                   | wheel
thrustmaster-t300rs-ps3                    | Thrustmaster T300RS (PS3 Normal Mode)                       | Thrustmaster                   | wheel
thrustmaster-t300rs                        | Thrustmaster T300RS Racing Wheel                            | Thrustmaster                   | wheel
thrustmaster-t500rs                        | Thrustmaster T500 RS Racing Wheel                           | Thrustmaster                   | wheel
thrustmaster-t80                           | Thrustmaster T80 Racing Wheel                               | Thrustmaster                   | wheel
thrustmaster-th8a-shifter                  | Thrustmaster TH8A Gear Shifter                              | Thrustmaster                   | other
thrustmaster-tpr-pedals                    | Thrustmaster TPR Rudder Pedals                              | Thrustmaster                   | pedals
thrustmaster-ts-pc-racer                   | Thrustmaster TS-PC Racer                                    | Thrustmaster                   | wheel
thrustmaster-ts-xw                         | Thrustmaster TS-XW Racer                                    | Thrustmaster                   | wheel
thrustmaster-tx-xbox                       | Thrustmaster TX Racing Wheel (Xbox)                         | Thrustmaster                   | wheel
realforce-108us                            | Topre Realforce 108 US                                      | Topre                          | keyboard
realforce-rgb                              | Topre Realforce RGB                                         | Topre                          | keyboard
truly-ergonomic-cleave                     | Truly Ergonomic CLEAVE                                      | Truly Ergonomic                | keyboard
velocityone-flightstick                    | Turtle Beach VelocityOne Flightstick                        | Turtle Beach                   | flightstick
velocityone-race                           | Turtle Beach VelocityOne Race (Steering Wheel)              | Turtle Beach                   | wheel
velocityone-throttle                       | Turtle Beach VelocityOne Throttle                           | Turtle Beach                   | other
steam-controller-2                         | Steam Controller (2026)                                     | Valve                          | gamepad
steam-controller-composite                 | Steam Controller (Composite)                                | Valve                          | gamepad
steam-controller                           | Steam Controller (Wired)                                    | Valve                          | gamepad
steam-deck                                 | Steam Deck Controller                                       | Valve                          | gamepad
steam-deck-composite                       | Steam Deck Controller (Composite)                           | Valve                          | gamepad
varmilo-ma109c                             | Varmilo MA109C                                              | Varmilo                        | keyboard
virpil-constellation-alpha-cm2             | Virpil VPC Constellation Alpha (CM2 base)                   | Virpil                         | joystick
virpil-constellation-alpha-cm3             | Virpil VPC Constellation Alpha (CM3 base)                   | Virpil                         | joystick
virpil-constellation-alpha-warbrd          | Virpil VPC Constellation Alpha (WarBRD-D base)              | Virpil                         | joystick
virpil-control-panel-1                     | Virpil VPC Control Panel #1                                 | Virpil                         | other
virpil-control-panel-2                     | Virpil VPC Control Panel #2                                 | Virpil                         | other
virpil-mongoost-50cm2-throttle             | Virpil VPC MongoosT-50CM2 Throttle                          | Virpil                         | other
virpil-mongoost-50cm3-throttle             | Virpil VPC MongoosT-50CM3 Throttle                          | Virpil                         | other
vkbsim-gladiator-k-l                       | VKBsim Gladiator K (L)                                      | VKBSim                         | joystick
vkbsim-gladiator-k-r                       | VKBsim Gladiator K (R)                                      | VKBSim                         | joystick
vkbsim-gladiator-mcp                       | VKBsim Gladiator Modern Combat Pro                          | VKBSim                         | joystick
vkbsim-gladiator-evo-l                     | VKBsim Gladiator NXT/EVO (L)                                | VKBSim                         | joystick
vkbsim-gladiator-evo-r                     | VKBsim Gladiator NXT/EVO (R)                                | VKBSim                         | joystick
vkbsim-gunfighter                          | VKBsim Gunfighter (R)                                       | VKBSim                         | joystick
vkbsim-gunfighter-sce-l                    | VKBsim Gunfighter Mk.III SCE (L)                            | VKBSim                         | joystick
vkbsim-gunfighter-sce-r                    | VKBsim Gunfighter Mk.III SCE (R)                            | VKBSim                         | joystick
vkbsim-sem-thq                             | VKBsim NXT SEM THQ Module                                   | VKBSim                         | other
vkbsim-stecs                               | VKBsim STECS Throttle                                       | VKBSim                         | other
vrc2                                       | VRC-2 Car/Flight Controller                                 | VRC                            | other
vrs-dfp-pedals                             | VRS DirectForce Pro Pedals                                  | VRS                            | pedals
vrs-dfp-wheel                              | VRS DirectForce Pro Wheelbase                               | VRS                            | wheel
winwing-orion2-joystick                    | Winwing Orion 2 Joystick Base                               | Winwing                        | joystick
winwing-orion2-f16ex                       | Winwing Orion Throttle Base II + F16EX Handle               | Winwing                        | other
winwing-orion2-f18                         | Winwing Orion Throttle Base II + F18 Handle                 | Winwing                        | other
winwing-skywalker-pedals                   | Winwing Skywalker Metal Rudder Pedals                       | Winwing                        | pedals
winwing-ursa-minor                         | Winwing Ursa Minor Fighter Stick (R)                        | Winwing                        | joystick
xiaomi-mi-wireless-mouse                   | Xiaomi Mi Wireless Mouse                                    | Xiaomi                         | mouse
zowie-gaming-mouse                         | ZOWIE Gaming Mouse                                          | ZOWIE                          | mouse









"""

from dataclasses import dataclass
import json
import logging
import math
import queue
import re
import secrets
import socket
import struct
import threading
import time
from types import SimpleNamespace
import uuid
from shiboken6 import Shiboken
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Slot
from psygnal import Signal

import dinput
from dinput import GEX_ID_STRING, GEX_MAX_DEVICES, GEX_PID_BASE, GEX_PRODUCT_STRING, DeviceSummary
import gremlin.config
from gremlin.singleton_decorator import SingletonDecorator
from gremlin.util import getHostIpSingle, InvokeUiMethod


from gremlin.ui.ui_common import (
    BaseDialogUi,
    Buttons,
    clear_layout,
    Color,
    ConfirmBox,
    get_mode_list,
    get_text_width,
    getFlowContainer,
    getGridContainer,
    getHContainer,
    getVContainer,
    Icons,
    InputListenerWidget,
    MessageBox,
    MessageBoxWarning,
    MessageBoxYesNo,
    QBoxFrameLayout,
    QCustomThemeDialog,
    QDataCheckbox,
    QDataComboBox,
    QDataIPLineEdit,
    QDataLabel,
    QDataLineEdit,
    QDataPushButton,
    QDataRadioButton,
    QDataRadioButtonGroup,
    QDelayWidget,
    QEnabledWidget,
    QFloatLineEdit,
    QGroupBoxV,
    QHorizontalLine,
    QIconLabel,
    QInfoBox,
    QIntLineEdit,
    QLineEdit,
    QPathLineItem,
    QRememberDialog,
    QScrollableWidget,
    QWarningWidget,
    synchronize_grids,
)

syslog = logging.getLogger("system")
AXIS_NAMES = ("X", "Y", "Z", "Rx", "Ry", "Rz", "Slider", "Dial")
HAT_POSITIONS = {
    (0, 0): 0,
    (0, 1): 1,
    (1, 1): 2,
    (1, 0): 3,
    (1, -1): 4,
    (0, -1): 5,
    (-1, -1): 6,
    (-1, 0): 7,
    (-1, 1): 8,
}
_LIST_REPLIES = {
    "/maestro_profiles": "/maestro_profile",
    "/maestro_definitions": "/maestro_definition",
    "/maestro_devices": "/maestro_device",
    "/maestro_system_devices": "/maestro_system_device",
}
_SINGLE_REPLIES = {
    "/maestro_ping": "/maestro_pong",
    "/maestro_create": "/maestro_created",
    "/maestro_create_custom": "/maestro_created",
    "/maestro_create_gamepad": "/maestro_created",
    "/maestro_activate": "/maestro_created",
    "/maestro_rename": "/maestro_renamed",
    "/maestro_remove": "/maestro_ok",
    "/maestro_delete": "/maestro_ok",
    "/maestro_delete_all": "/maestro_ok",
    "/maestro_capabilities": "/maestro_capabilities_result",
    "/maestro_state": "/maestro_state_result",
    "/maestro_reset": "/maestro_ok",
}

GEX_VENDOR_ID = 0x0001  # fake vendor ID
GEX_PRODUCT_ID = 0x0001  # fake product ID


def _osc_string(value):
    if "\0" in value:
        raise ValueError("OSC strings cannot contain NUL")
    data = value.encode("utf-8") + b"\0"
    return data + b"\0" * (-len(data) % 4)


def _encode_message(address, arguments):
    """Encode the scalar types used by Maestro protocol version 1."""
    tags, payload = ",", bytearray()
    for value in arguments:
        if isinstance(value, bool):
            tags += "T" if value else "F"
        elif isinstance(value, int):
            tags += "i"
            payload.extend(struct.pack(">i", value))
        elif isinstance(value, float):
            tags += "f"
            payload.extend(struct.pack(">f", value))
        elif isinstance(value, str):
            tags += "s"
            payload.extend(_osc_string(value))
        else:
            raise TypeError(f"Unsupported OSC argument: {type(value).__name__}")
    return _osc_string(address) + _osc_string(tags) + payload


def _decode_message(data):
    """Decode a service reply. The service sends individual OSC messages."""
    offset = 0

    def read_string():
        nonlocal offset
        end = data.index(b"\0", offset)
        value = data[offset:end].decode("utf-8")
        padded_end = (end + 4) & ~3
        if padded_end > len(data) or any(data[end:padded_end]):
            raise ValueError("Invalid OSC string padding")
        offset = padded_end
        return value

    address, tags = read_string(), read_string()
    if not address.startswith("/maestro_") or not tags.startswith(","):
        raise ValueError("Invalid Maestro OSC reply")
    values = []
    for tag in tags[1:]:
        if tag == "s":
            values.append(read_string())
        elif tag in "ifhd":
            fmt = ">" + {"h": "q"}.get(tag, tag)
            values.append(struct.unpack_from(fmt, data, offset)[0])
            offset += struct.calcsize(fmt)
        elif tag in "TF":
            values.append(tag == "T")
        else:
            raise ValueError(f"Unsupported OSC reply type: {tag}")
    if offset != len(data):
        raise ValueError("Trailing OSC reply data")
    return address, values


class MaestroServiceError(RuntimeError):
    """An error returned by MaestroOscService."""

    def __init__(self, address, code, description):
        super().__init__(f"{address}: {code}: {description}")
        self.address, self.code, self.description = address, code, description


class MaestroResult:
    """Outcome of a Maestro management request (success or error).

    ok          True for success, False for a service error
    address     command address the result belongs to (e.g. /maestro_delete)
    reply       raw reply address (e.g. /maestro_ok, /maestro_created, /maestro_error)
    args        extra reply arguments (for /maestro_ok: the echoed target arguments)
    data        JSON payload decoded to python objects when the reply carries one, else None
    code        error code from the service ("not_found", "bad_arguments", ...) or None
    message     error description or None
    error       the underlying exception (MaestroServiceError, TimeoutError, OSError) or None
    """

    __slots__ = ("ok", "address", "reply", "args", "data", "code", "message", "error")

    def __init__(self, ok, address, reply=None, args=(), data=None, code=None, message=None, error=None):
        self.ok, self.address, self.reply = ok, address, reply
        self.args, self.data = tuple(args), data
        self.code, self.message, self.error = code, message, error

    def __bool__(self):
        return self.ok

    def __repr__(self):
        if self.ok:
            return f"MaestroResult(ok, {self.address}, reply={self.reply}, args={self.args})"
        return f"MaestroResult(error, {self.address}, code={self.code}, message={self.message})"

    @classmethod
    def from_reply(cls, address, values):
        """Builds a success result from the reply values returned by MaestroOscClient.request()."""
        # values: [request id, ...]; /maestro_ok is [id, command address, target args...]
        rest = list(values[1:]) if isinstance(values, (list, tuple)) else []
        reply = _SINGLE_REPLIES.get(address)
        if reply == "/maestro_ok":
            return cls(True, address, reply, rest[1:])
        data = None
        if rest and isinstance(rest[-1], str):
            try:
                data = json.loads(rest[-1])
            except ValueError:
                data = None
        verbose = gremlin.config.Configuration().verbose_mode_maestro
        if verbose:
            syslog.info(f"Maestro reply for {address}: [{'ok' if reply == '/maestro_ok' else reply}] {rest}")
        return cls(True, address, reply, rest, data)

    @classmethod
    def from_error(cls, address, error):
        """Builds an error result from an exception raised by MaestroOscClient.request()."""
        if isinstance(error, MaestroServiceError):
            return cls(False, error.address or address, "/maestro_error", (), None,
                       error.code, error.description, error)
        code = "timeout" if isinstance(error, TimeoutError) else "transport_error"
        return cls(False, address, None, (), None, code, str(error), error)

    def raise_for_error(self):
        """Raises the underlying error if this result is a failure; returns self otherwise."""
        if not self.ok and self.error is not None:
            syslog.error(f"Maestro: reply: {self.reply} raised error for {self.address}: code={self.code}, message={self.message}")
            raise self.error  # @IgnoreException
        return self


class MaestroOscClient:
    """Dedicated OSC transport, independent of GEX's user OSC input/output.

    A receiver drains control echoes/errors without blocking output callbacks.
    Management calls correlate by ID and retry identical packets from the same
    source socket, using the service's replay cache. Lists collect indexed rows
    even when completion arrives before the data or a retry repeats rows.
    """

    def __init__(self, host="127.0.0.1", port=8010, reply_host="127.0.0.1", reply_port=8011, timeout=3.0, attempts=3):
        self.destination = (socket.gethostbyname(host), port)
        self.timeout, self.attempts = timeout, attempts
        self._closed = threading.Event()
        self._send_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending = {}
        self.service_callback = None  # called with True on /maestro_start and False on /maestro_stop
        self._port = port
        self._host = host
        self._request_id = secrets.randbelow(1 << 30)
        self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Two applications cannot correlate replies reliably on a shared
            # fixed destination port. Never enable SO_REUSEADDR here.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self._rx.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self._rx.bind((reply_host, reply_port))
            self._rx.settimeout(0.2)
        except OSError:
            self._tx.close()
            self._rx.close()
            raise
        self._receiver = threading.Thread(target=self._receive, name="Maestro OSC replies", daemon=True)
        self._receiver.start()

    @property
    def host(self):
        """connected UDP host IP (IPV4 string)"""
        return self._host

    @property
    def port(self):
        """connected UDP port #"""
        return self._port

    def _send(self, packet):
        with self._send_lock:
            if self._closed.is_set():
                raise OSError("Maestro OSC client is closed")
            self._tx.sendto(packet, self.destination)

    def write(self, address, value):
        """Send a value-first control message without a management request ID."""
        self._send(_encode_message(address, [value]))

    def request(self, address, *arguments, timeout=None, attempts=None) -> MaestroResult:
        """Send a management request and return the data in MaestroResult"""
        try:
            values = self._request(address, *arguments, timeout=timeout, attempts=attempts)  # @IgnoreException
        except (MaestroServiceError, TimeoutError, OSError) as error:
            return MaestroResult.from_error(address, error)
        if address in _LIST_REPLIES:
            rows, total = values
            return MaestroResult(True, address, _LIST_REPLIES[address], (total,), rows)
        return MaestroResult.from_reply(address, values)

    def _request(self, address, *arguments, timeout=None, attempts=None):
        if address not in _LIST_REPLIES and address not in _SINGLE_REPLIES:
            raise ValueError(f"Not a Maestro management address: {address}")
        replies = queue.Queue()
        with self._pending_lock:
            self._request_id = (self._request_id + 1) & 0x7FFFFFFF
            request_id = self._request_id
            self._pending[request_id] = replies
        try:
            packet = _encode_message(address, [request_id, *arguments])
            rows, done = {}, None
            for _ in range(self.attempts if attempts is None else attempts):
                self._send(packet)
                deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
                while time.monotonic() < deadline:
                    try:
                        item = replies.get(timeout=max(0.001, deadline - time.monotonic()))  # @IgnoreException
                    except queue.Empty:
                        break
                    if item is None:
                        raise OSError("Maestro OSC client is closed")
                    reply, values = item
                    if reply == "/maestro_error":
                        raise MaestroServiceError(values[1], values[2], values[3])  # @IgnoreException
                    if address not in _LIST_REPLIES:
                        if reply == _SINGLE_REPLIES[address]:
                            # /maestro_ok is [id, command address, optional target args...]
                            if reply == "/maestro_ok" and (len(values) < 2 or values[1] != address):
                                continue
                            return values
                        continue
                    if reply == "/maestro_done" and len(values) == 5 and values[1] == address:
                        done = values
                    elif reply == _LIST_REPLIES[address] and len(values) == 3:
                        rows[values[1]] = values[2]
                    if done is not None:
                        expected = range(done[3], done[3] + done[4])
                        if all(index in rows for index in expected):
                            return [json.loads(rows[index]) for index in expected], done[2]
            raise TimeoutError(f"No complete Maestro reply for {address} at {self.destination}")  # @IgnoreException
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def list(self, address):
        result, offset = [], 0
        while True:
            rows, total = self._request(address, offset, 100)  # @IgnoreException
            result.extend(rows)
            offset += len(rows)
            if offset >= total:
                return result
            if not rows:
                raise RuntimeError(f"Maestro list made no progress: {address}")

    def _receive(self):
        while not self._closed.is_set():
            try:
                data, source = self._rx.recvfrom(65535)  # @IgnoreException
            except socket.timeout:
                continue
            except OSError:
                if not self._closed.is_set():
                    syslog.exception("MAESTRO: reply listener failed")
                return
            if source[0] != self.destination[0]:
                continue
            try:
                reply, values = _decode_message(data)
                if reply in ("/maestro_start", "/maestro_stop"):
                    callback = self.service_callback
                    if callback is not None:
                        callback(reply == "/maestro_start")
                    continue
                if reply == "/maestro_error" and len(values) != 4:
                    raise ValueError("Invalid Maestro error reply")
                with self._pending_lock:
                    pending = self._pending.get(values[0]) if values and type(values[0]) is int else None
                    if pending is not None and not reply.startswith(
                        (
                            "/maestro_axis/",
                            "/maestro_button/",
                            "/maestro_hat/",
                            "/maestro_gamepad_axis/",
                        )
                    ):
                        pending.put((reply, values))
                    elif reply == "/maestro_error":
                        syslog.error("MAESTRO: %s: %s: %s", *values[1:])
            except (ValueError, IndexError, struct.error) as error:
                syslog.warning("MAESTRO: invalid OSC reply: %s", error)

    def close(self):
        with self._send_lock:
            self._closed.set()
            self._tx.close()
            self._rx.close()
        with self._pending_lock:
            for pending in self._pending.values():
                pending.put(None)
        if threading.current_thread() is not self._receiver:
            self._receiver.join(timeout=1)


@dataclass
class MaestroController:
    """Service-owned custom joystick; Index and Profile retain legacy access."""

    index: int
    id: str
    name: str
    axis_count: int
    button_count: int
    hat_count: int
    profile: SimpleNamespace
    host: str  # host IP connected to
    port: int  # port number connected to
    axis_names: tuple = AXIS_NAMES
    kind: str = "custom"

    @property
    def key(self) -> str:
        """unique key for the controller based on host, port, and ID"""
        return f"maestro://{self.host}:{self.port}/{self.id}"


_GEX_ID_PATTERN = re.compile(r"gex-(?:gp-)?(\d+)")


def is_valid_gex_id(device_id) -> bool:
    """GEX joystick/gamepad IDs are 1-based (gex-1.. / gex-gp-1..); other IDs are not GEX-managed and pass."""
    match = _GEX_ID_PATTERN.fullmatch(str(device_id))
    return match is None or 1 <= int(match.group(1)) <= GEX_MAX_DEVICES


def service_snapshot(client):
    """Read saved definitions, active devices and the host's profile catalog, discarding 0-based GEX ids."""
    definitions = [d for d in client.list("/maestro_definitions") if is_valid_gex_id(d["id"])]
    devices = [d for d in client.list("/maestro_devices") if is_valid_gex_id(d["id"])]
    return dict(definitions=definitions, devices=devices, profiles=client.list("/maestro_profiles"))



def save_device_definition(client, definition, previous=None):
    """Save the editor's definition using the service's version 1 commands.

    Layout edits require recreation. If any step fails, restore the previous
    saved definition, including whether it was active. Never erase input maps.
    """
    device_id = definition["id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device_id):
        raise ValueError("Device ID must contain 1–64 letters, digits, underscores or hyphens")
    if not is_valid_gex_id(device_id):
        raise ValueError(f"GEX device IDs are 1-based (gex-1..gex-{GEX_MAX_DEVICES}); {device_id} is invalid")
    if not definition["name"].strip() or len(definition["name"]) > 128:
        raise ValueError("Device name must contain 1–128 characters")
    if previous is not None and previous["id"] != device_id:
        raise ValueError("An existing device's ID cannot be changed")

    def create(row):
        if row["kind"] == "custom":
            result = client.request("/maestro_create_custom", row["id"], row["name"], row["buttons"], row["axes"], row["hats"])
            if not result:
                syslog.error(f"MAESTRO: failed to create custom device {row['id']}: {result.code}: {result.message}")
                return False
        else:
            result = client.request("/maestro_create", row["id"], row["profileId"], row["name"])
            if not result:
                syslog.error(f"MAESTRO: failed to create device {row['id']}: {result.code}: {result.message}")
                return False

        if not row["enabled"]:
            result = client.request("/maestro_remove", row["id"])
            if not result:
                syslog.error(f"MAESTRO: failed to remove device {row['id']}: {result.code}: {result.message}")
                return False
        return True

    layout_keys = ("kind", "profileId", "axes", "buttons", "hats")
    changed_layout = previous is not None and any(definition.get(k) != previous.get(k) for k in layout_keys)
    if previous is None:
        if not create(definition):
            return False
    elif changed_layout:
        result = client.request("/maestro_delete", device_id)
        if not result:
            syslog.error(f"MAESTRO: failed to delete device {device_id}: {result.code}: {result.message}")
            return False
        try:
            if not create(definition):
                return False
        except Exception as error:
            try:
                # A failed create may still have saved a definition (e.g. a
                # later deactivate failed). Clear that ID before restoring.
                if any(d["id"] == device_id for d in client.list("/maestro_definitions")):
                    client.request("/maestro_delete", device_id).raise_for_error()
                if not create(previous):
                    return False
            except Exception as restore_error:
                raise RuntimeError(f"{error}. Restoring the previous device also failed: {restore_error}") from error
            raise RuntimeError(f"{error}. The previous device definition was restored.") from error
    else:
        if definition["name"] != previous["name"]:
            result = client.request("/maestro_rename", device_id, definition["name"])
            if not result:
                syslog.error(f"MAESTRO: failed to rename device {device_id}: {result.code}: {result.message}")
                return False
        if definition["enabled"] != previous["enabled"]:
            result = client.request("/maestro_activate" if definition["enabled"] else "/maestro_remove", device_id)
            if not result:
                syslog.error(f"MAESTRO: failed to change activation state for device {device_id}: {result.code}: {result.message}")
                return False

    return True


@SingletonDecorator
class Maestro:
    connected_changed = Signal(bool)  # fires when the connection status changes (connection_state : bool)
    service_state_changed = Signal(bool)  # fires on /maestro_start (True) and /maestro_stop (False) from the bridge service

    def __init__(self):
        self._service_running = False  # last bridge state announced by the service
        self._output_used = False  # true if the running profile sent output to a Maestro device
        self._controller_map = {}  # holds index to MaestroController mapping [int] -> MaestroController
        self._name_map = {}  # holds lower case controller names to the controller value [str] -> MaestroController
        self._device_map = {}  # holds dinput DeviceSummary map for the Maestro devices [index] -> DeviceSummary
        self._buffer_map = {}
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._sync_worker = None
        self._stopping = threading.Event()
        self._dirty = False
        self.client = None
        self._initialized = False
        self._shutdown_connected = False
        self._local_service = True

        # the connection data is stored in our config
        config = gremlin.config.Configuration()

        if not config.maestro_enabled:
            syslog.info("MAESTRO: disabled")
            return

        # check defaults, use hosts where possible
        reply_host = config.maestro_osc_reply_host
        if reply_host == "127.0.0.1":
            # use self
            reply_host = getHostIpSingle()
            config.maestro_osc_reply_host = reply_host

        try:
            self.connect()
            self.LoadActiveControllers()
            if config.maestro_device_map is None:
                for index in range(min(GEX_MAX_DEVICES, max(0, config.maestro_device_count))):
                    if index not in self._controller_map:
                        self.createJoystickController(at_index=index)
            self.populateDeviceList()
            self.sync(force=True)
            syslog.info(f"MAESTRO: connected to Maestro Bridge service {len(self._controller_map)} managed controllers")
        except (OSError, RuntimeError, ValueError, IndexError) as error:
            syslog.error("MAESTRO: could not initialize Maestro Bridge service: %s", error)
            if self.client is not None:
                self.client.close()
                self.client = None
            self._initialized = False

    @staticmethod
    def _joystick_id(index):
        return f"gex-{index + 1}"

    @staticmethod
    def _gamepad_id(index):
        return f"gex-gp-{index + 1}"

    @classmethod
    def _service_index(cls, device_id):
        """0-based slot for a 1-based GEX joystick or gamepad id, else None."""
        match = _GEX_ID_PATTERN.fullmatch(str(device_id))
        if match is None or not is_valid_gex_id(device_id):
            return None
        return int(match.group(1)) - 1

    @property
    def initialized(self):
        return self._initialized

    @property
    def enabled(self):
        return self.initialized and gremlin.config.Configuration().maestro_enabled

    def ping(self):
        """Send a ping message to the Maestro service."""
        self.connect()
        if self.connected():
            self.client._send(_encode_message("/maestro_ping", []))
        return

    def getCapabilities(self, device_id: str) -> "MaestroProfileInfo | None":
        """Query /maestro_capabilities for one device and return it as a MaestroProfileInfo."""
        if not self.initialized or self.client is None:
            return None
        result = self.client.request("/maestro_capabilities", device_id)
        if not result or not isinstance(result.data, dict):
            syslog.error("MAESTRO: capabilities request failed for %s: %s: %s", device_id, result.code, result.message)
            return None
        try:
            return MaestroProfileInfo.from_dict(result.data, device_id)
        except (RuntimeError, ValueError, KeyError):
            syslog.exception("MAESTRO: invalid capabilities for %s", device_id)
            return None

    def getAllCapabilities(self) -> dict:
        """Return {device id: MaestroProfileInfo} for every known Maestro device (active devices and saved definitions)."""
        result = {}
        if not self.initialized or self.client is None:
            return result
        try:
            ids = {d["id"] for d in self.client.list("/maestro_devices")}
            ids.update(d["id"] for d in self.client.list("/maestro_definitions"))
        except (OSError, RuntimeError, ValueError, TimeoutError):
            syslog.exception("MAESTRO: unable to list devices for capabilities")
            return result
        for device_id in sorted(ids):
            if not is_valid_gex_id(device_id):
                continue
            caps = self.getCapabilities(device_id)
            if caps is not None:
                result[device_id] = caps
        return result

    def connected(self) -> bool:
        """Check the existing client with a service/protocol ping (up to one second)."""
        with self._lock:
            if not self._initialized or self.client is None:
                return False
            result = self.client.request("/maestro_ping", timeout=1.0, attempts=1)
            return bool(result) and list(result.args) == ["MaestroOscService", 1]

    def testConnection(self) -> bool:
        """Test the connection to the Maestro service."""
        if not self.connected():
            result = self.connect()
            if not result:
                return False
        return True

    def connect(self, host=None, port=None, reply_host=None, reply_port=None, throw_on_error=False):
        """Connect or retest the shared transport used by output and the dialog."""

        config = gremlin.config.Configuration()
        if host is None:
            host = config.maestro_osc_host
        if port is None:
            port = config.maestro_osc_port
        if reply_host is None:
            reply_host = config.maestro_osc_reply_host
        if reply_port is None:
            reply_port = config.maestro_osc_reply_port
        if host is None:
            syslog.error("MAESTRO: host is not specified")
            return None
        if port is None:
            syslog.error("MAESTRO: port is not specified")
            return None
        if reply_host is None:
            syslog.error("MAESTRO: reply host is not specified")
            return None
        if reply_port is None:
            syslog.error("MAESTRO: reply port is not specified")
            return None

        settings = (socket.gethostbyname(host), port, reply_host, reply_port)
        with self._lock:
            if self.client is not None and getattr(self, "_connection_settings", None) != settings:
                self._handle_shutdown()
                self._controller_map.clear()
                self._device_map.clear()
                self._buffer_map.clear()
                from gremlin import joystick_handling

                joystick_handling.set_maestro_devices([])
            if self.client is None:
                self.client = MaestroOscClient(*settings)
                self.client.service_callback = self._handle_service_state
            try:
                pong = self.client.request("/maestro_ping", timeout=1.0, attempts=2).raise_for_error()  # @IgnoreException
                if list(pong.args) != ["MaestroOscService", 1]:
                    raise RuntimeError(f"Unsupported Maestro service/protocol: {list(pong.args)}")
            except Exception:
                self.client.close()
                self.client = None
                self._initialized = False
                if throw_on_error:
                    raise
                return None
            self._connection_settings = settings
            self._local_service = settings[0].startswith("127.") or settings[0] == "0.0.0.0"
            if not self._local_service:
                try:
                    self._local_service = settings[0] in socket.gethostbyname_ex(socket.gethostname())[2]
                except OSError:
                    pass
            self._stopping.clear()
            self._initialized = True
            self._service_running = True
            self.connected_changed.emit(True)
            if not self._shutdown_connected:
                from gremlin import event_handler

                event_handler.EventListener().shutdown.connect(self._handle_shutdown)
                self._shutdown_connected = True
            return pong

    @property
    def service_running(self) -> bool:
        """true if the bridge service last announced /maestro_start (or answered a ping) and has not stopped since"""
        return self._service_running

    def markOutputUsed(self):
        """flags that the running profile is sending output to a Maestro device"""
        self._output_used = True

    def resetOutputUsage(self):
        """clears the output usage flag (called when a profile starts)"""
        self._output_used = False

    def _handle_service_state(self, running: bool):
        """handles /maestro_start and /maestro_stop messages from the bridge (receiver thread)"""
        self._service_running = running
        if running:
            syslog.info("MAESTRO: bridge service started")
        else:
            import gremlin.shared_state

            if gremlin.shared_state.is_running and self._output_used:
                syslog.warning("MAESTRO: bridge service stopped while the active profile is using Maestro devices - output is unavailable")
            else:
                syslog.info("MAESTRO: bridge service stopped")
        self.service_state_changed.emit(running)
        if running and self._initialized:
            # the service restarted: its controllers must be restored
            self.refreshDevices()

    def ensureConnected(self):
        if not self._initialized:
            result = self.connect(throw_on_error=False)
            return result is not None
        return True

    def disconnect(self):
        if self.client is not None:
            self._handle_shutdown()

    def _handle_shutdown(self):
        self._stopping.set()
        with self._lock:
            if self.client is None:
                return
            # The service outlives GEX. Finish in-flight writes before resetting
            # controls, and retain definitions for the next GEX session.
            try:
                for controller in list(self._controller_map.values()):
                    result = self.client.request("/maestro_reset", controller.id, timeout=0.3, attempts=1)
                    if not result:
                        syslog.warning("MAESTRO: reset on shutdown failed: %s", result.message)
            finally:
                self.client.close()
                self.client = None
                self._initialized = False
                self._service_running = False
                self.connected_changed.emit(False)

    def _cache_controller(self, info, definition, index=None) -> MaestroController:
        if index is None:
            index = self._service_index(info["id"])
        capabilities = self.client.request("/maestro_capabilities", info["id"]).raise_for_error().data
        state = self.client.request("/maestro_state", info["id"]).raise_for_error().data
        axes = tuple(capabilities["axes"])
        custom = definition["kind"] == "custom"
        buttons = definition["buttons"] if custom else capabilities.get("addressableButtons", 32)
        hats = definition["hats"] if custom else capabilities.get("hatCount", 1)
        controller = MaestroController(
            index=index,
            id=info["id"],
            name=info["name"],
            axis_count=len(axes),
            button_count=buttons,
            hat_count=hats,
            profile=SimpleNamespace(ProductId=capabilities["productId"], VendorId=capabilities["vendorId"]),
            axis_names=axes,
            kind=definition["kind"],
            host=self.client.host,
            port=self.client.port,
        )
        with self._lock:
            self._controller_map[index] = controller
            self._buffer_map[index] = self._neutral_buffer(controller)
            for axis, name in enumerate(axes, 1):
                self._set_axis(index, axis, state["axes"].get(name, 0.5) * 2 - 1)
            pressed = state.get("pressedButtons")
            if pressed is None:
                pressed = [b for b in range(1, buttons + 1) if state["buttons"] & (1 << (b - 1))]
            for button in pressed:
                self._set_button(index, button, True)
            positions = state.get("hats") or ([state["hat"]] if hats else [])
            for hat, position in enumerate(positions, 1):
                self._set_hat(index, hat, position)
            self._dirty = True
        return controller

    def LoadActiveControllers(self, device_map=None):
        """Attach selected active definitions without recreating hardware."""
        if not self.initialized:
            return
        if device_map is None:
            device_map = gremlin.config.Configuration().maestro_device_map
        definitions = {d["id"]: d for d in self.client.list("/maestro_definitions")}
        active = {}
        name_map = {}
        for info in self.client.list("/maestro_devices"):
            if not is_valid_gex_id(info["id"]):
                syslog.warning("MAESTRO: ignoring 0-based GEX device %s", info["id"])
                continue
            index = self._service_index(info["id"]) if device_map is None else device_map.get(info["id"])
            if index is not None and info["id"] in definitions:
                controller = self._cache_controller(info, definitions[info["id"]], index)
                active[controller.index] = controller
                name_map[controller.name.casefold()] = controller
        with self._lock:
            self._controller_map = active
            self._device_map = {i: d for i, d in self._device_map.items() if i in active}
            self._buffer_map = {i: b for i, b in self._buffer_map.items() if i in active}
            self._name_map = name_map
            self._dirty = True

    def hasControllerName(self, name: str) -> bool:
        """Check if a controller with the given name exists in the current controller map."""
        with self._lock:
            name = name.casefold()
            return any(c.name.casefold() == name for c in self._controller_map.values())

    def reset(self):
        """Reconnect saved active controllers and refresh DirectInput discovery."""
        if self.enabled:
            self.LoadActiveControllers()
            self.populateDeviceList()
            self.sync(force=True)

    def sync(self, force=False) -> bool:
        if not self.enabled or self._stopping.is_set() or not (self._dirty or force):
            return False
        with self._sync_lock:
            if self._sync_worker is not None:
                return False
            self.syncDinput()
            if not self._compare_list():
                self._dirty = False
                return False
            self._sync_worker = threading.Thread(target=self._sync_worker_runner, name="Maestro DirectInput sync", daemon=True)
            self._sync_worker.start()
            return True

    def _sync_worker_runner(self):
        try:
            deadline = time.monotonic() + 20
            while not self._stopping.is_set():
                self.syncDinput()
                if not self._compare_list():
                    self._dirty = False
                    import gremlin.joystick_handling

                    self.populateDeviceList()
                    gremlin.joystick_handling.joystick_devices_initialization()
                    return
                if time.monotonic() >= deadline:
                    syslog.warning("MAESTRO: DirectInput discovery timed out (service names may be cached by Windows)")
                    return
                self._stopping.wait(0.2)
        except Exception:
            syslog.exception("MAESTRO: DirectInput synchronization failed")
        finally:
            with self._sync_lock:
                self._sync_worker = None

    def _compare_list(self) -> bool:
        with self._lock:
            if not self._local_service:
                return False
            return self._controller_map.keys() != self._device_map.keys()

    def syncDinput(self):
        """Match by name and capabilities: service PIDs are not device indices."""
        if not self._local_service:
            with self._lock:
                self._device_map.clear()
            return
        devices = dinput.DILL.getDevices()
        with self._lock:
            mapped = {}
            for index, controller in self._controller_map.items():
                matches = [
                    d
                    for d in devices
                    if d.name == controller.name
                    and d.vendor_id == controller.profile.VendorId
                    and d.product_id == controller.profile.ProductId
                    and (d.axis_count, d.button_count, d.hat_count) == (controller.axis_count, controller.button_count, controller.hat_count)
                ]
                if len(matches) == 1:
                    mapped[index] = matches[0]
            self._device_map = mapped

    def syncBridge(self) -> list[DeviceSummary]:
        """Load the bridge's active devices (JSON) into the controller map and publish them to the device list."""
        if not self.enabled:
            return []
        self.LoadActiveControllers()
        self.populateDeviceList()
        with self._lock:
            return [self._device_map[c.key] for c in self._controller_map.values() if c.key in self._device_map]

    def controllerGuid(self, controller: MaestroController) -> dinput.GUID:
        """Generate a stable GUID for the given controller based on its ID and the host endpoint."""
        return dinput.GUID(uuid.uuid5(uuid.NAMESPACE_URL, controller.key))

    def populateDeviceList(self):
        """Publish selected service devices to Gremlin's virtual device registry.

        Use native DirectInput identities where they can be matched uniquely.
        Other hosts use stable endpoint/device identities and expose output
        capabilities; they do not generate local joystick input events.
        """
        from gremlin import joystick_handling
        from gremlin.types import DeviceType, DeviceCategory

        self.syncDinput()
        devices = []
        with self._lock:
            for index, controller in self._controller_map.items():
                device = self._device_map.get(index)
                if device is None:
                    # build a new device summary for this controller since no match was found
                    device = dinput.DeviceSummary()
                    host, port = self.client.destination
                    # use a GUID that is unique to this device
                    device.device_guid = self.controllerGuid(controller)
                    device.device_id = gremlin.util.normalize_guid(device.device_guid)
                    device.axis_count = controller.axis_count
                    device.button_count = controller.button_count
                    device.hat_count = controller.hat_count
                    device.vendor_id = controller.profile.VendorId
                    device.product_id = controller.profile.ProductId
                    for axis, name in enumerate(controller.axis_names[: controller.axis_count], 1):
                        device.linear_id_map[axis] = axis
                        device.axis_id_map[axis] = axis
                        device.axis_names[axis] = name
                    device.setConnected(True)
                    device.input_enabled = False
                axis_map = dict(device.axis_id_map)
                device.setAxisCallback(lambda axis, i=index, mapping=axis_map: self._read_axis_raw(i, mapping.get(axis, axis)))
                device.setButtonCallback(lambda button, i=index: self._read_button(i, button))
                device.setHatCallback(lambda hat, i=index: self._read_hat(i, hat))
                device.name = controller.name
                device.device_type = DeviceType.Maestro
                device.device_category = DeviceCategory.Virtual
                device.setVirtual(True)
                device.virtual_id = index
                device.data["maestro_key"] = controller.key
                devices.append(device)
                self._device_map[controller.key] = device
        joystick_handling.set_maestro_devices(devices)

    def getDeviceAt(self, index: int) -> DeviceSummary:
        """Return the device at the given index, if it exists."""
        with self._lock:
            controller = self._controller_map.get(index)
            if controller is None:
                return None
            if controller.key not in self._device_map:
                self.populateDeviceList()
            return self._device_map.get(controller.key)

    def getMaestroControllerAt(self, index: int) -> MaestroController:
        """Return the maestro controller at the given index, if it exists."""
        return self._controller_map.get(index)

    def hasDeviceAt(self, index: int) -> bool:
        """Check if a device exists at the given index."""
        with self._lock:
            return index in self._controller_map

    def hasDevice(self, name: str) -> bool:
        with self._lock:
            return any(device.name == name for device in self._device_map.values())

    def _read_axis_raw(self, index, axis):
        """Return the retained OSC output in DirectInput's signed axis units."""
        with self._lock:
            controller = self._controller_map.get(index)
            if controller is None or not 1 <= axis <= controller.axis_count:
                return 0
            offset = (controller.button_count + 7) // 8 + (axis - 1) * 2
            return struct.unpack_from("<h", self._buffer_map[index], offset)[0]

    def _read_button(self, index, button):
        with self._lock:
            controller = self._controller_map.get(index)
            if controller is None or not 1 <= button <= controller.button_count:
                return False
            return bool(self._buffer_map[index][(button - 1) // 8] & (1 << ((button - 1) % 8)))

    def _read_hat(self, index, hat):
        with self._lock:
            controller = self._controller_map.get(index)
            if controller is None or not 1 <= hat <= controller.hat_count:
                return -1
            offset = (controller.button_count + 7) // 8 + controller.axis_count * 2 + hat - 1
            value = self._buffer_map[index][offset]
            return -1 if value == 255 else value * 4500

    def getController(self, key: int):
        return self._controller_map.get(key)

    def getAllDevices(self) -> list[DeviceSummary]:
        """Return JSON records for all active devices owned by the service."""
        json_data = self.client.list("/maestro_devices") if self.enabled else []
        controllers = []
        device_list = []
        for controller in controllers:
            device = self._device_map.get(controller.key)
            if device is not None:
                device_list.append(device)
        return device_list

    def addMissingControllers(self):
        if self.enabled:
            if gremlin.config.Configuration().maestro_device_map is not None:
                self.LoadActiveControllers()
                self.populateDeviceList()
                return
            count = min(GEX_MAX_DEVICES, max(0, gremlin.config.Configuration().maestro_device_count))
            for index in range(count):
                if index not in self._controller_map:
                    self.createJoystickController(at_index=index)

    def removeController(self, controller):
        """Deactivate one GEX controller, retaining its saved definition."""
        if not self.enabled or self._controller_map.get(controller.index) is not controller:
            return
        self.client.request("/maestro_remove", controller.id).raise_for_error()
        with self._lock:
            self._controller_map.pop(controller.index, None)
            self._device_map.pop(controller.index, None)
            self._buffer_map.pop(controller.index, None)
            self._dirty = True
        self.refreshDevices(reload=False)

    def removeAllControllers(self):
        """Deactivate only attached GEX devices; never remove other clients' devices."""
        for controller in list(self._controller_map.values()):
            self.removeController(controller)

    def _register_controller(self, controller):
        """Persist the id->slot mapping so LoadActiveControllers keeps devices whose ids are not GEX-N."""
        config = gremlin.config.Configuration()
        if config.maestro_device_map is not None and config.maestro_device_map.get(controller.id) != controller.index:
            config.maestro_device_map = {**config.maestro_device_map, controller.id: controller.index}
            config.save()

    def createJoystickController(
        self, name: str = None, axis_count=8, button_count=128, hat_count=4, definition: str = None, at_index=None
    ) -> None | MaestroController:
        """Create a service-owned custom joystick controller.

        :param name: The name of the joystick controller.
        :param axis_count: The number of axes (0..8) - if definition is used this will be overwritten.
        :param button_count: The number of buttons (0..128) - if definition is used this will be overwritten.
        :param hat_count: The number of hats (0..4) - if definition is used this will be overwritten.
        :param definition: The definition string for the joystick controller (optional) - if set, defines the controller layout and overrides axis_count, button_count, and hat_count.
        :param at_index: The index at which to create the controller, use None or -1 to auto-assign.
        :return: The created MaestroController instance or None if creation failed.
        """
        if not self.ensureConnected():
            return None
        counts = ((axis_count, 8), (button_count, 128), (hat_count, 4))
        if any(type(n) is not int or not 0 <= n <= maximum for n, maximum in counts) or not any(n for n, _ in counts):
            raise ValueError("Maestro joystick requires 0..8 axes, 0..128 buttons, 0..4 hats and at least one control")
        index = at_index
        if index is None:
            index = next((i for i in range(GEX_MAX_DEVICES) if i not in self._controller_map), GEX_MAX_DEVICES)
        if type(index) is not int or not 0 <= index < GEX_MAX_DEVICES:
            syslog.warning(f"MAESTRO: controller index must be 0..{GEX_MAX_DEVICES - 1}")
            return None
        try:
            name = name or self._joystick_id(index)
            if not is_valid_gex_id(name):
                raise ValueError(f"GEX device id {name} must be 1-based")
            vendor_id = GEX_VENDOR_ID
            product_id = GEX_PRODUCT_ID
            # will throw an error if creation fails
            result = self.client.request(
                "/maestro_create_custom", name, name, button_count, axis_count, hat_count, vendor_id, product_id, True
            ).raise_for_error()  # @IgnoreException
            controller = self._cache_controller(result.data, dict(kind="custom", axes=axis_count, buttons=button_count, hats=hat_count), index)
            self._register_controller(controller)
            self.refreshDevices(reload=False)
            return controller
        except (OSError, RuntimeError, ValueError) as error:
            syslog.error(f"MAESTRO: failed to create controller {index}: {error}")
            return None

    def createGamepadController(self, name: str, definition: str, at_index=None) -> None | MaestroController:
        """Create a service-owned Xbox 360 gamepad controller.

        :param name: The name of the gamepad controller.
        :param definition: The definition string for the gamepad controller (see list above in comment header)
        :param at_index: The index at which to create the controller, use None or -1 to auto-assign.


        """
        if not self.ensureConnected():
            return None
        index = at_index
        if index is None:
            index = next((i for i in range(GEX_MAX_DEVICES) if i not in self._controller_map), GEX_MAX_DEVICES)
        if type(index) is not int or not 0 <= index < GEX_MAX_DEVICES:
            syslog.warning(f"MAESTRO: controller index must be 0..{GEX_MAX_DEVICES - 1}")
            return None
        try:
            name = name or self._gamepad_id(index)
            if not is_valid_gex_id(name):
                raise ValueError(f"GEX device id {name} must be 1-based")
            result = self.client.request("/maestro_create_gamepad", name, name, True).raise_for_error()
            controller = self._cache_controller(result.data, dict(kind="gamepad"), index)
            self._register_controller(controller)
            self.refreshDevices(reload=False)
            return controller
        except (OSError, RuntimeError, ValueError) as error:
            syslog.error(f"MAESTRO: failed to create gamepad controller {index}: {error}")
            return None

    def refreshDevices(self, reload=True):
        """Refresh the device list from maestro after a device was added or removed."""
        if not self.enabled:
            return
        try:
            if reload:
                self.LoadActiveControllers()
            self.populateDeviceList()
            self.sync(force=True)
        except Exception:
            syslog.exception("MAESTRO: device list refresh failed")

    def deleteDevice(self, name: str) -> MaestroResult:
        result = self.client.request("/maestro_remove", name)
        if not result:
            syslog.error(f"MAESTRO: failed to delete device {name}: {result.code}: {result.message}")
        else:
            self.refreshDevices()
        return result

    def deleteAll(self) -> MaestroResult:
        """Delete all attached controllers for our devices only"""
        result = self.client.request("/maestro_delete_all", GEX_VENDOR_ID, GEX_PRODUCT_ID)
        if not result:
            syslog.error(f"MAESTRO: failed to delete all devices: {result.code}: {result.message}")
        else:
            self.refreshDevices()
        return result



    def pidToIndex(self, pid: int) -> int:
        """Convert a legacy GEX logical PID; service hardware PIDs are shared."""
        index = pid - GEX_PID_BASE
        return index if 0 <= index < GEX_MAX_DEVICES else -1

    def getDevice(self, pid: int):
        """Look up DirectInput using a legacy GEX logical PID (base + index)."""
        if self._dirty:
            self.syncDinput()
        return self._device_map.get(self.pidToIndex(pid))

    @staticmethod
    def _neutral_buffer(controller):
        size = (controller.button_count + 7) // 8 + controller.axis_count * 2
        return bytearray(size) + bytearray([255] * controller.hat_count)

    def getBuffer(self, device_index):
        """Return the local service-layout snapshot; mutating it sends no OSC."""
        return self._buffer_map.get(device_index)

    def _control(self, device_index, control_index, kind):
        controller = self._controller_map.get(device_index)
        if controller is None:
            return None
        count = getattr(controller, f"{kind}_count")
        if type(control_index) is not int or not 1 <= control_index <= count:
            raise ValueError(f"Maestro {kind} index must be 1..{count}")
        return controller

    def _set_axis(self, device_index, axis_index, value):
        controller = self._control(device_index, axis_index, "axis")
        if controller is None:
            return
        if not math.isfinite(value):
            raise ValueError("Maestro axis value must be finite")
        value = max(-1.0, min(1.0, value))
        raw = value * 32767
        raw = math.floor(raw + 0.5) if raw >= 0 else math.ceil(raw - 0.5)
        offset = (controller.button_count + 7) // 8 + (axis_index - 1) * 2
        struct.pack_into("<h", self._buffer_map[device_index], offset, raw)

    def setAxis(self, device_index: int, axis_index: int, value: float):
        """Write a one-based axis, converting GEX -1..1 to service 0..1."""
        with self._lock:
            if not self.enabled or self._stopping.is_set():
                return
            controller = self._control(device_index, axis_index, "axis")
            if controller is None:
                return
            if not math.isfinite(value):
                raise ValueError("Maestro axis value must be finite")
            value = max(-1.0, min(1.0, value))
            self.client.write(f"/maestro_axis/{controller.id}/{controller.axis_names[axis_index - 1]}", (value + 1) / 2)
            self._set_axis(device_index, axis_index, value)

    def _set_button(self, device_index, button_index, is_pressed):
        if self._control(device_index, button_index, "button") is None:
            return
        offset, bit = divmod(button_index - 1, 8)
        buffer = self._buffer_map[device_index]
        if is_pressed:
            buffer[offset] |= 1 << bit
        else:
            buffer[offset] &= ~(1 << bit)

    def setButton(self, device_index: int, button_index: int, is_pressed: bool):
        """Write a one-based descriptor button, including buttons 33..128."""
        with self._lock:
            if not self.enabled or self._stopping.is_set():
                return
            controller = self._control(device_index, button_index, "button")
            if controller is None:
                return
            self.client.write(f"/maestro_button/{controller.id}/{button_index}", int(bool(is_pressed)))
            self._set_button(device_index, button_index, is_pressed)

    def _set_hat(self, device_index, hat_index, value):
        controller = self._control(device_index, hat_index, "hat")
        if controller is None:
            return
        offset = (controller.button_count + 7) // 8 + controller.axis_count * 2 + hat_index - 1
        self._buffer_map[device_index][offset] = value - 1 if value else 255

    def setHat(self, device_index: int, hat_index: int, position: tuple):
        """Write a one-based independent hat using a GEX (x, y) direction."""
        with self._lock:
            if not self.enabled or self._stopping.is_set():
                return
            controller = self._control(device_index, hat_index, "hat")
            if controller is None:
                return
            value = HAT_POSITIONS.get(position, 0)
            self.client.write(f"/maestro_hat/{controller.id}/{hat_index}", value)
            self._set_hat(device_index, hat_index, value)

    def syncBuffer(self, device_index: int):
        """Refresh the local snapshot from DirectInput without sending outputs."""
        import gremlin.joystick_handling

        with self._lock:
            device = self._device_map.get(device_index)
            controller = self._controller_map.get(device_index)
            if device is None or controller is None:
                return
            for axis in range(1, controller.axis_count + 1):
                input_id = device.axis_sequence_to_input_id(axis - 1)
                self._set_axis(device_index, axis, gremlin.joystick_handling.get_axis(device.device_guid, input_id))
            for button in range(1, controller.button_count + 1):
                self._set_button(device_index, button, gremlin.joystick_handling.get_button(device.device_guid, button))
            for hat in range(1, controller.hat_count + 1):
                position = gremlin.joystick_handling.get_hat_position(device.device_guid, hat)
                self._set_hat(device_index, hat, HAT_POSITIONS.get(position, 0))

    def removeDevice(self):
        """Legacy single-controller removal hook."""
        controller = getattr(self, "controller", None)
        if controller is not None:
            self.removeController(controller)
            self.controller = None


class MaestroAxis:
    def __init__(self, device, index):
        self.device, self.axis_id = device, index

    @property
    def value(self):
        return self.device.maestro._read_axis_raw(self.device.id, self.axis_id) / 32767

    @value.setter
    def value(self, value):
        self.device.maestro.setAxis(self.device.id, self.axis_id, value)

    def set_absolute_value(self, value):
        self.value = value


class MaestroButton:
    def __init__(self, device, index):
        self.device, self.button_id = device, index

    @property
    def is_pressed(self):
        return self.device.maestro._read_button(self.device.id, self.button_id)

    @is_pressed.setter
    def is_pressed(self, value):
        self.device.maestro.setButton(self.device.id, self.button_id, value)


class MaestroHat:
    def __init__(self, device, index):
        self.device, self.hat_id = device, index

    @property
    def direction(self):
        degrees = self.device.maestro._read_hat(self.device.id, self.hat_id)
        value = 0 if degrees == -1 else degrees // 4500 + 1
        return next(position for position, code in HAT_POSITIONS.items() if code == value)

    @direction.setter
    def direction(self, value):
        self.device.maestro.setHat(self.device.id, self.hat_id, value)


class MaestroOutputDevice:
    """vjoy.VJoy-compatible axis/button/hat access backed by Maestro OSC."""

    def __init__(self, index, maestro=None):
        self.id = index
        self.maestro = maestro if maestro is not None else Maestro()
        self.maestro.markOutputUsed()

    @property
    def controller(self):
        controller = self.maestro.getController(self.id)
        if controller is None:
            raise RuntimeError(f"Maestro device {self.id} is unavailable")
        return controller

    @property
    def axis_count(self):
        return self.controller.axis_count

    @property
    def button_count(self):
        return self.controller.button_count

    @property
    def hat_count(self):
        return self.controller.hat_count

    def is_axis_valid(self, axis_id=None, linear_index=None):
        index = axis_id if axis_id is not None else linear_index
        return type(index) is int and 1 <= index <= self.axis_count

    def is_button_valid(self, index):
        return type(index) is int and 1 <= index <= self.button_count

    def is_hat_valid(self, index):
        return type(index) is int and 1 <= index <= self.hat_count

    def axis(self, axis_id=None, linear_index=None):
        index = axis_id if axis_id is not None else linear_index
        if not self.is_axis_valid(index):
            raise ValueError(f"Invalid Maestro axis: {index}")
        return MaestroAxis(self, index)

    def button(self, index):
        if not self.is_button_valid(index):
            raise ValueError(f"Invalid Maestro button: {index}")
        return MaestroButton(self, index)

    def hat(self, index):
        if not self.is_hat_valid(index):
            raise ValueError(f"Invalid Maestro hat: {index}")
        return MaestroHat(self, index)


class _MaestroDialogSignals(QtCore.QObject):
    completed = QtCore.Signal(object, object)

@dataclass
class MaestroProfileInfo:
    """Python equivalent of ProfileInfo in the Maestro service (/maestro_capabilities_result)."""

    id: str = "" # Maestro device ID
    name: str = "" # Maestro device name
    type: str = "" # Maestro device type - e.g., "joystick", "wheel", etc. or "custom" for custom joystick device
    vendor_id: int = 0 # USB vendor ID
    product_id: int = 0 # USB product ID
    deployable: bool = False # Whether the device is deployable in Maestro
    axis_names: tuple = () # Names of the axes
    button_count: int = 0  # physical buttons (ButtonCount)
    addressable_buttons: int = 0 # Number of addressable buttons
    hat_count: int = 0 # Number of hats
    has_hat: bool = False # Whether the device has a hat
    hat_logical_min: int | None = None # Logical minimum value for the hat
    hat_logical_max: int | None = None # Logical maximum value for the hat
    button_map: tuple | None = None # Mapping of buttons
    kind: str = "profile" # Kind of the profile
    used_profile_name: str | None = None # Name of the used profile to build the device in Maestro (if one was used from an emulation)
    profile_id : str = "" # Profile ID
    device_id: str = "" # Service device ID the capabilities were requested for

    @property
    def axis_count(self) -> int:
        return len(self.axis_names)

    @classmethod
    def from_dict(cls, data: dict, device_id: str = ""):
        button_count = data.get("buttonCount") or 0
        button_map = data.get("buttonMap")
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            type=data.get("type", ""),
            vendor_id=data.get("vendorId", 0),
            product_id=data.get("productId", 0),
            deployable=data.get("deployable", False),
            axis_names=tuple(data.get("axes") or ()),
            button_count=button_count,
            addressable_buttons=data.get("addressableButtons") or button_count,
            hat_count=data.get("hatCount") or 0,
            has_hat=data.get("hasHat", False),
            hat_logical_min=data.get("hatLogicalMin"),
            hat_logical_max=data.get("hatLogicalMax"),
            button_map=tuple(button_map) if button_map is not None else None,
            kind=data.get("kind") or "profile",
            used_profile_name=data.get("usedProfileName"),
            profile_id=data.get("profileId", ""),
            device_id=device_id,
        )



class MaestroNewDeviceDialog(QRememberDialog):
    """Collects all parameters needed to create a Maestro device: a custom joystick or a Maestro profile."""

    def __init__(self, profiles, existing_ids, parent=None):
        super().__init__("MaestroNewDeviceDialog", width=480, height=320, parent=parent)
        self.setWindowTitle("New Maestro Device")
        self.setModal(True)
        self._profiles = profiles
        self._existing_ids = set(existing_ids)

        self.profile_widget = QDataComboBox(wheel_enabled=False)
        self.profile_widget.addItem("Custom joystick", "")
        for profile in sorted(profiles.values(), key=lambda p: p["name"].casefold()):
            if profile.get("deployable") and profile["type"].lower() not in ("keyboard", "mouse"):
                self.profile_widget.addItem(profile["name"], profile["id"])
        self.axes_widget = QIntLineEdit(min_range=0, max_range=8, value=8, chars=3)
        self.buttons_widget = QIntLineEdit(min_range=0, max_range=128, value=128, chars=4)
        self.hats_widget = QIntLineEdit(min_range=0, max_range=4, value=4, chars=3)
        self.active_widget = QDataCheckbox("Active on host", checked=True)
        self.include_widget = QDataCheckbox("Include in Gremlin", checked=True)
        self.warning_widget = QWarningWidget(autohide=True)
        self.create_button = QDataPushButton("Create", clicked=self._accept)
        self.cancel_button = QDataPushButton("Cancel", clicked=self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        for widgets in (
            ["Profile:", self.profile_widget],
            ["Axes:", self.axes_widget, "Buttons:", self.buttons_widget, "Hats:", self.hats_widget],
            [self.active_widget, self.include_widget],
        ):
            layout.addWidget(getHContainer(widgets, widget_only=True))
        layout.addWidget(self.warning_widget)
        layout.addStretch()
        layout.addWidget(getHContainer(["||", self.create_button, self.cancel_button], widget_only=True, auto_size=True))

        self.profile_widget.currentIndexChanged.connect(self._profile_changed)
        self._profile_changed()

    def _is_gamepad(self) -> bool:
        profile = self._profiles.get(self.profile_widget.currentData(), {})
        return profile.get("type", "").lower() == "gamepad"

    def _next_id(self) -> str:
        """Next free GEX-managed ID: gex-N for joysticks, gex-gp-N for gamepads."""
        prefix = "gex-gp-" if self._is_gamepad() else "gex-"
        for index in range(1, GEX_MAX_DEVICES + 1):
            if f"{prefix}{index}" not in self._existing_ids:
                return f"{prefix}{index}"
        return ""

    def _profile_changed(self, *args):
        profile_id = self.profile_widget.currentData()
        for widget in (self.axes_widget, self.buttons_widget, self.hats_widget):
            widget.setEnabled(not profile_id)
        if profile_id:
            profile = self._profiles.get(profile_id, {})
            self.axes_widget.setValue(len(profile.get("axes", [])))
            self.buttons_widget.setValue(min(profile.get("addressableButtons", 32), 128))
            self.hats_widget.setValue(profile.get("hatCount", 1))

    def _accept(self):
        custom = not self.profile_widget.currentData()
        if not self._next_id():
            self.warning_widget.setText(f"The maximum of {GEX_MAX_DEVICES} GEX devices of this type already exists.")
            return
        if custom and (self.axes_widget.value() or 0) + (self.buttons_widget.value() or 0) + (self.hats_widget.value() or 0) == 0:
            self.warning_widget.setText("A custom joystick requires at least one axis, button or hat.")
            return
        self.accept()

    @property
    def include(self) -> bool:
        return self.include_widget.isChecked()

    def definition(self) -> dict:
        """The device definition in the format used by save_device_definition; ID and name are GEX-managed."""
        device_id = self._next_id()
        custom = not self.profile_widget.currentData()
        return dict(
            id=device_id,
            kind="custom" if custom else "profile",
            profileId=self.profile_widget.currentData() or "custom-" + device_id,
            name=device_id,
            axes=self.axes_widget.value() if custom else 0,
            buttons=self.buttons_widget.value() if custom else 0,
            hats=self.hats_widget.value() if custom else 0,
            enabled=self.active_widget.isChecked(),
        )


class MaestroDialog(QRememberDialog):
    """Configure HIDMaestro via the GEX bridge, edit service devices and update GremlinEx targets."""

    devices_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__("MaestroDialog", width=920, height=760, parent=parent)
        self.setWindowTitle("Maestro Devices")
        self.setModal(True)
        self.config = gremlin.config.Configuration()
        self.maestro = Maestro()
        self.maestro.connected_changed.connect(self._handle_maestro_connection_changed)
        self.verbose = self.config.verbose_mode_maestro

        self._busy = False
        self._tested_settings = None
        self._definitions = {}
        self._profiles = {}
        self._selected_ids = set()
        self._previous = None
        self._completion = None
        self._signals = _MaestroDialogSignals(self)
        self._signals.completed.connect(self._completed, QtCore.Qt.ConnectionType.QueuedConnection)
        layout = QtWidgets.QVBoxLayout(self)
        self._select_widget_map = {} # map of device ID to the selection box in the table

        self.enabled_widget = QEnabledWidget()
        self.connected_widget = QEnabledWidget("Enable Maestro", enabled=self.maestro.connected())

        self.connection_group = QGroupBoxV("Maestro Bridge service")
        self.host_widget = QDataLineEdit(self.config.maestro_osc_host, tooltip="Host name or IPv4 address of the Maestro service")
        self.port_widget = QIntLineEdit(min_range=1, max_range=65535, value=self.config.maestro_osc_port, chars=6)
        self.reply_host_widget = QDataIPLineEdit(self.config.maestro_osc_reply_host)
        self.reply_port_widget = QIntLineEdit(min_range=1, max_range=65535, value=self.config.maestro_osc_reply_port, chars=6)
        self.refresh_button = Buttons.getRefreshWidget(
            "Refresh Devices", callback=self._refresh_devices, tooltip="Refresh the list of connected Maestro devices"
        )
        self.host_self_widget = QDataPushButton("Set Self", clicked=self._handle_set_self_reply_host)
        self.ping_button = QDataPushButton("Ping Maestro", clicked=self._handle_ping_maestro)
        self.select_none_button = QDataPushButton("Select None", clicked=self._handle_select_none, tooltip="Deselect all devices")
        self.select_all_button = QDataPushButton("Select All", clicked=self._handle_select_all, tooltip="Select all devices")
        self.delete_all_button = QDataPushButton("Delete All Devices", clicked=self._handle_delete_all_devices, tooltip="Delete all connected Maestro devices")
        self.connection_group.addWidget(
            getHContainer(
                [
                    "Host:",
                    self.host_widget,
                    "Port:",
                    self.port_widget,
                    self.refresh_button,
                    self.ping_button,
                ],
                widget_only=True,
            )
        )



        self.connection_group.addWidget(
            getHContainer(
                [
                    "Receive replies on:",
                    self.reply_host_widget,
                    "Reply port:",
                    self.reply_port_widget,
                    self.host_self_widget,
                ],
                widget_only=True,
                tooltip="Reply port must match the host service's SendPort. For another host, use a local LAN interface or 0.0.0.0.",
            )
        )
        layout.addWidget(self.connection_group)
        self.status_widget = QDataLabel("Enter the service address and test the connection.")
        self.status_widget.setWordWrap(True)
        self.status_widget.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        layout.addWidget(self.status_widget)
        self.warning_widget = QWarningWidget(autohide=True)
        layout.addWidget(self.warning_widget)

        self.devices_group = QGroupBoxV("Devices on host — check devices to include in Gremlin")
        self.device_list = QScrollableWidget(stretch=False, horizontal_scroll=False)
        self.device_list.getLayout().setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.device_list.setMinimumHeight(150)
        self.devices_group.addWidget(self.device_list)
        self.new_button = QDataPushButton("New Device", clicked=self._create_new_joystick, tooltip="Creates a new Maestro virtual device")

        # presets
        presets = {
            "Create one Joystick 8/128/4": {
                "type": "joystick",
                "count": 1,
                "axes": 8,
                "buttons": 128,
                "hats": 4,
                "tooltip": "Createas a single gex-1 device with 128 buttons, 8 axes and 4 hats",
            },
            "Create four Joysticks 8/128/4": {
                "type": "joystick",
                "count": 4,
                "axes": 8,
                "buttons": 128,
                "hats": 4,
                "tooltip": "Create gex-1 to gex-4 devices with 128 buttons, 8 axes and 4 hats",
            },
            "Create eight Joysticks 8/128/4": {
                "type": "joystick",
                "count": 8,
                "axes": 8,
                "buttons": 128,
                "hats": 4,
                "tooltip": "Create gex-1 to gex-8 devices with 128 buttons, 8 axes and 4 hats",
            },
            "Xbox 360 controller": {
                "type": "gamepad",
                "definition": "xbox-360-wired",
                "tooltip": "Create a single Xbox 360 device with 12 buttons, 6 axes and 1 hat",
            },
        }
        self.presets_widget = QDataPushButton("Presets...", tooltip="Select a preset configuration for joystick or gamepad devices")
        menu = QtWidgets.QMenu(self)
        for preset_name, preset_data in presets.items():
            action = menu.addAction(preset_name)
            action.setToolTip(preset_data.get("tooltip", ""))
            action.triggered.connect(lambda checked, preset_name=preset_name, preset_data=preset_data: self._handle_preset_selected(preset_name, preset_data))
        self.presets_widget.setMenu(menu)

        self.devices_group.addWidget(
            getHContainer(
                [
                    self.presets_widget,
                    self.new_button,
                    "||",
                    self.select_none_button,
                    self.select_all_button,
                    self.delete_all_button,
                ],
                widget_only=True,
            )
        )
        layout.addWidget(self.devices_group, 1)

        self.apply_button = QDataPushButton("Apply to Gremlin", clicked=self._apply)
        self.close_button = QDataPushButton("Close", clicked=self.close)
        layout.addWidget(
            getHContainer(
                [
                    "||",
                    self.apply_button,
                    self.close_button,
                ],
                widget_only=True,
                auto_size=True,
            )
        )
        for widget in (self.host_widget, self.reply_host_widget, self.port_widget, self.reply_port_widget):
            widget.textChanged.connect(self._invalidate_connection)

        layout.addWidget(getHContainer([self.connected_widget, self.enabled_widget], widget_only=True))
        self._update_enabled()

        # refresh on start if the bridge is connectable
        self._refresh_devices()

    def _handle_preset_selected(self, preset_name: str, preset_data: dict):
        """handle preset selected"""
        mc = Maestro()
        if not mc.ensureConnected():
            # not available
            return
        count = preset_data.get("count", 0)
        axis_count = preset_data.get("axes", 0)
        button_count = preset_data.get("buttons", 0)
        hat_count = preset_data.get("hats", 0)
        definition = preset_data.get("definition", "")
        prompted = False  # true if user has accepted deleting existing devices

        def createJoystick(result: bool, data: tuple):
            # create a stick device
            # index -1 means automatically choose an available index
            axis_count, button_count, hat_count, index, definition = data
            self.maestro.createJoystickController(
                name=f"gex-{index + 1}", axis=axis_count, buttons=button_count, hats=hat_count, at_index=index if index != -1 else None, definition=definition
            )

        def createGamepad(result: bool, data: tuple):
            # create a gamepad device (can be programmed withing GEX as a joystick)
            # index -1 means automatically choose an available index
            axis_count, button_count, hat_count, index, definition = data
            self.maestro.createGamepadController(name=f"gex-gp-{index + 1}", at_index=index if index != -1 else None, definition=definition)

        match preset_data.get("type"):
            case "joystick":
                # create a joystick
                for index in range(count):
                    if index != -1 and self.maestro.hasDeviceAt(index) and not prompted:
                        device = self.maestro.getDeviceAt(index)
                        prompted = True
                        MessageBoxYesNo(
                            prompt=f"A device already exists at index [{index}]:<br> Device ID: [{device.device_id}]<br>Name: [{device.name}]<br>Axis: [{device.axis_count}]<br>Buttons: [{device.button_count}]<br>Hats: [{device.hat_count}].<br>Do you want to replace it?",
                            callback=createJoystick,
                            data=(axis_count, button_count, hat_count, index, definition),
                        )
                        return

                    createJoystick(result=True, data=(axis_count, button_count, hat_count, index, definition))

            case "gamepad":
                # create a gamepad
                for index in range(count):
                    if index != -1 and self.maestro.hasDeviceAt(index) and not prompted:
                        device = self.maestro.getDeviceAt(index)
                        prompted = True
                        MessageBoxYesNo(
                            prompt=f"A device already exists at index [{index}]:<br> Device ID: [{device.device_id}]<br>Name: [{device.name}]<br>Axis: [{device.axis_count}]<br>Buttons: [{device.button_count}]<br>Hats: [{device.hat_count}].<br>Do you want to replace it?",
                            callback=createGamepad,
                            data=(axis_count, button_count, hat_count, index, definition),
                        )
                        return

                    createGamepad(result=True, data=(axis_count, button_count, hat_count, index, definition))

    def _handle_create_device_by_preset(self, preset_name: str, preset_data: dict):
        pass

    def _handle_set_self_reply_host(self, widget):
        """self reply host clicked"""
        self.reply_host_widget.setText(getHostIpSingle())

    def _handle_disconnect(self):
        self.maestro.disconnect()
        self._update_enabled()

    def _handle_ping_maestro(self, widget):
        """ping maestro clicked"""
        if not self.maestro.ensureConnected():
            return
        self.maestro.ping()



    @Slot()
    def _handle_select_none(self):
        """select none clicked"""
        for widget in self._select_widget_map.values():
            if Shiboken.isValid(widget):
                widget.setChecked(False)

    @Slot()
    def _handle_select_all(self):
        """select all clicked"""
        # Implement the logic to select all devices
        for widget in self._select_widget_map.values():
            if Shiboken.isValid(widget):
                widget.setChecked(True)

    @Slot()
    def _handle_delete_all_devices(self):
        """delete all devices managed by GEX"""
        if not self.maestro.ensureConnected():
            return
        MessageBoxYesNo(prompt="Are you sure you want to delete all devices?", callback=self._delete_all_callback)

    def _delete_all_callback(self, result):
        """ deletes all device after confirmation box is confirmed"""
        if result:
            result = self.maestro.deleteAll()
            if result.ok:
                self._refresh_devices()

    def _handle_maestro_connection_changed(self, connected: bool):
        gremlin.util.InvokeUiMethod(self._handle_maestro_connection_changed_ui, connected)

    def _handle_maestro_connection_changed_ui(self, connected: bool):
        # runs on UI thread to update the UI on a new valid connection
        self._update_enabled()

    def _handle_create_device_by_index(self, widget, index: int):
        # creates or replaces a Maestro device with the given index duplicating a vjoy device
        mc = Maestro()
        if not mc.ensureConnected():
            # not available
            return

        if mc.hasDeviceAt(index):
            device = mc.getDeviceAt(index)

            def callback(result):
                if result:
                    mc.removeJoystickController(at_index=index)
                else:
                    return

            MessageBoxYesNo(
                prompt=f"A device already exists at index [{index}]:<br> Device ID: [{device.device_id}]<br>Name: [{device.name}]<br>Axis: [{device.axis_count}]<br>Buttons: [{device.button_count}]<br>Hats: [{device.hat_count}].<br>Do you want to replace it?",
                callback=self._handle_create_device,
                data=index,
            )
            return
        self._handle_create_device(True, index)

    def _handle_create_device(self, result, index: int):
        if not result:
            return
        mc = Maestro()
        if not mc.ensureConnected():
            return
        mc.createJoystickController(axis=8, buttons=128, hats=4, at_index=index)
        self._refresh_devices()

    def _settings(self):
        host, reply_host = self.host_widget.text().strip(), self.reply_host_widget.text().strip()
        port, reply_port = self.port_widget.value(), self.reply_port_widget.value()
        if not host or not reply_host or port is None or reply_port is None or not 1 <= port <= 65535 or not 1 <= reply_port <= 65535 or port == reply_port:
            raise ValueError("Enter a host, a reply interface and two different ports between 1 and 65535")
        return host, port, reply_host, reply_port

    def _invalidate_connection(self, *args):
        self._tested_settings = None
        self._update_enabled()
        self.status_widget.setText("Connection settings changed. Test the connection to load this host's devices.")

    def _update_enabled(self):
        """updates dialog widget state based on connection status and device availability"""
        connected = self._tested_settings is not None
        self.connection_group.setEnabled(not self._busy)
        self.devices_group.setEnabled(connected and not self._busy)
        self.apply_button.setEnabled(connected and not self._busy)
        self.enabled_widget.setEnabled(not self._busy)
        self.connected_widget.setEnabled(connected)
        self.close_button.setEnabled(not self._busy)
        has_devices = bool(self._select_widget_map)
        self.select_all_button.setEnabled(has_devices)
        self.delete_all_button.setEnabled(has_devices)
        self.new_button.setEnabled(connected)
        self.presets_widget.setEnabled(connected)


    def _submit(self, operation, complete, message):
        if self._busy:
            return
        self._busy = True
        self._completion = complete
        self.warning_widget.setText("")
        self.status_widget.setText(message)
        self._update_enabled()
        signals = self._signals

        def run():
            result, error = None, None
            try:
                result = operation()
            except Exception as exc:
                syslog.exception("MAESTRO: dialog operation failed")
                error = str(exc)
            signals.completed.emit(result, error)

        threading.Thread(target=run, name="Maestro dialog request", daemon=True).start()

    @QtCore.Slot(object, object)
    def _completed(self, result, error):
        self._busy = False
        complete, self._completion = self._completion, None
        if error:
            self.warning_widget.setText(error)
            self.status_widget.setText("The operation did not complete. Refresh to read the host's current devices.")
        else:
            complete(result)
        self._update_enabled()

    def _refresh_devices(self):
        try:
            settings = self._settings()
        except ValueError as error:
            self.warning_widget.setText(str(error))
            return
        retain_selection = settings == self._tested_settings
        self._tested_settings = None

        def operation():
            self.maestro.connect(*settings)
            snapshot = service_snapshot(self.maestro.client)
            capabilities = {}
            for definition in snapshot["definitions"]:
                caps = self.maestro.getCapabilities(definition["id"])
                if caps is not None:
                    capabilities[definition["id"]] = caps
            snapshot["capabilities"] = capabilities
            return snapshot

        def complete(snapshot):
            self._tested_settings = settings
            if not retain_selection:
                same_host = settings[:2] == (self.config.maestro_osc_host, self.config.maestro_osc_port)
                selected = self.config.maestro_device_map if same_host else None
                attached = {c.id for c in self.maestro._controller_map.values()} if same_host else set()
                self._selected_ids = (
                    set(selected)
                    if selected is not None
                    else {d["id"] for d in snapshot["definitions"] if d["id"] in attached or self.maestro._service_index(d["id"]) is not None}
                )
            self._load_snapshot(snapshot)
            self.status_widget.setText(f"Connected to {settings[0]}:{settings[1]} — {len(snapshot['devices'])} active device(s).")

        self._submit(operation, complete, "Testing the connection and reading devices…")

    def _load_snapshot(self, snapshot, select_id=None):
        self._definitions = {d["id"]: d for d in snapshot["definitions"]}
        self._profiles = {p["id"]: p for p in snapshot["profiles"]}
        active = {d["id"] for d in snapshot["devices"]}
        self._selected_ids.intersection_update(self._definitions)
        self.device_list.clear()
        capabilities = snapshot.get("capabilities", {})
        # clear the UI
        self.device_list.clear()
        self._select_widget_map.clear()

        if capabilities:
            if self.verbose:
                syslog.info("Maestro snapshot summary:")
                syslog.info(f"\tAttached devices: {len(self._definitions)}")
            cap : MaestroProfileInfo
            for cap in capabilities.values():

                device_id = cap.device_id
                axes = cap.axis_count
                buttons = cap.addressable_buttons
                hats = cap.hat_count
                checkbox = QDataCheckbox(data=cap, checked=device_id in self._selected_ids, callbackEx=self._selection_changed)
                self._select_widget_map[device_id] = checkbox

                label = QDataLabel(
                    f"{cap.name}  [{device_id}/{cap.kind}] — {axes} axes, {buttons} buttons, {hats} hats — {'Active' if device_id in active else 'Inactive'}"
                )
                label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                # edit = QDataPushButton("...", data=device_id, callback=self._edit_clicked)
                delete = Buttons.getDeleteWidget(data=device_id, callback=self._delete_clicked)
                self.device_list.addWidget(getHContainer([checkbox, (label, 1), delete], right_stretch=False, widget_only=True))
                if self.verbose:
                    syslog.info(f"\tDevice: {cap.name} [{device_id}] — kind: [{cap.kind}] Maestro build profile: [{cap.used_profile_name}] — type: [{cap.type}] — {axes} axes, {buttons} buttons, {hats} hats — {'Active' if device_id in active else 'Inactive'}")





        else:
            self.device_list.addWidget(QDataLabel("No devices were found. Use New Device or presets to create some."))

    def _selection_changed(self, widget, checked):
        if checked:
            self._selected_ids.add(widget.data.device_id)
        else:
            self._selected_ids.discard(widget.data.device_id)

    # def _edit_clicked(self, widget, data):
    #     self._edit_device(data)

    def _delete_clicked(self, widget, data):
        self._delete_device(data)

    # def _edit_device(self, device_id):
    #     """ called when the edit button is pressed """
    #     self._previous = dict(self._definitions[device_id])
    #     row = self._previous
    #     self.id_widget.setText(row["device_id"])
    #     self.id_widget.setReadOnly(True)
    #     self.name_widget.setText(row["name"])
    #     profile_id = "" if row["kind"] == "custom" else row["profile_id"]
    #     index = self.profile_widget.findData(profile_id)
    #     if index < 0:
    #         self.profile_widget.addItem(profile_id, profile_id)
    #         index = self.profile_widget.count() - 1
    #     self.profile_widget.setCurrentIndex(index)
    #     self.axes_widget.setValue(row["axes"])
    #     self.buttons_widget.setValue(row["buttons"])
    #     self.hats_widget.setValue(row["hats"])
    #     self.active_widget.setChecked(row["enabled"])
    #     self.include_widget.setChecked(device_id in self._selected_ids)
    #     self._profile_changed()

    def _delete_device(self, device_id):
        try:
            self.maestro.deleteDevice(device_id)  # @IgnoreException
        except MaestroServiceError as e:
            MessageBox.warning(self, "Error", f"Failed to delete device {device_id}: {e}")
            return

        if device_id in self._definitions:
            del self._definitions[device_id]
        if device_id in self._selected_ids:
            self._selected_ids.discard(device_id)
        self._refresh_devices()

    def _create_new_joystick(self):
        """Prompts for all device creation parameters and creates the device on the host."""
        dialog = MaestroNewDeviceDialog(self._profiles, self._definitions.keys(), self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        definition = dialog.definition()
        device_id = definition["id"]
        include = dialog.include
        if include and len(self._selected_ids) >= GEX_MAX_DEVICES:
            self.warning_widget.setText(f"Gremlin supports at most {GEX_MAX_DEVICES} Maestro targets. Uncheck another device first.")
            include = False

        def operation():
            save_device_definition(self.maestro.client, definition, None)
            snapshot = service_snapshot(self.maestro.client)
            snapshot["capabilities"] = {}
            for row in snapshot["definitions"]:
                caps = self.maestro.getCapabilities(row["id"])
                if caps is not None:
                    snapshot["capabilities"][row["id"]] = caps
            return snapshot

        def complete(snapshot):
            if include:
                self._selected_ids.add(device_id)
            self._load_snapshot(snapshot, device_id)
            self._apply()

        self._submit(operation, complete, "Creating device…")

    def _create_new_gamepad(self):
        """creates a new device entry with default values for the UI widgets"""
        self._previous = None
        self.maestro.syncBridge()  # ensure we're updated with the latest controller state
        for i in range(GEX_MAX_DEVICES):
            name = self.maestro._gamepad_id(i)
            if not self.maestro.hasControllerName(name):
                self.maestro.createGamepadController(name)
                self._profile_changed()
                return

    def _apply(self):
        if len(self._selected_ids) > GEX_MAX_DEVICES:
            self.warning_widget.setText(f"Select at most {GEX_MAX_DEVICES} Maestro targets.")
            return
        current_map = self.config.maestro_device_map or {}
        device_map = {key: value for key, value in current_map.items() if key in self._selected_ids}
        for device_id in sorted(self._selected_ids):
            if device_id not in device_map:
                preferred = Maestro.klass._service_index(device_id)
                slots = [preferred] if preferred is not None else []
                slots += list(range(GEX_MAX_DEVICES))
                device_map[device_id] = next(index for index in slots if index not in device_map.values())
        settings = self._tested_settings
        enabled = self.enabled_widget.isChecked()

        def operation():
            # A previous Apply may have disabled/closed the output transport.
            self.maestro.connect(*settings)
            if enabled:
                self.maestro.LoadActiveControllers(device_map)
                self.maestro.populateDeviceList()
            else:
                # Keep the management connection usable while output is off.
                # Host device activation and Gremlin output are independent.
                self.maestro._stopping.set()
                with self.maestro._lock:
                    for controller in self.maestro._controller_map.values():
                        result = self.maestro.client.request("/maestro_reset", controller.id, timeout=0.3, attempts=1)
                        if not result:
                            syslog.error(f"MAESTRO: failed to reset controller {controller.id}: {result.message}")
                    self.maestro._controller_map.clear()
                    self.maestro._device_map.clear()
                    self.maestro._buffer_map.clear()
                from gremlin import joystick_handling

                joystick_handling.set_maestro_devices([])
            return service_snapshot(self.maestro.client) if self.maestro.client is not None else None

        def complete(snapshot):
            (self.config.maestro_osc_host, self.config.maestro_osc_port, self.config.maestro_osc_reply_host, self.config.maestro_osc_reply_port) = settings
            self.config.maestro_device_map = device_map
            self.config.maestro_device_count = len(device_map)
            self.config.maestro_enabled = enabled
            self.config.save()
            if snapshot is not None:
                self._load_snapshot(snapshot)
            else:
                self._tested_settings = None
            self.devices_changed.emit()
            self.status_widget.setText(f"Maestro settings saved. {len(self.maestro._controller_map)} active target(s) available in Gremlin.")

        self._submit(operation, complete, "Updating the Maestro target list…")

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):
        if not self._busy:
            super().reject()
