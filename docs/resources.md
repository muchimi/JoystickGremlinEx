# Resources

GremlinEx includes all dependencies in the release.  There are however some companion applications that are highly recommended for full functionality:

## Required modules

### VJOY

VJOY is an open source virtual joystick driver used by GremlinEx as output.  VJOY can be installed from: [https://github.com/jshafer817/vJoy/releases](https://github.com/jshafer817/vJoy/releases) 

Version recommended: 2.1.9.1 for Windows 10/11 x64

### HIDHide

This open source tool manages which devices are visible to a specific process on Windows.  The tool is essential to "hide" physical inputs mapped via GremlinEx from the target application (game) to avoid confusion in the game's own mapper.

HIDHide and documentation is available here: [https://github.com/nefarius/HidHide](https://github.com/nefarius/HidHide)

Version recommended: 1.5.230.0 or later.

## Recommended Tools


### Open Stage Control

Open Stage Control is an open source glass surface programming tool that lets you place graphics and widgets on a screen that will send OSC messages to GremlinEx, for a "GameGlass" type experience.

[https://openstagecontrol.ammd.net/](https://openstagecontrol.ammd.net/)

### Touch/OSC

Touch/OSC is an OSC/MIDI glass surface controller application (payware).  While Touch/OSC as of this writing does not support images, Touch/OSC supports sophisticated internal scripting for OSC and MIDI message handling which can be helpful in certain situations.  Touch/OSC is similar to OSC/Pilot.

[https://hexler.net/touchosc](https://hexler.net/touchosc)

### OSC/Pilot

OSC/Pilot is an OSC/MIDI glass surface controller application (payware).  This application supports graphics and images but does not currently support internal scripting.   OSC/Pilot is similar to Touch/OSC.

[https://oscpilot.com/](https://oscpilot.com/)


## Additional GremlinEx sources

### GremlinEX WASM (MSFS) module 

For Microsoft Flight Simulator (MSFS) 2020/2024

This C++ module is part of GremlinEx and is necessary for GremlinEx to be able to access internal simulator variables and run SimConnect "expressions" not otherwise exposed via the SimConnect SDK.   This module is written in C++ and included with GremlinEx relases as a zip file.

The project source code can be found here:

[https://github.com/muchimi/JoystickGremlinBridge](https://github.com/muchimi/JoystickGremlinBridge)

The release is also included in the GremlinEx repository:

[https://github.com/muchimi/JoystickGremlinEx/releases/tag/msfs_wasm](https://github.com/muchimi/JoystickGremlinEx/releases/tag/msfs_wasm)

### GremlinEx DInput module

This C++ module is part of GremlinEx and is the interface to the Microsoft DirectInput (part of DirectX) API to access HID input devices.  Installation is not necessary as the required files are already included as a dependency in the GremlinEx releases.  

The project source code is located here:

[https://github.com/muchimi/dinput](https://github.com/muchimi/dinput)
