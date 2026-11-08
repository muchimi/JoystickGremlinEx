"""Real Qt splitter lifetime checks: python tools/test_split_tab_lifetime.py."""

import ast
from types import SimpleNamespace as NS
from typing import Callable
import unittest
from unittest.mock import patch

from PySide6 import QtCore, QtWidgets
from shiboken6 import Shiboken

from test_qt_marshalling import APP, definitions, flush_deletes


def vertical_container(widgets=None, widget_only=False):
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(widget)
    for child in widgets or []:
        if child != "||":
            layout.addWidget(child)
    return widget if widget_only else (widget, layout)


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()


UTIL = dict(QtWidgets=QtWidgets)
exec(compile(ast.Module(body=definitions("gremlin/util.py", {
    "clear_widget_references",
}), type_ignores=[]), "gremlin/util.py", "exec"), UTIL)
SERVICES = NS(
    util=NS(get_guid=lambda: "tab", normalize_guid=str, clear_layout=clear_layout,
            clear_widget_references=UTIL["clear_widget_references"]),
    ui=NS(ui_common=NS(Color=lambda: NS(cssTabContent=lambda: ""))),
)
NAMESPACE = dict(QtCore=QtCore, QtWidgets=QtWidgets, QWidget=QtWidgets.QWidget,
                 Shiboken=Shiboken, Callable=Callable, gremlin=SERVICES,
                 getVContainer=vertical_container, QEmptyWidget=QtWidgets.QWidget)
exec(compile(ast.Module(body=definitions("gremlin/ui/ui_common.py", {
    "QDataWidget", "QContentWidget", "QSplitTabWidget",
}), type_ignores=[]), "gremlin/ui/ui_common.py", "exec"), NAMESPACE)


class SplitTab(NAMESPACE["QSplitTabWidget"]):
    # The widget registry uses profile/device services unrelated to resizing.
    def _blank_input(self):
        pass

    def unregisterAllWidgets(self):
        pass


class SplitTabLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.tab = SplitTab("split-tab-test", "device")
        self.tab._share_splitter_sizes = False

    def tearDown(self):
        if Shiboken.isValid(self.tab):
            self.tab.deleteLater()
        flush_deletes()

    def test_live_resize_preserves_the_remembered_proportions(self):
        self.tab._last_sizes = [250, 750]
        self.tab._handle_content_resized(1200, 600)
        self.assertEqual(self.tab._splitter.size(), QtCore.QSize(1200, 600))
        self.assertEqual(self.tab._last_sizes, [300, 900])

    def test_resize_queued_before_cleanup_is_harmless_at_delivery(self):
        content = self.tab._content_widget
        content.resized.connect(self.tab._handle_content_resized, QtCore.Qt.ConnectionType.QueuedConnection)
        content.resized.emit(1000, 500)
        self.tab._cleanup_ui()
        self.assertIsNone(self.tab._splitter)
        with patch("sys.excepthook") as uncaught:
            APP.processEvents()
        uncaught.assert_not_called()

    def test_sizing_callbacks_after_cleanup_are_harmless(self):
        self.tab._cleanup_ui()
        self.tab._cleanup_ui()  # cleanup remains idempotent
        self.tab._handle_content_resized(1000, 500)
        self.tab._splitter_moved(-1, 1)
        self.tab._apply_splitter_sizes()

    def test_sizing_callbacks_skip_a_missing_splitter(self):
        self.tab._splitter = None
        self.tab._handle_content_resized(1000, 500)
        self.tab._splitter_moved(-1, 1)
        self.tab._apply_splitter_sizes()

    def test_sizing_callbacks_skip_a_deleted_qt_splitter(self):
        Shiboken.delete(self.tab._splitter)
        self.tab._handle_content_resized(1000, 500)
        self.tab._splitter_moved(-1, 1)
        self.tab._apply_splitter_sizes()


if __name__ == "__main__":
    unittest.main()
