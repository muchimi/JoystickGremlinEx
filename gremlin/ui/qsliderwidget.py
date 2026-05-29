# implements a custom multi-gate slider widget
# from __future__ import annotations # deprecated with python 3.14+
import threading
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

from itertools import pairwise

syslog = logging.getLogger("system")


class QSliderWidget(QtWidgets.QWidget):
    """custom slider object --- WARNING : ALL EVENT HANDLERS NEED TO CHECK FOR UI THREAD"""

    handleClicked = QtCore.Signal(
        int
    )  # called when a handle is left clicked (handle index)
    handleRightClicked = QtCore.Signal(
        int
    )  # called when a handle is right clicked (handle index)
    handleDoubleClicked = QtCore.Signal(
        int
    )  # called when a handle is double clicked (handle index)
    handleDoubleRightClicked = QtCore.Signal(
        int
    )  # called when a handle is double clicked with the right mouse button (handle index)
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
    valueChanged = QtCore.Signal(
        int, float
    )  # called when a gate value changes via dragging (index of handle, updated value)
    handleDragStart = QtCore.Signal(
        int
    )  # called when a handle is being dragged (handle index)
    handleDragStop = QtCore.Signal(
        int
    )  # called when a handle stops being dragged (handle index)

    # handleClicked = Signal(int) # called when a handle is left clicked (handle index)
    # handleRightClicked = Signal(int) # called when a handle is right clicked (handle index)
    # handleDoubleClicked = Signal(int) # called when a handle is double clicked (handle index)
    # handleDoubleRightClicked = Signal(int) # called when a handle is double clicked with the right mouse button (handle index)
    # rangeClicked = Signal(float, int, int) # called when a groove is clicked (between handles) - sends the value of the slider where clicked - (value, left handle index, right handle index)
    # rangeRightClicked = Signal(float, int, int) # called when a range is right clicked (between handles) - sends the value of the slider where clicked - (value, left handle index, right handle index)
    # rangeDoubleClicked = Signal(float, int, int) # called when a range is double clicked (between handles) - sends the value of the slider where clicked - (value, left handle index, right handle index)
    # rangeDoubleRightClicked = Signal(float, int, int) # called when a range is double clicked with the right mouse button (between handles) - sends the value of the slider where clicked - (value, left handle index, right handle index)
    # valueChanged = Signal(int, float) # called when a gate value changes via dragging (index of handle, updated value)
    # handleDragStart = Signal(int) # called when a handle is being dragged (handle index)
    # handleDragStop = Signal(int) # called when a handle stops being dragged (handle index)

    def __init__(self, object_name=None, parent=None):
        import gremlin.ui.ui_common

        super().__init__(parent)
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
        self._draw_handles = True
        self.setObjectName(object_name if object_name else "QSliderWidget")

        self._tick_count = 0  # no ticks

        self.handleColor = QColor(
            gremlin.ui.ui_common.Color.sliderHandleColor()
        )  # QColor("#a7b59e")
        self.tickColor = QColor(
            gremlin.ui.ui_common.Color.sliderTickColor()
        )  # QColor("#232323")
        self.handleBorderColor = QColor(
            gremlin.ui.ui_common.Color.sliderHandleBorderColor()
        )  # QColor("#e0e0e0")
        self.rangeBorderColor = QColor(
            gremlin.ui.ui_common.Color.sliderRangeBorderColor()
        )  # QColor("#e0e0e0")
        self.rangeColor = QColor(
            gremlin.ui.ui_common.Color.sliderRangeColor()
        )  # QColor("8fb9bc")
        self.rangeAlternateColor = QColor(
            gremlin.ui.ui_common.Color.sliderAlternateRangeColor()
        )  # QColor("#8fb9bc")
        self.UseAlternateColor = True  # alternate range colors
        self.BackgroundColor = QColor(
            gremlin.ui.ui_common.Color.sliderBackgroundColor()
        )  # QColor("#c3c3c3")

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
        self._range_width = (
            0  # width of the bar between min gate and max gate in pixels
        )
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
        self._drag_x_offset = (
            0  # offset in pixels of the mouse position to the center of the gate
        )
        self._drag_emit = False  # true if the drag event was emitted on drag start

        # hover tracking
        self._hover_handle = False  # true if mouse is over a handle hotspot
        self._hover_range = False  # true if mouse is over a range hotspot
        self._hover_handle_index = -1  # hover index for handle -1 indicates not set
        self._hover_range_handle_pair = None  # hover index pairs
        self._hover_lock = (
            False  # true when a drag operation is in process to keep the hover as-is
        )

        self._tooltip_timer = None  # tooltip delay timer
        self._tooltip_handle_map = {}  # tooltips to display for the given handle, key is the index of the handle, 0 based
        self._tooltip_range_map = {}  # tooltips for a given range, the key is a tuple of the index two bounding gates (a,b)
        self._desired_height = 32

        self._tick_marks = None
        self._tick_count = 0

        self._value_lock = False

        # self.sizePolicy().setHorizontalPolicy(QtWidgets.QSizePolicy.Expanding)

        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

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
        self.setMouseTracking(False)
        if self._tooltip_timer:
            self._tooltip_timer.cancel()

    @property
    def desired_height(self) -> int:
        return self._desired_height

    @desired_height.setter
    def desired_height(self, value: int):
        gremlin.util.InvokeUiMethod(self._set_desired_height_ui, value)

    def _set_desired_height_ui(self, value: int):
        self._desired_height = value
        self.resize(self.minimumSizeHint())

    def minimumSizeHint(self):
        """
        Minimum size of the widget in pixels

        Returns:
            Minimum widget size (Qsize)
        """
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
        self._single_range = value
        self._update_offsets_ui()
        self.update()

    def setTickCount(self, value: int):
        gremlin.util.InvokeUiMethod(self._set_tick_count, value)

    def _set_tick_count(self, value: int):
        """sets the number of ticks"""
        value = gremlin.util.clamp(value, 0, 50)
        if self._tick_count != value:
            self._tick_count = value
            self.update()

    def setTickMarks(self, value: int):
        gremlin.util.InvokeUiMethod(self._set_tick_marks_ui, value)

    def _set_tick_marks_ui(self, value: int):
        """sets the tick marks for the axis as set values"""
        if value:
            self._tick_marks = value
            self._tick_count = len(value)
        else:
            self._tick_count = 0
        self.update()

    def setDrawHandles(self, value: bool):
        if self._draw_handles != value:
            gremlin.util.InvokeUiMethod(self._set_draw_handles_ui, value)

    def _set_draw_handles_ui(self, value: bool):
        """enable/disables the drawing of handles"""
        self._draw_handles = value
        self.update()

    def setHandleIcon(self, index, icon, use_qta=False, color="#a0a0a0"):
        gremlin.util.InvokeUiMethod(
            self._set_handle_icon_ui, index, icon, use_qta, color
        )

    def _set_handle_icon_ui(self, index, icon, use_qta=False, color="#a0a0a0"):
        """sets the handle icon - to clear an icon, set it to None

        :param index: the handle index (int)
        :param icon: the QTA name or the png/svg file
        :param use_qta: set to true if the icon is a QTA icon
        :param color: icon color (qta icons only), None if default color

        """

        if icon is None:
            # clear the entry
            if index in self._handle_icons:
                del self._handle_icons[index]
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
        key = (a, b)
        if message is None and key in self._tooltip_handle_map:
            del self._tooltip_range_map[key]
        else:
            self._tooltip_range_map[key] = message

    def setValueIndex(self, index: int, value: int | float):
        gremlin.util.InvokeUiMethod(self._set_value_index_ui, index, value)

    def _set_value_index_ui(self, index: int, value: int | float):
        """sets a specific value by index"""

        value = gremlin.util.clamp(value, self._minimum, self._maximum)
        try:
            values = self._values
            values[index] = value
            self._set_value_ui(values)
        except Exception:
            syslog.error(
                f"Unable to set value index {index} - out of index range error"
            )

    def setValue(self, value: int | float | list | tuple):
        gremlin.util.InvokeUiMethod(self._set_value_ui, value)  # ensure on UI thread

    def _set_value_ui(self, value: int | float | list | tuple):
        """input values expected to be -1 to +1 floating point"""
        try:
            if self._value_lock:
                return
            self._value_lock = True
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                gremlin.util.assert_ui_thread()
            values = None
            if isinstance(value, float):
                value = gremlin.util.clamp(value, self._minimum, self._maximum)
                values = [value]
            elif isinstance(value, int):
                value = gremlin.util.clamp(float(value), self._minimum, self._maximum)
                values = [float(value)]
            elif isinstance(value, list):
                values = value
                values = [
                    gremlin.util.clamp(v, self._minimum, self._maximum)
                    for v in values
                    if v is not None
                ]
            elif isinstance(value, tuple):
                values = list(value)
                values = [
                    gremlin.util.clamp(v, self._minimum, self._maximum)
                    for v in values
                    if v is not None
                ]

            changed = False
            if values:
                values.sort()  # sort by value so the values are always in smallest to greatest
                changed = gremlin.util.compare_float_lists(self._values, values)

            if changed:
                verbose = gremlin.config.Configuration().verbose_mode_ui
                if verbose:
                    syslog.info(
                        f"Slider changed: {self.objectName()} [{self._id}]: {values}"
                    )
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
        self._marker_size = value
        self._update_pixmaps()
        self._update_marker_offsets_ui()
        self.update()

    def setReadOnly(self, value: bool):
        self._readOnly = value

    def readOnly(self) -> bool:
        return self._readOnly

    def _update_offsets_ui(self):
        """recomputes pixel offsets based on gate values"""
        size = self.size()
        widget_width = size.width()
        widget_height = size.height()
        margin = 4  # pixel margin
        usable_width = widget_width - margin
        range_width = usable_width - margin
        usable_margin = int((widget_width - range_width) * 0.5)

        gate_positions = []

        if len(self._values) == 0:
            return

        handle_count = len(self._values)

        # handle sizes
        max_icon_size = widget_height - 2 * margin
        handle_size = 24
        handle_size = min(handle_size, max_icon_size)
        self._handle_radius = int(handle_size * 0.5)
        self._handle_size = self._handle_radius * 2
        self._handle_top = int((widget_height - self._handle_size) * 0.5)

        self._handle_count = handle_count
        self._widget_width = widget_width
        self._widget_height = widget_height
        self._widget_corner = int(widget_height * 0.5)

        # compute the max range geometry boundaries (horizontal only)
        self._usable_width = range_width
        self._usable_margin = (
            int(handle_size * 0.5) + usable_margin
        )  # account for handle diameter
        self._usable_left = self._usable_margin
        self._usable_right = widget_width - self._usable_margin

        # print (f"Range width: {self._usable_width} range left: {self._usable_left} range right: {self._usable_right}  range width: {self._usable_width}  widget width: {widget_width}  height {widget_height} handle diameter: {handle_size} radius: {self._handle_radius}")

        # handle_offsets = []
        for value in self._values:
            x = gremlin.util.scale_to_range(
                value,
                source_min=self._minimum,
                source_max=self._maximum,
                target_min=self._usable_left,
                target_max=self._usable_right,
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
        # self._update_all_handle_pixmaps()

    def _update_marker_offsets_ui(self):
        if self._marker_pos:
            # compute marker positions
            source_min = self._minimum
            source_max = self._maximum
            target_min = self._usable_left  # self._to_qinteger_space(self._range_left)
            target_max = (
                self._usable_right
            )  # self._to_qinteger_space(self._range_right)
            self._int_marker_pos = [
                ((v - source_min) * (target_max - target_min))
                / (source_max - source_min)
                + target_min
                for v in self._marker_pos
            ]
            # print (f"marker: {[v for v in self._int_marker_pos]}")

    def _update_targets(self):
        """update target positions"""
        self._target_min = self._minimum  # self._to_qinteger_space(self._minimum)
        self._target_max = self._maximum  # self._to_qinteger_space(self._maximum)

    def setMarkerValue(self, value):
        gremlin.util.InvokeUiMethod(self._set_marker_value_ui, value)

    def _set_marker_value_ui(self, value):
        """sets the marker(s) value - single float is one marker, passing a tuple creates multiple markers"""
        # if self._lock:
        #     return
        # try:
        #     self._lock = True
        if isinstance(value, float) or isinstance(value, int):
            value = gremlin.util.clamp(value, self._minimum, self._maximum)
            list_value = [value]
        else:
            list_value = value
        self._marker_pos = list_value

        # update geometry + repaint
        self._update_offsets_ui()
        self.update()

        # finally:
        #     self._lock = False

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
        self._minimum = value
        if self._maximum < self._minimum:
            self._maximum, self._minimum = self._minimum, self._maximum
        self._update_targets()
        self._update_offsets_ui()

    def maximum(self) -> float:  # type: ignore
        """gets the slider's maximum value"""
        return self._maximum

    def setMaximum(self, value: float) -> None:
        gremlin.util.InvokeUiMethod(self._set_maximum_ui, value)

    def _set_maximum_ui(self, value: float) -> None:
        """sets the slider's maximum value"""
        self._maximum = value
        if self._maximum < self._minimum:
            self._maximum, self._minimum = self._minimum, self._maximum
        self._update_targets()
        self._update_offsets_ui()

    def setRange(self, range_min: float, range_max: float):
        gremlin.util.InvokeUiMethod(self._set_range_ui, range_min, range_max)

    def _set_range_ui(self, range_min: float, range_max: float):
        """sets the slider's min/max values

        :param range_min: min range (float)
        :param range_max: max range (float)

        """
        if range_min > range_max:
            # swap
            range_max, range_min = range_min, range_max
        self._minimum = range_min
        self._maximum = range_max
        self._update_targets()
        self._update_offsets_ui()

    def range(self):
        """returns the range of the slider"""
        return (self._minimum, self._maximum)

    def paintEvent(self, event: QPaintEvent):
        """paint event

        :param event: QPaintEvent object

        """
        # draw the widget
        # syslog.info("slider paint start")

        painter = QPainter(self)
        # painter.begin(self)
        painter.setRenderHint(QPainter.Antialiasing)

        self._draw_widget(painter)
        if self._tick_count > 0:
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

    def _draw_widget(self, painter: QPainter):
        """
        Draw the progress bar with Circular or Square style.

        :param painter: QPainter object.
        """
        handle_count = self._handle_count

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

        # reset computed hotspots
        self._handle_hotspots = []
        self._range_hotspots = []
        self._range_hotspots_map = {}  # map of rect to range index pairs (a,b)

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

            range_rect = QRect(range_left, range_top, range_width, range_height)
            # msg += f"range [{x1} {x2} {range_rect.left()} {range_rect.right()} {range_rect.top()} {range_rect.bottom()} ] "
            self._range_hotspots.append(range_rect)
            self._range_hotspots_map[range_rect] = (a, b)

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

                range_rect = QRect(range_left, range_top, range_width, range_height)
                # msg += f"range [{x1} {x2} {range_rect.left()} {range_rect.right()} {range_rect.top()} {range_rect.bottom()} ] "
                self._range_hotspots.append(range_rect)
                self._range_hotspots_map[range_rect] = (a, b)

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
                handle_rect = QRect(
                    x, self._handle_top, self._handle_size, self._handle_size
                )
                # print (f"handle [{index}  {handle_rect}]")
                self._handle_hotspots.append(handle_rect)
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
        center = self.height() * 0.66

        pixmaps = self._get_pixmaps()
        p_count = len(pixmaps)
        for index, value in enumerate(positions):
            if index < p_count:
                pd = pixmaps[index]
                painter.drawPixmap(value + pd.offset_x, center + pd.offset_y, pd.pixmap)

    def _draw_ticks(self, painter: QPainter):
        """draws the tick markers"""
        tick_pen = QPen(QBrush(self.tickColor), 1)
        painter.setPen(tick_pen)

        count = self._tick_count

        x1 = self._handle_min + self._handle_radius
        x2 = self._handle_max + self._handle_radius
        center = self.height() * 0.66
        width = x2 - x1

        if count > 0:
            y1 = center
            y2 = 10  # int((self.height() - center) * 0.8)

            if self._tick_marks:
                # variable spaced
                for value in self._tick_marks:
                    if value >= -1 and value <= 1:
                        x = gremlin.util.scale_to_range(
                            value, target_min=x1, target_max=x2
                        )
                        p1 = QPoint(x, y1)
                        p2 = QPoint(x, y2)
                        painter.drawLine(p1, p2)
            else:
                # equally spaced
                interval = width / (count - 1)
                x = x1
                for _ in range(self._tick_count + 1):
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
        super().resizeEvent(event)
        self._update_offsets_ui()
        self.adjustSize()
        self.update()

    def _mouse_position_to_value(self, x):
        """converts a mouse position to a slider value"""
        if x >= self._usable_left and x <= self._usable_right:
            # x is in the "value" zone
            value = gremlin.util.scale_to_range(
                x, self._usable_left, self._usable_right, self._minimum, self._maximum
            )
            # print (f"click value: {x} -> {value}")
            return value
        # not in range
        # print (f"not in range click value: {x} -> N/A")
        return None

    def _get_min_max_handles(self):
        """gets the index of the lowest and highest handle by value"""
        values = [(value, index) for index, value in enumerate(self._values)]
        values.sort(key=lambda x: x[0])
        return (values[0][1], values[-1][1])

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
        gremlin.util.InvokeUiMethod(self._show_tooltip_ui, message)

    def _show_tooltip_ui(self, message: str):
        if self._tooltip_timer is not None:
            self._tooltip_timer.cancel()

        # update m76T122 - remove all instances of QTimer to avoid mixing and matching QT threading model from Python threading model
        # syncing with QT is manually handled to guard against pitfalls

        self._tooltip_timer = threading.Timer(1, self._create_tooltip_callback(message))
        self._tooltip_timer.start()

    def _create_tooltip_callback(self, message):
        return lambda: self._handle_show_tooltip(message)

    def _handle_show_tooltip(self, message):
        gremlin.util.InvokeUiMethod(self._handle_show_tooltip_ui, message)

    def _handle_show_tooltip_ui(self, message):
        QToolTip.showText(QCursor.pos(), message, self)

    def _hover_update(self, event: QMouseEvent):
        """updates the hover state"""
        hover_changed = False
        if self._readOnly:
            # no hovering in readonly mode
            return

        if not self._hover_lock:
            is_hover = False
            rect: QRect

            point: QPoint = event.pos()
            # look for hover entry/exit on handles first
            for index, rect in enumerate(self._handle_hotspots):
                if rect.contains(point):
                    if self._hover_handle_index != index:
                        hover_changed = hover_changed or self._hover_exit_handle()
                        hover_changed = hover_changed or self._hover_exit_range()
                        hover_changed = hover_changed or self._hover_enter_handle(index)
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
                        if (
                            self._hover_range_handle_pair is None
                            or self._hover_range_handle_pair != (a, b)
                        ):
                            hover_changed = hover_changed or self._hover_exit_handle()
                            hover_changed = hover_changed or self._hover_exit_range()
                            hover_changed = hover_changed or self._hover_enter_range(
                                a, b
                            )
                            key = (a, b)
                            if key in self._tooltip_range_map:
                                self._show_tooltip(self._tooltip_range_map[key])
                        is_hover = True
                        break

            if not is_hover:
                hover_changed = hover_changed or self._hover_exit_handle()
                hover_changed = hover_changed or self._hover_exit_range()
                QToolTip.hideText()

        return hover_changed

    def mouseDoubleClickEvent(self, event):
        """double click event"""
        if self._readOnly:
            # don't fire events in readonly mode
            # print ("readonly - skip mousepress")
            return

        # print ("double click")
        self._double_clicked = True

        verbose = gremlin.config.Configuration().verbose_mode_ui
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
        if self._readOnly:
            # don't fire events in readonly mode
            return

        point = event.pos()
        for index, rect in enumerate(self._handle_hotspots):
            if rect.contains(point):
                # gate clicked

                self._mouse_down = True
                self._drag_active = True
                self._drag_handle_index = (
                    index  # current handle index of the handle bring dragged
                )
                self._drag_start = point
                # store the x offset where the drag started occuring
                self._drag_x_offset = self._handle_positions[index] - point.x()
                self._drag_last_point = point
                self._drag_x = point.x()
                self._hover_lock = True  # lock the current hover mode

    def mouseMoveEvent(self, event: QMouseEvent):
        point: QPoint = event.pos()

        # process mouse movement for hover
        hover_changed = self._hover_update(event)

        if event.buttons() == QtCore.Qt.LeftButton:
            # left mouse drag operation
            point = event.pos()
            x = point.x()

            if (
                not self._drag_active and self._mouse_down and abs(self._drag_x - x) > 2
            ):  # move at least 3 pixels
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
                        self.handleDragStart.emit(
                            self._drag_handle_index
                        )  # fire the drag start event
                        self._drag_emit = True

                    current_x = self._handle_positions[self._drag_handle_index]

                    x_offset = x - self._drag_x
                    current_x += x_offset

                    # drag bounds check
                    if current_x < self._handle_min:
                        current_x = self._handle_min
                    elif current_x > self._handle_max:
                        current_x = self._handle_max

                    value = self._mouse_position_to_value(
                        current_x + self._handle_radius
                    )

                    # get the index of the value relative to the other gates
                    old_value = self._values[self._drag_handle_index]
                    # print (f"Current x: {old_x} -> {current_x}  offset: {x_offset}  old value: {old_value}  new value: {value}")
                    if old_value != value:
                        self._values[self._drag_handle_index] = value
                        values = [
                            (value, index) for index, value in enumerate(self._values)
                        ]
                        pair = values[self._drag_handle_index]
                        values.sort(key=lambda x: x[0])
                        self._values.sort()
                        new_index = values.index(pair)

                        # print (f"new index: {new_index}")
                        self._drag_handle_index = new_index

                        self._handle_positions[self._drag_handle_index] = current_x
                        index_min, index_max = self._get_min_max_handles()

                        self._range_left = (
                            self._handle_positions[index_min] + self._handle_radius
                        )
                        self._range_right = (
                            self._handle_positions[index_max] + self._handle_radius
                        )
                        self._range_width = self._range_right - self._range_left
                        self._drag_x = x
                        # print (f"drag offset: {x_offset}  new position: {current_x}  new value: {value}  min index: {index_min}  max index: {index_max}")

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
        if self._readOnly:
            # don't fire events in readonly mode
            # print ("readonly - skip mouse release")
            return

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
        def __init__(
            self, index: int, icon: str, use_qta: bool = True, color="#808080"
        ):
            self.index = index
            self.icon = icon
            self.use_qta = use_qta
            self.color = color

    def _get_pixmaps(self):
        if self._pixmaps:
            return self._pixmaps
        return self._internal_pixmaps

    def _update_pixmaps(self):
        icon = gremlin.util.load_icon("ei.chevron-up")
        pixmap = icon.pixmap(self.marker_size)
        center = self.height() / 2
        if pixmap.height() > center:
            pixmap = pixmap.scaledToHeight(center)
        pd = QSliderWidget.PixmapData(
            pixmap=pixmap, offset_x=-pixmap.width() / 2, offset_y=0
        )
        self._internal_pixmaps = [pd]

    def _update_handle_pixmaps(self, hid: QSliderWidget.HandleIconData):  # noqa: F821
        """updates the pixmaps for the handle icons

        two versions of the icon are loaded, a regular and highlighted version

        """
        icon_size = int(self._handle_size * 0.75)
        margin = (self._handle_size - icon_size) // 2
        # hex_color = "#323232" # default QTA is rgb 50,50,50
        hex_color = hid.color
        color = QColor(hex_color)
        color_h = gremlin.util.highlight_qcolor(color, factor=1.4)
        icon = gremlin.util.load_icon(hid.icon, qta_color=color)
        icon_h = gremlin.util.load_icon(hid.icon, qta_color=color_h)
        pixmap = icon.pixmap(icon_size)
        pixmap_h = icon_h.pixmap(icon_size)
        pd = QSliderWidget.PixmapData(
            pixmap=pixmap, offset_x=-pixmap.width() / 2, offset_y=margin
        )
        pd_h = QSliderWidget.PixmapData(
            pixmap=pixmap_h, offset_x=-pixmap.width() / 2, offset_y=margin
        )
        self._internal_handle_pixmaps[hid.index] = (pd, pd_h)

    def _update_all_handle_pixmaps(self):
        """updates all handle icons on resize/update"""
        for hid in self._handle_icons.values():
            self._update_handle_pixmaps(hid)
