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

"""
This module provides convenient access to the Microsoft SAPI text
to speech system.

TTS uses PyTTSx3 which is not thread safe.

m77 update: migrate to the play engine and phrase system to avoid legacy API problems


"""

import os
import logging
import time
import gremlin.config
import gremlin.event_handler
import gremlin.shared_state
import threading
from gremlin.sound import PhraseData
import gremlin.threading
import gremlin.util as util
import pyttsx3
import pythoncom
import gremlin.singleton_decorator
import traceback

# import queue
from gremlin.base_classes import FastQueue
import gremlin.util
from gremlin.sound import Sound, PlaybackOptions, PhraseData
from gremlin.types import PlayMode

syslog = logging.getLogger("system")


@gremlin.singleton_decorator.SingletonDecorator
class TextToSpeech:
    rate_playback = 100  # default playback rate
    rate_offset_min = 50  # max slow
    rate_offset_max = 300  # max fast

    def __init__(self):
        """Creates a new instance."""
        # syslog = logging.getLogger("system")
        gremlin.util.assert_ui_thread()
        self.valid = False
        self.voices = None
        self.default_voice = None
        # el = gremlin.event_handler.EventListener()
        # el.tts_change.connect(self._tts_changed)
        # el.shutdown.connect(self.end)
        # el.profile_start.connect(self.profile_start)
        # el.profile_stop.connect(self.profile_stop)

        self._current_rate = 100  # default rate (global)
        self._current_voice = None  # voice to use
        self._last_hash = None

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_tts
        self._started = False
        self._tts_thread = None
        self._queue_thread = None
        self._queue = FastQueue()  # queue.Queue()
        self._engine_lock = threading.Lock()  # pyttsx3/SAPI5 is not thread-safe; serialize access
        self.valid = config.tts_enabled
        try:
            pythoncom.CoInitialize()
            engine = pyttsx3.init()
            self.voices = engine.getProperty("voices")
            self.default_voice = next((voice for voice in self.voices if "David Desktop" in voice.name), None)

            if verbose:
                syslog.info("TTS voice listing:")
                for voice in self.voices:
                    syslog.info(f"\t{voice.name}  (id: {voice.id})")
                if self.default_voice:
                    syslog.info(f"TTS default voice: {self.default_voice.name}  (id: {self.default_voice.id})")

            engine.stop()
            # if self.valid:
            #     self.start()

        except Exception as err:
            syslog.error(f"TTS: unable to initialize TTS: {err}")
        finally:
            engine.stop()
            pythoncom.CoUninitialize()

    def profile_start(self):
        """called on profile start"""
        self._last_hash = None  # reset prior speech
        self.start()

    def profile_stop(self):
        """called on profile stop"""
        self.stop()

    def _tts_changed(self, enabled: bool):
        gremlin.util.InvokeUiMethod(self._tts_changed_ui, enabled)

    def _tts_changed_ui(self, enabled: bool):
        self.valid = enabled
        if enabled:
            self.start()
        else:
            self.stop()

    def getVoices(self):
        """gets a list of defined voices"""

        if self.valid and self.voices:
            return self.voices
        return []

    def set_voice(self, voice):
        pass



    def speak(
        self,
        text: str,
        rate: int = 100,
        clear: bool = False,
        override_suppress: bool = False,
    ):
        # m77T13 - use the play engine to speak the text + cache
        sound = Sound()
        sound.playPyTTS(text, voice=self._current_voice.name if self._current_voice else self.default_voice.name, rate=rate, timed_random=self._timed_random)



    def text_substitution(self, text):
        """Returns the provided text after running text substitution on it.

        :param text the text to substitute parts of
        :return original text with parts substituted
        """
        text = text.replace("${current_mode}", gremlin.shared_state.current_mode)
        return text

    def generateActionWav(self, phrase: PhraseData, voice: str = None, rate: float = 1.0, pitch: float = 0.0, volume: float = 100) -> str:

        self._result = None
        gremlin.util.InvokeUiMethod(self._generate_action_wav_ui, phrase, voice, rate, pitch, volume)
        while self._result is None:
            time.sleep(0.01)  # wait for the UI thread to finish
        return self._result

    def _generate_action_wav_ui(self, phrase: PhraseData, voice: str = None, rate: float = 1.0, pitch: float = 0.0, volume: float = 100) -> str:
        """generates a wav file from the current action"""
        gremlin.util.assert_ui_thread()
        tts_file = phrase.getSoundFile()
        rate = phrase.rate  # floating point value 1.0 is normal
        speaker = voice if voice else phrase.speaker
        if not speaker:
            if not self.default_voice:
                syslog.error(f"Voice: [{voice}] not found and no default voice was found - unable to proceed with voice generation")
                return False

            speaker = self.default_voice.name

        text = phrase.text
        if not text:
            syslog.error("TTS: No text provided for voice generation")
            return False
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_sound or config.verbose_mode_tts
        try:
            pythoncom.CoInitialize()
            engine = pyttsx3.init(debug=True)
            try:
                voices = engine.getProperty("voices")
                index = next((i for i, v in enumerate(voices) if v.name.casefold() == speaker.casefold()), 0)

                engine.setProperty("rate", rate)
                engine.setProperty("voice", voices[index].id)

                # ensure the folder exists
                os.makedirs(os.path.dirname(tts_file), exist_ok=True)
                if os.path.isfile(tts_file):
                    # file cannot exist before being created
                    os.remove(tts_file)

                engine.save_to_file(text, tts_file)  # generates wav files by itself

                # m77 - run manual loop or it will kill itself
                engine.startLoop(False)
                while engine.isBusy():
                    time.sleep(0.01)
                    engine.iterate()
                engine.endLoop()
            except Exception as e:
                syslog.error(f"TTS: Error during TTS generation: {e}")
                syslog.error(traceback.format_exc())
            finally:
                engine = None
                pythoncom.CoUninitialize()

            self._result = os.path.isfile(tts_file)
            if not self._result:
                syslog.error(f"TTS: Failed to generate wav file: {tts_file}")
            else:
                if verbose:
                    syslog.info(f"TTS: Successfully generated wav file: {tts_file}")
            return self._result
        except Exception as e:
            syslog.error(f"TTS: Error generating wav for action: {e}")

        return self._result
