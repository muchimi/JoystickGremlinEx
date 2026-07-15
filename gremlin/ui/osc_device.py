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

from __future__ import annotations  # deprecated with python 3.14+
import logging

from PySide6 import QtWidgets, QtCore, QtGui
import threading

import gremlin.config
import gremlin.event_handler

import gremlin.input_devices
import gremlin.joystick_handling
import gremlin.ui.ui_common as ui_common
import gremlin.shared_state
from gremlin.types import DeviceType, EventSourceType
from gremlin.input_types import InputType
from gremlin.input_item import InputItem, InputIdentifier, InputItemWidget, InputItemListView, BaseDeviceTabWidget
from gremlin.util import read_guid, safe_read, safe_format, list_to_csv, csv_to_list
import gremlin.base_profile
import uuid
from gremlin.singleton_decorator import SingletonDecorator
import collections
import re
import time
from typing import (
    overload,
    List,
    Any,
    Tuple,
    Callable,
    Optional,
    Iterator,
    Union,
    cast,
    Coroutine,
    NamedTuple,
)
import asyncio
from asyncio import BaseEventLoop
import fnmatch
import socketserver
import socket
from socket import socket as _socket
import os
from collections.abc import Iterable
import struct
from datetime import datetime, timedelta

import gremlin.ui.ui_common
from shiboken6 import Shiboken
from lxml import etree as ElementTree

import enum

# from gremlin.base_classes import AbstractInputItem
import gremlin.util
from psygnal import Signal


syslog = logging.getLogger("system")

### OSC handler start -------------------------------------------------------
# Adapted from: Python-OSC  https://github.com/attwad/python-osc
# Credits go to AttWad
# ####


### ----------------------------------------------------------- OSC server stuff ----------------------------------------------------------


### PARSING ###


"""Parsing and conversion of NTP dates contained in datagrams."""


# 63 zero bits followed by a one in the least signifigant bit is a special
# case meaning "immediately."
IMMEDIATELY = struct.pack(">Q", 1)

# timetag * (1 / 2 ** 32) == l32bits + (r32bits / 1 ** 32)
_NTP_TIMESTAMP_TO_SECONDS = 1.0 / 2.0**32.0
_SECONDS_TO_NTP_TIMESTAMP = 2.0**32.0

# From NTP lib.
_SYSTEM_EPOCH = datetime(*time.gmtime(0)[0:3])
_NTP_EPOCH = datetime(1900, 1, 1)
# _NTP_DELTA is 2208988800
_NTP_DELTA = (_SYSTEM_EPOCH - _NTP_EPOCH).days * 24 * 3600


Timestamp = NamedTuple(
    "Timestamp",
    [
        ("seconds", int),
        ("fraction", int),
    ],
)


class NtpError(Exception):
    """Base class for ntp module errors."""

    pass


def parse_timestamp(timestamp: int) -> Timestamp:
    """Parse NTP timestamp as Timetag."""
    seconds = timestamp >> 32
    fraction = timestamp & 0xFFFFFFFF
    return Timestamp(seconds, fraction)


def ntp_to_system_time(timestamp: bytes) -> float:
    """Convert a NTP timestamp to system time in seconds."""
    try:
        timestamp = struct.unpack(">Q", timestamp)[0]
    except Exception as e:
        raise NtpError(e)
    return timestamp * _NTP_TIMESTAMP_TO_SECONDS - _NTP_DELTA


def system_time_to_ntp(seconds: float) -> bytes:
    """Convert a system time in seconds to NTP timestamp."""
    try:
        seconds = seconds + _NTP_DELTA
    except TypeError as e:
        raise NtpError(e)
    return struct.pack(">Q", int(seconds * _SECONDS_TO_NTP_TIMESTAMP))


def ntp_time_to_system_epoch(seconds: float) -> float:
    """Convert a NTP time in seconds to system time in seconds."""
    return seconds - _NTP_DELTA


def system_time_to_ntp_epoch(seconds: float) -> float:
    """Convert a system time in seconds to NTP time in seconds."""
    return seconds + _NTP_DELTA


MidiPacket = Tuple[int, int, int, int]


class OscParseError(Exception):
    """Base exception for when a datagram parsing error occurs."""


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
_EMPTY_STR_DGRAM = b"\x00\x00\x00\x00"


def write_string(val: str) -> bytes:
    """Returns the OSC string equivalent of the given python string.

    Raises:
    - BuildError if the string could not be encoded.
    """
    try:
        dgram = val.encode("utf-8")  # Default, but better be explicit.
    except (UnicodeEncodeError, AttributeError) as e:
        raise OscBuildError("Incorrect string, could not encode {}".format(e))
    diff = _STRING_DGRAM_PAD - (len(dgram) % _STRING_DGRAM_PAD)
    dgram += b"\x00" * diff
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
        raise OscParseError("start_index < 0")
    offset = 0
    try:
        if len(dgram) > start_index + _STRING_DGRAM_PAD and dgram[start_index + _STRING_DGRAM_PAD] == _EMPTY_STR_DGRAM:
            return "", start_index + _STRING_DGRAM_PAD
        while dgram[start_index + offset] != 0:
            offset += 1
        # Align to a byte word.
        if (offset) % _STRING_DGRAM_PAD == 0:
            offset += _STRING_DGRAM_PAD
        else:
            offset += -offset % _STRING_DGRAM_PAD
        # Python slices do not raise an IndexError past the last index,
        # do it ourselves.
        if offset > len(dgram[start_index:]):
            raise OscParseError("Datagram is too short")
        data_str = dgram[start_index : start_index + offset]
        return data_str.replace(b"\x00", b"").decode("utf-8"), start_index + offset
    except IndexError as ie:
        raise OscParseError(f"Could not parse datagram {ie}")
    except TypeError as te:
        raise OscParseError(f"Could not parse datagram {te}")


def write_int(val: int) -> bytes:
    """Returns the datagram for the given integer parameter value

    Raises:
    - BuildError if the int could not be converted.
    """
    try:
        return struct.pack(">i", val)
    except struct.error as e:
        raise OscBuildError(f"Wrong argument value passed: {e}")


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
            raise OscParseError("Datagram is too short")
        return (
            struct.unpack(">i", dgram[start_index : start_index + _INT_DGRAM_LEN])[0],
            start_index + _INT_DGRAM_LEN,
        )
    except (struct.error, TypeError) as e:
        raise OscParseError(f"Could not parse datagram {e}")


def write_int64(val: int) -> bytes:
    """Returns the datagram for the given 64-bit big-endian signed parameter value

    Raises:
    - BuildError if the int64 could not be converted.
    """
    try:
        return struct.pack(">q", val)
    except struct.error as e:
        raise OscBuildError(f"Wrong argument value passed: {e}")


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
            raise OscParseError("Datagram is too short")
        return (
            struct.unpack(">q", dgram[start_index : start_index + _INT64_DGRAM_LEN])[0],
            start_index + _INT64_DGRAM_LEN,
        )
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
            raise OscParseError("Datagram is too short")
        return (
            struct.unpack(">Q", dgram[start_index : start_index + _UINT64_DGRAM_LEN])[0],
            start_index + _UINT64_DGRAM_LEN,
        )
    except (struct.error, TypeError) as e:
        raise OscParseError(f"Could not parse datagram {e}")


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
            raise OscParseError("Datagram is too short")

        timetag, _ = get_uint64(dgram, start_index)
        seconds, fraction = parse_timestamp(timetag)

        hours, seconds = seconds // 3600, seconds % 3600
        minutes, seconds = seconds // 60, seconds % 60

        utc = datetime.combine(_NTP_EPOCH, datetime.min.time()) + timedelta(hours=hours, minutes=minutes, seconds=seconds)

        return (utc, fraction), start_index + _TIMETAG_DGRAM_LEN
    except (struct.error, TypeError) as e:
        raise OscParseError(f"Could not parse datagram {e}")


def write_float(val: float) -> bytes:
    """Returns the datagram for the given float parameter value

    Raises:
    - BuildError if the float could not be converted.
    """
    try:
        return struct.pack(">f", val)
    except struct.error as e:
        raise OscBuildError(f"Wrong argument value passed: {e}")


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
            dgram = dgram + b"\x00" * (_FLOAT_DGRAM_LEN - len(dgram[start_index:]))
        return (
            struct.unpack(">f", dgram[start_index : start_index + _FLOAT_DGRAM_LEN])[0],
            start_index + _FLOAT_DGRAM_LEN,
        )
    except (struct.error, TypeError) as e:
        raise OscParseError(f"Could not parse datagram {e}")


def write_double(val: float) -> bytes:
    """Returns the datagram for the given double parameter value

    Raises:
    - BuildError if the double could not be converted.
    """
    try:
        return struct.pack(">d", val)
    except struct.error as e:
        raise OscBuildError(f"Wrong argument value passed: {e}")


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
            raise OscParseError("Datagram is too short")
        return (
            struct.unpack(">d", dgram[start_index : start_index + _DOUBLE_DGRAM_LEN])[0],
            start_index + _DOUBLE_DGRAM_LEN,
        )
    except (struct.error, TypeError) as e:
        raise OscParseError("Could not parse datagram {}".format(e))


def get_blob(dgram: bytes, start_index: int) -> Tuple[bytes, int]:
    """Get a blob from the datagram.

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
        raise OscParseError("Datagram is too short.")
    return dgram[int_offset : int_offset + size], int_offset + total_size


def write_blob(val: bytes) -> bytes:
    """Returns the datagram for the given blob parameter value.

    Raises:
    - BuildError if the value was empty or if its size didn't fit an OSC int.
    """
    if not val:
        raise OscBuildError("Blob value cannot be empty")
    dgram = write_int(len(val))
    dgram += val
    while len(dgram) % _BLOB_DGRAM_PAD != 0:
        dgram += b"\x00"
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
    if dgram[start_index : start_index + _TIMETAG_DGRAM_LEN] == IMMEDIATELY:
        return IMMEDIATELY, start_index + _TIMETAG_DGRAM_LEN
    if len(dgram[start_index:]) < _TIMETAG_DGRAM_LEN:
        raise OscParseError("Datagram is too short")
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
        return struct.pack(">I", val)
    except struct.error as e:
        raise OscBuildError("Wrong argument value passed: {}".format(e))


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
            raise OscParseError("Datagram is too short")
        return (
            struct.unpack(">I", dgram[start_index : start_index + _INT_DGRAM_LEN])[0],
            start_index + _INT_DGRAM_LEN,
        )
    except (struct.error, TypeError) as e:
        raise OscParseError(f"Could not parse datagram {e}")


def write_midi(val: MidiPacket) -> bytes:
    """Returns the datagram for the given MIDI message parameter value

    A valid MIDI message: (port id, status byte, data1, data2).

    Raises:
    - BuildError if the MIDI message could not be converted.

    """
    if len(val) != 4:
        raise OscBuildError("MIDI message length is invalid")
    try:
        value = sum((value & 0xFF) << 8 * (3 - pos) for pos, value in enumerate(val))
        return struct.pack(">I", value)
    except struct.error as e:
        raise OscBuildError("Wrong argument value passed: {}".format(e))


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
            raise OscParseError("Datagram is too short")
        val = struct.unpack(">I", dgram[start_index : start_index + _INT_DGRAM_LEN])[0]
        midi_msg = cast(MidiPacket, tuple((val & 0xFF << 8 * i) >> 8 * i for i in range(3, -1, -1)))
        return (midi_msg, start_index + _INT_DGRAM_LEN)
    except (struct.error, TypeError) as e:
        raise OscParseError(f"Could not parse datagram {e}")


### OSC MESSAGE ###

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
            if type_tag.startswith(","):
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
                        raise OscParseError(f"Unexpected closing bracket in type tag: {type_tag}")
                    param_stack.pop()
                # TODO: Support more exotic types as described in the specification.
                else:
                    syslog.warning(f"Unhandled parameter type: {param}")
                    continue
                if param not in "[]":
                    param_stack[-1].append(val)
            if len(param_stack) != 1:
                raise OscParseError("Missing closing bracket in type tag: {0}".format(type_tag))
            self._parameters = params
        except OscParseError as pe:
            raise OscParseError("Found incorrect datagram, ignoring it", pe)

    @property
    def address(self) -> str:
        """Returns the OSC address regular expression."""
        return self._address_regexp

    @staticmethod
    def dgram_is_message(dgram: bytes) -> bool:
        """Returns whether this datagram starts as an OSC message."""
        return dgram.startswith(b"/")

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
TimedMessage = NamedTuple(
    "TimedMessage",
    [
        ("time", float),
        ("message", OscMessage),
    ],
)


def _timed_msg_of_bundle(bundle, now: float) -> List[TimedMessage]:
    """Returns messages contained in nested bundles as a list of TimedMessage."""
    msgs = []
    for content in bundle:
        if type(content) is OscMessage:
            if bundle.timestamp == IMMEDIATELY or bundle.timestamp < now:
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
                self._messages = sorted(_timed_msg_of_bundle(OscBundle(dgram), now), key=lambda x: x.time)
            elif OscMessage.dgram_is_message(dgram):
                self._messages = [TimedMessage(now, OscMessage(dgram))]
            else:
                # Empty packet, should not happen as per the spec but heh, UDP...
                raise OscParseError("OSC Packet should at least contain an OscMessage or an OscBundle.")
        except (OscParseError, OscParseError) as e:
            raise OscParseError(f"Could not parse packet {e}")

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
                content_dgram = self._dgram[index : index + content_size]
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
        dgram = b"#bundle\x00"
        try:
            dgram += write_date(self._timestamp)
            for content in self._contents:
                # if type(content) == OscMessage or type(content) == OscBundle:
                if isinstance(content, (OscMessage, OscBundle)):
                    size = content.size
                    dgram += write_int(size)
                    dgram += content.dgram
                else:
                    raise OscBuildError("Content must be either OscBundle or OscMessagefound {}".format(type(content)))
            return OscBundle(dgram)
        except OscBuildError as be:
            raise OscBuildError(f"Could not build the bundle {be}")


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
        ARG_TYPE_FLOAT,
        ARG_TYPE_DOUBLE,
        ARG_TYPE_INT,
        ARG_TYPE_INT64,
        ARG_TYPE_BLOB,
        ARG_TYPE_STRING,
        ARG_TYPE_RGBA,
        ARG_TYPE_MIDI,
        ARG_TYPE_TRUE,
        ARG_TYPE_FALSE,
        ARG_TYPE_NIL,
    )

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
            raise ValueError("arg_type must be one of {}, or an array of valid types".format(self._SUPPORTED_ARG_TYPES))
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
            raise ValueError("Infered arg_value type is not supported")
        return arg_type

    def build(self):  # -> OscMessage:
        """Builds an OscMessage from the current state of this builder.

        Raises:
        - BuildError: if the message could not be build or if the address
                        was empty.

        Returns:
        - an OscMessage instance.
        """
        if not self._address:
            raise OscBuildError("OSC addresses cannot be empty")
        dgram = b""
        try:
            # Write the address.
            dgram += write_string(self._address)
            if not self._args:
                dgram += write_string(",")
                return OscMessage(dgram)

            # Write the parameters.
            arg_types = "".join([arg[0] for arg in self._args])
            dgram += write_string("," + arg_types)
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
                elif arg_type in (
                    self.ARG_TYPE_TRUE,
                    self.ARG_TYPE_FALSE,
                    self.ARG_TYPE_ARRAY_START,
                    self.ARG_TYPE_ARRAY_STOP,
                    self.ARG_TYPE_NIL,
                ):
                    continue
                else:
                    raise OscBuildError(f"Incorrect parameter type found {arg_type}")

            return OscMessage(dgram)
        except OscBuildError as be:
            raise OscBuildError(f"Could not build the message: {be}")


### DISPATCHER ###
"""Maps OSC addresses to handler functions
"""


class Handler(object):
    """Wrapper for a callback function that will be called when an OSC message is sent to the right address.

    Represents a handler callback function that will be called whenever an OSC message is sent to the address this
    handler is mapped to. It passes the address, the fixed arguments (if any) as well as all osc arguments from the
    message if any were passed.
    """

    def __init__(
        self,
        _callback: Callable,
        _args: Union[Any, List[Any]],
        _needs_reply_address: bool = False,
    ) -> None:
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
        return (
            type(self) is type(other) and self.callback == other.callback and self.args == other.args and self.needs_reply_address == other.needs_reply_address
        )

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
        self._map = collections.defaultdict(list)
        self._default_handler = None

    def map(
        self,
        address: str,
        handler: Callable,
        *args: Union[Any, List[Any]],
        needs_reply_address: bool = False,
    ):
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
    def unmap(
        self,
        address: str,
        handler: Callable,
        *args: Union[Any, List[Any]],
        needs_reply_address: bool = False,
    ) -> None:
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
        pattern = escaped_address_pattern.replace("\\?", "\\w?")
        # '*' in the OSC Address Pattern matches any sequence of zero or more
        # characters.
        pattern = pattern.replace(r"\*", r"[\w|\+]*")
        # The rest of the syntax in the specification is like the re module so
        # we're fine.
        pattern = pattern + "$"
        patterncompiled = re.compile(pattern)
        matched = False

        for addr, handlers in self._map.items():
            if patterncompiled.match(addr) or (("*" in addr) and re.match(addr.replace("*", "[^/]*?/*"), address_pattern)):
                yield from handlers
                matched = True

        if not matched and self._default_handler:
            logging.debug("No handler matched but default handler present, added it.")
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
                handlers = self.handlers_for_address(timed_msg.message.address)
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
    return OscBundle.dgram_is_bundle(data) or OscMessage.dgram_is_message(data)


class OSCUDPServer(socketserver.UDPServer):
    """Superclass for different flavors of OSC UDP servers"""

    def __init__(
        self,
        server_address: Tuple[str, int],
        dispatcher,
        bind_and_activate: bool = True,
    ) -> None:
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


class AsyncIOOSCUDPServer:
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

    def create_serve_endpoint(
        self,
    ) -> Coroutine[Any, Any, Tuple[asyncio.transports.BaseTransport, asyncio.DatagramProtocol]]:
        """Creates a datagram endpoint and registers it with event loop as coroutine.

        Returns:
            Awaitable coroutine that returns transport and protocol objects
        """
        return self._loop.create_datagram_endpoint(
            lambda: self._OSCProtocolFactory(self.dispatcher),
            local_addr=self._server_address,
        )

    @property
    def dispatcher(self):
        return self._dispatcher


### UDP CLIENT ###

"""UDP Clients for sending OSC messages to an OSC server"""


class UDPClient(object):
    """OSC client to send :class:`OscMessage` or :class:`OscBundle` via UDP"""

    def __init__(
        self,
        address: str,
        port: int,
        allow_broadcast: bool = False,
        family: socket.AddressFamily = socket.AF_UNSPEC,
    ) -> None:
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
        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self.stop)

    def send(self, content) -> None:
        """Sends an :class:`OscMessage` or :class:`OscBundle` via UDP

        Args:
            content: Message or bundle to be sent
        """
        self._sock.sendto(content.dgram, (self._address, self._port))

    def stop(self):
        if self._sock:
            self._sock.close()
            self._sock = None


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


class OscClient:
    """client that sends data out"""

    def __init__(self, host_ip="127.0.0.1", output_port=8001, name=None):

        self._server_ip = host_ip
        self._output_port = output_port
        self._client = None
        self._started = False
        self._name = name
        self._loopback = False  # true if the client sends to the current server hosted in this process (same IP, same port)

    def setPort(self, port):
        self._output_port = port

    def setHost(self, host: str, output_port: int = None):
        self._server_ip = host
        if output_port is not None:
            self._output_port = output_port

    @property
    def isLoopback(self) -> bool:
        return self._loopback

    def setName(self, value: str):
        self._name = value

    def start(self, server_ip=None, server_port=None):
        """
        starts the OSC client to send OSC commands
        :param server_ip = ip address of server in format xxx.xxx.xxx.xxx
        :param server_port = output port
        """

        if self._started:
            # already started
            return

        verbose = gremlin.config.Configuration().verbose_mode_osc

        if server_ip:
            self._server_ip = server_ip
        if server_port:
            self._output_port = server_port

        oi = OscInterface()
        if self._server_ip == oi.hostIp and self._output_port == oi.hostPort:
            # loopback scenario
            self._loopback = True
            if verbose:
                syslog.info(f"OSC loopback client: {self._name} starting {self._server_ip} port: {self._output_port}")
        else:
            # syslog = logging.getLogger("system")
            if self._server_ip is not None and self._output_port is not None:
                self._client = UDPClient(self._server_ip, self._output_port)
                self._started = True
                if verbose:
                    syslog.info(f"OSC client: {self._name} starting {self._server_ip} port: {self._output_port}")
            else:
                syslog.error(f"OSC client: {self._name} Invalid OSC configuration, provide server IP and port #")

        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self.stop)

    def stop(self):
        verbose = gremlin.config.Configuration().verbose_mode_osc
        if self._started:
            self._started = False
            if self._loopback:
                self._loopback = False
                if verbose:
                    syslog.info(f"OSC: loopback client stop: ip: {self._server_ip} port: {self._output_port}")
            else:
                self._client.stop()  # stop UDP client
                self._client = None
                # syslog = logging.getLogger("system")
                if verbose:
                    syslog.info(f"OSC: client stop: ip: {self._server_ip} port: {self._output_port}")

    def add_arg(self, builder, value):
        if value is not None:
            if isinstance(value, float):
                builder.add_arg(value, OscMessageBuilder.ARG_TYPE_FLOAT)
            elif isinstance(value, str):
                builder.add_arg(value, OscMessageBuilder.ARG_TYPE_STRING)
            elif isinstance(value, int):
                builder.add_arg(value, OscMessageBuilder.ARG_TYPE_INT)
            elif isinstance(value, bool):
                if value:
                    builder.add_arg(value, OscMessageBuilder.ARG_TYPE_TRUE)
                else:
                    builder.add_arg(value, OscMessageBuilder.ARG_TYPE_FALSE)
            else:
                # syslog = logging.getLogger("system")
                syslog.warning(f"OSC Argument: don't know how to handle {value} {type(value).__name__}")

    def send(self, command: str, v1=None, v2=None):
        """sends an osc command

        :param command : the OSC command to send (string)
        :param v1 : optional value 1 (type determines what is sent)
        :param v2 : optional value 2 (type determines what is sent)


        """
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_osc
        if not self._started:
            return  # not started

        if verbose:
            msg = f"OSC (internal): Send OSC: {command}  target: {self._server_ip}  port: {self._output_port}"
            if v1 is not None:
                msg += f" v1 {v1}"
            if v2 is not None:
                msg += f" v2 {v2}"
            syslog.info(msg)

        builder = OscMessageBuilder(command)

        if v1 is not None or v2 is not None:
            self.add_arg(builder, v1)
            self.add_arg(builder, v2)
        else:
            if gremlin.config.Configuration().osc_pad_args:
                # add default
                value = 1.0
                self.add_arg(builder, value)

        osc = builder.build()

        if self._loopback:
            # send via the internal loop back
            el = gremlin.event_handler.EventListener()
            el.osc_loopback.emit(osc)
        else:
            self._send(osc)
            verbose = gremlin.config.Configuration().verbose_mode_osc
            if verbose:
                syslog.info(
                    f"OSC SEND: target: {self._server_ip} port: {self._output_port} message: {command} v1: {v1 if v1 is not None else 'n/a'} v2: {v2 if v2 is not None else 'n/a'}  args: {builder.args}"
                )

    def sendEx(self, command: str, *args):
        """sends a variable number args to OSC"""
        builder = OscMessageBuilder(command)
        arg_count = 0
        if args:
            for arg in args:
                if isinstance(arg, list) or isinstance(arg, tuple):
                    for a in arg:
                        arg_count += 1
                        self.add_arg(builder, a)
                else:
                    arg_count += 1
                    self.add_arg(builder, arg)
        if arg_count == 0 and gremlin.config.Configuration().osc_pad_args:
            # add default
            value = 1.0
            self.add_arg(builder, value)

        osc = builder.build()

        if self._loopback:
            # send via the internal loop back
            el = gremlin.event_handler.EventListener()
            el.osc_loopback.emit(osc)
        else:
            self._send(osc)
            verbose = gremlin.config.Configuration().verbose_mode_osc
            if verbose:
                syslog.info(f"OSC SEND: target: {self._server_ip} port: {self._output_port} message: {command} args: {builder.args}")

    def _send(self, content):
        self._client.send(content)


class OscServer:
    def __init__(self):
        # syslog.info("OSC: server init")
        self._server = None
        self._server_thread = None
        self._stop = False
        self._running = False
        self._missed_count = 0
        self._start_requested = False
        self._lock = threading.Lock()
        self._server_thread = None
        self._host_ip = None
        self._input_port = None
        self._dispatcher = None
        self._callback = None

        el = gremlin.event_handler.EventListener()
        el.shutdown.connect(self._shutdown)

    def setHostIp(self, host_ip, input_port):
        """changes the OSC server IP"""
        self.stop()
        self._host_ip = host_ip
        self._input_port = input_port
        self.start(host_ip, self._input_port, self._callback)

    @QtCore.Slot()
    def _shutdown(self):
        """app shutdown received"""
        self.stop()

    @property
    def started(self):
        """true if server is started or in the process of starting"""
        if self._lock.locked():
            syslog.info("OSC: server locked")
            return True

        return self._running

    def start(self, host_ip, input_port, callback):
        """starts the server on IP and port

        :param host_ip = ip address of server in format xxx.xxx.xxx.xxx
        :param input_port = input port, numeric, default 8000
        :param callback = the callback to call when a message arrives

        """

        config = gremlin.config.Configuration()
        _verbose = config.verbose_mode_osc
        if not config.osc_enabled:
            # disabled
            return
        if self._running and self._server_thread is not None:
            return  # already started

        if not callback:
            return  # don't start unless there's a callback provided

        with self._lock:
            # everything here is now locked until the server start is completed

            self._host_ip = host_ip
            self._input_port = input_port
            self._callback = callback

            self._stop = False
            self._server_thread = threading.Thread(target=self._server_thread_loop, daemon=False)
            self._server_thread.setName("OSC server listener")
            self._server_thread.start()
            self._running = True

            # syslog = logging.getLogger("system")
            syslog.info(f"OSC: server start {self._host_ip} port {self._input_port}")

    def stop(self):
        """stops the server"""
        if not self._running or self._start_requested:
            return
        # syslog.info("OSC: stop requested")
        self._stop = True
        if self._server:
            self._server.shutdown()
            time.sleep(0.1)
        self._server_thread.join()
        self._server_thread = None
        self._running = False
        time.sleep(0.1)  # allow time for the server thread to fully terminate
        syslog.info("OSC: server stopped")

    def _server_thread_loop(self):
        """main threading loop"""

        self._dispatcher = OscDispatcher()
        self._dispatcher.set_default_handler(self._callback)

        try:
            syslog.info("OSC: server starting")
            self._server = BlockingOSCUDPServer((self._host_ip, self._input_port), self._dispatcher)
            self._server.serve_forever()  # blocks until shutdown

            # resume after exit
            syslog.info("OSC: server shutdown")
        except Exception as e:
            syslog.error(f"OSC: server error: {e}")

        self._server = None


"""  OscInterface ================================================================================================== """


@SingletonDecorator
class OscInterface(QtCore.QObject):
    """GremlinEX Open Sound Control/Open Stage Control interface"""

    osc_message = Signal(str, object)  # signal on receiving an osc message

    def __init__(self, host_ip: str = None):
        super().__init__()

        self._host_ip = host_ip
        self._started = False
        self._osc_client = None
        self._osc_server = None
        self._osc_internal_client = None
        self._input_port = None
        self._output_port = None
        self._target_ip = None
        self._target_port = None
        self._client_pool = {}
        self._client_map = {}
        self.osc_enabled = False

        el = gremlin.event_handler.EventListener()
        el.request_osc.connect(self._request_osc_state)
        el.osc_input_port_changed.connect(self._input_port_changed)
        el.osc_output_port_changed.connect(self._output_port_changed)
        el.osc_output_server_changed.connect(self._output_server_changed)
        el.host_ip_changed.connect(self.setHostIp)
        el.osc_loopback.connect(self._loopback_handler)

        self._started = False

    def start(self):
        """starts OSC"""
        config = gremlin.config.Configuration()
        if not config.osc_enabled:
            # disabled
            return

        if self._started:
            # already started
            return

        verbose = config.verbose_mode_osc

        self._input_port = config.osc_input_port
        if self._input_port is None:
            self._input_port = 8000

        self._output_port = config.osc_output_port  # self._input_port + 1
        if self._output_port is None:
            self._output_port = 8001  # default

        host_ip = self._host_ip

        # find our current IP address
        if not host_ip:
            self._host_ip = gremlin.config.Configuration().hostIp
            if verbose:
                syslog.info(f"OSC: last server IP: {host_ip}")

        ip_list = gremlin.util.getHostIp()
        if ip_list:
            if host_ip in ip_list:
                if verbose:
                    syslog.info("OSC: last server IP found")
            else:
                host_ip = ip_list[0]
                if verbose:
                    syslog.info("OSC: detected host IPs")

                    syslog.info(f"OSC: last server IP not found, defaulting to default host IP: {host_ip}")
        else:
            host_ip = "127.0.0.1"
            if verbose:
                syslog.info(f"OSC: last server IP not found, no IP found, defaulting to locahost: {host_ip}")

        if verbose:
            syslog.info(f"OSC: input port: {self._input_port}")

        self._target_ip = config.osc_host
        self._target_port = config.osc_output_port
        self._osc_server = OscServer()  # the OSC server
        self.osc_enabled = True  # always able to listen to ports
        self._client_pool = {}  # pool of clients keyed by (ip,port)
        self._client_map = {}  # list of clients by client ID (str)
        self._osc_client = self.getClient("osc_interface", self._target_ip, self._target_port)  # the default OSC client setup in the configuration file
        if verbose:
            syslog.info(f"OSC: output IP: {self._target_ip} port: {self._output_port}")

        self.setHostIp(host_ip)
        self._osc_internal_client = self.getClient(
            "osc_internal_client", self._host_ip, self.output_port, "internal"
        )  # the OSC internal client for loop messages

        syslog.info(f"OSC (interface): starting with IP: {self._host_ip} port: {self._input_port} send host: {self._target_ip} port: {self._output_port}")
        self._osc_server.stop()  # stop server if started - this resets the message handler for the server and listen ip/port
        self._osc_server.start(self._host_ip, self._input_port, self._osc_message_handler)
        self.startClients()
        self._started = True

        el = gremlin.event_handler.EventListener()
        el.heartbeat.disconnect(self._keep_alive)

    def _loopback_handler(self, data: OscMessage):
        """handles a loopback osc message"""
        self._osc_message_handler(data.address, *data.params)

    def setHostIp(self, host_ip):
        """sets a new host IP for the OSC server"""
        if host_ip != self._host_ip and host_ip:
            self._host_ip = host_ip
            config = gremlin.config.Configuration()
            config.hostIp = host_ip
            if hasattr(self, "_osc_internal_client") and self._osc_internal_client:
                self._osc_internal_client.setHost(host_ip, self._output_port)  # loopback internal device
            if hasattr(self, "_osc_server") and self._osc_server:
                self._osc_server.setHostIp(host_ip, self._input_port)  # server listening

    @property
    def hostIp(self) -> str:
        return self._host_ip

    @property
    def hostPort(self) -> int:
        return self._input_port

    @QtCore.Slot(bool)
    def _request_osc_state(self, state: bool):

        if state:
            self.start()
        else:
            self.stop()

    @QtCore.Slot()
    def _input_port_changed(self):
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_osc
        value = config.osc_input_port
        if verbose:
            # syslog = logging.getLogger("system")
            syslog.info(f"OSC: input port changed to: {value}")
        self.input_port = value

    @QtCore.Slot()
    def _output_port_changed(self):
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_osc
        value = config.osc_output_port
        if verbose:
            # syslog = logging.getLogger("system")
            syslog.info(f"OSC: output port changed to: {value}")
        self.output_port = value

    @QtCore.Slot()
    def _output_server_changed(self):
        config = gremlin.config.Configuration()
        verbose = config.verbose_mode_osc
        value = config.osc_host
        if verbose:
            # syslog = logging.getLogger("system")
            syslog.info(f"OSC: output host changed to: {value}")
        self.target_server = value

    def getClient(self, client_id: str, server: str, port: int, name: str = None) -> OscClient:
        """gets the client for that server/port"""
        config = gremlin.config.Configuration()
        if not config.osc_enabled:
            # disabled
            syslog.info("OSC: osc is disabled, client will not start.")
            return None

        key = (server, port)
        if key not in self._client_pool:
            client = OscClient(server, port, name)
            self._client_pool[key] = client
            verbose = gremlin.config.Configuration().verbose_mode_osc
            if verbose:
                # syslog = logging.getLogger("system")
                syslog.info(f"OSC: register client {key}")

        if key not in self._client_map:
            self._client_map[key] = []
        if client_id not in self._client_map[key]:
            self._client_map[key].append(client_id)

        return self._client_pool[key]

    def closeClient(self, client_id: str, client: OscClient):
        """removes a client from the pool"""

        key = (client._server_ip, client._output_port)

        if key in self._client_pool:
            if key not in self._client_map:
                self._client_map[key] = []

            if client_id in self._client_map[key]:
                self._client_map[key].remove(client_id)

            if self._client_map[key]:
                # client is still used
                return

            if client is not None:
                client.stop()
                verbose = gremlin.config.Configuration().verbose_mode_osc
                if verbose:
                    # syslog = logging.getLogger("system")
                    syslog.info(f"OSC: unregister client {key}")

            del self._client_pool[key]

    def stopClients(self):
        """stops all registered clients"""
        for client in self._client_pool.values():
            client.stop()
        self._client_map.clear()

    def startClients(self, server=None, port=None):
        """starts all registered clients"""
        remove_list = []
        add_list = []
        for key, client in self._client_pool.items():
            if server is not None:
                if not gremlin.util.validateIp(server):
                    continue
                client._server_ip = server
            if port is not None:
                client._output_port = port
            if not gremlin.util.validateIp(key[0]):
                remove_list.append(key)
                continue
            new_key = (client._server_ip, client._output_port)
            if key != new_key:
                add_list.append((new_key, client))
                remove_list.append(key)

            client.start()

        # update the clients with new keys
        for key in remove_list:
            del self._client_pool[key]
        for key, client in add_list:
            self._client_pool[key] = client

    @property
    def input_port(self):
        """UDP input port to use for OSC messages - default is 8000"""
        return self._input_port

    @input_port.setter
    def input_port(self, value):
        if value != self._input_port:
            self._input_port = value
            self.stop()
            self.start()

    @property
    def output_port(self):
        """UDP output port to use for OSC messages - default is 8001"""
        return self._output_port

    @output_port.setter
    def output_port(self, value):
        if value != self._output_port:
            self._output_port = value
            self.stopClients()
            self.startClients(self.target_server, value)

    @property
    def target_server(self):
        return self._target_ip

    @target_server.setter
    def target_server(self, value: str):
        if value != self._target_ip:
            self._target_ip = value
            self.stopClients()
            self.startClients(value, self.output_port)

    @property
    def host_ip(self):
        """host ip in string form xxx.xxx.xxx.xxx"""
        return self._host_ip

    @host_ip.setter
    def host_ip(self, value):
        self._host_ip = value

    def log(msg):
        """displays a log message in Gremlin and in the console"""
        syslog.info(msg)

    def _osc_message_handler(self, address, *args):
        """handles internal OSC messages"""
        verbose = gremlin.config.Configuration().verbose_mode_osc
        if verbose:
            syslog.info(f"OSC: received: {address}: {args}")
        address = address.casefold()
        if address == "/noop":
            # heartbeat
            # syslog.info(f"OSC: tick")
            return
        self.osc_message.emit(address, args)

    def _keep_alive(self):
        if self._started:
            self._osc_internal_client.send("/noop")

    def stop(self):
        """stops listencing to OSC messages"""
        if self._started:
            self._osc_server.stop()
            self.stopClients()
            self._started = False
            el = gremlin.event_handler.EventListener()
            el.heartbeat.disconnect(self._keep_alive)

    def send(self, command: str, v1=None, v2=None):
        """send data via the default client"""
        self._osc_client.send(command, v1, v2)


""" end OscInterface ================================================================================================== """

""" GREMLIN UI STUFF """


# class OscInputItem(AbstractInputItem):
class OscInputItem(gremlin.input_item.InputItemMessage):
    """holds OSC input data"""

    message_key_changed = Signal(str, str)  # fires when message key changes
    input_type_changed = Signal(object)  # fires when osc input type changes from button to axis or vice versa

    class InputMode(enum.Enum):
        """possible input modes"""

        Axis = 0  # input is variable
        Button = 1  # input is marked pressed if the value is in the upper range
        OnChange = 2  # input triggers pressed on any state change
        Encoder = 3  # input is an encoder - two ranges of valuel, triggers two actions

    class CommandMode(enum.Enum):
        """OSC command mode = determines how the command key is derived"""

        Message = 0  # only the command part of the message is used (data is variable)
        Data = 1  # the message and arguments are considered

        def __lt__(self, other):
            return self.value < other.value

    def __init__(self, mode_object: gremlin.base_profile.ProfileModeNode = None):
        super().__init__(
            mode_object,
            device_guid=OscDeviceTabWidget.device_guid,
            input_type=InputType.OpenSoundControl,
            custom_input_id_handler=self._handle_input_id_callback,
            on_message_key_changed=self._on_message_key_changed,
        )  # parent is the mode object this input belongs to

        config = gremlin.config.Configuration()
        self.verbose = config.verbose_mode_osc
        self._message = None  # the OSC message command
        self._message_data = None  # the list of values associated with that command
        self._message_data_string = None  # the string representation of the data args
        self._mode = OscInputItem.InputMode.Button
        self._override_input_type = InputType.JoystickButton
        self._command_mode = OscInputItem.CommandMode.Message
        self._title_name = "OSC (not configured)"
        self._display_name = ""
        self._display_tooltip = "Input configuration not set"
        self._source_index = 0  # OSC parameter source index - used for multi-argument data
        self.setMessageKey(self._guid)
        self._min_range = 0.0
        self._max_range = 1.0
        self._trigger_autorelease = None  # trigger with autorelease when message received
        self._autorelease_delay = int(config.osc_default_autorelease_delay * 1000)  # default release delay in milliseconds
        self._autorelease_timer = None  # autorelease timer for this input

        self._axis_values = []
        current_mode = gremlin.shared_state.current_mode
        tracker = gremlin.ui.ui_common.DeviceWidgetTracker()

        tracker.registerWidget(
            self,
            self._device_guid,
            current_mode,
            self._input_type,
            self.getCompoundMessageKey(),
            self._guid,
        )
        client = InputOscClient()
        client.registerInput(self)
        self.setInputIdCallback(self._handle_input_id_callback)

    def _handle_input_id_callback(self):
        """input id is self for OSC"""
        return self  # whole input

    def to_html(self) -> str:
        """returns reporting graphviz data for this action"""
        from gremlin.reporting import ReportTable

        table = ReportTable(cellpadding=4)
        table.addField("Message", self.message)
        table.addField("Mode", self.mode.name)
        table.addField("Command Mode", self._command_mode.name)
        if self.autoRelease is None:
            table.addField("Autorelease", "Global setting")
        else:
            table.addField("Autorelease", "Yes" if self._trigger_autorelease else "No")
        if self._message_data:
            for index, data in enumerate(self._message_data):
                if isinstance(data, str):
                    if gremlin.util.isNumeric(data):
                        data_stub = f"{float(data):0.3f}"
                elif isinstance(data, float):
                    data_stub = f"{data:03f}"
                else:
                    data_stub = data

                table.addField(f"Data [{index}]", data_stub)
        if self.mode == OscInputItem.InputMode.Axis:
            table.addField("Axis Range", f"[{self._min_range:0.3f}, {self._max_range:0.3f}]")

        return table.to_html()

    def __deepcopy__(self, memo):
        return self

    @property
    def autorelease_timer(self):
        return self._autorelease_timer

    @autorelease_timer.setter
    def autorelease_timer(self, timer):
        if self._autorelease_timer:
            self._autorelease_timer.cancel()
        self._autorelease_timer = timer

    @property
    def profile_mode(self):
        return self._profile_mode

    @profile_mode.setter
    def profile_mode(self, value):
        self._profile_mode = value

    @property
    def is_valid(self) -> bool:
        """true if the input is configured (controls the visibility of the repeater)"""
        valid = bool(self._message)
        return valid

    @property
    def is_status(self) -> bool:
        """true if the input has status information to display"""
        return False

    def getOverrideInputType(self):
        match self._mode:
            case OscInputItem.InputMode.Button | None:
                return InputType.JoystickButton
            case OscInputItem.InputMode.Axis:
                return InputType.JoystickAxis
        return self._input_type

    def getCompoundMessageKey(self):
        return f"{self._message_key}_{self._source_index}"

    def getAxisValue(self):
        """gets the current axis value (override)"""
        if self._source_index < len(self._axis_values):
            return self._axis_values[self._source_index]
        if self._axis_value is not None:
            return self._axis_value
        return 0.0

    @property
    def autoRelease(self) -> bool:
        if self._trigger_autorelease is None:
            return False
        return self._trigger_autorelease

    @autoRelease.setter
    def autoRelease(self, value: bool):
        self._trigger_autorelease = value
        self._update()

    @property
    def autorelease_delay(self) -> int:
        return self._autorelease_delay

    @autorelease_delay.setter
    def autorelease_delay(self, value: int):
        self._autorelease_delay = value

    @property
    def mode(self) -> OscInputItem.InputMode:
        """input mode"""
        return self._mode

    def setMode(self, value: OscInputItem.InputMode):
        """changes the input mode"""
        if self._mode != value:
            self._mode = value
            match value:
                case OscInputItem.InputMode.Axis:
                    self._override_input_type = InputType.JoystickAxis
                case OscInputItem.InputMode.Button:
                    self._override_input_type = InputType.JoystickButton
            self._update()
            self.input_type_changed.emit(self)

    @property
    def is_axis(self) -> bool:
        return self._mode == OscInputItem.InputMode.Axis

    @property
    def is_button(self) -> bool:
        return self._mode != OscInputItem.InputMode.Axis

    @property
    def command_mode(self) -> OscInputItem.CommandMode:
        """command mode"""
        return self._command_mode

    @command_mode.setter
    def command_mode(self, value: OscInputItem.CommandMode):
        self._command_mode = value
        self._update()

    @property
    def title_name(self) -> str:
        """title for this input"""
        return self._title_name

    @property
    def display_name(self) -> str:
        """display name for this input"""
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

    def getState(self):
        """gets the current value of the input item"""
        osc_client = InputOscClient()
        if not osc_client.started:
            osc_client.start()
        value = osc_client.getData(self.message_key)
        match self.mode:
            case OscInputItem.InputMode.Axis:
                value = value if value is not None else 0.0
                return gremlin.event_handler.AxisValues(value)

            case OscInputItem.InputMode.Button:
                return bool(value) if value is not None else False
        return None

    @property
    def data_string(self):
        """string representation of the OSC arguments"""
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
    def source_index(self) -> int:
        return self._source_index

    @source_index.setter
    def source_index(self, value: int):
        if value >= 0 and self._source_index != value:
            current_mode = gremlin.shared_state.current_mode
            client = InputOscClient()
            client.unregisterInput(self)
            tracker = gremlin.ui.ui_common.DeviceWidgetTracker()
            tracker.unregisterWidget(
                self._device_guid,
                current_mode,
                self._input_type,
                self.getCompoundMessageKey(),
                self._guid,
            )
            self._source_index = value
            tracker.registerWidget(
                self,
                self._device_guid,
                current_mode,
                self._input_type,
                self.getCompoundMessageKey(),
                self._guid,
            )
            client.registerInput(self)

    @property
    def display_tooltip(self):
        """detailed tooltip"""
        return self._display_tooltip

    @property
    def mode_string(self):
        match self._mode:
            case OscInputItem.InputMode.Axis:
                return "axis"
            case OscInputItem.InputMode.Button:
                return "button"
            case OscInputItem.InputMode.OnChange:
                return "change"
            case OscInputItem.InputMode.Encoder:
                return "encoder"

    def _mode_from_string(self, value):
        match value:
            case "axis":
                self._mode = OscInputItem.InputMode.Axis
            case "button":
                self._mode = OscInputItem.InputMode.Button
            case "change":
                self._mode = OscInputItem.InputMode.OnChange
            case "encoder":
                self._mode = OscInputItem.InputMode.Encoder
            case _:
                raise ValueError(f"mode_from_string(): don't know how to handle {value}")

    @property
    def command_mode_string(self):
        return OscInputItem.command_mode_to_string(self._command_mode)

    @staticmethod
    def command_mode_to_string(value):
        """converts a string to a command mode"""
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
        """returns the sorting key for this message - includes the source parameter index"""
        if not self._message_key and self._message:
            self._message_key = OscInputItem.toMessageKey(self._command_mode, self._message, self._source_index)
        return self._message_key

    def _on_message_key_changed(self, old_key, new_key):

        client = InputOscClient()

        if self._message_key:
            client.unregisterInput(self)

        self._message_key = new_key
        client.registerInput(self)

    @staticmethod
    def data_to_string(data):
        """returns a string representation of the data"""
        return list_to_csv(data)

    def _string_to_data(self, value):
        """converts a string representation of the data to a list of args"""
        return csv_to_list(value)

    @staticmethod
    def toMessageKey(command_mode: OscInputItem.CommandMode, message, args):
        if command_mode == OscInputItem.CommandMode.Data:
            return f"{message} {OscInputItem.data_to_string(args)}"
        elif command_mode == OscInputItem.CommandMode.Message:
            if args:
                return f"{message} {args}"
            return f"{message}"
        else:
            raise ValueError(f"_update(): don't know how to handle {command_mode}")

    def toSortKey(self):
        return (self.command_mode, self._message.casefold() if self._message else "")

    def _update(self):
        """updates the message key based on the current config"""
        message_key = OscInputItem.toMessageKey(self._command_mode, self.message, self._source_index)
        self.setMessageKey(message_key)

        # update data string from the raw data
        self._message_data_string = list_to_csv(self._message_data)

        self._update_display_name()

    def from_xml(self, node, data=None, extra_data: dict = None):
        # OSC data

        for child in node:
            if child.tag == "input":
                self.parse_xml(child, data, extra_data)

        if self.is_axis:
            self.setOverrideInputType(InputType.JoystickAxis)
        else:
            self.setOverrideInputType(InputType.JoystickButton)
        if node.tag == "input":
            self.parse_xml(node, data, extra_data)

        super().from_xml(node, data, extra_data)

    def parse_xml(self, node, data=None, extra_data: dict = None):
        """reads an input item from xml"""

        if node.tag == "input":
            self.setId(read_guid(node, "guid"))
            self._message = safe_read(node, "cmd", str, "")
            csv = safe_read(node, "data", str, "")
            self._message_data = csv_to_list(csv)
            self._mode_from_string(safe_read(node, "mode", str, ""))
            self._command_mode = OscInputItem.command_mode_from_string(safe_read(node, "cmd_mode", str, ""))
            self._min_range = safe_read(node, "min", float, 0.0)
            self._max_range = safe_read(node, "max", float, 1.0)
            self._source_index = safe_read(node, "source_index", int, 0)

            if "autorelease" in node.attrib:
                self._trigger_autorelease = safe_read(node, "autorelease", bool, False)
            else:
                self._trigger_autorelease = None  # not set

            if "autorelease_delay" in node.attrib:
                self._autorelease_delay = safe_read(node, "autorelease_delay", int, 250)

        self._update()

    def to_xml(self):
        """writes the input item to XML"""
        node = ElementTree.Element("input")
        node.set("guid", str(self.id))
        if self.message:
            node.set("cmd", self.message)
        if self._message_data:
            node.set("data", list_to_csv(self._message_data))
        node.set("mode", self.mode_string)
        if self.command_mode_from_string:
            node.set("cmd_mode", self.command_mode_string)
        node.set("min", str(self._min_range))
        node.set("max", str(self._max_range))
        node.set("source_index", safe_format(self._source_index, int))
        if self._trigger_autorelease is not None:
            node.set("autorelease", str(self._trigger_autorelease))
        node.set("autorelease_delay", str(self._autorelease_delay))

        super().to_xml(node)
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
        msg = self._message if self._message else "n/a"
        if self._command_mode == OscInputItem.CommandMode.Message:
            self._display_name = f"{msg} (P{self._source_index + 1})"
        else:
            if self._message_data_string:
                self._display_name = f"{msg}/{self._message_data_string} (P{self._source_index + 1})"
            else:
                self._display_name = f"{msg} (P{self._source_index + 1})"

    def duplicate(self) -> OscInputItem:
        """duplicates an input item"""
        import copy

        source = self
        target = OscInputItem()
        target.id = uuid.uuid4()
        target._message = copy.deepcopy(source._message)
        target._message_data = source._message_data
        target._message_data_string = source._message_data_string
        target._mode = source._mode
        target._profile_mode = source._profile_mode
        target._command_mode = source._command_mode
        target._title_name = source._title_name
        target._display_name = source._display_name
        target._display_tooltip = source._display_tooltip
        target.message_key = source._message_key
        target._min_range = source._min_range
        target._max_range = source._max_range
        target._source_index = source._source_index
        target._update_display_name()
        return target

    def __hash__(self):
        if self._message_key:
            return str(self._message_key).__hash__()
        return str(self.id).__hash__()

    def __lt__(self, other):
        """used for sorting purposes"""
        if other is None or not isinstance(other, OscInputItem):
            return False
        k1 = self.toSortKey()
        k2 = other.toSortKey()
        return k1 < k2

    def __eq__(self, other):

        if other is None:
            return False
        if isinstance(other, str):
            return gremlin.util.compare_guid(self.id, other)
        if not isinstance(other, OscInputItem):
            return False
        k1 = self.toSortKey()
        k2 = other.toSortKey()
        return k1 == k2

    def __str__(self):
        return self._title_name


class OscInputItemWidget(gremlin.input_item.InputItemWidget):
    def __init__(
        self,
        input_item: OscInputItem,
        populate_ui_callback=None,
        populate_name_callback=None,
        selection_changed_callback=None,
        update_callback=None,
        confirm_delete_callback=None,
        config_external=False,
        data=None,
        parent=None,
    ):
        # store the get_state_callback to be used by child widgets
        get_state_callback = self._handle_get_state
        super().__init__(
            input_item=input_item,
            populate_ui_callback=populate_ui_callback,
            populate_name_callback=populate_name_callback,
            selection_changed_callback=selection_changed_callback,
            update_callback=update_callback,
            confirm_delete_callback=confirm_delete_callback,
            get_state_callback=get_state_callback,
            config_external=config_external,
            data=data,
            parent=parent,
        )

    def _handle_get_state(self, *args, **kwargs):
        return self.input_item.getState()


class OscInputListenerWidget(QtWidgets.QFrame):
    """opens a centered modal osc message listener dialog

    grabs the first OSC message it hears and closes

    also closes on esc key press

    """

    def __init__(self, callback, input_port=None, parent=None):
        """Creates a new instance.

        :param callback the function to pass the key pressed by the
            user to
        :param host_ip = host ip
        :param input_port = input port

        """
        super().__init__(parent)

        # Disable ui input selection on joystick input
        gremlin.shared_state.push_suspend_highlighting()

        # setup and listen for the osc message
        self._interface = OscInterface()

        self.host_ip = self._interface.host_ip
        self.input_port = self._interface.input_port

        self._interface.osc_message.connect(self._osc_message_cb)
        self._callback = callback

        self.message = None

        # Create and configure the ui overlay
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addWidget(
            QtWidgets.QLabel(
                f"""<center>Listening to OSC input {self._interface.host_ip} port {self._interface.input_port}.<br/><br/>Press ESC to abort.</center>"""
            )
        )

        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setFrameStyle(QtWidgets.QFrame.Plain | QtWidgets.QFrame.Box)
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColorConstants.DarkGray)
        self.setPalette(palette)

        cancel_widget = gremlin.ui.ui_common.Buttons.getCancelWidget(callback=self._cancel_cb)

        # listen for the escape key
        event_listener = gremlin.event_handler.EventListener()
        event_listener.keyboard_event.connect(self._kb_event_cb)

        self.main_layout.addWidget(cancel_widget, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        # start listening on all ports
        self._interface.start()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """called when dialog is closing"""
        gremlin.shared_state.pop_suspend_highlighting()
        return super().closeEvent(event)

    def _cancel_cb(self):
        gremlin.util.InvokeUiMethod(self._cancel_ui)

    def _cancel_ui(self):
        # stop listening
        self._interface.stop()
        self.close()

    def _kb_event_cb(self, event):
        """capture a key - esc"""
        gremlin.util.InvokeUiMethod(self._kb_event_ui, event)

    def _kb_event_ui(self, event):
        from gremlin.keyboard import key_from_code, key_from_name

        key = key_from_code(event.identifier[0], event.identifier[1])
        if event.is_pressed and key == key_from_name("esc"):
            # esc pressed
            self._cancel_ui()

    def _osc_message_cb(self, message, data):
        """called when a osc messages is provided by the listener"""
        gremlin.util.InvokeUiMethod(self._osc_message_ui, message, data)

    def _osc_message_ui(self, message, data):
        if message:
            self.message = message
        self._callback(message, data)
        self.close()


class OscInputConfigDialog(gremlin.ui.ui_common.QShowAtCursorDialog):
    """dialog showing the OSC input configuration options"""

    def __init__(self, current_mode, index, data, parent):
        """
        :param index - the input item index zero based
        :param identifier - the input item identifier
        """

        super().__init__(self.__class__.__name__, parent=parent)
        # self._sequence = InputKeyboardModel(sequence=sequence)

        # Disable ui input selection on joystick input
        gremlin.shared_state.push_suspend_highlighting()

        main_layout = QtWidgets.QVBoxLayout()
        self.setWindowTitle("OSC Input Mapper")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self._parent = parent  # list view
        assert hasattr(parent, "inputItemListModel"), "OSC CONFIG: Parent widget does not have required listview model"
        assert hasattr(parent, "inputItemListView"), "OSC CONFIG: Parent widget does not have required listview"

        profile = gremlin.shared_state.current_profile
        device_guid = gremlin.shared_state.osc_tab_guid
        device_modes = profile.get_device_modes(device_guid, DeviceType.to_string(DeviceType.Osc))
        self._mode_object = device_modes.ensure_mode_exists(gremlin.shared_state.current_mode)

        self._config_widget = QtWidgets.QWidget()
        self._config_layout = QtWidgets.QHBoxLayout()
        self._config_widget.setLayout(self._config_layout)
        self._current_mode = current_mode
        self.index = index
        self.input_item = data
        self._mode: OscInputItem = OscInputItem.InputMode.Button
        self._command_mode: OscInputItem = OscInputItem.CommandMode.Message
        self._mode_locked = False  # if set, prevents flipping input modes axis to a button mode
        self._min_range = 0.0  # min value for axis mapping (maps to -1.0 in vjoy)
        self._max_range = 1.0  # max value for axis mapping (maps to 1.0 in vjoy)
        self._trigger_autorelease = data._trigger_autorelease
        self._pulse_delay = data._autorelease_delay
        self._source_index = data._source_index

        self._data_widgets = {}  # value of the parameter
        self._label_widgets = {}  # label for the parameter
        self._select_widgets = {}  # selection radio button for which parameter is active

        # OSC message
        self._command = None  # OSC command text
        self._command_data = []  # OSC arguments

        self._command_widget = gremlin.ui.ui_common.QDataLineEdit()
        self._command_widget.valueChanged.connect(self._command_changed)

        self._config_layout.addWidget(QtWidgets.QLabel("Cmd:"))
        self._config_layout.addWidget(self._command_widget)

        widget, layout = gremlin.ui.ui_common.getHContainer()
        self._data_container_widget = widget
        self._data_container_layout = layout

        widget, layout = gremlin.ui.ui_common.getHContainer([self._data_container_widget], "Parameters:")
        self._parameter_widget = widget

        widget, layout = gremlin.ui.ui_common.getHContainer()
        self._source_container_widget = widget
        self._source_container_layout = layout

        widget, layout = gremlin.ui.ui_common.getHContainer([self._source_container_widget], "Source:")
        self._source_widget = widget

        self._config_layout.addStretch()

        self._container_mode_radio_widget = QtWidgets.QWidget()
        self._container_mode_radio_layout = QtWidgets.QHBoxLayout(self._container_mode_radio_widget)

        self._container_mode_description_widget = gremlin.ui.ui_common.QInfoBox()

        self._container_command_mode_radio_widget = QtWidgets.QWidget()
        self._container_command_mode_radio_layout = QtWidgets.QHBoxLayout()
        self._container_command_mode_radio_widget.setLayout(self._container_command_mode_radio_layout)
        self._container_command_mode_description_widget = QtWidgets.QLabel()

        self._mode_button_widget = QtWidgets.QRadioButton("Button")
        self._mode_button_widget.setToolTip(
            "The input will behave as an on/off button based on the value.<br/>"
            "If the value is in the lower half of the range, the button is released.<br>"
            "If the value is in the upper half of the reange, the button will be pressed<br>"
        )
        self._mode_button_widget.clicked.connect(self._mode_button_cb)

        self._mode_axis_widget = QtWidgets.QRadioButton("Axis")
        self._mode_axis_widget.setToolTip("The input will be scaled (-1 to +1) based on the input's value")
        self._mode_axis_widget.clicked.connect(self._mode_axis_cb)

        self._container_range_widget = QtWidgets.QWidget()
        self._container_range_layout = QtWidgets.QHBoxLayout(self._container_range_widget)

        self._min_range_widget = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self._min_range_widget.setValue(0.0)  # default min range
        self._min_range_widget.valueChanged.connect(self._min_range_cb)
        self._max_range_widget = gremlin.ui.ui_common.DynamicDoubleSpinBox()
        self._max_range_widget.setValue(1.0)  # default min range
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

        self._trigger_on_message_widget = gremlin.ui.ui_common.QDataCheckbox(
            "Trigger on message",
            value=self.input_item._trigger_autorelease,
            callbackEx=self._autorelease_change_cb,
            tooltip="When enabled, receiving a message regardless of parameter will trigger the action with an autorelease.<br>Use this option when the OSC source message does not send >0 for press, 0 for release.",
        )

        self._trigger_on_message_delay_widget = gremlin.ui.ui_common.QDelayWidget(value=self._pulse_delay, callback=self._pulse_value_changed)

        self._container_trigger_widget = gremlin.ui.ui_common.getHContainer(
            [self._trigger_on_message_widget, self._trigger_on_message_delay_widget],
            widget_only=True,
        )

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
        self.listen_widget = gremlin.ui.ui_common.Buttons.getListenWidget(callback=self._listen_cb)

        self.button_layout.addWidget(self.listen_widget)
        self.button_layout.addStretch(1)
        self.button_layout.addWidget(self.ok_widget)
        self.button_layout.addWidget(self.cancel_widget)

        main_layout.addWidget(QtWidgets.QLabel("OSC message:"))
        main_layout.addWidget(self._config_widget)
        main_layout.addWidget(self._parameter_widget)
        main_layout.addWidget(self._source_widget)
        main_layout.addWidget(self._container_options_widget)
        main_layout.addWidget(self._container_trigger_widget)
        main_layout.addWidget(self._container_range_widget)
        main_layout.addWidget(self._container_mode_description_widget)
        main_layout.addWidget(self._container_command_mode_description_widget)
        main_layout.addWidget(self._validation_message_widget)
        main_layout.addWidget(gremlin.ui.ui_common.QHLine())
        main_layout.addWidget(self.button_widget)

        self.setLayout(main_layout)

        if data:
            input_id: OscInputItem = data
            # see if this input has any containers
            profile = gremlin.shared_state.current_profile
            for device in profile.devices.values():
                if device.name == "osc":
                    if current_mode in device.modes:
                        for input_items in device.modes[current_mode].config.values():
                            if data in input_items:
                                item = input_items[data]
                                self._mode_locked = len(item.containers) > 0  # lock mode to prevent axis to button/change
                                break

            message = input_id.message
            if message:
                self._mode = input_id.mode
                self._command_mode = input_id.command_mode
                self._command = input_id.message
                self._command_data = input_id.data

        self._validate()
        self._update_parameters_from_command()
        self._update_display()

    @QtCore.Slot()
    def _command_changed(self):
        """command text changed"""
        self._command = self._command_widget.text()
        self._validate()

    def _pulse_value_changed(self, value):
        """called when the pulse value changes"""
        if value >= 0:
            self._pulse_delay = value

    def _validate(self):
        """validates the input to ensure it does not conflict with an existing input"""
        # assume ok
        if not Shiboken.isValid(self):
            return True
        valid = True
        try:
            self._validation_message_widget.setText("")
            if self._command is not None:
                # get the list of all the other inputs
                parent_widget = self._parent
                model = parent_widget.inputItemListModel
                message = self._command

                input_item = OscInputItem(self._mode_object)
                input_item._message = message
                input_item._message_data = self._command_data
                input_item._command_mode = self._command_mode
                input_item._mode = self._mode
                input_item._source_index = self._source_index
                input_item._update()  # this updates the message key
                key = input_item.message_key
                visible_indices = model.getFilteredIndices()
                for index in range(len(visible_indices)):
                    input_item: OscInputItem = parent_widget.itemAt(index)
                    if not input_item:
                        continue
                    if index == self.index:
                        continue  # ignore self
                    # grab the input's configured osc message
                    other_input = input_item
                    other_message = other_input.message
                    if other_message is None:
                        # input not set = ok
                        continue

                    other_key = other_input.message_key
                    if key == other_key:
                        if self._source_index != other_input._source_index:
                            # same key, different sources = ok
                            continue

                        syslog.info(f"OSC: conflict detected: key {key} is the same as {other_key}")
                        self._validation_message_widget.setText(f"Input conflict detected with input [{index + 1}] - ensure inputs are unique")
                        warning_color = gremlin.ui.ui_common.Color.warningColor()
                        icon_color = QtGui.QColor(warning_color)
                        self._validation_message_widget.setIcon("ph.shield-warning-fill", True, color=icon_color)
                        valid = False
                        return

                if self._mode == OscInputItem.InputMode.Axis:
                    # cannot be an axis mode for sysex or program change

                    # valid = len(self._command_data) > 0 # in axis mode, data MUST be provided
                    # if not valid:
                    #     self._validation_message_widget.setText(f"Data value must be given in axis mode")
                    #     self._validation_message_widget.setIcon("ph.shield-warning-fill",True, color="red")
                    #     return

                    if self._min_range > self._max_range:
                        self._validation_message_widget.setText("Min range must be less than max range")
                        warning_color = gremlin.ui.ui_common.Color.warningColor()
                        icon_color = QtGui.QColor(warning_color)
                        self._validation_message_widget.setIcon("ph.shield-warning-fill", True, color=icon_color)
                        return

                    if self._min_range == self._max_range:
                        self._validation_message_widget.setText("Min range cannot be the same as the max range")
                        warning_color = gremlin.ui.ui_common.Color.warningColor()
                        icon_color = QtGui.QColor(warning_color)
                        self._validation_message_widget.setIcon("ph.shield-warning-fill", True, color=icon_color)
                        return

                    # ensure the argument is numeric
                    if not self._command_data:
                        self._command_data = [0]
                    arg = self._command_data[0]
                    if not (isinstance(arg, int) or isinstance(arg, float)):
                        self._validation_message_widget.setText("First data item must be a number for axis input")
                        warning_color = gremlin.ui.ui_common.Color.warningColor()
                        icon_color = QtGui.QColor(warning_color)
                        self._validation_message_widget.setIcon("ph.shield-warning-fill", True, color=icon_color)
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

    @QtCore.Slot()
    def _mode_change_cb(self):
        if self._mode_on_change_widget.isChecked():
            self._mode = OscInputItem.InputMode.OnChange
            self._update_display()

    @QtCore.Slot(bool)
    def _autorelease_change_cb(self, widget, checked):
        self._trigger_autorelease = checked
        self.input_item._trigger_autorelease = checked
        self._update_display()

    @QtCore.Slot()
    def _command_mode_message_cb(self):
        if self._command_mode_message_widget.isChecked():
            self._command_mode = OscInputItem.CommandMode.Message
            self._update_display()

    @QtCore.Slot()
    def _command_mode_data_cb(self):
        if self._command_mode_data_widget.isChecked():
            self._command_mode = OscInputItem.CommandMode.Data
            self._update_display()

    @QtCore.Slot()
    def _min_range_cb(self):
        self._min_range = self._min_range_widget.value()
        self._validate()

    @QtCore.Slot()
    def _max_range_cb(self):
        self._max_range = self._max_range_widget.value()
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

    @property
    def source_index(self) -> int:
        return self._source_index

    @source_index.setter
    def source_index(self, value: int):
        if value >= 0:
            self._source_index = value

    def _set_parameter(self, index, value):
        """sets a data parameter - if the index does not exist, it's created"""
        if not Shiboken.isValid(self):
            return

        if index not in self._data_widgets:
            widget = gremlin.ui.ui_common.QDataLineEdit()
            widget.setReadOnly(True)
            widget.data = index
            label = QtWidgets.QLabel(f"P{index + 1}:")
            selector = gremlin.ui.ui_common.QDataRadioButton(f"P{index + 1}")
            selector.data = index
            if index == self._source_index:
                selector.setChecked(True)
            selector.clicked.connect(self._active_parameter_cb)
            self._data_widgets[index] = widget
            self._label_widgets[index] = label
            self._select_widgets[index] = selector

            self._data_container_layout.addWidget(label)
            self._data_container_layout.addWidget(widget)
            self._source_container_layout.addWidget(selector)

        self._label_widgets[index].setVisible(True)
        self._select_widgets[index].setVisible(True)
        self._data_widgets[index].setVisible(True)

        self._data_widgets[index].setText(str(value))

    @QtCore.Slot()
    def _active_parameter_cb(self):
        widget = self.sender()
        self._source_index = widget.data
        self._validate()

    def _clear_parameters(self):
        """clears paramters UI"""
        if not Shiboken.isValid(self):
            return
        for index in self._data_widgets.keys():
            self._label_widgets[index].setVisible(False)
            self._select_widgets[index].setVisible(False)
            self._data_widgets[index].setVisible(False)

    def _update_parameters_from_command(self):
        if not Shiboken.isValid(self):
            return
        self._clear_parameters()
        if self._command_data:
            for index, value in enumerate(self._command_data):
                self._set_parameter(index, value)

    def _command_parameters(self) -> list:
        index_list = [index for index in self._data_widgets.keys()]
        index_list.sort()
        values = [self._data_widgets[index].value() for index in index_list]
        return values

    def _update_display(self):
        """loads message data into the UI"""
        if not Shiboken.isValid(self):
            return
        # mode radio buttons
        autorelease_visible = False
        parameters_visible = True
        range_visible = False
        delay_enabled = False
        # config = gremlin.config.Configuration()

        if self._mode == OscInputItem.InputMode.Button:
            if self.input_item._trigger_autorelease:
                msg = "Autorelease mode.<br>The input will trigger a press action when a message is received, followed by a release when the delay has lapsed.<br>Use this mode to trigger a button press/release when an OSC message arrives."
                delay_enabled = True
            else:
                msg = "The input will trigger a press action when the first parameter value is not zero (0).<br>A value of zero (0) will trigger a release action.<br>Use this to mode to trigger button presses from OSC messages."
            self._container_mode_description_widget.setText(msg)
            if not self._mode_button_widget.isChecked():
                with QtCore.QSignalBlocker(self._mode_button_widget):
                    self._mode_button_widget.setChecked(True)
            autorelease_visible = True
            parameters_visible = False

        elif self._mode == OscInputItem.InputMode.Axis:
            self._container_mode_description_widget.setText(
                "The input act as an axis input using the OSC value.<br>Use this mode if mapping to an axis output (OSC value messages only)"
            )
            # self._command_mode = OscInputItem.CommandMode.Message # force message mode in axis as the value will determine the state
            with QtCore.QSignalBlocker(self._mode_axis_widget):
                self._mode_axis_widget.setChecked(True)
            range_visible = True

        elif self._mode == OscInputItem.InputMode.OnChange:
            self._container_mode_description_widget.setText(
                "The input will trigger a button press on any value change<br>Use this mode to trigger a button or action whenever the OSC command value changes."
            )
            with QtCore.QSignalBlocker(self._mode_on_change_widget):
                self._mode_on_change_widget.setChecked(True)

        if self._command_mode == OscInputItem.CommandMode.Message:
            self._container_command_mode_description_widget.setText("The OSC message is the primary input (data ignored)")
            with QtCore.QSignalBlocker(self._command_mode_message_widget):
                self._command_mode_message_widget.setChecked(True)
                self._data_container_widget.setEnabled(False)  # disable the value area if in message only mode
        elif self._command_mode == OscInputItem.CommandMode.Data:
            self._container_command_mode_description_widget.setText("The OSC message and arguments are used as the primary input")
            with QtCore.QSignalBlocker(self._command_mode_data_widget):
                self._command_mode_data_widget.setChecked(True)
            self._data_container_widget.setEnabled(True)  # enable the value area if in message + data mode

        self._container_range_widget.setVisible(self._mode == OscInputItem.InputMode.Axis)
        with QtCore.QSignalBlocker(self._command_widget):
            self._command_widget.setText(self._command)

        self._data_container_widget.setVisible(parameters_visible)
        self._source_container_widget.setVisible(parameters_visible)
        self._container_trigger_widget.setVisible(autorelease_visible)
        self._trigger_on_message_delay_widget.setEnabled(delay_enabled)
        self._container_range_widget.setVisible(range_visible)

    def _update_message(self):
        """updates message data from UI"""
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

    def _ok_button_cb(self):
        """ok button pressed"""
        gremlin.shared_state.pop_suspend_highlighting()
        self._update_message()  # update data from UI
        self.accept()

    def _cancel_button_cb(self):
        """cancel button pressed"""
        gremlin.shared_state.pop_suspend_highlighting()
        self.reject()

    def _listen_cb(self, current_port_only=False):
        """listens to an inbound message"""
        gremlin.util.InvokeUiMethod(self._listen_ui, current_port_only)

    def _listen_ui(self, current_port_only=False):
        """listens to an inbound OSC message - runs on UI thread"""

        gremlin.util.assert_ui_thread()
        _config = gremlin.config.Configuration()
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
            150,
        )
        self.listener_dialog.show()

    def _capture_message(self, command, data):
        """called when an OSC message is captured"""
        gremlin.util.assert_ui_thread()
        self._command = command
        self._command_data = data
        self._validate()
        self._update_parameters_from_command()
        self._update_display()  # update UI with these settings

        if not data and command:
            # no args - enable auto release
            self._trigger_autorelease = True
            if Shiboken.isValid(self):
                with QtCore.QSignalBlocker(self._trigger_on_message_widget):
                    self._trigger_on_message_widget.setChecked(True)

    @property
    def command(self):
        """returns the current command"""
        return self._command

    @command.setter
    def command(self, value):
        if value is None:
            value = ""  # catch None type
        self._command = value
        self._update_display()

    @property
    def mode(self):
        """gets the current input mode"""
        return self._mode

    @mode.setter
    def mode(self, value):
        self._mode = value
        self._update_display()

    @property
    def command_mode(self):
        """returns the command type"""
        return self._command_mode

    @command_mode.setter
    def command_mode(self, value):
        self._command_mode = value
        self._update_display()

    @property
    def data(self) -> list:
        """returns a list of parameters for that command"""
        return self._command_data

    @data.setter
    def data(self, value):
        self._command_data = value
        self._update_parameters_from_command()
        self._update_display()


class OscFilterWidget(QtWidgets.QWidget):
    """displays a filter widget that can be enabled, and a state category selected"""

    changed = Signal(str)  # fires when the filter is changed (passes the filter)
    select = Signal(object)  # request to select an item

    def __init__(self, model : OscInputItemModel, parent=None):
        super().__init__(parent)
        assert isinstance(model, OscInputItemModel), "model must be an instance of OscInputItemModel"

        self._config = gremlin.config.Configuration()

        self.main_layout = QtWidgets.QVBoxLayout(self)

        # filter widget
        self._model = model

        current_filter = self._config.osc_filter

        self._filter_widget = gremlin.ui.ui_common.QDataLineEdit(text=current_filter, tooltip="Enter filter text")
        self._filter_widget.enterPressed.connect(self._apply_filter) # apply the filter

        self._find_widget = gremlin.ui.ui_common.Buttons.getSearchWidget(callback=self._find_entry, tooltip="Search (F3)")

        self._apply_widget = QtWidgets.QPushButton("Apply")
        self._apply_widget.setToolTip("Apply current filter")
        self._apply_widget.clicked.connect(self._apply_filter)

        self._clear_filter_widget = gremlin.ui.ui_common.Buttons.getClearWidget(callback=self._clear_filter, label=None)
        self._clear_filter_widget.setMaximumWidth(24)

        widget = gremlin.ui.ui_common.getHContainer(
            [
                self._find_widget,
                "||",
                # self._filter_enabled_widget,
                QtWidgets.QLabel(" Filter:"),
                self._filter_widget,
                "||",
                self._apply_widget,
                self._clear_filter_widget,
            ],
            widget_only=True,
        )

        self.main_layout.addWidget(widget)

        # count row
        self._count_widget = QtWidgets.QLabel()
        widget = gremlin.ui.ui_common.getHContainer(self._count_widget, widget_only=True)

        self.main_layout.addWidget(widget)
        self.main_layout.setSpacing(2)

        self._last_search_index = -1  # last search index for a successful search
        self._last_search_term = None  # last search term for a succesful search

        self._update_count()

    def _find_entry(self):
        """occurs when the find button is clicked"""
        gremlin.util.InvokeUiMethod(self._find_entry_ui)

    def _find_entry_ui(self):
        """displays the find dialog"""
        config = gremlin.config.Configuration()
        current_term = config.osc_last_search_term
        self._dialog = gremlin.ui.ui_common.QInputDialog("Find OSC message", "Search for:", text=current_term)
        self._dialog.accepted.connect(self._find_entry_accept)
        self._dialog.setModal(True)
        self._dialog.show()

    def _find_entry_accept(self):
        new_term = self._dialog.text()
        self.find_next(new_term)

    def find_next(self, search_term: str):
        """finds the next entry"""
        config = gremlin.config.Configuration()

        if search_term:
            config.osc_last_search_term = search_term
            input_item: OscInputItem
            decorated_search_term = gremlin.util.decorate_filter(search_term)
            data = self._model
            matches = [
                (index, item)
                for index, item in data.items()
                if item.input_id.message and (fnmatch.fnmatch(item.input_id.message, decorated_search_term) or search_term in item.input_id.message)
            ]
            if matches:
                index_list = [i for (i, item) in matches]
                index_list.sort()
                last_index = -1
                if self._last_search_term == search_term:
                    # same index
                    last_index = self._last_search_index

                    # syslog.info(f"last search index: {last_index}")

                if last_index < 0 or last_index >= len(index_list):
                    last_index = 0  # round robin to first index

                # syslog.info(f"search index: {last_index}")
                index = index_list[last_index]
                input_item = data[index]


                self._last_search_term = search_term
                self._last_search_index = last_index + 1  # next search index

                el = gremlin.event_handler.EventListener()
                el.select_input.emit(input_item.device_guid, input_item.input_type, input_item.input_id, False, True, False, None)
            else:
                gremlin.ui.ui_common.MessageBox(prompt="Term not found")
                self._last_search_term = search_term
                self._last_search_index = -1

    def _update_count(self):
        """updates the count of defined inputs"""
        total = self._model.rows()
        count = self._model.count()

        plural = "s" if total > 1 else ""
        if total == 0:
            msg = "<i>(no inputs found)</i>"
        elif count != total:
            msg = f"<i>({count:,} of {total:,} OSC input{plural})</i>"
        else:
            msg = f"<i>({total:,} OSC input{plural})</i>"
        self._count_widget.setText(msg)

    def updateCounts(self):
        """updates the model counts"""
        self._update_count()

    def _clear_filter(self):
        value = self._filter_widget.text()
        if value:
            # if there is a filter, clear it
            with QtCore.QSignalBlocker(self._filter_widget):
                self._filter_widget.setText(None)
            self._config.osc_filter = ""
            self.changed.emit("")

    def _apply_filter(self):
        """applies the filter"""
        value = self._filter_widget.text()
        self._config.osc_filter = value
        self.changed.emit(value)


    def clearFilter(self):
        """clears the filter"""
        self._clear_filter()

    @property
    def filter(self) -> str:
        return self._filter_widget.text()


class OscBulkLoadDialog(gremlin.ui.ui_common.QRememberDialog):
    """dialog showing a virtual keyboard in which to select key combinations with the keyboard or mouse"""

    closed = QtCore.Signal()  # sent when the dialog closes

    def __init__(self, parent=None):
        """
        :param sequence - input keys to use
        :param select_single - if set, only can select a single key
        :param allow_modifiers - if set - modifier keys along with regular keys are allowed
        """
        super().__init__(self.__class__.__name__, parent=parent)

        main_layout = QtWidgets.QVBoxLayout(self)

        main_layout.addWidget(QtWidgets.QLabel("New OSC messages:"))

        self.text_widget = QtWidgets.QPlainTextEdit()

        main_layout.addWidget(self.text_widget)

        msg = """Enter new OSC messages one per line.  Messages must start with a forward slash (/). Entries may be given a suffix to set the type automatically. The default is a button.  If you are importing an axis message, add the suffix A after the message such as /osc_msg A or /osc_msg, A
Valid suffixes are A for axis, BNP for a no paramater (auto-release) button, B for a parameter button (0 = released, not 0 = pressed), C for change, E for encoder.
Existing entries will be ignored.
"""

        info_box = gremlin.ui.ui_common.QInfoBox(msg)
        main_layout.addWidget(info_box)

        cancel_button_widget = QtWidgets.QPushButton("Cancel")
        cancel_button_widget.clicked.connect(self._cancel_cb)

        ok_button_widget = QtWidgets.QPushButton("Ok")
        ok_button_widget.clicked.connect(self._close_cb)

        widget = gremlin.ui.ui_common.getHContainer(
            [ok_button_widget, cancel_button_widget],
            left_stretch=True,
            widget_only=True,
        )
        button_container_widget = widget

        main_layout.addWidget(button_container_widget)
        self.setModal(True)

    def _close_cb(self):
        self.accept()
        self.close()

    def _cancel_cb(self):
        self.close()

    def text(self):
        return self.text_widget.toPlainText()


class OscInputItemModel(gremlin.input_item.InputItemListModel):
    """model for OSC input items"""

    def __init__(
        self,
        profile: gremlin.base_profile.Profile,
        mode: str,
        custom_load_handler: Callable = None,
        custom_remove_handler: Callable = None,
        custom_filter_handler: Callable = None,
    ):
        """initializes the model
        :param profile: the profile containing the data
        :param mode: the mode containing the data
        :param custom_filter_handler: optional function to filter items, takes an OscInputItem

        """
        super().__init__(
            profile=profile,
            device_guid=OscDeviceTabWidget.device_guid,
            mode=mode,
            allowed_types=[InputType.OpenSoundControl],
            custom_load_handler=custom_load_handler,
            custom_remove_handler=custom_remove_handler,
            custom_filter_handler=custom_filter_handler,
        )


class OscDeviceTabWidget(BaseDeviceTabWidget):
    """Widget used to configure open sound control (OSC) inputs"""

    # IMPORTANT: MUST BE A DID FORMATTED ID ON CUSTOM INPUTS
    device_guid = gremlin.shared_state.osc_tab_guid

    def __init__(
        self,
        profile: gremlin.base_profile.Profile,
        mode: str,
        object_name="OSC Device",
        parent=None,
    ):
        """Creates a new object instance.

        :param profile profile data of the entire device
        :param mode the current mode to display
        :param parent the parent of this widget
        """

        device = gremlin.joystick_handling.getDevice(self.device_guid)
        super().__init__(
            device=device,
            profile=profile,
            mode=mode,
            object_name=object_name,
            custom_input_widget_callback=self._custom_widget_handler,
            blank_input_message="Please add an OSC input.",
            parent=parent,
        )

        config = gremlin.config.Configuration()

        self._filter = gremlin.util.decorate_filter(config.osc_filter)
        self._in_input_dialog = False  # flag to deal with focus issue

        self._last_selected_index = -1  # index of last input, -1 if none

        # List of inputs
        model = OscInputItemModel(
            profile=self.profile,
            mode=mode,
            custom_load_handler=self._load_handler,
            custom_remove_handler=self._remove_handler,
            custom_filter_handler=self._handle_filter_data,
        )

        self.setInputItemListModel(model)

        # lock widget
        lock_widget = gremlin.ui.ui_common.QInputLockWidget(data=self.device_guid)
        widget = gremlin.ui.ui_common.getHContainer(["OSC Inputs", "||", lock_widget], widget_only=True)
        self.addLeftPanelHeaderWidget(widget)

        if config.show_container_id:
            device = gremlin.joystick_handling.get_device(self.device_guid)
            width = gremlin.ui.ui_common.get_text_width(gremlin.util.get_guid())
            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.device_id)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device ID:", widget_only=True)
            self.addLeftPanelHeaderWidget(widget)
            w1 = widget

            line_edit = gremlin.ui.ui_common.QDataLineEdit()
            line_edit.setText(device.name)
            line_edit.setReadOnly(True)
            line_edit.setMinimumWidth(width)
            widget = gremlin.ui.ui_common.getGridContainer(line_edit, "Device Name:", widget_only=True)
            self.addLeftPanelHeaderWidget(widget)
            w2 = widget

            gremlin.ui.ui_common.synchronize_grids([w1, w2])

        # filter view
        self._filter_widget = OscFilterWidget(self.inputItemListModel)
        self._filter_widget.changed.connect(self._filter_changed)
        self._filter_widget.select.connect(self._select_input_item_cb)

        self.addLeftPanelHeaderWidget(self._filter_widget)

        button_container_widget = QtWidgets.QWidget()
        button_container_layout = QtWidgets.QHBoxLayout(button_container_widget)

        # key clear button

        clear_button = ui_common.ConfirmPushButton("Clear", show_callback=self._show_clear_cb)
        icon = gremlin.ui.ui_common.Icons.trashIcon()
        clear_button.setIcon(icon)
        clear_button.setToolTip("Deletes all OSC inputs")
        clear_button.confirmed.connect(self._clear_inputs_cb)
        button_container_layout.addWidget(clear_button)
        button_container_layout.addStretch(1)

        # sort button
        sort_button = QtWidgets.QPushButton("Sort")
        sort_button.setToolTip("Sorts the command by message")
        icon = gremlin.util.load_icon("fa5s.sort-alpha-down")
        sort_button.setIcon(icon)
        sort_button.clicked.connect(self._sort_input_cb)
        button_container_layout.addWidget(sort_button)

        # Key add button
        add_button = QtWidgets.QPushButton("Add")
        add_button.setToolTip("Adds a new OSC message input to the profile")
        icon = gremlin.ui.ui_common.Icons.addIcon()
        add_button.setIcon(icon)
        add_button.clicked.connect(self._add_input_cb)

        button_container_layout.addWidget(add_button)

        # load from list button - load / edit from list
        load_button = QtWidgets.QPushButton("Import")
        load_button.setToolTip("Adds multiple OSC message inputs to the profile from a list.")
        icon = gremlin.ui.ui_common.Icons.addIcon(gremlin.ui.ui_common.Color.yellowColor())
        load_button.setIcon(icon)
        load_button.clicked.connect(self._handle_bulk_load)
        button_container_layout.addWidget(load_button)

        self.addLeftPanelHeaderWidget(button_container_widget)

        el = gremlin.event_handler.EventListener()
        # update on an edit mode change so we update the display
        el.edit_mode_changed.connect(self._handle_edit_mode_changed)
        el.config_changed.connect(self._config_changed_cb)
        # lock all inputs
        el.lock_inputs.connect(self._handle_lock_inputs)
        el.unlock_inputs.connect(self._handle_unlock_inputs)
        el.find_next.connect(self._handle_find_next)

        # re-apply filters after config is loaded
        self.inputItemListModel.applyFilter()

    def _load_handler(self, model: OscInputItemModel, emit=True) -> bool:
        """called when the data model for the input list needs to be updated - refreshes the model view"""

        model.pushSuspend()  # suspend triggers
        model.clear(emit=False)
        registry = gremlin.shared_state.current_profile.registry
        mode = gremlin.shared_state.edit_mode
        input_list = registry.getInputItems(self.device_guid, mode, InputType.OpenSoundControl)
        if len(input_list) > 0:
            input_list.sort(key=lambda x: x.sortKey)
            for index, input_item in enumerate(input_list):
                model.setItemAt(index, input_item)

        model.popSuspend()  # resume triggers
        if emit:
            model.trigger()  # causes an update
        return True

    def _remove_handler(self, model: OscInputItemModel, index, emit_change=True):
        """clears a single index"""
        if index in model._index_map:
            del model._index_map[index]
            item = next((key for key, data in model._item_map.items() if data == index), None)
            if item:
                del model._item_map[item]

            model._update_filter()

    def _handle_filter_data(self, input_item) -> bool:
        """custom filter handler - true if the data is included in the filter, false otherwise"""
        import fnmatch

        if not self._filter:
            return True  # ok
        item: OscInputItem = input_item.input_id
        key = item.message
        if not key:
            # no key = match
            return True

        key = item.message.casefold().strip()

        include = fnmatch.fnmatch(key, self._filter)
        syslog.info(f"Filter check: key='{key}', filter='{self._filter}', result={include}")
        return include

    def onInputListViewCreated(self):
        """called when input item list view is created"""
        # Handle user interaction
        self.inputItemListView.item_edit.connect(self._edit_item_cb)
        self.inputItemListView.item_closed.connect(self._close_item_cb)
        self.inputItemListView.updated.connect(self._update_conflicts)

    def onInputListViewRemoved(self):
        """called when input item list view is removed"""
        # Handle user interaction
        self.inputItemListView.item_edit.disconnect(self._edit_item_cb)
        self.inputItemListView.item_closed.disconnect(self._close_item_cb)
        self.inputItemListView.updated.disconnect(self._update_conflicts)

    @property
    def inputCount(self) -> int:
        """number of inputs in the device"""
        return self.inputItemListModel.rows()

    @property
    def inputWidgetCount(self) -> int:
        """number of input widgets currently in the device"""
        return self.inputItemListView.count()

    def _handle_lock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_lock_inputs_ui, data)  # ensure on UI thread

    def _handle_unlock_inputs(self, data):
        gremlin.util.InvokeUiMethod(self._handle_unlock_inputs_ui, data)  # ensure on UI thread

    def _handle_lock_inputs_ui(self, data):
        """lock all inputs event"""
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = True
            self.setUpdatesEnabled(True)

    def _handle_unlock_inputs_ui(self, data):
        """unlock all inputs event"""
        if Shiboken.isValid(self) and data == self.device_guid:
            # ours
            self.setUpdatesEnabled(False)
            for input_item in self.inputItemListModel.getFilteredItems():
                input_item.locked = False
            self.setUpdatesEnabled(True)

    def _handle_find_next(self):
        """finds the next item"""
        if gremlin.shared_state.current_tab_device_guid == gremlin.shared_state.osc_tab_id:
            term = gremlin.config.Configuration().osc_last_search_term  # last search term
            if term:
                gremlin.util.InvokeUiMethod(self._filter_widget.find_next, term)



    def _filter_changed(self, filter):
        """called when the filter changes"""
        self._filter = gremlin.util.decorate_filter(filter)

        self.inputItemListModel.applyFilter()
        self._filter_widget.updateCounts()

    def find_item(self, device_guid, input_type, input_id) -> OscInputItem:
        """locates the input item, returns none if not found"""
        for input_item in self.inputItemListModel:
            if input_item.device_guid == device_guid and input_item.input_type == input_type and input_item.input_id == input_id:
                return input_item
        return None  # not found

    def find_item_by_message(self, mode: str, msg: str) -> tuple[int, OscInputItem]:
        """looks for OSC input messages to see if there's a match"""
        msg = msg.strip().casefold()
        model = self.inputItemListModel

        for index, input_item in enumerate(model):
            if input_item.mode_string == mode and input_item.message == msg:
                return (index, input_item)

        return (-1, None)

    def _handle_edit_mode_changed(self, mode: str):
        """occurs when a new mode is selected"""
        gremlin.util.InvokeUiMethod(self._edit_mode_changed_ui, mode)  # ensure on UI thread

    def _edit_mode_changed_ui(self, mode: str):
        """occurs when a mode is selected (ui thread)"""
        self.set_mode(mode)

    def _config_changed_cb(self):
        """called when configuraition has changed"""
        self.refresh()

    def display_name(self, input_id):
        """returns the name for the given input ID"""
        return input_id.display_name

    def _show_clear_cb(self):
        return self.inputItemListModel.rows() > 0

    @QtCore.Slot()
    def _clear_inputs_cb(self):
        """clears all input keys"""
        self.inputItemListModel.clear(input_types=[InputType.OpenSoundControl])

        # add a blank input configuration if nothing is selected - the configuration widget is always the second widget of the main layout
        self._blank_input()

    @QtCore.Slot()
    def _add_input_cb(self):
        """Adds a new input to the inputs list"""
        profile: gremlin.base_profile.Profile = gremlin.shared_state.current_profile
        device_node = profile.getDeviceNode(self._device_guid)
        mode_node = device_node.getModeNode(gremlin.shared_state.current_mode)
        input_item = OscInputItem(mode_node)
        input_item.input_type_changed.connect(self._refresh_mappings)

        mode_node.addInputItem(input_item)

        self.inputItemListModel.refresh()
        index = self.inputItemListModel.indexOf(input_item)
        self.inputItemListView.selectItemAt(index)

        self._edit_item_cb(None, index, input_item)

    @QtCore.Slot()
    def _handle_bulk_load(self):
        """loads bulk inputs"""

        self.bulk_dialog = OscBulkLoadDialog()
        self.bulk_dialog.showNormal()
        self.bulk_dialog.accepted.connect(self._handle_bulk_accepted)

    def _handle_bulk_accepted(self):

        text = self.bulk_dialog.text()
        self.bulk_dialog = None

        # parse the data
        if not text:
            return  # nothing to do

        # new input list
        new_messages = {}

        # parse the data
        for line in text.splitlines():
            line = line.replace(",", " ")  # remove commas
            tokens = line.split()

            if tokens:
                count = len(tokens)
                match count:
                    case 2:
                        # msg and param
                        msg = tokens[0]
                        msg_mode = tokens[1].casefold()
                    case 1:
                        msg = tokens[0]
                        msg_mode = "b"
                    case _:
                        syslog.info(f"OSC: bulk load skip: unable to parse: [{line}]")
                        continue

                new_messages[msg] = msg_mode

        if new_messages:
            profile = gremlin.shared_state.current_profile
            mode = gremlin.shared_state.current_mode
            imported_list = []

            device_node = profile.getDeviceNode(self._device_guid)
            mode_node = device_node.getModeNode(gremlin.shared_state.current_mode)

            self.inputItemListModel.pushSuspend()

            for msg, msg_mode in new_messages.items():
                _, osc = self.find_item_by_message(mode, msg)
                if osc:
                    # already in the list, skip
                    syslog.info(f"OSC: bulk load skip: [{msg}] is already defined for mode [{mode}]")
                    continue

                input_item = OscInputItem(mode_node)
                input_item.message = msg
                mode = OscInputItem.InputMode.Button
                auto_release = False
                match msg_mode:
                    case "b":
                        # button mode
                        pass

                    case "bnp":
                        # button mode, autorelease, no param
                        auto_release = True

                    case "c":
                        # button mode, on change
                        mode = OscInputItem.InputMode.OnChange
                    case "a":
                        # axis mode
                        mode = OscInputItem.InputMode.Axis

                    case "e":
                        # encoder mode
                        mode = OscInputItem.InputMode.Encoder

                    case _:
                        syslog.info(f"OSC: bulk load skip: [{msg}] unknown option: [{mode}]")

                # add the new input item

                input_item.setMode(mode)
                input_item.autoRelease = auto_release
                mode_node.addInputItem(input_item)
                imported_list.append(input_item)
                input_item.input_type_changed.connect(self._refresh_mappings)

            self.inputItemListModel.popSuspend()

            if imported_list:
                # # reload list
                # self.inputItemListModel.refresh()
                self.inputItemListView.selectInputItem(imported_list[0])

            # show results
            gremlin.ui.ui_common.MessageBox(prompt=f"Imported {len(imported_list):,} entries.", is_warning=False)

    @QtCore.Slot()
    def _sort_input_cb(self):

        if not self.inputItemListModel.rows():
            # nothing to sort
            return
        index = self._last_selected_index
        current_selection = None
        if index != -1:
            current_selection = self.inputItemListModel.data(index)

        self.inputItemListModel.sort(self._sort_callback)
        # self.inputItemListView.redraw()

        if current_selection:
            # reselect the saved item - because the inputs were likely recreated - we can't compare the old with the new
            # so we need to find the matching data packet
            self.selectInputItemIndex(current_selection.index)

    def _sort_callback(self, item_list: list) -> list:
        """callback for sorting inputs in this device"""
        item_list.sort(key=lambda x: x.input_id.message.casefold())  # sort alpha no case
        return item_list

    def _index_for_key(self, input_id):
        """returns the index of the selected input id"""
        mode = self.device_profile.modes[self.current_mode]
        sorted_keys = list(mode.config[InputType.OpenSoundControl].keys())
        return sorted_keys.index(input_id)

    def _refresh_mappings(self, item):
        """called when the mappings should be refreshed due to input change"""
        pass

    def getWidgetKey(self, input_type, input_id):
        """gets the content widget compound key for the item / input combination"""
        return (self.device_guid, input_type, input_id)

    def _select_input_item_cb(self, input_item, emit=True):
        """select by input"""
        input_id = input_item.input_id
        index = self.inputItemListModel.indexOf(input_id)
        if index == -1:
            self.clearFilter()
            index = self.inputItemListModel.indexOf(input_id)
        if index != -1:
            self.selectInputItemIndex(index)

    def clearFilter(self):
        """clears the current data filter"""
        self._filter_widget.clearFilter()
        self.inputItemListModel.refresh()

    def _close_item_cb(self, widget, index, data):
        """called when the close button is clicked"""
        key = self.getRegisteredKeyIndex(index)
        self.unregisterWidget(key)
        if not self.inputItemListModel.rows():
            # display blank page if no item left
            self._blank_input()

    def _custom_widget_handler(self, list_view, index: int, identifier: InputIdentifier, data, parent=None):
        """creates a widget for the input

        the widget must have a selected property
        :param list_view The list view control the widget to create belongs to
        :param index The index in the list starting at 0 being the top item
        :param identifier the InpuIdentifier for the input list
        :param data the data associated with this input item

        """

        widget = OscInputItemWidget(
            input_item=identifier.input_item,
            populate_ui_callback=self._populate_input_widget_ui,
            update_callback=self._update_input_widget,
            config_external=True,
            parent=parent,
            data=data,
        )
        widget._identifier = data
        widget.create_action_icons(data)
        widget.setInputDescription(data.display_name)
        widget.enable_close()
        widget.enable_edit()
        widget.setIcon("mdi.surround-sound")

        # remember what widget is at what index
        widget.index = index
        return widget

    def _update_conflicts(self):
        # check for conflicts with other entries
        # model = self.inputItemListModel
        widgets = self.inputItemListView.getWidgets()
        # widgets = [self.itemAt(index) for index in range(model.rows())]
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
                    warning_color = gremlin.ui.ui_common.Color.warningColor()
                    icon_color = QtGui.QColor(warning_color)

                    self._set_status(
                        widget,
                        "ph.shield-warning-fill",
                        f"Input conflict detected with input [{input_widget_index + 1}]",
                        color=icon_color,
                    )
                    self._set_status(
                        input_widget,
                        "ph.shield-warning-fill",
                        f"Input conflict detected with input [{index + 1}]",
                        color=icon_color,
                    )
                    conflicted_widgets.append(widget)
                    conflicted_widgets.append(input_widget)
                    break

        ok_widgets = [widget for widget in widgets if widget not in conflicted_widgets]
        for widget in ok_widgets:
            self._set_status(widget)

    def _set_status(self, widget, icon=None, status=None, use_qta=True, color=None):
        """sets the status of an input widget"""
        status_widget = widget.findChild(gremlin.ui.ui_common.QIconLabel, "status")
        if status_widget:
            if color:
                status_widget.setIcon(icon, use_qta=use_qta, color=color)
            else:
                status_widget.setIcon(icon, use_qta=use_qta)

            status_widget.setText(status)
            status_widget.setVisible(status is not None)

    def _update_input_widget(self, input_widget, container_widget):
        """called when the widget has to update itself on a data change"""
        input_item: OscInputItem = input_widget.input_item
        input_item._update_display_name()
        # background_color = gremlin.ui.ui_common.Color.entryBackgroundColor()
        # border_color = gremlin.ui.ui_common.Color.keyBorderColor()

        # css = f"""
        #     QLabel {{
        #         background-color: {background_color};
        #         padding: 4px;
        #         border-radius: 8px;
        #         border: solid {background_color};
        #         margin: 4px;
        #         }}
        # """
        css = gremlin.ui.ui_common.Color.cssEntry()
        input_widget.setTitle(input_item.title_name)
        input_widget.setInputDescription(input_item.display_name)
        input_widget.setInputDescriptionStyle(css)
        input_widget.setToolTip(input_item.display_tooltip)

        status_text = ""
        is_warning = False
        if not input_item.message:
            is_warning = True
            status_text = "Not configured"

        icon = None
        if is_warning:
            warning_color = gremlin.ui.ui_common.Color.warningColor()
            icon_color = QtGui.QColor(warning_color)
            icon = gremlin.util.load_icon("ph.shield-warning-fill", use_qta=True, qta_color=icon_color)

        input_widget.setStatus(status_text, icon)

    def _populate_input_widget_ui(self, input_widget, container_widget, data=None):
        """called when a button is created for custom content"""
        layout = QtWidgets.QVBoxLayout(container_widget)
        status_widget = gremlin.ui.ui_common.QIconLabel()
        status_widget.setObjectName("status")
        layout.addWidget(status_widget)
        self._update_input_widget(input_widget, container_widget)

    def _edit_item_cb(self, widget, index, data):
        """called when the edit button is clicked"""
        current_mode = gremlin.shared_state.edit_mode
        self._edit_dialog = OscInputConfigDialog(current_mode, index, data, parent=self)
        self._edit_dialog.accepted.connect(self._dialog_ok_cb)
        self._edit_dialog.rejected.connect(self._dialog_rejected_cb)
        gremlin.util.centerDialog(self._edit_dialog)
        self._edit_dialog.showNormal()
        self._index = index

    def _dialog_ok_cb(self):
        """called when the ok button is pressed on the edit dialog"""
        message = self._edit_dialog.command
        data = self._edit_dialog.data
        index = self._edit_dialog.index
        mode = self._edit_dialog.mode
        command_mode = self._edit_dialog.command_mode
        min_range = self._edit_dialog.min_range
        max_range = self._edit_dialog.max_range
        autorelease = self._edit_dialog._trigger_autorelease
        autorelease_delay = self._edit_dialog._pulse_delay

        input_item: OscInputItem = self.inputItemListModel.itemAt(index)
        input_item._message = message  # OSC command message as text
        input_item._message_data = data  # arguments as a list
        input_item.setMode(mode)
        input_item._command_mode = command_mode
        input_item._min_range = min_range
        input_item._max_range = max_range
        input_item._trigger_autorelease = autorelease
        input_item._autorelease_delay = autorelease_delay
        input_item._source_index = self._edit_dialog.source_index

        input_item._update()  # refresh other properties
        self.inputItemListView.update_item(index)

        el = gremlin.event_handler.EventListener()
        el.device_mapping_changed.emit(self._device_id)
        el.request_action_list_refresh.emit()  # ask action lists to refresh

    def _dialog_rejected_cb(self):
        index = self._edit_dialog.index
        self.inputItemListView.update_item(index)

    def _index_for_key(self, input_id):
        """returns the index of the selected input id"""
        mode = self.device_profile.modes[self.current_mode]
        sorted_keys = list(mode.config[InputType.OpenSoundControl].keys())
        return sorted_keys.index(input_id)

    def _create_change_cb(self, index):
        """Creates a callback handling content changes.

        :param index the index of the content being changed
        :return callback function redrawing changed content
        """
        return lambda: self.inputItemListView.redraw_index(index)

    def set_mode(self, mode):
        """changes the mode of the tab"""
        self.current_mode = mode
        self.device_profile.ensure_mode_exists(self.current_mode)
        self.inputItemListModel.mode = mode

        # self.inputItemListView.select_item(-1)
        if gremlin.shared_state.isDeviceTabActive(self.device_guid):
            self.inputItemListModel.refresh()
            self.selectInputItemIndex(self._last_selected_index)


@gremlin.singleton_decorator.SingletonDecorator
class InputOscClient(QtCore.QObject):
    """runtime client for OSC messages

    this is where inbound OSC messages are processed

    """

    def __init__(self):

        super().__init__()
        self._interface = None

        self._event_handler = gremlin.event_handler.EventHandler()
        self._event_listener = gremlin.event_handler.EventListener()

        self._event_listener.request_osc.connect(self._request_osc_state)
        self._event_listener.profile_start.connect(self._profile_start)
        self._event_listener.options_changed.connect(self._options_changed)
        self._osc_map = {}  # map of message keys to inputs
        self._started = False
        self._state_data = {}  # holds the state data from received messages
        self._autorelease_tracker = {}

    @QtCore.Slot()
    def _options_changed(self):

        config = gremlin.config.Configuration()
        osc_enabled = config.osc_enabled
        # if osc_enabled:
        #     self.start()
        # else:
        self.stop()  # force a restart if it was running
        if osc_enabled:
            # restart
            self.start()

    @QtCore.Slot()
    def _profile_start(self):
        """called on profile start

        ensure the OSC server is running if the profile has OSC items

        """
        import gremlin.execution_graph

        config = gremlin.config.Configuration()
        if not config.osc_enabled:
            return

        self.start()  # start if not started

        verbose = config.verbose_mode_osc
        # syslog = logging.getLogger("system")
        self._update_messages()

        if self._osc_map:
            if verbose:
                # dump the mappings to the log file
                syslog.info("OSC: Listening for commands:")

                for items in self._osc_map.values():
                    for input_item in items:
                        item_mode = "axis" if input_item.is_axis else "momentary"
                        syslog.info(f"\t{input_item.display_name}  key: [{input_item.message_key}] input mode: [{item_mode}]")

            if not self._started:
                if verbose:
                    syslog.info("OSC: Start")
                self.start()
            else:
                syslog.info("OSC: Running")
        else:
            syslog.info("OSC: no OSC mappings found - start skipped")

    @QtCore.Slot(bool)
    def _request_osc_state(self, state: bool):
        if state:
            self.start()
        else:
            self.stop()

    def registerInput(self, input_item):
        """registers an OSC input item"""

        input_id = input_item.input_id
        if isinstance(input_id, OscInputItem):
            if not self._started:
                # ensure OSC is listening
                self._start()

            message_key = input_id.message_key
            if message_key not in self._osc_map.keys():
                self._osc_map[message_key] = []

            if input_id not in self._osc_map[message_key]:
                self._osc_map[message_key].append(input_id)
            verbose = gremlin.config.Configuration().verbose_mode_osc
            if verbose:
                syslog.info(
                    f"OSC: register trigger on: {input_id.display_name} source index: {input_id.source_index} mode: {input_id.mode_string} key: {message_key}"
                )

    def unregisterInput(self, input_item):
        """unregisters an OSC input item"""
        # syslog = logging.getLogger("system")
        verbose = gremlin.config.Configuration().verbose_mode_osc
        if isinstance(input_item, OscInputItem):
            message_key = input_item.message_key
            if message_key in self._osc_map:
                if input_item in self._osc_map[message_key]:
                    self._osc_map[message_key].remove(input_item)
                    if verbose:
                        syslog.info(f"OSC: unregister trigger on: {input_item.display_name} mode: {input_item.mode_string} key: {message_key}")

    def start(self):
        """starts the client"""

        # build a list of messages configured for input
        config = gremlin.config.Configuration()
        if not config.osc_enabled:
            return

        # build a list of input items to OSC messages
        if self._started:
            return
        self._update_messages()
        self._start()

    def _start(self):
        from gremlin.ui.osc_device import OscInterface
        import gremlin.shared_state

        config = gremlin.config.Configuration()
        if not config.osc_enabled:
            return

        if self._started:
            return
        self._interface = OscInterface()
        self._interface.start()  # ensure started
        self._interface.osc_message.connect(self._handle_osc_message_received)

        self._verbose = gremlin.config.Configuration().verbose_mode_osc
        self._started = True

    def _update_messages(self):
        """refresh OSC message we're listening to"""
        self._osc_map = {}  # list of message keys
        profile = gremlin.shared_state.current_profile
        if profile:
            for device in profile.devices.values():
                if device.name and device.name.casefold() == "osc":
                    for mode in device.modes.values():
                        if InputType.OpenSoundControl in mode.config:
                            for input_item in mode.config[InputType.OpenSoundControl].values():
                                self.registerInput(input_item)

    def stop(self):
        """stops the client"""
        if self._started:
            self._interface.osc_message.disconnect(self._handle_osc_message_received)
            self._interface.stop()
            self._interface = None
        self._started = False

    @property
    def started(self) -> bool:
        """true if listening to OSC messages"""
        return self._started

    def getData(self, address: str):
        if self._started:
            if address in self._state_data:
                return self._state_data[address]
        return None

    def sendData(self, address: str, v1=None, v2=None):
        if self._started:
            self._interface.send(address, v1, v2)

    def _handle_osc_message_received(self, message, args):
        """called when an OSC message is received"""
        from gremlin.ui.osc_device import OscInputItem, OscDeviceTabWidget
        from gremlin.input_types import InputType

        # get the input items behind this message
        config = gremlin.config.Configuration()
        tracker = gremlin.ui.ui_common.DeviceWidgetTracker()
        current_mode = gremlin.shared_state.current_mode
        _cache = tracker.getCache(OscDeviceTabWidget.device_guid, current_mode, InputType.OpenSoundControl)
        command = OscInputItem.CommandMode.Message
        # look for the the message
        message_key = OscInputItem.toMessageKey(command, message, args)
        is_running = gremlin.shared_state.is_running
        input_type = InputType.OpenSoundControl
        verbose = gremlin.config.Configuration().verbose_mode_osc

        normalized_args = [gremlin.util.scale_to_range(value, source_min=0, source_max=1.0) for value in args] if args else []
        tokens = message.split(maxsplit=1)
        primary_message = tokens[0]
        hits = [key for key in self._osc_map if key == primary_message]
        for hit_key in hits:
            if message != hit_key:
                # params
                splits = hit_key.split()
                source_index = int(splits[1])
            else:
                source_index = 0

            if verbose:
                syslog.info(f"OSC: runtime: processing {message_key}  hit key: {hit_key}  source index: {source_index}")
            input_item: OscInputItem
            for input_item in self._osc_map[hit_key]:
                if input_item.source_index != source_index:
                    # incorrect source
                    continue

                is_axis = False
                input_item._axis_values = normalized_args
                index = source_index  # input_item.source_index # source index of the param
                raw_value = 0.0
                value = 0.0
                if args:
                    if index < len(args):
                        raw_value = args[input_item.source_index]
                        value = normalized_args[input_item.source_index]
                        if verbose:
                            syslog.info(f"OSC: source index: {input_item.source_index}  value: {raw_value:0.3f}")
                    else:
                        syslog.error(
                            f"OSC: command [{input_item.message}] : source index {index} specifies an invalid parameter index. Valid parameters received: {args}"
                        )
                        raw_value = args[0]
                        value = normalized_args[0]

                autorelease = False

                if input_item.mode == OscInputItem.InputMode.Axis:
                    # trigger an axis event
                    is_pressed = False
                    is_axis = True
                    # update the current axis value for the input

                    if len(args) == 0:
                        # axis mode always requires at least a value parameter
                        syslog.warning(
                            f"OSC: no parameters received on OSC message for input set in axis mode.  Check mode and parameters for OSC input message [{input_item.message}]"
                        )
                        continue

                    event = gremlin.event_handler.Event(
                        event_type=InputType.OpenSoundControl,
                        device_guid=OscDeviceTabWidget.device_guid,
                        override_input_type=InputType.JoystickAxis,
                        identifier=input_item,
                        is_pressed=False,
                        value=value,
                        raw_value=raw_value,
                        data=index,  # source index
                        is_virtual=True,  # indicate we are not a hardware input
                        is_axis=True,
                        extra_data={"input_item": input_item},
                        source = EventSourceType.OSC,
                    )

                    self._state_data[input_item.message_key] = normalized_args  # this can have multiple axis values returned

                    self._event_listener.osc_event.emit(event)

                    if not is_running:
                        self._event_listener.vjoy_output_event_ui.emit(event)
                        continue

                elif input_item.mode == OscInputItem.InputMode.OnChange:
                    if len(args) == 0:
                        # axis mode always requires at least a value parameter
                        syslog.warning(
                            f"OSC: no parameters received on OSC message for input set to change mode.  Check mode and parameters for OSC input message [{input_item.message}]"
                        )
                        continue
                    is_pressed = True
                    value = raw_value

                elif input_item.mode == OscInputItem.InputMode.Button:
                    # trigger a button press event
                    autorelease = input_item.autoRelease

                    if len(args) == 0:
                        is_pressed = True
                        if not autorelease:
                            if config.osc_no_arg_autorelease:
                                # automatic autorelease mode for buttons on input with no args
                                autorelease = True

                            else:
                                syslog.warning(
                                    f"Autorelease not set on OSC no param button.  Thay may cause no trigger.  Check mode for [{input_item.message}]"
                                )
                                autorelease = False

                    else:
                        # first argument is pressed if non zero
                        is_pressed = raw_value != 0.0  # for OSC pressed is any value except 0

                    value = 1 if is_pressed else 0

                    input_item.setButtonValue(is_pressed)

                    self._state_data[input_item.message_key] = is_pressed

                    if self._verbose:
                        syslog.info(
                            f"OSC: send event: is_pressed: {is_pressed} value: {value} raw value: {raw_value} is axis: {is_axis} mode: [{input_item.mode.name}]"
                        )

                    # button mode
                    event = gremlin.event_handler.Event(
                        event_type=input_type,
                        device_guid=OscDeviceTabWidget.device_guid,
                        override_input_type=InputType.JoystickButton,
                        identifier=input_item,
                        is_pressed=is_pressed,
                        value=value,
                        raw_value=raw_value,
                        data=index,  # source index
                        is_virtual=True,  # indicate we are not a hardware input
                        is_axis=is_axis,
                        extra_data={"input_item": input_item},
                        source=EventSourceType.OSC,
                    )

                    self._event_listener.osc_event.emit(event)
                    self._event_listener.joystick_event_ui.emit(event)

                    if not gremlin.shared_state.is_running:
                        # fire UI event to update the button
                        self._event_listener.vjoy_output_event_ui.emit(event)

                    if autorelease:
                        # schedule an autorelease event
                        input_item.autoRelease = True
                        delay = input_item.autorelease_delay / 1000  # ms to s
                        release_event = event.clone()
                        release_event.is_pressed = False
                        release_event.value = 0
                        timer = threading.Timer(delay, self._create_callback(input_item, release_event))
                        input_item.autorelease_timer = timer  # auto cancels the prior timer when the new value is set
                        timer.start()

        # grab any defined callbacks
        if is_running:
            callbacks = gremlin.input_devices.callback_registry.registry
            device_guid = gremlin.shared_state.osc_tab_guid
            current_mode = gremlin.shared_state.runtime_mode
            if device_guid in callbacks:
                if current_mode in callbacks[device_guid]:
                    for event in callbacks[device_guid][current_mode]:
                        input_item = event.identifier
                        if input_item.message == message:
                            index = input_item.source_index
                            if index < len(args):
                                raw_value = args[index]
                                value = normalized_args[index]
                                syslog.info(f"OSC: source index: {input_item.source_index}  value: {raw_value:0.3f}")
                            else:
                                syslog.error(
                                    f"OSC: command [{input_item.command}] : source index {index} specifies an invalid parameter index. Valid parameters received: {args}"
                                )
                                raw_value = args[0]
                                value = normalized_args[0]

                            event.value = raw_value
                            event.raw_value = raw_value
                            event.data = normalized_args

                            self._event_listener.osc_event.emit(event)

    def _create_callback(self, input_item, event):
        return lambda: self._autorelease_callback(input_item, event)

    def _autorelease_callback(self, input_item, event):
        """execute autorelease for an input"""
        self._event_listener.osc_event.emit(event)
        if not gremlin.shared_state.is_running:
            self._event_listener.joystick_event_ui.emit(event)


# listen to OSC input
osc_client = InputOscClient()
