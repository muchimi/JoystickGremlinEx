# -*- coding: utf-8; -*-

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

# implements a custom multi-gate slider widget
from __future__ import annotations  # deprecated with python 3.14+
import logging
from PySide6 import QtWidgets, QtCore, QtGui
import gremlin.config
import gremlin.util
from PySide6.QtCore import Qt, QPoint, QRect

from PySide6.QtWidgets import QToolTip
from PySide6.QtGui import (
    QColor,
    QBrush,
    QPaintEvent,
    QPen,
    QPainter,
    QMouseEvent,
    QCursor,
)
from shiboken6 import Shiboken

from itertools import pairwise
from bisect import bisect_left, bisect_right

syslog = logging.getLogger("system")


class QSliderWidget(QtWidgets.QWidget):
    """custom slider object --- WARNING : ALL EVENT HANDLERS NEED TO CHECK FOR UI THREAD"""

    handleClicked = QtCore.Signal(int)  # called when a handle is left clicked (handle index)
    handleRightClicked = QtCore.Signal(int)  # called when a handle is right clicked (handle index)
    handleDoubleClicked = QtCore.Signal(int)  # called when a handle is double clicked (handle index)
    handleDoubleRightClicked = QtCore.Signal(int)  # called when a handle is double clicked with the right mouse button (handle index)
    rangeClicked = QtCore.Signal(
        float, int, int
    )  # called when a groove is clicked (between handles) - sends the value of the slider where clicked - (value, left handle index, right handle index)
    rangeRightClicked = QtCore.Signal(
        float, int, int
    )  # called when a range is right clicked (between handles) - sends the value of the slider where clicked - (value, left handle index, right handle index)
    rangeDoubleClicked = QtCore.Signal(
        float, int, int
    )  # called when a range is double clicked (between handles) - sends the value of the slider where clicked - (value, left handle index, right handle index)
    rangeDoubleRightClicked = QtCore.Signal(
        float, int, int
    )  # called when a range is double clicked with the right mouse button (between handles) - sends the value of the slider where clicked - (value, left handle index, right handle index)
    valueChanged = QtCore.Signal(int, float)  # called when a gate is dragged or scrolled (index of handle, updated value)
    handleDragStart = QtCore.Signal(int)  # called when a handle is being dragged (handle index)
    handleDragStop = QtCore.Signal(int)  # called when a handle stops being dragged (handle index)

    def __init__(self, object_name=None, parent=None):
        import gremlin.ui.ui_common

        super().__init__(parent)
        self._disposed = False
        self._id = gremlin.util.get_guid()
        self._lock = False
        self._values = [
            -1.0,
            1.0,
        ]  # position of the gates inside the range - the values must be between the slider's min/max values
        self._handle_icons = {}  # icon data for handles, keyed by index
        self._internal_handle_pixmaps = {}  # holds the pixmaps for the current handle icons keyed by handle ID
        self._minimum = -1.0
        self._maximum = 1.0
        self._single_step = 0.01  # value change per mouse wheel notch
        self._draw_handles = True
        self.setObjectName(object_name if object_name else "QSliderWidget")

        self._tick_count = 0  # no ticks

        self.handleColor = QColor(gremlin.ui.ui_common.Color().sliderHandleColor())  # QColor("#a7b59e")
        self.tickColor = QColor(gremlin.ui.ui_common.Color().sliderTickColor())  # QColor("#232323")
        self.handleBorderColor = QColor(gremlin.ui.ui_common.Color().sliderHandleBorderColor())  # QColor("#e0e0e0")
        self.rangeBorderColor = QColor(gremlin.ui.ui_common.Color().sliderRangeBorderColor())  # QColor("#e0e0e0")
        self.rangeColor = QColor(gremlin.ui.ui_common.Color().sliderRangeColor())  # QColor("8fb9bc")
        self.rangeAlternateColor = QColor(gremlin.ui.ui_common.Color().sliderAlternateRangeColor())  # QColor("#8fb9bc")
        self.UseAlternateColor = True  # alternate range colors
        self.BackgroundColor = QColor(gremlin.ui.ui_common.Color().sliderBackgroundColor())  # QColor("#c3c3c3")

        self._finishedProgressLength = 0
        self._handle_hotspots = []  # rects of handle clickable spots
        self._range_hotspots = []  # rects of clickable spots for ranges between handles
        self._handle_positions = []  # computed gate position offset indexed by gate index
        self._marker_pos = []  # computed marker positions

        self._readOnly = False
        self._usable_width = 0  # range width, pixels
        self._usable_left = 0  # left range start position, pixel
        self._usable_right = 0  # right range start position, pixel
        self._marker_size = 16  # size of the marker icons in pixels
        self._marker_visible = True  # show marker

        self._range_left = 0  # position of the first gate in pixels
        self._range_right = 0  # position of the last gate in pixels
        self._range_width = 0  # width of the bar between min gate and max gate in pixels
        self._handle_height = 0  # height of the gate range bar
        self._handle_top = 0  # top offset for the gate range bar
        self._handle_min = 0  # min possible x for a handle position
        self._handle_max = 0  # max possible x for a handle position
        self._range_msg = "N/A"

        self._single_range = False  # true if there are different ranges between handles, false if a single range between min/max handles

        # mouse and drag tracking
        self._mouse_down = False  # is mouse button down
        self._double_clicked = False  # true if the mouse was just double clicked
        self._drag_start = None  # start drag position
        self._drag_handle_index = None  # handle being dragged
        self._drag_active = False  # true if a drag operation is in progress
        self._drag_x_offset = 0  # offset in pixels of the mouse position to the center of the gate
        self._drag_emit = False  # true if the drag event was emitted on drag start

        # hover tracking
        self._hover_handle = False  # true if mouse is over a handle hotspot
        self._hover_range = False  # true if mouse is over a range hotspot
        self._hover_handle_index = -1  # hover index for handle -1 indicates not set
        self._hover_range_handle_pair = None  # hover index pairs
        self._hover_lock = False  # true when a drag operation is in process to keep the hover as-is

        self._tooltip_timer = QtCore.QTimer(self)  # tooltip delay timer (Qt event loop)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.timeout.connect(self._handle_show_tooltip_ui)
        self._tooltip_message = None
        self._tooltip_handle_map = {}  # tooltips to display for the given handle, key is the index of the handle, 0 based
        self._tooltip_range_map = {}  # tooltips for a given range, the key is a tuple of the index two bounding gates (a,b)
        self._desired_height = 32

        self._tick_marks = None
        self._tick_count = 0
        self._show_tick_marks = False # true if tick marks are visible on the widget
        

        self._value_lock = False

        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)

        self._pixmaps = []  # list of pixmap data marker definition objects

        self.adjustSize()

        self._update_pixmaps()
        self._update_targets()
        self.setMarkerValue(0)
        self._update_offsets_ui()
        self._update_all_handle_pixmaps()
        self.setMouseTracking(True)  # track mouse movements



    def unhook(self):
        """cleanup"""
        if self._disposed:
            return
        self._disposed = True
        self.setMouseTracking(False)
        if self._tooltip_timer is not None and Shiboken.isValid(self._tooltip_timer):
            self._tooltip_timer.stop()
            try:
                self._tooltip_timer.timeout.disconnect(self._handle_show_tooltip_ui)
            except (RuntimeError, TypeError):
                pass
        self._tooltip_timer = None
        self._tooltip_message = None
        self._tooltip_handle_map.clear()
        self._tooltip_range_map.clear()
        self._handle_hotspots.clear()
        self._range_hotspots.clear()
        self._range_hotspots_map = {}
        self._drag_active = False
        self._mouse_down = False
        self._drag_handle_index = None
        self._hover_lock = False
        self._hover_handle = False
        self._hover_range = False
        QToolTip.hideText()

    def _is_active(self) -> bool:
        return not self._disposed and Shiboken.isValid(self)

    @property
    def desired_height(self) -> int:
        return self._desired_height

    @desired_height.setter
    def desired_height(self, value: int):
        gremlin.util.InvokeUiMethod(self._set_desired_height_ui, value)

    def _set_desired_height_ui(self, value: int):
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        # Compatibility hint only: Qt minimum/maximum/fixed sizes remain authoritative.
        self._desired_height = max(1, int(value))
        self.updateGeometry()

    def minimumSizeHint(self):
        # Contents scale down to the actual size; do not impose hidden limits.
        return QtCore.QSize(0, 0)

    def sizeHint(self):
        return QtCore.QSize(100, self._desired_height)

    @property
    def values(self) -> list:
        return self._values

    @values.setter
    def values(self, value: int | float | list | tuple):
        self.setValue(value)

    @property
    def singleRange(self):
        return self._single_range

    @singleRange.setter
    def singleRange(self, value):
        if self._single_range != value:
            gremlin.util.InvokeUiMethod(self._set_single_range_ui, value)

    def _set_single_range_ui(self, value):
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        self._single_range = value
        self._update_offsets_ui()
        self.update()

    def setTickCount(self, value: int):
        gremlin.util.InvokeUiMethod(self._set_tick_count_ui, value)

    def _set_tick_count_ui(self, value: int):
        """sets the number of ticks"""
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        value = gremlin.util.clamp(value, 0, 50)
        if self._tick_count != value or self._tick_marks is not None:
            self._tick_marks = None
            self._tick_count = value
            self.update()

    def setTickMarks(self, value: int | list | tuple):
        gremlin.util.InvokeUiMethod(self._set_tick_marks_ui, value)

    def _set_tick_marks_ui(self, value: int | list | tuple):
        """sets the tick marks for the axis as set values"""
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        if isinstance(value, int):
            marks = [value]
        else:
            marks = value if value is not None else []
        if self._tick_marks == marks and self._tick_count == len(marks):
            return
        self._tick_marks = marks or None
        self._tick_count = len(marks)
        self.update()


    def showTickMarks(self, value: bool):
        gremlin.util.InvokeUiMethod(self._show_tick_marks_ui, value)

    def _show_tick_marks_ui(self, value: bool):
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        self._show_tick_marks = value
        self.update()

    def setDrawHandles(self, value: bool):
        if self._draw_handles != value:
            gremlin.util.InvokeUiMethod(self._set_draw_handles_ui, value)

    def _set_draw_handles_ui(self, value: bool):
        """enable/disables the drawing of handles"""
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        self._draw_handles = value
        self._update_hotspots()
        self.update()

    def setHandleIcon(self, index, icon, use_qta=False, color="#a0a0a0"):
        gremlin.util.InvokeUiMethod(self._set_handle_icon_ui, index, icon, use_qta, color)

    def _set_handle_icon_ui(self, index, icon, use_qta=False, color="#a0a0a0"):
        """sets the handle icon - to clear an icon, set it to None

        :param index: the handle index (int)
        :param icon: the QTA name or the png/svg file
        :param use_qta: set to true if the icon is a QTA icon
        :param color: icon color (qta icons only), None if default color

        """

        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        if icon is None:
            # clear the entry
            if index in self._handle_icons:
                del self._handle_icons[index]
                self._internal_handle_pixmaps.pop(index, None)
                self.update()
        else:
            hid = QSliderWidget.HandleIconData(index, icon, use_qta, color)
            self._handle_icons[index] = hid
            self._update_handle_pixmaps(hid)
            self.update()

    def setHandleTooltip(self, index: int, message: str):
        """sets the tooltip for a given handle, to disable, set the message to None
        :param index: index of the handle
        :param message: message to display
        """
        gremlin.util.InvokeUiMethod(self._set_handle_tooltip_ui, index, message)

    def _set_handle_tooltip_ui(self, index: int, message: str):
        if not self._is_active():
            return
        if message is None and index in self._tooltip_handle_map:
            del self._tooltip_handle_map[index]
        else:
            self._tooltip_handle_map[index] = message

    def setRangeTooltip(self, a: int, b: int, message: str):
        """sets the tooltip for a given handle, to disable, set the message to None

        :param a: index of the first handle (left)
        :param b: index of the second handle (right)
        :param message: message to display

        """
        gremlin.util.InvokeUiMethod(self._set_range_tooltip_ui, a, b, message)

    def _set_range_tooltip_ui(self, a: int, b: int, message: str):
        if not self._is_active():
            return
        key = (a, b)
        if message is None and key in self._tooltip_range_map:
            del self._tooltip_range_map[key]
        else:
            self._tooltip_range_map[key] = message

    def setValueIndex(self, index: int, value: int | float):
        gremlin.util.InvokeUiMethod(self._set_value_index_ui, index, value)

    def _set_value_index_ui(self, index: int, value: int | float):
        """sets a specific value by index"""
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return

        value = gremlin.util.clamp(value, self._minimum, self._maximum)
        try:
            values = self._values.copy()
            values[index] = value
            self._set_value_ui(values)
        except Exception:
            syslog.error(f"Unable to set value index {index} - out of index range error")

    def setValue(self, value: int | float | list | tuple):
        gremlin.util.InvokeUiMethod(self._set_value_ui, value)  # ensure on UI thread

    def _set_value_ui(self, value: int | float | list | tuple):
        """input values expected to be -1 to +1 floating point"""
        if not self._is_active():
            return
        if self._value_lock:
            return
        try:
            gremlin.util.assert_ui_thread()
            self._value_lock = True
            values = None
            if isinstance(value, float):
                value = gremlin.util.clamp(value, self._minimum, self._maximum)
                values = [value]
            elif isinstance(value, int):
                value = gremlin.util.clamp(float(value), self._minimum, self._maximum)
                values = [float(value)]
            elif isinstance(value, list):
                values = value
                values = [gremlin.util.clamp(v, self._minimum, self._maximum) for v in values if v is not None]
            elif isinstance(value, tuple):
                values = list(value)
                values = [gremlin.util.clamp(v, self._minimum, self._maximum) for v in values if v is not None]

            changed = False
            if values:
                values.sort()  # sort by value so the values are always in smallest to greatest
                changed = gremlin.util.compare_float_lists(self._values, values)

            if changed:
                verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
                if verbose:
                    syslog.info(f"Slider changed: {self.objectName()} [{self._id}]: {values}")
                self._values = values  # [max(min(1.0, n), -1.0) for n in values]
                self._update_offsets_ui()
                self.update()
        finally:
            self._value_lock = False

    def value(self) -> list:
        """gets the list of values in the slider - a single value is returned as a list of one"""
        return self._values

    def setMarkerVisible(self, value: bool):
        """toggle marker visibility"""
        gremlin.util.InvokeUiMethod(self._set_marker_visible_ui, value)

    def _set_marker_visible_ui(self, value: bool):
        """toggle marker visibility"""
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        if self._marker_visible != value:
            self._marker_visible = value
            self.update()

    @property
    def marker_size(self):
        return self._marker_size

    @marker_size.setter
    def marker_size(self, value):
        if value > 0 and self._marker_size != value:
            gremlin.util.InvokeUiMethod(self._set_marker_size_ui, value)

    def _set_marker_size_ui(self, value):
        """sets the relative size of the marker"""
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        self._marker_size = value
        self._update_pixmaps()
        self._update_marker_offsets_ui()
        self.update()

    def setReadOnly(self, value: bool):
        gremlin.util.InvokeUiMethod(self._set_read_only_ui, value)

    def _set_read_only_ui(self, value: bool):
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        self._readOnly = value

    def readOnly(self) -> bool:
        return self._readOnly

    def singleStep(self) -> float:
        return self._single_step

    def setSingleStep(self, value: float):
        """Sets the value change for one mouse wheel notch."""
        gremlin.util.InvokeUiMethod(self._set_single_step_ui, value)

    def _set_single_step_ui(self, value: float):
        gremlin.util.assert_ui_thread()
        if not self._is_active() or value <= 0:
            return
        self._single_step = float(value)

    def _update_offsets_ui(self):
        """recomputes pixel offsets based on gate values"""
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        size = self.size()
        widget_width = size.width()
        widget_height = size.height()
        margin = min(4, widget_width // 2, widget_height // 2)  # fit narrow/short widgets
        usable_width = widget_width - margin
        range_width = usable_width - margin
        usable_margin = int((widget_width - range_width) * 0.5)

        gate_positions = []

        if len(self._values) == 0:
            return

        handle_count = len(self._values)

        # handle sizes
        max_icon_size = min(widget_height, widget_width) - 2 * margin
        handle_size = 24
        handle_size = max(0, min(handle_size, max_icon_size))
        self._handle_radius = int(handle_size * 0.5)
        self._handle_size = self._handle_radius * 2
        self._handle_top = int((widget_height - self._handle_size) * 0.5)

        self._handle_count = handle_count
        self._widget_width = widget_width
        self._widget_height = widget_height
        self._widget_corner = int(widget_height * 0.5)

        # compute the max range geometry boundaries (horizontal only)
        self._usable_width = range_width
        self._usable_margin = int(handle_size * 0.5) + usable_margin  # account for handle diameter
        self._usable_left = self._usable_margin
        self._usable_right = max(self._usable_left, widget_width - self._usable_margin)

        # print (f"Range width: {self._usable_width} range left: {self._usable_left} range right: {self._usable_right}  range width: {self._usable_width}  widget width: {widget_width}  height {widget_height} handle diameter: {handle_size} radius: {self._handle_radius}")

        # handle_offsets = []
        for value in self._values:
            x = (
                self._usable_left
                if self._minimum == self._maximum
                else gremlin.util.scale_to_range(
                    value,
                    source_min=self._minimum,
                    source_max=self._maximum,
                    target_min=self._usable_left,
                    target_max=self._usable_right,
                )
            )
            gate_positions.append(x - self._handle_radius)
            # handle_offsets.append((value, x))

        # print(f"Handle offset: {handle_offsets}")

        # leftmost position of the first gate
        if len(gate_positions) == 1:
            # single gate - use the whole range
            self._range_left = self._usable_left
            self._range_right = self._usable_right
        else:
            # two or more gates
            self._range_left = gate_positions[0] + self._handle_radius
            self._range_right = gate_positions[-1] + self._handle_radius

        self._handle_min = self._usable_left - self._handle_radius
        self._handle_max = self._usable_right - self._handle_radius
        self._range_width = self._range_right - self._range_left
        self._range_height = int(self._handle_size * 0.6)
        self._range_corner = int(self._range_height * 0.33)
        self._range_top = int((widget_height - self._range_height) * 0.5)
        self._handle_positions = gate_positions
        # print (f"Range left: {self._range_left}  right: {self._range_right}  width: {self._range_width} height: {self._range_height} top margin: {self._range_top}")
        self._update_marker_offsets_ui()
        self._update_hotspots()
        if getattr(self, "_icon_geometry", None) != (self._handle_size, widget_height):
            self._icon_geometry = (self._handle_size, widget_height)
            self._update_pixmaps()
            self._update_all_handle_pixmaps()

    def _update_hotspots(self):
        """Hit targets depend on geometry, not on paint frequency."""
        self._handle_hotspots = []
        self._range_hotspots = []
        self._range_hotspots_map = {}
        positions = self._handle_positions
        if not positions:
            return
        pairs = [(0, len(positions) - 1)] if self._single_range else pairwise(range(len(positions)))
        for a, b in pairs:
            x1, x2 = positions[a], positions[b]
            left = x1 + self._handle_radius
            if self._single_range and not self._draw_handles:
                left = x1 - self._handle_radius
                x1 -= self._handle_radius
                x2 += self._handle_radius
            rect = QRect(int(left), int(self._range_top), int(x2 - x1), int(self._range_height))
            self._range_hotspots.append(rect)
            self._range_hotspots_map[rect] = (a, b)
        if self._draw_handles:
            self._handle_hotspots = [QRect(int(x), self._handle_top, self._handle_size, self._handle_size) for x in positions]

    def _update_marker_offsets_ui(self):
        if not self._marker_pos:
            self._int_marker_pos = []
            return
        if self._marker_pos:
            # compute marker positions
            source_min = self._minimum
            source_max = self._maximum
            if source_max == source_min:
                self._int_marker_pos = [self._usable_left for _ in self._marker_pos]
                return
            target_min = self._usable_left  # self._to_qinteger_space(self._range_left)
            target_max = self._usable_right  # self._to_qinteger_space(self._range_right)
            factor = (target_max - target_min) / (source_max - source_min)
            self._int_marker_pos = [(v - source_min) * factor + target_min for v in self._marker_pos]
            # print (f"marker: {[v for v in self._int_marker_pos]}")

    def _update_targets(self):
        """update target positions"""
        self._target_min = self._minimum  # self._to_qinteger_space(self._minimum)
        self._target_max = self._maximum  # self._to_qinteger_space(self._maximum)

    def setMarkerValue(self, value):
        gremlin.util.InvokeUiMethod(self._set_marker_value_ui, value)

    def _set_marker_value_ui(self, value):
        """sets the marker(s) value - single float is one marker, passing a tuple creates multiple markers"""
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        if isinstance(value, (float, int)):
            values = [value]
        else:
            values = list(value) if value is not None else []
        clamp = gremlin.util.clamp
        values = [clamp(v, self._minimum, self._maximum) for v in values if v is not None]
        if values == self._marker_pos:
            return
        self._marker_pos = values
        self._update_marker_offsets_ui()
        if self._marker_visible:
            self.update()

    def markerValue(self) -> float:
        """gets the marker value"""
        return self._marker_pos

    def minimum(self) -> float:  # type: ignore
        """gets the slider's minimum value"""
        return self._minimum

    def setMinimum(self, value: float) -> None:
        """sets the slider's minimum value"""
        gremlin.util.InvokeUiMethod(self._set_minimum_ui, value)

    def _set_minimum_ui(self, value: float):
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        self._minimum = value
        if self._maximum < self._minimum:
            self._maximum, self._minimum = self._minimum, self._maximum
        self._update_targets()
        self._update_offsets_ui()
        self.update()

    def maximum(self) -> float:  # type: ignore
        """gets the slider's maximum value"""
        return self._maximum

    def setMaximum(self, value: float) -> None:
        gremlin.util.InvokeUiMethod(self._set_maximum_ui, value)

    def _set_maximum_ui(self, value: float) -> None:
        """sets the slider's maximum value"""
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        self._maximum = value
        if self._maximum < self._minimum:
            self._maximum, self._minimum = self._minimum, self._maximum
        self._update_targets()
        self._update_offsets_ui()
        self.update()

    def setRange(self, range_min: float, range_max: float):
        gremlin.util.InvokeUiMethod(self._set_range_ui, range_min, range_max)

    def _set_range_ui(self, range_min: float, range_max: float):
        """sets the slider's min/max values

        :param range_min: min range (float)
        :param range_max: max range (float)

        """
        gremlin.util.assert_ui_thread()
        if not self._is_active():
            return
        if range_min > range_max:
            # swap
            range_max, range_min = range_min, range_max
        self._minimum = range_min
        self._maximum = range_max
        self._update_targets()
        self._update_offsets_ui()
        self.update()

    def range(self):
        """returns the range of the slider"""
        return (self._minimum, self._maximum)

    def paintEvent(self, event: QPaintEvent):
        """paint event

        :param event: QPaintEvent object

        """
        if not self._is_active():
            return
        # draw the widget
        # syslog.info("slider paint start")

        painter = QPainter(self)
        # painter.begin(self)
        painter.setRenderHint(QPainter.Antialiasing)

        self._draw_widget(painter)
        if self._show_tick_marks and self._tick_count > 0:
            # draw the tick marks
            self._draw_ticks(painter)
        if self._marker_visible:
            self._draw_markers(painter)

        painter.end()
        # syslog.info("slider paint end")

    def getBackgroundColor(self) -> QColor:
        """
        Get the background color of the progress bar.

        :return: QColor object representing the background color.
        """
        return self.BackgroundColor

    def getFinishedBackgroundColor(self) -> QColor:
        """
        Get the color for finished progress bar segments.

        :return: QColor object representing the finished segment color.
        """
        return self.rangeColor

    def getFinishedNumberColor(self) -> QColor:
        """
        Get the color for finished numbers in the progress bar.

        :return: QColor object representing the finished number color.
        """
        return self.handleColor

    def _get_paint_resources(self):
        colors = (self.handleBorderColor, self.rangeBorderColor, self.handleColor, self.rangeColor, self.rangeAlternateColor, self.getBackgroundColor())
        key = tuple(color.rgba() for color in colors) + (self._handle_size, self._range_height, self.UseAlternateColor)
        if getattr(self, "_paint_resource_key", None) == key:
            return self._paint_resources
        handle_pen = QPen(QBrush(self.handleBorderColor), self._handle_size * 0.1)
        range_pen = QPen(QBrush(self.rangeBorderColor), self._range_height * 0.1)
        handle_pen_h = QPen(
            QBrush(gremlin.util.highlight_qcolor(self.handleBorderColor)),
            self._handle_size * 0.1,
        )
        range_pen_h = QPen(
            QBrush(gremlin.util.highlight_qcolor(self.rangeBorderColor)),
            self._range_height * 0.1,
        )

        handle_fill = QBrush(self.handleColor)
        handle_fill_h = QBrush(gremlin.util.highlight_qcolor(self.handleColor))

        if self.UseAlternateColor:
            range_colors = [self.rangeColor, self.rangeAlternateColor]
            range_colors_h = [
                gremlin.util.highlight_qcolor(self.rangeColor),
                gremlin.util.highlight_qcolor(self.rangeAlternateColor),
            ]
        else:
            color_h = gremlin.util.highlight_qcolor(self.rangeColor)
            range_colors = [self.rangeColor, self.rangeColor]
            range_colors_h = [color_h, color_h]

        backgroundBrush = QBrush(self.getBackgroundColor())
        emptyPen = QPen(Qt.NoPen)

        self._paint_resource_key = key
        self._paint_resources = (
            handle_pen,
            range_pen,
            handle_pen_h,
            range_pen_h,
            handle_fill,
            handle_fill_h,
            range_colors,
            range_colors_h,
            backgroundBrush,
            emptyPen,
        )
        return self._paint_resources

    def _draw_widget(self, painter: QPainter):
        """
        Draw the progress bar with Circular or Square style.

        :param painter: QPainter object.
        """
        handle_count = self._handle_count

        (handle_pen, range_pen, handle_pen_h, range_pen_h, handle_fill, handle_fill_h, range_colors, range_colors_h, backgroundBrush, emptyPen) = (
            self._get_paint_resources()
        )

        # slider background
        painter.setPen(emptyPen)
        painter.setBrush(backgroundBrush)
        painter.drawRoundedRect(
            0,
            0,
            self._widget_width,
            self._widget_height,
            self._widget_corner,
            self._widget_corner,
        )

        # slider range - from the leftmost handle to the rightmost handle

        # draw ranges of different colors
        color_index = 0
        # color_count = len(range_colors)
        painter.setPen(range_pen)
        msg = ""
        range_height = self._range_height
        range_corner = 0
        range_top = self._range_top

        if self._single_range:
            # single range used across all gates
            color_fill = range_colors[color_index]
            color_pen = self.rangeBorderColor
            if self._hover_range:
                color_fill = range_colors_h[color_index]
                color_pen = range_pen_h

            painter.setBrush(color_fill)
            painter.setPen(color_pen)
            a = 0
            b = handle_count - 1

            x1 = self._handle_positions[a]
            x2 = self._handle_positions[b]

            if self._draw_handles:
                range_left = x1 + self._handle_radius
            else:
                range_left = x1 - self._handle_radius
                x1 -= self._handle_radius
                x2 += self._handle_radius

            range_width = x2 - x1

            painter.drawRoundedRect(
                range_left,
                range_top,
                range_width,
                range_height,
                range_corner,
                range_corner,
            )

        else:
            # individual ranges between handles
            color_index = 0
            for a, b in pairwise(range(handle_count)):
                x1 = self._handle_positions[a]
                x2 = self._handle_positions[b]

                color_fill = range_colors[color_index]
                # print (f"range color index: {color_index}")
                color_pen = self.rangeBorderColor
                if self._hover_range:
                    ah, bh = self._hover_range_handle_pair
                    if a == ah and b == bh:
                        # highlight on hover
                        # print (f"hover range {a} {b}")
                        color_fill = range_colors_h[color_index]
                        color_pen = range_pen_h

                painter.setBrush(color_fill)
                painter.setPen(color_pen)

                color_index = (color_index + 1) % 2

                range_left = x1 + self._handle_radius
                range_width = x2 - x1

                painter.drawRoundedRect(
                    range_left,
                    range_top,
                    range_width,
                    range_height,
                    range_corner,
                    range_corner,
                )

        self._range_msg = msg

        if self._draw_handles:
            for index in range(handle_count):
                is_hover = self._hover_handle and self._hover_handle_index == index
                if is_hover:
                    color_fill = handle_fill_h
                    color_pen = handle_pen_h

                else:
                    color_fill = handle_fill
                    color_pen = handle_pen

                painter.setBrush(color_fill)
                painter.setPen(color_pen)

                x = self._handle_positions[index]
                # clickable areas
                handle_rect = self._handle_hotspots[index]
                painter.drawEllipse(handle_rect)

                # handle icons
                if index in self._internal_handle_pixmaps:
                    # pick the regular or highlighted icon
                    pd = self._internal_handle_pixmaps[index][1 if is_hover else 0]
                    painter.drawPixmap(
                        x + self._handle_radius + pd.offset_x,
                        self._handle_top + pd.offset_y,
                        pd.pixmap,
                    )

    def _draw_markers(self, painter: QPainter):
        """draws the markers on the widget"""
        positions = self._int_marker_pos
        center = int(self.height() * 0.66)

        pixmaps = self._get_pixmaps()
        p_count = len(pixmaps)
        for index, value in enumerate(positions):
            if index < p_count:
                pd = pixmaps[index]
                ratio = pd.pixmap.devicePixelRatio()
                width = pd.pixmap.width() / ratio
                height = pd.pixmap.height() / ratio
                if width <= 0 or height <= 0 or self.height() <= center:
                    continue
                # Also fit caller-supplied marker pixmaps, preserving their aspect
                # ratio and offsets without resampling them on every paint.
                factor = min(
                    1.0,
                    (self.height() - center) / max(height, pd.offset_y + height),
                    (2 * self._usable_margin) / max(width, 2 * abs(pd.offset_x), 2 * abs(pd.offset_x + width)),
                )
                painter.drawPixmap(
                    QtCore.QRectF(value + pd.offset_x * factor, center + pd.offset_y * factor, width * factor, height * factor),
                    pd.pixmap,
                    QtCore.QRectF(pd.pixmap.rect()),
                )

    def _draw_ticks(self, painter: QPainter):
        """draws the tick markers"""
        tick_pen = QPen(QBrush(self.tickColor), 1)
        painter.setPen(tick_pen)

        count = self._tick_count

        x1 = self._handle_min + self._handle_radius
        x2 = self._handle_max + self._handle_radius
        center = int(self.height() * 0.66)
        width = x2 - x1

        if count > 0:
            y1 = center
            y2 = int(self.height() * (10 / 32))

            if self._tick_marks:
                # variable spaced
                for value in self._tick_marks:
                    if self._minimum <= value <= self._maximum:
                        x = gremlin.util.scale_to_range(value, self._minimum, self._maximum, x1, x2)
                        p1 = QPoint(x, y1)
                        p2 = QPoint(x, y2)
                        painter.drawLine(p1, p2)
            else:
                # equally spaced
                if count == 1:
                    p1 = QPoint(x1 + (width * 0.5), y1)
                    p2 = QPoint(x1 + (width * 0.5), y2)
                    painter.drawLine(p1, p2)
                    return

                interval = width / (count - 1)
                x = x1
                for _ in range(self._tick_count):
                    p1 = QPoint(x, y1)
                    p2 = QPoint(x, y2)
                    painter.drawLine(p1, p2)
                    x += interval

        # horizontal line
        p1 = QPoint(x1, y1)
        p2 = QPoint(x2, y1)
        painter.drawLine(p1, p2)

    def resizeEvent(self, event):
        """called on resize"""
        if not self._is_active():
            return
        super().resizeEvent(event)
        self._update_offsets_ui()
        self.update()

    def _mouse_position_to_value(self, x):
        """converts a mouse position to a slider value"""
        if x >= self._usable_left and x <= self._usable_right:
            # x is in the "value" zone
            if self._usable_left == self._usable_right:
                return self._minimum
            value = gremlin.util.scale_to_range(x, self._usable_left, self._usable_right, self._minimum, self._maximum)
            # print (f"click value: {x} -> {value}")
            return value
        # not in range
        # print (f"not in range click value: {x} -> N/A")
        return None

    def _get_min_max_handles(self):
        """Values are stored in ascending order."""
        return (0, len(self._values) - 1)

    def _hover_enter_range(self, a, b):
        """enters a range"""
        self._hover_exit_handle()
        self._hover_exit_range()
        # print (f"hover enter range: {a} {b}")
        self._hover_range = True
        self._hover_range_handle_pair = (a, b)
        return True

    def _hover_exit_range(self):
        """exists a range"""
        if self._hover_range:
            # no longer hovering over a range
            # print (f"hover exit range: {self._hover_range_handle_pair}")
            self._hover_range = False  # not over a range
            self._hover_range_handle_pair = None
            return True
        return False

    def _hover_enter_handle(self, index):
        """enters a handle"""
        self._hover_exit_range()
        self._hover_exit_handle()
        # print (f"hover enter handle: {index}")
        self._hover_handle = True
        self._hover_handle_index = index
        return True

    def _hover_exit_handle(self):
        """exits a handle"""
        if self._hover_handle:
            # print (f"hover exit handle: {self._hover_handle_index}")
            self._hover_handle = False
            self._hover_handle_index = -1
            return True
        return False

    def _show_tooltip(self, message: str):
        if not self._is_active():
            return
        gremlin.util.InvokeUiMethod(self._show_tooltip_ui, message)

    def _show_tooltip_ui(self, message: str):
        gremlin.util.assert_ui_thread()
        if not self._is_active() or not Shiboken.isValid(self._tooltip_timer):
            return
        self._tooltip_message = message
        self._tooltip_timer.stop()
        self._tooltip_timer.start(1000)

    def _handle_show_tooltip_ui(self):
        if self._is_active() and self._tooltip_message:
            gremlin.util.assert_ui_thread()
            QToolTip.showText(QCursor.pos(), self._tooltip_message, self)

    def _hover_update(self, event: QMouseEvent | QtGui.QWheelEvent):
        """updates the hover state"""
        hover_changed = False
        if self._readOnly:
            # no hovering in readonly mode
            return

        if not self._hover_lock:
            is_hover = False
            rect: QRect

            point: QPoint = event.position().toPoint()
            # look for hover entry/exit on handles first
            for index, rect in enumerate(self._handle_hotspots):
                if rect.contains(point):
                    if self._hover_handle_index != index:
                        hover_changed = self._hover_exit_handle() or hover_changed
                        hover_changed = self._hover_exit_range() or hover_changed
                        hover_changed = self._hover_enter_handle(index) or hover_changed
                        # tooltip
                        if index in self._tooltip_handle_map:
                            self._show_tooltip(self._tooltip_handle_map[index])

                    is_hover = True
                    break

            if not is_hover:
                # print (f"mouse {point} {self._range_msg}")

                # scan for hovering over a range
                for rect in self._range_hotspots:
                    if rect.contains(point):
                        a, b = self._range_hotspots_map[rect]
                        if self._hover_range_handle_pair is None or self._hover_range_handle_pair != (a, b):
                            hover_changed = self._hover_exit_handle() or hover_changed
                            hover_changed = self._hover_exit_range() or hover_changed
                            hover_changed = self._hover_enter_range(a, b) or hover_changed
                            key = (a, b)
                            if key in self._tooltip_range_map:
                                self._show_tooltip(self._tooltip_range_map[key])
                        is_hover = True
                        break

            if not is_hover:
                hover_changed = self._hover_exit_handle() or hover_changed
                hover_changed = self._hover_exit_range() or hover_changed
                self._tooltip_message = None
                if self._tooltip_timer is not None:
                    self._tooltip_timer.stop()
                QToolTip.hideText()

        return hover_changed

    def event(self, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.Wheel:
            # Dispatch to wheelEvent before preventing propagation to the parent.
            super().event(event)
            event.accept()
            return True
        return super().event(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Moves the handle nearest the pointer in the wheel direction."""
        event.accept()
        if not self._is_active() or self._readOnly or not self.isEnabled() or not self._draw_handles or self._drag_active:
            return
        gremlin.util.assert_ui_thread()
        if not self._values or not self._handle_positions:
            return

        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        x = event.position().x()
        index = min(range(len(self._values)), key=lambda i: abs(self._handle_positions[i] + self._handle_radius - x))
        old_value = self._values[index]
        value = gremlin.util.clamp(old_value + steps * self._single_step, self._minimum, self._maximum)
        if value == old_value:
            return

        # Match dragging: keep handles sorted and report the updated index.
        self._values.pop(index)
        new_index = bisect_left(self._values, value) if value > old_value else bisect_right(self._values, value)
        self._values.insert(new_index, value)
        self._update_offsets_ui()
        self._hover_update(event)
        self.update()
        self.valueChanged.emit(new_index, value)

    def mouseDoubleClickEvent(self, event):
        """double click event"""
        if not self._is_active() or self._readOnly:
            # don't fire events in readonly mode
            # print ("readonly - skip mousepress")
            return

        # print ("double click")
        self._double_clicked = True

        verbose = gremlin.config.Configuration().verbose_mode_ui_level(1)
        if verbose:
            syslog = logging.getLogger("system")

        point = event.pos()
        # print("Mouse click coordinates:", point)  # Debug print
        for index, rect in enumerate(self._handle_hotspots):
            if rect.contains(point):
                button = event.button()
                if button == Qt.MouseButton.LeftButton:
                    if verbose:
                        syslog.info(f"handle {index} left double clicked")
                    self.handleDoubleClicked.emit(index)

                elif button == Qt.MouseButton.RightButton:
                    if verbose:
                        syslog.info(f"handle {index} right rouble clicked")
                    self.handleDoubleRightClicked.emit(index)
                return

        # check ranges
        # print (f"mouse point: {point}")
        for index, rect in enumerate(self._range_hotspots):
            # print (f"{rect}")
            if rect.contains(point):
                a, b = self._range_hotspots_map[rect]
                value = self._mouse_position_to_value(point.x())
                if value is not None:
                    button = event.button()
                    if button == Qt.MouseButton.LeftButton:
                        if verbose:
                            syslog.info(f"range left double clicked: {value}")
                        self.rangeDoubleClicked.emit(value, a, b)
                    elif button == Qt.MouseButton.RightButton:
                        if verbose:
                            syslog.info(f"range right double clicked: {value}")
                        self.rangeDoubleRightClicked.emit(value, a, b)

                    return

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """mouse press event handler
        :param event: QMouseEvent object.

        """
        # print ("mouse press")
        if not self._is_active() or self._readOnly:
            # don't fire events in readonly mode
            return

        point = event.pos()
        for index, rect in enumerate(self._handle_hotspots):
            if rect.contains(point):
                # gate clicked

                self._mouse_down = True
                self._drag_active = True
                self._drag_handle_index = index  # current handle index of the handle bring dragged
                self._drag_start = point
                # store the x offset where the drag started occuring
                self._drag_x_offset = self._handle_positions[index] - point.x()
                self._drag_last_point = point
                self._drag_x = point.x()
                self._hover_lock = True  # lock the current hover mode
                self._drag_emit = False
                break

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._is_active() or self._readOnly:
            return
        point: QPoint = event.pos()

        # process mouse movement for hover
        hover_changed = self._hover_update(event)

        if event.buttons() == QtCore.Qt.LeftButton:
            # left mouse drag operation
            point = event.pos()
            x = point.x()

            if not self._drag_active and self._mouse_down and abs(self._drag_x - x) > 2:  # move at least 3 pixels
                # drag started
                self._drag_active = True
                self._drag_emit = False
                # print ("mouse drag starting")

            if self._drag_active:
                if self._drag_x != x:
                    # mouse moved
                    # print ("mouse drag detected")
                    if not self._drag_emit:
                        # only emit if there is an actual move drag happening
                        self.handleDragStart.emit(self._drag_handle_index)  # fire the drag start event
                        self._drag_emit = True

                    current_x = x + self._drag_x_offset

                    # drag bounds check
                    if current_x < self._handle_min:
                        current_x = self._handle_min
                    elif current_x > self._handle_max:
                        current_x = self._handle_max

                    value = self._mouse_position_to_value(current_x + self._handle_radius)

                    # get the index of the value relative to the other gates
                    old_value = self._values[self._drag_handle_index]
                    # print (f"Current x: {old_x} -> {current_x}  offset: {x_offset}  old value: {old_value}  new value: {value}")
                    if old_value != value:
                        self._values.pop(self._drag_handle_index)
                        if value > old_value:
                            new_index = bisect_left(self._values, value)
                        else:
                            new_index = bisect_right(self._values, value)
                        self._values.insert(new_index, value)
                        self._drag_handle_index = new_index
                        self._drag_x = x
                        self._update_offsets_ui()

                        # fire the gate value change
                        self.valueChanged.emit(self._drag_handle_index, value)

                    hover_changed = True

        if hover_changed:
            # update colors/state
            # print("hover changed")
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """
        Mouse release event handler.

        :param event: QMouseEvent object.
        """

        # print ("mouse release")
        if not self._is_active() or self._readOnly:
            # don't fire events in readonly mode
            # print ("readonly - skip mouse release")
            return

        self._mouse_down = False
        if self._double_clicked:
            self._double_clicked = False
            # ignore mouse releases on double click
            return

        verbose = gremlin.config.Configuration().verbose
        if verbose:
            syslog = logging.getLogger("system")

        if self._drag_active:
            # stop drag
            # print ("stop drag")
            self._hover_lock = False
            self._drag_active = False
            self._values.sort()  # update any values
            self._hover_update(event)
            self.update()  # get the updated hotspots
            button = event.button()
            index = self._drag_handle_index
            if self._drag_emit:
                # drag emit was sent, emit the stop event
                self.handleDragStop.emit(index)
                self._drag_emit = False
            if button == Qt.MouseButton.LeftButton:
                # if verbose:
                #     syslog.info(f"handle {index} left clicked")
                self.handleClicked.emit(index)
            elif button == Qt.MouseButton.RightButton:
                # if verbose:
                #     syslog.info(f"handle {index} right clicked")
                self.handleRightClicked.emit(index)
            return

        point = event.pos()
        # print("Mouse click coordinates:", point)  # Debug print
        for index, rect in enumerate(self._handle_hotspots):
            if rect.contains(point):
                button = event.button()
                if button == Qt.MouseButton.LeftButton:
                    # if verbose:
                    #     syslog.info(f"handle {index} left clicked")
                    self.handleClicked.emit(index)
                elif button == Qt.MouseButton.RightButton:
                    # if verbose:
                    #     syslog.info(f"handle {index} right clicked")
                    self.handleRightClicked.emit(index)
                return

        # check ranges
        # print (f"mouse point: {point}")
        for index, rect in enumerate(self._range_hotspots):
            # print (f"{rect}")
            if rect.contains(point):
                a, b = self._range_hotspots_map[rect]
                value = self._mouse_position_to_value(point.x())
                if value is not None:
                    button = event.button()
                    if button == Qt.MouseButton.LeftButton:
                        if verbose:
                            syslog.info(f"range left clicked: {value}")
                        self.rangeClicked.emit(value, a, b)
                    elif button == Qt.MouseButton.RightButton:
                        if verbose:
                            syslog.info(f"range right clicked: {value}")
                        self.rangeRightClicked.emit(value, a, b)
                    return

    class PixmapData:
        """holds a pixmap definition"""

        def __init__(self, pixmap: QtGui.QPixmap = None, offset_x=None, offset_y=None):
            self.pixmap = pixmap
            self.offset_x = offset_x
            self.offset_y = offset_y
            if pixmap is not None:
                self.width = pixmap.width()
                self.height = pixmap.height()
            else:
                self.width = 0
                self.height = 0

    class HandleIconData:
        def __init__(self, index: int, icon: str, use_qta: bool = True, color="#808080"):
            self.index = index
            self.icon = icon
            self.use_qta = use_qta
            self.color = color

    def _get_pixmaps(self):
        if self._pixmaps:
            return self._pixmaps
        return self._internal_pixmaps

    @staticmethod
    def _fit_icon_pixmap(pixmap, width, height):
        """Fit in logical pixels without stretching or losing high-DPI resolution."""
        ratio = pixmap.devicePixelRatio()
        return pixmap.scaled(
            max(1, int(width * ratio)),
            max(1, int(height * ratio)),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )

    def _update_pixmaps(self):
        icon = gremlin.util.load_icon("ei.chevron-up")
        pixmap = icon.pixmap(max(1, int(self.marker_size)))
        # Markers start below the groove. Fit the remaining space, including
        # the horizontal margin at either end of the slider.
        top = int(self.height() * 0.66)
        width = max(1, min(self.marker_size, self._handle_size + 8)) if hasattr(self, "_handle_size") else self.marker_size
        pixmap = self._fit_icon_pixmap(pixmap, width, max(1, self.height() - top))
        pd = QSliderWidget.PixmapData(
            pixmap=pixmap,
            offset_x=-pixmap.width() / pixmap.devicePixelRatio() / 2,
            offset_y=0,
        )
        self._internal_pixmaps = [pd]

    def _update_handle_pixmaps(self, hid: QSliderWidget.HandleIconData):  # noqa: F821
        """updates the pixmaps for the handle icons

        two versions of the icon are loaded, a regular and highlighted version

        """
        if self._handle_size <= 0:
            self._internal_handle_pixmaps.pop(hid.index, None)
            return
        icon_size = max(1, int(self._handle_size * 0.75))
        # hex_color = "#323232" # default QTA is rgb 50,50,50
        hex_color = hid.color
        color = QColor(hex_color)
        color_h = gremlin.util.highlight_qcolor(color, factor=1.4)
        icon = gremlin.util.load_icon(hid.icon, qta_color=color)
        icon_h = gremlin.util.load_icon(hid.icon, qta_color=color_h)
        pixmap = self._fit_icon_pixmap(icon.pixmap(icon_size), icon_size, icon_size)
        pixmap_h = self._fit_icon_pixmap(icon_h.pixmap(icon_size), icon_size, icon_size)

        def centered_data(image):
            ratio = image.devicePixelRatio()
            return QSliderWidget.PixmapData(
                pixmap=image,
                offset_x=-image.width() / ratio / 2,
                offset_y=(self._handle_size - image.height() / ratio) / 2,
            )

        pd = centered_data(pixmap)
        pd_h = centered_data(pixmap_h)
        self._internal_handle_pixmaps[hid.index] = (pd, pd_h)

    def _update_all_handle_pixmaps(self):
        """updates all handle icons on resize/update"""
        for hid in self._handle_icons.values():
            self._update_handle_pixmaps(hid)
