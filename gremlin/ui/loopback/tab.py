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


"""Loopback control editor and profile startup settings."""

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QVBoxLayout

from gremlin import shared_state
from gremlin.base_classes import AbstractCallbackModel
from gremlin.input_item import InputItemListModel, InputItemWidget
from gremlin.ui.joystick_device import AxisCurveDeviceTab
from gremlin.ui.ui_common import (
    BaseDialogUi,
    ConfirmBox,
    MessageBoxWarning,
    QDataCheckbox,
    QDataLabel,
    QDataPushButton,
    QFloatLineEdit,
    QGroupBoxV,
    QInputDialog,
    QNoWheelPlainTextEdit,
    clear_layout,
    getHContainer,
)

from . import AXIS, BUTTON
from .usage import find_usage


class NameDialog(QInputDialog):
    def __init__(self, loopback, title, text, parent, exclude=None):
        self._loopback = loopback
        self._exclude = exclude
        super().__init__(title=title, label="Input name", text=text, parent=parent, key=title)

    def _accept(self):
        name = self.text().strip()
        if self._loopback.name_available(name, exclude=self._exclude):
            self.setText(name)
            super()._accept()
        else:
            MessageBoxWarning(title="Loopback input name", prompt="Enter a nonempty name that is unique in Loopback.", parent=self)


class LoopbackUsageDialog(BaseDialogUi):
    def __init__(self, usage, parent):
        super().__init__("LoopbackUsageDialog", width=660, height=360, parent=parent)
        self.setWindowTitle("Loopback Inputs in Use")

        message = QDataLabel("Remove the mappings and conditions listed below before deleting these Loopback inputs.")
        message.setWordWrap(True)
        details = QNoWheelPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText("\n\n".join(
            "\n".join([name, *(f"• {location}" for location in locations)])
            for name, locations in sorted(usage.items(), key=lambda entry: entry[0].casefold())
        ))
        close_button = QDataPushButton("OK", clicked=self.accept)
        panel = QGroupBoxV("Profile References")
        panel.layout().addWidget(details)
        panel_layout = QVBoxLayout(self)
        panel_layout.addWidget(message)
        panel_layout.addWidget(panel, 1)
        panel_layout.addWidget(getHContainer([close_button], left_stretch=True, widget_only=True))


class LoopbackInputListModel(InputItemListModel):
    def remove(self, item, emit=True):
        """Route toolbar deletion through the Loopback definition handler."""
        index = item if isinstance(item, int) else self._item_map.get(item, -1)
        if index >= 0:
            self.removeAt(index, emit=emit)


class LoopbackTab(AxisCurveDeviceTab):
    def __init__(self, device, profile, mode):
        self.device_guid = device.device_guid
        self.loopback = profile.loopback
        profile.get_device_modes(device.device_guid, device.device_type, "loopback").device = device
        super().__init__(
            device=device, profile=profile, mode=mode, object_name="Loopback",
            enable_filter=False, custom_input_widget_callback=self._create_input_widget,
            blank_input_message="Add an axis or button to start mapping Loopback inputs.",
        )
        self.model = LoopbackInputListModel(
            profile, device.device_guid, mode, allowed_types=[AXIS, BUTTON],
            custom_load_handler=self._load_inputs, custom_remove_handler=self._remove_item,
        )
        self.setInputItemListModel(self.model)
        presets_button = QDataPushButton("Presets...", tooltip="Add a preset group of Loopback axes and buttons")
        presets_menu = QMenu(self)
        for axis_count, button_count in ((4, 16), (8, 32)):
            action = presets_menu.addAction(f"Add {axis_count} Axes and {button_count} Buttons")
            action.triggered.connect(
                lambda _checked, axes=axis_count, buttons=button_count: self._add_preset(axes, buttons)
            )
        presets_button.setMenu(presets_menu)
        self.addLeftPanelHeaderWidget(getHContainer([
            QDataPushButton("Add Axis", callback=lambda: self._add(AXIS, "Axis")),
            QDataPushButton("Add Button", callback=lambda: self._add(BUTTON, "Button")),
            presets_button,
        ], widget_only=True))
        self.addLeftPanelHeaderWidget(getHContainer([
            QDataPushButton("Rename", callback=self._rename),
            QDataPushButton("Delete All", callback=self._delete_all),
        ], widget_only=True))
        self.model.refresh()

    def _create_input_widget(self, list_view, index, _identifier, item, parent=None):
        widget = InputItemWidget(
            item, model_index=index, mapping_changed_callback=list_view._handle_mapping_changed,
            confirm_delete_callback=self._confirm_delete_input,
        )
        if item.input_type == AXIS:
            widget.setIcon("dark_joystick.png" if shared_state.is_dark_theme else "joystick.png")
        else:
            widget.setIcon("mdi.gesture-tap-button")
        widget.enable_close()
        return widget

    def _confirm_delete_input(self, item):
        kind, index = item.input_type, item.input_id
        if not self._can_delete([(kind, index)]):
            return False
        name = escape(self.loopback.controls[kind][index].name)
        return ConfirmBox(prompt=f"<p>Delete the Loopback input <b>{name}</b> from this profile?</p>", parent=self)

    def _load_inputs(self, model):
        items = self.loopback.prepare_mode(self.profile, model.mode)
        AbstractCallbackModel.clear(model, emit=False)
        model.setItems(items, emit=False)
        model.trigger()

    def set_mode(self, mode):
        if self.model.mode != mode:
            self.model.mode = mode

    def _ask_name(self, title, name, exclude=None):
        dialog = NameDialog(self.loopback, title, name, self, exclude)
        try:
            return dialog.text() if dialog.exec() else None
        finally:
            dialog.deleteLater()

    def _add(self, kind, label):
        name = self._ask_name(f"Add Loopback {label}", self.loopback.next_name(kind))
        if name is None:
            return
        index = self.loopback.add(kind, name)
        self.model.refresh()
        item = self.profile.getModeNode(self.device_guid, self.model.mode).getInputItem(kind, index)
        self.selectInputItem(item)

    def _add_preset(self, axis_count, button_count):
        self.loopback.add_generic_controls(axis_count, button_count)
        self.model.refresh()

    def _rename(self):
        item = self.getSelectedInputItem()
        if item is None:
            return
        key = item.input_type, item.input_id
        name = self._ask_name("Rename Loopback Input", self.loopback.controls[key[0]][key[1]].name, key)
        if name is not None:
            self.loopback.rename(*key, name)
            self.model.refresh()
            self.selectInputItem(item)

    def _remove_item(self, model, index, emit):
        item = model.itemAt(index)
        if item is None or not self._delete([(item.input_type, item.input_id)]):
            return False
        model.refresh(emit=emit)
        return True

    def _delete_all(self):
        keys = [(kind, index) for kind, controls in self.loopback.controls.items() for index in controls]
        if keys and self._delete(keys, confirm_all=True):
            self.model.refresh()

    def _can_delete(self, keys):
        usage = find_usage(self.profile, keys)
        if usage:
            named_usage = {self.loopback.controls[kind][index].name: locations for (kind, index), locations in usage.items()}
            dialog = LoopbackUsageDialog(named_usage, self)
            try:
                dialog.exec()
            finally:
                dialog.deleteLater()
            return False
        return True

    def _delete(self, keys, confirm_all=False):
        if not self._can_delete(keys):
            return False
        if confirm_all and not ConfirmBox(prompt="Delete all Loopback axes and buttons in this profile?", parent=self):
            return False
        device_node = self.profile.getDeviceNode(self.device_guid)
        for mode in device_node.modes.values():
            for kind, index in keys:
                item = mode.getInputItem(kind, index)
                if item is not None:
                    self.profile.registry.removeInputItem(item)
        self.loopback.remove(keys)
        return True


class LoopbackStartupWidget(QGroupBoxV):
    def __init__(self, loopback):
        super().__init__("Loopback Startup Values")
        self.loopback = loopback
        self.loopback.definitions_changed.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        layout = self.layout()
        clear_layout(layout)
        self.setVisible(any(self.loopback.controls.values()))
        for control in self.loopback.controls[AXIS].values():
            field = QFloatLineEdit(value=control.start, callback=lambda value, item=control: setattr(item, "start", value))
            label = QDataLabel(control.name)
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(getHContainer([label, field], widget_only=True))
        for control in self.loopback.controls[BUTTON].values():
            label = QDataLabel(control.name)
            label.setTextFormat(Qt.TextFormat.PlainText)
            field = QDataCheckbox("Pressed", value=control.start, data=control, callback=lambda widget, value: setattr(widget.data, "start", value))
            layout.addWidget(getHContainer([label, field], widget_only=True))
