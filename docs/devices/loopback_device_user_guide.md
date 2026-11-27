# Loopback Device — User Guide

Use **Loopback** to pass named axes and buttons between mappings inside a GremlinEx profile. A physical control can write to a Loopback input, and a second mapping can react to it. A joystick condition can also read its current value.

Loopback works without a virtual joystick driver and stays inside GEX. To send a Loopback value to a game, add a mapping from the Loopback input to an output the game can see, such as a vJoy or Maestro controller.

## Contents

- [Open the Loopback tab](#open-the-loopback-tab)
- [Create and name inputs](#create-and-name-inputs)
- [Write to a Loopback input](#write-to-a-loopback-input)
- [Use a Loopback input in a joystick condition](#use-a-loopback-input-in-a-joystick-condition)
- [Monitor Loopback in the Input Viewer](#monitor-loopback-in-the-input-viewer)
- [Set startup values](#set-startup-values)
- [Rename or delete inputs](#rename-or-delete-inputs)
- [Worked examples](#worked-examples)

## Open the Loopback tab

Loopback is enabled by default. Open the **Loopback** device tab in the current profile. If the module is disabled, open **Options → Modules**, enable **Loopback**, and restart GEX. If the tab is still hidden, check the device visibility filter.

## Create and name inputs

1. Click **Add Axis** or **Add Button** in the left pane.
2. Keep the suggested name, such as `axis-1` or `button-1`, or enter a name that describes the input's purpose.
3. Confirm the dialog to create the input. Use **Cancel** to close it without adding anything.

Names must be unique across all Loopback axes and buttons in the profile. Names are case-sensitive, so `Trim` and `trim` are distinct. Loopback has no fixed limit on the number of axes or buttons.

Use **Presets...** to add **4 axes and 16 buttons** or **8 axes and 32 buttons**. Each preset appends controls using the next available generic names. You can apply either preset again to add more controls.

## Write to a Loopback input

1. Select the source control in the profile mode you want to edit.
2. Add **Virtual Remap** to the source input's container.
3. Choose a mapping mode that produces the output you need. For a momentary button, choose the normal button mapping with **Hold** behavior. For a stick or slider, choose an absolute axis mapping.
4. Under **Device**, select **Loopback**. Under **Output**, select the named axis or button.
5. Open the **Loopback** tab, select the same input, and add the actions that should run when its value changes.
6. Save and start the profile. Operate the source control and check that the downstream action responds. For a held button, test both the press and the release.

Loopback inputs keep their current values across mode changes. The actions attached to them follow the profile's active mode. Writing the same value again leaves the input unchanged. Keep mappings flowing from the source through Loopback to the destination. [Virtual Remap User Guide](../actions/map_to_vjoy_user_guide.md)

Open **Input Curve** on a Loopback axis’s toolbar to set its response curve and deadzones for the selected mode. Mappings use the shaped value. Joystick conditions can read it by selecting **Use calibrated input**.

## Use a Loopback input in a joystick condition

1. Open the condition controls for the container or action you want to gate.
2. Add a **Joystick Condition**, choose **Loopback** as the device, and select the named input.
3. For a button, choose **Pressed** or **Released**. For an axis, choose **Inside** or **Outside** and set the range.
4. Start the profile. Set the Loopback input to a value that passes the condition and operate the mapped control. Repeat with a value that fails the condition.

The condition reads the current Loopback value when the mapped input triggers. To run an action when the Loopback value itself changes, attach the action to that input in the **Loopback** tab.

## Monitor Loopback in the Input Viewer

After defining an axis or button, open **Tools → Input Viewer**. Choose the views under **Loopback**, or pick **Loopback** from the virtual-device dropdown and click **Select Virtual Device** to open the current axis and button panels. The axis timeline is available from the Loopback device list. Hover over a button number to see its name.

## Set startup values

Open the profile's **Settings** tab and find **Loopback Startup Values**. This section appears after you create at least one Loopback input.

| Control | Default | How to change it |
| --- | --- | --- |
| Axis | `0.0` (center) | Enter a value from `-1.0` to `+1.0`. |
| Button | Released | Check **Pressed** to start with the button held. |

Save the profile and restart it to test the initial values. A button that starts pressed or an axis that starts off center can trigger its attached mappings at startup.

## Rename or delete inputs

Select an input and click **Rename** to change its name. Mappings and conditions already linked to that input keep their target.

The profile XML gives each Loopback control its own GUID. Loopback input mappings, Virtual Remap targets, and joystick conditions save references to that GUID alongside comments showing the current name. Profiles saved before this change gain GUIDs on their next save.

Click **Delete** on the input’s toolbar to remove that control, or use **Delete All** to remove all Loopback controls. If a control is in use, GEX blocks the deletion and lists its references across the profile's modes. Remove or reassign the listed mappings and conditions, then retry. A new control with the same name is a separate input.

## Worked examples

### Share one command between two buttons

Create a Loopback button named `Radio Menu`. Add a held-button Virtual Remap on each physical button and point both to **Loopback → Radio Menu**. On the Loopback button, add the keyboard action for opening the radio menu. Test each physical button independently. Both use the same downstream action, so you only need to change the keyboard binding in one place.

### Enable a mapping within a lever range

Create a Loopback axis named `Lever Position`. Map the physical lever to it using an absolute axis mapping. On a separate button's action, add a **Joystick Condition** for **Loopback → Lever Position** and set **Inside** to the range `0.5` through `1.0`. Start the profile and press the button with the lever inside and outside the range to check both outcomes.
