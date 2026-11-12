"""Hardware-free Maestro identity checks: python tools/test_maestro_identity.py."""

import sys
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from test_maestro_osc import CONFIG, GREMLIN, MAESTRO, MODULES, source_definitions
import test_vjoy_remap_selector as selector_checks


def definition(device_id):
    gamepad = device_id.startswith("gex-gp-")
    return dict(id=device_id, name=device_id, kind="gamepad" if gamepad else "custom",
                axes=6 if gamepad else 8, buttons=16 if gamepad else 128, hats=1 if gamepad else 4)


class MaestroIdentityChecks(unittest.TestCase):
    def setUp(self):
        modules = patch.dict(sys.modules, MODULES)
        modules.start()
        self.addCleanup(modules.stop)
        config = patch.multiple(CONFIG, maestro_enabled=False, maestro_device_map=None)
        config.start()
        self.addCleanup(config.stop)
        self.maestro = MAESTRO.Maestro.klass()
        CONFIG.maestro_enabled = True
        self.maestro._initialized = True
        self.maestro._local_service = False
        self.maestro.refreshDevices = Mock()
        self.definitions = {device_id: definition(device_id) for device_id in ("gex-1", "gex-gp-1")}
        self.active_ids = list(self.definitions)
        self.client = self.maestro._client = NS(
            host="127.0.0.1", port=8010, destination=("127.0.0.1", 8010),
            request=Mock(side_effect=self.request), list=Mock(side_effect=self.list_devices), write=Mock(),
        )
        CONFIG.save.reset_mock()
        normalize = patch.object(GREMLIN.util, "normalize_guid", str, create=True)
        normalize.start()
        self.addCleanup(normalize.stop)
        self.registry = dict(DeviceType=GREMLIN.types.DeviceType, _device_registry_lock=threading.RLock())
        for key in ("_all_devices_map", "_joystick_device_guid_map", "_maestro_service_devices",
                    "_maestro_replaced_devices", "_maestro_devices_map", "_vjoy_devices_map",
                    "_all_vjoy_devices_map", "_disconnected_devices_map", "_all_virtual_devices_map", "_output_targets"):
            self.registry[key] = {}
        source_definitions("gremlin/joystick_handling.py", {
            "set_maestro_devices", "_apply_maestro_service_devices", "_update_joystick_device_maps", "_update_virtual_map",
            "virtual_devices", "vjoy_devices", "maestro_devices", "maestro_device_map",
        }, self.registry)
        publish = patch.object(GREMLIN.joystick_handling, "set_maestro_devices", self.registry["set_maestro_devices"])
        publish.start()
        self.addCleanup(publish.stop)

    def list_devices(self, address):
        if address == "/maestro_definitions":
            return [dict(row) for row in self.definitions.values()]
        if address == "/maestro_devices":
            return [dict(self.definitions[device_id]) for device_id in self.active_ids]
        raise AssertionError(address)

    def request(self, address, device_id, *args):
        if address.startswith("/maestro_create_"):
            self.definitions[device_id] = definition(device_id)
            if device_id not in self.active_ids:
                self.active_ids.append(device_id)
            data = self.definitions[device_id]
        else:
            info = self.definitions[device_id]
            if address == "/maestro_capabilities":
                data = dict(axes=list(MAESTRO.AXIS_NAMES[:info["axes"]]), addressableButtons=info["buttons"],
                            hatCount=info["hats"], productId=0x8010, vendorId=0xFEED,
                            type=info.get("type", "gamepad" if info["kind"] == "gamepad" else "joystick"))
            elif address == "/maestro_state":
                data = dict(axes={}, pressedButtons=[], hats=[0] * info["hats"], hat=0)
            elif address == "/maestro_rename":
                info["name"] = args[0]
                data = dict(info)
            else:
                raise AssertionError(address)
        result = NS(data=data)
        result.raise_for_error = lambda: result
        return result

    def load(self):
        self.maestro.LoadActiveControllers()
        return {controller.id: index for index, controller in self.maestro._controller_map.items()}

    def published(self):
        self.maestro.populateDeviceList()
        return {device.name: device for device in self.registry["virtual_devices"]()}

    def test_same_suffix_joystick_and_gamepad_are_both_registered(self):
        slots = self.load()
        self.assertEqual(set(slots), {"gex-1", "gex-gp-1"})
        self.assertNotEqual(slots["gex-1"], slots["gex-gp-1"])
        devices = self.published()
        self.assertEqual(set(devices), set(slots))
        self.assertNotEqual(devices["gex-1"].device_guid, devices["gex-gp-1"].device_guid)
        self.assertEqual(devices["gex-1"].button_count, 128)
        self.assertEqual(devices["gex-gp-1"].button_count, 16)

    def test_remote_gamepads_are_flagged_without_flagging_custom_joysticks(self):
        self.load()
        devices = self.published()
        self.assertFalse(devices["gex-1"].is_gamepad)
        self.assertTrue(devices["gex-gp-1"].is_gamepad)

    def test_catalog_gamepad_profile_is_flagged_even_with_generic_profile_kind(self):
        self.definitions["catalog-pad"] = definition("catalog-pad") | dict(kind="profile", type="Gamepad")
        self.active_ids.append("catalog-pad")
        CONFIG.maestro_device_map = {"catalog-pad": 5}
        self.load()
        self.assertEqual(self.maestro._controller_map[5].kind, "profile")
        self.assertTrue(self.published()["catalog-pad"].is_gamepad)

    def test_native_maestro_summary_uses_the_emulated_profile_for_gamepad_classification(self):
        for device_id in ("gex-1", "gex-gp-1"):
            with self.subTest(device_id=device_id):
                row = self.definitions[device_id]
                native = MAESTRO.dinput.DeviceSummary()
                native.device_guid = MAESTRO.dinput.GUID(MAESTRO.uuid.uuid4())
                native.name, native.vendor_id, native.product_id = device_id, 0xFEED, 0x8010
                native.axis_count, native.button_count, native.hat_count = row["axes"], row["buttons"], row["hats"]
                # Exercise both setting the flag and clearing stale metadata.
                native.setGamepad(device_id == "gex-1")
                self.maestro._local_service = True
                with patch.object(MAESTRO.dinput.DILL, "getDevices", return_value=[native]):
                    self.load()
                    published = self.published()[device_id]
                self.assertIs(published, native)
                self.assertEqual(published.is_gamepad, device_id == "gex-gp-1")

    def test_service_enumeration_order_does_not_choose_the_winner(self):
        self.active_ids.reverse()
        slots = self.load()
        self.assertEqual(slots, {"gex-gp-1": 1, "gex-1": 0})

    def test_refresh_preserves_both_guids_and_slots(self):
        slots = self.load()
        guids = {name: device.device_guid for name, device in self.published().items()}
        self.active_ids.reverse()
        self.assertEqual(self.load(), slots)
        self.assertEqual({name: device.device_guid for name, device in self.published().items()}, guids)

    def test_new_joystick_does_not_take_existing_gamepad_slot(self):
        slots = self.load()
        self.definitions["gex-2"] = definition("gex-2")
        self.active_ids.insert(0, "gex-2")
        updated = self.load()
        for device_id, index in slots.items():
            self.assertEqual(updated[device_id], index)
        self.assertEqual(len(set(updated.values())), 3)

    def test_saved_distinct_slots_are_preserved(self):
        CONFIG.maestro_device_map = {"gex-1": 7, "gex-gp-1": 3}
        self.assertEqual(self.load(), CONFIG.maestro_device_map)
        CONFIG.save.assert_not_called()

    def test_saved_duplicate_slots_are_repaired_and_saved(self):
        CONFIG.maestro_device_map = {"gex-1": 0, "gex-gp-1": 0}
        slots = self.load()
        self.assertEqual(slots, {"gex-1": 0, "gex-gp-1": 1})
        self.assertEqual(CONFIG.maestro_device_map, slots)
        CONFIG.save.assert_called_once_with()

    def test_inactive_selected_device_keeps_its_reserved_slot(self):
        CONFIG.maestro_device_map = {"offline": 1, "gex-1": 0, "gex-gp-1": 0}
        self.assertEqual(self.load(), {"gex-1": 0, "gex-gp-1": 2})
        self.assertEqual(CONFIG.maestro_device_map["offline"], 1)

    def test_explicit_selection_is_repaired_for_dialog_to_persist(self):
        selection = {"gex-1": 0, "gex-gp-1": 0}
        self.maestro.LoadActiveControllers(selection)
        self.assertEqual(selection, {"gex-1": 0, "gex-gp-1": 1})
        self.assertIsNone(CONFIG.maestro_device_map)

    def test_creating_gamepad_at_joystick_index_keeps_both(self):
        self.active_ids = ["gex-1"]
        self.load()
        gamepad = self.maestro.createGamepadController("gex-gp-1", definition=None, at_index=0)
        self.assertIsNotNone(gamepad)
        self.assertEqual(self.maestro._controller_map[0].id, "gex-1")
        self.assertNotEqual(gamepad.index, 0)
        self.assertEqual(set(self.published()), {"gex-1", "gex-gp-1"})

    def test_creating_joystick_at_gamepad_index_keeps_both(self):
        self.active_ids = ["gex-gp-1"]
        self.load()
        joystick = self.maestro.createJoystickController("gex-1", at_index=0)
        self.assertIsNotNone(joystick)
        self.assertEqual(self.maestro._controller_map[0].id, "gex-gp-1")
        self.assertNotEqual(joystick.index, 0)

    def test_recreating_same_full_id_reuses_its_slot(self):
        slots = self.load()
        controller = self.maestro.createGamepadController("gex-gp-1", definition=None, at_index=0)
        self.assertEqual(controller.index, slots["gex-gp-1"])
        self.assertEqual(len(self.maestro._controller_map), 2)

    def test_duplicate_names_are_renamed_on_host_in_transport_order_without_changing_guids(self):
        self.definitions = {device_id: definition(device_id) for device_id in (
            "gex-1", "gex-2", "gex-3", "gex-gp-1", "gex-gp-2",
        )}
        self.active_ids = list(self.definitions)
        host_order = ["gex-2", "gex-gp-2", "gex-3", "gex-gp-1", "gex-1"]
        for index, device_id in enumerate(host_order):
            self.definitions[device_id]["transportIndex"] = index
        CONFIG.maestro_device_map = {device_id: index for index, device_id in enumerate(self.active_ids)}
        slots = self.load()
        guids = {device.data["maestro_key"]: device.device_guid for device in self.published().values()}
        for device_id, row in self.definitions.items():
            row["name"] = "gex-gp-1" if device_id.startswith("gex-gp-") else "gex-1"
        previous = {device_id: dict(row) for device_id, row in self.definitions.items()}
        self.client.request.reset_mock()

        self.assertEqual(self.load(), slots)
        expected = {"gex-2": "gex-1", "gex-3": "gex-2", "gex-1": "gex-3",
                    "gex-gp-2": "gex-gp-1", "gex-gp-1": "gex-gp-2"}
        self.assertEqual({device_id: row["name"] for device_id, row in self.definitions.items()}, expected)
        for device_id, row in previous.items():
            self.assertEqual(self.definitions[device_id], row | dict(name=expected[device_id]))
        renames = [call.args for call in self.client.request.call_args_list if call.args[0] == "/maestro_rename"]
        self.assertEqual(renames, [("/maestro_rename", "gex-3", "gex-2"),
                                   ("/maestro_rename", "gex-1", "gex-3"),
                                   ("/maestro_rename", "gex-gp-1", "gex-gp-2")])
        self.assertEqual(CONFIG.maestro_device_map, slots)
        CONFIG.save.assert_not_called()
        self.assertEqual({device.data["maestro_key"]: device.device_guid for device in self.published().values()}, guids)
        self.assertEqual({controller.id: controller.name for controller in self.maestro._controller_map.values()}, expected)
        self.assertEqual(set(self.maestro._name_map), set(expected.values()))
        self.client.request.reset_mock()
        self.load()
        self.assertFalse(any(call.args[0] == "/maestro_rename" for call in self.client.request.call_args_list))

    def test_duplicate_names_follow_host_enumeration_when_transport_indices_are_missing(self):
        self.definitions = {f"gex-{i}": definition(f"gex-{i}") | dict(name="gex-1") for i in (1, 2, 3)}
        self.active_ids = ["gex-3", "gex-2", "gex-1"]
        self.load()
        self.assertEqual([self.definitions[device_id]["name"] for device_id in self.active_ids],
                         ["gex-1", "gex-2", "gex-3"])

    def test_repair_preserves_native_guids_when_windows_still_reports_duplicate_names(self):
        self.definitions = {f"gex-{i}": definition(f"gex-{i}") for i in (1, 2)}
        self.active_ids = list(self.definitions)
        native_devices = []
        for row in self.definitions.values():
            device = MAESTRO.dinput.DeviceSummary()
            device.device_guid = MAESTRO.dinput.GUID(MAESTRO.uuid.uuid4())
            device.name, device.vendor_id, device.product_id = row["name"], 0xFEED, 0x8010
            device.axis_count, device.button_count, device.hat_count = 8, 128, 4
            native_devices.append(device)
        self.maestro._local_service = True
        with patch.object(MAESTRO.dinput.DILL, "getDevices", return_value=native_devices):
            self.load()
            guids = {device.data["maestro_key"]: device.device_guid for device in self.published().values()}
            for row, device in zip(self.definitions.values(), native_devices):
                row["name"] = device.name = "gex-1"
            self.load()
            repaired = {device.data["maestro_key"]: device.device_guid for device in self.published().values()}
            self.maestro.LoadActiveControllers({"gex-1": 1, "gex-2": 0})
            reordered = {device.data["maestro_key"]: device.device_guid for device in self.published().values()}
        self.assertEqual(repaired, guids)
        self.assertEqual(reordered, guids)

    def test_inactive_and_unselected_gex_devices_are_repaired_after_active_devices(self):
        self.definitions["gex-2"] = definition("gex-2") | dict(name="gex-1", enabled=False)
        self.definitions["gex-3"] = definition("gex-3") | dict(name="gex-1")
        self.active_ids = ["gex-3", "gex-1", "gex-gp-1"]
        CONFIG.maestro_device_map = {"gex-1": 7}
        self.assertEqual(self.load(), {"gex-1": 7})
        self.assertEqual({device_id: row["name"] for device_id, row in self.definitions.items()},
                         {"gex-1": "gex-2", "gex-2": "gex-3", "gex-3": "gex-1", "gex-gp-1": "gex-gp-1"})
        self.assertFalse(self.definitions["gex-2"]["enabled"])
        self.assertEqual(self.active_ids, ["gex-3", "gex-1", "gex-gp-1"])

    def test_only_gex_service_ids_are_renamed_and_other_clients_names_are_reserved(self):
        for device_id in ("gex-2", "another-client", "gex-helper"):
            self.definitions[device_id] = definition(device_id) | dict(name="gex-1")
        self.active_ids = list(self.definitions)
        self.assertEqual(self.maestro._ensureControllerUniqueNames(), 2)
        self.assertEqual(self.definitions["gex-1"]["name"], "gex-2")
        self.assertEqual(self.definitions["gex-2"]["name"], "gex-3")
        self.assertEqual(self.definitions["another-client"]["name"], "gex-1")
        self.assertEqual(self.definitions["gex-helper"]["name"], "gex-1")
        self.assertEqual([call.args[1] for call in self.client.request.call_args_list], ["gex-1", "gex-2"])
        self.maestro.refreshDevices.assert_called_once_with()

    def test_unique_custom_names_are_unchanged_and_do_not_refresh(self):
        self.definitions["gex-1"]["name"] = "Pilot controls"
        self.definitions["gex-gp-1"]["name"] = "Copilot gamepad"
        self.assertEqual(self.maestro._ensureControllerUniqueNames(), 0)
        self.client.request.assert_not_called()
        self.maestro.refreshDevices.assert_not_called()

    def test_case_insensitive_duplicates_only_resequence_the_affected_type(self):
        self.definitions["gex-1"]["name"] = "Pilot controls"
        self.definitions["gex-gp-2"] = definition("gex-gp-2") | dict(name="GEX-GP-1")
        self.active_ids = list(self.definitions)
        self.assertEqual(self.maestro._ensureControllerUniqueNames(), 1)
        self.assertEqual(self.definitions["gex-gp-2"]["name"], "gex-gp-2")
        self.assertEqual(self.definitions["gex-1"]["name"], "Pilot controls")
        self.client.request.assert_called_once_with("/maestro_rename", "gex-gp-2", "gex-gp-2")

    def test_failed_host_rename_does_not_update_local_names(self):
        self.definitions["gex-2"] = definition("gex-2") | dict(name="gex-1")
        self.active_ids = list(self.definitions)
        failure = MAESTRO.MaestroResult(False, "/maestro_rename", code="rename_failed", message="Device busy")
        for response in (failure, TimeoutError("No reply")):
            with self.subTest(response=response), patch.object(MAESTRO, "syslog", Mock()):
                self.client.request.side_effect = response if isinstance(response, Exception) else None
                self.client.request.return_value = response
                definitions = {device_id: dict(row) for device_id, row in self.definitions.items()}
                devices = {device_id: dict(self.definitions[device_id]) for device_id in self.active_ids}
                self.assertEqual(self.maestro._ensureControllerUniqueNames(definitions, devices), 0)
                self.assertEqual(definitions["gex-2"]["name"], "gex-1")
                self.assertEqual(devices["gex-2"]["name"], "gex-1")
                self.assertEqual(self.definitions["gex-2"]["name"], "gex-1")
                self.maestro.refreshDevices.assert_not_called()

    def test_automatic_names_have_separate_sequences_from_controller_slots(self):
        self.definitions.clear()
        self.active_ids.clear()
        controllers = [
            self.maestro.createJoystickController(at_index=-1),
            self.maestro.createGamepadController(at_index=-1),
            self.maestro.createJoystickController(),
            self.maestro.createGamepadController(),
        ]
        expected = ["gex-1", "gex-gp-1", "gex-2", "gex-gp-2"]
        self.assertEqual([controller.id for controller in controllers], expected)
        self.assertEqual([controller.name for controller in controllers], expected)
        self.assertEqual([controller.index for controller in controllers], [0, 1, 2, 3])
        creates = [call.args for call in self.client.request.call_args_list if call.args[0].startswith("/maestro_create_")]
        self.assertEqual([(args[1], args[2]) for args in creates], [(name, name) for name in expected])

    def test_saved_unattached_devices_reserve_names_after_reloading_selection(self):
        self.active_ids.clear()
        CONFIG.maestro_device_map = {}
        for suffix in (2, 3):
            joystick = self.maestro.createJoystickController()
            gamepad = self.maestro.createGamepadController()
            self.assertEqual((joystick.id, gamepad.id), (f"gex-{suffix}", f"gex-gp-{suffix}"))
            self.assertEqual((joystick.index, gamepad.index), (0, 1))
            self.maestro.LoadActiveControllers({})
            self.assertFalse(self.maestro._controller_map)
        self.assertEqual(len(self.definitions), 6)

    def test_automatic_name_uses_first_free_number(self):
        self.definitions["gex-3"] = definition("gex-3")
        controller = self.maestro.createJoystickController(at_index=7)
        self.assertEqual((controller.id, controller.name, controller.index), ("gex-2", "gex-2", 7))

    def test_automatic_name_reserves_active_ids_even_without_saved_definitions(self):
        self.client.list.side_effect = lambda address: [{"id": "gex-1"}] if address == "/maestro_devices" else []
        controller = self.maestro.createJoystickController()
        self.assertEqual(controller.id, "gex-2")

    def test_automatic_name_reserves_cached_ids_even_with_stale_host_inventory(self):
        self.load()
        self.client.list.side_effect = lambda address: []
        controller = self.maestro.createJoystickController()
        self.assertEqual(controller.id, "gex-2")

    def test_full_name_range_does_not_recreate_existing_device(self):
        for gamepad in (False, True):
            prefix = "gex-gp-" if gamepad else "gex-"
            self.definitions = {f"{prefix}{i}": definition(f"{prefix}{i}") for i in range(1, 17)}
            self.active_ids.clear()
            self.client.request.reset_mock()
            create = self.maestro.createGamepadController if gamepad else self.maestro.createJoystickController
            with self.subTest(gamepad=gamepad), patch.object(MAESTRO, "syslog", Mock()):
                self.assertIsNone(create())
                self.client.request.assert_not_called()

    def test_repeated_presets_append_sequential_devices(self):
        dialog = NS(maestro=self.maestro, _selected_ids=set(), _refresh_devices=Mock())
        for _ in range(2):
            MAESTRO.MaestroDialog._handle_preset_selected(dialog, "Joysticks", dict(
                type="joystick", count=2, axes=8, buttons=128, hats=4,
            ))
            MAESTRO.MaestroDialog._handle_preset_selected(dialog, "Gamepad", dict(type="gamepad"))
        expected = {"gex-2", "gex-3", "gex-4", "gex-5", "gex-gp-2", "gex-gp-3"}
        self.assertEqual(dialog._selected_ids, expected)
        self.assertEqual(set(self.definitions), expected | {"gex-1", "gex-gp-1"})
        self.assertEqual(dialog._refresh_devices.call_count, 4)

    def test_gamepad_action_skips_host_devices_outside_controller_map(self):
        dialog = NS(maestro=self.maestro, _selected_ids=set(), _refresh_devices=Mock())
        for _ in range(2):
            MAESTRO.MaestroDialog._create_new_gamepad(dialog)
        self.assertEqual(dialog._selected_ids, {"gex-gp-2", "gex-gp-3"})
        self.assertEqual(dialog._refresh_devices.call_count, 2)

    def test_each_device_writes_to_its_own_osc_address(self):
        self.maestro._notify_output = Mock()
        for device_id, index in self.load().items():
            MAESTRO.MaestroOutputDevice(index, self.maestro).axis(1).value = 0.5
            self.client.write.assert_called_with(f"/maestro_axis/{device_id}/X", 0.75)

    def test_both_devices_remain_selectable_in_output_dropdown(self):
        self.load()
        devices = self.published()
        selector = selector_checks.OutputSelectorTests()
        selector.setUp()
        self.addCleanup(selector.tearDown)
        selector.devices = list(devices.values())
        selector.ui._update_device_selector()
        combo = selector.ui.virtual_device_selector_widget
        self.assertEqual({combo.itemText(i) for i in range(combo.count())}, set(devices))
        for index in range(combo.count()):
            combo.setCurrentIndex(index)
            self.assertIs(selector.ui.action_data.virtual_device, devices[combo.currentText()])

    def test_removing_gamepad_keeps_joystick(self):
        self.load()
        self.published()
        self.active_ids = ["gex-1"]
        self.assertEqual(self.load(), {"gex-1": 0})
        self.assertEqual(set(self.published()), {"gex-1"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
