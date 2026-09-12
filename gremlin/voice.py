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
import re


from lxml import etree
from PySide6 import QtCore, QtMultimedia, QtWidgets
import gremlin.util
from gremlin.util import hashString, safe_format, safe_read, TimedRandomInt, hashString
from gremlin.base_classes import FastQueue
import queue
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
from PySide6.QtMultimedia import QMediaDevices, QAudioOutput
import threading
import logging
import os
import numpy as np
import time
import concurrent.futures
from rapidfuzz import process, fuzz

syslog = logging.getLogger("system")

SAMPLE_RATE = 16000  # Hz
TRIGGER_KEY = "space"  # Key to trigger recording


@gremlin.singleton_decorator.SingletonDecorator
class Voice:
    """speech recognition engine"""

    def __init__(self):
        os.environ["HF_HUB_VERBOSITY"] = "error"
        self._voice_lock = threading.RLock()
        self._audio_lock = threading.RLock()  # lock when adding new recognized words
        self._model_size = "small" # "base" #  possible models: "tiny", "base", "small", "medium", "large-v3"
        self._listening = False  # true if actively listening for voice input
        self._suspend_stack = 0  # > 1 if listening suspended
        self._listen_thread = None  # thread for listening to voice input
        self._process_thread = None  # thread for processing the incoming recognized words

        self._abort_event = threading.Event()
        self._stride_time = 0.5  # how long to capture audio before processing in seconds
        self._listen_time = 10  # how many seconds of audio to keep in the buffer
        self._sample_rate = SAMPLE_RATE
        self._buffer_size = 1024  # example buffer size, adjust as needed
        self._audio_queue = queue.Queue()
        self._language = "en"  # default language for transcription
        self.pool = concurrent.futures.ThreadPoolExecutor()  # supports mutliple concurrent tasks to process received words
        self._words = []  # words heard
        self._new_word = False  # flag to indicate if a new word has been added

        self._phrases = []  # phrases to match
        # test phrases to match
        self._phrases = ["gear up", "gear down", "self destruct", "abort mission","toggle gear"]  # example test phrases to match

        if gremlin.config.VOICE_INPUT_ENABLED:
            self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8") # use int8_float16 for CUDA
            #self._model = WhisperModel(self._model_size, device="cuda", compute_type="int8_float32") # use int8_float16 for CUDA
        else:
            self._model = None

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self.start)
        el.profile_stop.connect(self.stop)

    def pushSuspend(self):
        """increment the suspend stack to suspend listening"""
        with self._voice_lock:
            self._suspend_stack += 1

    def popSuspend(self, reset=False):
        """decrement the suspend stack to resume listening if possible"""
        with self._voice_lock:
            if reset:
                self._suspend_stack = 0
            elif self._suspend_stack > 0:
                self._suspend_stack -= 1

    def test(self):

        # channels=1 ensures mono audio, and dtype='float32' matches Whisper's expected input
        if not gremlin.config.VOICE_INPUT_ENABLED:
            syslog.info("Voice input is disabled.")
            return

        self.start()  # start to listen to audio

    def start(self):
        """start listening for voice input"""
        if self._model:
            if self._listening:
                return  # already listening
            syslog.info("Starting voice input...")
            with self._voice_lock:
                if self._suspend_stack == 0:  # not suspended
                    self._listening = True
                    self._abort_event.clear()
                    if self._listen_thread is None or not self._listen_thread.is_alive():
                        self._abort_event = threading.Event()
                        self._listen_thread = threading.Thread(target=self._listen_runner, args=(self._abort_event,))
                        self._listen_thread.name = "VoiceListen"
                        self._listen_thread.start()
                        self._process_thread = threading.Thread(target=self._process_runner, args=(self._abort_event,))
                        self._process_thread.name = "VoiceProcess"
                        self._process_thread.start()
                else:
                    self._listening = False

    def stop(self):
        """stop listening for voice input"""
        if self._model:
            if not self._listening:
                return
            syslog.info("Stopping voice input...")
            with self._voice_lock:
                self._listening = False
                if self._abort_event is not None:
                    self._abort_event.set()
                    self._listen_thread.join()
                    self._listen_thread = None
                    self._process_thread.join()
                    self._process_thread = None

    def _listen_runner(self, abort_event: threading.Event):
        """internal method run in a separate thread to handle listening"""

        syslog.info("Voice listen runner started...")

        # Callback function to collect audio blocks from sounddevice
        def audio_callback(indata, frames, time_info, status):
            # collect input audio data
            self._audio_queue.put(indata.copy())

        window_samples = int(self._listen_time * self._sample_rate)
        stride_samples = int(self._stride_time * self._sample_rate)
        audio_buffer = np.zeros(window_samples, dtype=np.float32)
        new_samples_count = 0
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype=np.float32, callback=audio_callback)
        with stream:
            # Keep the stream open until the trigger key is pressed
            while not abort_event.is_set():
                chunk = self._audio_queue.get()
                chunk_flattened = chunk.flatten()
                chunk_flattened = chunk_flattened * 2.0
                chunk_flattened = np.clip(chunk_flattened, -1.0, 1.0)
                chunk_size = len(chunk_flattened)

                audio_buffer = np.roll(audio_buffer, -chunk_size)
                audio_buffer[-chunk_size:] = chunk_flattened
                new_samples_count += chunk_size
                #syslog.info(f"chunk size: {chunk_size}  stride_samples: {stride_samples} sample count: {new_samples_count}")
                if new_samples_count >= stride_samples:
                    new_samples_count = 0
                    segments, info = self._model.transcribe(audio_buffer, beam_size=3, vad_filter=True, language=self._language)
                    if segments:
                        combined_text = "".join([segment.text for segment in segments])
                        word_list = re.findall(r'\b\w+\b', combined_text.casefold())
                        audio_buffer = np.zeros(window_samples, dtype=np.float32)
                        # fire a task to process the audio
                        with self._audio_lock:
                            self._words.extend(word_list)
                            if len(self._words) > 20:
                                self._words = self._words[-20:]
                            self._new_word = True
                #time.sleep(0.1)  # Small sleep to prevent high CPU usage in the loop

    def _process_runner(self, abort_event: threading.Event):
        """internal method run in a separate thread to handle processing recognized words"""
        syslog.info("Voice process runner started...")
        while not abort_event.is_set():
            if self._new_word and self._words:
                with self._audio_lock:
                    self._new_word = False
                    self._process_audio()
            time.sleep(0.1)  # small delay to prevent busy-waiting

    def _process_audio(self):
        """ process the recognized words"""
        # text_heard = " ".join(self._words)
        # match = process.extractOne(
        #     text_heard,
        #     self._phrases,
        #     scorer=fuzz.partial_ratio # Looks for the phrase inside a larger sentence
        # )
        # if match:
        #     phrase, score, index = match
        #     # A score above 85 generally handles typos perfectly without false positives
        #     if score > 85:
        #         syslog.info(f"*************** Matched phrase: {phrase} with score: {score}")
        #         self._words.clear()
        #         return
        syslog.info(f"Processing word list: {self._words}")

        matches = self.recognize_phrases(
            self._words,
            self._phrases,
            threshold=85,
        )

        for match in matches:
            syslog.info(f"Matched phrase: {match}")



    def recognize_phrases(self,
        rolling_words: list[str],
        command_phrases: list[str],
        threshold: int = 85,
    ) -> list[str]:
        """
        Finds fuzzy phrase matches in rolling_words, removes them in place,
        and returns the recognized command phrases.
        """
        commands = [
            (phrase, phrase.lower().split())
            for phrase in command_phrases
        ]

        # Prefer longer phrases over shorter overlapping phrases.
        commands.sort(key=lambda item: len(item[1]), reverse=True)

        recognized = []
        match_found = True

        while match_found:
            match_found = False

            for phrase, phrase_words in commands:
                phrase_length = len(phrase_words)

                if phrase_length > len(rolling_words):
                    continue

                # Check every contiguous window of the appropriate length.
                for start in range(len(rolling_words) - phrase_length + 1):
                    end = start + phrase_length
                    candidate = " ".join(rolling_words[start:end])

                    score = fuzz.ratio(
                        candidate.lower(),
                        " ".join(phrase_words),
                    )

                    if score >= threshold:
                        recognized.append(phrase)
                        del rolling_words[start:end]
                        match_found = True
                        break

                if match_found:
                    # Restart because rolling_words was modified.
                    break

        return recognized