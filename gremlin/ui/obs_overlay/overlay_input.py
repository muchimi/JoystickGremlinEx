# -*- coding: utf-8; -*-
#
# Overlay HUD buttons as profile inputs (Stream Deck pattern).
# Events use InputType.OverlayButton; mapping UI uses JoystickButton override
# so ActionSelector / ContainerPlugins stay identical to a hardware button.

from __future__ import annotations

import logging
from typing import Any

from lxml import etree as ElementTree

import dinput
import gremlin.event_handler
import gremlin.input_item
import gremlin.joystick_handling
import gremlin.shared_state
from gremlin.input_types import InputType
from gremlin.types import DeviceCategory, DeviceType, EventSourceType
from gremlin.util import read_guid, safe_read

syslog = logging.getLogger("system")


def overlay_device_guid():
    return gremlin.shared_state.overlay_tab_guid


def _ensure_overlay_special_device():
    guid = overlay_device_guid()
    if gremlin.joystick_handling.getDevice(guid) is None:
        placeholder = dinput.DeviceSummary()
        placeholder.name = "Overlay"
        placeholder.device_guid = guid
        placeholder.device_type = DeviceType.Overlay
        placeholder.device_category = DeviceCategory.Special
        gremlin.joystick_handling.upsertSpecialDevice(placeholder)
    return guid


class OverlayInputItem(gremlin.input_item.InputItem):
    """Profile input for one overlay button widget."""

    def __init__(self, mode_object=None, device_guid=None):
        self._widget_id = ""
        self._title = ""
        if device_guid is None and mode_object is not None and getattr(mode_object, "parent", None) is not None:
            device_guid = getattr(mode_object.parent, "device_guid", None)
        if device_guid is None:
            device_guid = overlay_device_guid()
        _ensure_overlay_special_device()
        super().__init__(
            mode_object,
            InputType.OverlayButton,
            device_guid=device_guid,
            custom_input_id_handler=self._handle_input_id_callback,
            override_input_type=InputType.JoystickButton,
        )
        self.setInputIdCallback(self._handle_input_id_callback)
        self.setInputType(InputType.OverlayButton)
        self.setOverrideInputType(InputType.JoystickButton)
        self._is_button = True
        self.is_axis = False

    def _handle_input_id_callback(self):
        return self

    @property
    def message_key(self) -> str:
        return str(self._widget_id or "")

    @property
    def widget_id(self) -> str:
        return self._widget_id

    @widget_id.setter
    def widget_id(self, value: str):
        self._widget_id = str(value or "")

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, value: str):
        self._title = str(value or "")

    @property
    def display_name(self) -> str:
        title = (self._title or "").strip()
        if title:
            return f"Overlay · {title}"
        key = self._widget_id[:8] if self._widget_id else "?"
        return f"Overlay · Button {key}"

    def getDisplayName(self, full: bool = True) -> str:
        return self.display_name if full else (self._title or self._widget_id or "Overlay button")

    def parse_xml(self, node, data=None, extra_data=None):
        if node.tag not in ("input", "overlay"):
            return
        if node.get("guid"):
            self.setId(read_guid(node, "guid"))
        self._widget_id = safe_read(node, "widget-id", str, "")
        self._title = safe_read(node, "title", str, "")
        self.setOverrideInputType(InputType.JoystickButton)
        self._is_button = True

    def from_xml(self, node, data=None, extra_data=None):
        for child in node:
            if child.tag in ("input", "overlay"):
                self.parse_xml(child, data, extra_data)
        if node.tag in ("input", "overlay"):
            self.parse_xml(node, data, extra_data)
        parent = node.getparent()
        if parent is None or parent.tag not in ("mode", "gate", "states", "voices"):
            wrapper = ElementTree.Element("device")
            wrapper.set("type", "overlay")
            mode = ElementTree.SubElement(wrapper, "mode")
            mode.set("name", str(getattr(self, "profile_mode", None) or "Default"))
            mode.append(node)
        extra = dict(extra_data or {})
        extra.setdefault("input_item", self)
        extra.setdefault("input_type", InputType.OverlayButton)
        extra.setdefault("mode_object", getattr(self, "parent", None))
        super().from_xml(node, data, extra)
        self.setOverrideInputType(InputType.JoystickButton)
        self.setInputType(InputType.OverlayButton)

    def to_xml(self, parent_node=None):
        node = ElementTree.Element("overlay")
        node.set("guid", str(self.id))
        node.set("widget-id", self._widget_id or "")
        node.set("title", self._title or "")
        super().to_xml(node)
        return node

    def __hash__(self):
        key = self.message_key
        return hash(key) if key else hash(self.id)

    def __eq__(self, other):
        if isinstance(other, OverlayInputItem):
            return self.message_key == other.message_key
        if isinstance(other, str):
            return self.message_key == other
        return False


def _edit_mode() -> str | None:
    return gremlin.shared_state.edit_mode or gremlin.shared_state.current_mode


def _profile_mode_names() -> list[str]:
    names: list[str] = []
    profile = gremlin.shared_state.current_profile
    if profile is not None:
        try:
            raw = profile.get_modes() if hasattr(profile, "get_modes") else profile.mode_list()
            for mode in raw or []:
                name = mode if isinstance(mode, str) else str(getattr(mode, "name", "") or "")
                if name and name not in names:
                    names.append(name)
        except Exception:
            pass
    current = _edit_mode()
    if current and current not in names:
        names.insert(0, current)
    master = getattr(gremlin.shared_state, "master_mode", None)
    if master:
        names = [name for name in names if name != master]
    if not names:
        names = ["Default"]
    return names


def _mode_node(mode: str | None = None):
    profile = gremlin.shared_state.current_profile
    if not profile:
        return None
    mode = mode or _edit_mode() or next(iter(_profile_mode_names()), None)
    if not mode:
        return None
    guid = _ensure_overlay_special_device()
    device_node = profile.getDeviceNode(guid, autocreate=True)
    if device_node is None:
        return None
    device = gremlin.joystick_handling.getDevice(guid)
    if device is not None:
        device_node.device = device
        try:
            device.device_type = DeviceType.Overlay
        except Exception:
            pass
    return device_node.ensure_mode_exists(mode)


def find_overlay_input(widget_id: str, mode: str | None = None) -> OverlayInputItem | None:
    widget_id = str(widget_id or "")
    if not widget_id:
        return None
    if mode:
        return find_overlay_input_in_mode(widget_id, mode)
    mapped = None
    for name in _profile_mode_names():
        item = find_overlay_input_in_mode(widget_id, name)
        if item is None:
            continue
        if overlay_input_has_mappings(item):
            return item
        if mapped is None:
            mapped = item
    return mapped


def find_overlay_input_in_mode(widget_id: str, mode: str | None) -> OverlayInputItem | None:
    widget_id = str(widget_id or "")
    if not widget_id:
        return None
    mode_object = _mode_node(mode)
    if mode_object is None:
        return None
    config = mode_object.getConfig(InputType.OverlayButton) or {}
    item = config.get(widget_id)
    if isinstance(item, OverlayInputItem):
        return item
    for existing in config.values():
        if isinstance(existing, OverlayInputItem) and existing.widget_id == widget_id:
            return existing
    return None


def overlay_input_has_mappings(item: OverlayInputItem | None) -> bool:
    if item is None:
        return False
    try:
        if item.hasContainers:
            return True
    except Exception:
        pass
    return False


def _mapping_note_text(value) -> str:
    text = str(value or "").strip()
    return text if text else "-"


def _mapping_type_name(obj, fallback: str) -> str:
    name = str(getattr(obj, "name", None) or "").strip()
    return name or fallback


def overlay_mapping_summary_lines(item: OverlayInputItem | None) -> list[str]:
    if item is None or not overlay_input_has_mappings(item):
        return ["No bindings"]
    description = str(getattr(item, "_description", None) or "").strip()
    lines = [f"Description: {description if description else '-'}"]
    try:
        containers = list(item.containers)
    except Exception:
        return lines
    for container in containers:
        actions = []
        try:
            for action_set in container.action_sets or []:
                if not action_set:
                    continue
                for action in action_set:
                    if action is not None:
                        actions.append(action)
        except Exception:
            actions = []
        lines.append(
            f"{_mapping_type_name(container, 'Container')}, Notes: {_mapping_note_text(getattr(container, 'comment', None))}"
        )
        for action in actions:
            lines.append(
                f"{_mapping_type_name(action, 'Action')}, Notes: {_mapping_note_text(getattr(action, 'comment', None))}"
            )
    return lines


def overlay_mapping_summary(item: OverlayInputItem | None) -> str:
    return "\n".join(overlay_mapping_summary_lines(item))


def dump_overlay_mapping_xml(item: OverlayInputItem | None) -> str:
    if item is None or not overlay_input_has_mappings(item):
        return ""
    try:
        node = item.to_xml()
        if node is None:
            return ""
        return ElementTree.tostring(node, encoding="unicode")
    except Exception as err:
        syslog.error(f"OBS OVERLAY: mapping xml dump failed: {err}")
        return ""


def write_widget_mapping_xml(
    widget: dict[str, Any] | None,
    item: OverlayInputItem | None = None,
    *,
    persist_empty: bool = False,
):
    if not isinstance(widget, dict):
        return
    widget_id = str(widget.get("id") or "")
    live = item if item is not None else find_overlay_input(widget_id)
    xml = dump_overlay_mapping_xml(live)
    if xml:
        widget["mapping_xml"] = xml
    elif persist_empty:
        widget.pop("mapping_xml", None)


def _mapping_xml_root(fragment):
    if fragment.tag in ("overlay", "input"):
        return fragment
    for child in fragment.iter():
        if child.tag in ("overlay", "input"):
            return child
    return fragment


def _load_mapping_containers(item: OverlayInputItem, xml_text: str) -> bool:
    import gremlin.plugin_manager

    fragment = _mapping_xml_root(ElementTree.fromstring(xml_text))
    if fragment.tag not in ("overlay", "input"):
        syslog.warning("OBS OVERLAY: mapping xml is not an overlay node")
        return False
    extra = {
        "input_type": InputType.OverlayButton,
        "input_item": item,
        "mode_object": getattr(item, "parent", None),
    }
    item.from_xml(fragment, item, extra)
    if overlay_input_has_mappings(item):
        item.setOverrideInputType(InputType.JoystickButton)
        item.setInputType(InputType.OverlayButton)
        return True
    plugin_manager = gremlin.plugin_manager.ContainerPlugins()
    item.containers.clear()
    extra = {"input_type": InputType.JoystickButton, "input_item": item}
    for child in list(fragment) + list(fragment.iter("container")):
        if child.tag != "container":
            continue
        tag = child.get("type")
        if tag not in plugin_manager.tag_map:
            continue
        new_container = plugin_manager.tag_map[tag](item, extra_data=extra)
        new_container.from_xml(child, item, extra)
        item.containers.addContainer(new_container)
    item.setOverrideInputType(InputType.JoystickButton)
    item.setInputType(InputType.OverlayButton)
    ok = overlay_input_has_mappings(item)
    if not ok:
        syslog.warning(f"OBS OVERLAY: mapping xml parsed with no containers ({item.widget_id})")
    return ok


def apply_overlay_mapping_xml(widget_id: str, title: str, xml_text: str) -> OverlayInputItem | None:
    text = str(xml_text or "").strip()
    if not text:
        remove_overlay_input(widget_id)
        return None
    loaded = None
    for mode in _profile_mode_names():
        item = ensure_overlay_input(widget_id, title, mode)
        if item is None:
            continue
        try:
            if _load_mapping_containers(item, text):
                loaded = item
        except Exception as err:
            syslog.error(f"OBS OVERLAY: mapping xml load failed ({mode}): {err}")
    return loaded


def write_ocr_rule_mapping_xml(
    widget: dict[str, Any] | None,
    rule: dict[str, Any] | None,
    item: OverlayInputItem | None = None,
    *,
    persist_empty: bool = False,
):
    """Persist mapping XML onto an OCR rule (same pattern as button widgets)."""
    if not isinstance(widget, dict) or not isinstance(rule, dict):
        return
    from .model import ocr_rule_input_id

    input_id = ocr_rule_input_id(str(widget.get("id") or ""), str(rule.get("id") or ""))
    live = item if item is not None else find_overlay_input(input_id)
    xml = dump_overlay_mapping_xml(live)
    if xml:
        rule["mapping_xml"] = xml
    elif persist_empty:
        rule.pop("mapping_xml", None)


def sync_overlay_mappings_to_widgets(scene) -> None:
    if scene is None:
        return
    from .model import normalize_ocr_rules

    for page in getattr(scene, "pages", None) or []:
        for widget in page.get("widgets") or []:
            if widget.get("type") == "button":
                write_widget_mapping_xml(widget)
            elif widget.get("type") == "ocr":
                live = []
                for rule in normalize_ocr_rules(widget.get("ocr_rules")):
                    write_ocr_rule_mapping_xml(widget, rule)
                    live.append(rule)
                if live:
                    widget["ocr_rules"] = live


def restore_overlay_mappings_from_widgets(scene) -> None:
    if scene is None or not gremlin.shared_state.current_profile:
        return
    from .model import normalize_ocr_rules, ocr_rule_input_id, widget_display_name

    for page in getattr(scene, "pages", None) or []:
        for widget in page.get("widgets") or []:
            if widget.get("type") == "button":
                xml = widget.get("mapping_xml")
                widget_id = str(widget.get("id") or "")
                if xml:
                    apply_overlay_mapping_xml(widget_id, widget_display_name(widget), str(xml))
                else:
                    remove_overlay_input(widget_id)
            elif widget.get("type") == "ocr":
                widget_id = str(widget.get("id") or "")
                for rule in normalize_ocr_rules(widget.get("ocr_rules")):
                    rule_id = str(rule.get("id") or "")
                    input_id = ocr_rule_input_id(widget_id, rule_id)
                    title = f"OCR · {rule.get('name') or rule.get('display_name') or 'Rule'}"
                    xml = rule.get("mapping_xml")
                    if xml:
                        apply_overlay_mapping_xml(input_id, title, str(xml))
                    else:
                        remove_overlay_input(input_id)

def ensure_overlay_input(widget_id: str, title: str = "", mode: str | None = None) -> OverlayInputItem | None:
    widget_id = str(widget_id or "")
    if not widget_id:
        return None
    profile = gremlin.shared_state.current_profile
    if not profile:
        return None
    mode_object = _mode_node(mode)
    if mode_object is None:
        return None
    existing = find_overlay_input_in_mode(widget_id, mode)
    if existing is not None:
        if title:
            existing.title = title
        return existing
    guid = overlay_device_guid()
    item = OverlayInputItem(mode_object=mode_object, device_guid=guid)
    item.widget_id = widget_id
    item.title = title or ""
    mode_object.addInputItem(item)
    try:
        profile.registry.registerInputItem(item)
    except Exception:
        pass
    return item


def remove_overlay_input(widget_id: str, mode: str | None = None):
    widget_id = str(widget_id or "")
    if not widget_id:
        return
    profile = gremlin.shared_state.current_profile
    if profile is None:
        return
    modes = [mode] if mode else _profile_mode_names()
    for name in modes:
        item = find_overlay_input_in_mode(widget_id, name)
        if item is None:
            continue
        try:
            profile.registry.removeInputItem(item)
        except Exception:
            pass
        try:
            mode_object = item.parent
            if mode_object is not None:
                mode_object.delete_data(InputType.OverlayButton, item)
        except Exception:
            pass


def copy_overlay_mappings(source_widget_id: str, dest_widget_id: str, dest_title: str = ""):
    src = find_overlay_input(source_widget_id)
    dest = ensure_overlay_input(dest_widget_id, dest_title)
    if src is None or dest is None:
        return dest
    try:
        import gremlin.plugin_manager

        plugin_manager = gremlin.plugin_manager.ContainerPlugins()
        dest.containers.clear()
        for container in list(src.containers):
            node = container.to_xml()
            if node is None:
                continue
            tag = node.get("type") or getattr(container, "tag", None)
            if tag not in plugin_manager.tag_map:
                continue
            new_container = plugin_manager.tag_map[tag](dest)
            extra = {"input_type": InputType.JoystickButton}
            new_container.from_xml(node, dest, extra)
            dest.containers.addContainer(new_container)
    except Exception as err:
        syslog.error(f"OBS OVERLAY: copy mappings failed: {err}")
    try:
        from gremlin.ui.obs_overlay import OverlayManager

        dest_widget = OverlayManager().scene.widget_by_id(dest_widget_id)
        write_widget_mapping_xml(dest_widget, dest)
    except Exception:
        pass
    return dest


def emit_overlay_button_event(
    input_item: OverlayInputItem,
    is_pressed: bool,
    *,
    extra_data: dict[str, Any] | None = None,
) -> bool:
    if input_item is None:
        return False
    payload = {"input_item": input_item}
    if isinstance(extra_data, dict):
        payload.update(extra_data)
    event = gremlin.event_handler.Event(
        InputType.OverlayButton,
        input_item,
        overlay_device_guid(),
        is_pressed=is_pressed,
        value=1.0 if is_pressed else 0.0,
        raw_value=1.0 if is_pressed else 0.0,
        override_input_type=InputType.JoystickButton,
        extra_data=payload,
    )
    event.source = EventSourceType.Overlay
    el = gremlin.event_handler.EventListener()
    try:
        el.overlay_event.emit(event)
    except Exception:
        pass
    try:
        el.joystick_event_ui.emit(event)
    except Exception:
        pass
    if not gremlin.shared_state.is_running:
        try:
            el.joystick_event.emit(event)
        except Exception:
            pass
    return True


def emit_overlay_widget_button(widget: dict[str, Any] | None, is_pressed: bool) -> bool:
    if not widget:
        return False
    widget_id = str(widget.get("id") or "")
    from .model import widget_display_name

    item = find_overlay_input(widget_id) or ensure_overlay_input(widget_id, widget_display_name(widget))
    if item is None or not overlay_input_has_mappings(item):
        return False
    return emit_overlay_button_event(item, is_pressed)


def _event_button_id(event) -> int | None:
    ident = getattr(event, "identifier", None)
    if isinstance(ident, bool):
        return None
    if isinstance(ident, int):
        return ident
    try:
        return int(ident)
    except (TypeError, ValueError):
        return None


class OverlayLookForwarder:
    """While the profile runs, Follow-input look sources fire overlay Map… actions."""

    def __init__(self):
        self._hooked = False
        self._last: dict[str, bool] = {}
        self._forwarding = False

    def start(self):
        return

    def stop(self):
        if not self._hooked:
            return
        el = gremlin.event_handler.EventListener()
        for signal, slot in (
            (el.joystick_event, self._on_joystick),
            (el.vjoy_output_event, self._on_vjoy),
            (el.state_event, self._on_state),
            (el.runtime_mode_changed, self._on_mode),
            (el.keyboard_event, self._on_keyboard),
        ):
            try:
                signal.disconnect(slot)
            except Exception:
                pass
        self._hooked = False
        self._last.clear()

    def _follow_buttons(self):
        from .model import button_appearance_mode

        try:
            from gremlin.ui.obs_overlay import OverlayManager

            pages = OverlayManager().scene.pages or []
        except Exception:
            return
        for page in pages:
            for widget in page.get("widgets") or []:
                if widget.get("type") == "button" and button_appearance_mode(widget) == "follow":
                    yield widget

    def _fire(self, widget: dict[str, Any], pressed: bool):
        if bool(widget.get("binding", {}).get("invert")):
            pressed = not pressed
        widget_id = str(widget.get("id") or "")
        if widget_id and self._last.get(widget_id) is pressed:
            return
        if self._forwarding:
            return
        self._forwarding = True
        try:
            if emit_overlay_widget_button(widget, pressed) and widget_id:
                self._last[widget_id] = pressed
        finally:
            self._forwarding = False

    def _on_joystick(self, event):
        if self._forwarding or not gremlin.shared_state.is_running:
            return
        if getattr(event, "event_type", None) != InputType.JoystickButton:
            return
        if getattr(event, "source", None) == EventSourceType.Overlay:
            return
        from .bindings import binding_source
        from gremlin.util import compare_guid

        bid = _event_button_id(event)
        if bid is None:
            return
        pressed = bool(getattr(event, "is_pressed", False))
        for widget in self._follow_buttons():
            binding = widget.get("binding") or {}
            source = binding_source(binding)
            want = int(binding.get("input_id") or 0)
            if want <= 0 or bid != want:
                continue
            if source == "physical":
                if compare_guid(event.device_guid, binding.get("device_guid")):
                    self._fire(widget, pressed)
            elif source == "vjoy":
                vjoy_id = int(binding.get("vjoy_id") or 0)
                guid = binding.get("device_guid")
                if guid and compare_guid(event.device_guid, guid):
                    self._fire(widget, pressed)
                elif vjoy_id:
                    try:
                        vguid = gremlin.joystick_handling.vjoy_guid_from_id(vjoy_id)
                    except Exception:
                        vguid = None
                    if vguid is not None and compare_guid(event.device_guid, vguid):
                        self._fire(widget, pressed)

    def _on_vjoy(self, event):
        if self._forwarding or not gremlin.shared_state.is_running:
            return
        if getattr(event, "input_type", None) != InputType.JoystickButton:
            return
        from .bindings import binding_source

        vjoy_id = int(getattr(event, "vjoy_id", 0) or 0)
        bid = int(getattr(event, "input_id", 0) or 0)
        pressed = bool(getattr(event, "value", False))
        for widget in self._follow_buttons():
            binding = widget.get("binding") or {}
            if binding_source(binding) != "vjoy":
                continue
            if int(binding.get("vjoy_id") or 0) != vjoy_id:
                continue
            if int(binding.get("input_id") or 0) != bid:
                continue
            self._fire(widget, pressed)

    def _on_state(self, event):
        if self._forwarding or not gremlin.shared_state.is_running:
            return
        from .bindings import binding_source, resolve_overlay_state

        ident = getattr(event, "identifier", None)
        key = getattr(ident, "key", None) if ident is not None and not isinstance(ident, str) else ident
        key = str(key or "").strip()
        pressed = bool(getattr(event, "is_pressed", getattr(event, "value", False)))
        for widget in self._follow_buttons():
            binding = widget.get("binding") or {}
            if binding_source(binding) != "state":
                continue
            state = resolve_overlay_state(binding)
            name = str(getattr(state, "key", None) or binding.get("state_name") or "").strip()
            if name and name == key:
                self._fire(widget, pressed)

    def _on_mode(self, new_mode: str):
        if self._forwarding or not gremlin.shared_state.is_running:
            return
        from .bindings import binding_source, resolve_overlay_mode

        current = str(new_mode or "").strip()
        for widget in self._follow_buttons():
            binding = widget.get("binding") or {}
            if binding_source(binding) != "mode":
                continue
            _mid, name = resolve_overlay_mode(binding.get("mode_id"), binding.get("mode_name"))
            self._fire(widget, bool(name) and current == name)

    def _on_keyboard(self, event):
        if self._forwarding or not gremlin.shared_state.is_running:
            return
        from .bindings import binding_source, read_button

        for widget in self._follow_buttons():
            binding = widget.get("binding") or {}
            if binding_source(binding) != "keyboard":
                continue
            self._fire(widget, bool(read_button(binding)))


_look_forwarder = OverlayLookForwarder()


def start_look_forwarder():
    _look_forwarder.start()


def stop_look_forwarder():
    _look_forwarder.stop()
