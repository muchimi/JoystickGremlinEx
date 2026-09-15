# -*- coding: utf-8; -*-

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

from __future__ import annotations  # deprecated with python 3.14+
from enum import Enum


import logging
import fnmatch
import random
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import QModelIndex
import threading
from lxml import etree as ElementTree

import gremlin.util
from gremlin.util import safe_format, safe_read, write_guid, read_guid

import gremlin.config
import gremlin.event_handler
from gremlin.types import DeviceType
from gremlin.input_types import InputType
import gremlin.shared_state
import html
import re

from gremlin.singleton_decorator import SingletonDecorator
import gremlin.base_profile
from psygnal import Signal
import gremlin.input_item
from gremlin.input_item import AbstractCondition, InputItemWidget, BaseAbstractCondition, AbstractConditionWidget, InputItem, AbstractContainer, AbstractAction
from shiboken6 import Shiboken
import html
from typing import Callable

from gremlin.voice import VoiceCommand, Voice
from gremlin.sound import Sound
from PySide6.QtMultimedia import QMediaDevices, QAudioInput
from gremlin.keyboard import Key

from gremlin.ui.keyboard_device import KeyboardInputItem, QKeyListWidget
from gremlin.ui.osc_device import OscInputItem
from gremlin.ui.midi_device import MidiInputItem
from gremlin.ui.streamdeck_device import StreamDeckInputItem
from gremlin.ui.state_device import StateInputItem, StateData


syslog = logging.getLogger("system")


class VoiceInputItem(InputItem):
    """holds a single speech recognition input"""

    def __init__(
        self,
        key: str = None,
        text: str = None,
        description=None,
        data=None,
    ):

        assert key is None or isinstance(key, str), "key must be a string"
        self._key = key  # ok if None (blank)
        self._text = text
        self._phrases_map = {}  # map of phrase by hash value
        self._hooked = False

        self._command_map = {}

        self._mode_object = self._get_master_mode_object()

        super().__init__(
            mode_node=self._mode_object,
            device_guid=VoiceDeviceTabWidget.device_guid,
            input_type=InputType.Voice,
            override_input_type=InputType.JoystickButton,
            custom_input_id_handler=self._handle_input_id_callback,
        )

        self._update_commands()

    def _get_master_mode_object(self):
        master_mode = gremlin.shared_state.master_mode

        # get the mode object for this state input
        profile = gremlin.shared_state.current_profile
        # device = gremlin.joystick_handling.getDevice(StateDeviceTabWidget.device_guid)
        device_modes = profile.get_device_modes(
            VoiceDeviceTabWidget.device_guid,
            DeviceType.Voice,
            DeviceType.to_string(DeviceType.Voice),
        )
        mode_object = device_modes.ensure_mode_exists(master_mode)
        return mode_object

    @property
    def commands(self) -> list[VoiceCommand]:
        """gets the list of voice commands in this voice input (updates based on text property)"""
        return list(self._command_map.values())

    def _update_commands(self):
        """builds voice commands from the input phrase if it has multiple phrases separated by '|'"""
        self._command_map.clear()
        if self._text:
            phrases = re.split(r"\||\n|\r", self.text)
            phrases = [item for item in phrases if item]
            for phrase in phrases:
                command = VoiceCommand(phrase=phrase, callback=self._handle_voice_trigger, owner=self)
                self._command_map[command.key] = command

    def _handle_voice_trigger(self, vc):
        """called when the voice triggers a command - passes the command triggered"""
        if vc.owner != self:
            # not our command
            return
        if self._emit:
            self._last_triggered_command = vc
            syslog.info(f"VOICE: triggered [{self._key}] with phrase [{vc.phrase}]")
            # handle the voice command here
            event = gremlin.event_handler.Event(
                event_type=InputType.Voice,
                value=True,
                is_pressed=True,
                identifier=self,
                device_guid=VoiceDeviceTabWidget.device_guid,
                override_input_type=InputType.JoystickButton,
                extra_data={"command": vc},
            )
            config = gremlin.config.Configuration()
            el = gremlin.event_handler.EventListener()
            el.queueJoystickEvent(event)

            timer = threading.Timer(config.voice_command_release_delay, self._get_release_trigger_callback(vc))
            timer.start()

    def _get_release_trigger_callback(self, vc):
        return lambda: self._trigger_release_event(vc)

    def _trigger_release_event(self, vc: VoiceCommand):
        if self._emit:
            syslog.info(f"VOICE: released [{self._key}] with phrase [{vc.phrase}]")
            # handle the voice command here
            event = gremlin.event_handler.Event(
                event_type=InputType.Voice,
                value=True,
                is_pressed=False,
                identifier=self,
                device_guid=VoiceDeviceTabWidget.device_guid,
                override_input_type=InputType.JoystickButton,
                extra_data={"command": vc},
            )
            el = gremlin.event_handler.EventListener()
            el.queueJoystickEvent(event)

    def suppressEvents(self):
        """disable events"""
        self._emit = False

    def enableEvents(self):
        """enable events"""
        self._emit = True

    def clone(self):
        """clones the input item (gives it a new ID)"""

        return VoiceInputItem(key=self.key, text=self.text, description=self.description, data=self.data)

    def _handle_input_id_callback(self):
        """input id is self for a voice input"""
        return self

    def hook(self):
        """called when the state is being created - hooks into the event model"""
        if not self._hooked:
            sd = gremlin.ui.state_device.StateData()
            sd.key_changed.connect(self._change_state_name)
            self._hooked = True
            el = gremlin.event_handler.EventListener()
            el.profile_unloaded.connect(self._handle_profile_unload)
            verbose = gremlin.config.Configuration().verbose_mode_state
            if verbose:
                syslog.info(f"VOICE: hook [{self._key}] id: [{self._guid}]")

    def unhook(self):
        """called when the state should unhook itself because it is being discarded"""
        if self._hooked:
            sd = gremlin.ui.state_device.StateData()
            sd.key_changed.disconnect(self._change_state_name)
            # clear any dependencies
            el = gremlin.event_handler.EventListener()
            el.profile_unloaded.disconnect(self._handle_profile_unload)
            self._hooked = False
            verbose = gremlin.config.Configuration().verbose_mode_state
            if verbose:
                syslog.info(f"VOICE: unhook [{self._key}]  id: [{self._guid}]")

    def _handle_profile_unload(self):
        """occurs on profile unload before a new profile is loaded"""
        self.unhook()

    @property
    def display_name(self):
        return "Voice Input"

    @property
    def key(self) -> str:
        # the key of the input item is the id
        if not self._key:
            self._key = str(self._id)
        return self._key

    @key.setter
    def key(self, value: str):
        assert value is None or isinstance(value, str), "key must be a string"
        self._key = value

    @property
    def message_key(self):
        return self.key

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value
        # rebuild command list
        self._update_commands()

    def matchText(self, text: str) -> bool:
        """check if the given text matches any of the stored phrases"""
        if not text:
            return False
        text_hash = hash(text.strip().casefold())
        return text_hash in self._phrase_map

    def to_xml(self) -> ElementTree.Element:
        """write XML voice input node"""

        node = ElementTree.Element("voice-input", id=write_guid(self._id), key=self._key)

        description = self.description

        node.set("id", write_guid(self._id))

        if description:
            node.set("description", html.escape(description))

        node.set("text", html.escape(self._text))

        # write container data
        super().to_xml(node)

        return node

    def from_xml(self, node, data=None, extra_data=None):
        """read XML voice input node"""

        self._key = node.get("key")
        if "id" in node.attrib:
            self.setId(read_guid(node, "id"))

        text = node.get("text")
        if text:
            text = html.unescape(text)

        self._text = text
        self._update_commands()

        super().from_xml(node, data, extra_data)

    def __str__(self):
        commands = self.commands
        if commands:
            vc = commands[0]
            return f"Voice Input: {vc.phrase}"
        return "Voice Input: <no command>"


class VoiceInputItemModel(gremlin.input_item.InputItemListModel):
    """data model for state inputs"""

    def __init__(
        self,
        profile: gremlin.base_profile.Profile,
        custom_load_handler: Callable = None,
        custom_filter_handler: Callable = None,
        custom_change_handler: Callable = None,
        item_changed_handler: Callable = None,
    ):

        super().__init__(
            profile=profile,
            device_guid=VoiceDeviceTabWidget.device_guid,
            mode=gremlin.shared_state.master_mode,
            allowed_types=[InputType.Voice],
            custom_load_handler=custom_load_handler,
            custom_change_handler=custom_change_handler,
            custom_filter_handler=custom_filter_handler,
            show_master_mode=True,
        )

        if item_changed_handler:
            self.addOnItemChangedCallback(item_changed_handler)


DEFAULT_AUDIO_DEVICE_INDEX = -1
DEFAULT_AUDIO_DEVICE_MARKER = "__default__"


class VoiceSettingsDialog(gremlin.ui.ui_common.QRememberDialog):
    """configuration dialog to select the voice input device and set speech recognition options"""

    def __init__(self, mode: VoicePTTMode, input_item, device_name: str, parent=None):
        super().__init__(self.__class__.__name__, parent=parent)
        self.setWindowTitle("Voice Input Configuration")
        self.setModal(True)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.setLayout(self.main_layout)

        self._sound = Sound()
        self._voice = Voice()
        self._started = False  # true if monitoring started

        # input item to use
        self._input_type = InputType.KeyboardLatched  # default input type
        self._input_item = input_item
        self._mode = mode

        if self._input_item:
            self._input_type = self._input_item.input_type

        self._mode_object = self._get_mode_object()

        self._last_monitored_device = None
        self._monitored_input = None
        self._default_device_name: str = device_name  # name of default device when in default named entry

        # view meter
        self._view_meter = gremlin.ui.ui_common.QAudioLevelMeter()

        # input selector
        voice_data = VoiceData()
        source = self._get_audio_source()
        index = voice_data.getAudioDeviceIndex()
        self._input_selector = gremlin.ui.ui_common.QDataComboBox(source=source, value=index, callback=self._handle_audio_change)

        self._default_name_widget = QtWidgets.QLabel()

        # monitor button
        # self._monitor_button = gremlin.ui.ui_common.Buttons.getRecordWidget("Monitor input")
        self._monitor_button = QtWidgets.QPushButton("Monitor Input")
        self._monitor_button.setCheckable(True)
        self._monitor_button.toggled.connect(self._handle_monitor_toggle)
        self._monitor_button.setIcon(gremlin.ui.ui_common.Icons.recordIcon())

        self._gain_widget = gremlin.ui.ui_common.QDataRepeaterWidget(value=0.0, decimals=0, prefix="Auto Gain: ", suffix=" dB")

        view_container = gremlin.ui.ui_common.getVContainer([self._view_meter, self._gain_widget], widget_only=True)

        self._volume_widget = gremlin.ui.ui_common.QVolumeKnob(value=0.0)
        self._volume_widget.valueChanged.connect(self._handle_volume_change)

        selector_container = gremlin.ui.ui_common.getVContainer([self._input_selector, self._default_name_widget, self._volume_widget], widget_only=True)

        action_container = gremlin.ui.ui_common.getVContainer(self._monitor_button, widget_only=True)

        widget = gremlin.ui.ui_common.getHContainer([view_container, selector_container, action_container, "||"], widget_only=True)

        self.main_layout.addWidget(widget)

        # computed data
        widget = gremlin.ui.ui_common.getHContainer([self._gain_widget, "||"], widget_only=True)
        self.main_layout.addWidget(widget)

        # listen mode for PTT
        modes = [(VoicePTTMode.to_display(mode), mode, VoicePTTMode.tooltip(mode)) for mode in VoicePTTMode]
        self._ptt_mode_widget = gremlin.ui.ui_common.QDataRadioButtonGroup(
            modes,
            value=self._mode,
            callbackEx=self._handle_ptt_mode_changed,
        )

        self.info_box_widget = gremlin.ui.ui_common.QInfoBox(VoicePTTMode.tooltip(mode))

        widget = gremlin.ui.ui_common.getHContainer(["Activation Mode:", self._ptt_mode_widget, "||"], widget_only=True)
        self.main_layout.addWidget(widget)
        self.main_layout.addWidget(self.info_box_widget)

        # input layout

        self._ptt_input_container = QtWidgets.QWidget()
        self._ptt_input_layout = QtWidgets.QVBoxLayout(self._ptt_input_container)
        self._ptt_input_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self._ptt_input_container)

        # ptt input selector - lets user select the latching type for voice recognition input

        source = [
            ("Keyboard/Mouse", InputType.KeyboardLatched),
            ("Joystick Button", InputType.JoystickButton),
            ("Joystick Hat", InputType.JoystickHat),
            ("State", InputType.State),
            #    ("OSC Input", InputType.OpenSoundControl),
            #    ("MIDI Input", InputType.MIDI),
        ]

        self._ptt_input_selector = gremlin.ui.ui_common.QDataComboBox(source=source, value=self._input_type, callback=self._handle_ptt_input_changed)

        widget = gremlin.ui.ui_common.getHContainer(["Latched Input:", self._ptt_input_selector, "||"], widget_only=True)
        self._ptt_input_layout.addWidget(widget)

        self._update_ptt_input_selector()

        # button bar
        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._execute_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._close_cb)

        widget = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget], left_stretch=True, widget_only=True)

        self.main_layout.addWidget(widget)

        self._update_ui()
        self._update_volume()
        self._update_volume_monitor()

    @property
    def mode(self):
        return self._mode

    @property
    def input_item(self):
        return self._input_item

    def _get_mode_object(self):
        """gets the master mode object"""
        master_mode = gremlin.shared_state.master_mode
        profile = gremlin.shared_state.current_profile
        # device = gremlin.joystick_handling.getDevice(StateDeviceTabWidget.device_guid)
        device_modes = profile.get_device_modes(
            gremlin.shared_state.voice_tab_guid,
            DeviceType.Voice,
            DeviceType.to_string(DeviceType.Voice),
        )
        mode_object = device_modes.ensure_mode_exists(master_mode)
        return mode_object

    def _handle_ptt_mode_changed(self, widget, checked):
        if checked:
            self._mode = widget.data
            self.info_box_widget.setText(VoicePTTMode.tooltip(self._mode))
            self._update_ui()

    def _handle_ptt_input_changed(self, input_type):
        self._input_type = input_type
        self._update_ptt_input_selector()

    def _update_ui(self):
        visible = self._input_selector.currentData() == DEFAULT_AUDIO_DEVICE_INDEX
        if visible:
            self._default_name_widget.setText(VoiceData().getDefaultAudioDevice())
        self._default_name_widget.setVisible(visible)

        # only show input selector if the mode is not off
        visible = self._mode not in (VoicePTTMode.Off, VoicePTTMode.Toggle)
        self._ptt_input_container.setVisible(visible)

    def _ensure_input_item(self):
        match self._input_type:
            case InputType.KeyboardLatched | InputType.Keyboard:
                class_item = KeyboardInputItem
            case InputType.JoystickButton | InputType.JoystickHat:
                class_item = InputItem
            case InputType.State:
                class_item = StateInputItem
            case InputType.OpenSoundControl:
                class_item = OscInputItem
            case InputType.MIDI:
                class_item = MidiInputItem
            case _:
                self._input_item = None
                return

        if self._input_item is None or not isinstance(self._input_item, class_item):
            self._input_item = class_item(self._mode_object)

        return self._input_item

    def _update_ptt_input_selector(self):
        # input selector for PTT mode
        layout = self._ptt_input_layout
        self._ensure_input_item()

        match self._input_type:
            case InputType.KeyboardLatched:
                input_item: KeyboardInputItem = self._input_item
                self.keyboard_widget = QKeyListWidget(input_item.key)
                widget = gremlin.ui.ui_common.getHContainer([self.keyboard_widget, "||"], widget_only=True)
                layout.addWidget(widget)

                record_button_widget = gremlin.ui.ui_common.Buttons.getEditWidget(label="Listen", callback=self._keyboard_listen_cb)
                select_button_widget = gremlin.ui.ui_common.Buttons.getKeyboardWidget(label="Select Keys", callback=self._keyboard_select_cb)
                delete_button_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(
                    callback=self._keyboard_clear_cb,
                    tooltip="Clear",
                )

                widget = gremlin.ui.ui_common.getHContainer([record_button_widget, select_button_widget, delete_button_widget], widget_only=True)
                layout.addWidget(widget)

            case InputType.JoystickButton | InputType.JoystickHat:
                input_item: InputItem = self._input_item
                device = gremlin.joystick_handling.getDevice(input_item.device_guid)
                selector_widget = gremlin.ui.ui_common.QJoystickSelectorWidget(
                    input_types=[self._input_type],  # restrict to hat or button
                    default_device=device,
                    default_input_type=input_item.input_type,
                    default_input_id=input_item.input_id,
                    callback=self._handle_joystick_selection_changed,
                )
                layout.addWidget(selector_widget)

            case InputType.State:
                sd = StateData()
                sources = [(key, state) for key, state in sd.getStates()]
                state = sd.getState(input_item.key)
                state_selector_widget = gremlin.ui.ui_common.QDataComboBox(
                    sources=sources,
                    value=state,
                    callback=self._handle_state_selection_changed,
                )
                layout.addWidget(state_selector_widget)

            case InputType.OpenSoundControl:
                layout.addWidget(gremlin.ui.ui_common.QLabel("OSC input not yet implemented"))

            case InputType.MIDI:
                layout.addWidget(gremlin.ui.ui_common.QLabel("MIDI input not yet implemented"))

            case _:
                layout.addWidget(gremlin.ui.ui_common.QLabel(f"Unknown input type [{self.input_type}]"))

    def _handle_joystick_selection_changed(self, data):
        """Handles changes in joystick selection."""
        device_guid, input_type, input_id = data
        input_item: InputItem = self._input_item
        input_item.device_guid = device_guid
        input_item.input_type = input_type
        input_item.input_id = input_id

    def _handle_state_selection_changed(self, state):
        """Handles changes in state selection."""
        input_item: StateInputItem = self._input_item
        input_item.key = state.key

    def _keyboard_listen_cb(self):
        gremlin.util.InvokeUiMethod(self._keyboard_listen_ui)

    def _keyboard_listen_ui(self):
        """Prompts the user for the input to bind to this item."""

        gremlin.shared_state.push_suspend_highlighting()
        self.button_press_dialog = gremlin.ui.ui_common.InputListenerWidget(
            [InputType.Keyboard, InputType.Mouse],
            return_kb_event=False,
            multi_keys=True,
        )
        self.button_press_dialog.item_selected.connect(self._add_keyboard_listener_key_cb)
        self.button_press_dialog.closed.connect(self._handle_keyboard_listen_close)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        self.button_press_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150,
        )
        self.button_press_dialog.show()

    def _add_keyboard_listener_key_cb(self, data):
        gremlin.util.InvokeUiMethod(self._add_keyboard_listener_key_ui, data)

    def _add_keyboard_listener_key_ui(self, key_list: list[Key]):
        """Processes input events to update the UI and model.

        :param key_list the list of input keys to process
        """
        if not key_list:
            self._input_item.key = None
            self.keyboard_widget.clear()
            return
        key = gremlin.keyboard.key_from_list(key_list)
        self._input_item.key = key
        self.keyboard_widget.setValues(key.getKeys())

    @QtCore.Slot()
    def _keyboard_select_cb(self):
        """brings up the keyboard to select keys from"""

        from gremlin.ui.virtual_keyboard import InputKeyboardDialog

        sequence = self._input_item.key.getKeys() if self._input_item and self._input_item.key else []

        self._keyboard_dialog = InputKeyboardDialog(sequence=sequence, parent=self, select_single=False, index=-1)
        self._keyboard_dialog.setModal(True)
        self._keyboard_dialog.accepted.connect(self._select_keyboard_dialog_ok_cb)
        gremlin.util.centerDialog(self._keyboard_dialog)
        self._keyboard_dialog.showNormal()

    @QtCore.Slot()
    def _select_keyboard_dialog_ok_cb(self):
        """callled when the dialog completes"""

        # grab a new data index as this is a new entry
        self._add_keyboard_listener_key_ui(self._keyboard_dialog.latched_key)

    @QtCore.Slot()
    def _execute_cb(self):
        """ok button callback"""
        self.setResult(QtWidgets.QDialog.DialogCode.Accepted)
        self.close()

    @QtCore.Slot()
    def _close_cb(self):
        """cancel button callback"""
        self.setResult(QtWidgets.QDialog.DialogCode.Rejected)
        self.close()

    @QtCore.Slot()
    def _keyboard_clear_cb(self):
        """clears the currently selected keyboard key"""
        self._add_keyboard_listener_key_ui(None)

    def _handle_monitor_toggle(self, checked):
        if checked:
            self.start()
        else:
            self.stop()

    def stop(self):
        """stop the voice device and disconnect the monitored input"""
        if self._started:
            self._voice.stop()
            self._voice.audioMonitor.disconnect(self._update_view_meter)
            if self._monitored_input:
                self._monitored_input.volumeChanged.disconnect(self._handle_system_volume_changed)
                self._monitored_input = None
            self._voice.popRecognize()
            self._started = False

            if self._monitor_button.isChecked():
                # uncheck the monitor button if it is still checked (stop may be called externally)
                with QtCore.QSignalBlocker(self._monitor_button):  # prevent UI updates while stopping
                    self._monitor_button.setChecked(False)

    def start(self):
        """start the voice device and connect the monitored input"""
        if self._started:
            return
        self._voice.pushRecognize()
        self._voice.audioMonitor.connect(self._update_view_meter)
        self._voice.start()
        if self._monitored_input:
            self._monitored_input.volumeChanged.connect(self._handle_system_volume_changed)
        self._started = True

    def closeEvent(self, event):
        """handle the dialog close event"""
        self.stop()
        super().closeEvent(event)

    def _update_view_meter(self, info: dict):
        """update the view meter based on audio monitor info"""
        level_db = info.get("level_db", -100.0)
        gain_db = info.get("gain_db", 0.0)
        # noise_db = info.get("noise_db", -100.0)
        threshold_db = info.get("threshold_db", -100.0)
        # is_speech = info.get("is_speech", False)
        # speech_started = info.get("speech_started", False)
        # speech_ended = info.get("speech_ended", False)

        self._view_meter.setLevels(level_db, threshold_db)
        self._gain_widget.setValue(gain_db)

    def _handle_audio_change(self, index: int):
        self.stop()  # ensure monitoring stopped
        voice_data = VoiceData()
        if index == DEFAULT_AUDIO_DEVICE_INDEX:
            # follow the Windows default output device at playback time

            if not self._default_device_name:
                self._default_device_name = voice_data.getDefaultAudioDevice()
            voice_data._audio_device = self._default_device_name
            return
        self.device_name = voice_data.getAudioDeviceFromIndex(index)
        self._update_ui()

    def _update_volume_monitor(self):

        target_name = self._get_target_device().casefold()
        if self._last_monitored_device is None or self._last_monitored_device != target_name:
            self._last_monitored_device = target_name

            monitored_device = None
            for device in QMediaDevices.audioInputs():
                if target_name in device.description().casefold():
                    monitored_device = device
                    break

            if self._monitored_input:
                self._monitored_input.volumeChanged.disconnect(self.on_volume_changed)

            self._monitored_input = QAudioInput(monitored_device, self)
            self._monitored_input.volumeChanged.connect(self._handle_system_volume_changed)

    def _handle_system_volume_changed(self, value: float):
        """reflects a volume change in the system microphone volume"""
        volume = round(value * 100)  # convert 0 to 1 to 0 to 100
        if self._volume_widget.value() == volume:
            return
        with QtCore.QSignalBlocker(self._volume_widget):
            self._volume_widget.setValue(volume)

    @QtCore.Slot(int)
    def _handle_volume_change(self, value: int):
        # set the system microphone volume (ui thread)

        target_name = self._get_target_device()
        self._voice._set_volume_ui(value, target_name=target_name)

    def _update_volume(self) -> int:
        """gets the current device input volume as set in the operating system"""
        target_name = self._get_target_device()
        volume = self._voice.getVolume(target_name=target_name)
        self._volume_widget.setValue(volume)

    def _get_target_device(self) -> str:
        index = self._input_selector.currentData()
        if index == DEFAULT_AUDIO_DEVICE_INDEX:
            if not self._default_device_name:
                self._default_device_name = self._voice_data.getDefaultAudioDevice()
            return self._default_device_name
        return self._input_selector.currentText()

    def _update_audio_devices(self):
        # update the list of available audio devices

        with QtCore.QSignalBlocker(self._input_selector):
            self._input_selector.clear()

            source = [("Default device", DEFAULT_AUDIO_DEVICE_INDEX)]
            source += self._voice_data.getAudioDevicePairs()

            for device, index in source:
                self._input_selector.addItem(device, index)

    def _get_audio_source(self):
        voice_data = VoiceData()
        source = [("Default device", DEFAULT_AUDIO_DEVICE_INDEX)]
        source += voice_data.getAudioDevicePairs()
        return source

    def _handle_audio_change(self, value: int):
        """device changed via selector box"""
        try:
            if value == DEFAULT_AUDIO_DEVICE_INDEX:
                # follow the Windows default output device at playback time
                self._default_device_name = self._voice_data.getDefaultAudioDevice()
                self._device_name = self._default_device_name
                return
            device_name = self._voice_data.getAudioDeviceFromIndex(value)

            if device_name is not None:
                self._device_name = device_name
                return
        finally:
            self._update_ui()


class VoicePTTMode(Enum):
    """enumeration for push-to-talk modes"""

    Off = 0  # push-to-talk key is disabled
    Toggle = 1  # PTT key toggles listen on/off
    AlwaysOn = 2  # listen all the time
    PressToSuspend = 3  # if PTT is not held, listen to microphone (normal setup for most users who use PTT for discord)
    PressToListen = 4  # if PTT key is held, listen to the microphone (normal PTT mode)

    @staticmethod
    def to_string(mode: "VoicePTTMode") -> str:
        match mode:
            case VoicePTTMode.Off:
                return "Off"
            case VoicePTTMode.Toggle:
                return "Toggle"
            case VoicePTTMode.AlwaysOn:
                return "AlwaysOn"
            case VoicePTTMode.PressToSuspend:
                return "PressToSuspend"
            case VoicePTTMode.PressToListen:
                return "PressToListen"

        return "Unknown"

    @staticmethod
    def to_display(mode: "VoicePTTMode") -> str:
        match mode:
            case VoicePTTMode.Off:
                return "Off"
            case VoicePTTMode.Toggle:
                return "Toggle"
            case VoicePTTMode.AlwaysOn:
                return "Always On"
            case VoicePTTMode.PressToSuspend:
                return "Press to Suspend"
            case VoicePTTMode.PressToListen:
                return "Press to Listen"

        return "Unknown"

    @staticmethod
    def from_string(mode_str: str) -> "VoicePTTMode":
        match mode_str:
            case "Off":
                return VoicePTTMode.Off
            case "Toggle":
                return VoicePTTMode.Toggle
            case "AlwaysOn":
                return VoicePTTMode.AlwaysOn
            case "PressToSuspend":
                return VoicePTTMode.PressToSuspend
            case "PressToListen":
                return VoicePTTMode.PressToListen

        return VoicePTTMode.Off

    @staticmethod
    def tooltip(mode: "VoicePTTMode") -> str:
        match mode:
            case VoicePTTMode.Off:
                return "Push-to-talk key is disabled (speech recognition is never active)"
            case VoicePTTMode.Toggle:
                return "PTT key toggles speech recognition on/off with each press"
            case VoicePTTMode.AlwaysOn:
                return "Listen all the time"
            case VoicePTTMode.PressToSuspend:
                return "Enable speech recognition when the PTT is not held (this is the usual setup for most users who use PTT for voice chat)"
            case VoicePTTMode.PressToListen:
                return "Enable speech recognition only when the PTT key is held (normal PTT mode)"

        return f"Unknown mode [{mode}]"


@SingletonDecorator
class VoiceData:
    """holds voice information"""

    crud = Signal()  # fires when a voice input is added or removed or changed

    def __init__(self):
        self._data = {}
        self._id_map = {}

        self._audio_device: str = None  # name of the selected audio device
        self._sound = Sound()

        self._gain = 1.0  # default gain value
        self._ptt_mode: VoicePTTMode = VoicePTTMode.PressToSuspend
        self._ptt_input_item = None  # input to use/monitor for PTT - can be a KeyboardInputItem, OSCInputItem, JoystickInputItem, etc...

        self._voice = Voice()

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self._reset)
        el.profile_unloaded.connect(self._handle_profile_unload)

    def getCommandsFromText(self, text: str) -> list:
        """gets the list of commands that match the given text"""
        if text:
            phrases = [token.strip() for token in text.split("|")]
            phrases = set(token.casefold() for token in phrases if token)
            commands = [VoiceCommand(phrase) for phrase in phrases]
            return commands
        return []

    def getCommands(self) -> list:
        """gets the current list of commands"""
        return self._voice.getCommands()

    def _update_commands(self):
        """updates the list of commands based on the current input items"""
        for input_item in self._data.values():
            text = input_item.text if hasattr(input_item, "text") else ""
            commands = self.getCommandsFromText(text)
            self._voice.addCommands(commands)

    def clearCommands(self):
        """clears all commands from the matcher"""
        self._voice.clearCommands()

    def getDefaultAudioDevice(self):
        """gets the default input device"""
        if self._audio_device is None:
            self._audio_device = self._sound.getDefaultInputDevice()
        return self._audio_device

    def getAudioDevices(self):
        """gets the list of all input devices"""
        return list(self._sound.input_device_map.values())

    def getAudioDevicePairs(self) -> list[tuple[str, int]]:
        """gets the list of all input devices as (description, index) pairs"""
        return [(name, index) for index, name in self._sound.input_device_map.items()]

    def getAudioDevice(self) -> str:
        """gets the name of the selected audio device"""
        if self._audio_device is None or self._audio_device == DEFAULT_AUDIO_DEVICE_MARKER:
            # use the current system default
            return self._sound.getDefaultInputDevice()
        return self._audio_device

    @property
    def device_name(self) -> str:
        """gets the name of the selected audio device"""
        return self._audio_device

    @device_name.setter
    def device_name(self, value: str):
        """sets the name of the selected audio device"""
        self.setAudioDevice(value)

    def getAudioDeviceIndex(self) -> int:
        """gets the index of the selected audio device"""
        if self._audio_device is None or self._audio_device == DEFAULT_AUDIO_DEVICE_MARKER:
            # use the current system default
            return DEFAULT_AUDIO_DEVICE_INDEX
        name = self._audio_device.casefold()
        for index, device_name in self._sound.input_device_map.items():
            if device_name.casefold().startswith(name):
                return index
        return DEFAULT_AUDIO_DEVICE_INDEX

    def getAudioDeviceFromIndex(self, device_index: int) -> str:
        """gets the name of the audio device corresponding to the given index"""
        if device_index == DEFAULT_AUDIO_DEVICE_INDEX:
            return DEFAULT_AUDIO_DEVICE_MARKER
        device_name = self._sound.input_device_map.get(device_index)
        if device_name is not None:
            return device_name
        return DEFAULT_AUDIO_DEVICE_MARKER

    def setAudioDeviceIndex(self, device_index: int):
        device_name = self._sound.input_device_map.get(device_index)
        if device_name is not None:
            self._audio_device = device_name

    def setAudioDevice(self, device_name: str, validate=False):
        if device_name is not None:
            # ensure the device name exists in the current audio stack
            if device_name == DEFAULT_AUDIO_DEVICE_MARKER:
                self._audio_device = None  # use the default
                return
            if validate:
                # validate the device exists in the current system input devices
                name = device_name.casefold()
                device_name_found = next((d for d in self._sound.input_device_map.values() if d.description().casefold().startswith(name)), None)
                if device_name_found is None:
                    syslog.warning(f"Audio device '{device_name}' not found, using default")
                    self._audio_device = None
                    return
                self._audio_device = device_name
            else:
                # no validation
                self._audio_device = device_name
        else:
            self._audio_device = None

    @property
    def audio_device(self) -> str:
        """gets the name of the selected audio device"""
        return self._audio_device

    @audio_device.setter
    def audio_device(self, value: str):
        self.setAudioDevice(value)

    @property
    def gain(self) -> float:
        """user set gain value for the voice input (microphone) = normal is 1.0"""
        return self._gain

    @gain.setter
    def gain(self, value: float):
        self._gain = value

    @property
    def ptt_input_item(self):
        """input item for push-to-talk (PTT) mode control functionality"""
        return self._ptt_input_item

    @ptt_input_item.setter
    def ptt_input_item(self, value):
        self._ptt_input_item = value

    @property
    def ptt_mode(self) -> VoicePTTMode:
        """gets the current push-to-talk (PTT) mode"""
        return self._ptt_mode

    @ptt_mode.setter
    def ptt_mode(self, value: VoicePTTMode):
        assert isinstance(value, VoicePTTMode), "ptt_mode must be an instance of VoicePTTMode"
        self._ptt_mode = value

    def setVolume(self, value: int, target_name: str = None):
        """sets the volume of the current input device"""
        self._voice.setVolume(value, target_name)

    def getVolume(self, target_name: str = None) -> int:
        """gets the volume of the current input device"""
        return self._voice.getVolume(target_name)

    def _reset(self):
        """reset voices"""
        pass

    def _handle_profile_unload(self):
        """occurs on profile unload before a new profile is loaded"""

        self._data = {}
        self._id_map = {}
        verbose = gremlin.config.Configuration().verbose_mode_voice
        if verbose:
            syslog.info("VOICE: clear data")

    def _register(self, key: str, text=None, description=None) -> VoiceInputItem:
        """registers a new voice input"""
        if not key:
            return None
        key = key.casefold().strip()
        if key in self._data:
            # already in the list
            return self._data[key]

        input_item = VoiceInputItem(key, text, description)
        self._data[key] = input_item
        self._id_map[input_item.id] = input_item
        self.crud.emit()
        return input_item

    def register(self, key: str, text=None, description=None) -> VoiceInputItem:
        """registers a new state"""
        item = self._register(key, text, description)
        if item:
            self._sort()
        return item

    def unregister(self, key: str):
        """removes a voice input from the list"""
        key = key.casefold().strip()
        if key in self._data:
            input_item = self._data[key]
            input_item.unhook()

            id = input_item.id
            del self._data[key]
            del self._id_map[id]

    def add(self, data: VoiceInputItem, emit=True):
        if data and data.key not in self._data:
            self._data[data.key] = data
            self._id_map[data.id] = data
            self._update_commands()
            self._sort()
            if emit:
                self.crud.emit()

    def _sort(self):
        self._data = dict(sorted(self._data.items()))

    def sorted_keys(self) -> list:
        """returns the keys in the state data sorted alphabetically"""
        return list(self._data.keys())

    def exists(self, key: str | VoiceInputItem):
        """true if the key exists in the state data"""
        if isinstance(key, str):
            key = key.casefold().strip()
            return key in self._data

        data: VoiceInputItem = key
        if data.id in self._id_map:
            return True
        if data.key in self._data:
            return True
        return False

    def clear(self):
        """clears all data"""
        if self._data:
            self._data.clear()
            self._id_map.clear()
            self.crud.emit()

    def remove(self, state: VoiceInputItem | str):

        if isinstance(state, str):
            key = state.casefold().strip()
        else:
            key = state.key
        if key in self._data:
            data = self._data[key]
            data.unhook()
            del self._data[key]
            del self._id_map[data.id]
            self.crud.emit()

    def removeId(self, id: str):
        if id in self._id_map:
            data = self._id_map[id]
            data.unhook()
            key = data.key
            del self._data[key]
            del self._id_map[data.id]

    def index(self, item: VoiceInputItem):
        """gets the index of the item in the current list"""
        if item.key in self._data:
            keys = list(self._data.keys())
            return keys.index(item.key)
        return -1

    def getVoices(self) -> list:
        """returns a list of all voice input items"""
        return list(self._data.values())

    @property
    def pttMode(self) -> VoicePTTMode:
        return self._ptt_mode

    @pttMode.setter
    def pttMode(self, mode: VoicePTTMode):
        self._ptt_mode = mode

    @property
    def input_item(self):
        """latched input item for push-to-talk (PTT) mode - none if not set"""
        return self._ptt_input_item

    @input_item.setter
    def input_item(self, input_item: InputItem):
        assert input_item is None or isinstance(input_item, InputItem), "input_item must be an instance of InputItem"
        self._ptt_input_item = input_item

    def __iter__(self):
        return self._data.__iter__()

    def __next__(self):
        return self._data.__next__()

    def __len__(self):
        return len(self._data)

    def __getitem__(self, key):
        if key in self._data:
            return self._data[key]
        return None

    def to_xml(self):
        """persists the voice input configuration data to XML"""
        verbose = gremlin.config.Configuration().verbose_mode_voice
        if verbose:
            syslog.info(f"Persisting voices to XML - voice count: {len(self._data)}")
        root = ElementTree.Element("voices")
        for key in self._data:
            item = self._data[key]
            if item:
                node = item.to_xml()
                if node is not None:
                    root.append(node)

        # persist device selection
        if self._audio_device:
            root.set("device", self._audio_device)
        if self._ptt_mode is not None:
            root.set("ptt-mode", VoicePTTMode.to_string(self._ptt_mode))

        if self._ptt_input_item:
            input_node = self._ptt_input_item.to_xml()
            if input_node is not None:
                ptt_node = ElementTree.Element("ptt-input")
                ptt_node.append(input_node)
                root.append(ptt_node)

        root.set("gain", safe_format(self._gain, float))

        return root

    def __deepcopy__(self, memo):
        # deep copy returns self as this is a singleton object
        return self

    def from_xml(self, root, data=None, extra_data=None):
        """reads saved data"""

        for node in root:
            if node.tag == "voice-input":
                item = VoiceInputItem()
                item.from_xml(node)
                self._data[item.key] = item
                self._id_map[item.id] = item

        self._audio_device = safe_read(root, "device", str, None)
        self._ptt_mode = VoicePTTMode.from_string(safe_read(root, "ptt-mode", str, None))

        master_mode = gremlin.shared_state.master_mode

        # get the master mode object
        profile = gremlin.shared_state.current_profile
        # device = gremlin.joystick_handling.getDevice(StateDeviceTabWidget.device_guid)
        device_modes = profile.get_device_modes(
            gremlin.shared_state.state_tab_guid,
            DeviceType.State,
            DeviceType.to_string(DeviceType.State),
        )
        mode_object = device_modes.ensure_mode_exists(master_mode)

        input_node = root.find("ptt-input")
        if input_node is not None:
            match self._ptt_input_item.input_type:
                case InputType.Keyboard | InputType.KeyboardLatched:
                    input_item = KeyboardInputItem(mode_object)
                case InputType.JoystickButton:
                    input_item = InputItem(mode_object)
                case InputType.OpenSoundControl:
                    input_item = OscInputItem(mode_object)
                case InputType.MIDI:
                    input_item = MidiInputItem(mode_object)
                case InputType.State:
                    input_item = StateInputItem(mode_object)
                case InputType.StreamDeck:
                    input_item = StreamDeckInputItem()
                case _:
                    input_item = None

            if input_item:
                # read the input information
                input_item.from_xml(input_node[0])
                self._ptt_input_item = input_item

        self._ptt_input_id = safe_read(root, "ptt-input-id", str, None)
        self._ptt_device_guid = safe_read(root, "ptt-device-guid", str, None)
        self._gain = safe_read(root, "gain", float, 1.0)
        self._update_commands()
        self._sort()


class VoiceInputItemConfigDialog(gremlin.ui.ui_common.QShowAtCursorDialog):
    """dialog showing the voice input configuration options"""

    def __init__(
        self,
        input_item: VoiceInputItem,
        ref_input_item: VoiceInputItem,
        edit_mode: bool,
        parent=None,
    ):
        """
        :param input_item - the voice input item being edited
        :param ref_input_item - the reference voice input item
        """

        super().__init__(self.__class__.__name__, parent=parent)

        gremlin.shared_state.push_suspend_highlighting()  # prevent device highlight changes while editing a state

        self.setWindowTitle("Voice Input Editor")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self._parent = parent  # list view
        self._is_edit = edit_mode  # edit mode vs new mode
        self.commands = []  # returned commands

        main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(main_layout)

        self._config_widget, self._config_layout = gremlin.ui.ui_common.getGridContainer()
        self.data = input_item
        self.ref_data = ref_input_item  # reference state

        self._text_widget = QtWidgets.QPlainTextEdit()
        # self._text_widget.setAcceptRichText(False)
        self._text_widget.setMinimumWidth(200)
        self._text_widget.setPlainText(input_item.text)

        self._test_widget = QtWidgets.QPushButton("Test")
        self._test_widget.setToolTip("Tests the voice recognition")
        self._test_widget.setEnabled(False)

        self._description_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._description_widget.setText(input_item._description)
        self._description_widget.textChanged.connect(self._description_changed)

        # Removed autorelease widgets and containers as they are no longer needed
        msg = "Punctuation and casing are discarded for voice commands.  Separate multiple commands with a vertical bar (|)."
        self._info_widget = gremlin.ui.ui_common.QInfoBox(msg, hide_key="voice_input_info")

        self._status_widget = gremlin.ui.ui_common.QWarningWidget()

        row = 0
        col = 0

        self._config_layout.addWidget(QtWidgets.QLabel("Description:"), row, col)
        self._config_layout.addWidget(self._description_widget, row, col + 1)

        row += 1
        self._config_layout.addWidget(QtWidgets.QLabel("Voice Command:"), row, col)
        row += 1
        self._config_layout.addWidget(self._text_widget, row, col, 1, -1)

        main_layout.addWidget(self._config_widget)

        main_layout.addWidget(self._status_widget)

        main_layout.addWidget(self._info_widget)

        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        widget = gremlin.ui.ui_common.getHContainer([self.ok_widget, self.cancel_widget], left_stretch=True, widget_only=True)

        main_layout.addWidget(widget)
        self._update_ui()

    @property
    def editMode(self) -> bool:
        """true if the dialog was called in edit mode"""
        return self._is_edit

    def _set_status(self, text: str):
        """sets the status text"""
        self._status_widget.setText(text)
        self._update_ui()

    def _clear_status(self):
        """clears and hides the status text"""
        self._set_status(None)

    def _validate(self):
        sd = VoiceData()
        msg = None
        key = self.data.key

        # blank
        enabled = bool(key)
        if not enabled:
            msg = "Name cannot be blank."

        # words
        if re.search(r"\s", key):
            enabled = False
            msg = "Name cannot include spaces"

        if enabled:
            voice = sd.getVoice(self.data.key)
            if voice and self.ref_data and voice != self.ref_data:
                enabled = False
                msg = "Name is not case sensitive and must be unique."

        self.ok_widget.setEnabled(enabled)
        self._set_status(msg)

    @QtCore.Slot()
    def _name_changed(self):
        self.data.key = self._name_widget.text()
        self._validate()

    @QtCore.Slot()
    def _description_changed(self):
        description = self._description_widget.text()
        self.data.setDescription(description)

    @QtCore.Slot(bool)
    def _default_changed(self, checked: bool):
        widget = self.sender()
        self.data.default_value = widget.data

    def _ok_button_cb(self):
        """ok button pressed"""
        # ensure the defined phrases are unique and not already used

        voice_data = VoiceData()
        text = self._text_widget.toPlainText()
        self.data.text = text

        new_commands = voice_data.getCommandsFromText(self.data.text)
        commands = voice_data.getCommands()  # defined commands in the profile

        if not self._is_edit:
            # validate if not editing
            matches = [vc for vc in new_commands for item in commands if item.hashedKey == vc.hashKey]
            if matches:
                vc = matches[0]
                gremlin.ui.ui_common.MessageBox(
                    title="Voice Input Error",
                    prompt=f"[{vc.phrase}] is already defined as a voice command.\nVoice commands must be unique and are not case sensitive.",
                )
                return

        else:
            gremlin.shared_state.pop_suspend_highlighting()
            self.commands = commands

        self.accept()

    def _cancel_button_cb(self):
        """cancel button pressed"""
        gremlin.shared_state.pop_suspend_highlighting()
        self.reject()

    def _update_ui(self):
        """updates the dialog controls based on options"""

        text = self.data.text
        if not text:
            self._status_widget.setText("Please enter one or more voice commands.")
        else:
            self._status_widget.setText("")
        self._status_widget.setVisible(bool(self._status_widget.text()))


class VoiceDeviceTabWidget(gremlin.input_item.BaseDeviceTabWidget):
    # IMPORTANT: MUST BE A DID FORMATTED ID ON CUSTOM INPUTS
    device_guid = gremlin.shared_state.voice_tab_guid

    def __init__(
        self,
        profile: gremlin.base_profile.Profile,
        mode: str,
        object_name="Voice Device",
        parent=None,
    ):
        """Creates a new object instance.

        :param profile profile data of the entire device
        :param current_mode currently active mode
        :param parent the parent of this widget
        """

        device = gremlin.joystick_handling.getDevice(self.device_guid)
        super().__init__(
            device=device,
            profile=profile,
            mode=mode,
            object_name=object_name,
            custom_input_widget_callback=self._custom_widget_handler,
            blank_input_message="Please add a voice input.",
            parent=parent,
        )

        self._widget_map = {}

        button_container_widget = QtWidgets.QWidget()
        button_container_layout = QtWidgets.QHBoxLayout(button_container_widget)

        config = gremlin.config.Configuration()
        self._voice_data = VoiceData()

        # lock widget
        lock_widget = gremlin.ui.ui_common.QInputLockWidget(data=self.device_guid)
        widget = gremlin.ui.ui_common.getHContainer(["Voice Inputs", "||", lock_widget], widget_only=True)
        self.addLeftPanelHeaderWidget(widget)

        if config.show_container_id:
            device = gremlin.joystick_handling.get_device(self.device_guid)
            width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.device_id)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device ID:", widget_only=True)
            self.addLeftPanelHeaderWidget(widget)
            w1 = widget

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.name)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Name:", widget_only=True)
            self.addLeftPanelHeaderWidget(widget)
            w2 = widget

            gremlin.ui.ui_common.synchronize_grids([w1, w2])

        self._filter = gremlin.util.decorate_filter(config.state_filter)
        self._category_filter = config.state_category_filter

        # data model
        model = VoiceInputItemModel(
            profile,
            custom_load_handler=self._load_handler,
            custom_filter_handler=self._filter_data,
            item_changed_handler=self.onItemChanged,
        )

        self.setInputItemListModel(model)

        # clear and add buttons to add/clear all states
        clear_button = gremlin.ui.ui_common.ConfirmPushButton("Clear", show_callback=self._show_clear_cb)
        icon = gremlin.ui.ui_common.Icons.trashIcon()
        clear_button.setIcon(icon)
        clear_button.setToolTip("Deletes all states")
        clear_button.confirmed.connect(self._confirm_clear_inputs_cb)
        button_container_layout.addWidget(clear_button)

        test_button = gremlin.ui.ui_common.QDataPushButton("Test", callback=self._test_input_cb)
        button_container_layout.addWidget(test_button)

        # configure button
        configure_widget = gremlin.ui.ui_common.QIconPushButton(
            icon=gremlin.ui.ui_common.Icons.gearIcon(),
            text="Voice Recognition Options",
            tooltip="Voice Recognition Options",
            callback=self._handle_configure,
            height=24,
            icon_size=18,
        )

        button_container_layout.addWidget(configure_widget)

        # right align
        button_container_layout.addStretch(1)

        # sort inputs
        sort_button = QtWidgets.QPushButton("Sort")
        icon = gremlin.ui.ui_common.Icons.sortIcon()
        sort_button.setIcon(icon)
        sort_button.clicked.connect(self._sort_input_cb)
        button_container_layout.addWidget(sort_button)

        # Key add input button
        add_button = QtWidgets.QPushButton("Add")
        add_button.setToolTip("Adds a new state to the profile")
        icon = gremlin.ui.ui_common.Icons.addIcon()
        add_button.setIcon(icon)
        add_button.clicked.connect(self._add_input_cb)

        button_container_layout.addWidget(add_button)

        # Handle user interaction
        self.addLeftPanelHeaderWidget(button_container_widget)

        self.inputItemListModel.refresh()

        # refresh on configuration change
        el = gremlin.event_handler.EventListener()
        # lock all inputs
        el.lock_inputs.connect(self._handle_lock_inputs)
        el.unlock_inputs.connect(self._handle_unlock_inputs)
        el.find_next.connect(self._handle_find_next)

    def _handle_configure(self):
        """callback for the configure button"""
        input_item = self._voice_data.input_item
        mode = self._voice_data.ptt_mode
        device_name = self._voice_data.device_name

        self._config_dialog = VoiceSettingsDialog(mode=mode, input_item=input_item, device_name=device_name, parent=self)
        self._config_dialog.accepted.connect(self._handle_configure_accepted)
        self._config_dialog.show()

    def _handle_configure_accepted(self):
        """callback for when the configure dialog is accepted"""
        # Implement the logic to handle the acceptance of the configuration dialog
        dialog = self._config_dialog
        self._voice_data.input_item = dialog.input_item
        self._voice_data.ptt_mode = dialog.mode
        self._voice_data.device_name = dialog.device_name

    def _test_input_cb(self):
        """callback for the test input button"""
        pass

    def _filter_data(self, input_item) -> bool:
        """custom filter handler - true if the data is included in the filter, false otherwise"""

        if not self._filter:
            return True  # ok
        item: VoiceInputItem = input_item.input_id
        key = item.key
        if not key:
            # no key = match
            return True

        key = item.key.casefold().strip()
        if self._filter in key:
            return True
        return fnmatch.fnmatch(key, self._filter)

    def _custom_widget_handler(self, list_view, index: int, identifier, data, parent=None):
        """creates a widget for the input

        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item

        """

        assert isinstance(data, VoiceInputItem), f"Unexpected type in widget handler - expected VoiceInputItem and got [{type(data).__name__}]"

        widget = InputItemWidget(
            input_item=identifier.input_item,
            populate_ui_callback=self._populate_input_widget_ui,
            mapping_changed_callback=self._update_input_widget,
            confirm_delete_callback=self._handle_confirm_delete,
            config_external=True,
            parent=parent,
            data=data,
        )
        widget._identifier = data
        widget.create_action_icons(data)
        input_item: VoiceInputItem = data

        vd = VoiceData()

        title = "Voice Input"
        widget.setTitle(title)

        widget.enable_edit()
        widget.enable_close()
        widget.clearWidgets()
        widget.setIcon("ri.user-voice-fill")

        commands = input_item.commands
        if commands:
            vc: VoiceCommand
            for vc in input_item.commands:
                widget.addWidget(QtWidgets.QLabel(vc.phrase))
        else:
            widget.addWidget(QtWidgets.QLabel("No commands available"))

        return widget

    def _populate_input_widget_ui(self, input_widget, container_widget, data=None):
        """called when an input is created for custom content"""
        self._update_input_widget(input_widget, container_widget)

    def _update_input_widget(self, input_widget, container_widget):
        """called when the widget has to update itself on a data change"""
        input_item: VoiceInputItem = input_widget.input_item
        if not input_item.commands:
            input_widget.setCustomContent(QtWidgets.QLabel("No commands found"))
            return
        widgets = []
        for command in input_item.commands:
            widgets.append(QtWidgets.QLabel(command.phrase))

        container_widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)
        input_widget.setCustomContent(container_widget)

    def _handle_confirm_delete(self, input_item: gremlin.input_item.InputItem):
        """confirms if an input should be deleted"""
        result = gremlin.ui.ui_common.ConfirmBox("Delete this input?")
        return result

    def _load_handler(self, model: VoiceInputItemModel, emit=True) -> bool:
        """called when the data model for the input list needs to be updated - refreshes the model view"""
        voice = self.profile.voice
        self._input_items = {}

        keys = [key for key in voice]
        keys.sort()

        model.pushSuspend()
        model.clear(emit=False)

        changed = False
        index = 0
        for key in keys:
            data = voice[key]
            input_item = data
            self._input_items[key] = input_item
            changed = True
            model.setItemAt(index, input_item)
            index += 1

        model.applyFilter()  # update model filters and sort
        model.popSuspend()

        if changed and emit:
            model.trigger()  # causes an update
        return changed

    def onItemChanged(self, model, index, new_item, old_item, operation):
        redraw = False
        vd = VoiceData()
        match operation:
            case "add":
                # handle add operation
                vd.add(new_item)
                redraw = True
            case "remove":
                vd.remove(old_item)
                redraw = True
        if redraw:
            self.inputItemListView.redraw()  # tell the list

    def onInputListViewCreated(self):
        """called when list view is created"""
        self.inputItemListView.item_edit.connect(self._edit_item_cb)
        self.inputItemListView.item_closed.connect(self._close_item_cb)

    def onInputListViewRemoved(self):
        """called when list view is removed"""
        self.inputItemListView.item_edit.disconnect(self._edit_item_cb)
        self.inputItemListView.item_closed.disconnect(self._close_item_cb)

    def _handle_model_changed_cb(self, data=None, force: bool = False):
        """called when the model changes"""
        self._filter_widget.updateCounts()

    @property
    def inputCount(self) -> int:
        """number of inputs in the device"""
        return self.inputItemListModel.rows()

    @property
    def inputWidgetCount(self) -> int:
        """number of input widgets currently in the device"""
        return self.inputItemListView.count()

    def _handle_lock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_lock_inputs_ui, data)  # ensure on UI thread

    def _handle_unlock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_unlock_inputs_ui, data)  # ensure on UI thread

    def _handle_find_next(self):
        """finds the next item"""
        if gremlin.shared_state.current_tab_device_guid == gremlin.shared_state.state_tab_id:
            term = gremlin.config.Configuration().state_last_search_term  # last search term
            if term:
                gremlin.util.InvokeUiMethod(self._filter_widget.find_next, term)

    def _handle_lock_inputs_ui(self, data):
        """lock all inputs event"""

        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = True
            self.setUpdatesEnabled(True)

    def _handle_unlock_inputs_ui(self, data):
        """unlock all inputs event"""
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = False
            self.setUpdatesEnabled(True)

    def _show_clear_cb(self):
        return self.inputItemListModel.rows() > 0

    def _config_changed_cb(self):
        gremlin.util.InvokeUiMethod(self._config_changed_ui)

    def _config_changed_ui(self):
        """called when configuraition has changed"""
        gremlin.util.assert_ui_thread()
        self.refresh()

    def getOverrideInputType(self):
        """override type"""
        return InputType.JoystickButton

    @QtCore.Slot()
    def _add_input_cb(self):
        """Adds a new state to the inputs list ADD STATE"""
        input_item = VoiceInputItem()
        input_item.suppressEvents()

        self._edit_dialog = VoiceInputItemConfigDialog(input_item, None, edit_mode=False, parent=self)
        self._edit_dialog.accepted.connect(self._dialog_ok_confirm_cb)
        self._edit_dialog.rejected.connect(self._dialog_cancel_cb)
        gremlin.util.centerDialog(self._edit_dialog)
        self._edit_dialog.showNormal()

    def _edit_item_cb(self, widget, index, input_item):
        """edit the state"""
        tmp_input_item = input_item.clone()
        tmp_input_item.suppressEvents()
        self._edit_dialog = VoiceInputItemConfigDialog(tmp_input_item, input_item, edit_mode=True, parent=self)
        self._edit_dialog.accepted.connect(self._dialog_ok_confirm_cb)
        self._edit_dialog.rejected.connect(self._dialog_cancel_cb)
        gremlin.util.centerDialog(self._edit_dialog)
        self._edit_dialog.showNormal()

    def _dialog_cancel_cb(self):
        self._edit_dialog.deleteLater()
        self._edit_dialog = None

    def _dialog_ok_confirm_cb(self):
        """called when edit dialog closes with ok on a new state"""
        try:
            verbose = gremlin.config.Configuration().verbose_mode_state
            edit_mode = self._edit_dialog.editMode

            edited_input_item = self._edit_dialog.data
            input_item = self._edit_dialog.ref_data if edit_mode else edited_input_item

            voice_data = VoiceData()

            if not edit_mode:
                # add the new entry
                index = self.inputItemListModel.add(input_item)
                if verbose:
                    syslog.info(f"adding id: [{input_item.id}]  key: [{input_item.key}] at index [{index}]")

                # change the state
                voice_data.add(edited_input_item)

            else:
                # edit an existing entry

                index = self.inputItemListModel.indexOf(input_item)
                assert index != -1, "Reference input is missing from model"
                if verbose:
                    syslog.info(f"modifying id: [{input_item.id}]  key: [{edited_input_item.key}] at index [{index}]")

                # copy changed data
                input_item.enableEvents()
                input_item.key = edited_input_item.key
                input_item.setDescription(edited_input_item.description)
                input_item.text = edited_input_item.text

                self.inputItemListModel.refresh()
                self._filter_widget.updateCounts()

            index = self.inputItemListView.indexOf(input_item)
            syslog.info(f"selecting state index: [{index}] for [{input_item.input_id}]")
            self.selectInputItemIndex(index)

            el = gremlin.event_handler.EventListener()
            el.device_mapping_changed.emit(self._device_id)
        finally:
            self._edit_dialog.deleteLater()
            self._edit_dialog = None
            self.inputItemListView.redraw()

    def _sort_input_cb(self):
        """sorts states by key name"""

        if not self.inputItemListModel.rows():
            # nothing to sort
            return

        # current selection (so we can select the item that was selected if the order changes)
        index = self._last_selected_index
        current_selection = None
        if index != -1:
            current_selection = self.inputItemListModel.data(index)

        self.inputItemListModel.sort(self._sort_callback)

        if current_selection:
            # reselect the saved item - because the inputs were likely recreated - we can't compare the old with the new
            # so we need to find the matching data packet
            self.selectInputItemIndex(current_selection.index)

    def _sort_callback(self, items: list):
        """callback for sorting inputs in this device"""
        items.sort(key=lambda x: x.input_id.key.casefold() if x.input_id.key else "")
        return items

    def _close_item_cb(self, widget, index, data):
        """called when the close button is clicked"""
        key = self.getRegisteredKeyIndex(index)
        self.unregisterWidget(key)
        if not self.inputItemListModel.rows():
            # display blank page if no item left
            self._blank_input()

    def _confirm_clear_inputs_cb(self):
        """clears all input keys"""
        sd = VoiceData()
        sd.clear()
        profile = gremlin.shared_state.current_profile
        profile.state.clear()

        self.inputItemListModel.clear()

        self._filter_widget.updateCounts()

        # add a blank input configuration if nothing is selected - the configuration widget is always the second widget of the main layout
        self._blank_input()
