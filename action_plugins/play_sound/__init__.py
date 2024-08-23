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
from PySide6 import QtCore, QtGui, QtMultimedia, QtWidgets
from lxml import etree as ElementTree
import qtawesome as qta

import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
from gremlin.util import load_icon, userprofile_path
import gremlin.ui.input_item
import threading


class PlaySoundWidget(gremlin.ui.input_item.AbstractActionWidget):

    """Widget for the resume action."""

    # player has to be a class reference to avoid it being garbage collected and not playing a sound at all
    player = QtMultimedia.QMediaPlayer()
    audio = QtMultimedia.QAudioOutput()

    def __init__(self, action_data, parent=None):
        super().__init__(action_data, parent=parent)
        assert isinstance(action_data, PlaySound)

    def _create_ui(self):
        content_layout = QtWidgets.QHBoxLayout(self)
        self.icon_widget = QtWidgets.QLabel()
        self.file_path_widget = QtWidgets.QLineEdit()
        self.file_path_widget.installEventFilter(self)
        self.file_path_widget.textChanged.connect(self._file_changed)
        self.edit_path_widget = QtWidgets.QPushButton()
        self.edit_path_widget.setIcon(load_icon("gfx/button_edit.png"))
        self.edit_path_widget.clicked.connect(self._new_sound_file)
        self.volume_widget = QtWidgets.QSpinBox()
        self.volume_widget.setRange(0, 100)
        self.volume_widget.valueChanged.connect(self._volume_changed)

        self.play_widget = QtWidgets.QPushButton("Play")
        self.play_widget.setIcon(load_icon("fa.play",qta_color="green"))
        self.play_widget.setToolTip("Plays the audio as configured")
        self.play_widget.clicked.connect(self._play_cb)



        content_layout.addWidget(self.icon_widget)
        content_layout.addWidget(self.file_path_widget)
        content_layout.addWidget(self.edit_path_widget)
        content_layout.addWidget(QtWidgets.QLabel("Volume"))
        content_layout.addWidget(self.volume_widget)
        content_layout.addWidget(self.play_widget)
        
        self.main_layout.addLayout(content_layout)

        self.player.setAudioOutput(self.audio)
        

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
            self._setIcon("fa.check", color="green")
        else:
            self._setIcon("fa.exclamation-circle", color="red")
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
                dir = userprofile_path()
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Path to sound file",
            dir,
            "All Files (*)"
        )
        if os.path.isfile(fname):
            self.action_data.sound_file = fname
            dirname,_ = os.path.split(fname)
            config.last_sound_folder = dirname
            # refresh the UI
            self._populate_ui()

    @QtCore.Slot()
    def _play_cb(self):
        if os.path.isfile(self.action_data.sound_file):
            media = QtCore.QUrl(self.action_data.sound_file)
            self.player.setSource(media)
            volume = self.action_data.volume/100.0  # 0.0 to 1.0
            self.audio.setVolume(volume) 
            self.player.play()

class PlaySoundFunctor(gremlin.base_profile.AbstractFunctor):
    ''' fixed for QT6 media player changes '''

    player = QtMultimedia.QMediaPlayer()
    audio = QtMultimedia.QAudioOutput()

    def __init__(self, action):
        super().__init__(action)
        self.sound_file = action.sound_file
        self.volume = action.volume
        PlaySoundFunctor.player.setAudioOutput(PlaySoundFunctor.audio)


    def process_event(self, event, value):
        if os.path.isfile(self.sound_file):
            media = QtCore.QUrl(self.sound_file)
            PlaySoundFunctor.player.setSource(media)
            PlaySoundFunctor.audio.setVolume(self.volume/100) # 0 to 1
            PlaySoundFunctor.player.play()
        return True


class PlaySound(gremlin.base_profile.AbstractAction):

    """Action to resume callback execution."""

    name = "Play Sound"
    tag = "play-sound"

    default_button_activation = (True, False)

    # override default allowed input types here if not all
    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    functor = PlaySoundFunctor
    widget = PlaySoundWidget

    def icon(self):
        return f"{os.path.dirname(os.path.realpath(__file__))}/icon.png"

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.sound_file = None
        self.volume = 50

    def display_name(self):
        ''' returns a display string for the current configuration '''
        return f"Play: [{self.sound_file}]"

    def requires_virtual_button(self):
        return self.get_input_type() in [
            InputType.JoystickAxis,
            InputType.JoystickHat
        ]

    def _parse_xml(self, node):
        self.sound_file = node.get("file")
        self.volume = int(node.get("volume", 50))

    def _generate_xml(self):
        node = ElementTree.Element("play-sound")
        if not self.sound_file:
            self.sound_file = ""
        node.set("file", self.sound_file)
        node.set("volume", str(self.volume))
        return node

    def _is_valid(self):
        return self.sound_file is not None and os.path.isfile(self.sound_file) # and len(self.sound_file) > 0


version = 1
name = "play-sound"
create = PlaySound
