# -*- coding: utf-8; -*-
#
# Overlay label variables (%name%). OCR/label substitution comes later.

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

from gremlin.ui.ui_common import QDataPushButton

from .model import (
    OverlayScene,
    overlay_variable_name,
    overlay_variable_name_ok,
    overlay_variable_token,
)


def _alive(widget) -> bool:
    try:
        return widget is not None and Shiboken.isValid(widget)
    except Exception:
        return False


class _NameWrap(QtWidgets.QWidget):
    """% [name] % so the user only types the identifier."""

    submitted = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        prefix = QtWidgets.QLabel("%", self)
        prefix.setStyleSheet("font-weight: bold;")
        self.edit = QtWidgets.QLineEdit(self)
        self.edit.setPlaceholderText("mining_signature")
        self.edit.setClearButtonEnabled(True)
        self.edit.returnPressed.connect(self.submitted.emit)
        suffix = QtWidgets.QLabel("%", self)
        suffix.setStyleSheet("font-weight: bold;")
        layout.addWidget(prefix)
        layout.addWidget(self.edit, 1)
        layout.addWidget(suffix)

    def name(self) -> str:
        return overlay_variable_name(self.edit.text())

    def set_name(self, name: str):
        self.edit.setText(overlay_variable_name(name))


class OverlayVariableEditDialog(QtWidgets.QDialog):
    def __init__(self, row: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit variable" if row else "New variable")
        self.setModal(True)
        self.setMinimumSize(480, 320)
        self.resize(520, 360)
        self._row = dict(row or {})

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self._name = _NameWrap(self)
        self._name.set_name(self._row.get("name") or "")
        form.addRow("Name", self._name)
        self._default = QtWidgets.QLineEdit(str(self._row.get("default") or ""), self)
        self._default.setPlaceholderText("Shown until OCR or other logic sets a value")
        form.addRow("Default", self._default)
        root.addLayout(form)

        reset_box = QtWidgets.QGroupBox("Reset", self)
        reset_layout = QtWidgets.QVBoxLayout(reset_box)
        reset_layout.setSpacing(8)

        self._reset_deactivate = QtWidgets.QCheckBox("Profile deactivation", reset_box)
        self._reset_deactivate.setChecked(bool(self._row.get("reset_on_deactivate")))
        self._reset_deactivate.setToolTip("Restore this variable to its default when the profile stops.")
        reset_layout.addWidget(self._reset_deactivate)

        timer_row = QtWidgets.QHBoxLayout()
        timer_row.setSpacing(8)
        self._reset_timer = QtWidgets.QCheckBox("Timer", reset_box)
        # Legacy rows only had reset_seconds; normalize_overlay_variable sets reset_timer.
        timer_on = bool(self._row.get("reset_timer")) if "reset_timer" in self._row else (
            float(self._row.get("reset_seconds") or 0) > 0
        )
        self._reset_timer.setChecked(timer_on)
        self._reset_timer.setToolTip(
            "Restore the default after the timer expires. Any detection that writes the variable restarts the timer."
        )
        timer_row.addWidget(self._reset_timer)

        self._reset_seconds = QtWidgets.QDoubleSpinBox(reset_box)
        self._reset_seconds.setRange(0.1, 86400.0)
        self._reset_seconds.setDecimals(1)
        self._reset_seconds.setSingleStep(1.0)
        self._reset_seconds.setSuffix(" s")
        try:
            seconds = float(self._row.get("reset_seconds") or 0)
        except (TypeError, ValueError):
            seconds = 0.0
        self._reset_seconds.setValue(seconds if seconds > 0 else 5.0)
        self._reset_seconds.setToolTip("Seconds after the last write before restoring the default.")
        timer_row.addWidget(self._reset_seconds, 1)
        reset_layout.addLayout(timer_row)

        hint = QtWidgets.QLabel(
            "Unchecked options keep the current value until something else changes it.",
            reset_box,
        )
        hint.setWordWrap(True)
        reset_layout.addWidget(hint)
        root.addWidget(reset_box)

        self._reset_timer.toggled.connect(self._sync_timer_enabled)
        self._sync_timer_enabled(self._reset_timer.isChecked())

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _sync_timer_enabled(self, checked: bool):
        self._reset_seconds.setEnabled(bool(checked))

    def values(self) -> dict:
        return {
            "name": self._name.name(),
            "default": self._default.text(),
            "reset_on_deactivate": bool(self._reset_deactivate.isChecked()),
            "reset_timer": bool(self._reset_timer.isChecked()),
            "reset_seconds": float(self._reset_seconds.value()),
        }


class OverlayVariablesDialog(QtWidgets.QDialog):
    """List, add, edit, delete, and copy overlay variables."""

    def __init__(self, scene: OverlayScene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.setWindowTitle("Overlay variables")
        self.setModal(True)
        self.setMinimumSize(520, 360)
        self.resize(560, 420)

        root = QtWidgets.QVBoxLayout(self)
        hint = QtWidgets.QLabel(
            "Use %name% in a label later. Copy the token (right-click) to paste into OCR or label fields. "
            "Letters, digits, and underscore only.",
            self,
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._table = QtWidgets.QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(("Variable", "Default", "Current", "Reset"))
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self._table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_menu)
        self._table.itemDoubleClicked.connect(lambda *_: self._edit_selected())
        root.addWidget(self._table, 1)

        add_row = QtWidgets.QHBoxLayout()
        add_row.addWidget(QtWidgets.QLabel("New", self))
        self._name = _NameWrap(self)
        self._name.submitted.connect(self._add)
        add_row.addWidget(self._name, 1)
        add_btn = QDataPushButton("Add", clicked=self._add)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self.scene.changed.connect(self._reload)
        self._reload()

    def closeEvent(self, event):
        try:
            self.scene.changed.disconnect(self._reload)
        except Exception:
            pass
        super().closeEvent(event)

    @staticmethod
    def _reset_summary(row: dict) -> str:
        parts = []
        if bool(row.get("reset_on_deactivate")):
            parts.append("Deactivate")
        timer_on = bool(row.get("reset_timer")) if "reset_timer" in row else (
            float(row.get("reset_seconds") or 0) > 0
        )
        if timer_on:
            try:
                seconds = float(row.get("reset_seconds") or 0)
            except (TypeError, ValueError):
                seconds = 0.0
            parts.append(f"{seconds:g} s" if seconds > 0 else "Timer")
        return ", ".join(parts) if parts else "Never"

    def _reload(self):
        if not _alive(self._table):
            return
        selected = self._selected_id()
        self._table.setRowCount(0)
        for row in self.scene.variables:
            index = self._table.rowCount()
            self._table.insertRow(index)
            token = overlay_variable_token(row.get("name"))
            values = (
                token,
                str(row.get("default") or "") or "—",
                str(row.get("value") or "") or "—",
                self._reset_summary(row),
            )
            for col, text in enumerate(values):
                item = QtWidgets.QTableWidgetItem(text)
                if col == 0:
                    item.setData(QtCore.Qt.UserRole, str(row.get("id") or ""))
                self._table.setItem(index, col, item)
            if str(row.get("id") or "") == selected:
                self._table.selectRow(index)

    def _selected_id(self) -> str:
        items = self._table.selectedItems()
        if not items:
            return ""
        first = self._table.item(items[0].row(), 0)
        return str(first.data(QtCore.Qt.UserRole) or "") if first else ""

    def _selected_row(self) -> dict | None:
        return self.scene.overlay_variable_by_id(self._selected_id())

    def _on_menu(self, pos: QtCore.QPoint):
        row = self._selected_row()
        if row is None:
            index = self._table.indexAt(pos)
            if index.isValid():
                self._table.selectRow(index.row())
                row = self._selected_row()
        if row is None:
            return
        menu = QtWidgets.QMenu(self)
        copy_act = menu.addAction("Copy %name%")
        copy_act.setText(f"Copy {overlay_variable_token(row.get('name'))}")
        edit_act = menu.addAction("Edit…")
        delete_act = menu.addAction("Delete")
        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen is copy_act:
            self._copy(row)
        elif chosen is edit_act:
            self._edit(row)
        elif chosen is delete_act:
            self._delete(row)

    def _copy(self, row: dict):
        token = overlay_variable_token(row.get("name"))
        if not token:
            return
        QtWidgets.QApplication.clipboard().setText(token)
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), f"Copied {token}", self)

    def _add(self):
        name = self._name.name()
        if not overlay_variable_name_ok(name):
            QtWidgets.QMessageBox.warning(
                self,
                "Overlay variables",
                "Use letters, digits, and underscore. The name must start with a letter or underscore.",
            )
            return
        if self.scene.overlay_variable_by_name(name):
            QtWidgets.QMessageBox.warning(self, "Overlay variables", f"%{name}% already exists.")
            return
        added = self.scene.add_overlay_variable(name)
        if added:
            self._name.edit.clear()
            self._name.edit.setFocus()

    def _edit_selected(self):
        row = self._selected_row()
        if row:
            self._edit(row)

    def _edit(self, row: dict):
        dialog = OverlayVariableEditDialog(row, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        values = dialog.values()
        if not overlay_variable_name_ok(values["name"]):
            QtWidgets.QMessageBox.warning(
                self,
                "Overlay variables",
                "Use letters, digits, and underscore. The name must start with a letter or underscore.",
            )
            return
        if not self.scene.update_overlay_variable(str(row.get("id") or ""), **values):
            QtWidgets.QMessageBox.warning(self, "Overlay variables", "Could not save that name (duplicate or invalid).")

    def _delete(self, row: dict):
        token = overlay_variable_token(row.get("name"))
        answer = QtWidgets.QMessageBox.question(
            self,
            "Overlay variables",
            f"Delete {token}?",
        )
        if answer == QtWidgets.QMessageBox.Yes:
            self.scene.remove_overlay_variable(str(row.get("id") or ""))
