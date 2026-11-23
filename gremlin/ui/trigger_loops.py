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


"""Confirmation for potential trigger feedback in a profile."""

from PySide6 import QtCore, QtWidgets

from gremlin.ui.ui_common import QDataLabel, QDataPushButton, QRememberDialog, QScrollableWidget, getHContainer


class TriggerLoopsDialog(QRememberDialog):
    def __init__(self, loops, parent=None):
        super().__init__("TriggerLoopsDialog", width=680, height=410, parent=parent)
        self.setWindowTitle("Possible trigger loops")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)
        message = QDataLabel("These inputs can retrigger each other. Conditions or state changes may stop a loop during execution.")
        message.setWordWrap(True)
        layout.addWidget(message)

        groups = [f"Modes: {', '.join(modes)}\n" + "\n".join(f"• {name}" for name in inputs) for modes, inputs in loops]
        details = QDataLabel("\n\n".join(groups))
        details.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        details.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        details.setWordWrap(True)
        layout.addWidget(QScrollableWidget(details, horizontal_scroll=False))

        proceed = QDataPushButton("Continue", clicked=self.accept)
        proceed.setAutoDefault(False)
        abort = QDataPushButton("Abort Start", clicked=self.reject)
        abort.setDefault(True)
        abort.setFocus()
        layout.addWidget(getHContainer(["||", abort, proceed], widget_only=True))


def confirm_trigger_loops(loops, parent=None):
    dialog = TriggerLoopsDialog(loops, parent=parent)
    try:
        return dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
    finally:
        dialog.deleteLater()
