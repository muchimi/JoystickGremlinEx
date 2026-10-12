# -*- coding: utf-8; -*-

# Based on original Joystick Gremlin work by Lionel Ott and other contributors - GremlinEx is (C) EMCS 2026
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

"""Native crash capture that does not re-enter Python.

The fault can happen inside the garbage collector. A Python vectored handler
would allocate while the collector is running. This module installs a
machine-code unhandled-exception filter that writes native-crash.txt and
native-crash.dmp, then forwards to the previous filter.
"""

from __future__ import annotations

import ctypes
import os
import struct
import sys
from ctypes import wintypes

_STATE: dict = {}

# Data block. The filter addresses it with r12. Offsets are fixed.
OFF_FLAG = 0
OFF_PID = 4
OFF_PROCESS = 8
OFF_DUMP = 16
OFF_TEXTH = 24
OFF_DUMPFN = 32
OFF_GETTID = 40
OFF_WRITE = 48
OFF_GETMOD = 56
OFF_GETNAME = 64
OFF_PREV = 72
OFF_FLUSH = 80
OFF_DUMPTYPE = 88
OFF_WRITTEN = 92
OFF_HMOD = 96
OFF_SCRATCH = 104
OFF_POS = 136  # write cursor. The formatter uses OFF_SCRATCH, so this must stay separate.
OFF_EP = 144
OFF_GO = 152
OFF_DONE = 160
OFF_WAIT = 168
OFF_SET = 176
_MEI = 192  # ThreadId, pad, ExceptionPointers, ClientPointers
OFF_BUF = 224
OFF_MODNAME = OFF_BUF + 8192
OFF_STR = OFF_MODNAME + 520

_FATAL = (
    0xC0000005,  # access violation
    0xC0000006,  # in-page error
    0xC000001D,  # illegal instruction
    0xC0000094,  # integer divide by zero
    0xC0000096,  # privileged instruction
    0xC00000FD,  # stack overflow
    0xC0000409,  # fast fail
)

# MiniDumpWithDataSegs | WithHandleData | WithUnloadedModules
# | WithIndirectlyReferencedMemory | WithProcessThreadData
# | WithThreadInfo | IgnoreInaccessibleMemory
_DUMP_TYPE = 0x1 | 0x4 | 0x20 | 0x40 | 0x100 | 0x1000 | 0x20000


class _Asm:
    def __init__(self) -> None:
        self.code = bytearray()
        self.fixups: list[tuple[int, str]] = []
        self.labels: dict[str, int] = {}

    def here(self, name: str) -> None:
        self.labels[name] = len(self.code)

    def b(self, data: bytes) -> None:
        self.code.extend(data)

    def u8(self, value: int) -> None:
        self.code.append(value & 0xFF)

    def u32(self, value: int) -> None:
        self.code.extend(struct.pack("<I", value & 0xFFFFFFFF))

    def rel32(self, label: str) -> None:
        self.fixups.append((len(self.code), label))
        self.u32(0)

    def near(self, opcode: bytes, label: str) -> None:
        self.b(opcode)
        self.rel32(label)

    def finish(self, data_at: int) -> bytes:
        self.labels["data"] = data_at
        for at, label in self.fixups:
            dest = self.labels[label]
            struct.pack_into("<i", self.code, at, dest - (at + 4))
        return bytes(self.code)


def _lea_rcx(asm: _Asm, offset: int) -> None:
    asm.b(b"\x49\x8D\x8C\x24")
    asm.u32(offset)


def _call(asm: _Asm, label: str) -> None:
    asm.near(b"\xE8", label)


def _newline(asm: _Asm) -> None:
    asm.b(b"\x41\xC6\x45\x00\x0A\x49\xFF\xC5")


def _remember(asm: _Asm) -> None:
    """Store rcx at scratch. Later calls clobber rcx."""
    asm.b(b"\x49\x89\x8C\x24")
    asm.u32(OFF_SCRATCH)


def _reload(asm: _Asm) -> None:
    asm.b(b"\x49\x8B\x8C\x24")
    asm.u32(OFF_SCRATCH)


def _emit_labeled_value(asm: _Asm, label_off: int, load_rcx: bytes, locate: bool) -> None:
    _lea_rcx(asm, label_off)
    _call(asm, "append_str")
    asm.b(load_rcx)
    _remember(asm)
    _reload(asm)
    _call(asm, "append_hex64")
    if locate:
        _reload(asm)
        _call(asm, "append_loc")
    _newline(asm)


def _load_record_field(offset: int) -> bytes:
    # mov rax, [rbx]; mov rcx, [rax+offset]
    if offset == 0:
        return b"\x48\x8B\x03\x8B\x08"
    if offset < 128:
        return b"\x48\x8B\x03\x48\x8B\x48" + bytes((offset,))
    packed = struct.pack("<I", offset)
    return b"\x48\x8B\x03\x48\x8B\x88" + packed


def _load_context_field(offset: int) -> bytes:
    # mov rax, [rbx+8]; mov rcx, [rax+offset]
    packed = struct.pack("<I", offset)
    return b"\x48\x8B\x43\x08\x48\x8B\x88" + packed


def _load_stack_slot(index: int) -> bytes:
    # mov rax, [rbx+8]; mov rax, [rax+152]; mov rcx, [rax+index*8]
    disp = index * 8
    head = b"\x48\x8B\x43\x08\x48\x8B\x80" + struct.pack("<I", 152)
    if disp == 0:
        return head + b"\x48\x8B\x08"
    if disp < 128:
        return head + b"\x48\x8B\x48" + bytes((disp,))
    return head + b"\x48\x8B\x88" + struct.pack("<I", disp)


def _build_code(strings: dict[str, int]) -> tuple[bytes, int]:
    asm = _Asm()
    # Unhandled-exception filter. rcx = EXCEPTION_POINTERS on entry.
    asm.b(b"\x53\x41\x54\x41\x55\x48\x83\xEC\x40")
    asm.b(b"\x4C\x8D\x25")
    asm.rel32("data")
    asm.b(b"\x48\x89\xCB")  # mov rbx, rcx
    asm.b(b"\x48\x8B\x03\x8B\x00")  # mov eax, [ [rbx] ]
    for code in _FATAL:
        asm.b(b"\x3D")
        asm.u32(code)
        asm.near(b"\x0F\x84", "fatal")
    asm.near(b"\xE9", "forward")

    asm.here("fatal")
    asm.b(b"\xB8\x01\x00\x00\x00\xF0\x41\x87\x04\x24")  # lock xchg eax, [r12]
    asm.b(b"\x85\xC0")
    asm.near(b"\x0F\x85", "forward")
    asm.b(b"\x4D\x8D\xAC\x24")  # lea r13, [r12+OFF_BUF]
    asm.u32(OFF_BUF)

    _emit_labeled_value(asm, strings["code"], _load_record_field(0), False)
    _emit_labeled_value(asm, strings["address"], _load_record_field(16), False)
    _emit_labeled_value(asm, strings["access"], _load_record_field(32), False)
    _emit_labeled_value(asm, strings["target"], _load_record_field(40), False)

    registers = (
        ("rax", 120),
        ("rcx", 128),
        ("rdx", 136),
        ("rbx", 144),
        ("rsp", 152),
        ("rbp", 160),
        ("rsi", 168),
        ("rdi", 176),
        ("r8", 184),
        ("r9", 192),
        ("r10", 200),
        ("r11", 208),
        ("r12", 216),
        ("r13", 224),
        ("r14", 232),
        ("r15", 240),
        ("rip", 248),
    )
    for name, offset in registers:
        _emit_labeled_value(asm, strings[name], _load_context_field(offset), False)

    # Raw registers hit disk before any module lookup or stack read.
    _call(asm, "write_from_scratch")

    _emit_labeled_value(asm, strings["address"], _load_record_field(16), True)
    _emit_labeled_value(asm, strings["target"], _load_record_field(40), True)
    _emit_labeled_value(asm, strings["rip"], _load_context_field(248), True)
    _lea_rcx(asm, strings["stack"])
    _call(asm, "append_str")
    for index in range(8):
        _emit_labeled_value(asm, strings["slot"], _load_stack_slot(index), True)
    _call(asm, "write_from_scratch")

    # Another thread writes the dump. Doing it here overwrites this stack
    # before dbghelp records it, and a handmade exception record makes
    # MiniDumpWriteDump fail. The pointer in rbx is the real one from Windows.
    asm.b(b"\x49\x89\x9C\x24")
    asm.u32(OFF_EP)
    asm.b(b"\x49\x8B\x8C\x24")
    asm.u32(OFF_GO)
    asm.b(b"\x49\x8B\x84\x24")
    asm.u32(OFF_SET)
    asm.b(b"\xFF\xD0")
    asm.b(b"\x49\x8B\x8C\x24")
    asm.u32(OFF_DONE)
    asm.b(b"\xBA\x20\x4E\x00\x00")  # 20000 ms
    asm.b(b"\x49\x8B\x84\x24")
    asm.u32(OFF_WAIT)
    asm.b(b"\xFF\xD0")

    asm.here("forward")
    asm.b(b"\x48\x89\xD9")  # mov rcx, rbx
    asm.b(b"\x49\x8B\x84\x24")
    asm.u32(OFF_PREV)
    asm.b(b"\x48\x85\xC0")
    asm.near(b"\x0F\x84", "search")
    asm.b(b"\x48\x83\xC4\x40\x41\x5D\x41\x5C\x5B\xFF\xE0")

    asm.here("search")
    asm.b(b"\x31\xC0\x48\x83\xC4\x40\x41\x5D\x41\x5C\x5B\xC3")

    # lpParameter is the data block. Waits until the filter publishes the
    # real EXCEPTION_POINTERS, then writes the dump off the faulting stack.
    asm.here("dump_thread")
    asm.b(b"\x53\x48\x83\xEC\x40")
    asm.b(b"\x48\x89\xCB")  # mov rbx, rcx
    asm.here("dump_wait")
    asm.b(b"\x48\x8B\x8B")
    asm.u32(OFF_GO)
    asm.b(b"\xBA\xFF\xFF\xFF\xFF")
    asm.b(b"\x48\x8B\x83")
    asm.u32(OFF_WAIT)
    asm.b(b"\xFF\xD0")
    asm.b(b"\x48\x8B\x83")
    asm.u32(OFF_GETTID)
    asm.b(b"\xFF\xD0")
    asm.b(b"\x89\x83")
    asm.u32(_MEI)
    asm.b(b"\x48\x8B\x83")
    asm.u32(OFF_EP)
    asm.b(b"\x48\x89\x83")
    asm.u32(_MEI + 8)
    asm.b(b"\xC7\x83")
    asm.u32(_MEI + 16)
    asm.u32(1)
    asm.b(b"\x48\x8B\x8B")
    asm.u32(OFF_PROCESS)
    asm.b(b"\x8B\x93")
    asm.u32(OFF_PID)
    asm.b(b"\x4C\x8B\x83")
    asm.u32(OFF_DUMP)
    asm.b(b"\x44\x8B\x8B")
    asm.u32(OFF_DUMPTYPE)
    asm.b(b"\x48\x8D\x83")
    asm.u32(_MEI)
    asm.b(b"\x48\x89\x44\x24\x20")
    asm.b(b"\x48\xC7\x44\x24\x28\x00\x00\x00\x00")
    asm.b(b"\x48\xC7\x44\x24\x30\x00\x00\x00\x00")
    asm.b(b"\x48\x8B\x83")
    asm.u32(OFF_DUMPFN)
    asm.b(b"\xFF\xD0")
    asm.b(b"\x85\xC0")
    asm.near(b"\x0F\x85", "dump_flush")
    asm.b(b"\x48\x8B\x8B")
    asm.u32(OFF_PROCESS)
    asm.b(b"\x8B\x93")
    asm.u32(OFF_PID)
    asm.b(b"\x4C\x8B\x83")
    asm.u32(OFF_DUMP)
    asm.b(b"\x44\x8B\x8B")
    asm.u32(OFF_DUMPTYPE)
    asm.b(b"\x48\x31\xC0\x48\x89\x44\x24\x20\x48\x89\x44\x24\x28\x48\x89\x44\x24\x30")
    asm.b(b"\x48\x8B\x83")
    asm.u32(OFF_DUMPFN)
    asm.b(b"\xFF\xD0")
    asm.here("dump_flush")
    asm.b(b"\x48\x8B\x8B")
    asm.u32(OFF_DUMP)
    asm.b(b"\x48\x8B\x83")
    asm.u32(OFF_FLUSH)
    asm.b(b"\xFF\xD0")
    asm.b(b"\x48\x8B\x8B")
    asm.u32(OFF_DONE)
    asm.b(b"\x48\x8B\x83")
    asm.u32(OFF_SET)
    asm.b(b"\xFF\xD0")
    asm.near(b"\xE9", "dump_wait")

    asm.here("append_str")
    asm.here("append_str_loop")
    asm.b(b"\x49\x8D\x84\x24")
    asm.u32(OFF_BUF + 8000)
    asm.b(b"\x49\x39\xC5")
    asm.near(b"\x0F\x83", "append_str_ret")
    asm.b(b"\x8A\x01\x84\xC0")
    asm.near(b"\x0F\x84", "append_str_ret")
    asm.b(b"\x41\x88\x45\x00\x49\xFF\xC5\x48\xFF\xC1")
    asm.near(b"\xE9", "append_str_loop")
    asm.here("append_str_ret")
    asm.b(b"\xC3")

    asm.here("append_hex64")
    asm.b(b"\x49\x89\xCA\x41\xBB\x10\x00\x00\x00")  # mov r10, rcx; mov r11d, 16
    asm.here("hex_loop")
    asm.b(b"\x49\x8D\x84\x24")
    asm.u32(OFF_BUF + 8000)
    asm.b(b"\x49\x39\xC5")
    asm.near(b"\x0F\x83", "hex_ret")
    asm.b(b"\x4C\x89\xD0\x48\xC1\xE8\x3C\x04\x30\x3C\x3A")
    asm.near(b"\x0F\x82", "hex_store")
    asm.b(b"\x04\x27")
    asm.here("hex_store")
    asm.b(b"\x41\x88\x45\x00\x49\xFF\xC5\x49\xC1\xE2\x04\x41\xFF\xCB")
    asm.near(b"\x0F\x85", "hex_loop")
    asm.here("hex_ret")
    asm.b(b"\xC3")

    asm.here("append_loc")
    asm.b(b"\x56\x48\x83\xEC\x30")
    asm.b(b"\x48\x89\xCE")  # mov rsi, rcx
    asm.b(b"\x49\x89\xB4\x24")
    asm.u32(OFF_HMOD)
    # zero the qword first so a failed lookup does not reuse an old module
    asm.b(b"\x49\xC7\x84\x24")
    asm.u32(OFF_HMOD)
    asm.u32(0)
    asm.b(b"\xB9\x06\x00\x00\x00")  # FROM_ADDRESS | UNCHANGED_REFCOUNT
    asm.b(b"\x48\x89\xF2")
    asm.b(b"\x4D\x8D\x84\x24")
    asm.u32(OFF_HMOD)
    asm.b(b"\x49\x8B\x84\x24")
    asm.u32(OFF_GETMOD)
    asm.b(b"\xFF\xD0\x85\xC0")
    asm.near(b"\x0F\x84", "loc_done")
    asm.b(b"\x49\x8B\x8C\x24")
    asm.u32(OFF_HMOD)
    asm.b(b"\x49\x8D\x94\x24")
    asm.u32(OFF_MODNAME)
    asm.b(b"\x41\xB8\x04\x01\x00\x00")  # 260
    asm.b(b"\x49\x8B\x84\x24")
    asm.u32(OFF_GETNAME)
    asm.b(b"\xFF\xD0")
    asm.b(b"\xB0\x20")  # space
    _call(asm, "emit_byte")
    asm.b(b"\x49\x8D\x94\x24")
    asm.u32(OFF_MODNAME)
    asm.b(b"\x49\x89\xD0")  # mov r8, rdx  (scan cursor starts at the name)
    asm.here("loc_scan")
    asm.b(b"\x0F\xB7\x02\x85\xC0")
    asm.near(b"\x0F\x84", "loc_emit")
    asm.b(b"\x66\x83\xF8\x5C")
    asm.near(b"\x0F\x85", "loc_next")
    asm.b(b"\x4C\x8D\x42\x02")  # lea r8, [rdx+2]
    asm.here("loc_next")
    asm.b(b"\x48\x83\xC2\x02")
    asm.near(b"\xE9", "loc_scan")
    asm.here("loc_emit")
    asm.b(b"\x41\x0F\xB7\x00\x85\xC0")
    asm.near(b"\x0F\x84", "loc_plus")
    _call(asm, "emit_byte")
    asm.b(b"\x49\x83\xC0\x02")
    asm.near(b"\xE9", "loc_emit")
    asm.here("loc_plus")
    asm.b(b"\xB0\x2B")
    _call(asm, "emit_byte")
    asm.b(b"\x48\x89\xF1")
    asm.b(b"\x49\x2B\x8C\x24")
    asm.u32(OFF_HMOD)
    _call(asm, "append_hex64")
    asm.here("loc_done")
    asm.b(b"\x48\x83\xC4\x30\x5E\xC3")

    asm.here("emit_byte")
    asm.b(b"\x49\x8D\x90\x24") if False else asm.b(b"")
    asm.b(b"\x49\x8D\x94\x24")
    asm.u32(OFF_BUF + 8000)
    asm.b(b"\x49\x39\xD5")
    asm.near(b"\x0F\x83", "emit_ret")
    asm.b(b"\x41\x88\x45\x00\x49\xFF\xC5")
    asm.here("emit_ret")
    asm.b(b"\xC3")

    asm.here("write_from_scratch")
    asm.b(b"\x56\x48\x83\xEC\x30")
    asm.b(b"\x49\x8B\x94\x24")
    asm.u32(OFF_POS)
    asm.b(b"\x48\x85\xD2")
    asm.near(b"\x0F\x85", "write_have_start")
    asm.b(b"\x49\x8D\x94\x24")
    asm.u32(OFF_BUF)
    asm.here("write_have_start")
    asm.b(b"\x49\x8B\x8C\x24")
    asm.u32(OFF_TEXTH)
    asm.b(b"\x4C\x89\xE8\x48\x29\xD0")  # mov rax, r13; sub rax, rdx
    asm.b(b"\x49\x89\xC0")  # mov r8, rax
    asm.b(b"\x4D\x8D\x8C\x24")
    asm.u32(OFF_WRITTEN)
    asm.b(b"\x48\xC7\x44\x24\x20\x00\x00\x00\x00")
    asm.b(b"\x49\x8B\x84\x24")
    asm.u32(OFF_WRITE)
    asm.b(b"\xFF\xD0")
    asm.b(b"\x49\x8B\x8C\x24")
    asm.u32(OFF_TEXTH)
    asm.b(b"\x49\x8B\x84\x24")
    asm.u32(OFF_FLUSH)
    asm.b(b"\xFF\xD0")
    asm.b(b"\x4D\x89\xAC\x24")
    asm.u32(OFF_POS)
    asm.b(b"\x48\x83\xC4\x30\x5E\xC3")

    while len(asm.code) % 16:
        asm.b(b"\x90")
    dump_at = asm.labels["dump_thread"]
    return asm.finish(len(asm.code)), dump_at


def _strings() -> tuple[bytes, dict[str, int]]:
    names = (
        "code",
        "address",
        "access",
        "target",
        "rax",
        "rcx",
        "rdx",
        "rbx",
        "rsp",
        "rbp",
        "rsi",
        "rdi",
        "r8",
        "r9",
        "r10",
        "r11",
        "r12",
        "r13",
        "r14",
        "r15",
        "rip",
        "stack",
        "slot",
    )
    text = {
        "code": b"code=",
        "address": b"address=",
        "access": b"access=",
        "target": b"target=",
        "stack": b"stack\n",
        "slot": b"slot ",
    }
    for name in names:
        text.setdefault(name, name.encode("ascii") + b"=")
    blob = bytearray()
    offsets: dict[str, int] = {}
    for name in names:
        offsets[name] = OFF_STR + len(blob)
        blob.extend(text[name])
        blob.append(0)
    return bytes(blob), offsets


def _poke(base: int, offset: int, value: int, size: int) -> None:
    raw = int(value or 0).to_bytes(size, "little", signed=False)
    ctypes.memmove(base + offset, raw, size)


def install(directory: str) -> bool:
    """Arm the native filter. Safe to call once. Returns False if it could not arm."""
    if _STATE.get("armed"):
        return True
    os.makedirs(directory, exist_ok=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dbghelp = ctypes.WinDLL("dbghelp", use_last_error=True)

    kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    kernel32.VirtualAlloc.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    kernel32.SetUnhandledExceptionFilter.argtypes = [ctypes.c_void_p]
    kernel32.SetUnhandledExceptionFilter.restype = ctypes.c_void_p

    strings, offsets = _strings()
    code, dump_at = _build_code(offsets)
    data = bytearray(OFF_STR) + bytearray(strings)
    blob = code + data
    memory = kernel32.VirtualAlloc(None, len(blob), 0x3000, 0x40)
    if not memory:
        return False
    ctypes.memmove(memory, blob, len(blob))
    data_at = memory + len(code)

    def _open(name: str) -> int:
        path = os.path.join(directory, name)
        handle = kernel32.CreateFileW(path, 0x40000000, 0x01, None, 2, 0x80 | 0x80000000, None)
        if handle is None or int(handle) == 0xFFFFFFFFFFFFFFFF:
            return 0
        return int(handle)

    text_handle = _open("native-crash.txt")
    dump_handle = _open("native-crash.dmp")
    if not text_handle or not dump_handle:
        return False

    def _proc(dll, name: str) -> int:
        return int(ctypes.cast(getattr(dll, name), ctypes.c_void_p).value or 0)

    _poke(data_at, OFF_PID, kernel32.GetCurrentProcessId(), 4)
    _poke(data_at, OFF_PROCESS, kernel32.GetCurrentProcess(), 8)
    _poke(data_at, OFF_DUMP, dump_handle, 8)
    _poke(data_at, OFF_TEXTH, text_handle, 8)
    _poke(data_at, OFF_DUMPFN, _proc(dbghelp, "MiniDumpWriteDump"), 8)
    _poke(data_at, OFF_GETTID, _proc(kernel32, "GetCurrentThreadId"), 8)
    _poke(data_at, OFF_WRITE, _proc(kernel32, "WriteFile"), 8)
    _poke(data_at, OFF_GETMOD, _proc(kernel32, "GetModuleHandleExW"), 8)
    _poke(data_at, OFF_GETNAME, _proc(kernel32, "GetModuleFileNameW"), 8)
    _poke(data_at, OFF_FLUSH, _proc(kernel32, "FlushFileBuffers"), 8)
    _poke(data_at, OFF_WAIT, _proc(kernel32, "WaitForSingleObject"), 8)
    _poke(data_at, OFF_SET, _proc(kernel32, "SetEvent"), 8)
    _poke(data_at, OFF_DUMPTYPE, _DUMP_TYPE, 4)

    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateEventW.restype = ctypes.c_void_p
    kernel32.CreateThread.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    kernel32.CreateThread.restype = ctypes.c_void_p
    go_event = kernel32.CreateEventW(None, False, False, None)
    done_event = kernel32.CreateEventW(None, False, False, None)
    if not go_event or not done_event:
        return False
    _poke(data_at, OFF_GO, go_event, 8)
    _poke(data_at, OFF_DONE, done_event, 8)
    thread = kernel32.CreateThread(None, 0, memory + dump_at, data_at, 0, None)
    if not thread:
        return False

    previous = kernel32.SetUnhandledExceptionFilter(memory)
    _poke(data_at, OFF_PREV, previous or 0, 8)
    _STATE["armed"] = True
    _STATE["memory"] = memory
    _STATE["directory"] = directory
    return True


def _invoke_for_test(record_addr: int, context_addr: int) -> None:
    """Call the filter directly. Used by the self-test."""
    ep = (ctypes.c_uint64 * 2)(record_addr, context_addr)
    prototype = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
    prototype(_STATE["memory"])(ctypes.addressof(ep))


def _self_test() -> None:
    import tempfile
    import time

    if "--av" in sys.argv:
        folder = sys.argv[-1]
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetErrorMode(0x0003)
        if not install(folder):
            raise SystemExit(2)
        stub = bytes((0x48, 0x31, 0xC0, 0x48, 0x8B, 0x00, 0xC3))
        kernel32.VirtualAlloc.restype = ctypes.c_void_p
        page = kernel32.VirtualAlloc(None, len(stub), 0x3000, 0x40)
        ctypes.memmove(page, stub, len(stub))
        kernel32.CreateThread.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        kernel32.CreateThread.restype = ctypes.c_void_p
        kernel32.CreateThread(None, 0, page, None, 0, None)
        time.sleep(8)
        raise SystemExit(0)

    folder = tempfile.mkdtemp(prefix="native-fault-")
    if not install(folder):
        raise SystemExit("install failed")

    captured = ctypes.create_string_buffer(4096)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.RtlCaptureContext.argtypes = [ctypes.c_void_p]
    kernel.RtlCaptureContext(ctypes.addressof(captured))
    struct.pack_into("<Q", captured, 120, 0xDEADBEEF)
    rip = int.from_bytes(captured.raw[248:256], "little")
    stack = (ctypes.c_uint64 * 8)()
    stack[0] = rip
    struct.pack_into("<Q", captured, 152, ctypes.addressof(stack))
    record = ctypes.create_string_buffer(256)
    struct.pack_into("<I", record, 0, 0xC0000005)
    struct.pack_into("<Q", record, 16, rip)
    struct.pack_into("<I", record, 24, 2)
    struct.pack_into("<Q", record, 40, 0x10)
    _invoke_for_test(ctypes.addressof(record), ctypes.addressof(captured))
    text = open(os.path.join(folder, "native-crash.txt"), "rb").read().decode("ascii", "replace")
    dump = open(os.path.join(folder, "native-crash.dmp"), "rb").read(4)
    print(text)
    print("dump", dump)
    if "c0000005" not in text or "deadbeef" not in text:
        raise SystemExit(f"direct capture failed in {folder}")
    print("direct ok", folder, "dump", dump)
