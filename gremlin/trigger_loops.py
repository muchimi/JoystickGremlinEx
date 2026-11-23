# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
#
# Written for Gremlin Ex by Muchimi
# Some portions are derived from the original 2019 Joystick Gremlin by Lionel Ott and other contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.


"""Find potentialfeedback between configured trigger events before activating a profile.

    this is not foolproof by any means but should at least identify the simplest loops.

"""

from collections import defaultdict
from dataclasses import dataclass
from functools import cache

from gremlin.device_remap import guid_key
from gremlin.input_types import InputType
from gremlin.types import ButtonOutputMode, DeviceType, VjoyAction

_JOYSTICK_TYPES = (InputType.JoystickButton, InputType.JoystickAxis, InputType.JoystickHat)
_VIRTUAL_ACTIONS = ("vjoyremap", "remap", "split-axis", "macro")


@dataclass(frozen=True)
class TriggerInput:
    input_type: InputType
    identifier: int | str
    device: str | None = None


def _state_input(key):
    return TriggerInput(InputType.State, key.casefold())


def _input_key(item):
    if item.input_type == InputType.State and item.key:
        return _state_input(item.key)
    if item.input_type in _JOYSTICK_TYPES and (device := guid_key(item.device_guid)):
        return TriggerInput(item.input_type, item.input_id, device)


def _joystick_outputs(action, source, pressed):
    if not (action.use_actual or (action.exec_on_press if pressed else action.exec_on_release)):
        return ()
    if action.input_type not in _JOYSTICK_TYPES or not (device := guid_key(action.device_id)):
        return ()
    if source.input_type == InputType.JoystickAxis and action.input_type != InputType.JoystickAxis:
        return ()
    target = TriggerInput(action.input_type, action.input_id, device)
    if action.input_type == InputType.JoystickButton:
        phases = {"press": (True,), "release": (False,), "pulse": (True, False)}.get(action.mode, ())
    else:
        # MapToTrigger emits axis and hat events with the default pressed flag.
        phases = (False,)
    return tuple((target, phase) for phase in phases)


def _state_outputs(action, source, pressed, states, targets):
    mode = action.mode
    if mode == "none" or source.input_type == InputType.JoystickAxis:
        return ()
    on_input = action.exec_on_press if pressed else action.exec_on_release
    if not (on_input or mode in ("actual", "pulse") or (not pressed and mode == "invert")):
        return ()
    if source.input_type == InputType.JoystickHat:
        # Hat position can force a state on/off or release a previous position.
        hat_keys = (key for position, key in action.hat_map.items()
                    if key and action.hat_mode_map.get(position) != ButtonOutputMode.NoOp)
        keys = (*hat_keys, *(targets if action.target_mode != "state" else ()))
        return tuple((target, phase) for key in keys if (target := _state_input(key)) in states
                     and not states[target].isExpression for phase in (True, False))

    phases = {"actual": (pressed,), "press": (True,), "release": (False,), "invert": (not pressed,),
              "toggle": (True, False), "latch": (True, False), "pulse": (True, False) if pressed else ()}.get(mode, ())
    return tuple((target, phase) for key in targets if (target := _state_input(key)) in states for phase in phases
                 if (target, phase) != (source, pressed) or mode in ("latch", "pulse"))


def _virtual_input_resolver(profile):
    from gremlin import joystick_handling

    inputs = {guid_key(device.device_guid) for device in joystick_handling.virtual_input_candidates()
              if profile.settings.getVirtualAsInput(device)}
    inputs.discard(None)

    @cache
    def resolve(key):
        if not inputs or key in (None, 0, -1, ""):
            return None
        target = joystick_handling.get_output_target(key)
        if target and (device := guid_key(target.device.device_guid)) in inputs:
            return device

    return resolve


def _virtual_writes(action, pressed):
    """Yield output keys, controls and the input phases they may emit."""
    axis, button, hat = InputType.JoystickAxis, InputType.JoystickButton, InputType.JoystickHat
    if action.tag == "remap":
        phases = (False,) if action.input_type == axis else (pressed,) if action.input_type == button else (False, True)
        yield action.vjoy_id, action.input_type, action.vjoy_input_id, phases
        return
    if action.tag == "split-axis":
        yield action.device_low_vjoy_id, axis, action.device_low_axis, (False,)
        yield action.device_high_vjoy_id, axis, action.device_high_axis, (False,)
        return
    if action.tag == "macro":
        from gremlin.macro import VJoyMacroAction

        for step in action.sequence:
            if not isinstance(step, VJoyMacroAction):
                continue
            phases = (False, True)
            if step.input_type == axis:
                phases = (False,)
            elif step.input_type == button and step.value != "toggle":
                phases = (step.value == "press",)
            yield step.device_guid or step.vjoy_id, step.input_type, step.input_id, phases
        return

    mode = action.action_mode
    device = action.virtual_device
    if not device or mode is None or VjoyAction.is_command(mode):
        return
    key = device.vjoy_id if device.device_type == DeviceType.VJoy else device.device_guid
    fires = action.exec_on_press if pressed else action.exec_on_release
    if VjoyAction.is_axis_action(mode) or mode == VjoyAction.VJoySetAxisStepped:
        yield key, axis, action.vjoy_axis_id, (False,)
    elif mode == VjoyAction.VJoyHatToButton:
        for position, control in action.hat_map.items():
            button_mode = action.hat_mode_map.get(position)
            if button_mode != ButtonOutputMode.NoOp:
                phases = {ButtonOutputMode.Press: (True,), ButtonOutputMode.Release: (False,)}.get(button_mode, (True, False))
                yield key, button, control, phases
    elif VjoyAction.is_hat_action(mode):
        yield key, hat, action.vjoy_hat_id, (False, True)
    elif VjoyAction.is_button_action(mode):
        if mode in (VjoyAction.VJoyButton, VjoyAction.VJoyButtonInverted):
            if pressed and not fires:
                return
            value = pressed != (mode == VjoyAction.VJoyButtonInverted)
            phases = (not value if not pressed and fires else value,)
        elif mode == VjoyAction.VJoyAxisToButton:
            phases = (False, True)
        elif not fires:
            return
        else:
            phases = {VjoyAction.VJoyButtonPress: (True,), VjoyAction.VJoyButtonRelease: (False,)}.get(mode, (True, False))
        yield key, button, action.vjoy_button_id, phases


def _virtual_outputs(action, pressed, resolve):
    return tuple((TriggerInput(input_type, control, device), phase)
                 for key, input_type, control, phases in _virtual_writes(action, pressed)
                 if input_type in _JOYSTICK_TYPES and control and (device := resolve(key))
                 for phase in phases)


def _cyclic_components(edges):
    """Iterative strongly connected components, including self-loops."""
    reverse = {source: set() for source in edges}
    for source, targets in edges.items():
        for target in targets:
            reverse.setdefault(target, set()).add(source)

    seen, finished = set(), []
    for start in edges:
        if start in seen:
            continue
        seen.add(start)
        stack = [(start, iter(edges[start]))]
        while stack:
            source, targets = stack[-1]
            target = next(targets, None)
            if target is None:
                finished.append(source)
                stack.pop()
            elif target not in seen:
                seen.add(target)
                stack.append((target, iter(edges.get(target, ()))))

    seen.clear()
    for start in reversed(finished):
        if start in seen:
            continue
        component = set()
        stack = [start]
        seen.add(start)
        while stack:
            source = stack.pop()
            component.add(source)
            new = reverse[source] - seen
            seen.update(new)
            stack.extend(new)
        if len(component) > 1 or start in edges.get(start, ()):
            yield component


def _input_label(key, pressed, item):
    if key.input_type == InputType.State:
        return f"State {item.key} ({'on' if pressed else 'off'})"
    label = f"{item.device_name} · {item.short_display_name}"
    if key.input_type == InputType.JoystickButton:
        label += f" ({'press' if pressed else 'release'})"
    return label


def find_trigger_loops(graph, profile, master_mode):
    """Return (runtime modes, involved inputs) groups from the built execution graph."""
    state_items = {_state_input(state.key): state for state in profile.state.getStates().values() if state.key}
    by_mode = defaultdict(dict)
    modeless = {}
    resolve_virtual_input = None
    for node in graph.descendants:
        if node.nodeType.name != "InputItem" or not node.input_item.containers:
            continue
        item = node.input_item
        source = _input_key(item)
        if source is None:
            continue
        actions = [child.action for child in node.descendants if child.nodeType.name == "Action"
                   and child.action is not None and child.action.enabled
                   and child.action.tag in ("trigger", "map_to_state", *_VIRTUAL_ACTIONS)]
        outputs = defaultdict(set)
        phases = (False,) if source.input_type == InputType.JoystickAxis else (False, True)
        for action in actions:
            if action.tag == "map_to_state" and action.mode != "none" and source.input_type != InputType.JoystickAxis:
                targets = [state.key for state in action.target_states() if not state.isExpression]
            else:
                targets = ()
            for pressed in phases:
                if action.tag == "trigger":
                    emitted = _joystick_outputs(action, source, pressed)
                elif action.tag == "map_to_state":
                    emitted = _state_outputs(action, source, pressed, state_items, targets)
                else:
                    if resolve_virtual_input is None:
                        resolve_virtual_input = _virtual_input_resolver(profile)
                    emitted = _virtual_outputs(action, pressed, resolve_virtual_input)
                if emitted:
                    outputs[(source, pressed)].update(emitted)
        mappings = modeless if source.input_type == InputType.State else by_mode[node.mode]
        mappings[source] = item, outputs

    dependencies = defaultdict(set)
    for target, state in state_items.items():
        for dependency in state.getDependencies():
            if dependency.key and (source := _state_input(dependency.key)) in state_items:
                for phase in (False, True):
                    dependencies[(source, phase)].update(((target, False), (target, True)))

    # Keep empty overrides only where the same input produces trigger edges
    # in another mode. This limits per-mode work to the relevant mappings.
    sources = {source for mappings in by_mode.values() for source, (_, outputs) in mappings.items() if outputs}
    if not (sources or dependencies or any(outputs for _, outputs in modeless.values())):
        return []
    by_mode = {mode: {source: mapping for source, mapping in mappings.items() if source in sources}
               for mode, mappings in by_mode.items()}
    groups = {}
    for mode in profile.get_modes():
        routes = {}
        seen_modes = {master_mode}
        routes.update(by_mode.get(master_mode, {}))
        lookup = mode
        while lookup and lookup not in seen_modes:
            seen_modes.add(lookup)
            for source, mapping in by_mode.get(lookup, {}).items():
                routes.setdefault(source, mapping)
            lookup = profile.get_parent_mode(lookup)
        routes.update(modeless)
        items = dict(state_items)
        edges = {origin: set(targets) for origin, targets in dependencies.items()}
        for source, (item, outputs) in routes.items():
            items[source] = item
            for origin, targets in outputs.items():
                edges.setdefault(origin, set()).update(targets)

        for component in _cyclic_components(edges):
            key = frozenset(component)
            if key not in groups:
                inputs = tuple(sorted((_input_label(source, phase, items[source]) for source, phase in component), key=str.casefold))
                groups[key] = [], inputs
            groups[key][0].append(mode)

    return sorted(((tuple(modes), inputs) for modes, inputs in groups.values()), key=lambda group: group)
