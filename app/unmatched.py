"""Recorder for scan readings the app could not match.

Every confirmed reading with no exact match is kept (number, kind of scan,
time, a small PNG of the box) in <settings folder>/unmatched/, listed in
Settings → UNMATCHED READINGS. index.json holds the entries, newest first:

    [{"value": 76000, "kind": "unknown", "time": 1761998400.0,
      "image": "76000-20261101-143702-123.png"}, ...]

The same value again within REPEAT_SECONDS is not recorded (the HUD shows one
rock for many reads); only the newest MAX_ENTRIES are kept, older pictures are
deleted with them.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from . import safe_store

log = logging.getLogger(__name__)

INDEX_NAME = "index.json"
FOLDER_NAME = "unmatched"
MAX_ENTRIES = 200
REPEAT_SECONDS = 60.0


def _png_bytes(crop: Any) -> bytes | None:
    try:
        import cv2
        ok, buf = cv2.imencode(".png", crop)
    except Exception as exc:            # not an image cv2 understands
        log.warning("unmatched: could not encode the crop (%s)", exc)
        return None
    return buf.tobytes() if ok else None


class UnmatchedLog:
    def __init__(self, folder: Path | None = None):
        if folder is None:
            from .config import config_dir
            folder = config_dir() / FOLDER_NAME
        self.folder = Path(folder)
        self._lock = threading.Lock()

    @property
    def index_path(self) -> Path:
        return self.folder / INDEX_NAME

    def _load(self) -> list[dict] | None:
        """Entries newest first; None when index.json exists but can't be read."""
        value = safe_store.read_json(self.index_path, default=[])
        if value is safe_store.LOAD_FAILED:
            return None
        if not isinstance(value, list):
            return []
        return [e for e in value if isinstance(e, dict) and "value" in e]

    def entries(self) -> list[dict]:
        with self._lock:
            return list(self._load() or [])

    def record(self, value: int, kind: str, crop=None,
               when: float | None = None) -> bool:
        """Keep one unmatched reading; False when skipped (repeat or error)."""
        now = time.time() if when is None else float(when)
        with self._lock:
            entries = self._load()
            if entries is None:
                return False            # never save over an index we can't read
            for e in entries:
                try:
                    if (int(e["value"]) == int(value)
                            and abs(now - float(e.get("time", 0))) < REPEAT_SECONDS):
                        return False
                except (TypeError, ValueError):
                    continue
            image = ""
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                if crop is not None:
                    data = _png_bytes(crop)
                    if data is not None:
                        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
                        image = f"{int(value)}-{stamp}-{int(now * 1000) % 1000:03d}.png"
                        safe_store.write_bytes(self.folder / image, data)
                entry = {"value": int(value), "kind": str(kind), "time": now,
                         "image": image}
                entries.insert(0, entry)
                entries.sort(key=lambda e: float(e.get("time", 0)), reverse=True)
                kept, dropped = entries[:MAX_ENTRIES], entries[MAX_ENTRIES:]
                safe_store.write_json(self.index_path, kept)
            except OSError as exc:
                log.warning("unmatched: could not record %s (%s)", value, exc)
                return False
            for e in dropped:
                self._remove_image(e.get("image"))
            return True

    def clear(self) -> None:
        """Remove every entry and picture (the folder itself stays)."""
        with self._lock:
            if not self.folder.is_dir():
                return
            for path in self.folder.iterdir():
                if path.is_file() and (path.suffix.lower() == ".png"
                                       or path.name.startswith(INDEX_NAME)):
                    try:
                        path.unlink()
                    except OSError as exc:
                        log.warning("unmatched: could not remove %s (%s)", path, exc)

    def _remove_image(self, name) -> None:
        if not name:
            return
        path = self.folder / Path(str(name)).name
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("unmatched: could not remove %s (%s)", path, exc)
