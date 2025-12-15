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


added_files = [
    ("about", "about"),
    ("doc", "doc"),
    ("gfx", "gfx"),
]



added_files.extend(action_plugins_files)
added_files.extend(container_plugins_files)
added_files.extend(doc_files)
added_files.extend(xml_files)
added_binaries = [
    ("vjoy/vJoyInterface.dll", "."),
    ("dill.dll", "."),
    ("vigem/ViGEmClient.dll", "."),
    ("SimConnect.dll","."),
    ("hidapi.dll","."),
    ("rubberband.exe","."),
    ("rubberband-r3.exe","."),
    ("sndfile.dll","."),


	
]

from PyInstaller.utils.hooks import collect_all

pkgs = [
    "torch",
   
    "scipy",
    "sklearn", 
    "TTS",


]

modules = [
    'mido.backends.rtmidi',
    "windows_event_hook",
    "soundfile",
    "pydub",
    "pyrubberband",
    'lxml',
    'pyttsx3',
    'hid',
    "psygnal",
    "graphviz",
    "pygame",
    "torch._C",
    
]

def merge_collect_all(pkgs):
    datas, binaries, hiddenimports = [], [], []
    for p in pkgs:
        d, b, h = collect_all(p)
        datas += d
        binaries += b
        hiddenimports += h

    # de-dupe (important when packages overlap)
    datas = list(dict.fromkeys(datas))
    binaries = list(dict.fromkeys(binaries))
    hiddenimports = list(dict.fromkeys(hiddenimports))
    return datas, binaries, hiddenimports



datas, binaries, hidden_imports = merge_collect_all(pkgs)
hidden_imports.extend(modules)
added_binaries.extend(binaries)
added_files.extend(datas)



# dedup
added_binaries = list(dict.fromkeys(added_binaries))
added_files = list(dict.fromkeys(added_files))
hidden_imports = list(dict.fromkeys(hidden_imports))


a = Analysis(
    ["gremlinEx.py"],
    pathex=['C:/JoystickGremlin-develop'],
    binaries=added_binaries,
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=None,
    runtime_hooks=None,
    excludes=None,
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
    icon="gfx\\icon.ico"
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

