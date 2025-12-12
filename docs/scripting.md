# Advanced Scripting

Scripting in GremlinEx (GEX) requires at least a basic understanding of Python programming and the Python language.  As such is is an advanced feature.


## Plugins

Plugins are the core of the GEX extensible architecture.  Plugins are written in Python and will be loaded and executed by the GEX runtime.
When GEX runs, it will scan specific folders for plugins and make them available to a profile.

There are three plugin types supported:

- Container plugin - a plugin that contains actions.  GEX comes with a set of delivered container plugins.
- Action plugin - a plugin that defines mapping functionality, such as keyboard, mouse, map to vjoy, etc...   GEX comes with a set of delivered actions.
- User plugins - a plugin that is neither a container or an action, but allows easy programmatic extension of GEX using decorations to easily hook inputs and modes.

## When to use a user plugin

A user plugin is typically for:

- to add very specialized behaviors not otherwise available via delivered containers and actions for which a general action/container does not exist
- to easily solve complex logic issues that are more difficult or inefficient or impractical in delivered containers/actions/conditions : if you need to use a lot of conditions and modes - you may want to consider a user plugin instead.
- to access the full functionality of the Python libraries driven by GEX input triggers


## Requirements

Plugins should be written for the same version of Python and dependent libraries used by GEX.  GEX will load these modules at runtime.  As of this writing, GEX runs in Python 3.13.x, so you would, for example, not be able to use Python 3.14.x specific features in a user plugin.

Visual Studio Code with the Python extensions is the recommended development environment for user plugins.   You can debug user plugins by running GEX in script mode from source and it will work with breakpoints and the debugger.  This will require the setup of the supporting GEX libraries and dependencies if you intend to debug/trace through your plugin as described in the [resources guide](resources.md#required-modules).

For simple editing, any text editor will work, however VSCode is recommended for Python editing as it's what GEX uses and is setup for.

Plugins will also need to handle external dependencies that are not part of the GEX distribution with care, as GEX will not include them in the packaged version.  How to accomplish this is beyond the scope of this document as it would require re-packaging GEX and is only for developers/modders.

Is is recommended to stay away from UI elements in a user plugin but it is completely possible to leverage the QT library inside a user plugin.  A user interface for a plugin is a very advanced feature and at this point, you are most likely considering a custom action or container plugin rather than a user plugin.  If this is the case, the source code for actions/containers should be examined as they require a very specific structure to be loaded and executed.

## Load behavior

A user plugin is loaded whenever a profile starts.  This will identify any exceptions/errors in the plugin when the profile starts.  

![warning](assets/warning.png) Imported Python packages by a user plugin, including for example another python source file, once imported will not get re-imported again because of the way the Python importer and package resolver works.  This is not a GEX limitation - it is a behavior of the Python interpreter.  To reload an imported package, GEX needs to exit and restart, and run a profile once to load the plugin with the import reference.


## General structure of a plugin

A user plugin is, and should be, in most cases, a single python (.py) file. 

There are use-cases if you have multiple plugins to have for example a configuration file containing data for your devices that are shared by multiple plugins to avoid repeating the information in every file.

## Plugin file location

The .py file for your plugin should be in the same folder containing the profile.

## Attaching a plugin to a profile

Plugins are attached to a profile on a per profile basis.  This is done via the Plugins tab in the device list in GEX.  Usually the Plugins tab is the very last tab.
As with modes, the plugins tab may not be available until if the profile is saved.  This is because, as with modes, the data is stored in the profile file itself so the file must exist.

### Sample code

The top of the file should reference GEX components that will be used by the plugin.  The usual suspects includes macros.

```python
from __future__ import annotations
from gremlin.macro import Macro, MacroManager # import macro functionality for key output 

```




GEX user plugins use decorators to "hool" GEX inputs easily.  A python decorator starts with the @ sign and adds the required behind the scenes functionality to register a particular method to a GEX input.  When GEX triggers the input, the method in the plugin will be executed.

To facilitate this, GEX has a decorator factory that easily lets you create the required decorators for your input devices.

The recommended method is to define constants corresponding to your hardware name and globally unique identifier (GUID) as text strings:

```python

VPC_LEFT_NAME = "LEFT VPC Stick WarBRD"
VPC_LEFT_GUID = "{DD8C51A0-6B27-11EC-800B-444553540000}"
VPC_RIGHT_NAME = "RIGHT VPC Stick WarBRD"
VPC_RIGHT_GUID = "{6AD0CFE0-6B2E-11EC-800D-444553540000}"
```

These define two joysticks.  The names and GUIDs will be different for your system (more on this in a bit):

It is also helpful to define the modes in your profile as constants, so that it becomes easy to create the necessary decorators for each mode.

```python
MODE_DEFAULT = "Default"

MODE_FLIGHT = "Flight"
```

You can then create decorators for these two devices.  A decorator should be created for each device, and each mode (if the mode is used).

```python
right_vpc = gremlin.input_devices.JoystickDecorator( VPC_RIGHT_NAME, VPC_RIGHT_GUID, MODE_DEFAULT ) # decorator for the right stick, default mode
left_vpc = gremlin.input_devices.JoystickDecorator( VPC_LEFT_NAME, VPC_LEFT_GUID, MODE_DEFAULT ) # decorator for the left stick, default mode
right_vpc_flight = gremlin.input_devices.JoystickDecorator( VPC_RIGHT_NAME, VPC_RIGHT_GUID, MODE_FLIGHT ) # decorateor for the right stick, flight mode
left_vpc_flight = gremlin.input_devices.JoystickDecorator( VPC_LEFT_NAME, VPC_LEFT_GUID, MODE_FLIGHT ) # decorator for the left stick, flight mode

```

The plugin should include any code necessary to define specific uses.  For example, a macro can be defined as follows:

```python

''' macro member functions "add" a macro step - multiple calls add a step to the macro
    press(key) # issue a key make (press) - presses a key down until it's released
    release(key) # issue a key break (release) - releases a key if it was pressed 
    tap(key) # press/release a key with the default delay (250ms)
    pause(seconds) # pause between steps

    For keys, they can be a text string by name, or they can be a gremlin.keyboard.Key object.  Supported keys are all listed in gremlin.keymap.  Special keys are listed in _g_name_map.
    Normal keys are the normal keys like "A" to "Z" and "0" to "9".  
    Note that keys are mapped as scan codes, and are mapped currently to US QUERTY layouts.  Internally named keys get mapped to the corresponding scan code and extended flag.

    Keys can also be defined as my_key = gremlin.keyboard.Key(scancode = , is_extended = ) to use scan codes and flags directly.

'''

cruise_toggle_macro = Macro() # define a macro that taps the "C" key on the keyboard whenever triggered
cruise_toggle_macro.tap("C")

```

You can then attach methods to each device as follows:

```python
@left_vpc.axis(3) # hook left stick axis 3 (axes are base 1, so are 1 to 8 - not that some devices don't have 8 axes and may skip them, so it could be 1,2,3,5,8 - they are not necessarily in sequence as defined by the device )
def positive_only(event, vjoy):
    """
    :param event: the event data for the trigger - see gremlin.event_handler.Event() for the definition of that object
    :param vjoy: the vjoy proxy object - provides access to output vjoy axis, buttons and hats
    """
    vjoy[1].axis(1).value = abs(event.value) # assign vjoy device 1, axis 1 the absolute value of the input device - in this case - the left stick in default mode


@right_vpc_flight.axis(2)
def negative_only(event, vjoy):
    """
    :param event: the event data for the trigger - see gremlin.event_handler.Event() for the definition of that object
    :param vjoy: the vjoy proxy object - provides access to output vjoy axis, buttons and hats
    """
    vjoy[1].axis(1).value = -abs(event.value) # assign vjoy device 1, axis 1 the negative absolute value of the input device - in this case - the left stick in flight mode



@left_vpc.button(1) # hook left stick button 1 (1 based to 128 if supported)
def cruise_toggle(event, vjoy):
    """
    :param event: the event data for the trigger - see gremlin.event_handler.Event() for the definition of that object
    :param vjoy: the vjoy proxy object - provides access to output vjoy axis, buttons and hats
    """
    MacroManager().queue_macro(cruise_toggle_macro) # run the cruise toggle macro define dabove
        

```


## Generating Python device headers


For convenience, GEX can automatically generate the relevant Python constants and variables needed to hook devices.
GEX will generate this for your complete device list.  This is done from the Device Information window in the tools menu.  
The 'Generate plugin script header' button will place the relevant Python code into the clipboard that can be pasted into the plugin.  This will contain all required definitions and GUIDs.

