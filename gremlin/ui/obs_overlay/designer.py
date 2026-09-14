# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import math
import os

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

import gremlin.event_handler
import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.util
from gremlin.ui.ui_common import Color, QTabHeader

from .images import (
    apply_image_to_item,
    clipboard_has_image,
    import_image_file,
    local_image_path_from_mime,
    qimage_from_clipboard,
    qimage_from_mime,
    save_qimage,
)
from .inspector import OverlayInspector
from .model import DEFAULT_SIZES, PALETTE_GROUPS, OverlayScene, is_interactive_overlay, overlay_path_for_profile, profile_display_name, profile_xml_path
from .overlay_window import OverlayView, ROTATE_HANDLE
from .qt_guard import alive, on_ui
from .widgets import (
    apply_widget_rotation,
    normalize_rotation,
    scene_to_widget_local,
    widget_center,
    widget_local_to_scene,
    widget_rotation_deg,
)
from .shapes import (
    _abs_point,
    _handle_point,
    _has_handles,
    button_uses_shape_path,
    closest_segment,
    default_shape_points,
    expand_shape_widget_to_controls,
    ensure_shape_points,
    insert_shape_point,
    is_shape_widget,
    normalize_shape_kind,
    remove_shape_point,
    save_custom_shape,
    scene_to_normalized,
    snapshot_shape_points,
    snap_handle_offset,
    uses_bezier_edit,
    uses_editable_points,
)
from .templates import (
    TEMPLATES,
    delete_user_template,
    list_user_templates,
    save_user_template,
    update_user_template,
)


WIDGET_TITLES = {
    "axis_bar": "Bar",
    "axis_radio": "Radio",
    "axis_fader": "Fader",
    "axis_radial": "Radial",
    "axis_encoder": "Encoder",
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
    "streamdeck": "Stream Deck",
}

_BANNER_SETTINGS = ("Joystick Gremlin Ex", "Overlay")
_BANNER_PREF_KEY = "show_action_banner"

_COMMON_WIDGET_MOUSE = (
    "Drag to move (snaps to grid and guides). Drag corner/edge handles to resize; hold Shift to keep aspect ratio. "
    "Drag the round handle above the widget to rotate; hold Shift to snap to 15°. "
    "Shift+click adds to the selection. Right-click: Duplicate, Delete, Bring forward, Send backward, Group, Ungroup."
)
_COMMON_WIDGET_KEYS = (
    "Delete removes. Ctrl+D duplicates. Ctrl+V pastes a screenshot from the clipboard as an Image. "
    "Arrow keys nudge (Shift = larger step). Ctrl+Z / Ctrl+Y undo/redo. "
    "Ctrl+G groups (two or more). Ctrl+Shift+G ungroups. Ctrl+A selects all. Ctrl+wheel zooms. Ctrl+0 resets zoom."
)
_COMMON_WIDGET_PALETTE = "With this widget selected, a palette click changes its type and keeps compatible settings."


def _banner_pref_visible() -> bool:
    return QtCore.QSettings(*_BANNER_SETTINGS).value(_BANNER_PREF_KEY, True, type=bool)


def _set_banner_pref_visible(visible: bool):
    QtCore.QSettings(*_BANNER_SETTINGS).setValue(_BANNER_PREF_KEY, bool(visible))


def _banner_type_help(item: dict) -> list[str]:
    """Inspector and mouse extras that apply only to this widget type."""
    widget_type = item.get("type")
    lines: list[str] = []
    if widget_type == "label":
        lines.append(
            "Inspector: type the caption, or check Show current mode to follow the active profile mode live. "
            "Fill, border, and font are in Label."
        )
    elif is_shape_widget(item):
        lines.append("Inspector: pick Rectangle, Circle, Triangle, Diamond, Line, Freeform, or a saved custom shape. Uncheck Closed for an open path.")
        if uses_editable_points(item):
            if uses_bezier_edit(item):
                lines.append(
                    "Mouse: double-click the outline to add a point, then drag points to move them. "
                    "Yellow handles are Bézier controls — drag them to curve a corner. "
                    "Hold Ctrl to snap a handle to 15° steps. Hold Alt and drag a handle to move it independently. "
                    "Dragging a handle past the widget edge grows the shape. "
                    "Delete removes the selected point. Right-click Add point / Delete point."
                )
            else:
                lines.append(
                    "Mouse: double-click the outline to add a point. Drag points to reshape. "
                    "Delete removes the selected point. Right-click Add point / Delete point."
                )
        else:
            lines.append("Mouse: resize from the handles. Switch to Freeform, Line, Triangle, or Diamond to edit points on the canvas.")
        lines.append(
            "Right-click: Turn into button to bind the same outline. Save as custom shape to add it to the Shape list."
        )
    elif button_uses_shape_path(item):
        lines.append(
            "This button uses a shape outline. Off/On fill follow press. Bind it like any button. "
            "Right-click: Turn into shape, or Save as custom shape."
        )
    elif widget_type == "image":
        lines.append(
            "Inspector: browse to a PNG, WebP, GIF, JPEG, or BMP, or Paste a screenshot from the clipboard "
            "(Windows Snipping Tool / Win+Shift+S). Ctrl+V on the canvas does the same. Formats with alpha keep transparency. "
            "Keep aspect ratio is on by default."
        )
    elif widget_type == "streamdeck":
        lines.append("Inspector: pick the deck (or First connected), follow the GEX page or set a page, Show bezel, Fit to device. No joystick binding.")
    elif widget_type == "axis_graph":
        lines.append("Inspector: Datasets add/remove physical or vJoy axes (Listen…). Period, Min/Max, and Unit set the time plot. No single binding.")
    elif widget_type == "axis_bars":
        lines.append(
            "Inspector: Orientation (vertical/horizontal). Datasets are the bars — color and Range per axis "
            "(Auto, Centered −100…+100, or 0…100%). Auto range uses negatives only when a centered axis is selected."
        )
    elif widget_type == "sys_stats":
        lines.append(
            "Inspector: Datasets add one or more readings (time, FPS, CPU, GPU, RAM, manual tally), each with its own color. "
            "FPS is in-game via RTSS/Afterburner. Manual: bind Increment, Decrement, and optional Reset."
        )
    elif widget_type == "stopwatch":
        lines.append(
            "Inspector: Digital or Analog, mm:ss or hh:mm:ss. Bind Start / stop (press toggles; a state or mode follows on/off). "
            "Optional Reset binding. Analog: color, width, and arrow for hour, minute, and second needles."
        )
    elif widget_type == "input_display":
        lines.append(
            "Inspector: pick a preset (WASD + mouse, full keyboard, mouse only) or Select keys… on the virtual keyboard. "
            "Select all / Deselect all. Off/On fill, mouse Silhouette or Button map. Live presses light the selected keys and mouse buttons."
        )
    elif widget_type == "axis_mouse":
        lines.append("Inspector: VJoy (arrow from rest) or Standard (mouse icon). Max displacement and idle recenter apply to Standard.")
    elif widget_type == "button":
        lines.append("Inspector: shape, off/on fill. Binding is a physical, vJoy, state, mode, or keyboard/mouse button (Listen or Select…).")
    elif widget_type == "hat":
        lines.append("Inspector: 4- or 8-position, axis labels. Binding is a hat. Drag on an Interactive overlay if bound to vJoy.")
    elif widget_type == "switch_4way":
        lines.append(
            "Inspector: bind North, East, South, West, and optional Center as separate buttons. "
            "For hats that report as five buttons rather than a POV hat. Interactive overlay springs back to center."
        )
    elif widget_type == "switch_2way":
        lines.append(
            "Inspector: bind Position 1 and Position 2. Orientation flips vertical/horizontal. "
            "Interactive overlay latches the last side you press."
        )
    elif widget_type == "switch_3way":
        lines.append(
            "Inspector: bind Up, Center, and Down. Center is optional when neither end is pressed. "
            "Interactive overlay springs back to center on lift."
        )
    elif widget_type in ("axis_stick_square", "axis_stick_circle", "axis_crosshair"):
        lines.append("Inspector: Axis X and Axis Y are independent (mix devices). Dot, grid, and crosshair options. Drag on an Interactive overlay if bound to vJoy.")
    elif widget_type in ("axis_bar", "axis_radio", "axis_fader"):
        lines.append("Inspector: Orientation, binding (Listen…). Drag on an Interactive overlay if bound to vJoy.")
    elif widget_type in ("axis_radial", "axis_encoder", "axis_dial"):
        lines.append("Inspector: ticks/arc, binding (Listen…). Drag on an Interactive overlay if bound to vJoy.")
    elif widget_type:
        lines.append("Inspector: size, visibility, appearance, and binding for this widget.")
    return lines


def action_banner_content(scene: OverlayScene) -> tuple[str, str]:
    """Title and HTML body for the designer action banner."""
    items = scene.selected_widgets()
    if not items:
        page = scene.page_by_id(scene.active_page_id) or {}
        name = str(page.get("name") or "Overlay")
        title = f"Canvas — {name}"
        body = (
            "<b>Mouse</b> — Click empty space to deselect. Drag empty space for a rubber-band (Shift adds). "
            "Drag a guide to move it. Ctrl+wheel zooms the designer (does not change overlay resolution).<br>"
            "<b>Keys</b> — Ctrl+A select all. Ctrl+V paste a screenshot as an Image. Ctrl+Z / Ctrl+Y undo/redo. Ctrl+0 reset zoom. Ctrl++ / Ctrl+− zoom.<br>"
            "<b>Pages</b> — Double-click a tab to rename. Right-click a tab to duplicate or delete. + adds a page. "
            "Show overlay and Interactive apply to the selected page.<br>"
            "<b>Palette</b> — Click a type to add it at the center of the current view. Templates add a ready layout.<br>"
            "<b>Inspector</b> — Background (chroma / image / on-screen), Visible, Interactive, Toggle overlay, "
            "Show at profile start, Guides, and canvas size."
        )
        return title, body

    grouped = any(str(item.get("group") or "").strip() for item in items)
    types = {item.get("type") for item in items}
    if len(items) == 1:
        item = items[0]
        kind = WIDGET_TITLES.get(item.get("type"), str(item.get("type") or "Widget").replace("_", " "))
        title = f"{kind} selected"
        extras = _banner_type_help(item)
        extra_html = "".join(f"<br><b>This widget</b> — {line}" for line in extras)
        body = (
            f"<b>Mouse</b> — {_COMMON_WIDGET_MOUSE}<br>"
            f"<b>Keys</b> — {_COMMON_WIDGET_KEYS}<br>"
            f"<b>Palette</b> — {_COMMON_WIDGET_PALETTE}"
            f"{extra_html}"
        )
        return title, body

    type_names = ", ".join(sorted(WIDGET_TITLES.get(t, str(t or "").replace("_", " ")) for t in types))
    title = f"{len(items)} widgets selected"
    if grouped:
        title += " (grouped)"
    extra = ""
    if len(types) == 1:
        extra = "".join(f"<br><b>This type</b> — {line}" for line in _banner_type_help(items[0]))
    body = (
        f"<b>Mouse</b> — Drag moves every selected widget. Drag the dashed bounding-box handles to resize them together "
        f"(Shift keeps aspect). {_COMMON_WIDGET_MOUSE}<br>"
        f"<b>Keys</b> — {_COMMON_WIDGET_KEYS}<br>"
        f"<b>Palette</b> — A palette click converts every selected widget to that type when settings are compatible.<br>"
        f"<b>Inspector</b> — Shared properties only; edits apply to all selected widgets. Types: {type_names}."
        f"{extra}"
    )
    return title, body


class ActionBanner(QtWidgets.QFrame):
    """Context help at the top of the designer canvas column."""

    hide_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("overlayActionBanner")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 6, 6)
        layout.setSpacing(8)
        col = QtWidgets.QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self._title = QtWidgets.QLabel()
        self._title.setStyleSheet("font-weight: bold;")
        self._body = QtWidgets.QLabel()
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        col.addWidget(self._title)
        col.addWidget(self._body)
        layout.addLayout(col, 1)
        close = QtWidgets.QToolButton()
        close.setText("×")
        close.setAutoRaise(True)
        close.setToolTip("Hide this banner. Use Hints on the toolbar to show it again.")
        close.setFixedSize(22, 22)
        close.clicked.connect(self.hide_requested.emit)
        layout.addWidget(close, 0, QtCore.Qt.AlignTop)
        self._apply_style()

    def _apply_style(self):
        bg = Color.backgroundLighterColor()
        fg = Color.normalColor()
        border = Color.normalGradientColor()
        self.setStyleSheet(
            f"#overlayActionBanner {{ background: {bg}; border: 1px solid {border}; border-radius: 6px; }}"
            f"#overlayActionBanner QLabel {{ color: {fg}; background: transparent; }}"
        )

    def set_content(self, title: str, body: str):
        if not alive(self) or not alive(self._title) or not alive(self._body):
            return
        self._title.setText(title)
        self._body.setText(body)


class TemplateButton(QtWidgets.QPushButton):
    """Built-in or saved template. Saved templates can be updated or deleted from a right-click menu."""

    apply_requested = QtCore.Signal()
    update_requested = QtCore.Signal()
    delete_requested = QtCore.Signal()

    def __init__(self, label: str, editable: bool = False, parent=None):
        super().__init__(label, parent)
        self._editable = editable
        self.clicked.connect(lambda _=False: self.apply_requested.emit())
        if editable:
            self.setToolTip("Click to apply. Right-click to update with the current widgets or delete.")
            self.setContextMenuPolicy(QtCore.Qt.DefaultContextMenu)
        else:
            self.setToolTip("Click to add this template to the canvas.")
            self.setContextMenuPolicy(QtCore.Qt.NoContextMenu)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        if not self._editable:
            return
        menu = QtWidgets.QMenu(self)
        update_action = menu.addAction("Update with current widgets")
        update_action.triggered.connect(lambda _=False: self.update_requested.emit())
        delete_action = menu.addAction("Delete template")
        delete_action.triggered.connect(lambda _=False: self.delete_requested.emit())
        menu.exec(event.globalPos())


class DesignerCanvas(OverlayView):
    """Interactive canvas: select, move, resize, rubber-band."""

    def __init__(self, scene: OverlayScene, parent=None):
        super().__init__(scene, interactive=True, parent=parent)
        self._mode = None
        self._handle = -1
        self._guide_id = None
        self._last = QtCore.QPointF()
        self._origin = QtCore.QPointF()
        self._start_geom = {}
        self._start_geoms: dict[str, dict] = {}
        self._start_bounds: dict = {}
        self._shape_vertex = None
        self._shape_handle = None
        self._rotate_center = QtCore.QPointF()
        self._rotate_start_mouse = 0.0
        self._start_rotations: dict[str, float] = {}
        self.setAcceptDrops(True)
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.setContextMenuPolicy(QtCore.Qt.DefaultContextMenu)
        self.scene.selection_changed.connect(self._clear_shape_vertex)
        self.destroyed.connect(self._detach_designer_canvas)

    def _detach_designer_canvas(self, *_args):
        try:
            self.scene.selection_changed.disconnect(self._clear_shape_vertex)
        except Exception:
            pass
        self.detach_from_scene()

    def _clear_shape_vertex(self):
        if self._mode == "shape":
            return
        self._shape_vertex = None
        self._shape_handle = None

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() != QtCore.Qt.LeftButton:
            return
        self.setFocus()
        pos = self.map_to_scene(event.position())
        vertex = self.shape_handle_at(pos)
        if vertex is not None:
            self.scene.push_undo()
            self._mode = "shape"
            self._shape_vertex, self._shape_handle = vertex
            self.update()
            return
        widget_id, handle = self.handle_at(pos)
        if handle == ROTATE_HANDLE:
            self.scene.push_undo()
            self._mode = "rotate"
            self._last = pos
            bounds = self._selected_bounds()
            item = self.scene.widget_by_id(widget_id) or self.scene.primary_selection()
            if len(self.scene.selected_ids) > 1 and bounds is not None:
                self._rotate_center = bounds.center()
            elif item:
                self._rotate_center = widget_center(item)
            else:
                self._rotate_center = pos
            self._rotate_start_mouse = math.degrees(
                math.atan2(pos.y() - self._rotate_center.y(), pos.x() - self._rotate_center.x())
            )
            self._start_rotations = {}
            for sid in self.scene.selected_ids:
                it = self.scene.widget_by_id(sid)
                if it:
                    self._start_rotations[sid] = widget_rotation_deg(it)
            return
        if handle >= 0:
            self.scene.push_undo()
            self._mode = "resize"
            self._handle = handle
            self._last = pos
            self._start_geoms = {}
            for sid in self.scene.selected_ids:
                it = self.scene.widget_by_id(sid)
                if it:
                    self._start_geoms[sid] = {
                        "x": float(it.get("x") or 0),
                        "y": float(it.get("y") or 0),
                        "w": float(it.get("w") or 1),
                        "h": float(it.get("h") or 1),
                    }
            bounds = self._selected_bounds()
            self._start_bounds = (
                {"x": bounds.x(), "y": bounds.y(), "w": bounds.width(), "h": bounds.height()}
                if bounds is not None
                else {}
            )
            item = self.scene.widget_by_id(widget_id) or self.scene.primary_selection()
            self._start_geom = dict(item) if item else {}
            return
        hit = self.scene.hit_test(pos.x(), pos.y())
        if hit:
            additive = bool(event.modifiers() & QtCore.Qt.ShiftModifier)
            group_ids = self.scene.expand_group_ids([hit["id"]])
            if additive:
                self.scene.set_selection(group_ids, additive=True)
                self.scene.set_selection(self.scene.expand_group_ids(self.scene.selected_ids))
            elif hit["id"] not in self.scene.selected_ids:
                self.scene.set_selection(group_ids)
            self.scene.push_undo()
            self._mode = "move"
            self._last = pos
            self.setCursor(QtCore.Qt.SizeAllCursor)
            return
        guide = self.guide_at(pos)
        if guide:
            self.scene.push_undo()
            self._mode = "guide"
            self._guide_id = guide.get("id")
            self.setCursor(QtCore.Qt.SizeVerCursor if guide.get("axis") == "h" else QtCore.Qt.SizeHorCursor)
            return
        if not (event.modifiers() & QtCore.Qt.ShiftModifier):
            self.scene.set_selection([])
        self._mode = "rubber"
        self._origin = pos
        self._rubber = QtCore.QRectF(pos, pos)
        self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        pos = self.map_to_scene(event.position())
        if self._mode == "move":
            dx = pos.x() - self._last.x()
            dy = pos.y() - self._last.y()
            self.scene.move_selected(int(dx), int(dy), snap=True)
            self._last = pos
        elif self._mode == "shape":
            self._drag_shape_handle(pos, event.modifiers())
        elif self._mode == "rotate":
            self._rotate_to(pos, bool(event.modifiers() & QtCore.Qt.ShiftModifier))
        elif self._mode == "resize":
            self._resize_to(pos, bool(event.modifiers() & QtCore.Qt.ShiftModifier))
        elif self._mode == "guide":
            self._drag_guide(pos)
        elif self._mode == "rubber":
            self._rubber = QtCore.QRectF(self._origin, pos)
            self.update()
        else:
            _, handle = self.handle_at(pos)
            if handle == ROTATE_HANDLE:
                self.setCursor(QtCore.Qt.OpenHandCursor)
                return
            if handle >= 0:
                self.setCursor(self._resize_cursor(handle))
                return
            guide = self.guide_at(pos)
            if guide:
                self.setCursor(QtCore.Qt.SizeVerCursor if guide.get("axis") == "h" else QtCore.Qt.SizeHorCursor)
            else:
                self.setCursor(QtCore.Qt.ArrowCursor)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if self._mode == "rubber":
            ids = self.scene.widgets_in_rect(
                self._rubber.x(), self._rubber.y(), self._rubber.width(), self._rubber.height()
            )
            ids = self.scene.expand_group_ids(ids)
            self.scene.set_selection(ids, additive=bool(event.modifiers() & QtCore.Qt.ShiftModifier))
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                self.scene.set_selection(self.scene.expand_group_ids(self.scene.selected_ids))
            self._rubber = QtCore.QRectF()
        self._mode = None
        self._handle = -1
        self._guide_id = None
        self._shape_handle = None
        self._start_rotations = {}
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.update()

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        key = event.key()
        mods = event.modifiers()
        step = 8 if self.scene.canvas.get("snap_to_grid") else 1
        if mods & QtCore.Qt.ShiftModifier:
            step *= 4
        if key == QtCore.Qt.Key_Delete:
            if self._delete_shape_vertex():
                return
            self.scene.remove_selected()
        elif key == QtCore.Qt.Key_D and mods & QtCore.Qt.ControlModifier:
            self.scene.duplicate_selected()
        elif key == QtCore.Qt.Key_G and mods & QtCore.Qt.ControlModifier:
            if mods & QtCore.Qt.ShiftModifier:
                self.scene.ungroup_selected()
            else:
                self.scene.group_selected()
        elif key == QtCore.Qt.Key_A and mods & QtCore.Qt.ControlModifier:
            self.scene.set_selection([w["id"] for w in self.scene.widgets])
        elif key == QtCore.Qt.Key_Z and mods & QtCore.Qt.ControlModifier:
            if mods & QtCore.Qt.ShiftModifier:
                self.scene.redo()
            else:
                self.scene.undo()
        elif key == QtCore.Qt.Key_Y and mods & QtCore.Qt.ControlModifier:
            self.scene.redo()
        elif key == QtCore.Qt.Key_Left:
            self.scene.push_undo()
            self.scene.move_selected(-step, 0)
        elif key == QtCore.Qt.Key_Right:
            self.scene.push_undo()
            self.scene.move_selected(step, 0)
        elif key == QtCore.Qt.Key_Up:
            self.scene.push_undo()
            self.scene.move_selected(0, -step)
        elif key == QtCore.Qt.Key_Down:
            self.scene.push_undo()
            self.scene.move_selected(0, step)
        elif key == QtCore.Qt.Key_0 and mods & QtCore.Qt.ControlModifier:
            self._zoom_at(1.0)
        elif (key in (QtCore.Qt.Key_Plus, QtCore.Qt.Key_Equal)) and mods & QtCore.Qt.ControlModifier:
            self._zoom_at(self.zoom * 1.1)
        elif key == QtCore.Qt.Key_Minus and mods & QtCore.Qt.ControlModifier:
            self._zoom_at(self.zoom / 1.1)
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        pos = self.map_to_scene(event.pos())
        hit = self.scene.hit_test(pos.x(), pos.y())
        if hit and hit["id"] not in self.scene.selected_ids:
            self.scene.set_selection(self.scene.expand_group_ids([hit["id"]]))
        menu = QtWidgets.QMenu(self)
        paste_image = menu.addAction("Paste image")
        paste_image.setEnabled(clipboard_has_image())
        if not self.scene.selected_ids:
            chosen = menu.exec(event.globalPos())
            if chosen is paste_image:
                self.paste_clipboard_image(pos)
            return
        grouped = any(str(item.get("group") or "").strip() for item in self.scene.selected_widgets())
        menu.addSeparator()
        duplicate = menu.addAction("Duplicate")
        delete = menu.addAction("Delete")
        menu.addSeparator()
        forward = menu.addAction("Bring forward")
        backward = menu.addAction("Send backward")
        menu.addSeparator()
        group = menu.addAction("Group")
        group.setEnabled(len(self.scene.selected_ids) >= 2)
        ungroup = menu.addAction("Ungroup")
        ungroup.setEnabled(grouped)
        add_point = None
        delete_point = None
        turn_button = None
        turn_shape = None
        save_custom = None
        item = self.scene.primary_selection()
        if uses_editable_points(item):
            menu.addSeparator()
            add_point = menu.addAction("Add point")
            delete_point = menu.addAction("Delete point")
            delete_point.setEnabled(self._shape_vertex is not None)
        if is_shape_widget(item) or button_uses_shape_path(item):
            menu.addSeparator()
            if is_shape_widget(item):
                turn_button = menu.addAction("Turn into button")
            if button_uses_shape_path(item):
                turn_shape = menu.addAction("Turn into shape")
            save_custom = menu.addAction("Save as custom shape…")
        chosen = menu.exec(event.globalPos())
        if chosen is paste_image:
            self.paste_clipboard_image(pos)
        elif chosen is duplicate:
            self.scene.duplicate_selected()
        elif chosen is delete:
            self.scene.remove_selected()
        elif chosen is forward:
            self.scene.bring_forward()
        elif chosen is backward:
            self.scene.send_backward()
        elif chosen is group:
            self.scene.group_selected()
        elif chosen is ungroup:
            self.scene.ungroup_selected()
        elif chosen is add_point:
            pos = self.map_to_scene(event.pos())
            self.scene.push_undo()
            index, _dist = closest_segment(item, pos)
            self._shape_vertex = insert_shape_point(item, index, pos)
            self.scene._dirty = True
            self.scene.changed.emit()
        elif chosen is delete_point:
            self._delete_shape_vertex()
        elif chosen is turn_button:
            shapes = [w for w in self.scene.selected_widgets() if is_shape_widget(w)]
            self.scene.convert_widgets_to(shapes, "button")
        elif chosen is turn_shape:
            buttons = [w for w in self.scene.selected_widgets() if button_uses_shape_path(w)]
            self.scene.convert_widgets_to(buttons, "shape")
        elif chosen is save_custom:
            self._save_custom_shape(item)

    def wheelEvent(self, event: QtGui.QWheelEvent):
        if event.modifiers() & QtCore.Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                factor = 1.1 if delta > 0 else 1.0 / 1.1
                self._zoom_at(self.zoom * factor, event.position())
                event.accept()
                return
        event.ignore()

    def _zoom_at(self, zoom: float, widget_pos: QtCore.QPointF | None = None):
        scroll = self.parent()
        while scroll is not None and not isinstance(scroll, QtWidgets.QScrollArea):
            scroll = scroll.parent()
        old_zoom = self.zoom
        if widget_pos is None:
            self.set_zoom(zoom)
            return
        scene_pos = QtCore.QPointF(widget_pos.x() / max(old_zoom, 0.01), widget_pos.y() / max(old_zoom, 0.01))
        viewport_pos = None
        if scroll is not None:
            viewport_pos = self.mapTo(scroll.viewport(), widget_pos.toPoint())
        self.set_zoom(zoom)
        if scroll is None or viewport_pos is None:
            return
        new_widget = QtCore.QPoint(int(scene_pos.x() * self.zoom), int(scene_pos.y() * self.zoom))
        scroll.horizontalScrollBar().setValue(new_widget.x() - viewport_pos.x())
        scroll.verticalScrollBar().setValue(new_widget.y() - viewport_pos.y())

    def _resize_cursor(self, handle: int):
        if handle == ROTATE_HANDLE:
            return QtCore.Qt.OpenHandCursor
        mapping = {
            0: QtCore.Qt.SizeFDiagCursor,
            1: QtCore.Qt.SizeVerCursor,
            2: QtCore.Qt.SizeBDiagCursor,
            3: QtCore.Qt.SizeHorCursor,
            4: QtCore.Qt.SizeFDiagCursor,
            5: QtCore.Qt.SizeVerCursor,
            6: QtCore.Qt.SizeBDiagCursor,
            7: QtCore.Qt.SizeHorCursor,
        }
        return mapping.get(handle, QtCore.Qt.ArrowCursor)

    def _rotate_to(self, pos: QtCore.QPointF, snap: bool = False):
        if not self._start_rotations:
            return
        angle = math.degrees(math.atan2(pos.y() - self._rotate_center.y(), pos.x() - self._rotate_center.x()))
        delta = angle - self._rotate_start_mouse
        for widget_id, start in self._start_rotations.items():
            item = self.scene.widget_by_id(widget_id)
            if not item:
                continue
            rotation = start + delta
            if snap:
                rotation = round(rotation / 15.0) * 15.0
            item["rotation"] = normalize_rotation(rotation)
        self.scene._dirty = True
        self.scene.changed.emit()

    def _resize_to(self, pos: QtCore.QPointF, keep_aspect: bool = False):
        if len(self._start_geoms) > 1 and self._start_bounds:
            self._resize_group_to(pos, keep_aspect)
            return
        item = self.scene.primary_selection()
        if not item or not self._start_geom:
            return
        ox = float(self._start_geom["x"])
        oy = float(self._start_geom["y"])
        ow = float(self._start_geom["w"])
        oh = float(self._start_geom["h"])
        resize_pos = pos
        if abs(widget_rotation_deg(item)) >= 0.001:
            resize_pos = scene_to_widget_local(item, pos.x(), pos.y())
        x, y, w, h = self._bounds_from_handle(ox, oy, ow, oh, resize_pos)
        if keep_aspect:
            x, y, w, h = self._lock_aspect(x, y, w, h, ox, oy, ow, oh)
            x, y, w, h = self._snap_locked_geom(x, y, w, h, ox, oy, ow, oh)
            item["x"] = int(round(x))
            item["y"] = int(round(y))
            item["w"] = max(8, int(round(w)))
            item["h"] = max(8, int(round(h)))
        else:
            item["x"] = self.scene.snap_value(x)
            item["y"] = self.scene.snap_value(y)
            item["w"] = max(8, self.scene.snap_value(w))
            item["h"] = max(8, self.scene.snap_value(h))
            x_edges, y_edges = self._handle_edges()
            gx, gy, gw, gh = self.scene.snap_geom_to_guides(
                float(item["x"]),
                float(item["y"]),
                float(item["w"]),
                float(item["h"]),
                x_edges=x_edges,
                y_edges=y_edges,
                mode="resize",
            )
            item["x"] = int(round(gx))
            item["y"] = int(round(gy))
            item["w"] = max(8, int(round(gw)))
            item["h"] = max(8, int(round(gh)))
        self.scene._dirty = True
        self.scene.changed.emit()

    def _handle_edges(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        handle = self._handle
        x_edges = ()
        y_edges = ()
        if handle in (0, 6, 7):
            x_edges = ("left",)
        elif handle in (2, 3, 4):
            x_edges = ("right",)
        if handle in (0, 1, 2):
            y_edges = ("top",)
        elif handle in (4, 5, 6):
            y_edges = ("bottom",)
        return x_edges, y_edges

    def _bounds_from_handle(self, x0: float, y0: float, w0: float, h0: float, pos: QtCore.QPointF) -> tuple[float, float, float, float]:
        x1, y1 = x0 + w0, y0 + h0
        px, py = pos.x(), pos.y()
        handle = self._handle
        if handle in (0, 6, 7):
            x0 = px
        if handle in (2, 3, 4):
            x1 = px
        if handle in (0, 1, 2):
            y0 = py
        if handle in (4, 5, 6):
            y1 = py
        x, y = min(x0, x1), min(y0, y1)
        w, h = max(8.0, abs(x1 - x0)), max(8.0, abs(y1 - y0))
        return x, y, w, h

    def _lock_aspect(self, x: float, y: float, w: float, h: float, ox: float, oy: float, ow: float, oh: float):
        """Keep the original aspect, anchored on the opposite edge or corner."""
        ow = max(1.0, ow)
        oh = max(1.0, oh)
        ratio = ow / oh
        handle = self._handle
        right = ox + ow
        bottom = oy + oh
        cx = ox + ow / 2.0
        cy = oy + oh / 2.0
        min_scale = max(8.0 / ow, 8.0 / oh)
        if handle in (0, 2, 4, 6):
            scale = max(w / ow, h / oh, min_scale)
            w = ow * scale
            h = oh * scale
            if handle == 0:
                x, y = right - w, bottom - h
            elif handle == 2:
                x, y = ox, bottom - h
            elif handle == 4:
                x, y = ox, oy
            else:
                x, y = right - w, oy
            return x, y, w, h
        if handle in (3, 7):
            w = max(8.0, w)
            h = max(8.0, w / ratio)
            y = cy - h / 2.0
            x = (right - w) if handle == 7 else ox
            return x, y, w, h
        h = max(8.0, h)
        w = max(8.0, h * ratio)
        x = cx - w / 2.0
        y = (bottom - h) if handle == 1 else oy
        return x, y, w, h

    def _snap_locked_geom(self, x: float, y: float, w: float, h: float, ox: float, oy: float, ow: float, oh: float):
        """Snap an aspect-locked rect to the grid without stretching it."""
        ow = max(1.0, ow)
        oh = max(1.0, oh)
        ratio = ow / oh
        sw = max(8.0, float(self.scene.snap_value(w)))
        sh = max(8.0, float(self.scene.snap_value(h)))
        from_w = (sw, max(8.0, sw / ratio))
        from_h = (max(8.0, sh * ratio), sh)
        err_w = abs(from_w[0] - w) + abs(from_w[1] - h)
        err_h = abs(from_h[0] - w) + abs(from_h[1] - h)
        nw, nh = from_w if err_w <= err_h else from_h
        return self._lock_aspect(x, y, nw, nh, ox, oy, ow, oh)

    def _resize_group_to(self, pos: QtCore.QPointF, keep_aspect: bool = False):
        ox = float(self._start_bounds.get("x") or 0)
        oy = float(self._start_bounds.get("y") or 0)
        ow = max(1.0, float(self._start_bounds.get("w") or 1))
        oh = max(1.0, float(self._start_bounds.get("h") or 1))
        nx, ny, nw, nh = self._bounds_from_handle(ox, oy, ow, oh, pos)
        if keep_aspect:
            nx, ny, nw, nh = self._lock_aspect(nx, ny, nw, nh, ox, oy, ow, oh)
        else:
            x_edges, y_edges = self._handle_edges()
            nx, ny, nw, nh = self.scene.snap_geom_to_guides(nx, ny, nw, nh, x_edges=x_edges, y_edges=y_edges, mode="resize")
        min_w = min((max(1.0, g["w"]) for g in self._start_geoms.values()), default=8.0)
        min_h = min((max(1.0, g["h"]) for g in self._start_geoms.values()), default=8.0)
        if keep_aspect:
            scale = max(nw / ow, nh / oh, 8.0 / min_w, 8.0 / min_h)
            nw, nh = ow * scale, oh * scale
            nx, ny, nw, nh = self._lock_aspect(nx, ny, nw, nh, ox, oy, ow, oh)
            nx, ny, nw, nh = self._snap_locked_geom(nx, ny, nw, nh, ox, oy, ow, oh)
        else:
            nw = max(nw, 8.0 * ow / min_w)
            nh = max(nh, 8.0 * oh / min_h)
        sx = nw / ow
        sy = nh / oh
        self.scene._suspend += 1
        try:
            for widget_id, geom in self._start_geoms.items():
                item = self.scene.widget_by_id(widget_id)
                if not item:
                    continue
                item["x"] = int(round(nx + (geom["x"] - ox) * sx))
                item["y"] = int(round(ny + (geom["y"] - oy) * sy))
                item["w"] = max(8, int(round(geom["w"] * sx)))
                item["h"] = max(8, int(round(geom["h"] * sy)))
        finally:
            self.scene._suspend = max(0, self.scene._suspend - 1)
            self.scene._dirty = True
            self.scene._emit()

    def _drag_guide(self, pos: QtCore.QPointF):
        guide = self.scene.guide_by_id(self._guide_id) if self._guide_id else None
        if not guide:
            return
        cw, ch = self.canvas_size()
        if guide.get("axis") == "h":
            value = 0.0 if ch <= 0 else pos.y() / ch
        else:
            value = 0.0 if cw <= 0 else pos.x() / cw
        self.scene.update_guide(guide["id"], position=max(0.0, min(1.0, value)))

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent):
        if event.button() != QtCore.Qt.LeftButton:
            return
        pos = self.map_to_scene(event.position())
        item = self.scene.primary_selection()
        if not uses_editable_points(item):
            hit = self.scene.hit_test(pos.x(), pos.y())
            if hit:
                self.scene.set_selection(self.scene.expand_group_ids([hit["id"]]))
                item = hit
        if not uses_editable_points(item):
            return
        self.scene.push_undo()
        local = scene_to_widget_local(item, pos.x(), pos.y())
        index, _dist = closest_segment(item, local)
        self._shape_vertex = insert_shape_point(item, index, local)
        self._shape_handle = "point"
        self.scene._dirty = True
        self.scene.changed.emit()

    def _bezier_handle_indices(self, item: dict, points: list) -> list[int]:
        if uses_bezier_edit(item):
            handled = [index for index, point in enumerate(points) if _has_handles(point)]
            if handled:
                return handled
            if normalize_shape_kind((item.get("style") or {}).get("shape_kind")) == "freeform":
                return list(range(len(points)))
        if self._shape_vertex is not None and 0 <= self._shape_vertex < len(points):
            return [self._shape_vertex]
        return []

    def shape_handle_at(self, pos: QtCore.QPointF):
        item = self.scene.primary_selection()
        if not uses_editable_points(item):
            return None
        points = ensure_shape_points(item)
        tol = 7.0 / max(self._zoom, 0.25)
        for index in self._bezier_handle_indices(item, points):
            point = points[index]
            origin = _abs_point(item, point)
            for kind in ("in", "out"):
                local = _handle_point(item, point, kind)
                if QtCore.QLineF(origin, local).length() < 4.0:
                    continue
                handle = widget_local_to_scene(item, local.x(), local.y())
                if abs(pos.x() - handle.x()) <= tol and abs(pos.y() - handle.y()) <= tol:
                    return index, kind
        for index, point in enumerate(points):
            local = _abs_point(item, point)
            origin = widget_local_to_scene(item, local.x(), local.y())
            if abs(pos.x() - origin.x()) <= tol and abs(pos.y() - origin.y()) <= tol:
                return index, "point"
        return None

    def _drag_shape_handle(self, pos: QtCore.QPointF, modifiers):
        item = self.scene.primary_selection()
        if not uses_editable_points(item) or self._shape_vertex is None:
            return
        points = ensure_shape_points(item)
        if self._shape_vertex < 0 or self._shape_vertex >= len(points):
            return
        point = points[self._shape_vertex]
        freeform = uses_bezier_edit(item)
        local = scene_to_widget_local(item, pos.x(), pos.y())
        if self._shape_handle == "point":
            nx, ny = scene_to_normalized(item, local, clamp=not freeform)
            point["x"] = nx
            point["y"] = ny
        else:
            origin = _abs_point(item, point)
            width = max(1.0, float(item["w"]))
            height = max(1.0, float(item["h"]))
            dx = (local.x() - origin.x()) / width
            dy = (local.y() - origin.y()) / height
            if modifiers & QtCore.Qt.ControlModifier:
                dx, dy = snap_handle_offset(dx, dy, width, height)
            kind = self._shape_handle or "out"
            point[f"{kind}_x"] = dx
            point[f"{kind}_y"] = dy
            if not (modifiers & QtCore.Qt.AltModifier):
                other = "in" if kind == "out" else "out"
                point[f"{other}_x"] = -dx
                point[f"{other}_y"] = -dy
        if freeform:
            expand_shape_widget_to_controls(item, points)
        item["points"] = points
        self.scene._dirty = True
        self.scene.changed.emit()

    def _delete_shape_vertex(self) -> bool:
        item = self.scene.primary_selection()
        if not uses_editable_points(item) or self._shape_vertex is None:
            return False
        self.scene.push_undo()
        if not remove_shape_point(item, self._shape_vertex):
            return False
        self._shape_vertex = None
        self._shape_handle = None
        self.scene._dirty = True
        self.scene.changed.emit()
        return True

    def _save_custom_shape(self, item: dict | None):
        if not item or not (is_shape_widget(item) or button_uses_shape_path(item)):
            return
        suggested = str(item.get("label") or "").strip() or "Custom shape"
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Save custom shape",
            "Name:",
            QtWidgets.QLineEdit.Normal,
            suggested,
        )
        if not ok:
            return
        name = str(name or "").strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Save custom shape", "Enter a name for the shape.")
            return
        try:
            points, closed = snapshot_shape_points(item)
            kind = save_custom_shape(name, points, closed)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Save custom shape", str(exc) or "Could not save the shape.")
            return
        self.scene.push_undo()
        item.setdefault("style", {})
        item["style"]["shape_kind"] = kind
        item["style"]["shape_closed"] = closed
        item["points"] = default_shape_points(kind)
        self.scene._dirty = True
        self.scene.changed.emit()
        self.scene.selection_changed.emit()

    def _image_origin(self, width: int, height: int, scene_pos: QtCore.QPointF | None = None) -> tuple[int, int]:
        canvas_w = max(1, int(self.scene.canvas.get("width") or 1280))
        canvas_h = max(1, int(self.scene.canvas.get("height") or 720))
        if scene_pos is not None:
            x = int(scene_pos.x() - width / 2)
            y = int(scene_pos.y() - height / 2)
        else:
            scroll = self.parent()
            while scroll is not None and not isinstance(scroll, QtWidgets.QScrollArea):
                scroll = scroll.parent()
            if scroll is not None:
                viewport = scroll.viewport()
                center = self.mapFrom(viewport, viewport.rect().center())
                scene = self.map_to_scene(QtCore.QPointF(center))
                x = int(scene.x() - width / 2)
                y = int(scene.y() - height / 2)
            else:
                x = int(canvas_w / 2 - width / 2)
                y = int(canvas_h / 2 - height / 2)
        return max(0, min(canvas_w - width, x)), max(0, min(canvas_h - height, y))

    def _place_image(self, path: str, image: QtGui.QImage | None = None, scene_pos: QtCore.QPointF | None = None, hit=None) -> bool:
        if not path:
            return False
        if image is None or image.isNull():
            image = QtGui.QImage(path)
        target = hit
        if target is None and scene_pos is None:
            target = self.scene.primary_selection()
        if target is not None and target.get("type") == "image":
            self.scene.push_undo()
            return apply_image_to_item(self.scene, target, path, image)
        width = 200
        height = 120
        if image is not None and not image.isNull():
            canvas_w = max(32, int(self.scene.canvas.get("width") or 1280))
            canvas_h = max(32, int(self.scene.canvas.get("height") or 720))
            scale = min(1.0, canvas_w / max(1, image.width()), canvas_h / max(1, image.height()))
            width = max(16, int(round(image.width() * scale)))
            height = max(16, int(round(image.height() * scale)))
        x, y = self._image_origin(width, height, scene_pos)
        item = self.scene.add_widget("image", x, y)
        item["w"] = width
        item["h"] = height
        item["x"] = x
        item["y"] = y
        apply_image_to_item(self.scene, item, path, image)
        return True

    def paste_clipboard_image(self, scene_pos: QtCore.QPointF | None = None) -> bool:
        image = qimage_from_clipboard()
        if image is None:
            return False
        path = save_qimage(self.scene, image)
        if not path:
            return False
        hit = None
        if scene_pos is not None:
            hit = self.scene.hit_test(scene_pos.x(), scene_pos.y())
        return self._place_image(path, image, scene_pos, hit)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        mime = event.mimeData()
        if local_image_path_from_mime(mime) or qimage_from_mime(mime) is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        self.dragEnterEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent):
        mime = event.mimeData()
        scene_pos = self.map_to_scene(event.position())
        hit = self.scene.hit_test(scene_pos.x(), scene_pos.y())
        file_path = local_image_path_from_mime(mime)
        if file_path:
            path = import_image_file(self.scene, file_path)
            image = QtGui.QImage(path) if path else None
            if self._place_image(path, image, scene_pos, hit):
                event.acceptProposedAction()
                return
        image = qimage_from_mime(mime)
        if image is not None:
            path = save_qimage(self.scene, image)
            if self._place_image(path, image, scene_pos, hit):
                event.acceptProposedAction()
                return
        event.ignore()

    def _paint_selection(self, painter: QtGui.QPainter):
        super()._paint_selection(painter)
        item = self.scene.primary_selection()
        if not uses_editable_points(item):
            return
        points = ensure_shape_points(item)
        hs = 4.0 / max(self._zoom, 0.25)
        painter.save()
        apply_widget_rotation(painter, item)
        for index, point in enumerate(points):
            origin = _abs_point(item, point)
            selected = index == self._shape_vertex
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffe27a" if selected else "#7ec8ff"), 1.2))
            painter.setBrush(QtGui.QColor("#ffe27a" if selected else "#7ec8ff"))
            painter.drawEllipse(origin, hs, hs)
        for index in self._bezier_handle_indices(item, points):
            point = points[index]
            origin = _abs_point(item, point)
            selected = index == self._shape_vertex
            color = QtGui.QColor("#ffe27a" if selected else "#d4b84a")
            painter.setPen(QtGui.QPen(color, 1.0, QtCore.Qt.DashLine))
            for kind in ("in", "out"):
                handle = _handle_point(item, point, kind)
                if QtCore.QLineF(origin, handle).length() < 4.0:
                    continue
                painter.drawLine(origin, handle)
                painter.setBrush(color)
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawEllipse(handle, hs * 0.85, hs * 0.85)
                painter.setPen(QtGui.QPen(color, 1.0, QtCore.Qt.DashLine))
        painter.restore()


class OverlayDesignerWidget(QtWidgets.QWidget):
    """Overlay layout editor hosted on the Overlay device tab."""

    def __init__(self, scene: OverlayScene, overlay_manager=None, overlay_callback=None, parent=None):
        super().__init__(parent)
        self.scene = scene
        self._overlay_manager = overlay_manager
        self._overlay_callback = overlay_callback
        self.setMinimumSize(640, 480)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        self._title = QtWidgets.QLabel()
        self._title.setStyleSheet("font-weight: bold;")
        root.addWidget(self._title)
        self.refresh_profile_title()
        root.addWidget(self._toolbar())
        root.addWidget(self._page_bar())

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(self._palette())
        self.canvas = DesignerCanvas(scene)
        scroll = QtWidgets.QScrollArea()
        self._canvas_scroll = scroll
        scroll.setWidgetResizable(False)
        scroll.setAlignment(QtCore.Qt.AlignCenter)
        scroll.setWidget(self.canvas)
        bg = Color.actionBackgroundColor()
        scroll.setStyleSheet(f"QScrollArea {{ background: {bg}; border: none; }}")
        scroll.viewport().setAutoFillBackground(True)
        scroll.viewport().setStyleSheet(f"background: {bg};")
        center = QtWidgets.QWidget()
        center_layout = QtWidgets.QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(6)
        self._action_banner = ActionBanner()
        self._action_banner.hide_requested.connect(lambda: self._set_hints_visible(False))
        center_layout.addWidget(self._action_banner)
        center_layout.addWidget(scroll, 1)
        splitter.addWidget(center)
        self.inspector = OverlayInspector(scene)
        self.inspector.setMinimumWidth(300)
        self.inspector.setMaximumWidth(420)
        splitter.addWidget(self.inspector)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([220, 760, 320])
        root.addWidget(splitter, 1)
        self.canvas.zoom_changed.connect(self._on_canvas_zoom)
        self.scene.changed.connect(self._on_scene_ui)
        self.scene.selection_changed.connect(self._refresh_action_banner)
        if self._overlay_manager is not None:
            try:
                self._overlay_manager.visibility_changed.connect(self._refresh_overlay_button)
            except Exception:
                pass
        self._set_hints_visible(_banner_pref_visible(), persist=False)
        self._hints_box.toggled.connect(self._set_hints_visible)
        self._refresh_action_banner()
        paste = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Paste, self)
        paste.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        paste.activated.connect(self._paste_shortcut)

        try:
            el = gremlin.event_handler.EventListener()
            el.profile_loaded.connect(self.refresh_profile_title)
            el.profile_unloaded.connect(self.refresh_profile_title)
            self._profile_hooks = True
        except Exception:
            self._profile_hooks = False
        self.destroyed.connect(self._cleanup_ui)

    def _focus_wants_text_paste(self) -> bool:
        widget = QtWidgets.QApplication.focusWidget()
        while widget is not None:
            if isinstance(widget, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit, QtWidgets.QAbstractSpinBox)):
                return True
            if isinstance(widget, QtWidgets.QComboBox) and widget.isEditable():
                return True
            widget = widget.parentWidget()
        return False

    def _paste_shortcut(self):
        clip = QtWidgets.QApplication.clipboard()
        mime = clip.mimeData() if clip is not None else None
        has_text = bool(mime is not None and mime.hasText() and str(mime.text() or "").strip())
        if clipboard_has_image() and not (self._focus_wants_text_paste() and has_text):
            if self.canvas.paste_clipboard_image():
                return
        if not self._focus_wants_text_paste():
            return
        focus = QtWidgets.QApplication.focusWidget()
        if isinstance(focus, QtWidgets.QAbstractSpinBox):
            line = focus.lineEdit()
            if line is not None:
                line.paste()
            return
        if hasattr(focus, "paste"):
            focus.paste()

    def _cleanup_ui(self, *_args):
        """Disconnect scene/manager/profile hooks before Qt tears the widget down."""
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        if getattr(self, "scene", None) is not None and self.scene.dirty:
            self.scene.save_later()
        try:
            self.scene.changed.disconnect(self._on_scene_ui)
        except Exception:
            pass
        try:
            self.scene.selection_changed.disconnect(self._refresh_action_banner)
        except Exception:
            pass
        if self._overlay_manager is not None:
            try:
                self._overlay_manager.visibility_changed.disconnect(self._refresh_overlay_button)
            except Exception:
                pass
        if getattr(self, "_profile_hooks", False):
            try:
                el = gremlin.event_handler.EventListener()
                el.profile_loaded.disconnect(self.refresh_profile_title)
                el.profile_unloaded.disconnect(self.refresh_profile_title)
            except Exception:
                pass
            self._profile_hooks = False
        canvas = getattr(self, "canvas", None)
        if canvas is not None and alive(canvas):
            try:
                canvas.detach_from_scene()
            except Exception:
                pass
            try:
                canvas.detach_bus()
            except Exception:
                pass
        inspector = getattr(self, "inspector", None)
        if inspector is not None and alive(inspector):
            try:
                inspector._detach_scene()
            except Exception:
                pass

    @property
    def inputCount(self) -> int:
        return 0

    @property
    def inputWidgetCount(self) -> int:
        return 0

    def isLoaded(self) -> bool:
        return True

    def ensureLoaded(self):
        if self._overlay_manager is not None:
            self._overlay_manager._ensure_current_profile_scene()
        self.refresh_profile_title()

    def refresh(self, emit=True, force=False, **kwargs):
        self.refresh_profile_title()

    def refresh_ui(self):
        self.refresh_profile_title()

    def _on_zoom_slider(self, value: int):
        canvas = getattr(self, "canvas", None)
        if canvas is not None and alive(canvas):
            canvas.set_zoom(value / 100.0)
        zoom_value = getattr(self, "_zoom_value", None)
        if zoom_value is not None and alive(zoom_value):
            zoom_value.setText(f"{int(value)}%")

    def _set_zoom_percent(self, percent: int):
        slider = getattr(self, "_zoom_slider", None)
        if slider is not None and alive(slider):
            slider.setValue(int(percent))
        else:
            self._on_zoom_slider(int(percent))

    def _on_canvas_zoom(self, zoom: float):
        percent = int(round(float(zoom) * 100))
        slider = getattr(self, "_zoom_slider", None)
        if slider is not None and alive(slider):
            with QtCore.QSignalBlocker(slider):
                slider.setValue(percent)
        zoom_value = getattr(self, "_zoom_value", None)
        if zoom_value is not None and alive(zoom_value):
            zoom_value.setText(f"{percent}%")

    def _toolbar(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        self._overlay_button = QtWidgets.QPushButton("Show overlay")
        self._overlay_button.setToolTip("Show or hide the live window for the selected overlay page")
        self._overlay_button.clicked.connect(lambda _=False: self._toggle_overlay())
        self._interactive_box = QtWidgets.QCheckBox("Interactive")
        self._interactive_box.setToolTip(
            "On this page’s live overlay, touch or click widgets bound to vJoy or GEX states. "
            "Physical bindings stay display-only. Empty space stays click-through."
        )
        self._interactive_box.setChecked(bool(self.scene.canvas.get("interactive")))
        self._interactive_box.toggled.connect(self._set_interactive)
        self._hints_box = QtWidgets.QCheckBox("Hints")
        self._hints_box.setToolTip("Show or hide the action banner at the top of the canvas. The banner lists mouse and key actions for the current selection.")
        self._hints_box.setChecked(_banner_pref_visible())
        export = QtWidgets.QPushButton("Export overlay...")
        export.setToolTip("Copy this overlay to a JSON file you choose. The profile still keeps its own overlay.")
        export.clicked.connect(self._export_overlay)
        import_btn = QtWidgets.QPushButton("Import overlay...")
        import_btn.setToolTip("Replace this profile’s overlay with a JSON file.")
        import_btn.clicked.connect(self._import_overlay)
        undo = QtWidgets.QPushButton("Undo")
        undo.clicked.connect(self.scene.undo)
        redo = QtWidgets.QPushButton("Redo")
        redo.clicked.connect(self.scene.redo)
        for widget in (self._overlay_button, self._interactive_box, self._hints_box, export, import_btn, undo, redo):
            layout.addWidget(widget)
        layout.addStretch()
        zoom_label = QtWidgets.QLabel("Zoom")
        self._zoom_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._zoom_slider.setRange(25, 400)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(140)
        self._zoom_slider.setToolTip("Scale the designer canvas. Does not change the overlay resolution. Ctrl+wheel, Ctrl+0 reset.")
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        self._zoom_value = QtWidgets.QLabel("100%")
        self._zoom_value.setMinimumWidth(44)
        reset_zoom = QtWidgets.QPushButton("100%")
        reset_zoom.setFixedWidth(48)
        reset_zoom.setToolTip("Reset designer zoom to 100%")
        reset_zoom.clicked.connect(lambda _=False: self._set_zoom_percent(100))
        layout.addWidget(zoom_label)
        layout.addWidget(self._zoom_slider)
        layout.addWidget(self._zoom_value)
        layout.addWidget(reset_zoom)
        self._refresh_overlay_button()
        return bar

    def _page_bar(self) -> QtWidgets.QWidget:
        self._page_tabs = QTabHeader()
        self._page_tabs.setContentsMargins(0, 0, 0, 0)
        self._page_tabs.setMovable(True)
        self._page_tabs.setUsesScrollButtons(True)
        self._page_tabs.setObjectName("overlay_pages")
        self._page_tabs.setStyleSheet(Color.cssTab())
        self._page_tabs.setToolTip("Each tab is a separate overlay. Double-click to rename. Right-click to add, duplicate, or delete. Drag to reorder.")
        self._page_tabs.currentChanged.connect(self._on_page_tab_changed)
        self._page_tabs.tabBarDoubleClicked.connect(self._rename_page_tab)
        self._page_tabs.tabContextMenu.connect(self._page_tab_context)
        self._page_tabs.tabMoveCompleted.connect(self._on_page_tab_moved)
        add = gremlin.ui.ui_common.Buttons.getAddWidget(
            label=None,
            tooltip="Add overlay page",
            callback=lambda _data=None: self._add_page(),
        )
        add.setFixedSize(24, 24)
        row = gremlin.ui.ui_common.getHContainer([add, self._page_tabs], widget_only=True)
        row.setContentsMargins(0, 0, 0, 0)
        row.setMaximumHeight(30)
        self._page_tabs_sig = None
        self._refresh_page_tabs()
        return row

    def _on_scene_ui(self):
        if not alive(self):
            return
        if not gremlin.util.is_ui_thread():
            on_ui(self, self._on_scene_ui)
            return
        self._refresh_page_tabs()
        self._refresh_interactive_box()
        self._refresh_overlay_button()
        self._refresh_action_banner()

    def _refresh_action_banner(self):
        if not alive(self):
            return
        if not gremlin.util.is_ui_thread():
            on_ui(self, self._refresh_action_banner)
            return
        banner = getattr(self, "_action_banner", None)
        if banner is None or not alive(banner):
            return
        title, body = action_banner_content(self.scene)
        banner.set_content(title, body)

    def _set_hints_visible(self, visible: bool, persist: bool = True):
        banner = getattr(self, "_action_banner", None)
        if banner is not None and Shiboken.isValid(banner):
            banner.setVisible(bool(visible))
        box = getattr(self, "_hints_box", None)
        if box is not None and Shiboken.isValid(box) and box.isChecked() != bool(visible):
            with QtCore.QSignalBlocker(box):
                box.setChecked(bool(visible))
        if persist:
            _set_banner_pref_visible(bool(visible))

    def _refresh_page_tabs(self):
        if not Shiboken.isValid(self):
            return
        tabs = getattr(self, "_page_tabs", None)
        if tabs is None or not Shiboken.isValid(tabs):
            return
        if getattr(tabs, "moveInProgress", False):
            return
        sig = (self.scene.active_page_id, tuple((page["id"], page.get("name") or "Overlay") for page in self.scene.pages))
        if getattr(self, "_page_tabs_sig", None) == sig:
            return
        self._page_tabs_sig = sig
        with QtCore.QSignalBlocker(tabs):
            while tabs.count():
                tabs.removeTab(0)
            current = 0
            for index, page in enumerate(self.scene.pages):
                tabs.addTab(str(page.get("name") or "Overlay"))
                tabs.setTabData(index, page["id"])
                if page["id"] == self.scene.active_page_id:
                    current = index
            if tabs.count():
                tabs.setCurrentIndex(current)

    def _on_page_tab_changed(self, index: int):
        if index < 0:
            return
        page_id = self._page_tabs.tabData(index)
        if page_id:
            self.scene.set_active_page(str(page_id))

    def _rename_page_tab(self, index: int):
        if index < 0:
            return
        page_id = self._page_tabs.tabData(index)
        page = self.scene.page_by_id(page_id)
        if page is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Rename overlay page", "Name:", text=str(page.get("name") or ""))
        if ok:
            self.scene.rename_page(name, page_id)

    def _on_page_tab_moved(self, _from_index: int, _to_index: int):
        tabs = getattr(self, "_page_tabs", None)
        if tabs is None:
            return
        order = []
        for index in range(tabs.count()):
            page_id = tabs.tabData(index)
            if page_id:
                order.append(str(page_id))
        if order:
            self.scene.reorder_pages(order)

    def _page_tab_context(self, index: int):
        if index < 0:
            return
        page_id = self._page_tabs.tabData(index)
        menu = QtWidgets.QMenu(self)
        add = menu.addAction("Add page")
        rename = menu.addAction("Rename")
        duplicate = menu.addAction("Duplicate")
        delete = menu.addAction("Delete")
        delete.setEnabled(len(self.scene.pages) > 1)
        chosen = menu.exec(QtGui.QCursor.pos())
        if chosen is add:
            self._add_page()
        elif chosen is rename:
            self._rename_page_tab(index)
        elif chosen is duplicate:
            self.scene.duplicate_page(page_id)
        elif chosen is delete:
            self._delete_page(page_id)

    def _add_page(self):
        self.scene.add_page()

    def _delete_page(self, page_id):
        if len(self.scene.pages) <= 1:
            QtWidgets.QMessageBox.information(self, "OBS Overlay", "Keep at least one overlay page.")
            return
        page = self.scene.page_by_id(page_id)
        name = (page or {}).get("name") or "this page"
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Delete overlay page",
            f"Delete “{name}”? Widgets on this page are removed from the layout.",
        )
        if confirm == QtWidgets.QMessageBox.Yes:
            self.scene.delete_page(page_id)

    def _palette(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        panel.setMinimumWidth(220)
        panel.setMaximumWidth(280)
        layout = QtWidgets.QVBoxLayout(panel)
        for title, types in PALETTE_GROUPS:
            layout.addWidget(QtWidgets.QLabel(title))
            for widget_type in types:
                btn = QtWidgets.QPushButton(WIDGET_TITLES.get(widget_type, widget_type))
                btn.setToolTip(
                    f"Add a {WIDGET_TITLES.get(widget_type, widget_type)}. "
                    "If a widget is selected, change it to this type and keep compatible settings."
                )
                btn.clicked.connect(lambda _=False, t=widget_type: self._add_widget(t))
                layout.addWidget(btn)
        layout.addSpacing(12)
        layout.addWidget(QtWidgets.QLabel("Templates"))
        for name, tip, factory in TEMPLATES:
            btn = TemplateButton(name, editable=False)
            btn.setToolTip(tip)
            btn.apply_requested.connect(lambda fn=factory, title=name: self._apply_template(title, fn))
            layout.addWidget(btn)
        saved_header = QtWidgets.QWidget()
        saved_row = QtWidgets.QHBoxLayout(saved_header)
        saved_row.setContentsMargins(0, 0, 0, 0)
        saved_row.setSpacing(4)
        saved_row.addWidget(QtWidgets.QLabel("Saved templates"))
        add_template = gremlin.ui.ui_common.Buttons.getAddWidget(
            label=None,
            tooltip="Save the current widgets as a global template (not profile-specific)",
            callback=lambda _data=None: self._save_template(),
        )
        add_template.setFixedSize(24, 24)
        saved_row.addWidget(add_template)
        saved_row.addStretch()
        layout.addWidget(saved_header)
        self._user_templates_host = QtWidgets.QWidget()
        self._user_templates_layout = QtWidgets.QVBoxLayout(self._user_templates_host)
        self._user_templates_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._user_templates_host)
        self._refresh_user_templates()
        layout.addStretch()
        bg = Color.actionBackgroundColor()
        panel.setStyleSheet(f"QWidget {{ background: {bg}; }}")
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(220)
        scroll.setMaximumWidth(280)
        return scroll

    def _add_widget(self, widget_type: str):
        if self.scene.convert_selected(widget_type):
            self.canvas.setFocus()
            return
        size = DEFAULT_SIZES.get(widget_type, (80, 80))
        if widget_type == "streamdeck":
            size = self._streamdeck_add_size()
        x, y = self._viewport_add_origin(int(size[0]), int(size[1]))
        item = self.scene.add_widget(widget_type, x, y)
        if widget_type == "streamdeck" and item:
            item["w"] = int(size[0])
            item["h"] = int(size[1])
            self.scene._emit()
        self.canvas.setFocus()

    def _streamdeck_add_size(self) -> tuple[int, int]:
        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge
            from .widgets import streamdeck_preferred_size

            bridge = StreamDeckBridge()
            device_id = bridge.resolve_overlay_device_id("")
            info = bridge.devices.get(device_id, {}) if device_id else {}
            return streamdeck_preferred_size((info or {}).get("type"))
        except Exception:
            return DEFAULT_SIZES.get("streamdeck", (320, 208))

    def _viewport_add_origin(self, width: int, height: int) -> tuple[int, int]:
        scroll = getattr(self, "_canvas_scroll", None)
        canvas_w = max(1, int(self.scene.canvas.get("width") or 1280))
        canvas_h = max(1, int(self.scene.canvas.get("height") or 720))
        if scroll is not None:
            viewport = scroll.viewport()
            center = self.canvas.mapFrom(viewport, viewport.rect().center())
            scene = self.canvas.map_to_scene(QtCore.QPointF(center))
            x = int(scene.x() - width / 2)
            y = int(scene.y() - height / 2)
        else:
            x = int(canvas_w / 2 - width / 2)
            y = int(canvas_h / 2 - height / 2)
        return max(0, min(canvas_w - width, x)), max(0, min(canvas_h - height, y))

    def _apply_template(self, title: str, factory):
        items = factory()
        if not items:
            if title.lower().startswith("blank"):
                self.scene.clear_widgets()
            return
        self.scene.add_widgets(items)

    def _refresh_user_templates(self):
        layout = getattr(self, "_user_templates_layout", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        entries = list_user_templates()
        if not entries:
            hint = QtWidgets.QLabel("None yet — use + to save the current widgets.")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            return
        for name, tip, factory, filename in entries:
            btn = TemplateButton(name, editable=True)
            btn.setToolTip(f"{tip}. Click to apply. Right-click to update with the current widgets or delete.")
            btn.apply_requested.connect(lambda fn=factory, title=name: self._apply_template(title, fn))
            btn.update_requested.connect(lambda fname=filename, title=name: self._update_template(fname, title))
            btn.delete_requested.connect(lambda fname=filename, title=name: self._delete_template(fname, title))
            layout.addWidget(btn)

    def _update_template(self, filename: str, title: str):
        if not self.scene.widgets:
            QtWidgets.QMessageBox.information(self, "OBS Overlay", "Add widgets before updating a template.")
            return
        try:
            update_user_template(filename, self.scene.widgets)
        except Exception as err:
            QtWidgets.QMessageBox.warning(self, "OBS Overlay", f"Could not update template:\n{err}")
            return
        self._refresh_user_templates()
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), f"Updated {title}", self)

    def _delete_template(self, filename: str, title: str):
        try:
            delete_user_template(filename)
        except Exception as err:
            QtWidgets.QMessageBox.warning(self, "OBS Overlay", f"Could not delete template:\n{err}")
            return
        self._refresh_user_templates()
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), f"Deleted {title}", self)

    def _save_template(self):
        if not self.scene.widgets:
            QtWidgets.QMessageBox.information(self, "OBS Overlay", "Add widgets before saving a template.")
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Save template", "Template name:")
        if not ok or not str(name).strip():
            return
        try:
            path = save_user_template(str(name).strip(), self.scene.widgets)
        except Exception as err:
            QtWidgets.QMessageBox.warning(self, "OBS Overlay", f"Could not save template:\n{err}")
            return
        self._refresh_user_templates()
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), f"Saved {path}", self)

    def _set_interactive(self, checked: bool):
        if bool(self.scene.canvas.get("interactive")) == bool(checked):
            return
        self.scene.canvas["interactive"] = bool(checked)
        self.scene._dirty = True
        self.scene.changed.emit()

    def _refresh_interactive_box(self):
        box = getattr(self, "_interactive_box", None)
        if box is None or not alive(box):
            return
        checked = is_interactive_overlay(self.scene.canvas)
        if box.isChecked() != checked:
            with QtCore.QSignalBlocker(box):
                box.setChecked(checked)

    def _toggle_overlay(self):
        manager = self._overlay_manager
        page_id = self.scene.active_page_id
        if manager is not None and page_id:
            if manager.page_is_visible(page_id):
                manager.hide_overlay_page(page_id)
            else:
                manager.show_overlay(page_ids=[page_id])
            self._refresh_overlay_button()
            return
        if callable(self._overlay_callback):
            self._overlay_callback()
        self._refresh_overlay_button()

    def _refresh_overlay_button(self):
        if not alive(self):
            return
        if not gremlin.util.is_ui_thread():
            on_ui(self, self._refresh_overlay_button)
            return
        button = getattr(self, "_overlay_button", None)
        if button is None or not alive(button):
            return
        page_id = self.scene.active_page_id
        visible = bool(self._overlay_manager and page_id and self._overlay_manager.page_is_visible(page_id))
        button.setText("Hide overlay" if visible else "Show overlay")

    def refresh_profile_title(self):
        if not alive(self):
            return
        if not gremlin.util.is_ui_thread():
            on_ui(self, self.refresh_profile_title)
            return
        title = getattr(self, "_title", None)
        if title is None or not alive(title):
            return
        title.setText(f"Overlay — {profile_display_name()}")
        self._refresh_overlay_button()

    def _overlay_file_start(self) -> str:
        sidecar = overlay_path_for_profile()
        if sidecar:
            return sidecar
        xml = profile_xml_path()
        folder = os.path.dirname(xml) if xml else (gremlin.shared_state.data_path or "")
        stem = profile_display_name().replace(" ", "_") or "overlay"
        if stem in ("No profile", "Unsaved profile"):
            stem = "overlay"
        return os.path.join(folder, f"{stem}.overlay.json")

    def _export_overlay(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export overlay",
            self._overlay_file_start(),
            "Overlay JSON (*.overlay.json);;JSON (*.json)",
        )
        if not path:
            return
        lower = path.casefold()
        if not (lower.endswith(".overlay.json") or lower.endswith(".json")):
            path += ".overlay.json"
        if self.scene.save(path):
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), f"Exported {os.path.basename(path)}", self)
        else:
            QtWidgets.QMessageBox.warning(self, "OBS Overlay", f"Could not export overlay to:\n{path}")

    def _import_overlay(self):
        start = self._overlay_file_start()
        directory = os.path.dirname(start) if start else ""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Import overlay",
            directory,
            "Overlay JSON (*.overlay.json *.json)",
        )
        if path:
            self.scene.load(path)
            self.refresh_profile_title()

    def showEvent(self, event):
        if hasattr(self, "canvas") and Shiboken.isValid(self.canvas):
            self.canvas.attach_bus()
        self._refresh_overlay_button()
        super().showEvent(event)

    def hideEvent(self, event):
        if hasattr(self, "canvas") and Shiboken.isValid(self.canvas):
            self.canvas.detach_bus()
        if self.scene.dirty:
            self.scene.save_later()
        super().hideEvent(event)


OverlayDesignerDialog = OverlayDesignerWidget
