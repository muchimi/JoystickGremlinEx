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





class TextToSpeechWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget which allows the configuration of TTS actions."""

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, TextToSpeech)

    def _create_ui(self):
        self.text_field = QtWidgets.QPlainTextEdit()
        self.text_field.textChanged.connect(self._content_changed_cb)
        self.text_field.installEventFilter(self)

        self.volume_widget = QtWidgets.QSpinBox()
        self.volume_widget.setRange(0, 100)
        self.volume_widget.valueChanged.connect(self._volume_changed_cb)
                                                
        self.rate_widget = QtWidgets.QSpinBox()
        
        self.rate_widget.setRange(-10, 10)
        self.rate_widget.valueChanged.connect(self._rate_changed_cb)
        self.container_widget = QtWidgets.QWidget()
        self.container_layout = QtWidgets.QHBoxLayout()
        self.container_widget.setLayout(self.container_layout)

        self.container_layout.addWidget(QtWidgets.QLabel("Volume:"))
        self.container_layout.addWidget(self.volume_widget)

        self.container_layout.addWidget(QtWidgets.QLabel("Playback rate:"))
        self.container_layout.addWidget(self.rate_widget)
        self.container_layout.addStretch()

        self.main_layout.addWidget(self.text_field)
        self.main_layout.addWidget(self.container_widget)

    def eventFilter(self, object, event):
        t = event.type()
        if t == QtCore.QEvent.Type.FocusOut:
            self.action_data.text = self.text_field.toPlainText()
        return False

    def _content_changed_cb(self):
        self.action_data.text = self.text_field.toPlainText()

    def _populate_ui(self):
        self.text_field.setPlainText(self.action_data.text)
        with QtCore.QSignalBlocker(self.volume_widget):
            self.volume_widget.setValue(self.action_data.volume)
        with QtCore.QSignalBlocker(self.rate_widget):
            self.rate_widget.setValue(self.action_data.rate)

    def _volume_changed_cb(self, value):
        self.action_data.volume = value

    def _rate_changed_cb(self, value):
        self.action_data.rate = value


class TextToSpeechFunctor(gremlin.base_profile.AbstractFunctor):

    tts = gremlin.tts.TextToSpeech()

    def __init__(self, action):
        super().__init__(action)
        self.text = action.text
        self.volume = action.volume
        self.rate = action.rate

    def _speak(self, text, volume, rate):
        tts = TextToSpeechFunctor.tts
        tts.set_volume(volume)
        tts.set_rate(rate)
        tts.speak(gremlin.tts.text_substitution(text))

    def process_event(self, event, value):
        t = threading.Thread(target=self._speak, args = (self.text,self.volume,self.rate))
        t.start()
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
        self.text = ""
        self.volume = 100
        self.rate = 0

    def icon(self):
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node):
        self.text = node.get("text")
        if "volume" in node.attrib:
            self.volume = int(node.get("volume"))
        else:
            self.volume = 50
        if "rate" in node.attrib:
            self.rate = int(node.get("rate"))
        else:
            self.rate = 0

    def _generate_xml(self):
        node = ElementTree.Element("text-to-speech")
        node.set("text", self.text)
        node.set("volume",str(self.volume))
        node.set("rate",str(self.rate))
        return node

    def _is_valid(self):
        return len(self.text) > 0


version = 1
name = "text-to-speech"
create = TextToSpeech
