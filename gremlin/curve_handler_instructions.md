
# Axis Response Curve Interaction guide

## General usage

Use **Curve Type** to choose a response curve. **Cubic Spline** and **Cubic Bezier Spline** let you shape the curve with control points.

Select **Undo** or press **Ctrl+Z** to restore the previous curve. Dragging a point, handle, or deadzone slider counts as one edit.

## Full Axis

Use **Full Axis** for a lever, pedal, or other axis that travels continuously from one end to the other. Set **Inflection point** to **Low**, **Center**, or **High** to place the bend at 25%, 50%, or 75% of the active range. The active range runs between the two end dead zones.

## Cubic spline

A cubic spline is a best fit curve between two or more points on the graph.  The cure will be fitted using a cubic fit method to pass through the points as defined.

By default two points are defined at each corner, defining a straight line.


## Bezier spline

A bezier spline is a curve fitted through control points.  End control points have a single handle, points located along the curve have two handles.

Handles are points anchored to the control point that are used to define the curvature of the spline passing through the control point.

Use **Smooth handles** to align mismatched tangents where segments meet. Existing smooth joins and end handles stay in place. Click a Bézier segment to highlight it, then use **Straighten selected segment** to make it a straight line between its control points. Click an empty part of the graph or press Escape to clear the selection. With no segment selected, **Straighten segments** applies to the whole curve.

Drag a Bézier segment to move its control points and handles. Axis endpoints stay at their existing input positions, and a locked center stays at zero. With **Diagonal Symmetry** enabled, the opposite segment moves in the opposite direction. A segment that mirrors onto itself stays in place. One **Undo** restores the previous curve. Both tools keep the control points in place.

## Adding points

Select a Bézier segment and click **Insert point** to split it without changing its shape. When **Diagonal Symmetry** is enabled, the editor also splits the opposite segment. You can also double-click the graph to place a point manually.


## Moving points and handles


Points and handles (if in bezier mode) can be selected and clicked/dragged with the mouse.  Snap to grid is available via the shift and control keys for fine and coarse snapping.

The control point coordinates (-1.0 to +1.0) in x and y can also be entered manually in the input boxes below the graph.

## Deselect a handle

Press the Escape key to deselect a handle and select its control point instead.

## Cycle through handles or control points

The up and down arrow cycle through control points or handles.  If a handle is selected, it cycles through the handles.  If a control point is selected, it cycles through the control points.


The sequence of control points is determined through the shortest path so it's possible that the sequence is not linear depending on the position of the points and if they cross the line.

## Align in X and Y

The X and Y buttons become available when a handle is selected (Bezier mode).  The buttons match the X (or Y) value of the control point.

Press both the X and Y buttons to place the handle directly on the control point.

## Removing points

The point can be selected (will highlight in red) and you can press the DEL key to delete it.

## Curve values

Open **Curve values...** to sample the response at evenly spaced inputs from -1 to +1. **Sample curve** writes one floating-point output per line, and **Copy text** copies those values to the clipboard. Sampling uses the response curve alone, before deadzones and filtering.

Paste 2 to 501 lines and click **Fit Bézier**. With one **Y** value per line, inputs are spaced evenly from -1 to +1. With two values per line, use **X, Y** pairs separated by a comma or whitespace. X and Y must both be between -1 and +1. If the X values cover only part of the axis, the curve holds the nearest output at either end. The editor fits the samples with editable control points and clears the center lock if the fitted curve shifts neutral. **Undo** restores the previous curve.

## Presets

Presets can be saved or recalled via the save preset and load preset respectively.  When saving a preset, the current configuration will be saved to an xml file of your choosing. 

You can later recall that preset by reloading that xml file into the tool.

The **Bézier presets** row offers **S-curve** and **Logarithmic** shapes. Choose **Low**, **Center**, or **High** to make small movements gentler in that part of the axis. Choose a strength from **Gentle** to **Very aggressive**, then select **Apply** to load editable Bézier points. Both endpoints stay fixed. **Low** and **High** can shift the neutral output on a non-centered curve. Enable **Lock center at zero** to anchor neutral. Centered curves keep neutral at zero. Clearing the lock also turns off **Centered**.

For cubic smoothstep across the whole axis, choose **S-curve**, **Both ends**, and **Very aggressive**. Lower strengths blend the curve with a linear response.

## Dead zones

Dead zones control no response areas at the start, middle and end of the curve.

The leftmost number / slider is the -1 value of the input.
The rightmost number / slider is the +1 value of the input.
The two values in the middle are the center dead zones.

