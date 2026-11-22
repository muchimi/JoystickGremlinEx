"""Hardware-free regression tests for saving and reloading profile modes."""

import ast
import html
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import anytree
from lxml import etree


ROOT = Path(__file__).resolve().parents[1]
shared_state = SimpleNamespace(master_mode="Master")
NAMESPACE = dict(
    anytree=anytree, Node=anytree.Node, etree=etree, html=html, syslog=logging.getLogger(__name__),
    safe_read=lambda node, key, cast, default: cast(node.get(key)) if key in node.attrib else default,
    gremlin=SimpleNamespace(shared_state=shared_state, profile=SimpleNamespace(ProfileConverter=SimpleNamespace(current_version=1))),
)


def load_class(path, name, methods=None, base=None):
    tree = ast.parse((ROOT / path).read_bytes())
    node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    if methods is not None:
        node.body = [method for method in node.body if isinstance(method, ast.FunctionDef) and method.name in methods]
    if base is not None:
        node.bases = [ast.parse(base, mode="eval").body]
    source = ast.Module(body=[*ast.parse("from __future__ import annotations").body, node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(source), path, "exec"), NAMESPACE)
    return NAMESPACE[name]


load_class("gremlin/base_profile.py", "ModeNode")
Profile = load_class("gremlin/base_profile.py", "Profile", {
    "registry", "sync", "_ensure_mode_tree", "mode_list", "get_modes", "add_mode", "modeExists",
    "build_inheritance_tree", "mode_tree", "reload_modes", "to_xml",
})
GraphRoot = load_class("gremlin/profile_graph.py", "ProfileRootNode", {"from_xml"}, "object")
GraphMode = load_class("gremlin/profile_graph.py", "ProfileModeNode", {"from_xml"}, "anytree.NodeMixin")
GraphMode.inherit = None
ProfileGraph = load_class("gremlin/profile_graph.py", "ProfileGraph", {"getModeList", "getModeNode"})


def profile_fixture():
    profile = Profile.__new__(Profile)
    profile._mode_tree = None
    profile._loaded = True
    profile.devices = {}
    for guid in ("stick", "pedals", "states"):
        modes = {
            "Landing": SimpleNamespace(inherit="Combat"),
            "Default": SimpleNamespace(inherit=None),
            "Combat": SimpleNamespace(inherit="Default"),
        }
        profile.devices[guid] = SimpleNamespace(
            device_guid=guid,
            modes=modes,
            getModeNode=Mock(side_effect=lambda name, modes=modes, **kwargs: modes.setdefault(name, SimpleNamespace(inherit=None))),
            to_xml=Mock(return_value=None),
        )
    profile.vjoy_devices = {}
    profile._profile_registry = Mock()
    profile.id = "mode-persistence"
    profile.get_start_mode = profile.get_default_start_mode = lambda: "Default"
    profile._restore_last_mode = profile._force_numlock_off = profile._force_numlock_on = False
    profile._simconnect_modes = {}
    profile.merge_axes = []
    profile.plugins = []
    profile._start_state = {}
    profile.settings = SimpleNamespace(to_xml=lambda: etree.Element("settings"))
    profile.state = SimpleNamespace(to_xml=lambda: etree.Element("states"))
    profile.voice = SimpleNamespace(to_xml=lambda: etree.Element("voices"))
    return profile


class ModePersistenceTests(unittest.TestCase):
    def assert_mode_xml(self, xml):
        modes = etree.fromstring(xml).findall("./modes/mode")
        parents = {node.get("name"): node.get("inherit") for node in modes}
        self.assertEqual(len(modes), len(parents))
        self.assertEqual(parents, {
            "Default": None,
            "Combat": "Default",
            "Landing": "Combat",
            shared_state.master_mode: None,
        })

    def test_rebuilt_modes_are_unique_and_keep_parents_after_save_reload(self):
        profile = profile_fixture()
        profile._ensure_mode_tree(reset=True)
        first_save = profile.to_xml()
        self.assert_mode_xml(first_save)

        reloaded = profile_fixture()
        reloaded._profile_graph = ProfileGraph()
        root = GraphRoot()
        root._graph_modes = {}
        root.from_xml(etree.fromstring(first_save))
        reloaded._profile_graph._root = root
        reloaded.reload_modes(update_devices=True)
        self.assert_mode_xml(reloaded.to_xml())

    def test_missing_mode_lookup_preserves_inheritance_defined_only_in_profile_tree(self):
        profile = profile_fixture()
        profile._ensure_mode_tree()
        for device in profile.devices.values():
            for mode in device.modes.values():
                mode.inherit = None

        self.assertFalse(profile.modeExists("Removed mode"))
        self.assert_mode_xml(profile.to_xml())


if __name__ == "__main__":
    unittest.main()
