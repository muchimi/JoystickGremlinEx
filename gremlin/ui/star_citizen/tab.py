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

"""UI for the star citizen device"""

from PySide6 import QtCore, QtWidgets

from gremlin.base_classes import AbstractCallbackModel
from gremlin.config import Configuration
from gremlin.input_item import AdvancedInputItemListModel, BaseDeviceTabWidget, InputItem, InputItemWidget
from gremlin.input_types import InputType
from gremlin.ui.ui_common import QWarningWidget

from . import DEVICE_NAME, get_device
from .telemetry import BUTTONS, HELD_INPUTS

_HELD_BUTTON_IDS = frozenset(item.button for item in HELD_INPUTS.values())


def _input_name(item):
    return BUTTONS[item.input_id].label


def prepare_inputs(device, profile, mode):
    """Populate profile modes with the telemetry inputs, reusing saved items."""
    device_profile = profile.get_device_modes(device.device_guid, device.device_type, device.name)
    for mode_name in dict.fromkeys([*profile.get_modes(), mode]):
        mode_node = device_profile.ensure_mode_exists(mode_name)
        for button_id in BUTTONS:
            item = mode_node.getInputItem(InputType.StarCitizen, button_id)
            if item is None:
                item = InputItem(mode_node, input_type=InputType.StarCitizen, input_id=button_id)
                mode_node.addInputItem(item)
            item.setInputNameHandler(_input_name)
    profile.setFilterDefaults(device.device_guid)


class StarCitizenInputItemModel(AdvancedInputItemListModel):
    def __init__(self, profile, device_guid, mode):
        super().__init__(
            profile=profile,
            device_guid=device_guid,
            mode=mode,
            allowed_types=[InputType.StarCitizen],
            custom_load_handler=self._load_inputs,
        )

    def _load_inputs(self, model):
        inputs = self._profile.registry.getInputItems(self._device_guid, self.mode, InputType.StarCitizen)
        AbstractCallbackModel.clear(model, emit=False)
        model.setItems(
            sorted(
                (item for item in inputs if item.input_id in BUTTONS),
                key=lambda item: (item.input_id not in _HELD_BUTTON_IDS, item.input_id),
            ),
            emit=False,
        )
        model.trigger()

    def _handle_custom_filter(self, item, filter=AdvancedInputItemListModel.DEFAULT_FILTER):
        if not self._profile.settings.getInputVisible(item.device_guid, item.input_type, item.input_id):
            return False
        text = self._search_string_map[filter]
        definition = BUTTONS[item.input_id]
        return not text or text in definition.label.casefold() or text in definition.address


class StarCitizenInputItemWidget(InputItemWidget):
    def __init__(self, input_item, index, service, parent=None):
        super().__init__(
            input_item=input_item,
            model_index=index,
            data=input_item,
            get_state_callback=lambda: input_item.input_id in service.preview_held_buttons,
            parent=parent,
        )
        self.definition = BUTTONS[input_item.input_id]
        self.setIcon("mdi.rocket-launch")
        self.setToolTip(self.definition.address)
        self.disable_edit()
        self.disable_close()
        self.create_action_icons(input_item)
        self._service = service
        self._pulse_timer = QtCore.QTimer(self)
        self._pulse_timer.setSingleShot(True)
        self._pulse_timer.setInterval(250)
        self._pulse_timer.timeout.connect(self._clear_pulse)
        service.input_preview_changed.connect(self._update_indicator)

        self._current = QtWidgets.QLabel()
        self.addWidget(self._current)
        service.snapshot_changed.connect(self._update_snapshot)
        Configuration().changed.connect(self._config_changed)
        self._update_value_visibility()

    def _cleanup_ui(self):
        self._service.snapshot_changed.disconnect(self._update_snapshot)
        self._service.input_preview_changed.disconnect(self._update_indicator)
        Configuration().changed.disconnect(self._config_changed)
        self._pulse_timer.stop()
        super()._cleanup_ui()

    @QtCore.Slot(object, object)
    def _update_indicator(self, pulse_buttons, held_buttons):
        button = self.definition.button
        if button in pulse_buttons:
            self._pulse_timer.start()
        if self.button_repeater_widget is not None:
            self.button_repeater_widget.setState(button in held_buttons or self._pulse_timer.isActive())

    @QtCore.Slot()
    def _clear_pulse(self):
        if self.button_repeater_widget is not None:
            self.button_repeater_widget.setState(self.definition.button in self._service.preview_held_buttons)

    @QtCore.Slot(str, object)
    def _config_changed(self, field, _value):
        if field in ("verbose", "verbose_mode"):
            self._update_value_visibility()

    def _update_value_visibility(self):
        label = self._current
        if label is None:
            return
        show_value = Configuration().verbose_mode_star_citizen
        label.setVisible(show_value)
        if show_value:
            self._update_snapshot(self._service.snapshot)

    @QtCore.Slot(object)
    def _update_snapshot(self, snapshot):
        label = self._current
        if label is None or label.isHidden():
            return
        value = snapshot[1].get(self.definition.field) if snapshot else None
        label.setText(f"Current value  {value.replace('-', ' ')}" if value else "Current value unavailable")


class StarCitizenDeviceTabWidget(BaseDeviceTabWidget):
    def __init__(self, device, profile, mode, parent=None):
        self.device_guid = device.device_guid
        self._input_dirty = False
        prepare_inputs(device, profile, mode)
        super().__init__(
            device=device,
            profile=profile,
            mode=mode,
            object_name=DEVICE_NAME,
            enable_filter=True,
            custom_input_widget_callback=self._create_input_widget,
            blank_input_message="No matching telemetry inputs.",
            parent=parent,
        )
        self._service = get_device()
        self.model = StarCitizenInputItemModel(profile, device.device_guid, mode)
        self.setInputItemListModel(self.model)

        warning_widget = QWarningWidget("Experimental Star Citizen support")
        self.addLeftPanelHeaderWidget(warning_widget)

        status = QtWidgets.QLabel(self._service.status)
        status.setWordWrap(True)
        self._service.status_changed.connect(status.setText)
        self.addLeftPanelHeaderWidget(status)

        self._ship = QtWidgets.QLabel()
        self._ship.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self._service.snapshot_changed.connect(self._update_ship)
        self._update_ship(self._service.snapshot)
        self.addLeftPanelHeaderWidget(self._ship)

        search = QtWidgets.QLineEdit()
        search.setPlaceholderText("Search telemetry inputs")
        search.setClearButtonEnabled(True)
        search.textChanged.connect(self.model.setSearchString)
        self.addLeftPanelHeaderWidget(search)

        filter_button = QtWidgets.QPushButton("Filter Inputs…")
        filter_button.clicked.connect(self._show_input_filter)
        self.addLeftPanelHeaderWidget(filter_button)
        self.model.refresh()

    @QtCore.Slot()
    def _show_input_filter(self):
        from gremlin.ui.joystick_device import JoystickFilterDialog

        dialog = JoystickFilterDialog(self.device_guid, parent=self)
        try:
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                self.model.refresh()
        finally:
            dialog.deleteLater()

    def _create_input_widget(self, list_view, index, identifier, data, parent=None):
        return StarCitizenInputItemWidget(identifier.input_item, index, self._service, parent)

    @QtCore.Slot(object)
    def _update_ship(self, snapshot):
        if snapshot:
            name, class_name = snapshot[0]
            self._ship.setText(class_name or name or "Vehicle telemetry available")
        else:
            self._ship.setText("Waiting for vehicle telemetry")

    def set_mode(self, mode):
        if mode != self.model.mode:
            prepare_inputs(self.device, self.profile, mode)
            self.model.mode = mode
