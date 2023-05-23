Joystick Gremlin EX
================

Introduction
------------

For general Joystick Gremlin documentation - consult https://whitemagic.github.io/JoystickGremlin/

This custom version adds to release 13.3 of Gremlin:

- Udate to x64 bit from x32 bit
- Update to Python 11.x (improved execution speed over Python 10)
- Improved stability when loading a plugin that has an error on load
- Remote data control of another GremlinEx client on the local network
- OSC message handling
- VjoyRemap plugin for control
 

Adds a few decorators not in version 13:

### @gremlin_start

Called when a profile is started

### @gremlin_stop

Called when a profile is stopped

### @gremlin_mode

Called when the mode is changed (use def mode_change(mode) - mode will be a string).

## Remote control feature

GremlinEx adds a feature to link multiple GremlinEx instances running on separate computers.  This is helpful to share a single set of controls and a single profile on a master machine to one or more client machines on the local network.

Events sent over the network include all GremlinEX output functions:
- VJOY joystick axis events (when an axis is moved)
- VJOY joystick button events
- keyboard output events (press/release keys including extended keys)
- mouse output events (pres/release mice button 1 to 5, mouse wheel events, and mouse motion events)
- Gremlin macro outputs

By output events, we mean that inputs into GremlinEx are not broadcast to clients, only events that GremlinEx outputs are synchronized with clients.


### Master machine setup

The master machine will have the broadcast option enabled and an available UDP port setup (default 6012).  When the broadcast feature is enabled, the comptuer will by default broadcast all output events from GremlinEx to the clients on the network.

While more than one master machine can broadcast, it's recommended to only have one.


### Client machine setup

Each GremlinEx client needs to have the remote control option enabled in options to be able to receive events from the master machine.   The master machine must also be setup to broadcast these events.

The client must be in run mode to accept broadcast events, and the profile can be empty.  No profile needs to be loaded on the client when the client is in remote control mode.

Clients will only output to VJOY outputs that match the master.  So if the client has the same setup for VJOY (number of VJOY devices, button counts and hat counts) as the master machine, all VJOY events will be synchronized with the master machine.   This is the recommended setup.   

Clients will ignore events for devices that do not exist on the client (such as an invalid VJOY device number, or an invalid button for that defined device).

## Master control functions

The VJoyRemap plugin adds three control function specific to remote control:
1. Enable remote control (which disables local control) - when this command is issued, the master machine will only output events to remote clients and stop sending events to itself.   This mode should be used when the master only controls another client on the network.
2. Enable local control (which disables remote control) - when this command is issued - the master machine will output regular events to the local machine only.  This mode is used when the master does not control the remote client.
3. Toggle local/remote control.   This command toggles between the two states.





## Recommended Resources

#### VJOY virtual joystick driver 
 
https://github.com/shauleiz/vJoy

Installs one or more virtual programmable HID joysticks on Windows with up to 8 axes, 4 hats and 128 buttons per the DirectInput specification.

#### OSC support in Joystick Gremlin from TouchOSC

https://github.com/muchimi/TouchOsc

Transforms any touch screen into a game control surface, similar to GameGlass.


#### HIDHIDE

This tool hides raw hardware only exposing the VJOY devices.  Essential to not confuse games or simulators.

https://github.com/ViGEm/HidHide

#### Hexler TouchOSC

A touch enabled surface designer initially setup for the OSC (open sound control) and MIDI protocols to control musical instruments, DAWs and live performances.  Supports multiple platforms.  Has a free version but the license is well worth the price.  Simple set of controls, but very powerful because of the available LUA based scripting and works on any platform, thus making your phone, tablet or touch-enabled desktop function as an input device.

https://hexler.net/touchosc#_

I also recommend the Protokol tool to diagnose any OSC issues.