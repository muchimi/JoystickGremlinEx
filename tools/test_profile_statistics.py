"""Profile statistics checks without connected hardware or an application window."""

import ast
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.input_types import InputType
from gremlin.types import ActivationRule, ButtonOutputMode, DeviceType, GamePadOutput, HatDirection, VjoyAction


class StateCondition(SimpleNamespace):
    pass


class VirtualCondition(SimpleNamespace):
    pass


class KeyboardCondition(SimpleNamespace):
    pass


class ContainerAction(SimpleNamespace):
    pass


class StateStep(SimpleNamespace):
    pass


def action(name, tag="noop", **fields):
    return SimpleNamespace(name=name, tag=tag, conditions=[], **fields)


def container(tag, *sets, conditions=()):
    return SimpleNamespace(name=tag.capitalize(), tag=tag, conditions=conditions, get_action_sets=lambda: sets)


def input_item(input_type, input_id, *containers, **fields):
    return SimpleNamespace(input_type=input_type, input_id=input_id, containers=containers, **fields)


def device(name, kind, *, axes=0, gamepad=False, virtual=False):
    return SimpleNamespace(name=name, device_guid=name, device_type=kind, axis_count=axes, usage=0,
                           is_gamepad=gamepad, is_virtual=virtual)


def profile_device(summary, **modes):
    return SimpleNamespace(
        device=summary, device_guid=summary.device_guid, device_type=summary.device_type, name=summary.name,
        modes={mode: SimpleNamespace(config={0: dict(enumerate(items))}) for mode, items in modes.items()},
    )


def mode_tree(**parents):
    return SimpleNamespace(descendants=[
        SimpleNamespace(name=name, parent=SimpleNamespace(name=parent)) for name, parent in parents.items()
    ])


class ProfileStatisticsTests(unittest.TestCase):
    def test_counts_unique_controls_devices_and_nested_definitions(self):
        stick = device("Flight stick", DeviceType.Joystick, axes=3)
        pad = device("Gamepad", DeviceType.Joystick, gamepad=True)
        keypad = device("Azeron Keypad", DeviceType.Joystick, axes=2, gamepad=True)
        bridge = device("gex-1", DeviceType.Maestro, virtual=True)
        midi = device("MIDI", DeviceType.Midi)
        osc = device("OSC", DeviceType.Osc)
        keyboard = device("Keyboard", DeviceType.Keyboard)

        ready = input_item(InputType.State, "ready", key="ready", isExpression=False)
        expr = input_item(InputType.State, "armed", key="armed", isExpression=True, expression="not (ready)")
        unused = input_item(InputType.State, "unused", key="unused", isExpression=False)
        macro = action("Macro", "macro", sequence=[object(), StateStep(key="ready"), object()])
        target = action("Virtual Remap", "vjoyremap", action_mode=VjoyAction.VJoyAxis, virtual_device=bridge, vjoy_axis_id=1, merge_data=[])
        target.conditions = [StateCondition(key="ready", comparison="on"), StateCondition(key="armed", comparison="off")]
        target.activation_condition = SimpleNamespace(rule=ActivationRule.Any)
        osc_send = lambda: action("Map to OSC", "map-to-osc", command="/test", server_ip="127.0.0.1", server_port=8000)

        child = input_item(InputType.JoystickAxis, 1, container("chain", [osc_send()], [action("Pause")]))
        nested = ContainerAction(name="Nested", tag="test-container", conditions=[], _item_data_map={0: child})
        key_condition = KeyboardCondition(key=SimpleNamespace(name="Left Shift"), comparison="pressed", scan_code=42, is_extended=False)
        devices = [
            profile_device(stick,
                           Default=[input_item(InputType.JoystickAxis, 1, container("sequence", [target, nested], [macro], conditions=[StateCondition(key="armed", comparison="on")]))],
                           Flight=[input_item(InputType.JoystickAxis, 1, container("basic", [action("Pause")]))]),
            profile_device(pad, Default=[input_item(InputType.JoystickButton, 1, container("basic", [action("Pause")]))]),
            profile_device(keypad, Default=[input_item(InputType.JoystickButton, 1, container(
                "basic", [action("Pause")], conditions=[VirtualCondition(vjoy_id="gex-1"), key_condition],
            ), short_display_name="Button 1")]),
            profile_device(midi, Default=[input_item(InputType.Midi, "cc:1", container("basic", [action("Pause")]), port_name="MIDI port")]),
            profile_device(osc, Default=[input_item(InputType.OpenSoundControl, "/in", container("basic", [osc_send()]))]),
            profile_device(keyboard, Default=[input_item(InputType.KeyboardLatched, "Ctrl+A", container("basic", [action("Pause")]))]),
        ]
        profile = SimpleNamespace(
            name="Flight | Test", get_modes=lambda: ["Default", "Flight", "Empty"],
            modeTree=lambda: mode_tree(Default=None, Flight="Default", Empty="Flight"),
            devices={node.device_guid: node for node in devices},
            state=SimpleNamespace(getStates=lambda: {state.key: state for state in (ready, expr, unused)}),
            voice=SimpleNamespace(getVoices=list), merge_axes=[], _start_state={},
            settings=SimpleNamespace(getVirtualAsInputList=lambda kind: [0] if kind == DeviceType.Maestro else []),
        )
        stats = self._collector(bridge)(profile, "Master")
        summary = dict(stats.sections()[0][2])
        expected = {
            "Mapped axes": 1, "Keyboard inputs mapped": 1, "OSC input commands mapped": 1,
            "OSC output commands mapped": 1, "MIDI input commands mapped": 1, "Virtual devices used as input": 1,
            "Virtual devices enabled as input": 1, "Input devices in use": 7, "Joysticks in use": 1,
            "Gamepads in use": 1, "Other input devices in use": 4, "States defined": 3,
            "States used": 2, "Expression states used": 1, "Conditions": 5, "Longest macro (steps)": 3,
            "Longest sequence (steps)": 2, "Longest chain (steps)": 2, "Actions defined": 11,
            "Output devices and destinations in use": 2,
        }
        for label, count in expected.items():
            self.assertEqual(summary[label], count, label)
        self.assertEqual(stats.actions["Map to OSC"], 2)
        self.assertEqual(stats.modes["Default"]["Axes"], 1)
        self.assertEqual(stats.modes["Flight"]["Axes"], 1)
        self.assertIn("Empty", stats.modes)
        report = stats.to_markdown()
        self.assertIn(r"Flight \| Test", report)
        self.assertIn("| Map to OSC | 2 |", report)
        self.assertIn("| Empty | 0 | 0 | 0 | 0 | 0 | 0 | 0 |", report)
        headers, rows = next((headers, rows) for title, headers, rows in stats.sections() if title == "Mode Parenting")
        self.assertEqual(headers, ("Mode", "Parent mode"))
        self.assertEqual(rows, [("Default", "No parent"), ("Flight", "Default"), ("Empty", "Flight")])
        self.assertIn("## Mode Parenting\n\n| Mode | Parent mode |", report)
        self.assertIn("| Empty | Flight |", report)
        self.assertNotIn("## Input Keybinds", report)
        self.assertNotIn("## Bindings by Device", report)

        keybinds = stats.to_markdown(statistics=False, keybinds=True)
        self.assertIn("| Default | Ctrl+A | Basic → Pause |", keybinds)
        self.assertIn("| Left Shift | pressed | Default | Azeron Keypad | Button 1 |", keybinds)
        self.assertNotIn("## Overview", keybinds)
        self.assertNotIn("## Bindings by Device", keybinds)

        bindings = stats.to_markdown(statistics=False, bindings=True)
        self.assertIn("### Flight stick", bindings)
        self.assertIn("Sequence (step 1) \\[if State armed on\\] → gex-1 Axis 1 (Axis) \\[if State ready on OR State armed off\\]", bindings)
        self.assertIn("| Flight | 1 | Basic → Pause |", bindings)
        self.assertIn("### MIDI port", bindings)
        self.assertNotIn("## Input Keybinds", bindings)
        self.assertNotIn("## Mapping Usage", bindings)
        self.assertIn("| Container | Chain | 1 | 1 | 14.29% |", report)
        self.assertIn("## Output Bindings", report)
        self.assertIn("| gex-1 Axis 1 | Flight stick | 1 | Default |", report)
        self.assertEqual(stats.output_bindings, [
            ("gex-1 Axis 1", "Flight stick", "1", "Default",
             "Sequence (step 1) [if State armed on] → gex-1 Axis 1 (Axis) [if State ready on OR State armed off]"),
            ("OSC 127.0.0.1:8000 /test", "Flight stick", "1", "Default",
             "Sequence (step 1) [if State armed on] → Nested → Chain (step 1) → OSC 127.0.0.1:8000 /test"),
            ("OSC 127.0.0.1:8000 /test", "OSC", "/in", "Default", "Basic → OSC 127.0.0.1:8000 /test"),
            ("State ready", "Flight stick", "1", "Default", "Sequence (step 2) [if State armed on] → Macro (3 steps)"),
        ])

    def test_usage_counts_definitions_and_mapping_coverage_separately(self):
        stick = device("Flight stick", DeviceType.Joystick, axes=3)
        node = profile_device(
            stick,
            Default=[input_item(
                InputType.JoystickAxis, 1,
                container("basic", [action("Pause"), action("Pause")]),
                container("basic", [action("Pause")]),
            )],
            Flight=[
                input_item(InputType.JoystickAxis, 1, container("basic", [action("Pause")])),
                input_item(InputType.JoystickAxis, 2, container("chain", [action("Switch Mode")])),
            ],
        )
        profile = SimpleNamespace(
            name="Usage Test", devices={node.device_guid: node}, get_modes=lambda: ["Default", "Flight"],
            modeTree=lambda: mode_tree(Default=None, Flight="Master", Master=None),
            state=SimpleNamespace(getStates=dict), voice=SimpleNamespace(getVoices=list),
            settings=SimpleNamespace(getVirtualAsInputList=lambda kind: []), merge_axes=[], _start_state={},
        )
        collect = self._collector(stick)
        stats = collect(profile, "Master")
        self.assertEqual(dict(stats.sections()[0][2])["Mapping assignments"], 3)
        report = stats.to_markdown()
        self.assertIn("| Container | Basic | 3 | 2 | 66.67% |", report)
        self.assertIn("| Action | Pause | 4 | 2 | 66.67% |", report)
        self.assertIn("| Container | Chain | 1 | 1 | 33.33% |", report)
        self.assertLess(report.index("| Action | Pause |"), report.index("| Container | Chain |"))

        profile.devices.clear()
        sections = {title: rows for title, _, rows in collect(profile, "Master").sections()}
        self.assertEqual(sections["Mapping Usage"], [])
        self.assertEqual(sections["Mode Parenting"], [("Default", "No parent"), ("Flight", "Profile-wide")])

    def test_hat_outputs_have_their_own_directions_and_skip_noop(self):
        stick = device("Flight stick", DeviceType.Joystick)
        bridge = device("gex-1", DeviceType.Maestro, virtual=True)
        hat = action("Hat mapping", "vjoyremap", action_mode=VjoyAction.VJoyHatToButton,
                     virtual_device=bridge, merge_data=[], hat_map={(0, 0): 1, (0, 1): 2, (1, 0): 3},
                     hat_mode_map={(0, 0): ButtonOutputMode.NoOp})
        node = profile_device(stick, Default=[input_item(InputType.JoystickHat, 1, container("basic", [hat]),
                                                        short_display_name="Hat 1")])
        profile = SimpleNamespace(
            name="Hat Test", devices={node.device_guid: node}, get_modes=lambda: ["Default"],
            modeTree=lambda: mode_tree(Default=None),
            state=SimpleNamespace(getStates=dict), voice=SimpleNamespace(getVoices=list),
            settings=SimpleNamespace(getVirtualAsInputList=lambda kind: []), merge_axes=[], _start_state={},
        )
        rows = self._collector(bridge)(profile, "Master").output_bindings
        self.assertEqual([row[:4] for row in rows], [
            ("gex-1 Button 2", "Flight stick", "Hat 1", "Default"),
            ("gex-1 Button 3", "Flight stick", "Hat 1", "Default"),
        ])
        for row, direction in zip(rows, (HatDirection.North, HatDirection.East)):
            self.assertTrue(row[-1].endswith(f"[if Hat direction {HatDirection.to_display_name(direction)}]"))

    def _collector(self, bridge):
        path = ROOT / "gremlin" / "profile_statistics.py"
        tree = ast.parse(path.read_bytes())
        tree.body = [node for node in tree.body if not isinstance(node, ast.ImportFrom) or not node.module.startswith("gremlin")]
        module = ModuleType("profile_statistics_checks")
        module.__dict__.update(
            InputType=InputType, DeviceType=DeviceType, GamePadOutput=GamePadOutput, VjoyAction=VjoyAction,
            ButtonOutputMode=ButtonOutputMode, HatDirection=HatDirection,
            AbstractContainerAction=ContainerAction, BaseStateCondition=StateCondition, BaseVJoyCondition=VirtualCondition,
            BaseKeyboardCondition=KeyboardCondition, BaseJoystickCondition=type("JoystickCondition", (), {}),
            BaseModeCondition=type("ModeCondition", (), {}), BaseInputActionCondition=type("InputCondition", (), {}),
            getInputIdKey=lambda input_id: input_id,
            joystick_handling=SimpleNamespace(all_joystick_devices=lambda: [bridge], virtual_device_map=dict),
            macro=SimpleNamespace(StateAction=StateStep, **{
                name: type(name, (), {}) for name in (
                    "VJoyMacroAction", "JoystickAction", "KeyAction", "MouseButtonAction", "MouseMotionAction", "StreamDeckAction",
                )
            }),
        )
        exec(compile(tree, str(path), "exec"), vars(module))
        return module.collect_profile_statistics


if __name__ == "__main__":
    unittest.main()
