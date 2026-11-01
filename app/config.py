"""Persistent user settings, stored per OS outside OneDrive.

Windows: %APPDATA%\\SC Assistant
macOS:   ~/Library/Application Support/SC Assistant
Linux:   $XDG_CONFIG_HOME/SC Assistant (or ~/.config)

Older builds used an "SC-Overlay" folder; the user files are copied over on
first run so the region calibration and notes survive the rename.  Builds
before 1.0.0 were called Citizen Assistant; that folder is moved over once.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .version import APP_NAME, OLD_APP_NAME

log = logging.getLogger(__name__)

LEGACY_APP_NAMES = ("SC-Overlay",)
MIGRATE_FILES = ("config.json", "inventory.json", "unlocked_blueprints.json")

# Settings folder chosen for each base folder, so the move below runs once.
_RESOLVED: dict[Path, Path] = {}


def _migrate_legacy(base: Path, target: Path) -> None:
    """Copy user data from the pre-rename config folder, once."""
    for name in LEGACY_APP_NAMES:
        legacy = base / name
        if not legacy.is_dir():
            continue
        for fname in MIGRATE_FILES:
            old = legacy / fname
            new = target / fname
            if old.is_file() and not new.exists():
                try:
                    shutil.copy2(old, new)
                except OSError:
                    pass


def _is_empty_dir(path: Path) -> bool:
    try:
        return path.is_dir() and not any(path.iterdir())
    except OSError:
        return False


# ONE-TIME (rename to SC Assistant): move the "Citizen Assistant" settings
# folder to "SC Assistant" on the first start of 1.0.0.  Can go once no 1.2.x
# (Citizen Assistant) installs remain.
def _move_old_folder(base: Path) -> Path:
    """Return the settings folder to use, moving the old-name one if needed.

    Never deletes or overwrites user data: when both folders hold files the
    new one is used and the old one is left alone; when the folder cannot be
    renamed (a file held open) it is copied instead; when that fails too the
    old folder is used as it is and the move is tried again next start.
    """
    new = base / APP_NAME
    old = base / OLD_APP_NAME
    if not old.is_dir() or (new.exists() and not _is_empty_dir(new)):
        return new
    try:
        if new.is_dir():
            new.rmdir()
        os.replace(old, new)
        return new
    except OSError as exc:
        log.warning("Could not move %s to %s (%s); copying instead", old, new, exc)
    # Copy next to the target, then rename, so a failed copy never leaves a
    # half-filled new folder that a later start would take as the real one.
    tmp = base / f"{APP_NAME}.moving"
    try:
        if tmp.exists():
            shutil.rmtree(tmp)          # our own leftover copy, never user data
        shutil.copytree(old, tmp)
        if new.is_dir():
            new.rmdir()
        os.replace(tmp, new)
        return new
    except OSError as exc:
        log.warning("Could not copy %s to %s (%s); using %s for now",
                    old, new, exc, old)
        shutil.rmtree(tmp, ignore_errors=True)
        return old


def _base_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home())
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def config_dir() -> Path:
    base = _base_dir()
    d = _RESOLVED.get(base)
    if d is None:
        d = _RESOLVED[base] = _move_old_folder(base)
    d.mkdir(parents=True, exist_ok=True)
    _migrate_legacy(base, d)
    return d


CONFIG_PATH = config_dir() / "config.json"

DEFAULTS: dict = {
    "hotkey_toggle_nav": 0x72,          # VK_F3
    "hotkey_panic": 0x73,               # VK_F4 - hide everything
    # Optional hotkeys that open a tool directly (Settings → HOTKEYS):
    # {tool id: Windows virtual-key code}; 0 or missing = no hotkey.
    "hotkey_tools": {},
    "poll_ms": 250,                     # 4 reads a second; Settings → READS / S
    "stability_reads": 2,               # fallback reads before the value is shown
    "fast_single_read": True,           # high-confidence exact reads lock immediately
    "fast_confidence": 0.97,            # OCR confidence needed for the fast path
    # CPU threads the OCR model may use. 1 keeps every scan on the (low
    # priority) scanner thread, so it cannot take cores from the game.
    "ocr_threads": 1,
    # Close the mining scanner when Game.log reports leaving the pilot seat.
    "close_scanner_on_seat_exit": True,
    "scan_tuning_version": 2,           # migration marker for the poll_ms defaults
    "min_value": 2500,
    "max_value": 60000,
    "tolerance": 0.08,
    # Physical-pixel rectangle of the in-game signature readout.
    "region": None,
    # Qt name of the monitor the game runs on (Settings → GAME MONITOR).
    # None means "the monitor the box is on, else the primary monitor".
    "game_monitor": None,
    # Physical rect of that monitor when the box was drawn. If the monitor's
    # resolution or position changes later, the box is rescaled to match.
    "region_monitor": None,
    # HUD tracking (Settings → TRACKING): how far, in px either side, the
    # scanner follows the swaying signature plate, for a 2160-px-high monitor
    # (scaled by monitor height; vertical is 0.75x). 0 reads the fixed box.
    "tracking_range": 400,
    # Pin icon found left of the box at DRAW REGION (tracking.Anchor.save meta);
    # the picture is anchor.png in the config folder. None = fixed box only.
    "anchor": None,
    # Signature data: "scmdb" refreshes from scmdb.net game data (cached, the
    # bundled app/data/signatures.json is the fallback); "bundled" never
    # downloads. Channel picks the live servers or the test server (PTU).
    "signature_source": "scmdb",
    "signature_channel": "live",
    "show_debug_preview": False,
    # Draw an outline around the capture box on screen (Settings → SHOW BOX).
    # Off by default: any window over the game makes Windows composite it.
    "show_region_outline": False,
    "voice_enabled": True,             # speak the ore name when a scan locks
    "voice_volume": 0.8,               # 0.0 - 1.0
    # Forget the last spoken rock after this many seconds without a scan.
    # Brief HUD flicker keeps the dedupe, so the same rock is not re-announced.
    "voice_idle_reset_seconds": 12.0,
    "ui_scale": 1.0,                   # 0.75 - 1.5, applied on next launch
    "overlay_opacity": 1.0,            # 0.3 - 1.0, applies to overlay windows
    "nav_visible": True,
    "mining_panel_pos": None,
    "orefinder_pos": None,
    "hauling_pos": None,
    "inventory_pos": None,
    "uex_pos": None,
    "notes_pos": None,
    "combat_pos": None,
    "open_tools": [],
    # Panels pinned with their header pin (ui/pin_button.py): they stay on
    # screen when the overlay is hidden (F4 / the nav bar's ✕). Panel ids:
    # "mining", "orefinder", "hauling", "inventory", "uex", "notes",
    # "combat", "settings".
    "pinned_windows": [],
    "hauling_cargo": 32,              # SCU used for trip-profit maths
    "hauling_commodity": 0,           # 0 = all commodities / top routes
    "hauling_selection_version": 2,   # migration marker for the new default
    # True keeps the overlay out of screenshots/streams via
    # WDA_EXCLUDEFROMCAPTURE.  Visible by default so a normal screenshot or
    # screen share includes the panels; toggle it in Settings for stream privacy.
    "capture_exclude": False,
    "capture_visibility_version": 1,   # migration marker for the visible default
}


def open_folder(path) -> None:
    """Reveal a folder in the platform file manager."""
    target = str(path)
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


class Config:
    def __init__(self, data: dict | None = None):
        self.data = dict(DEFAULTS)
        if data:
            self.data.update({k: v for k, v in data.items() if k in DEFAULTS})

    @classmethod
    def load(cls) -> "Config":
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            # The trade-routes tab used to open on Aluminum. Migrate existing
            # configs once so it opens on the all-commodity top routes instead.
            try:
                version = int(data.get("hauling_selection_version", 1))
            except (TypeError, ValueError):
                version = 0
            if version < 2:
                data["hauling_commodity"] = 0
                data["hauling_selection_version"] = 2
            # Move existing installs from the old 250 ms scan cadence to the
            # faster default once. Custom values other than the old default
            # are left alone.
            try:
                scan_version = int(data.get("scan_tuning_version", 0))
            except (TypeError, ValueError):
                scan_version = 0
            if scan_version < 1:
                try:
                    old_poll = int(data.get("poll_ms", 250))
                except (TypeError, ValueError):
                    old_poll = 250
                if old_poll == 250:
                    data["poll_ms"] = 125
                data["scan_tuning_version"] = 1
            # 8 reads a second was the default before the OCR thread cap; 4 is
            # now the default (see README "Game performance"). Only the old
            # default moves; a value someone chose stays.
            if scan_version < 2:
                try:
                    if int(data.get("poll_ms", 125)) == 125:
                        data["poll_ms"] = 250
                except (TypeError, ValueError):
                    data["poll_ms"] = 250
                data["scan_tuning_version"] = 2
            # Capture exclusion used to be on by default with no UI toggle, so
            # existing installs could not screenshot the overlay at all.  Flip
            # that old default once; the new Settings toggle still lets anyone
            # hide the overlay from streams afterwards.
            try:
                capture_version = int(data.get("capture_visibility_version", 0))
            except (TypeError, ValueError):
                capture_version = 0
            if capture_version < 1:
                data["capture_exclude"] = False
                data["capture_visibility_version"] = 1
            return cls(data)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls()

    def save(self) -> None:
        tmp = CONFIG_PATH.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2)
            os.replace(tmp, CONFIG_PATH)
        except OSError:
            pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)
