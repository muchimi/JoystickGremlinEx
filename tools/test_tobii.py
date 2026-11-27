"""Hardware-free regression checks for the Tobii Game Hub UDP input."""

import socket
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6 import QtCore, QtWidgets


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gremlin.base_profile  # initialize the normal profile/action import order
import dinput
from gremlin.types import DeviceType
from gremlin.ui import tobii
from gremlin.ui.tobii.gaze import normalize_gaze


class TobiiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["tobii-tests", "-platform", "offscreen"])

    def test_pose_decoding_checks_size_and_finite_values(self):
        self.assertEqual(tobii.decode_pose(tobii.POSE_PACKET.pack(25, -50, 100, 90, -180, -360)),
                         (16384, -32767, 32767, 16384, -32767, -32767))
        self.assertIsNone(tobii.decode_pose(b"\0" * 49))
        self.assertIsNone(tobii.decode_pose(tobii.POSE_PACKET.pack(float("nan"), 0, 0, 0, 0, 0)))
        self.assertIsNone(tobii.decode_pose(tobii.POSE_PACKET.pack(0, float("inf"), 0, 0, 0, 0)))

    def test_gaze_coordinates_normalize_pixels_and_reject_invalid_values(self):
        self.assertEqual(normalize_gaze(960, 540, 1920, 1080), (0, 0))
        self.assertEqual(normalize_gaze(2000, 0, 1920, 1080), (32767, 32767))
        self.assertIsNone(normalize_gaze(True, 0, 1920, 1080))
        self.assertIsNone(normalize_gaze(float("nan"), 0, 1920, 1080))

    def test_loopback_udp_stream_registers_six_axes_before_traffic_and_centers_after_timeout(self):
        listener = Mock()
        offline = SimpleNamespace(device=None)
        profile = SimpleNamespace(devices={tobii.TOBII_GUID: offline})
        self.enterContext(patch.object(tobii, "EventListener", return_value=listener))
        self.enterContext(patch.object(tobii.shared_state, "current_profile", profile))
        self.enterContext(patch.object(tobii.shared_state, "ui_ready", False))
        publish = self.enterContext(patch.object(tobii.joystick_handling, "set_streamed_joystick_devices"))
        clock = self.enterContext(patch.object(tobii, "monotonic", return_value=10))
        receiver = tobii.TobiiReceiver(0)
        self.addCleanup(receiver.stop)
        receiver.timer.stop()
        destination = receiver.socket.getsockname()
        self.assertEqual(destination[0], "127.0.0.1")
        summary = receiver.summary
        publish.assert_called_once_with(DeviceType.Tobii, [summary], device_guid=tobii.TOBII_GUID)
        self.assertIs(offline.device, summary)
        self.assertFalse(summary.connected)
        self.assertIn("Waiting for Tobii Game Hub", receiver.status)

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(b"invalid", destination)
            receiver.poll()
            self.assertFalse(summary.connected)
            listener.refresh_devices.emit.assert_not_called()
            sender.sendto(tobii.POSE_PACKET.pack(0, 0, 0, 90, -45, 180), destination)
            receiver.poll()

        self.assertTrue(summary.connected)
        self.assertIn("Receiving head tracking", receiver.status)
        listener.refresh_devices.emit.assert_called_once()
        self.assertEqual(summary.getAxisInputIdList(), [1, 2, 3, 4, 5, 6])
        self.assertEqual([summary.getAxisName(i) for i in summary.getAxisInputIdList()], ["X", "Y", "Z", "Yaw", "Pitch", "Roll"])
        self.assertEqual((summary.button_count, summary.hat_count), (0, 0))
        self.assertEqual(summary.get_axis(4), 16384)

        events = [call.args[0] for call in listener.process_joystick_input.call_args_list]
        self.assertEqual([(event.input_type, event.input_index, event.value) for event in events],
                         [(dinput.InputType.Axis, 4, 16384), (dinput.InputType.Axis, 5, -8192), (dinput.InputType.Axis, 6, 32767)])

        clock.return_value = 11
        receiver.poll()
        self.assertEqual(summary.get_axis(4), 0)
        self.assertIn("Waiting for Tobii Game Hub", receiver.status)
        self.assertTrue(listener.process_joystick_input.call_args.kwargs["final"])
        self.assertEqual(listener.process_joystick_input.call_count, 6)
        receiver.poll()
        self.assertEqual(listener.process_joystick_input.call_count, 6)

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(tobii.POSE_PACKET.pack(0, 25, 0, 0, 0, 0), destination)
        receiver.poll()
        self.assertEqual(summary.get_axis(2), 16384)
        publish.assert_called_once()

    def test_waiting_receiver_is_visible_without_a_profile_and_is_removed_on_stop(self):
        registry = tobii.joystick_handling
        self.enterContext(patch.object(registry, "_all_devices_map", {}))
        self.enterContext(patch.object(registry, "_update_joystick_device_maps"))
        self.enterContext(patch.object(tobii.shared_state, "current_profile", None))
        self.enterContext(patch.object(tobii.shared_state, "ui_ready", False))
        self.enterContext(patch.object(tobii, "EventListener", return_value=Mock()))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            port = occupied.getsockname()[1]
            with self.assertLogs("system", level="WARNING"):
                receiver = tobii.TobiiReceiver(port)
            self.addCleanup(receiver.stop)
            self.assertIn("Cannot listen", receiver.status)
            self.assertIn(receiver.summary, registry.display_devices())
            self.assertFalse(receiver.summary.connected)
            receiver.stop()
            self.assertNotIn(receiver.summary, registry.display_devices())

    def test_device_filter_can_hide_waiting_tobii_and_empty_loopback(self):
        from gremlin.ui.dialogs import DeviceDisplayDialog
        from gremlin.ui.loopback import make_summary
        from gremlin.ui.tobii.gaze import GazeReceiver

        if not isinstance(self.app, QtWidgets.QApplication):
            self.skipTest("The current Qt application cannot create widgets.")
        config = tobii.Configuration()
        self.enterContext(patch.object(config, "_set_data"))
        self.enterContext(patch.object(type(config), "startup_loopback_enabled", True))
        self.enterContext(patch.object(tobii, "EventListener", return_value=Mock()))
        self.enterContext(patch.object(tobii.shared_state, "ui_ready", False))
        ui = SimpleNamespace(_create_tabs_ui=Mock())
        self.enterContext(patch.object(tobii.shared_state, "ui", ui))
        loopback = make_summary()
        profile = SimpleNamespace(devices={}, vjoy_devices={}, loopback=SimpleNamespace(device=loopback))
        self.enterContext(patch.object(tobii.shared_state, "current_profile", profile))
        registry = tobii.joystick_handling
        self.enterContext(patch.object(registry, "_all_devices_map", {}))
        self.enterContext(patch.object(registry, "_update_joystick_device_maps"))
        self.enterContext(patch.object(registry, "refresh_device_inventory"))
        head = tobii.TobiiReceiver(0)
        gaze = GazeReceiver()
        self.addCleanup(head.stop)
        self.addCleanup(gaze.stop)
        self.assertFalse(head.summary.connected)
        self.assertFalse(gaze.summary.connected)
        self.assertEqual(loopback.axis_count, 0)

        dialog = DeviceDisplayDialog()
        self.addCleanup(dialog.close)
        device_ids = {device.device_id for device in (head.summary, gaze.summary, loopback)}
        rows = [dialog._list_widget.itemWidget(dialog._list_widget.item(index)) for index in range(dialog._list_widget.count())]
        self.assertEqual({row.data.device_id for row in rows}, device_ids)
        for row in rows:
            self.assertTrue(row.visible_widget.isEnabled())
            row.visible_widget.setChecked(True)
            row.visible_widget.click()
            self.assertFalse(dialog.visible_map[row.data.device_id])
        dialog._update_tabs()
        config._set_data.assert_any_call("device-visibility", dialog.visible_map)
        ui._create_tabs_ui.assert_called_once()


if __name__ == "__main__":
    unittest.main()
