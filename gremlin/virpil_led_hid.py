# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# Direct HID feature-report path for Virpil device LEDs.
# Protocol based on community documentation (charliefoxtwo / Virpil Communicator),
# firmware era ~20210102+. Sending raw HID data is at-your-own-risk.

from __future__ import annotations

import logging
import threading

from gremlin.singleton_decorator import SingletonDecorator

# Ensure hidapi.dll is loaded before importing hid (same as gremlin.hid)
import gremlin.hid  # noqa: F401
import hid

syslog = logging.getLogger("system")

VIRPIL_VENDOR_ID = 0x3344

# Board type bytes for feature reports
BOARD_DEFAULT = 0x64
BOARD_ADD = 0x65
BOARD_ONBOARD = 0x66
BOARD_SLAVE = 0x67
BOARD_EXTRA = 0x68

REPORT_ID = 0x02
REPORT_SIZE = 38
REPORT_TERMINATOR = 0xF0


def _channel_to_2bit(value: int) -> int:
    """Map 0..255 channel to Virpil 2-bit intensity (00/01/10/11)."""
    if value <= 0:
        return 0
    if value <= 76:
        return 1  # ~25% (tool 40)
    if value <= 153:
        return 2  # ~50% (tool 80)
    return 3  # 100% (tool FF)


def pack_color_byte(r: int, g: int, b: int) -> int:
    """Pack RGB into Virpil color byte: 10 bb gg rr."""
    rr = _channel_to_2bit(r)
    gg = _channel_to_2bit(g)
    bb = _channel_to_2bit(b)
    return 0x80 | (bb << 4) | (gg << 2) | rr


def tool_led_id_to_board_and_index(tool_led_id: int) -> tuple[int, int] | None:
    """
    Convert VPC_LED_Control dropdown command IDs to HID board + local LED index.

    Tool IDs:
      1-20  = On-board #01-#20
      21-40 = Slave1 #01-#20
    """
    if 1 <= tool_led_id <= 20:
        return BOARD_ONBOARD, tool_led_id
    if 21 <= tool_led_id <= 40:
        return BOARD_SLAVE, tool_led_id - 20
    return None


def board_command(board: int, local_led: int) -> int | None:
    """HID command byte for a board-local LED index (1-based)."""
    if local_led < 1:
        return None
    if board == BOARD_ADD:
        if local_led > 4:
            return None
        return local_led  # 0x01-0x04
    if board == BOARD_ONBOARD:
        if local_led > 20:
            return None
        return local_led + 0x04  # 0x05-0x18
    if board == BOARD_SLAVE:
        if local_led > 20:
            return None
        return local_led + 0x18  # 0x19-0x2C
    if board == BOARD_EXTRA:
        if local_led > 10:
            return None
        return local_led + 0x2C  # 0x2D-0x36
    if board == BOARD_DEFAULT:
        return 0x00
    return None


def build_feature_report(board: int, local_led: int, r: int, g: int, b: int) -> bytes | None:
    """Build the 38-byte Virpil LED feature report."""
    command = board_command(board, local_led)
    if command is None:
        return None
    color_index = local_led + 4
    if color_index < 0 or color_index >= REPORT_SIZE - 1:
        return None

    data = [0] * REPORT_SIZE
    data[0] = REPORT_ID
    data[1] = board & 0xFF
    data[2] = command & 0xFF
    data[color_index] = pack_color_byte(r, g, b) & 0xFF
    data[REPORT_SIZE - 1] = REPORT_TERMINATOR
    return bytes(data)


@SingletonDecorator
class VirpilLedHid:
    """Keeps Virpil HID devices open and sends LED feature reports."""

    def __init__(self):
        self._lock = threading.RLock()
        # key: (vid, pid) -> hid.Device
        self._devices: dict[tuple[int, int], hid.Device] = {}
        # paths that failed recently — avoid hammering logs
        self._fail_logged: set[tuple[int, int]] = set()

    def close_all(self):
        """Close all open HID handles (e.g. on profile stop)."""
        with self._lock:
            for key, device in list(self._devices.items()):
                try:
                    device.close()
                except Exception:
                    pass
                self._devices.pop(key, None)
            self._fail_logged.clear()

    def close_device(self, vid: int, pid: int):
        with self._lock:
            key = (int(vid), int(pid))
            device = self._devices.pop(key, None)
            if device is not None:
                try:
                    device.close()
                except Exception:
                    pass

    def _candidate_paths(self, vid: int, pid: int) -> list[bytes]:
        """Return HID device paths for vid/pid (vendor interface preferred)."""
        entries: list[tuple[int, bytes]] = []
        try:
            for info in hid.enumerate(vid, pid):
                path = info.get("path")
                if not path:
                    continue
                # Prefer vendor usage page (0xFF00) used for Virpil LED feature reports
                usage_page = int(info.get("usage_page") or 0)
                priority = 0 if usage_page == 0xFF00 else 1
                entries.append((priority, path))
        except Exception as exc:
            syslog.warning(f"VIRPIL HID: enumerate failed for {vid:04X}:{pid:04X}: {exc}")

        entries.sort(key=lambda item: item[0])
        paths: list[bytes] = []
        for _, path in entries:
            if path not in paths:
                paths.append(path)
        return paths

    def _open_device(self, vid: int, pid: int) -> hid.Device | None:
        """Open the first HID interface that can be opened for vid/pid."""
        vid = int(vid)
        pid = int(pid)
        paths = self._candidate_paths(vid, pid)
        last_error = None

        if not paths:
            try:
                device = hid.Device(vid, pid)
                device.nonblocking = 1
                return device
            except Exception as exc:
                syslog.warning(f"VIRPIL HID: open failed for {vid:04X}:{pid:04X}: {exc}")
                return None

        for path in paths:
            try:
                device = hid.Device(path=path)
                device.nonblocking = 1
                return device
            except Exception as exc:
                last_error = exc
                continue

        if last_error is not None:
            syslog.warning(f"VIRPIL HID: open failed for {vid:04X}:{pid:04X}: {last_error}")
        return None

    def _try_send_on_paths(self, vid: int, pid: int, report: bytes) -> bool:
        """Try feature report on each HID interface until one accepts it."""
        vid = int(vid)
        pid = int(pid)
        key = (vid, pid)
        paths = self._candidate_paths(vid, pid)
        if not paths:
            paths = [None]  # vid/pid open

        last_error = None
        for path in paths:
            device = None
            try:
                if path is None:
                    device = hid.Device(vid, pid)
                else:
                    device = hid.Device(path=path)
                device.nonblocking = 1
                device.send_feature_report(report)
                self._devices[key] = device
                self._fail_logged.discard(key)
                syslog.info(f"VIRPIL HID: opened device {vid:04X}:{pid:04X}")
                return True
            except Exception as exc:
                last_error = exc
                if device is not None:
                    try:
                        device.close()
                    except Exception:
                        pass
                continue

        if last_error is not None and key not in self._fail_logged:
            syslog.warning(f"VIRPIL HID: send_feature_report failed for {vid:04X}:{pid:04X}: {last_error}")
            self._fail_logged.add(key)
        return False

    def _get_device(self, vid: int, pid: int) -> hid.Device | None:
        key = (int(vid), int(pid))
        device = self._devices.get(key)
        if device is not None:
            return device
        device = self._open_device(vid, pid)
        if device is not None:
            self._devices[key] = device
            self._fail_logged.discard(key)
            syslog.info(f"VIRPIL HID: opened device {vid:04X}:{pid:04X}")
        return device

    def set_led(self, vid: int, pid: int, tool_led_id: int, r: int, g: int, b: int) -> bool:
        """
        Set one LED via HID feature report.

        :param tool_led_id: VPC_LED_Control dropdown command number (1-40 typical)
        :returns: True if the feature report was sent successfully
        """
        mapping = tool_led_id_to_board_and_index(int(tool_led_id))
        if mapping is None:
            return False
        board, local_led = mapping
        report = build_feature_report(board, local_led, int(r), int(g), int(b))
        if report is None:
            return False

        key = (int(vid), int(pid))
        with self._lock:
            device = self._devices.get(key)
            if device is not None:
                try:
                    device.send_feature_report(report)
                    return True
                except Exception as exc:
                    try:
                        device.close()
                    except Exception:
                        pass
                    self._devices.pop(key, None)
                    if key not in self._fail_logged:
                        syslog.warning(
                            f"VIRPIL HID: send failed for {vid:04X}:{pid:04X} led={tool_led_id}: {exc}; retrying interfaces"
                        )

            return self._try_send_on_paths(vid, pid, report)