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

"""Read DirectInput interface paths and Windows container identities."""

import ctypes as c
from contextlib import contextmanager
from ctypes import wintypes as w
from functools import lru_cache
import sys
import uuid


@lru_cache(maxsize=None)
def _library(name):
    return c.WinDLL(name)


class _GUID(c.Structure):
    _fields_ = [("bytes", c.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        return cls((c.c_ubyte * 16).from_buffer_copy(uuid.UUID(str(value)).bytes_le))


class _PropertyHeader(c.Structure):
    _fields_ = [(name, w.DWORD) for name in ("size", "header_size", "object", "how")]


class _GuidAndPath(c.Structure):
    _fields_ = [("header", _PropertyHeader), ("class_guid", _GUID), ("path", w.WCHAR * 260)]


class _DeviceInstancePrefix(c.Structure):
    _fields_ = [("size", w.DWORD), ("instance_guid", _GUID)]


class _PropertyKey(c.Structure):
    _fields_ = [("guid", _GUID), ("pid", w.DWORD)]


def _method(pointer, index, *types):
    table = c.cast(pointer, c.POINTER(c.POINTER(c.c_void_p))).contents
    return c.WINFUNCTYPE(c.c_long, c.c_void_p, *types)(table[index])


def _interface_instance_id(path):
    cfg = _library("cfgmgr32.dll")
    interface_property = cfg.CM_Get_Device_Interface_PropertyW
    interface_property.argtypes = [w.LPCWSTR, c.POINTER(_PropertyKey), c.POINTER(w.ULONG), c.c_void_p,
                                  c.POINTER(w.ULONG), w.ULONG]
    interface_property.restype = w.ULONG
    instance_key = _PropertyKey(_GUID.parse("78c34fc8-104a-4aca-9ea4-524d52996e57"), 256)
    instance = c.create_unicode_buffer(1024)
    size, kind = w.ULONG(c.sizeof(instance)), w.ULONG()
    if interface_property(path, c.byref(instance_key), c.byref(kind), instance, c.byref(size), 0) != 0:
        return None
    return instance.value


def _find_devnode(instance, flags=0):
    cfg = _library("cfgmgr32.dll")
    locate = cfg.CM_Locate_DevNodeW
    locate.argtypes = [c.POINTER(w.ULONG), w.LPWSTR, w.ULONG]
    locate.restype = w.ULONG
    node = w.ULONG()
    if locate(c.byref(node), c.create_unicode_buffer(instance), flags) == 0:
        return node.value


def _container_id(path):
    """Resolve a device interface to its devnode's DEVPKEY_Device_ContainerId."""
    instance = _interface_instance_id(path)
    node = _find_devnode(instance) if instance else None
    if node is None:
        return None
    cfg = _library("cfgmgr32.dll")
    node_property = cfg.CM_Get_DevNode_PropertyW
    node_property.argtypes = [w.ULONG, c.POINTER(_PropertyKey), c.POINTER(w.ULONG), c.c_void_p,
                             c.POINTER(w.ULONG), w.ULONG]
    node_property.restype = w.ULONG
    container_key = _PropertyKey(_GUID.parse("8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c"), 2)
    container = _GUID()
    kind = w.ULONG()
    size = w.ULONG(c.sizeof(container))
    if node_property(node, c.byref(container_key), c.byref(kind), c.byref(container), c.byref(size), 0) != 0:
        return None
    return str(uuid.UUID(bytes_le=bytes(container.bytes))) if kind.value == 13 else None  # DEVPROP_TYPE_GUID


@contextmanager
def _direct_input():
    library = _library("dinput8.dll")
    create = library.DirectInput8Create
    create.argtypes = [w.HINSTANCE, w.DWORD, c.POINTER(_GUID), c.POINTER(c.c_void_p), c.c_void_p]
    create.restype = c.c_long
    kernel = _library("kernel32.dll")
    kernel.GetModuleHandleW.argtypes = [w.LPCWSTR]
    kernel.GetModuleHandleW.restype = w.HMODULE
    root = c.c_void_p()
    iid = _GUID.parse("bf798031-483a-4da2-aa99-5d64ed369700")
    result = create(kernel.GetModuleHandleW(None), 0x0800, c.byref(iid), c.byref(root), None)
    if result < 0 or not root:
        raise OSError(f"DirectInput8Create failed: 0x{result & 0xFFFFFFFF:08X}")
    try:
        yield root
    finally:
        _method(root, 2)(root)


def _device_interface(root, guid):
    device = c.c_void_p()
    result = _method(root, 3, c.POINTER(_GUID), c.POINTER(c.c_void_p), c.c_void_p)(
        root, c.byref(guid), c.byref(device), None)
    if result < 0 or not device:
        return ""
    try:
        prop = _GuidAndPath()
        prop.header = _PropertyHeader(c.sizeof(prop), c.sizeof(_PropertyHeader), 0, 0)
        # DIPROP_GUIDANDPATH is MAKEDIPROP(12), not an allocated GUID.
        result = _method(device, 5, c.c_void_p, c.c_void_p)(device, 12, c.byref(prop))
        return prop.path if result >= 0 else ""
    finally:
        _method(device, 2)(device)


def get_device_identities(device_guids):
    """Read identities without acquiring devices or changing their state.

    Keys are normalized instance GUIDs (32 lowercase hex digits). A failed
    per-device query is omitted, for example when a controller is unplugged.
    """
    device_guids = list(device_guids)
    if sys.platform != "win32" or not device_guids:
        return {}
    identities = {}
    with _direct_input() as root:
        for value in device_guids:
            if path := _device_interface(root, _GUID.parse(value)):
                identities[uuid.UUID(str(value)).hex] = dict(path=path, container_id=_container_id(path))
    return identities


def get_directinput_controller_paths():
    """Return HID paths of attached game controllers enumerated by DirectInput."""
    if sys.platform != "win32":
        return set()
    guids = []
    callback_type = c.WINFUNCTYPE(w.BOOL, c.POINTER(_DeviceInstancePrefix), c.c_void_p)

    @callback_type
    def collect(instance, _context):
        guids.append(bytes(instance.contents.instance_guid.bytes))
        return True  # DIENUM_CONTINUE

    with _direct_input() as root:
        enumerate_devices = _method(root, 4, w.DWORD, callback_type, c.c_void_p, w.DWORD)
        result = enumerate_devices(root, 4, collect, None, 1)  # DI8DEVCLASS_GAMECTRL, DIEDFL_ATTACHEDONLY
        if result < 0:
            raise OSError(f"DirectInput EnumDevices failed: 0x{result & 0xFFFFFFFF:08X}")
        return {path for value in guids if (path := _device_interface(root, _GUID.from_buffer_copy(value)))}


def get_device_ancestors(instance_path):
    """Return the parent PnP instance IDs for a Windows device."""
    if sys.platform != "win32" or not instance_path:
        return ()
    cfg = _library("cfgmgr32.dll")
    locate = cfg.CM_Locate_DevNodeW
    locate.argtypes = [c.POINTER(w.ULONG), w.LPWSTR, w.ULONG]
    locate.restype = w.ULONG
    get_parent = cfg.CM_Get_Parent
    get_parent.argtypes = [c.POINTER(w.ULONG), w.ULONG, w.ULONG]
    get_parent.restype = w.ULONG
    get_id = cfg.CM_Get_Device_IDW
    get_id.argtypes = [w.ULONG, w.LPWSTR, w.ULONG, w.ULONG]
    get_id.restype = w.ULONG
    node, parent = w.ULONG(), w.ULONG()
    if locate(c.byref(node), c.create_unicode_buffer(instance_path), 0) != 0:
        return ()
    ancestors = []
    buffer = c.create_unicode_buffer(1024)
    while get_parent(c.byref(parent), node, 0) == 0:
        if get_id(parent, buffer, len(buffer), 0) != 0:
            break
        ancestors.append(buffer.value)
        node.value = parent.value
    return tuple(ancestors)


def _interface_paths(class_id, flags=0):
    cfg = _library("cfgmgr32.dll")
    size = cfg.CM_Get_Device_Interface_List_SizeW
    size.argtypes = [c.POINTER(w.ULONG), c.POINTER(_GUID), w.LPCWSTR, w.ULONG]
    size.restype = w.ULONG
    read = cfg.CM_Get_Device_Interface_ListW
    read.argtypes = [c.POINTER(_GUID), w.LPCWSTR, w.LPWSTR, w.ULONG, w.ULONG]
    read.restype = w.ULONG
    guid, length = _GUID.parse(class_id), w.ULONG()
    for _ in range(3):
        result = size(c.byref(length), c.byref(guid), None, flags)
        if result:
            break
        buffer = c.create_unicode_buffer(length.value)
        result = read(c.byref(guid), None, buffer, length, flags)
        if result == 0:
            return tuple(filter(None, buffer[:].split("\0")))
        if result != 0x1A:  # CR_BUFFER_SMALL after a hotplug.
            break
    raise OSError(f"Could not enumerate Windows device interfaces (CONFIGRET 0x{result:02x}).")


def get_hid_interfaces():
    """Return HID instance IDs and metadata, even if access to the HID is denied."""
    hid_class = "4d1e55b2-f16f-11cf-88cb-001111000030"
    xusb_class = "ec87f1e3-c13b-4100-b5f7-8b84d54260cb"
    present = {path.casefold() for path in _interface_paths(hid_class)}
    xusb = {}
    for path in _interface_paths(xusb_class, flags=1):
        if instance := _interface_instance_id(path):
            xusb[instance.casefold()] = instance
    maestro_companions = {
        instance.rsplit("\\", 1)[-1]
        for path in _interface_paths(xusb_class)
        if (instance := (_interface_instance_id(path) or "").casefold()).startswith("swd\\hidmaestro\\hm_")
    }
    device_key = _GUID.parse("a45c254e-df1c-4efd-8020-67d146a850e0")
    bus_name = _PropertyKey(_GUID.parse("540b947e-8b40-45bc-a8a2-6a0b894cbda2"), 4)
    compatible_ids = _PropertyKey(device_key, 4)
    name_keys = (_PropertyKey(device_key, 14), bus_name, _PropertyKey(device_key, 2))
    class_key = _PropertyKey(device_key, 10)
    xbox_classes = {uuid.UUID(value).bytes_le for value in (
        "d61ca365-5af4-4486-998b-9db4734c6ca3", "05f5cfe2-4733-4950-a6bb-07aad01a3a84",
    )}
    prop = _library("cfgmgr32.dll").CM_Get_DevNode_PropertyW
    prop.argtypes = [w.ULONG, c.POINTER(_PropertyKey), c.POINTER(w.ULONG), c.c_void_p, c.POINTER(w.ULONG), w.ULONG]
    prop.restype = w.ULONG

    def read(node, key, expected):
        buffer = c.create_unicode_buffer(2048)
        kind, size = w.ULONG(), w.ULONG(c.sizeof(buffer))
        if prop(node, c.byref(key), c.byref(kind), buffer, c.byref(size), 0) == 0 and kind.value == expected:
            return buffer[:size.value // c.sizeof(w.WCHAR)].rstrip("\0")
        return ""

    for path in _interface_paths(hid_class, flags=1):
        instance = _interface_instance_id(path)
        if not instance:
            continue
        connected = path.casefold() in present
        node = _find_devnode(instance, flags=0 if connected else 1)
        if node is None:
            continue
        ids = read(node, compatible_ids, 0x2012).upper().split("\0")
        gaming = any(hid_id in ids for hid_id in ("HID_DEVICE_SYSTEM_GAME", "HID_DEVICE_UP:0001_U:0004", "HID_DEVICE_UP:0001_U:0005"))
        name = next((name for key in name_keys if (name := read(node, key, 0x12))), instance)
        ancestors = get_device_ancestors(instance) if connected else ()
        alias = next((xusb[parent.casefold()] for parent in ancestors if parent.casefold() in xusb), "")
        gaming = gaming or instance.casefold() in xusb
        if gaming and not alias:
            # Xbox One can expose XInput through its Xbox composite setup class.
            for parent in ancestors:
                parent_node = _find_devnode(parent)
                value = _GUID()
                kind, size = w.ULONG(), w.ULONG(c.sizeof(value))
                if parent_node is not None and prop(parent_node, c.byref(class_key), c.byref(kind), c.byref(value), c.byref(size), 0) == 0:
                    if kind.value == 13 and bytes(value.bytes) in xbox_classes:
                        alias = parent
                        break
        alias = alias or xusb.get(instance.casefold(), "")
        # The Maestro XUSB companion is a separate devnode. Its instance
        # token matches the HID controller's parent, rather than its VID/PID.
        companion = any(parent.rsplit("\\", 1)[-1].casefold() in maestro_companions for parent in ancestors)
        yield instance, path, connected, name, gaming, alias, ancestors, bool(alias) or companion
