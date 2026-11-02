# Map to State — User Guide

**Map to State** changes the profile's ordinary on/off states from an input. Use it to follow a physical switch, toggle a flag, send a pulse, select a control bank, or update a set of related states.

Create and organize states in the [State Device](../devices/state_device_user_guide.md). Map inputs to ordinary states, then use those states or derived expression states in conditions, State containers, and output mappings.

## Contents

- [Create your first mapping](#create-your-first-mapping)
- [Choose the target states](#choose-the-target-states)
  - [One state](#one-state)
  - [An explicit list](#an-explicit-list)
  - [Categories](#categories)
  - [Attributes](#attributes)
- [Follow a switch or held button](#follow-a-switch-or-held-button)
- [Set or clear a state](#set-or-clear-a-state)
- [Toggle a state](#toggle-a-state)
- [Pulse a state](#pulse-a-state)
- [Latch a state for a fixed interval](#latch-a-state-for-a-fixed-interval)
- [Choose the triggering event](#choose-the-triggering-event)
- [Apply an operation to other states](#apply-an-operation-to-other-states)
- [Map a hat to states](#map-a-hat-to-states)
- [Use randomized state changes](#use-randomized-state-changes)
- [Startup and stop settings](#startup-and-stop-settings)
- [Worked examples](#worked-examples)
  - [Track a panel switch](#track-a-panel-switch)
  - [Trigger one state from another](#trigger-one-state-from-another)
  - [Use a state as a condition](#use-a-state-as-a-condition)
  - [Toggle an alternate command layer](#toggle-an-alternate-command-layer)
  - [Clear a group of flags](#clear-a-group-of-flags)
  - [Select one state in a category](#select-one-state-in-a-category)
- [Test the mapping](#test-the-mapping)

## Create your first mapping

1. Create an ordinary state named `shift_held` in the State Device, with Default State set to Off.
2. Select a physical button and add **Map to State** to its action container.
3. Under **Apply to**, choose **State (single)**.
4. Select `shift_held` in **State**.
5. Select **Hold** under Mode.
6. Leave **Other State Mode** on NoOp and Randomize disabled.
7. Save and start the profile.
8. Watch `shift_held` in the input viewer while pressing and releasing the source.

Hold sends the source's pressed/released value to the state. The state should be On while the button is held and Off after release.

The action offers button, hat, and keyboard input types according to the surrounding input configuration. Start with a joystick button when testing a new state setup. A raw hat uses the direction table described below.

## Choose the target states

**Apply to** selects the states changed by the action's main Mode. Use ordinary states for these targets. Expression states should get their values from their source states.

### One state

Choose State (single), then select the state by name. The Description field helps identify its purpose.

The adjacent add control creates a state without leaving the action. In **Add State**, enter a unique name, optional description, and an On or Off default. Confirm, then check the action's selected state. Use the full State Editor for expressions, categories, attributes, autorelease, or exclusive groups.

### An explicit list

Choose **States (multi)**. Click **Pick…** in the States list and select the names to include. Select list entries and click **Remove** to remove them from this action's target list.

The main operation applies to every listed target. For example, Release (off) can clear a fixed list of flags with one input.

### Categories

Choose **Category**, click Pick… beside Categories, and select one or more categories. The action matches states in any of the selected categories.

Review **Impacted states** before testing. Assigning another state to a selected category adds it to that selection without adding its name to an explicit list.

### Attributes

Choose **Attributes**, then use Pick… to choose labels defined on states. A state matches if it has **any** of the selected attributes; it does not need all of them.

Use exact attribute spelling and case. Check Impacted states after changing the selection or editing state labels. For example, attach `reset_on_command` to flags in several categories, then target that attribute from one reset action.

For Category and Attributes, keep expression states out of the writable selection by choosing suitable categories or labels. Use an expression when the requirement is a logical combination of state values.

## Follow a switch or held button

Select **Hold** when the state should follow the physical input. Hold handles the source's On and Off values, so it is appropriate for a maintained switch or a temporary shift button.

Select **Invert** when a pressed source should set the state Off and a released source should set it On. Start with Execute on press enabled and verify both edges in the viewer.

Ensure the surrounding container and conditions let release events reach the mapping. For a maintained switch, also set startup synchronization to Input so an already-on switch is read when the profile starts.

## Set or clear a state

Use **Press (on)** to set the targets On when the selected event triggers. Use **Release (off)** to set them Off. These names describe the requested state value; Execute on press/release selects the physical event that performs the operation.

For separate On and Off controls:

1. Add Map to State to the On input, select the target, and choose Press (on).
2. Add another to the Off input, select the same target, and choose Release (off).
3. Use execution on press only for both actions.
4. Test the two controls in either order.

Setting an ordinary state to its existing value normally does not create a new state transition. Use Pulse for a momentary event or change the state deliberately when its attached actions need another press/release cycle.

## Toggle a state

Select **Toggle** to change Off to On or On to Off on each qualifying event. New actions use Toggle with execution on press only.

For a one-button switch, keep Execute on press enabled and Execute on release disabled. Test two complete press/release cycles: the first press should set the state and the second should clear it.

Use one ordinary state per independently held source when inputs can overlap. Combine those source states with an expression instead of writing several Hold mappings to the same destination.

## Pulse a state

1. Select **Pulse**.
2. Under **Pulse Options**, set the pulse duration in milliseconds.
3. Choose whether **Pulse inverts state** is enabled.
4. Leave **Pulse repeat** off for the first test.
5. Start the profile and observe the state through one complete pulse.

With Pulse inverts state enabled, the pulse toggles the state at its start and again at its end. This is useful when a pulse should temporarily invert an existing value. With it disabled, the pulse sets On and then Off. Avoid another mapping writing that state during the pulse when the original value matters.

New actions use a pulse duration of `250 ms`, Pulse inverts state enabled, and repetition disabled. **Pulse repeat** adds repeated cycles with a separate repeat-delay field, also initially `250 ms`. Test the full source press/release cycle and any profile mode change before using repeated pulses in a larger mapping.

Pulse duration and repeat delay are separate from the state's own Autorelease settings. Keep state-level Autorelease disabled for a simple action-controlled pulse.

## Latch a state for a fixed interval

Select **Latch** to turn an Off state On for **Latch delay (ms)**. Repeated On requests during the active latch interval are ignored; they do not keep extending that interval. The state returns Off when the timer expires, and clearing it earlier ends the active latch.

1. Select an ordinary Off state.
2. Choose Latch and enter a positive delay, such as `1000 ms`.
3. Use press-only execution.
4. Trigger it repeatedly during the first second, then wait for Off.

Use the [State Editor's Autorelease controls](../devices/state_device_user_guide.md#configure-automatic-state-changes) when the timer rule should belong to the state itself. Use Latch when this mapping should initiate the timed On interval.

## Choose the triggering event

Use **Execute on press** for operations such as Press (on), Release (off), Toggle, or Latch when the command should run as a button is pressed. Use **Execute on release** when it should run as the source is released.

Enabling both can apply a one-shot operation twice during one physical press/release cycle. In particular, Toggle can turn On at the press and Off at the release.

Hold follows both values of the source. Pulse has its own cycle, so test it as a complete operation rather than using the trigger checkboxes as a pulse-duration control. **Other State Mode** uses the selected trigger events separately from the main operation.

## Apply an operation to other states

**Other State Mode** performs an additional operation on states outside the main target selection. Leave it on **NoOp** when only the selected targets should change.

To clear peers after selecting a state:

1. Put the related ordinary states in one category.
2. Choose the selected state's main operation, such as Press (on).
3. Set Other State Mode to Release (off).
4. Enable **Category Only**.
5. Test each selection while watching all states in that category.

Category Only limits the additional operation to categories represented by the main targets. With it disabled, the additional operation reaches the profile's other states across categories. For a multi-target selection, the main targets are excluded from the additional operation.

Other State Mode also offers Press (on), Toggle, XOR, AND, and OR. For the Boolean operations, each target's value after the main operation is combined with each other state's current value:

- **XOR** sets the other state On when its value differs from the target's value.
- **AND** keeps the other state On only when both values are On.
- **OR** sets the other state On when either value is On.

With several main targets, these combinations are applied successively for each target. Begin with a single target and a small category when configuring them.

Select main Mode **NoOp** when only the Other State Mode operation is needed. The main targets are still used to identify the excluded states, categories, and Boolean values.

For a group-wide selection rule that should apply whenever any mapping sets a member On, configure [Mutually exclusive](../devices/state_device_user_guide.md#make-states-mutually-exclusive) in the State Editor. Other State Mode is an operation attached to this particular action.

## Map a hat to states

On a raw hat input, assign states in the direction table rather than using the single button-mode selector:

1. Add Map to State to the hat input.
2. Select a state for each direction you need, including diagonals where appropriate.
3. Choose **Hold**, **Pulse**, **Press**, **Release**, or **NoOp** for each position.
4. Leave center unmapped or use NoOp unless centering should issue a command.
5. Test each direction, adjacent transitions, diagonals, and return to center.

Use **All Hold**, **All Pulse**, **All Press**, **All Release**, or **All NoOp** to set the table's operation across positions. **Clear Buttons** clears its assignments; assign the required state names manually afterward.

When Apply to selects more than a single state, a position can also affect the additional selected targets. Test with State (single) and one mapped direction before adding a broader target selection.

## Use randomized state changes

Enable **Randomize** when an input should produce probabilistic state changes, such as a varied sequence or wiggle setup. The panel exposes **Skip Chance %** for adjusting the gate, and Pulse uses its own timing controls instead.

Keep Randomize off for switch tracking, bank selection, and command-enable states that must respond to every input. For a randomized setup, use a dedicated test state and watch many triggers in the viewer while adjusting the percentage. Add the randomized state to the final mapping after the observed result matches the intended use.

## Startup and stop settings

Use **State on profile start** to select initialization for the targets:

- **Ignore** leaves this action out of startup synchronization. The State Device still applies the state's default initialization.
- **Default** applies each target's Default State.
- **Input** reads the source position. Use it with Hold for a maintained joystick switch; Invert reverses the sampled input.
- **LastOrInput** requests the retained last value, using the source when no last value is available.
- **LastOrDefault** requests the retained last value, using the configured default when none is available.

For a predictable switch setup, begin with Hold and Input. Test startup with the switch both On and Off, particularly when other actions also target the same state. Check the hat directions as well when synchronizing a raw hat mapping.

**Reset to Default on stop** returns the action's targets to their configured defaults when the profile stops. It is enabled for new actions. Save the profile after changing these choices; runtime On/Off values are separate from the saved state definitions.

## Worked examples

### Track a panel switch

1. Create `panel_power` with Default State Off.
2. Add Map to State to the switch input.
3. Select panel_power, choose Hold, and set State on profile start to Input.
4. Leave Other State Mode on NoOp and Randomize off.
5. Start with the switch Off, then repeat the test with it already On.

Use panel_power in a condition or State container to enable the panel's commands.

### Trigger one state from another

Use one state as the input that changes a second state. In this example, a physical button holds `light_request` On, and each transition of light_request to On toggles `aux_lights`.

1. In the State Device, create two ordinary states, `light_request` and `aux_lights`, both with Default State Off. Leave Autorelease and Mutually exclusive disabled.
2. On a physical button, add Map to State. Select State (single), target light_request, and choose Hold.
3. In the **State Device tab**, select **light_request** and add a **Basic** container to that state's mapping.
4. Inside that container, add a second Map to State action. Set its target to **aux_lights**, choose **Toggle**, enable Execute on press, and disable Execute on release.
5. Leave Other State Mode on NoOp and Randomize off on both actions. Use State on profile start: Ignore for this test.
6. Save and start the profile. Display both states in the input viewer.
7. Press the physical button. Light_request turns On, and its mapped action toggles aux_lights On.
8. Release the physical button. Light_request turns Off; aux_lights stays On because its Toggle action executes only on the source state's press.
9. Press again. Light_request turns On again and toggles aux_lights Off. Release to return light_request to Off.

The second Map to State action belongs to **light_request's State Device mapping**, with aux_lights selected as its target. This placement makes the state transition trigger the next action in the chain.

To observe a virtual output too, select aux_lights in the State Device and add a normal Hold-style Map to vJoy button action. The virtual button follows aux_lights and stays pressed between the first and second requests.

For a second state that should follow light_request On and Off instead of toggling independently, change the second Map to State action to Hold. Keep the chain directed from light_request to aux_lights; do not add a return mapping that changes light_request from aux_lights.

### Use a state as a condition

Use an enabling state to decide whether another input may set a command state. Here, `commands_enabled` gates a second button that holds `command_active` On.

1. Create two ordinary states, commands_enabled and command_active, both with Default State Off.
2. Map an enable button to commands_enabled using Toggle and execution on press only.
3. On a separate command button, add a Basic container with Map to State targeting command_active. Choose Hold, Other State Mode NoOp, and Randomize off.
4. Open the **conditions for that Map to State action** and add a **State condition**.
5. Select **commands_enabled**, choose **Pressed** to require On, and enable **Apply condition on press only** so the command's release can still pass through.
6. Save and start the profile, then watch both states in the input viewer.
7. With commands_enabled Off, press and release the command button. Command_active remains Off.
8. Press the enable button to turn commands_enabled On. Hold the command button: command_active turns On. Release it: command_active turns Off.
9. Test release handling by holding the command button, turning commands_enabled Off with the enable button, and then releasing the command button. Command_active must return Off.

Changing commands_enabled alone does not press command_active. The condition is checked when the command button's event arrives. The state-triggered mapping in the previous example is the setup to use when a state transition should initiate another action directly.

You can place the same condition on another action, such as a virtual button or keyboard mapping, or select an expression state when several requirements must be met. See the [State Device condition example](../devices/state_device_user_guide.md#enable-a-command-only-when-ready) for a compound condition.

### Toggle an alternate command layer

1. Create `alternate_layer` with Default State Off.
2. Map the layer button to it using Toggle and execution on press only.
3. Put alternate commands in State containers requiring alternate_layer On/Pressed.
4. Put ordinary commands in containers requiring alternate_layer Off/Released.
5. Test switching layers with all command buttons released, then test the release handling needed by any held outputs.

### Clear a group of flags

1. Add the attribute `reset_on_command` to the ordinary states that should be cleared together.
2. Add Map to State to the reset button and choose Apply to: Attributes.
3. Pick reset_on_command and inspect the matched names.
4. Choose Release (off), press-only execution, Other State Mode NoOp, and Randomize off.
5. Turn several flags On in the viewer and press reset.

Use Category instead when every ordinary state in one or more complete categories should be cleared.

### Select one state in a category

1. Create `radio_1`, `radio_2`, and `radio_3` in a `radios` category.
2. Map each selection button to its own state using Press (on).
3. On each action, choose Other State Mode Release (off) and enable Category Only.
4. Use press-only execution.
5. Test that selecting one radio clears its peers while states in other categories remain as configured.

Use the State Editor's Mutually exclusive group instead when every writer of these states should apply the same peer-clearing rule.

## Test the mapping

Use the input viewer to inspect the target values before binding their outputs in a game:

1. Check the source event and the main target selection.
2. Test press and release separately.
3. For Category or Attributes, inspect every matched state.
4. Check any additional Other State Mode targets.
5. Observe dependent expression states and their output mappings.
6. Repeat from a fresh profile start with the hardware in different positions.

If the result is unclear, reduce the setup to one ordinary state, one physical button, Hold or Toggle, Other State Mode NoOp, and Randomize off. Add expressions, group operations, and timers after that mapping works.
