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

"""Find live profile mappings that depend on Loopback inputs."""

from collections import defaultdict

from gremlin import shared_state, util
from gremlin.types import VjoyAction
from gremlin.ui.joystick_device import BaseJoystickCondition

from . import AXIS, BUTTON


def find_usage(profile, keys):
    """List references to the requested controls across all profile modes."""
    keys = set(keys)
    usage = defaultdict(list)
    device_guid = profile.loopback.device.device_guid

    for source, item, container, action_set, action in profile._iter_mode_mappings():
        owner = container if action_set is None else action
        references = []
        if action_set is None and source is item and item.device_guid == device_guid:
            references.append(((item.input_type, item.input_id), "Input mapping"))

        activation = owner.activation_condition
        for condition in activation.conditions if activation else ():
            if isinstance(condition, BaseJoystickCondition) and condition.device_guid == device_guid:
                references.append(((condition.input_type, condition.input_id), "Joystick condition"))

        if action is not None:
            references.extend(_action_references(action, device_guid))
        references = [(key, detail) for key, detail in references if key in keys]
        if not references:
            continue

        location = f"{source.display_name} (mode {shared_state.translateMode(source.profile_mode) or 'None'})"
        mapping = f"{location} — {container.name}"
        if action is not None:
            mapping = f"{mapping} / {action.name}"
        for key, detail in references:
            usage[key].append(f"{mapping} — {detail}")

    device = profile.getDeviceNode(device_guid)
    if device:
        for kind, index in keys:
            for mode in device.modes.values():
                item = mode.getInputItem(kind, index)
                if item is not None and item.curve_data is not None:
                    usage[kind, index].append(f"{item.display_name} (mode {shared_state.translateMode(mode.name)}) — Axis curve")

    for merge in profile.merge_axes:
        for end in ("lower", "upper"):
            source = merge.get(end)
            if source and source["device_guid"] == device_guid:
                key = (AXIS, source["axis_id"])
                if key in keys:
                    usage[key].append(f"Merged axis mapping (mode {shared_state.translateMode(merge['mode'])}) — {end.title()} source")

    return {key: sorted(locations, key=str.casefold) for key, locations in usage.items()}


def _action_references(action, device_guid):
    if action.tag == "trigger" and util.normalize_guid(action.device_id) == str(device_guid):
        yield (action.input_type, action.input_id), "Trigger target"

    if action.tag != "vjoyremap":
        return

    mode = action.action_mode
    if action.virtual_device_guid == device_guid:
        if mode == VjoyAction.VJoyHatToButton:
            for direction, index in action.hat_map.items():
                yield (BUTTON, index), f"Hat direction {direction}"
        elif mode == VjoyAction.VJoySetAxisStepped or VjoyAction.is_axis_action(mode):
            yield (AXIS, action.vjoy_input_id), "Virtual Remap target"
        elif VjoyAction.is_button_action(mode):
            yield (BUTTON, action.vjoy_input_id), "Virtual Remap target"

    if action.stepped_device_guid == device_guid:
        yield (action.stepped_input_type, action.stepped_input_id), "Secondary input"
    for source in action.merge_data:
        if source.device_guid == device_guid:
            yield (AXIS, source.input_id), "Merged axis source"
