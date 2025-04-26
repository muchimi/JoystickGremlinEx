# GremlinEx Overview

GremlinEx is a universal controller integrator: it allows you to take input from multiple hardware devices from different manufacturers connected to a local machine, or a remote machine, such as joysticks and HID controllers, OSC (Open Source Control), MIDI, Keyboard and mouse inputs and map them to virtual outputs like VJOY, or keyboard or mouse output, and send that to a game or another process.

## What can GremlinEx do?

GremlinEx can take inputs from any hardware device visible to windows that reports in as a controller (so a device with buttons, hats or axes) and map that to an output.

For example, a button can be used to trigger a complex macro, set a value on a joystick, say something with Text To Speech (TTS), change a profile mode, or sends keystrokes to an application.

An axis can map to an axis, or can be setup to trigger specific actions based on the position of the axis and the direction of travel.

GremlinEx can also listen for OSC or MIDI button or axis messages from the network and trigger actions based on that input.  This is helpful when using a glass control surface that sends messages to GremlinEx.  GremlinEx translates these messages to game outputs.

## User Interface Overview

![user_interface](assets/ui_overview.png)

### Menu

The menu offers typical options to create, save or load a profile, access tools and options available in GremlinEx.  

### Toolbar

![toolbar](assets/toolbar.png)

The quick action toolbar below the menu offers buttons to quickly save, load or run a profile.  Quick actions also includes the input viewer dialog, which shows "live" inputs, and quick access to GremlinEx's options.

### Edit mode

![profile_edit_mode](assets/profile_edit_mode.png)

To the right of the toolbar, a drop down with the current edit mode for the active profile is displayed, which lets you change the active edit mode.  It also includes a button to bring up the mode options for the profile to edit/change available modes and their relationships, as well as profile options.

### Device list

![device tabs](assets/device_tabs.png)

The top of the user interface below the toolbar is the device list, shown as a list of tabs.  The list shows all detected devices, as well as special devices (like OSC), keyboard, modes, and some general options to setup user plugins and profile options.

Click on a tab to select the device as the active device.

#### Special devices


| Device     | Description |
| ----------- | ----------- |
| Keyboard   | This device is for keyboard and mouse mappings |
| MODE   | This device allows you to map actions on mode change (entering a mode or exiting a mode) |
| OSC   | This device allows you to map inbound OSC messages |
| MIDI   | This device allows you to map inbound MIDI messages |
| Settings   | This device opens profile options specific to input settings |
| Plugins   | This device allows you to add user plugins to the profile - plugins are loaded whenever the profile start and are written in Python - see the plugin documentation for details |


#### Disconnected devices

![disconnected device tabs](assets/disconnected_device_tabs.png)

If a device was saved to a profile, the profile is loaded, and the device is no longer detected, GremlinEx will indicate the device is not currently available with a disconnected flag as shown above.  The device can be reconnected by plugging it back in, or deleted via the context (right click) menu.  Disconnected devices are normal when opening a profile created on a different machine as device hardware IDs will be different.

It is possible for the disconnected device to have the same name of a current device if the device has a different hardware ID from what is currently detected.

### Input area

![input panel](assets/input_panel.png)

The left of the user interface (UI) is the input area.  It shows a list of available inputs on the currently selected device.

### Linear inputs

Linear inputs indicate an axis type input is detected.   The input can change values.  Examples of linear inputs are a joystick axis, a slider, a fader, or rotary knob.

Linear inputs that have multiple axes, such as an XY pad, will show as one input per axis.

### Momentary inputs

A momentary input is an input that typically has two states - pressed or released such as a key or a button.   A momentary input can also be held in which case it will keep its pressed state until it is released. 

Encoders are also typically momentary but they have multiple positions.  In GremlinEx, an encoder will typically show as two inputs, one to increase, one to decrease.

### Hats

![hat input](assets/hat_input.png)

Hats are a special type of momentary input.  GremlinEx supports eight (8) positions per hat (north, north-east, east, south-east, south, south-west, west and north-west).  The center position is the released state for a hat.
A hat with a push (or pull) function will show as a separate momentary input for the function.

### Keyboard

![keyboard input](assets/keyboard_alt_c_input.png)

The keyboard is a momentary input with a key either pressed or released (known as a key make or a key break).  In the above example, the key sequence alt-c is selected.

### Mouse

![mouse input](assets/mouse_input.png)

In GremlinEx, mouse inputs are available through the keyboard device and GremlinEx supports five mouse buttons, and adds four more for wheel up/down and wheel left/right.  The left button is mouse 1, the right button is mouse 2, the middle button is mouse 3.  Buttons 4 and 5 are sometimes known as the forward and back buttons on the mouse.

### Available inputs

For controller devices, such as a hardware joystick connected to the computer or VJOY virtual controllers, the list of inputs is defined by the controller and cannot be changed.  The list is defined by the controller.

For configurable devices, such as OSC and the keyboard, the inputs must be user configured and can be added, edited or removed.

## Mapping area

![mapping area](assets/mapping_area.png)

The right of the user interface (UI) is the mapping area.  It shows a list of configured mappings for a given input.  GremlinEx organizes mappings using containers and actions.  A mapping will include at least one container, and the container in turn contains one or more actions.  The container type and action type determine what GremlinEx outputs when the input is triggered.

Containers and actions mapped to an input will appear in this area.  In this case, we have a gated axis action mapped to an axis input.

## Profiles

All mappings in GremlinEx are stored in a profile.  Profiles are stored in %user_profile%/Joystick Gremlin Ex.

![profile xml](assets/profile_xml.png)

The profile contains the mapping information and is stored as an XML file.  The profile contains all devices, modes, profile options and mappings for each input.  GremlinEx will not save unmapped devices or inputs to conserve space and speed up the profile load time.

The profile contents can be view in any text editor.  It is not recommended to manually edit the XML file outside of GremlinEx, but it is entirely possible to do so, observing the following:

- Most entities in the profile have a unique ID that cannot be duplicated.  Every entity added manually must have its own unique ID.  IDs are not random - they are GUIDs (globally unique identifiers) to ensure they are unique.
- Some of these entities keep references to other entities by ID so linkage can easily be broken with cut/paste in the XML
- GremlinEx may change the XMl format depending on versions although it is designed to load older versions and "add" the new information if needed when saving.
- Unexpected errors in the XML may crash GremlinEx on load

### Saving a profile

Saving a profile saves (persists) the profile data to a file.  Very few actions in GremlinEx are saved automatically so it's a good idea to save often when you make modifications.

When saving a profile, if a prior profile by that name exists, GremlinEx will make an automatic backup of that profile and keep a number of copies (sequentially numbered).  How many is configured in options and defaults to five (5).  After the number of backups is exceeded, the oldest is deleted.  Profiles are also backed up by version, so each version of GremlinEx has its own backup folder.  This is a safety mechanism in case a new version of GremlinEx introduces profile file format changes (or dragons) that an earlier version may not be able to read.

### Loading a profile

GremlinEx offers a list of recent profiles used to load, listed in order of last use, in the file/open recent option.

When loading a profile, if GremlinEx detects changes were made to the current profile, it will prompt you to save the changes first.   Loading a profile does a reset of all inputs and GremlinEx will attempt to reload the exact device and input that was selected the last time the profile was loaded.

Load times are typically speedy, however large profiles with lots of modes and inputs may take some time to load because of the internal processing that happens.

### Deleting a profile

GremlinEx does not offer in the UI the option to delete a profile.  To remove a profile, you can open File Eplorer to the GremlinEx storage folder via the menu (Actions/Open GremlinEx folder) and delete the file manually.

## Devices

A device is a physical or virtual controller recognized by GremlinEx as an input controler. Examples of devices are joysticks and panels connected to the computer, or a virtual device, such as an OSC input message or a virtual joystick (VJOY).

GremlinEx will list the devices it finds at the top of the user interface in a series of tabs.

Devices that are referenced in a profile but not currently avaialble will show in a warning color with a disconnected icon next to them.  This means device information was read from a saved profile, but the device is not currently visible to GremlinEx.

This can happen if the device is disconnected, or when importing a profile from another machine that had different device identifiers so GremlinEx cannot find them on the current machine.

### Physical (HID) controllers

A physical device is a controller currently attached to the computer and that has buttons, axes, or hats in any combination.  Such devices are usually connected via USB.

Based on the DirectInput specification, controllers can have up to eight (8) axes/sliders, up to 128 buttons and up to four (4) hats.

The device will only show if it is an HID compliant game controller - so joysticks, console game controllers, and devices using Arduino or Rasberry Pi (setup as HID controllers) will be displayed.  HID devices that are not reporting as an HID controller and thus not visible to DirectInput will not be visible in GremlinEx.

GremlinEx will only work with controllers that report through DirectInput (so not the XBox API for example).  All controllers compatible with PC will show in DirectInput.  All controllers compatible with XBox will not show, unless they run in PC/Windows compatibility mode.

### Virtual controllers

A virtual controller is a software controller that exists at the hardware driver level.  VJOY is one such example of a virtual joystick driver, with up to sixteen (16) virtual devices that can be configured in VJOY provided each is different from the other in terms of axis, hat or button count.  Another example is VIGEM, a virtual x-box 360 controller that is similar to VJOY but for a game (console) controller.

### Keyboard and mouse

GremlinEx will display a special keyboard device that groups the functionality of a keyboard and mouse.  Note that mouse axis input (mouse movement) is not currently supported as input (it is supported as output).

### OSC and MIDI devices

GremlinEx will display a device for processing OSC and MIDI messages sent to the local machine.  The messages can originate locally or from a remote machine.

While MIDI and OSC are protocols associated with musical instruments, they are also sophisticated stage controllers with touch-screen surfaces or physical sliders, dials, button and touch pads.   GremlinEx can use signals from these devices to control a game.

### Reordering of devices

Microsoft Windows does not currently offer a way to set the order of devices connected to a computer, and furthermore, this order may change depending on connections/disconnections, reboot status, and the order of detection by the operating system.  To this end, GremlinEx offers a way to manually re-order devices as displayed in GremlinEx for convenience via drag and drop of the device tabs.   The order only exists within GremlinEx and it does not change the device order in the operating system.

## Inputs

An input is a source trigger definition.  When you press a button on a controller, move an axis, or press a key or click a mouse button, all these are input source triggers that can be mapped to a series of actions.

Some hardware devices have a fixed set of inputs defined at the hardware (firmware) level.  Some controllers can change that information with their own programming, but for the purpose of GremlinEx, physical hardware defines a fixed number of axes, buttons and hats it can use for mapping.

### Examples of physical inputs

Inputs can be a button on a joystick, and axis or slider on a joystick, a pressed key on the keyboard.

### Examples of virtual inputs

A virtual input does not come from a physical device.  It typically comes from receiving a network message (such as OSC or MIDI), or from a software virtual device like VJOY used as input.   Virtual devices are not "real", but they function nontheless the same way as physical inputs do.

Virtual inputs have to be configured in GremlinEx, so you need to tell GremlinEx what to listen for.  For example, which OSC message to listen to, and what should the message parameters be.

Another input may be a complex key combination to trigger on, such as left-control, left-shift, A and CAPS-LOCK pressed concurrently.  Unlike the "traditional" keyboard combinations, GremlinEx can latch multiple keyboard inputs together and require all of them to be pressed concurrently to trigger, so quad key combinations and up are completely feasible (although perhaps not practical).

### Input Widget

The input widget corresponds to an input for the device currently selected. For controllers, GremlinEx displays "live" inputs (when the option is enabled, which it is by default).  The repeaters will show the current axis or button state for controllers.

![input widget linear](assets/input_linear.png)


![input widget button](assets/input_button.png)

Input widgets will show an icon for each action map found in the containers attached to the input for a quick visual review of all actions mapped to the input.  

Input widgets will also have a calibration button to calibrate the input axis (global), or for setting up a curve for the input. 

If the input can be configured, for example, OSC or Keyboard devices, a configuration button is also visible.

In the example below, two keystrokes are defined as input. Alt-C and F5.  While Alt-C is not selected, the icon in the input widget indicates it is mapped to button #1.  The input box for F5 shows that it has two actions, button #1 and another joystick action.  

Because the action is complex, it won't show the details but from the action configuration we can see it's setup to toggle button #2 whenever the F5 key is pressed, and to pulse button #1.

![input example](assets/input_example.png)

The bottom of the input panel has two buttons, one to add a new input, one to remove it.   These buttons are only displayed on inputs that are configurable, such as the Keyboard, OSC, or MIDI devices.

![input add remove](assets/input_add_remove_inputs.png)

### Special Mode inputs

The Mode device is a special device that defines two fixed inputs. These are triggered whenever a mode is activated, or deactivated.

In the example below, whenever the "Default" mode is activated, the F18 key will be sent.

![input mode](assets/input_mode.png)

## Automatic input selection

![automatic selection](assets/automatic_selection.png)

Depending on the number of axes and buttons a particular device has, it's not always clear which axis or button it is.  To this end, GremlinEx has a feature to automatically select the input when you move an axis or press a button.  This works for controllers only (so not for keyboard or mouse inputs).

There are four options:

- Disabled: automatic highlighting is turned off.
- Button: automatic highlighting switches to the pressed button.
- Axis: automatic highlighting switches to the moved axis.
- Device: automatic highlighting switches the device.  

These options are also available in the Gremlin options panel.

It it not advised to have the axis or device modes enabled if you have a noisy input as the UI will constantly thrash because it will detect constant inputs.



## Containers

The container holds one or more actions.  There are multiple container types available.  All actions in a container are executed when an input trigger occurs, subject to the options and the capabilities of the container and the action that modify the behavior.

### Basic

The basic container is the most used and the default container.  It is a simple container with one or more actions in it.

### TempoEx

This container has two content areas.  One for short press actions, one for long press actions.

### Chain

This container lets you chain actions.  Whenever the input is triggered, the chain will increment the index and move to the next block of actions index, and loop around when it runs out of blocks to execute.  This is used for round-robin type mappings when you need a sequence of things to happen for each trigger.

### Sequence

This container is a bit like a high level macro, and runs all the actions in the sequence they appear.

### Smart Toggle

This container is used to toggle outputs based on short of long presses.  Used to toggle "hold"/"sticky" outputs.

### Button

This container has a set of actions that execute on input press, and another set on input release, in the same container.

### Range

THis container performs certain actions when the input value is in a certain range

## Actions

Actions are added to a container.  They perform the actual mapping of the input.  



### Action priority

Certain actions execute last (such as a mode change).  Actions have an internal priority that determines when an action runs.  In most cases, actions are executed top down (in the order they appear), however some actions like a mode change are executed last, and actions that change the input value like applying a curve will execute first.

### Vjoy Remap

![vjoy remap action](assets/action_vjoy_remap.png)

This is the most common action in GremlinEx and lets you map an input (linear or momentary) to a VJOY device.

This action replaces the legacy remap option.

### Gated Axis

![gated axis](assets/action_gated_axis.png)

This action lets you split an input axis and define what should happen when

- a range is entered or exited
- a specific point on the axis is crossed

Up to 20 gates or crossing points can be defined (19 ranges). It is possible for ranges to send a fixed value or rescale/change the value of the output.
This container was specifically created for output needs that have "gates", such as throttles used in some simulators.

### Mode Switch

![switch to mode](assets/action_switch_to_mode.png)

This action lets you change a profile mode at runtime based on an input trigger.

### Temporary Mode Switch

![temporary mode switch](assets//action_map_to_temporary_mode_switch.png)

This action lets you change the profile mode temporarily while the input is pressed.

### Mode Cycle

This action lets you cycle modes with each press.

![cycle modes](assets/action_cycle_mode.png)

### Map to Keyboard Ex

![map to keyboard](assets/action_map_to_keyboard_ex.png)

This action lets you send a keyboard or mouse button/wheel click to the output.

### Map to Mouse Ex

![map to mouse ex](assets/action_mouse_ex.png)

This action lets you send a mouse button/wheel or mouse position change to the output.

### Map to Gamepad

![map to gamepad](assets/action_map_to_gamepad.png)

This action maps to a Gamepad (VIGEM) output.

### Map to SimConnect

![map to simconnect action](assets/action_map_to_simconnect.png)


This action lets you send a SimConnect command to Microsoft Flight Simulator via the SimConnect SDK.  

This includes sending calculation and expressions via the GremlinEX WASM module to read or modify internal simulator parameters defined by addons that are not exposed by the SimConnect API (in this example, execute the "(>K:AP_MASTER)" internal command.

![map to simconnect calculator action](assets/action_map_to_simconnect_calculator.png)

### Map to OSC

![map to osc action](assets/action_map_to_osc.png)

This action lets you send an OSC message to the network.

### Text to Speech

![tts action](assets/action_tts.png)

This action lets you send an audio prompt via TTS (text to speech).

### Macro

![macro action](assets/action_macro.png)

This action lets you send complex sequences of outputs (joystick, keyboard, mouse) complete with timing and delay controls and separate make/break actions for buttons.

### Play Sound

![play sound](assets/action_play_sound.png)

This action lets you play a sound file located on disk.

## Conditions

GremlinEx can apply conditions to triggers to modify what should happen when an input trigger happens. 

Conditions can be used to:

- only trigger a mapping if another condition is true (or false), such as an key or button is pressed, released, or another axis is within a certain range.
- trigger on release only
- turn on or off certain activations at the container level or the individual action level.

Conditions apply to containers or actions or both concurrently.

Conditions are cummulative and apply in the order of evaluation, so conditions on containers are evaluated before conditions on actions.

### Virtual Button

When mapping a momentary action to an axis, the virtual button tab usually becomes availble to define a range on the axis where the condition is active.
In the example below, the action is enabled when the input axis is between -0.0965 and +0.324.

![virtual button](assets/condition_virtual_button.png)

### Condition tab

The condition tab on a container (appears below the action tab) is used to configure conditions on the container for its activation. Conditions are cummulative.

![condition tab](assets/condition_tab.png)

#### Container conditions

Container conditions apply to the whole container.  In the example below, button 27 on the HOTAS Warthog device must be pressed for the condition to pass on all actions in the container.

#### Action conditions

Action conditions only apply to a specific condition.  In this case, the play sound action will only be active if the F4 key is pressed.  Because the play action is also subject to the container condition, both conditions must be true for the sound to play.  Because the container is mapped to an axis, and a virtual button is defined, not only do the action and container conditions be true, the axis must also be in the correct range.

