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
"""Windows delivery and lifecycle regressions without sending real input."""

import ast
import ctypes
import importlib.util
import logging
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from lxml import etree
from PySide6 import QtCore


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin.input_types import InputType
from gremlin.types import KeyboardOutputMode, SyncMode


class FunctorBase:
    def __init__(self, action, parent=None):
        self.action_data = action

    @property
    def profile_mode(self):
        return self.action_data.get_mode()


PLUGIN_DIR = ROOT / "action_plugins" / "map_to_application"
spec = importlib.util.spec_from_file_location("win32_core", PLUGIN_DIR / "win32_core.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
services = SimpleNamespace(
    base_profile=SimpleNamespace(AbstractFunctor=FunctorBase), input_item=SimpleNamespace(AbstractAction=object),
    event_handler=SimpleNamespace(EventListener=None, Event=lambda *args, **kwargs: SimpleNamespace(**kwargs)),
    config=SimpleNamespace(Configuration=lambda: SimpleNamespace(verbose_mode_keyboard=False)),
    joystick_handling=SimpleNamespace(get_button=None), shared_state=SimpleNamespace(current_profile=None),
)
plugin = SimpleNamespace(
    core=core, gremlin=services, math=math, syslog=logging.getLogger("application-checks"), QtCore=QtCore,
    InputType=InputType, KeyboardOutputMode=KeyboardOutputMode, SyncMode=SyncMode, MapToApplicationWidget=object,
    Path=Path,
)
source = PLUGIN_DIR / "__init__.py"
nodes = [node for node in ast.parse(source.read_bytes()).body
         if getattr(node, "name", None) in ("_num", "_load_application_presets", "MapToApplicationFunctor", "MapToApplication")
         or isinstance(node, ast.Assign)
         and any(getattr(target, "id", None) in ("PLUGIN_PRESETS_FOLDER", "USER_PRESETS_FILENAME") for target in node.targets)]
plugin.__file__ = str(source)
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), vars(plugin))

KEY_A = (65, 30, False)
KEY_B = (66, 48, False)


class PresetTests(unittest.TestCase):
    def test_bundled_legacy_and_sidecar_presets_merge_on_each_load(self):
        with TemporaryDirectory() as temporary:
            profile = Path(temporary)
            bundled = profile / "presets"
            user = profile / "gex_apps"
            sidecar = profile / "map_to_application.ini"
            user.mkdir()
            (user / "Shared.ini").write_text("[app]\nprogram = user.exe\n", encoding="utf-8")

            with (
                patch.object(plugin, "PLUGIN_PRESETS_FOLDER", bundled),
                patch.object(core, "presets_folder", return_value=user),
                patch.object(core, "gex_user_folder", return_value=profile),
            ):
                self.assertEqual(list(plugin._load_application_presets(warn=False)), ["Shared"])

                bundled.mkdir()
                (bundled / "Bundled.ini").write_text("[app]\nprogram = bundled.exe\n", encoding="utf-8")
                (bundled / "Shared.ini").write_text("[app]\nprogram = default.exe\n", encoding="utf-8")
                (bundled / "_Example.ini").write_text("[app]\nprogram = example.exe\n", encoding="utf-8")

                presets = plugin._load_application_presets(warn=True)
                self.assertEqual(list(presets), ["Bundled", "Shared"])
                self.assertEqual(presets["Bundled"].program, "bundled.exe")
                self.assertEqual(presets["Shared"].program, "user.exe")

                sidecar.write_text(
                    "[App: Shared]\nprogram = custom.exe\n"
                    "[Functions: shared]\nSave = ctrl+s [focus]\nInvalid = not-a-key\n"
                    "[app: Another App]\nprogram = another.exe\n"
                    "[functions: Another App]\nHelp = F1\n"
                    "[functions: Unknown App]\nIgnored = f2\n",
                    encoding="utf-8-sig",
                )

                with self.assertLogs(core.log, level="WARNING") as logs:
                    presets = plugin._load_application_presets(warn=True)
                self.assertIn("preset Shared: 'Invalid = not-a-key' skipped", logs.output[0])
                self.assertEqual(list(presets), ["Another App", "Bundled", "Shared"])
                self.assertEqual(presets["Shared"].path, sidecar)
                self.assertEqual(presets["Shared"].program, "custom.exe")
                save, = presets["Shared"].functions
                self.assertEqual((save.name, save.value, save.option), ("Save", "ctrl+s", "focus"))
                self.assertEqual(presets["Another App"].function("Help").value, "F1")

                sidecar.unlink()
                self.assertEqual(plugin._load_application_presets(warn=False)["Shared"].program, "user.exe")


class DeliveryTests(unittest.TestCase):
    def test_separate_holds_send_releases_to_their_own_children(self):
        with (
            patch.object(core, "_held", {}),
            patch.object(core, "_u32", IsolatedWindows()),
            patch.object(core, "main_window", side_effect=[(1, 10), (1, 10), (4, 40), (4, 40)]),
            patch.object(core, "key_target", side_effect=[2, 3]),
            patch.object(core, "_post_keys", return_value=True) as post,
        ):
            core.window_send("target.exe", "", [KEY_A], True, False)
            core.window_send("target.exe", "", [KEY_B], True, False)
            self.assertEqual(core.window_send("target.exe", "", [KEY_A], False, True), "")
            self.assertEqual(core.window_send("target.exe", "", [KEY_B], False, True), "")
            self.assertEqual(post.call_args_list, [
                call(2, [KEY_A], True, False, False), call(3, [KEY_B], True, False, False),
                call(2, [KEY_A], False, True, False), call(3, [KEY_B], False, True, False),
            ])

    def test_mouse_pulse_preserves_an_existing_hold(self):
        points = [core._P(1, 1), core._P(2, 2)]
        with (
            patch.object(core, "_held", {}),
            patch.object(core, "_u32", IsolatedWindows()),
            patch.object(core, "main_window", return_value=(1, 10)),
            patch.object(core, "mouse_point", side_effect=points),
            patch.object(core, "child_at", side_effect=[(2, points[0]), (3, points[1])]),
            patch.object(core, "_post", return_value=True) as post,
        ):
            hold_id = object()
            core.window_send("target.exe", "", ["mouse:left"], True, False, hold_id=hold_id)
            core.window_send("target.exe", "", ["mouse:left"])
            core.window_send("target.exe", "", ["mouse:left"], False, True, hold_id=hold_id)
            up_message = core.MOUSE_BUTTONS["left"][1]
            self.assertEqual([args.args[0] for args in post.call_args_list if args.args[1] == up_message], [3, 2])
            self.assertFalse(core._held)

    def test_focus_reports_win32_send_input_failure(self):
        windows = IsolatedWindows()
        windows.SendInput.return_value = 0
        with patch.object(core, "_u32", windows), patch.object(core, "main_window", return_value=(1, 10)):
            self.assertEqual(core.deliver("target.exe", "", "focus", [KEY_A]), (False, core.REFUSED))
        self.assertEqual(windows.SendInput.call_count, 2)

    def test_focus_reacquires_target_for_release_then_restores_new_window(self):
        windows = IsolatedWindows()
        sent = []

        def send(count, pointer, size):
            flags = ctypes.cast(pointer, ctypes.POINTER(core._INPUT)).contents.u.ki.dwFlags
            sent.append((windows.foreground, bool(flags & 2)))
            return 1

        def sleep(seconds):
            if seconds == 0.05:
                windows.foreground = 2

        windows.SendInput.side_effect = send
        with (
            patch.object(core, "_u32", windows),
            patch.object(core, "main_window", return_value=(1, 10)),
            patch.object(core, "activate", side_effect=windows.activate) as activate,
            patch.object(core.time, "sleep", side_effect=sleep),
        ):
            self.assertEqual(core.deliver("target.exe", "", "focus", [KEY_A]), (True, ""))
        self.assertEqual(sent, [(1, False), (1, True)])
        self.assertEqual(activate.call_args_list, [call(1), call(2)])


class IsolatedWindows:
    def __init__(self):
        self.foreground = 1
        self.SendInput = Mock(return_value=1)

    def GetForegroundWindow(self):
        return self.foreground

    def IsWindow(self, hwnd):
        return bool(hwnd)

    def activate(self, hwnd):
        self.foreground = hwnd
        return True


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.events = SimpleNamespace(profile_hook=Mock(), profile_unhook=Mock(), autorepeat_clear=Mock())
        events = patch.object(plugin.gremlin.event_handler, "EventListener", return_value=self.events)
        events.start()
        self.addCleanup(events.stop)
        self.action = SimpleNamespace(
            name="Map to Application", id="test", mode=plugin.KeyboardOutputMode.Hold,
            sync_mode=plugin.SyncMode.Input, get_mode=lambda: "Default", items=[KEY_A],
            hardware_device_guid="test", hardware_input_id=1, get_input_type=lambda: plugin.InputType.JoystickButton,
            function_kind="key", uia_name="", delivery="window", exec_on_press=True, exec_on_release=False,
        )
        self.functor = plugin.MapToApplicationFunctor(self.action)
        self.functor._send = Mock(side_effect=lambda down, up: setattr(self.functor, "_down", down and not up))

    def test_startup_hold_survives_initial_mode_change_and_releases_later(self):
        profile = SimpleNamespace(get_mode_ancestors=lambda mode, include_self: [mode])
        with (
            patch.object(plugin.gremlin.shared_state, "current_profile", profile),
            patch.object(plugin.gremlin.joystick_handling, "get_button", return_value=True) as get_button,
        ):
            self.functor.profile_start()
            get_button.assert_not_called()
            self.functor.profile_mode_changed("Default")
            self.assertEqual(self.functor._send.call_args_list, [call(True, False)])
            self.functor.profile_mode_changed("Other")
            self.assertEqual(self.functor._send.call_args_list, [call(True, False), call(False, True)])
            self.functor._send.reset_mock()
            self.functor.profile_start()
            self.functor.profile_mode_changed("Other")
            self.functor._send.assert_not_called()

    def test_empty_release_runs_autorepeat_clear(self):
        self.action.mode = plugin.KeyboardOutputMode.Release
        self.action._items = self.action.items = []
        self.assertTrue(plugin.MapToApplication.hasOutput(self.action))
        self.functor.process_event(SimpleNamespace(is_pressed=True), None)
        self.events.autorepeat_clear.emit.assert_called_once_with()

    def test_nonfinite_xml_attributes_use_defaults(self):
        node = etree.Element("action", delay="inf", click_x="NaN", interval="1e999")
        self.assertEqual(plugin._num(node, "delay", int, 250), 250)
        self.assertEqual(plugin._num(node, "click_x", float, 50.0), 50.0)
        self.assertEqual(plugin._num(node, "interval", int, 250), 250)


if __name__ == "__main__":
    unittest.main()
