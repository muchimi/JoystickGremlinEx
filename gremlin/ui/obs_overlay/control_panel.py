# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Runtime control panel: anchors, visibility, and save for the live overlay."""

from __future__ import annotations

import logging

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

from gremlin.ui.ui_common import QDataPushButton

from .model import (
    ANCHOR_LABELS,
    OverlayScene,
    is_onscreen_mode,
)

syslog = logging.getLogger("system")

_REPOSITION_SETTINGS = ("Joystick Gremlin Ex", "Overlay")
_REPOSITION_SKIP_PROMPT_KEY = "skip_mouse_reposition_prompt"


def _skip_mouse_reposition_prompt() -> bool:
    return QtCore.QSettings(*_REPOSITION_SETTINGS).value(_REPOSITION_SKIP_PROMPT_KEY, False, type=bool)


def _set_skip_mouse_reposition_prompt(skip: bool):
    QtCore.QSettings(*_REPOSITION_SETTINGS).setValue(_REPOSITION_SKIP_PROMPT_KEY, bool(skip))


def _alive(widget) -> bool:
    try:
        return widget is not None and Shiboken.isValid(widget)
    except Exception:
        return False


class MouseRepositionBanner(QtWidgets.QWidget):
    """Top-of-screen advisory while mouse repositioning is enabled."""

    def __init__(self, parent=None):
        super().__init__(None)
        self.setObjectName("overlayMouseRepositionBanner")
        self.setWindowFlags(
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        label = QtWidgets.QLabel(
            "Mouse repositioning is ON — click and drag overlay widgets to move them. "
            "Interactive widgets are paused until this is turned off.",
            self,
        )
        label.setWordWrap(True)
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setStyleSheet(
            "QLabel {"
            "  color: #102018;"
            "  background: #7dffc8;"
            "  border: 1px solid #1a8f5c;"
            "  border-radius: 6px;"
            "  padding: 10px 16px;"
            "  font-size: 13px;"
            "  font-weight: 600;"
            "}"
        )
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        self._place()

    def _place(self):
        app = QtWidgets.QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            self.setFixedWidth(720)
            self.adjustSize()
            return
        geo = screen.availableGeometry()
        self.setFixedWidth(min(900, max(420, geo.width() - 80)))
        self.adjustSize()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + 12
        self.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        self._place()


_reposition_banner: MouseRepositionBanner | None = None


def sync_mouse_reposition_banner(enabled: bool):
    """Show or hide the top-of-screen mouse-reposition advisory."""
    global _reposition_banner
    if enabled:
        if _reposition_banner is None or not _alive(_reposition_banner):
            _reposition_banner = MouseRepositionBanner()
        _reposition_banner._place()
        _reposition_banner.show()
        _reposition_banner.raise_()
        return
    if _reposition_banner is not None and _alive(_reposition_banner):
        _reposition_banner.hide()
        _reposition_banner.close()
    _reposition_banner = None


class OverlayControlPanel(QtWidgets.QWidget):
    """Always-on-top utility for runtime overlay position and visibility."""

    def __init__(self, scene: OverlayScene, parent=None):
        # Always a true top-level window. Parenting to the designer/inspector
        # makes Qt disable this panel when the Overlay tab is runtime-locked.
        super().__init__(None)
        self.scene = scene
        self.setObjectName("overlayControlPanel")
        self.setWindowTitle("Overlay control")
        self.setWindowFlags(
            QtCore.Qt.Window
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.WindowCloseButtonHint
            | QtCore.Qt.WindowMinimizeButtonHint
            | QtCore.Qt.WindowTitleHint
        )
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setMinimumWidth(360)
        self._building = False
        self._hooks = False
        self._highlight_idle = QtCore.QTimer(self)
        self._highlight_idle.setSingleShot(True)
        self._highlight_idle.setInterval(2500)
        self._highlight_idle.timeout.connect(self._hide_control_highlight)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self._list_filter = "all"  # all | groups | widgets
        self._list_query = ""

        self._auto_launch = QtWidgets.QCheckBox("Auto launch at profile start", self)
        self._auto_launch.setToolTip(
            "When checked, this Overlay control panel opens automatically when the profile starts."
        )
        self._auto_launch.toggled.connect(self._on_auto_launch_toggled)
        root.addWidget(self._auto_launch)

        # --- Target ---
        target_box = QtWidgets.QGroupBox("Target", self)
        target_form = QtWidgets.QFormLayout(target_box)
        self._page_box = QtWidgets.QComboBox(self)
        self._page_box.currentIndexChanged.connect(self._on_page_changed)
        target_form.addRow("Page", self._page_box)

        filter_row = QtWidgets.QHBoxLayout()
        self._filter_box = QtWidgets.QComboBox(self)
        self._filter_box.addItem("All", "all")
        self._filter_box.addItem("Groups only", "groups")
        self._filter_box.addItem("Widgets only", "widgets")
        self._filter_box.setToolTip("Show entire page plus groups, only groups, or only widgets.")
        self._filter_box.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._filter_box, 0)
        self._search_edit = QtWidgets.QLineEdit(self)
        self._search_edit.setPlaceholderText("Filter by name…")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._on_search_changed)
        filter_row.addWidget(self._search_edit, 1)
        target_form.addRow("Show", filter_row)

        self._target_list = QtWidgets.QListWidget(self)
        self._target_list.setMinimumHeight(140)
        self._target_list.currentItemChanged.connect(self._on_target_item)
        target_form.addRow(self._target_list)
        root.addWidget(target_box)

        # --- Anchor points ---
        anchor_box = QtWidgets.QGroupBox("Anchor points", self)
        anchor_layout = QtWidgets.QVBoxLayout(anchor_box)
        pad = QtWidgets.QGridLayout()
        pad.setSpacing(4)
        self._anchor_buttons: dict[str, QtWidgets.QToolButton] = {}
        grid = [
            ("tl", 0, 0),
            ("tm", 0, 1),
            ("tr", 0, 2),
            ("ml", 1, 0),
            ("center", 1, 1),
            ("mr", 1, 2),
            ("bl", 2, 0),
            ("bm", 2, 1),
            ("br", 2, 2),
        ]
        short = {
            "tl": "↖",
            "tm": "↑",
            "tr": "↗",
            "ml": "←",
            "center": "●",
            "mr": "→",
            "bl": "↙",
            "bm": "↓",
            "br": "↘",
        }
        for key, row, col in grid:
            btn = QtWidgets.QToolButton(self)
            btn.setText(short[key])
            btn.setToolTip(ANCHOR_LABELS.get(key, key))
            btn.setFixedSize(40, 32)
            btn.setAutoRaise(False)
            btn.clicked.connect(lambda _checked=False, a=key: self._anchor(a))
            self._anchor_buttons[key] = btn
            pad.addWidget(btn, row, col)
        anchor_layout.addLayout(pad)

        self._cycle_btn = QDataPushButton(
            "Cycle anchor",
            parent=self,
            tooltip="Move to the next anchor point.",
            clicked=self._cycle,
        )
        self._cycle_btn.setMinimumHeight(32)
        self._cycle_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        anchor_layout.addWidget(self._cycle_btn)
        root.addWidget(anchor_box)

        # --- Nudge (keyboard arrow cluster) ---
        nudge_box = QtWidgets.QGroupBox("Nudge", self)
        nudge_outer = QtWidgets.QVBoxLayout(nudge_box)
        nudge_pad = QtWidgets.QGridLayout()
        nudge_pad.setSpacing(4)
        nudge_pad.setContentsMargins(0, 0, 0, 0)

        self._nudge_timer = QtCore.QTimer(self)
        self._nudge_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._nudge_timer.timeout.connect(self._on_nudge_tick)
        self._nudge_dir = (0, 0)
        self._nudge_step = 8
        self._nudge_ticks = 0
        self._nudge_buttons: list[QtWidgets.QToolButton] = []

        # Layout like a keyboard arrow cluster:
        #       [↑]
        #   [←] [↓] [→]
        def _nudge_btn(label: str, dx: int, dy: int) -> QtWidgets.QToolButton:
            btn = QtWidgets.QToolButton(self)
            btn.setText(label)
            btn.setToolTip(f"Nudge {label} — hold to keep moving (accelerates).")
            btn.setFixedSize(40, 32)
            btn.setAutoRaise(False)
            btn.setAutoRepeat(False)
            btn.pressed.connect(lambda ddx=dx, ddy=dy: self._start_nudge(ddx, ddy))
            btn.released.connect(self._stop_nudge)
            self._nudge_buttons.append(btn)
            return btn

        nudge_pad.addWidget(_nudge_btn("↑", 0, -1), 0, 1)
        nudge_pad.addWidget(_nudge_btn("←", -1, 0), 1, 0)
        nudge_pad.addWidget(_nudge_btn("↓", 0, 1), 1, 1)
        nudge_pad.addWidget(_nudge_btn("→", 1, 0), 1, 2)
        nudge_outer.addLayout(nudge_pad)
        hint = QtWidgets.QLabel("Hold an arrow to keep moving; speed increases while held.", self)
        hint.setWordWrap(True)
        nudge_outer.addWidget(hint)
        self._mouse_reposition = QtWidgets.QCheckBox("Enable mouse repositioning", self)
        self._mouse_reposition.setToolTip(
            "Drag widgets on the live overlay with the mouse. "
            "Click a widget to select it, then drag. Interactive widget input is suspended while this is on. "
            "Assign a keybind under Keybinds… → Toggle mouse repositioning."
        )
        self._mouse_reposition.toggled.connect(self._on_mouse_reposition_toggled)
        nudge_outer.addWidget(self._mouse_reposition)
        root.addWidget(nudge_box)

        # --- Visibility ---
        vis_box = QtWidgets.QGroupBox("Visibility", self)
        vis_layout = QtWidgets.QVBoxLayout(vis_box)
        self._page_visible = QtWidgets.QCheckBox("Show page (live window)", self)
        self._page_visible.toggled.connect(self._on_page_visible)
        vis_layout.addWidget(self._page_visible)
        self._target_visible = QtWidgets.QCheckBox("Show target widgets", self)
        self._target_visible.toggled.connect(self._on_target_visible)
        vis_layout.addWidget(self._target_visible)
        root.addWidget(vis_box)

        # --- Save / Reset ---
        save_row = QtWidgets.QHBoxLayout()
        self._reset_btn = QDataPushButton(
            "Reset",
            parent=self,
            tooltip="Restore widget and window positions to the designed canvas settings (snapshot at profile start or last Save).",
            clicked=self._reset_layout,
        )
        self._save_btn = QDataPushButton(
            "Save",
            parent=self,
            tooltip="Write the overlay to the current profile.",
            clicked=self._save,
        )
        self._save_as_btn = QDataPushButton(
            "Save as new page…",
            parent=self,
            tooltip="Duplicate this page under a new name and save.",
            clicked=self._save_as,
        )
        save_row.addWidget(self._reset_btn)
        save_row.addWidget(self._save_btn)
        save_row.addWidget(self._save_as_btn)
        root.addLayout(save_row)

        self._keybinds_btn = QDataPushButton(
            "Keybinds…",
            parent=self,
            tooltip="Assign physical, vJoy, or keyboard/mouse inputs to every control action.",
            clicked=self._open_keybinds,
        )
        root.addWidget(self._keybinds_btn)

        self._status = QtWidgets.QLabel("", self)
        self._status.setWordWrap(True)
        root.addWidget(self._status)
        root.addStretch(1)

        self.scene.changed.connect(self._on_scene)
        self.scene.control_target_changed.connect(self._on_scene)
        try:
            self.scene.mouse_reposition_changed.connect(self._on_mouse_reposition_changed)
        except Exception:
            pass
        self._rebuild_timer = QtCore.QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(50)
        self._rebuild_timer.timeout.connect(self._rebuild)
        self.destroyed.connect(self._detach)
        self._bind_runtime_hooks()
        self._install_activity_filters()
        self._ensure_interactive()
        self._rebuild()
        self._pulse_control_highlight()

    def _install_activity_filters(self):
        self.installEventFilter(self)
        for widget in self.findChildren(QtWidgets.QWidget):
            try:
                widget.installEventFilter(self)
            except RuntimeError:
                pass

    def _bind_runtime_hooks(self):
        if self._hooks:
            return
        try:
            import gremlin.event_handler

            el = gremlin.event_handler.EventListener()
            el.profile_start.connect(self._on_profile_runtime)
            el.profile_stop.connect(self._on_profile_runtime)
            self._hooks = True
        except Exception:
            pass

    def _on_profile_runtime(self, *_args):
        if _alive(self):
            # Profile stop: clear mouse reposition so interactive mode is not left suspended.
            try:
                import gremlin.shared_state

                if not gremlin.shared_state.is_running and self.scene.mouse_reposition_enabled:
                    self.scene.set_mouse_reposition(False)
            except Exception:
                pass
            QtCore.QTimer.singleShot(0, self, self._sync_runtime_enabled)

    def _sync_runtime_enabled(self):
        """Window stays openable; controls only work while the profile is running."""
        if not _alive(self):
            return
        try:
            import gremlin.shared_state

            active = bool(gremlin.shared_state.is_running)
        except Exception:
            active = False
        # Keep the window itself enabled so it can be moved/minimized/closed.
        self.setEnabled(True)
        for box in self.findChildren(QtWidgets.QGroupBox):
            try:
                box.setEnabled(active)
            except RuntimeError:
                pass
        for btn in list(self._anchor_buttons.values()) + self._nudge_buttons:
            try:
                btn.setEnabled(active)
            except RuntimeError:
                pass
        for attr in (
            "_cycle_btn",
            "_reset_btn",
            "_save_btn",
            "_save_as_btn",
            "_keybinds_btn",
            "_page_visible",
            "_target_visible",
            "_mouse_reposition",
            "_page_box",
            "_target_list",
            "_filter_box",
            "_search_edit",
        ):
            widget = getattr(self, attr, None)
            if widget is not None and _alive(widget):
                widget.setEnabled(active)
        # Preference can be set before the profile starts.
        if _alive(self._auto_launch):
            self._auto_launch.setEnabled(True)
        if active:
            self._sync_target_visible_checkbox()
            if not (self._status.text() or "").strip():
                self._status.setText("")
        else:
            self._status.setText("Start the profile to use Overlay control.")

    def _ensure_interactive(self):
        # Back-compat alias used by show/rebuild paths.
        self._sync_runtime_enabled()

    def _detach(self, *_args):
        self._stop_nudge()
        self._hide_control_highlight()
        try:
            self._highlight_idle.stop()
        except Exception:
            pass
        try:
            self.scene.changed.disconnect(self._on_scene)
        except Exception:
            pass
        try:
            self.scene.control_target_changed.disconnect(self._on_scene)
        except Exception:
            pass
        try:
            self.scene.mouse_reposition_changed.disconnect(self._on_mouse_reposition_changed)
        except Exception:
            pass
        if self._hooks:
            try:
                import gremlin.event_handler

                el = gremlin.event_handler.EventListener()
                el.profile_start.disconnect(self._on_profile_runtime)
                el.profile_stop.disconnect(self._on_profile_runtime)
            except Exception:
                pass
            self._hooks = False

    def eventFilter(self, watched, event: QtCore.QEvent):
        # Any interaction with the panel shows the live cyan target box briefly.
        et = event.type()
        if et in (
            QtCore.QEvent.MouseButtonPress,
            QtCore.QEvent.KeyPress,
            QtCore.QEvent.Wheel,
            QtCore.QEvent.FocusIn,
        ):
            self._pulse_control_highlight()
        return super().eventFilter(watched, event)

    def changeEvent(self, event: QtCore.QEvent):
        super().changeEvent(event)
        if event.type() != QtCore.QEvent.WindowStateChange:
            return
        if self.windowState() & QtCore.Qt.WindowMinimized:
            if not self.scene.mouse_reposition_enabled:
                self._hide_control_highlight()
        elif self.isVisible():
            self._pulse_control_highlight()

    def _pulse_control_highlight(self):
        if not _alive(self):
            return
        if self.windowState() & QtCore.Qt.WindowMinimized:
            return
        self.scene.set_control_highlight(True)
        # Keep the cyan box while mouse reposition is armed.
        if self.scene.mouse_reposition_enabled:
            self._highlight_idle.stop()
            return
        self._highlight_idle.start()

    def _hide_control_highlight(self):
        if self.scene.mouse_reposition_enabled:
            return
        try:
            self.scene.set_control_highlight(False)
        except Exception:
            pass

    def _on_scene(self, *_args):
        if not _alive(self) or self._building:
            return
        # Don't rebuild while hold-nudging — it can interrupt pressed state.
        # Also avoid re-pulsing the cyan box on every scene change so idle hide works.
        if self._nudge_timer.isActive():
            return
        if not self.isVisible():
            return
        timer = getattr(self, "_rebuild_timer", None)
        if timer is None:
            QtCore.QTimer.singleShot(0, self, self._rebuild)
            return
        if not timer.isActive():
            timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        # Ensure a baseline exists even if the panel opens before profile start.
        if not self.scene._layout_baseline:
            self.scene.capture_layout_baseline()
        self._ensure_interactive()
        self._rebuild()
        self._pulse_control_highlight()

    def hideEvent(self, event):
        self._stop_nudge()
        self._hide_control_highlight()
        super().hideEvent(event)

    def _on_mouse_reposition_toggled(self, checked: bool):
        if self._building:
            return
        if checked:
            if not _skip_mouse_reposition_prompt():
                box = QtWidgets.QMessageBox(self)
                box.setWindowTitle("Enable mouse repositioning")
                box.setIcon(QtWidgets.QMessageBox.Question)
                box.setText("Interactive widgets will be disabled until this box is unchecked.")
                box.setInformativeText(
                    "You can drag the selected control target on the live overlay. "
                    "Empty space stays click-through and the game keeps focus."
                )
                again = QtWidgets.QCheckBox("Do not show again", box)
                box.setCheckBox(again)
                box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                box.setDefaultButton(QtWidgets.QMessageBox.Yes)
                reply = box.exec()
                if again.isChecked() and reply == QtWidgets.QMessageBox.Yes:
                    _set_skip_mouse_reposition_prompt(True)
                if reply != QtWidgets.QMessageBox.Yes:
                    self._mouse_reposition.blockSignals(True)
                    self._mouse_reposition.setChecked(False)
                    self._mouse_reposition.blockSignals(False)
                    return
            self.scene.set_mouse_reposition(True)
            self._pulse_control_highlight()
            self._status.setText("Mouse repositioning on — drag the cyan target on the live overlay.")
        else:
            self.scene.set_mouse_reposition(False)
            self.scene.set_control_highlight(False)
            self._status.setText("Mouse repositioning off — interactive widgets restored.")

    def _on_mouse_reposition_changed(self, *_args):
        """Keep the checkbox in sync when a keybind toggles mouse reposition."""
        if not _alive(self):
            return
        on = bool(self.scene.mouse_reposition_enabled)
        if self._mouse_reposition.isChecked() != on:
            self._mouse_reposition.blockSignals(True)
            self._mouse_reposition.setChecked(on)
            self._mouse_reposition.blockSignals(False)
        if on:
            self._pulse_control_highlight()
            self._status.setText("Mouse repositioning on — drag widgets on the live overlay.")
        else:
            self._status.setText("Mouse repositioning off — interactive widgets restored.")

    def _on_auto_launch_toggled(self, checked: bool):
        if self._building:
            return
        self.scene.show_control_panel_on_profile_start = bool(checked)
        self.scene._dirty = True
        self.scene.changed.emit()
        self._status.setText(
            "Overlay control will open when the profile starts."
            if checked
            else "Overlay control will not auto-open on profile start."
        )

    def _current_page_id(self) -> str | None:
        data = self._page_box.currentData()
        return str(data) if data else self.scene.active_page_id

    def _rebuild(self):
        if not _alive(self):
            return
        self._building = True
        try:
            page_id = self._current_page_id() or self.scene.active_page_id
            self._page_box.blockSignals(True)
            self._page_box.clear()
            for page in self.scene.pages:
                self._page_box.addItem(str(page.get("name") or "Overlay"), page["id"])
            idx = self._page_box.findData(page_id)
            if idx < 0 and self.scene.pages:
                page_id = self.scene.pages[0]["id"]
                idx = 0
            if idx >= 0:
                self._page_box.setCurrentIndex(idx)
            self._page_box.blockSignals(False)

            page = self.scene.page_by_id(page_id)
            self._page_visible.blockSignals(True)
            self._page_visible.setChecked(bool((page or {}).get("visible", True)))
            from gremlin.ui.obs_overlay import OverlayManager

            live = OverlayManager().page_is_visible(page_id) if page_id else False
            tip = "Page marked visible in the designer."
            if live:
                tip += " Live window is open."
            self._page_visible.setToolTip(tip)
            self._page_visible.blockSignals(False)

            self._rebuild_targets(page_id)
            self._sync_target_visible_checkbox()
            self._mouse_reposition.blockSignals(True)
            self._mouse_reposition.setChecked(bool(self.scene.mouse_reposition_enabled))
            self._mouse_reposition.blockSignals(False)
            self._auto_launch.blockSignals(True)
            self._auto_launch.setChecked(bool(self.scene.show_control_panel_on_profile_start))
            self._auto_launch.blockSignals(False)
            self._highlight_anchor()
            self._ensure_interactive()
        finally:
            self._building = False

    def _rebuild_targets(self, page_id: str | None):
        current = self.scene.control_target or {}
        self._target_list.blockSignals(True)
        self._target_list.clear()

        kind_filter = str(getattr(self, "_list_filter", "all") or "all")
        query = str(getattr(self, "_list_query", "") or "").strip().casefold()

        def _match(text: str) -> bool:
            if not query:
                return True
            return query in str(text or "").casefold()

        # Entire page always listed unless filtering to groups/widgets only.
        if kind_filter == "all":
            page = self.scene.page_by_id(page_id)
            page_name = str((page or {}).get("name") or "Overlay")
            if _match(page_name) or _match("entire page"):
                page_item = QtWidgets.QListWidgetItem("Entire page")
                page_item.setData(QtCore.Qt.UserRole, ("page", page_id))
                self._target_list.addItem(page_item)

        if kind_filter in ("all", "groups"):
            for group in self.scene.list_named_groups(page_id):
                label = f"Group: {group['name']} ({group['count']})"
                if not _match(group["name"]) and not _match(label):
                    continue
                item = QtWidgets.QListWidgetItem(label)
                item.setData(QtCore.Qt.UserRole, ("group", group["id"]))
                self._target_list.addItem(item)

        if kind_filter in ("all", "widgets"):
            for widget in self.scene.widgets_for(page_id):
                name = str(widget.get("name") or "").strip() or str(widget.get("type") or "widget")
                label = f"Widget: {name}"
                if not _match(name) and not _match(label) and not _match(widget.get("type")):
                    continue
                item = QtWidgets.QListWidgetItem(label)
                item.setData(QtCore.Qt.UserRole, ("widget", widget["id"]))
                self._target_list.addItem(item)

        # Select matching target
        kind = str(current.get("kind") or "page")
        tid = current.get("id")
        select_row = 0
        for row in range(self._target_list.count()):
            data = self._target_list.item(row).data(QtCore.Qt.UserRole)
            if not data:
                continue
            if data[0] == kind and (kind == "page" or data[1] == tid):
                select_row = row
                break
        if self._target_list.count():
            self._target_list.setCurrentRow(select_row)
        self._target_list.blockSignals(False)

    def _on_filter_changed(self, _index: int = 0):
        if self._building:
            return
        data = self._filter_box.currentData()
        self._list_filter = str(data or "all")
        self._rebuild_targets(self._current_page_id())

    def _on_search_changed(self, text: str):
        if self._building:
            return
        self._list_query = str(text or "")
        self._rebuild_targets(self._current_page_id())

    def _sync_target_visible_checkbox(self):
        ids = self.scene.control_target_widget_ids()
        self._target_visible.blockSignals(True)
        if not ids:
            self._target_visible.setEnabled(False)
            self._target_visible.setChecked(True)
        else:
            self._target_visible.setEnabled(True)
            visible = all(bool((self.scene.widget_by_id(wid) or {}).get("visible", True)) for wid in ids)
            self._target_visible.setChecked(visible)
        kind = str((self.scene.control_target or {}).get("kind") or "page")
        if kind == "page" and not is_onscreen_mode(self.scene.canvas_for(self._current_page_id())):
            # Windowed entire-page target moves the window; widget visibility still applies to all widgets.
            self._target_visible.setToolTip("Show or hide all widgets on this page.")
        else:
            self._target_visible.setToolTip("Show or hide the targeted widget(s).")
        self._target_visible.blockSignals(False)

    def _highlight_anchor(self):
        last = str(getattr(self.scene, "_last_anchor", "center") or "center")
        for key, btn in self._anchor_buttons.items():
            btn.setProperty("activeAnchor", key == last)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_page_changed(self, _index: int):
        if self._building:
            return
        page_id = self._current_page_id()
        if page_id:
            self.scene.set_active_page(page_id)
            self.scene.set_control_target("page", page_id)
        self._rebuild()

    def _on_target_item(self, current, _previous):
        if self._building or current is None:
            return
        data = current.data(QtCore.Qt.UserRole)
        if not data:
            return
        kind, tid = data
        self.scene.set_control_target(kind, tid)
        if kind == "widget":
            self.scene.set_selection([tid])
        elif kind == "group":
            ids = self.scene.control_target_widget_ids({"kind": "group", "id": tid})
            self.scene.set_selection(ids)
        self._sync_target_visible_checkbox()

    def _anchor(self, key: str):
        self._pulse_control_highlight()
        self.scene.anchor_target(key)
        self._status.setText(f"Anchored: {ANCHOR_LABELS.get(key, key)}")
        self._highlight_anchor()

    def _cycle(self):
        self._pulse_control_highlight()
        nxt = self.scene.cycle_anchor()
        self._status.setText(f"Anchored: {ANCHOR_LABELS.get(nxt, nxt)}")
        self._highlight_anchor()

    def _nudge(self, dx: int, dy: int):
        self._pulse_control_highlight()
        if self.scene.nudge_control_target(int(dx), int(dy)):
            self._status.setText(f"Nudged ({int(dx):+d}, {int(dy):+d})")

    def _start_nudge(self, dx: int, dy: int):
        """Begin continuous nudge; first step is immediate, then timer accelerates."""
        self._nudge_dir = (int(dx), int(dy))
        self._nudge_step = 8
        self._nudge_ticks = 0
        self._nudge(self._nudge_dir[0] * self._nudge_step, self._nudge_dir[1] * self._nudge_step)
        # Initial delay before repeat feels like a key; then faster ticks.
        self._nudge_timer.start(120)

    def _stop_nudge(self):
        self._nudge_timer.stop()
        self._nudge_dir = (0, 0)
        self._nudge_step = 8
        self._nudge_ticks = 0

    def _on_nudge_tick(self):
        dx, dy = self._nudge_dir
        if dx == 0 and dy == 0:
            self._stop_nudge()
            return
        self._nudge_ticks += 1
        # Accelerate: 8 → 16 → 24 … capped so it stays controllable.
        if self._nudge_ticks >= 2:
            self._nudge_step = min(48, 8 + (self._nudge_ticks - 1) * 4)
        # After first repeats, tighten the interval for smoother motion.
        if self._nudge_ticks == 2 and self._nudge_timer.interval() > 40:
            self._nudge_timer.setInterval(40)
        self._nudge(dx * self._nudge_step, dy * self._nudge_step)

    def _on_page_visible(self, on: bool):
        if self._building:
            return
        page_id = self._current_page_id()
        self.scene.set_page_visible(bool(on), page_id=page_id)
        from gremlin.ui.obs_overlay import OverlayManager

        mgr = OverlayManager()
        if on:
            mgr.show_overlay(page_ids=[page_id] if page_id else None)
        elif page_id:
            mgr.hide_overlay_page(page_id)

    def _on_target_visible(self, on: bool):
        if self._building:
            return
        target = self.scene.control_target or {}
        kind = str(target.get("kind") or "page")
        if kind == "group":
            self.scene.set_group_widgets_visible(target.get("id"), bool(on), page_id=self._current_page_id())
        else:
            ids = self.scene.control_target_widget_ids()
            self.scene.set_widgets_visible(ids, bool(on))

    def _reset_layout(self):
        page_id = self._current_page_id()
        # Capture now if the user opened the panel before profile start.
        if page_id and page_id not in (self.scene._layout_baseline or {}):
            self.scene.capture_layout_baseline(page_id)
        if self.scene.restore_layout_baseline(page_id):
            self._status.setText("Reset to canvas settings.")
        else:
            self._status.setText("Nothing to reset.")

    def _save(self):
        try:
            ok = self.scene.save_to_profile()
            if ok:
                self.scene.capture_layout_baseline()
            self._status.setText("Saved to profile." if ok else "Save failed.")
        except Exception as err:
            syslog.exception("OBS OVERLAY: control panel save failed")
            self._status.setText(f"Save failed: {err}")

    def _save_as(self):
        page = self.scene.page_by_id(self._current_page_id()) or self.scene.active_page()
        if page is None:
            return
        base = str(page.get("name") or "Overlay")
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Save as new page",
            "Name for the new overlay page:",
            text=f"{base} copy",
        )
        if not ok:
            return
        dup = self.scene.duplicate_page(page.get("id"), activate=True)
        if dup is None:
            self._status.setText("Could not duplicate page.")
            return
        label = str(name or "").strip() or f"{base} copy"
        self.scene.rename_page(label, page_id=dup["id"])
        self.scene.set_control_target("page", dup["id"])
        try:
            self.scene.save_to_profile()
            self.scene.capture_layout_baseline()
            self._status.setText(f"Saved as new page “{label}”.")
        except Exception as err:
            self._status.setText(f"Page created but save failed: {err}")
        self._rebuild()

    def _open_keybinds(self):
        from .keybinds_dialog import open_runtime_keybinds_dialog

        self._pulse_control_highlight()
        open_runtime_keybinds_dialog(self.scene, page_id=self._current_page_id(), parent=self)


_panel: OverlayControlPanel | None = None


def open_overlay_control_panel(scene: OverlayScene | None = None, parent=None) -> OverlayControlPanel:
    """Show the singleton runtime control panel.

    ``parent`` is ignored for ownership — the panel is always a top-level window
    so the Overlay tab's runtime lock cannot disable it.
    """
    global _panel
    if scene is None:
        from gremlin.ui.obs_overlay import OverlayManager

        scene = OverlayManager().scene
    if _panel is not None and _alive(_panel):
        _panel._ensure_interactive()
        _panel.raise_()
        _panel.activateWindow()
        _panel.show()
        return _panel
    _panel = OverlayControlPanel(scene, parent=None)
    _panel.show()
    _panel.raise_()
    _panel.activateWindow()
    return _panel
