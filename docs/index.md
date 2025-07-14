# Overview

(this documentation is a work in progress)

## What is GremlinEx?

GremlinEx is a universal controller integrator: it allows you to take input from multiple hardware devices from different manufacturers connected to a local machine, or a remote machine, such as joysticks and HID controllers, OSC (Open Source Control), MIDI, Keyboard and mouse inputs and map them to virtual outputs like VJOY, or keyboard or mouse output, and send that to a game or another process.

GremlinEx is independent from any controller software.  It does not require you to run any specific software from a hardware manufacturer to "map" the device.  So long as the device shows up on Windows as an HID device with axes and buttons, GremlinEx will let you map this input.  It is vendor agnostic and relies on standard APIs that are not vendor specific. GremlinEx works with any HID compliant controller device, so supports any device up to eight (8) axes, up to a hundred and twenty eight (128) buttons, and up to four (4) hats.

There is no limit to the number of input devices GremlinEx supports.

Some of these inputs can be virtual, so GremlinEx can also accept inputs from VJOY while sending outputs to VJOY so long as the input device is not the same as the output device to avoid a loop.

GremlinEx can accomplish very sophisticated condition based routing based on one or more concurrent inputs.

Gremlin offers multiple hierarchical modes, each with its own mapping.  A child mode can inherit mappings from the parent mode if the child does not also map that input.

GremlinEx includes a number of built-in containers to solve common mapping scenarios, such as short press versus long press, axis in a certain zone, macros and chaining.

GremlinEx supports the Open Sound Control (OSC) protocol which allows it to receive or send OSC messages to/from suitable devices.  This capability allows GremlinEx to process inputs from touch screen surfaces and touch-devices on the network, and update the devices back.

GremlinEx supports custom Python user scripts for complete programmatic control over the mapping if the built-in capabilities are insufficient or impractical.

## Resources and help

![Discord Icon](assets/discord_small.png)&nbsp;Please join our  [GremlinEx Discord](https://discord.gg/pNadcReth9) server!

## History

GremlinEx is based on a fork from the 2019 [Joystick Gremlin by Whitemagic](https://whitemagic.github.io/JoystickGremlin/).  GremlinEx builds on that excellent software and its concepts, and incorporates notable modifications and enhancements:

- x64 bit support and current Python environments/libraries
- networking support for multiple GremlinEx instances
- [OSC](https://en.wikipedia.org/wiki/Open_Sound_Control) and [MIDI](https://en.wikipedia.org/wiki/MIDI) built in support to enable inputs from StreamDeck, LoupeDeck and networked glass control surfaces like Open Stage Control, OSC/Pilot, Touch/OSC for a "GameGlass" type experience.
- Built in-support for Microsoft Flight Simulator 2020 and 2024 via the SimConnect SDK including a custom WASM module
- Sophisticated containers like Gated Axis
- Highly responsive runtime through a graph based execution model (starting with m73 dev branch)
- Sophisticated latched keyboard and mouse inputs
- Support for all extended keys including F13 to F24
- Playback speed and voice selection for text to speech
- User interface enhancements

While GremlinEx is based on Joystick Gremlin, it's important to note that it is not the same software.  GremlinEx may differ significantly from the original in behavior and compatibility with Joystick Gremlin profile is mostly supported but not guaranteed.

The 2019 repository was forked, and then substantially modified in the last few years to achieve the goals of GremlinEx. While the base concept was preserved, however are substantial changes to the internal API, logic, flows and classes to support GremlinEx's needs and feature set that did not exist, or are heavily modified, deprecated or just replaced with different modules.

GremlinEx makes an attempt to keep with the philosophy of the original project as much as possible, and I am grateful to WhiteMagic and his excellent ideas and concept: Joystick Gremlin remains one of the best mapping utilities I have ever seen or used in decades of simulation and hardware input mapping to games.  The architecture is elegant and served as a launchpad for GremlinEx.

GremlinEx is in active development and thus may include bugs and issues refered to as dragons.  Rather than releasing new features and fixes sporadically, I have adopted an open development model where pre-releases are posted to the dev branch for you to use as the features and fixes are implemented.  Some are more bleeding edge than others.

The benefits of open development outweigh the drawbacks, it encourages feedback and input from the community. I appreciate the patience as not everything will work in every pre-release patch as expected, that is part of the process.
  

## What can I do with GremlinEx?

Some examples of what GremlinEx can do:

- Integrate devices from multiple vendors without the need to use any vendor specific proprietary software.  GremlinEx works with any HID compliant game input device without requiring any special software.  Most of this can be done without ever installing proprietary software from hardware vendors to "program" their devices.   GremlinEx is designed to use the default behavior of an input device and through profiles, map that to a game.
- Take input from one or more devices, physical or virtual, local or networked, and remap that output to a VJOY joystick, and local keyboard and mouse.
- Take input from a game controller like an XBox 360 controller and map it to VJOY.
- If [VIGEM](https://github.com/nefarius/ViGEmBus) is installed, output to virtual game controller for games that do not support joysticks (usually because they are console ports) (VIGEM is technically retired but works well with Windows 10 and Windows 11).
- Map a joystick axis and split it up into multiple zones or trigger specific actions when the input axis is moving, passing through specific points, or within a specific zones (Gated Axis, range container and virtual input).
- Execute actions based on multiple input keys pressed concurrently and other conditions
- Execute macros that combine joystick, mouse, keyboard actions.
- Use touch-surface input (glass surface) via the OSC protocol. While OSC is used for music and stage control, GremlinEx uses OSC to work with Open Stage Control (open source) and other OSC protocol enabled touch control surfaces to map touch-screen inputs to a game over the network.  Because software like [Open Stage Control](https://openstagecontrol.ammd.net/docs/getting-started/introduction/) lets you design any control surface using buttons, faders, knobs, encoders, this becomes an extremely powerful custom touch-screen input mapped to a game via GremlinEx.   GremlinEx also supports two-way communications so that state data can be returned to the touch surface via a plugin or the "map to OSC" action.
- Control Microsoft Flight Simulator (MSFS) 2020 or 2024 via the SimConnect API and a custom WASM module.  This enables GremlinEx to do direct control mappings in MSFS without having to map controllers in MSFS.  GremlinEx can also execute what's called "RPN expressions" and access internal commands and variables, including custom ones created by add-ons).
- Sophisticated condition based execution
- (as of 1.0ex m74) GremlinEx adds a [state machine](https://en.wikipedia.org/wiki/Finite-state_machine) to the behavior model. See [more information on states](overview.md#state-device) in the overview.
- Comprehensive collection of various action container types to solve common mapping problems without custom programming.
- Custom scripting via Python if needed
- Play audio (.wav) files, and use text to speech (TTS) to convert text to audio cues.

## What about device conflicts?

At its core, GremlinEx takes "real" hardware input and maps it to "virtual" joystick outputs via VJOY.  
This can create confusion with in-game control mapping utilities because the game will usually get inputs concurrently from the "real" device and from the "virtual" device.
To avoid this, [HIDHide](https://github.com/nefarius/HidHide) is recommended to "hide" the input devices from the target application.  This is also recommended because many games unfortunately only support a limited of game controllers.

