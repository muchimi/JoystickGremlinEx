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


"""Report missing mode references that prevent profile activation."""

from PySide6 import QtCore, QtWidgets

from gremlin.ui.ui_common import Buttons, QDataLabel, QRememberDialog, QScrollableWidget, getHContainer


def show_missing_profile_modes(missing_modes, parent=None):
    dialog = QRememberDialog("MissingProfileModesDialog", width=680, height=410, parent=parent)
    dialog.setWindowTitle("Profile Start Aborted")
    dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_QuitOnClose, False)

    layout = QtWidgets.QVBoxLayout(dialog)
    message = QDataLabel("These modes are missing from the profile's mode tree. Fix the listed references before starting the profile.")
    message.setWordWrap(True)
    layout.addWidget(message)

    groups = [f"{mode}\n" + "\n".join(f"• {location}" for location in locations)
              for mode, locations in missing_modes.items()]
    details = QDataLabel("\n\n".join(groups))
    details.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    details.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
    details.setWordWrap(True)
    layout.addWidget(QScrollableWidget(details, horizontal_scroll=False), stretch=1)

    ok_button = Buttons.getOkWidget(label="OK", no_keyboard=False)
    ok_button.clicked.connect(dialog.accept)
    layout.addWidget(getHContainer(["||", ok_button], widget_only=True))
    ok_button.setDefault(True)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
