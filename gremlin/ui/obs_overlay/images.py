# -*- coding: utf-8; -*-
#
# Clipboard / file helpers for overlay Image widgets (Windows Snipping Tool paste).
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

import hashlib
import os
import uuid
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
_CLIPBOARD_MIME_FORMATS = (
    "image/png",
    "PNG",
    "image/bmp",
    "BMP",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "application/x-qt-image",
)


def overlay_images_dir(scene=None) -> str:
    """Folder next to the overlay JSON (or the GEX user profile) for pasted clips."""
    import gremlin.util

    from .model import overlay_path_for_profile

    path = None
    if scene is not None:
        path = getattr(scene, "_path", None)
    path = path or overlay_path_for_profile()
    if path:
        base = os.path.dirname(os.path.abspath(str(path)))
    else:
        try:
            base = gremlin.util.userprofile_path()
        except Exception:
            base = os.getcwd()
        base = os.path.join(base, "overlay")
    dest = os.path.join(base, "overlay_images")
    os.makedirs(dest, exist_ok=True)
    return dest


def qimage_from_bytes(raw) -> QtGui.QImage | None:
    if not raw:
        return None
    data = bytes(raw)
    if not data:
        return None
    image = QtGui.QImage()
    if image.loadFromData(data) and not image.isNull():
        return image
    return None


def qimage_from_mime(mime: QtCore.QMimeData | None) -> QtGui.QImage | None:
    """Read a bitmap from clipboard or drop mime (Snipping Tool uses PNG/DIB)."""
    if mime is None:
        return None
    for fmt in _CLIPBOARD_MIME_FORMATS:
        if mime.hasFormat(fmt):
            image = qimage_from_bytes(mime.data(fmt))
            if image is not None:
                return image
    try:
        formats = list(mime.formats() or [])
    except Exception:
        formats = []
    for fmt in formats:
        name = str(fmt or "")
        if name.casefold().startswith("image/") or name.upper() in ("PNG", "BMP", "JFIF"):
            image = qimage_from_bytes(mime.data(fmt))
            if image is not None:
                return image
    if mime.hasImage():
        data = mime.imageData()
        if isinstance(data, QtGui.QImage) and not data.isNull():
            return data
        if isinstance(data, QtGui.QPixmap) and not data.isNull():
            return data.toImage()
    path = local_image_path_from_mime(mime)
    if path:
        image = QtGui.QImage(path)
        if not image.isNull():
            return image
    return None


def qimage_from_clipboard() -> QtGui.QImage | None:
    app = QtWidgets.QApplication.instance()
    if app is None:
        return None
    clipboard = app.clipboard()
    if clipboard is None:
        return None
    image = qimage_from_mime(clipboard.mimeData())
    if image is not None:
        return image
    grabbed = clipboard.image()
    if grabbed is not None and not grabbed.isNull():
        return grabbed
    pixmap = clipboard.pixmap()
    if pixmap is not None and not pixmap.isNull():
        return pixmap.toImage()
    return None


def clipboard_has_image() -> bool:
    return qimage_from_clipboard() is not None


def local_image_path_from_mime(mime: QtCore.QMimeData | None) -> str:
    if mime is None:
        return ""
    paths: list[str] = []
    if mime.hasUrls():
        for url in mime.urls():
            if url.isLocalFile():
                paths.append(url.toLocalFile())
    if not paths and mime.hasText():
        text = (mime.text() or "").strip().strip('"')
        if text and os.path.isfile(text):
            paths.append(text)
    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        if ext in _IMAGE_EXTS and os.path.isfile(path):
            return path
    return ""


def save_qimage(scene, image: QtGui.QImage, prefix: str = "clip") -> str:
    """Write a PNG next to the overlay and return the path, or ''."""
    if image is None or image.isNull():
        return ""
    dest_dir = overlay_images_dir(scene)
    payload = QtCore.QByteArray()
    buffer = QtCore.QBuffer(payload)
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        return ""
    raw = bytes(payload)
    if not raw:
        return ""
    stem = hashlib.sha1(raw).hexdigest()[:12]
    dest = os.path.join(dest_dir, f"{prefix}_{stem}.png")
    if not os.path.isfile(dest):
        try:
            with open(dest, "wb") as handle:
                handle.write(raw)
        except OSError:
            dest = os.path.join(dest_dir, f"{prefix}_{uuid.uuid4().hex[:12]}.png")
            if not image.save(dest, "PNG"):
                return ""
    return dest.replace("\\", "/")


def import_image_file(scene, source_path: str) -> str:
    source_path = os.path.abspath(os.path.normpath(source_path or ""))
    if not source_path or not os.path.isfile(source_path):
        return ""
    dest_dir = os.path.abspath(overlay_images_dir(scene))
    try:
        common = os.path.commonpath([dest_dir, source_path])
    except ValueError:
        common = ""
    if common == dest_dir:
        return source_path.replace("\\", "/")
    ext = os.path.splitext(source_path)[1].lower()
    if ext not in _IMAGE_EXTS:
        ext = ".png"
    try:
        digest = hashlib.sha1()
        with open(source_path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 256)
                if not chunk:
                    break
                digest.update(chunk)
        stem = digest.hexdigest()[:12]
    except OSError:
        stem = uuid.uuid4().hex[:12]
    dest = os.path.join(dest_dir, f"import_{stem}{ext}")
    if not os.path.isfile(dest):
        try:
            import shutil

            shutil.copy2(source_path, dest)
        except OSError:
            image = QtGui.QImage(source_path)
            if image.isNull() or not image.save(dest, "PNG"):
                return ""
            dest = os.path.splitext(dest)[0] + ".png"
    return dest.replace("\\", "/")


def fit_item_to_image_size(item: dict[str, Any], image_w: int, image_h: int, canvas: dict[str, Any] | None):
    canvas = canvas or {}
    canvas_w = max(32, int(canvas.get("width") or 1280))
    canvas_h = max(32, int(canvas.get("height") or 720))
    scale = min(1.0, canvas_w / max(1, image_w), canvas_h / max(1, image_h))
    width = max(16, int(round(image_w * scale)))
    height = max(16, int(round(image_h * scale)))
    cx = int(item.get("x") or 0) + int(item.get("w") or 0) / 2.0
    cy = int(item.get("y") or 0) + int(item.get("h") or 0) / 2.0
    item["w"] = width
    item["h"] = height
    item["x"] = max(0, min(canvas_w - width, int(round(cx - width / 2.0))))
    item["y"] = max(0, min(canvas_h - height, int(round(cy - height / 2.0))))


def apply_image_to_item(scene, item: dict[str, Any], path: str, image: QtGui.QImage | None = None) -> bool:
    if not item or not path:
        return False
    style = item.setdefault("style", {})
    style["image_path"] = path
    if image is None or image.isNull():
        image = QtGui.QImage(path)
    if image is not None and not image.isNull():
        fit_item_to_image_size(item, image.width(), image.height(), scene.canvas)
    scene._dirty = True
    scene._emit()
    return True
