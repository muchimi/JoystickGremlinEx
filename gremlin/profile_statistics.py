"""Read-only statistics for the mappings in a loaded profile."""

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import cached_property

from gremlin import joystick_handling, keyboard, macro
from gremlin.base_buttons import VirtualAxisButton, VirtualHatButton
from gremlin.base_profile import AbstractContainerAction
from gremlin.gated_handler import GateConditionType
from gremlin.input_item import BaseInputActionCondition, BaseModeCondition, BaseVJoyCondition, getInputIdKey
from gremlin.input_types import InputType
from gremlin.types import ButtonOutputMode, DeviceType, GamePadOutput, HatDirection, VjoyAction
from gremlin.ui.joystick_device import BaseJoystickCondition
from gremlin.ui.keyboard_device import BaseKeyboardCondition
from gremlin.ui.state_device import BaseStateCondition


VIRTUAL_TYPES = (DeviceType.VJoy, DeviceType.Maestro)
INTERNAL_TYPES = (DeviceType.State, DeviceType.ModeControl, DeviceType.Settings, DeviceType.Plugins)
KEYBOARD_TYPES = (InputType.Keyboard, InputType.KeyboardLatched)
CONTROL_NAMES = {InputType.JoystickAxis: "Axis", InputType.JoystickButton: "Button", InputType.JoystickHat: "Hat"}
log = logging.getLogger("system")
SIMPLE_OUTPUTS = {
    "map-to-mouse": ("Mouse", "Mouse"),
    "map_to_mouse_ex": ("Mouse", "Mouse"),
    "map-to-octavi-ifr1": ("Octavi IFR-1", "Controller"),
    "map-to-simconnect": ("SimConnect", "Simulator"),
    "text-to-speech": ("Default audio device", "Audio"),
}


def _markdown_text(value):
    value = str(value).replace("\\", "\\\\").replace("|", "\\|")
    for marker in ("`", "*", "_", "[", "]"):
        value = value.replace(marker, "\\" + marker)
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return value.replace("\n", " ").replace("\r", " ")


def _markdown_table(headers, rows):
    def row_text(row):
        return "| " + " | ".join(_markdown_text(value) for value in row) + " |"

    return [row_text(headers), row_text(["---"] * len(headers)), *(row_text(row) for row in rows), ""]


@dataclass
class InputBinding:
    device_key: str
    device_name: str
    mode: str
    item: object
    actions: list = field(default_factory=list)
    key_conditions: list = field(default_factory=list)

    @cached_property
    def input_name(self):
        if self.item.input_type in KEYBOARD_TYPES:
            keys = getattr(self.item, "keynames", ())
            return " + ".join(keys) if keys else (getattr(self.item, "display_name", "") or str(self.item.input_id))
        if self.item.input_type in (InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat, InputType.ModeControl):
            return getattr(self.item, "short_display_name", "") or str(self.item.input_id)
        return getattr(self.item, "display_name", "") or str(self.item.input_id)


@dataclass
class MappedAction:
    action: object
    chain: tuple[str, ...]


@dataclass
class ProfileStatistics:
    name: str
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    actions: Counter = field(default_factory=Counter)
    containers: Counter = field(default_factory=Counter)
    mapping_usage: Counter = field(default_factory=Counter)
    input_types: Counter = field(default_factory=Counter)
    lengths: dict = field(default_factory=dict)
    modes: dict = field(default_factory=dict)
    mode_parents: dict[str, str | None] = field(default_factory=dict)
    totals: Counter = field(default_factory=Counter)
    bindings: list[InputBinding] = field(default_factory=list)
    profile_output_bindings: list = field(default_factory=list)
    virtual_names: dict = field(default_factory=dict)

    def sections(self):
        """Return the table data shared by the dialog and the Markdown export."""
        kinds = Counter(kind for _, kind in self.inputs.values())
        summary = [
            ("Input devices in use", len(self.inputs)),
            ("Virtual devices used as input", kinds["Virtual"]),
            ("Joysticks in use", kinds["Joystick"]),
            ("Gamepads in use", kinds["Gamepad"]),
            ("Other input devices in use", kinds["Other"]),
            ("Virtual devices enabled as input", self.totals["virtual_enabled"]),
            ("Output devices and destinations in use", len(self.outputs)),
            ("Virtual output devices", sum(kind == "Virtual" for _, kind in self.outputs.values())),
            ("Modes", self.totals["modes"]),
            ("Actions defined", self.actions.total()),
            ("Containers", self.containers.total()),
            ("Conditions", self.totals["conditions"]),
            ("Distinct mapped inputs", self.input_types.total()),
            ("Mapping assignments", len(self.bindings)),
            ("Mapped axes", self.input_types["Axes"]),
            ("Mapped joystick buttons", self.input_types["Buttons"]),
            ("Mapped joystick hats", self.input_types["Hats"]),
            ("Keyboard inputs mapped", self.input_types["Keyboard"]),
            ("Keys referenced by keyboard conditions", self.totals["condition_keys"]),
            ("OSC input commands mapped", self.input_types["OSC"]),
            ("OSC output commands mapped", self.totals["osc_commands"]),
            ("MIDI input commands mapped", self.input_types["MIDI"]),
            ("States defined", self.totals["states"]),
            ("States used", self.totals["used_states"]),
            ("Expression states used", self.totals["used_expressions"]),
            ("Expression states defined", self.totals["expressions"]),
        ]
        for name, (count, longest) in self.lengths.items():
            summary.extend(((f"{name} definitions", count), (f"Longest {name.lower()} (steps)", longest)))
        actions = sorted(self.actions.items(), key=lambda row: (-row[1], row[0].casefold()))
        usage = []
        for kind, definitions in (("Container", self.containers), ("Action", self.actions)):
            for name, count in sorted(definitions.items(), key=lambda row: (-row[1], row[0].casefold())):
                mappings = self.mapping_usage[kind, name]
                share = mappings / len(self.bindings) if self.bindings else 0
                usage.append((kind, name, count, mappings, f"{share:.2%}"))
        usage.sort(key=lambda row: row[3], reverse=True)
        mode_columns = ("inputs", "Axes", "Keyboard", "OSC", "MIDI", "actions", "conditions")
        modes = [(name or "Profile-wide", *(values[column] for column in mode_columns)) for name, values in self.modes.items()]
        mode_parents = [(mode, parent or "No parent") for mode, parent in self.mode_parents.items()]
        devices = [
            (direction, kind, name)
            for direction, mapping in (("Input", self.inputs), ("Output", self.outputs))
            for name, kind in sorted(mapping.values(), key=lambda row: (row[1], row[0].casefold()))
        ]
        return (
            ("Overview", ("Metric", "Count"), summary),
            ("Actions", ("Action", "Count"), actions),
            ("Mapping Usage", ("Kind", "Name", "Definitions", "Mappings using it", "% of all mappings"), usage),
            ("Modes", ("Mode", "Mapped inputs", "Axes", "Keyboard", "OSC", "MIDI", "Actions", "Conditions"), modes),
            ("Mode Parenting", ("Mode", "Parent mode"), mode_parents),
            ("Devices", ("Direction", "Type", "Device or destination"), devices),
            ("Output Bindings", ("Output", "Input device", "Input", "Mode", "Mapping chain"), self.output_bindings),
        )

    def to_markdown(self, *, statistics=True, keybinds=False, bindings=False):
        title = "Profile Report" if keybinds or bindings else "Profile Statistics"
        lines = [f"# {title}", "", f"Profile: {_markdown_text(self.name)}", ""]
        if statistics:
            lines.extend((COUNTING_NOTE, ""))
            for title, headers, rows in self.sections():
                lines.extend((f"## {title}", "", *_markdown_table(headers, rows)))
        if keybinds:
            lines.extend(self.keybind_report)
        if bindings:
            lines.extend(self.binding_report)
        return "\n".join(lines)

    def _virtual_name(self, key):
        return self.virtual_names.get(str(key)) or (f"vJoy {key}" if isinstance(key, int) else (str(key) if key else "Unassigned virtual output"))

    @staticmethod
    def _hat_buttons(action):
        buttons = defaultdict(list)
        for direction, button in action.hat_map.items():
            if button and action.hat_mode_map.get(direction) != ButtonOutputMode.NoOp:
                buttons[button].append(HatDirection.to_display_name(HatDirection(direction)))
        return buttons

    def _virtual_controls(self, action):
        mode = action.action_mode
        device = action.virtual_device
        if not device or mode is None or VjoyAction.is_command(mode):
            return ()
        if VjoyAction.is_axis_action(mode) or mode == VjoyAction.VJoySetAxisStepped:
            return (f"{device.name} Axis {action.vjoy_axis_id}",)
        if VjoyAction.is_hat_action(mode):
            return (f"{device.name} Hat {action.vjoy_hat_id}",)
        return (f"{device.name} Button {action.vjoy_button_id}",)

    def _action_outputs(self, action):
        match action.tag:
            case "vjoyremap":
                return self._virtual_controls(action)
            case "remap":
                kind = CONTROL_NAMES.get(action.input_type, "Button")
                return (f"{self._virtual_name(action.vjoy_id)} {kind} {action.vjoy_input_id}",)
            case "split-axis":
                return (
                    f"{self._virtual_name(action.device_low_vjoy_id)} Axis {action.device_low_axis}",
                    f"{self._virtual_name(action.device_high_vjoy_id)} Axis {action.device_high_axis}",
                )
            case "map-to-osc" | "map-to-osc-ex":
                return (self._action_label(action),) if action.command else ()
            case "map-to-gamepad":
                return (
                    (f"Gamepad {action.device_index + 1} {GamePadOutput.to_display_name(action.output_mode)}",)
                    if action.output_mode != GamePadOutput.NotSet
                    else ()
                )
            case "map-to-keyboard" | "map-to-keyboard-ex":
                return tuple(self._key_output(key) for key in _keyboard_output_keys(action))
            case "macro":
                return tuple(output for step in action.sequence if (output := self._macro_output(step)))
            case "map_to_state":
                return tuple(f"State {key}" for key in {*(state.key for state in action.target_states()), *action.hat_map.values()} if key)
            case "map-to-streamdeck":
                return (f"Stream Deck {action.device_id}",) if action.device_id else ()
            case "gex-map-to-application":
                target = action.program or action.window_title
                return (f"Application {target}",) if target else ()
            case "play-sound":
                return (action.audio_device or "Default audio device",)
            case "virpil-led":
                return (action.device.name,) if action.device else ()
            case "map-to-mouse" | "map_to_mouse_ex":
                return ("Mouse movement" if action.motion_input else f"Mouse {action.button_id.name}",)
            case "map-to-simconnect":
                return (f"SimConnect {action.command}",) if action.command else ()
            case _:
                return (SIMPLE_OUTPUTS[action.tag][0],) if action.tag in SIMPLE_OUTPUTS else ()

    @staticmethod
    def _key_output(key):
        kind = "Mouse" if getattr(key, "is_mouse", False) else "Keyboard"
        return f"{kind} {key.name}" if key else ""

    def _macro_output(self, step):
        if isinstance(step, macro.VJoyMacroAction):
            kind = CONTROL_NAMES.get(step.input_type, "Control")
            return f"{self._virtual_name(step.device_guid or step.vjoy_id)} {kind} {step.input_id}"
        if isinstance(step, macro.KeyAction):
            return self._key_output(step.key)
        if isinstance(step, macro.MouseButtonAction):
            return f"Mouse {step.button.name}"
        if isinstance(step, macro.MouseMotionAction):
            return "Mouse movement"
        if isinstance(step, macro.StreamDeckAction) and step.device_id:
            return f"Stream Deck {step.device_id}"
        if isinstance(step, macro.StateAction) and step.key:
            return f"State {step.key}"
        return ""

    @cached_property
    def output_bindings(self):
        rows = list(self.profile_output_bindings)
        device_keys = defaultdict(set)
        for binding in self.bindings:
            device_keys[binding.device_name].add(binding.device_key)
        for binding in self.bindings:
            device = binding.device_name
            if len(device_keys[device]) > 1:
                device = f"{device} ({binding.device_key})"
            for mapping in binding.actions:
                chain = " → ".join(mapping.chain)
                action = mapping.action
                if action.tag == "vjoyremap" and action.action_mode == VjoyAction.VJoyHatToButton and action.virtual_device:
                    for button, directions in self._hat_buttons(action).items():
                        output = f"{action.virtual_device.name} Button {button}"
                        hat_condition = f"Hat direction {' or '.join(directions)}"
                        rows.append((output, device, binding.input_name, binding.mode, f"{chain} [if {hat_condition}]"))
                else:
                    outputs = tuple(filter(None, self._action_outputs(action)))
                    rows.extend((output, device, binding.input_name, binding.mode, chain) for output in outputs)
                    if action.tag == "vjoyremap" and action.action_mode == VjoyAction.VJoyMergeAxis:
                        for source in action.merge_data:
                            if source.device_guid and source.input_id:
                                key = str(source.device_guid)
                                name = self.inputs.get(key, (key, None))[0]
                                rows.extend((output, name, f"Axis {source.input_id}", binding.mode, f"{chain} (merged input)") for output in outputs)
        return sorted(dict.fromkeys(rows), key=lambda row: tuple(value.casefold() for value in row))

    def _action_label(self, action):
        if action.tag == "vjoyremap":
            mode = action.action_mode
            if mode is None:
                return action.name
            label = VjoyAction.to_name(mode)
            if VjoyAction.is_command(mode):
                return label
            device = action.virtual_device
            destination = device.name if device else "Unassigned virtual output"
            if mode == VjoyAction.VJoyHatToButton:
                buttons = self._hat_buttons(action)
                targets = ", ".join(f"Button {index} ({' or '.join(buttons[index])})" for index in sorted(buttons)) or "No buttons assigned"
            elif VjoyAction.is_axis_action(mode) or mode == VjoyAction.VJoySetAxisStepped:
                targets = f"Axis {action.vjoy_axis_id}"
            elif VjoyAction.is_hat_action(mode):
                targets = f"Hat {action.vjoy_hat_id}"
            else:
                targets = f"Button {action.vjoy_button_id}"
            return f"{destination} {targets} ({label})"
        if action.tag == "remap":
            kind = {InputType.JoystickAxis: "Axis", InputType.JoystickHat: "Hat"}.get(action.input_type, "Button")
            return f"{self._virtual_name(action.vjoy_id)} {kind} {action.vjoy_input_id}"
        if action.tag == "split-axis":
            low = f"{self._virtual_name(action.device_low_vjoy_id)} Axis {action.device_low_axis}"
            high = f"{self._virtual_name(action.device_high_vjoy_id)} Axis {action.device_high_axis}"
            return f"Split Axis → {low} / {high}"
        if action.tag in ("map-to-osc", "map-to-osc-ex") and action.command:
            return f"OSC {action.server_ip}:{action.server_port} {action.command}"
        if action.tag == "map-to-streamdeck":
            return f"{action.name} → {action.device_id}" if action.device_id else action.name
        if action.tag == "macro":
            return f"{action.name} ({len(action.sequence)} steps)"
        try:
            display = getattr(action, "display_name", None)
            detail = display() if callable(display) else display
        except Exception:
            log.debug("Could not format binding for %s", action.name, exc_info=True)
            return action.name
        return detail if detail and detail != "Action" else action.name

    def _binding_targets(self, binding):
        return " · ".join(" → ".join(mapping.chain) for mapping in binding.actions) or "No actions defined"

    def condition_label(self, condition):
        comparison = getattr(condition, "comparison", "")
        if isinstance(condition, BaseStateCondition):
            target = f"State {condition.key}"
        elif isinstance(condition, BaseKeyboardCondition):
            target = f"Keyboard {condition.key.name if condition.key else 'unassigned key'}"
        elif isinstance(condition, (BaseJoystickCondition, BaseVJoyCondition)):
            device = getattr(condition, "device_name", "")
            if not device and isinstance(condition, BaseVJoyCondition):
                device = self._virtual_name(condition.vjoy_id)
            control = CONTROL_NAMES.get(getattr(condition, "input_type", None), "Control")
            target = f"{device or 'Joystick'} {control} {getattr(condition, 'input_id', '?')}"
            if control == "Axis" and (limits := getattr(condition, "range", None)):
                comparison = f"{comparison} [{limits[0]:g}, {limits[1]:g}]".strip()
        elif isinstance(condition, BaseModeCondition):
            target = f"Mode {condition.mode}"
        elif isinstance(condition, BaseInputActionCondition):
            target = "Trigger input"
        else:
            return str(condition)
        label = " ".join(filter(None, (target, comparison)))
        if delay := getattr(condition, "delay", 0):
            label += f" (delay {delay:g} s)"
        return label

    @cached_property
    def keybind_report(self):
        lines = ["## Input Keybinds", ""]
        mapped = [(binding.mode, binding.input_name, self._binding_targets(binding)) for binding in self.bindings if binding.item.input_type in KEYBOARD_TYPES]
        if mapped:
            lines.extend(_markdown_table(("Mode", "Keybind", "Maps to"), sorted(mapped, key=lambda row: (row[0].casefold(), row[1].casefold()))))
        else:
            lines.extend(("No keyboard inputs are mapped.", ""))
        conditions = {
            (condition.key.name, condition.comparison, binding.mode, binding.device_name, binding.input_name)
            for binding in self.bindings
            for condition in binding.key_conditions
        }
        if conditions:
            lines.extend(("### Keyboard Conditions", ""))
            lines.extend(_markdown_table(("Key", "Condition", "Mode", "Device", "Input"), sorted(conditions)))
        return lines

    @cached_property
    def binding_report(self):
        lines = [
            "## Bindings by Device",
            "",
            "Rows show mappings defined in each mode. Actions in sequences and conditional branches are listed under their source input.",
            "",
        ]
        devices = defaultdict(list)
        for binding in self.bindings:
            devices[binding.device_name, binding.device_key].append((binding.mode, binding.input_name, self._binding_targets(binding)))
        duplicates = Counter(name for name, _ in devices)
        for name, key in sorted(devices, key=lambda group: (group[0].casefold(), group[1])):
            heading = f"{name} ({key})" if duplicates[name] > 1 else name
            lines.extend((f"### {_markdown_text(heading)}", ""))
            lines.extend(_markdown_table(("Mode", "Input", "Maps to"), sorted(devices[name, key], key=lambda row: row[0].casefold())))
        if not devices:
            lines.extend(("No input bindings are defined.", ""))
        return lines


COUNTING_NOTE = (
    "Overview: Distinct inputs across all modes. "
    "Mode totals: Assignments defined per mode (excludes inherited copies). "
    "Profile-wide: States, voice, and startup mappings. "
    "Device totals: Configured mappings and condition sources (includes offline). "
    "Mapping usage: Counted once per mode and type (a mapping can use multiple types)."
)


def _keyboard_output_keys(action):
    for code in action.keys:
        if isinstance(code, tuple):
            key = keyboard.key_from_code(*code)
        elif isinstance(code, int):
            key = keyboard.KeyMap.find_virtual(code)
        else:
            key = code
        if getattr(key, "name", None):
            yield key


def _state_key(value):
    return (value or "").strip().casefold()


def _input_kind(device_type, device, name):
    if device_type in VIRTUAL_TYPES or (device and device.is_virtual):
        return "Virtual"
    # Button panels and keypads can present as generic joystick/gamepad HID devices.
    label = name.casefold()
    if any(word in label for word in ("azeron", "keypad", "button box", "button controller", "throttle", "pedal", "crosswind")):
        return "Other"
    if device and device.is_gamepad:
        return "Gamepad"
    if device_type == DeviceType.Joystick and (not device or device.axis_count or device.usage == 0x04):
        return "Joystick"
    return "Other"


class _Collector:
    def __init__(self, profile, master_mode):
        self.profile = profile
        self.master_mode = master_mode
        self.stats = ProfileStatistics(profile.name or "Untitled")
        self.states = list(profile.state.getStates().values())
        self.state_keys = {_state_key(state.key) for state in self.states}
        self.devices = {str(device.device_guid): device for device in joystick_handling.all_joystick_devices()}
        self.devices.update({str(node.device_guid): node.device for node in profile.devices.values() if node.device})
        self.virtuals = joystick_handling.virtual_device_map()
        self.input_keys = defaultdict(set)
        self.osc_commands = set()
        self.condition_keys = set()
        self.used_states = set()
        self.mapped_states = set()
        self.resolved_outputs = {}

    def input_device(self, guid, name=None, device_type=DeviceType.NotSet):
        if not guid or device_type in INTERNAL_TYPES:
            return
        guid = str(guid)
        device = self.devices.get(guid)
        if device:
            device_type = device.device_type
        name = (device.name if device else None) or name or guid
        self.stats.inputs[guid] = (name, _input_kind(device_type, device, name))

    def output(self, kind, name):
        if name:
            self.stats.outputs[kind, name.casefold()] = (name, kind)

    def virtual_output(self, key=None, device=None):
        if not device and key not in (None, "", 0, -1):
            if key not in self.resolved_outputs:
                target = joystick_handling.get_output_target(key)
                self.resolved_outputs[key] = target.device if target else None
            device = self.resolved_outputs[key]
        if device:
            self.stats.outputs["Virtual", str(device.device_guid)] = (device.name, "Virtual")
            if key is not None:
                self.stats.virtual_names[str(key)] = device.name
        elif key not in (None, "", 0, -1):
            name = f"vJoy {key}" if isinstance(key, int) else str(key)
            self.stats.outputs["Virtual", str(key)] = (name, "Virtual")

    def virtual_input(self, key):
        if not key:
            return
        device = self.virtuals.get(DeviceType.VJoy, {}).get(key) if isinstance(key, int) else self.devices.get(str(key))
        guid = device.device_guid if device else key
        name = device.name if device else (f"vJoy {key}" if isinstance(key, int) else str(key))
        self.input_device(guid, name, device.device_type if device else DeviceType.VJoy)

    def conditions(self, owner, mode_counts, binding, *, count):
        labels = []
        for condition in owner.conditions:
            labels.append(self.stats.condition_label(condition))
            if not count:
                continue
            self.stats.totals["conditions"] += 1
            mode_counts["conditions"] += 1
            if isinstance(condition, BaseStateCondition):
                self.used_states.add(_state_key(condition.key))
            elif isinstance(condition, BaseVJoyCondition):
                self.virtual_input(condition.vjoy_id)
            elif isinstance(condition, BaseJoystickCondition):
                self.input_device(condition.device_guid, condition.device_name, DeviceType.Joystick)
            elif isinstance(condition, BaseKeyboardCondition) and condition.key:
                self.input_device("keyboard", "Keyboard", DeviceType.Keyboard)
                self.condition_keys.add((condition.scan_code, condition.is_extended))
                binding.key_conditions.append(condition)
        rule = getattr(getattr(owner, "activation_condition", None), "rule", None)
        return (" OR " if getattr(rule, "name", None) == "Any" else " AND ").join(labels)

    def length(self, name, steps):
        count, longest = self.stats.lengths.get(name, (0, 0))
        self.stats.lengths[name] = (count + 1, max(longest, steps))

    def macro_step(self, step):
        if isinstance(step, macro.StateAction):
            self.used_states.add(_state_key(step.key))
        elif isinstance(step, macro.VJoyMacroAction):
            self.virtual_output(step.device_guid or step.vjoy_id)
        elif isinstance(step, macro.JoystickAction):
            self.input_device(step.device_guid, device_type=DeviceType.Joystick)
        elif isinstance(step, macro.KeyAction):
            self.output("Keyboard", "Keyboard")
        elif isinstance(step, (macro.MouseButtonAction, macro.MouseMotionAction)):
            self.output("Mouse", "Mouse")
        elif isinstance(step, macro.StreamDeckAction):
            self.output("Stream Deck", step.device_id)

    def action(self, action, mode_counts):
        self.stats.actions[action.name] += 1
        mode_counts["actions"] += 1
        match action.tag:
            case "macro":
                self.length("Macro", len(action.sequence))
                for step in action.sequence:
                    self.macro_step(step)
            case "map_to_state":
                self.used_states.update(_state_key(state.key) for state in action.target_states())
                self.used_states.update(_state_key(key) for key in action.hat_map.values())
            case "vjoyremap":
                if not VjoyAction.is_command(action.action_mode):
                    self.virtual_output(device=action.virtual_device)
                for entry in action.merge_data:
                    self.input_device(entry.device_guid, device_type=DeviceType.Joystick)
            case "remap":
                self.virtual_output(action.vjoy_id)
            case "split-axis":
                self.virtual_output(action.device_low_vjoy_id)
                self.virtual_output(action.device_high_vjoy_id)
            case "map-to-osc" | "map-to-osc-ex":
                if action.command:
                    host = action.server_ip or ""
                    self.osc_commands.add((host.casefold(), action.server_port, action.command))
                    if host and action.server_port:
                        self.output("OSC", f"{host}:{action.server_port}")
            case "map-to-gamepad":
                self.output("Gamepad", f"Gamepad {action.device_index + 1}")
            case "map-to-keyboard" | "map-to-keyboard-ex":
                for key in _keyboard_output_keys(action):
                    kind = "Mouse" if getattr(key, "is_mouse", False) else "Keyboard"
                    self.output(kind, kind)
            case "map-to-streamdeck":
                self.output("Stream Deck", action.device_id)
            case "gex-map-to-application":
                self.output("Application", action.program or action.window_title)
            case "play-sound":
                self.output("Audio", action.audio_device or "Default audio device")
            case "virpil-led":
                if action.device:
                    self.stats.outputs["Controller", str(action.device.device_guid)] = (action.device.name, "Controller")
            case _:
                if action.tag in SIMPLE_OUTPUTS:
                    name, kind = SIMPLE_OUTPUTS[action.tag]
                    self.output(kind, name)

    def mapping(self, binding, mode_counts):
        pending = [(binding.item, (), frozenset())]
        seen = set()
        container_types = set()
        while pending:
            current, parent_chain, ancestors = pending.pop()
            if current is None or id(current) in ancestors:
                continue
            ancestors = ancestors | {id(current)}
            count = id(current) not in seen
            seen.add(id(current))
            for container in current.containers:
                name = getattr(container, "name", None) or container.tag
                if count:
                    self.stats.containers[name] += 1
                container_types.add(name)
                condition = self.conditions(container, mode_counts, binding, count=count)
                state = getattr(container, "state", None) if container.tag == "state" else None
                gates = []
                if state:
                    value = container.required_value
                    gates.append(f"State {state} {'exists' if value is None else ('is on' if value else 'is off')}")
                    self.used_states.add(_state_key(state))
                if getattr(container, "has_virtual_button", False):
                    button = container.virtual_button
                    if isinstance(button, VirtualAxisButton):
                        gates.append(f"Trigger axis in [{button.lower_limit:g}, {button.upper_limit:g}] ({button.direction.name})")
                    elif isinstance(button, VirtualHatButton):
                        gates.append(f"Trigger hat direction {' or '.join(button.directions)}")
                if gates:
                    condition = " AND ".join(([f"({condition})"] if condition else []) + gates)
                sets = container.get_action_sets()
                if count and container.tag in ("chain", "sequence"):
                    self.length(container.tag.capitalize(), len(sets))
                for index, actions in enumerate(sets, start=1):
                    container_label = f"{name} (step {index})" if container.tag in ("chain", "sequence") else name
                    if condition:
                        container_label += f" [if {condition}]"
                    chain = (*parent_chain, container_label)
                    for action in actions or ():
                        if action is None:
                            continue
                        if count:
                            self.action(action, mode_counts)
                        label = self.stats._action_label(action)
                        condition_text = self.conditions(action, mode_counts, binding, count=count)
                        if condition_text:
                            label += f" [if {condition_text}]"
                        action_chain = (*chain, label)
                        binding.actions.append(MappedAction(action, action_chain))
                        if isinstance(action, AbstractContainerAction):
                            pending.extend((child, action_chain, ancestors) for child in action._item_data_map.values())
                        if action.tag == "gated-axis":
                            for data in action.gates:
                                for gate in data.getGates():
                                    for trigger, child in gate.item_data_map.items():
                                        branch = f"{GateConditionType.to_display_name(trigger)} at {gate.value:g}"
                                        pending.append((child, (*action_chain, branch), ancestors))
                                for axis_range in data.getRanges():
                                    for trigger, child in axis_range.item_data_map.items():
                                        branch = f"{GateConditionType.to_display_name(trigger)} [{axis_range.range_min:g}, {axis_range.range_max:g}]"
                                        pending.append((child, (*action_chain, branch), ancestors))
        self.stats.mapping_usage.update(("Container", name) for name in container_types)
        self.stats.mapping_usage.update(("Action", name) for name in {mapping.action.name for mapping in binding.actions})

    def input_mapping(self, item, mode, guid=None, device_type=DeviceType.NotSet, name=None):
        if item is None or not item.containers:
            return
        input_type = item.input_type
        mode_counts = self.stats.modes.setdefault(mode, Counter())
        mode_counts["inputs"] += 1
        identity = str(getInputIdKey(item.input_id))
        label = {
            InputType.JoystickAxis: "Axes",
            InputType.JoystickButton: "Buttons",
            InputType.JoystickHat: "Hats",
            InputType.OpenSoundControl: "OSC",
            InputType.Midi: "MIDI",
        }.get(input_type, "Keyboard" if input_type in KEYBOARD_TYPES else "Other")
        mode_counts[label] += 1
        if input_type in KEYBOARD_TYPES:
            guid, name = "keyboard", "Keyboard"
        elif input_type == InputType.Midi:
            name = item.port_name or "MIDI input"
            guid = f"midi:{name}"
        elif input_type == InputType.StreamDeck:
            guid = f"streamdeck:{item.device_id}"
            name = item.device_id or "Stream Deck"
        self.input_keys[label].add((guid, label if label == "Keyboard" else input_type, identity))
        self.input_device(guid, name, device_type)
        device_name = self.stats.inputs.get(guid, (name, None))[0]
        binding = InputBinding(guid or "states", device_name or "States", mode or "Profile-wide", item)
        self.stats.bindings.append(binding)
        self.mapping(binding, mode_counts)

    def collect(self):
        modes = self.profile.get_modes()
        self.stats.modes = {mode: Counter() for mode in modes}
        for node in self.profile.modeTree().descendants:
            if node.name != self.master_mode:
                parent = node.parent.name
                self.stats.mode_parents[node.name] = "Profile-wide" if parent == self.master_mode else parent
        self.stats.totals["modes"] = len(modes)
        for guid, device in self.profile.devices.items():
            if device.device_type in (DeviceType.State, DeviceType.Voice):
                continue
            for mode, data in device.modes.items():
                for items in data.config.values():
                    for item in items.values():
                        self.input_mapping(item, None if mode == self.master_mode else mode, str(guid), device.device_type, device.name)

        for state in self.states:
            key = _state_key(state.key)
            if state.isExpression:
                tokens = (state.expression or "").casefold().replace("(", " ").replace(")", " ").split()
                self.used_states.update(token for token in tokens if token != key and token in self.state_keys)
            if state.containers:
                self.mapped_states.add(id(state))
                self.input_mapping(state, None)
        for item in self.profile.voice.getVoices():
            self.input_mapping(item, None, "voice", DeviceType.Voice, "Voice")
        for entry in self.profile.merge_axes:
            if "vjoy" in entry:
                target = entry["vjoy"]
                self.virtual_output(target["vjoy_id"])
                output = f"{self.stats._virtual_name(target['vjoy_id'])} Axis {target['axis_id']}"
                for side in ("lower", "upper"):
                    if source := entry.get(side):
                        guid = str(source["device_guid"])
                        self.input_device(guid, device_type=DeviceType.Joystick)
                        name = self.stats.inputs.get(guid, (guid, None))[0]
                        mode = entry.get("mode")
                        self.stats.profile_output_bindings.append(
                            (
                                output,
                                name,
                                f"Axis {source['axis_id']}",
                                "Profile-wide" if mode in (None, self.master_mode) else mode,
                                f"Merge Axis ({side} input)",
                            ),
                        )
        for key, settings in self.profile._start_state.items():
            if settings.get("buttons") or settings.get("axis"):
                self.virtual_output(key)
            name = self.stats._virtual_name(key)
            for axis, value in settings.get("axis", {}).items():
                if settings.get("enabled", {}).get(axis, False):
                    self.stats.profile_output_bindings.append((f"{name} Axis {axis}", "Profile", "Startup", "Profile-wide", f"Set axis to {value}"))
            for button, pressed in settings.get("buttons", {}).items():
                self.stats.profile_output_bindings.append(
                    (f"{name} Button {button}", "Profile", "Startup", "Profile-wide", "Press button" if pressed else "Release button")
                )
        self.stats.totals["virtual_enabled"] = sum(len(self.profile.settings.getVirtualAsInputList(kind)) for kind in VIRTUAL_TYPES)
        used_states = [state for state in self.states if id(state) in self.mapped_states or _state_key(state.key) in self.used_states]
        self.stats.totals.update(
            states=len(self.states),
            used_states=len(used_states),
            expressions=sum(state.isExpression for state in self.states),
            used_expressions=sum(state.isExpression for state in used_states),
            osc_commands=len(self.osc_commands),
            condition_keys=len(self.condition_keys),
        )
        self.stats.input_types.update({name: len(keys) for name, keys in self.input_keys.items()})
        return self.stats


def collect_profile_statistics(profile, master_mode):
    return _Collector(profile, master_mode).collect()
