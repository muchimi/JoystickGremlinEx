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
from PySide6 import QtWidgets, QtCore
from lxml import etree as ElementTree
import threading
import gremlin.base_profile
from gremlin.input_types import InputType
import gremlin.ui.input_item
import gremlin.tts
import gremlin.ui.ui_common
import gremlin.util
from gremlin.util import safe_format, safe_read
from shiboken6 import Shiboken

class TextToSpeechWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget which allows the configuration of TTS actions."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, TextToSpeech)

    def _create_ui(self):
        if not Shiboken.isValid(self):
            return

        self.voice_widget = gremlin.ui.ui_common.QComboBox()
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
                                                
        self.rate_widget = gremlin.ui.ui_common.QIntLineEdit()
        self.rate_widget.setRange(tts.rate_offset_min, tts.rate_offset_max)
        self.rate_widget.valueChanged.connect(self._rate_changed_cb)
        self.rate_widget.doubleClick.connect(self._rate_reset_cb)

        self.play_widget = QtWidgets.QPushButton("Play")
        self.play_widget.setIcon(gremlin.util.load_icon("ei.play",qta_color = gremlin.ui.ui_common.Color.activeColor()))
        self.play_widget.setToolTip("Plays the audio as configured")
        self.play_widget.clicked.connect(self._play_cb)

        self.clear_queue_widget = QtWidgets.QCheckBox("Clear voice queue")
        self.clear_queue_widget.setToolTip("When enabled, any prior TTS messages still in queue will be removed")
        self.clear_queue_widget.setChecked(self.action_data.clearQueue)
        self.clear_queue_widget.clicked.connect(self._handle_clear_queue_changed)

        widgets = [
            "Voice:",
            self.voice_widget,
            "Volume:",
            self.voice_widget,
            "Rate (wpm):",
            self.rate_widget,
            self.play_widget,
            self.clear_queue_widget,
        ]

        self.container_widget,self.container_layout = gremlin.ui.ui_common.getHContainer(widgets)

        self.main_layout.addWidget(self.text_field)
        self.main_layout.addWidget(self.container_widget)

        self._content_changed_cb() # update buttons

    

    def eventFilter(self, object, event):
        t = event.type()
        if t == QtCore.QEvent.Type.FocusOut:
            self.action_data.text = self.text_field.toPlainText()
        return False
    
    @QtCore.Slot(bool)
    def _handle_clear_queue_changed(self, checked):
        self.action_data.clearQueue = checked
    
    @QtCore.Slot()
    def _rate_reset_cb(self):
        self.rate_widget.setValue(100)
    
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
        tts.speak_single(self.action_data.text, self.action_data.rate) 


class TextToSpeechFunctor(gremlin.base_profile.AbstractFunctor):
    
    tts = gremlin.tts.TextToSpeech()

    def __init__(self, action, parent = None):
        super().__init__(action, parent)
        self.action_data = action

    def _speak(self):
        if self.tts is not None:
            voice = self.tts.getVoices()[self.action_data.voice_index]
            self.tts.set_voice(voice)
            self.tts.set_volume(self.action_data.volume)
            self.tts.speak(self.action_data.text, self.action_data.rate, self.action_data.clearQueue)
    
    def profile_start(self):
        if self.action_data.enabled:
            self.tts.start()
    
    def process_event(self, event, value, extra_data = None):
        if not self.action_data.enabled:
            return True

        if event.is_pressed:
            self._speak()
        return True
        


class TextToSpeech(gremlin.base_profile.AbstractAction):

    """Action representing a single TTS entry."""

    name = "Text to Speech"
    tag = "text-to-speech"
    hint = "Converts a text string to voice using the TTS API."

    # trigger condition (trigger_on_press, trigger_on_release)
    default_button_activation = (True, False)
    # override default allowed inputs here
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

    functor = TextToSpeechFunctor
    widget = TextToSpeechWidget

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self._text = ""
        self.volume = 100
        self.rate = 0
        self.voice_index = 0
        self._voice_name = ''
        self.clearQueue = False # true if pending items are cleared when new voice items are queued

    @property
    def voice_name(self):
        return self._voice_name
    @voice_name.setter
    def voice_name(self, value):
        if value != self._voice_name:
            self._voice_name = value


    @property
    def text(self):
        return self._text
    @text.setter
    def text(self, value):
        if value != self._text:
            self._text = value


    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"TTS: WPM: [{self.rate}] Volume: [{self.volume}] Voice: [{self.voice_name}] Say: [{self.text}] " # Voice: [{self.voice_name}]"

    def icon(self):
        return "mdi.playlist-music"
        #return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node, data = None, extra_data = None):
        
        voice_id = None
        tts = gremlin.tts.TextToSpeech()
        if "voice_id" in node.attrib:
            voice_id = node.get("voice_id")
            if voice_id.isdigit():
                voice_id = int(voice_id)
            else:
                voice_id = 0
            
    
            voices = tts.getVoices()
            if voices and voice_id < len(voices):
                self.voice_name = voices[voice_id]
            self.voice_index = voice_id
            
            
        if "volume" in node.attrib:
            self.volume = safe_read(node, "volume", int, 50)
        else:
            self.volume = 50 # default
        self.volume =gremlin.util.clamp(self.volume, 0, 100)    
        if "rate" in node.attrib:
            self.rate = safe_read(node, "rate", int, 100)
        if self.rate == 0:
            self.rate = 100 # default
        self.rate =gremlin.util.clamp(self.rate, tts.rate_offset_min, tts.rate_offset_max)
        if "text" in node.attrib:
            self.text = node.get("text")
        if "clear-queue" in node.attrib:
            self.clearQueue = safe_read(node,"clear-queue",bool, False)


    def _generate_xml(self):
        node = ElementTree.Element("text-to-speech")
        node.set("voice_id", safe_format(self.voice_index, int))
        node.set("text", self.text)
        node.set("volume",safe_format(self.volume, int))
        node.set("rate", safe_format(self.rate, int))
        node.set("clear-queue", safe_format(self.clearQueue, bool))
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
        obj.setId(gremlin.util.get_guid())
        return obj


version = 1
name = "text-to-speech"
create = TextToSpeech
