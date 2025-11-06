
# Gated Axis Interaction guide

## General usage

### Gates

A gate is a point on an axis that defines a "trigger" when the hardware axis crosses it. A gate can be located anywhere on the axis.

Actions added to a gate are seen as button (point in time) triggers from a GremlinEx perspective, so the action list is the same as for a joystick button.

Gates cannot overlap.  The smallest allowed gap between gates is 0.001 on a scale of -1.000 to +1.000.

Up to 20 gates can be defined.  The minimum number of gates is 2.

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
- Right-click the gate or range to bring up a context menu with options.

## Ways to add a new gate

- Move the input joystick to position the caret where you want the new gate, click the record button.  This will add a gate at the current input axis location.
- Right click a range at the desired gate position.
- Add gate button.
- Set the number of gates to a higher number than the current defined gates.

Gates cannot be stacked (meaning, on top of one another).  Only one gate can occupy a specific value.  The smallest gap between two gates is 0.001.

## Ways to move a gate along the axis

- Drag a gate via the mouse to change its position and value.
- The position is more precise by entering the specific value in the gate data repeater.
- You can use the mouse wheel to change the numeric value while hovering over it.  Hold the shift key to increase sensitivity (smaller increments).
- The normalize buttons change all gate values are regular intervals based on the left-most and right-most gate positions, or resets the whole range.
  
## Ways to remove a gate

- Click the delete button on the gate repeater for that gate (and confirm).
- Set the number of gates to a smaller number than the number of gates.  This method is very fast to delete multiple gates at once but does not let you pick which gate is deleted.

## Usage recommendations

- Develop a plan on where you may need gates and how you need the axis split up.  Also plan on the types of triggers you may need, and what happens when the axis is crossing a gate, or within a range.

- End gates can be moved to isolate a specific range of an axis if needed.  You do not need to map the whole range of an axis and this is a quick way to map an axis to a subrange.

- Position your gates and add or move where you need them.  The position can be very accurate using the mouse wheel on the gate's position number box.  Add gates with the record button after moving the axis where you want it, and fine tune with the mouse wheel on the postion numeric repeater for that gate.

- You may need to add gates that do nothing to define additional ranges you do need.  Just because you have a gate doesn't mean that it needs to trigger an action.
  
- Once gates are where you need them and they define the required ranges, then add mappings to them.   Mappings are attached to gates and ranges and if they move around, which they can, your mappings may no longer be correct because they moved along with the gate.

- If you remove a gate, it will delete that gate and its mappings, along with mappings of the impacted ranges also removed as result of the gate removal.
  
- If you need to delete a gate and want to keep the mappings, the easiest is to create a template of the mapping for each gate or range, or just duplicate the whole gated axis into the same container and then copy/paste between them.


