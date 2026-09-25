# -*- mode: python -*-

import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

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

added_files = [
    ("about", "about"),
    ("doc", "doc"),
    ("icons","icons"),
    ("gremlin/ui/streamdeck_icon_library", "gremlin/ui/streamdeck_icon_library"),
]
if os.path.isdir("gremlin/ui/obs_overlay/assets"):
    added_files.append(("gremlin/ui/obs_overlay/assets", "gremlin/ui/obs_overlay/assets"))


added_files.extend(collect_data_files("faster_whisper"))

added_files.extend(action_plugins_files)
added_files.extend(icon_files)
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
        "pycaw",
        "pycountry",
        "OdenGraphQt",
        "gremlin.ui.obs_overlay",
        "gremlin.ui.obs_overlay.bindings",
        "gremlin.ui.obs_overlay.blink",
        "gremlin.ui.obs_overlay.designer",
        "gremlin.ui.obs_overlay.gradient",
        "gremlin.ui.obs_overlay.host_window",
        "gremlin.ui.obs_overlay.inspector",
        "gremlin.ui.obs_overlay.model",
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
        ] +  collect_submodules('encodings') + collect_submodules('av') + collect_submodules('OdenGraphQt'),
    hookspath=None,
    runtime_hooks=None,
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
    name="gremlinEx"
)

