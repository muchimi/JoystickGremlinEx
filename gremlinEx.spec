# -*- mode: python -*-

import os

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
    ("icons","icons")
]

added_files.extend(action_plugins_files)
added_files.extend(icon_files)
added_files.extend(container_plugins_files)
added_files.extend(doc_files)
added_files.extend(xml_files)
added_binaries = [
    ("vjoy/vJoyInterface.dll", "."),
    ("dill.dll", "."),
    ("vigem/ViGEmClient.dll", "."),
    ("SimConnect.dll","."),
    ("hidapi.dll","."),
    ("ffmpeg/ffmpeg.exe",".")

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
    hiddenimports=['mido.backends.rtmidi','lxml','pyttsx3','hid',"windows_event_hook","psygnal","graphviz","numpy","scipy","scipy._cyutility","sounddevice","soundfile","pyrubberband","pydub","ffmpeg"],
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
    icon="icons\\icon.ico"
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

