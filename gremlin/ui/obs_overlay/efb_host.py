"""Local Star Citizen Electronic Flight Bag viewer (no OCR, no web lookup).

Plates are JPG/JPEG under a user-chosen install folder set in the inspector.
"""

from __future__ import annotations

import logging
import os
import webbrowser
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

syslog = logging.getLogger("system")

_DESIGNER_INSET = 8
_APP_PAGE = "https://www.deltaconsultingsc.com/apppage"
_DEFAULT_DISCORD = "https://discord.com/invite/p6PVqSk"
_JPG_EXT = {".jpg", ".jpeg"}

SYSTEMS = ("Stanton", "Pyro", "Nyx", "Castra", "Terra")

_SFD_BY_SYSTEM = {
    "Stanton": "2-Stanton SFD",
    "Pyro": "8-Pyro SFD",
    "Nyx": "10-Nyx SFD",
}

_DEFAULT_SECTION_BUTTONS = [
    {"id": "sfd", "label": "SFD", "path": ""},
    {"id": "nfz", "label": "NFZ", "path": "3-Stanton No Fly Zone Supplement"},
    {"id": "tac", "label": "TAC", "path": "4-Stanton Terminal Area Chart Supplement"},
    {"id": "iap", "label": "IAP", "path": "5-Stanton Instrument Approach Procedure Supplement"},
    {"id": "gen", "label": "GEN", "path": "7-General Structures Supplement"},
]

_DRAW_COLORS = ("#111111", "#888888", "#c62828", "#ef6c00", "#f9a825", "#2e7d32", "#1565c0", "#ffffff")

_BTN_QSS = """
QPushButton {
  background: #2a3038; color: #c8d0da; border: 1px solid #3a414c;
  border-radius: 4px; padding: 4px 8px; min-height: 22px;
}
QPushButton:checked {
  background: #3d6ea5; color: #ffffff; border: 1px solid #5a9ad4;
}
QPushButton:disabled { color: #5a6270; }
"""


def default_section_buttons() -> list[dict[str, str]]:
    return [dict(row) for row in _DEFAULT_SECTION_BUTTONS]


def open_download_page():
    webbrowser.open(_APP_PAGE)


def open_discord(url: str):
    target = str(url or "").strip() or _DEFAULT_DISCORD
    webbrowser.open(target)


def _is_jpg(path: str) -> bool:
    return os.path.splitext(path)[1].casefold() in _JPG_EXT


def unwrap_section_dir(path: str) -> str:
    """Delta packs nest ``Name/Name/plates`` — prefer the inner folder when present."""
    if not path or not os.path.isdir(path):
        return path
    name = os.path.basename(path.rstrip("\\/"))
    inner = os.path.join(path, name)
    if os.path.isdir(inner):
        return inner
    return path


def resolve_section_path(root: str, system: str, button: dict[str, Any]) -> str:
    root = str(root or "").strip()
    if not root:
        return ""
    bid = str(button.get("id") or "").casefold()
    rel = str(button.get("path") or "").strip()
    if bid == "sfd" and not rel:
        rel = _SFD_BY_SYSTEM.get(system, "")
    if not rel:
        return unwrap_section_dir(root)
    return unwrap_section_dir(os.path.join(root, rel))


def system_search_roots(root: str, system: str) -> list[str]:
    """Folders searched for the active system filter."""
    root = str(root or "").strip()
    if not root or not os.path.isdir(root):
        return []
    system = str(system or "Stanton")
    if system == "Stanton":
        names = [
            "2-Stanton SFD",
            "3-Stanton No Fly Zone Supplement",
            "4-Stanton Terminal Area Chart Supplement",
            "5-Stanton Instrument Approach Procedure Supplement",
            "6-Settlements and CDF Chart Supplement",
            "7-General Structures Supplement",
            "1-Stanton System Facility Directory with Supplements",
        ]
    elif system == "Pyro":
        names = ["8-Pyro SFD"]
    elif system == "Nyx":
        names = ["10-Nyx SFD"]
    else:
        # Castra / Terra: match folder names that contain the system token.
        token = system.casefold()
        found = []
        try:
            for name in os.listdir(root):
                if token in name.casefold() and os.path.isdir(os.path.join(root, name)):
                    found.append(name)
        except OSError:
            pass
        names = found
    out = []
    for name in names:
        path = unwrap_section_dir(os.path.join(root, name))
        if os.path.isdir(path):
            out.append(path)
    return out


def list_entries(folder: str) -> tuple[list[str], list[str]]:
    """Return (subdirs, jpg files) sorted by name."""
    dirs: list[str] = []
    files: list[str] = []
    if not folder or not os.path.isdir(folder):
        return dirs, files
    try:
        names = os.listdir(folder)
    except OSError:
        return dirs, files
    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(folder, name)
        if os.path.isdir(full):
            dirs.append(full)
        elif os.path.isfile(full) and _is_jpg(full):
            files.append(full)
    dirs.sort(key=lambda p: os.path.basename(p).casefold())
    files.sort(key=lambda p: os.path.basename(p).casefold())
    return dirs, files


def favorite_key(root: str, path: str) -> str:
    """Store favorites relative to the install root when possible."""
    path = os.path.normpath(str(path or ""))
    root = os.path.normpath(str(root or ""))
    if root and path.lower().startswith(root.lower() + os.sep):
        return path[len(root) :].lstrip("\\/")
    return path


def resolve_favorite(root: str, entry: str) -> str:
    entry = str(entry or "").strip()
    if not entry:
        return ""
    if os.path.isabs(entry) and os.path.isfile(entry):
        return entry
    root = str(root or "").strip()
    if root:
        joined = os.path.normpath(os.path.join(root, entry))
        if os.path.isfile(joined):
            return joined
    return entry if os.path.isfile(entry) else ""


def find_stanton_cover(root: str) -> str:
    """Path to the Stanton SFD cover plate, or empty if missing."""
    folder = resolve_section_path(root, "Stanton", {"id": "sfd", "label": "SFD", "path": ""})
    if not folder or not os.path.isdir(folder):
        return ""
    preferred = (
        "1-Stanton_SFD Cover.jpg",
        "1-Stanton SFD Cover.jpg",
        "1-Stanton_SFD cover.jpg",
    )
    for name in preferred:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    try:
        for name in sorted(os.listdir(folder), key=lambda n: n.casefold()):
            if "cover" in name.casefold() and _is_jpg(name) and "stanton" in name.casefold():
                return os.path.join(folder, name)
    except OSError:
        pass
    return ""


def search_jpgs(roots: list[str], query: str, limit: int = 200) -> list[str]:
    q = str(query or "").strip().casefold()
    if not q:
        return []
    hits: list[str] = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                if not _is_jpg(name):
                    continue
                if q not in name.casefold():
                    continue
                hits.append(os.path.join(dirpath, name))
                if len(hits) >= limit:
                    return hits
    hits.sort(key=lambda p: os.path.basename(p).casefold())
    return hits


# Reuse browser runtime window helpers without importing WebEngine.
def _runtime_window_flags(owner) -> QtCore.Qt.WindowType:
    from .browser_host import _runtime_window_flags as _flags

    return _flags(owner)


def _show_runtime_hwnd(hwnd: int, *, topmost: bool):
    from .browser_host import _show_runtime_hwnd as _show

    _show(hwnd, topmost=topmost)


def _overlay_is_shown(view) -> bool:
    from .browser_host import _overlay_is_shown as _shown

    return _shown(view)


def _screen_top_left(view, local_rect: QtCore.QRect) -> QtCore.QPoint:
    from .browser_host import _screen_top_left as _tl

    return _tl(view, local_rect)


class _PlateView(QtWidgets.QGraphicsView):
    """Zoom / pan plate with freehand, rectangle, or circle ink."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self.setBackgroundBrush(QtGui.QColor("#121418"))
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setRenderHints(
            QtGui.QPainter.Antialiasing
            | QtGui.QPainter.SmoothPixmapTransform
            | QtGui.QPainter.TextAntialiasing
        )
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self._pix_item: QtWidgets.QGraphicsPixmapItem | None = None
        self._tool = ""  # "", "draw", "rect", "circle"
        self._draw_color = QtGui.QColor("#c62828")
        self._stroke_width = 3.0
        self._current_item: QtWidgets.QGraphicsItem | None = None
        self._stroke_path: QtGui.QPainterPath | None = None
        self._origin = QtCore.QPointF()
        self._strokes: list[QtWidgets.QGraphicsItem] = []
        self._fit_pending = False

    def clear_plate(self):
        self._scene.clear()
        self._pix_item = None
        self._current_item = None
        self._stroke_path = None
        self._strokes.clear()
        self._fit_pending = False
        self.resetTransform()

    def show_plate(self, path: str) -> bool:
        self.clear_plate()
        image = QtGui.QImage(path)
        if image.isNull():
            return False
        pix = QtGui.QPixmap.fromImage(image)
        self._pix_item = self._scene.addPixmap(pix)
        self._pix_item.setZValue(0)
        self._scene.setSceneRect(QtCore.QRectF(pix.rect()))
        # fitInView before the stacked page has a real size shrinks the plate to a speck.
        self._fit_pending = True
        self.schedule_fit()
        return True

    def schedule_fit(self):
        self._fit_pending = True
        QtCore.QTimer.singleShot(0, self._fit_when_ready)

    def _fit_when_ready(self):
        if not self._fit_pending or self._pix_item is None:
            return
        if self.width() < 8 or self.height() < 8:
            QtCore.QTimer.singleShot(50, self._fit_when_ready)
            return
        self.resetTransform()
        self.fitInView(self._pix_item, QtCore.Qt.KeepAspectRatio)
        self._fit_pending = False

    def showEvent(self, event: QtGui.QShowEvent):
        super().showEvent(event)
        if self._fit_pending:
            self.schedule_fit()

    def resizeEvent(self, event: QtGui.QResizeEvent):
        super().resizeEvent(event)
        if self._fit_pending:
            self._fit_when_ready()

    def set_tool(self, tool: str):
        self._tool = str(tool or "")
        self.setDragMode(
            QtWidgets.QGraphicsView.NoDrag if self._tool else QtWidgets.QGraphicsView.ScrollHandDrag
        )

    def set_draw_color(self, color: str):
        self._draw_color = QtGui.QColor(color)
        if not self._draw_color.isValid():
            self._draw_color = QtGui.QColor("#c62828")

    def _pen(self) -> QtGui.QPen:
        pen = QtGui.QPen(self._draw_color, self._stroke_width)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        return pen

    def zoom_in(self):
        self.scale(1.25, 1.25)

    def zoom_out(self):
        self.scale(0.8, 0.8)

    def zoom_fit(self):
        if self._pix_item is not None:
            self.fitInView(self._pix_item, QtCore.Qt.KeepAspectRatio)

    def clear_strokes(self):
        for item in self._strokes:
            self._scene.removeItem(item)
        self._strokes.clear()
        self._current_item = None
        self._stroke_path = None

    def wheelEvent(self, event: QtGui.QWheelEvent):
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if self._tool and event.button() == QtCore.Qt.LeftButton and self._pix_item is not None:
            pos = self.mapToScene(event.position().toPoint())
            self._origin = QtCore.QPointF(pos.x(), pos.y())
            self._stroke_path = None
            if self._tool == "draw":
                # Keep our own path object. Re-wrapping path() with QPainterPath(...)
                # in PySide can drop the start point and line from scene (0,0).
                self._stroke_path = QtGui.QPainterPath()
                self._stroke_path.moveTo(self._origin)
                item = self._scene.addPath(self._stroke_path, self._pen())
            elif self._tool == "rect":
                item = self._scene.addRect(QtCore.QRectF(self._origin, self._origin), self._pen())
            else:
                item = self._scene.addEllipse(QtCore.QRectF(self._origin, self._origin), self._pen())
            item.setZValue(10)
            self._current_item = item
            self._strokes.append(item)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if self._tool and self._current_item is not None:
            pos = self.mapToScene(event.position().toPoint())
            if (
                self._tool == "draw"
                and self._stroke_path is not None
                and isinstance(self._current_item, QtWidgets.QGraphicsPathItem)
            ):
                self._stroke_path.lineTo(QtCore.QPointF(pos.x(), pos.y()))
                self._current_item.setPath(self._stroke_path)
            elif self._tool == "rect" and isinstance(self._current_item, QtWidgets.QGraphicsRectItem):
                self._current_item.setRect(QtCore.QRectF(self._origin, pos).normalized())
            elif self._tool == "circle" and isinstance(self._current_item, QtWidgets.QGraphicsEllipseItem):
                side = max(abs(pos.x() - self._origin.x()), abs(pos.y() - self._origin.y()))
                if side <= 0:
                    side = 0.1
                dx = side if pos.x() >= self._origin.x() else -side
                dy = side if pos.y() >= self._origin.y() else -side
                self._current_item.setRect(
                    QtCore.QRectF(self._origin, self._origin + QtCore.QPointF(dx, dy)).normalized()
                )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if self._tool and event.button() == QtCore.Qt.LeftButton:
            self._current_item = None
            self._stroke_path = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class EfbSurface(QtWidgets.QWidget):
    """ForeFlight-style EFB chrome around a local plate browser/viewer."""

    def __init__(self, view, widget_id: str, *, floating: bool = False, owner: QtWidgets.QWidget | None = None):
        super().__init__(None)
        self._view = view
        self.widget_id = str(widget_id)
        self._floating = False
        self._root = ""
        self._system = "Stanton"
        self._section_id = "sfd"
        self._section_buttons = default_section_buttons()
        self._browse_dir = ""
        self._plate_path = ""
        self._nav_stack: list[str] = []
        self._search_hits: list[str] = []
        self._favorites: list[str] = []
        self._browsing_favorites = False
        self._discord_url = ""
        self._ink_tool = ""
        self._style_sig = None
        self._home_shown = False

        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setStyleSheet(
            _BTN_QSS
            + " QWidget { background:#1a1e24; color:#d0d6de; }"
            + " QLineEdit { background:#121418; color:#e8eef6; border:1px solid #3a414c;"
            + " border-radius:4px; padding:4px 8px; selection-background-color:#3d6ea5; }"
        )

        self._search = QtWidgets.QLineEdit(self)
        self._search.setPlaceholderText("Search")
        self._search.setClearButtonEnabled(True)
        self._search.setFocusPolicy(QtCore.Qt.StrongFocus)
        self._search.returnPressed.connect(self._run_search)
        self._search.textChanged.connect(self._on_search_text)
        self._search.installEventFilter(self)

        self._star = QtWidgets.QPushButton("☆", self)
        self._star.setCheckable(True)
        self._star.setFixedWidth(36)
        self._star.setToolTip("Save current plate as favorite")
        self._star.setEnabled(False)
        self._star.clicked.connect(self._toggle_favorite)

        self._back = QtWidgets.QPushButton("Back", self)
        self._back.clicked.connect(self._go_back)

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(4, 4, 4, 2)
        top.setSpacing(4)
        top.addWidget(self._search, 1)
        top.addWidget(self._star)
        top.addWidget(self._back)

        self._list = QtWidgets.QListWidget(self)
        self._list.setStyleSheet("QListWidget { background:#121418; border:none; }")
        self._list.itemActivated.connect(self._on_list_activated)
        self._list.itemClicked.connect(self._on_list_activated)

        self._plate = _PlateView(self)
        self._message = QtWidgets.QLabel("Set install folder in the inspector", self)
        self._message.setAlignment(QtCore.Qt.AlignCenter)
        self._message.setWordWrap(True)
        self._message.setStyleSheet("background:#121418; color:#9aa4b2;")

        self._stack = QtWidgets.QStackedWidget(self)
        self._stack.addWidget(self._message)
        self._stack.addWidget(self._list)
        self._stack.addWidget(self._plate)

        self._system_bar = QtWidgets.QHBoxLayout()
        self._system_bar.setContentsMargins(4, 2, 4, 4)
        self._system_bar.setSpacing(4)
        self._fav_btn = QtWidgets.QPushButton("Favorites", self)
        self._fav_btn.setCheckable(True)
        self._fav_btn.setToolTip("Browse saved favorite plates")
        self._fav_btn.clicked.connect(self._open_favorites)
        self._system_bar.addWidget(self._fav_btn)
        self._system_btns: dict[str, QtWidgets.QPushButton] = {}
        for name in SYSTEMS:
            btn = QtWidgets.QPushButton(name, self)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, n=name: self._select_system(n))
            self._system_btns[name] = btn
            self._system_bar.addWidget(btn)
        self._system_bar.addStretch(1)

        self._rail = QtWidgets.QVBoxLayout()
        self._rail.setContentsMargins(2, 4, 4, 4)
        self._rail.setSpacing(4)
        self._section_btns: dict[str, QtWidgets.QPushButton] = {}
        self._section_rail = QtWidgets.QVBoxLayout()
        self._section_rail.setSpacing(4)
        self._rail.addLayout(self._section_rail)

        zoom_in = QtWidgets.QPushButton("Zoom +", self)
        zoom_out = QtWidgets.QPushButton("Zoom −", self)
        zoom_fit = QtWidgets.QPushButton("Fit", self)
        zoom_in.clicked.connect(self._plate.zoom_in)
        zoom_out.clicked.connect(self._plate.zoom_out)
        zoom_fit.clicked.connect(self._plate.zoom_fit)
        self._rail.addWidget(zoom_in)
        self._rail.addWidget(zoom_out)
        self._rail.addWidget(zoom_fit)

        divider = QtWidgets.QFrame(self)
        divider.setFrameShape(QtWidgets.QFrame.HLine)
        divider.setFrameShadow(QtWidgets.QFrame.Sunken)
        divider.setStyleSheet("color:#3a414c; margin: 4px 0;")
        self._rail.addWidget(divider)

        self._tool_btns: dict[str, QtWidgets.QPushButton] = {}
        for tool, label in (("draw", "Draw"), ("rect", "Rect"), ("circle", "Circle")):
            btn = QtWidgets.QPushButton(label, self)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, t=tool: self._select_ink_tool(t, checked))
            self._tool_btns[tool] = btn
            self._rail.addWidget(btn)

        clear_draw = QtWidgets.QPushButton("Clear ink", self)
        clear_draw.clicked.connect(self._plate.clear_strokes)
        self._rail.addWidget(clear_draw)

        colors = QtWidgets.QHBoxLayout()
        colors.setSpacing(2)
        for hex_color in _DRAW_COLORS:
            swatch = QtWidgets.QToolButton(self)
            swatch.setFixedSize(18, 18)
            swatch.setStyleSheet(f"background:{hex_color}; border:1px solid #555;")
            swatch.clicked.connect(lambda _=False, c=hex_color: self._set_draw_color(c))
            colors.addWidget(swatch)
        self._rail.addLayout(colors)
        self._rail.addStretch(1)

        center_row = QtWidgets.QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.setSpacing(0)
        center_row.addWidget(self._stack, 1)
        rail_wrap = QtWidgets.QWidget(self)
        rail_wrap.setLayout(self._rail)
        rail_wrap.setFixedWidth(96)
        center_row.addWidget(rail_wrap)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addLayout(center_row, 1)
        layout.addLayout(self._system_bar)

        self._rebuild_section_buttons()
        self._adopt_window(bool(floating and owner is not None), owner)

    def shutdown(self):
        return

    def _efb_runtime_flags(self, owner) -> QtCore.Qt.WindowType:
        """Like the browser surface, but keyboard focus is allowed for search."""
        flags = QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint
        if owner is not None and (owner.windowFlags() & QtCore.Qt.WindowStaysOnTopHint):
            flags |= QtCore.Qt.WindowStaysOnTopHint
        return flags

    def _adopt_window(self, floating: bool, owner: QtWidgets.QWidget | None):
        if floating and owner is not None:
            flags = self._efb_runtime_flags(owner)
            current = self.windowFlags()
            same_type = (int(current) & 0xFF) == (int(QtCore.Qt.Window) & 0xFF)
            if (
                self._floating
                and self.isWindow()
                and self.parentWidget() is owner
                and same_type
                and bool(current & QtCore.Qt.WindowStaysOnTopHint) == bool(flags & QtCore.Qt.WindowStaysOnTopHint)
                and bool(current & QtCore.Qt.FramelessWindowHint)
                and not bool(current & QtCore.Qt.WindowDoesNotAcceptFocus)
            ):
                return
            self.hide()
            self.setParent(owner, flags)
            self._floating = True
            self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
            self.setAttribute(QtCore.Qt.WA_NativeWindow, True)
            self.winId()
            return
        if not self._floating and not self.isWindow() and self.parentWidget() is self._view:
            return
        self.hide()
        self.setParent(self._view)
        self.setWindowFlags(QtCore.Qt.Widget)
        self._floating = False

    def _present_runtime(self):
        if not self._floating:
            return
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        if not self.isVisible():
            self.show()
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId() or 0)
        except Exception:
            hwnd = 0
        if not hwnd:
            return
        try:
            # Tool-window + topmost without WS_EX_NOACTIVATE so the search field can type.
            import ctypes

            user32 = ctypes.windll.user32
            gwl_exstyle = -20
            ws_ex_topmost = 0x00000008
            ws_ex_toolwindow = 0x00000080
            extras = ws_ex_toolwindow
            topmost = bool(self.windowFlags() & QtCore.Qt.WindowStaysOnTopHint)
            if topmost:
                extras |= ws_ex_topmost
            if ctypes.sizeof(ctypes.c_void_p) == 8:
                user32.GetWindowLongPtrW.restype = ctypes.c_longlong
                user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
                user32.SetWindowLongPtrW.restype = ctypes.c_longlong
                user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
                style = int(user32.GetWindowLongPtrW(hwnd, gwl_exstyle))
                style = (style | extras) & ~0x08000000  # clear WS_EX_NOACTIVATE
                user32.SetWindowLongPtrW(hwnd, gwl_exstyle, style)
            else:
                style = int(user32.GetWindowLongW(hwnd, gwl_exstyle))
                style = (style | extras) & ~0x08000000
                user32.SetWindowLongW(hwnd, gwl_exstyle, style)
            user32.SetWindowPos(
                hwnd,
                ctypes.c_void_p(-1 if topmost else 0),
                0,
                0,
                0,
                0,
                0x0001 | 0x0002 | 0x0010 | 0x0020 | 0x0040,
            )
        except Exception as err:
            if not getattr(self, "_present_warned", False):
                self._present_warned = True
                syslog.warning(f"OBS OVERLAY: runtime EFB show failed: {err}")

    def eventFilter(self, watched, event):
        if watched is self._search:
            et = event.type()
            if et in (QtCore.QEvent.Type.MouseButtonPress, QtCore.QEvent.Type.FocusIn):
                self._focus_search()
        return super().eventFilter(watched, event)

    def _focus_search(self):
        try:
            if self._floating:
                self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, False)
                self.activateWindow()
            self._search.setFocus(QtCore.Qt.MouseFocusReason)
        except Exception:
            pass

    def _item(self):
        try:
            return self._view.scene.widget_by_id(self.widget_id, getattr(self._view, "_page_id", None))
        except Exception:
            return None

    def _style_signature(self, style: dict) -> tuple:
        buttons = style.get("section_buttons") or default_section_buttons()
        favorites = style.get("favorites") or ()
        return (
            str(style.get("efb_root") or ""),
            str(style.get("system") or "Stanton"),
            str(style.get("section_id") or "sfd"),
            str(style.get("discord_url") or ""),
            tuple(str(p) for p in favorites),
            tuple(
                (str(b.get("id") or ""), str(b.get("label") or ""), str(b.get("path") or ""))
                for b in buttons
                if isinstance(b, dict)
            ),
        )

    def apply_item(self, item: dict):
        style = item.get("style") or {}
        sig = self._style_signature(style)
        root = str(style.get("efb_root") or "").strip()
        system = str(style.get("system") or "Stanton")
        if system not in SYSTEMS:
            system = "Stanton"
        section_id = str(style.get("section_id") or "sfd")
        buttons = style.get("section_buttons") or default_section_buttons()
        if not isinstance(buttons, list) or not buttons:
            buttons = default_section_buttons()
        favs = style.get("favorites") or []
        self._favorites = [str(p) for p in favs if str(p or "").strip()]
        self._discord_url = str(style.get("discord_url") or "")

        buttons_changed = buttons != self._section_buttons
        self._section_buttons = [dict(b) for b in buttons if isinstance(b, dict)]
        if buttons_changed:
            self._rebuild_section_buttons()
        self._refresh_star()

        for name, btn in self._system_btns.items():
            btn.setChecked(name == system)

        root_changed = root != self._root
        system_changed = system != self._system
        section_changed = section_id != self._section_id
        self._root = root
        self._system = system
        self._section_id = section_id

        for bid, btn in self._section_btns.items():
            btn.setChecked(bid == section_id)

        if not root or not os.path.isdir(root):
            self._plate_path = ""
            self._browse_dir = ""
            self._nav_stack.clear()
            self._home_shown = False
            self._message.setText("Set install folder in the inspector")
            self._stack.setCurrentWidget(self._message)
            self._style_sig = sig
            return

        # First open (or new install folder): Stanton SFD cover as the landing plate.
        if root_changed or not self._home_shown:
            self._open_stanton_cover()
            self._home_shown = True
        elif (system_changed or section_changed or self._style_sig != sig) and (
            not self._plate_path or system_changed or section_changed
        ):
            self._open_section(section_id, push=False)
        self._style_sig = sig

    def _open_stanton_cover(self):
        """Landing view: Stanton + SFD with the pack cover plate."""
        self._system = "Stanton"
        self._section_id = "sfd"
        for name, btn in self._system_btns.items():
            btn.setChecked(name == "Stanton")
        for bid, btn in self._section_btns.items():
            btn.setChecked(bid == "sfd")
        # Keep style in sync so the next sync tick does not jump to another system.
        item = self._item()
        if item is not None:
            style = item.setdefault("style", {})
            style["system"] = "Stanton"
            style["section_id"] = "sfd"
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._search_hits = []
        folder = resolve_section_path(self._root, "Stanton", self._button_by_id("sfd"))
        self._nav_stack = [folder] if folder and os.path.isdir(folder) else []
        self._browse_dir = folder if folder and os.path.isdir(folder) else ""
        self._browsing_favorites = False
        self._fav_btn.setChecked(False)
        cover = find_stanton_cover(self._root)
        if cover:
            self._show_plate(cover)
            return
        if self._browse_dir:
            self._show_folder(self._browse_dir)
            return
        self._message.setText("Stanton SFD cover not found")
        self._stack.setCurrentWidget(self._message)
        self._refresh_star()

    def _rebuild_section_buttons(self):
        while self._section_rail.count():
            item = self._section_rail.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._section_btns.clear()
        for row in self._section_buttons:
            bid = str(row.get("id") or row.get("label") or "").strip()
            label = str(row.get("label") or bid).strip() or bid
            if not bid:
                continue
            btn = QtWidgets.QPushButton(label, self)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, i=bid: self._select_section(i))
            self._section_btns[bid] = btn
            self._section_rail.addWidget(btn)

    def _select_system(self, name: str):
        self._browsing_favorites = False
        self._fav_btn.setChecked(False)
        self._system = name
        for n, btn in self._system_btns.items():
            btn.setChecked(n == name)
        self._persist(system=name)
        self._open_section(self._section_id, push=False)

    def _select_section(self, section_id: str):
        self._browsing_favorites = False
        self._fav_btn.setChecked(False)
        self._section_id = section_id
        for bid, btn in self._section_btns.items():
            btn.setChecked(bid == section_id)
        self._persist(section_id=section_id)
        self._open_section(section_id, push=False)

    def _favorite_paths(self) -> list[str]:
        out = []
        seen = set()
        for entry in self._favorites:
            path = resolve_favorite(self._root, entry)
            if not path or path in seen:
                continue
            seen.add(path)
            out.append(path)
        return out

    def _is_favorite(self, path: str) -> bool:
        if not path:
            return False
        key = favorite_key(self._root, path)
        norm = os.path.normcase(os.path.normpath(path))
        for entry in self._favorites:
            if favorite_key(self._root, entry) == key:
                return True
            resolved = resolve_favorite(self._root, entry)
            if resolved and os.path.normcase(os.path.normpath(resolved)) == norm:
                return True
        return False

    def _refresh_star(self):
        has_plate = bool(self._plate_path) and os.path.isfile(self._plate_path)
        self._star.setEnabled(has_plate)
        fav = has_plate and self._is_favorite(self._plate_path)
        self._star.blockSignals(True)
        self._star.setChecked(fav)
        self._star.setText("★" if fav else "☆")
        self._star.blockSignals(False)

    def _toggle_favorite(self):
        if not self._plate_path or not os.path.isfile(self._plate_path):
            self._refresh_star()
            return
        key = favorite_key(self._root, self._plate_path)
        if self._is_favorite(self._plate_path):
            self._favorites = [
                e
                for e in self._favorites
                if favorite_key(self._root, e) != key
                and os.path.normcase(os.path.normpath(resolve_favorite(self._root, e) or e))
                != os.path.normcase(os.path.normpath(self._plate_path))
            ]
        else:
            self._favorites = list(self._favorites) + [key]
        self._persist(favorites=list(self._favorites))
        self._refresh_star()
        if self._browsing_favorites and not self._plate_path:
            self._open_favorites()

    def _open_favorites(self):
        self._browsing_favorites = True
        self._fav_btn.setChecked(True)
        for btn in self._system_btns.values():
            btn.setChecked(False)
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._search_hits = []
        self._plate_path = ""
        self._plate.clear_plate()
        paths = self._favorite_paths()
        self._list.clear()
        if not paths:
            self._message.setText("No favorites yet — open a plate and tap ★")
            self._stack.setCurrentWidget(self._message)
            self._refresh_star()
            self._back.setEnabled(False)
            return
        for path in paths:
            rel = favorite_key(self._root, path)
            item = QtWidgets.QListWidgetItem(rel)
            item.setData(QtCore.Qt.UserRole, ("file", path))
            self._list.addItem(item)
        self._stack.setCurrentWidget(self._list)
        self._refresh_star()
        self._back.setEnabled(False)

    def _button_by_id(self, section_id: str) -> dict[str, Any]:
        for row in self._section_buttons:
            if str(row.get("id") or "") == section_id:
                return row
        return {"id": section_id, "label": section_id, "path": ""}

    def _open_section(self, section_id: str, *, push: bool):
        self._browsing_favorites = False
        self._fav_btn.setChecked(False)
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._search_hits = []
        self._plate_path = ""
        self._plate.clear_plate()
        folder = resolve_section_path(self._root, self._system, self._button_by_id(section_id))
        if not folder or not os.path.isdir(folder):
            self._browse_dir = ""
            self._nav_stack.clear()
            self._message.setText(f"No folder for {section_id} ({self._system})")
            self._stack.setCurrentWidget(self._message)
            return
        self._nav_stack = [folder] if not push else self._nav_stack
        if not self._nav_stack:
            self._nav_stack = [folder]
        else:
            self._nav_stack = [folder]
        self._show_folder(folder)

    def _show_folder(self, folder: str):
        self._browse_dir = folder
        self._plate_path = ""
        self._plate.clear_plate()
        self._list.clear()
        dirs, files = list_entries(folder)
        if not dirs and not files:
            self._message.setText("Empty folder")
            self._stack.setCurrentWidget(self._message)
            return
        for path in dirs:
            item = QtWidgets.QListWidgetItem("[dir] " + os.path.basename(path))
            item.setData(QtCore.Qt.UserRole, ("dir", path))
            self._list.addItem(item)
        for path in files:
            item = QtWidgets.QListWidgetItem(os.path.basename(path))
            item.setData(QtCore.Qt.UserRole, ("file", path))
            self._list.addItem(item)
        self._stack.setCurrentWidget(self._list)
        self._back.setEnabled(len(self._nav_stack) > 1 or bool(self._plate_path))

    def _show_plate(self, path: str):
        # Switch the stack page first so the graphics view gets a real size
        # before fitInView runs (otherwise the plate appears as a tiny icon).
        self._stack.setCurrentWidget(self._plate)
        self._plate_path = path
        self._back.setEnabled(True)
        if not self._plate.show_plate(path):
            self._plate_path = ""
            self._message.setText("Could not load image")
            self._stack.setCurrentWidget(self._message)
            self._refresh_star()
            return
        self._plate.schedule_fit()
        self._refresh_star()

    def _on_list_activated(self, item: QtWidgets.QListWidgetItem):
        data = item.data(QtCore.Qt.UserRole)
        if not data:
            return
        kind, path = data
        if kind == "dir":
            self._browsing_favorites = False
            self._fav_btn.setChecked(False)
            self._nav_stack.append(path)
            self._show_folder(path)
            return
        if kind == "file":
            self._show_plate(path)

    def _go_back(self):
        if self._plate_path:
            self._plate_path = ""
            self._plate.clear_plate()
            self._refresh_star()
            if self._browsing_favorites:
                self._open_favorites()
            elif self._search_hits:
                self._show_search_results(self._search_hits)
            elif self._browse_dir:
                self._show_folder(self._browse_dir)
            else:
                self._open_section(self._section_id, push=False)
            return
        if self._browsing_favorites:
            self._browsing_favorites = False
            self._fav_btn.setChecked(False)
            self._open_section(self._section_id, push=False)
            return
        if len(self._nav_stack) > 1:
            self._nav_stack.pop()
            self._show_folder(self._nav_stack[-1])
            return
        self._back.setEnabled(False)

    def _on_search_text(self, text: str):
        if not str(text or "").strip():
            self._search_hits = []
            if self._browse_dir and not self._plate_path:
                self._show_folder(self._browse_dir)

    def _run_search(self):
        query = self._search.text().strip()
        if not query:
            self._search_hits = []
            if self._browse_dir:
                self._show_folder(self._browse_dir)
            return
        roots = system_search_roots(self._root, self._system)
        if not roots and self._root:
            roots = [self._root]
        hits = search_jpgs(roots, query)
        self._search_hits = hits
        self._plate_path = ""
        self._show_search_results(hits)

    def _show_search_results(self, hits: list[str]):
        self._list.clear()
        if not hits:
            self._message.setText("No matches")
            self._stack.setCurrentWidget(self._message)
            return
        for path in hits:
            rel = path
            if self._root and path.startswith(self._root):
                rel = path[len(self._root) :].lstrip("\\/")
            item = QtWidgets.QListWidgetItem(rel)
            item.setData(QtCore.Qt.UserRole, ("file", path))
            self._list.addItem(item)
        self._stack.setCurrentWidget(self._list)
        self._back.setEnabled(True)

    def _select_ink_tool(self, tool: str, checked: bool):
        if not checked or self._ink_tool == tool:
            # Clicking the active tool again turns ink off (pan/zoom resumes).
            self._ink_tool = ""
        else:
            self._ink_tool = tool
        for name, btn in self._tool_btns.items():
            btn.blockSignals(True)
            btn.setChecked(name == self._ink_tool)
            btn.blockSignals(False)
        self._plate.set_tool(self._ink_tool)

    def _set_draw_color(self, color: str):
        self._plate.set_draw_color(color)
        if not self._ink_tool:
            self._select_ink_tool("draw", True)

    def _persist(self, **style_updates):
        item = self._item()
        if item is None:
            return
        style = item.setdefault("style", {})
        style.update(style_updates)
        scene = self._view.scene
        scene._dirty = True
        try:
            scene._emit()
        except Exception:
            pass

    def place(self, local_rect: QtCore.QRect, floating: bool, owner: QtWidgets.QWidget | None):
        self._adopt_window(bool(floating and owner is not None), owner)
        if self._floating and owner is not None:
            top_left = _screen_top_left(self._view, local_rect)
            target = QtCore.QRect(top_left, local_rect.size())
        else:
            target = QtCore.QRect(local_rect)
        if self.geometry() != target:
            self.setGeometry(target)
        if self._floating:
            self._present_runtime()
            return
        if not self.isVisible():
            self.show()


def sync_efb_surfaces(view) -> None:
    """Create, place, or remove the EFB surface for each efb widget on this view."""
    if view is None:
        return
    surfaces: dict = getattr(view, "_efb_surfaces", None)
    if surfaces is None:
        surfaces = {}
        view._efb_surfaces = surfaces

    if not _overlay_is_shown(view):
        for surface in surfaces.values():
            surface.hide()
        return

    from .bindings import widget_is_live_visible
    from .widgets import widget_rect

    page_id = getattr(view, "_page_id", None)
    interactive = bool(getattr(view, "interactive", False))
    wanted = {}
    try:
        items = view.scene.sorted_widgets(page_id)
    except Exception:
        items = []
    for item in items:
        if str(item.get("type") or "") != "efb":
            continue
        if interactive:
            if item.get("visible", True) is False:
                continue
        elif not widget_is_live_visible(item):
            continue
        wanted[str(item.get("id") or "")] = item

    for widget_id in list(surfaces):
        if widget_id not in wanted:
            surface = surfaces.pop(widget_id)
            surface.shutdown()
            surface.hide()
            surface.deleteLater()

    floating = not interactive
    owner = view.window()
    for widget_id, item in wanted.items():
        surface = surfaces.get(widget_id)
        if surface is None:
            surface = EfbSurface(view, widget_id, floating=floating, owner=owner)
            surfaces[widget_id] = surface
        local = view._widget_rect(widget_rect(item).toAlignedRect())
        if interactive and local.width() > _DESIGNER_INSET * 3 and local.height() > _DESIGNER_INSET * 3:
            local = local.adjusted(_DESIGNER_INSET, _DESIGNER_INSET, -_DESIGNER_INSET, -_DESIGNER_INSET)
        surface.apply_item(item)
        surface.place(local, floating, owner)

    timer = getattr(view, "_efb_timer", None)
    if surfaces and timer is None:
        timer = QtCore.QTimer(view)
        timer.setInterval(200)
        timer.timeout.connect(lambda v=view: sync_efb_surfaces(v))
        view._efb_timer = timer
        timer.start()
    elif not surfaces and timer is not None:
        timer.stop()
