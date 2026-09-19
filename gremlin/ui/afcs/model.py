# -*- coding: utf-8; -*-

"""AFCS document: flight modes, DAG nodes, sidecar JSON."""

from __future__ import annotations

import copy
import json
import logging
import os
import uuid
from typing import Any

from PySide6 import QtCore
from psygnal import Signal

import gremlin.shared_state
import gremlin.util
from gremlin.ui.obs_overlay.model import default_toggle_binding, normalize_toggle_binding, normalize_visibility

from .ops import normalize_input_display_range, normalize_limiter_range, normalize_limiter_shape, normalize_merge_op

syslog = logging.getLogger("system")

DOCUMENT_VERSION = 1
NODE_KINDS = ("input", "merge", "curve", "limiter", "deadzone", "override", "laglead", "output")


def _new_id() -> str:
    return str(uuid.uuid4())


def default_node_props(kind: str) -> dict[str, Any]:
    if kind == "input":
        return {
            "source_name": "",
            "device_guid": "",
            "device_name": "",
            "axis_id": 0,
            "invert": False,
            "display_range": "auto",
        }
    if kind == "merge":
        return {"operation": "add"}
    if kind == "curve":
        return {"curve_xml": ""}
    if kind == "limiter":
        return {"curve_xml": "", "range_mode": "unipolar", "shape": "linear"}
    if kind == "deadzone":
        return {"center": 0.05, "outer": 0.0}
    if kind == "override":
        return {"threshold": 0.08, "release": 0.03, "release_ms": 0.0, "hold_until_in": False}
    if kind == "laglead":
        return {"lag_ms": 80.0, "lead_ms": 0.0}
    if kind == "output":
        return {"vjoy_id": 1, "axis_id": 1}
    return {}


def decode_when(raw) -> dict[str, Any]:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raw = None
        else:
            try:
                raw = json.loads(text)
            except Exception:
                raw = None
    return normalize_visibility(raw)


def encode_when(raw) -> str:
    return json.dumps(decode_when(raw), separators=(",", ":"))


def when_is_active(props: dict[str, Any] | None) -> bool:
    raw = (props or {}).get("when")
    if not raw:
        return True
    if isinstance(raw, dict) and not raw.get("conditions"):
        return True
    if isinstance(raw, str) and not raw.strip():
        return True
    try:
        vis = decode_when(raw)
        if not vis.get("conditions"):
            return True
        from gremlin.ui.obs_overlay.bindings import widget_conditions_match

        return widget_conditions_match({"visibility": vis})
    except Exception:
        return True


def default_node(kind: str, name: str | None = None, x: float = 0, y: float = 0) -> dict[str, Any]:
    kind = kind if kind in NODE_KINDS else "input"
    labels = {
        "input": "Input",
        "merge": "Merge",
        "curve": "Curve",
        "limiter": "Limiter",
        "deadzone": "Deadzone",
        "override": "Override",
        "laglead": "Lag-lead",
        "output": "Output",
    }
    return {
        "id": _new_id(),
        "kind": kind,
        "name": name or labels[kind],
        "x": float(x),
        "y": float(y),
        "props": default_node_props(kind),
    }


def default_mode(name: str = "Default") -> dict[str, Any]:
    return {
        "id": _new_id(),
        "name": name,
        "activation": default_toggle_binding(),
        "nodes": [],
        "connections": [],
    }


def default_document() -> dict[str, Any]:
    mode = default_mode("Default")
    return {
        "version": DOCUMENT_VERSION,
        "active_mode_id": mode["id"],
        "modes": [mode],
        "enrollments": [],
    }


def _normalize_node(raw) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "input").casefold()
    if kind not in NODE_KINDS:
        kind = "input"
    node = default_node(kind, str(raw.get("name") or "").strip() or None)
    node["id"] = str(raw.get("id") or node["id"])
    try:
        node["x"] = float(raw.get("x") or 0)
        node["y"] = float(raw.get("y") or 0)
    except (TypeError, ValueError):
        node["x"] = 0.0
        node["y"] = 0.0
    props = default_node_props(kind)
    incoming = raw.get("props") if isinstance(raw.get("props"), dict) else {}
    props.update(incoming)
    if kind == "merge":
        props["operation"] = normalize_merge_op(props.get("operation"))
    if kind == "input":
        props["invert"] = bool(props.get("invert"))
        try:
            props["axis_id"] = int(props.get("axis_id") or 0)
        except (TypeError, ValueError):
            props["axis_id"] = 0
        props["source_name"] = str(props.get("source_name") or "").strip()
        props["device_guid"] = str(props.get("device_guid") or "")
        props["device_name"] = str(props.get("device_name") or "")
        props["display_range"] = normalize_input_display_range(props.get("display_range"))
    if kind == "output":
        try:
            props["vjoy_id"] = int(props.get("vjoy_id") or 1)
        except (TypeError, ValueError):
            props["vjoy_id"] = 1
        try:
            props["axis_id"] = int(props.get("axis_id") or 1)
        except (TypeError, ValueError):
            props["axis_id"] = 1
        props["vjoy_id"] = max(1, min(16, props["vjoy_id"]))
        props["axis_id"] = max(1, min(8, props["axis_id"]))
    if kind == "curve":
        props["curve_xml"] = str(props.get("curve_xml") or "")
    if kind == "limiter":
        props["curve_xml"] = str(props.get("curve_xml") or "")
        props["range_mode"] = normalize_limiter_range(props.get("range_mode") if props.get("range_mode") is not None else props.get("centered"))
        props["shape"] = normalize_limiter_shape(props.get("shape"))
        props.pop("centered", None)
    if kind == "deadzone":
        try:
            props["center"] = max(0.0, min(0.95, float(props.get("center") if props.get("center") is not None else 0.05)))
        except (TypeError, ValueError):
            props["center"] = 0.05
        try:
            props["outer"] = max(0.0, min(0.95, float(props.get("outer") or 0.0)))
        except (TypeError, ValueError):
            props["outer"] = 0.0
    if kind == "override":
        try:
            props["threshold"] = max(0.0, min(1.0, float(props.get("threshold") if props.get("threshold") is not None else 0.08)))
        except (TypeError, ValueError):
            props["threshold"] = 0.08
        try:
            props["release"] = max(0.0, min(1.0, float(props.get("release") if props.get("release") is not None else 0.03)))
        except (TypeError, ValueError):
            props["release"] = 0.03
        if props["release"] > props["threshold"]:
            props["release"] = props["threshold"]
        try:
            props["release_ms"] = max(0.0, min(5000.0, float(props.get("release_ms") or 0.0)))
        except (TypeError, ValueError):
            props["release_ms"] = 0.0
        props["hold_until_in"] = bool(props.get("hold_until_in"))
    if kind == "laglead":
        try:
            props["lag_ms"] = max(0.0, min(5000.0, float(props.get("lag_ms") if props.get("lag_ms") is not None else 80.0)))
        except (TypeError, ValueError):
            props["lag_ms"] = 80.0
        try:
            props["lead_ms"] = max(0.0, min(5000.0, float(props.get("lead_ms") or 0.0)))
        except (TypeError, ValueError):
            props["lead_ms"] = 0.0
    props["when"] = decode_when(props.get("when") if props.get("when") is not None else props.get("when_json"))
    props.pop("when_json", None)
    node["props"] = props
    return node


def _normalize_connection(raw) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    src = str(raw.get("from") or "").strip()
    dst = str(raw.get("to") or "").strip()
    if not src or not dst:
        return None
    return {
        "from": src,
        "from_port": str(raw.get("from_port") or "out"),
        "to": dst,
        "to_port": str(raw.get("to_port") or "in"),
    }


def _normalize_enrollment(raw) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    try:
        axis_id = int(raw.get("axis_id") or 0)
    except (TypeError, ValueError):
        axis_id = 0
    return {
        "id": str(raw.get("id") or _new_id()),
        "name": name,
        "device_guid": str(raw.get("device_guid") or ""),
        "device_name": str(raw.get("device_name") or ""),
        "axis_id": axis_id,
    }


def _normalize_mode(raw) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    mode = default_mode(str(raw.get("name") or "Mode").strip() or "Mode")
    mode["id"] = str(raw.get("id") or mode["id"])
    mode["activation"] = normalize_toggle_binding(raw.get("activation"))
    nodes = []
    seen = set()
    for item in raw.get("nodes") or []:
        node = _normalize_node(item)
        if node is None or node["id"] in seen:
            continue
        seen.add(node["id"])
        nodes.append(node)
    mode["nodes"] = nodes
    ids = {node["id"] for node in nodes}
    connections = []
    for item in raw.get("connections") or []:
        conn = _normalize_connection(item)
        if conn is None or conn["from"] not in ids or conn["to"] not in ids:
            continue
        connections.append(conn)
    mode["connections"] = connections
    return mode


def normalize_document(raw) -> dict[str, Any]:
    doc = default_document()
    if not isinstance(raw, dict):
        return doc
    modes = []
    seen = set()
    for item in raw.get("modes") or []:
        mode = _normalize_mode(item)
        if mode is None or mode["id"] in seen:
            continue
        seen.add(mode["id"])
        modes.append(mode)
    if not modes:
        modes = doc["modes"]
    doc["modes"] = modes
    active = str(raw.get("active_mode_id") or "")
    if active and any(mode["id"] == active for mode in modes):
        doc["active_mode_id"] = active
    else:
        doc["active_mode_id"] = modes[0]["id"]
    enrollments = []
    names = set()
    for item in raw.get("enrollments") or []:
        entry = _normalize_enrollment(item)
        if entry is None or entry["name"] in names:
            continue
        names.add(entry["name"])
        enrollments.append(entry)
    doc["enrollments"] = enrollments
    doc["version"] = DOCUMENT_VERSION
    return doc


def profile_xml_path(profile=None, dest_xml: str | None = None) -> str | None:
    if dest_xml:
        return dest_xml
    profile = profile or gremlin.shared_state.current_profile
    if profile is None:
        return None
    return getattr(profile, "profile_file", None) or getattr(profile, "_profile_fname", None)


def sidecar_path_for_profile(profile=None, dest_xml: str | None = None) -> str | None:
    path = profile_xml_path(profile, dest_xml)
    if not path:
        return None
    return gremlin.util.swap_ext(path, "afcs.json")


class AfcsDocument(QtCore.QObject):
    """In-memory AFCS graph; persisted next to the profile as <profile>.afcs.json."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.data = default_document()
        self._dirty = False
        self._save_later_pending = False
        self._profile_key: str | None = None
        self._suspend = 0

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.data)

    def from_dict(self, raw) -> None:
        self.data = normalize_document(raw)
        self._dirty = False
        self._emit()

    def modes(self) -> list[dict[str, Any]]:
        return list(self.data.get("modes") or [])

    def mode_by_id(self, mode_id: str | None) -> dict[str, Any] | None:
        if not mode_id:
            return None
        for mode in self.modes():
            if mode["id"] == mode_id:
                return mode
        return None

    def active_mode(self) -> dict[str, Any] | None:
        mode = self.mode_by_id(self.data.get("active_mode_id"))
        return mode or (self.modes()[0] if self.modes() else None)

    def set_active_mode(self, mode_id: str) -> None:
        if self.mode_by_id(mode_id) is None:
            return
        if self.data.get("active_mode_id") == mode_id:
            return
        self.data["active_mode_id"] = mode_id
        self._dirty = True
        self._emit()

    def _unique_mode_name(self, name: str) -> str:
        existing = {mode["name"] for mode in self.modes()}
        label = str(name or "").strip() or "Flight mode"
        if label not in existing:
            return label
        index = 2
        while f"{label} {index}" in existing:
            index += 1
        return f"{label} {index}"

    def add_mode(self, name: str = "Flight mode") -> dict[str, Any]:
        mode = default_mode(self._unique_mode_name(name))
        self.data["modes"].append(mode)
        self.data["active_mode_id"] = mode["id"]
        self._dirty = True
        self._emit()
        return mode

    def duplicate_mode(self, mode_id: str) -> dict[str, Any] | None:
        source = self.mode_by_id(mode_id)
        if source is None:
            return None
        cloned = copy.deepcopy(source)
        cloned["id"] = _new_id()
        cloned["name"] = self._unique_mode_name(f"{source['name']} copy")
        id_map = {}
        nodes = []
        for node in cloned.get("nodes") or []:
            old_id = str(node.get("id") or "")
            new_id = _new_id()
            id_map[old_id] = new_id
            node["id"] = new_id
            nodes.append(node)
        connections = []
        for conn in cloned.get("connections") or []:
            src = id_map.get(str(conn.get("from") or ""))
            dst = id_map.get(str(conn.get("to") or ""))
            if not src or not dst:
                continue
            conn["from"] = src
            conn["to"] = dst
            connections.append(conn)
        cloned["nodes"] = nodes
        cloned["connections"] = connections
        cloned["activation"] = normalize_toggle_binding(cloned.get("activation"))
        self.data["modes"].append(cloned)
        self.data["active_mode_id"] = cloned["id"]
        self._dirty = True
        self._emit()
        return cloned

    def remove_mode(self, mode_id: str) -> None:
        modes = self.modes()
        if len(modes) <= 1:
            return
        self.data["modes"] = [mode for mode in modes if mode["id"] != mode_id]
        if self.data.get("active_mode_id") == mode_id:
            self.data["active_mode_id"] = self.data["modes"][0]["id"]
        self._dirty = True
        self._emit()

    def rename_mode(self, mode_id: str, name: str) -> None:
        mode = self.mode_by_id(mode_id)
        if mode is None:
            return
        label = str(name or "").strip() or mode["name"]
        if mode["name"] == label:
            return
        mode["name"] = label
        self._dirty = True
        self._emit()

    def set_mode_activation(self, mode_id: str, binding: dict[str, Any]) -> None:
        mode = self.mode_by_id(mode_id)
        if mode is None:
            return
        mode["activation"] = normalize_toggle_binding(binding)
        self._dirty = True
        self._emit()

    def replace_graph(self, mode_id: str, nodes: list[dict[str, Any]], connections: list[dict[str, str]]) -> None:
        mode = self.mode_by_id(mode_id)
        if mode is None:
            return
        normalized = _normalize_mode({"id": mode["id"], "name": mode["name"], "activation": mode["activation"], "nodes": nodes, "connections": connections})
        if normalized is None:
            return
        mode["nodes"] = normalized["nodes"]
        mode["connections"] = normalized["connections"]
        self._dirty = True
        self._emit()

    def update_node_props(self, mode_id: str, node_id: str, **fields) -> None:
        mode = self.mode_by_id(mode_id)
        if mode is None:
            return
        for node in mode["nodes"]:
            if node["id"] != node_id:
                continue
            if "name" in fields and fields["name"] is not None:
                node["name"] = str(fields.pop("name") or node["name"])
            if "x" in fields:
                node["x"] = float(fields.pop("x"))
            if "y" in fields:
                node["y"] = float(fields.pop("y"))
            props = node.setdefault("props", default_node_props(node["kind"]))
            for key, value in fields.items():
                props[key] = value
            if node["kind"] == "merge":
                props["operation"] = normalize_merge_op(props.get("operation"))
            self._dirty = True
            self._emit()
            return

    def node_by_id(self, mode_id: str, node_id: str) -> dict[str, Any] | None:
        mode = self.mode_by_id(mode_id)
        if mode is None:
            return None
        for node in mode.get("nodes") or []:
            if node["id"] == node_id:
                return node
        return None

    def enrollments(self) -> list[dict[str, Any]]:
        return list(self.data.get("enrollments") or [])

    def ensure_enrollment(self, name: str, device_guid: str = "", device_name: str = "", axis_id: int = 0) -> dict[str, Any]:
        label = str(name or "").strip()
        if not label:
            label = "Axis"
        for entry in self.enrollments():
            if entry["name"] == label:
                entry["device_guid"] = str(device_guid or entry.get("device_guid") or "")
                entry["device_name"] = str(device_name or entry.get("device_name") or "")
                if axis_id:
                    entry["axis_id"] = int(axis_id)
                self._dirty = True
                self._emit()
                return entry
        entry = {
            "id": _new_id(),
            "name": label,
            "device_guid": str(device_guid or ""),
            "device_name": str(device_name or ""),
            "axis_id": int(axis_id or 0),
        }
        self.data.setdefault("enrollments", []).append(entry)
        self._ensure_input_node(label)
        self._dirty = True
        self._emit()
        return entry

    def _ensure_input_node(self, source_name: str) -> None:
        mode = self.active_mode() or (self.modes()[0] if self.modes() else None)
        if mode is None:
            return
        for node in mode.get("nodes") or []:
            if node.get("kind") == "input" and (node.get("props") or {}).get("source_name") == source_name:
                return
        count = len(mode.get("nodes") or [])
        node = default_node("input", source_name, x=40, y=40 + count * 90)
        node["props"]["source_name"] = source_name
        mode.setdefault("nodes", []).append(node)

    def mark_dirty(self) -> None:
        self._dirty = True
        self._emit()

    @property
    def dirty(self) -> bool:
        return self._dirty

    def _emit(self) -> None:
        if self._suspend:
            return
        try:
            self.changed.emit()
        except Exception:
            pass

    def load_for_profile(self, profile=None) -> bool:
        profile = profile or gremlin.shared_state.current_profile
        path = sidecar_path_for_profile(profile)
        self._profile_key = profile_xml_path(profile)
        data = None
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    data = loaded
            except Exception as err:
                syslog.warning(f"AFCS: failed to load {path}: {err}")
        self.from_dict(data if data is not None else default_document())
        self._dirty = False
        return data is not None

    def save_to_profile(self, profile=None, dest_xml: str | None = None) -> bool:
        path = sidecar_path_for_profile(profile, dest_xml)
        if not path:
            return False
        try:
            folder = os.path.dirname(path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.to_dict(), handle, indent=2)
            self._dirty = False
            self._profile_key = profile_xml_path(profile, dest_xml)
            return True
        except Exception as err:
            syslog.error(f"AFCS: failed to save {path}: {err}")
            return False

    def save_later(self) -> None:
        if not QtCore.QCoreApplication.instance():
            return
        if not gremlin.util.is_ui_thread():
            gremlin.util.InvokeUiMethod(self.save_later)
            return
        if self._save_later_pending:
            return
        self._save_later_pending = True
        QtCore.QTimer.singleShot(0, self._save_later_run)

    def _save_later_run(self) -> None:
        self._save_later_pending = False
        if not self._dirty:
            return
        try:
            self.save_to_profile()
        except Exception:
            pass
