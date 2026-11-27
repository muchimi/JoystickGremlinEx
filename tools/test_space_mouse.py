"""SpaceMouse discovery, input delivery, and reconnect without a physical device."""

import json
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6 import QtWidgets


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dinput
from gremlin import event_handler, joystick_handling, shared_state
from gremlin.base_profile import Settings
from gremlin.input_types import InputType
from gremlin.types import DeviceType
from gremlin.ui import space_mouse


class HidError(Exception):
    pass


class FakeMouse:
    def __init__(self, info, device):
        self.info = info
        self.device = device
        self.product_name = info.name
        self.state = self.sample(0)
        self.reports = deque()
        self.closed = False

    @staticmethod
    def sample(t, x=0, buttons=(0, 0)):
        return SimpleNamespace(t=t, x=x, y=0, z=0, roll=0, pitch=0, yaw=0, buttons=buttons)

    def open(self):
        self.device.mouse = self

    def read(self):
        if self.reports:
            report = self.reports.popleft()
            if isinstance(report, Exception):
                raise report
            self.state = report
        return self.state

    def close(self):
        self.closed = True


class SpaceMouseChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["space-mouse-tests", "-platform", "offscreen"])

    def setUp(self):
        spec = SimpleNamespace(name="SpaceMouse Compact", vendor_id=0x256F, product_id=0xC635,
                               button_specs=(None, None), button_names=("Left", "Right"))
        self.api = SimpleNamespace(
            get_device_specs=lambda: {spec.name: spec}, apply_axis_convention=lambda info, _: info,
            AxisConvention=SimpleNamespace(HID_Z_UP=1), SpaceMouseDevice=FakeMouse,
        )
        self.interfaces = []
        self.listener = Mock()
        self.profile = SimpleNamespace(devices={}, vjoy_devices={})
        self.config = SimpleNamespace(verbose_mode_space_mouse=False, startup_space_mouse_enabled=True)
        self.enterContext(patch.object(space_mouse, "Configuration", return_value=self.config))
        self.enterContext(patch.object(space_mouse, "EventListener", return_value=self.listener))
        self.enterContext(patch.object(shared_state, "current_profile", self.profile))
        self.enterContext(patch.object(joystick_handling, "_all_devices_map", {}))
        self.enterContext(patch.object(joystick_handling, "_joystick_device_guid_map", {}))
        self.enterContext(patch.object(joystick_handling, "_all_joystick_devices", []))
        self.enterContext(patch.object(joystick_handling, "_joystick_devices", []))
        self.enterContext(patch.object(joystick_handling, "_disconnected_devices", []))
        self.enterContext(patch.object(joystick_handling, "_disconnected_devices_map", {}))
        self.enterContext(patch.object(joystick_handling, "_joystick_initialized", True))
        self.enterContext(patch.object(space_mouse.raw_input, "attached_hid_products", side_effect=self.attached_products))
        self.enumeration = Mock(side_effect=self.enumerate_hid)
        self.manager = space_mouse.SpaceMouseManager(
            self.api, lambda products: space_mouse._enumerate_space_mice(self.enumeration, products), HidError,
        )
        self.addCleanup(self.manager.stop)

    def attached_products(self, usage_page, usage):
        return {
            (device.vendor_id, device.product_id) for device in self.interfaces
            if (device.usage_page, device.usage) == (usage_page, usage)
        }

    def enumerate_hid(self, vendor_id, product_id):
        return SimpleNamespace(find=lambda **query: [
            device for device in self.interfaces
            if (device.vendor_id, device.product_id) == (vendor_id, product_id)
            and all(getattr(device, key) == value for key, value in query.items())
        ])

    def test_skip_hidapi_until_a_supported_space_mouse_appears(self):
        self.interfaces.append(SimpleNamespace(path="unrelated controller", vendor_id=0x256F, product_id=0xFFFF,
                                               usage_page=1, usage=8))
        self.connect("keyboard collection", usage=6)
        self.enumeration.assert_not_called()
        self.assertFalse(self.manager.devices)

        self.connect()
        self.enumeration.assert_called_once_with(0x256F, 0xC635)
        self.assertEqual(list(self.manager.devices), ["controller"])

    def test_disabled_module_skips_startup_detection(self):
        self.config.startup_space_mouse_enabled = False
        with patch.object(space_mouse, "SpaceMouseManager") as start:
            self.assertIsNone(space_mouse.start_space_mouse())
        start.assert_not_called()

    def test_enabled_module_can_be_filtered_without_hardware(self):
        from gremlin.config import Configuration
        from gremlin.ui.dialogs import DeviceDisplayDialog

        if not isinstance(self.app, QtWidgets.QApplication):
            self.skipTest("The current Qt application cannot create widgets.")
        config = Configuration()
        self.enterContext(patch.object(config, "_set_data"))
        self.enterContext(patch.object(config, "_startup_space_mouse_enabled", True))
        self.enterContext(patch.object(joystick_handling, "display_devices", return_value=[]))
        ui = SimpleNamespace(_create_tabs_ui=Mock())
        self.enterContext(patch.object(shared_state, "ui", ui))
        device_id = shared_state.space_mouse_filter_id
        dialog = DeviceDisplayDialog()
        self.addCleanup(dialog.close)
        checkbox = dialog._space_mouse_filter
        self.assertEqual(checkbox.text(), "Space Mouse")
        dialog._set_all_devices_visible(False)
        self.assertFalse(checkbox.isChecked())
        dialog._update_tabs()
        self.assertFalse(dialog.visible_map[device_id])
        config._set_data.assert_any_call("device-visibility", dialog.visible_map)
        ui._create_tabs_ui.assert_called_once()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "visibility.json"
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(path), "")):
                dialog._handle_save_order(None)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {device_id: False})
            checkbox.setChecked(True)
            dialog._load_order_file(str(path))
            self.assertFalse(checkbox.isChecked())

        config._startup_space_mouse_enabled = False
        disabled_dialog = DeviceDisplayDialog()
        self.addCleanup(disabled_dialog.close)
        self.assertIsNone(disabled_dialog._space_mouse_filter)

    def connect(self, path="controller", serial="one", usage=8):
        interface = SimpleNamespace(path=path, serial_number=serial, vendor_id=0x256F, product_id=0xC635,
                                    usage_page=1, usage=usage, set_nonblocking=Mock())
        self.interfaces.append(interface)
        self.manager.scan()
        return interface

    def test_hotplug_exposes_filterable_joystick_summary_and_preserves_id(self):
        self.assertFalse(self.manager.read_timer.isActive())
        self.connect("keyboard collection", usage=6)
        self.assertFalse(self.manager.devices)
        interface = self.connect()
        interface.set_nonblocking.assert_called_once_with(True)
        summary = joystick_handling.getPhysicalDevices()[0]
        guid = summary.device_guid
        self.assertEqual(summary.device_type, DeviceType.SpaceMouse)
        self.assertTrue(Settings.getDeviceFiltered(None, guid))
        self.assertIn(summary, joystick_handling.display_devices(self.profile))
        self.assertEqual([summary.getAxisName(index) for index in summary.axis_index_list()],
                         ["X", "Y", "Z", "Roll", "Pitch", "Yaw"])
        self.assertEqual(summary.get_button_name(2), "Right")
        self.profile.devices[guid] = SimpleNamespace(device=summary)

        interface.mouse.reports.extend([FakeMouse.sample(1, 0.8, (1, 0)), FakeMouse.sample(2, 0.8, (0, 1))])
        self.manager.poll()
        self.assertAlmostEqual(joystick_handling.get_axis(guid, 1), 0.8, places=4)
        self.assertTrue(joystick_handling.get_button(guid, 2))
        event_calls = self.listener.process_joystick_input.call_args_list
        self.assertEqual([(call.args[0].input_type, call.args[0].input_index, call.args[0].value)
                          for call in event_calls], [
            (dinput.InputType.Axis, 1, 26214),
            (dinput.InputType.Button, 1, 1),
            (dinput.InputType.Button, 1, 0),
            (dinput.InputType.Button, 2, 1),
        ])

        # A device can disappear between enumeration and a read.
        interface.mouse.reports.append(HidError())
        self.manager.poll()
        self.assertTrue(interface.mouse.closed)
        self.assertFalse(summary.connected)
        self.assertEqual(joystick_handling.get_axis(guid, 1), 0)
        self.assertFalse(joystick_handling.get_button(guid, 2))
        self.assertFalse(self.manager.read_timer.isActive())
        releases = self.listener.process_joystick_input.call_args_list[-2:]
        self.assertEqual([(call.args[0].input_index, call.args[0].value, call.kwargs["final"])
                          for call in releases], [(1, 0, True), (2, 0, True)])

        self.interfaces.remove(interface)
        self.connect("different USB path")
        reconnected = joystick_handling.getDevice(guid)
        self.assertTrue(reconnected.connected)
        self.assertIs(reconnected, self.profile.devices[guid].device)

    def test_startup_status_is_logged_without_verbose_mode(self):
        with self.assertLogs("system", level="INFO") as logs:
            self.manager.scan(startup=True)
        self.assertEqual([record.getMessage() for record in logs.records],
                         ["SpaceMouse: no supported device connected at startup"])
        with self.assertNoLogs("system", level="INFO"):
            self.connect()
        with self.assertLogs("system", level="INFO") as logs:
            self.manager.scan(startup=True)
        self.assertEqual([record.getMessage() for record in logs.records],
                         ["SpaceMouse: connected at startup: SpaceMouse Compact"])

    def test_verbose_mode_logs_connection_reports_and_disconnect(self):
        self.config.verbose_mode_space_mouse = True
        with self.assertLogs("system", level="INFO") as logs:
            interface = self.connect()
            interface.mouse.reports.append(FakeMouse.sample(1, 0.5, (1, 0)))
            self.manager.poll()
            self.manager.poll()
            self.interfaces.remove(interface)
            self.manager.scan()
        messages = [record.getMessage() for record in logs.records]
        self.assertEqual(len(messages), 3)
        self.assertIn("connected SpaceMouse Compact", messages[0])
        self.assertIn("axes (x, y, z, roll, pitch, yaw)=(0.5, 0, 0, 0, 0, 0) buttons=(True, False)", messages[1])
        self.assertIn("disconnected SpaceMouse Compact", messages[2])

        self.config.verbose_mode_space_mouse = False
        with self.assertNoLogs("system", level="INFO"):
            interface = self.connect()
            interface.mouse.reports.append(FakeMouse.sample(2, 0.5, (1, 0)))
            self.manager.poll()

    def test_gex_dispatch_preserves_space_mouse_source_and_axis_button_keys(self):
        self.connect()
        summary = joystick_handling.getPhysicalDevices()[0]
        listener = Mock(_verbose_dinput=False, _verbose_dinput_extra=False)
        listener._dinput_event_filter.return_value = False
        listener._has_calibration.return_value = False
        listener._apply_curve_ex.return_value = (0.25, True)
        with patch.object(event_handler, "AxisState"), patch.object(event_handler, "DInputState"):
            for native_type, value, mapping_type in (
                (dinput.InputType.Axis, 12345, InputType.JoystickAxis),
                (dinput.InputType.Button, 1, InputType.JoystickButton),
            ):
                sample = dinput.InputEvent.from_values(summary.device_guid, native_type, 1, value)
                event_handler.EventListener.klass.process_joystick_input(listener, sample)
                event = listener.queueJoystickEventList.call_args.args[0][0]
                self.assertEqual(event.event_type, mapping_type)
                self.assertEqual(event.source_input_type, InputType.SpaceMouse)
                self.assertEqual(event.device_guid, summary.device_guid)
                self.assertEqual(event.identifier, 1)
        self.assertEqual(DeviceType.to_enum(DeviceType.to_string(DeviceType.SpaceMouse)), DeviceType.SpaceMouse)
        self.assertEqual(InputType.to_enum(InputType.to_string(InputType.SpaceMouse)), InputType.SpaceMouse)

    def test_buffered_button_edges_are_not_dropped_as_bounce(self):
        self.connect()
        summary = joystick_handling.getPhysicalDevices()[0]
        listener = Mock()
        input_filter = event_handler.EventListener.klass._dinput_event_filter
        for value in (1, 0, 1, 0):
            sample = dinput.InputEvent.from_values(summary.device_guid, dinput.InputType.Button, 1, value)
            self.assertFalse(input_filter(listener, summary, sample))
        summary.disabled = True
        self.assertTrue(input_filter(listener, summary, sample))


if __name__ == "__main__":
    unittest.main()
