"""Deployment version checks without building or contacting GitHub.

Run: python tools/test_deploy_version.py
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from create_version import create_version_file, read_version_metadata
import upload_release


class DeployVersionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="Gremlin deploy checks ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.version_file = self.root / "gremlin" / "version.py"
        self.version_file.parent.mkdir()
        self.write_version("m77T93")

    def write_version(self, build):
        self.version_file.write_text(
            'raise RuntimeError("Do not import application startup")\n'
            'APPLICATION_NAME = "GremlinEx"\n'
            f'APPLICATION_BASE = "{build}"\n'
            'APPLICATION_MAIN = "1.0ex"\n'
            'APPLICATION_EXE = "gremlinex.exe"\n'
            'APPLICATION_VERSION = f"{APPLICATION_MAIN} ({APPLICATION_BASE})"\n',
            encoding="utf-8-sig",
        )

    def artifacts(self, build):
        assets = (
            self.root / "dist" / f"gremlinEx_1_0_{build}.zip",
            self.root / "dist" / "installer" / f"GremlinEx-Setup-1.0ex-{build}.exe",
        )
        for asset in assets:
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(b"test artifact")
        return assets

    def run_uploader(self, *arguments):
        select_assets = upload_release.build_assets
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", ["upload_release.py", *arguments]),
            patch.object(upload_release, "build_assets", side_effect=lambda: select_assets(self.root)),
            patch.object(upload_release, "github_token") as token,
            patch.object(upload_release, "GitHubRelease") as github,
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            result = upload_release.main()
        return result, output.getvalue(), errors.getvalue(), token, github

    def test_upload_selects_source_version_despite_stale_unpacked_executable(self):
        old_assets = self.artifacts("m77T92")
        expected = self.artifacts("m77T93")
        executable = self.root / "dist" / "gremlinEx" / "gremlinEx.exe"
        executable.parent.mkdir()
        executable.write_bytes(b"old or unreadable executable")
        self.assertEqual(upload_release.build_assets(self.root), expected)
        self.assertTrue(all(asset.exists() for asset in old_assets))

    def test_push_only_does_not_require_the_unpacked_executable(self):
        expected = self.artifacts("m77T93")
        self.assertEqual(upload_release.build_assets(self.root), expected)

    def test_missing_current_build_stops_before_credentials_or_github(self):
        self.artifacts("m77T92")
        result, _, errors, token, github = self.run_uploader()
        self.assertEqual(result, 1)
        self.assertIn("1.0ex (m77T93)", errors)
        self.assertIn("gremlinEx_1_0_m77T93.zip", errors)
        self.assertIn("GremlinEx-Setup-1.0ex-m77T93.exe", errors)
        self.assertIn("Run deploy.bat", errors)
        token.assert_not_called()
        github.assert_not_called()

    def test_empty_current_artifact_is_rejected(self):
        assets = self.artifacts("m77T93")
        assets[1].write_bytes(b"")
        with self.assertRaisesRegex(FileNotFoundError, "missing or empty"):
            upload_release.build_assets(self.root)

    def test_letter_suffix_is_preserved(self):
        self.write_version("m77T93A")
        expected = self.artifacts("m77T93A")
        self.assertEqual(upload_release.build_assets(self.root), expected)

    def test_other_release_series_is_rejected(self):
        self.write_version("m78T1")
        with self.assertRaisesRegex(ValueError, "Expected an M77 test build"):
            upload_release.build_assets(self.root)

    def test_preview_reports_both_artifacts_without_contacting_github(self):
        assets = self.artifacts("m77T93")
        result, output, errors, token, github = self.run_uploader("--check-assets")
        self.assertEqual(result, 0, errors)
        for asset in assets:
            self.assertIn(str(asset), output)
        token.assert_not_called()
        github.assert_not_called()

    def test_publish_receives_only_the_current_version(self):
        self.artifacts("m77T92")
        assets = self.artifacts("m77T93")
        result, _, errors, token, github = self.run_uploader()
        self.assertEqual(result, 0, errors)
        token.assert_called_once_with()
        client = github.return_value
        client.publish.assert_called_once_with(client.release.return_value, assets)

    def test_resource_and_upload_use_the_same_version_metadata(self):
        self.write_version("m77T93A")
        metadata = read_version_metadata(self.version_file)
        resource = create_version_file(self.root / "version.txt", self.version_file).read_text(encoding="utf-8")
        self.assertEqual(metadata["APPLICATION_VERSION"], "1.0ex (m77T93A)")
        self.assertIn("filevers=(1, 0, 77, 93)", resource)
        self.assertIn("StringStruct('ProductVersion', '1.0ex (m77T93A)')", resource)

    @unittest.skipUnless(os.name == "nt", "Windows batch script")
    def test_deploy_push_only_checks_current_source_version(self):
        for name in ("deploy.bat", "upload_release.py", "create_version.py"):
            shutil.copyfile(ROOT / name, self.root / name)
        self.artifacts("m77T92")
        environment = os.environ.copy()
        environment.update(PYTHON_EXE=sys.executable, GH_TOKEN="test-token", GITHUB_TOKEN="test-token")
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "deploy.bat", "--push-only"],
            cwd=self.root, env=environment, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("m77T93", result.stderr)
        self.assertIn("Run deploy.bat", result.stderr)
        self.assertIn("GitHub publishing failed", result.stdout)
        self.assertNotIn("Building GremlinEx executable", result.stdout)


if __name__ == "__main__":
    unittest.main()
