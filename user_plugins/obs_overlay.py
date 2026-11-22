# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
# Module created by Lolo350 for GremlinEx
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

from gremlin.input_devices import gremlin_start, gremlin_stop
from gremlin.user_plugin import BoolVariable, ButtonVariable


def _launch_designer():
    import gremlin.ui.obs_overlay as overlay

    overlay.launch_designer()


launch = ButtonVariable(
    "Open Overlay tab",
    "Switch to the Overlay tab for the current profile. Layouts are stored with that profile.",
    callback=_launch_designer,
)

auto_show = BoolVariable(
    "Show overlay when profile starts",
    "Also open the overlay when this plugin instance starts. Prefer the Overlay tab option of the same name.",
    False,
    is_optional=True,
)


@gremlin_start()
def on_start():
    if auto_show.value:
        from PySide6 import QtCore

        def _open():
            try:
                import gremlin.ui.obs_overlay as overlay

                overlay.show_overlay(auto=True)
            except Exception:
                pass

        QtCore.QTimer.singleShot(0, _open)


@gremlin_stop()
def on_stop():
    if not auto_show.value:
        return
    try:
        import gremlin.ui.obs_overlay as overlay

        overlay.hide_overlay()
    except Exception:
        pass
