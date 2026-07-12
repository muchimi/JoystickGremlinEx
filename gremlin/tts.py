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


"""

import logging
import time
import gremlin.config
import gremlin.event_handler
import gremlin.shared_state
import threading
import gremlin.threading
import gremlin.util as util
import pyttsx3
import gremlin.singleton_decorator
import queue
import gremlin.util

syslog = logging.getLogger("system")


@gremlin.singleton_decorator.SingletonDecorator
class TextToSpeech:
    rate_playback = 100  # default playback rate
    rate_offset_min = 50  # max slow
    rate_offset_max = 300  # max fast

    def __init__(self):
        """Creates a new instance."""
        # syslog = logging.getLogger("system")
        self.valid = False
        el = gremlin.event_handler.EventListener()
        el.tts_change.connect(self._tts_changed)
        el.shutdown.connect(self.end)
        el.profile_start.connect(self.profile_start)
        el.profile_stop.connect(self.profile_stop)

        self._current_rate = 100  # default rate (global)
        self._last_hash = None

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_tts
        self._started = False
        self._tts_thread = None
        self._queue_thread = None
        self._queue = queue.Queue()
        self.valid = config.tts_enabled
        try:
            self.engine = pyttsx3.init()
            self.voices = self.engine.getProperty("voices")
            self.default_voice = next(
                (voice for voice in self.voices if "David Desktop" in voice.name), None
            )

            if verbose:
                syslog.info("TTS voice listing:")
                for voice in self.voices:
                    syslog.info(f"\t{voice.name}  (id: {voice.id})")
                if self.default_voice:
                    syslog.info(
                        f"TTS default voice: {self.default_voice.name}  (id: {self.default_voice.id})"
                    )

            if self.valid:
                self.start()

        except Exception as err:
            syslog.error(f"TTS: unable to initialize TTS: {err}")

    def profile_start(self):
        """called on profile start"""
        self._last_hash = None  # reset prior speech
        self._start_ui()

    def profile_stop(self):
        """called on profile stop"""
        self.stop()

    def _tts_changed(self, enabled: bool):
        gremlin.util.InvokeUiMethod(self._tts_changed_ui, enabled)

    def _tts_changed_ui(self, enabled: bool):
        self.valid = enabled
        if enabled:
            self._start_ui()
        else:
            self._stop_ui()

    def getVoices(self):
        """gets a list of defined voices"""
        if self.valid:
            return self.voices
        return []

    def set_voice(self, voice):
        """sets the voice"""
        gremlin.util.InvokeUiMethod(self._set_voice_ui, voice)

    def _set_voice_ui(self, voice):
        """sets the voice"""
        if not self.valid:
            return
        try:
            self.engine.setProperty("voice", voice.id)
        except Exception:
            # syslog = logging.getLogger("system")
            syslog.warning(f"TTS: unable to select voice {voice.name}")
            if self.default_voice:
                try:
                    self.engine.setProperty("voice", self.default_voice.id)
                    syslog.warning(f"TTS: selecting default voice {voice.name}")
                except Exception as err:
                    syslog.error(f"TTS: unable to activate TTS: {err}")

    def speak(
        self,
        text: str,
        rate: int = 100,
        clear: bool = False,
        override_suppress: bool = False,
    ):
        gremlin.util.InvokeUiMethod(
            self._speak_ui, text, rate, clear, override_suppress
        )  # ensure on UI thread

    def _speak_ui(self, text, rate=100, clear=False, override_suppress: bool = False):
        if not self.valid:
            return
        # syslog = logging.getLogger("system")

        if text:
            config = gremlin.config.Configuration()
            verbose = config.verbose_mode_tts

            if config.tts_suppress_duplicate and not override_suppress:
                h = hash(text)
                if h == self._last_hash:
                    if verbose:
                        syslog.info(f"TTS: SUPRESS duplicate: {text}")
                    return
                self._last_hash = h

            if verbose:
                syslog.info(f"TTS: SPEAK add to queue: {text}")

            if clear or not text:
                # clear on no message.
                self._clear_queue()
            if text:
                self._queue.put(lambda: self._speak(text, rate))

    def _clear_queue(self):
        """clears the queue"""
        while not self._queue.empty():
            self._queue.get()
            self._queue.task_done()

    def _speak(self, text, rate=None):
        """speaks the text"""

        try:
            if text:
                text = self.text_substitution(text)
                if rate is None:
                    rate = self._current_rate
                new_rate = self.rate_playback + int(
                    util.clamp(rate, self.rate_offset_min, self.rate_offset_max)
                )
                self.engine.setProperty("rate", new_rate)
                self.engine.say(text)

        except Exception as err:
            logging.getLogger("system").error(f"Error in TTS: {err}")

    def speak_single(self, text, rate=None, clear=False, threaded=True):
        gremlin.util.InvokeUiMethod(self._speak_single_ui, text, rate, clear, threaded)

    def _speak_single_ui(self, text, rate=None, clear=False, threaded=True):
        if text and self.valid:
            if not self._started:
                self._start_ui()
            # syslog = logging.getLogger("system")
            verbose = gremlin.config.Configuration().verbose_mode_tts
            if verbose:
                syslog.info(f"TTS: SPEAK SINGLE add to queue: {text}")
            if clear:
                self._clear_queue()
            self._queue.put(lambda: self._speak_single_ui(text, rate))

    def _speak_single_ui(self, text, rate=None):
        """speaks the test as a single event (don't use this inside an event loop)"""
        if not self.valid:
            return
        try:
            self.engine.stop()
            text = self.text_substitution(text)
            if rate is None:
                rate = self._current_rate

            new_rate = self.rate_playback + int(
                util.clamp(rate, self.rate_offset_min, self.rate_offset_max)
            )
            self.engine.setProperty("rate", new_rate)
            self.engine.say(text)

            verbose = gremlin.config.Configuration().verbose_mode_tts
            if verbose:
                syslog.info(f"TTS: Engine speech requested: {text}")

            try:
                if not self.engine._inLoop:
                    self.engine.runAndWait()
                    self.engine.stop()
            except Exception:
                pass

        except Exception as err:
            syslog.error(f"Error in TTS: {err}")

    def abort(self):
        gremlin.util.InvokeUiMethod(self._abort_ui)  # ensure on UI thread

    def _abort_ui(self):
        """aborts current speech and resets the queue"""
        self.engine.stop()
        self._clear_queue()

    def stop(self):
        if self._started:
            gremlin.util.InvokeUiMethod(self._stop_ui)  # ensure on UI thread

    def _stop_ui(self):
        """stops any speech"""

        try:
            syslog.info("TTS: stop")
            if self._queue_thread and self._queue_thread.is_alive():
                self._queue_thread.stop()
                self._queue_thread.join()
            self._queue_thread = None

            if self._tts_thread and self._tts_thread.is_alive():
                self._tts_thread.stop()
                self._tts_thread.join()
            self._tts_thread = None

            self.engine.stop()

            self._clear_queue()
            self._started = False

        except Exception as err:
            syslog.error(f"Error in TTS: {err}")

    def start(self):
        if not self._started:
            gremlin.util.InvokeUiMethod(self._start_ui)  # ensure on UI thread

    def _start_ui(self):
        """starts the loop"""
        if not self.valid:
            return
        if not self._started:
            syslog.info("TTS: start")
            self._tts_thread = gremlin.threading.AbortableThread(
                target=self._tts_runner
            )
            self._tts_thread.name = "TTS engine"
            self._tts_thread.start()
            self._queue_thread = gremlin.threading.AbortableThread(
                target=self._queue_runner
            )
            self._queue_thread.name = "TTS queue"
            self._queue_thread.start()
            self._started = True

    def _tts_runner(self):
        """runner thread for the TTS engine"""
        if not self.valid:
            return
        threading.current_thread().reset()
        self.engine.startLoop(False)
        try:
            while not self._tts_thread.stopped():
                time.sleep(0.1)
                self.engine.iterate()
        except Exception as err:
            pass # ignore
        finally:
            self.engine.endLoop()

    def _queue_runner(self):
        """processes the speech queue"""
        # syslog = logging.getLogger("system")
        threading.current_thread().reset()
        verbose = gremlin.config.Configuration().verbose_mode_tts
        while not self._queue_thread.stopped():
            if not self._queue.empty():
                functor = self._queue.get()
                if verbose:
                    syslog.info("TTS: POP queue")
                gremlin.util.InvokeUiMethod(functor)
                self._queue.task_done()
            time.sleep(0.05)

        # terminate any remaining queue items
        self._clear_queue()

    def end(self):
        gremlin.util.InvokeUiMethod(self._end_ui)  # ensure on UI thread

    def _end_ui(self):
        """ends the loop"""

        if not self.valid:
            return

        if self._started:
            # syslog = logging.getLogger("system")
            syslog.info("TTS: shutdown")

            self._queue_thread.stop()
            self._queue_thread.join()
            self._queue_thread = None

            self._tts_thread.stop()
            self._tts_thread.join()
            self._tts_thread = None
            try:
                self.engine.stop()
            except Exception:
                pass
            self._started = False

    def set_volume(self, value):
        gremlin.util.InvokeUiMethod(self._set_volume_ui, value)  # ensure on UI thread

    def _set_volume_ui(self, value):
        """Sets the volume anywhere between 0 and 100.

        :param value the new volume value
        """
        if not self.valid:
            return
        volume = int(util.clamp(value, 0, 100))
        self.engine.setProperty(
            "volume", volume / 100
        )  # value is 0 to 1 floating point

    def set_rate(self, value):
        gremlin.util.InvokeUiMethod(self._set_rate_ui, value)  # ensure on UI thread

    def _set_rate_ui(self, value):
        """Sets the speaking speed between -10 and 10.

        Negative values slow speech down while positive values speed
        it up.

        :param value the new speaking rate
        """
        # default is 200 words per minute
        if not self.valid:
            return
        rate = self.rate_playback + int(
            util.clamp(value, self.rate_offset_min, self.rate_offset_max)
        )
        self._current_rate = rate
        self.engine.setProperty("rate", rate)

    def text_substitution(self, text):
        """Returns the provided text after running text substitution on it.

        :param text the text to substitute parts of
        :return original text with parts substituted
        """
        text = text.replace("${current_mode}", gremlin.shared_state.current_mode)
        return text
