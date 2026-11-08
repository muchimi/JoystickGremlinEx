"""Hardware-free Qt output selector checks: python tools/test_vjoy_remap_selector.py."""

import ast
import logging
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from PySide6 import QtCore, QtWidgets
from shiboken6 import Shiboken

from test_qt_marshalling import definitions, flush_deletes


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.input_types import InputType  # noqa: E402
from gremlin.types import VjoyAction  # noqa: E402


SERVICES = NS()
source = definitions("action_plugins/map_to_vjoy/__init__.py", {"VJoyRemapWidget"})[0]
source.bases = [ast.Attribute(value=ast.Name(id="QtWidgets", ctx=ast.Load()), attr="QWidget", ctx=ast.Load())]
source.body = [node for node in source.body if getattr(node, "name", None) in {
    "_update_device_selector", "_handle_virtual_device_input_changed", "_update_device_input_list",
    "_handle_virtual_button_usage_changed", "_populate_grid_ui",
}]
namespace = dict(QtCore=QtCore, QtWidgets=QtWidgets, Shiboken=Shiboken, gremlin=SERVICES,
                 InputType=InputType, VjoyAction=VjoyAction, syslog=logging.getLogger("selector-checks"))
exec(compile(ast.fix_missing_locations(ast.Module(body=[*ast.parse("from __future__ import annotations").body,
    source], type_ignores=[])), "action_plugins/map_to_vjoy/__init__.py", "exec"), namespace)
Selector = namespace["VJoyRemapWidget"]


def device(guid="output-1", connected=True):
    return NS(device_guid=guid, name=guid, connected=connected, virtual_id=1,
              axis_count=3, get_axis_name=lambda axis: f"Axis {axis}")


class OutputSelectorTests(unittest.TestCase):
    def setUp(self):
        self.devices = []
        self.config = NS(vjoy_show_disconnected=False)
        self.query = Mock(side_effect=lambda connected_only: [
            dev for dev in self.devices if not connected_only or dev.connected
        ])
        SERVICES.config = NS(Configuration=lambda: self.config)
        SERVICES.joystick_handling = NS(virtual_devices=self.query)
        self.ui = Selector()
        self.ui.action_data = NS(virtual_device=None, action_mode=VjoyAction.VJoyAxis,
                                 vjoy_input_id=2, virtual_id=-1, grid_visible=True,
                                 refresh_virtual_inputs=Mock())
        self.ui.virtual_device_selector_widget = QtWidgets.QComboBox(self.ui)
        self.ui.virtual_output_selector_widget = QtWidgets.QComboBox(self.ui)
        self.ui.virtual_device_selector_widget.currentIndexChanged.connect(self.ui._handle_virtual_device_input_changed)
        self.ui._get_selector_input_type = lambda: InputType.JoystickAxis
        self.ui._update_hat_mapping = Mock()
        self.ui.notify_device_changed = Mock()
        self.ui.setWarning = Mock()
        self.ui._grid_widgets = {}

    def tearDown(self):
        self.ui.deleteLater()
        flush_deletes()

    def assert_empty_outputs(self):
        self.assertEqual(self.ui.virtual_device_selector_widget.count(), 0)
        self.assertEqual(self.ui.virtual_output_selector_widget.count(), 0)
        self.assertIn("No virtual output devices", self.ui.setWarning.call_args.args[0])

    def test_no_devices_warns_without_changing_the_action(self):
        self.ui._update_device_selector()
        self.assert_empty_outputs()
        self.assertIsNone(self.ui.action_data.virtual_device)
        self.ui.notify_device_changed.assert_not_called()
        self.ui.action_data.refresh_virtual_inputs.assert_not_called()

    def test_empty_list_preserves_saved_disconnected_target(self):
        saved = self.ui.action_data.virtual_device = device(connected=False)
        self.ui.virtual_output_selector_widget.addItem("Old output", 1)
        self.ui._update_device_selector()
        self.assert_empty_outputs()
        self.assertIs(self.ui.action_data.virtual_device, saved)
        # Later UI population must not restore outputs hidden by the filter.
        self.ui._update_device_input_list()
        self.assert_empty_outputs()

    def test_device_removal_clears_stale_outputs(self):
        self.devices = [device()]
        self.ui._update_device_selector()
        saved = self.ui.action_data.virtual_device
        self.assertEqual(self.ui.virtual_output_selector_widget.count(), 3)
        self.devices.clear()
        self.ui._update_device_selector()
        self.assert_empty_outputs()
        self.assertIs(self.ui.action_data.virtual_device, saved)

    def test_device_reappearing_restores_selection_and_clears_warning(self):
        self.ui.action_data.virtual_device = device()
        self.ui._update_device_selector()
        current = device()
        self.devices = [current]
        self.ui._update_device_selector()
        self.assertIs(self.ui.action_data.virtual_device, current)
        self.assertEqual(self.ui.virtual_output_selector_widget.currentData(), 2)
        self.ui.setWarning.assert_called_with(None)

    def test_missing_target_falls_back_to_first_available_output(self):
        self.ui.action_data.virtual_device = device("missing")
        self.devices = [device("maestro-1"), device("vjoy-1")]
        self.ui._update_device_selector()
        self.assertIs(self.ui.action_data.virtual_device, self.devices[0])
        self.ui.notify_device_changed.assert_called_once()

    def test_matching_guid_rebinds_to_the_current_device_instance(self):
        self.ui.action_data.virtual_device = device("maestro-1")
        self.devices = [device("vjoy-1"), device("maestro-1")]
        self.ui._update_device_selector()
        self.assertEqual(self.ui.virtual_device_selector_widget.currentIndex(), 1)
        self.assertIs(self.ui.action_data.virtual_device, self.devices[1])
        self.ui.notify_device_changed.assert_called_once()

    def test_show_disconnected_repopulates_an_empty_selector(self):
        self.devices = [device(connected=False)]
        self.ui._update_device_selector()
        self.assert_empty_outputs()
        self.config.vjoy_show_disconnected = True
        self.ui._update_device_selector()
        self.assertIs(self.ui.action_data.virtual_device, self.devices[0])
        self.assertEqual(self.ui.virtual_output_selector_widget.count(), 3)
        self.assertEqual([call.args for call in self.query.call_args_list], [(True,), (False,)])

    def test_grid_refresh_without_a_target_is_harmless(self):
        self.ui._populate_grid_ui()

    def test_button_usage_notification_without_a_target_is_harmless(self):
        self.ui._handle_virtual_button_usage_changed("vjoy", 1)


if __name__ == "__main__":
    unittest.main()
