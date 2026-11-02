"""app.log and EXPORT DIAGNOSTICS (app/applog.py).

    python -m tools.applog_selftest

Every check uses temporary folders (APPDATA too); nothing touches the real
settings folder and nothing goes on the network. Exit code 1 on any failure.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory(prefix="sca-applog-")
os.environ["APPDATA"] = _TMP.name          # before app.config is imported

import numpy as np  # noqa: E402

from app import applog, sigsource, tracking, updater  # noqa: E402

LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} (DEBUG|INFO|WARNING|ERROR|CRITICAL) "
                  r"[\w.]+: .*$")


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


def _text(path: Path) -> str:
    applog._handler.flush()                # type: ignore[union-attr]
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _handlers() -> list:
    return [h for h in logging.getLogger().handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)]


def check_logging(base: Path) -> int:
    failures = 0
    folder = base / "settings"
    print("Warnings from app loggers land in app.log")
    path = applog.setup(folder, detailed=False)
    failures += _check("setup returns <folder>/app.log", path == folder / "app.log", str(path))
    logging.getLogger("app.notes").warning("notes could not be saved (%s)", "disk full")
    logging.getLogger("app.inventory").error("inventory unreadable")
    logging.getLogger("app.notes").debug("hidden debug line")
    logging.getLogger("app.notes").info("hidden info line")
    text = _text(path)
    lines = text.splitlines()
    failures += _check("warning written", "WARNING app.notes: notes could not be saved (disk full)"
                       in text, repr(text[-200:]))
    failures += _check("error written", "ERROR app.inventory: inventory unreadable" in text)
    failures += _check("every line has the format 'date time.ms LEVEL name: message'",
                       bool(lines) and all(LINE.match(x) for x in lines), repr(lines[:3]))
    failures += _check("no DEBUG/INFO lines when not detailed",
                       "hidden debug line" not in text and "hidden info line" not in text)
    failures += _check("detailed() is off", applog.detailed() is False)

    print("DETAILED LOG switches live")
    applog.set_detailed(True)
    logging.getLogger("app.tracking").debug("trace line one")
    failures += _check("DEBUG written once detailed", "DEBUG app.tracking: trace line one"
                       in _text(path))
    failures += _check("detailed() is on", applog.detailed() is True)
    logging.getLogger("urllib3.connectionpool").debug("library chatter")
    logging.getLogger("urllib3.connectionpool").warning("library warning")
    failures += _check("detailed covers app.* only: library DEBUG not written",
                       "library chatter" not in _text(path)
                       and "WARNING urllib3.connectionpool: library warning" in _text(path))
    applog.set_detailed(False)
    logging.getLogger("app.tracking").debug("trace line two")
    failures += _check("DEBUG stops when switched off", "trace line two" not in _text(path))

    print("Trace points in updater, sigsource and tracking (detailed only)")
    applog.set_detailed(True)
    sigsource.cached_data(base / "no-such-cache.json", "live")
    img = np.zeros((40, 40, 3), np.uint8)
    tracking.find_anchor_in_box(img, (0, 0, 2, 2), 1440)
    saved = updater.is_frozen, updater.latest_release
    try:
        updater.is_frozen = lambda: True
        updater.latest_release = lambda timeout=15.0: updater.Release(
            "9.9.9", "https://example.invalid/x.exe", 1, "", "")
        updater.check()
    finally:
        updater.is_frozen, updater.latest_release = saved
    src = sigsource.SignatureSource(cache_path=base / "sig.json",
                                    fetcher=lambda url, timeout: (_ for _ in ()).throw(
                                        OSError("offline")))
    src.refresh("live", force=True)
    text = _text(path)
    failures += _check("sigsource: fallback reason", "DEBUG app.sigsource: cache: none usable"
                       in text)
    failures += _check("sigsource: fetch and failure", "app.sigsource: fetch:" in text
                       and "refresh: failed, keeping the cache (OSError: offline)" in text)
    failures += _check("tracking: find_anchor_in_box result",
                       "DEBUG app.tracking: find_anchor_in_box:" in text)
    failures += _check("updater: check steps", "DEBUG app.updater: check: latest release 9.9.9"
                       in text)
    applog.set_detailed(False)
    mark = len(_text(path))
    sigsource.cached_data(base / "no-such-cache.json", "live")
    failures += _check("trace points silent when not detailed", len(_text(path)) == mark)

    print("Unhandled errors are logged too (the earlier hook still runs)")
    sys.excepthook(ValueError, ValueError("boom"), None)  # chained to the default hook
    t = threading.Thread(target=lambda: 1 / 0, name="probe-thread")
    stderr, sys.stderr = sys.stderr, open(os.devnull, "w")
    try:
        t.start()
        t.join()
    finally:
        sys.stderr.close()
        sys.stderr = stderr
    text = _text(path)
    failures += _check("sys.excepthook writes CRITICAL", "CRITICAL app.crash: unhandled ValueError"
                       in text)
    failures += _check("thread errors write CRITICAL",
                       "unhandled ZeroDivisionError in thread probe-thread" in text)

    print("setup is idempotent")
    applog.setup(folder, detailed=False)
    applog.setup(folder, detailed=True)
    failures += _check("one file handler after three setups", len(_handlers()) == 1,
                       str(len(_handlers())))
    failures += _check("setup(detailed=True) sets detailed", applog.detailed() is True)
    before = _text(path).count("once only")
    logging.getLogger("app.x").warning("once only")
    failures += _check("a line is written once", _text(path).count("once only") == before + 1)
    hooks = sys.excepthook
    applog.setup(folder, detailed=False)
    failures += _check("the crash hook is not stacked again", sys.excepthook is hooks)
    other = base / "other"
    applog.setup(other, detailed=False)
    failures += _check("a new folder replaces the handler", len(_handlers()) == 1
                       and applog.log_path() == other / "app.log")
    applog.setup(folder, detailed=False)

    print("Rotation at 1 MB keeps 3 backups")
    applog.set_detailed(True)
    chunk = "x" * 1000
    for i in range(5200):                      # ~5.2 MB
        logging.getLogger("app.fill").debug("%05d %s", i, chunk)
    applog._handler.flush()                    # type: ignore[union-attr]
    files = applog.log_files()
    names = [p.name for p in files]
    failures += _check("app.log, .1, .2, .3 newest first",
                       names == ["app.log", "app.log.1", "app.log.2", "app.log.3"], str(names))
    failures += _check("no fourth backup", not (folder / "app.log.4").exists())
    sizes = [p.stat().st_size for p in files]
    failures += _check("every file at most 1 MB", all(s <= applog.MAX_BYTES for s in sizes),
                       str(sizes))
    newest = (folder / "app.log").read_text(encoding="utf-8").splitlines()[-1]
    failures += _check("the last line is in app.log", " 05199 " in newest)
    applog.set_detailed(False)
    return failures


def _touch(path: Path, text: str = "x", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def check_export(base: Path) -> int:
    failures = 0
    print("EXPORT DIAGNOSTICS")
    folder = base / "full"
    applog.setup(folder, detailed=False)
    logging.getLogger("app.probe").warning("in the zip")
    for name in applog.DIAG_EXCLUDE:
        _touch(folder / name, "private")
    _touch(folder / "config.json", '{"debug_detailed_log": false}')
    _touch(folder / "error.log", "crash")
    _touch(folder / "scan_history.txt", "reads")
    for i in range(1, 4):
        _touch(folder / f"app.log.{i}", f"old {i}")
    now = time.time()
    for i in range(30):                        # bad_00 oldest .. bad_29 newest
        _touch(folder / "bad_reads" / f"bad_{i:02d}.png", "png", now - 1000 + i)
    entries = []
    for i in range(30):                        # index newest first: u_29 .. u_00
        name = f"u_{i:02d}.png"
        _touch(folder / "unmatched" / name, "png")
        entries.insert(0, {"value": i, "kind": "unknown", "time": now, "image": name})
    _touch(folder / "unmatched" / "index.json", json.dumps(entries))
    _touch(folder / "notes_backup" / "notes.txt", "private")     # excluded name in a folder
    monitors = ["DISPLAY1 5120x2160 @ (0, 0) scale 1.0", "DISPLAY2 1920x1080 @ (5120, 0)"]
    out = applog.export_diagnostics(base / "desk", folder, {"monitors": monitors})
    failures += _check("named 'SC Assistant diagnostics <date time>.zip'",
                       re.fullmatch(r"SC Assistant diagnostics \d{4}-\d\d-\d\d \d{6}\.zip",
                                    out.name) is not None, out.name)
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        system = z.read("system.txt").decode("utf-8") if "system.txt" in names else ""
        applog_text = z.read("app.log").decode("utf-8") if "app.log" in names else ""
    from app import version
    for name in ("config.json", "error.log", "scan_history.txt", "app.log", "app.log.1",
                 "app.log.2", "app.log.3", "unmatched/index.json"):
        failures += _check(f"includes {name}", name in names)
    failures += _check("app.log is flushed before zipping", "in the zip" in applog_text)
    failures += _check("system.txt: version and build",
                       version.VERSION in system and version.BUILD_DATE in system)
    failures += _check("system.txt: OS, Python, Qt",
                       "OS: " in system and "Python: " in system and "Qt: " in system)
    failures += _check("system.txt: monitors", all(m in system for m in monitors))
    bad = sorted(n for n in names if n.startswith("bad_reads/"))
    failures += _check("newest 20 bad_reads pictures",
                       bad == [f"bad_reads/bad_{i:02d}.png" for i in range(10, 30)], str(bad[:2]))
    unm = sorted(n for n in names if n.startswith("unmatched/") and n.endswith(".png"))
    failures += _check("newest 20 unmatched entries",
                       unm == [f"unmatched/u_{i:02d}.png" for i in range(10, 30)], str(unm[:2]))
    leaked = [n for n in names if Path(n).name in applog.DIAG_EXCLUDE]
    failures += _check("never the user's records (DIAG_EXCLUDE)", not leaked, str(leaked))
    failures += _check("DIAG_EXCLUDE lists the six files", set(applog.DIAG_EXCLUDE) == {
        "notes.txt", "inventory.json", "unlocked_blueprints.json", "refinery_jobs.json",
        "active_run.json", "workflow_wallet.json"})

    print("EXPORT DIAGNOSTICS with missing files")
    empty = base / "empty"
    empty.mkdir()
    zpath = base / "given.zip"
    try:
        got = applog.export_diagnostics(zpath, empty, {})
        with zipfile.ZipFile(got) as z:
            names = z.namelist()
        ok = got == zpath and names == ["system.txt"]
    except Exception as exc:
        ok, names = False, [repr(exc)]
    failures += _check("only system.txt, no error; a .zip target is used as given", ok, str(names))
    _touch(empty / "unmatched" / "index.json", "not json")
    for i in range(3):
        _touch(empty / "unmatched" / f"p{i}.png", "png", now - 10 + i)
    got = applog.export_diagnostics(base / "given2.zip", empty, {})
    with zipfile.ZipFile(got) as z:
        names = sorted(z.namelist())
    failures += _check("broken index.json: index + newest pictures",
                       names == ["system.txt", "unmatched/index.json", "unmatched/p0.png",
                                 "unmatched/p1.png", "unmatched/p2.png"], str(names))
    return failures


def main() -> int:
    base = Path(_TMP.name) / "work"
    base.mkdir()
    failures = check_logging(base) + check_export(base)
    root = logging.getLogger()
    for h in _handlers():                      # release app.log before the temp folder goes
        root.removeHandler(h)
        h.close()
    print("ALL CHECKS PASSED" if not failures else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
