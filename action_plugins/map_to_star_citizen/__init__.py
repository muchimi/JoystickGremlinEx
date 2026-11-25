"""Map an input press to a Star Citizen action advertised by the local server."""

import logging

from lxml import etree
from PySide6 import QtWidgets

from gremlin.base_profile import AbstractFunctor
from gremlin.config import Configuration
from gremlin.input_item import AbstractAction, AbstractActionWidget
from gremlin.input_types import InputType
from gremlin.util import safe_read


syslog = logging.getLogger("system")


def _get_enabled_device():
    if not Configuration().startup_star_citizen_enabled:
        return None

    from gremlin.ui.star_citizen import get_device

    return get_device()


class MapToStarCitizenWidget(AbstractActionWidget):
    def _create_ui(self):
        self._device = _get_enabled_device()
        self.action_name = QtWidgets.QComboBox()
        self.action_name.setEditable(True)
        self.action_name.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.action_name.setToolTip("Game action name advertised by the local server")
        self.hold = QtWidgets.QSpinBox()
        self.hold.setRange(0, 60_000)
        self.hold.setSuffix(" ms")
        self.hold.setToolTip("Optional hold duration. Zero uses a normal press.")
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        form = QtWidgets.QFormLayout()
        form.addRow("Game action", self.action_name)
        form.addRow("Hold duration", self.hold)
        form.addRow(self.status)
        self.main_layout.addLayout(form)
        self.action_name.lineEdit().editingFinished.connect(self._save_name)
        self.action_name.activated.connect(self._save_name)
        self.hold.valueChanged.connect(self._save_hold)
        if self._device is not None:
            self._device.status_changed.connect(self._update_status)

    def _populate_ui(self):
        self.action_name.setEditText(self.action_data.action_name)
        self.hold.setValue(self.action_data.hold_ms)
        if self._device is not None:
            self._update_status(self._device.status)
        else:
            self.status.setText("Star Citizen integration is disabled")

    def _update_status(self, status):
        name = self.action_name.currentText()
        self.action_name.clear()
        self.action_name.addItems(self._device.action_names())
        self.action_name.setEditText(name)
        self.status.setText(status)

    def _save_name(self):
        self.action_data.action_name = self.action_name.currentText().strip()
        self.action_modified.emit()

    def _save_hold(self, value):
        self.action_data.hold_ms = value
        self.action_modified.emit()


class MapToStarCitizenFunctor(AbstractFunctor):
    def profile_start(self):
        self._device = _get_enabled_device()
        self._reported_unavailable = False

    def process_event(self, event, value, extra_data=None):
        device = getattr(self, "_device", None)
        if event.is_pressed and device is not None and not device.trigger(self.action_data.action_name, self.action_data.hold_ms):
            if not self._reported_unavailable:
                syslog.warning("Star Citizen action unavailable: %s", self.action_data.action_name)
                self._reported_unavailable = True
        return True


class MapToStarCitizen(AbstractAction):
    name = "Map to Star Citizen"
    tag = "map-to-star-citizen"
    hint = "Trigger a game action supported by the local Star Citizen server"
    default_button_activation = (True, False)
    input_types = [
        InputType.JoystickButton, InputType.JoystickHat, InputType.Keyboard, InputType.KeyboardLatched,
        InputType.OpenSoundControl, InputType.Midi, InputType.State, InputType.StreamDeck, InputType.ModeControl,
    ]
    functor = MapToStarCitizenFunctor
    widget = MapToStarCitizenWidget

    def __init__(self, parent, extra_data=None):
        super().__init__(parent, extra_data=extra_data)
        self.action_name = ""
        self.hold_ms = 0

    def icon(self):
        return "mdi.rocket-launch"

    def requires_virtual_button(self):
        return False

    def _is_valid(self):
        return bool(self.action_name)

    def _parse_xml(self, node, data=None, extra_data=None):
        self.action_name = node.get("action-name", "").strip()
        self.hold_ms = max(0, min(60_000, safe_read(node, "hold-ms", int, 0)))

    def _generate_xml(self):
        return etree.Element(self.tag, {"action-name": self.action_name, "hold-ms": str(self.hold_ms)})


version = 1
name = "map-to-star-citizen"
create = MapToStarCitizen
