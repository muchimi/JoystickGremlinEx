"""Match bridge identities to the unmodified Windows HIDAPI enumeration."""

import hashlib
import re


def joystick_number(device_id):
    match = re.fullmatch(r"gex-([1-9][0-9]*)", str(device_id))
    return int(match[1]) if match and int(match[1]) <= 256 else None


def _path(value):
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")


def instance_token_for_key(key):
    """SDK identity for older bridges that supplied a key but omitted its token."""
    digest = hashlib.sha256(("HIDMaestro.DeviceIdentity.v1\n" + key.strip()).encode("utf-8")).digest()
    return "HM_" + digest[:8].hex().upper()


def matches_instance(row, token):
    """Match HID and XUSB presentations of the same SDK instance identity."""
    path = _path(row.get("path")).casefold()
    token = token or ""
    if not re.fullmatch(r"HM_[0-9A-Fa-f]{16}", token):
        return False
    # The SDK gives the HID device and XUSB companion the same container.
    token_hash = token[3:].casefold()
    container = f"48494430-4d41-4553-{token_hash[:4]}-{token_hash[4:]}"
    observed_container = str(row.get("container_id") or "").strip("{}").casefold()
    if observed_container and observed_container != "00000000-0000-0000-0000-000000000000":
        return observed_container == container
    if token.casefold() in path:
        return True
    # HID children carry the parent's hash, not necessarily its HM_ token.
    # The SDK may use counters 1..3 after an older child's removal was vetoed.
    prefix_hash = format(int(token[3:11], 16), "x")
    return re.search(r"(?:#|\\)1&" + prefix_hash + r"&[0-3](?:&|#|\\|$)", path) is not None


def inspect_hid_order(devices, hid_rows):
    """Keep the observed scan order; never sort rows to manufacture a pass.

    Canonical GEX joystick IDs are inspected in numeric order. Only IDs 1..16
    are eligible for vJoy failover. Other
    Maestro clients, physical controllers and gamepads are separate identities.
    Multiple HID collections of one controller count as one device.
    """
    expected = {
        device["id"]: device for device in devices
        if joystick_number(device.get("id")) is not None
    }
    ordered_ids = []
    matches = {}
    ambiguous = []
    for hid_index, row in enumerate(hid_rows):
        if row.get("usage_page") != 1 or row.get("usage") not in (4, 5):
            continue
        candidates = [device_id for device_id, device in expected.items() if matches_instance(row, device.get("instanceToken"))]
        if len(candidates) > 1:
            ambiguous.append(_path(row.get("path")))
            continue
        if not candidates or candidates[0] in matches:
            continue
        device_id = candidates[0]
        ordered_ids.append(device_id)
        matches[device_id] = dict(
            path=_path(row.get("path")), hid_index=hid_index, windows_order=len(ordered_ids),
            product_string=row.get("product_string"),
        )
    # Only relative GEX order matters. Other controllers may occur between GEX
    # devices, and inactive lower numbered IDs do not renumber the remaining IDs.
    expected_order = sorted(expected, key=joystick_number)
    missing = [device_id for device_id in expected_order if device_id not in matches]
    return dict(
        devices=matches, order=ordered_ids, expected_order=expected_order, missing=missing,
        ambiguous=ambiguous,
        verified=bool(expected) and not missing and not ambiguous and ordered_ids == expected_order,
        mismatch=bool(ordered_ids) and ordered_ids != sorted(ordered_ids, key=joystick_number),
    )
