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
import os
import html
import sys
from lxml import etree
from PySide6 import QtCore, QtMultimedia, QtWidgets
import gremlin.util
from gremlin.util import hashString, safe_format, safe_read, TimedRandomInt
import gremlin.event_handler
import asyncio
import edge_tts
from typing import Any, Dict, List
import io
import os
import shutil
import gremlin.config
import importlib.util
import json
import random
import gremlin.ui.ui_common
import threading
import pycountry

import logging

import gremlin.singleton_decorator

# import queue
from gremlin.base_classes import FastQueue
import enum
import time
from psygnal import Signal
from gremlin.types import PlaybackMode, PlayMode


syslog = logging.getLogger("system")

USE_SD = True  # use sound device for playback
USE_QT = False  # use QT for playback
USE_PG = False  # use pygame for playback
PHRASE_VERSION = 1

if USE_PG:
    import pygame


if USE_SD:
    import sounddevice as sd  # for sound playback
    import soundfile as sf  # for reading sound files as numpy data
    import numpy as np  # for sound device library
    import concurrent.futures  # for thread pool of concurrent playback
    import pyrubberband as pyrb  # for sound sample rate modification
    from pydub import AudioSegment  # for audio format conversion

    from scipy import signal  # for audio resampling if needed


class SoundAction(enum.Enum):
    Play = 1  # play a sound key using the options previously selected
    ChangeDevice = 2  # change the audio output device
    SetVolume = 3  # set teh volume on a sound key
    Stop = 4  # stop playback


class PlaybackOptions:
    """holds sound playback options"""

    def __init__(
        self,
        key: Any,
        sound_file: str = None,
        device: str = None,
        loops: int = 1,
        volume: float = None,
        playback_ms: int = 0,
        fadein_ms: int = 0,
        fadeout_ms: int = 0,
        stop_previous: bool = False,
        rate: float = None,
        timed_random: TimedRandomInt = TimedRandomInt(),
        blocking: bool = False,
    ):
        """playback options

        :param key: the sound file key as registered with the sound module (getSoundKey())
        :param loops: count of playback loops.  0 means no playback.
        :param volume: volume 0 to 1, leave None for default volume
        :param playback_ms: time for the playback in milliseconds, 0 to disable.  If provided, plays the sound only for the specified number of milliseconds.
        :param fadein_ms: time in milliseconds for the time for the sound to fade in - if the sound is too short, it may never reach max volume
        :param fadeout_ms: time in milliseconds for the time for the sound to fade out
        """
        self.key = key  # this is a GUID for PG mode, and the file name for SD mode
        self.sound_file = sound_file  # path to wave file to play
        self.device: str = device  # playback device - if not set - default playback is used
        if USE_PG:
            self.loops = loops - 1 if loops > 0 else 0  # sounds plays once, loops are extra repeats
        elif USE_SD:
            self.loops = loops
        self.volume = volume
        self.playback_ms = playback_ms  # this only works for PG mode
        self.fadein_ms = fadein_ms  # this only works for PG mode
        self.fadeout_ms = fadeout_ms  # this only works for PG mode
        self.stop_previous = stop_previous
        self.rate = rate  # playback rate (1.0 = normal)
        self.blocking = blocking  # whether playback should block until finished


class SoundEvent:
    """single commands for the queue"""

    def __init__(self, action: SoundAction, key: str = None, data=None):
        self.key = key
        self.data = data
        self.action = action

    @staticmethod
    def PlayAction(
        key: Any,
        sound_file: str,
        device: str,
        loops: int = 1,
        volume: float = None,
        playback_ms: int = 0,
        fadein_ms: int = 0,
        fadeout_ms: int = 0,
        stop_previous: bool = False,
        rate: float = 1.0,
        timed_random: TimedRandomInt = TimedRandomInt(),
        blocking: bool = False,
    ):
        data = PlaybackOptions(
            key, sound_file, device, loops, volume, playback_ms, fadein_ms, fadeout_ms, stop_previous, rate, timed_random=timed_random, blocking=blocking
        )
        return SoundEvent(action=SoundAction.Play, key=key, data=data)

    @staticmethod
    def ChangeDeviceAction(device_name: str):
        return SoundEvent(action=SoundAction.ChangeDevice, data=device_name)

    @staticmethod
    def SetVolumeAction(key: str, volume: int):
        return SoundEvent(action=SoundAction.SetVolume, key=key, data=volume / 100)

    @staticmethod
    def StopAction():
        return SoundEvent(action=SoundAction.Stop)


class PhraseData:
    """holds data for a phrase to be spoken
    tracks single text and playback parameters and associated found files on disk. and tracks a unique key for the text that can be persisted for later re-use after generation
    """

    def __init__(
        self,
        text: str,
        engine: PlayMode = None,
        voice: str = None,
        rate: float = 1.0,
        pitch: int = 0,
        volume: float = 1.0,
        sound_file: str = None,
        temporary: bool = False,
        generated: bool = True,
    ):
        """creates an instance
        :param text: the text of the phrase
        :param voice: the voice to use for TTS
        :param rate: the rate of speech
        :param pitch: the pitch of the voice
        :param volume: the volume of the playback
        :param sound_file: the path to the sound file
        :param temporary: whether the phrase is temporary
        :param generated: whether the sound is generated or static
        """
        self._id = gremlin.util.get_guid()  # unique ID of this object
        if text:
            assert "|" not in text, "multitext not supported in PhraseData text"
        self._id = gremlin.util.get_guid()  # unique ID of this phrase
        self._engine = engine
        self._text = text
        self._voice = voice
        self._rate = rate
        self._pitch = pitch
        self._volume = volume
        if sound_file:
            assert text is None or text == "", "Static sound files should not have associated text"

        self._sound_file = sound_file  # partial sound file from the sounds folder
        self._temporary = temporary
        self._key = None
        self._generated = generated
        self._version = PHRASE_VERSION
        self._update_key()

    @property
    def id(self) -> str:
        return self._id

    def setId(self, value: str):
        self._id = value

    @property
    def generated(self) -> bool:
        return self._generated

    @generated.setter
    def generated(self, value: bool):
        self._generated = value

    @property
    def temporary(self) -> bool:
        return self._temporary

    @temporary.setter
    def temporary(self, value: bool):
        self._temporary = value

    @property
    def version(self) -> int:
        return self._version

    def getSoundFile(self) -> str:
        return self._sound_file

    @property
    def sound_file(self) -> str:
        return self._sound_file

    @sound_file.setter
    def sound_file(self, value: str):
        # strip the profile sounds folders
        self._sound_file = value

    def sound_file_stub(self) -> str:
        value = self._sound_file
        if value:
            pm = PhraseDataManager()
            folder = pm.getSoundFolder() + "\\"  # include trailing \
            value = value.casefold()
            if value.startswith(folder):
                value = value[len(folder) :]
        return value

    def sound_file_full_path(self, sound_file_stub: str = None) -> str:
        value = sound_file_stub
        if value:
            value = value.casefold()
            pm = PhraseDataManager()
            folder = pm.getSoundFolder().casefold()
            if not value.startswith(folder):
                value = os.path.join(folder, value)
            assert value.startswith(folder), f"Sound file [{value}] is not in the expected folder [{folder}]"
        return value

    def _update_key(self):
        if self._engine:
            hash_string = f"{self._version}{self._text}{self._engine.name}{self._voice}{self._rate:0.3f}{self._pitch}{self._volume:0.3f}"
        else:
            hash_string = f"{self._version}{self._text}{self._voice}{self._rate:0.3f}{self._pitch}{self._volume:0.3f}"
        self._key = hashString(hash_string)

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value
        self._update_key()

    @property
    def engine(self) -> PlayMode:
        return self._engine

    @engine.setter
    def engine(self, value: PlayMode):
        self._engine = value
        self._update_key()

    @property
    def voice(self) -> str:
        return self._voice

    @voice.setter
    def voice(self, value: str):
        self._voice = value
        self._update_key()

    @property
    def rate(self) -> float:
        return self._rate

    @rate.setter
    def rate(self, value: float):
        self._rate = value
        self._update_key()

    @property
    def pitch(self) -> int:
        return self._pitch

    @pitch.setter
    def pitch(self, value: int):
        self._pitch = value
        self._update_key()

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value
        self._update_key()

    @property
    def key(self) -> str:
        if self._key is None:
            self._update_key()
        return self._key

    def to_xml(self) -> etree.Element:
        """stores phrase data to an XML element"""
        node = etree.Element("phrase")
        node.set("text", html.escape(self.text))
        if self.engine is not None:
            node.set("engine", self.engine.name)
        if self.voice is not None:
            voice_value = self.voice if isinstance(self.voice, str) else getattr(self.voice, "name", str(self.voice))
            node.set("voice", voice_value)
        node.set("rate", safe_format(self.rate, float))
        node.set("pitch", safe_format(self.pitch, int))
        node.set("volume", safe_format(self.volume, float))
        node.set("guid", self.id)
        node.set("key", self.key)
        node.set("version", safe_format(self._version, int))
        return node

    def from_xml(self, node: etree.Element) -> "PhraseData":
        """reads phrase data from an XML element"""
        self._text = html.unescape(node.get("text", ""))
        self._voice = node.get("voice", None)
        self._rate = safe_read(node, "rate", float, 1.0)
        self._pitch = safe_read(node, "pitch", int, 0)
        self._volume = safe_read(node, "volume", float, 1.0)
        self._temporary = False  # persisted files are, by definition, not temporary
        self._version = safe_read(node, "version", int, 0)
        engine = safe_read(node, "engine", str, None)
        if engine:
            self._engine = PlayMode[engine]
        if "guid" in node.attrib:
            self._id = node.get("guid")
        self._sound_file = None  # force a reset
        self._update_key()

    def __repr__(self):
        return f"PhraseData(id=[{self._id}], version: [{self._version}]text=[{self._text}], engine=[{self._engine.name if self._engine else 'n/a'}], voice=[{self._voice}], rate=[{self._rate}], pitch=[{self._pitch}], volume=[{self._volume}], sound_file=[{self._sound_file}], temporary=[{self._temporary}], generated=[{self._generated}])"

    def __str__(self):
        return self.__repr__()


@gremlin.singleton_decorator.SingletonDecorator
class PhraseDataManager:
    """handles persistence of phrases to disk for generated audio"""

    def __init__(self):
        self._lock = threading.RLock()
        self.phrases = {}  # maps phrase keys to PhraseData objects - keyed by key
        self._sound_map = {}  # map of phrase keys to sound file paths
        self._sound_folder = os.path.join(gremlin.util.userprofile_path(), "sounds", "managed")
        if not gremlin.util.create_folder(self._sound_folder):
            syslog.error(f"Unable to create sound file repository :{self._sound_folder}")
            self._sound_folder = gremlin.util.userprofile_path()
        self._config_file = os.path.join(self._sound_folder, "phrases.xml")
        syslog.info(f"AUDIO: found sound folder at [{gremlin.util.toUrl(self._sound_folder)}]")

        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self._handle_shutdown)
        el.profile_loaded.connect(self._handle_profile_changed)

    def _handle_profile_changed(self):
        """handle profile changed event"""
        self.readConfig()  # update the config for the new profile

    def getPhraseDataById(self, id: str) -> PhraseData:
        with self._lock:
            for phrase in self.phrases.values():
                if phrase.id == id:
                    return phrase
        return None

    def getSoundFolder(self) -> str:
        """gets a profile specific sound folder tied to the profile ID"""
        return self._sound_folder

    def _handle_shutdown(self):
        """shutdown event - save the config"""
        self.writeConfig()
        self.purgeData()  # remove any non tracked files

    def readConfig(self):
        with self._lock:
            self.phrases.clear()
            self._sound_map.clear()
        if not os.path.exists(self._config_file):
            # no saved data
            return
        tree = etree.parse(self._config_file)
        root = tree.getroot()
        self.from_xml(root)

    def writeConfig(self):
        tree = etree.ElementTree(self.to_xml())
        tree.write(self._config_file, encoding="utf-8", xml_declaration=True, pretty_print=True)
        syslog.info(f"Phrases: save configuration [{gremlin.util.toUrl(self._config_file)}]")

    def getPhraseDataByKey(self, key: str) -> PhraseData:
        """gets cached phrase data by key, None if not found"""
        with self._lock:
            return self.phrases.get(key, None)

    def ensureSoundFile(self, phrase: PhraseData):
        """ensures the phrase has a sound file associated with it"""
        with self._lock:
            if phrase:
                if phrase.text:
                    # GUID based sound file
                    verbose = gremlin.config.Configuration().verbose_mode_tts
                    sound_file = phrase.sound_file
                    if not sound_file:
                        # create a unique file for this phrase
                        # file_name = f"{phrase.key}.wav"
                        file_name = f"{phrase.id}.wav"
                        sound_file = os.path.join(self.getSoundFolder(), file_name)
                        if verbose:
                            syslog.info(f"Phrase: update sound file: {phrase}")
                        phrase.sound_file = sound_file
                    key = phrase.key
                    if key not in self._sound_map:
                        self._sound_map[key] = sound_file

                if __debug__:
                    for k, v in self._sound_map.items():
                        if v == sound_file and k != key:
                            conflict_phrase = self.phrases[k]
                            assert False, f"Sound file conflict: {sound_file} is already associated with key {k} (phrase text: [{conflict_phrase.text}])"

                return sound_file
        return None

    def purgeData(self):
        """remove all wav files that are not tracked by this manager - if the manager is empty, all files will be removed"""
        all_files = set(gremlin.util.find_files(self._sound_folder, source_pattern="*.wav"))
        managed_files = set()
        with self._lock:
            for phrase in self.phrases.values():
                sound_file = phrase.sound_file
                if phrase.sound_file and os.path.isfile(sound_file):
                    managed_files.add(phrase.sound_file.casefold())

        remove_files = [f for f in all_files if f not in managed_files]

        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_sound or config.verbose_mode_tts

        if verbose:
            syslog.info(f"Audio cache purge: folder [{gremlin.util.toUrl(self._sound_folder)}]")
            managed_files = sorted(managed_files)
            syslog.info(f"------------------ managed files ----------------- [{len(managed_files)}]")
            for file in managed_files:
                syslog.info(f"{gremlin.util.toUrl(file)} {file}")

            all_files = sorted(all_files)
            syslog.info(f"------------------ all files ----------------- [{len(all_files)}]")
            for file in all_files:
                syslog.info(f"{gremlin.util.toUrl(file)} {file}")

            remove_files = sorted(remove_files)
            syslog.info(f"------------------ to remove ----------------- [{len(remove_files)}]")
            for file in remove_files:
                syslog.info(f"{gremlin.util.toUrl(file)} {file}")

        for file in remove_files:
            try:
                os.remove(file)
            except Exception as ex:
                syslog.error(f"Unable to remove unmanaged sound file: {file} - {str(ex)}")

    def add_phrase(self, phrase: PhraseData):
        """adds a phrase to the manager and returns it"""
        with self._lock:
            key = phrase.key
            if key and key not in self.phrases:
                self.ensureSoundFile(phrase)  # create a sound file reference if needed
                self.phrases[key] = phrase
            return self.phrases[key]  # return the existing phrase to re-use

    def getSoundFile(self, key: str) -> str:
        """gets the sound file associated with a phrase key, None if not found"""
        with self._lock:
            if key in self._sound_map:
                return self._sound_map[key]
            if key in self.phrases:
                phrase = self.phrases[key]
                self.ensureSoundFile(phrase)
                return self._sound_map[key]
            return None

    def get_phrase(self, key: str) -> PhraseData:
        """gets a phrase by its key, None if not found"""
        with self._lock:
            return self.phrases.get(key, None)

    def remove_phrase(self, key: str, clear_file: bool = False):
        with self._lock:
            if key in self.phrases:
                if clear_file:
                    phrase = self.phrases[key]
                    if phrase.sound_file and os.path.isfile(phrase.sound_file_full_path()):
                        try:
                            os.remove(phrase.sound_file_full_path())
                        except Exception as ex:
                            syslog.error(f"Unable to remove sound file: {phrase.sound_file_full_path()} - {str(ex)}")
                if key in self._sound_map:
                    del self._sound_map[key]
                del self.phrases[key]

    def to_xml(self) -> etree.Element:
        """stores all phrase data to an XML element"""
        node = etree.Element("phrases")
        with self._lock:
            for phrase in self.phrases.values():
                if phrase.temporary or not phrase.generated:
                    # exclude temporary or static files
                    continue
                node.append(phrase.to_xml())
        return node

    def from_xml(self, node: etree.Element):
        """reads all phrase data from an XML element"""
        with self._lock:
            self.phrases.clear()
            self._sound_map.clear()
            for phrase_node in node.findall("phrase"):
                phrase = PhraseData(text="", engine=None)
                phrase.from_xml(phrase_node)
                if phrase.version != PHRASE_VERSION:
                    # skip phrases with a different version
                    continue
                if not phrase.engine:
                    # require an engine
                    continue
                self.add_phrase(phrase)


@gremlin.singleton_decorator.SingletonDecorator
class Sound:
    """wrapper class to play sounds via pygame and QT multimedia"""

    def __init__(self):
        self._state_lock = threading.RLock()
        self._tasks_lock = threading.RLock()

        # If running in a PyInstaller bundle, add the temporary folder to the PATH
        if hasattr(sys, "_MEIPASS"):
            os.environ["PATH"] = sys._MEIPASS + os.pathsep + os.environ["PATH"]

        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self._handle_shutdown)

        self._has_rubberband = False
        spec = importlib.util.find_spec("pyrubberband")
        self._has_rubberband = spec is not None
        self._ffmpeg_exe = None
        self._sound_files = []  # list of sound files for multiple audio playback
        self._playback_device_name = None
        self._last_phrase_key = None
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_tts or config.verbose_mode_sound

        if USE_SD:
            # use sound device library
            self.device_map = {}
            self.device_name_to_id_map = {}
            self.device_sample_rate_map = {}
            self.running_data = {}  # data for running audio streams
            self._playback_enabled = True  # enable playback
            self._sound_tasks = []  # tracks sound tasks
            self._last_phrase = None

            device_list = sd.query_devices()

            for device in device_list:
                if device["max_output_channels"] > 0:
                    name = device["name"]
                    index = device["index"]
                    api_id = device["hostapi"]
                    api = sd.query_hostapis(device["hostapi"])
                    api_name = api["name"]
                    samplerate = device["default_samplerate"]

                    if verbose:
                        syslog.info(f"API: [{name}] [{api_name}] id: [{api_id}] sample rate: [{samplerate}] ")
                    if api_name == "Windows WASAPI":
                        # only use wasapi as that has the lowest latency
                        # other choices are 'MME'
                        # 'Windows DirectSound'
                        self.device_map[index] = name
                        self.device_name_to_id_map[name] = index
                        self.device_sample_rate_map[index] = samplerate

            # get the default device
            device = sd.query_devices(kind="output")
            name = device["name"]
            if name not in self.device_name_to_id_map:
                # different API - match by starting name
                for device_name in self.device_name_to_id_map:
                    if device_name.startswith(name):
                        name = device_name
                        break

            self._playback_device_name = name

            self.pool = concurrent.futures.ThreadPoolExecutor()  # supports mutliple concurrent audio threads

        else:
            # list of devices from QT multimedia
            devices = QtMultimedia.QMediaDevices.audioOutputs()
            self.device_map = {index: device for index, device in enumerate(devices)}
            # flip the device map
            self.device_name_to_id_map = {id: name for id, name in self.device_map.items()}

        self.pm = PhraseDataManager()

        self.sound_map = {}  # holds sound objects by key (guid -> sound object)
        self.sound_file_map = {}  # maps files to the sound key
        self.sound_volume_map = {}  # holds the sound volume for each key - if not present used the default volume
        self.sound_audio_file_map = {}  # maps key to the sound file on disk (full path)
        self._audio_device = None
        self._event_queue = FastQueue()  # queue.Queue()  # sound queue - holds SoundCommand objects
        self._thread = None  # sound thread
        self._is_running = False  # true if the queue is running
        self._is_paused = False  # true if queue processing is paused
        self._next_key = 0  # next key to use for each registered sound

        if USE_PG:
            pygame.init()
            pygame.mixer.init()

        self._temporary_files = []  # list of temp files created
        self._sound_folder = self.pm.getSoundFolder()

        # read the configuration
        el.shutdown.connect(self._handle_shutdown)

    @property
    def soundFolder(self) -> str:
        """gets the base sound folder"""
        return self.pm.getSoundFolder()

    def getSoundFolder(self) -> str:
        """gets a profile specific sound folder tied to the profile ID"""
        return self.pm.getSoundFolder()

    def getSoundFile(self, key: str) -> str:
        """gets the sound file associated with a phrase key, None if not found"""
        return self.pm.getSoundFile(key)

    def start(self):
        """starts the sound queue"""
        with self._state_lock:
            if not self._is_running:
                self._is_running = True
                self._thread = threading.Thread(target=self._queue_runner)
                self._thread.name = "Sound Runner"
                self._thread.start()
                verbose = gremlin.config.Configuration().verbose_mode_sound
                if verbose:
                    syslog.info("SOUND: starting engine")

    def stop(self):
        """stops the sound queue"""
        thread = None
        with self._state_lock:
            if self._is_running:
                self._is_running = False
                thread = self._thread

        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join()

        with self._state_lock:
            self._thread = None
            verbose = gremlin.config.Configuration().verbose_mode_sound
            if verbose:
                syslog.info("SOUND: engine shutdown")

    def ensureStarted(self) -> bool:
        """makes sure the mixer is started - returns true if initialized"""
        self.start()
        if USE_PG:
            if not pygame.mixer.get_init():
                try:
                    if not self._playback_device_name:
                        syslog.error("SOUND: Unable to initialize sound: device not selected.")
                        return False

                    pygame.mixer.pre_init(self._playback_device_name)
                    pygame.mixer.init()
                except Exception as ex:
                    syslog.error(f"SOUND: Unable to initialize sound: {str(ex)}")
                    return False
        return True

    def _handle_shutdown(self):
        self.stop()  # stop the runner
        self.soundStop()
        self.device_map.clear()
        self.device_name_to_id_map.clear()
        if USE_PG:
            pygame.quit()

        # temporary file cleanup
        for temp_file in self._temporary_files:
            try:
                if os.path.isfile(temp_file):
                    os.remove(temp_file)
            except Exception as ex:
                syslog.error(f"Unable to remove temporary sound file {temp_file}: {str(ex)}")
        self._temporary_files.clear()

    @property
    def audio_device(self) -> str:
        return self._audio_device

    @audio_device.setter
    def audio_device(self, name: str):
        index = self.findDeviceIndex(name)
        init_mixer = False
        if index is None:
            # no longer valid, switch to the new default device
            self.device = self.getDefaultAudioDevice()
            if self.device:
                name = self.device.description()
            else:
                name = None
            self._audio_device = name
            init_mixer = True
        else:
            if self._audio_device != name:
                # changed ?
                self.device = self.device_map[index]
                self._audio_device = name
                init_mixer = True

        if init_mixer:
            self.setPlaybackDevice(name)

    def findDevice(self, index: int):
        if index in self.device_map:
            return self.device_map[index]

    def findDeviceByDescription(self, description: str):
        """gets a device by description (name)"""
        device = next((d for d in self.device_map.values() if d.description() == description), None)
        return device

    def findDeviceIndex(self, name: str):
        """gets the device index for a specific device name"""
        if name in self.device_name_to_id_map:
            return self.device_name_to_id_map[name]
        return None

    def getAudioDevice(self):
        """gets the audio device to play from"""

        default_audio_device = self.getDefaultAudioDevice()

        if self.audio_device:
            device = next((d for d in self.device_map.values() if d.description() == self.audio_device), default_audio_device)
        else:
            device = default_audio_device
        return device

    def getDefaultAudioDevice(self) -> str:
        if USE_SD:
            return sd.default.device

        return QtMultimedia.QMediaDevices.defaultAudioOutput()

    def getDefaultAudioDeviceIndex(self):
        index = next((i for i, d in self.device_map.items() if d.isDefault()), None)
        return index

    def getAudioDeviceIndex(self):
        """gets the index of the selected device"""
        if not self.audio_device:
            device = self.getDefaultAudioDevice()
            self.audio_device = device.description()
        index = next((i for i, d in self.device_map.items() if d.description() == self.audio_device), None)
        return index

    def setPlaybackDevice(self, name: str):
        """changes the playback device"""
        if self._playback_device_name != name:
            if USE_PG:
                if pygame.mixer.get_init():
                    # stop the mixer so we can change the device
                    pygame.mixer.stop()
                    pygame.mixer.quit()

                pygame.mixer.pre_init(devicename=name)
                pygame.mixer.init()

            if USE_SD:
                sd.default.device = name

            self._playback_device_name = name

    def playbackDevice(self) -> str:
        return self._playback_device_name

    def setDefaultPlaybackDevice(self):
        """sets the playback device to system default"""
        device = self.getDefaultAudioDevice()
        if USE_PG:
            self.setPlaybackDevice(device.description())

    def soundStart(self):
        # reset the mixer
        if USE_PG:
            self.soundStop()
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        elif USE_SD:
            with self._tasks_lock:
                self._playback_enabled = True

    def soundStop(self):
        """terminate any active playbacks"""
        if USE_PG:
            if pygame.mixer.get_init():
                pygame.mixer.stop()  # stop playing whatever is being played now
                pygame.mixer.quit()  # we will re-init the mixer later
        elif USE_SD:
            # terminate the thread pools
            with self._tasks_lock:
                self._playback_enabled = False  # stop all streams
            # Wait for active tasks to finish, but bound the wait so a stream
            # that never completes (e.g. a stalled device) cannot hang the
            # caller indefinitely. Previously this was an unbounded
            # 'while self._sound_tasks' loop, which could freeze profile stop
            # and 'stop previous audio' for minutes if a task got stuck.
            deadline = time.time() + 2.0  # seconds
            while True:
                with self._tasks_lock:
                    has_tasks = bool(self._sound_tasks)
                if not has_tasks or time.time() >= deadline:
                    break
                self._task_trim()
                time.sleep(0.01)
            with self._tasks_lock:
                pending_tasks = list(self._sound_tasks)
            if pending_tasks:
                # give up on stragglers: try to cancel and drop them so the
                # queue is not blocked. Tasks already running cannot be
                # cancelled, but disabling playback above has signalled them
                # to stop at their next callback.
                for t in pending_tasks:
                    t.cancel()
                with self._tasks_lock:
                    self._sound_tasks = []
            with self._tasks_lock:
                self._playback_enabled = True  # renable once all streams are done

    def _task_trim(self):
        """trims the task list of completed tasks"""
        with self._tasks_lock:
            if self._sound_tasks:
                done_list = [t for t in self._sound_tasks if t.done()]
                self._sound_tasks = [t for t in self._sound_tasks if t not in done_list]

    def _is_playback_enabled(self) -> bool:
        with self._tasks_lock:
            return self._playback_enabled

    def play(self, filename: str, options: PlaybackOptions, blocking: bool = False):
        """plays a sound file via SD low level library"""
        try:
            if not self._is_playback_enabled():
                # playback is not enabled
                return

            self._task_trim()  # cleanup prior tasks

            device_name = options.device  # playback device name
            loops = options.loops  # number of loops to play

            if device_name:
                if device_name in self.device_name_to_id_map:
                    device_id = self.device_name_to_id_map[device_name]
                    device_samplerate = self.device_sample_rate_map[device_id]
            else:
                # get the current default device
                device = sd.query_devices(kind="output")
                device_id = device["index"]
                device_samplerate = device["default_samplerate"]
                device_name = device["name"]

            # process the audio file
            with sf.SoundFile(filename) as f:
                data = f.read(dtype="float32", always_2d=True)  # default is 64bit, change to 32bit floats
                samplerate = f.samplerate  # audio file sample rate in hertz
                channels = f.channels  # 1 for mono, 2 for stereo (usual)

            rate = options.rate  # playback rate (pitch corrected)
            volume = options.volume  # volume to apply
            fade_in = options.fadein_ms  # fade in duration
            fade_out = options.fadeout_ms  # fade out duration
            duration = options.playback_ms  # max duration of the sample to play back
            _verbose = gremlin.config.Configuration().verbose_mode_sound

            fade_in = 0
            fade_out = 0

            # data, samplerate = sf.read(filename, dtype='float32')

            # resample the audio to match the device sample rate

            if device_samplerate != samplerate:
                # determin how many new samples are needed
                new_sample_count = int(len(data) * device_samplerate / samplerate)

                # 3. Resample the audio data using scipy.signal.resample
                resampled_audio = signal.resample(data, new_sample_count)

                # Ensure data type is compatible with sounddevice (e.g., float32)
                data = np.array(resampled_audio, dtype="float32")

            total_frames = len(data)

            # modify the playback rate if requested maintaining the pitch (this is approximate)
            if rate is not None and rate != 1.0:
                # this maintains pitch using pyrubberband
                data = pyrb.time_stretch(data, samplerate, rate)

            # modify the playback duration if requested (this will make the sample shorter only)
            if duration is not None and duration > 0:
                duration_seconds = duration / 1000  # to seconds
                frame_count = int(duration_seconds * samplerate)
                if total_frames > frame_count:
                    # trim needed
                    data = data[:frame_count]

            # modify the playback volume
            if volume is not None and volume >= 0:
                data = data * (volume / 100)  # convert percent to volume.  50% = 0.5 = half volume

            # apply a fade in ramp if requested
            if fade_in is not None and fade_in > 0:
                duration_seconds = fade_in / 1000
                frame_count = int(duration_seconds * samplerate)
                # creates vector ramp from 0.0 to 1.0 volume over the fade duration
                fade_ramp = np.linspace(0.0, 1.0, frame_count)
                multiplier = np.ones(total_frames)
                multiplier[-len(fade_ramp) :] = fade_ramp

                if data.ndim > 1:  # Stereo
                    data = (data * multiplier[:, np.newaxis]).astype(data.dtype)
                else:  # Mono
                    data = (data * multiplier).astype(data.dtype)

            # apply a fade out ramp if requested
            if fade_out is not None and fade_out > 0:
                duration_seconds = fade_out / 1000
                frame_count = int(duration_seconds * samplerate)
                # creates vector ramp from 1.0 to 0.0 volume
                fade_ramp = np.linspace(1.0, 0.0, frame_count)
                multiplier = np.ones(total_frames)
                multiplier[-len(fade_ramp) :] = fade_ramp

                if channels > 1:  # Stereo
                    data = (data * multiplier[:, np.newaxis]).astype(data.dtype)
                else:  # Mono
                    data = (data * multiplier).astype(data.dtype)

            # cache the playback data

            if filename not in self.running_data:
                self.running_data[filename] = {}

            task = self.pool.submit(self._play_runner, data, device_id, loops)
            with self._tasks_lock:
                self._sound_tasks.append(task)
            if blocking:
                task.result()  # wait for the task to complete if blocking

        except Exception as e:
            syslog.error(f"SOUND: PLAY: An error occurred: {e}")

    def _play_runner(self, data, device_id, loops):

        try:
            for _ in range(loops):
                event = threading.Event()
                current_frame = 0

                def callback(outdata, frames, time, status):
                    nonlocal current_frame, event
                    if status:
                        syslog.info(status)
                    chunksize = min(len(data) - current_frame, frames)
                    outdata[:chunksize] = data[current_frame : current_frame + chunksize]
                    if chunksize < frames or not self._is_playback_enabled():
                        # terminate playback on last frame or playback abort
                        outdata[chunksize:] = 0
                        event.set()
                    current_frame += chunksize

                stream = sd.OutputStream(callback=callback, device=device_id, finished_callback=event.set, channels=data.ndim)
                with stream:
                    event.wait()  # wait until playback is finished

            # syslog.info(f"playback done")

        except sd.CallbackStop:
            event.set()
        except Exception as e:
            syslog.error(f"SOUND: PLAY: An error occurred: {e}")

    def addPhrase(self, phrase: PhraseData) -> PhraseData:
        """registers a single phrase - ignored if already registered - returns the cached phrase if the phrase already exists"""
        return self.pm.add_phrase(phrase)

    def getPhrase(self, key):
        """retrieves a registered phrase by its key"""
        return self.pm.get_phrase(key)

    def registerPhrase(
        self, text: str, voice: str = None, rate: float = 1.0, pitch: int = 0, volume: float = 1.0, sound_file: str = None, temporary: bool = False
    ) -> dict:
        """returns a map of key -> PhraseData for the given text, new phrases are registered as needed"""
        return self.getPhraseMap(text, voice=voice, rate=rate, pitch=pitch, volume=volume, sound_file=sound_file, temporary=temporary)

    def saveConfig(self):
        """saves the current configuration of the phrase manager"""
        self.pm.writeConfig()

    def loadConfig(self):
        """loads the current configuration of the phrase manager"""
        self.pm.readConfig()

    def getPhraseMap(
        self,
        text: str,
        engine: PlayMode = None,
        voice: str = None,
        rate: float = 1.0,
        pitch: int = 0,
        volume: float = 1.0,
        sound_file: str = None,
        temporary: bool = False,
        register: bool = True,
    ):
        """gets a map of key -> PhraseData for the given text
        :param text: the text to generate phrases for
        :param engine: the engine to use for generating the phrase
        :param voice: the voice to use for TTS
        :param rate: the speech rate
        :param pitch: the speech pitch
        :param volume: the playback volume
        :param sound_file: the associated sound file
        :param temporary: whether the phrase is temporary
        :param register: whether to register the generated phrases immediately
        """
        phrase_map = {}
        if text:
            splits = text.split("|") if "|" in text else [text]
            for text in splits:
                text = text.strip()
                if text:
                    text = self.sanitizeText(text)  # also translates as needed
                    phrase = PhraseData(text=text, engine=engine, voice=voice, rate=rate, pitch=pitch, volume=volume, temporary=temporary)
                    phrase = self.addPhrase(phrase)  # add or get cached phrase
                    phrase_map[phrase.key] = phrase

                    if __debug__:
                        sound_file = phrase.sound_file
                        assert sound_file is not None, "invalid sound file - phrase not registered properly"
        return phrase_map

    def playPhrase(self, phrase: PhraseData, options: PlaybackOptions):
        """plays a registered phrase if the audio file is available"""
        if phrase and phrase.key in self.sound_audio_file_map:
            sound_file = self.sound_audio_file_map[phrase.key]
            self.play(sound_file, options)

    def playPyTTS(
        self,
        text: str,
        voice: str = None,
        rate: float = 1.0,
        audio_device: str = None,
        timed_random: TimedRandomInt = None,
        suppress_duplicate: bool = False,
        cooldown_seconds: float = 0,
    ):
        """plays the given text using the audio data generated by the legacy TTS engine"""

        phrase = self.generate(text, mode=PlayMode.PyTTS, voice=voice, rate=rate, timed_random=timed_random)
        if phrase:
            if suppress_duplicate:
                key = phrase.key
                if self._last_phrase_key:
                    last_key, last_time = self._last_phrase_key
                    if key == last_key:
                        now = time.time()
                        if (now - last_time) < cooldown_seconds:
                            return
                self._last_phrase_key = (key, time.time())

            options = PlaybackOptions(phrase.key)
            if audio_device:
                options.audio_device = audio_device
            self.playPhrase(phrase, options)

    def generate(
        self,
        text: str,
        mode: PlayMode = PlayMode.EdgeAI,
        voice: str = None,
        randomize_sound_file: bool = False,
        rate: float = 0,
        pitch: int = 0,
        volume: float = 1.0,
        playback_mode: PlaybackMode = PlaybackMode.RoundRobin,
        timed_random: TimedRandomInt = None,
        sound_file: str = None,  # single sound file
        sound_files: list[str] = None,  # pick list of sound files
        as_map: bool = False,
        force: bool = False,
    ) -> PhraseData | dict:
        """generates the audio for a given phrase using the specified play mode
        :param text: the text to generate audio for
        :param mode: the play mode to use for generating the audio
        :param voice: the voice to use for TTS
        :param randomize_sound_file: whether to randomize the sound file selection
        :param rate: the speech rate
        :param pitch: the speech pitch
        :param volume: the playback volume
        :param playback_mode: the playback mode to use
        :param timed_random: the timed random instance for randomization
        :param sound_file: the single sound file to use
        :param sound_files: the list of sound files to choose from
        :param as_map: whether to return the result as a map of key -> PhraseData
        :param force: whether to force regeneration of the audio
        :return: the generated PhraseData or a map of key if in map return mode [key] -> PhraseData

        """

        # ensure started
        if not self.ensureStarted():
            syslog.error("PLAY: unable to play sound due to sound library initialization issue")
            return None
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_tts or config.verbose_mode_sound

        # get the phrases for the sound
        phrase_map = {}

        # get or autogenerate the sound file

        match mode:
            case PlayMode.AudioFile:
                # static playback of one or more files depending if a folder or a single file
                if sound_file and os.path.isfile(sound_file):
                    if randomize_sound_file:
                        # pick a file at random from a list of files in the folder
                        if not sound_files:
                            # update file list - there is at least one file
                            sound_files = self.scanFolder(sound_file)
                            timed_random.setMax(len(sound_files) - 1)
                        index = timed_random.getValue()
                        sound_file = sound_files[index]
                    else:
                        sound_file = sound_file

                    # build a phrase for this static wav file
                    phrase = PhraseData(text=gremlin.util.get_guid(), engine=PlayMode.AudioFile, temporary=True)
                    phrase.sound_file = sound_file
                    phrase_map[phrase.key] = phrase

                    return phrase if not as_map else phrase_map

                else:
                    syslog.warning(f"PLAY: unable to locate file: [{sound_file}]")
                    return None if not as_map else {}

            case PlayMode.EdgeAI:
                # EdgeAI TTS generated

                engine = gremlin.sound.EdgeTTS()
                pitch = pitch
                volume = volume
                voice = voice
                rate = rate
                phrase_map = self.getPhraseMap(text, engine=mode, voice=voice, rate=rate, pitch=pitch, volume=volume)

            case PlayMode.PyTTS:
                # generate using internal TTS
                engine = gremlin.tts.TextToSpeech()
                pitch = 0
                volume = 1.0
                voice = voice
                rate = rate
                phrase_map = self.getPhraseMap(text, engine=mode, voice=voice, rate=rate, pitch=pitch, volume=volume)

            case _:
                syslog.error(f"PLAY: unsupported play mode: {mode}")
                return None

        assert engine is not None, "invalid engine"
        assert hasattr(engine, "generateActionWav"), "invalid engine - missing generateActionWav method"

        generated = False

        if verbose:
            count = len(phrase_map)
            syslog.info(f"PLAY: Generating [{count}] sound files...")
        for phrase in phrase_map.values():
            key = phrase.key
            sound_file = self.getSoundFile(key)
            assert sound_file is not None, "invalid sound file - phrase not registered properly"
            if force and os.path.isfile(sound_file):
                os.unlink(sound_file)
            if force or not os.path.isfile(sound_file):
                # does not exist, create
                result = engine.generateActionWav(phrase=phrase, voice=voice, rate=rate, pitch=pitch, volume=volume)
                if result:
                    generated = True
                    if verbose:
                        syslog.info(f"PLAY: Phrase: [{phrase.text}]")
                        syslog.info(f"\tSound file path: [{gremlin.util.toUrl(self.getSoundFolder())}]")
                        syslog.info(f"\tGenerated sound file: [{gremlin.util.toUrl(sound_file)}]")
                else:
                    syslog.error(f"PLAY: Phrase: [{phrase.text}]")
                    syslog.error(f"\tFailed to generate sound file: [{sound_file}]")
                    return None

            else:
                if verbose:
                    syslog.info(f"\tSound file path: [{gremlin.util.toUrl(self.getSoundFolder())}]")
                    syslog.info(f"PLAY: Phrase: [{phrase.text}]")
                    syslog.info(f"PLAY: Using cache [{gremlin.util.toUrl(sound_file)}]")

            # ensure the sound file is registered
            if key not in self.sound_audio_file_map:
                if not os.path.isfile(sound_file):
                    syslog.warning(f"PLAY: warning, generated sound file not found on disk for key [{key}]: [{gremlin.util.toUrl(sound_file)}]")
                self.sound_audio_file_map[key] = sound_file

        if generated:
            self.saveConfig()  # save the updated sound configuration for next time

        if as_map:
            return phrase_map

        # if multiple phrases, pick one at random
        phrase = self.pickPhrase(phrase_map, mode=mode, playback_mode=playback_mode, timed_random=timed_random)
        return phrase

    def scanFolder(self, sound_file: str = None):
        """scans the file folder for valid audio files"""
        if sound_file and os.path.isfile(sound_file):
            sound_files = []
            folder_path = os.path.dirname(sound_file)
            entries = os.listdir(folder_path)
            for entry in entries:
                ext = gremlin.util.get_ext(entry)
                if ext in (".wav", ".mp3"):
                    sound_files.append(os.path.join(folder_path, entry).casefold())
        return sound_files

    def pickPhrase(self, phrase_map: dict, mode: PlayMode, playback_mode: PlaybackMode = PlaybackMode.RoundRobin, timed_random: TimedRandomInt = None):
        """picks a phrase to play based on the playback mode"""
        if not phrase_map:
            self._last_phrase = None
            return None

        keys = list(phrase_map.keys())
        count = len(keys)
        match playback_mode:
            case PlaybackMode.RoundRobin:
                if count == 1:
                    self._last_phrase = phrase_map[keys[0]]
                    return self._last_phrase
                if self._last_phrase:
                    key = self._last_phrase.key
                    if key in keys:
                        index = keys.index(self._last_phrase.key)
                        index = (index + 1) % len(keys)
                        phrase = phrase_map[keys[index]]
                    else:
                        # first item if key is invalid
                        phrase = phrase_map[keys[0]]
                else:
                    # first item
                    phrase = phrase_map[keys[0]]

            case PlaybackMode.Random:
                key = random.choice(keys)
                phrase = phrase_map[key]

            case PlaybackMode.TimedRandom:
                # ensure the timed randomizer gets us a correct index for the number of available sound files
                match mode:
                    case PlayMode.EdgeAI | PlayMode.PyTTS:
                        # EdgeAI specific logic if needed
                        if timed_random.max_val != count - 1:
                            timed_random.max_val = count - 1
                    case PlayMode.AudioFile:
                        count_files = len(self._sound_files) - 1
                        if timed_random.max_val != count_files:
                            timed_random.max_val = count_files

                index = timed_random.getValue()
                key = keys[index]
                phrase = phrase_map[key]
            case _:
                phrase = next(iter(phrase_map.values()))

        self._last_phrase = phrase
        return phrase

    def queueAction(self, action: SoundEvent):
        """queues a sound action - PG mode only"""
        self._event_queue.put(action)
        if not self._is_running:
            self.start()  # ensure started

    def queueActions(self, actions: list[SoundEvent]):
        """queues multiple sound actions  - PG mode only"""
        with self._state_lock:
            self._is_paused = True  # pause sound processing
        for action in actions:
            self._event_queue.put(action)
        with self._state_lock:
            self._is_paused = False  # resume processing
        if not self._is_running:
            self.start()  # ensure started

    def clearQueue(self):
        """clears pending sound actions  - PG mode only"""
        with self._state_lock:
            self._is_paused = True  # pause processing
        while not self._event_queue.empty():
            self._event_queue.get()
            self._event_queue.all_tasks_done()
        with self._state_lock:
            self._is_paused = False  # resume processing

    def stopPlayback(self):
        """stops all playbacks"""
        self.clearQueue()
        self.soundStop()

    def _queue_runner(self):
        """processes the sound queue - PG mode onlyt"""
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_tts or config.verbose_mode_sound
        current_device_name = None

        while True:
            with self._state_lock:
                is_running = self._is_running
                is_paused = self._is_paused
            if not is_running:
                break

            if is_paused:
                # pause processing
                time.sleep(0.01)
                continue

            if self._event_queue.empty():
                time.sleep(0.01)
                continue

            event: SoundEvent = self._event_queue.get()
            if verbose:
                syslog.info(f"SOUNDLISTEN: DEQUEUE event {event.action.name}  QUEUE size: {self._event_queue.qsize():,}")
            if USE_PG:
                if pygame.mixer.get_init() is None:
                    if self._playback_device_name:
                        pygame.mixer.pre_init(devicename=self._playback_device_name)
                    pygame.mixer.init()
            match event.action:
                case SoundAction.Play:
                    # play item
                    key = event.key
                    data: PlaybackOptions = event.data
                    sound_file = data.sound_file
                    if verbose:
                        syslog.info(f"\tplay [{key}] [{gremlin.util.toUrl(sound_file)}]")
                    if USE_SD:
                        if data.stop_previous:
                            # stop any sounds currently playing before starting
                            # the new one. On the sounddevice (SD) path this was
                            # previously ignored - stop_previous was only honored
                            # on the pygame path below - so 'Stop previous audio'
                            # had no effect for AI/Edge-TTS playback.
                            self.soundStop()
                        self.play(sound_file, data, blocking=data.blocking)
                    elif USE_PG:
                        if key in self.sound_map:
                            _audio_file = self.sound_audio_file_map[key]
                            sound = pygame.mixer.Sound(_audio_file)
                            if data.stop_previous:
                                # stop previous sounds
                                pygame.mixer.stop()
                            if data.volume is not None:
                                volume = data.volume
                                sound.set_volume(volume)
                            if data.fadeout_ms:
                                sound.fadeout(data.fadeout_ms)
                            sound.play(data.loops, data.playback_ms, data.fadein_ms)
                    # self._event_queue.task_done()

                case SoundAction.SetVolume:
                    if USE_PG:
                        key = event.key
                        if key in self.sound_map:
                            if verbose:
                                syslog.info(f"\tset volume [{key}] volume: {event.data:0.3f}")
                            sound: pygame.mixer.Sound = self.sound_map[key]
                            volume = event.data
                            self.sound_volume_map[key] = volume
                    # self._event_queue.task_done()

                case SoundAction.ChangeDevice:
                    if USE_PG:
                        device_name = event.data

                        if current_device_name != device_name:
                            if verbose:
                                syslog.info(f"\tchange device [{device_name}]")
                            self.setPlaybackDevice(device_name)
                            current_device_name = device_name
                            self._playback_device_name = device_name
                    # self._event_queue.task_done()

                case SoundAction.Stop:
                    # clear the queue and stop playback
                    if verbose:
                        syslog.info("\tstop")
                    if USE_PG:
                        pygame.mixer.stop()
                    elif USE_SD:
                        sd.stop()

                    # self._event_queue.task_done()

                    # clear the rest of the queue
                    while not self._event_queue.empty():
                        self._event_queue.get()
                        # self._event_queue.task_done()

    def hasActionWav(self, action) -> bool:
        """true if the action wave file if found"""
        wav = action.tts_file
        return wav and os.path.isfile(wav)

    def getNewWav(self) -> str:
        id = gremlin.util.get_guid()
        tts_file = os.path.join(self._sound_folder, f"{id}.wav")
        return tts_file

    def translate_text(self, text):
        """Returns the provided text after running text substitution on it.

        :param text the text to substitute parts of
        :return original text with parts substituted
        """
        text = text.replace("${current_mode}", gremlin.shared_state.current_mode)
        return text

    def sanitizeText(self, text):
        """removes characters that are problematic in text"""
        import re

        # translation layer
        text = self.translate_text(text)

        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        text = re.sub(r"`.*?`", "", text, flags=re.DOTALL)
        text = re.sub(r"\(.*?\)", "", text, flags=re.DOTALL)

        # remove marks
        text = text.replace("```", "")
        text = text.replace("...", " ")
        text = text.replace("(", " ")
        text = text.replace(")", " ")

        # use cp1252 encoding since it's what is used under the hood
        encoded = text.encode("cp1252", errors="replace")
        return encoded.decode("cp1252")

    def convertMp3ToWav_pydub(self, mp3_file: str, wav_file: str) -> bool:
        """Converts an MP3 file to WAV format."""
        try:
            audio = AudioSegment.from_mp3(mp3_file)
            audio.export(wav_file, format="wav")
            return True
        except Exception as e:
            syslog.error(f"Failed to convert MP3 to WAV [{mp3_file} -> {wav_file}]: {str(e)}")
            return False

    def ensureFFmpeg(self) -> bool:
        try:
            if self._ffmpeg_exe:
                return True

            if getattr(sys, "frozen", False):
                # Running as a packaged executable - ffmpeg ships in _internal
                current_dir = os.path.dirname(sys.executable)
                ffmpeg_exe = os.path.join(current_dir, "_internal", "ffmpeg.exe")
                if os.path.isfile(ffmpeg_exe):
                    self._ffmpeg_exe = ffmpeg_exe
                    return True
                syslog.error("FFmpeg not found.")
                return False

            # Running as a normal Python script
            main_module = sys.modules["__main__"]
            if not hasattr(main_module, "__file__"):
                return False
            current_dir = os.path.dirname(os.path.abspath(main_module.__file__))

            # 1. Look for a local ./ffmpeg/ffmpeg.exe next to the script
            ffmpeg_exe = os.path.join(current_dir, "ffmpeg", "ffmpeg.exe")
            if os.path.isfile(ffmpeg_exe):
                self._ffmpeg_exe = ffmpeg_exe
                return True

            # 2. Fall back to ffmpeg on the system PATH
            path_ffmpeg = shutil.which("ffmpeg")
            if path_ffmpeg:
                self._ffmpeg_exe = path_ffmpeg
                syslog.info(f"FFmpeg found on PATH: {path_ffmpeg}")
                return True

            # 3. Last resort: auto-download a static build into ./ffmpeg/
            downloaded = self._downloadFFmpeg()
            if downloaded and os.path.isfile(downloaded):
                self._ffmpeg_exe = downloaded
                syslog.info(f"FFmpeg auto-downloaded: {downloaded}")
                return True

            syslog.error("FFmpeg not found.")
            return False
        except Exception as e:
            syslog.error(f"Failed to ensure FFmpeg: {str(e)}")
            return False

    def _downloadFFmpeg(self) -> str | None:
        """Download a static FFmpeg build from gyan.dev into ./ffmpeg/ on first use.

        Returns the path to ffmpeg.exe on success, else None.
        """
        import urllib.request
        import hashlib
        import zipfile
        import tempfile

        try:
            # Determine target directory next to the main script
            main_module = sys.modules["__main__"]
            if not hasattr(main_module, "__file__"):
                return None
            base_dir = os.path.dirname(os.path.abspath(main_module.__file__))
            target_dir = os.path.join(base_dir, "ffmpeg")
            os.makedirs(target_dir, exist_ok=True)
            target_exe = os.path.join(target_dir, "ffmpeg.exe")

            url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
            sha_url = url + ".sha256"

            syslog.info("FFmpeg not found locally. Downloading a static build (~100 MB, one-time)...")

            # Fetch expected SHA-256 (best-effort)
            expected_sha = None
            try:
                with urllib.request.urlopen(sha_url, timeout=30) as r:
                    expected_sha = r.read().decode("utf-8").split()[0].strip().lower()
            except Exception as e:
                syslog.warning(f"FFmpeg: could not fetch checksum ({e}); continuing without verification.")

            # Download the ZIP to a temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp_zip = tmp.name
            with urllib.request.urlopen(url, timeout=120) as resp, open(tmp_zip, "wb") as out:
                shutil.copyfileobj(resp, out)

            # Verify integrity
            if expected_sha:
                h = hashlib.sha256()
                with open(tmp_zip, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                actual_sha = h.hexdigest().lower()
                if actual_sha != expected_sha:
                    syslog.error("FFmpeg: checksum mismatch, aborting download.")
                    os.remove(tmp_zip)
                    return None

            # Extract bin/ffmpeg.exe (and ffprobe.exe) into target_dir, flattened
            with zipfile.ZipFile(tmp_zip) as zf:
                for name in zf.namelist():
                    lower = name.lower()
                    if lower.endswith("/bin/ffmpeg.exe") or lower.endswith("/bin/ffprobe.exe"):
                        exe_name = os.path.basename(name)
                        with zf.open(name) as src, open(os.path.join(target_dir, exe_name), "wb") as dst:
                            shutil.copyfileobj(src, dst)

            os.remove(tmp_zip)

            if os.path.isfile(target_exe):
                syslog.info(f"FFmpeg installed to {target_exe}")
                return target_exe
            syslog.error("FFmpeg: ffmpeg.exe not found in downloaded archive.")
            return None

        except Exception as e:
            syslog.error(f"FFmpeg auto-download failed: {str(e)}")
            return None

    def convertMp3ToWav(self, mp3_file: str, wav_file: str) -> bool:
        """Converts an MP3 file to WAV format."""
        try:
            if self.ensureFFmpeg():
                import subprocess

                process = subprocess.run([self._ffmpeg_exe, "-i", mp3_file, wav_file], capture_output=True)
                if process.returncode != 0:
                    syslog.error(f"FFmpeg: conversion failed: {process.stderr.decode()}")
                    return False
                verbose = gremlin.config.Configuration().verbose_mode_sound
                if verbose:
                    syslog.info(f"FFmpeg: conversion succeeded: {mp3_file} -> {wav_file}")
                return True
            syslog.error("FFmpeg: conversion failed: ffmpeg not installed or not found on this system.")

        except Exception as e:
            syslog.error(f"FFmpeg: Failed to convert MP3 to WAV [{mp3_file} -> {wav_file}]: {str(e)}")
        return False

    def adjust_speed(self, wav, sample_rate: int = 24000, tts_speed: float = 1.0):
        """
        Adjusts the playback speed of a wav file.  The file is modified in place.

        :param wav: the full path to the source wave file to modify
        :param sample_rate: the sample rate, the default for AI generated is 24KHz
        :param tts_speed: playback factor, 1.0 = normal

        """

        from pydub import AudioSegment
        import soundfile as sf
        import pyrubberband as pyrb

        if tts_speed == 1.0:
            return True  # nothing to do

        # load the audio stream
        tmp = gremlin.util.getTemporaryFile("wav")
        try:
            shutil.copy(wav, tmp)
        except Exception as e:
            syslog.error(f"ETTS: Failed to copy file: {str(e)}")
            return False

        try:
            audio = AudioSegment.from_wav(tmp)
            wav_io = io.BytesIO()
            audio.export(wav_io, format="wav")

            data, samplerate = sf.read(wav_io)
            stretched_data = pyrb.time_stretch(data, samplerate, tts_speed)
            stretched_wav_io = io.BytesIO()
            sf.write(stretched_wav_io, stretched_data, samplerate, format="wav")
            stretched_wav_io.seek(0)

            try:
                os.unlink(wav)
            except Exception as e:
                syslog.error(f"ETTS: Failed to remove existing file: {str(e)}")
                return False

            try:
                new_audio = AudioSegment.from_wav(stretched_wav_io)
                new_audio.export(wav, format="wav")
                new_audio = None
            except Exception as e:
                syslog.error(f"ETTS: Failed to save file: {str(e)}")
                return False
        finally:
            try:
                os.unlink(tmp)
            except Exception as e:
                syslog.error(f"ETTS: Failed to remove temporary file: {str(e)}")

        return os.path.isfile(wav)


class TTSGeneratorDialog(QtWidgets.QDialog):
    """generic dialog box audio generator"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        config = gremlin.config.Configuration()

        self._speaker = config.ai_tts_last_speaker
        self.tts_speed = 1.0

        self.setWindowTitle("Generate AI Options")
        self.setModal(True)
        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.text_field = QtWidgets.QPlainTextEdit()

        widgets = [
            "Text (one line per audio file will be generated)",
            self.text_field,
        ]

        text_container = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)
        self.main_layout.addWidget(text_container)

        widgets = []

        self.speaker_widget = gremlin.ui.ui_common.QDataComboBox(auto_adjust=True, tooltip="Selected speaker for AI voice generation.")
        widgets.append(self.speaker_widget)

        self.tts_speed_widget = gremlin.ui.ui_common.QFloatLineEdit(
            min_range=0.1,
            max_range=10.0,
            value=self.tts_speed,
            callback=self._handle_tts_speed_changed,
            tooltip="Speed rate modifier for the generated audio.\n1.0 is the normal rate.",
        )

        widget = gremlin.ui.ui_common.QDataCheckbox(
            "Overwrite existing filenames",
            value=config.ai_tts_overwrite_filenames,
            callback=self._handle_overwrite_filename_changed,
            tooltip="Use the input text as the file name for the generated audio file.\nIf not set, a unique GUID will be used.",
        )
        widgets.append(widget)

        options_container = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True)
        self.main_layout.addWidget(options_container)

        generate_widget = gremlin.ui.ui_common.QDataPushButton("Generate", callback=self._handle_generate)
        close_widget = gremlin.ui.ui_common.QDataPushButton("Close", callback=self._handle_close)
        open_widget = gremlin.ui.ui_common.QDataPushButton("Open folder", callback=self._handle_open_folder)

        widgets = [generate_widget, open_widget, close_widget]
        button_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True, left_stretch=True)
        self.main_layout.addWidget(button_container)

        # initialize AI and load speaker list
        self._update_speakers(initialize=True)
        self.speaker_widget.setCallback(self._handle_speaker_changed)

    def _handle_close(self, widget):
        self.close()

    def _handle_open_folder(self, widget):
        """opens the sound folder"""
        ktts = gremlin.ktts.KTTS()
        folder = ktts.getSoundFolder()
        gremlin.util.create_folder(folder)  # create if it doesn't exist yet
        gremlin.util.open_folder(folder)

    def _handle_tts_speed_changed(self, value: float):
        self.tts_speed = value

    def _handle_speaker_changed(self, value):
        self.speaker = value
        config = gremlin.config.Configuration()
        config.ai_tts_last_speaker = value

    def _update_speakers(self, initialize=True):
        config = gremlin.config.Configuration()
        last_speaker = config.ai_tts_last_speaker
        if not self.speaker:
            # default speaker is the last one if we have one defined
            self.speaker = last_speaker

        ktts = gremlin.ktts.KTTS()

        speakers = ktts.getSpeakers(initialize=initialize)
        with QtCore.QSignalBlocker(self.speaker_widget):
            self.speaker_widget.clear()
        if speakers:
            # we have a list of speakers
            for speaker in speakers:
                self.speaker_widget.addItem(speaker, speaker)
            if self.speaker:
                speaker = self.speaker
            else:
                speaker = config.ai_tts_last_speaker
            if speaker:
                index = self.speaker_widget.findText(speaker)
                if index != -1:
                    self.speaker_widget.setCurrentIndex(index)
        else:
            if self.speaker:
                speaker = self.speaker
                self.speaker_widget.addItem(speaker, speaker)

        self.speaker_widget.setEnabled(speakers is not None)

        if self.speaker:
            index = self.speaker_widget.findData(self.speaker)
            if index != -1:
                with QtCore.QSignalBlocker(self.speaker_widget):
                    self.speaker_widget.setCurrentIndex(index)

    @property
    def speaker(self) -> str:
        return self._speaker

    @speaker.setter
    def speaker(self, value):
        self._speaker = value

    def _handle_overwrite_filename_changed(self, checked: bool):
        config = gremlin.config.Configuration()
        config.ai_tts_overwrite_filenames = checked

    def _handle_generate(self, widget):
        """generate the audio files"""
        import gremlin.ktts
        import gremlin.config
        import gremlin.util

        speaker = self.speaker
        tts_speed = self.tts_speed

        text = self.text_field.toPlainText()
        if not text:
            return  # nothing to do
        config = gremlin.config.Configuration()
        overwrite = config.ai_tts_overwrite_filenames

        lines = text.splitlines()
        ktts = gremlin.ktts.KTTS()
        wav = ktts.getNewWav()
        ext = gremlin.util.get_ext(wav)
        dir = os.path.dirname(wav)

        ui = gremlin.shared_state.ui
        count = len(lines)
        progress_dialog = QtWidgets.QProgressDialog("Generating audio", "", 0, count, parent=ui)
        progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
        progress_dialog.setAutoClose(True)
        progress_dialog.setMinimumDuration(0)  # Show immediately
        progress_dialog.setCancelButton(None)  # no cancel button
        time.sleep(0.05)
        QtWidgets.QApplication.processEvents()  # Process events to keep the UI responsive

        for index, text in enumerate(lines):
            progress_dialog.setValue(index + 1)
            time.sleep(0.05)
            QtWidgets.QApplication.processEvents()  # Process events to keep the UI responsive

            suggested_name = gremlin.util.textWordsToUnderscore(text)
            suggested_file = os.path.join(dir, suggested_name)
            fname = gremlin.util.swap_ext(suggested_file, ext)
            if os.path.isfile(fname):
                if overwrite:
                    try:
                        os.unlink(fname)
                    except Exception as e:
                        syslog.error(f"PLAY: unable to remove existing audio file [{fname}]: {str(e)}")
            # use index for a unique name if needed
            if os.path.isfile(fname):
                index = 1
                base_fname = fname
                while os.path.isfile(fname):
                    fname = gremlin.util.swap_ext(base_fname, suffix=f"_{index}")
                    index += 1

            # generate the output
            wav = ktts.generateWav(tts_file=fname, text=text, speaker=speaker, tts_speed=tts_speed)


class GenerateDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent=parent)

        config = gremlin.config.Configuration()

        self.setWindowTitle("Generate AI Options")
        self.setModal(True)
        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.main_layout.addWidget(QtWidgets.QLabel("AI generation options:"))

        widgets = []
        widget = gremlin.ui.ui_common.QDataCheckbox(
            "Save profile on generate",
            value=config.ai_tts_save_on_generate,
            callback=self._handle_save_on_generate_changed,
            tooltip="Save the profile automatically once the audio file have been generated.",
        )
        widgets.append(widget)

        widget = gremlin.ui.ui_common.QDataCheckbox(
            "Use word based filenames",
            value=config.ai_tts_use_word_filenames,
            callback=self._handle_word_filename_changed,
            tooltip="Use the input text as the file name for the generated audio file.\nIf not set, a unique GUID will be used.",
        )
        widgets.append(widget)

        widget = gremlin.ui.ui_common.QDataCheckbox(
            "Overwrite existing filenames",
            value=config.ai_tts_overwrite_filenames,
            callback=self._handle_overwrite_filename_changed,
            tooltip="Use the input text as the file name for the generated audio file.\nIf not set, a unique GUID will be used.",
        )
        widgets.append(widget)

        option_container = gremlin.ui.ui_common.getVContainer(widgets, widget_only=True, left_margin=12)
        self.main_layout.addWidget(option_container)

        ok_widget = gremlin.ui.ui_common.QDataPushButton("Ok", callback=self._handle_ok)
        cancel_widget = gremlin.ui.ui_common.QDataPushButton("Cancel", callback=self._handle_cancel)
        widgets = ["||", ok_widget, cancel_widget, "||"]
        button_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.main_layout.addWidget(button_container)

    def _handle_save_on_generate_changed(self, checked: bool):
        config = gremlin.config.Configuration()
        config.ai_tts_save_on_generate = checked

    def _handle_word_filename_changed(self, checked: bool):
        config = gremlin.config.Configuration()
        config.ai_tts_use_word_filenames = checked

    def _handle_overwrite_filename_changed(self, checked: bool):
        config = gremlin.config.Configuration()
        config.ai_tts_overwrite_filenames = checked

    def _handle_ok(self, widget):
        self.accept()

    def _handle_cancel(self, widget):
        self.reject()


class EdgeTTSVoice:
    """Represents a structured Microsoft Edge TTS Voice."""

    def __init__(self, data: Dict[str, Any]):
        self.name: str = ""
        self.short_name: str = ""
        self.gender: str = ""
        self.locale: str = ""
        self.suggested_codec: str = ""
        self.friendly_name: str = ""
        self.friendly_locale: str = ""
        self.status: str = ""
        if data:
            if "Name" in data:
                self.name: str = data.get("Name", "")
                self.short_name: str = data.get("ShortName", "")
                self.gender: str = data.get("Gender", "")
                self.locale: str = data.get("Locale", "")
                self.friendly_locale: str = self.translateLocale(self.locale)
                self.suggested_codec: str = data.get("SuggestedCodec", "")
                self.friendly_name: str = data.get("FriendlyName", "")
                self.status: str = data.get("Status", "")
            elif "name" in data:
                # read from JSON with lowercase keys
                self.name: str = data.get("name", "")
                self.short_name: str = data.get("short_name", "")
                self.gender: str = data.get("gender", "")
                self.locale: str = data.get("locale", "")
                self.friendly_locale: str = self.translateLocale(self.locale)
                self.suggested_codec: str = data.get("suggested_codec", "")
                self.friendly_name: str = data.get("friendly_name", "")
                self.status: str = data.get("status", "")

    def translateLocale(self, locale: str) -> str:
        """Returns a descriptive string like 'English (United States)'."""
        parts = locale.strip().split("-")
        lang_code = parts[0].lower()

        lang = pycountry.languages.get(alpha_2=lang_code) or pycountry.languages.get(alpha_3=lang_code)
        lang_name = lang.name if lang else "Unknown Language"

        if len(parts) > 1:
            country_code = parts[1].upper()
            country = pycountry.countries.get(alpha_2=country_code)
            if country:
                return f"{lang_name} ({country.name})"

        return lang_name

    def __repr__(self) -> str:
        return f"<Voice name='{self.short_name}' gender='{self.gender}' locale='{self.locale}'>"


@gremlin.singleton_decorator.SingletonDecorator
class EdgeTTS:
    """TTS generation via edge-tts"""

    def __init__(self):
        self._speaker = "default"
        self._sound = Sound()

        self._voices_list = {}  # keyed by short name
        self.getVoiceList()  # load the default voices or from the web

    def _generate(
        self,
        text: str,
        output_wav: str,
        speaker: str = "en-US-AvaNeural",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        volume: str = "+0%",
    ):
        """generates the output file (MP3) via edge tts
        :param text: the text to convert to speech
        :param speaker: the speaker voice to use, optional - default is ava neural US english
        :param output_wav: the path to the output WAV file
        :param rate: the speech rate adjustment
        :param pitch: the speech pitch adjustment
        :param volume: the speech volume adjustment
        :returns: the path to the generated WAV file or None if failed

        """
        output_mp3 = gremlin.util.getTemporaryFile(".mp3")
        try:
            assert bool(speaker), "Speaker must be specified"
            assert bool(output_wav), "Output WAV file must be specified"

            try:
                communicate = edge_tts.Communicate(text=text, voice=speaker, rate=rate, pitch=pitch, volume=volume)

                asyncio.run(communicate.save(output_mp3))

            except Exception as e:
                syslog.error(f"ETTS: failed to generate audio file [{output_wav}]: {str(e)}")
                return None

            # convert mp3 to wav
            if os.path.isfile(output_mp3):
                # valiate the output folder
                path = os.path.dirname(output_wav)
                if not os.path.isdir(path):
                    os.makedirs(path, exist_ok=True)
                if os.path.isfile(output_wav):
                    os.unlink(output_wav)
                result = self._sound.convertMp3ToWav(output_mp3, output_wav)
                if not result:
                    syslog.error(f"ETTS: failed to convert MP3 to WAV [{output_mp3} -> {output_wav}]")

                return output_wav

            return None
        finally:
            # cleanup temporary MP3 file
            if os.path.isfile(output_mp3):
                try:
                    os.unlink(output_mp3)
                except Exception as e:
                    syslog.error(f"ETTS: unable to remove temporary MP3 file [{output_mp3}]: {str(e)}")

    def is_available(self):
        return True

    def is_speed_available(self):
        return True

    def generateActionWav(self, phrase: PhraseData, voice: str = None, rate: int = 0, pitch: int = 0, volume: int = 0) -> bool:
        """generates a wave file for the given action
        :param phrase: the phrase data containing text, rate, pitch, and sound file
        :param voice: the speaker voice to use, optional
        :param rate: the speech rate adjustment - generated playback rate (as a whole percentage, e.g., 10 means +10%)
        :param pitch: the speech pitch adjustment in Herz, 0 for no change
        :param volume: the speech volume adjustment positive or negative percentage, -50 means 50% quieter, 50 means 50% louder
        :returns: the file name or None

        """
        tts_file = phrase.getSoundFile()
        # convert to an edge tts rate
        edge_rate = f"{int(rate):+}%"
        edge_pitch = f"{pitch:+}Hz"
        edge_volume = f"{int(volume * 100):+}%"

        return self.generateWav(tts_file=tts_file, text=phrase.text, voice=voice, rate=edge_rate, pitch=edge_pitch, volume=edge_volume)

    def generateWav(self, tts_file: str, text: str, voice: EdgeTTSVoice | str = None, rate: str = "+0%", pitch: str = "+0Hz", volume: str = "+0%") -> bool:
        """gets the wave file for the given options

        :param tts_file: the path to create
        :param text: the text to use
        :param voice: the speaker voice to use, optional
        :param rate: the speech rate adjustment
        :param volume: the speech volume adjustment
        :param pitch: the speech pitch adjustment

        :returns: True if the WAV file was successfully generated, False otherwise
        """

        if not text:
            syslog.warning("ETTS: sanitized text is blank, nothing to generate.")
            return False  # no text

        if not voice:
            # grab the default voice
            voice = voice = self.defaultVoice()
        else:
            if isinstance(voice, str):
                speaker = voice.casefold()

                voice = self._voices_list.get(speaker, None)

                if not voice:
                    syslog.warning(f"Sound: ETTS: unable to find voice matching '{speaker}', using default voice.")
                    voice = self.defaultVoice()
        if not voice:
            syslog.error("Sound: unable to find a voice to use.'")
            return False

        # speaker to use
        wav = tts_file
        syslog.info(f"ETTS: generate voice using [{voice.short_name}]")

        if os.path.isfile(wav):
            try:
                os.unlink(wav)
            except Exception as e:
                syslog.error(f"ETTS: unable to remove existing file: {str(e)}")
                return False

        """ generate """

        speaker = voice if isinstance(voice, str) else voice.short_name
        wav = self._generate(text=text, speaker=speaker, pitch=pitch, rate=rate, volume=volume, output_wav=wav)
        if wav:
            syslog.info(f"\tPhrase: [{text}]")
            syslog.info(f"\tsuccess: generated  [{gremlin.util.toUrl(wav)}]")
            return True
        return False

    def _get_voice_list(self) -> dict[str, EdgeTTSVoice]:
        """gets a list of all edge tts voices"""
        voices = asyncio.run(self._list_all_voices())

        # Print the details of each voice
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_tts or config.verbose_mode_sound
        if verbose:
            syslog.info("ETTS: listing all available voices:")
            for voice in voices:
                syslog.info(f"Name: {voice.short_name} | Gender: {voice.gender} | Locale: {voice.locale}")

        return {voice.short_name.casefold(): voice for voice in voices}

    async def _list_all_voices(self) -> List[EdgeTTSVoice]:
        """gets the list of all voices via edge-tts"""

        voices = await edge_tts.list_voices()
        voices = [EdgeTTSVoice(voice) for voice in voices]
        return voices

    def getVoiceList(self) -> dict[str, EdgeTTSVoice]:
        if not self._voices_list:
            # attempt to read the voice list from the local configuration file
            self.readVoiceList()
        if not self._voices_list:
            try:
                self._voices_list = self._get_voice_list()
                self.saveVoiceList()
            except Exception as e:
                syslog.error(f"Sound: ETTS: unable to read voice list: {str(e)}")
                # use default voices
                self.loadDefaultVoices()

        return self._voices_list

    def loadDefaultVoices(self):
        """setup default voices"""
        self._voices_list.clear()
        self._voices_list["en-US-AriaNeural".casefold()] = EdgeTTSVoice({"short_name": "en-US-AriaNeural", "gender": "Female", "locale": "en-US"})
        self._voices_list["en-US-GuyNeural".casefold()] = EdgeTTSVoice({"short_name": "en-US-GuyNeural", "gender": "Male", "locale": "en-US"})

    def defaultVoice(self) -> EdgeTTSVoice:
        """returns the default voice"""
        voice = self._voices_list.get("en-US-AriaNeural".casefold(), None)
        if not voice:
            self.loadDefaultVoices()
            voice = self._voices_list.get("en-US-AriaNeural".casefold(), None)
        return voice

    def saveVoiceList(self):
        if self._voices_list:
            try:
                config = gremlin.config.Configuration()
                verbose = config.verbose_mode_tts or config.verbose_mode_sound
                sound = Sound()
                config_file = os.path.join(sound.soundFolder, "etts_voices.json")
                if verbose:
                    syslog.info(f"ETTS: save available voices to [{gremlin.util.toUrl(config_file)}]")
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump([voice.__dict__ for voice in self._voices_list.values()], f, ensure_ascii=False, indent=4)
            except Exception as e:
                syslog.error(f"Sound: ETTS: unable to save voice list: {str(e)}")

    def readVoiceList(self):
        try:
            sound = Sound()
            config_file = os.path.join(sound.soundFolder, "etts_voices.json")
            if os.path.isfile(config_file):
                self._voices_list.clear()
                with open(config_file, "r", encoding="utf-8") as f:
                    voices_data = json.load(f)
                    for data in voices_data:
                        voice = EdgeTTSVoice(data)
                        self._voices_list[voice.short_name.casefold()] = voice

            # sort by name
            self._voices_list = dict(sorted(self._voices_list.items(), key=lambda item: item[0]))
        except Exception as e:
            syslog.error(f"Sound: ETTS: unable to load voice list: {str(e)}")

    def getLocales(self, gender: str = None) -> list[(str, str)]:
        """gets a list of all available locales (friendly_locale, locale)"""
        voices = self.getVoiceList()
        if gender:
            voices = {k: v for k, v in voices.items() if v.gender == gender}
        locales = sorted(set((v.friendly_locale, v.locale) for v in voices.values()))
        return locales

    def getGenders(self) -> list[str]:
        """gets a list of all available genders"""
        voices = self.getVoiceList()
        genders = sorted(set(v.gender for v in voices.values()))
        return genders

    def getFilteredVoices(self, locale: str = None, gender: str = None) -> dict[str, EdgeTTSVoice]:
        """gets a list of filtered voices by locale and gender"""
        voices = self.getVoiceList()
        if locale:
            voices = {k: v for k, v in voices.items() if v.locale == locale}
        if gender:
            voices = {k: v for k, v in voices.items() if v.gender == gender}
        return voices

    def getVoice(self, speaker: str) -> EdgeTTSVoice:
        """gets a voice by speaker name, not case sensitive"""
        return self._voices_list.get(speaker.casefold(), None)

    def refreshVoiceList(self):
        """refresh the voice list from the web"""
        try:
            self._voices_list = self._get_voice_list()
            self.saveVoiceList()
        except Exception as e:
            syslog.error(f"Sound: ETTS: unable to refresh voice list: {str(e)}")
            self.loadDefaultVoices()

    def findVoice(self, speaker: str) -> EdgeTTSVoice:
        """finds a voice by speaker name, not case sensitive"""
        return self._voices_list.get(speaker.casefold(), None)
