"""Hardware-free mode manager regressions: python tools/test_mode_manager.py."""

import ast
import inspect
import logging
from types import SimpleNamespace as NS
from typing import Callable
import unittest
from unittest.mock import Mock, patch

from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import Shiboken
from test_qt_marshalling import APP, definitions, flush_deletes


def load(path, names, namespace):
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    nodes = [node for node in definitions(path, names) if isinstance(node, (ast.ClassDef, ast.FunctionDef))]
    tree = ast.Module(body=[future, *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), path, "exec"), namespace)


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


class Events(QtCore.QObject):
    profile_modes_changed = QtCore.Signal()
    edit_mode_changed = QtCore.Signal(str)
    mode_list_update = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.keyboard_hook = NS(start=Mock(), stop=Mock())


CONFIG = NS(hide_default_mode=False, dropdown_use_mouse_wheel=False)
CONFIG.getWindowSize = CONFIG.getWindowLocation = lambda *args: None
CONFIG.setWindowSize = CONFIG.setWindowLocation = CONFIG.save = Mock()
STATE = NS(master_mode="Master", edit_mode="Combat", runtime_mode="Combat")
EVENTS = Events()
GREMLIN = NS(config=NS(Configuration=lambda: CONFIG), shared_state=STATE,
             event_handler=NS(EventListener=lambda: EVENTS), util=NS(
                 clear_layout=clear_layout, InvokeUiMethod=lambda callback, *args: callback(*args)))
UI = dict(QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets, QWidget=QtWidgets.QWidget,
          Qt=QtCore.Qt, QSize=QtCore.QSize, QIcon=QtGui.QIcon, inspect=inspect,
          Callable=Callable, Shiboken=Shiboken, gremlin=GREMLIN,
          Buttons=NS(_default_parent=None), syslog=logging.getLogger("system"),
          Color=lambda: NS(cssButton=lambda: "", selectColor=lambda: "#ffffff"),
          get_text_width=lambda text: QtGui.QFontMetrics(APP.font()).horizontalAdvance(text),
          load_icon=lambda *args: QtGui.QIcon(), ConfirmBox=Mock(return_value=True))
load("gremlin/ui/ui_common.py", {
    "QRememberDialog", "BaseDialogUi", "QDataLabel", "QDataPushButton", "QDataLineEdit",
    "QDataCheckbox", "QComboBox", "QDataComboBox", "getHContainer", "getVContainer", "clear_layout",
}, UI)
load("gremlin/ui/dialogs.py", {"ModeManagerDialog"}, UI)


class ProfileFixture:
    def __init__(self, modes=None):
        self.parents = dict(modes or {"Default": None, "Combat": "Default", "Landing": "Combat"})
        self.start_mode = "Combat" if "Combat" in self.parents else next(iter(self.parents))
        self.remove_mode = Mock(side_effect=self._remove_mode)
        self.rename_mode = Mock(side_effect=self._rename_mode)
        self.set_start_mode = Mock(side_effect=lambda name: setattr(self, "start_mode", name))

    def get_mode_map(self):
        return self.parents | {"Master": None}

    def get_root_mode(self):
        return next(name for name, parent in self.parents.items() if parent is None)

    def get_start_mode(self):
        if self.start_mode not in self.parents:
            self.start_mode = self.get_root_mode()
        return self.start_mode

    def get_restore_mode(self):
        return False

    def set_mode_parent(self, name, parent, emit=True):
        self.parents[name] = None if parent == "None" else parent

    def _remove_mode(self, name, emit=True):
        if name not in self.parents or len(self.parents) == 1:
            return False
        parent = self.parents.pop(name)
        for child in self.parents:
            if self.parents[child] == name:
                self.parents[child] = parent
        return True

    def _rename_mode(self, old, new, emit=True):
        self.parents[new] = self.parents.pop(old)
        for child in self.parents:
            if self.parents[child] == old:
                self.parents[child] = new
        if self.start_mode == old:
            self.start_mode = new
        return True


class ModeManagerChecks(unittest.TestCase):
    def setUp(self):
        self.profile = ProfileFixture()
        STATE.current_profile = self.profile
        STATE.edit_mode = STATE.runtime_mode = "Combat"
        self.changed = Mock()
        EVENTS.profile_modes_changed.connect(self.changed)
        self.addCleanup(lambda: EVENTS.profile_modes_changed.disconnect(self.changed))
        UI["ConfirmBox"].reset_mock()
        UI["ConfirmBox"].return_value = True
        self.dialog = UI["ModeManagerDialog"](self.profile, mode="Combat")
        self.dialog.show()
        APP.processEvents()
        self.addCleanup(self.close_dialog)

    def close_dialog(self):
        self.dialog.close()
        self.dialog.deleteLater()
        flush_deletes()

    def startup_modes(self):
        selector = self.dialog.mode_default_selector
        return [selector.itemText(index) for index in range(selector.count())]

    def click_delete(self, mode):
        QtTest.QTest.mouseClick(self.dialog.mode_delete[mode], QtCore.Qt.MouseButton.LeftButton)
        APP.processEvents()

    def test_delete_button_removes_row_and_refreshes_all_mode_lists(self):
        self.click_delete("Combat")
        self.profile.remove_mode.assert_called_once_with("Combat", emit=False)
        self.assertEqual(set(self.dialog.mode_delete), {"Default", "Landing"})
        self.assertEqual(self.startup_modes(), ["Default", "Landing"])
        self.assertEqual(self.profile.parents["Landing"], "Default")
        self.assertEqual(STATE.edit_mode, "Default")
        self.assertEqual(STATE.runtime_mode, "Default")
        self.assertEqual(self.dialog.selected_mode, "Default")
        self.changed.assert_called_once_with()

    def test_rebuilding_does_not_duplicate_modes_or_save_the_start_mode(self):
        self.dialog._populate_mode_layout()
        self.dialog._populate_mode_layout()
        self.assertEqual(self.startup_modes(), ["Combat", "Default", "Landing"])
        self.assertEqual(self.dialog.mode_default_selector.currentText(), "Combat")
        self.profile.set_start_mode.assert_not_called()

    def test_startup_selection_callback_is_connected_once(self):
        self.dialog._populate_mode_layout()
        self.dialog._populate_mode_layout()
        self.profile.set_start_mode.reset_mock()
        self.dialog.mode_default_selector.setCurrentText("Landing")
        self.profile.set_start_mode.assert_called_once_with("Landing")

    def test_cancelled_delete_keeps_modes_and_selection(self):
        UI["ConfirmBox"].return_value = False
        self.click_delete("Combat")
        UI["ConfirmBox"].assert_called_once()
        self.profile.remove_mode.assert_not_called()
        self.assertEqual(set(self.dialog.mode_delete), set(self.profile.parents))
        self.assertEqual(self.dialog.selected_mode, "Combat")
        self.changed.assert_not_called()

    def test_rejected_removal_keeps_the_list_and_does_not_notify(self):
        self.profile.remove_mode.side_effect = None
        self.profile.remove_mode.return_value = False
        self.click_delete("Combat")
        self.profile.remove_mode.assert_called_once_with("Combat", emit=False)
        self.assertEqual(self.startup_modes(), ["Combat", "Default", "Landing"])
        self.changed.assert_not_called()

    def test_last_mode_cannot_be_deleted(self):
        self.profile.parents = {"Default": None}
        self.dialog._populate_mode_layout()
        self.assertFalse(self.dialog.mode_delete["Default"].isEnabled())
        self.click_delete("Default")
        self.profile.remove_mode.assert_not_called()

    def test_rename_button_calls_the_bound_mode_and_refreshes_dropdowns(self):
        with patch.object(QtWidgets.QInputDialog, "getText", return_value=("Cruise", True)):
            QtTest.QTest.mouseClick(self.dialog.mode_rename["Combat"], QtCore.Qt.MouseButton.LeftButton)
        self.profile.rename_mode.assert_called_once_with("Combat", "Cruise", emit=False)
        self.assertEqual(self.startup_modes(), ["Cruise", "Default", "Landing"])
        self.assertIn("Cruise", self.dialog.mode_delete)
        self.assertNotIn("Combat", self.dialog.mode_delete)


if __name__ == "__main__":
    unittest.main(verbosity=2)
