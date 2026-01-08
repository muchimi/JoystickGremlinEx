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

from __future__ import annotations
import os
from PySide6 import QtCore, QtGui, QtMultimedia, QtWidgets
from lxml import etree as ElementTree
import qtawesome as qta
import gremlin.util
import gremlin.event_handler


import gremlin.config


from gremlin.util import load_icon, userprofile_path

import gremlin.ui.ui_common
import threading

from gremlin.util import safe_format, safe_read
import logging
from psygnal import Signal

import gremlin.singleton_decorator
import queue
import enum
import time

syslog = logging.getLogger("system")

USE_SD = True # use sound device for playback
USE_QT = False # use QT for playback
USE_PG = False # use pygame for playback

if USE_PG:
    import pygame
    
import scipy
import scipy._cyutility

if USE_SD:
    import sounddevice as sd # for sound playback
    import soundfile as sf # for reading sound files as numpy data
    import numpy as np # for sound device library
    import concurrent.futures # for thread pool of concurrent playback
    import pyrubberband as pyrb # for sound sample rate modification 
 
    from scipy import signal # for audio resampling if needed


class SoundAction(enum.Enum):
    Play = 1 # play a sound key using the options previously selected
    ChangeDevice = 2 # change the audio output device 
    SetVolume = 3 # set teh volume on a sound key
    Stop = 4 # stop playback


class PlaybackOptions():
    ''' holds sound playback options '''
    def __init__(self, key : str, device : str = None, loops : int = 1, volume : float = None, playback_ms : int = 0, fadein_ms : int = 0, fadeout_ms : int = 0, stop_previous : bool = False, rate : float = None):
        ''' playback options 
        
        :param key: the sound file key as registered with the sound module (getSoundKey())
        :param loops: count of playback loops.  0 means no playback. 
        :param volume: volume 0 to 1, leave None for default volume
        :param playback_ms: time for the playback in milliseconds, 0 to disable.  If provided, plays the sound only for the specified number of milliseconds.
        :param fadein_ms: time in milliseconds for the time for the sound to fade in - if the sound is too short, it may never reach max volume
        :param fadeout_ms: time in milliseconds for the time for the sound to fade out
        '''
        self.key = key # this is a GUID for PG mode, and the file name for SD mode
        self.device : str = device # playback device - if not set - default playback is used
        if USE_PG:
            self.loops = loops - 1 if loops > 0 else 0 # sounds plays once, loops are extra repeats
        elif USE_SD:
            self.loops = loops
        self.volume = volume
        self.playback_ms = playback_ms # this only works for PG mode
        self.fadein_ms = fadein_ms # this only works for PG mode
        self.fadeout_ms = fadeout_ms # this only works for PG mode
        self.stop_previous = stop_previous
        self.rate = rate # playback rate (1.0 = normal)


class SoundEvent():
    ''' single commands for the queue '''
    def __init__(self, action : SoundAction, key : str = None,  data = None):
        self.key = key
        self.data = data
        self.action = action

    @staticmethod
    def PlayAction(key : str, device : str, loops : int = 1, volume : float = None, playback_ms : int = 0, fadein_ms : int = 0, fadeout_ms : int = 0, stop_previous : bool = False, rate : float = 1.0):
        data = PlaybackOptions(key, device, loops, volume, playback_ms, fadein_ms, fadeout_ms, stop_previous, rate)
        return SoundEvent(action = SoundAction.Play, key = key, data = data)
    
    @staticmethod
    def ChangeDeviceAction(device_name : str):
        return SoundEvent(action = SoundAction.ChangeDevice, data = device_name)
    
    @staticmethod
    def SetVolumeAction(key : str, volume : int):
        return SoundEvent(action = SoundAction.SetVolume, key = key, data = volume / 100)
    
    @staticmethod
    def StopAction():
        return SoundEvent(action = SoundAction.Stop)
    
# class SoundData():
#     ''' holds compiled sound data for SD mode '''
#     def __init__(self, filename : str, device_id: int, options : PlaybackOptions, data, ):
#         self.filename = filename
#         self.device_id = device_id
#         self.data = data
#         self.id = gremlin.util.get_guid() # unique record id
#         self.options = options




@gremlin.singleton_decorator.SingletonDecorator
class Sound():
    ''' wrapper class to play sounds via pygame and QT multimedia '''
    def __init__(self):
        
        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self._handle_shutdown)

        self._playback_device_name = None
        
        if USE_SD:
            # use sound device library
            self.device_map = {}
            self.device_name_to_id_map = {}
            self.device_sample_rate_map = {}
            self.running_data = {} # data for running audio streams
            self._playback_enabled = True # enable playback
            self._sound_tasks = [] # tracks sound tasks
            
            
            device_list = sd.query_devices()
            
            for device  in device_list:
                if device['max_output_channels'] > 0:
                    name = device['name']
                    index = device['index']
                    api_id = device['hostapi']
                    api = sd.query_hostapis(device['hostapi'])
                    api_name = api['name']
                    samplerate = device['default_samplerate']

                    syslog.info(f"API: [{name}] [{api_name}] id: [{api_id}] sample rate: [{samplerate}] ")
                    if api_name == 'Windows WASAPI':
                        # only use wasapi as that has the lowest latency
                        # other choices are 'MME'
                        # 'Windows DirectSound'
                        self.device_map[index] = name
                        self.device_name_to_id_map[name] = index
                        self.device_sample_rate_map[index] = samplerate


            # get the default device
            device = sd.query_devices(kind='output')
            name = device['name']
            if not name in self.device_name_to_id_map:
                # different API - match by starting name
                for device_name in self.device_name_to_id_map:
                    if device_name.startswith(name):
                        name = device_name
                        break

            self._playback_device_name = name


            self.pool = concurrent.futures.ThreadPoolExecutor() # supports mutliple concurrent audio threads

        else:
            # list of devices from QT multimedia
            devices = QtMultimedia.QMediaDevices.audioOutputs()
            self.device_map = {index:device for index, device in enumerate(devices)}
            # flip the device map
            self.device_name_to_id_map = {id:name for id,name in self.device_map.items()}
        
        
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

        if USE_PG:
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

    def ensureStarted(self) -> bool:
        ''' makes sure the mixer is started - returns true if initialized '''
        self.start()        
        if USE_PG:
            if not pygame.mixer.get_init():
                try:
                    if not self._playback_device_name:
                        syslog.error(f"SOUND: Unable to initialize sound: device not selected.")
                        return False
                    
                    pygame.mixer.pre_init(self._playback_device_name)
                    pygame.mixer.init()
                except Exception as ex:
                    syslog.error(f"SOUND: Unable to initialize sound: {str(ex)}")
                    return False
        return True

            

    def _handle_shutdown(self):
        self.stop() # stop the runner
        self.soundStop() 
        self.device_map.clear()
        self.device_name_to_id_map.clear()
        if USE_PG:
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
    
    def findDeviceIndex(self, name : str):
        ''' gets the device index for a specific device name '''
        if name in self.device_name_to_id_map:
            return self.device_name_to_id_map[name]
        return None
    
        # index = next((i for i, d in self.device_map.items() if d.description() == name),None) 
        # return index

    def getAudioDevice(self):
        ''' gets the audio device to play from '''
        
        default_audio_device = self.getDefaultAudioDevice()
        
        if self.audio_device:
            device = next((d for d in self.device_map.values() if d.description() == self.audio_device), default_audio_device) 
        else:
            device = default_audio_device
        return device
    
    def getDefaultAudioDevice(self) -> str:
        if USE_SD:
            return sd.default.device
        
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
            if USE_PG:
                if pygame.mixer.get_init():
                    # stop the mixer so we can change the device
                    pygame.mixer.stop()
                    pygame.mixer.quit()
                
                pygame.mixer.pre_init(devicename = name)
                pygame.mixer.init()

            if USE_SD:
                sd.default.device = name
            
            self._playback_device_name = name 
            

    def playbackDevice(self) -> str:
        return self._playback_device_name
    
    def setDefaultPlaybackDevice(self):
        ''' sets the playback device to system default '''
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
            self._playback_enabled = True

    def soundStop(self):
        ''' terminate any active playbacks '''
        if USE_PG:
            if pygame.mixer.get_init():
                pygame.mixer.stop() # stop playing whatever is being played now
                pygame.mixer.quit() # we will re-init the mixer later
        elif USE_SD:
            # terminate the thread pools
            self._playback_enabled = False # stop all streams
            # wait for all the tasks to be completed
            while self._sound_tasks:
                self._task_trim()
                time.sleep(0.01)
            self._playback_enabled = True # renable once all streams are done

    def _task_trim(self):
        ''' trims the task list of completed tasks '''
        if self._sound_tasks:
            done_list = [t for t in self._sound_tasks if t.done()]
            self._sound_tasks = [t for t in self._sound_tasks if not t in done_list]
        


    def play(self, filename : str, options : PlaybackOptions):
        ''' plays a sound file via SD low level library '''
        try:
            if not self._playback_enabled:
                # playback is not enabled
                return
            
            self._task_trim() # cleanup prior tasks
            
            device_name = options.device # playback device name
            loops = options.loops # number of loops to play

            if device_name:
                if device_name in self.device_name_to_id_map:
                    device_id = self.device_name_to_id_map[device_name]
                    device_samplerate = self.device_sample_rate_map[device_id]
            else:
                # get the current default device
                device = sd.query_devices(kind='output')
                device_id = device['index']
                device_samplerate = device['default_samplerate']
                device_name = device['name']

            # process the audio file
            with sf.SoundFile(filename) as f:
                data = f.read(dtype='float32', always_2d=True) # default is 64bit, change to 32bit floats
                samplerate = f.samplerate # audio file sample rate in hertz 
                channels = f.channels # 1 for mono, 2 for stereo (usual)
                

        
        
            
            rate = options.rate # playback rate (pitch corrected)
            volume = options.volume # volume to apply
            fade_in = options.fadein_ms # fade in duration
            fade_out = options.fadeout_ms # fade out duration
            duration = options.playback_ms # max duration of the sample to play back
            verbose = gremlin.config.Configuration().verbose_mode_sound

            fade_in = 0
            fade_out = 0



            #data, samplerate = sf.read(filename, dtype='float32')

            # resample the audio to match the device sample rate

            if device_samplerate != samplerate:
                # determin how many new samples are needed 
                new_sample_count = int(len(data) * device_samplerate / samplerate)

                # 3. Resample the audio data using scipy.signal.resample
                resampled_audio = signal.resample(data, new_sample_count)

                # Ensure data type is compatible with sounddevice (e.g., float32)
                data = np.array(resampled_audio, dtype='float32')


            total_frames = len(data)

            # modify the playback rate if requested maintaining the pitch (this is approximate)
            if rate is not None and rate != 1.0:
                # this maintains pitch using pyrubberband
                data = pyrb.time_stretch(data, samplerate, rate)


            # modify the playback duration if requested (this will make the sample shorter only)
            if duration is not None and duration > 0:
                duration_seconds = duration / 1000 # to seconds
                frame_count = int(duration_seconds * samplerate) 
                if total_frames > frame_count:
                    # trim needed
                    data = data[:frame_count]


            # modify the playback volume 
            if volume is not None and volume >= 0:
                data = data * (volume / 100) # convert percent to volume.  50% = 0.5 = half volume                    

            # apply a fade in ramp if requested
            if fade_in is not None and fade_in > 0:
                duration_seconds = fade_in / 1000
                frame_count = int(duration_seconds * samplerate)
                # creates vector ramp from 0.0 to 1.0 volume over the fade duration
                fade_ramp = np.linspace(0.0, 1.0, frame_count)
                multiplier = np.ones(total_frames)
                multiplier[-len(fade_ramp):] = fade_ramp

                if data.ndim > 1: # Stereo
                    data = (data * multiplier[:, np.newaxis]).astype(data.dtype)
                else: # Mono
                    data = (data * multiplier).astype(data.dtype)

            # apply a fade out ramp if requested
            if fade_out is not None and fade_out > 0:
                duration_seconds = fade_out / 1000
                frame_count = int(duration_seconds * samplerate) 
                # creates vector ramp from 1.0 to 0.0 volume
                fade_ramp = np.linspace(1.0, 0.0, frame_count)
                multiplier = np.ones(total_frames)
                multiplier[-len(fade_ramp):] = fade_ramp

                if channels > 1: # Stereo
                    data = (data * multiplier[:, np.newaxis]).astype(data.dtype)
                else: # Mono
                    data = (data * multiplier).astype(data.dtype)

            # cache the playback data
            
            if not filename in self.running_data:
                self.running_data[filename] = {}


            task = self.pool.submit(self._play_runner, data, device_id, loops)
            self._sound_tasks.append(task)
            
        
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
                    outdata[:chunksize] = data[current_frame:current_frame + chunksize]
                    if chunksize < frames or not self._playback_enabled:
                        # terminate playback on last frame or playback abort
                        outdata[chunksize:] = 0
                        event.set()
                    current_frame += chunksize

                stream = sd.OutputStream(callback=callback, device=device_id, finished_callback=event.set, channels=data.ndim)
                with stream:
                    event.wait()  # wait until playback is finished

            #syslog.info(f"playback done")


        except sd.CallbackStop:
            event.set()
        except Exception as e:
            syslog.error(f"SOUND: PLAY: An error occurred: {e}")
                        
    

    def getSoundKey(self, sound_file) -> int:
        ''' registers a sound file and returns a key '''
        if os.path.isfile(sound_file):
            sound_file = sound_file.casefold()
            if USE_PG:
                if not sound_file in self.sound_file_map:
                    key = gremlin.util.get_guid() # self._next_key
                    self.sound_file_map[sound_file] = key
                else:
                    key = self.sound_file_map[sound_file]

                self.sound_audio_file_map[key] = sound_file
                
                sound = pygame.mixer.Sound(sound_file)
                self.sound_map[key] = sound
                return self.sound_file_map[sound_file]
            if USE_SD:
                # use the filename as the key for SD playback
                return sound_file 
        
        return None
    
    def releaseSoundKey(self, sound_file):
        if USE_PG:
            sound_file = sound_file.casefold()
            if sound_file and sound_file in self.sound_file_map:
                sound = self.sound_file_map[sound_file]
                self.sound_file_map[sound_file] = None
                pygame.mixer.stop()
                del sound
                del self.sound_file_map[sound_file]
    
    def queueAction(self, action : SoundEvent):
        ''' queues a sound action - PG mode only'''
        self._event_queue.put(action)
        if not self._is_running:
            self.start() # ensure started

    def queueActions(self, actions : list[SoundEvent]):
        ''' queues multiple sound actions  - PG mode only'''
        self._is_paused = True # pause sound processing
        for action in actions:
            self._event_queue.put(action)
        self._is_paused = False # resume processing
        if not self._is_running:
            self.start() # ensure started
        
    def clearQueue(self):
        ''' clears pending sound actions  - PG mode only'''
        self._is_paused = True # pause processing
        while not self._event_queue.empty():
            self._event_queue.get()
            self._event_queue.all_tasks_done()
        self._is_paused = False # resume processing
            

    def _queue_runner(self):
        ''' processes the sound queue - PG mode onlyt '''
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
            if USE_PG:
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
                    if USE_SD:
                        self.play(key, data)
                    elif USE_PG:
                        if key in self.sound_map:
                            audio_file = self.sound_audio_file_map[key]
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
                    if USE_PG:
                        key = event.key
                        if key in self.sound_map:
                            if verbose: syslog.info(f"\tset volume [{key}] volume: {event.data:0.3f}")
                            sound : pygame.mixer.Sound = self.sound_map[key]
                            volume = event.data
                            self.sound_volume_map[key] = volume
                    self._event_queue.task_done()

                case SoundAction.ChangeDevice:
                    if USE_PG:
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
                    if USE_PG:
                        pygame.mixer.stop()
                    elif USE_SD:
                        sd.stop()

                    self._event_queue.task_done()    

                    # clear the rest of the queue    
                    while not self._event_queue.empty():
                        self._event_queue.get()
                        self._event_queue.task_done()        



class TTSGeneratorDialog(QtWidgets.QDialog):
    ''' generic dialog box audio generator '''
    def __init__(self, parent=None):
        super().__init__(parent = parent)
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

        text_container = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True)
        self.main_layout.addWidget(text_container)



        widgets = []

        self.speaker_widget = gremlin.ui.ui_common.QDataComboBox(auto_adjust=True, tooltip = "Selected speaker for AI voice generation.")
        widgets.append(self.speaker_widget)


        self.tts_speed_widget = gremlin.ui.ui_common.QFloatLineEdit(min_range = 0.1, max_range = 10.0, value = self.tts_speed, callback = self._handle_tts_speed_changed, tooltip = "Speed rate modifier for the generated audio.\n1.0 is the normal rate.")


        widget = gremlin.ui.ui_common.QDataCheckbox("Overwrite existing filenames",
                                                    value = config.ai_tts_overwrite_filenames, 
                                                    callback = self._handle_overwrite_filename_changed,
                                                    tooltip = "Use the input text as the file name for the generated audio file.\nIf not set, a unique GUID will be used." 
                                                    )
        widgets.append(widget)



        options_container = gremlin.ui.ui_common.getVContainer(widgets, widget_only = True)
        self.main_layout.addWidget(options_container)

        generate_widget = gremlin.ui.ui_common.QDataPushButton("Generate", callback = self._handle_generate)
        close_widget = gremlin.ui.ui_common.QDataPushButton("Close", callback = self._handle_close)
        open_widget = gremlin.ui.ui_common.QDataPushButton("Open folder", callback = self._handle_open_folder)


        widgets = [generate_widget,open_widget,close_widget]
        button_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True, left_stretch=True)
        self.main_layout.addWidget(button_container)

        # initialize AI and load speaker list
        self._update_speakers(initialize = True)
        self.speaker_widget.setCallback(self._handle_speaker_changed)
        
    def _handle_close(self, widget):
        self.close()

    def _handle_open_folder(self, widget):
        ''' opens the sound folder '''
        ktts = gremlin.ktts.KTTS()
        folder = ktts.getSoundFolder()
        gremlin.util.create_folder(folder) # create if it doesn't exist yet
        gremlin.util.open_folder(folder)

    def _handle_tts_speed_changed(self, value : float):
        self.tts_speed = value

    def _handle_speaker_changed(self, value):
        self.speaker = value
        config = gremlin.config.Configuration()
        config.ai_tts_last_speaker = value

    def _update_speakers(self, initialize = True):
        config = gremlin.config.Configuration()
        last_speaker = config.ai_tts_last_speaker
        if not self.speaker:
            # default speaker is the last one if we have one defined
            self.speaker = last_speaker

        ktts = gremlin.ktts.KTTS()
        try:
            gremlin.util.pushCursor()
            speakers = ktts.getSpeakers(initialize = initialize)
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
        finally:
            gremlin.util.popCursor()


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

    def _handle_overwrite_filename_changed(self, checked):
        config = gremlin.config.Configuration()
        config.ai_tts_overwrite_filenames = checked        

    def _handle_generate(self, widget):
        ''' generate the audio files '''
        import gremlin.ktts
        import gremlin.config
        import gremlin.util

        speaker = self.speaker
        tts_speed = self.tts_speed

        text = self.text_field.toPlainText()
        if not text:
            return # nothing to do
        config = gremlin.config.Configuration()
        overwrite = config.ai_tts_overwrite_filenames

        lines = text.splitlines()
        ktts = gremlin.ktts.KTTS()
        wav = ktts.getNewWav()
        ext = gremlin.util.get_ext(wav)
        dir = os.path.dirname(wav)

        ui = gremlin.shared_state.ui
        count = len(lines)
        progress_dialog = QtWidgets.QProgressDialog("Generating audio", "", 0, count, parent = ui)
        progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
        progress_dialog.setAutoClose(True)
        progress_dialog.setMinimumDuration(0) # Show immediately
        progress_dialog.setCancelButton(None) # no cancel button
        time.sleep(0.05) 
        QtWidgets.QApplication.processEvents() # Process events to keep the UI responsive
        
        for index, text in enumerate(lines):
            progress_dialog.setValue(index+1)
            time.sleep(0.05) 
            QtWidgets.QApplication.processEvents() # Process events to keep the UI responsive



            suggested_name = gremlin.util.textWordsToUnderscore(text)
            suggested_file = os.path.join(dir, suggested_name)
            fname = gremlin.util.swap_ext(suggested_file,ext)
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
            wav = ktts.generateWav(tts_file = fname, text = text, speaker = speaker, tts_speed = tts_speed)








class GenerateDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent = parent)

        config = gremlin.config.Configuration()

        self.setWindowTitle("Generate AI Options")
        self.setModal(True)
        self.main_layout = QtWidgets.QVBoxLayout(self)

        self.main_layout.addWidget(QtWidgets.QLabel("AI generation options:"))

        widgets = []
        widget = gremlin.ui.ui_common.QDataCheckbox("Save profile on generate",
                                                    value = config.ai_tts_save_on_generate,
                                                    callback = self._handle_save_on_generate_changed,
                                                    tooltip = "Save the profile automatically once the audio file have been generated.")
        widgets.append(widget)

        
        widget = gremlin.ui.ui_common.QDataCheckbox("Use word based filenames",
                                                    value = config.ai_tts_use_word_filenames, 
                                                    callback = self._handle_word_filename_changed,
                                                    tooltip = "Use the input text as the file name for the generated audio file.\nIf not set, a unique GUID will be used." 
                                                    )
        widgets.append(widget)


        widget = gremlin.ui.ui_common.QDataCheckbox("Overwrite existing filenames",
                                                    value = config.ai_tts_overwrite_filenames, 
                                                    callback = self._handle_overwrite_filename_changed,
                                                    tooltip = "Use the input text as the file name for the generated audio file.\nIf not set, a unique GUID will be used." 
                                                    )
        widgets.append(widget)

   
   

        option_container = gremlin.ui.ui_common.getVContainer(widgets, widget_only =True, left_margin=12)
        self.main_layout.addWidget(option_container)

        ok_widget = gremlin.ui.ui_common.QDataPushButton("Ok", callback = self._handle_ok)
        cancel_widget = gremlin.ui.ui_common.QDataPushButton("Cancel", callback = self._handle_cancel)
        widgets = ["||", ok_widget, cancel_widget,"||"]
        button_container = gremlin.ui.ui_common.getHContainer(widgets, widget_only=True)
        self.main_layout.addWidget(button_container)


    def _handle_save_on_generate_changed(self, checked):
        config = gremlin.config.Configuration()
        config.ai_tts_save_on_generate = checked

    def _handle_word_filename_changed(self, checked):
        config = gremlin.config.Configuration()
        config.ai_tts_use_word_filenames = checked

    def _handle_overwrite_filename_changed(self, checked):
        config = gremlin.config.Configuration()
        config.ai_tts_overwrite_filenames = checked


    def _handle_ok(self, widget):
        self.accept()

    def _handle_cancel(self, widget):
        self.reject()
