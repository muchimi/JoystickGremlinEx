# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
# Module created by Joop de Hoog, 14-11-2026 for the map to application action
# Modified for Gremlin Ex by Muchimi
# Some portions are derived from the original 2019 Joystick Gremlin by Lionel Ott and other contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.


"""Map to Application: send keys or mouse buttons to an application, with or without a focus change.

Modified for m77 by Muchimi for UI consistency with other plugins

Delivery
  window  PostMessage into the application's main window (or the window_class child from the preset);
          no focus change, the application in front never sees the input (LXSim, XCSoar, LK8000 ...)
  focus   Focus and return: the application comes to the front, real input (SendInput), the focus goes
          back to the window that was in front, or to the main application 'sim' (CoMoMap, Discord ...)
Application
  <preset>  choose a preset from the plugin's presets folder or the user's gex_apps folder, then a function;
            the values are stored in the profile, so the profile works without the ini file
  (none)    target application, window title, delivery and key combination set by hand
Shared code: gex_core.py (copied into this folder by install_gex_actions.bat).
"""

import html
import logging
import math
from pathlib import Path
import time

from lxml import etree as ElementTree
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import QLabel
from shiboken6 import Shiboken

import gremlin.base_profile
import gremlin.config
import gremlin.event_handler
import gremlin.input_item
import gremlin.joystick_handling
import gremlin.keyboard
import gremlin.repeater
import gremlin.shared_state
import gremlin.ui.virtual_keyboard
import gremlin.util
import gremlin.win32_core as core
import vjoy.vjoy
from gremlin.input_types import InputType
from gremlin.keyboard import sort_keys
from gremlin.types import KeyboardOutputMode, SyncMode
from gremlin.ui.ui_common import (
    Buttons,
    Color,
    InputListenerWidget,
    QDataComboBox,
    QDataLineEdit,
    QDataPushButton,
    QDataRadioButton,
    QDelayWidget,
    QExecuteWidget,
    QFloatLineEdit,
    QHorizontalLine,
    QIconPushButton,
    QInfoBox,
    QIntLineEdit,
    QSyncModeWidget,
    QWarningWidget,
    getGridContainer,
    getHContainer,
    getVContainer,
    synchronize_grids,
)
from gremlin.ui.virtual_keyboard import InputKeyboardDialog
from gremlin.util import load_icon
from gremlin.window_picker import WindowPickerButton

syslog = logging.getLogger("system")
VERSION = "1.0"
PLUGIN_PRESETS_FOLDER = Path(__file__).with_name("presets")


def _load_application_presets(warn):
    """Load optional plugin presets and let user presets override matching names."""
    presets = {}
    if PLUGIN_PRESETS_FOLDER.is_dir():
        presets.update(core.load_presets(PLUGIN_PRESETS_FOLDER, warn=warn))
    presets.update(core.load_presets(warn=warn))
    return dict(sorted(presets.items(), key=lambda entry: entry[0].casefold()))

syslog.info(f"{core.TAG}: Map to Application {VERSION} loaded (gex_core {core.VERSION})")
if core.VERSION != VERSION:
    syslog.warning(f"{core.TAG}: Map to Application {VERSION} expects gex_core {VERSION}, found {core.VERSION}")
try:
    core.log_presets_folder()
    if PLUGIN_PRESETS_FOLDER.is_dir():
        syslog.info(f"{core.TAG}: additional presets from {PLUGIN_PRESETS_FOLDER}")
except Exception as e:  # noqa: BLE001
    syslog.warning(f"{core.TAG}: presets folder not determined: {e}")

DELIVERY = [("window", "Window (no focus change)"), ("focus", "Focus and return")]
DELIVERY_SHORT = {"window": "Window", "focus": "Focus and return"}
DELIVERY_HELP = {
    "window": "<b>Window</b>: the input goes only into the target application's main window (or into the child "
    "window set with window_class in the preset). A mouse button clicks on the fixed point, or where "
    "the mouse is when it is over the application, otherwise in the middle of its window; the mouse "
    "pointer does not move. The application in front keeps the focus and never sees the input. For "
    "applications that read input from their own window (for example LXSim, XCSoar, LK8000).",
    "focus": "<b>Focus and return</b>: the target application is brought to the front, the input is sent as real "
    "keystrokes or mouse clicks (on the fixed point - the mouse moves there and back - or where the mouse "
    "is), then the focus goes back to the window that was in front. For applications that react only "
    "while they are in front, or that listen to the keyboard globally (for example CoMoMap, Discord, "
    "TeamSpeak). The application in front loses the focus for a moment. Every output mode acts as Pulse "
    "Single; Duration is the time the input is held.",
    "uia": "<b>UI element</b>: the named control in the application is pressed through UI Automation, without "
    "keys. If the application takes the focus doing so, the focus is given back. Every output mode acts "
    "as Pulse Single.",
}

# mouse button -> Windows virtual key (used to find GremlinEx's own Key object for display)
_MOUSE_VK = {"left": 0x01, "right": 0x02, "middle": 0x04, "x1": 0x05, "x2": 0x06}
_MOUSE_LABEL = {
    "left": "Mouse Left",
    "right": "Mouse Right",
    "middle": "Mouse Middle",
    "x1": "Mouse Back",
    "x2": "Mouse Forward",
    "wheel_up": "Wheel Up",
    "wheel_down": "Wheel Down",
    "wheel_left": "Wheel Left",
    "wheel_right": "Wheel Right",
}
_KEY_CACHE = {}  # item -> GremlinEx Key object (for display and the virtual keyboard)


def _bool(node, key, default):
    v = node.get(key)
    return default if v is None else str(v).strip().lower() in ("1", "true", "yes")


def _num(node, key, kind, default):
    """a number attribute of an XML node; the default when it is missing or damaged (never raises,
    so a hand-edited profile still loads)"""
    v = node.get(key)
    if v is None:
        return default
    try:
        value = float(str(v).strip().replace(",", "."))
        if not math.isfinite(value):
            raise ValueError("number must be finite")
        return int(value) if kind is int else value
    except TypeError, ValueError, OverflowError:
        syslog.warning(f'{core.TAG}: Map to Application: bad value {key}="{v}" in the profile; using {default}')
        return default


# ============================================================================ items <-> GremlinEx keys
# Joystick Gremlin MouseButton values (gremlin.types.MouseButton)
_MOUSE_VALUE = {1: "left", 2: "right", 3: "middle", 4: "x1", 5: "x2", 10: "wheel_up", 11: "wheel_down", 12: "wheel_left", 13: "wheel_right"}
_MOUSE_WORDS = (
    ("wheel up", "wheel_up"),
    ("wheel down", "wheel_down"),
    ("wheel left", "wheel_left"),
    ("wheel right", "wheel_right"),
    ("wheelup", "wheel_up"),
    ("wheeldown", "wheel_down"),
    ("wheelleft", "wheel_left"),
    ("wheelright", "wheel_right"),
    ("left", "left"),
    ("right", "right"),
    ("middle", "middle"),
    ("back", "x1"),
    ("forward", "x2"),
    ("x1", "x1"),
    ("x2", "x2"),
)


def _mouse_item_from_key(key):
    """GremlinEx mouse Key -> 'mouse:<name>' (Key.mouse_button may be an enum, an int or a string;
    the key name looks like 'Mouse 2 (right)')"""
    mb = getattr(key, "mouse_button", None)
    if mb is not None:
        item = core.mouse_item(str(getattr(mb, "name", "") or ""))
        if item:
            return item
        try:
            name = _MOUSE_VALUE.get(int(getattr(mb, "value", mb)))
            if name:
                return core.mouse_item(name)
        except TypeError, ValueError:
            pass
    for text in (str(mb or ""), str(getattr(key, "name", "") or "")):
        low = text.lower()
        for word, name in _MOUSE_WORDS:
            if word in low:
                return core.mouse_item(name)
    syslog.warning(f"{core.TAG}: Map to Application: unknown mouse button {mb!r} ({type(mb).__name__}) name [{getattr(key, 'name', '')}]")
    return None


def item_from_key(key):
    """GremlinEx Key -> gex_core item: (vk, scan, extended) or 'mouse:<name>' (None if unusable)"""
    if getattr(key, "is_mouse", False):
        return _mouse_item_from_key(key)
    vk = int(getattr(key, "virtual_code", 0) or 0)
    if not vk:
        return None
    return (vk, int(getattr(key, "scan_code", 0) or 0), bool(getattr(key, "is_extended", False)))


def key_from_item(item):
    """gex_core item -> GremlinEx Key (None if GremlinEx has no matching key)"""
    if item in _KEY_CACHE:
        return _KEY_CACHE[item]
    key = None
    try:
        km = gremlin.keyboard.KeyMap
        if core.is_mouse(item):
            vk = _MOUSE_VK.get(core.mouse_name(item))
            k = km.find_virtual(vk) if vk else None
            if k is not None and getattr(k, "is_mouse", False) and item_from_key(k) == item:
                key = k
        else:
            vk, scan, ext = item
            k = km.find(scan, ext) if scan else None
            if k is None or getattr(k, "virtual_code", vk) != vk:
                k = km.find_virtual(vk) or k
            key = k
    except Exception:  # noqa: BLE001
        key = None
    if key is not None and getattr(key, "name", None):
        _KEY_CACHE[item] = key
        return key
    return None


def item_label(item):
    if core.is_mouse(item):
        return _MOUSE_LABEL.get(core.mouse_name(item), item)
    key = key_from_item(item)
    try:
        name = gremlin.keyboard.KeyMap.get_name(key) if key is not None else ""
    except Exception:  # noqa: BLE001
        name = ""
    return name or core.items_to_text([item])


# ============================================================================ widget
class MapToApplicationWidget(gremlin.input_item.AbstractActionWidget):
    """UI widget for mapping inputs to keys / mouse buttons for an application"""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        self.action_data = action_data

    # ------------------------------------------------------------------ build
    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        action_data = self.action_data
        self.presets = {}
        self._listened = []
        self._kbd_suspended = False

        # 1. application: a preset, or (none) for manual settings
        self.preset_app_cb = QDataComboBox(
            tooltip="Choose a preset from the plugin's presets folder or your gex_apps folder, or choose (none) to set the target, delivery and keys yourself"
        )
        self.reload_btn = QDataPushButton("Reload", tooltip="Read the preset files again from the plugin and user folders")
        self.preset_func_cb = QDataComboBox(tooltip="Choosing a function fills in the input; the values are stored in the profile")
        app_row = getHContainer([self.preset_app_cb, self.reload_btn], "Application:", widget_only=True)
        func_row = getHContainer(self.preset_func_cb, "Function:", widget_only=True)
        self.preset_info = QtWidgets.QLabel()
        self.preset_info.setWordWrap(True)
        self.running_lbl = QtWidgets.QLabel()
        info_row = getHContainer([(self.preset_info, 1), self.running_lbl], right_stretch=False, set_alignment=False, widget_only=True)
        self.uia_lbl = QtWidgets.QLabel()
        self.list_elements_btn = QDataPushButton(
            "List elements...", tooltip="Show the pressable UI elements of the running application (the chosen one is copied to the clipboard as a preset line)"
        )
        self.uia_row = getHContainer([self.uia_lbl, self.list_elements_btn], widget_only=True)
        self.preset_container = getVContainer([func_row, info_row, self.uia_row], widget_only=True)

        # 2. manual (application = none)
        self.program_ed = QDataLineEdit(action_data.program)
        self.program_ed.setPlaceholderText("process name, e.g. LXSim.exe")
        self.pick_btn = QDataPushButton("Select...", tooltip="Choose from the running programs")
        self.window_picker = WindowPickerButton(parent=self)
        self.window_picker.picking_started.connect(self._window_pick_started)
        self.window_picker.window_picked.connect(self._window_picked)
        self.window_picker.status_changed.connect(self._set_status)
        self.title_ed = QDataLineEdit(action_data.window_title)
        self.title_ed.setPlaceholderText("optional")
        target_row = getHContainer([self.program_ed, self.pick_btn, self.window_picker], "Target app:", widget_only=True)
        title_row = getHContainer(self.title_ed, "Window title:", widget_only=True)
        self.delivery_buttons = []
        for key, label in DELIVERY:
            rb = QDataRadioButton(label, key)
            rb.setChecked(action_data.delivery == key)
            rb.clicked.connect(self._delivery_changed)
            self.delivery_buttons.append(rb)
        delivery_row = getHContainer(self.delivery_buttons, "Delivery:", widget_only=True)

        # key combination (as Map to Keyboard/Mouse Ex)
        self.key_combination = QtWidgets.QLabel("<b>Key combination:</b>")
        self.display_container_widget, self.display_container_layout = getVContainer()
        self.key_combination_widget, self.key_combination_layout = getHContainer()
        widget = gremlin.ui.virtual_keyboard.QKeyWidget()
        self._key_height = widget.desiredHeight
        self.display_container_widget.setMinimumHeight(self._key_height + 4)
        self.display_container_layout.addWidget(self.key_combination_widget)

        self.listen_multi_widget = Buttons.getListenWidget(label="Listen (multi)", callback=self._record_multi_keys_cb)
        self.listen_multi_widget.setToolTip(
            "Listen for multiple inputs.  Click on ok when done.  Clicks on the buttons will not be included in the recorded list."
        )
        self.listen_widget = Buttons.getListenWidget(callback=self._record_keys_cb, tooltip="Listen for a single input.")

        self.show_keyboard_widget = QIconPushButton("Select...", callback=self._select_keys_cb, tooltip="Select keys using the virtual keyboard")
        self.show_keyboard_widget.setIcon(load_icon("mdi.keyboard-settings-outline", qta_color=Color().listenColor()))

        # self.show_keyboard_widget.setFixedHeight(24)  # match the other buttons
        self.clear_widget = Buttons.getClearWidget(callback=self._clear_keys_cb, tooltip="Clear the current keys")
        self.copy_line_btn = QDataPushButton(
            "Copy as preset line", tooltip="Copy this input as a line for a preset file ([functions] section) to the clipboard"
        )

        self.container_action_widget = getHContainer(
            [self.clear_widget, self.listen_widget, self.listen_multi_widget, self.show_keyboard_widget, self.copy_line_btn],
            widget_only=True,
        )

        # click position (only when the input has a mouse button)
        self.click_buttons = []
        for key, label in (("mouse", "Where the mouse is"), ("fixed", "Fixed point")):
            rb = QDataRadioButton(label, key)
            rb.setChecked(action_data.click_pos == key)
            rb.clicked.connect(self._click_pos_changed)
            self.click_buttons.append(rb)
        self.click_buttons[0].setToolTip("Click where the mouse is when it is over the application, otherwise in the middle of its window")
        self.click_buttons[1].setToolTip("Always click on the same spot in the application's window")
        self.click_x_box = QFloatLineEdit(decimals=1, step=1.0)
        self.click_y_box = QFloatLineEdit(decimals=1, step=1.0)
        self._sync_click_fields()
        for box in (self.click_x_box, self.click_y_box):
            box.setMinimumWidth(70)
            box.valueChanged.connect(self._click_xy_changed)
        self.click_unit_lbl = QLabel("")
        self.pick_btn2 = QDataPushButton("Pick...", tooltip="Then click on the spot in the application (Esc to cancel)", callback=self._pick_start)

        self.click_row = getHContainer(
            self.click_buttons + [QLabel("X:"), self.click_x_box, QLabel("Y:"), self.click_y_box, self.click_unit_lbl, self.pick_btn2],
            "Click position:",
            widget_only=True,
        )
        self._pick_timer = None

        self.manual_container = getVContainer(
            [target_row, title_row, delivery_row, self.key_combination, self.display_container_widget, self.container_action_widget, self.click_row],
            widget_only=True,
        )

        # 4. always: output mode, duration, interval, execute on (as Map to Keyboard/Mouse Ex)
        self.delay_box = QDelayWidget(action_data.delay)
        self.autorepeat_delay_box = QDelayWidget(action_data.autorepeat_delay)
        self.delay_box.setValue(action_data.delay)
        self.autorepeat_delay_box.setValue(action_data.autorepeat_delay)
        widgets = []
        for mode in KeyboardOutputMode:
            rb = QDataRadioButton(KeyboardOutputMode.to_displayname(mode), mode)
            rb.setChecked(action_data.mode == mode)
            rb.clicked.connect(self._mode_changed)
            widgets.append(rb)
        self.delay_box.valueChanged.connect(self._delay_changed)
        self.autorepeat_delay_box.valueChanged.connect(self._autorepeat_changed)
        self.container_options_widget = getGridContainer(getGridContainer(widgets, widget_only=True), "Output Mode:", widget_only=True, left_margin=12)
        self.delay_row = getGridContainer(self.delay_box, "Duration (ms):", widget_only=True)
        self.autorepeat_row = getGridContainer(self.autorepeat_delay_box, "Interval (ms):", widget_only=True)
        widgets = [self.delay_row, self.autorepeat_row]
        self.container_delay_widget = getVContainer(widgets, widget_only=True, left_margin=12)
        widgets.append(self.container_options_widget)
        synchronize_grids(widgets)

        self._execute_widget = QExecuteWidget(action_data.exec_on_press, action_data.exec_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)
        exec_container = getHContainer([self._execute_widget], widget_only=True)
        self._sync_widget = QSyncModeWidget(
            mode=action_data.sync_mode, label="State on profile start:", sync_modes=[SyncMode.Ignore, SyncMode.Input], callback=self._sync_changed
        )
        sync_container = getHContainer(self._sync_widget, left_margin=12, widget_only=True)
        widget = QIntLineEdit(value=action_data.wheel_factor, min_range=1, max_range=100, callback=self._handle_wheel_factor_changed)
        self.wheel_factor_container = getHContainer(
            widget,
            "Mouse Wheel Factor:",
            widget_only=True,
            tooltip="Mouse wheel motion factor, determines how much the wheel moves per trigger. The default is 1 for 1x.",
            left_margin=12,
        )

        # 5. test, information, warnings
        self.test_btn = QDataPushButton("Test now")
        self.test_btn.setToolTip("Send the input once (Pulse Single) to the application")
        self.status_lbl = QLabel("")
        test_row = getHContainer([self.test_btn, self.status_lbl], widget_only=True)
        self.description_widget = QInfoBox(hide_key=self.__class__.__name__)
        self.warning_widget = QWarningWidget()

        for w in (
            app_row,
            self.preset_container,
            self.manual_container,
            QHorizontalLine(),
            self.container_options_widget,
            self.container_delay_widget,
            self.wheel_factor_container,
            exec_container,
            sync_container,
            test_row,
            self.description_widget,
            self.warning_widget,
        ):
            self.main_layout.addWidget(w)
        self.main_layout.addStretch()

        # signals; 'activated' = a choice made by the user (not when the panel is filled)
        self.preset_app_cb.activated.connect(self._preset_app_chosen)
        self.preset_func_cb.activated.connect(self._preset_function_chosen)
        self.reload_btn.clicked.connect(lambda: self._fill_presets(warn=True))
        self.list_elements_btn.clicked.connect(self._list_elements)
        self.program_ed.editingFinished.connect(self._target_changed)
        self.title_ed.editingFinished.connect(self._target_changed)
        self.pick_btn.clicked.connect(self._pick_program)
        self.copy_line_btn.clicked.connect(self._copy_preset_line)
        self.test_btn.clicked.connect(self._test)

        self._fill_presets(warn=False)
        self._populate_ui()

    def _populate_ui(self):
        """Populates the UI components (does not change the action)."""
        if not Shiboken.isValid(self) or not hasattr(self, "key_combination_layout"):
            return
        self._show_keys()
        self._update_ui()

    def _modified(self):
        try:
            self.action_modified.emit()
        except Exception:  # noqa: BLE001, S110
            pass

    # ------------------------------------------------------------------ application / presets
    def _uses_preset(self):
        a = self.action_data
        return a.source == "preset" and bool(a.preset_app)

    def _fill_presets(self, warn=False):
        a = self.action_data
        self.presets = _load_application_presets(warn)
        cb = self.preset_app_cb
        current = a.preset_app if self._uses_preset() else ""
        with QtCore.QSignalBlocker(cb):
            cb.clear()
            cb.addItem("(none: set manually)", "")
            for name in self.presets:
                cb.addItem(name, name)
            if current and current not in self.presets:
                cb.addItem(f"{current} (file not found)", current)
            cb.setCurrentIndex(max(0, cb.findData(current)))
        self._fill_functions()
        if warn:
            self.status_lbl.setText(f"{len(self.presets)} preset(s) loaded")
            self._update_ui()

    def _fill_functions(self):
        a = self.action_data
        name = self.preset_app_cb.currentData() or ""
        preset = self.presets.get(name)
        cb = self.preset_func_cb
        with QtCore.QSignalBlocker(cb):
            cb.clear()
            cb.addItem("(choose a function)", "")
            if preset:
                for f in preset.functions:
                    cb.addItem(f.label, f.name)
            if name and name == a.preset_app and a.preset_function:
                idx = cb.findData(a.preset_function)
                if idx < 0:
                    cb.addItem(f"{a.preset_function} (not in the file)", a.preset_function)
                    idx = cb.count() - 1
                cb.setCurrentIndex(idx)
            cb.setEnabled(bool(name))

    def _apply_app_settings(self, preset, func=None):
        a = self.action_data
        a.program = preset.program
        a.window_title = preset.window_title
        a.window_class = preset.window_class
        a.delivery = preset.delivery_of(func) if func is not None else preset.delivery
        a.sim = preset.sim or "Condor.exe"
        a.click = func.click() if func is not None else None

    def _preset_app_chosen(self, *_):
        a = self.action_data
        name = self.preset_app_cb.currentData() or ""
        preset = self.presets.get(name)
        if not name:
            # (none): manual settings; the current values are kept
            a.source, a.preset_app, a.preset_function = "manual", "", ""
            self._fill_functions()
            self._sync_manual_fields()
            self._populate_ui()
            self._modified()
            return
        if preset is None:
            return  # 'file not found' entry: keep the stored values
        if self._uses_preset() and a.preset_app == preset.name:
            return  # the same application chosen again: nothing changes
        a.source = "preset"
        a.preset_app, a.preset_function = preset.name, ""
        self._apply_app_settings(preset)
        a.setItems([])
        a.function_kind, a.uia_name = "key", ""
        self._fill_functions()
        self._sync_manual_fields()
        self._populate_ui()
        self._modified()

    def _preset_function_chosen(self, *_):
        a = self.action_data
        preset = self.presets.get(self.preset_app_cb.currentData() or "")
        func = preset.function(self.preset_func_cb.currentData() or "") if preset else None
        if func is None:
            self._fill_functions()  # placeholder chosen: show the stored function again
            return
        a.source = "preset"
        a.preset_app, a.preset_function = preset.name, func.name
        self._apply_app_settings(preset, func)
        if func.kind() == "uia":
            a.function_kind, a.uia_name = "uia", func.uia_name
            a.setItems([])
        else:
            a.function_kind, a.uia_name = "key", ""
            a.setItems(func.items())
        self._sync_manual_fields()
        self._populate_ui()
        self._modified()

    def _preset_differences(self):
        """list of stored values that differ from the preset file ([] if equal or no file)"""
        a = self.action_data
        preset = self.presets.get(a.preset_app)
        func = preset.function(a.preset_function) if preset and a.preset_function else None
        if preset is None or func is None:
            return []
        diff = []
        if a.program.lower() != preset.program.lower():
            diff.append("program")
        if a.window_title != preset.window_title:
            diff.append("window title")
        if a.window_class != preset.window_class:
            diff.append("window class")
        if a.delivery != preset.delivery_of(func):
            diff.append("delivery")
        if func.kind() == "uia":
            if a.function_kind != "uia" or a.uia_name != func.uia_name:
                diff.append("UI element")
        elif a.function_kind != "key" or core.items_signature(a.items) != core.items_signature(func.items()):
            diff.append("input")
        elif a.click != func.click():
            diff.append("click position")
        return diff

    def _list_elements(self):
        a = self.action_data
        program, title = a.program, a.window_title
        if not core.is_running(program, title):
            self.status_lbl.setText(f"{program or 'Target app'} not running")
            return
        self.status_lbl.setText("Reading UI elements...")

        def job():
            try:
                names = core.uia_names(program, title)
            except Exception as e:  # noqa: BLE001
                syslog.warning(f"{core.TAG}: List elements: {e}")
                names = []
            gremlin.util.InvokeUiMethod(self._show_elements, names)

        core.UiaWorker.put(job)

    def _show_elements(self, names):
        if not Shiboken.isValid(self):
            return
        a = self.action_data
        if not names:
            self.status_lbl.setText("No pressable UI elements found")
            return
        self.status_lbl.setText(f"{len(names)} UI element(s)")
        item, ok = QtWidgets.QInputDialog.getItem(self, "UI elements", f"Pressable UI elements in {a.program}:", names, 0, False)
        if ok and item:
            QtWidgets.QApplication.clipboard().setText(f"{item} = uia:{item}")
            self.status_lbl.setText("Copied to the clipboard as a preset line")

    # ------------------------------------------------------------------ manual: target / delivery
    def _sync_manual_fields(self):
        a = self.action_data
        with QtCore.QSignalBlocker(self.program_ed):
            self.program_ed.setText(a.program)
        with QtCore.QSignalBlocker(self.title_ed):
            self.title_ed.setText(a.window_title)
        for rb in self.delivery_buttons:
            rb.setChecked(rb.data == a.delivery)
        self._sync_click_fields()

    def _target_changed(self):
        a = self.action_data
        program, title = self.program_ed.text().strip(), self.title_ed.text().strip()
        if (program, title) != (a.program, a.window_title):
            a.program, a.window_title = program, title
            self._modified()
        self._update_ui()

    def _pick_program(self):
        names = core.running_programs()
        item, ok = QtWidgets.QInputDialog.getItem(self, "Target app", "Running programs with a window:", names, 0, False)
        if ok and item:
            self.program_ed.setText(item)
            self._target_changed()

    def _window_pick_started(self):
        if self._pick_timer is not None:
            self._pick_stop("Click position pick cancelled")

    def _window_picked(self, program, title):
        a = self.action_data
        if (program, title, "") != (a.program, a.window_title, a.window_class):
            a.program, a.window_title, a.window_class = program, title, ""
            self._sync_manual_fields()
            self._update_ui()
            self._modified()

    def _delivery_changed(self):
        self.action_data.delivery = self.sender().data
        self._update_ui()
        self._modified()

    # ------------------------------------------------------------------ manual: click position
    def _sync_click_fields(self):
        a = self.action_data
        for rb in self.click_buttons:
            rb.setChecked(rb.data == a.click_pos)
        maximum = 100 if a.click_unit == "%" else 10000
        for box, value in ((self.click_x_box, a.click_x), (self.click_y_box, a.click_y)):
            with QtCore.QSignalBlocker(box):
                box.setRange(0, maximum)
                box.setValue(round(min(max(value, 0.0), maximum), 1))

    def _click_pos_changed(self):
        self.action_data.click_pos = self.sender().data
        self._update_ui()
        self._modified()

    def _click_xy_changed(self, value):
        if not math.isfinite(value):
            self._sync_click_fields()
            return

        a = self.action_data
        box = self.sender()
        box.setValue(round(min(max(value, 0.0), box.maximum()), 1), emit=False)
        coordinates = self.click_x_box.value(), self.click_y_box.value()
        if coordinates != (a.click_x, a.click_y):
            a.click_x, a.click_y = coordinates
            self._modified()

    def _pick_start(self):
        a = self.action_data
        if self._pick_timer is not None:
            self._pick_stop("Pick cancelled")
            return
        if not core.is_running(a.program, a.window_title):
            self.status_lbl.setText(f"{a.program or 'Target app'} not running")
            return
        self._pick_wait_release = True  # the click on Pick... itself does not count
        self._pick_deadline = time.time() + 15
        self._pick_timer = QtCore.QTimer(self)
        self._pick_timer.setInterval(20)
        self._pick_timer.timeout.connect(self._pick_tick)
        self._pick_timer.start()
        self.pick_btn2.setText("Picking...")
        self.status_lbl.setText(f"Click on the spot in {a.program} (Esc to cancel)")

    def _pick_stop(self, message):
        if self._pick_timer is not None:
            self._pick_timer.stop()
            self._pick_timer.deleteLater()
            self._pick_timer = None
        if Shiboken.isValid(self):
            self.pick_btn2.setText("Pick...")
            self.status_lbl.setText(message)

    def _pick_tick(self):
        if not Shiboken.isValid(self):
            return
        a = self.action_data
        if core.button_down(0x1B):  # Esc
            self._pick_stop("Pick cancelled")
            return
        if time.time() > self._pick_deadline:
            self._pick_stop("Pick timed out")
            return
        if self._pick_wait_release:
            self._pick_wait_release = core.button_down(0x01)
            return
        down = core.button_down(0x01, or_since_last=True)  # left mouse button (also a very short click)
        if not down:
            return
        click = core.click_from_screen(a.program, a.window_title, core.cursor_pos())
        if click is None:
            self.status_lbl.setText(f"Not on {a.program}: click on the spot in {a.program} (Esc to cancel)")
            self._pick_wait_release = True
            return
        a.click_pos = "fixed"
        a.click_x, a.click_y, a.click_unit = click[0], click[1], "%"
        self._sync_click_fields()
        self._pick_stop(f"Picked {click[0]:g} %, {click[1]:g} % in {a.program}")
        self._update_ui()
        self._modified()

    def _copy_preset_line(self):
        a = self.action_data
        if a.function_kind == "uia" and a.uia_name:
            value = f"uia:{a.uia_name}"
        elif a.items:
            value = core.value_text(a.items, a.click)
        else:
            self.status_lbl.setText("Nothing to copy")
            return
        name = a.preset_function or "Function name"
        QtWidgets.QApplication.clipboard().setText(f"{name} = {value} [{a.delivery}]")
        self.status_lbl.setText("Copied to the clipboard as a preset line")

    # ------------------------------------------------------------------ keys (as Map to Keyboard/Mouse Ex)
    def _show_keys(self):
        gremlin.util.clear_layout(self.key_combination_layout)
        a = self.action_data
        if not a.items:
            if a.function_kind == "uia" and a.uia_name:
                text = f"UI element <i>{html.escape(a.uia_name)}</i> (from a preset). Choose keys to replace it."
                self.key_combination_layout.addWidget(QLabel(text))
            else:
                self.key_combination_layout.addWidget(QWarningWidget("No input selected. Please select at least one input."))
            self.key_combination_layout.addStretch()
            return
        for item in a.items:
            self._add_key_widget(item)
        self.key_combination_layout.addStretch()

    def _add_key_widget(self, item):
        widget = gremlin.ui.virtual_keyboard.QKeyWidget()
        key = key_from_item(item)
        if key is not None:
            try:
                widget.key = key
                icon = gremlin.keyboard.KeyMap.icon(key)
                if icon:
                    widget.setIcon(icon)
                tooltip = gremlin.keyboard.KeyMap.get_description(key)
                if tooltip:
                    widget.setToolTip(tooltip)
            except Exception:  # noqa: BLE001, S110
                pass
        widget.setText(item_label(item))
        widget.keySize = 2
        widget.autoSize = True
        widget.gex_item = item
        widget.right_clicked.connect(self._handle_key_context)
        layout = self.key_combination_layout
        idx = layout.count()
        if idx and layout.itemAt(idx - 1).spacerItem() is not None:
            idx -= 1  # keep the stretch at the end
        layout.insertWidget(idx, widget)

    def _handle_key_context(self, widget):
        gremlin.util.InvokeUiMethod(self._handle_key_context_ui, widget)

    def _handle_key_context_ui(self, widget):
        from functools import partial

        actionDelete = QtGui.QAction("Delete", self)
        actionDelete.triggered.connect(partial(self._delete_key, widget))
        menu = QtWidgets.QMenu(self)
        menu.addAction(actionDelete)
        menu.exec_(QtGui.QCursor.pos())

    def _delete_key(self, widget):
        item = getattr(widget, "gex_item", None)
        self.action_data.removeItem(item)
        self._populate_ui()
        self._modified()

    def _set_from_keys(self, keys):
        """store GremlinEx Key objects (from Listen / Select) as items"""
        keys = [k for k in keys if k is not None]
        try:
            keys = sort_keys(keys)
        except Exception:  # noqa: BLE001, S110
            pass
        items = []
        for k in keys:
            item = item_from_key(k)
            if item is None:
                syslog.warning(f"{core.TAG}: Map to Application: input [{getattr(k, 'name', k)}] is not supported")
                continue
            if item not in items:
                _KEY_CACHE.setdefault(item, k)
                items.append(item)
        # press order: modifiers, other keys, mouse buttons (released in reverse)
        items = (
            [i for i in items if not core.is_mouse(i) and i[0] in core.MODIFIER_VKS]
            + [i for i in items if not core.is_mouse(i) and i[0] not in core.MODIFIER_VKS]
            + [i for i in items if core.is_mouse(i)]
        )
        a = self.action_data
        a.setItems(items)
        a.function_kind, a.uia_name = "key", ""
        self._populate_ui()
        self._modified()

    def _clear_keys_cb(self):
        gremlin.util.InvokeUiMethod(self._clear_keys_ui)

    def _clear_keys_ui(self):
        a = self.action_data
        a.setItems([])
        a.function_kind, a.uia_name = "key", ""
        self._populate_ui()
        self._modified()

    def _select_keys_cb(self):
        """display the keyboard input dialog"""
        gremlin.shared_state.push_suspend_ui_keyinput()
        self._kbd_suspended = True
        sequence = [k for k in (key_from_item(i) for i in self.action_data.items) if k is not None]
        self._keyboard_dialog = InputKeyboardDialog(sequence=sequence, parent=self)
        self._keyboard_dialog.accepted.connect(self._keyboard_dialog_ok_cb)
        self._keyboard_dialog.closed.connect(self._keyboard_dialog_closed_cb)
        self._keyboard_dialog.setModal(True)
        self._keyboard_dialog.showNormal()

    def _resume_keyinput(self):
        if self._kbd_suspended:
            self._kbd_suspended = False
            gremlin.shared_state.pop_suspend_ui_keyinput()

    def _keyboard_dialog_closed_cb(self, *_):
        self._resume_keyinput()

    def _keyboard_dialog_ok_cb(self):
        self._set_from_keys(list(self._keyboard_dialog.keys))
        self._resume_keyinput()

    def _record_keys_cb(self):
        gremlin.util.InvokeUiMethod(self._record_keys_ui, False)

    def _record_multi_keys_cb(self):
        gremlin.util.InvokeUiMethod(self._record_keys_ui, True)

    def _record_keys_ui(self, multi_keys):
        """Prompts the user to press the desired key combination. - runs on UI thread"""
        gremlin.shared_state.push_suspend_highlighting()
        button_press_dialog = InputListenerWidget([InputType.Keyboard, InputType.Mouse], return_kb_event=False, multi_keys=multi_keys)
        button_press_dialog.item_selected.connect(self._listen_selected)
        button_press_dialog.keyInput.connect(self._listen_key_input)
        button_press_dialog.closed.connect(self._listen_closed)
        self._listened = []
        gremlin.util.clear_layout(self.key_combination_layout)  # clear the current display
        self.key_combination_layout.addStretch()

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()
        button_press_dialog.setGeometry(int(geom.x() + geom.width() / 2 - 150), int(geom.y() + geom.height() / 2 - 75), 300, 150)
        button_press_dialog.show()
        self._listen_dialog = button_press_dialog

    def _listen_selected(self, keys):
        keys = list(keys) if hasattr(keys, "__iter__") else [keys]
        gremlin.util.InvokeUiMethod(self._set_from_keys, keys)

    def _listen_key_input(self, keys):
        gremlin.util.InvokeUiMethod(self._listen_key_input_ui, keys)

    def _listen_key_input_ui(self, keys):
        for k in list(keys) if hasattr(keys, "__iter__") else [keys]:
            if k not in self._listened:
                self._listened.append(k)
                item = item_from_key(k)
                if item is not None:
                    _KEY_CACHE.setdefault(item, k)
                    self._add_key_widget(item)

    def _listen_closed(self, accepted):
        """occurs when the listen dialog closes, passes the close state"""
        if accepted and self._listened:
            self._set_from_keys(self._listened)
        else:
            self._populate_ui()
        gremlin.shared_state.pop_suspend_highlighting()

    # ------------------------------------------------------------------ options (as Map to Keyboard/Mouse Ex)
    def _handle_wheel_factor_changed(self, value: int):
        self.action_data.wheel_factor = value

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked: bool):
        had_output = self.action_data.hasOutput()
        self.action_data.exec_on_press = checked
        self._output_option_changed(had_output)

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked: bool):
        had_output = self.action_data.hasOutput()
        self.action_data.exec_on_release = checked
        self._output_option_changed(had_output)

    def _sync_changed(self, mode):
        self.action_data.sync_mode = mode

    def _mode_changed(self):
        had_output = self.action_data.hasOutput()
        self.action_data.mode = self.sender().data
        self._output_option_changed(had_output)

    def _output_option_changed(self, had_output):
        if self.action_data.hasOutput() != had_output:
            self.action_data.fireIconChanged()
        self._update_ui()
        self._modified()

    def _delay_changed(self):
        self.action_data.delay = self.delay_box.value()

    def _autorepeat_changed(self):
        self.action_data.autorepeat_delay = self.autorepeat_delay_box.value()

    # ------------------------------------------------------------------ state
    def _update_ui(self):
        """updates the UI based on the current source, delivery and mode"""
        a = self.action_data
        is_preset = self._uses_preset()
        uia = a.function_kind == "uia" and bool(a.uia_name)
        holdable = a.delivery == "window" and not uia
        self.preset_container.setVisible(is_preset)
        self.manual_container.setVisible(not is_preset)
        self.uia_row.setVisible(is_preset and uia)
        self.uia_lbl.setText(f"UI element: <i>{html.escape(a.uia_name)}</i>")

        # preset information line
        running = bool(a.program) and core.is_running(a.program, a.window_title)
        if is_preset:
            if not a.program:
                self.preset_info.setText("The preset has no program.")
            else:
                what = f"UI element: {a.uia_name}" if uia else (core.value_text(a.items, a.click) or "no input")
                preset = self.presets.get(a.preset_app)
                path = Path(preset.path) if preset is not None else None
                origin = f"from {path.parent.name}/{path.name}" if path is not None else f"saved preset {a.preset_app}"
                origin = html.escape(origin)
                text = f"{a.program} · {DELIVERY_SHORT.get(a.delivery, a.delivery)} · {what} · {origin}"
                diff = self._preset_differences()
                if diff:
                    text += f"<br><i>Stored {', '.join(diff)} differs from the preset file. Select the function again to update the stored values.</i>"
                self.preset_info.setText(text)
            self.running_lbl.setText("running" if running else ("not running" if a.program else ""))
        if a.program:
            self.test_btn.setToolTip(f"Send the input once (Pulse Single) to {a.program}")

        # output mode (texts as Map to Keyboard/Mouse Ex)
        delay_visible = False
        autorepeat_visible = False
        warnings = []
        match a.mode:
            case KeyboardOutputMode.Press:
                description = "<b>Press</b> mode will press the input - it is not released and should be paired with a release at some point (keyboard 'make')."
            case KeyboardOutputMode.Release:
                description = "<b>Release</b> mode will release the input previously pressed with the Press mode (keyboard 'break'). If no input is set, the release mode will also clear any auto-repeat actions to cancel them."
            case KeyboardOutputMode.Hold:
                if a.exec_on_release:
                    warnings.append("Hold mode cannot be used for execute on release.  The action will not execute at runtime on input release.")
                description = "<b>Hold</b> mode will keep the input pressed while the input is on/pressed.  It is released when the input is off/released.<br>This mode <b>does not</b> autorepeat.  To autorepeat, select autorepeat mode."
            case KeyboardOutputMode.Pulse:
                delay_visible = True
                description = "<b>Pulse</b> mode will press the input, wait for the delay, then release it."
            case KeyboardOutputMode.AutoRepeat:
                if a.exec_on_release:
                    warnings.append("Autorepeat mode cannot be used for execute on release.  The action will not execute at runtime on input release.")
                delay_visible = True
                autorepeat_visible = True
                description = "<b>AutoRepeat</b> mode will pulse the input repeatedly. The delay is the time between a press/release, interval is the time between pulses."
            case _:
                description = "<b>Toggle</b> mode will toggle the input pressed/released."
        if not holdable:
            delay_visible, autorepeat_visible = True, False
            if a.mode != KeyboardOutputMode.Pulse:
                warnings.append("With " + ("a UI element" if uia else "Focus and return") + " every output mode acts as Pulse Single.")
        self.container_delay_widget.setVisible(delay_visible)
        self.autorepeat_row.setVisible(autorepeat_visible)
        self.wheel_factor_container.setVisible(any(core.is_wheel(i) for i in a.items))
        has_mouse = any(core.is_mouse(i) for i in a.items)
        self.click_row.setVisible(has_mouse)
        fixed = a.click_pos == "fixed"
        for w in (self.click_x_box, self.click_y_box):
            w.setEnabled(fixed)
        self.click_unit_lbl.setText("%" if a.click_unit == "%" else "px")

        help_text = DELIVERY_HELP["uia"] if uia else DELIVERY_HELP.get(a.delivery, "")
        self.description_widget.setText(f"{help_text}<br><br>{description}")

        clears_autorepeat = a.mode == KeyboardOutputMode.Release and not a.items and not uia
        if not a.program and not clears_autorepeat:
            warnings.append("No target application.")
        elif a.program and not running and not clears_autorepeat:
            warnings.append(f"{a.program} is not running at the moment.")
        if not a.items and not uia and not clears_autorepeat:
            warnings.append("No input selected.")
        if is_preset and a.preset_app and a.preset_app not in self.presets:
            warnings.append(f"Preset file {a.preset_app}.ini not found; the stored values are used.")
        if not a.exec_on_press and not a.exec_on_release and a.mode not in (KeyboardOutputMode.Hold, KeyboardOutputMode.AutoRepeat):
            warnings.append("Neither execute on press nor on release is selected: the action does nothing.")
        self.warning_widget.setVisible(bool(warnings))
        self.warning_widget.setText("<br>".join(warnings))

    def _test(self):
        a = self.action_data
        if a.source == "manual":
            self._target_changed()
        if not core.is_running(a.program, a.window_title):
            self.status_lbl.setText(f"{a.program or 'Target app'} not running")
            return
        if a.function_kind == "uia" and a.uia_name:
            args = (a.program, a.window_title, a.uia_name)
            core.UiaWorker.put(lambda: self._test_result(core.deliver_uia(*args)))
        elif a.items:
            args = (a.program, a.window_title, a.delivery, list(a.items), True, True, a.sim, a.delay / 1000.0, a.window_class, a.wheel_factor, a.click)
            core.Worker.put(lambda: self._test_result(core.deliver(*args)))
        else:
            self.status_lbl.setText("Nothing to send")
            return
        self.status_lbl.setText("Sending...")

    def _test_result(self, result):
        _report(result, self.action_data)
        ok, msg = result
        gremlin.util.InvokeUiMethod(self._set_status, "Sent" if ok else msg)

    def _set_status(self, text):
        if Shiboken.isValid(self):
            self.status_lbl.setText(text)


def _report(result, action, release_only=False):
    ok, msg = result
    if not ok:
        if release_only and msg.endswith("not running"):
            return  # already reported at the press: one warning per press is enough
        syslog.warning(f"{core.TAG}: Map to Application: {msg}")
    elif gremlin.config.Configuration().verbose_mode_keyboard:
        syslog.info(f"{core.TAG}: Map to Application: sent to {action.program} ({action.delivery})")


# ============================================================================ functor
class MapToApplicationFunctor(gremlin.base_profile.AbstractFunctor):
    def __init__(self, action, parent=None):
        super().__init__(action, parent)
        self.action_data = action
        self.verbose = gremlin.config.Configuration().verbose_mode_keyboard
        self._pulse_worker = None
        self._down = False  # input sent down and not yet released (window delivery)
        self._toggled = False
        self._hold_id = object()
        self._startup_sync_pending = False
        el = gremlin.event_handler.EventListener()
        el.autorepeat_clear.connect(self._autorepeat_clear)

    # ------------------------------------------------------------------ delivery
    def _uses_uia(self):
        a = self.action_data
        return a.function_kind == "uia" and bool(a.uia_name)

    def _has_output(self):
        return self._uses_uia() or bool(self.action_data.items)

    def _holdable(self):
        """separate press and release: only keys / mouse buttons with Window delivery"""
        return not self._uses_uia() and self.action_data.delivery == "window"

    def _send(self, down, up):
        """queue one press and/or release on the background worker (never blocks the event thread)"""
        a = self.action_data
        program, title, delivery, items = a.program, a.window_title, a.delivery, list(a.items)
        wclass, sim, hold_s, wheel, click = a.window_class, a.sim, a.delay / 1000.0, a.wheel_factor, a.click
        uia = a.uia_name if self._uses_uia() else ""
        if down and not up:
            self._down = True
        elif up:
            self._down = False
        if self.verbose:
            syslog.info(
                f"{core.TAG}: Map to Application: {'down' if down else ''}{'up' if up else ''} {uia or core.items_to_text(items)} -> {program} ({delivery})"
            )

        if uia:
            if down:
                # UI Automation can be slow: its own thread, so it never delays a key release
                core.UiaWorker.put(lambda: _report(core.deliver_uia(program, title, uia), a))
            return
        # Separate Press and Release actions can share a matching binding.
        hold_id = None if a.mode in (KeyboardOutputMode.Press, KeyboardOutputMode.Release) else self._hold_id
        core.Worker.put(
            lambda: _report(
                core.deliver(program, title, delivery, items, down, up, sim, hold_s, wclass, wheel, click, hold_id), a, release_only=up and not down
            )
        )

    # GremlinEx's PulseWorker passes 'data' only when it is set: accept both call forms
    def _pulse_on(self, *_data):
        self._send(True, False)

    def _pulse_off(self, *_data):
        self._send(False, True)

    def pulse_start(self, duration: float, interval: float):
        """pulse (interval < 0) or repeated pulses, as Map to Keyboard/Mouse Ex"""
        worker = self._pulse_worker
        if worker is not None and worker.is_running:
            return  # already pulsing - ignore
        self._pulse_worker = gremlin.repeater.PulseWorker(duration, interval, self._pulse_on, self._pulse_off, data=None)
        self._pulse_worker.start()

    def pulse_stop(self):
        """stop pulsing; if a pulse was cut off between press and release, release now"""
        if self._pulse_worker is not None:
            self._pulse_worker.stop()
            self._pulse_worker = None
            if self._down:
                self._send(False, True)

    def _release_all(self):
        """release whatever this action still holds (pulse, Hold, Press, Toggle)"""
        self.pulse_stop()
        if self._down:
            self._send(False, True)
        self._toggled = False

    @QtCore.Slot()
    def _autorepeat_clear(self):
        self.pulse_stop()

    # ------------------------------------------------------------------ profile
    def profile_start(self):
        self._down = False
        self._toggled = False
        self._pulse_worker = None
        self._startup_sync_pending = self.action_data.sync_mode == SyncMode.Input

    def _sync_input(self):
        is_pressed = False
        device_guid = self.action_data.hardware_device_guid
        input_id = self.action_data.hardware_input_id
        input_type = self.action_data.get_input_type()
        match input_type:
            case InputType.JoystickHat:
                value = gremlin.joystick_handling.get_hat(device_guid, input_id)
                if value in vjoy.vjoy.Hat.to_continuous_position:
                    hat_position = vjoy.vjoy.Hat.to_continuous_position[value]
                else:
                    hat_position = (0, 0)
                is_pressed = hat_position != (0, 0)
            case InputType.JoystickButton:
                is_pressed = gremlin.joystick_handling.get_button(device_guid, input_id)

        if self.verbose:
            syslog.info(f"\t sync to input : {is_pressed}")
        event = gremlin.event_handler.Event(input_type, input_id, device_guid, value=is_pressed, is_pressed=is_pressed)
        self.process_event(event, is_pressed, extra_data={"virtual": True})

    def profile_stop(self):
        # release anything still pressed to avoid stuck keys / buttons, and wait a moment until it is sent
        self._startup_sync_pending = False
        self._release_all()
        core.Worker.flush(0.3)

    def profile_mode_changed(self, mode: str):
        if self._startup_sync_pending:
            # The runner selects the actual start mode after the start hooks.
            self._startup_sync_pending = False
            profile = gremlin.shared_state.current_profile
            if profile is not None and self.profile_mode in profile.get_mode_ancestors(mode, include_self=True):
                self._sync_input()
            return
        # the release of the input may never reach this action after a mode change: release now
        self._release_all()

    # ------------------------------------------------------------------ events
    def process_event(self, event, value, extra_data=None):
        """handles inbound input event to process"""
        a = self.action_data
        is_pressed = bool(event.is_pressed)
        mode = a.mode

        if mode in (KeyboardOutputMode.Hold, KeyboardOutputMode.AutoRepeat):
            trigger = True  # Hold and Pulse Repeat follow the input itself: start on press, stop on release
        else:
            trigger = (is_pressed and a.exec_on_press) or (not is_pressed and a.exec_on_release)
            if trigger and a.exec_on_release:
                is_pressed = True  # execute on release acts as a press

        if not self._holdable():
            # Focus and return / UI element: every output mode acts as Pulse Single
            if is_pressed and trigger:
                if mode == KeyboardOutputMode.Release and not self._has_output():
                    gremlin.event_handler.EventListener().autorepeat_clear.emit()
                elif self._has_output():
                    self._send(True, True)
            return True

        has_items = bool(a.items)
        if is_pressed:
            if not trigger:
                return True
            match mode:
                case KeyboardOutputMode.Release:
                    if not has_items:
                        # clear autorepeat if no input is provided
                        gremlin.event_handler.EventListener().autorepeat_clear.emit()
                    else:
                        self._toggled = False
                        self._send(False, True)
                case KeyboardOutputMode.Press:
                    if has_items:
                        self._send(True, False)
                case KeyboardOutputMode.Hold:
                    if has_items:
                        self._send(True, False)
                case KeyboardOutputMode.Pulse:
                    if has_items:
                        self.pulse_start(a.delay / 1000, -1)
                case KeyboardOutputMode.Toggle:
                    if has_items:
                        self._toggled = not self._toggled
                        self._send(self._toggled, not self._toggled)
                case KeyboardOutputMode.AutoRepeat:
                    if has_items:
                        self.pulse_start(a.delay / 1000, a.autorepeat_delay / 1000)
        else:
            match mode:
                case KeyboardOutputMode.Hold:
                    if self._down:
                        self._send(False, True)
                case KeyboardOutputMode.AutoRepeat:
                    self.pulse_stop()
        return True


# ============================================================================ action
class MapToApplication(gremlin.input_item.AbstractAction):
    """Action data for Map to Application: keys / mouse buttons for a target application."""

    name = "Map to Application"
    tag = "gex-map-to-application"
    hint = """Send keys or mouse buttons to an application that does not have the focus,
without a focus change (Window) or with a brief focus change (Focus and return)."""

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, True)

    input_types = [  # noqa: RUF012
        InputType.JoystickButton,
        InputType.JoystickHat,
    ]

    functor = MapToApplicationFunctor
    widget = MapToApplicationWidget

    def __init__(self, parent, extra_data: dict | None = None):
        super().__init__(parent, extra_data=extra_data)
        self.parent = parent
        self._items = []  # [(vk, scan, extended) | 'mouse:<name>'] in press order
        self.mode = KeyboardOutputMode.Pulse
        config = gremlin.config.Configuration()
        self._delay = config.last_keyboard_mapper_pulse_value  # delay between make/break in milliseconds
        self._autorepeat_delay = config.last_keyboard_mapper_interval_value  # delay between autorepeats in milliseconds
        self.sync_mode = SyncMode.Ignore
        self.exec_on_press = True
        self.exec_on_release = False
        self.wheel_factor = 1
        self.source = "manual"  # preset = an application preset is chosen in the panel
        self.program = ""
        self.window_title = ""
        self.window_class = ""
        self.delivery = "window"
        self.sim = "Condor.exe"
        self.preset_app = ""
        self.preset_function = ""
        self.function_kind = "key"  # key (keys and/or mouse buttons) | uia
        self.uia_name = ""
        self.click_pos = "mouse"  # mouse = where the mouse is (else the centre) | fixed
        self.click_x = 50.0
        self.click_y = 50.0
        self.click_unit = "%"  # % of the window's client area | px

    # ------------------------------------------------------------------ click position
    @property
    def click(self):
        """fixed click point (x, y, pct) for gex_core, or None (= where the mouse is)"""
        if self.click_pos != "fixed":
            return None
        return (float(self.click_x), float(self.click_y), self.click_unit != "px")

    @click.setter
    def click(self, value):
        if not value:
            self.click_pos = "mouse"
            return
        x, y, pct = value
        self.click_pos, self.click_x, self.click_y, self.click_unit = "fixed", float(x), float(y), "%" if pct else "px"

    # ------------------------------------------------------------------ items
    @property
    def items(self):
        return self._items

    def setItems(self, value):
        self._items = []
        for item in value or []:
            if item is not None and item not in self._items:
                self._items.append(item)
        self.fireIconChanged()

    def removeItem(self, item):
        if item in self._items:
            self._items.remove(item)
            self.fireIconChanged()

    # ------------------------------------------------------------------ timing (as Map to Keyboard/Mouse Ex)
    @property
    def delay(self):
        return self._delay

    @delay.setter
    def delay(self, value):
        value = max(value, 0)
        self._delay = value
        gremlin.config.Configuration().last_keyboard_mapper_pulse_value = value

    @property
    def autorepeat_delay(self):
        return self._autorepeat_delay

    @autorepeat_delay.setter
    def autorepeat_delay(self, value):
        value = max(value, 0)
        self._autorepeat_delay = value
        gremlin.config.Configuration().last_keyboard_mapper_interval_value = value

    # ------------------------------------------------------------------ display
    def _what(self):
        if self.function_kind == "uia" and self.uia_name:
            return f"UI element {self.uia_name}"
        text = " + ".join(item_label(i) for i in self._items) or "N/A"
        if self.click and any(core.is_mouse(i) for i in self._items):
            text += " " + core.click_to_text(self.click)
        return text

    def display_name(self):
        return f"App: {self.program or '?'}: {self._what()} ({DELIVERY_SHORT.get(self.delivery, self.delivery)})"

    def icon(self):
        return "mdi.application"

    def requires_virtual_button(self):
        return self.get_input_type() in [InputType.JoystickAxis, InputType.JoystickHat]

    # ------------------------------------------------------------------ xml
    def _parse_xml(self, node, data=None, extra_data=None):
        mode = node.get("mode", "pulse")
        self.mode = {
            "make": KeyboardOutputMode.Press,
            "press": KeyboardOutputMode.Press,
            "break": KeyboardOutputMode.Release,
            "release": KeyboardOutputMode.Release,
            "both": KeyboardOutputMode.Pulse,
            "pulse": KeyboardOutputMode.Pulse,
            "hold": KeyboardOutputMode.Hold,
            "autorepeat": KeyboardOutputMode.AutoRepeat,
            "toggle": KeyboardOutputMode.Toggle,
        }.get(str(mode).lower(), KeyboardOutputMode.Pulse)
        if "delay" in node.attrib:
            self.delay = _num(node, "delay", int, 250)
        if "interval" in node.attrib:
            self.autorepeat_delay = _num(node, "interval", int, 250)
        try:
            self.sync_mode = SyncMode(_num(node, "sync-mode", int, 0))
        except Exception:  # noqa: BLE001
            self.sync_mode = SyncMode.Ignore
        self.exec_on_press = _bool(node, "exec_on_press", True)
        self.exec_on_release = _bool(node, "exec_on_release", False)
        self.wheel_factor = max(1, _num(node, "wheel-factor", int, 1))

        source = node.get("source", "manual")
        self.source = source if source in ("preset", "manual") else "manual"
        self.program = node.get("program", "")
        self.window_title = node.get("window_title", "")
        self.window_class = node.get("window_class", "")
        self.delivery = core.norm_delivery(node.get("delivery", "window"))
        self.sim = node.get("sim", "Condor.exe")
        self.preset_app = node.get("preset_app", "")
        self.preset_function = node.get("preset_function", "")
        kind = node.get("function_kind", "key")
        self.function_kind = kind if kind in ("key", "uia") else "key"
        self.uia_name = node.get("uia_name", "")
        self.click_pos = "fixed" if node.get("click_pos", "mouse") == "fixed" else "mouse"
        self.click_unit = "px" if node.get("click_unit", "%") == "px" else "%"
        self.click_x = max(0.0, _num(node, "click_x", float, 50.0))
        self.click_y = max(0.0, _num(node, "click_y", float, 50.0))

        items = []
        for child in node:
            tag = getattr(child, "tag", "")
            if tag == "key":
                vk = _num(child, "virtual-code", int, 0)
                if vk > 0:
                    items.append((vk, _num(child, "scan-code", int, 0), _bool(child, "extended", False)))
            elif tag == "mouse":
                item = core.mouse_item(child.get("button", ""))
                if item:
                    items.append(item)
        self._items = []
        self.setItems(items)
        if not items and not (self.function_kind == "uia" and self.uia_name):
            input_item = extra_data.get("input_item", None) if extra_data else None
            syslog.warning(
                f"{core.TAG}: Map to Application: device: [{input_item.device_name if input_item else 'n/a'}] input: "
                f"[{input_item.display_name if input_item else 'n/a'}] no input found in XML.  This action will not do anything."
            )

    def _generate_xml(self):
        node = ElementTree.Element(MapToApplication.tag)
        for k, v in (
            ("mode", self.mode.name.lower()),
            ("delay", str(int(self.delay))),
            ("interval", str(int(self.autorepeat_delay))),
            ("sync-mode", str(int(getattr(self.sync_mode, "value", self.sync_mode)))),
            ("exec_on_press", str(bool(self.exec_on_press))),
            ("exec_on_release", str(bool(self.exec_on_release))),
            ("wheel-factor", str(int(self.wheel_factor))),
            ("source", self.source),
            ("program", self.program),
            ("window_title", self.window_title),
            ("window_class", self.window_class),
            ("delivery", self.delivery),
            ("sim", self.sim),
            ("preset_app", self.preset_app),
            ("preset_function", self.preset_function),
            ("function_kind", self.function_kind),
            ("uia_name", self.uia_name),
            ("click_pos", self.click_pos),
            ("click_x", f"{float(self.click_x):g}"),
            ("click_y", f"{float(self.click_y):g}"),
            ("click_unit", self.click_unit),
        ):
            node.set(k, v or "")
        for item in self._items:
            if core.is_mouse(item):
                child = ElementTree.SubElement(node, "mouse")
                child.set("button", core.mouse_name(item) or "")
            else:
                vk, scan, ext = item
                child = ElementTree.SubElement(node, "key")
                child.set("virtual-code", str(vk))
                child.set("scan-code", str(scan))
                child.set("extended", str(bool(ext)))
                child.set("description", core.items_to_text([item]))
        return node

    def _is_valid(self):
        # return true by default so the action gets saved even if it doesn't do anything
        return True

    def hasOutput(self):
        """true if the action generates an output"""
        return (
            bool(self._items)
            or (self.function_kind == "uia" and bool(self.uia_name))
            or (self.mode == KeyboardOutputMode.Release and (self.exec_on_press or self.exec_on_release))
        )

    def to_html(self) -> str:
        """returns reporting data for this action"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)
        table.addField("Application", html.escape(self.program or "?"))
        table.addField("Delivery", DELIVERY_SHORT.get(self.delivery, self.delivery))
        table.addField("Input", html.escape(self._what()))
        table.addField("Mode", self.mode.name)
        if self.source == "preset" and self.preset_app:
            table.addField("Preset", html.escape(f"{self.preset_app} / {self.preset_function}"))
        match self.mode:
            case KeyboardOutputMode.Pulse:
                table.addField("Delay", f"{self.delay} ms")
            case KeyboardOutputMode.AutoRepeat:
                table.addField("Delay", f"{self.delay} ms")
                table.addField("Repeat Delay", f"{self._autorepeat_delay} ms")
        return table.to_html()


version = 1
name = "gex-map-to-application"
create = MapToApplication
