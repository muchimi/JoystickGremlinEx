"""FFmpeg discovery and real pydub conversion without audio devices or downloads.

Run: python -m pytest tools/test_ffmpeg.py tools/test_audio_devices.py -q
"""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gremlin import ffmpeg  # noqa: E402


class FFmpegTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gremlin audio ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.converter = NS(converter="old-ffmpeg")
        patches = (
            patch.dict(os.environ, {"PATH": ""}),
            patch.object(ffmpeg, "__file__", str(self.root / "gremlin" / "ffmpeg.py")),
            patch.object(sys, "frozen", False, create=True),
            patch.dict(sys.modules, {"pydub.audio_segment": NS(AudioSegment=self.converter)}),
        )
        for context in patches:
            context.start()
            self.addCleanup(context.stop)

    def tools(self, directory, probe=True):
        directory.mkdir(parents=True, exist_ok=True)
        suffix = ".exe" if os.name == "nt" else ""
        encoder = directory / f"ffmpeg{suffix}"
        encoder.write_bytes(b"test executable")
        if probe:
            (directory / f"ffprobe{suffix}").write_bytes(b"test executable")
        return str(encoder.resolve())

    def sound(self):
        source = next(node for node in ast.parse((ROOT / "gremlin/sound.py").read_bytes()).body
                      if getattr(node, "name", None) == "Sound")
        source.decorator_list = []
        source.body = [node for node in source.body if getattr(node, "name", None) in {
            "ensureFFmpeg", "convertMp3ToWav_pydub",
        }]
        namespace = dict(configure_ffmpeg=ffmpeg.configure_ffmpeg, os=os, syslog=Mock(),
                         AudioSegment=Mock())
        module = ast.Module(body=[source], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), "gremlin/sound.py", "exec"), namespace)
        sound = namespace["Sound"]()
        sound._ffmpeg_exe = None
        sound._ffmpeg_download_dir = Mock(return_value=str(self.root / "cache" / "ffmpeg"))
        sound._downloadFFmpeg = Mock(return_value=None)
        return sound, namespace

    def test_source_tools_are_found_independently_of_main_module_or_cwd(self):
        expected = self.tools(self.root / "ffmpeg")
        with patch.object(sys.modules["__main__"], "__file__", "unrelated_launcher.py", create=True):
            self.assertEqual(ffmpeg.configure_ffmpeg(), expected)
        self.assertEqual(self.converter.converter, expected)
        self.assertEqual(os.environ["PATH"], str(self.root / "ffmpeg"))

    def test_packaged_and_installer_layouts_work(self):
        for subdir in ("_internal", "ffmpeg", "ffmpeg/bin", "tools/ffmpeg/bin"):
            with self.subTest(subdir=subdir):
                app = self.root / subdir.replace("/", "-")
                expected = self.tools(app / subdir)
                with patch.object(sys, "frozen", True), patch.object(sys, "executable", str(app / "gremlinEx.exe")):
                    self.assertEqual(ffmpeg.configure_ffmpeg(), expected)

    def test_pyinstaller_extraction_directory_is_used(self):
        bundle = self.root / "onefile bundle"
        expected = self.tools(bundle)
        with patch.object(sys, "frozen", True), patch.object(sys, "_MEIPASS", str(bundle), create=True):
            self.assertEqual(ffmpeg.configure_ffmpeg(), expected)

    def test_existing_download_is_reused_without_network(self):
        sound, _ = self.sound()
        expected = self.tools(Path(sound._ffmpeg_download_dir()))
        sound._ffmpeg_exe = str(self.root / "deleted ffmpeg.exe")
        self.assertTrue(sound.ensureFFmpeg())
        self.assertEqual(sound._ffmpeg_exe, expected)
        self.assertEqual(self.converter.converter, expected)
        sound._downloadFFmpeg.assert_not_called()

    def test_path_fallback_exposes_probe_from_a_separate_directory(self):
        expected = self.tools(self.root / "system encoder", probe=False)
        self.tools(self.root / "system probe")
        probe = self.root / "system probe" / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        with patch.object(ffmpeg, "_tool_directories", return_value=[]), patch.object(
            ffmpeg.shutil, "which", side_effect=lambda name: expected if name == "ffmpeg" else str(probe),
        ):
            self.assertEqual(ffmpeg.configure_ffmpeg(), expected)
        self.assertEqual(os.environ["PATH"].split(os.pathsep), [str(self.root / "system encoder"), str(probe.parent)])

    def test_repeated_configuration_does_not_duplicate_path_entries(self):
        expected = self.tools(self.root / "ffmpeg")
        os.environ["PATH"] = os.pathsep.join([str(self.root / "other"), str(self.root / "ffmpeg")])
        for _ in range(3):
            self.assertEqual(ffmpeg.configure_ffmpeg(), expected)
        self.assertEqual(os.environ["PATH"].split(os.pathsep), [str(self.root / "ffmpeg"), str(self.root / "other")])

    def test_downloaded_tools_are_registered_for_pydub(self):
        sound, _ = self.sound()

        def download():
            return self.tools(self.root / "downloaded")

        sound._downloadFFmpeg.side_effect = download
        with patch.object(ffmpeg, "_tool_directories", return_value=[]), patch.object(ffmpeg.shutil, "which", return_value=None):
            self.assertTrue(sound.ensureFFmpeg())
        self.assertEqual(self.converter.converter, sound._ffmpeg_exe)
        self.assertEqual(os.environ["PATH"], str(self.root / "downloaded"))
        sound._downloadFFmpeg.assert_called_once_with()

    def test_pydub_conversion_configures_tools_first(self):
        sound, namespace = self.sound()
        expected = self.tools(self.root / "ffmpeg")

        def load_audio(filename):
            self.assertEqual(self.converter.converter, expected)
            return Mock()

        namespace["AudioSegment"].from_mp3.side_effect = load_audio
        self.assertTrue(sound.convertMp3ToWav_pydub("input.mp3", "output.wav"))
        namespace["AudioSegment"].from_mp3.assert_called_once_with("input.mp3")

    def test_missing_tools_report_failure_without_calling_pydub(self):
        sound, namespace = self.sound()
        with patch.object(ffmpeg, "_tool_directories", return_value=[]), patch.object(ffmpeg.shutil, "which", return_value=None):
            self.assertFalse(sound.convertMp3ToWav_pydub("input.mp3", "output.wav"))
        namespace["AudioSegment"].from_mp3.assert_not_called()
        namespace["syslog"].error.assert_called_with("FFmpeg not found.")


class PydubConversionTests(unittest.TestCase):
    def test_bundled_tools_convert_mp3_to_wav_with_no_system_path(self):
        if not (ROOT / "ffmpeg" / "ffmpeg.exe").is_file():
            self.skipTest("Bundled Windows FFmpeg is unavailable")
        # Fresh interpreter checks pydub's import-time discovery as well as ffprobe.
        script = '''
import json, sys, warnings
sys.path.insert(0, sys.argv[1])
from gremlin.ffmpeg import configure_ffmpeg
with warnings.catch_warnings(record=True) as messages:
    warnings.simplefilter("always")
    converter = configure_ffmpeg()
    from pydub import AudioSegment
    from pydub.utils import get_prober_name
    AudioSegment.converter = converter
    with AudioSegment.silent(duration=250).export("sample sound.mp3", format="mp3"):
        pass
    audio = AudioSegment.from_mp3("sample sound.mp3")
    with audio.export("sample sound.wav", format="wav"):
        pass
    assert not [message for message in messages if "Couldn't find" in str(message.message)]
    print(json.dumps(dict(converter=converter, probe=get_prober_name(), duration=len(audio))))
'''
        with tempfile.TemporaryDirectory(prefix="gremlin conversion ") as directory:
            result = subprocess.run([sys.executable, "-c", script, str(ROOT)], cwd=directory,
                                    env={**os.environ, "PATH": ""}, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(Path(output["converter"]), ROOT / "ffmpeg" / "ffmpeg.exe")
            self.assertEqual(output["probe"], "ffprobe")
            self.assertEqual(output["duration"], 250)
            self.assertTrue((Path(directory) / "sample sound.wav").is_file())


if __name__ == "__main__":
    unittest.main()
