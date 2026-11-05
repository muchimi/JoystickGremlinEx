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
from PySide6 import QtWidgets
import os
from pathlib import Path
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

    def show_command_line_help(self):
        help_path = Path(__file__).resolve().parent.parent / "command_line.md"
        try:
            help_text = help_path.read_text(encoding="utf-8")
        except OSError as err:
            syslog.error(f"Unable to read command-line help file '{help_path}': {err}")
            self.exit(1, f"Unable to read command-line help file: {err}\n")

        if sys.stdout is not None:
            sys.stdout.write(help_text)
            return

        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication(sys.argv)

        dialog = QtWidgets.QDialog()
        dialog.setWindowTitle("GremlinEx Command-line Help")
        dialog.resize(760, 600)
        layout = QtWidgets.QVBoxLayout(dialog)
        help_view = QtWidgets.QTextBrowser(dialog)
        help_view.setMarkdown(help_text)
        layout.addWidget(help_view)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()


class _CommandLineHelpAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        parser.show_command_line_help()
        parser.exit()


class CommandLineProcessor:

    def process(self):
        """ process command line options and set configuration accordingly """


        config = gremlin.config.Configuration()
        parser = _MessageParser(prefix_chars='-/')
        app_path = gremlin.shared_state.data_path

        parser.add_argument("/no-profile", "/np", dest="no_profile", action="store_true", default=None, help="Do not load a profile on start (--r and --p will be ignored)")
        parser.add_argument("/profile", "/p", dest="profile_file_name", default=None, help="Optional profile XML to load. Requires the profile xml to be provided.  If a path is not provided, GremlinEx will look for the profile file in the default profile folder.")
        parser.add_argument("/mousehook", "/mh", dest="mousehook", action="store_true", default=None, help="Enable mouse hook - diagnostics use only (disable with /no-mousehook)")
        parser.add_argument("/no-mousehook", "/no-mh", "--no-mousehook", dest="mousehook", action="store_false", default=None, help=argparse.SUPPRESS)
        parser.add_argument("/as", "/autoswitch", dest="switch", action="store_true", default=None, help="Enable automatic profile switching by process (disable with /no-as)")
        parser.add_argument("/no-as", "/no-autoswitch", "--no-as", "--no-autoswitch", dest="switch", action="store_false", default=None, help=argparse.SUPPRESS)
        parser.add_argument("/autoload", "/al", dest="load", action="store_true", default=None, help="Load the last used profile on startup (disable with /no-autoload)")
        parser.add_argument("/no-autoload", "/no-al", "--no-autoload", dest="load", action="store_false", default=None, help=argparse.SUPPRESS)
        parser.add_argument("/r", "/run", dest="run", action="store_true", default=None, help="Automatically start the last profile on launch if a profile is available.")
        parser.add_argument("/nr", "/no-r", "/no-run", "--no-r", "--no-run", dest="run", action="store_false", default=None, help="Do not automatically start the last profile on launch")
        parser.add_argument("/voice", "/v", dest="voice", action="store_true", default=None, help="Enable voice recognition module (disable with /no-voice)")
        parser.add_argument("/no-voice", "/no-v", "--no-voice", dest="voice", action="store_false", default=None, help=argparse.SUPPRESS)
        parser.add_argument("/overlay", "/ov", dest="overlay", action="store_true", default=None, help="Enable overlay module (disable with /no-overlay)")
        parser.add_argument("/no-overlay", "/no-ov", "--no-overlay", dest="overlay", action="store_false", default=None, help=argparse.SUPPRESS)
        parser.add_argument("/streamdeck", "/sd", dest="streamdeck", action="store_true", default=None, help="Enable streamdeck module (disable with /no-streamdeck)")
        parser.add_argument("/no-streamdeck", "/no-sd", "--no-streamdeck", dest="streamdeck", action="store_false", default=None, help=argparse.SUPPRESS)
        parser.add_argument("/osc", dest="osc", action="store_true", default=None, help="Enable OSC (open stage control protocol) module (disable with /no-osc)")
        parser.add_argument("/no-osc", "--no-osc", dest="osc", action="store_false", default=None, help=argparse.SUPPRESS)
        parser.add_argument("/midi", dest="midi", action="store_true", default=None, help="Enable MIDI module (disable with /no-midi)")
        parser.add_argument("/no-midi", "--no-midi", dest="midi", action="store_false", default=None, help=argparse.SUPPRESS)
        parser.add_argument("/theme", dest="theme", choices=["dark", "light", "auto"], help="Set the application theme to dark, light or automatic mode")
        parser.add_argument("/help", "/h", "/?", action=_CommandLineHelpAction, nargs=0, help="Show command-line documentation and exit")
        parser.add_argument("/min", "/m", dest="minimize", action="store_true", default=None, help="Start minimized to tray (override with /no-min)")
        parser.add_argument("/no-min", "--no-min", dest="minimize", action="store_false", default=None, help=argparse.SUPPRESS)
        parser.add_argument("/persist", dest="persist", action="store_true", help="Persist command line options as default for future launches")
        args, unknown_args = parser.parse_known_args()

        def set_option(name, value, startup_name=None):
            # depending on the persistent flag, set the global options or the temporary startup options
            if value is not None:
                setattr(config, name if args.persist else startup_name or f"startup_{name}", value)

        set_option("mouse_hook_disabled", None if args.mousehook is None else not args.mousehook)
        set_option("voice_enabled", args.voice)
        set_option("overlay_enabled", args.overlay)
        set_option("streamdeck_enabled", args.streamdeck)
        set_option("osc_enabled", args.osc)
        set_option("midi_enabled", args.midi)
        set_option("autoload_profiles", args.switch, "startup_autoload_profiles")

        # auto start a profile (if a profile is available)
        if args.run is not None:
            set_option("run_on_start", bool(args.run), "startup_run_on_start")

        # Auto-load the last profile is a separate startup behavior from process switching.
        if args.load is not None:
            set_option("autoload_last_profile", args.load, "startup_autoload_last_profile")

        if args.no_profile is not None:
            if args.persist:
                config.autoload_last_profile = not args.no_profile
            config.startup_auto_load_disabled = args.no_profile

        if not args.persist and (config.startup_auto_load_disabled or args.load is False):
            config.startup_run_on_start = False

        set_option("start_minimized", args.minimize)

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
            config.startup_profile_to_load = profile_to_load
            if args.persist:
                config.last_profile = profile_to_load

        # theme
        set_option("theme", args.theme)