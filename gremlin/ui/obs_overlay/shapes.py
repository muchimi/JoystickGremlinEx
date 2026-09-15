# -*- coding: utf-8; -*-

from __future__ import annotations

import copy
import json
import math
import os
import uuid
from typing import Any

from PySide6 import QtCore, QtGui

CUSTOM_KIND_PREFIX = "custom:"


SHAPE_KINDS = (
    "rectangle",
    "circle",
    "triangle",
    "diamond",
    "line",
    "freeform",
)

SHAPE_KIND_LABELS = (
    ("rectangle", "Rectangle"),
    ("circle", "Circle"),
    ("triangle", "Triangle"),
    ("diamond", "Diamond"),
    ("line", "Line"),
    ("freeform", "Freeform"),
)

_SHAPE_KIND_TOOLTIPS = {
    "rectangle": "Filled rectangle. Use Corner radius for rounded corners.",
    "circle": "Circle inscribed in the widget.",
    "triangle": "Three points. Double-click the outline to add a point, then drag points to move them.",
    "diamond": "Four points. Double-click the outline to add a point, then drag points to move them.",
    "line": "Open or closed polyline. Double-click the outline to add a point, then drag points to move them.",
    "freeform": (
        "Double-click the outline to add a point, then drag points to move them. "
        "Yellow handles are Bézier controls — drag them to curve a corner. "
        "Hold Ctrl to snap a handle to 15° steps (0, 15, 30, 45…). "
        "Hold Alt and drag a handle to move it independently of the opposite handle."
    ),
}


_CUSTOM_SHAPES_CACHE: list[dict[str, Any]] | None = None
_CIRCLE_KAPPA = 0.5522847498307936


def is_custom_kind(kind) -> bool:
    return str(kind or "").casefold().startswith(CUSTOM_KIND_PREFIX)


def custom_shapes_path() -> str:
    try:
        import gremlin.shared_state
        root = gremlin.shared_state.data_path
    except Exception:
        root = None
    if not root:
        root = os.path.join(os.path.expanduser("~"), "Joystick Gremlin Ex")
    return os.path.join(root, "overlay_custom_shapes.json")


def list_custom_shapes() -> list[dict[str, Any]]:
    global _CUSTOM_SHAPES_CACHE
    if _CUSTOM_SHAPES_CACHE is not None:
        return _CUSTOM_SHAPES_CACHE
    path = custom_shapes_path()
    if not os.path.isfile(path):
        _CUSTOM_SHAPES_CACHE = []
        return _CUSTOM_SHAPES_CACHE
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        shapes = payload.get("shapes") if isinstance(payload, dict) else payload
        if not isinstance(shapes, list):
            shapes = []
        cleaned: list[dict[str, Any]] = []
        for entry in shapes:
            if not isinstance(entry, dict):
                continue
            kind = str(entry.get("id") or "").strip()
            label = str(entry.get("label") or "").strip()
            if not kind.startswith(CUSTOM_KIND_PREFIX) or not label:
                continue
            points = _library_points(entry.get("points"))
            if len(points) < 2:
                continue
            cleaned.append({
                "id": kind,
                "label": label,
                "closed": bool(entry.get("closed", True)),
                "points": points,
            })
        _CUSTOM_SHAPES_CACHE = cleaned
    except Exception:
        _CUSTOM_SHAPES_CACHE = []
    return _CUSTOM_SHAPES_CACHE


def _library_points(raw: Any) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    if not isinstance(raw, list):
        return points
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            x = max(0.0, min(1.0, float(item.get("x", 0.0))))
            y = max(0.0, min(1.0, float(item.get("y", 0.0))))
        except (TypeError, ValueError):
            continue
        try:
            in_x = float(item.get("in_x") or 0)
            in_y = float(item.get("in_y") or 0)
            out_x = float(item.get("out_x") or 0)
            out_y = float(item.get("out_y") or 0)
        except (TypeError, ValueError):
            in_x = in_y = out_x = out_y = 0.0
        points.append({"x": x, "y": y, "in_x": in_x, "in_y": in_y, "out_x": out_x, "out_y": out_y})
    return points


def _write_custom_shapes(shapes: list[dict[str, Any]]) -> None:
    global _CUSTOM_SHAPES_CACHE
    path = custom_shapes_path()
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "shapes": shapes}, handle, indent=2)
    _CUSTOM_SHAPES_CACHE = copy.deepcopy(shapes)


def custom_shape(kind: str) -> dict[str, Any] | None:
    kind = str(kind or "")
    for entry in list_custom_shapes():
        if entry.get("id") == kind:
            return entry
    return None


def save_custom_shape(label: str, points: list[dict[str, Any]], closed: bool = True) -> str:
    label = str(label or "").strip()
    if not label:
        raise ValueError("Name is required.")
    points = _library_points(points)
    if len(points) < 2:
        raise ValueError("Need at least two points to save a shape.")
    shapes = copy.deepcopy(list_custom_shapes())
    existing = next(
        (entry for entry in shapes if str(entry.get("label") or "").casefold() == label.casefold()),
        None,
    )
    if existing is None:
        kind = f"{CUSTOM_KIND_PREFIX}{uuid.uuid4().hex[:12]}"
        shapes.append({
            "id": kind,
            "label": label,
            "closed": bool(closed),
            "points": points,
        })
        _write_custom_shapes(shapes)
        return kind
    existing["label"] = label
    existing["closed"] = bool(closed)
    existing["points"] = points
    _write_custom_shapes(shapes)
    return str(existing["id"])


def shape_kind_choices() -> list[tuple[str, str]]:
    items = list(SHAPE_KIND_LABELS)
    for entry in list_custom_shapes():
        items.append((entry["id"], entry["label"]))
    return items


def shape_kind_tooltip(kind) -> str:
    kind = normalize_shape_kind(kind)
    if is_custom_kind(kind):
        entry = custom_shape(kind)
        name = (entry or {}).get("label") or "Custom shape"
        return f"{name}. Drag points to edit. Right-click the shape to save another copy."
    return _SHAPE_KIND_TOOLTIPS.get(kind, "")


def normalize_shape_kind(value) -> str:
    raw = str(value or "rectangle").strip()
    kind = raw.casefold().replace(" ", "_")
    if kind in ("rect", "rounded", "panel"):
        return "rectangle"
    if kind in ("ellipse", "oval"):
        return "circle"
    if kind in ("poly", "polygon", "bezier"):
        return "freeform"
    if kind in ("lines", "polyline"):
        return "line"
    if is_custom_kind(raw):
        return raw if raw.startswith(CUSTOM_KIND_PREFIX) else kind
    return kind if kind in SHAPE_KINDS else "rectangle"


def is_shape_widget(item: dict[str, Any] | None) -> bool:
    return bool(item) and item.get("type") in ("shape", "panel")


def button_uses_shape_path(item: dict[str, Any] | None) -> bool:
    if not item or item.get("type") != "button":
        return False
    style = item.get("style") or {}
    return bool(style.get("shape_kind")) or bool(item.get("points"))


def uses_shape_geometry(item: dict[str, Any] | None) -> bool:
    return is_shape_widget(item) or button_uses_shape_path(item)


def uses_editable_points(item: dict[str, Any] | None) -> bool:
    if not uses_shape_geometry(item):
        return False
    kind = normalize_shape_kind((item.get("style") or {}).get("shape_kind"))
    return kind in ("triangle", "diamond", "line", "freeform") or is_custom_kind(kind)


def uses_bezier_edit(item: dict[str, Any] | None) -> bool:
    if not uses_editable_points(item):
        return False
    kind = normalize_shape_kind((item.get("style") or {}).get("shape_kind"))
    return kind == "freeform" or is_custom_kind(kind)


def _point(x: float, y: float, in_x: float = 0.0, in_y: float = 0.0, out_x: float = 0.0, out_y: float = 0.0) -> dict[str, float]:
    return {
        "x": float(x),
        "y": float(y),
        "in_x": float(in_x),
        "in_y": float(in_y),
        "out_x": float(out_x),
        "out_y": float(out_y),
    }


def default_shape_points(kind: str) -> list[dict[str, float]]:
    kind = normalize_shape_kind(kind)
    if is_custom_kind(kind):
        entry = custom_shape(kind)
        if entry and entry.get("points"):
            return copy.deepcopy(entry["points"])
        return [_point(0.08, 0.08), _point(0.92, 0.08), _point(0.92, 0.92), _point(0.08, 0.92)]
    if kind == "triangle":
        return [_point(0.5, 0.04), _point(0.96, 0.96), _point(0.04, 0.96)]
    if kind == "diamond":
        return [_point(0.5, 0.04), _point(0.96, 0.5), _point(0.5, 0.96), _point(0.04, 0.5)]
    if kind == "line":
        return [_point(0.04, 0.5), _point(0.96, 0.5)]
    if kind == "freeform":
        return [_point(0.08, 0.08), _point(0.92, 0.08), _point(0.92, 0.92), _point(0.08, 0.92)]
    return []


def snapshot_shape_points(item: dict[str, Any]) -> tuple[list[dict[str, float]], bool]:
    """Normalized points + closed flag for saving a library shape."""
    kind = normalize_shape_kind((item.get("style") or {}).get("shape_kind"))
    if kind == "circle" and not uses_editable_points(item):
        return _inscribed_ellipse_points(item), True
    if kind == "rectangle" and not uses_editable_points(item):
        return [_point(0.0, 0.0), _point(1.0, 0.0), _point(1.0, 1.0), _point(0.0, 1.0)], True
    points = copy.deepcopy(ensure_shape_points(item))
    if len(points) < 2:
        if kind == "circle":
            return _inscribed_ellipse_points(item), True
        return [_point(0.0, 0.0), _point(1.0, 0.0), _point(1.0, 1.0), _point(0.0, 1.0)], True
    return points, bool(shape_closed(item))


def _inscribed_ellipse_points(item: dict[str, Any]) -> list[dict[str, float]]:
    width = max(1.0, float(item.get("w") or 1))
    height = max(1.0, float(item.get("h") or 1))
    rx = min(width, height) / 2.0 / width
    ry = min(width, height) / 2.0 / height
    kx = _CIRCLE_KAPPA * rx
    ky = _CIRCLE_KAPPA * ry
    return [
        _point(0.5, 0.5 - ry, -kx, 0.0, kx, 0.0),
        _point(0.5 + rx, 0.5, 0.0, -ky, 0.0, ky),
        _point(0.5, 0.5 + ry, kx, 0.0, -kx, 0.0),
        _point(0.5 - rx, 0.5, 0.0, ky, 0.0, -ky),
    ]


def normalize_shape_points(raw, kind: str | None = None) -> list[dict[str, float]]:
    points = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        try:
            x = max(0.0, min(1.0, float(entry.get("x", 0))))
            y = max(0.0, min(1.0, float(entry.get("y", 0))))
        except (TypeError, ValueError):
            continue
        try:
            in_x = float(entry.get("in_x") or 0)
            in_y = float(entry.get("in_y") or 0)
            out_x = float(entry.get("out_x") or 0)
            out_y = float(entry.get("out_y") or 0)
        except (TypeError, ValueError):
            in_x = in_y = out_x = out_y = 0.0
        points.append({"x": x, "y": y, "in_x": in_x, "in_y": in_y, "out_x": out_x, "out_y": out_y})
    if len(points) < 2:
        return default_shape_points(kind or "freeform")
    return points


def ensure_shape_points(item: dict[str, Any]) -> list[dict[str, float]]:
    kind = normalize_shape_kind((item.get("style") or {}).get("shape_kind"))
    points = normalize_shape_points(item.get("points"), kind)
    if kind == "freeform" and points and not any(_has_handles(point) for point in points):
        closed = shape_closed(item)
        for index in range(len(points)):
            _apply_tangent_handles(points, index, closed)
    item["points"] = points
    return points


def shape_closed(item: dict[str, Any]) -> bool:
    style = item.get("style") or {}
    kind = normalize_shape_kind(style.get("shape_kind"))
    if kind == "line":
        return bool(style.get("shape_closed"))
    if "shape_closed" in style:
        return bool(style.get("shape_closed"))
    return kind != "line"


def _abs_point(item: dict[str, Any], point: dict[str, float]) -> QtCore.QPointF:
    return QtCore.QPointF(
        float(item["x"]) + float(point["x"]) * float(item["w"]),
        float(item["y"]) + float(point["y"]) * float(item["h"]),
    )


def _handle_point(item: dict[str, Any], point: dict[str, float], prefix: str) -> QtCore.QPointF:
    origin = _abs_point(item, point)
    return QtCore.QPointF(
        origin.x() + float(point.get(f"{prefix}_x") or 0) * float(item["w"]),
        origin.y() + float(point.get(f"{prefix}_y") or 0) * float(item["h"]),
    )


def snap_handle_offset(dx: float, dy: float, width: float, height: float, step_deg: float = 15.0) -> tuple[float, float]:
    """Snap a Bézier handle offset to the nearest visual angle step (default 15°)."""
    px = float(dx) * max(1.0, float(width))
    py = float(dy) * max(1.0, float(height))
    length = math.hypot(px, py)
    if length < 1e-6:
        return dx, dy
    step = float(step_deg) or 15.0
    angle = round(math.degrees(math.atan2(py, px)) / step) * step
    rad = math.radians(angle)
    return (math.cos(rad) * length) / max(1.0, float(width)), (math.sin(rad) * length) / max(1.0, float(height))


def _has_handles(point: dict[str, float]) -> bool:
    return any(abs(float(point.get(key) or 0)) > 0.0005 for key in ("in_x", "in_y", "out_x", "out_y"))


def _apply_tangent_handles(points: list[dict[str, float]], index: int, closed: bool) -> None:
    """Place in/out handles at 1/3 of the adjacent segments so a rectangle stays straight but is editable."""
    count = len(points)
    if count < 2 or index < 0 or index >= count:
        return
    cur = points[index]
    if closed:
        prev = points[(index - 1) % count]
        nxt = points[(index + 1) % count]
    else:
        prev = points[index - 1] if index > 0 else None
        nxt = points[index + 1] if index + 1 < count else None
        if prev is None and nxt is not None:
            prev = {"x": cur["x"] - (nxt["x"] - cur["x"]), "y": cur["y"] - (nxt["y"] - cur["y"])}
        elif nxt is None and prev is not None:
            nxt = {"x": cur["x"] - (prev["x"] - cur["x"]), "y": cur["y"] - (prev["y"] - cur["y"])}
    if prev is None or nxt is None:
        return
    cur["in_x"] = (prev["x"] - cur["x"]) / 3.0
    cur["in_y"] = (prev["y"] - cur["y"]) / 3.0
    cur["out_x"] = (nxt["x"] - cur["x"]) / 3.0
    cur["out_y"] = (nxt["y"] - cur["y"]) / 3.0


def shape_path(item: dict[str, Any]) -> QtGui.QPainterPath:
    style = item.get("style") or {}
    kind = normalize_shape_kind(style.get("shape_kind"))
    rect = QtCore.QRectF(item["x"], item["y"], item["w"], item["h"])
    path = QtGui.QPainterPath()
    if kind == "rectangle":
        radius = float(style.get("corner_radius") or 0)
        if radius > 0:
            path.addRoundedRect(rect, radius, radius)
        else:
            path.addRect(rect)
        return path
    if kind == "circle":
        side = min(rect.width(), rect.height())
        path.addEllipse(QtCore.QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side))
        return path
    points = ensure_shape_points(item)
    if len(points) < 2:
        path.addRect(rect)
        return path
    first = _abs_point(item, points[0])
    path.moveTo(first)
    count = len(points)
    last_index = count if shape_closed(item) else count - 1
    for i in range(last_index):
        current = points[i]
        nxt = points[(i + 1) % count]
        dest = _abs_point(item, nxt)
        if _has_handles(current) or _has_handles(nxt):
            path.cubicTo(_handle_point(item, current, "out"), _handle_point(item, nxt, "in"), dest)
        else:
            path.lineTo(dest)
    if shape_closed(item) and count >= 3:
        path.closeSubpath()
    return path


def scene_to_normalized(item: dict[str, Any], pos: QtCore.QPointF, clamp: bool = True) -> tuple[float, float]:
    w = max(1.0, float(item.get("w") or 1))
    h = max(1.0, float(item.get("h") or 1))
    nx = (pos.x() - float(item["x"])) / w
    ny = (pos.y() - float(item["y"])) / h
    if clamp:
        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))
    return nx, ny


def _control_scene_points(item: dict[str, Any], points: list[dict[str, float]]) -> list[tuple[float, float]]:
    coords: list[tuple[float, float]] = []
    for point in points:
        origin = _abs_point(item, point)
        coords.append((origin.x(), origin.y()))
        for prefix in ("in", "out"):
            handle = _handle_point(item, point, prefix)
            coords.append((handle.x(), handle.y()))
    return coords


def _remap_shape_points(
    points: list[dict[str, float]],
    old_x: float,
    old_y: float,
    old_w: float,
    old_h: float,
    new_x: float,
    new_y: float,
    new_w: float,
    new_h: float,
) -> None:
    old_w = max(1.0, float(old_w))
    old_h = max(1.0, float(old_h))
    new_w = max(1.0, float(new_w))
    new_h = max(1.0, float(new_h))
    for point in points:
        abs_x = old_x + float(point["x"]) * old_w
        abs_y = old_y + float(point["y"]) * old_h
        in_x = abs_x + float(point.get("in_x") or 0) * old_w
        in_y = abs_y + float(point.get("in_y") or 0) * old_h
        out_x = abs_x + float(point.get("out_x") or 0) * old_w
        out_y = abs_y + float(point.get("out_y") or 0) * old_h
        point["x"] = (abs_x - new_x) / new_w
        point["y"] = (abs_y - new_y) / new_h
        point["in_x"] = (in_x - abs_x) / new_w
        point["in_y"] = (in_y - abs_y) / new_h
        point["out_x"] = (out_x - abs_x) / new_w
        point["out_y"] = (out_y - abs_y) / new_h


def expand_shape_widget_to_controls(item: dict[str, Any], points: list[dict[str, float]]) -> bool:
    """Grow the widget so vertices and Bézier handles stay inside. Scene positions stay put."""
    if not uses_bezier_edit(item) or not points:
        return False
    old_x = float(item["x"])
    old_y = float(item["y"])
    old_w = max(1.0, float(item["w"]))
    old_h = max(1.0, float(item["h"]))
    min_x, min_y = old_x, old_y
    max_x, max_y = old_x + old_w, old_y + old_h
    for sx, sy in _control_scene_points(item, points):
        if sx < min_x:
            min_x = sx
        if sy < min_y:
            min_y = sy
        if sx > max_x:
            max_x = sx
        if sy > max_y:
            max_y = sy
    new_x = math.floor(min_x)
    new_y = math.floor(min_y)
    new_r = math.ceil(max_x)
    new_b = math.ceil(max_y)
    new_w = max(8, int(new_r - new_x))
    new_h = max(8, int(new_b - new_y))
    new_x = int(new_x)
    new_y = int(new_y)
    if new_x == int(old_x) and new_y == int(old_y) and new_w == int(round(old_w)) and new_h == int(round(old_h)):
        return False
    _remap_shape_points(points, old_x, old_y, old_w, old_h, new_x, new_y, new_w, new_h)
    item["x"] = new_x
    item["y"] = new_y
    item["w"] = new_w
    item["h"] = new_h
    return True


def closest_segment(item: dict[str, Any], pos: QtCore.QPointF) -> tuple[int, float]:
    points = ensure_shape_points(item)
    if len(points) < 2:
        return 0, 1e9
    best_i = 0
    best_d = 1e9
    count = len(points)
    steps = count if shape_closed(item) else count - 1
    for i in range(steps):
        a = _abs_point(item, points[i])
        b = _abs_point(item, points[(i + 1) % count])
        dist = _distance_to_segment(pos, a, b)
        if dist < best_d:
            best_d = dist
            best_i = i
    return best_i, best_d


def _distance_to_segment(pos: QtCore.QPointF, a: QtCore.QPointF, b: QtCore.QPointF) -> float:
    ax, ay = a.x(), a.y()
    bx, by = b.x(), b.y()
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if length <= 1e-6:
        return QtCore.QLineF(pos, a).length()
    t = max(0.0, min(1.0, ((pos.x() - ax) * dx + (pos.y() - ay) * dy) / length))
    proj = QtCore.QPointF(ax + t * dx, ay + t * dy)
    return QtCore.QLineF(pos, proj).length()


def insert_shape_point(item: dict[str, Any], after_index: int, pos: QtCore.QPointF) -> int:
    points = ensure_shape_points(item)
    nx, ny = scene_to_normalized(item, pos)
    index = max(0, min(len(points), after_index + 1))
    points.insert(index, _point(nx, ny))
    kind = normalize_shape_kind((item.get("style") or {}).get("shape_kind"))
    if kind == "freeform":
        _apply_tangent_handles(points, index, shape_closed(item))
    item["points"] = points
    return index


def remove_shape_point(item: dict[str, Any], index: int) -> bool:
    points = ensure_shape_points(item)
    kind = normalize_shape_kind((item.get("style") or {}).get("shape_kind"))
    minimum = 2 if kind == "line" else 3
    if index < 0 or index >= len(points) or len(points) <= minimum:
        return False
    points.pop(index)
    item["points"] = points
    return True
