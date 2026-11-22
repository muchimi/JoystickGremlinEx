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
"""Driver-free DILL binding regressions: python tools/test_dill_api.py."""

import ast
import copy
import ctypes
from ctypes import wintypes as ctwt
import logging
import os
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import uuid

ROOT = Path(__file__).resolve().parents[1]


def load_binding():
    source = ROOT / "dinput/__init__.py"
    names = {"DILLError", "_GUID", "_AxisMap", "_JoystickInputData", "_DeviceSummary", "_DillAbiInfo", "DILL"}
    nodes = [node for node in ast.parse(source.read_bytes()).body
             if isinstance(node, ast.ClassDef) and node.name in names
             or isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                 and target.id in {"C_EVENT_CALLBACK", "C_DEVICE_CHANGE_CALLBACK"} for target in node.targets)]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    namespace = dict(ctypes=ctypes, ctwt=ctwt, threading=threading, copy=copy, uuid=uuid, os=os,
                     __file__=str(source), syslog=logging.getLogger(__name__),
                     DeviceSummary=lambda row: NS(name=row.name.decode(), device_guid=row.device_guid.toId()))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[])), str(source), "exec"), namespace)
    return namespace


class BindingChecks(unittest.TestCase):
    def setUp(self):
        self.ns = load_binding()
        self.dill = self.ns["DILL"]
        self.error = self.ns["DILLError"]
        self.abi_type = self.ns["_DillAbiInfo"]
        self.rows = []
        self.code = 0
        self.running = False
        self.library = NS(**{name: Mock() for name in self.dill.api_functions})
        self.library.get_api_version.return_value = self.dill.API_VERSION
        self.library.get_abi_info.side_effect = self.fill_abi
        self.library.is_worker_thread.return_value = False
        self.library.is_initialized.side_effect = lambda: self.running
        self.library.init.side_effect = self.start
        self.library.shutdown.side_effect = self.stop
        self.library.get_device_snapshot.side_effect = self.snapshot
        self.library.get_last_error_code.side_effect = lambda: self.code
        self.library.get_last_error_message.side_effect = self.message
        self.dill._dll = self.library
        util = ModuleType("gremlin.util")
        util.get_dll_version = Mock()
        modules = patch.dict(sys.modules, {"gremlin": ModuleType("gremlin"), "gremlin.util": util})
        modules.start()
        self.addCleanup(modules.stop)

    def fill_abi(self, pointer, size):
        info = ctypes.cast(pointer, ctypes.POINTER(self.abi_type)).contents
        values = (self.dill.API_VERSION, ctypes.sizeof(self.abi_type), ctypes.sizeof(self.ns["_GUID"]),
                  ctypes.sizeof(self.ns["_DeviceSummary"]), ctypes.sizeof(self.ns["_JoystickInputData"]),
                  ctypes.sizeof(self.ns["_AxisMap"]), self.ns["_DeviceSummary"].usage_page.offset,
                  self.ns["_DeviceSummary"].usage.offset, self.ns["_JoystickInputData"].input_type.offset,
                  self.ns["_JoystickInputData"].input_index.offset, self.ns["_JoystickInputData"].value.offset)
        for (name, _), value in zip(info._fields_, values):
            setattr(info, name, value)
        return True

    def start(self):
        self.running = True
        return True

    def stop(self):
        self.running = False
        return True

    def message(self, buffer, capacity):
        buffer.value = b"native failure"
        return 15

    def snapshot(self, buffer, capacity, count, generation):
        ctypes.cast(count, ctypes.POINTER(ctypes.c_size_t)).contents.value = len(self.rows)
        ctypes.cast(generation, ctypes.POINTER(ctypes.c_uint64)).contents.value = 42
        if capacity < len(self.rows):
            self.code = 0x8007007A
            return False
        for index, row in enumerate(self.rows):
            buffer[index] = row
        return True

    def test_wrong_api_is_rejected_before_native_initialization(self):
        self.library.get_api_version.return_value = 0x00010000
        with self.assertRaisesRegex(self.error, "Incompatible DILL API"):
            self.dill._start_library(self.library)
        self.library.init.assert_not_called()

    def test_legacy_dll_is_rejected_without_passing_structures(self):
        del self.library.get_api_version
        with self.assertRaisesRegex(self.error, "API 2 is required"):
            self.dill._start_library(self.library)
        self.library.init.assert_not_called()

    def test_layout_mismatch_is_rejected_before_native_initialization(self):
        def wrong(pointer, size):
            self.fill_abi(pointer, size)
            ctypes.cast(pointer, ctypes.POINTER(self.abi_type)).contents.device_summary_size -= 4
            return True
        self.library.get_abi_info.side_effect = wrong
        with self.assertRaisesRegex(self.error, "device_summary_size"):
            self.dill._start_library(self.library)
        self.library.init.assert_not_called()

    def test_native_initialization_failure_preserves_error_details(self):
        self.library.init.side_effect = None
        self.library.init.return_value = False
        self.code = 0x80004005
        with self.assertRaisesRegex(self.error, "native failure.*80004005"):
            self.dill.init()
        self.assertFalse(self.dill.initialized)

    def test_snapshot_grows_buffer_without_count_index_calls(self):
        self.dill.init()
        for index in range(40):
            row = self.ns["_DeviceSummary"]()
            row.name = f"Controller {index}".encode()
            row.device_guid.Data1 = index + 1
            self.rows.append(row)
        devices = self.dill.getDevices()
        self.assertEqual([row.name for row in devices], [f"Controller {index}" for index in range(40)])
        self.assertEqual(self.library.get_device_snapshot.call_count, 2)
        self.library.get_device_count.assert_not_called()
        self.library.get_device_information_by_index.assert_not_called()
        self.assertEqual(self.dill.snapshot_generation, 42)

    def test_snapshot_failure_is_reported_without_retrying_unrelated_error(self):
        self.dill.init()
        self.library.get_device_snapshot.side_effect = None
        self.library.get_device_snapshot.return_value = False
        self.code = 0x80004005
        with self.assertRaisesRegex(self.error, "80004005"):
            self.dill.getDevices()
        self.library.get_device_snapshot.assert_called_once()

    def test_lifecycle_is_idempotent_and_reuses_library_after_shutdown(self):
        self.dill.init()
        self.dill.init()
        self.library.init.assert_called_once()
        self.dill.set_input_event_callback(lambda event: None)
        original = self.dill.input_event_callback_fn
        def joining():
            self.assertIs(self.dill.input_event_callback_fn, original)
            return self.stop()
        self.library.shutdown.side_effect = joining
        self.dill.shutdown()
        self.assertIsNone(self.dill.input_event_callback_fn)
        self.assertFalse(self.dill.initialized)
        self.assertEqual(self.dill.getDevices(), [])
        self.dill.init()
        self.assertTrue(self.dill.initialized)
        self.assertEqual(self.library.init.call_count, 2)

    def test_replaced_callbacks_remain_pinned_until_native_workers_join(self):
        self.dill.init()
        self.dill.set_input_event_callback(lambda event: None)
        first = self.dill.input_event_callback_fn
        self.dill.set_input_event_callback(None)
        self.assertIn(first, self.dill._retired_callbacks)
        self.dill.shutdown()
        self.assertEqual(self.dill._retired_callbacks, [])

    def test_shutdown_failure_does_not_release_callback_trampolines(self):
        self.dill.init()
        self.dill.set_input_event_callback(lambda event: None)
        first = self.dill.input_event_callback_fn
        self.library.shutdown.side_effect = None
        self.library.shutdown.return_value = False
        self.code = 0x800700AA
        with self.assertRaises(self.error):
            self.dill.shutdown()
        self.assertIs(self.dill.input_event_callback_fn, first)

    def test_native_callback_cannot_wait_on_owner_lifecycle_lock(self):
        self.library.is_worker_thread.return_value = True
        with self.assertRaisesRegex(self.error, "outside native callbacks"):
            self.dill.shutdown()
        self.library.shutdown.assert_not_called()

    def test_listener_joins_native_workers_even_if_callback_setup_fails(self):
        tree = ast.parse((ROOT / "gremlin/event_handler.py").read_bytes())
        owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EventListener")
        run = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "_run")
        run.decorator_list = []
        native = NS(initialized=True, set_device_change_callback=Mock(),
                    set_input_event_callback=Mock(side_effect=RuntimeError("setup failed")), shutdown=Mock())
        namespace = dict(dinput=NS(DILL=native), syslog=logging.getLogger(__name__))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[run], type_ignores=[])), "event_handler.py", "exec"), namespace)
        listener = NS(_dinput_device_change_handler=Mock(), _dinput_event_handler=Mock(), _run_event=Mock())
        with self.assertRaisesRegex(RuntimeError, "setup failed"):
            namespace["_run"](listener)
        native.shutdown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main(verbosity=2)
