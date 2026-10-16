# -*- coding: utf-8; -*-
#
# OCR rule pack import/export and built-in SC mineables / intelligence / EFB loaders.
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from .model import (
    default_ocr_rule,
    normalize_ocr_base,
    normalize_ocr_capture,
    normalize_ocr_match,
    normalize_ocr_rules,
    ocr_rule_input_id,
    overlay_variable_name,
    split_ocr_texts,
)

syslog = logging.getLogger("system")

PACK_SCHEMA = "jgex-ocr-pack/1"

PACK_KINDS = ("static", "citizen_lookup", "image_map")


def _packs_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    # Prefer repo data/ocr_packs next to project root.
    candidates = [
        os.path.join(here, "packs"),
        os.path.normpath(os.path.join(here, "..", "..", "..", "data", "ocr_packs")),
        os.path.normpath(os.path.join(here, "..", "..", "..", "..", "data", "ocr_packs")),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    # Create under package packs/ as fallback.
    dest = os.path.join(here, "packs")
    try:
        os.makedirs(dest, exist_ok=True)
    except Exception:
        pass
    return dest


def normalize_pack_kind(value) -> str:
    raw = str(value or "static").strip().casefold()
    if raw in ("citizen", "citizen_lookup", "rsi", "sc_intelligence", "intelligence"):
        return "citizen_lookup"
    if raw in ("image_map", "image", "efb", "chart", "charts"):
        return "image_map"
    return "static"


def _normalize_variables_list(raw, fallback_single: dict | None = None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    rows = raw if isinstance(raw, list) else []
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        name = overlay_variable_name(entry.get("name"))
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        out.append({"name": name, "default": str(entry.get("default") or "")})
    if not out and isinstance(fallback_single, dict):
        name = overlay_variable_name(fallback_single.get("name") or "rock")
        if name:
            out.append({"name": name, "default": str(fallback_single.get("default") or "")})
    return out


def _norm_location_text(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", str(text or "")).strip()


def _slug_for_location(name: str) -> str:
    import re

    raw = _norm_location_text(name)
    raw = re.sub(r"/IAP\b", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"[^\w\s\-]", "", raw)
    raw = re.sub(r"\s+", "-", raw.strip()).casefold()
    return raw.strip("-") or "location"


def _normalize_efb_location(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    import re

    if not isinstance(entry, dict):
        return None
    name = _norm_location_text(entry.get("name") or entry.get("display_name") or "")
    if not name:
        return None
    texts = []
    raw_texts = entry.get("texts") if "texts" in entry else entry.get("text")
    if isinstance(raw_texts, (list, tuple)):
        texts = [_norm_location_text(t) for t in raw_texts if _norm_location_text(t)]
    elif raw_texts:
        for part in re.split(r"[\n;]+", str(raw_texts)):
            part = _norm_location_text(part)
            if part:
                texts.append(part)
    if name not in texts:
        texts.insert(0, name)
    sid = _slug_for_location(name)
    chart_id = _norm_location_text(entry.get("chart_id") or "") or sid
    page_url = _norm_location_text(entry.get("page_url") or "")
    chart_url = _norm_location_text(entry.get("chart_url") or "")
    path_tail = page_url.rstrip("/").rsplit("/", 1)[-1].casefold() if page_url else ""
    if not chart_id or len(chart_id) <= 1 or chart_id.casefold() in ("s", "location", "w"):
        chart_id = sid
    if not page_url or len(path_tail) <= 1 or path_tail in ("s", "location", "w"):
        page_url = f"https://www.deltaconsultingsc.com/{sid}"
    return {
        "name": name,
        "texts": texts,
        "chart_id": chart_id,
        "page_url": page_url,
        "chart_url": chart_url,
    }


def normalize_efb_locations(raw) -> list[dict[str, Any]]:
    """Catalog rows stored on an EFB pack. Chart download stays a later feature."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return out
    for entry in raw:
        loc = _normalize_efb_location(entry if isinstance(entry, dict) else {"name": entry})
        if not loc:
            continue
        key = loc["name"].casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(loc)
    out.sort(key=lambda row: -max((len(t) for t in row.get("texts") or [row["name"]]), default=0))
    return out


def normalize_pack(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    schema = str(raw.get("schema") or "").strip()
    if schema and schema != PACK_SCHEMA:
        # Accept unknown schemas if they look like rule packs.
        if not raw.get("rules") and not raw.get("images"):
            return None
    pack_id = str(raw.get("id") or "").strip() or "pack"
    name = str(raw.get("name") or pack_id).strip()
    description = str(raw.get("description") or "").strip()
    kind = normalize_pack_kind(raw.get("kind"))
    variable = raw.get("variable") if isinstance(raw.get("variable"), dict) else {}
    variables = _normalize_variables_list(raw.get("variables"), variable if variable else None)
    if not variables and kind == "static":
        variables = [{"name": "rock", "default": ""}]
    var_name = variables[0]["name"] if variables else "rock"

    field_map = {}
    raw_fields = raw.get("field_map") if isinstance(raw.get("field_map"), dict) else {}
    for key, val in raw_fields.items():
        k = str(key or "").strip().casefold()
        n = overlay_variable_name(val)
        if k and n:
            field_map[k] = n

    target_image = str(raw.get("target_image_widget") or raw.get("image_widget") or "").strip()
    if kind == "image_map" and not target_image:
        target_image = "SC EFB Chart"

    # Prefer explicit locations[] catalog (EFB lookup). Fall back to legacy per-rule images/rules.
    locations = normalize_efb_locations(raw.get("locations") if "locations" in raw else raw.get("images"))
    if kind == "image_map" and not locations and raw.get("rules"):
        # Legacy: each rule was one location with texts + chart URLs.
        legacy = []
        for entry in raw.get("rules") or []:
            if not isinstance(entry, dict):
                continue
            legacy.append(
                {
                    "name": entry.get("name") or entry.get("display_name"),
                    "texts": entry.get("texts") if "texts" in entry else entry.get("text"),
                    "chart_url": entry.get("chart_url"),
                    "page_url": entry.get("page_url"),
                    "chart_id": entry.get("chart_id") or entry.get("id"),
                }
            )
        locations = normalize_efb_locations(legacy)

    rules_src = list(raw.get("rules") or [])
    # Catalog-driven EFB: ignore per-location rules; install one region-capture rule.
    catalog_lookup = kind == "image_map" and bool(locations)
    if catalog_lookup:
        rules_src = [
            {
                "name": "EFB location",
                "display_name": "EFB location",
                "texts": [],
                "match": "any",
                "capture": "region",
                "mapping": {
                    "action": "map_to_overlay",
                    "mode": "efb_lookup",
                    "image_widget": target_image,
                },
            }
        ]

    rules_out = []
    for index, entry in enumerate(rules_src):
        if not isinstance(entry, dict):
            continue
        rule = default_ocr_rule(index)
        rule["id"] = str(entry.get("id") or "").strip() or str(uuid.uuid4())
        rule["name"] = str(entry.get("name") or "").strip() or f"Rule {index + 1}"
        rule["display_name"] = str(entry.get("display_name") or entry.get("name") or "").strip() or rule["name"]
        rule["texts"] = split_ocr_texts(entry.get("texts") if "texts" in entry else entry.get("text"))
        rule["match"] = normalize_ocr_match(
            entry.get("match")
            or ("any" if kind in ("citizen_lookup", "image_map") and catalog_lookup else "exact")
        )
        rule["base"] = normalize_ocr_base(entry.get("base"))
        rule["capture"] = normalize_ocr_capture(
            entry.get("capture")
            or ("region" if kind == "citizen_lookup" or catalog_lookup else "")
        )
        if (kind == "citizen_lookup" or catalog_lookup) and not rule["capture"]:
            rule["capture"] = "region"
            rule["match"] = "any"
            rule["texts"] = []
        chart_url = str(entry.get("chart_url") or "").strip()
        page_url = str(entry.get("page_url") or "").strip()
        chart_id = str(entry.get("chart_id") or entry.get("id") or rule["name"]).strip()
        image_widget = str(entry.get("image_widget") or target_image).strip()
        mapping = entry.get("mapping") if isinstance(entry.get("mapping"), dict) else {}
        mode = str(mapping.get("mode") or "").strip().casefold()
        if not mode:
            if kind == "citizen_lookup":
                mode = "citizen_lookup"
            elif catalog_lookup:
                mode = "efb_lookup"
            elif kind == "image_map":
                mode = "set_image"
            else:
                mode = "set_variable"
        recipe = {
            "action": str(mapping.get("action") or "map_to_overlay"),
            "mode": mode,
            "write": str(mapping.get("write") or "contribute"),
            "variable": overlay_variable_name(mapping.get("variable") or var_name),
            "use_detection_label": bool(mapping.get("use_detection_label", True)),
            "image_widget": str(mapping.get("image_widget") or image_widget).strip(),
            "chart_url": str(mapping.get("chart_url") or chart_url).strip(),
            "page_url": str(mapping.get("page_url") or page_url).strip(),
            "chart_id": str(mapping.get("chart_id") or chart_id).strip(),
            "field_map": dict(field_map),
        }
        rule["_mapping_recipe"] = recipe
        runtime = {
            "kind": mode,
            "pack_id": pack_id,
            "image_widget": recipe["image_widget"],
            "chart_url": recipe["chart_url"],
            "page_url": recipe["page_url"],
            "chart_id": recipe["chart_id"],
            "field_map": dict(field_map),
        }
        if mode == "efb_lookup" or catalog_lookup:
            runtime["kind"] = "efb_lookup"
            runtime["locations"] = list(locations)
            recipe["mode"] = "efb_lookup"
        if kind == "citizen_lookup":
            runtime["kind"] = "citizen_lookup"
            runtime["field_map"] = dict(field_map)
        rule["_runtime"] = runtime
        rule["pack_id"] = pack_id
        if chart_url:
            rule["chart_url"] = chart_url
        if page_url:
            rule["page_url"] = page_url
        if chart_id:
            rule["chart_id"] = chart_id
        if image_widget:
            rule["image_widget"] = image_widget
        if entry.get("mapping_xml"):
            rule["mapping_xml"] = str(entry.get("mapping_xml") or "")
        rules_out.append(rule)

    # Citizen lookup packs always need at least one region-capture rule.
    if kind == "citizen_lookup" and not rules_out:
        rule = default_ocr_rule(0)
        rule["name"] = "Citizen handle"
        rule["display_name"] = "Citizen handle"
        rule["match"] = "any"
        rule["capture"] = "region"
        rule["texts"] = []
        recipe = {
            "action": "map_to_overlay",
            "mode": "citizen_lookup",
            "write": "replace",
            "variable": "",
            "use_detection_label": True,
            "field_map": dict(field_map),
            "image_widget": "",
            "chart_url": "",
            "page_url": "",
            "chart_id": "",
        }
        rule["_mapping_recipe"] = recipe
        rule["_runtime"] = {"kind": "citizen_lookup", "field_map": dict(field_map)}
        rules_out.append(rule)

    if kind == "image_map" and locations and "SCefb_location" not in {
        str(v.get("name") or "").casefold() for v in variables
    }:
        variables.append({"name": "SCefb_location", "default": ""})

    return {
        "schema": PACK_SCHEMA,
        "id": pack_id,
        "name": name,
        "description": description,
        "kind": kind,
        "variable": {"name": var_name, "default": variables[0]["default"] if variables else ""},
        "variables": variables,
        "field_map": field_map,
        "target_image_widget": target_image,
        "locations": locations,
        "rules": rules_out,
    }


def load_pack_file(path: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception as err:
        return None, f"Unable to read pack: {err}"
    pack = normalize_pack(raw)
    if not pack:
        return None, "File is not a valid OCR rule pack."
    return pack, None


def save_pack_file(path: str, pack: dict[str, Any]) -> str | None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(pack, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except Exception as err:
        return f"Unable to save pack: {err}"
    return None


def list_builtin_packs() -> list[dict[str, Any]]:
    packs = []
    root = _packs_dir()
    try:
        for name in sorted(os.listdir(root)):
            if not name.lower().endswith(".json"):
                continue
            path = os.path.join(root, name)
            pack, err = load_pack_file(path)
            if pack and not err:
                packs.append(pack)
    except Exception as err:
        syslog.debug(f"OBS OVERLAY OCR: list packs failed: {err}")
    return packs


def export_widget_pack(scene, item: dict[str, Any]) -> dict[str, Any]:
    rules = normalize_ocr_rules(item.get("ocr_rules"))
    # Prefer rock if present, else first variable, else rock stub.
    var_name = "rock"
    if scene is not None:
        row = scene.overlay_variable_by_name("rock")
        if row is None and scene.variables:
            var_name = str(scene.variables[0].get("name") or "rock")
    exported_rules = []
    for rule in rules:
        exported_rules.append(
            {
                "id": rule.get("id"),
                "name": rule.get("name"),
                "display_name": rule.get("display_name") or rule.get("name"),
                "base": rule.get("base"),
                "texts": list(rule.get("texts") or []),
                "match": rule.get("match") or "contain",
                "capture": rule.get("capture") or "",
                "chart_url": rule.get("chart_url") or "",
                "page_url": rule.get("page_url") or "",
                "mapping": {
                    "action": "map_to_overlay",
                    "mode": "set_variable",
                    "write": "contribute",
                    "variable": var_name,
                    "use_detection_label": True,
                },
            }
        )
    return {
        "schema": PACK_SCHEMA,
        "id": "exported",
        "name": "Exported OCR rules",
        "description": "",
        "kind": "static",
        "variable": {"name": var_name, "default": ""},
        "variables": [{"name": var_name, "default": ""}],
        "rules": exported_rules,
    }


def _ensure_variable(scene, name: str, default: str = "") -> None:
    if scene is None:
        return
    cleaned = overlay_variable_name(name)
    if not cleaned:
        return
    if scene.overlay_variable_by_name(cleaned):
        return
    scene.add_overlay_variable(cleaned, default=default)


def _install_mapping_recipe(widget: dict[str, Any], rule: dict[str, Any], recipe: dict[str, Any]) -> None:
    """Create a Map to Overlay action on the rule's OverlayInputItem."""
    if not recipe or str(recipe.get("action") or "") != "map_to_overlay":
        return
    mode = str(recipe.get("mode") or "set_variable").casefold()
    # Citizen lookup / set_image are handled by OCR runtime hooks; still install a
    # stub Map to Overlay so the mapping dialog shows something useful when opened.
    try:
        from .overlay_input import ensure_overlay_input, dump_overlay_mapping_xml, write_ocr_rule_mapping_xml
        import gremlin.plugin_manager
        from gremlin.input_types import InputType

        input_id = ocr_rule_input_id(str(widget.get("id") or ""), str(rule.get("id") or ""))
        title = f"OCR · {rule.get('name') or rule.get('display_name') or 'Rule'}"
        item = ensure_overlay_input(input_id, title)
        if item is None:
            return
        # Skip if mappings already exist (import merge).
        if item.hasContainers:
            write_ocr_rule_mapping_xml(widget, rule, item)
            return

        try:
            from action_plugins.map_to_overlay import MapToOverlay as action_cls
        except Exception:
            try:
                action_cls = gremlin.plugin_manager.ActionPlugins().get_class("Map to Overlay")
            except Exception:
                return

        try:
            from container_plugins.basic import BasicContainer as basic_cls
        except Exception:
            try:
                basic_cls = gremlin.plugin_manager.ContainerPlugins().get_class("basic")
            except Exception:
                return

        container = basic_cls(parent=item)
        action = action_cls(container)
        if mode == "citizen_lookup":
            action.overlay_action = "citizen_lookup"
            action.use_detection_label = True
        elif mode in ("set_image", "efb_lookup"):
            # efb_lookup is handled by OCR runtime catalog match; Map action is set_image stub.
            action.overlay_action = "set_image"
            action.image_widget_name = str(recipe.get("image_widget") or "SC EFB Chart")
            action.chart_url = str(recipe.get("chart_url") or "")
            action.page_url = str(recipe.get("page_url") or "")
            action.chart_id = str(recipe.get("chart_id") or "")
            action.use_detection_label = True
        else:
            action.overlay_action = "set_variable"
            action.variable_name = overlay_variable_name(recipe.get("variable") or "rock")
            action.variable_write = str(recipe.get("write") or "contribute")
            action.use_detection_label = bool(recipe.get("use_detection_label", True))
            action.release_empty = True
        if not getattr(container, "action_sets", None):
            container.action_sets = [[]]
        if not container.action_sets:
            container.action_sets = [[]]
        if container.action_sets[0] is None:
            container.action_sets[0] = []
        container.action_sets[0].append(action)
        item.containers.addContainer(container)
        item.setOverrideInputType(InputType.JoystickButton)
        write_ocr_rule_mapping_xml(widget, rule, item)
        xml = dump_overlay_mapping_xml(item)
        if xml:
            rule["mapping_xml"] = xml
    except Exception as err:
        syslog.warning(f"OBS OVERLAY OCR: pack mapping install failed: {err}")


def apply_pack_to_widget(scene, widget_id: str, pack: dict[str, Any], *, replace: bool = True) -> str | None:
    """Apply a normalized pack onto an OCR widget. Returns error string or None."""
    if scene is None:
        return "No overlay scene."
    item = scene.widget_by_id(widget_id)
    if not item or item.get("type") != "ocr":
        return "Select an OCR widget."
    pack = normalize_pack(pack)
    if not pack:
        return "Invalid pack."

    for row in pack.get("variables") or []:
        _ensure_variable(scene, row.get("name") or "", str(row.get("default") or ""))
    # Legacy single variable
    var = pack.get("variable") or {}
    if var.get("name"):
        _ensure_variable(scene, var.get("name") or "rock", str(var.get("default") or ""))

    kind = normalize_pack_kind(pack.get("kind"))
    if kind == "image_map":
        try:
            from .ocr_images import ensure_named_image_widget

            ensure_named_image_widget(scene, pack.get("target_image_widget") or "SC EFB Chart")
        except Exception as err:
            syslog.warning(f"OBS OVERLAY OCR: ensure EFB image widget failed: {err}")

    if kind == "citizen_lookup":
        try:
            from .ocr_lookup import citizen_lookup

            citizen_lookup().configure(pack.get("field_map") or None)
        except Exception as err:
            syslog.debug(f"OBS OVERLAY OCR: citizen lookup configure failed: {err}")

    # Persist pack identity on the widget so runtime survives profile reload
    # even if `_runtime.locations` was stripped from saved JSON.
    try:
        style = dict(item.get("style") or {})
        style["ocr_pack_id"] = str(pack.get("id") or "")
        style["ocr_pack_kind"] = kind
        scene.apply_widget_update(widget_id, style=style)
        item = scene.widget_by_id(widget_id) or item
    except Exception as err:
        syslog.debug(f"OBS OVERLAY OCR: pack id style write failed: {err}")

    prepared: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for entry in pack.get("rules") or []:
        rule = default_ocr_rule(len(prepared))
        rule["id"] = str(entry.get("id") or rule["id"])
        rule["name"] = str(entry.get("name") or rule["name"])
        rule["display_name"] = str(entry.get("display_name") or rule["name"])
        rule["texts"] = list(entry.get("texts") or [])
        rule["match"] = normalize_ocr_match(entry.get("match") or "exact")
        rule["base"] = normalize_ocr_base(entry.get("base"))
        rule["capture"] = normalize_ocr_capture(entry.get("capture"))
        rule["pack_id"] = str(pack.get("id") or entry.get("pack_id") or "")
        for key in ("chart_url", "page_url", "chart_id", "image_widget", "_runtime"):
            if entry.get(key) is not None:
                rule[key] = entry.get(key)
        # Ensure runtime always carries pack_id + catalog/field_map after apply.
        runtime = rule.get("_runtime") if isinstance(rule.get("_runtime"), dict) else {}
        runtime = dict(runtime)
        runtime.setdefault("pack_id", rule["pack_id"])
        if kind == "citizen_lookup":
            runtime["kind"] = "citizen_lookup"
            runtime["field_map"] = dict(pack.get("field_map") or runtime.get("field_map") or {})
        elif kind == "image_map":
            runtime["kind"] = "efb_lookup"
            runtime["image_widget"] = str(pack.get("target_image_widget") or "SC EFB Chart")
            runtime["locations"] = list(pack.get("locations") or runtime.get("locations") or [])
        rule["_runtime"] = runtime
        if entry.get("mapping_xml"):
            rule["mapping_xml"] = str(entry.get("mapping_xml") or "")
        recipe = entry.get("_mapping_recipe") if isinstance(entry.get("_mapping_recipe"), dict) else None
        prepared.append((rule, recipe))

    from .overlay_input import remove_overlay_input

    if replace:
        for old in normalize_ocr_rules(item.get("ocr_rules")):
            remove_overlay_input(ocr_rule_input_id(widget_id, str(old.get("id") or "")))
        rules = []
        for rule, recipe in prepared:
            if not str(rule.get("mapping_xml") or "").strip() and recipe:
                _install_mapping_recipe(item, rule, recipe)
            rules.append(rule)
    else:
        rules = normalize_ocr_rules(item.get("ocr_rules"))
        existing_names = {str(r.get("name") or "").casefold() for r in rules}
        for rule, recipe in prepared:
            if str(rule.get("name") or "").casefold() in existing_names:
                continue
            if not str(rule.get("mapping_xml") or "").strip() and recipe:
                _install_mapping_recipe(item, rule, recipe)
            rules.append(rule)

    if not rules:
        rules = [default_ocr_rule(0)]
    scene.apply_widget_update(widget_id, ocr_rules=normalize_ocr_rules(rules))
    return None


def _mineable_signature_text(value) -> str:
    """Star Citizen shows thousands with a comma, so 11655 is stored as 11,655."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value or "").strip()
    if number >= 1000:
        return f"{number:,}"
    return str(number)


def build_sc_mineables_pack_from_source(source_path: str) -> dict[str, Any] | None:
    """Convert sc-overlay-main data/mineables.json into a jgex-ocr-pack."""
    try:
        with open(source_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as err:
        syslog.error(f"OBS OVERLAY OCR: unable to read mineables source: {err}")
        return None
    rocks = data.get("rocks") if isinstance(data, dict) else None
    if not isinstance(rocks, list):
        return None
    rules = []
    for rock in rocks:
        if not isinstance(rock, dict):
            continue
        name = str(rock.get("name") or "").strip()
        if not name:
            continue
        try:
            base = int(rock.get("base") or 0)
        except (TypeError, ValueError):
            base = 0
        sigs = rock.get("sigs") or []
        texts = [_mineable_signature_text(s) for s in sigs if s is not None]
        if not texts and base > 0:
            texts = [_mineable_signature_text(base)]
        rules.append(
            {
                "name": name,
                "display_name": name,
                "base": base if base > 0 else None,
                "texts": texts,
                "match": "exact",
                "mapping": {
                    "action": "map_to_overlay",
                    "mode": "set_variable",
                    "write": "contribute",
                    "variable": "rock",
                    "use_detection_label": True,
                },
            }
        )
    return {
        "schema": PACK_SCHEMA,
        "id": "sc-mineables",
        "name": "SC mineables",
        "description": "Star Citizen mining signature → ore × rock count (from sc-overlay mineables table).",
        "kind": "static",
        "variable": {"name": "rock", "default": ""},
        "variables": [{"name": "rock", "default": ""}],
        "rules": rules,
        "source": str(data.get("source") or ""),
    }
