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

import qtawesome as qta
from lxml import etree
from PySide6 import QtCore, QtWidgets

import gremlin.shared_state
from gremlin.device_remap import (
    guid_key,
    is_maestro_output,
    maestro_output_id,
    native_vjoy_output_id,
    output_device_sources,
    remap_output_devices,
    remap_profile_devices,
    suggest_target,
)
from gremlin.ui.ui_common import (
    MessageBoxYesNo,
    QDataCheckbox,
    QDataPushButton,
    QHtmlDataComboBox,
    QInfoBox,
    QRememberDialog,
    getHContainer,
)


class ProfileDeviceRemapDialog(QRememberDialog):
    def __init__(self, profile_xml, devices, apply_changes, parent=None, *, startup_missing=None, saved_root=None):
        super().__init__(self.__class__.__name__, width=1100, height=600, parent=parent)
        self.setWindowTitle("Remap Profile Devices")
        self.setModal(True)
        # self.resize(1100, 600)
        self._root = etree.fromstring(profile_xml)
        self._saved_root = saved_root
        self._apply_changes = apply_changes
        self._rows = []
        self._output_rows = []
        self._devices = list(devices)
        self._output_changes = []
        startup = startup_missing is not None
        if startup:
            startup_missing = {key if isinstance(key, int) else guid_key(key) for key in startup_missing}
            startup_missing.discard(None)
        dark = gremlin.shared_state.is_dark_theme
        self._device_status_icons = {
            "deviceStatusConnected": (
                qta.icon("mdi.check-circle-outline", color="#58d68d" if dark else "#16753c").pixmap(20, 20),
                "Connected. No change needed.",
            ),
            "deviceStatusSuggested": (
                qta.icon("mdi.alert-outline", color="#ffb454" if dark else "#ad5100").pixmap(20, 20),
                "Device unavailable. A replacement is selected.",
            ),
            "deviceStatusManual": (
                qta.icon("mdi.help-circle-outline", color="#8ac5ff" if dark else "#225fa3").pixmap(20, 20),
                "No automatic match. You can choose a replacement device.",
            ),
        }

        connected_inputs = [device for device in self._devices if device.connected and not device.is_virtual]
        targets = sorted(
            (device for device in connected_inputs if not (startup and getattr(device, "disabled", False))),
            key=lambda device: (device.name.casefold(), str(device.device_guid)),
        )
        inputs_by_guid = {guid_key(device.device_guid): device for device in connected_inputs}
        layout = QtWidgets.QVBoxLayout(self)
        info_widget = QInfoBox(
            "Some devices referenced by the profile are missing. "
            "GEX found connected replacements for these missing devices. "
            "Apply and reload to update the profile, then activate it again. "
            "Cancel to continue startup with the current mappings."
            if startup
            else "Remap saved input and output devices in the sections below. "
            "Connected replacements are selected when a match is found. "
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
        for column, title in enumerate(("Status", "Apply", "Profile device / old GUID", "Connected device / new GUID")):
            grid.addWidget(QtWidgets.QLabel(title), 0, column)
        sources = [node for node in self._root.findall("./devices/device") if node.get("type", "").casefold() == "joystick"]
        if saved_root is not None:
            self._restore_referenced_inputs(sources, inputs_by_guid.keys())
        sources.sort(key=lambda node: (guid_key(node.get("device-guid")) in inputs_by_guid, node.get("name", "").casefold()))
        for source in sources:
            old = source.get("device-guid")
            current = inputs_by_guid.get(guid_key(old))
            suggested = suggest_target(source, targets) if current is None else None
            choices = [current, *targets] if current is not None and current not in targets else targets
            check, combo = self._add_device_row(
                grid,
                len(self._rows) + 1,
                source,
                f"<b>{source.get('name')}</b><br>[{old}]",
                accent,
                "Choose a target device...",
                choices,
                current,
                suggested,
            )
            self._rows.append((source, check, combo))
        grid.setRowStretch(len(self._rows) + 1, 1)
        grid.setColumnStretch(3, 1)
        sections.addWidget(input_section)
        input_section.setVisible(not startup or bool(self._rows))
        output_section = QtWidgets.QGroupBox("Output devices")
        output_section.setObjectName("outputDevices")

        accent = "#78c5ff" if dark else "#075a9c"
        output_section.setStyleSheet(
            f"QGroupBox#outputDevices {{ border: 1px solid {accent}; border-radius: 4px; margin-top: 10px; padding-top: 12px; }}"
            f"QGroupBox#outputDevices::title {{ color: {accent}; subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        output_grid = QtWidgets.QGridLayout(output_section)
        for column, title in enumerate(("Status", "Apply", "Output device / saved identity", "Target output device")):
            output_grid.addWidget(QtWidgets.QLabel(title), 0, column)
        output_targets = sorted(
            (device for device in self._devices if is_maestro_output(device)),
            key=lambda device: (maestro_output_id(device) or 17, device.name.casefold(), str(device.device_guid)),
        )
        outputs = output_device_sources(self._root, self._devices, saved_root=saved_root)
        preselected_outputs = set()
        for source in outputs:
            choices, current, suggested = self._output_choices(source, output_targets, startup_missing)
            suggested_guid = guid_key(suggested.device_guid) if suggested is not None else None
            apply_suggestion = suggested_guid not in preselected_outputs
            if suggested_guid is not None:
                preselected_outputs.add(suggested_guid)
            old = source["device-guid"] or (f"vJoy ID {source['key']}" if source["provider"] == "vjoy" else source["key"])
            check, combo = self._add_device_row(
                output_grid,
                len(self._output_rows) + 1,
                source,
                f"<b>{source['name']}</b><br>[{old}]",
                accent,
                "Choose a target output...",
                choices,
                current,
                suggested,
                apply_suggestion=apply_suggestion,
            )
            check.setToolTip("Remap this output device, including its saved startup values.")
            self._output_rows.append((source, check, combo))
        if not startup and not self._output_rows:
            output_grid.addWidget(QtWidgets.QLabel("No virtual output devices are referenced in this profile."), 1, 2, 1, 2)
        output_grid.setColumnStretch(3, 1)
        sections.addWidget(output_section)
        output_section.setVisible(not startup or bool(self._output_rows))
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

    @property
    def has_matches(self):
        return any(check.isChecked() for _, check, _ in self._rows + self._output_rows)

    def _add_device_row(self, grid, row, source, text, accent, placeholder, choices, current, suggested, *, apply_suggestion=True):
        if current is not None:
            status_name = "deviceStatusConnected"
        elif suggested is not None:
            status_name = "deviceStatusSuggested"
        else:
            status_name = "deviceStatusManual"
        pixmap, description = self._device_status_icons[status_name]
        if not choices:
            description = "No replacement devices are connected."
        elif suggested is not None and not apply_suggestion:
            description = "Another output already has this target selected. Apply one row at a time."
        status = QtWidgets.QLabel()
        status.setObjectName(status_name)
        status.setPixmap(pixmap)
        status.setToolTip(description)
        status.setAccessibleName(description)
        grid.addWidget(status, row, 0, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        check = QDataCheckbox()
        check.setChecked(suggested is not None and apply_suggestion)
        check.toggled.connect(self._validate)
        grid.addWidget(check, row, 1)

        label = QtWidgets.QLabel(text)
        label.setStyleSheet(f"color: {accent};")
        label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(label, row, 2)

        combo = QHtmlDataComboBox()
        combo.addItem(placeholder, None)
        for device in choices:
            combo.addItem(f"<b>{device.name}</b> [{device.device_guid}]", device)
        default = current if current is not None else suggested
        if default is not None:
            combo.setCurrentIndex(choices.index(default) + 1)
        combo.currentIndexChanged.connect(lambda _: self._target_changed(source, check, combo))
        grid.addWidget(combo, row, 3, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
        return check, combo

    def _target_changed(self, source, check, combo):
        target = combo.currentData()
        with QtCore.QSignalBlocker(check):
            check.setChecked(target is not None and not self._is_current_device(source, target))
        self._validate()

    def _restore_referenced_inputs(self, sources, connected):
        # Serialization can omit device declarations that have no mappings of
        # their own, even when a condition or another input refers to their GUID.
        declared = {guid_key(node.get("device-guid")) for node in sources}
        missing = {}
        for node in self._saved_root.findall("./devices/device"):
            key = guid_key(node.get("device-guid"))
            if key and node.get("type", "").casefold() == "joystick" and key not in declared | connected:
                missing[key] = node
        if not missing:
            return
        references = {guid_key(value) for node in self._root.iter() if isinstance(node.tag, str) for value in node.attrib.values()}
        devices = self._root.find("devices")
        if devices is not None:
            for key in missing.keys() & references:
                sources.append(etree.SubElement(devices, "device", dict(missing[key].attrib)))

    def _output_choices(self, source, targets, startup_missing):
        old_guid = guid_key(source["device-guid"])
        if source["provider"] == "vjoy":
            index = source["key"]
            natives = [device for device in self._devices if native_vjoy_output_id(device) == index]
            choices = natives + targets
            current = next((device for device in natives if old_guid == guid_key(device.device_guid)), None)
            if current is not None:
                return choices, current, None
            if len(natives) == 1:
                return (choices, natives[0], None) if old_guid is None else (choices, None, natives[0])
            if startup_missing is not None and index not in startup_missing and old_guid not in startup_missing:
                return choices, None, None
            matches = [device for device in targets if maestro_output_id(device, require_hid_order=False) == index]
            return choices, None, matches[0] if len(matches) == 1 else None

        current = next((device for device in targets if guid_key(device.device_guid) == old_guid), None)
        if current is not None or old_guid is None:
            return targets, current, None
        suggested_guid = guid_key(source.get("suggested-guid"))
        matches = [
            device
            for device in targets
            if guid_key(device.device_guid) == suggested_guid or any(guid_key(guid) == old_guid for guid in device.data.get("maestro_native_guids", ()))
        ]
        if matches:
            return targets, None, matches[0] if len(matches) == 1 else None
        suggested = suggest_target(source, targets) if source["name"] != "Unavailable output" else None
        return targets, None, suggested

    @staticmethod
    def _is_current_device(source, target):
        old_guid = guid_key(source.get("device-guid"))
        if old_guid is not None:
            return old_guid == guid_key(target.device_guid)
        return source.get("provider") == "vjoy" and native_vjoy_output_id(target) == source["key"]

    def _apply_confirmation(self):
        MessageBoxYesNo(
            prompt="Are you sure you want to apply the changes?",
            callback=lambda button: self._apply(button == QtWidgets.QMessageBox.StandardButton.Yes),
            parent=self,
        )

    def _select(self, checked):
        for source, check, combo in self._rows + self._output_rows:
            target = combo.currentData()
            blocker = QtCore.QSignalBlocker(check)
            check.setChecked(checked and target is not None and not self._is_current_device(source, target))
            blocker.unblock()
        self._validate()

    def _replacement_root(self):
        self._output_changes = []
        self._validation_message = "Select an input or output device and choose its target. Changes will only be applied to selected (checked) items."
        replacements = {}
        for source, check, combo in self._rows:
            if not check.isChecked():
                continue
            target = combo.currentData()
            if target is None:
                self._validation_message = f'Choose a target for "{source.get("name")}" or deselect it.'
                return None
            if self._is_current_device(source, target):
                self._validation_message = f'Choose a different device for "{source.get("name")}" or deselect it.'
                return None
            replacements[source.get("device-guid")] = (str(target.device_guid), target.name)
        output_replacements = {}
        for source, check, combo in self._output_rows:
            if not check.isChecked():
                continue
            target = combo.currentData()
            if target is None:
                self._validation_message = f'Choose a target output for "{source["name"]}" or deselect it.'
                return None
            if self._is_current_device(source, target):
                self._validation_message = f'Choose a different output device for "{source["name"]}" or deselect it.'
                return None
            output_replacements[source["key"]] = target
        root = self._root
        if output_replacements:
            root, self._output_changes = remap_output_devices(root, self._devices, output_replacements, saved_root=self._saved_root)
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
        except Exception as error:  # noqa: BLE001
            self._status.setText(f"Could not remap the profile: {error}")
            return
        self.accept()
