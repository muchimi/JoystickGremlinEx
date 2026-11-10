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
            return list(self.definitions.values())
        if address == "/maestro_devices":
            return [self.definitions[device_id] for device_id in self.active_ids]
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
                            hatCount=info["hats"], productId=0x8010, vendorId=0xFEED)
            elif address == "/maestro_state":
                data = dict(axes={}, pressedButtons=[], hats=[0] * info["hats"], hat=0)
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

    def test_each_device_writes_to_its_own_osc_address(self):
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
