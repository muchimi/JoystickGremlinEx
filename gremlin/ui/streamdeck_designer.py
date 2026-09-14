# -*- coding: utf-8; -*-
#
# Companion-style Stream Deck designer (Overlay-inspired three-pane UI).
# Left: GEX virtual pages | Center: deck grid | Right pane is the device tab mapping panel.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import base64
import hashlib
import logging
import os
import shutil
import uuid

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.util
from gremlin.ui.ui_common import Color

syslog = logging.getLogger("system")

_ICON_DROP_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
_SLOT_MIME = "application/x-jgex-sd-slot"
_button_clipboard: dict | None = None
_STREAMDECK_ICONS_DIRNAME = "streamdeck_icons"
_CLIPBOARD_CONTAINERS_KEY = "_containers_xml"


def _containers_xml_snapshot(item) -> bytes | None:
    """Serialize an input item's action containers for clipboard paste."""
    if item is None:
        return None
    try:
        containers = list(item.containers) if getattr(item, "containers", None) else []
        if not containers:
            return None
        from lxml import etree

        root = etree.Element("multi_containers")
        for container in containers:
            root.append(container.to_xml())
        return etree.tostring(root)
    except Exception as err:
        syslog.error(f"STREAMDECK: copy containers failed: {err}")
        return None


def _apply_containers_xml(item, xml_bytes) -> None:
    """Replace ``item`` containers with clones from a MultiContainer XML snapshot."""
    if item is None:
        return
    model = item.containers
    suspended = False
    try:
        if hasattr(model, "pushSuspend"):
            model.pushSuspend()
            suspended = True
        try:
            while model and len(model):
                model.removeAt(0)
        except Exception:
            try:
                if hasattr(model, "clear"):
                    model.clear()
            except Exception:
                pass
        if not xml_bytes:
            return
        from lxml import etree
        from gremlin.plugin_manager import ContainerPlugins

        plugin_manager = ContainerPlugins()
        root = etree.fromstring(xml_bytes)
        extra_data = {"paste": True}
        for node in root:
            container_type = node.get("type")
            if container_type not in plugin_manager.tag_map:
                continue
            try:
                new_container = plugin_manager.tag_map[container_type](item)
                new_container.from_xml(node, data=item, extra_data=extra_data)
                if hasattr(new_container, "generateGuids"):
                    new_container.generateGuids()
                plugin_manager.set_container_data(item, new_container)
                model.addContainer(new_container)
            except Exception as err:
                syslog.error(f"STREAMDECK: paste container failed: {err}")
    except Exception as err:
        syslog.error(f"STREAMDECK: paste containers failed: {err}")
    finally:
        if suspended:
            try:
                model.popSuspend()
            except Exception:
                pass


def _state_panel_colors(kind: str = "released") -> dict:
    """Cool (released) / warm (pressed) panel colors for dark or light theme."""
    dark = bool(gremlin.shared_state.is_dark_theme)
    if kind == "pressed":
        if dark:
            return {
                "panel_bg": "#2c2432",
                "border": "#7a5f8a",
                "title_fg": "#e2d0f0",
                "btn_fg": "#e8eef4",
                "btn_checked": "#6b4a82",
                "btn_hover": "#3a3042",
                "btn_checked_hover": "#7a5a92",
            }
        return {
            "panel_bg": "#eadff0",
            "border": "#8a6a9a",
            "title_fg": "#4a2860",
            "btn_fg": "#2a1838",
            "btn_checked": "#c9a8de",
            "btn_hover": "#ddd0e8",
            "btn_checked_hover": "#d4b5e6",
        }
    if dark:
        return {
            "panel_bg": "#1e2832",
            "border": "#5a7a90",
            "title_fg": "#c5d8e8",
            "btn_fg": "#e8eef4",
            "btn_checked": "#3d6ea5",
            "btn_hover": "#2a3540",
            "btn_checked_hover": "#4a7eb5",
        }
    return {
        "panel_bg": "#d8e6f0",
        "border": "#5a7a90",
        "title_fg": "#1e4560",
        "btn_fg": "#123040",
        "btn_checked": "#8eb6d8",
        "btn_hover": "#c8d8e6",
        "btn_checked_hover": "#9fc0de",
    }


def _swatch_empty_style() -> str:
    """Empty icon/BG square style matching current theme."""
    if gremlin.shared_state.is_dark_theme:
        return "QLabel { background: transparent; border:2px dashed #666; border-radius:8px; color:#888; }"
    return "QLabel { background: transparent; border:2px dashed #888; border-radius:8px; color:#555; }"


def _swatch_idle_icon_style() -> str:
    if gremlin.shared_state.is_dark_theme:
        return "QLabel { background:#222; border:2px solid #666; border-radius:8px; color:#888; }"
    return "QLabel { background:#f5f5f5; border:2px solid #999; border-radius:8px; color:#555; }"


def _local_image_path_from_mime(mime: QtCore.QMimeData) -> str:
    """Return a local image file path from drag mime data, or ''."""
    if mime is None:
        return ""
    paths = []
    if mime.hasUrls():
        for url in mime.urls():
            if url.isLocalFile():
                paths.append(url.toLocalFile())
    if not paths and mime.hasText():
        text = (mime.text() or "").strip().strip('"')
        if text and os.path.isfile(text):
            paths.append(text)
    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        if ext in _ICON_DROP_EXTS and os.path.isfile(path):
            return path
    return ""


def _profile_icons_dir() -> str:
    """``<profile_dir>/streamdeck_icons`` next to the open profile XML."""
    profile = gremlin.shared_state.current_profile
    fname = None
    if profile is not None:
        fname = getattr(profile, "_profile_fname", None) or getattr(profile, "profile_file", None)
    if not fname:
        # Fallback: keep icons under the user profile folder.
        try:
            base = gremlin.util.userprofile_path()
        except Exception:
            base = os.getcwd()
        dest = os.path.join(base, _STREAMDECK_ICONS_DIRNAME)
    else:
        dest = os.path.join(os.path.dirname(os.path.abspath(str(fname))), _STREAMDECK_ICONS_DIRNAME)
    os.makedirs(dest, exist_ok=True)
    return dest


def _import_icon_to_profile_folder(source_path: str) -> str:
    """Copy ``source_path`` into the profile ``streamdeck_icons`` folder and return that path.

    If the file is already inside that folder, returns it unchanged. Uses a content
    hash prefix so re-importing the same image reuses one file.
    """
    source_path = os.path.abspath(os.path.normpath(source_path or ""))
    if not source_path or not os.path.isfile(source_path):
        return ""
    icons_dir = os.path.abspath(_profile_icons_dir())
    try:
        common = os.path.commonpath([icons_dir, source_path])
    except ValueError:
        common = ""
    if common == icons_dir:
        return source_path.replace("\\", "/")

    ext = os.path.splitext(source_path)[1].lower() or ".png"
    if ext not in _ICON_DROP_EXTS:
        ext = ".png"
    # Stable name from content so identical drops don't duplicate files.
    try:
        digest = hashlib.sha1()
        with open(source_path, "rb") as hdl:
            while True:
                chunk = hdl.read(1024 * 256)
                if not chunk:
                    break
                digest.update(chunk)
        stem = digest.hexdigest()[:12]
    except Exception:
        stem = uuid.uuid4().hex[:12]
    base = os.path.splitext(os.path.basename(source_path))[0]
    # Keep a short readable hint from the original filename.
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in base)[:40].strip("_") or "icon"
    dest_name = f"{stem}_{safe}{ext}"
    dest_path = os.path.join(icons_dir, dest_name)
    if not os.path.isfile(dest_path):
        try:
            shutil.copy2(source_path, dest_path)
        except Exception as err:
            syslog.error(f"STREAMDECK: icon import failed: {err}")
            return ""
    return dest_path.replace("\\", "/")


def _pixmap_from_source(path: str = "", data_url: str = "") -> QtGui.QPixmap:
    """Load a key icon from a filesystem path or data-URL."""
    if path and os.path.isfile(path):
        pm = QtGui.QPixmap(path)
        if not pm.isNull():
            return pm
    raw = data_url or ""
    if raw.startswith("data:") and "," in raw:
        try:
            b64 = raw.split(",", 1)[1]
            data = base64.b64decode(b64)
            pm = QtGui.QPixmap()
            if pm.loadFromData(data):
                return pm
        except Exception:
            pass
    return QtGui.QPixmap()


def _pixmap_from_item(item, pressed: bool = False, *, dial_lcd: bool = False) -> QtGui.QPixmap:
    if item is None:
        return QtGui.QPixmap()
    try:
        from gremlin.ui.streamdeck_surface import compose_key_pixmap, item_needs_composite

        kind = getattr(item, "kind", "") or ""
        use_lcd = dial_lcd or kind in ("dial", "dial_press")
        if item_needs_composite(item, pressed=pressed) or (
            pressed and item_needs_composite(item, pressed=False)
        ) or (use_lcd and (getattr(item, "bg_color", "") or getattr(item, "bg_color_pressed", ""))):
            if use_lcd:
                return compose_key_pixmap(item, pressed=pressed, width=200, height=100)
            return compose_key_pixmap(item, size=144, pressed=pressed)
    except Exception:
        pass
    if pressed:
        path = getattr(item, "image_pressed_path", "") or getattr(item, "image_path", "") or ""
        data = getattr(item, "image_pressed", "") or getattr(item, "image", "") or ""
    else:
        path = getattr(item, "image_path", "") or ""
        data = getattr(item, "image", "") or ""
    return _pixmap_from_source(path, data)


class _IconPreviewSquare(QtWidgets.QLabel):
    """Square released/pressed icon preview; accepts image file drops."""

    icon_dropped = QtCore.Signal(str)
    clicked = QtCore.Signal()

    def __init__(self, tip: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setToolTip(tip)
        self.setAcceptDrops(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setStyleSheet(_swatch_idle_icon_style())
        self.setText("—")
        self.setScaledContents(False)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        if _local_image_path_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        if _local_image_path_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent):
        path = _local_image_path_from_mime(event.mimeData())
        if path:
            self.icon_dropped.emit(path)
            event.acceptProposedAction()
        else:
            event.ignore()


class _BgColorSquare(QtWidgets.QLabel):
    """Square swatch for key background color; click to pick, right-click to clear."""

    clicked = QtCore.Signal()
    clear_requested = QtCore.Signal()

    def __init__(self, tip: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setToolTip(tip)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self._color = ""
        self.set_color("")

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _context_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        act = menu.addAction("Clear background")
        if menu.exec(self.mapToGlobal(pos)) is act:
            self.clear_requested.emit()

    def set_color(self, color: str):
        self._color = color or ""
        if self._color:
            self.setText("")
            self.setStyleSheet(
                f"QLabel {{ background:{self._color}; border:2px solid #888; border-radius:8px; }}"
            )
        else:
            self.setText("BG")
            self.setStyleSheet(_swatch_empty_style())


class StreamDeckKeyButton(QtWidgets.QPushButton):
    """One cell on the deck grid (square key, optional icon)."""

    icon_dropped = QtCore.Signal(str)
    slot_moved = QtCore.Signal(object, object)  # src (kind,row,col), dst
    context_action = QtCore.Signal(str)  # copy|paste|delete|wipe_page|link:<page>|unlink

    def __init__(self, row: int, column: int, kind: str = "button", side: int = 80, parent=None):
        super().__init__(parent)
        self.row = row
        self.column = column
        self.kind = kind or "button"
        self._has_mappings = False
        self._foreign = False
        self._linked_page = 0
        self._label = ""
        self._pressed_flash = False
        self._drag_hover = False
        self._pixmap = QtGui.QPixmap()
        self._drag_start = None
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setToolTip("Click · Ctrl+click multi-select · drop image · drag to move · right-click menu")
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.set_side(side if kind == "button" else max(48, side - 12))
        self._apply_style()
        self._link_pages: list[tuple[int, str]] = []
        self._current_page = 0
        self._multi_count = 1

    def slot_tuple(self):
        return (self.kind, self.row, self.column)

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        # Foreign keys are selectable for icon/background, but cannot be
        # dragged — that would swap mappings onto a non-JG Ex hardware slot.
        if event.button() == QtCore.Qt.LeftButton and not getattr(self, "_foreign", False):
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if (
            self._drag_start is not None
            and (event.buttons() & QtCore.Qt.LeftButton)
            and (event.position().toPoint() - self._drag_start).manhattanLength()
            >= QtWidgets.QApplication.startDragDistance()
        ):
            self._start_slot_drag()
            self._drag_start = None
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def _start_slot_drag(self):
        if getattr(self, "_foreign", False):
            return
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        payload = f"{self.kind}|{self.row}|{self.column}"
        mime.setData(_SLOT_MIME, QtCore.QByteArray(payload.encode("utf-8")))
        mime.setText(payload)
        drag.setMimeData(mime)
        if not self._pixmap.isNull():
            drag.setPixmap(
                self._pixmap.scaled(48, 48, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            )
        drag.exec(QtCore.Qt.MoveAction)

    def set_link_pages(self, pages: list[tuple[int, str]], current_page: int = 0, multi_count: int = 1):
        """Pages available for Link to page submenu: [(page_num, label), ...]."""
        self._link_pages = list(pages or [])
        self._current_page = int(current_page or 0)
        self._multi_count = max(1, int(multi_count or 1))

    def _show_context_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        multi = max(1, int(getattr(self, "_multi_count", 1) or 1))
        if getattr(self, "_foreign", False):
            info = menu.addAction("Not a JG Ex Button — icon / background only")
            info.setEnabled(False)
            menu.addSeparator()
            act_copy = menu.addAction("Copy look")
            act_paste = menu.addAction("Paste look")
            act_paste.setEnabled(_button_clipboard is not None)
            menu.addSeparator()
            act_delete = menu.addAction("Clear look")
            menu.addSeparator()
            act_wipe = menu.addAction("Wipe page…")
            act_unlink = None
            link_actions = {}
        else:
            act_copy = menu.addAction("Copy button" if multi <= 1 else f"Copy button ({multi} selected — copies this one)")
            act_paste = menu.addAction("Paste button" if multi <= 1 else f"Paste onto {multi} buttons")
            act_paste.setEnabled(_button_clipboard is not None)
            menu.addSeparator()
            act_delete = menu.addAction("Delete button" if multi <= 1 else f"Delete {multi} buttons")
            menu.addSeparator()
            link_menu = menu.addMenu("Link to page" if multi <= 1 else f"Link {multi} buttons to page")
            link_actions = {}
            for page_num, label in getattr(self, "_link_pages", []) or []:
                if page_num == getattr(self, "_current_page", 0):
                    continue
                act = link_menu.addAction(label)
                link_actions[act] = int(page_num)
            if not link_actions:
                empty = link_menu.addAction("(no other pages)")
                empty.setEnabled(False)
            act_unlink = menu.addAction(
                "Unlink from page"
                if multi <= 1
                else f"Unlink {multi} buttons"
            )
            act_unlink.setEnabled(bool(getattr(self, "_linked_page", 0)) or multi > 1)
            if multi <= 1 and getattr(self, "_linked_page", 0):
                act_unlink.setText(f"Unlink from page {int(self._linked_page)}")
            menu.addSeparator()
            act_wipe = menu.addAction("Wipe page…")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_copy:
            self.context_action.emit("copy")
        elif chosen is act_paste:
            self.context_action.emit("paste")
        elif chosen is act_delete:
            self.context_action.emit("delete")
        elif chosen is act_wipe:
            self.context_action.emit("wipe_page")
        elif act_unlink is not None and chosen is act_unlink:
            self.context_action.emit("unlink")
        elif chosen in link_actions:
            self.context_action.emit(f"link:{link_actions[chosen]}")

    def set_side(self, side: int):
        if not Shiboken.isValid(self):
            return
        side = max(40, int(side))
        self._side = side
        self.setFixedSize(side, side)
        self.update()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return width

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(getattr(self, "_side", 80), getattr(self, "_side", 80))

    def minimumSizeHint(self) -> QtCore.QSize:
        return self.sizeHint()

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        mime = event.mimeData()
        if not mime:
            event.ignore()
            return
        # Linked slots are display-only proxies — no icon drop / slot swap.
        if getattr(self, "_linked_page", 0):
            event.ignore()
            return
        # Foreign keys accept an image drop (icon only), not a slot-swap.
        ok = bool(_local_image_path_from_mime(mime))
        if not getattr(self, "_foreign", False) and mime.hasFormat(_SLOT_MIME):
            ok = True
        if ok:
            self._drag_hover = True
            self._apply_style()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        mime = event.mimeData()
        if not mime or getattr(self, "_linked_page", 0):
            event.ignore()
            return
        ok = bool(_local_image_path_from_mime(mime))
        if not getattr(self, "_foreign", False) and mime.hasFormat(_SLOT_MIME):
            ok = True
        if ok:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent):
        self._drag_hover = False
        self._apply_style()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent):
        self._drag_hover = False
        self._apply_style()
        if getattr(self, "_linked_page", 0):
            event.ignore()
            return
        mime = event.mimeData()
        if mime and mime.hasFormat(_SLOT_MIME) and not getattr(self, "_foreign", False):
            raw = bytes(mime.data(_SLOT_MIME)).decode("utf-8", errors="ignore")
            parts = raw.split("|")
            if len(parts) == 3:
                try:
                    src = (parts[0], int(parts[1]), int(parts[2]))
                    dst = self.slot_tuple()
                    if src != dst:
                        self.slot_moved.emit(src, dst)
                    event.acceptProposedAction()
                    return
                except ValueError:
                    pass
        path = _local_image_path_from_mime(mime)
        if path:
            self.icon_dropped.emit(path)
            event.acceptProposedAction()
        else:
            event.ignore()

    def set_cell(
        self,
        label: str,
        has_mappings: bool,
        pixmap: QtGui.QPixmap | None = None,
        foreign: bool = False,
        linked_page: int = 0,
    ):
        if not Shiboken.isValid(self):
            return
        self._label = label or ""
        self._linked_page = int(linked_page or 0)
        self._has_mappings = bool(has_mappings) and not foreign and not self._linked_page
        self._foreign = bool(foreign)
        self._pixmap = pixmap if pixmap is not None and not pixmap.isNull() else QtGui.QPixmap()
        self.setText("")
        self.setIcon(QtGui.QIcon())
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        if self._foreign:
            self.setToolTip(
                "Not a JG Ex Button on the Stream Deck.\n"
                "Icon and background only — mappings cannot be added here.\n"
                "Place a JG Ex Button in Stream Deck software to map this key."
            )
        elif self._linked_page:
            tip = self._label or f"{self.row}:{self.column}"
            self.setToolTip(
                f"{tip}\n"
                f"Linked to page {self._linked_page} — mirrors that page’s same key.\n"
                f"Edit icon, style, and mappings on page {self._linked_page}.\n"
                "Ctrl+click to multi-select · right-click menu"
            )
        else:
            tip = self._label or f"{self.row}:{self.column}"
            self.setToolTip(
                f"{tip}\nCtrl+click multi-select · drop image · drag to move · right-click menu"
            )
        self._apply_style()
        self.update()

    def set_pressed_flash(self, pressed: bool):
        if not Shiboken.isValid(self):
            return
        self._pressed_flash = bool(pressed)
        self._apply_style()

    def _apply_style(self):
        if not Shiboken.isValid(self):
            return
        bg = Color.actionBackgroundColor()
        border = Color.activeColor() if self.isChecked() else Color.normalColor()
        if self._foreign:
            border = "#a45a5a"
            bg = "#2a1818"
        elif self._linked_page:
            border = "#7a6cff" if not self.isChecked() else Color.activeColor()
            bg = "#1c1a32"
        elif self._has_mappings and not self.isChecked():
            border = "#6a9" if not border else border
        if self._pressed_flash and not self._foreign:
            border = "#f0a020"
            bg = "#3a3018"
        if self._drag_hover:
            border = "#4da3ff"
            bg = "#1a2a3a"
        radius = max(6, getattr(self, "_side", 80) // 10)
        self.setStyleSheet(
            f"QPushButton {{ background:{bg}; border:2px solid {border}; border-radius:{radius}px; padding:2px; }}"
            f"QPushButton:checked {{ border:2px solid {Color.activeColor()}; }}"
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        if not Shiboken.isValid(self):
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        if not self._pixmap.isNull():
            margin = max(4, self.width() // 14)
            avail = self.rect().adjusted(margin, margin, -margin, -margin)
            side = min(avail.width(), avail.height())
            scaled = self._pixmap.scaled(
                side, side, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
            )
            x = avail.x() + (avail.width() - scaled.width()) // 2
            y = avail.y() + (avail.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            caption = (self._label or "").strip()
            if not caption:
                caption = (
                    f"{self.column + 1}/{self.row + 1}"
                    if self.kind == "button"
                    else f"D{self.column + 1}"
                )
            # Light-on-light fails in light mode; use theme text color.
            painter.setPen(
                QtGui.QColor(
                    "#c47878"
                    if self._foreign
                    else ("#b8b0ff" if self._linked_page else Color.normalColor())
                )
            )
            font = painter.font()
            font.setFamily("Segoe UI")
            font.setBold(True)
            font.setPixelSize(max(14, int(self.width() * 0.32)))
            painter.setFont(font)
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, caption)
        if self._foreign:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor("#d45454"))
            painter.drawEllipse(self.width() - 14, 6, 8, 8)
        elif self._linked_page:
            # Corner badge: ↗P# so linked keys are obvious next to mapping dots.
            badge = f"↗{int(self._linked_page)}"
            font = painter.font()
            font.setFamily("Segoe UI")
            font.setBold(True)
            font.setPixelSize(max(9, int(self.width() * 0.16)))
            painter.setFont(font)
            metrics = painter.fontMetrics()
            tw = metrics.horizontalAdvance(badge) + 6
            th = metrics.height() + 2
            br = QtCore.QRect(self.width() - tw - 4, 4, tw, th)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor("#5a4fd4"))
            painter.drawRoundedRect(br, 3, 3)
            painter.setPen(QtGui.QColor("#ffffff"))
            painter.drawText(br, QtCore.Qt.AlignCenter, badge)
        elif self._has_mappings:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor("#6ac48a"))
            painter.drawEllipse(self.width() - 14, 6, 8, 8)
        painter.end()


class StreamDeckDialScreenWidget(QtWidgets.QWidget):
    """Stream Deck + touch-strip LCD segment above a dial (≈200×100 preview)."""

    clicked = QtCore.Signal()
    icon_dropped = QtCore.Signal(str)

    def __init__(self, column: int, width: int = 120, parent=None):
        super().__init__(parent)
        self.column = int(column)
        self._w = max(72, int(width))
        self._label = ""
        self._pixmap = QtGui.QPixmap()
        self._bg = ""
        self._selected = False
        self.setAcceptDrops(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip("Dial LCD — icon, title, and background for this dial window")
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self._apply_size()

    def _apply_size(self):
        # Hardware encoder canvas is 200×100 — keep 2:1 in the designer.
        h = max(36, int(self._w * 0.5))
        self.setFixedSize(self._w, h)

    def set_width(self, width: int):
        if not Shiboken.isValid(self):
            return
        self._w = max(72, int(width))
        self._apply_size()
        self.update()

    def set_content(self, label: str = "", pixmap: QtGui.QPixmap | None = None, bg: str = ""):
        if not Shiboken.isValid(self):
            return
        # When a composed pixmap is provided it already includes bg/icon/text.
        self._label = label or ""
        self._pixmap = pixmap if pixmap is not None and not pixmap.isNull() else QtGui.QPixmap()
        self._bg = bg or ""
        self.update()

    def set_selected(self, selected: bool):
        if not Shiboken.isValid(self):
            return
        self._selected = bool(selected)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        r = self.rect().adjusted(1, 1, -1, -1)
        fill = self._bg if self._bg else Color.actionBackgroundColor()
        border = Color.activeColor() if self._selected else Color.normalColor()
        painter.setBrush(QtGui.QColor(fill))
        painter.setPen(QtGui.QPen(QtGui.QColor(border), 2 if self._selected else 1))
        painter.drawRoundedRect(r, 6, 6)

        inner = r.adjusted(3, 3, -3, -3)
        if not self._pixmap.isNull():
            # Stretch to fill the LCD window (hardware canvas is already 2:1).
            scaled = self._pixmap.scaled(
                inner.size(), QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation
            )
            painter.drawPixmap(inner.topLeft(), scaled)
        else:
            caption = (self._label or "").strip() or f"LCD {self.column + 1}"
            painter.setPen(QtGui.QColor(Color.normalColor() if self._bg else Color.grayColor()))
            font = painter.font()
            font.setFamily("Segoe UI")
            font.setBold(True)
            font.setPixelSize(max(10, int(self.height() * 0.28)))
            painter.setFont(font)
            painter.drawText(inner, QtCore.Qt.AlignCenter, caption)
        painter.end()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        if _local_image_path_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        if _local_image_path_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent):
        path = _local_image_path_from_mime(event.mimeData())
        if path:
            self.icon_dropped.emit(path)
            event.acceptProposedAction()
        else:
            event.ignore()


class StreamDeckDialWidget(QtWidgets.QWidget):
    """Stream Deck + dial: circular press face with CW / CCW rotate hit targets."""

    press_clicked = QtCore.Signal()
    inc_clicked = QtCore.Signal()  # clockwise
    dec_clicked = QtCore.Signal()  # counterclockwise
    icon_dropped = QtCore.Signal(str)
    context_action = QtCore.Signal(str)

    def __init__(self, column: int, side: int = 72, parent=None):
        super().__init__(parent)
        self.column = int(column)
        self.kind = "dial_press"
        self.row = 0
        self._side = max(48, int(side))
        self._label = ""
        self._pixmap = QtGui.QPixmap()
        self._has_press = False
        self._has_inc = False
        self._has_dec = False
        self._foreign = False
        self._sel = ""  # "", "press", "inc", "dec"
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(
            "Center: dial press mappings\n"
            "↻: clockwise rotate mappings\n"
            "↺: counterclockwise rotate mappings\n"
            "LCD above: icon / title / background"
        )
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self._apply_size()

    def _apply_size(self):
        # Room for side arrows around the circle.
        w = int(self._side * 1.85)
        h = int(self._side * 1.15)
        self.setFixedSize(w, h)

    def set_side(self, side: int):
        if not Shiboken.isValid(self):
            return
        self._side = max(48, int(side))
        self._apply_size()
        self.update()

    def set_cell(self, label: str, has_press: bool, pixmap: QtGui.QPixmap | None = None,
                 has_inc: bool = False, has_dec: bool = False, foreign: bool = False):
        if not Shiboken.isValid(self):
            return
        self._label = label or ""
        self._foreign = bool(foreign)
        self._has_press = bool(has_press) and not self._foreign
        self._has_inc = bool(has_inc) and not self._foreign
        self._has_dec = bool(has_dec) and not self._foreign
        self._pixmap = pixmap if pixmap is not None and not pixmap.isNull() else QtGui.QPixmap()
        self.setCursor(QtCore.Qt.ForbiddenCursor if self._foreign else QtCore.Qt.PointingHandCursor)
        self.setAcceptDrops(not self._foreign)
        if self._foreign:
            self.setToolTip("Not a JG Ex Dial on the Stream Deck.")
            self._sel = ""
        else:
            self.setToolTip(
                "Center: dial press mappings\n"
                "↻: clockwise rotate mappings\n"
                "↺: counterclockwise rotate mappings\n"
                "LCD above: icon / title / background"
            )
        self.update()

    def set_selection(self, part: str):
        """part: '' | 'press' | 'inc' | 'dec'"""
        if not Shiboken.isValid(self):
            return
        self._sel = part or ""
        self.update()

    def _circle_rect(self) -> QtCore.QRect:
        d = int(self._side * 0.82)
        x = (self.width() - d) // 2
        y = (self.height() - d) // 2
        return QtCore.QRect(x, y, d, d)

    def _arrow_rects(self):
        """Return (dec_rect, inc_rect) hit targets left/right of the circle."""
        cr = self._circle_rect()
        aw = max(22, int(self._side * 0.34))
        ah = max(28, int(self._side * 0.55))
        cy = self.height() // 2
        dec = QtCore.QRect(2, cy - ah // 2, aw, ah)
        inc = QtCore.QRect(self.width() - aw - 2, cy - ah // 2, aw, ah)
        # Keep arrows clear of circle a bit
        if dec.right() > cr.left() - 2:
            dec.moveRight(cr.left() - 2)
        if inc.left() < cr.right() + 2:
            inc.moveLeft(cr.right() + 2)
        return dec, inc

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)

        bg = Color.actionBackgroundColor()
        text = Color.normalColor()
        active = Color.activeColor()

        # Arrows (counterclockwise left, clockwise right)
        dec_r, inc_r = self._arrow_rects()
        for rect, glyph, selected, mapped in (
            (dec_r, "↺", self._sel == "dec", self._has_dec),
            (inc_r, "↻", self._sel == "inc", self._has_inc),
        ):
            if selected:
                painter.setBrush(QtGui.QColor(active))
                painter.setPen(QtGui.QPen(QtGui.QColor(active), 1))
                painter.setOpacity(0.25)
                painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)
                painter.setOpacity(1.0)
            font = painter.font()
            font.setFamily("Segoe UI Symbol")
            font.setBold(True)
            font.setPixelSize(max(16, int(self._side * 0.36)))
            painter.setFont(font)
            painter.setPen(QtGui.QColor(active if selected else (Color.greenColor() if mapped else text)))
            painter.drawText(rect, QtCore.Qt.AlignCenter, glyph)
            if mapped and not selected:
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(QtGui.QColor("#6ac48a"))
                painter.drawEllipse(rect.center().x() - 3, rect.bottom() - 8, 6, 6)

        # Circle face (knob) — LCD content lives on the strip above.
        cr = self._circle_rect()
        border = active if self._sel == "press" else Color.normalColor()
        if self._has_press and self._sel != "press":
            border = "#6a9"
        painter.setBrush(QtGui.QColor(bg))
        painter.setPen(QtGui.QPen(QtGui.QColor(border), 2 if self._sel != "press" else 3))
        painter.drawEllipse(cr)
        painter.setPen(QtGui.QColor(text))
        font = painter.font()
        font.setFamily("Segoe UI")
        font.setBold(True)
        font.setPixelSize(max(11, int(cr.width() * 0.28)))
        painter.setFont(font)
        painter.drawText(cr, QtCore.Qt.AlignCenter, f"D{self.column + 1}")

        if self._has_press:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor("#6ac48a"))
            painter.drawEllipse(cr.right() - 12, cr.top() + 4, 8, 8)
        elif getattr(self, "_foreign", False):
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor("#d45454"))
            painter.drawEllipse(cr.right() - 12, cr.top() + 4, 8, 8)

        painter.end()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if getattr(self, "_foreign", False):
            event.ignore()
            return
        if event.button() == QtCore.Qt.LeftButton:
            pos = event.position().toPoint()
            dec_r, inc_r = self._arrow_rects()
            if dec_r.contains(pos):
                self.dec_clicked.emit()
                event.accept()
                return
            if inc_r.contains(pos):
                self.inc_clicked.emit()
                event.accept()
                return
            if self._circle_rect().contains(pos):
                self.press_clicked.emit()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        if _local_image_path_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        if _local_image_path_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent):
        path = _local_image_path_from_mime(event.mimeData())
        if path and self._circle_rect().contains(event.position().toPoint()):
            self.icon_dropped.emit(path)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _show_context_menu(self, pos):
        # Context only on the press face
        if not self._circle_rect().contains(pos):
            return
        menu = QtWidgets.QMenu(self)
        act_copy = menu.addAction("Copy dial press")
        act_paste = menu.addAction("Paste onto dial press")
        act_paste.setEnabled(_button_clipboard is not None)
        menu.addSeparator()
        act_delete = menu.addAction("Delete dial press")
        menu.addSeparator()
        act_wipe = menu.addAction("Wipe page…")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_copy:
            self.context_action.emit("copy")
        elif chosen is act_paste:
            self.context_action.emit("paste")
        elif chosen is act_delete:
            self.context_action.emit("delete")
        elif chosen is act_wipe:
            self.context_action.emit("wipe_page")


class StreamDeckDesignerWidget(QtWidgets.QWidget):
    """Pages list + graphical deck grid (Overlay-style left/center)."""

    selection_changed = QtCore.Signal(object)  # StreamDeckInputItem | None
    # True = show right-pane mappings; False = appearance-only (dial LCD).
    mapping_enabled_changed = QtCore.Signal(bool)
    pages_changed = QtCore.Signal()

    def __init__(self, device_tab, parent=None):
        super().__init__(parent)
        self._tab = device_tab
        self._device_id = getattr(device_tab, "_elgato_device_id", "") or ""
        self._edit_page = 1
        self._selected_row = None
        self._selected_col = None
        self._selected_kind = "button"
        # Ctrl+click multi-select for button slots: set of (kind, row, col)
        self._multi_selection: set[tuple[str, int, int]] = set()
        self._cells: dict[tuple[str, int, int], StreamDeckKeyButton] = {}
        self._dial_cells: dict[int, StreamDeckDialWidget] = {}
        self._dial_screens: dict[int, StreamDeckDialScreenWidget] = {}
        self._grid_widget = None
        self._grid_cols = 5
        self._grid_rows = 3
        self._scroll = None
        self._cell_side = 80
        self._rebuilding = False
        self._refresh_pending = False
        self._cells_pending = False
        self._size_pending = False
        self._bridge_hooks = []
        self._press_clear_timer = None
        self._preview_pressed = False  # designer grid shows released vs pressed appearance

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        root.addWidget(self._build_toolbar())

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setChildrenCollapsible(True)
        splitter.addWidget(self._build_pages_panel())
        splitter.addWidget(self._build_grid_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([160, 560])
        self._main_splitter = splitter
        self.setMinimumWidth(0)
        root.addWidget(splitter, 1)

        from gremlin.ui.streamdeck_device import StreamDeckBridge

        bridge = StreamDeckBridge()
        bridge.virtual_page_changed.connect(self._on_virtual_page_changed)
        bridge.inputs_changed.connect(self._on_inputs_changed)
        bridge.plugin_connected.connect(self._on_plugin_connected)
        bridge.slot_pressed.connect(self._on_slot_pressed)
        self._bridge_hooks = [
            (bridge.virtual_page_changed, self._on_virtual_page_changed),
            (bridge.inputs_changed, self._on_inputs_changed),
            (bridge.plugin_connected, self._on_plugin_connected),
            (bridge.slot_pressed, self._on_slot_pressed),
        ]

        try:
            import gremlin.event_handler

            el = gremlin.event_handler.EventListener()
            el.profile_start.connect(self._on_profile_start)
            el.profile_stop.connect(self._on_profile_stop)
            self._bridge_hooks.extend(
                [
                    (el.profile_start, self._on_profile_start),
                    (el.profile_stop, self._on_profile_stop),
                ]
            )
        except Exception:
            pass

        self.refresh()
        self._apply_runtime_lock(bool(gremlin.shared_state.is_running))

    def closeEvent(self, event):
        self._disconnect_bridge()
        super().closeEvent(event)

    def _cleanup_ui(self):
        self._disconnect_bridge()
        self._clear_cells()

    def _disconnect_bridge(self):
        for signal, slot in list(self._bridge_hooks):
            try:
                signal.disconnect(slot)
            except Exception:
                pass
        self._bridge_hooks.clear()

    def _on_plugin_connected(self, _connected: bool):
        if self._runtime_locked():
            return
        self._schedule_refresh()

    def _runtime_locked(self) -> bool:
        """True while the profile is executing — designer must stay frozen."""
        return bool(gremlin.shared_state.is_running)

    def _on_profile_start(self):
        self._apply_runtime_lock(True)

    def _on_profile_stop(self):
        self._apply_runtime_lock(False)
        # One catch-up refresh after stop so the grid matches live state.
        self._schedule_refresh()

    def _apply_runtime_lock(self, locked: bool):
        """Disable designer interaction while the profile runs; keep display frozen."""
        if not Shiboken.isValid(self):
            return
        # Cancel pending UI work so page changes / presses don't paint the grid.
        self._refresh_pending = False
        self._cells_pending = False
        interactive = not locked
        for name in (
            "_page_list",
            "_grid_widget",
            "_scroll",
            "_status",
            "_grid_title",
            "_preview_released_btn",
            "_preview_pressed_btn",
            "_appearance_panel",
        ):
            w = getattr(self, name, None)
            if w is not None and Shiboken.isValid(w):
                w.setEnabled(interactive)
        # Disable page buttons / toolbar children without blanking the whole widget.
        for child in self.findChildren(QtWidgets.QPushButton):
            if Shiboken.isValid(child):
                child.setEnabled(interactive)
        if locked and getattr(self, "_status", None) is not None and Shiboken.isValid(self._status):
            self._status.setText("Profile running — designer locked (actions only)")
            self._status.setEnabled(True)

    def _bridge(self):
        from gremlin.ui.streamdeck_device import StreamDeckBridge

        return StreamDeckBridge()

    def _schedule_refresh(self):
        """Coalesce full UI rebuilds (willAppear storms must not touch deleted cells)."""
        if not Shiboken.isValid(self) or self._runtime_locked():
            return
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QtCore.QTimer.singleShot(0, self._run_scheduled_refresh)

    def _run_scheduled_refresh(self):
        self._refresh_pending = False
        if Shiboken.isValid(self) and not self._runtime_locked():
            self.refresh()

    def _schedule_cell_refresh(self):
        if not Shiboken.isValid(self) or self._runtime_locked():
            return
        if self._rebuilding or self._refresh_pending:
            return
        if self._cells_pending:
            return
        self._cells_pending = True
        QtCore.QTimer.singleShot(0, self._run_scheduled_cell_refresh)

    def _run_scheduled_cell_refresh(self):
        self._cells_pending = False
        if Shiboken.isValid(self) and not self._rebuilding and not self._runtime_locked():
            self._refresh_cell_contents()

    def _clear_cells(self):
        """Drop grid buttons immediately so stale refs cannot be painted."""
        old = (
            list(self._cells.values())
            + list(self._dial_cells.values())
            + list(getattr(self, "_dial_screens", {}).values())
        )
        self._cells.clear()
        self._dial_cells.clear()
        self._dial_screens = {}
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for w in old:
            if Shiboken.isValid(w):
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _build_toolbar(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)

        self._status = QtWidgets.QLabel()
        self._status.setObjectName("streamdeck_designer_status")
        refresh = gremlin.ui.ui_common.Buttons.getRefreshWidget(
            "Refresh",
            tooltip="Reload live plugin keys",
            callback=self._on_refresh,
        )
        clear_btn = QtWidgets.QPushButton("Clear cell")
        clear_btn.setToolTip("Remove mappings and appearance from the selected key on this page")
        clear_btn.clicked.connect(self._clear_selected_cell)
        wipe_btn = QtWidgets.QPushButton("Wipe page")
        wipe_btn.setToolTip("Clear all keys on the current edit page")
        wipe_btn.clicked.connect(self._wipe_page)

        layout.addWidget(self._status, 1)
        layout.addWidget(refresh)
        layout.addWidget(clear_btn)
        layout.addWidget(wipe_btn)
        return bar

    def _build_pages_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        panel.setMinimumWidth(0)
        panel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        panel.setMaximumWidth(260)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QtWidgets.QLabel("Pages")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        self._page_list = QtWidgets.QListWidget()
        self._page_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._page_list.currentRowChanged.connect(self._on_page_row_changed)
        self._page_list.itemDoubleClicked.connect(self._rename_page)
        layout.addWidget(self._page_list, 1)

        row = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("Add")
        add_btn.clicked.connect(self._add_page)
        del_btn = QtWidgets.QPushButton("Delete")
        del_btn.clicked.connect(self._delete_page)
        rename_btn = QtWidgets.QPushButton("Rename")
        rename_btn.clicked.connect(self._rename_page)
        row.addWidget(add_btn)
        row.addWidget(rename_btn)
        row.addWidget(del_btn)
        layout.addLayout(row)

        import_btn = QtWidgets.QPushButton("Import")
        import_btn.setToolTip("Import page appearance from a Bitfocus Companion configuration export")
        import_btn.clicked.connect(self._import_companion_pages)
        layout.addWidget(import_btn)
        return panel

    def _build_grid_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QtWidgets.QHBoxLayout()
        self._grid_title = QtWidgets.QLabel("Deck")
        self._grid_title.setStyleSheet("font-weight: bold;")
        header.addWidget(self._grid_title, 1)

        preview_wrap = QtWidgets.QWidget()
        preview_row = QtWidgets.QHBoxLayout(preview_wrap)
        preview_row.setContentsMargins(0, 0, 0, 0)
        preview_row.setSpacing(0)
        preview_lbl = QtWidgets.QLabel("Preview:")
        preview_lbl.setStyleSheet(
            f"color: {Color.normalColor()}; padding-right: 8px; font-size: 12px;"
        )
        preview_font = QtGui.QFont(self.font())
        preview_font.setPointSize(11)
        preview_font.setBold(False)

        def _preview_btn(text: str) -> QtWidgets.QPushButton:
            btn = QtWidgets.QPushButton(text)
            btn.setCheckable(True)
            btn.setFont(preview_font)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            # Prefer readable labels, but allow shrink in narrow designer panes.
            btn.setMinimumWidth(72 if text == "Released" else 64)
            btn.setMinimumHeight(28)
            btn.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
            return btn

        self._preview_released_btn = _preview_btn("Released")
        self._preview_released_btn.setChecked(True)
        self._preview_released_btn.setToolTip("Show released (idle) appearance on the grid")
        self._preview_pressed_btn = _preview_btn("Pressed")
        self._preview_pressed_btn.setToolTip("Show pressed appearance on the grid")
        self._preview_group = QtWidgets.QButtonGroup(self)
        self._preview_group.setExclusive(True)
        self._preview_group.addButton(self._preview_released_btn, 0)
        self._preview_group.addButton(self._preview_pressed_btn, 1)
        self._preview_group.idClicked.connect(self._on_preview_state_changed)
        # Segmented look — match Released (cool) / Pressed (warm) panel tints
        rel_c = _state_panel_colors("released")
        prs_c = _state_panel_colors("pressed")
        self._preview_released_btn.setStyleSheet(
            "QPushButton {"
            f"  padding: 4px 10px; min-width: 72px; border: 1px solid {rel_c['border']};"
            f"  background: {rel_c['panel_bg']};"
            "  border-top-left-radius: 4px; border-bottom-left-radius: 4px;"
            f"  font-size: 12px; color: {rel_c['btn_fg']};"
            "}"
            f"QPushButton:checked {{ background: {rel_c['btn_checked']}; border-color: {rel_c['border']}; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {rel_c['btn_hover']}; }}"
            f"QPushButton:checked:hover {{ background: {rel_c['btn_checked_hover']}; }}"
        )
        self._preview_pressed_btn.setStyleSheet(
            "QPushButton {"
            f"  padding: 4px 10px; min-width: 64px; border: 1px solid {prs_c['border']};"
            f"  background: {prs_c['panel_bg']};"
            "  border-top-right-radius: 4px; border-bottom-right-radius: 4px; margin-left: -1px;"
            f"  font-size: 12px; color: {prs_c['btn_fg']};"
            "}"
            f"QPushButton:checked {{ background: {prs_c['btn_checked']}; border-color: {prs_c['border']}; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {prs_c['btn_hover']}; }}"
            f"QPushButton:checked:hover {{ background: {prs_c['btn_checked_hover']}; }}"
        )
        preview_row.addWidget(preview_lbl)
        preview_row.addWidget(self._preview_released_btn)
        preview_row.addWidget(self._preview_pressed_btn)
        header.addWidget(preview_wrap, 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        layout.addLayout(header)
        layout.setSpacing(4)

        # Scroll hosts grid + settings as one top-aligned column (no dead space
        # between the deck and the Released/Pressed panels).
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        bg = Color.actionBackgroundColor()
        scroll.setStyleSheet(f"QScrollArea {{ background: {bg}; border: none; }}")
        self._scroll = scroll

        scroll_body = QtWidgets.QWidget()
        scroll_body.setStyleSheet(f"background: {bg};")
        body_layout = QtWidgets.QVBoxLayout(scroll_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        # Top-align only — horizontal centering kept oversized panels from
        # shrinking and they spilled under the mapping pane.
        body_layout.setAlignment(QtCore.Qt.AlignTop)
        scroll_body.setMinimumWidth(0)

        self._grid_host = QtWidgets.QWidget()
        self._grid_host.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum
        )
        self._grid_layout = QtWidgets.QGridLayout(self._grid_host)
        self._grid_layout.setSpacing(8)
        self._grid_layout.setContentsMargins(8, 4, 8, 4)
        self._grid_layout.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        body_layout.addWidget(self._grid_host, 0, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)

        self._props_host = QtWidgets.QWidget()
        self._props_host.setMinimumWidth(0)
        self._props_host.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum
        )
        props = QtWidgets.QVBoxLayout(self._props_host)
        props.setContentsMargins(4, 0, 4, 8)
        props.setSpacing(6)

        def _section_box(title: str, *, kind: str = "released") -> QtWidgets.QGroupBox:
            """Section header: larger, bold, centered title; tinted panel by state."""
            box = QtWidgets.QGroupBox(title)
            box.setAlignment(QtCore.Qt.AlignHCenter)
            font = box.font()
            font.setPointSize(max(12, font.pointSize() + 3))
            font.setBold(True)
            box.setFont(font)
            c = _state_panel_colors(kind)
            panel_bg, border, title_fg = c["panel_bg"], c["border"], c["title_fg"]
            text_fg = Color.normalColor()
            popup_bg = Color.backgroundColor()
            # Title/style fields: tinted enough to see the panel, opaque enough in light mode.
            if gremlin.shared_state.is_dark_theme:
                field_bg = "rgba(0,0,0,0.28)"
                btn_bg = "rgba(0,0,0,0.18)"
                btn_hover = "rgba(255,255,255,0.08)"
            else:
                field_bg = "rgba(255,255,255,0.72)"
                btn_bg = "rgba(255,255,255,0.85)"
                btn_hover = "rgba(0,0,0,0.06)"
            box.setStyleSheet(
                f"QGroupBox {{"
                f"  margin-top: 0.85em;"
                f"  padding: 10px 8px 8px 8px;"
                f"  background-color: {panel_bg};"
                f"  border: 1px solid {border};"
                f"  border-radius: 8px;"
                f"  color: {text_fg};"
                f"}}"
                f"QGroupBox::title {{"
                f"  subcontrol-origin: margin;"
                f"  subcontrol-position: top center;"
                f"  padding: 0 10px;"
                f"  color: {title_fg};"
                f"  background-color: transparent;"
                f"}}"
                f"QPlainTextEdit, QLineEdit, QComboBox, QFontComboBox, QSpinBox, QAbstractSpinBox {{"
                f"  background-color: {field_bg};"
                f"  color: {text_fg};"
                f"  border: 1px solid {border};"
                f"  border-radius: 4px;"
                f"  padding: 2px 4px;"
                f"}}"
                f"QAbstractScrollArea {{ background-color: {field_bg}; border: none; }}"
                f"QPlainTextEdit:focus, QComboBox:focus, QFontComboBox:focus, QSpinBox:focus {{"
                f"  border: 1px solid {title_fg};"
                f"}}"
                f"QComboBox::drop-down {{ background: transparent; border: none; }}"
                f"QComboBox QAbstractItemView {{ background-color: {popup_bg}; color: {text_fg}; }}"
                f"QLabel {{ background: transparent; color: {text_fg}; }}"
                f"QCheckBox {{ background: transparent; color: {text_fg}; }}"
                f"QPushButton {{ background-color: {btn_bg}; color: {text_fg}; border: 1px solid {border}; border-radius: 4px; padding: 4px 8px; }}"
                f"QPushButton:hover {{ background-color: {btn_hover}; }}"
            )
            return box

        # Stack Released / Pressed vertically so the designer can shrink with the
        # window. Side-by-side forced a huge minimum width and blew the splitter.
        states_row = QtWidgets.QVBoxLayout()
        states_row.setSpacing(10)

        # Appearance driver: hardware press vs a named GEX state (OFF/ON).
        driver_host = QtWidgets.QWidget()
        self._appearance_driver_host = driver_host
        driver_layout = QtWidgets.QHBoxLayout(driver_host)
        driver_layout.setContentsMargins(0, 0, 0, 0)
        driver_layout.setSpacing(8)
        driver_layout.addWidget(QtWidgets.QLabel("Appearance"))
        self._appearance_mode_combo = QtWidgets.QComboBox()
        self._appearance_mode_combo.addItem("Press / Release", "press")
        self._appearance_mode_combo.addItem("GEX State", "state")
        self._appearance_mode_combo.setToolTip(
            "Press / Release follows the physical key hold. "
            "GEX State uses State OFF / State ON looks from a named state."
        )
        self._appearance_mode_combo.currentIndexChanged.connect(self._on_appearance_mode_ui)
        driver_layout.addWidget(self._appearance_mode_combo)
        self._appearance_state_label = QtWidgets.QLabel("State")
        driver_layout.addWidget(self._appearance_state_label)
        self._appearance_state_combo = QtWidgets.QComboBox()
        self._appearance_state_combo.setEditable(True)
        self._appearance_state_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self._appearance_state_combo.setMinimumWidth(120)
        self._appearance_state_combo.setToolTip("GEX state that drives State ON / State OFF appearance")
        self._appearance_state_combo.currentTextChanged.connect(self._on_appearance_state_ui)
        driver_layout.addWidget(self._appearance_state_combo, 1)
        states_row.addWidget(driver_host)

        def _wire_icon_bg_row(
            layout: QtWidgets.QHBoxLayout,
            *,
            preview: _IconPreviewSquare,
            browse_cb,
            clear_icon_cb,
            bg_swatch: _BgColorSquare,
            pick_bg_cb,
            clear_bg_cb,
            icon_tip: str,
        ):
            """Icon preview | Icon… | Clear | BG swatch | Color… | Clear BG"""
            browse = QtWidgets.QPushButton("Icon…")
            browse.setToolTip(icon_tip)
            browse.clicked.connect(browse_cb)
            clear_icon = QtWidgets.QPushButton("Clear")
            clear_icon.setToolTip("Clear icon")
            clear_icon.clicked.connect(clear_icon_cb)
            pick_bg = QtWidgets.QPushButton("Color…")
            pick_bg.setToolTip("Choose background color")
            pick_bg.clicked.connect(pick_bg_cb)
            clear_bg = QtWidgets.QPushButton("Clear BG")
            clear_bg.setToolTip("Clear background color")
            clear_bg.clicked.connect(clear_bg_cb)
            bg_swatch.clicked.connect(pick_bg_cb)
            bg_swatch.clear_requested.connect(clear_bg_cb)
            layout.addWidget(preview)
            layout.addWidget(browse)
            layout.addWidget(clear_icon)
            layout.addWidget(bg_swatch)
            layout.addWidget(pick_bg)
            layout.addWidget(clear_bg)
            layout.addStretch(1)

        def _prep_title_edit(edit: QtWidgets.QPlainTextEdit, placeholder: str, height: int):
            edit.setPlaceholderText(placeholder)
            edit.setTabChangesFocus(True)
            edit.setFixedHeight(height)
            edit.installEventFilter(self)
            pal = edit.palette()
            pal.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor(Color.grayColor()))
            edit.setPalette(pal)

        # --- Released column ---
        released_box = _section_box("Released", kind="released")
        self._released_box = released_box
        released_layout = QtWidgets.QVBoxLayout(released_box)
        released_icon_row = QtWidgets.QHBoxLayout()
        self._icon_preview = _IconPreviewSquare("Released (unpressed) icon — drop image or click to choose")
        self._icon_preview.clicked.connect(self._browse_icon)
        self._icon_preview.icon_dropped.connect(self._on_released_preview_drop)
        self._bg_swatch = _BgColorSquare("Released background color")
        _wire_icon_bg_row(
            released_icon_row,
            preview=self._icon_preview,
            browse_cb=self._browse_icon,
            clear_icon_cb=self._clear_icon,
            bg_swatch=self._bg_swatch,
            pick_bg_cb=lambda: self._pick_bg_color(pressed=False),
            clear_bg_cb=lambda: self._clear_bg_color(pressed=False),
            icon_tip="Choose released icon from library or a custom file",
        )
        released_layout.addLayout(released_icon_row)
        self._released_extras = QtWidgets.QWidget()
        released_extras_layout = QtWidgets.QVBoxLayout(self._released_extras)
        released_extras_layout.setContentsMargins(0, 0, 0, 0)
        released_extras_layout.setSpacing(6)
        released_extras_layout.addWidget(QtWidgets.QLabel("Title"))
        self._title_edit = QtWidgets.QPlainTextEdit()
        fm = self._title_edit.fontMetrics()
        title_h = fm.lineSpacing() * 3 + 16
        _prep_title_edit(self._title_edit, "Released title — up to 3 lines", title_h)
        released_extras_layout.addWidget(self._title_edit)
        self._style_rel = self._build_state_style_block(released_extras_layout, pressed=False)
        released_layout.addWidget(self._released_extras)
        states_row.addWidget(released_box, 1)

        # --- Pressed column ---
        pressed_box = _section_box("Pressed", kind="pressed")
        self._pressed_box = pressed_box
        pressed_layout = QtWidgets.QVBoxLayout(pressed_box)
        pressed_icon_row = QtWidgets.QHBoxLayout()
        self._pressed_preview = _IconPreviewSquare("Pressed icon — drop image or click to choose")
        self._pressed_preview.clicked.connect(self._browse_pressed_icon)
        self._pressed_preview.icon_dropped.connect(self._on_pressed_preview_drop)
        self._bg_swatch_p = _BgColorSquare("Pressed background color")
        _wire_icon_bg_row(
            pressed_icon_row,
            preview=self._pressed_preview,
            browse_cb=self._browse_pressed_icon,
            clear_icon_cb=self._clear_pressed_icon,
            bg_swatch=self._bg_swatch_p,
            pick_bg_cb=lambda: self._pick_bg_color(pressed=True),
            clear_bg_cb=lambda: self._clear_bg_color(pressed=True),
            icon_tip="Choose pressed icon from library or a custom file",
        )
        pressed_layout.addLayout(pressed_icon_row)
        self._pressed_extras = QtWidgets.QWidget()
        pressed_extras_layout = QtWidgets.QVBoxLayout(self._pressed_extras)
        pressed_extras_layout.setContentsMargins(0, 0, 0, 0)
        pressed_extras_layout.setSpacing(6)
        pressed_extras_layout.addWidget(QtWidgets.QLabel("Title"))
        self._title_pressed_edit = QtWidgets.QPlainTextEdit()
        _prep_title_edit(
            self._title_pressed_edit,
            "Pressed title — up to 3 lines (blank = use released)",
            title_h,
        )
        pressed_extras_layout.addWidget(self._title_pressed_edit)
        self._style_prs = self._build_state_style_block(pressed_extras_layout, pressed=True)
        pressed_layout.addWidget(self._pressed_extras)
        states_row.addWidget(pressed_box, 1)

        # Keep path fields for load/save display (hidden from layout clutter).
        self._icon_path_edit = QtWidgets.QLineEdit()
        self._icon_path_edit.hide()
        self._pressed_path_edit = QtWidgets.QLineEdit()
        self._pressed_path_edit.hide()
        # Back-compat aliases used by older helpers
        self._font_family = self._style_rel["font_family"]
        self._font_size = self._style_rel["font_size"]
        self._font_color_btn = self._style_rel["font_color_btn"]
        self._shrink_fit = self._style_rel["shrink_fit"]
        self._text_h = self._style_rel["text_h"]
        self._text_v = self._style_rel["text_v"]
        self._icon_h = self._style_rel["icon_h"]
        self._icon_v = self._style_rel["icon_v"]
        self._bg_color_btn = getattr(self, "_bg_swatch", None)
        self._font_color = "#ffffff"
        self._bg_color = ""
        self._font_color_p = "#ffffff"
        self._bg_color_p = ""
        self._props_host.setStyleSheet("background: transparent;")

        self._link_banner = QtWidgets.QFrame()
        self._link_banner.setObjectName("sdLinkBanner")
        self._link_banner.setStyleSheet(
            """
            QFrame#sdLinkBanner {
                background-color: #1c1a32;
                border: 1px solid #7a6cff;
                border-radius: 8px;
            }
            QLabel { color: #d8d4ff; }
            """
        )
        link_layout = QtWidgets.QVBoxLayout(self._link_banner)
        link_layout.setContentsMargins(12, 10, 12, 10)
        link_layout.setSpacing(8)
        self._link_banner_label = QtWidgets.QLabel()
        self._link_banner_label.setWordWrap(True)
        link_layout.addWidget(self._link_banner_label)
        link_btn_row = QtWidgets.QHBoxLayout()
        self._link_goto_btn = QtWidgets.QPushButton("Go to source page")
        self._link_goto_btn.clicked.connect(self._goto_linked_source_page)
        self._link_unlink_btn = QtWidgets.QPushButton("Unlink")
        self._link_unlink_btn.clicked.connect(self._unlink_selected)
        link_btn_row.addWidget(self._link_goto_btn)
        link_btn_row.addWidget(self._link_unlink_btn)
        link_btn_row.addStretch(1)
        link_layout.addLayout(link_btn_row)
        self._link_banner.hide()
        props.addWidget(self._link_banner)

        self._multi_banner = QtWidgets.QFrame()
        self._multi_banner.setObjectName("sdMultiBanner")
        self._multi_banner.setStyleSheet(
            """
            QFrame#sdMultiBanner {
                background-color: #1a2832;
                border: 1px solid #4da3ff;
                border-radius: 8px;
            }
            QLabel { color: #c5d8e8; }
            """
        )
        multi_layout = QtWidgets.QVBoxLayout(self._multi_banner)
        multi_layout.setContentsMargins(12, 10, 12, 10)
        self._multi_banner_label = QtWidgets.QLabel()
        self._multi_banner_label.setWordWrap(True)
        multi_layout.addWidget(self._multi_banner_label)
        self._multi_banner.hide()
        props.addWidget(self._multi_banner)
        props.addLayout(states_row)

        body_layout.addWidget(self._props_host, 0)
        body_layout.addStretch(1)
        scroll.setWidget(scroll_body)
        scroll.viewport().installEventFilter(self)
        layout.addWidget(scroll, 1)
        return panel

    def _build_state_style_block(self, parent_layout: QtWidgets.QVBoxLayout, *, pressed: bool) -> dict:
        """Style controls for one state column (font, align, background)."""
        hdr = QtWidgets.QLabel("Style")
        hf = hdr.font()
        hf.setBold(True)
        hf.setPointSize(max(11, hf.pointSize() + 1))
        hdr.setFont(hf)
        hdr.setAlignment(QtCore.Qt.AlignHCenter)
        parent_layout.addWidget(hdr)

        font_row = QtWidgets.QHBoxLayout()
        font_family = QtWidgets.QFontComboBox()
        font_family.currentFontChanged.connect(lambda *_: self._apply_style_fields())
        font_size = QtWidgets.QSpinBox()
        font_size.setRange(8, 72)
        font_size.setValue(18)
        font_size.valueChanged.connect(lambda *_: self._apply_style_fields())
        font_color_btn = QtWidgets.QPushButton("Color")
        font_color_btn.clicked.connect(
            lambda: self._pick_font_color(pressed=pressed)
        )
        shrink_fit = QtWidgets.QCheckBox("Shrink to fit")
        shrink_fit.setChecked(True)
        shrink_fit.toggled.connect(lambda *_: self._apply_style_fields())
        font_row.addWidget(font_family, 1)
        font_row.addWidget(font_size)
        font_row.addWidget(font_color_btn)
        font_row.addWidget(shrink_fit)
        parent_layout.addLayout(font_row)

        align_row = QtWidgets.QHBoxLayout()
        text_h = QtWidgets.QComboBox()
        text_h.addItem("Text ←", "left")
        text_h.addItem("Text ↔", "center")
        text_h.addItem("Text →", "right")
        text_h.setCurrentIndex(1)
        text_h.currentIndexChanged.connect(lambda *_: self._apply_style_fields())
        text_v = QtWidgets.QComboBox()
        text_v.addItem("Text ↑", "top")
        text_v.addItem("Text ↕", "middle")
        text_v.addItem("Text ↓", "bottom")
        text_v.setCurrentIndex(2)
        text_v.currentIndexChanged.connect(lambda *_: self._apply_style_fields())
        icon_h = QtWidgets.QComboBox()
        icon_h.addItem("Icon ←", "left")
        icon_h.addItem("Icon ↔", "center")
        icon_h.addItem("Icon →", "right")
        icon_h.setCurrentIndex(1)
        icon_h.currentIndexChanged.connect(lambda *_: self._apply_style_fields())
        icon_v = QtWidgets.QComboBox()
        icon_v.addItem("Icon ↑", "top")
        icon_v.addItem("Icon ↕", "middle")
        icon_v.addItem("Icon ↓", "bottom")
        icon_v.setCurrentIndex(1)
        icon_v.currentIndexChanged.connect(lambda *_: self._apply_style_fields())
        align_row.addWidget(text_h)
        align_row.addWidget(text_v)
        align_row.addWidget(icon_h)
        align_row.addWidget(icon_v)
        parent_layout.addLayout(align_row)

        return {
            "font_family": font_family,
            "font_size": font_size,
            "font_color_btn": font_color_btn,
            "shrink_fit": shrink_fit,
            "text_h": text_h,
            "text_v": text_v,
            "icon_h": icon_h,
            "icon_v": icon_v,
        }

    def _set_icon_preview(self, label: QtWidgets.QLabel, path: str = "", data_url: str = ""):
        if label is None or not Shiboken.isValid(label):
            return
        pm = _pixmap_from_source(path, data_url)
        if pm.isNull():
            label.setPixmap(QtGui.QPixmap())
            label.setText("—")
            return
        side = min(label.width(), label.height()) - 6
        scaled = pm.scaled(side, side, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        label.setText("")
        label.setPixmap(scaled)

    def showEvent(self, event):
        super().showEvent(event)
        # Tab re-entry: rebuild/refresh so keys are not blank until manual Refresh.
        QtCore.QTimer.singleShot(0, self._on_shown)

    def _on_shown(self):
        if not Shiboken.isValid(self):
            return
        if not self._cells:
            self.refresh()
        else:
            self._refresh_cell_contents()
            self._schedule_square_resize()

    def refresh(self):
        if not Shiboken.isValid(self) or self._runtime_locked():
            return
        bridge = self._bridge()
        self._device_id = getattr(self._tab, "_elgato_device_id", "") or bridge.device_id_for_guid(self._tab.device_guid)
        if Shiboken.isValid(self._status):
            self._status.setText(bridge.status_text())
        self._rebuild_pages()
        self._rebuild_grid()

    def _rebuild_pages(self):
        if not Shiboken.isValid(self) or not Shiboken.isValid(self._page_list):
            return
        bridge = self._bridge()
        # Load names once if this deck has none yet (do not re-emit every refresh —
        # that used to schedule infinite rebuilds and blank the grid).
        try:
            if self._device_id and not (bridge._page_names.get(self._device_id) or {}):
                bridge._load_page_metadata(emit=False)
                # Sidecar may key names under a prior Elgato id — bind to this deck.
                bridge._adopt_orphan_page_metadata(
                    [self._device_id] if self._device_id else None
                )
        except Exception:
            pass
        pages = bridge.list_pages(self._device_id) if self._device_id else [1]
        active = bridge.get_active_page(self._device_id) if self._device_id else 1
        if self._edit_page not in pages:
            self._edit_page = active if active in pages else pages[0]

        self._page_list.blockSignals(True)
        self._page_list.clear()
        select_row = 0
        for i, page in enumerate(pages):
            name = bridge.page_name(self._device_id, page)
            # Keep bank number visible when a custom name is set.
            if name and name != f"Page {page}" and not name.startswith(f"{page}."):
                label = f"{page}. {name}"
            else:
                label = name or f"Page {page}"
            marker = " ▶" if page == active else ""
            item = QtWidgets.QListWidgetItem(f"{label}{marker}")
            item.setData(QtCore.Qt.UserRole, page)
            self._page_list.addItem(item)
            if page == self._edit_page:
                select_row = i
        self._page_list.setCurrentRow(select_row)
        self._page_list.blockSignals(False)
        if Shiboken.isValid(self._grid_title):
            self._grid_title.setText(f"Page {self._edit_page} — {bridge.page_name(self._device_id, self._edit_page)}")

    def _rebuild_grid(self):
        if not Shiboken.isValid(self):
            return
        self._rebuilding = True
        try:
            bridge = self._bridge()
            info = bridge.devices.get(self._device_id, {}) if self._device_id else {}
            from gremlin.ui.streamdeck_device import (
                device_grid_size,
                friendly_streamdeck_name,
                is_streamdeck_designer_supported,
                parse_streamdeck_device_type,
            )

            self._clear_cells()
            self._set_appearance_mode("hidden")

            dtype = parse_streamdeck_device_type(info.get("type"))
            # If the plugin hasn't reported a type yet, infer from profile inputs
            # (Companion import / XL is 8×4) instead of blanking the designer.
            if not is_streamdeck_designer_supported(dtype):
                inferred = None
                try:
                    max_c = max_r = -1
                    for item in bridge._iter_device_inputs(self._device_id or ""):
                        if getattr(item, "kind", "button") not in ("button", None, ""):
                            continue
                        if item._column is not None:
                            max_c = max(max_c, int(item._column))
                        if item._row is not None:
                            max_r = max(max_r, int(item._row))
                    if max_c >= 7 and max_r >= 3:
                        inferred = 2  # XL
                    elif max_c >= 4 and max_r >= 2:
                        inferred = 0  # standard 5×3
                    elif max_c >= 0 and max_r >= 0:
                        inferred = 0
                except Exception:
                    inferred = None
                if inferred is not None:
                    dtype = inferred
                else:
                    self._grid_cols = 0
                    self._grid_rows = 0
                    label = friendly_streamdeck_name(
                        info.get("name"), info.get("type"), self._device_id or ""
                    )
                    type_txt = str(dtype) if dtype is not None else "unknown"
                    msg = QtWidgets.QLabel(
                        f"<b>{label}</b> is connected, but this device type "
                        f"(Elgato DeviceType {type_txt}) is not supported by the "
                        f"Joystick Gremlin Ex Stream Deck designer yet.<br><br>"
                        f"No key grid is shown (a default 5×3 layout would be wrong).<br><br>"
                        f"Please contact the developer to request support for this device."
                    )
                    msg.setWordWrap(True)
                    msg.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
                    msg.setTextFormat(QtCore.Qt.RichText)
                    msg.setMinimumWidth(420)
                    msg.setStyleSheet(f"color: {Color.normalColor()}; padding: 12px;")
                    self._grid_layout.addWidget(msg, 0, 0, 1, 1, QtCore.Qt.AlignTop)
                    if Shiboken.isValid(self._grid_title):
                        self._grid_title.setText("Unsupported device")
                    return

            cols, rows = device_grid_size(dtype)
            if not cols or not rows:
                return
            self._grid_cols = cols
            self._grid_rows = rows
            side = self._compute_cell_side(cols)

            for r in range(rows):
                for c in range(cols):
                    btn = StreamDeckKeyButton(r, c, kind="button", side=side)
                    btn.clicked.connect(
                        lambda checked=False, row=r, col=c: self._on_cell_clicked(row, col, "button")
                    )
                    btn.icon_dropped.connect(
                        lambda path, row=r, col=c: self._on_icon_dropped(row, col, "button", path)
                    )
                    btn.slot_moved.connect(self._on_slot_moved)
                    btn.context_action.connect(
                        lambda action, row=r, col=c: self._on_context_action(action, row, col, "button")
                    )
                    self._grid_layout.addWidget(btn, r, c, QtCore.Qt.AlignCenter)
                    self._cells[("button", r, c)] = btn

            # Stream Deck + dials sit below the key grid (4 encoders).
            if dtype in (7, 8):
                screen_w = max(72, int(side * 1.85))
                for i in range(4):
                    screen = StreamDeckDialScreenWidget(i, width=screen_w)
                    screen.clicked.connect(
                        lambda col=i: self._on_cell_clicked(0, col, "dial_screen")
                    )
                    screen.icon_dropped.connect(
                        lambda path, col=i: self._on_icon_dropped(0, col, "dial_screen", path)
                    )
                    self._grid_layout.addWidget(screen, rows, i, QtCore.Qt.AlignCenter)
                    self._dial_screens[i] = screen
                for i in range(4):
                    dial = StreamDeckDialWidget(i, side=side)
                    dial.press_clicked.connect(
                        lambda col=i: self._on_cell_clicked(0, col, "dial_press")
                    )
                    dial.inc_clicked.connect(
                        lambda col=i: self._on_cell_clicked(0, col, "dial_inc")
                    )
                    dial.dec_clicked.connect(
                        lambda col=i: self._on_cell_clicked(0, col, "dial_dec")
                    )
                    dial.context_action.connect(
                        lambda action, col=i: self._on_context_action(action, 0, col, "dial_press")
                    )
                    self._grid_layout.addWidget(dial, rows + 1, i, QtCore.Qt.AlignCenter)
                    self._dial_cells[i] = dial

            self._refresh_cell_contents()
            self._restore_selection_highlight()
        finally:
            self._rebuilding = False
            # Must refresh AFTER clearing _rebuilding — _refresh_cell_contents
            # no-ops while rebuild is in progress (that left blank keys on page/tab switch).
            if self._cells or self._dial_cells:
                self._refresh_cell_contents()
                self._schedule_square_resize()
                QtCore.QTimer.singleShot(0, self._refresh_cell_contents)

    def _compute_cell_side(self, cols: int | None = None) -> int:
        cols = cols or self._grid_cols or 5
        spacing = self._grid_layout.spacing() if self._grid_layout is not None else 8
        margins = 16
        avail = 640
        if self._scroll is not None and Shiboken.isValid(self._scroll):
            vp = self._scroll.viewport()
            if vp is not None and Shiboken.isValid(vp):
                avail = max(200, vp.width() - margins)
        # Fit columns as equal squares; clamp to a readable Stream Deck-like size.
        side = (avail - spacing * max(0, cols - 1)) // max(1, cols)
        return max(56, min(112, int(side)))

    def _schedule_square_resize(self):
        if not Shiboken.isValid(self) or self._rebuilding:
            return
        if self._size_pending:
            return
        self._size_pending = True
        QtCore.QTimer.singleShot(0, self._apply_square_cell_sizes)

    def _apply_square_cell_sizes(self):
        self._size_pending = False
        if not Shiboken.isValid(self) or self._rebuilding:
            return
        side = self._compute_cell_side()
        if side == self._cell_side and self._cells:
            # Still refresh in case first layout pass had width 0.
            pass
        self._cell_side = side
        for btn in list(self._cells.values()):
            if Shiboken.isValid(btn):
                btn.set_side(side)
        for dial in list(self._dial_cells.values()):
            if Shiboken.isValid(dial):
                dial.set_side(max(48, side - 4))
        screen_w = max(72, int(max(48, side - 4) * 1.85))
        for screen in list(getattr(self, "_dial_screens", {}).values()):
            if Shiboken.isValid(screen):
                screen.set_width(screen_w)

    def eventFilter(self, obj, event):
        if (
            self._scroll is not None
            and obj is self._scroll.viewport()
            and event.type() == QtCore.QEvent.Type.Resize
        ):
            self._schedule_square_resize()
        elif event.type() == QtCore.QEvent.Type.FocusOut and obj in (
            getattr(self, "_title_edit", None),
            getattr(self, "_title_pressed_edit", None),
        ):
            self._apply_style_fields()
        return super().eventFilter(obj, event)

    def _inputs_on_edit_page(self):
        from gremlin.ui.streamdeck_device import StreamDeckInputItem
        from gremlin.input_types import InputType

        result = []
        try:
            mode = self._tab.profile.getDeviceNode(self._tab.device_guid, autocreate=False)
            mode = mode.getModeNode(gremlin.shared_state.edit_mode, autocreate=False) if mode else None
            config = mode.getConfig(InputType.StreamDeck) if mode else {}
            for item in (config or {}).values():
                if isinstance(item, StreamDeckInputItem) and item.page == self._edit_page:
                    # Pages/keys are per Elgato device id — never mix another deck's slots.
                    if self._device_id and (item.device_id or "") == self._device_id:
                        result.append(item)
                    elif not self._device_id and not (item.device_id or ""):
                        result.append(item)
        except Exception:
            pass
        return result

    def _on_preview_state_changed(self, button_id: int):
        self._preview_pressed = button_id == 1
        self._refresh_cell_contents()

    def _restore_selection_highlight(self):
        kind = self._selected_kind or "button"
        dial_kinds = ("dial_press", "dial_screen", "dial_inc", "dial_dec")
        multi = {
            k
            for k in getattr(self, "_multi_selection", set()) or set()
            if isinstance(k, tuple) and len(k) == 3
        }
        if kind in dial_kinds:
            for col, dial in list(self._dial_cells.items()):
                if not Shiboken.isValid(dial):
                    continue
                if col == self._selected_col:
                    part = {
                        "dial_press": "press",
                        "dial_screen": "",  # screen has its own highlight
                        "dial_inc": "inc",
                        "dial_dec": "dec",
                    }.get(kind, "")
                    dial.set_selection(part)
                else:
                    dial.set_selection("")
            for col, screen in list(getattr(self, "_dial_screens", {}).items()):
                if Shiboken.isValid(screen):
                    # Highlight LCD when editing appearance (screen) or press maps.
                    screen.set_selected(
                        col == self._selected_col and kind == "dial_screen"
                    )
            for btn in list(self._cells.values()):
                if Shiboken.isValid(btn):
                    btn.setChecked(False)
            return
        for dial in list(self._dial_cells.values()):
            if Shiboken.isValid(dial):
                dial.set_selection("")
        for screen in list(getattr(self, "_dial_screens", {}).values()):
            if Shiboken.isValid(screen):
                screen.set_selected(False)
        primary = (kind, self._selected_row, self._selected_col)
        if primary[1] is not None and primary[2] is not None and not multi:
            multi = {primary}
        for k, btn in list(self._cells.items()):
            if Shiboken.isValid(btn):
                btn.setChecked(k in multi or k == primary)

    def _set_appearance_visible(self, visible: bool):
        """Back-compat: show/hide both Released+Pressed (button mode)."""
        self._set_appearance_mode("button" if visible else "hidden")

    def _set_appearance_mode(self, mode: str):
        """Appearance editors under the deck.

        - ``hidden``: nothing (dial rotate / dial press mappings)
        - ``button``: Released + Pressed columns (or State OFF / ON)
        - ``lcd``: single LCD column only (touch strip is not pressable)
        - ``look``: icon + background only (other-plugin hardware keys)
        - ``linked``: read-only banner pointing at the source page
        - ``multi``: Ctrl+click multi-select banner (right-click actions apply to all)
        """
        host = getattr(self, "_props_host", None)
        if host is None or not Shiboken.isValid(host):
            return
        mode = (mode or "hidden").lower()
        if mode not in ("hidden", "button", "lcd", "look", "linked", "multi"):
            mode = "hidden"
        host.setVisible(mode != "hidden")
        link_banner = getattr(self, "_link_banner", None)
        if link_banner is not None and Shiboken.isValid(link_banner):
            link_banner.setVisible(mode == "linked")
        multi_banner = getattr(self, "_multi_banner", None)
        if multi_banner is not None and Shiboken.isValid(multi_banner):
            multi_banner.setVisible(mode == "multi")
        driver = getattr(self, "_appearance_driver_host", None)
        if driver is not None and Shiboken.isValid(driver):
            driver.setVisible(mode == "button")
        released = getattr(self, "_released_box", None)
        pressed = getattr(self, "_pressed_box", None)
        if released is not None and Shiboken.isValid(released):
            released.setVisible(mode in ("button", "lcd", "look"))
        if pressed is not None and Shiboken.isValid(pressed):
            pressed.setVisible(mode == "button")
        extras = getattr(self, "_released_extras", None)
        if extras is not None and Shiboken.isValid(extras):
            extras.setVisible(mode != "look")
        pressed_extras = getattr(self, "_pressed_extras", None)
        if pressed_extras is not None and Shiboken.isValid(pressed_extras):
            pressed_extras.setVisible(mode == "button")
        preview_pressed = getattr(self, "_preview_pressed_btn", None)
        if preview_pressed is not None and Shiboken.isValid(preview_pressed):
            preview_pressed.setVisible(mode not in ("look", "linked", "multi", "lcd"))
        if mode == "look" and getattr(self, "_preview_pressed", False):
            self._preview_pressed = False
            preview_released = getattr(self, "_preview_released_btn", None)
            if preview_released is not None and Shiboken.isValid(preview_released):
                preview_released.setChecked(True)
        self._refresh_appearance_driver_labels(panel_mode=mode)

    def _dial_base_id(self, button_id: str) -> int | None:
        """Parse dial column from '3', '3:inc', or '3:dec'."""
        bid = str(button_id or "").strip()
        if not bid:
            return None
        base = bid.split(":", 1)[0]
        if base.isdigit():
            return int(base)
        return None

    def _item_has_mappings(self, item) -> bool:
        if item is None:
            return False
        try:
            if hasattr(item, "hasActions"):
                return bool(item.hasActions)
            return bool(item.containers)
        except Exception:
            return bool(getattr(item, "containers", None))

    def _item_has_local_content(self, item) -> bool:
        """True when the slot has its own style/mappings (not counting a page link)."""
        if item is None:
            return False
        if self._item_has_mappings(item):
            return True
        fields = (
            "title",
            "text_line2",
            "text_line3",
            "title_pressed",
            "text_line2_pressed",
            "text_line3_pressed",
            "image",
            "image_path",
            "image_expr",
            "image_pressed",
            "image_pressed_path",
            "bg_color",
            "bg_color_pressed",
        )
        for name in fields:
            if str(getattr(item, name, "") or "").strip():
                return True
        return False

    def _link_page_choices(self) -> list[tuple[int, str]]:
        bridge = self._bridge()
        pages = bridge.list_pages(self._device_id) if self._device_id else [1]
        out = []
        for page in pages:
            name = bridge.page_name(self._device_id, page) if self._device_id else f"Page {page}"
            if name == f"Page {page}":
                label = f"Page {page}"
            else:
                label = f"Page {page} — {name}"
            out.append((page, label))
        return out

    def _show_linked_selection(self, item):
        """Lock appearance/mappings UI and explain where to edit."""
        page = int(getattr(item, "linked_page", 0) or 0)
        bridge = self._bridge()
        name = bridge.page_name(self._device_id, page) if self._device_id and page else f"Page {page}"
        if name == f"Page {page}":
            name_bit = f"page {page}"
        else:
            name_bit = f"page {page} ({name})"
        self._set_appearance_mode("linked")
        label = getattr(self, "_link_banner_label", None)
        if label is not None and Shiboken.isValid(label):
            label.setText(
                f"This key is linked to {name_bit}.\n"
                f"It shows and runs the same button at this position on that page.\n"
                f"Edit icon, style, and mappings on {name_bit}."
            )
        self.mapping_enabled_changed.emit(False)
        self.selection_changed.emit(None)

    def _show_multi_selection_ui(self):
        """Inspector for Ctrl+click multi-select (actions via right-click)."""
        keys = self._button_selection_keys()
        n = len(keys)
        linked = 0
        for item in self._items_for_keys(keys, create=False):
            if getattr(item, "is_linked", False):
                linked += 1
        self._set_appearance_mode("multi")
        label = getattr(self, "_multi_banner_label", None)
        if label is not None and Shiboken.isValid(label):
            extra = f" ({linked} linked)" if linked else ""
            label.setText(
                f"{n} keys selected{extra}.\n"
                "Ctrl+click to add or remove keys. Right-click for Link to page, "
                "Unlink, Delete, or Paste on the whole selection."
            )
        self.mapping_enabled_changed.emit(False)
        self.selection_changed.emit(None)

    def _button_selection_keys(self) -> list[tuple[str, int, int]]:
        """Ordered button slots in the current multi-selection (falls back to primary)."""
        multi = [
            k
            for k in getattr(self, "_multi_selection", set()) or set()
            if isinstance(k, tuple) and len(k) == 3 and k[0] == "button"
        ]
        if multi:
            multi.sort(key=lambda t: (t[1], t[2]))
            return multi
        if (self._selected_kind or "button") == "button" and self._selected_row is not None and self._selected_col is not None:
            return [("button", int(self._selected_row), int(self._selected_col))]
        return []

    def _items_for_keys(self, keys: list[tuple[str, int, int]], *, create: bool = True) -> list:
        bridge = self._bridge()
        out = []
        for kind, row, col in keys:
            if kind != "button":
                continue
            if create:
                item = bridge.ensure_slot_input(
                    self._device_id,
                    self._edit_page,
                    kind="button",
                    row=row,
                    column=col,
                    button_id="",
                    title="",
                )
            else:
                item = bridge.find_input_for_slot(
                    self._device_id,
                    self._edit_page,
                    {
                        "kind": "button",
                        "row": row,
                        "column": col,
                        "button_id": f"{row}:{col}",
                        "slot_key": f"r{row}c{col}",
                    },
                )
            if item is not None:
                out.append(item)
        return out

    def _clear_multi_selection(self):
        self._multi_selection = set()

    def _sync_primary_from_multi(self):
        keys = self._button_selection_keys()
        if not keys:
            return
        # Prefer keeping current primary if still selected.
        primary = ("button", self._selected_row, self._selected_col)
        if primary not in keys:
            kind, row, col = keys[0]
            self._selected_kind = kind
            self._selected_row = row
            self._selected_col = col

    def _goto_linked_source_page(self):
        item = self._selected_item()
        page = int(getattr(item, "linked_page", 0) or 0) if item is not None else 0
        if page <= 0:
            return
        # Select that page in the list so the designer switches banks.
        for i in range(self._page_list.count()):
            list_item = self._page_list.item(i)
            if list_item is not None and int(list_item.data(QtCore.Qt.UserRole) or 0) == page:
                self._page_list.setCurrentRow(i)
                break

    def _unlink_selected(self):
        keys = self._button_selection_keys()
        items = self._items_for_keys(keys, create=False)
        linked = [i for i in items if getattr(i, "is_linked", False)]
        if not linked:
            return
        for item in linked:
            item.linked_page = 0
        self._sync_primary_from_multi()
        if len(keys) > 1:
            self._show_multi_selection_ui()
        else:
            self._on_cell_clicked(
                self._selected_row, self._selected_col, self._selected_kind or "button"
            )
        self._refresh_cell_contents()
        bridge = self._bridge()
        if bridge.get_active_page(self._device_id) == self._edit_page:
            bridge.paint_active_page(self._device_id)
        self.pages_changed.emit()

    def _strip_local_button_content(self, item):
        """Remove local style and mappings so a page link is the only content."""
        if item is None:
            return
        try:
            while item.containers and len(item.containers):
                item.containers.removeAt(0)
        except Exception:
            try:
                item.containers.clear()
            except Exception:
                pass
        item.apply_style_snapshot(
            {
                "title": "",
                "text_line2": "",
                "text_line3": "",
                "title_pressed": "",
                "text_line2_pressed": "",
                "text_line3_pressed": "",
                "image": "",
                "image_path": "",
                "image_expr": "",
                "image_pressed": "",
                "image_pressed_path": "",
                "font_family": "Segoe UI",
                "font_size": 18,
                "font_color": "#ffffff",
                "text_h_align": "center",
                "text_v_align": "bottom",
                "shrink_to_fit": True,
                "icon_h_align": "center",
                "icon_v_align": "middle",
                "bg_color": "",
                "font_family_pressed": "Segoe UI",
                "font_size_pressed": 18,
                "font_color_pressed": "#ffffff",
                "text_h_align_pressed": "center",
                "text_v_align_pressed": "bottom",
                "shrink_to_fit_pressed": True,
                "icon_h_align_pressed": "center",
                "icon_v_align_pressed": "middle",
                "bg_color_pressed": "",
                "appearance_mode": "press",
                "appearance_state": "",
                "step_mode": "all",
                "step_wrap": True,
                "linked_page": 0,
            }
        )
        item.step_index = 0

    def _link_selected_to_page(self, target_page: int):
        target_page = int(target_page or 0)
        if target_page <= 0 or target_page == self._edit_page:
            return
        keys = self._button_selection_keys()
        if not keys:
            return
        items = self._items_for_keys(keys, create=True)
        if not items:
            return
        to_change = [
            i
            for i in items
            if getattr(i, "linked_page", 0) != target_page or self._item_has_local_content(i)
        ]
        if not to_change:
            return
        if any(self._item_has_local_content(i) for i in to_change):
            n = len(to_change)
            reply = QtWidgets.QMessageBox.warning(
                self,
                "Link to page",
                (
                    f"{n} selected button(s) already have an icon, style, and/or mappings.\n\n"
                    f"Linking to page {target_page} will erase that content and "
                    f"mirror the same key on page {target_page} instead.\n\n"
                    f"Continue?"
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        for item in to_change:
            self._strip_local_button_content(item)
            item.linked_page = target_page
        self._sync_primary_from_multi()
        if len(keys) > 1:
            self._show_multi_selection_ui()
        else:
            self._show_linked_selection(items[0])
        self._refresh_cell_contents()
        bridge = self._bridge()
        if bridge.get_active_page(self._device_id) == self._edit_page:
            bridge.paint_active_page(self._device_id)
        self.pages_changed.emit()

    def _refresh_cell_contents(self):
        if not Shiboken.isValid(self) or self._rebuilding or self._runtime_locked():
            return
        from gremlin.ui.streamdeck_surface import text_lines_for_item

        preview_pressed = bool(getattr(self, "_preview_pressed", False))
        bridge = self._bridge()
        link_choices = self._link_page_choices()
        by_coord = {}
        by_dial_press = {}
        by_dial_inc = {}
        by_dial_dec = {}
        for item in self._inputs_on_edit_page():
            kind = getattr(item, "kind", "button") or "button"
            if kind == "button" and item._row is not None and item._column is not None:
                try:
                    by_coord[(int(item._row), int(item._column))] = item
                except (TypeError, ValueError):
                    pass
            elif kind == "dial_press":
                col = None
                try:
                    col = int(item._column) if item._column is not None else None
                except (TypeError, ValueError):
                    col = None
                if col is None:
                    col = self._dial_base_id(item.button_id)
                if col is not None:
                    by_dial_press[col] = item
            elif kind == "dial":
                col = self._dial_base_id(item.button_id)
                if col is None:
                    continue
                bid = str(item.button_id or "")
                if bid.endswith(":inc"):
                    by_dial_inc[col] = item
                elif bid.endswith(":dec"):
                    by_dial_dec[col] = item
        stale = []
        for key, btn in list(self._cells.items()):
            if not Shiboken.isValid(btn):
                stale.append(key)
                continue
            kind, r, c = key
            item = by_coord.get((r, c)) if kind == "button" else None
            foreign = self._slot_is_foreign(r, c, kind)
            if hasattr(btn, "set_link_pages"):
                in_multi = ("button", r, c) in (getattr(self, "_multi_selection", set()) or set())
                multi_n = len(self._button_selection_keys()) if in_multi else 1
                btn.set_link_pages(link_choices, self._edit_page, multi_count=multi_n)
            if item is None:
                btn.set_cell("", False, foreign=foreign, linked_page=0)
            else:
                linked_page = int(getattr(item, "linked_page", 0) or 0)
                display = item
                if linked_page:
                    display = bridge.resolve_linked_source(item)
                # Foreign keys never show a mapping badge; preview stays released.
                use_pressed = preview_pressed and not foreign and not linked_page
                if linked_page and display is not None:
                    use_pressed = preview_pressed and not foreign
                has = (
                    (not linked_page)
                    and self._item_has_mappings(item)
                    and not foreign
                )
                if linked_page and display is not None:
                    has = self._item_has_mappings(display) and not foreign
                pm = (
                    _pixmap_from_item(display, pressed=use_pressed)
                    if display is not None
                    else QtGui.QPixmap()
                )
                lines = text_lines_for_item(display, pressed=use_pressed) if display is not None else []
                label = (lines[0] if lines else "").strip()
                if not label and pm.isNull():
                    label = ""
                # Mapping green is suppressed for linked keys; badge shows ↗P#
                btn.set_cell(
                    label,
                    has if not linked_page else False,
                    pm,
                    foreign=foreign,
                    linked_page=linked_page,
                )
        for key in stale:
            self._cells.pop(key, None)

        for col, dial in list(self._dial_cells.items()):
            if not Shiboken.isValid(dial):
                continue
            item = by_dial_press.get(col)
            has_inc = self._item_has_mappings(by_dial_inc.get(col))
            has_dec = self._item_has_mappings(by_dial_dec.get(col))
            foreign = self._slot_is_foreign(0, col, "dial_press")
            if foreign:
                dial.set_cell("", False, has_inc=False, has_dec=False, foreign=True)
            elif item is None:
                dial.set_cell("", False, has_inc=has_inc, has_dec=has_dec)
            else:
                dial.set_cell(
                    "",
                    self._item_has_mappings(item),
                    has_inc=has_inc,
                    has_dec=has_dec,
                )
            screen = getattr(self, "_dial_screens", {}).get(col)
            if screen is not None and Shiboken.isValid(screen):
                if item is None:
                    screen.set_content("", None, "")
                else:
                    # LCD is not a button — always show the idle (released) look.
                    pm = _pixmap_from_item(item, pressed=False, dial_lcd=True)
                    bg = ""
                    try:
                        bg = getattr(item, "bg_color", "") or ""
                    except Exception:
                        bg = ""
                    screen.set_content("", pm, bg)
        self._restore_selection_highlight()

    def _slot_is_foreign(self, row, col, kind: str = "button") -> bool:
        """True when the plugin is live and this physical slot is not a JG Ex action."""
        if row is None or col is None:
            return False
        bridge = self._bridge()
        if not bridge.viewport_known(self._device_id):
            return False
        kind = kind or "button"
        try:
            row_i, col_i = int(row), int(col)
        except (TypeError, ValueError):
            return False
        if kind == "button":
            return (row_i, col_i) not in bridge.live_button_coords(self._device_id)
        if kind in ("dial", "dial_press", "dial_inc", "dial_dec", "dial_screen"):
            return col_i not in bridge.live_dial_columns(self._device_id)
        return False

    def _on_cell_clicked(self, row: int, col: int, kind: str = "button"):
        if not Shiboken.isValid(self) or self._runtime_locked():
            return
        kind = kind or "button"
        look_only = self._slot_is_foreign(row, col, kind)
        # Other-plugin dials: no press/rotate mappings. LCD / key look is allowed.
        if look_only and kind in ("dial_inc", "dial_dec", "dial_press"):
            return

        key = (kind, row, col)
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        ctrl = bool(modifiers & QtCore.Qt.KeyboardModifier.ControlModifier)

        # Ctrl+click multi-select (JG Ex buttons only).
        if ctrl and kind == "button" and not look_only:
            multi = set(getattr(self, "_multi_selection", set()) or set())
            # Seed with previous primary button if starting a multi-select.
            if not multi and (self._selected_kind or "button") == "button":
                if self._selected_row is not None and self._selected_col is not None:
                    multi.add(("button", int(self._selected_row), int(self._selected_col)))
            if key in multi and len(multi) > 1:
                multi.discard(key)
            else:
                multi.add(key)
            self._multi_selection = {k for k in multi if k[0] == "button"}
            if key in self._multi_selection:
                self._selected_row = row
                self._selected_col = col
                self._selected_kind = kind
            self._sync_primary_from_multi()
            self._restore_selection_highlight()
            if len(self._multi_selection) > 1:
                self._show_multi_selection_ui()
                self._refresh_cell_contents()
                return
            # One key left after toggle — load it as a normal single selection.
            row = int(self._selected_row)
            col = int(self._selected_col)
            kind = "button"
            key = (kind, row, col)
            look_only = self._slot_is_foreign(row, col, kind)

        if kind == "button" and not look_only:
            self._multi_selection = {key}
        else:
            self._clear_multi_selection()

        self._selected_row = row
        self._selected_col = col
        self._selected_kind = kind
        self._restore_selection_highlight()

        bridge = self._bridge()
        # Rotate arrows: mapping only (no appearance). Circle: press + appearance.
        if kind == "dial_inc":
            self._set_appearance_mode("hidden")
            item = bridge.ensure_slot_input(
                self._device_id,
                self._edit_page,
                kind="dial",
                row=None,
                column=None,
                button_id=f"{col}:inc",
                title="",
            )
        elif kind == "dial_dec":
            self._set_appearance_mode("hidden")
            item = bridge.ensure_slot_input(
                self._device_id,
                self._edit_page,
                kind="dial",
                row=None,
                column=None,
                button_id=f"{col}:dec",
                title="",
            )
        elif kind == "dial_screen":
            # LCD strip: single appearance editor (not pressable — no Released/Pressed).
            self._set_appearance_mode("look" if look_only else "lcd")
            item = bridge.ensure_slot_input(
                self._device_id,
                self._edit_page,
                kind="dial_press",
                row=0,
                column=col,
                button_id=str(col),
                title="",
            )
        elif kind == "dial_press":
            # Knob press: mappings only (edit look on the LCD above).
            self._set_appearance_mode("hidden")
            item = bridge.ensure_slot_input(
                self._device_id,
                self._edit_page,
                kind="dial_press",
                row=0,
                column=col,
                button_id=str(col),
                title="",
            )
        else:
            self._set_appearance_mode("look" if look_only else "button")
            item = bridge.ensure_slot_input(
                self._device_id,
                self._edit_page,
                kind="button",
                row=row,
                column=col,
                button_id="",
                title="",
            )

        if item is not None:
            if kind == "button" and getattr(item, "is_linked", False) and not look_only:
                self._show_linked_selection(item)
                self._refresh_cell_contents()
                self.pages_changed.emit()
                return
            # LCD + buttons: show appearance editors (look-only = icon/bg).
            if kind in ("dial_screen", "button"):
                self._load_appearance_fields(item)
            # LCD and other-plugin keys: no right-pane containers/actions.
            show_mappings = kind != "dial_screen" and not look_only
            self.mapping_enabled_changed.emit(show_mappings)
            if show_mappings:
                self.selection_changed.emit(item)
            else:
                self.selection_changed.emit(None)
            self._refresh_cell_contents()
            self.pages_changed.emit()
        else:
            self.mapping_enabled_changed.emit(False)
            self.selection_changed.emit(None)

    def _on_page_row_changed(self, row: int):
        if row < 0 or not Shiboken.isValid(self) or self._runtime_locked():
            return
        item = self._page_list.item(row)
        if item is None:
            return
        page = item.data(QtCore.Qt.UserRole)
        if page is None:
            return
        self._edit_page = int(page)
        self._selected_row = None
        self._selected_col = None
        self._selected_kind = "button"
        self._clear_multi_selection()
        self._set_appearance_mode("hidden")
        if Shiboken.isValid(self._title_edit):
            self._title_edit.setPlainText("")
        if getattr(self, "_title_pressed_edit", None) is not None and Shiboken.isValid(self._title_pressed_edit):
            self._title_pressed_edit.setPlainText("")
        if Shiboken.isValid(self._icon_path_edit):
            self._icon_path_edit.setText("")
        if Shiboken.isValid(self._pressed_path_edit):
            self._pressed_path_edit.setText("")
        self._set_icon_preview(getattr(self, "_icon_preview", None))
        self._set_icon_preview(getattr(self, "_pressed_preview", None))
        # Clear right-pane mappings for the previous page's selection.
        self.selection_changed.emit(None)
        # Selecting a page in JG Ex also activates that bank on the hardware.
        if self._device_id:
            self._bridge().set_virtual_page(self._device_id, self._edit_page)
        self._rebuild_pages()
        self._rebuild_grid()

    def _gex_state_names(self) -> list[str]:
        try:
            import gremlin.ui.state_device as state_device

            names = [str(n) for n in (state_device.StateData().getStateNames() or []) if str(n).strip()]
            names.sort(key=lambda s: s.casefold())
            return names
        except Exception:
            return []

    def _current_appearance_driver(self) -> str:
        combo = getattr(self, "_appearance_mode_combo", None)
        if combo is not None and Shiboken.isValid(combo):
            data = combo.currentData()
            if data:
                return "state" if str(data).casefold() == "state" else "press"
        item = self._selected_item()
        if item is not None:
            mode = str(getattr(item, "appearance_mode", "press") or "press").casefold()
            return "state" if mode == "state" else "press"
        return "press"

    def _refresh_appearance_driver_labels(self, panel_mode: str | None = None):
        """Rename Released/Pressed UI to State OFF/ON when appearance follows a GEX state."""
        if panel_mode is None:
            released = getattr(self, "_released_box", None)
            if released is not None and Shiboken.isValid(released) and released.isVisible():
                # Infer from visibility of pressed column when possible.
                pressed = getattr(self, "_pressed_box", None)
                if pressed is not None and Shiboken.isValid(pressed) and pressed.isVisible():
                    panel_mode = "button"
                else:
                    title = released.title() if hasattr(released, "title") else ""
                    if title == "LCD":
                        panel_mode = "lcd"
                    elif title.startswith("Icon"):
                        panel_mode = "look"
                    else:
                        panel_mode = "button"
            else:
                panel_mode = "hidden"
        driver = self._current_appearance_driver() if panel_mode == "button" else "press"
        use_state = driver == "state" and panel_mode == "button"

        state_label = getattr(self, "_appearance_state_label", None)
        state_combo = getattr(self, "_appearance_state_combo", None)
        if state_label is not None and Shiboken.isValid(state_label):
            state_label.setVisible(use_state)
        if state_combo is not None and Shiboken.isValid(state_combo):
            state_combo.setVisible(use_state)
            state_combo.setEnabled(use_state)

        released = getattr(self, "_released_box", None)
        pressed = getattr(self, "_pressed_box", None)
        if released is not None and Shiboken.isValid(released):
            if panel_mode == "lcd":
                released.setTitle("LCD")
            elif panel_mode == "look":
                released.setTitle("Icon / background")
            elif use_state:
                released.setTitle("State OFF")
            else:
                released.setTitle("Released")
        if pressed is not None and Shiboken.isValid(pressed):
            pressed.setTitle("State ON" if use_state else "Pressed")

        title = getattr(self, "_title_edit", None)
        if title is not None and Shiboken.isValid(title):
            if panel_mode == "lcd":
                title.setPlaceholderText("LCD title — up to 3 lines")
            elif use_state:
                title.setPlaceholderText("State OFF title — up to 3 lines")
            else:
                title.setPlaceholderText("Released title — up to 3 lines")
        title_p = getattr(self, "_title_pressed_edit", None)
        if title_p is not None and Shiboken.isValid(title_p):
            title_p.setPlaceholderText(
                "State ON title — up to 3 lines (blank = use State OFF)"
                if use_state
                else "Pressed title — up to 3 lines (blank = use released)"
            )

        preview_rel = getattr(self, "_preview_released_btn", None)
        preview_prs = getattr(self, "_preview_pressed_btn", None)
        if preview_rel is not None and Shiboken.isValid(preview_rel):
            preview_rel.setText("State OFF" if use_state else "Released")
            preview_rel.setToolTip(
                "Show State OFF appearance on the grid" if use_state else "Show released (idle) appearance on the grid"
            )
            preview_rel.setMinimumWidth(80 if use_state else 72)
        if preview_prs is not None and Shiboken.isValid(preview_prs):
            preview_prs.setText("State ON" if use_state else "Pressed")
            preview_prs.setToolTip(
                "Show State ON appearance on the grid" if use_state else "Show pressed appearance on the grid"
            )
            preview_prs.setMinimumWidth(72 if use_state else 64)

        icon = getattr(self, "_icon_preview", None)
        if icon is not None and Shiboken.isValid(icon):
            icon.setToolTip(
                "State OFF icon — drop image or click to choose"
                if use_state
                else "Released (unpressed) icon — drop image or click to choose"
            )
        icon_p = getattr(self, "_pressed_preview", None)
        if icon_p is not None and Shiboken.isValid(icon_p):
            icon_p.setToolTip(
                "State ON icon — drop image or click to choose" if use_state else "Pressed icon — drop image or click to choose"
            )
        bg = getattr(self, "_bg_swatch", None)
        if bg is not None and Shiboken.isValid(bg):
            bg.setToolTip("State OFF background color" if use_state else "Released background color")
        bg_p = getattr(self, "_bg_swatch_p", None)
        if bg_p is not None and Shiboken.isValid(bg_p):
            bg_p.setToolTip("State ON background color" if use_state else "Pressed background color")

    def _populate_appearance_state_combo(self, selected: str = ""):
        combo = getattr(self, "_appearance_state_combo", None)
        if combo is None or not Shiboken.isValid(combo):
            return
        names = self._gex_state_names()
        selected = (selected or "").strip()
        with QtCore.QSignalBlocker(combo):
            combo.clear()
            combo.addItem("")
            for name in names:
                combo.addItem(name)
            if selected:
                idx = combo.findText(selected)
                if idx < 0:
                    combo.addItem(selected)
                    idx = combo.findText(selected)
                combo.setCurrentIndex(max(0, idx))
            else:
                combo.setCurrentIndex(0)

    def _on_appearance_mode_ui(self, *_args):
        item = self._selected_item()
        if item is None:
            self._refresh_appearance_driver_labels(panel_mode="button")
            return
        combo = getattr(self, "_appearance_mode_combo", None)
        mode = "press"
        if combo is not None and Shiboken.isValid(combo):
            mode = str(combo.currentData() or "press")
        item.appearance_mode = mode
        self._refresh_appearance_driver_labels(panel_mode="button")
        self._refresh_cell_contents()
        bridge = self._bridge()
        if bridge.get_active_page(self._device_id) == self._edit_page:
            bridge.paint_active_page(self._device_id)

    def _on_appearance_state_ui(self, *_args):
        item = self._selected_item()
        if item is None:
            return
        combo = getattr(self, "_appearance_state_combo", None)
        if combo is None or not Shiboken.isValid(combo):
            return
        item.appearance_state = (combo.currentText() or "").strip()
        self._refresh_cell_contents()
        bridge = self._bridge()
        if bridge.get_active_page(self._device_id) == self._edit_page:
            bridge.paint_active_page(self._device_id)

    def _load_appearance_fields(self, item):
        blockers = []
        for block in (getattr(self, "_style_rel", None), getattr(self, "_style_prs", None)):
            if not block:
                continue
            for w in block.values():
                if w is not None and Shiboken.isValid(w):
                    blockers.append(QtCore.QSignalBlocker(w))
        mode_combo = getattr(self, "_appearance_mode_combo", None)
        if mode_combo is not None and Shiboken.isValid(mode_combo):
            mode = str(getattr(item, "appearance_mode", "press") or "press").casefold()
            if mode != "state":
                mode = "press"
            with QtCore.QSignalBlocker(mode_combo):
                idx = mode_combo.findData(mode)
                mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._populate_appearance_state_combo(getattr(item, "appearance_state", "") or "")
        if Shiboken.isValid(self._title_edit):
            lines = [
                item.title or "",
                getattr(item, "text_line2", "") or "",
                getattr(item, "text_line3", "") or "",
            ]
            while lines and not lines[-1]:
                lines.pop()
            with QtCore.QSignalBlocker(self._title_edit):
                self._title_edit.setPlainText("\n".join(lines))
        if getattr(self, "_title_pressed_edit", None) is not None and Shiboken.isValid(self._title_pressed_edit):
            lines = [
                getattr(item, "title_pressed", "") or "",
                getattr(item, "text_line2_pressed", "") or "",
                getattr(item, "text_line3_pressed", "") or "",
            ]
            while lines and not lines[-1]:
                lines.pop()
            with QtCore.QSignalBlocker(self._title_pressed_edit):
                self._title_pressed_edit.setPlainText("\n".join(lines))
        if Shiboken.isValid(self._icon_path_edit):
            self._icon_path_edit.setText(getattr(item, "image_path", "") or "")
        if Shiboken.isValid(self._pressed_path_edit):
            self._pressed_path_edit.setText(getattr(item, "image_pressed_path", "") or "")
        self._set_icon_preview(
            getattr(self, "_icon_preview", None),
            getattr(item, "image_path", "") or "",
            getattr(item, "image", "") or "",
        )
        self._set_icon_preview(
            getattr(self, "_pressed_preview", None),
            getattr(item, "image_pressed_path", "") or "",
            getattr(item, "image_pressed", "") or "",
        )
        self._load_style_block(
            getattr(self, "_style_rel", None),
            font_family=getattr(item, "font_family", "Segoe UI") or "Segoe UI",
            font_size=int(getattr(item, "font_size", 18) or 18),
            font_color=getattr(item, "font_color", "#ffffff") or "#ffffff",
            shrink=bool(getattr(item, "shrink_to_fit", True)),
            text_h=getattr(item, "text_h_align", "center") or "center",
            text_v=getattr(item, "text_v_align", "bottom") or "bottom",
            icon_h=getattr(item, "icon_h_align", "center") or "center",
            icon_v=getattr(item, "icon_v_align", "middle") or "middle",
            bg_color=getattr(item, "bg_color", "") or "",
            pressed=False,
        )
        self._load_style_block(
            getattr(self, "_style_prs", None),
            font_family=getattr(item, "font_family_pressed", "Segoe UI") or "Segoe UI",
            font_size=int(getattr(item, "font_size_pressed", 18) or 18),
            font_color=getattr(item, "font_color_pressed", "#ffffff") or "#ffffff",
            shrink=bool(getattr(item, "shrink_to_fit_pressed", True)),
            text_h=getattr(item, "text_h_align_pressed", "center") or "center",
            text_v=getattr(item, "text_v_align_pressed", "bottom") or "bottom",
            icon_h=getattr(item, "icon_h_align_pressed", "center") or "center",
            icon_v=getattr(item, "icon_v_align_pressed", "middle") or "middle",
            bg_color=getattr(item, "bg_color_pressed", "") or "",
            pressed=True,
        )
        self._update_color_button_styles()
        self._refresh_appearance_driver_labels(panel_mode="button")
        del blockers

    def _load_style_block(
        self,
        block: dict | None,
        *,
        font_family: str,
        font_size: int,
        font_color: str,
        shrink: bool,
        text_h: str,
        text_v: str,
        icon_h: str,
        icon_v: str,
        bg_color: str,
        pressed: bool,
    ):
        if not block:
            return
        ff = block.get("font_family")
        if ff is not None and Shiboken.isValid(ff):
            ff.setCurrentFont(QtGui.QFont(font_family))
        fs = block.get("font_size")
        if fs is not None and Shiboken.isValid(fs):
            fs.setValue(font_size)
        if pressed:
            self._font_color_p = font_color
            self._bg_color_p = bg_color
        else:
            self._font_color = font_color
            self._bg_color = bg_color
        sf = block.get("shrink_fit")
        if sf is not None and Shiboken.isValid(sf):
            sf.setChecked(shrink)
        for key, value, fallback in (
            ("text_h", text_h, 1),
            ("text_v", text_v, 2),
            ("icon_h", icon_h, 1),
            ("icon_v", icon_v, 1),
        ):
            w = block.get(key)
            if w is not None and Shiboken.isValid(w):
                idx = w.findData(value)
                w.setCurrentIndex(idx if idx >= 0 else fallback)

    def _update_color_button_styles(self):
        for block, font_c in (
            (getattr(self, "_style_rel", None), getattr(self, "_font_color", "#ffffff")),
            (getattr(self, "_style_prs", None), getattr(self, "_font_color_p", "#ffffff")),
        ):
            if not block:
                continue
            btn = block.get("font_color_btn")
            if btn is not None and Shiboken.isValid(btn):
                btn.setStyleSheet(f"background:{font_c}; color:#000; border-radius:4px; padding:4px 8px;")
        swatch = getattr(self, "_bg_swatch", None)
        if swatch is not None and Shiboken.isValid(swatch):
            swatch.set_color(getattr(self, "_bg_color", "") or "")
        swatch_p = getattr(self, "_bg_swatch_p", None)
        if swatch_p is not None and Shiboken.isValid(swatch_p):
            swatch_p.set_color(getattr(self, "_bg_color_p", "") or "")

    def _apply_title_lines_to_item(self, item, edit, attr_names: tuple[str, str, str]):
        """Split a 3-line title field into the given item attributes."""
        a1, a2, a3 = attr_names
        if item is None or edit is None or not Shiboken.isValid(edit):
            return
        raw = edit.toPlainText().replace("\r\n", "\n").replace("\r", "\n")
        parts = raw.split("\n")
        while len(parts) < 3:
            parts.append("")
        setattr(item, a1, parts[0].rstrip())
        setattr(item, a2, parts[1].rstrip())
        setattr(item, a3, parts[2].rstrip())
        if len(raw.split("\n")) > 3:
            trimmed = [parts[0], parts[1], parts[2]]
            while trimmed and not str(trimmed[-1]).strip():
                trimmed.pop()
            with QtCore.QSignalBlocker(edit):
                edit.setPlainText("\n".join(trimmed))

    def _apply_style_block_to_item(self, item, block: dict | None, *, pressed: bool):
        if item is None or not block:
            return
        suffix = "_pressed" if pressed else ""
        ff = block.get("font_family")
        if ff is not None and Shiboken.isValid(ff):
            setattr(item, f"font_family{suffix}", ff.currentFont().family())
        fs = block.get("font_size")
        if fs is not None and Shiboken.isValid(fs):
            setattr(item, f"font_size{suffix}", fs.value())
        font_c = getattr(self, "_font_color_p" if pressed else "_font_color", "#ffffff") or "#ffffff"
        bg_c = getattr(self, "_bg_color_p" if pressed else "_bg_color", "") or ""
        setattr(item, f"font_color{suffix}", font_c)
        setattr(item, f"bg_color{suffix}", bg_c)
        sf = block.get("shrink_fit")
        if sf is not None and Shiboken.isValid(sf):
            setattr(item, f"shrink_to_fit{suffix}", sf.isChecked())
        for key, attr in (
            ("text_h", f"text_h_align{suffix}"),
            ("text_v", f"text_v_align{suffix}"),
            ("icon_h", f"icon_h_align{suffix}"),
            ("icon_v", f"icon_v_align{suffix}"),
        ):
            w = block.get(key)
            if w is not None and Shiboken.isValid(w):
                default = "bottom" if "v_align" in attr and "text" in attr else ("middle" if "icon_v" in attr else "center")
                setattr(item, attr, w.currentData() or default)

    def _apply_style_fields(self):
        item = self._selected_item()
        if item is None:
            return
        look_only = self._slot_is_foreign(
            self._selected_row, self._selected_col, self._selected_kind or "button"
        )
        if look_only:
            # Other-plugin keys: persist background only; icon is set via browse/drop.
            item.bg_color = getattr(self, "_bg_color", "") or ""
            self._refresh_cell_contents()
            bridge = self._bridge()
            if bridge.get_active_page(self._device_id) == self._edit_page:
                bridge.paint_active_page(self._device_id)
            return
        self._apply_title_lines_to_item(
            item, getattr(self, "_title_edit", None), ("title", "text_line2", "text_line3")
        )
        self._apply_title_lines_to_item(
            item,
            getattr(self, "_title_pressed_edit", None),
            ("title_pressed", "text_line2_pressed", "text_line3_pressed"),
        )
        self._apply_style_block_to_item(item, getattr(self, "_style_rel", None), pressed=False)
        self._apply_style_block_to_item(item, getattr(self, "_style_prs", None), pressed=True)
        mode_combo = getattr(self, "_appearance_mode_combo", None)
        if mode_combo is not None and Shiboken.isValid(mode_combo):
            item.appearance_mode = str(mode_combo.currentData() or "press")
        state_combo = getattr(self, "_appearance_state_combo", None)
        if state_combo is not None and Shiboken.isValid(state_combo):
            item.appearance_state = (state_combo.currentText() or "").strip()
        self._refresh_cell_contents()
        bridge = self._bridge()
        if bridge.get_active_page(self._device_id) == self._edit_page:
            bridge.paint_active_page(self._device_id)

    def _pick_font_color(self, pressed: bool = False):
        key = "_font_color_p" if pressed else "_font_color"
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(getattr(self, key, "#ffffff")), self, "Text color"
        )
        if color.isValid():
            setattr(self, key, color.name())
            self._update_color_button_styles()
            self._apply_style_fields()

    def _pick_bg_color(self, pressed: bool = False):
        key = "_bg_color_p" if pressed else "_bg_color"
        initial = getattr(self, key, "") or "#1a1a1a"
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(initial), self, "Background color")
        if color.isValid():
            setattr(self, key, color.name())
            self._update_color_button_styles()
            self._apply_style_fields()

    def _clear_bg_color(self, pressed: bool = False):
        key = "_bg_color_p" if pressed else "_bg_color"
        setattr(self, key, "")
        self._update_color_button_styles()
        self._apply_style_fields()

    def _on_slot_moved(self, src, dst):
        """Swap appearance (+ action containers) between two slots."""
        if not src or not dst or src == dst:
            return
        sk, sr, sc = src
        dk, dr, dc = dst
        if self._slot_is_foreign(sr, sc, sk) or self._slot_is_foreign(dr, dc, dk):
            return
        bridge = self._bridge()
        src_item = bridge.ensure_slot_input(
            self._device_id, self._edit_page, kind=sk, row=sr, column=sc,
            button_id=str(sc) if sk != "button" else "",
        )
        dst_item = bridge.ensure_slot_input(
            self._device_id, self._edit_page, kind=dk, row=dr, column=dc,
            button_id=str(dc) if dk != "button" else "",
        )
        if src_item is None or dst_item is None:
            return
        snap_a = src_item.style_snapshot()
        snap_b = dst_item.style_snapshot()
        src_item.apply_style_snapshot(snap_b)
        dst_item.apply_style_snapshot(snap_a)
        # Swap containers by identity move (suspend to avoid mid-swap redraw crash)
        try:
            src_model = src_item.containers
            dst_model = dst_item.containers
            src_model.pushSuspend()
            dst_model.pushSuspend()
            try:
                ca = [c for c in list(src_model)]
                cb = [c for c in list(dst_model)]
                while len(src_model):
                    src_model.removeAt(0)
                while len(dst_model):
                    dst_model.removeAt(0)
                for c in cb:
                    try:
                        c.parent = src_item
                    except Exception:
                        pass
                    src_model.addContainer(c)
                for c in ca:
                    try:
                        c.parent = dst_item
                    except Exception:
                        pass
                    dst_model.addContainer(c)
            finally:
                src_model.popSuspend()
                dst_model.popSuspend()
        except Exception as err:
            syslog.error(f"STREAMDECK: swap containers failed: {err}")
        self._on_cell_clicked(dr, dc, dk)
        self._refresh_cell_contents()
        self.pages_changed.emit()
        if bridge.get_active_page(self._device_id) == self._edit_page:
            bridge.paint_active_page(self._device_id)

    def _on_context_action(self, action: str, row: int, col: int, kind: str):
        global _button_clipboard
        look_only = self._slot_is_foreign(row, col, kind)
        key = (kind or "button", row, col)
        multi = set(getattr(self, "_multi_selection", set()) or set())

        # Right-click on a key outside the multi-selection replaces it.
        if kind == "button" and not look_only:
            if key not in multi:
                self._multi_selection = {key}
                self._on_cell_clicked(row, col, kind)
            else:
                self._selected_row = row
                self._selected_col = col
                self._selected_kind = kind
                self._restore_selection_highlight()
        else:
            self._clear_multi_selection()
            self._on_cell_clicked(row, col, kind)

        item = self._selected_item()
        if action == "wipe_page":
            self._wipe_page()
            return
        if isinstance(action, str) and action.startswith("link:"):
            try:
                target = int(action.split(":", 1)[1])
            except (TypeError, ValueError):
                return
            if kind != "button" or look_only:
                return
            self._link_selected_to_page(target)
            return
        if action == "unlink":
            if kind != "button" or look_only:
                return
            self._unlink_selected()
            return
        if item is None and action != "paste":
            return
        if action == "copy" and item is not None:
            # Copy always uses the right-clicked / primary key.
            snap = item.style_snapshot()
            snap[_CLIPBOARD_CONTAINERS_KEY] = (
                None if look_only else _containers_xml_snapshot(item)
            )
            _button_clipboard = snap
        elif action == "paste":
            if _button_clipboard is None:
                return
            keys = self._button_selection_keys() if kind == "button" and not look_only else []
            targets = self._items_for_keys(keys, create=True) if keys else ([item] if item else [])
            if not targets:
                return
            for tgt in targets:
                tgt.apply_style_snapshot(_button_clipboard)
                if not look_only:
                    _apply_containers_xml(tgt, _button_clipboard.get(_CLIPBOARD_CONTAINERS_KEY))
            if len(keys) > 1:
                self._show_multi_selection_ui()
            elif getattr(targets[0], "is_linked", False):
                self._show_linked_selection(targets[0])
            else:
                self._load_appearance_fields(targets[0])
                show_mappings = kind != "dial_screen" and not look_only
                self.mapping_enabled_changed.emit(show_mappings)
                self.selection_changed.emit(targets[0] if show_mappings else None)
            self._refresh_cell_contents()
            bridge = self._bridge()
            if bridge.get_active_page(self._device_id) == self._edit_page:
                bridge.paint_active_page(self._device_id)
            self.pages_changed.emit()
        elif action == "delete":
            self._clear_selected_cell()

    def _wipe_page(self):
        reply = QtWidgets.QMessageBox.question(
            self,
            "Wipe page",
            f"Clear all keys on page {self._edit_page}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        for item in list(self._inputs_on_edit_page()):
            try:
                while item.containers and len(item.containers):
                    item.containers.removeAt(0)
            except Exception:
                pass
            item.apply_style_snapshot(
                {
                    "title": "",
                    "text_line2": "",
                    "text_line3": "",
                    "title_pressed": "",
                    "text_line2_pressed": "",
                    "text_line3_pressed": "",
                    "image": "",
                    "image_path": "",
                    "image_expr": "",
                    "image_pressed": "",
                    "image_pressed_path": "",
                    "font_family": "Segoe UI",
                    "font_size": 18,
                    "font_color": "#ffffff",
                    "text_h_align": "center",
                    "text_v_align": "bottom",
                    "shrink_to_fit": True,
                    "icon_h_align": "center",
                    "icon_v_align": "middle",
                    "bg_color": "",
                    "font_family_pressed": "Segoe UI",
                    "font_size_pressed": 18,
                    "font_color_pressed": "#ffffff",
                    "text_h_align_pressed": "center",
                    "text_v_align_pressed": "bottom",
                    "shrink_to_fit_pressed": True,
                    "icon_h_align_pressed": "center",
                    "icon_v_align_pressed": "middle",
                    "bg_color_pressed": "",
                    "appearance_mode": "press",
                    "appearance_state": "",
                    "step_mode": "all",
                    "step_wrap": True,
                }
            )
            item.step_index = 0
            item.linked_page = 0
        self._selected_row = None
        self._selected_col = None
        self._clear_multi_selection()
        self.selection_changed.emit(None)
        self._set_appearance_mode("hidden")
        self._refresh_cell_contents()
        bridge = self._bridge()
        if bridge.get_active_page(self._device_id) == self._edit_page:
            bridge.paint_active_page(self._device_id)

    def _selected_item(self):
        dial_ui = ("dial_press", "dial_screen", "dial_inc", "dial_dec")
        if self._selected_row is None and self._selected_kind not in dial_ui:
            return None
        if self._selected_col is None and self._selected_kind in dial_ui:
            return None
        bridge = self._bridge()
        kind = self._selected_kind or "button"
        col = self._selected_col
        if kind == "dial_inc":
            meta = {"kind": "dial", "row": None, "column": None, "button_id": f"{col}:inc"}
        elif kind == "dial_dec":
            meta = {"kind": "dial", "row": None, "column": None, "button_id": f"{col}:dec"}
        elif kind in ("dial_press", "dial_screen"):
            meta = {"kind": "dial_press", "row": 0, "column": col, "button_id": str(col)}
        else:
            if self._selected_row is None:
                return None
            meta = {
                "kind": "button",
                "row": self._selected_row,
                "column": self._selected_col,
                "button_id": "",
            }
        return bridge.find_input_for_slot(self._device_id, self._edit_page, meta)

    def _browse_icon(self):
        item = self._selected_item()
        if item is None:
            QtWidgets.QMessageBox.information(self, "Stream Deck", "Select a key first.")
            return
        from gremlin.ui.streamdeck_icon_picker import pick_icon_path

        path = pick_icon_path(self, pressed=False)
        if path:
            self._apply_icon_path(item, path)

    def _on_released_preview_drop(self, path: str):
        item = self._selected_item()
        if item is None:
            QtWidgets.QMessageBox.information(self, "Stream Deck", "Select a key first.")
            return
        self._apply_icon_path(item, path)

    def _on_pressed_preview_drop(self, path: str):
        item = self._selected_item()
        if item is None:
            QtWidgets.QMessageBox.information(self, "Stream Deck", "Select a key first.")
            return
        self._apply_pressed_icon_path(item, path)

    def _on_icon_dropped(self, row: int, col: int, kind: str, path: str):
        """Drop an image file onto a key → released (unpressed) icon."""
        if not path:
            return
        # Select the target cell first so the inspector matches the drop.
        self._on_cell_clicked(row, col, kind or "button")
        item = self._selected_item()
        if item is None:
            QtWidgets.QMessageBox.warning(self, "Stream Deck", "Could not bind that key.")
            return
        if getattr(item, "is_linked", False):
            QtWidgets.QMessageBox.information(
                self,
                "Linked key",
                f"This key is linked to page {item.linked_page}.\n"
                f"Change the icon on that page instead.",
            )
            return
        self._apply_icon_path(item, path)

    def _apply_icon_path(self, item, path: str) -> bool:
        """Set the released (idle / unpressed) icon and update previews."""
        from gremlin.ui.streamdeck_surface import file_to_data_url

        # Library picker may hand a temp PNG; still import into profile folder.
        imported = _import_icon_to_profile_folder(path)
        if not imported:
            QtWidgets.QMessageBox.warning(self, "Stream Deck", "Could not import that image into streamdeck_icons.")
            return False
        data_url = file_to_data_url(imported)
        if not data_url:
            QtWidgets.QMessageBox.warning(self, "Stream Deck", "Could not load that image.")
            return False
        item.image_path = imported
        item.image = data_url  # deck-sized PNG data-URL
        if Shiboken.isValid(self._icon_path_edit):
            self._icon_path_edit.setText(imported)
        self._set_icon_preview(getattr(self, "_icon_preview", None), imported, data_url)
        self._refresh_cell_contents()
        # Keep inspector in sync (released square must show the dropped image).
        if item is self._selected_item():
            self._load_appearance_fields(item)
        bridge = self._bridge()
        if bridge.get_active_page(self._device_id) == self._edit_page:
            bridge.paint_active_page(self._device_id)
        return True

    def _clear_icon(self):
        item = self._selected_item()
        if item is None:
            return
        item.image = ""
        item.image_path = ""
        item.image_expr = ""
        if Shiboken.isValid(self._icon_path_edit):
            self._icon_path_edit.setText("")
        self._set_icon_preview(getattr(self, "_icon_preview", None))
        self._refresh_cell_contents()
        bridge = self._bridge()
        if bridge.get_active_page(self._device_id) == self._edit_page:
            bridge.paint_active_page(self._device_id)

    def _browse_pressed_icon(self):
        item = self._selected_item()
        if item is None:
            QtWidgets.QMessageBox.information(self, "Stream Deck", "Select a key first.")
            return
        from gremlin.ui.streamdeck_icon_picker import pick_icon_path

        path = pick_icon_path(self, pressed=True)
        if path:
            self._apply_pressed_icon_path(item, path)

    def _apply_pressed_icon_path(self, item, path: str) -> bool:
        from gremlin.ui.streamdeck_surface import file_to_data_url

        imported = _import_icon_to_profile_folder(path)
        if not imported:
            QtWidgets.QMessageBox.warning(self, "Stream Deck", "Could not import that image into streamdeck_icons.")
            return False
        data_url = file_to_data_url(imported)
        if not data_url:
            QtWidgets.QMessageBox.warning(self, "Stream Deck", "Could not load that image.")
            return False
        item.image_pressed_path = imported
        item.image_pressed = data_url
        if Shiboken.isValid(self._pressed_path_edit):
            self._pressed_path_edit.setText(imported)
        self._set_icon_preview(getattr(self, "_pressed_preview", None), imported, data_url)
        if item is self._selected_item():
            self._load_appearance_fields(item)
        return True

    def _clear_pressed_icon(self):
        item = self._selected_item()
        if item is None:
            return
        item.image_pressed = ""
        item.image_pressed_path = ""
        if Shiboken.isValid(self._pressed_path_edit):
            self._pressed_path_edit.setText("")
        self._set_icon_preview(getattr(self, "_pressed_preview", None))

    def _clear_selected_cell(self):
        keys = self._button_selection_keys()
        items = self._items_for_keys(keys, create=False) if keys else []
        if not items:
            item = self._selected_item()
            if item is None:
                return
            items = [item]
        for item in items:
            try:
                while item.containers and len(item.containers):
                    item.containers.removeAt(0)
            except Exception:
                try:
                    item.containers.clear()
                except Exception:
                    pass
            item.title = ""
            item.image = ""
            item.image_path = ""
            item.image_expr = ""
            item.image_pressed = ""
            item.image_pressed_path = ""
            item.text_line2 = ""
            item.text_line3 = ""
            item.title_pressed = ""
            item.text_line2_pressed = ""
            item.text_line3_pressed = ""
            item.bg_color = ""
            item.font_family = "Segoe UI"
            item.font_size = 18
            item.font_color = "#ffffff"
            item.text_h_align = "center"
            item.text_v_align = "bottom"
            item.icon_h_align = "center"
            item.icon_v_align = "middle"
            item.shrink_to_fit = True
            item.sync_pressed_style_from_released()
            item.appearance_mode = "press"
            item.appearance_state = ""
            item.step_mode = "all"
            item.step_index = 0
            item.linked_page = 0
        self._font_color = "#ffffff"
        self._bg_color = ""
        self._font_color_p = "#ffffff"
        self._bg_color_p = ""
        self._sync_primary_from_multi()
        if len(keys) > 1:
            self._show_multi_selection_ui()
        else:
            primary = items[0]
            self._load_appearance_fields(primary)
            self._set_appearance_mode("button")
            self.selection_changed.emit(primary)
            self.mapping_enabled_changed.emit(True)
        self._refresh_cell_contents()
        bridge = self._bridge()
        if bridge.get_active_page(self._device_id) == self._edit_page:
            bridge.paint_active_page(self._device_id)

    def _add_page(self):
        if not self._device_id:
            return
        page = self._bridge().add_page(self._device_id)
        self._edit_page = page
        self.refresh()
        self.pages_changed.emit()

    def _delete_page(self):
        if not self._device_id:
            return
        bridge = self._bridge()
        if not bridge.delete_page(self._device_id, self._edit_page):
            QtWidgets.QMessageBox.information(self, "Stream Deck", "At least one page must remain.")
            return
        self._edit_page = bridge.get_active_page(self._device_id)
        self.refresh()
        self.pages_changed.emit()

    def _rename_page(self, *_args):
        if not self._device_id:
            return
        bridge = self._bridge()
        current = bridge.page_name(self._device_id, self._edit_page)
        text, ok = QtWidgets.QInputDialog.getText(self, "Rename page", "Page name:", text=current)
        if ok and text.strip():
            bridge.rename_page(self._device_id, self._edit_page, text.strip())
            self.refresh()

    def _import_companion_pages(self):
        if not self._device_id:
            QtWidgets.QMessageBox.warning(self, "Import from Companion", "No Stream Deck device is connected.")
            return
        from gremlin.ui.streamdeck_companion_import import run_companion_import_wizard

        summary = run_companion_import_wizard(self, self._device_id)
        if not summary:
            return
        page_numbers = summary.get("page_numbers") or []
        if page_numbers:
            self._edit_page = int(page_numbers[0])
            try:
                self._bridge().set_virtual_page(self._device_id, self._edit_page)
            except Exception:
                pass
        self.refresh()
        self.pages_changed.emit()

    def _on_refresh(self):
        if hasattr(self._tab, "_handle_refresh_clicked"):
            self._tab._handle_refresh_clicked()
        else:
            self.refresh()

    def _on_virtual_page_changed(self, device_id, page):
        if not Shiboken.isValid(self) or self._runtime_locked():
            return
        if device_id and self._device_id and device_id != self._device_id:
            return
        self._schedule_refresh()

    def _on_inputs_changed(self, device_guid):
        if not Shiboken.isValid(self) or self._runtime_locked():
            return
        from gremlin.util import compare_guid

        if compare_guid(device_guid, self._tab.device_guid):
            # Defer — willAppear storms must not paint cells mid-rebuild / after deleteLater.
            self._schedule_cell_refresh()

    def _on_slot_pressed(self, device_id, row, column, is_pressed):
        if not Shiboken.isValid(self) or self._runtime_locked():
            return
        if device_id and self._device_id and device_id != self._device_id:
            return
        try:
            r = int(row) if row is not None else None
            c = int(column) if column is not None else None
        except (TypeError, ValueError):
            return
        if r is None or c is None:
            return
        btn = self._cells.get(("button", r, c))
        if btn is not None and Shiboken.isValid(btn):
            btn.set_pressed_flash(bool(is_pressed))
            if is_pressed:
                if self._press_clear_timer is not None:
                    try:
                        self._press_clear_timer.stop()
                    except Exception:
                        pass
                self._press_clear_timer = QtCore.QTimer(self)
                self._press_clear_timer.setSingleShot(True)
                self._press_clear_timer.timeout.connect(lambda: btn.set_pressed_flash(False) if Shiboken.isValid(btn) else None)
                self._press_clear_timer.start(180)
