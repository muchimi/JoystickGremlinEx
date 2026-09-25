# -*- coding: utf-8; -*-
#
# Preview dialog for overlay visibility boolean expressions.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

import gremlin.ui.ui_common

from .visibility_logic import (
    VisibilityExprError,
    eval_visibility_node,
    expression_letters,
    parse_visibility_expression,
    pretty_visibility_expression,
    truth_table,
)

_FILL = QtGui.QColor(40, 90, 200)
_EMPTY = QtGui.QColor(255, 255, 255)
_OUTLINE = QtGui.QColor(20, 20, 20)
_OUTSIDE = QtGui.QColor(245, 245, 245)
_UNIVERSE = QtGui.QColor(230, 230, 230)
_ZERO_BG = QtGui.QColor(168, 42, 42)
_ONE_BG = QtGui.QColor(34, 122, 58)
_VALUE_FG = QtGui.QColor(255, 255, 255)


def _truth_cell(on: bool) -> QtWidgets.QTableWidgetItem:
    item = QtWidgets.QTableWidgetItem("1" if on else "0")
    item.setTextAlignment(int(QtCore.Qt.AlignCenter))
    item.setBackground(_ONE_BG if on else _ZERO_BG)
    item.setForeground(QtGui.QBrush(_VALUE_FG))
    return item


class VisibilityVennWidget(QtWidgets.QWidget):
    """Venn diagram for 1–3 inputs; regions follow the expression’s output."""

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self._node = None
        self._letters: list[str] = []
        self._message = ""
        self._compact = bool(compact)
        if self._compact:
            self.setFixedSize(168, 104)
        else:
            self.setMinimumSize(280, 220)
            self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

    def set_expression(self, node, letters: list[str], message: str = ""):
        self._node = node
        self._letters = list(letters or [])
        self._message = str(message or "")
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(168, 104) if self._compact else QtCore.QSize(340, 240)

    def _circles(self, rect: QtCore.QRectF) -> list[tuple[str, QtCore.QPointF, float]]:
        cx, cy = rect.center().x(), rect.center().y()
        names = self._letters[:3]
        if len(names) <= 1:
            r = min(rect.width(), rect.height()) * 0.32
            letter = names[0] if names else "A"
            return [(letter, QtCore.QPointF(cx, cy), r)]
        if len(names) == 2:
            r = min(rect.width(), rect.height()) * 0.30
            offset = r * 0.55
            return [
                (names[0], QtCore.QPointF(cx - offset, cy), r),
                (names[1], QtCore.QPointF(cx + offset, cy), r),
            ]
        r = min(rect.width(), rect.height()) * 0.26
        dy = r * 0.42
        return [
            (names[0], QtCore.QPointF(cx - r * 0.55, cy - dy), r),
            (names[1], QtCore.QPointF(cx + r * 0.55, cy - dy), r),
            (names[2], QtCore.QPointF(cx, cy + r * 0.55), r),
        ]

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), _OUTSIDE)
        if self._message:
            painter.setPen(QtGui.QColor("#333"))
            painter.drawText(
                self.rect().adjusted(16, 16, -16, -16),
                int(QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap),
                self._message,
            )
            painter.end()
            return
        letters = self._letters[:3]
        if not letters:
            painter.setPen(QtGui.QColor("#333"))
            painter.drawText(self.rect(), int(QtCore.Qt.AlignCenter), "Add a mode or state to preview.")
            painter.end()
            return
        pad = 6 if self._compact else 16
        bottom = 10 if self._compact else 32
        inner = QtCore.QRectF(self.rect()).adjusted(pad, pad, -pad, -bottom)
        painter.setPen(QtGui.QPen(_OUTLINE, 1))
        painter.setBrush(_UNIVERSE)
        painter.drawRoundedRect(inner, 8, 8)

        universe = QtGui.QPainterPath()
        universe.addRoundedRect(inner.adjusted(1, 1, -1, -1), 7, 7)
        circles = self._circles(inner)
        circle_paths: list[tuple[str, QtGui.QPainterPath]] = []
        for name, center, radius in circles:
            path = QtGui.QPainterPath()
            path.addEllipse(center, radius, radius)
            circle_paths.append((name, path))

        count = len(circle_paths)
        for index in range(1 << count):
            env = {}
            region = QtGui.QPainterPath(universe)
            for bit, (name, circle) in enumerate(circle_paths):
                on = bool(index & (1 << (count - 1 - bit)))
                env[name] = on
                region = region.intersected(circle) if on else region.subtracted(circle)
            if region.isEmpty():
                continue
            on = eval_visibility_node(self._node, env) if self._node is not None else True
            painter.fillPath(region, _FILL if on else _EMPTY)

        font = painter.font()
        font.setBold(True)
        font.setPointSize(8 if self._compact else 12)
        painter.setFont(font)
        painter.setBrush(QtCore.Qt.NoBrush)
        for name, center, radius in circles:
            painter.setPen(QtGui.QPen(_OUTLINE, 2))
            painter.drawEllipse(center, radius, radius)
            painter.setPen(_OUTLINE)
            label_dy = 12 if self._compact else 18
            painter.drawText(QtCore.QPointF(center.x() - 5, center.y() - radius + label_dy), name)
        painter.end()


class VisibilityPreviewDialog(gremlin.ui.ui_common.QRememberDialog):
    def __init__(self, expression: str, legend: list[tuple[str, str]], parent=None):
        super().__init__("overlay_visibility_preview", parent=parent)
        self.setWindowTitle("Visibility preview")
        self.resize(760, 540)
        layout = QtWidgets.QVBoxLayout(self)

        legend_box = QtWidgets.QGroupBox("Inputs")
        legend_form = QtWidgets.QFormLayout(legend_box)
        if not legend:
            legend_form.addRow(QtWidgets.QLabel("No modes or states yet."))
        else:
            for letter, phrase in legend:
                legend_form.addRow(letter, QtWidgets.QLabel(phrase))
        layout.addWidget(legend_box)

        error = ""
        node = None
        used: list[str] = []
        letters = [letter for letter, _phrase in legend if str(letter or "").strip()]
        try:
            node = parse_visibility_expression(expression)
            used = expression_letters(node) if node is not None else []
            if used:
                letters = used
        except VisibilityExprError as err:
            error = str(err)

        algebra = QtWidgets.QLabel()
        algebra.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        algebra.setWordWrap(True)
        if error:
            algebra.setText(f"Boolean algebra: {expression or '—'}\n{error}")
        elif node is None:
            algebra.setText("Boolean algebra: —")
        else:
            pretty = pretty_visibility_expression(node)
            unused = [letter for letter, _phrase in legend if letter and letter not in (used or [])]
            extra = f"\nUnused: {', '.join(unused)}" if unused else ""
            algebra.setText(f"Boolean algebra: {pretty}\nEntered: {expression or '—'}{extra}")
        font = algebra.font()
        font.setPointSize(font.pointSize() + 1)
        algebra.setFont(font)
        layout.addWidget(algebra)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        venn = VisibilityVennWidget()
        if error:
            venn.set_expression(None, [], error)
        elif len(letters) > 3:
            venn.set_expression(node, letters, "Venn diagrams are shown for up to three inputs. Use the table for the full result.")
        else:
            venn.set_expression(node, letters)
        split.addWidget(venn)

        table = QtWidgets.QTableWidget()
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        if error:
            table.setColumnCount(1)
            table.setHorizontalHeaderLabels(["Output"])
            table.setRowCount(0)
        elif len(letters) > 8:
            table.setColumnCount(1)
            table.setHorizontalHeaderLabels(["Output"])
            table.setRowCount(1)
            table.setItem(0, 0, QtWidgets.QTableWidgetItem("Too many inputs for a full table (max 8)."))
        else:
            headers = list(letters) + ["Output"]
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)
            rows = truth_table(node, letters)
            table.setRowCount(len(rows))
            for r, (env, out) in enumerate(rows):
                for c, letter in enumerate(letters):
                    table.setItem(r, c, _truth_cell(bool(env.get(letter))))
                table.setItem(r, len(letters), _truth_cell(bool(out)))
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        split.addWidget(table)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)

        close_btn = gremlin.ui.ui_common.Buttons.getOkWidget(label="Close", callback=self.accept)
        layout.addWidget(
            gremlin.ui.ui_common.getHContainer(["||", close_btn], widget_only=True)
        )


def _truth_table_widget(node, letters: list[str], parent=None) -> QtWidgets.QTableWidget:
    table = QtWidgets.QTableWidget(parent)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setFocusPolicy(QtCore.Qt.NoFocus)
    table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
    headers = list(letters) + ["Output"]
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    rows = truth_table(node, letters)
    table.setRowCount(len(rows))
    for r, (env, out) in enumerate(rows):
        for c, letter in enumerate(letters):
            table.setItem(r, c, _truth_cell(bool(env.get(letter))))
        table.setItem(r, len(letters), _truth_cell(bool(out)))
    table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(22)
    table.setFixedWidth(168 if len(letters) <= 1 else 200)
    table.setFixedHeight(28 + 22 * max(1, len(rows)) + 4)
    return table


class LogicGateWidget(QtWidgets.QWidget):
    """IEEE-style AND / OR / XOR / NOT / NAND / NOR / XNOR symbol."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = str(kind or "AND").upper()
        self.setFixedSize(120, 72)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(120, 72)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        color = self.palette().color(QtGui.QPalette.WindowText)
        pen = QtGui.QPen(color, 2.2)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        rect = QtCore.QRectF(self.rect()).adjusted(6, 10, -6, -10)
        kind = self._kind
        if kind == "NOT":
            self._draw_not(painter, rect)
        elif kind in ("AND", "NAND"):
            self._draw_and(painter, rect, bubble=kind == "NAND")
        elif kind in ("OR", "NOR"):
            self._draw_or(painter, rect, bubble=kind == "NOR", extra=False)
        else:
            self._draw_or(painter, rect, bubble=kind == "XNOR", extra=True)
        painter.end()

    def _draw_not(self, painter: QtGui.QPainter, rect: QtCore.QRectF):
        left, top, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        cy = top + h / 2
        tip = left + w - 18
        tri = QtGui.QPainterPath()
        tri.moveTo(left + 18, top)
        tri.lineTo(tip, cy)
        tri.lineTo(left + 18, top + h)
        tri.closeSubpath()
        painter.drawPath(tri)
        painter.drawLine(QtCore.QPointF(left, cy), QtCore.QPointF(left + 18, cy))
        bubble = QtCore.QRectF(tip, cy - 5, 10, 10)
        painter.drawEllipse(bubble)
        painter.drawLine(QtCore.QPointF(bubble.right(), cy), QtCore.QPointF(left + w, cy))

    def _draw_and(self, painter: QtGui.QPainter, rect: QtCore.QRectF, bubble: bool):
        left = rect.x() + 16
        top = rect.y()
        height = rect.height()
        width = rect.width() - 34
        cy = top + height / 2
        y1 = top + height * 0.28
        y2 = top + height * 0.72
        painter.drawLine(QtCore.QPointF(rect.x(), y1), QtCore.QPointF(left, y1))
        painter.drawLine(QtCore.QPointF(rect.x(), y2), QtCore.QPointF(left, y2))
        arc = QtCore.QRectF(left + width - height, top, height, height)
        path = QtGui.QPainterPath()
        path.moveTo(left, top)
        path.lineTo(arc.center().x(), top)
        path.arcTo(arc, 90, -180)
        path.lineTo(left, top + height)
        path.closeSubpath()
        painter.drawPath(path)
        out_x = left + width
        if bubble:
            bubble_rect = QtCore.QRectF(out_x - 1, cy - 5, 10, 10)
            painter.drawEllipse(bubble_rect)
            painter.drawLine(QtCore.QPointF(bubble_rect.right(), cy), QtCore.QPointF(rect.right(), cy))
        else:
            painter.drawLine(QtCore.QPointF(out_x, cy), QtCore.QPointF(rect.right(), cy))

    def _draw_or(self, painter: QtGui.QPainter, rect: QtCore.QRectF, bubble: bool, extra: bool):
        left = rect.x() + (22 if extra else 16)
        top = rect.y()
        height = rect.height()
        right = rect.right() - 18
        cy = top + height / 2
        y1 = top + height * 0.28
        y2 = top + height * 0.72
        back = left + 10
        path = QtGui.QPainterPath()
        path.moveTo(left, top)
        path.quadTo((left + right) / 2, top - 2, right, cy)
        path.quadTo((left + right) / 2, top + height + 2, left, top + height)
        path.quadTo(back, cy, left, top)
        painter.drawPath(path)
        if extra:
            xor = QtGui.QPainterPath()
            xor.moveTo(left - 8, top)
            xor.quadTo(back - 8, cy, left - 8, top + height)
            painter.drawPath(xor)
        painter.drawLine(QtCore.QPointF(rect.x(), y1), QtCore.QPointF(left + 6, y1))
        painter.drawLine(QtCore.QPointF(rect.x(), y2), QtCore.QPointF(left + 6, y2))
        if bubble:
            bubble_rect = QtCore.QRectF(right - 2, cy - 5, 10, 10)
            painter.drawEllipse(bubble_rect)
            painter.drawLine(QtCore.QPointF(bubble_rect.right(), cy), QtCore.QPointF(rect.right(), cy))
        else:
            painter.drawLine(QtCore.QPointF(right, cy), QtCore.QPointF(rect.right(), cy))


_BOOLEAN_OPERATORS = (
    ("AND", "A AND B", "A · B", ["A", "B"]),
    ("OR", "A OR B", "A + B", ["A", "B"]),
    ("XOR", "A XOR B", "A ⊕ B", ["A", "B"]),
    ("NOT", "NOT A", "Ā", ["A"]),
    ("NAND", "A NAND B", "¬(A · B)", ["A", "B"]),
    ("NOR", "A NOR B", "¬(A + B)", ["A", "B"]),
    ("XNOR", "A XNOR B", "¬(A ⊕ B)", ["A", "B"]),
)


class BooleanOperatorsDialog(gremlin.ui.ui_common.QRememberDialog):
    """Graphical reference for every visibility boolean operator."""

    def __init__(self, parent=None):
        super().__init__("overlay_boolean_operators", parent=parent)
        self.setWindowTitle("Boolean operators")
        self.resize(920, 720)
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel(
            "Use these operators in the expression, with parentheses to group. "
            "Example: A AND (B OR C). Symbols · + ⊕ ¬ also work."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        host = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(host)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        headers = ("Expression", "Symbol", "Venn diagram", "Boolean algebra", "Values")
        for col, title in enumerate(headers):
            label = QtWidgets.QLabel(title)
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            grid.addWidget(label, 0, col)

        for row, (name, typed, algebra, letters) in enumerate(_BOOLEAN_OPERATORS, start=1):
            title = QtWidgets.QLabel(name)
            font = title.font()
            font.setBold(True)
            font.setPointSize(font.pointSize() + 2)
            title.setFont(font)
            title.setAlignment(QtCore.Qt.AlignCenter)
            grid.addWidget(title, row, 0)

            gate = LogicGateWidget(name)
            grid.addWidget(gate, row, 1, 1, 1, QtCore.Qt.AlignCenter)

            node = parse_visibility_expression(typed)
            venn = VisibilityVennWidget(compact=True)
            venn.set_expression(node, letters)
            grid.addWidget(venn, row, 2, 1, 1, QtCore.Qt.AlignCenter)

            algebra_label = QtWidgets.QLabel(f"{algebra}\nType: {typed}")
            algebra_label.setAlignment(QtCore.Qt.AlignCenter)
            algebra_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            grid.addWidget(algebra_label, row, 3, 1, 1, QtCore.Qt.AlignCenter)

            table = _truth_table_widget(node, letters)
            grid.addWidget(table, row, 4, 1, 1, QtCore.Qt.AlignCenter)

        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(4, 1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        close_btn = gremlin.ui.ui_common.Buttons.getOkWidget(label="Close", callback=self.accept)
        layout.addWidget(
            gremlin.ui.ui_common.getHContainer(["||", close_btn], widget_only=True)
        )
