"""Safe reads and writes for the user's own data files.

Shared by notes.txt, inventory.json, the blueprint registry and the ore-finder
cache.  The rules:

* Reads try UTF-8 (with or without a BOM), then Windows-1252 with unknown bytes
  replaced, so a file saved by another editor still opens.  A file that cannot
  be read at all (locked, no permission, broken JSON) gives ``LOAD_FAILED``,
  never an empty value: the caller must not save over a file it never read.
* Broken JSON is copied once to ``<name>.bad-<timestamp>`` so it can be
  recovered by hand.
* Writes go to a temporary file in the same folder and are renamed over the
  target.  The previous file is kept as ``<name>.bak``.  Windows file locks
  (an editor, a backup tool or a virus scanner holding the file) are retried a
  few times before giving up.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, NamedTuple, TypeVar

RETRIES = 5
RETRY_DELAY = 0.1  # seconds between attempts on a Windows file lock

BOM = b"\xef\xbb\xbf"
_MISSING = object()

T = TypeVar("T")


class _LoadFailed:
    """Sentinel: the file exists (or may exist) but could not be read."""

    _instance: "_LoadFailed | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "LOAD_FAILED"


LOAD_FAILED: Any = _LoadFailed()


class StoreNotLoaded(OSError):
    """Raised by a store asked to save after its file could not be read."""


class Loaded(NamedTuple):
    value: Any          # the text / JSON value, the default, or LOAD_FAILED
    error: str = ""     # why loading failed ("" when it did not)
    encoding: str = ""  # "utf-8", "utf-8-sig", "cp1252"; "" if not read


def _retry(action: Callable[[], T]) -> T:
    """Run *action*, retrying Windows sharing violations."""
    for attempt in range(RETRIES):
        try:
            return action()
        except PermissionError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(RETRY_DELAY)
    raise AssertionError("unreachable")


def decode(data: bytes) -> tuple[str, str]:
    """Return ``(text, encoding)``; never raises."""
    if data.startswith(BOM):
        return data[len(BOM):].decode("utf-8", errors="replace"), "utf-8-sig"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "cp1252"


def load_text(path: Path | str, default: Any = "") -> Loaded:
    """Read *path* as text.  Missing file -> *default*; failure -> LOAD_FAILED."""
    path = Path(path)
    try:
        data = _retry(path.read_bytes)
    except FileNotFoundError:
        return Loaded(default)
    except OSError as exc:
        return Loaded(LOAD_FAILED, f"Could not read {path.name}: {_reason(exc)}")
    text, encoding = decode(data)
    return Loaded(text, "", encoding)


def load_json(path: Path | str, default: Any = None) -> Loaded:
    """Read *path* as JSON.  Broken JSON is kept as ``<name>.bad-<time>``."""
    path = Path(path)
    loaded = load_text(path, default=_MISSING)
    if loaded.value is _MISSING:
        return Loaded(default)
    if loaded.value is LOAD_FAILED:
        return loaded
    try:
        value = json.loads(loaded.value)
    except ValueError as exc:
        kept = keep_bad_copy(path)
        where = f" (copy kept as {kept.name})" if kept else ""
        return Loaded(LOAD_FAILED,
                      f"{path.name} is damaged: {exc}{where}", loaded.encoding)
    return Loaded(value, "", loaded.encoding)


def read_text(path: Path | str, default: Any = "") -> Any:
    return load_text(path, default).value


def read_json(path: Path | str, default: Any = None) -> Any:
    return load_json(path, default).value


def keep_bad_copy(path: Path) -> Path | None:
    """Copy an unreadable file to ``<name>.bad-<timestamp>`` once.

    The original is left in place (nothing is ever saved over it while it is
    broken); an identical earlier copy is reused, so restarts don't pile up
    copies.
    """
    try:
        data = path.read_bytes()
        for old in sorted(path.parent.glob(path.name + ".bad-*")):
            try:
                if old.read_bytes() == data:
                    return old
            except OSError:
                continue
        target = path.with_name(
            f"{path.name}.bad-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, target)
        return target
    except OSError:
        return None


def backup_path(path: Path | str) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".bak")


def write_bytes(path: Path | str, data: bytes) -> None:
    """Atomic write with a ``.bak`` of the previous file.  Raises OSError."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                    dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            bak = backup_path(path)
            _retry(lambda: shutil.copy2(path, bak))
        _retry(lambda: os.replace(tmp, path))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def write_text(path: Path | str, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def write_json(path: Path | str, value: Any, *, indent: int | None = 2) -> None:
    write_text(path, json.dumps(value, indent=indent, ensure_ascii=False))


def _reason(exc: OSError) -> str:
    if isinstance(exc, PermissionError):
        return "the file is locked or access is denied"
    return exc.strerror or str(exc)
