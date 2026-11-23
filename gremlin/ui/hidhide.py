# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
#
# Written for Gremlin Ex by Muchimi
# Some portions are derived from the original 2019 Joystick Gremlin by Lionel Ott and other contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.


"""Shared HidHide device editor for Tools and global options.

as of m77, this uses the new IOCTL based driver hooks in hidhide.py

"""

import logging
import sys

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

from gremlin import hidhide, shared_state
from gremlin.ui.ui_common import BaseDialogUi, QDataCheckbox, QDataLabel, QDataPushButton, QRememberDialog, getHContainer
from gremlin.worker import WorkManager

log = logging.getLogger("system")


def offer_startup_access():
    """Offer HidHide access before DirectInput initializes."""
    if not hidhide.is_installed():
        return
    client = hidhide.HidHide()
    try:
        if client.gex_allowed():
            return
    except OSError, RuntimeError:
        log.exception("Could not check GEX access in HidHide at startup")
        return

    dialog = HidHideStartupDialog(client)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()


class HidHideStartupDialog(QRememberDialog):
    def __init__(self, client):
        super().__init__("HidHideStartupDialog", width=480, height=200)
        self._client = client
        self.setWindowTitle("Allow GEX through HidHide?")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_QuitOnClose, False)

        layout = QtWidgets.QVBoxLayout(self)
        description = QDataLabel("HidHide is installed and GEX cannot see controllers when they are hidden. Allow this executable to read hidden devices?")
        description.setWordWrap(True)
        layout.addWidget(description)
        executable = QDataLabel(sys.executable)
        executable.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        executable.setWordWrap(True)
        layout.addWidget(executable)

        self._error = QDataLabel()
        self._error.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        self._error.hide()
        layout.addWidget(self._error)

        allow = QDataPushButton(
            "Whitelist (allow) GEX", clicked=self._allow, tooltip="Ensures the current GEX executable is allowed by HID Hide to view and read hidden devices."
        )
        allow.setAutoDefault(False)
        skip = QDataPushButton(
            "Continue without access",
            clicked=self.reject,
            tooltip="Continue without allowing GEX to access hidden devices. This may significantly limit functionality.",
        )
        skip.setDefault(True)
        skip.setFocus()
        layout.addStretch()
        layout.addWidget(getHContainer(["||", allow, skip], widget_only=True))

    def _allow(self):
        try:
            self._client.allow_gex()
            if not self._client.gex_allowed():
                raise RuntimeError("HidHide still reports that GEX cannot read hidden devices.")
        except (OSError, RuntimeError) as error:
            log.exception("Could not allow GEX to read hidden HidHide devices")
            self._error.setText(str(error))
            self._error.show()
        else:
            self.accept()


class HidHideDeviceWidget(QtWidgets.QWidget):
    _completed = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = hidhide.HidHide()
        self._snapshot = None
        self._desired = {}
        self._bulk_selected = set()
        self._busy = False
        self._loaded = False
        self._completed.connect(self._show_result, QtCore.Qt.ConnectionType.QueuedConnection)

        layout = QtWidgets.QVBoxLayout(self)
        self._description = QDataLabel("Select devices to hide, then click Apply. Bulk hide skips virtual outputs used by the loaded profile.")
        self._description.setWordWrap(True)
        layout.addWidget(self._description)

        self._enabled = QDataCheckbox("Enable device hiding", tooltip="Enable or disable HidHide device hiding.")
        self._enabled.toggled.connect(self._update_controls)
        self._show_all = QDataCheckbox("Show all HID devices", tooltip="Show all HID devices, including non controllers. ")
        self._show_all.toggled.connect(self._populate)
        layout.addWidget(getHContainer([self._enabled, self._show_all], widget_only=True))

        self._table = QtWidgets.QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(("Device", "Role", "Input API", "Hide"))
        self._table.verticalHeader().hide()
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemChanged.connect(self._device_checked)
        layout.addWidget(self._table)

        self._status = QDataLabel()
        self._status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._bulk = QDataPushButton("Select controllers to hide", clicked=self._select_controllers)
        self._bulk.setToolTip("Select detected physical joysticks and gamepads and unused vJoy and Maestro devices.")
        self._allow = QDataPushButton(
            "Whitelist (allow) GEX",
            clicked=self._allow_gex,
            tooltip="Ensures the current GEX executable is allowed by HID Hide to view and read hidden devices.",
        )
        self._allow.setToolTip(f"Allow this executable to read hidden devices in HidHide.\n{sys.executable}")
        self._refresh = QDataPushButton("Reload", clicked=self._load, tooltip="Reload HidHide configuration and discard unapplied edits.")
        self._refresh.setToolTip("Reload HidHide configuration and discard unapplied edits.")
        self._apply = QDataPushButton("Apply", clicked=self._apply_changes, tooltip="Apply the changes to the HidHide configuration.")
        layout.addWidget(getHContainer([self._bulk, self._allow, "||", self._refresh, self._apply], widget_only=True))
        self._update_controls()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self._load()

    def _load(self):
        self._request()

    def _request(self, change=None, *, keep_edits=False):
        if self._busy:
            return
        self._busy = True
        self._status.setText("Reading HidHide configuration…" if change is None else "Updating HidHide configuration…")
        self._update_controls()
        profile = shared_state.current_profile
        master_mode = shared_state.master_mode
        client = self._client

        def run(_):
            error = ""
            if change is not None:
                try:
                    error = change(client, profile, master_mode) or ""
                except (OSError, RuntimeError) as exc:
                    error = str(exc)
            try:
                snapshot = hidhide.read_devices(client, profile, master_mode)
            except Exception as exc:
                log.exception("Could not read HidHide devices")
                return None, "\n".join(filter(None, (error, str(exc)))), keep_edits
            return snapshot, error, keep_edits

        def complete(result, _):
            if Shiboken.isValid(self):
                self._completed.emit(result)

        WorkManager().submit(run, complete_callback=complete)

    @QtCore.Slot(object)
    def _show_result(self, result):
        self._busy = False
        previous = self._snapshot
        self._snapshot, error, keep_edits = result
        if self._snapshot is None:
            self._desired.clear()
            self._bulk_selected.clear()
            self._status.setText(error)
            self._enabled.setChecked(False)
        else:
            desired = self._snapshot.hidden.copy()
            active = self._snapshot.active
            if keep_edits:
                desired.update((key, self._desired[key]) for key in self._desired.keys() - previous.hidden.keys())
                for key in previous.hidden.keys() - self._desired.keys():
                    desired.pop(key, None)
                if self._enabled.isChecked() != previous.active:
                    active = self._enabled.isChecked()
            self._desired = desired
            if not keep_edits:
                self._bulk_selected.clear()
            self._enabled.setChecked(active)
            self._status.setText(
                error
                or ("GEX is whitelisted." if self._snapshot.gex_allowed else "Use Allow GEX to keep these controllers available to GEX when hiding is enabled.")
            )
        self._populate()

    def _populate(self):
        rows = ()
        if self._snapshot:
            rows = [
                row
                for row in self._snapshot.devices
                if self._show_all.isChecked() or row.gaming or any(path.casefold() in self._snapshot.hidden for path in row.paths)
            ]
        with QtCore.QSignalBlocker(self._table):
            self._table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                name = QtWidgets.QTableWidgetItem(row.name)
                name.setToolTip("\n".join(row.paths))
                self._table.setItem(index, 0, name)
                role = QtWidgets.QTableWidgetItem(row.role)
                role.setData(QtCore.Qt.ItemDataRole.UserRole, row.is_virtual)
                self._table.setItem(index, 1, role)
                api = QtWidgets.QTableWidgetItem(" / ".join(row.apis) or "—")
                if not row.apis:
                    api.setToolTip("No game-controller API detected for this device.")
                self._table.setItem(index, 2, api)
                check = QtWidgets.QTableWidgetItem()
                check.setFlags(check.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                check.setData(QtCore.Qt.ItemDataRole.UserRole, row.paths)
                self._table.setItem(index, 3, check)
        self._update_checks()

    def _update_checks(self):
        from gremlin.maestro import MaestroDialog

        states = QtCore.Qt.CheckState
        dark = shared_state.is_dark_theme
        physical_color = QtGui.QColor(MaestroDialog.JOYSTICK_DARK_COLOR if dark else MaestroDialog.JOYSTICK_LIGHT_COLOR)
        virtual_color = QtGui.QColor(MaestroDialog.FAILOVER_JOYSTICK_DARK_COLOR if dark else MaestroDialog.FAILOVER_JOYSTICK_LIGHT_COLOR)
        with QtCore.QSignalBlocker(self._table):
            for index in range(self._table.rowCount()):
                check = self._table.item(index, 3)
                paths = check.data(QtCore.Qt.ItemDataRole.UserRole)
                hidden = sum(path.casefold() in self._desired for path in paths)
                check.setCheckState(states.Checked if hidden == len(paths) else states.PartiallyChecked if hidden else states.Unchecked)
                role = self._table.item(index, 1)
                virtual = role.data(QtCore.Qt.ItemDataRole.UserRole)
                if virtual is None:
                    continue
                attention = not virtual and hidden < len(paths)
                if not virtual:
                    status = " · Partially hidden" if attention and hidden else " · Not hidden" if attention else ""
                    role.setText(f"Physical controller{status}")
                fill = virtual_color if virtual else physical_color
                text = QtGui.QColor("white" if virtual or dark else "black")
                font = self._table.font()
                font.setBold(attention)
                for column in range(self._table.columnCount()):
                    item = self._table.item(index, column)
                    colored = column == 1 or attention
                    item.setBackground(QtGui.QBrush(fill) if colored else QtGui.QBrush())
                    item.setForeground(QtGui.QBrush(text) if colored else QtGui.QBrush())
                    item.setFont(font)
        self._update_controls()

    def _device_checked(self, item):
        paths = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not paths:
            return
        hide = item.checkState() == QtCore.Qt.CheckState.Checked
        for path in paths:
            self._bulk_selected.discard(path.casefold())
            if hide:
                self._desired[path.casefold()] = path
            else:
                self._desired.pop(path.casefold(), None)
        self._update_checks()

    def _select_controllers(self):
        for row in self._snapshot.devices:
            if row.bulk_hide:
                for path in row.paths:
                    key = path.casefold()
                    if key not in self._desired:
                        self._bulk_selected.add(key)
                        self._desired[key] = path
        self._update_checks()

    def _update_controls(self):
        ready = self._snapshot is not None and not self._busy
        self._table.setEnabled(ready)
        self._enabled.setEnabled(ready)
        self._show_all.setEnabled(ready)
        self._refresh.setEnabled(not self._busy)
        self._bulk.setEnabled(ready and any(row.bulk_hide for row in self._snapshot.devices))
        self._allow.setEnabled(ready and not self._snapshot.gex_allowed)
        dirty = ready and (self._desired.keys() != self._snapshot.hidden.keys() or self._enabled.isChecked() != self._snapshot.active)
        self._apply.setEnabled(dirty)

    def _apply_changes(self):
        hidden = self._snapshot.hidden
        changes = {self._desired[key]: True for key in self._desired.keys() - hidden.keys()}
        changes.update((hidden[key], False) for key in hidden.keys() - self._desired.keys())
        active = self._enabled.isChecked()
        previous_active = self._snapshot.active
        bulk_selected = self._bulk_selected.copy()

        def apply(client, profile, master_mode):
            eligible = bulk_selected
            if bulk_selected:
                fresh = hidhide.read_devices(client, profile, master_mode)
                eligible = {path.casefold() for row in fresh.devices if row.bulk_hide for path in row.paths}
            skipped = bulk_selected - eligible
            client.apply({path: hide for path, hide in changes.items() if path.casefold() not in skipped}, active, previous_active)
            if skipped:
                return "Some bulk selections were skipped because the devices or their output assignments changed."

        self._request(apply)

    def _allow_gex(self):
        self._request(lambda client, *_: client.allow_gex(), keep_edits=True)


class HidHideDialog(BaseDialogUi):
    def __init__(self, parent=None):
        super().__init__("HidHideDialog", width=860, height=560, parent=parent)
        self.setWindowTitle("HidHide")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(HidHideDeviceWidget(self))
        close = QDataPushButton("Close", clicked=self.accept)
        layout.addWidget(getHContainer(["||", close], widget_only=True))
