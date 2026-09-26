# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""OBS chromakey overlay designer and capture window."""

from __future__ import annotations

import logging

from PySide6 import QtCore
from psygnal import Signal
from shiboken6 import Shiboken

import gremlin.event_handler
import gremlin.shared_state
import gremlin.util
from gremlin.singleton_decorator import SingletonDecorator

from .bindings import binding_is_configured, read_toggle_active, toggle_follows_level
from .designer import OverlayDesignerWidget
from .model import (
    ANCHOR_KEYS,
    OverlayScene,
    RUNTIME_HOLD_ACTIONS,
    RUNTIME_NUDGE_DELTA,
    normalize_background_mode,
    normalize_runtime_bindings,
    _overlay_payload_has_content,
)
from .overlay_window import OverlayWindow, apply_onscreen_geometry
from .widgets import live_window_is_layered

syslog = logging.getLogger("system")


@SingletonDecorator
class OverlayManager:
    """Owns the shared scene, designer, and overlay windows (one per visible page)."""

    visibility_changed = Signal()

    def __init__(self):
        self.scene = OverlayScene()
        self._overlays: dict[str, OverlayWindow] = {}
        self._hooks = False
        self._auto_shown = False
        self._page_chrome: dict[str, tuple] = {}
        self._page_visible_flags: dict[str, bool] = {}
        self._toggle_timer = None
        self._toggle_active: dict[str, bool] = {}
        self._runtime_binding_active: dict[str, bool] = {}
        self._runtime_nudge_ticks: dict[str, int] = {}
        self._recreate_pending: set[str] = set()
        self._stream_page_id: str | None = None
        self._bind_profile_hooks()
        self.scene.load_for_profile()
        self._apply_all_onscreen()
        self._refresh_page_chrome()
        self.scene.changed.connect(self._on_scene_changed)
        self.scene.page_window_move_requested.connect(self._on_page_window_move)
        try:
            self.scene.mouse_reposition_changed.connect(self._on_mouse_reposition_banner)
        except Exception:
            pass

    def _bind_profile_hooks(self):
        if self._hooks:
            return
        el = gremlin.event_handler.EventListener()
        el.profile_loaded.connect(self._on_profile_loaded)
        el.profile_unloaded.connect(self._on_profile_unloaded)
        el.profile_started.connect(self._on_profile_started)
        el.profile_stop.connect(self._on_profile_stop)
        el.tabs_loaded.connect(self._on_tabs_loaded)
        self._hooks = True

    def _apply_all_onscreen(self):
        for page in self.scene.pages:
            apply_onscreen_geometry(self.scene, emit=False, page_id=page["id"])

    def _page_chrome_tuple(self, page_id: str) -> tuple:
        canvas = self.scene.canvas_for(page_id)
        return (
            normalize_background_mode(canvas.get("background_mode")),
            live_window_is_layered(canvas),
        )

    def _refresh_page_chrome(self):
        self._page_chrome = {page["id"]: self._page_chrome_tuple(page["id"]) for page in self.scene.pages}
        self._page_visible_flags = {page["id"]: bool(page.get("visible", True)) for page in self.scene.pages}

    def _load_current_profile_scene(self):
        self.scene.load_for_profile()
        self._apply_all_onscreen()
        self._refresh_page_chrome()

    def _on_profile_loaded(self):
        # profile_loaded is a psygnal Signal and may fire on the profile-load
        # worker thread — never touch Qt widgets / scene emits from there.
        gremlin.util.InvokeUiMethod(self._on_profile_loaded_ui)

    def _flush_dirty_scene(self) -> bool:
        """Write unsaved overlay edits (page names, etc.) before start/stop/reload."""
        if not self.scene.dirty:
            return True
        try:
            payload = self.scene.to_dict()
            if not _overlay_payload_has_content(payload):
                existing = self.scene.read_stored_layout()
                if _overlay_payload_has_content(existing):
                    syslog.info("OBS OVERLAY: skip flush of empty default over saved layout")
                    self.scene._dirty = False
                    return True
            return bool(self.scene.save_owned() or self.scene.save_to_profile())
        except Exception as err:
            syslog.warning(f"OBS OVERLAY: flush before profile event failed: {err}")
            return False

    def _on_profile_loaded_ui(self):
        if self.scene.belongs_to_profile():
            # Already showing this profile. Flush edits; do not reload from disk
            # (that used to drop in-memory changes that had not hit JSON yet).
            self._flush_dirty_scene()
            return
        self._flush_dirty_scene()
        self._load_current_profile_scene()

    def _on_profile_unloaded(self):
        # Same as loaded: unload runs on WorkManager; inspector rebuild must
        # stay on the UI thread or GEX hangs (Not Responding).
        gremlin.util.InvokeUiMethod(self._on_profile_unloaded_ui)

    def _on_profile_unloaded_ui(self):
        self._flush_dirty_scene()
        self._stop_runtime_toggle()
        self.hide_overlay()
        # current_profile is often None during the swap. Reloading then resets
        # the scene to an empty default; the following profile_loaded flush
        # could write that empty layout over the profile that is about to load.
        if gremlin.shared_state.current_profile is None:
            return
        self._load_current_profile_scene()

    def _on_tabs_loaded(self):
        gremlin.util.InvokeUiMethod(self._ensure_current_profile_scene)

    def _on_profile_started(self):
        gremlin.util.InvokeUiMethod(self._on_profile_started_ui)

    def _on_profile_started_ui(self):
        # Flush renames/edits before runtime so deactivate cannot reload stale names.
        self._flush_dirty_scene()
        # Snapshot designed layout so the control panel can Reset to canvas settings.
        self.scene.capture_layout_baseline()
        self._start_runtime_toggle()
        auto_ids = []
        for page in self.scene.pages:
            if not page.get("visible", True) or not page.get("canvas", {}).get("show_on_profile_start"):
                continue
            binding = page.get("canvas", {}).get("toggle_binding")
            # A released state toggle must not open the window at start.
            if (
                toggle_follows_level(binding)
                and binding_is_configured(binding)
                and not read_toggle_active(binding)
            ):
                continue
            auto_ids.append(page["id"])
        if auto_ids:
            self._auto_shown = True
            QtCore.QTimer.singleShot(0, lambda ids=auto_ids: self.show_overlay(auto=True, page_ids=ids))
        if self.scene.show_control_panel_on_profile_start:
            QtCore.QTimer.singleShot(0, lambda: self.open_control_panel())
        self._poll_toggle()

    def _on_profile_stop(self):
        gremlin.util.InvokeUiMethod(self._on_profile_stop_ui)

    def _on_profile_stop_ui(self):
        self._flush_dirty_scene()
        self._release_overlay_touch()
        try:
            self.scene.set_mouse_reposition(False)
        except Exception:
            pass
        self._sync_mouse_reposition_banner()
        self._stop_runtime_toggle()
        auto = self._auto_shown or any(
            page.get("canvas", {}).get("show_on_profile_start") for page in self.scene.pages
        )
        attached = any(
            window is not None
            and Shiboken.isValid(window)
            and getattr(window, "_host_attached", False)
            for window in self._overlays.values()
        )
        self._auto_shown = False
        # Always tear down live / app-share overlays on deactivate — a detached
        # child that Qt still thinks is hidden leaves a ghost HWND + host cursor
        # over JG Ex.
        if auto or attached or self._overlays:
            self.hide_overlay()

    def _start_runtime_toggle(self):
        if not gremlin.util.is_ui_thread():
            gremlin.util.InvokeUiMethod(self._start_runtime_toggle)
            return
        self._toggle_active = {
            page["id"]: read_toggle_active(page.get("canvas", {}).get("toggle_binding"))
            for page in self.scene.pages
        }
        self._runtime_binding_active = {}
        for page in self.scene.pages:
            bindings = normalize_runtime_bindings(page.get("canvas", {}).get("runtime_bindings"))
            for action, binding in bindings.items():
                key = f"{page['id']}:{action}"
                self._runtime_binding_active[key] = (
                    read_toggle_active(binding) if binding_is_configured(binding) else False
                )
        self._runtime_nudge_ticks = {}
        if self._toggle_timer is None:
            app = QtCore.QCoreApplication.instance()
            timer = QtCore.QTimer(app)
            timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
            timer.setInterval(16)
            timer.timeout.connect(self._poll_toggle)
            self._toggle_timer = timer
        if not self._toggle_timer.isActive():
            self._toggle_timer.start()

    def _stop_runtime_toggle(self):
        if not gremlin.util.is_ui_thread():
            gremlin.util.InvokeUiMethod(self._stop_runtime_toggle)
            return
        if self._toggle_timer is not None:
            self._toggle_timer.stop()
        self._toggle_active = {}
        self._runtime_binding_active = {}
        self._runtime_nudge_ticks = {}

    def _poll_toggle(self):
        for page in self.scene.pages:
            page_id = page["id"]
            binding = page.get("canvas", {}).get("toggle_binding")
            if binding_is_configured(binding):
                active = read_toggle_active(binding)
                previous = self._toggle_active.get(page_id, False)
                self._toggle_active[page_id] = active
                visible = self.page_is_visible(page_id)
                if toggle_follows_level(binding):
                    # GEX states are latched: show while pressed, hide while released.
                    if active and not visible:
                        self._auto_shown = True
                        self.show_overlay(auto=True, page_ids=[page_id])
                    elif not active and visible:
                        self._auto_shown = False
                        self.hide_overlay_page(page_id)
                else:
                    rising = active and not previous
                    if rising:
                        if visible:
                            self._auto_shown = False
                            self.hide_overlay_page(page_id)
                        else:
                            self._auto_shown = True
                            self.show_overlay(auto=True, page_ids=[page_id])
            self._poll_runtime_bindings(page)

    def _poll_runtime_bindings(self, page: dict):
        page_id = page["id"]
        # Prefer active page for open_control_panel / anchors so one profile does not
        # fire every page's hotkeys; still allow bindings defined on each page canvas.
        bindings = normalize_runtime_bindings(page.get("canvas", {}).get("runtime_bindings"))
        for action, binding in bindings.items():
            key = f"{page_id}:{action}"
            if not binding_is_configured(binding):
                self._runtime_binding_active[key] = False
                self._runtime_nudge_ticks.pop(key, None)
                continue
            # One-shots: ignore state/mode level-follow.
            if toggle_follows_level(binding) and action not in RUNTIME_HOLD_ACTIONS:
                self._runtime_binding_active[key] = read_toggle_active(binding)
                continue
            active = read_toggle_active(binding)
            previous = self._runtime_binding_active.get(key, False)
            self._runtime_binding_active[key] = active

            if action in RUNTIME_HOLD_ACTIONS:
                if not active:
                    self._runtime_nudge_ticks.pop(key, None)
                    continue
                if page_id != self.scene.active_page_id and not self.page_is_visible(page_id):
                    continue
                ticks = self._runtime_nudge_ticks.get(key, 0) + 1
                self._runtime_nudge_ticks[key] = ticks
                dx, dy = RUNTIME_NUDGE_DELTA.get(action, (0, 0))
                if ticks == 1:
                    self.scene.nudge_control_target(dx * 8, dy * 8)
                    try:
                        self.scene.set_control_highlight(True)
                    except Exception:
                        pass
                elif ticks >= 8 and (ticks - 8) % 2 == 0:
                    step = min(48, 8 + ((ticks - 8) // 2) * 4)
                    self.scene.nudge_control_target(dx * step, dy * step)
                continue

            if not (active and not previous):
                continue
            # Only fire anchors for the page that owns the binding when it is active,
            # or always for open_control_panel from any configured page.
            if action == "open_control_panel":
                self.open_control_panel()
                continue
            if action == "toggle_mouse_reposition":
                # Rising-edge toggle; do not steal focus with a confirm dialog.
                try:
                    self.scene.set_mouse_reposition(not self.scene.mouse_reposition_enabled)
                except Exception:
                    syslog.exception("OBS OVERLAY: toggle mouse reposition binding failed")
                continue
            if page_id != self.scene.active_page_id and not self.page_is_visible(page_id):
                continue
            try:
                self.scene.set_control_highlight(True)
            except Exception:
                pass
            if action == "anchor_cycle":
                self.scene.cycle_anchor()
            elif action.startswith("anchor_"):
                anchor = action[len("anchor_") :]
                if anchor in ANCHOR_KEYS:
                    self.scene.anchor_target(anchor)
            elif action == "toggle_page_visible":
                self._runtime_toggle_page_visible(page_id)
            elif action == "toggle_target_visible":
                self._runtime_toggle_target_visible(page_id)
            elif action == "reset_layout":
                if page_id and page_id not in (self.scene._layout_baseline or {}):
                    self.scene.capture_layout_baseline(page_id)
                self.scene.restore_layout_baseline(page_id)
            elif action == "save":
                try:
                    if self.scene.save_to_profile():
                        self.scene.capture_layout_baseline()
                except Exception:
                    syslog.exception("OBS OVERLAY: runtime save binding failed")
            elif action == "save_as":
                gremlin.util.InvokeUiMethod(self._runtime_save_as_ui, page_id)

    def _runtime_toggle_page_visible(self, page_id: str):
        visible = self.page_is_visible(page_id)
        self.scene.set_page_visible(not visible, page_id=page_id)
        if visible:
            self._auto_shown = False
            self.hide_overlay_page(page_id)
        else:
            self._auto_shown = True
            self.show_overlay(auto=True, page_ids=[page_id])

    def _runtime_toggle_target_visible(self, page_id: str):
        target = self.scene.control_target or {}
        kind = str(target.get("kind") or "page")
        ids = self.scene.control_target_widget_ids(target, page_id=page_id)
        if kind == "group":
            currently = all(bool((self.scene.widget_by_id(wid) or {}).get("visible", True)) for wid in ids) if ids else True
            self.scene.set_group_widgets_visible(target.get("id"), not currently, page_id=page_id)
            return
        if not ids:
            return
        currently = all(bool((self.scene.widget_by_id(wid) or {}).get("visible", True)) for wid in ids)
        self.scene.set_widgets_visible(ids, not currently)

    def _runtime_save_as_ui(self, page_id: str | None):
        from .control_panel import open_overlay_control_panel

        panel = open_overlay_control_panel(self.scene)
        if page_id:
            # Align panel page selection, then reuse its save-as flow.
            try:
                idx = panel._page_box.findData(page_id)
                if idx >= 0:
                    panel._page_box.setCurrentIndex(idx)
            except Exception:
                pass
        panel._save_as()

    def open_control_panel(self, parent=None):
        gremlin.util.InvokeUiMethod(self._open_control_panel_ui, parent)

    def _open_control_panel_ui(self, parent=None):
        from .control_panel import open_overlay_control_panel

        open_overlay_control_panel(self.scene, parent=parent)

    def _on_mouse_reposition_banner(self, *_args):
        gremlin.util.InvokeUiMethod(self._sync_mouse_reposition_banner)

    def _sync_mouse_reposition_banner(self):
        from .control_panel import sync_mouse_reposition_banner

        sync_mouse_reposition_banner(bool(self.scene.mouse_reposition_enabled))

    def _on_page_window_move(self, page_id: str, x: int, y: int):
        gremlin.util.InvokeUiMethod(self._on_page_window_move_ui, page_id, x, y)

    def _on_page_window_move_ui(self, page_id: str, x: int, y: int):
        window = self._overlays.get(page_id)
        if window is None or not Shiboken.isValid(window):
            return
        try:
            window.move(int(x), int(y))
            window._record_window_position()
        except RuntimeError:
            return

    def _ensure_current_profile_scene(self):
        if self.scene.belongs_to_profile():
            return
        if self.scene.dirty and not self._flush_dirty_scene():
            # Keep the in-memory layout rather than reloading a stale profile JSON.
            return
        self._load_current_profile_scene()

    def _on_scene_changed(self):
        # scene.changed is psygnal and may fire off the UI thread after profile work.
        gremlin.util.InvokeUiMethod(self._on_scene_changed_ui)

    def _on_scene_changed_ui(self):
        live_ids = {page["id"] for page in self.scene.pages}
        for page_id in list(self._overlays):
            if page_id not in live_ids:
                self._hide_page_ui(page_id)
        recreate = []
        for page in self.scene.pages:
            page_id = page["id"]
            chrome = self._page_chrome_tuple(page_id)
            previous = self._page_chrome.get(page_id)
            self._page_chrome[page_id] = chrome
            if previous is not None and previous != chrome and self.page_is_visible(page_id):
                recreate.append(page_id)
            visible = bool(page.get("visible", True))
            was_visible = self._page_visible_flags.get(page_id)
            self._page_visible_flags[page_id] = visible
            if was_visible is True and not visible:
                self._hide_page_ui(page_id)
        for page_id in recreate:
            if page_id in self._recreate_pending:
                continue
            self._recreate_pending.add(page_id)
            QtCore.QTimer.singleShot(0, lambda pid=page_id: gremlin.util.InvokeUiMethod(self._recreate_page_ui, pid))
        self._sync_stream_to_active_page()

    def _recreate_page_ui(self, page_id: str):
        self._recreate_pending.discard(page_id)
        was_visible = self.page_is_visible(page_id)
        self._hide_page_ui(page_id)
        if was_visible:
            self._show_page_ui(page_id)

    def launch_designer(self, parent=None):
        gremlin.util.InvokeUiMethod(self._launch_designer_ui, parent)

    def _launch_designer_ui(self, parent=None):
        self._ensure_current_profile_scene()
        ui = gremlin.shared_state.ui
        guid = gremlin.shared_state.overlay_tab_guid
        if ui is not None:
            ui.selectTabWidget(guid)
            return
        syslog.warning("OBS OVERLAY: main window is not ready; Overlay tab cannot be selected")

    def overlay_is_visible(self) -> bool:
        return any(self.page_is_visible(page_id) for page_id in list(self._overlays))

    def page_is_visible(self, page_id: str) -> bool:
        window = self._overlays.get(page_id)
        if window is None or not Shiboken.isValid(window):
            return False
        # After app-share SetParent, Qt can report isVisible()==False even though
        # the child HWND is live — that made the 16ms toggle poll reopen forever.
        if window.isVisible():
            return True
        return bool(getattr(window, "_host_attached", False))

    def show_overlay(self, auto: bool = False, page_ids: list[str] | None = None):
        gremlin.util.InvokeUiMethod(self._show_overlay_ui, auto, page_ids)

    def hide_overlay_page(self, page_id: str):
        gremlin.util.InvokeUiMethod(self._hide_overlay_page_ui, page_id)

    def _hide_overlay_page_ui(self, page_id: str):
        window = self._overlays.get(page_id)
        reclaim = bool(
            window is not None and Shiboken.isValid(window) and getattr(window, "_host_attached", False)
        )
        self._hide_page_ui(page_id)
        if reclaim:
            self._reclaim_main_window_focus()
            QtCore.QTimer.singleShot(50, self._reclaim_main_window_focus)
            QtCore.QTimer.singleShot(200, self._reclaim_main_window_focus)

    def _show_overlay_ui(self, auto: bool = False, page_ids: list[str] | None = None):
        try:
            self._ensure_current_profile_scene()
            self._apply_all_onscreen()
            if page_ids is None:
                active = self.scene.active_page_id
                targets = [active] if active and self.scene.page_by_id(active) else []
            else:
                targets = [page_id for page_id in page_ids if self.scene.page_by_id(page_id)]
            opened = False
            for page_id in targets:
                already = self.page_is_visible(page_id)
                self._show_page_ui(page_id, auto=auto)
                self._stream_page_id = page_id
                if not already:
                    opened = True
            if auto and opened:
                syslog.info("OBS OVERLAY: window opened for profile start")
            self._emit_visibility()
            self._invalidate_remote_window_cache()
        except Exception as err:
            syslog.error(f"OBS OVERLAY: failed to open overlay window: {err}")

    def _show_page_ui(self, page_id: str, auto: bool = False):
        apply_onscreen_geometry(self.scene, emit=False, page_id=page_id)
        window = self._overlays.get(page_id)
        if window is not None and Shiboken.isValid(window):
            # Already live (including app-share child): avoid flag rebuild / re-show storms.
            if window.isVisible() or getattr(window, "_host_attached", False):
                if self.scene.canvas_for(page_id).get("attach_to_window"):
                    window._sync_host_attach()
                return
            window._apply_window_flags()
            window.show_without_activating()
            self._enforce_exclusive_app_share(page_id)
            return
        window = OverlayWindow(self.scene, page_id=page_id)
        window.destroyed.connect(lambda *_args, pid=page_id: self._overlay_destroyed(pid))
        self._overlays[page_id] = window
        self._page_chrome[page_id] = self._page_chrome_tuple(page_id)
        window.show_without_activating()
        self._enforce_exclusive_app_share(page_id)

    def _sync_stream_to_active_page(self):
        """Track designer selection only — do not auto show/hide live windows.

        Forcing show on tab change fought toggle + app-share and stole focus
        (game cursor appearing over JG Ex).
        """
        active = self.scene.active_page_id
        if active and self.page_is_visible(active):
            self._stream_page_id = active

    def _enforce_exclusive_app_share(self, page_id: str):
        """Only one overlay may be parented into a host for app share."""
        canvas = self.scene.canvas_for(page_id)
        if not canvas.get("attach_to_window"):
            return
        for other_id, window in list(self._overlays.items()):
            if other_id == page_id or not Shiboken.isValid(window):
                continue
            other_canvas = self.scene.canvas_for(other_id)
            if not other_canvas.get("attach_to_window"):
                continue
            if getattr(window, "_host_attached", False) or window.isVisible():
                try:
                    window._detach_host()
                except Exception:
                    pass
                if window.isVisible():
                    window.hide()
        window = self._overlays.get(page_id)
        if window is not None and Shiboken.isValid(window) and (
            window.isVisible() or getattr(window, "_host_attached", False)
        ):
            window._sync_host_attach()

    def _invalidate_remote_window_cache(self):
        try:
            import gremlin.remote_video as remote_video

            cache = getattr(remote_video, "_hwnd_cache", None)
            if isinstance(cache, dict):
                cache["checked_at"] = 0.0
                cache["hwnd"] = 0
        except Exception:
            pass

    def _overlay_destroyed(self, page_id: str):
        current = self._overlays.get(page_id)
        if current is None or not Shiboken.isValid(current):
            self._overlays.pop(page_id, None)
            self._emit_visibility()

    def hide_overlay(self):
        gremlin.util.InvokeUiMethod(self._hide_overlay_ui)

    def _hide_overlay_ui(self):
        reclaim = False
        for page_id in list(self._overlays):
            window = self._overlays.get(page_id)
            if window is not None and Shiboken.isValid(window) and getattr(window, "_host_attached", False):
                reclaim = True
            self._hide_page_ui(page_id)
        self._emit_visibility()
        if reclaim:
            self._reclaim_main_window_focus()
            # Windows often ignores the first SetForegroundWindow after SetParent;
            # retry so the host cursor does not stay glued over JG Ex.
            QtCore.QTimer.singleShot(50, self._reclaim_main_window_focus)
            QtCore.QTimer.singleShot(200, self._reclaim_main_window_focus)

    def _reclaim_main_window_focus(self):
        """After app-share detach, ensure the game is not left covering JG Ex."""
        try:
            from .host_window import release_input_hooks, restore_foreground

            release_input_hooks()
            ui = gremlin.shared_state.ui
            if ui is None or not Shiboken.isValid(ui):
                return
            hwnd = int(ui.winId()) if hasattr(ui, "winId") else 0
            if hwnd:
                restore_foreground(hwnd)
            ui.raise_()
            ui.activateWindow()
        except Exception as err:
            syslog.debug(f"OBS OVERLAY: reclaim UI focus skipped: {err}")

    def _hide_page_ui(self, page_id: str):
        window = self._overlays.pop(page_id, None)
        if window is None:
            return
        try:
            if Shiboken.isValid(window):
                # Tear down app-share parenting before hide/close so the host
                # cannot stay raised over JG Ex after profile deactivation.
                try:
                    window._stop_host_follow()
                    window._detach_host(activate_host=False, hide_window=True)
                except Exception:
                    pass
                window.detach_from_scene()
                window.hide()
                window.close()
                window.deleteLater()
        except Exception as err:
            syslog.warning(f"OBS OVERLAY: failed to close overlay window: {err}")
        self._emit_visibility()

    def _release_overlay_touch(self):
        for window in list(self._overlays.values()):
            if window is None or not Shiboken.isValid(window):
                continue
            view = getattr(window, "view", None)
            if view is not None and Shiboken.isValid(view):
                view.release_touch()

    def _emit_visibility(self):
        try:
            self.visibility_changed.emit()
        except Exception:
            pass


def launch_designer(parent=None):
    OverlayManager().launch_designer(parent)


def show_overlay(auto: bool = False):
    OverlayManager().show_overlay(auto=auto)


def hide_overlay():
    OverlayManager().hide_overlay()


def persist_for_profile(profile, dest_xml: str | None = None) -> bool:
    """Write the in-memory overlay next to the profile XML that was just saved."""
    try:
        if OverlayManager.instance is None:
            return False
        scene = OverlayManager.instance.scene
        ok = scene.save_to_profile(profile, dest_xml=dest_xml)
        if not ok:
            syslog.warning("OBS OVERLAY: profile save did not write the overlay layout")
        return ok
    except Exception as err:
        syslog.warning(f"OBS OVERLAY: persist on profile save failed: {err}")
        return False


def current_scene() -> OverlayScene:
    return OverlayManager().scene
