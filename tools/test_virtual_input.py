"""Hardware-free virtual input checks: python tools/test_virtual_input.py."""

import ast
from dataclasses import dataclass, field
import logging
from pathlib import Path
import sys
import traceback
import threading
import uuid
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from lxml import etree
from PySide6 import QtCore, QtWidgets
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
    profile_loaded = QtCore.Signal()
    tabs_loaded = QtCore.Signal()
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
                               else DeviceCategory.Virtual if self.is_virtual else DeviceCategory.Physical)


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
            shared_state=NS(current_profile=None, is_joystick_suspended=False, is_running=False),
            event_handler=NS(EventListener=lambda: self.events),
            util=NS(normalize_guid=str, is_ui_thread=lambda: True),
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
            QFailoverWidget=lambda: QtWidgets.QLabel("Virtual output failover"),
            safe_format=lambda value, cast: str(value),
            safe_read=lambda node, key, cast, default: (
                (node.get(key).casefold() == "true" if cast is bool else cast(node.get(key)))
                if key in node.attrib
                else default
            ),
            syslog=logging.getLogger("virtual-input-checks"),
            traceback=traceback,
        )
        load("gremlin/base_profile.py", {"Settings"}, self.ui)
        load("gremlin/event_handler.py", {"JoystickState"}, self.ui)
        self.state = self.ui["JoystickState"]()
        self.services.event_handler.JoystickState = lambda: self.state
        self.settings = self.make_settings()
        self.profile = NS(settings=self.settings)
        self.services.shared_state.current_profile = self.profile
        self.services.joystick_handling = NS(
            virtual_devices=lambda connected_only=True: [
                dev for dev in self.devices if dev.is_virtual and (dev.connected or not connected_only)
            ],
            all_joystick_devices=lambda: list(self.devices),
            getAllDevices=lambda: list(self.devices),
            getDevice=lambda guid: next((dev for dev in self.devices if dev.device_id == guid), None),
            getSpecialDevices=lambda: [],
            getConfigDevices=lambda: [],
            getDeviceName=str,
            getDeviceFromVjoyId=lambda index: self.devices[0] if index == 1 else None,
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

    def test_vigem_gamepad_summaries_retain_gamepad_classification(self):
        for vendor, product in ((0x045E, 0x028E), (0x054C, 0x05C4)):
            with self.subTest(vendor=vendor, product=product):
                native = self.native_summary("Virtual controller", vendor, product, usage=5)
                native.setVirtual(True)
                self.assertTrue(native.is_gamepad)
                self.assertTrue(native.is_virtual)

    def test_joysticks_and_other_hid_usages_are_not_gamepads(self):
        for usage_page, usage in ((1, 4), (1, 8), (1, 6), (2, 5), (0, 0)):
            with self.subTest(usage_page=usage_page, usage=usage):
                native = self.native_summary("Controller", usage_page=usage_page, usage=usage)
                self.assertFalse(native.is_gamepad)

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

    def test_unmatched_native_maestros_do_not_become_bridge_output_slots(self):
        natives = [self.native_summary() for _ in range(4)]
        namespace = dict(
            self.ui,
            threading=threading,
            _device_registry_lock=threading.RLock(),
            _all_devices_map={dev.device_guid: dev for dev in natives},
            _maestro_service_devices={},
            _all_virtual_devices_map={},
            _all_vjoy_devices_map={},
            _output_targets={},
        )
        load(
            "gremlin/joystick_handling.py",
            {
                "_update_joystick_device_maps",
                "_update_virtual_map",
                "_apply_maestro_service_devices",
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

    def test_maestro_input_is_available_with_output_failover_enabled(self):
        self.config.virtual_output_failover = True
        load(
            "gremlin/ui/profile_settings.py",
            {"ProfileSettingsWidget"},
            self.ui,
            {"_create_ui", "virtual_as_input_changed"},
            "Widget",
        )
        self.services.shared_state.settings_tab_id = "settings"
        self.services.tabstate = NS(TabState=lambda: NS(getData=lambda key: NS(populateEnabled=True)))
        self.ui["DefaultModeSelector"] = lambda settings: QtWidgets.QLabel("Mode")
        self.ui["DefaultDelay"] = lambda settings: QtWidgets.QLabel("Delay")
        self.services.ui.ui_common.getGridContainer = lambda: (QtWidgets.QWidget(), QtWidgets.QGridLayout())
        self.services.ui.ui_common.getVContainer = self.ui["getVContainer"]
        window = self.ui["ProfileSettingsWidget"]()
        window.profile_settings = self.settings
        window.scroll_layout = QtWidgets.QVBoxLayout(window)
        self.addCleanup(self.delete_widget, window)
        window._create_ui()
        group = window.findChild(self.ui["VirtualAsInputWidget"])
        self.assertIsNotNone(group)
        self.assertIn((DeviceType.Maestro, 0), group._virtual_widgets)
        self.assertEqual(group.title(), "Virtual as Input")

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
        self.ui["Color"] = lambda: NS(alternateActiveColor=lambda: "#8a761c")
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
        self.profile.getLastInput = lambda: ("Maestro 0", None, None)
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
            self.assertEqual(header.count(), 2)
            self.assertEqual(registered["vJoy 1"].data, (TabDeviceType.VjoyInput, "vJoy 1", 0))
            self.assertEqual(registered["Maestro 0"].data, (TabDeviceType.MaestroInput, "Maestro 0", 1))
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
