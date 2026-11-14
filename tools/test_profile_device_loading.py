"""Hardware-free profile loading checks: python tools/test_profile_device_loading.py."""

import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class ProfileDeviceLoadingChecks(unittest.TestCase):
    def setUp(self):
        names = {"refresh_devices", "getVjoyDeviceGuid", "vjoy_info_from_vjoy_id", "maestro_info_from_index"}
        tree = ast.parse((ROOT / "gremlin/joystick_handling.py").read_bytes())
        nodes = [node for node in tree.body if getattr(node, "name", None) in names]
        self.assertEqual({node.name for node in nodes}, names)
        self.state = NS(profile_loading=True)
        self.reset = Mock(return_value=True)
        self.devices = {}
        self.namespace = dict(
            gremlin=NS(shared_state=self.state), reset_devices=self.reset,
            getDeviceFromVjoyId=lambda index: self.devices.get(index),
            parse_virtual_device_key=int,
            vjoy_device_map=lambda **kwargs: self.devices,
            _maestro_devices_map=self.devices,
        )
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "joystick_handling.py", "exec"), self.namespace)

    def test_repeated_missing_device_lookups_do_not_enumerate_during_load(self):
        for _ in range(100):
            self.assertIsNone(self.namespace["getVjoyDeviceGuid"](3))
            self.assertIsNone(self.namespace["vjoy_info_from_vjoy_id"](3))
            self.assertIsNone(self.namespace["maestro_info_from_index"](7))
            self.assertIsNone(self.namespace["maestro_info_from_index"](7, connected_only=False))
        self.reset.assert_not_called()

    def test_known_devices_remain_available_during_load(self):
        device = NS(device_guid="known-device")
        self.devices[3] = device
        self.assertEqual(self.namespace["getVjoyDeviceGuid"](3), device.device_guid)
        self.assertIs(self.namespace["vjoy_info_from_vjoy_id"](3), device)
        self.assertIs(self.namespace["maestro_info_from_index"](3), device)
        self.reset.assert_not_called()

    def test_missing_device_can_be_discovered_after_loading(self):
        self.state.profile_loading = False
        device = NS(device_guid="new-device")
        self.reset.side_effect = lambda *args, **kwargs: self.devices.update({3: device})
        self.assertEqual(self.namespace["getVjoyDeviceGuid"](3), device.device_guid)
        self.reset.assert_called_once_with(False, force=False)

    def test_refresh_returns_false_until_loading_finishes(self):
        self.assertFalse(self.namespace["refresh_devices"]())
        self.state.profile_loading = False
        self.assertTrue(self.namespace["refresh_devices"]())
        self.reset.assert_called_once_with(False, force=False)


class ProfileTabPopulationChecks(unittest.TestCase):
    def load_method(self, filename, class_name, method_name, services):
        tree = ast.parse((ROOT / filename).read_bytes())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
        future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
        namespace = {"gremlin": services, "InputType": NS(JoystickAxis="axis", JoystickButton="button", JoystickHat="hat")}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[future, method], type_ignores=[])), filename, "exec"), namespace)
        return namespace[method_name]

    def populate(self, count, *, connected=False, emit=True):
        class Item:
            def __init__(self, index):
                self.device_guid = "device"
                self.input_type = "button"
                self.input_id = index
                self.sortKey = index

        items = [Item(index) for index in range(count, 0, -1)]
        device = NS(connected=connected, disabled=False, device_id="device", device_guid="device")
        settings = NS(
            default_input_visible_map={"device": {}},
            input_visible_map={"device": {"button": {i: i % 2 == 0 for i in range(1, count + 1)}}},
            setFilterDefaults=Mock(), syncFilterDefaults=Mock(),
            profile=NS(isInputMapped=Mock(return_value=False)),
        )
        profile = NS(settings=settings, registry=NS(getInputItems=Mock(return_value=items)),
                     ensureInputItems=Mock(), setFilterDefaults=Mock())
        services = NS(
            shared_state=NS(current_profile=profile, current_mode="Default", edit_mode="Default"),
            joystick_handling=NS(getDevice=lambda guid: device),
            config=NS(Configuration=lambda: NS(verbose_mode_ui=False)),
        )
        visible = self.load_method("gremlin/base_profile.py", "Settings", "getInputVisible", services)
        settings.getInputVisible = Mock(side_effect=lambda *args: visible(settings, *args))
        tab = NS(device_guid="device")
        callback = self.load_method("gremlin/ui/joystick_device.py", "JoystickDeviceTabWidget", "_filter_data", services)
        load_tab = self.load_method("gremlin/ui/joystick_device.py", "JoystickDeviceTabWidget", "_load_handler", services)
        place = self.load_method("gremlin/base_classes.py", "AbstractCallbackModel", "place", services)
        model = NS(_index_map={}, _item_map={}, visible=[],
                   pushSuspend=Mock(), popSuspend=Mock(), trigger=Mock(),
                   _register_content=Mock(), _onItemChanged=Mock(),
                   _fireChanged=Mock(), _notify_changed=Mock())
        model.itemAt = lambda index: model._index_map.get(index)
        model.clear = lambda **kwargs: (model._index_map.clear(), model._item_map.clear())
        model.place = lambda *args, **kwargs: place(model, *args, **kwargs)

        def apply_filter(**kwargs):
            model.visible = [item for item in model._index_map.values() if callback(tab, item, "default")]

        model.applyFilter = Mock(side_effect=apply_filter)
        self.assertTrue(load_tab(tab, model, emit=emit))
        return model, settings

    def test_offline_tab_evaluates_visibility_once_per_input(self):
        for count in (140, 280):
            with self.subTest(inputs=count):
                model, settings = self.populate(count)
                self.assertEqual(settings.getInputVisible.call_count, count)
                model.applyFilter.assert_called_once_with(emit=False)
                self.assertEqual(len(model._index_map), count)
                self.assertEqual(len(model._item_map), count)
                model.pushSuspend.assert_called_once()
                model.popSuspend.assert_called_once()
                model.trigger.assert_called_once()
                settings.setFilterDefaults.assert_not_called()
                settings.syncFilterDefaults.assert_not_called()

    def test_offline_saved_visibility_and_mappings_remain_accessible(self):
        model, settings = self.populate(140)
        self.assertEqual([item.input_id for item in model.visible], list(range(2, 141, 2)))
        self.assertEqual(settings.profile.isInputMapped.call_count, 70)

    def test_connected_tabs_use_same_single_filter_pass(self):
        model, settings = self.populate(140, connected=True, emit=False)
        self.assertEqual(settings.getInputVisible.call_count, 140)
        model.applyFilter.assert_called_once_with(emit=False)
        model.trigger.assert_not_called()
        self.assertEqual([item.input_id for item in model.visible], list(range(2, 141, 2)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
