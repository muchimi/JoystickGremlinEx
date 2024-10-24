
# Gated Axis Interaction guide

## General usage

### Gates

A gate is a point on an axis that defines a "trigger" when the hardware axis crosses it. A gate can be located anywhere on the axis.

Actions added to a gate are seen as button (point in time) triggers from a GremlinEx perspective, so the action list is the same as for a joystick button.

### Ranges

The area of the axis between two gates is a range.  A range can "trigger" actions when entered, exited.  Raw axis values while in range can be remapped to a new output range if needed.

Action lists for a range are the same as a Joystick Axis from the GremlinEx perspective.

### Range Modes

When the input axis is in a given range, the range mode determines the output behavior and what happens while the input is in the range.

| Mode | Description |
| ---- | ----------- |
| Normal | The output range is the same as the input range |
| Ranged | The output range can be rescaled to a new min/max range |
| Fixed | The output is constant (fixed) while the input is in the range.  The same value is sent whenever the input changes. |
| Filtered | There is no output sent while the input is in this range |
| Rebased | Similar to Ranged mode, but the range is always set to -1 to +1 |

## Configuring a gate or a range

- Double click a gate or a range to view its configuration and mapping options (dialog).
- Click the configure button for the gate or range repeater.

## Ways to add a new gate

- Move the input joystick to position the caret where you want the new gate, click the record button.  This will add a gate at the current input axis location.
- Right click a range at the desired gate position.
- Add gate button.

Gates cannot be stacked (meaning, on top of one another).  Only one gate can occupy a specific value.  An error will be generated if two gates are in the same value point.

## Ways to move a gate along the axis

- Drag a gate via the mouse to change its position and value.
- The position is more precise by entering the specific value in the gate data repeater.
- You can use the mouse wheel to change the numeric value while hovering over it.  Hold the shift key to increase sensitivity (smaller increments).
- The normalize buttons change all gate values are regular intervals based on the left-most and right-most gate positions, or resets the whole range.
  
## Ways to remove a gate

- Click the delete button on the gate repeater for that gate (and confirm).

## Usage recommendations

Configure you gates first, then add mappings to them.   Mappings are attached to gates and ranges and if they move around, which they can, your mappings may no longer be correct because they moved along with the gate.

For this reason, setup gates before assigning actions to them.
