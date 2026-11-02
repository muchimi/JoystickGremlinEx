# State Device — User Guide

Use the **State Device** to create named on/off values in a GremlinEx profile. A state can record a switch position, enable a group of commands, combine several inputs, or trigger a shared mapping.

Create the states in the State Device tab, change ordinary states with [Map to State](../actions/map_to_state_user_guide.md), and use their values in conditions or mappings. State definitions belong to the saved profile. Their runtime values are available across the profile's modes.

## Contents

- [Create a state](#create-a-state)
- [Name and describe states](#name-and-describe-states)
- [Organize states with categories and attributes](#organize-states-with-categories-and-attributes)
- [Create an expression state](#create-an-expression-state)
- [Run actions when a state changes](#run-actions-when-a-state-changes)
- [Use a state as a condition](#use-a-state-as-a-condition)
- [Use the State container](#use-the-state-container)
- [Configure automatic state changes](#configure-automatic-state-changes)
- [Make states mutually exclusive](#make-states-mutually-exclusive)
- [Set the startup values](#set-the-startup-values)
- [Inspect and test states](#inspect-and-test-states)
- [Edit or remove states](#edit-or-remove-states)
- [Worked examples](#worked-examples)
  - [Combine two controls into one output](#combine-two-controls-into-one-output)
  - [Trigger one state from another](#trigger-one-state-from-another)
  - [Enable a command only when ready](#enable-a-command-only-when-ready)
  - [Choose one control bank](#choose-one-control-bank)

## Create a state

1. Open the **State Device** tab and click **Add**.
2. In **State Editor**, enter a **Name**, such as `landing_lights`.
3. Enter a **Description** that explains what On means, such as “Landing lights switch is on.”
4. Choose a **Category**, or leave the existing category selected.
5. Leave **This state is an expression** disabled for a state that an input will set directly.
6. Select **Default State: Off** or **On**.
7. Leave Autorelease and Mutually exclusive disabled for the first test.
8. Click **Ok** and save the profile.

The state is now available to Map to State, state conditions, the State container, and expression states. It can be used as a condition without attaching any actions to its State Device input.

For a first complete mapping, create an Off state, map a physical button to it using **Hold**, and watch it in the input viewer while pressing and releasing the button.

## Name and describe states

State names must be unique within a profile and cannot contain whitespace. Names are **not case sensitive**: `Landing_Lights` and `landing_lights` identify the same state. Use a consistent style such as `lower_case_with_underscores`.

Reserve `and`, `or`, `not`, and `xor` for expression operators. Useful names describe a condition, such as `gear_down`, `shift_held`, `panel_power`, or `weapons_armed`.

Use Description for the longer explanation. For example, `panel_ready` can have the description “Panel power is on and the safety cover is open.” This keeps expressions readable while documenting their purpose.

## Organize states with categories and attributes

A **category** places a state in one named group. **Attributes** are labels that let a state belong to several selections at once.

To assign a category:

1. Edit the state and use the Category selector.
2. Use the adjacent **Edit categories** control to add or rename categories.
3. Select the category and confirm the State Editor.

For example, put `radio_1`, `radio_2`, and `radio_3` in a `radios` category, and put warning flags in an `alerts` category.

To add attributes:

1. In the editor's **Attributes** area, click **Add**.
2. Enter one attribute name per line, such as `panel`, `reset_on_command`, or `annunciation`.
3. Use Edit or Remove to maintain the list. Copy and Paste transfer attribute names as one name per line.
4. Confirm the editor and save the profile.

Attribute names retain their spelling and case. Use the same spelling on every state that should share a label.

Use the State Device's search, category, and attribute filters to find related states. These filters change the displayed list. In Map to State, **Category** and **Attributes** target selections determine which states an action changes; use its **Impacted states** list to check the selection.

## Create an expression state

An expression state derives its value from other states. For example, `panel_ready` can be defined as:

```text
panel_power and safety_open
```

To create it:

1. Create the referenced states first.
2. Click Add in the State Device and name the new state `panel_ready`.
3. Enable **This state is an expression**.
4. Enter the expression in **Expression**.
5. Click **Test** and check the result or correct the reported expression error.
6. Confirm the editor and save the profile.

Use state names, spaces between operators and operands, and parentheses for grouping. Expressions and state-name references are not case sensitive.

| Operator | Example | When the result is On |
| --- | --- | --- |
| `and` | `panel_power and safety_open` | Both states are On. |
| `or` | `left_trigger or right_trigger` | At least one state is On. |
| `not` | `not inhibit` | The referenced state is Off. |
| `xor` | `left_switch xor right_switch` | Exactly one state is On. |

`not` has the highest precedence, followed by `and`. `or` and `xor` have the same precedence. Add parentheses whenever mixed operators would be unclear, for example:

```text
armed and (left_trigger or right_trigger) and not inhibited
```

Map inputs to the ordinary source states. Use the expression state as a condition or as the input for its own mappings. When a dependency changes, GremlinEx reevaluates the expression.

Keep dependencies flowing from source states to expressions to outputs. Avoid self-references, circular expression references, or mappings that change an earlier state in the same chain.

## Run actions when a state changes

1. Select the state in the State Device tab.
2. Add a container and actions as you would on a button input.
3. Configure the actions for the desired press and release events.
4. Start the profile and change the state through its physical input or the input viewer.

On corresponds to a button press; Off corresponds to a release. For example, a normal [Map to vJoy](../actions/map_to_vjoy_user_guide.md) button mapping can stay pressed while the state is On. A [Play Sound/TTS](../actions/play_sound_user_guide.md) action configured for press only can announce the transition to On.

Setting an ordinary state to a value it already has normally does not create another transition. Use Pulse when you need an On/Off event rather than a stored On value.

Attach shared outputs to one derived state when several physical controls should operate the same command. This gives you one output mapping to maintain.

## Use a state as a condition

Use a state condition when an existing input should work only while a state has a particular value:

1. Open the condition controls for the input's container or action.
2. Add a **State condition**.
3. Select the state.
4. Choose **Pressed** to require On or **Released** to require Off.
5. Test the input with the state in both positions.

Choose an expression state to apply a compound test without adding a separate condition for every contributing input.

For momentary outputs, consider **Apply condition on press only**. It checks the state before starting the output while allowing release events through. Test this by holding the output's source, changing the enabling state, and then releasing the source.

The condition checks a state when the mapped input event arrives. Attach actions to the state itself when the state transition should initiate a command.

## Use the State container

The **State** container puts a state selection directly on a group of actions:

1. Add a State container to the control being conditioned.
2. Select its **State**.
3. Under **Execute when state is**, choose **On/Pressed**, **Off/Released**, or **Any value**.
4. Add the actions to run when that selection matches.

Use an expression state for a compound requirement. For example, choose `panel_ready` and On/Pressed to enable a group of panel commands.

Any value accepts either value of an existing selected state. Keep the selected state explicit so the container's purpose is clear. Test both press and release events when its actions hold outputs.

## Configure automatic state changes

**Autorelease** in the State Editor schedules a later change on that ordinary state:

1. Enable Autorelease.
2. Set **Delay (s)** in seconds.
3. Set **Trigger on** to On, Off, or Any.
4. Set **Set Value** to Off, On, or Toggle.
5. Confirm, then test the initiating transition and the delayed result.

For a temporary On flag, use **Trigger on: On**, **Set Value: Off**, and a delay such as `2.0` seconds. Setting that state On starts its return to Off.

For a delayed On after a release, use Trigger on: Off and Set Value: On. Any with Toggle can create ongoing timed transitions, so choose a single trigger value when you want one delayed change.

The State Editor delay is in **seconds**. The Map to State action's pulse and latch delays are in **milliseconds**. Configure timing in one place for a simple mapping, then add further timing only when needed.

## Make states mutually exclusive

Use **Mutually exclusive** for a group in which turning one ordinary state On turns the selected peers Off:

1. Create the ordinary states in the group, such as `bank_1`, `bank_2`, and `bank_3`.
2. Edit one member and enable Mutually exclusive.
3. Click **Select…** and select the other members. Use the picker's search and category filter to find them.
4. Confirm the selection and the State Editor.
5. Save, start the profile, and turn each member On in turn.

The selected group is applied to every member. Use Map to State **Press (on)** actions to select a bank without toggling it off on a second press.

Mutual exclusion permits all members to be Off; it does not select a replacement when the active member turns Off. Set at most one member's Default State to On, and choose one On default if a bank must be selected at startup.

Use ordinary states as group members. Expression states derive their values from their dependencies and are not selected as exclusive peers. Review the whole group when changing its membership.

## Set the startup values

Choose each ordinary state's Default State in its editor. On profile start, ordinary states initialize from their defaults and expression states are evaluated from their dependencies.

For a physical switch that may already be on when you start the profile, configure its Map to State action with **Hold** and **State on profile start: Input**. This synchronizes the state with the switch position. See [Startup and stop settings](../actions/map_to_state_user_guide.md#startup-and-stop-settings) for the action's synchronization choices.

Test startup with the hardware in both positions. If several mappings write the same state, give them a consistent initialization plan. Save the profile after changing defaults, expressions, or synchronization settings.

## Inspect and test states

Open the **input viewer** and display the states. Ordinary states can be toggled there for manual testing; expression states are displayed from their computed values.

For each mapping:

1. Verify the physical input's pressed/released state.
2. Confirm that its ordinary state follows or toggles as intended.
3. Check any expression that depends on it.
4. Observe the resulting virtual output, sound, or conditioned command.
5. Repeat from a fresh profile start.

Use the viewer's category, attribute, and search filters to focus on the states in the test. Clear the filters if a state appears to be missing. **Sort** on the State Device arranges its list by name.

## Edit or remove states

Open a state's edit control to change its description, category, attributes, expression, or default. Prefer editing an existing state over deleting and recreating it when its mappings should remain attached.

After renaming, check its dependent expressions, action selections, and conditions, then save and reopen the profile to confirm the references.

Before removing a state, remove or replace references in expressions, Map to State actions, state conditions, State containers, and macros. Remove the state using its input-list controls and save the profile. **Clear** on the State Device deletes all states, so use it only when you intend to remove the complete state list.

## Worked examples

### Combine two controls into one output

1. Create `left_trigger` and `right_trigger`, both with an Off default.
2. Map each physical button to its own state using Map to State Hold.
3. Create an expression state named `either_trigger`:

   ```text
   left_trigger or right_trigger
   ```

4. Select `either_trigger` in the State Device and add a normal virtual button mapping.
5. Test each physical button, then hold both and release one at a time.

The virtual button stays pressed while either source is held. Separate source states let the expression track overlapping holds correctly.

### Trigger one state from another

Follow the [Map to State worked example](../actions/map_to_state_user_guide.md#trigger-one-state-from-another) to make a `light_request` state toggle an `aux_lights` state. The example shows where to attach the second action, how to select its target, and how to test both state transitions in the viewer.

### Enable a command only when ready

1. Create `panel_power` and `safety_open`, and map their switches with Hold and startup Input synchronization.
2. Create `panel_ready` with `panel_power and safety_open`.
3. Add a Basic container to a separate command button, then add a normal Hold-style Map to vJoy action targeting an unused virtual button, such as button 5.
4. Open that action's condition controls and add a **State condition**.
5. Select **panel_ready**, choose **Pressed**, and enable **Apply condition on press only** to let the output's release pass through.
6. Save and start the profile. Test the command button with both switches Off, each switch On separately, and both switches On.
7. Confirm that the virtual button activates only when both switches are On.
8. Hold the command button while both switches are On, turn one switch Off, and release the command button. Verify that the virtual output releases.

Turning the switches On makes panel_ready true; pressing the command button then issues the command. To condition a whole group of actions, use a State container with panel_ready and On/Pressed, and test its press/release handling as well.

For a simpler example using one ordinary enabling state, follow [Use a state as a condition](../actions/map_to_state_user_guide.md#use-a-state-as-a-condition).

### Choose one control bank

1. Create `bank_1`, `bank_2`, and `bank_3` in a `banks` category.
2. Set bank_1's default to On and the other defaults to Off.
3. Configure the three states as one mutually exclusive group.
4. Map three selection buttons to the corresponding states using Press (on).
5. Add State containers to the controls whose commands depend on the selected bank.
6. Select the required bank state in each container and choose On/Pressed.

Each selection button activates its bank and clears the other members. Check the selected bank in the viewer before testing its command mappings.
