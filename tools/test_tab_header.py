"""Render the production device tab header without starting Gremlin or hardware.

Run: python tools/test_tab_header.py
Checks use the real stylesheet, palettes, icon engines and Qt tab painting.
"""

import ast
import copy
import enum
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

from PySide6 import QtCore, QtGui, QtTest, QtWidgets
import qtawesome as qta


ROOT = Path(__file__).resolve().parents[1]
APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([
    "tab-header-checks", "-platform", "offscreen",
])
# The Windows offscreen plugin does not enumerate system fonts. Register one
# before QtAwesome loads its icon fonts so ordinary labels retain a text font.
system_font = Path("C:/Windows/Fonts/segoeui.ttf")
if not QtGui.QFontDatabase.families() and system_font.exists():
    font_id = QtGui.QFontDatabase.addApplicationFontFromData(system_font.read_bytes())
    families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
    if families:
        APP.setFont(QtGui.QFont(families[0], 9))


def load_header():
    tree = ast.parse((ROOT / "gremlin/ui/ui_common.py").read_bytes())
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    color_class = copy.deepcopy(classes["Color"])
    color_class.decorator_list = []
    initializer = next(node for node in color_class.body if getattr(node, "name", None) == "__init__")
    palette = next(
        node.value for node in initializer.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Attribute)
        and node.targets[0].attr == "_color_map"
    )
    color_class.body.remove(initializer)  # Avoid reading or writing user configuration.
    services = NS(shared_state=NS(is_dark_theme=True), config=NS(Configuration=lambda: NS(is_debug=True)))
    namespace = {
        "QtCore": QtCore, "QtGui": QtGui, "QtWidgets": QtWidgets,
        "Qt": QtCore.Qt, "QPoint": QtCore.QPoint, "QTabBar": QtWidgets.QTabBar,
        "QProxyStyle": QtWidgets.QProxyStyle, "QStyleFactory": QtWidgets.QStyleFactory,
        "QStyle": QtWidgets.QStyle, "enum": enum, "copy": copy, "gremlin": services,
    }

    def execute(nodes):
        module = ast.Module(body=[
            *ast.parse("from __future__ import annotations").body, *nodes,
        ], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), "gremlin/ui/ui_common.py", "exec"), namespace)

    execute([color_class])
    colors = namespace["Color"]()
    colors._color_map = ast.literal_eval(palette)
    colors._color_map["custom"] = copy.deepcopy(colors._color_map["dark"])
    colors._color_map["custom"].update(
        backgroundColor="#112233", tabBackgroundColor="#335577",
        tabSelectedBackgroundColor="#772244", tabHoverColor="#226644",
        tabTextColor="#ffff00", tabSelectedTextColor="#00ffff",
    )
    colors.theme = "custom"
    namespace["Color"] = lambda: colors
    namespace["QEvent"] = QtCore.QEvent
    execute([copy.deepcopy(classes[name]) for name in ("FixedTabBar", "QTabHeader")])
    return namespace["QTabHeader"], colors


Header, COLORS = load_header()


class TabHeaderChecks(unittest.TestCase):
    def setUp(self):
        self.old_style = APP.style().objectName()
        self.old_css = APP.styleSheet()
        APP.setStyle("Fusion")
        COLORS.theme = "custom"
        APP.setStyleSheet(COLORS.cssApplication())
        self.bar = Header()
        self.bar.setObjectName("devices")  # Ui_Gremlin.build renames the header.
        self.bar.setExpanding(False)
        self.bar.setMovable(True)
        self.bar.setUsesScrollButtons(True)
        for name in ("Unmapped", "Mapped", "Other Mode", "Disconnected"):
            self.bar.addTab(name)
        self.bar.resize(680, 40)
        self.bar.show()
        QtTest.QTest.mouseMove(self.bar, QtCore.QPoint(self.bar.width() - 3, self.bar.height() - 3))
        APP.processEvents()
        self.icon = qta.icon("ri.organization-chart", color=COLORS.tabUsedForegroundColor())

    def tearDown(self):
        self.bar.close()
        self.bar.deleteLater()
        if hasattr(self, "parent_window"):
            self.parent_window.deleteLater()
        if hasattr(self, "parent_window"):
            self.parent_window.deleteLater()
        APP.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        APP.setStyleSheet(self.old_css)
        APP.setStyle(self.old_style)

    def render(self, hovered=False):
        APP.processEvents()
        if not hovered:
            # A previous mouse test can leave the offscreen cursor over a tab,
            # especially when another test process uses a different DPI.
            point = QtCore.QPointF(-1, -1)
            APP.sendEvent(self.bar, QtGui.QHoverEvent(QtCore.QEvent.Type.HoverLeave, point, point, point))
        return self.bar.grab().toImage().scaled(self.bar.size())

    def assert_background(self, image):
        expected = QtGui.QColor(COLORS.backgroundColor())
        for y in (0, 1, 5, self.bar.height() // 2, self.bar.height() - 2):
            self.assertEqual(image.pixelColor(self.bar.width() - 5, y), expected)

    def tab_fill(self, image, index):
        rect = self.bar.tabRect(index)
        return image.pixelColor(rect.center().x(), rect.top() + 3)

    def test_renamed_header_paints_custom_background_with_icons(self):
        self.bar.setTabIcon(1, self.icon)
        self.assert_background(self.render())

    def test_populated_header_cannot_collapse_to_zero_height(self):
        self.bar.setTabIcon(1, self.icon)
        self.bar.resize(self.bar.width(), 0)  # Allocation observed in the live window.
        self.assertGreaterEqual(self.bar.height(), self.bar.tabRect(1).height())
        image = self.render()
        self.assertEqual(self.tab_fill(image, 1), QtGui.QColor(COLORS.tabBackgroundColor()))

    def test_clicking_icon_area_selects_tab(self):
        self.bar.setTabIcon(1, self.icon)
        self.render()
        rect = self.bar.tabRect(1)
        point = QtCore.QPoint(rect.left() + 10, rect.center().y())
        QtTest.QTest.mouseClick(self.bar, QtCore.Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(self.bar.currentIndex(), 1)

    def test_icon_replacement_removal_and_size_change(self):
        self.bar.setTabIcon(1, self.icon)
        replacement = qta.icon("ph.tree-structure-thin", color="#ffffff")
        self.bar.setTabIcon(1, replacement)
        self.assertEqual(self.bar.tabIcon(1).cacheKey(), replacement.cacheKey())
        self.bar.setIconSize(QtCore.QSize(24, 24))
        self.bar.resize(self.bar.width(), 0)
        self.assertGreaterEqual(self.bar.height(), 24)
        self.bar.setTabIcon(1, QtGui.QIcon())
        self.assertTrue(self.bar.tabIcon(1).isNull())

    def test_parent_layout_sizes_header_after_hidden_profile_rebuild(self):
        window = QtWidgets.QWidget()
        self.parent_window = window
        self.parent_window = window
        layout = QtWidgets.QVBoxLayout(window)
        row = QtWidgets.QHBoxLayout()
        layout.addLayout(row)
        button = QtWidgets.QPushButton("...")
        button.setFixedSize(24, 24)
        row.addWidget(button)
        self.bar.hide()
        self.bar.setParent(window)
        row.addWidget(self.bar)
        while self.bar.count():
            self.bar.removeTab(0)
        self.bar.resize(600, 0)
        body = QtWidgets.QLabel("Profile mapping content")
        layout.addWidget(body, 1)
        window.resize(680, 300)
        for name in ("Keyboard/Mouse", "State", "Settings", "LEFT VPC Stick WarBRD"):
            self.bar.addTab(name)
        self.bar.setTabIcon(3, self.icon)
        self.bar.show()
        window.show()
        APP.processEvents()
        self.assertGreaterEqual(self.bar.height(), self.bar.tabRect(3).height())
        self.assertGreater(self.bar.visibleRegion().boundingRect().height(), 0)
        window.close()

    def test_empty_header_uses_custom_background(self):
        while self.bar.count():
            self.bar.removeTab(0)
        self.assert_background(self.render())

    def test_available_styles_keep_custom_background_with_icons(self):
        for name in QtWidgets.QStyleFactory.keys():
            with self.subTest(style=name):
                APP.setStyle(name)
                self.bar.setStyleSheet(COLORS.cssTab())
                self.bar.setTabIcon(1, self.icon)
                self.bar.setCurrentIndex(1)
                image = self.render()
                self.assert_background(image)
                self.assertEqual(self.tab_fill(image, 1), QtGui.QColor(COLORS.tabSelectedBackgroundColor()))

    def test_theme_colors_survive_icon_changes_and_selection(self):
        for theme in ("dark", "light", "custom"):
            with self.subTest(theme=theme):
                COLORS.theme = theme
                self.bar.setStyleSheet(COLORS.cssTab())
                self.bar.setCurrentIndex(1)
                for icon in (self.icon, QtGui.QIcon(), self.icon):
                    self.bar.setTabIcon(1, icon)
                    image = self.render()
                    self.assert_background(image)
                    self.assertEqual(self.tab_fill(image, 1), QtGui.QColor(COLORS.tabSelectedBackgroundColor()))
                    self.assertEqual(self.tab_fill(image, 2), QtGui.QColor(COLORS.tabBackgroundColor()))

    def test_hover_colors_with_icons(self):
        self.bar.setTabIcon(2, self.icon)
        QtTest.QTest.mouseMove(self.bar, self.bar.tabRect(2).center())
        image = self.render(hovered=True)
        self.assertEqual(self.tab_fill(image, 2), QtGui.QColor(COLORS.tabHoverColor()))
        self.assert_background(image)

    def test_icon_layout_updates_without_clipping_or_stale_paint(self):
        self.bar.setTabText(1, "Mapped device with a long name")
        self.render()
        initial = self.bar.tabRect(1)

        def icon_pixels(image):
            rect = self.bar.tabRect(1).adjusted(1, 2, -1, -2)
            return sum(
                min(image.pixelColor(x, y).getRgb()[:3]) > 240
                for x in range(rect.left(), rect.right())
                for y in range(rect.top(), rect.bottom())
            )

        self.bar.setTabIcon(1, self.icon)
        image = self.render()
        expanded = self.bar.tabRect(1)
        self.assertGreater(expanded.width(), initial.width())
        self.assertGreater(icon_pixels(image), 0)
        self.assert_background(image)
        self.bar.setTabIcon(1, QtGui.QIcon())
        self.assertEqual(icon_pixels(self.render()), 0)
        self.assertEqual(self.bar.tabRect(1).width(), initial.width())

    def test_scrolling_and_moving_tabs_keep_styles_and_icons(self):
        self.bar.setTabIcon(1, self.icon)
        self.bar.moveTab(1, 2)
        self.assertEqual(self.bar.tabText(2), "Mapped")
        self.assertEqual(self.bar.tabIcon(2).cacheKey(), self.icon.cacheKey())
        for index in range(12):
            self.bar.addTab(f"Device {index}")
        self.bar.resize(320, 40)
        self.bar.setCurrentIndex(self.bar.count() - 1)
        image = self.render()
        self.assertEqual(self.tab_fill(image, self.bar.currentIndex()), QtGui.QColor(COLORS.tabSelectedBackgroundColor()))
        self.assertTrue(any(button.isVisible() for button in self.bar.findChildren(QtWidgets.QToolButton)))

    def test_mouse_drag_moves_icon_with_its_tab(self):
        self.bar.setTabIcon(1, self.icon)
        self.render()
        start = self.bar.tabRect(1).center()
        target = self.bar.tabRect(2).center()
        QtTest.QTest.mousePress(self.bar, QtCore.Qt.MouseButton.LeftButton, pos=start)
        for point in (start + QtCore.QPoint(15, 0), target):
            event = QtGui.QMouseEvent(
                QtCore.QEvent.Type.MouseMove, QtCore.QPointF(point),
                QtCore.QPointF(self.bar.mapToGlobal(point)),
                QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.LeftButton,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
            APP.sendEvent(self.bar, event)
            APP.processEvents()
        QtTest.QTest.mouseRelease(self.bar, QtCore.Qt.MouseButton.LeftButton, pos=target)
        self.assertEqual(self.bar.tabText(2), "Mapped")
        self.assertEqual(self.bar.tabIcon(2).cacheKey(), self.icon.cacheKey())


if __name__ == "__main__":
    unittest.main()
