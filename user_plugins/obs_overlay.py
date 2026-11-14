#
# Optional overlay helper plugin for Joystick Gremlin Ex.
# The Overlay tab is always available. This plugin only adds a button
# that switches to that tab, plus an extra profile-start toggle for
# profiles that already used the plugin.
#

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
