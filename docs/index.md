# Introduction

(this documentation is a work in progress)

## What is GremlinEx?

GremlinEx is a universal game/simpit controller integrator: it allows you to take concurrnt input from various hardware or network devices, such as joysticks, panels, game controllers, and audio-visual hardware and software that supports OSC (Open Source Control) such as a glass surface (touch screen) panel, MIDI, keyboard and mouse inputs and map them to virtual outputs like VJOY, or keyboard or mouse output, and send that to a game or another process.  GremlinEx maps this input to a simplified and consolidated set of outputs, and it is vendor agnostic.   GremlinEx also has the ability to directly send data to Microsoft Flight Simulator via the SimConnect API and a custom WASM module.

Gremlin supports glass surfaces (touch screens), hardware panels like StreamDeck, and even MIDI control panels and works well with tools like Bitfocus Companion and Open Stage Control.

The audience for GremlinEx is anyone looking to easily integrate multiple hardware input devices from joysticks to control panels and map it to a game without having to use proprietary vendor software.  GremlinEx is simple to use for simple mapping scenarios, and it also includes a rich set of tools for the transformations, manipulation and routing of inputs.  GEX supports anything from custom joystick curve editing to conditional output, execution, and has modes and states to dynamically control the execution of mappings at runtime.  GremlinEx can also remote control other GremlinEx instances on the network, playback audio, supports dynamic text to speech, axis merging and axis splitting and scaling, curving and calibration.

A more detailed look at features supported by GremlinEx can be found in the [overview section](overview.md) of the documentation.

## How can I support the project?

The project is a labor of love and started as "I really want to be able to do [missing feature here] and can't find a way to do this".  The project has evolved in the last few years to take significant time and resources to support and develop.

Please consider supporting the project by making a secure donation, either one time or recurring, via the sponsor link on [the home project on Github](https://github.com/muchimi/JoystickGremlinEx).

This project is open source.  It has as of this writing, more than 133,000 of lines of code (almost 200,000 if you include comments) - it is a large project.  Donations help with the purchase of hardware, maintaining computing resources for testing and development platform purposes.  Donations make more time available to research, develop features and support the project on an on-going basis.  Thanks to your help, the project has already seen hundreds of updates, many of them daily.  It has seen the implementation of nearly all requested features, many of which are not available in other similar tools.  It has a [rich set of features](overview.md#key-features-what-can-gremlinex-do), many of them not found in payware tools.   It is your support and shared passion for this hobby that makes GremlinEx, and its continuing support, possible.  

Thank you for considering supporting the project if you have not already, and thank you to those of you who have already supported.

Every bit helps!

## Project Home on Github

The project's [home is on GitHub](https://github.com/muchimi/JoystickGremlinEx) from where you can download the latest releases and view patch notes.

## Support and chat

The project has a dedicated [Discord server](https://discord.com/channels/1279461873317707827) where you can lookup solutions to typical mapping questions, view how-to guides and setup screenshots, ask questions and report any issues.  You can also report issues on GitHub if you wish.

## General Architecture

![general_architecture](assets/gremlinex_diagram.png)

GremlinEx takes inputs from multiple sources, local and network, performs the transformations and mappings specififed in the profile based on the current profile options, container and action configurations, and sends the output as required.

There should be no expectation that a single input always results in a single output. A single input can produce multiple outputs, and multiple inputs can provide a single output.  It's also possible that no output is produced if the input(s) should be ignored based on the particular context.

## Differences with Joystick Gremlin

GremlinEx started as a fork of the excellent Joystick Gremlin serveral years ago, with the goal of seeing if it could be ported to 64 bit and a more up to date version of Python.

Fast forward to today: GremlinEx (GEX) at this point is not Joystick Gremlin nor a new version of Joystick Gremlin - it's been re-architected and converted, while keeping with the spirit of the original.  While common in origin, GEX is very significantly different internally with a different run engine, multi-threading, new and reworked mapping actions and containers, and core new functionality. GremlinEx may have started as a fork, however in the last several years has evolved to look similar, and functions differently and is now more than hundred thousand line of codes, two hundred if you include comments - I am a firm believer in comments to understand what the code does and perhaps more importantly, why.

GremlinEx is now heavily event driven, uses multi-threading, has networking and support for non-joystick devices, and has many actions, functions and options that do not exist in the original because they evolved differently.  Available [containers are listed here](containers.md#containers) and available mapping [actions are found here](actions.md#actions).

GremlinEx is squarely focused on performance, with most mappings aiming for millisecond processing time, and has many UI features to reduce the UI complexity to help with performance at design time.

GremlinEx is heavily networked: it supports remote control of multiple clients.  It supports network protocols to accept inputs from other devices on the network, and send data to other devices on the network for two-way communication/updates.

GremlinEx even has a KVM mode to completly take over a client for game control purposes.

The internal wiring is completely new, implementing a high performance execution graph runtime engine.

While most Joystick Gremlin profiles should load as-is, some may not depending on the version of the profile and features used, especially if the features were deprecated in GremlinEx and replaced.  This said, simpler profiles should work "as-is".  A lot of care was applied to ensuring older profiles can load "as is" with the necessary conversions happening automatically - however this only goes so far.

Also note that once a profile has been touched by GremlinEx, it may not work at all with any other prior version, including Joystick Gremlin because of changes to the profile file.

GremlinEx also has several UI (user interface) enhancements aimed at improving the understanding of "what is my hardware doing now", for example, visual repeaters on buttons and axes, and automatic input switching for that time when you don't remember what button is what and you need to go to that input fast.

GremlinEx lets you re-order your devices internally so the ones most often used can show up first in the user interface.

GremlinEx is Windows theme aware, so has a dark mode.

GremlinEx has a new sound processing engine, and features to play back audio at different speeds while maintaining the pitch.

GremlinEx has a new API that makes it easier for custom plugins to be written and interface with inputs and outputs.

## Installation

GremlinEx comes as a compressed zip file in the [release section of GitHub](https://github.com/muchimi/JoystickGremlinEx/releases) that contains all you need including required libraries.

The contents of the zip file should be extracted to a folder that is not a protected system folder such as "Program Files" or "Windows".

The recommendation is to install GremlinEx in its own folder, like "GremlinEx" and if you will use multiple versions, it's recommended you also name the folder after the version.  This is automatic if you extract the zip File using tools like 7Zip or Nanazip as the folder will be the same name as the zip file.  This enables you to have multiple versions installed.

The master repository can be found here on GitHub: [https://github.com/muchimi/JoystickGremlinEx
](https://github.com/muchimi/JoystickGremlinEx).

### Test versions

GremlinEx uses an open development philosphy.  As such, test releases are frequently available that introduce not only fixes but desired features as well.  Some of the versions are more robust than others, however test versions are more likely to have issues, especially with new features.

To this end, GremlinEx offers in the configuration an option to "Version" profile folders so that configurations and profiles are safe from mishaps, such as a new profile version making it incompatible with a prior version of GremlinEx.

It is a best practice regardless ot make a copy of the data folder (default is %USERPROFILE%\Joystick Gremlin Ex) to safeguard any files and configurations, just in case.

### Required additional tools

GremlinEx works with a number of tools to function as a device integrator, such as VJOY.   Some tools are mandatory (VJOY), others are not (VIGEM, Bitfocus) but recommended.

Please see the [resources section](resources.md) for a list of required and optional tools.

### Optional WASM module

The Microsoft Flight Simulator SimConnect module in GremlinEx requires the installation of the WASM module in the MSFS community folder.  This module is what provides GremlinEx with the ability to execute calculator code in MSFS and thus read/write variables and simulator controls not otherwise exposed by the SimConnect SDK (as of this writing).

### Running from source

While GremlinEx releases are provided as self-contained Python packages, you can run GremlinEx directly from source code, especially if you would like to contribute or just see how GremlinEx does what it does.  The recommended environment is [Visual Studio Code](https://code.visualstudio.com/).  When running in this mode, it is up to you to setup the environment and pre-requisites manually.  The GremlinEx project on GitHub includes a Python requirements file listing dependencies.  This is an advanced topic and requires a strong familiarity with Python development, working with Python and Python libraries, installing and configuring these environments, interfacing with C++, using the QT graphical environment, and working with low level hardware and network protocols. Also of note is the dependencies will vary with new releases as the project matures.

### OSC configuration

OSC (Open Sound Control) is a very important feature support in GremlinEx that allows it to communicate hardware panels like Elgato Streamdeck via [Bitfocus Companion](https://bitfocus.io/companion).  The feature also provides support for glass surfaces (touch screens) via tools like [Open Stage Control](https://openstagecontrol.ammd.net/).  While supported in the box, it does require some ports to be specified.

For Elgato Stream Deck specifically, GremlinEx also supports a direct [Stream Deck plugin bridge](streamdeck.md) that keeps Stream Deck software running (no Companion required for those keys).

Please see the [OSC configuration section](usage.md#osc-device-open-sound-control) for OSC specific setup to enable this feature.  

### Virus False positives

Unfortunately, some older anti-virus and anti-malware programs may flag GremlinEx (and any Python packaged applications) incorrectly, known as a false-positive.  See more on the topic and options in [this section of the documentation](usage.md#antivirus-false-positives).  It should be noted that most malware and anti-virus tools correctly handle the false-positive.

## Running GremlinEx for the first time

The first time you run GremlinEx, as it is written (mostly) in Python, the Python environment will most likely be running first a first run optimization and cache creation process.  This happens for every new version of GremlinEx, but only the first time a module is used/loaded.  This process is automatic and part of the normal Python environment.  You may thus experience an increase in load times and decrease in performance when first running a new version, especially at design time.  This however should not persist on a restart once the caches are created and the optimization done by the Python environment has completed.  This is less noticeable on systems with very fast storage solutions as Python creates a number of files during this process, however it can still be noticeable.

It is thus recommended to run the software once, and then restart.

## UAC (user access control)

Windows UAC may prevent GremlinEx from starting with Windows (if the option is selected) unless the process is given higher permissions.  Typically this will manifest itself as a load error, DLL not found error or some other I/O error, even if the program runs fine when started normally.  This is not a GremlinEx issue but a UAC security issue.

## Resources and help

![Discord Icon](assets/discord_small.png)&nbsp;Please join our  [GremlinEx Discord](https://discord.gg/pNadcReth9) server!

## History

GremlinEx is based on a fork from the 2019 [Joystick Gremlin by Whitemagic](https://whitemagic.github.io/JoystickGremlin/).  GremlinEx builds on that excellent software and its concepts, and incorporates notable modifications and enhancements:

- x64 bit support and current Python environments/libraries
- remote control of GremlinEx instances
- Built-in state machine with user defined states, including support for boolean state expressions and state triggered mappings
- Built-in support for the [OSC](https://en.wikipedia.org/wiki/Open_Sound_Control) protocol and [MIDI](https://en.wikipedia.org/wiki/MIDI) devices.
- Streamdeck, Loupedeck and other panel two way control.  To simplify and greatly enhance capabilities, highly recommended via [Bitfocus Companion](https://bitfocus.io/companion)) to simplify the setup with GremlinEx
- Support for custom glass surface controller support (touch screen use-case)
- Built in-support for Microsoft Flight Simulator 2020 and 2024 control via the SimConnect SDK including a custom WASM module for calculator expressions and access to custom sim variables
- Advanced containers and actions included.
- High performance runtime execution graph engine (starting with m73)
- Advanced latched keyboard and mouse inputs
- Support for extended keys including F13 to F24 and media keys
- Selectable voice and playback speed for text to speech prompts
- Modern user interface with dark UI theme support

While GremlinEx is based on Joystick Gremlin, it's important to note they are not the same software, certainly not internally, but also from the standpoint of behaviors.  GremlinEx is heavily event based, has a completely different execution engine.  While legacy profiles may load in GremlinEx, complete compatibility is not assured.

GremlinEx makes an attempt to keep with the philosophy and concepts of the original project as much as possible, and I am grateful to WhiteMagic and his excellent work on Joystick Gremlin and for the inspiration. Joystick Gremlin remains one of the best mapping utilities I have ever seen or used in decades of simpit simulation.  The architecture is elegant and served as a launchpad for GremlinEx.

GremlinEx is in active development and thus may include bugs and issues refered to as dragons.  Rather than releasing new features and fixes sporadically, I have adopted an open development model where pre-releases are posted to the dev branch for you to use as the features and fixes are implemented.  Some are more bleeding edge than others.

I am a firm believer that open development outweighs the drawbacks, it encourages feedback and input and participation from the community. I appreciate the patience as not everything will work in every pre-release patch as expected, that is part of the process.
  


