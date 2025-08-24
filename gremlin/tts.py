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

"""
This module provides convenient access to the Microsoft SAPI text
to speech system.
"""

import logging
import time
import gremlin.config
import gremlin.event_handler
import gremlin.shared_state
import threading
import gremlin.threading
import multiprocessing
from . import event_handler, util
import pyttsx3
import gremlin.singleton_decorator
from PySide6 import QtCore

syslog = logging.getLogger("system")

@gremlin.singleton_decorator.SingletonDecorator
class TextToSpeech:

    rate_playback = 100 # default playback rate
    rate_offset_min = 50 # max slow
    rate_offset_max = 300 # max fast

    def __init__(self):
        """Creates a new instance."""
        # syslog = logging.getLogger("system")
        self.valid = False
        el = gremlin.event_handler.EventListener()
        el.tts_change.connect(self._tts_changed)
        el.shutdown.connect(self.end)
        self._lock = threading.Lock()

        self._current_rate  = 100 # default rate (global)

        config = gremlin.config.Configuration()
        verbose = config.verbose

        try:
            self.engine = pyttsx3.init()
            self.voices = self.engine.getProperty('voices')
            self.default_voice = next((voice for voice in self.voices if "David Desktop" in voice.name), None)
            self._started = False
            self.valid = config.tts_enabled
            self._tts_thread = None
            self._queue_thread = None
            self._queue = []

            
            if verbose:
                syslog.info(f"TTS voice listing:")
                for voice in self.voices:
                    syslog.info(f"\t{voice.name}  (id: {voice.id})")
                if self.default_voice:
                    syslog.info(f"TTS default voice: {self.default_voice.name}  (id: {self.default_voice.id})")

            if self.valid:
                self.start()


        except Exception as err:
            syslog.error(f"TTS: unable to initialize TTS: {err}")
                

        
    @QtCore.Slot(bool)
    def _tts_changed(self, enabled : bool):
        self.valid = enabled
        if enabled:
            self.start()
        else:
            self.stop()
        


    def getVoices(self):
        ''' gets a list of defined voices'''
        if self.valid:
            return self.voices  
        return []
    
    def set_voice(self, voice):
        ''' sets the voice'''
        if not self.valid:
            return
        try:
            self.engine.setProperty("voice", voice.id)
        except:
            # syslog = logging.getLogger("system")
            syslog.warning(f"TTS: unable to select voice {voice.name}")
            if self.default_voice:
                try:
                    self.engine.setProperty("voice", self.default_voice.id)
                    syslog.warning(f"TTS: selecting default voice {voice.name}")
                except Exception as err:
                    syslog.error(f"TTS: unable to activate TTS: {err}")


    def speak(self, text, rate = 100, clear = False):     
        if not self.valid:
            return
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose
        if verbose: syslog.info(f"TTS: SPEAK add to queue: {text}")

        self._lock.acquire_lock()
        if clear:
            self._queue.clear()
        self._queue.append(lambda : self._speak(text, rate))
        self._lock.release_lock()

    def _speak(self, text, rate = None):        
        ''' speaks the text'''
        
        try:
            text = self.text_substitution(text)
            if rate is None:
                rate = self._current_rate
            new_rate = self.rate_playback + int(util.clamp(rate, self.rate_offset_min, self.rate_offset_max))
            self.engine.setProperty('rate', new_rate)
            self.engine.say(text)


        except Exception as err:
            logging.getLogger(f"system").error(f"Error in TTS: {err}")

    def speak_single(self, text, rate = None, clear = False, threaded = True):        
        if text and self.valid:
            # syslog = logging.getLogger("system")
            verbose = gremlin.config.Configuration().verbose
            if verbose: syslog.info(f"TTS: SPEAK SINGLE add to queue: {text}")
            self._lock.acquire_lock()
            if clear:
                self._queue.clear()
            self._queue.append(lambda : self._speak_single(text, rate))
            self._lock.release_lock()


    def _speak_single(self, text, rate = None):
        ''' speaks the test as a single event (don't use this inside an event loop)'''
        if not self.valid:
            return
        try:
            self.engine.stop()
            text = self.text_substitution(text)
            if rate is None:
                rate = self._current_rate

            new_rate = self.rate_playback + int(util.clamp(rate, self.rate_offset_min, self.rate_offset_max))
            self.engine.setProperty('rate', new_rate)
            self.engine.say(text)

            try:
                if not self.engine._inLoop:
                    self.engine.runAndWait()
            except:
                pass


        except Exception as err:
            syslog.error(f"Error in TTS: {err}")


    def stop(self):
        ''' stops any speech '''
        if not self._started:
            return
        try:
            syslog.info("TTS: stop")
            self._queue_thread.stop()
            self._queue_thread.join()
            self._tts_thread.stop()
            self._tts_thread.join()
            self.engine.stop()
            self._lock.acquire_lock()
            self._queue.clear()
            self._lock.release_lock()
            self._started = False

        except Exception as err:
            logging.getLogger(f"system").error(f"Error in TTS: {err}")

    def start(self):
        ''' starts the loop '''
        if not self.valid:
            return
        if not self._started:
            syslog.info("TTS: start")
            self._tts_thread = gremlin.threading.AbortableThread(target = self._tts_runner)
            self._tts_thread.name = "TTS engine"
            self._tts_thread.start()
            self._queue_thread = gremlin.threading.AbortableThread(target= self._queue_runner)
            self._queue_thread.name = "TTS queue"
            self._queue_thread.start()
            self._started = True

    def _tts_runner(self):
        ''' runner thread for the TTS engine '''
        if not self.valid:
            return
        threading.current_thread().reset()
        self.engine.startLoop(False)
        while not self._tts_thread.stopped():
            time.sleep(0.05)
            self.engine.iterate()
            
        self.engine.endLoop()


    def _queue_runner(self):
        ''' processes the speech queue '''
        # syslog = logging.getLogger("system")
        threading.current_thread().reset()
        verbose = gremlin.config.Configuration().verbose
        while not self._queue_thread.stopped():
            if self._queue:
                self._lock.acquire_lock()
                functor = self._queue.pop(0)
                self._lock.release_lock()
                if verbose: syslog.info("TTS: POP queue")
                functor()
            time.sleep(0.05)

        # terminate any remaining queue items
        self._queue.clear()


    @QtCore.Slot()
    def end(self):
        ''' ends the loop '''
        
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
            except:
                pass
            self._started = False
        

    def set_volume(self, value):
        """Sets the volume anywhere between 0 and 100.

        :param value the new volume value
        """
        if not self.valid:
            return
        volume = int(util.clamp(value, 0, 100))
        self.engine.setProperty('volume', volume / 100) # value is 0 to 1 floating point

    def set_rate(self, value):
        """Sets the speaking speed between -10 and 10.

        Negative values slow speech down while positive values speed
        it up.

        :param value the new speaking rate
        """
        # default is 200 words per minute
        if not self.valid:
            return
        rate = self.rate_playback + int(util.clamp(value, self.rate_offset_min, self.rate_offset_max))
        self._current_rate = rate
        self.engine.setProperty('rate', rate )
        


    def text_substitution(self, text):
        """Returns the provided text after running text substitution on it.

        :param text the text to substitute parts of
        :return original text with parts substituted
        """
        text = text.replace("${current_mode}", gremlin.shared_state.current_mode)
        return text
