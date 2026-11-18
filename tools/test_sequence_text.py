"""Hardware-free checks for Sequence text import and export."""

import html
from pathlib import Path
import sys
import unittest

from lxml import etree


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.sequence_text import SequenceText


class SequenceTextChecks(unittest.TestCase):
    def setUp(self):
        self.codec = SequenceText(
            self.resolve_output, self.output_label, self.key_xml, lambda key: key.get("name"),
            base_folder=ROOT, local_voice="Test voice",
        )

    def resolve_output(self, name, control, index):
        devices = {"gex-1": ("Maestro", 0), "vjoy-2": ("VJoy", 2)}
        if name not in devices:
            raise ValueError(f"Unknown output {name}")
        if control == "a" and index > 3 or control == "b" and index > 32:
            raise ValueError(f"Unknown control {control}{index}")
        return devices[name]

    def output_label(self, node):
        labels = {("Maestro", "0"): "gex-1", ("VJoy", "2"): "vjoy-2"}
        return labels.get((node.get("device-type"), node.get("virtual-id")))

    def key_xml(self, name):
        codes = {"Left Ctrl": "162", "F13": "124"}
        if name not in codes:
            raise ValueError(f"Unknown key {name}")
        return etree.Element("key", {"name": name, "virtual-code": codes[name]})

    def test_native_actions_and_grouped_step_options(self):
        root = self.codec.parse('''sequence repeat while pressed
press gex-1 b1
pause 125ms
release gex-1 b1
set vjoy-2 a2 0.25
step repeat=3 repeat-delay=100ms..0.25s autorelease=50ms
    hold gex-1 b2
    key hold "Left Ctrl+F13"
end step
step repeat=random:4 autorelease=30ms..80ms
    pulse gex-1 b3 80ms
    key tap "F13" 40ms
end step
sound "sounds/gear lock.wav"
say "Gear #1 locked" # comment
''')
        self.assertEqual(root.get("mode"), "loop")
        self.assertEqual(root.get("autorelease-exec"), "0")
        steps = root.findall("action-set")
        self.assertEqual([len(step) for step in steps], [1, 1, 1, 1, 2, 2, 1, 1])
        self.assertEqual(steps[0][0].get("mode"), "VJoyButtonPress")
        self.assertEqual(steps[1][0].get("delay"), "125")
        self.assertEqual(steps[2][0].get("mode"), "VJoyButtonRelease")
        self.assertEqual(steps[3][0].get("device-type"), "VJoy")
        self.assertEqual(steps[3][0].get("target_value"), "0.25")
        self.assertEqual(steps[4][1].xpath("key/@virtual-code"), ["162", "124"])
        self.assertEqual(steps[5][0].get("pulse_delay"), "80")
        self.assertEqual(steps[5][1].get("delay"), "40")
        self.assertEqual(Path(steps[6][0].get("file")), ROOT / "sounds" / "gear lock.wav")
        self.assertEqual(steps[7][0].get("text"), "Gear #1 locked")
        self.assertEqual(steps[7][0].get("speaker"), "Test voice")
        fixed, randomized = root.findall("step-option")
        self.assertEqual((fixed.get("index"), fixed.get("mode"), fixed.get("repeat-count")), ("4", "loop", "3"))
        self.assertEqual((fixed.get("repeat-min"), fixed.get("repeat-max")), ("100", "250"))
        self.assertEqual(randomized.get("mode"), "random")
        self.assertEqual(randomized.get("randomize-autorelease"), "True")
        notes = []
        text = self.codec.format(root, notes=notes)
        self.assertEqual(notes, [])
        self.assertEqual(self.codec.format(self.codec.parse(text)), text)

    def test_export_uses_simple_commands_and_reports_omitted_settings(self):
        root = self.codec.parse('''sequence toggle with {"attrs": {"autorelease-exec": "250"}}
step repeat=3 autorelease=50ms
    set gex-1 a1 -0.25 with {"attrs": {"priority": "7", "action_id": "axis-action"}}
    action "<map-to-mouse action_id=\\"mouse-action\\" speed=\\"15\\"/>"
end step
key tap "F13" 45ms
say "She said: \\"Gear up\\" ✓" engine=edge with {"attrs": {"speaker": "A selected voice", "volume": "36"}}
''')
        self.assertEqual(root.get("autorelease-exec"), "250")
        etree.SubElement(root, "activation-condition", **{"condition-id": "saved"})
        own_action = root.find("./action-set/vjoyremap")
        self.assertEqual(own_action.get("priority"), "7")
        notes = []
        text = self.codec.format(root, notes=notes)
        self.assertEqual(text, '''sequence toggle
step repeat=3 autorelease=50ms
    set gex-1 a1 -0.25
end step
key tap "F13" 45ms
say "She said: \\"Gear up\\" ✓" engine=edge
''')
        self.assertTrue(any("Container settings" in note for note in notes))
        self.assertIn("Skipped map-to-mouse in step 1.", notes)
        self.assertTrue(any("step 3" in note for note in notes))
        restored = self.codec.parse(text)
        self.assertEqual(restored.get("autorelease-exec"), "0")
        self.assertEqual(restored.find("step-option").get("repeat-min"), "250")
        self.assertIsNone(restored.find("activation-condition"))
        self.assertIsNone(restored.find("./action-set/map-to-mouse"))
        restored_sound = restored.find("./action-set/play-sound")
        self.assertEqual(restored_sound.get("mode"), "etts")
        self.assertEqual(restored_sound.get("volume"), "100")
        self.assertEqual(html.unescape(restored_sound.get("text")), 'She said: "Gear up" ✓')

    def test_export_reports_when_no_actions_have_simple_commands(self):
        root = self.codec.parse('sequence once\naction "<map-to-mouse/>"')
        with self.assertRaisesRegex(ValueError, "Export requires at least one action"):
            self.codec.format(root)

    def test_validation_reports_the_line_and_rejects_unavailable_actions(self):
        for text, message in (
            ("step\npause 25ms", "Line 1"),
            ("sequence once\nstep\npause 200ms", "Line 2"),
            ("sequence once\nstep\nstep", "Line 3"),
            ("sequence once\nend step", "Line 2"),
            ("sequence once\nstep autorelease=125ms", "repeating step"),
            ("sequence once\nstep repeat=3 autorelease=125ms..50ms", "above its maximum"),
            ("sequence once\npause 125", "Line 2"),
            ("sequence once\npause -1ms", "Line 2"),
            ("sequence once\nset gex-1 a4 0", "Unknown control"),
            ("sequence once\nset gex-1 a1 nan", "between -1 and 1"),
            ('sequence once\nkey hold "missing"', "Unknown key"),
            ('sequence once\naction "<unknown/>"', 'Action "unknown" is unavailable'),
        ):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                self.codec.parse(text, action_tags={"vjoyremap", "map-to-keyboard-ex", "pause"})


if __name__ == "__main__":
    unittest.main()
