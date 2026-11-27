"""Update prompts and background work for the GEX main window."""

import logging
from concurrent.futures import CancelledError
from pathlib import Path
from threading import Event, Thread

from PySide6 import QtCore, QtWidgets

from gremlin import update, version
from gremlin.ui.ui_common import MessageBoxInfo, MessageBoxWarning, MessageBoxYesNo


syslog = logging.getLogger("system")
_TITLE = "GremlinEx Updates"


class UpdateController(QtCore.QObject):
    _checked = QtCore.Signal(object, object)
    _downloaded = QtCore.Signal(object, object)
    _progress = QtCore.Signal(int)

    def __init__(self, window, action, prepare_to_close, close):
        super().__init__(window)
        self._window = window
        self._action = action
        self._prepare_to_close = prepare_to_close
        self._close = close
        self._checking = False
        self._manual = False
        self._dialog = None
        self._cancel = Event()
        self._checked.connect(self._show_result)
        self._downloaded.connect(self._offer_to_run)
        self._progress.connect(self._update_progress)
        action.triggered.connect(self.check_manually)
        QtCore.QCoreApplication.instance().aboutToQuit.connect(self._cancel.set)

    @QtCore.Slot()
    def check_manually(self):
        self.check(manual=True)

    def check(self, manual=False):
        if not self._action.isEnabled():
            return
        self._manual |= manual
        if self._checking:
            return
        self._checking = True
        current = f"{version.APPLICATION_MAIN}-{version.APPLICATION_BASE}"
        self._start_worker(self._checked, update.find_update, current)

    @staticmethod
    def _start_worker(signal, operation, *args):
        def run():
            try:
                result = operation(*args)
            except Exception as error:
                signal.emit(None, error)
            else:
                signal.emit(result, None)

        Thread(target=run, name="GEX update", daemon=True).start()

    @QtCore.Slot(object, object)
    def _show_result(self, installer, error):
        self._checking = False
        manual, self._manual = self._manual, False
        if error is not None:
            syslog.warning("Update check failed: %s", error)
        if not manual:
            if installer is not None:
                syslog.info("GremlinEx %s is available. Use Help > Check for Updates to download it.", installer.version)
            return

        self._action.setEnabled(False)
        try:
            if error is not None:
                MessageBoxWarning(title=_TITLE, prompt="Could not check GitHub for updates. Try again later.", parent=self._window)
            elif installer is None:
                MessageBoxInfo(
                    title=_TITLE,
                    prompt="No updates available.",
                    informative_text=f"Installed version: GremlinEx {version.APPLICATION_VERSION}",
                    parent=self._window,
                )
            else:
                MessageBoxYesNo(
                    title=_TITLE,
                    prompt=f"GremlinEx {installer.version} is available. Download the installer?",
                    informative_text=f"Current build {version.APPLICATION_VERSION}. Download size {installer.size / (1024 * 1024):,.0f} MiB.",
                    callback=lambda result: self._download(installer) if result == QtWidgets.QMessageBox.StandardButton.Yes else None,
                    parent=self._window,
                    default_button=QtWidgets.QMessageBox.StandardButton.No,
                )
        finally:
            if self._dialog is None:
                self._action.setEnabled(True)

    def _download(self, installer):
        downloads = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.DownloadLocation)
        self._cancel.clear()
        self._dialog = QtWidgets.QProgressDialog(f"Downloading {installer.name}", "Cancel", 0, 100, self._window)
        self._dialog.setWindowTitle(_TITLE)
        self._dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        self._dialog.setAutoClose(False)
        self._dialog.setAutoReset(False)
        self._dialog.canceled.connect(self._cancel.set)
        self._dialog.setValue(0)
        self._dialog.show()
        self._start_worker(self._downloaded, update.download_installer, installer, downloads or Path.home() / "Downloads", self._cancel, self._progress.emit)

    @QtCore.Slot(int)
    def _update_progress(self, percent):
        if self._dialog is not None and not self._cancel.is_set():
            self._dialog.setValue(percent)

    @QtCore.Slot(object, object)
    def _offer_to_run(self, path, error):
        self._dialog.hide()
        self._dialog.deleteLater()
        self._dialog = None
        try:
            if error is not None:
                if not isinstance(error, CancelledError):
                    syslog.warning("Update download failed: %s", error)
                    MessageBoxWarning(title=_TITLE, prompt="The installer download failed. Try checking for updates again.", parent=self._window)
            elif not self._cancel.is_set():
                MessageBoxYesNo(
                    title=_TITLE,
                    prompt="Close GremlinEx and run the downloaded installer?",
                    informative_text=f"Saved to {path}",
                    callback=lambda result: self._run_installer(path) if result == QtWidgets.QMessageBox.StandardButton.Yes else None,
                    parent=self._window,
                    default_button=QtWidgets.QMessageBox.StandardButton.No,
                )
        finally:
            self._action.setEnabled(True)

    def _run_installer(self, path):
        try:
            if not self._prepare_to_close():
                return
            update.run_installer_after_exit(path)
        except Exception as error:
            syslog.warning("Could not prepare to install the update: %s", error)
            MessageBoxWarning(title=_TITLE, prompt="GremlinEx could not start the installer.", informative_text=f"Saved to {path}", parent=self._window)
            return
        self._close()
