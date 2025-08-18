# Resources

GremlinEx includes all dependencies in the release.  There are however some companion applications that are highly recommended for full functionality:

## Required modules

### VJOY

VJOY is an open source virtual joystick driver used by GremlinEx as output.  VJOY can be installed from: [https://github.com/jshafer817/vJoy/releases](https://github.com/jshafer817/vJoy/releases) 

Version recommended: 2.1.9.1 for Windows 10/11 x64.

Other versions may work, however the DLLs must match as the DLL included in GremlinEx is only for 2.1.9.1.

### HIDHide

HIDHide is an open source tool to manage by process device visibility.  In other words, HIDHide is used to "hide" inputs from games so that the game only sees VJOY as mapped through GremlinEx.  The tool is essential to avoid confusion in the game's own mapper.

HIDHide and documentation is available here: [https://github.com/nefarius/HidHide](https://github.com/nefarius/HidHide)

Version recommended: 1.5.230.0 or later.

### GremlinEX WASM (MSFS) module

This module is included in the GremlinEx release.  

This C++ module is part of GremlinEx and is necessary for GremlinEx to be able to access internal simulator variables and run SimConnect "expressions" not otherwise exposed via the SimConnect SDK.   This module is written in C++ and included with GremlinEx relases as a zip file.

The module is compatible with Microsoft Flight Simulator 2024 and may work with MSFS 2020 (untested).

The project source code can be found here:

[https://github.com/muchimi/JoystickGremlinBridge](https://github.com/muchimi/JoystickGremlinBridge)

The release is also included in the GremlinEx repository:

[https://github.com/muchimi/JoystickGremlinEx/releases/tag/msfs_wasm](https://github.com/muchimi/JoystickGremlinEx/releases/tag/msfs_wasm)

### GremlinEx DInput module

This module is a depency of GremlinEx and included in the GremlinEx releases.

This C++ module is part of GremlinEx and is the interface to the Microsoft DirectInput (part of DirectX) API to access HID input devices.  Installation is not necessary as the required files are already included as a dependency in the GremlinEx releases.  

The project source code is located here:

[https://github.com/muchimi/dinput](https://github.com/muchimi/dinput)



## Recommended Tools

These companion tools are recommended to work alongside GremlinEx.

### BitFocus Companion

Bitfocus Companion is a panel integrator able to manage from a single environment a number of hardware control panels such as Elgato, LoupeDeck, Razer and other hardware control surfaces.  A key feature of Companion is that it works with the OSC protocol, thus enables two-way communications between hardware panels and GremlinEx.

With BitFocus Companion it becomes easy to press a button on a Streamdeck, rotate a knob on a LoupeDeck and have GremlinEx translate these inputs to games.

While the setup and usage of Companion is beyond the scope of this document, there are some simple setup steps outlined with screenshots in the [GremlinEx discord channel](https://discord.com/channels/1279461873317707827/1292975259003256935) on how to set it up to work with GremlinEx.

[Bitfocus Companion](https://bitfocus.io/companion)


### Glass Surface control tools

These tools let you design an interface for touch-screens to send data to GremlinEx for mapping purposes.  These applications run on separate computers and connect to GremlinEx via the network.  The recommended protocol is OSC because it is much more flexible and easy to use.  MIDI can work as well but it's more difficult to setup in a networked environment because it doesn't natively support this, and because the MIDI protocol was designed decades ago, it is not as flexible as OSC.

#### Open Stage Control

Open Stage Control is an open source glass surface programming tool that lets you place graphics and widgets on a screen that will send OSC messages to GremlinEx, for a "GameGlass" type experience.

[https://openstagecontrol.ammd.net/](https://openstagecontrol.ammd.net/)

#### Touch/OSC

Touch/OSC is an OSC/MIDI glass surface controller application (payware).  While Touch/OSC as of this writing does not support images, Touch/OSC supports sophisticated internal scripting for OSC and MIDI message handling which can be helpful in certain situations.  Touch/OSC is similar to OSC/Pilot.

[https://hexler.net/touchosc](https://hexler.net/touchosc)

#### OSC/Pilot

OSC/Pilot is an OSC/MIDI glass surface controller application (payware).  This application supports graphics and images but does not currently support internal scripting.   OSC/Pilot is similar to Touch/OSC.

[https://oscpilot.com/](https://oscpilot.com/)

#### MIDI over the network

RTP-MIDI is a MIDI virtual driver (freeware) that lets you network MIDI data over the network.  Useful to accept input from a MIDI device hooked up to a machine on the network back into GremlinEx.

[rtpMidi](https://www.tobias-erichsen.de/software/rtpmidi.html). 

#### MIDI loop

 Another utility that is useful lets you define a loopback port on the local machine.  The MIDI device connected locally can send to that MIDI device, and GremlinEx can get MIDI input from it without connecting directly to each MIDI device.
 
 [loopMidi](https://www.tobias-erichsen.de/software/loopmidi.html).  
