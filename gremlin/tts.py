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
from . import event_handler, util
import pyttsx3
import gremlin.singleton_decorator
from PySide6 import QtCore


@gremlin.singleton_decorator.SingletonDecorator
class TextToSpeech:

    rate_playback = 200 # default playback rate
    rate_offset_min = -175 # max slow
    rate_offset_max = 100 # max fast

    def __init__(self):
        """Creates a new instance."""
        syslog = logging.getLogger("system")
        self.valid = False
        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self.end)

        try:
            self.engine = pyttsx3.init()
            self.voices = self.engine.getProperty('voices')
            self.default_voice = next((voice for voice in self.voices if "David Desktop" in voice.name), None)
            self._started = False
            self.valid = True
            self._tts_thread = None
            verbose = gremlin.config.Configuration().verbose
            if verbose:
                syslog.info(f"TTS voice listing:")
                for voice in self.voices:
                    syslog.info(f"\t{voice.name}  (id: {voice.id})")
                if self.default_voice:
                    syslog.info(f"TTS default voice: {self.default_voice.name}  (id: {self.default_voice.id})")
        except Exception as err:
            syslog.error(f"TTS: unable to initialize TTS: {err}")
                



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
            syslog = logging.getLogger("system")
            syslog.warning(f"TTS: unable to select voice {voice.name}")
            if self.default_voice:
                try:
                    self.engine.setProperty("voice", self.default_voice.id)
                    syslog.warning(f"TTS: selecting default voice {voice.name}")
                except Exception as err:
                    syslog.error(f"TTS: unable to activate TTS: {err}")


    def speak(self, text, threaded = True):        
        if threaded:
            t = threading.Thread(target= self._speak, args=[text])
            t.start()
        else:
            self._speak(text)


    def _speak(self, text):        
        ''' speaks the text'''
        if not self.valid:
            return
        try:
            text = self.text_substitution(text)
            self.engine.say(text)
            
        except Exception as err:
            logging.getLogger(f"system").error(f"Error in TTS: {err}")

    def speak_single(self, text, threaded = True):        
        if threaded:
            t = threading.Thread(target= self._speak_single, args=[text])
            t.start()
        else:
            self._speak_single(text)

    def _speak_single(self, text):
        ''' speaks the test as a single event (don't use this inside an event loop)'''
        if not self.valid:
            return
        try:
            text = self.text_substitution(text)
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception as err:
            logging.getLogger(f"system").error(f"Error in TTS: {err}")


    def stop(self):
        ''' stops any speech '''
        if not self.valid:
            return
        try:
            self.engine.stop()
        except Exception as err:
            logging.getLogger(f"system").error(f"Error in TTS: {err}")

    def start(self):
        ''' starts the loop '''
        if not self.valid:
            return
        if not self._started:
            self._tts_thread = gremlin.threading.AbortableThread(target = self._tts_runner)
            self._tts_thread.start()
            self._started = True
            
    def _tts_runner(self):
        ''' runner thread for the TTS engine '''
        if not self.valid:
            return
        self.engine.startLoop(False)
        while not self._tts_thread.stopped():
            time.sleep(0.1)
            self.engine.iterate()
            
        self.engine.endLoop()


    @QtCore.Slot()
    def end(self):
        ''' ends the loop '''
        
        if not self.valid:
            return
        if self._started:
            syslog = logging.getLogger("system")
            syslog.info("TTS: shutdown")
            self._tts_thread.stop()
            self._tts_thread.join()
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
        self.engine.setProperty('rate', rate )
        


    def text_substitution(self, text):
        """Returns the provided text after running text substitution on it.

        :param text the text to substitute parts of
        :return original text with parts substituted
        """
        text = text.replace("${current_mode}", gremlin.shared_state.runtime_mode)
        return text
