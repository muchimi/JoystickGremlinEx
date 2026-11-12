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


"""checks  maestro bridge availability and optionally install"""

import logging
import os
from pathlib import Path
import re
import winreg

import psutil
from PySide6 import QtCore, QtWidgets
from vjoy.vjoy_interface import VJoyInterface, VJoyState

syslog = logging.getLogger("system")
_BRIDGE_SERVICE = "GEXMaestroBridgeService"
_BRIDGE_SERVICE_KEY = rf"SYSTEM\CurrentControlSet\Services\{_BRIDGE_SERVICE}"
_BRIDGE_UNINSTALL_KEY = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1"
)


def _machine_key_exists(path):
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | view):  # @IgnoreException
                return True
        except OSError:
            pass
    return False


def vjoy_installed(config):
    """Require a responding driver and a defined device; registry data can be stale."""
    registered = bool(config.vjoy_installed or _machine_key_exists(r"SYSTEM\CurrentControlSet\Services\vjoy"))
    has_device = False  # assume not valid
    try:
        responding = bool(VJoyInterface.valid and VJoyInterface.vJoyEnabled())
        has_device = responding and any(
            VJoyInterface.GetVJDStatus(device_id)
            in (
                VJoyState.Owned.value,
                VJoyState.Free.value,
                VJoyState.Bust.value,
            )
            for device_id in range(1, 17)
        )
    except (OSError, RuntimeError) as error:
        syslog.info("VJOY: Not found: unable to query the driver")
        return False
    if registered and not responding:
        syslog.info("VJOY: Not found: No response")
    elif responding and not has_device:
        syslog.info("VJOY: Not found: no vJoy device configured")
    return has_device


def _machine_registry_value(path, name):
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | view) as key:
                value, kind = winreg.QueryValueEx(key, name)
                if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(value, str) and value.strip():
                    return os.path.expandvars(value.strip())
        except OSError:
            pass
    return ""


def bridge_installed(require_running=False):
    """Find a registered bridge, optionally requiring a running Windows service."""
    try:
        service = psutil.win_service_get(_BRIDGE_SERVICE)
        if require_running:
            return service.status() == "running"
        return True
    except psutil.NoSuchProcess, psutil.AccessDenied, OSError:
        if require_running:
            return False

    # Service ImagePath can contain a quoted executable followed by arguments.
    image_path = _machine_registry_value(_BRIDGE_SERVICE_KEY, "ImagePath")
    match = re.match(r'^\s*(?:"([^"]+\.exe)"|(.+?\.exe)(?:\s|$))', image_path, re.IGNORECASE)
    if match and Path(match.group(1) or match.group(2)).is_file():
        return True
    location = _machine_registry_value(_BRIDGE_UNINSTALL_KEY, "InstallLocation")
    return bool(location and (Path(location) / f"{_BRIDGE_SERVICE}.exe").is_file())


def install_bridge(parent=None):
    """Run the same download helper as setup, keeping the UI responsive."""
    helper = Path(__file__).resolve().parents[1] / "installer" / "dependencies.ps1"
    if not helper.is_file():
        raise OSError(f"Bridge installation helper is missing: {helper}")
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    progress = QtWidgets.QProgressDialog("Downloading and installing GEX Maestro Bridge...", "", 0, 0, parent)
    progress.setWindowTitle("GEX Maestro Bridge setup")
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
    process.start(
        str(powershell), ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper), "-Component", "bridge"]
    )
    progress.show()
    if not result:
        loop.exec()
    progress.close()
    output = bytes(process.readAllStandardOutput()).decode(errors="replace")
    if output:
        syslog.info(f"GEX BRIDGE SETUP: {output.strip()}")
    if process.error() == QtCore.QProcess.ProcessError.FailedToStart:
        raise OSError(process.errorString())
    return result[0]


def show_startup_ui(ui, config, maestro, vjoy_working):
    """Show the editor before reporting missing virtual output providers."""
    output_unavailable = not (
        vjoy_working or (not vjoy_installed(config) and maestro.enabled and maestro.service_running)
    )
    ui.apply_user_settings(ignore_minimize=output_unavailable)
    if output_unavailable or not config.startup_start_minimized:
        ui.showNormal()
    if output_unavailable:
        # Run after the main event loop starts, with a visible parent. A missing
        # driver must not leave startup at a standalone warning or in the tray.
        QtCore.QTimer.singleShot(0, ui, lambda: check_virtual_output(config, maestro, vjoy_working, parent=ui))


def _connect_maestro(config, maestro):
    """Retest the configured OSC endpoint instead of relying on startup flags."""
    try:
        if maestro.connect(throw_on_error=True) is not None:
            if not config.maestro_enabled:
                config.maestro_enabled = True
                syslog.info("MAESTRO: enabled automatically after a successful startup handshake")
            maestro.refreshDevices()
            return maestro.enabled and maestro.service_running
    except OSError, RuntimeError, ValueError:
        syslog.exception("Unable to connect to the configured Maestro bridge during startup")
    return False


def check_virtual_output(config, maestro, vjoy_working, parent=None):
    """Warn or offer setup when no provider is available; always allow startup."""
    if vjoy_working:
        return True
    if vjoy_installed(config):
        message = (
            "vJoy is installed, but no usable vJoy output was found. "
            "Enable the vJoy driver and configure its devices, then restart GEX. "
            "You can still edit profiles and use other outputs."
        )
        syslog.warning(message)
        QtWidgets.QMessageBox.warning(parent, "Virtual joystick output unavailable", message)
        return False
    if maestro.enabled and maestro.service_running:
        return True

    # The constructor may have run before the bridge was ready, or closed its
    # client after an inventory error. Confirm availability before warning.
    if _connect_maestro(config, maestro):
        return True

    message = (
        "No usable vJoy output or connected Maestro bridge was found. "
        "Virtual joystick output is unavailable; you can still edit profiles and use other outputs."
    )
    syslog.warning(message)
    bridge_present = bridge_installed()
    if not bridge_present:
        answer = QtWidgets.QMessageBox.question(
            parent,
            "Install GEX Maestro Bridge?",
            message + "\n\nDownload and install GEX Maestro Bridge for HIDMaestro virtual controllers? "
            "An Internet connection and elevated administrator rights are required for the Bridge installation.",
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
                QtWidgets.QMessageBox.information(
                    parent,
                    "Restart required",
                    "Bridge setup requires a Windows restart. Restart Windows before using Maestro output.",
                )
                return False
            if code == 1602:
                message = "Bridge installation was cancelled. Virtual joystick output remains unavailable."
            elif code != 0:
                message = f"Bridge installation failed (exit code {code}). You can install it later from the project releases."
            else:
                if _connect_maestro(config, maestro):
                    return True
                message = (
                    "Bridge setup finished, but the bridge is not connected. Start the bridge service and "
                    "check the connection and devices in Tools > Maestro Devices."
                )
        except (OSError, RuntimeError, ValueError) as error:
            syslog.exception("Unable to install or connect to GEX Maestro Bridge")
            message = f"Unable to install or connect to GEX Maestro Bridge: {error}"
    else:
        if bridge_present and config.maestro_use_localhost:
            if bridge_installed(require_running=True):
                message += (
                    "\n\nThe local GEX Maestro Bridge Windows service is running. "
                    "Enable Maestro and check the localhost address and service/reply ports in Tools > Maestro Devices."
                )
            else:
                message += (
                    "\n\nThe bridge is installed, but no running Windows service could be confirmed. "
                    "Start GEXMaestroBridgeService in Windows Services, or start the bridge in console mode. "
                    "Then test the connection in Tools > Maestro Devices."
                )
        else:
            message += "\n\nConfigure vJoy devices, or enable Maestro and check the bridge connection in Tools > Maestro Devices."
    QtWidgets.QMessageBox.warning(parent, "Virtual joystick output unavailable", message)
    return False
