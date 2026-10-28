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
    "_filter_data", "_filter_changed",
}, base="object")
load("gremlin/ui/osc_device.py", {"OscFilterWidget"})


class Input:
    def __init__(self, message):
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


if __name__ == "__main__":
    unittest.main()
