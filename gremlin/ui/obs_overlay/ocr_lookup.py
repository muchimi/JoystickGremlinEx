# -*- coding: utf-8; -*-
#
# RSI citizen dossier lookup for SC Intelligence OCR packs.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

import logging
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

syslog = logging.getLogger("system")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 JoystickGremlinEx-OCR/1.0"
)
_TIMEOUT_S = 15
_CACHE_TTL_S = 600.0
_CITIZEN_URL = "https://robertsspaceindustries.com/en/citizens/{handle}"

# Default variable names written by the SC Intelligence pack.
DEFAULT_FIELD_VARS = {
    "handle": "SCintell_handle",
    "name": "SCintell_name",
    "org": "SCintell_org",
    "enlisted": "SCintell_enlisted",
    "location": "SCintell_location",
    "fluency": "SCintell_fluency",
}

# OCR often grabs app chrome around the nameplate ("File Edit View Lolo_350").
_UI_STOPWORDS = frozenset(
    {
        "file",
        "edit",
        "view",
        "help",
        "window",
        "windows",
        "tools",
        "tool",
        "options",
        "settings",
        "profile",
        "handle",
        "name",
        "main",
        "organization",
        "org",
        "enlisted",
        "location",
        "fluency",
        "citizen",
        "dossier",
        "record",
        "uee",
        "spectrum",
        "identification",
        "sid",
        "rank",
        "master",
        "member",
        "affiliate",
        "wing",
        "commander",
        "the",
        "and",
        "or",
        "of",
        "to",
        "a",
        "an",
        # Overlay / HUD status chrome OCR often reads when the nameplate is blank.
        "idle",
        "armed",
        "ocr",
        "scanning",
        "scan",
        "test",
        "status",
        "none",
        "null",
        "n/a",
        "na",
    }
)
_HANDLE_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,63}")


def clean_citizen_handle(raw: str) -> str:
    """Pick the best RSI handle token from OCR text (ignore UI chrome words)."""
    text = str(raw or "").replace("\r", "\n")
    tokens = _HANDLE_TOKEN.findall(text)
    if not tokens:
        collapsed = re.sub(r"\s+", "", text.strip().strip("\"'`"))
        collapsed = re.sub(r"[^A-Za-z0-9_\-]", "", collapsed)
        if not collapsed or collapsed.casefold() in _UI_STOPWORDS:
            return ""
        return collapsed[:64]

    scored: list[tuple[int, int, str]] = []
    for index, tok in enumerate(tokens):
        low = tok.casefold()
        if low in _UI_STOPWORDS:
            continue
        # Pure menu-ish short words without underscore/digit are weak.
        score = 0
        if "_" in tok:
            score += 20
        if any(ch.isdigit() for ch in tok):
            score += 8
        if "-" in tok:
            score += 4
        if 4 <= len(tok) <= 32:
            score += 2
        if tok[0].isupper() and any(ch.islower() for ch in tok):
            score += 1  # CamelCase / Lolo_350 style
        if score <= 0:
            continue
        scored.append((score, index, tok))

    if scored:
        # Highest score, then prefer later tokens (handle usually at end of OCR blob).
        scored.sort()
        best = scored[-1][2]
        return best[:64]

    # Fallback: last non-stopword token. Never return chrome-only OCR as a handle.
    for tok in reversed(tokens):
        if tok.casefold() not in _UI_STOPWORDS:
            return tok[:64]
    return ""


def parse_citizen_html(html: str) -> dict[str, str]:
    """Extract dossier fields from an RSI citizen page (markup-tolerant)."""
    raw = str(html or "")
    # Collapse tags to spaces for label/value scanning.
    plain = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw)
    plain = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", plain)
    plain = re.sub(r"(?s)<[^>]+>", " ", plain)
    plain = re.sub(r"&nbsp;", " ", plain)
    plain = re.sub(r"&amp;", "&", plain)
    plain = re.sub(r"\s+", " ", plain).strip()

    def _after(label: str) -> str:
        pattern = re.compile(
            rf"{re.escape(label)}\s*(.+?)(?=(?:Handle name|Main organization|Spectrum Identification|"
            rf"Organization rank|Enlisted|Location|Fluency|UEE Citizen|CITIZEN DOSSIER|$))",
            re.IGNORECASE,
        )
        m = pattern.search(plain)
        if not m:
            return ""
        return re.sub(r"\s+", " ", m.group(1)).strip(" :-")

    def _first_handle_token(value: str) -> str:
        for tok in _HANDLE_TOKEN.findall(str(value or "")):
            if tok.casefold() not in _UI_STOPWORDS:
                return tok
        return ""

    handle_name = _first_handle_token(_after("Handle name"))
    # Display name often appears before Handle name; try title-ish token near dossier.
    display = ""
    m_title = re.search(
        r"CITIZEN DOSSIER.*?UEE Citizen Record[^\d]*\d+\s+([A-Za-z0-9_\-]{2,64})",
        plain,
        re.IGNORECASE,
    )
    if m_title:
        display = _first_handle_token(m_title.group(1))
    if display.casefold() in _UI_STOPWORDS or display.casefold() in ("profile", "citizen"):
        display = ""
    if not display:
        display = handle_name

    org = _after("Main organization")
    # Org block often includes SID / rank — keep the first line-ish token.
    if org:
        org = re.split(
            r"\s+(?:Spectrum Identification|Organization rank)\b",
            org,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        # Prefer leading ALLCAPS / word token group before SID code.
        org = re.sub(r"\s{2,}", " ", org).strip()
        # Drop trailing rank words if the greedy scrape pulled them in.
        org = re.split(r"\s+(?:Master|Member|Affiliate|Junior|Senior)\b", org, maxsplit=1)[0].strip()

    enlisted = _after("Enlisted")
    location = _after("Location")
    fluency = _after("Fluency")

    # Clean location commas ("Canada , Ontario" → "Canada, Ontario")
    location = re.sub(r"\s*,\s*", ", ", location)

    return {
        "name": display or handle_name,
        "org": org,
        "enlisted": enlisted,
        "location": location,
        "fluency": fluency,
    }


def fetch_citizen_dossier(handle: str) -> dict[str, str] | None:
    cleaned = clean_citizen_handle(handle)
    if not cleaned:
        return None
    url = _CITIZEN_URL.format(handle=urllib.parse.quote(cleaned, safe="_-"))
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            status = getattr(resp, "status", 200) or 200
            if int(status) >= 400:
                syslog.info("OBS OVERLAY OCR: RSI citizen HTTP %s for %s", status, cleaned)
                return None
            raw = resp.read()
    except urllib.error.HTTPError as err:
        syslog.info("OBS OVERLAY OCR: RSI citizen HTTP %s for %s", err.code, cleaned)
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        syslog.warning(f"OBS OVERLAY OCR: RSI citizen fetch failed for {cleaned}: {err}")
        return None
    try:
        html = raw.decode("utf-8", errors="replace")
    except Exception:
        return None
    fields = parse_citizen_html(html)
    fields["handle"] = cleaned
    return fields


def _write_variables(field_map: dict[str, str], values: dict[str, str]) -> None:
    import gremlin.util

    def _do():
        try:
            from gremlin.ui.obs_overlay import OverlayManager
            from gremlin.ui.obs_overlay.bindings import OverlayValueBus

            scene = OverlayManager().scene
            if scene is None:
                return
            changed = False
            for field, var_name in field_map.items():
                val = str((values or {}).get(field) or "")
                try:
                    if scene.set_overlay_variable_runtime_value(var_name, val):
                        changed = True
                except Exception as err:
                    syslog.debug(f"OBS OVERLAY OCR: set {var_name} failed: {err}")
            if changed:
                OverlayValueBus().refresh()
                syslog.info(
                    "OBS OVERLAY OCR: SCintell vars updated handle=%r name=%r org=%r",
                    values.get("handle"),
                    values.get("name"),
                    values.get("org"),
                )
        except Exception as err:
            syslog.warning(f"OBS OVERLAY OCR: SCintell write failed: {err}")

    try:
        gremlin.util.InvokeUiMethod(_do)
    except Exception:
        _do()


class OcrCitizenLookup:
    """Debounced, cached RSI citizen lookups driven by OCR hold state."""

    def __init__(self):
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[float, dict[str, str]]] = {}
        self._active_handle: str | None = None
        self._field_map: dict[str, str] = dict(DEFAULT_FIELD_VARS)
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def configure(self, field_map: dict[str, str] | None = None):
        with self._lock:
            if field_map:
                cleaned = {}
                for key, name in field_map.items():
                    k = str(key or "").strip().casefold()
                    n = str(name or "").strip().lstrip("%").rstrip("%")
                    if k and n:
                        cleaned[k] = n
                if cleaned:
                    self._field_map = cleaned

    def _ensure_thread(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="GexOcrCitizenLookup", daemon=True)
        self._thread.start()

    def lookup(self, handle_text: str, field_map: dict[str, str] | None = None):
        cleaned = clean_citizen_handle(handle_text)
        if cleaned and cleaned.casefold() in _UI_STOPWORDS:
            cleaned = ""
        if field_map:
            self.configure(field_map)
        with self._lock:
            self._active_handle = cleaned or None
        if not cleaned:
            self.clear()
            return
        self._ensure_thread()
        self._queue.put(("lookup", cleaned))

    def clear(self):
        with self._lock:
            self._active_handle = None
            field_map = dict(self._field_map)
        empty = {k: "" for k in field_map}
        _write_variables(field_map, empty)

    def _run(self):
        while not self._stop.is_set():
            try:
                op, payload = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if op != "lookup":
                continue
            handle = str(payload or "")
            with self._lock:
                if handle != self._active_handle:
                    continue
                field_map = dict(self._field_map)
                cached = self._cache.get(handle)
            now = time.monotonic()
            dossier = None
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                dossier = cached[1]
            else:
                dossier = fetch_citizen_dossier(handle)
                if dossier:
                    with self._lock:
                        self._cache[handle] = (time.monotonic(), dossier)
            with self._lock:
                if handle != self._active_handle:
                    continue
            if dossier:
                _write_variables(field_map, dossier)
            else:
                # Keep handle var so the user sees what was attempted; clear the rest.
                values = {k: "" for k in field_map}
                if "handle" in field_map:
                    values["handle"] = handle
                _write_variables(field_map, values)


_citizen_lookup: OcrCitizenLookup | None = None


def citizen_lookup() -> OcrCitizenLookup:
    global _citizen_lookup
    if _citizen_lookup is None:
        _citizen_lookup = OcrCitizenLookup()
    return _citizen_lookup
