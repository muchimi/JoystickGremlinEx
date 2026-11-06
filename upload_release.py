"""Upload the current portable ZIP and installer to the M77 test release."""

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, urlencode

from create_version import read_version_metadata


ROOT = Path(__file__).resolve().parent
REPOSITORY = "muchimi/JoystickGremlinEx"
RELEASE_TAG = "m77_series"
RELEASE_URL = f"https://github.com/{REPOSITORY}/releases/tag/{RELEASE_TAG}"


def github_token() -> str:
    """Reuse an environment token or Git's configured credential helper."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if token := os.environ.get(name):
            return token

    environment = os.environ.copy()
    environment.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    result = subprocess.run(
        ["git", "credential", "fill"],
        input=f"protocol=https\nhost=github.com\npath={REPOSITORY}.git\n\n",
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
        cwd=ROOT,
    )
    credentials = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if result.returncode == 0 and credentials.get("password"):
        return credentials["password"]
    raise RuntimeError(
        "No GitHub credentials available. Sign in through Git Credential Manager, "
        "or set GH_TOKEN/GITHUB_TOKEN to a token with Contents read/write access to " + REPOSITORY
    )


class GitHubRelease:
    def __init__(self, token: str):
        self.token = token

    def request(self, method: str, path: str, *, asset: Path | None = None):
        """Stream large assets directly from disk, keeping credentials in headers."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "GremlinEx-Deploy",
        }
        host = "uploads.github.com" if asset is not None else "api.github.com"
        connection = http.client.HTTPSConnection(host, timeout=300, blocksize=1024 * 1024)
        try:
            if asset is None:
                connection.request(method, path, headers=headers)
            else:
                headers["Content-Type"] = "application/zip" if asset.suffix.lower() == ".zip" else "application/octet-stream"
                headers["Content-Length"] = str(asset.stat().st_size)
                with asset.open("rb") as stream:
                    connection.request(method, path, body=stream, headers=headers)
            response = connection.getresponse()
            body = response.read()
            try:
                data = json.loads(body) if body else None
            except json.JSONDecodeError:
                raise RuntimeError(f"GitHub {method} returned HTTP {response.status}: {response.reason}") from None
            if not 200 <= response.status < 300:
                message = data.get("message", response.reason) if isinstance(data, dict) else response.reason
                raise RuntimeError(f"GitHub {method} failed (HTTP {response.status}): {message}")
            return data
        finally:
            connection.close()

    def release(self) -> dict:
        release = self.request("GET", f"/repos/{REPOSITORY}/releases/tags/{quote(RELEASE_TAG, safe='')}")
        if release["tag_name"] != RELEASE_TAG or release["draft"] or not release["prerelease"]:
            raise ValueError(f"Expected the published M77 test prerelease: {RELEASE_URL}")
        if release.get("immutable"):
            raise ValueError("The M77 release is immutable and cannot accept new assets")
        return release

    def publish(self, release: dict, assets: tuple[Path, Path]) -> None:
        release_path = f"/repos/{REPOSITORY}/releases/{release['id']}/assets"
        existing = []
        page = 1
        while True:
            batch = self.request("GET", f"{release_path}?per_page=100&page={page}")
            existing.extend(batch)
            if len(batch) < 100:
                break
            page += 1

        for asset in assets:
            with asset.open("rb") as stream:
                digest = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
            matches = [item for item in existing if item["name"].casefold() == asset.name.casefold()]
            for item in matches:
                print(f"Replacing existing asset: {item['name']}", flush=True)
                self.request("DELETE", f"/repos/{REPOSITORY}/releases/assets/{item['id']}")
            print(f"Uploading {asset.name} ({asset.stat().st_size:,} bytes)...", flush=True)
            uploaded = self.request("POST", f"{release_path}?{urlencode({'name': asset.name})}", asset=asset)
            if uploaded["state"] != "uploaded" or uploaded["size"] != asset.stat().st_size:
                raise RuntimeError(f"GitHub did not finish uploading {asset.name}")
            if uploaded.get("digest") and uploaded["digest"] != digest:
                raise RuntimeError(f"GitHub checksum does not match {asset.name}")
            print(f"Uploaded: {uploaded['browser_download_url']}", flush=True)


def build_assets(root: Path = ROOT) -> tuple[Path, Path]:
    """Select the source version's artifacts, even when the unpacked EXE is older."""
    version = read_version_metadata(root / "gremlin" / "version.py")["APPLICATION_VERSION"]
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)ex \((m77T[0-9]+[A-Za-z]*)\)", version, re.IGNORECASE)
    if match is None:
        raise ValueError(f"Expected an M77 test build like '1.0ex (m77T92)', found {version!r}")
    major, minor, build = match.groups()
    filename_version = version.replace(" (", "-").replace(")", "")
    assets = (
        root / "dist" / f"gremlinEx_{major}_{minor}_{build}.zip",
        root / "dist" / "installer" / f"GremlinEx-Setup-{filename_version}.exe",
    )
    missing = [str(asset) for asset in assets if not asset.is_file() or asset.stat().st_size == 0]
    if missing:
        raise FileNotFoundError(
            f"Build artifacts for {version} are missing or empty: {', '.join(missing)}. "
            "Run deploy.bat to build this version before using --push-only."
        )
    return assets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument("--check", action="store_true", help="Check credentials and the target release without uploading")
    checks.add_argument("--check-assets", action="store_true", help="Check the source version's local artifacts without contacting GitHub")
    args = parser.parse_args()
    try:
        # Validate both artifacts before replacing anything on GitHub.
        assets = None if args.check else build_assets()
        if assets is not None:
            for asset in assets:
                print(f"Selected artifact: {asset}", flush=True)
        if args.check_assets:
            return 0
        github = GitHubRelease(github_token())
        release = github.release()
        if args.check:
            print(f"GitHub publishing target: {RELEASE_URL}")
        else:
            github.publish(release, assets)
            print(f"Published both build artifacts: {RELEASE_URL}")
    except (OSError, SyntaxError, NameError, ValueError, RuntimeError, subprocess.SubprocessError, http.client.HTTPException) as err:
        print(f"Unable to publish GremlinEx build: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
