# Map to vJoy — User Guide

Map to vJoy sends an input to a virtual joystick output. It supports **vJoy** and **HIDMaestro** output devices. Use it to map a physical control to a virtual axis, button, or hat; turn an axis range into a button; combine axes; or move an axis with buttons or an encoder.

The action supersedes the legacy **remap** action.

The action is also identified as **Vjoy Remap** and **Map to Vjoy**. This guide describes the supplied GremlinEx implementation. Available controls depend on the source input and the selected action mode. Mode descriptions below describe their behavior; the wording in the Mode list may vary by build.

## Contents

- [Map to vJoy — User Guide](#map-to-vjoy--user-guide)
  - [Contents](#contents)
  - [Before you start](#before-you-start)
    - [Choose a virtual output device](#choose-a-virtual-output-device)
    - [Axis values](#axis-values)
  - [Create your first mapping](#create-your-first-mapping)
  - [Choose a mapping mode](#choose-a-mapping-mode)
  - [Map and shape an axis](#map-and-shape-an-axis)
    - [Absolute axis mapping](#absolute-axis-mapping)
    - [Limit the output range](#limit-the-output-range)
    - [Apply an output curve](#apply-an-output-curve)
    - [Relative axis mapping](#relative-axis-mapping)
  - [Map buttons](#map-buttons)
    - [Trigger on press or release](#trigger-on-press-or-release)
    - [Pulse timing](#pulse-timing)
  - [Turn an axis range into a button](#turn-an-axis-range-into-a-button)
  - [Map hats](#map-hats)
    - [Hat to virtual hat](#hat-to-virtual-hat)
    - [Button to hat](#button-to-hat)
    - [Hat to buttons](#hat-to-buttons)
  - [Set an axis with a button](#set-an-axis-with-a-button)
  - [Control an axis with two inputs](#control-an-axis-with-two-inputs)
    - [Set the reverse input](#set-the-reverse-input)
    - [Set the startup position](#set-the-startup-position)
    - [Velocity: move while held](#velocity-move-while-held)
    - [Stepped: move between presets](#stepped-move-between-presets)
    - [Stepped+PID: move smoothly between presets](#steppedpid-move-smoothly-between-presets)
    - [Encoder: adjust with pulses](#encoder-adjust-with-pulses)
    - [PID: move a target and follow it smoothly](#pid-move-a-target-and-follow-it-smoothly)
  - [Merge axes](#merge-axes)
  - [Startup and output options](#startup-and-output-options)
    - [Startup state](#startup-state)
    - [Local and remote output](#local-and-remote-output)
    - [Release and display options](#release-and-display-options)
  - [Worked examples](#worked-examples)
    - [A throttle with a high-end detent button](#a-throttle-with-a-high-end-detent-button)
    - [Five discrete flap positions](#five-discrete-flap-positions)
    - [Smooth flap transitions](#smooth-flap-transitions)
    - [Smooth trim adjustment](#smooth-trim-adjustment)
    - [One hat, separate command buttons](#one-hat-separate-command-buttons)
  - [Troubleshooting](#troubleshooting)

## Before you start

Have the following ready:

- A GremlinEx profile containing the source input you want to use.
- A connected virtual output device with the axis, button, or hat you need.
- A way to observe the virtual output while testing, such as the application's output display or a joystick monitor.

Configure the target game or application to use the virtual output you select. A physical input and its virtual output are separate controls; verify which one the target application has bound.

For the first test, use one source input and one virtual output. Add curves, merging, or remote output after the basic mapping works.

You can test output values in the GEX **input viewer**. For vJoy devices, you can also use the **vJoy Monitor** utility included with your vJoy installation. For HIDMaestro, use a joystick monitor on the computer hosting the controller. This is often faster and easier than testing in the game directly.

### Choose a virtual output device

The **Device** list includes available vJoy devices and HIDMaestro devices included in GremlinEx. Select the device by name, then choose an output that it actually exposes. Devices with different axis, button, or hat counts offer different output choices.

For **vJoy**, configure and enable the virtual controller with your vJoy installation before selecting it in the action.

For **HIDMaestro**:

1. Run the Maestro Bridge service on the computer that will host the virtual controller.
2. Enable the **Maestro** module in GremlinEx's module configuration if needed.
3. Open **Tools → Maestro Devices...** and enter the service **Host** and **Port**, plus the local reply address and **Reply port**. The reply port must match the service's **SendPort**.
4. Use **Refresh Devices** to load the host's devices. Select an existing device, or create one with **New Device** or **Presets...**.
5. Ensure the device is **Active on host**, check **Include in Gremlin**, and select **Apply to Gremlin**.
6. Select that controller in the action's **Device** list, choose the output, and test it.

Maestro output uses the configured bridge connection, including when the bridge runs on another computer. The virtual controller is available to games on the host computer. The action's separate remote-vJoy routing controls do not select the Maestro host; see [Local and remote output](#local-and-remote-output).

### Axis values

Axis settings generally use a normalized range:

| Value | Meaning |
| --- | --- |
| `-1.0` | Low end |
| `0.0` | Center |
| `+1.0` | High end |

The full span is **2.0 units**. A change of `0.05` is 2.5% of the full span. Center does not necessarily mean “off” in a game; that depends on the control you bind.

## Create your first mapping

1. Select the profile mode and source input you want to map.
2. Add **Map to vJoy** to the input's action container.
3. In **Mode**, select the required mapping behavior. For a simple test, use direct axis, button, or hat mapping to match the source control.
4. In **Device**, select the destination virtual joystick.
5. In **Output**, select its axis, button, or hat.
6. Save the profile and start it.
7. Operate the source control and observe the virtual output.
8. Bind that virtual output in the target game or application.

**Next Unused** selects an available output according to the profile's usage information. It does not guarantee that the output is unused by other applications.

**Show disconnected** includes unavailable virtual devices in the selector. Selecting one does not connect it. Resolve the device warning before relying on the mapping.

## Choose a mapping mode

The Mode list changes with the input type. Select the source input first, then choose the behavior.

| Source | Available behavior families |
| --- | --- |
| Axis | Direct axis output, axis-to-button, axis merging |
| Button or input treated as a button | Button hold/invert/press/release/pulse/toggle; hat output; axis inversion; set-axis; stepped-axis; change-axis-range; merging; local/remote control commands |
| Hat | Direct hat output or hat-to-button mapping |

Keyboard and other supported event inputs may be treated as buttons by the surrounding input/container configuration. Use **Override input type** only when the action needs to interpret an input as an axis, button, or hat differently from its current configuration. An override changes the interpretation; it does not create missing input data.

## Map and shape an axis

### Absolute axis mapping

Use **Absolute** when the virtual axis should follow the source axis position.

1. Choose the axis mapping mode.
2. Select the destination device and axis.
3. Select **Absolute**.
4. Move the source through its full travel.
5. Enable **Reverse Axis** if the direction is opposite to the one you need.

For example, a throttle can drive a virtual throttle axis directly, while a stick axis can drive virtual pitch or roll.

### Limit the output range

Under **Output Scale**, set **Range Min** and **Range Max** to constrain the output span.

| Range Min | Range Max | Resulting span |
| --- | --- | --- |
| `-1.0` | `+1.0` | Full travel |
| `-0.5` | `+0.5` | Middle half of full travel |
| `0.0` | `+1.0` | Upper half of the normalized range |

Use **Reset** to restore the normal full range. Test both endpoints after changing the range.

### Apply an output curve

Select **Output Curve** to edit the action's curve. A curve changes how input movement translates into output movement—for example, to make movement near the center less sensitive.

Use the adjacent remove control to clear the action's output curve. Other curves applied elsewhere in the input configuration can still affect the result. Watch the input/output values rather than assuming this is the only curve in the profile.

### Relative axis mapping

Use **Relative** when the source should increase or decrease the current output instead of commanding an absolute position.

1. Select **Relative**.
2. Set **Relative Value**, the amount applied per update.
3. Set the pulse/update delay in milliseconds.
4. For a centered analog input, enable **Use relative value** so the amount is scaled by input deflection and updates stop near the center.
5. Test movement in both directions and return the source to center.

Smaller increments or longer delays produce slower movement. Reversing the axis reverses the direction of relative adjustment.

Unlike Absolute mode, returning the source to center normally leaves the virtual axis at its accumulated position. Verify the stop behavior before using a large increment.

## Map buttons

Choose the behavior that matches the desired output state.

| Behavior | What it does | Typical use |
| --- | --- | --- |
| Hold / normal button | Output follows the input's pressed/released state. | Momentary commands |
| Inverted button | Output uses the opposite input state. | Reversing switch logic |
| Press | Sets the output button on without automatically pairing it with a release. | One input turns a function on |
| Release | Sets the output button off. | A second input turns that function off |
| Pulse | Sends a timed press followed by a release. | A brief command from a switch or button |
| Toggle | Alternates the output state on successive qualifying triggers. | Latching a function with one button |

For a normal momentary mapping, start with Hold and leave **Ignore release** off. For Press mappings, provide a deliberate way to release the same output, such as a separate Release action.

### Trigger on press or release

The execution controls select whether supported actions run on the source press, release, or both. They are especially useful for pulse, set-axis, and command actions.

Select only the event you need for a one-shot action. Enabling both can cause one physical press-and-release cycle to trigger the action twice. Hold-style mappings still need the appropriate release behavior to avoid leaving the output on.

### Pulse timing

- **Pulse Delay** is the duration of the output press, in milliseconds.
- **Repeat delay** controls the spacing of repeated pulses.
- Enable pulse repetition to keep pulsing while the triggering condition remains active.

The supplied default duration is **125 ms**; the default repeat delay is also **125 ms**. If the target application misses brief pulses, increase the duration and test again.

## Turn an axis range into a button

Use axis-to-button mapping for a detent, end-stop, or position zone.

1. Select the source axis and add the action.
2. Choose the axis-to-button mode.
3. Select a destination device and button.
4. Set **Axis to Button Range Min** and **Range Max**.
5. Choose **Hold** or **Pulse**.
6. Move into, within, and out of the range while observing the output.

Use the grab controls to capture the current axis value as either boundary.

| Quick setting | Range |
| --- | --- |
| Reset | `-1.0` to `+1.0` |
| Half | `-0.5` to `+0.5` |
| L-Half | `-1.0` to `0.0` |
| U-Half | `0.0` to `+1.0` |
| Bot | `-1.0` to `-0.75` |
| Top | `+0.75` to `+1.0` |

**Hold** keeps the output on while the axis is in range and releases it when the axis leaves. **Pulse** starts when the axis enters the range; repetition, if enabled, continues until it leaves.

For a throttle detent near the high end, try `0.90` to `1.00`. These are example values; use the displayed axis value to find the correct range for your device. Curves and other axis processing can affect the value being tested.

For position-dependent behavior, use Hold or Pulse in this version. See [Behavior notes for this version](#behavior-notes-for-this-version) before using the range panel's Press or Release options.

## Map hats

### Hat to virtual hat

Select the hat mapping mode, destination device, and output hat. Test all eight directions and the centered position.

### Button to hat

For button-based hat output, select the output hat and configure:

- **Press Position**: the direction to send when activated.
- **Release position**: the position to send when released or when a pulse completes.

Choose centered as the release position when the hat should return to neutral. Use a hat press action to retain a position, or a hat pulse action for a timed direction command.

### Hat to buttons

Use hat-to-button mapping when the target application needs separate buttons for hat positions.

1. Choose the hat-to-button mode and destination device.
2. Assign a button to each direction you want to use.
3. Choose a behavior for each position.
4. Configure the center position deliberately; select **Not mapped** or **NoOp** if it should not issue a command.
5. Test transitions between adjacent directions, diagonals, and center.

| Per-position behavior | Result |
| --- | --- |
| Hold | Tracks the active position and releases previously held positions as the hat changes. |
| Pulse | Sends a timed output for that position. |
| Press | Turns the selected button on. |
| Release | Turns the selected button off. |
| NoOp | Sends no output for that position. |

**Map Buttons** assigns sequential button numbers, using the first position's selection as a starting reference when set. **Clear Buttons** removes the assignments. The **All Hold**, **All Pulse**, **All Press**, **All Release**, and **All NoOp** controls set the behavior across the table.

After automatic assignment, check every row, including center. Stay within the destination device's available button count. NoOp means “do nothing”; it should not be used as an implicit release command for an output you intentionally left on.

## Set an axis with a button

Choose the set-axis mode when a button should command a particular virtual axis position.

1. Select a button-like input.
2. Choose set-axis mode and the destination axis.
3. Enter **Set Value** within `-1.0` to `+1.0`.
4. Select the triggering event, usually press only.
5. Start the profile and test the button.

Examples include setting a throttle to an idle position or centering a virtual control at `0.0`.

**Is Relative** is presented as the option for adding the entered value to the current output. In the supplied implementation, that checkbox does not control the setting read by the set-axis output routine, so do not rely on it alone for incremental movement. For repeatable increments, use the stepped-axis modes below. Axis output is limited to the normalized bounds.

**Use last** resends the last axis value with a small temporary movement intended to make the target application reread it. Use it only when that behavior is needed.

Two related modes are available for button-like inputs:

- **Invert axis** changes the target axis's reversal state when triggered.
- **Change axis range** changes the range used for the selected output axis. It does not itself move a physical input.

## Control an axis with two inputs

Choose the stepped-axis action mode, then select a behavior under **Button to Axis (step) Mode**:

| Mode | How the axis moves | Typical use |
| --- | --- | --- |
| Velocity | Moves continuously while the input is held. | Hold a button to adjust trim. |
| Stepped | Jumps directly to the next configured preset. | Discrete flap positions. |
| Stepped+PID | Moves smoothly toward the next configured preset. | Flaps that travel gradually between detents. |
| Encoder | Accumulates pulses, with optional speed-based acceleration or return to center. | Rotary encoder adjustment. |
| PID | Changes a target by a configured amount and follows it smoothly. | Fine trim adjustment with momentary inputs. |

All five modes share **Initial axis value** and the secondary reverse-input configuration. See [Set the startup position](#set-the-startup-position) for fixed and automatic initialization.

### Set the reverse input

The source input is the primary control. To add a control for the opposite direction:

1. Enable **Latch secondary input for reverse action**.
2. Under **Latched Input Type**, choose **Keyboard** or **Joystick**.
3. For Keyboard, use **Select Keys** to define the secondary key sequence.
4. For Joystick, select the device and input, or use the listen control. Select the direction when using a hat input.
5. Test each input separately.

Here, “secondary” or “latched” input is a reverse-direction trigger. It is not an instruction to hold the primary and secondary controls together. A keyboard sequence assigned to the secondary trigger can itself require multiple simultaneous keys.

Use a distinct control or key combination for each direction. Begin with execution on press only and test both controls, including their releases. See [Behavior notes for this version](#behavior-notes-for-this-version) for the current direction-selector limitation in Stepped, Stepped+PID, and PID modes.

### Set the startup position

For a fixed startup position, choose a numbered step preset so **Initial axis value** is editable, then enter a value or move its slider. The configured value is sent immediately when the profile starts; the mode's movement state starts from the same position. Even Stepped+PID and PID initialize immediately rather than easing from the previous output.

In **Stepped** and **Stepped+PID**, **Use step preset: Start Index** and the selection beside an individual step copy that preset into **Initial axis value**. The start index is numbered from **1**. The slider shows the configured step positions as tick marks, and **Preset value** shows the selected preset.

**Auto** requests initialization from the current virtual output axis position instead of the configured initial value. It reads the virtual output, not the physical source control. When Auto is active, the fixed startup controls are disabled. The current editor has an Auto-selection limitation; check [Behavior notes for this version](#behavior-notes-for-this-version) before relying on it.

### Velocity: move while held

Use Velocity for continuous adjustment while a button is held.

| Setting | Effect |
| --- | --- |
| Update Interval (ms) | Time between output updates. |
| Rate of change | Axis movement per second. |
| Acceleration | How quickly the movement rate changes; `0` gives a constant rate. |

Choose a modest rate, test a short press, and then test a longer hold. The secondary input moves in the opposite direction.

### Stepped: move between presets

Use Stepped for a fixed set of positions, such as flap or mixture presets.

1. Define the step values, keeping them in ascending order within `-1.0` to `+1.0`.
2. Adjust **Steps**, use **Add Step**, edit the comma-separated list or individual values, or choose a list from **Presets...**. Use the delete control beside a value to remove it.
3. Check **Step direction** and test which input increases or decreases the output; see the current [direction-selector limitation](#behavior-notes-for-this-version).
4. Choose **Use step preset: Start Index** or select an individual step to set the startup value. Verify **Preset value** and **Initial axis value**.
5. Start the profile and test each direction from the configured startup position.

**Presets...** replaces the step list with a supplied distribution, including evenly spaced lists, **Ends + Quarters + Center (9)**, and geometric low/high lists. Review the resulting values and count before running the profile.

Distribution controls help generate values:

| Control | Purpose |
| --- | --- |
| Normalize | Even spacing |
| Low / High | More positions toward the low or high portion of the range |
| Geometric Low / Geometric High | Nonlinear spacing toward an end |
| Cubic Center | Cubic progression around the center |

The step sequence stops at its endpoints rather than wrapping. Keep the list nonempty and verify the first trigger in each direction, especially if **Initial axis value** lies between presets.

### Stepped+PID: move smoothly between presets

Use **Stepped+PID** when you want the same discrete target positions as Stepped, with gradual movement between them.

1. Select **Stepped+PID** under **Button to Axis (step) Mode**.
2. Define the step values with the same preset, list-editing, and distribution controls used by Stepped.
3. Select a startup preset and check **Initial axis value**.
4. Configure the secondary reverse input and use execution on press only for the first test.
5. Start the profile and observe the output during single presses, rapid presses, and a direction change.

Each trigger requests the next preset. The axis moves faster at first and eases into that target, continuing after the button is released. Further triggers choose presets from the commanded target while the output is still moving. For example, with presets `-1.0`, `-0.5`, `0.0`, `0.5`, and `1.0`, two increase triggers from `0.0` request `0.5` and then `1.0` without waiting for the first transition to finish. The sequence stops at its endpoints.

Stepped+PID uses the exact preset values as targets. PID's **Setpoint change per press** and faster-input acceleration do not enlarge these preset steps. The current Stepped+PID panel shows the stepped controls; response-time editing and saving have a limitation described in [Behavior notes for this version](#behavior-notes-for-this-version).

### Encoder: adjust with pulses

Use Encoder when a rotary control generates momentary events in each direction.

Bind one direction as the primary input and the other as the secondary reverse input. Then choose:

| Setting | Effect |
| --- | --- |
| Relative | Keeps the accumulated axis position after rotation stops. |
| Spring | Returns the axis to center after pulses stop. |
| Spring delay (ms) | Idle time before the return to center. |
| Min Step / Max Step | Smallest and largest movement per pulse. |
| Start Frequency (Hz) | Pulse frequency where acceleration begins. |
| Full Frequency (Hz) | Pulse frequency that reaches the maximum step. |
| Curve Power | Shapes how the step grows with input speed. |
| Timeout (ms) | Idle time before acceleration resets. |

Keep Full Frequency above Start Frequency. Use small steps for fine adjustment and larger accelerated steps for rapid travel. In Spring mode, use a positive spring delay if automatic return is required.

### PID: move a target and follow it smoothly

Use PID when each momentary press should change a target position and the axis should move smoothly toward it. The axis moves quickly at first and eases into the target.

1. Select **PID**.
2. Set **Initial axis value**.
3. Set **Setpoint change per press**.
4. Set **Response time (s)**.
5. Assign the increase control as primary and the decrease control as secondary; see the current [direction-selector limitation](#behavior-notes-for-this-version).
6. Configure the secondary reverse input if needed.
7. Test single presses before enabling acceleration.

| Setting | Supplied default | Meaning |
| --- | --- | --- |
| Setpoint change per press | `0.05` | Change in the target per incoming press event. |
| Response time (s) | `1.0` | Approximate time to close 99% of the gap; lower values make the response faster. |

With execution on press only, PID changes the target on incoming press events; it continues following the target after release. If the input source produces repeated press events while held, those events can produce additional target changes. Use Velocity for continuous movement while held. Additional qualifying triggers adjust the commanded target while the axis is still moving, and an opposite trigger can redirect it before it settles.

**Response time (s)** accepts `0.05` to `120.0` seconds. It scales the whole curved transition; it is not a constant movement speed or an exact arrival deadline. Use **Stepped+PID** when targets must come from a fixed list of presets.

Enable **Accelerate setpoint steps with faster input** to make rapid presses change the target by larger amounts.

| Acceleration setting | Supplied default | Meaning |
| --- | --- | --- |
| Maximum step multiplier | `4.0` | Largest step relative to the base step. |
| Acceleration starts (triggers/s) | `2.0` | At or below this rate, use the base step. |
| Full acceleration (triggers/s) | `12.0` | Rate that reaches the maximum step. |
| Acceleration curve | `2.0` | Higher values delay the increase toward the maximum step. |
| Idle reset (s) | `0.75` | A pause this long resets acceleration; direction changes reset it too. |

Keep Full acceleration above Acceleration starts. Output remains within `-1.0` to `+1.0`.

## Merge axes

Use axis merging to combine a primary axis with one or more additional axes.

1. Select the primary axis and choose the merge-axis mode.
2. Choose the destination device and axis.
3. In **Merge Information**, select a **Merge Device** and **Merge Axis**, or use the listen control.
4. Choose the merge operation.
5. Configure a curve for the additional axis if needed.
6. Test each source separately, then move them together.
7. Add further merge entries only after the first combination behaves correctly.

Each merge entry uses the running result as **A** and its selected axis as **B**. Entries are processed in order, so changing the sequence can change the result.

| Operation family | Use |
| --- | --- |
| Add | Combines A and B by addition. |
| Average | Uses `(A + B) / 2`. |
| Center | Uses `(A - B) / 2`, useful for opposing controls. |
| Minimum / Maximum | Chooses the lower or higher value. |
| Multiply | Uses one input to scale the other by multiplication. |
| Scale variants | Uses B as a scaling control; centered and half variants interpret B differently. |
| Trim / Trim (centered) | Uses B to adjust the primary axis's response. |

Scaling and range processing also affect the final output. For scale and trim variants, watch the live values while moving B through both ends and center rather than assuming the variant matches your device's rest position.

Use **Reverse Axis** to invert the primary input before merging. Use **Invert Merged Output** to reverse the final combined result.

When axis repeaters are enabled, each merge entry shows a **Step Output** value for its selected source axis. The main **Output** preview reflects the combined result and updates when either the primary axis or an additional merge axis moves. Use both displays to check which input changes the result before testing in the target application.

## Startup and output options

### Startup state

Where displayed, the startup synchronization controls let you initialize an output from a configured default or the source input. Test startup with the source in more than one position to confirm that the initial output is appropriate.

The five button-to-axis modes initialize separately from the general synchronization controls: they apply **Initial axis value**, or reuse the virtual output position when Auto is active. See [Set the startup position](#set-the-startup-position).

### Local and remote output

For **vJoy** destinations, the action includes output routing through its remote-client controls. Check the routing when a mapping works remotely but not locally, or vice versa.

Button-like inputs can also select command modes that enable or disable local output, enable or disable remote output, choose local-only or remote-only output, enable both, toggle remote output, or control paired remote behavior. These commands change routing state; they are not ordinary button mappings.

Configure remote clients through the application's remote-output features before using remote routing. Leave **Paired Group Member** unchanged unless the mapping is part of an intentionally paired setup.

For **HIDMaestro** destinations, axis, button, and hat output goes through the configured Maestro Bridge connection. Remote-vJoy client selection and local/remote-vJoy switches do not redirect that output. Change the host in **Tools → Maestro Devices...** when the controller is provided by a different Maestro service.

### Release and display options

| Option | Use |
| --- | --- |
| Ignore release | Suppresses release handling where supported. Normally leave it off for a momentary mapping. |
| Auto Release | Requests release handling for inputs/containers that need it. Test the entire press/release cycle. |
| Show button grid | Shows the output assignment grid. |
| Override input type | Changes how the action interprets the source input. |

## Worked examples

### A throttle with a high-end detent button

Create two actions on the throttle input:

1. A direct Absolute mapping to the virtual throttle axis.
2. An axis-to-button mapping to a separate virtual button, using a range of `0.90` to `1.00` and Hold behavior.

The virtual axis follows the throttle. The virtual button turns on near the high end and off when the throttle leaves the zone. Adjust the boundary using the live value on your hardware.

### Five discrete flap positions

1. Add the stepped-axis action to the increase control.
2. Select **Stepped** and the virtual flap axis.
3. Choose **Presets... → 5 steps**, giving `-1.0`, `-0.5`, `0.0`, `0.5`, and `1.0`.
4. Set **Use step preset: Start Index** to **1** and verify that **Initial axis value** is `-1.0`.
5. Configure a secondary reverse control.
6. Start the profile and verify that each trigger moves to the adjacent preset and stops at the ends.

### Smooth flap transitions

1. Configure the five flap presets from the previous example.
2. Change the mode from **Stepped** to **Stepped+PID**.
3. Verify **Initial axis value** and the secondary reverse control.
4. Start the profile and press the increase control once. The output should travel smoothly toward `-0.5`.
5. Press again during that movement to request `0.0`, then test the reverse control while the axis is moving.

The target positions remain the configured detents, while the virtual axis travels through intermediate values. Bind this output to a game control that accepts an axis. Reload the saved profile and retest the transition timing; see the [Stepped+PID settings limitation](#behavior-notes-for-this-version).

### Smooth trim adjustment

1. Add the stepped-axis action to the trim-increase control.
2. Select **PID** and the virtual trim axis.
3. Set **Initial axis value** to `0.0`, **Setpoint change per press** to `0.02`, and **Response time (s)** to `0.5`.
4. Select **Primary increases** and assign trim-decrease as the secondary input.
5. Leave acceleration off for the initial test.

Each press moves the target by `0.02`; the virtual axis follows smoothly. These are example settings, not the supplied defaults.

### One hat, separate command buttons

1. Select the physical hat and choose hat-to-button mapping.
2. Assign a different virtual button to each direction you need.
3. Use Hold for commands that should remain active while held, or Pulse for brief commands.
4. Leave unused directions unassigned and configure center deliberately.
5. Test transitions through diagonals before binding the buttons in the target application.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| No virtual output | Profile running; correct profile mode; action/container enabled; destination connected; valid output selected; local/remote routing. |
| Virtual output works, but the game does not respond | The game is bound to the selected virtual device and output rather than the physical control or another virtual device. |
| Desired axis, button, or hat is missing | The selected destination actually exposes that output type and number. |
| Output moves backward | Reverse Axis, final merge inversion, and other curves or reversal settings. |
| Axis does not reach the expected endpoints | Output Scale, output curves, merge operations, and any range-changing action on that output. |
| Relative axis keeps moving at center | Enable Use relative value for deflection-scaled updates; verify the source returns near zero. |
| Button remains on | Press/toggle behavior, Ignore release, missing Release action, or a container that does not deliver release events. |
| One press causes two adjustments | Both press and release selected, duplicate actions targeting the output, or repeated input events. |
| Pulses are missed | Increase pulse duration; verify the destination button and trigger condition. |
| Axis-range button activates at the wrong position | Observe the processed axis value, review the range, and check the behavior notes below. |
| Secondary input does nothing | Enable reverse-input latching; verify Keyboard/Joystick selection, device, input, hat direction, and relevant conditions. |
| Stepped axis starts at an unexpected value | Check Initial axis value, the selected Start Index, and whether Auto is active. Preset selection now copies the preset into Initial axis value. |
| Stepped axis stops changing | It may have reached the first or last preset. |
| Stepped+PID jumps immediately on profile start | Expected for a fixed startup value. Smoothing applies to subsequent target changes. |
| Stepped+PID timing changes after reloading | The current profile writer does not save its PID response-time setting; see the behavior notes below. |
| PID output continues after release | Expected: it is finishing the move to the target. Increase/decrease Response time to change the transition speed. |
| Direction selector does not reverse PID or preset stepping | The current handlers use primary for increase and secondary for decrease; swap the assigned controls and see the behavior notes below. |
| Encoder feels too fast or too slow | Min Step, Max Step, acceleration frequencies, Curve Power, and Timeout. |
| Merged axis jumps or disagrees with expectations | Source rest positions, curves, operation order, conflicting writers to the same output, and final inversion. |
| Maestro device is missing from Device | Maestro module enabled; bridge running; correct host, service port, and reply settings; device active on host and included in Gremlin; Apply to Gremlin completed. |
| Maestro output goes to the wrong computer | Check the Maestro Bridge host. Remote-vJoy routing does not choose the Maestro host. |

When diagnosing a problem, temporarily reduce the mapping to one action with no extra curve or merge. Verify the input event, the virtual output, and then the target application's binding in that order.

