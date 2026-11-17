#
# Import Bitfocus Companion Stream Deck page appearance into GEX (titles/icons/colors).
# Mappings are left blank — only StreamDeckInputItem appearance is created/updated.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from PySide6 import QtCore, QtWidgets

import gremlin.config
import gremlin.shared_state

syslog = logging.getLogger("system")

COMPANION_EXPORT_TIP = (
    "In Bitfocus Companion, export your configuration as JSON before continuing.\n\n"
    "Typical path: the Import/Export (or Backup) section → Export configuration. "
    "Companion may save a .companionconfig or .json file — both are accepted.\n\n"
    "Next you will pick that file and choose which pages to import. "
    "Only titles, icons, and colors are imported; action mappings stay blank."
)


@dataclass
class CompanionPageInfo:
    """One Companion page available for import."""

    number: int
    name: str
    button_count: int = 0
    recommended: bool = False


@dataclass
class CompanionButtonAppearance:
    page: int
    row: int
    col: int
    title: str = ""
    font_color: str = "#ffffff"
    bg_color: str = ""
    image_data_url: str = ""


@dataclass
class CompanionImportPlan:
    """Parsed Companion config ready for selective import."""

    source_path: str
    pages: list[CompanionPageInfo] = field(default_factory=list)
    buttons: list[CompanionButtonAppearance] = field(default_factory=list)
    raw_pages: dict = field(default_factory=dict)

    def buttons_for_pages(self, page_numbers: set[int]) -> list[CompanionButtonAppearance]:
        return [b for b in self.buttons if b.page in page_numbers]


def _val(node, key, default=None):
    if not isinstance(node, dict):
        return default
    v = node.get(key, default)
    if isinstance(v, dict) and "value" in v:
        return v.get("value")
    return v


def rgb_int_to_hex(n) -> str:
    try:
        n = int(n) & 0xFFFFFF
    except (TypeError, ValueError):
        return ""
    return f"#{n:06x}"


def extract_appearance(btn: dict) -> dict:
    style = (btn or {}).get("style") or {}
    layers = style.get("layers") or []
    title = ""
    font_color = "#ffffff"
    bg_color = ""
    image_data_url = ""
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        kind = layer.get("type")
        if kind == "text":
            txt = _val(layer, "text") or ""
            if txt and not title:
                title = str(txt)
            col = _val(layer, "color")
            if col is not None:
                hx = rgb_int_to_hex(col)
                if hx:
                    font_color = hx
        elif kind == "box":
            col = _val(layer, "color")
            if col is not None:
                hx = rgb_int_to_hex(col)
                if hx and hx.lower() not in ("#000000", "#000"):
                    bg_color = hx
                elif hx and not bg_color:
                    bg_color = hx
        elif kind == "image":
            img = _val(layer, "base64Image") or _val(layer, "png") or ""
            if isinstance(img, str) and img:
                if img.startswith("data:"):
                    image_data_url = img
                elif re.fullmatch(r"[A-Za-z0-9+/=\s]+", img[:80] or ""):
                    image_data_url = "data:image/png;base64," + re.sub(r"\s+", "", img)
    return {
        "title": title,
        "font_color": font_color,
        "bg_color": bg_color,
        "image": image_data_url,
    }


def save_data_url(data_url: str, dest: Path) -> bool:
    if not data_url or not data_url.startswith("data:"):
        return False
    try:
        _header, b64 = data_url.split(",", 1)
    except ValueError:
        return False
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return True


def load_companion_plan(path: str) -> CompanionImportPlan:
    """Parse a Companion export (.json / .companionconfig) into an import plan."""
    path = os.path.abspath(path)
    with open(path, "r", encoding="utf-8") as hdl:
        data = json.load(hdl)
    if not isinstance(data, dict):
        raise ValueError("Companion file root must be a JSON object")
    pages_node = data.get("pages") or {}
    if not isinstance(pages_node, dict):
        raise ValueError("Companion file has no pages object")

    plan = CompanionImportPlan(source_path=path, raw_pages=pages_node)
    for page_key, pg in pages_node.items():
        if not isinstance(pg, dict):
            continue
        try:
            page_num = int(page_key)
        except (TypeError, ValueError):
            continue
        if page_num < 1:
            continue
        name = (pg.get("name") or f"Page {page_num}").strip() or f"Page {page_num}"
        controls = pg.get("controls") or {}
        button_count = 0
        if isinstance(controls, dict):
            for row_s, cols in controls.items():
                if not isinstance(cols, dict):
                    continue
                try:
                    row = int(row_s)
                except (TypeError, ValueError):
                    continue
                for col_s, btn in cols.items():
                    if not isinstance(btn, dict) or not btn.get("type"):
                        continue
                    try:
                        col = int(col_s)
                    except (TypeError, ValueError):
                        continue
                    appearance = extract_appearance(btn)
                    title = appearance.get("title") or ""
                    # Companion paints empty keys with "col/row" placeholders — not real titles.
                    if re.fullmatch(r"\d+/\d+", str(title).strip()):
                        title = ""
                    plan.buttons.append(
                        CompanionButtonAppearance(
                            page=page_num,
                            row=row,
                            col=col,
                            title=title,
                            font_color=appearance.get("font_color") or "#ffffff",
                            bg_color=appearance.get("bg_color") or "",
                            image_data_url=appearance.get("image") or "",
                        )
                    )
                    button_count += 1
        # Skip empty placeholder banks named PAGE unless they somehow have buttons.
        recommended = button_count > 0 or (name.upper() != "PAGE" and name != f"Page {page_num}")
        if button_count == 0 and name.upper() == "PAGE":
            # Still list empty placeholders so the user can pick them if desired,
            # but do not recommend them.
            recommended = False
        plan.pages.append(
            CompanionPageInfo(
                number=page_num,
                name=name,
                button_count=button_count,
                recommended=recommended or button_count > 0,
            )
        )
    plan.pages.sort(key=lambda p: p.number)
    return plan


def companion_icons_dir() -> str:
    """``<profile>/streamdeck_icons/companion_import``."""
    from gremlin.ui.streamdeck_designer import _profile_icons_dir

    dest = os.path.join(_profile_icons_dir(), "companion_import")
    os.makedirs(dest, exist_ok=True)
    return dest


def import_companion_pages(
    device_id: str,
    plan: CompanionImportPlan,
    page_numbers: list[int] | set[int],
    *,
    max_columns: int | None = None,
    max_rows: int | None = None,
) -> dict:
    """Import selected Companion pages into the live GEX profile for ``device_id``.

    Creates/updates Stream Deck slot appearance only (no action containers).
    Returns a summary dict: pages, buttons, icons, page_numbers.
    """
    from gremlin.ui.streamdeck_device import StreamDeckBridge, device_grid_size

    device_id = device_id or ""
    if not device_id:
        raise ValueError("No Stream Deck device selected")
    if not gremlin.shared_state.current_profile:
        raise ValueError("No profile is open")

    selected = {int(p) for p in page_numbers}
    if not selected:
        raise ValueError("No pages selected")

    bridge = StreamDeckBridge()
    info = bridge.devices.get(device_id) or {}
    grid = device_grid_size(info.get("type"))
    if grid:
        cols, rows = grid
    else:
        cols, rows = 8, 4
    if max_columns is not None:
        cols = int(max_columns)
    if max_rows is not None:
        rows = int(max_rows)

    icon_root = Path(companion_icons_dir())
    page_name_by_num = {p.number: p.name for p in plan.pages}
    imported_buttons = 0
    imported_icons = 0
    imported_pages = sorted(selected)

    for page_num in imported_pages:
        name = page_name_by_num.get(page_num) or f"Page {page_num}"
        bridge._ensure_page_listed(device_id, page_num)
        bridge.rename_page(device_id, page_num, name)

    for btn in plan.buttons_for_pages(selected):
        if btn.row < 0 or btn.col < 0 or btn.row >= rows or btn.col >= cols:
            continue
        title = (btn.title or "").strip()
        item = bridge.ensure_slot_input(
            device_id,
            btn.page,
            kind="button",
            row=btn.row,
            column=btn.col,
            button_id=f"{btn.row}:{btn.col}",
            title=title,
        )
        if item is None:
            continue
        if title:
            item.title = title
        if btn.font_color:
            item.font_color = btn.font_color
        if btn.bg_color:
            item.bg_color = btn.bg_color
        if btn.image_data_url:
            dest = icon_root / f"p{btn.page:02d}_r{btn.row}_c{btn.col}.png"
            if save_data_url(btn.image_data_url, dest):
                item.image_path = str(dest).replace("\\", "/")
                item.image = ""
                imported_icons += 1
        try:
            item.sync_pressed_style_from_released()
        except Exception:
            pass
        imported_buttons += 1

    try:
        bridge.paint_active_page(device_id)
    except Exception as err:
        syslog.warning(f"STREAMDECK: companion import paint failed: {err}")
    try:
        bridge.virtual_page_changed.emit(device_id, bridge.get_active_page(device_id))
    except Exception:
        pass

    syslog.info(
        f"STREAMDECK: companion import device={device_id[:12]} "
        f"pages={len(imported_pages)} buttons={imported_buttons} icons={imported_icons}"
    )
    return {
        "pages": len(imported_pages),
        "buttons": imported_buttons,
        "icons": imported_icons,
        "page_numbers": imported_pages,
    }


class CompanionExportTipDialog(QtWidgets.QDialog):
    """Prompt user to export Companion config; optional don't-show-again."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import from Companion")
        self.setMinimumWidth(420)
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(COMPANION_EXPORT_TIP)
        label.setWordWrap(True)
        layout.addWidget(label)
        self._again = QtWidgets.QCheckBox("Don't show this again")
        layout.addWidget(self._again)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def dont_show_again(self) -> bool:
        return bool(self._again.isChecked())


class CompanionPageSelectDialog(QtWidgets.QDialog):
    """Multi-select Companion pages for import."""

    def __init__(self, plan: CompanionImportPlan, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Companion pages to import")
        self.setMinimumSize(420, 480)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(
            QtWidgets.QLabel(
                "Choose pages to import. Appearance only (titles, icons, colors); "
                "mappings stay blank."
            )
        )

        self._list = QtWidgets.QListWidget()
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        for page in plan.pages:
            label = f"{page.number}. {page.name}"
            if page.button_count:
                label += f"  ({page.button_count} keys)"
            else:
                label += "  (empty)"
            item = QtWidgets.QListWidgetItem(label)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, page.number)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked if page.recommended else QtCore.Qt.CheckState.Unchecked
            )
            self._list.addItem(item)
        layout.addWidget(self._list, 1)

        sel_row = QtWidgets.QHBoxLayout()
        all_btn = QtWidgets.QPushButton("Select all")
        all_btn.clicked.connect(self._select_all)
        none_btn = QtWidgets.QPushButton("Select none")
        none_btn.clicked.connect(self._select_none)
        recommended_btn = QtWidgets.QPushButton("Recommended")
        recommended_btn.setToolTip("Select pages that have keys or a real name (skip empty PAGE banks)")
        recommended_btn.clicked.connect(lambda: self._select_recommended(plan))
        sel_row.addWidget(all_btn)
        sel_row.addWidget(none_btn)
        sel_row.addWidget(recommended_btn)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _select_all(self):
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(QtCore.Qt.CheckState.Checked)

    def _select_none(self):
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(QtCore.Qt.CheckState.Unchecked)

    def _select_recommended(self, plan: CompanionImportPlan):
        recommended = {p.number for p in plan.pages if p.recommended}
        for i in range(self._list.count()):
            item = self._list.item(i)
            num = item.data(QtCore.Qt.ItemDataRole.UserRole)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked if num in recommended else QtCore.Qt.CheckState.Unchecked
            )

    def selected_pages(self) -> list[int]:
        out = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                out.append(int(item.data(QtCore.Qt.ItemDataRole.UserRole)))
        return sorted(out)


def should_show_companion_export_tip() -> bool:
    return not bool(gremlin.config.Configuration()._get_data("streamdeck_companion_import_tip_hidden", False))


def set_companion_export_tip_hidden(hidden: bool = True) -> None:
    gremlin.config.Configuration()._set_data("streamdeck_companion_import_tip_hidden", bool(hidden))


def run_companion_import_wizard(parent: QtWidgets.QWidget, device_id: str) -> dict | None:
    """Full Import UX: tip → file → page select → import. Returns summary or None if cancelled."""
    if not device_id:
        QtWidgets.QMessageBox.warning(parent, "Import from Companion", "No Stream Deck device is connected.")
        return None
    if not gremlin.shared_state.current_profile:
        QtWidgets.QMessageBox.warning(parent, "Import from Companion", "Open a profile before importing.")
        return None

    if should_show_companion_export_tip():
        tip = CompanionExportTipDialog(parent)
        if tip.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        if tip.dont_show_again:
            set_companion_export_tip_hidden(True)

    path, _ = QtWidgets.QFileDialog.getOpenFileName(
        parent,
        "Select Companion configuration",
        "",
        "Companion config (*.companionconfig *.json);;JSON (*.json);;All files (*.*)",
    )
    if not path:
        return None

    try:
        plan = load_companion_plan(path)
    except Exception as err:
        QtWidgets.QMessageBox.critical(
            parent,
            "Import from Companion",
            f"Could not read Companion file:\n{err}",
        )
        return None

    if not plan.pages:
        QtWidgets.QMessageBox.information(
            parent,
            "Import from Companion",
            "No pages were found in that Companion configuration.",
        )
        return None

    picker = CompanionPageSelectDialog(plan, parent)
    if picker.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return None
    selected = picker.selected_pages()
    if not selected:
        QtWidgets.QMessageBox.information(parent, "Import from Companion", "No pages were selected.")
        return None

    try:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        summary = import_companion_pages(device_id, plan, selected)
    except Exception as err:
        QtWidgets.QMessageBox.critical(
            parent,
            "Import from Companion",
            f"Import failed:\n{err}",
        )
        syslog.exception("STREAMDECK: companion import failed")
        return None
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()

    QtWidgets.QMessageBox.information(
        parent,
        "Import from Companion",
        (
            f"Imported {summary['pages']} page(s), "
            f"{summary['buttons']} key(s), "
            f"{summary['icons']} icon(s).\n\n"
            "Mappings were left blank. Save the profile to keep the import."
        ),
    )
    return summary
