# -*- coding: utf-8; -*-
#
# Runtime tracker for overlay OCR widgets: arm gate, scan, match rules, emit as buttons.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

import logging
from collections import deque
import re
import threading
import time
from typing import Any

from gremlin.singleton_decorator import SingletonDecorator

from .model import (
    detection_label_for_rule,
    normalize_ocr_arm_mode,
    normalize_ocr_arm_pulse_spacing_ms,
    normalize_ocr_arm_pulses,
    normalize_ocr_base,
    normalize_ocr_confidence,
    normalize_ocr_engine,
    normalize_ocr_match,
    normalize_ocr_miss_tolerance,
    normalize_ocr_rules,
    ocr_rule_input_id,
    split_ocr_texts,
)

syslog = logging.getLogger("system")

# Prefer thousands-grouped forms (3,170 / 3.170), then bare 4–5 digit runs.
_SIG_GROUPED = re.compile(r"(?<!\d)(\d{1,2})[.,](\d{3})(?!\d)")
_SIG_BARE = re.compile(r"(?<!\d)(\d{4,5})(?!\d)")


def _load_builtin_pack_runtime(pack_id: str) -> dict[str, Any]:
    """Rebuild pack runtime from a built-in JSON (survives profile save stripping `_runtime`)."""
    try:
        from .ocr_packs import list_builtin_packs, normalize_pack

        for pack in list_builtin_packs():
            if str(pack.get("id") or "").casefold() != str(pack_id or "").casefold():
                continue
            pack = normalize_pack(pack) or pack
            kind = str(pack.get("kind") or "").casefold()
            if kind == "citizen_lookup":
                return {
                    "kind": "citizen_lookup",
                    "field_map": dict(pack.get("field_map") or {}),
                }
            if kind == "image_map":
                return {
                    "kind": "efb_lookup",
                    "image_widget": str(pack.get("target_image_widget") or "SC EFB Chart"),
                    "locations": list(pack.get("locations") or []),
                }
    except Exception as err:
        syslog.debug(f"OBS OVERLAY OCR: builtin pack runtime load failed: {err}")
    return {}


def _resolve_rule_runtime(rule: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge rule `_runtime`, emit extras, and pack-id fallbacks."""
    extra = extra if isinstance(extra, dict) else {}
    runtime = dict(rule.get("_runtime") if isinstance(rule.get("_runtime"), dict) else {})
    kind = str(runtime.get("kind") or extra.get("ocr_runtime_kind") or "").casefold()
    pack_id = str(
        runtime.get("pack_id")
        or extra.get("ocr_pack_id")
        or rule.get("pack_id")
        or ""
    ).strip()
    if not kind:
        # Infer from pack id / rule shape after pack load / UI edits.
        capture = str(rule.get("capture") or "").casefold()
        match = str(rule.get("match") or "").casefold()
        name = str(rule.get("name") or rule.get("display_name") or "").casefold()
        pid = pack_id.casefold().replace("_", "-")
        if pid in ("sc-intelligence", "scintelligence"):
            kind = "citizen_lookup"
            pack_id = "sc-intelligence"
        elif pid in ("sc-efb", "scefb"):
            kind = "efb_lookup"
            pack_id = "sc-efb"
        elif match == "any" or capture in ("region", "handle", "any", "text"):
            if "citizen" in name or "intell" in name:
                kind = "citizen_lookup"
                pack_id = pack_id or "sc-intelligence"
            elif "efb" in name:
                kind = "efb_lookup"
                pack_id = pack_id or "sc-efb"
    if kind in ("efb_lookup", "image_map") and not (runtime.get("locations") or extra.get("ocr_efb_locations")):
        pack_id = pack_id or "sc-efb"
        loaded = _load_builtin_pack_runtime(pack_id)
        runtime.update({k: v for k, v in loaded.items() if v})
        kind = str(runtime.get("kind") or kind)
    if kind == "citizen_lookup" and not (runtime.get("field_map") or extra.get("ocr_field_map")):
        pack_id = pack_id or "sc-intelligence"
        loaded = _load_builtin_pack_runtime(pack_id)
        runtime.update({k: v for k, v in loaded.items() if v})
        kind = str(runtime.get("kind") or kind)
    if kind:
        runtime["kind"] = kind
    if pack_id:
        runtime["pack_id"] = pack_id
    if extra.get("ocr_image_widget") and not runtime.get("image_widget"):
        runtime["image_widget"] = extra.get("ocr_image_widget")
    if extra.get("ocr_efb_locations") and not runtime.get("locations"):
        runtime["locations"] = extra.get("ocr_efb_locations")
    if extra.get("ocr_field_map") and not runtime.get("field_map"):
        runtime["field_map"] = extra.get("ocr_field_map")
    return runtime


def _dispatch_ocr_runtime(rule: dict[str, Any], is_pressed: bool, label: str, extra: dict[str, Any]):
    """Citizen lookup / chart image hooks driven by pack `_runtime` metadata."""
    runtime = _resolve_rule_runtime(rule, extra)
    kind = str(runtime.get("kind") or "").casefold()
    syslog.info(
        "OBS OVERLAY OCR: runtime %s kind=%s label=%r locs=%s",
        "PRESS" if is_pressed else "RELEASE",
        kind or "(none)",
        (label or "")[:80],
        len(runtime.get("locations") or []),
    )
    if kind == "citizen_lookup":
        from .ocr_lookup import citizen_lookup

        if is_pressed:
            citizen_lookup().lookup(label, runtime.get("field_map") or extra.get("ocr_field_map"))
        else:
            citizen_lookup().clear()
        return
    if kind in ("efb_lookup", "image_map"):
        from .ocr_efb import apply_efb_ocr

        widget_name = str(
            runtime.get("image_widget")
            or extra.get("ocr_image_widget")
            or rule.get("image_widget")
            or "SC EFB Chart"
        )
        locations = runtime.get("locations") or extra.get("ocr_efb_locations") or []
        apply_efb_ocr(
            label,
            is_pressed=is_pressed,
            locations=list(locations) if isinstance(locations, list) else [],
            image_widget=widget_name,
        )
        return
    if kind == "set_image":
        from .ocr_images import fetch_chart_to_cache, set_named_image_path_runtime

        widget_name = str(
            runtime.get("image_widget")
            or extra.get("ocr_image_widget")
            or rule.get("image_widget")
            or "SC EFB Chart"
        )
        if not is_pressed:
            set_named_image_path_runtime(widget_name, "")
            return

        def _fetch_and_set():
            path = fetch_chart_to_cache(
                chart_url=str(runtime.get("chart_url") or extra.get("ocr_chart_url") or rule.get("chart_url") or ""),
                page_url=str(runtime.get("page_url") or extra.get("ocr_page_url") or rule.get("page_url") or ""),
                chart_id=str(runtime.get("chart_id") or extra.get("ocr_chart_id") or rule.get("chart_id") or ""),
                hint=str(label or rule.get("name") or ""),
            )
            if path:
                import gremlin.util

                gremlin.util.InvokeUiMethod(set_named_image_path_runtime, widget_name, path)

        threading.Thread(target=_fetch_and_set, name="GexOcrChartFetch", daemon=True).start()


def rule_matches(text: str, needle: str, mode: str) -> bool:
    hay = str(text or "")
    pin = str(needle or "").strip()
    if not pin:
        return False
    mode = normalize_ocr_match(mode)
    if mode == "exact":
        return hay.strip().casefold() == pin.casefold()
    return pin.casefold() in hay.casefold()


def parse_signatures(text: str) -> list[int]:
    """Extract mining-style signature integers from OCR text (comma-tolerant)."""
    raw = str(text or "")
    if not any(ch.isdigit() for ch in raw):
        return []
    # Light OCR digit repair for common confusions in otherwise numeric tokens.
    cleaned = raw
    for src, dst in (("o", "0"), ("O", "0"), ("l", "1"), ("I", "1"), ("|", "1")):
        cleaned = cleaned.replace(src, dst)
    found: list[int] = []
    seen: set[int] = set()

    def _accept(value: int):
        if 1000 <= value <= 30000 and value not in seen:
            seen.add(value)
            found.append(value)

    for m in _SIG_GROUPED.finditer(cleaned):
        try:
            _accept(int(m.group(1) + m.group(2)))
        except ValueError:
            pass
    for m in _SIG_BARE.finditer(cleaned):
        try:
            _accept(int(m.group(1)))
        except ValueError:
            pass
    return found


def rule_match_result(text: str, rule: dict[str, Any]) -> tuple[bool, int | None, str]:
    """Return (matched, signature_or_none, detection_label)."""
    needles = split_ocr_texts(rule.get("texts") if "texts" in rule else rule.get("text"))
    mode = rule.get("match")
    capture = str(rule.get("capture") or "").strip().casefold()
    # Region / any: fire on non-empty OCR. Keep full text for EFB catalog contain-match;
    # citizen lookup cleans the handle itself later (do NOT strip spaces here).
    if capture in ("region", "handle", "text", "any") or str(mode or "").casefold() == "any":
        from .ocr_lookup import clean_citizen_handle

        hay = str(text or "").strip()
        if not hay:
            return False, None, ""
        if capture == "handle":
            label = clean_citizen_handle(hay) or hay.splitlines()[0].strip()
        else:
            # Full OCR blob — EFB matches locations inside a multi-line list.
            label = hay
        if not label:
            return False, None, ""
        return True, None, label

    base = normalize_ocr_base(rule.get("base"))
    signatures = parse_signatures(text) if base else []

    if base and signatures:
        for sig in signatures:
            if sig % base != 0:
                continue
            count = sig // base
            if count < 1:
                continue
            # Prefer exact signature listed in texts when provided.
            if needles:
                needle_nums = set()
                for n in needles:
                    try:
                        needle_nums.add(int(re.sub(r"[^\d]", "", n) or "0"))
                    except ValueError:
                        pass
                if needle_nums and sig not in needle_nums:
                    continue
            return True, sig, detection_label_for_rule(rule, sig)

    hay = str(text or "")
    for needle in needles:
        if rule_matches(hay, needle, mode):
            # If needle is numeric, try to use it as signature for count.
            sig = None
            try:
                digits = re.sub(r"[^\d]", "", needle)
                if digits:
                    sig = int(digits)
            except ValueError:
                sig = None
            return True, sig, detection_label_for_rule(rule, sig)
        # Also try matching against parsed signatures as strings.
        if base:
            continue
        for sig in parse_signatures(hay):
            if rule_matches(str(sig), needle, mode) or rule_matches(f"{sig:,}", needle, mode):
                return True, sig, detection_label_for_rule(rule, sig)
    return False, None, detection_label_for_rule(rule, None)


class _OcrSession:
    """Identity and cancellation live longer than any individual scan result."""

    def __init__(self, widget_id: str, serial: int, kind: str):
        self.widget_id = widget_id
        self.serial = serial
        self.kind = kind
        self.cancelled = threading.Event()
        self.countdown = None


@SingletonDecorator
class OcrOverlayTracker:
    """Per-widget OCR scan state shared by the value bus and paint path."""

    def __init__(self):
        self._lock = threading.RLock()
        self._slots: dict[str, dict[str, Any]] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._serial = 0
        self._test_jobs = deque()
        # GUI-thread ownership of delivered presses, separate from match state.
        self._delivered = {}

    def _session_current(self, session) -> bool:
        if session is None or session.cancelled.is_set():
            return False
        with self._lock:
            slot = self._slots.get(session.widget_id)
            return slot is not None and slot.get("session") is session

    def _cancel_session(self, session):
        if session is None or session.cancelled.is_set():
            return
        session.cancelled.set()
        countdown, session.countdown = session.countdown, None
        if countdown is not None:
            countdown.cancel()
        import gremlin.util

        # Defer releases so cancellation inside a mapped press can unwind first.
        gremlin.util.singleShot(lambda: self._release_session(session))

    def _new_session(self, widget_id, slot, kind="runtime"):
        self._cancel_session(slot.get("session"))
        self._test_jobs = deque(job for job in self._test_jobs if not job[2].cancelled.is_set())
        self._serial += 1
        session = _OcrSession(widget_id, self._serial, kind)
        slot["session"] = session
        slot["rule_state"] = {}
        slot["matched"] = []
        slot["last_scan"] = 0.0
        return session

    def cancel(self, widget_id: str | None = None):
        """Stop a widget (or all widgets) without waiting for native OCR."""
        with self._lock:
            for ident, slot in self._slots.items():
                if widget_id is not None and ident != str(widget_id):
                    continue
                self._cancel_session(slot.get("session"))
                slot["armed"] = False
                slot["manual_stop"] = True
                slot["pulse_remaining"] = 0
                slot["rule_state"] = {}
                slot["matched"] = []
                slot["status"] = "Cancelled"
            self._test_jobs = deque(job for job in self._test_jobs if not job[2].cancelled.is_set())
        self._wake.set()

    def _release_delivery(self, key, session):
        delivery = self._delivered.get(key)
        if delivery is None or delivery[0] is not session:
            return
        self._delivered.pop(key, None)
        try:
            delivery[1]()
        except Exception as err:
            syslog.warning("OBS OVERLAY OCR: cleanup release failed: %s", err)

    def _release_session(self, session):
        """GUI-only cleanup; an old session cannot release a new session's press."""
        for key, delivery in list(self._delivered.items()):
            if delivery[0] is session:
                self._release_delivery(key, session)

    def retain(self, widget_ids: set[str] | None):
        with self._lock:
            if not widget_ids:
                for slot in self._slots.values():
                    self._cancel_session(slot.get("session"))
                self._slots.clear()
                return
            for ident in list(self._slots):
                if ident not in widget_ids:
                    slot = self._slots.pop(ident, None)
                    if slot:
                        self._cancel_session(slot.get("session"))

    def stop_runtime(self):
        """Cancel all sessions and request worker exit; never join the GUI thread."""
        self.cancel()
        with self._lock:
            self._stop.set()
            self._wake.set()

    def _ensure_thread(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._wake.set()
                return
            # Each worker owns its stop flag. A replacement never revives it.
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(self._stop,), name="GexOverlayOCR", daemon=True)
            self._thread.start()

    @staticmethod
    def _profile_running() -> bool:
        try:
            import gremlin.shared_state

            return bool(gremlin.shared_state.is_running)
        except Exception:
            return False

    def sample(self, item: dict[str, Any] | None):
        """Update arm state and return a fingerprint for the value bus."""
        if not item:
            return False
        widget_id = str(item.get("id") or "")
        if not widget_id:
            return False
        from .bindings import binding_is_configured, read_toggle_active

        style = item.get("style") or {}
        arm_mode = normalize_ocr_arm_mode(style.get("ocr_arm_mode"))
        running = self._profile_running()
        with self._lock:
            slot = self._slots.setdefault(
                widget_id,
                {
                    "armed": False,
                    "arm_prev": False,
                    "pulse_remaining": 0,
                    "generation": 0,
                    "last_text": "",
                    "hits": [],
                    "engine": "none",
                    "status": "Idle",
                    "matched": [],
                    "rule_state": {},
                    "last_scan": 0.0,
                    "interval_ms": 400,
                    "confidence": 0.70,
                    "miss_tolerance": 3,
                    "engine_pref": "auto",
                    "region": "widget",
                    "arm_mode": "toggle",
                    "arm_pulses": 5,
                    "arm_pulse_spacing_ms": 500,
                    "item": item,
                },
            )
            slot["item"] = item
            slot["arm_mode"] = arm_mode
            slot["arm_pulses"] = normalize_ocr_arm_pulses(style.get("ocr_arm_pulses"))
            slot["arm_pulse_spacing_ms"] = normalize_ocr_arm_pulse_spacing_ms(
                style.get("ocr_arm_pulse_spacing_ms")
            )
            slot["confidence"] = normalize_ocr_confidence(style.get("ocr_confidence"))
            slot["miss_tolerance"] = normalize_ocr_miss_tolerance(style.get("ocr_miss_tolerance"))
            slot["engine_pref"] = normalize_ocr_engine(style.get("ocr_engine"))
            slot["region"] = str(style.get("ocr_region") or "widget")
            # Pulse runs use their own spacing; continuous modes use Scan interval.
            if arm_mode == "multi_pulse" and slot.get("armed") and int(slot.get("pulse_remaining") or 0) > 0:
                slot["interval_ms"] = int(slot.get("arm_pulse_spacing_ms") or 500)
            elif arm_mode == "pulse" and slot.get("armed"):
                slot["interval_ms"] = 50
            else:
                try:
                    slot["interval_ms"] = max(100, min(5000, int(style.get("ocr_interval_ms") or 400)))
                except (TypeError, ValueError):
                    slot["interval_ms"] = 400
            # Designer Show overlay / deactivated profile: never arm or scan.
            if not running:
                if slot.get("armed"):
                    self._cancel_session(slot.get("session"))
                slot["armed"] = False
                slot["arm_prev"] = False
                slot["pulse_remaining"] = 0
                session = slot.get("session")
                if slot.get("status") != "Cancelled" and not (session and session.kind == "test" and not session.cancelled.is_set()):
                    slot["status"] = "Idle"
            else:
                binding = item.get("binding")
                configured = binding_is_configured(binding)
                active = bool(configured and read_toggle_active(binding))
                prev_armed = bool(slot.get("armed"))
                if slot.get("manual_stop"):
                    # A held arm input must be released before a fresh gesture.
                    slot["manual_stop"] = active
                    slot["arm_prev"] = active
                    slot["armed"] = False
                elif arm_mode == "hold":
                    slot["armed"] = active
                    slot["pulse_remaining"] = 0
                elif arm_mode in ("pulse", "multi_pulse"):
                    if active and not slot["arm_prev"]:
                        count = 1 if arm_mode == "pulse" else int(slot.get("arm_pulses") or 1)
                        slot["pulse_remaining"] = max(1, count)
                        slot["armed"] = True
                        slot["last_scan"] = 0.0
                        if arm_mode == "multi_pulse":
                            slot["interval_ms"] = int(slot.get("arm_pulse_spacing_ms") or 500)
                        else:
                            slot["interval_ms"] = 50
                        syslog.info(
                            "OBS OVERLAY OCR: pulse start widget=%s count=%s spacing_ms=%s",
                            widget_id,
                            slot["pulse_remaining"],
                            slot.get("interval_ms"),
                        )
                    slot["arm_prev"] = active
                else:
                    # Continuous (Toggle)
                    if active and not slot["arm_prev"]:
                        slot["armed"] = not bool(slot["armed"])
                    slot["arm_prev"] = active
                    slot["pulse_remaining"] = 0
                if bool(slot.get("armed")) != prev_armed:
                    if slot["armed"]:
                        self._new_session(widget_id, slot)
                        slot["status"] = "Armed"
                    else:
                        self._cancel_session(slot.get("session"))
                    syslog.info(
                        "OBS OVERLAY OCR: arm %s widget=%s mode=%s binding_ok=%s input_active=%s",
                        "ON" if slot.get("armed") else "OFF",
                        widget_id,
                        arm_mode,
                        configured,
                        active,
                    )
                if not slot["armed"]:
                    slot["pulse_remaining"] = 0
                    session = slot.get("session")
                    if slot.get("status") != "Cancelled" and not (session and session.kind == "test" and not session.cancelled.is_set()):
                        slot["status"] = "Idle"
            # Live paint only needs armed (border on/off style). Matched/status
            # belong in the designer marker — including them here repainted the
            # whole layered overlay on every detection.
            armed = bool(slot.get("armed"))
            fingerprint = armed
        if armed and running:
            self._ensure_thread()
        return fingerprint

    def status(self, item: dict[str, Any] | None) -> str:
        if not item:
            return ""
        with self._lock:
            slot = self._slots.get(str(item.get("id") or ""))
            if not slot:
                return "Idle"
            return str(slot.get("status") or "")

    def last_text(self, item: dict[str, Any] | None) -> str:
        if not item:
            return ""
        with self._lock:
            slot = self._slots.get(str(item.get("id") or ""))
            return str((slot or {}).get("last_text") or "")

    def armed(self, item: dict[str, Any] | None) -> bool:
        if not item:
            return False
        with self._lock:
            slot = self._slots.get(str(item.get("id") or ""))
            return bool((slot or {}).get("armed"))

    def matched_names(self, item: dict[str, Any] | None) -> list[str]:
        if not item:
            return []
        with self._lock:
            slot = self._slots.get(str(item.get("id") or ""))
            return list((slot or {}).get("matched") or [])

    def _consume_pulse(self, widget_id: str, slot: dict[str, Any]) -> None:
        """After a scan attempt in pulse modes: decrement and disarm when finished."""
        arm_mode = str(slot.get("arm_mode") or "")
        if arm_mode not in ("pulse", "multi_pulse"):
            return
        remaining = int(slot.get("pulse_remaining") or 0) - 1
        slot["pulse_remaining"] = max(0, remaining)
        if remaining > 0:
            syslog.info(
                "OBS OVERLAY OCR: pulse remaining widget=%s left=%s",
                widget_id,
                remaining,
            )
            return
        slot["armed"] = False
        slot["pulse_remaining"] = 0
        self._release_all_rules(slot)
        slot["status"] = "Idle"
        syslog.info("OBS OVERLAY OCR: pulse done widget=%s", widget_id)

    def clear_results(self, item: dict[str, Any] | None) -> None:
        """Clear last OCR text / hits / status for a widget (inspector Clear button)."""
        if not item:
            return
        widget_id = str(item.get("id") or "")
        with self._lock:
            slot = self._slots.get(widget_id)
            if not slot:
                return
            if slot.get("armed"):
                self._new_session(widget_id, slot)
            else:
                self._cancel_session(slot.get("session"))
            slot["last_text"] = ""
            slot["hits"] = []
            slot["engine"] = ""
            slot["matched"] = []
            slot["status"] = "Idle"
            slot["generation"] = int(slot.get("generation") or 0) + 1

    def test_once(self, item: dict[str, Any] | None, on_done=None) -> str:
        """One-shot OCR for the inspector Test button (UI thread)."""
        if not item:
            if on_done is not None:
                on_done("No widget")
            return "No widget"
        from .ocr_capture import run_test_capture_countdown

        widget_id = str(item.get("id") or "")
        with self._lock:
            slot = self._slots.setdefault(widget_id, {"generation": 0, "armed": False, "arm_prev": False, "pulse_remaining": 0})
            session = self._new_session(widget_id, slot, "test")
            slot["item"] = item
            slot["armed"] = False
            slot["manual_stop"] = True
            slot["status"] = "Test countdown…"
            slot["last_text"] = ""

        def _after_capture(image):
            session.countdown = None
            with self._lock:
                if not self._session_current(session):
                    return
                slot["status"] = "Recognizing…"
                self._test_jobs.append((widget_id, item, session, image, on_done))
            self._ensure_thread()

        handle = run_test_capture_countdown(item, seconds=5, on_done=_after_capture, cancelled=session.cancelled.is_set)
        if handle is None:
            with self._lock:
                if self._session_current(session):
                    slot["status"] = "Region unresolved"
            if on_done is not None:
                on_done("Region unresolved")
            return "Region unresolved"
        if not self._session_current(session):
            handle.cancel()
            return "Cancelled"
        session.countdown = handle
        return "Test countdown…"

    def _emit_rule(self, widget_id: str, rule: dict[str, Any], is_pressed: bool, label: str, signature: int | None):
        """Emit press/release on the UI thread (scanner may run in a worker)."""
        import gremlin.util

        with self._lock:
            session = (self._slots.get(widget_id) or {}).get("session")
        key = (widget_id, str(rule.get("id") or ""))

        def _do_emit():
            if not self._session_current(session):
                return
            if not is_pressed:
                self._release_delivery(key, session)
                return
            from .overlay_input import (
                emit_overlay_button_event,
                ensure_overlay_input,
                find_overlay_input,
                overlay_input_has_mappings,
            )

            rule_id = str(rule.get("id") or "")
            input_id = ocr_rule_input_id(widget_id, rule_id)
            title = str(rule.get("name") or rule.get("display_name") or "OCR rule")
            item = find_overlay_input(input_id) or ensure_overlay_input(input_id, f"OCR · {title}")
            if item is None:
                syslog.warning(
                    "OBS OVERLAY OCR: emit SKIP — no overlay input input_id=%s rule=%s",
                    input_id,
                    title,
                )
                return
            has_map = overlay_input_has_mappings(item)
            has_xml = bool(str(rule.get("mapping_xml") or "").strip())
            runtime = _resolve_rule_runtime(rule, {})
            # Keep resolved runtime on the rule for this emit (catalog reload, etc.).
            if runtime:
                rule["_runtime"] = runtime
            extra = {
                "input_item": item,
                "ocr_detection_label": label,
                "ocr_signature": signature,
                "ocr_rule_id": rule_id,
                "ocr_widget_id": widget_id,
                "ocr_chart_url": str(rule.get("chart_url") or runtime.get("chart_url") or ""),
                "ocr_page_url": str(rule.get("page_url") or runtime.get("page_url") or ""),
                "ocr_chart_id": str(rule.get("chart_id") or runtime.get("chart_id") or ""),
                "ocr_image_widget": str(
                    rule.get("image_widget") or runtime.get("image_widget") or ""
                ),
                "ocr_field_map": dict(runtime.get("field_map") or {}),
                "ocr_efb_locations": list(runtime.get("locations") or []),
                "ocr_pack_id": str(runtime.get("pack_id") or ""),
                "ocr_runtime_kind": str(runtime.get("kind") or ""),
            }
            has_runtime = bool(extra.get("ocr_runtime_kind") or runtime.get("kind"))
            if not has_map and not has_xml and not has_runtime:
                syslog.warning(
                    "OBS OVERLAY OCR: emit SKIP — rule has no Map… actions "
                    "input_id=%s rule=%s press=%s label=%r (open Map on the rule)",
                    input_id,
                    title,
                    is_pressed,
                    label,
                )
                return
            # Avoid double-apply: Map to Overlay citizen_lookup/set_image no-op
            # when runtime already handled the pack kind.
            if has_runtime:
                extra["ocr_runtime_handled"] = True
            syslog.info(
                "OBS OVERLAY OCR: emit %s input_id=%s rule=%s label=%r sig=%s has_map=%s",
                "PRESS" if is_pressed else "RELEASE",
                input_id,
                title,
                label,
                signature,
                has_map or has_xml,
            )
            def _dispatch(pressed):
                if pressed and not self._session_current(session):
                    return
                if has_runtime:
                    try:
                        _dispatch_ocr_runtime(rule, pressed, label, extra)
                    except Exception as err:
                        syslog.warning(f"OBS OVERLAY OCR: runtime hook failed: {err}")
                if pressed and not self._session_current(session):
                    return
                if has_map or has_xml:
                    emit_overlay_button_event(item, pressed, extra_data=extra)

            previous = self._delivered.get(key)
            if previous is not None and previous[0] is not session:
                self._release_delivery(key, previous[0])
            if not self._session_current(session):
                return
            # Capture the actual input and payload for cleanup, even after a
            # profile replacement has introduced another input with this ID.
            self._delivered[key] = (session, lambda: _dispatch(False))
            _dispatch(True)

        try:
            gremlin.util.InvokeUiMethod(_do_emit)
        except Exception as err:
            syslog.warning(f"OBS OVERLAY OCR: emit failed: {err}")

    def _release_all_rules(self, slot: dict[str, Any]):
        item = slot.get("item") or {}
        widget_id = str(item.get("id") or "")
        rule_state = slot.get("rule_state") or {}
        for rule_id, st in list(rule_state.items()):
            if st.get("held"):
                rule = st.get("rule") or {"id": rule_id, "name": st.get("name") or ""}
                label = str(st.get("label") or "")
                sig = st.get("signature")
                try:
                    self._emit_rule(widget_id, rule, False, label, sig)
                except Exception as err:
                    syslog.debug(f"OBS OVERLAY OCR: release failed: {err}")
                st["held"] = False
            st["matched"] = False
            st["miss_count"] = 0
        slot["matched"] = []

    def _apply_rules(self, item: dict[str, Any], text: str, slot: dict[str, Any], force_eval: bool = False):
        widget_id = str(item.get("id") or "")
        session = slot.get("session")
        rules = normalize_ocr_rules(item.get("ocr_rules"))
        style = item.get("style") or {}
        pack_id = str(style.get("ocr_pack_id") or "").strip()
        rule_state = slot.setdefault("rule_state", {})
        miss_limit = normalize_ocr_miss_tolerance(
            slot.get("miss_tolerance")
            if slot.get("miss_tolerance") is not None
            else style.get("ocr_miss_tolerance")
        )
        matched_names = []
        for rule in rules:
            if not self._session_current(session):
                return
            rule_id = str(rule.get("id") or "")
            # Re-attach pack id from widget style when the saved rule lost `_runtime`.
            if pack_id and not rule.get("pack_id"):
                rule["pack_id"] = pack_id
            if pack_id:
                runtime = rule.get("_runtime") if isinstance(rule.get("_runtime"), dict) else {}
                runtime = dict(runtime)
                runtime.setdefault("pack_id", pack_id)
                rule["_runtime"] = runtime
            st = rule_state.setdefault(
                rule_id,
                {
                    "matched": False,
                    "held": False,
                    "miss_count": 0,
                    "label": "",
                    "signature": None,
                    "rule": rule,
                },
            )
            st["rule"] = rule
            is_match, signature, label = rule_match_result(text, rule)
            runtime = _resolve_rule_runtime(rule, {"ocr_pack_id": pack_id} if pack_id else {})
            # SC Intelligence: blank / chrome OCR ("Idle", menu words) must not match.
            if is_match and str(runtime.get("kind") or "").casefold() == "citizen_lookup":
                from .ocr_lookup import clean_citizen_handle

                cleaned = clean_citizen_handle(label)
                if not cleaned:
                    is_match = False
                    label = ""
                    signature = None
                else:
                    label = cleaned
            prev_held = bool(st.get("held"))
            prev_label = str(st.get("label") or "")
            prev_sig = st.get("signature")
            rule_name = str(rule.get("name") or rule_id)
            if is_match:
                st["miss_count"] = 0
                st["matched"] = True
                st["label"] = label
                st["signature"] = signature
                if not prev_held or force_eval:
                    syslog.info(
                        "OBS OVERLAY OCR: MATCH edge rule=%s label=%r sig=%s text=%r",
                        rule_name,
                        label,
                        signature,
                        (text or "")[:120],
                    )
                    self._emit_rule(widget_id, rule, True, label, signature)
                    if not self._session_current(session):
                        return
                    st["held"] = True
                elif label != prev_label or signature != prev_sig:
                    # Still held — refresh contribute/replace with the new detection label.
                    syslog.info(
                        "OBS OVERLAY OCR: MATCH update rule=%s label=%r→%r sig=%s→%s",
                        rule_name,
                        prev_label,
                        label,
                        prev_sig,
                        signature,
                    )
                    self._emit_rule(widget_id, rule, True, label, signature)
                matched_names.append(label or rule_name)
            else:
                st["matched"] = False
                if prev_held:
                    misses = int(st.get("miss_count") or 0) + 1
                    st["miss_count"] = misses
                    if misses < miss_limit:
                        # Keep hold through flaky frames so Map-to-Overlay hold
                        # (contribute/replace) does not clear the label every miss.
                        syslog.info(
                            "OBS OVERLAY OCR: MATCH soft-miss rule=%s %s/%s (hold kept)",
                            rule_name,
                            misses,
                            miss_limit,
                        )
                        matched_names.append(str(st.get("label") or rule_name))
                    else:
                        syslog.info(
                            "OBS OVERLAY OCR: MATCH lost rule=%s after %s misses",
                            rule_name,
                            misses,
                        )
                        self._emit_rule(
                            widget_id,
                            rule,
                            False,
                            str(st.get("label") or label),
                            st.get("signature"),
                        )
                        st["held"] = False
                        st["miss_count"] = 0
                else:
                    st["miss_count"] = 0
        live_ids = {str(r.get("id") or "") for r in rules}
        for rid in list(rule_state):
            if rid not in live_ids:
                st = rule_state.pop(rid)
                if st.get("held"):
                    rule = st.get("rule") or {"id": rid}
                    self._emit_rule(widget_id, rule, False, str(st.get("label") or ""), st.get("signature"))
        if self._session_current(session):
            slot["matched"] = matched_names

    @staticmethod
    def _app_allows_scan() -> bool:
        """Skip OCR when nothing useful is on screen (app suspended / all windows minimized).

        Keep scanning while a live overlay window is visible even if the main
        JG Ex window is minimized — that is the normal HUD-over-game case.
        """
        try:
            from PySide6 import QtCore, QtWidgets

            app = QtWidgets.QApplication.instance()
            if app is None:
                return True
            state = app.applicationState()
            if state in (
                QtCore.Qt.ApplicationState.ApplicationSuspended,
                QtCore.Qt.ApplicationState.ApplicationHidden,
            ):
                return False
            # Live overlay up → keep scanning.
            try:
                from gremlin.ui.obs_overlay.ocr_capture import _overlay_windows

                if _overlay_windows():
                    return True
            except Exception:
                pass
            # No overlay: only scan if some non-minimized top-level is visible (designer).
            for widget in app.topLevelWidgets():
                try:
                    if widget.isWindow() and widget.isVisible() and not widget.isMinimized():
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return True

    def _run(self, stop):
        try:
            self._run_loop(stop)
        finally:
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None
                    pending = any(not job[2].cancelled.is_set() for job in self._test_jobs)
                    pending = pending or (self._profile_running() and any(s.get("armed") for s in self._slots.values()))
                    if pending:
                        self._ensure_thread()

    def _notify_test(self, session, on_done, result):
        if self._session_current(session) and on_done is not None:
            on_done(result)

    def _run_test_job(self, job, stop):
        from .ocr_engine import joined_text, recognize
        import gremlin.util

        widget_id, item, session, image, on_done = job
        cancelled = lambda: stop.is_set() or not self._session_current(session)
        if cancelled():
            return
        style = item.get("style") or {}
        try:
            hits, engine = recognize(image, engine=normalize_ocr_engine(style.get("ocr_engine")),
                                     min_confidence=normalize_ocr_confidence(style.get("ocr_confidence")), cancelled=cancelled)
            if cancelled():
                return
            text = joined_text(hits)
            with self._lock:
                if cancelled():
                    return
                slot = self._slots[widget_id]
                slot.update(last_text=text, hits=hits, engine=engine)
                slot["status"] = "Region unresolved" if image is None else (f"Test ({engine})" if engine != "none" else "No OCR engine")
                slot["generation"] = int(slot.get("generation") or 0) + 1
                self._apply_rules(item, text, slot, force_eval=True)
                result = text or slot["status"]
        except Exception as err:
            if cancelled():
                return
            with self._lock:
                if cancelled():
                    return
                self._slots[widget_id]["status"] = result = f"Error: {err}"
            syslog.warning("OBS OVERLAY OCR: test failed: %s", err)
        gremlin.util.InvokeUiMethod(self._notify_test, session, on_done, result)

    def _run_loop(self, stop):
        while not stop.is_set():
            with self._lock:
                test_job = self._test_jobs.popleft() if self._test_jobs else None
            if test_job is not None:
                self._run_test_job(test_job, stop)
                continue
            if not self._profile_running():
                # Profile stopped while the scanner was live — exit cleanly.
                with self._lock:
                    for slot in self._slots.values():
                        slot["armed"] = False
                        if (slot.get("session") and slot["session"].kind == "runtime"):
                            self._cancel_session(slot["session"])
                            slot["status"] = "Idle"
                return
            if not self._app_allows_scan():
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            jobs = []
            with self._lock:
                for widget_id, slot in self._slots.items():
                    if not slot.get("armed"):
                        continue
                    item = slot.get("item")
                    if not item:
                        continue
                    interval = max(0.1, float(slot.get("interval_ms") or 400) / 1000.0)
                    if (time.monotonic() - float(slot.get("last_scan") or 0.0)) < interval:
                        continue
                    jobs.append((widget_id, item, dict(slot)))
            if not jobs:
                self._wake.wait(0.15)
                self._wake.clear()
                with self._lock:
                    if not any(s.get("armed") for s in self._slots.values()):
                        return
                continue

            from .ocr_capture import capture_for_item_sync
            from .ocr_engine import joined_text, recognize

            for widget_id, item, snap in jobs:
                session = snap.get("session")
                cancelled = lambda session=session: stop.is_set() or not self._session_current(session)
                if cancelled():
                    continue
                if not self._app_allows_scan():
                    syslog.info("OBS OVERLAY OCR: scan paused (app not allowing scan)")
                    break
                try:
                    # Keep the HUD visible during armed scans (no hide/show flash).
                    # SRCCOPY omits layered windows; a cached re-blit repairs BitBlt glitches.
                    image = capture_for_item_sync(item, hide_overlay=False, cancelled=cancelled)
                    if cancelled():
                        continue
                    if image is None or image.isNull():
                        syslog.warning(
                            "OBS OVERLAY OCR: capture FAILED widget=%s region=%s (null image)",
                            widget_id,
                            snap.get("region"),
                        )
                        with self._lock:
                            slot = self._slots.get(widget_id)
                            if slot and not cancelled():
                                slot["status"] = "Capture failed"
                                slot["last_scan"] = time.monotonic()
                                self._consume_pulse(widget_id, slot)
                        continue
                    hits, engine = recognize(
                        image,
                        engine=snap.get("engine_pref") or "auto",
                        min_confidence=float(snap.get("confidence") or 0.70),
                        cancelled=cancelled,
                    )
                    if cancelled():
                        continue
                    text = joined_text(hits)
                    preview = (text or "").replace("\n", " ").strip()
                    if len(preview) > 160:
                        preview = preview[:157] + "..."
                    syslog.debug(
                        "OBS OVERLAY OCR: scan widget=%s engine=%s hits=%s size=%sx%s text=%r",
                        widget_id,
                        engine,
                        len(hits or []),
                        int(image.width()),
                        int(image.height()),
                        preview or "(empty)",
                    )
                    with self._lock:
                        slot = self._slots.get(widget_id)
                        if cancelled() or not slot or not slot.get("armed"):
                            syslog.info("OBS OVERLAY OCR: scan dropped (disarmed mid-scan) widget=%s", widget_id)
                            continue
                        slot["last_scan"] = time.monotonic()
                        slot["hits"] = hits
                        slot["engine"] = engine
                        slot["last_text"] = text
                        slot["status"] = "Armed" if engine != "none" else "No OCR engine"
                        slot["generation"] = int(slot.get("generation") or 0) + 1
                        rules = normalize_ocr_rules(item.get("ocr_rules"))
                        if not rules:
                            syslog.warning(
                                "OBS OVERLAY OCR: widget=%s has ZERO rules — nothing to fire",
                                widget_id,
                            )
                        self._apply_rules(item, text, slot)
                        self._consume_pulse(widget_id, slot)
                except Exception as err:
                    if cancelled():
                        continue
                    syslog.warning(f"OBS OVERLAY OCR: scan failed: {err}")
                    with self._lock:
                        slot = self._slots.get(widget_id)
                        if slot and not cancelled():
                            slot["status"] = f"Error: {err}"
                            slot["last_scan"] = time.monotonic()
                            self._consume_pulse(widget_id, slot)
            stop.wait(0.05)
