# -*- coding: utf-8; -*-
#
# Stream Deck icon source chooser + Elgato-style categorized icon library.
# Icons: gremlin/ui/streamdeck_icon_library/icons/ (CC0-style geometric SVGs).
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets, QtSvg
from shiboken6 import Shiboken

import gremlin.config
import gremlin.ui.ui_common
import gremlin.util
from gremlin.ui.ui_common import Buttons, Color, QDataPushButton

syslog = logging.getLogger("system")

_TIP_CONFIG_KEY = "streamdeck_icon_source_tip_hidden"
_PACK_ORDER = ("navigation", "media", "system", "status", "numbers")
_PACK_TITLES = {
    "navigation": "Navigation",
    "media": "Media",
    "system": "System",
    "status": "Status",
    "numbers": "Numbers",
}
_IMAGE_EXTS = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
_USER_META_NAME = "categories.json"


@dataclass
class IconEntry:
    pack_id: str
    pack_title: str
    name: str
    display_name: str
    path: str
    user_owned: bool = False


def _builtin_library_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "streamdeck_icon_library", "icons")


def _user_library_root() -> str:
    """Per-user icon library (not tied to a profile)."""
    try:
        base = gremlin.config.Configuration().data_path()
    except Exception:
        base = os.path.join(os.path.expanduser("~"), "Joystick Gremlin Ex")
    root = os.path.join(base, "streamdeck_icon_library")
    icons = os.path.join(root, "icons")
    os.makedirs(icons, exist_ok=True)
    return root


def _user_icons_root() -> str:
    return os.path.join(_user_library_root(), "icons")


def _user_meta_path() -> str:
    return os.path.join(_user_library_root(), _USER_META_NAME)


def _load_user_meta() -> dict:
    path = _user_meta_path()
    if not os.path.isfile(path):
        return {"categories": {}}
    try:
        import json

        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {"categories": {}}
        data.setdefault("categories", {})
        return data
    except Exception as err:
        syslog.error(f"STREAMDECK: icon library meta read failed: {err}")
        return {"categories": {}}


def _save_user_meta(data: dict) -> None:
    import json

    path = _user_meta_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)


def _sanitize_pack_id(title: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", "_", (title or "").strip().casefold()).strip("_")
    return raw[:48] or "custom"


def _display_name(stem: str) -> str:
    return re.sub(r"[_\-]+", " ", stem).strip().title()


def list_user_categories() -> list[tuple[str, str]]:
    """Return [(pack_id, title), ...] for user-created categories."""
    meta = _load_user_meta()
    cats = meta.get("categories") or {}
    out = []
    icons_root = _user_icons_root()
    # Include folders even if not in meta yet
    known = set(cats.keys())
    if os.path.isdir(icons_root):
        for name in os.listdir(icons_root):
            path = os.path.join(icons_root, name)
            if os.path.isdir(path) and name not in known:
                cats[name] = _display_name(name)
    for pack_id, title in cats.items():
        out.append((pack_id, str(title) or _display_name(pack_id)))
    out.sort(key=lambda t: t[1].casefold())
    return out


def create_user_category(title: str) -> tuple[str, str] | None:
    """Create a user category folder. Returns (pack_id, title) or None."""
    title = (title or "").strip()
    if not title:
        return None
    pack_id = _sanitize_pack_id(title)
    # Avoid clobbering built-in pack ids
    if pack_id in _PACK_TITLES or pack_id in _PACK_ORDER:
        pack_id = f"user_{pack_id}"
    folder = os.path.join(_user_icons_root(), pack_id)
    os.makedirs(folder, exist_ok=True)
    meta = _load_user_meta()
    meta.setdefault("categories", {})[pack_id] = title
    _save_user_meta(meta)
    return pack_id, title


def import_icons_to_category(pack_id: str, file_paths: list[str]) -> int:
    """Copy image files into a user category. Returns count imported."""
    if not pack_id or not file_paths:
        return 0
    dest_dir = os.path.join(_user_icons_root(), pack_id)
    os.makedirs(dest_dir, exist_ok=True)
    # Ensure category is registered
    meta = _load_user_meta()
    cats = meta.setdefault("categories", {})
    if pack_id not in cats:
        cats[pack_id] = _display_name(pack_id)
        _save_user_meta(meta)

    imported = 0
    used_names: set[str] = set()
    for src in file_paths:
        if not src or not os.path.isfile(src):
            continue
        ext = os.path.splitext(src)[1].lower()
        if ext not in _IMAGE_EXTS:
            continue
        base = os.path.splitext(os.path.basename(src))[0]
        safe = re.sub(r"[^a-zA-Z0-9_\-]+", "_", base).strip("_") or "icon"
        safe = safe[:60]
        dest_name = f"{safe}{ext}"
        n = 2
        while dest_name.casefold() in used_names or os.path.isfile(os.path.join(dest_dir, dest_name)):
            dest_name = f"{safe}_{n}{ext}"
            n += 1
        used_names.add(dest_name.casefold())
        try:
            import shutil

            shutil.copy2(src, os.path.join(dest_dir, dest_name))
            imported += 1
        except Exception as err:
            syslog.error(f"STREAMDECK: icon import failed ({src}): {err}")
    return imported


def _scan_pack_dir(
    pack_path: str,
    pack_id: str,
    title: str,
    *,
    user_owned: bool,
) -> list[IconEntry]:
    out: list[IconEntry] = []
    if not os.path.isdir(pack_path):
        return out
    files = sorted(
        f for f in os.listdir(pack_path) if f.lower().endswith(_IMAGE_EXTS) and not f.startswith(".")
    )
    for fname in files:
        stem = os.path.splitext(fname)[0]
        out.append(
            IconEntry(
                pack_id=pack_id,
                pack_title=title,
                name=stem,
                display_name=_display_name(stem),
                path=os.path.join(pack_path, fname),
                user_owned=user_owned,
            )
        )
    return out


def list_library_icons() -> list[IconEntry]:
    """Scan built-in + user icon packs (user library is profile-independent)."""
    out: list[IconEntry] = []

    # Built-in
    root = _builtin_library_root()
    if os.path.isdir(root):
        pack_dirs = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
        pack_dirs.sort(key=lambda n: (_PACK_ORDER.index(n) if n in _PACK_ORDER else 99, n))
        for pack_id in pack_dirs:
            title = _PACK_TITLES.get(pack_id, _display_name(pack_id))
            out.extend(_scan_pack_dir(os.path.join(root, pack_id), pack_id, title, user_owned=False))

    # User packs (after built-ins)
    user_root = _user_icons_root()
    meta = _load_user_meta()
    cats = meta.get("categories") or {}
    user_dirs = []
    if os.path.isdir(user_root):
        user_dirs = [n for n in os.listdir(user_root) if os.path.isdir(os.path.join(user_root, n))]
    user_dirs.sort(key=lambda n: str(cats.get(n, _display_name(n))).casefold())
    for pack_id in user_dirs:
        title = str(cats.get(pack_id) or _display_name(pack_id))
        out.extend(
            _scan_pack_dir(os.path.join(user_root, pack_id), pack_id, title, user_owned=True)
        )

    return out


def render_icon_to_png(
    path: str,
    size: int = 144,
    color: QtGui.QColor | None = None,
) -> str | None:
    """Render an SVG (or raster) icon to a temporary PNG and return that path.

    Optional ``color`` tints opaque glyph pixels (white library icons → any color).
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        lower = path.lower()
        if lower.endswith(".svg"):
            renderer = QtSvg.QSvgRenderer(path)
            if not renderer.isValid():
                return None
            image = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32)
            image.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(image)
            renderer.render(painter)
            painter.end()
        else:
            pm = QtGui.QPixmap(path)
            if pm.isNull():
                return None
            image = pm.scaled(
                size,
                size,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            ).toImage()
        if color is not None and color.isValid():
            image = _tint_glyph_image(image, color)
        fd, tmp = tempfile.mkstemp(prefix="jgex_sd_icon_", suffix=".png")
        os.close(fd)
        if not image.save(tmp, "PNG"):
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return None
        return tmp
    except Exception as err:
        syslog.error(f"STREAMDECK: icon render failed ({path}): {err}")
        return None


def _tint_glyph_image(image: QtGui.QImage, color: QtGui.QColor) -> QtGui.QImage:
    """Recolor white-on-transparent glyphs while preserving alpha/edges."""
    out = image.convertToFormat(QtGui.QImage.Format.Format_ARGB32)
    tr, tg, tb = color.red(), color.green(), color.blue()
    for y in range(out.height()):
        for x in range(out.width()):
            c = out.pixelColor(x, y)
            a = c.alpha()
            if a == 0:
                continue
            intensity = max(c.red(), c.green(), c.blue()) / 255.0
            out.setPixelColor(
                x,
                y,
                QtGui.QColor(int(tr * intensity), int(tg * intensity), int(tb * intensity), a),
            )
    return out


def should_show_icon_source_tip() -> bool:
    return not bool(gremlin.config.Configuration()._get_data(_TIP_CONFIG_KEY, False))


def set_icon_source_tip_hidden(hidden: bool) -> None:
    gremlin.config.Configuration()._set_data(_TIP_CONFIG_KEY, bool(hidden))


class _IconTile(QtWidgets.QToolButton):
    """Dark square tile matching Elgato's icon browser look."""

    def __init__(self, entry: IconEntry, tile_size: int, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setToolTip(entry.display_name)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._set_tile_size(tile_size)
        self._apply_icon()

    def _set_tile_size(self, tile_size: int):
        self._tile = int(tile_size)
        self.setFixedSize(self._tile, self._tile)
        pad = max(4, self._tile // 8)
        self.setIconSize(QtCore.QSize(self._tile - pad * 2, self._tile - pad * 2))
        self.setStyleSheet(
            f"""
            QToolButton {{
                background-color: #2b2b2b;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: {pad // 2}px;
            }}
            QToolButton:hover {{
                background-color: #353535;
                border-color: #5a5a5a;
            }}
            QToolButton:checked {{
                background-color: #3d4a5c;
                border: 2px solid #4c8bfd;
            }}
            """
        )

    def set_tile_size(self, tile_size: int):
        self._set_tile_size(tile_size)
        self._apply_icon()

    def _apply_icon(self):
        pm = QtGui.QPixmap(self.entry.path)
        if pm.isNull() and self.entry.path.lower().endswith(".svg"):
            renderer = QtSvg.QSvgRenderer(self.entry.path)
            if renderer.isValid():
                side = max(48, self._tile - 8)
                image = QtGui.QImage(side, side, QtGui.QImage.Format.Format_ARGB32)
                image.fill(QtCore.Qt.GlobalColor.transparent)
                painter = QtGui.QPainter(image)
                renderer.render(painter)
                painter.end()
                pm = QtGui.QPixmap.fromImage(image)
        if not pm.isNull():
            self.setIcon(QtGui.QIcon(pm))


class _PackSection(QtWidgets.QWidget):
    """Collapsible pack header + icon flow grid."""

    selection_changed = QtCore.Signal(object)  # IconEntry | None
    activated = QtCore.Signal(object)  # IconEntry

    def __init__(self, pack_title: str, entries: list[IconEntry], tile_size: int, parent=None):
        super().__init__(parent)
        self._pack_title = pack_title or (entries[0].pack_title if entries else "Pack")
        self._entries = list(entries)
        self._tiles: list[_IconTile] = []
        self._tile_size = tile_size
        self._expanded = True

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 8)
        root.setSpacing(4)

        # QToolButton + setArrowType hides text on some Windows styles — use a
        # plain flat button with an explicit chevron in the label.
        self._header = QtWidgets.QPushButton()
        self._header.setFlat(True)
        self._header.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        hdr = Color.headerBarBackgroundColor()
        fg = Color.normalColor()
        self._header.setStyleSheet(
            f"""
            QPushButton {{
                color: {fg};
                font-weight: 600;
                font-size: 13px;
                text-align: left;
                padding: 6px 4px;
                border: none;
                background: transparent;
            }}
            QPushButton:hover {{ color: {Color.normalLightColor()}; background-color: {hdr}; border-radius: 4px; }}
            """
        )
        self._header.clicked.connect(self._toggle)
        root.addWidget(self._header)

        self._grid_host = QtWidgets.QWidget()
        self._grid = QtWidgets.QGridLayout(self._grid_host)
        self._grid.setContentsMargins(8, 0, 8, 4)
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(6)
        root.addWidget(self._grid_host)

        self._rebuild_header()
        self._rebuild_grid()

    def _rebuild_header(self):
        count = len(self._entries)
        chevron = "▼" if self._expanded else "▶"
        self._header.setText(f"{chevron}  {self._pack_title}  ({count})")

    def _columns(self) -> int:
        # Approximate Elgato density; dialog width drives reflow via set_tile_size/relayout
        return max(6, int(560 / max(36, self._tile_size + 6)))

    def _rebuild_grid(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._tiles.clear()
        cols = self._columns()
        for i, entry in enumerate(self._entries):
            tile = _IconTile(entry, self._tile_size, self._grid_host)
            tile.clicked.connect(lambda checked=False, e=entry: self.selection_changed.emit(e))
            tile.installEventFilter(self)
            self._grid.addWidget(tile, i // cols, i % cols)
            self._tiles.append(tile)
        self._grid_host.setVisible(self._expanded and bool(self._entries))

    def eventFilter(self, obj, event):
        if isinstance(obj, _IconTile) and event.type() == QtCore.QEvent.Type.MouseButtonDblClick:
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                self.activated.emit(obj.entry)
                return True
        return super().eventFilter(obj, event)

    def _toggle(self):
        self._expanded = not self._expanded
        self._rebuild_header()
        self._grid_host.setVisible(self._expanded and bool(self._entries))

    def set_filter(self, query: str):
        q = (query or "").strip().casefold()
        # Do not use QWidget.isVisible() for layout membership: before the dialog
        # is shown, isVisible() is False for every child and the grid would empty.
        matched: list[_IconTile] = []
        for tile in self._tiles:
            entry = tile.entry
            hit = (not q) or q in entry.display_name.casefold() or q in entry.name.casefold()
            tile.setVisible(hit)
            if hit:
                matched.append(tile)
        cols = self._columns()
        for tile in self._tiles:
            self._grid.removeWidget(tile)
        for i, tile in enumerate(matched):
            self._grid.addWidget(tile, i // cols, i % cols)
        show_pack = bool(matched)
        self.setVisible(show_pack)
        if show_pack and q:
            self._expanded = True
            self._rebuild_header()
            self._grid_host.setVisible(True)
        elif show_pack:
            self._rebuild_header()

    def set_tile_size(self, tile_size: int):
        self._tile_size = int(tile_size)
        for tile in self._tiles:
            tile.set_tile_size(self._tile_size)
        # Reflow by filter match (isHidden), not isVisible — same pre-show pitfall.
        cols = self._columns()
        matched = [t for t in self._tiles if not t.isHidden()]
        for tile in self._tiles:
            self._grid.removeWidget(tile)
        for i, tile in enumerate(matched):
            self._grid.addWidget(tile, i // cols, i % cols)

    def clear_selection(self):
        for tile in self._tiles:
            with QtCore.QSignalBlocker(tile):
                tile.setChecked(False)


class IconLibraryDialog(gremlin.ui.ui_common.QRememberDialog):
    """Elgato-style categorized icon browser."""

    def __init__(self, parent=None, title: str = "Icon Library — Stream Deck"):
        super().__init__("streamdeck_icon_library", parent=parent)
        self.setWindowTitle(title)
        self.setMinimumSize(640, 520)
        self.resize(720, 560)
        self._selected: IconEntry | None = None
        self._tile_size = 56
        self.setStyleSheet(
            """
            QDialog { background-color: #1e1e1e; color: #e8e8e8; }
            QLineEdit {
                background-color: #2b2b2b;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
                padding: 8px 12px;
                color: #e8e8e8;
                selection-background-color: #4c8bfd;
            }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                background: #1e1e1e; width: 10px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #4a4a4a; border-radius: 4px; min-height: 24px;
            }
            QPushButton {
                background-color: #2b2b2b;
                border: 1px solid #4a4a4a;
                border-radius: 6px;
                padding: 6px 14px;
                color: #e8e8e8;
            }
            QPushButton:hover { background-color: #353535; }
            QPushButton:default {
                background-color: #3d6ea5;
                border-color: #4c8bfd;
            }
            """
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        search_row = QtWidgets.QHBoxLayout()
        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText("Search in icons…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search, 1)
        new_cat_btn = QDataPushButton("New category…", tooltip="Create a personal icon category (stored for your user, not in the profile)", clicked=self._new_category)
        import_btn = QDataPushButton("Import icons…", tooltip="Import image files into a personal category", clicked=lambda: self._import_icons())
        search_row.addWidget(new_cat_btn)
        search_row.addWidget(import_btn)
        layout.addLayout(search_row)

        hint = QtWidgets.QLabel(
            "Personal categories & imports are saved for your Windows user — not inside a profile."
        )
        hint.setStyleSheet(f"color: {Color.inactiveColor()}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body = QtWidgets.QWidget()
        self._body_layout = QtWidgets.QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 4, 0)
        self._body_layout.setSpacing(2)
        self._scroll.setWidget(self._body)
        layout.addWidget(self._scroll, 1)

        self._sections: list[_PackSection] = []
        self._stretch_item = None
        self._reload_packs()

        # Color controls (enabled once an icon is selected)
        color_row = QtWidgets.QHBoxLayout()
        color_row.addWidget(QtWidgets.QLabel("Color:"))
        self._color = QtGui.QColor("#ffffff")
        self._color_swatch = QtWidgets.QPushButton()
        self._color_swatch.setFixedSize(28, 28)
        self._color_swatch.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._color_swatch.setToolTip("Change icon color")
        self._color_swatch.clicked.connect(self._pick_color)
        self._update_color_swatch()
        color_row.addWidget(self._color_swatch)
        color_btn = QDataPushButton("Color…", tooltip="Pick a tint color for the selected icon", clicked=self._pick_color)
        white_btn = QDataPushButton("White", tooltip="Reset to white", clicked=self._reset_color)
        # Quick presets
        for name, hex_color in (
            ("Red", "#e74c3c"),
            ("Green", "#2ecc71"),
            ("Blue", "#3498db"),
            ("Amber", "#f1c40f"),
            ("Cyan", "#1abc9c"),
        ):
            b = QDataPushButton(name)
            b.setToolTip(hex_color)
            b.clicked.connect(lambda checked=False, c=hex_color: self._set_color(QtGui.QColor(c)))
            color_row.addWidget(b)
        color_row.addWidget(color_btn)
        color_row.addWidget(white_btn)
        color_row.addStretch(1)
        layout.addLayout(color_row)

        footer = QtWidgets.QHBoxLayout()
        zoom_down = QtWidgets.QToolButton()
        zoom_down.setText("−")
        zoom_down.setToolTip("Smaller icons")
        zoom_down.clicked.connect(lambda: self._nudge_zoom(-8))
        zoom_up = QtWidgets.QToolButton()
        zoom_up.setText("+")
        zoom_up.setToolTip("Larger icons")
        zoom_up.clicked.connect(lambda: self._nudge_zoom(8))
        for btn in (zoom_down, zoom_up):
            btn.setFixedSize(28, 28)
            btn.setStyleSheet(
                "QToolButton { background:#2b2b2b; border:1px solid #4a4a4a; border-radius:14px; color:#e8e8e8; }"
                "QToolButton:hover { background:#353535; }"
            )
        footer.addWidget(zoom_down)
        footer.addWidget(zoom_up)
        footer.addStretch(1)
        self._ok = Buttons.getOkWidget(callback=self._accept_selection)
        self._ok.setEnabled(False)
        cancel_btn = Buttons.getCancelWidget(callback=self.reject)
        footer.addWidget(
            gremlin.ui.ui_common.getHContainer([self._ok, cancel_btn], widget_only=True)
        )
        layout.addLayout(footer)

    def _update_color_swatch(self):
        c = self._color
        self._color_swatch.setStyleSheet(
            f"QPushButton {{ background-color: {c.name()}; border: 1px solid #888; border-radius: 4px; }}"
        )

    def _set_color(self, color: QtGui.QColor):
        if color.isValid():
            self._color = color
            self._update_color_swatch()

    def _reset_color(self):
        self._set_color(QtGui.QColor("#ffffff"))

    def _pick_color(self):
        color = QtWidgets.QColorDialog.getColor(self._color, self, "Icon color")
        if color.isValid():
            self._set_color(color)

    def _reload_packs(self):
        """Rebuild pack sections from built-in + user libraries."""
        # Clear existing sections
        for section in self._sections:
            section.setParent(None)
            section.deleteLater()
        self._sections.clear()
        # Remove leftover widgets (empty label / stretch)
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        icons = list_library_icons()
        by_pack: dict[str, list[IconEntry]] = {}
        for entry in icons:
            by_pack.setdefault(entry.pack_id, []).append(entry)
        for pack_id, entries in by_pack.items():
            title = entries[0].pack_title if entries else _PACK_TITLES.get(pack_id, pack_id)
            if entries and entries[0].user_owned:
                title = f"{title}  ·  Personal"
            section = _PackSection(title, entries, self._tile_size, self._body)
            section.selection_changed.connect(self._on_select)
            section.activated.connect(self._on_activate)
            self._body_layout.addWidget(section)
            self._sections.append(section)
        if not icons:
            empty = QtWidgets.QLabel("No icons found. Import some or use New category…")
            empty.setStyleSheet(f"color: {Color.inactiveColor()}; padding: 24px;")
            self._body_layout.addWidget(empty)
        self._body_layout.addStretch(1)
        # Re-apply active search filter
        if getattr(self, "_search", None) is not None:
            self._apply_filter(self._search.text())

    def _new_category(self):
        title, ok = QtWidgets.QInputDialog.getText(
            self,
            "New category",
            "Category name:",
        )
        if not ok or not title.strip():
            return
        created = create_user_category(title.strip())
        if not created:
            QtWidgets.QMessageBox.warning(self, "Icon Library", "Could not create that category.")
            return
        pack_id, display = created
        self._reload_packs()
        QtWidgets.QMessageBox.information(
            self,
            "Icon Library",
            f"Created personal category “{display}”.\nUse Import icons… to add images.",
        )
        # Offer import immediately
        reply = QtWidgets.QMessageBox.question(
            self,
            "Import icons",
            f"Import images into “{display}” now?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.Yes,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._import_icons(preferred_pack_id=pack_id)

    def _import_icons(self, preferred_pack_id: str | None = None):
        cats = list_user_categories()
        if not cats:
            title, ok = QtWidgets.QInputDialog.getText(
                self,
                "New category",
                "Create a category name for these icons:",
            )
            if not ok or not title.strip():
                return
            created = create_user_category(title.strip())
            if not created:
                return
            cats = [created]

        # Pick category
        labels = [t for _, t in cats]
        ids = [i for i, _ in cats]
        current = 0
        if preferred_pack_id and preferred_pack_id in ids:
            current = ids.index(preferred_pack_id)
        cat_title, ok = QtWidgets.QInputDialog.getItem(
            self,
            "Import icons",
            "Personal category:",
            labels,
            current,
            False,
        )
        if not ok or not cat_title:
            return
        pack_id = ids[labels.index(cat_title)]

        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Import icon images",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.svg);;All files (*.*)",
        )
        if not paths:
            return
        count = import_icons_to_category(pack_id, paths)
        self._reload_packs()
        if count:
            QtWidgets.QMessageBox.information(
                self,
                "Icon Library",
                f"Imported {count} icon(s) into “{cat_title}”.",
            )
        else:
            QtWidgets.QMessageBox.warning(self, "Icon Library", "No images were imported.")

    def _load_packs(self):
        self._reload_packs()

    def _apply_filter(self, text: str):
        for section in self._sections:
            section.set_filter(text)

    def _nudge_zoom(self, delta: int):
        self._tile_size = max(40, min(88, self._tile_size + delta))
        for section in self._sections:
            section.set_tile_size(self._tile_size)

    def _on_select(self, entry: IconEntry):
        self._selected = entry
        self._ok.setEnabled(entry is not None)
        # Clear checks in other packs
        for section in self._sections:
            if not any(t.entry is entry for t in section._tiles):
                section.clear_selection()

    def _on_activate(self, entry: IconEntry):
        self._selected = entry
        self.accept()

    def _accept_selection(self):
        if self._selected is None:
            return
        self.accept()

    def selected_path(self) -> str | None:
        if self._selected is None:
            return None
        tint = None if self._color.name().lower() == "#ffffff" else self._color
        # Don't tint multi-color raster packs by default unless user picked a color
        if tint is None:
            return render_icon_to_png(self._selected.path)
        return render_icon_to_png(self._selected.path, color=tint)


class IconSourceDialog(gremlin.ui.ui_common.QRememberDialog):
    """Choose Icon Library vs Custom file, with optional drag-drop tip."""

    SOURCE_LIBRARY = "library"
    SOURCE_CUSTOM = "custom"

    def __init__(self, parent=None, *, pressed: bool = False):
        super().__init__("streamdeck_icon_source", parent=parent)
        kind = "pressed" if pressed else "released"
        self.setWindowTitle(f"Choose {kind} icon")
        self.setMinimumWidth(440)
        self._source: str | None = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        show_tip = should_show_icon_source_tip()
        self._again: QtWidgets.QCheckBox | None = None
        if show_tip:
            banner = gremlin.ui.ui_common.QInfoBox(
                "Tip: you can also drag and drop an image file directly onto a "
                "Stream Deck key (or onto the Released / Pressed icon preview)."
            )
            self._again = QtWidgets.QCheckBox("Don't show this again")
            tip_wrap = QtWidgets.QWidget()
            tip_layout = QtWidgets.QVBoxLayout(tip_wrap)
            tip_layout.setContentsMargins(0, 0, 0, 0)
            tip_layout.addWidget(banner)
            tip_layout.addWidget(self._again)
            layout.addWidget(tip_wrap)

        layout.addWidget(QtWidgets.QLabel("Where should the icon come from?"))

        lib_btn = QDataPushButton("Icon Library…", tooltip="Browse built-in Stream Deck style icons by category", clicked=self._choose_library)
        custom_btn = QDataPushButton("Custom File…", tooltip="Open a file from disk (PNG, JPG, …)", clicked=self._choose_custom)
        for btn in (lib_btn, custom_btn):
            btn.setMinimumHeight(36)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(lib_btn, 1)
        row.addWidget(custom_btn, 1)
        layout.addLayout(row)

        cancel_btn = Buttons.getCancelWidget(callback=self.reject)
        layout.addWidget(
            gremlin.ui.ui_common.getHContainer(["||", cancel_btn], widget_only=True)
        )

    def _persist_tip(self):
        if self._again is not None and self._again.isChecked():
            set_icon_source_tip_hidden(True)

    def _choose_library(self):
        self._persist_tip()
        self._source = self.SOURCE_LIBRARY
        self.accept()

    def _choose_custom(self):
        self._persist_tip()
        self._source = self.SOURCE_CUSTOM
        self.accept()

    @property
    def source(self) -> str | None:
        return self._source


def pick_icon_path(parent: QtWidgets.QWidget | None = None, *, pressed: bool = False) -> str | None:
    """Full flow: tip + library/custom → returns a filesystem image path, or None."""
    chooser = IconSourceDialog(parent, pressed=pressed)
    if chooser.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return None
    if chooser.source == IconSourceDialog.SOURCE_CUSTOM:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            parent,
            "Select pressed icon" if pressed else "Select released icon",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.svg);;All files (*.*)",
        )
        if not path:
            return None
        if path.lower().endswith(".svg"):
            return render_icon_to_png(path)
        return path
    if chooser.source == IconSourceDialog.SOURCE_LIBRARY:
        dlg = IconLibraryDialog(parent)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        return dlg.selected_path()
    return None
