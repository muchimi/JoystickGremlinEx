# -*- coding: utf-8; -*-
#
# Remote video return feed: client capture/publish + master subscribe/decode.
# Separate from UDP remote control (gremlin.remote).
#
# Process model (client):
#   Main JG Ex process     – UDP VJoy/KVM only; supervises video worker
#   Video helper process   – TCP publish + capture/encode (gremlinEx --remote-video-worker)
#
# Thread model (video worker process):
#   GexRemoteVideoListen  – TCP accept only
#   GexRemoteVideo-Capture – GDI grab scaled at capture (CPU), latest-frame slot
#   GexRemoteVideo-Encode  – H.264 (GPU HW preferred) or JPEG; latest-packet slot
#   GexRemoteVideo-Send-*  – TCP send of the latest encoded packet only
#
# Thread model (master):
#   GexRemoteVideo-Recv-*  – TCP receive + H.264 decode (GPU HW preferred)
#   UI thread              – pixmap swap only (via InvokeUiMethod)
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other
# contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

import gremlin.config
import gremlin.shared_state
import gremlin.singleton_decorator
import gremlin.util

syslog = logging.getLogger("system")

MAGIC = b"GEXV"
CODEC_JPEG = 1
CODEC_H264 = 2
HEADER = struct.Struct("!4sBBHHI")  # magic, ver, codec, w, h, seq + separate !I length

# Populated only in the video helper process (from JSON); main process leaves this None.
_worker_settings: dict[str, Any] | None = None

_THREAD_PRIORITY_BELOW_NORMAL = -1
_COLORONCOLOR = 3
_HWND_CACHE_TTL_S = 2.0
_hwnd_cache: dict[str, Any] = {"needle": "", "hwnd": 0, "checked_at": 0.0}


def list_monitors() -> list[tuple[int, str]]:
    app = QtWidgets.QApplication.instance()
    if app is None:
        return [(0, "Primary")]
    out = []
    for index, screen in enumerate(app.screens()):
        geo = screen.geometry()
        name = screen.name() or f"Display {index + 1}"
        out.append((index, f"{index}: {name} ({geo.width()}x{geo.height()})"))
    return out or [(0, "Primary")]


def list_top_windows() -> list[tuple[int, str]]:
    """Visible top-level windows as (hwnd, title) for the Options picker."""
    windows: list[tuple[int, str]] = []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        GetWindowTextW = user32.GetWindowTextW
        GetWindowTextLengthW = user32.GetWindowTextLengthW
        IsWindowVisible = user32.IsWindowVisible
        GetWindow = user32.GetWindow
        GW_OWNER = 4

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lparam):
            if not IsWindowVisible(hwnd):
                return True
            if GetWindow(hwnd, GW_OWNER):
                return True
            length = GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if title:
                windows.append((int(hwnd), title))
            return True

        user32.EnumWindows(_enum, 0)
    except Exception as err:
        syslog.warning(f"REMOTE VIDEO: window enum failed: {err}")
    windows.sort(key=lambda item: item[1].casefold())
    return windows


def _find_hwnd_by_title(needle: str) -> int:
    needle = (needle or "").strip().casefold()
    if not needle:
        return 0
    windows = list_top_windows()
    # Exact title first (avoids locking onto the first "GEX Overlay — …").
    for hwnd, title in windows:
        if title.casefold() == needle:
            return hwnd
    starts = [(hwnd, title) for hwnd, title in windows if title.casefold().startswith(needle)]
    if starts:
        if len(starts) > 1 and needle.startswith("gex overlay"):
            try:
                from gremlin.ui.obs_overlay import OverlayManager
                from gremlin.ui.obs_overlay.model import overlay_window_title

                page = OverlayManager().scene.active_page()
                want = overlay_window_title(page).casefold()
                for hwnd, title in starts:
                    if title.casefold() == want:
                        return hwnd
            except Exception:
                pass
        return starts[0][0]
    for hwnd, title in windows:
        if needle in title.casefold():
            return hwnd
    return 0


def _find_hwnd_by_title_cached(needle: str) -> int:
    """Resolve window title without EnumWindows on every capture tick."""
    needle_key = (needle or "").strip().casefold()
    if not needle_key:
        return 0
    now = time.monotonic()
    try:
        import ctypes

        user32 = ctypes.windll.user32
        cached_hwnd = int(_hwnd_cache.get("hwnd") or 0)
        if (
            _hwnd_cache.get("needle") == needle_key
            and (now - float(_hwnd_cache.get("checked_at") or 0.0)) < _HWND_CACHE_TTL_S
            and cached_hwnd
            and user32.IsWindow(cached_hwnd)
            and user32.IsWindowVisible(cached_hwnd)
        ):
            return cached_hwnd
    except Exception:
        pass
    hwnd = _find_hwnd_by_title(needle_key)
    _hwnd_cache["needle"] = needle_key
    _hwnd_cache["hwnd"] = int(hwnd or 0)
    _hwnd_cache["checked_at"] = now
    return int(hwnd or 0)


def _even_size(width: int, height: int, max_width: int) -> tuple[int, int]:
    """Even target size (H.264 yuv420p) capped by max_width."""
    src_w = max(1, int(width))
    src_h = max(1, int(height))
    cap_w = max(2, int(max_width))
    if src_w > cap_w:
        target_w = cap_w
        target_h = max(2, int(round(src_h * (target_w / float(src_w)))))
    else:
        target_w = src_w
        target_h = src_h
    target_w &= ~1
    target_h &= ~1
    if target_w < 2 or target_h < 2:
        return 0, 0
    return target_w, target_h


def _set_current_thread_priority(level: int) -> None:
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), int(level))
    except Exception:
        pass


def _scale_image(image: QtGui.QImage, max_width: int) -> QtGui.QImage:
    if image.isNull():
        return image
    # H.264 (yuv420p) needs even dimensions.
    target_w = int(max_width)
    if image.width() > target_w:
        image = image.scaledToWidth(target_w, QtCore.Qt.FastTransformation)
    w = image.width() & ~1
    h = image.height() & ~1
    if w <= 0 or h <= 0:
        return QtGui.QImage()
    if w != image.width() or h != image.height():
        image = image.copy(0, 0, w, h)
    return image


def _active_video_settings() -> dict[str, Any]:
    """Worker JSON settings, or live Options config when running in-process (tests)."""
    if _worker_settings is not None:
        return _worker_settings
    cfg = gremlin.config.Configuration()
    return {
        "port": int(cfg.remote_video_port),
        "fps": int(cfg.remote_video_fps),
        "max_width": int(cfg.remote_video_max_width),
        "quality": int(cfg.remote_video_quality),
        "encoder": str(cfg.remote_video_encoder or "auto"),
        "source": str(cfg.remote_video_source or "screen"),
        "monitor_index": int(cfg.remote_video_monitor_index),
        "window_title": str(cfg.remote_video_window_title or ""),
        "parent_pid": 0,
    }


def _encode_jpeg(image: QtGui.QImage, quality: int) -> bytes:
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    image.save(buf, "JPG", int(quality))
    return bytes(buf.data())


def _qimage_to_bgra_ndarray(image: QtGui.QImage):
    """BGRA layout matching Qt Format_RGB32 on little-endian Windows — skips RGB888 copy."""
    import numpy as np

    converted = image
    if converted.format() != QtGui.QImage.Format_RGB32:
        converted = converted.convertToFormat(QtGui.QImage.Format_RGB32)
    w = converted.width()
    h = converted.height()
    bpl = converted.bytesPerLine()
    ptr = converted.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8, count=h * bpl)
    if bpl == w * 4:
        return arr.reshape((h, w, 4)).copy()
    out = np.empty((h, w, 4), dtype=np.uint8)
    for y in range(h):
        start = y * bpl
        out[y] = arr[start : start + w * 4].reshape((w, 4))
    return out


def _rgb_ndarray_to_qimage(arr) -> QtGui.QImage:
    import numpy as np

    if arr is None:
        return QtGui.QImage()
    h, w = int(arr.shape[0]), int(arr.shape[1])
    contiguous = np.ascontiguousarray(arr, dtype=np.uint8)
    image = QtGui.QImage(contiguous.data, w, h, w * 3, QtGui.QImage.Format_RGB888)
    return image.copy()


def _quality_to_crf(quality: int) -> int:
    # Map UI quality 1..100 → x264 CRF ~35..18 (lower CRF = better).
    q = max(1, min(100, int(quality)))
    return int(round(35 - (q / 100.0) * 17))


def _quality_to_bitrate_kbps(quality: int, width: int, height: int, fps: int) -> int:
    # Rough bitrate budget for HW encoders that ignore CRF.
    pixels = max(1, int(width) * int(height))
    base = pixels * max(1, int(fps)) * 0.07 / 1000.0  # ~0.07 bit/pixel heuristic
    scale = 0.35 + (max(1, min(100, int(quality))) / 100.0) * 1.4
    return max(250, min(12000, int(base * scale)))


class _H264Encoder:
    """PyAV H.264 encoder with hardware preference and libx264 fallback."""

    def __init__(self):
        self._ctx = None
        self._codec_name = ""
        self._width = 0
        self._height = 0
        self._fps = 0
        self._pts = 0
        self._failed = False

    @property
    def active(self) -> bool:
        return self._ctx is not None and not self._failed

    @property
    def codec_name(self) -> str:
        return self._codec_name

    def close(self):
        self._ctx = None
        self._codec_name = ""
        self._width = 0
        self._height = 0
        self._fps = 0
        self._pts = 0

    def _candidates(self, preference: str) -> list[str]:
        pref = (preference or "auto").casefold()
        hw = ["h264_nvenc", "h264_amf", "h264_qsv", "h264_mf"]
        soft = ["libx264"]
        if pref == "nvenc":
            return ["h264_nvenc"] + soft
        if pref == "amf":
            return ["h264_amf"] + soft
        if pref == "qsv":
            return ["h264_qsv"] + soft
        if pref == "h264":
            return soft + hw
        # auto: prefer HW then software
        return hw + soft

    def _open(self, width: int, height: int, fps: int, quality: int, preference: str) -> bool:
        try:
            import av
            from fractions import Fraction
        except Exception as err:
            syslog.warning(f"REMOTE VIDEO: PyAV unavailable for H.264: {err}")
            self._failed = True
            return False

        width = int(width) & ~1
        height = int(height) & ~1
        fps = max(1, min(30, int(fps)))
        if width < 16 or height < 16:
            return False

        last_err = None
        for name in self._candidates(preference):
            try:
                ctx = av.CodecContext.create(name, "w")
                ctx.width = width
                ctx.height = height
                ctx.pix_fmt = "yuv420p"
                ctx.time_base = Fraction(1, fps)
                ctx.framerate = Fraction(fps, 1)
                ctx.gop_size = fps
                ctx.options = {}
                if name == "libx264":
                    ctx.options = {
                        "preset": "ultrafast",
                        "tune": "zerolatency",
                        "crf": str(_quality_to_crf(quality)),
                        "repeat-headers": "1",
                    }
                else:
                    kbps = _quality_to_bitrate_kbps(quality, width, height, fps)
                    ctx.bit_rate = kbps * 1000
                    if name == "h264_nvenc":
                        ctx.options = {"preset": "ll", "zerolatency": "1", "rc": "vbr"}
                    elif name == "h264_amf":
                        ctx.options = {"usage": "ultralowlatency", "quality": "speed"}
                    elif name == "h264_qsv":
                        ctx.options = {"preset": "veryfast"}
                ctx.open()
                self._ctx = ctx
                self._codec_name = name
                self._width = width
                self._height = height
                self._fps = fps
                self._pts = 0
                self._failed = False
                syslog.info(f"REMOTE VIDEO: H.264 encoder ready ({name}) {width}x{height}@{fps}")
                return True
            except Exception as err:
                last_err = err
                continue
        syslog.warning(f"REMOTE VIDEO: no H.264 encoder available: {last_err}")
        self._failed = True
        self._ctx = None
        return False

    def encode(self, image: QtGui.QImage, fps: int, quality: int, preference: str) -> bytes | None:
        if image is None or image.isNull():
            return None
        w = image.width() & ~1
        h = image.height() & ~1
        if w != image.width() or h != image.height():
            image = image.copy(0, 0, w, h)
        fps = max(1, min(30, int(fps)))
        if (
            self._ctx is None
            or self._width != w
            or self._height != h
            or self._fps != fps
            or self._failed
        ):
            self.close()
            if not self._open(w, h, fps, quality, preference):
                return None
        try:
            import av

            rgb = _qimage_to_bgra_ndarray(image)
            frame = av.VideoFrame.from_ndarray(rgb, format="bgra")
            frame = frame.reformat(format="yuv420p")
            frame.pts = self._pts
            self._pts += 1
            blobs = []
            for packet in self._ctx.encode(frame):
                blobs.append(bytes(packet))
            if not blobs:
                return None
            return b"".join(blobs)
        except Exception as err:
            syslog.warning(f"REMOTE VIDEO: H.264 encode failed ({self._codec_name}): {err}")
            self.close()
            self._failed = True
            return None


class _H264Decoder:
    """Decode H.264; prefer decoders that return system memory, else software."""

    def __init__(self):
        self._ctx = None
        self._codec_name = ""
        self._skip = set()

    def close(self):
        self._ctx = None
        self._codec_name = ""

    def _candidates(self) -> list[str]:
        # Skip pure CUDA/D3D surfaces unless we add an explicit download path.
        # h264_mf / h264_qsv usually yield CPU frames; libav 'h264' is software.
        ordered = ["h264_mf", "h264_qsv", "h264"]
        return [n for n in ordered if n not in self._skip]

    def _open(self) -> bool:
        try:
            import av
        except Exception:
            return False
        for name in self._candidates():
            try:
                ctx = av.CodecContext.create(name, "r")
                ctx.open()
                self._ctx = ctx
                self._codec_name = name
                syslog.info(f"REMOTE VIDEO: H.264 decoder ready ({name})")
                return True
            except Exception:
                self._skip.add(name)
                continue
        return False

    def decode(self, payload: bytes) -> QtGui.QImage | None:
        if not payload:
            return None
        try:
            import av
        except Exception:
            return None
        attempts = 0
        while attempts < 3:
            attempts += 1
            try:
                if self._ctx is None and not self._open():
                    return None
                packet = av.Packet(payload)
                frames = list(self._ctx.decode(packet))
                if not frames:
                    return None
                frame = frames[-1]
                try:
                    rgb = frame.to_ndarray(format="rgb24")
                except Exception:
                    # HW surface without download support — skip this decoder.
                    self._skip.add(self._codec_name)
                    self.close()
                    continue
                return _rgb_ndarray_to_qimage(rgb)
            except Exception as err:
                syslog.debug(f"REMOTE VIDEO: H.264 decode failed ({self._codec_name}): {err}")
                if self._codec_name:
                    self._skip.add(self._codec_name)
                self.close()
        return None


def _pack_frame(seq: int, width: int, height: int, payload: bytes, codec: int = CODEC_JPEG) -> bytes:
    header = HEADER.pack(
        MAGIC,
        1,
        int(codec) & 0xFF,
        int(width) & 0xFFFF,
        int(height) & 0xFFFF,
        int(seq) & 0xFFFFFFFF,
    )
    return header + struct.pack("!I", len(payload)) + payload


def _read_exact(sock: socket.socket, size: int) -> bytes | None:
    chunks = []
    remaining = size
    while remaining > 0:
        try:
            block = sock.recv(remaining)
        except OSError:
            return None
        if not block:
            return None
        chunks.append(block)
        remaining -= len(block)
    return b"".join(chunks)


def _unpack_frame(sock: socket.socket) -> tuple[int, int, int, int, bytes] | None:
    """Returns (seq, width, height, codec, payload)."""
    raw = _read_exact(sock, HEADER.size + 4)
    if not raw:
        return None
    magic, _ver, codec, width, height, seq = HEADER.unpack(raw[: HEADER.size])
    if magic != MAGIC or codec not in (CODEC_JPEG, CODEC_H264):
        return None
    (length,) = struct.unpack("!I", raw[HEADER.size :])
    if length <= 0 or length > 16 * 1024 * 1024:
        return None
    payload = _read_exact(sock, length)
    if payload is None:
        return None
    return seq, width, height, int(codec), payload


def _monitor_rect(monitor_index: int) -> tuple[int, int, int, int] | None:
    """Return (left, top, width, height) for a display index via Win32."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        monitors: list[tuple[int, int, int, int]] = []

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        MonitorEnumProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(RECT),
            wintypes.LPARAM,
        )

        def _enum(hmon, hdc, lprect, _lparam):
            r = lprect.contents
            monitors.append((int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)))
            return True

        user32.EnumDisplayMonitors(0, 0, MonitorEnumProc(_enum), 0)
        if not monitors:
            w = int(user32.GetSystemMetrics(0))
            h = int(user32.GetSystemMetrics(1))
            return (0, 0, w, h) if w > 0 and h > 0 else None
        index = max(0, min(len(monitors) - 1, int(monitor_index)))
        return monitors[index]
    except Exception as err:
        syslog.debug(f"REMOTE VIDEO: monitor enum failed: {err}")
        return None


def _qimage_from_dibits(gdi32, hdc_mem, hbmp, width: int, height: int) -> QtGui.QImage | None:
    import ctypes
    from ctypes import wintypes

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buf = (ctypes.c_char * (width * height * 4))()
    got = gdi32.GetDIBits(hdc_mem, hbmp, 0, height, buf, ctypes.byref(bmi), 0)
    if not got:
        return None
    image = QtGui.QImage(bytes(buf), width, height, width * 4, QtGui.QImage.Format_RGB32)
    return image.copy()


def _grab_screen_gdi(monitor_index: int, max_width: int) -> QtGui.QImage | None:
    """Desktop capture scaled at Blit time (no full-res QImage)."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        rect = _monitor_rect(monitor_index)
        if not rect:
            return None
        left, top, width, height = rect
        if width <= 0 or height <= 0:
            return None
        target_w, target_h = _even_size(width, height, max_width)
        if not target_w:
            return None

        hdc_screen = user32.GetDC(0)
        if not hdc_screen:
            return None
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, target_w, target_h)
        old = gdi32.SelectObject(hdc_mem, hbmp)
        SRCCOPY = 0x00CC0020
        gdi32.SetStretchBltMode(hdc_mem, _COLORONCOLOR)
        if target_w == width and target_h == height:
            ok = gdi32.BitBlt(hdc_mem, 0, 0, target_w, target_h, hdc_screen, left, top, SRCCOPY)
        else:
            ok = gdi32.StretchBlt(
                hdc_mem, 0, 0, target_w, target_h, hdc_screen, left, top, width, height, SRCCOPY
            )
        image = _qimage_from_dibits(gdi32, hdc_mem, hbmp, target_w, target_h) if ok else None
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)
        return image
    except Exception as err:
        syslog.debug(f"REMOTE VIDEO: GDI screen grab failed: {err}")
        return None


def _grab_window_gdi(hwnd: int, max_width: int) -> QtGui.QImage | None:
    if not hwnd:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        rect = RECT()
        if not user32.GetClientRect(int(hwnd), ctypes.byref(rect)):
            return None
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width <= 0 or height <= 0:
            return None
        target_w, target_h = _even_size(width, height, max_width)
        if not target_w:
            return None

        hdc_win = user32.GetDC(int(hwnd))
        if not hdc_win:
            return None
        hdc_full = gdi32.CreateCompatibleDC(hdc_win)
        hbmp_full = gdi32.CreateCompatibleBitmap(hdc_win, width, height)
        old_full = gdi32.SelectObject(hdc_full, hbmp_full)
        PW_CLIENTONLY = 1
        PW_RENDERFULLCONTENT = 2
        ok = bool(user32.PrintWindow(int(hwnd), hdc_full, PW_CLIENTONLY | PW_RENDERFULLCONTENT))
        if not ok:
            SRCCOPY = 0x00CC0020
            ok = bool(gdi32.BitBlt(hdc_full, 0, 0, width, height, hdc_win, 0, 0, SRCCOPY))

        image = None
        if ok:
            if target_w == width and target_h == height:
                image = _qimage_from_dibits(gdi32, hdc_full, hbmp_full, width, height)
            else:
                hdc_small = gdi32.CreateCompatibleDC(hdc_win)
                hbmp_small = gdi32.CreateCompatibleBitmap(hdc_win, target_w, target_h)
                old_small = gdi32.SelectObject(hdc_small, hbmp_small)
                SRCCOPY = 0x00CC0020
                gdi32.SetStretchBltMode(hdc_small, _COLORONCOLOR)
                stretched = gdi32.StretchBlt(
                    hdc_small, 0, 0, target_w, target_h, hdc_full, 0, 0, width, height, SRCCOPY
                )
                if stretched:
                    image = _qimage_from_dibits(gdi32, hdc_small, hbmp_small, target_w, target_h)
                gdi32.SelectObject(hdc_small, old_small)
                gdi32.DeleteObject(hbmp_small)
                gdi32.DeleteDC(hdc_small)

        gdi32.SelectObject(hdc_full, old_full)
        gdi32.DeleteObject(hbmp_full)
        gdi32.DeleteDC(hdc_full)
        user32.ReleaseDC(int(hwnd), hdc_win)
        return image
    except Exception as err:
        syslog.debug(f"REMOTE VIDEO: GDI window grab failed: {err}")
        return None


def grab_window_image(hwnd: int, max_width: int = 960) -> QtGui.QImage | None:
    """Public GDI PrintWindow capture for overlay Application widgets."""
    return _grab_window_gdi(int(hwnd or 0), int(max_width or 960))


def _grab_frame_image() -> QtGui.QImage | None:
    """Capture on the caller thread via GDI — never blocks the Qt UI loop."""
    settings = _active_video_settings()
    max_w = max(320, min(1920, int(settings.get("max_width") or 960)))
    try:
        if str(settings.get("source") or "screen") == "window":
            hwnd = _find_hwnd_by_title_cached(str(settings.get("window_title") or ""))
            image = _grab_window_gdi(hwnd, max_w) if hwnd else None
            if image is None:
                image = _grab_screen_gdi(int(settings.get("monitor_index") or 0), max_w)
            return image
        return _grab_screen_gdi(int(settings.get("monitor_index") or 0), max_w)
    except Exception as err:
        syslog.debug(f"REMOTE VIDEO: capture failed: {err}")
        return None


class _LatestSlot:
    """Single-slot latest-wins handoff between pipeline stages (no backlog)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._seq = 0
        self._item = None
        self._event = threading.Event()

    def put(self, item):
        with self._lock:
            self._seq += 1
            self._item = item
            seq = self._seq
        self._event.set()
        return seq

    def get_latest(self, after_seq: int = 0, timeout: float | None = 0.05):
        if after_seq >= self._seq:
            self._event.wait(timeout if timeout is not None else 0.05)
            self._event.clear()
        with self._lock:
            if self._item is None or self._seq <= after_seq:
                return after_seq, None
            return self._seq, self._item

    def clear(self):
        with self._lock:
            self._item = None
            self._seq = 0
        self._event.clear()


class _CaptureBroker:
    """Remote-video pipeline: Capture thread → Encode thread → shared packet slot.

    Network send threads only copy the latest encoded packet (never capture/encode).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._encode_thread: threading.Thread | None = None
        self._refs = 0
        self._frame_slot = _LatestSlot()
        self._packet_slot = _LatestSlot()
        self._encoder = _H264Encoder()
        self._packet_seq = 0

    def acquire(self):
        with self._lock:
            self._refs += 1
            if self._capture_thread is None or not self._capture_thread.is_alive():
                self._stop.clear()
                self._frame_slot.clear()
                self._packet_slot.clear()
                self._capture_thread = threading.Thread(
                    target=self._capture_loop, daemon=True, name="GexRemoteVideo-Capture"
                )
                self._encode_thread = threading.Thread(
                    target=self._encode_loop, daemon=True, name="GexRemoteVideo-Encode"
                )
                self._capture_thread.start()
                self._encode_thread.start()

    def release(self):
        with self._lock:
            self._refs = max(0, self._refs - 1)
            if self._refs == 0:
                self._stop.set()
                self._frame_slot._event.set()
                self._packet_slot._event.set()

    def stop(self):
        with self._lock:
            self._refs = 0
            self._stop.set()
            self._frame_slot._event.set()
            self._packet_slot._event.set()
        for thread in (self._capture_thread, self._encode_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=1.5)
        self._capture_thread = None
        self._encode_thread = None
        self._encoder.close()
        self._frame_slot.clear()
        self._packet_slot.clear()

    def wait_next(self, after_seq: int, timeout: float = 0.05) -> tuple[int, bytes | None]:
        """Block until a newer encoded packet than after_seq is available."""
        return self._packet_slot.get_latest(after_seq=after_seq, timeout=timeout)

    def latest(self) -> tuple[int, bytes] | None:
        seq, item = self._packet_slot.get_latest(after_seq=0, timeout=0.0)
        if item is None:
            return None
        return seq, item

    def _capture_loop(self):
        _set_current_thread_priority(_THREAD_PRIORITY_BELOW_NORMAL)
        syslog.info("REMOTE VIDEO: capture thread started (CPU/GDI)")
        while not self._stop.is_set():
            started = time.monotonic()
            settings = _active_video_settings()
            fps = max(1, min(30, int(settings.get("fps") or 12)))
            max_w = max(320, min(1920, int(settings.get("max_width") or 960)))
            image = _grab_frame_image()
            if image is not None and not image.isNull():
                # Grab already scales via StretchBlt; keep even-dim safety net.
                if image.width() > max_w or (image.width() & 1) or (image.height() & 1):
                    image = _scale_image(image, max_w)
                if not image.isNull():
                    self._frame_slot.put(
                        (
                            image,
                            fps,
                            max(1, min(100, int(settings.get("quality") or 55))),
                            str(settings.get("encoder") or "auto"),
                        )
                    )
            delay = max(0.0, (1.0 / fps) - (time.monotonic() - started))
            if delay:
                self._stop.wait(delay)
        syslog.info("REMOTE VIDEO: capture thread stopped")

    def _encode_loop(self):
        _set_current_thread_priority(_THREAD_PRIORITY_BELOW_NORMAL)
        syslog.info("REMOTE VIDEO: encode thread started (GPU H.264 preferred)")
        last_frame_seq = 0
        while not self._stop.is_set():
            last_frame_seq, item = self._frame_slot.get_latest(after_seq=last_frame_seq, timeout=0.05)
            if item is None:
                continue
            image, fps, quality, preference = item
            packet = None
            if preference != "jpeg":
                payload = self._encoder.encode(image, fps, quality, preference)
                if payload:
                    packet = _pack_frame(
                        self._packet_seq + 1,
                        image.width(),
                        image.height(),
                        payload,
                        CODEC_H264,
                    )
            if packet is None:
                jpeg = _encode_jpeg(image, quality)
                packet = _pack_frame(
                    self._packet_seq + 1,
                    image.width(),
                    image.height(),
                    jpeg,
                    CODEC_JPEG,
                )
            self._packet_seq = (self._packet_seq + 1) & 0xFFFFFFFF
            self._packet_slot.put(packet)
            time.sleep(0)  # yield GIL to other work
        self._encoder.close()
        syslog.info("REMOTE VIDEO: encode thread stopped")


_capture_broker = _CaptureBroker()


class _PublisherSession(threading.Thread):
    """One TCP subscriber — only ships frames produced by the shared broker."""

    def __init__(self, conn: socket.socket, addr, stop_event: threading.Event):
        super().__init__(daemon=True, name="GexRemoteVideo-Send")
        self._conn = conn
        self._addr = addr
        self._stop = stop_event

    def run(self):
        _set_current_thread_priority(_THREAD_PRIORITY_BELOW_NORMAL)
        last_seq = 0
        _capture_broker.acquire()
        try:
            self._conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                self._conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
            except OSError:
                pass
            syslog.info(f"REMOTE VIDEO: client connected from {self._addr}")
            while not self._stop.is_set():
                seq, packet = _capture_broker.wait_next(last_seq, timeout=0.05)
                if packet is None or seq == last_seq:
                    continue
                last_seq = seq
                try:
                    self._conn.sendall(packet)
                except OSError:
                    break
        finally:
            _capture_broker.release()
            try:
                self._conn.close()
            except OSError:
                pass
            syslog.info(f"REMOTE VIDEO: client disconnected {self._addr}")


def _parent_process_alive(pid: int) -> bool:
    if not pid or int(pid) <= 0:
        return True
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        code = wintypes.DWORD()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and int(code.value) == STILL_ACTIVE
    except Exception:
        return False


def _run_worker_server(stop_event: threading.Event) -> None:
    """TCP listen + capture/encode inside the helper process."""
    settings = _active_video_settings()
    port = int(settings.get("port") or 6013)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.listen(4)
        sock.settimeout(1.0)
        syslog.info(f"REMOTE VIDEO: worker publishing on TCP port {port}")
    except OSError as err:
        syslog.error(f"REMOTE VIDEO: worker failed to listen on {port}: {err}")
        return
    sessions: list[_PublisherSession] = []
    try:
        while not stop_event.is_set():
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            session = _PublisherSession(conn, addr, stop_event)
            sessions.append(session)
            session.start()
    finally:
        stop_event.set()
        try:
            sock.close()
        except OSError:
            pass
        for session in sessions:
            session.join(timeout=0.5)
        _capture_broker.stop()


def _set_worker_process_identity(app: QtGui.QGuiApplication) -> QtGui.QWindow:
    """Make Task Manager show this helper as 'Video Stream' (not bare gremlinEx)."""
    title = "Video Stream"
    try:
        app.setApplicationName(title)
        app.setApplicationDisplayName(title)
        app.setDesktopFileName("gremlinex-video-stream")
    except Exception:
        pass
    try:
        import ctypes

        # Distinct AppUserModelID so Windows does not merge this with the main UI process.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EMCS.GremlinEx.VideoStream")
    except Exception:
        pass
    # Task Manager's Apps list uses a window title when one exists.
    win = QtGui.QWindow()
    win.setTitle(title)
    win.setFlags(
        QtCore.Qt.Tool
        | QtCore.Qt.FramelessWindowHint
        | QtCore.Qt.WindowDoesNotAcceptFocus
        | QtCore.Qt.WindowTransparentForInput
        | QtCore.Qt.WindowStaysOnBottomHint
    )
    win.setOpacity(0.0)
    win.resize(1, 1)
    win.setPosition(-32000, -32000)
    win.show()
    return win


def worker_main(argv: list[str] | None = None) -> int:
    """Entry for `gremlinEx --remote-video-worker <config.json>`."""
    global _worker_settings
    argv = list(argv if argv is not None else sys.argv)
    try:
        flag_i = argv.index("--remote-video-worker")
        config_path = argv[flag_i + 1]
    except (ValueError, IndexError):
        print("REMOTE VIDEO: worker requires --remote-video-worker <config.json>", file=sys.stderr)
        return 2
    try:
        with open(config_path, "r", encoding="utf-8-sig") as fh:
            raw = json.load(fh)
    except Exception as err:
        print(f"REMOTE VIDEO: worker cannot read config {config_path}: {err}", file=sys.stderr)
        return 2

    # Ensure worker messages reach the supervisor log file (stdout/stderr redirected).
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not syslog.handlers:
        syslog.addHandler(logging.StreamHandler(sys.stdout))
        syslog.setLevel(logging.INFO)

    _worker_settings = {
        "port": int(raw.get("port") or 6013),
        "fps": max(1, min(30, int(raw.get("fps") or 12))),
        "max_width": max(320, min(3840, int(raw.get("max_width") or 960))),
        "quality": max(1, min(100, int(raw.get("quality") or 55))),
        "encoder": str(raw.get("encoder") or "auto"),
        "source": str(raw.get("source") or "screen"),
        "monitor_index": max(0, int(raw.get("monitor_index") or 0)),
        "window_title": str(raw.get("window_title") or ""),
        "parent_pid": int(raw.get("parent_pid") or 0),
    }
    parent_pid = int(_worker_settings["parent_pid"])
    syslog.info(
        f"REMOTE VIDEO: worker start pid={os.getpid()} parent={parent_pid} "
        f"port={_worker_settings['port']} {_worker_settings['max_width']}px "
        f"@{_worker_settings['fps']}fps enc={_worker_settings['encoder']}"
    )

    app = QtGui.QGuiApplication.instance()
    if app is None:
        # First argv entry becomes the process display stem; keep a stable identity.
        app = QtGui.QGuiApplication(["Video Stream"] + argv[1:])
    identity_window = _set_worker_process_identity(app)

    stop_event = threading.Event()

    def _watch_parent():
        while not stop_event.is_set():
            if not _parent_process_alive(parent_pid):
                syslog.info("REMOTE VIDEO: parent process exited — stopping worker")
                stop_event.set()
                app.quit()
                break
            stop_event.wait(0.5)

    watcher = threading.Thread(target=_watch_parent, daemon=True, name="GexRemoteVideo-ParentWatch")
    watcher.start()

    server = threading.Thread(
        target=_run_worker_server, args=(stop_event,), daemon=True, name="GexRemoteVideo-Listen"
    )
    server.start()

    # Keep Qt event loop alive for QImage / timers; exit when stop_event set.
    def _poll_stop():
        if stop_event.is_set():
            app.quit()
        else:
            QtCore.QTimer.singleShot(250, _poll_stop)

    QtCore.QTimer.singleShot(250, _poll_stop)
    code = app.exec()
    stop_event.set()
    server.join(timeout=2.0)
    _capture_broker.stop()
    try:
        identity_window.close()
    except Exception:
        pass
    syslog.info("REMOTE VIDEO: worker exit")
    return int(code or 0)


def _supervisor_command(config_path: str) -> tuple[list[str], str]:
    """Build spawn command and cwd for the video helper process."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        cwd = os.path.dirname(os.path.abspath(exe))
        return [exe, "--remote-video-worker", config_path], cwd
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    script = os.path.join(root, "gremlinEx.py")
    return [sys.executable, script, "--remote-video-worker", config_path], root


@gremlin.singleton_decorator.SingletonDecorator
class RemoteVideoPublisher:
    """Main-process supervisor: spawns/stops the remote-video helper process."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._config_path: str | None = None
        self._log_path: str | None = None
        self._log_fh = None
        self._monitor: threading.Thread | None = None
        self._stop_monitor = threading.Event()
        self._want_running = False
        self._respawn_backoff_s = 1.0

    @property
    def running(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None

    def start(self):
        cfg = gremlin.config.Configuration()
        if not cfg.enable_remote_control or not cfg.remote_video_enabled:
            return
        with self._lock:
            self._want_running = True
            if self.running:
                return
            self._stop_monitor.clear()
            self._spawn_locked()
            self._ensure_monitor_locked()

    def stop(self):
        with self._lock:
            self._want_running = False
            self._stop_monitor.set()
            self._kill_locked()
        monitor = self._monitor
        if monitor is not None and monitor.is_alive() and monitor is not threading.current_thread():
            monitor.join(timeout=1.0)
        self._monitor = None

    def restart(self):
        self.stop()
        self.start()

    def _write_config_locked(self) -> str:
        cfg = gremlin.config.Configuration()
        payload = {
            "port": int(cfg.remote_video_port),
            "fps": int(cfg.remote_video_fps),
            "max_width": int(cfg.remote_video_max_width),
            "quality": int(cfg.remote_video_quality),
            "encoder": str(cfg.remote_video_encoder or "auto"),
            "source": str(cfg.remote_video_source or "screen"),
            "monitor_index": int(cfg.remote_video_monitor_index),
            "window_title": str(cfg.remote_video_window_title or ""),
            "parent_pid": int(os.getpid()),
        }
        path = os.path.join(tempfile.gettempdir(), f"gremlinEx-remote-video-{os.getpid()}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        self._config_path = path
        return path

    def _spawn_locked(self):
        self._kill_locked()
        path = self._write_config_locked()
        cmd, cwd = _supervisor_command(path)
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        log_path = path + ".log"
        try:
            self._log_fh = open(log_path, "w", encoding="utf-8")
            self._log_path = log_path
        except OSError:
            self._log_fh = subprocess.DEVNULL
            self._log_path = None
        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                creationflags=creationflags,
                stdout=self._log_fh,
                stderr=subprocess.STDOUT,
            )
            syslog.info(f"REMOTE VIDEO: spawned worker pid={self._proc.pid} log={log_path}")
            self._respawn_backoff_s = 1.0
        except Exception as err:
            syslog.error(f"REMOTE VIDEO: failed to spawn worker: {err}")
            self._proc = None
            self._close_log_fh()

    def _close_log_fh(self):
        fh = self._log_fh
        self._log_fh = None
        if fh is not None and fh is not subprocess.DEVNULL:
            try:
                fh.close()
            except Exception:
                pass

    def _kill_locked(self):
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            syslog.info("REMOTE VIDEO: worker stopped")
        self._close_log_fh()
        path = self._config_path
        self._config_path = None
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
        # Main process must never keep in-process capture threads.
        _capture_broker.stop()

    def _ensure_monitor_locked(self):
        if self._monitor is not None and self._monitor.is_alive():
            return
        self._stop_monitor.clear()
        self._monitor = threading.Thread(
            target=self._monitor_loop, daemon=True, name="GexRemoteVideo-Supervisor"
        )
        self._monitor.start()

    def _monitor_loop(self):
        while not self._stop_monitor.is_set():
            should_respawn = False
            exit_code = None
            with self._lock:
                want = self._want_running
                proc = self._proc
                alive = proc is not None and proc.poll() is None
                if want and not alive:
                    should_respawn = True
                    exit_code = None if proc is None else proc.poll()
            if should_respawn:
                syslog.warning(f"REMOTE VIDEO: worker exited (code={exit_code}) — respawning")
                self._stop_monitor.wait(self._respawn_backoff_s)
                with self._lock:
                    if self._want_running and not self._stop_monitor.is_set():
                        self._spawn_locked()
                        self._respawn_backoff_s = min(8.0, self._respawn_backoff_s * 1.5)
            self._stop_monitor.wait(1.0)


class _SubscriberWorker(threading.Thread):
    def __init__(self, client_id: int, host: str, port: int, hub: "RemoteVideoHub"):
        super().__init__(daemon=True, name=f"GexRemoteVideo-Recv-{client_id}")
        self.client_id = int(client_id)
        self.host = host
        self.port = int(port)
        self._hub = hub
        self._stop = threading.Event()
        self._h264 = _H264Decoder()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            sock = None
            self._h264.close()
            try:
                sock = socket.create_connection((self.host, self.port), timeout=3.0)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(5.0)
                syslog.info(f"REMOTE VIDEO: subscribed to {self.host}:{self.port} (client {self.client_id})")
                while not self._stop.is_set():
                    frame = _unpack_frame(sock)
                    if frame is None:
                        break
                    _seq, _w, _h, codec, payload = frame
                    if codec == CODEC_H264:
                        image = self._h264.decode(payload)
                    else:
                        image = QtGui.QImage.fromData(payload, "JPG")
                    if image is None or image.isNull():
                        continue
                    self._hub._push_frame(self.client_id, image)
            except OSError as err:
                if not self._stop.is_set():
                    syslog.warning(f"REMOTE VIDEO: cannot connect to {self.host}:{self.port}: {err}")
                time.sleep(1.0)
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                self._h264.close()
            if not self._stop.is_set():
                time.sleep(0.5)


@gremlin.singleton_decorator.SingletonDecorator
class RemoteVideoHub(QtCore.QObject):
    """Master-side feed cache for Overlay remote_view widgets."""

    frame_ready = QtCore.Signal(object)  # client_id (may exceed 32-bit Qt int)

    def __init__(self):
        super().__init__()
        self._pixmaps: dict[int, QtGui.QPixmap] = {}
        self._generation: dict[int, int] = {}
        self._workers: dict[int, _SubscriberWorker] = {}
        self._wanted: set[int] = set()
        self._lock = threading.Lock()
        app = QtWidgets.QApplication.instance()
        if app is not None and QtCore.QThread.currentThread() is not app.thread():
            self.moveToThread(app.thread())

    def retain(self, client_ids: set[int] | None):
        wanted = {int(cid) for cid in (client_ids or set()) if cid}
        with self._lock:
            self._wanted = wanted
            for cid in list(self._workers):
                if cid not in wanted:
                    worker = self._workers.pop(cid)
                    worker.stop()
            for cid in wanted:
                host, port = self._endpoint_for(cid)
                existing = self._workers.get(cid)
                if existing is not None and (existing.host != host or existing.port != port):
                    # Peer re-identified with a new IP/port — reconnect.
                    existing.stop()
                    self._workers.pop(cid, None)
                    existing = None
                if cid not in self._workers:
                    if not host or not port:
                        continue
                    worker = _SubscriberWorker(cid, host, port, self)
                    self._workers[cid] = worker
                    worker.start()

    def feed_status(self, client_id: int) -> str:
        """Short reason when no pixmap is available yet."""
        client_id = int(client_id or 0)
        if not client_id:
            return "Select remote client"
        if self.pixmap(client_id) is not None:
            return ""
        host, port = self._endpoint_for(client_id)
        if not host or not port:
            import gremlin.remote

            data = gremlin.remote.remote_control.getClient(client_id)
            if data is None:
                return "Client not found - Refresh"
            if not getattr(data, "video_enabled", False):
                return "No video on peer\nEnable Video return"
            if not getattr(data, "host_ip", ""):
                return "No peer IP yet\nRefresh clients"
            return "No video port on peer"
        if client_id in self._workers:
            return f"Connecting...\n{host}:{port}"
        return f"Waiting for feed...\n{host}:{port}"

    def generation(self, client_id: int) -> int:
        with self._lock:
            return int(self._generation.get(int(client_id), 0))

    def pixmap(self, client_id: int) -> QtGui.QPixmap | None:
        with self._lock:
            pm = self._pixmaps.get(int(client_id))
        if pm is None or pm.isNull():
            return None
        return pm

    def feed_clients(self) -> list[tuple[int, str, bool]]:
        """Known peers for the inspector: (client_id, label, video_capable)."""
        import gremlin.remote

        rows = []
        try:
            clients = gremlin.remote.remote_control.getClients() or {}
        except Exception:
            clients = {}
        try:
            local_id = int(gremlin.remote.remote_control.getLocalClientId() or 0)
        except (TypeError, ValueError):
            local_id = 0
        for client_id, data in list(clients.items()):
            try:
                cid = int(client_id)
            except (TypeError, ValueError):
                continue
            if not cid or cid == local_id:
                continue
            try:
                label = data.getClientName() if hasattr(data, "getClientName") else str(getattr(data, "client_name", cid))
                video = bool(getattr(data, "video_enabled", False))
            except Exception:
                label = str(cid)
                video = False
            rows.append((cid, str(label or cid), video))
        rows.sort(key=lambda row: row[1].casefold())
        return rows

    def _endpoint_for(self, client_id: int) -> tuple[str, int]:
        import gremlin.remote

        data = gremlin.remote.remote_control.getClient(client_id)
        if data is None or not getattr(data, "video_enabled", False):
            return "", 0
        host = str(getattr(data, "host_ip", "") or "")
        try:
            port = int(getattr(data, "video_port", 0) or 0)
        except (TypeError, ValueError):
            port = 0
        if not host or port <= 0:
            return "", 0
        return host, port

    def _push_frame(self, client_id: int, image: QtGui.QImage):
        """Receive-thread entry: never build QPixmap here (Qt6Widgets crash)."""
        client_id = int(client_id)
        if image is None or image.isNull():
            return
        # Deep-copy so decode buffers can be freed on the worker immediately.
        owned = image.copy()
        if owned.isNull():
            return
        gremlin.util.InvokeUiMethod(self._apply_frame, client_id, owned)

    def _apply_frame(self, client_id: int, image: QtGui.QImage):
        """UI-thread only: QPixmap is not safe to create off the GUI thread."""
        if image is None or image.isNull():
            return
        pm = QtGui.QPixmap.fromImage(image)
        if pm.isNull():
            return
        cid = int(client_id)
        with self._lock:
            self._pixmaps[cid] = pm
            self._generation[cid] = int(self._generation.get(cid, 0)) + 1
        self.frame_ready.emit(cid)


def sync_publisher_with_runtime():
    """Start video publish only while a profile is running on this client."""
    cfg = gremlin.config.Configuration()
    pub = RemoteVideoPublisher()
    if (
        cfg.enable_remote_control
        and cfg.remote_video_enabled
        and gremlin.shared_state.is_running
    ):
        pub.start()
    else:
        pub.stop()
