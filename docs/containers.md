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
| [Sequence](containers/sequence_user_guide.md) | Runs action steps once, in a loop, one per trigger, or with random selection and timing. Each step can contain multiple actions and its own repeat options. Keep mode-changing actions outside the sequence. | Create command sequences, repeating commands, stepped controls, or random command choices using full GremlinEx actions. |
| Smart Toggle | This container is used to toggle an output based on the short or long press of the input.  A short press pulses the output.  A long press causes the output to be toggled on. | Used for "sticky" output for keyboard or joystick buttons based on a quick toggle, or a hold function.  This container should not contain a mode change action. |
| Switch | This container is designed to support two way and three way hardware switches. | This container simplifies the mapping of actions to hardware buttons that only trigger in specific positions such as on, but not off.  The container makes it easy to do these mapping without having to use conditions, or to detect input state changes. |
| [State](devices/state_device_user_guide.md#use-the-state-container) | Groups actions with a built-in state selection. | Enable a group of commands using an ordinary state or a compound expression state. |
| Tempo | This is a container that performs actions on short press, or long press. | This is a legacy container for compatibiliy with older profiles. |
| TempoEx | This is a container that defines separate actions for short press, long press our double click of the input.  This container does not work for actions that require a release trigger at the onset. | Use this container instead of Tempo although both work pretty much the same. |

## Implementation

Each container in GremlinEx is a Python plugin.




## Sequence Container

The Sequence container runs groups of full GremlinEx actions as steps. Each step can contain multiple actions, including macros, with configurable press/release timing and repetition.

It offers five execution modes:

- **Normal (run once)** runs the steps once in order.
- **Toggle** starts a loop on one trigger and stops it on the next.
- **Loop (while pressed)** repeats while the trigger is active.
- **Wiggle (random)** supports random step selection, intervals, and a step-count limit.
- **Step** runs one step per trigger and wraps after the final step.

**Continue on trigger reset** determines whether Normal and Wiggle continue after the source changes state. It is enabled for new containers; disable it when releasing the source should stop the run. Other settings control startup synchronization, resuming a loop, and resetting the Step cursor.

See the [Sequence Container User Guide](containers/sequence_user_guide.md) for setup instructions, timing and repeat options, runtime settings, worked examples, and troubleshooting.
