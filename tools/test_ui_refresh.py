"""UI refresh/lifetime checks with real Qt and fake device/profile services.

Run: python tools/test_ui_refresh.py
Production methods are loaded without starting Gremlin or accessing hardware.
"""

import ast
from enum import IntEnum
import logging
import os
from pathlib import Path
import tempfile
import threading
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from PySide6 import QtCore, QtWidgets
from shiboken6 import Shiboken

from test_qt_marshalling import APP, UTIL, flush_deletes, invoke, pump_until


ROOT = Path(__file__).resolve().parents[1]
CONFIG = NS(verbose_mode_ui_level=lambda level: False)
CLIPBOARD = NS(disable=Mock(), enable=Mock())


def vertical_container(widgets=None, widget_only=False):
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(widget)
    if widgets is not None:
        for child in widgets if isinstance(widgets, list) else [widgets]:
            if child != "||":
                layout.addWidget(QtWidgets.QLabel(child) if isinstance(child, str) else child)
    return widget if widget_only else (widget, layout)


def delete_widget(widget):
    if Shiboken.isValid(widget):
        widget.hide()
        widget.deleteLater()


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            delete_widget(item.widget())


class LoadingHolder(QtWidgets.QWidget):
    def __init__(self, mode="empty"):
        super().__init__()
        self.mode = mode
        self.paints = 0
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Loading..." if mode == "wait" else "Empty"))

    def paintEvent(self, event):
        self.paints += 1
        super().paintEvent(event)


SERVICES = NS(
    util=NS(InvokeUiMethod=invoke, is_ui_thread=UTIL["is_ui_thread"],
            assert_ui_thread=lambda: None, hold_cyclic_gc=lambda method: method,
            delete_widget=delete_widget, clear_layout=clear_layout,
            compare_guid=lambda a, b: a == b, singleShot=lambda callback: QtCore.QTimer.singleShot(0, callback),
            get_ext=lambda path: Path(path).suffix, swap_ext=lambda path, ext: f"{path}.{ext}"),
    config=NS(Configuration=lambda: CONFIG), clipboard=NS(Clipboard=lambda: CLIPBOARD),
    shared_state=NS(profile_loading=False, current_profile=object(), current_mode="Default", is_running=False),
    ui=NS(ui_common=NS(getVContainer=vertical_container, QEmptyWidget=LoadingHolder,
                       QHorizontalLine=QtWidgets.QFrame)),
)


class ImportsFromServices(ast.NodeTransformer):
    def visit_Import(self, node):
        return None if all(alias.name.startswith("gremlin") for alias in node.names) else node

    def visit_ImportFrom(self, node):
        return None if node.module and node.module.startswith("gremlin") else node


def load_methods(path, class_name, names, **extra):
    source = next(node for node in ast.parse((ROOT / path).read_bytes()).body
                  if isinstance(node, ast.ClassDef) and node.name == class_name)
    methods = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    missing = names - {node.name for node in methods}
    assert not missing, missing
    source.bases = [ast.Attribute(value=ast.Name(id="QtWidgets", ctx=ast.Load()), attr="QWidget", ctx=ast.Load())]
    source.decorator_list = []
    source.body = methods
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), source], type_ignores=[])
    module = ImportsFromServices().visit(module)
    namespace = dict(gremlin=SERVICES, QtWidgets=QtWidgets, QtCore=QtCore, Shiboken=Shiboken,
                     QTimer=QtCore.QTimer, syslog=logging.getLogger("ui-refresh-checks"),
                     with_wait_cursor=lambda method: method,
                     os=os, _trace=lambda message: None, **extra)
    exec(compile(ast.fix_missing_locations(module), str(ROOT / path), "exec"), namespace)
    return namespace[class_name]


WORK = NS(submit=Mock(), pushCursor=Mock(), popCursor=Mock())


class StartupDeviceTab(QtWidgets.QWidget):
    """A real input list whose saved ids can exist before its rows do."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.inputs = QtWidgets.QListWidget(self)
        self.loaded = False

    def isLoaded(self):
        return self.loaded

    @property
    def inputWidgetCount(self):
        return self.inputs.count()

    @property
    def inputItemListView(self):
        return self.inputs

    def getSelectedInputItem(self):
        row = self.inputs.currentItem()
        return row.data(QtCore.Qt.ItemDataRole.UserRole) if row is not None else None

    def select_input(self, device_guid, input_type, input_id, **kwargs):
        self.loaded = True
        row = QtWidgets.QListWidgetItem(f"Input {input_id}")
        row.setData(QtCore.Qt.ItemDataRole.UserRole, NS(
            device_guid=device_guid, input_type=input_type, input_id=input_id,
        ))
        self.inputs.addItem(row)
        self.inputs.setCurrentItem(row)


MainWindow = load_methods("gremlinEx.py", "GremlinUi", {
    "refresh", "_create_tabs", "_request_tabs_rebuild_ui", "_arm_tabs_rebuild_timer", "_flush_tabs_rebuild",
    "_refresh_ui", "_enable_ui_after_refresh_ui", "isProfileLoading", "pushProfileLoading", "popProfileLoading",
    "_profile_load_completed", "_profile_load_completed_ui", "_do_load_profile", "_do_load_profile_ui",
    "_do_load_profile_internal_worker",
    "_profile_stop_ui", "_apply_startup_input_restore", "_startup_input_is_ready",
    "_schedule_startup_input_restore",
    "pushSuspendTabUpdate", "popSuspendTabUpdate",
    "_begin_ui_refresh_ui", "_finish_ui_refresh_ui",
    "_unregister_all_widgets_ui", "registerWidget", "_select_input", "_tab_selected_worker", "_tab_selection_complete",
}, WorkManager=lambda: WORK, sys=sys, QThread=QtCore.QThread, BaseDeviceTabWidget=StartupDeviceTab)


def main_window():
    ui = MainWindow()
    ui._creating_tabs = ui._tabs_rebuild_pending = ui._tabs_rebuild_refresh = False
    ui._suspend_ui_update = 0
    ui._ui_update_pending = False
    ui._ui_enable_after_refresh = False
    ui._tabs_rebuild_timer = None
    ui._ui_refresh_cursor = False
    ui._startup_restore_target = None
    ui._profile_loading_stack = 0
    ui._pending_profile_load = None
    ui.mode_selector = NS(populate_selector=Mock())
    ui._create_tabs_ui = Mock()
    ui._select_input = Mock()
    ui.getRegisteredWidget = Mock(return_value=None)
    ui.getActiveTabDeviceGuid = Mock(return_value="device")
    ui._refresh_tab = Mock()
    ui.setUIState = Mock()
    ui._update_status_bar_active = Mock()
    ui._update_highlight_toolbar_enabled = Mock()
    ui.ui = NS(tab_content_widget=QtWidgets.QWidget(ui))
    ui.ui_statusbar_highlight_container_widget = QtWidgets.QWidget(ui)
    ui._activate_ui = Mock()
    ui._reset_tab_data = Mock()
    ui._unregister_all_widgets_ui = Mock()
    ui.clearWidgets = Mock()
    ui._do_load_profile_internal_worker = Mock()
    return ui


class MainRefreshTests(unittest.TestCase):
    def setUp(self):
        SERVICES.shared_state.profile_loading = SERVICES.shared_state.is_running = False
        WORK.submit.reset_mock()
        self.ui = main_window()

    def tearDown(self):
        self.ui.deleteLater()
        flush_deletes()

    def test_refresh_burst_builds_once_without_second_selection(self):
        for _ in range(25):
            self.ui.refresh()
            self.ui._create_tabs()
        self.ui._create_tabs_ui.assert_not_called()
        pump_until(lambda: self.ui._create_tabs_ui.call_count == 1)
        self.ui.mode_selector.populate_selector.assert_called_once()
        self.ui._select_input.assert_not_called()
        APP.processEvents()
        self.ui._create_tabs_ui.assert_called_once()

    def test_loading_holder_survives_cleanup_and_reserves_index_zero(self):
        stack = QtWidgets.QStackedWidget(self.ui)
        stack.resize(300, 200)
        self.ui.ui.device_page_widget = stack
        holder = LoadingHolder(mode="wait")
        self.ui.ui.device_loading_widget = holder
        pages = [QtWidgets.QWidget(), QtWidgets.QWidget()]
        for page in [holder, *pages]:
            stack.addWidget(page)
        stack.setCurrentWidget(pages[-1])
        self.ui._widget_device_index_map = {"first": 1, "second": 2}
        self.ui._widget_index_device_map = {1: "first", 2: "second"}
        self.ui.show()
        stack.show()
        APP.processEvents()
        queued = []
        QtCore.QTimer.singleShot(0, lambda: queued.append("callback"))
        MainWindow._unregister_all_widgets_ui(self.ui)
        self.assertIs(stack.currentWidget(), holder)
        self.assertEqual(stack.count(), 1)
        self.assertGreater(holder.paints, 0)
        self.assertEqual(queued, [])  # repaint must not run queued work recursively
        flush_deletes()
        self.assertTrue(Shiboken.isValid(holder))
        self.assertTrue(all(not Shiboken.isValid(page) for page in pages))
        # Profile preparation and the subsequent tab build both perform cleanup.
        MainWindow._unregister_all_widgets_ui(self.ui)
        SERVICES.util.normalize_guid = lambda value: value
        self.ui._get_device_name = lambda value: value
        new_page = QtWidgets.QWidget()
        index = MainWindow.registerWidget(self.ui, "new-device", new_page)
        self.assertEqual(index, 1)
        self.assertIs(stack.widget(0), holder)

    def test_missing_loading_holder_is_recreated_before_device_pages(self):
        stack = QtWidgets.QStackedWidget(self.ui)
        self.ui.ui.device_page_widget = stack
        self.ui._widget_device_index_map = {}
        self.ui._widget_index_device_map = {}
        MainWindow._unregister_all_widgets_ui(self.ui)
        holder = self.ui.ui.device_loading_widget
        self.assertEqual(holder.mode, "wait")
        self.assertIs(stack.widget(0), holder)
        self.assertIs(stack.currentWidget(), holder)

    def test_worker_requests_are_coalesced_on_gui(self):
        threads = []
        self.ui._create_tabs_ui.side_effect = lambda: threads.append(QtCore.QThread.isMainThread())
        worker = threading.Thread(target=lambda: [self.ui.refresh() for _ in range(25)])
        worker.start()
        worker.join()
        pump_until(lambda: bool(threads))
        self.assertEqual(threads, [True])

    def test_suspended_refresh_waits_without_arming_timer(self):
        self.ui.pushSuspendTabUpdate()
        self.ui.refresh()
        self.assertIsNone(self.ui._tabs_rebuild_timer)
        self.ui.popSuspendTabUpdate()
        pump_until(lambda: self.ui._create_tabs_ui.called)
        self.ui._create_tabs_ui.assert_called_once()

    def test_request_during_build_is_not_lost(self):
        def build():
            if self.ui._create_tabs_ui.call_count == 1:
                self.ui._create_tabs()

        self.ui._create_tabs_ui.side_effect = build
        self.ui.refresh()
        pump_until(lambda: self.ui._create_tabs_ui.call_count == 2)
        APP.processEvents()
        self.assertEqual(self.ui._create_tabs_ui.call_count, 2)

    def test_load_defers_all_rebuilds_until_gui_completion(self):
        self.ui.pushProfileLoading()
        for _ in range(10):
            self.ui.refresh()
        APP.processEvents()
        self.ui._create_tabs_ui.assert_not_called()
        worker = threading.Thread(target=self.ui._profile_load_completed)
        worker.start()
        worker.join()
        self.assertTrue(self.ui.isProfileLoading())
        pump_until(lambda: self.ui._create_tabs_ui.call_count == 1)
        self.assertFalse(self.ui.isProfileLoading())
        self.ui.mode_selector.populate_selector.assert_called_once()

    def test_stop_updates_visible_tab_without_rebuilding(self):
        self.ui._ui_enable_after_refresh = True
        self.ui._profile_stop_ui()
        self.ui._refresh_tab.assert_called_once()
        self.ui._create_tabs_ui.assert_not_called()
        self.ui.setUIState.assert_called_once_with(True)

    def test_stop_during_load_preserves_disabled_ui(self):
        self.ui.pushProfileLoading()
        self.ui._ui_enable_after_refresh = True
        self.ui.ui.tab_content_widget.setEnabled(False)
        self.ui._profile_stop_ui()
        self.ui._refresh_tab.assert_not_called()
        self.ui.setUIState.assert_not_called()
        self.assertFalse(self.ui.ui.tab_content_widget.isEnabled())

    def test_satisfied_selection_restore_does_no_work(self):
        tab = StartupDeviceTab(self.ui)
        tab.select_input("device", "button", 3)
        self.ui.getRegisteredWidget.return_value = tab
        self.ui._startup_restore_target = ("device", "button", 3)
        self.ui._last_selected_device_guid, self.ui._last_selected_input_type, self.ui._last_selected_input_id = self.ui._startup_restore_target
        self.ui._apply_startup_input_restore(0)
        self.ui._select_input.assert_not_called()
        self.assertIsNone(self.ui._startup_restore_target)

    def test_initial_tab_with_saved_ids_but_empty_inputs_is_populated(self):
        tab = StartupDeviceTab(self.ui)
        self.ui.getRegisteredWidget.return_value = tab
        self.ui._startup_restore_target = ("device", "button", 3)
        self.ui._last_selected_device_guid, self.ui._last_selected_input_type, self.ui._last_selected_input_id = self.ui._startup_restore_target
        self.ui._select_input.side_effect = tab.select_input
        self.ui._apply_startup_input_restore(0)
        self.assertEqual(tab.inputWidgetCount, 1)
        self.assertEqual(tab.getSelectedInputItem().input_id, 3)
        self.ui._select_input.assert_called_once_with(
            device_guid="device", input_type="button", input_id=3,
            force_update=True, force_switch=True, tab_changed=True,
            extra_data={"source": "startup_restore_retry"},
        )
        self.assertIsNone(self.ui._startup_restore_target)

    def test_startup_restore_waits_for_input_rows_to_be_ready(self):
        tab = StartupDeviceTab(self.ui)
        self.ui.getRegisteredWidget.return_value = tab
        target = ("device", "button", 3)
        self.ui._startup_restore_target = target
        self.ui._last_selected_device_guid, self.ui._last_selected_input_type, self.ui._last_selected_input_id = target
        self.ui._apply_startup_input_restore(0)
        self.assertEqual(self.ui._startup_restore_target, target)
        self.ui._select_input.assert_called_once()
        # Qt finishes constructing the list before the scheduled retry runs.
        tab.select_input(*target)
        APP.processEvents()
        self.assertIsNone(self.ui._startup_restore_target)
        self.ui._select_input.assert_called_once()

    def test_load_prepares_qt_on_gui_before_worker_submission(self):
        SERVICES.shared_state.is_running = True
        steps = []
        for name in ("_activate_ui", "_reset_tab_data", "_unregister_all_widgets_ui", "clearWidgets"):
            getattr(self.ui, name).side_effect = lambda *args, name=name: steps.append((name, QtCore.QThread.isMainThread()))
        WORK.submit.side_effect = lambda **kwargs: steps.append(("submit", QtCore.QThread.isMainThread()))
        try:
            with tempfile.NamedTemporaryFile(suffix=".xml", dir=ROOT / "tools") as profile:
                worker = threading.Thread(target=lambda: self.ui._do_load_profile(profile.name))
                worker.start()
                worker.join()
                self.assertEqual(steps, [])
                pump_until(lambda: WORK.submit.called)
                self.assertEqual(steps, [(name, True) for name in (
                    "_activate_ui", "_reset_tab_data", "_unregister_all_widgets_ui", "clearWidgets", "submit",
                )])
                self.assertTrue(self.ui.isProfileLoading())
                self.assertTrue(SERVICES.shared_state.profile_loading)
        finally:
            WORK.submit.side_effect = None

    def test_overlapping_loads_keep_latest_pending_target(self):
        self.ui.pushProfileLoading()
        with tempfile.NamedTemporaryFile(suffix=".xml", dir=ROOT / "tools") as profile:
            self.ui._do_load_profile_ui(profile.name, False, False)
            self.ui._do_load_profile_ui(profile.name, True, True)
            self.assertEqual(self.ui._pending_profile_load, (profile.name, True, True))
            WORK.submit.assert_not_called()
            self.ui._profile_load_completed_ui()
            self.assertIsNone(self.ui._pending_profile_load)
            WORK.submit.assert_called_once()
            self.ui._create_tabs_ui.assert_not_called()

    def test_deleted_pending_profile_does_not_leave_ui_waiting(self):
        self.ui.pushProfileLoading()
        self.ui._pending_profile_load = ("missing-profile.xml", False, True)
        self.ui._profile_load_completed_ui()
        pump_until(lambda: self.ui._create_tabs_ui.called)
        self.assertFalse(self.ui.isProfileLoading())

    def test_profile_parse_and_completion_build_ui_once(self):
        listener, handler = Mock(), Mock()
        SERVICES.event_handler = NS(EventListener=lambda: listener, EventHandler=lambda: handler, JoystickState=Mock())
        SERVICES.execution_graph = Mock()
        SERVICES.joystick_handling = Mock()
        SERVICES.ui.axis_calibration = Mock()
        for name in ("push_redraw", "pop_redraw", "push_suspend_save_input", "pop_suspend_save_input"):
            setattr(SERVICES.shared_state, name, Mock())
        CONFIG.get_profile_last_edit_mode = lambda: "Default"
        profile_data = NS(
            from_xml=Mock(return_value=False), to_xml=Mock(), get_modes=lambda: ["Default"],
            get_default_start_mode=lambda: "Default", getMappingHash=lambda: "profile-hash",
            setLoaded=Mock(), settings=NS(input_visible_map=True), unload=Mock(),
        )
        SERVICES.base_profile = NS(Profile=lambda: profile_data, ProfileImportData=lambda: NS(used_ids=set()))
        self.ui.profile = profile_data
        SERVICES.shared_state.current_profile = None
        self.ui._sanitize_profile = Mock()
        self.ui._update_window_title = Mock()
        self.ui._profile_load_temporary_files = []
        self.ui._device_change_deferred = False
        self.ui._base_path = list(sys.path)
        del self.ui._do_load_profile_internal_worker  # use the production parser method
        paths = list(sys.path)
        results = []
        try:
            with tempfile.NamedTemporaryFile(suffix=".xml", dir=ROOT / "tools") as profile:
                profile.write(b"<profile/>")
                profile.flush()
                self.ui._comparative_file = profile.name + ".comparison"
                self.ui._do_load_profile_ui(profile.name)
                submission = WORK.submit.call_args.kwargs

                def parse():
                    results.append(submission["callback"](submission["args"]))
                    submission["complete_callback"](results[-1], submission["args"])

                worker = threading.Thread(target=parse)
                worker.start()
                worker.join()
                self.assertEqual(results, [None])  # successful worker has no explicit return
                self.ui.mode_selector.populate_selector.assert_not_called()
                pump_until(lambda: self.ui._create_tabs_ui.called)
                self.ui._create_tabs_ui.assert_called_once()
                self.ui.mode_selector.populate_selector.assert_called_once()
                self.ui._select_input.assert_not_called()
        finally:
            sys.path[:] = paths


class Model(QtCore.QObject):
    def __init__(self, items=()):
        super().__init__()
        self.items = list(items)
        self.debug_name = "test model"

    def __iter__(self):
        return iter(self.items)

    def count(self):
        return len(self.items)

    rows = count

    def hashKey(self):
        return hash(tuple(item.id for item in self.items))

    def itemAt(self, index):
        return self.items[index]

    def getFilteredMap(self):
        return enumerate(self.items)


class Editor(QtWidgets.QWidget):
    closed = QtCore.Signal()

    def __init__(self, data, action=False):
        super().__init__()
        self.container = self.action_data = data
        self.text = QtWidgets.QLineEdit(self)
        self.text.setText("unsaved text")
        self.redrawActionSets = Mock()


class Container:
    def __init__(self, identifier):
        self.id = self.name = identifier
        self.created = []

    def widget(self, input_item, container):
        editor = Editor(self)
        self.created.append(editor)
        return editor


ContainerView = load_methods("gremlin/input_item.py", "ContainerView", {
    "_create_ui", "create_ui", "_clear_widgets", "_is_alive", "_show_blank", "_show_content",
    "_redraw_ui", "redraw", "_create_closed_cb",
})
ContainerView.model = property(lambda self: self._model)
ContainerView.input_item = property(lambda self: self._input_item)


class ViewTypes(IntEnum):
    Action = 1
    Conditions = 2


ActionView = load_methods("gremlin/input_item.py", "ActionSetView", {
    "create_ui", "_redraw_ui", "redraw", "_show_blank", "_show_content",
}, ContainerViewTypes=ViewTypes, BasicActionWrapper=lambda widget: Editor(widget.action_data, True),
    ConditionActionWrapperWidget=lambda widget: Editor(widget.action_data, True))
ActionView.model = property(lambda self: self._model)
MappingView = load_methods("gremlin/input_item.py", "InputItemMappingWidget", {"_redraw_ui"})


class IncrementalEditorTests(unittest.TestCase):
    def setUp(self):
        self.container = Container("first")
        self.model = Model([self.container])
        self.view = ContainerView()
        self.view._main_layout = QtWidgets.QVBoxLayout(self.view)
        self.view._input_item = NS(display_name="Button 1")
        self.view._model = self.model
        self.view._redraw_lock = False
        self.view._last_hash = None
        self.view._create_ui()
        self.view._redraw_ui()

    def tearDown(self):
        self.view.deleteLater()
        flush_deletes()

    def test_add_remove_reorder_preserve_existing_container_editor(self):
        original = self.view._widget_map["first"]
        second = Container("second")
        self.model.items.append(second)
        self.view._redraw_ui()
        self.assertIs(self.view._widget_map["first"], original)
        self.assertEqual(len(self.container.created), 1)
        self.assertEqual(original.text.text(), "unsaved text")
        self.model.items.reverse()
        self.view._redraw_ui()
        self.assertIs(self.view._scroll_layout.itemAt(1).widget(), original)
        removed = self.view._widget_map["second"]
        self.model.items.remove(second)
        self.view._redraw_ui()
        flush_deletes(removed)
        self.assertFalse(Shiboken.isValid(removed))
        self.assertIs(self.view._widget_map["first"], original)
        self.assertEqual(self.view._scroll_layout.count(), 2)  # row + one stretch

    def test_replacement_with_same_id_recreates_only_replaced_row(self):
        old = self.view._widget_map["first"]
        replacement = Container("first")
        self.model.items[0] = replacement
        self.view._redraw_ui()
        self.assertIsNot(self.view._widget_map["first"], old)
        self.assertIs(self.view._widget_map["first"].container, replacement)

    def test_explicit_force_still_rebuilds_container_editors(self):
        original = self.view._widget_map["first"]
        self.view._redraw_ui(force=True)
        self.assertIsNot(self.view._widget_map["first"], original)
        self.assertEqual(len(self.container.created), 2)

    def test_mapping_add_retains_toolbar_and_container_view(self):
        mapping = MappingView()
        mapping._input_item = NS(containers=self.model)
        mapping._container_view = self.view
        mapping._drawn_once = True
        mapping._last_container_hash = self.model.hashKey()
        mapping.create_ui = Mock()
        mapping._update_page = Mock()
        self.model.items.append(Container("second"))
        mapping._redraw_ui()
        mapping.create_ui.assert_not_called()
        self.assertIs(mapping._container_view, self.view)
        self.assertEqual(len(self.view._widget_map), 2)
        mapping._redraw_ui(force=True)
        mapping.create_ui.assert_called_once()
        mapping.deleteLater()

    def test_action_add_reorder_remove_and_replacement_retain_others(self):
        view = ActionView()
        view._model = Model([NS(id="a"), NS(id="b")])
        view._stacked_widget = QtWidgets.QStackedWidget(view)
        view._stacked_widget.addWidget(QtWidgets.QWidget())
        view._widget_map = {}
        view._separator = True
        view._drawn_once = False
        view._last_action_hash = None
        view._model_callback_cleaned = False
        view.modelChanged = lambda: False
        view.view_type = ViewTypes.Action
        view._get_action_widget = lambda action: NS(action_data=action)
        view._create_closed_cb = lambda widget: lambda: None
        view._redraw_ui()
        original = dict(view._widget_map)
        separator = view._container_layout.itemAt(0).widget()
        view._model.items.append(NS(id="c"))
        view._redraw_ui()
        self.assertIs(view._widget_map["a"], original["a"])
        view._model.items.reverse()
        view._redraw_ui()
        view._redraw_ui()  # redundant notification must preserve separator order
        self.assertIs(view._container_layout.itemAt(0).widget(), separator)
        self.assertEqual([view._container_layout.itemAt(i).widget().action_data.id for i in range(1, 4)], ["c", "b", "a"])
        view._model.items[1] = NS(id="b")
        view._redraw_ui()
        self.assertIsNot(view._widget_map["b"], original["b"])
        self.assertIs(view._widget_map["a"], original["a"])
        view._model.items.pop()
        view._redraw_ui()
        self.assertNotIn("a", view._widget_map)
        self.assertEqual(view._container_layout.count(), 3)
        view.deleteLater()


class RunnerStopTests(unittest.TestCase):
    def test_completed_stop_notifies_after_runtime_cleanup_without_full_refresh(self):
        listener, handler, context = Mock(), Mock(), Mock()
        SERVICES.event_handler = NS(EventListener=lambda: listener, EventHandler=lambda: handler)
        SERVICES.input_devices = Mock()
        SERVICES.plugin_manager = Mock()
        SERVICES.joystick_handling = Mock()
        SERVICES.windows_event_hook = Mock()
        SERVICES.macro = Mock()
        SERVICES.execution_graph = NS(ExecutionContext=lambda: context)
        SERVICES.shared_state.is_running = True
        SERVICES.shared_state.edit_mode = "Default"
        observations = []
        listener.profile_stopped.emit.side_effect = lambda: observations.append((
            SERVICES.shared_state.is_running, context.clear.called,
        ))
        runner_type = load_methods("gremlin/code_runner.py", "CodeRunner", {"stop"},
                                   vjoy=Mock(), sendinput=Mock(), sync_publisher_with_runtime=Mock())
        runner = runner_type()
        runner._multimode_functors = []
        runner._startup_profile = None
        runner.event_handler = handler
        runner.stop()
        self.assertEqual(observations, [(False, True)])
        listener.request_ui_refresh.emit.assert_not_called()
        listener.profile_unhook.emit.assert_called_once()
        runner.deleteLater()
        flush_deletes()


if __name__ == "__main__":
    unittest.main()
