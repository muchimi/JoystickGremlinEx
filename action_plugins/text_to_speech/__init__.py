# -*- coding: utf-8; -*-

# Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
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
from PySide6 import QtWidgets, QtCore
from lxml import etree as ElementTree
import threading
import gremlin.base_profile
from gremlin.input_types import InputType
import gremlin.ui.input_item
import gremlin.tts
import gremlin.ui.ui_common
import gremlin.util


class TextToSpeechWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget which allows the configuration of TTS actions."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, TextToSpeech)

    def _create_ui(self):


        self.voice_widget = QtWidgets.QComboBox()
        tts = gremlin.tts.TextToSpeech()
        for voice in tts.getVoices():
            self.voice_widget.addItem(voice.name, voice.id)

        try:
            self.voice_widget.setCurrentIndex(self.action_data.voice_index)
            self.action_data.voice_name = self.voice_widget.currentText()
        except:
            pass
        
        self.voice_widget.currentIndexChanged.connect(self._voice_change_cb)

        self.text_field = QtWidgets.QPlainTextEdit()
        self.text_field.setPlainText(self.action_data.text)
        self.text_field.textChanged.connect(self._content_changed_cb)
        self.text_field.installEventFilter(self)

        self.volume_widget = QtWidgets.QSpinBox()
        self.volume_widget.setRange(0, 100)
        self.volume_widget.valueChanged.connect(self._volume_changed_cb)
                                                
        self.rate_widget = gremlin.ui.ui_common.QDoubleClickSpinBox()
        self.rate_widget.setRange(tts.rate_offset_min, tts.rate_offset_max)
        self.rate_widget.valueChanged.connect(self._rate_changed_cb)
        self.rate_widget.doubleClick.connect(self._rate_reset_cb)

        self.play_widget = QtWidgets.QPushButton("Play")
        self.play_widget.setIcon(gremlin.util.load_icon("fa.play",qta_color="green"))
        self.play_widget.setToolTip("Plays the audio as configured")
        self.play_widget.clicked.connect(self._play_cb)


        self.container_widget = QtWidgets.QWidget()
        self.container_layout = QtWidgets.QHBoxLayout()
        self.container_widget.setLayout(self.container_layout)

        self.container_layout.addWidget(QtWidgets.QLabel("Voice:"))
        self.container_layout.addWidget(self.voice_widget)

        self.container_layout.addWidget(QtWidgets.QLabel("Volume:"))
        self.container_layout.addWidget(self.volume_widget)

        self.container_layout.addWidget(QtWidgets.QLabel("Playback rate:"))
        self.container_layout.addWidget(self.rate_widget)

        self.container_layout.addWidget(self.play_widget)

        self.container_layout.addStretch()

        self.main_layout.addWidget(self.text_field)
        self.main_layout.addWidget(self.container_widget)

        self._content_changed_cb() # update buttons

    def eventFilter(self, object, event):
        t = event.type()
        if t == QtCore.QEvent.Type.FocusOut:
            self.action_data.text = self.text_field.toPlainText()
        return False
    
    @QtCore.Slot()
    def _rate_reset_cb(self):
        self.rate_widget.setValue(0)
    
    @QtCore.Slot()
    def _voice_change_cb(self):
        self.action_data.voice = self.voice_widget.currentData()
        self.action_data.voice_index = self.voice_widget.currentIndex()
        self.action_data.voice_name = self.voice_widget.currentText()

    @QtCore.Slot()
    def _content_changed_cb(self):
        self.action_data.text = self.text_field.toPlainText()
        self.play_widget.setEnabled(self.action_data.text != '')

    def _populate_ui(self):
        self.text_field.setPlainText(self.action_data.text)
        with QtCore.QSignalBlocker(self.volume_widget):
            self.volume_widget.setValue(self.action_data.volume)
        with QtCore.QSignalBlocker(self.rate_widget):
            self.rate_widget.setValue(self.action_data.rate)

    @QtCore.Slot()
    def _volume_changed_cb(self, value):
        self.action_data.volume = value

    @QtCore.Slot()
    def _rate_changed_cb(self, value):
        self.action_data.rate = value


    @QtCore.Slot()
    def _play_cb(self):
        tts = gremlin.tts.TextToSpeech()
        voice = tts.getVoices()[self.action_data.voice_index]
        tts.set_voice(voice)
        tts.set_volume(self.action_data.volume)
        tts.set_rate(self.action_data.rate)
        tts.speak_single(self.action_data.text) 


class TextToSpeechFunctor(gremlin.base_profile.AbstractFunctor):
    
    tts = gremlin.tts.TextToSpeech()

    def __init__(self, action):
        super().__init__(action)
        self.action_data = action

    def _speak(self):
        if self.tts is not None:
            voice = self.tts.getVoices()[self.action_data.voice_index]
            self.tts.set_voice(voice)
            self.tts.set_volume(self.action_data.volume)
            self.tts.set_rate(self.action_data.rate)
            self.tts.speak(self.action_data.text)
    
    def profile_start(self):
        if self.action_data.enabled:
            self.tts.start()
        
    
    def profile_stop(self):
        if self.action_data.enabled:
            self.tts.end()
    
    def process_event(self, event, value):
        if not self.action_data.enabled:
            return True

        if event.is_pressed:
            self._speak()
        return True
        


class TextToSpeech(gremlin.base_profile.AbstractAction):

    """Action representing a single TTS entry."""

    name = "Text to Speech"
    tag = "text-to-speech"

    default_button_activation = (True, False)
    # override default allowed inputs here
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = TextToSpeechFunctor
    widget = TextToSpeechWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self._text = ""
        self.volume = 100
        self.rate = 0
        self.voice_index = 0
        self.voice_name = ''

    @property
    def text(self):
        return self._text
    @text.setter
    def text(self, value):
        self._text = value


    def display_name(self):
        ''' returns a display string for the current configuration '''

        return f"Say: [{self.text}] Voice: [{self.voice_name}]"

    def icon(self):
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node):
        
        voice_id = None
        
        if "voice_id" in node.attrib:
            voice_id = node.get("voice_id")
            if voice_id.isdigit():
                voice_id = int(voice_id)
            else:
                voice_id = 0
            self.voice_index = voice_id
            
        if "volume" in node.attrib:
            self.volume = int(node.get("volume"))
        else:
            self.volume = 50
        if "rate" in node.attrib:
            self.rate = int(node.get("rate"))
        else:
            self.rate = 0
        if "text" in node.attrib:
            self.text = node.get("text")
            pass
            

    def _generate_xml(self):
        node = ElementTree.Element("text-to-speech")
        node.set("voice_id", str(self.voice_index))
        node.set("text", self.text)
        node.set("volume",str(self.volume))
        node.set("rate",str(self.rate))
        return node

    def _is_valid(self):
        return len(self.text) > 0
    
    def __deepcopy__(self, memo):
        ''' handles deepcopy operation for copy/paste'''
        obj = TextToSpeech(self.parent)
        memo[id(self)] = obj
                
        obj.text = self.text
        obj.volume = self.volume
        obj.rate = self.rate
        obj.voice_index = self.voice_index
        obj.action_id = gremlin.util.get_guid()
        return obj


    # def __getstate__(self) -> object:
    #     # serialize options
    #     state = self.__dict__.copy()
    #     del state['tts'] # don't serialize tts
    #     del state['voice'] # don't serialize voice
    #     return state
    
    # def __setstate__(self, state):
    #     # deserialize options
    #     self.__dict__.update(state)
    #     self.tts = gremlin.tts.TextToSpeech()
    #     self.voice = self.tts.getVoices()[self.voice_index]



version = 1
name = "text-to-speech"
create = TextToSpeech
