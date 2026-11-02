# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the Windows build.

Data layout matters: the app resolves ``app/data`` and ``app.ico`` relative to
``__file__``, so both must sit at the same paths inside the bundle.

rapidocr_onnxruntime is imported lazily inside SignatureOCR, which static
analysis cannot see, hence the explicit collect_all calls.
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas = [
    ("app/data", "app/data"),
    ("app.ico", "."),
]
binaries = []
hiddenimports = collect_submodules("app")
# Every module under app/, listed from the files themselves. Engines that are
# loaded by name at run time (app.tts.windows, .piper, .kokoro, .edge,
# .addons) were missing from the 1.0.4 build made on GitHub although
# collect_submodules found them locally; listing the files does not depend on
# importing anything. tools/check_bundle.py fails a release if one is missing.
import os as _os

for _dir, _subdirs, _files in _os.walk("app"):
    _subdirs[:] = [d for d in _subdirs if d != "__pycache__"]
    for _name in _files:
        if _name.endswith(".py"):
            _mod = _os.path.join(_dir, _name[:-3]).replace(_os.sep, ".").replace("/", ".")
            if _mod.endswith(".__init__"):
                _mod = _mod[: -len(".__init__")]
            if _mod not in hiddenimports:
                hiddenimports.append(_mod)

for package in ("rapidocr_onnxruntime", "onnxruntime"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

# edge-tts (Microsoft online voices) is LGPL-3.0: ship it as plain .py files
# (module_collection_mode below) so a user can replace it, with its licence.
# Piper and Kokoro (GPL-3.0) are never bundled: they are downloaded add-ons.
datas += copy_metadata("edge-tts")

# Standard-library modules the voice add-ons (Piper, Kokoro: downloaded, not
# bundled) import but the app itself never does, so PyInstaller would leave
# them out. 1.0.4: Piper failed with "No module named 'wave'". Checked with
# SCAssistant.exe --voice-check FOLDER on the built EXE.
hiddenimports += [
    "wave", "mmap", "array", "unicodedata", "csv", "uuid", "pickle", "copyreg",
    "multiprocessing", "multiprocessing.pool", "multiprocessing.shared_memory",
    "concurrent.futures", "concurrent.futures.process", "concurrent.futures.thread",
    "dataclasses", "importlib.metadata", "importlib.resources", "ctypes.util",
    "difflib", "textwrap", "string", "locale", "platform", "shutil", "tempfile",
    "subprocess", "queue", "inspect", "typing", "contextlib", "linecache",
    "faulthandler", "zipfile", "json", "decimal", "fractions", "numbers",
    "fnmatch", "glob", "hashlib", "hmac", "secrets", "base64", "binascii",
    "codecs", "encodings.idna", "html", "html.parser", "xml.etree.ElementTree",
    "urllib.parse", "urllib.request", "http.client", "email", "email.utils",
    "argparse", "pprint", "heapq", "bisect", "statistics", "random", "copy",
    "weakref", "gc", "signal", "selectors", "socket", "ssl",
]
hiddenimports += collect_submodules("edge_tts")

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    module_collection_mode={"edge_tts": "py"},
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SCAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["app.ico"],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SCAssistant",
)
