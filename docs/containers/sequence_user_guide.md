# Sequence Container — User Guide

The **Sequence** container runs groups of GremlinEx actions as a series of steps. Use it for a command sequence, a loop, one step per trigger, or a random choice of commands. Each step can contain one or more actions, including a Macro action.

The container controls when steps receive press and release events. The actions inside each step determine the actual output, such as a keyboard shortcut, a virtual joystick button, an OSC message, or a sound.

## Contents

- [Before you start](#before-you-start)
- [Create your first sequence](#create-your-first-sequence)
- [Add and arrange steps](#add-and-arrange-steps)
- [Choose an execution mode](#choose-an-execution-mode)
  - [Normal: run once](#normal-run-once)
  - [Toggle: start and stop a loop](#toggle-start-and-stop-a-loop)
  - [Loop: run while pressed](#loop-run-while-pressed)
  - [Wiggle: vary the steps and timing](#wiggle-vary-the-steps-and-timing)
  - [Step: advance once per trigger](#step-advance-once-per-trigger)
- [Choose the triggering event](#choose-the-triggering-event)
- [Set step timing and repetition](#set-step-timing-and-repetition)
  - [Sequence timing](#sequence-timing)
  - [Per-step repeat options](#per-step-repeat-options)
- [Set startup and resume behavior](#set-startup-and-resume-behavior)
- [Conditions and action behavior](#conditions-and-action-behavior)
- [Runtime settings](#runtime-settings)
- [Worked examples](#worked-examples)
  - [Send two virtual button commands in order](#send-two-virtual-button-commands-in-order)
  - [Toggle a repeating sequence](#toggle-a-repeating-sequence)
  - [Choose one random command](#choose-one-random-command)
  - [Cycle commands one press at a time](#cycle-commands-one-press-at-a-time)
- [Troubleshooting](#troubleshooting)

## Before you start

Have a profile containing the source input and a way to observe the output. For virtual joystick output, use the input viewer or a joystick monitor before testing in a game.

The container declares support for **joystick buttons and hats**. Configure a hat's virtual-button activation directions so it supplies a pressed/released state. Other input types depend on how the surrounding input configuration presents them; do not assume Sequence can be added directly to a raw axis.

For the first test, use a button, two simple actions, execution on press only, and **Normal (run once)** mode. Keep mode-changing actions outside the sequence: runtime settings can delay a mode change or terminate the running sequence.

## Create your first sequence

1. Select the profile mode and source input.
2. Choose **Sequence** in the **Container** selector and add it.
3. Select an action in the container's action selector and click **Add Step**. Configure its output.
4. Add a second step with another easy-to-observe output.
5. Select **Normal (run once)** under **Execution mode**.
6. Enable **Execute on press**, disable **Execute on release**, and leave **Continue on trigger reset** enabled.
7. Set **Step Autorelease delay (ms)** to `125` and **Step Interval Delay (ms)** to `300` for the initial test.
8. Save and start the profile. Press the source once and observe the two outputs in order.

These timing values are examples. They give the target application time to detect each command and make the step order easy to see.

## Add and arrange steps

A step is an action set, displayed as **Step 1**, **Step 2**, and so on.

- **Add Step** creates a new step containing the selected action.
- Use a step's own action controls to add more actions to that step.
- Use the up, down, top, and bottom controls to change the step order.
- Use the step's delete control to remove it.
- Configure each step's **Repeat Mode** and timing options separately.

Put commands in separate steps when their order or spacing matters. Actions grouped in one step receive the same synthetic press/release cycle; the normal action execution rules still apply within that group.

Recheck repeat counts and timing after reordering or deleting steps. The current implementation stores these options by step position. Empty action sets are omitted from the runnable step list, so give every intended step an action and remove unused empty steps.

## Choose an execution mode

| Execution mode | What starts it | What it runs | What stops it |
| --- | --- | --- | --- |
| Normal (run once) | A selected press or release event. | All steps once, in order. | End of the sequence, or trigger reset if continuation is disabled. |
| Toggle | A selected trigger event. | All steps repeatedly, in order. | The next selected trigger event. |
| Loop (while pressed) | The selected trigger becomes active. | All steps repeatedly, in order. | The trigger resets. With press-only execution, this is the source release. |
| Wiggle (random) | A selected trigger event. | Ordered or randomly selected steps, with optional random timing and a step-count limit. | The count limit, or trigger reset if continuation is disabled. |
| Step | Each selected trigger event. | One step, including that step's repeats. | Completion of that step, or trigger reset. The next trigger advances to the following step. |

Stopping the profile stops any active sequence. Mode changes can also affect execution; see [Runtime settings](#runtime-settings).

### Normal: run once

Normal starts at Step 1 and runs through the list once. Triggers received while the sequence is already running are ignored rather than queued.

**Continue on trigger reset** is enabled for new containers. With press-only execution, this allows a quick tap to start the sequence and releasing the source does not interrupt it. Disable continuation when releasing the source should cancel the remaining steps.

### Toggle: start and stop a loop

The first qualifying trigger starts the loop. The next qualifying trigger stops it. With execution on press only, press once to start and press again to stop; releases do not toggle the loop.

Enable **Resume at last step** to resume from the stored step position on the next activation. Leave it off to restart at Step 1.

### Loop: run while pressed

With **Execute on press** enabled and **Execute on release** disabled, the sequence loops while the source is held and stops on release. Enable **Resume at last step** if the next hold should continue from the stored position.

Use this mode for an ordered repeating sequence controlled by a held button or maintained switch. The container does not expose **Continue on trigger reset** in this mode.

### Wiggle: vary the steps and timing

Wiggle can vary the order, interval, and number of selected steps independently.

| Setting | Effect |
| --- | --- |
| Randomize Steps | Picks a step independently for each selection. A step can be selected again immediately; this is not a shuffle that uses every step once. |
| Random Delay | Chooses the interval between step selections using Min Delay and Max Delay when the bounds differ. |
| Min Delay (ms) / Max Delay (ms) | Bounds for the random interval. |
| Step Interval Delay (ms) | Fixed interval when random delay is off or its bounds are equal. |
| Step Autorelease Delay (ms) | Default time between a step's press and release. |
| Random Step Count | Limits one run to a selected number of step visits. |
| Wiggle Step Count Min / Max | Bounds for the number of step visits in a limited run. |
| Continue on trigger reset | Allows the current run to continue after the source changes state. |
| Resume at last step | Reuses the stored step position when restarting an ordered run. Randomize Steps picks a new random starting step. |

To run only while held, disable **Continue on trigger reset** and use press-only execution. With continuation enabled and no step-count limit, releasing the source does not stop Wiggle; stop the profile to end it.

With **Randomize Steps** off, steps run in their displayed order and wrap to Step 1. With **Random Step Count** off, there is no count-based stop.

For a fixed number of selections, enable Random Step Count and set Min and Max to the same positive value. For example, `3` and `3` select three steps before stopping. Each selected step still applies its own repeat options: one step visit can produce several output pulses, or none when its random repeat count is zero.

In this implementation, unequal Wiggle delay and step-count bounds use an **exclusive maximum**. A count range of `2` to `5` selects 2, 3, or 4 visits. Equal count bounds select that exact count. Equal delay bounds use **Step Interval Delay**, so set that field explicitly when you want a fixed interval.

### Step: advance once per trigger

Step mode runs one step on each qualifying trigger. After the final step, the next trigger wraps to Step 1. Any repeats configured on that step run before it finishes.

**Reset step execution on profile start** resets the current position to Step 1. It is enabled for new containers. When disabled, the current runtime position can be retained across profile stop/start; it is not a saved progress marker for reopening the profile or application.

A new trigger does not queue another step while the current step is still running. With press-only execution, releasing the source can interrupt the active step's remaining repeats. Test complete press/release cycles at the speed you intend to use.

## Choose the triggering event

**Execute on press** and **Execute on release** choose which source events count as active triggers. New containers use press only.

| Selection | Consequence |
| --- | --- |
| Press only | Normal choice for a button: press starts or advances; release resets the trigger. |
| Release only | Source release starts or advances. The next source press is a trigger reset. |
| Both | Both edges qualify. Step can advance twice per physical cycle; Toggle can start on press and stop on release. Loop does not get its usual release reset. |
| Neither | Source events do not start the sequence. |

**Continue on trigger reset** is shown in Normal and Wiggle modes. It suppresses further source state changes while that run is active. It does not enable simultaneous runs of the same container, override profile stop, or change mode-affinity settings.

The trigger settings on an action inside a step are separate from the container's trigger settings. The container can start on source release while still sending a synthetic press followed by a release to each step.

## Set step timing and repetition

All delay fields use **milliseconds**: `1000 ms` is one second.

### Sequence timing

The standard step cycle is:

1. Send a press to the step's actions.
2. Wait for the autorelease delay.
3. Send a release to the step's actions.
4. Repeat the same step if configured, waiting its repeat delay between repetitions.
5. Wait the sequence's interval before the next step.

In Normal mode, the container does not add a trailing interval after the final step. Toggle and Loop apply the interval when wrapping to Step 1. Wiggle applies its interval after each selected step, including the final selection of a count-limited run.

| Setting | New-container default | Use |
| --- | --- | --- |
| Normal Step Interval Delay | `0 ms` | Gap after one step's release and before the next step's press. |
| Normal Step Autorelease delay | `250 ms` | Time between a step's press and release when its Repeat Mode is No Repeat. |
| Wiggle Step Interval Delay | `250 ms` | Fixed gap between selected steps. |
| Wiggle Step Autorelease Delay | `250 ms` | Default press duration for a selected step. |
| Wiggle Random Delay | Enabled; `250` to `5000 ms` | Random gap instead of the fixed Wiggle interval when the bounds differ. |

The standard timing controls are displayed in **Normal** mode. **Toggle**, **Loop**, and **Step** reuse those stored values even though the controls are hidden. Select Normal to adjust them, then switch back to the intended mode. Step uses the autorelease duration and repeat settings; it does not wait an additional interval for another source trigger.

For example, an autorelease delay of `125 ms` and interval of `300 ms` place the second step's press about `425 ms` after the first step's press, plus action execution time. These are scheduled delays, not a guarantee of exact timing in the target application.

### Per-step repeat options

Each step has its own **Repeat Mode**:

| Repeat Mode | Number of press/release cycles per visit |
| --- | --- |
| No Repeat | One. Uses the sequence mode's default timing. |
| Repeat (roundrobin) | Exactly Count cycles of this same step. Count includes the first execution. |
| Repeat (random) | A random number from zero through Count, inclusive. Zero skips the step's normal press/release cycles. |

The repeat modes expose these additional controls:

- **Count**: total fixed count or maximum random count. The editor starts at `2`.
- **Repeat delay (ms)**: gap between one repetition's release and the next repetition's press.
- **Autorelease delay (ms)**: time between each repetition's press and release.
- **Randomize** beside either delay: uses that delay's Min and Max fields. These per-step random bounds include both endpoints.

New per-step repeat and autorelease delays are `250 ms`. Enabling a repeat mode uses those per-step values instead of the sequence's default duration. Keep each Min less than or equal to its Max.

Repeating a step repeats all actions in that step. **Repeat (roundrobin)** does not alternate between different steps. Use separate steps and Toggle or Loop for that behavior.

## Set startup and resume behavior

**State on profile start** offers two choices:

| Choice | Behavior |
| --- | --- |
| Ignore | Waits for a new source event. This is the default. |
| Input | For a joystick button, reads its current state when the profile starts and processes it using the container's trigger settings. |

With Input and press-only execution, a switch already on can start the sequence immediately. With release-only execution, a button already released can trigger startup execution. Hat startup synchronization is not implemented in this container; do not rely on Input to start from a held hat direction.

**Resume at last step** is available in Toggle, Loop, and Wiggle. It resumes from a stored step position, rather than from the middle of a press or repeat delay. It is not progress saved into the profile file, and a profile mode change clears the stored resume position. Random step selection can choose a different step regardless of that position.

In Step mode, use **Reset step execution on profile start** to control the step cursor. After switching execution modes or changing the step list, restart and test the first step to confirm the desired startup behavior.

## Conditions and action behavior

Container conditions determine whether a source event reaches the Sequence container. Step/action conditions and each action's own execution settings also affect the output when a step is visited. A step that produces no output can still consume timing and a step-count visit.

Keep trigger-reset events able to reach a running Loop or cancellable sequence. A condition that allows the initiating press but blocks its release can prevent the expected stop event from reaching the container.

The events sent to steps are synthetic **button press and release** events. Actions should be configured for that behavior. For example, a normal Hold mapping can use the synthetic release, while an explicit Press, Toggle, or timed Pulse action manages its output differently. See the [Map to vJoy guide](../actions/map_to_vjoy_user_guide.md) and [Keyboard Ex guide](../actions/keyboard_ex_user_guide.md) for their output modes.

Sequence controls step dispatch and timing. An action that starts its own background work, such as a macro or sound, may continue after its step has been dispatched. Allow enough time for the intended output and check that action's stop behavior; step order alone does not guarantee that every background effect has finished before the next step begins.

When stopped during an autorelease wait, the container still sends the active step its release event. Normal, Toggle, and Loop also send end-of-sequence release notifications to the steps. Outputs deliberately latched by Press or Toggle actions still need the matching action behavior to clear them.

## Runtime settings

The application's **Runtime Options** affect all Sequence containers:

| Setting | Effect |
| --- | --- |
| Concurrent sequence limit | Maximum number of Sequence runners active at once. `0` means no global limit. A start rejected by the limit is not queued. |
| Mode change aborts running macros/sequences | Allows a mode change immediately rather than waiting for active sequences to finish. |
| Sequence/Macro mode affinity | Stops a running sequence when the runtime profile mode changes. |

Each individual Sequence container can have only one active runner regardless of the global limit. If mode changes wait for sequences to finish, an indefinite Toggle, Loop, or Wiggle run must stop before a waiting mode change can proceed. Keep mode changes outside the sequence and test the chosen runtime settings together.

## Worked examples

### Send two virtual button commands in order

1. Add Sequence to a joystick button and select Normal.
2. Add a Map to vJoy action in Step 1, targeting virtual button 1 with normal Hold behavior.
3. Add another in Step 2, targeting virtual button 2 with Hold behavior.
4. Leave both steps on No Repeat. Set autorelease to `125 ms` and interval to `300 ms`.
5. Use press-only execution with Continue on trigger reset enabled.
6. Start the profile and tap the source once.

Button 1 turns on, releases, and then button 2 turns on and releases. Bind the two virtual buttons in the target application after verifying the order in a monitor.

### Toggle a repeating sequence

1. Configure the two steps above.
2. In Normal mode, set autorelease to `125 ms` and interval to `500 ms`.
3. Switch to Toggle, use press-only execution, and leave Resume at last step off.
4. Start the profile. Press once to repeat the two commands and press again to stop.

The next activation starts at Step 1. Enable Resume at last step if continuing from the stored step position is preferable.

### Choose one random command

1. Create one step per possible command and leave each on No Repeat.
2. Select Wiggle and enable Randomize Steps.
3. Enable Random Step Count and set both Min and Max to `1`.
4. Disable Random Delay and set Step Interval Delay to `0 ms`.
5. Set Step Autorelease Delay to `125 ms`.
6. Use press-only execution and enable Continue on trigger reset so a quick tap can finish the selected command.

Each trigger runs one randomly chosen step and stops. Consecutive triggers may choose the same step.

### Cycle commands one press at a time

1. Add three steps with different outputs and leave each on No Repeat.
2. In Normal mode, set the desired autorelease duration, such as `125 ms`.
3. Select Step and enable Reset step execution on profile start.
4. Use press-only execution, start the profile, and test three presses followed by a fourth.

The first three triggers run Steps 1, 2, and 3. The fourth wraps to Step 1. Test the source's release timing as well, since releasing can shorten the active pulse.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Sequence is unavailable for the selected input | Use a supported button or hat input and check its input-type configuration. |
| Nothing happens | Profile running; correct profile mode; enabled container/actions; trigger selection; conditions; nonempty steps; valid output target. |
| Only the first command runs after a quick tap | Enable Continue on trigger reset in Normal or Wiggle if release should not cancel the run. |
| Wiggle continues after release | Disable Continue on trigger reset for held operation, or use Random Step Count for a bounded run. |
| Toggle starts and stops during one press/release cycle | Select only one trigger edge. |
| Step advances twice | Both Execute on press and Execute on release may be enabled. |
| Rapid triggers are missed | The same container is still running its current step or sequence; triggers are not queued. Review autorelease, repeats, and intervals. |
| Repeated step is skipped occasionally | Repeat (random) can choose zero. Use No Repeat or Repeat (roundrobin) when it must execute. |
| A random command occurs twice in succession | Expected: Randomize Steps selects independently each time. |
| Wiggle never uses the displayed maximum count | Unequal Wiggle count bounds exclude Max. Use equal bounds for an exact count. |
| Equal Wiggle delay bounds do not give the desired delay | Set Step Interval Delay; equal bounds use that fixed interval. |
| Timing controls disappear | Normal timing controls are hidden in Toggle, Loop, and Step. Switch to Normal to edit the stored values. |
| A command activates unexpectedly at startup | Set State on profile start to Ignore, or review Input synchronization and the trigger edge. |
| A mode change waits indefinitely | Stop the active loop and review Mode change aborts running macros/sequences and mode affinity. |
| A sequence does not start while others run | Review Concurrent sequence limit. The log reports `SEQUENCE: exceeded concurrent sequence limit` when a start is rejected. |
| Output stays pressed or background work overlaps | Review the action's Hold/Press/Toggle/Pulse behavior, its release handling, and any independent macro or sound timing. |
| Timing changes after rearranging steps | Review repeat and delay options at each step position and remove empty action sets. |

For diagnosis, start with Normal mode, two simple steps, No Repeat, and visible delays. Verify the source event, then the step output, and then the target application's binding. Add repetition, conditions, and randomization after that test works.
