"""Rename to SC Assistant: settings folder move, names, mutex, User-Agent.

    python -m tools.rename_selftest

Every case runs in its own temporary %APPDATA% (never the user's folders).
Qt runs off-screen and no window is shown; nothing grabs the keyboard, no
hotkey thread starts and no message box opens (MessageBoxW is replaced).

The first case drives the import path itself: the old "Citizen Assistant"
folder exists before ``app.config`` is imported, so CONFIG_PATH must already
point into the moved folder and Config.load must read the old settings.
"""
from __future__ import annotations

from tools import _testguard

_testguard.install()        # first: no focus, no hotkeys

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.version import (APP_NAME, MUTEX_NAME, OLD_APP_NAME,  # noqa: E402
                         OLD_MUTEX_NAME, USER_AGENT, VERSION)

_TMP = Path(tempfile.mkdtemp(prefix="ca-rename-"))
_COUNTER = [0]
_KEEP: list = []        # the QApplication lives for the whole run


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


def _fresh_appdata() -> Path:
    _COUNTER[0] += 1
    base = _TMP / f"appdata{_COUNTER[0]}"
    base.mkdir()
    os.environ["APPDATA"] = str(base)
    os.environ["XDG_CONFIG_HOME"] = str(base)
    return base


def _seed(folder: Path, value: int) -> dict[str, bytes]:
    """User data as an old install leaves it; returns {relative path: bytes}."""
    files = {
        "config.json": json.dumps({"poll_ms": value}).encode(),
        "notes.txt": f"notes {value}".encode(),
        "inventory.json": b'{"items": [1, 2, 3]}',
        "anchors/anchor.png": bytes(range(256)) * 4,
    }
    for rel, data in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return files


def _same(folder: Path, files: dict[str, bytes]) -> bool:
    return all((folder / rel).is_file() and (folder / rel).read_bytes() == data
               for rel, data in files.items())


# --- 1: old folder only, at import time --------------------------------------
def case_import_moves() -> int:
    base = _fresh_appdata()
    files = _seed(base / OLD_APP_NAME, 4321)
    from app import config  # first import: CONFIG_PATH is computed now

    new = base / APP_NAME
    f = 0
    f += _check("import: CONFIG_PATH is in the new folder",
                config.CONFIG_PATH == new / "config.json", f"({config.CONFIG_PATH})")
    f += _check("import: old folder moved (gone)", not (base / OLD_APP_NAME).exists())
    f += _check("import: every file intact in the new folder", _same(new, files))
    f += _check("import: Config.load reads the moved settings",
                config.Config.load().get("poll_ms") == 4321)
    return f


# --- 2: both folders hold files -----------------------------------------------
def case_both_exist() -> int:
    from app import config

    base = _fresh_appdata()
    old_files = _seed(base / OLD_APP_NAME, 1111)
    new_files = _seed(base / APP_NAME, 2222)
    d = config.config_dir()
    f = 0
    f += _check("both: the new folder is used", d == base / APP_NAME, f"({d})")
    f += _check("both: old folder left as it was", _same(base / OLD_APP_NAME, old_files))
    f += _check("both: new folder left as it was", _same(base / APP_NAME, new_files))
    return f


# --- 3: new folder exists but empty -------------------------------------------
def case_new_empty() -> int:
    from app import config

    base = _fresh_appdata()
    files = _seed(base / OLD_APP_NAME, 3333)
    (base / APP_NAME).mkdir()
    d = config.config_dir()
    f = 0
    f += _check("empty new: the new folder is used", d == base / APP_NAME, f"({d})")
    f += _check("empty new: files moved in", _same(base / APP_NAME, files))
    f += _check("empty new: old folder gone", not (base / OLD_APP_NAME).exists())
    return f


# --- 4: rename blocked by an open file -> copy --------------------------------
def case_move_blocked_copies() -> int:
    from app import config

    base = _fresh_appdata()
    files = _seed(base / OLD_APP_NAME, 5555)
    real_replace = os.replace
    old_dir = base / OLD_APP_NAME

    def blocked(src, dst, *a, **k):
        # A file held open makes Windows refuse the folder rename; raise the
        # same error on every platform for the old folder only.
        if Path(src) == old_dir:
            raise PermissionError(32, "file in use", str(src))
        return real_replace(src, dst, *a, **k)

    with open(old_dir / "notes.txt", "rb"):
        config.os.replace = blocked
        try:
            d = config.config_dir()
        finally:
            config.os.replace = real_replace
    f = 0
    f += _check("blocked move: the new folder is used", d == base / APP_NAME, f"({d})")
    f += _check("blocked move: files copied to the new folder", _same(base / APP_NAME, files))
    f += _check("blocked move: old folder intact", _same(old_dir, files))
    f += _check("blocked move: no temporary copy left",
                not (base / f"{APP_NAME}.moving").exists())
    return f


# --- 5: rename and copy both fail -> old folder used, nothing lost ------------
def case_move_and_copy_fail() -> int:
    from app import config

    base = _fresh_appdata()
    files = _seed(base / OLD_APP_NAME, 7777)
    real_replace, real_copytree = os.replace, shutil.copytree
    old_dir = base / OLD_APP_NAME

    def no_replace(src, dst, *a, **k):
        if Path(src) == old_dir:
            raise PermissionError(32, "file in use", str(src))
        return real_replace(src, dst, *a, **k)

    def half_copy(src, dst, *a, **k):
        Path(dst).mkdir(parents=True)
        (Path(dst) / "config.json").write_bytes(b"{}")      # partial copy
        raise OSError(28, "disk full")

    config.os.replace, config.shutil.copytree = no_replace, half_copy
    try:
        d = config.config_dir()
    finally:
        config.os.replace, config.shutil.copytree = real_replace, real_copytree
    f = 0
    f += _check("both fail: old folder intact", _same(old_dir, files))
    f += _check("both fail: old folder used for this run", d == old_dir, f"({d})")
    f += _check("both fail: no half-copied new folder or leftover",
                not (base / APP_NAME).exists()
                and not (base / f"{APP_NAME}.moving").exists())
    # Next start (fresh resolution) the move goes through.
    config._RESOLVED.clear()
    d2 = config.config_dir()
    f += _check("both fail: next start moves the folder",
                d2 == base / APP_NAME and _same(d2, files)
                and not old_dir.exists())
    return f


# --- names --------------------------------------------------------------------
def case_names() -> int:
    from PySide6.QtWidgets import QApplication

    _fresh_appdata()
    _KEEP.append(QApplication.instance() or QApplication([]))
    from app import hauling, main as main_mod, planner, sigsource
    from app.ui import navbar, theme

    f = 0
    f += _check("APP_TITLE is the new name", main_mod.APP_TITLE == APP_NAME,
                f"({main_mod.APP_TITLE})")

    # Brand: record what the real paintEvent draws (off-screen grab).
    drawn: list[str] = []
    real_paint = theme.paint

    class Rec:
        def __init__(self, p):
            self._p = p

        def drawText(self, *args):  # noqa: N802
            drawn.extend(a for a in args if isinstance(a, str))
            return self._p.drawText(*args)

        def __getattr__(self, name):
            return getattr(self._p, name)

    def paint(widget):
        p, w, h = real_paint(widget)
        return Rec(p), w, h

    theme.paint = paint
    try:
        brand = navbar._Brand()
        brand.grab()
    finally:
        theme.paint = real_paint
    f += _check("nav bar brand reads SC ASSISTANT", "SC ASSISTANT" in drawn, f"({drawn})")

    bar = navbar.NavBar(main_mod.TOOLS)
    tip = bar.quit_btn.toolTip()
    f += _check("QUIT tooltip names SC Assistant", tip == "Quit SC Assistant (click twice)",
                f"({tip!r})")
    bar.deleteLater()
    brand.deleteLater()

    src = (ROOT / "app" / "ui" / "settings_panel.py").read_text(encoding="utf-8")
    f += _check("Settings texts have no old name", OLD_APP_NAME not in src)

    # --version and --help through the real argparse in main().
    saved_hook = sys.excepthook
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            main_mod.main(["--version"])
        except SystemExit:
            pass
        try:
            main_mod.main(["--help"])
        except SystemExit:
            pass
    sys.excepthook = saved_hook
    text = out.getvalue()
    f += _check("main --version prints SC Assistant",
                f"{APP_NAME} v{VERSION}" in text, f"({text.splitlines()[:1]})")
    f += _check("argparse prog is sc-assistant", "usage: sc-assistant" in text)

    proc = subprocess.run([sys.executable, "-m", "app", "--version"], cwd=ROOT,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ})
    f += _check("python -m app --version prints SC Assistant",
                proc.stdout.startswith(f"{APP_NAME} v{VERSION}"), f"({proc.stdout.strip()})")

    # User-Agent: hauling/planner constants and the header sigsource sends.
    f += _check("hauling User-Agent", hauling.USER_AGENT == USER_AGENT, f"({hauling.USER_AGENT})")
    f += _check("planner User-Agent", planner.USER_AGENT == USER_AGENT, f"({planner.USER_AGENT})")
    sent: list[str] = []

    class Stop(Exception):
        pass

    def fake_urlopen(req, timeout=None):
        sent.append(req.get_header("User-agent"))
        raise Stop

    real_urlopen = sigsource.urllib.request.urlopen
    sigsource.urllib.request.urlopen = fake_urlopen
    try:
        sigsource.http_get("https://example.invalid/")
    except Stop:
        pass
    finally:
        sigsource.urllib.request.urlopen = real_urlopen
    f += _check("sigsource sends the User-Agent", sent == [USER_AGENT], f"({sent})")
    return f


# --- mutex and the already-running message (Windows) --------------------------
def case_mutex() -> int:
    if sys.platform != "win32":
        print("  SKIP  mutex checks (Windows only)")
        return 0
    import ctypes
    from ctypes import wintypes

    from app import main as main_mod

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k32.OpenMutexW.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    def exists(name: str) -> bool:
        h = k32.OpenMutexW(0x00100000, False, f"Local\\{name}")
        if h:
            k32.CloseHandle(h)
        return bool(h)

    f = 0
    f += _check("main uses MUTEX_NAME / OLD_MUTEX_NAME",
                getattr(main_mod, "MUTEX_NAME", None) == MUTEX_NAME
                and getattr(main_mod, "OLD_MUTEX_NAME", None) == OLD_MUTEX_NAME)
    # The real names may be held by a copy the user is running, so the
    # behaviour runs on per-process test names patched into main.
    new_name = f"{MUTEX_NAME}-selftest-{os.getpid()}"
    old_name = f"{OLD_MUTEX_NAME}-selftest-{os.getpid()}"
    saved = (getattr(main_mod, "MUTEX_NAME", None), getattr(main_mod, "OLD_MUTEX_NAME", None))
    main_mod.MUTEX_NAME, main_mod.OLD_MUTEX_NAME = new_name, old_name
    try:
        old = k32.CreateMutexW(None, False, f"Local\\{old_name}")
        try:
            f += _check("refuses while an old-name copy runs",
                        main_mod._acquire_single_instance() is False)
            f += _check("refused copy took no mutex", not exists(new_name))
        finally:
            k32.CloseHandle(old)
        f += _check("starts once the old copy is gone",
                    main_mod._acquire_single_instance() is True)
        f += _check("holds the new-name mutex", exists(new_name))
        f += _check("a second copy is refused",
                    main_mod._acquire_single_instance() is False)
    finally:
        if main_mod._MUTEX_HANDLE:
            k32.CloseHandle(main_mod._MUTEX_HANDLE)
            main_mod._MUTEX_HANDLE = None
        main_mod.MUTEX_NAME, main_mod.OLD_MUTEX_NAME = saved

    shown: list[tuple] = []
    user32 = ctypes.windll.user32
    real_box = user32.MessageBoxW
    user32.MessageBoxW = lambda *a: shown.append(a) or 1
    try:
        main_mod._already_running_notice()
    finally:
        user32.MessageBoxW = real_box
    ok = bool(shown) and shown[0][1].startswith(f"{APP_NAME} is already running") \
        and shown[0][2] == APP_NAME
    f += _check("already-running message names SC Assistant", ok,
                f"({shown[0][1].splitlines()[0] if shown else 'not shown'})")
    return f


def main() -> int:
    failures = 0
    for case in (case_import_moves, case_both_exist, case_new_empty,
                 case_move_blocked_copies, case_move_and_copy_fail,
                 case_names, case_mutex):
        print(case.__name__)
        try:
            failures += case()
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            failures += _check(f"{case.__name__} ran", False, f"({exc!r})")
    shutil.rmtree(_TMP, ignore_errors=True)
    print(f"\n{'OK' if not failures else f'{failures} FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
