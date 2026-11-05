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

"""helper utility to produce the packaged distribution to the correct versioned archive name"""

import ast
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent


def rename_archive(dist_dir: Path, version_file: Path) -> Path:
    version_tree = ast.parse(version_file.read_text(encoding="utf-8"), filename=str(version_file))
    version = next(
        (
            ast.literal_eval(node.value)
            for node in version_tree.body
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "APPLICATION_BASE" for target in node.targets)
        ),
        None,
    )
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError(f"Unable to find a valid APPLICATION_BASE in {version_file}")

    source = dist_dir / "gremlinEx.zip"
    destination = dist_dir / f"gremlinEx_1_0_{version}.zip"

    if not source.is_file():
        raise FileNotFoundError(f"Archive not found: {source}")
    if destination.exists():
        destination.unlink()  # remove the existing file for overwrite

    source.rename(destination)
    return destination


if __name__ == "__main__":
    try:
        renamed_archive = rename_archive(ROOT / "dist", ROOT / "gremlin" / "version.py")
    except (OSError, SyntaxError, ValueError) as err:
        print(f"Unable to rename GremlinEx archive: {err}", file=sys.stderr)
        sys.exit(1)
    print(f"Created {renamed_archive}")
