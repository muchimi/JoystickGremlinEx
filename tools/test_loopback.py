"""Hardware-free regression checks for the GEX loopback controller."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gremlin.base_profile  # initialize the profile and action modules in their normal order
import gremlin.config
from gremlin import event_handler, joystick_handling, shared_state, util
from gremlin.actions import JoystickCondition
from gremlin.curve_handler import AxisCurveData, AxisCurveDialog
from gremlin.input_types import InputType
from gremlin.types import DeviceType, VjoyAction
from gremlin.ui import mode_device
from gremlin.ui.joystick_device import BaseJoystickCondition
from gremlin.ui.loopback import AXIS, BUTTON, Loopback, dispatch_context
from gremlin.ui.loopback import profile_xml
from gremlin.ui.loopback.tab import LoopbackTab
from gremlin.ui.loopback.usage import find_usage

from action_plugins.map_to_vjoy import VjoyRemap
from container_plugins.basic import BasicContainer


class LoopbackTests(unittest.TestCase):
    def setUp(self):
        self.loopback = Loopback()
        self.profile = SimpleNamespace(loopback=self.loopback)
        self.config = SimpleNamespace(startup_loopback_enabled=True, verbose_mode_condition=False)
        self.listener = Mock()
        self.enterContext(patch.object(gremlin.config, "Configuration", return_value=self.config))
        self.enterContext(patch.object(shared_state, "current_profile", self.profile))
        self.enterContext(patch.object(event_handler, "EventListener", return_value=self.listener))

    def test_profile_references_follow_guids_and_comments_follow_names(self):
        axis = self.loopback.add(AXIS, "Trim")
        button = self.loopback.add(BUTTON, "Trim--Hold")
        device_guid = str(self.loopback.device.device_guid)
        axis_guid = self.loopback.controls[AXIS][axis].guid
        button_guid = self.loopback.controls[BUTTON][button].guid
        self.assertNotEqual(UUID(axis_guid), UUID(button_guid))
        root = etree.fromstring(f"""
            <profile>
              <devices><device device-guid="{device_guid}"><mode>
                <axis id="{axis}"/>
              </mode></device></devices>
              <vjoyremap device-type="Loopback" mode="VJoyAxisToButton" axis="{button}" button="{button}" input="{button}"/>
              <condition condition-type="joystick" device-guid="{device_guid}" input="axis" id="{axis}"/>
            </profile>
        """)
        self.loopback.rename(AXIS, axis, "Pitch Trim")
        self.loopback.annotate_references(root)
        item = root.find("./devices/device/mode/axis")
        remap = root.find("vjoyremap")
        condition = root.find("condition")
        self.assertEqual(item.get("input-guid"), axis_guid)
        self.assertEqual(remap.get("output-guid"), button_guid)
        self.assertEqual(condition.get("input-guid"), axis_guid)
        self.assertIn("Pitch Trim", item[0].text)
        self.assertIn("Trim", remap[0].text)
        root = etree.fromstring(etree.tostring(root))

        definitions = self.loopback.to_xml()
        definitions.find("axis").set("id", "10")
        definitions.find("button").set("id", "20")
        restored = Loopback()
        restored.from_xml(definitions)
        restored.resolve_references(root)
        self.assertEqual(root.find("./devices/device/mode/axis").get("id"), "10")
        self.assertEqual(root.find("condition").get("id"), "10")
        self.assertEqual([root.find("vjoyremap").get(attr) for attr in ("axis", "button", "input")], ["20"] * 3)
        self.assertFalse(root.xpath("//comment()"))

        restored.remove([(BUTTON, 20)])
        restored.add(BUTTON, "Trim--Hold")
        restored.annotate_references(root)
        self.assertEqual(root.find("vjoyremap").get("output-guid"), button_guid)
        self.assertIn("Missing control", root.find("vjoyremap")[0].text)

        definitions = restored.to_xml()
        definitions.find("button").set("id", "20")
        restored.from_xml(definitions)
        restored.resolve_references(root)
        remap = root.find("vjoyremap")
        missing_slot = int(remap.get("button"))
        self.assertNotIn(missing_slot, restored.controls[BUTTON])
        self.assertEqual(restored.reference_guid(BUTTON, missing_slot), button_guid)

    def test_optional_stepped_device_ids_are_checked_without_uuid_parse_errors(self):
        axis = self.loopback.add(AXIS, "Trim")
        axis_guid = self.loopback.controls[AXIS][axis].guid
        device_guid = UUID(str(self.loopback.device.device_guid))
        root = etree.Element("profile")
        for device_id in (None, "", "invalid", str(UUID(int=1))):
            remap = etree.SubElement(root, "vjoyremap", {
                "stepped-input-type": "axis", "stepped-input-id": "99",
                "stepped-input-guid": axis_guid,
            })
            if device_id is not None:
                remap.set("stepped-device-id", device_id)
        for device_id in (str(device_guid), f"{{{device_guid}}}".upper(), device_guid.hex, device_guid.urn):
            etree.SubElement(root, "vjoyremap", {
                "stepped-device-id": device_id, "stepped-input-type": "axis",
                "stepped-input-id": "99", "stepped-input-guid": axis_guid,
            })

        with patch.object(profile_xml, "UUID", wraps=UUID) as parse_uuid:
            self.loopback.resolve_references(root)

        for call in parse_uuid.call_args_list:
            UUID(*call.args, **call.kwargs)
        self.assertEqual([remap.get("stepped-input-id") for remap in root], ["99"] * 4 + [str(axis)] * 4)

    def test_legacy_loopback_definitions_gain_guids_without_changing_slots(self):
        self.loopback.from_xml(etree.fromstring('<loopback><axis id="9" name="Axis X"/></loopback>'))
        self.assertEqual(self.loopback.device.get_axis_name(9), "Axis Axis X")
        saved = self.loopback.to_xml()
        guid = UUID(saved.find("axis").get("guid"))
        self.loopback.from_xml(saved)
        self.assertEqual(UUID(self.loopback.controls[AXIS][9].guid), guid)

    def test_presets_append_controls_and_use_available_names(self):
        existing = self.loopback.add(AXIS, "axis-2")
        self.loopback.add(BUTTON, "button-1")
        self.loopback.controls[AXIS][existing].start = 0.5
        changed = Mock()
        self.loopback.definitions_changed.connect(changed)

        self.loopback.add_generic_controls(4, 16)
        changed.assert_called_once()
        self.assertEqual(list(self.loopback.device.axis_names.values()), ["axis-2", "axis-1", "axis-3", "axis-4", "axis-5"])
        self.assertEqual(self.loopback.device.get_button_name(17), "button-17")
        self.assertEqual(self.loopback.controls[AXIS][existing].start, 0.5)

        self.loopback.add_generic_controls(8, 32)
        self.assertEqual(self.loopback.device.axis_count, 13)
        self.assertEqual(self.loopback.device.button_count, 49)
        self.assertEqual(changed.call_count, 2)

    def test_profile_data_keeps_case_and_sparse_ids_without_hardware_limits(self):
        self.assertIsNone(self.loopback.to_xml())
        axis = self.loopback.add(AXIS, "Pitch")
        button = self.loopback.add(BUTTON, "pitch")
        with self.assertRaises(ValueError):
            self.loopback.add(BUTTON, "Pitch")
        for _ in range(12):
            self.loopback.add(AXIS, self.loopback.next_name(AXIS))
        for _ in range(245):
            self.loopback.add(BUTTON, self.loopback.next_name(BUTTON))
        last_button = max(self.loopback.controls[BUTTON])
        self.loopback.remove([(BUTTON, button)])
        self.loopback.rename(AXIS, axis, "Pitch Trim")
        self.loopback.controls[AXIS][axis].start = -0.5
        self.loopback.controls[BUTTON][last_button].start = True

        saved = etree.fromstring(etree.tostring(self.loopback.to_xml()))
        restored = Loopback()
        restored.from_xml(saved)
        self.assertEqual(saved.tag, "loopback")
        self.assertEqual(restored.device.axis_count, 13)
        self.assertEqual(restored.device.button_count, 245)
        self.assertNotIn(button, restored.device.get_button_input_ids())
        self.assertEqual(restored.device.get_axis_name(axis), "Axis Pitch Trim")
        self.assertEqual(restored.controls[AXIS][axis].start, -0.5)
        self.assertTrue(restored.controls[BUTTON][last_button].start)
        self.assertGreater(restored.add(BUTTON, "new"), last_button)

    def test_output_backend_and_condition_reads_share_state(self):
        axis = self.loopback.add(AXIS, "Throttle")
        button = self.loopback.add(BUTTON, "Armed")
        guid = self.loopback.device.device_guid
        target = joystick_handling.get_output_target(str(guid))
        self.assertEqual(target.kind, "loopback")
        self.assertIs(joystick_handling.get_output_device(guid), self.loopback)
        self.assertEqual(joystick_handling.virtual_device_map()[DeviceType.Loopback], {0: self.loopback.device})
        joystick_handling.set_axis(guid, axis, 0.75, update_remote=True)
        joystick_handling.set_button(guid, button, True, update_remote=True)
        self.assertEqual(joystick_handling.get_axis(guid, axis), 0.75)
        self.assertTrue(joystick_handling.get_button(guid, button))
        trigger = SimpleNamespace(is_pressed=True)
        condition = JoystickCondition(SimpleNamespace(
            device_guid=guid, input_type=BUTTON, input_id=button,
            comparison="pressed", delay=0, ignore_release=False,
        ))
        self.assertTrue(condition(trigger, None))
        axis_condition = JoystickCondition(SimpleNamespace(
            device_guid=guid, input_type=AXIS, input_id=axis, comparison="inside",
            use_calibrated_data=False, range=[0.5, 1.0], delay=0, ignore_release=False,
        ))
        self.assertTrue(axis_condition(trigger, None))
        events = [call.args[0][0] for call in self.listener.queueJoystickEventList.call_args_list]
        self.assertEqual([event.event_type for event in events], [AXIS, BUTTON])
        self.assertTrue(all(event.source_input_type == InputType.Loopback for event in events))
        self.assertEqual(DeviceType.to_enum("loopback"), DeviceType.Loopback)
        self.assertEqual(InputType.to_enum("loopback"), InputType.Loopback)

        self.loopback.start()
        self.assertEqual(joystick_handling.get_axis(guid, axis), 0.0)
        self.assertFalse(joystick_handling.get_button(guid, button))
        self.config.startup_loopback_enabled = False
        self.assertIsNone(joystick_handling.get_output_target(guid))
        self.assertNotIn(DeviceType.Loopback, joystick_handling.virtual_device_map())

    def test_feedback_cannot_retrigger_the_same_control_in_a_chain(self):
        first = self.loopback.add(BUTTON, "First")
        second = self.loopback.add(BUTTON, "Second")
        self.loopback.button(first).is_pressed = True
        previous = self.listener.queueJoystickEventList.call_args.args[0][0]
        with dispatch_context(previous):
            self.loopback.button(second).is_pressed = True
        subsequent = self.listener.queueJoystickEventList.call_args.args[0][0]
        with dispatch_context(subsequent):
            self.loopback.button(first).is_pressed = False
        self.assertTrue(self.loopback.button(first).is_pressed)
        self.assertEqual(self.listener.queueJoystickEventList.call_count, 2)


class LoopbackDeletionTests(unittest.TestCase):
    def test_curve_and_deadzone_follow_the_active_mode_and_persist(self):
        profile_type = gremlin.base_profile.Profile
        self.enterContext(patch.object(profile_type, "initialize_regular_devices"))
        self.enterContext(patch.object(mode_device, "ensureMasterInputItems"))
        self.enterContext(patch.object(mode_device, "ensureModeInputItems"))
        listener = self.enterContext(patch.object(event_handler, "EventListener")).return_value
        profile = profile_type()
        self.enterContext(patch.object(shared_state, "current_profile", profile))
        self.enterContext(patch.object(shared_state, "is_running", True))
        self.enterContext(patch.object(shared_state, "runtime_mode", "Landing"))
        loopback = profile.loopback
        guid = loopback.device.device_guid
        axis = loopback.add(AXIS, "Trim")
        item = loopback.prepare_mode(profile, "Landing")[0]
        curve = AxisCurveData()
        curve.deadzone = [-1.0, -0.2, 0.2, 1.0]
        curve.control_points = [(-1.0, -1.0), (0.0, 0.0), (0.5, 0.25), (1.0, 1.0)]
        item.curve_data = curve

        loopback.write(AXIS, axis, 0.1)
        deadzone_event = listener.queueJoystickEventList.call_args.args[0][0]
        self.assertEqual(deadzone_event.raw_value, 0.1)
        self.assertAlmostEqual(deadzone_event.curve_value, 0.0)
        loopback.write(AXIS, axis, 0.6)
        event = listener.queueJoystickEventList.call_args.args[0][0]
        self.assertAlmostEqual(event.curve_value, 0.25)
        self.assertEqual(joystick_handling.get_axis(guid, axis), 0.6)
        self.assertAlmostEqual(joystick_handling.get_curved_axis(guid, axis), 0.25)

        with patch.object(shared_state, "runtime_mode", "Cruise"):
            loopback.write(AXIS, axis, 0.1)
            event = listener.queueJoystickEventList.call_args.args[0][0]
            self.assertIsNone(event.curve_value)
            self.assertEqual(joystick_handling.get_curved_axis(guid, axis), 0.1)

        xml = profile.to_xml()
        restored = profile_type()
        with patch.object(shared_state, "current_profile", restored):
            restored.from_xml(xml, fname_is_xml=True)
            restored_curve = restored.getInputItem(guid, "Landing", AXIS, axis).curve_data
            self.assertEqual(restored_curve.deadzone, curve.deadzone)
            self.assertAlmostEqual(restored_curve.curve_value(0.6), 0.25)

    def test_toolbar_delete_removes_the_clicked_input_and_blocks_references(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(["loopback-toolbar-test", "-platform", "offscreen"])
        if not isinstance(app, QApplication):
            self.skipTest("The current Qt application cannot create widgets.")
        self.enterContext(patch.object(gremlin.base_profile.Profile, "initialize_regular_devices"))
        self.enterContext(patch.object(mode_device, "ensureMasterInputItems"))
        self.enterContext(patch.object(mode_device, "ensureModeInputItems"))
        self.enterContext(patch.object(util, "is_ui_thread", return_value=True))
        self.enterContext(patch.object(util, "InvokeUiMethod", side_effect=lambda callback, *args: callback(*args)))
        self.enterContext(patch.object(gremlin.config.Configuration(), "save"))
        profile = gremlin.base_profile.Profile()
        self.enterContext(patch.object(shared_state, "current_profile", profile))
        loopback = profile.loopback
        device = loopback.device
        get_device = joystick_handling.getDevice

        def lookup(guid, *args, **kwargs):
            if util.compare_guid(guid, device.device_guid):
                return device
            return get_device(guid, *args, **kwargs)

        self.enterContext(patch.object(joystick_handling, "getDevice", side_effect=lookup))
        axis = loopback.add(AXIS, "Trim")
        button = loopback.add(BUTTON, "Fire")
        tab = LoopbackTab(device, profile, "Default")
        self.addCleanup(tab.close)
        tab.ensureLoaded()
        tab.show()
        app.processEvents()
        inputs = {(item.input_type, item.input_id): item for item in tab.model.unfilteredItemsList()}
        axis_widget = tab.getInputWidget(inputs[AXIS, axis])
        button_widget = tab.getInputWidget(inputs[BUTTON, button])
        tab.selectInputItem(inputs[AXIS, axis])

        with patch.object(AxisCurveDialog, "exec", return_value=1) as show_curve:
            QTest.mouseClick(axis_widget._curve_button_widget, Qt.MouseButton.LeftButton)
            show_curve.assert_called_once()
        self.assertIsInstance(inputs[AXIS, axis].curve_data, AxisCurveData)
        self.assertIsNone(button_widget._curve_button_widget)
        with patch("gremlin.ui.joystick_device.MessageBoxYesNo", side_effect=lambda **kwargs: kwargs["callback"](True)):
            QTest.mouseClick(axis_widget.clear_curve_widget, Qt.MouseButton.LeftButton)
        self.assertIsNone(inputs[AXIS, axis].curve_data)

        with (
            patch("gremlin.ui.loopback.tab.find_usage", return_value={(BUTTON, button): ["Used by a condition"]}),
            patch("gremlin.ui.loopback.tab.LoopbackUsageDialog") as warning,
            patch("gremlin.ui.ui_common.MessageBoxYesNo") as confirm,
        ):
            button_widget._close_button_widget.click()
            warning.assert_called_once()
            confirm.assert_not_called()
            self.assertIn(button, loopback.controls[BUTTON])
            self.assertEqual(tab.model.rows(), 2)

        with patch("gremlin.ui.ui_common.MessageBoxYesNo") as confirm:
            confirm.side_effect = lambda **kwargs: kwargs["callback"](QMessageBox.StandardButton.No)
            button_widget._close_button_widget.click()
            confirm.assert_called_once()
            self.assertIn("Fire", confirm.call_args.kwargs["prompt"])
        self.assertIn(button, loopback.controls[BUTTON])
        self.assertIs(tab.model.itemAt(1), inputs[BUTTON, button])

        with patch("gremlin.ui.ui_common.MessageBoxYesNo") as confirm:
            confirm.side_effect = lambda **kwargs: kwargs["callback"](QMessageBox.StandardButton.Yes)
            button_widget._close_button_widget.click()
            confirm.assert_called_once()
        app.processEvents()
        self.assertNotIn(button, loopback.controls[BUTTON])
        self.assertIsNone(profile.getModeNode(device.device_guid, "Default").getInputItem(BUTTON, button))
        self.assertIn(axis, loopback.controls[AXIS])
        self.assertEqual(tab.model.rows(), 1)

        with patch("gremlin.ui.ui_common.MessageBoxYesNo") as confirm:
            confirm.side_effect = lambda **kwargs: kwargs["callback"](QMessageBox.StandardButton.Yes)
            axis_widget._close_button_widget.click()
            confirm.assert_called_once()
        app.processEvents()
        self.assertFalse(any(loopback.controls.values()))
        self.assertEqual(tab.model.rows(), 0)

    def test_active_references_block_single_and_bulk_delete(self):
        self.enterContext(patch.object(gremlin.base_profile.Profile, "initialize_regular_devices"))
        self.enterContext(patch.object(mode_device, "ensureMasterInputItems"))
        self.enterContext(patch.object(mode_device, "ensureModeInputItems"))
        self.enterContext(patch.object(event_handler, "EventListener", return_value=Mock()))
        profile = gremlin.base_profile.Profile()
        self.enterContext(patch.object(shared_state, "current_profile", profile))
        loopback = profile.loopback
        guid = loopback.device.device_guid
        axis = loopback.add(AXIS, "Trim")
        button = loopback.add(BUTTON, "Hold")
        unused = loopback.add(BUTTON, "Unused")

        item = loopback.prepare_mode(profile, "Landing")[0]
        container = BasicContainer(item)
        item.containers.addContainer(container)
        action = VjoyRemap(container)
        action.virtual_device = loopback.device
        action.action_mode = VjoyAction.VJoyAxisToButton
        action.vjoy_input_id = button
        container.add_action(action)
        condition = BaseJoystickCondition(target=container)
        condition.device_guid = guid
        condition.input_type = BUTTON
        condition.input_id = button
        container.activation_condition.conditions.add(condition)

        keys = [(AXIS, axis), (BUTTON, button), (BUTTON, unused)]
        usage = find_usage(profile, keys)
        self.assertEqual(set(usage), set(keys[:2]))
        self.assertTrue(any("Landing" in row and "Input mapping" in row for row in usage[AXIS, axis]))
        self.assertTrue(any("Landing" in row and "Virtual Remap" in row for row in usage[BUTTON, button]))
        self.assertTrue(any("Landing" in row and "Joystick condition" in row for row in usage[BUTTON, button]))

        tab = Mock(profile=profile, loopback=loopback, device_guid=guid)
        tab._can_delete.side_effect = lambda keys: LoopbackTab._can_delete(tab, keys)
        warning = self.enterContext(patch("gremlin.ui.loopback.tab.LoopbackUsageDialog"))
        confirm = self.enterContext(patch("gremlin.ui.loopback.tab.ConfirmBox", return_value=True))
        self.assertFalse(LoopbackTab._delete(tab, [keys[1]]))
        self.assertFalse(LoopbackTab._delete(tab, keys, confirm_all=True))
        self.assertEqual(set(loopback.controls[BUTTON]), {button, unused})
        self.assertEqual(set(warning.call_args.args[0]), {"Trim", "Hold"})
        confirm.assert_not_called()

        item.containers.removeContainer(container)
        self.assertTrue(LoopbackTab._delete(tab, keys, confirm_all=True))
        self.assertFalse(any(loopback.controls.values()))


if __name__ == "__main__":
    unittest.main()
