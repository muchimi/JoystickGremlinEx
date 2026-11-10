"""Cross-feature virtual output regression checks with Qt and mocked providers.

Run: python tools/test_virtual_output_selectors.py
"""

import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import uuid

from lxml import etree
from PySide6 import QtCore, QtWidgets

import test_macro_virtual_output as macro
from gremlin.types import MergeAxisOperation, PluginVariableType


ROOT = Path(__file__).resolve().parents[1]
ENV = dict(macro.__dict__)
ENV.update(etree=etree, ElementTree=etree, lxml=NS(etree=etree), uuid=uuid,
           MergeAxisOperation=MergeAxisOperation, PluginVariableType=PluginVariableType,
           read_bool=lambda node, key, default=False: macro.safe_read(node, key, bool, default),
           safe_format=lambda value, kind, default=None: str(default if value is None else value),
           ProfileError=ValueError, error=NS(GremlinError=RuntimeError, VJoyError=RuntimeError))


def load(path, name, methods=None, base=None, env=ENV):
    tree = ast.parse((ROOT / path).read_bytes())
    node = next(n for n in ast.walk(tree) if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name == name)
    if isinstance(node, ast.ClassDef):
        node.decorator_list = []
        if methods is not None:
            node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in methods]
        if base:
            node.bases = [ast.parse(base, mode="eval").body]
    source = ast.Module(body=[*ast.parse("from __future__ import annotations").body, node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(source), str(ROOT / path), "exec"), env)
    return env[name]


for name in ("parse_virtual_device_key", "virtual_device_key", "get_virtual_device", "get_output_device",
             "getDeviceFromVjoyId", "getVjoyDeviceGuid", "getVjoyDeviceGuidStr", "is_vjoy_connected",
             "select_first_valid_vjoy_input", "VJoyProxy", "VjoyStart"):
    load("gremlin/joystick_handling.py", name)
Proxy = ENV["VJoyProxy"]
Selector = load("gremlin/ui/ui_common.py", "VJoySelector")
UserVariable = load("gremlin/user_plugin.py", "VirtualInputVariable", base="object")
Split = load("action_plugins/split_axis/__init__.py", "SplitAxis", {
    "_parse_xml", "_generate_xml", "_is_valid",
}, "object")
SplitFunctor = load("action_plugins/split_axis/__init__.py", "SplitAxisFunctor", {"process_event"}, "object")
Remap = load("action_plugins/remap/__init__.py", "Remap", {"vjoy_id", "virtual_device", "_parse_xml", "_generate_xml"}, "object")
RemapFunctor = load("action_plugins/remap/__init__.py", "RemapFunctor", {"process_event", "relative_axis_thread"}, "object")
Profile = load("gremlin/base_profile.py", "Profile", {
    "list_unused_vjoy_inputs", "list_vjoy_mappings", "_parse_merge_axis",
}, "object")
PluginVariable = load("gremlin/base_profile.py", "PluginVariable")
Merge = load("gremlin/code_runner.py", "MergeAxis")
Runner = load("gremlin/code_runner.py", "CodeRunner", {"_register_merge_axes"}, "object")
Release = load("gremlin/input_devices.py", "CallbackActions", {"_release_callback_prototype"}, "object")
load("gremlin/input_item.py", "BaseAbstractCondition")
Condition = load("gremlin/input_item.py", "BaseVJoyCondition")


class ConditionBase:
    def __init__(self, comparison, *args, **kwargs):
        self.comparison = comparison


ENV["AbstractCondition"] = ConditionBase
ConditionFunctor = load("gremlin/actions.py", "VJoyCondition")
macro.module("gremlin.base_profile", Profile=Profile, ProfileImportData=lambda: NS())
macro.module("gremlin.input_devices")
macro.module("gremlin.error", GremlinError=RuntimeError, VJoyError=RuntimeError)
macro.gremlin.types.MergeAxisOperation = MergeAxisOperation
macro.gremlin.types.PluginVariableType = PluginVariableType
EVENTS = NS(profile_started=Mock())
macro.gremlin.event_handler.EventListener = lambda: EVENTS
macro.gremlin.event_handler.Event = lambda **kwargs: NS(**kwargs)
macro.gremlin.util.valueInRange = lambda value, low, high: min(low, high) <= value <= max(low, high)
macro.gremlin.util.hat_direction_to_tuple = lambda value: next(key for key, name in macro.directions.items() if name.casefold() == value.casefold())
macro.CONFIG.verbose_mode_condition = False

for name in ("overlay_input_types_for_kind", "_device_has_input_types", "overlay_vjoy_devices", "overlay_virtual_key",
             "_vjoy_target", "_proxy_axis_value", "_proxy_hat_direction", "binding_is_configured", "binding_source",
             "binding_is_writable", "vjoy_binding_writable", "read_axis", "read_button", "read_hat", "_invert",
             "_clamp_axis", "write_axis", "write_button", "write_hat", "visibility_binding"):
    load("gremlin/ui/obs_overlay/bindings.py", name)
ENV["_warn_once"] = Mock()
ENV["QDataComboBox"] = macro.Combo
ENV["Buttons"] = NS(getClearWidget=lambda **kwargs: QtWidgets.QPushButton("Clear"),
                    getListenWidget=lambda **kwargs: QtWidgets.QPushButton("Listen"))
ENV["button_callback"] = lambda callback, *args, **kwargs: lambda *unused: callback(*args, **kwargs)
ENV["overlay_device_label"] = lambda device: device.name if device is not None else ""
VisibilityUI = load("gremlin/ui/obs_overlay/inspector.py", "OverlayInspector", {"_fill_visibility_input"}, "QtWidgets.QWidget")
ENV["_enum_radios"] = lambda *args, **kwargs: QtWidgets.QWidget()
ENV["_alive"] = lambda obj: True
KeybindUI = load("gremlin/ui/obs_overlay/keybinds_dialog.py", "RuntimeActionBindingEditor", {"_rebuild"}, "QtWidgets.QWidget")
load("gremlin/ui/obs_overlay/keybinds_dialog.py", "_button_choices")

for name in ("_vjoy_output_devices", "_vjoy_device_label", "_vjoy_axis_ids", "_vjoy_axis_label", "_output_target_label", "_device_from_combo"):
    load("gremlin/ui/afcs/designer.py", name)
AfcsConditionUI = load("gremlin/ui/afcs/designer.py", "NodeConditionWidget", {"_fill_button"}, "QtWidgets.QWidget")
load("gremlin/ui/obs_overlay/graph_track.py", "graph_series_label")
AfcsUI = load("gremlin/ui/afcs/designer.py", "AfcsDesignerWidget", {
    "_build_output_pickers", "_set_output_target", "_vjoy_output_used", "_next_free_output",
    "_apply_spec", "_spec_from_graph_node",
}, "QtWidgets.QWidget")
for name in ("_new_id", "default_node_props", "default_node", "_normalize_node"):
    load("gremlin/ui/afcs/model.py", name)
ENV.update(NODE_KINDS=("input", "merge", "curve", "limiter", "deadzone", "override", "laglead", "output"),
           decode_when=lambda value: value if isinstance(value, dict) else {})
load("gremlin/ui/afcs/runtime.py", "_write_output")
Mapper = load("gremlin/import_profile.py", "MapperDialog", {"mapSingle"}, "object")
ENV["dinput"] = NS(GUID=uuid.UUID)
macro.module("gremlin.plugin_manager")
MergeUI = load("gremlin/ui/merge_axis.py", "MergeAxisUi", {"to_profile", "from_profile"}, "object")


class ModeBox(QtWidgets.QComboBox):
    def __init__(self):
        super().__init__()
        self.mode_list = ["Default", "Flight"]
        self.addItems(self.mode_list)


MergeEntry = load("gremlin/ui/merge_axis.py", "MergeAxisEntry", {"select"}, "object")


class VirtualOutputSelectorTests(unittest.TestCase):
    setUpClass = classmethod(macro.MacroVirtualOutputTests.setUpClass.__func__)
    tearDownClass = classmethod(macro.MacroVirtualOutputTests.tearDownClass.__func__)

    def setUp(self):
        macro.MacroVirtualOutputTests.setUp(self)
        self.key = str(self.maestro.device_guid)
        self.native_key = 1
        self.targets[self.key] = self.targets[self.maestro.device_guid]
        self.targets[str(self.vjoy.device_guid)] = self.targets[self.vjoy.device_guid]
        self.factory = Mock(return_value=self.backends[self.vjoy.device_guid])
        ENV.update(vjoy=NS(VJoy=self.factory),
                   get_output_target=macro.get_output_target, _vjoy_devices_map={1: self.vjoy},
                   _all_vjoy_devices_map={1: self.vjoy}, refresh_devices=Mock())
        Proxy.vjoy_devices = {}
        macro.VJoyProxy = Proxy
        macro.gremlin.joystick_handling.VJoyProxy = Proxy
        def find(key, show_error=False):
            return next((dev for dev in self.devices if str(dev.device_guid) == str(key).strip("{}")), None)
        ENV["getDevice"] = find
        ENV["vjoy_devices"] = lambda connected_only=True: [dev for dev in self.devices if dev.device_type == macro.DeviceType.VJoy
                                                          and (dev.connected or not connected_only)]
        ENV["virtual_devices"] = lambda connected_only=True: [dev for dev in self.devices if dev.connected or not connected_only]
        macro.gremlin.joystick_handling.getDevice = find
        macro.gremlin.joystick_handling.virtual_devices = ENV["virtual_devices"]
        macro.gremlin.joystick_handling.vjoy_devices = ENV["vjoy_devices"]
        for name in ("parse_virtual_device_key", "virtual_device_key", "get_virtual_device", "get_output_device",
                     "getDeviceFromVjoyId", "getVjoyDeviceGuid", "is_vjoy_connected", "select_first_valid_vjoy_input"):
            setattr(macro.gremlin.joystick_handling, name, ENV[name])
        ENV["set_axis"] = macro.gremlin.joystick_handling.set_axis
        ENV["set_button"] = macro.gremlin.joystick_handling.set_button
        ENV["joystick_handling"] = macro.gremlin.joystick_handling
        ENV["input_devices"] = NS(CallbackActions=lambda: NS(register_button_release=Mock()))
        macro.gremlin.input_devices.JoystickProxy = lambda: self.backends
        EVENTS.profile_started.reset_mock()

    def tearDown(self):
        macro.MacroVirtualOutputTests.tearDown(self)

    def test_keys_keep_uuid_identity_and_provider_indices_independent(self):
        self.assertEqual(ENV["parse_virtual_device_key"](self.maestro.device_guid), self.key)
        self.assertEqual(ENV["virtual_device_key"](self.vjoy), 1)
        self.assertEqual(ENV["virtual_device_key"](self.maestro), self.key)
        self.assertIs(ENV["get_virtual_device"](self.key), self.maestro)
        self.assertIs(ENV["get_virtual_device"](1), self.vjoy)

    def test_proxy_guid_uses_maestro_without_acquiring_native_vjoy(self):
        Proxy()[self.key].axis(1).value = 0.75
        self.assertEqual(self.backends[self.maestro.device_guid].axis(1).value, 0.75)
        self.factory.assert_not_called()
        Proxy()[1].axis(2).value = -0.5
        self.factory.assert_called_once_with(1)

    def test_legacy_selector_offers_both_providers_and_serializable_keys(self):
        selector = Selector(Mock(), [macro.InputType.JoystickAxis])
        self.widgets.append(selector)
        self.assertEqual(selector.device_dropdown.count(), 2)
        selector.set_selection(macro.InputType.JoystickAxis, self.key, 2)
        self.assertEqual(selector.get_selection()["device_id"], self.key)
        selector.set_selection(macro.InputType.JoystickAxis, 1, 8)
        self.assertEqual(selector.get_selection()["device_id"], 1)
        self.assertEqual(selector.get_selection()["input_id"], 8)

    def test_first_valid_plugin_output_uses_maestro_when_vjoy_is_absent(self):
        self.devices = [self.maestro]
        value = ENV["select_first_valid_vjoy_input"]([macro.InputType.JoystickAxis])
        self.assertEqual(value["device_id"], self.key)
        variable = UserVariable.__new__(UserVariable)
        variable.value = value
        variable.set(Proxy(), NS(event_type=macro.InputType.JoystickAxis, value=0.5))
        self.assertEqual(self.backends[self.maestro.device_guid].axis(1).value, 0.5)
        self.factory.assert_not_called()

    def test_missing_selector_target_or_input_does_not_choose_a_different_output(self):
        selector = Selector(Mock(), [macro.InputType.JoystickAxis])
        self.widgets.append(selector)
        selector.set_selection(macro.InputType.JoystickAxis, self.key, 999)
        self.assertEqual(selector.get_selection()["device_id"], self.key)
        self.assertIsNone(selector.get_selection()["input_id"])
        selector.set_selection(macro.InputType.JoystickAxis, str(uuid.UUID(int=99)), 1)
        self.assertIsNone(selector.get_selection()["device_id"])

    def test_custom_plugin_editor_restores_and_emits_maestro_selection(self):
        variable = UserVariable.__new__(UserVariable)
        variable.get_label = lambda: "Output"
        variable.description, variable.valid_types = "Target", [macro.InputType.JoystickAxis]
        variable.value_changed = Mock()
        macro.gremlin.ui.ui_common.VJoySelector = Selector
        widget = QtWidgets.QWidget()
        self.widgets.append(widget)
        widget.setLayout(variable.create_ui_element({"device_id": self.key, "input_id": 2,
                                                     "input_type": macro.InputType.JoystickAxis}))
        selector = widget.layout().itemAtPosition(0, 1).widget()
        self.assertEqual(selector.get_selection()["device_id"], self.key)
        selector.input_item_dropdowns[selector.device_dropdown.currentIndex()].setCurrentIndex(0)
        self.assertEqual(variable.value_changed.emit.call_args.args[0]["device_id"], self.key)

    def test_output_selector_excludes_profile_inputs_per_provider(self):
        settings = NS(getVirtualAsInput=Mock(return_value=False))
        with patch.object(macro.gremlin.shared_state, "current_profile", NS(settings=settings), create=True):
            selector = Selector(Mock(), [macro.InputType.JoystickAxis], invalid_ids=[1])
            self.widgets.append(selector)
            self.assertEqual(selector.get_selection()["device_id"], self.key)
            settings.getVirtualAsInput.return_value = True
            selector = Selector(Mock(), [macro.InputType.JoystickAxis], invalid_ids=[])
            self.widgets.append(selector)
            self.assertEqual(selector.get_selection()["device_id"], 1)

    def test_custom_plugin_variable_xml_retains_guid(self):
        variable = PluginVariable(None)
        variable.name, variable.type = "output", PluginVariableType.VirtualInput
        variable.value = {"device_id": self.key, "input_id": 2, "input_type": macro.InputType.JoystickAxis}
        restored = PluginVariable(None)
        restored.from_xml(variable.to_xml())
        self.assertEqual(restored.value, variable.value)

    def split(self):
        action = Split()
        action.center_point = 0.0
        action.device_low_vjoy_id, action.device_low_axis = self.key, 1
        action.device_high_vjoy_id, action.device_high_axis = 1, 8
        return action

    def test_split_axis_roundtrip_and_outputs_to_independent_backends(self):
        action = self.split()
        restored = Split()
        restored._parse_xml(action._generate_xml())
        self.assertTrue(restored._is_valid())
        self.assertEqual(restored.device_low_vjoy_id, self.key)
        functor = SplitFunctor()
        functor.action = restored
        functor.process_event(None, NS(current=-0.75))
        self.assertEqual(self.backends[self.maestro.device_guid].axis(1).value, 0.5)
        self.assertEqual(self.backends[self.vjoy.device_guid].axis(8).value, -1.0)
        functor.process_event(None, NS(current=0.75))
        self.assertEqual(self.backends[self.vjoy.device_guid].axis(8).value, 0.5)
        self.assertEqual(self.backends[self.maestro.device_guid].axis(1).value, -1.0)

    def test_split_axis_extreme_center_never_divides_by_zero(self):
        functor = SplitFunctor()
        functor.action = self.split()
        for center, value in ((-1.0, -1.1), (1.0, 1.0)):
            functor.action.center_point = center
            functor.process_event(None, NS(current=value))

    def remap(self):
        action = Remap()
        action._vjoy_id, action._virtual_device = 1, self.vjoy
        action._vjoy_input_id, action._input_type = 0, macro.InputType.JoystickAxis
        action.set_button_used = Mock()
        action.get_input_type = lambda: macro.InputType.JoystickAxis
        action.input_type = macro.InputType.JoystickAxis
        action.axis_mode, action.axis_scaling = "absolute", 1.0
        return action

    def test_legacy_remap_setter_and_xml_keep_maestro_device(self):
        action = self.remap()
        action.vjoy_id = self.key
        self.assertIs(action._virtual_device, self.maestro)
        action.vjoy_input_id = 1
        node = action._generate_xml()
        restored = self.remap()
        restored._parse_xml(node)
        self.assertEqual(restored.vjoy_id, self.key)
        self.assertIs(restored._virtual_device, self.maestro)

    def test_legacy_remap_can_be_created_without_native_vjoy(self):
        class ActionBase:
            def __init__(self, *args, **kwargs):
                self.id, self.id_changed = "new", Mock()
            def setPriority(self, value):
                pass
            def get_input_type(self):
                return macro.InputType.JoystickAxis
        env = dict(ENV, ActionBase=ActionBase)
        cls = load("action_plugins/remap/__init__.py", "Remap", {
            "__init__", "_on_id_changed", "update_button_used", "virtual_device", "vjoy_id", "vjoy_input_id",
        }, "ActionBase", env)
        self.devices = [self.maestro]
        with patch.object(macro.gremlin.joystick_handling, "VirtualDeviceUsageState", Mock(), create=True):
            action = cls(None)
            self.assertIsNone(action.virtual_device)
            action.vjoy_id = self.key
        self.assertIs(action.virtual_device, self.maestro)
        self.factory.assert_not_called()

    def test_legacy_remap_writes_normal_button_press_and_release(self):
        functor = RemapFunctor()
        functor.vjoy_id, functor.vjoy_input_id = self.key, 1
        functor.input_type, functor.needs_auto_release = macro.InputType.JoystickButton, False
        for pressed in (True, False):
            functor.process_event(NS(), NS(current=pressed))
            self.assertEqual(self.backends[self.maestro.device_guid].button(1).is_pressed, pressed)
        self.factory.assert_not_called()

    def test_legacy_remap_writes_axes_and_hats_to_maestro(self):
        functor = RemapFunctor()
        functor.vjoy_id, functor.vjoy_input_id = self.key, 1
        functor.input_type, functor.axis_mode = macro.InputType.JoystickAxis, "absolute"
        functor.process_event(NS(curve_value=None), NS(current=0.75))
        self.assertEqual(self.backends[self.maestro.device_guid].axis(1).value, 0.75)
        functor.input_type = macro.InputType.JoystickHat
        functor.process_event(NS(), NS(current=(0, 1)))
        self.assertEqual(self.backends[self.maestro.device_guid].hat(1).direction, (0, 1))

    def test_autorelease_uses_selected_maestro_without_native_vjoy(self):
        self.backends[self.maestro.device_guid].button(1).is_pressed = True
        Release()._release_callback_prototype((self.key, 1), is_local=True)
        self.assertFalse(self.backends[self.maestro.device_guid].button(1).is_pressed)
        self.factory.assert_not_called()

    def test_relative_remap_clears_running_state_when_output_disappears(self):
        functor = RemapFunctor()
        functor.vjoy_id, functor.vjoy_input_id = self.key, 1
        with patch.object(macro.gremlin.joystick_handling, "get_output_device", side_effect=RuntimeError("disconnected")):
            functor.relative_axis_thread()
        self.assertFalse(functor.thread_running)

    def test_startup_values_are_kept_separate_for_vjoy_and_maestro(self):
        startup = ENV["VjoyStart"]()
        startup.setStartValue(self.key, 1, 0.5)
        startup.setStartValue(1, 8, -0.75)
        startup.setStartState(self.key, 1, True)
        self.assertEqual(len(startup._axis_data), 2)
        startup.apply()
        self.assertEqual(self.backends[self.maestro.device_guid].axis(1).value, 0.5)
        self.assertEqual(self.backends[self.vjoy.device_guid].axis(8).value, -0.75)
        self.assertTrue(self.backends[self.maestro.device_guid].button(1).is_pressed)
        EVENTS.profile_started.connect.assert_called_once()

    def test_usage_lists_do_not_mix_identical_provider_indices(self):
        profile = Profile()
        profile.list_actions = lambda: [NS(input_type=macro.InputType.JoystickAxis, virtual_device=self.maestro, vjoy_input_id=1)]
        unused = profile.list_unused_vjoy_inputs()
        self.assertEqual(unused[1]["axis"], [2, 8])
        self.assertEqual(unused[self.key]["axis"], [2])
        self.assertEqual(profile.list_vjoy_mappings()[self.key]["axis"], [1])

    def test_merge_xml_reader_accepts_legacy_and_guid_targets(self):
        xml = f'<merge-axis mode="Flight"><vjoy vjoy-id="{self.key}" axis-id="1"/><lower device-guid="{uuid.UUID(int=3)}" axis-id="2"/><upper device-guid="{uuid.UUID(int=4)}" axis-id="8"/></merge-axis>'
        entry = Profile()._parse_merge_axis(etree.fromstring(xml))
        self.assertEqual(entry["vjoy"]["vjoy_id"], self.key)
        self.assertEqual(entry["lower"]["axis_id"], 2)
        self.assertEqual(entry["upper"]["axis_id"], 8)

    def test_merge_registration_runs_through_mode_aware_callbacks(self):
        entry = {"vjoy": {"vjoy_id": self.key, "axis_id": 1}, "operation": MergeAxisOperation.Average,
                 "mode": "Flight", "lower": {"device_guid": uuid.UUID(int=3), "axis_id": 2},
                 "upper": {"device_guid": uuid.UUID(int=4), "axis_id": 8}}
        runner = Runner()
        runner._merge_axes, runner.event_handler = [], NS(addCallback=Mock())
        runner._register_merge_axes(NS(merge_axes=[entry]), "Default")
        calls = runner.event_handler.addCallback.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[1], "Flight")
        calls[0].args[3](NS(value=-1.0))
        calls[1].args[3](NS(value=1.0))
        self.assertEqual(self.backends[self.maestro.device_guid].axis(1).value, -1.0)
        runner._register_merge_axes(NS(merge_axes=[]), "Default")
        self.assertEqual(runner._merge_axes, [])

    def test_merge_ui_restores_and_saves_maestro_without_changing_other_rows(self):
        entry = MergeEntry()
        entry.vjoy_selector = Selector(Mock(), [macro.InputType.JoystickAxis])
        self.widgets.append(entry.vjoy_selector)
        entry.joy1_selector, entry.joy2_selector = Mock(), Mock()
        lower = {"device_guid": uuid.UUID(int=3), "axis_id": 2}
        upper = {"device_guid": uuid.UUID(int=4), "axis_id": 8}
        entry.joy1_selector.get_selection.return_value = {"device_id": lower["device_guid"], "input_id": 2}
        entry.joy2_selector.get_selection.return_value = {"device_id": upper["device_guid"], "input_id": 8}
        entry.mode_selector, entry.operation_selector = ModeBox(), QtWidgets.QComboBox()
        self.widgets.extend([entry.mode_selector, entry.operation_selector])
        entry.operation_selector.addItems(["Average", "Minimum", "Maximum", "Sum"])
        data = {"mode": "Flight", "vjoy": {"vjoy_id": self.key, "axis_id": 2},
                "operation": MergeAxisOperation.Sum, "lower": lower, "upper": upper}
        entry.select(data)
        dialog = MergeUI()
        dialog.entries, dialog.profile_data, dialog._building = [entry], NS(merge_axes=[copy.deepcopy(data)]), True
        dialog.to_profile()
        self.assertEqual(dialog.profile_data.merge_axes, [data])
        dialog._building = False
        dialog.to_profile()
        self.assertEqual(dialog.profile_data.merge_axes, [data])

    def condition(self, kind):
        condition = Condition()
        condition.vjoy_id, condition.input_id, condition.input_type = self.key, 1, kind
        condition.comparison = "inside" if kind == macro.InputType.JoystickAxis else "pressed" if kind == macro.InputType.JoystickButton else "north"
        condition.range = [0.25, 0.75]
        return condition

    def test_condition_xml_roundtrip_retains_maestro_reference(self):
        condition = self.condition(macro.InputType.JoystickAxis)
        restored = Condition()
        restored.from_xml(condition.to_xml())
        self.assertEqual(restored.vjoy_id, self.key)
        self.assertEqual(restored.device_name, self.maestro.name)
        self.assertTrue(restored.is_valid())

    def test_conditions_read_current_maestro_axes_buttons_and_hats(self):
        backend = self.backends[self.maestro.device_guid]
        backend.axis(1).value = 0.5
        backend.button(1).is_pressed = True
        backend.hat(1).direction = (0, 1)
        for kind in (macro.InputType.JoystickAxis, macro.InputType.JoystickButton, macro.InputType.JoystickHat):
            self.assertTrue(ConditionFunctor(self.condition(kind)).process_event(NS(is_pressed=True), None))
        self.factory.assert_not_called()

    def binding(self, kind="axis"):
        return {"source": "vjoy", "device_guid": self.key, "vjoy_id": 1, "input_type": kind, "input_id": 1}

    def test_overlay_lists_both_providers_and_prefers_explicit_guid(self):
        self.assertEqual(len(ENV["overlay_vjoy_devices"]("axis")), 2)
        self.assertEqual(ENV["overlay_virtual_key"](self.binding()), self.key)
        self.assertIs(ENV["_vjoy_target"](self.binding())[1], self.maestro)

    def test_overlay_writes_and_reads_all_maestro_input_types(self):
        self.assertTrue(ENV["write_axis"](self.binding(), -0.625))
        self.assertEqual(ENV["read_axis"](self.binding(), 1), -0.625)
        self.assertTrue(ENV["write_button"](self.binding("button"), True))
        self.assertTrue(ENV["read_button"](self.binding("button")))
        self.assertTrue(ENV["write_hat"](self.binding("hat"), (0, 1)))
        self.assertEqual(ENV["read_hat"](self.binding("hat")), (0, 1))
        self.factory.assert_not_called()

    def test_overlay_graph_label_identifies_maestro(self):
        self.assertIn("Maestro", ENV["graph_series_label"](dict(self.binding(), device_name="Maestro 1", vjoy_id=-1)))

    def test_overlay_missing_guid_does_not_fall_back_to_native_index(self):
        binding = self.binding()
        binding["device_guid"] = str(uuid.UUID(int=99))
        self.assertFalse(ENV["write_axis"](binding, 1.0))
        self.assertEqual(self.backends[self.vjoy.device_guid].axis(1).value, 0.0)

    def test_overlay_visibility_picker_restores_maestro_and_changes_provider(self):
        widget = VisibilityUI()
        self.widgets.append(widget)
        widget._is_alive = lambda: True
        widget._set_visibility_condition = Mock()
        widget._input_choices = lambda device, kind: [(i, f"Button {i}") for i in range(1, device.button_count + 1)]
        form = QtWidgets.QFormLayout(widget)
        cond = dict(self.binding("button"), kind="vjoy", id="condition")
        widget._fill_visibility_input(form, {"id": "item"}, cond)
        combo = form.itemAt(0, QtWidgets.QFormLayout.FieldRole).widget()
        self.assertEqual(combo.currentData(), self.key)
        combo.setCurrentIndex(combo.findData(1))
        self.assertEqual(widget._set_visibility_condition.call_args.kwargs["device_guid"], str(self.vjoy.device_guid))

    def test_overlay_runtime_keybind_picker_uses_maestro_guid(self):
        widget = KeybindUI()
        self.widgets.append(widget)
        widget._form = QtWidgets.QFormLayout(widget)
        widget._binding = lambda: self.binding("button")
        widget._save, widget._clear = Mock(), Mock()
        widget._rebuild()
        device = widget._form.itemAt(1, QtWidgets.QFormLayout.FieldRole).widget()
        self.assertEqual(device.currentData(), self.key)
        button = widget._form.itemAt(2, QtWidgets.QFormLayout.FieldRole).widget()
        button.setCurrentIndex(button.findData(2))
        self.assertEqual(widget._save.call_args.kwargs["input_id"], 2)
        device.setCurrentIndex(device.findData(1))
        self.assertEqual(widget._save.call_args.kwargs["device_guid"], str(self.vjoy.device_guid))

    def test_afcs_picker_restores_maestro_and_saves_provider_key(self):
        widget = AfcsUI()
        self.widgets.append(widget)
        widget._inspector_form = QtWidgets.QFormLayout(widget)
        widget._capture_graph = Mock()
        props = {"vjoy_id": self.key, "axis_id": 2}
        node = NS(get_property=props.get, set_property=lambda key, value: props.update({key: value}), name=lambda: "Output", set_name=Mock())
        widget._build_output_pickers(node)
        combo = widget._inspector_form.itemAt(0, QtWidgets.QFormLayout.FieldRole).widget()
        self.assertEqual(combo.currentData(), self.key)
        combo.setCurrentIndex(combo.findData(1))
        self.assertEqual(props["vjoy_id"], 1)
        self.assertEqual(props["axis_id"], 2)

    def test_afcs_condition_picker_saves_maestro_and_can_clear_selection(self):
        widget = AfcsConditionUI()
        self.widgets.append(widget)
        form = QtWidgets.QFormLayout(widget)
        widget._is_alive = lambda: True
        widget._listen, widget._set_condition = Mock(), Mock()
        widget._fill_button(form, dict(self.binding("button"), kind="vjoy", id="condition"))
        combo = form.itemAt(0, QtWidgets.QFormLayout.FieldRole).widget()
        self.assertEqual(combo.currentData(), self.key)
        combo.setCurrentIndex(combo.findData(1))
        self.assertEqual(widget._set_condition.call_args.kwargs["vjoy_id"], 1)
        combo.setCurrentIndex(combo.findData(self.key))
        self.assertEqual(widget._set_condition.call_args.kwargs["vjoy_id"], self.key)
        combo.setCurrentIndex(0)
        self.assertEqual(widget._set_condition.call_args.kwargs["device_guid"], "")

    def test_afcs_picker_preserves_missing_axis_until_a_new_target_is_chosen(self):
        widget = AfcsUI()
        self.widgets.append(widget)
        widget._inspector_form = QtWidgets.QFormLayout(widget)
        widget._capture_graph = Mock()
        props = {"vjoy_id": self.key, "axis_id": 99}
        node = NS(get_property=props.get, set_property=lambda key, value: props.update({key: value}), name=lambda: "Output", set_name=Mock())
        widget._build_output_pickers(node)
        combo = widget._inspector_form.itemAt(1, QtWidgets.QFormLayout.FieldRole).widget()
        self.assertEqual(combo.currentData(), 99)
        self.assertIn("missing", combo.currentText())
        self.assertEqual(props["axis_id"], 99)

    def test_afcs_normalization_and_runtime_preserve_maestro_guid(self):
        spec = ENV["_normalize_node"]({"kind": "output", "props": {"vjoy_id": self.key, "axis_id": 12}})
        self.assertEqual(json.loads(json.dumps(spec))["props"]["vjoy_id"], self.key)
        self.assertEqual(spec["props"]["axis_id"], 12)
        ENV["_write_output"](self.key, 1, 0.875)
        self.assertEqual(self.backends[self.maestro.device_guid].axis(1).value, 0.875)
        self.factory.assert_not_called()

    def test_afcs_graph_load_and_capture_preserve_maestro_target(self):
        widget = AfcsUI()
        self.widgets.append(widget)
        props = {}
        node = NS(get_property=props.get, set_name=Mock(), name=lambda: "Output", pos=lambda: [10, 20])
        widget._assign_spec_property = lambda node, key, value: props.update({key: value})
        with patch.dict(ENV, kind_for_node=lambda node: "output", encode_when=json.dumps):
            widget._apply_spec(node, {"id": "output", "kind": "output", "props": {"vjoy_id": self.key, "axis_id": 2}})
            spec = widget._spec_from_graph_node(node)
        self.assertEqual(spec["props"]["vjoy_id"], self.key)
        self.assertEqual(spec["props"]["axis_id"], 2)

    def test_afcs_free_output_allocation_keeps_provider_indices_separate(self):
        widget = AfcsUI()
        self.widgets.append(widget)
        used = widget._vjoy_output_used({"nodes": [{"kind": "output", "props": {"vjoy_id": self.key, "axis_id": 1}}]})
        self.assertIn((self.key, 1), used)
        key, axis = widget._next_free_output(used)
        self.assertNotEqual((key, axis), (self.key, 1))

    def test_one_to_one_mapper_assigns_maestro_descriptor_with_numeric_slot(self):
        profile = Profile()
        item = NS(containers=[])
        profile.registry = NS(getInputItem=Mock(return_value=item))
        mode = NS(addInputItem=Mock())
        profile.getModeNode = Mock(return_value=mode)
        macro.gremlin.shared_state.current_profile = profile
        container = NS(add_action=Mock())
        create = Mock(return_value=NS(virtual_device=None))
        macro.gremlin.plugin_manager.ContainerPlugins = lambda: NS(repository={"basic": lambda owner: container})
        macro.gremlin.plugin_manager.ActionPlugins = lambda: NS(repository={"Vjoy Remap": create})
        Mapper().mapSingle(profile, uuid.UUID(int=3), "Default", macro.InputType.JoystickAxis, 2,
                           self.key, macro.InputType.JoystickAxis, 1)
        self.assertEqual(create.call_args.args[1]["vjoy_id"], 1)
        self.assertIs(create.return_value.virtual_device, self.maestro)


if __name__ == "__main__":
    unittest.main(verbosity=2)
