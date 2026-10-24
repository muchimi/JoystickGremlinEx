# Gated Axis — User Guide

**Gated Axis** divides an axis into boundaries called **gates** and the **ranges** between them. Each gate or range can contain its own action containers. Use it to send commands when a throttle crosses a detent, hold a button while a lever is in a zone, or remap part of an axis to a different output span.

Gated Axis decides **when** nested actions run and **which axis value** they receive. The nested actions—such as Map to vJoy or Keyboard Ex—produce the actual output. Adding gates without adding actions does not create an output mapping by itself.

This guide is based on the supplied action and the available supporting gate-handler implementation. Shared action/container controls may differ between builds.

## Contents

- [Gated Axis — User Guide](#gated-axis--user-guide)
  - [Contents](#contents)
  - [Before you start](#before-you-start)
  - [Understand gates and ranges](#understand-gates-and-ranges)
    - [Gates are positions; ranges are intervals](#gates-are-positions-ranges-are-intervals)
    - [Normalized values and direction](#normalized-values-and-direction)
    - [A range condition and an output mode are different](#a-range-condition-and-an-output-mode-are-different)
  - [Create your first mapping](#create-your-first-mapping)
  - [Add and position gates](#add-and-position-gates)
    - [Add a gate at the physical control position](#add-a-gate-at-the-physical-control-position)
    - [Add a gate at a chosen slider position](#add-a-gate-at-a-chosen-slider-position)
    - [Move a gate](#move-a-gate)
    - [Set the gate count](#set-the-gate-count)
    - [Normalize positions](#normalize-positions)
    - [Display Mode](#display-mode)
  - [Configure gate-crossing actions](#configure-gate-crossing-actions)
  - [Configure range actions](#configure-range-actions)
    - [In Range: continuous value mapping](#in-range-continuous-value-mapping)
    - [Enter Range and Exit Range: one-shot events](#enter-range-and-exit-range-one-shot-events)
    - [Range Hold: matched press and release](#range-hold-matched-press-and-release)
    - [Outside of Range](#outside-of-range)
  - [Choose a range output mode](#choose-a-range-output-mode)
    - [Normal versus rebased values](#normal-versus-rebased-values)
    - [Ranged scaling](#ranged-scaling)
    - [Fixed output](#fixed-output)
    - [Filtered output](#filtered-output)
  - [Configure releases and trigger timing](#configure-releases-and-trigger-timing)
  - [Monitor and test events](#monitor-and-test-events)
    - [Recommended test sequence](#recommended-test-sequence)
  - [Startup and runtime behavior](#startup-and-runtime-behavior)
  - [Worked examples](#worked-examples)
    - [Hold a virtual button above a throttle detent](#hold-a-virtual-button-above-a-throttle-detent)
    - [Send different shortcuts across a detent](#send-different-shortcuts-across-a-detent)
    - [Use the upper half of an axis for a full virtual-axis span](#use-the-upper-half-of-an-axis-for-a-full-virtual-axis-span)
    - [Select discrete axis presets with lever zones](#select-discrete-axis-presets-with-lever-zones)
  - [Edit an existing layout safely](#edit-an-existing-layout-safely)
  - [Troubleshooting](#troubleshooting)

## Before you start

Select an **axis input** in the profile and decide what should happen at each position. The action declares support for joystick-axis inputs; it is not a button or hat mapper.

Have the required output available before adding nested mappings:

- For a virtual joystick output, know the destination device and axis or button.
- For a keyboard command, know the shortcut the target application expects.
- For a held output, decide what will release it.

Start with one interior gate and one simple action. Test that configuration before adding more boundaries or output behaviors.

Finalize the general gate layout before configuring many nested actions. Deleting gates or reducing the gate count can remove mappings from those gates and their adjacent ranges.

## Understand gates and ranges

### Gates are positions; ranges are intervals

A gate is a particular axis value. A range is the interval between two neighboring gates.

For example:

| Gate | Position |
| --- | --- |
| Low boundary | `-1.0` |
| Detent | `0.60` |
| High boundary | `+1.0` |

These three gates define two ranges:

| Range | Bounds | Possible use |
| --- | --- | --- |
| Lower range | `-1.0` to `0.60` | Normal throttle travel |
| Upper range | `0.60` to `+1.0` | Boost or afterburner zone |

Choose a **gate condition** when movement across a position should trigger a command. Choose a **range condition** when the position within an interval should control behavior.

### Normalized values and direction

The underlying axis values use `-1.0` to `+1.0`:

- `-1.0`: low end.
- `0.0`: center.
- `+1.0`: high end.

An **increasing** crossing moves from a lower value to a higher value. A **decreasing** crossing moves from a higher value to a lower value. These describe numeric direction, not necessarily the physical forward/backward direction of your lever.

Move the control and watch its marker before assigning increasing/decreasing commands. Account for the axis processing in the profile rather than assuming a particular physical orientation.

### A range condition and an output mode are different

The **condition tab** determines when its nested actions run. The range's **Output Mode** determines how its continuous axis value is transformed.

For example, **In Range** with **Rebased to [-1,1]** sends a remapped axis value to its nested axis action. **Range Hold** instead supplies press/release events suitable for holding a virtual button or keyboard key.

## Create your first mapping

This example sends a command when an axis crosses a detent in the increasing direction.

1. Select the source axis in the desired profile mode.
2. Add **Gated Axis** to its action container.
3. Move the physical control to the desired detent position.
4. Select **Add** to create a gate at the live marker position.
5. Double-click that gate's handle, or right-click it and select **Configure...**.
6. In the gate configuration dialog, select **Condition: Cross (inc)**.
7. Add a container and the required output action inside that tab.
8. Configure the nested action's output. For example, use Keyboard Ex in Pulse mode to send a short command.
9. Close the configuration dialog and save the profile.
10. Move across the gate in both directions while observing the event display.
11. Start the profile and confirm that the target application receives the intended command.

The increasing condition should respond when the axis crosses from below the gate to above it. Moving back uses the decreasing direction, which can have a different mapping.

## Add and position gates

### Add a gate at the physical control position

Move the axis until the live marker is at the desired position, then select **Add**. This is useful for matching a physical detent.

### Add a gate at a chosen slider position

Right-click the range on the slider and select **Add Gate...**. The new gate is added at the clicked position.

Duplicate positions are rejected or marked as conflicts. Keep neighboring gates separated so each range has usable width.

### Move a gate

Drag its slider handle or edit its value in the gate row. The gate row also provides a grab control for capturing the current source position.

After repositioning a gate, verify both adjacent ranges. Changing a boundary changes which physical positions belong to each range.

### Set the gate count

Enter the required total in **Set gate count**, then select **Set**.

- The editor supports at least **2** gates and a maximum of **20** in the current implementation.
- The count includes the low and high boundary gates. Three ordered gates normally define two adjacent ranges.
- Reducing the count prompts for confirmation because it can remove gate configurations and normalize positions.

Use the actual range rows shown by the editor to confirm the resulting layout.

### Normalize positions

| Control | Effect |
| --- | --- |
| Normalize | Spaces gates evenly over the existing outer-gate range. |
| Normalize (reset) | Uses the full axis range and spaces gates evenly across it. |

Normalization changes gate positions. Do it before tuning detents to a particular physical device, or recheck those positions afterward.

### Display Mode

The standard action widget offers **Normal** and **Percent** displays. The shared widget can also expose other labels when embedded elsewhere.

Display Mode controls the representation of values. It is separate from the range Output Mode and does not, by itself, select an output mapping or change its behavior. Examples in this guide use normalized values to avoid ambiguity.

## Configure gate-crossing actions

Open a gate through its configuration control, by double-clicking its slider handle, or through the right-click **Configure...** command.

Use **Gate Description** to give it a meaningful name, such as “Idle detent” or “Boost threshold.” Add containers/actions separately on the condition tabs you need.

| Gate condition | When it triggers | Example |
| --- | --- | --- |
| Crossed | The axis crosses the gate in either direction. | A notification at a detent. |
| Cross (inc) | The axis crosses from a lower value toward a higher value. | Enable a function above a threshold. |
| Cross (dec) | The axis crosses from a higher value toward a lower value. | Disable a function on the return movement. |

A crossing is an event, not a held state. Remaining on one side of a gate does not create repeated crossing events unless the axis crosses it again.

Do not put the same one-shot command on both Crossed and Cross (inc) unless you want both mappings to run on an increasing crossing. Each tab has its own mapping.

For a momentary output from a crossing, choose either a nested action that handles its own timed release or configure the gate's **Autorelease** behavior. See [Configure releases and trigger timing](#configure-releases-and-trigger-timing).

## Configure range actions

Double-click the space between gate handles, use a range's configuration control, or right-click the range and select **Configure...**.

Set a **Range Description**, then choose the relevant condition tab.

| Range condition | Meaning | Suitable use |
| --- | --- | --- |
| In Range | Supplies axis-value updates while the source is inside the interval. | Drive a virtual axis using this part of the input travel. |
| Enter Range | Generates an activation when the source enters the interval. | Send a one-shot command on entry. |
| Exit Range | Generates an activation when the source leaves the interval. | Send a one-shot command on exit. |
| Range Hold | Press on entry; release on exit. | Hold a virtual button or keyboard command while in the zone. |
| Outside of Range | Processes updates while the source is outside this interval. | Specialized outside-state behavior. |

### In Range: continuous value mapping

Use this tab when the nested action needs an axis value. Its **Output Mode** controls whether that value is unchanged, scaled, fixed, rebased, or filtered.

Add an axis-capable action, such as Map to vJoy configured for an axis destination. Set the destination inside that nested action; defining the range alone does not choose an output device.

In Range responds to incoming value changes. It is not a periodic timer that repeatedly runs a command while the axis is stationary.

### Enter Range and Exit Range: one-shot events

Both conditions produce activation events. **Exit Range is not a key-up event for an Enter Range action.** It is a separate condition with its own mappings.

For example, put a Keyboard Ex Pulse action on Enter Range to send one shortcut, and a different Pulse action on Exit Range to send another.

If you want a single output held throughout the interval, use Range Hold instead of trying to pair unrelated entry and exit containers.

### Range Hold: matched press and release

Use Range Hold with an output action that follows button state:

1. Select **Condition: Range Hold**.
2. Add a container and a button-capable output action.
3. For a virtual button, configure a normal hold mapping to the destination button.
4. For a keyboard key, configure Keyboard Ex in **Hold** mode.
5. Move into and out of the interval and verify both output states.

This condition supplies the natural release when the axis leaves. It does not need a timed release to simulate the end of a crossing pulse.

### Outside of Range

This condition can process many input updates while the axis remains outside the interval. It is not equivalent to “fire once when exiting.” Use Exit Range for a one-shot exit command.

In the reviewed handler, Outside of Range events carry a released/false button state, and the editor exposes a button-type mapping on this tab. Check the nested action's execution settings; a press-only mapping may not react. Use Range Hold for the common “on inside, off outside” requirement.

## Choose a range output mode

The following settings are available on a range's **In Range** tab.

| Output Mode | Value sent to nested axis actions |
| --- | --- |
| Normal | The input axis value, unchanged. |
| Output Fixed Value | The configured Fixed Value while inside the interval. |
| Ranged | The position within this interval, scaled to Range Min and Range Max. |
| Filtered (no output) | Suppresses the regular in-range axis-value output. |
| Rebased to [-1,1] | Maps this interval's low boundary to `-1.0` and high boundary to `+1.0`. |

### Normal versus rebased values

Suppose a range runs from `0.60` to `1.00`:

| Source position | Normal output | Rebased output |
| --- | --- | --- |
| `0.60` | `0.60` | `-1.00` |
| `0.80` | `0.80` | `0.00` |
| `1.00` | `1.00` | `+1.00` |

Use Normal to preserve the source's position. Use Rebased when a small part of the physical travel should operate a complete virtual-axis span.

### Ranged scaling

Select **Ranged**, then enter **Range Min** and **Range Max** under **Scaling options**.

For a physical interval of `0.60` to `1.00`, output limits of `0.00` and `1.00` produce:

| Source position | Ranged output |
| --- | --- |
| `0.60` | `0.00` |
| `0.80` | `0.50` |
| `1.00` | `1.00` |

The range dialog's **Reset** restores its scaling limits to that interval's input bounds. It does not necessarily select `-1.0` to `+1.0`. Choose Rebased or explicitly enter full-span limits when that is what you want.

### Fixed output

Select **Output Fixed Value** and enter the required value. This is useful for mapping a lever position zone to a discrete axis setting, such as a flap preset.

The value is an output to nested actions; it does not physically lock the source control. Outside the zone, another mapping must define any subsequent output you require.

### Filtered output

Use **Filtered (no output)** when this range should not pass its normal axis-value stream to nested actions.

Filtering is not a command to set an output to zero or release a key. The destination can retain its previous value. Gate crossings and other configured range conditions are separate from the continuous axis-value output, so review those tabs as well.

## Configure releases and trigger timing

Gate-crossing tabs and range Enter/Exit tabs expose **Autorelease**. The configuration dialog also has **Trigger Delay**, in milliseconds.

With Autorelease enabled, a trigger is followed by a release after the delay. This lets a crossing or entry event behave like a short button press for a nested action that expects a down/up pair.

Trigger Delay is **not** a dwell time, gate-crossing sensitivity, or noise filter. It does not require the axis to stay beyond a gate before activating the command.

Choose the release strategy that matches the task:

| Task | Suggested setup |
| --- | --- |
| Hold a button while in a zone | Range Hold plus a nested hold-style output. |
| Brief key command at a crossing | Gate condition plus Keyboard Ex Pulse. |
| Make a crossing resemble a momentary button | Gate condition with Autorelease, plus an action that follows the generated button state. |
| Separate commands on entering and leaving | Different one-shot actions on Enter Range and Exit Range. |

If a nested action has its own pulse duration, distinguish that duration from Gated Axis Trigger Delay. Adding two independent release mechanisms can make diagnosis harder; begin with the one your output actually needs.

## Monitor and test events

Enable **Show events** to display **Range events** and **Gate events**. Use the event-type checkboxes to reduce clutter:

- **All** selects every event type for display.
- **None** hides all event types from these lists.
- Individual checkboxes select the displayed categories.

These are **display filters**. They do not disable the action mappings. Likewise, hiding Show events does not turn off the Gated Axis action.

The reviewed handler keeps a short rolling history of the latest events rather than a permanent event log. These display histories are populated for editor-time diagnostics; do not assume they are a complete runtime execution trace.

### Recommended test sequence

1. With the profile stopped, move the axis slowly through every range.
2. Cross each configured gate in the increasing direction.
3. Cross it again in the decreasing direction.
4. Pause on each side and watch for unexpected repeated crossings.
5. Test the low and high ends and positions close to each boundary.
6. Start the profile and verify the actual virtual/key output.
7. Test a fast sweep, startup at several positions, and relevant runtime-mode changes.

An event appearing in the editor confirms trigger detection. It does not, by itself, prove that the nested action has a valid destination or that the target application accepts its output.

## Startup and runtime behavior

After profile startup, the action reads the current axis position and sends an initialization event to the gate handler. You do not necessarily have to move the control before range-related actions become active.

The reviewed handler's first evaluation can initialize:

- Enter Range and Range Hold for ranges containing the current value.
- Exit Range and outside-state behavior for other ranges.

Consequently, a one-shot mapped to Enter Range or Exit Range can run at startup without a physical crossing. Test startup separately, particularly when those commands have lasting effects. Do not assume “Exit Range” always proves the axis previously occupied that range during the current run.

Unchanged axis values are skipped by the trigger processor. Normal axis updates drive the evaluation; Gated Axis is not a repeating command timer.

A fast change can cross several gates between samples and produce several crossing events. Do not depend on their delivery order for a tightly timed command sequence. Configure a sequence action if strict ordering is required.

The action participates in profile-mode handling. If behavior changes after a mode switch, verify the active mode, its inherited mappings, and the nested action's conditions.

## Worked examples

### Hold a virtual button above a throttle detent

1. Add an interior gate at `0.80`.
2. Open the upper range, `0.80` to `1.00`.
3. Select **Condition: Range Hold**.
4. Add Map to vJoy with a normal button-hold mapping to the required destination button.
5. Save, start the profile, and move across the detent in both directions.

Expected result: the virtual button is on while the throttle is in the upper zone and off after it leaves. Verify the exact boundary and startup position on your device.

### Send different shortcuts across a detent

1. Add a gate at the desired threshold, such as `0.50`.
2. Open **Condition: Cross (inc)** and add Keyboard Ex Pulse with the command for increasing travel.
3. Open **Condition: Cross (dec)** and add a second Pulse action with the command for decreasing travel.
4. Leave Crossed empty unless a separate both-directions command is also required.
5. Test the actual command sent in each direction.

Use the condition-tab names and the direction of the live axis value when testing. The event history has a direction-label issue in the reviewed handler; see the version notes below.

### Use the upper half of an axis for a full virtual-axis span

1. Create gates at `-1.0`, `0.0`, and `1.0`.
2. Open the upper range's **In Range** tab.
3. Select **Rebased to [-1,1]**.
4. Add Map to vJoy in Absolute axis mode and choose the destination axis.
5. Move from just above `0.0` to `1.0` and verify full virtual travel.

Normal output on that interval would use only `0.0` to `1.0`; rebasing expands the interval to the full normalized span. Configure the lower range separately. If it is filtered, the destination may retain its last value while the source is there.

### Select discrete axis presets with lever zones

1. Add gates to divide the travel into the desired zones.
2. On each range's **In Range** tab, select **Output Fixed Value**.
3. Enter a different output value for each zone, such as `-1.0`, `0.0`, and `+1.0` for three zones.
4. Add a Map to vJoy axis action in each zone, all targeting the intended axis.
5. Check each zone and start the profile with the lever in different positions.

Expected result: the virtual axis receives the configured preset for the occupied zone. Use descriptions to keep the zones recognizable after editing.

## Edit an existing layout safely

Before deleting or substantially repositioning gates, save the profile and preserve important mappings using the application's duplication, template, or clipboard features where available.

To delete a gate, right-click its handle and select **Delete Gate**, or use the gate-row delete control. The editor prevents deletion below two gates and can prompt when the gate or adjacent ranges contain mappings.

Removing a gate changes the adjacent intervals. Reopen those ranges and check their condition tabs and output modes afterward. Do the same after reducing the gate count or normalizing the layout.

The editor provides a **Ctrl+Z** snapshot undo mechanism while the profile is stopped and UI key input is not suspended. The history is limited to **20** snapshots. Do not treat it as complete undo coverage for every gate operation or nested action edit; saving a known-good profile remains the dependable recovery point.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Moving the axis produces no output | The intended condition tab contains an action; the profile is running in the correct mode; nested conditions are satisfied; its output destination is valid. |
| Gates move, but commands never run | Editing a layout alone does not add output actions. Open the gate/range and configure a container on the relevant condition tab. |
| A command repeats throughout a zone | A continuous In Range or Outside of Range condition may be driving it. Use Enter Range or Exit Range for a one-shot. |
| A button remains pressed after leaving | Use Range Hold with a hold-style nested action, or provide an appropriate timed/explicit release for a crossing action. |
| Exit Range does not release the Enter Range output | Exit Range is a separate activation. Use Range Hold for matched press/release behavior. |
| Output uses only part of a virtual axis | Use Rebased or Ranged rather than Normal; also check scaling in the nested action. |
| Filtered range leaves the last output in place | Expected: filtering suppresses updates; it does not reset the destination. Configure a fixed value or another condition if a reset is required. |
| Direction appears backward | Check numeric movement and the chosen Cross (inc)/(dec) tab. Account for the event-history label issue noted below. |
| Small movement triggers a gate repeatedly | Observe whether the input oscillates across the boundary; reposition the gate away from an unstable rest position or address source-axis processing. Trigger Delay is not a deadband. |
| One crossing causes duplicate commands | Check Crossed and directional tabs, adjacent range Enter/Exit mappings, and other actions on the same source. |
| Startup sends an unexpected command | The initialization evaluation can fire range conditions without movement. Test the initial position and review Enter/Exit mappings. |
| Mapping information disappeared after editing | Gate deletion, gate-count reduction, or normalization may have changed affected ranges. Restore the saved profile or preserved mapping. |
| Cannot add a gate | Check for an existing gate at that value and the 20-gate maximum. |
| Range cannot be configured sensibly | Separate coincident gates and check adjacent boundaries. |
| No event-history text | Enable Show events and at least one display filter; test in the editor. The history is not a complete runtime log. |
| Analog output looks scaled twice | Review the range Output Mode and the nested action's own range/curve processing. |

