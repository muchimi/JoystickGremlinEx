"""
VPC Led Control is a modul to send Colour States from Joystick Gremlin to the Virpil Joystick LEDs.
"""
import logging
import os

from PySide6 import QtWidgets
from lxml import etree as ElementTree
from action_plugins.vpc_led_control import vpc_led_controller
from gremlin import shared_state
from gremlin.base_profile import AbstractFunctor, AbstractAction
from gremlin.input_types import InputType
from gremlin.ui.input_item import AbstractActionWidget
from gremlin.config import Configuration
from gremlin.profile import safe_read
from gremlin.joystick_handling import joystick_devices
from gremlin.ui.ui_common import QComboBox

syslog = logging.getLogger("system")


class VPCLedControlWidget(AbstractActionWidget):
    """
        VPC Led Control is a modul to send Colour States from Joystick Gremlin to the Virpil Joystick LEDs.
        the VPC_Led_Control.exe is from the Virpil Software Suite.
        More Information about at
        https://forum.virpil.com/index.php?/topic/2326-vpc_led_control-new-small-tool-to-control-leds-on-your-vpc-device/
        Modul is written by Tholo
    """

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, VPCLEDMode)

    def display_name(self):
        """ returns a display string for the current configuration """
        return "VPC Led Control Action"

    def _create_ui(self):
        # todo add Labels for Description
        self.device_box = QtWidgets.QGroupBox("Device")
        self.device_box_layout = QtWidgets.QVBoxLayout(self.device_box)

        self.device_list = QComboBox()
        self.devices = joystick_devices()
        for dev in self.devices:
            self.device_list.addItem(dev.name)
        self.device_list.activated.connect(self._device_list_changed_cb)

        self.command_list = QComboBox()
        for command in vpc_led_controller.COMMAND_LIST:
            self.command_list.addItem(command)
        self.command_list.activated.connect(self._command_list_changed_cb)


        self.group_box = QtWidgets.QGroupBox("Color")
        self.groupbox_layout = QtWidgets.QVBoxLayout(self.group_box)
        self.last_color = QtWidgets.QLabel()
        self.groupbox_layout.addWidget(self.last_color)
        self.color_list = QtWidgets.QComboBox()
        for color_name, hex_color in vpc_led_controller.COLOR_DICT.items():
            self.color_list.addItem(color_name)
        self.color_list.activated.connect(self._color_list_change_cb)

        self.groupbox_layout.addWidget(self.color_list)
        self.groupbox_layout.addWidget(self.last_color)
        self.device_box_layout.addWidget(self.device_list)
        self.device_box_layout.addWidget(self.command_list)
        self.main_layout.addWidget(self.device_box)
        self.main_layout.addWidget(self.group_box)

    def _command_list_changed_cb(self):
        self.action_data.command = self.command_list.currentText()
        self.action_modified.emit()

    def _device_list_changed_cb(self):
        self.action_data.device_name = self.device_list.currentText()
        self._get_vid_pid()
        self.action_modified.emit()

    def _color_list_change_cb(self):
        self.action_data.color = vpc_led_controller.COLOR_DICT.get(self.color_list.currentText())
        self.color_name = self.color_list.currentText()
        self.action_modified.emit()

    def _get_vid_pid(self):
        """
        read device vid and pid
        """
        for dev in self.devices:
            if dev.name == self.action_data.device_name:
                if len(format(int(dev.vendor_id), "x")) == 4:
                    vendor_id = str(format(int(dev.vendor_id), "x"))
                    self.action_data.device_vid = vendor_id
                elif len(format(int(dev.vendor_id), "#x")) >= 5:
                    vendor_id_format = str(format(int(dev.vendor_id), "#x")).replace("0x", "0")
                    self.action_data.device_vid = vendor_id_format

                if len(format(int(dev.product_id), "#x")) == 4:
                    p_id = str(format(int(dev.product_id), "#x"))
                    self.action_data.device_pid = p_id
                elif len(format(int(dev.product_id), "#x")) >= 5:
                    p_id_format = str(format(int(dev.product_id), "x")).replace("0x", "0")
                    if len(p_id_format) == 3:
                        p_id_format = f"0{p_id_format}"
                    self.action_data.device_pid = p_id_format

    def _populate_ui(self):
        command_id = self.command_list.findText(self.action_data.command)
        device_id = self.device_list.findText(self.action_data.device_name)
        for k, v in vpc_led_controller.COLOR_DICT.items():
            if v == self.action_data.color:
                color_id = self.color_list.findText(k)
                self.color_list.setCurrentIndex(color_id)
                break
        self.command_list.setCurrentIndex(command_id)
        self.device_list.setCurrentIndex(device_id)
        self.last_color.setText(f"Current Color is: 'HexCode': #{self.action_data.color} "
                                f"'rgb': {self.hex_to_rgb(self.action_data.color)}")
        self.last_color.setStyleSheet(f'color: #{self.action_data.color}')

    @staticmethod
    def hex_to_rgb(color):
        if len(color) == 0:
            color = "000000"
        rgb = list(int(color[i:i + 2], 16) for i in (0, 2, 4))
        return rgb


class VPCLedControlFunctor(AbstractFunctor):
    def __init__(self, action, parent=None):
        super().__init__(action, parent)
        self.mode_name = action.mode_name
        self.color = action.color
        self.device_name = action.device_name
        self.command = action.command
        self.device_vid = action.device_vid
        self.device_pid = action.device_pid

    def process_event(self, event, value, extra_data = None):
        send_color = vpc_led_controller.set_color(
            self.device_vid, self.device_pid,
            self.command, self.color
        )
        if send_color:
            return True
        else:
            syslog.error(f"Failed to send color {self.color} to device {self.device_name}")
            return False


class VPCLEDMode(AbstractAction):
    """Action representing the change of mode."""
    name = "VPC LED Control"
    tag = "vpc-led"
    default_button_activation = (True, False)
    input_types = [
        InputType.JoystickAxis,
        InputType.JoystickButton,
        InputType.JoystickHat,
        InputType.Keyboard
    ]
    widget = VPCLedControlWidget
    functor = VPCLedControlFunctor

    def __init__(self, parent):
        super().__init__(parent)
        self.mode_name = self.get_mode()
        self.color = ""
        self.device_name = ""
        self.command = ""
        self.device_vid = ""
        self.device_pid = ""

    def icon(self):
        return "{}/icon.png".format(os.path.dirname(os.path.realpath(__file__)))

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node, data=None):
        self.color = safe_read(
            node, "color-hex", str, ""
        )
        for child in node:
            if child.tag == "led-command":
                self.command = child.get("command")
            if child.tag == "mode":
                self.mode_name = child.get("mode-name")
            if child.tag == "virpil-device":
                self.device_name = child.get("vpc-name")
            if child.tag == "virtual-usb-id":
                self.device_vid = child.get("vid")
                self.device_pid = child.get("pid")
        self.mode_name = node.get("mode_name")
        verbose = Configuration().verbose_mode_outputs
        if verbose: syslog.info(f"Read mode: {self.mode_name} from XML - edit mode: {shared_state.edit_mode}")

    def _generate_xml(self):
        node = ElementTree.Element("vpc-led")
        node.set("color-hex", str(self.color))
        command_child = ElementTree.Element("led-command")
        command_child.set("command", self.command)
        mode_child = ElementTree.Element("mode")
        mode_child.set("mode-name", str(self.mode_name))
        entity_child = ElementTree.Element("virpil-device")
        entity_child.set("vpc-name", str(self.device_name))
        vid_child = ElementTree.Element("virtual-usb-id")
        vid_child.set("vid", self.device_vid)
        # pid_child = ElementTree.Element("p-usb-id")
        vid_child.set("pid", self.device_pid)
        node.append(command_child)
        node.append(mode_child)
        node.append(entity_child)
        node.append(vid_child)
        return node

    def _is_valid(self):
        return True


version = 1
name = "vpc-led"
create = VPCLEDMode
