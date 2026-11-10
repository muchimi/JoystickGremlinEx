"""Hardware-free window restoration checks: python tools/test_remember_dialog.py."""

import ast
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from PySide6 import QtCore, QtWidgets


ROOT = Path(__file__).resolve().parents[1]
APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([
    "remember-dialog-checks", "-platform", "offscreen",
])
SERVICES = NS(config=NS(Configuration=Mock()), util=NS(InvokeUiMethod=lambda callback: callback()))
UI = dict(QtCore=QtCore, QtWidgets=QtWidgets, gremlin=SERVICES)
tree = ast.parse((ROOT / "gremlin/ui/ui_common.py").read_bytes())
nodes = [node for node in tree.body if getattr(node, "name", None) == "QRememberDialog"]
exec(compile(ast.Module(body=nodes, type_ignores=[]), "ui_common.py", "exec"), UI)
QRememberDialog = UI["QRememberDialog"]


class RememberDialogChecks(unittest.TestCase):
    def setUp(self):
        self.config = NS(getWindowSize=Mock(return_value=None), getWindowLocation=Mock(return_value=None))
        SERVICES.config.Configuration.return_value = self.config
        self.dialog = QRememberDialog("remember-dialog-test")
        self.widgets = [self.dialog]
        self.dialog.show()
        APP.processEvents()

    def tearDown(self):
        for widget in reversed(self.widgets):
            widget.hide()
            widget.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        APP.processEvents()

    @contextmanager
    def screens(self, *areas):
        screens = [NS(availableGeometry=lambda area=area: QtCore.QRect(*area)) for area in areas]
        with patch.object(QtWidgets.QApplication, "screens", return_value=screens), patch.object(
            QtWidgets.QApplication, "primaryScreen", return_value=screens[0] if screens else None,
        ):
            yield screens

    def restore(self, size, location):
        self.config.getWindowSize.return_value = size
        self.config.getWindowLocation.return_value = location
        # The offscreen platform owns one real screen; check simulated monitors
        # synchronously before its native events reposition negative coordinates.
        self.dialog.apply_window_settings()

    def assert_inside(self, area):
        frame = self.dialog.frameGeometry()
        self.assertTrue(QtCore.QRect(*area).contains(frame), (area, frame.getRect()))

    def test_visible_saved_geometry_is_preserved(self):
        with self.screens((0, 0, 1920, 1040)):
            self.restore((500, 400), (100, 150))
            self.assertEqual(self.dialog.size(), QtCore.QSize(500, 400))
            self.assertEqual(self.dialog.frameGeometry().topLeft(), QtCore.QPoint(100, 150))

    def test_each_partially_hidden_edge_is_brought_inside_work_area(self):
        area = (0, 40, 1200, 720)
        with self.screens(area):
            for location in ((-100, 100), (100, -100), (1100, 100), (100, 700)):
                with self.subTest(location=location):
                    self.restore((400, 300), location)
                    self.assert_inside(area)
                    self.assertEqual(self.dialog.size(), QtCore.QSize(400, 300))

    def test_removed_monitor_falls_back_to_primary(self):
        area = (0, 0, 1200, 760)
        with self.screens(area):
            self.restore((400, 300), (3000, 1500))
            self.assert_inside(area)

    def test_resolution_reduction_fits_size_including_window_frame(self):
        area = (0, 30, 800, 570)
        with self.screens(area):
            self.restore((1920, 1080), (1200, 700))
            self.assert_inside(area)
            self.assertLess(self.dialog.width(), 800)
            self.assertLess(self.dialog.height(), 570)

    def test_valid_negative_monitor_coordinates_are_preserved(self):
        area = (-1600, -100, 1600, 900)
        with self.screens((0, 0, 1920, 1040), area):
            self.restore((400, 300), (-1400, -50))
            self.assert_inside(area)
            self.assertEqual(self.dialog.frameGeometry().topLeft(), QtCore.QPoint(-1400, -50))

    def test_partially_visible_secondary_monitor_is_used(self):
        area = (-1600, 0, 1600, 900)
        with self.screens((0, 0, 1920, 1040), area):
            self.restore((400, 300), (-1700, 100))
            self.assert_inside(area)

    def test_window_spanning_monitors_uses_largest_overlap(self):
        area = (800, 0, 1200, 900)
        with self.screens((0, 0, 800, 760), area):
            self.restore((600, 300), (700, 100))
            self.assert_inside(area)

    def test_window_in_gap_between_monitors_is_recovered(self):
        primary = (0, 0, 800, 760)
        with self.screens(primary, (1600, 0, 800, 760)):
            self.restore((300, 200), (1000, 100))
            self.assert_inside(primary)

    def test_removed_monitor_uses_parent_screen(self):
        primary = (0, 0, 800, 760)
        secondary = (-1600, 0, 1600, 900)
        parent = QtWidgets.QWidget()
        self.widgets.append(parent)
        self.dialog.setParent(parent, self.dialog.windowFlags())
        with self.screens(primary, secondary) as screens, patch.object(parent, "screen", return_value=screens[1]):
            self.restore((400, 300), (3000, 1500))
            self.assert_inside(secondary)

    def test_unshrinkable_dialog_keeps_title_bar_reachable(self):
        area = (20, 40, 800, 560)
        self.dialog.setFixedSize(1200, 900)
        with self.screens(area):
            self.restore((1200, 900), (2000, 1000))
            self.assertEqual(self.dialog.size(), QtCore.QSize(1200, 900))
            self.assertEqual(self.dialog.frameGeometry().topLeft(), QtCore.QPoint(20, 40))

    def test_explicit_restore_after_resolution_change_is_clamped(self):
        with self.screens((0, 0, 1920, 1040)):
            self.restore((900, 700), (900, 300))
        area = (0, 0, 800, 560)
        with self.screens(area):
            self.dialog.apply_window_settings()
            self.assert_inside(area)

    def test_missing_saved_location_still_fits_default_size(self):
        area = (0, 40, 240, 160)
        with self.screens(area):
            self.restore(None, None)
            self.assert_inside(area)

    def test_no_screens_does_not_raise(self):
        with self.screens():
            self.restore((400, 300), (100, 100))

    def test_show_rechecks_after_subclass_layout_changes(self):
        class LateResizeDialog(QRememberDialog):
            def showEvent(self, event):
                super().showEvent(event)
                self.resize(1000, 900)

        self.dialog = LateResizeDialog("late-resize-test")
        self.widgets.append(self.dialog)
        area = (0, 30, 800, 570)
        with self.screens(area):
            self.config.getWindowSize.return_value = (1920, 1080)
            self.config.getWindowLocation.return_value = (1200, 700)
            self.dialog.show()
            APP.processEvents()
            self.assert_inside(area)


if __name__ == "__main__":
    unittest.main(verbosity=2)
