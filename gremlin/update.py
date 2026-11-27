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


"""Discover and download installers published on the GEX m77 release."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_REPOSITORY = "muchimi/JoystickGremlinEx"
_TAG = "m77_series"
_RELEASE_API = f"https://api.github.com/repos/{_REPOSITORY}/releases/tags/{_TAG}"
_ASSET_BASE = f"https://github.com/{_REPOSITORY}/releases/download/{_TAG}/"
_VERSION = r"(\d+)\.(\d+)(?:ex)?-m(77)(?:(RC|T)(\d+)([A-Za-z]*))?"
_INSTALLER = re.compile(rf"GremlinEx-Setup-({_VERSION})(-Online)?\.exe")
_DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


@dataclass(frozen=True)
class UpdateInstaller:
    version: str
    name: str
    url: str
    size: int
    digest: str | None


def _version_key(major, minor, milestone, kind, build, revision):
    return int(major), int(minor), int(milestone), {None: 2, "RC": 1, "T": 0}[kind], int(build or 0), (revision or "").upper()


def find_update(current_version):
    """Return the newest newer m77 setup, preferring a bundled setup at equal versions."""
    current = re.fullmatch(_VERSION, current_version)
    if not current:
        raise ValueError("Unrecognized m77 version")
    current_key = _version_key(*current.groups())
    request = Request(_RELEASE_API, headers={"User-Agent": "GremlinEx", "Accept": "application/vnd.github+json"})
    with build_opener(_GitHubRedirects({"api.github.com"})).open(request, timeout=8) as response:
        release = json.load(response)
    if not isinstance(release, dict) or release.get("tag_name") != _TAG or release.get("draft") or not isinstance(release.get("assets"), list):
        raise ValueError("Unexpected GitHub release response")

    selected = None
    selected_key = (current_key, True)
    for asset in release["assets"]:
        name = asset.get("name", "")
        match = _INSTALLER.fullmatch(name)
        if not match or asset.get("state") != "uploaded" or asset.get("browser_download_url") != _ASSET_BASE + name:
            continue
        size = asset.get("size")
        digest = asset.get("digest")
        if type(size) is not int or size < 2 or (digest and not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)):
            continue
        version, *fields, online = match.groups()
        key = (_version_key(*fields), online is None)
        if key > selected_key:
            selected_key = key
            selected = UpdateInstaller(version, name, _ASSET_BASE + name, size, digest)
    return selected


class _GitHubRedirects(HTTPRedirectHandler):
    def __init__(self, allowed_hosts):
        self._allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != "https" or target.hostname not in self._allowed_hosts or target.username or target.password:
            raise OSError("GitHub redirected to an unexpected download host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_installer(installer, downloads, cancelled, progress):
    """Stream into a partial file, then publish only the verified installer."""
    if cancelled.is_set():
        raise CancelledError()
    download_folder = Path(downloads)
    download_folder.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="GremlinEx-update-", dir=download_folder))
    partial = stage / "installer.part"
    destination = stage / installer.name
    digest = hashlib.sha256()
    received = 0
    previous_percent = -1
    try:
        request = Request(installer.url, headers={"User-Agent": "GremlinEx"})
        with build_opener(_GitHubRedirects(_DOWNLOAD_HOSTS)).open(request, timeout=15) as response, partial.open("xb") as output:
            while block := response.read(256 * 1024):
                if cancelled.is_set():
                    raise CancelledError()
                if received == 0 and not block.startswith(b"MZ"):
                    raise OSError("GitHub did not return a Windows executable")
                received += len(block)
                if received > installer.size:
                    raise OSError("The installer exceeded its published size")
                output.write(block)
                digest.update(block)
                percent = received * 100 // installer.size
                if percent != previous_percent:
                    progress(percent)
                    previous_percent = percent
        if cancelled.is_set():
            raise CancelledError()
        if received != installer.size:
            raise OSError("The installer download was incomplete")
        if installer.digest and f"sha256:{digest.hexdigest()}" != installer.digest.lower():
            raise OSError("The installer did not match GitHub's SHA-256 digest")
        partial.rename(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        stage.rmdir()
        raise
    return destination


def run_installer_after_exit(installer_path):
    """Start a helper which waits for the current GEX process before opening setup."""
    powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    environment = dict(os.environ, GEX_UPDATE_PID=str(os.getpid()), GEX_UPDATE_INSTALLER=str(installer_path))
    command = (
        "$gex = Get-Process -Id ([int]$env:GEX_UPDATE_PID) -ErrorAction SilentlyContinue; "
        "if ($null -ne $gex -and -not $gex.WaitForExit(60000)) { exit 1 }; "
        "Start-Process -FilePath $env:GEX_UPDATE_INSTALLER"
    )
    subprocess.Popen(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
