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


"""

processes command line parameters

"""

# # ruff: disable[E401]
from __future__ import annotations
import argparse
from PySide6 import QtCore, QtGui, QtWidgets
import os
import sys
import gremlin.util
from gremlin.ui.ui_common import MessageBoxWarning
import logging
import gremlin.shared_state

syslog = logging.getLogger("system")

class _MessageParser(argparse.ArgumentParser):
    """Argument parser that shows its output in a message box when there is no console (windowed build)."""

    def _print_message(self, message, file=None):
        if not message:
            return
        stream = file if file is not None else sys.stdout
        if stream is not None:
            super()._print_message(message, file)
            return
        import ctypes

        is_error = file is sys.stderr
        ctypes.windll.user32.MessageBoxW(0, message, "GremlinEx command line", 0x10 if is_error else 0x40)


class CommandLineProcessor:

    def process(self):
        """ process command line options and set configuration accordingly """


        config = gremlin.config.Configuration()
        parser = _MessageParser(prefix_chars='-/')
        app_path = gremlin.shared_state.data_path

        parser.add_argument("/no-profile", "/np", dest="no_profile", action=argparse.BooleanOptionalAction, help="Do not load a profile on start (--r and --p will be ignored)")
        parser.add_argument("/profile", "/p", dest="profile_file_name", default=None, help="Optional profile XML to load. Requires the profile xml to be provided.  If a path is not provided, GremlinEx will look for the profile file in the default profile folder.")
        parser.add_argument("/mousehook", "/mh", dest="mousehook", action=argparse.BooleanOptionalAction, help="Toggle mouse hook - diagnostics use only")
        parser.add_argument("/as", "/autoswitch", dest="switch", action=argparse.BooleanOptionalAction, help="Toggle automatic profile switching by process (if processes are mapped to profiles)")
        parser.add_argument("/autoload", "/al", dest = "load", action=argparse.BooleanOptionalAction, default=True, help="Toggle profile auto-load.  Enabled by default, loads the last used profile into GEX.")
        parser.add_argument("/r", "/run", dest="run", action=argparse.BooleanOptionalAction, help="Automatically start the last profile on launch if a profile is available.")
        parser.add_argument("/nr", dest="run", action="store_const", const=False, help="Do not automatically start the last profile on launch")
        parser.add_argument("/voice", "/v", dest="voice", action=argparse.BooleanOptionalAction, help="Toggle voice recognition module")
        parser.add_argument("/overlay", "/ov", dest="overlay", action=argparse.BooleanOptionalAction, help="Toggle overlay module")
        parser.add_argument("/streamdeck", "/sd", dest="streamdeck", action=argparse.BooleanOptionalAction, help="Toggle streamdeck module")
        parser.add_argument("/osc", dest="osc", action=argparse.BooleanOptionalAction, help="Toggle OSC (open stage control protocol) module")
        parser.add_argument("/midi", dest="midi", action=argparse.BooleanOptionalAction, help="Toggle MIDI module")
        parser.add_argument("/theme", dest="theme", choices=["dark", "light", "auto"], help="Set the application theme to dark, light or automatic mode")
        parser.add_argument("/help", "/h", "/?", action="help", help="Show this help message and exit")
        args, unknown_args = parser.parse_known_args()

        # hook mouse on/off
        if args.mousehook is not None:
            config.mouse_hook_disabled = not args.mousehook

        # voice module
        if args.voice is not None:
            config.voice_enabled = args.voice

        # overlay module
        if args.overlay is not None:
            config.overlay_enabled = args.overlay

        # streamdeck module
        if args.streamdeck is not None:
            config.streamdeck_enabled = args.streamdeck

        # osc module
        if args.osc is not None:
            config.osc_enabled = args.osc

        # midi module
        if args.midi is not None:
            config.midi_enabled = args.midi

        # start with a blank profile
        if args.no_profile is not None:
            config.no_profile = args.no_profile

        # auto start a profile (if a profile is available)
        if args.run is not None:
            # set automatic profile start based on --run argument
            config.run_on_start = bool(args.run)

        # autoload last profile
        if args.load is not None:
            config.auto_load_disabled = not args.load

        if args.no_profile:
            config.auto_load_disabled = True

        if config.auto_load_disabled:
            # tell GEX to stasrt with a new blank profile
            config.run_on_start = False
            config.profile_to_load = False

        profile_to_load = args.profile_file_name
        if not profile_to_load:
            # see if there is an xml provided in the unknown args without a /profile or /p parameter
            profile_specified = False
            for arg in unknown_args:
                if arg.casefold().endswith(".xml"):
                    profile_to_load = arg
                    break

        profile_specified = bool(profile_to_load)

        if profile_specified and not os.path.isfile(profile_to_load):
            profile_to_load = os.path.join(app_path, profile_to_load)
            if not os.path.isfile(profile_to_load):
                msg = f"Profile file not found: {profile_to_load}"
                MessageBoxWarning(msg)
                syslog.error(msg)
                os._exit(1)

        if profile_specified and not args.no_profile:
            config.profile_to_load = profile_to_load

        # theme
        if args.theme is not None:
            config.theme = args.theme