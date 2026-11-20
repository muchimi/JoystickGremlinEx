"""Hardware-free virtual input checks: python tools/test_virtual_input.py."""

import ast
from dataclasses import dataclass, field
import enum
import html
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import traceback
import threading
import uuid
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from lxml import etree
from PySide6 import QtCore, QtGui, QtWidgets
from psygnal import Signal
from shiboken6 import Shiboken
from test_maestro_startup import COMMON
from test_qt_marshalling import APP, flush_deletes

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.input_types import InputType
from gremlin.types import DeviceCategory, DeviceType, TabDeviceType


class ServiceImports(ast.NodeTransformer):
    def visit_Import(self, node):
        return None if all(alias.name.startswith(("gremlin", "vjoy")) for alias in node.names) else node

    def visit_ImportFrom(self, node):
        return None if node.module and node.module.startswith("gremlin") else node


def load(path, names, namespace, methods=None, base=None):
    tree = ast.parse((ROOT / path).read_bytes())
    nodes = [node for node in tree.body if getattr(node, "name", None) in names]
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            node.decorator_list = []
            if methods is not None:
                node.body = [item for item in node.body if isinstance(item, ast.FunctionDef) and item.name in methods]
                assert not methods - {item.name for item in node.body}, methods - {item.name for item in node.body}
            if base is not None:
                node.bases = [ast.Name(id=base, ctx=ast.Load())]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ServiceImports().visit(ast.Module(body=[future, *nodes], type_ignores=[]))
    exec(compile(ast.fix_missing_locations(module), path, "exec"), namespace)


class Events(QtCore.QObject):
    virtual_as_input_changed = QtCore.Signal()
    remote_control_client_change = QtCore.Signal()
    profile_loaded = QtCore.Signal()
    tabs_loaded = QtCore.Signal()
    config_option_changed = QtCore.Signal()
    device_initialized = QtCore.Signal()
    device_change_event = QtCore.Signal()


@dataclass(eq=False)
class Device:
    name: str
    device_type: DeviceType = DeviceType.Maestro
    virtual_id: int = 0
    vjoy_id: int = -1
    connected: bool = True
    disabled: bool = False
    input_enabled: bool = True
    visible: bool = True
    axis_count: int = 2
    button_count: int = 4
    hat_count: int = 1
    vendor_id: int = 0
    product_id: int = 0
    data: dict = field(default_factory=dict)

    device_id = property(lambda self: self.name)
    device_guid = property(lambda self: self.name)
    device_name = property(lambda self: self.name)
    enabled = property(lambda self: self.connected and not self.disabled)
    is_virtual = property(lambda self: self.device_type in (DeviceType.VJoy, DeviceType.Maestro))
    device_category = property(lambda self: DeviceCategory.Config if self.device_type in (DeviceType.Settings, DeviceType.Plugins)
                               else DeviceCategory.Virtual if self.is_virtual
                               else DeviceCategory.Physical if self.device_type == DeviceType.Joystick
                               else DeviceCategory.Special)


class VirtualInputChecks(unittest.TestCase):
    def setUp(self):
        self.devices = [
            Device("vJoy 1", DeviceType.VJoy, virtual_id=1, vjoy_id=1),
            Device("Maestro 0"),
            Device("Maestro 1", virtual_id=1),
            Device("Physical", DeviceType.Joystick),
        ]
        self.events = Events()
        self.config = NS(
            verbose_mode_ui=False,
            verbose_mode_joystick=False,
            verbose_mode_vjoy=False,
            verbose_mode_ui_level=lambda level: False,
            virtual_output_failover=False,
            tab_list={},
            setDeviceVisible=Mock(),
            isDeviceVisible=lambda guid: True,
        )
        self.services = NS(
            config=NS(Configuration=lambda: self.config),
            shared_state=NS(current_profile=None, is_joystick_suspended=False, is_running=False, is_dark_theme=False),
            event_handler=NS(EventListener=lambda: self.events),
            util=NS(normalize_guid=str, is_ui_thread=lambda: True, load_icon=lambda name: QtGui.QIcon(str(ROOT / "icons" / name))),
        )
        self.ui = dict(
            COMMON,
            gremlin=self.services,
            etree=etree,
            Signal=Signal,
            InputType=InputType,
            DeviceType=DeviceType,
            DeviceCategory=DeviceCategory,
            TabDeviceType=TabDeviceType,
            Widget=QtWidgets.QWidget,
            EventListener=lambda: self.events,
            QInfoBox=QtWidgets.QLabel,
            QFailoverWidget=lambda **kwargs: QtWidgets.QLabel("Virtual output failover"),
            safe_format=lambda value, cast: str(value),
            safe_read=lambda node, key, cast, default: (
                (node.get(key).casefold() == "true" if cast is bool else cast(node.get(key)))
                if key in node.attrib
                else default
            ),
            syslog=logging.getLogger("virtual-input-checks"),
            traceback=traceback,
        )
        self.ui.update(enum=enum, ElementTree=etree)
        load("gremlin/remote.py", {"ClientOperation", "OutputMode", "_client_address_key", "read_client_selection", "write_client_selection"}, self.ui)
        load("gremlin/base_profile.py", {"Settings"}, self.ui)
        load("gremlin/event_handler.py", {"JoystickState"}, self.ui)
        self.state = self.ui["JoystickState"]()
        self.services.event_handler.JoystickState = lambda: self.state
        self.settings = self.make_settings()
        self.profile = NS(settings=self.settings, devices={}, vjoy_devices={})
        self.services.shared_state.current_profile = self.profile
        self.services.joystick_handling = NS(
            virtual_devices=lambda connected_only=True: [
                dev for dev in self.devices if dev.is_virtual and (dev.connected or not connected_only)
            ],
            all_joystick_devices=lambda: list(self.devices),
            display_devices=lambda profile: list(self.devices),
            getAllDevices=lambda: list(self.devices),
            getDevice=lambda guid: next((dev for dev in self.devices if dev.device_id == guid), None),
            getSpecialDevices=lambda: [],
            getConfigDevices=lambda: [],
            getDeviceName=str,
            getDeviceFromVjoyId=lambda index: self.devices[0] if index == 1 else None,
            get_native_vjoy_devices=lambda: [dev for dev in self.devices if dev.device_type == DeviceType.VJoy and dev.connected],
            maestro_info_from_index=lambda index: next(
                (dev for dev in self.devices if dev.device_type == DeviceType.Maestro and dev.virtual_id == index), None
            ),
            vjoy_info_from_vjoy_id=lambda index: self.devices[0] if index == 1 else None,
            VJoyProxy=Mock(return_value={1: NS(ensure_released=Mock())}),
            joystick_initialized=lambda: True,
        )
        load(
            "gremlin/joystick_handling.py",
            {
                "virtual_input_candidates",
                "virtual_input_devices",
                "axis_input_devices",
                "button_input_devices",
                "hat_input_devices",
                "filtered_input_devices",
            },
            self.ui,
        )
        self.ui["virtual_devices"] = self.services.joystick_handling.virtual_devices
        self.ui["all_joystick_devices"] = self.services.joystick_handling.all_joystick_devices
        self.ui["_all_joystick_devices"] = self.devices
        for name in ("virtual_input_candidates", "virtual_input_devices"):
            setattr(self.services.joystick_handling, name, self.ui[name])
        load("gremlin/ui/ui_common.py", {"QDataCheckbox", "QScrollableWidget"}, self.ui)
        load("gremlin/ui/ui_common.py", {"Icons"}, self.ui, {"deviceMappingIcon"})
        self.services.ui = NS(
            ui_common=NS(
                QRememberDialog=self.ui["QRememberDialog"],
                QDataPushButton=self.ui["QDataPushButton"],
                QScrollableWidget=self.ui["QScrollableWidget"],
                getHContainer=self.ui["getHContainer"],
            )
        )
        load("gremlin/input_item.py", {"VirtualAsInputDialog"}, self.ui)
        load("gremlin/ui/profile_settings.py", {"VirtualAsInputWidget"}, self.ui)
        self.state.hook()

    def make_settings(self):
        settings = self.ui["Settings"].__new__(self.ui["Settings"])
        settings._virtual_as_input = {}
        settings.vjoy_initial_values, settings.input_visible_map = {}, {}
        settings.startup_mode, settings.default_delay = None, 0.05
        settings.loadFilterDefaults = Mock()
        settings.profile = NS(profile_file=None)
        settings.reset()
        return settings

    def widget(self, name):
        widget = self.ui[name](self.settings)
        self.addCleanup(self.delete_widget, widget)
        return widget

    def delete_widget(self, widget):
        if Shiboken.isValid(widget):
            widget.deleteLater()
        flush_deletes()

    def native_summary(self, name="GEX Custom Device 3", vendor=1, product=1, usage_page=1, usage=4):
        self.services.types = NS(DeviceType=DeviceType, DeviceCategory=DeviceCategory)
        self.ui.update(
            GUID=uuid.UUID,
            VJOY_VID=0x1234,
            VJOY_PID=0xBEAD,
            MAESTRO_VID=0x1209,
            GEX_VID=0x1209,
            GEX_PID_BASE=0x1000,
            GEX_PID_MAX=0x100F,
            GEX_PRODUCT_STRING="GEX Custom Device",
        )
        load("dinput/__init__.py", {"DeviceSummary"}, self.ui)
        native = self.ui["DeviceSummary"](
            NS(
                device_guid=str(uuid.uuid4()),
                vendor_id=vendor,
                product_id=product,
                joystick_id=0,
                name=name.encode(),
                axis_count=8,
                button_count=128,
                hat_count=4,
                usage_page=usage_page,
                usage=usage,
                axis_map=[],
            )
        )
        native.device_category = DeviceCategory.Virtual if native.is_virtual else DeviceCategory.Physical
        return native

    def test_hardware_gamepads_are_recognized_by_hid_usage(self):
        for vendor, product in ((0x045E, 0x028E), (0x054C, 0x05C4), (0x0F0D, 0x00C1)):
            with self.subTest(vendor=vendor, product=product):
                native = self.native_summary("HID controller", vendor, product, usage=5)
                self.assertTrue(native.is_gamepad)
                self.assertTrue(native._is_gamepad)
                self.assertFalse(native.is_virtual)

    def test_vigem_gamepad_summaries_remain_physical_for_gex(self):
        for vendor, product in ((0x045E, 0x028E), (0x054C, 0x05C4)):
            with self.subTest(vendor=vendor, product=product):
                native = self.native_summary("Virtual controller", vendor, product, usage=5)
                native.setVirtual(True)
                self.assertTrue(native.is_gamepad)
                self.assertFalse(native.is_virtual)
                self.assertEqual(native.device_category, DeviceCategory.Physical)

    def test_joysticks_and_other_hid_usages_are_not_gamepads(self):
        for usage_page, usage in ((1, 4), (1, 8), (1, 6), (2, 5), (0, 0)):
            with self.subTest(usage_page=usage_page, usage=usage):
                native = self.native_summary("Controller", usage_page=usage_page, usage=usage)
                self.assertFalse(native.is_gamepad)

    def test_sequential_gex_hardware_ids_are_native_virtual_inputs(self):
        for pid in (*range(0x4701, 0x4801), *range(0x4801, 0x4805), 0x4901, 0x49FF):
            with self.subTest(pid=pid):
                native = self.native_summary("Pilot controls", vendor=1, product=pid,
                                             usage=5 if 0x4801 <= pid <= 0x4804 else 4)
                self.assertEqual(native.device_type, DeviceType.Maestro)
                self.assertTrue(native.is_virtual)
                self.assertTrue(native.input_enabled)
                self.assertTrue(native.data["maestro_native_input"])
                self.assertEqual(native.virtual_id, -1)
                self.assertEqual(native.is_gamepad, 0x4801 <= pid <= 0x4804)
        for vid, pid in ((2, 0x4701), (1, 0x4700), (1, 0x4805), (1, 0x4900)):
            with self.subTest(vid=vid, pid=pid):
                native = self.native_summary("gex-1", vendor=vid, product=pid)
                self.assertEqual(native.device_type, DeviceType.Joystick)
                self.assertFalse(native.is_virtual)

    def test_native_gex_classification_with_placeholder_vid_pid(self):
        native = self.native_summary()
        self.assertEqual(native.device_type, DeviceType.Maestro)
        self.assertTrue(native.is_virtual)
        self.assertTrue(native.input_enabled)
        self.assertEqual(native.virtual_id, -1)
        # The shared placeholder VID/PID alone must not classify other hardware.
        physical = self.native_summary("Physical joystick")
        self.assertEqual(physical.device_type, DeviceType.Joystick)
        self.assertFalse(physical.is_virtual)

    def test_identically_named_native_maestros_have_independent_profile_inputs(self):
        natives = [self.native_summary() for _ in range(4)]
        self.devices.extend(natives)
        self.state.reset()
        self.assertTrue(all(dev in self.ui["virtual_input_candidates"]() for dev in natives))
        self.assertTrue(all(not self.state.inputEnabled(dev.device_id) for dev in natives))
        group = self.widget("VirtualAsInputWidget")
        self.assertTrue(all((DeviceType.Maestro, dev.device_id) in group._virtual_widgets for dev in natives))
        dialog = self.widget("VirtualAsInputDialog")
        group._dialog = dialog
        dialog.accepted.connect(group._accepted)
        selected = natives[1]
        checkbox = next(widget for widget in dialog._widgets if widget.data == (DeviceType.Maestro, selected.device_id))
        checkbox.setChecked(True)
        dialog.accept()
        self.assertEqual(self.ui["virtual_input_devices"](), [selected])
        self.assertTrue(self.state.inputEnabled(selected.device_id))
        self.assertTrue(all(not self.state.inputEnabled(dev.device_id) for dev in natives if dev is not selected))
        self.config.setDeviceVisible.assert_called_once_with(selected.device_guid, True)
        saved = self.settings.to_xml()
        self.assertEqual(saved.xpath("maestro-input/@guid"), [selected.device_id])
        restored = self.make_settings()
        restored.from_xml(saved)
        self.assertTrue(restored.getVirtualAsInput(selected))
        self.assertTrue(all(not restored.getVirtualAsInput(dev) for dev in natives if dev is not selected))
        # A later successful bridge match must preserve the saved native selection.
        selected.virtual_id = 2
        self.assertTrue(restored.getVirtualAsInput(selected))
        load("gremlinEx.py", {"GremlinUi"}, self.ui, {"_get_sorted_tab_map"}, "Widget")
        window = self.ui["GremlinUi"]()
        self.addCleanup(self.delete_widget, window)
        window.config, window.profile = self.config, self.profile
        for tab_list in ({}, {i: (dev.device_id, True) for i, dev in enumerate(natives)}):
            self.config.tab_list = tab_list
            self.assertEqual(set(window._get_sorted_tab_map()["sorted"]), {self.devices[3], selected})
        self.settings.setVirtualAsInput(selected, False)
        self.assertFalse(self.state.inputEnabled(selected.device_id))

    def test_new_devices_join_their_group_without_moving_saved_settings_and_plugins(self):
        plugins = Device("Plugins", DeviceType.Plugins, disabled=True, visible=False)
        settings = Device("Settings", DeviceType.Settings, disabled=True, visible=False)
        wheel = Device("WingMan Formula GP", DeviceType.Joystick)
        stick = Device("T.16000M", DeviceType.Joystick)
        self.devices.extend([plugins, settings, wheel, stick])
        self.services.joystick_handling.getConfigDevices = lambda: [plugins, settings]
        self.config.device_visible_map = {plugins.device_id: False, settings.device_id: False}
        selected = self.devices[2]
        self.settings.setVirtualAsInput(selected, True)
        load("gremlinEx.py", {"GremlinUi"}, self.ui, {"_get_sorted_tab_map"}, "Widget")
        window = self.ui["GremlinUi"]()
        self.addCleanup(self.delete_widget, window)
        window.config, window.profile = self.config, self.profile
        for saved in (
            {"9": (selected.device_id, True), "2": (settings.device_id, False),
             "6": (self.devices[3].device_id, True), "3": (plugins.device_id, False),
             "8": (wheel.device_id, True), "4": (self.devices[1].device_id, True)},
            {"9": selected.device_id, "2": settings.device_id, "6": self.devices[3].device_id,
             "3": plugins.device_id, "8": wheel.device_id, "4": self.devices[1].device_id},
        ):
            with self.subTest(saved=saved):
                self.config.tab_list = saved
                result = window._get_sorted_tab_map()
                expected = [settings, plugins, self.devices[3], wheel, stick, selected]
                self.assertEqual(result["sorted"], expected)
                expected_ids = [dev.device_id for dev in expected]
                self.assertEqual(list(result["tab_map"].values()), expected_ids)
                self.assertEqual(list(result["index_map"].values()), expected_ids)
                self.assertEqual([row[0] for row in result["sorted_tuples"]], expected_ids)
                self.assertTrue(plugins.visible and settings.visible)
                self.assertNotIn(self.devices[1], result["sorted"])
        self.config.tab_list = {}
        self.assertEqual(window._get_sorted_tab_map()["sorted"][-2:], [settings, plugins])

    def test_default_order_groups_hardware_virtual_inputs_special_and_fixed_tabs(self):
        special = [Device(kind.name, kind) for kind in DeviceType if kind not in (
            DeviceType.NotSet, DeviceType.Joystick, DeviceType.VJoy, DeviceType.Maestro,
            DeviceType.Settings, DeviceType.Plugins,
        )]
        gamepad = Device("A gamepad", DeviceType.Joystick)
        missing = Device("Z missing stick", DeviceType.Joystick, connected=False)
        settings = Device("Settings", DeviceType.Settings, visible=False)
        plugins = Device("Plugins", DeviceType.Plugins, visible=False)
        self.devices.extend([*reversed(special), plugins, gamepad, settings, missing])
        self.services.joystick_handling.getSpecialDevices = lambda: special
        self.services.joystick_handling.getConfigDevices = lambda: [plugins, settings]
        for device in self.devices[:2]:
            self.settings.setVirtualAsInput(device)
        load("gremlinEx.py", {"GremlinUi"}, self.ui, {"_get_sorted_tab_map"}, "Widget")
        window = self.ui["GremlinUi"]()
        self.addCleanup(self.delete_widget, window)
        window.config, window.profile = self.config, self.profile
        expected = [gamepad, self.devices[3], missing, self.devices[1], self.devices[0],
                    *sorted(special, key=lambda device: device.name.casefold()), settings, plugins]
        self.assertEqual(window._get_sorted_tab_map()["sorted"], expected)
        self.config.tab_list = {index: (device.device_id, True) for index, device in enumerate(reversed(expected))}
        self.assertEqual(window._get_sorted_tab_map(reset=True)["sorted"], expected)

    def test_visibility_flags_do_not_replace_an_explicit_manual_tab_order(self):
        first = Device("Z stick", DeviceType.Joystick)
        second = Device("A stick", DeviceType.Joystick)
        keyboard = Device("Keyboard", DeviceType.Keyboard)
        self.devices[:] = [first, second, keyboard]
        self.services.joystick_handling.getSpecialDevices = lambda: [keyboard]
        saved = {0: (keyboard.device_id, True), 1: (first.device_id, True), 2: (second.device_id, False)}
        self.config.tab_list = saved
        self.config.device_visible_map = {first.device_id: False, second.device_id: True}
        load("gremlinEx.py", {"GremlinUi"}, self.ui, {"_get_sorted_tab_map"}, "Widget")
        window = self.ui["GremlinUi"]()
        self.addCleanup(self.delete_widget, window)
        window.config, window.profile = self.config, self.profile
        result = window._get_sorted_tab_map()
        self.assertEqual(result["sorted"], [keyboard, first, second])
        self.assertEqual(result["invisible"], [first])
        self.assertIs(self.config.tab_list, saved)

    def test_sort_tabs_keeps_every_special_module_and_places_fixed_tabs_last(self):
        kinds = [DeviceType.Plugins, DeviceType.State, DeviceType.Overlay, DeviceType.Keyboard,
                 DeviceType.Maestro, DeviceType.Settings, DeviceType.Joystick, DeviceType.Voice,
                 DeviceType.ModeControl, DeviceType.VJoy, DeviceType.Afcs, DeviceType.OctaviIFR1]
        self.devices[:] = [Device(kind.name, kind) for kind in kinds]
        tabs = {index: NS(device=device, device_guid=device.device_guid, tab_type=TabDeviceType.Joystick)
                for index, device in enumerate(self.devices)}
        load("gremlinEx.py", {"GremlinUi"}, self.ui, {"_sort_tabs_worker"}, "Widget")
        window = self.ui["GremlinUi"]()
        self.addCleanup(self.delete_widget, window)
        window.config = NS(verbose=False)
        window._get_tab_map = lambda: tabs
        window._reset_tab_data = Mock()
        window.getTabCount = lambda: 0
        window._add_tab_ui = Mock()
        window._select_last_tab = Mock()
        window._select_last_input = lambda **kwargs: setattr(window, "_tab_sorted_flag", True)
        window._handle_tabs_sorted_completed = Mock()
        window._sort_tabs_worker(None)
        self.assertEqual([call.args[0].name for call in window._add_tab_ui.call_args_list], [
            "Joystick", "Maestro", "VJoy", "Afcs", "Keyboard", "ModeControl", "OctaviIFR1",
            "Overlay", "State", "Voice", "Settings", "Plugins",
        ])

    def test_visibility_layouts_ignore_positions_in_new_and_legacy_files(self):
        physical = self.devices[3]
        keyboard = Device("Keyboard", DeviceType.Keyboard)
        self.devices.append(keyboard)
        self.ui.update(json=json, os=os, MessageBoxWarning=Mock())
        load("gremlin/ui/dialogs.py", {"DeviceDisplayDialog"}, self.ui, {"_load_order_file"}, "Widget")
        dialog = self.ui["DeviceDisplayDialog"]()
        self.addCleanup(self.delete_widget, dialog)
        dialog.config = self.config
        dialog._order_changed = False
        dialog._get_current_map = lambda: {0: (keyboard.device_id, False), 1: (physical.device_id, True)}
        dialog._populate_list_widget = Mock()
        layouts = (
            {physical.device_id: False, keyboard.device_id: True, "Offline": False},
            {"9": [physical.device_id, False], "0": [keyboard.device_id, True]},
            {"9": physical.device_id, "0": keyboard.device_id},
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "visibility.json"
            for index, layout in enumerate(layouts):
                with self.subTest(layout=layout):
                    dialog.visible_map = {}
                    path.write_text(json.dumps(layout), encoding="utf-8")
                    dialog._load_order_file(str(path))
                    rows = list(dialog._populate_list_widget.call_args.args[0].values())
                    self.assertEqual(rows, [(keyboard, True), (physical, index == 2)])
                    self.assertFalse(dialog._order_changed)
                    if index == 0:
                        self.assertFalse(dialog.visible_map["Offline"])
        self.ui["MessageBoxWarning"].assert_not_called()

    def test_applying_visibility_preserves_order_until_the_user_moves_a_row(self):
        self.services.shared_state.ui = NS(_create_tabs_ui=Mock())
        load("gremlin/ui/dialogs.py", {"DeviceDisplayDialog"}, self.ui,
             {"_update_tabs", "_handle_order_changed"}, "Widget")
        dialog = self.ui["DeviceDisplayDialog"]()
        self.addCleanup(self.delete_widget, dialog)
        dialog.config = self.config
        saved = {0: ("Existing manual order", True)}
        self.config.tab_list = saved
        dialog.visible_map = {"Offline": False}
        dialog._order_changed = False
        dialog._device_enabled = lambda device: True
        dialog._list_widget = QtWidgets.QListWidget(dialog)
        for device, visible in ((self.devices[3], False), (self.devices[0], True)):
            item = QtWidgets.QListWidgetItem(dialog._list_widget)
            item.setData(QtCore.Qt.UserRole, (device, visible))
        dialog._update_tabs()
        self.assertIs(self.config.tab_list, saved)
        self.assertEqual(self.config.device_visible_map, {"Offline": False, "Physical": False, "vJoy 1": True})
        dialog._handle_order_changed()
        dialog._update_tabs()
        self.assertEqual(self.config.tab_list, {0: ("Physical", False), 1: ("vJoy 1", True)})

    def test_saved_visibility_file_contains_device_flags_without_positions(self):
        self.ui.update(json=json, MessageBoxWarning=Mock())
        load("gremlin/ui/dialogs.py", {"DeviceDisplayDialog"}, self.ui, {"_handle_save_order"}, "Widget")
        dialog = self.ui["DeviceDisplayDialog"]()
        self.addCleanup(self.delete_widget, dialog)
        dialog._get_current_map = lambda: {0: ("Physical", False), 1: ("vJoy 1", True)}
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            self.services.shared_state.data_path = folder
            path = Path(folder) / "visibility.json"
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(path), "")):
                dialog._handle_save_order(None)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"Physical": False, "vJoy 1": True})
        self.ui["MessageBoxWarning"].assert_not_called()

    def test_settings_and_plugins_cannot_be_filtered_by_rows_bulk_actions_or_layouts(self):
        plugins = Device("Plugins", DeviceType.Plugins, disabled=True, visible=False)
        settings = Device("Settings", DeviceType.Settings, disabled=True, visible=False)
        self.devices.extend([plugins, settings])
        self.services.shared_state.ui = NS(_create_tabs_ui=Mock())
        self.ui.update(
            json=json, os=os, MessageBoxWarning=Mock(), dinput=NS(DeviceSummary=Device),
            QListWidgetItem=QtWidgets.QListWidgetItem, QListWidget=QtWidgets.QListWidget,
            QAbstractItemView=QtWidgets.QAbstractItemView, QLabel=QtWidgets.QLabel,
            Color=lambda: NS(alternateActiveColor=lambda: "#8a761c", disconnectedColor=lambda: "#db6512"),
        )
        self.services.util.InvokeUiMethod = lambda callback, *args: callback(*args)
        load("gremlin/ui/dialogs.py", {"ReorderDeviceListWidget", "ReorderListWidget"}, self.ui)
        load("gremlin/ui/dialogs.py", {"DeviceDisplayDialog"}, self.ui, {
            "_device_enabled", "_populate_list_widget", "_set_all_devices_visible", "_handle_visible_changed",
            "_get_current_map", "_load_order_file", "_update_tabs",
        }, "Widget")
        dialog = self.ui["DeviceDisplayDialog"]()
        self.addCleanup(self.delete_widget, dialog)
        dialog.config = self.config
        dialog._order_changed = False
        dialog.visible_map = {plugins.device_id: False, settings.device_id: False}
        dialog._list_widget = self.ui["ReorderListWidget"](dialog)
        original = {0: (plugins, False), 1: (self.devices[3], True), 2: (settings, False)}
        dialog._populate_list_widget(original)

        def assert_always_on():
            self.assertEqual(list(dialog._get_current_map().values())[::2], [("Plugins", True), ("Settings", True)])
            for index in (0, 2):
                item = dialog._list_widget.item(index)
                row = dialog._list_widget.itemWidget(item)
                self.assertTrue(row.visible_widget.isChecked())
                self.assertFalse(row.visible_widget.isEnabled())
                self.assertTrue(item.flags() & QtCore.Qt.ItemFlag.ItemIsDragEnabled)
                self.assertTrue(dialog.visible_map[row.data.device_id])

        assert_always_on()
        for visible in (False, True):
            dialog._set_all_devices_visible(visible)
            assert_always_on()
        row = dialog._list_widget.itemWidget(dialog._list_widget.item(0))
        dialog._handle_visible_changed(row.visible_widget, False)
        assert_always_on()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "visibility.json"
            path.write_text(json.dumps({"Plugins": False, "Physical": False, "Settings": False}), encoding="utf-8")
            dialog._load_order_file(str(path))
        assert_always_on()
        dialog._update_tabs()
        self.assertTrue(self.config.device_visible_map["Settings"])
        self.assertTrue(self.config.device_visible_map["Plugins"])
        self.assertEqual(self.config.tab_list, {})
        self.ui["MessageBoxWarning"].assert_not_called()

    def test_profile_only_disconnected_device_gets_a_tab_in_default_and_saved_order(self):
        missing = Device("Old left VPC", DeviceType.Joystick, connected=False)
        # Profile-only placeholders are registered in the general device map,
        # but are absent from the native joystick inventory.
        shown = [*self.devices, missing]
        self.services.joystick_handling.display_devices = lambda profile: shown
        self.services.joystick_handling.getAllDevices = lambda: shown
        self.services.joystick_handling.getDevice = lambda guid: next((d for d in shown if d.device_id == guid), None)
        load("gremlinEx.py", {"GremlinUi"}, self.ui, {"_get_sorted_tab_map"}, "Widget")
        window = self.ui["GremlinUi"]()
        self.addCleanup(self.delete_widget, window)
        window.config, window.profile = self.config, self.profile
        for saved in ({}, {0: (missing.device_id, True), 1: (self.devices[3].device_id, True)}):
            with self.subTest(saved=bool(saved)):
                self.config.tab_list = saved
                result = window._get_sorted_tab_map()
                self.assertIn(missing, result["sorted"])
                self.assertIn(missing, result["disconnected"])
                self.assertNotIn(missing, result["physical"])
                if saved:
                    self.assertIs(result["sorted"][0], missing)

    def test_tab_connection_state_uses_profile_aware_snapshot(self):
        cached = self.devices[3]
        missing = Device(cached.name, DeviceType.Joystick, connected=False)
        self.services.joystick_handling.display_devices = lambda profile: [missing]
        load("gremlinEx.py", {"GremlinUi"}, self.ui, {"_get_sorted_tab_map"}, "Widget")
        window = self.ui["GremlinUi"]()
        self.addCleanup(self.delete_widget, window)
        window.config, window.profile = self.config, self.profile
        self.config.tab_list = {0: (cached.device_id, True)}
        result = window._get_sorted_tab_map()
        self.assertEqual(result["disconnected"], [missing])
        self.assertNotIn(cached, result["physical"])
        self.assertIs(result["sorted"][0], missing)

    def test_missing_tab_uses_disconnected_icon_color_and_tooltip(self):
        cached = self.devices[3]
        missing = Device(cached.name, DeviceType.Joystick, connected=False)
        self.ui["Color"] = lambda: NS(tabMissingForegroundColor=lambda: "missing-color")
        self.ui["Icons"] = NS(disconnectedIcon=lambda: "missing-icon")
        load("gremlinEx.py", {"GremlinUi"}, self.ui, {"_update_tab_ui"}, "Widget")
        window = self.ui["GremlinUi"]()
        self.addCleanup(self.delete_widget, window)
        window._all_devices_map = {missing.device_id: missing}
        window.getTabIndexForDevice = lambda guid: 0
        header = Mock()
        window.ui = NS(devices_tab_header_widget=header)
        # The registry still reports connected, but tabs use the reconciled snapshot.
        window._update_tab_ui(missing.device_id)
        header.setTabIcon.assert_called_once_with(0, "missing-icon")
        header.setTabTextColor.assert_called_once_with(0, "missing-color")
        self.assertIn("Disconnected", header.setTabToolTip.call_args.args[1])
        self.assertIn(missing.device_id, header.setTabToolTip.call_args.args[1])
        header.reset_mock()
        window.getTabIndexForDevice = lambda guid: -1
        window._update_tab_ui(missing)
        header.setTabIcon.assert_not_called()
        header.setTabTextColor.assert_not_called()
        header.setTabToolTip.assert_not_called()

    def test_unmatched_native_maestros_do_not_become_bridge_output_slots(self):
        natives = [self.native_summary() for _ in range(4)]
        namespace = dict(
            self.ui,
            threading=threading,
            _device_registry_lock=threading.RLock(),
            _all_devices_map={dev.device_guid: dev for dev in natives},
            _maestro_service_devices={},
            _maestro_excluded_native_guids=set(),
            _joystick_device_guid_map={},
            _all_virtual_devices_map={},
            _all_vjoy_devices_map={},
            _output_targets={},
            updateFailoverMap=Mock(),
        )
        load(
            "gremlin/joystick_handling.py",
            {
                "_update_joystick_device_maps",
                "_update_virtual_map",
                "_apply_maestro_service_devices",
                "_replace_device_registry",
                "_maestro_output_summary",
            },
            namespace,
        )
        namespace["_update_joystick_device_maps"]()
        self.assertEqual(namespace["_maestro_devices_map"], {})
        self.assertEqual(set(namespace["_all_joystick_devices"]), set(natives))

    def test_provider_indices_are_independent_and_roundtrip_legacy_xml(self):
        self.settings.setVirtualAsInput(self.devices[0], True)
        self.settings.setVirtualAsInput(self.devices[1], True)
        self.settings.setVirtualAsInput(self.devices[2], False)
        saved = self.settings.to_xml()
        self.assertEqual(saved.xpath("vjoy-input/@id"), ["1"])
        self.assertEqual(saved.xpath("maestro-input/@id"), ["0", "1"])
        self.assertEqual(saved.xpath('maestro-input[@enabled="False"]/@id'), ["1"])
        restored = self.make_settings()
        restored.from_xml(saved)
        self.assertEqual(restored.getVirtualAsInputList(DeviceType.VJoy), [1])
        self.assertEqual(restored.getVirtualAsInputList(DeviceType.Maestro), [0])
        self.assertFalse(restored.getVirtualAsInput(self.devices[2]))
        restored.from_xml(etree.fromstring('<settings><vjoy-input id="1"/></settings>'))
        self.assertTrue(restored.getVirtualAsInput(self.devices[0]))
        self.assertFalse(restored.getVirtualAsInput(self.devices[1]))

    def test_candidates_exclude_output_only_failover_disconnected_and_disabled_devices(self):
        self.devices.extend(
            [
                Device("Remote", virtual_id=3, input_enabled=False),
                Device("Failover", DeviceType.VJoy, vjoy_id=2, data={"failover": True}),
                Device("Offline", virtual_id=4, connected=False),
                Device("Disabled", virtual_id=5, disabled=True),
            ]
        )
        self.assertEqual(self.ui["virtual_input_candidates"](), self.devices[:3])
        self.settings.setVirtualAsInput(self.devices[1])
        for name in ("axis_input_devices", "button_input_devices", "hat_input_devices"):
            self.assertEqual(self.ui[name](), [self.devices[3], self.devices[1]])

    def test_input_selectors_only_offer_selected_virtual_devices(self):
        filtered = self.ui["filtered_input_devices"]
        types = [InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat]
        self.assertEqual(filtered(types), [self.devices[3]])
        self.assertEqual(filtered(types, virtual_only=True), [])
        self.settings.setVirtualAsInput(self.devices[1])
        self.assertEqual(filtered(types), [self.devices[3], self.devices[1]])
        self.assertEqual(filtered(types, virtual_only=True), [self.devices[1]])
        self.settings.setVirtualAsInput(self.devices[1], False)
        self.assertEqual(filtered(types), [self.devices[3]])

    def test_input_selector_filters_requested_capabilities(self):
        self.devices[3].axis_count = 0
        filtered = self.ui["filtered_input_devices"]
        self.assertEqual(filtered([InputType.JoystickAxis]), [])
        self.assertEqual(filtered([InputType.JoystickButton]), [self.devices[3]])
        self.assertEqual(filtered([InputType.Keyboard]), [])

    def test_joystick_and_axis_source_widgets_use_profile_input_selection(self):
        self.services.joystick_handling.filtered_input_devices = self.ui["filtered_input_devices"]
        self.services.joystick_handling.axis_input_devices = self.ui["axis_input_devices"]
        load("gremlin/ui/ui_common.py", {"JoystickSelector"}, self.ui, {"_initialize"}, "Widget")
        load("gremlin/ui/ui_common.py", {"QAxisSourceSelector"}, self.ui, {"_refresh_devices"}, "Widget")
        combo = QtWidgets.QComboBox()
        self.addCleanup(self.delete_widget, combo)
        joystick = NS(valid_types=[InputType.JoystickAxis], device_list=[])
        axis = NS(_device_selector_widget=combo, _exclude_list=[])
        for selected in (False, True, False):
            with self.subTest(selected=selected):
                self.settings.setVirtualAsInput(self.devices[1], selected)
                expected = [self.devices[3], self.devices[1]] if selected else [self.devices[3]]
                joystick.device_list.clear()
                self.ui["JoystickSelector"]._initialize(joystick)
                self.assertEqual(set(joystick.device_list), set(expected))
                self.ui["QAxisSourceSelector"]._refresh_devices(axis)
                self.assertEqual([combo.itemData(i) for i in range(combo.count())], expected)

    def test_dialog_select_all_and_cancel_do_not_modify_profile(self):
        dialog = self.widget("VirtualAsInputDialog")
        dialog._set_all(True)
        self.assertEqual(
            dialog.virtual_map,
            {(DeviceType.VJoy, 1): True, (DeviceType.Maestro, 0): True, (DeviceType.Maestro, 1): True},
        )
        dialog.reject()
        self.assertEqual(self.settings.getVirtualAsInputList(DeviceType.VJoy), [])
        self.assertEqual(self.settings.getVirtualAsInputList(DeviceType.Maestro), [])

    def test_accept_applies_both_providers_and_emits_one_refresh(self):
        group = self.widget("VirtualAsInputWidget")
        dialog = self.widget("VirtualAsInputDialog")
        group._dialog = dialog
        dialog.accepted.connect(group._accepted)
        load(
            "gremlin/ui/profile_settings.py", {"ProfileSettingsWidget"}, self.ui, {"virtual_as_input_changed"}, "Widget"
        )
        receiver = self.ui["ProfileSettingsWidget"]()
        self.addCleanup(self.delete_widget, receiver)
        group.changed.connect(receiver.virtual_as_input_changed)
        observed = []
        self.events.virtual_as_input_changed.connect(
            lambda: observed.append(
                (
                    self.settings.getVirtualAsInputList(DeviceType.VJoy),
                    self.settings.getVirtualAsInputList(DeviceType.Maestro),
                )
            )
        )
        dialog._set_all(True)
        dialog.accept()
        self.assertEqual(observed, [([1], [0, 1])])
        self.assertTrue(self.state.inputEnabled("Maestro 0"))
        self.assertEqual(self.config.setDeviceVisible.call_count, 3)
        self.assertIn((DeviceType.Maestro, 0), group._virtual_widgets)
        self.services.joystick_handling.VJoyProxy.assert_called_once_with()
        self.services.joystick_handling.VJoyProxy()[1].ensure_released.assert_called_once_with()

    def test_state_reset_uses_profile_selections_without_mutating_them(self):
        self.settings.setVirtualAsInput(self.devices[1])
        changed = Mock()
        self.events.virtual_as_input_changed.connect(changed)
        self.state.reset()
        self.assertTrue(self.state.inputEnabled("Maestro 0"))
        self.assertFalse(self.state.inputEnabled("Maestro 1"))
        self.assertFalse(self.state.inputEnabled("vJoy 1"))
        self.assertTrue(self.state.inputEnabled("Physical"))
        self.assertFalse(self.state.outputIgnored("Maestro 0"))
        changed.assert_not_called()
        self.settings.setVirtualAsInput(self.devices[1], False)
        self.assertFalse(self.state.inputEnabled("Maestro 0"))

    def test_hotplug_restores_selection_for_a_new_directinput_identity(self):
        self.settings.setVirtualAsInput(self.devices[1])
        self.devices[1] = Device("Reconnected Maestro", virtual_id=0)
        self.events.device_change_event.emit()
        self.assertTrue(self.state.inputEnabled("Reconnected Maestro"))
        self.assertFalse(self.state.inputEnabled("Maestro 0"))

    def test_device_mapping_shortcut_requires_failover_without_native_vjoy(self):
        remap = Mock()
        self.services.shared_state.ui = NS(_remap_profile_devices_cb=remap)
        widget = self.widget("VirtualAsInputWidget")
        button = widget._device_mapping_button
        self.assertTrue(button.isHidden())

        self.config.virtual_output_failover = True
        self.events.config_option_changed.emit()
        self.assertTrue(button.isHidden())

        native_vjoy = self.devices[0]
        native_vjoy.connected = False
        self.events.device_change_event.emit()
        self.assertFalse(button.isHidden())

        self.devices.append(Device("Failover vJoy", DeviceType.VJoy, data={"failover": True}))
        self.events.profile_loaded.emit()
        self.assertFalse(button.isHidden())
        button.click()
        remap.assert_called_once_with()

        native_vjoy.connected = True
        self.events.device_initialized.emit()
        self.assertTrue(button.isHidden())

        native_vjoy.connected = False
        self.config.virtual_output_failover = False
        self.events.config_option_changed.emit()
        self.assertTrue(button.isHidden())

    def test_maestro_input_is_available_with_output_failover_enabled(self):
        self.config.virtual_output_failover = True
        load(
            "gremlin/ui/profile_settings.py",
            {"ProfileSettingsWidget"},
            self.ui,
            {"_create_ui", "_startup_remote_clients_changed", "virtual_as_input_changed"},
            "Widget",
        )
        load("gremlin/ui/ui_common.py", {"QDataRadioButton", "QDataRadioButtonGroup"}, self.ui)
        load("gremlin/remote.py", {"SelectionBehavior", "RemoteClientOptionsWidget", "RemoteClientSelectionWidget", "remote_client_row_label"}, self.ui)
        known = {"cockpit-pc": "Test & panel", "panel-pc": ""}
        self.ui["remote_control"] = NS(getKnownClients=lambda: known.copy())
        self.ui["html"] = html
        self.ui["Color"] = lambda: NS(
            cssButton=lambda: "",
            normalColor=lambda: "#111111",
            actionBackgroundColor=lambda: "#cccccc",
            borderColor=lambda: "#111111",
        )
        self.ui["show_remote_clients"] = Mock()

        def clear_rows(layout):
            while layout.count():
                row = layout.takeAt(0).widget()
                row.hide()
                row.deleteLater()

        self.services.util.clear_layout = clear_rows
        self.services.shared_state.settings_tab_id = "settings"
        self.services.tabstate = NS(TabState=lambda: NS(getData=lambda key: NS(populateEnabled=True)))
        self.ui["DefaultModeSelector"] = lambda settings: QtWidgets.QLabel("Mode")
        self.ui["DefaultDelay"] = lambda settings: QtWidgets.QLabel("Delay")
        self.services.ui.ui_common.getGridContainer = lambda: (QtWidgets.QWidget(), QtWidgets.QGridLayout())
        self.ui["getGridContainer"] = self.services.ui.ui_common.getGridContainer
        self.services.ui.ui_common.getVContainer = self.ui["getVContainer"]
        window = self.ui["ProfileSettingsWidget"]()
        window.profile_settings = self.settings
        window.changed = Mock()
        window.scroll_layout = QtWidgets.QVBoxLayout(window)
        self.addCleanup(self.delete_widget, window)
        window._create_ui()
        group = window.findChild(self.ui["VirtualAsInputWidget"])
        self.assertIsNotNone(group)
        self.assertIn((DeviceType.Maestro, 0), group._virtual_widgets)
        self.assertEqual(group.title(), "Virtual as Input")
        options = window.findChild(self.ui["RemoteClientOptionsWidget"])
        self.assertIs(options.operation, self.ui["ClientOperation"].EnableAll)
        self.assertIs(options.output_mode, self.ui["OutputMode"].LocalOnly)
        next(radio for radio in options.findChildren(QtWidgets.QRadioButton) if radio.text() == "Selection").click()
        clients = window.findChild(self.ui["RemoteClientSelectionWidget"])
        self.assertIsNotNone(clients)
        panel = next(check for check in clients.findChildren(QtWidgets.QCheckBox) if check.accessibleName() == "Include panel-pc")
        self.assertTrue(panel.isChecked())
        panel.setChecked(False)
        self.assertEqual(self.settings.startup_remote_clients, frozenset({"cockpit-pc"}))
        self.assertTrue(any(
            label.text() == "<b>cockpit-pc</b> — Test &amp; panel" and "border-radius: 6px" in label.styleSheet()
            for label in clients.findChildren(QtWidgets.QLabel)
        ))
        buttons = {button.text(): button for button in clients.findChildren(QtWidgets.QPushButton)}
        self.assertEqual(set(buttons), {"Select All", "Select None", "Edit Clients…", "Solo"})
        buttons["Edit Clients…"].click()
        self.ui["show_remote_clients"].assert_called_once_with(clients)

        known["new-pc"] = ""
        self.events.remote_control_client_change.emit()
        self.assertEqual(self.settings.startup_remote_clients, frozenset({"cockpit-pc"}))
        self.assertEqual(clients._clients.getLayout().count(), 3)

        self.assertFalse(any(check.text() == "Hold" for check in options.findChildren(QtWidgets.QCheckBox)))
        for label in ("Mute all", "Both"):
            next(radio for radio in options.findChildren(QtWidgets.QRadioButton) if radio.text() == label).click()
        self.assertIs(self.settings.startup_remote_operation, self.ui["ClientOperation"].DisableAll)
        self.assertIs(self.settings.startup_remote_output_mode, self.ui["OutputMode"].LocalAndRemote)
        self.assertTrue(clients.isHidden())
        reopened = self.make_settings()
        reopened.from_xml(self.settings.to_xml())
        self.assertIs(reopened.startup_remote_operation, self.ui["ClientOperation"].DisableAll)
        self.assertIs(reopened.startup_remote_output_mode, self.ui["OutputMode"].LocalAndRemote)
        self.assertEqual(reopened.startup_remote_clients, frozenset({"cockpit-pc"}))

    def test_new_and_legacy_profile_remote_startup_defaults(self):
        self.assertIs(self.settings.startup_remote_operation, self.ui["ClientOperation"].EnableAll)
        self.assertIs(self.settings.startup_remote_output_mode, self.ui["OutputMode"].LocalOnly)
        self.assertIsNone(self.settings.startup_remote_clients)
        saved = self.settings.to_xml()
        self.assertEqual(saved.get("startup-remote-operation"), "enable-all")
        self.assertEqual(saved.get("startup-remote-output-mode"), "local-only")
        self.settings.from_xml(etree.fromstring(b'<settings><startup-remote-clients><client address="panel"/></startup-remote-clients></settings>'))
        self.assertIs(self.settings.startup_remote_operation, self.ui["ClientOperation"].Select)
        self.assertIs(self.settings.startup_remote_output_mode, self.ui["OutputMode"].Unchanged)
        self.assertEqual(self.settings.startup_remote_clients, frozenset({"panel"}))

    def test_saved_tab_order_only_includes_selected_virtual_inputs(self):
        load("gremlinEx.py", {"GremlinUi"}, self.ui, {"_get_sorted_tab_map"}, "Widget")
        window = self.ui["GremlinUi"]()
        self.addCleanup(window.deleteLater)
        window.config, window.profile = self.config, self.profile
        self.settings.setVirtualAsInput(self.devices[1])
        for tab_list in ({}, {0: ("Maestro 1", True), 1: ("Maestro 0", True), 2: ("vJoy 1", True)}):
            with self.subTest(tab_list=tab_list):
                self.config.tab_list = tab_list
                result = window._get_sorted_tab_map()
                self.assertEqual(result["maestro"], [self.devices[1]])
                self.assertEqual(result["vjoy"], [])
                self.assertEqual(set(result["sorted"]), {self.devices[1], self.devices[3]})

    def test_device_visibility_list_only_includes_selected_virtual_inputs(self):
        self.ui["Color"] = lambda: NS(alternateActiveColor=lambda: "#8a761c", disconnectedColor=lambda: "#db6512")
        self.services.util.InvokeUiMethod = lambda callback, *args: callback(*args)
        self.ui.update(dinput=NS(DeviceSummary=Device), QListWidgetItem=QtWidgets.QListWidgetItem)
        self.ui.update(QListWidget=QtWidgets.QListWidget, QAbstractItemView=QtWidgets.QAbstractItemView, QLabel=QtWidgets.QLabel)
        load("gremlin/ui/dialogs.py", {"ReorderDeviceListWidget", "ReorderListWidget"}, self.ui)
        load(
            "gremlin/ui/dialogs.py",
            {"DeviceDisplayDialog"},
            self.ui,
            {"_device_enabled", "_populate_list_widget", "_handle_visible_changed",
             "_handle_select_all", "_handle_select_none", "_set_all_devices_visible", "_get_current_map"},
            "Widget",
        )
        dialog = self.ui["DeviceDisplayDialog"]()
        self.addCleanup(self.delete_widget, dialog)
        dialog._list_widget = self.ui["ReorderListWidget"](dialog)
        dialog.visible_map = {}
        tab_map = {i: (dev, True) for i, dev in enumerate(self.devices)}

        def populate():
            dialog._populate_list_widget(tab_map)
            return [dialog._list_widget.item(i).data(QtCore.Qt.UserRole)[0] for i in range(dialog._list_widget.count())]

        self.assertEqual(populate(), [self.devices[3]])
        for device in self.devices[:2]:
            self.settings.setVirtualAsInput(device)
        self.assertEqual(populate(), [self.devices[0], self.devices[1], self.devices[3]])
        item = dialog._list_widget.item(0)
        row = dialog._list_widget.itemWidget(item)
        dialog.show()
        dialog._list_widget.show()
        APP.processEvents()
        self.assertIsInstance(row.visible_widget, self.ui["QDataCheckbox"])
        self.assertEqual(row.name_widget.text(), self.devices[0].name)
        self.assertTrue(row.name_widget.property("deviceVisible"))
        self.assertTrue(row.visible_widget.isVisible())
        self.assertGreater(row.visible_widget.width(), 0)
        checked_indicator = row.visible_widget.grab().toImage()
        row.visible_widget.click()
        self.assertNotEqual(checked_indicator, row.visible_widget.grab().toImage())
        self.assertFalse(dialog.visible_map[self.devices[0].device_id])
        self.assertEqual(item.data(QtCore.Qt.UserRole), (self.devices[0], False))
        self.assertFalse(row.name_widget.property("deviceVisible"))
        row.visible_widget.click()
        self.assertTrue(dialog.visible_map[self.devices[0].device_id])
        self.assertEqual(item.data(QtCore.Qt.UserRole), (self.devices[0], True))
        self.assertTrue(row.name_widget.property("deviceVisible"))
        row.setDeviceVisible(False)
        self.assertFalse(row.visible_widget.isChecked())
        self.assertFalse(row.name_widget.property("deviceVisible"))
        # Bulk actions must cover rows absent from the sparse visibility map,
        # update persisted item values, and leave fixed system rows alone.
        fixed_item = dialog._list_widget.item(2)
        fixed_row = dialog._list_widget.itemWidget(fixed_item)
        fixed_row.setVisibleEnabled(False)
        original_order = [device_id for device_id, _ in dialog._get_current_map().values()]
        for handler, visible in ((dialog._handle_select_none, False), (dialog._handle_select_all, True)):
            handler(None)
            for index in range(dialog._list_widget.count()):
                current_item = dialog._list_widget.item(index)
                current_row = dialog._list_widget.itemWidget(current_item)
                device, saved_visible = current_item.data(QtCore.Qt.UserRole)
                expected = True if current_row is fixed_row else visible
                self.assertEqual(current_row.visible_widget.isChecked(), expected)
                self.assertEqual(current_row.name_widget.property("deviceVisible"), expected)
                self.assertEqual(saved_visible, expected)
                if current_row is not fixed_row:
                    self.assertEqual(dialog.visible_map[device.device_id], expected)
            self.assertEqual([device_id for device_id, _ in dialog._get_current_map().values()], original_order)
        self.settings.setVirtualAsInput(self.devices[0], False)
        self.devices[1].input_enabled = False
        self.assertEqual(populate(), [self.devices[3]])

        # Missing profile devices remain eligible even without a live virtual input slot.
        offline = [Device("Missing joystick", DeviceType.Joystick, connected=False),
                   Device("Missing vJoy", DeviceType.VJoy, connected=False),
                   Device("Missing Maestro", connected=False)]
        orphan = Device("Old profile joystick", DeviceType.Joystick, connected=False)
        self.profile.devices = {device.device_guid: NS(device=device) for device in offline}
        for device in (*offline, orphan):
            tab_map[len(tab_map)] = (device, True)
        shown = populate()
        self.assertEqual(shown, [self.devices[3], *offline])
        for index in range(1, dialog._list_widget.count()):
            offline_row = dialog._list_widget.itemWidget(dialog._list_widget.item(index))
            self.assertTrue(offline_row.name_widget.property("deviceDisconnected"))
            self.assertIn("Disconnected", offline_row.name_widget.toolTip())
            offline_row.name_widget.ensurePolished()
            text_color = QtGui.QPalette.ColorRole.WindowText
            self.assertEqual(offline_row.name_widget.palette().color(text_color).name(), "#db6512")
            self.assertTrue(offline_row.name_widget.text().endswith("(disconnected)"))
            offline_row.setDeviceVisible(False)
            self.assertEqual(offline_row.name_widget.palette().color(text_color).name(), "#db6512")

    def test_tab_creation_uses_joystick_editors_for_both_virtual_providers(self):
        class InputEditor(QtWidgets.QWidget):
            def __init__(self, device, **kwargs):
                super().__init__()
                self.device = device
                self.ensureSelectedVisible = Mock()

        self.devices[:] = self.devices[:2]
        for dev in self.devices:
            self.settings.setVirtualAsInput(dev)
        self.ui["BaseDeviceTabWidget"] = InputEditor
        self.services.ui.joystick_device = NS(JoystickDeviceTabWidget=InputEditor)
        self.services.tabstate = NS(TabState=lambda: NS(getData=lambda guid: NS()))
        self.services.shared_state.current_mode = "Default"
        self.services.shared_state.device_profile_map = {}
        self.services.shared_state.device_type_map = {}
        for name in (
            "push_redraw",
            "pop_redraw",
            "push_input_selection",
            "pop_input_selection",
            "push_suspend_save_input",
            "pop_suspend_save_input",
            "reload_device_map",
        ):
            setattr(self.services.shared_state, name, Mock())
        self.services.util.compare_guid = lambda a, b: a == b
        self.services.util.singleShot = lambda callback: callback()
        self.config.verbose_mode_device = self.config.verbose_mode_l1 = self.config.verbose_mode_extra = False
        self.config.device_visible_map = {}
        self.config.last_device_guid = "Maestro 0"
        self.config.get_last_input = lambda guid: (guid, None, None)
        selection_cleanup_counts = []
        self.profile.getLastInput = lambda: (
            selection_cleanup_counts.append(window._unregister_all_widgets_ui.call_count)
            or ("Maestro 0", None, None)
        )
        self.profile.get_device_modes = Mock(return_value=NS())
        self.profile.first_input = Mock(return_value=None)
        self.profile.isRemovedDevice = lambda guid: False
        self.events.push_input_selection = Mock()
        logger = Mock()
        self.ui["syslog"] = logger
        load(
            "gremlinEx.py", {"GremlinUi"}, self.ui,
            {"_get_sorted_tab_map", "_create_tabs_ui", "current_mode", "_resolve_tab_selection"}, "Widget"
        )
        window = self.ui["GremlinUi"]()
        self.addCleanup(self.delete_widget, window)
        window.config, window.profile = self.config, self.profile
        window._suspend_ui_update = 0
        window._creating_tabs = window._tabs_rebuild_pending = window._ui_enable_after_refresh = False
        window._tab_device_map, window._tab_index_map = {}, {}
        header = QtWidgets.QTabBar(window)
        window.ui = NS(devices_tab_header_widget=header)
        registered = {}
        window.getRegisteredWidget = registered.get
        window._has_mapping = lambda *args: False
        window.registerWidget = lambda guid, widget: registered.update({guid: widget})
        window.getTabIndexForDevice = lambda guid: window._tab_device_map.get(guid)
        window.getActiveTabDeviceGuid = lambda: "Maestro 0"

        def clear_tabs():
            while header.count():
                header.removeTab(0)
            window._tab_device_map.clear()
            window._tab_index_map.clear()

        def add_tab(device, tab_type, **kwargs):
            index = header.addTab(device.name)
            header.setTabData(index, NS(device_guid=device.device_guid))
            window._tab_device_map[device.device_guid] = index
            window._tab_index_map[index] = device.device_guid

        window._clear_tabs_ui, window._add_tab_ui = clear_tabs, add_tab
        for name in (
            "_begin_ui_refresh_ui",
            "_finish_ui_refresh_ui",
            "pushLoading",
            "popLoading",
            "_unregister_all_widgets_ui",
            "clearWidgets",
            "_reset_tab_data",
            "push_highlighting",
            "pop_highlighting",
            "_reindex_tabs",
            "_update_highlight_toolbar_enabled",
            "_select_input",
            "_schedule_startup_input_restore",
            "setCurrentTabTracking",
            "setUIState",
            "selectTabWidget",
        ):
            setattr(window, name, Mock())
        for _ in range(2):
            window._create_tabs_ui()
            self.assertEqual(selection_cleanup_counts, list(range(_ + 1)))
            self.assertEqual(header.count(), 2)
            self.assertEqual(registered["vJoy 1"].data, (TabDeviceType.VjoyInput, "vJoy 1", 1))
            self.assertEqual(registered["Maestro 0"].data, (TabDeviceType.MaestroInput, "Maestro 0", 0))
            logger.error.assert_not_called()
        self.settings.setVirtualAsInput(self.devices[1], False)
        window._create_tabs_ui()
        self.assertEqual(header.count(), 1)
        self.assertEqual(header.tabText(0), "vJoy 1")
        self.assertEqual(window._select_input.call_args.args[0], "vJoy 1")
        with self.subTest("fixed configuration tab remains available when devices are hidden"):
            class ConfigEditor(QtWidgets.QWidget):
                def __init__(self, settings):
                    super().__init__()
                    self.ensureLoaded = Mock()

            settings_device = Device("Settings", DeviceType.Settings, disabled=True, visible=False,
                                     axis_count=0, button_count=0, hat_count=0)
            self.devices.append(settings_device)
            self.services.shared_state.settings_tab_guid = settings_device.device_guid
            self.services.joystick_handling.getConfigDevices = lambda: [settings_device]
            self.services.ui.profile_settings = NS(ProfileSettingsWidget=ConfigEditor)
            self.config.tab_list = {index: (dev.device_id, False) for index, dev in enumerate(self.devices)}
            self.config.device_visible_map = {dev.device_id: False for dev in self.devices}
            self.profile.isRemovedDevice = lambda guid: guid == settings_device.device_guid
            window._select_input.reset_mock()
            window.selectTabWidget.reset_mock()
            window._create_tabs_ui()
            self.assertEqual(header.count(), 1)
            self.assertEqual(header.tabData(0).device_guid, settings_device.device_guid)
            window.selectTabWidget.assert_called_once_with(settings_device.device_guid)
            registered[settings_device.device_guid].ensureLoaded.assert_called_once_with()
            window._select_input.assert_not_called()
            logger.error.assert_not_called()

        with self.subTest("empty registry leaves no stale selection"):
            self.devices.clear()
            self.services.joystick_handling.getConfigDevices = lambda: []
            self.config.tab_list = {}
            window.selectTabWidget.reset_mock()
            window._create_tabs_ui()
            self.assertEqual(header.count(), 0)
            window.selectTabWidget.assert_not_called()
            logger.error.assert_not_called()
        for widget in registered.values():
            self.delete_widget(widget)

    def test_maestro_events_use_directinput_and_stop_when_deselected(self):
        native_types = NS(Axis=1, Button=2, Hat=3)
        self.ui.update(
            dinput=NS(InputEvent=lambda event: event, InputType=native_types),
            Event=lambda **kwargs: NS(**kwargs),
            AxisState=lambda: NS(shouldProcess=lambda event: True),
            DInputState=lambda: NS(shouldProcess=lambda event: True),
            dill_hat_lookup={9000: (1, 0)},
        )
        load(
            "gremlin/event_handler.py",
            {"EventListener"},
            self.ui,
            {"_dinput_event_handler", "_queue_settled_axis_event"},
            "Widget",
        )
        listener = self.ui["EventListener"]()
        self.addCleanup(listener.deleteLater)
        listener.js = self.state
        listener._verbose_dinput = listener._verbose_dinput_extra = False
        listener._dinput_event_filter = Mock(return_value=False)
        listener._has_calibration = lambda *args: False
        listener._apply_curve_ex = lambda guid, index, value: (value, False)
        listener._hat_state = {}
        listener.axis_state_change = NS(emit=Mock())
        listener.queueJoystickEventList = Mock()
        listener.shouldProcessVjoy = Mock(side_effect=AssertionError("Maestro must not use vJoy loopback"))
        self.services.util.scale_to_range = lambda value, **kwargs: value / 32767
        self.settings.setVirtualAsInput(self.devices[1])
        for native_type, value, expected in (
            (1, 16000, InputType.JoystickAxis),
            (2, 1, InputType.JoystickButton),
            (3, 9000, InputType.JoystickHat),
        ):
            with self.subTest(input_type=expected):
                listener.queueJoystickEventList.reset_mock()
                listener._dinput_event_handler(
                    NS(device_guid="Maestro 0", input_index=1, input_type=native_type, value=value)
                )
                events = listener.queueJoystickEventList.call_args.args[0]
                self.assertEqual(events[-1].event_type, expected)
                self.assertTrue(events[-1].is_virtual)
        self.settings.setVirtualAsInput(self.devices[1], False)
        listener.queueJoystickEventList.reset_mock()
        listener._dinput_event_filter.reset_mock()
        listener._dinput_event_handler(NS(device_guid="Maestro 0", input_index=1, input_type=1, value=1234))
        listener._queue_settled_axis_event("Maestro 0", 1, 1234, True)
        listener._dinput_event_filter.assert_not_called()
        listener.queueJoystickEventList.assert_not_called()

    def tearDown(self):
        flush_deletes()


if __name__ == "__main__":
    unittest.main(verbosity=2)
