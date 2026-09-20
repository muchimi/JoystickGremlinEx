# -*- coding: utf-8; -*-

"""AFCS merge operators — same math as Map to VJoy, owned by the AFCS graph."""

from __future__ import annotations

from gremlin.util import clamp, scale_to_range

MERGE_OPS = (
    "add",
    "average",
    "center",
    "min",
    "max",
    "scalefull",
    "scalehalf",
    "multiply",
    "trim",
    "trimcentered",
    "scalefullc",
    "scalehalfc",
)

MERGE_OP_LABELS = {
    "add": "Add",
    "average": "Average",
    "center": "Center",
    "min": "Minimum",
    "max": "Maximum",
    "scalefull": "Scale",
    "scalehalf": "Scale half",
    "multiply": "Multiply",
    "trim": "Trim",
    "trimcentered": "Trim (centered)",
    "scalefullc": "Scale (centered)",
    "scalehalfc": "Scale half (centered)",
}


def normalize_merge_op(value) -> str:
    key = str(value or "add").strip().casefold().replace(" ", "").replace("_", "").replace("-", "")
    aliases = {
        "scale": "scalefull",
        "scalefullcentered": "scalefullc",
        "scalehalfcentered": "scalehalfc",
        "minimum": "min",
        "maximum": "max",
        "trimcentered": "trimcentered",
    }
    key = aliases.get(key, key)
    return key if key in MERGE_OPS else "add"


def merge_values(op: str, v1: float, v2: float) -> float:
    """Two-input merge matching Map to VJoy's axis merge."""
    op = normalize_merge_op(op)
    if op == "add":
        value = scale_to_range(v1 + v2)
    elif op == "average":
        value = scale_to_range((v1 + v2) / 2)
    elif op == "center":
        value = scale_to_range((v1 - v2) / 2)
    elif op == "min":
        value = scale_to_range(min(v1, v2))
    elif op == "max":
        value = scale_to_range(max(v1, v2))
    elif op == "scalefull":
        value = scale_to_range(v1 * v2)
    elif op == "scalehalf":
        if v2 > 0:
            value = scale_to_range(v1 * v2)
        else:
            value = scale_to_range(v1 * -abs(v2))
    elif op == "scalefullc":
        scale = scale_to_range(v2, target_min=0, target_max=1)
        value = scale_to_range(v1 * scale)
    elif op == "scalehalfc":
        value = scale_to_range(v1 * abs(v2))
    elif op == "multiply":
        value = scale_to_range(v1 * v2)
    elif op == "trim":
        # B is a 0..1 trim amount. A centered axis at 0 is no trim, not 50%.
        t = scale_to_range(v2, source_min=0, source_max=1, target_min=0, target_max=1)
        if v1 > 0:
            value = t + ((1 - t) * v1)
        else:
            value = t + ((t + 1) * v1)
    elif op == "trimcentered":
        a = scale_to_range(v2, target_min=0, target_max=1)
        t = a - 0.5
        if v1 > 0:
            value = v2 + ((1 - t) * v1)
        else:
            value = v2 + ((t + 1) * v1)
    else:
        value = v1
    return clamp(float(value))


LIMITER_RANGES = ("unipolar", "bipolar")

LIMITER_RANGE_LABELS = {
    "unipolar": "0 to 100%",
    "bipolar": "Centered (−100 to +100)",
}

LIMITER_SHAPES = ("linear", "bezier", "minmax")

LIMITER_SHAPE_LABELS = {
    "linear": "Linear",
    "bezier": "Bezier",
    "minmax": "Min-max",
}

# Identity cubic-bezier (handles on the diagonal) → GEX Bezier 1 (handles pulled to center).
_BEZIER_LINEAR = (
    (-1.0, -1.0),
    (-2.0 / 3.0, -2.0 / 3.0),
    (-1.0 / 3.0, -1.0 / 3.0),
    (0.0, 0.0),
    (1.0 / 3.0, 1.0 / 3.0),
    (2.0 / 3.0, 2.0 / 3.0),
    (1.0, 1.0),
)
_BEZIER_MAX = (
    (-1.0, -1.0),
    (-1.0, 0.0),
    (-0.1, 0.0),
    (0.0, 0.0),
    (0.1, 0.0),
    (1.0, 0.0),
    (1.0, 1.0),
)
_BEZIER_SPLINES: dict[float, object] = {}

INPUT_DISPLAY_RANGES = ("auto", "unipolar", "centered")

INPUT_DISPLAY_LABELS = {
    "auto": "Auto (match GEX)",
    "unipolar": "0 to 100%",
    "centered": "Centered (−100 to +100)",
}

_UNIPOLAR_NAME_HINTS = ("throttle", "slider", "brake", "accelerator", "pedal", "collective")


def normalize_input_display_range(value) -> str:
    key = str(value or "auto").strip().casefold().replace("_", " ").replace("%", "")
    compact = key.replace(" ", "").replace("to", "")
    if key in ("unipolar",) or compact in ("unipolar", "0100", "0-100"):
        return "unipolar"
    if key in ("centered", "bipolar", "center") or compact in ("centered", "bipolar", "-100100", "-100-100"):
        return "centered"
    return "auto"


def names_look_unipolar(*parts) -> bool:
    blob = " ".join(str(part or "") for part in parts).casefold()
    return any(hint in blob for hint in _UNIPOLAR_NAME_HINTS)


def meter_is_centered(kind: str, props: dict | None = None, names=()) -> bool:
    """True when an input stays −1..+1 (stick). False remaps to 0..1 (throttle)."""
    props = props or {}
    key = str(kind or "").casefold()
    if key == "limiter":
        return normalize_limiter_range(props.get("range_mode") if props.get("range_mode") is not None else props.get("centered")) == "bipolar"
    if key == "input":
        mode = normalize_input_display_range(props.get("display_range"))
        if mode == "unipolar":
            return False
        if mode == "centered":
            return True
        return not names_look_unipolar(*names)
    return True


def apply_input_display_range(value: float, props: dict | None = None, names=()) -> float:
    """Invert the GEX −1..+1 axis, then remap to 0..1 when Display is unipolar."""
    current = clamp(float(value))
    props = props or {}
    if props.get("invert"):
        current = -current
    if meter_is_centered("input", props, names):
        return clamp(current)
    mapped = scale_to_range(current, -1.0, 1.0, 0.0, 1.0)
    return clamp(0.0 if mapped is None else float(mapped), 0.0, 1.0)


def normalize_limiter_shape(value) -> str:
    key = str(value or "linear").strip().casefold().replace("é", "e").replace("_", "").replace("-", "")
    if key in ("bezier", "bez", "curve"):
        return "bezier"
    if key in ("minmax", "min", "max", "clip", "clamp"):
        return "minmax"
    return "linear"


def bezier_limiter_amount(gain: float) -> float:
    """0 = linear identity, 1 = handles fully pulled (flat center, steep ends)."""
    return clamp(1.0 - abs(float(gain)), 0.0, 1.0)


def bezier_limiter_points(amount: float) -> list[tuple[float, float]]:
    t = clamp(float(amount), 0.0, 1.0)
    return [
        (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        for a, b in zip(_BEZIER_LINEAR, _BEZIER_MAX)
    ]


def bezier_limiter_spline(amount: float):
    key = round(clamp(float(amount), 0.0, 1.0), 3)
    spline = _BEZIER_SPLINES.get(key)
    if spline is None:
        import gremlin.spline

        spline = gremlin.spline.CubicBezierSpline(bezier_limiter_points(key))
        if len(_BEZIER_SPLINES) >= 48:
            _BEZIER_SPLINES.pop(next(iter(_BEZIER_SPLINES)))
        _BEZIER_SPLINES[key] = spline
    return spline


def sample_limiter_curve(curve, gain: float, shape: str = "linear") -> list[tuple[float, float]]:
    """Preview points in −1..+1. Linear leaves amplitude to the widget gain; Bezier and min-max bake the shape."""
    xs = [i / 16.0 - 1.0 for i in range(33)]

    def mapped(x: float) -> float:
        if curve is None:
            return float(x)
        try:
            return float(curve.curve_value(x))
        except Exception:
            return float(x)

    mode = normalize_limiter_shape(shape)
    if mode == "bezier":
        spline = bezier_limiter_spline(bezier_limiter_amount(gain))
        sign = -1.0 if float(gain) < 0 else 1.0
        return [(x, clamp(sign * float(spline(mapped(x))))) for x in xs]
    if mode == "minmax":
        ceiling = abs(float(gain))
        sign = -1.0 if float(gain) < 0 else 1.0
        if 0.0 < ceiling < 1.0:
            xs = sorted(set(xs + [-ceiling, ceiling]))
        return [(x, clamp(sign * clamp(mapped(x), -ceiling, ceiling))) for x in xs]
    return [(x, mapped(x)) for x in xs]


def normalize_limiter_range(value) -> str:
    """Limiter control range: 0–100% (unipolar) or −100..100% (signed, inverts)."""
    if value is True or value is False or value is None:
        return "unipolar"
    key = str(value).strip().casefold().replace("_", " ").replace("%", "")
    compact = key.replace(" ", "").replace("to", "")
    if key in ("bipolar", "signed") or compact in ("bipolar", "signed", "-100100", "-100-100", "n100100"):
        return "bipolar"
    return "unipolar"


def limiter_gain(limit: float, range_mode: str = "unipolar") -> float:
    """Map the limiter control to a scale factor.

    0 to 100%: GEX axes are −1..1 across that travel, so 0%→0, 50%→0.5, 100%→1.
    −100 to 100%: signed −1..1; negative inverts the limited output.
    """
    mode = normalize_limiter_range(range_mode)
    if mode == "bipolar":
        return clamp(float(limit), -1.0, 1.0)
    amount = scale_to_range(limit, target_min=0, target_max=1)
    return clamp(float(amount), 0.0, 1.0)


def apply_limiter(signal: float, limit: float, range_mode: str = "unipolar", shape: str = "linear") -> float:
    gain = limiter_gain(limit, range_mode)
    src = float(signal)
    mode = normalize_limiter_shape(shape)
    if mode == "bezier":
        value = float(bezier_limiter_spline(bezier_limiter_amount(gain))(src))
        if gain < 0:
            value = -value
        return clamp(value)
    if mode == "minmax":
        ceiling = abs(gain)
        value = clamp(src, -ceiling, ceiling)
        if gain < 0:
            value = -value
        return clamp(value)
    return clamp(src * gain)


def apply_deadzone(value: float, center: float = 0.05, outer: float = 0.0) -> float:
    """GEX-style four-point deadzone from inner and outer fractions (0..1)."""
    current = float(value)
    inner = clamp(abs(float(center)), 0.0, 0.95)
    end = clamp(abs(float(outer)), 0.0, 0.95)
    if inner + end >= 0.999:
        end = max(0.0, 0.999 - inner)
    low = -1.0 + end
    high = 1.0 - end
    low_center = -inner
    high_center = inner
    if high <= high_center:
        high = min(1.0, high_center + 1e-4)
    if low >= low_center:
        low = max(-1.0, low_center - 1e-4)
    if current >= 0:
        span = abs(high - high_center) or 1e-4
        return clamp(min(1.0, max(0.0, (current - high_center) / span)))
    span = abs(low - low_center) or 1e-4
    return clamp(max(-1.0, min(0.0, (current - low_center) / span)))


class OverrideState:
    """Stick takes over when deflected; hysteresis, optional dwell, optional wait for in to move."""

    _IN_MOVE = 0.02

    def __init__(self):
        self.engaged = False
        self._release_s = 0.0
        self._in_ref = None

    def process(
        self,
        default: float,
        stick: float,
        threshold: float,
        release: float,
        dt: float = 0.05,
        release_ms: float = 0.0,
        hold_until_in: bool = False,
    ) -> float:
        mag = abs(float(stick))
        current_in = float(default)
        take = clamp(abs(float(threshold)), 0.0, 1.0)
        drop = clamp(abs(float(release)), 0.0, take)
        hold = max(0.0, float(release_ms) / 1000.0)
        step = max(0.0, float(dt))
        if self.engaged:
            if mag <= drop:
                self._release_s += step
                if self._release_s + 1e-9 >= hold:
                    if not hold_until_in:
                        self.engaged = False
                        self._release_s = 0.0
                        self._in_ref = None
                    else:
                        if self._in_ref is None:
                            self._in_ref = current_in
                        elif abs(current_in - self._in_ref) >= self._IN_MOVE:
                            self.engaged = False
                            self._release_s = 0.0
                            self._in_ref = None
            else:
                self._release_s = 0.0
                self._in_ref = None
        else:
            self._release_s = 0.0
            self._in_ref = None
            if mag >= take:
                self.engaged = True
        return clamp(float(stick if self.engaged else default))


class LagLeadState:
    """First-order lag-lead: H(s) = (T_lead s + 1) / (T_lag s + 1)."""

    def __init__(self):
        self.lp = 0.0
        self.ready = False

    def process(self, value: float, dt: float, lag_s: float, lead_s: float) -> float:
        current = float(value)
        step = max(1e-4, float(dt))
        tau_lag = max(0.0, float(lag_s))
        tau_lead = max(0.0, float(lead_s))
        if not self.ready:
            self.lp = current
            self.ready = True
            return clamp(current)
        if tau_lag <= 1e-6:
            self.lp = current
            return clamp(current)
        alpha = step / (tau_lag + step)
        self.lp = self.lp + alpha * (current - self.lp)
        return clamp(self.lp + (tau_lead / tau_lag) * (current - self.lp))


NODE_HELP = {
    "input": "Named AFCS axis from Map to AFCS, or a listened physical axis. Invert flips the GEX −1..+1 sign first. Display then sets the node output: 0 to 100% remaps to 0..1 (idle at 0), Centered keeps −1..+1, Auto follows throttle/slider names like GEX.",
    "merge": "Combines two axes with the same math as Map to VJoy.",
    "curve": "Remaps the axis with the GEX response-curve editor. Double-click the node to edit.",
    "limiter": "Shapes throw from a limiter axis. Linear scales the slope with the live limiter. Bezier keeps full corners and pulls the handles toward a flat center as the limiter drops. Min-max follows 1:1 through the center, then clips at whatever the limiter axis is reading — 100% is full travel, 0% is locked at center, and every value in between is a live ceiling. Wire the signal to in and the controller to limit. 0 to 100% uses a slider or throttle; −100 to 100% inverts when the limiter is negative.",
    "deadzone": "Removes noise around center and optionally at the ends, then rescales the remaining travel to full range.",
    "override": "Passes in until the override axis moves past the take-over threshold (pilot stick). Hands back after the stick stays inside the release band for the hold time. Hold until in moves keeps the override after that until the in axis actually moves, so a pass through center does not drop it.",
    "laglead": "Lag smooths low-frequency jitter. Lead restores or boosts faster motion. Equal lag and lead is a pass-through; lead above lag anticipates.",
    "output": "Writes the finished axis to a vJoy virtual axis. Only one flight mode is active, so modes may share the same vJoy target. Optional conditions can skip the write.",
}

MERGE_HELP = {
    "add": "A + B, then clamped to ±1.",
    "average": "Mean of A and B.",
    "center": "Centered difference (A − B) / 2.",
    "min": "More negative of A and B.",
    "max": "More positive of A and B.",
    "scalefull": "A × B using the full ±1 range of B.",
    "scalehalf": "A scaled by B, with negative B reversing direction.",
    "multiply": "A × B.",
    "trim": "B is a 0..1 trim offset. 0 is no trim.",
    "trimcentered": "Centered-stick trim (B at 0 is 50% trim).",
    "scalefullc": "A scaled by B mapped from ±1 into 0..1.",
    "scalehalfc": "A scaled by |B|.",
}


def inspector_help(kind: str, operation: str | None = None) -> str:
    key = str(kind or "").casefold()
    text = NODE_HELP.get(key, "")
    if key == "merge":
        extra = MERGE_HELP.get(normalize_merge_op(operation), "")
        if extra:
            text = f"{text} {extra}".strip()
    return text
