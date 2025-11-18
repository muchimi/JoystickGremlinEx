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

syslog = logging.getLogger("system")


class PlaySoundWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget for the resume action."""

    # player has to be a class reference to avoid it being garbage collected and not playing a sound at all
    player = QtMultimedia.QMediaPlayer()
    audio = QtMultimedia.QAudioOutput()

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
        self.volume_widget = QtWidgets.QSpinBox()
        self.volume_widget.setRange(0, 100)
        self.volume_widget.valueChanged.connect(self._volume_changed)

        self.play_widget = QtWidgets.QPushButton("Play")
        self.play_widget.setIcon(load_icon("ei.play", qta_color = gremlin.ui.ui_common.Color.activeColor()))
        self.play_widget.setToolTip("Plays the audio as configured")
        self.play_widget.clicked.connect(self._handle_play)

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

        widgets = [
            "Playback device:",
            self.audio_widget,
            self.default_widget
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
            self.play_widget
        ]

        content_widget =  gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        
        self.main_layout.addWidget(audio_container)
        self.main_layout.addWidget(file_container)
        self.main_layout.addWidget(content_widget)
        self.main_layout.addWidget(self._execute_widget)
    
    def _handle_audio_change(self, value):
        device = self.action_data.findDevice(value)
        self.action_data.audio_device = device.description()

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
  


    def process_event(self, event, value, extra_data = None):
        verbose = self.verbose

        
        if self.device:

            is_pressed = event.is_pressed
            trigger = (is_pressed and self.action_data.exec_on_press) or \
                        (not is_pressed and self.action_data.exec_on_release) 
            
            if verbose: syslog.info(f"PLAY: trigger [{trigger}] on input state: [{is_pressed}]")


            if trigger and os.path.isfile(self.sound_file):
                if verbose: syslog.info(f"\texecute play soundfile: {self.sound_file}")
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
        self.volume = 50
        self.exec_on_press = True # true if trigger should execute on input press event
        self.exec_on_release = False # true if trigger should execute on input release event
        
        devices = QtMultimedia.QMediaDevices.audioOutputs()
        self.device_map = {}
        for index, device in enumerate(devices):
            self.device_map[index] = device
        default_audio_device = QtMultimedia.QAudioDevice()
        self._audio_device = default_audio_device.description()
        self.device = self.getAudioDevice()
        self.player = QtMultimedia.QMediaPlayer()
        self.audio = QtMultimedia.QAudioOutput()
        

    @property
    def audio_device(self) -> str:
        return self._audio_device
    @audio_device.setter
    def audio_device(self, name : str):
        index = self.findDeviceIndex(name)
        if index is None:
            # no longer valid, switch to the new default device
            self.device = self.getDefaultAudioDevice()
            if self.device:
                name = self.device.description()
            else:
                name = None
            self._audio_device = name

        else:
            self.device = self.device_map[index]
            self._audio_device = name



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
            verbose = gremlin.config.Configuration().verbose_mode_sound
            audio = QtMultimedia.QAudioOutput(self.device)
            PlaySound.player.setAudioOutput(audio)
            media = QtCore.QUrl.fromLocalFile(self.sound_file)
            PlaySound.player.setSource(media)
            audio.setVolume(self.volume/100) # 0 to 1
            if verbose: syslog.info(f"play start: {self.sound_file}")
            PlaySound.player.play()
            while PlaySound.player.isPlaying():
                QtWidgets.QApplication.processEvents()
            PlaySound.player.stop()
            if verbose: syslog.info("play done")
            
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
       

    def _generate_xml(self):
        node = ElementTree.Element("play-sound")
        if not self.sound_file:
            self.sound_file = ""
        node.set("file", self.sound_file)
        node.set("volume", str(self.volume))
        node.set("exec_on_press", safe_format(self.exec_on_press, bool))
        node.set("exec_on_release", safe_format(self.exec_on_release, bool))        
        if self.audio_device:
            node.set("audio-device", self.audio_device)
        return node

    def _is_valid(self):
        return self.sound_file is not None and os.path.isfile(self.sound_file) # and len(self.sound_file) > 0


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
