# -*- coding: utf-8; -*-

"""AFCS designer: flight-mode list, OdenGraphQt canvas, inspector, live meters."""

from __future__ import annotations

import copy
import logging
import uuid

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

import gremlin.config
import gremlin.curve_handler
import gremlin.event_handler
import gremlin.joystick_handling
import gremlin.keyboard
import gremlin.shared_state
import gremlin.ui.ui_common
import gremlin.util
from gremlin.input_types import InputType
from gremlin.ui.obs_overlay.bindings import (
    find_overlay_state,
    overlay_mode_combo_fields,
    overlay_state_combo_fields,
    populate_overlay_mode_combo,
    populate_overlay_state_combo,
    resolve_overlay_mode,
)
from gremlin.ui.obs_overlay.inspector import OverlayKeyCombinationWidget
from gremlin.ui.obs_overlay.model import (
    default_toggle_binding,
    default_visibility_condition,
    deserialize_overlay_key,
    normalize_overlay_keys,
    normalize_toggle_binding,
)

from .model import AfcsDocument, decode_when, default_node, encode_when
from .nodes import (
    AFCS_NODE_CLASSES,
    KIND_TO_TYPE,
    kind_for_node,
    operation_from_label,
    operation_label,
)
from .ops import (
    INPUT_DISPLAY_LABELS,
    INPUT_DISPLAY_RANGES,
    LIMITER_RANGE_LABELS,
    LIMITER_RANGES,
    LIMITER_SHAPE_LABELS,
    LIMITER_SHAPES,
    MERGE_OP_LABELS,
    MERGE_OPS,
    inspector_help,
    meter_is_centered,
    normalize_input_display_range,
    normalize_limiter_range,
    normalize_limiter_shape,
    sample_limiter_curve,
)
from .runtime import curve_from_xml, curve_to_xml

syslog = logging.getLogger("system")

_NODE_CLIPBOARD: dict | None = None

try:
    from OdenGraphQt import NodeGraph as _OdenNodeGraph
    from OdenGraphQt.base.commands import NodeAddedCmd, NodesRemovedCmd, PropertyChangedCmd
    from OdenGraphQt.nodes.base_node import BaseNode
except Exception as err:
    _OdenNodeGraph = None
    NodeGraph = None
    BaseNode = None
    syslog.error(f"AFCS: OdenGraphQt import failed: {err}")
else:

    class _AfcsHook:
        """Python stand-in for OdenGraphQt signals that pass NodeObject/Port.

        Those types are plain Python objects, not QObjects. Emitting them through
        a typed Qt signal native-crashes in Shiboken.
        """

        def __init__(self, graph, hook_attr: str | None = None):
            self._graph = graph
            self._hook_attr = hook_attr
            self._slots = []

        def emit(self, *args):
            hook = getattr(self._graph, self._hook_attr, None) if self._hook_attr else None
            if callable(hook):
                try:
                    hook(*args)
                except Exception:
                    pass
            for slot in list(self._slots):
                try:
                    slot(*args)
                except Exception:
                    pass

        def connect(self, slot):
            if callable(slot) and slot not in self._slots:
                self._slots.append(slot)

        def disconnect(self, slot=None):
            if slot is None:
                self._slots.clear()
            elif slot in self._slots:
                self._slots.remove(slot)

    def _afcs_node_added_redo(self) -> None:
        """Add the node without a Qt emit. OdenGraphQt's NodeObject is not a QObject."""
        self.graph.model.nodes[self.node.id] = self.node
        self.graph.viewer().add_node(self.node.view, self.pos)
        self.node.model.width = self.node.view.width
        self.node.model.height = self.node.view.height
        if self.emit_signal:
            hook = getattr(self.graph, "_afcs_node_created", None)
            if callable(hook):
                hook(self.node)

    def _afcs_nodes_removed_undo(self) -> None:
        for node in self.nodes:
            self.graph.model.nodes[node.id] = node
            self.graph.scene().addItem(node.view)
            if self.emit_signal:
                hook = getattr(self.graph, "_afcs_node_created", None)
                if callable(hook):
                    hook(node)

    def _afcs_set_node_property(self, name, value) -> None:
        model = self.node.model
        model.set_property(name, value)
        view = self.node.view
        if hasattr(view, "widgets") and name in view.widgets.keys():
            if view.widgets[name].get_value() != value:
                view.widgets[name].set_value(value)
        if name in view.properties.keys():
            setattr(view, "xy_pos" if name == "pos" else name, value)
        graph = self.node.graph
        hook = getattr(graph, "_afcs_property_changed", None)
        if callable(hook):
            hook(self.node, self.name, value)

    if not getattr(NodeAddedCmd, "_afcs_create_signal_fixed", False):
        NodeAddedCmd.redo = _afcs_node_added_redo
        NodeAddedCmd._afcs_create_signal_fixed = True
    if not getattr(NodesRemovedCmd, "_afcs_create_signal_fixed", False):
        NodesRemovedCmd.undo = _afcs_nodes_removed_undo
        NodesRemovedCmd._afcs_create_signal_fixed = True
    if not getattr(PropertyChangedCmd, "_afcs_create_signal_fixed", False):
        PropertyChangedCmd.set_node_property = _afcs_set_node_property
        PropertyChangedCmd._afcs_create_signal_fixed = True

    class NodeGraph(_OdenNodeGraph):
        """PySide6 cannot copy-convert OdenGraphQt's Python NodeObject/Port types."""

        def __init__(self, *args, **kwargs):
            self._afcs_node_created = None
            self._afcs_property_changed = None
            super().__init__(*args, **kwargs)
            self.node_created = _AfcsHook(self, "_afcs_node_created")
            self.property_changed = _AfcsHook(self, "_afcs_property_changed")
            self.port_connected = _AfcsHook(self)
            self.port_disconnected = _AfcsHook(self)
            self.node_selected = _AfcsHook(self)
            self.node_double_clicked = _AfcsHook(self)
            self.node_selection_changed = _AfcsHook(self)


class ActivationBindingWidget(QtWidgets.QWidget):
    """State / mode / button / keyboard activation for a flight mode."""

    changed = QtCore.Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._binding = default_toggle_binding()
        self._layout = QtWidgets.QFormLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._source = QtWidgets.QComboBox()
        for value, label in (
            ("none", "Always (fallback)"),
            ("state", "State"),
            ("mode", "GEX mode"),
            ("physical", "Button"),
            ("keyboard", "Keyboard"),
        ):
            self._source.addItem(label, value)
        self._source.currentIndexChanged.connect(self._on_source)
        self._layout.addRow("Activate by", self._source)
        self._body = QtWidgets.QWidget()
        self._body_layout = QtWidgets.QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addRow(self._body)

    def set_binding(self, binding: dict) -> None:
        self._binding = normalize_toggle_binding(binding)
        source = (self._binding.get("source") or "physical").casefold()
        kind = (self._binding.get("input_type") or "button").casefold()
        if not self._binding.get("input_id") and source == "physical" and kind == "button":
            combo_source = "none"
        elif source in ("state", "mode", "keyboard"):
            combo_source = source
        else:
            combo_source = "physical"
        index = self._source.findData(combo_source)
        with QtCore.QSignalBlocker(self._source):
            self._source.setCurrentIndex(index if index >= 0 else 0)
        self._rebuild_body()

    def _on_source(self) -> None:
        source = str(self._source.currentData() or "none")
        binding = default_toggle_binding()
        if source == "none":
            binding["input_id"] = 0
        elif source == "state":
            binding["source"] = "state"
            binding["input_type"] = "state"
        elif source == "mode":
            binding["source"] = "mode"
            binding["input_type"] = "mode"
        elif source == "keyboard":
            binding["source"] = "keyboard"
            binding["input_type"] = "keyboard"
        else:
            binding["source"] = "physical"
            binding["input_type"] = "button"
        self._binding = binding
        self._rebuild_body()
        self.changed.emit(dict(self._binding))

    def _rebuild_body(self) -> None:
        gremlin.util.clear_layout(self._body_layout)
        source = str(self._source.currentData() or "none")
        if source == "state":
            combo = QtWidgets.QComboBox()
            populate_overlay_state_combo(combo, self._binding.get("state_id"), self._binding.get("state_name"))
            combo.currentIndexChanged.connect(self._on_state)
            self._body_layout.addWidget(combo)
        elif source == "mode":
            combo = QtWidgets.QComboBox()
            populate_overlay_mode_combo(combo, self._binding.get("mode_id"), self._binding.get("mode_name"))
            combo.currentIndexChanged.connect(self._on_mode)
            self._body_layout.addWidget(combo)
        elif source == "keyboard":
            picker = OverlayKeyCombinationWidget(self._binding.get("keys") or [])
            picker.keys_changed.connect(self._on_keys)
            self._body_layout.addWidget(picker)
        elif source == "physical":
            row = QtWidgets.QHBoxLayout()
            label = QtWidgets.QLabel(self._device_label())
            listen = QtWidgets.QPushButton("Listen...")
            listen.clicked.connect(self._listen)
            row.addWidget(label, 1)
            row.addWidget(listen)
            wrap = QtWidgets.QWidget()
            wrap.setLayout(row)
            self._body_layout.addWidget(wrap)
            self._device_label_widget = label

    def _device_label(self) -> str:
        name = str(self._binding.get("device_name") or "").strip()
        input_id = int(self._binding.get("input_id") or 0)
        if name and input_id:
            return f"{name} button {input_id}"
        return "No button assigned"

    def _on_state(self) -> None:
        combo = self.sender()
        if not isinstance(combo, QtWidgets.QComboBox):
            return
        self._binding.update(overlay_state_combo_fields(combo))
        self._binding["source"] = "state"
        self.changed.emit(dict(self._binding))

    def _on_mode(self) -> None:
        combo = self.sender()
        if not isinstance(combo, QtWidgets.QComboBox):
            return
        self._binding.update(overlay_mode_combo_fields(combo))
        self._binding["source"] = "mode"
        self.changed.emit(dict(self._binding))

    def _on_keys(self, keys) -> None:
        self._binding["keys"] = normalize_overlay_keys(keys)
        self._binding["source"] = "keyboard"
        self._binding["input_type"] = "keyboard"
        self.changed.emit(dict(self._binding))

    def _listen(self) -> None:
        dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.JoystickButton],
            callback=self._listen_done,
        )
        dialog.show()

    def _listen_done(self, event) -> None:
        gremlin.util.InvokeUiMethod(self._listen_done_ui, event)

    def _listen_done_ui(self, event) -> None:
        device = gremlin.joystick_handling.getDevice(event.device_guid)
        self._binding["source"] = "physical"
        self._binding["input_type"] = "button"
        self._binding["device_guid"] = str(event.device_guid)
        self._binding["device_name"] = device.name if device else ""
        self._binding["input_id"] = int(event.identifier)
        if hasattr(self, "_device_label_widget") and Shiboken.isValid(self._device_label_widget):
            self._device_label_widget.setText(self._device_label())
        self.changed.emit(dict(self._binding))


_CONDITION_KINDS = (
    ("mode", "Mode"),
    ("state", "State"),
    ("physical", "Physical button"),
    ("vjoy", "vJoy button"),
    ("keyboard", "Keyboard/mouse"),
)


def _condition_phrase(cond: dict) -> str:
    kind = str(cond.get("kind") or "mode").casefold()
    on = str(cond.get("when") or "on").casefold() != "off"
    if kind == "mode":
        _mid, name = resolve_overlay_mode(cond.get("mode_id"), cond.get("mode_name"))
        name = name or str(cond.get("mode_name") or "").strip() or "(pick a mode)"
        return f"mode {name} is {'current' if on else 'not current'}"
    if kind == "state":
        state = find_overlay_state(cond.get("state_id"), cond.get("state_name"))
        name = (state.key if state is not None else str(cond.get("state_name") or "").strip()) or "(pick a state)"
        return f"state {name} is {'on' if on else 'off'}"
    if kind == "keyboard":
        names = []
        for raw in cond.get("keys") or []:
            key = deserialize_overlay_key(raw)
            if key is None:
                continue
            names.append(gremlin.keyboard.KeyMap.get_name(key) or str(key.name or ""))
        combo = " + ".join(n for n in names if n) or "(pick a key)"
        return f"{combo} is {'pressed' if on else 'released'}"
    try:
        input_id = int(cond.get("input_id") or 0)
    except (TypeError, ValueError):
        input_id = 0
    device = str(cond.get("device_name") or "").strip()
    if kind == "vjoy":
        try:
            vjoy_id = int(cond.get("vjoy_id") or 0)
        except (TypeError, ValueError):
            vjoy_id = 0
        source = f"vJoy {vjoy_id}" if vjoy_id else (device or "vJoy")
    else:
        source = device or "physical"
    button = f"button {input_id}" if input_id else "button (not set)"
    return f"{source} {button} is {'pressed' if on else 'released'}"


def _condition_summary(vis: dict) -> str:
    phrases = [_condition_phrase(cond) for cond in vis.get("conditions") or []]
    if not phrases:
        return "Always applied (no conditions)."
    join = " and " if (vis.get("join") or "all") == "all" else " or "
    return f"If {join.join(phrases)} then this node runs."


def _physical_joystick_devices():
    devices = gremlin.joystick_handling.getPhysicalDevices() or []
    return sorted(devices, key=lambda d: (d.name or "").casefold())


def _device_from_combo(device_box: QtWidgets.QComboBox, kind: str):
    data = device_box.currentData()
    if kind == "vjoy":
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


def _button_choices(device) -> list[tuple[int, str]]:
    count = int(getattr(device, "button_count", 0) or 0) if device else 16
    return [(i, f"Button {i}") for i in range(1, max(1, count) + 1)]


class NodeConditionWidget(QtWidgets.QWidget):
    """Overlay-style AND/OR conditions. Unmet conditions skip the node."""

    changed = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._vis = decode_when(None)
        self._building = False
        self._listen_dialog = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        box = QtWidgets.QGroupBox("Conditions")
        self._form = QtWidgets.QFormLayout(box)
        layout.addWidget(box)

    def set_value(self, raw) -> None:
        self._vis = decode_when(raw)
        self._rebuild()

    def _is_alive(self) -> bool:
        try:
            return Shiboken.isValid(self)
        except Exception:
            return False

    def _emit(self, rebuild: bool = False) -> None:
        if self._building:
            return
        self._vis = decode_when(self._vis)
        self.changed.emit(dict(self._vis))
        if rebuild:
            self._rebuild()

    def _rebuild(self) -> None:
        self._building = True
        try:
            gremlin.util.clear_layout(self._form)
            vis = self._vis
            join = QtWidgets.QComboBox()
            join.addItem("All of these (AND)", "all")
            join.addItem("Any of these (OR)", "any")
            join.setCurrentIndex(1 if (vis.get("join") or "all") == "any" else 0)
            join.setToolTip("All = every condition must be true. Any = at least one condition must be true.")
            join.currentIndexChanged.connect(self._on_join)
            self._form.addRow("Match", join)
            hint = QtWidgets.QLabel(_condition_summary(vis))
            hint.setWordWrap(True)
            self._form.addRow(hint)
            note = QtWidgets.QLabel(
                "If conditions fail, this node is skipped and the in (or in_a) signal flows through. "
                "An output does not write. Empty conditions always apply."
            )
            note.setWordWrap(True)
            self._form.addRow(note)
            for cond in vis.get("conditions") or []:
                self._form.addRow(self._condition_box(cond))
            add_kind = QtWidgets.QComboBox()
            for value, label in _CONDITION_KINDS:
                add_kind.addItem(label, value)
            add_btn = QtWidgets.QPushButton("Add condition")
            add_btn.clicked.connect(lambda _=False, box=add_kind: self._add_condition(str(box.currentData() or "mode")))
            add_row = QtWidgets.QWidget()
            add_layout = QtWidgets.QHBoxLayout(add_row)
            add_layout.setContentsMargins(0, 0, 0, 0)
            add_layout.addWidget(add_kind, 1)
            add_layout.addWidget(add_btn)
            self._form.addRow("Add", add_row)
        finally:
            self._building = False

    def _on_join(self) -> None:
        combo = self.sender()
        if not isinstance(combo, QtWidgets.QComboBox):
            return
        self._vis["join"] = str(combo.currentData() or "all")
        self._emit(rebuild=True)

    def _add_condition(self, kind: str) -> None:
        self._vis.setdefault("conditions", []).append(default_visibility_condition(kind))
        self._emit(rebuild=True)

    def _remove_condition(self, cond_id: str) -> None:
        self._vis["conditions"] = [c for c in (self._vis.get("conditions") or []) if str(c.get("id") or "") != str(cond_id)]
        self._emit(rebuild=True)

    def _set_condition(self, cond_id: str, rebuild: bool = False, **fields) -> None:
        for cond in self._vis.get("conditions") or []:
            if str(cond.get("id") or "") != str(cond_id):
                continue
            cond.update(fields)
            self._emit(rebuild=rebuild)
            return

    def _condition_box(self, cond: dict) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox(_condition_phrase(cond))
        form = QtWidgets.QFormLayout(box)
        cond_id = str(cond.get("id") or "")
        kind = str(cond.get("kind") or "mode").casefold()
        kind_box = QtWidgets.QComboBox()
        for value, label in _CONDITION_KINDS:
            kind_box.addItem(label, value)
        index = kind_box.findData(kind)
        kind_box.setCurrentIndex(index if index >= 0 else 0)
        kind_box.currentIndexChanged.connect(
            lambda _i, combo=kind_box, cid=cond_id: self._set_condition(cid, rebuild=True, kind=str(combo.currentData() or "mode"))
        )
        form.addRow("If", kind_box)
        when = QtWidgets.QComboBox()
        if kind == "mode":
            when.addItem("is current", "on")
            when.addItem("is not current", "off")
        else:
            when.addItem("is on", "on")
            when.addItem("is off", "off")
        when.setCurrentIndex(1 if str(cond.get("when") or "on").casefold() == "off" else 0)
        when.currentIndexChanged.connect(
            lambda _i, combo=when, cid=cond_id: self._set_condition(cid, when=str(combo.currentData() or "on"))
        )
        form.addRow("When", when)
        if kind == "mode":
            combo = QtWidgets.QComboBox()
            populate_overlay_mode_combo(combo, cond.get("mode_id"), cond.get("mode_name"))
            combo.currentIndexChanged.connect(
                lambda _i, combo=combo, cid=cond_id: self._set_condition(
                    cid, **{k: v for k, v in overlay_mode_combo_fields(combo).items() if k != "input_type"}
                )
            )
            form.addRow("Mode", combo)
        elif kind == "state":
            combo = QtWidgets.QComboBox()
            populate_overlay_state_combo(combo, cond.get("state_id"), cond.get("state_name"))
            combo.currentIndexChanged.connect(
                lambda _i, combo=combo, cid=cond_id: self._set_condition(
                    cid, **{k: v for k, v in overlay_state_combo_fields(combo).items() if k != "input_type"}
                )
            )
            form.addRow("State", combo)
        elif kind == "keyboard":
            picker = OverlayKeyCombinationWidget(cond.get("keys") or [])
            picker.keys_changed.connect(
                lambda keys, cid=cond_id: self._set_condition(cid, keys=normalize_overlay_keys(keys))
            )
            form.addRow(picker)
        else:
            self._fill_button(form, cond)
        remove = QtWidgets.QPushButton("Remove")
        remove.clicked.connect(lambda _=False, cid=cond_id: self._remove_condition(cid))
        form.addRow("", remove)
        return box

    def _fill_button(self, form: QtWidgets.QFormLayout, cond: dict) -> None:
        kind = str(cond.get("kind") or "physical").casefold()
        cond_id = str(cond.get("id") or "")
        device_box = QtWidgets.QComboBox()
        if kind == "vjoy":
            for dev in gremlin.joystick_handling.vjoy_devices(connected_only=False) or []:
                device_box.addItem(f"vJoy {dev.vjoy_id} ({dev.name})", int(dev.vjoy_id))
            current = int(cond.get("vjoy_id") or 0)
            for i in range(device_box.count()):
                if int(device_box.itemData(i) or 0) == current:
                    device_box.setCurrentIndex(i)
                    break
        else:
            for dev in _physical_joystick_devices():
                device_box.addItem(dev.name, str(dev.device_guid))
            current = str(cond.get("device_guid") or "")
            for i in range(device_box.count()):
                guid = str(device_box.itemData(i) or "")
                if guid and guid.casefold() == current.casefold():
                    device_box.setCurrentIndex(i)
                    break

        def _device_changed():
            if not self._is_alive():
                return
            dev = _device_from_combo(device_box, kind)
            if not dev:
                return
            payload = {"device_name": dev.name, "device_guid": str(dev.device_guid)}
            if kind == "vjoy":
                payload["vjoy_id"] = int(dev.vjoy_id)
            self._set_condition(cond_id, rebuild=True, **payload)

        device_box.currentIndexChanged.connect(_device_changed)
        form.addRow("Device", device_box)
        listen = QtWidgets.QPushButton("Listen...")
        listen.setToolTip("Assign from the next physical or vJoy button press")
        listen.clicked.connect(lambda _=False, cid=cond_id: self._listen(cid))
        form.addRow("", listen)
        device = _device_from_combo(device_box, kind)
        id_box = QtWidgets.QComboBox()
        id_box.addItem("(none)", 0)
        try:
            current_id = int(cond.get("input_id") or 0)
        except (TypeError, ValueError):
            current_id = 0
        found = current_id <= 0
        if found:
            id_box.setCurrentIndex(0)
        for button_id, label in _button_choices(device):
            id_box.addItem(label, button_id)
            if int(button_id) == current_id:
                id_box.setCurrentIndex(id_box.count() - 1)
                found = True
        if not found:
            id_box.addItem(f"Button {current_id}", current_id)
            id_box.setCurrentIndex(id_box.count() - 1)
        id_box.currentIndexChanged.connect(
            lambda _i, cid=cond_id, combo=id_box: self._set_condition(
                cid, input_id=int(combo.currentData() if combo.currentData() is not None else 0)
            )
        )
        form.addRow("Button", id_box)

    def _listen(self, cond_id: str) -> None:
        def _captured(event):
            if not self._is_alive():
                return
            gremlin.util.InvokeUiMethod(self._listen_done, cond_id, event)

        previous = self._listen_dialog
        if previous is not None:
            try:
                if Shiboken.isValid(previous):
                    previous.close()
            except Exception:
                pass
            self._listen_dialog = None
        listener = gremlin.ui.ui_common.InputListenerWidget([InputType.JoystickButton], callback=_captured, parent=self)
        self._listen_dialog = listener
        listener.show()

    def _listen_done(self, cond_id: str, event) -> None:
        if not self._is_alive():
            return
        if getattr(event, "event_type", None) != InputType.JoystickButton:
            return
        device = gremlin.joystick_handling.getDevice(event.device_guid, show_error=False)
        virtual = bool(getattr(device, "is_virtual", False))
        self._set_condition(
            cond_id,
            rebuild=True,
            kind="vjoy" if virtual else "physical",
            device_guid=str(event.device_guid),
            device_name=device.name if device else str(event.device_guid),
            vjoy_id=int(getattr(device, "vjoy_id", 0) or 0),
            input_id=int(event.identifier),
        )


def _vjoy_output_devices() -> list:
    devices = [
        device
        for device in gremlin.joystick_handling.vjoy_devices(connected_only=False)
        if device is not None and int(getattr(device, "axis_count", 0) or 0) > 0
    ]
    devices.sort(key=lambda device: int(device.vjoy_id or 0))
    return devices


def _vjoy_device_label(device) -> str:
    vid = int(device.vjoy_id or 0)
    name = gremlin.joystick_handling.getDeviceName(device.device_guid) or f"VJoy ({vid})"
    if not getattr(device, "connected", True):
        return f"{name} (disconnected)"
    return name


def _vjoy_axis_ids(device) -> list[int]:
    ids = []
    count = int(getattr(device, "axis_count", 0) or 0)
    for index in range(count):
        try:
            axis_id = int(device.axis_sequence_to_input_id(index))
        except Exception:
            axis_id = index + 1
        if axis_id > 0 and axis_id not in ids:
            ids.append(axis_id)
    return ids or list(range(1, count + 1))


def _vjoy_axis_label(device, axis_id: int) -> str:
    try:
        if device is not None:
            return device.get_axis_name(int(axis_id))
    except Exception:
        pass
    return f"Axis {gremlin.joystick_handling.get_axis_name(int(axis_id))}"


def _output_target_label(vjoy_id: int, axis_id: int) -> str:
    device = gremlin.joystick_handling.vjoy_info_from_vjoy_id(int(vjoy_id), connected_only=False)
    axis = _vjoy_axis_label(device, axis_id)
    if device is not None:
        return f"VJoy {int(device.vjoy_id)} {axis}"
    return f"VJoy {int(vjoy_id)} {axis}"


class AfcsDesignerWidget(QtWidgets.QWidget):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.document: AfcsDocument = manager.document
        self._loading = False
        self._graph = None
        self._cleaned = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        hint = QtWidgets.QLabel(
            "AFCS — visual axis flow. Click Output to add a vJoy axis destination, then pick the device and axis in the inspector. "
            "Select nodes and right-click Copy / Paste (or Ctrl+C / Ctrl+V); paste works in this flight mode or another. "
            "Limiter scales travel from a 0–100% controller. Delete removes the selected node. Outputs are virtual axes only."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        top = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        root.addWidget(top, 1)

        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._show_live_box = QtWidgets.QCheckBox("Show live values while profile is active")
        self._show_live_box.setChecked(bool(gremlin.config.Configuration().afcs_show_live_while_running))
        self._show_live_box.setToolTip("When a profile is running, live meters stay off unless this is checked. They always show while the profile is stopped.")
        self._show_live_box.toggled.connect(self._on_show_live_toggled)
        left_layout.addWidget(self._show_live_box)
        left_layout.addWidget(QtWidgets.QLabel("Flight modes"))
        self._mode_list = QtWidgets.QListWidget()
        self._mode_list.currentRowChanged.connect(self._on_mode_row)
        self._mode_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._mode_list.customContextMenuRequested.connect(self._mode_context_menu)
        left_layout.addWidget(self._mode_list, 1)
        mode_buttons = QtWidgets.QHBoxLayout()
        add_mode = QtWidgets.QPushButton("Add")
        duplicate_mode = QtWidgets.QPushButton("Duplicate")
        rename_mode = QtWidgets.QPushButton("Rename")
        delete_mode = QtWidgets.QPushButton("Delete")
        add_mode.clicked.connect(self._add_mode)
        duplicate_mode.clicked.connect(self._duplicate_mode)
        rename_mode.clicked.connect(self._rename_mode)
        delete_mode.clicked.connect(self._delete_mode)
        duplicate_mode.setToolTip("Copy the selected flight mode, including its graph and activation.")
        mode_buttons.addWidget(add_mode)
        mode_buttons.addWidget(duplicate_mode)
        mode_buttons.addWidget(rename_mode)
        mode_buttons.addWidget(delete_mode)
        left_layout.addLayout(mode_buttons)
        left_layout.addWidget(QtWidgets.QLabel("Activation"))
        self._activation = ActivationBindingWidget()
        self._activation.changed.connect(self._on_activation)
        left_layout.addWidget(self._activation)
        top.addWidget(left)

        center = QtWidgets.QWidget()
        center_layout = QtWidgets.QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        tools = QtWidgets.QHBoxLayout()
        for kind, label in (
            ("input", "Input"),
            ("merge", "Merge"),
            ("curve", "Curve"),
            ("limiter", "Limiter"),
            ("deadzone", "Deadzone"),
            ("override", "Override"),
            ("laglead", "Lag-lead"),
            ("output", "Output"),
        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(lambda _=False, k=kind: self._add_node(k))
            tools.addWidget(button)
        delete_btn = QtWidgets.QPushButton("Delete")
        delete_btn.setToolTip("Delete the selected node(s). The Delete key also works.")
        delete_btn.clicked.connect(self._delete_selected_nodes)
        tools.addWidget(delete_btn)
        tools.addStretch()
        center_layout.addLayout(tools)
        if NodeGraph is None:
            missing = QtWidgets.QLabel("OdenGraphQt is not available. Install OdenGraphQt>=0.7.4 into the GEX venv.")
            missing.setWordWrap(True)
            center_layout.addWidget(missing, 1)
        else:
            self._graph = NodeGraph(parent=self)
            self._graph.register_nodes(list(AFCS_NODE_CLASSES))
            self._graph._afcs_node_created = self._on_graph_changed
            self._graph._afcs_property_changed = self._on_property_changed
            self._graph.nodes_deleted.connect(self._on_graph_changed)
            self._graph.port_connected.connect(self._on_graph_changed)
            self._graph.port_disconnected.connect(self._on_graph_changed)
            self._graph.node_double_clicked.connect(self._on_double_click)
            self._graph.node_selected.connect(self._on_node_selected)
            self._bind_edit_actions()
            center_layout.addWidget(self._graph.widget, 1)
        top.addWidget(center)

        right = QtWidgets.QWidget()
        right.setMinimumWidth(280)
        self._inspector_layout = QtWidgets.QVBoxLayout(right)
        self._inspector_layout.setContentsMargins(0, 0, 0, 0)
        self._inspector_layout.addWidget(QtWidgets.QLabel("Inspector"))
        self._inspector_body = QtWidgets.QWidget()
        self._inspector_form = QtWidgets.QFormLayout(self._inspector_body)
        self._inspector_layout.addWidget(self._inspector_body, 1)
        top.addWidget(right)
        top.setStretchFactor(0, 0)
        top.setStretchFactor(1, 1)
        top.setStretchFactor(2, 0)
        top.setSizes([220, 700, 280])

        self._meter_timer = QtCore.QTimer(self)
        self._meter_timer.setInterval(50)
        self._meter_timer.timeout.connect(self._refresh_meters)

        self._reload_modes()
        self._load_graph()

    def showEvent(self, event):
        super().showEvent(event)
        if gremlin.shared_state.is_running:
            timer = getattr(self.manager.runtime, "_timer", None)
            if timer is not None and timer.isActive():
                self.resume_live()
            return
        self.manager.runtime.start_preview()
        self.resume_live()

    def hideEvent(self, event):
        self.pause_live()
        try:
            self.manager.runtime.pause_preview()
        except Exception:
            pass
        super().hideEvent(event)

    def pause_live(self) -> None:
        try:
            self._meter_timer.stop()
        except Exception:
            pass

    def resume_live(self) -> None:
        if getattr(self, "_cleaned", False) or not self.isVisible():
            return
        try:
            self._meter_timer.start()
            self._refresh_meters()
        except Exception:
            pass

    @property
    def inputCount(self) -> int:
        return 0

    @property
    def inputWidgetCount(self) -> int:
        return 0

    def isLoaded(self) -> bool:
        return True

    def ensureLoaded(self):
        return None

    def refresh(self, emit=True, force=False, **kwargs):
        return None

    def refresh_ui(self):
        return None

    def _cleanup_ui(self, *_args):
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        try:
            self._meter_timer.stop()
        except Exception:
            pass
        if not gremlin.shared_state.is_running:
            try:
                self.manager.runtime.stop()
            except Exception:
                pass
        if getattr(self.manager, "designer", None) is self:
            self.manager.designer = None
        self._graph = None

    def reload(self) -> None:
        if gremlin.shared_state.is_running:
            return
        self._reload_modes()
        self._load_graph()

    def _current_mode_id(self) -> str | None:
        item = self._mode_list.currentItem()
        if item is None:
            mode = self.document.active_mode()
            return mode["id"] if mode else None
        return item.data(QtCore.Qt.UserRole)

    def _reload_modes(self) -> None:
        active = self.document.data.get("active_mode_id")
        with QtCore.QSignalBlocker(self._mode_list):
            self._mode_list.clear()
            selected = 0
            for index, mode in enumerate(self.document.modes()):
                item = QtWidgets.QListWidgetItem(mode["name"])
                item.setData(QtCore.Qt.UserRole, mode["id"])
                self._mode_list.addItem(item)
                if mode["id"] == active:
                    selected = index
            if self._mode_list.count():
                self._mode_list.setCurrentRow(selected)
        mode = self.document.active_mode()
        if mode:
            self._activation.set_binding(mode.get("activation"))

    def _on_mode_row(self, row: int) -> None:
        if row < 0:
            return
        item = self._mode_list.item(row)
        if item is None:
            return
        mode_id = item.data(QtCore.Qt.UserRole)
        previous = self.document.data.get("active_mode_id")
        if self._graph is not None and previous and previous != mode_id:
            self._capture_graph(previous)
        self.document.set_active_mode(mode_id)
        mode = self.document.mode_by_id(mode_id)
        if mode:
            self._activation.set_binding(mode.get("activation"))
        self._load_graph()
        self._rebuild_inspector(None)

    def _add_mode(self) -> None:
        if self._graph is not None:
            self._capture_graph()
        self.document.add_mode()
        self._reload_modes()
        self._load_graph()

    def _duplicate_mode(self) -> None:
        mode_id = self._current_mode_id()
        if not mode_id:
            return
        if self._graph is not None:
            self._capture_graph(mode_id)
        if self.document.duplicate_mode(mode_id) is None:
            return
        self._reload_modes()
        self._load_graph()
        self._rebuild_inspector(None)
        self.document.save_later()

    def _mode_context_menu(self, pos) -> None:
        item = self._mode_list.itemAt(pos)
        if item is not None:
            self._mode_list.setCurrentItem(item)
        menu = QtWidgets.QMenu(self)
        menu.addAction("Duplicate", self._duplicate_mode)
        menu.addAction("Rename", self._rename_mode)
        delete_action = menu.addAction("Delete", self._delete_mode)
        delete_action.setEnabled(len(self.document.modes()) > 1)
        menu.exec(self._mode_list.mapToGlobal(pos))

    def _rename_mode(self) -> None:
        mode_id = self._current_mode_id()
        mode = self.document.mode_by_id(mode_id) if mode_id else None
        if mode is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Rename flight mode", "Name", text=mode["name"])
        if ok:
            self.document.rename_mode(mode_id, name)
            self._reload_modes()

    def _delete_mode(self) -> None:
        mode_id = self._current_mode_id()
        if not mode_id or len(self.document.modes()) <= 1:
            return
        self.document.remove_mode(mode_id)
        self._reload_modes()
        self._load_graph()

    def _on_activation(self, binding: dict) -> None:
        mode_id = self._current_mode_id()
        if mode_id:
            self.document.set_mode_activation(mode_id, binding)
            self.document.save_later()

    def _add_node(self, kind: str) -> None:
        if self._graph is None:
            return
        mode_id = self._current_mode_id()
        mode = self.document.mode_by_id(mode_id) if mode_id else None
        if mode is None:
            return
        count = len(mode.get("nodes") or [])
        spec = default_node(kind, x=80 + count * 40, y=80 + count * 60)
        if kind == "output":
            vjoy_id, axis_id = self._next_output_target(mode)
            spec["props"]["vjoy_id"] = vjoy_id
            spec["props"]["axis_id"] = axis_id
            spec["name"] = _output_target_label(vjoy_id, axis_id)
        node_type = KIND_TO_TYPE[kind]
        graph_node = self._graph.create_node(node_type, name=spec["name"], pos=[spec["x"], spec["y"]], selected=True)
        self._apply_spec(graph_node, spec)
        self._capture_graph()
        self.document.save_later()
        self._rebuild_inspector(graph_node)

    def _bind_edit_actions(self) -> None:
        if self._graph is None:
            return
        try:
            graph_menu = self._graph.get_context_menu("graph")
            if graph_menu is not None:
                graph_menu.add_command("Copy", self._on_menu_copy)
                graph_menu.add_command("Paste", self._on_menu_paste)
                graph_menu.add_command("Delete selected", self._on_menu_delete)
            nodes_menu = self._graph.get_context_menu("nodes")
            if nodes_menu is not None:
                for cls in AFCS_NODE_CLASSES:
                    nodes_menu.add_command("Copy", self._on_menu_copy, node_class=cls)
                    nodes_menu.add_command("Paste", self._on_menu_paste, node_class=cls)
                    nodes_menu.add_command("Delete", self._on_menu_delete_node, node_class=cls)
        except Exception as err:
            syslog.warning(f"AFCS: node edit menu failed: {err}")
        shortcuts = (
            (QtGui.QKeySequence.Delete, self._delete_selected_nodes),
            (QtGui.QKeySequence(QtCore.Qt.Key_Backspace), self._delete_selected_nodes),
            (QtGui.QKeySequence.Copy, self._copy_selected_nodes),
            (QtGui.QKeySequence.Paste, self._paste_nodes),
            (QtGui.QKeySequence.Cut, self._cut_selected_nodes),
        )
        for key, callback in shortcuts:
            shortcut = QtGui.QShortcut(key, self._graph.widget)
            shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)

    def _on_menu_delete(self, _graph=None) -> None:
        self._delete_selected_nodes()

    def _on_menu_delete_node(self, _graph=None, node=None) -> None:
        if node is not None:
            self._delete_nodes([node])
            return
        self._delete_selected_nodes()

    def _on_menu_copy(self, _graph=None, node=None) -> None:
        self._copy_selected_nodes(fallback=node)

    def _on_menu_paste(self, _graph=None, node=None) -> None:
        self._paste_nodes()

    def _selected_afcs_nodes(self, fallback=None) -> list:
        if self._graph is None:
            return []
        selected = [node for node in self._graph.selected_nodes() if node is not None and hasattr(node, "AFCS_KIND")]
        if selected:
            return selected
        if fallback is not None and hasattr(fallback, "AFCS_KIND"):
            return [fallback]
        return []

    def _copy_selected_nodes(self, *_args, fallback=None) -> None:
        global _NODE_CLIPBOARD
        nodes = self._selected_afcs_nodes(fallback)
        if not nodes:
            return
        specs, connections = self._serialize_graph_nodes(nodes)
        if not specs:
            return
        _NODE_CLIPBOARD = {"nodes": specs, "connections": connections}

    def _cut_selected_nodes(self, *_args) -> None:
        self._copy_selected_nodes()
        self._delete_selected_nodes()

    def _paste_nodes(self, *_args) -> None:
        clip = _NODE_CLIPBOARD
        if self._graph is None or not clip or not clip.get("nodes"):
            return
        mode_id = self._current_mode_id()
        mode = self.document.mode_by_id(mode_id) if mode_id else None
        if mode is None:
            return
        used = self._vjoy_output_used(mode)
        created = {}
        offset = 48.0
        self._loading = True
        try:
            for spec in clip["nodes"]:
                kind = spec.get("kind")
                node_type = KIND_TO_TYPE.get(kind)
                if not node_type:
                    continue
                new_spec = copy.deepcopy(spec)
                new_spec["id"] = str(uuid.uuid4())
                new_spec["x"] = float(spec.get("x") or 0) + offset
                new_spec["y"] = float(spec.get("y") or 0) + offset
                if kind == "output":
                    props = new_spec.setdefault("props", {})
                    try:
                        vid = int(props.get("vjoy_id") or 1)
                        aid = int(props.get("axis_id") or 1)
                    except (TypeError, ValueError):
                        vid, aid = 1, 1
                    original_label = _output_target_label(vid, aid)
                    if (vid, aid) in used:
                        vid, aid = self._next_free_output(used)
                        props["vjoy_id"] = vid
                        props["axis_id"] = aid
                        if not spec.get("name") or spec.get("name") in ("Output", original_label):
                            new_spec["name"] = _output_target_label(vid, aid)
                    used.add((vid, aid))
                graph_node = self._graph.create_node(
                    node_type,
                    name=new_spec.get("name") or kind,
                    pos=[new_spec["x"], new_spec["y"]],
                    selected=False,
                    push_undo=False,
                )
                self._apply_spec(graph_node, new_spec)
                created[spec["id"]] = graph_node
            for conn in clip.get("connections") or []:
                src = created.get(conn.get("from"))
                dst = created.get(conn.get("to"))
                if src is None or dst is None:
                    continue
                out_port = src.get_output(conn.get("from_port") or "out")
                in_port = dst.get_input(conn.get("to_port") or "in")
                if out_port is None or in_port is None:
                    continue
                try:
                    in_port.connect_to(out_port, push_undo=False, emit_signal=False)
                except Exception:
                    pass
            self._graph.clear_selection()
            for graph_node in created.values():
                try:
                    graph_node.set_selected(True)
                except Exception:
                    pass
        finally:
            self._loading = False
        if not created:
            return
        self._capture_graph()
        self.document.save_later()
        self._rebuild_inspector(next(reversed(list(created.values()))))

    def _delete_selected_nodes(self, *_args) -> None:
        if self._graph is None:
            return
        self._delete_nodes(self._graph.selected_nodes())

    def _delete_nodes(self, nodes) -> None:
        if self._graph is None or not nodes:
            return
        to_remove = [node for node in nodes if node is not None and hasattr(node, "AFCS_KIND")]
        if not to_remove:
            return
        try:
            self._graph.delete_nodes(to_remove)
        except Exception as err:
            syslog.warning(f"AFCS: delete node failed: {err}")
            return
        self._capture_graph()
        self._rebuild_inspector(None)

    def _apply_spec(self, graph_node, spec: dict) -> None:
        if graph_node is None:
            return
        props = spec.get("props") or {}
        graph_node.set_property("afcs_id", spec["id"], push_undo=False)
        graph_node.set_name(spec.get("name") or graph_node.name())
        kind = spec.get("kind")
        if kind == "input":
            graph_node.set_property("source_name", props.get("source_name") or "", push_undo=False)
            graph_node.set_property("device_guid", props.get("device_guid") or "", push_undo=False)
            graph_node.set_property("device_name", props.get("device_name") or "", push_undo=False)
            graph_node.set_property("axis_id", int(props.get("axis_id") or 0), push_undo=False)
            graph_node.set_property("invert", bool(props.get("invert")), push_undo=False)
            graph_node.set_property("display_range", normalize_input_display_range(props.get("display_range")), push_undo=False)
        elif kind == "merge":
            graph_node.set_property("operation", operation_label(props.get("operation")), push_undo=False)
        elif kind == "curve":
            graph_node.set_property("curve_xml", props.get("curve_xml") or "", push_undo=False)
        elif kind == "limiter":
            graph_node.set_property("curve_xml", props.get("curve_xml") or "", push_undo=False)
            graph_node.set_property("range_mode", normalize_limiter_range(props.get("range_mode") if props.get("range_mode") is not None else props.get("centered")), push_undo=False)
            graph_node.set_property("shape", normalize_limiter_shape(props.get("shape")), push_undo=False)
            self._update_limiter_preview(graph_node)
        elif kind == "deadzone":
            graph_node.set_property("center", float(props.get("center") if props.get("center") is not None else 0.05), push_undo=False)
            graph_node.set_property("outer", float(props.get("outer") or 0.0), push_undo=False)
        elif kind == "override":
            graph_node.set_property("threshold", float(props.get("threshold") if props.get("threshold") is not None else 0.08), push_undo=False)
            graph_node.set_property("release", float(props.get("release") if props.get("release") is not None else 0.03), push_undo=False)
            graph_node.set_property("release_ms", float(props.get("release_ms") or 0.0), push_undo=False)
            graph_node.set_property("hold_until_in", bool(props.get("hold_until_in")), push_undo=False)
        elif kind == "laglead":
            graph_node.set_property("lag_ms", float(props.get("lag_ms") if props.get("lag_ms") is not None else 80.0), push_undo=False)
            graph_node.set_property("lead_ms", float(props.get("lead_ms") or 0.0), push_undo=False)
        elif kind == "output":
            vjoy_id = int(props.get("vjoy_id") or 1)
            axis_id = int(props.get("axis_id") or 1)
            graph_node.set_property("vjoy_id", vjoy_id, push_undo=False)
            graph_node.set_property("axis_id", axis_id, push_undo=False)
            if not spec.get("name") or spec.get("name") == "Output":
                graph_node.set_name(_output_target_label(vjoy_id, axis_id))
        graph_node.set_property("when_json", encode_when(props.get("when")), push_undo=False)

    def _load_graph(self) -> None:
        if self._graph is None:
            return
        self._loading = True
        try:
            self._graph.clear_session()
            mode = self.document.mode_by_id(self._current_mode_id())
            if mode is None:
                return
            created = {}
            for spec in mode.get("nodes") or []:
                node_type = KIND_TO_TYPE.get(spec.get("kind"))
                if not node_type:
                    continue
                graph_node = self._graph.create_node(
                    node_type,
                    name=spec.get("name") or spec.get("kind"),
                    pos=[spec.get("x") or 0, spec.get("y") or 0],
                    selected=False,
                    push_undo=False,
                )
                self._apply_spec(graph_node, spec)
                created[spec["id"]] = graph_node
            for conn in mode.get("connections") or []:
                src = created.get(conn["from"])
                dst = created.get(conn["to"])
                if src is None or dst is None:
                    continue
                out_port = src.get_output(conn.get("from_port") or "out")
                in_port = dst.get_input(conn.get("to_port") or "in")
                if out_port is None or in_port is None:
                    continue
                try:
                    in_port.connect_to(out_port, push_undo=False, emit_signal=False)
                except Exception:
                    pass
            self._graph.clear_selection()
            try:
                self._graph._undo_stack.clear()
            except Exception:
                pass
        finally:
            self._loading = False
        self._refresh_meters()

    def _graph_nodes(self) -> list:
        if self._graph is None:
            return []
        nodes = []
        for node in self._graph.all_nodes():
            if BaseNode is not None and not isinstance(node, BaseNode):
                continue
            if not hasattr(node, "AFCS_KIND"):
                continue
            nodes.append(node)
        return nodes

    def _spec_from_graph_node(self, graph_node) -> dict:
        kind = kind_for_node(graph_node)
        afcs_id = str(graph_node.get_property("afcs_id") or "")
        pos = graph_node.pos() or [0, 0]
        spec = default_node(kind, graph_node.name(), float(pos[0]), float(pos[1]))
        if afcs_id:
            spec["id"] = afcs_id
        else:
            graph_node.set_property("afcs_id", spec["id"], push_undo=False)
        props = spec["props"]
        if kind == "input":
            props["source_name"] = str(graph_node.get_property("source_name") or "")
            props["device_guid"] = str(graph_node.get_property("device_guid") or "")
            props["device_name"] = str(graph_node.get_property("device_name") or "")
            props["axis_id"] = int(graph_node.get_property("axis_id") or 0)
            props["invert"] = bool(graph_node.get_property("invert"))
            props["display_range"] = normalize_input_display_range(graph_node.get_property("display_range"))
        elif kind == "merge":
            props["operation"] = operation_from_label(graph_node.get_property("operation"))
        elif kind == "curve":
            props["curve_xml"] = str(graph_node.get_property("curve_xml") or "")
        elif kind == "limiter":
            props["curve_xml"] = str(graph_node.get_property("curve_xml") or "")
            props["range_mode"] = normalize_limiter_range(graph_node.get_property("range_mode"))
            props["shape"] = normalize_limiter_shape(graph_node.get_property("shape"))
        elif kind == "deadzone":
            props["center"] = float(graph_node.get_property("center") or 0.0)
            props["outer"] = float(graph_node.get_property("outer") or 0.0)
        elif kind == "override":
            props["threshold"] = float(graph_node.get_property("threshold") or 0.0)
            props["release"] = float(graph_node.get_property("release") or 0.0)
            props["release_ms"] = float(graph_node.get_property("release_ms") or 0.0)
            props["hold_until_in"] = bool(graph_node.get_property("hold_until_in"))
        elif kind == "laglead":
            props["lag_ms"] = float(graph_node.get_property("lag_ms") or 0.0)
            props["lead_ms"] = float(graph_node.get_property("lead_ms") or 0.0)
        elif kind == "output":
            props["vjoy_id"] = int(graph_node.get_property("vjoy_id") or 1)
            props["axis_id"] = int(graph_node.get_property("axis_id") or 1)
        props["when"] = decode_when(graph_node.get_property("when_json"))
        return spec

    def _serialize_graph_nodes(self, graph_nodes) -> tuple[list[dict], list[dict]]:
        nodes = []
        id_map = {}
        wanted = set()
        for graph_node in graph_nodes:
            spec = self._spec_from_graph_node(graph_node)
            nodes.append(spec)
            id_map[graph_node.id] = spec["id"]
            wanted.add(graph_node.id)
        connections = []
        for graph_node in graph_nodes:
            src_id = id_map.get(graph_node.id)
            if not src_id:
                continue
            for port in graph_node.output_ports():
                for other in port.connected_ports():
                    dst_node = other.node()
                    if getattr(dst_node, "id", None) not in wanted:
                        continue
                    dst_id = id_map.get(getattr(dst_node, "id", None))
                    if not dst_id:
                        continue
                    connections.append(
                        {
                            "from": src_id,
                            "from_port": port.name(),
                            "to": dst_id,
                            "to_port": other.name(),
                        }
                    )
        return nodes, connections

    def _capture_graph(self, mode_id: str | None = None) -> None:
        if self._graph is None or self._loading:
            return
        mode_id = mode_id or self._current_mode_id()
        if not mode_id:
            return
        nodes, connections = self._serialize_graph_nodes(self._graph_nodes())
        self.document.replace_graph(mode_id, nodes, connections)
        self.document.save_later()

    def _on_graph_changed(self, *args) -> None:
        if self._loading:
            return
        self._capture_graph()

    def _on_property_changed(self, node, name, value) -> None:
        if self._loading or name in ("live_meter", "live_curve"):
            return
        self._capture_graph()

    def _on_double_click(self, node) -> None:
        kind = kind_for_node(node)
        if kind not in ("curve", "limiter"):
            return
        data = curve_from_xml(str(node.get_property("curve_xml") or ""))
        dialog = gremlin.curve_handler.AxisCurveDialog(data, self)
        dialog.exec()
        node.set_property("curve_xml", curve_to_xml(data))
        if kind == "limiter":
            self._update_limiter_preview(node)
        self._capture_graph()

    def _on_node_selected(self, node) -> None:
        self._rebuild_inspector(node)

    def _rebuild_inspector(self, node) -> None:
        gremlin.util.clear_layout(self._inspector_form)
        if node is None or not hasattr(node, "AFCS_KIND"):
            hint = QtWidgets.QLabel("Select a node to edit it. Click Output to add a vJoy axis destination. Delete removes the selected node.")
            hint.setWordWrap(True)
            self._inspector_form.addRow(hint)
            return
        kind = kind_for_node(node)
        name = QtWidgets.QLineEdit(node.name())
        name.editingFinished.connect(lambda n=node, box=name: self._rename_node(n, box.text()))
        self._inspector_form.addRow("Name", name)
        self._help_label = QtWidgets.QLabel()
        self._help_label.setWordWrap(True)
        self._inspector_form.addRow(self._help_label)
        self._set_inspector_help(kind, operation_from_label(node.get_property("operation")) if kind == "merge" else None)
        if kind == "input":
            source = QtWidgets.QComboBox()
            source.setEditable(True)
            source.addItem("")
            for entry in self.document.enrollments():
                source.addItem(entry["name"])
            current = str(node.get_property("source_name") or "")
            index = source.findText(current)
            if index >= 0:
                source.setCurrentIndex(index)
            else:
                source.setEditText(current)
            source.currentTextChanged.connect(lambda text, n=node: self._set_node_prop(n, "source_name", text.strip()))
            self._inspector_form.addRow("Map to AFCS name", source)
            invert = QtWidgets.QCheckBox("Invert")
            invert.setChecked(bool(node.get_property("invert")))
            invert.toggled.connect(lambda checked, n=node: self._set_node_prop(n, "invert", checked))
            self._inspector_form.addRow(invert)
            display = QtWidgets.QComboBox()
            for mode in INPUT_DISPLAY_RANGES:
                display.addItem(INPUT_DISPLAY_LABELS[mode], mode)
            current_display = normalize_input_display_range(node.get_property("display_range"))
            index = display.findData(current_display)
            display.setCurrentIndex(index if index >= 0 else 0)
            display.setToolTip(
                "Invert first, then this range is the node's output. Hardware is always −1..+1. "
                "0 to 100% remaps that to 0..1 (idle at 0). Centered keeps ±1. Auto uses throttle/slider names like GEX."
            )
            display.currentIndexChanged.connect(lambda _i, n=node, box=display: self._set_node_prop(n, "display_range", box.currentData()))
            self._inspector_form.addRow("Display", display)
            listen = QtWidgets.QPushButton("Listen for physical axis...")
            listen.clicked.connect(lambda _=False, n=node: self._listen_axis(n))
            self._inspector_form.addRow(listen)
            guid = str(node.get_property("device_guid") or "")
            axis_id = int(node.get_property("axis_id") or 0)
            device_name = str(node.get_property("device_name") or "")
            if guid and axis_id:
                self._inspector_form.addRow(QtWidgets.QLabel(f"{device_name or guid} axis {axis_id}"))
        elif kind == "merge":
            combo = QtWidgets.QComboBox()
            for op in MERGE_OPS:
                combo.addItem(MERGE_OP_LABELS[op], op)
            current = operation_from_label(node.get_property("operation"))
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.currentIndexChanged.connect(lambda _i, n=node, box=combo: self._set_merge_op(n, box.currentData()))
            self._inspector_form.addRow("Operation", combo)
        elif kind == "curve":
            edit = QtWidgets.QPushButton("Edit curve...")
            edit.clicked.connect(lambda _=False, n=node: self._on_double_click(n))
            self._inspector_form.addRow(edit)
        elif kind == "limiter":
            shape = QtWidgets.QComboBox()
            for mode in LIMITER_SHAPES:
                shape.addItem(LIMITER_SHAPE_LABELS[mode], mode)
            current_shape = normalize_limiter_shape(node.get_property("shape"))
            shape_index = shape.findData(current_shape)
            shape.setCurrentIndex(shape_index if shape_index >= 0 else 0)
            shape.setToolTip("Linear scales throw. Bezier morphs GEX-style handles toward a flat center. Min-max follows 1:1 then clips at the live limiter axis from 100% down to 0%.")
            shape.currentIndexChanged.connect(lambda _i, n=node, box=shape: self._set_limiter_shape(n, box.currentData()))
            self._inspector_form.addRow("Shape", shape)
            combo = QtWidgets.QComboBox()
            for mode in LIMITER_RANGES:
                combo.addItem(LIMITER_RANGE_LABELS[mode], mode)
            current = normalize_limiter_range(node.get_property("range_mode"))
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.setToolTip("0 to 100%: slider or throttle over full travel. Centered (−100 to +100): stick; negative inverts the output.")
            combo.currentIndexChanged.connect(lambda _i, n=node, box=combo: self._set_node_prop(n, "range_mode", box.currentData()))
            self._inspector_form.addRow("Limit axis", combo)
            edit = QtWidgets.QPushButton("Edit full-throw curve...")
            edit.clicked.connect(lambda _=False, n=node: self._on_double_click(n))
            self._inspector_form.addRow(edit)
        elif kind == "deadzone":
            center = self._percent_spin(self._prop_float(node, "center", 0.05), lambda value, n=node: self._set_node_prop(n, "center", value / 100.0))
            outer = self._percent_spin(self._prop_float(node, "outer", 0.0), lambda value, n=node: self._set_node_prop(n, "outer", value / 100.0))
            self._inspector_form.addRow("Center deadzone", center)
            self._inspector_form.addRow("End deadzone", outer)
        elif kind == "override":
            take = self._percent_spin(self._prop_float(node, "threshold", 0.08), lambda value, n=node: self._set_node_prop(n, "threshold", value / 100.0))
            drop = self._percent_spin(self._prop_float(node, "release", 0.03), lambda value, n=node: self._set_node_prop(n, "release", value / 100.0))
            hold = self._ms_spin(self._prop_float(node, "release_ms", 0.0), lambda value, n=node: self._set_node_prop(n, "release_ms", value))
            hold.setToolTip("Stay inside the release band this long before handing back. 0 ms releases immediately. Use this so a quick pass through center does not drop the override.")
            until_in = QtWidgets.QCheckBox("Hold until in moves")
            until_in.setChecked(bool(node.get_property("hold_until_in")))
            until_in.setToolTip("After the stick is in the release band, keep the override until the in axis moves. Crossing center on the override stick does not hand back by itself.")
            until_in.toggled.connect(lambda checked, n=node: self._set_node_prop(n, "hold_until_in", checked))
            self._inspector_form.addRow("Take over", take)
            self._inspector_form.addRow("Release", drop)
            self._inspector_form.addRow("Release hold", hold)
            self._inspector_form.addRow(until_in)
        elif kind == "laglead":
            lag = self._ms_spin(self._prop_float(node, "lag_ms", 80.0), lambda value, n=node: self._set_node_prop(n, "lag_ms", value))
            lead = self._ms_spin(self._prop_float(node, "lead_ms", 0.0), lambda value, n=node: self._set_node_prop(n, "lead_ms", value))
            self._inspector_form.addRow("Lag", lag)
            self._inspector_form.addRow("Lead", lead)
        elif kind == "output":
            self._build_output_pickers(node)
        when_widget = NodeConditionWidget()
        when_widget.set_value(node.get_property("when_json"))
        when_widget.changed.connect(lambda vis, n=node: self._set_node_prop(n, "when_json", encode_when(vis)))
        self._inspector_form.addRow(when_widget)
        remove = QtWidgets.QPushButton("Delete node")
        remove.setToolTip("Remove this node from the graph")
        remove.clicked.connect(lambda _=False, n=node: self._delete_nodes([n]))
        self._inspector_form.addRow(remove)

    def _set_inspector_help(self, kind: str, operation: str | None = None) -> None:
        label = getattr(self, "_help_label", None)
        if label is None or not Shiboken.isValid(label):
            return
        label.setText(inspector_help(kind, operation))

    def _prop_float(self, node, key: str, default: float) -> float:
        try:
            value = node.get_property(key)
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    def _percent_spin(self, fraction: float, callback) -> QtWidgets.QDoubleSpinBox:
        box = QtWidgets.QDoubleSpinBox()
        box.setRange(0.0, 95.0)
        box.setSingleStep(0.5)
        box.setDecimals(1)
        box.setSuffix(" %")
        box.setValue(max(0.0, min(95.0, float(fraction) * 100.0)))
        box.valueChanged.connect(callback)
        return box

    def _ms_spin(self, value: float, callback) -> QtWidgets.QDoubleSpinBox:
        box = QtWidgets.QDoubleSpinBox()
        box.setRange(0.0, 5000.0)
        box.setSingleStep(10.0)
        box.setDecimals(0)
        box.setSuffix(" ms")
        box.setValue(max(0.0, min(5000.0, float(value))))
        box.valueChanged.connect(callback)
        return box

    def _vjoy_output_used(self, mode: dict, skip_id: str | None = None) -> set[tuple[int, int]]:
        used = set()
        for spec in mode.get("nodes") or []:
            if spec.get("kind") != "output":
                continue
            if skip_id and spec.get("id") == skip_id:
                continue
            props = spec.get("props") or {}
            try:
                used.add((int(props.get("vjoy_id") or 0), int(props.get("axis_id") or 0)))
            except (TypeError, ValueError):
                continue
        return used

    def _next_free_output(self, used: set[tuple[int, int]]) -> tuple[int, int]:
        for device in _vjoy_output_devices():
            vid = int(device.vjoy_id or 0)
            for axis_id in _vjoy_axis_ids(device):
                if (vid, axis_id) not in used:
                    return vid, axis_id
        devices = _vjoy_output_devices()
        if devices:
            return int(devices[0].vjoy_id or 1), (_vjoy_axis_ids(devices[0]) or [1])[0]
        return 1, 1

    def _next_output_target(self, mode: dict) -> tuple[int, int]:
        return self._next_free_output(self._vjoy_output_used(mode))

    def _build_output_pickers(self, node) -> None:
        devices = _vjoy_output_devices()
        if not devices:
            self._inspector_form.addRow(QtWidgets.QLabel("No vJoy devices are configured."))
            return
        current_vid = int(node.get_property("vjoy_id") or devices[0].vjoy_id or 1)
        current_axis = int(node.get_property("axis_id") or 1)
        device_combo = QtWidgets.QComboBox()
        for device in devices:
            device_combo.addItem(_vjoy_device_label(device), int(device.vjoy_id))
        index = device_combo.findData(current_vid)
        if index < 0:
            current_vid = int(devices[0].vjoy_id or 1)
            index = 0
        with QtCore.QSignalBlocker(device_combo):
            device_combo.setCurrentIndex(index)
        axis_combo = QtWidgets.QComboBox()

        def fill_axes(vjoy_id: int, selected_axis: int) -> None:
            device = gremlin.joystick_handling.vjoy_info_from_vjoy_id(int(vjoy_id), connected_only=False)
            with QtCore.QSignalBlocker(axis_combo):
                axis_combo.clear()
                axis_ids = _vjoy_axis_ids(device) if device is not None else [1]
                for axis_id in axis_ids:
                    axis_combo.addItem(_vjoy_axis_label(device, axis_id), axis_id)
                axis_index = axis_combo.findData(selected_axis)
                axis_combo.setCurrentIndex(axis_index if axis_index >= 0 else 0)

        fill_axes(current_vid, current_axis)
        device_combo.setMaxVisibleItems(20)
        axis_combo.setMaxVisibleItems(20)
        device_combo.setStyleSheet("QComboBox { combobox-popup: 0; }")
        axis_combo.setStyleSheet("QComboBox { combobox-popup: 0; }")

        def on_device() -> None:
            vjoy_id = int(device_combo.currentData() or 1)
            fill_axes(vjoy_id, int(axis_combo.currentData() or 1))
            self._set_output_target(node, vjoy_id, int(axis_combo.currentData() or 1))

        def on_axis() -> None:
            self._set_output_target(node, int(device_combo.currentData() or 1), int(axis_combo.currentData() or 1))

        device_combo.currentIndexChanged.connect(lambda _i: on_device())
        axis_combo.currentIndexChanged.connect(lambda _i: on_axis())
        self._inspector_form.addRow("vJoy", device_combo)
        self._inspector_form.addRow("Axis", axis_combo)

    def _set_output_target(self, node, vjoy_id: int, axis_id: int) -> None:
        previous = _output_target_label(int(node.get_property("vjoy_id") or 1), int(node.get_property("axis_id") or 1))
        node.set_property("vjoy_id", int(vjoy_id))
        node.set_property("axis_id", int(axis_id))
        label = _output_target_label(int(vjoy_id), int(axis_id))
        current_name = str(node.name() or "")
        if current_name in ("", "Output", previous):
            node.set_name(label)
        self._capture_graph()

    def _rename_node(self, node, name: str) -> None:
        node.set_name(name.strip() or node.name())
        self._capture_graph()

    def _set_node_prop(self, node, key: str, value) -> None:
        node.set_property(key, value)
        self._capture_graph()

    def _set_limiter_shape(self, node, shape: str) -> None:
        node.set_property("shape", normalize_limiter_shape(shape))
        self._update_limiter_preview(node)
        self._capture_graph()

    def _set_merge_op(self, node, op: str) -> None:
        node.set_property("operation", operation_label(op))
        self._set_inspector_help("merge", op)
        self._capture_graph()

    def _listen_axis(self, node) -> None:
        dialog = gremlin.ui.ui_common.InputListenerWidget([InputType.JoystickAxis], callback=lambda event, n=node: self._listen_axis_done(n, event))
        dialog.show()

    def _listen_axis_done(self, node, event) -> None:
        gremlin.util.InvokeUiMethod(self._listen_axis_done_ui, node, event)

    def _listen_axis_done_ui(self, node, event) -> None:
        device = gremlin.joystick_handling.getDevice(event.device_guid)
        node.set_property("device_guid", str(event.device_guid))
        node.set_property("device_name", device.name if device else "")
        node.set_property("axis_id", int(event.identifier))
        self._capture_graph()
        self._rebuild_inspector(node)

    def _on_show_live_toggled(self, checked: bool) -> None:
        gremlin.config.Configuration().afcs_show_live_while_running = bool(checked)
        self._refresh_meters()

    def _should_show_live(self) -> bool:
        if not gremlin.shared_state.is_running:
            return True
        return bool(self._show_live_box.isChecked())

    def _set_live_visible(self, widget, visible: bool) -> None:
        if widget is None:
            return
        try:
            widget.setVisible(visible)
        except Exception:
            pass
        inner = widget.get_custom_widget() if hasattr(widget, "get_custom_widget") else None
        if inner is not None:
            try:
                inner.setVisible(visible)
            except Exception:
                pass

    def _update_limiter_preview(self, node, gain: float | None = None) -> None:
        widget = node.get_widget("live_curve") if node is not None else None
        if widget is None or not hasattr(widget, "set_points"):
            return
        try:
            curve = curve_from_xml(str(node.get_property("curve_xml") or ""))
            shape = normalize_limiter_shape(node.get_property("shape"))
            current = 1.0 if gain is None else float(gain)
            widget.set_points(sample_limiter_curve(curve, current, shape))
            if hasattr(widget, "set_gain"):
                widget.set_gain(1.0 if shape in ("bezier", "minmax") else current)
        except Exception:
            pass

    def _meter_names_for_node(self, graph_node) -> tuple:
        names = [graph_node.name(), graph_node.get_property("source_name"), graph_node.get_property("device_name")]
        guid = str(graph_node.get_property("device_guid") or "")
        try:
            axis_id = int(graph_node.get_property("axis_id") or 0)
        except Exception:
            axis_id = 0
        if guid and axis_id:
            try:
                names.append(gremlin.joystick_handling.get_axis_name(axis_id))
            except Exception:
                pass
            try:
                device = gremlin.joystick_handling.getDevice(guid)
                getter = getattr(device, "get_axis_name", None) if device is not None else None
                if callable(getter):
                    names.append(getter(axis_id))
            except Exception:
                pass
        return tuple(names)

    def _refresh_meters(self) -> None:
        try:
            self._refresh_meters_ui()
        except Exception:
            return

    def _refresh_meters_ui(self) -> None:
        if self._graph is None or self._loading or getattr(self, "_cleaned", False):
            return
        live = self._should_show_live()
        if live:
            self.manager.runtime.evaluate(write_outputs=False)
        values = self.manager.runtime.last_values if live else {}
        gains = getattr(self.manager.runtime, "last_gains", {}) or {} if live else {}
        for graph_node in self._graph_nodes():
            afcs_id = str(graph_node.get_property("afcs_id") or "")
            meter = graph_node.get_widget("live_meter")
            self._set_live_visible(meter, live)
            if meter is not None:
                try:
                    kind = kind_for_node(graph_node)
                    props = {
                        "range_mode": graph_node.get_property("range_mode"),
                        "display_range": graph_node.get_property("display_range"),
                    }
                    names = self._meter_names_for_node(graph_node)
                    centered = meter_is_centered(kind, props, names)
                    if hasattr(meter, "set_centered"):
                        meter.set_centered(centered)
                    if hasattr(meter, "set_unit_unipolar"):
                        meter.set_unit_unipolar(kind == "input" and not centered)
                    meter.set_value(float(values.get(afcs_id, 0.0)) if live else 0.0)
                except Exception:
                    pass
            preview = graph_node.get_widget("live_curve")
            self._set_live_visible(preview, live)
            if preview is None:
                continue
            try:
                if kind_for_node(graph_node) == "limiter":
                    self._update_limiter_preview(graph_node, float(gains.get(afcs_id, 1.0)) if live else 1.0)
                elif hasattr(preview, "set_gain"):
                    preview.set_gain(float(gains.get(afcs_id, 1.0)) if live else 1.0)
            except Exception:
                pass
