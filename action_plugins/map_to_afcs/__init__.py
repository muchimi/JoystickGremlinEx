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

import logging
from lxml import etree as ElementTree
from PySide6 import QtWidgets

import gremlin.base_profile
import gremlin.input_item
import gremlin.ui.ui_common
from gremlin.input_types import InputType
from gremlin.util import safe_format, safe_read
from shiboken6 import Shiboken

syslog = logging.getLogger("system")


class MapToAfcsWidget(gremlin.input_item.AbstractActionWidget):
    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("AFCS input name")
        self.name_edit.editingFinished.connect(self._on_name)
        hint = QtWidgets.QLabel("Sends this axis into the AFCS graph as a named Input. Open the AFCS tab to wire it through merge, curve, and vJoy output nodes.")
        hint.setWordWrap(True)
        self.main_layout.addWidget(QtWidgets.QLabel("AFCS input name"))
        self.main_layout.addWidget(self.name_edit)
        self.main_layout.addWidget(hint)
        self.remote_widget = gremlin.ui.ui_common.RemoteClientWidget(self.action_data.remote_config)
        self.main_layout.addWidget(self.remote_widget)

    def _populate_ui(self):
        if not Shiboken.isValid(self):
            return
        if not self.action_data.input_name:
            self.action_data.input_name = self.action_data.default_input_name()
        self.name_edit.blockSignals(True)
        self.name_edit.setText(self.action_data.input_name)
        self.name_edit.blockSignals(False)
        self.action_data.enroll()
        self.remote_widget.refreshClients()

    def _on_name(self):
        name = self.name_edit.text().strip()
        if not name:
            name = self.action_data.default_input_name()
            self.name_edit.setText(name)
        self.action_data.input_name = name
        self.action_data.enroll()


class MapToAfcsFunctor(gremlin.base_profile.AbstractFunctor):
    def __init__(self, action, parent=None):
        super().__init__(action, parent)
        self.action = action

    def profile_start(self):
        self.action.enroll()
        try:
            from gremlin.ui.afcs import AfcsManager

            AfcsManager().register_output_config(self.action.remote_config)
        except Exception:
            pass

    def profile_started(self):
        self._push_current()

    def profile_stop(self):
        try:
            from gremlin.ui.afcs import AfcsManager

            manager = AfcsManager()
            manager.set_input(self.action.input_name, 0.0)
            manager.unregister_output_config(self.action.remote_config)
        except Exception:
            pass

    def _push_current(self):
        try:
            import gremlin.joystick_handling
            from gremlin.ui.afcs import AfcsManager

            item = self.action.get_input_item()
            if item is None:
                return
            guid = getattr(item, "device_guid", None)
            axis_id = int(getattr(item, "input_id", 0) or 0)
            if not guid or not axis_id:
                return
            current = gremlin.joystick_handling.get_axis(guid, axis_id)
            if current is None:
                current = 0.0
            AfcsManager().set_input(self.action.input_name, float(current))
        except Exception:
            pass

    def process_event(self, event, value, extra_data=None):
        try:
            from gremlin.ui.afcs import AfcsManager

            current = getattr(value, "current", value)
            AfcsManager().set_input(self.action.input_name, float(current))
        except Exception:
            pass
        return True


class MapToAfcs(gremlin.input_item.AbstractAction):
    name = "Map to AFCS"
    tag = "map-to-afcs"
    hint = """Sends this axis to the AFCS graph as a named input.
Wire that input on the AFCS tab through merge, curve, and vJoy output nodes."""

    default_button_activation = (True, True)
    input_types = [InputType.JoystickAxis]

    functor = MapToAfcsFunctor
    widget = MapToAfcsWidget

    def __init__(self, parent, extra_data: dict = None):
        super().__init__(parent, extra_data=extra_data)
        self.parent = parent
        self.input_name = ""

    def icon(self):
        return "mdi.graph-outline"

    def requires_virtual_button(self):
        return False

    def default_input_name(self) -> str:
        item = None
        try:
            item = self.get_input_item()
        except Exception:
            item = None
        if item is not None:
            device = getattr(item, "device_name", None) or "Axis"
            display = getattr(item, "display_name", None)
            if callable(display):
                display = display()
            display = display or getattr(item, "input_id", "")
            label = f"{device} {display}".strip()
            return label or "AFCS input"
        return "AFCS input"

    def enroll(self):
        name = str(self.input_name or "").strip() or self.default_input_name()
        self.input_name = name
        device_guid = ""
        device_name = ""
        axis_id = 0
        try:
            item = self.get_input_item()
            if item is not None:
                device_guid = str(getattr(item, "device_guid", "") or "")
                device_name = str(getattr(item, "device_name", "") or "")
                axis_id = int(getattr(item, "input_id", 0) or 0)
        except Exception:
            pass
        try:
            from gremlin.ui.afcs import AfcsManager

            AfcsManager().enroll_axis(name, device_guid, device_name, axis_id)
        except Exception as err:
            syslog.warning(f"AFCS: enroll failed: {err}")

    def _parse_xml(self, node, data=None, extra_data=None):
        self.input_name = safe_read(node, "input-name", str, "") or self.default_input_name()

    def _generate_xml(self):
        node = ElementTree.Element("map-to-afcs")
        node.set("input-name", safe_format(self.input_name or self.default_input_name(), str))
        return node

    def _is_valid(self):
        return True


version = 1
name = "map-to-afcs"
create = MapToAfcs
