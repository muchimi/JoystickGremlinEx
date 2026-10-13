# -*- coding: utf-8; -*-
#
# Soft-dep OCR backends for the overlay OCR widget: RapidOCR (primary) + Windows.Media.Ocr.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

import logging
import threading
from typing import Any

from PySide6 import QtGui

from .model import normalize_ocr_confidence, normalize_ocr_engine

syslog = logging.getLogger("system")

_lock = threading.RLock()
_rapid_engine = None
_rapid_error = ""
_windows_ready: bool | None = None
_windows_error = ""


def engine_status() -> dict[str, Any]:
    """Return availability of RapidOCR and Windows OCR for the inspector."""
    rapid_ok, rapid_msg = _probe_rapid()
    win_ok, win_msg = _probe_windows()
    return {
        "rapid": bool(rapid_ok),
        "rapid_message": rapid_msg,
        "windows": bool(win_ok),
        "windows_message": win_msg,
        "summary": _status_summary(rapid_ok, rapid_msg, win_ok, win_msg),
    }


def _status_summary(rapid_ok: bool, rapid_msg: str, win_ok: bool, win_msg: str) -> str:
    if rapid_ok and win_ok:
        return "RapidOCR (primary) · Windows OCR (fallback)"
    if rapid_ok:
        return "RapidOCR available"
    if win_ok:
        return f"Windows OCR only — {rapid_msg or 'install rapidocr + onnxruntime for best results'}"
    return f"No OCR engine — {rapid_msg or win_msg or 'install rapidocr + onnxruntime'}"


def _probe_rapid() -> tuple[bool, str]:
    global _rapid_error
    try:
        import rapidocr  # noqa: F401
        import onnxruntime  # noqa: F401

        return True, ""
    except Exception as err:
        _rapid_error = str(err).strip() or err.__class__.__name__
        if len(_rapid_error) > 180:
            _rapid_error = _rapid_error[:177] + "..."
        return False, _rapid_error


def _probe_windows() -> tuple[bool, str]:
    global _windows_ready, _windows_error
    if _windows_ready is not None:
        return bool(_windows_ready), _windows_error
    try:
        ocr = _windows_engine()
        _windows_ready = ocr is not None
        if not _windows_ready:
            _windows_error = "Windows.Media.Ocr unavailable"
        return bool(_windows_ready), _windows_error
    except Exception as err:
        _windows_ready = False
        _windows_error = str(err)
        return False, _windows_error


def _qimage_to_rgb_bytes(image: QtGui.QImage) -> tuple[bytes, int, int]:
    converted = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    width = int(converted.width())
    height = int(converted.height())
    ptr = converted.constBits()
    buf = bytes(ptr[: converted.sizeInBytes()])
    # Drop alpha → RGB for RapidOCR / WinOCR helpers that want 3 channels.
    try:
        import numpy as np

        rgba = np.frombuffer(buf, dtype=np.uint8).reshape((height, width, 4))
        rgb = np.ascontiguousarray(rgba[:, :, :3])
        return rgb.tobytes(), width, height
    except Exception:
        rgb = bytearray(width * height * 3)
        src = memoryview(buf)
        dst = memoryview(rgb)
        di = 0
        for i in range(0, len(src), 4):
            dst[di] = src[i]
            dst[di + 1] = src[i + 1]
            dst[di + 2] = src[i + 2]
            di += 3
        return bytes(rgb), width, height


def _qimage_to_numpy(image: QtGui.QImage):
    import numpy as np

    converted = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    width = int(converted.width())
    height = int(converted.height())
    ptr = converted.constBits()
    buf = bytes(ptr[: converted.sizeInBytes()])
    rgba = np.frombuffer(buf, dtype=np.uint8).reshape((height, width, 4))
    return np.ascontiguousarray(rgba[:, :, :3])


def _normalize_hits(raw_hits: list[dict[str, Any]], min_confidence: float) -> list[dict[str, Any]]:
    hits = []
    for entry in raw_hits or []:
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        try:
            conf = float(entry.get("confidence") if entry.get("confidence") is not None else 1.0)
        except (TypeError, ValueError):
            conf = 1.0
        if conf < float(min_confidence):
            continue
        hits.append(
            {
                "text": text,
                "confidence": round(max(0.0, min(1.0, conf)), 4),
                "box": entry.get("box"),
            }
        )
    return hits


def _get_rapid():
    global _rapid_engine, _rapid_error
    with _lock:
        if _rapid_engine is not None:
            return _rapid_engine
        try:
            from rapidocr import RapidOCR

            _rapid_engine = RapidOCR()
            _rapid_error = ""
            return _rapid_engine
        except Exception as err:
            _rapid_error = str(err)
            syslog.info(f"OBS OVERLAY OCR: RapidOCR unavailable: {err}")
            return None


def _recognize_rapid(image: QtGui.QImage, min_confidence: float) -> list[dict[str, Any]] | None:
    engine = _get_rapid()
    if engine is None:
        return None
    # RapidOCR logs WARNING "text detection result is empty" on blank frames —
    # normal while armed over empty HUD regions or when the app is minimized.
    rapid_log = logging.getLogger("RapidOCR")
    prior_level = rapid_log.level
    try:
        rapid_log.setLevel(logging.ERROR)
        arr = _qimage_to_numpy(image)
        result = engine(arr)
    except Exception as err:
        syslog.warning(f"OBS OVERLAY OCR: RapidOCR failed: {err}")
        return None
    finally:
        try:
            rapid_log.setLevel(prior_level)
        except Exception:
            pass
    hits: list[dict[str, Any]] = []
    # rapidocr>=3 returns an object; older returns (boxes, txts, scores) style tuples.
    try:
        txts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        boxes = getattr(result, "boxes", None)
        if txts is not None:
            for index, text in enumerate(txts or []):
                conf = 1.0
                if scores is not None and index < len(scores):
                    try:
                        conf = float(scores[index])
                    except (TypeError, ValueError):
                        conf = 1.0
                box = None
                if boxes is not None and index < len(boxes):
                    box = boxes[index]
                hits.append({"text": text, "confidence": conf, "box": box})
            return _normalize_hits(hits, min_confidence)
    except Exception:
        pass
    try:
        # Fallback: result may be (dt_boxes, rec_res, ...) where rec_res is list of (text, score)
        if isinstance(result, (list, tuple)) and result:
            payload = result[0] if isinstance(result[0], (list, tuple)) else result
            for row in payload or []:
                if isinstance(row, (list, tuple)) and len(row) >= 2:
                    if isinstance(row[1], (list, tuple)) and len(row[1]) >= 2:
                        text, conf = row[1][0], row[1][1]
                        box = row[0]
                    else:
                        text, conf = row[0], row[1]
                        box = None
                    hits.append({"text": text, "confidence": conf, "box": box})
            if hits:
                return _normalize_hits(hits, min_confidence)
    except Exception as err:
        syslog.warning(f"OBS OVERLAY OCR: RapidOCR parse failed: {err}")
    return []


def _windows_engine():
    # Prefer winrt package (Python 3.10+), then winsdk.
    try:
        from winrt.windows.media.ocr import OcrEngine  # type: ignore

        return OcrEngine.try_create_from_user_profile_languages()
    except Exception:
        pass
    try:
        from winsdk.windows.media.ocr import OcrEngine  # type: ignore

        return OcrEngine.try_create_from_user_profile_languages()
    except Exception:
        pass
    return None


def _recognize_windows(image: QtGui.QImage, min_confidence: float) -> list[dict[str, Any]] | None:
    global _windows_ready, _windows_error
    try:
        import asyncio
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap  # type: ignore
        from winrt.windows.storage.streams import DataWriter  # type: ignore
    except Exception:
        try:
            import asyncio
            from winsdk.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap  # type: ignore
            from winsdk.windows.storage.streams import DataWriter  # type: ignore
        except Exception as err:
            _windows_ready = False
            _windows_error = str(err)
            return None
    engine = _windows_engine()
    if engine is None:
        _windows_ready = False
        _windows_error = "Windows OCR engine could not be created"
        return None
    try:
        converted = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
        width = int(converted.width())
        height = int(converted.height())
        ptr = converted.constBits()
        raw = bytes(ptr[: converted.sizeInBytes()])
        writer = DataWriter()
        writer.write_bytes(list(raw))
        buffer = writer.detach_buffer()
        bitmap = SoftwareBitmap.create_copy_from_buffer(buffer, BitmapPixelFormat.RGBA8, width, height)

        async def _run():
            return await engine.recognize_async(bitmap)

        try:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(_run())
            finally:
                loop.close()
        except RuntimeError:
            # Already in an event loop — fall back to sync-ish polling via nest if needed.
            result = asyncio.get_event_loop().run_until_complete(_run())  # type: ignore

        hits = []
        lines = getattr(result, "lines", None) or []
        for line in lines:
            text = str(getattr(line, "text", "") or "").strip()
            if not text:
                continue
            # Windows OCR does not always expose per-line confidence; treat as 1.0.
            hits.append({"text": text, "confidence": 1.0, "box": None})
        _windows_ready = True
        return _normalize_hits(hits, min_confidence)
    except Exception as err:
        syslog.warning(f"OBS OVERLAY OCR: Windows OCR failed: {err}")
        _windows_error = str(err)
        return None


def recognize(
    image: QtGui.QImage | None,
    *,
    engine: str = "auto",
    min_confidence: float = 0.70,
) -> tuple[list[dict[str, Any]], str]:
    """Run OCR. Returns (hits, engine_used). engine_used is rapid|windows|none."""
    if image is None or image.isNull():
        return [], "none"
    pref = normalize_ocr_engine(engine)
    conf = normalize_ocr_confidence(min_confidence)
    order = []
    if pref == "rapid":
        order = ["rapid", "windows"]
    elif pref == "windows":
        order = ["windows", "rapid"]
    else:
        order = ["rapid", "windows"]
    for name in order:
        if name == "rapid":
            hits = _recognize_rapid(image, conf)
            if hits is not None:
                return hits, "rapid"
        elif name == "windows":
            hits = _recognize_windows(image, conf)
            if hits is not None:
                return hits, "windows"
    return [], "none"


def joined_text(hits: list[dict[str, Any]] | None) -> str:
    return " ".join(str(h.get("text") or "").strip() for h in (hits or []) if str(h.get("text") or "").strip())
