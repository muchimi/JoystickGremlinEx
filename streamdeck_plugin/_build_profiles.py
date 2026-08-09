# Build JG Ex Stream Deck profile package(s) — one profile per device class.
import argparse
import json
import shutil
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "com.joystickgremlin.ex.sdPlugin"
PROFILES_DIR = ROOT / "profiles"
PROFILES_DIR.mkdir(exist_ok=True)

BUTTON_UUID = "com.joystickgremlin.ex.button"
PLUGIN_VERSION = "1.0.16"

# Elgato DeviceType -> package / grid / DeviceModel for AutoInstall profiles.
# Pages live inside each profile — never one profile per page.
DEVICE_SPECS = {
    "xl": {
        "out_name": "jgex-xl",
        "display_name": "JG Ex XL",
        "device_type": 2,
        "grid": (8, 4),
        "models": ("20GAT9902", "20GAT9901"),
        "preconfigured": "profiles/jgex-xl",
    },
    "plus": {
        "out_name": "jgex-plus",
        "display_name": "JG Ex +",
        "device_type": 7,
        "grid": (4, 2),
        "models": ("20GBD9901", "10GBD9901"),
        "preconfigured": "profiles/jgex-plus",
    },
    "classic": {
        "out_name": "jgex",
        "display_name": "JG Ex",
        "device_type": 0,
        "grid": (5, 3),
        "models": ("20GAA9901", "20GBA9901", "20GBA9902"),
        "preconfigured": "profiles/jgex",
    },
    "mini": {
        "out_name": "jgex-mini",
        "display_name": "JG Ex Mini",
        "device_type": 1,
        "grid": (3, 2),
        "models": ("20GAI9901", "20GBA9903"),
        "preconfigured": "profiles/jgex-mini",
    },
    "neo": {
        "out_name": "jgex-neo",
        "display_name": "JG Ex Neo",
        "device_type": 9,
        "grid": (4, 2),
        "models": ("20GEA9901", "20GDH9901"),
        "preconfigured": "profiles/jgex-neo",
    },
}


def _button_action(col: int, row: int, title: str, page: int = 1) -> dict:
    return {
        "Name": "JG Ex Button",
        "Settings": {"buttonId": f"{row}:{col}", "page": int(page), "title": title},
        "State": 0,
        "States": [{
            "FFamily": "", "FSize": "12", "FStyle": "", "FUnderline": "off",
            "Image": "", "Title": title, "TitleAlignment": "middle",
            "TitleColor": "#ffffff", "TitleShow": "",
        }],
        "UUID": BUTTON_UUID,
    }


def build_page_actions(cols: int, rows: int, page: int = 1) -> dict:
    actions = {}
    for r in range(rows):
        for c in range(cols):
            actions[f"{c},{r}"] = _button_action(c, r, f"{r}:{c}", page=page)
    # Brand marker on a stable key when the grid is large enough.
    if cols > 1:
        actions["1,0"] = _button_action(1, 0, "JG Ex", page=page)
    else:
        actions["0,0"] = _button_action(0, 0, "JG Ex", page=page)
    return actions


def build_legacy_profile(spec_key: str):
    spec = DEVICE_SPECS[spec_key]
    cols, rows = spec["grid"]
    out_name = spec["out_name"]
    display_name = spec["display_name"]
    device_model = spec["models"][0]
    profile_id = str(uuid.uuid4()).upper()
    staging = Path.cwd() / "_tmp_sd_profile" / out_name
    if staging.exists():
        shutil.rmtree(staging)
    sd = staging / f"{profile_id}.sdProfile"
    sd.mkdir(parents=True)

    manifest = {
        "Actions": build_page_actions(cols, rows),
        "DeviceModel": device_model,
        "Name": display_name,
        "Version": "1.0",
    }
    (sd / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    for c in range(cols):
        for r in range(rows):
            (sd / f"{c},{r}").mkdir(exist_ok=True)

    out = PROFILES_DIR / f"{out_name}.streamDeckProfile"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sd.rglob("*"):
            rel = path.relative_to(staging).as_posix()
            if path.is_dir():
                zf.writestr(rel.rstrip("/") + "/", b"")
            else:
                zf.write(path, rel)
    shutil.rmtree(staging.parent, ignore_errors=True)
    print(f"Wrote {out.name} ({out.stat().st_size} bytes) '{display_name}' model={device_model}")


def patch_plugin_manifest():
    manifest_path = ROOT / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["UUID"] = "com.joystickgremlin.ex"
    data["Version"] = PLUGIN_VERSION
    data["CodePath"] = "app.html"
    data["Software"] = {"MinimumVersion": "6.5"}
    data["Profiles"] = [
        {
            "Name": spec["preconfigured"],
            "DeviceType": spec["device_type"],
            "Readonly": False,
            "DontAutoSwitchWhenInstalled": True,
            "AutoInstall": True,
        }
        for spec in DEVICE_SPECS.values()
    ]
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Patched manifest v{data['Version']} profiles={len(data['Profiles'])}")


def remove_seeded_jgex_profiles():
    prefs = Path.home() / "AppData/Roaming/Elgato/StreamDeck/ProfilesV3"
    if not prefs.exists():
        return
    for folder in list(prefs.glob("*.sdProfile")):
        try:
            man = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        name = man.get("Name") or ""
        pre = man.get("PreconfiguredName") or ""
        if name.startswith("JG Ex") or pre.startswith("profiles/jgex"):
            shutil.rmtree(folder, ignore_errors=True)
            print(f"Removed {name} ({folder.name})")


def _find_connected_device_uuids() -> dict[str, tuple[str, str]]:
    """Map spec_key -> (DeviceModel, device UUID) for decks present in ProfilesV3."""
    prefs = Path.home() / "AppData/Roaming/Elgato/StreamDeck/ProfilesV3"
    found: dict[str, tuple[str, str]] = {}
    if not prefs.exists():
        return found
    for folder in prefs.glob("*.sdProfile"):
        try:
            man = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        dev = man.get("Device") or {}
        model = dev.get("Model")
        device_uuid = dev.get("UUID")
        if not model or not device_uuid:
            continue
        for key, spec in DEVICE_SPECS.items():
            if model in spec["models"] and key not in found:
                found[key] = (model, device_uuid)
    return found


def seed_profile_for_spec(spec_key: str, device_model: str, device_uuid: str, num_pages: int = 5):
    """Install one multi-page JG Ex profile into ProfilesV3 for a connected device."""
    prefs = Path.home() / "AppData/Roaming/Elgato/StreamDeck/ProfilesV3"
    if not prefs.exists():
        raise SystemExit("ProfilesV3 missing")

    spec = DEVICE_SPECS[spec_key]
    cols, rows = spec["grid"]
    profile_id = str(uuid.uuid4()).upper()
    root = prefs / f"{profile_id}.sdProfile"
    pages_root = root / "Profiles"
    pages_root.mkdir(parents=True)
    page_ids = [str(uuid.uuid4()) for _ in range(num_pages)]

    def v3_actions(page_index: int) -> dict:
        actions = {}
        for r in range(rows):
            for c in range(cols):
                title = f"P{page_index + 1}\n{r}:{c}"
                actions[f"{c},{r}"] = {
                    "ActionID": str(uuid.uuid4()),
                    "LinkedTitle": True,
                    "Name": "JG Ex Button",
                    "Plugin": {
                        "Name": "Joystick Gremlin Ex",
                        "UUID": "com.joystickgremlin.ex",
                        "Version": PLUGIN_VERSION,
                    },
                    "Resources": None,
                    "Settings": {
                        "buttonId": f"{r}:{c}",
                        "page": page_index + 1,
                        "title": title,
                    },
                    "State": 0,
                    "States": [{
                        "FontFamily": "", "FontSize": 12, "FontStyle": "",
                        "FontUnderline": False, "OutlineThickness": 2,
                        "ShowTitle": True, "Title": title,
                        "TitleAlignment": "middle", "TitleColor": "#ffffff",
                    }],
                    "UUID": BUTTON_UUID,
                }
        marker = "1,0" if cols > 1 else "0,0"
        actions[marker]["States"][0]["Title"] = f"JG Ex\nPage {page_index + 1}"
        actions[marker]["Settings"]["title"] = f"JG Ex\nPage {page_index + 1}"
        return actions

    for i, pid in enumerate(page_ids):
        pdir = pages_root / pid.upper()
        pdir.mkdir(parents=True)
        (pdir / "manifest.json").write_text(
            json.dumps(
                {"Controllers": [{"Type": "Keypad", "Actions": v3_actions(i)}], "Icon": "", "Name": ""},
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

    manifest = {
        "AppIdentifier": "*",
        "Device": {"Model": device_model, "UUID": device_uuid},
        "InstalledByPluginUUID": "com.joystickgremlin.ex",
        "Name": spec["display_name"],
        "Pages": {
            "Current": page_ids[0],
            "Default": page_ids[0],
            "Pages": page_ids,
        },
        "PreconfiguredName": spec["preconfigured"],
        "Version": "3.0",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    print(
        f"Seeded '{spec['display_name']}' ({spec_key}) model={device_model} "
        f"pages={num_pages} ({root.name})"
    )


def seed_connected_profiles(num_pages: int = 5):
    """Seed JG Ex profiles for every supported device type currently present."""
    connected = _find_connected_device_uuids()
    if not connected:
        raise SystemExit("No supported Stream Deck device UUIDs found in ProfilesV3")
    remove_seeded_jgex_profiles()
    for spec_key, (model, device_uuid) in sorted(connected.items()):
        seed_profile_for_spec(spec_key, model, device_uuid, num_pages)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=5, help="Pages inside each seeded JG Ex profile")
    parser.add_argument("--seed", action="store_true", help="Install JG Ex profiles into ProfilesV3 for connected decks")
    args = parser.parse_args()
    n = max(1, int(args.pages))

    for old in PROFILES_DIR.glob("*.streamDeckProfile"):
        old.unlink()
        print(f"Removed {old.name}")

    for key in DEVICE_SPECS:
        build_legacy_profile(key)
    patch_plugin_manifest()
    if args.seed:
        seed_connected_profiles(n)
    print("done")
