"""Offscreen Qt checks for flow-layout geometry and change notifications.

Run with: python -m pytest tools/test_qflowlayout.py -q -p no:cacheprovider
Load the real layout class without importing application or device services.
"""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

from PySide6 import QtCore, QtWidgets

ROOT = Path(__file__).resolve().parents[1]
APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["flow-layout-checks", "-platform", "offscreen"])


def load_flow_layout(source=None):
    path = ROOT / "gremlin/ui/ui_common.py"
    tree = ast.parse(source if source is not None else path.read_bytes())
    node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "QFlowLayout")
    namespace = dict(
        QtCore=QtCore, QtWidgets=QtWidgets, Qt=QtCore.Qt, QWidget=QtWidgets.QWidget,
        QSizePolicy=QtWidgets.QSizePolicy, QMargins=QtCore.QMargins, QSize=QtCore.QSize,
        QRect=QtCore.QRect, QPoint=QtCore.QPoint,
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["QFlowLayout"]


FLOW = load_flow_layout()


class Style:
    def __init__(self, horizontal=2, vertical=3):
        self.horizontal = horizontal
        self.vertical = vertical
        self.layoutSpacing = Mock(side_effect=self.spacing)

    def spacing(self, first, second, orientation):
        return self.horizontal if orientation == QtCore.Qt.Orientation.Horizontal else self.vertical


class Item:
    def __init__(self, size, style):
        self.size = QtCore.QSize(*size)
        self.sizeHint = Mock(side_effect=lambda: self.size)
        self.widget = lambda: NS(style=lambda: style)
        self.setGeometry = Mock()


class HintWidget(QtWidgets.QWidget):
    def __init__(self, width, height):
        super().__init__()
        self.hint = QtCore.QSize(width, height)

    def sizeHint(self):
        return self.hint

    def minimumSizeHint(self):
        return self.hint


class FlowLayoutChecks(unittest.TestCase):
    def make_holder(self):
        style = Style()
        items = [Item(size, style) for size in ((30, 10), (40, 20), (20, 15))]
        holder = NS(
            _item_list=items, _line_count=0, spacing=lambda: 1,
            parentWidget=lambda: None, lineCountChanged=NS(emit=Mock()),
        )
        return holder, items, style

    def test_wrapping_preserves_positions_and_height(self):
        holder, items, style = self.make_holder()
        height = FLOW._do_layout(holder, QtCore.QRect(5, 7, 80, 0), False)
        self.assertEqual(height, 39)
        self.assertEqual([item.setGeometry.call_args.args[0] for item in items], [
            QtCore.QRect(5, 7, 30, 10), QtCore.QRect(38, 7, 40, 20), QtCore.QRect(5, 31, 20, 15),
        ])
        self.assertEqual(holder._line_count, 2)
        holder.lineCountChanged.emit.assert_called_once_with(None, 2)

    def test_size_measurement_has_no_geometry_or_notification_side_effects(self):
        holder, items, style = self.make_holder()
        holder._line_count = 7
        self.assertEqual(FLOW._do_layout(holder, QtCore.QRect(5, 7, 80, 0), True), 39)
        self.assertEqual(holder._line_count, 7)
        holder.lineCountChanged.emit.assert_not_called()
        for item in items:
            item.setGeometry.assert_not_called()

    def test_unchanged_row_count_does_not_emit_again(self):
        holder, items, style = self.make_holder()
        FLOW._do_layout(holder, QtCore.QRect(0, 0, 80, 0), False)
        FLOW._do_layout(holder, QtCore.QRect(0, 0, 81, 0), False)
        holder.lineCountChanged.emit.assert_called_once_with(None, 2)
        FLOW._do_layout(holder, QtCore.QRect(0, 0, 110, 0), False)
        self.assertEqual(holder.lineCountChanged.emit.call_count, 2)
        self.assertEqual(holder.lineCountChanged.emit.call_args.args, (None, 1))

    def test_layout_reentry_from_change_callback_does_not_repeat_notification(self):
        holder, items, style = self.make_holder()
        rect = QtCore.QRect(0, 0, 80, 0)

        def update_geometry(*args):
            if holder.lineCountChanged.emit.call_count < 5:
                FLOW._do_layout(holder, rect, False)

        holder.lineCountChanged.emit.side_effect = update_geometry
        FLOW._do_layout(holder, rect, False)
        holder.lineCountChanged.emit.assert_called_once_with(None, 2)

    def test_each_item_size_is_read_once_and_spacing_once_per_style(self):
        holder, items, style = self.make_holder()
        FLOW._do_layout(holder, QtCore.QRect(0, 0, 80, 0), False)
        for item in items:
            item.sizeHint.assert_called_once_with()
        self.assertEqual(style.layoutSpacing.call_count, 2)

    def test_style_and_size_changes_are_visible_on_the_next_pass(self):
        holder, items, style = self.make_holder()
        FLOW._do_layout(holder, QtCore.QRect(0, 0, 80, 0), False)
        style.vertical = 10
        items[-1].size = QtCore.QSize(20, 25)
        self.assertEqual(FLOW._do_layout(holder, QtCore.QRect(0, 0, 80, 0), False), 56)
        self.assertEqual(items[-1].setGeometry.call_args.args[0], QtCore.QRect(0, 31, 20, 25))
        self.assertEqual(style.layoutSpacing.call_count, 4)

    def test_different_styles_keep_their_own_spacing(self):
        holder, items, style = self.make_holder()
        alternate = Style(horizontal=9, vertical=8)
        items[-1].widget = lambda: NS(style=lambda: alternate)
        self.assertEqual(FLOW._do_layout(holder, QtCore.QRect(5, 7, 80, 0), False), 44)
        self.assertEqual(items[-1].setGeometry.call_args.args[0], QtCore.QRect(5, 36, 20, 15))
        self.assertEqual(style.layoutSpacing.call_count, 2)
        self.assertEqual(alternate.layoutSpacing.call_count, 2)

    def test_empty_and_narrow_layouts_keep_existing_height_behavior(self):
        holder, items, style = self.make_holder()
        holder._item_list = []
        self.assertEqual(FLOW._do_layout(holder, QtCore.QRect(5, 7, 0, 0), False), 0)
        holder._item_list = items
        self.assertEqual(FLOW._do_layout(holder, QtCore.QRect(5, 7, 0, 0), False), 53)
        self.assertEqual(holder._line_count, 3)

    def test_native_qt_measurements_leave_committed_line_count_unchanged(self):
        parent = QtWidgets.QWidget()
        layout = FLOW(parent)
        layout.setSpacing(4)
        widgets = [HintWidget(30, 20) for _ in range(3)]
        for widget in widgets:
            layout.addWidget(widget)
        changes = []
        layout.lineCountChanged.connect(lambda widget, count: changes.append(count))
        try:
            self.assertEqual(layout.heightForWidth(200), 20)
            self.assertEqual(layout.lineCount, 0)
            self.assertEqual(changes, [])
            layout.setGeometry(QtCore.QRect(0, 0, 200, 100))
            self.assertEqual(layout.lineCount, 1)
            geometries = [QtCore.QRect(layout.itemAt(index).geometry()) for index in range(3)]
            narrow_height = layout.heightForWidth(35)
            self.assertGreater(narrow_height, 20)
            self.assertEqual(layout.lineCount, 1)
            self.assertEqual([layout.itemAt(index).geometry() for index in range(3)], geometries)
            self.assertEqual(changes, [1])
            layout.setGeometry(QtCore.QRect(0, 0, 35, narrow_height))
            self.assertEqual(layout.lineCount, 3)
            layout.setGeometry(QtCore.QRect(0, 0, 35, narrow_height))
            self.assertEqual(changes, [1, 3])
        finally:
            parent.deleteLater()

    def test_native_qt_insert_remove_and_resize_update_geometry(self):
        parent = QtWidgets.QWidget()
        layout = FLOW(parent)
        first, second = HintWidget(30, 20), HintWidget(40, 25)
        try:
            layout.addWidget(first)
            layout.insertWidget(0, second)
            self.assertEqual(layout.count(), 2)
            self.assertIs(layout.itemAt(0).widget(), second)
            layout.setGeometry(QtCore.QRect(0, 0, 200, 100))
            self.assertLess(layout.itemAt(0).geometry().x(), layout.itemAt(1).geometry().x())
            removed = layout.takeAt(0)
            self.assertIs(removed.widget(), second)
            layout.setGeometry(QtCore.QRect(0, 0, 200, 100))
            self.assertEqual(layout.itemAt(0).geometry().x(), 0)
            self.assertEqual(layout.lineCount, 1)
        finally:
            parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
