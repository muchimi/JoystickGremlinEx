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


import gc
import hashlib
import os
import html
import sys
import re
import string
from typing import Callable, Union

import comtypes
from lxml import etree
from PySide6 import QtCore, QtMultimedia, QtWidgets
import gremlin.util
from gremlin.util import hashString, safe_format, safe_read, TimedRandomInt, hashString
from collections import deque
import queue
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
from PySide6.QtMultimedia import QAudioInput, QMediaDevices, QAudioOutput
import threading
import logging
import os
import numpy as np
import time
import concurrent.futures
from rapidfuzz import process, fuzz
from psygnal import Signal

import sounddevice as sd
from comtypes import CoInitialize, CoUninitialize, GUID
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL

# avoid the avalanche of warnings from pycaw
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="pycaw")
from pycaw.pycaw import DEVICE_STATE, AudioUtilities, IAudioEndpointVolume, EDataFlow, IMMEndpoint, IMMDeviceEnumerator  # noqa: E402
from pycaw.constants import CLSID_MMDeviceEnumerator  # noqa: E402


class PROPERTYKEY(comtypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", comtypes.wintypes.DWORD)]


PKEY_Device_FriendlyName = PROPERTYKEY(GUID("{a45c254e-df1c-4efd-8020-67d146a850e0}"), 14)


# usage

SAMPLE_RATE = 16000
BLOCKSIZE = 1600


syslog = logging.getLogger("system")

SAMPLE_RATE = 16000  # Hz
TRIGGER_KEY = "space"  # Key to trigger recording


def audio_level_db(audio):
    """Return RMS audio level in dBFS."""
    audio = np.asarray(audio, dtype=np.float32)

    if audio.size == 0:
        return -100.0

    rms = np.sqrt(np.mean(audio * audio))

    if rms < 1e-10:
        return -100.0

    return 20.0 * np.log10(rms)


def apply_gain(audio, gain_db):
    """applies gain in decibels to the audio signal."""
    gain = 10.0 ** (gain_db / 20.0)

    # prevent clipping
    return np.clip(
        audio * gain,
        -1.0,
        1.0,
    )


class SpeechAudioProcessor:
    """
    Continuous speech-audio processor.
    Features:
        - RMS / dBFS level measurement
        - adaptive noise-floor estimation
        - dynamic voice-activity detection
        - VAD attack/release hysteresis
        - automatic gain control
        - pre-roll audio
        - post-roll / hangover audio
    """

    autoGainChanged = Signal(float)  # emits the automatic gain (current gain in dB) when it changes

    def __init__(
        self,
        sample_rate=16000,
        blocksize=1600,
        # AGC
        target_db=-20.0,
        max_gain_db=20.0,
        gain_attack=0.20,
        gain_release=0.03,
        # Noise estimation
        initial_noise_db=-60.0,
        noise_alpha=0.02,
        # VAD
        speech_margin_db=10.0,
        min_speech_db=-50.0,
        speech_attack_blocks=2,
        speech_release_blocks=2,
        # Pre/post roll
        pre_roll_ms=300,
        post_roll_ms=400,
    ):
        self.sample_rate = sample_rate
        self.blocksize = blocksize

        # AGC
        self.target_db = target_db
        self.max_gain_db = max_gain_db
        self.gain_attack = gain_attack
        self.gain_release = gain_release

        self.gain_db = 0.0
        self._last_gain_db = 0.0

        # Noise floor
        self.noise_floor_db = initial_noise_db
        self.noise_alpha = noise_alpha

        # VAD
        self.speech_margin_db = speech_margin_db
        self.min_speech_db = min_speech_db

        self.speech_attack_blocks = speech_attack_blocks
        self.speech_release_blocks = speech_release_blocks

        self.speech_counter = 0
        self.silence_counter = 0

        self.is_speech = False

        # -----------------------------------------------------
        # Convert milliseconds to block counts
        # -----------------------------------------------------

        block_ms = blocksize / sample_rate * 1000.0

        self.pre_roll_blocks = max(
            1,
            int(np.ceil(pre_roll_ms / block_ms)),
        )

        self.post_roll_blocks = max(
            0,
            int(np.ceil(post_roll_ms / block_ms)),
        )

        # Rolling audio before speech begins.
        self.pre_roll = deque(maxlen=self.pre_roll_blocks)

        # Remaining post-roll blocks.
        self.post_roll_remaining = 0

        # True while an utterance is being emitted,
        # including its post-roll.
        self.in_utterance = False

    # ---------------------------------------------------------
    # Level / VAD
    # ---------------------------------------------------------

    def _speech_threshold(self):
        return max(
            self.min_speech_db,
            self.noise_floor_db + self.speech_margin_db,
        )

    def _update_noise_floor(self, level_db):
        """
        Update the ambient-noise estimate only when we're
        safely outside an utterance.
        """

        if self.in_utterance:
            return

        if not np.isfinite(level_db):
            return

        # Don't learn obvious speech/transients as noise.
        if level_db > self.noise_floor_db + self.speech_margin_db:
            return

        self.noise_floor_db += (level_db - self.noise_floor_db) * self.noise_alpha

    def _detect_speech(self, level_db):
        """
        Adaptive VAD with attack/release hysteresis.
        """

        threshold_db = self._speech_threshold()

        raw_speech = level_db >= threshold_db

        if raw_speech:
            self.speech_counter += 1
            self.silence_counter = 0

            if self.speech_counter >= self.speech_attack_blocks:
                self.is_speech = True

        else:
            self.silence_counter += 1
            self.speech_counter = 0

            if self.silence_counter >= self.speech_release_blocks:
                self.is_speech = False

        return self.is_speech, threshold_db

    # ---------------------------------------------------------
    # AGC
    # ---------------------------------------------------------

    def _update_gain(self, level_db):
        """
        AGC follows actual detected speech.
        Silence/post-roll does not cause the AGC to increase
        gain and amplify background noise.
        """

        if not self.is_speech:
            return

        desired_gain = np.clip(
            self.target_db - level_db,
            0.0,
            self.max_gain_db,
        )

        if desired_gain > self.gain_db:
            rate = self.gain_attack
        else:
            rate = self.gain_release

        self.gain_db += (desired_gain - self.gain_db) * rate
        if self._last_gain_db != self.gain_db:
            self._last_gain_db = self.gain_db
            self.autoGainChanged.emit(self.gain_db)

    # ---------------------------------------------------------
    # Main processing
    # ---------------------------------------------------------

    def process(self, audio):
        """
        Process one microphone block.
        Returns:
            output_audio:
                Audio to send to the recognizer, or None.
                At speech start:
                    pre-roll + current block
                During speech:
                    current block
                During post-roll:
                    current block
            info:
                Processing/VAD status.
        """

        audio = np.asarray(
            audio,
            dtype=np.float32,
        ).reshape(-1)

        # -----------------------------------------------------
        # Measure input
        # -----------------------------------------------------

        level_db = audio_level_db(audio)

        was_speech = self.is_speech

        # -----------------------------------------------------
        # Update noise estimate
        # -----------------------------------------------------

        self._update_noise_floor(level_db)

        # -----------------------------------------------------
        # VAD
        # -----------------------------------------------------

        is_speech, threshold_db = self._detect_speech(level_db)

        vad_started = is_speech and not was_speech

        vad_stopped = was_speech and not is_speech

        # -----------------------------------------------------
        # AGC
        # -----------------------------------------------------

        self._update_gain(level_db)

        processed = apply_gain(
            audio,
            self.gain_db,
        )

        output_audio = None

        speech_started = False
        speech_ended = False

        # -----------------------------------------------------
        # Speech begins
        # -----------------------------------------------------

        if vad_started:
            # If we were already in post-roll, speech resumed.
            # This is the same utterance.
            if self.in_utterance:
                self.post_roll_remaining = 0

                output_audio = processed

            else:
                self.in_utterance = True
                speech_started = True

                if self.pre_roll:
                    output_audio = np.concatenate(
                        [
                            *self.pre_roll,
                            processed,
                        ]
                    )

                else:
                    output_audio = processed

                self.pre_roll.clear()

        # -----------------------------------------------------
        # Active speech
        # -----------------------------------------------------

        elif is_speech:
            self.in_utterance = True

            # Any renewed speech cancels post-roll.
            self.post_roll_remaining = 0

            output_audio = processed

        # -----------------------------------------------------
        # VAD has just stopped
        # -----------------------------------------------------

        elif vad_stopped and self.in_utterance:
            #
            # Current block is the first post-roll block.
            #
            self.post_roll_remaining = self.post_roll_blocks

            if self.post_roll_remaining > 0:
                output_audio = processed

                self.post_roll_remaining -= 1

            else:
                self.in_utterance = False
                speech_ended = True

        # -----------------------------------------------------
        # Continue post-roll
        # -----------------------------------------------------

        elif self.in_utterance and self.post_roll_remaining > 0:
            output_audio = processed

            self.post_roll_remaining -= 1

            if self.post_roll_remaining == 0:
                self.in_utterance = False
                speech_ended = True

        # -----------------------------------------------------
        # Normal silence
        # -----------------------------------------------------

        else:
            self.in_utterance = False

            #
            # Save recent audio for the next pre-roll.
            #
            self.pre_roll.append(processed.copy())

        info = {
            "level_db": level_db,
            "noise_db": self.noise_floor_db,
            "threshold_db": threshold_db,
            "gain_db": self.gain_db,
            "is_speech": is_speech,
            "in_utterance": self.in_utterance,
            "speech_started": speech_started,
            "speech_ended": speech_ended,
            "post_roll_remaining": self.post_roll_remaining,
        }

        return output_audio, info

    def reset(self):
        """Reset VAD and buffering state."""

        self.pre_roll.clear()

        self.speech_counter = 0
        self.silence_counter = 0

        self.is_speech = False
        self.in_utterance = False

        self.post_roll_remaining = 0


class SpeechRecognizer:
    def __init__(
        self,
        model_size="small.en",
        sample_rate=16000,
        device="cpu",
        compute_type="int8",
        callback: Callable = None,
    ):
        self.sample_rate = sample_rate
        self.callback = callback

        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )

        self._queue = queue.Queue()

        self._audio = []
        self._running = False
        self._abort_event = threading.Event()

        self.verbose = True

    def start(self):
        """Start the recognition thread."""
        if self._running:
            return
        # if self.verbose:
        #     syslog.info("Recog: starting recognition thread")
        self._running = True
        self._abort_event.clear()
        self._thread = threading.Thread(
            target=self._worker,
            args=(self._abort_event,),
        )

        self._thread.name = "SpeechRecognizer"
        self._thread.start()

    def stop(self):
        """Stop the recognition thread."""
        if self._running:
            # if self.verbose:
            #     syslog.info("Recog: stopping recognition thread")
            self._running = False
            self._abort_event.set()
            self._queue.put(None)

            self._thread.join(timeout=2.0)

    def add_audio(
        self,
        audio,
        speech_started=False,
        speech_ended=False,
    ):
        """
        Queue audio for recognition.

        This method returns immediately and is safe to call
        from the sounddevice callback.
        """

        if audio is not None:
            audio = (
                np.asarray(
                    audio,
                    dtype=np.float32,
                )
                .reshape(-1)
                .copy()
            )

        # if self.verbose:
        #     syslog.info(f"adding audio to recognize queue started: {speech_started}, ended: {speech_ended}")
        self._queue.put(
            (
                audio,
                speech_started,
                speech_ended,
            )
        )

    # ---------------------------------------------------------
    # Worker thread
    # ---------------------------------------------------------

    def _worker(self, abort_event):
        # verbose = self.verbose
        # if verbose:
        #     syslog.info("Recog: worker thread runner started")
        while not abort_event.is_set():
            item = self._queue.get()
            # if verbose:
            #     syslog.info(f"Recog: has data: {item is not None}")

            if item is None:
                # got signal break
                syslog.info("Recog: received stop signal, breaking worker loop")
                break

            audio, started, ended = item

            if started:
                # Speech has started
                # if verbose:
                #     syslog.info("Recog: SPEECH STARTED")
                self._audio.clear()

            if audio is not None:
                # syslog.info(f"Recog: got audio chunk of length {len(audio)}")
                self._audio.append(audio)

            if ended:
                # Speech has ended
                # if verbose:
                #     syslog.info("Recog: SPEECH ENDED")
                self._recognize()

        # if verbose:
        #     syslog.info("Recog: worker thread runner stopped")

    # ---------------------------------------------------------
    # Recognition
    # ---------------------------------------------------------

    def _recognize(self):

        # syslog.info("_recognize called")

        if not self._audio:
            return

        audio = np.concatenate(self._audio)

        self._audio.clear()

        # Ignore extremely short utterances.
        duration = len(audio) / self.sample_rate

        # syslog.info(f"\nDuration: {duration}")

        if duration < 0.15:
            return

        # syslog.info("\ntranscribe")
        segments, info = self.model.transcribe(
            audio,
            language="en",
            vad_filter=True,
            beam_size=2,
            condition_on_previous_text=False,
        )
        words = []
        for segment in segments:
            text = segment.text.strip().casefold()
            if text:
                if self.verbose:
                    syslog.info(f"Processing segment: {text}")
                words.extend([w.strip(string.punctuation) for w in text.split()])

        if words and self.callback:
            syslog.info(f"Recognized words: count {len(words)}: {words}")
            self.callback(words)


DEFAULT_FILLER_WORDS = {
    # Articles / politeness
    "a",
    "an",
    "the",
    "please",
    "kindly",
    # Hesitation
    "uh",
    "um",
    "umm",
    "uhh",
    "erm",
    "er",
    "hmm",
    "hm",
    # Conversational filler
    "actually",
    "basically",
    "essentially",
    "literally",
    "honestly",
    "obviously",
    "apparently",
    "anyway",
    "anyways",
    "well",
    # Greetings / padding
    "hey",
    "hello",
    "hi",
}


class VoiceCommand:
    """holds voice command information including a callback called when the command is triggered"""

    def __init__(self, phrase, callback=None, key=None, owner=None):
        self.key = key if key is not None else gremlin.util.get_guid()
        self.phrase = phrase.casefold().strip() if phrase is not None else None
        self._callbacks = [] # list of callbacks
        if callback is not None:
            self.registerCallback(callback)
        self.owner = owner
        self.meaningful_length = None
        self._update_key()


    def registerCallback(self, callback):
        """Adds a callback to the list of callbacks."""
        if callback is not None and callback not in self._callbacks:
            self._callbacks.append(callback)

    def removeCallback(self, callback):
        """Removes a callback from the list of callbacks."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def clearCallbacks(self):
        """Clears all callbacks from the list of callbacks."""
        self._callbacks.clear()

    @property
    def key(self) -> str:
        """ unique key for this command - based on the phrase or id """
        if self._key is None:
            self._update_key()
        return self._key

    @key.setter
    def key(self, value):
        raise ValueError("Key is readonly")


    def _update_key(self):
        """ updates the unique key value for the command """
        # key depends on the phrase and not the owner because voice recognition would not know otherwise, in the case of duplicate
        # phrases, which input to trigger.  This is checked when inputs are added.
        if self._phrase is not None:
            self._key = hash(self._phrase)
        else:
            self._key = hash(self._id)

    @property
    def id(self):
        """ id of this object - changes for ever instance and not persisted """
        return self._id

    @property
    def hashKey(self) -> str:
        return self.key

    @property
    def phrase(self):
        return self._phrase

    @phrase.setter
    def phrase(self, value):
        if value:
            value = value.casefold().strip()
        if self._phrase != value:
            self._phrase = value
            self._key = hash(self._phrase)

    @property
    def callback(self) -> Callable[[VoiceCommand], None]:
        return self._callback

    @callback.setter
    def callback(self, value):
        self._callback = value

    @property
    def owner(self) -> str:
        """ owner of this command - this usually is the input item that owns this command in the voice device """
        return self._owner

    @owner.setter
    def owner(self, value):
        self._owner = value

    def trigger(self):
        """triggers the registered callbacks for the voice command """
        for callback in self._callbacks:
            callback(self)


    def __str__(self):
        return f"VoiceCommand(key=[{self.key}], phrase=[{self.phrase}])"


class CommandMatcher:
    """
    Match a rolling stream of recognized speech words against
    a fixed list of command phrases.
    Features:
        - exact matching
        - fuzzy word matching
        - filler words
        - missing words
        - extra words
        - adjacent word swaps
        - rolling-buffer consumption
    """

    def __init__(
        self,
        commands,
        *,
        filler_words=None,
        fuzzy_match=True,
        fuzzy_threshold=89,
        word_threshold=60,
        gap_penalty=25,
        filler_penalty=2,
        swap_penalty=10,
        max_extra_words=5,
        callback: Callable = None,
    ):
        """
        Initializes the CommandMatcher with the given commands and matching parameters.

        Args:
            commands (list): List of VoiceCommand instances or command strings.
            filler_words (set, optional): Set of filler words to ignore. Defaults to None.
            fuzzy_match (bool, optional): Enable fuzzy matching. Defaults to True.
            fuzzy_threshold (int, optional): Threshold for fuzzy matching. Defaults to 89.
            word_threshold (int, optional): Threshold for individual word matching. Defaults to 60.
            gap_penalty (int, optional): Penalty for gaps in matching. Defaults to 25.
            filler_penalty (int, optional): Penalty for filler words. Defaults to 2.
            swap_penalty (int, optional): Penalty for adjacent word swaps. Defaults to 10.
            max_extra_words (int, optional): Maximum allowed extra words. Defaults to 5.
            callback (Callable, optional): Callback function when a command is matched. Passes the recognized command.
        """
        self.fuzzy_match = fuzzy_match
        self.fuzzy_threshold = fuzzy_threshold
        self.word_threshold = word_threshold
        self.gap_penalty = gap_penalty
        self.filler_penalty = filler_penalty
        self.swap_penalty = swap_penalty
        self.max_extra_words = max_extra_words
        self.callback = callback  # called when a command is matched
        self._callbacks = [] # list of callbacks
        self._buffer = deque()
        self._commands = []
        self.verbose = gremlin.config.Configuration().verbose_mode_voice

        self.filler_words = {word.lower() for word in (filler_words if filler_words is not None else DEFAULT_FILLER_WORDS)}

        self._command_map = {}  # holds the commands
        if commands:
            for command in commands:
                assert isinstance(command, VoiceCommand), "Command must be a VoiceCommand instance"
                assert command.owner is not None,"VoiceCommand must have an owner"
                vc = command



                words = self._tokenize(vc.phrase)

                vc.registerCallback(self._handle_command_trigger)
                vc.meaningful_length = self._meaningful_length(words)
                vc.words = words

                self._command_map[vc.key] = vc

            self._update_commands()

        if callback is not None:
            self.registerCallback(callback)

    def registerCallback(self, callback):
        """Adds a callback to the list of callbacks."""
        if callback is not None and callback not in self._callbacks:
            self._callbacks.append(callback)

    def removeCallback(self, callback):
        """Removes a callback from the list of callbacks."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def clearCallbacks(self):
        """Clears all callbacks from the list of callbacks."""
        self._callbacks.clear()

    def _handle_command_trigger(self, command : VoiceCommand):
        # fire the command callback, passes the command
        for callback in self._callbacks:
            callback(command)

    def hasCommands(self):
        return bool(self._commands)

    def _update_commands(self):
        self._commands = list(self._command_map.values())
        if self._commands:
            # Prefer longer / more specific commands.
            self._commands.sort(
                key=lambda vc: vc.meaningful_length,
                reverse=True,
            )

            self._max_command_words = max(len(command.words) for command in self._commands)

            self._buffer = deque(maxlen=self._max_command_words + self.max_extra_words)
        else:
            self._buffer = deque()

    def getCommands(self) -> list:
        return self._commands

    def count(self) -> int:
        """gets the number of commands currently in the matcher"""
        return len(self._commands)

    def addCommands(self, commands: list[VoiceCommand] | VoiceCommand):
        """adds multiple commands to the matcher - duplicates are ignored"""
        if isinstance(commands, VoiceCommand):
            # singleton
            commands = [commands]

        :param command: The command to add. Can be a VoiceCommand instance or a string representing the phrase.  If a voice command, callback will be called when a match occurs with the key.
        """
        if isinstance(command, VoiceCommand):
            vc = command
        else:
            vc = VoiceCommand(command)
        vc.words = self._tokenize(vc.phrase)
        vc.meaningful_length = self._meaningful_length(vc.words)
        self._command_map[vc.key] = vc
        vc.registerCallback(self._handle_command_trigger)

        self._update_commands()

        for command in commands:
            if isinstance(command, VoiceCommand):
                vc = command
            else:
                vc = VoiceCommand(command)
            vc.words = self._tokenize(vc.phrase)
            vc.meaningful_length = self._meaningful_length(vc.words)
            if verbose:
                syslog.info(f"Voice: Command: registered [{vc.phrase}] length: {vc.meaningful_length}")

            self._command_map[vc.key] = vc
            vc.registerCallback(self._handle_command_trigger)
        self._update_commands()

    def removeCommand(self, command: Union[VoiceCommand, str]):
        """removes a single command from the matcher"""
        if isinstance(command, VoiceCommand):
            key = command.key
        else:
            key = VoiceCommand(command).key
        if key in self._command_map:
            vc = self._command_map[key]
            vc.removeCallback(self._handle_command_trigger)
            del self._command_map[key]
            self._update_commands()


    def clearCommands(self):
        """clears all commands from the matcher"""
        for vc in self._command_map.values():
            vc.removeCallback(self._handle_command_trigger)
        self._command_map.clear()
        self._update_commands()

    def add_words(self, words):
        """adds multiple heard words to the matcher"""
        for word in words:
            self.add_word(word)

    def add_word(self, word):
        """
        adds a single word
        triggers any matching command
        Returns:
            matched command, or None

        """

        word = self._clean_word(word)

        if not word:
            return None

        self._buffer.append(word)

        words = list(self._buffer)

        # exact matching
        exact = self._find_exact_match(words)

        if exact is not None:
            command, start = exact

            self._consume_from(start)

            command.trigger()
            return command

        if not self.fuzzy_match:
            # no fuzzy match
            return None

        # fuzzy matching
        best_command = None
        best_score = 0.0
        best_start = None

        for command in self._commands:
            target = command.words

            target_length = len(target)

            # work on recent words only
            min_window = max(
                1,
                target_length - 2,
            )

            max_window = min(
                len(words),
                target_length + self.max_extra_words,
            )

            for window_size in range(
                min_window,
                max_window + 1,
            ):
                start = len(words) - window_size
                window = words[start:]

                score = self._dynamic_score(
                    window,
                    target,
                )

                if score > best_score:
                    best_score = score
                    best_command = command
                    best_start = start

                syslog.info(f"Fuzzy match candidate: [{command.phrase}] with score [{score}]")

        if best_command is not None: # and best_score >= self.fuzzy_threshold:
            self._consume_from(best_start)

            best_command.trigger()
            return best_command

        return None

    def add_phrase(self, text):
        """Add a new phrase to the rolling matcher."""
        words = text.split()
        for word in words:
            self.add_word(word)

    def clear(self):
        """Clear the rolling speech buffer."""

        self._buffer.clear()

    def get_buffer(self):
        """Return the current rolling words."""

        return list(self._buffer)

    # ---------------------------------------------------------
    # Exact matching
    # ---------------------------------------------------------


    def _find_exact_match(self, words):
        """
        Exact comparison while allowing filler words
        to exist on either side.
        """

        for command in self._commands:
            target = command.words
            target_nonfiller_len = self._meaningful_length(target)

            # Search all windows, not only suffixes.
            for start in range(len(words)):
                nonfiller_seen = 0
                for end in range(start + 1, len(words) + 1):
                    w = words[end - 1]
                    if not self._is_filler(w):
                        nonfiller_seen += 1

                    # stop once we exceeded target meaningful length
                    if nonfiller_seen > target_nonfiller_len:
                        break

                    window = words[start:end]
                    if self._equal_ignoring_fillers(window, target):
                        return command, start

        return None

    # old
    # def _find_exact_match(self, words):
    #     """
    #     Exact comparison while allowing filler words
    #     to exist on either side.
    #     """

    #     for command in self._commands:
    #         target = command.words

    #         for start in range(len(words)):
    #             window = words[start:]

    #             if self._equal_ignoring_fillers(
    #                 window,
    #                 target,
    #             ):
    #                 return command, start

    #     return None

    def _equal_ignoring_fillers(self, spoken, target):
        """
        Compare two word sequences after removing filler words.
        """

        spoken = [word for word in spoken if not self._is_filler(word)]

        target = [word for word in target if not self._is_filler(word)]

        return spoken == target

    # ---------------------------------------------------------
    # Dynamic matching
    # ---------------------------------------------------------

    def _dynamic_score(self, spoken, target):
        """
        Dynamic-programming alignment between two phrases.
        Supports:
            fuzzy substitution
            missing words
            extra words
            filler words
            adjacent transposition
        Returns:
            score from 0 to 100
        """

        n = len(spoken)
        m = len(target)

        if not n or not m:
            return 0.0

        inf = float("inf")

        dp = [[inf] * (m + 1) for _ in range(n + 1)]

        dp[0][0] = 0.0

        # -----------------------------------------------------
        # Initial insertion / deletion costs
        # -----------------------------------------------------

        for i in range(1, n + 1):
            dp[i][0] = dp[i - 1][0] + self._gap_cost(spoken[i - 1])

        for j in range(1, m + 1):
            dp[0][j] = dp[0][j - 1] + self._gap_cost(target[j - 1])

        # -----------------------------------------------------
        # Dynamic alignment
        # -----------------------------------------------------

        for i in range(1, n + 1):
            spoken_word = spoken[i - 1]

            for j in range(1, m + 1):
                target_word = target[j - 1]

                # ---------------------------------------------
                # Fuzzy word substitution
                # ---------------------------------------------

                similarity = fuzz.ratio(
                    spoken_word,
                    target_word,
                )

                substitution_cost = 100 - similarity

                #
                # Strongly discourage completely unrelated words.
                #
                if similarity < self.word_threshold:
                    substitution_cost += self.gap_penalty

                substitution = dp[i - 1][j - 1] + substitution_cost

                # ---------------------------------------------
                # Extra spoken word
                # ---------------------------------------------

                insertion = dp[i - 1][j] + self._gap_cost(spoken_word)

                # ---------------------------------------------
                # Missing spoken word
                # ---------------------------------------------

                deletion = dp[i][j - 1] + self._gap_cost(target_word)

                dp[i][j] = min(
                    substitution,
                    insertion,
                    deletion,
                )

                # ---------------------------------------------
                # Adjacent word transposition
                #
                # spoken:
                #     turn lights on
                #
                # target:
                #     turn on lights
                # ---------------------------------------------

                if i >= 2 and j >= 2:
                    s1 = spoken[i - 2]
                    s2 = spoken[i - 1]

                    t1 = target[j - 2]
                    t2 = target[j - 1]

                    score1 = fuzz.ratio(s1, t2)
                    score2 = fuzz.ratio(s2, t1)

                    if score1 >= self.word_threshold and score2 >= self.word_threshold:
                        swap_cost = (100 - score1) + (100 - score2) + self.swap_penalty

                        swap = dp[i - 2][j - 2] + swap_cost

                        dp[i][j] = min(
                            dp[i][j],
                            swap,
                        )

        penalty = dp[n][m]

        # -----------------------------------------------------
        # Normalize to 0..100
        # -----------------------------------------------------

        meaningful_length = max(
            1,
            self._meaningful_length(spoken),
            self._meaningful_length(target),
        )

        max_penalty = meaningful_length * 100

        score = 100 * (1 - penalty / max_penalty)

        return max(
            0.0,
            min(100.0, score),
        )

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    def _gap_cost(self, word):
        """
        Filler words are almost free.
        Important command words receive the normal
        insertion/deletion penalty.
        """

        if self._is_filler(word):
            return self.filler_penalty

        return self.gap_penalty

    def _is_filler(self, word):
        return word in self.filler_words

    def _meaningful_length(self, words):
        return sum(1 for word in words if not self._is_filler(word))

    def _tokenize(self, text):
        return [self._clean_word(word) for word in text.split() if self._clean_word(word)]

    @staticmethod
    def _clean_word(word):
        """
        Basic cleanup for speech-recognition tokens.
        """

        return word.lower().strip().strip(".,!?;:\"'()[]{}")

    def _consume_from(self, start):
        """
        Remove the recognized command and everything
        after its starting position.
        Words before the command remain in the buffer.
        """

        words = list(self._buffer)

        self._buffer.clear()

        self._buffer.extend(words[:start])


@gremlin.singleton_decorator.SingletonDecorator
class Voice:
    """speech recognition engine"""

    # info parameters sent by the audioMonitor signal:
    # - "level_db" (float): the audio level in decibels
    # - "gain_db" (float): the current gain applied to the audio in decibels
    # - "noise_db" (float): the estimated background noise level in decibels
    # - "threshold_db" (float): the threshold level in decibels for detecting significant audio events
    # - "is_speech" (bool): indicates whether the current audio segment contains detected speech
    # - "speech_started" (bool): indicates whether speech has started in the current audio segment
    # - "speech_ended" (bool): indicates whether speech has ended in the current audio segment
    # - "post_roll_remaining" (float): the remaining duration of the post-roll period in seconds

    audioMonitor = Signal(dict)  # send audio monitor data

    def __init__(
        self,
        commands: list = None,
        fuzzy_match=True,
        fuzzy_threshold=89,
    ):
        os.environ["HF_HUB_VERBOSITY"] = "error"
        self.verbose = False
        self._voice_lock = threading.RLock()
        self._audio_lock = threading.RLock()  # lock when adding new recognized words
        self._model_size = "small"  # "base" #  possible models: "tiny", "base", "small", "medium", "large-v3"
        self._listening = False  # true if actively listening for voice input
        self._listen_enabled = False  # true if listening is enabled while monitoring
        self._listen_lock = threading.RLock()

        self._suspend_stack = 0  # > 1 if listening suspended
        self._recognize_stack = 0  # > 1 if recognition is suspended
        self._listen_thread = None  # thread for listening to voice input
        self._abort_event = threading.Event()
        self._sample_rate = SAMPLE_RATE
        self._buffer_size = 1024  # example buffer size, adjust as needed
        self._audio_queue = queue.Queue()
        self._language = "en"  # default language for transcription
        self.pool = concurrent.futures.ThreadPoolExecutor()  # supports mutliple concurrent tasks to process received words
        self._words = []  # words heard
        self._new_word = False  # flag to indicate if a new word has been added
        self._volume = 0.0  # default volume level (system microphone level)

        self._callbacks = []

        self._rolling_matcher = CommandMatcher(commands=commands,
                                               fuzzy_match=fuzzy_match,
                                               fuzzy_threshold=fuzzy_threshold,
                                               callback=self._handle_command_trigger)

        el = gremlin.event_handler.EventListener()
        el.profile_start.connect(self.start)
        el.profile_stop.connect(self.stop)

    def registerCallback(self, callback):
        """register a callback to be invoked when a command is triggered"""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def removeCallback(self, callback):
        """remove a previously registered callback"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _handle_command_trigger(self, command: VoiceCommand):
        """ trigger all registered callbacks with the given command  when that command is triggered """
        for callback in self._callbacks:
            callback(command)

    def addCommand(self, command: VoiceCommand):
        """adds a single command to the matcher - duplicates are ignored"""
        if command is not None:
            self._rolling_matcher.addCommands([command])

    def addCommands(self, commands: list):
        """adds multiple commands to the matcher - duplicates are ignored"""
        self._rolling_matcher.addCommands(commands)

    def getCommands(self) -> list:
        return self._rolling_matcher.getCommands()

    def clearCommands(self):
        """clears all commands from the matcher"""
        self._rolling_matcher.clearCommands()

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

    def pushRecognize(self):
        """increment the recognize stack to suspend recognition"""
        with self._voice_lock:
            self._recognize_stack += 1

    def popRecognize(self, reset=False):
        """decrement the recognize stack to resume recognition if possible"""
        with self._voice_lock:
            if reset:
                self._recognize_stack = 0
            elif self._recognize_stack > 0:
                self._recognize_stack -= 1

    def setListen(self, enable: bool):
        """enable or disable listening while monitoring"""
        with self._listen_lock:
            self._listen_enabled = enable
        if self.verbose:
            syslog.info(f"Voice: Listening set to {'enabled' if enable else 'disabled'}")

    def listenEnabled(self) -> bool:
        """returns whether listening is currently enabled"""
        with self._listen_lock:
            return self._listen_enabled

    def test(self):

        # channels=1 ensures mono audio, and dtype='float32' matches Whisper's expected input
        if not gremlin.config.VOICE_INPUT_ENABLED:
            syslog.info("Voice input is disabled.")
            return

        self.start()  # start to listen to audio

    def start(self):
        """start listening for voice input"""
        if self._listening:
            return  # already listening

        syslog.info("Starting voice input...")

        self.processor = SpeechAudioProcessor(
            sample_rate=SAMPLE_RATE,
            blocksize=BLOCKSIZE,
            target_db=-20.0,
            max_gain_db=18.0,
            speech_margin_db=10.0,
            pre_roll_ms=300,
            post_roll_ms=400,
        )

        self.recognizer = SpeechRecognizer(
            model_size="small.en",
            sample_rate=SAMPLE_RATE,
            device="cpu",
            compute_type="int8",
            callback=self._on_recognized,
        )

        self.recognizer.start()

        with self._voice_lock:
            if self._suspend_stack == 0:  # not suspended
                self._listening = True
                self._abort_event.clear()
                if self._listen_thread is None or not self._listen_thread.is_alive():
                    self._abort_event = threading.Event()
                    self._listen_thread = threading.Thread(target=self._listen_runner, args=(self._abort_event,))
                    self._listen_thread.name = "VoiceListen"
                    self._listen_thread.start()
            else:
                self._listening = False


    def _on_recognized(self, words: list[str]):
        """callback when speech is recognized"""
        self._rolling_matcher.add_words(words)

    def stop(self):
        """stop listening for voice input"""
        if not self._listening and self._listen_thread is None:
            return

        syslog.info("Stopping voice input...")
        with self._voice_lock:
            self._listening = False
            self._abort_event.set()
            self._listen_thread.join(timeout=2)
            self._listen_thread = None
            self.recognizer.stop()

    # def _listen_runner(self, abort_event: threading.Event):
    #     """internal method run in a separate thread to handle listening"""

    #     syslog.info("Voice listen runner started...")

    #     def callback(indata, frames, time_info, status):
    #         if status:
    #             syslog.info(f"Audio: {status}")

    #         with self._listen_lock:
    #             if not self._listen_enabled:
    #                 # not listening - ignore incoming audio
    #                 return

    #         audio = indata[:, 0]

    #         output, info = self.processor.process(audio)

    #         if self._recognize_stack == 0 and self._rolling_matcher.hasCommands():  # speech recognition enabled
    #             # speech recognition enabled
    #             speech_started = info["speech_started"]
    #             speech_ended = info["speech_ended"]
    #             if output is not None:
    #                 # syslog.info(f"Audio: SPEECH DETECTED  started: {speech_started}, ended: {speech_ended}")
    #                 self.recognizer.add_audio(output, speech_started, speech_ended)

    #         # monitor mode
    #         self.audioMonitor.emit(info)

    #     stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype=np.float32, callback=callback)
    #     with stream:
    #         # Keep the stream open until the trigger key is pressed
    #         while not abort_event.is_set():
    #             time.sleep(0.01)  # Small sleep to prevent high CPU usage in the loop

    def _listen_runner(self, abort_event: threading.Event):
        """Internal method run in a separate thread to handle listening."""

        # if self.verbose:
        #     syslog.info("Voice listen runner started...")
        audio_queue = queue.Queue(maxsize=64)

        def callback(indata, frames, time_info, status):
            if status:
                if status.input_overflow:
                    syslog.warning("Audio input overflow")
                else:
                    syslog.info("Audio: %s", status)

            try:
                # Input buffers are reused after the callback returns.
                audio_queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                # Drop audio rather than blocking the real-time callback.
                syslog.warning("Audio processing queue full; dropping block")

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype=np.float32,
            callback=callback,
            blocksize=0,
            latency="high",
        )

        with stream:
            while not abort_event.is_set():
                try:
                    audio = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                with self._listen_lock:
                    listen_enabled = self._listen_enabled

                if not listen_enabled:
                    # if self.verbose:
                    #     syslog.info("Voice listen runner: listening disabled")
                    continue

                output, info = self.processor.process(audio)

                if (
                    self._recognize_stack == 0
                    and self._rolling_matcher.hasCommands()
                    and output is not None
                ):
                    self.recognizer.add_audio(
                        output,
                        info["speech_started"],
                        info["speech_ended"],
                    )

                self.audioMonitor.emit(info)

    def getVolume(self, target_name: str = None) -> float:
        if gremlin.util.is_ui_thread():
            return self._get_volume_ui(target_name=target_name)

        # non UI thread
        value = None

        def default_callback(volume: float):
            nonlocal value
            value = volume

        self._get_volume_ui(target_name=target_name, callback=default_callback)

        while value is None:
            time.sleep(0.01)  # Small sleep to prevent high CPU usage in the loop

        return value

    def _get_qmedia_device(self, target_name: str = None):
        """gets the QMediaDevice for the given device, use None for the default device"""
        gremlin.util.assert_ui_thread()

        device = None
        if target_name is not None:
            target_name = target_name.casefold()

            devices = QMediaDevices.audioInputs()
            for dev in devices:
                if target_name in dev.description().lower():
                    device = dev
                    break
        else:
            device = QMediaDevices.defaultAudioInput()

        return device

    def getDefaultDeviceName(self) -> str:
        """gets the name of the default input device (microphone)"""
        gremlin.util.assert_ui_thread()
        default_device = QMediaDevices.defaultAudioInput()
        if default_device is not None:
            return default_device.description()
        return ""

    def _get_volume_ui(self, target_name: str = None, callback: Callable = None) -> float:
        """gets the system volume 0 to 100 for the input device

        :param target_name: The name of the target input device (microphone). If None, the default microphone is used.
        :param update: If True, fetch the current volume from the system; otherwise, return the cached value.
        :return: The system volume level for the input device, ranging from 0 to 100, -1 if the device is not found.

        """
        # must run in UI thread to avoid COM issues
        gremlin.util.assert_ui_thread()

        mic = None
        percent_volume = -1

        mic = self._get_qmedia_device(target_name=target_name)
        if mic is not None:
            audio_input = QAudioInput(mic)
            percent_volume = audio_input.volume() * 100

        if callback:
            callback(percent_volume)
        return percent_volume

    def setVolume(self, percent: float, target_name: str = None):
        """sets the input device volume level"""
        gremlin.util.InvokeUiMethod(self._set_volume_ui, percent, target_name)  # must be on UI thread to avoid COM issues

    def _set_volume_com(self, device_name: str, volume_scalar: float) -> bool:
        """Set the volume of a matching active input device."""

        if not 0.0 <= volume_scalar <= 1.0:
            raise ValueError("volume_scalar must be between 0.0 and 1.0")

        com_initialized = False

        try:
            comtypes.CoInitialize()
            com_initialized = True

            def set_volume() -> bool:
                enumerator = comtypes.CoCreateInstance(
                    CLSID_MMDeviceEnumerator,
                    interface=IMMDeviceEnumerator,
                    clsctx=comtypes.CLSCTX_INPROC_SERVER,
                )

                collection = enumerator.EnumAudioEndpoints(
                    EDataFlow.eCapture.value,
                    DEVICE_STATE.ACTIVE.value,
                )

                target_device = None

                for index in range(collection.GetCount()):
                    device = collection.Item(index)
                    wrapped_device = AudioUtilities.CreateDevice(device)

                    if device_name.casefold() in wrapped_device.FriendlyName.casefold():
                        target_device = device
                        break

                if target_device is None:
                    print(f"Device matching {device_name!r} not found.")
                    return False

                interface = target_device.Activate(
                    IAudioEndpointVolume._iid_,
                    comtypes.CLSCTX_ALL,
                    None,
                )
                endpoint_volume = cast(
                    interface,
                    POINTER(IAudioEndpointVolume),
                )

                endpoint_volume.SetMasterVolumeLevelScalar(volume_scalar, None)
                return True

            result = set_volume()

            # Ensure any cyclic wrapper objects are finalized while COM is active.
            gc.collect()
            return result

        except Exception as exc:
            print(f"An error occurred while setting the volume: {exc}")
            return False

        finally:
            if com_initialized:
                # Ensure any cyclic wrapper objects are finalized while COM is active.
                gc.collect()
                comtypes.CoUninitialize()

    def _set_volume_ui(self, percent: float, target_name: str = None):
        """sets the input device volume level

        :param percent: The desired volume level as a percentage (0 to 100) (clamped if out of range)
        :param target_name: The name of the target input device (microphone). If None, the default microphone is used.

        """
        percent = max(0, min(100, percent))  # Clamp the value between 0 and 100

        if target_name is None:
            target_name = self.getDefaultDeviceName()
        target_name = target_name.casefold()
        level_scalar = percent / 100

        syslog.info(f"VOICE: Setting microphone volume to {percent}% for target device: {target_name}")

        self._set_volume_com(target_name, level_scalar)

        # microphone = None
        # devices = AudioUtilities.GetAllDevices()
        # for device in devices:
        #     if device.id.startswith("{0.0.1.00000000}"):  # input device
        #         # if not is_input_device(device):
        #         #     continue
        #         name = device.FriendlyName
        #         if not name:
        #             continue
        #         if target_name in name.casefold():
        #             microphone = device
        #             break

        # if microphone is not None:
        #     interface = microphone._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        #     volume = cast(interface, POINTER(IAudioEndpointVolume))
        #     volume.SetMasterVolumeLevelScalar(level_scalar, None)
        # syslog.info(f"VOICE: Microphone volume set to {percent}%  device: {target_name}")
