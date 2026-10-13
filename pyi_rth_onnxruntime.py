# PyInstaller runtime hook. The ONNX Runtime extension loads its DLL from the
# folder that contains the extension. That folder is not on the default search
# path inside a frozen build.
import os
import sys

if sys.platform == "win32" and getattr(sys, "frozen", False):
    base = getattr(sys, "_MEIPASS", "")
    capi = os.path.join(base, "onnxruntime", "capi")
    if base and os.path.isdir(capi):
        try:
            os.add_dll_directory(capi)
        except (AttributeError, OSError):
            pass
        os.environ["PATH"] = capi + os.pathsep + os.environ.get("PATH", "")
