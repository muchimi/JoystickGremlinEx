# Testing GEX Maestro support preparation

Those of you interested in testing the Maestro bridge, here's some prep info.

## Preamble

### What is HID Maestro

I'll paraphrase here because the details are on the project's home page.

HID Maestro is a virtual device driver that runs in user mode, and lets you create any HID input device without a kernel mode signed driver. GEX focuses on joysticks and gamepads in this case as a replacement to VJOY/VIGEM.  The clear advantage here is that it only needs elevated privileges to run, and installs no hardware drivers in kernel mode.  VJOY and VIGEM are no longer actively supported, one reason is the high cost of a kernel mode driver certificate which is unaffordable in the context of an open source project, and with the updated requirements, significantly more expensive than a development certificate.

### Why does it matter

It matters to GEX because at this point, VJOY and VIGEM are officially no longer supported by their initial developer. Both managed to survive the Windows 11 security requirements by having a brave soul sign the drivers and make them work under Windows 11.  The drop in support however means that bug fixes and new features are not in the cards, and that's primarily related to the new requirement to obtain a driver signing certificate, which is prohibitively expensive, and out of reach of open source software projects unless you have access to one.

HID Maestro does away with this requirement because it uses a different approach to virtual drivers in Windows that run in user-mode instead of kernel-mode, so the only requirement is elevated priviledges, not a very expensive signed certificate.  HID Maestro is also actively supported, although it is not specific to joysticks or gamepads.

### Two problems for GEX

The first problem is HID Maestro is written in C# and is thus dependent on the .NET platform.  This platform is a challenge for GEX because the Python/C++ environment GEX is built upon does not easily integrate with .NET. There are integration mechanisms, such as the excellent [PythonNet](https://pythonnet.github.io/).  However testing earlier this year showed that this route is not practical: CPU/Memory utilization was terrible (by GEX norms) and latency was also a disaster due to the translation overhead.  GEX must maintain low latency to keep mappings responsive.

The second problem is that HID Maestro and VJOY/VIGEM cannot co-exist on the same system. During testing, it was discovered that HID Maestro is destructive to VJOY (joystick) and VIGEM (gamepad) - it breaks both and is not easy to recover from short of a complete re-install/reconfig.  This presents a testing challenge.


		**If you install HID Maestro it will break your VJOY / VIGEM configuration**

### The solution to the first problem

GEX resolves the first problem by introducing a low latency bridge component written in C#.

The bridge component performs these duties:

- written entirely in C# for .NET 10 64 bit, so compatible with HID Maestro's API
- standalone distribution/project and installer.
- builds on GEX's support for low latency UDP binary OSC protocol - this gives GEX and the GEX bridge high speed, low overhead two way communication for complex commands and parameters.  This has a side effect of also being compatible with any OSC compatible application.
- contains the HID Maestro engine and translates GEX OSC commands to integrate with HID Maestro's API.  No separate install needed.
- lets GEX add, remove, read or write to virtual joystick and gamepad devices using the existing vjoy remap action.
- runs locally as a Windows service to start/stop automatically with Windows, or runs as a console application (manual start/diagnostics).
- supports all the features VJOY and VIGEM provide, and in particular solves the VJOY naming issues.
- adds XINPUT support to GEX
- Games can't tell the difference - they see joysticks or gamepads
- Entirely compatible with HID HIDE.


### No current practical solution to the second problem

At present, it is not feasible to use VJOY/VIGEM and HID Maestro on the same machine.

This said, as we covered earlier, VJOY and VIGEM days are numbered, so this provides an alternative solution and is thus not necessarily a bad thing as we look to the future:

- VJOY and VIGEM are no longer supported and it is not known if they will work in a future version of Windows.
- HID Maestro does not require the installation of a kernel mode driver so is easier to install and configure
- GEX can write to Maestro gamepad devices like a joystick, meaning that no custom actions are needed on the GEX side (no need for map to gamepad) - use the VJOY remap
- GEX is setup to failover existing VJOY outputs to compatible joystick devices GEX creates with no change to older profiles needed.


The drawbacks:

- Testing is difficult because of the conflict with VJOY/VIGEM and no easy way to walk that back.


### Testing environment


As this is a destructive test, in that HID Maestro will break VJOY and VIGEM, it is not the time to test this on your "production" gaming box.

The best environment to try this out is either in a VM or a separate machine.  For the VM, you will need a setup that lets the guest OS see your host's hardware controllers.



## Installation process

The installation will involve a pair of installs. I am working on making this as simple as possible by using traditional installers (in addition to the more manual portable install archive method).

Please note that the GEX support for the GEX Bridge module and Maestro is only available with the most current test releases of m77.

### GEX Installer (new as of m77T93)

The new installer provides uninstall data to Windows, supports versioning during install, and importantly, check your system for what is installed.  This then offers up optional installations (via their own installers) for HID Hide and the GEX Bridge.

The [GEX installer can be found here](https://github.com/muchimi/JoystickGremlinEx/releases/tag/m77_series).

### GEX Bridge Installer (new as of m77T92)

The setup program will install the GEX bridge module which encapsulates the HID Maestro functionality and enables GEX (as well as other apps) to manage HID Maestro devices.  This includes all you need.

The [GEX Bridge project is found here](https://github.com/muchimi/GEXMaestroBridgeService).

## Setup

The bridge module, because it is using the OSC protocol, works local or networked.  If networked, the firewall must be configured to allow traffic on the inbound port.

The default configuration is GEX and the GEX Bridge Service installed on the same instances.  This does not require firewall configurations.  The bridge service normally runs as a service, but can also run as a console app for diagnotics purposes (not at the same time the service is running, obviously).

### Virtual machines

Any VM can be used to test this is a physical machine is not available. Using and configuring a VM is outside of the scope of this project.  A VM that supports USB controller pass-through is suggested (like HyperV in Enhanced Session mode, which also requires the guest operating system to support this).

### IP/Ports

Two UDP ports are used, and can be configured.  The default is 8010 (send from GEX) and 8011 (send from bridge).  This can be changed but must match.

When configuring ports, the IP addresses must typically be configured but only if GEX and the bridge are on different machines.

### Testing scenario A: two separate machines

If the bridge module runs on a separate machine (such a a VM), you can keep GEX running local and still manage Maestro devices by providing the port/IP address where the bridge is running, and conversely, the bridge must know where to send the response data to, that would be the port/IP of the GEX machine.

This method has the advantage of not touching your VJOY/VIGEM setup on the GEX machine, while still being able to test the Maestro devices on the other (remote) machine.

### Testing scenario B: single machine

In this scenario, a fresh install of GEX and the GEX bridge on one machine is used, with all defaults.

This method may be problematic in a VM environment as input controllers may not be visible to the guest operating system.

If on a physical machine, connect at least one input controller to that system.

## Limitations

- You can only create up to four gamepads - that is an XINPUT limit, not a GEX limit.
- Gamepads will be named gex-gp-n where n is 1 to 4.  This is true of any gamepad profile used to create the gamepad.
- You **will break your VJOY/VIGEM setup if you run the bridge on the same machine where VJOY/VIGEM is installed**.  Recovery is not simple (recommend path - save the operating system snapshot as you would before a major Windows patch install).
- VJOY as input is not supported in a Maestro setup currently (although you can use a Maestro device as input outside fo the vjoy as input mechanism).
- This is a test. Things may break as this is an experimental feature and needs more testing.

## Recommendations

Based on internal testing, what I would recommend:

- use a VM or a separate machine for testing so as to not break your production machine.  The guest VM will ideally have visibility on your host connected USB controllers.
- Manage Maestro device from the Tools menu, Maestro Devices... dialog.
- GEX should automatically failover your VJOY devices as configured in a profile, so, in theory, should work as-is.  The failover creates "fake" VJOY devices so the profile is not confused but maps them to the Maestro devices at runtime if the VJOY ID matches the name of the Maestro device.   The mapping table is

	`vjoy 1 -> gex-1`

	`vjoy 2 -> gex-2`

	`...`

	`vjoy n -> gex-n`

The list of vjoy devices is based on the profile data.


- Use the default devices in the presets GEX creates for you.  The names matter for the failover to correctly function, as otherwise GEX has no way of knowing what to map to automatically.

- New profile can use the Maestro device directly, it will populate in the device selection drop down in vjoy remap.


## Question and Answers

### VJOY is broken!!!

Yes, if you run HID Maestro on the same machine you have VJOY installed, VJOY will be broken, you were warned multiple times.  They conflict at the driver level and there is no current workaround.

### Any functionality differences?

The goal is none.  GEX should work exactly the same with Maestro, at the same performance level.

### Should I use separate machines?

For testing, you want to use a separate machine for the GEX bridge testing.  For production, you can run both on the same machine.

### HID Hide concerns?

None. The devices created by the GEX Bridge should remain white listed in HID Hide to be visible to the game.

HID Hide may need to be reconfigured if you are using white listing (hide all except white listed mode).

### What about non joysticks or gamepads?

Keyboard and mouse, and remote control are not impacted.

### Game concerns?

Games will see GEX Bridge devices (gex-1, gex-2, gex-gp-1, etc...) in the order created and this order should persist between sessions because Maestro devices are deterministic (unlike kernel mode USB devices).

Your game should see the devices as normal joysticks or gamepads. Gamepads use XINPUT and DINPUT as far as the game goes so should be visible as either device.

The default joysticks created by GEX are all max DINPUT spec - so 8 axes, 128 buttons and 4 hats.  That should not confuse the games (as they should, after all, use the same DINPUT specification from Microsoft).

Reminder that the max number of gamepads is 4, which is a XINPUT specification, and most game controllers cannot have more than 32 buttons.  Gamepads are emulated so they will show as the "real" thing to the game.

### What about performance?

The bridge communication layer adds very little overhead.  Latency was measured to be under 2 milliseconds or much less.  Data read/writes are faster at profile run time.  UI mode involves additional data transfers between the two modules.  No practical impact to using the GEX Bridge vs VJOY as the overhead to talk to the VJOY API is similar.


### Do I need to install any special software?

No.  All you need is included in the distribution files (installer or portable archive ZIP format), with optional components available from the new GEX installation program that will download from the project sources.

The GEX bridge includes all the necessary files and includes the HID Maestro engine, and will prompt you for the configuration.

The HID Hide software is recommended to hide devices from a game to avoid mapping challenges

Additional software is needed to setup the development environment, including Visual Studio Code with the Python extensions such a Pylance and Ruff, Python 3.14 and dependencies listed in requirements.txt, and Visual Studio 2026 Community Edition configured for .NET and C# development for the bridge module with the .NET.

### What if I need help?

The [Discord testing channel](https://discord.com/channels/1279461873317707827/1341211588404842547) is where you get help faster as it's actively monitored. If you cannot access the link, please sign up for our Discord server first.

### Licensing

All included items are open source, or from open source repositories/projects.  All are either through GPL3 or MIT or similar open source, non commercial licenses. Check the licenses folder for relevant licensing information.

Usage is subject the terms of these licenses that you agree to by installing or using the software.




