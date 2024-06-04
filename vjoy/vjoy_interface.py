# -*- coding: utf-8; -*-

# Copyright (C) 2015 - 2019 Lionel Ott - Modified by Muchimi (C) EMCS 2024 and other contributors
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
from gremlin.error import GremlinError
import logging

class VJoyState(enum.Enum):

    """Enumeration of the possible VJoy device states."""

    Owned = 0       # The device is owned by the current application
    Free = 1        # The device is not owned by any application
    Bust = 2        # The device is owned by another application
    Missing = 3     # The device is not present
    Unknown = 4     # Unknown type of error


class VJoyInterface:

    """Allows low level interaction with VJoy devices via ctypes."""

    vjoy_dll = None


    # Declare argument and return types for all the functions
    # exposed by the dll
    api_functions = {
        # General vJoy information
        "GetvJoyVersion": {
            "arguments": [],
            "returns": ctypes.c_short
        },
        "vJoyEnabled": {
            "arguments": [],
            "returns": ctypes.c_bool
        },
        "GetvJoyProductString": {
            "arguments": [],
            "returns": ctypes.c_wchar_p
        },
        "GetvJoyManufacturerString": {
            "arguments": [],
            "returns": ctypes.c_wchar_p
        },
        "GetvJoySerialNumberString": {
            "arguments": [],
            "returns": ctypes.c_wchar_p
        },

        # Device properties
        "GetVJDButtonNumber": {
            "arguments": [ctypes.c_uint],
            "returns": ctypes.c_int
        },
        "GetVJDDiscPovNumber": {
            "arguments": [ctypes.c_uint],
            "returns": ctypes.c_int
        },
        "GetVJDContPovNumber": {
            "arguments": [ctypes.c_uint],
            "returns": ctypes.c_int
        },
        # API claims this should return a bool, however, this is untrue and
        # is an int, see:
        # http://vjoystick.sourceforge.net/site/index.php/forum/5-Discussion/1026-bug-with-getvjdaxisexist
        "GetVJDAxisExist": {
            "arguments": [ctypes.c_uint, ctypes.c_uint],
            "returns": ctypes.c_int
        },
        "GetVJDAxisMax": {
            "arguments": [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p],
            "returns": ctypes.c_bool
        },
        "GetVJDAxisMin": {
            "arguments": [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p],
            "returns": ctypes.c_bool
        },

        # Device management
        "GetOwnerPid": {
            "arguments": [ctypes.c_uint],
            "returns": ctypes.c_int
        },
        "AcquireVJD": {
            "arguments": [ctypes.c_uint],
            "returns": ctypes.c_bool
        },
        "RelinquishVJD": {
            "arguments": [ctypes.c_uint],
            "returns": None,
        },
        "UpdateVJD": {
            "arguments": [ctypes.c_uint, ctypes.c_void_p],
            "returns": ctypes.c_bool
        },
        "GetVJDStatus": {
            "arguments": [ctypes.c_uint],
            "returns": ctypes.c_int
        },

        # Reset functions
        "ResetVJD": {
            "arguments": [ctypes.c_uint],
            "returns": ctypes.c_bool
        },
        "ResetAll": {
            "arguments": [],
            "returns": None
        },
        "ResetButtons": {
            "arguments": [ctypes.c_uint],
            "returns": ctypes.c_bool
        },
        "ResetPovs": {
            "arguments": [ctypes.c_uint],
            "returns": ctypes.c_bool
        },

        # Set values
        "SetAxis": {
            "arguments": [ctypes.c_long, ctypes.c_uint, ctypes.c_uint],
            "returns": ctypes.c_bool
        },
        "SetBtn": {
            "arguments": [ctypes.c_bool, ctypes.c_uint, ctypes.c_ubyte],
            "returns": ctypes.c_bool
        },
        "SetDiscPov": {
            "arguments": [ctypes.c_int, ctypes.c_uint, ctypes.c_ubyte],
            "returns": ctypes.c_bool
        },
        "SetContPov": {
            "arguments": [ctypes.c_ulong, ctypes.c_uint, ctypes.c_ubyte],
            "returns": ctypes.c_bool
        },
    }

    @classmethod
    def initialize(self):
        """Initializes the functions as class methods."""
        from pathlib import Path
        from gremlin.util import display_error, get_dll_version, version_valid, get_vjoy_driver_version

        if VJoyInterface.vjoy_dll is None:

            dll_folder = os.path.dirname(__file__)
            dll_file = "vJoyInterface.dll"
            _dll_path = os.path.join(dll_folder, dll_file )
            if not os.path.isfile(_dll_path):

                # look one level up for packaging in 3.12
                parent = Path(dll_folder).parent
                _dll_path = os.path.join(parent, dll_file)
                if not os.path.isfile(_dll_path):
                    msg = f"Unable to continue - missing dll: {_dll_path}"
                    display_error(msg)
                    logging.getLogger("system").critical(msg)
                    os._exit(1) 

            # check vjoy driver version and that it's installed
            driver_version = get_vjoy_driver_version()
            if driver_version:
                min_version = "12.53.21.621"
                if not version_valid(driver_version, min_version):
                    msg = f"Invalid VJOY driver: {min_version} required, found {driver_version}"
                    display_error(msg)
                    logging.getLogger("system").critical(msg)
                    os._exit(1) 

                logging.getLogger("system").info(f"Found VJOY driver {driver_version}")
            else:
                # no driver
                msg = f"VJOY driver not detected - unable to continue - expecting version {min_version}"
                display_error(msg)
                logging.getLogger("system").critical(msg)
                os._exit(1)             


            # check DLL version                
            min_version = "2.1.9.1"
            dll_version = get_dll_version(_dll_path)
            if not version_valid(dll_version, min_version):
                msg = f"Invalid version dll: {_dll_path}\nVersion {min_version} required, found {dll_version}"
                display_error(msg)
                logging.getLogger("system").critical(msg)
                os._exit(1)

            logging.getLogger("system").info(f"Found VJOY DLL version {dll_version}")

            try:
                VJoyInterface.vjoy_dll = ctypes.cdll.LoadLibrary(_dll_path)
            except Exception as error:
                msg = f"vjoy_interface.dll load error, unable to continue:\n{error}"
                display_error(msg)
                logging.getLogger("system").critical(msg)
                os._exit(1)


        for fn_name, params in self.api_functions.items():
            dll_fn = getattr(self.vjoy_dll, fn_name)
            if "arguments" in params:
                dll_fn.argtypes = params["arguments"]
            if "returns" in params:
                dll_fn.restype = params["returns"]
            setattr(self, fn_name, dll_fn)


