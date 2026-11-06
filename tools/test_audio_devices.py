"""Audio/voice checks without hardware, recognition models, or network access.

Run: python tools/test_audio_devices.py
"""

import ast
import gc
import logging
import os
from pathlib import Path
import queue
import sys
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from PySide6 import QtCore, QtWidgets
from sounddevice import PortAudioError

from test_qt_marshalling import APP, flush_deletes


ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger("audio-device-checks")
LOGGER.addHandler(logging.NullHandler())
LOGGER.propagate = False


def load_class(path, name, methods, namespace, base=None):
    tree = ast.parse((ROOT / path).read_bytes())
    node = next(node for node in tree.body if getattr(node, "name", None) == name)
    node.decorator_list = []
    if base:
        node.bases = [ast.Name(id=base, ctx=ast.Load())]
    node.body = [member for member in node.body if getattr(member, "name", None) in methods]
    nodes = ast.parse("from __future__ import annotations").body + [node]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), path, "exec"), namespace)
    return namespace[name]


class MonitoredInput(QtCore.QObject):
    volumeChanged = QtCore.Signal(float)


class AudioDeviceTests(unittest.TestCase):
    def setUp(self):
        self.capture = None
        self.output = None
        self.sd = NS(
            PortAudioError=PortAudioError, default=NS(device=(-1, -1)),
            query_devices=Mock(side_effect=self.query_devices),
            query_hostapis=Mock(return_value={"name": "Windows WASAPI"}),
            _terminate=Mock(), _initialize=Mock(), InputStream=Mock(),
        )
        self.config = NS(verbose_mode_tts=False, verbose_mode_sound=False, startup_voice_enabled=True)
        self.media = NS(audioInputs=Mock(return_value=[]), defaultAudioInput=Mock(return_value=NS(isNull=lambda: True)))
        self.audio_input = Mock(side_effect=lambda device, parent: MonitoredInput(parent))
        self.namespace = dict(
            sd=self.sd, syslog=LOGGER, USE_SD=True, USE_PG=False,
            threading=threading, queue=queue, gc=gc, time=time, os=os, sys=sys,
            importlib=NS(util=NS(find_spec=Mock(return_value=None))),
            concurrent=NS(futures=NS(ThreadPoolExecutor=Mock())),
            SoundMonitor=Mock(), PhraseDataManager=Mock(), FastQueue=queue.Queue,
            gremlin=NS(config=NS(Configuration=lambda: self.config),
                       event_handler=NS(EventListener=Mock()),
                       util=NS(assert_ui_thread=Mock())),
            QtCore=QtCore, QtWidgets=QtWidgets, QMediaDevices=self.media, QAudioInput=self.audio_input,
            DEFAULT_AUDIO_DEVICE_INDEX=-1, DEFAULT_AUDIO_DEVICE_MARKER="__default__",
            VoicePTTMode=NS(Off="off", Toggle="toggle"),
        )
        self.sound_class = load_class("gremlin/sound.py", "Sound", {
            "__init__", "_update_devices", "pushPlaybackEnabled", "popPlaybackEnabled",
            "getDefaultAudioDeviceName", "getDefaultInputDevice", "getDefaultInputDeviceIndex", "_ensure_device",
            "_handle_shutdown", "_handle_device_changed", "_handle_config_option_changed",
        }, self.namespace)
        self.voice_class = load_class("gremlin/voice.py", "Voice", {
            "start", "_listen_runner", "_capture_audio", "_get_qmedia_device", "_get_volume_ui", "_on_recognized",
        }, self.namespace)
        self.data_class = load_class("gremlin/ui/voice_device.py", "VoiceData", {
            "getDefaultAudioDevice", "getAudioDevice", "getAudioDeviceIndex", "getAudioDevices", "getAudioDevicePairs",
            "setAudioDeviceName",
        }, self.namespace)
        self.dialog_class = load_class(
            "gremlin/ui/voice_device.py", "VoiceSettingsDialog", {
                "start", "stop", "_update_ui", "_get_target_device", "_update_volume_monitor", "_update_volume",
                "_handle_system_volume_changed", "_update_view_meter", "voice_data",
            }, {**self.namespace, "Widget": QtWidgets.QWidget}, base="Widget",
        )

    def query_devices(self, device=None, kind=None):
        if kind == "input":
            if self.capture is None:
                raise PortAudioError("Error querying device -1")
            return self.capture
        if kind == "output":
            if self.output is None:
                raise PortAudioError("Error querying device -1")
            return self.output
        if device == -1:
            raise PortAudioError("Error querying device -1")
        return [device for device in (self.capture, self.output) if device is not None]

    def microphone(self):
        return dict(name="Microphone", index=3, hostapi=0, max_input_channels=1,
                    max_output_channels=0, default_samplerate=48000)

    def sound(self):
        return self.sound_class()

    def voice(self):
        voice = self.voice_class()
        voice._listening = False
        voice._model_valid = True
        voice._model_size = "tiny"
        voice._suspend_stack = 0
        voice._voice_lock = threading.RLock()
        voice._abort_event = threading.Event()
        voice._listen_thread = None
        voice._rolling_matcher = Mock()
        voice.verbose = False
        voice.ensureModel = Mock()
        voice.getCommands = Mock(return_value=[NS(words=["test"])])
        voice.recognizer = Mock()
        voice.pushRecognize = Mock()
        voice.popRecognize = Mock()
        voice.setListen = Mock()
        voice.stop = Mock()
        voice.audioMonitor = Mock()
        voice.getVolume = Mock(return_value=-1)
        self.namespace.update(
            SpeechAudioProcessor=Mock(), SpeechRecognizer=Mock(return_value=voice.recognizer),
            SAMPLE_RATE=16000, BLOCKSIZE=1600, np=NS(float32="float32"),
            threading=NS(Event=threading.Event, Thread=Mock(), RLock=threading.RLock),
        )
        return voice

    def data(self, sound):
        data = self.data_class()
        data._sound = sound
        data._device_name = data._device_index = None
        return data

    def dialog(self, voice=None):
        dialog = self.dialog_class()
        self.addCleanup(flush_deletes)
        self.addCleanup(dialog.deleteLater)
        dialog._voice_data = self.data(self.sound())
        dialog._voice = voice or self.voice()
        dialog._started = False
        dialog._monitored_input = None
        dialog._last_monitored_device = None
        dialog._device_name = None
        dialog._input_selector = QtWidgets.QComboBox(dialog)
        dialog._input_selector.addItem("Default device", -1)
        dialog._default_name_widget = QtWidgets.QLabel(dialog)
        dialog._monitor_button = QtWidgets.QPushButton(dialog)
        dialog._monitor_button.setCheckable(True)
        dialog._volume_widget = QtWidgets.QSlider(dialog)
        dialog._ptt_input_container = QtWidgets.QWidget(dialog)
        dialog._mode = "press"
        return dialog

    def test_sound_initializes_without_any_audio_hardware(self):
        sound = self.sound()
        self.assertTrue(sound._initialized)
        self.assertIsNone(sound._playback_device_name)
        self.assertEqual(sound.device_map, {})
        self.assertEqual(sound.input_device_map, {})
        self.assertIsNone(sound.getDefaultInputDevice())
        self.assertIsNone(sound.getDefaultInputDeviceIndex())

    def test_output_lookup_can_recover_after_hardware_appears(self):
        sound = self.sound()
        self.output = dict(name="Speakers", index=4)
        self.assertEqual(sound.getDefaultAudioDeviceName(), "Speakers")

    def test_stale_configured_output_name_is_unavailable(self):
        self.sd.query_devices.side_effect = ValueError("No output device matching old speakers")
        sound = self.sound_class.__new__(self.sound_class)
        self.assertIsNone(sound.getDefaultAudioDeviceName())

    def test_default_name_still_matches_the_wasapi_device(self):
        sound = self.sound()
        sound.device_name_to_id_map = {"Speakers (USB Audio)": 4}
        self.output = {"name": "Speakers"}
        self.assertEqual(sound.getDefaultAudioDeviceName(), "Speakers (USB Audio)")

    def test_voice_data_handles_output_only_machine(self):
        self.output = dict(name="Speakers", index=4, hostapi=0, max_input_channels=0,
                           max_output_channels=2, default_samplerate=48000)
        data = self.data(self.sound())
        self.assertIsNone(data.getDefaultAudioDevice())
        self.assertIsNone(data.getAudioDevice())
        self.assertEqual(data._device_index, -1)
        self.assertEqual(data.getAudioDeviceIndex(), -1)
        self.assertEqual(data.getAudioDevicePairs(), [])

    def test_rescan_removes_disconnected_capture_devices(self):
        self.capture = self.microphone()
        sound = self.sound()
        self.assertEqual(sound.input_device_map, {3: "Microphone"})
        self.capture = None
        sound.soundStop = Mock()
        sound._update_devices()
        self.assertEqual(sound.input_device_map, {})
        self.assertEqual(sound.input_device_name_to_id_map, {})

    def test_voice_start_skips_models_and_threads_without_capture_hardware(self):
        voice = self.voice()
        self.assertFalse(voice.start())
        self.assertFalse(voice._listening)
        voice.ensureModel.assert_not_called()
        self.namespace["SpeechRecognizer"].assert_not_called()
        self.namespace["threading"].Thread.assert_not_called()

    def test_stale_configured_input_name_does_not_raise(self):
        sound = self.sound()
        self.sd.query_devices.side_effect = ValueError("No input device matching old microphone")
        self.assertIsNone(sound.getDefaultInputDevice())
        voice = self.voice()
        self.assertFalse(voice.start())
        voice.ensureModel.assert_not_called()

    def test_voice_start_retries_when_capture_hardware_appears(self):
        voice = self.voice()
        self.assertFalse(voice.start())
        self.capture = self.microphone()
        self.assertTrue(voice.start())
        voice.ensureModel.assert_called_once()
        voice.recognizer.start.assert_called_once()
        self.namespace["threading"].Thread.return_value.start.assert_called_once()

    def test_disconnected_microphone_stops_the_voice_workers(self):
        voice = self.voice()
        voice._listening = True
        self.sd.InputStream.side_effect = PortAudioError("Device was disconnected")
        voice._listen_runner(voice._abort_event)
        self.assertFalse(voice._listening)
        self.assertTrue(voice._abort_event.is_set())
        voice.recognizer.stop.assert_called_once()
        voice._rolling_matcher.stop.assert_called_once()

    def test_null_qt_capture_device_has_no_volume(self):
        voice = self.voice()
        self.assertEqual(voice._get_volume_ui(), -1)
        self.audio_input.assert_not_called()

    def test_settings_without_microphone_show_unavailable_controls(self):
        dialog = self.dialog()
        dialog._update_ui()
        dialog._update_volume()
        dialog._update_volume_monitor()
        self.assertIn("No audio capture device", dialog._default_name_widget.text())
        self.assertFalse(dialog._monitor_button.isEnabled())
        self.assertFalse(dialog._volume_widget.isEnabled())
        self.assertIsNone(dialog._monitored_input)
        self.audio_input.assert_not_called()

    def test_failed_monitor_start_unchecks_button_and_restores_recognition(self):
        dialog = self.dialog()
        dialog._monitor_button.setChecked(True)
        dialog.start()
        self.assertFalse(dialog._started)
        self.assertFalse(dialog._monitor_button.isChecked())
        dialog._voice.pushRecognize.assert_called_once()
        dialog._voice.popRecognize.assert_called_once()
        dialog._voice.setListen.assert_not_called()
        dialog._voice.audioMonitor.connect.assert_not_called()

    def test_valid_capture_device_still_resolves_and_enables_monitoring(self):
        self.capture = self.microphone()
        dialog = self.dialog()
        dialog._update_ui()
        dialog._update_volume_monitor()
        self.assertEqual(dialog._get_target_device(), "Microphone")
        self.assertTrue(dialog._monitor_button.isEnabled())
        self.assertEqual(dialog._voice_data.getAudioDeviceIndex(), 3)
        dialog._voice_data.setAudioDeviceName("micro", validate=True)
        self.assertEqual(dialog._voice_data._device_index, 3)

    def test_valid_monitor_start_and_stop_keep_signal_connections_balanced(self):
        self.capture = self.microphone()
        self.media.audioInputs.return_value = [NS(description=lambda: "Microphone")]
        dialog = self.dialog()
        dialog._update_volume_monitor()
        dialog.start()
        self.assertTrue(dialog._started)
        self.assertIsNotNone(dialog._monitored_input)
        self.assertEqual(self.audio_input.call_count, 1)
        dialog.stop()
        self.assertFalse(dialog._started)
        self.assertIsNone(dialog._monitored_input)
        dialog._voice.popRecognize.assert_called_once()
        dialog.start()
        self.assertTrue(dialog._started)
        self.assertEqual(self.audio_input.call_count, 2)
        dialog.stop()


if __name__ == "__main__":
    unittest.main()
