# Based on original Joystick Gremlin work by Lionel Ott and other contributors - Joystick Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Review and apply input device GUID and virtual output changes."""

from lxml import etree
from PySide6 import QtCore, QtWidgets

import gremlin.shared_state
from gremlin.device_remap import (
    guid_key,
    maestro_output_id,
    output_device_sources,
    remap_output_devices,
    remap_profile_devices,
    suggest_target,
)
from gremlin.ui.ui_common import (
    Color,
    MessageBoxYesNo,
    QDataCheckbox,
    QDataComboBox,
    QDataPushButton,
    QInfoBox,
    QRememberDialog,
    getHContainer,
)


class ProfileDeviceRemapDialog(QRememberDialog):
    def __init__(self, profile_xml, devices, apply_changes, parent=None):
        super().__init__(self.__class__.__name__, width=1100, height=600, parent=parent)
        self.setWindowTitle("Remap Profile Devices")
        self.setModal(True)
        # self.resize(1100, 600)
        self._root = etree.fromstring(profile_xml)
        self._apply_changes = apply_changes
        self._rows = []
        self._output_rows = []
        self._devices = list(devices)
        self._output_changes = []
        dark = gremlin.shared_state.is_dark_theme

        targets = sorted(
            (device for device in self._devices if device.connected and not device.is_virtual),
            key=lambda device: (device.name.casefold(), str(device.device_guid)),
        )
        connected = {guid_key(device.device_guid) for device in targets}
        layout = QtWidgets.QVBoxLayout(self)
        info_widget = QInfoBox(
            "Remap saved input and output devices in the sections below. "
            "Matches are suggested for disconnected inputs and vJoy outputs. "
            "Select Apply beside each device to change and choose its target. "
            "Output changes include startup values and preserve axis, button and hat numbers. "
            "Current edits are saved, a backup is created, and the profile is reloaded."
        )

        layout.addWidget(info_widget)
        select_all_widget = QDataPushButton("Select All")
        select_none_widget = QDataPushButton("Select None")
        select_all_widget.clicked.connect(lambda: self._select(True))
        select_none_widget.clicked.connect(lambda: self._select(False))
        layout.addWidget(getHContainer([select_all_widget, select_none_widget], widget_only=True))
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        sections = QtWidgets.QVBoxLayout(content)

        # input grid
        input_section = QtWidgets.QGroupBox("Input devices")
        input_section.setObjectName("inputDevices")
        accent = "#0f8633" if dark else "#0e5016"
        input_section.setStyleSheet(
            f"QGroupBox#inputDevices {{ border: 1px solid {accent}; border-radius: 4px; margin-top: 10px; padding-top: 12px; }}"
            f"QGroupBox#inputDevices::title {{ color: {accent}; subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        grid = QtWidgets.QGridLayout(input_section)
        sections.addWidget(input_section)
        for column, title in enumerate(("Apply", "Profile device / old GUID", "Connected device / new GUID")):
            grid.addWidget(QtWidgets.QLabel(title), 0, column)
        sources = [
            node for node in self._root.findall("./devices/device") if node.get("type", "").casefold() == "joystick"
        ]
        sources.sort(key=lambda node: (guid_key(node.get("device-guid")) in connected, node.get("name", "").casefold()))
        for index, source in enumerate(sources, 1):
            old = source.get("device-guid")
            missing = guid_key(old) not in connected
            check = QDataCheckbox()
            label = QtWidgets.QLabel(f"{source.get('name')} ({'disconnected' if missing else 'connected'})\n{old}")
            label.setStyleSheet(f"color: {accent};")
            label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            combo = QDataComboBox()
            combo.addItem("Choose a target device...", None)
            for device in targets:
                combo.addItem(f"{device.name} [{device.device_guid}]", device)
            suggested = suggest_target(source, targets) if missing else None
            if suggested is not None:
                combo.setCurrentIndex(targets.index(suggested) + 1)
                check.setChecked(True)
            self._rows.append((source, check, combo))
            check.toggled.connect(self._validate)
            combo.currentIndexChanged.connect(self._validate)
            grid.addWidget(check, index, 0)
            grid.addWidget(label, index, 1)
            grid.addWidget(combo, index, 2, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
        grid.setRowStretch(len(sources) + 1, 1)
        grid.setColumnStretch(2, 1)
        output_section = QtWidgets.QGroupBox("Output devices")
        output_section.setObjectName("outputDevices")

        accent = "#78c5ff" if dark else "#075a9c"
        output_section.setStyleSheet(
            f"QGroupBox#outputDevices {{ border: 1px solid {accent}; border-radius: 4px; margin-top: 10px; padding-top: 12px; }}"
            f"QGroupBox#outputDevices::title {{ color: {accent}; subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        output_grid = QtWidgets.QGridLayout(output_section)
        for column, title in enumerate(("Apply", "Output device / saved identity", "Target gex output device")):
            output_grid.addWidget(QtWidgets.QLabel(title), 0, column)
        output_targets = sorted(
            (device for device in self._devices if maestro_output_id(device) is not None),
            key=lambda device: (maestro_output_id(device), str(device.device_guid)),
        )
        outputs = output_device_sources(self._root, self._devices)
        for index, source in enumerate(outputs, 1):
            check = QDataCheckbox()
            check.setToolTip("Remap this output device, including its saved startup values.")
            identity = source["device-guid"] or (
                f"vJoy ID {source['key']}" if source["provider"] == "vjoy" else source["key"]
            )
            label = QtWidgets.QLabel(f"Output: {source['name']}\n{identity}")
            label.setStyleSheet(f"color: {accent};")
            label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            combo = QDataComboBox()
            combo.addItem("Choose a target gex output...", None)
            for device in output_targets:
                combo.addItem(f"{device.name} [{device.device_guid}]", device)
            matches = [
                device
                for device in output_targets
                if (
                    maestro_output_id(device) == source["key"]
                    if source["provider"] == "vjoy"
                    else guid_key(device.device_guid) == guid_key(source["device-guid"])
                )
            ]
            if len(matches) == 1:
                combo.setCurrentIndex(output_targets.index(matches[0]) + 1)
            self._output_rows.append((source, check, combo))
            check.toggled.connect(self._validate)
            combo.currentIndexChanged.connect(self._validate)
            output_grid.addWidget(check, index, 0)
            output_grid.addWidget(label, index, 1)
            output_grid.addWidget(combo, index, 2, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
        if not outputs:
            output_grid.addWidget(
                QtWidgets.QLabel("No virtual output devices are referenced in this profile."), 1, 1, 1, 2
            )
        output_grid.setColumnStretch(2, 1)
        sections.addWidget(output_section)
        sections.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self._status = QtWidgets.QLabel()
        self._status.setWordWrap(True)
        self._status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        layout.addWidget(self._status)
        self._apply_button = QDataPushButton("Apply and Reload")
        self._apply_button.clicked.connect(self._apply_confirmation)
        cancel = QDataPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        layout.addWidget(getHContainer([self._apply_button, cancel], left_stretch=True, widget_only=True))
        self._validate()

    def _apply_confirmation(self):
        # This method can be used to show a confirmation dialog before applying changes
        # For now, it simply returns True to proceed
        MessageBoxYesNo(prompt="Are you sure you want to apply the changes?", callback=self._apply)

    def _select(self, checked):
        for _, check, _ in self._rows + self._output_rows:
            blocker = QtCore.QSignalBlocker(check)
            check.setChecked(checked)
            blocker.unblock()
        self._validate()

    def _replacement_root(self):
        self._output_changes = []
        self._validation_message = "Select an input or output device and choose its target."
        replacements = {}
        for source, check, combo in self._rows:
            if not check.isChecked():
                continue
            target = combo.currentData()
            if target is None:
                self._validation_message = f'Choose a target for "{source.get("name")}" or deselect it.'
                return None
            if guid_key(source.get("device-guid")) == guid_key(target.device_guid):
                self._validation_message = f'Choose a different device for "{source.get("name")}" or deselect it.'
                return None
            replacements[source.get("device-guid")] = (str(target.device_guid), target.name)
        output_replacements = {}
        for source, check, combo in self._output_rows:
            if not check.isChecked():
                continue
            target = combo.currentData()
            if target is None:
                self._validation_message = f'Choose a target gex output for "{source["name"]}" or deselect it.'
                return None
            if guid_key(source["device-guid"]) is not None and guid_key(source["device-guid"]) == guid_key(
                target.device_guid
            ):
                self._validation_message = f'Choose a different output device for "{source["name"]}" or deselect it.'
                return None
            output_replacements[source["key"]] = target
        root = self._root
        if output_replacements:
            root, self._output_changes = remap_output_devices(root, self._devices, output_replacements)
        if replacements:
            return remap_profile_devices(root, replacements)
        if self._output_changes:
            return root
        return None

    def _validate(self, *_args):
        try:
            root = self._replacement_root()
        except ValueError as error:
            self._status.setText(str(error))
            self._apply_button.setEnabled(False)
        else:
            if root is None:
                self._status.setText(self._validation_message)
                self._apply_button.setEnabled(False)
                return
            count = sum(check.isChecked() for _, check, _ in self._rows)
            self._status.setText(
                f"Ready to remap {count} input device(s) and {len(self._output_changes)} output device(s). "
                "Input numbers are preserved; choose targets with sufficient axes, buttons and hats."
                + ("\n" + "\n".join(self._output_changes) if self._output_changes else "")
            )
            self._apply_button.setEnabled(True)

    def _apply(self, result):
        if not result:
            return
        try:
            root = self._replacement_root()
            if root is None:
                self._status.setText(self._validation_message)
                self._apply_button.setEnabled(False)
                return
            self._apply_changes(root)
        except Exception as error:
            self._status.setText(f"Could not remap the profile: {error}")
            return
        self.accept()
