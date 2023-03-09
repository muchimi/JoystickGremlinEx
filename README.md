Joystick Gremlin EX
================

Introduction
------------

For general Joystick Gremlin documentation - consult https://whitemagic.github.io/JoystickGremlin/

This custom version adds to release 13.3 of Gremlin:

- Upgrade x64 Python 10 (I will consider Python 11 later)
- Improved stability when loading a plugin that has an error on load


Adds a few decorators not in version 13:

### @gremlin_start

Called when a profile is started

### @gremlin_stop

Called when a profile is stopped

### @gremlin_mode

Called when the mode is changed (use def mode_change(mode) - mode will be a string).


## Recommended Resources

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