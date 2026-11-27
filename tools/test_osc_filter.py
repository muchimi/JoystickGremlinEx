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
"""OSC filtering/pagination checks with real Qt and no device services.

Run: python tools/test_osc_filter.py
Production model, filter controls and pagination methods are loaded in isolation.
"""

import ast
import collections
import fnmatch
import logging
from types import SimpleNamespace as NS
from typing import Callable
import unittest
from unittest.mock import Mock, patch
import uuid

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

from test_qt_marshalling import APP, definitions, flush_deletes, invoke


class ServiceImports(ast.NodeTransformer):
    def visit_Import(self, node):
        return None if all(alias.name.startswith("gremlin") for alias in node.names) else node


def load(path, names, members=None, base=None):
    nodes = definitions(path, names)
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            if members is not None:
                node.body = [member for member in node.body if getattr(member, "name", None) in members]
            if base:
                node.bases = [ast.Name(id=base, ctx=ast.Load())]
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(ServiceImports().visit(module)), path, "exec"), NAMESPACE)


def container(widgets, widget_only=False):
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(widget)
    for child in widgets if isinstance(widgets, list) else [widgets]:
        if child != "||":
            layout.addWidget(child)
    return widget if widget_only else (widget, layout)


class Button(QtWidgets.QPushButton):
    def __init__(self, text="", callback=None, data=None, **kwargs):
        super().__init__(text)
        self.data = data
        if callback:
            self.clicked.connect(lambda: callback(self) if data is not None else callback())

    def setUsed(self, used):
        self.used = used


class LineEdit(QtWidgets.QLineEdit):
    enterPressed = QtCore.Signal()

    def __init__(self, text="", tooltip=None):
        super().__init__(text)


CONFIG = NS(osc_filter="", device_page_size=16, verbose_mode_osc=False,
            verbose_mode_ui_level=lambda level: False)
SERVICES = NS(
    config=NS(Configuration=lambda: CONFIG),
    shared_state=NS(is_running=False, is_redraw_suspended=lambda: False),
    util=NS(get_uuid=uuid.uuid4, is_ui_thread=lambda: True, InvokeUiMethod=invoke,
            clear_widget_references=lambda widget: None),
    worker=NS(WorkManager=lambda: NS(pushCursor=lambda: None, popCursor=lambda: None)),
    event_handler=NS(EventListener=lambda: NS(device_mapping_changed=NS(emit=lambda *args: None))),
    ui=NS(ui_common=NS(QDataLineEdit=LineEdit, getHContainer=container,
                       Buttons=NS(getSearchWidget=Button, getClearWidget=Button))),
)
NAMESPACE = dict(QtCore=QtCore, QtWidgets=QtWidgets, Shiboken=Shiboken,
                 Signal=QtCore.Signal, Callable=Callable, uuid=uuid,
                 collections=collections, gremlin=SERVICES, fnmatch=fnmatch,
                 syslog=logging.getLogger("osc-filter-checks"),
                 QIconPushButton=Button, QUsedPushButton=Button, getHContainer=container,
                 QDataLineEdit=LineEdit, Buttons=SERVICES.ui.ui_common.Buttons,
                 Icons=NS(**{name: QtGui.QIcon for name in (
                     "arrowFirst", "arrowPrevious", "arrowNext", "arrowLast")}))
load("gremlin/util.py", {"TriggerDict", "decorate_filter"})
SERVICES.util.decorate_filter = NAMESPACE["decorate_filter"]
load("gremlin/base_classes.py", {"AbstractModel", "AbstractCallbackModel"})
Model = NAMESPACE["AbstractCallbackModel"]
NAMESPACE["OscInputItemModel"] = Model
load("gremlin/input_item.py", {"AbstractView", "AbstractPaginatedView", "PaginationWidget"})
load("gremlin/input_item.py", {"InputItemListView"}, {
    "_item_count", "count", "unfilteredCount", "redraw", "_redraw_ui",
    "_apply_pending_selection_page", "getInputItemWidgetCount",
})
load("gremlin/ui/osc_device.py", {"OscDeviceTabWidget"}, {
    "_filter_data", "_filter_changed", "revealFilteredInput",
}, base="object")
load("gremlin/ui/osc_device.py", {"OscFilterWidget"})


class Input:
    def __init__(self, message):
        self.guid = uuid.uuid4()
        self.input_id = NS(message=message)


class View(NAMESPACE["InputItemListView"]):
    """Use lightweight rows while exercising the production refresh path."""

    def __init__(self, model):
        super().__init__(model=model, page_size=16)
        self.filter = model.DEFAULT_FILTER
        self._model_hash = None
        self._redraw_force = self._redraw_lock = False
        self._requested_selected_index = self._redraw_selected_index = -1
        self._current_index = 0
        self._device = NS(device_id="osc")
        self._widget_map = {}

    def create_ui(self):
        start, end = self.pageRange()
        self._widget_map = dict(list(self.model.getFilteredMap(self.filter))[start:end])

    def widget(self, index):
        return None

    @property
    def current_index(self):
        return self._current_index

    def showBlank(self):
        self.blank = True

    def showContent(self):
        self.blank = False


class OscFilterTests(unittest.TestCase):
    def setUp(self):
        CONFIG.osc_filter = ""
        self.tab = NAMESPACE["OscDeviceTabWidget"]()
        self.tab._filter = ""
        self.tab._revealed_input_guids = set()
        self.model = Model(model_description="OSC filter test", filter_callback=self.tab._filter_data)
        inputs = [Input(f"/match/{index}") for index in range(19)]
        inputs.extend(Input(f"/other/{index}") for index in range(51))
        self.model._index_map = NAMESPACE["TriggerDict"].copyFrom(dict(enumerate(inputs)))
        self.model._item_map = NAMESPACE["TriggerDict"].copyFrom({item: i for i, item in enumerate(inputs)})
        self.model.applyFilter()
        self.tab.inputItemListModel = self.model
        self.controls = NAMESPACE["OscFilterWidget"](self.model)
        self.tab._filter_widget = self.controls
        self.controls.changed.connect(self.tab._filter_changed)
        self.view = View(self.model)
        self.view.redraw(force=True)
        self.pages = NAMESPACE["PaginationWidget"](self.view)

    def tearDown(self):
        self.controls._cleanup_ui()
        self.pages._cleanup_ui()
        self.view._cleanup_ui()
        for widget in (self.pages, self.controls, self.view):
            widget.deleteLater()
        flush_deletes()

    def apply_filter(self, text):
        self.controls._filter_widget.setText(text)
        self.controls._apply_filter()
        APP.processEvents()

    def test_filter_from_last_page_clamps_page_and_displays_remaining_matches(self):
        self.view.setPage(4)
        self.apply_filter("match")
        self.assertEqual((self.model.count(), self.view.page_count, self.view.page_index), (19, 2, 1))
        self.assertEqual(list(self.view._widget_map), [16, 17, 18])
        self.assertEqual(self.pages._label.text(), "2 / 2")
        self.assertIn("19 of 70 OSC inputs", self.controls._count_widget.text())
        self.assertIn("Total items 19 (unfiltered: 70)", self.pages._label.toolTip())
        self.assertFalse(self.pages._next_button.isEnabled())

    def test_pagination_total_counts_all_matches_instead_of_current_page_rows(self):
        self.assertEqual(self.view.count(), 16)
        self.assertIn("Total items 70", self.pages._label.toolTip())
        self.apply_filter("match")
        self.assertEqual(self.view.count(), 16)
        self.assertIn("Total items 19", self.pages._label.toolTip())

    def test_no_matches_shows_empty_view_and_single_valid_page(self):
        self.view.setPage(4)
        self.apply_filter("missing")
        self.assertEqual((self.view.page_count, self.view.page_index, self.view.pageRange()), (1, 0, (0, 0)))
        self.assertEqual(self.view.count(), 0)
        self.assertTrue(self.view.blank)
        self.assertEqual(self.pages._label.text(), "1 / 1")
        self.assertTrue(self.pages._paginator_widget.isHidden())
        self.assertIn("0 of 70 OSC inputs", self.controls._count_widget.text())

    def test_clearing_filter_restores_inputs_and_pages(self):
        self.apply_filter("missing")
        self.controls.clearFilter()
        self.assertEqual((self.model.count(), self.view.page_count, self.view.count()), (70, 5, 16))
        self.assertFalse(self.view.blank)
        self.assertIn("70 OSC inputs", self.controls._count_widget.text())
        self.assertIn("Total items 70", self.pages._label.toolTip())

    def test_revealing_one_input_keeps_the_filter_and_other_rows_hidden(self):
        self.apply_filter("match")
        target, other = list(self.model.getUnfilteredItems())[-2:]
        self.assertEqual(self.model.indexOf(target), -1)

        index = self.tab.revealFilteredInput(target)
        self.assertEqual(index, 19)
        self.assertIs(self.model.filteredItemAt(index), target)
        self.assertEqual(self.model.indexOf(other), -1)
        self.assertEqual(self.controls.filter, "match")
        self.assertIn("20 of 70 OSC inputs", self.controls._count_widget.text())

        self.model.applyFilter()
        self.assertEqual(self.model.indexOf(target), index)
        self.apply_filter("match")
        self.assertEqual(self.model.indexOf(target), -1)

    def test_revealing_an_input_when_the_filter_matches_nothing(self):
        self.apply_filter("missing")
        target = list(self.model.getUnfilteredItems())[-1]

        self.assertEqual(self.tab.revealFilteredInput(target), 0)
        self.assertIs(self.view._widget_map[0], target)
        self.assertFalse(self.view.blank)

    def test_disabled_pagination_renders_every_match(self):
        self.view.setPageSize(0)
        self.apply_filter("match")
        self.assertEqual((self.view.page_count, self.view.count()), (1, 19))
        self.assertEqual(self.view.pageRange(), (0, 19))

    def test_model_changes_refresh_osc_input_count(self):
        self.model._index_map.clear()
        self.model._item_map.clear()
        self.model.applyFilter()
        self.assertEqual(self.controls._count_widget.text(), "<i>(no inputs found)</i>")


class DeviceModelLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        NAMESPACE["SingletonDecorator"] = lambda kind: kind
        load("gremlin/ui/osc_device.py", {"OscData"})
        cls.OscData = NAMESPACE["OscData"]
        NAMESPACE["CleanupBase"] = type("CleanupBase", (), {"_cleanup_ui": lambda self: None})
        load("gremlin/input_item.py", {"BaseDeviceTabWidget"},
             {"_cleanup_ui", "setInputItemListModel", "onInputItemChange"}, base="CleanupBase")
        cls.DeviceTab = NAMESPACE["BaseDeviceTabWidget"]
        cls.device_tabs = []
        for filename, name in (("mode_device.py", "ModeDeviceTabWidget"),
                               ("keyboard_device.py", "KeyboardDeviceTabWidget"),
                               ("midi_device.py", "MidiDeviceTabWidget")):
            load("gremlin/ui/" + filename, {name}, {"_cleanup_ui"}, base="BaseDeviceTabWidget")
            cls.device_tabs.append(NAMESPACE[name])

    def test_shared_device_cleanup_detaches_model_and_aliases_before_disposal(self):
        cases = [(self.DeviceTab, alias) for alias in (None, "model", "_model")]
        cases.extend((kind, None) for kind in self.device_tabs)
        for kind, alias in cases:
            with self.subTest(device=kind.__name__, alias=alias):
                model = Model(model_description="device lifetime")
                tab = kind()
                tab.widget_storage = {"old": object()}
                events = Mock()
                tab._input_item_list_model = model
                tab._input_item_list_view = Mock()
                view = tab._input_item_list_view
                tab.main_layout = None
                tab._registered_callbacks = {}
                for name in ("_handle_lock_inputs", "_handle_unlock_inputs", "_handle_tab_changed",
                             "_handle_input_deleted", "_handle_input_filter_changed", "_handle_all_inputs_deleted",
                             "_handle_jump_to_mapped_input", "_handle_device_mapping_changed", "setInputItemListView",
                             "_handle_new_profile", "_handle_profile_mode_changed", "_mode_name_changed",
                             "_config_changed_cb", "_handle_edit_mode_changed"):
                    setattr(tab, name, Mock())
                if alias:
                    setattr(tab, alias, model)
                dispose_model = model.dispose
                def disposed():
                    self.assertIsNone(tab._input_item_list_model)
                    if alias:
                        self.assertIsNone(getattr(tab, alias))
                    view.setModel.assert_called_once_with(None)
                    if kind.__name__ == "ModeDeviceTabWidget":
                        events.edit_mode_changed.disconnect.assert_called_once_with(tab._handle_profile_mode_changed)
                    elif kind.__name__ in ("KeyboardDeviceTabWidget", "MidiDeviceTabWidget"):
                        events.edit_mode_changed.disconnect.assert_called_once_with(tab._handle_edit_mode_changed)
                    dispose_model()
                with patch.object(model, "dispose", side_effect=disposed) as dispose, patch.object(
                    SERVICES.event_handler, "EventListener", return_value=events
                ), patch.object(SERVICES.util, "clear_layout", create=True), patch.dict(
                    NAMESPACE, Shiboken=NS(isValid=lambda widget: False)
                ):
                    tab._cleanup_ui()
                dispose.assert_called_once_with()
                self.assertEqual(model._filtered_index_map, {})
                if kind.__name__ == "ModeDeviceTabWidget":
                    self.assertEqual(tab.widget_storage, {})
                    events.edit_mode_changed.disconnect.assert_called_once_with(tab._handle_profile_mode_changed)
                elif kind.__name__ in ("KeyboardDeviceTabWidget", "MidiDeviceTabWidget"):
                    events.edit_mode_changed.disconnect.assert_called_once_with(tab._handle_edit_mode_changed)

    def test_osc_registration_detaches_before_disposal_and_preserves_new_owner(self):
        data = self.OscData()
        old = Model(model_description="old OSC")
        new = Model(model_description="new OSC")
        data.setModel(old)
        data.clearModel(old)
        old.dispose()
        self.assertIsNone(data.model)
        self.assertIsNone(data.getOsc("saved-input"))
        data.setModel(new)
        data.clearModel(old)
        self.assertIs(data.model, new)
        data.clearModel(new)
        new.dispose()

    def test_osc_saved_input_lookup_ignores_display_filter(self):
        model = Model(model_description="OSC lookup", filter_callback=lambda item, filter: False)
        item = Input("/saved")
        item.id = "saved-input"
        model._index_map[0] = item
        model._item_map[item] = 0
        model.applyFilter()
        self.assertEqual(model.rowCount(), 0)
        data = self.OscData()
        data.setModel(model)
        self.assertIs(data.getOsc(item.id), item)
        data.clearModel(model)
        model.dispose()


if __name__ == "__main__":
    unittest.main()
