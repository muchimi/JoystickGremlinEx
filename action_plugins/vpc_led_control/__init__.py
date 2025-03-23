"""
VPC Led Control is a modul to send Colour States from Joystick Gremlin to the Virpil Joystick LEDs.
"""

import logging
import os

from PySide6 import QtWidgets
from PySide6.QtCore import QObject, Signal, QThread
from lxml import etree as ElementTree
from gremlin import shared_state
from gremlin.base_profile import AbstractFunctor, AbstractAction
from gremlin.input_types import InputType
from gremlin.ui.input_item import AbstractActionWidget
from gremlin.config import Configuration
from gremlin.profile import safe_read
from gremlin.joystick_handling import joystick_devices
from gremlin.ui.ui_common import QComboBox
import subprocess
import threading

syslog = logging.getLogger("system")

COMMAND_LIST = [
    "00 - Set Default",
    "01 - Set Add-boards LED 01",
    "02 - Set Add-boards LED 02",
    "03 - Set Add-boards LED 03",
    "04 - Set Add-boards LED 04",
    "05 - Set On-board LED 01",
    "06 - Set On-board LED 02",
    "07 - Set On-board LED 03",
    "08 - Set On-board LED 04",
    "09 - Set On-board LED 05",
    "10 - Set On-board LED 06",
    "11 - Set On-board LED 07",
    "12 - Set On-board LED 08",
    "13 - Set On-board LED 09",
    "14 - Set On-board LED 10",
    "15 - Set On-board LED 11",
    "16 - Set On-board LED 12",
    "17 - Set On-board LED 13",
    "18 - Set On-board LED 14",
    "19 - Set On-board LED 15",
    "20 - Set On-board LED 16",
    "21 - Set On-board LED 17",
    "22 - Set On-board LED 18",
    "23 - Set On-board LED 19",
    "24 - Set On-board LED 20",
    "25 - Set Slave-board LED 01 ",
    "26 - Set Slave-board LED 02 ",
    "27 - Set Slave-board LED 03 ",
    "28 - Set Slave-board LED 04 ",
    "29 - Set Slave-board LED 05 ",
    "30 - Set Slave-board LED 06 ",
    "31 - Set Slave-board LED 07 ",
    "32 - Set Slave-board LED 08 ",
    "33 - Set Slave-board LED 09 ",
    "34 - Set Slave-board LED 10 ",
    "35 - Set Slave-board LED 11 ",
    "36 - Set Slave-board LED 12 ",
    "37 - Set Slave-board LED 13 ",
    "38 - Set Slave-board LED 14 ",
    "39 - Set Slave-board LED 15 ",
    "40 - Set Slave-board LED 16 ",
    "41 - Set Slave-board LED 17 ",
    "42 - Set Slave-board LED 18 ",
    "43 - Set Slave-board LED 19 ",
    "44 - Set Slave-board LED 20 ",
]

COLOR_DICT = {
    "Black": "000000",
    "White_30": "404040",
    "White_60": "808080",
    "White_100": "FFFFFF",
    "Red_30": "400000",
    "Red_60": "800000",
    "Red_100": "FF0000",
    "Green_30": "004000",
    "Green_60": "008000",
    "Green_100": "00FF00",
    "Blue_30": "000040",
    "Blue_60": "000080",
    "Blue_100": "0000FF",
    "Yellow_30": "404000",
    "Yellow_60": "808000",
    "Yellow_100": "FFFF00",
    "Cyan_30": "004040",
    "Cyan_60": "008080",
    "Cyan_100": "00FFFF",
    "Magenta_30": "400040",
    "Magenta_60": "800080",
    "Magenta_100": "FF00FF",
}


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
        """returns a display string for the current configuration"""
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
        for command in COMMAND_LIST:
            self.command_list.addItem(command)
        self.command_list.activated.connect(self._command_list_changed_cb)

        self.group_box = QtWidgets.QGroupBox("Color")
        self.groupbox_layout = QtWidgets.QVBoxLayout(self.group_box)
        self.last_color = QtWidgets.QLabel()
        self.groupbox_layout.addWidget(self.last_color)
        self.color_list = QtWidgets.QComboBox()
        for color_name, hex_color in COLOR_DICT.items():
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
        self.action_data.color = COLOR_DICT.get(self.color_list.currentText())
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
                    vendor_id_format = str(format(int(dev.vendor_id), "#x")).replace(
                        "0x", "0"
                    )
                    self.action_data.device_vid = vendor_id_format

                if len(format(int(dev.product_id), "#x")) == 4:
                    p_id = str(format(int(dev.product_id), "#x"))
                    self.action_data.device_pid = p_id
                elif len(format(int(dev.product_id), "#x")) >= 5:
                    p_id_format = str(format(int(dev.product_id), "x")).replace(
                        "0x", "0"
                    )
                    if len(p_id_format) == 3:
                        p_id_format = f"0{p_id_format}"
                    self.action_data.device_pid = p_id_format

    def _populate_ui(self):
        command_id = self.command_list.findText(self.action_data.command)
        device_id = self.device_list.findText(self.action_data.device_name)
        for k, v in COLOR_DICT.items():
            if v == self.action_data.color:
                color_id = self.color_list.findText(k)
                self.color_list.setCurrentIndex(color_id)
                break
        self.command_list.setCurrentIndex(command_id)
        self.device_list.setCurrentIndex(device_id)
        self.last_color.setText(
            f"Current Color is: 'HexCode': #{self.action_data.color} "
            f"'rgb': {self.hex_to_rgb(self.action_data.color)}"
        )
        self.last_color.setStyleSheet(f"color: #{self.action_data.color}")

    @staticmethod
    def hex_to_rgb(color):
        if len(color) == 0:
            color = "000000"
        rgb = list(int(color[i : i + 2], 16) for i in (0, 2, 4))
        return rgb


class LEDThread:
    _instance = None
    _lock = threading.Lock()
    # maximum number of threads
    MAX_THREADS = 5

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "threads"):
            self.threads = []
            self.queue = []
        if not hasattr(self, "active_threads"):
            self.active_threads = 0

    def run_thread(self, fn, *args, **kwargs):
        with self._lock:
            # remove finished threads
            self.threads = [t for t in self.threads if t.is_alive()]

            # if there to many threads, add to queue
            if len(self.threads) >= self.MAX_THREADS:
                self.queue.append((fn, args, kwargs))
                return

            # start new thread
            thread = threading.Thread(
                target=self._thread_wrapper, args=(fn, args, kwargs)
            )
            thread.daemon = True
            thread.start()
            self.threads.append(thread)

    def _thread_wrapper(self, fn, args, kwargs):
        try:
            fn(*args, **kwargs)
        finally:
            # if thread is finished, remove it from the list
            with self._lock:
                if self.queue:
                    next_fn, next_args, next_kwargs = self.queue.pop(0)
                    thread = threading.Thread(
                        target=self._thread_wrapper,
                        args=(next_fn, next_args, next_kwargs),
                    )
                    thread.daemon = True
                    thread.start()
                    # Ersetze den aktuellen Thread in der Liste
                    for i, t in enumerate(self.threads):
                        if not t.is_alive():
                            self.threads[i] = thread
                            break


class LEDWorker(QObject):
    finished = Signal(bool)

    def __init__(self, vid, pid, command, hex_color, filepath=None):
        super().__init__()
        self.vid = vid
        self.pid = pid
        self.command = command
        self.hex_color = hex_color
        self.filepath = filepath

    def run(self):
        if self.filepath is None:
            self.filepath = os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "VPC_LED_Control.exe"
            )
        cmd = self.command[:2]
        hex_color_red = self.hex_color[:2]
        hex_color_green = self.hex_color[2:4]
        hex_color_blue = self.hex_color[4:6]
        run = f"{self.filepath} {self.vid} {self.pid} {cmd} {hex_color_red} {hex_color_green} {hex_color_blue}"
        result = subprocess.run(run)
        self.finished.emit(result.returncode == 0)


class VPCLedControlFunctor(AbstractFunctor):
    def __init__(self, action, parent=None):
        super().__init__(action, parent)
        self.mode_name = action.mode_name
        self.color = action.color
        self.device_name = action.device_name
        self.command = action.command
        self.device_vid = action.device_vid
        self.device_pid = action.device_pid
        self.thread_manager = LEDThread()

    def process_event(self, event, value, extra_data=None):
        self.thread_manager.run_thread(self._process_event, event, value, extra_data)

    def _process_event(self, event, value, extra_data=None):
        syslog.debug(f"Start Thread for color: {self.color}, Gerät: {self.device_name}")

        thread = QThread()
        worker = LEDWorker(self.device_vid, self.device_pid, self.command, self.color)
        worker.moveToThread(thread)

        # Lokalen Scope für die Closure-Funktionen erstellen
        context = {"worker": worker, "thread": thread}

        def on_finished(result):
            if result:
                syslog.debug(
                    f"Successfully sent color {self.color} to device {self.device_name}"
                )
            else:
                syslog.error(
                    f"Failed to send color {self.color} to device {self.device_name}"
                )

            # Thread beenden - WICHTIG: Direkt zugreifen, nicht über Variable
            if context["thread"].isRunning():
                context["thread"].quit()

        def cleanup_thread():
            try:
                # wait for the thread to finish
                if context["thread"].isRunning():
                    context["thread"].wait(1000)

                # Explicit cleanup
                context["worker"].deleteLater()
                context["thread"].deleteLater()

                syslog.debug(f"Thread für {self.device_name} erfolgreich bereinigt")
            except Exception as e:
                syslog.error(f"Fehler beim Bereinigen des Threads: {str(e)}")

        worker.finished.connect(on_finished)
        thread.started.connect(worker.run)
        thread.finished.connect(cleanup_thread)

        try:
            thread.start()
            syslog.debug(f"Thread für {self.device_name} gestartet")
        except Exception as e:
            syslog.error(f"Fehler beim Starten des Threads: {str(e)}")
            worker.deleteLater()
            thread.deleteLater()


class VPCLEDMode(AbstractAction):
    """Action representing the change of mode."""

    name = "VPC LED Control"
    tag = "vpc-led"
    default_button_activation = (True, False)
    input_types = [
        InputType.JoystickAxis,
        InputType.JoystickButton,
        InputType.JoystickHat,
        InputType.Keyboard,
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
        return self.get_input_type() in [InputType.JoystickAxis, InputType.JoystickHat]

    def _parse_xml(self, node, data=None):
        self.color = safe_read(node, "color-hex", str, "")
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
        if verbose:
            syslog.info(
                f"Read mode: {self.mode_name} from XML - edit mode: {shared_state.edit_mode}"
            )

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
