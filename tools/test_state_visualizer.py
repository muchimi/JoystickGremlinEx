# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
#
# Written for Gremlin Ex by Muchimi
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
"""State viewer checks with real Qt/models and no hardware or config writes.

Run: python tools/test_state_visualizer.py
"""

import _collections_abc
import ast
import collections
from enum import Enum, auto
import inspect
import json
import logging
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Callable
import unittest
from unittest.mock import Mock, patch
import uuid

from PySide6 import QtCore, QtGui, QtWidgets
from psygnal import Signal
from shiboken6 import Shiboken

from test_qt_marshalling import APP, definitions, flush_deletes, invoke


class InputType(Enum):
    State = auto()
    JoystickAxis = auto()
    JoystickButton = auto()
    JoystickHat = auto()


class DeviceType(Enum):
    State = auto()
    Joystick = auto()
    VJoy = auto()
    Maestro = auto()
    Keyboard = auto()
    Midi = auto()
    Osc = auto()


class State:
    changed = Signal(object)
    input_type = InputType.State
    expression = None

    def __init__(self, key, category="default", attributes=()):
        self.key = self.sortKey = self.display_name = key
        self.id = uuid.uuid4()
        self.value = False
        self.category = NS(name=category)
        self.category_name = category
        self.attributes = list(attributes)

    def getAttributes(self):
        return self.attributes


class Profile:
    profile_file = None

    def getDeviceNode(self, guid):
        return NS()


class StateStore:
    crud = Signal()

    def __init__(self):
        self.states = {}

    def getStates(self):
        return self.states

    def toggle(self, key):
        state = self.states[key]
        state.value = not state.value
        state.changed.emit(state)


class Config:
    changed = Signal(str, object)
    input_viewer_button_size = 12
    verbose_mode_state = False

    def verbose_mode_ui_level(self, level):
        return False


class DataButton(QtWidgets.QPushButton):
    def __init__(self, label, data=None, parent=None):
        super().__init__(label, parent)
        self.data = data

    def setCallback(self, callback):
        self.clicked.connect(lambda: callback(self))


class Colors:
    def __getattr__(self, name):
        return lambda *args: "#888888" if not name.startswith("css") else ""


def container(widgets, widget_only=False):
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(widget)
    for child in widgets:
        layout.addWidget(QtWidgets.QLabel(child) if isinstance(child, str) else child)
    return widget if widget_only else (widget, layout)


def clear_layout(layout):
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()


STORE = StateStore()
CONFIG = Config()
BUS = NS(all_inputs_deleted=Mock(), input_deleted=Mock())
SERVICES = NS(
    config=NS(Configuration=lambda: CONFIG),
    shared_state=NS(current_profile=Profile(), master_mode="Master", is_running=False,
                    ui=NS(getRegisteredWidget=Mock(return_value=None))),
    base_profile=NS(Profile=Profile),
    joystick_handling=NS(getDevice=lambda guid: NS(name="States", device_type=DeviceType.State)),
    event_handler=NS(EventListener=lambda: BUS),
    util=NS(InvokeUiMethod=invoke, clear_layout=clear_layout, get_guid=uuid.uuid4),
    ui=NS(ui_common=NS(Color=Colors)),
    input_item=NS(InputItem=State),
)
NAMESPACE = {name: getattr(QtWidgets, name) for name in (
    "QWidget", "QVBoxLayout", "QHBoxLayout", "QLineEdit", "QComboBox", "QPushButton",
    "QMenu", "QScrollArea", "QFrame", "QLabel", "QMessageBox", "QInputDialog",
)}
NAMESPACE.update(
    QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets, Qt=QtCore.Qt, Shiboken=Shiboken,
    Callable=Callable, Signal=Signal, collections=collections, _collections_abc=_collections_abc,
    inspect=inspect, uuid=uuid, os=os, json=json, Path=Path, gremlin=SERVICES,
    InputType=InputType, DeviceType=DeviceType, InputItem=State,
    StateDeviceTabWidget=NS(device_guid="state-device"), StateData=lambda: STORE,
    StateCategory=type("StateCategory", (), {}), Color=Colors,
    Icons=NS(warningIcon=lambda *args: QtGui.QIcon()), QDataPushButton=DataButton,
    QFlowLayout=QtWidgets.QHBoxLayout, QHorizontalLine=QtWidgets.QFrame,
    QWarningWidget=lambda text, icon=None: QtWidgets.QLabel(text),
    getHContainer=container, syslog=logging.getLogger("state-viewer-checks"),
)


class ServiceImports(ast.NodeTransformer):
    def visit_Import(self, node):
        return None if all(alias.name.startswith("gremlin") for alias in node.names) else node


def load(path, names):
    nodes = ast.parse("from __future__ import annotations").body + definitions(path, names)
    module = ServiceImports().visit(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(ast.fix_missing_locations(module), path, "exec"), NAMESPACE)


load("gremlin/util.py", {"TriggerDict"})
load("gremlin/base_classes.py", {"AbstractModel", "AbstractCallbackModel"})
load("gremlin/input_item.py", {"InputItemListModel", "AdvancedInputItemListModel", "FilterChip", "FilterControlWidget"})
SERVICES.input_item.AdvancedInputItemListModel = NAMESPACE["AdvancedInputItemListModel"]
load("gremlin/ui/ui_common.py", {"QDataRadioButton"})
load("gremlin/ui/state_device.py", {
    "StateInputItemModel", "StateFilterCountWidget", "StateFilterWidget", "StateRepeaterButton", "StateVisualizerWidget",
})
SERVICES.ui.state_device = NS(StateData=lambda: STORE)


class StateVisualizerTests(unittest.TestCase):
    def setUp(self):
        STORE.states = {"beta": State("beta", "other"), "alpha": State("alpha", attributes=["tag"])}
        BUS.all_inputs_deleted.reset_mock()
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            if Shiboken.isValid(widget):
                widget._cleanup_ui()
                widget.deleteLater()
        flush_deletes()

    def viewer(self):
        widget = NAMESPACE["StateVisualizerWidget"]()
        self.widgets.append(widget)
        APP.processEvents()
        return widget

    def test_opens_with_no_registered_states_tab(self):
        widget = self.viewer()
        self.assertEqual(list(widget._state_buttons), ["alpha", "beta"])
        self.assertIs(widget._state_buttons["alpha"].data, STORE.states["alpha"])
        self.assertIn("showing 2 of 2", widget._state_filter_widget.count_widget.text())
        BUS.all_inputs_deleted.emit.assert_not_called()

    def test_opens_with_no_main_ui_and_no_states(self):
        STORE.states.clear()
        previous = SERVICES.shared_state.ui
        SERVICES.shared_state.ui = None
        try:
            widget = self.viewer()
        finally:
            SERVICES.shared_state.ui = previous
        self.assertEqual(widget._state_buttons, {})
        self.assertTrue(any(label.text() == "No states available" for label in widget.findChildren(QtWidgets.QLabel)))

    def test_filter_survives_state_add_remove_and_profile_reload(self):
        widget = self.viewer()
        widget._state_filter_widget.search_input.setText("alpha")
        self.assertEqual(list(widget._state_buttons), ["alpha"])
        STORE.states["alpha2"] = State("alpha2")
        STORE.crud.emit()
        self.assertEqual(list(widget._state_buttons), ["alpha", "alpha2"])
        del STORE.states["alpha"]
        STORE.crud.emit()
        self.assertEqual(list(widget._state_buttons), ["alpha2"])
        STORE.states = {"alpha3": State("alpha3")}
        widget.reloadStates()
        self.assertEqual(list(widget._state_buttons), ["alpha3"])
        BUS.all_inputs_deleted.emit.assert_not_called()

    def test_category_and_attribute_filters_are_independent_between_viewers(self):
        first, second = self.viewer(), self.viewer()
        first._state_filter_widget.setCategory("other")
        self.assertEqual(list(first._state_buttons), ["beta"])
        self.assertEqual(list(second._state_buttons), ["alpha", "beta"])
        first._state_filter_widget.setCategory(None)
        first._state_filter_widget.setActiveAttributes(["tag"])
        self.assertEqual(list(first._state_buttons), ["alpha"])

    def test_saved_search_combines_category_search_and_multiple_attributes_on_open(self):
        STORE.states = {
            "panel-ready": State("panel-ready", "Panel", ["Ready", "Live"]),
            "panel-one": State("panel-one", "Panel", ["Ready"]),
            "panel-other": State("panel-other", "Other", ["Ready", "Live"]),
            "elsewhere": State("elsewhere", "Panel", ["Ready", "Live"]),
        }
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder, "profile.xml")
            profile.touch()
            preset = {"search": "panel", "category": "Panel", "attributes": ["Ready", "Live"]}
            Path(folder, "profile.filters.json").write_text(json.dumps({
                "version": 2, "selected": "Panel", "presets": {"Panel": preset},
            }), encoding="utf-8")
            def swapext(path, ext, suffix):
                return str(Path(path).with_suffix(suffix + ext))

            with patch.object(SERVICES.shared_state.current_profile, "profile_file", str(profile)):
                with patch.object(SERVICES.util, "swapext", swapext, create=True):
                    widget = self.viewer()
            self.assertEqual(list(widget._state_buttons), ["panel-ready"])
            self.assertIn("showing 1 of 4", widget._state_filter_widget.count_widget.text())

    def test_attribute_and_category_choices_refresh_without_clearing_other_filters(self):
        STORE.states["alpha"] = State("alpha", "Panel", ["tag", "live"])
        STORE.states["alpha2"] = State("alpha2", "Panel", ["tag"])
        STORE.states["alpha3"] = State("alpha3", "Other", ["tag", "live"])
        widget = self.viewer()
        filters = widget._state_filter_widget
        filters.setFilterOptions({"category": "Panel", "attributes": ["tag", "live"]})
        self.assertEqual(list(widget._state_buttons), ["alpha"])

        STORE.states["new"] = State("new", "Panel", ["tag", "live", "new"])
        STORE.crud.emit()
        self.assertEqual(list(widget._state_buttons), ["alpha", "new"])
        self.assertIn("new", filters.attribute_actions)
        filters.attribute_actions["new"].setChecked(True)
        self.assertEqual(list(widget._state_buttons), ["new"])
        self.assertEqual(filters.getFilterOptions()["category"], "Panel")

    def test_button_toggle_and_external_state_changes_stay_live_after_refresh(self):
        widget = self.viewer()
        for _ in range(3):
            widget.reloadStates()
        widget._state_buttons["alpha"].click()
        self.assertTrue(STORE.states["alpha"].value)
        self.assertTrue(widget._state_buttons["alpha"].isChecked())
        STORE.toggle("alpha")
        self.assertFalse(widget._state_buttons["alpha"].isChecked())

    def test_cleanup_disconnects_callbacks_before_reopening(self):
        widget = self.viewer()
        state = STORE.states["alpha"]
        self.assertEqual(len(state.changed), 1)
        model = widget.model
        widget._cleanup_ui()
        self.assertIsNone(widget.model)
        self.assertIsNone(widget._state_filter_widget.model)
        self.assertIsNone(widget._state_filter_widget.count_widget._model)
        self.widgets.remove(widget)
        self.assertEqual(len(state.changed), 0)
        self.assertEqual(len(STORE.crud), 0)
        self.assertEqual(len(CONFIG.changed), 0)
        self.assertEqual(model._data_changed_callbacks, [])
        widget.deleteLater()
        flush_deletes()
        STORE.crud.emit()
        CONFIG.changed.emit("input_viewer_button_size", 12)
        reopened = self.viewer()
        self.assertEqual(list(reopened._state_buttons), ["alpha", "beta"])


if __name__ == "__main__":
    unittest.main()
