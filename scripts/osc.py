### JGEX OSC module ###


# OSC server imports

import collections
import logging
import re
import time
from typing import overload, List, Union, Any, Generator, Tuple, Callable, Optional, DefaultDict, Iterator, Union, cast, Coroutine, NamedTuple
import logging
from typing import Any, Iterator, List, Union
import asyncio
from asyncio import BaseEventLoop

import socketserver
import socket
from socket import socket as _socket
import sys
import os
from collections.abc import Iterable
import struct
from datetime import datetime, timedelta, date
from typing import NamedTuple


### gremlin start ------------------------------------------------------- 


import gremlin
import threading
from gremlin.macro import Macro, key_from_name, MacroManager, Key, PauseAction


from util import fire_event

# host IP - change this to your IP address - this cannot usually be localhost or 127.0.0.1 but the actual IP of the machine
# the IP address can be found from a command line by running ipconfig /all  at a C: prompt
host_ip = "192.168.1.59"
# host OSC listen port (UDP) - make sure the host's firewall allows that port in
in_port = 8000
out_port = 8001

PERIODIC = 0.25
osc = None





def GetVjoy():
	''' get the vjoy device (virtual hardware input)'''
	return gremlin.joystick_handling.VJoyProxy()

def log(msg):
    ''' displays a log message in Gremlin and in the console '''
    gremlin.util.log(msg)
    #print(msg)

# async routine to pulse a button
def _fire_pulse(vjoy, unit, button, repeat = 1, duration = 0.2):
	if repeat < 0:
		repeat = -repeat
		for i in range(repeat):
			# gremlin.util.log("Pulsing vjoy %s button %s on" % (unit, button) )    
			vjoy[unit].button(button).is_pressed = True
			time.sleep(duration)
			vjoy[unit].button(button).is_pressed = False
			time.sleep(duration)
	else:
		if repeat <= 1: 
			gremlin.util.log(f"Pulsing vjoy {unit} button {button} on")  
			vjoy[unit].button(button).is_pressed = True
			time.sleep(duration)
			vjoy[unit].button(button).is_pressed = False
		else:
			vjoy[unit].button(button).is_pressed = True
			time.sleep(duration*repeat)
			vjoy[unit].button(button).is_pressed = False        
		
	# gremlin.util.log("Pulsing vjoy %s button %s off" % (unit, button) )

# pulses a button - unit is the vjoy output device number, button is the number of the button on the device to pulse
def pulse(vjoy, unit, button, duration = 0.2, repeat = 1):
	gremlin.util.log(f"pulsing: unit {unit} button {button}")
	threading.Timer(0.01, _fire_pulse, [vjoy, unit, button, repeat, duration]).start()


class Speech():
	''' tts interface '''
	def __init__(self):
		import win32com.client
		self.speaker = win32com.client.Dispatch("SAPI.SpVoice")

	def speak(self, text):
		try:
			self.speaker.speak(text)
		except:
			pass


def speech_handler(address, x):
    ''' handles sending text to speech '''
    splits = address.split("/")
    if len(splits) < 3:
        # not enough data
        return
    speech = splits[2:].pop()
    Speech().speak(speech)



def keyboard_handler(address, x):
    ''' handles keyboard commands - address is already in lowercase '''
    import re
    import itertools
    log(f"KEYBOARD: received {address} {x}")
    splits = address.split("/")
    if len(splits) < 3:
        # not enough data
        return
    
    # remove the command
    splits = splits[2:]
    pattern = re.compile(r"([+|-])|([^[\]\[]+)|(\[[0-9]+\])")
    macro = Macro()
    tail = []
    key_down = False
    key_up = False
    for section in splits:
        # further split each section in keyboard commands
        commands = list(itertools.chain.from_iterable(pattern.findall(section)))
        for token in commands:
            
            if token == "+":
                key_down = True
                continue
            if token == "-":
                key_up = True
                continue

            if token.startswith("["):
                # insert a delay - the square brackets contain the delay in ms
                # strip first and last
                token = token[1:][:-1]
                if token.isnumeric():
                    delay_ms = int(token)
                    macro.pause(delay_ms/1000)
                continue

            key = None

            if token in ("ctr", "lctr", "ctrl","lctrl","leftcontrol"):
                key = "leftcontrol"
            elif token in ("rctr", "rctrl", "rightcontrol"):
                key = "rightcontrol"
            elif token in ("shft","lshft","shift","lshift","leftshift"):
                key = "leftshift"
            elif token in ("rshft", "rshift","rightshift"):
                key = "rightshift"
            elif token in ("alt", "lalt","leftalt"):
                key = "leftalt"
            elif token == "ralt":
                key = "rightalt"
            elif token in ("win","lwin","leftwin"):
                key = "leftwin"
            elif token in ("rwin","rightwin"):
                key = "rightwin"
            elif token in ("pgdn","pagedown"):
                key = "pagedown"
            elif token in ("pgup","pageup"):
                key = "pageup"
            elif token == "slash":
                key = "/"
            else:
                # regular key - output by character
                key = token
            
            if not key:
                # don't know how to handle
                continue
            
            a_list = []
            
            action_key = key_from_name(key, validate = True)
            if not action_key:
                # check for text sequence that are press only without spacers - so wasd would pres w a s d separately
                for c in key:
                    action_key = key_from_name(c, validate = True)
                    if action_key:
                        a_list.append(action_key)
            else:
                a_list = [action_key]
                    
            if a_list:
                for action_key in a_list:
                    if key_down:
                        macro.action(action_key, True)
                    elif key_up:
                        macro.action(action_key, False)
                    else:
                        # press the key
                        macro.action(action_key, True)
                        macro.pause(0.25)
                        # key a release action on the tail end of the macro at the start of the queue (so they are in the correct reverse order)
                        tail.insert(0, action_key)

                key_down = False
                key_up = False
            else:
                # invalid key found
                log(f"OSC Macro error: cannot parse: {key}")
                return

    # append all the release actions
    for key in tail:
        macro.action(key, False)

    # # debug
    # cmd = ''
    # for action in macro.sequence:
    #     if isinstance(action,Key):
    #         cmd += (f"{'+' if action.is_pressed else '-' } {action.key.name} ({action.key.scan_code}) ")
    #     elif isinstance(action,PauseAction):
    #         cmd += f" Pause {action.duration}"
    # log(f"Macro: {cmd}")

    # execute the macro if it contains anything
    if macro.sequence:
        MacroManager().queue_macro(macro)
    

def vjoy_handler(address, args):
    ''' handles vjoy output '''
    # format is /vjoy/command
    #
    # command:
    #   D[device_number]B[R][button_number][R]P[duration]A[axis_number]v[axis_value]
    #  
    #  number: vjoy device number (1 based) so the first device is 1
    #  button_number: button 1 to 128
    #  axis_number: 1 to 8
    #  axis value: -1000 to +1000, floating point values are accepted
    #  R: releases the button instead of pressing it - can be after the B or after the button number or both
    #  P: if provided, indicates the button is pulsed for 250ms (default) - if more than that use the duration in milliseconds, so 500 is half a second
    vjoy = GetVjoy()
    x = 0
    y = 0
    arg_count = len(args)
    if arg_count == 2:
        (x,y) = args
    elif arg_count == 1:
        x = args[0]
    valid = False
    splits = address.split("/")
    if len(splits) == 3:
        # get the last arg
        command = splits.pop()
            
        regex = r'([d]|b[r|p]?|[a]|[v])\s*([+|-]?[0-9]*[.]?[0-9]*[r]?)'
        matches =re.findall(regex, command)

        vjoy_device = 0

        # list of all actions
        actions = []
        axis_actions = []

        # current action
        action = None

        for (item, data) in matches:
            # something got extracted - makes sense of i
            try:
                
                item = item.lower()
                
                release = False
                if  "r" in data:
                    data = data.replace("r","")
                    release = True
                if "r" in item:
                    item = item.replace("r","")
                    release = True
                
                try:
                    value = int(data)
                except:
                    gremlin.util.log(f"Bad number format: {data} - check OSC sequence")
                    # ignore bad data
                    continue
                
                
                if item == "d":
                    vjoy_device = value
                elif item in ("b","bp","br"):
                    # press action
                    action = [vjoy_device, value, not release, False, 0]
                    actions.append(action)

                elif item in ("t","tb"):
                    # toggle button
                    state = vjoy[vjoy_device].button(value).is_pressed
                    action = [vjoy_device, value, not state, False, 0]
                    actions.append(action)
                elif item == "p":
                    if action and action[1]:
                        # action must exist and must be a press action
                        action[3] = True
                        if value <= 0:
                            # make sure it's at least 200 ms to even register
                            value = 200
                        action[4] = value/1000

                elif item == "a":
                    # store the value that comes in at 0 to 1 to range -1 to +1 
                    axis_action = [vjoy_device, value, x*2 - 1]
                    axis_actions.append(axis_action)
                elif item == "v":
                    # sets the axis to a known value -1000 to +1000
                    if axis_action:
                        # current axis action from setup
                        v = float(data)/1000
                        if v > 1.0: 
                            v = 1.0
                        elif v < -1.0: 
                            v = -1.0

                        axis_action[2]= v

                
            except:
                log(f"Unable to parse command: {command}")
                
        
        # process the command
        for (vjoy_device, vjoy_button, is_pressed, is_pulse, duration) in actions:
            if 0 < vjoy_device <= 8 and 0 < vjoy_button <= 128:
                # valid
                if is_pulse:
                    pulse(vjoy, vjoy_device, vjoy_button, duration)
                    log(f"VJOY[{vjoy_device}] button({vjoy_button}): pulse   duration: {duration:0.4f})")
                else:
                    vjoy[vjoy_device].button(vjoy_button).is_pressed = is_pressed
                    log(f"VJOY[{vjoy_device}] button({vjoy_button}): {'press' if is_pressed else 'release'}")

        for (vjoy_device, vjoy_axis, value) in axis_actions:
            if 0 < vjoy_device <= 8 and 0 < vjoy_axis <= 8 and -1.0 <= value <= 1.0:
                vjoy[vjoy_device].axis(vjoy_axis).value = value
                log(f"VJOY[{vjoy_device}] axis({vjoy_axis} value: {value:0.4f})")    


def osc_message_handler(address, *args):
    log(f"OSC: {address}: {args}")
    address = address.lower()
    ESC = "!ESC!"
    try:
        commands = []
        keywords = ["say","key","kbd","knob","vjoy","cmd"]


        if args[0] == 0.0:
            # RELEASE - ignore OSC releases
            return
        
        # check for special characters 
        splits = address.split("/")
        while splits:
            split = splits.pop(0)
            if not split:
                # blank
                continue
            if splits and split in keywords:
                commands.append("/"+split+"/"+splits.pop(0))

        for cmd in commands:
            
            if cmd.startswith("/key") or cmd.startswith("/kbd"):
                # send to keyboard macro handler
                keyboard_handler(cmd, args[0])
            elif cmd.startswith("/say"):
                # send to text to speech handler
                speech_handler(cmd, args[0])
            elif cmd.startswith("/cmd"):
            # call the handler 
                # OSC PRESS 
                commands = address.split("/")
                commands.pop(0)
                for arg in commands:
                    fire_event("cmd", arg)
            else:
                # joystick related
                vjoy = GetVjoy()
                FAST_C = 0.75
                SLOW_C = 0.6
                FAST_CC = 0.25
                SLOW_CC = 0.4
                
                if cmd == "/knob":
                    (x,y) = args

                    # fast clockwise
                    if x > FAST_C:
                        vjoy[3].button(1).is_pressed = False
                        vjoy[3].button(2).is_pressed = True
                    elif x > SLOW_C:
                        vjoy[3].button(1).is_pressed = True
                        vjoy[3].button(2).is_pressed = False
                    if x < FAST_CC:            
                        vjoy[3].button(3).is_pressed = False
                        vjoy[3].button(4).is_pressed = True
                    elif x < SLOW_CC:
                        vjoy[3].button(3).is_pressed = True
                        vjoy[3].button(4).is_pressed = False
                    else:
                        vjoy[3].button(1).is_pressed = False
                        vjoy[3].button(2).is_pressed = False
                        vjoy[3].button(3).is_pressed = False
                        vjoy[3].button(4).is_pressed = False

                elif cmd == "/enc_heading":
                    pass

                elif cmd.startswith("/vjoy"):
                    vjoy_handler(cmd, args)

                    

    except Exception as ex:
        log(F"Command parse error: {ex}")


### OSC handler start ------------------------------------------------------- 
# Adapted from: Python-OSC  https://github.com/attwad/python-osc 
# Credits go to AttWad
# ####

class Osc:


    def thread_loop(self):
        ''' main threading loop '''
        log("OSC: server starting")
        self._dispatcher = Dispatcher()
        self._dispatcher.set_default_handler(osc_message_handler)
        self._server = BlockingOSCUDPServer((host_ip, in_port), self._dispatcher)
        
        # this blocks until the server is shutdown
        log("OSC: server running")

        # this runs after the server has shutdown
        self._server.serve_forever()  # Blocks forever
        log("OSC: server shutdown")
        self._server = None



    def __init__(self):
        log("OSC: init")
        self._server = None
        self._server_thread = None
        self._stop = False
        self._running = False
        self._missed_count = 0
        self._start_requested = False
        self._lock = threading.Lock()
        self._server_thread = threading.Thread(target=self.thread_loop)

    @property
    def started(self):
        ''' true if server is started or in the process of starting '''
        if self._lock.locked():
            log("OSC: server locked")
            return True
        
        return self._running

    def start(self):
        ''' starts the server '''

        with self._lock:
            # everything here is now locked until the server start is completed

            log("OSC: start requested")
            if self._running:
                return
            
            self._stop = False
            if not self._server_thread.is_alive():
                self._server_thread = threading.Thread(target=self.thread_loop)
                self._server_thread.start()
            self._running = True


    def stop(self):
        ''' stops the server '''
        if not self._running or self._start_requested:
            return
        log("OSC: stop requested")
        self._stop = True
        if self._server:
            self._server.shutdown()
        self._server_thread.join()
        self._server_thread = None
        self._running = False
        log("OSC: server stopped")

    def __del__(self):
        log("OSC stopping...")
        self.stop()

@gremlin.input_devices.gremlin_start()
def start():
    log("Gremlin start!")
    global osc
    osc = Osc()
    osc.start()


@gremlin.input_devices.gremlin_stop()
def stop():
    log("Gremlin stop!")
    global osc
    if osc:
        osc.stop()

@gremlin.input_devices.gremlin_mode()
def mode_changed(mode):
    log(f"Gremlin mode change!: {mode}")



### ----------------------------------------------------------- OSC server stuff ----------------------------------------------------------



### PARSING ###



"""Parsing and conversion of NTP dates contained in datagrams."""


# 63 zero bits followed by a one in the least signifigant bit is a special
# case meaning "immediately."
IMMEDIATELY = struct.pack('>Q', 1)

# timetag * (1 / 2 ** 32) == l32bits + (r32bits / 1 ** 32)
_NTP_TIMESTAMP_TO_SECONDS = 1. / 2. ** 32.
_SECONDS_TO_NTP_TIMESTAMP = 2. ** 32.

# From NTP lib.
_SYSTEM_EPOCH = datetime(*time.gmtime(0)[0:3])
_NTP_EPOCH = datetime(1900, 1, 1)
# _NTP_DELTA is 2208988800
_NTP_DELTA = (_SYSTEM_EPOCH - _NTP_EPOCH).days * 24 * 3600


Timestamp = NamedTuple('Timestamp', [
    ('seconds', int),
    ('fraction', int),
])


class NtpError(Exception):
  """Base class for ntp module errors."""


def parse_timestamp(timestamp: int) -> Timestamp:
    """Parse NTP timestamp as Timetag.
    """
    seconds = timestamp >> 32
    fraction = timestamp & 0xFFFFFFFF
    return Timestamp(seconds, fraction)


def ntp_to_system_time(timestamp: bytes) -> float:
    """Convert a NTP timestamp to system time in seconds.
    """
    try:
        timestamp = struct.unpack('>Q', timestamp)[0]
    except Exception as e:
        raise NtpError(e)
    return timestamp * _NTP_TIMESTAMP_TO_SECONDS - _NTP_DELTA


def system_time_to_ntp(seconds: float) -> bytes:
    """Convert a system time in seconds to NTP timestamp.
    """
    try:
      seconds = seconds + _NTP_DELTA
    except TypeError as e:
      raise NtpError(e)
    return struct.pack('>Q', int(seconds * _SECONDS_TO_NTP_TIMESTAMP))


def ntp_time_to_system_epoch(seconds: float) -> float:
    """Convert a NTP time in seconds to system time in seconds.
    """
    return seconds - _NTP_DELTA


def system_time_to_ntp_epoch(seconds: float) -> float:
    """Convert a system time in seconds to NTP time in seconds.
    """
    return seconds + _NTP_DELTA



"""Functions to get OSC types from datagrams and vice versa"""



MidiPacket = Tuple[int, int, int, int]


class ParseError(Exception):
    """Base exception for when a datagram parsing error occurs."""


class BuildError(Exception):
    """Base exception for when a datagram building error occurs."""


# Constant for special ntp datagram sequences that represent an immediate time.
IMMEDIATELY = 0

# Datagram length in bytes for types that have a fixed size.
_INT_DGRAM_LEN = 4
_INT64_DGRAM_LEN = 8
_UINT64_DGRAM_LEN = 8
_FLOAT_DGRAM_LEN = 4
_DOUBLE_DGRAM_LEN = 8
_TIMETAG_DGRAM_LEN = 8
# Strings and blob dgram length is always a multiple of 4 bytes.
_STRING_DGRAM_PAD = 4
_BLOB_DGRAM_PAD = 4
_EMPTY_STR_DGRAM = b'\x00\x00\x00\x00'


def write_string(val: str) -> bytes:
    """Returns the OSC string equivalent of the given python string.

    Raises:
      - BuildError if the string could not be encoded.
    """
    try:
        dgram = val.encode('utf-8')  # Default, but better be explicit.
    except (UnicodeEncodeError, AttributeError) as e:
        raise BuildError(f'Incorrect string, could not encode {e}')
    diff = _STRING_DGRAM_PAD - (len(dgram) % _STRING_DGRAM_PAD)
    dgram += (b'\x00' * diff)
    return dgram


def get_string(dgram: bytes, start_index: int) -> Tuple[str, int]:
    """Get a python string from the datagram, starting at pos start_index.

    According to the specifications, a string is:
    "A sequence of non-null ASCII characters followed by a null,
    followed by 0-3 additional null characters to make the total number
    of bits a multiple of 32".

    Args:
      dgram: A datagram packet.
      start_index: An index where the string starts in the datagram.

    Returns:
      A tuple containing the string and the new end index.

    Raises:
      ParseError if the datagram could not be parsed.
    """
    if start_index < 0:
        raise ParseError('start_index < 0')
    offset = 0
    try:
        if (len(dgram) > start_index + _STRING_DGRAM_PAD
                and dgram[start_index + _STRING_DGRAM_PAD] == _EMPTY_STR_DGRAM):
            return '', start_index + _STRING_DGRAM_PAD
        while dgram[start_index + offset] != 0:
            offset += 1
        # Align to a byte word.
        if (offset) % _STRING_DGRAM_PAD == 0:
            offset += _STRING_DGRAM_PAD
        else:
            offset += (-offset % _STRING_DGRAM_PAD)
        # Python slices do not raise an IndexError past the last index,
        # do it ourselves.
        if offset > len(dgram[start_index:]):
            raise ParseError('Datagram is too short')
        data_str = dgram[start_index:start_index + offset]
        return data_str.replace(b'\x00', b'').decode('utf-8'), start_index + offset
    except IndexError as ie:
        raise ParseError('Could not parse datagram %s' % ie)
    except TypeError as te:
        raise ParseError('Could not parse datagram %s' % te)


def write_int(val: int) -> bytes:
    """Returns the datagram for the given integer parameter value

    Raises:
      - BuildError if the int could not be converted.
    """
    try:
        return struct.pack('>i', val)
    except struct.error as e:
        raise BuildError(f'Wrong argument value passed: {e}')


def get_int(dgram: bytes, start_index: int) -> Tuple[int, int]:
    """Get a 32-bit big-endian two's complement integer from the datagram.

    Args:
      dgram: A datagram packet.
      start_index: An index where the integer starts in the datagram.

    Returns:
      A tuple containing the integer and the new end index.

    Raises:
      ParseError if the datagram could not be parsed.
    """
    try:
        if len(dgram[start_index:]) < _INT_DGRAM_LEN:
            raise ParseError('Datagram is too short')
        return (
            struct.unpack('>i',
                          dgram[start_index:start_index + _INT_DGRAM_LEN])[0],
            start_index + _INT_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise ParseError('Could not parse datagram %s' % e)


def write_int64(val: int) -> bytes:
    """Returns the datagram for the given 64-bit big-endian signed parameter value

    Raises:
      - BuildError if the int64 could not be converted.
    """
    try:
        return struct.pack('>q', val)
    except struct.error as e:
        raise BuildError(f'Wrong argument value passed: {e}')


def get_int64(dgram: bytes, start_index: int) -> Tuple[int, int]:
    """Get a 64-bit big-endian signed integer from the datagram.

    Args:
      dgram: A datagram packet.
      start_index: An index where the 64-bit integer starts in the datagram.

    Returns:
      A tuple containing the 64-bit integer and the new end index.

    Raises:
      ParseError if the datagram could not be parsed.
    """
    try:
        if len(dgram[start_index:]) < _INT64_DGRAM_LEN:
            raise ParseError('Datagram is too short')
        return (
            struct.unpack('>q',
                          dgram[start_index:start_index + _INT64_DGRAM_LEN])[0],
            start_index + _INT64_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise ParseError('Could not parse datagram %s' % e)


def get_uint64(dgram: bytes, start_index: int) -> Tuple[int, int]:
    """Get a 64-bit big-endian unsigned integer from the datagram.

    Args:
      dgram: A datagram packet.
      start_index: An index where the integer starts in the datagram.

    Returns:
      A tuple containing the integer and the new end index.

    Raises:
      ParseError if the datagram could not be parsed.
    """
    try:
        if len(dgram[start_index:]) < _UINT64_DGRAM_LEN:
            raise ParseError('Datagram is too short')
        return (
            struct.unpack('>Q',
                          dgram[start_index:start_index + _UINT64_DGRAM_LEN])[0],
            start_index + _UINT64_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise ParseError('Could not parse datagram %s' % e)


def get_timetag(dgram: bytes, start_index: int) -> Tuple[Tuple[datetime, int], int]:
    """Get a 64-bit OSC time tag from the datagram.

    Args:
      dgram: A datagram packet.
      start_index: An index where the osc time tag starts in the datagram.

    Returns:
      A tuple containing the tuple of time of sending in utc as datetime and the
      fraction of the current second and the new end index.

    Raises:
      ParseError if the datagram could not be parsed.
    """
    try:
        if len(dgram[start_index:]) < _TIMETAG_DGRAM_LEN:
            raise ParseError('Datagram is too short')

        timetag, _ = get_uint64(dgram, start_index)
        seconds, fraction = parse_timestamp(timetag)

        hours, seconds = seconds // 3600, seconds % 3600
        minutes, seconds = seconds // 60, seconds % 60

        utc = (datetime.combine(_NTP_EPOCH, datetime.min.time()) +
               timedelta(hours=hours, minutes=minutes, seconds=seconds))

        return (utc, fraction), start_index + _TIMETAG_DGRAM_LEN
    except (struct.error, TypeError) as e:
        raise ParseError('Could not parse datagram %s' % e)


def write_float(val: float) -> bytes:
    """Returns the datagram for the given float parameter value

    Raises:
      - BuildError if the float could not be converted.
    """
    try:
        return struct.pack('>f', val)
    except struct.error as e:
        raise BuildError(f'Wrong argument value passed: {e}')


def get_float(dgram: bytes, start_index: int) -> Tuple[float, int]:
    """Get a 32-bit big-endian IEEE 754 floating point number from the datagram.

    Args:
      dgram: A datagram packet.
      start_index: An index where the float starts in the datagram.

    Returns:
      A tuple containing the float and the new end index.

    Raises:
      ParseError if the datagram could not be parsed.
    """
    try:
        if len(dgram[start_index:]) < _FLOAT_DGRAM_LEN:
            # Noticed that Reaktor doesn't send the last bunch of \x00 needed to make
            # the float representation complete in some cases, thus we pad here to
            # account for that.
            dgram = dgram + b'\x00' * (_FLOAT_DGRAM_LEN - len(dgram[start_index:]))
        return (
            struct.unpack('>f',
                          dgram[start_index:start_index + _FLOAT_DGRAM_LEN])[0],
            start_index + _FLOAT_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise ParseError('Could not parse datagram %s' % e)


def write_double(val: float) -> bytes:
    """Returns the datagram for the given double parameter value

    Raises:
      - BuildError if the double could not be converted.
    """
    try:
        return struct.pack('>d', val)
    except struct.error as e:
        raise BuildError(f'Wrong argument value passed: {e}')


def get_double(dgram: bytes, start_index: int) -> Tuple[float, int]:
    """Get a 64-bit big-endian IEEE 754 floating point number from the datagram.

    Args:
      dgram: A datagram packet.
      start_index: An index where the double starts in the datagram.

    Returns:
      A tuple containing the double and the new end index.

    Raises:
      ParseError if the datagram could not be parsed.
    """
    try:
        if len(dgram[start_index:]) < _DOUBLE_DGRAM_LEN:
            raise ParseError('Datagram is too short')
        return (
            struct.unpack('>d',
                          dgram[start_index:start_index + _DOUBLE_DGRAM_LEN])[0],
            start_index + _DOUBLE_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise ParseError(f'Could not parse datagram {e}')


def get_blob(dgram: bytes, start_index: int) -> Tuple[bytes, int]:
    """ Get a blob from the datagram.

    According to the specifications, a blob is made of
    "an int32 size count, followed by that many 8-bit bytes of arbitrary
    binary data, followed by 0-3 additional zero bytes to make the total
    number of bits a multiple of 32".

    Args:
      dgram: A datagram packet.
      start_index: An index where the float starts in the datagram.

    Returns:
      A tuple containing the blob and the new end index.

    Raises:
      ParseError if the datagram could not be parsed.
    """
    size, int_offset = get_int(dgram, start_index)
    # Make the size a multiple of 32 bits.
    total_size = size + (-size % _BLOB_DGRAM_PAD)
    end_index = int_offset + size
    if end_index - start_index > len(dgram[start_index:]):
        raise ParseError('Datagram is too short.')
    return dgram[int_offset:int_offset + size], int_offset + total_size


def write_blob(val: bytes) -> bytes:
    """Returns the datagram for the given blob parameter value.

    Raises:
      - BuildError if the value was empty or if its size didn't fit an OSC int.
    """
    if not val:
        raise BuildError('Blob value cannot be empty')
    dgram = write_int(len(val))
    dgram += val
    while len(dgram) % _BLOB_DGRAM_PAD != 0:
        dgram += b'\x00'
    return dgram


def get_date(dgram: bytes, start_index: int) -> Tuple[float, int]:
    """Get a 64-bit big-endian fixed-point time tag as a date from the datagram.

    According to the specifications, a date is represented as is:
    "the first 32 bits specify the number of seconds since midnight on
    January 1, 1900, and the last 32 bits specify fractional parts of a second
    to a precision of about 200 picoseconds".

    Args:
      dgram: A datagram packet.
      start_index: An index where the date starts in the datagram.

    Returns:
      A tuple containing the system date and the new end index.
      returns osc_immediately (0) if the corresponding OSC sequence was found.

    Raises:
      ParseError if the datagram could not be parsed.
    """
    # Check for the special case first.
    if dgram[start_index:start_index + _TIMETAG_DGRAM_LEN] == IMMEDIATELY:
        return IMMEDIATELY, start_index + _TIMETAG_DGRAM_LEN
    if len(dgram[start_index:]) < _TIMETAG_DGRAM_LEN:
        raise ParseError('Datagram is too short')
    timetag, start_index = get_uint64(dgram, start_index)
    seconds = timetag * _NTP_TIMESTAMP_TO_SECONDS
    return ntp_time_to_system_epoch(seconds), start_index


def write_date(system_time: Union[int, float]) -> bytes:
    if system_time == IMMEDIATELY:
        return IMMEDIATELY

    try:
        return system_time_to_ntp(system_time)
    except NtpError as ntpe:
        raise BuildError(ntpe)


def write_rgba(val: bytes) -> bytes:
    """Returns the datagram for the given rgba32 parameter value

    Raises:
      - BuildError if the int could not be converted.
    """
    try:
        return struct.pack('>I', val)
    except struct.error as e:
        raise BuildError(f'Wrong argument value passed: {e}')


def get_rgba(dgram: bytes, start_index: int) -> Tuple[bytes, int]:
    """Get an rgba32 integer from the datagram.

    Args:
      dgram: A datagram packet.
      start_index: An index where the integer starts in the datagram.

    Returns:
      A tuple containing the integer and the new end index.

    Raises:
      ParseError if the datagram could not be parsed.
    """
    try:
        if len(dgram[start_index:]) < _INT_DGRAM_LEN:
            raise ParseError('Datagram is too short')
        return (
            struct.unpack('>I',
                          dgram[start_index:start_index + _INT_DGRAM_LEN])[0],
            start_index + _INT_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise ParseError('Could not parse datagram %s' % e)


def write_midi(val: MidiPacket) -> bytes:
    """Returns the datagram for the given MIDI message parameter value

       A valid MIDI message: (port id, status byte, data1, data2).

    Raises:
      - BuildError if the MIDI message could not be converted.

    """
    if len(val) != 4:
        raise BuildError('MIDI message length is invalid')
    try:
        value = sum((value & 0xFF) << 8 * (3 - pos) for pos, value in enumerate(val))
        return struct.pack('>I', value)
    except struct.error as e:
        raise BuildError(f'Wrong argument value passed: {e}')


def get_midi(dgram: bytes, start_index: int) -> Tuple[MidiPacket, int]:
    """Get a MIDI message (port id, status byte, data1, data2) from the datagram.

    Args:
      dgram: A datagram packet.
      start_index: An index where the MIDI message starts in the datagram.

    Returns:
      A tuple containing the MIDI message and the new end index.

    Raises:
      ParseError if the datagram could not be parsed.
    """
    try:
        if len(dgram[start_index:]) < _INT_DGRAM_LEN:
            raise ParseError('Datagram is too short')
        val = struct.unpack('>I',
                            dgram[start_index:start_index + _INT_DGRAM_LEN])[0]
        midi_msg = cast(
            MidiPacket,
            tuple((val & 0xFF << 8 * i) >> 8 * i for i in range(3, -1, -1)))
        return (midi_msg, start_index + _INT_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise ParseError('Could not parse datagram %s' % e)





### OSCE MESSAGE ###

"""Representation of an OSC message in a pythonesque way."""





class OscMessage(object):
    """Representation of a parsed datagram representing an OSC message.

    An OSC message consists of an OSC Address Pattern followed by an OSC
    Type Tag String followed by zero or more OSC Arguments.
    """

    def __init__(self, dgram: bytes) -> None:
        self._dgram = dgram
        self._parameters = []  # type: List[Any]
        self._parse_datagram()

    def _parse_datagram(self) -> None:
        try:
            self._address_regexp, index = get_string(self._dgram, 0)
            if not self._dgram[index:]:
                # No params is legit, just return now.
                return

            # Get the parameters types.
            type_tag, index = get_string(self._dgram, index)
            if type_tag.startswith(','):
                type_tag = type_tag[1:]

            params = []  # type: List[Any]
            param_stack = [params]
            # Parse each parameter given its type.
            for param in type_tag:
                val = NotImplemented  # type: Any
                if param == "i":  # Integer.
                    val, index = get_int(self._dgram, index)
                elif param == "h":  # Int64.
                    val, index = get_int64(self._dgram, index)
                elif param == "f":  # Float.
                    val, index = get_float(self._dgram, index)
                elif param == "d":  # Double.
                    val, index = get_double(self._dgram, index)
                elif param == "s":  # String.
                    val, index = get_string(self._dgram, index)
                elif param == "b":  # Blob.
                    val, index = get_blob(self._dgram, index)
                elif param == "r":  # RGBA.
                    val, index = get_rgba(self._dgram, index)
                elif param == "m":  # MIDI.
                    val, index = get_midi(self._dgram, index)
                elif param == "t":  # osc time tag:
                    val, index = get_timetag(self._dgram, index)
                elif param == "T":  # True.
                    val = True
                elif param == "F":  # False.
                    val = False
                elif param == "N":  # Nil.
                    val = None
                elif param == "[":  # Array start.
                    array = []  # type: List[Any]
                    param_stack[-1].append(array)
                    param_stack.append(array)
                elif param == "]":  # Array stop.
                    if len(param_stack) < 2:
                        raise ParseError(f'Unexpected closing bracket in type tag: {type_tag}')
                    param_stack.pop()
                # TODO: Support more exotic types as described in the specification.
                else:
                    logging.warning(f'Unhandled parameter type: {param}')
                    continue
                if param not in "[]":
                    param_stack[-1].append(val)
            if len(param_stack) != 1:
                raise ParseError(f'Missing closing bracket in type tag: {type_tag}')
            self._parameters = params
        except ParseError as pe:
            raise ParseError('Found incorrect datagram, ignoring it', pe)

    @property
    def address(self) -> str:
        """Returns the OSC address regular expression."""
        return self._address_regexp

    @staticmethod
    def dgram_is_message(dgram: bytes) -> bool:
        """Returns whether this datagram starts as an OSC message."""
        return dgram.startswith(b'/')

    @property
    def size(self) -> int:
        """Returns the length of the datagram for this message."""
        return len(self._dgram)

    @property
    def dgram(self) -> bytes:
        """Returns the datagram from which this message was built."""
        return self._dgram

    @property
    def params(self) -> List[Any]:
        """Convenience method for list(self) to get the list of parameters."""
        return list(self)

    def __iter__(self) -> Iterator[Any]:
        """Returns an iterator over the parameters of this message."""
        return iter(self._parameters)



### OSC PACKET ###

"""Use OSC packets to parse incoming UDP packets into messages or bundles.

It lets you access easily to OscMessage and OscBundle instances in the packet.
"""


# A namedtuple as returned my the _timed_msg_of_bundle function.
# 1) the system time at which the message should be executed
#    in seconds since the epoch.
# 2) the actual message.
TimedMessage = NamedTuple('TimedMessage', [
    ('time', float),
    ('message', OscMessage),
])


def _timed_msg_of_bundle(bundle, now: float) -> List[TimedMessage]:
    """Returns messages contained in nested bundles as a list of TimedMessage."""
    msgs = []
    for content in bundle:
        if type(content) is OscMessage:
            if (bundle.timestamp == IMMEDIATELY or bundle.timestamp < now):
                msgs.append(TimedMessage(now, content))
            else:
                msgs.append(TimedMessage(bundle.timestamp, content))
        else:
            msgs.extend(_timed_msg_of_bundle(content, now))
    return msgs



class OscPacket(object):
    """Unit of transmission of the OSC protocol.

    Any application that sends OSC Packets is an OSC Client.
    Any application that receives OSC Packets is an OSC Server.
    """

    def __init__(self, dgram: bytes) -> None:
        """Initialize an OdpPacket with the given UDP datagram.

        Args:
          - dgram: the raw UDP datagram holding the OSC packet.

        Raises:
          - ParseError if the datagram could not be parsed.
        """
        now = time.time()
        try:
            if OscBundle.dgram_is_bundle(dgram):
                self._messages = sorted(
                    _timed_msg_of_bundle(OscBundle(dgram), now),
                    key=lambda x: x.time)
            elif OscMessage.dgram_is_message(dgram):
                self._messages = [TimedMessage(now, OscMessage(dgram))]
            else:
                # Empty packet, should not happen as per the spec but heh, UDP...
                raise ParseError(
                    'OSC Packet should at least contain an OscMessage or an '
                    'OscBundle.')
        except (ParseError, ParseError) as pe:
            raise ParseError('Could not parse packet %s' % pe)

    @property
    def messages(self) -> List[TimedMessage]:
        """Returns asc-time-sorted TimedMessages of the messages in this packet."""
        return self._messages



### OSC BUNDLE ###


_BUNDLE_PREFIX = b"#bundle\x00"



class OscBundle(object):
    """Bundles elements that should be triggered at the same time.

    An element can be another OscBundle or an OscMessage.
    """

    def __init__(self, dgram: bytes) -> None:
        """Initializes the OscBundle with the given datagram.

        Args:
          dgram: a UDP datagram representing an OscBundle.

        Raises:
          ParseError: if the datagram could not be parsed into an OscBundle.
        """
        # Interesting stuff starts after the initial b"#bundle\x00".
        self._dgram = dgram
        index = len(_BUNDLE_PREFIX)
        try:
            self._timestamp, index = get_date(self._dgram, index)
        except ParseError as pe:
            raise ParseError("Could not get the date from the datagram: %s" % pe)
        # Get the contents as a list of OscBundle and OscMessage.
        self._contents = self._parse_contents(index)

    def _parse_contents(self, index: int) -> List[Union['OscBundle', OscMessage]]:
        contents = []  # type: List[Union[OscBundle, OscMessage]]

        try:
            # An OSC Bundle Element consists of its size and its contents.
            # The size is an int32 representing the number of 8-bit bytes in the
            # contents, and will always be a multiple of 4. The contents are either
            # an OSC Message or an OSC Bundle.
            while self._dgram[index:]:
                # Get the sub content size.
                content_size, index = get_int(self._dgram, index)
                # Get the datagram for the sub content.
                content_dgram = self._dgram[index:index + content_size]
                # Increment our position index up to the next possible content.
                index += content_size
                # Parse the content into an OSC message or bundle.
                if OscBundle.dgram_is_bundle(content_dgram):
                    contents.append(OscBundle(content_dgram))
                elif OscMessage.dgram_is_message(content_dgram):
                    contents.append(OscMessage(content_dgram))
                else:
                    logging.warning(
                        "Could not identify content type of dgram %r" % content_dgram)
        except (ParseError, ParseError, IndexError) as e:
            raise ParseError("Could not parse a content datagram: %s" % e)

        return contents

    @staticmethod
    def dgram_is_bundle(dgram: bytes) -> bool:
        """Returns whether this datagram starts like an OSC bundle."""
        return dgram.startswith(_BUNDLE_PREFIX)

    @property
    def timestamp(self) -> float:
        """Returns the timestamp associated with this bundle."""
        return self._timestamp

    @property
    def num_contents(self) -> int:
        """Shortcut for len(*bundle) returning the number of elements."""
        return len(self._contents)

    @property
    def size(self) -> int:
        """Returns the length of the datagram for this bundle."""
        return len(self._dgram)

    @property
    def dgram(self) -> bytes:
        """Returns the datagram from which this bundle was built."""
        return self._dgram

    def content(self, index: int) -> Any:
        """Returns the bundle's content 0-indexed."""
        return self._contents[index]

    def __iter__(self) -> Iterator[Any]:
        """Returns an iterator over the bundle's content."""
        return iter(self._contents)





### OSC BUNDLE BUILDER ###

"""Build OSC bundles for client applications."""



# Shortcut to specify an immediate execution of messages in the bundle.


class BuildError(Exception):
    """Error raised when an error occurs building the bundle."""


class OscBundleBuilder(object):
    """Builds arbitrary OscBundle instances."""

    def __init__(self, timestamp: int) -> None:
        """Build a new bundle with the associated timestamp.

        Args:
          - timestamp: system time represented as a floating point number of
                       seconds since the epoch in UTC or IMMEDIATELY.
        """
        self._timestamp = timestamp
        self._contents = []  # type: List[OscBundle]

    def add_content(self, content: OscBundle) -> None:
        """Add a new content to this bundle.

        Args:
          - content: Either an OscBundle or an OscMessage
        """
        self._contents.append(content)

    def build(self) -> OscBundle:
        """Build an OscBundle with the current state of this builder.

        Raises:
          - BuildError: if we could not build the bundle.
        """
        dgram = b'#bundle\x00'
        try:
            dgram += write_date(self._timestamp)
            for content in self._contents:
                if (type(content) == OscMessage
                        or type(content) == OscBundle):
                    size = content.size
                    dgram += write_int(size)
                    dgram += content.dgram
                else:
                    raise BuildError(
                        "Content must be either OscBundle or OscMessage"
                        f"found {type(content)}")
            return OscBundle(dgram)
        except BuildError as be:
            raise BuildError(f'Could not build the bundle {be}')




### OSC MESSAGE BUILDER ###

"""Build OSC messages for client applications."""


ArgValue = Union[str, bytes, bool, int, float, MidiPacket, list]

class BuildError(Exception):
    """Error raised when an incomplete message is trying to be built."""

class OscMessageBuilder(object):
    """Builds arbitrary OscMessage instances."""

    ARG_TYPE_FLOAT = "f"
    ARG_TYPE_DOUBLE = "d"
    ARG_TYPE_INT = "i"
    ARG_TYPE_INT64 = "h"
    ARG_TYPE_STRING = "s"
    ARG_TYPE_BLOB = "b"
    ARG_TYPE_RGBA = "r"
    ARG_TYPE_MIDI = "m"
    ARG_TYPE_TRUE = "T"
    ARG_TYPE_FALSE = "F"
    ARG_TYPE_NIL = "N"

    ARG_TYPE_ARRAY_START = "["
    ARG_TYPE_ARRAY_STOP = "]"

    _SUPPORTED_ARG_TYPES = (
        ARG_TYPE_FLOAT, ARG_TYPE_DOUBLE, ARG_TYPE_INT, ARG_TYPE_INT64, ARG_TYPE_BLOB, ARG_TYPE_STRING,
        ARG_TYPE_RGBA, ARG_TYPE_MIDI, ARG_TYPE_TRUE, ARG_TYPE_FALSE, ARG_TYPE_NIL)

    def __init__(self, address: Optional[str] = None) -> None:
        """Initialize a new builder for a message.

        Args:
          - address: The osc address to send this message to.
        """
        self._address = address
        self._args = []  # type: List[Tuple[str, Union[ArgValue, None]]]

    @property
    def address(self) -> Optional[str]:
        """Returns the OSC address this message will be sent to."""
        return self._address

    @address.setter
    def address(self, value: str) -> None:
        """Sets the OSC address this message will be sent to."""
        self._address = value

    @property
    def args(self) -> List[Tuple[str, Union[ArgValue, None]]]:
        """Returns the (type, value) arguments list of this message."""
        return self._args

    def _valid_type(self, arg_type: str) -> bool:
        if arg_type in self._SUPPORTED_ARG_TYPES:
            return True
        elif isinstance(arg_type, list):
            for sub_type in arg_type:
                if not self._valid_type(sub_type):
                    return False
            return True
        return False

    def add_arg(self, arg_value: ArgValue, arg_type: Optional[str] = None) -> None:
        """Add a typed argument to this message.

        Args:
          - arg_value: The corresponding value for the argument.
          - arg_type: A value in ARG_TYPE_* defined in this class,
                      if none then the type will be guessed.
        Raises:
          - ValueError: if the type is not supported.
        """
        if arg_type and not self._valid_type(arg_type):
            raise ValueError(
                f'arg_type must be one of {self._SUPPORTED_ARG_TYPES}, or an array of valid types'
                )
        if not arg_type:
            arg_type = self._get_arg_type(arg_value)
        if isinstance(arg_type, list):
            self._args.append((self.ARG_TYPE_ARRAY_START, None))
            for v, t in zip(arg_value, arg_type):  # type: ignore[var-annotated, arg-type]
                self.add_arg(v, t)
            self._args.append((self.ARG_TYPE_ARRAY_STOP, None))
        else:
            self._args.append((arg_type, arg_value))

    # The return type here is actually Union[str, List[<self>]], however there
    # is no annotation for a recursive type like this.
    def _get_arg_type(self, arg_value: ArgValue) -> Union[str, Any]:
        """Guess the type of a value.

        Args:
          - arg_value: The value to guess the type of.
        Raises:
          - ValueError: if the type is not supported.
        """
        if isinstance(arg_value, str):
            arg_type = self.ARG_TYPE_STRING  # type: Union[str, Any]
        elif isinstance(arg_value, bytes):
            arg_type = self.ARG_TYPE_BLOB
        elif arg_value is True:
            arg_type = self.ARG_TYPE_TRUE
        elif arg_value is False:
            arg_type = self.ARG_TYPE_FALSE
        elif isinstance(arg_value, int):
            if arg_value.bit_length() > 32:
                arg_type = self.ARG_TYPE_INT64
            else:
                arg_type = self.ARG_TYPE_INT
        elif isinstance(arg_value, float):
            arg_type = self.ARG_TYPE_FLOAT
        elif isinstance(arg_value, tuple) and len(arg_value) == 4:
            arg_type = self.ARG_TYPE_MIDI
        elif isinstance(arg_value, list):
            arg_type = [self._get_arg_type(v) for v in arg_value]
        elif arg_value is None:
            arg_type = self.ARG_TYPE_NIL
        else:
            raise ValueError('Infered arg_value type is not supported')
        return arg_type

    def build(self) -> OscMessage:
        """Builds an OscMessage from the current state of this builder.

        Raises:
          - BuildError: if the message could not be build or if the address
                        was empty.

        Returns:
          - an OscMessage instance.
        """
        if not self._address:
            raise BuildError('OSC addresses cannot be empty')
        dgram = b''
        try:
            # Write the address.
            dgram += write_string(self._address)
            if not self._args:
                dgram += write_string(',')
                return OscMessage(dgram)

            # Write the parameters.
            arg_types = "".join([arg[0] for arg in self._args])
            dgram += write_string(',' + arg_types)
            for arg_type, value in self._args:
                if arg_type == self.ARG_TYPE_STRING:
                    dgram += write_string(value)  # type: ignore[arg-type]
                elif arg_type == self.ARG_TYPE_INT:
                    dgram += write_int(value)  # type: ignore[arg-type]
                elif arg_type == self.ARG_TYPE_INT64:
                    dgram += write_int64(value)  # type: ignore[arg-type]
                elif arg_type == self.ARG_TYPE_FLOAT:
                    dgram += write_float(value)  # type: ignore[arg-type]
                elif arg_type == self.ARG_TYPE_DOUBLE:
                    dgram += write_double(value)  # type: ignore[arg-type]
                elif arg_type == self.ARG_TYPE_BLOB:
                    dgram += write_blob(value)  # type: ignore[arg-type]
                elif arg_type == self.ARG_TYPE_RGBA:
                    dgram += write_rgba(value)  # type: ignore[arg-type]
                elif arg_type == self.ARG_TYPE_MIDI:
                    dgram += write_midi(value)  # type: ignore[arg-type]
                elif arg_type in (self.ARG_TYPE_TRUE,
                                  self.ARG_TYPE_FALSE,
                                  self.ARG_TYPE_ARRAY_START,
                                  self.ARG_TYPE_ARRAY_STOP,
                                  self.ARG_TYPE_NIL):
                    continue
                else:
                    raise BuildError(f'Incorrect parameter type found {arg_type}')

            return OscMessage(dgram)
        except BuildError as be:
            raise BuildError(f'Could not build the message: {be}')





### DISPATCHER ###
"""Maps OSC addresses to handler functions
"""




class Handler(object):
    """Wrapper for a callback function that will be called when an OSC message is sent to the right address.

    Represents a handler callback function that will be called whenever an OSC message is sent to the address this
    handler is mapped to. It passes the address, the fixed arguments (if any) as well as all osc arguments from the
    message if any were passed.
    """

    def __init__(self, _callback: Callable, _args: Union[Any, List[Any]],
                 _needs_reply_address: bool = False) -> None:
        """
        Args:
            _callback Function that is called when handler is invoked
            _args: Message causing invocation
            _needs_reply_address Whether the client's ip address shall be passed as an argument or not
       """
        self.callback = _callback
        self.args = _args
        self.needs_reply_address = _needs_reply_address

    # needed for test module
    def __eq__(self, other: Any) -> bool:
        return (type(self) == type(other) and
                self.callback == other.callback and
                self.args == other.args and
                self.needs_reply_address == other.needs_reply_address)

    def invoke(self, client_address: Tuple[str, int], message: OscMessage) -> None:
        """Invokes the associated callback function

        Args:
            client_address: Address match that causes the invocation
            message: Message causing invocation
       """
        if self.needs_reply_address:
            if self.args:
                self.callback(client_address, message.address, self.args, *message)
            else:
                self.callback(client_address, message.address, *message)
        else:
            if self.args:
                self.callback(message.address, self.args, *message)
            else:
                self.callback(message.address, *message)


class Dispatcher(object):
    """Maps Handlers to OSC addresses and dispatches messages to the handler on matched addresses

    Maps OSC addresses to handler functions and invokes the correct handler when a message comes in.
    """

    def __init__(self) -> None:
        self._map = collections.defaultdict(list)  # type: DefaultDict[str, List[Handler]]
        self._default_handler = None  # type: Optional[Handler]

    def map(self, address: str, handler: Callable, *args: Union[Any, List[Any]],
            needs_reply_address: bool = False) -> Handler:
        """Map an address to a handler

        The callback function must have one of the following signatures:

        ``def some_cb(address: str, *osc_args: List[Any]) -> None:``
        ``def some_cb(address: str, fixed_args: List[Any], *osc_args: List[Any]) -> None:``

        ``def some_cb(client_address: Tuple[str, int], address: str, *osc_args: List[Any]) -> None:``
        ``def some_cb(client_address: Tuple[str, int], address: str, fixed_args: List[Any], *osc_args: List[Any]) -> None:``

        Args:
            address: Address to be mapped
            handler: Callback function that will be called as the handler for the given address
            *args: Fixed arguements that will be passed to the callback function
            needs_reply_address: Whether the IP address from which the message originated from shall be passed as
                an argument to the handler callback

        Returns:
            The handler object that will be invoked should the given address match

        """
        # TODO: Check the spec:
        # http://opensoundcontrol.org/spec-1_0
        # regarding multiple mappings
        handlerobj = Handler(handler, list(args), needs_reply_address)
        self._map[address].append(handlerobj)
        return handlerobj

    @overload
    def unmap(self, address: str, handler: Handler) -> None:
        """Remove an already mapped handler from an address

        Args:
            address (str): Address to be unmapped
            handler (Handler): A Handler object as returned from map().
        """
        pass

    @overload
    def unmap(self, address: str, handler: Callable, *args: Union[Any, List[Any]],
              needs_reply_address: bool = False) -> None:
        """Remove an already mapped handler from an address

        Args:
            address: Address to be unmapped
            handler: A function that will be run when the address matches with
                the OscMessage passed as parameter.
            args: Any additional arguments that will be always passed to the
                handlers after the osc messages arguments if any.
            needs_reply_address: True if the handler function needs the
                originating client address passed (as the first argument).
        """
        pass

    def unmap(self, address, handler, *args, needs_reply_address=False):
        try:
            if isinstance(handler, Handler):
                self._map[address].remove(handler)
            else:
                self._map[address].remove(Handler(handler, list(args), needs_reply_address))
        except ValueError as e:
            if str(e) == "list.remove(x): x not in list":
                raise ValueError("Address '%s' doesn't have handler '%s' mapped to it" % (address, handler)) from e

    def handlers_for_address(self, address_pattern: str) -> Generator[Handler, None, None]:
        """Yields handlers matching an address


        Args:
            address_pattern: Address to match

        Returns:
            Generator yielding Handlers matching address_pattern
        """
        # First convert the address_pattern into a matchable regexp.
        # '?' in the OSC Address Pattern matches any single character.
        # Let's consider numbers and _ "characters" too here, it's not said
        # explicitly in the specification but it sounds good.
        escaped_address_pattern = re.escape(address_pattern)
        pattern = escaped_address_pattern.replace('\\?', '\\w?')
        # '*' in the OSC Address Pattern matches any sequence of zero or more
        # characters.
        pattern = pattern.replace('\\*', '[\w|\+]*')
        # The rest of the syntax in the specification is like the re module so
        # we're fine.
        pattern = pattern + '$'
        patterncompiled = re.compile(pattern)
        matched = False

        for addr, handlers in self._map.items():
            if (patterncompiled.match(addr)
                    or (('*' in addr) and re.match(addr.replace('*', '[^/]*?/*'), address_pattern))):
                yield from handlers
                matched = True

        if not matched and self._default_handler:
            logging.debug('No handler matched but default handler present, added it.')
            yield self._default_handler

    def call_handlers_for_packet(self, data: bytes, client_address: Tuple[str, int]) -> None:
        """Invoke handlers for all messages in OSC packet

        The incoming OSC Packet is decoded and the handlers for each included message is found and invoked.

        Args:
            data: Data of packet
            client_address: Address of client this packet originated from
        """

        # Get OSC messages from all bundles or standalone message.
        try:
            packet = OscPacket(data)
            for timed_msg in packet.messages:
                now = time.time()
                handlers = self.handlers_for_address(
                    timed_msg.message.address)
                if not handlers:
                    continue
                # If the message is to be handled later, then so be it.
                if timed_msg.time > now:
                    time.sleep(timed_msg.time - now)
                for handler in handlers:
                    handler.invoke(client_address, timed_msg.message)
        except ParseError:
            pass

    def set_default_handler(self, handler: Callable, needs_reply_address: bool = False) -> None:
        """Sets the default handler

        The default handler is invoked every time no other handler is mapped to an address.

        Args:
            handler: Callback function to handle unmapped requests
            needs_reply_address: Whether the callback shall be passed the client address
        """
        self._default_handler = None if (handler is None) else Handler(handler, [], needs_reply_address)





### OSC SERVER ###

"""OSC Servers that receive UDP packets and invoke handlers accordingly.
"""



_RequestType = Union[_socket, Tuple[bytes, _socket]]
_AddressType = Union[Tuple[str, int], str]


class _UDPHandler(socketserver.BaseRequestHandler):
    """Handles correct UDP messages for all types of server."""

    def handle(self) -> None:
        """Calls the handlers via dispatcher

        This method is called after a basic sanity check was done on the datagram,
        whether this datagram looks like an osc message or bundle.
        If not the server won't call it and so no new
        threads/processes will be spawned.
        """
        server = cast(OSCUDPServer, self.server)
        server.dispatcher.call_handlers_for_packet(self.request[0], self.client_address)


def _is_valid_request(request: _RequestType) -> bool:
    """Returns true if the request's data looks like an osc bundle or message.

    Returns:
        True if request is OSC bundle or OSC message
    """
    assert isinstance(request, tuple)  # TODO: handle requests which are passed just as a socket?
    data = request[0]
    return (
            OscBundle.dgram_is_bundle(data)
            or OscMessage.dgram_is_message(data))


class OSCUDPServer(socketserver.UDPServer):
    """Superclass for different flavors of OSC UDP servers"""

    def __init__(self, server_address: Tuple[str, int], dispatcher: Dispatcher, bind_and_activate: bool = True) -> None:
        """Initialize

        Args:
            server_address: IP and port of server
            dispatcher: Dispatcher this server will use
            (optional) bind_and_activate: default=True defines if the server has to start on call of constructor  
        """
        super().__init__(server_address, _UDPHandler, bind_and_activate)
        self._dispatcher = dispatcher

    def verify_request(self, request: _RequestType, client_address: _AddressType) -> bool:
        """Returns true if the data looks like a valid OSC UDP datagram

        Args:
            request: Incoming data
            client_address: IP and port of client this message came from

        Returns:
            True if request is OSC bundle or OSC message
        """
        return _is_valid_request(request)

    @property
    def dispatcher(self) -> Dispatcher:
        return self._dispatcher


class BlockingOSCUDPServer(OSCUDPServer):
    """Blocking version of the UDP server.

    Each message will be handled sequentially on the same thread.
    Use this is you don't care about latency in your message handling or don't
    have a multiprocess/multithread environment.
    """


class ThreadingOSCUDPServer(socketserver.ThreadingMixIn, OSCUDPServer):
    """Threading version of the OSC UDP server.

    Each message will be handled in its own new thread.
    Use this when lightweight operations are done by each message handlers.
    """


if hasattr(os, "fork"):
    class ForkingOSCUDPServer(socketserver.ForkingMixIn, OSCUDPServer):
        """Forking version of the OSC UDP server.

        Each message will be handled in its own new process.
        Use this when heavyweight operations are done by each message handlers
        and forking a whole new process for each of them is worth it.
        """


class AsyncIOOSCUDPServer():
    """Asynchronous OSC Server

    An asynchronous OSC Server using UDP. It creates a datagram endpoint that runs in an event loop.
    """

    def __init__(self, server_address: Tuple[str, int], dispatcher: Dispatcher, loop: BaseEventLoop) -> None:
        """Initialize

        Args:
            server_address: IP and port of server
            dispatcher: Dispatcher this server shall use
            loop: Event loop to add the server task to. Use ``asyncio.get_event_loop()`` unless you know what you're
                doing.
        """

        self._server_address = server_address
        self._dispatcher = dispatcher
        self._loop = loop

    class _OSCProtocolFactory(asyncio.DatagramProtocol):
        """OSC protocol factory which passes datagrams to dispatcher"""

        def __init__(self, dispatcher: Dispatcher) -> None:
            self.dispatcher = dispatcher

        def datagram_received(self, data: bytes, client_address: Tuple[str, int]) -> None:
            self.dispatcher.call_handlers_for_packet(data, client_address)

    def serve(self) -> None:
        """Creates a datagram endpoint and registers it with event loop.

        Use this only in synchronous code (i.e. not from within a coroutine). This will start the server and run it
        forever or until a ``stop()`` is called on the event loop.
        """
        self._loop.run_until_complete(self.create_serve_endpoint())

    def create_serve_endpoint(self) -> Coroutine[Any, Any, Tuple[asyncio.transports.BaseTransport, asyncio.DatagramProtocol]]:
        """Creates a datagram endpoint and registers it with event loop as coroutine.

        Returns:
            Awaitable coroutine that returns transport and protocol objects
        """
        return self._loop.create_datagram_endpoint(
            lambda: self._OSCProtocolFactory(self.dispatcher),
            local_addr=self._server_address)

    @property
    def dispatcher(self) -> Dispatcher:
        return self._dispatcher


### UDP CLIENT ###

"""UDP Clients for sending OSC messages to an OSC server"""


from typing import Union

class UDPClient(object):
    """OSC client to send :class:`OscMessage` or :class:`OscBundle` via UDP"""

    def __init__(self, address: str, port: int, allow_broadcast: bool = False, family: socket.AddressFamily = socket.AF_UNSPEC) -> None:
        """Initialize client

        As this is UDP it will not actually make any attempt to connect to the
        given server at ip:port until the send() method is called.

        Args:
            address: IP address of server
            port: Port of server
            allow_broadcast: Allow for broadcast transmissions
            family: address family parameter (passed to socket.getaddrinfo)
        """

        for addr in socket.getaddrinfo(address, port, type=socket.SOCK_DGRAM, family=family):
            af, socktype, protocol, canonname, sa = addr

            try:
                self._sock = socket.socket(af, socktype)
            except OSError:
                continue
            break

        self._sock.setblocking(False)
        if allow_broadcast:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._address = address
        self._port = port

    def send(self, content: Union[OscMessage, OscBundle]) -> None:
        """Sends an :class:`OscMessage` or :class:`OscBundle` via UDP

        Args:
            content: Message or bundle to be sent
        """
        self._sock.sendto(content.dgram, (self._address, self._port))


class SimpleUDPClient(UDPClient):
    """Simple OSC client that automatically builds :class:`OscMessage` from arguments"""

    def send_message(self, address: str, value: ArgValue) -> None:
        """Build :class:`OscMessage` from arguments and send to server

        Args:
            address: OSC address the message shall go to
            value: One or more arguments to be added to the message
        """
        builder = OscMessageBuilder(address=address)
        if value is None:
            values = []
        elif not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
            values = [value]
        else:
            values = value
        for val in values:
            builder.add_arg(val)
        msg = builder.build()
        self.send(msg)
