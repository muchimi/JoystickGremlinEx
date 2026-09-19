# -*- coding: utf-8; -*-
#
# Live system counters for the overlay Counter widget (time, FPS, CPU, GPU, RAM, tally).
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import ctypes
import logging
import struct
import time
from ctypes import wintypes
from typing import Any

from gremlin.singleton_decorator import SingletonDecorator

syslog = logging.getLogger("system")

STAT_CHOICES = (
    ("time", "Current time"),
    ("time_s", "Current time (seconds)"),
    ("date", "Date"),
    ("fps", "FPS"),
    ("cpu", "CPU usage"),
    ("cpu_clock", "CPU clock"),
    ("cpu_temp", "CPU temperature"),
    ("ram", "Memory usage"),
    ("gpu", "GPU usage"),
    ("gpu_temp", "GPU temperature"),
    ("manual", "Manual counter"),
)

STAT_LABELS = {key: label for key, label in STAT_CHOICES}

_STAT_ALIASES = {
    "clock": "time",
    "clock_s": "time_s",
    "cpu_usage": "cpu",
    "cpu_freq": "cpu_clock",
    "frequency": "cpu_clock",
    "mhz": "cpu_clock",
    "memory": "ram",
    "temperature": "cpu_temp",
    "temp": "cpu_temp",
    "cpu_temperature": "cpu_temp",
    "gpu_usage": "gpu",
    "gpu_load": "gpu",
    "gpu_temperature": "gpu_temp",
    "overlay_fps": "fps",
    "count": "manual",
    "tally": "manual",
    "deaths": "manual",
}


def normalize_stat(value) -> str:
    key = str(value or "time").casefold().strip().replace(" ", "_").replace("-", "_")
    if key in STAT_LABELS:
        return key
    return _STAT_ALIASES.get(key, "time")


def stat_caption(key: str) -> str:
    kind = normalize_stat(key)
    if kind == "fps":
        return "FPS"
    if kind == "cpu_temp":
        return "CPU temp"
    if kind == "gpu_temp":
        return "GPU temp"
    if kind == "gpu":
        return "GPU"
    if kind == "manual":
        return "Count"
    return STAT_LABELS.get(kind, "Counter")


def _use_12h(style: dict[str, Any] | None) -> bool:
    value = str((style or {}).get("time_format") or "24h").casefold()
    return value in ("12h", "12", "ampm", "ap")


@SingletonDecorator
class SysStatsSampler:
    """Cached host metrics, sampled from the overlay 60 Hz poll."""

    def __init__(self):
        self._cpu_ready = False
        self._heavy_at = 0.0
        self._cpu = None
        self._cpu_mhz = None
        self._ram = None
        self._cpu_temp_c = None
        self._gpu_temp_c = None
        self._gpu_load = None
        self._fps = None
        self._cpu_temp_logged = False
        self._gpu_temp_logged = False
        self._gpu_load_logged = False
        self._fps_logged = False
        self._temp_retry_at = 0.0
        self._pdh = None
        self._nvml = None

    def tick(self):
        now = time.monotonic()
        if now - self._heavy_at >= 0.5:
            self._heavy_at = now
            self._sample_heavy()

    def format(self, key: str, style: dict[str, Any] | None = None) -> str:
        style = style or {}
        kind = normalize_stat(key)
        named = not bool(style.get("show_caption", True))
        if kind == "time":
            return time.strftime("%I:%M %p" if _use_12h(style) else "%H:%M").lstrip("0") or time.strftime("%H:%M")
        if kind == "time_s":
            if _use_12h(style):
                text = time.strftime("%I:%M:%S %p")
                return text.lstrip("0") or text
            return time.strftime("%H:%M:%S")
        if kind == "date":
            return time.strftime("%Y-%m-%d")
        if kind == "fps":
            if self._fps is None:
                return "FPS n/a" if named else "n/a"
            return f"{self._fps:.0f} FPS" if named else f"{self._fps:.0f}"
        if kind == "cpu":
            if self._cpu is None:
                return "CPU —" if named else "—"
            return f"{self._cpu:.0f} %" if not named else f"CPU {self._cpu:.0f} %"
        if kind == "cpu_clock":
            if self._cpu_mhz is None or self._cpu_mhz <= 0:
                return "CPU —" if named else "—"
            ghz = self._cpu_mhz / 1000.0
            clock = f"{ghz:.2f} GHz" if ghz >= 1.0 else f"{self._cpu_mhz:.0f} MHz"
            return f"CPU {clock}" if named else clock
        if kind == "ram":
            if self._ram is None:
                return "RAM —" if named else "—"
            return f"{self._ram:.0f} %" if not named else f"RAM {self._ram:.0f} %"
        if kind == "gpu":
            if self._gpu_load is None:
                return "GPU n/a" if named else "n/a"
            return f"{self._gpu_load:.0f} %" if not named else f"GPU {self._gpu_load:.0f} %"
        unit = str(style.get("temp_unit") or "C").casefold()
        if kind == "gpu_temp":
            return _format_temp(self._gpu_temp_c, unit, "GPU" if named else "")
        return _format_temp(self._cpu_temp_c, unit, "CPU" if named else "")

    def _sample_heavy(self):
        try:
            import psutil

            if not self._cpu_ready:
                psutil.cpu_percent(interval=None)
                self._cpu_ready = True
            else:
                self._cpu = float(psutil.cpu_percent(interval=None))
            freq = psutil.cpu_freq()
            if freq is not None and getattr(freq, "current", None):
                self._cpu_mhz = float(freq.current)
            mem = psutil.virtual_memory()
            self._ram = float(getattr(mem, "percent", 0.0) or 0.0)
            cpu_t, gpu_t = _psutil_temperatures(psutil)
            if cpu_t is not None:
                self._cpu_temp_c = cpu_t
            if gpu_t is not None:
                self._gpu_temp_c = gpu_t
        except Exception:
            pass

        now = time.monotonic()
        if now >= self._temp_retry_at:
            hw = _wmi_hardware()
            if hw.get("cpu_temp") is not None:
                self._cpu_temp_c = hw["cpu_temp"]
            if hw.get("gpu_temp") is not None:
                self._gpu_temp_c = hw["gpu_temp"]
            if hw.get("gpu_load") is not None:
                self._gpu_load = hw["gpu_load"]
            self._temp_retry_at = now + (2.0 if hw else 15.0)
            if self._cpu_temp_c is None and not self._cpu_temp_logged:
                self._cpu_temp_logged = True
                syslog.info("OBS OVERLAY: CPU temperature is not available on this system (shown as n/a).")
            if self._gpu_temp_c is None and not self._gpu_temp_logged:
                self._gpu_temp_logged = True
                syslog.info("OBS OVERLAY: GPU temperature is not available (Libre Hardware Monitor, NVIDIA NVML).")

        nvml = _nvml_gpu(self)
        if nvml.get("gpu_temp") is not None and self._gpu_temp_c is None:
            self._gpu_temp_c = nvml["gpu_temp"]
        if nvml.get("gpu_load") is not None:
            self._gpu_load = nvml["gpu_load"]

        pdh_load = _pdh_gpu_usage(self)
        if pdh_load is not None:
            self._gpu_load = pdh_load
        if self._gpu_load is None and not self._gpu_load_logged:
            self._gpu_load_logged = True
            syslog.info("OBS OVERLAY: GPU usage is not available (NVIDIA NVML, Windows GPU Engine, or Libre Hardware Monitor).")

        fps = _rtss_fps()
        self._fps = fps
        if fps is None and not self._fps_logged:
            self._fps_logged = True
            syslog.info(
                "OBS OVERLAY: FPS needs MSI Afterburner / RivaTuner Statistics Server (RTSS) running to read in-game frame rate."
            )


def _format_temp(celsius, unit: str, prefix: str) -> str:
    if celsius is None:
        return f"{prefix} n/a".strip() if prefix else "n/a"
    value = float(celsius)
    text = f"{value * 9.0 / 5.0 + 32.0:.0f} °F" if unit == "f" else f"{value:.0f} °C"
    return f"{prefix} {text}" if prefix else text


def _is_cpu_temp_name(name: str) -> bool:
    blob = name.casefold()
    if any(token in blob for token in ("gpu", "vram", "hotspot", "mem ")):
        return False
    return any(token in blob for token in ("cpu", "package", "tdie", "tctl", "core", "zen"))


def _is_gpu_temp_name(name: str) -> bool:
    blob = name.casefold()
    if "cpu" in blob:
        return False
    return any(token in blob for token in ("gpu", "graphics", "nvidia", "radeon", "geforce", "arc"))


def _is_gpu_load_name(name: str) -> bool:
    blob = name.casefold()
    if any(token in blob for token in ("memory", "vram", "fan", "power", "clock", "hotspot")):
        return False
    if "core" in blob and "gpu" in blob:
        return True
    return blob in ("gpu core", "gpu") or (blob.startswith("gpu") and "load" in blob) or blob.endswith("gpu")


def _psutil_temperatures(psutil_mod) -> tuple[float | None, float | None]:
    try:
        sensors = psutil_mod.sensors_temperatures() or {}
    except Exception:
        return None, None
    cpu_vals = []
    gpu_vals = []
    for chip, entries in sensors.items():
        chip_name = str(chip or "")
        for entry in entries or []:
            current = getattr(entry, "current", None)
            if current is None:
                continue
            try:
                value = float(current)
            except (TypeError, ValueError):
                continue
            label = f"{chip_name} {getattr(entry, 'label', '') or ''}"
            if _is_gpu_temp_name(label):
                gpu_vals.append(value)
            elif _is_cpu_temp_name(label) or _is_cpu_temp_name(chip_name):
                cpu_vals.append(value)
    cpu = sum(cpu_vals) / len(cpu_vals) if cpu_vals else None
    gpu = max(gpu_vals) if gpu_vals else None
    return cpu, gpu


def _wmi_hardware() -> dict[str, float | None]:
    result = {"cpu_temp": None, "gpu_temp": None, "gpu_load": None}
    try:
        import pythoncom
        from win32com.client import GetObject
    except Exception:
        return result
    pythoncom.CoInitialize()
    try:
        for namespace, cls, scale in (
            (r"winmgmts:\\.\root\LibreHardwareMonitor", "Sensor", "libre"),
            (r"winmgmts:\\.\root\OpenHardwareMonitor", "Sensor", "ohm"),
            (r"winmgmts:\\.\root\wmi", "MSAcpi_ThermalZoneTemperature", "acpi"),
        ):
            try:
                wmi = GetObject(namespace)
                instances = wmi.InstancesOf(cls)
            except Exception:
                continue
            cpu_temps = []
            gpu_temps = []
            gpu_loads = []
            for inst in instances:
                try:
                    if scale == "acpi":
                        raw = float(inst.CurrentTemperature)
                        cpu_temps.append(raw / 10.0 - 273.15)
                        continue
                    sensor_type = str(getattr(inst, "SensorType", "") or "").casefold()
                    name = str(getattr(inst, "Name", "") or "")
                    value = float(inst.Value)
                    if sensor_type == "temperature":
                        if _is_gpu_temp_name(name):
                            gpu_temps.append(value)
                        elif "gpu" not in name.casefold():
                            cpu_temps.append(value)
                    elif sensor_type == "load" and _is_gpu_load_name(name):
                        gpu_loads.append(value)
                except Exception:
                    continue
            if cpu_temps and result["cpu_temp"] is None:
                result["cpu_temp"] = sum(cpu_temps) / len(cpu_temps)
            if gpu_temps and result["gpu_temp"] is None:
                result["gpu_temp"] = max(gpu_temps)
            if gpu_loads and result["gpu_load"] is None:
                result["gpu_load"] = max(gpu_loads)
            if scale == "acpi":
                continue
            if result["cpu_temp"] is not None or result["gpu_temp"] is not None or result["gpu_load"] is not None:
                return result
    except Exception:
        return result
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
    return result


class _NvmlState:
    def __init__(self):
        self.ok = False
        self.lib = None
        self.devices = []


def _nvml_gpu(sampler: SysStatsSampler) -> dict[str, float | None]:
    result = {"gpu_temp": None, "gpu_load": None}
    state = sampler._nvml
    if state is None:
        state = _NvmlState()
        sampler._nvml = state
        try:
            lib = ctypes.WinDLL("nvml.dll")
            init = getattr(lib, "nvmlInit_v2", None) or getattr(lib, "nvmlInit", None)
            if init is None or int(init()) != 0:
                raise OSError("nvml init")
            count = ctypes.c_uint(0)
            get_count = getattr(lib, "nvmlDeviceGetCount_v2", None) or getattr(lib, "nvmlDeviceGetCount", None)
            if get_count is None or get_count(ctypes.byref(count)) != 0:
                raise OSError("nvml count")
            handles = []
            get_handle = getattr(lib, "nvmlDeviceGetHandleByIndex_v2", None) or getattr(lib, "nvmlDeviceGetHandleByIndex", None)
            for index in range(int(count.value)):
                handle = ctypes.c_void_p()
                if get_handle is not None and get_handle(index, ctypes.byref(handle)) == 0:
                    handles.append(handle)
            state.lib = lib
            state.devices = handles
            state.ok = bool(handles)
        except Exception:
            state.ok = False
    if not state.ok or not state.lib:
        return result
    temps = []
    loads = []

    class _Util(ctypes.Structure):
        _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

    for handle in state.devices:
        try:
            temp = ctypes.c_uint(0)
            if state.lib.nvmlDeviceGetTemperature(handle, 0, ctypes.byref(temp)) == 0:
                temps.append(float(temp.value))
            util = _Util()
            if state.lib.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(util)) == 0:
                loads.append(float(util.gpu))
        except Exception:
            continue
    if temps:
        result["gpu_temp"] = max(temps)
    if loads:
        result["gpu_load"] = max(loads)
    return result


class _PdhGpuState:
    def __init__(self):
        self.ok = False
        self.query = None
        self.counters = []
        self.primed = False


def _pdh_gpu_usage(sampler: SysStatsSampler) -> float | None:
    state = sampler._pdh
    if state is None:
        state = _PdhGpuState()
        sampler._pdh = state
        try:
            import win32pdh

            query = win32pdh.OpenQuery()
            counters = []
            try:
                paths = win32pdh.ExpandWildCardPath(r"\GPU Engine(*)\Utilization Percentage")
            except Exception:
                paths = []
            if not paths:
                try:
                    _items, instances = win32pdh.EnumObjectItems(None, None, "GPU Engine", -1)
                    paths = [rf"\GPU Engine({inst})\Utilization Percentage" for inst in instances or []]
                except Exception:
                    paths = []
            selected = [path for path in paths or [] if "engtype_3d" in str(path).casefold()] or list(paths or [])
            for path in selected:
                try:
                    counters.append(win32pdh.AddCounter(query, path))
                except Exception:
                    continue
            if not counters:
                win32pdh.CloseQuery(query)
                state.ok = False
                return None
            win32pdh.CollectQueryData(query)
            state.query = query
            state.counters = counters
            state.ok = True
            state.primed = False
        except Exception:
            state.ok = False
            return None
    if not state.ok:
        return None
    try:
        import win32pdh

        win32pdh.CollectQueryData(state.query)
        if not state.primed:
            state.primed = True
            return None
        values = []
        for counter in state.counters:
            try:
                _kind, value = win32pdh.GetFormattedCounterValue(counter, win32pdh.PDH_FMT_DOUBLE)
                values.append(float(value))
            except Exception:
                continue
        if not values:
            return None
        return max(0.0, min(100.0, max(values)))
    except Exception:
        return None


def _rtss_fps() -> float | None:
    mapping = None
    view = None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenFileMappingW.restype = wintypes.HANDLE
        kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.MapViewOfFile.restype = wintypes.LPVOID
        kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        kernel32.UnmapViewOfFile.argtypes = [wintypes.LPCVOID]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        FILE_MAP_READ = 0x0004
        mapping = kernel32.OpenFileMappingW(FILE_MAP_READ, False, "RTSSSharedMemoryV2")
        if not mapping:
            mapping = kernel32.OpenFileMappingW(FILE_MAP_READ, False, "Global\\RTSSSharedMemoryV2")
        if not mapping:
            return None
        view = kernel32.MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0)
        if not view:
            return None
        header = ctypes.string_at(view, 32)
        signature, version, entry_size, arr_offset, arr_size = struct.unpack_from("<IIIII", header, 0)
        if signature not in (0x52545353, 0x53535452) or entry_size < 284 or arr_size > 256:
            return None
        fg_pid = _foreground_pid()
        best = None
        fg = None
        for index in range(int(arr_size)):
            offset = int(arr_offset) + index * int(entry_size)
            entry = ctypes.string_at(view + offset, min(int(entry_size), 320))
            pid = struct.unpack_from("<I", entry, 0)[0]
            if not pid:
                continue
            fps = None
            if len(entry) >= 284:
                time0, time1, frames, frame_time = struct.unpack_from("<IIII", entry, 268)
                if frame_time and 0 < frame_time < 1_000_000_000:
                    candidate = 1_000_000.0 / float(frame_time)
                    if 1.0 <= candidate <= 1000.0:
                        fps = candidate
                if fps is None:
                    span = int(time1) - int(time0)
                    if span > 0 and frames:
                        candidate = float(frames) * 1000.0 / float(span)
                        if 1.0 <= candidate <= 1000.0:
                            fps = candidate
            if fps is None:
                continue
            if fg_pid and pid == fg_pid:
                fg = fps
            if best is None or fps > best:
                best = fps
        if fg is not None:
            return fg
        return best
    except Exception:
        return None
    finally:
        try:
            if view:
                ctypes.WinDLL("kernel32").UnmapViewOfFile(view)
        except Exception:
            pass
        try:
            if mapping:
                ctypes.WinDLL("kernel32").CloseHandle(mapping)
        except Exception:
            pass


def _foreground_pid() -> int:
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return 0
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


@SingletonDecorator
class ManualCounterTracker:
    """Edge-triggered increment / decrement / reset for Counter manual stats."""

    def __init__(self):
        self._state: dict[str, dict[str, Any]] = {}
        self._persist_dirty = False

    def retain(self, keys: set[str] | None):
        if not keys:
            self._state.clear()
            return
        for ident in list(self._state):
            if ident not in keys:
                self._state.pop(ident, None)

    def take_persist_dirty(self) -> bool:
        """True once since last call if any manual tally changed (for overlay save)."""
        dirty = self._persist_dirty
        self._persist_dirty = False
        return dirty

    def sample(self, item: dict[str, Any] | None, entry: dict[str, Any] | None) -> int:
        if not item or not entry:
            return 0
        widget_id = str(item.get("id") or "")
        entry_id = str(entry.get("id") or "")
        if not widget_id or not entry_id:
            return 0
        key = f"{widget_id}:{entry_id}"
        try:
            persisted = int(entry.get("value") or 0)
        except (TypeError, ValueError):
            persisted = 0
        try:
            step = max(1, int(entry.get("step") or 1))
        except (TypeError, ValueError):
            step = 1
        st = self._state.get(key)
        if st is None:
            st = {"inc": False, "dec": False, "reset": False, "value": persisted}
            self._state[key] = st
        current = int(st.get("value") or 0)
        before = current
        from .bindings import binding_is_configured, read_toggle_active

        reset_bind = entry.get("binding_z")
        if binding_is_configured(reset_bind):
            reset_on = bool(read_toggle_active(reset_bind))
            if reset_on and not st["reset"]:
                current = 0
            st["reset"] = reset_on
        else:
            st["reset"] = False

        inc_bind = entry.get("binding")
        if binding_is_configured(inc_bind):
            inc_on = bool(read_toggle_active(inc_bind))
            if inc_on and not st["inc"]:
                current += step
            st["inc"] = inc_on
        else:
            st["inc"] = False

        dec_bind = entry.get("binding_y")
        if binding_is_configured(dec_bind):
            dec_on = bool(read_toggle_active(dec_bind))
            if dec_on and not st["dec"]:
                current -= step
            st["dec"] = dec_on
        else:
            st["dec"] = False

        current = max(0, int(current))
        st["value"] = current
        entry["value"] = current
        for live in item.get("stats") or []:
            if isinstance(live, dict) and str(live.get("id") or "") == entry_id:
                live["value"] = current
                break
        if current != before:
            self._persist_dirty = True
        return current


def sample_counter_widget(item: dict[str, Any] | None) -> tuple:
    from .model import normalize_stat_series

    item = item or {}
    style = item.get("style") or {}
    sampler = SysStatsSampler()
    tracker = ManualCounterTracker()
    stats = item.get("stats")
    if not isinstance(stats, list) or not stats:
        stats = normalize_stat_series(stats, style.get("stat") or "time")
        item["stats"] = stats
    rows = []
    for entry in stats:
        if not isinstance(entry, dict):
            continue
        kind = normalize_stat(entry.get("stat"))
        if kind == "manual":
            text = str(tracker.sample(item, entry))
        else:
            text = sampler.format(kind, style)
        color = str(entry.get("color") or style.get("font_color") or "#f4efe4")
        caption = str(entry.get("label") or "").strip() or stat_caption(kind)
        rows.append((str(entry.get("id") or ""), text, color, caption))
    return tuple(rows)
