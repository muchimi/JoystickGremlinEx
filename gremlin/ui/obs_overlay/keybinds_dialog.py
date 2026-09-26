# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Runtime overlay control keybinds dialog (physical / vJoy / keyboard-mouse)."""

from __future__ import annotations

import logging

from PySide6 import QtCore, QtWidgets
from shiboken6 import Shiboken

import gremlin.joystick_handling
import gremlin.keyboard
import gremlin.ui.ui_common
from gremlin.input_types import InputType
from gremlin.ui.ui_common import Buttons, QDataComboBox, QDataPushButton

from .bindings import binding_is_configured
from .inspector import OverlayKeyCombinationWidget, _enum_radios
from .model import (
    OverlayScene,
    RUNTIME_BINDING_GROUPS,
    RUNTIME_BINDING_LABELS,
    RUNTIME_HOLD_ACTIONS,
    deserialize_overlay_key,
    normalize_overlay_keys,
    normalize_runtime_bindings,
    normalize_toggle_binding,
)

syslog = logging.getLogger("system")


def _alive(widget) -> bool:
    try:
        return widget is not None and Shiboken.isValid(widget)
    except Exception:
        return False


def _physical_devices():
    devices = gremlin.joystick_handling.getPhysicalDevices() or []
    return sorted(devices, key=lambda d: (d.name or "").casefold())


def _button_choices(device) -> list[tuple[int, str]]:
    count = int(getattr(device, "button_count", 0) or 0) if device else 16
    return [(i, f"Button {i}") for i in range(1, max(1, count) + 1)]


def _binding_summary(binding: dict) -> str:
    if not binding_is_configured(binding):
        return "(none)"
    source = (binding.get("source") or "physical").casefold()
    if source in ("keyboard", "keyboard/mouse", "mouse"):
        names = []
        for raw in binding.get("keys") or []:
            key = deserialize_overlay_key(raw)
            if key is None:
                continue
            names.append(gremlin.keyboard.KeyMap.get_name(key) or str(getattr(key, "name", "") or ""))
        return " + ".join(n for n in names if n) or "(none)"
    try:
        input_id = int(binding.get("input_id") or 0)
    except (TypeError, ValueError):
        input_id = 0
    if input_id <= 0:
        return "(none)"
    name = binding.get("device_name") or "—"
    return f"{name}  Button {input_id}"


class RuntimeActionBindingEditor(QtWidgets.QWidget):
    """One action row: Physical / vJoy / Keyboard-mouse + Listen/Clear."""

    changed = QtCore.Signal()

    def __init__(self, scene: OverlayScene, page_id: str | None, action: str, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.page_id = page_id
        self.action = action
        self._building = False
        self._listen_dialog = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 8)
        root.setSpacing(4)

        title = RUNTIME_BINDING_LABELS.get(action, action)
        if action in RUNTIME_HOLD_ACTIONS:
            title = f"{title} (hold)"
        heading = QtWidgets.QLabel(f"<b>{title}</b>", self)
        root.addWidget(heading)

        self._form = QtWidgets.QFormLayout()
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setSpacing(4)
        root.addLayout(self._form)

        self._rebuild()

    def set_page_id(self, page_id: str | None):
        self.page_id = page_id
        self._rebuild()

    def _canvas(self) -> dict:
        return self.scene.canvas_for(self.page_id)

    def _binding(self) -> dict:
        bindings = normalize_runtime_bindings(self._canvas().get("runtime_bindings"))
        return normalize_toggle_binding(bindings.get(self.action))

    def _save(self, rebuild: bool = False, **fields):
        if self._building:
            return
        canvas = self._canvas()
        bindings = normalize_runtime_bindings(canvas.get("runtime_bindings"))
        binding = normalize_toggle_binding(bindings.get(self.action))
        if (fields.get("source") or "").casefold() == "vjoy" and not int(fields.get("vjoy_id") or 0):
            devices = gremlin.joystick_handling.vjoy_devices(connected_only=False) or []
            if devices:
                fields["vjoy_id"] = int(devices[0].vjoy_id)
                fields.setdefault("device_guid", str(devices[0].device_guid))
                fields.setdefault("device_name", devices[0].name)
        binding.update(fields)
        binding = normalize_toggle_binding(binding)
        binding["input_type"] = "keyboard" if binding.get("source") == "keyboard" else "button"
        bindings[self.action] = binding
        canvas["runtime_bindings"] = bindings
        self.scene._dirty = True
        self.scene.changed.emit()
        self.changed.emit()
        if rebuild:
            self._rebuild()

    def _clear(self):
        self._save(
            rebuild=True,
            source="physical",
            device_guid="",
            device_name="",
            vjoy_id=0,
            input_id=0,
            keys=[],
            input_type="button",
        )

    def _device_from_combo(self, device_box: QtWidgets.QComboBox, source: str):
        data = device_box.currentData()
        if source == "vjoy":
            try:
                vjoy_id = int(data or 0)
            except (TypeError, ValueError):
                return None
            if vjoy_id <= 0:
                return None
            for dev in gremlin.joystick_handling.vjoy_devices(connected_only=False) or []:
                if int(getattr(dev, "vjoy_id", 0) or 0) == vjoy_id:
                    return dev
            return None
        guid = str(data or "").strip()
        if not guid:
            return None
        return gremlin.joystick_handling.getDevice(guid, show_error=False)

    def _listen(self):
        def _captured(event):
            if not _alive(self):
                return
            device = gremlin.joystick_handling.getDevice(event.device_guid, show_error=False)
            payload = {
                "source": "vjoy" if getattr(device, "is_virtual", False) else "physical",
                "device_guid": str(event.device_guid),
                "device_name": device.name if device else str(event.device_guid),
                "vjoy_id": int(getattr(device, "vjoy_id", 0) or 0),
                "input_type": "button",
                "input_id": int(event.identifier),
                "keys": [],
            }
            self._save(rebuild=True, **payload)

        previous = self._listen_dialog
        if previous is not None:
            try:
                if Shiboken.isValid(previous):
                    previous.close()
            except Exception:
                pass
            self._listen_dialog = None
        listener = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.JoystickButton],
            callback=_captured,
            parent=self,
        )
        self._listen_dialog = listener
        listener.show()

    def _rebuild(self):
        self._building = True
        while self._form.rowCount():
            self._form.removeRow(0)

        binding = self._binding()
        source = (binding.get("source") or "physical").casefold()
        if source in ("keyboard/mouse", "mouse"):
            source = "keyboard"
        if source not in ("physical", "vjoy", "keyboard"):
            source = "physical"

        source_group = _enum_radios(
            [
                ("Physical", "physical"),
                ("vJoy", "vjoy"),
                ("Keyboard/mouse", "keyboard"),
            ],
            source,
            lambda v: self._save(rebuild=True, source=str(v or "physical"), input_type="keyboard" if v == "keyboard" else "button"),
            parent=self,
        )
        self._form.addRow("Source", source_group)

        if source == "keyboard":
            picker = OverlayKeyCombinationWidget(binding.get("keys") or [], parent=self)
            picker.keys_changed.connect(
                lambda keys: self._save(
                    rebuild=False,
                    keys=normalize_overlay_keys(keys),
                    input_type="keyboard",
                    source="keyboard",
                    input_id=0,
                )
            )
            self._form.addRow(picker)
        else:
            device_box = QDataComboBox(self)
            if source == "vjoy":
                for dev in gremlin.joystick_handling.vjoy_devices(connected_only=False) or []:
                    device_box.addItem(f"vJoy {dev.vjoy_id} ({dev.name})", int(dev.vjoy_id))
                current = int(binding.get("vjoy_id") or 0)
                for i in range(device_box.count()):
                    if int(device_box.itemData(i) or 0) == current:
                        device_box.setCurrentIndex(i)
                        break
            else:
                for dev in _physical_devices():
                    device_box.addItem(dev.name, str(dev.device_guid))
                current = str(binding.get("device_guid") or "")
                for i in range(device_box.count()):
                    guid = str(device_box.itemData(i) or "")
                    if guid and guid.casefold() == current.casefold():
                        device_box.setCurrentIndex(i)
                        break

            def _device_changed():
                if self._building or not _alive(self):
                    return
                src = source
                dev = self._device_from_combo(device_box, src)
                if not dev:
                    return
                payload = {"device_name": dev.name, "device_guid": str(dev.device_guid), "source": src, "input_type": "button"}
                if src == "vjoy":
                    payload["vjoy_id"] = int(dev.vjoy_id)
                self._save(rebuild=True, **payload)

            device_box.currentIndexChanged.connect(_device_changed)
            self._form.addRow("Device", device_box)

            listen = Buttons.getListenWidget(
                label="Listen...",
                tooltip="Assign from the next physical or vJoy button",
                callback=self._listen,
            )
            self._form.addRow("", listen)

            device = self._device_from_combo(device_box, source)
            id_box = QDataComboBox(self)
            id_box.addItem("(none)", 0)
            try:
                current_id = int(binding.get("input_id") or 0)
            except (TypeError, ValueError):
                current_id = 0
            found = False
            for bid, label in _button_choices(device):
                id_box.addItem(label, bid)
                if int(bid) == current_id:
                    id_box.setCurrentIndex(id_box.count() - 1)
                    found = True
            if not found and current_id > 0:
                id_box.addItem(f"Button {current_id}", current_id)
                id_box.setCurrentIndex(id_box.count() - 1)
            elif current_id <= 0:
                id_box.setCurrentIndex(0)

            id_box.currentIndexChanged.connect(
                lambda _i, box=id_box: self._save(
                    input_type="button",
                    input_id=int(box.currentData() if box.currentData() is not None else 0),
                    keys=[],
                )
            )
            self._form.addRow("Button", id_box)

        assigned = QtWidgets.QLabel(_binding_summary(self._binding()), self)
        assigned.setWordWrap(True)
        self._form.addRow("Assigned", assigned)

        clear = Buttons.getClearWidget(callback=self._clear)
        self._form.addRow("", clear)

        self._building = False


class OverlayRuntimeKeybindsDialog(QtWidgets.QDialog):
    """Edit per-page runtime control keybinds from the overlay control panel."""

    def __init__(self, scene: OverlayScene, page_id: str | None = None, parent=None):
        super().__init__(parent)
        self.scene = scene
        self._page_id = page_id or scene.active_page_id
        self.setWindowTitle("Overlay control keybinds")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        self.resize(460, 640)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        hint = QtWidgets.QLabel(
            "Assign physical, vJoy, or keyboard/mouse inputs to overlay control actions. "
            "Bindings are stored on the selected page and fire while the profile is running. "
            "Nudge binds repeat while held.",
            self,
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        page_row = QtWidgets.QHBoxLayout()
        page_row.addWidget(QtWidgets.QLabel("Page", self))
        self._page_box = QtWidgets.QComboBox(self)
        for page in self.scene.pages:
            self._page_box.addItem(str(page.get("name") or "Overlay"), page.get("id"))
        idx = self._page_box.findData(self._page_id)
        if idx >= 0:
            self._page_box.setCurrentIndex(idx)
        self._page_box.currentIndexChanged.connect(self._on_page_changed)
        page_row.addWidget(self._page_box, 1)
        root.addLayout(page_row)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        host = QtWidgets.QWidget(scroll)
        self._host_layout = QtWidgets.QVBoxLayout(host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._host_layout.setSpacing(6)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        self._editors: list[RuntimeActionBindingEditor] = []
        self._rebuild_editors()

        close_btn = QDataPushButton("Close", parent=self, clicked=self.accept)
        root.addWidget(close_btn, 0, QtCore.Qt.AlignRight)

    def _on_page_changed(self, _index: int):
        data = self._page_box.currentData()
        self._page_id = str(data) if data else self.scene.active_page_id
        for editor in self._editors:
            editor.set_page_id(self._page_id)

    def _rebuild_editors(self):
        while self._host_layout.count():
            item = self._host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._editors.clear()
        for group_title, actions in RUNTIME_BINDING_GROUPS:
            box = QtWidgets.QGroupBox(group_title, self)
            form = QtWidgets.QVBoxLayout(box)
            form.setContentsMargins(8, 8, 8, 8)
            form.setSpacing(2)
            for action in actions:
                editor = RuntimeActionBindingEditor(self.scene, self._page_id, action, parent=box)
                form.addWidget(editor)
                self._editors.append(editor)
            self._host_layout.addWidget(box)
        self._host_layout.addStretch(1)


def open_runtime_keybinds_dialog(
    scene: OverlayScene,
    page_id: str | None = None,
    parent=None,
) -> OverlayRuntimeKeybindsDialog:
    dialog = OverlayRuntimeKeybindsDialog(scene, page_id=page_id, parent=parent)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
