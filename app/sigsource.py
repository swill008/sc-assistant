"""Signature data from scmdb.net game data, cached in the config folder.

scmdb.net publishes the game's mining data per build:

    https://scmdb.net/data/versions.json           [{"version": "4.10.2-live.12913470", "file": ...}, ...]
    https://scmdb.net/data/mining_data-<version>.json

Its mineableElements carry scanSignature (ship), groundScanSignature (ROC,
4,000) and fpsScanSignature (hand mining, 3,000). convert() turns that into
the shape of app/data/signatures.json; app.mining merges it with the bundled
file (short names, values, secondary ores, salvage).

Downloads only happen in a background thread (refresh_in_background), at most
once a day per channel, with short timeouts. A failed refresh keeps the cache
or the bundled file and leaves the reason in last_error.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

from .version import USER_AGENT

BASE_URL = "https://scmdb.net/data/"
VERSIONS_URL = BASE_URL + "versions.json"
CACHE_NAME = "signatures_scmdb.json"
REFRESH_SECONDS = 24 * 3600
TIMEOUT = 8.0
MAX_BYTES = 8 * 1024 * 1024
MIN_SHIP_ORES = 10          # fewer than this = not mining data we understand
CHANNELS = ("live", "ptu")

# scmdb names that differ from ours beyond the "(Ore)"/"(Raw)" suffix.
NAME_FIXES = {
    "quantainium": "Quantanium",
    "aluminium": "Aluminum",
}
RARITY = {"common": 2, "uncommon": 3, "rare": 4, "epic": 4, "legendary": 5}

_VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*)-([a-z]+)\.(\d+)$", re.I)
_FILE_RE = re.compile(r"^[\w.\-]+\.json$")

Fetcher = Callable[[str, float], bytes]

_log = logging.getLogger(__name__)


def clean_name(raw: str) -> str:
    name = re.sub(r"\s*\((?:ore|raw)\)\s*$", "", str(raw or ""), flags=re.I).strip()
    return NAME_FIXES.get(name.lower(), name)


def parse_version(version: str) -> tuple[tuple[int, ...], str, int] | None:
    """"4.10.2-live.12913470" -> ((4, 10, 2), "live", 12913470)."""
    m = _VERSION_RE.match(str(version or "").strip())
    if not m:
        return None
    nums = tuple(int(p) for p in m.group(1).split("."))
    return nums, m.group(2).lower(), int(m.group(3))


def pick_version(versions, channel: str = "live") -> dict | None:
    """Newest entry of versions.json for the channel (patch, then build)."""
    if isinstance(versions, dict):
        versions = next((v for v in versions.values() if isinstance(v, list)), [])
    best, best_key = None, None
    for entry in versions or []:
        if isinstance(entry, str):
            entry = {"version": entry}
        if not isinstance(entry, dict):
            continue
        parsed = parse_version(entry.get("version", ""))
        if parsed is None or parsed[1] != channel:
            continue
        key = (parsed[0], parsed[2])
        if best_key is None or key > best_key:
            best, best_key = entry, key
    return best


def data_url(entry: dict) -> str:
    """URL of an entry's mining data; never anything outside BASE_URL."""
    version = entry["version"]
    name = os.path.basename(str(entry.get("file") or ""))
    if not (name and _FILE_RE.match(name) and name.startswith("mining_data")):
        name = f"mining_data-{version}.json"
    return BASE_URL + name


def convert(mining: dict, version: str | None = None) -> dict:
    """scmdb mining_data -> our signatures shape (ship ores + ground lists)."""
    elements = mining.get("mineableElements") or {}
    items = elements.values() if isinstance(elements, dict) else elements
    ores: dict[str, dict] = {}
    fps: list[str] = []
    roc: list[str] = []
    for el in items:
        if not isinstance(el, dict):
            continue
        name = clean_name(el.get("name", ""))
        if not name or "(" in name:          # e.g. "Carinite (Pure)"
            continue
        ship = el.get("scanSignature")
        if isinstance(ship, (int, float)) and ship > 0 and name not in ores:
            ores[name] = {"name": name, "base": int(ship),
                          "rarity": RARITY.get(str(el.get("rarity", "")).lower(), 2)}
        if el.get("fpsScanSignature") and name not in fps:
            fps.append(name)
        if el.get("groundScanSignature") and name not in roc:
            roc.append(name)
    full = str(version or mining.get("version") or "")
    parsed = parse_version(full)
    return {
        "version": ".".join(map(str, parsed[0])) if parsed else full,
        "data_version": full,
        "channel": parsed[1] if parsed else "",
        "source": "scmdb.net",
        "ship_ores": sorted(ores.values(), key=lambda o: o["base"]),
        "ground": {"fps_minerals": sorted(fps), "roc_minerals": sorted(roc)},
    }


def valid(converted: dict | None) -> bool:
    return bool(converted) and len(converted.get("ship_ores", [])) >= MIN_SHIP_ORES


def http_get(url: str, timeout: float = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError(f"{url}: response too large")
    return body


def fetch(channel: str = "live", fetcher: Fetcher = http_get,
          timeout: float = TIMEOUT) -> dict:
    """Download and convert the newest data for the channel (raises on failure)."""
    _log.debug("fetch: %s (%s)", VERSIONS_URL, channel)
    versions = json.loads(fetcher(VERSIONS_URL, timeout))
    entry = pick_version(versions, channel)
    if entry is None:
        raise ValueError(f"no {channel} version on scmdb")
    converted = convert(json.loads(fetcher(data_url(entry), timeout)),
                        entry["version"])
    if not valid(converted):
        raise ValueError(f"scmdb {entry['version']}: no ship ores")
    _log.debug("fetch: scmdb %s, %d ship ores", entry["version"],
               len(converted.get("ship_ores", [])))
    return converted


def default_cache_path() -> Path:
    from .config import config_dir
    return config_dir() / CACHE_NAME


def read_cache(path: Path) -> dict | None:
    """{"fetched_at", "channel", "data"} or None when missing/unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not valid(raw.get("data")):
        return None
    return raw


def cached_data(path: Path, channel: str) -> dict | None:
    cache = read_cache(path)
    if cache is None:
        _log.debug("cache: none usable at %s, using the bundled data", path)
        return None
    if cache.get("channel") != channel:
        _log.debug("cache: holds %s, not %s, using the bundled data",
                   cache.get("channel"), channel)
        return None
    _log.debug("cache: using %s data from %s", channel, path)
    return cache["data"]


def needs_refresh(cache: dict | None, channel: str, now: float | None = None,
                  max_age: float = REFRESH_SECONDS) -> bool:
    if cache is None or cache.get("channel") != channel:
        return True
    try:
        age = (time.time() if now is None else now) - float(cache.get("fetched_at", 0))
    except (TypeError, ValueError):
        return True
    return age < 0 or age >= max_age


def write_cache(path: Path, channel: str, data: dict, now: float | None = None) -> None:
    payload = {"fetched_at": time.time() if now is None else now,
               "channel": channel, "data": data}
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, path)


class SignatureSource:
    """Background refresher of the scmdb cache (one refresh at a time)."""

    def __init__(self, cache_path: Path | None = None, fetcher: Fetcher = http_get):
        self._cache_path = cache_path
        self.fetcher = fetcher
        self.last_error = ""
        self.last_checked = 0.0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def cache_path(self) -> Path:
        if self._cache_path is None:
            self._cache_path = default_cache_path()
        return self._cache_path

    def cached(self, channel: str) -> dict | None:
        return cached_data(self.cache_path, channel)

    def refresh(self, channel: str, force: bool = False,
                now: float | None = None) -> bool:
        """Blocking refresh; True when a new cache was written. Never raises."""
        if channel not in CHANNELS:
            self.last_error = f"unknown channel {channel!r}"
            return False
        try:
            if not force and not needs_refresh(read_cache(self.cache_path), channel, now):
                _log.debug("refresh: %s cache is fresh, not fetching", channel)
                return False
            data = fetch(channel, self.fetcher)
            write_cache(self.cache_path, channel, data, now)
            _log.debug("refresh: %s cache written to %s", channel, self.cache_path)
            self.last_error = ""
            return True
        except Exception as exc:          # network, JSON, disk: keep what we have
            self.last_error = f"{type(exc).__name__}: {exc}"
            _log.debug("refresh: failed, keeping the cache (%s)", self.last_error)
            return False
        finally:
            self.last_checked = time.time() if now is None else now

    def refresh_in_background(self, channel: str,
                              on_done: Callable[[bool], None] | None = None,
                              force: bool = False) -> threading.Thread | None:
        """Start refresh() on a daemon thread; on_done(changed) runs on it.

        Returns None when a refresh is already running.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return None

            def run() -> None:
                changed = self.refresh(channel, force)
                if on_done is not None:
                    try:
                        on_done(changed)
                    except Exception:
                        pass

            self._thread = threading.Thread(target=run, name="signature-refresh",
                                            daemon=True)
            self._thread.start()
            return self._thread
