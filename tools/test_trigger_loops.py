"""Startup feedback analysis for built execution graph mappings."""

import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import gremlin
from gremlin.input_types import InputType
from gremlin.types import DeviceType, VjoyAction
from gremlin.trigger_loops import find_trigger_loops


DEVICE = "{39e9447b-52e6-4660-813d-21fe2f047bd3}"
VIRTUAL_DEVICE = "{f563cd70-9328-4348-8df2-08f88de259b6}"
BUTTON = InputType.JoystickButton


def trigger(button, mode="press", *, on_press=True, on_release=False):
    return NS(tag="trigger", enabled=True, device_id=DEVICE, input_type=BUTTON, input_id=button, mode=mode,
              use_actual=False, exec_on_press=on_press, exec_on_release=on_release)


def input_node(number, mode, *actions, state=None, device=DEVICE, name="Stick", input_type=BUTTON):
    control = "Button" if input_type == BUTTON else "Axis"
    item = state or NS(device_guid=device, input_type=input_type, input_id=number, device_name=name,
                       short_display_name=f"{control} {number}", containers=[object()])
    return NS(nodeType=NS(name="InputItem"), input_item=item, mode=mode,
              descendants=[NS(nodeType=NS(name="Action"), action=action) for action in actions])


def analyze(nodes, parents=None, states=None, settings=None):
    parents = parents or {"Default": None}
    profile = NS(state=NS(getStates=lambda: states or {}), get_modes=lambda: parents, get_parent_mode=parents.get,
                 settings=settings)
    return find_trigger_loops(NS(descendants=nodes), profile, "Master")


class TriggerLoopTests(unittest.TestCase):
    def test_reports_self_and_indirect_loops(self):
        self.assertEqual(analyze([input_node(1, "Default", trigger(1))]), [
            (("Default",), ("Stick · Button 1 (press)",)),
        ])
        nodes = [input_node(1, "Default", trigger(2)), input_node(2, "Default", trigger(1))]
        self.assertEqual(analyze(nodes), [(("Default",), ("Stick · Button 1 (press)", "Stick · Button 2 (press)"))])

    def test_distinguishes_release_only_feedback(self):
        first = input_node(1, "Default", trigger(2, "release"))
        self.assertEqual(analyze([first, input_node(2, "Default", trigger(1))]), [])
        second = input_node(2, "Default", trigger(1, on_press=False, on_release=True))
        self.assertEqual(analyze([first, second]), [
            (("Default",), ("Stick · Button 1 (press)", "Stick · Button 2 (release)")),
        ])
        pulsed = input_node(1, "Default", trigger(2, "pulse"))
        self.assertEqual(analyze([pulsed, second]), analyze([first, second]))

    def test_resolves_inheritance_and_child_overrides(self):
        nodes = [input_node(1, "Master", trigger(2)), input_node(2, "Parent", trigger(1)),
                 input_node(2, "Override", NS(tag="noop", enabled=True))]
        self.assertEqual(analyze(nodes, {"Parent": None, "Child": "Parent", "Override": "Parent", "Other": None}), [
            (("Parent", "Child"), ("Stick · Button 1 (press)", "Stick · Button 2 (press)")),
        ])

    def test_follows_state_mappings_and_expression_dependencies(self):
        armed = NS(key="Armed", input_type=InputType.State, containers=[], isExpression=False, getDependencies=list)
        ready = NS(key="Ready", input_type=InputType.State, containers=[object()], isExpression=True,
                   getDependencies=lambda: [armed])
        write_state = NS(tag="map_to_state", enabled=True, mode="press", target_states=lambda: [armed],
                         exec_on_press=True, exec_on_release=False)
        nodes = [input_node(1, "Default", write_state), input_node(None, "", trigger(1), state=ready)]
        self.assertEqual(analyze(nodes, states={"Armed": armed, "Ready": ready}), [
            (("Default",), ("State Armed (on)", "State Ready (on)", "Stick · Button 1 (press)")),
        ])

    def test_legacy_output_uses_resolved_maestro_input_and_requires_input_selection(self):
        device = NS(device_guid=VIRTUAL_DEVICE, device_type=DeviceType.Maestro)
        backend = NS(virtual_input_candidates=lambda: [device], get_output_target=Mock(return_value=NS(device=device)))
        settings = NS(getVirtualAsInput=Mock(return_value=True))
        remap = NS(tag="remap", enabled=True, input_type=BUTTON, vjoy_id=4, vjoy_input_id=2)
        nodes = [input_node(1, "Default", remap), input_node(2, "Default", trigger(1), device=VIRTUAL_DEVICE, name="gex-4")]
        with patch.object(gremlin, "joystick_handling", backend, create=True):
            self.assertEqual(analyze(nodes, settings=settings), [
                (("Default",), ("gex-4 · Button 2 (press)", "Stick · Button 1 (press)")),
            ])
            backend.get_output_target.assert_called_once_with(4)
            settings.getVirtualAsInput.return_value = False
            self.assertEqual(analyze(nodes, settings=settings), [])

    def test_modern_virtual_press_and_release_use_the_correct_phase(self):
        device = NS(device_guid=VIRTUAL_DEVICE, device_type=DeviceType.VJoy, vjoy_id=2)
        action = NS(tag="vjoyremap", enabled=True, virtual_device=device, action_mode=VjoyAction.VJoyButtonRelease,
                    exec_on_press=True, exec_on_release=False, vjoy_button_id=1)
        backend = NS(virtual_input_candidates=lambda: [device], get_output_target=lambda _: NS(device=device))
        settings = NS(getVirtualAsInput=lambda _: True)
        nodes = [input_node(1, "Default", action, device=VIRTUAL_DEVICE, name="vJoy 2")]
        with patch.object(gremlin, "joystick_handling", backend, create=True):
            self.assertEqual(analyze(nodes, settings=settings), [])
            action.action_mode = VjoyAction.VJoyButtonPress
            self.assertEqual(analyze(nodes, settings=settings), [(("Default",), ("vJoy 2 · Button 1 (press)",))])

    def test_split_axis_can_feed_back_through_an_enabled_virtual_axis(self):
        axis = InputType.JoystickAxis
        device = NS(device_guid=VIRTUAL_DEVICE, device_type=DeviceType.VJoy)
        action = NS(tag="split-axis", enabled=True, device_low_vjoy_id=2, device_low_axis=1,
                    device_high_vjoy_id=3, device_high_axis=2)
        backend = NS(virtual_input_candidates=lambda: [device], get_output_target=lambda key: NS(device=device) if key == 2 else None)
        settings = NS(getVirtualAsInput=lambda _: True)
        nodes = [input_node(1, "Default", action, device=VIRTUAL_DEVICE, name="vJoy 2", input_type=axis)]
        with patch.object(gremlin, "joystick_handling", backend, create=True):
            self.assertEqual(analyze(nodes, settings=settings), [(("Default",), ("vJoy 2 · Axis 1",))])

    def test_macro_output_step_can_feed_back(self):
        class VirtualStep(NS):
            pass

        device = NS(device_guid=VIRTUAL_DEVICE, device_type=DeviceType.Maestro)
        backend = NS(virtual_input_candidates=lambda: [device], get_output_target=Mock(return_value=NS(device=device)))
        settings = NS(getVirtualAsInput=lambda _: True)
        step = VirtualStep(device_guid=VIRTUAL_DEVICE, input_type=BUTTON, input_id=1, value="press")
        action = NS(tag="macro", enabled=True, sequence=[object(), step])
        nodes = [input_node(1, "Default", action, device=VIRTUAL_DEVICE, name="gex-4")]
        with patch.object(gremlin, "joystick_handling", backend, create=True), \
             patch.dict(sys.modules, {"gremlin.macro": NS(VJoyMacroAction=VirtualStep)}):
            self.assertEqual(analyze(nodes, settings=settings), [(("Default",), ("gex-4 · Button 1 (press)",))])
        backend.get_output_target.assert_called_once_with(VIRTUAL_DEVICE)


if __name__ == "__main__":
    unittest.main()
