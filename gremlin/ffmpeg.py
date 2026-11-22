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
"""Locate audio tools before pydub imports or launches its subprocesses."""

import os
from pathlib import Path
import shutil
import sys


def _tool_directories(extra_dirs=()):
    roots = []
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            roots.append(Path(bundle))
        roots.append(Path(sys.executable).parent)
    roots.append(Path(__file__).resolve().parent.parent)

    directories = []
    for root in roots:
        directories.extend((root, root / "_internal", root / "ffmpeg", root / "ffmpeg" / "bin",
                            root / "tools" / "ffmpeg" / "bin"))
    for directory in extra_dirs:
        if directory:
            directories.extend((Path(directory), Path(directory) / "bin"))
    if os.name == "nt":
        directories.extend((Path("C:/ffmpeg"), Path("C:/ffmpeg/bin")))
        directories.append(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "ffmpeg" / "bin")
    return directories


def configure_ffmpeg(preferred_path=None, extra_dirs=()):
    """Find FFmpeg and expose it and ffprobe to pydub in this process only.

    Prefer bundled tools, including the optional installer layout, before PATH.
    An existing pydub import also receives the converter's absolute filename.
    This function never downloads tools or changes the system environment.
    """
    suffix = ".exe" if os.name == "nt" else ""
    directories = _tool_directories(extra_dirs)
    candidates = [Path(preferred_path)] if preferred_path else []
    candidates.extend(directory / f"ffmpeg{suffix}" for directory in directories)
    encoder = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
    if encoder is None:
        path_encoder = shutil.which("ffmpeg")
        if not path_encoder:
            return None
        encoder = Path(path_encoder).resolve()

    probe_candidates = [encoder.parent / f"ffprobe{suffix}"]
    probe_candidates.extend(directory / f"ffprobe{suffix}" for directory in directories)
    probe = next((candidate.resolve() for candidate in probe_candidates if candidate.is_file()), None)
    if probe is None:
        path_probe = shutil.which("ffprobe")
        if path_probe:
            probe = Path(path_probe).resolve()

    # ffprobe is resolved by pydub through PATH even when converter is explicit.
    tool_dirs = [str(encoder.parent)]
    if probe is not None and probe.parent != encoder.parent:
        tool_dirs.append(str(probe.parent))
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    selected = {os.path.normcase(directory) for directory in tool_dirs}
    path_entries = [entry for entry in path_entries if entry and os.path.normcase(os.path.abspath(entry)) not in selected]
    os.environ["PATH"] = os.pathsep.join([*tool_dirs, *path_entries])

    pydub_module = sys.modules.get("pydub.audio_segment")
    if pydub_module is not None:
        pydub_module.AudioSegment.converter = str(encoder)
    return str(encoder)
