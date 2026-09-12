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
import hashlib
import os
import html
import sys
import gc

from lxml import etree
from PySide6 import QtCore, QtMultimedia, QtWidgets
import gremlin.util
from gremlin.util import hashString, safe_format, safe_read, TimedRandomInt, hashString

import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
from PySide6.QtMultimedia import QMediaDevices, QAudioOutput
import threading
import logging
import os
import numpy as np
import time

syslog = logging.getLogger("system")

SAMPLE_RATE = 16000  # Hz
TRIGGER_KEY = "space"  # Key to trigger recording

@gremlin.singleton_decorator.SingletonDecorator
class Voice():
    """ speech recognition engine """

    def __init__(self):
        os.environ["HF_HUB_VERBOSITY"] = "error"
        self._voice_lock = threading.RLock()
        self._model_size = "base"  # possible models: "tiny", "base", "small", "medium", "large-v3"

        if gremlin.config.VOICE_INPUT_ENABLED:
            self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")

        else:
            self._model = None

    def record(self):
        """ triggers a record from the default input """
        # List to store chunks of audio data dynamically
        import keyboard

        audio_chunks = []

        # Callback function to collect audio blocks from sounddevice
        def audio_callback(indata, frames, time_info, status):
            if status:
                syslog.info(status)
            # Append a copy of the incoming audio block
            audio_chunks.append(indata.copy())

        syslog.info("start speaking....press space to end")

        # Start recording with the callback
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32', callback=audio_callback):
            # Keep the stream open until the trigger key is pressed
            while True:
                if keyboard.is_pressed(TRIGGER_KEY):
                    syslog.info(f"\n[{TRIGGER_KEY.upper()}] pressed. Stopping recording...")
                    break
                time.sleep(0.1)  # Small sleep to prevent high CPU usage in the loop


        if audio_chunks:
            audio_data_flat = np.concatenate(audio_chunks, axis=0).flatten()
            return audio_data_flat

        return None




    def test(self):


        # channels=1 ensures mono audio, and dtype='float32' matches Whisper's expected input
        if not gremlin.config.VOICE_INPUT_ENABLED:
            syslog.info("Voice input is disabled.")
            return

        audio_data = self.record()
        if audio_data is None:
            return

        segments, info = self._model.transcribe(audio_data, beam_size=5)

        syslog.info(f"\nDetected language: '{info.language}' with probability {info.language_probability:.2f}")
        syslog.info("\n--- Transcription Result ---")
        for segment in segments:
            syslog.info(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")



