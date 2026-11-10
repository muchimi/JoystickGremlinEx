"""Hardware-free checkbox resource and rendering checks: python tools/test_checkbox_styles.py."""

import ast
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from PySide6 import QtCore, QtWidgets
from test_qt_marshalling import APP, flush_deletes

ROOT = Path(__file__).resolve().parents[1]


def load_functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_bytes())
    nodes = [node for node in tree.body if getattr(node, "name", None) in names]
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            node.decorator_list = []
            node.body = [method for method in node.body if getattr(method, "name", None) in names[node.name]]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), namespace)


UTIL = dict(os=os, __file__=str(ROOT / "gremlin/util.py"))
load_functions("gremlin/util.py", {"get_root_folder", "script_path", "resource_path"}, UTIL)
SERVICES = NS(util=NS(resource_path=UTIL["resource_path"]), shared_state=NS(is_dark_theme=False),
              config=NS(Configuration=lambda: NS(is_debug=False)))
UI = dict(gremlin=SERVICES)
load_functions("gremlin/ui/ui_common.py", {"Color": {"cssCheckbox", "cssApplication"}}, UI)


class Colors(UI["Color"]):
    def __getattr__(self, name):
        return lambda: [("#111111", "#eeeeee")] if name == "ChannelColors" else "#808080"


class CheckboxStyleChecks(unittest.TestCase):
    def styles(self):
        colors = Colors()
        return (colors.cssCheckbox(), colors.cssApplication())

    def test_source_images_resolve_without_a_debugger(self):
        with patch.object(sys, "frozen", False, create=True):
            for dark in (False, True):
                SERVICES.shared_state.is_dark_theme = dark
                prefix = "dark_" if dark else ""
                for css in self.styles():
                    paths = re.findall(r'image: url\("([^"\n]+)"\)', css)
                    self.assertTrue(paths)
                    for path in paths:
                        self.assertTrue(Path(path).is_absolute(), path)
                        self.assertTrue(Path(path).is_file(), path)
                    checked_rule = re.search(r'QCheckBox::indicator:checked\s*\{([^}]+)\}', css).group(1)
                    self.assertIn(prefix + "checkbox.png", checked_rule)
                    for name in ("checkbox_blank_outline_disabled.png", "checkbox_disabled.png", "checkbox_intermediate_disabled.png"):
                        self.assertIn(str(ROOT / "icons" / (prefix + name)).replace("\\", "/").lower(), css.lower())

    def test_packaged_images_resolve_from_bundle_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="checkbox bundle ") as bundle:
            shutil.copytree(ROOT / "icons", Path(bundle) / "icons")
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", bundle, create=True):
                for css in self.styles():
                    paths = re.findall(r'image: url\("([^"\n]+)"\)', css)
                    self.assertTrue(paths)
                    for path in paths:
                        self.assertTrue(Path(path).is_relative_to(bundle), path)
                        self.assertTrue(Path(path).is_file(), path)

    def test_enabled_and_disabled_indicators_render_distinct_states(self):
        with patch.object(sys, "frozen", False, create=True):
            for dark in (False, True):
                SERVICES.shared_state.is_dark_theme = dark
                for css in self.styles():
                    checkbox = QtWidgets.QCheckBox()
                    try:
                        checkbox.setStyleSheet(css)
                        checkbox.show()
                        checkbox.setTristate(True)
                        for enabled in (True, False):
                            checkbox.setEnabled(enabled)
                            rendered = []
                            for state in (QtCore.Qt.Unchecked, QtCore.Qt.Checked, QtCore.Qt.PartiallyChecked):
                                checkbox.setCheckState(state)
                                rendered.append(checkbox.grab().toImage())
                            for index, image in enumerate(rendered):
                                for other in rendered[index + 1:]:
                                    self.assertNotEqual(image, other, (dark, enabled))
                    finally:
                        checkbox.deleteLater()
                        flush_deletes()


if __name__ == "__main__":
    unittest.main(verbosity=2)
