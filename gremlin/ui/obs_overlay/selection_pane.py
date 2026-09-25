# -*- coding: utf-8; -*-
#
# PowerPoint-style overlay selection pane.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

import gremlin.ui.ui_common
from gremlin.ui.ui_common import Color, QDataPushButton, QDataRadioButtonGroup

from .model import OverlayScene, widget_display_name
from .qt_guard import alive
from .widgets import widget_rotated_bounds

_TYPE_TITLES = {
    "axis_bar": "Bar",
    "axis_radio": "Radio",
    "axis_fader": "Fader",
    "axis_radial": "Radial",
    "axis_encoder": "Encoder",
    "axis_paddle": "Paddle",
    "axis_stick_square": "X/Y",
    "axis_crosshair": "Radar",
    "axis_stick_circle": "Circular",
    "axis_mouse": "Mouse",
    "axis_graph": "Temporal graph",
    "axis_bars": "Bar graph",
    "button": "Button",
    "hat": "Hat",
    "switch_4way": "4-way switch",
    "switch_2way": "2-way toggle",
    "switch_3way": "3-way switch",
    "label": "Label",
    "sys_stats": "Counter",
    "stopwatch": "Stopwatch",
    "input_display": "Keyboard / Mouse",
    "shape": "Shape",
    "image": "Image",
    "application": "Application",
    "remote_view": "Remote View",
    "streamdeck": "Stream Deck",
}


def widget_type_title(widget_type: str | None) -> str:
    key = str(widget_type or "")
    return _TYPE_TITLES.get(key, key.replace("_", " ").title() or "Widget")


def _icon_eye(visible: bool) -> QtGui.QIcon:
    pm = QtGui.QPixmap(16, 16)
    pm.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    color = QtGui.QColor(Color.normalColor() if visible else Color.inactiveColor())
    painter.setPen(QtGui.QPen(color, 1.4))
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawEllipse(QtCore.QRectF(2.5, 5.0, 11.0, 6.0))
    if visible:
        painter.setBrush(color)
        painter.drawEllipse(QtCore.QRectF(6.0, 6.2, 4.0, 4.0))
    else:
        painter.drawLine(3, 13, 13, 3)
    painter.end()
    return QtGui.QIcon(pm)


def _icon_lock(locked: bool) -> QtGui.QIcon:
    pm = QtGui.QPixmap(16, 16)
    pm.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    color = QtGui.QColor(Color.orangeColor() if locked else Color.inactiveColor())
    painter.setPen(QtGui.QPen(color, 1.4))
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawRoundedRect(QtCore.QRectF(4.0, 7.5, 8.0, 6.0), 1.5, 1.5)
    painter.drawArc(QtCore.QRectF(5.2, 3.2, 5.6, 6.0), 0, 180 * 16)
    if locked:
        painter.setBrush(color)
        painter.drawEllipse(QtCore.QRectF(7.0, 9.2, 2.0, 2.0))
    painter.end()
    return QtGui.QIcon(pm)


class OverlaySelectionPane(QtWidgets.QWidget):
    """Lists widgets on the active overlay page: show/hide, lock, select, group."""

    def __init__(self, scene: OverlayScene, canvas=None, parent=None):
        super().__init__(parent)
        self.scene = scene
        self._canvas = canvas
        self._syncing = False
        self._sort = "name"
        self.setMinimumWidth(200)
        self.setMaximumWidth(280)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)
        title = QtWidgets.QLabel("Selection pane")
        title.setStyleSheet("font-weight: bold;")
        root.addWidget(title)

        sort_row = QtWidgets.QHBoxLayout()
        sort_row.addWidget(QtWidgets.QLabel("Sort"))
        self._sort_box = QDataRadioButtonGroup(
            [("Name", "name"), ("Type", "type")],
            value="name",
            callback=self._on_sort,
        )
        if self._sort_box.layout() is not None:
            self._sort_box.layout().setContentsMargins(0, 0, 0, 0)
        sort_row.addWidget(self._sort_box, 1)
        root.addLayout(sort_row)

        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderLabels(["", "", "Name", "Type"])
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._tree.setIndentation(0)
        self._tree.setIconSize(QtCore.QSize(16, 16))
        header = self._tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        self._tree.setColumnWidth(0, 28)
        self._tree.setColumnWidth(1, 28)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemSelectionChanged.connect(self._on_tree_selection)
        self._tree.setToolTip(
            "Click a name to select it and center the canvas. Eye shows or hides. Lock keeps the position. "
            "Shift/Ctrl click to select several, then Group."
        )
        root.addWidget(self._tree, 1)

        self._group_btn = QDataPushButton(
            "Group",
            tooltip="Group the widgets selected in this list (Ctrl+G).",
            clicked=self._group,
        )
        self._ungroup_btn = QDataPushButton(
            "Ungroup",
            tooltip="Ungroup the selected widgets (Ctrl+Shift+G).",
            clicked=self._ungroup,
        )
        root.addWidget(
            gremlin.ui.ui_common.getHContainer([self._group_btn, self._ungroup_btn], widget_only=True)
        )

        self.scene.changed.connect(self.refresh)
        self.scene.selection_changed.connect(self._on_scene_selection)
        self.destroyed.connect(self._detach)
        self.refresh()

    def set_canvas(self, canvas):
        self._canvas = canvas

    def _detach(self, *_args):
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        try:
            self.scene.changed.disconnect(self.refresh)
        except Exception:
            pass
        try:
            self.scene.selection_changed.disconnect(self._on_scene_selection)
        except Exception:
            pass

    def _on_sort(self, value=None):
        self._sort = str(value if value is not None else (self._sort_box.currentData() or "name"))
        self.refresh()

    def refresh(self):
        if not alive(self) or self._syncing:
            return
        self._syncing = True
        try:
            widgets = list(self.scene.widgets)
            if self._sort == "type":
                widgets.sort(key=lambda w: (widget_type_title(w.get("type")).casefold(), widget_display_name(w).casefold()))
            else:
                widgets.sort(key=lambda w: (widget_display_name(w).casefold(), widget_type_title(w.get("type")).casefold()))
            selected = set(self.scene.selected_ids)
            self._tree.clear()
            for item in widgets:
                row = QtWidgets.QTreeWidgetItem()
                visible = bool(item.get("visible", True))
                locked = bool(item.get("locked"))
                row.setIcon(0, _icon_eye(visible))
                row.setIcon(1, _icon_lock(locked))
                row.setText(2, widget_display_name(item))
                row.setText(3, widget_type_title(item.get("type")))
                row.setToolTip(0, "Show on the overlay" if not visible else "Hide on the overlay")
                row.setToolTip(1, "Unlock position" if locked else "Lock position")
                row.setData(0, QtCore.Qt.UserRole, item.get("id"))
                if str(item.get("group") or "").strip():
                    font = row.font(2)
                    font.setItalic(True)
                    row.setFont(2, font)
                self._tree.addTopLevelItem(row)
                row.setSelected(item.get("id") in selected)
            self._refresh_group_buttons()
        finally:
            self._syncing = False

    def _widget_id(self, row: QtWidgets.QTreeWidgetItem | None) -> str:
        if row is None:
            return ""
        return str(row.data(0, QtCore.Qt.UserRole) or "")

    def _selected_ids(self) -> list[str]:
        ids = []
        for row in self._tree.selectedItems():
            wid = self._widget_id(row)
            if wid:
                ids.append(wid)
        return ids

    def _on_item_clicked(self, row: QtWidgets.QTreeWidgetItem, column: int):
        wid = self._widget_id(row)
        if not wid:
            return
        item = self.scene.widget_by_id(wid)
        if item is None:
            return
        if column == 0:
            self.scene.push_undo()
            self.scene.apply_widget_update(wid, visible=not bool(item.get("visible", True)))
            return
        if column == 1:
            self.scene.push_undo()
            self.scene.apply_widget_update(wid, locked=not bool(item.get("locked")))
            return
        self._center_on(self._selected_ids() or [wid])

    def _on_tree_selection(self):
        if self._syncing:
            return
        ids = self._selected_ids()
        current = list(self.scene.selected_ids)
        if ids == current:
            self._refresh_group_buttons()
            return
        self._syncing = True
        try:
            self.scene.set_selection(ids)
        finally:
            self._syncing = False
        self._refresh_group_buttons()

    def _on_scene_selection(self):
        if self._syncing or not alive(self):
            return
        selected = set(self.scene.selected_ids)
        self._syncing = True
        try:
            self._tree.blockSignals(True)
            for index in range(self._tree.topLevelItemCount()):
                row = self._tree.topLevelItem(index)
                row.setSelected(self._widget_id(row) in selected)
            self._tree.blockSignals(False)
            self._refresh_group_buttons()
        finally:
            self._syncing = False

    def _refresh_group_buttons(self):
        ids = self._selected_ids() or list(self.scene.selected_ids)
        self._group_btn.setEnabled(len(ids) >= 2)
        grouped = False
        for wid in ids:
            item = self.scene.widget_by_id(wid)
            if item and str(item.get("group") or "").strip():
                grouped = True
                break
        self._ungroup_btn.setEnabled(grouped)

    def _group(self):
        ids = self._selected_ids()
        if ids:
            self.scene.set_selection(ids)
        self.scene.group_selected()

    def _ungroup(self):
        ids = self._selected_ids()
        if ids:
            self.scene.set_selection(ids)
        self.scene.ungroup_selected()

    def _center_on(self, ids: list[str]):
        canvas = self._canvas
        if canvas is None or not Shiboken.isValid(canvas):
            return
        center = getattr(canvas, "center_on_widgets", None)
        if callable(center):
            center(ids)
            return
        bounds = None
        for wid in ids:
            item = self.scene.widget_by_id(wid)
            if not item:
                continue
            rect = widget_rotated_bounds(item)
            bounds = rect if bounds is None else bounds.united(rect)
        if bounds is not None and hasattr(canvas, "center_on_scene_rect"):
            canvas.center_on_scene_rect(bounds)
