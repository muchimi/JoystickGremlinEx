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


""" Loopback device

    This virtual device is internal to GEX and lets profiles simulate joystick input internally without requiring physical hardware.
    The profile can define any number of named axis and button inputs, and map them to action as if they were real hardware inputs.
    The virtual mapper can write to these inputs as with any normal virtual output.
    Conditions can also use this device to apply logic based on the simulated inputs and current values.

"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import RLock
from time import monotonic
from uuid import UUID, uuid4

from lxml import etree
from PySide6.QtCore import QObject, Signal

from dinput import DeviceSummary
from gremlin import shared_state
from gremlin.input_types import InputType
from gremlin.types import DeviceCategory, DeviceType

AXIS = InputType.JoystickAxis
BUTTON = InputType.JoystickButton
PREFIX = {AXIS: "axis", BUTTON: "button"}
DEFAULT = {AXIS: 0.0, BUTTON: False}
_input_chain = ContextVar("loopback_input_chain", default=())


@contextmanager
def dispatch_context(event):
    token = _input_chain.set(event.extra_data["loopback_input_chain"])
    try:
        yield
    finally:
        _input_chain.reset(token)


def make_summary():
    device = DeviceSummary()
    device.device_guid = shared_state.loopback_tab_guid
    device.name = "Loopback"
    device.device_type = DeviceType.Loopback
    device.device_category = DeviceCategory.Special
    device.virtual_id = 0
    device.input_enabled = True
    device.data["button_names"] = {}
    device.setConnected(True)
    return device


@dataclass
class Control:
    name: str
    start: float | bool
    guid: str = field(default_factory=lambda: str(uuid4()))


class Loopback(QObject):
    definitions_changed = Signal()

    def __init__(self):
        super().__init__()
        self.device = make_summary()
        self.device.setAxisCallback(lambda index: round(self.read(AXIS, index) * 32767))
        self.device.setButtonCallback(lambda index: self.read(BUTTON, index))
        self.controls = {kind: {} for kind in PREFIX}
        self._values = {kind: {} for kind in PREFIX}
        self._next_id = {kind: 1 for kind in PREFIX}
        self._missing_guids = {kind: {} for kind in PREFIX}
        self._lock = RLock()

    def name_available(self, name, *, exclude=None):
        return bool(name) and all(
            control.name != name or (kind, index) == exclude
            for kind, controls in self.controls.items() for index, control in controls.items()
        )

    def next_name(self, kind):
        used = {control.name for controls in self.controls.values() for control in controls.values()}
        index = 1
        while f"{PREFIX[kind]}-{index}" in used:
            index += 1
        return f"{PREFIX[kind]}-{index}"

    def add(self, kind, name):
        if not self.name_available(name):
            raise ValueError("Input names must be unique")
        index = self._add_control(kind, name)
        self._update_summary()
        self.definitions_changed.emit()
        return index

    def add_generic_controls(self, axis_count, button_count):
        """Add a preset's controls without changing existing definitions."""
        with self._lock:
            for kind, count in ((AXIS, axis_count), (BUTTON, button_count)):
                for _ in range(count):
                    self._add_control(kind, self.next_name(kind))
            self._update_summary()
        self.definitions_changed.emit()

    def _add_control(self, kind, name):
        index = self._next_id[kind]
        self._next_id[kind] += 1
        self.controls[kind][index] = Control(name, DEFAULT[kind])
        return index

    def rename(self, kind, index, name):
        if not self.name_available(name, exclude=(kind, index)):
            raise ValueError("Input names must be unique")
        self.controls[kind][index].name = name
        self._update_summary()
        self.definitions_changed.emit()

    def remove(self, keys):
        with self._lock:
            for kind, index in keys:
                control = self.controls[kind].pop(index, None)
                if control is not None:
                    self._missing_guids[kind][index] = control.guid
                self._values[kind].pop(index, None)
            self._update_summary()
        self.definitions_changed.emit()

    def reference_guid(self, kind, index):
        control = self.controls[kind].get(index)
        return control.guid if control is not None else self._missing_guids[kind].get(index)

    def resolve_references(self, root):
        from .profile_xml import resolve_references

        resolve_references(self, root)

    def annotate_references(self, root):
        from .profile_xml import annotate_references

        annotate_references(self, root)

    def missing_reference_slot(self, kind, guid, previous_slot):
        """Reserve an unused slot for an unresolved GUID so it cannot redirect a mapping."""
        index = previous_slot
        if index <= 0 or self.reference_guid(kind, index) is not None:
            index = self._next_id[kind]
        self._next_id[kind] = max(self._next_id[kind], index + 1)
        self._missing_guids[kind][index] = guid
        return index

    def _update_summary(self):
        axes = self.controls[AXIS]
        buttons = self.controls[BUTTON]
        self.device.axis_count = len(axes)
        self.device.button_count = len(buttons)
        self.device.axis_names = {index: control.name for index, control in axes.items()}
        self.device.axis_id_map = {index: linear for linear, index in enumerate(axes, 1)}
        self.device.linear_id_map = {linear: index for index, linear in self.device.axis_id_map.items()}
        self.device.data["button_names"] = {index: control.name for index, control in buttons.items()}

    def prepare_mode(self, profile, mode):
        """Materialize defined controls while preserving existing mappings."""
        from gremlin.input_item import InputItem

        device_node = profile.get_device_modes(self.device.device_guid, DeviceType.Loopback, "loopback")
        device_node.device = self.device
        node = device_node.ensure_mode_exists(mode)
        items = []
        for kind, controls in self.controls.items():
            for index, control in controls.items():
                item = node.getInputItem(kind, index)
                if item is None:
                    item = InputItem(node, input_type=kind, input_id=index)
                    node.addInputItem(item)
                item.setInputNameHandler(lambda _, definition=control: definition.name)
                items.append(item)
        return items

    def read(self, kind, index):
        with self._lock:
            return self._values[kind].get(index, DEFAULT[kind])

    def write(self, kind, index, value):
        with self._lock:
            if index not in self.controls[kind] or (kind, index) in _input_chain.get():
                return
            value = bool(value) if kind == BUTTON else min(1.0, max(-1.0, float(value)))
            if value == self.read(kind, index):
                return
            self._values[kind][index] = value
            self._emit(kind, index, value)

    def _emit(self, kind, index, value):
        if getattr(shared_state.current_profile, "loopback", None) is not self:
            return
        from gremlin.event_handler import AxisState, Event, EventListener

        extra_data = {"source_input_type": InputType.Loopback, "loopback_input_chain": (*_input_chain.get(), (kind, index))}
        curved_value = None
        if kind == AXIS:
            curved_value = AxisState().applyCurve(self.device.device_guid, index, value)
            if curved_value is not None:
                extra_data["curved"] = True
        event = Event(
            kind, index, self.device.device_guid, value=value, raw_value=value, curved_value=curved_value,
            is_pressed=kind == BUTTON and value, is_axis=kind == AXIS, is_virtual=True,
            extra_data=extra_data,
        )
        EventListener().queueJoystickEventList([event])

    def start(self, *, emit=True):
        with self._lock:
            for kind, controls in self.controls.items():
                values = self._values[kind]
                for index, control in controls.items():
                    old_value = values.get(index, DEFAULT[kind])
                    values[index] = control.start
                    if emit and (old_value != control.start or control.start != DEFAULT[kind]):
                        self._emit(kind, index, control.start)

    def is_axis_valid(self, axis_id=None, linear_index=None):
        index = axis_id if axis_id is not None else self.device.linear_id_map.get(linear_index)
        return index in self.controls[AXIS]

    def is_button_valid(self, index):
        return index in self.controls[BUTTON]

    def is_hat_valid(self, index):
        return False

    def axis(self, axis_id=None, linear_index=None):
        index = axis_id if axis_id is not None else self.device.linear_id_map.get(linear_index)
        return LoopbackAxis(self, index)

    def button(self, index):
        return LoopbackButton(self, index)

    def from_xml(self, node):
        for kind in PREFIX:
            self.controls[kind].clear()
            self._values[kind].clear()
            self._next_id[kind] = 1
            self._missing_guids[kind].clear()
        if node is None:
            self._update_summary()
            return
        used_names = set()
        used_guids = set()
        for kind, prefix in PREFIX.items():
            controls = self.controls[kind]
            for child in node.findall(prefix):
                try:
                    index = int(child.get("id", "0"))
                    start = child.get("start", "0")
                    start = start.casefold() in ("1", "true") if kind == BUTTON else min(1.0, max(-1.0, float(start)))
                except ValueError:
                    continue
                name = child.get("name", "").strip()
                if index <= 0 or index in controls or not name or name in used_names:
                    continue
                try:
                    guid = str(UUID(child.get("guid", "")))
                except ValueError:
                    guid = str(uuid4())
                if guid in used_guids:
                    guid = str(uuid4())
                controls[index] = Control(name, start, guid)
                used_names.add(name)
                used_guids.add(guid)
            next_id = node.get(f"next-{prefix}-id", "1")
            self._next_id[kind] = max(int(next_id) if next_id.isdecimal() else 1, max(controls, default=0) + 1)
        self._update_summary()

    def to_xml(self):
        if all(index == 1 for index in self._next_id.values()):
            return None
        node = etree.Element("loopback")
        for kind, prefix in PREFIX.items():
            node.set(f"next-{prefix}-id", str(self._next_id[kind]))
            for index, control in self.controls[kind].items():
                start = str(int(control.start)) if kind == BUTTON else str(control.start)
                etree.SubElement(node, prefix, id=str(index), guid=control.guid, name=control.name, start=start)
        return node


@dataclass
class LoopbackAxis:
    loopback: Loopback
    index: int

    @property
    def value(self):
        return self.loopback.read(AXIS, self.index)

    @value.setter
    def value(self, value):
        self.set_absolute_value(value)

    @property
    def last_output(self):
        return self.value, monotonic()

    def set_absolute_value(self, value):
        self.loopback.write(AXIS, self.index, value)


@dataclass
class LoopbackButton:
    loopback: Loopback
    index: int

    @property
    def is_pressed(self):
        return self.loopback.read(BUTTON, self.index)

    @is_pressed.setter
    def is_pressed(self, value):
        self.loopback.write(BUTTON, self.index, value)
