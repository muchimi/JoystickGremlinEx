# -*- coding: utf-8; -*-

"""OdenGraphQt node types for the AFCS canvas."""

from __future__ import annotations

from OdenGraphQt import BaseNode
from OdenGraphQt.constants import NodePropWidgetEnum
from OdenGraphQt.widgets.node_widgets import NodeBaseWidget
from PySide6 import QtCore, QtGui, QtWidgets

from .ops import MERGE_OP_LABELS, MERGE_OPS, normalize_merge_op

IDENTIFIER = "gremlin.afcs"


class _MeterBar(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._centered = True
        self.setMinimumHeight(16)
        self.setMaximumHeight(18)
        self.setMinimumWidth(110)

    def set_centered(self, centered: bool) -> None:
        self._centered = bool(centered)
        self.update()

    def set_value(self, value: float) -> None:
        self._value = max(-1.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 2, -1, -2)
        painter.fillRect(rect, QtGui.QColor(40, 40, 40))
        if self._centered:
            mid = rect.center().x()
            painter.setPen(QtGui.QColor(80, 80, 80))
            painter.drawLine(mid, rect.top(), mid, rect.bottom())
            span = int(abs(self._value) * (rect.width() / 2))
            if self._value >= 0:
                bar = QtCore.QRect(mid, rect.top(), span, rect.height())
                color = QtGui.QColor(70, 170, 90)
            else:
                bar = QtCore.QRect(mid - span, rect.top(), span, rect.height())
                color = QtGui.QColor(200, 90, 60)
            painter.fillRect(bar, color)
        else:
            fill = max(0.0, min(1.0, (self._value + 1.0) * 0.5))
            span = int(fill * rect.width())
            painter.fillRect(QtCore.QRect(rect.left(), rect.top(), span, rect.height()), QtGui.QColor(70, 170, 90))
        painter.setPen(QtGui.QColor(20, 20, 20))
        painter.drawRect(rect)


class _MeterRow(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._centered = True
        self._bar = _MeterBar()
        self._label = QtWidgets.QLabel("+0.00")
        self._label.setMinimumWidth(42)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._bar, 1)
        layout.addWidget(self._label, 0)

    def set_centered(self, centered: bool) -> None:
        self._centered = bool(centered)
        self._bar.set_centered(centered)
        self.set_value(self._bar._value)

    def set_value(self, value: float) -> None:
        current = max(-1.0, min(1.0, float(value)))
        self._bar.set_value(current)
        if self._centered:
            self._label.setText(f"{current:+.2f}")
        else:
            self._label.setText(f"{(current + 1.0) * 50.0:.0f}%")


class NodeMeterWidget(NodeBaseWidget):
    """Live axis meter embedded at the bottom of an AFCS node."""

    def __init__(self, parent=None, name="live_meter", label=""):
        super().__init__(parent, name, label)
        row = _MeterRow()
        self.set_custom_widget(row)

    def get_value(self):
        return 0.0

    def set_centered(self, centered: bool) -> None:
        row = self.get_custom_widget()
        if row is not None:
            row.set_centered(centered)

    def set_value(self, value=0.0):
        row = self.get_custom_widget()
        if row is not None:
            row.set_value(float(value or 0.0))


def _attach_when(node) -> None:
    node.create_property("when_json", "", widget_type=NodePropWidgetEnum.HIDDEN.value)


def _detach_value_changed(widget) -> None:
    try:
        widget.value_changed.disconnect()
    except Exception:
        pass


def _attach_live_meter(node) -> None:
    _attach_when(node)
    meter = NodeMeterWidget(node.view, "live_meter", "")
    node.add_custom_widget(meter)
    _detach_value_changed(meter)


class _CurvePreview(QtWidgets.QWidget):
    """Mini response curve. Linear limiter scales Y. Bezier limiter bakes handle morph into the points."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gain = 1.0
        self._points: list[tuple[float, float]] = []
        self.setMinimumHeight(72)
        self.setMaximumHeight(80)
        self.setMinimumWidth(110)

    def set_gain(self, value: float) -> None:
        self._gain = max(-1.0, min(1.0, float(value)))
        self.update()

    def set_points(self, points) -> None:
        self._points = [(float(x), float(y)) for x, y in (points or [])]
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(rect, QtGui.QColor(28, 28, 28))
        painter.setPen(QtGui.QColor(55, 55, 55))
        for step in (0.25, 0.5, 0.75):
            x = rect.left() + int(rect.width() * step)
            y = rect.top() + int(rect.height() * step)
            painter.drawLine(x, rect.top(), x, rect.bottom())
            painter.drawLine(rect.left(), y, rect.right(), y)
        painter.setPen(QtGui.QColor(20, 20, 20))
        painter.drawRect(rect)

        def to_screen(x: float, y: float) -> QtCore.QPointF:
            px = rect.left() + ((x + 1.0) * 0.5) * rect.width()
            py = rect.bottom() - ((y + 1.0) * 0.5) * rect.height()
            return QtCore.QPointF(px, py)

        samples = self._points or [(-1.0, -1.0), (1.0, 1.0)]
        path = QtGui.QPainterPath(to_screen(samples[0][0], samples[0][1] * self._gain))
        for x, y in samples[1:]:
            path.lineTo(to_screen(x, y * self._gain))
        painter.setPen(QtGui.QPen(QtGui.QColor(120, 170, 120), 2))
        painter.drawPath(path)
        start = to_screen(samples[0][0], samples[0][1] * self._gain)
        end = to_screen(samples[-1][0], samples[-1][1] * self._gain)
        painter.setBrush(QtGui.QColor(220, 220, 220))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(start, 3, 3)
        painter.setBrush(QtGui.QColor(200, 70, 70))
        painter.drawEllipse(end, 3, 3)


class NodeCurvePreviewWidget(NodeBaseWidget):
    def __init__(self, parent=None, name="live_curve", label=""):
        super().__init__(parent, name, label)
        preview = _CurvePreview()
        self.set_custom_widget(preview)

    def get_value(self):
        return 0.0

    def set_value(self, value=0.0):
        self.set_gain(value)

    def set_gain(self, value: float) -> None:
        preview = self.get_custom_widget()
        if preview is not None:
            preview.set_gain(value)

    def set_points(self, points) -> None:
        preview = self.get_custom_widget()
        if preview is not None:
            preview.set_points(points)


def _attach_curve_preview(node) -> None:
    preview = NodeCurvePreviewWidget(node.view, "live_curve", "")
    node.add_custom_widget(preview)
    _detach_value_changed(preview)


class AfcsInput(BaseNode):
    __identifier__ = IDENTIFIER
    NODE_NAME = "Input"
    AFCS_KIND = "input"

    def __init__(self):
        super().__init__()
        self.add_output("out")
        self.create_property("afcs_id", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("source_name", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("device_guid", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("device_name", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("axis_id", 0, widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("invert", False, widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("display_range", "auto", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.set_color(45, 90, 140)
        _attach_live_meter(self)


class AfcsMerge(BaseNode):
    __identifier__ = IDENTIFIER
    NODE_NAME = "Merge"
    AFCS_KIND = "merge"

    def __init__(self):
        super().__init__()
        self.add_input("in_a")
        self.add_input("in_b")
        self.add_output("out")
        self.create_property("afcs_id", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.add_combo_menu("operation", "Op", items=[MERGE_OP_LABELS[op] for op in MERGE_OPS])
        self.set_color(160, 90, 40)
        _attach_live_meter(self)


class AfcsCurve(BaseNode):
    __identifier__ = IDENTIFIER
    NODE_NAME = "Curve"
    AFCS_KIND = "curve"

    def __init__(self):
        super().__init__()
        self.add_input("in")
        self.add_output("out")
        self.create_property("afcs_id", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("curve_xml", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.set_color(110, 60, 140)
        _attach_live_meter(self)


class AfcsLimiter(BaseNode):
    __identifier__ = IDENTIFIER
    NODE_NAME = "Limiter"
    AFCS_KIND = "limiter"

    def __init__(self):
        super().__init__()
        self.add_input("in")
        self.add_input("limit")
        self.add_output("out")
        self.create_property("afcs_id", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("curve_xml", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("range_mode", "unipolar", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("shape", "linear", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.set_color(70, 110, 130)
        _attach_curve_preview(self)
        _attach_live_meter(self)


class AfcsDeadzone(BaseNode):
    __identifier__ = IDENTIFIER
    NODE_NAME = "Deadzone"
    AFCS_KIND = "deadzone"

    def __init__(self):
        super().__init__()
        self.add_input("in")
        self.add_output("out")
        self.create_property("afcs_id", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("center", 0.05, widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("outer", 0.0, widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.set_color(90, 90, 110)
        _attach_live_meter(self)


class AfcsOverride(BaseNode):
    __identifier__ = IDENTIFIER
    NODE_NAME = "Override"
    AFCS_KIND = "override"

    def __init__(self):
        super().__init__()
        self.add_input("in")
        self.add_input("override")
        self.add_output("out")
        self.create_property("afcs_id", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("threshold", 0.08, widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("release", 0.03, widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("release_ms", 0.0, widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("hold_until_in", False, widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.set_color(170, 80, 50)
        _attach_live_meter(self)


class AfcsLagLead(BaseNode):
    __identifier__ = IDENTIFIER
    NODE_NAME = "Lag-lead"
    AFCS_KIND = "laglead"

    def __init__(self):
        super().__init__()
        self.add_input("in")
        self.add_output("out")
        self.create_property("afcs_id", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("lag_ms", 80.0, widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("lead_ms", 0.0, widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.set_color(40, 130, 120)
        _attach_live_meter(self)


class AfcsOutput(BaseNode):
    __identifier__ = IDENTIFIER
    NODE_NAME = "Output"
    AFCS_KIND = "output"

    def __init__(self):
        super().__init__()
        self.add_input("in")
        self.create_property("afcs_id", "", widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("vjoy_id", 1, widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.create_property("axis_id", 1, widget_type=NodePropWidgetEnum.HIDDEN.value)
        self.set_color(40, 120, 70)
        _attach_live_meter(self)


AFCS_NODE_CLASSES = (AfcsInput, AfcsMerge, AfcsCurve, AfcsLimiter, AfcsDeadzone, AfcsOverride, AfcsLagLead, AfcsOutput)
KIND_TO_TYPE = {cls.AFCS_KIND: f"{cls.__identifier__}.{cls.__name__}" for cls in AFCS_NODE_CLASSES}
TYPE_TO_KIND = {value: key for key, value in KIND_TO_TYPE.items()}


def kind_for_node(node) -> str:
    kind = TYPE_TO_KIND.get(getattr(node, "type_", None) or "")
    if kind:
        return kind
    return getattr(node, "AFCS_KIND", "") or "input"


def operation_label(op: str) -> str:
    return MERGE_OP_LABELS.get(normalize_merge_op(op), "Add")


def operation_from_label(label: str) -> str:
    for key, value in MERGE_OP_LABELS.items():
        if value.casefold() == str(label or "").casefold():
            return key
    return normalize_merge_op(label)
