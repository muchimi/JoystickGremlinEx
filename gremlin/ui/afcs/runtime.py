# -*- coding: utf-8; -*-

"""Evaluate the AFCS DAG and write vJoy. Live meters share the last pass."""

from __future__ import annotations

import logging
import time
from typing import Any

from lxml import etree as ElementTree
from PySide6 import QtCore

import gremlin.curve_handler
import gremlin.joystick_handling
import gremlin.remote
import gremlin.shared_state
import gremlin.util
from gremlin.ui.obs_overlay.bindings import binding_is_configured, read_axis, read_toggle_active
from gremlin.util import clamp

from .model import AfcsDocument, when_is_active
from .ops import LagLeadState, OverrideState, apply_deadzone, apply_limiter, limiter_gain, merge_values, normalize_limiter_range, normalize_limiter_shape

syslog = logging.getLogger("system")


class AfcsBus:
    """Named axis values pushed by Map to AFCS."""

    def __init__(self):
        self._values: dict[str, float] = {}

    def set(self, name: str, value: float) -> None:
        key = str(name or "").strip()
        if not key:
            return
        self._values[key] = clamp(float(value))

    def get(self, name: str) -> float | None:
        key = str(name or "").strip()
        if not key:
            return None
        if key not in self._values:
            return None
        return self._values[key]

    def clear(self) -> None:
        self._values.clear()


def curve_from_xml(xml: str) -> gremlin.curve_handler.AxisCurveData:
    data = gremlin.curve_handler.AxisCurveData()
    text = str(xml or "").strip()
    if not text:
        data.curve_update()
        return data
    try:
        node = ElementTree.fromstring(text)
        data._parse_xml(node)
    except Exception as err:
        syslog.warning(f"AFCS: curve parse failed: {err}")
    data.curve_update()
    return data


def curve_to_xml(data: gremlin.curve_handler.AxisCurveData) -> str:
    try:
        node = data._generate_xml()
        return ElementTree.tostring(node, encoding="unicode")
    except Exception:
        return ""


def _incoming(mode: dict[str, Any]) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for conn in mode.get("connections") or []:
        mapping.setdefault(conn["to"], {})[conn["to_port"]] = conn["from"]
    return mapping


def _node_map(mode: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: node for node in mode.get("nodes") or []}


def _physical_axis(guid: str, axis_id: int) -> float:
    if not guid or not axis_id:
        return 0.0
    binding = {"source": "physical", "device_guid": guid, "input_type": "axis", "input_id": axis_id}
    return float(read_axis(binding, axis_id, invert=False))


def _enrollment_axis(source_name: str, enrollments) -> tuple[str, int]:
    if not source_name:
        return "", 0
    for entry in enrollments or []:
        if str(entry.get("name") or "") != source_name:
            continue
        guid = str(entry.get("device_guid") or "")
        try:
            axis_id = int(entry.get("axis_id") or 0)
        except (TypeError, ValueError):
            axis_id = 0
        return guid, axis_id
    return "", 0


def _read_input(node: dict[str, Any], bus: AfcsBus, enrollments=None) -> float:
    props = node.get("props") or {}
    source_name = str(props.get("source_name") or "").strip()
    value = None
    if source_name and gremlin.shared_state.is_running:
        enrolled = bus.get(source_name)
        if enrolled is not None:
            value = enrolled
    if value is None:
        guid = str(props.get("device_guid") or "")
        try:
            axis_id = int(props.get("axis_id") or 0)
        except (TypeError, ValueError):
            axis_id = 0
        if (not guid or not axis_id) and source_name:
            enrolled_guid, enrolled_axis = _enrollment_axis(source_name, enrollments)
            guid = guid or enrolled_guid
            axis_id = axis_id or enrolled_axis
        value = _physical_axis(guid, axis_id)
    if props.get("invert"):
        value = -value
    return clamp(float(value))


def _write_output(
    vjoy_id: int,
    axis_id: int,
    value: float,
    is_local: bool = True,
    is_remote: bool = False,
    client_list: list | None = None,
) -> None:
    vid = int(vjoy_id)
    aid = int(axis_id)
    current = float(value)
    if is_local:
        try:
            axis = gremlin.joystick_handling.VJoyProxy()[vid].axis(aid)
            if axis is not None:
                axis.value = current
        except Exception as err:
            syslog.debug(f"AFCS: vJoy write failed {vid}:{aid}: {err}")
    if is_remote:
        try:
            gremlin.remote.remote_client.send_axis(vid, aid, current, client_list=client_list)
        except Exception as err:
            syslog.debug(f"AFCS: remote vJoy write failed {vid}:{aid}: {err}")


def resolve_active_mode(document: AfcsDocument) -> dict[str, Any] | None:
    modes = document.modes()
    if not modes:
        return None
    matched = []
    unbound = []
    for mode in modes:
        binding = mode.get("activation")
        if binding_is_configured(binding):
            if read_toggle_active(binding):
                matched.append(mode)
        else:
            unbound.append(mode)
    if matched:
        return matched[0]
    if unbound:
        return unbound[0]
    return None


class AfcsRuntime:
    def __init__(self, document: AfcsDocument, bus: AfcsBus):
        self.document = document
        self.bus = bus
        self.last_values: dict[str, float] = {}
        self.last_gains: dict[str, float] = {}
        self.last_mode_id: str | None = None
        self._curves: dict[str, gremlin.curve_handler.AxisCurveData] = {}
        self._timer: QtCore.QTimer | None = None
        self._write = False
        self.output_configs: list = []
        self._dyn_state: dict[str, Any] = {}
        self._eval_time: float | None = None

    def _output_routing(self, use_runtime_state: bool = True) -> tuple[bool, bool, list | None]:
        configs = self.output_configs or []
        if not configs:
            return True, False, None
        is_local = False
        is_remote = False
        clients: list = []
        saw_custom = False
        for cfg in configs:
            if not getattr(cfg, "isCustom", False):
                is_local = True
                continue
            saw_custom = True
            if use_runtime_state:
                loc, rem = cfg.state
            else:
                loc, rem = bool(cfg.local), bool(cfg.remote)
            is_local = is_local or loc
            is_remote = is_remote or rem
            if rem:
                clients.extend(cfg.getClientList() or [])
        if not saw_custom:
            return True, False, None
        if 0 in clients:
            client_list = [0]
        else:
            client_list = list(dict.fromkeys(clients)) or None
        return is_local, is_remote, client_list

    def reset(self, zero_outputs: bool = True) -> None:
        self.bus.clear()
        self.last_values = {}
        self.last_gains = {}
        self.last_mode_id = None
        self._dyn_state = {}
        self._eval_time = None
        if zero_outputs:
            self._zero_outputs()

    def start(self, write_outputs: bool = True) -> None:
        self.reset(zero_outputs=False)
        self._write = write_outputs
        self._ensure_timer()
        if self._timer is not None:
            self._timer.start()

    def halt(self) -> None:
        """Stop the evaluate timer without acquiring or writing vJoy."""
        self._write = False
        if self._timer is not None:
            self._timer.stop()

    def stop(self) -> None:
        self.halt()
        routing = self._output_routing(use_runtime_state=False)
        self.bus.clear()
        self.last_values = {}
        self.last_gains = {}
        self.last_mode_id = None
        self._dyn_state = {}
        self._eval_time = None
        self._zero_outputs(routing)

    def start_preview(self) -> None:
        if gremlin.shared_state.is_running:
            return
        self.start(write_outputs=False)

    def pause_preview(self) -> None:
        if gremlin.shared_state.is_running:
            return
        self.halt()

    def _zero_outputs(self, routing: tuple[bool, bool, list | None] | None = None) -> None:
        is_local, is_remote, client_list = routing if routing is not None else self._output_routing(use_runtime_state=False)
        for mode in self.document.modes():
            for node in mode.get("nodes") or []:
                if node.get("kind") != "output":
                    continue
                props = node.get("props") or {}
                try:
                    _write_output(
                        int(props.get("vjoy_id") or 1),
                        int(props.get("axis_id") or 1),
                        0.0,
                        is_local=is_local,
                        is_remote=is_remote,
                        client_list=client_list,
                    )
                except Exception:
                    pass

    def _ensure_timer(self) -> None:
        if self._timer is not None:
            return
        if QtCore.QCoreApplication.instance() is None:
            return
        timer = QtCore.QTimer()
        timer.setInterval(50)
        timer.timeout.connect(self.tick)
        self._timer = timer

    def tick(self) -> None:
        write = self._write and bool(gremlin.shared_state.is_running)
        try:
            self.evaluate(write_outputs=write)
        except Exception as err:
            syslog.warning(f"AFCS: evaluate failed: {err}")

    def evaluate(self, write_outputs: bool = False) -> dict[str, float]:
        try:
            return self._evaluate(write_outputs)
        except Exception as err:
            syslog.warning(f"AFCS: evaluate failed: {err}")
            return self.last_values

    def _evaluate(self, write_outputs: bool = False) -> dict[str, float]:
        if write_outputs:
            mode = resolve_active_mode(self.document)
        else:
            mode = self.document.active_mode() or resolve_active_mode(self.document)
        self.last_mode_id = mode["id"] if mode else None
        if mode is None:
            self.last_values = {}
            self.last_gains = {}
            return self.last_values
        now = time.monotonic()
        dt = 0.05 if self._eval_time is None else min(0.25, max(0.001, now - self._eval_time))
        self._eval_time = now
        nodes = _node_map(mode)
        incoming = _incoming(mode)
        values: dict[str, float] = {}
        visiting: set[str] = set()
        routing = self._output_routing() if write_outputs else (True, False, None)
        gains: dict[str, float] = {}
        enrollments = self.document.enrollments()

        def value_of(node_id: str) -> float:
            if node_id in values:
                return values[node_id]
            if node_id in visiting:
                return 0.0
            node = nodes.get(node_id)
            if node is None:
                return 0.0
            visiting.add(node_id)
            kind = node.get("kind")
            props = node.get("props") or {}
            ports = incoming.get(node_id) or {}
            if not when_is_active(props):
                if kind in ("override", "laglead"):
                    self._dyn_state.pop(node_id, None)
                if kind == "limiter":
                    gains[node_id] = 1.0
                if "in" in ports:
                    value = value_of(ports["in"])
                elif "in_a" in ports:
                    value = value_of(ports["in_a"])
                else:
                    value = 0.0
                visiting.discard(node_id)
                values[node_id] = value
                return value
            if kind == "input":
                value = _read_input(node, self.bus, enrollments)
            elif kind == "merge":
                a = value_of(ports["in_a"]) if "in_a" in ports else 0.0
                b = value_of(ports["in_b"]) if "in_b" in ports else 0.0
                value = merge_values(props.get("operation"), a, b)
            elif kind == "curve":
                src = value_of(ports["in"]) if "in" in ports else 0.0
                xml = str(props.get("curve_xml") or "")
                curve = self._curves.get(xml)
                if curve is None:
                    curve = curve_from_xml(xml)
                    self._curves[xml] = curve
                value = clamp(float(curve.curve_value(src)))
            elif kind == "limiter":
                src = value_of(ports["in"]) if "in" in ports else 0.0
                limit = value_of(ports["limit"]) if "limit" in ports else 1.0
                range_mode = normalize_limiter_range(props.get("range_mode") if props.get("range_mode") is not None else props.get("centered"))
                shape = normalize_limiter_shape(props.get("shape"))
                gain = limiter_gain(limit, range_mode)
                gains[node_id] = gain
                xml = str(props.get("curve_xml") or "")
                curve = self._curves.get(xml)
                if curve is None:
                    curve = curve_from_xml(xml)
                    self._curves[xml] = curve
                value = apply_limiter(float(curve.curve_value(src)), limit, range_mode, shape)
            elif kind == "deadzone":
                src = value_of(ports["in"]) if "in" in ports else 0.0
                try:
                    center = float(props.get("center") if props.get("center") is not None else 0.05)
                except (TypeError, ValueError):
                    center = 0.05
                try:
                    outer = float(props.get("outer") or 0.0)
                except (TypeError, ValueError):
                    outer = 0.0
                value = apply_deadzone(src, center, outer)
            elif kind == "override":
                default = value_of(ports["in"]) if "in" in ports else 0.0
                stick = value_of(ports["override"]) if "override" in ports else default
                try:
                    threshold = float(props.get("threshold") if props.get("threshold") is not None else 0.08)
                except (TypeError, ValueError):
                    threshold = 0.08
                try:
                    release = float(props.get("release") if props.get("release") is not None else 0.03)
                except (TypeError, ValueError):
                    release = 0.03
                try:
                    release_ms = float(props.get("release_ms") or 0.0)
                except (TypeError, ValueError):
                    release_ms = 0.0
                hold_until_in = bool(props.get("hold_until_in"))
                state = self._dyn_state.get(node_id)
                if not isinstance(state, OverrideState):
                    state = OverrideState()
                    self._dyn_state[node_id] = state
                value = state.process(default, stick, threshold, release, dt, release_ms, hold_until_in)
            elif kind == "laglead":
                src = value_of(ports["in"]) if "in" in ports else 0.0
                try:
                    lag_ms = float(props.get("lag_ms") if props.get("lag_ms") is not None else 80.0)
                except (TypeError, ValueError):
                    lag_ms = 80.0
                try:
                    lead_ms = float(props.get("lead_ms") or 0.0)
                except (TypeError, ValueError):
                    lead_ms = 0.0
                state = self._dyn_state.get(node_id)
                if not isinstance(state, LagLeadState):
                    state = LagLeadState()
                    self._dyn_state[node_id] = state
                value = state.process(src, dt, lag_ms / 1000.0, lead_ms / 1000.0)
            elif kind == "output":
                value = value_of(ports["in"]) if "in" in ports else 0.0
                if write_outputs:
                    is_local, is_remote, client_list = routing
                    _write_output(
                        int(props.get("vjoy_id") or 1),
                        int(props.get("axis_id") or 1),
                        value,
                        is_local=is_local,
                        is_remote=is_remote,
                        client_list=client_list,
                    )
            else:
                value = 0.0
            visiting.discard(node_id)
            values[node_id] = value
            return value

        for node_id in nodes:
            value_of(node_id)
        self.last_values = values
        self.last_gains = gains
        return values
