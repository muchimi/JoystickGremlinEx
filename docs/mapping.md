# Mapping Guide

This section contains some general tips and solutions to typical mapping and setup scenarios.

## General approach to mapping


| Scenario | Description |
| --- | --- |
| Keep it simple! | Whether trying out GremlinEx for the first time, or later when you are a veteran, use the simplest mapping scenario even if more complex options exist. GEX can do extremely complicated mappings, however most scenarios usually require a simple setup to accomplish what you want. The more complex, the harder it is to maintain. |
| Avoid constantly connecting/disconnecting USB controllers | When you connect a device in Windows, it usually gets added as the last device, and the order will change next time you reboot which can be a problem.  The other issue is the ID of the device may change depending how it's connected to the machine, which can cause devices to no longer be found, and new devices to appear. |
| Applying new hardware firmware usually changes IDs | Device IDs can change when you apply a new firmware update or change device capabilities.  Be mindful of this as the ID of the device may need to be changed in the profile. |
| At least one VJOY device must be defined | GremlinEx currently requires at least on VJOY device to exist on the system. This limitation may be removed in a future release but stems from the base architecture of GEX having started out as a way to program VJOY devices so it's inherent to the existing logic and internal API. |
| Each VJOY device must be different! | Each VJOY device must be different from the other either in axis, button or hat count. |
| Use sequential axes in VJOY! | Each VJOY device should be configured using the following order:  X, Y, Z, RX, RY, RZ, S1 an S2 for axes. Axes should not be skipped, so avoid going from X to RX without Y and Z defined. |
| There are usually multiple answers | Many containers and actions in GremlinEx can be used to produce the same output from a given input.  There is no right or wrong way, the approach should be the simplest possible because simple usually means less processing and easier profile maintenance / readability. |
| For mouse button and wheel output mapping | Use the map to keyboard/mouse EX action. This action lets you visually map not only all keyboard and media keys, but also lets you send all mouse buttons and mouse wheel actions. |
| For mouse axis output | Use the map to mouse/Ex action. |
| For mouse wheel output | Use the map to keyboard/mouse EX action. |
| Mapping a thumstick on a joystick | Use the map to vjoy action and you may also want to change the output curve to account for overly sensitive thumsticks. |
| For axis splitting or setting up trigger points on an axis | Use the gated axis action.  Gated Axis is one of the more complex actions in GEX and also the most flexible when it comes to setting up input deadzones, triggering when the axis moves past a certain point, and it supports full range trigger such as entering a range or exiting a range, or triggering continuous rescaled updates while in a given range.  |
| For mapping a gated input throttle | Use the gated axis action. |
| For merging multiple input axes like rudder toe-brakes | Use the map to vjoy action in axis merge mode.  This lets you merge multiple axes on a single mapping, and perform various computations with each merge.  |
| For older potentiometer based inputs that are noisy or fluctuating limits | Setup a calibration on that input to stabilize the input for all profiles.  This is much easier than dealing with the noise/calibration limit issues in the output of a profile. |
| To map physical switches | See the dedicated sections below on how to handle. |
| To map to rotary encoders | Rotary encoders are mapped the same way any input button would. |
| To output random actions | Look at the sequence container and its wiggle feature.  You can randomize the number of steps, their duration, the timing between each step, and also randomize which step is executed.  This works either one time or can auto-repeat randomly as well. |
| To map turboprop beta range and various turboprop throttles / levers in a flight sim | Use the gated axis action on the input axis to match the gates in the simulator and program it for each gate. |
| To map Airbus style airliner throttles with gates | Use the gated axis action to program the simulator with a mix of button and/or axis output.  This lets you also define virtual deadzones if your input hardware does not have these physical detents. |
| To accept inputs from an Elgato Streamdeck | Use Bitfocus Companion to enable OSC messages on the Elgato hardware.  This allows two way communication between GEX and the Elgato hardware, and lets GEX call up specific profiles on the Streamdeck. |
| To accept inputs from general AV hardware such as LoupeDeck or StreamDeck | Use Bitfocus Companion to enable OSC messages on the audio-visual hardware. |
| To accept input from a touch screen / glass surface | Use a tool like Open Stage Control to setup the user interface on your touch device.  GEX will communicate with these devices over the network using the OSC protocol.  This provides a GameGlass experience and is full two-way communication. |
| To remote control a game or application on another network machine | Run the GremlinEx client on the target machine and allow it to be remote controlled by another GremlinEx instance (the master) on the network.  This allows you to send keystrokes, mouse and joystick data to one or more clients on the local network.  GEX also has control functions to enable/disable the feature on the fly. |
| To map to Microsoft Flight Simulator | Use the map to simconnect action and the simconnect configurations.  This provides full access to not only the MSFS SDK but also access to internal variables defined by add-ons using calculator expressions using the GEX WASM module for MSFS.  This lets you bypass all mappings from the MSFS mapper and you control the entire simulation on an aicraft by aircraft basis completely via the SDK and internal variables.  This does require knowlege of these programming points in the simulator, usually described either in the MSFS SDK or in the add-on documentation, or add-on forums.  This provides the same functionality as Spad.Next or Axis-and-Ohs or similar. |
| Annotations | All actions and containers and custom inputs in GEX have comment fields.  Use them to describe what the mapping does as a helpful reference point.  These comments also show up in the debug data and the XML profiles. |

## Known state on start

When a profile starts, the output should be a known quantity to ensure a consistent experience.

There are three features in GremlinEx to make this happen:

- you can trigger actions when a profile starts, stops, or when a mode is entered via the profile/mode special device.  This has two mappings, one for enter/start, the other for stop/exit.
- You can trigger actions when a state changes.  You can keep track of various modes and start/stop using states, and then use these states either as expressions to change the output behavior of the profile.
- Many actions have a synchronize option on profile start, where GEX will read the axis or button state of each input and trigger, on profile start, the action.  This lets your output profile match the state of the input hardware on profile start.   Note that this can be dangerous, for example, if you sync your throttle to a physical lever and that lever is not in the idle position on profile start.

The above features can be used to setup the output on profile start to a known, repeatable output state.


## Two-Way hardware switch

2-way switches have an on position, and an off position.  Typically, only the on position fires an input button.  That input will be on/triggered when the switch is in the on position, and will be off/untriggered when in the off position.

GremlinEx offers several options for this scenario.

| Scenario | Description |
| --- | --- |
| vjoy button on/off | For simple joystick button output, use a single **vjoy remap action** on the input that triggers (on position), and set the button mode to HOLD.  When the switch is on, the vjoy button will be on, when the switch is off, the vjoy button will be off. |
| state on/off | To toggle a state on when the switch is in the on position, use a **map to state action** in HOLD mode. |
| hold a key while the switch is on | Use a **map to keyboard/mouse ex action** in HOLD mode. |
| single or multiple actions to execute when the switch is on, or off, or both | Use a **press/release container**.  This container contains two sets of actions, one for when the switch is in the ON state, the other for when it's released.  If you only need mappings when the switch is ON, leave the release actions blank. This container lets you map several actions. |

## Three-Way hardware switch that maps to three vjoy buttons

Three way switches have three positions.  A position 1, a middle position (usually off), and a position 2.  The switch triggers two inputs, when in position 1 and 2.
Let's call the vjoy buttons A, B and C.

The best way to handle this is to use a  **switch container** to the inputs for position 1.  Add two positions to the container (it defaults with two). 

Steps:

- Map the first position (input press) to a  **vjoy remap action** in button HOLD mode. The output should be button A.
- Map the second position (input release) to a  **vjoy remap action** in button HOLD mode. The output should be button B.  Ensure the container mode is set to release, and auto-release off.  
- Map the third position (input 2 press) to a  **vjoy remap action** in button HOLD mode. The output should be button C.  Select the button input via the drop downs, or use the listen button and throw the switch in that position.
- Map the fourth position (input 2 release) to a  **vjoy remap action** in button HOLD mode. The output should be button B.  Ensure the container mode is set to release, and auto-release off.  Select the button input via the drop downs, or use the listen button and throw the switch in that position.  The input button should match the input specified in the previous step.

This leverages a behavior of the **switch container** that only one output can be on at a time.  This will map vjoy buttons A, B and C to each of the three switch positions, with B being the middle.


## Using states

States are very helpful in GremlinEx to associate and trigger actions based on multiple conditions.  This is because a state can be defined using other states, allowing you to setup a state machine inside your profile.  In many cases, using states is far easier to setup and undertand than using conditions and/or modes.

| Scenario | Description |
| --- | --- |
| Trigger an output when two input buttons on two different devices are pressed | In this setup, you'd define three states, let's call them A, B and C.  The first two, A and B, track the button on each input device.  Use the map to state action to trigger the A and B state when their respective input is pressed.  Use the HOLD mode if the input is momentary, use the TOGGLE mode if the input should be a toggle for each input press.  Define the third state C as a function of states A and B.  In the State device tab, map the C state to the action you want triggered whenever both A and B are pressed. |
| Using states as conditions | This leverages two important features of GEX: A state can be defined as a boolean expression of other states, and a state can trigger actions when the value of the state changes, including setting another state.  These features work together to usually replace very complex conditions.  A state can be set based on an axis position (via gated axis) or crossing an axis position (also via gated axis).  Or a state can be set as in the first example using a combination of inputs on different devices.  GremlinEx states can then trigger a set of actions by mapping actions to a state whenever that state changes. |



