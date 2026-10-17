"""Overlay web page drawn inside the widget.

Windows default is the browser Windows uses for https links. The other rows
are browsers installed on the machine. The page stays in the widget. Choosing
a browser tells the site which browser it is. An already open browser is not
activated.
"""

from __future__ import annotations

import logging
import os

from PySide6 import QtCore, QtGui, QtWidgets

syslog = logging.getLogger("system")

_DESIGNER_INSET = 8
_APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
_SKIP_EXE = {
    "iexplore.exe",
    "icloudchrome.exe",
    "icloudfirefox.exe",
}
_KNOWN_EXE = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Mozilla Firefox",
    "brave.exe": "Brave",
    "opera.exe": "Opera",
    "vivaldi.exe": "Vivaldi",
    "duckduckgo.exe": "DuckDuckGo",
    "waterfox.exe": "Waterfox",
    "librewolf.exe": "LibreWolf",
    "floorp.exe": "Floorp",
    "palemoon.exe": "Pale Moon",
    "basilisk.exe": "Basilisk",
    "thorium.exe": "Thorium",
    "chromium.exe": "Chromium",
    "arc.exe": "Arc",
}
_FIREFOX_EXE = {"firefox.exe", "waterfox.exe", "librewolf.exe", "floorp.exe", "palemoon.exe", "basilisk.exe"}
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_USER_AGENTS = {
    "chrome": _CHROME_UA,
    "msedge": _CHROME_UA + " Edg/131.0.0.0",
    "firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "brave": _CHROME_UA,
    "opera": _CHROME_UA + " OPR/116.0.0.0",
    "vivaldi": _CHROME_UA,
    "duckduckgo": _CHROME_UA + " DuckDuckGo/5",
}


def installed_browsers() -> list[tuple[str, str]]:
    """``(id, label)``. The first row is the Windows default browser."""
    found: list[tuple[str, str]] = []
    default_path, default_label = _windows_default_browser()
    if default_label:
        found.append(("default", f"Windows default ({default_label})"))
    else:
        found.append(("default", "Windows default"))
    seen_paths = set()
    if default_path:
        seen_paths.add(os.path.normcase(default_path))
    for path, label in _installed_browser_exes():
        key = os.path.normcase(path)
        if key in seen_paths:
            # Still list it. Windows default and the same installed browser are different rows.
            pass
        seen_paths.add(key)
        browser_id = _browser_id_for_path(path, {item[0] for item in found})
        found.append((browser_id, label))
    return found


def normalize_browser_url(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        return "https://" + raw
    return raw


def resolve_browser(browser_id: str) -> tuple[str, str, str] | None:
    """``(exe path, kind, label)`` for a combo id. ``default`` follows Windows."""
    wanted = str(browser_id or "default")
    if wanted == "default":
        path, label = _windows_default_browser()
        if not path:
            return None
        return path, _browser_kind(path), label or "Windows default"
    for path, label in _installed_browser_exes():
        if _browser_id_for_path(path, set()) == wanted or os.path.normcase(path) == os.path.normcase(wanted):
            return path, _browser_kind(path), label
    # Id is the exe stem. Match that stem if the versioned path changed.
    for path, label in _installed_browser_exes():
        if _stem(path) == wanted:
            return path, _browser_kind(path), label
    return None


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0].lower()


def _browser_id_for_path(path: str, taken: set[str]) -> str:
    stem = _stem(path)
    if stem and stem not in taken and stem != "default":
        return stem
    # Same file name from two folders.
    extra = 2
    while f"{stem}-{extra}" in taken:
        extra += 1
    return f"{stem}-{extra}"


def _browser_kind(path: str) -> str:
    name = os.path.basename(path).lower()
    if name in _FIREFOX_EXE:
        return "firefox"
    if "duckduckgo" in name:
        return "duckduckgo"
    return "chromium"


def _exe_from_command(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    if text.startswith('"'):
        end = text.find('"', 1)
        return text[1:end] if end > 1 else ""
    return text.split(" ")[0]


def _windows_default_browser() -> tuple[str, str]:
    if os.name != "nt":
        return "", ""
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
        ) as key:
            prog_id, _kind = winreg.QueryValueEx(key, "ProgId")
    except OSError:
        return "", ""
    prog_id = str(prog_id or "")
    command = ""
    label = ""
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\shell\open\command") as key:
            command, _kind = winreg.QueryValueEx(key, "")
    except OSError:
        command = ""
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\Application") as key:
            label, _kind = winreg.QueryValueEx(key, "ApplicationName")
    except OSError:
        label = ""
    path = _exe_from_command(str(command or ""))
    if not path or not os.path.isfile(path):
        path = _app_path_exe(os.path.basename(path) if path else "")
    if not path:
        return "", ""
    label = str(label or "").strip()
    if not label or label.startswith("@"):
        label = _KNOWN_EXE.get(os.path.basename(path).lower()) or _stem(path).title()
    return path, label


def _app_path_exe(exe_name: str) -> str:
    if os.name != "nt" or not exe_name:
        return ""
    import winreg

    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, _APP_PATHS + "\\" + exe_name) as key:
                value, _kind = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        path = str(value or "").strip().strip('"')
        if path and os.path.isfile(path):
            return path
    return ""


def _installed_browser_exes() -> list[tuple[str, str]]:
    """Installed browsers as ``(exe path, label)``, without the Windows-default row."""
    if os.name != "nt":
        return []
    import winreg

    found: list[tuple[str, str]] = []
    seen = set()

    def add(path: str, label: str):
        path = str(path or "").strip().strip('"')
        if not path or not os.path.isfile(path):
            return
        name = os.path.basename(path).lower()
        if name in _SKIP_EXE or name.startswith("icloud"):
            return
        key = os.path.normcase(path)
        if key in seen:
            return
        seen.add(key)
        text = str(label or "").strip() or _KNOWN_EXE.get(name) or _stem(path).title()
        found.append((path, text))

    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Clients\StartMenuInternet"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Clients\StartMenuInternet"),
    )
    for root, path in roots:
        try:
            with winreg.OpenKey(root, path) as key:
                count, _values, _modified = winreg.QueryInfoKey(key)
                names = [winreg.EnumKey(key, index) for index in range(count)]
        except OSError:
            continue
        for name in names:
            command = ""
            try:
                with winreg.OpenKey(root, path + "\\" + name + r"\shell\open\command") as cmd_key:
                    command, _kind = winreg.QueryValueEx(cmd_key, "")
            except OSError:
                continue
            add(_exe_from_command(str(command or "")), name)

    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, _APP_PATHS) as key:
                count, _values, _modified = winreg.QueryInfoKey(key)
                names = [winreg.EnumKey(key, index) for index in range(count)]
        except OSError:
            continue
        for exe_name in names:
            low = exe_name.lower()
            if low not in _KNOWN_EXE and "duckduckgo" not in low:
                continue
            add(_app_path_exe(exe_name), _KNOWN_EXE.get(low, ""))

    default_path, _default_label = _windows_default_browser()
    if default_path:
        add(default_path, _KNOWN_EXE.get(os.path.basename(default_path).lower(), ""))
    return found


def _user_agent_for(browser_id: str) -> str:
    """User agent for the selected browser. Empty means the engine's own."""
    resolved = resolve_browser(browser_id)
    if resolved is None:
        return ""
    path, kind, _label = resolved
    stem = _stem(path)
    if stem in _USER_AGENTS:
        return _USER_AGENTS[stem]
    if kind == "firefox":
        return _USER_AGENTS["firefox"]
    if kind == "duckduckgo":
        return _USER_AGENTS["duckduckgo"]
    return _USER_AGENTS["chrome"]


def _show_runtime_hwnd(hwnd: int, *, topmost: bool):
    """Show a runtime page without activating it or adding a taskbar button.

    The tool-window extended style is applied on the HWND only. The Qt window
    type stays ``Window``, so Qt does not hide it while another app is in front.
    """
    import ctypes

    user32 = ctypes.windll.user32
    gwl_exstyle = -20
    ws_ex_topmost = 0x00000008
    ws_ex_toolwindow = 0x00000080
    ws_ex_noactivate = 0x08000000
    extras = ws_ex_toolwindow | ws_ex_noactivate
    if topmost:
        extras |= ws_ex_topmost
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_longlong
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
        style = user32.GetWindowLongPtrW(hwnd, gwl_exstyle)
        user32.SetWindowLongPtrW(hwnd, gwl_exstyle, style | extras)
    else:
        style = user32.GetWindowLongW(hwnd, gwl_exstyle)
        user32.SetWindowLongW(hwnd, gwl_exstyle, style | extras)
    user32.SetWindowPos.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = ctypes.c_int
    user32.SetWindowPos(
        hwnd,
        ctypes.c_void_p(-1 if topmost else 0),
        0,
        0,
        0,
        0,
        0x0001 | 0x0002 | 0x0010 | 0x0020 | 0x0040,
    )


def _runtime_window_flags(owner) -> QtCore.Qt.WindowType:
    """Frameless window that stays visible while the game is in front.

    ``Qt.Tool`` is hidden on Windows when this process is not the foreground
    app, which is the normal state of a live overlay. The editor does not use
    this path.
    """
    flags = (
        QtCore.Qt.Window
        | QtCore.Qt.FramelessWindowHint
        | QtCore.Qt.WindowDoesNotAcceptFocus
    )
    if owner is not None and (owner.windowFlags() & QtCore.Qt.WindowStaysOnTopHint):
        flags |= QtCore.Qt.WindowStaysOnTopHint
    return flags


def _install_page(profile, view):
    """Page that opens links in this view instead of another window."""
    from PySide6.QtWebEngineCore import QWebEnginePage

    class _WidgetPage(QWebEnginePage):
        def createWindow(self, _window_type):
            popup = _WidgetPage(self.profile(), self)
            popup.urlChanged.connect(self._adopt_popup)
            return popup

        def _adopt_popup(self, url):
            self.setUrl(url)
            sender = self.sender()
            if sender is not None and sender is not self:
                sender.deleteLater()

    page = _WidgetPage(profile, view)
    view.setPage(page)
    return page


class BrowserSurface(QtWidgets.QWidget):
    """URL bar plus the page. The page is drawn in this widget."""

    def __init__(self, view, widget_id: str, *, floating: bool = False, owner: QtWidgets.QWidget | None = None):
        super().__init__(None)
        self._view = view
        self.widget_id = str(widget_id)
        self._floating = False
        self._drag_origin = None
        self._drag_item_xy = None
        self._web = None
        self._profile = None
        self._default_ua = ""
        self._applied_ua = None
        self._loaded = None
        self._engine_error = ""
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

        self._grip = QtWidgets.QToolButton(self)
        self._grip.setText("::")
        self._grip.setToolTip("Drag to move this browser on the canvas")
        self._grip.setCursor(QtCore.Qt.SizeAllCursor)
        self._grip.setAutoRaise(True)
        self._grip.installEventFilter(self)

        self._url = QtWidgets.QLineEdit(self)
        self._url.setPlaceholderText("https://")
        self._url.setClearButtonEnabled(True)
        self._url.returnPressed.connect(self._commit_url)
        self._url.editingFinished.connect(self._commit_url)

        self._chrome = QtWidgets.QWidget(self)
        bar = QtWidgets.QHBoxLayout(self._chrome)
        bar.setContentsMargins(4, 2, 4, 2)
        bar.setSpacing(4)
        bar.addWidget(self._grip)
        bar.addWidget(self._url, 1)

        self._stage = QtWidgets.QWidget(self)
        stage_layout = QtWidgets.QVBoxLayout(self._stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(0)
        self._message = QtWidgets.QLabel("Enter a URL", self._stage)
        self._message.setAlignment(QtCore.Qt.AlignCenter)
        self._message.setWordWrap(True)
        self._message.setStyleSheet("background:#121418; color:#9aa4b2;")
        stage_layout.addWidget(self._message)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._chrome)
        layout.addWidget(self._stage, 1)
        self._adopt_window(bool(floating and owner is not None), owner)

    def shutdown(self):
        return

    def _adopt_window(self, floating: bool, owner: QtWidgets.QWidget | None):
        """Editor: child of the canvas. Runtime: its own window above the overlay."""
        if floating and owner is not None:
            flags = _runtime_window_flags(owner)
            current = self.windowFlags()
            same_type = (int(current) & 0xFF) == (int(QtCore.Qt.Window) & 0xFF)
            if (
                self._floating
                and self.isWindow()
                and self.parentWidget() is owner
                and same_type
                and bool(current & QtCore.Qt.WindowStaysOnTopHint) == bool(flags & QtCore.Qt.WindowStaysOnTopHint)
                and bool(current & QtCore.Qt.FramelessWindowHint)
            ):
                return
            self.hide()
            self.setParent(owner, flags)
            self._floating = True
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, False)
            self.setAttribute(QtCore.Qt.WA_NoSystemBackground, False)
            self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
            self.setAttribute(QtCore.Qt.WA_NativeWindow, True)
            self.setAutoFillBackground(True)
            palette = self.palette()
            palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#121418"))
            self.setPalette(palette)
            self.winId()
            return
        if not self._floating and not self.isWindow() and self.parentWidget() is self._view:
            return
        self.hide()
        self.setParent(self._view)
        self.setWindowFlags(QtCore.Qt.Widget)
        self._floating = False

    def _present_runtime(self):
        """Show the runtime page without taking focus, above a topmost overlay."""
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
            _show_runtime_hwnd(hwnd, topmost=bool(self.windowFlags() & QtCore.Qt.WindowStaysOnTopHint))
        except Exception as err:
            if not getattr(self, "_present_warned", False):
                self._present_warned = True
                syslog.warning(f"OBS OVERLAY: runtime browser show failed: {err}")

    def eventFilter(self, watched, event):
        if watched is self._grip and getattr(self._view, "interactive", False):
            if event.type() == QtCore.QEvent.Type.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                item = self._item()
                if item is not None and not item.get("locked"):
                    self._drag_origin = event.globalPosition()
                    self._drag_item_xy = (int(item.get("x") or 0), int(item.get("y") or 0))
                    try:
                        self._view.scene.set_selection([self.widget_id])
                    except Exception:
                        pass
                    return True
            if event.type() == QtCore.QEvent.Type.MouseMove and self._drag_origin is not None:
                self._drag_to(event.globalPosition())
                return True
            if event.type() == QtCore.QEvent.Type.MouseButtonRelease and self._drag_origin is not None:
                self._drag_origin = None
                self._drag_item_xy = None
                try:
                    self._view.scene._emit()
                except Exception:
                    pass
                return True
        return super().eventFilter(watched, event)

    def _drag_to(self, global_pos: QtCore.QPointF):
        item = self._item()
        if item is None or self._drag_origin is None or self._drag_item_xy is None:
            return
        zoom = float(getattr(self._view, "_zoom", 1.0) or 1.0)
        delta = global_pos - self._drag_origin
        item["x"] = int(round(self._drag_item_xy[0] + delta.x() / zoom))
        item["y"] = int(round(self._drag_item_xy[1] + delta.y() / zoom))
        scene = self._view.scene
        scene._dirty = True
        scene._emit_geometry()

    def _item(self):
        try:
            return self._view.scene.widget_by_id(self.widget_id, getattr(self._view, "_page_id", None))
        except Exception:
            return None

    def _commit_url(self):
        item = self._item()
        if item is None:
            return
        url = normalize_browser_url(self._url.text())
        style = item.setdefault("style", {})
        if str(style.get("url") or "") == url:
            self._show_page(url, str(style.get("browser") or "default"))
            return
        style["url"] = url
        scene = self._view.scene
        scene._dirty = True
        scene._emit()

    def apply_item(self, item: dict):
        style = item.get("style") or {}
        url = normalize_browser_url(style.get("url") or "")
        browser = str(style.get("browser") or "default")
        show_url = bool(style.get("show_url_bar", True))
        interactive = bool(getattr(self._view, "interactive", False))
        self._grip.setVisible(interactive)
        self._url.setVisible(show_url)
        # Runtime with URL off: only the page. Editor still shows the grip to move it.
        self._chrome.setVisible(show_url or interactive)
        if not self._url.hasFocus() and self._url.text().strip() != str(style.get("url") or "").strip():
            self._url.setText(str(style.get("url") or ""))
        self._show_page(url, browser)
        self._apply_scrollbars(bool(style.get("show_scrollbars", True)))

    def _apply_scrollbars(self, show: bool):
        if self._web is None:
            return
        try:
            from PySide6.QtWebEngineCore import QWebEngineSettings

            self._web.settings().setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, bool(show))
        except Exception:
            pass

    def _ensure_engine(self) -> bool:
        if self._web is not None:
            return True
        if self._engine_error:
            return False
        try:
            if self._floating:
                self.setAttribute(QtCore.Qt.WA_NativeWindow, True)
                self.winId()
            from PySide6.QtWebEngineCore import QWebEngineProfile
            from PySide6.QtWebEngineWidgets import QWebEngineView

            self._profile = QWebEngineProfile(self)
            self._default_ua = self._profile.httpUserAgent()
            self._web = QWebEngineView(self._stage)
            _install_page(self._profile, self._web)
            self._web.setFocusPolicy(QtCore.Qt.StrongFocus)
            item = self._item()
            style = (item or {}).get("style") or {}
            self._apply_scrollbars(bool(style.get("show_scrollbars", True)))
            self._stage.layout().addWidget(self._web, 1)
            self._message.hide()
            return True
        except Exception as err:
            self._web = None
            self._profile = None
            self._engine_error = str(err).strip() or err.__class__.__name__
            syslog.warning(f"OBS OVERLAY: in-widget browser failed: {err}")
            self._message.setText("The page could not be shown in the widget.")
            self._message.show()
            return False

    def _show_page(self, url: str, browser_id: str):
        if not url:
            self._message.setText("Enter a URL")
            self._message.show()
            if self._web is not None:
                self._web.hide()
            self._loaded = None
            return
        if not self._ensure_engine():
            return
        agent = _user_agent_for(browser_id) or self._default_ua
        key = (url, agent)
        if key == self._loaded:
            self._web.show()
            self._message.hide()
            return
        if agent != self._applied_ua:
            self._profile.setHttpUserAgent(agent)
            self._applied_ua = agent
        self._loaded = key
        self._message.hide()
        self._web.show()
        self._web.setUrl(QtCore.QUrl(url))

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


def _overlay_is_shown(view) -> bool:
    if view.isVisible():
        return True
    window = view.window()
    if window is None:
        return False
    return bool(getattr(window, "_host_attached", False)) and not bool(getattr(window, "_share_concealed", False))


def _screen_top_left(view, local_rect: QtCore.QRect) -> QtCore.QPoint:
    window = view.window()
    if os.name == "nt" and window is not None and bool(getattr(window, "_host_attached", False)):
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        user32 = ctypes.windll.user32
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        try:
            hwnd = int(window.winId())
        except Exception:
            hwnd = 0
        if hwnd and user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            local = view.mapTo(window, local_rect.topLeft())
            return QtCore.QPoint(int(rect.left) + int(local.x()), int(rect.top) + int(local.y()))
    return view.mapToGlobal(local_rect.topLeft())


def sync_browser_surfaces(view) -> None:
    """Create, place, or remove the browser for each browser widget on this view."""
    if view is None:
        return
    surfaces: dict = getattr(view, "_browser_surfaces", None)
    if surfaces is None:
        surfaces = {}
        view._browser_surfaces = surfaces

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
        if str(item.get("type") or "") != "browser":
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
            surface = BrowserSurface(view, widget_id, floating=floating, owner=owner)
            surfaces[widget_id] = surface
        local = view._widget_rect(widget_rect(item).toAlignedRect())
        if interactive and local.width() > _DESIGNER_INSET * 3 and local.height() > _DESIGNER_INSET * 3:
            local = local.adjusted(_DESIGNER_INSET, _DESIGNER_INSET, -_DESIGNER_INSET, -_DESIGNER_INSET)
        surface.apply_item(item)
        surface.place(local, floating, owner)

    timer = getattr(view, "_browser_timer", None)
    if surfaces and timer is None:
        timer = QtCore.QTimer(view)
        timer.setInterval(200)
        timer.timeout.connect(lambda v=view: sync_browser_surfaces(v))
        view._browser_timer = timer
        timer.start()
    elif not surfaces and timer is not None:
        timer.stop()


