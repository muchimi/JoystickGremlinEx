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


""" checks  maestro bridge availability and optionally install """

import logging
import os
from pathlib import Path
import winreg

from PySide6 import QtCore, QtWidgets

syslog = logging.getLogger('system')


def _machine_key_exists(path):
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | view):
                return True
        except OSError:
            pass
    return False


def bridge_installed():
    """Include service and console installations at custom install locations."""
    if _machine_key_exists(r'SYSTEM\CurrentControlSet\Services\GEXMaestroBridgeService'):
        return True
    if _machine_key_exists(r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1'):
        return True
    program_files = os.environ.get('ProgramW6432') or os.environ.get('ProgramFiles')
    return bool(program_files and (Path(program_files) / 'GEXMaestroBridge' / 'GEXMaestroBridgeService.exe').is_file())


def install_bridge(parent=None):
    """Run the same download helper as setup, keeping the UI responsive."""
    helper = Path(__file__).resolve().parents[1] / 'installer' / 'dependencies.ps1'
    if not helper.is_file():
        raise OSError(f'Bridge installation helper is missing: {helper}')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    progress = QtWidgets.QProgressDialog('Downloading and installing GEX Maestro Bridge...', '', 0, 0, parent)
    progress.setWindowTitle('GEX Maestro Bridge setup')
    progress.setCancelButton(None)
    progress.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
    progress.setWindowFlag(QtCore.Qt.WindowType.WindowCloseButtonHint, False)
    process = QtCore.QProcess(progress)
    process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
    loop = QtCore.QEventLoop()
    result = []

    def finished(code, status):
        result.append(code if status == QtCore.QProcess.ExitStatus.NormalExit else 1)
        loop.quit()

    def failed(error):
        if error == QtCore.QProcess.ProcessError.FailedToStart:
            result.append(1)
            loop.quit()

    process.finished.connect(finished)
    process.errorOccurred.connect(failed)
    process.start(str(powershell), ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper), '-Component', 'bridge'])
    progress.show()
    if not result:
        loop.exec()
    progress.close()
    output = bytes(process.readAllStandardOutput()).decode(errors='replace')
    if output:
        syslog.info(f"GEX BRIDGE SETUP: {output.strip()}")
    if process.error() == QtCore.QProcess.ProcessError.FailedToStart:
        raise OSError(process.errorString())
    return result[0]


def check_virtual_output(config, maestro, vjoy_working, parent=None):
    """Warn or offer setup when no provider is available; always allow startup."""
    if vjoy_working or (maestro.enabled and maestro.service_running):
        return True

    message = ('No usable vJoy output or connected Maestro bridge was found. '
               'Virtual joystick output is unavailable; you can still edit profiles and use other outputs.')
    syslog.warning(message)
    if not config.vjoy_installed and not _machine_key_exists(r'SYSTEM\CurrentControlSet\Services\vjoy') and not bridge_installed():
        answer = QtWidgets.QMessageBox.question(
            parent, 'Install GEX Maestro Bridge?',
            message + '\n\nDownload and install GEX Maestro Bridge for HIDMaestro virtual controllers? '
            'An Internet connection and administrator approval are required.',
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return False
        try:
            code = install_bridge(parent)
            if code in (0, 3010, 1641):
                config.maestro_enabled = True
            if code in (3010, 1641):
                QtWidgets.QMessageBox.information(parent, 'Restart required',
                    'Bridge setup requires a Windows restart. Restart Windows before using Maestro output.')
                return False
            if code == 1602:
                message = 'Bridge installation was cancelled. Virtual joystick output remains unavailable.'
            elif code != 0:
                message = f'Bridge installation failed (exit code {code}). You can install it later from the project releases.'
            else:
                if maestro.connect() is not None:
                    maestro.refreshDevices()
                    if maestro.enabled and maestro.service_running:
                        return True
                message = ('Bridge setup finished, but the bridge is not connected. Start the bridge service and '
                           'check the connection and devices in Tools > Maestro Devices.')
        except (OSError, RuntimeError, ValueError) as error:
            syslog.exception('Unable to install or connect to GEX Maestro Bridge')
            message = f'Unable to install or connect to GEX Maestro Bridge: {error}'
    else:
        message += '\n\nConfigure vJoy devices, or enable Maestro and check the bridge connection in Tools > Maestro Devices.'
    QtWidgets.QMessageBox.warning(parent, 'Virtual joystick output unavailable', message)
    return False
