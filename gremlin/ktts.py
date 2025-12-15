
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
import filelock
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
import pygame
import gremlin.singleton_decorator
import queue
import enum
import time
import json
import importlib.util
import numpy as np
import pydub
import noisereduce
import traceback
import tempfile
import uuid
import wave

syslog = logging.getLogger("system")


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


    def ensure_tts(self):
        if self._initialized:
            return True
        

        # this can take a while

        syslog.info("KTTS: init... (can take a while)")

        import torch

        from TTS.api import TTS
        syslog.info("KTTS: import complete")


        
        # determine where the model runs
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        syslog.info("KTTS: instancing... (this can take a while the first time)")
        tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(self._device)
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
        return self._installed
    
    def is_speed_available(self) -> bool:
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

    def getNewWav(self):
        id = gremlin.util.get_guid()
        tts_file = os.path.join(self._sound_folder,f"{id}.wav")
        return tts_file
        
    
    def generateActionWav(self, action):
        ''' gets the wave file for a specific TTS action
         
        :param action: the play action
        :param speaker: the speaker voice to use, optional
        :param tts_speed: float, the playback speed factor 1.0 = normal
        '''
        
        text = self.sanitize_text(action.text)
        if not text:
            return None # no text
        
        # speaker to use
        speaker = action.speaker
        if speaker:
            syslog.info(f"KTTS: generate voice using [{speaker}]")

        # rate
        tts_speed = action.tts_speed if self._has_rubberband else 1.0
            
        
        wav = action.tts_file
        if os.path.isfile(wav):
            try:
                os.unlink(wav)
            except Exception as e:
                syslog.error(f"KTTS: unable to remove existing file: {str(e)}")
                return wav
            
        wav = self.getNewWav()
        action.tts_file = wav
    
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
  