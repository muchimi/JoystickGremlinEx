# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Map to Overlay — drive overlay visibility, interactive mode, control panel, and variables."""

from __future__ import annotations

import logging
from typing import Any

from lxml import etree as ElementTree
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

import gremlin.base_profile
import gremlin.event_handler
import gremlin.input_item
import gremlin.ui.ui_common
import gremlin.util
from gremlin.input_types import InputType
from gremlin.repeater import PulseWorker
from gremlin.types import VjoyAction
from gremlin.util import safe_format, safe_read

syslog = logging.getLogger("system")

OVERLAY_ACTIONS = (
    ("visibility", "Show/Hide Page, Group, or Widget"),
    ("interactive", "Turn Interactive mode On/Off"),
    ("control_panel", "Show/Hide Runtime Control Panel"),
    ("set_variable", "Set overlay variable"),
    ("set_image", "Set image widget (OCR chart)"),
    ("citizen_lookup", "RSI citizen lookup (SC Intelligence)"),
)

VARIABLE_WRITE_MODES = (
    ("replace", "Replace"),
    ("contribute", "Contribute (multi-hit)"),
)

TARGET_KINDS = (
    ("page", "Page"),
    ("group", "Group"),
    ("widget", "Widget"),
)

BUTTON_MODES = (
    VjoyAction.VJoyButton,
    VjoyAction.VJoyButtonInverted,
    VjoyAction.VJoyButtonPress,
    VjoyAction.VJoyButtonRelease,
    VjoyAction.VJoyPulse,
    VjoyAction.VJoyToggle,
)

GRID_CELL_MIN = 72
GRID_CELL_MAX = 140
GRID_CELL_DEFAULT = 96


def _overlay_scene():
    try:
        from gremlin.ui.obs_overlay import OverlayManager

        return OverlayManager().scene
    except Exception:
        return None


def _overlay_manager():
    try:
        from gremlin.ui.obs_overlay import OverlayManager

        return OverlayManager()
    except Exception:
        return None


def _find_widget(scene, widget_id: str) -> tuple[dict | None, dict | None]:
    wid = str(widget_id or "").strip()
    if not scene or not wid:
        return None, None
    for page in scene.pages or []:
        for item in page.get("widgets") or []:
            if str(item.get("id") or "") == wid:
                return page, item
    return None, None


def _group_members(scene, group_id: str) -> tuple[list[str], set[str]]:
    gid = str(group_id or "").strip()
    widget_ids: list[str] = []
    page_ids: set[str] = set()
    if not scene or not gid:
        return widget_ids, page_ids
    for page in scene.pages or []:
        pid = str(page.get("id") or "")
        for item in page.get("widgets") or []:
            if str(item.get("group") or "").strip() == gid:
                wid = str(item.get("id") or "")
                if wid:
                    widget_ids.append(wid)
                    if pid:
                        page_ids.add(pid)
    return widget_ids, page_ids


def _items_for_thumbnail(kind: str, target_id: str) -> tuple[list[dict], dict | None]:
    """Return (widget items, optional page canvas) for a thumbnail target."""
    scene = _overlay_scene()
    if scene is None:
        return [], None
    kind = (kind or "page").casefold()
    tid = str(target_id or "").strip()
    if not tid:
        return [], None
    if kind == "page":
        page = scene.page_by_id(tid)
        if page is None:
            return [], None
        items = list(page.get("widgets") or [])
        canvas = page.get("canvas") if isinstance(page.get("canvas"), dict) else None
        return items, canvas
    if kind == "group":
        items = []
        canvas = None
        for page in scene.pages or []:
            for item in page.get("widgets") or []:
                if str(item.get("group") or "").strip() == tid:
                    items.append(item)
                    if canvas is None and isinstance(page.get("canvas"), dict):
                        canvas = page.get("canvas")
        return items, canvas
    page, item = _find_widget(scene, tid)
    if item is None:
        return [], None
    canvas = page.get("canvas") if page and isinstance(page.get("canvas"), dict) else None
    return [item], canvas


def _render_thumbnail(kind: str, target_id: str, size: int) -> QtGui.QPixmap:
    """Paint a compact preview of a page, group, or widget into a square pixmap."""
    size = max(32, int(size))
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtGui.QColor("#1b2230"))
    items, canvas = _items_for_thumbnail(kind, target_id)
    if not items and kind != "page":
        return pm

    from gremlin.ui.obs_overlay.widgets import (
        paint_background,
        paint_widget,
        widget_dirty_rect,
    )

    painter = QtGui.QPainter(pm)
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        margin = 4.0
        avail = max(8.0, float(size) - margin * 2.0)

        if kind == "page" and canvas is not None:
            try:
                cw = max(1, int(canvas.get("width") or 1920))
                ch = max(1, int(canvas.get("height") or 1080))
            except (TypeError, ValueError):
                cw, ch = 1920, 1080
            canvas_rect = QtCore.QRect(0, 0, cw, ch)
            scale = min(avail / float(cw), avail / float(ch))
            ox = margin + (avail - cw * scale) * 0.5
            oy = margin + (avail - ch * scale) * 0.5
            painter.translate(ox, oy)
            painter.scale(scale, scale)
            paint_background(painter, canvas, canvas_rect, preview=True)
            ordered = sorted(items, key=lambda w: (int(w.get("z") or 0), str(w.get("id") or "")))
            for item in ordered:
                if not item or not item.get("visible", True):
                    continue
                try:
                    paint_widget(painter, item, None, draw_shadow=False)
                except Exception:
                    continue
            return pm

        # Widget / group: fit dirty bounds of the selection.
        bounds = QtCore.QRect()
        ordered = sorted(items, key=lambda w: (int(w.get("z") or 0), str(w.get("id") or "")))
        paint_items = []
        for item in ordered:
            if not item:
                continue
            forced = {**item, "visible": True}
            paint_items.append(forced)
            try:
                dirty = widget_dirty_rect(forced)
            except Exception:
                dirty = QtCore.QRect(
                    int(item.get("x") or 0),
                    int(item.get("y") or 0),
                    max(1, int(item.get("w") or 1)),
                    max(1, int(item.get("h") or 1)),
                )
            bounds = bounds.united(dirty) if not bounds.isNull() else dirty
        if bounds.isNull() or bounds.width() <= 0 or bounds.height() <= 0:
            return pm

        scale = min(avail / float(bounds.width()), avail / float(bounds.height()))
        ox = margin + (avail - bounds.width() * scale) * 0.5
        oy = margin + (avail - bounds.height() * scale) * 0.5
        painter.translate(ox, oy)
        painter.scale(scale, scale)
        painter.translate(-bounds.x(), -bounds.y())
        painter.fillRect(bounds, QtGui.QColor("#121826"))
        for item in paint_items:
            try:
                paint_widget(painter, item, None, draw_shadow=False)
            except Exception:
                continue
    finally:
        painter.end()
    return pm


def _list_pages(scene) -> list[dict[str, Any]]:
    rows = []
    if not scene:
        return rows
    for page in scene.pages or []:
        pid = str(page.get("id") or "")
        if not pid:
            continue
        rows.append(
            {
                "id": pid,
                "name": str(page.get("name") or "Overlay"),
                "kind": "page",
                "subtitle": f"{len(page.get('widgets') or [])} widgets",
            }
        )
    return rows


def _list_groups(scene) -> list[dict[str, Any]]:
    rows = []
    if not scene:
        return rows
    seen: set[str] = set()
    for page in scene.pages or []:
        page_name = str(page.get("name") or "Overlay")
        for item in page.get("widgets") or []:
            gid = str(item.get("group") or "").strip()
            if not gid or gid in seen:
                continue
            seen.add(gid)
            members, _pages = _group_members(scene, gid)
            rows.append(
                {
                    "id": gid,
                    "name": scene.group_display_name(gid),
                    "kind": "group",
                    "subtitle": f"{len(members)} on {page_name}",
                }
            )
    rows.sort(key=lambda r: (str(r["name"]).casefold(), r["id"]))
    return rows


def _list_widgets(scene) -> list[dict[str, Any]]:
    from gremlin.ui.obs_overlay.model import widget_display_name

    rows = []
    if not scene:
        return rows
    for page in scene.pages or []:
        page_name = str(page.get("name") or "Overlay")
        for item in page.get("widgets") or []:
            wid = str(item.get("id") or "")
            if not wid:
                continue
            wtype = str(item.get("type") or "widget").replace("_", " ")
            rows.append(
                {
                    "id": wid,
                    "name": widget_display_name(item),
                    "kind": "widget",
                    "subtitle": f"{wtype} - {page_name}",
                    "type": item.get("type"),
                }
            )
    rows.sort(key=lambda r: (str(r["name"]).casefold(), r["id"]))
    return rows


def _target_rows(scene, kind: str) -> list[dict[str, Any]]:
    kind = (kind or "page").casefold()
    if kind == "group":
        return _list_groups(scene)
    if kind == "widget":
        return _list_widgets(scene)
    return _list_pages(scene)


# ---------------------------------------------------------------------------
# Target picker (list / grid)
# ---------------------------------------------------------------------------


class OverlayTargetPicker(QtWidgets.QWidget):
    """Multi-select list or compact grid of overlay pages / groups / widgets."""

    selection_changed = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._kind = "page"
        self._selected: set[str] = set()
        self._view_mode = "list"
        self._cell = GRID_CELL_DEFAULT
        self._rows: list[dict[str, Any]] = []
        self._building = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        self._list_btn = QtWidgets.QPushButton("List", self)
        self._list_btn.setCheckable(True)
        self._list_btn.setChecked(True)
        self._grid_btn = QtWidgets.QPushButton("Grid", self)
        self._grid_btn.setCheckable(True)
        self._list_btn.clicked.connect(lambda: self._set_view("list"))
        self._grid_btn.clicked.connect(lambda: self._set_view("grid"))
        toolbar.addWidget(self._list_btn)
        toolbar.addWidget(self._grid_btn)
        toolbar.addSpacing(8)
        toolbar.addWidget(QtWidgets.QLabel("Size:", self))
        self._size = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self._size.setRange(GRID_CELL_MIN, GRID_CELL_MAX)
        self._size.setValue(GRID_CELL_DEFAULT)
        self._size.setFixedWidth(100)
        self._size.valueChanged.connect(self._on_size)
        toolbar.addWidget(self._size)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self._stack = QtWidgets.QStackedWidget(self)
        self._list = QtWidgets.QListWidget(self)
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self._list.itemChanged.connect(self._on_list_item)
        self._stack.addWidget(self._list)

        self._grid_host = QtWidgets.QScrollArea(self)
        self._grid_host.setWidgetResizable(True)
        self._grid_host.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._grid_inner = QtWidgets.QWidget()
        self._grid_layout = QtWidgets.QGridLayout(self._grid_inner)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(6)
        self._grid_host.setWidget(self._grid_inner)
        self._stack.addWidget(self._grid_host)
        root.addWidget(self._stack, 1)

        self.setMinimumHeight(160)
        self.setMaximumHeight(320)

    def set_kind(self, kind: str, selected_ids: list[str] | None = None):
        self._kind = (kind or "page").casefold()
        if selected_ids is not None:
            self._selected = {str(i) for i in selected_ids if str(i or "").strip()}
        self.refresh()

    def selected_ids(self) -> list[str]:
        return sorted(self._selected)

    def set_selected_ids(self, ids: list[str]):
        self._selected = {str(i) for i in (ids or []) if str(i or "").strip()}
        self.refresh()

    def refresh(self):
        scene = _overlay_scene()
        self._rows = _target_rows(scene, self._kind)
        known = {r["id"] for r in self._rows}
        for sid in list(self._selected):
            if sid not in known:
                self._rows.append(
                    {
                        "id": sid,
                        "name": f"(missing) {sid[:8]}...",
                        "kind": self._kind,
                        "subtitle": "not in current overlay",
                        "missing": True,
                    }
                )
        self._rebuild()

    def _set_view(self, mode: str):
        self._view_mode = "grid" if mode == "grid" else "list"
        self._list_btn.setChecked(self._view_mode == "list")
        self._grid_btn.setChecked(self._view_mode == "grid")
        self._size.setEnabled(self._view_mode == "grid")
        self._stack.setCurrentIndex(1 if self._view_mode == "grid" else 0)
        self._rebuild()

    def _on_size(self, value: int):
        self._cell = int(value)
        if self._view_mode == "grid":
            self._rebuild()

    def _rebuild(self):
        self._building = True
        try:
            if self._view_mode == "grid":
                self._rebuild_grid()
            else:
                self._rebuild_list()
        finally:
            self._building = False

    def _rebuild_list(self):
        self._list.clear()
        for row in self._rows:
            item = QtWidgets.QListWidgetItem(f"{row['name']} - {row.get('subtitle') or ''}")
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if row["id"] in self._selected else QtCore.Qt.Unchecked)
            item.setData(QtCore.Qt.UserRole, row["id"])
            if row.get("missing"):
                item.setForeground(QtGui.QBrush(QtGui.QColor("#c97b7b")))
            self._list.addItem(item)

    def _rebuild_grid(self):
        while self._grid_layout.count():
            child = self._grid_layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()
        cell = max(GRID_CELL_MIN, min(GRID_CELL_MAX, int(self._cell)))
        cols = max(2, self._grid_host.viewport().width() // (cell + 8)) if self._grid_host.viewport().width() > 0 else 3
        for index, row in enumerate(self._rows):
            tile = self._make_tile(row, cell)
            self._grid_layout.addWidget(tile, index // cols, index % cols)
        self._grid_layout.setRowStretch((len(self._rows) + cols - 1) // cols, 1)
        self._grid_layout.setColumnStretch(cols, 1)

    def _make_tile(self, row: dict, cell: int) -> QtWidgets.QWidget:
        box = QtWidgets.QFrame(self)
        box.setFrameShape(QtWidgets.QFrame.StyledPanel)
        box.setFixedSize(cell, cell + 22)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        thumb_size = max(40, cell - 6)
        thumb = QtWidgets.QLabel(box)
        thumb.setFixedSize(thumb_size, thumb_size)
        thumb.setAlignment(QtCore.Qt.AlignCenter)
        thumb.setStyleSheet("background: #121826; border: 1px solid #2c3a52;")
        if row.get("missing"):
            thumb.setText("missing")
            thumb.setStyleSheet("color: #c97b7b; background: #121826; border: 1px solid #2c3a52;")
        else:
            try:
                pm = _render_thumbnail(str(row.get("kind") or self._kind), str(row["id"]), thumb_size)
                thumb.setPixmap(pm)
            except Exception:
                thumb.setText(str(row.get("kind") or "?"))
        layout.addWidget(thumb, 0, QtCore.Qt.AlignHCenter)

        check = QtWidgets.QCheckBox(row["name"], box)
        check.setChecked(row["id"] in self._selected)
        if row.get("missing"):
            check.setStyleSheet("color: #c97b7b;")
        # Elide long names so the checkbox row stays compact.
        metrics = check.fontMetrics()
        elided = metrics.elidedText(row["name"], QtCore.Qt.ElideRight, max(48, cell - 8))
        check.setText(elided)
        check.setToolTip(f"{row['name']}\n{row.get('subtitle') or ''}".strip())
        check.toggled.connect(lambda on, rid=row["id"]: self._toggle_id(rid, on))
        layout.addWidget(check)
        return box

    def _on_list_item(self, item: QtWidgets.QListWidgetItem):
        if self._building:
            return
        rid = item.data(QtCore.Qt.UserRole)
        if not rid:
            return
        self._toggle_id(str(rid), item.checkState() == QtCore.Qt.Checked)

    def _toggle_id(self, rid: str, selected: bool):
        if selected:
            self._selected.add(rid)
        else:
            self._selected.discard(rid)
        if not self._building:
            self.selection_changed.emit(self.selected_ids())


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------


class MapToOverlayWidget(gremlin.input_item.AbstractActionWidget):
    """Configuration UI for Map to Overlay."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, QtWidgets.QVBoxLayout, parent=parent)
        assert isinstance(action_data, MapToOverlay)

    def _create(self, action_data):
        self.action_data: MapToOverlay = action_data

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return

        self._action_box = gremlin.ui.ui_common.QDataComboBox(self)
        for value, label in OVERLAY_ACTIONS:
            self._action_box.addItem(label, value)
        self._action_box.currentIndexChanged.connect(self._on_action)

        self._mode_box = gremlin.ui.ui_common.QDataComboBox(self)
        for mode in BUTTON_MODES:
            self._mode_box.addItem(VjoyAction.to_name(mode), mode)
        self._mode_box.currentIndexChanged.connect(self._on_mode)

        self._pulse_widget = gremlin.ui.ui_common.QDelayWidget()
        self._pulse_widget.setToolTip("Pulse duration in milliseconds")
        self._pulse_widget.valueChanged.connect(self._on_pulse)

        self._top_form = QtWidgets.QFormLayout()
        self._top_form.setContentsMargins(0, 0, 0, 0)
        self._top_form.addRow("Action:", self._action_box)
        self._top_form.addRow("Mode:", self._mode_box)
        self._pulse_row = QtWidgets.QWidget(self)
        pulse_layout = QtWidgets.QHBoxLayout(self._pulse_row)
        pulse_layout.setContentsMargins(0, 0, 0, 0)
        pulse_layout.addWidget(self._pulse_widget)
        pulse_layout.addStretch(1)
        self._top_form.addRow("Pulse:", self._pulse_row)
        self.main_layout.addLayout(self._top_form)

        self._targets_box = QtWidgets.QGroupBox("Targets", self)
        targets_layout = QtWidgets.QVBoxLayout(self._targets_box)
        targets_layout.setContentsMargins(8, 8, 8, 8)

        kind_row = QtWidgets.QHBoxLayout()
        kind_row.addWidget(QtWidgets.QLabel("Select:", self))
        self._kind_group = QtWidgets.QButtonGroup(self)
        self._kind_buttons: dict[str, QtWidgets.QRadioButton] = {}
        for value, label in TARGET_KINDS:
            rb = QtWidgets.QRadioButton(label, self)
            rb.setProperty("kind", value)
            self._kind_group.addButton(rb)
            self._kind_buttons[value] = rb
            rb.toggled.connect(self._on_kind)
            kind_row.addWidget(rb)
        kind_row.addStretch(1)
        targets_layout.addLayout(kind_row)

        self._picker = OverlayTargetPicker(self)
        self._picker.selection_changed.connect(self._on_selection)
        targets_layout.addWidget(self._picker)

        self._bypass = QtWidgets.QCheckBox(
            "Bypass page / group (show selection even if its page is not current)",
            self,
        )
        self._bypass.setToolTip(
            "When checked, selected groups or widgets are shown even if their overlay page "
            "window is not currently displayed. Only the selection is affected  -  not the full parent page."
        )
        self._bypass.toggled.connect(self._on_bypass)
        targets_layout.addWidget(self._bypass)

        self.main_layout.addWidget(self._targets_box)

        # ---- Set variable panel ----
        self._variable_box = QtWidgets.QGroupBox("Variable", self)
        var_form = QtWidgets.QFormLayout(self._variable_box)
        self._variable_combo = gremlin.ui.ui_common.QDataComboBox(self)
        self._variable_combo.currentIndexChanged.connect(self._on_variable)
        var_form.addRow("Name:", self._variable_combo)

        self._write_mode_box = gremlin.ui.ui_common.QDataComboBox(self)
        for value, label in VARIABLE_WRITE_MODES:
            self._write_mode_box.addItem(label, value)
        self._write_mode_box.currentIndexChanged.connect(self._on_write_mode)
        var_form.addRow("Write:", self._write_mode_box)

        self._use_detection = QtWidgets.QCheckBox(
            "Use detection label from OCR event (e.g. Quantainium ×2)",
            self,
        )
        self._use_detection.setToolTip(
            "When the input is an OCR rule-as-button, contribute/replace with the computed detection label."
        )
        self._use_detection.toggled.connect(self._on_use_detection)
        var_form.addRow(self._use_detection)

        self._press_value = QtWidgets.QLineEdit(self)
        self._press_value.setPlaceholderText("Value on press")
        self._press_value.editingFinished.connect(self._on_press_value)
        self._press_empty = QtWidgets.QCheckBox("Empty", self)
        self._press_empty.toggled.connect(self._on_press_empty)
        press_row = QtWidgets.QHBoxLayout()
        press_row.addWidget(self._press_value, 1)
        press_row.addWidget(self._press_empty)
        press_host = QtWidgets.QWidget(self)
        press_host.setLayout(press_row)
        var_form.addRow("On pressed:", press_host)

        self._release_value = QtWidgets.QLineEdit(self)
        self._release_value.setPlaceholderText("Value on release")
        self._release_value.editingFinished.connect(self._on_release_value)
        self._release_empty = QtWidgets.QCheckBox("Empty", self)
        self._release_empty.toggled.connect(self._on_release_empty)
        release_row = QtWidgets.QHBoxLayout()
        release_row.addWidget(self._release_value, 1)
        release_row.addWidget(self._release_empty)
        release_host = QtWidgets.QWidget(self)
        release_host.setLayout(release_row)
        var_form.addRow("On released:", release_host)

        self.main_layout.addWidget(self._variable_box)

        # ---- Set image panel (OCR EFB charts) ----
        self._image_box = QtWidgets.QGroupBox("Image widget", self)
        img_form = QtWidgets.QFormLayout(self._image_box)
        self._image_widget_name = QtWidgets.QLineEdit(self)
        self._image_widget_name.setPlaceholderText("SC EFB Chart")
        self._image_widget_name.editingFinished.connect(self._on_image_widget_name)
        img_form.addRow("Widget name:", self._image_widget_name)
        self._chart_url = QtWidgets.QLineEdit(self)
        self._chart_url.setPlaceholderText("Direct chart image URL (optional)")
        self._chart_url.editingFinished.connect(self._on_chart_url)
        img_form.addRow("Chart URL:", self._chart_url)
        self._page_url = QtWidgets.QLineEdit(self)
        self._page_url.setPlaceholderText("Delta Consulting location page (scrapes chart)")
        self._page_url.editingFinished.connect(self._on_page_url)
        img_form.addRow("Page URL:", self._page_url)
        self._chart_id = QtWidgets.QLineEdit(self)
        self._chart_id.setPlaceholderText("Cache id (optional)")
        self._chart_id.editingFinished.connect(self._on_chart_id)
        img_form.addRow("Chart id:", self._chart_id)
        self.main_layout.addWidget(self._image_box)

        hint = QtWidgets.QLabel(
            "Local only — uses the overlay layout stored with this profile. "
            "Contribute mode joins simultaneous active values into one variable (e.g. %rock%). "
            "Set image / RSI citizen lookup are used by SC EFB and SC Intelligence OCR packs.",
            self,
        )
        hint.setStyleSheet("color: #9aa3b2;")
        hint.setWordWrap(True)
        self.main_layout.addWidget(hint)
    def _populate_ui(self):
        if not Shiboken.isValid(self):
            return
        data = self.action_data
        with QtCore.QSignalBlocker(self._action_box):
            idx = self._action_box.findData(data.overlay_action)
            self._action_box.setCurrentIndex(idx if idx >= 0 else 0)
        with QtCore.QSignalBlocker(self._mode_box):
            idx = self._mode_box.findData(data.button_mode)
            self._mode_box.setCurrentIndex(idx if idx >= 0 else 0)
        with QtCore.QSignalBlocker(self._pulse_widget):
            self._pulse_widget.setValue(int(data.pulse_delay or 250))
        with QtCore.QSignalBlocker(self._bypass):
            self._bypass.setChecked(bool(data.bypass_parent))
        kind = data.target_kind if data.target_kind in self._kind_buttons else "page"
        btn = self._kind_buttons.get(kind)
        if btn is not None:
            with QtCore.QSignalBlocker(btn):
                btn.setChecked(True)
        self._picker.set_kind(kind, list(data.selected_ids or []))
        self._refresh_variable_combo()
        with QtCore.QSignalBlocker(self._write_mode_box):
            idx = self._write_mode_box.findData(data.variable_write)
            self._write_mode_box.setCurrentIndex(idx if idx >= 0 else 0)
        with QtCore.QSignalBlocker(self._use_detection):
            self._use_detection.setChecked(bool(data.use_detection_label))
        with QtCore.QSignalBlocker(self._press_empty):
            self._press_empty.setChecked(bool(data.press_empty))
        with QtCore.QSignalBlocker(self._release_empty):
            self._release_empty.setChecked(bool(data.release_empty))
        with QtCore.QSignalBlocker(self._press_value):
            self._press_value.setText(str(data.press_value or ""))
            self._press_value.setEnabled(not bool(data.press_empty))
        with QtCore.QSignalBlocker(self._release_value):
            self._release_value.setText(str(data.release_value or ""))
            self._release_value.setEnabled(not bool(data.release_empty))
        with QtCore.QSignalBlocker(self._image_widget_name):
            self._image_widget_name.setText(str(data.image_widget_name or "SC EFB Chart"))
        with QtCore.QSignalBlocker(self._chart_url):
            self._chart_url.setText(str(data.chart_url or ""))
        with QtCore.QSignalBlocker(self._page_url):
            self._page_url.setText(str(data.page_url or ""))
        with QtCore.QSignalBlocker(self._chart_id):
            self._chart_id.setText(str(data.chart_id or ""))
        self._update_visibility()

    def _refresh_variable_combo(self):
        scene = _overlay_scene()
        names = []
        if scene is not None:
            for row in getattr(scene, "variables", None) or []:
                name = str((row or {}).get("name") or "").strip()
                if name:
                    names.append(name)
        names = sorted(set(names), key=str.casefold)
        current = str(self.action_data.variable_name or "").strip()
        with QtCore.QSignalBlocker(self._variable_combo):
            self._variable_combo.clear()
            self._variable_combo.addItem("(none)", "")
            for name in names:
                self._variable_combo.addItem(f"%{name}%", name)
            if current and current not in names:
                self._variable_combo.addItem(f"%{current}%", current)
            idx = self._variable_combo.findData(current)
            self._variable_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _set_top_row_visible(self, field: QtWidgets.QWidget, visible: bool):
        """Show/hide a QFormLayout row including its label (setVisible alone leaves the label)."""
        field.setVisible(visible)
        try:
            self._top_form.setRowVisible(field, visible)
        except Exception:
            label = self._top_form.labelForField(field)
            if label is not None:
                label.setVisible(visible)

    def _update_visibility(self):
        action = self.action_data.overlay_action
        show_targets = action in ("visibility", "interactive")
        self._targets_box.setVisible(show_targets)
        self._variable_box.setVisible(action == "set_variable")
        if hasattr(self, "_image_box"):
            self._image_box.setVisible(action == "set_image")
        # Mode / Pulse apply to all actions (incl. set_variable hold/toggle/pulse).
        self._set_top_row_visible(self._mode_box, True)
        show_pulse = self.action_data.button_mode == VjoyAction.VJoyPulse
        self._set_top_row_visible(self._pulse_row, show_pulse)
        kind_enabled = action == "visibility"
        for rb in self._kind_buttons.values():
            rb.setEnabled(kind_enabled)
        if action == "interactive":
            # Force page targets for interactive.
            if self.action_data.target_kind != "page":
                self.action_data.target_kind = "page"
                self.action_data.selected_ids = list(self.action_data.selected_ids or [])
            page_btn = self._kind_buttons.get("page")
            if page_btn is not None and not page_btn.isChecked():
                with QtCore.QSignalBlocker(page_btn):
                    page_btn.setChecked(True)
            self._picker.set_kind("page", list(self.action_data.selected_ids or []))
        self._bypass.setVisible(action == "visibility" and self.action_data.target_kind in ("group", "widget"))
        use_det = bool(self.action_data.use_detection_label)
        write = str(self.action_data.variable_write or "replace")
        # Fixed press/release strings are for replace; contribute uses detection or press_value as contribution.
        self._press_value.setEnabled(not bool(self.action_data.press_empty) and not (use_det and write == "contribute"))
        self._release_value.setEnabled(not bool(self.action_data.release_empty) and write == "replace")
        self._release_empty.setEnabled(write == "replace")
        self._press_empty.setEnabled(write == "replace" and not use_det)
    @QtCore.Slot()
    def _on_action(self):
        value = self._action_box.currentData()
        if value is None:
            return
        self.action_data.overlay_action = str(value)
        if self.action_data.overlay_action == "interactive":
            self.action_data.target_kind = "page"
        self._update_visibility()

    @QtCore.Slot()
    def _on_mode(self):
        mode = self._mode_box.currentData()
        if mode is None:
            return
        self.action_data.button_mode = mode
        self._update_visibility()

    @QtCore.Slot(object)
    def _on_pulse(self, value):
        try:
            self.action_data.pulse_delay = max(1, int(value))
        except (TypeError, ValueError):
            self.action_data.pulse_delay = 250

    @QtCore.Slot(bool)
    def _on_kind(self, checked: bool):
        if not checked:
            return
        sender = self.sender()
        kind = str(sender.property("kind") or "page") if sender is not None else "page"
        if self.action_data.overlay_action != "visibility":
            return
        if self.action_data.target_kind != kind:
            self.action_data.target_kind = kind
            self.action_data.selected_ids = []
        self._picker.set_kind(kind, list(self.action_data.selected_ids or []))
        self._update_visibility()

    @QtCore.Slot(list)
    def _on_selection(self, ids: list):
        self.action_data.selected_ids = [str(i) for i in (ids or []) if str(i or "").strip()]

    @QtCore.Slot(bool)
    def _on_bypass(self, checked: bool):
        self.action_data.bypass_parent = bool(checked)

    @QtCore.Slot()
    def _on_variable(self):
        self.action_data.variable_name = str(self._variable_combo.currentData() or "")

    @QtCore.Slot()
    def _on_write_mode(self):
        value = self._write_mode_box.currentData()
        if value is None:
            return
        self.action_data.variable_write = str(value)
        self._update_visibility()

    @QtCore.Slot(bool)
    def _on_use_detection(self, checked: bool):
        self.action_data.use_detection_label = bool(checked)
        self._update_visibility()

    @QtCore.Slot()
    def _on_press_value(self):
        self.action_data.press_value = self._press_value.text()

    @QtCore.Slot()
    def _on_release_value(self):
        self.action_data.release_value = self._release_value.text()

    @QtCore.Slot(bool)
    def _on_press_empty(self, checked: bool):
        self.action_data.press_empty = bool(checked)
        self._press_value.setEnabled(not checked)
        self._update_visibility()

    @QtCore.Slot(bool)
    def _on_release_empty(self, checked: bool):
        self.action_data.release_empty = bool(checked)
        self._release_value.setEnabled(not checked)
        self._update_visibility()

    @QtCore.Slot()
    def _on_image_widget_name(self):
        self.action_data.image_widget_name = str(self._image_widget_name.text() or "").strip()

    @QtCore.Slot()
    def _on_chart_url(self):
        self.action_data.chart_url = str(self._chart_url.text() or "").strip()

    @QtCore.Slot()
    def _on_page_url(self):
        self.action_data.page_url = str(self._page_url.text() or "").strip()

    @QtCore.Slot()
    def _on_chart_id(self):
        self.action_data.chart_id = str(self._chart_id.text() or "").strip()


# ---------------------------------------------------------------------------
# Functor / apply helpers
# ---------------------------------------------------------------------------

# Runtime contribution map for Contribute mode: (variable_id, contributor_key) -> value
_variable_contributions: dict[tuple[str, str], str] = {}


def _set_overlay_variable_value(name: str, value: str):
    scene = _overlay_scene()
    if scene is None:
        syslog.warning("OBS OVERLAY VAR: set %%%s%% SKIP — no overlay scene", name)
        return
    from gremlin.ui.obs_overlay.model import overlay_variable_name

    cleaned = overlay_variable_name(name)
    if not cleaned:
        syslog.warning("OBS OVERLAY VAR: set SKIP — empty variable name (raw=%r)", name)
        return
    # Runtime path: no undo stack, no scene.changed (that rebuilt the whole overlay).
    changed = False
    try:
        changed = bool(
            scene.set_overlay_variable_runtime_value(
                cleaned, str(value if value is not None else "")
            )
        )
    except Exception as err:
        syslog.warning("OBS OVERLAY VAR: set %%%s%% FAILED: %s", cleaned, err)
        changed = False
    if not changed:
        row = scene.overlay_variable_by_name(cleaned)
        cur = "" if row is None else str(row.get("value") if row.get("value") is not None else "")
        syslog.info(
            "OBS OVERLAY VAR: set %%%s%% unchanged (already %r) — no label refresh",
            cleaned,
            cur,
        )
        return
    syslog.info("OBS OVERLAY VAR: set %%%s%% = %r", cleaned, value)
    try:
        from gremlin.ui.obs_overlay.bindings import OverlayValueBus

        # Poll once; widgets whose labels resolve %var% fingerprint the new text
        # and only those ids are dirtied (no emit_all full-frame flash).
        OverlayValueBus().refresh()
        syslog.info("OBS OVERLAY VAR: value bus refresh after %%%s%%", cleaned)
    except Exception as err:
        syslog.warning("OBS OVERLAY VAR: value bus refresh failed: %s", err)


def _rebuild_contributed_value(variable_id: str) -> str:
    parts = []
    for (vid, _key), val in _variable_contributions.items():
        if vid == variable_id and str(val or "").strip():
            parts.append(str(val).strip())
    # Preserve insertion order, unique by casefold
    out = []
    seen = set()
    for part in parts:
        key = part.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(part)
    return ", ".join(out)


def _apply_citizen_lookup(action_data: "MapToOverlay", is_pressed: bool, event=None):
    from gremlin.ui.obs_overlay.ocr_lookup import citizen_lookup

    extra = getattr(event, "extra_data", None) or {} if event is not None else {}
    if isinstance(extra, dict) and extra.get("ocr_runtime_handled"):
        return
    detection = ""
    if isinstance(extra, dict):
        detection = str(extra.get("ocr_detection_label") or "").strip()
    field_map = extra.get("ocr_field_map") if isinstance(extra, dict) else None
    if is_pressed:
        citizen_lookup().lookup(detection, field_map if isinstance(field_map, dict) else None)
    else:
        citizen_lookup().clear()


def _apply_set_image(action_data: "MapToOverlay", is_pressed: bool, event=None):
    import threading

    try:
        from gremlin.ui.obs_overlay.ocr_images import fetch_chart_to_cache, set_named_image_path_runtime
    except Exception:
        syslog.warning("OBS OVERLAY: SC EFB chart images are not available in this build.")
        return

    extra = getattr(event, "extra_data", None) or {} if event is not None else {}
    if isinstance(extra, dict) and extra.get("ocr_runtime_handled"):
        return
    widget_name = str(
        (extra.get("ocr_image_widget") if isinstance(extra, dict) else None)
        or action_data.image_widget_name
        or "SC EFB Chart"
    ).strip()
    if not is_pressed:
        gremlin.util.InvokeUiMethod(set_named_image_path_runtime, widget_name, "")
        return
    chart_url = str(
        (extra.get("ocr_chart_url") if isinstance(extra, dict) else None) or action_data.chart_url or ""
    )
    page_url = str(
        (extra.get("ocr_page_url") if isinstance(extra, dict) else None) or action_data.page_url or ""
    )
    chart_id = str(
        (extra.get("ocr_chart_id") if isinstance(extra, dict) else None) or action_data.chart_id or ""
    )
    hint = ""
    if isinstance(extra, dict):
        hint = str(extra.get("ocr_detection_label") or "")

    def _fetch():
        path = fetch_chart_to_cache(
            chart_url=chart_url,
            page_url=page_url,
            chart_id=chart_id,
            hint=hint,
        )
        if path:
            gremlin.util.InvokeUiMethod(set_named_image_path_runtime, widget_name, path)

    threading.Thread(target=_fetch, name="GexOverlayChartFetch", daemon=True).start()


def _apply_set_variable(action_data: "MapToOverlay", is_pressed: bool, event=None):
    scene = _overlay_scene()
    if scene is None:
        syslog.warning("OBS OVERLAY VAR: Map to Overlay set_variable — no scene")
        return
    from gremlin.ui.obs_overlay.model import overlay_variable_name

    name = overlay_variable_name(action_data.variable_name)
    if not name:
        syslog.warning(
            "OBS OVERLAY VAR: Map to Overlay set_variable — no variable selected on action"
        )
        return
    row = scene.overlay_variable_by_name(name)
    if row is None:
        row = scene.add_overlay_variable(name)
    if row is None:
        syslog.warning("OBS OVERLAY VAR: could not create variable %%%s%%", name)
        return
    variable_id = str(row.get("id") or "")
    write = str(action_data.variable_write or "replace").casefold()

    detection = ""
    if event is not None:
        extra = getattr(event, "extra_data", None) or {}
        if isinstance(extra, dict):
            detection = str(extra.get("ocr_detection_label") or "").strip()

    syslog.info(
        "OBS OVERLAY VAR: action write=%s pressed=%s var=%%%s%% use_detection=%s detection=%r",
        write,
        is_pressed,
        name,
        bool(action_data.use_detection_label),
        detection,
    )

    if write == "contribute":
        # Contributor key: prefer overlay input message_key so OCR rules are stable.
        contributor = ""
        if event is not None:
            ident = getattr(event, "identifier", None)
            contributor = str(getattr(ident, "message_key", "") or getattr(ident, "widget_id", "") or "")
        if not contributor:
            contributor = str(getattr(action_data, "id", None) or id(action_data))
        key = (variable_id, contributor)
        if is_pressed:
            value = detection if action_data.use_detection_label and detection else str(action_data.press_value or "")
            if value.strip():
                _variable_contributions[key] = value.strip()
            else:
                _variable_contributions.pop(key, None)
                syslog.warning(
                    "OBS OVERLAY VAR: contribute press with empty value "
                    "(use_detection=%s detection=%r press_value=%r) — contribution cleared",
                    bool(action_data.use_detection_label),
                    detection,
                    action_data.press_value,
                )
        else:
            _variable_contributions.pop(key, None)
        joined = _rebuild_contributed_value(variable_id)
        syslog.info(
            "OBS OVERLAY VAR: contribute key=%s joined=%r",
            contributor,
            joined,
        )
        gremlin.util.InvokeUiMethod(_set_overlay_variable_value, name, joined)
        return

    # Replace mode
    if is_pressed:
        if action_data.press_empty:
            value = ""
        elif action_data.use_detection_label and detection:
            value = detection
        else:
            value = str(action_data.press_value or "")
    else:
        if action_data.release_empty:
            value = ""
        else:
            value = str(action_data.release_value or "")
    syslog.info("OBS OVERLAY VAR: replace %%%s%% → %r", name, value)
    gremlin.util.InvokeUiMethod(_set_overlay_variable_value, name, value)


def _set_control_panel_visible(visible: bool):
    from gremlin.ui.obs_overlay.control_panel import (
        open_overlay_control_panel,
        overlay_control_panel_is_open,
    )
    import gremlin.ui.obs_overlay.control_panel as panel_mod

    if visible:
        open_overlay_control_panel()
        return
    if overlay_control_panel_is_open() and panel_mod._panel is not None:
        try:
            panel_mod._panel.hide()
        except RuntimeError:
            pass
        try:
            panel_mod._sync_toolbar_overlay_control_checked(False)
        except Exception:
            pass


def _page_is_shown(manager, page_id: str) -> bool:
    try:
        return bool(manager.page_is_visible(page_id))
    except Exception:
        return False


def _ensure_pages_shown(manager, page_ids: set[str] | list[str]):
    ids = [pid for pid in page_ids if pid]
    if not ids:
        return
    need = [pid for pid in ids if not _page_is_shown(manager, pid)]
    if need:
        manager.show_overlay(auto=True, page_ids=need)


def _apply_visibility_ui(show: bool, kind: str, selected_ids: list, bypass: bool):
    scene = _overlay_scene()
    manager = _overlay_manager()
    if scene is None or manager is None:
        return
    kind = (kind or "page").casefold()
    ids = [str(i) for i in (selected_ids or []) if str(i or "").strip()]
    if not ids:
        return

    if kind == "page":
        for pid in ids:
            if not scene.page_by_id(pid):
                continue
            scene.set_page_visible(bool(show), page_id=pid)
            if show:
                manager.show_overlay(auto=True, page_ids=[pid])
            else:
                manager.hide_overlay_page(pid)
        return

    if kind == "group":
        widget_ids: list[str] = []
        page_ids: set[str] = set()
        for gid in ids:
            members, pages = _group_members(scene, gid)
            widget_ids.extend(members)
            page_ids |= pages
        if show and bypass:
            _ensure_pages_shown(manager, page_ids)
        if widget_ids:
            scene.set_widgets_visible(widget_ids, bool(show))
        return

    widget_ids = []
    page_ids = set()
    for wid in ids:
        page, item = _find_widget(scene, wid)
        if item is None:
            continue
        widget_ids.append(wid)
        if page is not None and page.get("id"):
            page_ids.add(str(page["id"]))
    if show and bypass:
        _ensure_pages_shown(manager, page_ids)
    if widget_ids:
        scene.set_widgets_visible(widget_ids, bool(show))


def _apply_visibility(show: bool, *, kind: str, selected_ids: list[str], bypass: bool):
    gremlin.util.InvokeUiMethod(
        _apply_visibility_ui,
        bool(show),
        kind,
        list(selected_ids or []),
        bool(bypass),
    )


def _toggle_visibility_ui(kind: str, selected_ids: list, bypass: bool):
    scene = _overlay_scene()
    manager = _overlay_manager()
    if scene is None or manager is None:
        return
    kind = (kind or "page").casefold()
    ids = [str(i) for i in (selected_ids or []) if str(i or "").strip()]
    if not ids:
        return

    if kind == "page":
        for pid in ids:
            if not scene.page_by_id(pid):
                continue
            currently = _page_is_shown(manager, pid)
            _apply_visibility_ui(not currently, "page", [pid], False)
        return
    if kind == "group":
        for gid in ids:
            members, _pages = _group_members(scene, gid)
            if not members:
                continue
            any_visible = False
            for wid in members:
                _page, item = _find_widget(scene, wid)
                if item is not None and bool(item.get("visible", True)):
                    any_visible = True
                    break
            _apply_visibility_ui(not any_visible, "group", [gid], bypass)
        return
    for wid in ids:
        _page, item = _find_widget(scene, wid)
        if item is None:
            continue
        currently = bool(item.get("visible", True))
        _apply_visibility_ui(not currently, "widget", [wid], bypass)


def _toggle_visibility(*, kind: str, selected_ids: list[str], bypass: bool):
    gremlin.util.InvokeUiMethod(
        _toggle_visibility_ui,
        kind,
        list(selected_ids or []),
        bool(bypass),
    )


def _apply_interactive_ui(enabled: bool, selected_ids: list):
    scene = _overlay_scene()
    if scene is None:
        return
    ids = [str(i) for i in (selected_ids or []) if str(i or "").strip()]
    pages = []
    if ids:
        for pid in ids:
            page = scene.page_by_id(pid)
            if page is not None:
                pages.append(page)
    else:
        pages = list(scene.pages or [])
    changed = False
    for page in pages:
        canvas = page.get("canvas") if isinstance(page.get("canvas"), dict) else None
        if canvas is None:
            continue
        if bool(canvas.get("interactive")) == bool(enabled):
            continue
        canvas["interactive"] = bool(enabled)
        changed = True
    if changed:
        scene._dirty = True
        scene.changed.emit()


def _apply_interactive(enabled: bool, selected_ids: list[str] | None):
    gremlin.util.InvokeUiMethod(_apply_interactive_ui, bool(enabled), list(selected_ids or []))


def _toggle_interactive_ui(selected_ids: list):
    scene = _overlay_scene()
    if scene is None:
        return
    ids = [str(i) for i in (selected_ids or []) if str(i or "").strip()]
    pages = []
    if ids:
        for pid in ids:
            page = scene.page_by_id(pid)
            if page is not None:
                pages.append(page)
    else:
        pages = list(scene.pages or [])
    any_on = any(bool((p.get("canvas") or {}).get("interactive")) for p in pages)
    _apply_interactive_ui(not any_on, selected_ids)


def _toggle_interactive(selected_ids: list[str] | None):
    gremlin.util.InvokeUiMethod(_toggle_interactive_ui, list(selected_ids or []))


def _apply_control_panel(show: bool):
    gremlin.util.InvokeUiMethod(_set_control_panel_visible, bool(show))


def _toggle_control_panel():
    from gremlin.ui.obs_overlay.control_panel import overlay_control_panel_is_open

    gremlin.util.InvokeUiMethod(_set_control_panel_visible, not overlay_control_panel_is_open())


class MapToOverlayFunctor(gremlin.base_profile.AbstractFunctor):
    """Runtime handler for Map to Overlay."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent)
        self.action_data: MapToOverlay = action_data
        self._pulse_worker: PulseWorker | None = None
        self._var_latched = False
        self._last_event = None

    def profile_stop(self):
        self._stop_pulse()
        if self.action_data.overlay_action == "set_variable" and self._var_latched:
            self._activate(False, event=None)
            self._var_latched = False

    def _stop_pulse(self):
        worker = self._pulse_worker
        self._pulse_worker = None
        if worker is not None:
            try:
                worker.stop()
            except Exception:
                pass

    def _activate(self, show: bool, event=None):
        data = self.action_data
        action = data.overlay_action
        if action == "set_variable":
            _apply_set_variable(data, bool(show), event=event)
            return
        if action == "citizen_lookup":
            _apply_citizen_lookup(data, bool(show), event=event)
            return
        if action == "set_image":
            _apply_set_image(data, bool(show), event=event)
            return
        if action == "visibility":
            _apply_visibility(
                show,
                kind=data.target_kind,
                selected_ids=list(data.selected_ids or []),
                bypass=bool(data.bypass_parent),
            )
        elif action == "interactive":
            _apply_interactive(show, list(data.selected_ids or []))
        elif action == "control_panel":
            _apply_control_panel(show)

    def _toggle(self, event=None):
        data = self.action_data
        action = data.overlay_action
        if action in ("set_variable", "set_image", "citizen_lookup"):
            self._var_latched = not self._var_latched
            self._activate(self._var_latched, event=event)
            return
        if action == "visibility":
            _toggle_visibility(
                kind=data.target_kind,
                selected_ids=list(data.selected_ids or []),
                bypass=bool(data.bypass_parent),
            )
        elif action == "interactive":
            _toggle_interactive(list(data.selected_ids or []))
        elif action == "control_panel":
            _toggle_control_panel()

    def _pulse_on(self, _data=None):
        self._activate(True, event=self._last_event)

    def _pulse_off(self, _data=None):
        self._activate(False, event=self._last_event)

    def _start_pulse(self):
        self._stop_pulse()
        delay = max(1, int(self.action_data.pulse_delay or 250)) / 1000.0
        worker = PulseWorker(delay, -1, self._pulse_on, self._pulse_off)
        self._pulse_worker = worker
        worker.start()

    def process_event(self, event, value, extra_data=None):
        is_pressed = bool(getattr(value, "is_pressed", getattr(event, "is_pressed", False)))
        self._last_event = event
        mode = self.action_data.button_mode

        if mode == VjoyAction.VJoyButton:
            # Hold: pressed → write / contribute; released → clear / release value.
            self._activate(is_pressed, event=event)
            return True
        if mode == VjoyAction.VJoyButtonInverted:
            self._activate(not is_pressed, event=event)
            return True
        if mode == VjoyAction.VJoyButtonPress:
            if is_pressed:
                self._activate(True, event=event)
            return True
        if mode == VjoyAction.VJoyButtonRelease:
            if not is_pressed:
                self._activate(False, event=event)
            return True
        if mode == VjoyAction.VJoyPulse:
            if is_pressed:
                self._start_pulse()
            else:
                self._stop_pulse()
                self._activate(False, event=event)
            return True
        if mode == VjoyAction.VJoyToggle:
            if is_pressed:
                self._toggle(event=event)
            return True
        return True


# ---------------------------------------------------------------------------
# Action data
# ---------------------------------------------------------------------------


class MapToOverlay(gremlin.input_item.AbstractAction):
    """Profile action: map an input to overlay visibility / variables / control panel."""

    name = "Map to Overlay"
    tag = "map_to_overlay"
    hint = "Show or hide overlay pages/groups/widgets; set overlay variables; toggle interactive mode; or the runtime control panel."

    default_button_activation = (True, True)

    functor = MapToOverlayFunctor
    widget = MapToOverlayWidget

    input_types = [
        InputType.JoystickButton,
        InputType.OverlayButton,
        InputType.Keyboard,
        InputType.KeyboardLatched,
    ]

    def __init__(self, parent, extra_data: dict = None):
        super().__init__(parent, extra_data=extra_data)
        self.parent = parent
        self.overlay_action = "visibility"
        self.target_kind = "page"
        self.selected_ids: list[str] = []
        self.bypass_parent = False
        self.button_mode = VjoyAction.VJoyButton
        self.pulse_delay = 250
        self.variable_name = ""
        self.variable_write = "replace"
        self.use_detection_label = False
        self.press_value = ""
        self.release_value = ""
        self.press_empty = False
        self.release_empty = True
        self.image_widget_name = "SC EFB Chart"
        self.chart_url = ""
        self.page_url = ""
        self.chart_id = ""

    def icon(self):
        return "mdi.monitor-dashboard"

    def requires_virtual_button(self):
        return False

    def display_name(self):
        label = dict(OVERLAY_ACTIONS).get(self.overlay_action, self.overlay_action)
        mode = VjoyAction.to_name(self.button_mode)
        if self.overlay_action == "set_variable":
            write = str(self.variable_write or "replace")
            var = f"%{self.variable_name}%" if self.variable_name else "(none)"
            return f"{label} · {write} · {var} · {mode}"
        if self.overlay_action == "set_image":
            return f"{label} · {self.image_widget_name or 'SC EFB Chart'} · {mode}"
        if self.overlay_action == "citizen_lookup":
            return f"{label} · {mode}"
        n = len(self.selected_ids or [])
        if self.overlay_action == "control_panel":
            return f"{label} · {mode}"
        return f"{label} · {self.target_kind}×{n} · {mode}"

    def _parse_xml(self, node, data=None, extra_data=None):
        action = safe_read(node, "overlay-action", str, "visibility").casefold()
        if action not in (
            "visibility",
            "interactive",
            "control_panel",
            "set_variable",
            "set_image",
            "citizen_lookup",
        ):
            action = "visibility"
        self.overlay_action = action

        kind = safe_read(node, "target-kind", str, "page").casefold()
        if kind not in ("page", "group", "widget"):
            kind = "page"
        self.target_kind = kind

        self.bypass_parent = safe_read(node, "bypass-parent", bool, False)
        self.pulse_delay = safe_read(node, "pulse-delay", int, 250)
        self.variable_name = safe_read(node, "variable-name", str, "")
        write = safe_read(node, "variable-write", str, "replace").casefold()
        self.variable_write = write if write in ("replace", "contribute") else "replace"
        self.use_detection_label = safe_read(node, "use-detection-label", bool, False)
        self.press_value = safe_read(node, "press-value", str, "")
        self.release_value = safe_read(node, "release-value", str, "")
        self.press_empty = safe_read(node, "press-empty", bool, False)
        self.release_empty = safe_read(node, "release-empty", bool, True)
        self.image_widget_name = safe_read(node, "image-widget-name", str, "SC EFB Chart")
        self.chart_url = safe_read(node, "chart-url", str, "")
        self.page_url = safe_read(node, "page-url", str, "")
        self.chart_id = safe_read(node, "chart-id", str, "")

        mode_name = safe_read(node, "button-mode", str, VjoyAction.VJoyButton.name)
        mode = None
        try:
            mode = VjoyAction.from_string(mode_name)
        except Exception:
            mode = None
        if mode not in BUTTON_MODES:
            mode = VjoyAction.VJoyButton
        self.button_mode = mode

        ids = []
        for child in node:
            if child.tag != "target":
                continue
            tid = safe_read(child, "id", str, "")
            if tid:
                ids.append(tid)
        self.selected_ids = ids
        if self.overlay_action == "interactive":
            self.target_kind = "page"

    def _generate_xml(self):
        node = ElementTree.Element(MapToOverlay.tag)
        node.set("overlay-action", safe_format(self.overlay_action, str))
        node.set("target-kind", safe_format(self.target_kind, str))
        node.set("bypass-parent", safe_format(bool(self.bypass_parent), bool))
        node.set("button-mode", safe_format(self.button_mode.name, str))
        node.set("pulse-delay", safe_format(int(self.pulse_delay or 250), int))
        node.set("variable-name", safe_format(str(self.variable_name or ""), str))
        node.set("variable-write", safe_format(str(self.variable_write or "replace"), str))
        node.set("use-detection-label", safe_format(bool(self.use_detection_label), bool))
        node.set("press-value", safe_format(str(self.press_value or ""), str))
        node.set("release-value", safe_format(str(self.release_value or ""), str))
        node.set("press-empty", safe_format(bool(self.press_empty), bool))
        node.set("release-empty", safe_format(bool(self.release_empty), bool))
        node.set("image-widget-name", safe_format(str(self.image_widget_name or ""), str))
        node.set("chart-url", safe_format(str(self.chart_url or ""), str))
        node.set("page-url", safe_format(str(self.page_url or ""), str))
        node.set("chart-id", safe_format(str(self.chart_id or ""), str))
        for tid in self.selected_ids or []:
            child = ElementTree.SubElement(node, "target")
            child.set("id", safe_format(str(tid), str))
        return node

    def _is_valid(self):
        if self.overlay_action == "control_panel":
            return True
        if self.overlay_action == "set_variable":
            return bool(str(self.variable_name or "").strip())
        if self.overlay_action == "set_image":
            return bool(str(self.image_widget_name or "").strip())
        if self.overlay_action == "citizen_lookup":
            return True
        return True

    def to_html(self) -> str:
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)
        table.addField("Action", dict(OVERLAY_ACTIONS).get(self.overlay_action, self.overlay_action))
        table.addField("Mode", VjoyAction.to_name(self.button_mode))
        if self.overlay_action == "set_variable":
            table.addField("Variable", f"%{self.variable_name}%" if self.variable_name else "(none)")
            table.addField("Write", str(self.variable_write or "replace"))
            table.addField("Detection label", "Yes" if self.use_detection_label else "No")
        elif self.overlay_action == "set_image":
            table.addField("Image widget", str(self.image_widget_name or "SC EFB Chart"))
            if self.chart_url:
                table.addField("Chart URL", str(self.chart_url))
            if self.page_url:
                table.addField("Page URL", str(self.page_url))
        elif self.overlay_action == "citizen_lookup":
            table.addField("Lookup", "RSI citizen dossier")
        else:
            if self.overlay_action != "control_panel":
                table.addField("Target", self.target_kind)
                table.addField("Selected", str(len(self.selected_ids or [])))
            if self.overlay_action == "visibility":
                table.addField("Bypass", "Yes" if self.bypass_parent else "No")
        if self.button_mode == VjoyAction.VJoyPulse:
            table.addField("Pulse", f"{self.pulse_delay} ms")
        return table.to_html()


version = 1
name = "map_to_overlay"
create = MapToOverlay
