"""Tests of the m77 update flow without installing anything."""

import hashlib
import io
import json
import os
import tempfile
import unittest
from concurrent.futures import CancelledError
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

from gremlin import update


def make_asset(version, suffix="", **overrides):
    name = f"GremlinEx-Setup-{version}{suffix}.exe"
    return {
        "name": name,
        "browser_download_url": update._ASSET_BASE + name,
        "state": "uploaded",
        "size": 100,
        **overrides,
    }


class UpdateTests(unittest.TestCase):
    def test_chooses_newest_revision_and_prefers_bundled_installer(self):
        release = {
            "tag_name": "m77_series",
            "assets": [
                make_asset("1.0ex-m77T99"),
                make_asset("1.0ex-m77T110"),
                make_asset("1.0ex-m77T110A", "-Online"),
                make_asset("1.0ex-m77T110A"),
                make_asset("1.0ex-m77T111", browser_download_url="https://example.org/installer.exe"),
                make_asset("1.0ex-m77T112", state="new"),
                make_asset("1.0ex-m78T1"),
                {"name": "gremlinEx_1_0_m77T113.zip"},
            ],
        }
        with patch.object(update, "build_opener") as opener:
            opener.return_value.open.side_effect = lambda *args, **kwargs: io.BytesIO(json.dumps(release).encode())
            selected = update.find_update("1.0ex-m77T110")
            self.assertEqual(selected.name, "GremlinEx-Setup-1.0ex-m77T110A.exe")
            self.assertIsNone(update.find_update("1.0ex-m77T110A"))
            self.assertIsNone(update.find_update("1.0ex-m77T112"))
            release["assets"].append(make_asset("1.0ex-m77T111", "-Online"))
            self.assertEqual(update.find_update("1.0ex-m77T110A").name, "GremlinEx-Setup-1.0ex-m77T111-Online.exe")

    def test_verified_installer_is_saved_and_failed_downloads_are_removed(self):
        content = b"MZ" + b"installer-data" * 30_000
        asset = make_asset("1.0ex-m77T111")
        installer = update.UpdateInstaller("1.0ex-m77T111", asset["name"], asset["browser_download_url"], len(content),
                                           f"sha256:{hashlib.sha256(content).hexdigest()}")
        with tempfile.TemporaryDirectory() as downloads, patch.object(update, "build_opener") as opener:
            opener.return_value.open.side_effect = lambda *args, **kwargs: io.BytesIO(content)
            progress = []
            path = update.download_installer(installer, downloads, Event(), progress.append)
            self.assertEqual(path.name, installer.name)
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(progress[-1], 100)

            cancelled = Event()
            with self.assertRaises(CancelledError):
                update.download_installer(installer, downloads, cancelled, lambda _: cancelled.set())
            for invalid in (content[:-1], content[:-1] + b"x"):
                opener.return_value.open.side_effect = None
                opener.return_value.open.return_value = io.BytesIO(invalid)
                with self.assertRaises(OSError):
                    update.download_installer(installer, downloads, Event(), lambda _: None)
            self.assertEqual(list(Path(downloads).iterdir()), [path.parent])

    def test_download_rejects_an_untrusted_redirect(self):
        redirects = update._GitHubRedirects(update._DOWNLOAD_HOSTS)
        for target in ("http://github.com/a", "https://github.com.example.org/a"):
            with self.assertRaises(OSError):
                redirects.redirect_request(update.Request(update._ASSET_BASE), None, 302, "", {}, target)

    def test_installer_launch_is_queued_with_the_current_process_and_path(self):
        path = Path(r"C:\Downloads\GEX's installer.exe")
        with patch.object(update.subprocess, "Popen") as launch:
            update.run_installer_after_exit(path)
        command = launch.call_args.args[0][-1]
        self.assertLess(command.index("WaitForExit"), command.index("Start-Process"))
        self.assertNotIn(str(path), command)
        self.assertEqual(launch.call_args.kwargs["env"]["GEX_UPDATE_INSTALLER"], str(path))
        self.assertEqual(launch.call_args.kwargs["env"]["GEX_UPDATE_PID"], str(os.getpid()))


class UpdateDialogTests(unittest.TestCase):
    def test_help_action_displays_results_through_shared_message_boxes(self):
        from PySide6 import QtCore, QtGui, QtWidgets

        import gremlin.base_profile
        from gremlin import version
        from gremlin.ui.update import UpdateController

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["update-dialog-test", "-platform", "offscreen"])
        window = QtWidgets.QWidget()
        self.addCleanup(window.close)
        action = QtGui.QAction("Check for Updates", window)
        controller = UpdateController(window, action, lambda: True, lambda: None)
        dialogs = []

        def dismiss_dialog():
            box = app.activeModalWidget()
            if isinstance(box, QtWidgets.QMessageBox):
                button = box.defaultButton()
                dialogs.append((box.text(), box.informativeText(), box.standardButton(button) if button else None))
                box.reject()

        timer = QtCore.QTimer(window)
        timer.timeout.connect(dismiss_dialog)
        timer.start(5)
        self.addCleanup(timer.stop)

        installer = update.UpdateInstaller("1.0ex-m77T999", "setup.exe", "https://github.com/example", 100, None)
        for result in (None, installer):
            with patch.object(update, "find_update", return_value=result):
                action.trigger()
                deadline = monotonic() + 2
                while (controller._checking or not action.isEnabled()) and monotonic() < deadline:
                    app.processEvents()
                    sleep(0.005)
                self.assertTrue(action.isEnabled())
                self.assertFalse(controller._checking)

        self.assertEqual(len(dialogs), 2)
        self.assertEqual(dialogs[0][:2], ("No updates available.", f"Installed version: GremlinEx {version.APPLICATION_VERSION}"))
        self.assertIn(installer.version, dialogs[1][0])
        self.assertEqual(dialogs[1][2], QtWidgets.QMessageBox.StandardButton.No)


if __name__ == "__main__":
    unittest.main()
