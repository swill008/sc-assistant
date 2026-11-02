"""The app's log file, app.log in the settings folder.

``setup`` puts one rotating file handler on the root logger, so every
``logging.getLogger(__name__).warning(...)`` in app/ lands on disk, also in
the EXE where there is no console. Normally only WARNING and above are
written; DETAILED LOG (Settings -> DEBUG) adds the DEBUG trace lines and can
be switched while the app runs. Unhandled errors still go to error.log (the
hook in main); they are written here as well.

``export_diagnostics`` zips what is needed to look at a problem: versions,
monitors, config.json, the logs and the DEBUG files. It never takes the
user's own records (DIAG_EXCLUDE).
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import sys
import threading
import zipfile
from datetime import datetime
from pathlib import Path

LOG_NAME = "app.log"
MAX_BYTES = 1024 * 1024
BACKUPS = 3
FORMAT = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Files in the settings folder that hold the user's own records: never zipped.
DIAG_EXCLUDE = (
    "notes.txt",
    "inventory.json",
    "unlocked_blueprints.json",
    "refinery_jobs.json",
    "active_run.json",
    "workflow_wallet.json",
)
APP_LOGGER = "app"           # the package: app.main, app.tracking, ...
DIAG_FILES = ("config.json", "error.log", "scan_history.txt")
DIAG_NEWEST = 20            # pictures from bad_reads/ and unmatched/

_lock = threading.Lock()
_handler: logging.handlers.RotatingFileHandler | None = None
_detailed = False


def trace(name: str) -> logging.Logger:
    """A logger for trace lines (``.debug``), written only when detailed."""
    return logging.getLogger(name)


def _level() -> int:
    return logging.DEBUG if _detailed else logging.WARNING


def _apply_levels() -> None:
    """Detailed lines come from the app's own loggers ("app.*") only; other
    libraries stay at WARNING so their debug chatter never fills the log."""
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger(APP_LOGGER).setLevel(_level())
    if _handler is not None:
        _handler.setLevel(_level())


def setup(folder: Path, detailed: bool = False) -> Path:
    """Write the log to <folder>/app.log; safe to call again (one handler)."""
    global _handler, _detailed
    path = Path(folder) / LOG_NAME
    with _lock:
        _detailed = bool(detailed)
        root = logging.getLogger()
        wanted = os.path.normcase(os.path.abspath(path))
        if _handler is not None and os.path.normcase(_handler.baseFilename) != wanted:
            root.removeHandler(_handler)
            _handler.close()
            _handler = None
        if _handler is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            _handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
            _handler.setFormatter(logging.Formatter(FORMAT, DATE_FORMAT))
            root.addHandler(_handler)
        _apply_levels()
        _hook_unhandled()
    return path


def set_detailed(on: bool) -> None:
    """Switch DEBUG lines on or off for the running app."""
    global _detailed
    with _lock:
        _detailed = bool(on)
        _apply_levels()


def detailed() -> bool:
    return _detailed


def log_path() -> Path:
    """app.log in use (before setup: the one in the settings folder)."""
    if _handler is not None:
        return Path(_handler.baseFilename)
    from .config import config_dir
    return config_dir() / LOG_NAME


def log_files() -> list[Path]:
    """app.log and its rotated copies that exist, newest first."""
    current = log_path()
    names = [current] + [current.with_name(f"{current.name}.{i}")
                         for i in range(1, BACKUPS + 1)]
    return [p for p in names if p.is_file()]


def _hook_unhandled() -> None:
    """Also log unhandled errors (main's hook keeps writing error.log)."""
    if not getattr(sys.excepthook, "_applog", False):
        previous = sys.excepthook

        def hook(exc_type, exc, tb) -> None:
            logging.getLogger("app.crash").critical(
                "unhandled %s", getattr(exc_type, "__name__", exc_type),
                exc_info=(exc_type, exc, tb))
            previous(exc_type, exc, tb)

        hook._applog = True                     # type: ignore[attr-defined]
        sys.excepthook = hook
    if not getattr(threading.excepthook, "_applog", False):
        previous_thread = threading.excepthook

        def thread_hook(args) -> None:
            if args.exc_type is not SystemExit:
                name = args.thread.name if args.thread is not None else "?"
                logging.getLogger("app.crash").critical(
                    "unhandled %s in thread %s",
                    getattr(args.exc_type, "__name__", args.exc_type), name,
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
            previous_thread(args)

        thread_hook._applog = True              # type: ignore[attr-defined]
        threading.excepthook = thread_hook


# --- EXPORT DIAGNOSTICS ------------------------------------------------------

def _newest(paths, count: int = DIAG_NEWEST) -> list[Path]:
    files = []
    for p in paths:
        try:
            files.append((p.stat().st_mtime, p))
        except OSError:
            continue
    files.sort(key=lambda item: item[0], reverse=True)
    return [p for _, p in files[:count]]


def _unmatched_files(folder: Path) -> list[Path]:
    """index.json plus the pictures of its newest DIAG_NEWEST entries."""
    index = folder / "index.json"
    picked: list[Path] = []
    try:
        entries = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        entries = None
    if isinstance(entries, list):              # newest first, as UnmatchedLog keeps it
        for entry in entries[:DIAG_NEWEST]:
            name = entry.get("image") if isinstance(entry, dict) else None
            if isinstance(name, str) and name and Path(name).name == name:
                p = folder / name
                if p.is_file():
                    picked.append(p)
    else:                                       # no usable index: newest pictures
        picked = _newest(folder.glob("*.png")) if folder.is_dir() else []
    if index.is_file():
        picked.insert(0, index)
    return picked


def _summary(extra: dict) -> str:
    from . import version
    lines = [f"{version.APP_NAME} {version.VERSION} (build {version.BUILD_DATE})",
             f"Written: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
             f"OS: {platform.platform()}",
             f"Python: {sys.version.split()[0]} ({platform.architecture()[0]})",
             f"Frozen: {bool(getattr(sys, 'frozen', False))}"]
    try:
        import PySide6
        from PySide6.QtCore import qVersion
        lines.append(f"Qt: {qVersion()} (PySide6 {PySide6.__version__})")
    except Exception as exc:                    # no Qt in this process
        lines.append(f"Qt: unknown ({exc})")
    lines.append(f"Detailed log: {'on' if _detailed else 'off'}")
    monitors = extra.get("monitors")
    if monitors:
        lines.append("Monitors:")
        lines.extend(f"  {m}" for m in monitors)
    for key, value in extra.items():
        if key != "monitors":
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


def export_diagnostics(target: Path, folder: Path, extra: dict | None = None) -> Path:
    """Zip the diagnostics from settings folder ``folder``; returns the zip.

    ``target`` is the zip's path, or a folder to write
    "SC Assistant diagnostics <date time>.zip" in. Missing files are skipped.
    """
    from . import version
    extra = dict(extra or {})
    folder = Path(folder)
    target = Path(target)
    if target.suffix.lower() != ".zip":
        stamp = datetime.now().strftime("%Y-%m-%d %H%M%S")
        target = target / f"{version.APP_NAME} diagnostics {stamp}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    if _handler is not None:
        _handler.flush()

    wanted: list[Path] = [folder / name for name in DIAG_FILES]
    logs = folder / LOG_NAME
    wanted += [logs] + [logs.with_name(f"{LOG_NAME}.{i}") for i in range(1, BACKUPS + 1)]
    bad = folder / "bad_reads"
    if bad.is_dir():
        wanted += _newest(bad.glob("*.png"))
    wanted += _unmatched_files(folder / "unmatched")

    excluded = {name.lower() for name in DIAG_EXCLUDE}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("system.txt", _summary(extra))
        for p in wanted:
            if p.name.lower() in excluded or not p.is_file():
                continue
            try:
                bundle.write(p, p.relative_to(folder).as_posix())
            except (OSError, ValueError) as exc:
                logging.getLogger(__name__).warning(
                    "diagnostics: could not add %s (%s)", p, exc)
    return target
