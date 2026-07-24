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

from __future__ import annotations  # deprecated with python 3.14+
import os
from PySide6 import QtCore, QtGui, QtMultimedia, QtWidgets
from lxml import etree as ElementTree
import html
from typing import Callable
import gremlin.util
import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
from gremlin.util import load_icon, TimedRandomInt
import gremlin.input_item
import gremlin.ui.ui_common
from gremlin.util import safe_format, safe_read
import logging
import gremlin.sound
from gremlin.sound import Sound, PhraseData, EdgeTTSVoice
import enum
import gremlin.ktts
import gremlin.tts
import gremlin.shared_state
import random
import time
from gremlin.types import PlaybackMode, PlayMode


syslog = logging.getLogger("system")



class AiTTSWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.setLayout(self.main_layout)


class PlaySoundWidget(gremlin.input_item.AbstractActionWidget):
    """Widget for the resume action."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, PlaySound)

    def _create(self, action_data):
        self.action_data: PlaySound = action_data


    def _create_ui(self):
        """creates the user interface for the widget"""

        verbose = gremlin.config.Configuration().verbose_mode_sound

        self.action_data.etts_callback = self._update_etts_ui

        container_widgets = []
        ktts_enabled = gremlin.ktts.KTTS_ENABLED

        self.icon_widget = QtWidgets.QLabel()
        self.file_path_widget = QtWidgets.QLineEdit()
        self.file_path_widget.installEventFilter(self)
        self.file_path_widget.textChanged.connect(self._file_changed)
        self.edit_path_widget = QtWidgets.QPushButton()
        self.edit_path_widget = gremlin.ui.ui_common.Buttons.getEditWidget()
        self.edit_path_widget.clicked.connect(self._new_sound_file)
        self.volume_widget = gremlin.ui.ui_common.QIntLineEdit(
            min_range=0,
            max_range=100,
            value=self.action_data.playback_volume,
            callback=self._volume_changed,
            chars=4,
            tooltip="Playback volume as a percentage 0 to 100.",
        )

        self.icon_loaded = gremlin.ui.ui_common.load_icon("fa5s.check-circle", qta_color="#16B11E")
        self.icon_available = gremlin.ui.ui_common.load_icon("fa5s.check-circle", qta_color="#AEB116")
        self.icon_unavailable = gremlin.ui.ui_common.load_icon("fa5s.times-circle", qta_color="#C08224")

        self.aitts_state_widget = gremlin.ui.ui_common.QIconLabel()

        options = [
            ("Audio file", PlayMode.AudioFile, "Plays an audio file"),
            (
                "TTS (local)",
                PlayMode.PyTTS,
                "Generates an audio file from text via local TTS (uses operating system TTS - options and quality may be limited), dynamic generation supported.",
            ),
            ("AI (Edge-TTS)", PlayMode.EdgeAI, "Generates an audio file from text via AI (requires Edge-TTS installation), dynamic generation supported."),\
        ]
        if ktts_enabled:
            options.append(
                ("AI (Coqui-TTS)", PlayMode.CoquiAI, "Generates an audio file from text via AI (requires Coqui-TTS installation)"),
            )


        widgets = ["Mode:"]
        for name, data, tooltip in options:
            rb = gremlin.ui.ui_common.QDataRadioButton(name, data, callbackEx=self._handle_mode_change, value=self.action_data.mode == data, tooltip=tooltip)
            widgets.append(rb)

        widgets.append(self.aitts_state_widget)
        mode_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

        self.main_layout.addWidget(mode_container)

        self.tts_text_widget = QtWidgets.QPlainTextEdit()
        self.tts_text_widget.setPlainText(self.action_data.text)
        self.tts_text_widget.textChanged.connect(self._content_changed_cb)
        self.tts_text_widget.installEventFilter(self)

        self.tts_file_widget = gremlin.ui.ui_common.QLineEdit(text=self.action_data.tts_file)
        self.tts_file_widget.setReadOnly(True)

        self.tts_file_delete_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback=self._handle_file_delete, tooltip="Delete the audio file")
        self.tts_file_rename_widget = gremlin.ui.ui_common.QDataPushButton("Rename", callback=self._handle_file_rename, tooltip="Rename the audio file")

        # speaker selection for pytts
        self.ptts_speaker_widget = gremlin.ui.ui_common.QDataComboBox(auto_adjust=True, tooltip="Selected speaker for AI voice generation.")
        self.ptts_speaker_widget.setCallback(self._handle_ptts_speaker_changed)

        tts = gremlin.tts.TextToSpeech()
        self.ptts_speed_widget = gremlin.ui.ui_common.QIntLineEdit(
            min_range=tts.rate_offset_min,
            max_range=tts.rate_offset_max,
            value=self.action_data.ptts_speed,
            callback=self._handle_ptts_speed_changed,
            tooltip="Words per minute (wpm) rate modifier for the generated audio.\n100 is the normal rate.",
        )
        self.ptts_speed_widget.doubleClick.connect(self._handle_ptts_speed_reset) # double click = reset

        self.ptts_volume_widget = gremlin.ui.ui_common.QIntLineEdit(min_range = 0, max_range = 100, value=self.action_data.ptts_volume, callback=self._handle_ptts_volume_changed, tooltip="Playback volume for the generated audio as a percentage 0 to 100.")
        self.ptts_volume_widget.doubleClick.connect(self._handle_ptts_volume_reset)

        # speaker selection for ktts
        if ktts_enabled:
            self.ktts_speaker_widget = gremlin.ui.ui_common.QDataComboBox(tooltip="Selected speaker for AI voice generation.")
            self.ktts_speaker_widget.setCallback(self._handle_ktts_speaker_changed)

        # speaker selection for edge tts
        self.etts_speaker_widget = gremlin.ui.ui_common.QDataComboBox(tooltip="Selected speaker for AI voice generation.")
        self.etts_speaker_widget.setCallback(self._handle_etts_speaker_changed)

        # locale filter for edge tts
        self.etts_locale_widget = gremlin.ui.ui_common.QDataComboBox(tooltip="Locale filter for Edge TTS.")
        self.etts_locale_widget.setCallback(self._handle_etts_locale_changed)

        # gender filter
        self.etts_gender_widget = gremlin.ui.ui_common.QDataComboBox(tooltip="Gender filter for Edge TTS.")
        self.etts_gender_widget.setCallback(self._handle_etts_gender_changed)

        ktts_refresh_speaker_widget = gremlin.ui.ui_common.Buttons.getRefreshWidget(
            label=None, callback=self._handle_refresh_ktts_speakers, tooltip="Refresh available AI speakers"
        )

        etts_refresh_speaker_widget = gremlin.ui.ui_common.Buttons.getRefreshWidget(
            label=None, callback=self._handle_refresh_etts_speakers, tooltip="Refresh available AI speakers"
        )

        ptts_refresh_speaker_widget = gremlin.ui.ui_common.Buttons.getRefreshWidget(
            label=None, callback=self._handle_refresh_ptts_speakers, tooltip="Refresh available AI speakers"
        )

        icon = gremlin.ui.ui_common.load_icon("ri.voiceprint-fill")
        self.generate_widget = gremlin.ui.ui_common.QDataPushButton("Generate", callback=self._handle_generate, tooltip="Generate the AI voice.")
        self.generate_widget.setIcon(icon)

        self.auto_generate_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Auto Generate",
            value=self.action_data.auto_generate,
            callback=self._handle_auto_generate_changed,
            tooltip="Automatically generate and cache all AI voices (select modes only).",
        )

        self.generate_play_widget = gremlin.ui.ui_common.Buttons.getPlayWidget(tooltip="Generate & Play", callback=self._handle_play)

        self.etts_speed_widget = gremlin.ui.ui_common.QFloatLineEdit(
            min_range=0.1,
            max_range=10.0,
            value=self.action_data.etts_speed,
            callback=self._handle_etts_speed_changed,
            tooltip="Speed rate modifier for the generated audio.\n1.0 is the normal rate.",
        )

        if ktts_enabled:
            self.ktts_speed_widget = gremlin.ui.ui_common.QFloatLineEdit(
                min_range=0.1,
                max_range=10.0,
                value=self.action_data.ktts_speed,
                callback=self._handle_ktts_speed_changed,
                tooltip="Speed rate modifier for the generated audio.\n1.0 is the normal rate.",
            )


        self.etts_pitch_widget = gremlin.ui.ui_common.QIntLineEdit(
            min_range=-500,
            max_range=500,
            value=self.action_data.etts_pitch,
            callback=self._handle_etts_pitch_changed,
            tooltip="Pitch adjustment for the generated audio in Hz offset.\n0 means no adjustment. +/- 100 Hz range.",
        )

        self.etts_volume_widget = gremlin.ui.ui_common.QIntLineEdit(
                    min_range=-100,
                    max_range=100,
                    value=self.action_data.etts_volume,
                    callback=self._handle_etts_volume_changed,
                    tooltip="Volume adjustment for the generated audio.\n0 is the normal volume. Range is -100 to 100.  0 means normal.\nNote: this is not the same as the playback volume.  This is the generation volume.",
                )

        widgets = [
            self.auto_generate_widget,
            self.generate_widget,
            (self.generate_play_widget, 100),

        ]

        playback_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

        self.tts_text_container = gremlin.ui.ui_common.getVContainer(["Text:", self.tts_text_widget], widget_only=True)

        # self.tts_file_container_widget = gremlin.ui.ui_common.getHContainer(
        #                 [self.tts_file_widget, self.tts_file_delete_widget, self.tts_file_rename_widget,playback_container], label="Cache file:", widget_only=True
        #             )

        widgets = [
            "PTTS Generation Options:",
            gremlin.ui.ui_common.getHContainer(["Voice:", self.ptts_speaker_widget, ptts_refresh_speaker_widget,
                                                "Rate (wpm):", self.ptts_speed_widget,
                                                "Volume (gen):", self.ptts_volume_widget]
                                                , widget_only=True),
        ]

        self.ptts_container = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)


        if ktts_enabled:
            widgets = [
                "KTTS Generation Options:",
                gremlin.ui.ui_common.getHContainer(["Voice:", self.ktts_speaker_widget, ktts_refresh_speaker_widget], widget_only=True),
                gremlin.ui.ui_common.getHContainer(["KTTS speed:", self.ktts_speed_widget], widget_only=True),
            ]

            self.ktts_container = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)

        widgets = [
            "ETTS Generation Options:",
            gremlin.ui.ui_common.getHContainer(["Locale:", self.etts_locale_widget, "Gender:", self.etts_gender_widget, "Voice:", self.etts_speaker_widget, etts_refresh_speaker_widget,"||"], widget_only=True),
            gremlin.ui.ui_common.getHContainer(["Rate (gen):", self.etts_speed_widget, "Pitch Offset (Hz):", self.etts_pitch_widget, "Volume (gen):", self.etts_volume_widget], widget_only=True),
        ]
        self.etts_container = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)



        self.play_widget = QtWidgets.QPushButton("Play")
        self.play_widget.setIcon(load_icon("ei.play", qta_color=gremlin.ui.ui_common.Color.activeColor()))
        self.play_widget.setToolTip("Plays the audio as configured")
        self.play_widget.clicked.connect(self._handle_play)

        widgets = []
        for mode in PlaybackMode:
            checked = mode == self.action_data.playback_mode
            match mode:
                case PlaybackMode.RoundRobin:
                    label = "Round Robin"
                    tooltip = "Plays audio in a round-robin fashion, cycling through available samples in sequence."
                case PlaybackMode.Random:
                    label = "Random"
                    tooltip = "Plays a random audio sample from the available samples."
                case PlaybackMode.TimedRandom:
                    label = "Timed Random"
                    tooltip = "Plays a random audio sample from the available samples at timed intervals."
                case _:
                    raise ValueError(f"Unsupported playback mode: {mode}")
            widgets.append(gremlin.ui.ui_common.QDataRadioButton(label=label, tooltip=tooltip, value= checked, callbackEx = self._handle_playback_mode_changed, data = mode))

        self.playback_mode_widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

        self.loops_widget = gremlin.ui.ui_common.QIntLineEdit(
            min_range=1,
            max_range=100,
            value=self.action_data.loops,
            callback=self._handle_loops_changed,
            chars=4,
            tooltip="Number of time the sample will play.\n1 is the default.",
        )
        self.fadein_widget = gremlin.ui.ui_common.QIntLineEdit(
            min_range=0,
            value=self.action_data.fadein_ms,
            callback=self._handle_fadein_changed,
            chars=4,
            tooltip="Time in ms to reach the maximum volume once the sample starts playing.\nUse 0 to disable (default).",
        )
        self.fadeout_widget = gremlin.ui.ui_common.QIntLineEdit(
            min_range=0,
            value=self.action_data.fadeout_ms,
            callback=self._handle_fadeout_changed,
            chars=4,
            tooltip="Time in ms for the sample to fade out once it starts playing.\nUse 0 to disable (default).",
        )

        self.playback_rate_widget = gremlin.ui.ui_common.QFloatLineEdit(
            min_range=0.1,
            max_range=10.0,
            value=self.action_data.playback_rate,
            callback=self._handle_playback_rate_changed,
            tooltip="Speed rate modifier for the playback audio.\n1.0 is the normal rate.",
        )


        self.playback_widget = gremlin.ui.ui_common.QIntLineEdit(
            min_range=0,
            value=self.action_data.playback_ms,
            callback=self._handle_playback_changed,
            chars=4,
            tooltip="Maximum time in ms the sample has to play.\nThe sample will be cut short if the specified time is shorter than the normal sample play time.\nUse 0 to disable (default).",
        )

        self.stop_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Stop previous audio",
            value=self.action_data.stop_previous,
            callback=self._handle_stop_audio_changed,
            tooltip="If checked, any other audio playing will stop before playing this sample.",
        )

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        device_index = self.action_data.getAudioDeviceIndex()

        source = [(d.description(), index) for index, d in self.action_data.device_map.items()]

        self.audio_device_selector = gremlin.ui.ui_common.QDataComboBox(callback=self._handle_audio_change, source=source, value=device_index)
        self.default_widget = gremlin.ui.ui_common.QDataPushButton("Default", callbackEx=self._handle_select_default, tooltip="Select system default")

        self.sync_widget = gremlin.ui.ui_common.QDataPushButton(
            "Sync All", callback=self._handle_sync_all, tooltip="Set all Play Sound actions in the profile to this device"
        )

        msg = """Samples played with this action will play concurrently as they are triggered.  Use the stop option to terminate prior audio streams before triggering the playback.  Playback timing options with a value of zero (0) means disabled.
For text to speech (tts) modes, multiple samples can be provided by separating them with vertical bars (|).  If multiple samples are specified, the playback mode will determine how the samples are selected.
"""

        info_widget = gremlin.ui.ui_common.QInfoBox(msg, hide_key="play-sound")

        widgets = ["Playback device:", self.audio_device_selector, self.default_widget, self.sync_widget]

        audio_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

        widget = gremlin.ui.ui_common.QDataCheckbox(
            "Randomize from folder",
            value=self.action_data.randomize_sound_file,
            callback=self._handle_folder_play_changed,
            tooltip="If enabled, will play a random audio file from the specified folder containing the sound source.",
        )

        widgets = [self.icon_widget, self.file_path_widget, self.edit_path_widget, widget]

        self.playback_file_container = gremlin.ui.ui_common.getHContainer(widgets, "Sound file:", widget_only=True)

        widgets = ["Volume:", self.volume_widget, "Loops:", self.loops_widget, self.stop_widget]

        playback_widget = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

        widgets = [
            "Playback (ms):",
            self.playback_widget,
            "Fade-in (ms):",
            self.fadein_widget,
            "Fade-out (ms)",
            self.fadeout_widget,
            self.playback_mode_widget,
            playback_container,
        ]

        options_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

        self.stack_widget = QtWidgets.QStackedWidget()

        self._blank_widget = QtWidgets.QLabel("Select a play mode.")

        # widget = gremlin.ui.ui_common.getVContainer([self._blank_widget, "||", gremlin.ui.ui_common.QEmptyWidget(), "||"], widget_only=True)
        widget = gremlin.ui.ui_common.getVContainer(self._blank_widget, widget_only=True)
        # widget.setContentsMargins(4, 4, 4, 4)
        #widget.setProperty("cssClass", "box_frame")
        # widget.setMaximumHeight(40)

        self._stack_map = {}
        self._stack_map[PlayMode.Blank] = 0  # index 0 - blank
        self._stack_map[PlayMode.EdgeAI] = 1  # index 1 - ETTS
        self._stack_map[PlayMode.PyTTS] = 2  # index 2  - PyTTS
        if ktts_enabled:
            self._stack_map[PlayMode.CoquiAI] = 3  # index 2 - KTTS

        self.stack_widget.addWidget(widget)  # index 0 - blank
        self.stack_widget.addWidget(self.etts_container)  # index 1 ETTS
        self.stack_widget.addWidget(self.ptts_container)  # index 2 PyTTS
        if ktts_enabled:
            self.stack_widget.addWidget(self.ktts_container)  # index 3 KTTS

        container_widgets.append(audio_container)
        container_widgets.append(self.playback_file_container)

        # holds the combined tts options - text, mode options, file options
        widgets = [self.tts_text_container, self.stack_widget] #, self.tts_file_container_widget]
        self.tts_container_widget = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)

        container_widgets.append(self.tts_container_widget)

        container_widgets.append(options_container)
        container_widgets.append(playback_widget)

        container_widgets.append(self._execute_widget)
        container_widgets.append(info_widget)

        self.main_layout.addWidget(gremlin.ui.ui_common.getVContainer(container_widgets, widget_only=True))

        self._update_speakers()  # update voice lists

        self._update_ui()



    @QtCore.Slot(bool)
    def _handle_folder_play_changed(self, checked: bool):
        self.action_data.randomize_sound_file = checked

    def _handle_auto_generate_changed(self, checked: bool):
        self.action_data.auto_generate = checked

    def _handle_playback_mode_changed(self, widget, checked):
        if checked:
            mode = widget.data
            self.action_data.playback_mode = mode

    def _handle_ptts_volume_reset(self):
        self.action_data.ptts_volume = 100
        self.ptts_volume_widget.setValue(100)

    def _handle_ptts_speed_reset(self):
        self.action_data.ptts_speed = 100
        self.ptts_speed_widget.setValue(100)

    def _handle_ptts_volume_changed(self, value: int):
        self.action_data.ptts_volume = value

    def _update_ui(self):

        tts_visible = self.action_data.mode in [PlayMode.CoquiAI, PlayMode.EdgeAI, PlayMode.PyTTS]
        self.tts_container_widget.setVisible(tts_visible)
        self.playback_file_container.setVisible(self.action_data.mode == PlayMode.AudioFile)


        mode = self.action_data.mode
        if mode in (PlayMode.CoquiAI, PlayMode.EdgeAI, PlayMode.PyTTS):
            playback_enabled = bool(self.action_data.text)
            self.play_widget.setEnabled(playback_enabled)
            self.generate_widget.setEnabled(playback_enabled)
            self.generate_play_widget.setEnabled(playback_enabled)
        else:
            playback_enabled = bool(self.action_data.sound_file)
            self.play_widget.setEnabled(playback_enabled)

        generate_visible = mode in (PlayMode.CoquiAI, PlayMode.EdgeAI, PlayMode.PyTTS)
        self.generate_widget.setVisible(generate_visible)
        self.auto_generate_widget.setVisible(generate_visible)

        match mode:
            case PlayMode.CoquiAI:
                if not self.action_data.ktts_enabled:
                    return
                ktts = gremlin.ktts.KTTS()

                generate_enabled =ktts.is_available() and self.action_data.text is not None and self.action_data.text != ""

                wav = self.action_data.tts_file
                play_enabled = wav is not None and os.path.isfile(wav)

                speed_visible = ktts.is_speed_available()
                delete_enabled = play_enabled

                if wav is not None and os.path.isfile(wav):
                    self.tts_file_widget.setText(wav)
                else:
                    self.tts_file_widget.setText("not generated")

                self.etts_speed_widget.setEnabled(speed_visible)
                self.generate_widget.setEnabled(generate_enabled)
                self.tts_file_delete_widget.setEnabled(delete_enabled)

                # ktts status
                if ktts.is_loaded():
                    icon = self.icon_loaded
                    label = "Ready"
                elif ktts.is_available():
                    icon = self.icon_available
                    label = "Available"
                else:
                    label = "Unavailable"
                    icon = self.icon_unavailable
                self.aitts_state_widget.setText(label)
                self.aitts_state_widget.setIcon(icon)

            case PlayMode.EdgeAI:
                etts = gremlin.sound.EdgeTTS()

                generate_enabled = etts.is_available() and self.action_data.text is not None and self.action_data.text != ""



                wav = self.action_data.tts_file
                play_enabled = wav is not None and os.path.isfile(wav)
                speed_visible = True
                pitch_visible = True
                delete_enabled = play_enabled

                if wav is not None and os.path.isfile(wav):
                    self.tts_file_widget.setText(wav)
                else:
                    self.tts_file_widget.setText("not generated")

                self.etts_speed_widget.setEnabled(speed_visible)
                self.tts_file_delete_widget.setEnabled(delete_enabled)

                # etts status
                icon = self.icon_available
                label = "Available"
                self.aitts_state_widget.setText(label)
                self.aitts_state_widget.setIcon(icon)





            case _:
                play_enabled = self.action_data.sound_file is not None and os.path.isfile(self.action_data.sound_file)
                speed_visible = False
                pitch_visible = False

        self.etts_speed_widget.setVisible(speed_visible)
        self.etts_pitch_widget.setVisible(pitch_visible)

        index = self._stack_map.get(self.action_data.mode, 0)  # pick the correct page to display
        self.stack_widget.setCurrentIndex(index)

        self.setPlayEnabled(play_enabled)

    @QtCore.Slot(bool)
    def _handle_save_on_generate_changed(self, checked: bool):
        self.action_data.save_on_generate = checked

    def _handle_tts_speed_changed(self, value: float):
        self.action_data.ptts_speed = value

    def _handle_etts_pitch_changed(self, value: float):
        self.action_data.etts_pitch = value

    def _handle_etts_volume_changed(self, value: float):
        self.action_data.etts_volume = value

    def _handle_ktts_speed_changed(self, value: float):
        self.action_data.ptts_speed = value

    def _handle_etts_speed_changed(self, value: float):
        self.action_data.ptts_speed = value

    def _handle_ptts_speed_changed(self, value: float):
        self.action_data.ptts_speed = value

    def _handle_refresh_ktts_speakers(self):
        """refresh the list of available KTTS speakers"""
        self._update_ktts_speakers()

    def _handle_refresh_etts_speakers(self):
        """refresh the list of available ETTS speakers"""
        self._update_etts_speakers()

    def _handle_refresh_ptts_speakers(self):
        """refresh the list of available PTTS speakers"""
        self._update_ptts_speakers()

    def _handle_ptts_speaker_changed(self, value):
        self.action_data.speaker = value
        gremlin.config.Configuration().ai_tts_last_speaker = value

    def _handle_ktts_speaker_changed(self, value):
        self.action_data.speaker = value
        gremlin.config.Configuration().ai_ktts_last_speaker = value

    def _handle_etts_speaker_changed(self, value):
        self.action_data.speaker = value
        gremlin.config.Configuration().ai_etts_last_speaker = value

    def _handle_etts_locale_changed(self, value):
        self.action_data.etts_locale = value
        gremlin.config.Configuration().ai_etts_last_locale = value
        self._update_etts_speakers()

    def _handle_etts_gender_changed(self, value):
        self.action_data.etts_gender = value
        gremlin.config.Configuration().ai_etts_last_gender = value
        self._update_etts_speakers()

    def _handle_file_delete(self, widget):
        wav = self.action_data.tts_file
        if wav and os.path.isfile(wav):
            ui = gremlin.shared_state.ui
            result = gremlin.ui.ui_common.ConfirmBox(prompt="Delete cached file?", parent=ui)
            if result:
                try:
                    os.unlink(wav)
                except Exception as e:
                    syslog.error(f"PLAY: unable to delete file: {wav}")
                    syslog.error(f"Error: {str(e)}")
                    return
                self.action_data.tts_file = None
                self.tts_file_widget.setText("")
                self._update_ui()

    def _handle_file_rename(self, widget):
        """renames the file"""
        self.action_data.renameFile()
        self.tts_file_widget.setText(self.action_data.tts_file)
        self._update_ui()

    def _handle_refresh_speakers(self):
        self._update_speakers()



    def _update_speakers(self):
        """updates the list of available voices / speakers for the appropriate TTS engines"""
        match self.action_data.mode:
            case PlayMode.CoquiAI:
                self._update_ktts_speakers()
            case PlayMode.EdgeAI:
                self._update_etts_genders()
                self._update_etts_locales()
                self._update_etts_speakers()
            case PlayMode.PyTTS:
                self._update_ptts_speakers()

    def _update_ktts_speakers(self, initialize=False):
        ktts = gremlin.ktts.KTTS()
        config = gremlin.config.Configuration()
        speakers = ktts.getSpeakers(initialize=initialize)
        with QtCore.QSignalBlocker(self.ktts_speaker_widget):
            self.ktts_speaker_widget.clear()
        if speakers:
            # we have a list of speakers
            for speaker in speakers:
                self.ktts_speaker_widget.addItem(speaker, speaker)
            if self.action_data.speaker:
                speaker = self.action_data.speaker
            else:
                speaker = config.ai_ktts_last_speaker
            if speaker:
                index = self.ktts_speaker_widget.findText(speaker)
                if index != -1:
                    self.ktts_speaker_widget.setCurrentIndex(index)
            else:
                speaker = self.ktts_speaker_widget.currentText()
                config.ai_ktts_last_speaker = speaker
                self.action_data.speaker = speaker
        else:
            if self.action_data.speaker:
                speaker = self.action_data.speaker
                self.ktts_speaker_widget.addItem(speaker, speaker)

        self.ktts_speaker_widget.setEnabled(speakers is not None)
        self.ktts_speaker_widget.updateGeometry()

    def _update_etts_ui(self):
        """called when the ETTS data change """
        update = False
        if self.action_data.etts_gender != self.etts_gender_widget.currentText():
            with QtCore.QSignalBlocker(self.etts_gender_widget):
                self.etts_gender_widget.setCurrentText(self.action_data.etts_gender)
                update = True
        if self.action_data.etts_locale != self.etts_locale_widget.currentText():
            with QtCore.QSignalBlocker(self.etts_locale_widget):
                self.etts_locale_widget.setCurrentText(self.action_data.etts_locale)
                update = True
        if update:
            self._update_etts_speakers()
        self.etts_gender_widget.updateGeometry()
        self.etts_locale_widget.updateGeometry()


    def _update_etts_genders(self):
        """ updates the list of available ETTS genders for the ETTS engine """
        etts = gremlin.sound.EdgeTTS()
        genders = etts.getGenders()
        config = gremlin.config.Configuration()
        with QtCore.QSignalBlocker(self.etts_gender_widget):
            self.etts_gender_widget.clear()
            for gender in genders:
                self.etts_gender_widget.addItem(gender, gender)
            if config.ai_etts_last_gender:
                index = self.etts_gender_widget.findText(config.ai_etts_last_gender)
                if index != -1:
                    self.etts_gender_widget.setCurrentIndex(index)
            else:
                if genders:
                    config.ai_etts_last_gender = genders[0]
                    self.etts_gender_widget.setCurrentIndex(0)

    def _update_etts_locales(self):
        """ updates the list of available ETTS locales for the ETTS engine """
        etts = gremlin.sound.EdgeTTS()
        locales = etts.getLocales(self.action_data.etts_gender)


        config = gremlin.config.Configuration()
        with QtCore.QSignalBlocker(self.etts_locale_widget):
            self.etts_locale_widget.clear()
            for locale in locales:
                self.etts_locale_widget.addItem(locale, locale)
            if config.ai_etts_last_locale:
                index = self.etts_locale_widget.findText(config.ai_etts_last_locale)
                if index != -1:
                    self.etts_locale_widget.setCurrentIndex(index)
            else:
                if locales:
                    config.ai_etts_last_locale = locales[0]
                    self.etts_locale_widget.setCurrentIndex(0)

    def _get_etts_filtered_voices(self) -> dict[str, EdgeTTSVoice]:
        """  gets a list of filtered voices by locale"""
        etts = gremlin.sound.EdgeTTS()
        return etts.getFilteredVoices(locale=self.action_data.etts_locale, gender=self.action_data.etts_gender)

    def _update_etts_speakers(self):
        config = gremlin.config.Configuration()
        voices : dict[str, EdgeTTSVoice] = self._get_etts_filtered_voices()
        etts = gremlin.sound.EdgeTTS()
        current_voice = etts.getVoice(self.etts_speaker_widget.currentText())
        if current_voice:
            if current_voice.gender != self.action_data.etts_gender or current_voice.locale != self.action_data.etts_locale:
                voice = list(voices.values())[0]
                self.action_data.etts_speaker = voice.short_name
                self.action_data.speaker = voice.short_name


        with QtCore.QSignalBlocker(self.etts_speaker_widget):
            self.etts_speaker_widget.clear()
            if voices:
                voice : EdgeTTSVoice
                for voice in voices.values():
                    speaker = voice.short_name
                    self.etts_speaker_widget.addItem(speaker, speaker)
                if self.action_data.speaker:
                    speaker = self.action_data.speaker
                else:
                    speaker = config.ai_etts_last_speaker
                index = self.etts_speaker_widget.findText(speaker)
                if index != -1:
                    self.etts_speaker_widget.setCurrentIndex(index)
                else:
                    config.ai_etts_last_speaker = speaker
                    self.action_data.speaker = self.etts_speaker_widget.currentText()

            self.etts_speaker_widget.setEnabled(bool(voices))
        self.etts_speaker_widget.updateGeometry()

    def _update_ptts_speakers(self, initialize=False):
        ptts = gremlin.tts.TextToSpeech()

        voices = ptts.voices
        config = gremlin.config.Configuration()

        with QtCore.QSignalBlocker(self.ptts_speaker_widget):
            self.ptts_speaker_widget.clear()
            if voices:
                for voice in voices:
                    self.ptts_speaker_widget.addItem(voice.name, voice)
                if self.action_data.speaker:
                    speaker = self.action_data.speaker
                else:
                    speaker = config.ai_tts_last_speaker
                if speaker:
                    index = self.ptts_speaker_widget.findText(speaker)
                    if index != -1:
                        self.ptts_speaker_widget.setCurrentIndex(index)
                else:
                    speaker = self.ptts_speaker_widget.currentText()
                    config.ai_tts_last_speaker = speaker
                    self.action_data.speaker = speaker

        self.ptts_speaker_widget.setEnabled(voices is not None)
        self.ptts_speaker_widget.updateGeometry()

    def _handle_generate(self, widget):
        if self.action_data.text:
            self.action_data.generate(force = True) # force a regen

    def _handle_mode_change(self, widget, mode):
        mode = widget.data
        self.action_data.mode = mode
        self._update_speakers()
        self._update_ui()

    def _handle_audio_change(self, value):
        device = self.action_data.findDevice(value)
        self.action_data.audio_device = device.description()

    def _handle_loops_changed(self, value: int):
        self.action_data.loops = value

    def _handle_fadein_changed(self, value: int):
        self.action_data.fadein_ms = value

    def _handle_fadeout_changed(self, value: int):
        self.action_data.fadeout_ms = value

    def _handle_playback_changed(self, value: int):
        self.action_data.playback_ms = value

    def _handle_playback_rate_changed(self, value: float):
        self.action_data.playback_rate = value

    def _handle_stop_audio_changed(self, checked: bool):
        self.action_data.stop_previous = checked

    @QtCore.Slot()
    def _content_changed_cb(self):
        text = self.tts_text_widget.toPlainText()
        self.action_data.text = text
        self._update_ui()

    def setPlayEnabled(self, value: bool):
        self.play_widget.setEnabled(value)

    @QtCore.Slot()
    def _play_ai_cb(self):
        """plays a ui"""
        ktts = gremlin.sound.KTTS()
        wav = ktts.getActionWav(self.action_data)
        if wav:
            _sound = gremlin.sound.Sound()

    @QtCore.Slot()
    def _handle_select_default(self, widget, is_control: bool, is_shift: bool, is_alt: bool, is_right: bool):
        """selects the default playback device"""

        default_index = self.action_data.getDefaultAudioDeviceIndex()
        index = self.audio_device_selector.findData(default_index)
        if index != -1:
            self.audio_device_selector.setCurrentIndex(index)

        if is_control:
            default_device = self.action_data.getDefaultAudioDevice()
            name = default_device.description()
            profile = gremlin.shared_state.current_profile
            profile.setDefaultAudioDevice(name)

    @QtCore.Slot()
    def _handle_sync_all(self, widget):
        name = self.action_data.audio_device
        profile = gremlin.shared_state.current_profile
        profile.setDefaultAudioDevice(name)

    @QtCore.Slot(bool)
    def _execute_on_press_changed(self, checked: bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked: bool):
        self.action_data.exec_on_release = checked

    def eventFilter(self, object, event):
        t = event.type()
        if t == QtCore.QEvent.Type.FocusOut:
            self.action_data.sound_file = self.file_path_widget.text()
        return False

    def _populate_ui(self):
        self.file_path_widget.setText(self.action_data.sound_file)
        self.volume_widget.setValue(self.action_data.playback_volume)
        self._file_changed()

    def _volume_changed(self, value):
        self.action_data.playback_volume = value

    def _file_changed(self):
        if self.action_data.mode == PlayMode.AudioFile:
            fname = self.file_path_widget.text()
            valid = os.path.isfile(fname)
            if valid:
                self._setIcon("mdi.checkbox-marked-outline", color=gremlin.ui.ui_common.Color.activeColor())
                self.action_data._sound_files.clear()  # force a reload at next play
            else:
                self._setIcon("fa6s.circle-exclamation", color="red")

            self.setPlayEnabled(valid)

    def _setIcon(self, icon_path=None, use_qta=True, color=None):
        import qtawesome as qta
        from gremlin.util import load_pixmap

        icon_size = QtCore.QSize(16, 16)
        """ sets the icon of the label, pass a blank or None path to clear the icon"""
        if icon_path:
            if use_qta:
                if color:
                    pixmap = qta.icon(icon_path, color=color).pixmap(icon_size)
                else:
                    pixmap = qta.icon(icon_path).pixmap(icon_size)
            else:
                pixmap = load_pixmap(icon_path) if icon_path else None
        else:
            pixmap = None
        if pixmap:
            pixmap = pixmap.scaled(icon_size, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self.icon_widget.setPixmap(pixmap)
        else:
            # clear the pixmap
            self.icon_widget.setPixmap(QtGui.QPixmap())

    @QtCore.Slot()
    def _new_sound_file(self):
        """Prompts the user to select a new sound file to add to the profile."""
        config = gremlin.config.Configuration()
        fname = self.file_path_widget.text()  # current entry
        if os.path.isfile(fname):
            dir = os.path.dirname(fname)
        elif os.path.isdir(fname):
            dir = fname
        else:
            dir = config.last_sound_folder
            if dir is None or not os.path.isdir(dir):
                dir = gremlin.shared_state.data_path
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(None, "Path to sound file", dir, "Audio files (*.wav *.mp3)")
        if os.path.isfile(fname):
            self.action_data.sound_file = fname
            dirname, _ = os.path.split(fname)
            config.last_sound_folder = dirname
            # refresh the UI
            self._populate_ui()

    @QtCore.Slot()
    def _handle_play(self):
        self.action_data.play()


class PlaySoundFunctor(gremlin.base_profile.AbstractFunctor):
    """fixed for QT6 media player changes"""

    def __init__(self, action: PlaySound, parent=None):
        super().__init__(action, parent)
        self.sound_file = action.sound_file
        self.volume = action.playback_volume
        self.action_data: PlaySound = action

        config = gremlin.config.Configuration()
        self.verbose = config.verbose_mode_output or config.verbose_mode_exec

    def profile_start(self):
        """runs on profile start"""
        if self.action_data.randomize_sound_file:
            # update the file list to randomize from
            self.action_data.scanFolder()

    def profile_stop(self):
        """stop any active audio on profile stop"""
        sound = self.action_data.sound
        sound.soundStop()

    def process_event(self, event, value, extra_data=None):
        _verbose = gremlin.config.Configuration().verbose_mode_sound
        is_pressed = event.is_pressed
        trigger = (is_pressed and self.action_data.exec_on_press) or (not is_pressed and self.action_data.exec_on_release)

        if trigger:
            self.action_data.play()
        return True


class PlaySound(gremlin.base_profile.AbstractAction):
    """Action to resume callback execution."""

    name = "Play Sound"
    tag = "play-sound"
    hint = "Play a sound."

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, False)



    # override default allowed input types here if not all
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    input_types = [
        InputType.JoystickButton,
        InputType.JoystickHat,
    ]

    functor = PlaySoundFunctor
    widget = PlaySoundWidget
    player = QtMultimedia.QMediaPlayer()  # needs to be a singleton or it blows up

    def icon(self):
        return "ei.speaker"
        # return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.mode = PlayMode.AudioFile
        self.auto_generate = True  # automatically generate AI voice when text changes (valid for some modes only)
        self.text = None  # text to speech for AI mode
        self.speaker = None  # text to speech AI speaker
        self.sound_file = None  # the sound file to play in audio mode
        self._sound_files = []  # list of sound files to pick from if in folder mode
        self._tts_file = None  # sound file for TTS
        self.ptts_speed: int = 100  # words per minute, 100 is the default
        self.ptts_volume: int = 100 # volume, 0 to 100
        self.etts_speed = 1.0  # speed factor for PyTTS
        self.ktts_speed = 1.0  # speed factor for KTTS

        self.playback_volume : int = 100  # default volume as a percentage 0 to 100
        self.etts_pitch : int = 0  # pitch adjust in hertz (edge tts only -100 to +100)
        self.etts_volume : int = 0  # volume offset as a whole percentage -100 to +100
        self._etts_speaker : str = None # etts speaker
        self._etts_locale = None  # selected locale for Edge TTS
        self._etts_gender = None  # selected gender for Edge TTS

        self.etts_callback : Callable = None # callback when etts data changes to update the UI

        self.randomize_sound_file = False  # true if sound is randomized from a folder

        self.key = None  # sound key for the sound file
        self.loops = 1  # number of times the sample is played back
        self.playback_ms = 0  # playback milliseconds, 0 means play normally
        self.playback_rate = 1.0 # playback speed
        self.fadein_ms = 0  # time to fade in in milliseconds, 0 disabled
        self.fadeout_ms = 0  # time to fade out in milliseconds, 0 disabled
        self.exec_on_press = True  # true if trigger should execute on input press event
        self.exec_on_release = False  # true if trigger should execute on input release event
        self.stop_previous = False  # true if the action should stop any prior sounds playing
        self.playback_mode = PlaybackMode.RoundRobin  # default playback mode for multi sounds

        self._timed_random = TimedRandomInt(0, 10, 10)

        default_audio_device = QtMultimedia.QAudioDevice()
        self._audio_device = default_audio_device.description()
        self._last_phrase = None # last played phrase for multiple choice phrases

        devices = QtMultimedia.QMediaDevices.audioOutputs()
        self.device_map = {}
        for index, device in enumerate(devices):
            self.device_map[index] = device

        self.sound = gremlin.sound.Sound()

        self._sound = None  # holds the sound object

    @property
    def save_on_generate(self) -> bool:
        return gremlin.config.Configuration().ai_tts_save_on_generate

    @property
    def audio_device(self) -> str:
        return self._audio_device

    @audio_device.setter
    def audio_device(self, name: str):
        index = self.findDeviceIndex(name)
        init_mixer = False
        if index is None:
            # no longer valid, switch to the new default device
            self.device = self.getDefaultAudioDevice()
            if self.device:
                name = self.device.description()
            else:
                name = None
            self._audio_device = name
            init_mixer = True
        else:
            if self._audio_device != name:
                # changed ?
                self.device = self.device_map[index]
                self._audio_device = name
                init_mixer = True

        if gremlin.sound.USE_PG:
            if init_mixer:
                self.sound.queueAction(gremlin.sound.SoundEvent.ChangeDeviceAction(name))

    @property
    def etts_speaker(self) -> str:
        return self._etts_speaker

    @etts_speaker.setter
    def etts_speaker(self, value: str):
        self._etts_speaker = value
        self.speaker = value
        if self.mode == PlayMode.EdgeAI:
            etts = gremlin.sound.EdgeTTS()
            voice = etts.getVoice(self._etts_speaker)
            if voice:
                self._etts_gender = voice.gender
                self._etts_locale = voice.locale
                if self.etts_callback:
                    self.etts_callback()

    @property
    def etts_gender(self) -> str:
        gender = self._etts_gender
        if not gender and self.speaker and self.mode == PlayMode.EdgeAI:
            etts = gremlin.sound.EdgeTTS()
            voice = etts.getVoice(self.speaker)
            if voice:
                self.etts_gender = voice.gender
                if self.etts_callback:
                    self.etts_callback()
        return self._etts_gender

    @etts_gender.setter
    def etts_gender(self, value: str):
        self._etts_gender = value

    @property
    def etts_locale(self) -> str:
        locale = self._etts_locale
        if not locale and self.speaker and self.mode == PlayMode.EdgeAI:
            etts = gremlin.sound.EdgeTTS()
            voice = etts.getVoice(self.speaker)
            if voice:
                self.etts_locale = voice.locale
        return self._etts_locale

    @etts_locale.setter
    def etts_locale(self, value: str):
        self._etts_locale = value

    @property
    def tts_file(self) -> str:
        return self._tts_file

    @tts_file.setter
    def tts_file(self, value: str):
        self._tts_file = value

    def display_name(self):
        """returns a display string for the current configuration"""
        return f"Play: [{self.sound_file}]"

    def requires_virtual_button(self):
        return self.get_input_type() in [InputType.JoystickAxis, InputType.JoystickHat]

    def getSuggestedFilename(self):
        # get a suggested file name using the first few words of the text
        wav = self.tts_file
        if wav and os.path.isfile(wav):
            ext = gremlin.util.get_ext(wav)
            suggested_name = gremlin.util.textWordsToUnderscore(self.action_data.text)
            dir = os.path.dirname(wav)
            suggested_file = os.path.join(dir, suggested_name)
            suggested_file = gremlin.util.swap_ext(suggested_file, ext)
            return suggested_file

    def scanFolder(self):
        """scans the file folder for valid audio files"""
        self._sound_files.clear()
        if self.sound_file and os.path.isfile(self.sound_file):
            folder_path = os.path.dirname(self.sound_file)
            entries = os.listdir(folder_path)
            for entry in entries:
                ext = gremlin.util.get_ext(entry)
                if ext in (".wav", ".mp3"):
                    self._sound_files.append(os.path.join(folder_path, entry))

        self._timed_random.setMax(len(self._sound_files) - 1)


    def generate(self, force = False):
        match self.mode:
            case PlayMode.AudioFile:
                pitch = 0
                volume = 100
                rate = 1.0
                self.scanFolder()
                self._timed_random.setMax(len(self._sound_files) - 1)

            case PlayMode.EdgeAI:
                pitch = self.etts_pitch
                volume = self.etts_volume
                rate = self.etts_speed
            case PlayMode.PyTTS:
                pitch = 0
                volume = self.ptts_volume
                rate = self.ptts_speed


        phrase = self.sound.generate(text = self.action_data.text,
                                     mode = self.mode,
                                     voice = self.speaker,
                                     randomize_sound_file = self.randomize_sound_file,
                                     rate = rate,
                                     pitch = pitch,
                                     volume = volume,
                                     force=force,
                                     timed_random=self._timed_random)
        if phrase:
            return phrase.key, phrase.sound_file
        return None, None




    def renameFile(self, new_name: str = None):
        """renames the wav file"""
        wav = self.tts_file
        if wav and os.path.isfile(wav):
            ext = gremlin.util.get_ext(wav)
            ui = gremlin.shared_state.ui

            suggested_file = self.getSuggestedFilename()

            # prompt for the file using the suggested name
            new_name, ok = QtWidgets.QFileDialog.getSaveFileName(parent=ui, caption="Enter New File Name", dir=suggested_file, filter=f"Audio Files (*{ext})")
            if ok and new_name:
                try:
                    if os.path.isfile(new_name):
                        # replace
                        os.unlink(new_name)
                    os.rename(wav, new_name)
                except Exception as e:
                    syslog.error(f"PLAY: unable to rename the file: {str(e)}")
                    gremlin.ui.ui_common.MessageBoxWarning(prompt=f"An error occured when renaming the file:\n{str(e)}", parent=ui)
                    return
                self.action_data.tts_file = new_name
                self.tts_file_widget.setText(new_name)
                if self.action_data.save_on_generate:
                    # save the profile
                    syslog.info("PLAY: save profile on wav generation...")
                    profile = gremlin.shared_state.current_profile
                    profile.save()

    def play(self):
        """plays the sound"""

        sound_file = None

        match self.mode:
            case PlayMode.PyTTS:
                rate = self.ptts_speed
                volume = self.ptts_volume
                pitch = 0
            case PlayMode.EdgeAI:
                rate =self.etts_speed
                volume = self.etts_volume
                pitch = self.etts_pitch
            case PlayMode.AudioFile:
                rate = 1.0
                volume = 1.0
                pitch = 0
                sound_file = self.sound_file
            case _:
                # default case
                pass

        # generate the sound file if needed - returns the path to the audio file to play
        phrase : PhraseData = self.sound.generate(text = self.text,
                                              mode = self.mode,
                                              voice = self.speaker,
                                              randomize_sound_file = self.randomize_sound_file,
                                              rate = rate,
                                              volume = volume,
                                              pitch = pitch,
                                              playback_mode = self.playback_mode,
                                              sound_file = sound_file,
                                              timed_random=self._timed_random,
                                              )
        sound_file = phrase.sound_file if phrase else None
        if not sound_file:
            syslog.error("PLAY: failed to generate sound file")
            return None

        # ensure started
        if not self.sound.ensureStarted():
            syslog.error("PLAY: unable to play sound due to sound library initialization issue")
            return
        verbose = gremlin.config.Configuration().verbose_mode_sound
        if verbose:
            mode = self.get_mode()
            input_id = self.get_input_id()
            input_type = self.get_input_type()
            device_name = self.get_device_name()
            syslog.info(f"PLAY: [{self.id}] play [{sound_file}]")
            syslog.info(f"\tAttached device: [{device_name}] input type: [{InputType.to_display_name(input_type)}] input: [{input_id}] mode: [{mode}]")
            syslog.info(
                f"\tOptions: exec on press: [{self.exec_on_press}] exec on release: [{self.exec_on_release}] volume: [{self.playback_volume}] audio channel:[{self.audio_device}]"
            )



        # playback
        if sound_file and os.path.isfile(sound_file):
            # verbose = gremlin.config.Configuration().verbose_mode_sound
            actions = []
            key = phrase.key
            if gremlin.sound.USE_PG:
                # pg needs volume to be set
                action = gremlin.sound.SoundEvent.SetVolumeAction(key, self.playback_volume)
                actions.append(action)
                action = gremlin.sound.SoundEvent.ChangeDeviceAction(self.audio_device)
                actions.append(action)

            action = gremlin.sound.SoundEvent.PlayAction(
                key=key,
                sound_file=sound_file,
                device=self.audio_device,
                loops=self.loops,
                volume=self.playback_volume,
                playback_ms=self.playback_ms,
                fadein_ms=self.fadein_ms,
                fadeout_ms=self.fadeout_ms,
                stop_previous=self.stop_previous,
                rate=self.playback_rate,
            )
            actions.append(action)

            self.sound.queueActions(actions)

        else:
            # if the stop is requested, allow no sound file
            if self.stop_previous:
                action = gremlin.sound.SoundEvent.StopAction()
                self.sound.queueAction(action)
            else:
                syslog.error(f"PLAY: don't know how to play: {sound_file}")



    def findDevice(self, index: int):
        if index in self.device_map:
            return self.device_map[index]

    def findDeviceByDescription(self, description: str):
        """gets a device by description (name)"""
        device = next((d for d in self.device_map.values() if d.description() == description), None)
        return device

    def findDeviceIndex(self, description: str):
        """gets the device index for a specific device description (name)"""
        index = next((i for i, d in self.device_map.items() if d.description() == description), None)
        return index

    def getAudioDevice(self):
        """gets the audio device to play from"""

        default_audio_device = self.getDefaultAudioDevice()

        if self.audio_device:
            device = next((d for d in self.device_map.values() if d.description() == self.audio_device), default_audio_device)
        else:
            device = default_audio_device
        return device

    def getDefaultAudioDevice(self):
        return QtMultimedia.QMediaDevices.defaultAudioOutput()

    def getDefaultAudioDeviceIndex(self):
        index = next((i for i, d in self.device_map.items() if d.isDefault()), None)
        return index

    def getAudioDeviceIndex(self):
        """gets the index of the selected device"""
        if not self.audio_device:
            device = self.getDefaultAudioDevice()
            self.audio_device = device.description()
        index = next((i for i, d in self.device_map.items() if d.description() == self.audio_device), None)
        return index

    def getWave(self):
        """gets the TTS wave file"""
        ktts = gremlin.ktts.KTTS()
        return ktts.getActionWaveFile()

    def isWave(self):
        """true if the TTS wave file exists"""
        wav = self.getWave()
        return os.path.isfile(wav)

    def _parse_xml(self, node, data=None, extra_data=None):
        mode = safe_read(node, "mode", str, "")
        self.mode = PlayMode.from_string(mode)
        self.text = None
        if "text" in node.attrib:
            self.text = html.unescape(node.get("text"))
        speaker = None
        if "speaker" in node.attrib:
            speaker = node.get("speaker")
        self.speaker = speaker  # speaker for AI
        if self.mode == PlayMode.EdgeAI:
            if speaker:
                config = gremlin.config.Configuration()
                etts = gremlin.sound.EdgeTTS()
                voice = etts.getVoice(speaker)
                self._etts_speaker = speaker # this will set the gender and the locale
                if voice:
                    self._etts_locale = voice.locale
                    self._etts_gender = voice.gender
                    config.ai_etts_last_speaker = speaker
                    config.ai_etts_last_locale = self._etts_locale
                    config.ai_etts_last_gender = self._etts_gender

                else:
                    locale = safe_read(node, "etts_locale", str, "")
                    self._etts_locale = locale if locale else None
                    config.ai_etts_last_locale = self._etts_locale
                    gender = safe_read(node, "etts_gender", str, "")
                    self._etts_gender = gender if gender else None
                    config.ai_etts_last_gender = self._etts_gender
            else:
                # use defaults
                self._etts_gender = config.ai_etts_last_gender
                self._etts_locale = config.ai_etts_last_locale






        self.tts_file = safe_read(node, "tts_file", str, "")
        self.sound_file = node.get("file")
        self.randomize_sound_file = safe_read(node, "randomize", bool, False)
        self._sound_files.clear()

        self.ptts_speed = safe_read(node, "ptts_speed", int, 100)
        self.ptts_volume = safe_read(node, "ptts_volume", int, 100)
        self.etts_speed = safe_read(node, "etts_speed", float, 1.0)
        self.etts_volume = safe_read(node, "etts_volume", float, 1.0)



        self.ktts_enabled = gremlin.ktts.KTTS_ENABLED
        self.ktts_speed = safe_read(node, "ktts_speed", float, 1.0)
        self.playback_rate = safe_read(node, "playback-rate", float, 1.0)
        self.playback_volume = int(node.get("volume", 50))
        self.exec_on_press = safe_read(node, "exec_on_press", bool, True)
        self.exec_on_release = safe_read(node, "exec_on_release", bool, False)
        self.audio_device = safe_read(node, "audio-device", str, None)
        self.loops = safe_read(node, "loops", int, 1)
        self.playback_ms = safe_read(node, "playback-ms", int, 0)
        self.fadein_ms = safe_read(node, "fadein-ms", int, 0)
        self.fadeout_ms = safe_read(node, "fadeout-ms", int, 0)
        self.stop_previous = safe_read(node, "stop-previous", bool, False)
        self.auto_generate = safe_read(node, "auto-generate", bool, True)
        pbm = safe_read(node, "playback-mode", str, PlaybackMode.RoundRobin.name)
        self.playback_mode = PlaybackMode[pbm]

    def _generate_xml(self):
        node = ElementTree.Element("play-sound")
        if not self.sound_file:
            self.sound_file = ""
        node.set("mode", PlayMode.to_string(self.mode))

        if self.sound_file:
            node.set("file", self.sound_file)

        node.set("randomize", safe_format(self.randomize_sound_file, bool))

        if self.tts_file:
            node.set("tts_file", self.tts_file)

        if self.speaker:
            node.set("speaker", self.speaker)
        node.set("volume", str(self.playback_volume))
        if self.text:
            node.set("text", html.escape(self.text))
        node.set("ptts_speed", safe_format(self.ptts_speed, int))
        node.set("ptts_volume", safe_format(self.ptts_volume, int))
        node.set("etts_speed", safe_format(self.etts_speed, float))
        node.set("etts_volume", safe_format(self.etts_volume, float))
        if self.etts_locale:
            node.set("etts_locale", self.etts_locale)
        if self.etts_gender:
            node.set("etts_gender", self.etts_gender)
        node.set("ktts_speed", safe_format(self.ktts_speed, float))
        node.set("exec_on_press", safe_format(self.exec_on_press, bool))
        node.set("exec_on_release", safe_format(self.exec_on_release, bool))
        node.set("loops", safe_format(self.loops, int))
        node.set("playback-ms", safe_format(self.playback_ms, int))
        node.set("playback-rate", safe_format(self.playback_rate, float))
        node.set("fadein-ms", safe_format(self.fadein_ms, int))
        node.set("fadeout-ms", safe_format(self.fadeout_ms, int))
        node.set("stop-previous", safe_format(self.stop_previous, bool))
        if self.audio_device:
            node.set("audio-device", self.audio_device)
        node.set("playback-mode", safe_format(self.playback_mode.name, str))
        node.set("auto-generate", safe_format(self.auto_generate, bool))
        return node

    def _is_valid(self):
        return True
        # return self.sound_file is not None and os.path.isfile(self.sound_file) # and len(self.sound_file) > 0

    def to_html(self) -> str:
        """returns reporting graphviz data for this action"""
        from gremlin.reporting import ReportTable
        import html

        table = ReportTable(cellpadding=4)

        table.addField("Mode", self.mode.name)

        match self.mode:
            case PlayMode.AudioFile:
                table.addField("Play", html.escape(self.sound_file))
            case PlayMode.CoquiAI:
                ktts = gremlin.sound.KTTS()
                text = self.text
                text = html.escape(text) if text else ""
                table.addField("Text", text)
                sound_file = ktts.getActionWav(self)
                if sound_file:
                    table.addField("Play (AI)", html.escape(sound_file))
                else:
                    table.addField("Play (AI)", "not found")
                table.addField("Speaker", self.speaker if self.speaker else "n/a")

        table.addField("Volume", f"{self.playback_volume}")

        if self.exec_on_press:
            table.addField("Exec (press)", "Yes")
        if self.exec_on_release:
            table.addField("Exec (release)", "Yes")

        return table.to_html()


version = 1
name = "play-sound"
create = PlaySound
