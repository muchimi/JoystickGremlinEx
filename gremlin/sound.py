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

from __future__ import annotations
import os
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

syslog = logging.getLogger("system")

class SoundAction(enum.Enum):
    Play = 1 # play a sound key using the options previously selected
    ChangeDevice = 2 # change the audio output device 
    SetVolume = 3 # set teh volume on a sound key
    Stop = 4 # stop playback


class PlaybackOptions():
    ''' holds sound playback options '''
    def __init__(self, key : str, loops : int = 1, volume : float = None, playback_ms : int = 0, fadein_ms : int = 0, fadeout_ms : int = 0, stop_previous : bool = False):
        ''' playback options 
        
        :param key: the sound file key as registered with the sound module (getSoundKey())
        :param loops: count of playback loops.  0 means no playback. 
        :param volume: volume 0 to 1, leave None for default volume
        :param playback_ms: time for the playback in milliseconds, 0 to disable.  If provided, plays the sound only for the specified number of milliseconds.
        :param fadein_ms: time in milliseconds for the time for the sound to fade in - if the sound is too short, it may never reach max volume
        :param fadeout_ms: time in milliseconds for the time for the sound to fade out
        '''
        self.key = key
        self.loops = loops - 1 if loops > 0 else 0 # sounds plays once, loops are extra repeats
        self.volume = volume
        self.playback_ms = playback_ms
        self.fadein_ms = fadein_ms
        self.fadeout_ms = fadeout_ms
        self.stop_previous = stop_previous


class SoundEvent():
    ''' single commands for the queue '''
    def __init__(self, action : SoundAction, key : str = None, data = None):
        self.key = key
        self.data = data
        self.action = action

    @staticmethod
    def PlayAction(key : str, loops : int = 1, volume : float = None, playback_ms : int = 0, fadein_ms : int = 0, fadeout_ms : int = 0, stop_previous : bool = False):
        data = PlaybackOptions(key, loops, volume, playback_ms, fadein_ms, fadeout_ms, stop_previous)
        return SoundEvent(SoundAction.Play, key = key, data = data)
    
    @staticmethod
    def ChangeDeviceAction(device_name : str):
        return SoundEvent(SoundAction.ChangeDevice, data = device_name)
    
    @staticmethod
    def SetVolumeAction(key : str, volume : int):
        return SoundEvent(SoundAction.SetVolume, key = key, data = volume / 100)
    
    @staticmethod
    def StopAction():
        return SoundEvent(SoundAction.Stop)
    


@gremlin.singleton_decorator.SingletonDecorator
class Sound():
    ''' wrapper class to play sounds via pygame and QT multimedia '''
    def __init__(self):
        
        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self._handle_shutdown)
        
        # list of devices from QT multimedia
        devices = QtMultimedia.QMediaDevices.audioOutputs()
        self.device_map = {index:device for index, device in enumerate(devices)}
        self._playback_device_name = None
        self.sound_map = {} # holds sound objects by key (guid -> sound object)
        self.sound_file_map = {} # holds the sound file (file -> key)
        self.sound_volume_map = {} # holds the sound volume for each key - if not present used the default volume
        self.sound_audio_file_map = {} # [key] -> audio file path
        self._audio_device = None 
        self._event_queue = queue.Queue() # sound queue - holds SoundCommand objects
        self._thread = None # sound thread
        self._is_running = False # true if the queue is running
        self._is_paused = False # true if queue processing is paused
        self._next_key = 0 # next key to use for each registered sound

        pygame.init()
        pygame.mixer.init()

    def start(self):
        ''' starts the sound queue '''
        if not self._is_running:
            self._is_running = True
            self._thread = threading.Thread(target = self._queue_runner)
            self._thread.name = "Sound Runner"
            self._thread.start()
            syslog.info("SOUND: starting engine")
           

    def stop(self):
        ''' stops the sound queue '''
        if self._is_running:
            self._is_running = False
            if self._thread.is_alive():
                self._thread.join()
            self._thread = None
            syslog.info("SOUND: engine shutdown")
            

    def _handle_shutdown(self):
        self.stop() # stop the runner
        self.soundStop() 
        self.device_map.clear()
        pygame.quit()


    @property
    def audio_device(self) -> str:
        return self._audio_device
    @audio_device.setter
    def audio_device(self, name : str):
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

    
    def findDevice(self, index : int):
        if index in self.device_map:
            return self.device_map[index]
        
    def findDeviceByDescription(self, description : str):
        ''' gets a device by description (name)'''
        device = next((d for d in self.device_map.values() if d.description() == description),None) 
        return device
    
    def findDeviceIndex(self, description : str):
        ''' gets the device index for a specific device description (name) '''
        index = next((i for i, d in self.device_map.items() if d.description() == description),None) 
        return index

    def getAudioDevice(self):
        ''' gets the audio device to play from '''
        
        default_audio_device = self.getDefaultAudioDevice()
        
        if self.audio_device:
            device = next((d for d in self.device_map.values() if d.description() == self.audio_device), default_audio_device) 
        else:
            device = default_audio_device
        return device
    
    def getDefaultAudioDevice(self):
        return  QtMultimedia.QMediaDevices.defaultAudioOutput()
    
    def getDefaultAudioDeviceIndex(self):
        index = next((i for i, d in self.device_map.items() if d.isDefault()),None) 
        return index

    
    def getAudioDeviceIndex(self):
        ''' gets the index of the selected device '''
        if not self.audio_device:
            device = self.getDefaultAudioDevice()
            self.audio_device = device.description()
        index = next((i for i, d in self.device_map.items() if d.description() == self.audio_device),None) 
        return index
    
    def setPlaybackDevice(self, name : str):
        ''' changes the playback device '''
        if self._playback_device_name != name:
            if pygame.mixer.get_init():
                # stop the mixer so we can change the device
                pygame.mixer.stop()
                pygame.mixer.quit()
            
            pygame.mixer.pre_init(devicename = name)
            self._playback_device_name = name 
            pygame.mixer.init()

    def playbackDevice(self) -> str:
        return self._playback_device_name
    
    def setDefaultPlaybackDevice(self):
        ''' sets the playback device to system default '''
        device = self.getDefaultAudioDevice()
        self.setPlaybackDevice(device.description())

    def soundStart(self):
        # reset the mixer
        self.soundStop()
        if not pygame.mixer.get_init():
            pygame.mixer.init()



    def soundStop(self):
        ''' terminate the mixer '''
        if pygame.mixer.get_init():
            pygame.mixer.stop() # stop playing whatever is being played now
            pygame.mixer.quit() # we will re-init the mixer later


    def getSoundKey(self, sound_file) -> int:
        ''' registers a sound file and returns a key '''
        if os.path.isfile(sound_file):
            sound_file = sound_file.casefold()
            if not sound_file in self.sound_file_map:
                key = gremlin.util.get_guid() # self._next_key
                self.sound_file_map[sound_file] = key
            else:
                key = self.sound_file_map[sound_file]

            self.sound_audio_file_map[key] = sound_file
            
            sound = pygame.mixer.Sound(sound_file)
            self.sound_map[key] = sound
            return self.sound_file_map[sound_file]
        
        return None
    
    def releaseSoundKey(self, sound_file):
        
        sound_file = sound_file.casefold()
        if sound_file and sound_file in self.sound_file_map:
            sound = self.sound_file_map[sound_file]
            self.sound_file_map[sound_file] = None
            pygame.mixer.stop()
            del sound
            del self.sound_file_map[sound_file]
    
    def queueAction(self, action : SoundEvent):
        ''' queues a sound action '''
        
        self._event_queue.put(action)
        if not self._is_running:
            self.start() # ensure started

    def queueActions(self, actions : list[SoundEvent]):
        ''' queues multiple sound actions '''
        self._is_paused = True # pause sound processing
        for action in actions:
            self._event_queue.put(action)
        self._is_paused = False # resume processing
        if not self._is_running:
            self.start() # ensure started
        
    def clearQueue(self):
        ''' clears pending sound actions '''
        self._is_paused = True # pause processing
        while not self._event_queue.empty():
            self._event_queue.get()
            self._event_queue.all_tasks_done()
        self._is_paused = False # resume processing
            

    def _queue_runner(self):
        ''' processes the sound queue '''
        verbose = gremlin.config.Configuration().verbose_mode_sound
        current_device_name = None
        

        while self._is_running:
            if self._is_paused:
                # pause processing 
                time.sleep(0.01)
                continue
                
            if self._event_queue.empty():
                time.sleep(0.01)
                continue

            event : SoundEvent = self._event_queue.get()
            if verbose: syslog.info(f"SOUNDLISTEN: DEQUEUE event {event.action.name}  QUEUE size: {self._event_queue.qsize():,}")		
            if pygame.mixer.get_init() is None:
                if self._playback_device_name:
                    pygame.mixer.pre_init(devicename=self._playback_device_name)
                pygame.mixer.init()
            match event.action:
                case SoundAction.Play:
                    # play item
                    key = event.key
                    if verbose: syslog.info(f"\tplay [{key}]")
                    data : PlaybackOptions = event.data
                    if key in self.sound_map:
                        sound = pygame.mixer.Sound(self.sound_audio_file_map[key])
                        #sound : pygame.mixer.Sound = self.sound_map[key]
                        if data.stop_previous:
                            # stop previous sounds
                            pygame.mixer.stop()
                        if data.volume is not None:
                            volume = data.volume
                            sound.set_volume(volume)
                        if data.fadeout_ms:
                            sound.fadeout(data.fadeout_ms)
                        sound.play(data.loops,data.playback_ms, data.fadein_ms)
                        self._event_queue.task_done()

                case SoundAction.SetVolume:
                    key = event.key
                    if key in self.sound_map:
                        if verbose: syslog.info(f"\tset volume [{key}] volume: {event.data:0.3f}")
                        sound : pygame.mixer.Sound = self.sound_map[key]
                        volume = event.data
                        self.sound_volume_map[key] = volume
                        self._event_queue.task_done()

                case SoundAction.ChangeDevice:
                    device_name = event.data

                    if current_device_name != device_name:
                        if verbose: syslog.info(f"\tchange device [{device_name}]")
                        self.setPlaybackDevice(device_name)
                        current_device_name = device_name
                        self._playback_device_name = device_name
                        self._event_queue.task_done()

                case SoundAction.Stop:
                    # clear the queue and stop playback
                    if verbose: syslog.info(f"\tstop")
                    pygame.mixer.stop()
                    self._event_queue.task_done()        
                    while not self._event_queue.empty():
                        self._event_queue.get()
                        self._event_queue.task_done()        



            

