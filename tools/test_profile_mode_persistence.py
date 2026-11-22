"""Hardware-free regression tests for profile XML and mode persistence."""

import ast
import html
import logging
import os
import re
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
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


def load_profile_parser():
    path = ROOT / "gremlin/profile.py"
    tree = ast.parse(path.read_bytes())
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "parse_profile_xml")
    namespace = dict(etree=etree, BytesIO=BytesIO, os=os, re=re)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["parse_profile_xml"]


parse_profile_xml = load_profile_parser()


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


class ProfileXmlEncodingTests(unittest.TestCase):
    def test_profile_exports_round_trip_special_characters_as_utf8(self):
        profile = profile_fixture()
        profile._ensure_mode_tree()
        device = 'RØDE & "東京" <U0001f3a4>'
        command = "Décollage — 起飛"
        voices = etree.Element("voices", device=device)
        etree.SubElement(voices, "voice-input").text = command
        profile.voice.to_xml = lambda: voices

        with TemporaryDirectory() as directory:
            path = Path(directory) / "profile.xml"
            profile.to_xml(path)
            on_disk = path.read_bytes()
            in_memory = profile.to_xml()
            self.assertEqual(etree.parse(path).docinfo.encoding.upper(), "UTF-8")
            for payload in (on_disk, in_memory):
                self.assertIn("RØDE".encode(), payload)
                self.assertIn("&amp;".encode(), payload)
                self.assertIn("&lt;".encode(), payload)
                node = parse_profile_xml(payload, from_memory=True).find("voices")
                self.assertEqual(node.get("device"), device)
                self.assertEqual(node.findtext("voice-input"), command)

    def test_file_and_memory_loads_honor_unicode_encodings_and_recover_legacy_bytes(self):
        name = "RØDE — 東京"
        utf8_document = f'<?xml version="1.0" encoding="UTF-8"?><profile name="{name}"/>'
        utf16_document = utf8_document.replace('encoding="UTF-8"', 'encoding="UTF-16"')
        utf8 = utf8_document.encode("utf-8")
        mixed = utf8.replace("Ø".encode(), b"\xd8").replace("—".encode(), b"\x97")
        for payload in (utf8, utf8_document.encode("utf-8-sig"), utf16_document.encode("utf-16"), mixed):
            with self.subTest(prefix=payload[:8]), TemporaryDirectory() as directory:
                path = Path(directory) / "profile.xml"
                path.write_bytes(payload)
                self.assertEqual(parse_profile_xml(path).getroot().get("name"), name)
                self.assertEqual(parse_profile_xml(payload, from_memory=True).getroot().get("name"), name)
                self.assertEqual(path.read_bytes(), payload)

    def test_recovery_still_rejects_malformed_xml(self):
        with self.assertRaises(etree.XMLSyntaxError):
            parse_profile_xml(b'<profile name="R\xd8DE"><item></profile>', from_memory=True)


if __name__ == "__main__":
    unittest.main()
