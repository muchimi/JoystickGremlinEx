# Containers

## What is a container?

A container in GremlinEx is a grouping mechanism that contains one or more actions to execute in a mapping. The container can also apply logic to how the contained actions are executed, and let you define conditions of execution.

Containers do not produce output.  

Containers must have at least one [action](actions.md#actions).

When you add an action to a mapping, it will be placed in a container, and the default container is the basic container.


## Available containers

GremlinEx includes several containers that can be used to solve various mapping challenges.


| Container | Description | Typical Use-Case |
| ----------- | ----------- | ----------- |
| Basic | The basic container is a container for one or more actions.  This is the simplest container.  All actions in GEX have to be in a container, and this is the simplest container that can be used. | This is the default container when adding a new action to an input and the most common.  Note that adding an action to an input automatically puts it in the basic container if no container exists. |
| Button | This container has two sets of actions, one for when a button is pressed, the other for when a button is released. | This container is best used with input that behave like buttons if a different action has to be executed on button press or release. |
| Chain | This container executes actions in the order the appear in stepped mode.  Every input trigger advances one step.  When the last action is executed, it wraps around. This container should not contain a mode change action. | This container is used for example to trigger state changes in sequence.   |
| Delay Trigger | This container executes one or more actions in the future.  The action will execute even on mode change.  Conditions applied to the container are evaluated at the scheduled time.  If the container is retriggered, the clock is reset and the delay starts again. |  This container is best used when combined with conditions, so execute this after several seconds have lapsed unless the condition changed. |
| Double Tap | Similar to the Button container, this adds the ability to detect a rapid double press of the input. | Similar to a mouse double click, this applies to a keyboard or button double pressed quickly. |
| Sequence | This container lets GEX actions to be used as a macro.  All actions will be executed, one after the other in the order they appear.  The container can also randomize these actions and randomize the delay between action executions. This container should not contain a mode change action. | This is the container equivalent of macros, and because actions have more functionality than the action macro, can be used to create very complex macros superseding the capabilities of the macro action. |
| Smart Toggle | This container is used to toggle an output based on the short or long press of the input.  A short press pulses the output.  A long press causes the output to be toggled on. | Used for "sticky" output for keyboard or joystick buttons based on a quick toggle, or a hold function.  This container should not contain a mode change action. |
| Switch | This container is designed to support two way and three way hardware switches. | This container simplifies the mapping of actions to hardware buttons that only trigger in specific positions such as on, but not off.  The container makes it easy to do these mapping without having to use conditions, or to detect input state changes. |
| State | This container is similar to the basic container however only executes the contained actions after checking a profile state (on or off). | This container eliminates the need to apply a state condition to a container and can be used to run differnt groups of actions based on a state, and without using performance intensive mode context switches.  Use one container for each group of actions.  Expression states can be used to combine multiple states if needed if multiple states are involved (for example A and B, A and B and C, A or B, B and not D, etc.).  Referencing an expression state for this container makes this a very powerful way to group actions that should only execute based on multiple states and increases the readability of the profile while making it simpler to create. |
| Tempo | This is a container that performs actions on short press, or long press. | This is a legacy container for compatibiliy with older profiles. |
| TempoEx | This is a container that defines separate actions for short press, long press our double click of the input.  This container does not work for actions that require a release trigger at the onset. | Use this container instead of Tempo although both work pretty much the same. |

## Implementation

Each container in GremlinEx is a Python plugin.




## Sequence Container

This container executes all contained actions in a sequence, and as such is very similar to a macro.  Unlike a macro, the sequence container executes one or more full action per step, which can itself contain a macro for example.  The difference between this container and others is the order of execution is guaranteed in step order, and each action runs in sequence rather than in parallel.

This container allows the sequencing of actions contained in the sequence steps, and has several features not available in the simpler macro action:

- all action types suitable for momentary input can be used, such as OSC.  The sequence container has more action types than the macro action.
- the steps can contain multiple actions.
- steps can themselves contain macros if needed.
- the container supports several "wiggle" modes to randomize the execution of the steps, including a random pick mode where a count of steps can be selected at random, thus using steps as a menu of possible choices to execute on trigger.
- steps can be re-ordered

### Run once mode

In this mode, the sequence is executed once when the input is triggered as determined by the "exec on release" or "exec on press" options.  The sequence will run in the order of the steps.  The sequence cannot be stopped in this mode.  If a retrigger occurs while the sequence is still running, the trigger is ignored.

### Toggle (loop) mode

In this mode, the sequence runs as a loop.  The first trigger, as determined by the "exec on release" or "exec on press" options, enables the loop.  The second trigger stops the loop.  If the "resume at last step" option is enabled, the sequence will start the next loop where it was last stopped.  By default the loop starts at the first step.

### Wiggle mode

When Wiggle mode is enabled, this container can randomize the execution of actions it contains. 

In wiggle mode, the container will continue executing actions while the input is pressed, and stop when the input is released.  This makes it particularly suitable to usage by a state, or when mapped to a physical toggle switch on a hardware input.

The pause between steps can be randomized between a minimum delay, and a maximum delay.

If step randomization is enabled, the next step to execute will also be randomized.  If disabled, the step sequence is observed.

Actions execute in the order they are listed and they can be re-ordered if needed.

The purpose of this container is to add macro-like functionality using mappings instead of the macro action itself.