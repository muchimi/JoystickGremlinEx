

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


import logging

from PySide6 import QtWidgets, QtCore, QtGui
import threading
import gremlin.config
from gremlin.types import DeviceType
from gremlin.input_types import InputType

from gremlin.keyboard import Key

import uuid
from gremlin.singleton_decorator import SingletonDecorator
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

from gremlin.util import *
from lxml import etree as ElementTree

import enum


  

### OSC handler start ------------------------------------------------------- 
# Adapted from: Python-OSC  https://github.com/attwad/python-osc 
# Credits go to AttWad
# ####




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
    pass


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


class OscParseError(Exception):
    """Base exception for when a datagram parsing error occurs."""


class OscBuildError(Exception):
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
        raise OscBuildError('Incorrect string, could not encode {}'.format(e))
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
        raise OscParseError('start_index < 0')
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
            raise OscParseError('Datagram is too short')
        data_str = dgram[start_index:start_index + offset]
        return data_str.replace(b'\x00', b'').decode('utf-8'), start_index + offset
    except IndexError as ie:
        raise OscParseError(f'Could not parse datagram {ie}')
    except TypeError as te:
        raise OscParseError(f'Could not parse datagram {te}')


def write_int(val: int) -> bytes:
    """Returns the datagram for the given integer parameter value

    Raises:
    - BuildError if the int could not be converted.
    """
    try:
        return struct.pack('>i', val)
    except struct.error as e:
        raise OscBuildError(f'Wrong argument value passed: {e}')


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
            raise OscParseError('Datagram is too short')
        return (
            struct.unpack('>i',
                        dgram[start_index:start_index + _INT_DGRAM_LEN])[0],
            start_index + _INT_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise OscParseError(f"Could not parse datagram {e}")


def write_int64(val: int) -> bytes:
    """Returns the datagram for the given 64-bit big-endian signed parameter value

    Raises:
    - BuildError if the int64 could not be converted.
    """
    try:
        return struct.pack('>q', val)
    except struct.error as e:
        raise OscBuildError(f'Wrong argument value passed: {e}')


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
            raise OscParseError('Datagram is too short')
        return (
            struct.unpack('>q',
                        dgram[start_index:start_index + _INT64_DGRAM_LEN])[0],
            start_index + _INT64_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise OscParseError(f"Could not parse datagram {e}")


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
            raise OscParseError('Datagram is too short')
        return (
            struct.unpack('>Q',
                        dgram[start_index:start_index + _UINT64_DGRAM_LEN])[0],
            start_index + _UINT64_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise OscParseError(f'Could not parse datagram {e}')


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
            raise OscParseError('Datagram is too short')

        timetag, _ = get_uint64(dgram, start_index)
        seconds, fraction = parse_timestamp(timetag)

        hours, seconds = seconds // 3600, seconds % 3600
        minutes, seconds = seconds // 60, seconds % 60

        utc = (datetime.combine(_NTP_EPOCH, datetime.min.time()) +
            timedelta(hours=hours, minutes=minutes, seconds=seconds))

        return (utc, fraction), start_index + _TIMETAG_DGRAM_LEN
    except (struct.error, TypeError) as e:
        raise OscParseError(f'Could not parse datagram {e}')


def write_float(val: float) -> bytes:
    """Returns the datagram for the given float parameter value

    Raises:
    - BuildError if the float could not be converted.
    """
    try:
        return struct.pack('>f', val)
    except struct.error as e:
        raise OscBuildError(f'Wrong argument value passed: {e}')


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
        raise OscParseError(f'Could not parse datagram {e}')


def write_double(val: float) -> bytes:
    """Returns the datagram for the given double parameter value

    Raises:
    - BuildError if the double could not be converted.
    """
    try:
        return struct.pack('>d', val)
    except struct.error as e:
        raise OscBuildError(f'Wrong argument value passed: {e}')


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
            raise OscParseError('Datagram is too short')
        return (
            struct.unpack('>d',
                        dgram[start_index:start_index + _DOUBLE_DGRAM_LEN])[0],
            start_index + _DOUBLE_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise OscParseError('Could not parse datagram {}'.format(e))


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
        raise OscParseError('Datagram is too short.')
    return dgram[int_offset:int_offset + size], int_offset + total_size


def write_blob(val: bytes) -> bytes:
    """Returns the datagram for the given blob parameter value.

    Raises:
    - BuildError if the value was empty or if its size didn't fit an OSC int.
    """
    if not val:
        raise OscBuildError('Blob value cannot be empty')
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
        raise OscParseError('Datagram is too short')
    timetag, start_index = get_uint64(dgram, start_index)
    seconds = timetag * _NTP_TIMESTAMP_TO_SECONDS
    return ntp_time_to_system_epoch(seconds), start_index


def write_date(system_time: Union[int, float]) -> bytes:
    if system_time == IMMEDIATELY:
        return IMMEDIATELY

    try:
        return system_time_to_ntp(system_time)
    except NtpError as ntpe:
        raise OscBuildError(ntpe)


def write_rgba(val: bytes) -> bytes:
    """Returns the datagram for the given rgba32 parameter value

    Raises:
    - BuildError if the int could not be converted.
    """
    try:
        return struct.pack('>I', val)
    except struct.error as e:
        raise OscBuildError('Wrong argument value passed: {}'.format(e))


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
            raise OscParseError('Datagram is too short')
        return (
            struct.unpack('>I',
                        dgram[start_index:start_index + _INT_DGRAM_LEN])[0],
            start_index + _INT_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise OscParseError(f'Could not parse datagram {e}')


def write_midi(val: MidiPacket) -> bytes:
    """Returns the datagram for the given MIDI message parameter value

    A valid MIDI message: (port id, status byte, data1, data2).

    Raises:
    - BuildError if the MIDI message could not be converted.

    """
    if len(val) != 4:
        raise OscBuildError('MIDI message length is invalid')
    try:
        value = sum((value & 0xFF) << 8 * (3 - pos) for pos, value in enumerate(val))
        return struct.pack('>I', value)
    except struct.error as e:
        raise OscBuildError('Wrong argument value passed: {}'.format(e))


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
            raise OscParseError('Datagram is too short')
        val = struct.unpack('>I',
                            dgram[start_index:start_index + _INT_DGRAM_LEN])[0]
        midi_msg = cast(
            MidiPacket,
            tuple((val & 0xFF << 8 * i) >> 8 * i for i in range(3, -1, -1)))
        return (midi_msg, start_index + _INT_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise OscParseError(f'Could not parse datagram {e}')





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
                        raise OscParseError(f'Unexpected closing bracket in type tag: {type_tag}')
                    param_stack.pop()
                # TODO: Support more exotic types as described in the specification.
                else:
                    logging.getLogger("system").warning(f'Unhandled parameter type: {param}')
                    continue
                if param not in "[]":
                    param_stack[-1].append(val)
            if len(param_stack) != 1:
                raise OscParseError('Missing closing bracket in type tag: {0}'.format(type_tag))
            self._parameters = params
        except OscParseError as pe:
            raise OscParseError('Found incorrect datagram, ignoring it', pe)

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
                raise OscParseError(
                    'OSC Packet should at least contain an OscMessage or an '
                    'OscBundle.')
        except (OscParseError, OscParseError) as e:
            raise OscParseError(f'Could not parse packet {e}')

    @property
    def messages(self) -> List:
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
        except OscParseError as e:
            raise OscParseError(f"Could not get the date from the datagram: {e}")
        # Get the contents as a list of OscBundle and OscMessage.
        self._contents = self._parse_contents(index)

    def _parse_contents(self, index: int) -> list:
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
                    logging.warning(f"Could not identify content type of dgram {content_dgram}")
        except (OscParseError, OscParseError, IndexError) as e:
            raise OscParseError(f"Could not parse a content datagram: {e}")

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


class OscBuildError(Exception):
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

    def add_content(self, content) -> None:
        """Add a new content to this bundle.

        Args:
        - content: Either an OscBundle or an OscMessage
        """
        self._contents.append(content)

    def build(self):
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
                    raise OscBuildError(
                        "Content must be either OscBundle or OscMessage"
                        "found {}".format(type(content)))
            return OscBundle(dgram)
        except OscBuildError as be:
            raise OscBuildError(f'Could not build the bundle {be}')




### OSC MESSAGE BUILDER ###

"""Build OSC messages for client applications."""


ArgValue = Union[str, bytes, bool, int, float, MidiPacket, list]

class OscBuildError(Exception):
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
    def args(self) -> list:
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

    def add_arg(self, arg_value, arg_type: Optional[str] = None) -> None:
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
                'arg_type must be one of {}, or an array of valid types'
                    .format(self._SUPPORTED_ARG_TYPES))
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
    def _get_arg_type(self, arg_value) -> Union[str, Any]:
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

    def build(self): #-> OscMessage:
        """Builds an OscMessage from the current state of this builder.

        Raises:
        - BuildError: if the message could not be build or if the address
                        was empty.

        Returns:
        - an OscMessage instance.
        """
        if not self._address:
            raise OscBuildError('OSC addresses cannot be empty')
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
                    raise OscBuildError(f'Incorrect parameter type found {arg_type}')

            return OscMessage(dgram)
        except OscBuildError as be:
            raise OscBuildError(f'Could not build the message: {be}')





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

    def invoke(self, client_address: Tuple[str, int], message) -> None:
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


class OscDispatcher(object):
    """Maps Handlers to OSC addresses and dispatches messages to the handler on matched addresses

    Maps OSC addresses to handler functions and invokes the correct handler when a message comes in.
    """

    def __init__(self) -> None:
        self._map = collections.defaultdict(list)  # type: DefaultDict[str, List[Handler]]
        self._default_handler = None  # type: Optional[Handler]

    def map(self, address: str, handler: Callable, *args: Union[Any, List[Any]],
            needs_reply_address: bool = False):
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
    def unmap(self, address: str, handler) -> None:
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
                raise ValueError(f"Address '{address}' doesn't have handler '{handler}' mapped to it") from e

    def handlers_for_address(self, address_pattern: str):
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
        pattern = pattern.replace(r'\*', r'[\w|\+]*')
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
        except OscParseError:
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

    def __init__(self, server_address: Tuple[str, int], dispatcher, bind_and_activate: bool = True) -> None:
        """Initialize

        Args:
            server_address: IP and port of server
            dispatcher: Dispatcher this server will use
            (optional) bind_and_activate: default=True defines if the server has to start on call of constructor  
        """
        super().__init__(server_address, _UDPHandler, bind_and_activate)
        self._dispatcher = dispatcher

    def verify_request(self, request, client_address) -> bool:
        """Returns true if the data looks like a valid OSC UDP datagram

        Args:
            request: Incoming data
            client_address: IP and port of client this message came from

        Returns:
            True if request is OSC bundle or OSC message
        """
        return _is_valid_request(request)

    @property
    def dispatcher(self):
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

    def __init__(self, server_address: Tuple[str, int], dispatcher, loop: BaseEventLoop) -> None:
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

        def __init__(self, dispatcher) -> None:
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
    def dispatcher(self):
        return self._dispatcher


### UDP CLIENT ###

"""UDP Clients for sending OSC messages to an OSC server"""

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

    def send(self, content) -> None:
        """Sends an :class:`OscMessage` or :class:`OscBundle` via UDP

        Args:
            content: Message or bundle to be sent
        """
        self._sock.sendto(content.dgram, (self._address, self._port))


class SimpleUDPClient(UDPClient):
    """Simple OSC client that automatically builds :class:`OscMessage` from arguments"""

    def send_message(self, address: str, value) -> None:
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


class OscServer():

    def thread_loop(self):
        ''' main threading loop '''
        
        #logging.getLogger("system").info("OSC: server starting")
        self._dispatcher = OscDispatcher()
        self._dispatcher.set_default_handler(self._callback)
        self._server = BlockingOSCUDPServer((self._host_ip, self._input_port), self._dispatcher)
        
        # this blocks until the server is shutdown
        logging.getLogger("system").info("OSC: server running")

        # this runs after the server has shutdown
        self._server.serve_forever()  # Blocks forever
        logging.getLogger("system").info("OSC: server shutdown")
        self._server = None



    def __init__(self):
        #logging.getLogger("system").info("OSC: server init")
        self._server = None
        self._server_thread = None
        self._stop = False
        self._running = False
        self._missed_count = 0
        self._start_requested = False
        self._lock = threading.Lock()
        self._server_thread = threading.Thread(target=self.thread_loop)
        self._host_ip = None
        self._input_port = None
        self._dispatcher = None
        self._callback = None

    @property
    def started(self):
        ''' true if server is started or in the process of starting '''
        if self._lock.locked():
            logging.getLogger("system").info("OSC: server locked")
            return True
        
        return self._running

    def start(self, host_ip, input_port, callback):
        ''' starts the server on IP and port 
        
        :param host_ip = ip address of server in format xxx.xxx.xxx.xxx
        :param input_port = input port
        :param callback = the callback to call when a message arrives
        
        '''

        with self._lock:
            # everything here is now locked until the server start is completed

            #logging.getLogger("system").info("OSC: start requested")
            if self._running:
                return
            
            self._host_ip = host_ip
            self._input_port = input_port
            self._callback = callback
            
            self._stop = False
            self._server_thread = threading.Thread(target=self.thread_loop)
            self._server_thread.start()
            self._running = True



    def stop(self):
        ''' stops the server '''
        if not self._running or self._start_requested:
            return
        #logging.getLogger("system").info("OSC: stop requested")
        self._stop = True
        if self._server:
            self._server.shutdown()
        self._server_thread.join()
        self._server_thread = None
        self._running = False
        #logging.getLogger("system").info("OSC: server stopped")

    def __del__(self):
        #logging.getLogger("system").info("OSC stopping...")
        self.stop()

    


    
'''  OscInterface ================================================================================================== '''

    
@SingletonDecorator
class OscInterface(QtCore.QObject):
    ''' GremlinEX Open Sound Control interface '''

    osc_message = QtCore.Signal(str, object ) # signal on receiving an osc message

    def __init__(self):
        super().__init__()


        #self._host_ip = "192.168.1.59"
        # host OSC listen port (UDP) - make sure the host's firewall allows that port in
        self._input_port = gremlin.config.Configuration().osc_port
        self._output_port = self._input_port + 1
        self._osc_server = OscServer() # the OSC server

        # find our current IP address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            s.connect(('10.254.254.254', 1)) # dummy address
            self._host_ip = s.getsockname()[0]
        except Exception:
            self._host_ip= '127.0.0.1'
        finally:
            s.close()
        
        logging.getLogger("system").info(f"OSC: found local IP: {self._host_ip}")

        self._started = False


    @property
    def input_port(self):
        ''' UDP input port to use for OSC messages - default is 8000 '''
        return self._input_port
    
    @input_port.setter
    def input_port(self, value):
        self._input_port = value

    @property
    def output_port(self):
        ''' UDP output port to use for OSC messages - default is 8001 '''
        return self._output_port
    
    @output_port.setter
    def output_port(self, value):
        self._output_port = value
    
    @property
    def host_ip(self):
        ''' host ip in string form xxx.xxx.xxx.xxx'''
        return self._host_ip
    
    @host_ip.setter
    def host_ip(self, value):
        self._host_ip = value

    def log(msg):
        ''' displays a log message in Gremlin and in the console '''
        logging.getLogger("system").info(msg)

    def _osc_message_handler(self, address, *args):
        ''' handles OSC messages'''
        # logging.getLogger("system").info(f"OSC: {address}: {args}")
        address = address.lower()
        self.osc_message.emit(address, args)
     

    def start(self):
        ''' starts listening to OSC messages '''
        logging.getLogger("system").info(f"OSC: starting server with IP: {self._host_ip} port: {self._input_port} output: {self._output_port}")
        self._osc_server.start(self._host_ip, self._input_port, self._osc_message_handler)

    def stop(self):
        ''' stops listencing to OSC messages '''
        self._osc_server.stop()



''' end OscInterface ================================================================================================== '''

''' GREMLIN UI STUFF '''

class OscInputItem():
    ''' holds OSC input data '''

    class InputMode(enum.Enum):
        ''' possible input modes '''
        Axis = 0  # input is variable
        Button = 1 # input is marked pressed if the value is in the upper range 
        OnChange = 2 # input triggers pressed on any state change

    class CommandMode(enum.Enum):
        ''' OSC command mode = determines how the command key is derived '''
        Message = 0 # only the command part of the message is used (data is variable)
        Data = 1 # the message and arguments are considered


    def __init__(self):
        self.id = uuid.uuid4() # GUID (unique) if loaded from XML - will reload that one
        self._message = None # the OSC message command
        self._message_data = None # the list of values associated with that command
        self._message_data_string = None # the string representation of the data args
        self._mode = OscInputItem.InputMode.Button
        self._command_mode = OscInputItem.CommandMode.Message
        self._title_name = "OSC (not configured)"
        self._display_name =  ""
        self._display_tooltip = "Input configuration not set"
        self._message_key = "" # unique key that identifies this input
        self._min_range = 0.0
        self._max_range = 1.0 

    @property
    def is_axis(self):
        return self._mode == OscInputItem.InputMode.Axis

    @property
    def message(self):
        return self._message
    
    @message.setter
    def message(self, value):
        self._message = value
        self._update()

    
    @property 
    def mode(self):
        ''' input mode '''
        return self._mode
    
    @mode.setter
    def mode(self, value):
        self._mode = value
        self._update()

    
    @property 
    def command_mode(self):
        ''' command mode '''
        return self._command_mode 
    
    @command_mode.setter
    def command_mode(self, value):
        self._command_mode = value
        self._update()

    @property
    def title_name(self):
        ''' title for this input '''
        return self._title_name

    @property
    def display_name(self):
        ''' display name for this input '''
        return self._display_name
    
    @property
    def data(self):
        return self._message_data
    
    @data.setter
    def data(self, value):
        assert isinstance(value, tuple) or isinstance(value, list)
        self._message_data = value
        self._message_data_string = list_to_csv(value)
        self._update()
    
    @property
    def data_string(self):
        ''' string representation of the OSC arguments '''
        return self._message_data_string
    

    @property
    def min_range(self):
        return self._min_range
    
    @min_range.setter
    def min_range(self, value):
        self._min_range = value
    
    @property 
    def max_range(self):
        return self._max_range
    
    @max_range.setter
    def max_range(self, value):
        self._max_range = value

    @property
    def display_tooltip(self):
        ''' detailed tooltip '''
        return self._display_tooltip
    
    @property
    def mode_string(self):
        if self._mode == OscInputItem.InputMode.Axis:
            return "axis"
        if self._mode == OscInputItem.InputMode.Button:
            return "button"
        if self._mode == OscInputItem.InputMode.OnChange:
            return "change"
        
    def _mode_from_string(self, value):
        if value == "axis":
            self._mode = OscInputItem.InputMode.Axis
        elif value == "button":
            self._mode = OscInputItem.InputMode.Button
        elif value == "change":
            self._mode = OscInputItem.InputMode.OnChange
        else:
            raise ValueError(f"mode_from_string(): don't know how to handle {value}")
        

    @property
    def command_mode_string(self):
        return  OscInputItem.command_mode_to_string(self._command_mode)
        
    
    @staticmethod
    def command_mode_to_string(value):
        ''' converts a string to a command mode '''
        if value == OscInputItem.CommandMode.Message:
            return "cmd"
        elif value == OscInputItem.CommandMode.Data:
            return "data"
        # default
        return "cmd"
    
    @staticmethod
    def command_mode_from_string(value):
        if value == "cmd":
            return OscInputItem.CommandMode.Message
        elif value == "data":
            return OscInputItem.CommandMode.Data
        else:
            raise ValueError(f"command_mode_from_string(): don't know how to handle {value}")


    @property
    def message_key(self):
        ''' returns the sorting key for this message '''
        return self._message_key
    
    def _data_to_string(self, data):
        ''' returns a string representation of the data '''
        return list_to_csv(data)
        

    def _string_to_data(self, value):
        ''' converts a string representation of the data to a list of args '''
        return csv_to_list(value)

    def _update(self):
        ''' updates the message key based on the current config '''
        if self._command_mode == OscInputItem.CommandMode.Data:
            self._message_key = f"{self.message} {self._data_to_string(self._data)}"
        elif self._command_mode == OscInputItem.CommandMode.Message:
            self._message_key = self.message
        else:
            raise ValueError(f"_update(): don't know how to handle {self._command_mode}")
        
        # update data string from the raw data
        self._message_data_string = list_to_csv(self._message_data)
        
        self._update_display_name()

    def parse_xml(self, node):
        ''' reads an input item from xml '''
        if node.tag == "input":
            self.id = read_guid(node, "guid")
            self._message = safe_read(node, "cmd", str)
            csv = safe_read(node, "data", str)
            self._message_data = csv_to_list(csv)
            self._mode_from_string(safe_read(node, "mode", str))
            self._command_mode = OscInputItem.command_mode_from_string(safe_read(node,"cmd_mode", str))
            self._min_range = safe_read(node,"min",float, 0.0)
            self._max_range = safe_read(node,"max",float, 1.0)

        self._update()


    def to_xml(self):
        ''' writes the input item to XML'''
        node = ElementTree.Element("input")
        node.set("guid", str(self.id))
        node.set("cmd", self.message)
        node.set("data", list_to_csv(self._message_data))
        node.set("mode", self.mode_string)
        node.set("cmd_mode", self.command_mode_string)
        node.set("min", str(self._min_range))
        node.set("max", str(self._max_range))
        return node
          
   
    def _update_display_name(self):
        
        if self._mode == OscInputItem.InputMode.Button:
                mode_stub = "Button"
        elif self._mode == OscInputItem.InputMode.Axis:
            mode_stub = "Axis"
        elif self._mode == OscInputItem.InputMode.OnChange:
            mode_stub = "Change"
        else:
            mode_stub = f"Unknown: {self._mode}"

        self._title_name = f"OSC input ({mode_stub})"
        if self._command_mode == OscInputItem.CommandMode.Message:
            self._display_name =  f"{self._message}"
        else:
            self._display_name =  f"{self._message}/{self._message_data_string}"
        

    def __hash__(self):
        return str(self.id).__hash__()
    
    def __lt__(self, other):
        ''' used for sorting purposes '''        
        # keep as is (don't sort)
        return False
    
    def __str__(self):
        return self._title_name

    
class OscInputListenerWidget(QtWidgets.QFrame):

    """ opens a centered modal osc message listener dialog
    
        grabs the first OSC message it hears and closes 

        also closes on esc key press 
       
    """

    def __init__(
            self,
            callback,
            host_ip = None,
            input_port = None,
            parent=None
    ):
        """Creates a new instance.

        :param callback the function to pass the key pressed by the
            user to
        :param host_ip = host ip 
        :param input_port = input port

        """
        super().__init__(parent)
        from gremlin.shared_state import set_suspend_input_highlighting


        # setup and listen for the osc message
        self._interface = OscInterface()
        if host_ip:
            # use specified instead of default
            self._interface.host_ip = host_ip
        if input_port:
            # use specified instead of default
            self._interface.input_port = input_port

        self.host_ip = self._interface.host_ip
        self.input_port = self._interface.input_port

        self._interface.osc_message.connect(self._osc_message_cb)
        self._callback = callback
        
        self.message = None
        
        # Create and configure the ui overlay
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(
            QtWidgets.QLabel(f"""<center>Listening to OSC input {self._interface.host_ip} port {self._interface.input_port}.<br/><br/>Press ESC to abort.</center>""")
        )

        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setFrameStyle(QtWidgets.QFrame.Plain | QtWidgets.QFrame.Box)
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColorConstants.DarkGray)
        self.setPalette(palette)

        # Disable ui input selection on joystick input
        push_suspend_highlighting()

        # listen for the escape key
        event_listener = gremlin.event_handler.EventListener()
        event_listener.keyboard_event.connect(self._kb_event_cb)

        # start listening on all ports 
        self._interface.start()


    def _kb_event_cb(self, event):
        from gremlin.keyboard import key_from_code, key_from_name
        key = key_from_code(
                event.identifier[0],
                event.identifier[1]
        )
        if event.is_pressed and key == key_from_name("esc"):

            # stop listening
            self._interface.stop()

            # close the winow
            self.close()

    def _osc_message_cb(self, message, data):
        ''' called when a osc messages is provided by the listener '''
        if self.message is None:
            self.message = message
            self._callback(message, data)

        self.close()



class OscInputConfigDialog(QtWidgets.QDialog):
    ''' dialog showing the OSC input configuration options '''

    def __init__(self, current_mode, index, data, parent):
        '''
        :param index - the input item index zero based
        :param identifier - the input item identifier 
        '''
        
        super().__init__(parent)
        # self._sequence = InputKeyboardModel(sequence=sequence)
        main_layout = QtWidgets.QVBoxLayout()
        self.setWindowTitle("OSC Input Mapper")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self._parent = parent # list view
        assert hasattr(parent, "input_item_list_model"),"OSC CONFIG: Parent widget does not have required listview model"
        assert hasattr(parent, "input_item_list_view"),"OSC CONFIG: Parent widget does not have required listview"

        self.config_widget =  QtWidgets.QWidget()
        self.config_layout = QtWidgets.QHBoxLayout()
        self.config_widget.setLayout(self.config_layout)
        
        self._current_mode = current_mode
        self.index = index
        self.identifier = data
        self._mode = OscInputItem.InputMode.Button
        self._command_mode = OscInputItem.CommandMode.Message
        self._mode_locked = False # if set, prevents flipping input modes axis to a button mode
        self._min_range = 0.0 # min value for axis mapping (maps to -1.0 in vjoy)
        self._max_range = 1.0 # max value for axis mapping (maps to 1.0 in vjoy)

        # midi message
        self._command = None # OSC command text
        self._command_data = [] # OSC arguments

        self._command_widget = QtWidgets.QLineEdit()
        self._data_widget = QtWidgets.QLineEdit()

        self.config_layout.addWidget(QtWidgets.QLabel("Cmd:"))
        self.config_layout.addWidget(self._command_widget)

        self.config_layout.addWidget(QtWidgets.QLabel("Data:"))
        self.config_layout.addWidget(self._data_widget)
        self.config_layout.addStretch()


        self._container_mode_radio_widget = QtWidgets.QWidget()
        self._container_mode_radio_layout = QtWidgets.QHBoxLayout(self._container_mode_radio_widget )
        
        self._container_mode_description_widget = QtWidgets.QLabel()

        self._container_command_mode_radio_widget = QtWidgets.QWidget()
        self._container_command_mode_radio_layout = QtWidgets.QHBoxLayout()
        self._container_command_mode_radio_widget.setLayout(self._container_command_mode_radio_layout)
        self._container_command_mode_description_widget = QtWidgets.QLabel()


        self._mode_button_widget = QtWidgets.QRadioButton("Button")
        self._mode_button_widget.setToolTip("The input will behave as an on/off button based on the value.<br/>" 
                                            "If the value is in the lower half of the range, the button is released.<br>" 
                                            "If the value is in the upper half of the reange, the button will be pressed<br>")
        self._mode_button_widget.clicked.connect(self._mode_button_cb)

        self._mode_axis_widget = QtWidgets.QRadioButton("Axis")
        self._mode_axis_widget.setToolTip("The input will be scaled (-1 to +1) based on the input's value")
        self._mode_axis_widget.clicked.connect(self._mode_axis_cb)

        self._container_range_widget = QtWidgets.QWidget()
        self._container_range_layout = QtWidgets.QHBoxLayout(self._container_range_widget)
        

        self._min_range_widget = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self._min_range_widget.setValue(0.0) # default min range 
        self._min_range_widget.valueChanged.connect(self._min_range_cb)
        self._max_range_widget = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self._max_range_widget.setValue(1.0) # default min range 
        self._min_range_widget.valueChanged.connect(self._max_range_cb)

        self._container_range_layout.addWidget(QtWidgets.QLabel("Min range:"))
        self._container_range_layout.addWidget(self._min_range_widget)
        self._container_range_layout.addWidget(QtWidgets.QLabel("Max range:"))
        self._container_range_layout.addWidget(self._max_range_widget)
        self._container_range_layout.addStretch()

        # validation message
        self._validation_message_widget = gremlin.ui.ui_common.QIconLabel()

        self._container_mode_radio_layout.addWidget(self._mode_axis_widget)

        self._command_mode_message_widget = QtWidgets.QRadioButton("Message only")
        self._command_mode_message_widget.clicked.connect(self._command_mode_message_cb)
        self._command_mode_data_widget = QtWidgets.QRadioButton("Message + data")
        self._command_mode_data_widget.clicked.connect(self._command_mode_data_cb)

        self._mode_on_change_widget = QtWidgets.QRadioButton("Change")
        self._mode_on_change_widget.setToolTip("The input will trigger as button press on any change in value")
        self._mode_on_change_widget.clicked.connect(self._mode_change_cb)
        self._mode_locked_widget = gremlin.ui.ui_common.QIconLabel()

        self._container_mode_radio_layout.addWidget(QtWidgets.QLabel("Action mode:"))
        self._container_mode_radio_layout.addWidget(self._mode_on_change_widget)
        self._container_mode_radio_layout.addWidget(self._mode_button_widget)
        self._container_mode_radio_layout.addWidget(self._mode_axis_widget)
        self._container_mode_radio_layout.addWidget(self._mode_locked_widget)
        self._container_mode_radio_layout.addStretch()


        self._container_command_mode_radio_layout.addWidget(self._command_mode_message_widget)
        self._container_command_mode_radio_layout.addWidget(self._command_mode_data_widget)


        self._container_options_widget = QtWidgets.QWidget()
        self._container_option_layout = QtWidgets.QHBoxLayout()
        self._container_options_widget.setLayout(self._container_option_layout)

        self._container_option_layout.addWidget(self._container_mode_radio_widget)
        self._container_option_layout.addWidget(self._container_command_mode_radio_widget)
        self._container_option_layout.addStretch()


        self.ok_widget = QtWidgets.QPushButton("Ok")
        self.ok_widget.clicked.connect(self._ok_button_cb)

        self.cancel_widget = QtWidgets.QPushButton("Cancel")
        self.cancel_widget.clicked.connect(self._cancel_button_cb)

        self.button_widget = QtWidgets.QWidget()
        self.button_layout = QtWidgets.QHBoxLayout(self.button_widget)
        

        # listen all ports button 
        self.listen_widget = QtWidgets.QPushButton("Listen")
        self.listen_widget.clicked.connect(self._listen_cb)

        self.button_layout.addWidget(self.listen_widget)
        self.button_layout.addStretch(1)
        self.button_layout.addWidget(self.ok_widget)
        self.button_layout.addWidget(self.cancel_widget)

        main_layout.addWidget(QtWidgets.QLabel("OSC message:"))
        main_layout.addWidget(self.config_widget)
        main_layout.addWidget(self._container_options_widget)
        main_layout.addWidget(self._container_range_widget)
        main_layout.addWidget(self._container_mode_description_widget)
        main_layout.addWidget(self._container_command_mode_description_widget)
        main_layout.addWidget(self._validation_message_widget)
        main_layout.addWidget(gremlin.ui.ui_common.QHLine())
        main_layout.addWidget(self.button_widget)
        
        self.setLayout(main_layout)

        if data:
            input_id : OscInputItem = data
            # see if this input has any containers 
            profile = gremlin.shared_state.current_profile
            for device in profile.devices.values():
                if device.name == "midi":
                    if current_mode in device.modes:
                        for input_items in device.modes[current_mode].config.values():
                            if data in input_items:
                                item = input_items[data]
                                self._mode_locked = len(item.containers) > 0 # lock mode to prevent axis to button/change 
                                break

            message = input_id.message
            if message:
                self._mode = input_id.mode
                self._command_mode = input_id.command_mode
                self._command = input_id.message
                self._command_data = input_id.data

        self._validate()
        self._update_display()

    def _validate(self):
        ''' validates the input to ensure it does not conflict with an existing input '''
        # assume ok
        valid = True
        try:
            self._validation_message_widget.setText("")
            if self._command is not None:
                # get the list of all the other inputs
                parent_widget = self._parent
                model = parent_widget.input_item_list_model
                message = self._command
                input_item = OscInputItem()
                input_item._message = message
                input_item._message_data = self._command_data
                input_item._command_mode = self._command_mode
                input_item._mode = self._mode
                input_item._update() # this updates the message key
                key = input_item.message_key
                
                for index in range(model.rows()):
                    widget = parent_widget.itemAt(index)
                    if index == self.index : continue # ignore self
                    # grab the input's configured midi message
                    other_input = widget.identifier.input_id
                    other_message = other_input.message
                    if other_message is None:
                        # input not set = ok
                        continue 

                    other_key = other_input.message_key
                    if key == other_key:
                        logging.getLogger("system").info(f"OSC: conflict detected: key {key} is the same as {other_key}")
                        self._validation_message_widget.setText(f"Input conflict detected with input [{index+1}] - ensure inputs are unique")
                        self._validation_message_widget.setIcon("fa.warning",True, color="red")
                        valid = False
                        return
                        
                    
                if self._mode == OscInputItem.InputMode.Axis:
                    # cannot be an axis mode for sysex or program change
                    
                    valid = len(self._command_data) > 0 # in axis mode, data MUST be provided
                    if not valid:
                        self._validation_message_widget.setText(f"Data value must be given in axis mode")
                        self._validation_message_widget.setIcon("fa.warning",True, color="red")
                        return
                
                    if self._min_range > self._max_range:
                        self._validation_message_widget.setText(f"Min range must be less than max range")
                        self._validation_message_widget.setIcon("fa.warning",True, color="red")
                        return
                    
                    if self._min_range == self._max_range:
                        self._validation_message_widget.setText(f"Min range cannot be the same as the max range")
                        self._validation_message_widget.setIcon("fa.warning",True, color="red")
                        return
                    
                    # ensure the argument is numeric
                    arg = self._command_data[0]
                    if not (isinstance(arg, int) or isinstance(arg, float)):
                        self._validation_message_widget.setText(f"First data item must be a number for axis input")
                        self._validation_message_widget.setIcon("fa.warning",True, color="red")
                        return


            
        finally:
            self.ok_widget.setEnabled(valid)
            self._valid = valid

            if valid:
                # clear error status
                self._validation_message_widget.setText()
                self._validation_message_widget.setIcon()

        return valid


    def _mode_axis_cb(self):
        if self._mode_axis_widget.isChecked():
            self._mode = OscInputItem.InputMode.Axis
            self._validate()
            self._update_display()           

    def _mode_button_cb(self):
        if self._mode_button_widget.isChecked():
            self._mode = OscInputItem.InputMode.Button
            self._update_display()             

    def _mode_change_cb(self):
        if self._mode_on_change_widget.isChecked():
            self._mode = OscInputItem.InputMode.OnChange
            self._update_display()

    def _command_mode_message_cb(self):
        if self._command_mode_message_widget.isChecked():
            self._command_mode = OscInputItem.CommandMode.Message
            self._update_display()

    def _command_mode_data_cb(self):
        if self._command_mode_data_widget.isChecked():
            self._command_mode = OscInputItem.CommandMode.Data
            self._update_display()

    def _min_range_cb(self):
        self._min_range = self._min_range_widget.value()
        self._validate()

    def _max_range_cb(self):
        self._min_range = self._max_range_widget.value()  
        self._validate()     


    @property
    def min_range(self):
        return self._min_range
    
    @min_range.setter
    def min_range(self, value):
        self._min_range = value
    
    @property 
    def max_range(self):
        return self._max_range
    
    @max_range.setter
    def max_range(self, value):
        self._max_range = value

    def _update_display(self):
        ''' loads message data into the UI '''
           # mode radio buttons
        if self._mode == OscInputItem.InputMode.Button:
            self._container_mode_description_widget.setText(f"The input will trigger a button press when the value is 1<br>Use this to trigger a button press from a specific OSC message.")
            with QtCore.QSignalBlocker(self._mode_button_widget):
                self._mode_button_widget.setChecked(True)
        elif self._mode == OscInputItem.InputMode.Axis:
            self._container_mode_description_widget.setText(f"The input act as an axis input using the OSC value.<br>Use this mode if mapping to an axis output (OSC value messages only)")
            self._command_mode = OscInputItem.CommandMode.Message # force message mode in axis as the value will determine the state
            with QtCore.QSignalBlocker(self._mode_axis_widget):
                self._mode_axis_widget.setChecked(True)
            
        elif self._mode == OscInputItem.InputMode.OnChange:
            self._container_mode_description_widget.setText(f"The input will trigger a button press on any value change<br>Use this mode to trigger a button or action whenever the MIDI command value changes.")
            with QtCore.QSignalBlocker(self._mode_on_change_widget):
                self._mode_on_change_widget.setChecked(True)      

        if self._command_mode == OscInputItem.CommandMode.Message:
            self._container_command_mode_description_widget.setText(f"The OSC message is the primary input (data ignored)")
            with QtCore.QSignalBlocker(self._command_mode_message_widget):
                self._command_mode_message_widget.setChecked(True)
                self._data_widget.setEnabled(False) # disable the value area if in message only mode
        elif self._command_mode == OscInputItem.CommandMode.Data:
            self._container_command_mode_description_widget.setText(f"The OSC message and arguments are used as the primary input")
            with QtCore.QSignalBlocker(self._command_mode_data_widget):
                self._command_mode_data_widget.setChecked(True)
            self._data_widget.setEnabled(True) # enable the value area if in message + data mode

        self._container_range_widget.setVisible(self._mode == OscInputItem.InputMode.Axis)
        self._command_widget.setText(self._command)
        csv = list_to_csv(self._command_data)
        self._data_widget.setText(csv)

    def _update_message(self):
        ''' updates message data from UI '''
        if self._mode_button_widget.isChecked():
            mode = OscInputItem.InputMode.Button
        elif self._mode_axis_widget.isChecked():
            mode = OscInputItem.InputMode.Axis
        elif self._mode_on_change_widget.isChecked():
            mode = OscInputItem.InputMode.OnChange

        if self._command_mode_message_widget.isChecked():
            command_mode = OscInputItem.CommandMode.Message
        elif self._command_mode_data_widget.isChecked():
            command_mode = OscInputItem.CommandMode.Data

        self._mode = mode
        self._command_mode = command_mode
        self._command = self._command_widget.text()
        self._command_data = csv_to_list(self._data_widget.text())


    def _ok_button_cb(self):
        ''' ok button pressed '''
        self._update_message() # update data from UI
        self.accept()
        
    def _cancel_button_cb(self):
        ''' cancel button pressed '''
        self.reject()        
    

    def _listen_cb(self, current_port_only = False):
        ''' listens to an inbound OSC message '''


        self.listener_dialog = OscInputListenerWidget(self._capture_message)

        # Display the dialog centered in the middle of the UI
        root = self
        while root.parent():
            root = root.parent()
        geom = root.geometry()

        self.listener_dialog.setGeometry(
            int(geom.x() + geom.width() / 2 - 150),
            int(geom.y() + geom.height() / 2 - 75),
            300,
            150
        )
        self.listener_dialog.show()               

    def _capture_message(self, command, data) :
        ''' called when an OSC message is captured '''
        self._command = command
        self._command_data = data
        self._validate()
        self._update_display() # update UI with these settings

    @property
    def command(self):
        ''' returns the current command '''
        return self._command
    
    @command.setter
    def command(self, value):
        if value is None:
            value = "" # catch None type
        self._command = value
        self._update_display()

    @property
    def mode(self):
        ''' gets the current input mode '''
        return self._mode
    
    @mode.setter
    def mode(self, value):
        self._mode = value
        self._update_display()

    @property
    def command_mode(self):
        ''' returns the command type'''
        return self._command_mode
    
    @command_mode.setter
    def command_mode(self, value):
        self._command_mode = value
        self._update_display()

    @property
    def data(self) -> list:
        ''' returns a list of parameters for that command '''
        return self._command_data
    
    @data.setter
    def data(self, value):
        self._command_data = value
        self._update_display()  

from gremlin.ui.qdatawidget import QDataWidget

class OscDeviceTabWidget(QDataWidget):

    """Widget used to configure open sound control (OSC) inputs """
    
    # IMPORTANT: MUST BE A DID FORMATTED ID ON CUSTOM INPUTS
    device_guid = parse_guid('ccb486e8-808e-4b3f-abe7-bcb380f39aa4')

    def __init__(
            self,
            device_profile,
            current_mode,
            parent=None
    ):
        """Creates a new object instance.

        :param device_profile profile data of the entire device
        :param current_mode currently active mode
        :param parent the parent of this widget
        """
        super().__init__(parent)
        import gremlin.ui.ui_common as ui_common
        import gremlin.ui.input_item as input_item

        # Store parameters
        self.device_profile = device_profile
        self.current_mode = current_mode

        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.left_panel_layout = QtWidgets.QVBoxLayout()
        self.device_profile.ensure_mode_exists(self.current_mode)
        self.widget_storage = {}

        # List of inputs
        self.input_item_list_model = input_item.InputItemListModel(
            device_profile,
            current_mode,
            [InputType.OpenSoundControl] # only allow OSC inputs for this widget
        )

        # update the display names 

        self.input_item_list_view = input_item.InputItemListView(custom_widget_handler=self._custom_widget_handler)
        self.input_item_list_view.setMinimumWidth(350)

        # Input type specific setups
        self.input_item_list_view.set_model(self.input_item_list_model)
        self.input_item_list_view.updated.connect(self._update_conflicts)
        self.input_item_list_view.redraw()

        # Handle user interaction
        self.input_item_list_view.item_selected.connect(self._select_item_cb)
        self.input_item_list_view.item_edit.connect(self._edit_item_cb)
        self.input_item_list_view.item_closed.connect(self._close_item_cb)


        self.left_panel_layout.addWidget(self.input_item_list_view)
        self.main_layout.addLayout(self.left_panel_layout,1)

        # add a blank input configuration if nothing is selected - the configuration widget is always the second widget of the main layout
        right_panel = self.main_layout.takeAt(1)
        if right_panel is not None and right_panel.widget():
            right_panel.widget().hide()
            right_panel.widget().deleteLater()
        if right_panel:
            self.main_layout.removeItem(right_panel)

        widget = gremlin.ui.device_tab.InputItemConfiguration()     
        self.main_layout.addWidget(widget,3)

        button_container_widget = QtWidgets.QWidget()
        button_container_layout = QtWidgets.QHBoxLayout(button_container_widget)
        

        # key clear button
        
        clear_keyboard_button = ui_common.ConfirmPushButton("Clear OSC Inputs", show_callback = self._show_clear_cb)
        clear_keyboard_button.confirmed.connect(self._clear_inputs_cb)
        button_container_layout.addWidget(clear_keyboard_button)
        button_container_layout.addStretch(1)

        # Key add button
        button = QtWidgets.QPushButton("Add OSC Input")
        button.clicked.connect(self._add_input_cb)

        button_container_layout.addWidget(button)

        self.left_panel_layout.addWidget(button_container_widget)
        

        # Select default entry
        selected_index = self.input_item_list_view.current_index
        if selected_index is not None:
            self._select_item_cb(selected_index)

    def itemAt(self, index):
        ''' returns the input widget at the given index '''
        return self.input_item_list_view.itemAt(index)

    def display_name(self, input_id):
        ''' returns the name for the given input ID '''
        return input_id.display_name

    def _show_clear_cb(self):
        return self.input_item_list_model.rows() > 0

    def _clear_inputs_cb(self):
        ''' clears all input keys '''
        self.input_item_list_model.clear(input_types=[InputType.OpenSoundControl])
        self.input_item_list_view.redraw()

        # add a blank input configuration if nothing is selected - the configuration widget is always the second widget of the main layout
        right_panel = self.main_layout.takeAt(1)
        if right_panel is not None and right_panel.widget():
            right_panel.widget().hide()
            right_panel.widget().deleteLater()
        if right_panel:
            self.main_layout.removeItem(right_panel)

        widget = gremlin.ui.device_tab.InputItemConfiguration()     
        self.main_layout.addWidget(widget,3)  
  
    def _add_input_cb(self):
        """Adds a new input to the inputs list  """
        input_type = InputType.OpenSoundControl
        input_id = OscInputItem()
        self.device_profile.modes[self.current_mode].get_data(input_type, input_id)
        self.input_item_list_model.refresh()
        self.input_item_list_view.redraw()
        self.input_item_list_view.select_item(self._index_for_key(input_id),True)
        
        index = self.input_item_list_view.current_index

        # redraw the UI
        self._select_item_cb(index)

        # auto edit new input
        self._edit_item_cb(None, index, input_id)


    def _index_for_key(self, input_id):
        ''' returns the index of the selected input id'''
        mode = self.device_profile.modes[self.current_mode]
        sorted_keys = list(mode.config[InputType.OpenSoundControl].keys())
        return sorted_keys.index(input_id)
    

    def _select_item_cb(self, index):
        """Handles the selection of an input item.

        :param index the index of the selected item
        """

        if index == -1:
            # nothing to select
            return 
        
        
        with QtCore.QSignalBlocker(self.input_item_list_view):
            self.input_item_list_view.select_item(index, False)
        

        right_panel = self.main_layout.takeAt(1)
        if right_panel is not None and right_panel.widget():
            right_panel.widget().hide()
            right_panel.widget().deleteLater()
        if right_panel:
            self.main_layout.removeItem(right_panel)

        item_data = self.input_item_list_model.data(index)
        widget = gremlin.ui.device_tab.InputItemConfiguration(item_data)
        self.main_layout.addWidget(widget,3)            

        if item_data:
            
            # Create new configuration widget
            
            change_cb = self._create_change_cb(index)
            widget.action_model.data_changed.connect(change_cb)
            widget.description_changed.connect(change_cb)
    

    def _close_item_cb(self, widget, index, data):
        ''' called when the close button is clicked '''

        # show a warning before deleting an input
        self.input_item_list_model(index)
        self.input_item_list_view.redraw()
        

    def _custom_widget_handler(self, list_view, index : int, identifier, data, parent = None):
        ''' creates a widget for the input 
        
        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item
        
        '''
        import gremlin.ui.input_item

        widget = gremlin.ui.input_item.InputItemWidget(identifier = identifier, populate_ui_callback = self._populate_input_widget_ui, update_callback = self._update_input_widget, config_external=True, parent = parent)
        #identifier = identifier.input_id
        widget.create_action_icons(data)
        widget.setDescription(data.description)
        widget.enable_close()
        widget.enable_edit()
        widget.setIcon("mdi.surround-sound")
        # remember what widget is at what index
        widget.index = index
        return widget
    


    def _update_conflicts(self):
         # check for conflicts with other entries
        model = self.input_item_list_model
        
        widgets = [self.itemAt(index) for index in range(model.rows())]
        compared_widgets = []
        conflicted_widgets = []
        for input_widget in widgets: 
            input_widget_index = widgets.index(input_widget)
            key = input_widget.identifier.input_id.message_key
            compare_widgets = [w for w in widgets if w != input_widget]
            for widget in compare_widgets:
                if not widget:
                    continue
                if (input_widget, widgets) in compared_widgets:
                    continue 
                if (widget, input_widget) in compared_widgets:
                    continue 
                compared_widgets.append((input_widget, widget))

                # grab the input's configured OSC message
                other_input = widget.identifier.input_id
                other_message = other_input.message
                if other_message is None:
                    # input not set = ok
                    continue 

                other_key = other_input.message_key
                if key == other_key:
                    index = widgets.index(widget)
                    self._set_status(widget,"fa.warning", f"Input conflict detected with input [{input_widget_index + 1}]", color = "red")
                    self._set_status(input_widget,"fa.warning", f"Input conflict detected with input [{index + 1}]", color = "red")
                    conflicted_widgets.append(widget)
                    conflicted_widgets.append(input_widget)
                    break

        ok_widgets = [widget for widget in widgets if not widget in conflicted_widgets]
        for widget in ok_widgets:
            self._set_status(widget)    
    
    def _set_status(self, widget, icon = None, status = None, use_qta = True, color = None):
        ''' sets the status of an input widget '''
        status_widget = widget.findChild(gremlin.ui.ui_common.QIconLabel, "status")
        if color:
            status_widget.setIcon(icon, use_qta = use_qta, color = color)
        else:
            status_widget.setIcon(icon, use_qta = use_qta)
        
        status_widget.setText(status)
        status_widget.setVisible(status is not None)    


    def _update_input_widget(self, input_widget, container_widget):
        ''' called when the widget has to update itself on a data change '''
        data = input_widget.identifier.input_id 
        input_widget.setTitle(data.title_name)
        input_widget.setInputDescription(data.display_name)
        input_widget.setToolTip(data.display_tooltip)

        status_text = ''
        is_warning = False
        if not data.message:
            is_warning = True
            status_text = "Not configured"
       

        status_widget = container_widget.findChild(gremlin.ui.ui_common.QIconLabel, "status")
        if is_warning:
            status_widget.setIcon("fa.warning", use_qta=True, color="red")
        else:
            status_widget.setIcon() # clear it

        status_widget.setText(status_text)
 

    def _populate_input_widget_ui(self, input_widget, container_widget, data):
        ''' called when a button is created for custom content '''
        layout = QtWidgets.QVBoxLayout(container_widget)
        status_widget = gremlin.ui.ui_common.QIconLabel()
        status_widget.setObjectName("status")
        layout.addWidget(status_widget)
        self._update_input_widget(input_widget, container_widget)


    def _edit_item_cb(self, widget, index, data):
        ''' called when the edit button is clicked  '''
        self._edit_dialog = OscInputConfigDialog(self.current_mode, index, data, self)
        self._edit_dialog.accepted.connect(self._dialog_ok_cb)
        self._edit_dialog.showNormal()

    def _dialog_ok_cb(self):
        ''' called when the ok button is pressed on the edit dialog '''
        message = self._edit_dialog.command
        data = self._edit_dialog.data
        index = self._edit_dialog.index
        mode = self._edit_dialog.mode
        command_mode = self._edit_dialog.command_mode
        min_range = self._edit_dialog.min_range
        max_range = self._edit_dialog.max_range
        

        identifier = self.input_item_list_model.data(index)
        input_item : OscInputItem = identifier.input_id
        input_item._message = message # OSC command message as text
        input_item._message_data = data  # arguments as a list
        input_item._mode = mode
        input_item._command_mode = command_mode
        input_item._min_range = min_range
        input_item._max_range = max_range
        input_item._update() # refresh other properties

        self.input_item_list_view.update_item(index)

    def _index_for_key(self, input_id):
        ''' returns the index of the selected input id'''
        mode = self.device_profile.modes[self.current_mode]
        sorted_keys = list(mode.config[InputType.OpenSoundControl].keys())
        return sorted_keys.index(input_id)
        

    def _create_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.input_item_list_view.redraw_index(index)

    def set_mode(self, mode):
        ''' changes the mode of the tab '''        
        self.current_mode = mode
        self.device_profile.ensure_mode_exists(self.current_mode)
        self.input_item_list_model.mode = mode
        self.input_item_list_model.refresh()
        self.input_item_list_view.redraw()        
        self.input_item_list_view.select_item(-1)

    def mode_changed_cb(self, mode):
        """Handles mode change.

        :param mode the new mode
        """
        self.set_mode(mode)


    def refresh(self):
        """Refreshes the current selection, ensuring proper synchronization."""
        self._select_item_cb(self.input_item_list_view.current_index)
