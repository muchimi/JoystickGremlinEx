# -*- coding: utf-8; -*-

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


import ctypes
import enum
import os
import logging
import threading
import ctypes.wintypes as wintypes

syslog = logging.getLogger("system")


class VJoyState(enum.Enum):
    """Enumeration of the possible VJoy device states."""

    Owned = 0  # The device is owned by the current application VJD_STAT_OWN
    Free = 1  # The device is not owned by any application VJD_STAT_FREE
    Bust = 2  # The device is owned by another application VJD_STAT_BUSY
    Missing = 3  # The device is not present VJD_STAT_MISS
    Unknown = 4  # Unknown type of error VJD_STAT_UNKN


class VJoyInterface:
    """Allows low level interaction with VJoy devices via ctypes."""

    vjoy_dll = None
    valid = False
    initialization_error = None

    # Declare argument and return types for all the functions
    # exposed by the dll
    api_functions = {
        # General vJoy information
        "GetvJoyVersion": {"arguments": [], "returns": ctypes.c_short},
        "vJoyEnabled": {"arguments": [], "returns": ctypes.c_bool},
        "GetvJoyProductString": {"arguments": [], "returns": ctypes.c_wchar_p},
        "GetvJoyManufacturerString": {"arguments": [], "returns": ctypes.c_wchar_p},
        "GetvJoySerialNumberString": {"arguments": [], "returns": ctypes.c_wchar_p},
        # Device properties
        "GetVJDButtonNumber": {"arguments": [ctypes.c_uint], "returns": ctypes.c_int},
        "GetVJDDiscPovNumber": {"arguments": [ctypes.c_uint], "returns": ctypes.c_int},
        "GetVJDContPovNumber": {"arguments": [ctypes.c_uint], "returns": ctypes.c_int},
        # API claims this should return a bool, however, this is untrue and
        # is an int, see:
        # http://vjoystick.sourceforge.net/site/index.php/forum/5-Discussion/1026-bug-with-getvjdaxisexist
        "GetVJDAxisExist": {
            "arguments": [ctypes.c_uint, ctypes.c_uint],
            "returns": ctypes.c_int,
        },
        "GetVJDAxisMax": {
            "arguments": [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p],
            "returns": ctypes.c_bool,
        },
        "GetVJDAxisMin": {
            "arguments": [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p],
            "returns": ctypes.c_bool,
        },
        # Device management
        "GetOwnerPid": {"arguments": [ctypes.c_uint], "returns": ctypes.c_int},
        "AcquireVJD": {"arguments": [ctypes.c_uint], "returns": ctypes.c_bool},
        "RelinquishVJD": {
            "arguments": [ctypes.c_uint],
            "returns": None,
        },
        "UpdateVJD": {
            "arguments": [ctypes.c_uint, ctypes.c_void_p],
            "returns": ctypes.c_bool,
        },
        "GetVJDStatus": {"arguments": [ctypes.c_uint], "returns": ctypes.c_int},
        # Reset functions
        "ResetVJD": {"arguments": [ctypes.c_uint], "returns": ctypes.c_bool},
        "ResetAll": {"arguments": [], "returns": None},
        "ResetButtons": {"arguments": [ctypes.c_uint], "returns": ctypes.c_bool},
        "ResetPovs": {"arguments": [ctypes.c_uint], "returns": ctypes.c_bool},
        # Set values
        "SetAxis": {
            "arguments": [ctypes.c_long, ctypes.c_uint, ctypes.c_uint],
            "returns": ctypes.c_bool,
        },
        "SetBtn": {
            "arguments": [ctypes.c_bool, ctypes.c_uint, ctypes.c_ubyte],
            "returns": ctypes.c_bool,
        },
        "SetDiscPov": {
            "arguments": [ctypes.c_int, ctypes.c_uint, ctypes.c_ubyte],
            "returns": ctypes.c_bool,
        },
        "SetContPov": {
            "arguments": [ctypes.c_ulong, ctypes.c_uint, ctypes.c_ubyte],
            "returns": ctypes.c_bool,
        },
    }


    @classmethod
    def initialize(self):
        """Initializes the functions as class methods."""
        if not self._is_ui_thread():
            return self._call_on_ui_thread(self.initialize)

        from pathlib import Path
        from gremlin.util import get_dll_version, version_valid

        if VJoyInterface.vjoy_dll is None:
            dll_folder = os.path.dirname(__file__)
            dll_file = "vJoyInterface.dll"
            _dll_path = os.path.join(dll_folder, dll_file)
            if not os.path.isfile(_dll_path):
                # look one level up for packaging in 3.12
                parent = Path(dll_folder).parent
                _dll_path = os.path.join(parent, dll_file)
                if not os.path.isfile(_dll_path):
                    return self._unavailable(f"Missing vJoy interface DLL: {_dll_path}")

            # check DLL version
            min_version = "2.1.9.1"
            try:
                dll_version = get_dll_version(_dll_path)

                if not version_valid(dll_version, min_version):
                    return self._unavailable(f"vJoy interface requires version {min_version}, found {dll_version}: {_dll_path}")
            except Exception as error:
                return self._unavailable(f"Unable to read vJoy interface version: {error}")

            syslog.info(f"Found VJOY DLL version {dll_version}")

            try:
                VJoyInterface.vjoy_dll = ctypes.cdll.LoadLibrary(_dll_path)
            except Exception as error:
                return self._unavailable(f"Unable to load vJoy interface DLL: {error}")

        try:
            functions = {}
            for fn_name, params in self.api_functions.items():
                dll_fn = getattr(self.vjoy_dll, fn_name)
                dll_fn.argtypes = params["arguments"]
                dll_fn.restype = params["returns"]
                functions[fn_name] = self._wrap_ui_thread_call(dll_fn)
            for fn_name, function in functions.items():
                setattr(self, fn_name, staticmethod(function))
        except Exception as error:
            return self._unavailable(f"Unable to initialize vJoy interface: {error}")

        self.valid = True
        self.initialization_error = None
        return True

    @classmethod
    def _reset_api(cls):
        """Keep optional-driver queries safe when the DLL cannot be used."""
        cls.valid = False
        for name, params in cls.api_functions.items():
            if name == 'GetVJDStatus':
                result = VJoyState.Missing.value
            elif params['returns'] in (None, ctypes.c_wchar_p):
                result = None
            else:
                result = 0
            setattr(cls, name, staticmethod(lambda *args, result=result: result))

    @classmethod
    def _unavailable(cls, reason):
        cls._reset_api()
        cls.initialization_error = reason
        syslog.warning("VJOY: %s. Native vJoy output is unavailable.", reason)
        return False

    @classmethod
    def _is_ui_thread(cls):
        import gremlin.util

        return gremlin.util.is_ui_thread()

    @classmethod
    def _call_on_ui_thread(cls, method, *args, **kwargs):
        import gremlin.util

        if cls._is_ui_thread():
            return method(*args, **kwargs)

        completed = threading.Event()
        result = []
        failure = []

        def invoke():
            try:
                result.append(method(*args, **kwargs))
            except BaseException as error:
                failure.append(error)
            finally:
                completed.set()

        gremlin.util.InvokeUiMethod(invoke)
        completed.wait()
        if failure:
            raise failure[0]
        return result[0] if result else None

    @classmethod
    def _wrap_ui_thread_call(cls, method):
        def invoke(*args, **kwargs):
            return cls._call_on_ui_thread(method, *args, **kwargs)

        return invoke

    @classmethod
    def shutdown(self):
        if not self._is_ui_thread():
            return self._call_on_ui_thread(self.shutdown)

        if self.vjoy_dll is not None:
            dll_handle = self.vjoy_dll._handle
            # use the correct kernel DLL for 64 bit
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel32.FreeLibrary.argtypes = [wintypes.HMODULE]
            kernel32.FreeLibrary(dll_handle)
            self.vjoy_dll = None
            syslog.info("VJOY: interface shutdown")
        self._reset_api()


