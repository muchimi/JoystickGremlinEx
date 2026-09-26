# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import logging
import sys
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

import gremlin.event_handler
import gremlin.joystick_handling
import gremlin.keyboard
import gremlin.shared_state
import gremlin.types
import gremlin.ui.ui_common
import gremlin.ui.virtual_keyboard
import gremlin.util
from gremlin.input_types import InputType
from gremlin.ui.ui_common import Buttons, Color, QDataComboBox, QDataPushButton, QDataRadioButtonGroup

from .bindings import (
    find_overlay_state,
    overlay_mode_combo_fields,
    overlay_state_combo_fields,
    populate_overlay_mode_combo,
    populate_overlay_state_combo,
    resolve_overlay_mode,
    widget_needs_xy,
)
from .mouse_track import normalize_mouse_mode
from .qt_guard import alive, later, on_ui
from .model import (
    DEFAULT_GUIDE_COLOR,
    GRAPH_SERIES_COLORS,
    NO_BINDING_WIDGET_TYPES,
    NO_CORNER_RADIUS_TYPES,
    NO_DEADZONE_WIDGET_TYPES,
    RUNTIME_BINDING_ACTIONS,
    RUNTIME_BINDING_LABELS,
    SWITCH_POSITION_TITLES,
    OverlayScene,
    canonical_widget_type,
    default_graph_series,
    default_stat_entry,
    default_style,
    default_toggle_binding,
    default_visibility,
    default_visibility_condition,
    deserialize_overlay_key,
    is_onscreen_mode,
    normalize_background_mode,
    normalize_graph_series,
    normalize_overlay_keys,
    normalize_paddle_direction,
    normalize_runtime_bindings,
    normalize_series_range_mode,
    normalize_stat_series,
    normalize_switch_appearance,
    normalize_toggle_binding,
    normalize_visibility,
    serialize_overlay_key,
    switch_channel,
    widget_display_name,
    widget_is_switch,
    widget_uses_series,
)
from .shapes import (
    button_uses_shape_path,
    custom_shape,
    default_shape_points,
    is_custom_kind,
    normalize_shape_kind,
    shape_kind_choices,
    shape_kind_tooltip,
)
from .overlay_window import apply_onscreen_geometry, list_overlay_screens, resolve_overlay_screen
from .visibility_logic import assign_condition_letters, default_join_expression, effective_visibility_expression
from .visibility_preview import BooleanOperatorsDialog, VisibilityPreviewDialog
from .palettes import (
    BUILTIN_IDS,
    COLOR_KEYS,
    add_palette,
    delete_palette,
    extract_colors,
    list_builtin_palettes,
    list_user_palettes,
    palette_type,
    update_palette,
)
from .widgets import (
    apply_group_rotation_delta,
    border_is_enabled,
    effective_font_size,
    qcolor,
    resolve_font_shadow,
    resolve_widget_shadow,
    _shadow_offset_xy,
    widget_rotated_bounds,
    widget_rotation_deg,
)

CANVAS_TOGGLE_ID = "__canvas_toggle__"
CANVAS_RUNTIME_PREFIX = "__canvas_runtime__:"
syslog = logging.getLogger("system")


def _set_form_rows_visible(form, fields, visible: bool):
    """Show or hide QFormLayout rows for the given field widgets (and their labels)."""
    visible = bool(visible)
    for field in fields or ():
        if field is None:
            continue
        if isinstance(form, QtWidgets.QFormLayout):
            try:
                form.setRowVisible(field, visible)
            except (AttributeError, TypeError, RuntimeError):
                pass
            label = form.labelForField(field)
            if label is not None:
                label.setVisible(visible)
        field.setVisible(visible)


class ColorButton(QtWidgets.QPushButton):
    """Solid color or gradient value swatch. Emits str hex or gradient dict."""

    color_changed = QtCore.Signal(object)

    def __init__(self, value="#ffffff", parent=None, preserve_transparent: bool = False, allow_gradient: bool = True):
        if parent is None:
            parent = Buttons._default_parent
        super().__init__(parent)
        self.setObjectName("overlayColorSwatch")
        self._value = value if value is not None else "#ffffff"
        self._preserve_transparent = bool(preserve_transparent)
        self._allow_gradient = bool(allow_gradient)
        self.setFixedHeight(24)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setStyleSheet("#overlayColorSwatch { border: none; background: transparent; }")
        self.clicked.connect(self._pick)
        self._refresh()

    def set_value(self, value):
        self._value = value if value is not None else "#ffffff"
        self._refresh()

    def value(self):
        return self._value

    def _refresh(self):
        from .gradient import gradient_preview_color, is_gradient

        if is_gradient(self._value):
            tip = "Gradient"
        else:
            tip = str(self._value)
        self.setToolTip(tip)
        self.update()

    def paintEvent(self, event):
        from .gradient import is_gradient, paint_gradient_spectrum

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 3, 3)
        painter.setClipPath(path)
        if is_gradient(self._value):
            paint_gradient_spectrum(painter, rect, self._value)
        else:
            color = qcolor(self._value)
            if color.alpha() < 255:
                # Checkerboard under translucent solids
                painter.fillRect(rect, QtGui.QColor(Color.backgroundColor()))
                tile = 5
                light = QtGui.QColor("#3a3a3a")
                for y in range(int(rect.top()), int(rect.bottom()), tile):
                    for x in range(int(rect.left()), int(rect.right()), tile):
                        if ((x // tile) + (y // tile)) % 2 == 0:
                            painter.fillRect(x, y, tile, tile, light)
            painter.fillRect(rect, color)
        painter.setClipping(False)
        painter.setPen(QtGui.QPen(QtGui.QColor("#444444"), 1))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(rect, 3, 3)
        painter.end()

    def _pick(self):
        import copy

        from .gradient import (
            GradientEditorDialog,
            default_gradient,
            gradient_preview_color,
            is_gradient,
            normalize_gradient,
        )

        parent = self.window() or self.parentWidget() or self
        if is_gradient(self._value):
            initial = qcolor(gradient_preview_color(self._value))
        else:
            initial = qcolor(self._value)
        dialog = QtWidgets.QColorDialog(initial, parent)
        dialog.setWindowTitle("Select color")
        dialog.setOption(QtWidgets.QColorDialog.DontUseNativeDialog, True)
        dialog.setOption(QtWidgets.QColorDialog.ShowAlphaChannel, True)

        last_gradient = copy.deepcopy(self._value) if is_gradient(self._value) else None

        gradient_enable = QtWidgets.QCheckBox("Gradient", dialog)
        gradient_enable.setChecked(is_gradient(self._value))
        gradient_enable.setToolTip("Use a gradient fill instead of a solid color. Uncheck to return to a solid color.")
        if not self._allow_gradient:
            gradient_enable.hide()

        gradient_btn = QDataPushButton(
            "Edit gradient…",
            parent=dialog,
            tooltip="Open the gradient editor (linear / radial, stops, angle, scale).",
        )
        gradient_btn.setEnabled(gradient_enable.isChecked())
        if not self._allow_gradient:
            gradient_btn.hide()

        def _apply_value(value):
            self._value = value
            self._refresh()
            self.color_changed.emit(self._value)

        def _solid_from_dialog():
            chosen = dialog.currentColor()
            if not chosen.isValid():
                if last_gradient is not None:
                    chosen = qcolor(gradient_preview_color(last_gradient))
                else:
                    chosen = qcolor("#ffffffff")
            previous = qcolor(self._value if not is_gradient(self._value) else "#00000000")
            if not self._preserve_transparent and previous.alpha() == 0 and chosen.alpha() == 0:
                chosen.setAlpha(255)
            return chosen.name(QtGui.QColor.HexArgb)

        def _on_gradient_toggled(on):
            nonlocal last_gradient
            if on:
                seed = dialog.currentColor().name(QtGui.QColor.HexArgb)
                if last_gradient is None:
                    last_gradient = default_gradient(seed)
                _apply_value(normalize_gradient(last_gradient, seed_color=seed))
                gradient_btn.setEnabled(True)
            else:
                if is_gradient(self._value):
                    last_gradient = copy.deepcopy(self._value)
                _apply_value(_solid_from_dialog())
                gradient_btn.setEnabled(False)

        def _open_gradient():
            nonlocal last_gradient
            seed = dialog.currentColor().name(QtGui.QColor.HexArgb)
            original = copy.deepcopy(self._value)
            current = self._value if is_gradient(self._value) else (last_gradient or default_gradient(seed))
            editor = GradientEditorDialog(current, seed_color=seed, parent=dialog)

            def _preview(grad):
                _apply_value(normalize_gradient(grad, seed_color=seed))

            editor.preview_changed.connect(_preview)
            _preview(editor.result_gradient())
            accepted = editor.exec() == QtWidgets.QDialog.Accepted
            if accepted:
                grad = normalize_gradient(editor.result_gradient(), seed_color=seed)
                last_gradient = copy.deepcopy(grad)
                gradient_enable.blockSignals(True)
                gradient_enable.setChecked(True)
                gradient_enable.blockSignals(False)
                gradient_btn.setEnabled(True)
                _apply_value(grad)
                dialog.reject()
            else:
                _apply_value(original)

        gradient_enable.toggled.connect(_on_gradient_toggled)
        gradient_btn.clicked.connect(_open_gradient)

        host = QtWidgets.QWidget(dialog)
        host_layout = QtWidgets.QVBoxLayout(host)
        host_layout.setContentsMargins(0, 6, 0, 0)
        host_layout.setSpacing(4)
        host_layout.addWidget(gradient_enable)
        host_layout.addWidget(gradient_btn)

        layout = dialog.layout()
        if isinstance(layout, QtWidgets.QGridLayout):
            layout.addWidget(host, layout.rowCount(), 0, 1, layout.columnCount())
        elif layout is not None:
            layout.addWidget(host)

        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        # Keep an active gradient; OK on the solid picker must not wipe it.
        if gradient_enable.isChecked() and is_gradient(self._value):
            _apply_value(normalize_gradient(self._value))
            return
        _apply_value(_solid_from_dialog())


class PaletteSwatch(QtWidgets.QPushButton):
    """One saved color set, shown as a fill square (cross if the fill is transparent)."""

    apply_requested = QtCore.Signal()
    update_requested = QtCore.Signal()
    delete_requested = QtCore.Signal()

    def __init__(self, colors: dict, label: str, editable: bool = False, parent=None):
        super().__init__(parent)
        self._colors = colors or {}
        self._editable = editable
        self.setFixedSize(28, 28)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setFlat(True)
        self.setStyleSheet("QPushButton { border: none; background: transparent; padding: 0; }")
        if editable:
            self.setToolTip(f"{label}. Click to apply. Right-click to update with the current colors or delete.")
            self.setContextMenuPolicy(QtCore.Qt.DefaultContextMenu)
        else:
            self.setToolTip(f"{label}. Click to apply.")
            self.setContextMenuPolicy(QtCore.Qt.NoContextMenu)
        self.clicked.connect(lambda _=False: self.apply_requested.emit())

    def paintEvent(self, event):
        from .gradient import is_gradient, paint_gradient_spectrum

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        rect = self.rect().adjusted(2, 2, -3, -3)
        fill_value = self._colors.get("fill")
        fill = qcolor(fill_value if not is_gradient(fill_value) else "#121826", "#121826")
        accent_raw = self._colors.get("fill_on") or self._colors.get("indicator") or self._colors.get("fill_bar") or self._colors.get("border")
        accent = qcolor(accent_raw if not is_gradient(accent_raw) else "#888888", "#888888")
        outline_raw = self._colors.get("border") or self._colors.get("indicator")
        outline = qcolor(outline_raw if not is_gradient(outline_raw) else "#555555", "#555555")
        if is_gradient(fill_value):
            paint_gradient_spectrum(painter, QtCore.QRectF(rect), fill_value)
        elif fill.alpha() <= 0:
            painter.fillRect(rect, QtGui.QColor(Color.backgroundColor()))
            painter.setPen(QtGui.QPen(accent if accent.alpha() > 0 else QtGui.QColor("#888888"), 2))
            painter.drawLine(rect.topLeft() + QtCore.QPoint(1, 1), rect.bottomRight() - QtCore.QPoint(1, 1))
            painter.drawLine(rect.topRight() + QtCore.QPoint(-1, 1), rect.bottomLeft() + QtCore.QPoint(1, -1))
        else:
            painter.fillRect(rect, fill)
            if accent.alpha() > 0 and accent != fill:
                corner = QtCore.QRect(rect.right() - 8, rect.bottom() - 8, 8, 8)
                painter.fillRect(corner, accent)
        painter.setPen(QtGui.QPen(outline if outline.alpha() > 0 else QtGui.QColor("#555555"), 1))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(rect)
        painter.end()

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        if not self._editable:
            return
        menu = QtWidgets.QMenu(self)
        update_action = menu.addAction("Update with current colors")
        update_action.triggered.connect(lambda _=False: self.update_requested.emit())
        delete_action = menu.addAction("Delete palette")
        delete_action.triggered.connect(lambda _=False: self.delete_requested.emit())
        menu.exec(event.globalPos())


class OverlayKeyCombinationWidget(QtWidgets.QWidget):
    """Map to Keyboard/Mouse Ex combination row: display, Listen, and Select popup."""

    keys_changed = QtCore.Signal(object)

    def __init__(self, keys=None, parent=None):
        super().__init__(parent)
        self._keys = []
        self._listen_dialog = None
        self._keyboard_dialog = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QtWidgets.QLabel("<b>Current key combination:</b>"))
        self._display, self._display_layout = gremlin.ui.ui_common.getHContainer()
        sample = gremlin.ui.virtual_keyboard.QKeyWidget()
        self._display.setMinimumHeight(int(sample.desiredHeight) + 4)
        layout.addWidget(self._display)
        layout.addWidget(gremlin.ui.ui_common.QHorizontalLine())
        clear = gremlin.ui.ui_common.Buttons.getClearWidget(callback=self._clear)
        listen = gremlin.ui.ui_common.Buttons.getListenWidget(callback=lambda: self._listen(False), no_keyboard=False)
        listen.setToolTip("Listen for a single keyboard or mouse input.")
        listen_multi = gremlin.ui.ui_common.Buttons.getListenWidget(
            label="Listen (multi)",
            callback=lambda: self._listen(True),
            no_keyboard=False,
        )
        listen_multi.setToolTip("Listen for multiple inputs. Click OK when done.")
        select = gremlin.ui.ui_common.QIconPushButton("Select...")
        select.setIcon(gremlin.util.load_icon("mdi.keyboard-settings-outline", qta_color=gremlin.ui.ui_common.Color.listenColor()))
        select.setToolTip("Select keys using the virtual keyboard")
        select.setFixedHeight(24)
        select.clicked.connect(self._select)
        actions = gremlin.ui.ui_common.getHContainer([clear, listen, listen_multi, select], widget_only=True)
        layout.addWidget(actions)
        self.set_keys(keys)

    def set_keys(self, keys):
        parsed = []
        for item in keys or []:
            key = deserialize_overlay_key(item)
            if key is not None and key not in parsed:
                parsed.append(key)
        self._keys = parsed
        self._populate()

    def _populate(self):
        gremlin.util.clear_layout(self._display_layout)
        if not self._keys:
            self._display_layout.addWidget(gremlin.ui.ui_common.QWarningWidget("No input selected. Please select at least one input."))
            self._display_layout.addStretch()
            return
        for key in self._keys:
            widget = gremlin.ui.virtual_keyboard.QKeyWidget()
            widget.key = key
            icon = gremlin.keyboard.KeyMap.icon(key)
            name = gremlin.keyboard.KeyMap.get_name(key)
            tooltip = gremlin.keyboard.KeyMap.get_description(key)
            if icon:
                widget.setIcon(icon)
            if name:
                widget.setText(name)
            if tooltip:
                widget.setToolTip(tooltip)
            widget.keySize = 2
            widget.autoSize = True
            widget.right_clicked.connect(self._key_menu)
            self._display_layout.addWidget(widget)
        self._display_layout.addStretch()

    def _emit(self):
        self.keys_changed.emit([serialize_overlay_key(key) for key in self._keys])

    def _clear(self):
        self._keys = []
        self._populate()
        self._emit()

    def _apply_keys(self, keys):
        parsed = []
        for item in keys or []:
            key = deserialize_overlay_key(item)
            if key is not None and key not in parsed:
                parsed.append(key)
        try:
            parsed = gremlin.keyboard.sort_keys(parsed)
        except Exception:
            pass
        self._keys = list(parsed)
        self._populate()
        self._emit()

    def _key_menu(self, widget):
        action = QtGui.QAction("Delete", self)
        action.triggered.connect(lambda _=False, w=widget: self._delete_key(w))
        menu = QtWidgets.QMenu(self)
        menu.addAction(action)
        menu.exec(QtGui.QCursor.pos())

    def _delete_key(self, widget):
        key = getattr(widget, "key", None)
        if key in self._keys:
            self._keys.remove(key)
            self._populate()
            self._emit()

    def _close_listen(self):
        dialog = self._listen_dialog
        self._listen_dialog = None
        if dialog is None:
            return
        try:
            if Shiboken.isValid(dialog):
                dialog.close()
        except Exception:
            pass

    def _listen(self, multi_keys: bool):
        self._close_listen()
        gremlin.shared_state.push_suspend_highlighting()
        listener = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.Keyboard, InputType.Mouse],
            return_kb_event=False,
            multi_keys=multi_keys,
        )
        listener.item_selected.connect(self._apply_keys)
        listener.keyInput.connect(self._preview_keys)
        listener.closed.connect(self._listen_closed)
        self._listen_dialog = listener
        listener.show()

    def _preview_keys(self, keys):
        parsed = []
        for item in keys or []:
            key = deserialize_overlay_key(item)
            if key is not None and key not in parsed:
                parsed.append(key)
        self._keys = parsed
        self._populate()

    def _listen_closed(self, accepted=True):
        self._close_listen()
        try:
            gremlin.shared_state.pop_suspend_highlighting()
        except Exception:
            pass
        if accepted:
            self._emit()
        else:
            self._populate()

    def _select(self):
        from gremlin.ui.virtual_keyboard import InputKeyboardDialog

        gremlin.shared_state.push_suspend_ui_keyinput()
        dialog = InputKeyboardDialog(sequence=list(self._keys), parent=self.window())
        dialog.accepted.connect(lambda: self._apply_keys(dialog.keys))
        dialog.closed.connect(self._select_closed)
        dialog.setModal(True)
        self._keyboard_dialog = dialog
        dialog.showNormal()

    def _select_closed(self):
        self._keyboard_dialog = None
        try:
            gremlin.shared_state.pop_suspend_ui_keyinput()
        except Exception:
            pass


class CollapsibleSection(QtWidgets.QWidget):
    """Inspector group with a title header and up/down arrow to show or hide the body."""

    toggled = QtCore.Signal(bool)  # True when expanded

    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        self._title = title
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 6)
        root.setSpacing(0)

        self._toggle = QtWidgets.QToolButton(self)
        self._toggle.setObjectName("overlaySectionToggle")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(bool(expanded))
        self._toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self._toggle.setAutoRaise(True)
        self._toggle.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        hdr = Color.headerBarBackgroundColor()
        hover = Color.backgroundLighterColor()
        fg = Color.normalColor()
        self._toggle.setStyleSheet(
            "#overlaySectionToggle {"
            "  font-weight: bold;"
            "  text-align: left;"
            "  padding: 6px 8px;"
            "  border: none;"
            "  border-radius: 0;"
            f"  background-color: {hdr};"
            f"  color: {fg};"
            "}"
            "#overlaySectionToggle:hover {"
            "  border-radius: 0;"
            f"  background-color: {hover};"
            "}"
            "#overlaySectionToggle:checked,"
            "#overlaySectionToggle:pressed {"
            "  border-radius: 0;"
            f"  background-color: {hdr};"
            "}"
        )
        self._toggle.setText(title)
        self._apply_arrow(bool(expanded))
        self._toggle.setToolTip("Collapse or expand this section.")
        self._toggle.toggled.connect(self._on_toggled)

        self._body = QtWidgets.QWidget(self)
        self._form = QtWidgets.QFormLayout(self._body)
        self._form.setLabelAlignment(QtCore.Qt.AlignRight)
        # Gap between the header fill and the first row of controls.
        self._form.setContentsMargins(12, 10, 0, 0)
        self._form.setVerticalSpacing(6)
        self._body.setVisible(bool(expanded))

        root.addWidget(self._toggle)
        root.addWidget(self._body)

    def form(self) -> QtWidgets.QFormLayout:
        return self._form

    def title(self) -> str:
        return self._title

    def is_expanded(self) -> bool:
        return bool(self._toggle.isChecked())

    def set_expanded(self, expanded: bool):
        expanded = bool(expanded)
        if self._toggle.isChecked() == expanded:
            self._body.setVisible(expanded)
            self._apply_arrow(expanded)
            return
        self._toggle.setChecked(expanded)

    def _apply_arrow(self, expanded: bool):
        self._toggle.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)

    def _on_toggled(self, expanded: bool):
        self._body.setVisible(bool(expanded))
        self._apply_arrow(bool(expanded))
        self.toggled.emit(bool(expanded))



def _enum_radios(options, value, callback, tooltip: str | None = None, parent=None) -> QDataRadioButtonGroup:
    """Horizontal radio group for short fixed enums (HF: prefer over <=4-item combos)."""
    if parent is None:
        parent = Buttons._default_parent
    group = QDataRadioButtonGroup(options, value=value, callback=callback, parent=parent)
    group.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
    layout = group.layout()
    if layout is not None:
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
    if tooltip:
        group.setToolTip(tooltip)
    return group


class OverlayInspector(QtWidgets.QWidget):
    """Property panel for canvas + selected widget."""

    def __init__(self, scene: OverlayScene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self._building = False
        self._edit_ids: list[str] = []
        self._multi = False
        self._live_fields: list = []
        self._rebuild_pending = False
        self._rebuild_armed = False
        self._last_rebuild_ids: list[str] = []
        self._pending_scroll = (0, 0)
        self._scroll_restore_tries = 0
        self._section_collapsed: dict[str, bool] = {}
        self._collapsible_sections: list[CollapsibleSection] = []
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        self._host = QtWidgets.QWidget(self)
        self._form = QtWidgets.QVBoxLayout(self._host)
        self._form.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._host)
        layout.addWidget(scroll)
        self._scroll = scroll
        self.scene.selection_changed.connect(self._on_selection_changed)
        self.scene.changed.connect(self._maybe_rebuild)
        try:
            self.scene.geometry_changed.connect(self._on_geometry_changed)
        except Exception:
            pass
        self.destroyed.connect(self._detach_scene)
        self._canvas_sig = None
        self._identity_hooks = False
        self._bind_identity_hooks()
        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            StreamDeckBridge().devices_changed.connect(self._on_streamdeck_devices_changed)
        except Exception:
            pass
        self.rebuild()

    def _bind_identity_hooks(self):
        if self._identity_hooks:
            return
        try:
            from gremlin.ui import state_device

            sd = state_device.StateData()
            sd.key_changed.connect(self._on_identity_changed)
            sd.crud.connect(self._on_identity_changed)
        except Exception:
            pass
        try:
            el = gremlin.event_handler.EventListener()
            el.mode_name_changed.connect(self._on_identity_changed)
        except Exception:
            pass
        self._identity_hooks = True

    def _on_identity_changed(self, *args):
        if not self._is_alive():
            return
        if getattr(gremlin.shared_state, "profile_loading", False):
            return
        on_ui(self, self.rebuild)

    def _detach_scene(self, *_args):
        listener = getattr(self, "_listen_dialog", None)
        if listener is not None:
            try:
                if Shiboken.isValid(listener):
                    listener.close()
            except Exception:
                pass
            self._listen_dialog = None
        try:
            self.scene.selection_changed.disconnect(self._on_selection_changed)
        except Exception:
            pass
        try:
            self.scene.changed.disconnect(self._maybe_rebuild)
        except Exception:
            pass
        try:
            self.scene.geometry_changed.disconnect(self._on_geometry_changed)
        except Exception:
            pass
        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            StreamDeckBridge().devices_changed.disconnect(self._on_streamdeck_devices_changed)
        except Exception:
            pass
        try:
            from gremlin.ui import state_device

            sd = state_device.StateData()
            sd.key_changed.disconnect(self._on_identity_changed)
            sd.crud.disconnect(self._on_identity_changed)
        except Exception:
            pass
        try:
            el = gremlin.event_handler.EventListener()
            el.mode_name_changed.disconnect(self._on_identity_changed)
        except Exception:
            pass
        self._identity_hooks = False
        self._scroll = None
        self._form = None
        self._host = None

    def _is_alive(self) -> bool:
        try:
            if not alive(self):
                return False
        except Exception:
            return False
        # Detached designers clear _form; ignore late rebuilds from scene signals.
        return getattr(self, "_form", None) is not None

    def _scroll_area(self):
        if not self._is_alive():
            return None
        scroll = getattr(self, "_scroll", None)
        try:
            if scroll is None or not alive(scroll):
                return None
        except Exception:
            return None
        return scroll

    def _on_streamdeck_devices_changed(self):
        if not self._is_alive():
            return
        items = self.scene.selected_widgets()
        if any(canonical_widget_type(item.get("type")) == "streamdeck" for item in items):
            self._schedule_rebuild()

    def _canvas_signature(self):
        canvas = self.scene.canvas
        page = self.scene.active_page() or {}
        return (
            self.scene.active_page_id,
            page.get("name"),
            page.get("visible"),
            page.get("window_x"),
            page.get("window_y"),
            canvas.get("width"),
            canvas.get("height"),
            canvas.get("background_mode"),
            canvas.get("monitor_index"),
            canvas.get("monitor_name"),
            canvas.get("interactive"),
            canvas.get("attach_to_window"),
            canvas.get("attach_window_title"),
            canvas.get("attach_window_exe"),
        )

    def _on_selection_changed(self):
        """Defer rebuild so selection + scene signals coalesce (avoids flash storms)."""
        self._schedule_rebuild()

    def _detach_sink(self) -> QtWidgets.QWidget:
        """Hidden child used to hold widgets being torn down (never top-level)."""
        sink = getattr(self, "_detach_sink_widget", None)
        if sink is None or not alive(sink):
            # Must be a child of the inspector — a parentless QWidget is itself a
            # top-level window and reparenting into it flashes on the canvas.
            sink = QtWidgets.QWidget(self)
            sink.setObjectName("overlayInspectorDetachSink")
            sink.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
            sink.hide()
            sink.setFixedSize(0, 0)
            self._detach_sink_widget = sink
        return sink

    def _discard_widget(self, widget: QtWidgets.QWidget | None):
        if widget is None:
            return
        try:
            widget.blockSignals(True)
            for child in widget.findChildren(QtWidgets.QWidget):
                try:
                    child.blockSignals(True)
                    child.hide()
                except RuntimeError:
                    pass
        except RuntimeError:
            pass
        try:
            widget.hide()
            widget.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
            widget.setParent(self._detach_sink())
            widget.deleteLater()
        except RuntimeError:
            return

    def _own(self, widget: QtWidgets.QWidget | None) -> QtWidgets.QWidget | None:
        """Adopt a freshly created control under the host before it can become a window."""
        if widget is None:
            return None
        host = self._host
        if host is not None and alive(host):
            try:
                if widget.parent() is not host:
                    widget.setParent(host)
            except RuntimeError:
                pass
        return widget

    def _on_geometry_changed(self):
        """Move/resize: update spin boxes only — never rebuild the inspector UI."""
        if not self._is_alive():
            return
        if not gremlin.util.is_ui_thread():
            on_ui(self, self._on_geometry_changed)
            return
        if self._building:
            return
        # Skip live churn during canvas drag — final flush on mouse release catches up.
        if getattr(self.scene, "geometry_gesture", False):
            return
        self._refresh_live_fields()

    def _maybe_rebuild(self):
        if not self._is_alive():
            return
        if not gremlin.util.is_ui_thread():
            on_ui(self, self._maybe_rebuild)
            return
        if self._building:
            # Mark dirty only — the active builder must call _schedule_rebuild()
            # when it clears _building. Setting pending without arming a timer
            # used to make the next _schedule_rebuild() a no-op (mode radios).
            self._rebuild_pending = True
            return
        if self._rebuild_pending and self._rebuild_armed:
            return
        sig = self._canvas_signature()
        if sig != self._canvas_sig:
            self._schedule_rebuild()
            return
        self._refresh_live_fields()

    def _schedule_rebuild(self):
        """Coalesce inspector rebuilds onto the next event-loop tick."""
        self._rebuild_pending = True
        if self._rebuild_armed:
            return
        self._rebuild_armed = True
        later(self, self._run_scheduled_rebuild)

    def _run_scheduled_rebuild(self):
        self._rebuild_armed = False
        if not self._is_alive():
            self._rebuild_pending = False
            return
        if self._building:
            # Still inside a mode/canvas mutation — retry next tick.
            self._schedule_rebuild()
            return
        self._rebuild_pending = False
        try:
            self.rebuild()
        except RuntimeError:
            return

    def _refresh_live_fields(self):
        for fn in list(self._live_fields):
            try:
                fn()
            except RuntimeError:
                continue

    def _bind_live(self, widget, getter):
        def _sync(w=widget, get=getter):
            if not alive(w):
                return
            try:
                value = get()
            except RuntimeError:
                return
            w.blockSignals(True)
            w.setValue(value)
            w.blockSignals(False)

        self._live_fields.append(_sync)

    def _clear(self):
        layout = self._form
        self._collapsible_sections = []
        if layout is None:
            return
        try:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    # Hide + reparent into a hidden sink before deleteLater.
                    # Leaving orphans briefly parentless (or setParent(None)) makes
                    # visible top-level windows flash over the designer canvas.
                    self._discard_widget(widget)
                else:
                    child = item.layout()
                    if child is not None:
                        while child.count():
                            nested = child.takeAt(0)
                            self._discard_widget(nested.widget())
        except RuntimeError:
            return

    def _add_expand_collapse_toolbar(self):
        """Expand all / Collapse all sits above Geometry (and other sections)."""
        if self._form is None:
            return
        row = QtWidgets.QWidget(self._host)
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)
        expand_btn = Buttons.getExpandAllWidget(
            tooltip="Expand every collapsible section in this panel.",
            callback=self._expand_all_sections,
        )
        collapse_btn = Buttons.getCollapseAllWidget(
            tooltip="Collapse every collapsible section in this panel.",
            callback=self._collapse_all_sections,
        )
        layout.addWidget(expand_btn)
        layout.addWidget(collapse_btn)
        layout.addStretch()
        self._form.addWidget(row)

    def _expand_all_sections(self):
        for section in list(self._collapsible_sections):
            try:
                section.set_expanded(True)
                self._section_collapsed[section.title()] = False
            except RuntimeError:
                continue

    def _collapse_all_sections(self):
        for section in list(self._collapsible_sections):
            try:
                section.set_expanded(False)
                self._section_collapsed[section.title()] = True
            except RuntimeError:
                continue

    def _section(self, title: str, collapsible: bool | None = None) -> QtWidgets.QFormLayout:
        """Add a titled section. Geometry stays fixed; all other sections fold."""
        if collapsible is None:
            collapsible = title != "Geometry"
        host = self._host
        if not collapsible:
            box = QtWidgets.QGroupBox(title, host)
            form = QtWidgets.QFormLayout(box)
            form.setLabelAlignment(QtCore.Qt.AlignRight)
            if self._form is not None:
                self._form.addWidget(box)
            return form
        expanded = not bool(self._section_collapsed.get(title, False))
        section = CollapsibleSection(title, expanded=expanded, parent=host)
        section.toggled.connect(lambda on, t=title: self._section_collapsed.__setitem__(t, not bool(on)))
        self._collapsible_sections.append(section)
        if self._form is not None:
            self._form.addWidget(section)
        return section.form()

    def rebuild(self):
        if not self._is_alive():
            return
        if not gremlin.util.is_ui_thread():
            # Scene signals are psygnal (same-thread); bounce off worker threads.
            on_ui(self, self.rebuild)
            return
        if self._building:
            self._rebuild_pending = True
            return
        self._building = True
        self._rebuild_pending = False
        self._live_fields = []
        built_ids = None
        saved_v = 0
        saved_h = 0
        scroll = self._scroll_area()
        if scroll is not None:
            try:
                saved_v = scroll.verticalScrollBar().value()
                saved_h = scroll.horizontalScrollBar().value()
            except RuntimeError:
                saved_v = 0
                saved_h = 0
        host = self._host
        updates_off = False
        prior_button_parent = Buttons._default_parent
        try:
            if self._form is None:
                return
            if host is not None and alive(host):
                host.setUpdatesEnabled(False)
                updates_off = True
            # Parentless Buttons / radios / color chips become top-level HWNDs.
            Buttons._default_parent = host if host is not None and alive(host) else None
            self._canvas_sig = self._canvas_signature()
            self._clear()
            if self._form is None:
                return
            items = self.scene.selected_widgets()
            self._edit_ids = [item["id"] for item in items]
            self._multi = len(items) > 1
            if not items:
                # Canvas / toggle overlay only when nothing is selected.
                self._build_canvas()
                if self._form is None:
                    return
                hint = QtWidgets.QLabel("Select a widget on the canvas, or add one from the palette.", host)
                hint.setWordWrap(True)
                self._form.addWidget(hint)
                self._form.addStretch()
            else:
                if self._form is None:
                    return
                types = {canonical_widget_type(item.get("type")) for item in items}
                if self._multi and len(types) > 1:
                    self._build_mixed(items)
                else:
                    self._build_widget(items[0])
                self._form.addStretch()
            built_ids = list(self._edit_ids)
            self._last_rebuild_ids = built_ids
            # Keep the same vertical position when switching widgets so Appearance /
            # Border / etc. stay in view. Clamped after layout if content is shorter.
            self._pending_scroll = (saved_h, saved_v)
            self._scroll_restore_tries = 0
            later(self, self._restore_inspector_scroll)
        except RuntimeError:
            return
        except Exception:
            syslog.exception("OBS OVERLAY: inspector rebuild failed")
        finally:
            Buttons._default_parent = prior_button_parent
            if updates_off and host is not None and alive(host):
                try:
                    host.setUpdatesEnabled(True)
                except RuntimeError:
                    pass
            self._building = False
        if not self._is_alive():
            return
        current_ids = [item["id"] for item in self.scene.selected_widgets()]
        if self._rebuild_pending or (built_ids is not None and current_ids != built_ids):
            self._rebuild_pending = False
            later(self, self.rebuild)

    def _restore_inspector_scroll(self):
        scroll = self._scroll_area()
        if scroll is None:
            return
        try:
            hx, vy = self._pending_scroll
            hbar = scroll.horizontalScrollBar()
            vbar = scroll.verticalScrollBar()
            if ((vy > vbar.maximum()) or (hx > hbar.maximum())) and self._scroll_restore_tries < 3:
                self._scroll_restore_tries += 1
                later(self, self._restore_inspector_scroll)
                return
            hbar.setValue(min(max(0, int(hx)), hbar.maximum()))
            vbar.setValue(min(max(0, int(vy)), vbar.maximum()))
        except RuntimeError:
            return

    def _build_canvas(self):
        self._add_expand_collapse_toolbar()
        form = self._section("Canvas")
        canvas = self.scene.canvas
        page = self.scene.active_page() or {}
        onscreen = is_onscreen_mode(canvas)

        name = QtWidgets.QLineEdit(str(page.get('name') or ''), self._host)
        name.setToolTip("Name of this overlay page. Shown on the designer tab and in the live window title.")
        # Capture page id so a deferred editingFinished from a destroyed field
        # cannot rename the wrong page after an activate/deactivate rebuild.
        page_id = page.get("id")
        name.editingFinished.connect(
            lambda edit=name, pid=page_id: self._on_page_name(edit.text(), page_id=pid)
        )
        form.addRow("Name", name)

        visible = QtWidgets.QCheckBox(self._host)
        visible.setChecked(bool(page.get("visible", True)))
        visible.setToolTip("When off, this page’s live window is closed. Show overlay still only opens the selected page.")
        visible.toggled.connect(lambda v: self.scene.set_page_visible(bool(v)))
        form.addRow("Visible", visible)

        start = QtWidgets.QCheckBox(self._host)
        start.setChecked(bool(canvas.get("show_on_profile_start")))
        start.toggled.connect(lambda v: self._set_canvas("show_on_profile_start", bool(v)))
        form.addRow("Show at profile start", start)

        interactive = QtWidgets.QCheckBox(self._host)
        interactive.setChecked(bool(canvas.get("interactive")))
        interactive.setToolTip(
            "On this page’s live overlay, touch or click widgets bound to vJoy or GEX states. "
            "Empty space stays click-through. Physical bindings stay display-only."
        )
        interactive.toggled.connect(lambda v: self._set_canvas("interactive", bool(v)))
        form.addRow("Interactive", interactive)
        touch_hint = QtWidgets.QLabel('vJoy buttons are held while pressed. A state button tap inverts the state. Sticks and hats return to center on lift; faders keep their value.', self._host)
        touch_hint.setWordWrap(True)
        form.addRow(touch_hint)

        current = normalize_background_mode(canvas.get("background_mode"))
        mode = _enum_radios(
            [
                ("Windowed", "windowed", "Capture window with a solid background (OBS chromakey / custom size)."),
                ("On-screen", "onscreen", "Transparent HUD sized to a monitor."),
            ],
            current,
            self._on_background_mode,
            tooltip="Live overlay mode for this page.",
            parent=self._host,
        )
        form.addRow("Mode", mode)

        if onscreen:
            screens = list_overlay_screens()
            monitor = QDataComboBox(parent=self._host)
            selected = resolve_overlay_screen(canvas)
            selected_index = selected["index"] if selected else 0
            for screen in screens:
                monitor.addItem(screen["label"], screen["index"])
            if screens:
                pos = monitor.findData(selected_index)
                if pos >= 0:
                    monitor.setCurrentIndex(pos)
            monitor.currentIndexChanged.connect(lambda _i, box=monitor: self._on_monitor(box.currentData()))
            form.addRow("Monitor", monitor)
            if bool(canvas.get("interactive")):
                hint = QtWidgets.QLabel('Canvas size follows this monitor. Interactive is on: widgets capture touch; empty space passes through to the screen behind.', self._host)
            else:
                hint = QtWidgets.QLabel('Canvas size follows this monitor. The overlay is a transparent, click-through HUD.', self._host)
            hint.setWordWrap(True)
            form.addRow(hint)
        else:
            color_btn = ColorButton(
                canvas.get("chroma_color") or "#00FF00",
                parent=self._host,
                preserve_transparent=True,
                allow_gradient=False,
            )
            color_btn.setFixedWidth(36)
            color_btn.setToolTip("Background fill for the windowed overlay. Click for a full color picker.")
            color_btn.color_changed.connect(lambda v: self._set_canvas("chroma_color", v))
            form.addRow("Background color", color_btn)
            form.addRow("Presets", self._windowed_color_presets_row(color_btn))
            color_hint = QtWidgets.QLabel('Use a solid chromakey color for OBS, or Transparent (alpha 0) for a see-through desktop window (frameless). Width and height set the capture window size.', self._host)
            color_hint.setWordWrap(True)
            form.addRow(color_hint)

        width = QtWidgets.QSpinBox(self._host)
        width.setRange(160, 7680)
        width.setValue(int(canvas.get("width") or 1280))
        height = QtWidgets.QSpinBox(self._host)
        height.setRange(120, 4320)
        height.setValue(int(canvas.get("height") or 720))
        width.setEnabled(not onscreen)
        height.setEnabled(not onscreen)
        if not onscreen:
            width.valueChanged.connect(lambda v: self._set_canvas("width", int(v)))
            height.valueChanged.connect(lambda v: self._set_canvas("height", int(v)))
        form.addRow("Width", width)
        form.addRow("Height", height)

        grid = QtWidgets.QSpinBox(self._host)
        grid.setRange(1, 64)
        grid.setValue(int(canvas.get("grid_size") or 8))
        grid.valueChanged.connect(lambda v: self._set_canvas("grid_size", int(v)))
        form.addRow("Grid size", grid)

        snap = QtWidgets.QCheckBox(self._host)
        snap.setChecked(bool(canvas.get("snap_to_grid", True)))
        snap.setToolTip("Snap move/resize to the canvas grid.")
        snap.toggled.connect(lambda v: self._set_canvas("snap_to_grid", v))
        form.addRow("Snap to grid", snap)
        snap_widgets = QtWidgets.QCheckBox(self._host)
        snap_widgets.setChecked(bool(canvas.get("snap_to_widgets", True)))
        snap_widgets.setToolTip(
            "Snap move/resize to other widgets' left/center/right and top/middle/bottom. "
            "A dashed white line shows the match while dragging."
        )
        snap_widgets.toggled.connect(lambda v: self._set_canvas("snap_to_widgets", v))
        form.addRow("Snap to widget", snap_widgets)
        self._build_guides(form, canvas)

        if not onscreen:
            top = QtWidgets.QCheckBox(self._host)
            top.setChecked(bool(canvas.get("always_on_top")))
            top.toggled.connect(lambda v: self._set_canvas("always_on_top", v))
            form.addRow("Always on top", top)

            frameless = QtWidgets.QCheckBox(self._host)
            frameless.setChecked(bool(canvas.get("frameless")))
            frameless.toggled.connect(lambda v: self._set_canvas("frameless", v))
            form.addRow("Frameless", frameless)

            drag = QtWidgets.QCheckBox(self._host)
            drag.setChecked(bool(canvas.get("show_drag_bar", True)))
            drag.toggled.connect(lambda v: self._set_canvas("show_drag_bar", v))
            form.addRow("Overlay drag bar", drag)

        if onscreen:
            attach = QtWidgets.QCheckBox(self._host)
            attach.setChecked(bool(canvas.get("attach_to_window")))
            attach.setToolTip(
                "Parents the live overlay to the chosen window so Discord application share "
                "(and similar window capture) can include it. Screen share already shows a separate overlay. "
                "Use windowed or borderless; exclusive full-screen and some game captures still omit it."
            )
            attach.toggled.connect(lambda v: self._set_canvas("attach_to_window", bool(v)))
            form.addRow("Include in app share", attach)
            if sys.platform == "win32":
                from .app_view import list_application_windows, window_choice_label

                current_title = str(canvas.get("attach_window_title") or "").strip()
                current_exe = str(canvas.get("attach_window_exe") or "").strip()
                box = QDataComboBox(parent=self._host)
                box.setEnabled(bool(canvas.get("attach_to_window")))
                box.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
                box.setMinimumContentsLength(24)
                box.addItem("(none)", ("", ""))
                selected = 0
                from .model import OVERLAY_WINDOW_TITLE

                for window in list_application_windows():
                    title = str(window.get("title") or "")
                    exe = str(window.get("exe") or "")
                    if title.startswith(OVERLAY_WINDOW_TITLE):
                        continue
                    box.addItem(window_choice_label(title, exe), (title, exe))
                    if title == current_title and (not current_exe or exe.casefold() == current_exe.casefold()):
                        selected = box.count() - 1
                if current_title and selected == 0:
                    box.addItem(f"{current_title}  (not running)", (current_title, current_exe))
                    selected = box.count() - 1
                box.setCurrentIndex(selected)

                def _on_attach_window(_index, combo=box):
                    data = combo.currentData() or ("", "")
                    title, exe = data if isinstance(data, tuple) else ("", "")
                    self._set_canvas("attach_window_title", str(title or ""))
                    self._set_canvas("attach_window_exe", str(exe or ""))

                box.currentIndexChanged.connect(_on_attach_window)
                attach.toggled.connect(box.setEnabled)
                form.addRow("Application window", box)
                refresh = Buttons.getRefreshWidget(
                    label="Refresh windows",
                    tooltip="Re-scan visible top-level windows.",
                    callback=lambda _=False: QtCore.QTimer.singleShot(0, self.rebuild),
                )
                form.addRow(refresh)
                hint = QtWidgets.QLabel('Discord application share captures that program only. Pin the overlay inside the game window, then share that game. If the game is not running, the overlay stays a normal window (screen share still works).', self._host)
                hint.setWordWrap(True)
                form.addRow(hint)
            else:
                hint = QtWidgets.QLabel('Pinning the overlay into another application is available on Windows.', self._host)
                hint.setWordWrap(True)
                form.addRow(hint)

        reset = QDataPushButton(
            "Reset position",
            tooltip="Clear the saved window position and center this overlay. Also used if the saved monitor is gone.",
            clicked=lambda: self._reset_page_position(),
        )
        if onscreen:
            reset.setToolTip("Use the primary monitor if the saved display is gone.")
        form.addRow(reset)
        self._build_toggle_binding()
        self._build_runtime_bindings()

    # Standard OBS / capture chromakey colors for Windowed mode quick picks.
    _WINDOWED_COLOR_PRESETS = (
        ("Green", "#00FF00"),
        ("Blue", "#0000FF"),
        ("Magenta", "#FF00FF"),
        ("Cyan", "#00FFFF"),
        ("Red", "#FF0000"),
        ("Black", "#000000"),
        ("White", "#FFFFFF"),
        ("Transparent", "#00000000"),
    )

    def _windowed_color_presets_row(self, color_btn: ColorButton) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget(self._host)
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        def _apply_preset(hex_color: str, button=color_btn):
            button.set_value(hex_color)
            self._set_canvas("chroma_color", hex_color)

        for name, hex_color in self._WINDOWED_COLOR_PRESETS:
            chip = QtWidgets.QToolButton(row)
            chip.setFixedSize(22, 22)
            chip.setAutoRaise(True)
            chip.setCursor(QtCore.Qt.PointingHandCursor)
            chip.setToolTip(f"{name} ({hex_color})")
            fill = qcolor(hex_color)
            if fill.alpha() < 255:
                chip.setStyleSheet(
                    "QToolButton { border: 1px solid #666; border-radius: 3px; "
                    "background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #3a3a3a, stop:0.49 #3a3a3a, "
                    "stop:0.51 #777, stop:1 #777); }"
                )
            else:
                chip.setStyleSheet(
                    f"QToolButton {{ border: 1px solid #666; border-radius: 3px; background: {fill.name()}; }}"
                )
            chip.clicked.connect(lambda _=False, c=hex_color: _apply_preset(c))
            layout.addWidget(chip)
        layout.addStretch(1)
        return row

    def _on_background_mode(self, stored: str):
        if self._building:
            return
        stored = normalize_background_mode(stored)
        previous = normalize_background_mode(self.scene.canvas.get("background_mode"))
        if stored == previous:
            return
        self._building = True
        try:
            if stored == "onscreen" and previous != "onscreen":
                self.scene.canvas["capture_width"] = int(self.scene.canvas.get("width") or 1280)
                self.scene.canvas["capture_height"] = int(self.scene.canvas.get("height") or 720)
                self.scene.canvas["background_mode"] = stored
                if not apply_onscreen_geometry(self.scene):
                    self.scene._dirty = True
                    self.scene.changed.emit()
            elif stored != "onscreen" and previous == "onscreen":
                self.scene.canvas["background_mode"] = stored
                restore_w = int(self.scene.canvas.get("capture_width") or 1280)
                restore_h = int(self.scene.canvas.get("capture_height") or 720)
                self.scene.canvas["width"] = restore_w
                self.scene.canvas["height"] = restore_h
                self.scene._dirty = True
                self.scene.changed.emit()
            else:
                self.scene.canvas["background_mode"] = stored
                self.scene._dirty = True
                self.scene.changed.emit()
        finally:
            self._building = False
        self._schedule_rebuild()

    def _on_monitor(self, index):
        if self._building or index is None:
            return
        self._building = True
        try:
            screens = list_overlay_screens()
            chosen = next((screen for screen in screens if screen["index"] == int(index)), None)
            self.scene.canvas["monitor_index"] = int(index)
            if chosen:
                self.scene.canvas["monitor_name"] = chosen["name"]
            apply_onscreen_geometry(self.scene, monitor_index=int(index))
        finally:
            self._building = False
        self._schedule_rebuild()

    def _set_canvas(self, key, value):
        if self.scene.canvas.get(key) == value:
            return
        self.scene.canvas[key] = value
        self.scene._dirty = True
        self.scene.changed.emit()

    def _on_page_name(self, name: str, page_id: str | None = None):
        if self._building:
            return
        label = str(name).strip()
        if not label:
            return
        self.scene.rename_page(label, page_id)

    def _reset_page_position(self):
        if self._building:
            return
        self.scene.reset_page_position()
        if is_onscreen_mode(self.scene.canvas):
            apply_onscreen_geometry(self.scene)

    def _build_guides(self, form, canvas: dict):
        buttons = QtWidgets.QWidget(self._host)
        row = QtWidgets.QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        add_v = Buttons.getAddWidget(
            label="Add vertical",
            tooltip="Add a vertical guide. Widgets snap left, center, or right to it.",
            callback=lambda _=False: self._add_guide("v"),
        )
        add_h = Buttons.getAddWidget(
            label="Add horizontal",
            tooltip="Add a horizontal guide. Widgets snap top, center, or bottom to it.",
            callback=lambda _=False: self._add_guide("h"),
        )
        row.addWidget(add_v)
        row.addWidget(add_h)
        row.addStretch()
        form.addRow("Guides", buttons)
        hint = QtWidgets.QLabel('Drag a guide on the canvas, or enter a percent of width (vertical) or height (horizontal).', self._host)
        hint.setWordWrap(True)
        form.addRow(hint)
        for guide in canvas.get("guides") or []:
            form.addRow("", self._guide_row(guide))

    def _guide_row(self, guide: dict) -> QtWidgets.QWidget:
        axis = "H" if guide.get("axis") == "h" else "V"
        gid = guide.get("id")
        percent = max(0.0, min(100.0, float(guide.get("position") or 0) * 100.0))
        row = QtWidgets.QWidget(self._host)
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        axis_label = QtWidgets.QLabel(axis, self._host)
        axis_label.setFixedWidth(14)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self._host)
        slider.setRange(0, 1000)
        slider.setValue(int(round(percent * 10)))
        spin = QtWidgets.QDoubleSpinBox(self._host)
        spin.setRange(0.0, 100.0)
        spin.setDecimals(1)
        spin.setSuffix(" %")
        spin.setValue(percent)
        spin.setMaximumWidth(84)
        color = ColorButton(guide.get("color") or DEFAULT_GUIDE_COLOR)
        color.setFixedWidth(36)
        delete = Buttons.getDeleteWidget(tooltip="Remove this guide")
        delete.setFixedWidth(24)

        def _from_slider(v, box=spin, ident=gid):
            pct = v / 10.0
            box.blockSignals(True)
            box.setValue(pct)
            box.blockSignals(False)
            self.scene.update_guide(ident, position=pct / 100.0)

        def _from_spin(v, bar=slider, ident=gid):
            bar.blockSignals(True)
            bar.setValue(int(round(float(v) * 10)))
            bar.blockSignals(False)
            self.scene.update_guide(ident, position=float(v) / 100.0)

        slider.valueChanged.connect(_from_slider)
        spin.valueChanged.connect(_from_spin)
        color.color_changed.connect(lambda v, ident=gid: self.scene.update_guide(ident, color=v))
        delete.clicked.connect(lambda _=False, ident=gid: self._remove_guide(ident))
        self._bind_live(spin, lambda ident=gid: self._guide_percent(ident))
        self._bind_live(slider, lambda ident=gid: int(round(self._guide_percent(ident) * 10)))
        layout.addWidget(axis_label)
        layout.addWidget(slider, 1)
        layout.addWidget(spin)
        layout.addWidget(color)
        layout.addWidget(delete)
        return row

    def _guide_percent(self, guide_id: str) -> float:
        guide = self.scene.guide_by_id(guide_id)
        if not guide:
            return 0.0
        return max(0.0, min(100.0, float(guide.get("position") or 0) * 100.0))

    def _add_guide(self, axis: str):
        if self._building:
            return
        self.scene.add_guide(axis)
        self.rebuild()

    def _remove_guide(self, guide_id: str):
        if self._building:
            return
        self.scene.remove_guide(guide_id)
        self.rebuild()

    def _build_widget(self, item: dict):
        self._add_expand_collapse_toolbar()
        form = self._section("Geometry")
        if self._multi:
            types = sorted({(w.get("type") or "").replace("_", " ") for w in self.scene.selected_widgets()})
            form.addRow("Selection", QtWidgets.QLabel(f'{len(self._edit_ids)} grouped widgets', self._host))
            form.addRow("Types", QtWidgets.QLabel(', '.join(types), self._host))
            group_ids = {
                str(w.get("group") or "").strip()
                for w in self.scene.selected_widgets()
                if str(w.get("group") or "").strip()
            }
            if len(group_ids) == 1:
                gid = next(iter(group_ids))
                name_edit = QtWidgets.QLineEdit(self.scene.group_display_name(gid), self._host)
                name_edit.setToolTip("Name for this widget group (shown in the runtime control panel).")
                name_edit.editingFinished.connect(
                    lambda box=name_edit, group=gid: self.scene.set_group_name(group, box.text().strip())
                )
                form.addRow("Group name", name_edit)
        else:
            type_label = QtWidgets.QLabel(item.get('type', '').replace('_', ' '), self._host)
            form.addRow("Type", type_label)
            name = QtWidgets.QLineEdit(str(item.get('name') or ''), self._host)
            name.setPlaceholderText(widget_display_name({**item, "name": ""}))
            name.setToolTip("Name in the selection pane. The on-screen caption stays under Label.")
            name.editingFinished.connect(lambda wid=item["id"], box=name: self._update(wid, name=box.text().strip()))
            form.addRow("Name", name)
            canvas_w = max(1, int(self.scene.canvas.get("width") or 1280))
            canvas_h = max(1, int(self.scene.canvas.get("height") or 720))
            self._slider_int(
                form,
                "X",
                int(item.get("x") or 0),
                0,
                canvas_w,
                lambda v, wid=item["id"]: self._update(wid, x=int(v)),
            )
            self._slider_int(
                form,
                "Y",
                int(item.get("y") or 0),
                0,
                canvas_h,
                lambda v, wid=item["id"]: self._update(wid, y=int(v)),
            )
        for key, lo, hi in (("w", 8, 4000), ("h", 8, 4000), ("z", -100, 100)):
            spin = QtWidgets.QSpinBox(self._host)
            spin.setRange(lo, hi)
            spin.setValue(int(self._common_field(lambda w: int(w.get(key) or 0), int(item.get(key) or 0))))
            spin.valueChanged.connect(lambda v, k=key, wid=item["id"]: self._update(wid, **{k: int(v)}))
            form.addRow(key.upper(), spin)

        self._rotation_slider(form, item)
        self._lock_position_row(form, item)

        self._build_visibility(item)

        label_form = self._section("Label")
        widget_type = canonical_widget_type(item.get("type"))
        show_mode = widget_type == "label" and bool((item.get("style") or {}).get("show_current_mode"))
        if not self._multi:
            if show_mode:
                from .bindings import current_profile_mode

                label = QtWidgets.QLineEdit(current_profile_mode(), self._host)
                label.setReadOnly(True)
                label.setToolTip("This label follows the active profile mode. Uncheck Show current mode to type your own text.")
            else:
                label = QtWidgets.QLineEdit(item.get('label') or '', self._host)
                label.editingFinished.connect(lambda wid=item["id"], w=label: self._update(wid, label=w.text()))
            label_form.addRow("Text", label)
        if not show_mode:
            self._style_bool(label_form, item, "show_label", "Show label")
        if widget_type == "label":
            mode_box = QtWidgets.QCheckBox(self._host)
            mode_box.setChecked(show_mode)
            mode_box.setToolTip(
                "Replace this label’s text with the profile mode that is currently active. "
                "It updates live when you change edit mode, or when the runtime mode changes while the profile is running."
            )
            mode_box.toggled.connect(lambda v, wid=item["id"]: self._set_show_current_mode(wid, bool(v)))
            label_form.addRow("Show current mode", mode_box)
            if show_mode:
                hint = QtWidgets.QLabel('Updates live: edit mode now, runtime mode while the profile is running.', self._host)
                hint.setWordWrap(True)
                label_form.addRow(hint)
        self._style_label_fonts(label_form, item, widget_type)
        self._slider_int(
            label_form,
            "Label offset X",
            int(item["style"].get("label_offset_x") or 0),
            -400,
            400,
            lambda v, wid=item["id"]: self._style(wid, label_offset_x=int(v)),
        )
        self._slider_int(
            label_form,
            "Label offset Y",
            int(item["style"].get("label_offset_y") or 0),
            -400,
            400,
            lambda v, wid=item["id"]: self._style(wid, label_offset_y=int(v)),
        )
        widget_type = canonical_widget_type(item.get("type"))
        if widget_type == "label":
            self._style_color(label_form, item, "fill", "Fill")
            self._border_appearance(label_form, item)

        look = self._section("Appearance")
        self._build_palettes(look, item)
        self._opacity_slider(look, item)
        if widget_type == "button":
            if button_uses_shape_path(item):
                self._shape_appearance(look, item, for_button=True)
            else:
                shape = _enum_radios(
                    [("Rounded", "rounded"), ("Rect", "rect"), ("Circle", "circle"), ("Pill", "pill")],
                    item["style"].get("shape") or "rounded",
                    lambda v, wid=item["id"]: self._style(wid, shape=v),
                )
                look.addRow("Shape", shape)
                self._style_color(look, item, "fill", "Off fill")
                self._style_color(look, item, "fill_on", "On fill")
            self._style_image_file(look, item, "image_path", "Off image")
            self._style_image_file(look, item, "image_path_on", "On image")
            self._style_bool(
                look,
                item,
                "image_keep_aspect",
                "Keep image aspect",
                tooltip="Fit the off/on image inside the button. Off stretches it to the button size.",
            )
        elif widget_type == "axis_bar":
            self._orientation_combo(look, item)
            self._style_color(look, item, "fill", "Fill")
            self._style_color(look, item, "indicator", "Dot")
            self._style_float(look, item, "indicator_size", "Dot size", 2, 80)
            self._indicator_shape(look, item)
            self._style_bool(look, item, "show_dot_shadow", "Dot shadow")
            self._style_bool(look, item, "show_dot_crosshair", "Lines through dot")
            self._grid_appearance(look, item)
            self._crosshair_appearance(look, item)
        elif widget_type == "axis_radio":
            self._orientation_combo(look, item, default="horizontal")
            steps = QtWidgets.QSpinBox(self._host)
            steps.setRange(2, 32)
            steps.setValue(int(item["style"].get("radio_steps") or 5))
            steps.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, radio_steps=int(v)))
            look.addRow("Steps", steps)
            self._style_color(look, item, "fill", "Off fill")
            self._style_color(look, item, "fill_on", "On fill")
            self._style_bool(look, item, "invert_display", "Invert")
        elif widget_type == "axis_fader":
            self._orientation_combo(look, item)
            self._style_color(look, item, "fill", "Track")
            self._style_color(look, item, "fill_bar", "Fill")
            self._style_color(look, item, "fill_on", "Thumb")
            self._style_color(look, item, "grid", "Rungs")
            steps = QtWidgets.QSpinBox(self._host)
            steps.setRange(3, 32)
            steps.setValue(int(item["style"].get("radio_steps") or 8))
            steps.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, radio_steps=int(v)))
            look.addRow("Rungs", steps)
            thumb = QtWidgets.QDoubleSpinBox(self._host)
            thumb.setRange(0, 80)
            thumb.setSingleStep(1)
            thumb.setSpecialValueText("One rung")
            thumb.setValue(float(item["style"].get("indicator_size") or 0))
            thumb.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, indicator_size=float(v)))
            look.addRow("Thumb size", thumb)
            self._style_bool(look, item, "invert_display", "Invert")
        elif widget_type in ("axis_radial", "axis_dial"):
            self._style_color(look, item, "track", "Track")
            self._style_color(look, item, "fill_bar", "Arc")
            self._style_color(look, item, "grid", "Ticks")
            self._style_float(look, item, "needle_width", "Arc width", 4, 40)
            ticks = QtWidgets.QSpinBox(self._host)
            ticks.setRange(2, 48)
            ticks.setValue(int(item["style"].get("radio_steps") or 11))
            ticks.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, radio_steps=int(v)))
            look.addRow("Ticks", ticks)
            self._style_bool(look, item, "invert_display", "Invert")
        elif widget_type == "axis_encoder":
            self._style_color(look, item, "fill", "Off fill")
            self._style_color(look, item, "fill_on", "On fill")
            self._style_color(look, item, "grid", "Ticks")
            ring = QtWidgets.QDoubleSpinBox(self._host)
            ring.setRange(0, 80)
            ring.setSingleStep(1)
            ring.setSpecialValueText("Auto")
            ring.setValue(float(item["style"].get("needle_width") or 0))
            ring.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, needle_width=float(v)))
            look.addRow("Ring thickness", ring)
            ticks = QtWidgets.QSpinBox(self._host)
            ticks.setRange(4, 48)
            ticks.setValue(int(item["style"].get("radio_steps") or 16))
            ticks.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, radio_steps=int(v)))
            look.addRow("Steps", ticks)
            self._style_bool(look, item, "invert_display", "Invert")
        elif widget_type == "axis_paddle":
            start = QtWidgets.QDoubleSpinBox(self._host)
            start.setRange(-360.0, 360.0)
            start.setDecimals(1)
            start.setSuffix("°")
            start.setValue(float(item["style"].get("paddle_start_deg") or 0.0))
            start.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, paddle_start_deg=float(v)))
            look.addRow("Start angle", start)
            end = QtWidgets.QDoubleSpinBox(self._host)
            end.setRange(-360.0, 360.0)
            end.setDecimals(1)
            end.setSuffix("°")
            end.setValue(float(item["style"].get("paddle_end_deg") or 70.0))
            end.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, paddle_end_deg=float(v)))
            look.addRow("End angle", end)
            cur_dir = normalize_paddle_direction(item["style"].get("paddle_direction"))
            direction = _enum_radios(
                [("Clockwise", "cw"), ("Counter-clockwise", "ccw")],
                cur_dir,
                lambda v, wid=item["id"]: self._style(wid, paddle_direction=v),
            )
            look.addRow("Rotation", direction)
            self._style_color(look, item, "fill", "Off fill")
            self._style_color(look, item, "fill_on", "On fill")
            self._style_color(look, item, "indicator", "Pivot")
            self._style_float(look, item, "indicator_size", "Pivot size", 4, 80)
            path_row = QtWidgets.QWidget(self._host)
            path_layout = QtWidgets.QHBoxLayout(path_row)
            path_layout.setContentsMargins(0, 0, 0, 0)
            path_edit = QtWidgets.QLineEdit(item['style'].get('paddle_image') or '', self._host)
            path_edit.setPlaceholderText("Optional — replaces built-in art (pivot = image center)")
            browse = Buttons.getFolderWidget(tooltip="Browse")
            browse.setFixedWidth(28)
            browse.setToolTip(
                "Choose a custom paddle image. PNG with transparency works best. "
                "Pivot is the center of the image. Clear uses the built-in silhouette from your reference."
            )
            browse.clicked.connect(lambda _=False, wid=item["id"]: self._browse_paddle_image(wid))
            clear = Buttons.getClearWidget(
                label="Clear",
                tooltip="Use the built-in vector paddle.",
                callback=lambda wid=item["id"]: self._style(wid, paddle_image="", rebuild=True),
            )
            path_edit.editingFinished.connect(
                lambda wid=item["id"], w=path_edit: self._style(wid, paddle_image=w.text().strip())
            )
            path_layout.addWidget(path_edit)
            path_layout.addWidget(browse)
            path_layout.addWidget(clear)
            look.addRow("Custom image", path_row)
            self._style_bool(look, item, "invert_display", "Invert")
        elif widget_type in ("axis_stick_square", "axis_stick_circle", "axis_crosshair", "hat"):
            self._style_color(look, item, "fill", "Fill")
            self._style_color(look, item, "indicator", "Dot")
            self._style_float(look, item, "indicator_size", "Dot size", 2, 80)
            if widget_type == "hat":
                current = 8 if int(item["style"].get("hat_positions") or 4) >= 8 else 4
                positions = _enum_radios(
                    [("4-position", 4), ("8-position", 8)],
                    current,
                    lambda v, wid=item["id"]: self._style(wid, hat_positions=int(v or 4)),
                )
                look.addRow("Positions", positions)
                self._crosshair_appearance(look, item, show_toggle=False)
            else:
                self._indicator_shape(look, item)
                self._style_bool(look, item, "show_dot_shadow", "Dot shadow")
                self._style_bool(look, item, "show_dot_crosshair", "Lines through dot")
                if widget_type in ("axis_stick_circle", "axis_crosshair"):
                    self._angle_step_combo(look, item)
                    rings = QtWidgets.QSpinBox(self._host)
                    rings.setRange(1, 8)
                    rings.setValue(int(item["style"].get("ring_count") or 3))
                    rings.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, ring_count=int(v)))
                    look.addRow("Rings", rings)
                self._grid_appearance(look, item)
                self._crosshair_appearance(look, item)
        elif widget_type == "switch_4way":
            self._switch_cardinal_appearance(look, item, include_orientation=False)
        elif widget_type == "switch_2way":
            self._switch_cardinal_appearance(look, item, include_orientation=True)
        elif widget_type == "switch_3way":
            self._orientation_combo(look, item)
            self._style_color(look, item, "fill", "Housing")
            self._style_color(look, item, "fill_on", "Active fill")
        elif widget_type in ("shape", "panel"):
            self._shape_appearance(look, item)
        elif widget_type == "image":
            self._image_appearance(look, item)
        elif widget_type == "application":
            self._application_appearance(look, item)
        elif widget_type == "remote_view":
            self._remote_view_appearance(look, item)
        elif widget_type == "streamdeck":
            self._streamdeck_appearance(look, item)
        elif widget_type == "axis_mouse":
            self._mouse_appearance(look, item)
        elif widget_type == "axis_graph":
            self._graph_appearance(look, item)
        elif widget_type == "axis_bars":
            self._bars_appearance(look, item)
        elif widget_type == "sys_stats":
            self._stats_appearance(look, item)
        elif widget_type == "stopwatch":
            self._stopwatch_appearance(look, item)
        elif widget_type == "input_display":
            self._input_display_appearance(look, item)
        elif widget_type != "label":
            self._style_color(look, item, "fill", "Fill")

        self._append_shared_appearance(look, item, widget_type)
        if widget_uses_series(widget_type) and not self._multi:
            self._build_graph_datasets(item)
        if widget_type == "sys_stats" and not self._multi:
            self._build_stat_datasets(item)
        if widget_type == "input_display" and not self._multi:
            self._build_input_display_keys(item)

    def _build_mixed(self, items: list[dict]):
        types = {item.get("type") for item in items}
        item = items[0]
        self._add_expand_collapse_toolbar()
        form = self._section("Geometry")
        form.addRow("Selection", QtWidgets.QLabel(f'{len(items)} grouped widgets', self._host))
        form.addRow("Types", QtWidgets.QLabel(', '.join(sorted(((t or '').replace('_', ' ') for t in types))), self._host))
        for key, lo, hi in (("w", 8, 4000), ("h", 8, 4000), ("z", -100, 100)):
            spin = QtWidgets.QSpinBox(self._host)
            spin.setRange(lo, hi)
            spin.setValue(int(self._common_field(lambda w, k=key: int(w.get(k) or 0), int(item.get(key) or 0))))
            spin.valueChanged.connect(lambda v, k=key, wid=item["id"]: self._update(wid, **{k: int(v)}))
            form.addRow(key.upper(), spin)
        self._rotation_slider(form, item)
        self._lock_position_row(form, item)
        self._build_visibility(item)

        label_form = self._section("Label")
        self._style_bool(label_form, item, "show_label", "Show label")
        meter_types = {canonical_widget_type(t) for t in types}
        if meter_types <= {"sys_stats", "stopwatch"} and len(meter_types) == 1:
            self._style_label_fonts(label_form, item, next(iter(meter_types)))
        else:
            self._style_font(label_form, item)
            self._style_color(label_form, item, "font_color", "Font color")
        self._slider_int(
            label_form,
            "Label offset X",
            int(item["style"].get("label_offset_x") or 0),
            -400,
            400,
            lambda v, wid=item["id"]: self._style(wid, label_offset_x=int(v)),
        )
        self._slider_int(
            label_form,
            "Label offset Y",
            int(item["style"].get("label_offset_y") or 0),
            -400,
            400,
            lambda v, wid=item["id"]: self._style(wid, label_offset_y=int(v)),
        )

        look = self._section("Appearance")
        if len(types) == 1:
            self._build_palettes(look, item)
        self._opacity_slider(look, item)
        self._style_color(look, item, "fill", "Fill")
        if types <= {"button"}:
            self._style_color(look, item, "fill_on", "On fill")
        if types <= {"switch_4way", "switch_2way", "switch_3way"}:
            self._style_color(look, item, "fill_on", "Active fill")
        if types <= {"switch_4way", "switch_2way"}:
            self._switch_cardinal_appearance(
                look, item, include_orientation=("switch_2way" in types)
            )
        elif types <= {"switch_3way"}:
            self._orientation_combo(look, item)
        if types <= {"axis_bar", "axis_radio", "axis_fader"}:
            self._orientation_combo(look, item)
        if types <= {"axis_stick_circle", "axis_crosshair"}:
            self._angle_step_combo(look, item)
        if types <= {"axis_bar", "axis_stick_square", "axis_stick_circle", "axis_crosshair"}:
            self._style_color(look, item, "indicator", "Dot")
            self._indicator_shape(look, item)
            self._style_bool(look, item, "show_dot_shadow", "Dot shadow")
            self._style_bool(look, item, "show_dot_crosshair", "Lines through dot")
            self._grid_appearance(look, item)
            self._crosshair_appearance(look, item)
        invert_types = {
            "axis_bar",
            "axis_radio",
            "axis_fader",
            "axis_radial",
            "axis_encoder",
            "axis_paddle",
            "axis_dial",
        }
        if types <= invert_types:
            self._style_bool(look, item, "invert_display", "Invert")
        if types <= {"axis_bar"}:
            self._axis_appearance(look, item, self._bar_label_ends(item), invert=False)
        elif types <= {"axis_stick_square", "axis_stick_circle", "axis_crosshair", "hat", "switch_4way"}:
            self._axis_appearance(look, item)
        elif types <= {"switch_2way", "switch_3way"}:
            self._axis_appearance(look, item, "ns")
        if not types.intersection(set(NO_DEADZONE_WIDGET_TYPES)):
            self._deadzone_field(look, item)
        if types <= {"button"}:
            self._border_appearance(look, item, colors=(("border", "Off border"), ("border_on", "On border")))
        elif types <= {"input_display"}:
            self._border_appearance(look, item, colors=(("border", "Off border"), ("border_on", "On border")))
        elif types <= {"axis_radio"}:
            self._border_appearance(look, item, colors=(("border", "Off border"), ("border_on", "Active border")), include_radius=False)
        elif types <= {"switch_2way", "switch_3way", "switch_4way"}:
            self._border_appearance(
                look,
                item,
                colors=(("border", "Off border"), ("border_on", "Active border")),
                include_radius=not types <= {"switch_4way"},
            )
        else:
            include_radius = not types <= set(NO_CORNER_RADIUS_TYPES) and not types <= {"switch_4way"}
            self._border_appearance(look, item, include_radius=include_radius)
        self._style_widget_shadow(look, item)
        self._build_blink(item)

    def _visibility_for(self, item: dict) -> dict:
        return normalize_visibility(item.get("visibility") if isinstance(item.get("visibility"), dict) else default_visibility())

    def _visibility_summary(self, vis: dict) -> str:
        phrases = [self._visibility_condition_phrase(cond) for cond in vis.get("conditions") or []]
        if not phrases:
            return "Always shown on the live overlay (no conditions)."
        expression = str(vis.get("expression") or "").strip()
        if expression:
            return f"Shown when {expression}."
        join = " and " if (vis.get("join") or "all") == "all" else " or "
        return f"If {join.join(phrases)} then display."

    def _visibility_condition_phrase(self, cond: dict) -> str:
        kind = str(cond.get("kind") or "mode").casefold()
        on = str(cond.get("when") or "on").casefold() != "off"
        if kind == "mode":
            _mid, name = resolve_overlay_mode(cond.get("mode_id"), cond.get("mode_name"))
            name = name or str(cond.get("mode_name") or "").strip() or "(pick a mode)"
            return f"mode {name} is {'current' if on else 'not current'}"
        if kind == "state":
            state = find_overlay_state(cond.get("state_id"), cond.get("state_name"))
            name = (state.key if state is not None else str(cond.get("state_name") or "").strip()) or "(pick a state)"
            return f"state {name} is {'on' if on else 'off'}"
        if kind == "keyboard":
            names = []
            for raw in cond.get("keys") or []:
                key = deserialize_overlay_key(raw)
                if key is None:
                    continue
                names.append(gremlin.keyboard.KeyMap.get_name(key) or str(key.name or ""))
            combo = " + ".join(n for n in names if n) or "(pick a key)"
            return f"{combo} is {'pressed' if on else 'released'}"
        try:
            input_id = int(cond.get("input_id") or 0)
        except (TypeError, ValueError):
            input_id = 0
        device = str(cond.get("device_name") or "").strip()
        if kind == "vjoy":
            try:
                vjoy_id = int(cond.get("vjoy_id") or 0)
            except (TypeError, ValueError):
                vjoy_id = 0
            source = f"vJoy {vjoy_id}" if vjoy_id else (device or "vJoy")
        else:
            source = device or "physical"
        button = f"button {input_id}" if input_id else "button (not set)"
        return f"{source} {button} is {'pressed' if on else 'released'}"

    def _build_visibility(self, item: dict):
        vis = self._visibility_for(item)
        form = self._section("Visibility")
        vis_box = QtWidgets.QCheckBox(self._host)
        self._set_bool_widget(
            vis_box,
            [bool(w.get("visible", True)) for w in self.scene.selected_widgets()] or [bool(item.get("visible", True))],
        )
        vis_box.setToolTip("Master switch. Off hides this widget in the designer and on the live overlay.")
        vis_box.stateChanged.connect(lambda _s, wid=item["id"], box=vis_box: self._on_bool(box, wid, field="visible"))
        form.addRow("Visible", vis_box)

        expr = QtWidgets.QLineEdit(self._host)
        expr.setText(str(vis.get("expression") or ""))
        expr.setPlaceholderText("A AND (B OR C)")
        expr.setToolTip(
            "Use letters A, B, C… for the conditions below. Operators: AND, OR, XOR, NAND, NOR, XNOR, NOT, and parentheses. "
            "Leave empty to require every condition (AND)."
        )
        expr.editingFinished.connect(
            lambda wid=item["id"], box=expr: self._set_visibility(wid, expression=box.text())
        )
        preview = QDataPushButton(
            "Preview",
            tooltip="Show a Venn diagram, boolean algebra, and truth table for this expression.",
            clicked=lambda _=False, it=item, box=expr: self._preview_visibility(it, box.text()),
        )
        expr_row = QtWidgets.QWidget(self._host)
        expr_layout = QtWidgets.QHBoxLayout(expr_row)
        expr_layout.setContentsMargins(0, 0, 0, 0)
        expr_layout.addWidget(expr, 1)
        expr_layout.addWidget(preview)
        form.addRow("Expression", expr_row)

        ops = QDataPushButton("Boolean operators", tooltip="Show AND, OR, XOR, NAND, NOR, XNOR, and NOT with gate symbols, Venn diagrams, and truth tables.", clicked=lambda: self._show_boolean_operators())
        form.addRow("", ops)

        hint = QtWidgets.QLabel(self._visibility_summary(vis), self._host)
        hint.setWordWrap(True)
        form.addRow(hint)
        note = QtWidgets.QLabel('Each condition gets a letter (A, B, C…). The live overlay hides the widget when the expression is false. The designer keeps a faded copy so you can still edit it.', self._host)
        note.setWordWrap(True)
        form.addRow(note)

        for cond in vis.get("conditions") or []:
            form.addRow(self._visibility_condition_box(item, cond))

        add_kind = QDataComboBox()
        add_kind.addItem("Mode", "mode")
        add_kind.addItem("State", "state")
        add_kind.addItem("Physical button", "physical")
        add_kind.addItem("vJoy button", "vjoy")
        add_kind.addItem("Keyboard/mouse", "keyboard")
        add_btn = Buttons.getAddWidget(
            label="Add condition",
            tooltip="Add a mode, state, or input. It is assigned the next letter (A, B, C…).",
            callback=lambda wid=item["id"], box=add_kind: self._add_visibility_condition(
                wid, str(box.currentData() or "mode")
            ),
        )
        add_row = QtWidgets.QWidget(self._host)
        add_layout = QtWidgets.QHBoxLayout(add_row)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.addWidget(add_kind, 1)
        add_layout.addWidget(add_btn)
        form.addRow("Add", add_row)

    def _visibility_condition_box(self, item: dict, cond: dict) -> QtWidgets.QGroupBox:
        letter = str(cond.get("letter") or "").strip().upper()
        phrase = self._visibility_condition_phrase(cond)
        box = QtWidgets.QGroupBox(f"{letter} — {phrase}" if letter else phrase, self._host)
        form = QtWidgets.QFormLayout(box)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        cond_id = str(cond.get("id") or "")
        kind = str(cond.get("kind") or "mode").casefold()

        kind_box = QDataComboBox()
        kinds = (
            ("mode", "Mode"),
            ("state", "State"),
            ("physical", "Physical button"),
            ("vjoy", "vJoy button"),
            ("keyboard", "Keyboard/mouse"),
        )
        for value, label in kinds:
            kind_box.addItem(label, value)
        index = kind_box.findData(kind)
        kind_box.setCurrentIndex(index if index >= 0 else 0)
        kind_box.currentIndexChanged.connect(
            lambda _i, combo=kind_box, wid=item["id"], cid=cond_id: self._set_visibility_condition(
                wid, cid, rebuild=True, kind=str(combo.currentData() or "mode")
            )
        )
        form.addRow("If", kind_box)

        when_opts = (
            [("is current", "on"), ("is not current", "off")]
            if kind == "mode"
            else [("is on", "on"), ("is off", "off")]
        )
        when_cur = "off" if str(cond.get("when") or "on").casefold() == "off" else "on"
        when = _enum_radios(
            when_opts,
            when_cur,
            lambda v, wid=item["id"], cid=cond_id: self._set_visibility_condition(wid, cid, when=str(v or "on")),
        )
        form.addRow("When", when)

        if kind == "mode":
            combo = QDataComboBox()
            populate_overlay_mode_combo(combo, cond.get("mode_id"), cond.get("mode_name"))
            combo.currentIndexChanged.connect(
                lambda _i, combo=combo, wid=item["id"], cid=cond_id: self._set_visibility_condition(
                    wid, cid, **{k: v for k, v in overlay_mode_combo_fields(combo).items() if k != "input_type"}
                )
            )
            form.addRow("Mode", combo)
        elif kind == "state":
            combo = QDataComboBox()
            populate_overlay_state_combo(combo, cond.get("state_id"), cond.get("state_name"))
            combo.currentIndexChanged.connect(
                lambda _i, combo=combo, wid=item["id"], cid=cond_id: self._set_visibility_condition(
                    wid, cid, **{k: v for k, v in overlay_state_combo_fields(combo).items() if k != "input_type"}
                )
            )
            form.addRow("State", combo)
        elif kind == "keyboard":
            picker = OverlayKeyCombinationWidget(cond.get("keys") or [])
            picker.keys_changed.connect(
                lambda keys, wid=item["id"], cid=cond_id: self._set_visibility_condition(wid, cid, keys=normalize_overlay_keys(keys))
            )
            form.addRow(picker)
        else:
            self._fill_visibility_input(form, item, cond)

        remove = Buttons.getRemoveWidget(
            label="Remove",
            callback=lambda wid=item["id"], cid=cond_id: self._remove_visibility_condition(wid, cid),
        )
        form.addRow("", remove)
        return box

    def _fill_visibility_input(self, form: QtWidgets.QFormLayout, item: dict, cond: dict):
        kind = str(cond.get("kind") or "physical").casefold()
        cond_id = str(cond.get("id") or "")
        device_box = QDataComboBox()
        if kind == "vjoy":
            for dev in gremlin.joystick_handling.vjoy_devices(connected_only=False) or []:
                device_box.addItem(f"vJoy {dev.vjoy_id} ({dev.name})", int(dev.vjoy_id))
            current = int(cond.get("vjoy_id") or 0)
            for i in range(device_box.count()):
                if int(device_box.itemData(i) or 0) == current:
                    device_box.setCurrentIndex(i)
                    break
        else:
            for dev in self._physical_joystick_devices():
                device_box.addItem(dev.name, str(dev.device_guid))
            current = str(cond.get("device_guid") or "")
            for i in range(device_box.count()):
                guid = str(device_box.itemData(i) or "")
                if guid and guid.casefold() == current.casefold():
                    device_box.setCurrentIndex(i)
                    break

        def _device_changed():
            if not self._is_alive():
                return
            src = "vjoy" if kind == "vjoy" else "physical"
            dev = self._device_from_combo(device_box, src)
            if not dev:
                return
            payload = {"device_name": dev.name, "device_guid": str(dev.device_guid)}
            if kind == "vjoy":
                payload["vjoy_id"] = int(dev.vjoy_id)
            self._set_visibility_condition(item["id"], cond_id, rebuild=True, **payload)

        device_box.currentIndexChanged.connect(_device_changed)
        form.addRow("Device", device_box)

        listen = Buttons.getListenWidget(
            label="Listen...",
            tooltip="Assign from the next physical or vJoy button press",
            # ListenWidget calls callback(button); keep widget dict in defaults.
            callback=lambda _btn=None, it=item, cid=cond_id: self._listen_visibility(it, cid),
        )
        form.addRow("", listen)

        device = self._device_from_combo(device_box, "vjoy" if kind == "vjoy" else "physical")
        id_box = QDataComboBox()
        id_box.addItem("(none)", 0)
        choices = self._input_choices(device, "button")
        try:
            current_id = int(cond.get("input_id") or 0)
        except (TypeError, ValueError):
            current_id = 0
        found = current_id <= 0
        if found:
            id_box.setCurrentIndex(0)
        for button_id, label in choices:
            id_box.addItem(label, button_id)
            if int(button_id) == current_id:
                id_box.setCurrentIndex(id_box.count() - 1)
                found = True
        if not found:
            id_box.addItem(f"Button {current_id}", current_id)
            id_box.setCurrentIndex(id_box.count() - 1)
        id_box.currentIndexChanged.connect(
            lambda _i, wid=item["id"], cid=cond_id, combo=id_box: self._set_visibility_condition(
                wid, cid, input_id=int(combo.currentData() if combo.currentData() is not None else 0)
            )
        )
        form.addRow("Button", id_box)

    def _set_visibility(self, widget_id: str, rebuild: bool = False, **fields):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        vis = self._visibility_for(item)
        vis.update(fields)
        self._update(widget_id, visibility=vis)
        if rebuild:
            self.rebuild()

    def _preview_visibility(self, item: dict, expression_text: str | None = None):
        vis = self._visibility_for(item)
        if expression_text is not None:
            vis["expression"] = str(expression_text)
            self._set_visibility(item["id"], expression=str(expression_text))
        legend = []
        for cond in vis.get("conditions") or []:
            letter = str(cond.get("letter") or "").strip().upper() or "?"
            legend.append((letter, self._visibility_condition_phrase(cond)))
        expression = effective_visibility_expression(vis)
        dialog = VisibilityPreviewDialog(expression, legend, parent=self)
        dialog.exec()

    def _show_boolean_operators(self):
        dialog = BooleanOperatorsDialog(parent=self)
        dialog.exec()

    def _set_visibility_condition(self, widget_id: str, cond_id: str, rebuild: bool = False, **fields):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        vis = self._visibility_for(item)
        updated = False
        for cond in vis.get("conditions") or []:
            if str(cond.get("id") or "") != str(cond_id):
                continue
            cond.update(fields)
            updated = True
            break
        if not updated:
            return
        self._update(widget_id, visibility=vis)
        if rebuild:
            self.rebuild()

    def _add_visibility_condition(self, widget_id: str, kind: str = "mode"):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        self.scene.push_undo()
        vis = self._visibility_for(item)
        vis.setdefault("conditions", []).append(default_visibility_condition(kind))
        vis["conditions"] = assign_condition_letters(vis["conditions"])
        if not str(vis.get("expression") or "").strip():
            letters = [str(c.get("letter") or "") for c in vis["conditions"]]
            vis["expression"] = default_join_expression(letters, "all")
        self._update(widget_id, visibility=vis)
        self.rebuild()

    def _remove_visibility_condition(self, widget_id: str, cond_id: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        vis = self._visibility_for(item)
        next_conditions = [c for c in (vis.get("conditions") or []) if str(c.get("id") or "") != str(cond_id)]
        if len(next_conditions) == len(vis.get("conditions") or []):
            return
        self.scene.push_undo()
        vis["conditions"] = next_conditions
        self._update(widget_id, visibility=vis)
        self.rebuild()

    def _listen_visibility(self, item: dict, cond_id: str):
        def _captured(event):
            if not self._is_alive():
                return
            if event.event_type != InputType.JoystickButton:
                return
            device = gremlin.joystick_handling.getDevice(event.device_guid, show_error=False)
            virtual = bool(getattr(device, "is_virtual", False))
            payload = {
                "kind": "vjoy" if virtual else "physical",
                "device_guid": str(event.device_guid),
                "device_name": device.name if device else str(event.device_guid),
                "vjoy_id": int(getattr(device, "vjoy_id", 0) or 0),
                "input_id": int(event.identifier),
            }
            self._set_visibility_condition(item["id"], cond_id, rebuild=True, **payload)

        previous = getattr(self, "_listen_dialog", None)
        if previous is not None:
            try:
                if Shiboken.isValid(previous):
                    previous.close()
            except Exception:
                pass
            self._listen_dialog = None
        listener = gremlin.ui.ui_common.InputListenerWidget([InputType.JoystickButton], callback=_captured, parent=self)
        self._listen_dialog = listener
        listener.show()

    def _common_field(self, getter, fallback=None):
        items = self.scene.selected_widgets()
        if not items:
            return fallback
        values = [getter(w) for w in items]
        if all(v == values[0] for v in values):
            return values[0]
        return fallback

    def _set_bool_widget(self, box: QtWidgets.QCheckBox, values: list[bool]):
        if len(values) > 1 and not all(v == values[0] for v in values):
            box.setTristate(True)
            box.setCheckState(QtCore.Qt.PartiallyChecked)
        else:
            box.setChecked(bool(values[0]) if values else False)

    def _on_bool(self, box: QtWidgets.QCheckBox, widget_id: str, field: str | None = None, style_key: str | None = None):
        if self._building:
            return
        if box.isTristate() and box.checkState() == QtCore.Qt.PartiallyChecked:
            return
        box.setTristate(False)
        value = box.isChecked()
        if field:
            self._update(widget_id, **{field: value})
        elif style_key:
            self._style(widget_id, **{style_key: value})

    def _bar_label_ends(self, item: dict) -> str | None:
        items = self.scene.selected_widgets() if self._multi else [item]
        vertical = []
        for widget in items:
            orient = ((widget.get("style") or {}).get("orientation") or "vertical").casefold()
            vertical.append(orient != "horizontal")
        if vertical and all(vertical):
            return "ns"
        if vertical and not any(vertical):
            return "ew"
        return "all"

    def _axis_label_fields(self, form, item, ends: str | None = "all"):
        self._style_bool(form, item, "show_axis_labels", "Axis labels")
        pairs = (
            ("axis_label_n", "North"),
            ("axis_label_s", "South"),
            ("axis_label_e", "East"),
            ("axis_label_w", "West"),
        )
        if ends == "ns":
            pairs = pairs[:2]
        elif ends == "ew":
            pairs = pairs[2:]
        for key, title in pairs:
            edit = QtWidgets.QLineEdit(item['style'].get(key) or '', self._host)
            edit.editingFinished.connect(lambda wid=item["id"], k=key, w=edit: self._style(wid, **{k: w.text()}))
            form.addRow(title, edit)
        spread = item["style"].get("axis_label_spread")
        self._slider_int(
            form,
            "Distance from center",
            100 if spread is None else int(spread),
            0,
            100,
            lambda v, wid=item["id"]: self._style(wid, axis_label_spread=int(v)),
            tooltip="How far N/S/E/W labels sit from the center. 100 places them near the border with even padding.",
        )
        self._style_font(form, item, prefix="axis_label_")
        self._style_color(form, item, "axis_label_font_color", "Axis label color")

    def _orientation_combo(self, form, item, default="vertical"):
        current = item["style"].get("orientation") or default
        orient = _enum_radios(
            [("Vertical", "vertical"), ("Horizontal", "horizontal")],
            current,
            lambda v, wid=item["id"]: self._set_orientation(wid, v),
        )
        form.addRow("Orientation", orient)

    def _switch_cardinal_appearance(self, form, item, include_orientation: bool = False):
        opts = [("Arrows", "arrows"), ("Arcs", "arcs")]
        if item.get("type") == "switch_2way" or include_orientation:
            opts.append(("Bars", "bars"))
        current = normalize_switch_appearance(item["style"].get("switch_appearance"))
        if current not in {o[1] for o in opts}:
            current = "arrows"
        appearance = _enum_radios(
            opts,
            current,
            lambda v, wid=item["id"]: self._style(
                wid, switch_appearance=str(v or "arrows"), rebuild=True
            ),
        )
        form.addRow("Style", appearance)
        if include_orientation:
            self._orientation_combo(form, item)
        self._style_color(form, item, "fill", "Inactive")
        self._style_color(form, item, "fill_on", "Active")
        self._style_color(form, item, "indicator", "Center")
        self._style_float(form, item, "indicator_size", "Center size", 10, 100)

    def _set_orientation(self, widget_id: str, orientation: str):
        if self._building:
            return
        ids = list(self._edit_ids or [widget_id])
        self.scene._suspend += 1
        try:
            for wid in ids:
                item = self.scene.widget_by_id(wid)
                if not item:
                    continue
                previous = (item["style"].get("orientation") or "vertical")
                fields = {"style": {"orientation": orientation}}
                if previous != orientation:
                    width, height = int(item["w"]), int(item["h"])
                    vertical = orientation != "horizontal"
                    if vertical and width > height:
                        fields["w"], fields["h"] = height, width
                    elif not vertical and height > width:
                        fields["w"], fields["h"] = height, width
                self.scene.apply_widget_update(wid, **fields)
        finally:
            self.scene._suspend = max(0, self.scene._suspend - 1)
            self.scene._dirty = True
            self.scene._emit()
        self.rebuild()

    def _indicator_shape(self, form, item):
        shape = _enum_radios(
            [("Circle", "circle"), ("Square", "square")],
            item["style"].get("indicator_shape") or "circle",
            lambda v, wid=item["id"]: self._style(wid, indicator_shape=v),
        )
        form.addRow("Dot shape", shape)

    def _angle_step_combo(self, form, item):
        current = int(item["style"].get("angle_step") or 0)
        if current not in (0, 15, 30, 45):
            current = 0
        combo = _enum_radios(
            [("Off", 0), ("15°", 15), ("30°", 30), ("45°", 45)],
            current,
            lambda v, wid=item["id"]: self._style(wid, angle_step=int(v)),
        )
        form.addRow("Angle lines", combo)

    def _rotation_slider(self, form, item: dict):
        # Primary widget is the displayed angle so mixed member angles still edit coherently.
        rotation = int(round(widget_rotation_deg(item)))
        if self._multi:
            common = self._common_field(lambda w: widget_rotation_deg(w), None)
            if common is not None:
                rotation = int(round(common))
        last = {"value": rotation}
        primary_id = item.get("id")
        # Fixed pivot + start geoms for the gesture — incremental AABB pivots spiral groups.
        gesture: dict[str, Any] = {"geoms": None, "pivot": None, "base": float(rotation)}

        def _capture_gesture():
            ids = [wid for wid in (self._edit_ids or [primary_id]) if wid]
            geoms: dict[str, dict[str, float]] = {}
            bounds = None
            for wid in ids:
                live = self.scene.widget_by_id(wid)
                if not live:
                    continue
                geoms[str(wid)] = {
                    "x": float(live.get("x") or 0),
                    "y": float(live.get("y") or 0),
                    "w": float(live.get("w") or 1),
                    "h": float(live.get("h") or 1),
                    "rotation": widget_rotation_deg(live),
                }
                rect = widget_rotated_bounds(live)
                bounds = rect if bounds is None else bounds.united(rect)
            if not geoms or bounds is None:
                gesture["geoms"] = None
                gesture["pivot"] = None
                return
            gesture["geoms"] = geoms
            gesture["pivot"] = bounds.center()
            gesture["base"] = float(last["value"])

        def _end_gesture():
            gesture["geoms"] = None
            gesture["pivot"] = None
            self.scene.end_geometry_gesture()

        def _on_rotation(value):
            if self._building:
                return
            value = int(value)
            ids = [wid for wid in (self._edit_ids or [primary_id]) if wid]
            if len(ids) <= 1:
                last["value"] = value
                if ids:
                    self._update(ids[0], rotation=value)
                return
            if gesture["geoms"] is None or gesture["pivot"] is None:
                _capture_gesture()
            geoms = gesture.get("geoms")
            pivot = gesture.get("pivot")
            if not geoms or pivot is None:
                return
            last["value"] = value
            delta = float(value) - float(gesture["base"])
            items = [self.scene.widget_by_id(wid) for wid in geoms]
            items = [it for it in items if it]
            self.scene.begin_geometry_gesture()
            apply_group_rotation_delta(items, geoms, pivot.x(), pivot.y(), delta)
            self.scene._dirty = True
            self.scene._emit_geometry()

        def _live():
            # External canvas edits invalidate an in-progress inspector gesture snapshot.
            if gesture["geoms"] is not None and getattr(self.scene, "geometry_gesture", False):
                pass
            elif gesture["geoms"] is not None:
                gesture["geoms"] = None
                gesture["pivot"] = None
            live = self.scene.widget_by_id(primary_id) if primary_id else None
            if live is None:
                live = self.scene.primary_selection()
            if self._multi:
                common = self._common_field(lambda w: widget_rotation_deg(w), None)
                current = int(round(common if common is not None else widget_rotation_deg(live)))
            else:
                current = int(round(widget_rotation_deg(live)))
            last["value"] = current
            return current

        slider, spin = self._slider_int(
            form,
            "Rotation",
            rotation,
            -180,
            180,
            _on_rotation,
            tooltip=(
                "Degrees clockwise. 0 is upright. "
                "With a group selected, the whole group turns around its center "
                "(same as dragging the round handle on the canvas; hold Shift to snap to 15°)."
            ),
            suffix="°",
            live_getter=_live,
            return_widgets=True,
        )
        if slider is not None:
            slider.sliderPressed.connect(_capture_gesture)
            slider.sliderReleased.connect(_end_gesture)
        if spin is not None:
            spin.editingFinished.connect(_end_gesture)

    def _slider_int(
        self,
        form,
        title: str,
        value: int,
        lo: int,
        hi: int,
        on_change,
        tooltip=None,
        suffix=None,
        live_getter=None,
        return_widgets: bool = False,
    ):
        value = int(value)
        lo, hi = int(lo), int(hi)
        if hi < lo:
            lo, hi = hi, lo
        if value < lo:
            lo = value
        if value > hi:
            hi = value
        row = QtWidgets.QWidget(self._host)
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self._host)
        slider.setRange(lo, hi)
        slider.setValue(value)
        spin = QtWidgets.QSpinBox(self._host)
        spin.setRange(lo, hi)
        spin.setValue(value)
        spin.setMaximumWidth(88)
        if suffix:
            spin.setSuffix(suffix)
        if tooltip:
            row.setToolTip(tooltip)
            slider.setToolTip(tooltip)
            spin.setToolTip(tooltip)

        def _from_slider(v, box=spin, cb=on_change):
            if not alive(box):
                return
            box.blockSignals(True)
            box.setValue(v)
            box.blockSignals(False)
            cb(v)

        def _from_spin(v, bar=slider, cb=on_change):
            if not alive(bar):
                return
            bar.blockSignals(True)
            bar.setValue(v)
            bar.blockSignals(False)
            cb(v)

        slider.valueChanged.connect(_from_slider)
        spin.valueChanged.connect(_from_spin)
        layout.addWidget(slider, 1)
        layout.addWidget(spin, 0)
        form.addRow(title, row)
        if live_getter is not None:
            def _sync(bar=slider, box=spin, get=live_getter):
                if not alive(bar) or not alive(box):
                    return
                try:
                    current = int(get())
                except (TypeError, ValueError, RuntimeError):
                    return
                bar.blockSignals(True)
                box.blockSignals(True)
                bar.setValue(current)
                box.setValue(current)
                bar.blockSignals(False)
                box.blockSignals(False)

            self._live_fields.append(_sync)
        if return_widgets:
            return slider, spin
        return None, None

    def _build_palettes(self, form, item: dict):
        widget_type = palette_type(item.get("type"))
        form.addRow("Default palettes", self._palette_swatch_row(widget_type, list_builtin_palettes(widget_type), editable=False))
        form.addRow("User palettes", self._palette_swatch_row(widget_type, list_user_palettes(widget_type), editable=True, add_new=True))

    def _palette_swatch_row(self, widget_type: str, palettes: list, editable: bool, add_new: bool = False) -> QtWidgets.QWidget:
        host = QtWidgets.QWidget(self._host)
        layout = QtWidgets.QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for pal in palettes:
            swatch = PaletteSwatch(pal.get("colors") or {}, pal.get("label") or "Saved palette", editable=editable)
            swatch.apply_requested.connect(lambda p=pal: self._apply_palette(p))
            if editable:
                swatch.update_requested.connect(lambda pid=pal.get("id"): self._update_saved_palette(widget_type, pid))
                swatch.delete_requested.connect(lambda pid=pal.get("id"): self._delete_saved_palette(widget_type, pid))
            layout.addWidget(swatch)
        if add_new:
            add_btn = Buttons.getAddWidget(
                label="+",
                tooltip="Save the current colors as a new user palette for this widget type.",
                callback=lambda: self._add_saved_palette(widget_type),
            )
            add_btn.setFixedSize(28, 28)
            layout.addWidget(add_btn)
        layout.addStretch()
        return host

    def _current_palette_colors(self) -> dict:
        items = self.scene.selected_widgets()
        if not items:
            return extract_colors({}, "button")
        item = items[0]
        return extract_colors(item.get("style") or {}, item.get("type"))

    def _apply_palette(self, palette: dict):
        colors = palette.get("colors") or {}
        payload = {key: colors[key] for key in COLOR_KEYS if key in colors}
        if not payload or not self._edit_ids:
            return
        self._style(self._edit_ids[0], **payload)
        self.rebuild()

    def _add_saved_palette(self, widget_type: str):
        add_palette(widget_type, self._current_palette_colors())
        self.rebuild()

    def _update_saved_palette(self, widget_type: str, palette_id: str):
        if not palette_id or palette_id in BUILTIN_IDS:
            return
        update_palette(widget_type, palette_id, self._current_palette_colors())
        self.rebuild()

    def _delete_saved_palette(self, widget_type: str, palette_id: str):
        if not palette_id or palette_id in BUILTIN_IDS:
            return
        delete_palette(widget_type, palette_id)
        self.rebuild()

    def _look_heading(self, form: QtWidgets.QFormLayout, title: str):
        label = QtWidgets.QLabel(title, self._host)
        label.setStyleSheet("font-weight: bold; padding-top: 8px;")
        form.addRow(label)

    def _opacity_slider(self, form, item: dict):
        raw = (item.get("style") or {}).get("opacity")
        try:
            value = 100 if raw is None else int(round(float(raw) * 100.0))
        except (TypeError, ValueError):
            value = 100
        value = max(0, min(100, value))
        self._slider_int(
            form,
            "Opacity",
            value,
            0,
            100,
            lambda v, wid=item["id"]: self._style(wid, opacity=max(0.0, min(1.0, float(v) / 100.0))),
            tooltip="Widget opacity (percent).",
        )

    def _deadzone_field(self, form, item: dict):
        dead = QtWidgets.QDoubleSpinBox(self._host)
        dead.setRange(0.0, 0.9)
        dead.setSingleStep(0.01)
        dead.setValue(float(item["style"].get("deadzone") or 0))
        dead.setToolTip("Overlay only: axis values inside this range around center are drawn as zero. Does not change GEX mappings.")
        dead.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, deadzone=float(v)))
        form.addRow("Deadzone display", dead)

    def _axis_appearance(self, form, item: dict, ends: str | None = "all", invert: bool = False):
        self._look_heading(form, "Axis")
        if invert:
            self._style_bool(form, item, "invert_display", "Invert display")
        self._axis_label_fields(form, item, ends)

    def _border_appearance(self, form, item: dict, colors=None, include_radius: bool = True):
        self._look_heading(form, "Border")
        style = item.get("style") or {}
        enabled = border_is_enabled(style)
        dependents: list[QtWidgets.QWidget] = []

        toggle = _enum_radios(
            [("On", "on"), ("Off", "off")],
            "on" if enabled else "off",
            None,
        )
        form.addRow("Border", toggle)

        color_keys = list(colors) if colors else [("border", "Color")]
        for key, title in color_keys:
            values = [(w.get("style") or {}).get(key) for w in self.scene.selected_widgets()] or [style.get(key)]
            same = all(v == values[0] for v in values)
            btn = ColorButton(values[0] or "#ffffff")
            if not same:
                btn.setToolTip("Multiple values — pick a color to apply to all")
            btn.color_changed.connect(lambda v, wid=item["id"], k=key: self._style(wid, **{k: v}))
            form.addRow(title, btn)
            dependents.append(btn)

        width = QtWidgets.QDoubleSpinBox(self._host)
        width.setRange(0, 20)
        width.setSingleStep(0.5)
        try:
            width.setValue(float(style.get("border_width") if style.get("border_width") is not None else 2.0))
        except (TypeError, ValueError):
            width.setValue(2.0)
        width.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, border_width=float(v)))
        form.addRow("Border width", width)
        dependents.append(width)

        if include_radius:
            # Corner radius shapes the fill as well — leave it usable when the stroke is off.
            self._style_float(form, item, "corner_radius", "Corner radius", 0, 200)

        def _sync(on: bool):
            _set_form_rows_visible(form, dependents, on)

        def _on_toggle(value, wid=item["id"]):
            on = str(value or "on") == "on"
            fields: dict = {"border_enabled": on}
            if on:
                try:
                    current = float((self.scene.widget_by_id(wid) or item).get("style", {}).get("border_width") or 0)
                except (TypeError, ValueError, AttributeError):
                    current = 0.0
                if current <= 0:
                    fields["border_width"] = 2.0
                    width.blockSignals(True)
                    width.setValue(2.0)
                    width.blockSignals(False)
            self._style(wid, **fields)
            _sync(on)

        toggle._callback = _on_toggle
        _sync(enabled)

    def _append_shared_appearance(self, look, item: dict, widget_type: str):
        axis_label_types = {"axis_bar", "axis_stick_square", "axis_stick_circle", "axis_crosshair", "hat", "switch_4way"}
        if widget_type in axis_label_types:
            ends = self._bar_label_ends(item) if widget_type == "axis_bar" else "all"
            self._axis_appearance(look, item, ends, invert=widget_type == "axis_bar")
        elif widget_type in ("switch_2way", "switch_3way"):
            ends = "ew" if (item.get("style") or {}).get("orientation") == "horizontal" else "ns"
            self._axis_appearance(look, item, ends, invert=False)
        if widget_type not in NO_DEADZONE_WIDGET_TYPES:
            self._deadzone_field(look, item)
        if widget_type == "button":
            self._border_appearance(look, item, colors=(("border", "Off border"), ("border_on", "On border")))
        elif widget_type == "input_display":
            self._border_appearance(look, item, colors=(("border", "Off border"), ("border_on", "On border")))
        elif widget_type == "axis_radio":
            self._border_appearance(
                look,
                item,
                colors=(("border", "Off border"), ("border_on", "Active border")),
                include_radius=False,
            )
        elif widget_type in ("switch_2way", "switch_3way", "switch_4way"):
            self._border_appearance(
                look,
                item,
                colors=(("border", "Off border"), ("border_on", "Active border")),
                include_radius=widget_type != "switch_4way",
            )
        elif widget_type == "remote_view":
            self._border_appearance(look, item)
        elif widget_type not in ("label", "shape", "panel", "image", "application", "streamdeck"):
            include_radius = widget_type not in NO_CORNER_RADIUS_TYPES
            self._border_appearance(look, item, include_radius=include_radius)
        self._style_widget_shadow(look, item)
        if widget_type not in NO_BINDING_WIDGET_TYPES and not self._multi:
            self._build_binding(item)
        self._build_blink(item)

    def _lock_position_row(self, form, item: dict):
        lock_box = QtWidgets.QCheckBox(self._host)
        self._set_bool_widget(
            lock_box,
            [bool(w.get("locked")) for w in self.scene.selected_widgets()] or [bool(item.get("locked"))],
        )
        lock_box.setToolTip("Lock position and size. The widget can still be selected and restyled.")
        lock_box.stateChanged.connect(lambda _s, wid=item["id"], box=lock_box: self._on_bool(box, wid, field="locked"))
        form.addRow("Lock position", lock_box)

    def _blink_for(self, item: dict) -> dict:
        from .blink import normalize_blink

        return normalize_blink(item.get("blink"))

    def _set_blink(self, widget_id: str, rebuild: bool = False, **fields):
        if self._building:
            return
        from .blink import normalize_blink

        ids = list(self._edit_ids or [widget_id])
        self.scene._suspend += 1
        try:
            for wid in ids:
                item = self.scene.widget_by_id(wid)
                if not item:
                    continue
                blink = normalize_blink(item.get("blink"))
                blink.update(fields)
                self.scene.apply_widget_update(wid, blink=normalize_blink(blink))
        finally:
            self.scene._suspend = max(0, self.scene._suspend - 1)
            self.scene._dirty = True
            self.scene._emit()
        if rebuild:
            self.rebuild()

    def _build_blink(self, item: dict):
        from .blink import blink_is_armed

        blink = self._blink_for(item)
        form = self._section("Blinking")
        hint = QtWidgets.QLabel('Off by default. While blinking, the widget swaps Off and On appearance. Check one or more triggers. Temporary runs for the duration after a trigger; Permanent keeps blinking while the condition holds.', self._host)
        hint.setWordWrap(True)
        form.addRow(hint)

        def _box(key, title, tooltip):
            box = QtWidgets.QCheckBox(self._host)
            values = [bool((w.get("blink") or {}).get(key)) for w in self.scene.selected_widgets()] or [bool(blink.get(key))]
            self._set_bool_widget(box, values)
            box.setToolTip(tooltip)
            box.stateChanged.connect(
                lambda _s, wid=item["id"], k=key, b=box: self._on_blink_flag(b, wid, k)
            )
            form.addRow(title, box)

        _box("off_to_on", "Off → On", "Blink when the widget turns on.")
        _box("on_to_off", "On → Off", "Blink when the widget turns off.")
        _box("while_on", "While on", "Blink for as long as the widget is on.")
        _box("while_off", "While off", "Blink for as long as the widget is off.")
        _box("state", "GEX state", "Blink while a Joystick Gremlin Ex state is on or off.")

        state_row = QtWidgets.QWidget(self._host)
        state_layout = QtWidgets.QHBoxLayout(state_row)
        state_layout.setContentsMargins(0, 0, 0, 0)
        state_combo = QDataComboBox()
        populate_overlay_state_combo(state_combo, blink.get("state_id"), blink.get("state_name"))
        state_combo.setEnabled(bool(blink.get("state")))
        state_combo.currentIndexChanged.connect(
            lambda _i, box=state_combo, wid=item["id"]: self._set_blink(
                wid, **{k: v for k, v in overlay_state_combo_fields(box).items() if k in ("state_id", "state_name")}
            )
        )
        when_cur = "off" if str(blink.get("state_when") or "on") == "off" else "on"
        when = _enum_radios(
            [("is on", "on"), ("is off", "off")],
            when_cur,
            lambda v, wid=item["id"]: self._set_blink(wid, state_when=str(v or "on")),
        )
        when.setEnabled(bool(blink.get("state")))
        state_layout.addWidget(state_combo, 1)
        state_layout.addWidget(when)
        form.addRow("State", state_row)

        mode = _enum_radios(
            [
                ("Permanent", "permanent", "Blink for as long as the condition holds."),
                ("Temporary", "temporary", "Blink for a fixed time after the trigger."),
            ],
            "temporary" if blink.get("mode") == "temporary" else "permanent",
            None,
        )
        form.addRow("Duration mode", mode)
        dur = QtWidgets.QDoubleSpinBox(self._host)
        dur.setRange(0.1, 30.0)
        dur.setSingleStep(0.1)
        dur.setSuffix(" s")
        dur.setValue(float(blink.get("duration_s") or 1.0))
        dur.setToolTip("How long a temporary blink lasts after Off→On, On→Off, or a matching state change.")
        dur.valueChanged.connect(lambda v, wid=item["id"]: self._set_blink(wid, duration_s=float(v)))
        form.addRow("Temporary for", dur)

        def _sync_temporary_enabled(value=None, spin=dur):
            if value is None:
                value = "temporary" if blink.get("mode") == "temporary" else "permanent"
            spin.setEnabled(str(value or "permanent") == "temporary")

        def _on_duration_mode(value, wid=item["id"]):
            self._set_blink(wid, mode=str(value or "permanent"))
            _sync_temporary_enabled(value)

        mode._callback = _on_duration_mode
        _sync_temporary_enabled()

        hz = QtWidgets.QDoubleSpinBox(self._host)
        hz.setRange(0.2, 12.0)
        hz.setSingleStep(0.1)
        hz.setSuffix(" Hz")
        hz.setValue(float(blink.get("hz") or 2.0))
        hz.setToolTip("How many times per second the off/on appearance swaps.")
        hz.valueChanged.connect(lambda v, wid=item["id"]: self._set_blink(wid, hz=float(v)))
        form.addRow("Frequency", hz)
        if not blink_is_armed(blink):
            note = QtWidgets.QLabel('No blink triggers are on.', self._host)
            note.setWordWrap(True)
            form.addRow(note)

    def _on_blink_flag(self, box: QtWidgets.QCheckBox, widget_id: str, key: str):
        if self._building:
            return
        if box.isTristate() and box.checkState() == QtCore.Qt.PartiallyChecked:
            return
        box.setTristate(False)
        self._set_blink(widget_id, rebuild=key == "state", **{key: box.isChecked()})

    def _grid_appearance(self, form, item: dict):
        self._look_heading(form, "Grid")
        self._style_bool(form, item, "show_grid", "Show grid")
        self._style_color(form, item, "grid", "Grid")
        self._style_float(form, item, "grid_width", "Line width", 0.5, 12)
        self._style_bool(
            form,
            item,
            "grid_fade",
            "Fade at border",
            tooltip="Keep the grid full strength in the center and fade it toward the widget border.",
        )

    def _crosshair_appearance(self, form, item: dict, show_toggle: bool = True):
        self._look_heading(form, "Crosshairs")
        if show_toggle:
            self._style_bool(form, item, "show_center_line", "Show crosshairs")
        self._style_color(form, item, "crosshair", "Crosshair")

    def _shape_appearance(self, form, item: dict, for_button: bool = False):
        kind = QDataComboBox()
        current = normalize_shape_kind(item["style"].get("shape_kind"))
        for stored, label in shape_kind_choices():
            kind.addItem(label, stored)
            tip = shape_kind_tooltip(stored)
            if tip:
                kind.setItemData(kind.count() - 1, tip, QtCore.Qt.ToolTipRole)
        index = kind.findData(current)
        if index < 0 and current:
            kind.addItem(current, current)
            index = kind.count() - 1
        if index >= 0:
            kind.setCurrentIndex(index)
        kind.setToolTip(shape_kind_tooltip(current))
        kind.currentIndexChanged.connect(lambda _i, box=kind, wid=item["id"]: self._set_shape_kind(wid, box.currentData()))
        form.addRow("Shape", kind)
        self._style_bool(
            form,
            item,
            "shape_closed",
            "Closed",
            tooltip="Connect the last point back to the first. Off for an open line or path.",
        )
        if current == "freeform" or is_custom_kind(current):
            hint = QtWidgets.QLabel(shape_kind_tooltip(current) + ' Dragging a handle past the widget edge grows the shape. Delete removes the selected point.', self._host)
            hint.setWordWrap(True)
            hint.setToolTip(hint.text())
            form.addRow(hint)
        if for_button:
            self._style_color(form, item, "fill", "Off fill")
            self._style_color(form, item, "fill_on", "On fill")
            return
        self._style_color(form, item, "fill", "Fill")
        self._border_appearance(form, item, include_radius=(current == "rectangle"))

    def _image_appearance(self, form, item: dict):
        path_row = QtWidgets.QWidget(self._host)
        path_layout = QtWidgets.QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_edit = QtWidgets.QLineEdit(item['style'].get('image_path') or '', self._host)
        browse = Buttons.getFolderWidget(tooltip="Browse")
        browse.setFixedWidth(28)
        browse.setToolTip("Choose an image or SVG file.")
        browse.clicked.connect(lambda _=False, wid=item["id"]: self._browse_image(wid))
        paste = Buttons.getPasteWidget(
            tooltip="Paste a screenshot from the clipboard (Windows Snipping Tool / Win+Shift+S).",
            callback=lambda wid=item["id"]: self._paste_image(wid),
        )
        path_edit.editingFinished.connect(lambda wid=item["id"], w=path_edit: self._style(wid, image_path=w.text()))
        path_layout.addWidget(path_edit)
        path_layout.addWidget(browse)
        path_layout.addWidget(paste)
        form.addRow("Image", path_row)
        self._style_bool(
            form,
            item,
            "image_keep_aspect",
            "Keep aspect ratio",
            tooltip="Fit the picture inside the widget. Off stretches it to the widget size.",
        )
        hint = QtWidgets.QLabel('PNG, WebP, GIF, and SVG keep transparency. SVG is vector (Illustrator-friendly) and stays sharp at any size. Fill is only a backdrop behind those pixels. JPEG has no alpha.', self._host)
        hint.setWordWrap(True)
        form.addRow(hint)
        self._style_color(form, item, "fill", "Fill")
        self._border_appearance(form, item, include_radius=False)
        from .app_view import list_application_windows, window_choice_label

        style = item.get("style") or {}
        current_title = str(style.get("window_title") or "").strip()
        current_exe = str(style.get("window_exe") or "").strip()
        windows = list_application_windows()
        box = QDataComboBox()
        box.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        box.setMinimumContentsLength(24)
        box.addItem("(none)", ("", ""))
        selected = 0
        for window in windows:
            title = str(window.get("title") or "")
            exe = str(window.get("exe") or "")
            box.addItem(window_choice_label(title, exe), (title, exe))
            if title == current_title and (not current_exe or exe.casefold() == current_exe.casefold()):
                selected = box.count() - 1
        if current_title and selected == 0:
            box.addItem(f"{current_title}  (not running)", (current_title, current_exe))
            selected = box.count() - 1
        box.setCurrentIndex(selected)

        def _on_window_chosen(_index, combo=box, wid=item["id"]):
            data = combo.currentData() or ("", "")
            title, exe = data if isinstance(data, tuple) else ("", "")
            self._style(wid, window_title=str(title or ""), window_exe=str(exe or ""))

        box.currentIndexChanged.connect(_on_window_chosen)
        form.addRow("Application", box)
        def _on_refresh_windows():
            QtCore.QTimer.singleShot(0, self.rebuild)

        refresh = Buttons.getRefreshWidget(
            label="Refresh windows",
            tooltip="Re-scan visible top-level windows.",
            callback=_on_refresh_windows,
        )
        form.addRow(refresh)
        hint = QtWidgets.QLabel('Shows a live picture of the selected window. The match is stored by window title (and process name when available) so it can reconnect after a restart. Some exclusive full-screen games cannot be captured.', self._host)
        hint.setWordWrap(True)
        form.addRow(hint)
        self._style_bool(
            form,
            item,
            "image_keep_aspect",
            "Keep aspect ratio",
            tooltip="Fit the captured window inside the widget. Off stretches it to the widget size.",
        )
        self._style_color(form, item, "fill", "Fill")
        self._border_appearance(form, item)

    def _remote_view_appearance(self, form, item: dict):
        from gremlin.remote_video import RemoteVideoHub

        style = item.get("style") or {}
        try:
            current_id = int(style.get("remote_client_id") or 0)
        except (TypeError, ValueError):
            current_id = 0
        client_box = QDataComboBox()
        client_box.addItem("(none)", 0)
        for cid, label, video in RemoteVideoHub().feed_clients():
            mark = " ●" if video else ""
            client_box.addItem(f"{label}{mark}", cid)
        idx = client_box.findData(current_id)
        client_box.setCurrentIndex(idx if idx >= 0 else 0)
        client_box.currentIndexChanged.connect(
            lambda _i, box=client_box, wid=item["id"]: self._style(wid, remote_client_id=int(box.currentData() or 0))
        )
        form.addRow("Remote client", client_box)
        def _on_refresh_clients():
            try:
                import gremlin.remote

                gremlin.remote.remote_client.requestIdentify()
            except Exception:
                pass
            # Defer rebuild — destroying this button mid-click hard-crashes Qt.
            QtCore.QTimer.singleShot(0, self.rebuild)

        refresh = Buttons.getRefreshWidget(
            label="Refresh clients",
            tooltip="Re-scan identified remote peers (run Identify from Remote Control if the list is empty).",
            callback=_on_refresh_clients,
        )
        form.addRow(refresh)
        hint = QtWidgets.QLabel('Clients must enable Remote Control → Video return. Dot (●) means the peer advertised a video port. Master connects to that peer over TCP (default 6013).', self._host)
        hint.setWordWrap(True)
        form.addRow(hint)
        self._style_bool(
            form,
            item,
            "image_keep_aspect",
            "Keep aspect ratio",
            tooltip="Fit the remote picture inside the widget. Off stretches to the widget size.",
        )
        self._style_color(form, item, "fill", "Fill")
        # Border controls come from _append_shared_appearance.

    def _mouse_appearance(self, form, item: dict):
        style = item.get("style") or {}
        current = normalize_mouse_mode(style.get("mouse_mode"))
        mode = _enum_radios(
            [("VJoy", "vjoy"), ("Standard", "standard")],
            current,
            lambda v, wid=item["id"]: self._on_mouse_mode(wid, str(v or "vjoy")),
        )
        form.addRow("Mode", mode)
        try:
            max_px = int(float(style.get("mouse_max") or 250))
        except (TypeError, ValueError):
            max_px = 250
        self._slider_int(
            form,
            "Max displacement",
            max_px,
            20,
            2000,
            lambda v, wid=item["id"]: self._style(wid, mouse_max=int(v)),
            tooltip="Screen pixels that map to a full-length arrow (VJoy) or the pad edge (Standard).",
        )
        if current == "standard":
            idle = QtWidgets.QDoubleSpinBox(self._host)
            idle.setRange(0.0, 10.0)
            idle.setSingleStep(0.1)
            idle.setDecimals(1)
            idle.setSuffix(" s")
            idle.setSpecialValueText("Off")
            try:
                idle.setValue(float(style.get("mouse_idle_s") if style.get("mouse_idle_s") is not None else 1.0))
            except (TypeError, ValueError):
                idle.setValue(1.0)
            idle.setToolTip("Return the mouse to the center after this much time with no movement. Off keeps the last position.")
            idle.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, mouse_idle_s=float(v)))
            form.addRow("Recenter after", idle)
        self._style_color(form, item, "fill", "Fill")
        self._style_color(form, item, "indicator", "Arrow / mouse")
        if current == "vjoy":
            self._style_float(form, item, "needle_width", "Arrow width", 1, 16, step=0.5)
        else:
            self._style_float(form, item, "indicator_size", "Mouse size", 10, 80)
            self._style_bool(form, item, "show_dot_shadow", "Shadow")
        self._grid_appearance(form, item)
        self._crosshair_appearance(form, item)

    def _graph_appearance(self, form, item: dict):
        style = item.get("style") or {}
        self._style_color(form, item, "fill", "Fill")
        period = QtWidgets.QDoubleSpinBox(self._host)
        period.setRange(0.5, 120.0)
        period.setSingleStep(0.5)
        period.setDecimals(1)
        period.setSuffix(" s")
        try:
            period.setValue(float(style.get("period_s") or 8.0))
        except (TypeError, ValueError):
            period.setValue(8.0)
        period.setToolTip("How much history the graph keeps on screen.")
        period.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, period_s=float(v)))
        form.addRow("Period", period)
        vmin = QtWidgets.QDoubleSpinBox(self._host)
        vmin.setRange(-10000.0, 10000.0)
        vmin.setDecimals(3)
        vmin.setSingleStep(0.1)
        try:
            vmin.setValue(float(style.get("value_min") if style.get("value_min") is not None else -1.0))
        except (TypeError, ValueError):
            vmin.setValue(-1.0)
        vmin.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, value_min=float(v)))
        form.addRow("Min", vmin)
        vmax = QtWidgets.QDoubleSpinBox(self._host)
        vmax.setRange(-10000.0, 10000.0)
        vmax.setDecimals(3)
        vmax.setSingleStep(0.1)
        try:
            vmax.setValue(float(style.get("value_max") if style.get("value_max") is not None else 1.0))
        except (TypeError, ValueError):
            vmax.setValue(1.0)
        vmax.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, value_max=float(v)))
        form.addRow("Max", vmax)
        unit = QtWidgets.QLineEdit(str(style.get('unit') or ''), self._host)
        unit.setPlaceholderText("%  °  or leave blank")
        unit.setToolTip("Shown next to the min / mid / max labels on the left.")
        unit.editingFinished.connect(lambda wid=item["id"], w=unit: self._style(wid, unit=w.text()))
        form.addRow("Unit", unit)
        self._style_bool(form, item, "show_legend", "Show legend")
        self._grid_appearance(form, item)

    def _bars_appearance(self, form, item: dict):
        from .model import bars_value_range

        style = item.get("style") or {}
        self._orientation_combo(form, item)
        self._style_color(form, item, "fill", "Fill")
        auto = QtWidgets.QCheckBox(self._host)
        auto.setChecked(bool(style.get("range_auto", True)))
        auto.setToolTip("Use −100…+100 when any selected axis is centered; 0…100 when every axis is 0–100%.")
        auto.toggled.connect(lambda v, wid=item["id"]: self._style(wid, rebuild=True, range_auto=bool(v)))
        form.addRow("Auto range", auto)
        vmin, vmax = bars_value_range(item)
        lo = QtWidgets.QDoubleSpinBox(self._host)
        lo.setRange(-10000.0, 10000.0)
        lo.setDecimals(1)
        lo.setSuffix(" %")
        lo.setValue(float(style.get("value_min") if style.get("value_min") is not None else vmin))
        lo.setEnabled(not bool(style.get("range_auto", True)))
        lo.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, value_min=float(v)))
        form.addRow("Min", lo)
        hi = QtWidgets.QDoubleSpinBox(self._host)
        hi.setRange(-10000.0, 10000.0)
        hi.setDecimals(1)
        hi.setSuffix(" %")
        hi.setValue(float(style.get("value_max") if style.get("value_max") is not None else vmax))
        hi.setEnabled(not bool(style.get("range_auto", True)))
        hi.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, value_max=float(v)))
        form.addRow("Max", hi)
        if bool(style.get("range_auto", True)):
            note = QtWidgets.QLabel(f'Current scale: {vmin:g} to {vmax:g} %', self._host)
            note.setWordWrap(True)
            form.addRow(note)
        self._style_bool(form, item, "show_legend", "Show legend")
        self._grid_appearance(form, item)

    def _stats_appearance(self, form, item: dict):
        style = item.get("style") or {}
        self._style_color(form, item, "fill", "Fill")
        self._orientation_combo(form, item)
        clock_cur = "12h" if str(style.get("time_format") or "24h").casefold() in ("12h", "12", "ampm") else "24h"
        clock = _enum_radios(
            [("24-hour", "24h"), ("12-hour", "12h")],
            clock_cur,
            lambda v, wid=item["id"]: self._style(wid, time_format=str(v or "24h")),
        )
        form.addRow("Time format", clock)
        unit_cur = "F" if str(style.get("temp_unit") or "C").casefold() == "f" else "C"
        unit = _enum_radios(
            [("Celsius", "C"), ("Fahrenheit", "F")],
            unit_cur,
            lambda v, wid=item["id"]: self._style(wid, temp_unit=str(v or "C")),
        )
        form.addRow("Temperature", unit)
        self._style_bool(form, item, "show_caption", "Show stat names")
        hint = QtWidgets.QLabel('Add one or more stats in Datasets, each with its own color. FPS is in-game (MSI Afterburner / RTSS). A Manual counter increments and decrements from keybinds.', self._host)
        hint.setWordWrap(True)
        form.addRow(hint)

    def _stats_for(self, item: dict) -> list[dict]:
        return normalize_stat_series(item.get("stats"), (item.get("style") or {}).get("stat") or "time")

    def _build_stat_datasets(self, item: dict):
        form = self._section("Datasets")
        hint = QtWidgets.QLabel('Each dataset is one value on this counter. Pick a color per row. Remove all but one if you only need a single reading.', self._host)
        hint.setWordWrap(True)
        form.addRow(hint)
        stats = self._stats_for(item)
        for index, entry in enumerate(stats):
            form.addRow(self._stat_entry_box(item, entry, index))
        add = Buttons.getAddWidget(
            label="Add stat",
            callback=lambda wid=item["id"]: self._add_stat_entry(wid),
        )
        form.addRow(add)

    def _stat_entry_box(self, item: dict, entry: dict, index: int) -> QtWidgets.QGroupBox:
        from .sys_stats import STAT_CHOICES, normalize_stat, stat_caption

        kind = normalize_stat(entry.get("stat"))
        title = str(entry.get("label") or "").strip() or stat_caption(kind)
        box = QtWidgets.QGroupBox(f'{index + 1}. {title}', self._host)
        form = QtWidgets.QFormLayout(box)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        sid = str(entry.get("id") or "")
        combo = QDataComboBox()
        for key, label in STAT_CHOICES:
            combo.addItem(label, key)
        found = combo.findData(kind)
        combo.setCurrentIndex(found if found >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _i, c=combo, wid=item["id"], ident=sid: self._set_stat_entry(
                wid, ident, rebuild=True, stat=str(c.currentData() or "time")
            )
        )
        form.addRow("Stat", combo)
        color = ColorButton(entry.get("color") or GRAPH_SERIES_COLORS[index % len(GRAPH_SERIES_COLORS)])
        color.color_changed.connect(lambda v, wid=item["id"], ident=sid: self._set_stat_entry(wid, ident, color=v))
        form.addRow("Color", color)
        label = QtWidgets.QLineEdit(str(entry.get('label') or ''), self._host)
        label.setPlaceholderText(stat_caption(kind))
        label.editingFinished.connect(lambda wid=item["id"], ident=sid, w=label: self._set_stat_entry(wid, ident, label=w.text()))
        form.addRow("Caption", label)
        if kind == "manual":
            step = QtWidgets.QSpinBox(self._host)
            step.setRange(1, 100)
            step.setValue(int(entry.get("step") or 1))
            step.valueChanged.connect(lambda v, wid=item["id"], ident=sid: self._set_stat_entry(wid, ident, step=int(v)))
            form.addRow("Step", step)
            fake = {
                "id": f"stat:{item['id']}:{sid}",
                "type": "button",
                "binding": entry.get("binding"),
                "binding_y": entry.get("binding_y"),
                "binding_z": entry.get("binding_z"),
            }
            self._build_channel(
                fake,
                "binding",
                "Increment",
                force_type="button",
                extra_hint="Press adds Step to the counter. Keyboard/mouse, physical, vJoy, state, or mode.",
                form=form,
            )
            self._build_channel(
                fake,
                "binding_y",
                "Decrement",
                force_type="button",
                allow_none=True,
                show_clear=True,
                extra_hint="Optional. Press subtracts Step (not below zero).",
                form=form,
            )
            self._build_channel(
                fake,
                "binding_z",
                "Reset",
                force_type="button",
                allow_none=True,
                show_clear=True,
                extra_hint="Optional. Press sets the counter to 0.",
                form=form,
            )
        if len(self._stats_for(item)) > 1:
            remove = Buttons.getRemoveWidget(
                label="Remove",
                callback=lambda wid=item["id"], ident=sid: self._remove_stat_entry(wid, ident),
            )
            form.addRow("", remove)
        return box

    def _set_stat_entry(self, widget_id: str, stat_id: str, rebuild: bool = False, **fields):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        stats = self._stats_for(item)
        updated = False
        for entry in stats:
            if str(entry.get("id") or "") != str(stat_id):
                continue
            entry.update(fields)
            updated = True
            break
        if not updated:
            return
        self._update(widget_id, stats=stats)
        if rebuild:
            self.rebuild()

    def _add_stat_entry(self, widget_id: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        self.scene.push_undo()
        stats = self._stats_for(item)
        stats.append(default_stat_entry(len(stats), "cpu"))
        self._update(widget_id, stats=stats)
        self.rebuild()

    def _remove_stat_entry(self, widget_id: str, stat_id: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        stats = [entry for entry in self._stats_for(item) if str(entry.get("id") or "") != str(stat_id)]
        if not stats:
            return
        self.scene.push_undo()
        self._update(widget_id, stats=stats)
        self.rebuild()

    def _bind_stat(self, widget_id: str, stat_id: str, channel: str, rebuild: bool = False, **fields):
        if self._building:
            return
        if (fields.get("source") or "").casefold() == "vjoy" and not int(fields.get("vjoy_id") or 0):
            devices = gremlin.joystick_handling.vjoy_devices(connected_only=False) or []
            if devices:
                fields["vjoy_id"] = int(devices[0].vjoy_id)
                fields.setdefault("device_guid", str(devices[0].device_guid))
                fields.setdefault("device_name", devices[0].name)
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        stats = self._stats_for(item)
        updated = False
        for entry in stats:
            if str(entry.get("id") or "") != str(stat_id):
                continue
            binding = normalize_toggle_binding(entry.get(channel))
            binding.update(fields)
            entry[channel] = normalize_toggle_binding(binding)
            updated = True
            break
        if not updated:
            return
        self._update(widget_id, stats=stats)
        if rebuild:
            self.rebuild()

    def _stopwatch_appearance(self, form, item: dict):
        from .stopwatch_track import normalize_stopwatch_face, normalize_stopwatch_format

        style = item.get("style") or {}
        self._style_color(form, item, "fill", "Fill")
        face = _enum_radios(
            [("Digital", "digital"), ("Analog", "analog")],
            normalize_stopwatch_face(style.get("stopwatch_face")),
            lambda v, wid=item["id"]: self._style(wid, rebuild=True, stopwatch_face=str(v or "digital")),
        )
        form.addRow("Display", face)
        fmt = _enum_radios(
            [("mm:ss", "mmss"), ("hh:mm:ss", "hhmmss")],
            normalize_stopwatch_format(style.get("stopwatch_format")),
            lambda v, wid=item["id"]: self._style(wid, stopwatch_format=str(v or "mmss")),
        )
        form.addRow("Format", fmt)
        if normalize_stopwatch_face(style.get("stopwatch_face")) == "analog":
            self._look_heading(form, "Hour needle")
            self._style_color(form, item, "needle_hour_color", "Color")
            self._style_float(form, item, "needle_hour_width", "Width", 0.5, 16, step=0.5)
            self._style_bool(form, item, "needle_hour_arrow", "Arrow at tip")
            self._look_heading(form, "Minute needle")
            self._style_color(form, item, "needle_minute_color", "Color")
            self._style_float(form, item, "needle_minute_width", "Width", 0.5, 16, step=0.5)
            self._style_bool(form, item, "needle_minute_arrow", "Arrow at tip")
            self._look_heading(form, "Second needle")
            self._style_color(form, item, "needle_second_color", "Color")
            self._style_float(form, item, "needle_second_width", "Width", 0.5, 16, step=0.5)
            self._style_bool(form, item, "needle_second_arrow", "Arrow at tip")

    def _input_display_appearance(self, form, item: dict):
        from .input_display import MOUSE_GRAPHIC_CHOICES, normalize_mouse_graphic

        style = item.get("style") or {}
        self._style_color(form, item, "fill", "Off fill")
        self._style_color(form, item, "fill_on", "On fill")
        self._style_bool(form, item, "show_keyboard", "Show keyboard")
        self._style_bool(form, item, "show_mouse", "Show mouse")
        current = normalize_mouse_graphic(style.get("mouse_graphic"))
        graphic = _enum_radios(
            [(label, key) for key, label in MOUSE_GRAPHIC_CHOICES],
            current,
            lambda v, wid=item["id"]: self._style(wid, mouse_graphic=str(v or "silhouette")),
            tooltip="Silhouette is a top-down mouse. Button map labels every mouse button (M1–M5, wheel, tilt).",
        )
        form.addRow("Mouse graphic", graphic)

    def _build_input_display_keys(self, item: dict):
        from .input_display import PRESET_CHOICES, matching_preset

        form = self._section("Keys")
        hint = QtWidgets.QLabel('Presets match common streaming layouts. Select keys… opens the same virtual keyboard as Map to Keyboard/Mouse Ex. Only selected keys and mouse buttons are drawn.', self._host)
        hint.setWordWrap(True)
        form.addRow(hint)
        preset = QDataComboBox()
        current = matching_preset(item)
        for key, label in PRESET_CHOICES:
            preset.addItem(label, key)
        index = preset.findData(current)
        preset.setCurrentIndex(index if index >= 0 else preset.findData("custom"))
        preset.currentIndexChanged.connect(
            lambda _i, box=preset, wid=item["id"]: self._apply_input_display_preset(wid, str(box.currentData() or "custom"))
        )
        form.addRow("Preset", preset)
        count = QtWidgets.QLabel(f"{len(item.get('keys') or [])} selected", self._host)
        form.addRow("Selection", count)
        select = gremlin.ui.ui_common.QIconPushButton("Select keys...")
        select.setIcon(gremlin.util.load_icon("mdi.keyboard-settings-outline", qta_color=gremlin.ui.ui_common.Color.listenColor()))
        select.setToolTip("Choose keys and mouse buttons on the virtual keyboard.")
        select.setFixedHeight(24)
        select.clicked.connect(lambda _=False, wid=item["id"]: self._open_input_display_picker(wid))
        form.addRow(select)
        all_btn = QDataPushButton("Select all", clicked=lambda wid=item["id"]: self._select_all_input_display_keys(wid))
        none_btn = QDataPushButton("Deselect all", clicked=lambda wid=item["id"]: self._clear_input_display_keys(wid))
        row = gremlin.ui.ui_common.getHContainer([all_btn, none_btn], widget_only=True)
        form.addRow(row)

    def _apply_input_display_preset(self, widget_id: str, preset: str):
        from .input_display import normalize_input_preset, preset_keys, preset_mouse_graphic

        if self._building:
            return
        preset = normalize_input_preset(preset)
        if preset == "custom":
            self._style(widget_id, input_preset="custom")
            return
        self.scene.apply_widget_update(
            widget_id,
            keys=preset_keys(preset),
            style={"input_preset": preset, "mouse_graphic": preset_mouse_graphic(preset)},
        )
        self.rebuild()

    def _select_all_input_display_keys(self, widget_id: str):
        from .input_display import all_picker_key_names, keys_from_names

        if self._building:
            return
        self.scene.apply_widget_update(widget_id, keys=keys_from_names(all_picker_key_names()), style={"input_preset": "all"})
        self.rebuild()

    def _clear_input_display_keys(self, widget_id: str):
        if self._building:
            return
        self.scene.apply_widget_update(widget_id, keys=[], style={"input_preset": "custom"})
        self.rebuild()

    def _open_input_display_picker(self, widget_id: str):
        from .input_display import OverlayInputDisplayPicker, overlay_keys_from_item

        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        gremlin.shared_state.push_suspend_ui_keyinput()
        dialog = OverlayInputDisplayPicker(sequence=list(overlay_keys_from_item(item)), parent=self.window())
        dialog.accepted.connect(lambda: self._apply_input_display_picker_keys(widget_id, dialog.keys))
        dialog.closed.connect(self._input_display_picker_closed)
        dialog.setModal(True)
        self._input_display_dialog = dialog
        dialog.showNormal()

    def _apply_input_display_picker_keys(self, widget_id: str, keys):
        from .input_display import matching_preset
        from .model import normalize_overlay_keys, serialize_overlay_key

        serialized = []
        for key in keys or []:
            if isinstance(key, dict):
                serialized.append(key)
            else:
                serialized.append(serialize_overlay_key(key))
        serialized = normalize_overlay_keys(serialized)
        self.scene.apply_widget_update(
            widget_id,
            keys=serialized,
            style={"input_preset": matching_preset({"keys": serialized})},
        )
        self.rebuild()

    def _input_display_picker_closed(self):
        self._input_display_dialog = None
        try:
            gremlin.shared_state.pop_suspend_ui_keyinput()
        except Exception:
            pass

    def _series_for(self, item: dict) -> list[dict]:
        return normalize_graph_series(item.get("series"))

    def _build_graph_datasets(self, item: dict):
        form = self._section("Datasets")
        if item.get("type") == "axis_bars":
            hint = QtWidgets.QLabel('Each dataset is one physical or vJoy axis. Pick Centered (−100 to +100) or 0 to 100% per axis. Bar colors match the graph. Auto range uses negatives only when a centered axis is selected.', self._host)
        else:
            hint = QtWidgets.QLabel('Each dataset is one physical or vJoy axis. Colors match the plot and legend.', self._host)
        hint.setWordWrap(True)
        form.addRow(hint)
        series = self._series_for(item)
        for index, entry in enumerate(series):
            form.addRow(self._graph_series_box(item, entry, index))
        add = Buttons.getAddWidget(
            label="Add dataset",
            callback=lambda wid=item["id"]: self._add_graph_series(wid),
        )
        form.addRow(add)

    def _graph_series_box(self, item: dict, series: dict, index: int) -> QtWidgets.QGroupBox:
        from .graph_track import graph_series_label

        box = QtWidgets.QGroupBox(graph_series_label(series), self._host)
        form = QtWidgets.QFormLayout(box)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        series_id = str(series.get("id") or "")
        src = str(series.get("source") or "physical").casefold()
        if src not in ("physical", "vjoy"):
            src = "physical"
        source = _enum_radios(
            [("Physical", "physical"), ("vJoy", "vjoy")],
            src,
            lambda v, wid=item["id"], sid=series_id: self._set_graph_series(
                wid, sid, rebuild=True, source=str(v or "physical")
            ),
        )
        form.addRow("Source", source)

        device_box = QDataComboBox()
        if src == "vjoy":
            for dev in gremlin.joystick_handling.vjoy_devices(connected_only=False) or []:
                device_box.addItem(f"vJoy {dev.vjoy_id} ({dev.name})", int(dev.vjoy_id))
            current = int(series.get("vjoy_id") or 0)
            for i in range(device_box.count()):
                if int(device_box.itemData(i) or 0) == current:
                    device_box.setCurrentIndex(i)
                    break
        else:
            for dev in self._physical_joystick_devices():
                device_box.addItem(dev.name, str(dev.device_guid))
            current_guid = str(series.get("device_guid") or "")
            for i in range(device_box.count()):
                guid = str(device_box.itemData(i) or "")
                if guid and guid.casefold() == current_guid.casefold():
                    device_box.setCurrentIndex(i)
                    break

        def _device_changed():
            if not self._is_alive():
                return
            combo_src = "vjoy" if src == "vjoy" else "physical"
            dev = self._device_from_combo(device_box, combo_src)
            if not dev:
                return
            payload = {"device_name": dev.name, "device_guid": str(dev.device_guid)}
            if src == "vjoy":
                payload["vjoy_id"] = int(dev.vjoy_id)
            self._set_graph_series(item["id"], series_id, rebuild=True, **payload)

        device_box.currentIndexChanged.connect(_device_changed)
        form.addRow("Device", device_box)

        listen = Buttons.getListenWidget(
            label="Listen...",
            tooltip="Assign from the next matching physical or vJoy axis",
            # ListenWidget calls callback(button); keep widget dict in defaults.
            callback=lambda _btn=None, it=item, sid=series_id: self._listen_graph_series(it, sid),
        )
        form.addRow("", listen)

        device = self._device_from_combo(device_box, "vjoy" if src == "vjoy" else "physical")
        id_box = QDataComboBox()
        id_box.addItem("(none)", 0)
        choices = self._input_choices(device, "axis")
        try:
            current_id = int(series.get("input_id") or 0)
        except (TypeError, ValueError):
            current_id = 0
        found = current_id <= 0
        if found:
            id_box.setCurrentIndex(0)
        for axis_id, label in choices:
            id_box.addItem(label, axis_id)
            if int(axis_id) == current_id:
                id_box.setCurrentIndex(id_box.count() - 1)
                found = True
        if not found:
            id_box.addItem(f"Axis {current_id}", current_id)
            id_box.setCurrentIndex(id_box.count() - 1)
        id_box.currentIndexChanged.connect(
            lambda _i, wid=item["id"], sid=series_id, combo=id_box: self._set_graph_series(
                wid, sid, rebuild=True, input_id=int(combo.currentData() if combo.currentData() is not None else 0)
            )
        )
        form.addRow("Axis", id_box)

        color = ColorButton(series.get("color") or GRAPH_SERIES_COLORS[index % len(GRAPH_SERIES_COLORS)])
        color.color_changed.connect(lambda v, wid=item["id"], sid=series_id: self._set_graph_series(wid, sid, color=v))
        form.addRow("Color", color)

        label = QtWidgets.QLineEdit(str(series.get('label') or ''), self._host)
        label.setPlaceholderText("Legend name (optional)")
        label.editingFinished.connect(
            lambda wid=item["id"], sid=series_id, w=label: self._set_graph_series(wid, sid, rebuild=True, label=w.text())
        )
        form.addRow("Name", label)

        inv = QtWidgets.QCheckBox(self._host)
        inv.setChecked(bool(series.get("invert")))
        inv.toggled.connect(lambda v, wid=item["id"], sid=series_id: self._set_graph_series(wid, sid, invert=bool(v)))
        form.addRow("Invert", inv)

        if item.get("type") == "axis_bars":
            current_mode = normalize_series_range_mode(series.get("range_mode") or series.get("centered"))
            range_box = _enum_radios(
                [
                    ("Auto", "auto"),
                    ("Centered", "centered", "−100 to +100"),
                    ("0–100%", "unipolar"),
                ],
                current_mode,
                lambda v, wid=item["id"], sid=series_id: self._set_graph_series(
                    wid, sid, rebuild=True, range_mode=str(v or "auto")
                ),
                tooltip=(
                    "Centered stick axes plot from −100 to +100. Throttles and sliders are typically 0 to 100%. "
                    "Auto guesses from the axis name (S1/S2 and throttle-like names are 0–100)."
                ),
            )
            form.addRow("Range", range_box)

        remove = Buttons.getRemoveWidget(
            label="Remove",
            callback=lambda wid=item["id"], sid=series_id: self._remove_graph_series(wid, sid),
        )
        form.addRow("", remove)
        return box

    def _set_graph_series(self, widget_id: str, series_id: str, rebuild: bool = False, **fields):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        series = self._series_for(item)
        updated = False
        for entry in series:
            if str(entry.get("id") or "") != str(series_id):
                continue
            entry.update(fields)
            updated = True
            break
        if not updated:
            return
        self._update(widget_id, series=series)
        if rebuild:
            self.rebuild()

    def _add_graph_series(self, widget_id: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        self.scene.push_undo()
        series = self._series_for(item)
        series.append(default_graph_series(len(series)))
        self._update(widget_id, series=series)
        self.rebuild()

    def _remove_graph_series(self, widget_id: str, series_id: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        series = self._series_for(item)
        next_series = [entry for entry in series if str(entry.get("id") or "") != str(series_id)]
        if len(next_series) == len(series):
            return
        self.scene.push_undo()
        self._update(widget_id, series=next_series)
        self.rebuild()

    def _listen_graph_series(self, item: dict, series_id: str):
        def _captured(event):
            if not self._is_alive():
                return
            if event.event_type != InputType.JoystickAxis:
                return
            device = gremlin.joystick_handling.getDevice(event.device_guid, show_error=False)
            virtual = bool(getattr(device, "is_virtual", False))
            payload = {
                "source": "vjoy" if virtual else "physical",
                "device_guid": str(event.device_guid),
                "device_name": device.name if device else str(event.device_guid),
                "vjoy_id": int(getattr(device, "vjoy_id", 0) or 0),
                "input_id": int(event.identifier),
            }
            self._set_graph_series(item["id"], series_id, rebuild=True, **payload)

        previous = getattr(self, "_listen_dialog", None)
        if previous is not None:
            try:
                if Shiboken.isValid(previous):
                    previous.close()
            except Exception:
                pass
            self._listen_dialog = None
        listener = gremlin.ui.ui_common.InputListenerWidget([InputType.JoystickAxis], callback=_captured, parent=self)
        self._listen_dialog = listener
        listener.show()

    def _on_mouse_mode(self, widget_id: str, mode: str):
        self._style(widget_id, mouse_mode=normalize_mouse_mode(mode))
        self.rebuild()

    def _streamdeck_appearance(self, form, item: dict):
        try:
            from gremlin.ui.streamdeck_device import (
                StreamDeckBridge,
                friendly_streamdeck_name,
            )

            bridge = StreamDeckBridge()
        except Exception:
            form.addRow(QtWidgets.QLabel('Stream Deck bridge is unavailable.', self._host))
            return

        style = item.get("style") or {}
        wanted = str(style.get("streamdeck_device_id") or "")
        combo = QDataComboBox()
        combo.addItem("First connected", "")
        seen = set()
        for device_id, info in (bridge.devices or {}).items():
            info = info or {}
            label = friendly_streamdeck_name(info.get("name"), info.get("type"), device_id)
            combo.addItem(label, device_id)
            seen.add(device_id)
        if wanted and wanted not in seen:
            combo.addItem(f"Disconnected ({wanted[:8]})", wanted)
        idx = combo.findData(wanted)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _i, w=combo, wid=item["id"]: self._on_streamdeck_device(wid, w.currentData() or "")
        )
        form.addRow("Device", combo)

        follow = bool(style.get("streamdeck_follow_page", True))
        page_combo = QDataComboBox()
        device_id = bridge.resolve_overlay_device_id(wanted)
        pages = bridge.list_pages(device_id) if device_id else [1]
        current_page = int(style.get("streamdeck_page") or 1)
        for page in pages:
            name = bridge.page_name(device_id, page) if device_id else f"Page {page}"
            if name and name != f"Page {page}" and not str(name).startswith(f"{page}."):
                label = f"{page}. {name}"
            else:
                label = name or f"Page {page}"
            page_combo.addItem(label, page)
        pidx = page_combo.findData(current_page)
        if pidx < 0:
            page_combo.addItem(f"Page {current_page}", current_page)
            pidx = page_combo.findData(current_page)
        page_combo.setCurrentIndex(pidx if pidx >= 0 else 0)
        page_combo.setEnabled(not follow)
        page_combo.currentIndexChanged.connect(
            lambda _i, w=page_combo, wid=item["id"]: self._style(wid, streamdeck_page=int(w.currentData() or 1))
        )

        follow_box = QtWidgets.QCheckBox(self._host)
        follow_box.setChecked(follow)
        follow_box.setToolTip("Show the GEX virtual page currently painted on the hardware.")
        follow_box.stateChanged.connect(
            lambda _s, wid=item["id"], box=follow_box, combo=page_combo: self._on_streamdeck_follow(wid, box, combo)
        )
        form.addRow("Follow hardware page", follow_box)
        form.addRow("Page", page_combo)
        self._style_bool(
            form,
            item,
            "show_bezel",
            "Show bezel",
            tooltip="Draw the Stream Deck body around the keys.",
        )
        fit = QDataPushButton("Fit to device", tooltip="Resize this widget to the key layout of the selected Stream Deck.", clicked=lambda wid=item["id"]: self._fit_streamdeck_item(wid, force=True))
        form.addRow(fit)
        hint = QtWidgets.QLabel(
            "Mirrors the selected deck’s keys (and Stream Deck + dials) using the current GEX page art.",
            self._host,
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        self._style_color(form, item, "fill", "Bezel")
        self._border_appearance(form, item)

    def _on_streamdeck_follow(self, widget_id: str, box: QtWidgets.QCheckBox, page_combo: QtWidgets.QComboBox):
        if self._building:
            return
        follow = box.isChecked()
        self._style(widget_id, streamdeck_follow_page=bool(follow))
        page_combo.setEnabled(not follow)

    def _on_streamdeck_device(self, widget_id: str, device_id: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        self.scene.push_undo()
        item["style"]["streamdeck_device_id"] = device_id or ""
        self._fit_streamdeck_geometry(item)
        self.scene._dirty = True
        self.scene._emit()
        self.rebuild()

    def _fit_streamdeck_item(self, widget_id: str, force: bool = False):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        self.scene.push_undo()
        self._fit_streamdeck_geometry(item, force=force)
        self.scene._dirty = True
        self.scene._emit()
        self.rebuild()

    def _fit_streamdeck_geometry(self, item: dict, force: bool = True):
        from .model import DEFAULT_SIZES
        from .widgets import streamdeck_preferred_size

        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            bridge = StreamDeckBridge()
            device_id = bridge.resolve_overlay_device_id(str((item.get("style") or {}).get("streamdeck_device_id") or ""))
            info = bridge.devices.get(device_id, {}) if device_id else {}
            width, height = streamdeck_preferred_size((info or {}).get("type"))
        except Exception:
            width, height = DEFAULT_SIZES.get("streamdeck", (320, 208))
        current = (int(item.get("w") or 0), int(item.get("h") or 0))
        default = tuple(int(v) for v in DEFAULT_SIZES.get("streamdeck", (320, 208)))
        if not force and current not in (default, (0, 0)):
            return
        canvas_w = max(32, int(self.scene.canvas.get("width") or 1280))
        canvas_h = max(32, int(self.scene.canvas.get("height") or 720))
        scale = min(1.0, canvas_w / max(1, width), canvas_h / max(1, height))
        width = max(48, int(round(width * scale)))
        height = max(48, int(round(height * scale)))
        cx = int(item.get("x") or 0) + int(item.get("w") or 0) / 2.0
        cy = int(item.get("y") or 0) + int(item.get("h") or 0) / 2.0
        item["w"] = width
        item["h"] = height
        item["x"] = max(0, min(canvas_w - width, int(round(cx - width / 2.0))))
        item["y"] = max(0, min(canvas_h - height, int(round(cy - height / 2.0))))

    def _style_image_file(self, form, item: dict, key: str, label: str):
        path_row = QtWidgets.QWidget(self._host)
        path_layout = QtWidgets.QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_edit = QtWidgets.QLineEdit(item['style'].get(key) or '', self._host)
        path_edit.setPlaceholderText("Optional")
        browse = Buttons.getFolderWidget(tooltip="Browse")
        browse.setFixedWidth(28)
        browse.setToolTip("Choose an image or SVG file.")
        browse.clicked.connect(lambda _=False, wid=item["id"], k=key: self._browse_style_image(wid, k))
        clear = Buttons.getClearWidget(
            label="Clear",
            callback=lambda wid=item["id"], k=key: self._style(wid, **{k: ""}),
        )
        path_edit.editingFinished.connect(
            lambda wid=item["id"], w=path_edit, k=key: self._style(wid, **{k: w.text().strip()})
        )
        path_layout.addWidget(path_edit)
        path_layout.addWidget(browse)
        path_layout.addWidget(clear)
        form.addRow(label, path_row)

    def _browse_style_image(self, widget_id: str, key: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        from .images import IMAGE_FILE_FILTER

        start = (item.get("style") or {}).get(key) or ""
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Button image",
            start,
            IMAGE_FILE_FILTER,
        )
        if not fname:
            return
        self._style(widget_id, **{key: fname})

    def _browse_image(self, widget_id: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        from .images import IMAGE_FILE_FILTER

        start = (item.get("style") or {}).get("image_path") or ""
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Overlay image",
            start,
            IMAGE_FILE_FILTER,
        )
        if not fname:
            return
        self.scene.push_undo()
        item["style"]["image_path"] = fname
        self._fit_item_to_image(item, fname)
        self.scene._dirty = True
        self.scene._emit()

    def _browse_paddle_image(self, widget_id: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        from .images import IMAGE_FILE_FILTER

        start = (item.get("style") or {}).get("paddle_image") or ""
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Paddle silhouette",
            start,
            IMAGE_FILE_FILTER,
        )
        if not fname:
            return
        self._style(widget_id, paddle_image=fname, rebuild=True)
        self.rebuild()

    def _paste_image(self, widget_id: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        from .images import apply_image_to_item, qimage_from_clipboard, save_qimage

        image = qimage_from_clipboard()
        if image is None:
            QtWidgets.QToolTip.showText(
                QtGui.QCursor.pos(),
                "Clipboard has no image. Capture with Win+Shift+S, then Paste.",
                self,
            )
            return
        path = save_qimage(self.scene, image)
        if not path:
            return
        self.scene.push_undo()
        apply_image_to_item(self.scene, item, path, image)
        self.rebuild()

    def _fit_item_to_image(self, item: dict, path: str):
        from .images import fit_item_to_image_size, image_intrinsic_size

        size = image_intrinsic_size(path)
        if size is None:
            return
        fit_item_to_image_size(item, size[0], size[1], self.scene.canvas)

    def _set_shape_kind(self, widget_id: str, kind):
        if self._building:
            return
        if kind is None:
            return
        kind = normalize_shape_kind(kind)
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        self.scene.push_undo()
        item["style"]["shape_kind"] = kind
        entry = custom_shape(kind)
        item["style"]["shape_closed"] = bool(entry.get("closed", True)) if entry else kind != "line"
        item["points"] = default_shape_points(kind)
        self.scene._dirty = True
        self.scene._emit()
        self.rebuild()

    def _style_color(self, form, item, key, title):
        values = [(w.get("style") or {}).get(key) for w in self.scene.selected_widgets()] or [item["style"].get(key)]
        same = all(v == values[0] for v in values)
        btn = ColorButton(values[0] or "#ffffff")
        if not same:
            btn.setToolTip("Multiple values — pick a color to apply to all")
        btn.color_changed.connect(lambda v, wid=item["id"], k=key: self._style(wid, **{k: v}))
        form.addRow(title, btn)

    def _style_float(self, form, item, key, title, lo, hi, step=0.5):
        spin = QtWidgets.QDoubleSpinBox(self._host)
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setValue(float(item["style"][key]) if item["style"].get(key) is not None else float(lo))
        spin.valueChanged.connect(lambda v, wid=item["id"], k=key: self._style(wid, **{k: float(v)}))
        form.addRow(title, spin)

    def _set_show_current_mode(self, widget_id: str, enabled: bool):
        if self._building:
            return
        fields = {"show_current_mode": bool(enabled)}
        if enabled:
            fields["show_label"] = True
        self._style(widget_id, rebuild=True, **fields)

    def _style_bool(self, form, item, key, title, tooltip=None):
        fallback = bool(default_style(item.get("type") or "button").get(key, False))
        values = [bool((w.get("style") or {}).get(key, fallback)) for w in self.scene.selected_widgets()]
        if not values:
            values = [bool(item["style"].get(key, fallback))]
        box = QtWidgets.QCheckBox(self._host)
        self._set_bool_widget(box, values)
        if tooltip:
            box.setToolTip(tooltip)
        box.stateChanged.connect(lambda _s, wid=item["id"], k=key, b=box: self._on_bool(b, wid, style_key=k))
        form.addRow(title, box)

    def _style_label_fonts(self, form, item, widget_type: str | None = None):
        """Font controls for the Label section; counters/stopwatches get separate caption fonts."""
        widget_type = canonical_widget_type(widget_type or item.get("type"))
        if widget_type == "sys_stats":
            self._style_font(form, item, title="Counter font")
            self._style_color(form, item, "font_color", "Counter color")
            self._style_font(form, item, prefix="caption_", title="Caption font")
            self._style_color(form, item, "caption_font_color", "Caption color")
            return
        if widget_type == "stopwatch":
            self._style_font(form, item, title="Timer font")
            self._style_color(form, item, "font_color", "Timer color")
            self._style_font(form, item, prefix="caption_", title="Caption font")
            self._style_color(form, item, "caption_font_color", "Caption color")
            return
        self._style_font(form, item)
        self._style_color(form, item, "font_color", "Font color")

    def _style_font(self, form, item, prefix="", title: str | None = None):
        family_key = f"{prefix}font_family"
        size_key = f"{prefix}font_size"
        bold_key = f"{prefix}font_bold"
        italic_key = f"{prefix}font_italic"
        underline_key = f"{prefix}font_underline"
        strike_key = f"{prefix}font_strike"
        combo = QtWidgets.QFontComboBox()
        family = item["style"].get(family_key) or item["style"].get("font_family") or "Segoe UI"
        combo.setCurrentFont(QtGui.QFont(family))
        idx = combo.findText(family)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.currentTextChanged.connect(lambda v, wid=item["id"], k=family_key: self._style(wid, **{k: v}))
        size = QtWidgets.QSpinBox(self._host)
        size.setRange(6, 192)
        size.setValue(effective_font_size(item, size_key))
        size.setToolTip("Drawn font size. Updates while the widget is resized when Scale font with size is on.")
        size.valueChanged.connect(lambda v, wid=item["id"], k=size_key: self._style(wid, **{k: int(v)}))
        self._bind_live(size, lambda it=item, k=size_key: effective_font_size(it, k))
        style_row = QtWidgets.QWidget(self._host)
        style_layout = QtWidgets.QHBoxLayout(style_row)
        style_layout.setContentsMargins(0, 0, 0, 0)
        style_layout.setSpacing(4)
        style_layout.addWidget(size)
        for key, letter, tooltip, default in (
            (bold_key, "B", "Bold", True),
            (italic_key, "I", "Italic", False),
            (underline_key, "U", "Underline", False),
            (strike_key, "S", "Strikethrough", False),
        ):
            btn = QtWidgets.QToolButton(self._host)
            btn.setText(letter)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.setFixedWidth(26)
            if letter == "B":
                font = btn.font()
                font.setBold(True)
                btn.setFont(font)
            elif letter == "I":
                font = btn.font()
                font.setItalic(True)
                btn.setFont(font)
            elif letter == "U":
                btn.setStyleSheet("text-decoration: underline;")
            elif letter == "S":
                btn.setStyleSheet("text-decoration: line-through;")
            fallback = bool(item["style"].get(key, item["style"].get(key.replace(prefix, "", 1) if prefix else key, default)))
            if prefix and key not in item["style"] and key.replace(prefix, "") in ("font_bold",):
                fallback = bool(item["style"].get("font_bold", True))
            btn.setChecked(bool(item["style"].get(key, fallback if key == bold_key else item["style"].get(key, default))))
            if key == bold_key:
                btn.setChecked(bool(item["style"].get(bold_key, item["style"].get("font_bold", True))))
            else:
                btn.setChecked(bool(item["style"].get(key, False)))
            btn.toggled.connect(lambda v, wid=item["id"], k=key: self._style(wid, **{k: v}))
            style_layout.addWidget(btn)
        style_layout.addStretch()
        if title is None:
            if prefix == "axis_label_":
                title = "Axis font"
            elif prefix == "caption_":
                title = "Caption font"
            else:
                title = "Font"
        label = title
        form.addRow(label, combo)
        form.addRow(f"{label} size", style_row)
        if not prefix:
            self._style_bool(
                form,
                item,
                "auto_scale_font",
                "Scale font with size",
                tooltip="Keep the same relative font size when this widget is resized.",
            )

        self._style_drop_shadow(
            form,
            item,
            enabled_key=f"{prefix}font_shadow",
            color_key=f"{prefix}font_shadow_color",
            angle_key=f"{prefix}font_shadow_angle",
            distance_key=f"{prefix}font_shadow_distance",
            spread_key=f"{prefix}font_shadow_spread",
            size_key=f"{prefix}font_shadow_size",
            dx_key=f"{prefix}font_shadow_dx",
            dy_key=f"{prefix}font_shadow_dy",
            row_label=f"{label} shadow",
            resolve=lambda style, pfx=prefix: resolve_font_shadow(style, pfx),
            tip="Draw a drop shadow behind the text.",
        )

        stroke_w = float(item["style"].get(f"{prefix}font_stroke_width") or 0)
        stroke_row = QtWidgets.QWidget(self._host)
        stroke_layout = QtWidgets.QHBoxLayout(stroke_row)
        stroke_layout.setContentsMargins(0, 0, 0, 0)
        stroke_layout.setSpacing(6)
        stroke_box = QtWidgets.QCheckBox(self._host)
        stroke_box.setChecked(stroke_w > 0)
        stroke_box.setToolTip("Outline the letters. Width is in pixels.")
        stroke_color = ColorButton(item["style"].get(f"{prefix}font_stroke_color") or "#000000")
        stroke_color.color_changed.connect(lambda v, wid=item["id"], k=f"{prefix}font_stroke_color": self._style(wid, **{k: v}))
        stroke_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self._host)
        stroke_slider.setRange(1, 12)
        stroke_slider.setValue(max(1, int(round(stroke_w)) or 2))
        stroke_spin = QtWidgets.QSpinBox(self._host)
        stroke_spin.setRange(1, 12)
        stroke_spin.setSuffix(" px")
        stroke_spin.setValue(max(1, int(round(stroke_w)) or 2))

        def _set_stroke(width, wid=item["id"], enabled=True):
            self._style(wid, **{f"{prefix}font_stroke_width": float(width) if enabled else 0.0})

        def _stroke_toggled(on, slider=stroke_slider, spin=stroke_spin, color=stroke_color):
            on = bool(on)
            color.setVisible(on)
            slider.setVisible(on)
            spin.setVisible(on)
            _set_stroke(spin.value(), enabled=on)

        stroke_box.toggled.connect(_stroke_toggled)
        stroke_slider.valueChanged.connect(lambda v, box=stroke_spin: (box.blockSignals(True), box.setValue(v), box.blockSignals(False), _set_stroke(v, enabled=True)))
        stroke_spin.valueChanged.connect(lambda v, bar=stroke_slider: (bar.blockSignals(True), bar.setValue(v), bar.blockSignals(False), _set_stroke(v, enabled=True)))
        stroke_color.setVisible(stroke_w > 0)
        stroke_slider.setVisible(stroke_w > 0)
        stroke_spin.setVisible(stroke_w > 0)
        stroke_layout.addWidget(stroke_box)
        stroke_layout.addWidget(stroke_color)
        stroke_layout.addWidget(stroke_slider, 1)
        stroke_layout.addWidget(stroke_spin)
        form.addRow(f"{label} stroke", stroke_row)

    def _style_widget_shadow(self, form, item: dict):
        """Appearance drop shadow for the widget body (same controls as font shadow)."""
        self._look_heading(form, "Shadow")
        self._style_drop_shadow(
            form,
            item,
            enabled_key="shadow",
            color_key="shadow_color",
            angle_key="shadow_angle",
            distance_key="shadow_distance",
            spread_key="shadow_spread",
            size_key="shadow_size",
            dx_key="shadow_dx",
            dy_key="shadow_dy",
            row_label="Shadow",
            resolve=lambda style: resolve_widget_shadow(style),
            tip="Draw a drop shadow behind the widget body.",
            distance_default=6,
            size_default=8,
            distance_max=80,
            size_max=80,
        )

    def _style_drop_shadow(
        self,
        form,
        item: dict,
        *,
        enabled_key: str,
        color_key: str,
        angle_key: str,
        distance_key: str,
        spread_key: str,
        size_key: str,
        dx_key: str,
        dy_key: str,
        row_label: str,
        resolve,
        tip: str,
        distance_default: float = 3,
        size_default: float = 0,
        distance_max: int = 40,
        size_max: int = 40,
    ):
        style = item.get("style") or {}
        shadow = resolve(style)
        shadow_on = bool(shadow.get("on"))
        shadow_head = QtWidgets.QWidget(self._host)
        shadow_head_layout = QtWidgets.QHBoxLayout(shadow_head)
        shadow_head_layout.setContentsMargins(0, 0, 0, 0)
        shadow_head_layout.setSpacing(6)
        shadow_box = QtWidgets.QCheckBox(self._host)
        shadow_box.setChecked(shadow_on)
        shadow_box.setToolTip(tip)
        shadow_color = ColorButton(style.get(color_key) or "#80000000")
        shadow_color.color_changed.connect(lambda v, wid=item["id"], k=color_key: self._style(wid, **{k: v}))
        shadow_head_layout.addWidget(shadow_box)
        shadow_head_layout.addWidget(shadow_color)
        shadow_head_layout.addStretch()
        form.addRow(row_label, shadow_head)

        angle_row = QtWidgets.QWidget(self._host)
        angle_layout = QtWidgets.QHBoxLayout(angle_row)
        angle_layout.setContentsMargins(0, 0, 0, 0)
        angle_layout.setSpacing(6)
        dial = QtWidgets.QDial()
        dial.setRange(0, 359)
        dial.setWrapping(True)
        dial.setNotchesVisible(True)
        dial.setFixedSize(48, 48)
        dial.setToolTip("Shadow direction. 0° = right, 90° = up.")
        dial.setValue(int(round(float(shadow.get("angle") or 135.0))) % 360)
        angle_spin = QtWidgets.QSpinBox(self._host)
        angle_spin.setRange(0, 359)
        angle_spin.setSuffix("°")
        angle_spin.setValue(int(round(float(shadow.get("angle") or 135.0))) % 360)
        angle_spin.setMaximumWidth(72)
        angle_layout.addWidget(dial)
        angle_layout.addWidget(angle_spin)
        angle_layout.addStretch()
        form.addRow("Angle", angle_row)

        def _apply_shadow_geometry(
            angle=None,
            distance=None,
            spread=None,
            size=None,
            wid=item["id"],
        ):
            cur_style = dict((self.scene.widget_by_id(wid) or item).get("style") or {})
            cur = resolve(cur_style)
            ang = float(cur["angle"] if angle is None else angle) % 360.0
            dist = max(0.0, float(cur["distance"] if distance is None else distance))
            spr = max(0.0, min(100.0, float(cur["spread"] if spread is None else spread)))
            sz = max(0.0, float(cur["size"] if size is None else size))
            dx, dy = _shadow_offset_xy(ang, dist)
            self._style(
                wid,
                **{
                    angle_key: ang,
                    distance_key: dist,
                    spread_key: spr,
                    size_key: sz,
                    dx_key: int(round(dx)),
                    dy_key: int(round(dy)),
                },
            )

        def _sync_angle(v, dial_w=dial, spin_w=angle_spin):
            value = int(v) % 360
            for w in (dial_w, spin_w):
                w.blockSignals(True)
                w.setValue(value)
                w.blockSignals(False)
            _apply_shadow_geometry(angle=value)

        dial.valueChanged.connect(_sync_angle)
        angle_spin.valueChanged.connect(_sync_angle)

        def _shadow_slider(title, value, lo, hi, suffix, tooltip, apply_key):
            row = QtWidgets.QWidget(self._host)
            layout = QtWidgets.QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
            slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self._host)
            slider.setRange(lo, hi)
            slider.setValue(int(value))
            spin = QtWidgets.QSpinBox(self._host)
            spin.setRange(lo, hi)
            spin.setValue(int(value))
            spin.setMaximumWidth(88)
            if suffix:
                spin.setSuffix(suffix)
            row.setToolTip(tooltip)
            slider.setToolTip(tooltip)
            spin.setToolTip(tooltip)

            def _from_slider(v, box=spin, key=apply_key):
                box.blockSignals(True)
                box.setValue(v)
                box.blockSignals(False)
                _apply_shadow_geometry(**{key: float(v)})

            def _from_spin(v, bar=slider, key=apply_key):
                bar.blockSignals(True)
                bar.setValue(v)
                bar.blockSignals(False)
                _apply_shadow_geometry(**{key: float(v)})

            slider.valueChanged.connect(_from_slider)
            spin.valueChanged.connect(_from_spin)
            layout.addWidget(slider, 1)
            layout.addWidget(spin)
            form.addRow(title, row)
            return row, slider, spin

        dist_row, dist_slider, dist_spin = _shadow_slider(
            "Distance",
            int(round(float(shadow.get("distance") if shadow.get("distance") is not None else distance_default))),
            0,
            int(distance_max),
            " px",
            "How far the shadow is offset.",
            "distance",
        )
        spread_row, spread_slider, spread_spin = _shadow_slider(
            "Spread",
            int(round(float(shadow.get("spread") or 0))),
            0,
            100,
            " %",
            "How far the shadow grows outward before the blur (0–100% of Size).",
            "spread",
        )
        size_row, size_slider, size_spin = _shadow_slider(
            "Size",
            int(round(float(shadow.get("size") if shadow.get("size") is not None else size_default))),
            0,
            int(size_max),
            " px",
            "Soft blur radius of the shadow.",
            "size",
        )

        def _set_shadow_enabled(on):
            on = bool(on)
            shadow_color.setVisible(on)
            _set_form_rows_visible(form, [angle_row, dist_row, spread_row, size_row], on)

        shadow_box.toggled.connect(
            lambda on, wid=item["id"], key=enabled_key: (
                self._style(wid, **{key: bool(on)}),
                _set_shadow_enabled(on),
            )
        )
        _set_shadow_enabled(shadow_on)

    def _build_toggle_binding(self):
        binding = normalize_toggle_binding(self.scene.canvas.get("toggle_binding"))
        # Canvas show/hide is a button (or state) assignment — not a free-form
        # axis/hat binding editor. Force button so Input type / Invert stay hidden.
        binding["input_type"] = "button"
        self.scene.canvas["toggle_binding"] = binding
        item = {"id": CANVAS_TOGGLE_ID, "type": "button", "binding": binding}
        self._build_channel(
            item,
            "binding",
            "Toggle overlay",
            force_type="button",
            allow_none=True,
            show_clear=True,
            show_invert=False,
            extra_hint=(
                "While the profile is running, this page’s overlay is shown while the state is pressed and hidden while it is released."
                if (binding.get("source") or "").casefold() == "state"
                else (
                    "While the profile is running, this page’s overlay is shown while this mode is active and hidden when another mode is selected."
                    if (binding.get("source") or "").casefold() == "mode"
                    else (
                        "While the profile is running, press the key combination to show or hide this page’s overlay window."
                        if (binding.get("source") or "").casefold() == "keyboard"
                        else "While the profile is running, press this button to show or hide this page’s overlay window."
                    )
                )
            ),
        )

    def _build_runtime_bindings(self):
        """Hotkeys for anchors and opening the runtime control panel."""
        bindings = normalize_runtime_bindings(self.scene.canvas.get("runtime_bindings"))
        self.scene.canvas["runtime_bindings"] = bindings
        form = self._section("Runtime control")
        hint = QtWidgets.QLabel(
            "While the profile is running, these inputs move the current control target "
            "(page / group / widget) to an anchor, nudge it, toggle visibility, save, "
            "cycle anchors, or open the control panel. "
            "Use rising-edge button or key bindings (nudge binds repeat while held). "
            "The Overlay control panel Keybinds… button edits the same list.",
            self._host,
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        open_panel = QDataPushButton(
            "Open control panel…",
            tooltip="Open the runtime overlay control panel now.",
            clicked=self._open_runtime_control_panel,
        )
        form.addRow(open_panel)
        for action in RUNTIME_BINDING_ACTIONS:
            binding = normalize_toggle_binding(bindings.get(action))
            binding["input_type"] = "button"
            bindings[action] = binding
            item = {"id": f"{CANVAS_RUNTIME_PREFIX}{action}", "type": "button", "binding": binding}
            self._build_channel(
                item,
                "binding",
                RUNTIME_BINDING_LABELS.get(action, action),
                force_type="button",
                allow_none=True,
                show_clear=True,
                show_invert=False,
                form=form,
            )

    def _open_runtime_control_panel(self):
        try:
            from gremlin.ui.obs_overlay import OverlayManager

            OverlayManager().open_control_panel(parent=self.window())
        except Exception:
            from .control_panel import open_overlay_control_panel

            open_overlay_control_panel(self.scene, parent=self.window())

    def _build_binding(self, item: dict):
        if widget_needs_xy(item.get("type")):
            self._build_channel(item, "binding", "Axis X", force_type="axis")
            self._build_channel(item, "binding_y", "Axis Y", force_type="axis")
            return
        widget_type = item.get("type")
        if widget_type == "stopwatch":
            self._build_channel(
                item,
                "binding",
                "Start / stop",
                force_type="button",
                extra_hint="Press toggles the clock. A GEX state or mode follows the value (running while on).",
            )
            self._build_channel(
                item,
                "binding_y",
                "Reset",
                force_type="button",
                allow_none=True,
                show_clear=True,
                extra_hint="Optional. A press sets the counter back to zero.",
            )
            return
        if widget_is_switch(widget_type):
            hints = {
                "switch_4way": "Each direction is a separate button. Center is optional (some hats press it at rest).",
                "switch_2way": "Position 1, Center, and Position 2. Center is optional. Interactive overlay latches the last press.",
                "switch_3way": "Spring-loaded center: an Interactive overlay returns to center when you lift.",
            }
            rows = list(SWITCH_POSITION_TITLES.get(widget_type) or ())
            for index, (position, title) in enumerate(rows):
                self._build_channel(
                    item,
                    switch_channel(position),
                    title,
                    force_type="button",
                    allow_none=True,
                    show_clear=True,
                    extra_hint=hints.get(widget_type) if index == 0 else None,
                )
            return
        force = None
        if widget_type == "button":
            force = "button"
        elif widget_type == "hat":
            force = "hat"
        elif widget_type and str(widget_type).startswith("axis"):
            force = "axis"
        self._build_channel(item, "binding", "Binding", force_type=force)

    def _channel_binding(self, item: dict, channel: str) -> dict:
        if channel.startswith("bindings."):
            position = channel.split(".", 1)[1]
            bindings = item.get("bindings")
            if not isinstance(bindings, dict):
                bindings = {}
                item["bindings"] = bindings
            binding = bindings.get(position)
            if not isinstance(binding, dict):
                binding = default_toggle_binding()
                bindings[position] = binding
            return binding
        binding = item.get(channel)
        if not isinstance(binding, dict):
            binding = {}
            item[channel] = binding
        return binding

    def _build_channel(
        self,
        item: dict,
        channel: str,
        title: str,
        force_type: str | None = None,
        allow_none: bool = False,
        extra_hint: str | None = None,
        show_clear: bool = False,
        show_invert: bool = True,
        form=None,
    ):
        if form is None:
            form = self._section(title)
        elif title:
            self._look_heading(form, title)
        binding = self._channel_binding(item, channel)
        sources = ["physical", "vjoy"]
        if force_type != "axis" or not widget_needs_xy(item.get("type")):
            sources.append("state")
        if force_type == "button" or item.get("type") in ("button", "stopwatch") or widget_is_switch(item.get("type")):
            sources.append("mode")
            sources.append("keyboard")
        current_source = binding.get("source") or "physical"
        if current_source in ("keyboard/mouse", "mouse"):
            current_source = "keyboard"
        if current_source not in sources:
            current_source = "physical"
        source_opts = [
            ("Keyboard/mouse" if value == "keyboard" else ("vJoy" if value == "vjoy" else value.capitalize()), value)
            for value in sources
        ]

        def _on_source(v, wid=item["id"], ch=channel, ft=force_type, bind=binding):
            src = str(v or "physical")
            self._bind(
                wid,
                ch,
                rebuild=True,
                source=src,
                input_type="keyboard" if src == "keyboard" else (ft or bind.get("input_type") or "button"),
            )

        if len(source_opts) <= 4:
            source = _enum_radios(source_opts, current_source, _on_source)
        else:
            source = QDataComboBox()
            for label, value in source_opts:
                source.addItem(label, value)
            index = source.findData(current_source)
            source.setCurrentIndex(index if index >= 0 else 0)
            source.currentIndexChanged.connect(lambda _i, box=source: _on_source(box.currentData()))
        form.addRow("Source", source)

        # Use the binding's current source for the rest of this build (radio/combo agree via currentData).
        active_source = current_source
        if hasattr(source, "currentData"):
            try:
                active_source = source.currentData() or current_source
            except Exception:
                active_source = current_source

        if active_source == "state":
            combo = QDataComboBox()
            populate_overlay_state_combo(combo, binding.get("state_id"), binding.get("state_name"))
            combo.currentIndexChanged.connect(
                lambda _i, combo=combo, wid=item["id"], ch=channel: self._bind(
                    wid, ch, **overlay_state_combo_fields(combo)
                )
            )
            form.addRow("State", combo)
            self._finish_channel(form, item, channel, extra_hint, show_clear)
            return

        if active_source == "mode":
            combo = QDataComboBox()
            populate_overlay_mode_combo(combo, binding.get("mode_id"), binding.get("mode_name"))
            combo.currentIndexChanged.connect(
                lambda _i, box=combo, wid=item["id"], ch=channel: self._bind(
                    wid, ch, **overlay_mode_combo_fields(box)
                )
            )
            form.addRow("Mode", combo)
            self._finish_channel(form, item, channel, extra_hint, show_clear)
            return

        if active_source == "keyboard":
            picker = OverlayKeyCombinationWidget(binding.get("keys") or [])
            picker.keys_changed.connect(
                lambda keys, wid=item["id"], ch=channel: self._bind(
                    wid, ch, keys=normalize_overlay_keys(keys), input_type="keyboard", source="keyboard"
                )
            )
            form.addRow(picker)
            self._finish_channel(form, item, channel, extra_hint, show_clear)
            return

        device_box = QDataComboBox()
        if active_source == "vjoy":
            for dev in gremlin.joystick_handling.vjoy_devices(connected_only=False) or []:
                # Store vjoy id only — DeviceSummary instances are discarded on m77 refresh.
                device_box.addItem(f"vJoy {dev.vjoy_id} ({dev.name})", int(dev.vjoy_id))
            current = int(binding.get("vjoy_id") or 0)
            for i in range(device_box.count()):
                if int(device_box.itemData(i) or 0) == current:
                    device_box.setCurrentIndex(i)
                    break
            shown = self._device_from_combo(device_box, "vjoy")
            if shown is not None and current <= 0:
                payload = {
                    "vjoy_id": int(shown.vjoy_id),
                    "device_guid": str(shown.device_guid),
                    "device_name": shown.name,
                }
                binding.update(payload)
                wid = str(item.get("id") or "")
                if wid.startswith("stat:"):
                    parts = wid.split(":", 2)
                    live = self.scene.widget_by_id(parts[1]) if len(parts) == 3 else None
                    if live:
                        for entry in live.get("stats") or []:
                            if str(entry.get("id") or "") != parts[2]:
                                continue
                            target = entry.get(channel)
                            if not isinstance(target, dict):
                                target = {}
                                entry[channel] = target
                            target.update(payload)
                            self.scene._dirty = True
                            break
                else:
                    self._channel_binding(item, channel).update(payload)
                    self.scene._dirty = True
        else:
            for dev in self._physical_joystick_devices():
                device_box.addItem(dev.name, str(dev.device_guid))
            current = str(binding.get("device_guid") or "")
            for i in range(device_box.count()):
                guid = str(device_box.itemData(i) or "")
                if guid and guid.casefold() == current.casefold():
                    device_box.setCurrentIndex(i)
                    break

        def _device_changed():
            if not self._is_alive():
                return
            src = str(source.currentData() or "physical")
            dev = self._device_from_combo(device_box, src)
            if not dev:
                return
            payload = {"device_name": dev.name, "device_guid": str(dev.device_guid)}
            if src == "vjoy":
                payload["vjoy_id"] = int(dev.vjoy_id)
            self._bind(item["id"], channel, rebuild=True, **payload)

        device_box.currentIndexChanged.connect(_device_changed)
        form.addRow("Device", device_box)

        listen = Buttons.getListenWidget(
            label="Listen...",
            tooltip="Assign from the next matching physical or vJoy input",
            # ListenWidget calls callback(button); keep widget dict in defaults.
            callback=lambda _btn=None, it=item, ch=channel, kind=force_type: self._listen(it, ch, kind),
        )
        form.addRow("", listen)

        input_kind = force_type or binding.get("input_type") or "axis"
        if not force_type:
            types = ["axis", "button", "hat"]
            if input_kind not in types:
                input_kind = "axis"
            input_type = _enum_radios(
                [("Axis", "axis"), ("Button", "button"), ("Hat", "hat")],
                input_kind,
                lambda v, wid=item["id"], ch=channel: self._bind(wid, ch, rebuild=True, input_type=v),
            )
            form.addRow("Input type", input_type)
        else:
            if binding.get("input_type") != force_type:
                binding["input_type"] = force_type
            input_kind = force_type

        device = self._device_from_combo(device_box, str(source.currentData() or "physical"))
        id_box = QDataComboBox()
        if allow_none:
            id_box.addItem("(none)", 0)
        choices = self._input_choices(device, input_kind)
        try:
            current_id = int(binding.get("input_id") or 0)
        except (TypeError, ValueError):
            current_id = 0
        if not allow_none and current_id <= 0:
            current_id = int(choices[0][0]) if choices else 1
        found = False
        for axis_id, label in choices:
            id_box.addItem(label, axis_id)
            if int(axis_id) == current_id:
                id_box.setCurrentIndex(id_box.count() - 1)
                found = True
        if not found:
            if allow_none and current_id <= 0:
                id_box.setCurrentIndex(0)
                found = True
            else:
                id_box.addItem(f"{input_kind.capitalize()} {current_id}", current_id)
                id_box.setCurrentIndex(id_box.count() - 1)
        id_box.currentIndexChanged.connect(
            lambda _i, wid=item["id"], ch=channel, box=id_box, kind=input_kind: self._bind(
                wid, ch, input_type=kind, input_id=int(box.currentData() if box.currentData() is not None else 0)
            )
        )
        form.addRow("Axis" if input_kind == "axis" else input_kind.capitalize(), id_box)

        if show_invert:
            inv = QtWidgets.QCheckBox(self._host)
            inv.setChecked(bool(binding.get("invert")))
            inv.toggled.connect(lambda v, wid=item["id"], ch=channel: self._bind(wid, ch, invert=v))
            form.addRow("Invert", inv)

        hint = QtWidgets.QLabel(self._channel_summary(binding, input_kind), self._host)
        hint.setWordWrap(True)
        form.addRow("Assigned", hint)
        self._finish_channel(form, item, channel, extra_hint, show_clear)

    def _finish_channel(self, form, item: dict, channel: str, extra_hint: str | None, show_clear: bool):
        if extra_hint:
            note = QtWidgets.QLabel(extra_hint, self._host)
            note.setWordWrap(True)
            form.addRow(note)
        if show_clear:
            clear = Buttons.getClearWidget(
                callback=lambda wid=item["id"], ch=channel: self._bind(
                    wid,
                    ch,
                    rebuild=True,
                    device_guid="",
                    device_name="",
                    vjoy_id=0,
                    input_id=0,
                    state_name="",
                    state_id="",
                    mode_name="",
                    mode_id="",
                    keys=[],
                )
            )
            form.addRow("", clear)

    def _input_choices(self, device, input_kind: str) -> list[tuple[int, str]]:
        if input_kind == "axis":
            choices = []
            maps = getattr(device, "axismap_list", None) or [] if device else []
            for am in maps:
                axis_id = getattr(am, "axis_index", 0)
                if not axis_id:
                    continue
                try:
                    axis_name = gremlin.joystick_handling.get_axis_name(axis_id)
                except Exception:
                    axis_name = str(axis_id)
                try:
                    device_name = device.get_axis_name(axis_id) if device else None
                except Exception:
                    device_name = None
                label = f"Axis {axis_id} ({axis_name})"
                if device_name and str(device_name) not in label:
                    label = f"{label} — {device_name}"
                choices.append((int(axis_id), label))
            if choices:
                return choices
            count = int(getattr(device, "axis_count", 0) or 0) if device else 8
            for i in range(1, max(1, count) + 1):
                try:
                    axis_name = gremlin.joystick_handling.get_axis_name(i)
                except Exception:
                    axis_name = str(i)
                choices.append((i, f"Axis {i} ({axis_name})"))
            return choices or [(1, "Axis 1 (X)"), (2, "Axis 2 (Y)")]
        if input_kind == "button":
            count = int(getattr(device, "button_count", 0) or 0) if device else 16
            return [(i, f"Button {i}") for i in range(1, max(1, count) + 1)]
        count = int(getattr(device, "hat_count", 0) or 0) if device else 4
        return [(i, f"Hat {i}") for i in range(1, max(1, count) + 1)]

    def _channel_summary(self, binding: dict, input_kind: str) -> str:
        source = binding.get("source") or "physical"
        if source == "state":
            state = find_overlay_state(binding.get("state_id"), binding.get("state_name"))
            return (state.key if state is not None else binding.get("state_name")) or "(none)"
        if source == "mode":
            _mid, name = resolve_overlay_mode(binding.get("mode_id"), binding.get("mode_name"))
            return name or binding.get("mode_name") or "(none)"
        if source in ("keyboard", "keyboard/mouse", "mouse"):
            names = []
            for raw in binding.get("keys") or []:
                key = deserialize_overlay_key(raw)
                if key is None:
                    continue
                names.append(gremlin.keyboard.KeyMap.get_name(key) or str(key.name or ""))
            return " + ".join(n for n in names if n) or "(none)"
        try:
            input_id = int(binding.get("input_id") or 0)
        except (TypeError, ValueError):
            input_id = 0
        if input_id <= 0:
            return "(none)"
        name = binding.get("device_name") or "—"
        return f"{name}  {input_kind.capitalize()} {input_id}"

    def _listen(self, item: dict, channel: str = "binding", force_type: str | None = None):
        types = [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat]
        widget_type = item.get("type")
        if force_type == "axis" or (widget_type and str(widget_type).startswith("axis")):
            types = [InputType.JoystickAxis]
        elif force_type == "button" or widget_type == "button":
            types = [InputType.JoystickButton]
        elif force_type == "hat" or widget_type == "hat":
            types = [InputType.JoystickHat]

        def _captured(event):
            if not self._is_alive():
                return
            input_type = "axis"
            if event.event_type == InputType.JoystickButton:
                input_type = "button"
            elif event.event_type == InputType.JoystickHat:
                input_type = "hat"
            device = gremlin.joystick_handling.getDevice(event.device_guid, show_error=False)
            payload = {
                "source": "vjoy" if getattr(device, "is_virtual", False) else "physical",
                "device_guid": str(event.device_guid),
                "device_name": device.name if device else str(event.device_guid),
                "vjoy_id": int(getattr(device, "vjoy_id", 0) or 0),
                "input_type": input_type,
                "input_id": int(event.identifier),
            }
            self._bind(item["id"], channel, rebuild=True, **payload)

        previous = getattr(self, "_listen_dialog", None)
        if previous is not None:
            try:
                if Shiboken.isValid(previous):
                    previous.close()
            except Exception:
                pass
            self._listen_dialog = None
        listener = gremlin.ui.ui_common.InputListenerWidget(types, callback=_captured, parent=self)
        self._listen_dialog = listener
        listener.show()

    @staticmethod
    def _physical_joystick_devices():
        """Physical HID joysticks only — not Keyboard/State/OSC/Stream Deck/etc."""
        devices = gremlin.joystick_handling.getPhysicalDevices() or []
        return sorted(devices, key=lambda d: (d.name or "").casefold())

    def _device_from_combo(self, device_box: QtWidgets.QComboBox, source: str):
        """Resolve a live DeviceSummary from combo itemData (guid or vjoy id)."""
        data = device_box.currentData()
        if source == "vjoy":
            try:
                vjoy_id = int(data or 0)
            except (TypeError, ValueError):
                return None
            if vjoy_id <= 0:
                return None
            for dev in gremlin.joystick_handling.vjoy_devices(connected_only=False) or []:
                if int(getattr(dev, "vjoy_id", 0) or 0) == vjoy_id:
                    return dev
            return None
        guid = str(data or "").strip()
        if not guid:
            return None
        return gremlin.joystick_handling.getDevice(guid, show_error=False)

    def _update(self, widget_id: str, **fields):
        if self._building:
            return
        ids = list(self._edit_ids or [widget_id])
        self.scene.apply_widget_updates(ids, **fields)

    def _style(self, widget_id: str, **fields):
        if self._building:
            return
        rebuild = bool(fields.pop("rebuild", False))
        ids = list(self._edit_ids or [widget_id])
        self.scene.apply_widget_updates(ids, style=fields)
        if rebuild:
            self.rebuild()

    def _bind(self, widget_id: str, channel: str = "binding", rebuild: bool = False, **fields):
        if self._building:
            return
        if (fields.get("source") or "").casefold() == "vjoy" and not int(fields.get("vjoy_id") or 0):
            devices = gremlin.joystick_handling.vjoy_devices(connected_only=False) or []
            if devices:
                fields["vjoy_id"] = int(devices[0].vjoy_id)
                fields.setdefault("device_guid", str(devices[0].device_guid))
                fields.setdefault("device_name", devices[0].name)
        if str(widget_id).startswith("stat:"):
            parts = str(widget_id).split(":", 2)
            if len(parts) == 3:
                self._bind_stat(parts[1], parts[2], channel, rebuild=rebuild, **fields)
                return
        if widget_id == CANVAS_TOGGLE_ID:
            binding = normalize_toggle_binding(self.scene.canvas.get("toggle_binding"))
            binding.update(fields)
            self.scene.canvas["toggle_binding"] = normalize_toggle_binding(binding)
            self.scene._dirty = True
            self.scene.changed.emit()
            if rebuild:
                self.rebuild()
            return
        if str(widget_id).startswith(CANVAS_RUNTIME_PREFIX):
            action = str(widget_id)[len(CANVAS_RUNTIME_PREFIX) :]
            bindings = normalize_runtime_bindings(self.scene.canvas.get("runtime_bindings"))
            binding = normalize_toggle_binding(bindings.get(action))
            binding.update(fields)
            bindings[action] = normalize_toggle_binding(binding)
            self.scene.canvas["runtime_bindings"] = bindings
            self.scene._dirty = True
            self.scene.changed.emit()
            if rebuild:
                self.rebuild()
            return
        if channel.startswith("bindings."):
            position = channel.split(".", 1)[1]
            self.scene.apply_widget_update(widget_id, bindings={position: fields})
            if rebuild:
                self.rebuild()
            return
        self.scene.apply_widget_update(widget_id, **{channel: fields})
        if rebuild:
            self.rebuild()
