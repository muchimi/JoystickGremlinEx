
# Axis Response Curve Interaction guide

## General usage

This tool lets you configure a response curve for an axis input.  Two types of response curves are supported.  A cubic spline, and a bezier spline.

The type of curve is selected in the drop down.

## Cubic spline

A cubic spline is a best fit curve between two or more points on the graph.  The cure will be fitted using a cubic fit method to pass through the points as defined.

By default two points are defined at each corner, defining a straight line.


## Bezier spline

A bezier spline is a curve fitted through control points.  End control points have a single handle, points located along the curve have two handles.

Handles are points anchored to the control point that are used to define the curvature of the spline passing through the control point.

Handles always produce a smooth spline.

## Adding points

A new point (cubic or bezier) can be added by double-clicking on the curve at any point.


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

## Presets

Presets can be saved or recalled via the save preset and load preset respectively.  When saving a preset, the current configuration will be saved to an xml file of your choosing. 

You can later recall that preset by reloading that xml file into the tool.

A number of additional presets are also available 1 through 4.

## Dead zones

Dead zones control no response areas at the start, middle and end of the curve.

The leftmost number / slider is the -1 value of the input.
The rightmost number / slider is the +1 value of the input.
The two values in the middle are the center dead zones.

