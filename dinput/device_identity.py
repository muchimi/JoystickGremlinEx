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


class _PropertyKey(c.Structure):
    _fields_ = [("guid", _GUID), ("pid", w.DWORD)]


def _method(pointer, index, *types):
    table = c.cast(pointer, c.POINTER(c.POINTER(c.c_void_p))).contents
    return c.WINFUNCTYPE(c.c_long, c.c_void_p, *types)(table[index])


def _container_id(path):
    """Resolve a device interface to its devnode's DEVPKEY_Device_ContainerId."""
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
    locate = cfg.CM_Locate_DevNodeW
    locate.argtypes = [c.POINTER(w.ULONG), w.LPWSTR, w.ULONG]
    locate.restype = w.ULONG
    node = w.ULONG()
    if locate(c.byref(node), instance, 0) != 0:
        return None
    node_property = cfg.CM_Get_DevNode_PropertyW
    node_property.argtypes = [w.ULONG, c.POINTER(_PropertyKey), c.POINTER(w.ULONG), c.c_void_p,
                             c.POINTER(w.ULONG), w.ULONG]
    node_property.restype = w.ULONG
    container_key = _PropertyKey(_GUID.parse("8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c"), 2)
    container = _GUID()
    size = w.ULONG(c.sizeof(container))
    if node_property(node, c.byref(container_key), c.byref(kind), c.byref(container), c.byref(size), 0) != 0:
        return None
    return str(uuid.UUID(bytes_le=bytes(container.bytes))) if kind.value == 13 else None  # DEVPROP_TYPE_GUID


def get_device_identities(device_guids):
    """Read identities without acquiring devices or changing their state.

    Keys are normalized instance GUIDs (32 lowercase hex digits). A failed
    per-device query is omitted, for example when a controller is unplugged.
    """
    device_guids = list(device_guids)
    if sys.platform != "win32" or not device_guids:
        return {}
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
    identities = {}
    try:
        for value in device_guids:
            guid = _GUID.parse(value)
            device = c.c_void_p()
            result = _method(root, 3, c.POINTER(_GUID), c.POINTER(c.c_void_p), c.c_void_p)(
                root, c.byref(guid), c.byref(device), None)
            if result < 0 or not device:
                continue
            try:
                prop = _GuidAndPath()
                prop.header = _PropertyHeader(c.sizeof(prop), c.sizeof(_PropertyHeader), 0, 0)
                # DIPROP_GUIDANDPATH is MAKEDIPROP(12), not an allocated GUID.
                result = _method(device, 5, c.c_void_p, c.c_void_p)(device, 12, c.byref(prop))
                if result >= 0 and prop.path:
                    identities[uuid.UUID(str(value)).hex] = dict(path=prop.path, container_id=_container_id(prop.path))
            finally:
                _method(device, 2)(device)
    finally:
        _method(root, 2)(root)
    return identities
