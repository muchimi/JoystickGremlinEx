# -*- coding: utf-8; -*-

"""AFCS visual axis-flow designer and runtime."""

from __future__ import annotations

import logging

from shiboken6 import Shiboken

import gremlin.event_handler
import gremlin.shared_state
import gremlin.util
from gremlin.singleton_decorator import SingletonDecorator

from .designer import AfcsDesignerWidget
from .model import AfcsDocument
from .runtime import AfcsBus, AfcsRuntime

syslog = logging.getLogger("system")


@SingletonDecorator
class AfcsManager:
    """Owns the AFCS document, designer, bus, and runtime."""

    def __init__(self):
        self.document = AfcsDocument()
        self.bus = AfcsBus()
        self.runtime = AfcsRuntime(self.document, self.bus)
        self.designer: AfcsDesignerWidget | None = None
        self.output_configs: list = []
        self.runtime.output_configs = self.output_configs
        self._hooks = False
        self._bind_profile_hooks()
        self.document.load_for_profile()

    def register_output_config(self, config) -> None:
        if config is None or config in self.output_configs:
            return
        self.output_configs.append(config)

    def unregister_output_config(self, config) -> None:
        if config in self.output_configs:
            self.output_configs.remove(config)

    def _bind_profile_hooks(self):
        if self._hooks:
            return
        el = gremlin.event_handler.EventListener()
        el.profile_loaded.connect(self._on_profile_loaded)
        el.profile_unloaded.connect(self._on_profile_unloaded)
        el.profile_before_start.connect(self._on_profile_start)
        el.profile_start.connect(self._on_profile_start)
        el.profile_started.connect(self._on_profile_started)
        el.profile_stop.connect(self._on_profile_stop)
        el.tabs_loaded.connect(self._on_tabs_loaded)
        self._hooks = True

    def designer_widget(self, parent=None) -> AfcsDesignerWidget:
        widget = self.designer
        if widget is None or not Shiboken.isValid(widget) or getattr(widget, "_cleaned", False):
            self.designer = AfcsDesignerWidget(self, parent)
        return self.designer

    def enroll_axis(self, name: str, device_guid: str = "", device_name: str = "", axis_id: int = 0) -> None:
        running = bool(gremlin.shared_state.is_running)
        if not running and self.designer is not None and Shiboken.isValid(self.designer):
            try:
                self.designer._capture_graph()
            except Exception:
                pass
        self.document.ensure_enrollment(name, device_guid, device_name, axis_id)
        if running:
            return
        self.document.save_later()
        if self.designer is not None and Shiboken.isValid(self.designer):
            gremlin.util.InvokeUiMethod(self.designer.reload)

    def set_input(self, name: str, value: float) -> None:
        self.bus.set(name, value)

    def _on_profile_loaded(self):
        gremlin.util.InvokeUiMethod(self._on_profile_loaded_ui)

    def _on_profile_loaded_ui(self):
        self._flush()
        self.bus.clear()
        self.document.load_for_profile()
        if self.designer is not None and Shiboken.isValid(self.designer):
            self.designer.reload()

    def _on_profile_unloaded(self):
        gremlin.util.InvokeUiMethod(self._on_profile_unloaded_ui)

    def _on_profile_unloaded_ui(self):
        self._flush()
        self.runtime.stop()
        self.bus.clear()
        self.document.load_for_profile()
        if self.designer is not None and Shiboken.isValid(self.designer):
            self.designer.reload()

    def _on_tabs_loaded(self):
        gremlin.util.InvokeUiMethod(self._ensure_loaded)

    def _ensure_loaded(self):
        if not self.document.modes():
            self.document.load_for_profile()

    def _on_profile_start(self):
        gremlin.util.InvokeUiMethod(self._on_profile_start_ui)

    def _on_profile_start_ui(self):
        self.runtime.halt()
        if self.designer is not None and Shiboken.isValid(self.designer) and not getattr(self.designer, "_cleaned", False):
            self.designer.pause_live()

    def _on_profile_started(self):
        gremlin.util.InvokeUiMethod(self._on_profile_started_ui)

    def _on_profile_started_ui(self):
        self._flush()
        self.bus.clear()
        self.runtime.start(write_outputs=True)
        if (
            self.designer is not None
            and Shiboken.isValid(self.designer)
            and not getattr(self.designer, "_cleaned", False)
            and self.designer.isVisible()
        ):
            self.designer.resume_live()

    def _on_profile_stop(self):
        gremlin.util.InvokeUiMethod(self._on_profile_stop_ui)

    def _on_profile_stop_ui(self):
        self.runtime.stop()
        self.output_configs.clear()
        self.bus.clear()
        if (
            self.designer is not None
            and Shiboken.isValid(self.designer)
            and not getattr(self.designer, "_cleaned", False)
            and self.designer.isVisible()
        ):
            self.runtime.start_preview()
            self.designer.resume_live()
        self._flush()

    def _flush(self) -> bool:
        if not self.document.dirty:
            return True
        try:
            return bool(self.document.save_to_profile())
        except Exception as err:
            syslog.warning(f"AFCS: flush failed: {err}")
            return False


def persist_for_profile(profile, dest_xml: str | None = None) -> bool:
    try:
        if AfcsManager.instance is None:
            return False
        manager = AfcsManager()
        current = gremlin.shared_state.current_profile
        if current is not profile:
            return False
        return manager.document.save_to_profile(profile, dest_xml=dest_xml)
    except Exception as err:
        syslog.warning(f"AFCS: persist on profile save failed: {err}")
        return False
