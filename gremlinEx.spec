# -*- mode: python -*-

import os
import sys

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

block_cipher = None

# Properly enumerate all files required for the action_plugins and
# container_plugins system
action_plugins_files = []
for root, _, files in os.walk("action_plugins"):
    for fname in files:
        if fname.endswith(".pyc"):
            continue
        action_plugins_files.append((os.path.join(root, fname), root))
container_plugins_files = []
for root, _, files in os.walk("container_plugins"):
    for fname in files:
        if fname.endswith(".pyc"):
            continue
        container_plugins_files.append((os.path.join(root, fname), root))
doc_files = []
for root, _, files in os.walk("gremlin"):
    for fname in files:
        if fname.endswith(".md"):
            doc_files.append((os.path.join(root, fname), root))
xml_files = []
for root, _, files in os.walk(".xml"):
    for fname in files:
        if fname.endswith(".xml"):
            xml_files.append((os.path.join(root, fname), root))

icon_files = []
for root, _, files in os.walk("icons"):
    for fname in files:
        icon_files.append((os.path.join(root, fname), root))

sound_files = []
for root, _, files in os.walk("sounds"):
    for fname in files:
        sound_files.append((os.path.join(root, fname), root))

added_files = [
    ("about", "about"),
    ("doc", "doc"),
    ("icons","icons"),
    ("gremlin/ui/streamdeck_icon_library", "gremlin/ui/streamdeck_icon_library"),
]
if os.path.isdir("gremlin/ui/obs_overlay/assets"):
    added_files.append(("gremlin/ui/obs_overlay/assets", "gremlin/ui/obs_overlay/assets"))
if os.path.isdir("gremlin/ui/obs_overlay/packs"):
    added_files.append(("gremlin/ui/obs_overlay/packs", "gremlin/ui/obs_overlay/packs"))


added_files.extend(collect_data_files("faster_whisper"))
added_files.extend(collect_data_files("rapidocr"))

added_files.extend(action_plugins_files)
added_files.extend(icon_files)
added_files.extend(sound_files)
added_files.extend(container_plugins_files)
added_files.extend(doc_files)
added_files.extend(xml_files)
_binary_candidates = [
    ("vjoy/vJoyInterface.dll", "."),
    ("dill.dll", "."),
    ("vigem/ViGEmClient.dll", "."),
    ("SimConnect.dll", "."),
    ("hidapi.dll", "."),
    ("ffmpeg/ffmpeg.exe", "."),
    ("ffmpeg/ffprobe.exe", "."),
]



added_binaries = []
for src, dest in _binary_candidates:
    if os.path.exists(src):
        added_binaries.append((src, dest))
    else:
        print(f"WARNING: skipping missing binary {src}")
added_binaries.extend(collect_dynamic_libs("cv2"))
# CPU build. The CUDA and TensorRT provider DLLs are not used and fail to load
# on a machine that does not have those runtimes.
for _src, _dest in collect_dynamic_libs("onnxruntime"):
    _name = os.path.basename(_src).lower()
    if "cuda" in _name or "tensorrt" in _name:
        print(f"WARNING: skipping ONNX provider {_name}")
        continue
    added_binaries.append((_src, _dest))

# The extension is not a dependency of onnxruntime.dll. Name it so the frozen
# import can find it beside that DLL.
import onnxruntime as _onnxruntime

_ort_capi = os.path.join(os.path.dirname(_onnxruntime.__file__), "capi")
_ort_pyd = os.path.join(_ort_capi, "onnxruntime_pybind11_state.pyd")
if os.path.isfile(_ort_pyd):
    added_binaries.append((_ort_pyd, "onnxruntime/capi"))
else:
    print(f"WARNING: missing {_ort_pyd}")

# The extension imports these by name. msvcp140.dll and msvcp140_1.dll live in
# System32, not next to Python, so a dependency walk can miss them.
_vc_names = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll")
_vc_dirs = [
    getattr(sys, "base_prefix", ""),
    os.path.dirname(sys.executable),
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"),
]
for _vc_name in _vc_names:
    _vc_path = ""
    for _folder in _vc_dirs:
        if not _folder:
            continue
        _candidate = os.path.join(_folder, _vc_name)
        if os.path.isfile(_candidate):
            _vc_path = _candidate
            break
    if not _vc_path:
        print(f"WARNING: VC runtime DLL not found: {_vc_name}")
        continue
    added_binaries.append((_vc_path, "."))
    added_binaries.append((_vc_path, "onnxruntime/capi"))

# pathlib.PurePath.match patterns. UPX corrupts these if a builder does not
# already skip Control Flow Guard binaries.
_OCR_UPX_EXCLUDE = [
    "onnxruntime.dll",
    "onnxruntime_*.dll",
    "onnxruntime_pybind11_state.pyd",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
]

'''
excludes=["torch",
        "torchvision",
        "torchaudio",
        "torch._C",
        "torch.utils",
        "torch.cuda",
        "torch.backends",
        "torch.distributed",
        "noisereduce",
        "coqui-tts",
        "soundfile",
        "numba"],
'''


a = Analysis(
    ["gremlinEx.py"],
    pathex=['C:/JoystickGremlin-develop'],
    binaries=added_binaries,
    datas=added_files,
    hiddenimports=[
        'mido.backends.rtmidi',
        'lxml',
        'pyttsx3',
        'hid',
        "psygnal",
        "graphviz",
        "numpy",
        "scipy",
        "scipy._cyutility",
        "sounddevice",
        "soundfile",
        "pyrubberband",
        "pydub",
        "faster_whisper",
        "huggingface_hub",
        "ctranslate2",
        "tokenizers",
        "onnxruntime",
        "onnxruntime.capi._pybind_state",
        "cv2",
        "pyclipper",
        "shapely",
        "yaml",
        "PIL",
        "omegaconf",
        "colorlog",
        "winrt.windows.media.ocr",
        "winrt.windows.graphics.imaging",
        "winrt.windows.storage.streams",
        "winrt.windows.globalization",
        "pycaw",
        "pycountry",
        "objprint",
        "frozendict",
        "anytree",
        "dill",
        "filelock",
        "rapidfuzz",
        "sympy",
        "qtawesome",
        "OdenGraphQt",
        # "pygraphviz",
        # "networkx",
        "gremlin.ui.obs_overlay",
        "gremlin.ui.obs_overlay.bindings",
        "gremlin.ui.obs_overlay.blink",
        "gremlin.ui.obs_overlay.designer",
        "gremlin.ui.obs_overlay.gradient",
        "gremlin.ui.obs_overlay.host_window",
        "gremlin.ui.obs_overlay.inspector",
        "gremlin.ui.obs_overlay.model",
        "gremlin.ui.obs_overlay.ocr_capture",
        "gremlin.ui.obs_overlay.ocr_engine",
        "gremlin.ui.obs_overlay.ocr_lookup",
        "gremlin.ui.obs_overlay.ocr_packs",
        "gremlin.ui.obs_overlay.ocr_track",
        "gremlin.ui.obs_overlay.overlay_window",
        "gremlin.ui.obs_overlay.palettes",
        "gremlin.ui.obs_overlay.property_clipboard",
        "gremlin.ui.obs_overlay.selection_pane",
        "gremlin.ui.obs_overlay.shapes",
        "gremlin.ui.obs_overlay.templates",
        "gremlin.ui.obs_overlay.touch",
        "gremlin.ui.obs_overlay.visibility_logic",
        "gremlin.ui.obs_overlay.visibility_preview",
        "gremlin.ui.obs_overlay.widgets",
        "gremlin.remote_video",
        "gremlin.ui.afcs",
        "gremlin.ui.afcs.designer",
        "gremlin.ui.afcs.model",
        "gremlin.ui.afcs.nodes",
        "gremlin.ui.afcs.ops",
        "gremlin.ui.afcs.runtime",
        "OdenGraphQt",
        "qtpy",
        "av",
        ] +  collect_submodules('encodings') + collect_submodules('av') + collect_submodules('OdenGraphQt') + collect_submodules('rapidocr'),
    hookspath=None,
    runtime_hooks=["pyi_rth_onnxruntime.py"],
    excludes=["torch",
        "torchvision",
        "torchaudio",
        "torch._C",
        "torch.utils",
        "torch.cuda",
        "torch.backends",
        "torch.distributed",
        "transformers",
        "noisereduce",
        "coqui-tts",
        "numba",
        "sklearn",
        "pandas",
        "pil",
        "TensorFlow",
        "pycrfsuite",
        "pysbd",
        "librosa",
        "pygame",
        ],
    win_no_prefer_redirects=None,
    win_private_assemblies=None,
    cipher=block_cipher,
    optimize=1,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="gremlinEx",
    debug=False,
    strip=None,
    upx=True,
    upx_exclude=_OCR_UPX_EXCLUDE,
    console=False,
    icon="icons\\gex.ico"
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=None,
    upx=True,
    upx_exclude=_OCR_UPX_EXCLUDE,
    name="gremlinEx"
)

