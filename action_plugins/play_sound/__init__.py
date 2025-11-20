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


import os
from PySide6 import QtCore, QtGui, QtMultimedia, QtWidgets
from lxml import etree as ElementTree
import qtawesome as qta
import gremlin.util
import gremlin.event_handler

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

syslog = logging.getLogger("system")


USE_QT = False # use QT for playback 

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
                                                                   callback = self._handle_select_default,
                                                                   ctrl_callback = self._handle_select_default_all,
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


        file_container =  gremlin.ui.ui_common.getHContainer(widgets,"Sound file:", widget_only=True)

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
        self.main_layout.addWidget(file_container)
        self.main_layout.addWidget(options_container)
        self.main_layout.addWidget(content_widget)
        
        self.main_layout.addWidget(self._execute_widget)
        self.main_layout.addWidget(info_widget)
    
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
    def _handle_select_default(self):
        ''' selects the default playback device '''
        default_index = self.action_data.getDefaultAudioDeviceIndex()
        index = self.audio_widget.findData(default_index)
        if index != -1:
            self.audio_widget.setCurrentIndex(index)

    @QtCore.Slot()
    def _handle_select_default_all(self):
        ''' on control click the default button, change all devices '''
        self._handle_select_default() # update ours
        # update the rest of the profile
        default_device = self.action_data.getDefaultAudioDevice()
        name = default_device.description()
        profile = gremlin.shared_state.current_profile
        profile.setDefaultAudioDevice(name)
        
    @QtCore.Slot()
    def _handle_sync_all(self):
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
        fname = self.file_path_widget.text()
        valid =  os.path.isfile(fname)
        if valid:
            self._setIcon("mdi.checkbox-marked-outline", color = gremlin.ui.ui_common.Color.activeColor())
        else:
            self._setIcon("fa6s.circle-exclamation", color="red")
        self.play_widget.setEnabled(valid)

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
        self.sound_file = None
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

        # if USE_QT:
        
            
          
        #     self.device = self.getAudioDevice()
        #     self.player = QtMultimedia.QMediaPlayer()
        #     self.audio = QtMultimedia.QAudioOutput()

        # else:
        self.sound = gremlin.sound.Sound()






        self._sound = None # holds the sound object 
        

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



  

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"Play: [{self.sound_file}]"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]
    
    def play(self):
        ''' plays the sound '''
        if self.sound_file and os.path.isfile(self.sound_file):
            # verbose = gremlin.config.Configuration().verbose_mode_sound
            if not self.key:
                self.key = self.sound.getSoundKey(self.sound_file)
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
                syslog.error(f"PLAY: don't know how to play: {self.sound_file}")


    
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


    def _parse_xml(self, node, data = None, extra_data = None):
        self.sound_file = node.get("file")
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
        node.set("file", self.sound_file)
        node.set("volume", str(self.volume))
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
        
        table.addField("Play", html.escape(self.sound_file))
        table.addField("Volume", f"{self.volume}")

        if self.exec_on_press:
            table.addField("Exec (press)", "Yes")
        if self.exec_on_release:
            table.addField("Exec (release)", "Yes")

        return table.to_html()


version = 1
name = "play-sound"
create = PlaySound

