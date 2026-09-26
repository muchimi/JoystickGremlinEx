# -*- coding: utf-8; -*-
#
# PowerPoint-style overlay selection pane.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

from collections import defaultdict

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

_ROLE_ID = QtCore.Qt.ItemDataRole.UserRole
_ROLE_KIND = QtCore.Qt.ItemDataRole.UserRole + 1
_ROLE_GID = QtCore.Qt.ItemDataRole.UserRole + 2


def widget_type_title(widget_type: str | None) -> str:
    key = str(widget_type or "")
    return _TYPE_TITLES.get(key, key.replace("_", " ").title() or "Widget")


_ICON_EYE_CACHE: dict[bool, QtGui.QIcon] = {}
_ICON_LOCK_CACHE: dict[bool, QtGui.QIcon] = {}
_ICON_FOLDER_CACHE: dict[bool, QtGui.QIcon] = {}


def _icon_eye(visible: bool) -> QtGui.QIcon:
    cached = _ICON_EYE_CACHE.get(visible)
    if cached is not None:
        return cached
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
    icon = QtGui.QIcon(pm)
    _ICON_EYE_CACHE[visible] = icon
    return icon


def _icon_lock(locked: bool) -> QtGui.QIcon:
    cached = _ICON_LOCK_CACHE.get(locked)
    if cached is not None:
        return cached
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
    icon = QtGui.QIcon(pm)
    _ICON_LOCK_CACHE[locked] = icon
    return icon


def _icon_folder(expanded: bool) -> QtGui.QIcon:
    cached = _ICON_FOLDER_CACHE.get(expanded)
    if cached is not None:
        return cached
    pm = QtGui.QPixmap(16, 16)
    pm.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    stroke = QtGui.QColor(Color.normalColor())
    fill = QtGui.QColor(Color.normalColor())
    fill.setAlpha(55 if expanded else 90)
    painter.setPen(QtGui.QPen(stroke, 1.2))
    painter.setBrush(fill)
    # Tab
    painter.drawRoundedRect(QtCore.QRectF(2.0, 3.5, 5.5, 2.5), 1.0, 1.0)
    # Body
    body = QtCore.QRectF(2.0, 5.5, 12.0, 8.0)
    if expanded:
        body = QtCore.QRectF(1.5, 6.0, 13.0, 7.5)
    painter.drawRoundedRect(body, 1.5, 1.5)
    painter.end()
    icon = QtGui.QIcon(pm)
    _ICON_FOLDER_CACHE[expanded] = icon
    return icon


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
        self._tree.setRootIsDecorated(True)
        self._tree.setItemsExpandable(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._tree.setIndentation(18)
        self._tree.setIconSize(QtCore.QSize(16, 16))
        # Branch arrow toggles expand; double-click on a group name also toggles.
        self._tree.setExpandsOnDoubleClick(True)
        self._tree.setAnimated(True)
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
        self._tree.itemExpanded.connect(self._on_group_expanded)
        self._tree.itemCollapsed.connect(self._on_group_collapsed)
        self._tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._tree.setToolTip(
            "Groups appear as folders — click the arrow (or double-click the name) to expand or collapse. "
            "Right-click for the same actions as on the designer canvas. "
            "Eye shows or hides. Lock keeps the position. Shift/Ctrl click to select several, then Group."
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

        self._structure_sig = None
        # Remember which group folders the user left open/closed across refreshes.
        self._group_expanded: dict[str, bool] = {}
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(40)
        self._refresh_timer.timeout.connect(self._refresh_now)
        self.scene.changed.connect(self._schedule_refresh)
        self.scene.selection_changed.connect(self._on_scene_selection)
        self.destroyed.connect(self._detach)
        self._refresh_now()

    def set_canvas(self, canvas):
        self._canvas = canvas

    def _detach(self, *_args):
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        timer = getattr(self, "_refresh_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
        try:
            self.scene.changed.disconnect(self._schedule_refresh)
        except Exception:
            pass
        try:
            self.scene.selection_changed.disconnect(self._on_scene_selection)
        except Exception:
            pass

    def _on_sort(self, value=None):
        if value is None:
            value = getattr(self._sort_box, "_value", None) or "name"
        self._sort = str(value or "name")
        self._structure_sig = None
        self._refresh_now()

    def _structure_signature(self):
        """Ids / names / groups / flags — ignore style and selection so color edits skip rebuilds."""
        rows = []
        for item in self.scene.widgets:
            rows.append(
                (
                    item.get("id"),
                    str(item.get("name") or ""),
                    item.get("type"),
                    str(item.get("group") or ""),
                    bool(item.get("visible", True)),
                    bool(item.get("locked")),
                )
            )
        return (self._sort, tuple(rows))

    def _schedule_refresh(self):
        if not alive(self) or self._syncing:
            return
        timer = getattr(self, "_refresh_timer", None)
        if timer is None:
            self._refresh_now()
            return
        if not timer.isActive():
            timer.start()

    def _sort_key(self, item: dict):
        name = widget_display_name(item).casefold()
        type_title = widget_type_title(item.get("type")).casefold()
        if self._sort == "type":
            return (type_title, name)
        return (name, type_title)

    def _make_widget_row(self, item: dict) -> QtWidgets.QTreeWidgetItem:
        row = QtWidgets.QTreeWidgetItem()
        visible = bool(item.get("visible", True))
        locked = bool(item.get("locked"))
        row.setIcon(0, _icon_eye(visible))
        row.setIcon(1, _icon_lock(locked))
        row.setText(2, widget_display_name(item))
        row.setText(3, widget_type_title(item.get("type")))
        row.setToolTip(0, "Show on the overlay" if not visible else "Hide on the overlay")
        row.setToolTip(1, "Unlock position" if locked else "Lock position")
        row.setData(0, _ROLE_ID, item.get("id"))
        row.setData(0, _ROLE_KIND, "widget")
        row.setChildIndicatorPolicy(QtWidgets.QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
        return row

    def _make_group_row(self, gid: str, members: list[dict], expanded: bool) -> QtWidgets.QTreeWidgetItem:
        row = QtWidgets.QTreeWidgetItem()
        visible = all(bool(m.get("visible", True)) for m in members)
        locked = all(bool(m.get("locked")) for m in members) if members else False
        row.setIcon(0, _icon_eye(visible))
        row.setIcon(1, _icon_lock(locked))
        name = self.scene.group_display_name(gid)
        row.setText(2, name)
        row.setIcon(2, _icon_folder(expanded))
        row.setText(3, f"Group ({len(members)})")
        font = row.font(2)
        font.setBold(True)
        row.setFont(2, font)
        row.setToolTip(0, "Show all widgets in this group" if not visible else "Hide all widgets in this group")
        row.setToolTip(1, "Unlock all in this group" if locked else "Lock all in this group")
        row.setToolTip(2, f"Group folder: {name} — click the arrow or double-click to expand/collapse")
        row.setData(0, _ROLE_KIND, "group")
        row.setData(0, _ROLE_GID, gid)
        row.setFlags(row.flags() | QtCore.Qt.ItemFlag.ItemIsAutoTristate)
        row.setChildIndicatorPolicy(QtWidgets.QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        return row

    def refresh(self):
        """Public entry — coalesce onto the debounce timer when connected to scene.changed."""
        self._schedule_refresh()

    def _remember_expanded_state(self):
        """Snapshot open/closed folders before the tree is cleared."""
        for index in range(self._tree.topLevelItemCount()):
            row = self._tree.topLevelItem(index)
            gid = self._group_id(row)
            if gid:
                self._group_expanded[gid] = row.isExpanded()

    def _on_group_expanded(self, row: QtWidgets.QTreeWidgetItem):
        gid = self._group_id(row)
        if not gid:
            return
        self._group_expanded[gid] = True
        row.setIcon(2, _icon_folder(True))

    def _on_group_collapsed(self, row: QtWidgets.QTreeWidgetItem):
        gid = self._group_id(row)
        if not gid:
            return
        self._group_expanded[gid] = False
        row.setIcon(2, _icon_folder(False))

    def _refresh_now(self):
        if not alive(self) or self._syncing:
            return
        sig = self._structure_signature()
        if sig == self._structure_sig:
            return
        self._structure_sig = sig
        self._syncing = True
        try:
            self._remember_expanded_state()
            widgets = list(self.scene.widgets)
            grouped: dict[str, list[dict]] = defaultdict(list)
            ungrouped: list[dict] = []
            for item in widgets:
                gid = str(item.get("group") or "").strip()
                if gid:
                    grouped[gid].append(item)
                else:
                    ungrouped.append(item)

            for members in grouped.values():
                members.sort(key=self._sort_key)
            ungrouped.sort(key=self._sort_key)
            group_ids = sorted(
                grouped.keys(),
                key=lambda gid: (self.scene.group_display_name(gid).casefold(), gid),
            )

            selected = set(self.scene.selected_ids)
            self._tree.clear()
            has_groups = bool(group_ids)
            # Always keep branch decorations available so group folders show expand arrows.
            self._tree.setRootIsDecorated(True)
            self._tree.setIndentation(18 if has_groups else 8)

            for gid in group_ids:
                members = grouped[gid]
                expanded = self._group_expanded.get(gid, True)
                parent = self._make_group_row(gid, members, expanded)
                self._tree.addTopLevelItem(parent)
                for item in members:
                    child = self._make_widget_row(item)
                    parent.addChild(child)
                    if item.get("id") in selected:
                        child.setSelected(True)
                parent.setExpanded(expanded)
                if any(m.get("id") in selected for m in members):
                    # Keep parent unselected unless every member is selected — avoids
                    # collapsing multi-select into the group row alone.
                    parent.setSelected(all(m.get("id") in selected for m in members))

            for item in ungrouped:
                row = self._make_widget_row(item)
                self._tree.addTopLevelItem(row)
                row.setSelected(item.get("id") in selected)

            # Drop expand memory for groups that no longer exist.
            alive_gids = set(group_ids)
            for gid in list(self._group_expanded):
                if gid not in alive_gids:
                    self._group_expanded.pop(gid, None)

            self._refresh_group_buttons()
        finally:
            self._syncing = False

    def _row_kind(self, row: QtWidgets.QTreeWidgetItem | None) -> str:
        if row is None:
            return ""
        return str(row.data(0, _ROLE_KIND) or "widget")

    def _widget_id(self, row: QtWidgets.QTreeWidgetItem | None) -> str:
        if row is None or self._row_kind(row) != "widget":
            return ""
        return str(row.data(0, _ROLE_ID) or "")

    def _group_id(self, row: QtWidgets.QTreeWidgetItem | None) -> str:
        if row is None or self._row_kind(row) != "group":
            return ""
        return str(row.data(0, _ROLE_GID) or "")

    def _ids_for_row(self, row: QtWidgets.QTreeWidgetItem | None) -> list[str]:
        kind = self._row_kind(row)
        if kind == "widget":
            wid = self._widget_id(row)
            return [wid] if wid else []
        if kind == "group":
            ids = []
            for index in range(row.childCount()):
                wid = self._widget_id(row.child(index))
                if wid:
                    ids.append(wid)
            return ids
        return []

    def _selected_ids(self) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for row in self._tree.selectedItems():
            for wid in self._ids_for_row(row):
                if wid and wid not in seen:
                    ids.append(wid)
                    seen.add(wid)
        return ids

    def _on_item_clicked(self, row: QtWidgets.QTreeWidgetItem, column: int):
        kind = self._row_kind(row)
        if kind == "group":
            members = self._ids_for_row(row)
            if not members:
                return
            if column == 0:
                visible = all(
                    bool((self.scene.widget_by_id(wid) or {}).get("visible", True)) for wid in members
                )
                self.scene.push_undo()
                self.scene.apply_widget_updates(members, visible=not visible)
                return
            if column == 1:
                locked = all(bool((self.scene.widget_by_id(wid) or {}).get("locked")) for wid in members)
                self.scene.push_undo()
                self.scene.apply_widget_updates(members, locked=not locked)
                return
            self._center_on(self._selected_ids() or members)
            return

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

    def _on_tree_context_menu(self, pos: QtCore.QPoint):
        """Match the designer canvas widget context menu."""
        row = self._tree.itemAt(pos)
        if row is not None:
            ids = self._ids_for_row(row)
            if ids:
                selected = set(self.scene.selected_ids)
                # Same as the canvas: right-clicking outside the current selection replaces it.
                if not any(wid in selected for wid in ids):
                    self._syncing = True
                    try:
                        self.scene.set_selection(self.scene.expand_group_ids(ids))
                    finally:
                        self._syncing = False
                    self._on_scene_selection()
        canvas = self._canvas
        if canvas is None or not Shiboken.isValid(canvas):
            return
        show = getattr(canvas, "show_widget_context_menu", None)
        if not callable(show):
            return
        show(self._tree.viewport().mapToGlobal(pos))

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

            def _walk(row: QtWidgets.QTreeWidgetItem):
                kind = self._row_kind(row)
                if kind == "widget":
                    row.setSelected(self._widget_id(row) in selected)
                elif kind == "group":
                    child_ids = self._ids_for_row(row)
                    row.setSelected(bool(child_ids) and all(wid in selected for wid in child_ids))
                    for index in range(row.childCount()):
                        _walk(row.child(index))

            for index in range(self._tree.topLevelItemCount()):
                _walk(self._tree.topLevelItem(index))
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
        if len(self.scene.selected_ids) < 2:
            return
        suggested = self.scene._next_group_name()
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Group widgets",
            "Group name:",
            text=suggested,
        )
        if not ok:
            return
        self.scene.group_selected(name=str(name or "").strip() or suggested)

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
