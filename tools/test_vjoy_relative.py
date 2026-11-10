"""Hardware-free relative axis UI/output checks: python tools/test_vjoy_relative.py."""

import ast
import logging
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken
from test_qt_marshalling import APP, flush_deletes


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.input_types import InputType  # noqa: E402
from gremlin.types import SyncMode, VjoyAction  # noqa: E402


def load(path, names, namespace, methods=None, base=None):
    nodes = [node for node in ast.parse((ROOT / path).read_bytes()).body if getattr(node, "name", None) in names]
    if methods is not None:
        for node in nodes:
            node.body = [method for method in node.body if getattr(method, "name", None) in methods]
            node.bases = [ast.parse(base).body[0].value]
    future = ast.parse("from __future__ import annotations").body
    exec(compile(ast.fix_missing_locations(ast.Module(body=[*future, *nodes], type_ignores=[])), path, "exec"), namespace)


SERVICES = NS(
    types=NS(SyncMode=SyncMode),
    config=NS(Configuration=lambda: NS(dropdown_use_mouse_wheel=False)),
    util=NS(InvokeUiMethod=lambda callback, *args: callback(*args), assert_ui_thread=lambda: None,
            clamp=lambda value: max(-1.0, min(1.0, value))),
)
UI = dict(QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets, QWidget=QtWidgets.QWidget, Qt=QtCore.Qt,
          Shiboken=Shiboken, gremlin=SERVICES, InputType=InputType, SyncMode=SyncMode,
          Buttons=NS(_default_parent=None),
          get_text_width=lambda text: QtGui.QFontMetrics(APP.font()).horizontalAdvance(text))
load("gremlin/ui/ui_common.py", {
    "QLineEdit", "QFloatLineEdit", "QComboBox", "QDataComboBox", "QSyncModeWidget", "getHContainer",
}, UI)
UI["QDelayWidget"] = QtWidgets.QSpinBox
load("action_plugins/map_to_vjoy/__init__.py", {"VJoyRemapWidget"}, UI, {
    "_create_input_axis", "_create_sync_widget", "_default_value_changed", "_axis_reverse_changed",
    "_axis_mode_changed", "_axis_scaling_changed", "_relative_value_changed", "_use_relative_value_changed",
    "_relative_pulse_value_changed", "_sync_on_start_changed", "_b_min_start_value_clicked",
    "_b_center_start_value_clicked", "_b_max_start_value_clicked",
}, "QtWidgets.QWidget")


class RelativeAxisWidgetChecks(unittest.TestCase):
    def setUp(self):
        self.widget = UI["VJoyRemapWidget"]()
        self.widget.action_data = NS(
            axis_mode="relative", reverse=False, relative_value=0.2, relative_pulse_delay=100,
            use_relative_value=True, axis_start_value=0.25, button_start_value=False,
            sync_mode=SyncMode.Default, get_input_type=lambda: InputType.JoystickAxis,
        )
        self.widget.main_layout = QtWidgets.QVBoxLayout(self.widget)
        self.widget.container_height = 42
        self.widget.set_width = lambda button, width: button.setFixedWidth(width)
        self.widget._enable_axis_tracking = self.widget._update_ui = Mock()
        self.widget._create_input_axis()
        self.widget._create_sync_widget()

    def tearDown(self):
        self.widget.deleteLater()
        flush_deletes()

    def test_all_preset_buttons_update_display_and_saved_start_value(self):
        errors, changes = [], []
        self.widget._sync_widget.valueChanged.connect(changes.append)
        with patch.object(sys, "excepthook", side_effect=lambda kind, error, tb: errors.append(error)):
            for button, expected in ((self.widget.b_min_value, -1.0), (self.widget.b_center_value, 0.0),
                                     (self.widget.b_max_value, 1.0), (self.widget.b_min_value, -1.0)):
                with self.subTest(expected=expected):
                    button.click()
                    self.assertEqual(errors, [])
                    self.assertEqual(self.widget.action_data.axis_start_value, expected)
                    self.assertEqual(self.widget._sync_widget.value, expected)
                    self.assertEqual(self.widget._sync_widget._default_widget.value(), expected)
        self.assertEqual(changes, [-1.0, 0.0, 1.0, -1.0])

    def test_presets_keep_input_sync_mode_selected(self):
        sync = self.widget._sync_widget
        sync._selector_widget.setCurrentIndex(sync._selector_widget.findData(SyncMode.Input))
        self.widget._b_max_start_value_clicked()
        self.assertEqual(self.widget.action_data.axis_start_value, 1.0)
        self.assertEqual(self.widget.action_data.sync_mode, SyncMode.Input)
        self.assertEqual(sync.mode, SyncMode.Input)
        self.assertTrue(sync._default_container_widget.isHidden())

    def test_manual_edit_still_updates_profile_after_presets(self):
        self.widget._b_min_start_value_clicked()
        self.widget._sync_widget._default_widget.setValue(0.375)
        self.assertEqual(self.widget.action_data.axis_start_value, 0.375)
        self.assertEqual(self.widget._sync_widget.value, 0.375)

    def test_sync_value_setter_preserves_button_states(self):
        sync = UI["QSyncModeWidget"](input_type=InputType.JoystickButton, default_value=False, parent=self.widget)
        changes = []
        sync.valueChanged.connect(changes.append)
        for value, radio in ((True, sync.rb_start_pressed), (False, sync.rb_start_released),
                             (None, sync.rb_start_ignored)):
            sync.setValue(value)
            self.assertIs(sync.value, value)
            self.assertTrue(radio.isChecked())
        self.assertEqual(changes, [True, False, None])


class Pulse:
    def __init__(self, duration, interval, on_callback, data):
        self.interval, self.on_callback, self.data = interval, on_callback, data
        self.is_running = False

    def start(self):
        self.is_running = True

    def stop(self):
        self.is_running = False

    def tick(self):
        if self.is_running:
            self.on_callback(self.data)


RUNTIME = dict(gremlin=SERVICES, VjoyAction=VjoyAction, InputType=InputType, PulseWorker=Pulse,
               syslog=logging.getLogger("relative-axis-checks"))
load("action_plugins/map_to_vjoy/__init__.py", {"VJoyRemapFunctor"}, RUNTIME, {
    "_process_event", "_relative_pulse_on", "_get_axis", "_set_axis",
}, "object")


class RelativeAxisOutputChecks(unittest.TestCase):
    def setUp(self):
        self.axis = NS(value=0.4)
        self.remote_value = 0.4
        self.functor = RUNTIME["VJoyRemapFunctor"]()
        f = self.functor
        f.vjoy_id, f.vjoy_input_id = 1, 6
        f.action_mode = VjoyAction.VJoyAxis
        f.action_data = NS(axis_mode="relative", relative_value=0.2, relative_pulse_delay=100,
                           use_relative_value=True, reverse=False, axis_last_value=0.4)
        f.verbose = f.verbose_extra = False
        f.lock = threading.Lock()
        f._relative_pulse_worker = None
        f._send_flags = lambda: (True, True)
        f._is_maestro_target = lambda: False
        f._output_key = lambda device_id: device_id
        f._is_output_connected = Mock(return_value=True)
        f._output_device = lambda device_id: NS(axis=lambda axis_id: self.axis)
        f.usage_data = NS(is_inverted=Mock(return_value=False))
        f.client_list = [0]
        f.remote_client = NS(send_relative_axis=Mock(side_effect=self.receive_relative))

    def receive_relative(self, device_id, axis_id, offset, **kwargs):
        self.remote_value = max(-1.0, min(1.0, self.remote_value + offset))

    def move(self, value, force_remote=False):
        event = NS(is_axis=True, value=value, curve_value=None, force_remote=force_remote,
                   getInputType=lambda: InputType.JoystickAxis)
        self.assertTrue(self.functor._process_event(event, NS(current=value, raw=value), None))
        return self.functor._relative_pulse_worker

    def test_repeated_pulses_apply_same_increment_locally_and_remotely(self):
        worker = self.move(0.5)
        self.assertEqual(worker.interval, 0.1)
        for expected in (0.5, 0.6, 0.7):
            worker.tick()
            self.assertAlmostEqual(self.axis.value, expected)
            self.assertAlmostEqual(self.remote_value, expected)
            self.assertAlmostEqual(self.functor.action_data.axis_last_value, expected)

    def test_remote_increment_uses_receivers_current_position(self):
        self.remote_value = -0.4
        self.move(0.5).tick()
        self.assertAlmostEqual(self.axis.value, 0.5)
        self.assertAlmostEqual(self.remote_value, -0.3)

    def test_negative_and_reversed_inputs(self):
        for reverse, expected in ((False, 0.3), (True, 0.5)):
            with self.subTest(reverse=reverse):
                self.axis.value = self.remote_value = 0.4
                self.functor.action_data.reverse = reverse
                self.move(-0.5).tick()
                self.assertAlmostEqual(self.axis.value, expected)
                self.assertAlmostEqual(self.remote_value, expected)

    def test_center_stops_and_next_deflection_reuses_worker(self):
        worker = self.move(0.5)
        worker.tick()
        self.move(0.01)
        self.assertFalse(worker.is_running)
        worker.tick()
        self.assertAlmostEqual(self.axis.value, 0.5)
        self.assertIs(self.move(-0.5), worker)
        worker.tick()
        self.assertAlmostEqual(self.axis.value, 0.4)
        self.assertAlmostEqual(self.remote_value, 0.4)

    def test_constant_increment_mode_ignores_deflection_magnitude(self):
        self.functor.action_data.use_relative_value = False
        self.move(0.5).tick()
        self.assertAlmostEqual(self.axis.value, 0.6)
        self.assertAlmostEqual(self.remote_value, 0.6)

    def test_output_inversion_reverses_both_routes(self):
        self.functor.usage_data.is_inverted.return_value = True
        self.move(0.5).tick()
        self.assertAlmostEqual(self.axis.value, 0.3)
        self.assertAlmostEqual(self.remote_value, 0.3)

    def test_local_and_remote_outputs_clamp_at_both_limits(self):
        for value, expected in ((0.95, 1.0), (-0.95, -1.0)):
            with self.subTest(expected=expected):
                self.axis.value = self.remote_value = value
                self.move(1.0 if value > 0 else -1.0).tick()
                self.assertEqual(self.axis.value, expected)
                self.assertEqual(self.remote_value, expected)

    def test_force_remote_is_carried_by_each_pulse(self):
        self.move(0.5, force_remote=True).tick()
        self.assertEqual(self.axis.value, 0.4)
        self.assertAlmostEqual(self.remote_value, 0.5)
        self.functor.remote_client.send_relative_axis.assert_called_once_with(
            1, 6, 0.1, client_list=[0], force_remote=True,
        )

    def test_reused_worker_updates_routing(self):
        worker = self.move(0.5)
        worker.tick()
        self.assertIs(self.move(-0.5, force_remote=True), worker)
        worker.tick()
        self.assertAlmostEqual(self.axis.value, 0.5)
        self.assertAlmostEqual(self.remote_value, 0.4)
        self.functor.remote_client.send_relative_axis.assert_called_with(
            1, 6, -0.1, client_list=[0], force_remote=True,
        )

    def test_maestro_output_remains_local_for_force_remote_events(self):
        self.functor._is_maestro_target = lambda: True
        self.functor._send_flags = lambda: (True, False)
        self.move(0.5, force_remote=True).tick()
        self.assertAlmostEqual(self.axis.value, 0.5)
        self.functor.remote_client.send_relative_axis.assert_not_called()

    def test_pulses_round_trip_through_real_remote_protocol(self):
        from test_remote import RemoteChecks

        remote = RemoteChecks()
        remote.setUpClass()
        remote.setUp()
        # Supply the output resolver added since this older fixture was written.
        remote.services.joystick_handling.get_output_target = lambda device_id: None
        remote.axes[6].value = -0.4
        self.functor.remote_client = remote.sender
        worker = self.move(0.5)
        for expected in (-0.3, -0.2, -0.1):
            worker.tick()
            remote.transfer()
            self.assertAlmostEqual(remote.axes[6].value, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
