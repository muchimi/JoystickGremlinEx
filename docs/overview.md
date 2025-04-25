# What is GremlinEx?

GremlinEx is a universal controller integrator: it allows you to take input from multiple hardware devices from different manufacturers connected to a local machine, or a remote machine, such as joysticks and HID controllers, OSC (Open Source Control), MIDI, Keyboard and mouse inputs and map them to virtual outputs like VJOY, or keyboard or mouse output, and send that to a game or another process.

# What can GremlinEx do?

GremlinEx can take inputs from any hardware device visible to windows that reports in as a controller (so a device with buttons, hats or axes) and map that to an output.

For example, a button can be used to trigger a complex macro, set a value on a joystick, say something with Text To Speech (TTS), change a profile mode, or sends keystrokes to an application.

An axis can map to an axis, or can be setup to trigger specific actions based on the position of the axis and the direction of travel.

GremlinEx can also listen for OSC or MIDI button or axis messages from the network and trigger actions based on that input.  This is helpful when using a glass control surface that sends messages to GremlinEx.  GremlinEx translates these messages to game outputs.

# Profiles

GremlinEx is configured by mappings stored to a profile.  The profile contains the mapping information and is stored as an XML file.  The usual scenario is each target application GremlinEx sends output to has its own profile.  That profile is a unique collection of mappings.

# Devices

A device is a controller, physically connected to the computer via USB for example, or virtual (for example an OSC message that comes from the network for from VJOY).  

GremlinEx will list the devices it finds at the top of the user interface in a series of tabs.

Devices that are referenced in a profile but not currently avaialble will show in a warning color with a disconnected icon next to them.  This means device information was read from a saved profile, but the device is not currently visible to GremlinEx.

This can happen if the device is disconnected, or when importing a profile from another machine that had different device identifiers so GremlinEx cannot find them on the current machine.

## Physical controllers

A physical device is a controller currently attached to the computer and that has buttons, axes, or hats in any combination.  Such devices are usually connected via USB.

The device will only show if it is an HID compliant game controller - so joysticks, console game controllers, and devices using Arduino or Rasberry Pi (setup as HID controllers) will be displayed.

## Keyboard and mouse

GremlinEx will display a special keyboard device that groups the functionality of a keyboard and mouse.  Note that mouse axis input (mouse movement) is not currently supported as input (it is supported as output).

## OSC and MIDI devices

GremlinEx will display a device for processing OSC and MIDI messages sent to the local machine.  The messages can originate locally or from a remote machine.

While MIDI and OSC are protocols associated with musical instruments, they are also sophisticated stage controllers with touch-screen surfaces or physical sliders, dials, button and touch pads.   GremlinEx can use signals from these devices to control a game.

# Inputs

An input is a source trigger definition.  When you press a button on a controller, move an axis, or press a key or click a mouse button, all these are input source triggers that can be mapped to a series of actions.

Some hardware devices have a fixed set of inputs defined at the hardware (firmware) level.  Some controllers can change that information with their own programming, but for the purpose of GremlinEx, physical hardware defines a fixed number of axes, buttons and hats it can use for mapping.

## Examples of physical inputs

Inputs can be a button on a joystick, and axis or slider on a joystick, a pressed key on the keyboard.

## Examples of virtual inputs

A virtual input does not come from a physical device.  It typically comes from receiving a network message (such as OSC or MIDI), or from a software virtual device like VJOY used as input.   Virtual devices are not "real", but they function nontheless the same way as physical inputs do.

Virtual inputs have to be configured in GremlinEx, so you need to tell GremlinEx what to listen for.  For example, which OSC message to listen to, and what should the message parameters be.

Another input may be a complex key combination to trigger on, such as left-control, left-shift, A and CAPS-LOCK pressed concurrently.  Unlike the "traditional" keyboard combinations, GremlinEx can latch multiple keyboard inputs together and require all of them to be pressed concurrently to trigger, so quad key combinations and up are completely feasible (although perhaps not practical).



