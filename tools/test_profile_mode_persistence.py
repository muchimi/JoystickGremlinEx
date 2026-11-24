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
shared_state = SimpleNamespace(master_mode="Master", current_profile=None, translateMode=lambda mode: mode)


class ModeCondition:
    def __init__(self, mode):
        self.mode = mode


class NestedAction(SimpleNamespace):
    pass


plugin_variable_types = SimpleNamespace(Mode="mode", String="string")
NAMESPACE = dict(
    AbstractContainerAction=NestedAction, PluginVariableType=plugin_variable_types, InputType=SimpleNamespace(State="state"),
    anytree=anytree, Node=anytree.Node, etree=etree, html=html, logging=logging, syslog=logging.getLogger(__name__),
    safe_read=lambda node, key, cast, default: cast(node.get(key)) if key in node.attrib else default,
    gremlin=SimpleNamespace(
        shared_state=shared_state,
        profile=SimpleNamespace(ProfileConverter=SimpleNamespace(current_version=1)),
        config=SimpleNamespace(Configuration=lambda: SimpleNamespace(verbose=False)),
        event_handler=SimpleNamespace(EventListener=lambda: SimpleNamespace(mode_name_changed=Mock())),
        input_item=SimpleNamespace(BaseModeCondition=ModeCondition),
    ),
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
    "build_inheritance_tree", "mode_tree", "reload_modes", "rename_mode", "_rename_mode_references", "to_xml",
    "_mode_conditions", "_iter_mode_mappings", "_mode_plugin_variables", "get_missing_mode_references", "getDeviceLabel",
    "remove_mode", "_mode_mapping_removals", "get_mode_removal_usage", "_remove_mode_references",
})
CycleModes = load_class("action_plugins/cycle_modes/__init__.py", "CycleModes", {"_parse_xml"}, "object")
GraphRoot = load_class("gremlin/profile_graph.py", "ProfileRootNode", {"from_xml"}, "object")
GraphMode = load_class("gremlin/profile_graph.py", "ProfileModeNode", {"from_xml"}, "anytree.NodeMixin")
GraphMode.inherit = None
ProfileGraph = load_class("gremlin/profile_graph.py", "ProfileGraph", {"getModeList", "getModeNode", "rename_mode", "remove_mode"})


def profile_fixture():
    profile = Profile.__new__(Profile)
    profile._mode_tree = None
    profile._loaded = True
    profile.devices = {}
    for guid in ("stick", "pedals", "states"):
        modes = {
            "Landing": SimpleNamespace(name="Landing", inherit="Combat"),
            "Default": SimpleNamespace(name="Default", inherit=None),
            "Combat": SimpleNamespace(name="Combat", inherit="Default"),
        }
        for mode in modes.values():
            mode.config = {}
        profile.devices[guid] = SimpleNamespace(
            device_guid=guid,
            name=guid,
            modes=modes,
            getModeNode=Mock(side_effect=lambda name, modes=modes, **kwargs: modes.setdefault(name, SimpleNamespace(name=name, inherit=None, config={}))),
            to_xml=Mock(return_value=None),
        )
    profile.vjoy_devices = {}
    profile._profile_graph = None
    profile._profile_fname = None
    profile._start_mode = profile._default_start_mode = "Default"
    profile._last_runtime_mode = profile._last_edit_mode = profile.override_start_mode = None
    profile._profile_registry = Mock()
    profile.id = "mode-persistence"
    profile.get_start_mode = profile.get_default_start_mode = lambda: "Default"
    profile._restore_last_mode = profile._force_numlock_off = profile._force_numlock_on = False
    profile._simconnect_modes = {}
    profile.merge_axes = []
    profile.plugins = []
    profile._start_state = {}
    profile.settings = SimpleNamespace(startup_mode=None, to_xml=lambda: etree.Element("settings"))
    profile.state = SimpleNamespace(getInputItems=lambda: {}, to_xml=lambda: etree.Element("states"))
    profile.voice = SimpleNamespace(getInputItems=lambda: {}, to_xml=lambda: etree.Element("voices"))
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

    def test_renamed_mode_preserves_mappings_and_inheritance_after_reloading_tree(self):
        profile = profile_fixture()
        profile._ensure_mode_tree()
        root = GraphRoot()
        root._graph_modes = {}
        root.from_xml(etree.fromstring(profile.to_xml()))
        profile._profile_graph = ProfileGraph()
        profile._profile_graph._root = root
        mapping = profile.devices["stick"].modes["Combat"]
        graph_mode = profile._profile_graph.getModeNode("Combat")
        profile._default_start_mode = "Combat"

        self.assertTrue(profile.rename_mode("Combat", "Cruise"))
        self.assertIs(profile.devices["stick"].modes["Cruise"], mapping)
        self.assertEqual(mapping.name, "Cruise")
        self.assertIs(profile._profile_graph.getModeNode("Cruise"), graph_mode)
        self.assertEqual(profile._default_start_mode, "Cruise")
        for device in profile.devices.values():
            self.assertNotIn("Combat", device.modes)
            self.assertEqual(device.modes["Landing"].inherit, "Cruise")

        profile.reload_modes()
        modes = etree.fromstring(profile.to_xml()).findall("./modes/mode")
        parents = {mode.get("name"): mode.get("inherit") for mode in modes}
        self.assertNotIn("Combat", parents)
        self.assertEqual(parents["Cruise"], "Default")
        self.assertEqual(parents["Landing"], "Cruise")

    def test_renaming_updates_refs_in_settings_conditions_and_nested_actions(self):
        profile = profile_fixture()
        profile._ensure_mode_tree()

        def mapping(*actions, condition=None):
            activation = SimpleNamespace(conditions=[condition]) if condition else None
            container = SimpleNamespace(activation_condition=activation, get_action_sets=lambda: [list(actions)])
            return SimpleNamespace(containers=[container])

        container_condition = ModeCondition("Combat")
        action_condition = ModeCondition("Combat")
        switch = SimpleNamespace(tag="switch-mode", mode="Combat", activation_condition=None)
        temporary = SimpleNamespace(
            tag="temporary-mode-switch", mode="Landing", return_mode="Combat",
            activation_condition=SimpleNamespace(conditions=[action_condition]),
        )
        cycle = SimpleNamespace(tag="cycle-modes", mode_list=["Landing", "Combat", "Combat 2"], activation_condition=None)
        nested = NestedAction(tag="script-container", activation_condition=None, _item_data_map={0: mapping(cycle)})
        gate = SimpleNamespace(
            profile_mode="Combat", getGates=lambda: [SimpleNamespace(item_data_map={0: mapping(nested)})],
            getRanges=lambda: [SimpleNamespace(item_data_map={0: mapping(switch)})],
        )
        gated_axis = SimpleNamespace(tag="gated-axis", gates=[gate], activation_condition=None)
        other = SimpleNamespace(tag="play-sound", mode="Combat", activation_condition=None)
        profile.devices["stick"].modes["Default"].config["axis"] = {
            1: mapping(gated_axis, other, condition=container_condition),
        }
        profile.state.getInputItems = lambda: {"state": mapping(temporary)}
        voice_switch = SimpleNamespace(tag="switch-mode", mode="Combat", activation_condition=None)
        profile.voice.getInputItems = lambda: {"voice": mapping(voice_switch)}
        profile.settings.startup_mode = "Combat"
        profile.merge_axes = [{"mode": "Combat"}, {"mode": "Combat 2"}]
        profile._simconnect_modes = {("plane", "model"): "Combat"}
        typed = SimpleNamespace(type=plugin_variable_types.Mode, value="Combat")
        text = SimpleNamespace(type=plugin_variable_types.String, value="Combat")
        profile.plugins = [SimpleNamespace(instances=[SimpleNamespace(variables={"mode": typed, "description": text})])]

        self.assertTrue(profile.rename_mode("Combat", "Cruise"))
        self.assertEqual(profile.settings.startup_mode, "Cruise")
        self.assertEqual(profile.merge_axes, [{"mode": "Cruise"}, {"mode": "Combat 2"}])
        self.assertEqual(profile._simconnect_modes[("plane", "model")], "Cruise")
        self.assertEqual((typed.value, text.value), ("Cruise", "Combat"))
        self.assertEqual((container_condition.mode, action_condition.mode), ("Cruise", "Cruise"))
        self.assertEqual((switch.mode, voice_switch.mode, gate.profile_mode), ("Cruise", "Cruise", "Cruise"))
        self.assertEqual((temporary.mode, temporary.return_mode), ("Landing", "Cruise"))
        self.assertEqual(cycle.mode_list, ["Landing", "Cruise", "Combat 2"])
        self.assertEqual(other.mode, "Combat")

    def test_delete_removes_dependent_mappings_and_keeps_unrelated_actions(self):
        class ActionSet(list):
            remove_action = list.remove

        def mapping(*actions, condition=None):
            action_set = ActionSet(actions)
            activation = SimpleNamespace(conditions=[condition]) if condition else None
            item = SimpleNamespace(containers=[SimpleNamespace(
                activation_condition=activation, get_action_sets=lambda: [action_set],
            )])
            item.remove_container = item.containers.remove
            return item, action_set

        profile = profile_fixture()
        profile._ensure_mode_tree()
        root = GraphRoot()
        root._graph_modes = {}
        root.from_xml(etree.fromstring(profile.to_xml()))
        profile._profile_graph = ProfileGraph()
        profile._profile_graph._root = root
        switch = SimpleNamespace(tag="switch-mode", mode="Combat", activation_condition=None)
        cycle = SimpleNamespace(tag="cycle-modes", mode_list=["Combat", "Landing"], activation_condition=None)
        unrelated = SimpleNamespace(tag="pause", activation_condition=None)
        owned, _ = mapping(unrelated)
        conditioned, _ = mapping(unrelated, condition=ModeCondition("Combat"))
        dependent, actions = mapping(switch, cycle, unrelated)
        profile.devices["stick"].modes["Combat"].config["button"] = {1: owned}
        profile.devices["pedals"].modes["Default"].config["button"] = {1: conditioned, 2: dependent}
        profile.merge_axes = [{"mode": "Combat"}, {"mode": "Landing"}]
        profile.settings.startup_mode = "Combat"
        profile._simconnect_modes = {("plane", "model"): "Combat"}
        variable = SimpleNamespace(type=plugin_variable_types.Mode, value="Combat")
        profile.plugins = [SimpleNamespace(instances=[SimpleNamespace(variables={"mode": variable})])]

        usage = profile.get_mode_removal_usage("Combat")
        self.assertEqual(usage["Inputs mapped in this mode"], 1)
        self.assertEqual(usage["Actions or containers elsewhere that will be removed"], 2)
        self.assertEqual(usage["Mode cycle lists that will be updated"], 1)
        self.assertEqual(usage["Modes that inherit from this mode"], 1)
        self.assertEqual(actions, [switch, cycle, unrelated])
        self.assertTrue(owned.containers and conditioned.containers)

        self.assertTrue(profile.remove_mode("Combat", emit=False))
        self.assertEqual(actions, [cycle, unrelated])
        self.assertEqual(cycle.mode_list, ["Landing"])
        self.assertFalse(owned.containers or conditioned.containers)
        self.assertEqual(profile.merge_axes, [{"mode": "Landing"}])
        self.assertEqual(profile.settings.startup_mode, "Default")
        self.assertEqual(profile._simconnect_modes, {})
        self.assertIsNone(variable.value)
        profile.reload_modes()
        self.assertNotIn("Combat", profile.get_modes())
        self.assertEqual(profile.devices["stick"].modes["Landing"].inherit, "Default")

    def test_start_validation_groups_missing_modes_by_source_input_and_reference(self):
        def configured_input(name, mode, *actions, input_type="button", conditions=()):
            container = SimpleNamespace(
                activation_condition=SimpleNamespace(conditions=conditions),
                get_action_sets=lambda: [actions],
            )
            return SimpleNamespace(display_name=name, profile_mode=mode, input_type=input_type,
                                   containers=[container], curve_data=None)

        profile = profile_fixture()
        profile.build_inheritance_tree()
        switch = SimpleNamespace(tag="switch-mode", mode="Old Flight", name="Switch Mode", activation_condition=None)
        temp = SimpleNamespace(tag="temporary-mode-switch", mode="Default", name="Temporary Mode Switch",
                               return_mode="Disabled Return", enable_return_mode=False, activation_condition=None)
        cycle = CycleModes()
        cycle.tag = "cycle-modes"
        cycle.mode_list = []
        cycle.activation_condition = None
        cycle._parse_xml(etree.fromstring(b'<cycle-modes><mode name="Combat"/><mode name="Old Flight"/></cycle-modes>'))
        nested = NestedAction(tag="nested", activation_condition=None,
                              _item_data_map={1: configured_input("Internal button", "Default", switch)})
        stick = configured_input("Stick: Button 4", "Default", nested, temp)
        pedals = configured_input("Pedals: Axis 2", "Lost Parent")
        state = configured_input("Flight check", "Master", cycle, input_type="state",
                                 conditions=[ModeCondition("Old Flight")])
        profile.devices["stick"].modes["Default"].config["button"] = {4: stick}
        profile.devices["pedals"].modes["Lost Parent"] = SimpleNamespace(inherit=None, config={"axis": {2: pedals}})
        profile.state.getInputItems = lambda: {"check": state}
        profile.merge_axes = [{"mode": "none"}, {"mode": "Old Flight", "lower": {"device_guid": "pedals", "axis_id": 1}}]

        missing = profile.get_missing_mode_references("Unknown Startup")
        self.assertEqual(set(missing), {"Lost Parent", "Old Flight", "Unknown Startup"})
        self.assertIn("Pedals: Axis 2", missing["Lost Parent"][0])
        self.assertEqual(len(missing["Old Flight"]), 4)
        self.assertTrue(any("Stick: Button 4" in reference and "Switch Mode" in reference for reference in missing["Old Flight"]))
        self.assertEqual(sum("State: Flight check" in reference for reference in missing["Old Flight"]), 2)
        self.assertNotIn("Internal button", str(missing))
        self.assertEqual(cycle.mode_list, ["Combat", "Old Flight"])

    def test_undefined_inheritance_parent_loads_for_start_validation(self):
        profile = profile_fixture()
        root = GraphRoot()
        root._graph_modes = {}
        root.from_xml(etree.fromstring(b'<profile><modes><mode name="Landing" inherit="Missing"/></modes></profile>'))
        profile._profile_graph = ProfileGraph()
        profile._profile_graph._root = root
        profile.reload_modes()
        self.assertNotIn("Missing", profile.get_modes())
        self.assertEqual(profile.get_missing_mode_references(), {"Missing": ["Parent of mode Landing"]})
        self.assertEqual(profile.get_missing_mode_references("Master")["Missing"], ["Parent of mode Landing"])

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
