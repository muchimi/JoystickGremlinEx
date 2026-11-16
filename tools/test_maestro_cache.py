"""Hardware-free cache and Device Information checks: python tools/test_maestro_cache.py."""

import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import uuid

from PySide6 import QtCore, QtGui, QtWidgets

import test_maestro_identity as identity
from test_maestro_osc import MAESTRO, GREMLIN, CONFIG, source_definitions
from test_qt_marshalling import flush_deletes


ROOT = Path(__file__).resolve().parents[1]
DeviceType = GREMLIN.types.DeviceType


class MaestroCacheChecks(unittest.TestCase):
    setUp = identity.MaestroIdentityChecks.setUp
    list_devices = identity.MaestroIdentityChecks.list_devices
    request = identity.MaestroIdentityChecks.request
    load = identity.MaestroIdentityChecks.load
    published = identity.MaestroIdentityChecks.published

    def native(self, name="gex-1", guid=None):
        device = MAESTRO.dinput.DeviceSummary()
        device.device_guid = guid or MAESTRO.dinput.GUID(uuid.uuid4())
        device.name = name
        device.vendor_id, device.product_id = 0xFEED, 0x8010
        device.axis_count, device.button_count, device.hat_count = 8, 128, 4
        device.device_type = DeviceType.Joystick
        device.setConnected(True)
        device.input_enabled = True
        return device

    def local_devices(self, devices):
        self.maestro._local_service = True
        discovery = patch.object(MAESTRO.dinput.DILL, "getDevices", return_value=devices)
        discovery.start()
        self.addCleanup(discovery.stop)
        return discovery

    def test_published_cache_uses_slots_and_get_device_does_not_republish(self):
        slots = self.load()
        published = self.published()
        self.assertEqual(set(self.maestro._device_map), set(slots.values()))
        for name, index in slots.items():
            with patch.object(self.maestro, "populateDeviceList", side_effect=AssertionError("Cache miss")):
                self.assertIs(self.maestro.getDeviceAt(index), published[name])
        self.assertEqual(len(self.maestro._device_map), len(slots))

    def test_published_summaries_have_matching_vjoy_ids_without_changing_slots(self):
        self.load()
        devices = self.published()
        self.assertEqual(devices["gex-1"].vjoy_id, 1)
        self.assertEqual(devices["gex-1"].virtual_id, 0)
        self.assertEqual(devices["gex-gp-1"].vjoy_id, -1)

    def test_failover_id_uses_service_identity_after_rename_and_slot_reassignment(self):
        self.definitions = {"gex-2": identity.definition("gex-2") | dict(name="Pilot controls")}
        self.active_ids = ["gex-2"]
        CONFIG.maestro_device_map = {"gex-2": 7}
        self.load()
        device = self.published()["Pilot controls"]
        self.assertEqual(device.vjoy_id, 2)
        self.assertEqual(device.virtual_id, 7)
        self.assertEqual(device.device_type, DeviceType.Maestro)
        self.assertEqual(device.name, "Pilot controls")
        self.assertIs(self.maestro.getDeviceAt(7), device)

    def test_failover_identity_requires_active_maestro_joystick_output(self):
        device = self.native("gex-1")
        device.device_type = DeviceType.Maestro
        device.virtual_id = 7
        identify = self.registry["_maestro_failover_id"]
        self.assertEqual(identify(device), 1)
        cases = (
            ("disconnected", lambda d: d.setConnected(False)),
            ("physical", lambda d: setattr(d, "device_type", DeviceType.Joystick)),
            ("vjoy", lambda d: setattr(d, "device_type", DeviceType.VJoy)),
            ("disabled", lambda d: setattr(d, "disabled", True)),
            ("input only", lambda d: setattr(d, "virtual_id", -1)),
            ("invalid slot", lambda d: setattr(d, "virtual_id", 16)),
            ("gamepad", lambda d: d.setGamepad(True)),
        )
        from copy import copy
        for name, invalidate in cases:
            with self.subTest(name=name):
                invalid = copy(device)
                invalidate(invalid)
                self.assertIsNone(identify(invalid))

    def test_failover_map_rejects_inactive_devices_and_stale_vjoy_ids(self):
        source = self.native("VJoy 1")
        source.device_type = DeviceType.VJoy
        source.setConnected(False)
        target = self.native("gex-1")
        target.device_type = DeviceType.Maestro
        target.virtual_id = 7
        target.vjoy_id = 1
        namespace = dict(self.registry, gremlin=NS(config=NS(Configuration=lambda: NS(verbose_mode_maestro=False, virtual_output_failover=True))),
                         _native_vjoy_devices={1: source}, _maestro_devices=[target],
                         _maestro_failover_map={}, _raw_vjoy_target_map={}, _output_targets={}, _all_devices_map={})
        source_definitions("gremlin/joystick_handling.py", {"updateFailoverMap", "OutputTarget"}, namespace)
        namespace["updateFailoverMap"]()
        self.assertEqual(namespace["_maestro_failover_map"][1].out_id, 7)
        target.setConnected(False)
        namespace["updateFailoverMap"]()
        self.assertEqual(namespace["_maestro_failover_map"], {})
        target.setConnected(True)
        target.name = "gex-2"  # Cached vjoy_id=1 must not identify this as gex-1.
        namespace["updateFailoverMap"]()
        self.assertNotIn(1, namespace["_maestro_failover_map"])
        self.assertIs(namespace["_maestro_failover_map"][target.device_guid].device, target)

    def test_native_summary_gets_failover_id_and_keeps_native_identity(self):
        self.active_ids = ["gex-1"]
        native = self.native()
        native.vjoy_id = 12
        guid = native.device_guid
        self.local_devices([native])
        CONFIG.maestro_device_map = {"gex-1": 7}
        self.load()
        self.assertIs(self.published()["gex-1"], native)
        self.assertEqual(native.vjoy_id, 1)
        self.assertEqual(native.virtual_id, 7)
        self.assertEqual(native.device_guid, guid)
        self.assertEqual(native.name, "gex-1")

    def test_custom_joysticks_match_instance_identity_despite_windows_names(self):
        from gremlin.maestro_identity import instance_token_for_key

        self.definitions = {f"gex-{n}": identity.definition(f"gex-{n}") for n in range(1, 5)}
        self.active_ids = list(self.definitions)
        devices = [self.native(f"GEX Custom Device {n}") for n in range(4)]
        self.local_devices(list(reversed(devices)))
        identities = {}
        for n, device in enumerate(devices, 1):
            token = instance_token_for_key(f"MaestroOscService:gex-{n}")
            # Cover both explicit tokens and older bridges with only SDK keys.
            if n % 2:
                self.definitions[f"gex-{n}"]["instanceToken"] = token
            identities[device.device_guid.hex] = dict(path=f"hid#{token}")
            self.registry["_all_devices_map"][device.device_guid] = device
            self.registry["_joystick_device_guid_map"][device.device_guid] = device
        with patch.object(MAESTRO.dinput.DILL, "get_device_identities", return_value=identities, create=True), \
                patch.object(self.maestro, "_scan_hid_order"):
            slots = self.load()
            published = self.published()
            self.assertCountEqual(self.registry["all_joystick_devices"](), devices)
            self.assertEqual(len(published), 4)
            for n, device in enumerate(devices, 1):
                self.assertIs(published[f"gex-{n}"], device)
                self.assertEqual(device.virtual_id, slots[f"gex-{n}"])
                self.assertTrue(device.input_enabled)
            # Another inventory refresh must retain the same native identities.
            self.assertEqual(self.published(), published)
            self.assertCountEqual(self.registry["all_joystick_devices"](), devices)

    def test_obsolete_legacy_native_is_not_displayed_after_bridge_or_native_refresh(self):
        legacy = self.native("GEX Custom Device 3", MAESTRO.dinput.GUID("cb5df360d5cd11f18001444553540000"))
        legacy.vendor_id = legacy.product_id = 1
        physical = self.native("GEX Custom Device 3")
        physical.vendor_id, physical.product_id = 0x045E, 0x028E
        current = self.native("gex-1")
        self.local_devices([legacy, physical, current])
        for device in (legacy, physical, current):
            self.registry["_all_devices_map"][device.device_guid] = device
        self.load()
        self.published()
        self.assertNotIn(legacy.device_guid, self.registry["_all_devices_map"])
        self.assertNotIn(legacy.device_guid, self.registry["_joystick_device_guid_map"])
        self.assertIn(physical, self.registry["all_joystick_devices"]())
        self.assertIn(current, self.registry["all_joystick_devices"]())
        # Windows still enumerates the legacy device on a subsequent hot-plug.
        self.registry["_all_devices_map"][legacy.device_guid] = legacy
        self.registry["_update_joystick_device_maps"]()
        self.assertNotIn(legacy, self.registry["all_joystick_devices"]())
        self.assertNotIn(legacy.device_guid, self.registry["_all_devices_map"])

    def test_legacy_native_without_authoritative_inventory_is_preserved(self):
        legacy = self.native("GEX Custom Device 3")
        legacy.vendor_id = legacy.product_id = 1
        self.local_devices([legacy])
        self.registry["_all_devices_map"][legacy.device_guid] = legacy
        self.registry["set_maestro_devices"]([])
        self.assertIn(legacy, self.registry["all_joystick_devices"]())

    def test_active_legacy_native_service_identity_is_preserved(self):
        legacy = self.native("GEX Custom Device 3")
        legacy.vendor_id = legacy.product_id = 1
        key = "maestro://127.0.0.1:8010/gex-1"
        legacy.data["maestro_key"] = key
        self.local_devices([legacy])
        self.registry["_all_devices_map"][legacy.device_guid] = legacy
        self.registry["set_maestro_devices"]([], known_devices={key: dict(active=True)})
        self.assertIn(legacy, self.registry["all_joystick_devices"]())

    def test_display_inventory_uses_live_devices_and_only_this_profiles_missing_devices(self):
        live = self.native("Connected", guid=MAESTRO.dinput.GUID(uuid.uuid4()))
        stale = self.native("Unplugged but cached as connected")
        saved = self.native("Profile joystick")
        saved.setConnected(False)
        virtual = self.native("Profile vJoy")
        virtual.device_type = DeviceType.VJoy
        virtual.setConnected(False)
        unrelated = self.native("Previous profile")
        unrelated.setConnected(False)
        self.local_devices([live])
        for device in (live, stale, unrelated):
            self.registry["_all_devices_map"][device.device_guid] = device
        profile = NS(devices={stale.device_guid: NS(device=stale), saved.device_guid: NS(device=saved)},
                     vjoy_devices={virtual.device_guid: NS(device=virtual)})
        with patch.object(MAESTRO.dinput.DILL, "initialized", True, create=True):
            shown = {d.device_guid: d for d in self.registry["display_devices"](profile)}
            self.assertEqual(set(shown), {d.device_guid for d in (live, stale, saved, virtual)})
            self.assertIs(shown[live.device_guid], live)
            for device in (stale, saved, virtual):
                self.assertFalse(shown[device.device_guid].connected)
            self.assertTrue(stale.connected)  # Display copies do not mutate the cache or profile.
            empty = NS(devices={}, vjoy_devices={})
            self.assertEqual(self.registry["display_devices"](empty), [live])
            # A reconnected device takes its status from native enumeration.
            live.setConnected(False)
            reconnected = self.registry["display_devices"](empty)
            self.assertEqual([d.device_guid for d in reconnected], [live.device_guid])
            self.assertTrue(reconnected[0].connected)

    def test_display_inventory_reads_native_devices_without_registry_entries(self):
        physical = self.native("Physical")
        vjoy = self.native("vJoy Device")
        vjoy.device_type = DeviceType.VJoy
        vjoy.vjoy_id = 1
        cached = self.native("Cached connected joystick")
        cached_vjoy = self.native("Cached vJoy failover")
        cached_vjoy.device_type = DeviceType.VJoy
        cached_vjoy.data["failover"] = True
        for device in (cached, cached_vjoy):
            self.registry["_all_devices_map"][device.device_guid] = device
        self.local_devices([physical, vjoy])
        with patch.object(MAESTRO.dinput.DILL, "initialized", True, create=True):
            shown = self.registry["display_devices"](NS(devices={}, vjoy_devices={}))
        self.assertCountEqual([d.device_guid for d in shown], [physical.device_guid, vjoy.device_guid])
        self.assertTrue(all(d.connected for d in shown))

    def test_display_inventory_rejects_invalid_and_excluded_native_interfaces(self):
        devices = []
        for name, vendor, product, axes, buttons, hats in (
            ("Too many axes", 0x1234, 1, 9, 8, 1),
            ("Too many buttons", 0x1234, 2, 2, 129, 1),
            ("Too many hats", 0x1234, 3, 2, 8, 5),
            ("Empty interface", 0x1234, 4, 0, 0, 0),
            ("Wooting keyboard interface", 0x31E3, 1, 0, 674, 0),
            ("Wooting three-button interface", 0x31E3, 1, 0, 3, 0),
            ("Wooting empty interface", 0x31E3, 1, 0, 0, 0),
            ("IFR1 HID interface", 0x04D8, 0xE6D6, 1, 35, 0),
            ("Button box", 0x1234, 5, 0, 32, 0),
            ("Wooting gamepad", 0x31E3, 1, 5, 10, 1),
            ("Full-size joystick", 0x1234, 6, 8, 128, 4),
        ):
            device = self.native(name)
            device.vendor_id, device.product_id = vendor, product
            device.axis_count, device.button_count, device.hat_count = axes, buttons, hats
            devices.append(device)
        self.local_devices(devices)
        # Profile references must not reintroduce a rejected live interface as
        # a disconnected device, even when their saved layout is incomplete.
        from copy import copy
        saved = [copy(device) for device in devices]
        for device in saved:
            device.axis_count = device.button_count = device.hat_count = 0
        profiles = (
            NS(devices={}, vjoy_devices={}),
            NS(devices={device.device_guid: NS(device=device) for device in saved}, vjoy_devices={}),
        )
        with patch.object(MAESTRO.dinput.DILL, "initialized", True, create=True):
            for profile in profiles:
                with self.subTest(profile_references=bool(profile.devices)):
                    shown = self.registry["display_devices"](profile)
                    self.assertCountEqual([d.name for d in shown],
                                          ["Button box", "Wooting gamepad", "Full-size joystick"])

    def test_display_inventory_preserves_registered_disable_flags(self):
        registered = self.native("Disabled joystick")
        registered.disabled = True
        self.registry["_all_devices_map"][registered.device_guid] = registered
        fresh = self.native(registered.name, guid=registered.device_guid)
        self.local_devices([fresh])
        profile = NS(devices={fresh.device_guid: NS(device=fresh)}, vjoy_devices={})
        with patch.object(MAESTRO.dinput.DILL, "initialized", True, create=True):
            self.assertEqual(self.registry["display_devices"](profile), [])

    def test_display_inventory_preserves_unknown_disconnected_profile_placeholder(self):
        missing = self.native("Unplugged joystick")
        missing.axis_count = missing.button_count = missing.hat_count = 0
        missing.setConnected(False)
        self.local_devices([])
        profile = NS(devices={missing.device_guid: NS(device=missing)}, vjoy_devices={})
        with patch.object(MAESTRO.dinput.DILL, "initialized", True, create=True):
            shown = self.registry["display_devices"](profile)
        self.assertEqual([d.device_guid for d in shown], [missing.device_guid])
        self.assertFalse(shown[0].connected)

    def test_display_inventory_never_trusts_connected_cache_without_native_enumeration(self):
        cached = self.native("Cached connected joystick")
        self.registry["_all_devices_map"][cached.device_guid] = cached
        empty = NS(devices={}, vjoy_devices={})
        profile = NS(devices={cached.device_guid: NS(device=cached)}, vjoy_devices={})
        with patch.object(MAESTRO.dinput.DILL, "initialized", False, create=True):
            self.assertEqual(self.registry["display_devices"](empty), [])
            shown = self.registry["display_devices"](profile)
        self.assertEqual([d.device_guid for d in shown], [cached.device_guid])
        self.assertFalse(shown[0].connected)
        self.assertTrue(cached.connected)

    def test_excluded_legacy_profile_device_is_retained_as_disconnected(self):
        legacy = self.native("GEX Custom Device 7")
        legacy.vendor_id = legacy.product_id = 1
        self.local_devices([legacy])
        self.registry["_all_devices_map"][legacy.device_guid] = legacy
        self.registry["set_maestro_devices"]([], known_devices={})
        profile = NS(devices={legacy.device_guid: NS(device=legacy)}, vjoy_devices={})
        shown = self.registry["display_devices"](profile)
        self.assertEqual([d.device_guid for d in shown], [legacy.device_guid])
        self.assertFalse(shown[0].connected)

    def test_display_inventory_includes_connected_remote_service_devices(self):
        self.local_devices([])
        self.load()
        published = self.published()
        with patch.object(MAESTRO.dinput.DILL, "initialized", True, create=True):
            shown = self.registry["display_devices"](NS(devices={}, vjoy_devices={}))
        self.assertCountEqual(shown, published.values())
        self.assertTrue(all(d.connected for d in shown))

    def test_setting_maestro_vjoy_id_preserves_name_guid_and_maestro_slot(self):
        device = self.native("Pilot controls")
        device.data["maestro_key"] = "maestro://127.0.0.1:8010/gex-2"
        device.device_type = DeviceType.Maestro
        device.setVirtual(True)
        device.virtual_id = 7
        guid = device.device_guid
        device.set_vjoy_id(2)
        self.assertEqual(device.vjoy_id, 2)
        self.assertEqual(device.virtual_id, 7)
        self.assertEqual(device.device_guid, guid)
        self.assertEqual(device.name, "Pilot controls")

    def test_setting_native_vjoy_id_still_updates_name_and_slot(self):
        device = self.native()
        device.device_type = DeviceType.VJoy
        device.setVirtual(True)
        device.set_vjoy_id(3)
        self.assertEqual(device.vjoy_id, 3)
        self.assertEqual(device.virtual_id, 3)
        self.assertEqual(device.name, "VJoy 8/128/4 (3)")

    def test_registry_refresh_repairs_stale_failover_ids(self):
        self.load()
        devices = self.published()
        devices["gex-1"].vjoy_id = 12
        devices["gex-gp-1"].vjoy_id = 12
        self.registry["_update_joystick_device_maps"]()
        self.assertEqual(devices["gex-1"].vjoy_id, 1)
        self.assertEqual(devices["gex-gp-1"].vjoy_id, -1)

    def test_missing_native_device_keeps_sync_pending_despite_output_summary(self):
        self.local_devices([])
        self.load()
        self.published()
        self.assertTrue(self.maestro._compare_list())
        self.assertTrue(all(not d.input_enabled for d in self.maestro._device_map.values()))
        self.maestro._local_service = False
        self.assertFalse(self.maestro._compare_list())

    def test_unique_native_matches_finish_sync_without_extra_string_keys(self):
        self.active_ids = ["gex-1"]
        native = self.native()
        self.local_devices([native])
        self.load()
        self.published()
        self.assertEqual(self.maestro._device_map, {0: native})
        self.assertFalse(self.maestro._compare_list())

    def test_reassigned_slots_preserve_native_guids_even_with_cached_duplicate_names(self):
        self.definitions = {name: identity.definition(name) for name in ("gex-1", "gex-2")}
        self.active_ids = list(self.definitions)
        devices = [self.native(name) for name in self.active_ids]
        self.local_devices(devices)
        self.load()
        self.published()
        for device in devices:
            device.name = "gex-2"
        self.maestro.LoadActiveControllers({"gex-1": 1, "gex-2": 0})
        self.published()
        self.assertIs(self.maestro._device_map[1], devices[0])
        self.assertIs(self.maestro._device_map[0], devices[1])

    def test_one_native_guid_cannot_be_claimed_by_two_controllers(self):
        self.definitions = {name: identity.definition(name) | dict(name="same") for name in ("gex-1", "gex-2")}
        self.active_ids = list(self.definitions)
        native = self.native("same")
        self.local_devices([native])
        self.load()
        self.maestro.populateDeviceList()
        published = list(self.registry["_maestro_service_devices"].values())
        self.assertEqual(len(published), 2)
        self.assertEqual(sum(d.device_guid == native.device_guid for d in published), 1)

    def test_new_controller_cannot_take_an_existing_native_identity_by_name(self):
        self.definitions = {"gex-2": identity.definition("gex-2") | dict(name="same")}
        self.active_ids = ["gex-2"]
        native = self.native("same")
        self.local_devices([native])
        self.load()
        self.published()
        self.definitions["gex-1"] = identity.definition("gex-1") | dict(name="same")
        self.active_ids.insert(0, "gex-1")
        slots = self.load()
        self.maestro.populateDeviceList()
        self.assertIs(self.maestro._device_map[slots["gex-2"]], native)
        self.assertNotEqual(self.maestro._device_map[slots["gex-1"]].device_guid, native.device_guid)

    def test_native_guid_replacement_does_not_restore_old_joystick(self):
        self.active_ids = ["gex-1"]
        old_native = self.native()
        devices = [old_native]
        self.local_devices(devices)
        self.registry["_all_devices_map"][old_native.device_guid] = self.native(guid=old_native.device_guid)
        self.load()
        self.published()
        new_native = self.native()
        devices[:] = [new_native]
        self.registry["_all_devices_map"][new_native.device_guid] = self.native(guid=new_native.device_guid)
        self.published()
        self.assertEqual(self.registry["_all_joystick_devices"], [new_native])
        self.assertNotIn(old_native.device_guid, self.registry["_joystick_device_guid_map"])
        self.assertNotIn(old_native.device_guid, self.registry["_maestro_replaced_devices"])
        self.assertEqual(new_native.device_type, DeviceType.Maestro)

    def test_removed_native_device_is_not_restored_from_overlay_cache(self):
        self.active_ids = ["gex-1"]
        native = self.native()
        devices = [native]
        self.local_devices(devices)
        self.registry["_all_devices_map"][native.device_guid] = self.native(guid=native.device_guid)
        self.load()
        self.published()
        devices.clear()
        self.active_ids.clear()
        self.load()
        self.published()
        self.assertEqual(self.registry["_all_joystick_devices"], [])
        self.assertEqual(self.registry["_maestro_replaced_devices"], {})
        self.assertEqual(self.maestro._device_map, {})

    def test_deselected_live_native_remains_maestro_input_without_output_slot(self):
        self.active_ids = ["gex-1"]
        native = self.native()
        devices = [native]
        self.local_devices(devices)
        self.registry["_all_devices_map"][native.device_guid] = self.native(guid=native.device_guid)
        self.load()
        self.published()
        current = self.native(guid=native.device_guid)
        current.vjoy_id = 12
        devices[:] = [current]
        CONFIG.maestro_device_map = {}
        self.load()
        self.published()
        self.assertEqual(self.registry["_all_joystick_devices"], [current])
        self.assertEqual(current.device_type, DeviceType.Maestro)
        self.assertTrue(current.is_virtual)
        self.assertTrue(current.input_enabled)
        self.assertEqual(current.virtual_id, -1)
        self.assertEqual(current.vjoy_id, -1)
        self.assertEqual(self.registry["maestro_device_map"](), {})

    def test_standalone_legacy_cache_entries_are_removed_from_every_registry_view(self):
        physical = self.native("Physical controller")
        physical.vendor_id, physical.product_id = 0x045E, 0x028E
        offline_physical = self.native("Saved physical controller")
        offline_physical.setConnected(False)
        vjoy = self.native("VJoy 1")
        vjoy.device_type = DeviceType.VJoy
        vjoy.vjoy_id = vjoy.virtual_id = 1
        vjoy.setConnected(False)
        stale = [self.native(name) for name in ("GEX Custom Device 3", "GEX Custom Device 4", "gex-0", "gex-gp-0", "gex-17")]
        stale[1].device_type = DeviceType.Maestro
        stale[1].setConnected(False)
        for device in (physical, offline_physical, vjoy, *stale):
            self.registry["_all_devices_map"][device.device_guid] = device
            self.registry["_joystick_device_guid_map"][device.device_guid] = device
        self.registry["_all_vjoy_devices_map"][3] = stale[1]
        self.registry["_all_vjoy_devices_map"][1] = vjoy
        self.registry["_maestro_replaced_devices"][stale[0].device_guid] = stale[0]
        orphan = self.native("GEX Custom Device 5")
        self.registry["_joystick_device_guid_map"][orphan.device_guid] = orphan
        self.definitions.clear()
        self.active_ids.clear()
        self.local_devices([physical])
        self.load()
        self.published()
        self.assertCountEqual(self.registry["all_joystick_devices"](), [physical, offline_physical, vjoy])
        self.assertCountEqual(self.registry["_disconnected_devices"], [offline_physical, vjoy])
        self.assertEqual(self.registry["_maestro_devices_map"], {})
        self.assertEqual(self.registry["_all_vjoy_devices_map"], {1: vjoy})
        self.assertEqual(self.registry["_all_virtual_devices_map"][DeviceType.Maestro], {})
        for device in stale:
            self.assertNotIn(device.device_guid, self.registry["_all_devices_map"])
            self.assertNotIn(device.device_guid, self.registry["_joystick_device_guid_map"])
            self.assertNotIn(device.device_guid, self.registry["_disconnected_devices_map"])
            self.assertNotIn(device.device_guid, self.registry["_maestro_replaced_devices"])
        self.assertNotIn(orphan.device_guid, self.registry["_joystick_device_guid_map"])

    def test_fresh_snapshot_removes_maestro_aliases_from_the_native_vjoy_map(self):
        self.active_ids = ["gex-1"]
        self.load()
        device = self.published()["gex-1"]
        self.registry["_all_vjoy_devices_map"][1] = device
        self.published()
        self.assertEqual(self.registry["_all_vjoy_devices_map"], {})
        self.assertEqual(self.registry["_all_virtual_devices_map"][DeviceType.VJoy], {})
        self.assertEqual(self.registry["_maestro_devices_map"], {device.virtual_id: device})

    def test_deleted_service_device_is_not_restored_from_lingering_native_snapshot(self):
        self.active_ids = ["gex-1"]
        native = self.native()
        self.local_devices([native])
        self.registry["_all_devices_map"][native.device_guid] = self.native(guid=native.device_guid)
        self.load()
        self.published()
        del self.definitions["gex-1"]
        self.active_ids.clear()
        self.load()
        self.published()
        self.assertEqual(self.registry["all_joystick_devices"](), [])
        self.assertEqual(self.registry["_maestro_service_devices"], {})
        self.assertEqual(self.maestro._controller_map, {})

    def test_current_inactive_profile_metadata_is_preserved_but_deleted_metadata_is_removed(self):
        saved = self.native("Old label")
        saved.data["maestro_key"] = "maestro://127.0.0.1:8010/gex-1"
        saved.device_type = DeviceType.Maestro
        saved.setConnected(False)
        removed = self.native("Removed device")
        removed.data["maestro_key"] = "maestro://127.0.0.1:8010/deleted"
        removed.device_type = DeviceType.Maestro
        removed.setConnected(False)
        self.registry["_all_devices_map"].update({device.device_guid: device for device in (saved, removed)})
        self.active_ids.clear()
        self.local_devices([])
        self.load()
        self.published()
        self.assertEqual(self.registry["all_joystick_devices"](), [saved])
        self.assertEqual(saved.name, "gex-1")
        self.assertFalse(saved.connected)
        self.assertEqual(saved.virtual_id, -1)
        self.assertEqual(self.registry["maestro_device_map"](), {})

    def test_explicit_inventory_refresh_applies_bridge_after_native_enumeration(self):
        self.active_ids = ["gex-1"]
        native = self.native()
        self.local_devices([native])
        self.registry["_all_devices_map"][native.device_guid] = self.native(guid=native.device_guid)
        self.load()
        self.published()
        del self.definitions["gex-1"]
        self.active_ids.clear()
        stages = []

        def native_refresh(*args, **kwargs):
            stages.append("native")
            self.registry["_update_joystick_device_maps"]()
            return True

        sync_bridge = self.maestro.syncBridge

        def bridge_refresh():
            stages.append("bridge")
            return sync_bridge()

        source_definitions("gremlin/joystick_handling.py", {"refresh_device_inventory"}, self.registry)
        self.registry.update(syslog=MAESTRO.syslog, reset_devices=Mock(side_effect=native_refresh))
        with (patch.object(MAESTRO.dinput.DILL, "init", create=True),
              patch.object(MAESTRO, "Maestro", return_value=self.maestro),
              patch.object(self.maestro, "syncBridge", side_effect=bridge_refresh) as bridge):
            self.registry["all_joystick_devices"](refresh=True)
        self.registry["reset_devices"].assert_called_once_with(False, force=True)
        bridge.assert_called_once_with()
        self.assertEqual(stages, ["native", "bridge"])
        self.assertEqual(self.registry["all_joystick_devices"](), [])

    def test_maestro_dialog_snapshot_reconciles_the_shared_registry_immediately(self):
        self.active_ids = ["gex-1"]
        self.load()
        old = self.published()["gex-1"]
        self.registry["_output_targets"][1] = object()
        del self.definitions["gex-1"]
        self.active_ids.clear()
        snapshot = dict(definitions=list(self.definitions.values()), devices=[], profiles=[])
        dialog = NS(maestro=self.maestro, config=CONFIG)
        with patch.object(MAESTRO, "service_snapshot", return_value=snapshot):
            self.assertIs(MAESTRO.MaestroDialog._read_snapshot(dialog), snapshot)
        self.assertNotIn(old.device_guid, self.registry["_all_devices_map"])
        self.assertEqual(self.registry["all_joystick_devices"](), [])
        self.assertEqual(self.registry["_output_targets"], {})

    def test_failed_bridge_read_is_not_treated_as_an_empty_inventory(self):
        self.active_ids = ["gex-1"]
        self.load()
        old = self.published()["gex-1"]
        source_definitions("gremlin/joystick_handling.py", {"refresh_device_inventory"}, self.registry)
        self.registry.update(syslog=Mock(), reset_devices=Mock(return_value=True))
        self.client.list.side_effect = TimeoutError("Bridge did not reply")
        with (patch.object(MAESTRO.dinput.DILL, "init", create=True),
              patch.object(MAESTRO, "Maestro", return_value=self.maestro)):
            devices = self.registry["all_joystick_devices"](refresh=True)
        self.assertEqual(devices, [old])
        self.registry["syslog"].exception.assert_called_once()

    def test_snapshot_also_prunes_when_maestro_output_is_disabled(self):
        self.active_ids = ["gex-1"]
        self.load()
        old = self.published()["gex-1"]
        CONFIG.maestro_enabled = False
        snapshot = dict(definitions=[], devices=[])
        self.maestro.syncBridge(snapshot=snapshot)
        self.assertNotIn(old.device_guid, self.registry["_all_devices_map"])
        self.assertEqual(self.registry["all_joystick_devices"](), [])
        self.assertEqual(self.registry["_maestro_service_devices"], {})

    def test_preview_of_other_endpoint_does_not_replace_configured_registry(self):
        self.active_ids = ["gex-1"]
        self.load()
        old = self.published()["gex-1"]
        self.client.destination = ("127.0.0.1", 9999)
        snapshot = dict(definitions=[], devices=[], profiles=[])
        dialog = NS(maestro=self.maestro, config=CONFIG)
        with patch.object(MAESTRO, "service_snapshot", return_value=snapshot):
            MAESTRO.MaestroDialog._read_snapshot(dialog)
        self.assertIn(old.device_guid, self.registry["_all_devices_map"])

    def test_zero_based_saved_ids_do_not_keep_obsolete_cache_entries(self):
        self.definitions = {"gex-0": identity.definition("gex-0")}
        self.active_ids.clear()
        old = self.native("GEX Custom Device 0")
        old.data["maestro_key"] = "maestro://127.0.0.1:8010/gex-0"
        old.setConnected(False)
        self.registry["_all_devices_map"][old.device_guid] = old
        self.local_devices([])
        self.load()
        self.published()
        self.assertEqual(self.registry["all_joystick_devices"](), [])


class MaestroGamepadCacheChecks(unittest.TestCase):
    setUp = identity.MaestroIdentityChecks.setUp
    list_devices = identity.MaestroIdentityChecks.list_devices
    request = identity.MaestroIdentityChecks.request
    load = identity.MaestroIdentityChecks.load
    native = MaestroCacheChecks.native
    local_devices = MaestroCacheChecks.local_devices

    def gamepads(self, count=1, *, tokens=True):
        self.definitions = {
            f"gex-gp-{n}": identity.definition(f"gex-gp-{n}") | dict(
                axes=7, buttons=32, vendorId=0x045E, productId=0x02A1,
                **({"instanceToken": f"HM_{0x6000000000000000 + n:016X}"} if tokens else {}))
            for n in range(1, count + 1)
        }
        self.active_ids = list(self.definitions)
        self.rows = []
        self.identities = {}
        self.local_devices(self.rows)
        reader = patch.object(MAESTRO.dinput.DILL, "get_device_identities",
                              side_effect=lambda guids: dict(self.identities), create=True)
        reader.start()
        self.addCleanup(reader.stop)

    def interface(self, number, *, companion=False, name=None, physical=False):
        device = self.native(name or f"gex-gp-{number}")
        device.vendor_id = 0x045E
        device.product_id = 0x0719 if companion else 0x02A1
        device.axis_count, device.button_count, device.hat_count = 5, 16 if companion else 10, 1
        device.setGamepad(True)
        device.axis_id_map = device.linear_id_map = {n: n for n in range(1, 6)}
        container = f"48494430-4d41-4553-6000-{number:012x}"
        if physical:
            container = str(uuid.uuid4())
        self.identities[device.device_guid.hex] = dict(path=f"hid#{device.device_guid}", container_id=container)
        self.rows.append(device)
        self.registry["_all_devices_map"][device.device_guid] = device
        self.registry["_joystick_device_guid_map"][device.device_guid] = device
        return device

    def refresh(self):
        self.load()
        self.maestro.populateDeviceList()
        return self.registry["all_joystick_devices"]()

    def test_native_layout_mismatch_does_not_create_a_synthetic_duplicate(self):
        self.gamepads()
        native = self.interface(1)
        devices = self.refresh()
        self.assertEqual(devices, [native])
        self.assertEqual((native.axis_count, native.button_count), (5, 10))
        self.assertEqual(self.maestro._controller_map[native.virtual_id].button_count, 32)
        output = self.registry["maestro_device_map"]()[native.virtual_id]
        self.assertEqual((output.axis_count, output.button_count), (7, 32))
        self.assertEqual(output.device_guid, self.maestro.controllerGuid(self.maestro._controller_map[native.virtual_id]))
        self.assertIsNot(output, native)
        self.assertFalse(output.input_enabled)
        self.assertTrue(native.data["maestro_native_input"])
        self.assertEqual(native.device_type, DeviceType.Maestro)
        self.assertTrue(native.is_gamepad)
        self.assertTrue(native.input_enabled)
        with patch.object(MAESTRO.dinput.DILL, "get_axis", return_value=12345, create=True) as read:
            self.assertEqual(native.get_axis(1), 12345)
        read.assert_called_once_with(native.device_guid, 1)

    def test_hid_and_xusb_aliases_publish_one_device_in_every_map(self):
        self.gamepads()
        hid = self.interface(1)
        xusb = self.interface(1, companion=True, name="Xbox 360 Wireless Receiver for Windows")
        self.registry["_all_vjoy_devices_map"][3] = xusb
        self.assertEqual(self.refresh(), [hid])
        self.assertEqual(set(hid.data["maestro_native_guids"]), {hid.device_guid, xusb.device_guid})
        for name in ("_all_devices_map", "_joystick_device_guid_map", "_disconnected_devices_map", "_maestro_replaced_devices"):
            self.assertNotIn(xusb.device_guid, self.registry[name])
        self.assertEqual(self.registry["_all_vjoy_devices_map"], {})
        outputs = list(self.registry["_maestro_devices_map"].values())
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0].data["maestro_key"], hid.data["maestro_key"])

    def test_display_inventory_hides_reenumerated_and_profile_aliases(self):
        self.gamepads()
        hid = self.interface(1)
        alias = self.interface(1, companion=True, name="gex-gp-1")
        self.refresh()
        output = hid.data["maestro_output_summary"]
        profile = NS(devices={alias.device_guid: NS(device=alias)},
                     vjoy_devices={output.device_guid: NS(device=output)})
        # A later native refresh may reinsert an interface removed by syncBridge.
        self.registry["_all_devices_map"][alias.device_guid] = alias
        self.registry["_update_joystick_device_maps"]()
        with patch.object(MAESTRO.dinput.DILL, "initialized", True, create=True):
            shown = self.registry["display_devices"](profile)
        self.assertEqual([d.device_guid for d in shown], [hid.device_guid])
        self.assertTrue(shown[0].connected)

    def test_native_arrival_replaces_the_old_synthetic_gamepad(self):
        self.gamepads()
        self.refresh()
        synthetic = self.registry["all_joystick_devices"]()[0]
        hid = self.interface(1)
        self.interface(1, companion=True)
        self.assertEqual(self.refresh(), [hid])
        self.assertNotIn(synthetic.device_guid, self.registry["_all_devices_map"])
        self.assertEqual(self.registry["maestro_device_map"]()[hid.virtual_id].device_guid, synthetic.device_guid)

    def test_two_gamepads_with_cached_identical_names_remain_distinct_and_stable(self):
        self.gamepads(2)
        hid1 = self.interface(1)
        self.interface(1, companion=True)
        hid2 = self.interface(2, name="gex-gp-1")
        self.interface(2, companion=True, name="gex-gp-1")
        devices = self.refresh()
        self.assertCountEqual(devices, [hid1, hid2])
        self.assertEqual((hid1.name, hid2.name), ("gex-gp-1", "gex-gp-2"))
        self.rows.reverse()
        for device in self.rows:
            device.name = "gex-gp-1"
        self.assertCountEqual(self.refresh(), [hid1, hid2])
        self.assertEqual((hid1.name, hid2.name), ("gex-gp-1", "gex-gp-2"))

    def test_same_name_physical_gamepad_is_not_merged_or_marked_virtual(self):
        self.gamepads()
        hid = self.interface(1)
        self.interface(1, companion=True)
        physical = self.interface(1, physical=True)
        physical.axis_count, physical.button_count = 7, 32
        self.assertCountEqual(self.refresh(), [hid, physical])
        self.assertEqual(physical.device_type, DeviceType.Joystick)
        self.assertFalse(physical.is_virtual)
        self.assertNotIn(physical.device_guid, hid.data["maestro_native_guids"])

    def test_unselected_gamepad_aliases_are_also_reconciled_as_native_input(self):
        self.gamepads()
        hid = self.interface(1)
        self.interface(1, companion=True)
        CONFIG.maestro_device_map = {}
        self.assertEqual(self.refresh(), [hid])
        self.assertEqual(hid.virtual_id, -1)
        self.assertTrue(hid.is_virtual)
        self.assertTrue(hid.input_enabled)
        self.assertEqual(self.registry["maestro_device_map"](), {})
        self.assertEqual(self.registry["virtual_devices"](), [])

    def test_deleted_gamepad_removes_all_cached_interfaces_even_during_native_teardown(self):
        self.gamepads()
        hid = self.interface(1)
        xusb = self.interface(1, companion=True)
        self.refresh()
        self.registry["_all_devices_map"][xusb.device_guid] = xusb
        self.definitions.clear()
        self.active_ids.clear()
        self.assertEqual(self.refresh(), [])
        self.assertEqual(self.registry["_maestro_service_devices"], {})
        self.assertNotIn(hid.device_guid, self.registry["_joystick_device_guid_map"])
        self.assertNotIn(xusb.device_guid, self.registry["_joystick_device_guid_map"])

    def test_deactivated_gamepad_does_not_restore_old_native_aliases(self):
        self.gamepads()
        self.interface(1)
        xusb = self.interface(1, companion=True)
        self.refresh()
        self.registry["_all_devices_map"][xusb.device_guid] = xusb
        self.active_ids.clear()
        self.assertEqual(self.refresh(), [])

    def test_bridge_without_tokens_uses_unique_maestro_container(self):
        self.gamepads(tokens=False)
        hid = self.interface(1)
        self.interface(1, companion=True, name="Xbox controller")
        self.assertEqual(self.refresh(), [hid])

    def test_older_bridge_with_identical_cached_names_uses_original_sdk_keys(self):
        from gremlin.maestro_identity import instance_token_for_key

        self.gamepads(2, tokens=False)
        hid1 = self.interface(1)
        xusb1 = self.interface(1, companion=True)
        hid2 = self.interface(2, name="gex-gp-1")
        xusb2 = self.interface(2, companion=True, name="gex-gp-1")
        for number, group in ((1, (hid1, xusb1)), (2, (hid2, xusb2))):
            token = instance_token_for_key(f"MaestroOscService:gex-gp-{number}")[3:].lower()
            for device in group:
                self.identities[device.device_guid.hex]["container_id"] = f"48494430-4d41-4553-{token[:4]}-{token[4:]}"
        self.assertCountEqual(self.refresh(), [hid1, hid2])
        self.assertEqual((hid1.name, hid2.name), ("gex-gp-1", "gex-gp-2"))

    def test_unselected_aliases_are_reconciled_when_maestro_output_is_disabled(self):
        self.gamepads()
        hid = self.interface(1)
        self.interface(1, companion=True)
        CONFIG.maestro_enabled = False
        snapshot = dict(definitions=list(self.definitions.values()), devices=list(self.definitions.values()))
        self.maestro.syncBridge(snapshot=snapshot)
        self.assertEqual(self.registry["all_joystick_devices"](), [hid])
        self.assertEqual(hid.virtual_id, -1)
        self.assertEqual(self.registry["maestro_device_map"](), {})

    def test_bridge_without_tokens_does_not_claim_a_physical_container(self):
        self.gamepads(tokens=False)
        physical = self.interface(1, physical=True)
        self.refresh()
        self.assertEqual(physical.device_type, DeviceType.Joystick)
        self.assertFalse(physical.is_virtual)
        self.assertNotIn(physical.device_guid, next(iter(self.maestro._device_map.values())).data["maestro_native_guids"])

    def test_stale_standard_vid_pid_gamepad_cache_is_removed(self):
        self.gamepads(0)
        for connected in (True, False):
            cached = self.native("gex-gp-1")
            cached.vendor_id, cached.product_id = 0x045E, 0x02A1
            cached.setGamepad(True)
            cached.setConnected(connected)
            self.registry["_all_devices_map"][cached.device_guid] = cached
        self.assertEqual(self.refresh(), [])


class DeviceInformationChecks(unittest.TestCase):
    def setUp(self):
        self.devices = []
        self.config = NS(show_disconnected=True)
        self.query = Mock(side_effect=lambda profile, **kwargs: list(self.devices))
        tree = ast.parse((ROOT / "gremlin/ui/dialogs.py").read_bytes())
        dialog = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DeviceInformationDialog")
        update = next(n for n in dialog.body if isinstance(n, ast.FunctionDef) and n.name == "_update_data")
        color = next(n for n in dialog.body if isinstance(n, ast.FunctionDef) and n.name == "_color")
        namespace = dict(
            QtWidgets=QtWidgets, QtGui=QtGui, DeviceType=DeviceType,
            gremlin=NS(config=NS(Configuration=lambda: self.config),
                       shared_state=NS(is_dark_theme=False),
                       joystick_handling=NS(display_devices=self.query)),
        )
        future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[future, update, color], type_ignores=[])),
                     "gremlin/ui/dialogs.py", "exec"), namespace)
        self.update = namespace["_update_data"]
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(10)
        self.table.setSortingEnabled(True)
        self.dialog = NS(table=self.table, profile=NS(devices={}, vjoy_devices={}))
        self.dialog._color = lambda virtual, connected: namespace["_color"](self.dialog, virtual, connected)
        self.addCleanup(flush_deletes)
        self.addCleanup(self.table.deleteLater)

    def device(self, name, kind=DeviceType.Maestro, **options):
        device = NS(name=name, device_type=kind, disabled=False, connected=True,
                    is_virtual=kind != DeviceType.Joystick, is_gamepad=False,
                    axis_count=8, button_count=128, hat_count=4, vendor_id=0x1209,
                    product_id=0x1000, device_guid=uuid.uuid4(), vjoy_id=-1, data={})
        device.__dict__.update(options)
        self.devices.append(device)
        return device

    def assert_rows_match_devices(self):
        rows = {}
        for row in range(self.table.rowCount()):
            cells = [self.table.item(row, column).text() for column in range(10)]
            self.assertNotIn(cells[7], rows, "Duplicate GUID displayed")
            rows[cells[7]] = cells
        expected = [d for d in self.devices if not d.disabled and (d.connected or self.config.show_disconnected)]
        self.assertEqual(set(rows), {str(d.device_guid) for d in expected})
        for device in expected:
            row = rows[str(device.device_guid)]
            self.assertEqual(row[0], device.name)
            expected_type = device.device_type.name + ("/failover" if device.data.get("failover") else "")
            self.assertEqual(row[1], expected_type)
            self.assertEqual(row[9], "Y" if device.connected else "N")

    def test_sorting_and_refresh_keep_names_types_and_guids_together(self):
        self.device("Physical", DeviceType.Joystick)
        self.device("gex-2")
        self.device("gex-1")
        self.device("VJoy 1", DeviceType.VJoy, vjoy_id=1, data={"failover": True})
        self.device("Offline", connected=False)
        for column in (0, 1, 7, 9):
            for direction in (QtCore.Qt.AscendingOrder, QtCore.Qt.DescendingOrder):
                with self.subTest(column=column, direction=direction):
                    self.table.sortItems(column, direction)
                    for _ in range(3):
                        self.update(self.dialog)
                        self.assert_rows_match_devices()
                        self.assertTrue(self.table.isSortingEnabled())

    def test_refresh_removes_disabled_removed_and_hidden_disconnected_rows(self):
        self.device("gex-2")
        self.device("Disabled", disabled=True)
        self.device("Offline", connected=False)
        self.update(self.dialog)
        self.assert_rows_match_devices()
        self.devices.pop(0)
        self.config.show_disconnected = False
        self.update(self.dialog)
        self.assertEqual(self.table.rowCount(), 0)

    def test_refresh_requests_live_inventory_instead_of_redrawing_the_old_cache(self):
        stale = self.device("GEX Custom Device 3")
        self.update(self.dialog)
        self.assertEqual(self.table.rowCount(), 1)

        def refreshed_inventory(profile, *, refresh):
            self.assertTrue(refresh)
            self.devices.remove(stale)
            return list(self.devices)

        self.query.side_effect = refreshed_inventory
        self.update(self.dialog)
        self.query.assert_called_with(self.dialog.profile, refresh=True)
        self.assertEqual(self.table.rowCount(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
