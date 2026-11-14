"""Hardware-free Unicode and icon font checks: python tools/test_input_icon_encoding.py."""

import ast
from pathlib import Path
import unittest

from PySide6 import QtGui, QtWidgets
import qtawesome as qta

ROOT = Path(__file__).resolve().parents[1]
APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([
    "input-icon-checks", "-platform", "offscreen",
])


class InputIconEncodingChecks(unittest.TestCase):
    def test_both_empty_mapping_labels_use_the_empty_set_symbol(self):
        tree = ast.parse((ROOT / "gremlin/input_item.py").read_bytes())
        widget = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "InputItemWidget")
        for name in ("create_action_icons", "clear_action_icon"):
            method = next(node for node in widget.body if getattr(node, "name", None) == name)
            labels = [node for node in ast.walk(method) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute) and node.func.attr == "QLabel"]
            self.assertEqual([node.args[0].value for node in labels], ["\u2205"], name)

    def test_collapse_controls_use_single_unicode_arrows(self):
        tree = ast.parse((ROOT / "gremlin/ui/ui_common.py").read_bytes())
        widget = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "QCollapsible")
        initializer = next(node for node in widget.body if getattr(node, "name", None) == "__init__")
        defaults = dict(zip([arg.arg for arg in initializer.args.args][-len(initializer.args.defaults):], initializer.args.defaults))
        self.assertEqual(ast.literal_eval(defaults["expandedIcon"]), "\u25bc")
        self.assertEqual(ast.literal_eval(defaults["collapsedIcon"]), "\u25b2")

    def test_input_icon_fonts_have_valid_unicode_glyphs(self):
        # Material Design icons use supplementary-plane code points; preserve
        # the full Unicode character instead of truncating it to 16 bits.
        icons = {
            "mdi.chart-bell-curve": 0xF0C50,
            "mdi.arrow-expand-horizontal": 0xF084E,
            "mdi.alpha-c-box-outline": 0xF0BF1,
            "mdi.gesture-tap-button": 0xF12A8,
            "fa6s.power-off": 0xF011,
            "fa6s.gear": 0xF013,
            "ei.fullscreen": 0xF16F,
        }
        for name, expected in icons.items():
            with self.subTest(icon=name):
                icon = qta.icon(name)
                prefix, key = name.split(".", 1)
                char = qta.charmap(name)
                self.assertEqual(ord(char), expected)
                raw = QtGui.QRawFont.fromFont(qta.font(prefix, 24))
                self.assertTrue(raw.supportsCharacter(expected))
                self.assertTrue(all(raw.glyphIndexesForString(char)))
                self.assertFalse(icon.pixmap(24, 24).isNull())


if __name__ == "__main__":
    unittest.main()
