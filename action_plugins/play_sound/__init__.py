# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2025 
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

from __future__ import annotations
import os
from PySide6 import QtCore, QtGui, QtMultimedia, QtWidgets
from lxml import etree as ElementTree
import qtawesome as qta
import gremlin.util
import gremlin.event_handler
import re
import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
import gremlin.ui.ui_about
from gremlin.util import load_icon, userprofile_path
import gremlin.ui.input_item
import gremlin.ui.ui_common
import threading
from shiboken6 import Shiboken
from gremlin.util import safe_format, safe_read
import logging
import psygnal
from psygnal import Signal
import gremlin.sound
import enum
import gremlin.ktts
import gremlin.shared_state

syslog = logging.getLogger("system")


USE_QT = False # use QT for playback

class PlayMode(enum.Enum):
    AudioFile = 0 # use standard sound files
    CoquiAI = 1 # use KTTS 

    @staticmethod
    def to_string(value) -> str:
        match value:
            case PlayMode.AudioFile:
                return "audio"
            case PlayMode.CoquiAI:
                return "ktts"
            
    @staticmethod
    def from_string(value) -> PlayMode:
        match value:
            case "ktts":
                return PlayMode.CoquiAI
            case _:
                return PlayMode.AudioFile




    





class PlaySoundWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget for the resume action."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, PlaySound)

    def _create_ui(self):
        
        self.icon_widget = QtWidgets.QLabel()
        self.file_path_widget = QtWidgets.QLineEdit()
        self.file_path_widget.installEventFilter(self)
        self.file_path_widget.textChanged.connect(self._file_changed)
        self.edit_path_widget = QtWidgets.QPushButton()
        self.edit_path_widget= gremlin.ui.ui_common.Buttons.getEditWidget()
        self.edit_path_widget.clicked.connect(self._new_sound_file)
        self.volume_widget =  gremlin.ui.ui_common.QIntLineEdit(min_range=0, max_range = 100, value = self.action_data.volume, callback = self._volume_changed, chars = 4,
                                                              tooltip="Playback volume as a percentage 0 to 100.")
        
        # if KTTS enabled, provide the option to use text to speech
        ktts = gremlin.ktts.KTTS()

        self.ktts_container = None
        self.icon_loaded = gremlin.ui.ui_common.load_icon("fa5s.check-circle", qta_color="#16B11E")
        self.icon_available = gremlin.ui.ui_common.load_icon("fa5s.check-circle", qta_color="#AEB116")
        self.icon_unavailable = gremlin.ui.ui_common.load_icon("fa5s.times-circle", qta_color="#C08224")

        self.ktts_state_widget = gremlin.ui.ui_common.QIconLabel()

        options = [("Audio file", PlayMode.AudioFile, "Plays an audio file"),
                    ("AI TTS", PlayMode.CoquiAI, "Generates an audio file from text via AI (requires Coqui-TTS installation)")]
        
        widgets = []
        for name, data, tooltip in options:
            rb = gremlin.ui.ui_common.QDataRadioButton(name,
                                                        data,
                                                        callback = self._handle_mode_change,
                                                        value = self.action_data.mode == data,
                                                        tooltip = tooltip
                                                        )
            widgets.append(rb)


        widgets.append(self.ktts_state_widget)
        mode_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only = True)

        self.main_layout.addWidget(mode_container)

        self.text_field = QtWidgets.QPlainTextEdit()
        self.text_field.setPlainText(self.action_data.text)
        self.text_field.textChanged.connect(self._content_changed_cb)
        self.text_field.installEventFilter(self)

        self.tts_file_widget = gremlin.ui.ui_common.QLineEdit(text = self.action_data.tts_file)
        self.tts_file_widget.setReadOnly(True)

        self.tts_file_delete_widget = gremlin.ui.ui_common.Buttons.getDeleteWidget(callback = self._handle_file_delete,tooltip = "Delete the audio file")
        self.tts_file_rename_widget = gremlin.ui.ui_common.QDataPushButton("Rename", callback = self._handle_file_rename, tooltip = "Rename the audio file")



        self.speaker_widget = gremlin.ui.ui_common.QDataComboBox(auto_adjust=True, tooltip = "Selected speaker for AI voice generation.")
        self._update_speakers(initialize = False)
        self.speaker_widget.setCallback(self._handle_speaker_changed)



        refresh_speaker_widget = gremlin.ui.ui_common.Buttons.getRefreshWidget(label=None, callback = self._handle_refresh_speakers,tooltip="Refresh available AI speakers")
    
        icon = gremlin.ui.ui_common.load_icon("ri.voiceprint-fill")
        self.generate_widget = gremlin.ui.ui_common.QDataPushButton("Generate", callback = self._handle_generate, tooltip = "Generate the AI voice.")
        self.generate_widget.setIcon(icon)
        
        self.tts_speed_widget = gremlin.ui.ui_common.QFloatLineEdit(min_range = 0.1, max_range = 10.0, value = self.action_data.tts_speed, callback = self._handle_tts_speed_changed, tooltip = "Speed rate modifier for the generated audio.\n1.0 is the normal rate.")

        widgets = [
            "Speaker:",
            self.speaker_widget,
            refresh_speaker_widget,
            "TTS speed:",
            self.tts_speed_widget,
            self.generate_widget,
            ]
        
        ai_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)


        widgets = [
            "Text:",
            self.text_field,
            gremlin.ui.ui_common.getHContainer([
                self.tts_file_widget,
                self.tts_file_delete_widget,
                self.tts_file_rename_widget
                ],
                  label = "Cache file:", widget_only=True),
            ai_container,

        ]

        self.ktts_container = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True)

    

        self.play_widget = QtWidgets.QPushButton("Play")
        self.play_widget.setIcon(load_icon("ei.play", qta_color = gremlin.ui.ui_common.Color.activeColor()))
        self.play_widget.setToolTip("Plays the audio as configured")
        self.play_widget.clicked.connect(self._handle_play)




        self.loops_widget = gremlin.ui.ui_common.QIntLineEdit(min_range=1, max_range = 100, value = self.action_data.loops, callback = self._handle_loops_changed, chars = 4,
                                                              tooltip="Number of time the sample will play.\n1 is the default.")
        self.fadein_widget = gremlin.ui.ui_common.QIntLineEdit(min_range = 0, value = self.action_data.fadein_ms, callback = self._handle_fadein_changed, chars = 4,
                                                               tooltip = "Time in ms to reach the maximum volume once the sample starts playing.\nUse 0 to disable (default).")
        self.fadeout_widget = gremlin.ui.ui_common.QIntLineEdit(min_range = 0, value = self.action_data.fadeout_ms, callback = self._handle_fadeout_changed, chars = 4,
                                                                tooltip = "Time in ms for the sample to fade out once it starts playing.\nUse 0 to disable (default).")
        self.playback_widget = gremlin.ui.ui_common.QIntLineEdit(min_range = 0, value = self.action_data.playback_ms, callback = self._handle_playback_changed, chars = 4,
                                                                 tooltip = "Maximum time in ms the sample has to play.\nThe sample will be cut short if the specified time is shorter than the normal sample play time.\nUse 0 to disable (default).")
        

        
        self.stop_widget = gremlin.ui.ui_common.QDataCheckbox("Stop previous audio",value = self.action_data.stop_previous, callback = self._handle_stop_audio_changed, 
                                                              tooltip="If checked, any other audio playing will stop before playing this sample.")

        self._execute_widget = gremlin.ui.ui_common.QExecuteWidget(self.action_data.exec_on_press, self.action_data.exec_on_release)
        self._execute_widget.pressChanged.connect(self._execute_on_press_changed)
        self._execute_widget.releaseChanged.connect(self._execute_on_release_changed)

        verbose = gremlin.config.Configuration().verbose_mode_sound
        
        device_index = self.action_data.getAudioDeviceIndex()
        
        source = [(d.description(), index) for index, d in self.action_data.device_map.items()]

        self.audio_widget = gremlin.ui.ui_common.QDataComboBox(callback=self._handle_audio_change, source=source, value = device_index)
        self.default_widget = gremlin.ui.ui_common.QDataPushButton("Default",
                                                                   callback_ex= self._handle_select_default,
                                                                   tooltip = "Select system default")
        
        
        self.sync_widget =gremlin.ui.ui_common.QDataPushButton("Sync All",callback = self._handle_sync_all, tooltip ="Set all Play Sound actions in the profile to this device")

        

        msg = """Samples played with this action will play concurrently as they are triggered.  Use the stop option to terminate prior audio streams before triggering the playback.  Playback timing options with a value of zero (0) means disabled.
"""

        info_widget = gremlin.ui.ui_common.QInfoBox(msg, hide_key="play-sound")

        widgets = [
            "Playback device:",
            self.audio_widget,
            self.default_widget,
            self.sync_widget
        ]

        audio_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

        widgets = [
            self.icon_widget,
            self.file_path_widget,
            self.edit_path_widget
        ]


        self.file_container =  gremlin.ui.ui_common.getHContainer(widgets,"Sound file:", widget_only=True)

        widgets = [
            "Volume:",
            self.volume_widget, 
            "Loops:",
            self.loops_widget,
            self.stop_widget,
            self.play_widget
        ]

        content_widget =  gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)

        widgets = [
            "Playback (ms):",
            self.playback_widget,
            "Fade-in (ms):",
            self.fadein_widget,
            "Fade-out (ms)",
            self.fadeout_widget
        ]

        options_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True) 

        
        self.main_layout.addWidget(audio_container)
        self.main_layout.addWidget(self.file_container)
        if self.ktts_container:
            self.main_layout.addWidget(self.ktts_container)
        self.main_layout.addWidget(options_container)
        self.main_layout.addWidget(content_widget)
        
        self.main_layout.addWidget(self._execute_widget)
        self.main_layout.addWidget(info_widget)

        self._update_ui()

    def _update_ui(self):
        if self.action_data.mode == PlayMode.CoquiAI:
            ktts = gremlin.ktts.KTTS()
            generate_enabled = ktts.is_available() and self.action_data.text is not None and self.action_data.text != ''
            wav = self.action_data.tts_file
            play_enabled = wav is not None and os.path.isfile(wav)
            ktts_visible = True
            speed_visible = ktts.is_speed_available()
            delete_enabled = play_enabled
            
            if wav is not None and os.path.isfile(wav):
                self.tts_file_widget.setText(wav)
            else:
                self.tts_file_widget.setText('not generated')

            self.tts_speed_widget.setEnabled(speed_visible)
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
            self.ktts_state_widget.setText(label)    
            self.ktts_state_widget.setIcon(icon)
            

        else:
            play_enabled = self.action_data.sound_file is not None and os.path.isfile(self.action_data.sound_file)
            ktts_visible = False
            speed_visible = False

       

        file_visible = not ktts_visible
        self.file_container.setVisible(file_visible)
        self.ktts_container.setVisible(ktts_visible)
        
        self.setPlayEnabled(play_enabled)

    @QtCore.Slot(bool)
    def _handle_save_on_generate_changed(self, checked):
        self.action_data.save_on_generate = checked


    def _handle_tts_speed_changed(self, value : float):
        self.action_data.tts_speed = value

    def _handle_speaker_changed(self, value):
        self.action_data.speaker = value
        gremlin.config.Configuration().ai_tts_last_speaker = value

    def _handle_file_delete(self, widget):
        wav = self.action_data.tts_file
        if wav and os.path.isfile(wav):
            ui = gremlin.shared_state.ui
            result = gremlin.ui.ui_common.MessageBoxYesNo(prompt="Delete cached file?", parent = ui)
            if result == QtWidgets.QMessageBox.StandardButton.Yes:
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
        ''' renames the file '''
        self.action_data.renameFile()
        self.tts_file_widget.setText(self.action_data.tts_file)
        self._update_ui()
        

    def _handle_refresh_speakers(self):
        self._update_speakers(initialize = True)

    def _update_speakers(self, initialize = False):
        config = gremlin.config.Configuration()
        last_speaker = config.ai_tts_last_speaker
        if not self.action_data.speaker:
            # default speaker is the last one if we have one defined
            self.action_data.speaker = last_speaker

        ktts = gremlin.ktts.KTTS()
        try:
            gremlin.util.pushCursor()
            speakers = ktts.getSpeakers(initialize = initialize)
            with QtCore.QSignalBlocker(self.speaker_widget):
                self.speaker_widget.clear()
            if speakers:
                # we have a list of speakers
                for speaker in speakers:
                    self.speaker_widget.addItem(speaker, speaker)
                if self.action_data.speaker:
                    speaker = self.action_data.speaker
                else:
                    speaker = config.ai_tts_last_speaker
                if speaker:
                    index = self.speaker_widget.findText(speaker)
                    if index != -1:
                        self.speaker_widget.setCurrentIndex(index)
                else:
                    speaker = self.speaker_widget.currentText()
                    config.ai_tts_last_speaker = speaker
                    self.action_data.speaker = speaker
            else:
                if self.action_data.speaker:
                    speaker = self.action_data.speaker
                    self.speaker_widget.addItem(speaker, speaker)
            
            self.speaker_widget.setEnabled(speakers is not None)
        finally:
            gremlin.util.popCursor()
        

    def _handle_generate(self, widget):
        if self.action_data.text:
            ui = gremlin.shared_state.ui
            dialog = gremlin.sound.GenerateDialog(self.action_data, parent = ui)
            result = dialog.exec()
            if result == QtWidgets.QDialog.accepted:
                try:
                    gremlin.util.pushCursor()
                    self.action_data.generate()
                finally:
                    gremlin.util.popCursor()
            self._update_ui()

        # update speakers if not done
        enabled = self.speaker_widget.isEnabled()
        if not enabled:
            self._update_speakers()
        


    def _handle_mode_change(self):
        widget = self.sender()
        mode = widget.data
        self.action_data.mode = mode
        self._update_ui()
    
    def _handle_audio_change(self, value):
        device = self.action_data.findDevice(value)
        self.action_data.audio_device = device.description()

    def _handle_loops_changed(self, value : int):
        self.action_data.loops = value

    def _handle_fadein_changed(self, value : int):
        self.action_data.fadein_ms = value

    def _handle_fadeout_changed(self, value : int):
        self.action_data.fadeout_ms = value

    def _handle_playback_changed(self, value : int):
        self.action_data.playback_ms = value

    def _handle_stop_audio_changed(self, checked: bool):
        self.action_data.stop_previous = checked

    @QtCore.Slot()
    def _content_changed_cb(self):
        text = self.text_field.toPlainText()
        self.action_data.text = text
        self._update_ui()


    def setPlayEnabled(self, value : bool):
        self.play_widget.setEnabled(value)

    @QtCore.Slot()
    def _play_ai_cb(self):
        ''' plays a ui '''
        ktts = gremlin.sound.KTTS()
        wav = ktts.getActionWav(self.action_data)
        if wav:
            sound = gremlin.sound.Sound()         
                
        
    @QtCore.Slot()
    def _handle_select_default(self, is_control : bool, is_shift : bool, is_right : bool):
        ''' selects the default playback device '''

        default_index = self.action_data.getDefaultAudioDeviceIndex()
        index = self.audio_widget.findData(default_index)
        if index != -1:
            self.audio_widget.setCurrentIndex(index)

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
    def _execute_on_press_changed(self, checked : bool):
        self.action_data.exec_on_press = checked

    @QtCore.Slot(bool)
    def _execute_on_release_changed(self, checked : bool):
        self.action_data.exec_on_release = checked       


    def eventFilter(self, object, event):
        t = event.type()
        if t == QtCore.QEvent.Type.FocusOut:
            self.action_data.sound_file = self.file_path_widget.text()  
        return False

    def _populate_ui(self):
        self.file_path_widget.setText(self.action_data.sound_file)
        self.volume_widget.setValue(self.action_data.volume)
        self._file_changed()

    def _volume_changed(self, value):
        self.action_data.volume = value

    def _file_changed(self):
        if self.action_data.mode == PlayMode.AudioFile:
            fname = self.file_path_widget.text()
            valid =  os.path.isfile(fname)
            if valid:
                self._setIcon("mdi.checkbox-marked-outline", color = gremlin.ui.ui_common.Color.activeColor())
            else:
                self._setIcon("fa6s.circle-exclamation", color="red")
            self.setPlayEnabled(valid)

    def _setIcon(self, icon_path = None, use_qta = True, color = None):
        import qtawesome as qta
        from gremlin.util import load_pixmap
        icon_size = QtCore.QSize(16, 16)
        ''' sets the icon of the label, pass a blank or None path to clear the icon'''
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
        """Prompts the user to select a new sound file to add to the profile.  """
        config = gremlin.config.Configuration()
        fname = self.file_path_widget.text() # current entry
        if os.path.isfile(fname):
            dir = os.path.dirname(fname)
        elif os.path.isdir(fname):
            dir = fname
        else:
            dir = config.last_sound_folder
            if dir is None or not os.path.isdir(dir):
                dir = gremlin.shared_state.data_path
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Path to sound file",
            dir,
            "Audio files (*.wav *.mp3)"
        )
        if os.path.isfile(fname):
            self.action_data.sound_file = fname
            dirname,_ = os.path.split(fname)
            config.last_sound_folder = dirname
            # refresh the UI
            self._populate_ui()

    @QtCore.Slot()
    def _handle_play(self):
        self.action_data.play()
class PlaySoundFunctor(gremlin.base_profile.AbstractFunctor):
    ''' fixed for QT6 media player changes '''
    
    def __init__(self, action, parent = None):
        super().__init__(action, parent)
        self.sound_file = action.sound_file
        self.volume = action.volume
      
        config = gremlin.config.Configuration()
        self.verbose = config.verbose_mode_output or config.verbose_mode_exec
  
    def profile_stop(self):
        ''' stop any active audio on profile stop '''
        sound = self.action_data.sound
        sound.soundStop()


    def process_event(self, event, value, extra_data = None):
        verbose = self.verbose
        is_pressed = event.is_pressed
        trigger = (is_pressed and self.action_data.exec_on_press) or \
                    (not is_pressed and self.action_data.exec_on_release) 
        
        if verbose: syslog.info(f"PLAY: trigger [{trigger}] on input state: [{is_pressed}]")


        if trigger:
            if verbose and os.path.isfile(self.sound_file):
                syslog.info(f"\texecute play soundfile: {self.sound_file}")
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
    player = QtMultimedia.QMediaPlayer() # needs to be a singleton or it blows up

    def icon(self):
        return "ei.speaker"
        #return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.mode = PlayMode.AudioFile
        self.text = None # text to speech for AI mode
        self.speaker = None # text to speech AI speaker 
        self.sound_file = None # the sound file to play in audio mode
        self._tts_file = None # sound file for TTS 
        self.tts_speed = 1.0 # for AI generation, speed factor, 1.0 = normal rate
        self.volume = 100 # default volume as a percentage 0 to 100
        
        self.key = None # sound key for the sound file
        self.loops = 1 # number of times the sample is played back
        self.playback_ms = 0 # playback milliseconds, 0 means play normally
        self.fadein_ms = 0 # time to fade in in milliseconds, 0 disabled
        self.fadeout_ms = 0 # time to fade out in milliseconds, 0 disabled
        self.exec_on_press = True # true if trigger should execute on input press event
        self.exec_on_release = False # true if trigger should execute on input release event
        self.stop_previous = False # true if the action should stop any prior sounds playing

        default_audio_device = QtMultimedia.QAudioDevice()
        self._audio_device = default_audio_device.description()

        devices = QtMultimedia.QMediaDevices.audioOutputs()
        self.device_map = {}
        for index, device in enumerate(devices):
            self.device_map[index] = device        

        self.sound = gremlin.sound.Sound()

        self._sound = None # holds the sound object 
        
    @property
    def save_on_generate(self) -> bool:
        return gremlin.config.Configuration().ai_tts_save_on_generate

    @property
    def audio_device(self) -> str:
        return self._audio_device
    @audio_device.setter
    def audio_device(self, name : str):
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

        if init_mixer:
            if USE_QT:
                pass
            else:
                self.sound.queueAction(gremlin.sound.SoundEvent.ChangeDeviceAction(name))


    @property
    def tts_file(self) -> str:
        return self._tts_file
    @tts_file.setter
    def tts_file(self, value : str):
        self._tts_file = value
  

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"Play: [{self.sound_file}]"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]
    
    def getSuggestedFilename(self):
        # get a suggested file name using the first few words of the text
        wav = self.tts_file
        if wav and os.path.isfile(wav):
            ext = gremlin.util.get_ext(wav)
            suggested_name = gremlin.util.textWordsToUnderscore(self.action_data.text)
            dir = os.path.dirname(wav)
            suggested_file = os.path.join(dir, suggested_name)
            suggested_file = gremlin.util.swap_ext(suggested_file,ext)
            return suggested_file

    
    def generate(self) -> bool:
        ''' generates the output wav file with current options 
        
        :returns: true on success
        
        '''
        config = gremlin.config.Configuration()
        ktts = gremlin.ktts.KTTS()
        # release the sound file if it exists
        tts_file = self.tts_file
        if tts_file and os.path.isfile(tts_file):
            os.unlink(tts_file)
        
        wav = ktts.generateActionWav(action = self)
        if wav:
            assert os.path.isfile(wav)
            self.tts_file = wav
            self.play()
            if config.ai_tts_use_word_filenames:
                new_wav = self.getSuggestedFilename()
                if os.path.isfile(new_wav):
                    # prompt for a new file name if it exists and save the profile if needed
                    self.renameFile() 
                else:
                    # simple rename
                    try:
                        os.rename(wav, new_wav)
                        self.action_data.tts_file = new_wav
                    except Exception as e:
                        syslog.error(f"PLAY: unable to rename the file: {str(e)}")
                        ui = gremlin.shared_state.ui
                        gremlin.ui.ui_common.MessageBoxWarning(prompt = f"An error occured when renaming the file:\n{str(e)}", parent = ui)
                        return False
                    if self.action_data.save_on_generate:
                        # save the profile
                        syslog.info("PLAY: save profile on wav generation...")
                        profile = gremlin.shared_state.current_profile
                        profile.save()

                return True
        return False
    
    def renameFile(self, new_name : str = None):
        ''' renames the wav file '''
        wav = self.tts_file
        if wav and os.path.isfile(wav):
            ext = gremlin.util.get_ext(wav)
            ui = gremlin.shared_state.ui

            suggested_file = self.getSuggestedFilename()

            # prompt for the file using the suggested name
            new_name, ok = QtWidgets.QFileDialog.getSaveFileName(
                parent = ui,
                caption = "Enter New File Name",
                dir = suggested_file,
                filter = f"Audio Files (*{ext})"
                )
            if ok and new_name:
                try:
                    if os.path.isfile(new_name):
                        # replace
                        os.unlink(new_name) 
                    os.rename(wav, new_name)
                except Exception as e:
                    syslog.error(f"PLAY: unable to rename the file: {str(e)}")
                    gremlin.ui.ui_common.MessageBoxWarning(prompt = f"An error occured when renaming the file:\n{str(e)}", parent = ui)
                    return
                self.action_data.tts_file = new_name
                self.tts_file_widget.setText(new_name)
                if self.action_data.save_on_generate:
                    # save the profile
                    syslog.info("PLAY: save profile on wav generation...")
                    profile = gremlin.shared_state.current_profile
                    profile.save()
    
    def play(self):
        ''' plays the sound '''

        # get the sound file
        sound_file = None
        match self.mode:
            case PlayMode.AudioFile:
                if self.sound_file and os.path.isfile(self.sound_file):
                    sound_file = self.sound_file 
            case PlayMode.CoquiAI:
                ''' AI generated '''
                sound_file = self.tts_file

        if sound_file and os.path.isfile(sound_file):
            # verbose = gremlin.config.Configuration().verbose_mode_sound
            if not self.key:
                self.key = self.sound.getSoundKey(sound_file)
                action = gremlin.sound.SoundEvent.SetVolumeAction(self.key, self.volume)
                self.sound.queueAction(action)

            
                
            actions = [
                gremlin.sound.SoundEvent.ChangeDeviceAction(self.audio_device),
                gremlin.sound.SoundEvent.PlayAction(self.key,
                                                    self.loops,
                                                    self.volume,
                                                    self.playback_ms,
                                                    self.fadein_ms,
                                                    self.fadeout_ms,
                                                    self.stop_previous
                                                    )
                ]

            self.sound.queueActions(actions)
            
        else:
            # if the stop is requested, allow no sound file
            if self.stop_previous:
                action = gremlin.sound.SoundEvent.StopAction()
                self.sound.queueAction(action)
            else:
                syslog.error(f"PLAY: don't know how to play: {sound_file}")


    
    def findDevice(self, index : int):
        if index in self.device_map:
            return self.device_map[index]
        
    def findDeviceByDescription(self, description : str):
        ''' gets a device by description (name)'''
        device = next((d for d in self.device_map.values() if d.description() == description),None) 
        return device
    
    def findDeviceIndex(self, description : str):
        ''' gets the device index for a specific device description (name) '''
        index = next((i for i, d in self.device_map.items() if d.description() == description),None) 
        return index

    def getAudioDevice(self):
        ''' gets the audio device to play from '''
        
        default_audio_device = self.getDefaultAudioDevice()
        
        if self.audio_device:
            device = next((d for d in self.device_map.values() if d.description() == self.audio_device), default_audio_device) 
        else:
            device = default_audio_device
        return device
    
    def getDefaultAudioDevice(self):
        return  QtMultimedia.QMediaDevices.defaultAudioOutput()
    
    def getDefaultAudioDeviceIndex(self):
        index = next((i for i, d in self.device_map.items() if d.isDefault()),None) 
        return index

    
    def getAudioDeviceIndex(self):
        ''' gets the index of the selected device '''
        if not self.audio_device:
            device = self.getDefaultAudioDevice()
            self.audio_device = device.description()
        index = next((i for i, d in self.device_map.items() if d.description() == self.audio_device),None) 
        return index
    
    def getWave(self):
        ''' gets the TTS wave file '''
        ktts = gremlin.ktts.KTTS()
        return ktts.getActionWaveFile()
    
    def isWave(self):
        ''' true if the TTS wave file exists '''
        wav = self.getWave()
        return os.path.isfile(wav)


    def _parse_xml(self, node, data = None, extra_data = None):
        mode = safe_read(node, "mode", str, "")
        self.mode = PlayMode.from_string(mode)
        self.text = None
        if "text" in node.attrib:
            self.text = node.get("text")
        speaker = None
        if "speaker" in node.attrib:
            speaker = node.get("speaker")
        self.speaker = speaker # speaker for AI
        self.tts_file = safe_read(node,"tts_file", str, '')
        self.sound_file = node.get("file")
        self.tts_speed = safe_read(node,"tts_speed", float, 1.0)
        self.volume = int(node.get("volume", 50))
        self.exec_on_press = safe_read(node,"exec_on_press",bool, True)
        self.exec_on_release = safe_read(node,"exec_on_release",bool, False)
        self.audio_device = safe_read(node,"audio-device",str, None)
        self.loops = safe_read(node,"loops",int, 1)
        self.playback_ms = safe_read(node,"playback-ms",int, 0)
        self.fadein_ms = safe_read(node,"fadein-ms",int, 0)
        self.fadeout_ms = safe_read(node,"fadeout-ms",int, 0)        
        self.stop_previous = safe_read(node,"stop-previous",bool, False)
        

    def _generate_xml(self):
        node = ElementTree.Element("play-sound")
        if not self.sound_file:
            self.sound_file = ""
        node.set("mode", PlayMode.to_string(self.mode))

        if self.sound_file:
            node.set("file", self.sound_file)

        if self.tts_file:
            node.set("tts_file", self.tts_file)
        
        if self.speaker:
            node.set("speaker", self.speaker)
        node.set("volume", str(self.volume))
        if self.text:
            node.set("text", self.text)
        node.set("tts_speed", safe_format(self.tts_speed, float))
        node.set("exec_on_press", safe_format(self.exec_on_press, bool))
        node.set("exec_on_release", safe_format(self.exec_on_release, bool))  
        node.set("loops", safe_format(self.loops,int))      
        node.set("playback-ms", safe_format(self.playback_ms, int))
        node.set("fadein-ms", safe_format(self.fadein_ms, int))
        node.set("fadeout-ms", safe_format(self.fadeout_ms, int))
        node.set("stop-previous", safe_format(self.stop_previous, bool))
        if self.audio_device:
            node.set("audio-device", self.audio_device)
        return node

    def _is_valid(self):
        return True
        # return self.sound_file is not None and os.path.isfile(self.sound_file) # and len(self.sound_file) > 0


    def to_html(self) -> str:
        ''' returns reporting graphviz data for this action '''
        from gremlin.reporting import ReportTable, ReportRow, ReportCell
        import html
        table = ReportTable(cellpadding=4) 
        
        table.addField("Mode", self.mode.name)
        
        match self.mode:
            case PlayMode.AudioFile:
                table.addField("Play", html.escape(self.sound_file))
            case PlayMode.CoquiAI:
                ktts = gremlin.sound.KTTS()
                text = html.escape(text) if text else ""
                table.addField("Text", text)
                sound_file = ktts.getActionWav(self)
                if sound_file:
                    table.addField("Play (AI)", html.escape(sound_file))
                else:
                    table.addField("Play (AI)", "not found")
                table.addField("Speaker", self.speaker if self.speaker else "n/a")

                
        table.addField("Volume", f"{self.volume}")

        if self.exec_on_press:
            table.addField("Exec (press)", "Yes")
        if self.exec_on_release:
            table.addField("Exec (release)", "Yes")

        return table.to_html()


version = 1
name = "play-sound"
create = PlaySound

