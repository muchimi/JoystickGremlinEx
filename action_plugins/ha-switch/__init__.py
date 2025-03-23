import os
from abc import ABC

from decouple import config
from PySide6 import QtWidgets, QtCore
from lxml import etree as ElementTree
from gremlin.input_types import InputType
from gremlin.ui.input_item import AbstractActionWidget
from gremlin.base_profile import AbstractFunctor, AbstractAction
from gremlin.profile import safe_read
from ha_request import JGHAClient

light_entities = config("HA_ENTITY_LIGHT")
ha_client = JGHAClient()


class HALightSwitchWidget(AbstractActionWidget):
    """Widget which allows the toggle light at home assistant."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, HALightSwitch)

    def _create_ui(self):
        self.extra_arguments_layout = QtWidgets.QHBoxLayout()
        self.extra_args_label = QtWidgets.QLabel("HA Light Extra Arguments as Json")
        self.extra_args = QtWidgets.QLineEdit()
        self.extra_args.textChanged.connect(self._update_sensor_msg)
        self.extra_arguments_layout.addWidget(self.extra_args_label)
        self.extra_arguments_layout.addWidget(self.extra_args)

        self.entity_label = QtWidgets.QLabel("Entity")
        self.entity_list = QtWidgets.QComboBox()
        for entity, friendly_name in light_entities.items():
            self.entity_list.addItem(entity)
        self.entity_list.activated.connect(self._entity_list_changed_cb)

        self.command_label = QtWidgets.QLabel("Command")
        self.command_list = QtWidgets.QComboBox()
        for command in ["turn_on", "turn_off", "toggle"]:
            self.command_list.addItem(command)
        self.command_list.activated.connect(self._command_list_changed_cb)

        self.group_box = QtWidgets.QGroupBox("Color")
        self.groupbox_layout = QtWidgets.QVBoxLayout(self.group_box)

        self.last_color = QtWidgets.QLabel()
        self.groupbox_layout.addWidget(self.last_color)

        self.color_button = QtWidgets.QPushButton("change Color")
        self.color_button.clicked.connect(self._color_button_cb)
        self.brightness_label = QtWidgets.QLabel("Brightness ")
        self.brightness_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(0, 100)
        self.brightness_slider.setTickPosition(
            QtWidgets.QSlider.TickPosition.TicksBelow
        )
        self.brightness_slider.setTickInterval(10)
        self.brightness_slider.setSliderPosition(self.action_data.brightness)
        self.brightness_slider.valueChanged[int].connect(self._brightness_change_cb)

        self.groupbox_layout.addWidget(self.color_button)
        self.groupbox_layout.addWidget(self.brightness_label)
        self.groupbox_layout.addWidget(self.brightness_slider)

        self.effect_button = QtWidgets.QPushButton("Set Effect")
        self.effect_button.clicked.connect(self._effect_button_change_cb)

        self.main_layout.addWidget(self.entity_label)
        self.main_layout.addWidget(self.entity_list)
        self.main_layout.addWidget(self.command_label)
        self.main_layout.addWidget(self.command_list)
        self.main_layout.addWidget(self.group_box)
        self.main_layout.addWidget(self.effect_button)
        self.main_layout.addLayout(self.extra_arguments_layout)

    def _effect_button_change_cb(self, s):
        if len(self.entity_list.currentText()) == 0:
            entity_error = QtWidgets.QMessageBox.critical(
                self,
                "Error",
                "Set Entity first",
                buttons=QtWidgets.QMessageBox.StandardButton.Ok,
                defaultButton=QtWidgets.QMessageBox.StandardButton.Ok,
            )
            if entity_error == QtWidgets.QMessageBox.Ok:
                return

        else:
            self.effect_dialog = EffectDialog(self.entity_list.currentText(), self)

            if self.effect_dialog.exec():
                self.action_data.effect = self.effect_dialog.effect
                self.effect_button.setText(f"Effect: '{self.action_data.effect}'")
            else:
                self.action_data.effect = "Solid"
                self.effect_button.setText("Set Effect")

    def _brightness_change_cb(self):
        self.action_data.brightness = self.brightness_slider.value()

    def _command_list_changed_cb(self):
        self.action_data.command = self.command_list.currentText()
        self.action_modified.emit()

    def _entity_list_changed_cb(self):
        self.action_data.entity_name = self.entity_list.currentText()
        self.action_modified.emit()

    def _color_button_cb(self):
        self.button_press_dialog = QtWidgets.QColorDialog.getColor().getRgb()
        rgb_color_hex = str(self.button_press_dialog)
        print(rgb_color_hex)
        self.action_data.color = self.button_press_dialog
        self.action_modified.emit()

    def _update_sensor_msg(self, value):
        self.action_data.text = value

    def _populate_ui(self):
        self.extra_args.setText(self.action_data.text)
        entity_id = self.entity_list.findText(self.action_data.entity_name)
        command_id = self.command_list.findText(self.action_data.command)
        self.entity_list.setCurrentIndex(entity_id)
        self.command_list.setCurrentIndex(command_id)
        self.last_color.setText(f"Current Color is: {self.action_data.color}")
        self.last_color.setStyleSheet(f"color: rgb{self.action_data.color}")
        self.brightness_label.setText(f"Brightness {self.action_data.brightness}")
        if isinstance(self.action_data.brightness, int):
            self.brightness_slider.setSliderPosition(self.action_data.brightness)


class EffectDialog(QtWidgets.QDialog):
    def __init__(self, entity, parent):
        super().__init__(parent)
        self.setWindowTitle("Effects")
        self.entity = entity

        self.effect_label = QtWidgets.QLabel("Effect List")
        self.effect_list = QtWidgets.QComboBox()
        entity_attributes = ha_client.get_entity_state(self.entity)

        for effect in entity_attributes["attributes"]["effect_list"]:
            self.effect_list.addItem(effect)
        self.effect = self.effect_list.currentText()
        self.effect_list.activated.connect(self._effect_list_change_cb)
        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.layout = QtWidgets.QHBoxLayout()
        self.layout.addWidget(self.effect_label)
        self.layout.addWidget(self.effect_list)
        self.layout.addWidget(self.button_box)
        self.setLayout(self.layout)

    def _effect_list_change_cb(self):
        self.effect = self.effect_list.currentText()

class HALightFunctor(AbstractFunctor):
    def __init__(self, action):
        super().__init__(action)
        self.entity_name = action.entity_name
        self.command = action.command
        self.color = action.color
        self.text = action.text
        self.brightness = action.brightness
        self.effect = action.effect

    def process(self, event, value):
        match self.entity_name:
            case name if "light" in name:
                ha_client.trigger_light_service(self.entity_name, self.command)
            case switch if "switch" in name:
                pass
                #ha_client.trigger_service()

class HALightSwitch(AbstractAction):
    name = "HA Light Switch"
    tag = "ha-light-switch"
    default_button_activation = (True, False)
    input_types = [
        InputType.JoystickAxis,
        InputType.JoystickButton,
        InputType.JoystickHat,
        InputType.Keyboard,
    ]
    widget = HALightSwitchWidget
    functor = HALightFunctor

    def __init__(self, parent):
        super().__init__(parent)
        self.entity_name = ""
        self.command = ""

        self.color = ""
        self.brightness = 50
        self.effect = "Solid"
        self.text = ""

    def icon(self):
        return "{}/icon.png".format(os.path.dirname(os.path.realpath(__file__)))

    def requires_virtual_button(self):
        return self.get_input_type() in [InputType.JoystickAxis, InputType.JoystickHat]

    def _parse_xml(self, node, data=None):
        self.text = safe_read(node, "text", str, "")
        for child in node:
            if child.tag == "command":
                self.command = child.get("command")
            if child.tag == "entity":
                self.entity_name = child.get("entity-name")
            if child.tag == "color":
                self.color = child.get("color")
            if child.tag == "brightness":
                self.brightness = int(child.get("brightness"))
            if child.tag == "effect":
                self.effect = child.get("effect")

    def _generate_xml(self):
        node = ElementTree.Element("ha-light-switch")
        node.set("text", str(self.text))
        command_child = ElementTree.Element("command")
        command_child.set("command", self.command)
        entity_child = ElementTree.Element("entity")
        entity_child.set("entity-name", str(self.entity_name))
        color_child = ElementTree.Element("color")
        color_child.set("color", self.color)
        brightness_child = ElementTree.Element("brightness")
        brightness_child.set("brightness", str(self.brightness))
        effect_child = ElementTree.Element("effect")
        effect_child.set("effect", self.effect)
        node.append(command_child)
        node.append(entity_child)
        node.append(color_child)
        node.append(brightness_child)
        node.append(effect_child)
        return node

    def _is_valid(self):
        return True

version = 1
name = "ha-light-switch"
create = HALightSwitch