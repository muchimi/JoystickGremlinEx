
# -*- coding: utf-8; -*-

# Gremlin Ex is (C) EMCS 2025 
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
#
# some code based on source from: https://github.com/h2oai/h2ogpt/tree/main

from __future__ import annotations
import io
import os
import shutil
from PySide6 import QtCore, QtGui, QtMultimedia, QtWidgets
from lxml import etree as ElementTree
import qtawesome as qta
import gremlin.util
import gremlin.event_handler

import gremlin.base_profile
import gremlin.config
from gremlin.input_types import InputType
from gremlin.util import load_icon, userprofile_path
import gremlin.ui.input_item
import gremlin.ui.ui_common
import threading
from shiboken6 import Shiboken
from gremlin.util import safe_format, safe_read
import logging
from psygnal import Signal
import gremlin.singleton_decorator
import time
import json
import importlib.util
import sys

syslog = logging.getLogger("system")


KTTS_DISABLED = getattr(sys, 'frozen', False) # disabled if running packaged
            

@gremlin.singleton_decorator.SingletonDecorator
class KTTS():
    ''' interface to Coqui TTS 
    
    Koki is setup as an external package due to its size.  If installed, 
    
    '''

    def __init__(self):
        self._installed = False # koki not found
        self._device = None 
        self._tts = None
        self._has_rubberband = False
        self._id_file_map = {} # map of action IDs to the wave file name
        self._lock_name = "ktts"
        self._initialized = False

        spec = importlib.util.find_spec("torch")
        if spec is None:
            # not found
            return
        spec = importlib.util.find_spec("TTS")
        if spec is None:
            # not found
            return
        
        spec = importlib.util.find_spec("pyrubberband")
        self._has_rubberband = spec is not None
        
        self._installed = True
        syslog.info(f"KTTS found at {spec.origin}") 

        # By using this tool, you agree to CPML license https://coqui.ai/cpml
        os.environ["COQUI_TOS_AGREED"] = "1"
  
        self._sound_folder = os.path.join(gremlin.util.userprofile_path(),"sounds")
        if not gremlin.util.create_folder(self._sound_folder):
            syslog.error(f"Unable to create sound file repository :{self._sound_folder}")
            self._sound_folder = gremlin.util.userprofile_path()


    def ensure_tts(self) -> bool:
        if self._initialized:
            return True
        
        if not self.is_available():
            return False
        
        gremlin.util.InvokeUiMethod(self._ensure_tts_ui)

        return self._initialized
        
    def _ensure_tts_ui(self):


        # this can take a while
        ui = gremlin.shared_state.ui
        progress_dialog = QtWidgets.QProgressDialog("Initializing KTTS module...", "", 0, 3, parent = ui)
        progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
        progress_dialog.setAutoClose(True)
        progress_dialog.setMinimumDuration(0) # Show immediately
        progress_dialog.setCancelButton(None) # no cancel button
        time.sleep(0.05) 
        QtWidgets.QApplication.processEvents() # Process events to keep the UI responsive

        syslog.info("KTTS: init... (can take a while)")

        
        import torch
        progress_dialog.setValue(1)
        time.sleep(0.05) 
        QtWidgets.QApplication.processEvents() # Process events to keep the UI responsive



        from TTS.api import TTS
        syslog.info("KTTS: import complete")
        progress_dialog.setValue(2)
        time.sleep(0.05) 
        QtWidgets.QApplication.processEvents() # Process events to keep the UI responsive

        
        # determine where the model runs
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        syslog.info("KTTS: instancing... (this can take a while the first time)")
        tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(self._device)

        progress_dialog.setValue(3)
        time.sleep(0.05) 
        QtWidgets.QApplication.processEvents() # Process events to keep the UI responsive


        if not tts:
            tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")
            self._device = "cpu"
        self._tts = tts
        syslog.info(f"KTTS mode: {self._device}")

        self._installed = self._tts is not None

        self._initialized = True

        return self._installed
        
        

    def is_available(self) -> bool:
        ''' true if coqui-tts is found and initialized '''
        if KTTS_DISABLED:
            return False
        
        return self._installed
    
    def is_loaded(self) -> bool:
        ''' true if coqui-tts is found and initialized '''
        if KTTS_DISABLED:
            return False
        return self._initialized
    
    def is_speed_available(self) -> bool:
        if KTTS_DISABLED:
            return False
        return self._has_rubberband
    
    def get_config(self) -> str:
        ''' gets the configuration file name '''
        config = os.path.join(self._sound_folder, "ktts.json")
        return config
    
    def save(self):
        ''' save the map of files '''
        fname = self.get_config() 
        with open(fname, "w") as hdl:  
            encoder = json.JSONEncoder(sort_keys=True,indent=4)
            hdl.write(encoder.encode(self._id_file_map))
            hdl.flush()
            hdl.close()


    def load(self):
        fname = self.get_config() 
        load_successful = False
        with open(fname) as hdl:
            try:
                decoder = json.JSONDecoder()
                data = decoder.decode(hdl.read())
                load_successful = True
                self._id_file_map = data
            except ValueError:
                pass

        return load_successful  


    def getModels(self) -> list:
        if not self._tts:
            return None
        from TTS.utils.manage import ModelManager
        return ModelManager().list_tts_models()
    
    def getSpeakers(self, initialize = False) -> list:
        ''' gets the list of available voices '''
        if not self._tts and not self._initialized and initialize:
            self.ensure_tts()
        
        if not self._tts:
            return None
        
        speakers =  self._tts.speakers
        if speakers:
            speakers.sort()
        return speakers
    

    def hasActionWav(self, action) -> bool:
        ''' true if the action wave file if found '''
        wav = action.tts_file
        return wav and os.path.isfile(wav)

    def getNewWav(self) -> str:
        id = gremlin.util.get_guid()
        tts_file = os.path.join(self._sound_folder,f"{id}.wav")
        return tts_file
    
    def getSoundFolder(self) -> str:
        return self._sound_folder



    def generateActionWav(self, action) -> str:
        ''' generates a wave file for the given action
        
        :param action: the play action
        :returns: the file name or None

        '''
        tts_file = action.tts_file
        if not tts_file:
            tts_file = self.getNewWav()
            action.tts_file = tts_file

        return self.generateWav(tts_file = tts_file, text = action.text, speaker = action.speaker, tts_speed = action.tts_speed)
    
    def generateWav(self, tts_file : str, text, speaker : str = None, tts_speed : float = 1.0) -> str:
        ''' gets the wave file for the given options
         
        :param tts_file: the path to create
        :param text: the text to use
        :param speaker: the speaker voice to use, optional
        :param tts_speed: float, the playback speed factor 1.0 = normal

        :returns: the file name or None
        '''
        
        text = self.sanitize_text(text)
        if not text:
            syslog.warning("KTTS: sanitized text is blank, nothing to generate.")
            return None # no text
        
        # pick a default speaker
        speakers = self.getSpeakers(True)
        if not speakers:
            syslog.error(f"KTTS: unable to get speaker list.")
            return None
        if not speaker or not speaker in speakers:
            speaker = speakers[0]

        # speaker to use
        syslog.info(f"KTTS: generate voice using [{speaker}]")

        # rate
        tts_speed = tts_speed if self._has_rubberband else 1.0
            
        
        wav = tts_file
        if os.path.isfile(wav):
            try:
                os.unlink(wav)
            except Exception as e:
                syslog.error(f"KTTS: unable to remove existing file: {str(e)}")
                return wav
            
        
    
        ''' generate '''
        if not self.ensure_tts():
            return None
        
        self._tts.tts_to_file(text, speaker, "en", file_path = wav)
        if os.path.isfile(wav):
            # adjust wave file speed 
            self.adjust_speed(wav, tts_speed = tts_speed)
            self._id_file_map[id] = wav
            syslog.info(f"KTTS: TTS generated [{wav}]")

        else:
            syslog.warning(f"KTTS: unable to generate TTS")

        return wav
    
    def sanitize_text(self, text):
        ''' removes characters that are problematic in text '''
        import re
        text = re.sub("```.*?```", "", text, flags=re.DOTALL)
        text = re.sub("`.*?`", "", text, flags=re.DOTALL)
        text = re.sub("\(.*?\)", "", text, flags=re.DOTALL)

        # remove marks
        text = text.replace("```", "")
        text = text.replace("...", " ")
        text = text.replace("(", " ")
        text = text.replace(")", " ")

        # use cp1252 encoding since it's what is used under the hood
        encoded = text.encode('cp1252', errors="replace")
        return encoded.decode('cp1252')
    
    def adjust_speed(self, wav, sample_rate : int = 24000, tts_speed : float = 1.0):
        ''' 
        Adjusts the playback speed of a wav file.  The file is modified in place.
        
        :param wav: the full path to the source wave file to modify
        :param sample_rate: the sample rate, the default for AI generated is 24KHz
        :param tts_speed: playback factor, 1.0 = normal
        
        '''

        from pydub import AudioSegment
        import noisereduce as nr
        import soundfile as sf
        import pyrubberband as pyrb
        if tts_speed == 1.0:
            return True # nothing to do
        
        

        # load the audio stream
        tmp = gremlin.util.getTemporaryFile("wav")
        try:
            shutil.copy(wav, tmp)
        except Exception as e:
            syslog.error(f"KTTS: Failed to copy file: {str(e)}")
            return False
        
        try:
            audio = AudioSegment.from_wav(tmp)
            wav_io = io.BytesIO()
            audio.export(wav_io, format = "wav")

            data, samplerate = sf.read(wav_io)
            stretched_data = pyrb.time_stretch(data, samplerate, tts_speed)
            stretched_wav_io = io.BytesIO()
            sf.write(stretched_wav_io, stretched_data, samplerate, format='wav')
            stretched_wav_io.seek(0)

            try:
                os.unlink(wav)
            except Exception as e:
                syslog.error(f"KTTS: Failed to remove existing file: {str(e)}")
                return False
            
            try:
                new_audio = AudioSegment.from_wav(stretched_wav_io)
                new_audio.export(wav, format = "wav")
                new_audio = None
            except Exception as e:
                syslog.error(f"KTTS: Failed to save file: {str(e)}")
                return False     
        finally:
            try:
                os.unlink(tmp)
            except Exception as e:
                syslog.error(f"KTTS: Failed to remove temporary file: {str(e)}")
        
        return os.path.isfile(wav)
  