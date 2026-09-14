# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import logging

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

import gremlin.joystick_handling
import gremlin.keyboard
import gremlin.shared_state
import gremlin.types
import gremlin.ui.ui_common
import gremlin.ui.virtual_keyboard
import gremlin.util
from gremlin.input_types import InputType

from .bindings import profile_mode_choices, widget_needs_xy
from .mouse_track import normalize_mouse_mode
from .qt_guard import alive, later, on_ui
from .model import (
    DEFAULT_GUIDE_COLOR,
    GRAPH_SERIES_COLORS,
    NO_BINDING_WIDGET_TYPES,
    NO_CORNER_RADIUS_TYPES,
    NO_DEADZONE_WIDGET_TYPES,
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
    normalize_series_range_mode,
    normalize_stat_series,
    normalize_switch_appearance,
    normalize_toggle_binding,
    normalize_visibility,
    serialize_overlay_key,
    switch_channel,
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
from .widgets import effective_font_size, qcolor, widget_rotation_deg

CANVAS_TOGGLE_ID = "__canvas_toggle__"
syslog = logging.getLogger("system")


class ColorButton(QtWidgets.QPushButton):
    color_changed = QtCore.Signal(str)

    def __init__(self, value="#ffffff", parent=None, preserve_transparent: bool = False):
        super().__init__(parent)
        self.setObjectName("overlayColorSwatch")
        self._value = value or "#ffffff"
        self._preserve_transparent = bool(preserve_transparent)
        self.setFixedHeight(24)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._refresh()

    def set_value(self, value: str):
        self._value = value or "#ffffff"
        self._refresh()

    def value(self) -> str:
        return self._value

    def _refresh(self):
        color = qcolor(self._value)
        # Object-name selector so this does not leak onto QColorDialog buttons.
        self.setStyleSheet(
            f"#overlayColorSwatch {{ background:{color.name(QtGui.QColor.HexArgb)}; border:1px solid #444; border-radius:3px; }}"
        )
        self.setToolTip(self._value)

    def _pick(self):
        chosen = QtWidgets.QColorDialog.getColor(
            qcolor(self._value),
            self.window() or self.parentWidget() or self,
            "Select color",
            QtWidgets.QColorDialog.DontUseNativeDialog | QtWidgets.QColorDialog.ShowAlphaChannel,
        )
        if chosen.isValid():
            previous = qcolor(self._value)
            # Transparent defaults keep alpha at 0 in the picker; bump so fill/border actually show.
            if not self._preserve_transparent and previous.alpha() == 0 and chosen.alpha() == 0:
                chosen.setAlpha(255)
            self._value = chosen.name(QtGui.QColor.HexArgb)
            self._refresh()
            self.color_changed.emit(self._value)


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
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        rect = self.rect().adjusted(2, 2, -3, -3)
        fill = qcolor(self._colors.get("fill"), "#121826")
        accent = qcolor(
            self._colors.get("fill_on") or self._colors.get("indicator") or self._colors.get("fill_bar") or self._colors.get("border"),
            "#888888",
        )
        outline = qcolor(self._colors.get("border") or self._colors.get("indicator"), "#555555")
        if fill.alpha() <= 0:
            painter.fillRect(rect, QtGui.QColor("#2a2a2a"))
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
        self._last_rebuild_ids: list[str] = []
        self._pending_scroll = (0, 0)
        self._scroll_restore_tries = 0
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        self._host = QtWidgets.QWidget()
        self._form = QtWidgets.QVBoxLayout(self._host)
        self._form.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._host)
        layout.addWidget(scroll)
        self._scroll = scroll
        self.scene.selection_changed.connect(self.rebuild)
        self.scene.changed.connect(self._maybe_rebuild)
        self.destroyed.connect(self._detach_scene)
        self._canvas_sig = None
        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            StreamDeckBridge().devices_changed.connect(self._on_streamdeck_devices_changed)
        except Exception:
            pass
        self.rebuild()

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
            self.scene.selection_changed.disconnect(self.rebuild)
        except Exception:
            pass
        try:
            self.scene.changed.disconnect(self._maybe_rebuild)
        except Exception:
            pass
        try:
            from gremlin.ui.streamdeck_device import StreamDeckBridge

            StreamDeckBridge().devices_changed.disconnect(self._on_streamdeck_devices_changed)
        except Exception:
            pass
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
        )

    def _maybe_rebuild(self):
        if not self._is_alive():
            return
        if not gremlin.util.is_ui_thread():
            on_ui(self, self._maybe_rebuild)
            return
        if self._building:
            self._rebuild_pending = True
            return
        if self._rebuild_pending:
            return
        sig = self._canvas_signature()
        if sig != self._canvas_sig:
            self._schedule_rebuild()
            return
        self._refresh_live_fields()

    def _schedule_rebuild(self):
        if self._rebuild_pending:
            return
        self._rebuild_pending = True
        later(self, self._run_scheduled_rebuild)

    def _run_scheduled_rebuild(self):
        self._rebuild_pending = False
        if not self._is_alive():
            return
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
        if layout is None:
            return
        try:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    # Hide first. setParent(None) would make a visible top-level
                    # window (title = application name) for a frame on page switch.
                    # blockSignals: focusOut/editingFinished on a stale Name field
                    # must not rewrite page["name"] back to the pre-rename value.
                    try:
                        widget.blockSignals(True)
                        for child in widget.findChildren(QtWidgets.QWidget):
                            child.blockSignals(True)
                    except RuntimeError:
                        pass
                    widget.hide()
                    widget.deleteLater()
        except RuntimeError:
            return

    def _section(self, title: str) -> QtWidgets.QFormLayout:
        box = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(box)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        if self._form is not None:
            self._form.addWidget(box)
        return form

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
        previous_ids = list(self._last_rebuild_ids)
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
        try:
            if self._form is None:
                return
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
                hint = QtWidgets.QLabel("Select a widget on the canvas, or add one from the palette.")
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
            keep_scroll = bool(built_ids) and built_ids == previous_ids
            self._pending_scroll = (saved_h, saved_v) if keep_scroll else (0, 0)
            self._scroll_restore_tries = 0
            later(self, self._restore_inspector_scroll)
        except RuntimeError:
            return
        except Exception:
            syslog.exception("OBS OVERLAY: inspector rebuild failed")
        finally:
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
        form = self._section("Canvas")
        canvas = self.scene.canvas
        page = self.scene.active_page() or {}
        onscreen = is_onscreen_mode(canvas)

        name = QtWidgets.QLineEdit(str(page.get("name") or ""))
        name.setToolTip("Name of this overlay page. Shown on the designer tab and in the live window title.")
        # Capture page id so a deferred editingFinished from a destroyed field
        # cannot rename the wrong page after an activate/deactivate rebuild.
        page_id = page.get("id")
        name.editingFinished.connect(
            lambda edit=name, pid=page_id: self._on_page_name(edit.text(), page_id=pid)
        )
        form.addRow("Name", name)

        visible = QtWidgets.QCheckBox()
        visible.setChecked(bool(page.get("visible", True)))
        visible.setToolTip("When off, this page’s live window is closed. Show overlay still only opens the selected page.")
        visible.toggled.connect(lambda v: self.scene.set_page_visible(bool(v)))
        form.addRow("Visible", visible)

        start = QtWidgets.QCheckBox()
        start.setChecked(bool(canvas.get("show_on_profile_start")))
        start.toggled.connect(lambda v: self._set_canvas("show_on_profile_start", bool(v)))
        form.addRow("Show at profile start", start)

        interactive = QtWidgets.QCheckBox()
        interactive.setChecked(bool(canvas.get("interactive")))
        interactive.setToolTip(
            "On this page’s live overlay, touch or click widgets bound to vJoy or GEX states. "
            "Empty space stays click-through. Physical bindings stay display-only."
        )
        interactive.toggled.connect(lambda v: self._set_canvas("interactive", bool(v)))
        form.addRow("Interactive", interactive)
        touch_hint = QtWidgets.QLabel(
            "vJoy buttons are held while pressed. A state button tap inverts the state. Sticks and hats return to center on lift; faders keep their value."
        )
        touch_hint.setWordWrap(True)
        form.addRow(touch_hint)

        mode = QtWidgets.QComboBox()
        labels = [("chroma", "chroma"), ("image", "image"), ("onscreen", "on-screen")]
        for stored, label in labels:
            mode.addItem(label, stored)
        current = normalize_background_mode(canvas.get("background_mode"))
        mode.setCurrentIndex(next((i for i, (stored, _) in enumerate(labels) if stored == current), 0))
        mode.currentIndexChanged.connect(lambda _i, box=mode: self._on_background_mode(box.currentData()))
        form.addRow("Background", mode)

        if onscreen:
            screens = list_overlay_screens()
            monitor = QtWidgets.QComboBox()
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
                hint = QtWidgets.QLabel("Canvas size follows this monitor. Interactive is on: widgets capture touch; empty space passes through to the screen behind.")
            else:
                hint = QtWidgets.QLabel("Canvas size follows this monitor. The overlay is a transparent, click-through HUD.")
            hint.setWordWrap(True)
            form.addRow(hint)
        else:
            chroma = ColorButton(canvas.get("chroma_color") or "#00FF00", preserve_transparent=True)
            chroma.color_changed.connect(lambda v: self._set_canvas("chroma_color", v))
            form.addRow("Chroma color", chroma)
            chroma_hint = QtWidgets.QLabel(
                "Alpha 0 makes the overlay see-through to the desktop. Windows needs a frameless window for that — use the drag bar to move it. OBS chroma key still needs an opaque color."
            )
            chroma_hint.setWordWrap(True)
            form.addRow(chroma_hint)

            path_row = QtWidgets.QWidget()
            path_layout = QtWidgets.QHBoxLayout(path_row)
            path_layout.setContentsMargins(0, 0, 0, 0)
            path_edit = QtWidgets.QLineEdit(canvas.get("image_path") or "")
            browse = QtWidgets.QPushButton("...")
            browse.setFixedWidth(28)

            def _browse():
                fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Background image", path_edit.text(), "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
                if fname:
                    path_edit.setText(fname)
                    self._set_canvas("image_path", fname)

            browse.clicked.connect(_browse)
            path_edit.editingFinished.connect(lambda: self._set_canvas("image_path", path_edit.text()))
            path_layout.addWidget(path_edit)
            path_layout.addWidget(browse)
            form.addRow("Image", path_row)

        width = QtWidgets.QSpinBox()
        width.setRange(160, 7680)
        width.setValue(int(canvas.get("width") or 1280))
        height = QtWidgets.QSpinBox()
        height.setRange(120, 4320)
        height.setValue(int(canvas.get("height") or 720))
        width.setEnabled(not onscreen)
        height.setEnabled(not onscreen)
        if not onscreen:
            width.valueChanged.connect(lambda v: self._set_canvas("width", int(v)))
            height.valueChanged.connect(lambda v: self._set_canvas("height", int(v)))
        form.addRow("Width", width)
        form.addRow("Height", height)

        grid = QtWidgets.QSpinBox()
        grid.setRange(1, 64)
        grid.setValue(int(canvas.get("grid_size") or 8))
        grid.valueChanged.connect(lambda v: self._set_canvas("grid_size", int(v)))
        form.addRow("Grid size", grid)

        snap = QtWidgets.QCheckBox()
        snap.setChecked(bool(canvas.get("snap_to_grid", True)))
        snap.toggled.connect(lambda v: self._set_canvas("snap_to_grid", v))
        form.addRow("Snap to grid", snap)
        self._build_guides(form, canvas)

        if not onscreen:
            top = QtWidgets.QCheckBox()
            top.setChecked(bool(canvas.get("always_on_top")))
            top.toggled.connect(lambda v: self._set_canvas("always_on_top", v))
            form.addRow("Always on top", top)

            frameless = QtWidgets.QCheckBox()
            frameless.setChecked(bool(canvas.get("frameless")))
            frameless.toggled.connect(lambda v: self._set_canvas("frameless", v))
            form.addRow("Frameless", frameless)

            drag = QtWidgets.QCheckBox()
            drag.setChecked(bool(canvas.get("show_drag_bar", True)))
            drag.toggled.connect(lambda v: self._set_canvas("show_drag_bar", v))
            form.addRow("Overlay drag bar", drag)

        reset = QtWidgets.QPushButton("Reset position")
        if onscreen:
            reset.setToolTip("Use the primary monitor if the saved display is gone.")
        else:
            reset.setToolTip("Clear the saved window position and center this overlay. Also used if the saved monitor is gone.")
        reset.clicked.connect(lambda _=False: self._reset_page_position())
        form.addRow(reset)
        self._build_toggle_binding()

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
        buttons = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        add_v = QtWidgets.QPushButton("Add vertical")
        add_v.setToolTip("Add a vertical guide. Widgets snap left, center, or right to it.")
        add_v.clicked.connect(lambda _=False: self._add_guide("v"))
        add_h = QtWidgets.QPushButton("Add horizontal")
        add_h.setToolTip("Add a horizontal guide. Widgets snap top, center, or bottom to it.")
        add_h.clicked.connect(lambda _=False: self._add_guide("h"))
        row.addWidget(add_v)
        row.addWidget(add_h)
        row.addStretch()
        form.addRow("Guides", buttons)
        hint = QtWidgets.QLabel("Drag a guide on the canvas, or enter a percent of width (vertical) or height (horizontal).")
        hint.setWordWrap(True)
        form.addRow(hint)
        for guide in canvas.get("guides") or []:
            form.addRow("", self._guide_row(guide))

    def _guide_row(self, guide: dict) -> QtWidgets.QWidget:
        axis = "H" if guide.get("axis") == "h" else "V"
        gid = guide.get("id")
        percent = max(0.0, min(100.0, float(guide.get("position") or 0) * 100.0))
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        axis_label = QtWidgets.QLabel(axis)
        axis_label.setFixedWidth(14)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(0, 1000)
        slider.setValue(int(round(percent * 10)))
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(0.0, 100.0)
        spin.setDecimals(1)
        spin.setSuffix(" %")
        spin.setValue(percent)
        spin.setMaximumWidth(84)
        color = ColorButton(guide.get("color") or DEFAULT_GUIDE_COLOR)
        color.setFixedWidth(36)
        delete = QtWidgets.QPushButton("×")
        delete.setFixedWidth(24)
        delete.setToolTip("Remove this guide")

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
        form = self._section("Geometry")
        if self._multi:
            types = sorted({(w.get("type") or "").replace("_", " ") for w in self.scene.selected_widgets()})
            form.addRow("Selection", QtWidgets.QLabel(f"{len(self._edit_ids)} grouped widgets"))
            form.addRow("Types", QtWidgets.QLabel(", ".join(types)))
        else:
            type_label = QtWidgets.QLabel(item.get("type", "").replace("_", " "))
            form.addRow("Type", type_label)
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
            spin = QtWidgets.QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(int(self._common_field(lambda w: int(w.get(key) or 0), int(item.get(key) or 0))))
            spin.valueChanged.connect(lambda v, k=key, wid=item["id"]: self._update(wid, **{k: int(v)}))
            form.addRow(key.upper(), spin)

        self._rotation_slider(form, item)

        self._style_bool(
            form,
            item,
            "auto_scale_font",
            "Scale font with size",
            tooltip="Keep the same relative font size when this widget is resized.",
        )
        self._build_visibility(item)

        label_form = self._section("Label")
        widget_type = canonical_widget_type(item.get("type"))
        show_mode = widget_type == "label" and bool((item.get("style") or {}).get("show_current_mode"))
        if not self._multi:
            if show_mode:
                from .bindings import current_profile_mode

                label = QtWidgets.QLineEdit(current_profile_mode())
                label.setReadOnly(True)
                label.setToolTip("This label follows the active profile mode. Uncheck Show current mode to type your own text.")
            else:
                label = QtWidgets.QLineEdit(item.get("label") or "")
                label.editingFinished.connect(lambda wid=item["id"], w=label: self._update(wid, label=w.text()))
            label_form.addRow("Text", label)
        if not show_mode:
            self._style_bool(label_form, item, "show_label", "Show label")
        if widget_type == "label":
            mode_box = QtWidgets.QCheckBox()
            mode_box.setChecked(show_mode)
            mode_box.setToolTip(
                "Replace this label’s text with the profile mode that is currently active. "
                "It updates live when you change edit mode, or when the runtime mode changes while the profile is running."
            )
            mode_box.toggled.connect(lambda v, wid=item["id"]: self._set_show_current_mode(wid, bool(v)))
            label_form.addRow("Show current mode", mode_box)
            if show_mode:
                hint = QtWidgets.QLabel("Updates live: edit mode now, runtime mode while the profile is running.")
                hint.setWordWrap(True)
                label_form.addRow(hint)
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
        widget_type = canonical_widget_type(item.get("type"))
        if widget_type == "label":
            self._style_color(label_form, item, "fill", "Fill")
            self._style_color(label_form, item, "border", "Border")
            self._style_float(label_form, item, "border_width", "Border width", 0, 20)
            self._style_float(label_form, item, "corner_radius", "Corner radius", 0, 200)

        look = self._section("Appearance")
        self._build_palettes(look, item)
        self._opacity_slider(look, item)
        if widget_type == "button":
            if button_uses_shape_path(item):
                self._shape_appearance(look, item, for_button=True)
            else:
                shape = QtWidgets.QComboBox()
                shape.addItems(["rounded", "rect", "circle", "pill"])
                shape.setCurrentText(item["style"].get("shape") or "rounded")
                shape.currentTextChanged.connect(lambda v, wid=item["id"]: self._style(wid, shape=v))
                look.addRow("Shape", shape)
                self._style_color(look, item, "fill", "Off fill")
                self._style_color(look, item, "fill_on", "On fill")
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
            steps = QtWidgets.QSpinBox()
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
            steps = QtWidgets.QSpinBox()
            steps.setRange(3, 32)
            steps.setValue(int(item["style"].get("radio_steps") or 8))
            steps.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, radio_steps=int(v)))
            look.addRow("Rungs", steps)
            thumb = QtWidgets.QDoubleSpinBox()
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
            ticks = QtWidgets.QSpinBox()
            ticks.setRange(2, 48)
            ticks.setValue(int(item["style"].get("radio_steps") or 11))
            ticks.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, radio_steps=int(v)))
            look.addRow("Ticks", ticks)
            self._style_bool(look, item, "invert_display", "Invert")
        elif widget_type == "axis_encoder":
            self._style_color(look, item, "fill", "Off fill")
            self._style_color(look, item, "fill_on", "On fill")
            self._style_color(look, item, "grid", "Ticks")
            ring = QtWidgets.QDoubleSpinBox()
            ring.setRange(0, 80)
            ring.setSingleStep(1)
            ring.setSpecialValueText("Auto")
            ring.setValue(float(item["style"].get("needle_width") or 0))
            ring.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, needle_width=float(v)))
            look.addRow("Ring thickness", ring)
            ticks = QtWidgets.QSpinBox()
            ticks.setRange(4, 48)
            ticks.setValue(int(item["style"].get("radio_steps") or 16))
            ticks.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, radio_steps=int(v)))
            look.addRow("Steps", ticks)
            self._style_bool(look, item, "invert_display", "Invert")
        elif widget_type in ("axis_stick_square", "axis_stick_circle", "axis_crosshair", "hat"):
            self._style_color(look, item, "fill", "Fill")
            self._style_color(look, item, "indicator", "Dot")
            self._style_float(look, item, "indicator_size", "Dot size", 2, 80)
            if widget_type == "hat":
                positions = QtWidgets.QComboBox()
                positions.addItem("4-position", 4)
                positions.addItem("8-position", 8)
                current = 8 if int(item["style"].get("hat_positions") or 4) >= 8 else 4
                positions.setCurrentIndex(1 if current == 8 else 0)
                positions.currentIndexChanged.connect(
                    lambda _i, box=positions, wid=item["id"]: self._style(wid, hat_positions=int(box.currentData() or 4))
                )
                look.addRow("Positions", positions)
                self._crosshair_appearance(look, item, show_toggle=False)
            else:
                self._indicator_shape(look, item)
                self._style_bool(look, item, "show_dot_shadow", "Dot shadow")
                self._style_bool(look, item, "show_dot_crosshair", "Lines through dot")
                if widget_type in ("axis_stick_circle", "axis_crosshair"):
                    self._angle_step_combo(look, item)
                    rings = QtWidgets.QSpinBox()
                    rings.setRange(1, 8)
                    rings.setValue(int(item["style"].get("ring_count") or 3))
                    rings.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, ring_count=int(v)))
                    look.addRow("Rings", rings)
                self._grid_appearance(look, item)
                self._crosshair_appearance(look, item)
        elif widget_type == "switch_4way":
            appearance = QtWidgets.QComboBox()
            appearance.addItem("Arrows", "arrows")
            appearance.addItem("Arcs", "arcs")
            current = normalize_switch_appearance(item["style"].get("switch_appearance"))
            appearance.setCurrentIndex(0 if current == "arrows" else 1)
            appearance.currentIndexChanged.connect(
                lambda _i, wid=item["id"], box=appearance: self._style(
                    wid, switch_appearance=str(box.currentData() or "arrows"), rebuild=True
                )
            )
            look.addRow("Style", appearance)
            self._style_color(look, item, "fill", "Inactive")
            self._style_color(look, item, "fill_on", "Active")
            self._style_color(look, item, "indicator", "Center")
            self._style_float(look, item, "indicator_size", "Center size", 10, 100)
        elif widget_type in ("switch_2way", "switch_3way"):
            self._orientation_combo(look, item)
            self._style_color(look, item, "fill", "Housing")
            self._style_color(look, item, "fill_on", "Active fill")
        elif widget_type in ("shape", "panel"):
            self._shape_appearance(look, item)
        elif widget_type == "image":
            self._image_appearance(look, item)
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
        form = self._section("Geometry")
        form.addRow("Selection", QtWidgets.QLabel(f"{len(items)} grouped widgets"))
        form.addRow("Types", QtWidgets.QLabel(", ".join(sorted((t or "").replace("_", " ") for t in types))))
        for key, lo, hi in (("w", 8, 4000), ("h", 8, 4000), ("z", -100, 100)):
            spin = QtWidgets.QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(int(self._common_field(lambda w, k=key: int(w.get(k) or 0), int(item.get(key) or 0))))
            spin.valueChanged.connect(lambda v, k=key, wid=item["id"]: self._update(wid, **{k: int(v)}))
            form.addRow(key.upper(), spin)
        self._rotation_slider(form, item)
        self._style_bool(
            form,
            item,
            "auto_scale_font",
            "Scale font with size",
            tooltip="Keep the same relative font size when this widget is resized.",
        )
        self._build_visibility(item)

        label_form = self._section("Label")
        self._style_bool(label_form, item, "show_label", "Show label")
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
        if types <= {"switch_4way"}:
<<<<<<< Updated upstream
<<<<<<< Updated upstream
            self._style_color(look, item, "indicator", "Knob")
            self._style_color(look, item, "track", "Inner fill")
            self._style_color(look, item, "crosshair", "Direction fill")
            self._style_float(look, item, "corner_radius", "Direction radius", 0, 80)
=======
=======
>>>>>>> Stashed changes
            appearance = QtWidgets.QComboBox()
            appearance.addItem("Arrows", "arrows")
            appearance.addItem("Arcs", "arcs")
            current = normalize_switch_appearance(item["style"].get("switch_appearance"))
            appearance.setCurrentIndex(0 if current == "arrows" else 1)
            appearance.currentIndexChanged.connect(
                lambda _i, wid=item["id"], box=appearance: self._style(
                    wid, switch_appearance=str(box.currentData() or "arrows"), rebuild=True
                )
            )
            look.addRow("Style", appearance)
            self._style_color(look, item, "indicator", "Center")
            self._style_float(look, item, "indicator_size", "Center size", 10, 100)
            self._style_color(look, item, "fill", "Inactive")
<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
        if types <= {"switch_2way", "switch_3way"}:
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
        elif types <= {"axis_radio"}:
            self._border_appearance(look, item, colors=(("border", "Off border"), ("border_on", "Active border")), include_radius=False)
        else:
            include_radius = not types <= set(NO_CORNER_RADIUS_TYPES) and not types <= {"switch_4way"}
            self._border_appearance(look, item, include_radius=include_radius)

    def _visibility_for(self, item: dict) -> dict:
        return normalize_visibility(item.get("visibility") if isinstance(item.get("visibility"), dict) else default_visibility())

    def _visibility_summary(self, vis: dict) -> str:
        phrases = [self._visibility_condition_phrase(cond) for cond in vis.get("conditions") or []]
        if not phrases:
            return "Always shown on the live overlay (no conditions)."
        join = " and " if (vis.get("join") or "all") == "all" else " or "
        return f"If {join.join(phrases)} then display."

    def _visibility_condition_phrase(self, cond: dict) -> str:
        kind = str(cond.get("kind") or "mode").casefold()
        on = str(cond.get("when") or "on").casefold() != "off"
        if kind == "mode":
            name = str(cond.get("mode_name") or "").strip() or "(pick a mode)"
            return f"mode {name} is {'current' if on else 'not current'}"
        if kind == "state":
            name = str(cond.get("state_name") or "").strip() or "(pick a state)"
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
        vis_box = QtWidgets.QCheckBox()
        self._set_bool_widget(
            vis_box,
            [bool(w.get("visible", True)) for w in self.scene.selected_widgets()] or [bool(item.get("visible", True))],
        )
        vis_box.setToolTip("Master switch. Off hides this widget in the designer and on the live overlay.")
        vis_box.stateChanged.connect(lambda _s, wid=item["id"], box=vis_box: self._on_bool(box, wid, field="visible"))
        form.addRow("Visible", vis_box)

        join = QtWidgets.QComboBox()
        join.addItem("All of these (AND)", "all")
        join.addItem("Any of these (OR)", "any")
        join.setCurrentIndex(1 if (vis.get("join") or "all") == "any" else 0)
        join.setToolTip("All = every condition must be true. Any = at least one condition must be true.")
        join.currentIndexChanged.connect(
            lambda _i, box=join, wid=item["id"]: self._set_visibility(wid, rebuild=True, join=str(box.currentData() or "all"))
        )
        form.addRow("Match", join)

        hint = QtWidgets.QLabel(self._visibility_summary(vis))
        hint.setWordWrap(True)
        form.addRow(hint)
        note = QtWidgets.QLabel("The live overlay hides the widget when conditions fail. The designer keeps a faded copy so you can still edit it.")
        note.setWordWrap(True)
        form.addRow(note)

        for cond in vis.get("conditions") or []:
            form.addRow(self._visibility_condition_box(item, cond))

        add_kind = QtWidgets.QComboBox()
        add_kind.addItem("Mode", "mode")
        add_kind.addItem("State", "state")
        add_kind.addItem("Physical button", "physical")
        add_kind.addItem("vJoy button", "vjoy")
        add_kind.addItem("Keyboard/mouse", "keyboard")
        add_btn = QtWidgets.QPushButton("Add condition")
        add_btn.clicked.connect(
            lambda _=False, wid=item["id"], box=add_kind: self._add_visibility_condition(wid, str(box.currentData() or "mode"))
        )
        add_row = QtWidgets.QWidget()
        add_layout = QtWidgets.QHBoxLayout(add_row)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.addWidget(add_kind, 1)
        add_layout.addWidget(add_btn)
        form.addRow("Add", add_row)

    def _visibility_condition_box(self, item: dict, cond: dict) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox(self._visibility_condition_phrase(cond))
        form = QtWidgets.QFormLayout(box)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        cond_id = str(cond.get("id") or "")
        kind = str(cond.get("kind") or "mode").casefold()

        kind_box = QtWidgets.QComboBox()
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

        when = QtWidgets.QComboBox()
        if kind == "mode":
            when.addItem("is current", "on")
            when.addItem("is not current", "off")
        else:
            when.addItem("is on", "on")
            when.addItem("is off", "off")
        when.setCurrentIndex(1 if str(cond.get("when") or "on").casefold() == "off" else 0)
        when.currentIndexChanged.connect(
            lambda _i, combo=when, wid=item["id"], cid=cond_id: self._set_visibility_condition(
                wid, cid, when=str(combo.currentData() or "on")
            )
        )
        form.addRow("When", when)

        if kind == "mode":
            combo = QtWidgets.QComboBox()
            combo.addItem("", "")
            for display, name in profile_mode_choices():
                combo.addItem(display, name)
            current = str(cond.get("mode_name") or "")
            index = combo.findData(current)
            if index < 0 and current:
                combo.addItem(current, current)
                index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.currentIndexChanged.connect(
                lambda _i, combo=combo, wid=item["id"], cid=cond_id: self._set_visibility_condition(
                    wid, cid, mode_name=str(combo.currentData() or "")
                )
            )
            form.addRow("Mode", combo)
        elif kind == "state":
            names = [""]
            try:
                from gremlin.ui import state_device

                names.extend(state_device.StateData().getStateNames())
            except Exception:
                pass
            combo = QtWidgets.QComboBox()
            combo.setEditable(True)
            combo.addItems(names)
            combo.setCurrentText(str(cond.get("state_name") or ""))
            combo.currentTextChanged.connect(
                lambda v, wid=item["id"], cid=cond_id: self._set_visibility_condition(wid, cid, state_name=v)
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

        remove = QtWidgets.QPushButton("Remove")
        remove.clicked.connect(lambda _=False, wid=item["id"], cid=cond_id: self._remove_visibility_condition(wid, cid))
        form.addRow("", remove)
        return box

    def _fill_visibility_input(self, form: QtWidgets.QFormLayout, item: dict, cond: dict):
        kind = str(cond.get("kind") or "physical").casefold()
        cond_id = str(cond.get("id") or "")
        device_box = QtWidgets.QComboBox()
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

        listen = QtWidgets.QPushButton("Listen...")
        listen.setToolTip("Assign from the next physical or vJoy button press")
        listen.clicked.connect(lambda _=False, it=item, cid=cond_id: self._listen_visibility(it, cid))
        form.addRow("", listen)

        device = self._device_from_combo(device_box, "vjoy" if kind == "vjoy" else "physical")
        id_box = QtWidgets.QComboBox()
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
            edit = QtWidgets.QLineEdit(item["style"].get(key) or "")
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
        orient = QtWidgets.QComboBox()
        orient.addItems(["vertical", "horizontal"])
        orient.setCurrentText(item["style"].get("orientation") or default)
        orient.currentTextChanged.connect(lambda v, wid=item["id"]: self._set_orientation(wid, v))
        form.addRow("Orientation", orient)

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
        shape = QtWidgets.QComboBox()
        shape.addItems(["circle", "square"])
        shape.setCurrentText(item["style"].get("indicator_shape") or "circle")
        shape.currentTextChanged.connect(lambda v, wid=item["id"]: self._style(wid, indicator_shape=v))
        form.addRow("Dot shape", shape)

    def _angle_step_combo(self, form, item):
        combo = QtWidgets.QComboBox()
        for label, value in (("Off", 0), ("15°", 15), ("30°", 30), ("45°", 45)):
            combo.addItem(label, value)
        current = int(item["style"].get("angle_step") or 0)
        index = {0: 0, 15: 1, 30: 2, 45: 3}.get(current, 0)
        combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(
            lambda _i, wid=item["id"], box=combo: self._style(wid, angle_step=int(box.currentData()))
        )
        form.addRow("Angle lines", combo)

    def _rotation_slider(self, form, item: dict):
        rotation = int(round(self._common_field(lambda w: widget_rotation_deg(w), widget_rotation_deg(item))))
        self._slider_int(
            form,
            "Rotation",
            rotation,
            -180,
            180,
            lambda v, wid=item["id"]: self._update(wid, rotation=int(v)),
            tooltip="Degrees clockwise. 0 is upright. Drag the round handle above the widget on the canvas; hold Shift to snap to 15°.",
            suffix="°",
            live_getter=lambda: int(round(self._common_field(lambda w: widget_rotation_deg(w), 0))),
        )

    def _slider_int(self, form, title: str, value: int, lo: int, hi: int, on_change, tooltip=None, suffix=None, live_getter=None):
        value = int(value)
        lo, hi = int(lo), int(hi)
        if hi < lo:
            lo, hi = hi, lo
        if value < lo:
            lo = value
        if value > hi:
            hi = value
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(value)
        spin = QtWidgets.QSpinBox()
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

    def _build_palettes(self, form, item: dict):
        widget_type = palette_type(item.get("type"))
        form.addRow("Default palettes", self._palette_swatch_row(widget_type, list_builtin_palettes(widget_type), editable=False))
        form.addRow("User palettes", self._palette_swatch_row(widget_type, list_user_palettes(widget_type), editable=True, add_new=True))

    def _palette_swatch_row(self, widget_type: str, palettes: list, editable: bool, add_new: bool = False) -> QtWidgets.QWidget:
        host = QtWidgets.QWidget()
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
            add_btn = QtWidgets.QPushButton("+")
            add_btn.setFixedSize(28, 28)
            add_btn.setToolTip("Save the current colors as a new user palette for this widget type.")
            add_btn.clicked.connect(lambda _=False: self._add_saved_palette(widget_type))
            layout.addWidget(add_btn)
        layout.addStretch()
        return host

    def _current_palette_colors(self) -> dict[str, str]:
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
        label = QtWidgets.QLabel(title)
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
        dead = QtWidgets.QDoubleSpinBox()
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
        if colors:
            for key, title in colors:
                self._style_color(form, item, key, title)
        else:
            self._style_color(form, item, "border", "Border")
        self._style_float(form, item, "border_width", "Border width", 0, 20)
        if include_radius:
            self._style_float(form, item, "corner_radius", "Corner radius", 0, 200)

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
        elif widget_type not in ("label", "shape", "panel", "image", "streamdeck"):
            include_radius = widget_type not in NO_CORNER_RADIUS_TYPES and widget_type != "switch_4way"
            self._border_appearance(look, item, include_radius=include_radius)
        if widget_type not in NO_BINDING_WIDGET_TYPES and not self._multi:
            self._build_binding(item)

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
        kind = QtWidgets.QComboBox()
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
            hint = QtWidgets.QLabel(
                shape_kind_tooltip(current)
                + " Dragging a handle past the widget edge grows the shape. Delete removes the selected point."
            )
            hint.setWordWrap(True)
            hint.setToolTip(hint.text())
            form.addRow(hint)
        if for_button:
            self._style_color(form, item, "fill", "Off fill")
            self._style_color(form, item, "fill_on", "On fill")
            return
        self._style_color(form, item, "fill", "Fill")
        self._look_heading(form, "Border")
        self._style_color(form, item, "border", "Border")
        self._style_float(form, item, "border_width", "Border width", 0, 20)
        if current == "rectangle":
            self._style_float(form, item, "corner_radius", "Corner radius", 0, 200)

    def _image_appearance(self, form, item: dict):
        path_row = QtWidgets.QWidget()
        path_layout = QtWidgets.QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_edit = QtWidgets.QLineEdit(item["style"].get("image_path") or "")
        browse = QtWidgets.QPushButton("...")
        browse.setFixedWidth(28)
        browse.setToolTip("Choose an image file.")
        browse.clicked.connect(lambda _=False, wid=item["id"]: self._browse_image(wid))
        paste = QtWidgets.QPushButton("Paste")
        paste.setToolTip("Paste a screenshot from the clipboard (Windows Snipping Tool / Win+Shift+S).")
        paste.clicked.connect(lambda _=False, wid=item["id"]: self._paste_image(wid))
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
        hint = QtWidgets.QLabel("PNG, WebP, and GIF keep their transparency. Fill is only a backdrop behind those pixels. JPEG has no alpha.")
        hint.setWordWrap(True)
        form.addRow(hint)
        self._style_color(form, item, "fill", "Fill")
        self._look_heading(form, "Border")
        self._style_color(form, item, "border", "Border")
        self._style_float(form, item, "border_width", "Border width", 0, 20)

    def _mouse_appearance(self, form, item: dict):
        style = item.get("style") or {}
        mode = QtWidgets.QComboBox()
        mode.addItem("VJoy", "vjoy")
        mode.addItem("Standard", "standard")
        current = normalize_mouse_mode(style.get("mouse_mode"))
        index = mode.findData(current)
        if index >= 0:
            mode.setCurrentIndex(index)
        mode.currentIndexChanged.connect(
            lambda _i, box=mode, wid=item["id"]: self._on_mouse_mode(wid, str(box.currentData() or "vjoy"))
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
            idle = QtWidgets.QDoubleSpinBox()
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
        period = QtWidgets.QDoubleSpinBox()
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
        vmin = QtWidgets.QDoubleSpinBox()
        vmin.setRange(-10000.0, 10000.0)
        vmin.setDecimals(3)
        vmin.setSingleStep(0.1)
        try:
            vmin.setValue(float(style.get("value_min") if style.get("value_min") is not None else -1.0))
        except (TypeError, ValueError):
            vmin.setValue(-1.0)
        vmin.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, value_min=float(v)))
        form.addRow("Min", vmin)
        vmax = QtWidgets.QDoubleSpinBox()
        vmax.setRange(-10000.0, 10000.0)
        vmax.setDecimals(3)
        vmax.setSingleStep(0.1)
        try:
            vmax.setValue(float(style.get("value_max") if style.get("value_max") is not None else 1.0))
        except (TypeError, ValueError):
            vmax.setValue(1.0)
        vmax.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, value_max=float(v)))
        form.addRow("Max", vmax)
        unit = QtWidgets.QLineEdit(str(style.get("unit") or ""))
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
        auto = QtWidgets.QCheckBox()
        auto.setChecked(bool(style.get("range_auto", True)))
        auto.setToolTip("Use −100…+100 when any selected axis is centered; 0…100 when every axis is 0–100%.")
        auto.toggled.connect(lambda v, wid=item["id"]: self._style(wid, rebuild=True, range_auto=bool(v)))
        form.addRow("Auto range", auto)
        vmin, vmax = bars_value_range(item)
        lo = QtWidgets.QDoubleSpinBox()
        lo.setRange(-10000.0, 10000.0)
        lo.setDecimals(1)
        lo.setSuffix(" %")
        lo.setValue(float(style.get("value_min") if style.get("value_min") is not None else vmin))
        lo.setEnabled(not bool(style.get("range_auto", True)))
        lo.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, value_min=float(v)))
        form.addRow("Min", lo)
        hi = QtWidgets.QDoubleSpinBox()
        hi.setRange(-10000.0, 10000.0)
        hi.setDecimals(1)
        hi.setSuffix(" %")
        hi.setValue(float(style.get("value_max") if style.get("value_max") is not None else vmax))
        hi.setEnabled(not bool(style.get("range_auto", True)))
        hi.valueChanged.connect(lambda v, wid=item["id"]: self._style(wid, value_max=float(v)))
        form.addRow("Max", hi)
        if bool(style.get("range_auto", True)):
            note = QtWidgets.QLabel(f"Current scale: {vmin:g} to {vmax:g} %")
            note.setWordWrap(True)
            form.addRow(note)
        self._style_bool(form, item, "show_legend", "Show legend")
        self._grid_appearance(form, item)

    def _stats_appearance(self, form, item: dict):
        style = item.get("style") or {}
        self._style_color(form, item, "fill", "Fill")
        self._orientation_combo(form, item)
        clock = QtWidgets.QComboBox()
        clock.addItem("24-hour", "24h")
        clock.addItem("12-hour", "12h")
        clock.setCurrentIndex(1 if str(style.get("time_format") or "24h").casefold() in ("12h", "12", "ampm") else 0)
        clock.currentIndexChanged.connect(
            lambda _i, box=clock, wid=item["id"]: self._style(wid, time_format=str(box.currentData() or "24h"))
        )
        form.addRow("Time format", clock)
        unit = QtWidgets.QComboBox()
        unit.addItem("Celsius", "C")
        unit.addItem("Fahrenheit", "F")
        unit.setCurrentIndex(1 if str(style.get("temp_unit") or "C").casefold() == "f" else 0)
        unit.currentIndexChanged.connect(
            lambda _i, box=unit, wid=item["id"]: self._style(wid, temp_unit=str(box.currentData() or "C"))
        )
        form.addRow("Temperature", unit)
        self._style_bool(form, item, "show_caption", "Show stat names")
        hint = QtWidgets.QLabel(
            "Add one or more stats in Datasets, each with its own color. FPS is in-game (MSI Afterburner / RTSS). "
            "A Manual counter increments and decrements from keybinds."
        )
        hint.setWordWrap(True)
        form.addRow(hint)

    def _stats_for(self, item: dict) -> list[dict]:
        return normalize_stat_series(item.get("stats"), (item.get("style") or {}).get("stat") or "time")

    def _build_stat_datasets(self, item: dict):
        form = self._section("Datasets")
        hint = QtWidgets.QLabel("Each dataset is one value on this counter. Pick a color per row. Remove all but one if you only need a single reading.")
        hint.setWordWrap(True)
        form.addRow(hint)
        stats = self._stats_for(item)
        for index, entry in enumerate(stats):
            form.addRow(self._stat_entry_box(item, entry, index))
        add = QtWidgets.QPushButton("Add stat")
        add.clicked.connect(lambda _=False, wid=item["id"]: self._add_stat_entry(wid))
        form.addRow(add)

    def _stat_entry_box(self, item: dict, entry: dict, index: int) -> QtWidgets.QGroupBox:
        from .sys_stats import STAT_CHOICES, normalize_stat, stat_caption

        kind = normalize_stat(entry.get("stat"))
        title = str(entry.get("label") or "").strip() or stat_caption(kind)
        box = QtWidgets.QGroupBox(f"{index + 1}. {title}")
        form = QtWidgets.QFormLayout(box)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        sid = str(entry.get("id") or "")
        combo = QtWidgets.QComboBox()
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
        label = QtWidgets.QLineEdit(str(entry.get("label") or ""))
        label.setPlaceholderText(stat_caption(kind))
        label.editingFinished.connect(lambda wid=item["id"], ident=sid, w=label: self._set_stat_entry(wid, ident, label=w.text()))
        form.addRow("Caption", label)
        if kind == "manual":
            step = QtWidgets.QSpinBox()
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
            remove = QtWidgets.QPushButton("Remove")
            remove.clicked.connect(lambda _=False, wid=item["id"], ident=sid: self._remove_stat_entry(wid, ident))
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
        face = QtWidgets.QComboBox()
        face.addItem("Digital counter", "digital")
        face.addItem("Analog watch", "analog")
        face.setCurrentIndex(1 if normalize_stopwatch_face(style.get("stopwatch_face")) == "analog" else 0)
        face.currentIndexChanged.connect(
            lambda _i, box=face, wid=item["id"]: self._style(wid, rebuild=True, stopwatch_face=str(box.currentData() or "digital"))
        )
        form.addRow("Display", face)
        fmt = QtWidgets.QComboBox()
        fmt.addItem("mm:ss", "mmss")
        fmt.addItem("hh:mm:ss", "hhmmss")
        fmt.setCurrentIndex(1 if normalize_stopwatch_format(style.get("stopwatch_format")) == "hhmmss" else 0)
        fmt.currentIndexChanged.connect(
            lambda _i, box=fmt, wid=item["id"]: self._style(wid, stopwatch_format=str(box.currentData() or "mmss"))
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
        graphic = QtWidgets.QComboBox()
        current = normalize_mouse_graphic(style.get("mouse_graphic"))
        for key, label in MOUSE_GRAPHIC_CHOICES:
            graphic.addItem(label, key)
        index = graphic.findData(current)
        graphic.setCurrentIndex(index if index >= 0 else 0)
        graphic.setToolTip("Silhouette is a top-down mouse. Button map labels every mouse button (M1–M5, wheel, tilt).")
        graphic.currentIndexChanged.connect(
            lambda _i, box=graphic, wid=item["id"]: self._style(wid, mouse_graphic=str(box.currentData() or "silhouette"))
        )
        form.addRow("Mouse graphic", graphic)

    def _build_input_display_keys(self, item: dict):
        from .input_display import PRESET_CHOICES, matching_preset

        form = self._section("Keys")
        hint = QtWidgets.QLabel(
            "Presets match common streaming layouts. Select keys… opens the same virtual keyboard as Map to Keyboard/Mouse Ex. "
            "Only selected keys and mouse buttons are drawn."
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        preset = QtWidgets.QComboBox()
        current = matching_preset(item)
        for key, label in PRESET_CHOICES:
            preset.addItem(label, key)
        index = preset.findData(current)
        preset.setCurrentIndex(index if index >= 0 else preset.findData("custom"))
        preset.currentIndexChanged.connect(
            lambda _i, box=preset, wid=item["id"]: self._apply_input_display_preset(wid, str(box.currentData() or "custom"))
        )
        form.addRow("Preset", preset)
        count = QtWidgets.QLabel(f"{len(item.get('keys') or [])} selected")
        form.addRow("Selection", count)
        select = gremlin.ui.ui_common.QIconPushButton("Select keys...")
        select.setIcon(gremlin.util.load_icon("mdi.keyboard-settings-outline", qta_color=gremlin.ui.ui_common.Color.listenColor()))
        select.setToolTip("Choose keys and mouse buttons on the virtual keyboard.")
        select.setFixedHeight(24)
        select.clicked.connect(lambda _=False, wid=item["id"]: self._open_input_display_picker(wid))
        form.addRow(select)
        all_btn = QtWidgets.QPushButton("Select all")
        all_btn.clicked.connect(lambda _=False, wid=item["id"]: self._select_all_input_display_keys(wid))
        none_btn = QtWidgets.QPushButton("Deselect all")
        none_btn.clicked.connect(lambda _=False, wid=item["id"]: self._clear_input_display_keys(wid))
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
            hint = QtWidgets.QLabel(
                "Each dataset is one physical or vJoy axis. Pick Centered (−100 to +100) or 0 to 100% per axis. "
                "Bar colors match the graph. Auto range uses negatives only when a centered axis is selected."
            )
        else:
            hint = QtWidgets.QLabel("Each dataset is one physical or vJoy axis. Colors match the plot and legend.")
        hint.setWordWrap(True)
        form.addRow(hint)
        series = self._series_for(item)
        for index, entry in enumerate(series):
            form.addRow(self._graph_series_box(item, entry, index))
        add = QtWidgets.QPushButton("Add dataset")
        add.clicked.connect(lambda _=False, wid=item["id"]: self._add_graph_series(wid))
        form.addRow(add)

    def _graph_series_box(self, item: dict, series: dict, index: int) -> QtWidgets.QGroupBox:
        from .graph_track import graph_series_label

        box = QtWidgets.QGroupBox(graph_series_label(series))
        form = QtWidgets.QFormLayout(box)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        series_id = str(series.get("id") or "")
        source = QtWidgets.QComboBox()
        source.addItem("physical", "physical")
        source.addItem("vjoy", "vjoy")
        src = str(series.get("source") or "physical").casefold()
        source.setCurrentIndex(1 if src == "vjoy" else 0)
        source.currentIndexChanged.connect(
            lambda _i, combo=source, wid=item["id"], sid=series_id: self._set_graph_series(
                wid, sid, rebuild=True, source=str(combo.currentData() or "physical")
            )
        )
        form.addRow("Source", source)

        device_box = QtWidgets.QComboBox()
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

        listen = QtWidgets.QPushButton("Listen...")
        listen.setToolTip("Assign from the next matching physical or vJoy axis")
        listen.clicked.connect(lambda _=False, it=item, sid=series_id: self._listen_graph_series(it, sid))
        form.addRow("", listen)

        device = self._device_from_combo(device_box, "vjoy" if src == "vjoy" else "physical")
        id_box = QtWidgets.QComboBox()
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

        label = QtWidgets.QLineEdit(str(series.get("label") or ""))
        label.setPlaceholderText("Legend name (optional)")
        label.editingFinished.connect(
            lambda wid=item["id"], sid=series_id, w=label: self._set_graph_series(wid, sid, rebuild=True, label=w.text())
        )
        form.addRow("Name", label)

        inv = QtWidgets.QCheckBox()
        inv.setChecked(bool(series.get("invert")))
        inv.toggled.connect(lambda v, wid=item["id"], sid=series_id: self._set_graph_series(wid, sid, invert=bool(v)))
        form.addRow("Invert", inv)

        if item.get("type") == "axis_bars":
            range_box = QtWidgets.QComboBox()
            range_box.addItem("Auto", "auto")
            range_box.addItem("Centered (−100 to +100)", "centered")
            range_box.addItem("0 to 100%", "unipolar")
            current_mode = normalize_series_range_mode(series.get("range_mode") or series.get("centered"))
            index = range_box.findData(current_mode)
            range_box.setCurrentIndex(index if index >= 0 else 0)
            range_box.setToolTip(
                "Centered stick axes plot from −100 to +100. Throttles and sliders are typically 0 to 100%. "
                "Auto guesses from the axis name (S1/S2 and throttle-like names are 0–100)."
            )
            range_box.currentIndexChanged.connect(
                lambda _i, wid=item["id"], sid=series_id, combo=range_box: self._set_graph_series(
                    wid, sid, rebuild=True, range_mode=str(combo.currentData() or "auto")
                )
            )
            form.addRow("Range", range_box)

        remove = QtWidgets.QPushButton("Remove")
        remove.clicked.connect(lambda _=False, wid=item["id"], sid=series_id: self._remove_graph_series(wid, sid))
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
            form.addRow(QtWidgets.QLabel("Stream Deck bridge is unavailable."))
            return

        style = item.get("style") or {}
        wanted = str(style.get("streamdeck_device_id") or "")
        combo = QtWidgets.QComboBox()
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
        page_combo = QtWidgets.QComboBox()
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

        follow_box = QtWidgets.QCheckBox()
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
        fit = QtWidgets.QPushButton("Fit to device")
        fit.setToolTip("Resize this widget to the key layout of the selected Stream Deck.")
        fit.clicked.connect(lambda _=False, wid=item["id"]: self._fit_streamdeck_item(wid, force=True))
        form.addRow(fit)
        hint = QtWidgets.QLabel("Mirrors the selected deck’s keys (and Stream Deck + dials) using the current GEX page art.")
        hint.setWordWrap(True)
        form.addRow(hint)
        self._style_color(form, item, "fill", "Bezel")
        self._look_heading(form, "Border")
        self._style_color(form, item, "border", "Border")
        self._style_float(form, item, "border_width", "Border width", 0, 20)
        self._style_float(form, item, "corner_radius", "Corner radius", 0, 200)

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

    def _browse_image(self, widget_id: str):
        if self._building:
            return
        item = self.scene.widget_by_id(widget_id)
        if not item:
            return
        start = (item.get("style") or {}).get("image_path") or ""
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Overlay image",
            start,
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif)",
        )
        if not fname:
            return
        self.scene.push_undo()
        item["style"]["image_path"] = fname
        self._fit_item_to_image(item, fname)
        self.scene._dirty = True
        self.scene._emit()
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
        from .images import fit_item_to_image_size

        image = QtGui.QImage(path)
        if image.isNull():
            return
        fit_item_to_image_size(item, image.width(), image.height(), self.scene.canvas)

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
        spin = QtWidgets.QDoubleSpinBox()
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
        box = QtWidgets.QCheckBox()
        self._set_bool_widget(box, values)
        if tooltip:
            box.setToolTip(tooltip)
        box.stateChanged.connect(lambda _s, wid=item["id"], k=key, b=box: self._on_bool(b, wid, style_key=k))
        form.addRow(title, box)

    def _style_font(self, form, item, prefix=""):
        family_key = f"{prefix}font_family"
        size_key = f"{prefix}font_size"
        bold_key = f"{prefix}font_bold"
        combo = QtWidgets.QFontComboBox()
        family = item["style"].get(family_key) or item["style"].get("font_family") or "Segoe UI"
        combo.setCurrentFont(QtGui.QFont(family))
        idx = combo.findText(family)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.currentTextChanged.connect(lambda v, wid=item["id"], k=family_key: self._style(wid, **{k: v}))
        size = QtWidgets.QSpinBox()
        size.setRange(6, 192)
        size.setValue(effective_font_size(item, size_key))
        size.setToolTip("Drawn font size. Updates while the widget is resized when Scale font with size is on.")
        size.valueChanged.connect(lambda v, wid=item["id"], k=size_key: self._style(wid, **{k: int(v)}))
        self._bind_live(size, lambda it=item, k=size_key: effective_font_size(it, k))
        bold = QtWidgets.QCheckBox()
        bold.setChecked(bool(item["style"].get(bold_key, item["style"].get("font_bold", True))))
        bold.toggled.connect(lambda v, wid=item["id"], k=bold_key: self._style(wid, **{k: v}))
        label = "Axis font" if prefix else "Font"
        form.addRow(label, combo)
        form.addRow(f"{label} size", size)
        form.addRow(f"{label} bold", bold)

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
                "switch_2way": "Two positions. On an Interactive overlay the last side you press stays latched.",
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
        source = QtWidgets.QComboBox()
        for value in sources:
            source.addItem("keyboard/mouse" if value == "keyboard" else value, value)
        current_source = binding.get("source") or "physical"
        if current_source in ("keyboard/mouse", "mouse"):
            current_source = "keyboard"
        if current_source not in sources:
            current_source = "physical"
        index = source.findData(current_source)
        source.setCurrentIndex(index if index >= 0 else 0)
        source.currentIndexChanged.connect(
            lambda _i, box=source, wid=item["id"], ch=channel: self._bind(
                wid,
                ch,
                rebuild=True,
                source=str(box.currentData() or "physical"),
                input_type="keyboard" if str(box.currentData() or "") == "keyboard" else (force_type or binding.get("input_type") or "button"),
            )
        )
        form.addRow("Source", source)

        if source.currentData() == "state":
            names = [""]
            try:
                from gremlin.ui import state_device

                names.extend(state_device.StateData().getStateNames())
            except Exception:
                pass
            combo = QtWidgets.QComboBox()
            combo.setEditable(True)
            combo.addItems(names)
            combo.setCurrentText(binding.get("state_name") or "")
            combo.currentTextChanged.connect(lambda v, wid=item["id"], ch=channel: self._bind(wid, ch, state_name=v, input_type="state"))
            form.addRow("State", combo)
            self._finish_channel(form, item, channel, extra_hint, show_clear)
            return

        if source.currentData() == "mode":
            combo = QtWidgets.QComboBox()
            combo.addItem("", "")
            for display, name in profile_mode_choices():
                combo.addItem(display, name)
            current = str(binding.get("mode_name") or "")
            index = combo.findData(current)
            if index < 0 and current:
                combo.addItem(current, current)
                index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.currentIndexChanged.connect(
                lambda _i, box=combo, wid=item["id"], ch=channel: self._bind(
                    wid, ch, mode_name=str(box.currentData() or ""), input_type="mode"
                )
            )
            form.addRow("Mode", combo)
            self._finish_channel(form, item, channel, extra_hint, show_clear)
            return

        if source.currentData() == "keyboard":
            picker = OverlayKeyCombinationWidget(binding.get("keys") or [])
            picker.keys_changed.connect(
                lambda keys, wid=item["id"], ch=channel: self._bind(
                    wid, ch, keys=normalize_overlay_keys(keys), input_type="keyboard", source="keyboard"
                )
            )
            form.addRow(picker)
            self._finish_channel(form, item, channel, extra_hint, show_clear)
            return

        device_box = QtWidgets.QComboBox()
        if source.currentData() == "vjoy":
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

        listen = QtWidgets.QPushButton("Listen...")
        listen.setToolTip("Assign from the next matching physical or vJoy input")
        listen.clicked.connect(lambda _=False, it=item, ch=channel, kind=force_type: self._listen(it, ch, kind))
        form.addRow("", listen)

        input_kind = force_type or binding.get("input_type") or "axis"
        if not force_type:
            input_type = QtWidgets.QComboBox()
            types = ["axis", "button", "hat"]
            input_type.addItems(types)
            if input_kind not in types:
                input_kind = "axis"
            input_type.setCurrentText(input_kind)
            input_type.currentTextChanged.connect(lambda v, wid=item["id"], ch=channel: self._bind(wid, ch, rebuild=True, input_type=v))
            form.addRow("Input type", input_type)
        else:
            if binding.get("input_type") != force_type:
                binding["input_type"] = force_type
            input_kind = force_type

        device = self._device_from_combo(device_box, str(source.currentData() or "physical"))
        id_box = QtWidgets.QComboBox()
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
            inv = QtWidgets.QCheckBox()
            inv.setChecked(bool(binding.get("invert")))
            inv.toggled.connect(lambda v, wid=item["id"], ch=channel: self._bind(wid, ch, invert=v))
            form.addRow("Invert", inv)

        hint = QtWidgets.QLabel(self._channel_summary(binding, input_kind))
        hint.setWordWrap(True)
        form.addRow("Assigned", hint)
        self._finish_channel(form, item, channel, extra_hint, show_clear)

    def _finish_channel(self, form, item: dict, channel: str, extra_hint: str | None, show_clear: bool):
        if extra_hint:
            note = QtWidgets.QLabel(extra_hint)
            note.setWordWrap(True)
            form.addRow(note)
        if show_clear:
            clear = QtWidgets.QPushButton("Clear")
            clear.clicked.connect(
                lambda _=False, wid=item["id"], ch=channel: self._bind(
                    wid,
                    ch,
                    rebuild=True,
                    device_guid="",
                    device_name="",
                    vjoy_id=0,
                    input_id=0,
                    state_name="",
                    mode_name="",
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
            return binding.get("state_name") or "(none)"
        if source == "mode":
            return binding.get("mode_name") or "(none)"
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
        if channel.startswith("bindings."):
            position = channel.split(".", 1)[1]
            self.scene.apply_widget_update(widget_id, bindings={position: fields})
            if rebuild:
                self.rebuild()
            return
        self.scene.apply_widget_update(widget_id, **{channel: fields})
        if rebuild:
            self.rebuild()
