

# -*- coding: utf-8; -*-

# Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import annotations
import os
from lxml import etree as ElementTree
from PySide6 import QtWidgets, QtCore, QtGui #QtWebEngineWidgets

import gremlin.base_profile
import gremlin.config
import gremlin.config
import gremlin.event_handler
import gremlin.execution_graph
from gremlin.input_types import InputType
import gremlin.joystick_handling
import gremlin.shared_state
import gremlin.macro
from gremlin.ui import ui_common
import gremlin.ui.device_tab
import gremlin.ui.input_item
import gremlin.ui.ui_common
from gremlin.ui.qsliderwidget import QSliderWidget
import gremlin.util
from gremlin.util import *
from gremlin.types import *
import gremlin.clipboard

from enum import Enum, auto
from gremlin.macro_handler import *
import gremlin.util
import gremlin.singleton_decorator
from gremlin.util import InvokeUiMethod
import gremlin.util
from itertools import pairwise

from gremlin.ui.ui_common import DynamicDoubleSpinBox, DualSlider, get_text_width
import enum
from lxml import etree

g_scene_size = 250.0

class CurvePreset(enum.IntEnum):
    ''' preset enums '''
    Bezier1 = 1
    Bezier2 = 2
    Bezier3 = 3
    Bezier4 = 4
    Reset = 5

    @staticmethod
    def to_display(value : CurvePreset) -> str:
        return _curve_preset_string_lookup[value]

_curve_preset_string_lookup = {
    CurvePreset.Bezier1 : "Bezier 1",
    CurvePreset.Bezier2 : "Bezier 2",
    CurvePreset.Bezier3 : "Bezier 3",
    CurvePreset.Bezier4 : "Bezier 4",
    CurvePreset.Reset : "Reset",
}

class DeadzonePreset(enum.IntEnum):
    center_two = 1
    center_five = 2
    center_ten = 3
    end_two = 4
    end_five = 5
    end_ten = 6
    reset = 7

    @staticmethod
    def to_display(value : DeadzonePreset) -> str:
        return _deadzon_preset_string_lookup[value]

_deadzon_preset_string_lookup = {    
    DeadzonePreset.center_two : "Center 2%",
    DeadzonePreset.center_five : "Center 5%",
    DeadzonePreset.center_ten : "Center 10%",
    DeadzonePreset.end_two : "End 2%",
    DeadzonePreset.end_five : "End 5%",
    DeadzonePreset.end_ten : "End 10%",
    DeadzonePreset.reset : "Reset"
}


class CurveType(enum.Enum):
    ''' supported curve types '''
    Cubic = 0
    Bezier = 1

    @staticmethod
    def to_string(value : CurveType) -> str:
        return _curve_type_to_string_lookup[value]
    
    @staticmethod
    def to_enum(value : str) -> CurveType:
        return _curve_type_to_enum_lookup[value]
    
    @staticmethod
    def to_display(value : CurveType) -> str:
        return _curve_type_to_display_name[value]
    

_curve_type_to_string_lookup = {
    CurveType.Cubic : "cubic-spline",
    CurveType.Bezier : "cubic-bezier-spline"
}

_curve_type_to_enum_lookup = {
    "cubic-spline" : CurveType.Cubic,
    "cubic-bezier-spline" : CurveType.Bezier  
}

_curve_type_to_display_name = {
    CurveType.Cubic : "Cubic Spline",
    CurveType.Bezier : "Cubic Bezier Spline"
}

class SymmetryMode(enum.Enum):

    """Symmetry modes for response curves."""

    NoSymmetry = 1
    Diagonal = 2

    @staticmethod
    def to_string(value):
        return _symmetry_mode_to_string[value]
    
    @staticmethod
    def to_enum(value):
        return _symmetry_mode_to_enum[value]

_symmetry_mode_to_string = {
    SymmetryMode.NoSymmetry: "none",
    SymmetryMode.Diagonal: "diagonal"
}

_symmetry_mode_to_enum = {
    "none" : SymmetryMode.NoSymmetry,
    "diagonal" : SymmetryMode.Diagonal
}


class Point2D:

    """Represents a 2D point with support for addition and subtraction."""

    def __init__(self, x : float = 0.0, y : float = 0.0):
        """Creates a new instance.

        :param x the x coordinate
        :param y the y coordinate
        """
        try:
            self.x = float(x)
        except:
            self.x = 0.0
        try:    
            self.y = float(y)
        except:
            self.y = 0.0

    def __add__(self, other):
        return Point2D(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Point2D(self.x - other.x, self.y - other.y)
    
    def __eq__(self, other):
        return gremlin.util.is_close(self.x, other.x) and \
                gremlin.util.is_close(self.y, other.y)
        

    def __str__(self):
        return f"[{self.x:.3f}, {self.y:.3f}]"


class ControlPoint:

    """Represents a single control point in a response curve.

    Each control point has at least a center point but can possibly have
    multiple handles which are used to control the shape of a curve segment.
    Each instance furthermore has a unique identifier used to distinguish
    and track different instances.
    """

    # Identifier of the next ControlPoint instance being created
    next_id = 0

    def __init__(self, model, center, handles=()):
        """Creates a new instance.

        :param model the model the control point is associated with
        :param center the center point of the control point
        :param handles optional list of handles to control curvature
        """
        self._model = model
        self._center = center
        self._handles = [hdl for hdl in handles]
        self._identifier = ControlPoint.next_id
        self._last_modified = time.time()
        ControlPoint.next_id += 1

    @property
    def last_modified(self):
        return self._last_modified

    @property
    def model(self):
        return self._model

    @property
    def center(self):
        """Returns the center point of the control point.

        :return center point of the control point
        """
        return self._center

    def set_center(self, point, emit_model_update=True):
        """Sets the center of the control point, if it is a valid point.

        This method uses the provided model to check if the provided location
        is valid.

        :param point the new center position of the control point
        :param emit_model_update if True a message will be emitted when the
            model changes
        """
        eh = CurveEventHandler()
        if self._model.is_valid_point(point, self.identifier):
            # Update handle locations if any are present
            delta = self.center - point
            for handle in self.handles:
                handle.x -= delta.x
                handle.y -= delta.y

            # Update center position
            self._center = point

            self._last_modified = time.time()
            if emit_model_update:
                self._model.model_updated()
            eh.message.emit(None)
        else:
            
            eh.message.emit(f"Invalid point")

    @property
    def x(self) -> float:
        return self._center.x
    @property
    def y(self) -> float:
        return self._center.y

    @property
    def identifier(self):
        return self._identifier

    @property
    def handles(self):
        return self._handles

    def set_handle(self, index : int, point : Point2D):
        """Sets the location of the specified handle.

        :param index the id of the handle to modify
        :param point the new location of the handle
        """
        if len(self.handles) > index:
            self._last_modified = time.time()
            self.handles[index] = point
            if len(self.handles) == 2 and \
                    isinstance(self._model, CubicBezierSplineModel) and \
                    self._model.handle_symmetry_enabled:
                alt_point = self._center + (self._center - point)
                alt_index = 1 if index == 0 else 0
                self.handles[alt_index] = alt_point
            self._model.model_updated()

            self._last_modified = time.time()
            self._model.model_updated()

    def __eq__(self, other):
        """Compares two control points for identity.

        The unique identifier is used for the comparison.

        :param other the control point to compare with for identity
        :return True of the control points are the same, False otherwise
        """
        return self.identifier == other.identifier


@gremlin.singleton_decorator.SingletonDecorator
class CurveEventHandler(QtCore.QObject):
    ''' handler of events related to the curve handler '''
    message = QtCore.Signal(str) # displays an informational message
    selected_item = QtCore.Signal(object, int) # (item selected, index of item select : int) - the graphics item selected
    next_point = QtCore.Signal() # navigate to the next control point
    prev_point = QtCore.Signal() # navigate to the previous control point
    handle_match_x = QtCore.Signal() # match control point x value
    handle_match_y = QtCore.Signal() # match control point y value
    delete_point = QtCore.Signal() # delete the control point
    value_changed = QtCore.Signal(float) # output value changed (value:float) 


class AbstractCurveModel(QtCore.QObject):

    """Abstract base class for all  curve models."""

    # Signal emitted when model data changes
    content_modified = QtCore.Signal()
    # Signal emitted when points are added or removed
    content_added = QtCore.Signal()

    def __init__(self, action_data, parent=None):
        """Initializes an empty model.
        
        :param profile_data the data of this response curve
        """
        super().__init__(parent)
        self._control_points = []
        self._action_data = action_data
        self._init_from_profile_data()

        self.symmetry_mode = SymmetryMode.NoSymmetry

    def invert(self):
        for cp in self._control_points:
            cp.center.y = -cp.center.y
            for handle in cp.handles:
                handle.y = -handle.y
        self.save_to_profile()
        self.content_modified.emit()

    def model_updated(self):
        # If symmetry is enabled ensure that symmetry is preserved after
        # any changes
        if self.symmetry_mode == SymmetryMode.Diagonal:
            self._enforce_symmetry()
        self.save_to_profile()
        self.content_modified.emit()
        

    def get_curve_function(self):
        """Returns the curve function corresponding to the model.

        :return curve function corresponding to the model
        """
        raise gremlin.error.MissingImplementationError(
            "AbstractCurveModel::get_curve_function not implemented"
        )

    def get_control_points(self):
        """Returns the list of control points.

        :return list of control points
        """
        return self._control_points

    def add_control_point(self, point, handles=()):
        """Adds a new control point to the model.

        :param point the center of the control point
        :param handles list of potential handles
        :return the newly created control point
        """
        self._control_points.append(self._create_control_point(point, handles))

        if self.symmetry_mode == SymmetryMode.Diagonal:
            self._control_points.append(self._create_control_point(
                Point2D(-point.x, -point.y),
                handles
            ))
        self.save_to_profile()
        self.content_added.emit()

    def _create_control_point(self, point, handles=()):
        """Subclass specific implementation to add new control points.

        :param point the center of the control point
        :param handles list of potential handles
        :return the newly created control point
        """
        raise gremlin.error.MissingImplementationError(
            "AbstractCurveModel::_add_control_point not implemented"
        )

    def remove_control_point(self, control_point):
        """Removes the specified control point if it exists in the model.

        :param control_point the control point to remove
        """
        idx = self._control_points.index(control_point)
        if idx:
            del self._control_points[idx]
            self.save_to_profile()
            self.content_added.emit()

    def is_valid_point(self, point, identifier=None):
        """Checks is a point is valid in the model.

        :param point the point to check for validity
        :param identifier the identifier of a control point to ignore
        :return True if valid, False otherwise
        """
        raise gremlin.error.MissingImplementationError(
            "AbstractCurveModel::is_valid_point not implemented"
        )

    def _init_from_profile_data(self):
        """Initializes the control points based on profile data."""
        raise gremlin.error.MissingImplementationError(
            "AbstractCurveModel::_init_from_profile_data not implemented"
        )

    def save_to_profile(self):
        """Ensures that the control point data is properly recorded in
        the profile data."""
        raise gremlin.error.MissingImplementationError(
            "AbstractCurveModel::_update_profile_data not implemented"
        )

    def _enforce_symmetry(self):
        count = len(self._control_points)

        ordered_cp = sorted(self._control_points, key=lambda x: x.center.x)
        for i in range(int(count / 2.0)):
            cp1 = ordered_cp[i]
            cp2 = ordered_cp[-i - 1]
            if cp1.last_modified < cp2.last_modified:
                cp2, cp1 = cp1, cp2

            # cp1 is now the reference which is used to specify the values
            # of cp2
            cp2.set_center(Point2D(-cp1.center.x, -cp1.center.y), False)

            # Update handles
            if len(cp1.handles) == 2:
                cp2.handles[0] = cp2.center - (cp1.handles[1] - cp1.center)
                cp2.handles[1] = cp2.center - (cp1.handles[0] - cp1.center)
            elif len(cp1.handles) == 1:
                cp2.handles[0] = cp2.center - (cp1.handles[0] - cp1.center)

        if count % 2 != 0:
            ordered_cp[int(count / 2)].set_center(Point2D(0, 0), False)

    def set_symmetry_mode(self, mode):
        """Sets the symmetry mode of the curve model.

        :param mode the symmetry mode to use
        """
        self.symmetry_mode = mode
        if mode == SymmetryMode.Diagonal:
            if len(self._control_points) == 2:
                self.add_control_point(Point2D(0.0, 0.0))
                self.content_added.emit()
                self._enforce_symmetry()
        

class CubicSplineModel(AbstractCurveModel):

    """Represents a simple cubic spline model."""

    def __init__(self, profile_data):
        """Creates a new instance."""
        super().__init__(profile_data)

    def get_curve_function(self):
        """Returns the curve function corresponding to the model.

        :return curve function corresponding to the model
        """
        points = []
        for cp in sorted(self._control_points, key=lambda e: e.center.x):
            points.append((cp.center.x, cp.center.y))
        if len(points) < 2:
            return None
        else:
            return gremlin.spline.CubicSpline(points)

    def _create_control_point(self, point, handles=()):
        """Adds a new control point to the model.

        :param point the center of the control point
        :param handles list of potential handles
        :return the newly created control point
        """
        return ControlPoint(self, point)

    def is_valid_point(self, point, identifier=None):
        """Checks is a point is valid in the model.

        :param point the point to check for validity
        :param identifier the identifier of a control point to ignore
        :return True if valid, False otherwise
        """
        is_valid = True
        for other in self._control_points:
            if other.identifier == identifier:
                continue
            elif other.center.x == point.x:
                is_valid = False
        return is_valid

    def _init_from_profile_data(self):
        """Initializes the control points based on profile data."""
        for coord in self._action_data.control_points:
            self._control_points.append(
                ControlPoint(self, Point2D(coord[0], coord[1]))
            )

    def save_to_profile(self):
        """Ensures that the control point data is properly recorded in
        the profile data."""
        self._action_data.mapping_type = CurveType.Cubic
        self._action_data.control_points = []
        for cp in self._control_points:
            self._action_data.control_points.append((cp.center.x, cp.center.y))


class CubicBezierSplineModel(AbstractCurveModel):

    """Represents a cubic bezier spline model."""

    def __init__(self, profile_data):
        """Creates a new model."""
        super().__init__(profile_data)
        self.handle_symmetry_enabled = False

    def get_curve_function(self):
        """Returns the curve function corresponding to the model.

        :return curve function corresponding to the model
        """
        points = []
        sorted_control_points = sorted(
            self._control_points, key=lambda e: e.center.x
        )
        for i, pt in enumerate(sorted_control_points):
            if i == 0:
                points.append((pt.center.x, pt.center.y))
                points.append((pt.handles[0].x, pt.handles[0].y))
            elif i == len(self._control_points) - 1:
                points.append((pt.handles[0].x, pt.handles[0].y))
                points.append((pt.center.x, pt.center.y))
            else:
                points.append((pt.handles[0].x, pt.handles[0].y))
                points.append((pt.center.x, pt.center.y))
                points.append((pt.handles[1].x, pt.handles[1].y))
        if len(points) < 4:
            return None
        else:
            return gremlin.spline.CubicBezierSpline(points)

    def set_handle_symmetry(self, is_enabled):
        """Enables and disables the handle symmetry mode.

        :param is_enabled whether or not the handle symmetry should be enabled
        """
        self.handle_symmetry_enabled = is_enabled

    def _create_control_point(self, point, handles=()):
        """Adds a new control point to the model.

        :param point the center of the control point
        :param handles list of potential handles
        :return the newly created control point
        """
        if len(handles) == 0:
            handles = (
                Point2D(point.x - 0.05, point.y),
                Point2D(point.x + 0.05, point.y)
            )
        return ControlPoint(self, point, handles)

    def is_valid_point(self, point, identifier=None):
        """Checks is a point is valid in the model.

        :param point the point to check for validity
        :param identifier the identifier of a control point to ignore
        :return True if valid, False otherwise
        """
        is_valid = True
        for other in self._control_points:
            if other.identifier == identifier:
                continue
            elif other.center.x == point.x:
                is_valid = False
        return is_valid

    def _init_from_profile_data(self):
        """Initializes the spline with profile data.
        
        expecting 3 points and 3 handles - the points must be left, center and right with x = -1, x = 0, and x = 1
        the second value in the series is the handle coordinate


        point_first handle_first  (x must be -1)
        ...
        point_center point_handle_1 point_handle_2  # point is centered and has two handles
        point_center point_handle_1 point_handle_2
        point_center point_handle_1 point_handle_2
        ...
        point_last handle_last (x must be + 1)
        
        """
        # If the data appears to be invalid insert a valid default
        if len(self._action_data.control_points) < 4:
            self._action_data.control_points = []
            self._action_data.control_points.extend([
                (-1, -1),
                (-0.9, -0.9),
                (0.9, 0.9),
                (1, 1)
            ])
        coordinates = self._action_data.control_points

        self._control_points.append(
            ControlPoint(
                self,
                Point2D(coordinates[0][0], coordinates[0][1]),
                [Point2D(coordinates[1][0], coordinates[1][1])]
            )
        )

        for i in range(3, len(coordinates)-3, 3):
            self._control_points.append(
                ControlPoint(
                    self,
                    Point2D(coordinates[i][0], coordinates[i][1]),
                    [
                        Point2D(coordinates[i-1][0], coordinates[i-1][1]),
                        Point2D(coordinates[i+1][0], coordinates[i+1][1])
                    ]
                )
            )
        self._control_points.append(
            ControlPoint(
                self,
                Point2D(coordinates[-1][0], coordinates[-1][1]),
                [Point2D(coordinates[-2][0], coordinates[-2][1])]
            )
        )

    def save_to_profile(self):
        """Ensure that UI and profile data are in sync."""

        self._action_data.mapping_type = CurveType.Bezier

        control_points = sorted(
            self._control_points,
            key=lambda entry: entry.center.x
        )
        self._action_data.control_points = []

        for cp in control_points:
            if cp.center.x == -1: # left point
                self._action_data.control_points.append(
                    [cp.center.x, cp.center.y]
                )
                self._action_data.control_points.append(
                    [cp.handles[0].x, cp.handles[0].y]
                )
            elif cp.center.x == 1: # right point
                self._action_data.control_points.append(
                    [cp.handles[0].x, cp.handles[0].y]
                )
                self._action_data.control_points.append(
                    [cp.center.x, cp.center.y]
                )
            else: # other points in the middle 
                self._action_data.control_points.append(
                    [cp.handles[0].x, cp.handles[0].y]
                )
                self._action_data.control_points.append(
                    [cp.center.x, cp.center.y]
                )
                self._action_data.control_points.append(
                    [cp.handles[1].x, cp.handles[1].y]
                )
            




class DataPointGraphicsItem(QtWidgets.QGraphicsEllipseItem):

    """UI Item representing a data point center of a control point."""

    def __init__(self, x, y, parent=None):
        """Creates a new instance.

        :param control_point the control point this element visualizes
        :param parent the parent of this widget
        """
        super().__init__(-6, -6, 12, 12, parent)

        self.x = x
        self.y = y

        self.setPos(x, y)
            
        self.setZValue(3)
        color = QtGui.QColor("#f27e0a")
        color.setAlpha(128)
        self.setBrush(QtGui.QBrush(color))


    def update(self, x, y):
        self.x = x
        self.y = y
        self.redraw()


    def redraw(self):
        """Forces a position update of the ui element."""
        self.setPos(self.x, self.y)

class ControlPointGraphicsItem(QtWidgets.QGraphicsEllipseItem):

    """UI Item representing the center of a control point."""

    def __init__(self, control_point, parent=None):
        """Creates a new instance.

        :param control_point the control point this element visualizes
        :param parent the parent of this widget
        """
        super().__init__(-4, -4, 8, 8, parent)
        assert(isinstance(control_point, ControlPoint))

        self.control_point = control_point
        self.parent = parent
        

        self.setPos(
            g_scene_size * self.control_point.center.x,
            -g_scene_size * self.control_point.center.y
        )
        self.setZValue(2)
        self.setBrush(QtGui.QBrush(QtCore.Qt.gray))
        self.handles = []

        if len(self.control_point.handles) > 0:
            for i, handle in enumerate(self.control_point.handles):
                dx = -(self.control_point.center.x - handle.x) * g_scene_size
                dy = -(self.control_point.center.y - handle.y) * g_scene_size
                item = CurveHandleGraphicsItem(i, Point2D(dx, dy), self)
                self.handles.append(item)

        self.eh = gremlin.event_handler.EventListener()

    def redraw(self):
        """Forces a position update of the ui element."""
        self.setPos(
            g_scene_size * self.control_point.center.x,
            -g_scene_size * self.control_point.center.y
        )

    def set_active(self, is_active):
        """Handles changing the selected state of an item

        :param is_active flag indicating if an item is selected or not
        """
        scene = self.scene()
        if scene is not None:
            if is_active:
                self.setBrush(QtGui.QBrush(QtCore.Qt.red))
                if scene.mouseGrabberItem() != self:
                    self.grabMouse()
            else:
                self.setBrush(QtGui.QBrush(QtCore.Qt.gray))
                if scene.mouseGrabberItem() == self:
                    self.ungrabMouse()



    def mouseReleaseEvent(self, evt):
        """Releases the mouse grab when the mouse is released.

        :param evt the mouse even to process
        """
        self.ungrabMouse()
        # self.control_point.model.model_updated()

    def mouseMoveEvent(self, evt):
        """Updates the position of the control point based on mouse
        movements.

        :param evt the mouse event to process
        """
        # Create desired point
        x = gremlin.util.clamp(evt.scenePos().x() / g_scene_size, -1.0, 1.0)
        y = gremlin.util.clamp(-evt.scenePos().y() / g_scene_size, -1.0, 1.0)

        

        # snap to grid if shift key is down
        if self.parent:
            center = self.parent.control_point.center
        else:
            center = None
        if self.eh.get_control_state():
            # coarse snap
            if center:
                x,y = gremlin.util.snap_to_grid(x, y, 25, center.x, center.y)
            else:
                x,y = gremlin.util.snap_to_grid(x, y, 25)
        elif self.eh.get_shifted_state():
            # fine snap
            if center:
                x,y = gremlin.util.snap_to_grid(x, y, 50, center.x, center.y)
            else:
                x,y = gremlin.util.snap_to_grid(x, y, 50)
            
        new_point = Point2D(x,y)

        # Only allow movement along the y axis if the point is on either
        # end of the area
        if abs(self.control_point.center.x) == 1.0:
            new_point.x = self.control_point.center.x

        self.control_point.set_center(new_point)


class CurveHandleGraphicsItem(QtWidgets.QGraphicsRectItem):

    """UI Item representing a handle of a control point."""

    def __init__(self, index : int, point : Point2D, parent : ControlPointGraphicsItem):
        """Creates a new control point handle UI element.

        :param index the id of the handle
        :param point the location of the handle
        :param parent the parent of this widget
        """
        super().__init__(-4, -4, 8, 8, parent)
        self.setPos(point.x, point.y)
        self.setBrush(QtGui.QBrush(QtCore.Qt.gray))
        self.parent : ControlPointGraphicsItem = parent
        self.index = index
        self.line = QtWidgets.QGraphicsLineItem(point.x, point.y, 0, 0, parent)
        self.line.setZValue(0)
        self.setZValue(1)
        


        self.eh = gremlin.event_handler.EventListener()

    def redraw(self):
        """Forces a position update of the ui element."""
        center = self.parent.control_point.center
        point = self.parent.control_point.handles[self.index]
        delta = point - center

        self.setPos(delta.x*g_scene_size, -delta.y*g_scene_size)
        self.line.setLine(delta.x*g_scene_size, -delta.y*g_scene_size, 0, 0)

    def set_active(self, is_active):
        """Handles changing the selected state of an item

        :param is_active flag indicating if an item is selected or not
        """
        if self.scene() is None:
            return

        if is_active:
            self.setBrush(QtGui.QBrush(QtCore.Qt.red))
            if self.scene().mouseGrabberItem() != self:
                self.grabMouse()
        else:
            self.setBrush(QtGui.QBrush(QtCore.Qt.gray))
            if self.scene().mouseGrabberItem() == self:
                self.ungrabMouse()

    def mouseReleaseEvent(self, evt):
        """Releases the mouse grab when the mouse is released.

        :param evt the mouse event to process
        """
        self.ungrabMouse()

    def mouseMoveEvent(self, evt):
        """Updates the position of the control point based on mouse
        movements.

        :param evt the mouse event to process
        """
        # Create desired point
        x = gremlin.util.clamp(evt.scenePos().x() / g_scene_size, -1.0, 1.0)
        y = gremlin.util.clamp(-evt.scenePos().y() / g_scene_size, -1.0, 1.0)
        
        # snap to grid if shift key is down
        if self.parent:
            center = self.parent.control_point.center
        else:
            center = None
        if self.eh.get_control_state():
            # coarse snap
            if center:
                x,y = gremlin.util.snap_to_grid(x, y, 25, center.x, center.y)
            else:
                x,y = gremlin.util.snap_to_grid(x, y, 25)
        elif self.eh.get_shifted_state():
            # fine snap
            if center:
                x,y = gremlin.util.snap_to_grid(x, y, 50, center.x, center.y)
            else:
                x,y = gremlin.util.snap_to_grid(x, y, 50)
            
            
        new_point = Point2D(x,y)

        self.parent.control_point.set_handle(self.index, new_point)


class CurveView(QtWidgets.QGraphicsScene):

    """Visualization of the entire curve editor UI element."""

    def __init__(self, curve_model, point_editor, show_input_axis = False, parent=None):
        """Creates a new instance.

        :param curve_model the model to visualize
        :param point_editor the point editor to use
        :param parent parent of this widget
        """
        super().__init__(parent)
        self.model = curve_model
        self.model.content_modified.connect(self._model_changed)
        self.model.content_added.connect(self._populate_from_model)
        self.point_editor = point_editor
        from gremlin.util import load_image
        
        self.background_image = load_image("curve_grid_ex.svg")

        # Connect editor widget signals
        self.point_editor.x_input.valueChanged.connect(self._editor_update)
        self.point_editor.y_input.valueChanged.connect(self._editor_update)

        self.show_input_axis = show_input_axis
        self.current_item = None
        self.tracker = None
        self.value = 0.0
        self.item_list = [] # map of control points to items
        self._populate_from_model()

        eh = CurveEventHandler()
        eh.next_point.connect(self._next_item)
        eh.prev_point.connect(self._prev_item)
        eh.handle_match_x.connect(self._handle_match_x)
        eh.handle_match_y.connect(self._handle_match_y)
        eh.delete_point.connect(self._delete_point)

        if self.item_list:
            self._select_item(self.item_list[0])

    def _model_changed(self):
        eh = CurveEventHandler()
        self.redraw_scene()
        eh.value_changed.emit(self.value)



    def _dist(self, a, b):
        return ((b.x - a.x)**2 + (b.y - a.y)**2) ** 0.5


    def _shortest_path(self, points):
        ''' sorts the points by the shortest distance '''
        start = points[0]
        pass_by = points
        path = [start]
        pass_by.remove(start)
        while pass_by:
            nearest = min(pass_by, key=lambda x: self._dist(path[-1], x))
            path.append(nearest)
            pass_by.remove(nearest)
        return path

    def _populate_from_model(self):
        """Populates the UI based on content stored in the model."""
        # Remove old curve path and update control points
        self.item_list = []
        for item in self.items():
            if type(item) in [
                ControlPointGraphicsItem,
                CurveHandleGraphicsItem
            ]:
                self.removeItem(item)

        points = [cp for cp in self.model.get_control_points()]
        points.sort(key = lambda p: (p.x, p.y)) # do a pre-sort by x value then y value
        points = self._shortest_path(points)

        for cp in points:
            item = ControlPointGraphicsItem(cp)
            self.item_list.append(item)
            self.addItem(item)

        if self.show_input_axis and self.tracker is None:
            self.tracker = DataPointGraphicsItem(0,0)
            self.addItem(self.tracker)
        
        self.redraw_scene()


    def add_control_point(self, point, handles=()):
        """Adds a new control point to the model and scene.

        :param point the center of the control point
        :param handles list of potential handles
        """
        self.model.add_control_point(point, handles)
        self._populate_from_model()


    def _editor_update(self, value):
        """Callback for changes in the point editor UI.

        :param value the new value entered using the editor UI
        """
        # We can only move control points around using the numerical inputs
        if self.current_item is None:
            return
        new_point = Point2D(
                self.point_editor.x_input.value(),
                self.point_editor.y_input.value()
            )
        if isinstance(self.current_item, CurveHandleGraphicsItem):
            # move a handle
            item : CurveHandleGraphicsItem = self.current_item
            item.parent.control_point.set_handle(item.index, new_point)
        elif isinstance(self.current_item, ControlPointGraphicsItem):
            if abs(self.current_item.control_point.center.x) == 1.0:
                new_point.x = self.current_item.control_point.center.x
            self.current_item.control_point.set_center(new_point)
        self.model.save_to_profile()
        

    @QtCore.Slot()
    def _next_item(self):
        ''' selects the next item '''
        item = self.current_item
        if item and isinstance(item, CurveHandleGraphicsItem):
            
            handle_list = item.parent.handles
            index = item.index
            index -= 1
            self._select_item(handle_list[index])
            return

        index = 0
            
        if not self.current_item is None:
            count = len(self.item_list)
            if self.current_item in self.item_list:
                index = self.item_list.index(self.current_item)
                index += 1
                if index >= count:
                    index = 0
            
        self._select_item(self.item_list[index])

    @QtCore.Slot()
    def _prev_item(self):
        ''' selects the next item '''

        item = self.current_item
        if item and isinstance(item, CurveHandleGraphicsItem):
            
            handle_list = item.parent.handles
            index = item.index
            index += 1
            if index >= len(handle_list):
                index = 0
            self._select_item(handle_list[index])
            return
        
        count = len(self.item_list)
        if self.current_item is None:
            index = count - 1 
        else:
            index = self.item_list.index(self.current_item)
            index -= 1
            if index < 0:
                index = count - 1
        self._select_item(self.item_list[index])       

    @QtCore.Slot()
    def _delete_point(self):   
        item = self.current_item
        if item and isinstance(item, ControlPointGraphicsItem):
            if self.current_item is None:
                return # nothin selected
            
            count = len(self.item_list)
            if count < 3:
                # must have at least two points
                ui_common.MessageBox("At least two points must exist. Unable to remove end points")
                return

            # don't remove the edges
            if abs(self.current_item.control_point.center.x) == 1.0:
                ui_common.MessageBox("Unable to remove end points")
                return
    
        message_box = QtWidgets.QMessageBox()
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message_box.setText("Delete this control point?")
        message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
        gremlin.util.centerDialog(message_box)
        result = message_box.exec()
        if result == QtWidgets.QMessageBox.StandardButton.Ok:
            self._delete_point_confirmed()

    @QtCore.Slot()
    def _delete_point_confirmed(self):         
        ''' deletes the current control point '''
        
        index = self.item_list.index(self.current_item)
        index-=1
        if index < 0:
            index = len(self.item_list)-1
        select_item = self.item_list[index]


        self.model.remove_control_point(self.current_item.control_point)
        self._populate_from_model()
        self._select_item(select_item)
            
            

    @QtCore.Slot()
    def _handle_match_x(self):
        ''' handles the x '''
        item = self.current_item
        if not item or not isinstance(item, CurveHandleGraphicsItem):
            return
        y = gremlin.util.clamp(item.y() / g_scene_size, -1.0, 1.0)
        point = Point2D(item.parent.control_point.x, y)
        
        # if point == item.parent.control_point.center:
        #     point = item.parent.control_point.center + Point2D(0.001,0.0)

        item.parent.control_point.set_handle(item.index, point)
        
        
    @QtCore.Slot()
    def _handle_match_y(self):
        ''' handles the y '''
        item = self.current_item
        if not item or not isinstance(item, CurveHandleGraphicsItem):
            return
        x = gremlin.util.clamp(item.x() / g_scene_size, -1.0, 1.0)
        point = Point2D(x, item.parent.control_point.y)
        # if point == item.parent.control_point.center:
        #     point = item.parent.control_point.center + Point2D(0.0,0.001)
        item.parent.control_point.set_handle(item.index, point)
        

    def _select_item(self, item):
        """Handles drawing of an item being selected.

        :param item the item being selected
        """
        # Ensure we want / can select the provided item
        if isinstance(item, ControlPointGraphicsItem) or \
                isinstance(item, CurveHandleGraphicsItem):
            if self.current_item and item != self.current_item:
                self.current_item.set_active(False)
            self.current_item = item
            self.current_item.set_active(True)
            eh = CurveEventHandler()
            if item in self.item_list:
                index = self.item_list.index(item)
            else:
                index = -1
            eh.selected_item.emit(item, index)
            

    def redraw_scene(self):
        """Updates the scene

        Need to update positions rather then recreating everything, as
        otherwise the state gets lost.
        """
        # Remove old curve path and update control points
        for item in self.items():
            if isinstance(item, QtWidgets.QGraphicsPathItem):
                self.removeItem(item)
            elif type(item) in [
                ControlPointGraphicsItem,
                CurveHandleGraphicsItem,
            ]:
                item.redraw()

        # Redraw response curve
        curve_fn = self.model.get_curve_function()
        if curve_fn:
            path = QtGui.QPainterPath(
                QtCore.QPointF(int(-g_scene_size),int(-g_scene_size*curve_fn(-1)))
            )
            for x in range(-int(g_scene_size), int(g_scene_size+1), 2):
                path.lineTo(x, -g_scene_size * curve_fn(x / g_scene_size))
            self.addPath(path, QtGui.QPen(QtGui.QColor("#8FBC8F"), 4))

            # update the tracking item
            if self.show_input_axis:
                x = self.value
                y = -g_scene_size * curve_fn(x / g_scene_size)
                self.tracker.update(x,y)
                #self.tracker.redraw()
            

        # Update editor widget fields
        if self.current_item:
            if isinstance(self.current_item, ControlPointGraphicsItem):
                self.point_editor.set_values(
                    self.current_item.control_point.center
                )


    def mousePressEvent(self, evt):
        """Informs the model about point selection if a point is clicked.

        :param evt the mouse event to process
        """
        if evt.button() == QtCore.Qt.LeftButton:
            self._select_item(self.itemAt(evt.scenePos(), QtGui.QTransform()))

    def mouseDoubleClickEvent(self, evt):
        """Adds or removes a control point.

        A left double click on empty space creates a new control point.

        :param evt the mouse event to process
        """
        if evt.button() == QtCore.Qt.LeftButton:
            item = self.itemAt(evt.scenePos(), QtGui.QTransform())
            if not isinstance(item, ControlPointGraphicsItem):
                self.add_control_point(Point2D(
                    evt.scenePos().x() / g_scene_size,
                    evt.scenePos().y() / -g_scene_size
                ))

    def keyPressEvent(self, evt):
        """Removes the currently selected control point if the Del
        key is pressed.

        :param evt the keyboard event to process.
        """
        key = evt.key()
        item = self.current_item
        if key == QtCore.Qt.Key_Delete and isinstance(item, ControlPointGraphicsItem):
            # Disallow removing edge points
            if abs(self.current_item.control_point.center.x) == 1.0:
                return

            # Otherwise remove the currently active control point
            self.model.remove_control_point(self.current_item.control_point)
            self._populate_from_model()
            self.current_item = None

        elif key == QtCore.Qt.Key_Escape and isinstance(item, CurveHandleGraphicsItem):
            # return control to the control point
            self._select_item(item.parent)

    def drawBackground(self, painter, rect):
        """Draws the grid background image.

        :param painter the painter object
        :param rect the drawing rectangle
        """
        painter.drawImage(QtCore.QPoint(int(-g_scene_size), int(-g_scene_size)),self.background_image)


class ControlPointEditorWidget(QtWidgets.QWidget):

    """Widgets allowing the control point coordinates to be changed
    via text fields."""

    def __init__(self, parent=None):
        """Creates a new instance.

        :param parent the parent widget
        """
        super().__init__(parent)

        # Generate controls
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.point_label = QtWidgets.QLabel("Control Point")
        self.x_label = QtWidgets.QLabel("X")
        self.y_label = QtWidgets.QLabel("Y")
        self.message = QtWidgets.QLabel("")

        self.data = None 

        self.x_input = ui_common.QFloatLineEdit() # DynamicDoubleSpinBox()
        self.x_input.setRange(-1, 1)
        self.x_input.setDecimals(3)
        self.x_input.setSingleStep(0.1)
        self.x_input.setValue(0)

        self.y_input = ui_common.QFloatLineEdit() #DynamicDoubleSpinBox()
        self.y_input.setRange(-1, 1)
        self.y_input.setDecimals(3)
        self.y_input.setSingleStep(0.1)
        self.y_input.setValue(0)

        self.next_control_point = QtWidgets.QPushButton()
        self.next_control_point.setIcon(gremlin.util.load_icon("fa.caret-up"))
        self.next_control_point.setMaximumWidth(20)
        self.next_control_point.setToolTip("Select next control point")

        self.prev_control_point = QtWidgets.QPushButton()
        self.prev_control_point.setIcon(gremlin.util.load_icon("fa.caret-down"))
        self.prev_control_point.setMaximumWidth(20)
        self.prev_control_point.setToolTip("Select previous control point")

        self.remove_control_point = QtWidgets.QPushButton()
        self.remove_control_point.setIcon(gremlin.util.load_icon("mdi.delete"))
        self.remove_control_point.setMaximumWidth(20)
        self.remove_control_point.setToolTip("Delete Control Point")

        self.handle_match_x = QtWidgets.QPushButton("x")
        self.handle_match_x.setToolTip("Match control X")
        self.handle_match_x.setMaximumWidth(20)

        self.handle_match_y = QtWidgets.QPushButton("y")
        self.handle_match_y.setToolTip("Match control Y")
        self.handle_match_y.setMaximumWidth(20)

        self.next_control_point.clicked.connect(self._next_control_point)
        self.prev_control_point.clicked.connect(self._prev_control_point)
        self.handle_match_x.clicked.connect(self._handle_match_x)
        self.handle_match_y.clicked.connect(self._handle_match_y)
        self.remove_control_point.clicked.connect(self._delete_control_point)

        self.selected_label = QtWidgets.QLabel("")

        self.main_layout.addWidget(self.point_label)
        self.main_layout.addWidget(self.x_label)
        self.main_layout.addWidget(self.x_input)
        self.main_layout.addWidget(self.y_label)
        self.main_layout.addWidget(self.y_input)
        self.main_layout.addWidget(self.prev_control_point)
        self.main_layout.addWidget(self.next_control_point)
        self.main_layout.addWidget(self.remove_control_point)
        self.main_layout.addWidget(self.handle_match_x)
        self.main_layout.addWidget(self.handle_match_y)
        self.main_layout.addWidget(self.selected_label)
        self.main_layout.addStretch()

        eh = CurveEventHandler()
        eh.message.connect(self._update_message)
        eh.selected_item.connect(self._selected_item_changed)

        self._selected_item_changed(None, 0)


    @QtCore.Slot(object)
    def _selected_item_changed(self, item, index):
        msg = ""
        handle_visible = False
        point = None
        if item is None:
            pass
        elif isinstance(item, CurveHandleGraphicsItem):
            self.point_label.setText("Handle")
            handle_visible = True
            point = item.parent.control_point.handles[item.index]
        elif isinstance(item, ControlPointGraphicsItem):
            self.point_label.setText("Control Point")
            msg = f"{[index+1]}"
            point = item.control_point.center

        else:
            self.point_label.setText("???")
        
        self.selected_label.setText(msg)

        self.handle_match_x.setVisible(handle_visible)
        self.handle_match_y.setVisible(handle_visible)

        # update the data 
        if point is not None:
            self.set_values(point)

        
        

    @QtCore.Slot()
    def _next_control_point(self):
        ''' switches to the enxt selected control point'''
        eh = CurveEventHandler()
        eh.next_point.emit()

    @QtCore.Slot()
    def _prev_control_point(self):
        ''' switches to the enxt selected control point'''
        eh = CurveEventHandler()
        eh.prev_point.emit()

    @QtCore.Slot()
    def _handle_match_x(self):
        ''' called when match x button called'''
        eh = CurveEventHandler()
        eh.handle_match_x.emit()

    @QtCore.Slot()
    def _handle_match_y(self):
        ''' called when match x button called'''
        eh = CurveEventHandler()
        eh.handle_match_y.emit()        

    @QtCore.Slot(str)
    def _update_message(self, message):
        if message is None:
            self.message.setText("")    
        else:
            self.message.setText(message)

    @QtCore.Slot()
    def _delete_control_point(self):
        ''' deletes the current control point '''
        if self.data:
            curve_model = self.data
            if curve_model.current_item is None:
                return
            
            if abs(curve_model.current_item.control_point.center.x) == 1.0:
                gremlin.ui.ui_common.MessageBox(prompt="Unable to delete first or last points")
                return
        eh = CurveEventHandler()
        eh.delete_point.emit()

    @QtCore.Slot(str)
    def _update_selected_message(self, message):
        if message is None:
            self.selected_label.setText("")    
        else:
            self.selected_label.setText(message)


    def set_values(self, point):
        """Sets the values in the input fields to those of the provided point.

        :param point the point containing the new field values
        """
        self.x_input.setValue(point.x)
        self.y_input.setValue(point.y)


class DeadzoneWidget(QtWidgets.QWidget):
    ''' deadzone widget '''

    changed = QtCore.Signal() # indicates the data has changed
    

    def __init__(self, profile_data, parent=None):
        """Creates a new instance.

        :param profile_data the data of this response curve
        :param parent the parent widget
        """
        super().__init__(parent)

        self.profile_data = profile_data
        self.main_layout = QtWidgets.QGridLayout(self)
        self.event_lock = False

        # Create the two sliders
        self.left_slider = QSliderWidget()
        self.left_slider.setMarkerVisible(False)
        self.left_slider.desired_height = 24
        self.left_slider.setRange(-1, 0)
        self.right_slider = QSliderWidget()
        self.right_slider.setMarkerVisible(False)
        self.right_slider.setRange(0, 1)
        self.right_slider.desired_height = 24

        # Create spin boxes for the left slider
        self.left_lower = ui_common.QFloatLineEdit()
        self.left_lower.setMinimum(-1.0)
        self.left_lower.setMaximum(0.0)
        self.left_lower.setSingleStep(0.05)
        self.left_lower.setValue(-1)
        self.left_lower.setToolTip("Low (-1.0) deadzone")

        self.left_upper = ui_common.QFloatLineEdit()
        self.left_upper.setMinimum(-1.0)
        self.left_upper.setMaximum(0.0)
        self.left_upper.setSingleStep(0.05)
        self.left_upper.setValue(0)
        self.left_upper.setToolTip("Center left deadzone")

        # Create spin boxes for the right slider
        self.right_lower = ui_common.QFloatLineEdit()
        self.right_lower.setSingleStep(0.05)
        self.right_lower.setMinimum(0.0)
        self.right_lower.setMaximum(1.0)
        self.right_lower.setValue(0)
        self.right_lower.setToolTip("Center right deadzone")

        self.right_upper = ui_common.QFloatLineEdit()
        self.right_lower.setToolTip("High (+1.0) deadzone")
        self.right_upper.setSingleStep(0.05)
        self.right_upper.setMinimum(0.0)
        self.right_upper.setMaximum(1.0)
        self.right_upper.setValue(1)

        # Hook up all the required callbacks
        self.left_slider.valueChanged.connect(self._update_left)
        self.right_slider.valueChanged.connect(self._update_right)
        self.left_lower.valueChanged.connect(
            lambda value: self._update_from_spinner(
                value,
                0,
                self.left_slider
            )
        )
        self.left_upper.valueChanged.connect(
            lambda value: self._update_from_spinner(
                value,
                1,
                self.left_slider
            )
        )
        self.right_lower.valueChanged.connect(
            lambda value: self._update_from_spinner(
                value,
                0,
                self.right_slider
            )
        )
        self.right_upper.valueChanged.connect(
            lambda value: self._update_from_spinner(
                value,
                1,
                self.right_slider
            )
        )

        # Set deadzone positions
        self.set_values(self.profile_data.deadzone)

        # Put everything into the layout
        self.main_layout.addWidget(self.left_slider, 0, 0, 1, 2)
        self.main_layout.addWidget(self.right_slider, 0, 2, 1, 2)
        self.main_layout.addWidget(self.left_lower, 1, 0)
        self.main_layout.addWidget(self.left_upper, 1, 1)
        self.main_layout.addWidget(self.right_lower, 1, 2)
        self.main_layout.addWidget(self.right_upper, 1, 3)


    def set_values(self, values):
        """Sets the deadzone values.

        :param values the new deadzone values
        """
        v1, v2 = values[0], values[1]
        with QtCore.QSignalBlocker(self.left_slider):
            self.left_slider.setValue((v1,v2))
        with QtCore.QSignalBlocker(self.left_lower):
            self.left_lower.setValue(v1)
        with QtCore.QSignalBlocker(self.left_upper):            
            self.left_upper.setValue(v2)

        v1, v2 = values[2], values[3]
        with QtCore.QSignalBlocker(self.right_slider):
            self.right_slider.setValue((v1,v2))
        with QtCore.QSignalBlocker(self.right_lower):
            self.right_lower.setValue(v1)
        with QtCore.QSignalBlocker(self.right_upper):
            self.right_upper.setValue(v2)


    def get_values(self):
        """Returns the current deadzone values.

        :return current deadzone values
        """
        return [
            self.left_lower.value(),
            self.left_upper.value(),
            self.right_lower.value(),
            self.right_upper.value()
        ]

    def _update_left(self, handle, value):
        """Updates the left spin boxes.

        :param handle the handle which was moved
        :param value the new value
        """
        if not self.event_lock:
            self.event_lock = True
            if handle == 0:
                self.left_lower.setValue(value)
                self.profile_data.deadzone[0] = value
            elif handle == 1:
                self.left_upper.setValue(value)
                self.profile_data.deadzone[1] = value

            self.changed.emit()
            self.event_lock = False

    def _update_right(self, handle, value):
        """Updates the right spin boxes.

        :param handle the handle which was moved
        :param value the new value
        """
        if not self.event_lock:
            self.event_lock = True
            if handle == 0:
                self.right_lower.setValue(value)
                self.profile_data.deadzone[2] = value
            elif handle == 1:
                self.right_upper.setValue(value)
                self.profile_data.deadzone[3] = value

            self.changed.emit()
            self.event_lock = False

        

    def _update_from_spinner(self, value, index, widget):
        """Updates the slider position.

        :param value the new value
        :param handle the handle to move
        :param widget which slider widget to update
        """
        with QtCore.QSignalBlocker(widget):
            values = widget.value()
            if values[index] != value:
                widget.setValueIndex(index,value)
                print (f"index {index} set value {value} new values: {widget.value()}")




class AxisCurveWidget(QtWidgets.QWidget):
    ''' response curve standalone widget '''

    def __init__(self, curve_data : AxisCurveData, parent=None):
        """Creates a new instance.

        :param curve_data: the curve configuration data 
        :param parent: the parent widget
        """
        super().__init__(parent=parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.action_data : AxisCurveData = curve_data
        self.is_inverted = False
        self.last_value = 0
        self.curve_model = None
        self._create_ui()
        eh = CurveEventHandler()
        eh.value_changed.connect(self.update_value)

        clipboard = gremlin.clipboard.Clipboard()
        clipboard.clipboard_changed.connect(self._update_clipboard)

    @QtCore.Slot(float)
    def update_value(self, value):
        ''' updates dot on the curve based on the value -1 to +1 '''

        if self.action_data.show_input_axis:
            
        
            ''' draw the current value on the curve '''
            curve_fn = self.curve_model.get_curve_function()
            if curve_fn:
                # get the position of the marker
                curve_value = gremlin.joystick_handling.scale_to_range(value, target_min = -g_scene_size, target_max = g_scene_size)  # value on the curve by pixel x
                x = curve_value
                y = -g_scene_size * curve_fn(x / g_scene_size)

                #print (f"value: {value} cv: {curve_value}  x: {x} y: {y}")

                # tracker only exists when input repeater mode is enabled
                self.curve_scene.tracker.update(x,y)

                self.input_raw_widget.setText(f"{value:0.3f}")
                curved = gremlin.util.clamp(curve_fn(value),-1.0, +1.0)
                self.input_curved_widget.setText(f"{curved:0.3f}")

                self.reapeater_widget.setValue(curved)

        self.last_value = value
        self.curve_scene.value = value

                

    def _cleanup_ui(self):
        ''' cleanup operations '''
        self.action_data = None 


    def _create_ui(self):
        """Creates the required UI elements."""


        self.container_options_widget = QtWidgets.QWidget()
        self.container_options_widget.setContentsMargins(0,0,0,0)
        self.container_options_layout = QtWidgets.QHBoxLayout(self.container_options_widget)
        self.container_options_layout.setContentsMargins(0,0,0,0)

        # Dropdown menu for the different curve types
        self.curve_type_selection = gremlin.ui.ui_common.QComboBox()
        self.curve_type_selection.addItem("Cubic Spline", CurveType.Cubic)
        self.curve_type_selection.addItem("Cubic Bezier Spline", CurveType.Bezier)
        self.curve_type_selection.setCurrentIndex(0)
        self.curve_type_selection.currentIndexChanged.connect(self._curve_type_changed)

        # help button
        help_button = QtWidgets.QPushButton()
        help_icon = gremlin.util.load_icon("mdi.help-circle-outline")
        help_button.setIcon(help_icon)
        help_button.setToolTip("Help")
        help_button.setFlat(True)
        help_button.setStyleSheet("QPushButton { background-color: transparent }")
        help_button.setMaximumWidth(32)
        
        help_button.clicked.connect(self._show_help)        

        # Curve manipulation options
        
        self.container_options_layout.addWidget(QtWidgets.QLabel("Curve Type:"))
        self.container_options_layout.addWidget(self.curve_type_selection)

        

        # Curve inversion
        self.curve_inversion = QtWidgets.QPushButton("Invert")
        self.curve_inversion.clicked.connect(self._invert_curve)
        self.container_options_layout.addWidget(self.curve_inversion)

        # Curve symmetry
        self.curve_symmetry = QtWidgets.QCheckBox("Diagonal Symmetry")
        self.curve_symmetry.setChecked(self.action_data.symmetry_mode == SymmetryMode.Diagonal)
        self.curve_symmetry.clicked.connect(self._curve_symmetry_cb)
        self.container_options_layout.addWidget(self.curve_symmetry)

        # Handle symmetry
        self.handle_symmetry_widget = QtWidgets.QCheckBox("Force smooth curves")
        
        if self.action_data.mapping_type == "cubic-bezier-spline":
            self.handle_symmetry_widget.setChecked(self.curve_model.handle_symmetry_enabled)
            self.handle_symmetry_widget.stateChanged.connect(self._handle_symmetry_cb)
        else:
            self.handle_symmetry_widget.setVisible(False)

        self.container_options_layout.addWidget(self.handle_symmetry_widget)        


        self.container_options_layout.addStretch()

        self.copy_button_widget = QtWidgets.QPushButton()
        icon = gremlin.util.load_icon("button_copy.svg")
        self.copy_button_widget.setIcon(icon)
        self.copy_button_widget.setMaximumWidth(24)
        self.copy_button_widget.setToolTip("Copy curve")
        self.copy_button_widget.clicked.connect(self._copy_curve_cb)
        
        self.paste_button_widget = QtWidgets.QPushButton()
        icon = gremlin.util.load_icon("button_paste.svg")
        self.paste_button_widget.setIcon(icon)
        self.paste_button_widget.setMaximumWidth(24)
        self.paste_button_widget.setToolTip("Paste curve")
        self.paste_button_widget.clicked.connect(self._paste_curve_cb)

        self.container_options_layout.addWidget(self.copy_button_widget)
        self.container_options_layout.addWidget(self.paste_button_widget)
        self.container_options_layout.addWidget(help_button)


        self.container_presets_widget = QtWidgets.QWidget()
        self.container_presets_widget.setContentsMargins(0,0,0,0)
        self.container_presets_layout = QtWidgets.QHBoxLayout(self.container_presets_widget)
        self.container_presets_layout.setContentsMargins(0,0,0,0)
        self.container_presets_layout.addWidget(QtWidgets.QLabel("Presets:"))
        

                
        self.preset_save_button_widget = QtWidgets.QPushButton("Save preset")
        self.preset_save_button_widget.setToolTip("Saves a preset to a file")
        self.preset_save_button_widget.clicked.connect(self._save_preset_cb)
        self.preset_load_button_widget = QtWidgets.QPushButton("Load preset")
        self.preset_load_button_widget.setToolTip("Load preset from a previously saved preset")
        self.preset_load_button_widget.clicked.connect(self._load_preset_cb)


        

        self.container_presets_layout.addWidget(self.preset_save_button_widget)
        self.container_presets_layout.addWidget(self.preset_load_button_widget)

        for preset in CurvePreset:
            button = ui_common.QDataPushButton(CurvePreset.to_display(preset))
            button.data = preset
            button.clicked.connect(self._curve_set_preset_cb)
            self.container_presets_layout.addWidget(button)
        self.container_presets_layout.addStretch()


      
        self.container_control_widget = QtWidgets.QWidget()
        self.container_control_widget.setContentsMargins(0,0,0,0)
        self.container_control_layout = QtWidgets.QHBoxLayout(self.container_control_widget)
        self.container_control_layout.setContentsMargins(0,0,0,0)

        # Create all objects required for the response curve UI
        self.control_point_editor = ControlPointEditorWidget()
        self.control_point_editor.setContentsMargins(0,0,0,0)
        self.container_control_layout.addWidget(self.control_point_editor)        

        width = get_text_width("M") * 8

        self.input_raw_widget = QtWidgets.QLineEdit()
        self.input_raw_widget.setMaximumWidth(width)
        self.input_raw_widget.setReadOnly(True)
        self.input_curved_widget = QtWidgets.QLineEdit()
        self.input_curved_widget.setMaximumWidth(width)
        self.input_curved_widget.setReadOnly(True)

        # Response curve model used
        if self.action_data.mapping_type == CurveType.Cubic:
            self.curve_model = CubicSplineModel(self.action_data)
        elif self.action_data.mapping_type == CurveType.Bezier:
            self.curve_model = CubicBezierSplineModel(self.action_data)
        else:
            raise gremlin.error.ProfileError("Invalid curve type")
        
        
        # mode
        self.curve_model.set_symmetry_mode(self.action_data.symmetry_mode)

        self.container_curve_widget = QtWidgets.QFrame()
        self.container_curve_widget.setStyleSheet('.QFrame{background-color: #ffffff; border-radius: 10px;}')
        self.container_curve_layout = QtWidgets.QHBoxLayout(self.container_curve_widget)

        # Graphical curve editor
        self.curve_scene = CurveView(
            self.curve_model,
            self.control_point_editor,
            self.action_data.show_input_axis
        )

        # Create view displaying the curve scene
        
        self.curve_view = QtWidgets.QGraphicsView(self.curve_scene)
        self._configure_response_curve_view()

        self.control_point_editor.data = self.curve_scene
        

        # Deadzone configuration
        self.container_deadzone_widget = QtWidgets.QWidget()
        self.container_deadzone_widget.setContentsMargins(0,0,0,0)
        self.container_deadzone_layout = QtWidgets.QHBoxLayout(self.container_deadzone_widget)
        self.container_deadzone_layout.setContentsMargins(0,0,0,0)

        self.container_deadzone_layout.addWidget(QtWidgets.QLabel("Deadzone"))
        for preset in DeadzonePreset:
            button = ui_common.QDataPushButton(DeadzonePreset.to_display(preset))
            button.data = preset
            button.clicked.connect(self._deadzone_preset_cb)
            self.container_deadzone_layout.addWidget(button)

        self.container_deadzone_layout.addStretch()
        
        self.container_repeater_widget = QtWidgets.QWidget()
        self.container_repeater_widget.setContentsMargins(0,0,0,0)
        self.container_repeater_layout = QtWidgets.QHBoxLayout(self.container_repeater_widget)
        self.container_repeater_layout.setContentsMargins(0,0,0,0)
        self.reapeater_widget = ui_common.AxisStateWidget(orientation=QtCore.Qt.Orientation.Horizontal)


        self.container_repeater_layout.addWidget(QtWidgets.QLabel("Input:"))
        self.container_repeater_layout.addWidget(self.input_raw_widget)
        self.container_repeater_layout.addWidget(QtWidgets.QLabel("Curved:"))
        self.container_repeater_layout.addWidget(self.input_curved_widget)
        self.container_repeater_layout.addWidget(self.reapeater_widget)
        self.container_repeater_layout.addStretch()

        
        self.deadzone_widget = DeadzoneWidget(self.action_data)
        self.deadzone_widget.changed.connect(self._deadzone_modified_cb)

        # Add all widgets to the layout
        self.main_layout.addWidget(self.container_options_widget)
        self.main_layout.addWidget(self.container_presets_widget)
        self.main_layout.addWidget(self.container_curve_widget)
        self.main_layout.addWidget(self.container_repeater_widget)
        self.main_layout.addWidget(self.container_control_widget)
        self.main_layout.addWidget(self.container_deadzone_widget)
        self.main_layout.addWidget(self.deadzone_widget)

        self._update_ui()
        self._update_clipboard(gremlin.clipboard.Clipboard())

    def _update_ui(self):
        """Populates the UI elements."""

        # Setup correct response curve object
        index = self.curve_type_selection.findData(self.action_data.mapping_type)

        with QtCore.QSignalBlocker(self.curve_type_selection):
            self.curve_type_selection.setCurrentIndex(index)
        
        self.curve_scene.redraw_scene()

        # Set deadzone values
        self.deadzone_widget.set_values(self.action_data.deadzone)

    @QtCore.Slot()
    def _show_help(self):
  
        
    
        dialog = ui_common.MarkdownDialog("Axis Response Curve Instructions")
        w = 600
        h = 400
        geom = self.geometry()
        dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - w/2),
            int(geom.y() + geom.height() / 2 - h/2),
            w,
            h
        )
        if dialog.load("curve_handler_instructions.md"):
            gremlin.util.centerDialog(dialog,w,h)
            dialog.exec()
            return
        else:
            ui_common.MessageBox(prompt ="Unable to locate help file")




    @QtCore.Slot()
    def _save_preset_cb(self):
        ''' save the current curve information to a preset '''
        xml_source, _ = QtWidgets.QFileDialog.getSaveFileName(
            None,
            "Save Preset",
            gremlin.util.userprofile_path(),
            "XML files (*.xml)"
        )

        if xml_source != "":
            try:
            
                if os.path.isfile(xml_source):
                    # blitz it
                    os.unlink(xml_source)
                root = etree.Element("curve_preset")
                #self.curve_model.save_to_profile() # sync the coords
                node = self.action_data._generate_xml()
                root.append(node)
                tree = etree.ElementTree(root)
                tree.write(xml_source, pretty_print=True,xml_declaration=True,encoding="utf-8")
                base_name = os.path.basename(xml_source)
                gremlin.ui.ui_common.MessageBox(prompt = f"Preset saved to {base_name}", is_warning=False)
            except Exception as err:
                gremlin.ui.ui_common.MessageBox(prompt = f"Error saving preset: {err}")


    @QtCore.Slot()
    def _load_preset_cb(self):
        ''' save the current curve information to a preset '''
        xml_source, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Load Preset",
            gremlin.util.userprofile_path(),
            "XML files (*.xml)"
        )

        if xml_source != "":
            try:
                base_name = os.path.basename(xml_source)
                parser = etree.XMLParser(remove_blank_text=True)
                tree = etree.parse(xml_source, parser)            
                root = tree.getroot()
                if root is None or root.tag != "curve_preset":
                    gremlin.ui.ui_common.MessageBox(prompt = f"File {base_name} does not appear to be a valid preset file.")    
                    return
                node = gremlin.util.get_xml_child(root,"response-curve")
                if node is None:
                    gremlin.ui.ui_common.MessageBox(prompt = f"File {base_name} does not appear to be a valid preset file.")    
                    return
                
                self.action_data._parse_xml(node)
                self._change_curve_type(self.action_data.mapping_type, self.action_data.control_points)
                self.action_data.curve_update()
                self._update_ui()
                self.update_value(self.last_value)

            except Exception as err:
                gremlin.ui.ui_common.MessageBox(prompt = f"Error loading preset: {err}")

    def _clipboard_valid(self, clipboard) -> bool:
        ''' true if the clipboard data is valid '''
        data = clipboard.data
        if gremlin.util.is_binary_string(data):
            data = data.decode("utf-8")
        return isinstance(data, str) and "</response-curve>" in data

            
    @QtCore.Slot()
    def _copy_curve_cb(self):
        ''' copies current curve data to the clipboard '''
        node = self.action_data._generate_xml()
        xml = etree.tostring(node)
        clipboard = gremlin.clipboard.Clipboard()
        clipboard.data = xml


    @QtCore.Slot()
    def _paste_curve_cb(self):
        ''' paste curve data from clipboard '''
        clipboard = gremlin.clipboard.Clipboard()
        if self._clipboard_valid(clipboard):
            try:
                xml = clipboard.data
                node = etree.fromstring(xml)
                self.action_data._parse_xml(node)
                self._change_curve_type(self.action_data.mapping_type, self.action_data.control_points)
                self.action_data.curve_update()
                self._update_ui()
                self.update_value(self.last_value)
            except:
                # invalid
                return
            


    def _update_clipboard(self, clipboard):
        ''' updates the state of the clipboard buttons '''
        self.paste_button_widget.setEnabled(self._clipboard_valid(clipboard))
    

    @QtCore.Slot(int)
    def _curve_type_changed(self):
        curve_type = self.curve_type_selection.currentData()
        self._change_curve_type(curve_type)


    
    def _change_curve_type(self, curve_type : CurveType, control_points = None):
        """Changes the type of curve used.

        :param curve_type the name of the new curve type
        """

        # Create new model
        if control_points is None:
            if curve_type == CurveType.Cubic:
                self.action_data.control_points = [(-1.0, -1.0), (1.0, 1.0)]
            elif curve_type == CurveType.Bezier:
                self.action_data.control_points = [(-1.0, -1.0), (-1.0, 0),
                                (-0.08, 0.0), (0.0, 0.0), (0.08, 0.0),
                                (1.0, 0.0), (1.0, 1.0),
                                    ]
        else:
            self.action_data.control_points = control_points
            
        self.action_data.mapping_type = curve_type
        self.curve_model = AxisCurveData.model_map[curve_type](self.action_data)

        # Update curve settings UI
        if self.action_data.mapping_type == CurveType.Cubic:
            self.handle_symmetry_widget.setVisible(False)
        elif self.action_data.mapping_type == CurveType.Bezier:
            self.handle_symmetry_widget.setVisible(True)
            self.handle_symmetry_widget.stateChanged.connect(
                self._handle_symmetry_cb
            )
            
        self.curve_symmetry.setChecked(False)

        # Recreate the UI components
        self.curve_scene = CurveView(
            self.curve_model,
            self.control_point_editor,
            self.action_data.show_input_axis
        )
        self.curve_view = QtWidgets.QGraphicsView(self.curve_scene)
        self._configure_response_curve_view()

    @QtCore.Slot(bool)
    def _curve_symmetry_cb(self, checked):
        if checked:
            self.action_data.symmetry_mode = SymmetryMode.Diagonal
            self.curve_model.set_symmetry_mode(SymmetryMode.Diagonal)
        else:
            self.action_data.symmetry_mode = SymmetryMode.NoSymmetry
            self.curve_model.set_symmetry_mode(SymmetryMode.NoSymmetry)

        self.curve_scene.redraw_scene()

    @QtCore.Slot()
    def _curve_set_preset_cb(self):
        ''' sets the curve points to max bezier '''

        # point_first handle_first  (x must be -1)
        # ...
        # point_handle_1 point_center point_handle_2  # point is centered and has two handles
        # ...
        # point_handle_1 point_center point_handle_2
        # ...
        # handle_last point_last (x must be + 1)

        widget = self.sender()
        preset : CurvePreset = widget.data
        curve_type = CurveType.Bezier
        match preset:
            case CurvePreset.Bezier1:
                # max 10% 
                control_points =  [(-1.0, -1.0), (-1.0, 0),
                                (-0.1, 0.0), (0.0, 0.0), (0.1, 0.0),
                                (1.0, 0.0), (1.0, 1.0),
                                    ]
            case CurvePreset.Bezier2:
                # max 20% 
                control_points =  [(-1.0, -1.0), (-1.0, 0),
                                (-0.2, 0.0), (0.0, 0.0), (0.2, 0.0),
                                (1.0, 0.0), (1.0, 1.0),
                                    ]
            case CurvePreset.Bezier3:
                # 5% start 50%
                control_points =  [(-1.0, -1.0), (-0.5, 0),
                                (-0.05, 0.0), (0.0, 0.0), (0.05, 0.0),
                                (0.5, 0.0), (1.0, 1.0),
                                    ]                
            case CurvePreset.Bezier4:
                # 10% start 50% 
                control_points =  [(-1.0, -1.0), (-0.5, 0),
                                    (-0.1, 0.0), (0.0, 0.0), (0.1, 0.0),
                                    (0.5, 0.0), (1.0, 1.0),
                    ]
            case CurvePreset.Reset:
                # reset to cubic linear
                curve_type = CurveType.Cubic
                control_points =  [(-1.0, -1.0), (1.0, 1.0)]

            case _:
                syslog.error(f"Curve preset: don't know how to handle {preset}")
                return

        self.action_data.symmetry_mode = SymmetryMode.NoSymmetry
        self.action_data.mapping_type = curve_type
        self._change_curve_type(curve_type, control_points)
        self._update_ui()
        self.update_value(self.last_value)

    @QtCore.Slot() 
    def _deadzone_preset_cb(self):
        ''' handles deadzone presets '''
        widget = self.sender()
        preset : DeadzonePreset = widget.data

        dd = self.deadzone_widget
        d_start, d_left, d_right, d_end = dd.get_values()
        
        match preset:
            case DeadzonePreset.center_two :
                d_left = -0.02 * 2
                d_right = 0.02 * 2
            case DeadzonePreset.center_five :
                d_left = -0.05 * 2
                d_right = 0.05 * 2
            case DeadzonePreset.center_ten :
                d_left = -0.1 * 2
                d_right = 0.1 * 2
            case DeadzonePreset.end_two : 
                d_start = -1 + 0.02 * 2
                d_end = 1 - 0.02 * 2
            case DeadzonePreset.end_five :
                d_start = -1 + 0.05 * 2
                d_end = 1 - 0.05 * 2
            case DeadzonePreset.end_ten : 
                d_start = -1 + 0.1 * 2
                d_end = 1 - 0.1 * 2

            case DeadzonePreset.reset : 
                d_start = -1
                d_left = 0
                d_right = 0
                d_end = 1
        
        
        dd.set_values([d_start, d_left, d_right, d_end])

    @QtCore.Slot() 
    def _deadzone_modified_cb(self):
        ''' called when deadzones are modified '''
        self.action_data.curve_update()
        self._update_ui()
        self.update_value(self.last_value)


    def _handle_symmetry_cb(self, state):
        if not isinstance(self.curve_model, CubicBezierSplineModel):
            logging.getLogger("system").error(
                "Handle symmetry callback in non bezier curve attempted."
            )
            return

        self.curve_model.set_handle_symmetry(state == QtCore.Qt.Checked.value)

    def _configure_response_curve_view(self):
        """Initializes the response curve view components."""
        self.curve_view = QtWidgets.QGraphicsView(self.curve_scene)
        self.curve_view.setFixedSize(QtCore.QSize(510, 510))
        self.curve_view.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.curve_view.setSceneRect(QtCore.QRectF(
            -g_scene_size,
            -g_scene_size,
            2*g_scene_size,
            2*g_scene_size
        ))
        gremlin.ui.ui_common.clear_layout(self.container_curve_layout)
        self.container_curve_layout.addStretch()
        self.container_curve_layout.addWidget(self.curve_view)
        self.container_curve_layout.addStretch()

    def _invert_curve(self):
        self.curve_model.invert()


class AxisCurveData():
    ''' holds the data for a curved axis '''   

    # map of curve types to curve models
    model_map = {
        CurveType.Cubic : CubicSplineModel,
        CurveType.Bezier : CubicBezierSplineModel
        }    

    def __init__(self):
        self.deadzone = [-1, 0, 0, 1]
        self.sensitivity = 1.0
        self._mapping_type = CurveType.Cubic
        self.control_points = [(-1.0, -1.0), (1.0, 1.0)]
        self.symmetry_mode = SymmetryMode.NoSymmetry
        self.show_input_axis = gremlin.config.Configuration().show_input_axis
        self.deadzone_fn = None
        self.response_fn = None

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self.profile_start)

    @property
    def mapping_type(self) -> CurveType:
        return self._mapping_type
    @mapping_type.setter
    def mapping_type(self, value : CurveType):
        self._mapping_type = value

    @QtCore.Slot()
    def profile_start(self):
        ''' called on profile start '''
        # setup the curve function for the output
        self.curve_update() 

    def _parse_xml(self, node):
        """Parses the XML corresponding to a response curve.

        :param node the XML node to parse
        """

        if "mode" in node.attrib:
            mode = node.get("mode")
            self.symmetry_mode = SymmetryMode.to_enum(mode)


        self.control_points = []
        for child in node:
            if child.tag == "deadzone":
                self.deadzone = [
                    float(child.get("low")),
                    float(child.get("center-low")),
                    float(child.get("center-high")),
                    float(child.get("high"))
                ]
            elif child.tag == "mapping":
                curve_type = child.get("type")
                self.mapping_type = CurveType.to_enum(curve_type)
                self.control_points = []
                for point in child.iter("control-point"):
                    self.control_points.append((
                        float(point.get("x")),
                        float(point.get("y"))
                    ))


        self.curve_update()


    def _generate_xml(self):
        """Generates a XML node corresponding to this object.

        :return XML node representing the object's data
        """
        node = ElementTree.Element("response-curve")
        node.set("mode", SymmetryMode.to_string(self.symmetry_mode))

        # Response curve mapping
        if len(self.control_points) > 0:
            mapping_node = ElementTree.Element("mapping")
            mapping_node.set("type", CurveType.to_string(self.mapping_type))
            for point in self.control_points:
                cp_node = ElementTree.Element("control-point")
                cp_node.set("x", float_to_xml(point[0]))
                cp_node.set("y", float_to_xml(point[1]))
                mapping_node.append(cp_node)
            node.append(mapping_node)

        # Deadzone settings
        deadzone_node = ElementTree.Element("deadzone")
        deadzone_node.set("low", float_to_xml(self.deadzone[0]))
        deadzone_node.set("center-low", float_to_xml(self.deadzone[1]))
        deadzone_node.set("center-high", float_to_xml(self.deadzone[2]))
        deadzone_node.set("high", float_to_xml(self.deadzone[3]))
        node.append(deadzone_node)

        return node


    def curve_update(self):
        ''' updates the curve params '''
        self.deadzone_fn = lambda value: gremlin.input_devices.deadzone(
            value,
            self.deadzone[0],
            self.deadzone[1],
            self.deadzone[2],
            self.deadzone[3]
        )
        if self.mapping_type == CurveType.Cubic:
            self.response_fn = gremlin.spline.CubicSpline(self.control_points)
        elif self.mapping_type == CurveType.Bezier:
            self.response_fn = \
                gremlin.spline.CubicBezierSpline(self.control_points)
        else:
            raise gremlin.error.GremlinError("Invalid curve type")

    def curve_value(self, value : float, update : bool = False):
        ''' processes an input value -1 to +1 and outputs the curved value based on the current curve model '''
        if update or self.deadzone_fn is None or self.response_fn is None:
            self.curve_update()
        if self.deadzone_fn is not None:
            value = self.deadzone_fn(value)
        if self.response_fn is not None:
            value = self.response_fn(value)
        
        return value
        


class AxisCurveDialog(QtWidgets.QDialog):
    ''' dialog box for curve configuration '''

    def __init__(self, curve_data, parent=None):
        """Creates a new instance.

        :param curve_data: the curve configuration data 
        :param parent: the parent widget
        """
        super().__init__(parent=parent)

        self.action_data = curve_data
        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.widget = AxisCurveWidget(curve_data, self)
        self.main_layout.addWidget(self.widget)

        self.minimumWidth = 700
        self.minimumHeight = 600

    @property
    def curve_update_handler(self):
        return self.widget.update_value
    

    def keyPressEvent(self, event):
        ''' disable escape key to prevent conflict with handle deselect'''
        if event.key() == QtCore.Qt.Key_Escape:
            pass
        else:
            super().keyPressEvent(event)
    

    def closeEvent(self, arg__1):
        return super().closeEvent(arg__1)




        
