"""Convert line-oriented sequence text to and from native profile XML."""

from decimal import Decimal
import html
import json
import math
from pathlib import Path
import re

from lxml import etree


_MODES = {
    "once": "normal",
    "repeat while pressed": "loop",
    "toggle": "toggle",
    "step": "step",
    "wiggle": "wiggle",
}
_OUTPUT_ACTIONS = {
    "hold": "VJoyButton",
    "press": "VJoyButtonPress",
    "release": "VJoyButtonRelease",
    "pulse": "VJoyPulse",
    "set": "VJoySetAxis",
}
_TRIGGER = {"exec_on_press": "True", "exec_on_release": "False"}
_CONTAINER_DEFAULTS = {
    "priority": "0", "collapsed": "False", "trigger-on-press": "True", "trigger-on-release": "False",
    "ignore-release": "True", "resume-mode": "False", "sync-mode": "0", "stepped-exec-reset": "True",
    "normal-exec": "0", "autorelease-exec": "0", "wiggle-min": "250", "wiggle-max": "5000",
    "wiggle-exec": "250", "wiggle-step": "250", "wiggle-random": "True", "wiggle-random-steps": "False",
    "wiggle-count-min": "1", "wiggle-count-max": "1", "wiggle-count-enabled": "False",
}
_STEP_DEFAULTS = {
    "mode": "normal", "repeat-count": "2", "repeat-min": "250", "repeat-max": "250",
    "autorelease-min": "250", "autorelease-max": "250", "randomize-delay": "False",
    "randomize-autorelease": "False",
}
_ACTION_DEFAULTS = {
    "vjoyremap": {"sync-mode": "0", "ignore-release": "False", "paired": "False", "start_pressed": "False",
                 "target_relative": "False", "use_relative_value": "False", "auto_release": "False",
                 "target-use-last": "False", "target_value": "0.00000000", "relative_value": "0.00000000",
                 "relative_pulse_delay": "100",
                 "latched-input-type": "button"},
    "map-to-keyboard-ex": {"sync-mode": "0", "wheel-factor": "1", "interval": "250"},
    "play-sound": {"loops": "1", "blocking": "False", "volume": "100", "randomize": "False",
                   "stop-previous": "False", "playback-default": "True", "playback-mode": "RoundRobin"},
}
_REMOTE_DEFAULTS = {
    "custom": "False", "local": "True", "remote": "False", "remote-profile": "True",
    "singleton": "False", "target-process": "False", "partial-title": "True",
}


def _tokens(line):
    """Read JSON strings and objects, bare words, and comments outside quotes."""
    decoder = json.JSONDecoder()
    tokens = []
    while line := line.lstrip():
        if line.startswith("#"):
            break
        if line[0] in '"{':
            value, length = decoder.raw_decode(line)
            if len(line) > length and not (line[length].isspace() or line[length] == "#"):
                raise ValueError("Separate arguments with a space.")
        else:
            word = re.match(r'[^\s#"{}]+', line)
            if word is None:
                raise ValueError("Expected a word, a quoted string, or a settings object.")
            value, length = word.group(), word.end()
        tokens.append(value)
        line = line[length:]
    return tokens


def _duration(value):
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s)", value, re.IGNORECASE)
    if match is None:
        raise ValueError(f'Invalid duration "{value}". Use milliseconds or seconds, such as 125ms.')
    ms = Decimal(match[1]) * (1000 if match[2].casefold() == "s" else 1)
    if ms != ms.to_integral_value() or not 0 <= ms <= 2_147_483_647:
        raise ValueError(f'Invalid duration "{value}". Use a whole number of milliseconds in range.')
    return str(int(ms))


def _axis_value(value):
    number = float(value)
    if not math.isfinite(number) or not -1 <= number <= 1:
        raise ValueError("Axis values must be between -1 and 1.")
    return str(number)


def _repeat_count(value):
    if not value.isdecimal() or not 2 <= int(value) <= 2_147_483_647:
        raise ValueError("Repeat count must be an integer of at least 2.")
    return str(int(value))


def _xml(text):
    if not isinstance(text, str):
        raise ValueError("Expected quoted XML.")
    node = etree.fromstring(text.encode("utf-8"), parser=etree.XMLParser(resolve_entities=False, no_network=True))
    if node.getroottree().docinfo.doctype:
        raise ValueError("XML document types are unavailable in sequence text.")
    return node


def _with_settings(tokens):
    if len(tokens) >= 2 and tokens[-2] == "with" and isinstance(tokens[-1], dict):
        tokens, settings = tokens[:-2], tokens[-1]
        if not tokens:
            raise ValueError("Missing command before settings.")
    else:
        settings = {}
    if not all(isinstance(token, str) for token in tokens):
        raise ValueError("Put extra settings after 'with'.")
    return tokens, settings


def _attributes(attributes):
    if not isinstance(attributes, dict) or not all(isinstance(value, str) for value in attributes.values()):
        raise ValueError("Native settings attributes must be strings.")
    return attributes


def _apply_settings(node, settings, *, protected=(), child_tags=None):
    if settings.keys() - {"attrs", "children"}:
        raise ValueError("Expected attrs or children in native settings.")
    attributes = _attributes(settings.get("attrs", {}))
    if set(protected) & attributes.keys():
        raise ValueError("Set the command's value in its arguments.")
    node.attrib.update(attributes)
    children = settings.get("children", [])
    if not isinstance(children, list):
        raise ValueError("Native settings children must be a list of XML fragments.")
    for fragment in children:
        child = _xml(fragment)
        if child_tags is not None and child.tag not in child_tags:
            raise ValueError(f'Unexpected settings element "{child.tag}".')
        node.append(child)


class SequenceText:
    """Codec with device and key lookups supplied by the application."""

    def __init__(self, resolve_output, output_label, key_xml, key_label, *, base_folder=None, local_voice=None):
        self.resolve_output = resolve_output
        self.output_label = output_label
        self.key_xml = key_xml
        self.key_label = key_label
        self.base_folder = Path(base_folder) if base_folder else None
        self.local_voice = local_voice

    def parse(self, text, *, action_tags=None):
        """Return a validated container XML node, without editing the profile."""
        document = None
        step = None
        for line_no, line in enumerate(text.splitlines(), 1):
            try:
                tokens, settings = _with_settings(_tokens(line))
                if not tokens:
                    continue
                command = tokens[0].casefold()
                args = tokens[1:]
                if document is None:
                    mode = _MODES.get(" ".join(args).casefold())
                    if command != "sequence" or mode is None:
                        raise ValueError("Start with a sequence mode, such as 'sequence once'.")
                    document = etree.Element("container", _CONTAINER_DEFAULTS | {"type": "sequence", "mode": mode})
                    _apply_settings(document, settings, protected=("type", "mode"),
                                    child_tags={"virtual-button", "activation-condition"})
                elif command == "step":
                    if step is not None:
                        raise ValueError("Close the current step before opening another.")
                    step = self._open_step(document, args, settings)
                    step_line = line_no
                elif command == "end":
                    if [arg.casefold() for arg in args] != ["step"] or settings or step is None:
                        raise ValueError("Expected 'end step' after an open step.")
                    step = None
                elif command == "sequence":
                    raise ValueError("A text definition contains one sequence.")
                else:
                    action = self._action(command, args, settings)
                    if not isinstance(action.tag, str):
                        raise ValueError("Expected an action element.")
                    if action_tags is not None and action.tag not in action_tags:
                        raise ValueError(f'Action "{action.tag}" is unavailable.')
                    destination = step if step is not None else etree.SubElement(document, "action-set")
                    destination.append(action)
            except (ValueError, TypeError, etree.XMLSyntaxError) as error:
                raise ValueError(f"Line {line_no}: {error}") from error
        if step is not None:
            raise ValueError(f"Line {step_line}: Missing 'end step'.")
        if document is None:
            raise ValueError("Enter a sequence definition.")
        if not any(len(action_set) for action_set in document.findall("action-set")):
            raise ValueError("Add at least one action.")
        return document

    @staticmethod
    def _open_step(document, args, settings):
        options = {}
        for arg in args:
            name, separator, value = arg.partition("=")
            name = name.casefold()
            if not separator or name in options or name not in {"repeat", "repeat-delay", "autorelease"}:
                raise ValueError(f'Invalid step option "{arg}".')
            options[name] = value.casefold()
        values = dict(_STEP_DEFAULTS)
        repeat = options.pop("repeat", "none")
        if repeat != "none":
            count = _repeat_count(repeat.removeprefix("random:"))
            values.update(mode="random" if repeat.startswith("random:") else "loop", **{"repeat-count": count})
        elif options:
            raise ValueError("Repeat delay and autorelease require a repeating step.")
        for name, value in options.items():
            low, delimiter, high = value.partition("..")
            minimum, maximum = _duration(low), _duration(high if delimiter else low)
            if int(minimum) > int(maximum):
                raise ValueError(f"{name} starts above its maximum.")
            prefix = "repeat" if name == "repeat-delay" else "autorelease"
            randomize = "randomize-delay" if name == "repeat-delay" else "randomize-autorelease"
            values.update({f"{prefix}-min": minimum, f"{prefix}-max": maximum, randomize: str(bool(delimiter))})
        settings = dict(settings)
        extra_options = _attributes(settings.pop("options", {}))
        if {"index", "mode"} & extra_options.keys():
            raise ValueError("Set step mode in the repeat option.")
        values.update(extra_options)
        values["index"] = str(len(document.findall("action-set")))
        if values["mode"] != "normal" or extra_options:
            etree.SubElement(document, "step-option", values)
        node = etree.SubElement(document, "action-set")
        _apply_settings(node, settings, child_tags=set())
        return node

    def _action(self, command, args, settings):
        protected = ()
        if command in _OUTPUT_ACTIONS and len(args) == (3 if command in ("set", "pulse") else 2):
            device, control = args[:2]
            axis = command == "set"
            prefix = "a" if axis else "b"
            if not re.fullmatch(prefix + r"[1-9][0-9]*", control.casefold()):
                raise ValueError(f'Expected {"an axis" if axis else "a button"}, such as {prefix}1.')
            index = int(control[1:])
            provider, slot = self.resolve_output(device, prefix, index)
            node = etree.Element("vjoyremap", _TRIGGER | {
                "mode": _OUTPUT_ACTIONS[command], "device-type": provider, "virtual-id": str(slot),
                "input": str(index),
            })
            if not axis:
                node.set("button", str(index))
            if axis:
                node.set("target_value", _axis_value(args[2]))
            elif command == "pulse":
                node.set("pulse_delay", _duration(args[2]))
            protected = ("axis", "button", "hat", "vjoy", "pulse-delay")
        elif command == "pause" and len(args) == 1:
            node = etree.Element("pause", mode="0", delay=_duration(args[0]))
        elif command == "key" and args and args[0].casefold() in ("tap", "hold", "press", "release"):
            verb = args[0].casefold()
            if len(args) != (3 if verb == "tap" else 2):
                raise ValueError('Use a key combination such as key tap "Left Ctrl+F13" 50ms.')
            node = etree.Element("map-to-keyboard-ex", _TRIGGER | {
                "mode": "pulse" if verb == "tap" else verb, "interval": "250",
            })
            if verb == "tap":
                node.set("delay", _duration(args[2]))
            for key in args[1].split("+"):
                node.append(self.key_xml(key.strip()))
        elif command == "sound" and len(args) == 1 and args[0]:
            path = Path(args[0])
            if not path.is_absolute() and self.base_folder is not None:
                path = self.base_folder / path
            node = etree.Element("play-sound", _TRIGGER | {"mode": "audio", "file": str(path), "volume": "100"})
        elif command == "say" and args and args[0].strip() and args[1:] in ([], ["engine=edge"]):
            mode = "etts" if args[1:] else "pytts"
            node = etree.Element("play-sound", _TRIGGER | {"mode": mode, "text": html.escape(args[0]), "volume": "100"})
            if self.local_voice and mode == "pytts":
                node.set("speaker", self.local_voice)
        elif command == "action" and len(args) == 1 and not settings:
            return _xml(args[0])
        else:
            raise ValueError(f'Unknown command or invalid arguments for "{command}".')
        # Older exports can include native settings.
        protected = set(protected) | (node.attrib.keys() - _TRIGGER.keys() - {"volume", "interval", "speaker"})
        _apply_settings(node, settings, protected=protected, child_tags=None)
        return node

    def format(self, document, *, notes=None):
        """Export simple commands and optionally report what they leave out."""
        if notes is None:
            notes = []
        mode = next((label for label, mode in _MODES.items() if mode == document.get("mode", "normal")), "once")
        lines = [f"sequence {mode}"]
        if _has_extra_settings(document, {"mode", "type"}, _CONTAINER_DEFAULTS) or any(
            child.tag in ("virtual-button", "activation-condition") for child in document
        ):
            notes.append("Container settings beyond the execution mode use import defaults.")
        options = {child.get("index"): child for child in document.findall("step-option")}
        for index, step in enumerate(document.findall("action-set")):
            commands = []
            extra_action_settings = False
            omitted_actions = set()
            for child in step:
                if not isinstance(child.tag, str):
                    continue
                try:
                    command, extra = self._format_action(child)
                except ValueError:
                    command = None
                if command is None:
                    omitted_actions.add(child.tag)
                else:
                    commands.append(command)
                    extra_action_settings |= extra
            if omitted_actions:
                notes.append(f"Skipped {', '.join(sorted(omitted_actions))} in step {index + 1}.")
            if not commands:
                continue
            try:
                labels = _format_options(options.get(str(index)))
            except ValueError:
                labels = []
                notes.append(f"Step {index + 1} repeat settings use import defaults.")
            if extra_action_settings:
                notes.append(f"Review extra action settings and conditions in step {index + 1} after import.")
            if len(commands) == 1 and not labels:
                lines.extend(commands)
            else:
                lines.append(" ".join(["step", *labels]))
                lines.extend(f"    {command}" for command in commands)
                lines.append("end step")
        if len(lines) == 1:
            raise ValueError("Export requires at least one action with a simple text command.")
        return "\n".join(lines) + "\n"

    def _format_action(self, node):
        mode = node.get("mode", "")
        children = [child for child in node if isinstance(child.tag, str)]
        skipped = set()
        text = None
        if node.tag == "vjoyremap":
            command = next((verb for verb, native in _OUTPUT_ACTIONS.items() if native.casefold() == mode.casefold()), None)
            output = self.output_label(node) if command else None
            axis = command == "set"
            control = node.get("axis" if axis else "button") or node.get("input")
            if output and control and control.isdecimal() and int(control) > 0:
                target = output if re.fullmatch(r'[\w:/.%-]+', output) else _quote(output)
                text = f'{command} {target} {"a" if axis else "b"}{int(control)}'
                skipped = {"mode", "device-type", "virtual-id", "vjoy", "axis", "button", "input"}
                if axis:
                    text += f' {_axis_value(node.get("target_value", "0.0"))}'
                    skipped.add("target_value")
                elif command == "pulse":
                    duration = _duration(f'{node.get("pulse-delay") or node.get("pulse_delay", "250")}ms')
                    text += f" {duration}ms"
                    skipped.update(("pulse-delay", "pulse_delay"))
        elif node.tag == "pause" and mode == "0":
            text, skipped = f'pause {_duration(node.get("delay", "250") + "ms")}ms', {"mode", "delay"}
        elif node.tag == "map-to-keyboard-ex" and mode in ("pulse", "hold", "press", "release"):
            keys = node.findall("key")
            names = [self.key_label(key) for key in keys]
            if names and all(name and "+" not in name for name in names) and not any(len(key) for key in keys):
                verb = "tap" if mode == "pulse" else mode
                text = f'key {verb} {_quote("+".join(names))}'
                skipped = {"mode"}
                if mode == "pulse":
                    text += f' {_duration(node.get("delay", "250") + "ms")}ms'
                    skipped.add("delay")
                children = [child for child in children if child.tag != "key"]
        elif node.tag == "play-sound" and mode == "audio" and node.get("file"):
            path = Path(node.get("file"))
            if self.base_folder and path.is_absolute() and path.is_relative_to(self.base_folder):
                path = path.relative_to(self.base_folder)
            text, skipped = f"sound {_quote(path.as_posix())}", {"mode", "file", "speaker"}
        elif node.tag == "play-sound" and mode in ("pytts", "etts") and node.get("text"):
            text, skipped = f'say {_quote(html.unescape(node.get("text")))}', {"mode", "text"}
            if mode == "etts":
                text += " engine=edge"
            elif node.get("speaker") == self.local_voice:
                skipped.add("speaker")
        if text is None:
            return None, False
        defaults = _TRIGGER | _ACTION_DEFAULTS.get(node.tag, {}) | {"priority": "5"}
        has_extra_children = any(
            child.tag != "remote-config" or len(child) or _has_extra_settings(child, set(), _REMOTE_DEFAULTS)
            for child in children
        )
        return text, has_extra_children or _has_extra_settings(node, skipped, defaults)


def _format_options(node):
    if node is None or (mode := node.get("mode", "normal").casefold()) == "normal":
        return []
    if mode not in ("loop", "random", "repeat"):
        raise ValueError("Unknown repeat mode.")
    count = _repeat_count(node.get("repeat-count", _STEP_DEFAULTS["repeat-count"]))
    labels = [f'repeat={"random:" if mode == "random" else ""}{count}']
    for name, prefix, flag in (("repeat-delay", "repeat", "randomize-delay"),
                               ("autorelease", "autorelease", "randomize-autorelease")):
        min_name, max_name = f"{prefix}-min", f"{prefix}-max"
        minimum = _duration(node.get(min_name, _STEP_DEFAULTS[min_name]) + "ms")
        if node.get(flag, "False").casefold() in ("true", "1"):
            maximum = _duration(node.get(max_name, _STEP_DEFAULTS[max_name]) + "ms")
            if int(minimum) > int(maximum):
                raise ValueError("Invalid repeat delay range.")
            labels.append(f"{name}={minimum}ms..{maximum}ms")
        elif minimum != _STEP_DEFAULTS[min_name]:
            labels.append(f"{name}={minimum}ms")
    return labels


def _quote(text):
    return json.dumps(text, ensure_ascii=False)


def _has_extra_settings(node, skipped, defaults):
    ignored = skipped | {"action_id", "container_id", "guid", "collapsed", "grid-visible", "grid_visible"}
    return any(name not in ignored and defaults.get(name) != value for name, value in node.attrib.items())
