
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
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

from __future__ import annotations  # deprecated with python 3.14+
import math
import os
import re
from lxml import etree as ElementTree
from PySide6 import QtWidgets, QtCore, QtGui  # QtWebEngineWidgets
import traceback
import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
import time

import gremlin.joystick_handling
import gremlin.shared_state
from gremlin.ui import ui_common
import gremlin.ui.ui_common

import gremlin.util
from gremlin.util import float_to_xml, safe_format, safe_read

# from gremlin.types import
import gremlin.clipboard

import gremlin.util
import gremlin.singleton_decorator
import gremlin.util


import enum
from lxml import etree
from gremlin.ui.deadzone import DeadzonePreset, DeadzoneWidget
from psygnal import Signal
import gremlin.ui.ui_common

import numpy as np
from shiboken6 import Shiboken

import logging
from gremlin.ui.ui_common import (
    Buttons,
    Color,
    MessageBox,
    QDataLabel,
    QAxisRepeaterProgressbar,
    QDataCheckbox,
    QDataComboBox,
    QDataPushButton,
    QFloatLineEdit,
    QIntLineEdit,
    QRememberDialog,
    clear_layout,
    getHContainer,
    get_text_width,
    MarkdownDialog,
)

syslog = logging.getLogger("system")


g_scene_size = 250.0
_max_curve_samples = 501


class CurvePreset(enum.IntEnum):
    """preset enums"""

    Bezier1 = 1
    Bezier2 = 2
    Bezier3 = 3
    Bezier4 = 4
    Reset = 5

    @staticmethod
    def to_display(value: CurvePreset) -> str:  # noqa: F821
        return _curve_preset_string_lookup[value]


_curve_preset_string_lookup = {
    CurvePreset.Bezier1: "Bezier 1",
    CurvePreset.Bezier2: "Bezier 2",
    CurvePreset.Bezier3: "Bezier 3",
    CurvePreset.Bezier4: "Bezier 4",
    CurvePreset.Reset: "Reset",
}


class BezierPresetShape(enum.Enum):
    Smoothstep = "S-curve"
    Logarithmic = "Logarithmic"


class BezierPresetRange(enum.Enum):
    Low = "Low"
    Center = "Center"
    High = "High"
    BothEnds = "Both ends"


def bezier_preset_points(
    shape: BezierPresetShape, region: BezierPresetRange, strength: float, *, lock_center: bool = False
) -> list[tuple[float, float]]:
    """Build editable Bézier segments with fixed endpoints and optional neutral anchoring."""
    logarithmic = shape == BezierPresetShape.Logarithmic
    log_factor = 15.0
    log_scale = math.log1p(log_factor)

    def ease(value):
        """Return the eased value and slope for a half-axis starting at its soft end."""
        if logarithmic:
            eased = 1.0 - math.log1p(log_factor * (1.0 - value)) / log_scale
            slope = log_factor / ((1.0 + log_factor * (1.0 - value)) * log_scale)
            if lock_center and region != BezierPresetRange.Center:
                # Blend into the linear half with unit slope at neutral.
                distance = 1.0 - value
                slope = 1.0 + distance * (slope - 1.0) - (eased - value)
                eased = value + distance * (eased - value)
            return eased, slope
        if region == BezierPresetRange.Center:
            return value**3, 3.0 * value**2
        return value * value * (2.0 - value), value * (4.0 - 3.0 * value)

    def response(value):
        if region == BezierPresetRange.BothEnds:
            t = (value + 1.0) / 2.0
            eased, slope = 2.0 * t * t * (3.0 - 2.0 * t) - 1.0, 6.0 * t * (1.0 - t)
        elif region == BezierPresetRange.Center:
            eased, slope = ease(abs(value))
            eased = math.copysign(eased, value)
        elif not lock_center:
            # Use the full travel to ease toward the selected end.
            if region == BezierPresetRange.Low:
                eased, slope = ease((value + 1.0) / 2.0)
                eased = 2.0 * eased - 1.0
            else:
                eased, slope = ease((1.0 - value) / 2.0)
                eased = 1.0 - 2.0 * eased
        elif region == BezierPresetRange.Low and value <= 0.0:
            eased, slope = ease(value + 1.0)
            eased -= 1.0
        elif region == BezierPresetRange.High and value >= 0.0:
            eased, slope = ease(1.0 - value)
            eased = 1.0 - eased
        else:
            return value, 1.0
        return value + strength * (eased - value), 1.0 + strength * (slope - 1.0)

    knots = [-1.0, 0.0, 1.0]
    if logarithmic:
        # Additional knots fit the log shape in each curved half.
        if not lock_center or region != BezierPresetRange.High:
            knots[1:1] = [-0.75, -0.5, -0.25]
        if not lock_center or region != BezierPresetRange.Low:
            knots[-1:-1] = [0.25, 0.5, 0.75]

    values, slopes = zip(*(response(knot) for knot in knots))
    return _bezier_points_from_tangents(knots, values, slopes)


def _bezier_points_from_tangents(knots, values, slopes):
    points = [(knots[0], values[0])]
    for index, (left, right) in enumerate(zip(knots, knots[1:])):
        offset = (right - left) / 3.0
        # Match each endpoint's slope with its handle and keep x linear within the segment.
        points.extend([
            (left + offset, values[index] + offset * slopes[index]),
            (right - offset, values[index + 1] - offset * slopes[index + 1]),
            (right, values[index + 1]),
        ])
    return points


class Point2D:
    """Represents a 2D point with support for addition and subtraction."""

    def __init__(self, x: float = 0.0, y: float = 0.0):
        """Creates a new instance.

        :param x the x coordinate
        :param y the y coordinate
        """
        try:
            self.x = float(x)
        except Exception:
            self.x = 0.0
        try:
            self.y = float(y)
        except Exception:
            self.y = 0.0

    def __iter__(self):
        """iterator version"""
        for value in [self.x, self.y]:
            yield value

    def __getitem__(self, item):
        """indexable version"""
        if item == 0:
            return self.x
        if item == 1:
            return self.y
        raise IndexError("Index out of range")

    def __len__(self):
        """size of the iteration"""
        return 2

    def __add__(self, other):
        return Point2D(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Point2D(self.x - other.x, self.y - other.y)

    def __str__(self):
        return f"[{self.x:.3f}, {self.y:.3f}]"

    def __eq__(self, other):
        return gremlin.util.is_close(self.x, other.x) and gremlin.util.is_close(self.y, other.y)

    def __hash__(self):
        return hash((self.x, self.y))


def _subdivide_bezier(left, outgoing, incoming, right, fraction=0.5):
    """Return the two portions of a cubic Bézier segment using de Casteljau's algorithm."""

    def blend(a, b):
        return Point2D(a.x + (b.x - a.x) * fraction, a.y + (b.y - a.y) * fraction)

    left_handle = blend(left, outgoing)
    middle = blend(outgoing, incoming)
    right_handle = blend(incoming, right)
    incoming = blend(left_handle, middle)
    outgoing = blend(middle, right_handle)
    return left, left_handle, incoming, blend(incoming, outgoing), outgoing, right_handle, right


def _parse_curve_samples(text: str) -> list[tuple[float, float]]:
    """Read one Y value or one X,Y pair per nonblank line."""
    lines = [line.strip().removesuffix("\\").strip() for line in text.splitlines() if line.strip()]
    if not 2 <= len(lines) <= _max_curve_samples:
        raise ValueError(f"Paste between 2 and {_max_curve_samples} lines of values.")
    rows = [re.split(r"[\s,]+", line) for line in lines]
    columns = len(rows[0])
    if columns not in (1, 2) or any(len(row) != columns for row in rows):
        raise ValueError("Use one Y value per line or one X,Y pair per line throughout.")

    try:
        samples = [tuple(float(token) for token in row) for row in rows]
    except ValueError as error:
        raise ValueError("Use numbers with a decimal point, such as -0.25.") from error
    if any(not math.isfinite(value) or not -1.0 <= value <= 1.0 for row in samples for value in row):
        raise ValueError("Every X and Y value must be between -1 and +1.")
    if columns == 1:
        return [(-1.0 + 2.0 * index / (len(samples) - 1), row[0]) for index, row in enumerate(samples)]

    samples.sort(key=lambda row: row[0])
    if any(left[0] == right[0] for left, right in zip(samples, samples[1:])):
        raise ValueError("Each X position must be unique.")
    return samples


def _fit_sampled_bezier(samples: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Interpolate the supplied coordinates with shape-preserving cubic Bézier segments."""
    knots, values = map(list, zip(*samples))
    if knots[0] > -1.0:
        knots.insert(0, -1.0)
        values.insert(0, values[0])
    if knots[-1] < 1.0:
        knots.append(1.0)
        values.append(values[-1])

    widths = [right - left for left, right in zip(knots, knots[1:])]
    secants = [(right - left) / width for left, right, width in zip(values, values[1:], widths)]
    slopes = [secants[0]]
    for index, (left, right) in enumerate(zip(secants, secants[1:])):
        if left * right > 0.0:
            # A weighted harmonic mean accounts for uneven spacing.
            left_width, right_width = widths[index:index + 2]
            left_weight = 2.0 * right_width + left_width
            right_weight = right_width + 2.0 * left_width
            slopes.append((left_weight + right_weight) / (left_weight / left + right_weight / right))
        else:
            slopes.append(0.0)
    slopes.append(secants[-1])
    points = _bezier_points_from_tangents(knots, values, slopes)
    if 0.0 not in knots:
        # Add a point at neutral while preserving the fit between its neighboring samples.
        index = next(index for index, knot in enumerate(knots) if knot > 0.0) - 1
        start = 3 * index
        segment = [Point2D(*point) for point in points[start:start + 4]]
        split = _subdivide_bezier(*segment, fraction=-knots[index] / widths[index])
        split[3].x = 0.0
        points[start:start + 4] = [tuple(point) for point in split]
    return points


class CurveType(enum.Enum):
    """supported curve types"""

    Cubic = 0
    Bezier = 1
    FullAxis = 2

    @staticmethod
    def to_string(value: CurveType) -> str:  # noqa: F821
        return _curve_type_to_string_lookup[value]

    @staticmethod
    def to_enum(value: str) -> CurveType:  # noqa: F821
        return _curve_type_to_enum_lookup[value]

    @staticmethod
    def to_display(value: CurveType) -> str:  # noqa: F821
        return _curve_type_to_display_name[value]


_curve_type_to_string_lookup = {
    CurveType.Cubic: "cubic-spline",
    CurveType.Bezier: "cubic-bezier-spline",
    CurveType.FullAxis: "full-axis",
}

_curve_type_to_enum_lookup = {
    "cubic-spline": CurveType.Cubic,
    "cubic-bezier-spline": CurveType.Bezier,
    "full-axis": CurveType.FullAxis,
}

_curve_type_to_display_name = {
    CurveType.Cubic: "Cubic Spline",
    CurveType.Bezier: "Cubic Bezier Spline",
    CurveType.FullAxis: "Full Axis",
}


class FullAxisInflection(enum.Enum):
    """Inflection positions on the normalized axis."""

    Low = -0.5
    Center = 0.0
    High = 0.5


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
    SymmetryMode.Diagonal: "diagonal",
}

_symmetry_mode_to_enum = {
    "none": SymmetryMode.NoSymmetry,
    "diagonal": SymmetryMode.Diagonal,
}


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
        self._last_modified_handle_index = 0  # index of the last modified handle
        ControlPoint.next_id += 1

    @property
    def last_modified(self):
        return self._last_modified

    @property
    def last_modified_handle_index(self):
        return self._last_modified_handle_index

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
        if self._model.is_point_locked(self) and (point.x != self.x or point.y != self.y):
            eh.message.emit("The center point is locked.")
            return
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
            eh.message.emit("Invalid point")

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

    def set_handle(self, index: int, point: Point2D):
        """Sets the location of the specified handle.

        :param index the id of the handle to modify
        :param point the new location of the handle
        """
        if len(self.handles) > index:
            self._last_modified = time.time()
            self.handles[index] = point
            if len(self.handles) == 2 and isinstance(self._model, CubicBezierSplineModel) and self._model.handle_symmetry_enabled:
                alt_point = self._center + (self._center - point)
                alt_index = 1 if index == 0 else 0
                self.handles[alt_index] = alt_point
            self._model.model_updated()

            self._last_modified = time.time()
            self._last_modified_handle_index = index
            self._model.model_updated()

    def __eq__(self, other):
        """Compares two control points for identity.

        The unique identifier is used for the comparison.

        :param other the control point to compare with for identity
        :return True of the control points are the same, False otherwise
        """
        # return  self.identifier == other.identifier
        return gremlin.util.is_close(self.x, other.x) and gremlin.util.is_close(self.y, other.y)

    def __hash__(self):
        return hash(self.identifier)


@gremlin.singleton_decorator.SingletonDecorator
class CurveEventHandler(QtCore.QObject):
    """handler of events related to the curve handler"""

    message = Signal(str)  # displays an informational message
    selected_item = Signal(object, object, int)  # (point_editor, item selected, index of item select : int) - the graphics item selected
    next_point = Signal(object)  # navigate to the next control point (point_editor)
    prev_point = Signal(object)  # navigate to the previous control point (point_editor)
    handle_match_x = Signal(object)  # match control point x value (point_editor)
    handle_match_y = Signal(object)  # match control point y value (point_editor)
    delete_point = Signal(object)  # delete the control point (point_editor)
    value_changed = Signal(float)  # output value changed (point_editor,value:float)


class AbstractCurveModel(QtCore.QObject):
    """Abstract base class for all  curve models."""

    # Signal emitted when model data changes
    content_modified = Signal()
    # Signal emitted when points are added or removed
    content_added = Signal()

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

    def mirror_x(self):
        for control_point in self._control_points:
            control_point.center.x = -control_point.center.x
            for handle in control_point.handles:
                handle.x = -handle.x
            control_point.handles.reverse()
        self._control_points.sort(key=lambda point: point.x)
        self.save_to_profile()
        self.content_added.emit()

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
        raise gremlin.error.MissingImplementationError("AbstractCurveModel::get_curve_function not implemented")

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

        cp = self._create_control_point(point, handles)
        self._control_points.append(cp)

        if self.symmetry_mode == SymmetryMode.Diagonal and (point.x != 0.0 or point.y != 0.0):
            self._control_points.append(self._create_control_point(Point2D(-point.x, -point.y), handles))
        self.save_to_profile()
        self.content_added.emit()

        return cp

    def _create_control_point(self, point, handles=()):
        """Subclass specific implementation to add new control points.

        :param point the center of the control point
        :param handles list of potential handles
        :return the newly created control point
        """
        raise gremlin.error.MissingImplementationError("AbstractCurveModel::_add_control_point not implemented")

    def is_point_locked(self, control_point):
        return False

    def remove_control_point(self, control_point):
        """Removes the specified control point if it exists in the model.

        :param control_point the control point to remove
        """
        idx = self._control_points.index(control_point)
        if idx and not self.is_point_locked(control_point):
            del self._control_points[idx]
            self.save_to_profile()
            self.content_added.emit()

    def is_valid_point(self, point, identifier=None):
        """Checks is a point is valid in the model.

        :param point the point to check for validity
        :param identifier the identifier of a control point to ignore
        :return True if valid, False otherwise
        """
        raise gremlin.error.MissingImplementationError("AbstractCurveModel::is_valid_point not implemented")

    def _init_from_profile_data(self):
        """Initializes the control points based on profile data."""
        raise gremlin.error.MissingImplementationError("AbstractCurveModel::_init_from_profile_data not implemented")

    def save_to_profile(self):
        """Ensures that the control point data is properly recorded in
        the profile data."""
        raise gremlin.error.MissingImplementationError("AbstractCurveModel::_update_profile_data not implemented")

    def _enforce_symmetry(self):
        """enforces symmetry of all points"""
        count = len(self._control_points)

        ordered_cp = sorted(self._control_points, key=lambda x: x.center.x)

        # for index, cp in enumerate(ordered_cp):
        #     print (f"cp[{index}]: {cp.x} {cp.y} handles: {len(cp.handles)}")

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

        # handle the special case of the bezier center point
        ordered_cp = sorted(self._control_points, key=lambda x: x.center.x)
        cp = next((p for p in ordered_cp if p.x == 0.0 and p.y == 0.0), None)
        if cp and len(cp.handles) == 2:
            # which handle is selected
            index = cp.last_modified_handle_index
            h1 = 0
            h2 = 1
            if index == 0:
                h1, h2 = h2, h1
            cp.handles[h1] = cp.center - cp.handles[h2]

    def set_symmetry_mode(self, mode):
        """Sets the symmetry mode of the curve model.

        :param mode the symmetry mode to use
        """
        self.symmetry_mode = mode
        if mode == SymmetryMode.Diagonal:
            if len(self._control_points) == 2:
                # if only two points (the ends) - add a center point '''
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
            self._control_points.append(ControlPoint(self, Point2D(coord[0], coord[1])))

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

    def is_point_locked(self, control_point):
        return control_point.x == 0.0 and control_point.y == 0.0 and self._action_data.center_is_locked

    def anchor_center(self):
        """Make neutral a fixed knot while preserving the ordering of output values."""
        center = next((point for point in self._control_points if point.x == 0.0), None)
        if center is None:
            self.add_control_point(Point2D(0.0, 0.0))
        elif 0.0 < abs(center.y) < 1.0:
            offset = center.y
            for control_point in self._control_points:
                for point in (control_point.center, *control_point.handles):
                    y = gremlin.util.clamp(point.y)
                    point.y = (y - offset) / (1.0 - offset * y)
            self.model_updated()
        elif center.y != 0.0:
            center.set_center(Point2D(0.0, 0.0))

    def get_curve_function(self):
        """Returns the curve function corresponding to the model.

        :return curve function corresponding to the model
        """
        points = []
        sorted_control_points = sorted(self._control_points, key=lambda e: e.center.x)
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

    def move_segment(self, segment_index: int, delta: Point2D) -> Point2D:
        """Move a segment and return the offset allowed by its anchors and neighbors."""
        points = sorted(self._control_points, key=lambda point: point.x)
        if not 0 <= segment_index < len(points) - 1:
            return Point2D()

        indices = (segment_index, segment_index + 1)
        directions = [0] * len(points)
        for index in indices:
            opposite = len(points) - 1 - index
            if self.symmetry_mode == SymmetryMode.Diagonal:
                if opposite in indices:
                    # A shared center or a segment mirrored onto itself cannot translate.
                    continue
                directions[opposite] = -1
            directions[index] = 1

        y_directions = [0 if self.is_point_locked(point) else direction for point, direction in zip(points, directions)]
        x_directions = [0 if abs(point.x) == 1.0 else direction for point, direction in zip(points, y_directions)]

        x_min, x_max = -2.0, 2.0
        for index, (left, right) in enumerate(zip(points, points[1:])):
            difference = x_directions[index + 1] - x_directions[index]
            if difference:
                # Keep knots ordered and avoid pushing a handle past a neighboring knot.
                gap = max(0.0, min(right.x - left.x - 0.001, right.x - left.handles[-1].x, right.handles[0].x - left.x))
                if difference > 0:
                    x_min = max(x_min, -gap / difference)
                else:
                    x_max = min(x_max, -gap / difference)

        y_min, y_max = -2.0, 2.0
        for point, direction in zip(points, y_directions):
            if direction:
                for coordinate in (point.center, *point.handles):
                    height = coordinate.y * direction
                    y_min = max(y_min, min(0.0, -1.0 - height))
                    y_max = min(y_max, max(0.0, 1.0 - height))

        dx = gremlin.util.clamp(delta.x, x_min, x_max) if any(x_directions) else 0.0
        dy = gremlin.util.clamp(delta.y, y_min, y_max) if any(y_directions) else 0.0
        if dx or dy:
            for point, horizontal, vertical in zip(points, x_directions, y_directions):
                for coordinate in (point.center, *point.handles):
                    coordinate.x += dx * horizontal
                    coordinate.y += dy * vertical
            self.save_to_profile()
            self._action_data.curve_update()
            self.content_modified.emit()
        return Point2D(dx, dy)

    def split_segment(self, segment_index: int) -> ControlPoint | None:
        """Subdivide a Bézier segment at t=0.5 without changing its shape."""
        points = sorted(self._control_points, key=lambda point: point.x)
        if not 0 <= segment_index < len(points) - 1:
            return None
        indices = [segment_index]
        if self.symmetry_mode == SymmetryMode.Diagonal:
            mirrored_index = len(points) - 2 - segment_index
            if mirrored_index != segment_index:
                indices.append(mirrored_index)

        splits = []
        for index in indices:
            left, right = points[index:index + 2]
            _, left_handle, incoming, center, outgoing, right_handle, _ = _subdivide_bezier(
                left.center, left.handles[-1], right.handles[0], right.center
            )
            if not left.x < center.x < right.x:
                return None
            point = self._create_control_point(center, (incoming, outgoing))
            splits.append((left, left_handle, point, right_handle, right))

        for left, left_handle, point, right_handle, right in splits:
            left.handles[-1] = left_handle
            right.handles[0] = right_handle
            self._control_points.append(point)
        self.save_to_profile()
        self._action_data.curve_update()
        self.content_added.emit()
        return splits[0][2]

    def adjust_handles(self, *, smooth: bool, segment_index: int | None = None):
        """Align mismatched joins or straighten the requested spans between control points."""
        points = sorted(self._control_points, key=lambda point: point.x)
        if len(points) < 2 or any(left.x == right.x for left, right in zip(points, points[1:])):
            return
        if smooth:
            if not self._smooth_handle_joins(points):
                return
        else:
            if segment_index is not None:
                if not 0 <= segment_index < len(points) - 1:
                    return
                points = points[segment_index:segment_index + 2]
            for left, right in zip(points, points[1:]):
                offset = Point2D((right.x - left.x) / 3.0, (right.y - left.y) / 3.0)
                left.handles[-1] = left.center + offset
                right.handles[0] = right.center - offset

        self.save_to_profile()
        self._action_data.curve_update()
        self.content_modified.emit()

    def _smooth_handle_joins(self, points):
        """Blend the existing tangent directions at interior joins."""
        changed = False
        for previous, point, following in zip(points, points[1:], points[2:]):
            incoming = point.center - point.handles[0]
            outgoing = point.handles[1] - point.center
            incoming_length = math.hypot(incoming.x, incoming.y)
            outgoing_length = math.hypot(outgoing.x, outgoing.y)
            # Preserve collapsed handles and skip handles that loop back along the input axis.
            if not incoming_length or not outgoing_length or incoming.x < 0 or outgoing.x < 0:
                continue

            incoming_angle = math.atan2(incoming.y, incoming.x)
            outgoing_angle = math.atan2(outgoing.y, outgoing.x)
            if math.isclose(incoming_angle, outgoing_angle, abs_tol=1e-10):
                continue

            angle = (incoming_angle + outgoing_angle) / 2.0
            if (point.y - previous.y) * (following.y - point.y) <= 0.0:
                # A flat span or a local extremum needs a horizontal tangent.
                angle = 0.0
            dx, dy = math.cos(angle), math.sin(angle)
            for index, length, limit, direction in (
                (0, incoming_length, point.x - previous.x, -1.0),
                (1, outgoing_length, following.x - point.x, 1.0),
            ):
                # Keep each handle in its own span if rotation would carry it past the next knot.
                if dx * length > limit:
                    length = limit / dx
                point.handles[index] = point.center + Point2D(direction * dx * length, direction * dy * length)
            changed = True
        return changed

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
                Point2D(point.x + 0.05, point.y),
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
            self._action_data.control_points.extend([(-1, -1), (-0.9, -0.9), (0.9, 0.9), (1, 1)])
        coordinates = self._action_data.control_points

        self._control_points.append(
            ControlPoint(
                self,
                Point2D(coordinates[0][0], coordinates[0][1]),
                [Point2D(coordinates[1][0], coordinates[1][1])],
            )
        )

        for i in range(3, len(coordinates) - 3, 3):
            self._control_points.append(
                ControlPoint(
                    self,
                    Point2D(coordinates[i][0], coordinates[i][1]),
                    [
                        Point2D(coordinates[i - 1][0], coordinates[i - 1][1]),
                        Point2D(coordinates[i + 1][0], coordinates[i + 1][1]),
                    ],
                )
            )
        self._control_points.append(
            ControlPoint(
                self,
                Point2D(coordinates[-1][0], coordinates[-1][1]),
                [Point2D(coordinates[-2][0], coordinates[-2][1])],
            )
        )

    def save_to_profile(self):
        """Ensure that UI and profile data are in sync."""

        self._action_data.mapping_type = CurveType.Bezier

        control_points = sorted(self._control_points, key=lambda entry: entry.center.x)
        self._action_data.control_points = []

        for cp in control_points:
            if cp.center.x == -1:  # left point
                self._action_data.control_points.append([cp.center.x, cp.center.y])
                self._action_data.control_points.append([cp.handles[0].x, cp.handles[0].y])
            elif cp.center.x == 1:  # right point
                self._action_data.control_points.append([cp.handles[0].x, cp.handles[0].y])
                self._action_data.control_points.append([cp.center.x, cp.center.y])
            else:  # other points in the middle
                self._action_data.control_points.append([cp.handles[0].x, cp.handles[0].y])
                self._action_data.control_points.append([cp.center.x, cp.center.y])
                self._action_data.control_points.append([cp.handles[1].x, cp.handles[1].y])


class FullAxisCurveModel(AbstractCurveModel):
    """Displays a generated curve without editable control points."""

    def _init_from_profile_data(self):
        pass

    def get_curve_function(self):
        return self._action_data.full_axis_curve


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
        gremlin.util.InvokeUiMethod(self._redraw_ui)  # ensure on UI thread

    def _redraw_ui(self):
        """Forces a position update of the ui element."""
        if not Shiboken.isValid(self):
            return
        self.setPos(self.x, self.y)


class ControlPointGraphicsItem(QtWidgets.QGraphicsEllipseItem):
    """UI Item representing the center of a control point."""

    def __init__(self, control_point, parent=None):
        """Creates a new instance.

        :param control_point the control point this element visualizes
        :param parent the parent of this widget
        """
        super().__init__(-4, -4, 8, 8, parent)
        assert isinstance(control_point, ControlPoint)

        self.control_point = control_point
        self.parent = parent

        self.setPos(
            g_scene_size * self.control_point.center.x,
            -g_scene_size * self.control_point.center.y,
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
        gremlin.util.InvokeUiMethod(self._redraw_ui)  # ensure on UI thread

    def _redraw_ui(self):
        """Forces a position update of the ui element."""
        if not Shiboken.isValid(self):
            return
        self.setPos(
            g_scene_size * self.control_point.center.x,
            -g_scene_size * self.control_point.center.y,
        )

    def set_active(self, is_active):
        """Handles changing the selected state of an item

        :param is_active flag indicating if an item is selected or not
        """
        scene = self.scene()
        if scene is not None:
            self.setBrush(QtGui.QBrush(QtCore.Qt.red if is_active else QtCore.Qt.gray))
            if not is_active and scene.mouseGrabberItem() == self:
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
                x, y = gremlin.util.snap_to_grid(x, y, 25, center.x, center.y)
            else:
                x, y = gremlin.util.snap_to_grid(x, y, 25)
        elif self.eh.get_shifted_state():
            # fine snap
            if center:
                x, y = gremlin.util.snap_to_grid(x, y, 50, center.x, center.y)
            else:
                x, y = gremlin.util.snap_to_grid(x, y, 50)

        new_point = Point2D(x, y)

        # Only allow movement along the y axis if the point is on either
        # end of the area
        if abs(self.control_point.center.x) == 1.0:
            new_point.x = self.control_point.center.x

        self.control_point.set_center(new_point)


class CurveHandleGraphicsItem(QtWidgets.QGraphicsRectItem):
    """UI Item representing a handle of a control point."""

    def __init__(self, index: int, point: Point2D, parent: ControlPointGraphicsItem):
        """Creates a new control point handle UI element.

        :param index the id of the handle
        :param point the location of the handle
        :param parent the parent of this widget
        """
        super().__init__(-4, -4, 8, 8, parent)
        self.setPos(point.x, point.y)
        self.setBrush(QtGui.QBrush(QtCore.Qt.gray))
        self.parent: ControlPointGraphicsItem = parent
        self.index = index
        self.line = QtWidgets.QGraphicsLineItem(point.x, point.y, 0, 0, parent)
        self.line.setZValue(0)
        self.setZValue(1)

        self.eh = gremlin.event_handler.EventListener()

    def redraw(self):
        gremlin.util.InvokeUiMethod(self._redraw_ui)  # ensure on UI thread

    def _redraw_ui(self):
        """Forces a position update of the ui element."""
        if not Shiboken.isValid(self):
            return
        center = self.parent.control_point.center
        point = self.parent.control_point.handles[self.index]
        delta = point - center

        self.setPos(delta.x * g_scene_size, -delta.y * g_scene_size)
        self.line.setLine(delta.x * g_scene_size, -delta.y * g_scene_size, 0, 0)

    def set_active(self, is_active):
        """Handles changing the selected state of an item

        :param is_active flag indicating if an item is selected or not
        """
        if self.scene() is None:
            return

        self.setBrush(QtGui.QBrush(QtCore.Qt.red if is_active else QtCore.Qt.gray))
        if not is_active and self.scene().mouseGrabberItem() == self:
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
                x, y = gremlin.util.snap_to_grid(x, y, 25, center.x, center.y)
            else:
                x, y = gremlin.util.snap_to_grid(x, y, 25)
        elif self.eh.get_shifted_state():
            # fine snap
            if center:
                x, y = gremlin.util.snap_to_grid(x, y, 50, center.x, center.y)
            else:
                x, y = gremlin.util.snap_to_grid(x, y, 50)

        new_point = Point2D(x, y)

        self.parent.control_point.set_handle(self.index, new_point)


class CurveGraphicsView(QtWidgets.QGraphicsView):
    """Fit the logical curve scene into the viewport without distorting it."""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        # Keep scrollbars from changing the viewport while fitting it.
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        # Include the tracker/point radii and their outlines at the endpoints.
        padding = 8.0
        self.setSceneRect(
            QtCore.QRectF(
                -g_scene_size - padding,
                -g_scene_size - padding,
                2 * (g_scene_size + padding),
                2 * (g_scene_size + padding),
            )
        )

    def sizeHint(self):
        return QtCore.QSize(510, 510)

    def minimumSizeHint(self):
        return QtCore.QSize(0, 0)

    def _fit_curve(self):
        if self.viewport().width() > 0 and self.viewport().height() > 0:
            # Scene items, including control handles and the live tracker, share
            # this transform. Scene coordinates used for editing stay unchanged.
            self.fitInView(self.sceneRect(), QtCore.Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_curve()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_curve()


class CurveView(QtWidgets.QGraphicsScene):
    """Visualization of the entire curve editor UI element."""

    curve_changed = QtCore.Signal()
    segment_selection_changed = QtCore.Signal()
    drag_started = QtCore.Signal()
    drag_finished = QtCore.Signal()

    def __init__(self, curve_model, point_editor, show_input_axis=True, parent=None):
        """Creates a new instance.

        :param curve_model the model to visualize
        :param point_editor the point editor to use
        :param parent parent of this widget
        """
        super().__init__(parent)

        self._redraw = False
        self.id = gremlin.util.get_guid()

        self.model = None
        self.point_editor = point_editor
        from gremlin.util import load_image

        is_dark = gremlin.shared_state.is_dark_theme
        curve_image = "dark_curve_grid_ex.svg" if is_dark else "curve_grid_ex.svg"
        self.background_image = load_image(curve_image)

        # Connect editor widget signals
        self.point_editor.x_input.valueChanged.connect(self._editor_update)
        self.point_editor.y_input.valueChanged.connect(self._editor_update)

        self.show_input_axis = show_input_axis
        self.current_item = None
        self.selected_segment: int | None = None
        self._drag_press_pos: QtCore.QPoint | None = None
        self._dragging = False
        self._segment_drag_origin: QtCore.QPointF | None = None
        self._segment_drag_offset = Point2D()
        self.tracker = None
        self.value = 0.0
        self.item_list = []  # list of items by index
        self.item_list_map = {}  # map of points to items

        eh = CurveEventHandler()
        eh.next_point.connect(self._next_item)
        eh.prev_point.connect(self._prev_item)
        eh.handle_match_x.connect(self._handle_match_x)
        eh.handle_match_y.connect(self._handle_match_y)
        eh.delete_point.connect(self._delete_point)

        self.set_model(curve_model)

    def set_model(self, curve_model):
        if self.model is not None:
            self.model.content_modified.disconnect(self._model_changed)
            self.model.content_added.disconnect(self._model_points_changed)
        self.model = curve_model
        self.model.content_modified.connect(self._model_changed)
        self.model.content_added.connect(self._model_points_changed)
        self.current_item = None
        self._clear_segment_selection()
        self._populate_from_model()
        if self.item_list:
            self._select_item(self.item_list[0])
        else:
            CurveEventHandler().selected_item.emit(self.point_editor, None, -1)

    def _model_changed(self):
        self.redraw_scene()
        CurveEventHandler().value_changed.emit(self.value)
        self.curve_changed.emit()

    def _model_points_changed(self):
        self._clear_segment_selection()
        self._populate_from_model()
        self.curve_changed.emit()

    def _dist(self, a, b):
        return ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5

    def _shortest_path(self, points):
        """sorts the points by the shortest distance"""
        if not points:
            return []
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
        self.item_list_map = {}
        for item in self.items():
            if type(item) in [ControlPointGraphicsItem, CurveHandleGraphicsItem]:
                self.removeItem(item)

        points = [cp for cp in self.model.get_control_points()]
        points.sort(key=lambda p: (p.x, p.y))  # do a pre-sort by x value then y value
        points = self._shortest_path(points)

        for cp in points:
            item = ControlPointGraphicsItem(cp)
            self.item_list.append(item)
            self.addItem(item)
            self.item_list_map[cp] = item

        if self.show_input_axis and self.tracker is None:
            self.tracker = DataPointGraphicsItem(0, 0)
            self.addItem(self.tracker)

        self.redraw_scene()

    def add_control_point(self, point, handles=()):
        """Adds a new control point to the model and scene.

        :param point the center of the control point
        :param handles list of potential handles
        """

        if isinstance(self.model, FullAxisCurveModel) or not self.model.is_valid_point(point):
            return

        cp = self.model.add_control_point(point, handles)
        self._populate_from_model()

        item = self.item_list_map[cp]

        self._select_item(item)

    def _editor_update(self, value):
        gremlin.util.InvokeUiMethod(self._editor_update_ui, value)

    def _editor_update_ui(self, value):
        """Callback for changes in the point editor UI.
        runs on UI thread

        :param value the new value entered using the editor UI
        """
        # We can only move control points around using the numerical inputs
        if self.current_item is None:
            return
        new_point = Point2D(self.point_editor.x_input.value(), self.point_editor.y_input.value())
        if isinstance(self.current_item, CurveHandleGraphicsItem):
            # move a handle
            item: CurveHandleGraphicsItem = self.current_item
            item.parent.control_point.set_handle(item.index, new_point)
        elif isinstance(self.current_item, ControlPointGraphicsItem):
            if abs(self.current_item.control_point.center.x) == 1.0:
                new_point.x = self.current_item.control_point.center.x
            self.current_item.control_point.set_center(new_point)
        self.model.save_to_profile()

    @QtCore.Slot()
    def _next_item(self, point_editor):
        """selects the next item"""
        if self.point_editor != point_editor or not self.item_list:
            return
        item = self.current_item
        if item and isinstance(item, CurveHandleGraphicsItem):
            handle_list = item.parent.handles
            index = item.index
            index -= 1
            self._select_item(handle_list[index])
            return

        index = 0

        if self.current_item is not None:
            count = len(self.item_list)
            if self.current_item in self.item_list:
                index = self.item_list.index(self.current_item)
                index += 1
                if index >= count:
                    index = 0

        self._select_item(self.item_list[index])

    @QtCore.Slot()
    def _prev_item(self, point_editor):
        """selects the next item"""
        if self.point_editor != point_editor:
            return

        index = None
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
        if count == 0:
            return

        if self.current_item is None:
            index = count - 1
        else:
            if self.current_item in self.item_list:
                index = self.item_list.index(self.current_item)
                index -= 1
                if index < 0:
                    index = count - 1
        if index is None:
            index = 0
        item = self.item_list[index]
        self._select_item(item)

    @QtCore.Slot(object)
    def _delete_point(self, point_editor):
        if self.point_editor != point_editor:
            return

        item = self.current_item
        if item and isinstance(item, ControlPointGraphicsItem):
            if self.current_item is None:
                return  # nothin selected

            count = len(self.item_list)
            if count < 3:
                # must have at least two points
                MessageBox(prompt="At least two points must exist.")
                return

            if self.model.is_point_locked(item.control_point):
                return

            # don't remove the edges
            if abs(self.current_item.control_point.center.x) == 1.0:
                MessageBox(prompt="Enpoints cannot be removed.")
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
        """deletes the current control point"""

        self.model.remove_control_point(self.current_item.control_point)
        self._populate_from_model()
        self.current_item = None
        self._next_item(self.point_editor)

    @QtCore.Slot()
    def _handle_match_x(self, point_editor):
        if self.point_editor != point_editor:
            return

        """ handles the x """
        item = self.current_item
        if not item or not isinstance(item, CurveHandleGraphicsItem):
            return
        y = gremlin.util.clamp(item.y() / g_scene_size, -1.0, 1.0)
        point = Point2D(item.parent.control_point.x, y)

        # if point == item.parent.control_point.center:
        #     point = item.parent.control_point.center + Point2D(0.001,0.0)

        item.parent.control_point.set_handle(item.index, point)

    @QtCore.Slot()
    def _handle_match_y(self, point_editor):
        """handles the y"""
        if self.point_editor != point_editor:
            return

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
        if isinstance(item, (ControlPointGraphicsItem, CurveHandleGraphicsItem)):
            self._select_segment(None)
            if self.current_item and item != self.current_item:
                self.current_item.set_active(False)
            self.current_item = item
            self.current_item.set_active(True)
            eh = CurveEventHandler()
            if item in self.item_list:
                index = self.item_list.index(item)
            else:
                index = -1
            eh.selected_item.emit(self.point_editor, item, index)

    def _clear_segment_selection(self):
        if self.selected_segment is not None:
            self.selected_segment = None
            self.segment_selection_changed.emit()

    def _select_segment(self, index: int | None):
        if index == self.selected_segment:
            return
        self.selected_segment = index
        if index is not None and self.current_item is not None:
            self.current_item.set_active(False)
            self.current_item = None
            CurveEventHandler().selected_item.emit(self.point_editor, None, -1)
        self.redraw_scene()
        self.segment_selection_changed.emit()

    def insert_point_on_selected_segment(self):
        if self.selected_segment is None or not isinstance(self.model, CubicBezierSplineModel):
            return
        point = self.model.split_segment(self.selected_segment)
        if point is not None:
            self._select_item(self.item_list_map[point])

    def _draw_curve_path(self, curve_fn, left: float, right: float, segment_index: int | None = None):
        start, end = left * g_scene_size, right * g_scene_size
        steps = max(1, math.ceil((end - start) / 2.0))
        path = QtGui.QPainterPath(QtCore.QPointF(start, -g_scene_size * curve_fn(left)))
        for step in range(1, steps + 1):
            x = start + (end - start) * step / steps
            path.lineTo(x, -g_scene_size * curve_fn(x / g_scene_size))

        selected = segment_index is not None and segment_index == self.selected_segment
        color = Color().activeColor() if selected else Color().selectColor()
        item = self.addPath(path, QtGui.QPen(QtGui.QColor(color), 7 if selected else 4))
        if segment_index is not None:
            item.setData(0, segment_index)
            item.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)

    def redraw_scene(self):
        """Updates the scene

        Need to update positions rather then recreating everything, as
        otherwise the state gets lost.
        """
        # Remove old curve path and update control points
        if self._redraw:
            return
        self._redraw = True
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
            if isinstance(self.model, CubicBezierSplineModel):
                knots = sorted(point.x for point in self.model.get_control_points())
                for index, (left, right) in enumerate(zip(knots, knots[1:])):
                    self._draw_curve_path(curve_fn, left, right, index)
            else:
                self._draw_curve_path(curve_fn, -1.0, 1.0)

            # update the tracking item
            if self.show_input_axis:
                x = self.value
                y = -g_scene_size * curve_fn(x / g_scene_size)
                self.tracker.update(x, y)
                # self.tracker.redraw()

        # Update editor widget fields
        if isinstance(self.current_item, ControlPointGraphicsItem):
            self.point_editor.set_values(self.current_item.control_point.center)
        elif isinstance(self.current_item, CurveHandleGraphicsItem):
            handle = self.current_item
            self.point_editor.set_values(handle.parent.control_point.handles[handle.index])

        self._redraw = False

    def mousePressEvent(self, evt):
        """Select a point, handle, or segment and prepare for a possible drag."""
        if evt.button() != QtCore.Qt.LeftButton:
            super().mousePressEvent(evt)
            return

        pos = evt.scenePos()
        item = next(
            (item for item in self.items(pos) if isinstance(item, (ControlPointGraphicsItem, CurveHandleGraphicsItem))),
            None,
        )
        if item is not None:
            self._select_item(item)
            item.grabMouse()
        elif isinstance(self.model, CubicBezierSplineModel):
            # A small hit area makes thin or steep segments easier to select.
            area = QtCore.QRectF(pos.x() - 5.0, pos.y() - 5.0, 10.0, 10.0)
            index = next((item.data(0) for item in self.items(area) if isinstance(item, QtWidgets.QGraphicsPathItem)), None)
            self._select_segment(index)
            if index is None:
                return
            self._segment_drag_origin = pos
            self._segment_drag_offset = Point2D()
        else:
            return

        self._drag_press_pos = evt.screenPos()
        evt.accept()

    def _move_dragged_segment(self, pos):
        if self.selected_segment is not None:
            total = pos - self._segment_drag_origin
            offset = Point2D(total.x() / g_scene_size, -total.y() / g_scene_size)
            applied = self.model.move_segment(self.selected_segment, offset - self._segment_drag_offset)
            self._segment_drag_offset += applied

    def mouseMoveEvent(self, evt):
        if self._drag_press_pos is None or not evt.buttons() & QtCore.Qt.LeftButton:
            super().mouseMoveEvent(evt)
            return
        if not self._dragging:
            distance = (evt.screenPos() - self._drag_press_pos).manhattanLength()
            if distance < QtWidgets.QApplication.startDragDistance():
                evt.accept()
                return
            self._dragging = True
            self.drag_started.emit()
            if self._segment_drag_origin is not None and evt.widget() is not None:
                evt.widget().setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
        if self._segment_drag_origin is None:
            super().mouseMoveEvent(evt)
        else:
            self._move_dragged_segment(evt.scenePos())
            evt.accept()

    def mouseReleaseEvent(self, evt):
        if evt.button() != QtCore.Qt.LeftButton:
            super().mouseReleaseEvent(evt)
            return

        if self._segment_drag_origin is not None:
            if self._dragging:
                self._move_dragged_segment(evt.scenePos())
                if evt.widget() is not None:
                    evt.widget().unsetCursor()
            self._segment_drag_origin = None
            evt.accept()
        else:
            super().mouseReleaseEvent(evt)
        self._drag_press_pos = None
        if self._dragging:
            self._dragging = False
            self.drag_finished.emit()

    def mouseDoubleClickEvent(self, evt):
        """Adds or removes a control point.

        A left double click on empty space creates a new control point.

        :param evt the mouse event to process
        """
        if evt.button() == QtCore.Qt.LeftButton:
            if not any(isinstance(item, ControlPointGraphicsItem) for item in self.items(evt.scenePos())):
                self.add_control_point(
                    Point2D(
                        evt.scenePos().x() / g_scene_size,
                        evt.scenePos().y() / -g_scene_size,
                    )
                )

    def keyPressEvent(self, evt):
        """Removes the currently selected control point if the Del
        key is pressed.

        :param evt the keyboard event to process.
        """
        key = evt.key()
        item = self.current_item
        if key == QtCore.Qt.Key_Delete and isinstance(item, ControlPointGraphicsItem):
            # Disallow removing endpoints or locked points.
            if abs(item.control_point.x) == 1.0 or self.model.is_point_locked(item.control_point):
                return

            # Otherwise remove the currently active control point
            self.model.remove_control_point(self.current_item.control_point)
            self._populate_from_model()
            self.current_item = None

        elif key == QtCore.Qt.Key_Escape:
            if self.selected_segment is not None:
                self._select_segment(None)
            elif isinstance(item, CurveHandleGraphicsItem):
                self._select_item(item.parent)

    def drawBackground(self, painter, rect):
        """Draws the grid background image.

        :param painter the painter object
        :param rect the drawing rectangle
        """
        painter.drawImage(QtCore.QPoint(int(-g_scene_size), int(-g_scene_size)), self.background_image)


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
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.point_label = QtWidgets.QLabel("Control Point")
        self.x_label = QtWidgets.QLabel("X")
        self.y_label = QtWidgets.QLabel("Y")
        self.message = QtWidgets.QLabel("")

        self.x_input = QFloatLineEdit()
        self.x_input.setRange(-1, 1)
        self.x_input.setDecimals(3)
        self.x_input.setSingleStep(0.1)
        self.x_input.setValue(0)

        self.y_input = QFloatLineEdit()
        self.y_input.setRange(-1, 1)
        self.y_input.setDecimals(3)
        self.y_input.setSingleStep(0.1)
        self.y_input.setValue(0)

        self.active_point = None
        self.active_handle = None

        self.next_control_point = QDataPushButton()
        self.next_control_point.setIcon(gremlin.util.load_icon("ph.caret-up-fill"))
        self.next_control_point.setMaximumWidth(20)
        self.next_control_point.setToolTip("Select next control point")

        self.prev_control_point = QDataPushButton()
        self.prev_control_point.setIcon(gremlin.util.load_icon("ph.caret-down-fill"))
        self.prev_control_point.setMaximumWidth(20)
        self.prev_control_point.setToolTip("Select previous control point")

        self.remove_control_point = QDataPushButton()
        self.remove_control_point.setIcon(gremlin.util.load_icon("mdi.delete"))
        self.remove_control_point.setMaximumWidth(20)
        self.remove_control_point.setToolTip("Delete Control Point")

        self.handle_match_x = QDataPushButton("x")
        self.handle_match_x.setToolTip("Match control X")
        self.handle_match_x.setMaximumWidth(20)

        self.handle_match_y = QDataPushButton("y")
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

        self._selected_item_changed(self, None, 0)

    @QtCore.Slot(object, object, int)
    def _selected_item_changed(self, point_editor, item, index):
        if self != point_editor:
            return  # not ours
        msg = ""
        handle_visible = False
        point = None
        self.active_handle = None
        if item is None:
            pass
        elif isinstance(item, CurveHandleGraphicsItem):
            self.point_label.setText("Handle")
            handle_visible = True
            point = item.parent.control_point.handles[item.index]
            self.selected_handle = item
        elif isinstance(item, ControlPointGraphicsItem):
            self.point_label.setText("Control Point")
            msg = f"{[index + 1]}"
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
        """switches to the enxt selected control point"""
        eh = CurveEventHandler()
        eh.next_point.emit(self)

    @QtCore.Slot()
    def _prev_control_point(self):
        """switches to the enxt selected control point"""
        eh = CurveEventHandler()
        eh.prev_point.emit(self)

    @QtCore.Slot()
    def _handle_match_x(self):
        """called when match x button called"""
        eh = CurveEventHandler()
        eh.handle_match_x.emit(self)

    @QtCore.Slot()
    def _handle_match_y(self):
        """called when match x button called"""
        eh = CurveEventHandler()
        eh.handle_match_y.emit(self)

    @QtCore.Slot(str)
    def _update_message(self, message):
        if message is None:
            self.message.setText("")
        else:
            self.message.setText(message)

    @QtCore.Slot()
    def _delete_control_point(self):
        """deletes the current control point"""

        eh = CurveEventHandler()
        eh.delete_point.emit(self)

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
        with QtCore.QSignalBlocker(self.x_input):
            self.x_input.setValue(point.x)
        with QtCore.QSignalBlocker(self.y_input):
            self.y_input.setValue(point.y)
        self.active_point = point


class AxisCurveWidget(QtWidgets.QWidget):
    """response curve standalone widget - displays the curve option UI"""

    _undo_fields = (
        "id", "mapping_type", "full_axis_inflection", "full_axis_inverted", "symmetry_mode", "isCentered", "lock_center",
        "isFiltered", "filterSamples", "filterWindow", "filterOrder",
    )
    _undo_limit = 20

    def __init__(self, curve_data: AxisCurveData, parent=None):  # noqa: F821
        """Creates a new instance.

        :param curve_data: the curve configuration data
        :param parent: the parent widget
        """
        super().__init__(parent=parent)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.curve_data: AxisCurveData = curve_data
        self.is_inverted = False
        self.last_value = 0
        self.curve_model = None
        self._undo_history = []
        self._last_curve_edit = None
        self._curve_edit_in_progress = False
        self._create_ui()
        self._last_curve_edit = self._curve_edit_state()
        ch = CurveEventHandler()
        ch.value_changed.connect(self.update_value)

        clipboard = gremlin.clipboard.Clipboard()
        clipboard.clipboard_changed.connect(self._update_clipboard)

    def _curve_edit_state(self):
        values = {name: getattr(self.curve_data, name) for name in self._undo_fields}
        values["deadzone"] = tuple(self.curve_data.deadzone)
        values["control_points"] = tuple(tuple(point) for point in self.curve_data.control_points)
        return values, self.handle_symmetry_widget.isChecked()

    def _begin_curve_edit(self):
        self._curve_edit_in_progress = True

    def _finish_curve_edit(self):
        self._curve_edit_in_progress = False
        self._record_curve_edit()

    def _record_curve_edit(self):
        if self._last_curve_edit is None or self._curve_edit_in_progress or self.curve_data is None:
            return
        state = self._curve_edit_state()
        if state != self._last_curve_edit:
            self._undo_history.append(self._last_curve_edit)
            if len(self._undo_history) > self._undo_limit:
                self._undo_history.pop(0)
            self._last_curve_edit = state
            self.undo_button.setEnabled(True)

    def _undo_curve_edit(self):
        if not self._undo_history or self._curve_edit_in_progress:
            return
        values, smooth_handles = self._undo_history.pop()
        self._begin_curve_edit()
        try:
            for name, value in values.items():
                if name in ("deadzone", "control_points"):
                    value = list(value)
                setattr(self.curve_data, name, value)
            self._change_curve_type(self.curve_data.mapping_type, self.curve_data.control_points)
            self.curve_model.symmetry_mode = self.curve_data.symmetry_mode
            self.curve_symmetry.setChecked(self.curve_data.symmetry_mode == SymmetryMode.Diagonal)
            if isinstance(self.curve_model, CubicBezierSplineModel):
                self.handle_symmetry_widget.setChecked(smooth_handles)
            self.curve_data.curve_update()
            self._update_ui()
            self._last_curve_edit = self._curve_edit_state()
        finally:
            self._curve_edit_in_progress = False
            self.undo_button.setEnabled(bool(self._undo_history))

    def update_value(self, value: float):
        """handler to update a visual input value on the curve"""
        gremlin.util.InvokeUiMethod(self._update_value_ui, value)

    def unhook(self):
        ch = CurveEventHandler()
        ch.value_changed.disconnect(self.update_value)
        self.curve_data = None
        gremlin.util.clear_layout(self.main_layout)

    def _update_value_ui(self, value):
        """updates dot on the curve based on the value -1 to +1 - runs on UI thread"""
        if not Shiboken.isValid(self):
            return
        value = gremlin.util.clamp(value)

        """ draw the current value on the curve """
        curve_fn = self.curve_model.get_curve_function()
        if curve_fn:
            # get the position of the marker
            curve_value = gremlin.joystick_handling.scale_to_range(value, target_min=-g_scene_size, target_max=g_scene_size)  # value on the curve by pixel x
            x = curve_value
            y = -g_scene_size * curve_fn(x / g_scene_size)

            # tracker only exists when input repeater mode is enabled
            if self.curve_scene.show_input_axis:
                self.curve_scene.tracker.update(x, y)

            self.input_raw_widget.setText(f"{value:0.3f}")
            curved = gremlin.util.clamp(curve_fn(value), -1.0, +1.0)
            self.input_curved_widget.setText(f"{curved:0.3f}")

            # show the curve output and the input
            self.reapeater_widget.setValue([curved, value])

        self.last_value = value
        self.curve_scene.value = value

    def _cleanup_ui(self):
        """cleanup operations"""
        self.curve_data = None

    def _create_ui(self):
        """Creates the required UI elements."""
        if not Shiboken.isValid(self):
            return

        self.container_options_widget = QtWidgets.QWidget()
        self.container_options_widget.setContentsMargins(0, 0, 0, 0)
        self.container_options_layout = QtWidgets.QHBoxLayout(self.container_options_widget)
        self.container_options_layout.setContentsMargins(0, 0, 0, 0)

        # Dropdown menu for the different curve types
        self.curve_type_selection = QDataComboBox()
        for curve_type in CurveType:
            self.curve_type_selection.addItem(CurveType.to_display(curve_type), curve_type)
        self.curve_type_selection.setCurrentIndex(0)
        self.curve_type_selection.currentIndexChanged.connect(self._curve_type_changed)

        self.inflection_selection = QDataComboBox()
        for inflection in FullAxisInflection:
            self.inflection_selection.addItem(inflection.name, inflection)
        self.inflection_selection.setToolTip("Select the inflection point at 25%, 50%, or 75% of the active axis range.")
        self.inflection_selection.currentIndexChanged.connect(self._inflection_changed)
        self.inflection_label = QtWidgets.QLabel("Inflection point:")
        self.inflection_label.setBuddy(self.inflection_selection)

        # filter widget

        self.filter_enabled_widget = QDataCheckbox(
            "Noise Filter (experimental)",
            value=self.curve_data.isFiltered,
            callback=self._handle_filter_changed,
            tooltip="Enables a Savitzky-Golay low-pass noise filter to the input.",
        )

        widgets = [self.filter_enabled_widget]

        grids = []

        self.filter_sample_widget = QIntLineEdit(
            min_range=10,  # 10 is the smallest
            value=self.curve_data.filterSamples,
            callback=self._handle_filter_samples_changed,
            tooltip="Number of input data points tracked for smoothing",
        )

        grids.append("Filter samples:")
        grids.append(self.filter_sample_widget)

        self.filter_order_widget = QIntLineEdit(
            min_range=2,
            max_range=10,
            value=self.curve_data.filterOrder,
            callback_ex=self._handle_filter_order_changed,
            tooltip="Polynomial smoothing order, must be less than the window size",
        )

        grids.append("Polynomial order:")
        grids.append(self.filter_order_widget)

        self.filter_window_widget = QIntLineEdit(
            step=2,
            value=self.curve_data.filterWindow,
            callback_ex=self._handle_filter_window_changed,
            tooltip="Sliding window size (must be an odd number and less than the sample size)",
        )

        grids.append("Window size:")
        grids.append(self.filter_window_widget)

        widget = QDataPushButton(
            "Defaults",
            callback=self._handle_filter_default,
            tooltip="Reset to default values",
        )
        grids.append(widget)

        self.container_filter_options = getHContainer(grids, widget_only=True, left_margin=12)

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout(widget)
        widget.setContentsMargins(0, 0, 0, 0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.container_filter_options, 0, 0)
        layout.addWidget(QtWidgets.QWidget(), 0, 1)
        layout.setColumnStretch(1, 3)

        # widgets.append(self.container_filter_options)
        widgets.append(widget)
        self.container_filter_widget = getHContainer(widgets, widget_only=True)

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
        self.container_options_layout.addWidget(self.inflection_label)
        self.container_options_layout.addWidget(self.inflection_selection)

        # Curve inversion
        self.curve_inversion = QDataPushButton("Invert", callback=self._invert_curve, tooltip="Inverts the current response curve")
        self.container_options_layout.addWidget(self.curve_inversion)

        # Curve symmetry
        self.curve_symmetry = QtWidgets.QCheckBox("Diagonal Symmetry")
        self.curve_symmetry.setChecked(self.curve_data.symmetry_mode == SymmetryMode.Diagonal)
        self.curve_symmetry.clicked.connect(self._curve_symmetry_cb)
        self.container_options_layout.addWidget(self.curve_symmetry)

        # Handle symmetry
        self.handle_symmetry_widget = QtWidgets.QCheckBox("Force smooth curves")

        self.handle_symmetry_widget.stateChanged.connect(self._handle_symmetry_cb)

        self.container_options_layout.addWidget(self.handle_symmetry_widget)

        self.centered_widget = QtWidgets.QCheckBox("Centered")
        self.centered_widget.clicked.connect(self._centered_changed_cb)

        self.container_options_layout.addWidget(self.centered_widget)
        self.container_options_layout.addStretch()

        self.copy_button_widget = Buttons.getCopyWidget(callback=self._copy_curve_cb, tooltip="Copy curve")
        self.copy_button_widget.setMaximumWidth(24)

        self.paste_button_widget = Buttons.getPasteWidget(callback=self._paste_curve_cb, tooltip="Paste curve")
        self.paste_button_widget.setMaximumWidth(24)
        self._update_clipboard()

        self.undo_button = QDataPushButton(
            "Undo", clicked=self._undo_curve_edit, tooltip="Undo the last curve edit (Ctrl+Z).", enabled=False
        )
        undo_shortcut = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Undo, self)
        undo_shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo_shortcut.setAutoRepeat(False)
        undo_shortcut.activated.connect(self._undo_curve_edit)
        self.container_options_layout.addWidget(self.undo_button)
        self.container_options_layout.addWidget(self.copy_button_widget)
        self.container_options_layout.addWidget(self.paste_button_widget)
        self.container_options_layout.addWidget(help_button)

        self.container_presets_widget = QtWidgets.QWidget()
        self.container_presets_widget.setContentsMargins(0, 0, 0, 0)
        self.container_presets_layout = QtWidgets.QHBoxLayout(self.container_presets_widget)
        self.container_presets_layout.setContentsMargins(0, 0, 0, 0)
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
            button = QDataPushButton(CurvePreset.to_display(preset))
            button.data = preset
            button.clicked.connect(self._curve_set_preset_cb)
            self.container_presets_layout.addWidget(button)
        curve_values_button = QDataPushButton("Curve values...", clicked=self._show_curve_values)
        self.container_presets_layout.addWidget(curve_values_button)
        self.container_presets_layout.addStretch()

        self.bezier_preset_shape = QDataComboBox(
            source=[(shape.value, shape) for shape in BezierPresetShape],
            tooltip="Choose cubic smoothing or a logarithmic response.",
        )
        self.bezier_preset_range = QDataComboBox(tooltip="Choose where small input movements should produce smaller output changes.")
        self.bezier_preset_shape.currentIndexChanged.connect(self._update_bezier_preset_ranges)
        self._update_bezier_preset_ranges()
        self.bezier_preset_strength = QDataComboBox(
            source=[("Gentle", 0.25), ("Moderate", 0.5), ("Strong", 0.75), ("Very aggressive", 1.0)],
            value=0.5,
            tooltip="Choose how far the preset bends away from a linear response.",
        )
        self.lock_center_widget = QtWidgets.QCheckBox("Lock center at zero")
        self.lock_center_widget.setToolTip(
            "Keep the Bézier curve at zero output when the input is zero. Unlocking also turns off Centered."
        )
        self.lock_center_widget.clicked.connect(self._lock_center_changed)
        self.apply_bezier_preset_button = QDataPushButton(
            "Apply", clicked=self._apply_bezier_preset, tooltip="Replace the current curve with editable Bézier points."
        )
        self.container_bezier_presets = getHContainer(
            [
                "Bézier presets:",
                self.bezier_preset_shape,
                self.bezier_preset_range,
                self.bezier_preset_strength,
                self.lock_center_widget,
                self.apply_bezier_preset_button,
            ],
            widget_only=True,
        )

        self.container_control_widget = QtWidgets.QWidget()
        self.container_control_widget.setContentsMargins(0, 0, 0, 0)
        self.container_control_layout = QtWidgets.QHBoxLayout(self.container_control_widget)
        self.container_control_layout.setContentsMargins(0, 0, 0, 0)

        # Create all objects required for the response curve UI
        self.control_point_editor = ControlPointEditorWidget()

        self.control_point_editor.setContentsMargins(0, 0, 0, 0)
        self.container_control_layout.addWidget(self.control_point_editor)

        width = get_text_width("M") * 8

        self.input_raw_widget = QtWidgets.QLineEdit()
        self.input_raw_widget.setMaximumWidth(width)
        self.input_raw_widget.setReadOnly(True)
        self.input_curved_widget = QtWidgets.QLineEdit()
        self.input_curved_widget.setMaximumWidth(width)
        self.input_curved_widget.setReadOnly(True)

        # Response curve model used
        self.curve_model = AxisCurveData.model_map[self.curve_data.mapping_type](self.curve_data)

        # mode
        self.curve_model.set_symmetry_mode(self.curve_data.symmetry_mode)

        self.container_curve_widget = QtWidgets.QFrame()

        background_color = Color().actionBackgroundColor()
        self.container_curve_widget.setStyleSheet(f".QFrame{{background-color: {background_color}; border-radius: 10px;}}")
        self.container_curve_layout = QtWidgets.QHBoxLayout(self.container_curve_widget)

        # Graphical curve editor
        self.curve_scene = CurveView(self.curve_model, self.control_point_editor, self.curve_data.show_input_axis)
        self.curve_scene.curve_changed.connect(self._record_curve_edit)
        self.curve_scene.drag_started.connect(self._begin_curve_edit)
        self.curve_scene.drag_finished.connect(self._finish_curve_edit)

        # Create view displaying the curve scene

        self._configure_response_curve_view()

        self.smooth_handles_button = QDataPushButton(
            "Smooth handles",
            clicked=lambda: self._adjust_bezier_handles(smooth=True),
            tooltip="Align mismatched tangents at interior control points while keeping smooth sections and end handles.",
        )
        mirror_x_button = QDataPushButton(
            "Mirror X",
            clicked=lambda: self._mirror_curve(x=True),
            tooltip="Flip the curve left to right by reversing the input axis.",
        )
        mirror_y_button = QDataPushButton(
            "Mirror Y",
            clicked=self._invert_curve,
            tooltip="Flip the curve top to bottom by reversing the output axis.",
        )
        self.straighten_segments_button = QDataPushButton(
            "Straighten segments",
            clicked=lambda: self._adjust_bezier_handles(smooth=False),
            tooltip="Straighten all segments. Click a curve segment to straighten it on its own.",
        )
        self.insert_point_button = QDataPushButton(
            "Insert point",
            clicked=self.curve_scene.insert_point_on_selected_segment,
            tooltip="Split the highlighted Bézier segment while keeping its shape.",
            enabled=False,
        )
        self.curve_scene.segment_selection_changed.connect(self._update_segment_controls)
        self.container_curve_buttons = getHContainer(
            [self.smooth_handles_button, self.straighten_segments_button, self.insert_point_button, "|", mirror_x_button, mirror_y_button,],
            widget_only=True,
        )

        self.container_repeater_widget = QtWidgets.QWidget()
        self.container_repeater_widget.setContentsMargins(0, 0, 0, 0)
        self.container_repeater_layout = QtWidgets.QHBoxLayout(self.container_repeater_widget)
        self.container_repeater_layout.setContentsMargins(0, 0, 0, 0)
        self.reapeater_widget = QAxisRepeaterProgressbar()

        self.container_repeater_layout.addWidget(QtWidgets.QLabel("Input:"))
        self.container_repeater_layout.addWidget(self.input_raw_widget)
        self.container_repeater_layout.addWidget(QtWidgets.QLabel("Curved:"))
        self.container_repeater_layout.addWidget(self.input_curved_widget)
        self.container_repeater_layout.addWidget(self.reapeater_widget)
        self.container_repeater_layout.addStretch()

        self.deadzone_widget = DeadzoneWidget(self.curve_data)
        self.deadzone_widget.changed.connect(self._deadzone_modified_cb)
        for slider in (self.deadzone_widget.slider, self.deadzone_widget.left_slider, self.deadzone_widget.right_slider):
            slider.handleDragStart.connect(self._begin_curve_edit)
            slider.handleDragStop.connect(self._finish_curve_edit)

        # Add all widgets to the layout
        self.main_layout.addWidget(self.container_options_widget)
        self.main_layout.addWidget(self.container_filter_widget)
        self.main_layout.addWidget(self.container_presets_widget)
        self.main_layout.addWidget(self.container_bezier_presets)
        self.main_layout.addWidget(self.container_curve_widget)
        self.main_layout.addWidget(self.container_curve_buttons)
        self.main_layout.addWidget(self.container_repeater_widget)
        self.main_layout.addWidget(self.container_control_widget)
        self.main_layout.addWidget(self.deadzone_widget)

        self._update_ui()
        self._update_clipboard(gremlin.clipboard.Clipboard())

    def _update_ui(self):
        """Populates the UI elements."""

        # Setup correct response curve object
        index = self.curve_type_selection.findData(self.curve_data.mapping_type)

        with QtCore.QSignalBlocker(self.curve_type_selection):
            self.curve_type_selection.setCurrentIndex(index)

        is_full_axis = self.curve_data.mapping_type == CurveType.FullAxis
        self.inflection_label.setVisible(is_full_axis)
        self.inflection_selection.setVisible(is_full_axis)
        with QtCore.QSignalBlocker(self.inflection_selection):
            self.inflection_selection.setCurrentIndex(self.inflection_selection.findData(self.curve_data.full_axis_inflection))

        self.container_control_widget.setVisible(not is_full_axis)
        self.curve_inversion.setVisible(not is_full_axis)
        self.curve_symmetry.setVisible(not is_full_axis)
        self.centered_widget.setVisible(not is_full_axis)
        is_bezier = self.curve_data.mapping_type == CurveType.Bezier
        self.handle_symmetry_widget.setVisible(is_bezier)
        for button in (self.smooth_handles_button, self.straighten_segments_button, self.insert_point_button):
            button.setVisible(is_bezier)

        self.curve_scene.redraw_scene()

        is_centered = self.curve_data.isCentered and not is_full_axis
        with QtCore.QSignalBlocker(self.centered_widget):
            self.centered_widget.setChecked(is_centered)

        self.deadzone_widget.setValues(self.curve_data.deadzone)
        self.deadzone_widget.isCentered = is_centered
        self._update_center_lock()

        self._update_value_ui(self.last_value)

        # filter
        visible = self.curve_data.isFiltered
        self.container_filter_options.setVisible(visible)
        with QtCore.QSignalBlocker(self.filter_enabled_widget):
            self.filter_enabled_widget.setChecked(visible)
        for widget, value in (
            (self.filter_sample_widget, self.curve_data.filterSamples),
            (self.filter_order_widget, self.curve_data.filterOrder),
            (self.filter_window_widget, self.curve_data.filterWindow),
        ):
            with QtCore.QSignalBlocker(widget):
                widget.setValue(value)

    @QtCore.Slot(bool)
    def _centered_changed_cb(self, checked: bool):
        self.curve_data.isCentered = checked
        self.deadzone_widget.isCentered = checked
        self._update_center_lock()
        if checked:
            self._anchor_bezier_center()
        self._record_curve_edit()

    def _update_center_lock(self):
        self.lock_center_widget.setChecked(self.curve_data.center_is_locked)

    @QtCore.Slot(bool)
    def _lock_center_changed(self, checked: bool):
        self.curve_data.lock_center = checked
        if checked:
            self._anchor_bezier_center()
        elif self.curve_data.isCentered:
            self.curve_data.isCentered = False
            self._update_ui()
        self._record_curve_edit()

    def _anchor_bezier_center(self):
        if isinstance(self.curve_model, CubicBezierSplineModel):
            self.curve_model.anchor_center()
            self.curve_data.curve_update()
            self.curve_scene.redraw_scene()
            self._update_value_ui(self.last_value)

    @QtCore.Slot()
    def _show_help(self):

        dialog = MarkdownDialog("Axis Response Curve Instructions")
        w = 600
        h = 400
        geom = self.geometry()
        dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - w / 2),
            int(geom.y() + geom.height() / 2 - h / 2),
            w,
            h,
        )
        if dialog.load("curve_handler_instructions.md"):
            gremlin.util.centerDialog(dialog, w, h)
            dialog.exec()
            return
        else:
            MessageBox(prompt="Unable to locate help file")

    def _show_curve_values(self):
        dialog = QRememberDialog("AxisCurveValuesDialog", width=500, height=460, parent=self)
        dialog.setWindowTitle("Curve Values")
        layout = QtWidgets.QVBoxLayout(dialog)
        instructions = QDataLabel(
            "Paste one Y value per line for evenly spaced inputs, or one X,Y pair per line. Values must be between -1 and +1."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        values = QtWidgets.QPlainTextEdit(parent=dialog)
        values.setPlaceholderText("-1.0, -0.3225\n-0.8947, -0.8076\n…")
        samples = QIntLineEdit(min_range=2, max_range=_max_curve_samples, value=21, chars=4)

        def export_values():
            count = samples.value()
            if count is None or not 2 <= count <= _max_curve_samples:
                MessageBox(title="Cannot sample curve", prompt=f"Choose between 2 and {_max_curve_samples} samples.", parent=dialog)
                return
            if self.curve_data.mapping_type == CurveType.FullAxis:
                response = self.curve_data.full_axis_response
            else:
                response = self.curve_model.get_curve_function()
            if response is not None:
                output = (gremlin.util.clamp(response(-1.0 + 2.0 * index / (count - 1))) for index in range(count))
                values.setPlainText("\n".join(format(value, ".16g") for value in output))

        def import_values():
            try:
                points = _fit_sampled_bezier(_parse_curve_samples(values.toPlainText()))
            except (ValueError, ArithmeticError) as error:
                MessageBox(title="Cannot fit curve", prompt=str(error), parent=dialog)
                return
            centered = self.curve_data.isCentered
            if self.curve_data.center_is_locked:
                center_index = next(index for index in range(0, len(points), 3) if points[index][0] == 0.0)
                if math.isclose(points[center_index][1], 0.0, abs_tol=1e-12):
                    points[center_index] = (0.0, 0.0)
                else:
                    centered = False
                    self.curve_data.lock_center = False
            self._apply_curve_preset(CurveType.Bezier, points, centered)
            dialog.accept()

        export_button = QDataPushButton("Sample curve", clicked=export_values)
        copy_button = QDataPushButton("Copy text", clicked=lambda: QtWidgets.QApplication.clipboard().setText(values.toPlainText()))
        layout.addWidget(getHContainer([QDataLabel("Samples", min_width=0), samples, export_button, copy_button], widget_only=True))
        layout.addWidget(values)
        fit_button = QDataPushButton("Fit Bézier", clicked=import_values)
        close_button = QDataPushButton("Close", clicked=dialog.reject)
        layout.addWidget(getHContainer(["||", fit_button, close_button], widget_only=True))
        export_values()
        dialog.exec()
        dialog.deleteLater()

    @QtCore.Slot()
    def _save_preset_cb(self):
        """save the current curve information to a preset"""
        xml_source, _ = QtWidgets.QFileDialog.getSaveFileName(None, "Save Preset", gremlin.shared_state.data_path, "XML files (*.xml)")

        if xml_source != "":
            try:
                if os.path.isfile(xml_source):
                    # blitz it
                    os.unlink(xml_source)
                root = etree.Element("curve_preset")
                # self.curve_model.save_to_profile() # sync the coords
                node = self.curve_data._generate_xml()
                root.append(node)
                tree = etree.ElementTree(root)
                tree.write(
                    xml_source,
                    pretty_print=True,
                    xml_declaration=True,
                    encoding="utf-8",
                )
                base_name = os.path.basename(xml_source)
                MessageBox(prompt=f"Preset saved to {base_name}", is_warning=False)
            except Exception as err:
                MessageBox(prompt=f"Error saving preset: {err}")
                syslog.error(f"{err}\n{traceback.format_exc()}")

    @QtCore.Slot()
    def _load_preset_cb(self):
        """save the current curve information to a preset"""
        xml_source, _ = QtWidgets.QFileDialog.getOpenFileName(None, "Load Preset", gremlin.shared_state.data_path, "XML files (*.xml)")

        if xml_source != "":
            try:
                base_name = os.path.basename(xml_source)
                parser = etree.XMLParser(remove_blank_text=True)
                tree = etree.parse(xml_source, parser)
                root = tree.getroot()
                if root is None or root.tag != "curve_preset":
                    MessageBox(prompt=f"File {base_name} does not appear to be a valid preset file.")
                    return
                node = gremlin.util.get_xml_child(root, "curve-data")
                if node is None:
                    MessageBox(prompt=f"File {base_name} does not appear to be a valid preset file.")
                    return

                self.curve_data._parse_xml(node)
                self._change_curve_type(self.curve_data.mapping_type, self.curve_data.control_points)
                self.curve_data.curve_update()
                self._update_ui()
                self.update_value(self.last_value)
                self._record_curve_edit()

            except Exception as err:
                MessageBox(prompt=f"Error loading preset: {err}")
                syslog.error(f"{err}\n{traceback.format_exc()}")

    def _clipboard_valid(self, clipboard) -> bool:
        """true if the clipboard data is valid"""
        data = clipboard.data
        if gremlin.util.is_binary_string(data):
            data = data.decode("utf-8")
        return isinstance(data, str) and "</curve-data>" in data

    @QtCore.Slot()
    def _copy_curve_cb(self):
        """copies current curve data to the clipboard"""
        node = self.curve_data._generate_xml()
        xml = etree.tostring(node)
        clipboard = gremlin.clipboard.Clipboard()
        clipboard.data = xml
        self._update_clipboard()

    @QtCore.Slot()
    def _paste_curve_cb(self):
        """paste curve data from clipboard"""
        clipboard = gremlin.clipboard.Clipboard()
        if self._clipboard_valid(clipboard):
            try:
                xml = clipboard.data
                node = etree.fromstring(xml)
                self.curve_data._parse_xml(node)
                self._change_curve_type(self.curve_data.mapping_type, self.curve_data.control_points)
                self.curve_data.curve_update()
                self._update_ui()
                self.update_value(self.last_value)
                self._record_curve_edit()
            except Exception:
                # invalid
                return

    def _update_clipboard(self, clipboard=None):
        """updates the state of the clipboard buttons"""
        if not Shiboken.isValid(self):
            return
        if clipboard is None:
            clipboard = gremlin.clipboard.Clipboard()
        self.paste_button_widget.setEnabled(self._clipboard_valid(clipboard))

    @QtCore.Slot(int)
    def _curve_type_changed(self):
        curve_type = self.curve_type_selection.currentData()
        self._change_curve_type(curve_type)
        if curve_type != CurveType.FullAxis:
            self.curve_data.isCentered = curve_type == CurveType.Bezier
        self.curve_data.curve_update()
        self._update_ui()
        self._record_curve_edit()

    @QtCore.Slot(int)
    def _inflection_changed(self, index: int):
        self.curve_data.full_axis_inflection = self.inflection_selection.itemData(index)
        self.curve_scene.redraw_scene()
        self._update_value_ui(self.last_value)
        self._record_curve_edit()

    @QtCore.Slot(bool)
    def _handle_filter_changed(self, checked: bool):
        self.curve_data.isFiltered = checked
        self._update_ui()
        self._record_curve_edit()

    @QtCore.Slot(int)
    def _handle_filter_samples_changed(self, value: int):
        if self.curve_data.filterSamples != value:
            if value < 10:
                value = 10  # 10 is the smallest sample size
            self.curve_data.filterSamples = value
            if self.curve_data.filterWindow > value:
                # sliding window must be less than the total samples
                if value % 2 == 0:
                    # even
                    value -= 1
                if value < 1:
                    value = 1
                self.curve_data.filterWindow = value
                with QtCore.QSignalBlocker(self.filter_window_widget):
                    self.filter_window_widget.setValue(value)
        self._record_curve_edit()

    @QtCore.Slot(int)
    def _handle_filter_order_changed(self, widget, value: int):
        if self.curve_data.filterOrder != value:
            if value < 2:
                value = 2  # min value is 2 for polynomial smoothing
                widget.setValue(2)

            self.curve_data.filterOrder = value
        self._record_curve_edit()

    @QtCore.Slot(int)
    def _handle_filter_window_changed(self, widget, value: int):
        if self.curve_data.filterSamples != value:
            p_value = value
            if value > self.curve_data.filterSamples:
                value = self.curve_data.filterSamples
            if value % 2 == 0:
                # even
                value -= 1
            self.curve_data.filterWindow = value
            if p_value != value:
                # update the correct value
                widget.setValue(value)
        self._record_curve_edit()

    @QtCore.Slot()
    def _handle_filter_default(self):
        self.curve_data.filterSamples = 200
        self.curve_data.filterOrder = 2
        self.curve_data.filterWindow = 51
        self._update_ui()
        self._record_curve_edit()

    def _change_curve_type(self, curve_type: CurveType, control_points=None):
        """Changes the type of curve used.

        :param curve_type the name of the new curve type
        """

        # Create new model
        if control_points is None:
            if curve_type == CurveType.Cubic:
                self.curve_data.control_points = [(-1.0, -1.0), (1.0, 1.0)]
            elif curve_type == CurveType.FullAxis:
                self.curve_data.control_points = []
            elif curve_type == CurveType.Bezier:
                self.curve_data.control_points = [
                    (-1.0, -1.0),
                    (-1.0, 0),
                    (-0.08, 0.0),
                    (0.0, 0.0),
                    (0.08, 0.0),
                    (1.0, 0.0),
                    (1.0, 1.0),
                ]

        else:
            self.curve_data.control_points = control_points

        self.curve_data.mapping_type = curve_type
        self.curve_model = AxisCurveData.model_map[curve_type](self.curve_data)

        with QtCore.QSignalBlocker(self.handle_symmetry_widget):
            self.handle_symmetry_widget.setChecked(False)

        self.curve_symmetry.setChecked(False)

        self.curve_scene.set_model(self.curve_model)

    @QtCore.Slot(bool)
    def _curve_symmetry_cb(self, checked: bool):
        self._begin_curve_edit()
        try:
            self.curve_data.symmetry_mode = SymmetryMode.Diagonal if checked else SymmetryMode.NoSymmetry
            self.curve_model.set_symmetry_mode(self.curve_data.symmetry_mode)
            self.curve_model.save_to_profile()
            self.curve_scene.redraw_scene()
        finally:
            self._finish_curve_edit()

    @QtCore.Slot()
    def _curve_set_preset_cb(self):
        """sets the curve points to max bezier"""

        # point_first handle_first  (x must be -1)
        # ...
        # point_handle_1 point_center point_handle_2  # point is centered and has two handles
        # ...
        # point_handle_1 point_center point_handle_2
        # ...
        # handle_last point_last (x must be + 1)

        widget = self.sender()
        preset: CurvePreset = widget.data
        curve_type = CurveType.Bezier
        is_centered = True  # assume centered
        match preset:
            case CurvePreset.Bezier1:
                # max 10%
                control_points = [
                    (-1.0, -1.0),
                    (-1.0, 0),
                    (-0.1, 0.0),
                    (0.0, 0.0),
                    (0.1, 0.0),
                    (1.0, 0.0),
                    (1.0, 1.0),
                ]
            case CurvePreset.Bezier2:
                # max 20%
                control_points = [
                    (-1.0, -1.0),
                    (-1.0, 0),
                    (-0.2, 0.0),
                    (0.0, 0.0),
                    (0.2, 0.0),
                    (1.0, 0.0),
                    (1.0, 1.0),
                ]
            case CurvePreset.Bezier3:
                # 5% start 50%
                control_points = [
                    (-1.0, -1.0),
                    (-0.5, 0),
                    (-0.05, 0.0),
                    (0.0, 0.0),
                    (0.05, 0.0),
                    (0.5, 0.0),
                    (1.0, 1.0),
                ]
            case CurvePreset.Bezier4:
                # 10% start 50%
                control_points = [
                    (-1.0, -1.0),
                    (-0.5, 0),
                    (-0.1, 0.0),
                    (0.0, 0.0),
                    (0.1, 0.0),
                    (0.5, 0.0),
                    (1.0, 1.0),
                ]
            case CurvePreset.Reset:
                # reset to cubic linear
                curve_type = CurveType.Cubic
                control_points = [(-1.0, -1.0), (1.0, 1.0)]
                is_centered = False

            case _:
                syslog.error(f"Curve preset: don't know how to handle {preset}")
                return

        self._apply_curve_preset(curve_type, control_points, is_centered)

    @QtCore.Slot()
    def _update_bezier_preset_ranges(self):
        selection = self.bezier_preset_range.currentData()
        shape = self.bezier_preset_shape.currentData()
        self.bezier_preset_range.clear()
        for region in BezierPresetRange:
            if region != BezierPresetRange.BothEnds or shape == BezierPresetShape.Smoothstep:
                self.bezier_preset_range.addItem(region.value, region)
        index = self.bezier_preset_range.findData(selection)
        if index < 0:
            index = self.bezier_preset_range.findData(BezierPresetRange.Center)
        self.bezier_preset_range.setCurrentIndex(index)

    def _apply_bezier_preset(self):
        control_points = bezier_preset_points(
            self.bezier_preset_shape.currentData(),
            self.bezier_preset_range.currentData(),
            self.bezier_preset_strength.currentData(),
            lock_center=self.curve_data.center_is_locked,
        )
        self._apply_curve_preset(CurveType.Bezier, control_points, self.curve_data.isCentered)

    def _apply_curve_preset(self, curve_type, control_points, is_centered):
        self.curve_data.symmetry_mode = SymmetryMode.NoSymmetry
        self.curve_data.isCentered = is_centered
        self._change_curve_type(curve_type, control_points)
        self.curve_data.curve_update()
        self._update_ui()
        self._record_curve_edit()

    @QtCore.Slot()
    def _deadzone_preset_cb(self):
        """handles deadzone presets"""
        widget = self.sender()
        preset: DeadzonePreset = widget.data

        dd = self.deadzone_widget
        d_start, d_left, d_right, d_end = dd.values()

        if d_start is None:
            d_start = -1
        if d_end is None:
            d_end = 1
        if d_left is None:
            d_left = 0
        if d_right is None:
            d_right = 0

        match preset:
            case DeadzonePreset.center_zero:
                d_left = 0.0
                d_right = 0.0
            case DeadzonePreset.center_two:
                d_left = -0.02 * 2
                d_right = 0.02 * 2
            case DeadzonePreset.center_five:
                d_left = -0.05 * 2
                d_right = 0.05 * 2
            case DeadzonePreset.center_ten:
                d_left = -0.1 * 2
                d_right = 0.1 * 2
            case DeadzonePreset.end_two:
                d_start = -1 + 0.02 * 2
                d_end = 1 - 0.02 * 2
            case DeadzonePreset.end_five:
                d_start = -1 + 0.05 * 2
                d_end = 1 - 0.05 * 2
            case DeadzonePreset.end_ten:
                d_start = -1 + 0.1 * 2
                d_end = 1 - 0.1 * 2

            case DeadzonePreset.reset:
                d_start = -1
                d_left = 0
                d_right = 0
                d_end = 1

        dd._update_deadzone([d_start, d_left, d_right, d_end])
        # dd.set_values([d_start, d_left, d_right, d_end])

    @QtCore.Slot()
    def _deadzone_modified_cb(self):
        """called when deadzones are modified"""
        self.curve_data.deadzone = self.deadzone_widget.values()
        self.curve_data.curve_update()
        self._update_ui()
        self._record_curve_edit()

    def _update_segment_controls(self):
        segment_selected = self.curve_scene.selected_segment is not None
        self.control_point_editor.setEnabled(not segment_selected)
        self.insert_point_button.setEnabled(segment_selected)
        if not segment_selected:
            self.straighten_segments_button.setText("Straighten segments")
            self.straighten_segments_button.setToolTip("Straighten all segments. Click a curve segment to straighten it on its own.")
        else:
            self.straighten_segments_button.setText("Straighten selected segment")
            self.straighten_segments_button.setToolTip(
                "Straighten the highlighted segment. Drag it to move it, or click an empty part of the graph to clear the selection."
            )

    def _adjust_bezier_handles(self, *, smooth: bool):
        if isinstance(self.curve_model, CubicBezierSplineModel):
            self.curve_model.adjust_handles(smooth=smooth, segment_index=self.curve_scene.selected_segment)

    def _handle_symmetry_cb(self, state):
        if not isinstance(self.curve_model, CubicBezierSplineModel):
            syslog.error("Handle symmetry callback in non bezier curve attempted.")
            return

        self.curve_model.set_handle_symmetry(state == QtCore.Qt.Checked.value)
        self._record_curve_edit()

    def _configure_response_curve_view(self):
        """Create a view that scales the graph and its items to the layout bounds."""
        clear_layout(self.container_curve_layout)
        self.curve_view = CurveGraphicsView(self.curve_scene, self.container_curve_widget)
        self.container_curve_layout.addWidget(self.curve_view)

    def _invert_curve(self):
        self._mirror_curve(x=False)

    def _mirror_curve(self, *, x: bool):
        self._begin_curve_edit()
        try:
            if x:
                # Input deadzones move with the mirrored input axis.
                self.curve_data.deadzone = [
                    -value if value is not None else None for value in reversed(self.curve_data.deadzone)
                ]
            if self.curve_data.mapping_type == CurveType.FullAxis:
                if x:
                    self.curve_data.full_axis_inflection = FullAxisInflection(-self.curve_data.full_axis_inflection.value)
                self.curve_data.full_axis_inverted = not self.curve_data.full_axis_inverted
            elif x:
                self.curve_model.mirror_x()
            else:
                self.curve_model.invert()
            self.curve_data.curve_update()
            self._update_ui()
        finally:
            self._finish_curve_edit()


class SmoothingFilter:
    """smoothing filter for time lapsed data"""

    def __init__(self, samples=200, window_size=51, poly_order=2):
        self.data = []
        samples = max(samples, 10)  # 10 is the min
        self.count = 0  # number of values in the array
        self.filtered_data = None
        if window_size > samples:
            if samples % 2 == 0:
                window_size = samples - 1
        self.samples = samples
        self.window_size = window_size
        self.poly_order = poly_order

    def update(self, value: float, ts=None) -> float:
        """updates the filter with a single value"""
        from scipy.signal import (
            savgol_filter,
        )  # delay load this import because it takes a while to initialize

        if ts is None:
            ts = time.time()  # current timestamp of the data
        pt = [ts, value]

        if len(self.data) < self.samples:
            self.data.append(pt)
        else:
            # shift the data
            self.data.pop(0)
            self.data.append(pt)

        a = np.array(self.data)
        # window length must be an odd number
        count = len(self.data)
        if count % 2 == 0:
            # even number -> odd number
            count -= 1
        window_length = min(count, self.window_size)
        poly_order = min(window_length - 1, self.poly_order)
        fd = savgol_filter(a, window_length=window_length, polyorder=poly_order, axis=0)
        return float(fd[-1][1])


class AxisCurveData:
    """holds the data for a curved axis"""

    # map of curve types to curve models
    model_map = {
        CurveType.Cubic: CubicSplineModel,
        CurveType.Bezier: CubicBezierSplineModel,
        CurveType.FullAxis: FullAxisCurveModel,
    }

    def __init__(self):
        self.id = gremlin.util.get_guid()  # unique ID for this curve
        self.deadzone = [-1, 0, 0, 1]
        self.sensitivity = 1.0
        self._mapping_type = CurveType.Cubic
        self.full_axis_inflection = FullAxisInflection.Center
        self.full_axis_inverted = False
        self.control_points = [(-1.0, -1.0), (1.0, 1.0)]
        self.symmetry_mode = SymmetryMode.NoSymmetry
        self.show_input_axis = gremlin.config.Configuration().show_input_axis
        self.deadzone_fn = None
        self.response_fn = None
        self.isCentered = False
        self.lock_center = False
        self.curve_filter = None
        self.isFiltered = False  # true if filtered
        self.filterSamples = 200  # number of samples to use for filtering
        self.filterWindow = 51  # window size (must be odd number)
        self.filterOrder = 2  # polynomial order for filtering

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self.profile_start)

    def to_html(self) -> str:
        """returns reporting graphviz data for this action"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)

        table.addField("Mode", self.symmetry_mode.name)
        table.addField("Control points", f"{len(self.control_points)}")
        table.addField("Mapping", self.mapping_type.name)
        table.addField("Sensitivity", f"{self.sensitivity:0.3f}")
        table.addField("Centered", "Yes" if self.isCentered else "No")
        table.addField("Deadzone Low", f"{self.deadzone[0]}")
        table.addField("Deadzone Ctr Low", f"{self.deadzone[1]}")
        table.addField("Deadzone Ctr High", f"{self.deadzone[2]}")
        table.addField("Deadzone High", f"{self.deadzone[3]}")
        table.addField("Filtered", "Yes" if self.isFiltered else "No")
        if self.isFiltered:
            table.addField("Filter Samples", f"{self.filterSamples:,}")
            table.addField("Filter Window", f"{self.filterWindow:,}")
            table.addField("Filter PolyOrder", f"{self.filterOrder}")

        return table.to_html()

    @property
    def center_is_locked(self) -> bool:
        return self.isCentered or self.lock_center

    @property
    def mapping_type(self) -> CurveType:
        return self._mapping_type

    @mapping_type.setter
    def mapping_type(self, value: CurveType):
        self._mapping_type = value

    @QtCore.Slot()
    def profile_start(self):
        """called on profile start"""
        # setup the curve function for the output
        self.curve_update()

    def _parse_xml(self, node, data=None, extra_data=None):
        """Parses the XML corresponding to a response curve.

        :param node the XML node to parse
        """

        if not gremlin.input_item._is_curve_tag(node.tag):
            return

        if "id" in node.attrib:
            self.id = node.get("id")  # re use existing ID

        if "mode" in node.attrib:
            mode = node.get("mode")
            self.symmetry_mode = SymmetryMode.to_enum(mode)

        self.isCentered = safe_read(node, "centered", bool, False)
        self.lock_center = safe_read(node, "lock-center", bool, False)

        # filter data
        self.isFiltered = safe_read(node, "filtered", bool, False)
        self.filterSamples = safe_read(node, "samples", int, 200)
        self.filterWindow = safe_read(node, "window", int, 51)
        self.filterOrder = safe_read(node, "poly", int, 2)

        self.full_axis_inflection = FullAxisInflection.Center
        self.full_axis_inverted = False
        self.control_points = []
        for child in node:
            if child.tag == "deadzone":
                self.deadzone = [
                    float(child.get("low")),
                    float(child.get("center-low")),
                    float(child.get("center-high")),
                    float(child.get("high")),
                ]
            elif child.tag == "mapping":
                curve_type = child.get("type")
                self.mapping_type = CurveType.to_enum(curve_type)
                if self.mapping_type == CurveType.FullAxis:
                    inflection = child.get("inflection", "").capitalize()
                    self.full_axis_inflection = FullAxisInflection.__members__.get(inflection, FullAxisInflection.Center)
                    self.full_axis_inverted = safe_read(child, "inverted", bool, False)
                self.control_points = []
                for point in child.iter("control-point"):
                    self.control_points.append((float(point.get("x")), float(point.get("y"))))

        self.curve_update()

    def setPreset(self, preset: CurvePreset):
        """applies a preset to this curve"""
        match preset:
            case CurvePreset.Bezier1:
                # max 10%
                control_points = [
                    (-1.0, -1.0),
                    (-1.0, 0),
                    (-0.1, 0.0),
                    (0.0, 0.0),
                    (0.1, 0.0),
                    (1.0, 0.0),
                    (1.0, 1.0),
                ]
            case CurvePreset.Bezier2:
                # max 20%
                control_points = [
                    (-1.0, -1.0),
                    (-1.0, 0),
                    (-0.2, 0.0),
                    (0.0, 0.0),
                    (0.2, 0.0),
                    (1.0, 0.0),
                    (1.0, 1.0),
                ]
            case CurvePreset.Bezier3:
                # 5% start 50%
                control_points = [
                    (-1.0, -1.0),
                    (-0.5, 0),
                    (-0.05, 0.0),
                    (0.0, 0.0),
                    (0.05, 0.0),
                    (0.5, 0.0),
                    (1.0, 1.0),
                ]
            case CurvePreset.Bezier4:
                # 10% start 50%
                control_points = [
                    (-1.0, -1.0),
                    (-0.5, 0),
                    (-0.1, 0.0),
                    (0.0, 0.0),
                    (0.1, 0.0),
                    (0.5, 0.0),
                    (1.0, 1.0),
                ]
            case CurvePreset.Reset:
                # reset to cubic linear
                control_points = [(-1.0, -1.0), (1.0, 1.0)]

        self.control_points = control_points

    def _generate_xml(self):
        """Generates a XML node corresponding to this object.

        :return XML node representing the object's data
        """
        node = ElementTree.Element("curve-data")
        node.set("mode", SymmetryMode.to_string(self.symmetry_mode))
        node.set("centered", str(self.isCentered))
        if self.lock_center:
            node.set("lock-center", safe_format(self.lock_center, bool))
        node.set("id", self.id)

        # filter data
        node.set("filtered", safe_format(self.isFiltered, bool))
        node.set("samples", safe_format(self.filterSamples, int))
        node.set("poly", safe_format(self.filterOrder, int))
        node.set("window", safe_format(self.filterWindow, int))

        # Response curve mapping
        if self.mapping_type == CurveType.FullAxis:
            mapping_node = ElementTree.SubElement(node, "mapping")
            mapping_node.set("type", CurveType.to_string(self.mapping_type))
            mapping_node.set("inflection", self.full_axis_inflection.name.lower())
            if self.full_axis_inverted:
                mapping_node.set("inverted", safe_format(True, bool))
        elif self.control_points:
            mapping_node = ElementTree.SubElement(node, "mapping")
            mapping_node.set("type", CurveType.to_string(self.mapping_type))
            for point in self.control_points:
                cp_node = ElementTree.Element("control-point")
                if self.mapping_type == CurveType.Bezier:
                    # Preserve straight and tangent-aligned handles across save and reload.
                    cp_node.set("x", repr(float(point[0])))
                    cp_node.set("y", repr(float(point[1])))
                else:
                    cp_node.set("x", float_to_xml(point[0]))
                    cp_node.set("y", float_to_xml(point[1]))
                mapping_node.append(cp_node)

        # Deadzone settings
        deadzone_node = ElementTree.Element("deadzone")

        # provide suitable defaults
        if self.deadzone:
            if len(self.deadzone) == 2:
                # enpoints only
                v1, v4 = self.deadzone
                v2 = v3 = 0
            else:  # 4 members
                v1, v2, v3, v4 = self.deadzone
            if v1 is None:
                v1 = -1
            if v2 is None:
                v2 = 0
            if v3 is None:
                v3 = 0
            if v4 is None:
                v4 = 1
        else:
            v1 = -1
            v2 = 0
            v3 = 0
            v4 = +1

        deadzone_node.set("low", float_to_xml(v1))
        deadzone_node.set("center-low", float_to_xml(v2))
        deadzone_node.set("center-high", float_to_xml(v3))
        deadzone_node.set("high", float_to_xml(v4))
        node.append(deadzone_node)

        return node

    def filter_update(self):
        """updates the curve filter"""
        if self.isFiltered:
            if not self.curve_filter:
                self.curve_filter = SmoothingFilter(self.filterSamples, self.filterWindow, self.filterOrder)
            else:
                self.curve_filter.poly_order = self.filterOrder
                self.curve_filter.samples = self.filterSamples
                self.curve_filter.window_size = self.filterWindow
        else:
            self.curve_filter = None

    def full_axis_curve(self, value: float) -> float:
        """Evaluate a monotonic cubic over the active range between the end deadzones."""
        low, high = (self.deadzone[0], self.deadzone[-1]) if self.deadzone else (-1.0, 1.0)
        low = -1.0 if low is None else low
        high = 1.0 if high is None else high
        if low < high:
            value = gremlin.util.scale_to_range(value, source_min=low, source_max=high)
        else:
            value = gremlin.util.clamp(value)
        return self.full_axis_response(value)

    def full_axis_response(self, value: float) -> float:
        """Evaluate the Full Axis response before end deadzones are applied."""
        inflection = self.full_axis_inflection.value
        # The cubic term vanishes at the endpoints. Its second derivative is zero at the selected inflection.
        response = value + 0.15 * (1.0 - value * value) * (value - 3.0 * inflection)
        return -response if self.full_axis_inverted else response

    def curve_update(self):
        """updates the curve params"""

        # update filter options
        self.filter_update()

        if self.mapping_type == CurveType.FullAxis:
            self.deadzone_fn = None
            self.response_fn = self.full_axis_curve
            return

        self.deadzone_fn = lambda value: gremlin.input_devices.deadzone(
            value,
            self.deadzone[0],
            self.deadzone[1],
            self.deadzone[2],
            self.deadzone[3],
        )
        if self.mapping_type == CurveType.Cubic:
            self.response_fn = gremlin.spline.CubicSpline(self.control_points)
        elif self.mapping_type == CurveType.Bezier:
            self.response_fn = gremlin.spline.CubicBezierSpline(self.control_points)
        else:
            raise gremlin.error.GremlinError("Invalid curve type")

    def curve_value(self, value: float, update: bool = False, *, apply_filter: bool = True):
        """processes an input value -1 to +1 and outputs the curved value based on the current curve model"""
        if update or self.response_fn is None:
            self.curve_update()
        if self.deadzone_fn is not None:
            # v1 = self.deadzone_fn(value)
            # syslog.info(f"deadzone: input [{value:0.4f}] output [{v1:0.4f}]")
            value = self.deadzone_fn(value)
        if self.response_fn is not None:
            value = self.response_fn(value)

        if apply_filter and self.curve_filter:
            value = self.curve_filter.update(value)

        return value

    def __str__(self):
        return f"Curve Data: [{self.id}] deadzone: {self.deadzone} mapping: {self.mapping_type.name}  cp: {self.control_points}"


class AxisCurveDialog(QRememberDialog):
    """dialog box for curve configuration"""

    def __init__(self, curve_data, parent=None):
        """Creates a new instance.

        :param curve_data: the curve configuration data
        :param parent: the parent widget
        """
        super().__init__(self.__class__.__name__, parent=parent, width=640, height=480)

        self.setWindowTitle("Curve Editor")

        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout(self.scroll_widget)
        self.scroll_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_widget)

        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.widget = AxisCurveWidget(curve_data, self)
        self.main_layout.addWidget(self.scroll_area)
        self.scroll_layout.addWidget(self.widget)

        self.setMinimumSize(400, 400)
        self._resize_to_contents()

    def _resize_to_contents(self):
        """Fit the editor rather than QScrollArea's capped default size hint."""
        self.ensurePolished()
        self.widget.ensurePolished()
        self.scroll_layout.activate()
        self.main_layout.activate()
        content_size = self.scroll_layout.sizeHint().expandedTo(self.scroll_widget.minimumSizeHint())
        margins = self.main_layout.contentsMargins()
        frame = self.scroll_area.frameWidth() * 2
        preferred = content_size + QtCore.QSize(
            margins.left() + margins.right() + frame,
            margins.top() + margins.bottom() + frame,
        )
        preferred = preferred.expandedTo(self.minimumSize())
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry().size()
            # Retain scrolling when the full editor will not fit on screen.
            if preferred.height() > available.height():
                preferred.setWidth(preferred.width() + self.scroll_area.verticalScrollBar().sizeHint().width())
            if preferred.width() > available.width():
                preferred.setHeight(preferred.height() + self.scroll_area.horizontalScrollBar().sizeHint().height())
            preferred = preferred.boundedTo(available)
        self.resize(preferred)

    def getCurveData(self):
        return self.widget.curve_data

    @property
    def curve_update_handler(self):
        """call this to update the curve input dynamically"""
        return self.widget.update_value

    def keyPressEvent(self, event):
        """disable escape key to prevent conflict with handle deselect"""
        if event.key() == QtCore.Qt.Key_Escape:
            self.widget.curve_scene.keyPressEvent(event)
        else:
            super().keyPressEvent(event)
