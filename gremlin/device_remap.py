# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import logging

"""Profile device identity replacement """

from copy import deepcopy
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from lxml import etree


syslog = logging.getLogger("system")


_GUID_HEX = re.compile(r"[0-9a-fA-F]{32}\Z")


def guid_key(value):
    """Normalize GUIDs without raising exceptions for ordinary XML values.

    This is called for every attribute during remapping. Caught UUID parsing
    errors still trigger debugger exception hooks, making UI validation slow.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value.hex
    text = str(value).strip()
    if text.startswith("urn:uuid:"):
        text = text[9:]
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    if len(text) not in (32, 36):
        return None
    text = text.replace("-", "")
    return text.lower() if _GUID_HEX.fullmatch(text) else None


def _vjoy_source_id(value, sources):
    """Read a numeric request or known GUID without exception-based probing."""
    if isinstance(value, int):
        return value
    if value is None:
        return None
    text = str(value).strip()
    digits = text[1:] if text.startswith(("+", "-")) else text
    if digits.isdecimal():
        return int(text)
    return sources.get(guid_key(value))


def device_name_key(name):
    words = re.findall(r"[a-z0-9]+", name.casefold())
    return tuple({"l": "left", "r": "right"}.get(word, word) for word in words)


def suggest_target(source, targets):
    """Only propose a unique name match; ambiguous devices require a choice."""
    matches = [device for device in targets if device_name_key(device.name) == device_name_key(source.get("name", ""))]
    return matches[0] if len(matches) == 1 else None


def remap_profile_devices(root, replacements):
    """Return a copy with simultaneous GUID replacements, or reject conflicts.

    replacements maps old GUIDs to (new GUID, new device name). Existing empty
    target nodes may be replaced, but existing mappings are never overwritten.
    """
    changes = {}
    for old, (new, name) in replacements.items():
        old_key, new_key = guid_key(old), guid_key(new)
        if old_key is None or new_key is None:
            raise ValueError("A device has an invalid GUID.")
        if old_key != new_key:
            changes[old_key] = (new_key, name)
    if not changes:
        raise ValueError("Select at least one device with a different target GUID.")
    destinations = [new for new, _ in changes.values()]
    if len(destinations) != len(set(destinations)):
        raise ValueError("Choose a different target for each selected device.")
    result = deepcopy(root)
    devices = result.findall("./devices/device")
    sources = {guid_key(node.get("device-guid")) for node in devices}
    if not changes.keys() <= sources:
        raise ValueError("A selected source device is no longer in the profile.")
    for node in devices:
        key = guid_key(node.get("device-guid"))
        if key in destinations and key not in changes:
            if node.findall(".//container"):
                raise ValueError(
                    f'Target device "{node.get("name")}" already has mappings in the profile. Select another target.'
                )
            node.getparent().remove(node)
    for node in result.iter():
        if not isinstance(node.tag, str):
            continue
        original_key = guid_key(node.get("device-guid"))
        if node.tag == "device" and original_key in changes and node.getparent().tag == "devices":
            node.set("name", changes[original_key][1])
        for attribute, value in list(node.attrib.items()):
            key = guid_key(value)
            if key in changes:
                node.set(attribute, changes[key][0])
        key = guid_key(node.text)
        if key in changes:
            node.text = changes[key][0]
    return result


def vjoy_references(root, *, include_filter_guids=False):
    """Return native vJoy IDs and saved GUIDs needed by profile failover.

    A macro's device GUID takes precedence over its legacy numeric slot.
    Maestro output keys must never be interpreted as native vJoy references.
    """
    references = {}
    sources = {}

    def add(value, guid=None):
        index = _vjoy_source_id(value, sources)
        if index is not None and 1 <= index <= 16:
            references.setdefault(index, None)
            if guid:
                references[index] = guid

    for node in root.xpath("./devices/device | ./devices/vjoy-device | ./vjoy-devices/vjoy-device"):
        kind = node.get("type", "").casefold()
        if node.tag != "vjoy-device" and kind != "vjoy" and not (
            not kind and node.get("name", "").casefold().startswith("vjoy")
        ):
            continue
        value = node.get("vjoy-id") or node.get("virtual-id")
        if value is None or value == "-1":
            match = re.search(r"\((\d+)\)", node.get("name", ""))
            value = match.group(1) if match else None
        guid = node.get("device-guid") or node.get("device")
        add(value, guid)
        if guid_key(guid) is not None:
            try:
                sources[guid_key(guid)] = int(value)
            except (ValueError, TypeError):
                pass

    # Visibility metadata can identify native GUID keys without itself
    # requiring an output device or activating failover.
    for node in root.findall("./settings/input-filter/device"):
        if node.get("name", "").casefold().startswith("vjoy"):
            match = re.search(r"\((\d+)\)", node.get("name", ""))
            key = guid_key(node.get("device"))
            if match and key is not None:
                sources.setdefault(key, int(match.group(1)))

    for node in root.iter():
        if node.tag == "vjoyremap" and node.get("device-type", "vjoy").casefold() in ("", "vjoy"):
            value = node.get("virtual-id", "-1")
            add(node.get("vjoy", "1") if value == "-1" else value)
        elif node.tag == "remap":
            add(node.get("vjoy", "1"))
        elif node.tag == "split-axis":
            for attribute in ("device-low-vjoy-id", "device-high-vjoy-id"):
                add(node.get(attribute, "1"))
        elif node.tag == "vjoy" and node.get("vjoy-id") is not None:
            add(node.get("device-guid") or node.get("vjoy-id"))
        elif node.tag == "variable" and node.get("type") == "VirtualInput":
            add(node.get("vjoy-id"))
    for node in root.findall("./settings/vjoy-input"):
        add(node.get("guid") or node.get("id"))
    for node in root.findall("./settings/vjoy"):
        add(node.get("id"))
    if include_filter_guids:
        for guid, index in sources.items():
            if index in references and not references[index]:
                references[index] = guid
    return references


def remap_vjoy_outputs(root, devices, replacements=None, *, source_guids=None):
    """Copy output references to their stable gex-N Maestro equivalents.

    Return the new XML and a description of each changed vJoy device. Maestro
    slots are used only by vjoyremap; legacy output keys use the target GUID.
    Missing or ambiguous equivalents reject the entire operation. When
    replacements is supplied, only its vJoy IDs are changed, using the chosen
    Maestro devices rather than the automatic gex-N equivalents.
    """
    result = deepcopy(root)
    devices = list(devices)
    targets = {}
    source_ids = dict(source_guids or {})
    for device in devices:
        kind = getattr(getattr(device, "device_type", None), "name", "").casefold()
        if kind == "vjoy":
            key = guid_key(device.device_guid)
            if key is not None:
                source_ids[key] = device.vjoy_id
        index = maestro_output_id(device)
        if index is not None:
            targets.setdefault(index, []).append(device)

    if replacements is not None:
        available = {guid_key(device.device_guid): device for device in devices if is_maestro_output(device)}
        selected = {}
        for device_id, target in replacements.items():
            key = guid_key(target.device_guid)
            if key not in available:
                raise ValueError(f'Choose a connected gex output for vJoy {device_id}.')
            selected[int(device_id)] = [available[key]]
        targets = selected

    # Saved declarations remain authoritative when the vJoy driver is absent.
    declarations = []
    for node in result.xpath("./devices/device | ./devices/vjoy-device | ./vjoy-devices/vjoy-device"):
        kind = node.get("type", "").casefold()
        if node.tag != "vjoy-device" and kind != "vjoy" and not (
            not kind and node.get("name", "").casefold().startswith("vjoy")
        ):
            continue
        value = node.get("vjoy-id") or node.get("virtual-id")
        if value is None or value == "-1":
            match = re.search(r"\((\d+)\)", node.get("name", ""))
            value = match.group(1) if match else None
        try:
            device_id = int(value)
        except (ValueError, TypeError):
            raise ValueError("Cannot determine the vJoy ID of a saved device.")
        key = guid_key(node.get("device-guid"))
        if key is not None:
            source_ids[key] = device_id
        declarations.append((node, device_id))

    # Visibility filters can identify old GUIDs, but are not device/output
    # dependencies: unused filters must not require a connected equivalent.
    for node in result.findall("./settings/input-filter/device"):
        if node.get("name", "").casefold().startswith("vjoy"):
            match = re.search(r"\((\d+)\)", node.get("name", ""))
            key = guid_key(node.get("device"))
            if match and key is not None:
                source_ids.setdefault(key, int(match.group(1)))

    changed = {}

    def target_for(value):
        device_id = _vjoy_source_id(value, source_ids)
        if device_id is None or (replacements is not None and device_id not in replacements):
            return None  # Already another provider, or an unchecked output.
        matches = targets.get(device_id, [])
        if len(matches) != 1:
            reason = "No connected" if not matches else "More than one connected"
            raise ValueError(f"{reason} Maestro equivalent for vJoy {device_id} (gex-{device_id}).")
        target = matches[0]
        changed[device_id] = f"vJoy {device_id} -> {target.name}"
        return target

    # Convert provider metadata as well as actions, so reloading does not
    # reconstruct synthetic vJoy failover devices from stale declarations.
    guid_changes = {}
    for node, device_id in declarations:
        target = target_for(device_id)
        if target is None:
            continue
        old_key = guid_key(node.get("device-guid"))
        if old_key is not None:
            guid_changes[old_key] = str(target.device_guid)
        node.tag = "device"
        node.set("device-guid", str(target.device_guid))
        node.set("name", target.name)
        node.set("type", "maestro")
        node.set("virtual-id", str(target.virtual_id))
        node.attrib.pop("vjoy-id", None)
        if node.getparent().tag != "devices":
            parent = result.find("devices")
            if parent is None:
                parent = etree.SubElement(result, "devices")
            parent.append(node)

    for node in result.findall("./settings/vjoy-input"):
        target = target_for(node.get("guid") or node.get("id"))
        if target is not None:
            node.tag = "maestro-input"
            node.set("guid", str(target.device_guid))
            node.attrib.pop("id", None)

    for node in result.iter():
        if not isinstance(node.tag, str):
            continue
        for attribute, value in list(node.attrib.items()):
            key = guid_key(value)
            if key in source_ids and key not in guid_changes and source_ids[key] in targets:
                guid_changes[key] = str(target_for(value).device_guid)
            if key in guid_changes:
                node.set(attribute, guid_changes[key])
                if node.tag == "device" and node.getparent().tag == "input-filter":
                    node.set("name", targets[source_ids[key]][0].name)

    # Legacy initialization settings only accept numeric vJoy IDs. Move them
    # into the provider-independent startup state instead of losing values.
    for node in result.findall("./settings/vjoy"):
        target = target_for(node.get("id"))
        if target is None:
            continue
        start = result.find("start")
        if start is None:
            start = etree.SubElement(result, "start")
        start_devices = start.find("devices")
        if start_devices is None:
            start_devices = etree.SubElement(start, "devices")
        startup = next((item for item in start_devices if guid_key(item.get("device-guid")) == guid_key(target.device_guid)), None)
        if startup is None:
            startup = etree.SubElement(start_devices, "device", {"device-guid": str(target.device_guid)})
        for axis in node.findall("axis"):
            existing = next((item for item in startup.findall("axis") if item.get("id") == axis.get("id")), None)
            if existing is None:
                startup.append(deepcopy(axis))
        node.getparent().remove(node)

    for node in result.iter():
        if not isinstance(node.tag, str):
            continue
        if node.tag == "vjoyremap":
            if node.get("device-type", "vjoy").casefold() not in ("", "vjoy"):
                continue
            output_id = node.get("virtual-id", "-1")
            if output_id == "-1":
                output_id = node.get("vjoy", "1")
            target = target_for(output_id)
            if target is not None:
                node.set("device-type", "Maestro")
                node.set("virtual-id", str(target.virtual_id))
                node.attrib.pop("vjoy", None)
        elif node.tag == "remap":
            target = target_for(node.get("vjoy", "1"))
            if target is not None:
                node.set("vjoy", str(target.device_guid))
        elif node.tag == "split-axis":
            for attribute in ("device-low-vjoy-id", "device-high-vjoy-id"):
                target = target_for(node.get(attribute, "1"))
                if target is not None:
                    node.set(attribute, str(target.device_guid))
        elif node.tag == "variable" and node.get("type") == "VirtualInput" and node.get("vjoy-id") is not None:
            target = target_for(node.get("vjoy-id"))
            if target is not None:
                node.set("vjoy-id", str(target.device_guid))
        elif node.tag == "vjoy" and node.get("vjoy-id") is not None:
            # Macro actions carry an optional GUID; merge-axis outputs use a key.
            if node.get("input-type") is not None:
                target = target_for(node.get("device-guid") or node.get("vjoy-id"))
                if target is not None:
                    node.set("device-guid", str(target.device_guid))
                    node.set("vjoy-id", str(target.virtual_id))
            else:
                target = target_for(node.get("vjoy-id"))
                if target is not None:
                    node.set("vjoy-id", str(target.device_guid))
    _merge_output_declarations(result, {guid_key(value) for value in guid_changes.values()})
    remaining = vjoy_references(result)
    if replacements is not None:
        remaining = {key: value for key, value in remaining.items() if key in replacements}
    if remaining:
        raise ValueError(f"Unconverted vJoy references remain: {sorted(remaining)}")
    return result, [changed[key] for key in sorted(changed)]



def _merge_output_declarations(root, destination_guids):
    # An empty target declaration may already have been saved by enumeration.
    # Reject mapped collisions rather than silently overwriting either device.
    by_guid = {}
    for node in root.xpath("./devices/device | ./devices/vjoy-device | ./vjoy-devices/vjoy-device"):
        key = guid_key(node.get("device-guid"))
        if key not in destination_guids:
            continue
        previous = by_guid.get(key)
        if previous is not None:
            if previous.findall(".//container") and node.findall(".//container"):
                raise ValueError(f'Target device "{node.get("name")}" already has mappings in the profile.')
            if node.findall(".//container"):
                previous.getparent().remove(previous)
            else:
                node.getparent().remove(node)
                continue
        by_guid[key] = node


def is_maestro_output(device):
    """Whether the device can be used as a direct Maestro output."""
    kind = getattr(getattr(device, "device_type", None), "name", "").casefold()
    return (kind == "maestro" and device.connected and not getattr(device, "disabled", False)
            and device.virtual_id >= 0)


def native_vjoy_output_id(device):
    """Return the vJoy request ID for a connected native output."""
    kind = getattr(getattr(device, "device_type", None), "name", "").casefold()
    if (kind == "vjoy" and device.connected and not getattr(device, "disabled", False)
            and not device.data.get("failover", False) and 1 <= device.vjoy_id <= 16):
        return device.vjoy_id
    return None


def maestro_output_id(device, *, require_hid_order=True):
    """Return the canonical gex number for a vJoy counterpart."""
    if not is_maestro_output(device) or getattr(device, "is_gamepad", False):
        return None
    data = device.data
    key = data.get("maestro_key")
    name = str(key).rsplit("/", 1)[-1] if key else device.name
    match = re.fullmatch(r"gex-(1[0-6]|[1-9])", name.casefold())
    if match and (not require_hid_order or data.get("maestro_hid_order_valid") is not False):
        return int(match.group(1))
    return None


def output_device_sources(root, devices, *, saved_root=None):
    """Describe saved output identities once per device for the remapping grid."""
    devices = list(devices)
    input_guids = {guid_key(node.get("device-guid")) for node in root.findall("./devices/device")
                   if node.get("type", "").casefold() == "joystick"}
    saved_vjoy = vjoy_references(saved_root, include_filter_guids=True) if saved_root is not None else {}
    sources = {
        index: {"key": index, "name": f"vJoy {index}", "device-guid": saved_vjoy.get(index) or guid or "",
                "provider": "vjoy"}
        for index, guid in vjoy_references(root, include_filter_guids=True).items()
    }
    maestros = {}
    legacy_guids = {}
    slots = {}
    native = {}
    for device in devices:
        kind = getattr(getattr(device, "device_type", None), "name", "").casefold()
        key = guid_key(device.device_guid)
        if kind == "maestro":
            source = {"key": key, "name": device.name, "device-guid": str(device.device_guid),
                      "virtual-id": str(device.virtual_id), "provider": "maestro"}
            maestros[key] = source
            service_key = device.data.get("maestro_key")
            if service_key:
                legacy_guids[uuid.uuid5(uuid.NAMESPACE_URL, service_key).hex] = source
            slots.setdefault(str(device.virtual_id), source)
        elif kind == "vjoy":
            native[key] = device.vjoy_id
    for index, guid in saved_vjoy.items():
        if guid_key(guid) is not None:
            native.setdefault(guid_key(guid), index)

    live_guids = {guid_key(device.device_guid) for device in devices if is_maestro_output(device)}
    for document in (root, saved_root):
        if document is None:
            continue
        for node in document.findall("./devices/device"):
            key = guid_key(node.get("device-guid"))
            if node.get("type", "").casefold() != "maestro" or key is None:
                continue
            source = {"key": key, "name": node.get("name", "Maestro"), "device-guid": node.get("device-guid"),
                      "virtual-id": node.get("virtual-id", "-1"), "provider": "maestro"}
            maestros.setdefault(key, source)
            slot = source["virtual-id"]
            if slot not in slots or (key not in live_guids and slots[slot]["key"] in live_guids):
                slots[slot] = source

    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        if node.tag == "vjoyremap" and node.get("device-type", "").casefold() == "maestro":
            slot = node.get("virtual-id", "-1")
            saved_guid = guid_key(slot)
            source = maestros.get(saved_guid) if saved_guid else slots.get(slot)
            source = source or {"key": saved_guid or f"maestro-slot:{slot}", "name": f"Maestro {slot}",
                               "device-guid": slot if saved_guid else "", "virtual-id": slot, "provider": "maestro"}
            sources[source["key"]] = source
        values = []
        if node.tag == "remap":
            values.append(node.get("vjoy"))
        elif node.tag == "split-axis":
            values.extend(node.get(attribute) for attribute in ("device-low-vjoy-id", "device-high-vjoy-id"))
        elif node.tag == "vjoy" or (node.tag == "variable" and node.get("type") == "VirtualInput"):
            values.append(node.get("device-guid") or node.get("vjoy-id"))
        elif node.tag == "device" and node.getparent().tag == "devices" and node.getparent().getparent().tag == "start":
            values.append(node.get("device-guid"))
        for value in values:
            key = guid_key(value)
            if node.tag == "device" and key in input_guids:
                # Input remapping already handles startup references to a
                # declared physical input; don't add a spurious output row.
                continue
            if key in maestros:
                sources[key] = maestros[key]
            elif key in native:
                index = native[key]
                sources.setdefault(index, {"key": index, "name": f"vJoy {index}", "device-guid": value, "provider": "vjoy"})
            elif key is not None:
                # An action/startup reference can outlive its device declaration
                # or a temporary GEX GUID. It still needs an editable output row.
                sources.setdefault(key, {"key": key, "name": "Unavailable output", "device-guid": value,
                                         "provider": "maestro"})
    for source in sources.values():
        previous = legacy_guids.get(guid_key(source["device-guid"]))
        if previous and source["key"] != previous["key"]:
            source["suggested-guid"] = previous["device-guid"]
            if source["name"] == "Unavailable output":
                source["name"] = previous["name"] + " (previous GUID)"
    return sorted(sources.values(), key=lambda source: (source["provider"], source["name"].casefold(), str(source["key"])))


def remap_output_devices(root, devices, replacements, *, saved_root=None):
    """Apply checked output rows simultaneously, preserving unchecked outputs."""
    devices = list(devices)
    sources = {source["key"]: source for source in output_device_sources(root, devices, saved_root=saved_root)}
    if not replacements.keys() <= sources.keys():
        raise ValueError("A selected output device is no longer in the profile.")
    available = {guid_key(device.device_guid) for device in devices}
    destinations = {}
    for source, target in replacements.items():
        key = guid_key(target.device_guid)
        if key not in available or not (is_maestro_output(target) or native_vjoy_output_id(target) == source):
            raise ValueError("Choose a connected output device.")
        if key in destinations:
            previous_name = sources[destinations[key]]["name"]
            raise ValueError(
                f'"{previous_name}" and "{sources[source]["name"]}" both target "{target.name}". '
                "Deselect one of these rows or choose another target."
            )
        destinations[key] = source
    result = deepcopy(root)
    guid_changes, slot_changes, descriptions = {}, {}, []
    for key, target in replacements.items():
        source = sources[key]
        if source["provider"] == "vjoy" and is_maestro_output(target):
            continue
        old_guid = guid_key(source["device-guid"])
        if old_guid == guid_key(target.device_guid):
            raise ValueError(f'Choose a different output device for "{source["name"]}" or deselect it.')
        if old_guid is not None:
            guid_changes[old_guid] = target
        if source["provider"] == "maestro" and source.get("virtual-id") is not None:
            slot_changes[source["virtual-id"]] = target
        descriptions.append(f'{source["name"]} -> {target.name}')
    if guid_changes or slot_changes:
        for node in result.iter():
            if not isinstance(node.tag, str):
                continue
            original = guid_key(node.get("device-guid") or node.get("device"))
            if node.tag == "vjoyremap" and node.get("device-type", "").casefold() == "maestro":
                target = slot_changes.get(node.get("virtual-id"))
                if target is not None:
                    node.set("virtual-id", str(target.virtual_id))
            for attribute, value in list(node.attrib.items()):
                target = guid_changes.get(guid_key(value))
                if target is not None:
                    node.set(attribute, str(target.device_guid))
            target = guid_changes.get(original)
            if target is not None:
                if node.tag in ("device", "vjoy-device"):
                    node.set("name", target.name)
                    if node.get("type", "").casefold() == "maestro":
                        node.set("virtual-id", str(target.virtual_id))
                elif node.tag == "vjoy" and node.get("input-type") is not None:
                    node.set("vjoy-id", str(target.virtual_id))
        _merge_output_declarations(result, {guid_key(target.device_guid) for target in guid_changes.values()})
    native = {key: target for key, target in replacements.items() if isinstance(key, int) and is_maestro_output(target)}
    if native:
        source_guids = {guid_key(sources[key]["device-guid"]): key for key in native}
        source_guids.pop(None, None)
        result, changes = remap_vjoy_outputs(result, devices, native, source_guids=source_guids)
        descriptions.extend(changes)
    return result, descriptions


def write_remapped_profile(filename, root):
    """Back up the saved profile and atomically replace it with the new XML."""
    payload = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="utf-8")
    path = Path(filename)
    backup = path.with_name(f"{path.stem}.guid-remap-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.xml")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copy2(path, backup)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return backup
