"""Application entry point and controller."""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QEvent, QObject, QStandardPaths, Qt, QThread,
                            QTimer, Signal)
from PySide6.QtGui import (QAction, QColor, QFont, QGuiApplication, QIcon,
                           QKeySequence, QPainter, QPainterPath, QPixmap,
                           QShortcut)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import applog
from . import config as app_config
from . import display, win32
from .blueprints import BlueprintTracker
from .capture import is_region_valid
from .combat import CombatTracker
from .config import Config, config_dir, open_folder
from .game_log import GameLogMonitor
from .hotkeys import HotkeyThread
from .mining import MiningData
from .orefinder import LiveData
from .ui.combat_panel import CombatPanel
from .ui.hauling_panel import HaulingPanel
from .ui.inventory_panel import InventoryPanel
from .ui.log_viewer import LogViewer
from .ui.mining_panel import MiningPanel
from .ui.navbar import NavBar
from .ui.notes_panel import NotesPanel
from .ui.orefinder_panel import OreFinderPanel
from .ui.region_outline import RegionOutline
from .ui.region_selector import RegionSelector
from .ui.settings_panel import SECTION_IDS, SettingsPanel
from .ui.uex_panel import UexPanel
from .ui import theme
from .unmatched import UnmatchedLog
from .version import APP_NAME, MUTEX_NAME, OLD_MUTEX_NAME
from .version import label as version_label
from .voice import Voice, spoken_text

APP_TITLE = APP_NAME
ICON_PATH = Path(__file__).resolve().parents[1] / "app.ico"
log = logging.getLogger(__name__)

TOOLS = [
    {"id": "mining", "label": "MINING", "enabled": True,
     "hint": "Read scan signatures and identify the rock"},
    {"id": "orefinder", "label": "ORE FINDER", "enabled": True,
     "hint": "Where to mine each ore, live from scminer.rocks"},
    {"id": "hauling", "label": "HAULING", "enabled": True,
     "hint": "Trade routes, hauling contracts and the PPM planner"},
    {"id": "uex", "label": "UEX", "enabled": True,
     "hint": "Search the UEX player marketplace for items on sale"},
    {"id": "inventory", "label": "INVENTORY", "enabled": True,
     "hint": "Remember loot and supplies left at other stations"},
    {"id": "combat", "label": "COMBAT", "enabled": True,
     "hint": "Live kill, soft-death and destruction feed from Game.log"},
    {"id": "notes", "label": "NOTES", "enabled": True,
     "hint": "A notepad that saves itself"},
]
# HotkeyThread ids for "open this tool" hotkeys: TOOL_HOTKEY_BASE + index in
# TOOLS (1 = nav bar, 2 = hide all).
TOOL_HOTKEY_BASE = 100
# How long the DRAW REGION result stays on screen (even with SHOW BOX off).
CONFIRM_MS = 3000
# DRAW REGION grabs up to this many frames, this far apart (~0.5 s), and uses
# the first that shows the pin, so one blurred or tinted frame doesn't fail it.
DRAW_FRAMES = 5
DRAW_FRAME_MS = 120
# Seconds in a row the tracked plate must stay unreadable before the result
# border turns red ("noread"); single dropped frames never do.
NOREAD_SECONDS = 1.0
# Settings → DEBUG. SCAN HISTORY: the last HISTORY_KEEP reads, newest last, in
# <settings folder>/scan_history.txt, rewritten at most every HISTORY_WRITE_MS.
# SAVE BAD READS: a PNG of the digits when the tracked plate is on screen but
# unreadable, at most one per BAD_READ_SECONDS, the newest BAD_READS_KEEP kept.
HISTORY_NAME = "scan_history.txt"
HISTORY_KEEP = 50
HISTORY_WRITE_MS = 1000
BAD_READS_FOLDER = "bad_reads"
BAD_READS_KEEP = 200
BAD_READ_SECONDS = 1.0


class ScanHistory:
    """The last reads as text lines; flush() rewrites the (small) file."""

    def __init__(self, path: Path, keep: int = HISTORY_KEEP):
        self.path = Path(path)
        self.lines: deque[str] = deque(maxlen=keep)
        self.dirty = False

    def load(self) -> None:
        """Carry on from the lines already in the file."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            log.warning("scan history: could not read %s (%s)", self.path, exc)
            return
        self.lines.extend(line for line in text.splitlines() if line.strip())

    def add(self, line: str) -> None:
        self.lines.append(line)
        self.dirty = True

    def flush(self) -> None:
        if not self.dirty:
            return
        self.dirty = False
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:          # a full disk must not stop the scanner
            log.warning("scan history: could not write %s (%s)", self.path, exc)


def history_line(when: float, res, matches, confirmed: bool, shown: bool,
                 border: str | None, track: str | None) -> str:
    """One SCAN HISTORY line: time, read, confidence, top and second exact
    match, confirmed, shown, border result and track state."""
    stamp = datetime.fromtimestamp(when).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    value = getattr(res, "value", None)
    read = f"{int(value):,}" if value is not None else "—"
    try:
        conf = f"{float(getattr(res, 'confidence', 0.0)):.2f}"
    except (TypeError, ValueError):
        conf = "?"

    def name(m) -> str:
        return f"{m.label} ×{m.count}"
    top = matches[0] if matches else None
    top_text = f"{name(top)} {'exact' if top.exact else '~'}" if top is not None else "none"
    second = next((m for m in (matches or [])[1:] if m.exact), None)
    second_text = name(second) if second is not None else "none"
    return (f"{stamp} | read {read} | conf {conf} | top {top_text} | 2nd {second_text}"
            f" | confirmed {'yes' if confirmed else 'no'} | shown {'yes' if shown else 'no'}"
            f" | border {border or 'none'} | track {track or 'none'}")


def save_bad_read(folder: Path, crop, when: float, track: dict | None,
                  seq: int, keep: int = BAD_READS_KEEP) -> Path | None:
    """Write the crop as PNG (time and track info in the name), then delete
    all but the newest ``keep`` pictures. None when it could not be saved."""
    try:
        import cv2
        ok, buf = cv2.imencode(".png", crop)
    except Exception as exc:            # not an image cv2 understands
        log.warning("bad reads: could not encode the crop (%s)", exc)
        return None
    if not ok:
        return None
    stamp = datetime.fromtimestamp(when).strftime("%Y%m%d-%H%M%S-%f")[:-3]
    info = (track or {}).get("state") or "none"
    digits = (track or {}).get("digits") or {}
    if digits:
        info += (f"-x{digits.get('left')}-y{digits.get('top')}"
                 f"-{digits.get('width')}x{digits.get('height')}")
    path = Path(folder) / f"{stamp}-{seq:06d}-{info}.png"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.tobytes())
        # Names start with the time, so name order is age order.
        old = sorted(path.parent.glob("*.png"))[:-keep] if keep > 0 else []
        for extra in old:
            extra.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("bad reads: could not save %s (%s)", path, exc)
        return None
    return path


# ---------------------------------------------------------------------------
class ScanThread(QThread):
    """Grabs the calibrated region, OCRs it and resolves the signature."""

    result = Signal(object, object)   # OCRResult, list[Match]
    failed = Signal(str)
    # Physical rect of the digits read this frame while tracking, None when
    # the plate was not found or tracking is off. Emitted on change only.
    tracked = Signal(object)
    # {"state": "locked"|"searching"|"fixed", "digits": rect|None,
    #  "pin": rect|None}: physical rects, on change only. locked = the pin
    # was found and the digits beside it read; searching = tracking is on but
    # no plate this read; fixed = no pin or TRACKING OFF (the drawn box).
    track_state = Signal(object)
    # (meta, Anchor | error text) for request_anchor(): the saved pin is
    # decoded here so OpenCV never loads on the GUI thread at start-up.
    anchor_loaded = Signal(object, object)
    # (plate crop, pin rect, digits rect) while locked with a saved plate:
    # the whole signature window for the Settings preview, rects (x, y, w, h)
    # in crop pixels. None (on change only) when there is none. Emitted
    # before that frame's result.
    plate_view = Signal(object)

    _NO_ANCHOR = object()     # configure(): leave the anchor/plate as it is

    def __init__(self, data: MiningData, cfg: Config, demo: bool = False,
                 anchor=None, parent=None):
        super().__init__(parent)
        self.data = data
        self.demo = demo
        self._region = cfg["region"]
        self._enabled = True
        self._stop = False
        self._interval = int(cfg["poll_ms"])
        self._min_value = int(cfg["min_value"])
        self._max_value = int(cfg["max_value"])
        self._tolerance = float(cfg["tolerance"])
        self._ocr_threads = int(cfg.get("ocr_threads", 1))
        self._last_hash: int | None = None
        self._last_payload: tuple | None = None
        self._tracking_range = parse_tracking_range(cfg.get("tracking_range"))
        self._anchor = anchor
        self._plate = parse_plate(cfg.get("plate"))
        self._plate_shown = False
        self._anchor_request: tuple | None = None
        self._last_track_state: dict | None = None
        # (anchor, physical search area), or None for the fixed box. Swapped
        # as one object so the scanner thread never sees half an update.
        self._track: tuple | None = None
        self._last_tracked: dict | None = None
        self._update_track()

    # -- setters are called from the GUI thread -------------------------
    def configure(self, region=None, interval_ms=None, tolerance=None,
                  tracking_range=None, anchor=_NO_ANCHOR, plate=_NO_ANCHOR) -> None:
        """``anchor=None`` turns tracking off; leave it out to keep it.
        ``plate``: the signature window as (dx, dy, w, h) from the anchor's
        template, None for no plate preview; leave it out to keep it."""
        if region is not None:
            self._region = region
        if interval_ms is not None:
            self._interval = max(50, int(interval_ms))
        if tolerance is not None:
            self._tolerance = float(tolerance)
        if tracking_range is not None:
            self._tracking_range = max(0, int(tracking_range))
        if anchor is not ScanThread._NO_ANCHOR:
            self._anchor = anchor
        if plate is not ScanThread._NO_ANCHOR:
            self._plate = parse_plate(plate)
        if region is not None or tracking_range is not None \
                or anchor is not ScanThread._NO_ANCHOR or plate is not ScanThread._NO_ANCHOR:
            self._update_track()

    def _update_track(self) -> None:
        # The range is set for a 2160-px-high monitor; the HUD scales with
        # height, so does the range. Worked out here, not per frame.
        if self._anchor is None or self._tracking_range <= 0 \
                or not is_region_valid(self._region):
            self._track = None
            return
        from . import tracking

        screen = display.screen_of_region(self._region)
        mon = display.physical_rect(screen) if screen is not None else None
        height = (mon or {}).get("height") or 2160
        rx = round(self._tracking_range * height / 2160)
        area = tracking.search_area(self._region, rx, round(0.75 * rx))
        self._track = (self._anchor, _clip(area, mon), self._plate)

    @property
    def tracking(self) -> bool:
        return self._track is not None

    @property
    def has_anchor(self) -> bool:
        return self._anchor is not None

    def request_anchor(self, folder: Path, meta: dict) -> None:
        """Decode the saved pin on the scanner thread; anchor_loaded follows."""
        self._anchor_request = (Path(folder), dict(meta))

    def _load_requested_anchor(self) -> None:
        req, self._anchor_request = self._anchor_request, None
        if req is None:
            return
        folder, meta = req
        try:
            from . import tracking

            anchor = tracking.Anchor.load(folder, meta)
            result = anchor if anchor is not None else                 "the saved pin image could not be read"
        except Exception as exc:
            result = f"{type(exc).__name__}: {exc}"
        self.anchor_loaded.emit(meta, result)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def stop(self) -> None:
        self._stop = True

    def resume(self) -> None:
        """Start again after stop() (RESET SETTINGS failed)."""
        self._stop = False
        if not self.isRunning():
            self.start(QThread.Priority.LowPriority)

    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: D102
        # numpy, OpenCV and the OCR model are loaded only when there is an
        # active region or demo frame, so a fresh install (no region until
        # DRAW REGION) does not pay that cost at launch.
        grabber = None
        ocr = None
        demo_mod = None
        try:
            while not self._stop:
                started = time.perf_counter()
                if self._anchor_request is not None:
                    self._load_requested_anchor()
                region = self._region
                active = self.demo or (self._enabled and is_region_valid(region))
                if not active:
                    # Paused or no box: nothing is tracked. Forget the last
                    # state so the next active read reports it again.
                    self._set_tracked(None)
                    self._last_track_state = None
                if active:
                    try:
                        if self.demo and demo_mod is None:
                            from . import demo as demo_mod
                        if grabber is None:
                            from .capture import ScreenGrabber
                            grabber = ScreenGrabber()
                        if ocr is None:
                            from .ocr import SignatureOCR
                            ocr = SignatureOCR(self._min_value,
                                               self._max_value,
                                               threads=self._ocr_threads)
                    except Exception as exc:
                        self.failed.emit(f"Scanner unavailable: {exc}")
                        return

                    try:
                        if self.demo:
                            self._read_crop(demo_mod.signature_crop(), ocr)
                        else:
                            self.scan_once(grabber.grab, ocr, region)
                    except Exception as exc:  # keep the loop alive
                        self.failed.emit(str(exc))
                elapsed = (time.perf_counter() - started) * 1000.0
                self.msleep(max(25, int(self._interval - elapsed)))
        finally:
            if grabber is not None:
                grabber.close()

    def scan_once(self, grab, ocr, region: dict) -> None:
        """One poll: grab, (track,) OCR and emit. ``grab(rect)`` returns BGR."""
        track = self._track
        if track is None:
            self._set_tracked(None)
            self._set_track_state("fixed")
            self._set_plate_view(None)
            self._read_crop(grab(region), ocr)
            return
        from . import tracking

        anchor, area, plate = track
        frame = grab(area)
        match = tracking.locate(frame, anchor)
        if match is None:
            # No plate on screen: nothing to read, so the OCR model is not run.
            self._set_tracked(None)
            self._set_plate_view(None)
            self._set_track_state("searching")
            if self._last_hash != -1:
                from .ocr import OCRResult

                self._last_hash = -1      # never a real crop hash
                self._last_payload = (OCRResult(raw="no plate"), [])
            self.result.emit(*self._last_payload)
            return
        x, y, w, h = tracking.digits_rect(match, anchor)
        fh, fw = frame.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(fw, x + w), min(fh, y + h)
        if x1 - x0 < 8 or y1 - y0 < 8:
            # Plate at the edge of the search area: the digits are cut off.
            self._set_tracked(None)
            self._set_track_state("searching")
            self._set_plate_view(None)
            self._read_crop(None, ocr)
            return
        digits = {"left": int(area["left"] + x0), "top": int(area["top"] + y0),
                  "width": int(x1 - x0), "height": int(y1 - y0)}
        self._set_tracked(digits)
        self._set_track_state("locked", digits,
                              pin_rect(match, anchor, area["left"], area["top"]))
        self._set_plate_view(None if plate is None else
                             plate_view(frame, match, anchor, plate, (x0, y0, x1 - x0, y1 - y0)))
        self._read_crop(frame[y0:y1, x0:x1], ocr)

    def _read_crop(self, crop, ocr) -> None:
        if crop is None:
            from .ocr import OCRResult

            self._last_hash = None
            self._last_payload = None
            self.result.emit(OCRResult(raw="no plate"), [])
            return
        # A static screen means the OCR result cannot change; re-running the
        # model would only burn CPU.
        digest = hash((crop.shape, crop.tobytes()))
        if digest == self._last_hash and self._last_payload is not None:
            self.result.emit(*self._last_payload)
            return
        res = ocr.read(crop)
        matches = self.data.lookup(res.value, self._tolerance) if res.ok else []
        self._last_hash = digest
        self._last_payload = (res, matches)
        self.result.emit(res, matches)

    def _set_tracked(self, rect: dict | None) -> None:
        if rect != self._last_tracked:
            self._last_tracked = rect
            self.tracked.emit(rect)

    def _set_plate_view(self, view) -> None:
        # Every locked frame (the picture changes); None once per change.
        if view is not None or self._plate_shown:
            self._plate_shown = view is not None
            self.plate_view.emit(view)

    def _set_track_state(self, state: str, digits: dict | None = None,
                         pin: dict | None = None) -> None:
        info = {"state": state, "digits": digits, "pin": pin}
        if info != self._last_track_state:
            self._last_track_state = info
            self.track_state.emit(info)


def pin_rect(match, anchor, left: int, top: int) -> dict:
    """Physical rect of the pin icon itself (the template less its margin)
    for a match found in an image whose top-left is at (left, top)."""
    from .tracking import PIN_MARGIN

    th, tw = anchor.template.shape[:2]
    return {"left": int(left + match.x + PIN_MARGIN),
            "top": int(top + match.y + PIN_MARGIN),
            "width": int(tw - 2 * PIN_MARGIN),
            "height": int(th - 2 * PIN_MARGIN)}


def plate_view(frame, match, anchor, plate, digits) -> tuple | None:
    """(crop, pin, digits) for the Settings preview: the saved signature
    window cut from ``frame`` at the pin ``match`` (clipped to the frame), and
    the pin and ``digits`` ((x, y, w, h) in ``frame``) relative to that crop."""
    from .tracking import PIN_MARGIN

    pdx, pdy, pw, ph = plate
    fh, fw = frame.shape[:2]
    x0, y0 = max(0, match.x + pdx), max(0, match.y + pdy)
    x1, y1 = min(fw, match.x + pdx + pw), min(fh, match.y + pdy + ph)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    th, tw = anchor.template.shape[:2]
    pin = (match.x + PIN_MARGIN - x0, match.y + PIN_MARGIN - y0,
           tw - 2 * PIN_MARGIN, th - 2 * PIN_MARGIN)
    # The green box is the part the reader actually reads (the bright digits
    # inside the read area), so it sits on the number, not on the wider area
    # worked out from the pin. None when no digits stand out.
    import cv2

    from .ocr import SignatureOCR

    dx, dy, dw, dh = digits
    ax0, ay0 = max(0, dx), max(0, dy)
    area = frame[ay0:min(fh, dy + dh), ax0:min(fw, dx + dw)]
    found = None
    if area.size:
        box = SignatureOCR.digit_box(cv2.cvtColor(area, cv2.COLOR_BGR2GRAY))
        if box is not None:
            bx, by, bw, bh = box
            found = (ax0 + bx - x0, ay0 + by - y0, bw, bh)
    return frame[y0:y1, x0:x1].copy(), pin, found


def parse_plate(value) -> tuple[int, int, int, int] | None:
    """Config "plate" ({"dx", "dy", "w", "h"}) as a tuple; None when unset,
    hand-edited or broken."""
    if isinstance(value, dict):
        value = tuple(value.get(k) for k in ("dx", "dy", "w", "h"))
    if not isinstance(value, (tuple, list)) or len(value) != 4 \
            or any(isinstance(v, bool) for v in value):
        return None
    try:
        dx, dy, w, h = (int(v) for v in value)
    except (TypeError, ValueError, OverflowError):
        return None
    return (dx, dy, w, h) if w >= 8 and h >= 8 else None


def parse_tracking_range(value, default: int = 400) -> int:
    """TRACKING range from config: a whole number of px >= 0. A hand-edited
    or broken value falls back to ``default`` instead of crashing."""
    if value is None or isinstance(value, bool):
        return default
    try:
        return max(0, int(round(float(value))))
    except (TypeError, ValueError, OverflowError):
        return default


def _vk(value) -> int:
    """A Windows virtual-key code from config, 0 when unset or broken."""
    if isinstance(value, bool):
        return 0
    try:
        vk = int(value)
    except (TypeError, ValueError):
        return 0
    return vk if 0 < vk < 256 else 0


# ---------------------------------------------------------------------------
_NO_PIN_NOTE = ("No pin icon found in or next to the box: tracking is off. "
                "Press DRAW REGION around the whole signature window to turn it on.")
_TRACKING_DROPPED = (" Tracking is off (the saved pin was for the old "
                     "resolution): it turns back on by itself when the box "
                     "next reads a signature; if not, press DRAW REGION to "
                     "turn it back on.")
_PIN_SEARCH_FAILED_NOTE = ("Pin search failed ({}): tracking is off. Press DRAW "
                           "REGION to try again.")
_PIN_MISSING_NOTE = ("The saved pin picture (anchor.png) is missing: tracking "
                     "is off until the box reads a signature, or press DRAW "
                     "REGION.")
_PIN_LOAD_FAILED_NOTE = ("Could not load the saved pin ({}): tracking is off "
                         "until the box reads a signature, or press DRAW "
                         "REGION.")
_PIN_LEARNED_NOTE = "Pin learned from the scan: tracking is on."


def _calibration_area(region: dict) -> dict:
    """Screen around a drawn box to look for the pin in: 4 box heights each
    side, kept on the box's monitor."""
    pad = 4 * int(region["height"])
    area = {"left": region["left"] - pad, "top": region["top"] - pad,
            "width": region["width"] + 2 * pad, "height": region["height"] + 2 * pad}
    screen = display.screen_of_region(region)
    return _clip(area, display.physical_rect(screen) if screen is not None else None)


def _clip(area: dict, mon: dict | None) -> dict:
    """``area`` cut to the monitor rect (unchanged when ``mon`` is None)."""
    if mon is None:
        return area
    left = max(area["left"], mon["left"])
    top = max(area["top"], mon["top"])
    right = min(area["left"] + area["width"], mon["left"] + mon["width"])
    bottom = min(area["top"] + area["height"], mon["top"] + mon["height"])
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def _tray_icon(size: int = 64) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    k = size / 64.0
    path = QPainterPath()
    path.moveTo(32 * k, 6 * k)
    path.lineTo(58 * k, 32 * k)
    path.lineTo(32 * k, 58 * k)
    path.lineTo(6 * k, 32 * k)
    path.closeSubpath()
    pen = p.pen()
    pen.setColor(QColor(79, 209, 224))
    pen.setWidthF(max(1.0, size / 64.0))
    p.setPen(pen)
    p.setBrush(QColor(16, 26, 34))
    p.drawPath(path)
    p.setPen(QColor(232, 240, 248))
    p.setFont(QFont(theme.UI_FAMILY, max(5, int(round(20 * k))),
                     QFont.Weight.Bold))
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "CA")
    p.end()
    return QIcon(pix)


def _install_crash_log() -> Path:
    """Keep unhandled errors on disk when launched with pythonw (no console)."""
    path = config_dir() / "error.log"

    def hook(exc_type, exc, tb) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"[{stamp}] {getattr(exc_type, '__name__', exc_type)}: {exc}\n")
                fh.write("".join(traceback.format_exception(exc_type, exc, tb)))
                fh.write("\n")
        except OSError:
            pass

    sys.excepthook = hook
    return path


_MUTEX_HANDLE = None        # held open for the life of the process


# ONE-TIME (rename to SC Assistant): a Citizen Assistant (1.2.x or older) copy
# still running would fight this one for F3/F4, so refuse to start while its
# mutex exists. Can go once no 1.2.x installs remain.
def _old_name_running(kernel32) -> bool:
    handle = kernel32.OpenMutexW(0x00100000, False,     # SYNCHRONIZE
                                 f"Local\\{OLD_MUTEX_NAME}")
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def _acquire_single_instance(replacing: bool = False) -> bool:
    """Windows named mutex: only one overlay may own the global hotkeys.

    A second copy would start with every window in place but could not
    register F3/F4, so pressing them would appear to do nothing.
    """
    global _MUTEX_HANDLE
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                      wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                    wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE

    name = f"Local\\{MUTEX_NAME}"
    # Restarting ourselves spawns the new copy before this one quits, so the
    # replacement waits for the old process to let go of the mutex.
    deadline = time.monotonic() + (10.0 if replacing else 0.0)
    while True:
        if _old_name_running(kernel32):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.25)
            continue
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            return True             # no mutex: never block the app
        if ctypes.get_last_error() != 183:     # ERROR_ALREADY_EXISTS
            _MUTEX_HANDLE = handle
            return True
        kernel32.CloseHandle(handle)
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def _already_running_notice() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.user32.MessageBoxW(
        None,
        f"{APP_NAME} is already running.\n\n"
        "Use its tray icon, or press F3 to show the nav bar.\n\n"
        f"This copy is {version_label()}. If the running copy is older, "
        "quit it from the tray and start this one.",
        APP_TITLE,
        0x00000040)                 # MB_ICONINFORMATION


# ---------------------------------------------------------------------------
def _saved_pos(value) -> tuple[int, int] | None:
    """A saved [x, y] window position, or None when missing or malformed."""
    if isinstance(value, list) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _rect_distance(rect, point) -> int:
    """Squared distance from point to rect (0 inside it)."""
    dx = max(rect.left() - point.x(), 0, point.x() - rect.right())
    dy = max(rect.top() - point.y(), 0, point.y() - rect.bottom())
    return dx * dx + dy * dy


def fit_on_screen(widget) -> None:
    """Move a window fully onto the nearest connected screen (logical px).

    Nearest: the screen whose available area holds the window's centre, else
    the one closest to it. A window larger than that area is aligned by its
    top-left. A window already fully on a screen is not moved.
    """
    frame = widget.frameGeometry()
    screens = QGuiApplication.screens()
    if not screens:
        return
    centre = frame.center()
    geo = min((sc.availableGeometry() for sc in screens),
              key=lambda g: _rect_distance(g, centre))
    if geo.contains(frame):
        return
    x = max(geo.left(), min(frame.left(), geo.right() - frame.width() + 1))
    y = max(geo.top(), min(frame.top(), geo.bottom() - frame.height() + 1))
    widget.move(widget.x() + x - frame.left(), widget.y() + y - frame.top())


# Errors already logged by _warn_once (key), so a timer that fails every
# tick (topmost every 2 s) writes one line, not one a tick.
_WARNED: set = set()


def _warn_once(key, message: str, *args) -> None:
    if key in _WARNED:
        return
    _WARNED.add(key)
    log.warning(message, *args)


def _desktop_dir() -> Path | None:
    """The user's Desktop folder, or None when there is none."""
    found = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DesktopLocation)
    path = Path(found) if found else Path.home() / "Desktop"
    return path if path.is_dir() else None


def diagnostics_target() -> tuple[Path, str]:
    """EXPORT DIAGNOSTICS: (zip path, where in words): the Desktop when it
    exists, else the settings folder."""
    stamp = datetime.now().strftime("%Y-%m-%d %H%M%S")
    name = f"{APP_NAME} diagnostics {stamp}.zip"
    desktop = _desktop_dir()
    if desktop is not None:
        return desktop / name, "the Desktop"
    return config_dir() / name, "the settings folder"


def _monitor_lines() -> list[str]:
    lines = []
    primary = QGuiApplication.primaryScreen()
    for screen in QGuiApplication.screens():
        g = screen.geometry()
        lines.append(f"{screen.name()}: {g.width()}x{g.height()} at {g.x()},{g.y()}, "
                     f"scale {screen.devicePixelRatio():g}"
                     + (" (primary)" if screen is primary else ""))
    return lines


def start_logging(folder: Path | None = None, detailed: bool = False) -> Path | None:
    """app.log in the settings folder (app/applog.py); None if it cannot
    be opened (the app runs on without it)."""
    try:
        return applog.setup(folder if folder is not None else config_dir(), detailed)
    except OSError as exc:
        print(f"app.log unavailable: {exc}", file=sys.stderr)
        return None


def _startup_config() -> Config:
    """main(): app.log first, so anything that warns from here on (reading
    the settings included) is on disk, then the settings, then the DETAILED
    LOG choice from them."""
    start_logging(config_dir())
    cfg = Config.load()
    applog.set_detailed(bool(cfg.get("debug_detailed_log")))
    log.debug("starting %s %s", APP_NAME, version_label())
    return cfg


class _WindowWatcher(QObject):
    """Event filter on the tool windows and Settings: any move, show or hide
    restarts a short timer, so a position is saved once the window stops."""

    _EVENTS = (QEvent.Type.Move, QEvent.Type.Show, QEvent.Type.Hide)

    def __init__(self, on_change, parent: QObject):
        super().__init__(parent)
        self._on_change = on_change

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() in self._EVENTS:
            self._on_change()
        return False


class OverlayApp(QObject):
    # Host-facing headless bridges.  The trackers never create windows; the
    # host decides whether to render a toast, update a HUD layer, or ignore it.
    combat_event = Signal(object)
    blueprint_unlocked_signal = Signal(object)
    inventory_event_signal = Signal(object)
    # Re-emitted from the Game.log tailer's thread so the GUI can react.
    pilot_seat = Signal(bool)
    # MiningData.refresh_in_background finished (worker thread): changed?
    data_refreshed = Signal(bool)

    def __init__(self, app: QApplication, cfg: Config, demo: bool = False,
                 capture_visible: bool = False, launch_args: list[str] | None = None):
        super().__init__()
        self.app = app
        self.cfg = cfg
        self.demo = demo
        self.capture_visible = capture_visible
        self._launch_args = list(launch_args or [])

        self.data = MiningData()
        self.voice = Voice()
        self._spoken_key: tuple | None = None
        self._spoken_value: int | None = None
        self._selector: RegionSelector | None = None
        self._recent: deque[int] = deque(maxlen=max(1, int(cfg["stability_reads"])))
        self._last_value: int | None = None
        self._last_matches = []
        self._last_good_at = 0.0
        self._last_res = None
        self._paused = False
        self._last_match_name = ""
        self._init_result_state()
        self._init_debug_state()
        # RESET SETTINGS in progress: nothing may write the old settings back.
        self._resetting = False
        # QUIT or dispose ran: the debounced window save is off for good.
        self._closed = False
        # Settings has a real position (restored or placed when opened); until
        # then its x/y are meaningless and "settings_pos" is not written.
        self._settings_placed = False
        self.unmatched = UnmatchedLog()

        self.nav = NavBar(TOOLS)
        self.panel = MiningPanel()
        self.settings = SettingsPanel()
        self.outline = RegionOutline()
        self.ore_data = LiveData()
        self.orefinder = OreFinderPanel(self.ore_data)
        self.hauling = HaulingPanel()
        self.inventory = InventoryPanel()
        self.uex = UexPanel()
        self.notes = NotesPanel()

        # Headless combat feed: the tracker stays Qt-free; this panel only
        # renders the structured events it forwards.
        self.combat = CombatTracker()
        self.combat.subscribe(self._on_combat_event)
        self.combat_panel = CombatPanel(self.combat)

        # Headless blueprint/inventory feed.  The log watcher owns matching;
        # the registry worker owns JSON reads and writes.
        self.blueprint_tracker = BlueprintTracker()
        self.blueprint_tracker.subscribe(self._on_inventory_event)

        self._init_tracking_state()
        # No anchor yet: the saved pin is decoded on the scanner thread after
        # the windows are up (start -> _load_anchor), never on the GUI thread.
        self.scan = ScanThread(self.data, cfg, demo=demo)
        self.scan.result.connect(self._on_result)
        self.scan.failed.connect(self._on_scan_error)
        self.scan.tracked.connect(self._on_tracked)
        self.scan.track_state.connect(self._on_track_state)
        self.scan.anchor_loaded.connect(self._on_anchor_loaded)
        self.scan.plate_view.connect(self._on_plate_view)

        self.hotkeys = HotkeyThread(self._hotkey_bindings())
        self.hotkeys.pressed.connect(self._on_hotkey)

        # Read-only Game.log tailer for pilot-seat notifications, so the
        # scanner can close when the player stands up. Nothing touches the
        # game process; the monitor only reads text.
        self.game_log = GameLogMonitor(callback=self._on_game_log_event)
        self.pilot_seat.connect(self._on_pilot_seat)
        self.data_refreshed.connect(self._on_data_refreshed)

        self._build_tray()
        self._wire()
        self.app.aboutToQuit.connect(self.hauling.shutdown)
        self.app.aboutToQuit.connect(self.combat.close)
        self.app.aboutToQuit.connect(self.blueprint_tracker.close)
        # Last chance to write the notepad before the process exits.
        self.app.aboutToQuit.connect(self.notes.flush)
        self.app.aboutToQuit.connect(self.game_log.stop)

        self._freshness = QTimer(self)
        self._freshness.setInterval(500)
        self._freshness.timeout.connect(self._check_freshness)

        # Re-assert topmost periodically: games and browsers can out-stack a
        # NOACTIVATE window, which previously left the bar hidden behind Chrome.
        self._topmost = QTimer(self)
        self._topmost.setInterval(2000)
        self._topmost.timeout.connect(self._assert_topmost)

        # Window positions and open tools are saved about a second after a
        # window stops moving or is shown/hidden, not only on QUIT/restart.
        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(1000)
        self._persist_timer.timeout.connect(self._save_state)
        self._window_watcher = _WindowWatcher(self._schedule_save, self)

    def _windows(self) -> dict:
        """Config key -> window for every window whose position is saved
        (the seven tools and Settings; the nav bar keeps its edge place)."""
        return {"mining_panel_pos": self.panel,
                "orefinder_pos": self.orefinder,
                "hauling_pos": self.hauling,
                "inventory_pos": self.inventory,
                "combat_pos": self.combat_panel,
                "uex_pos": self.uex,
                "notes_pos": self.notes,
                "settings_pos": self.settings}

    def _restore_pos(self, widget, key: str) -> bool:
        pos = _saved_pos(self.cfg.get(key))
        if pos is None:
            return False
        widget.move(*pos)
        return True

    def _schedule_save(self) -> None:
        if not self._closed and not self._resetting:
            self._persist_timer.start()

    def _stop_saving(self) -> None:
        self._closed = True
        self._persist_timer.stop()

    # ------------------------------------------------------------------
    def _wire(self) -> None:
        self.nav.tool_requested.connect(self._on_tool)
        self.nav.close_requested.connect(self._hide_all)
        self.nav.quit_requested.connect(self.quit)
        self.nav.settings_requested.connect(self._toggle_settings)
        self.panel.close_requested.connect(self._on_panel_close)
        self.orefinder.close_requested.connect(self._on_orefinder_close)
        self.hauling.close_requested.connect(self._on_hauling_close)
        self.inventory.close_requested.connect(self._on_inventory_close)
        self.combat_panel.close_requested.connect(self._on_combat_close)
        self.uex.close_requested.connect(self._on_uex_close)
        self.notes.close_requested.connect(self._on_notes_close)
        self.combat_event.connect(
            self.combat_panel.add_event,
            Qt.ConnectionType.QueuedConnection)
        self.settings.region_requested.connect(self.select_region)
        self.settings.pause_toggled.connect(self._on_pause)
        self.settings.debug_toggled.connect(self._on_debug)
        self.settings.voice_toggled.connect(self._on_voice)
        self.settings.volume_changed.connect(self._on_volume)
        self.settings.opacity_changed.connect(self._on_opacity)
        self.settings.capture_toggled.connect(self._on_capture_visible)
        self.settings.ui_scale_changed.connect(self._on_ui_scale)
        self.settings.restart_requested.connect(self.restart)
        self.settings.install_requested.connect(self._install_update)
        self.settings.reload_requested.connect(self._reload_data)
        self.settings.close_requested.connect(self.settings.hide)
        self.settings.reads_changed.connect(self._on_reads)
        self.settings.monitor_changed.connect(self._on_game_monitor)
        self.settings.outline_toggled.connect(self._on_outline)
        self.settings.tracking_changed.connect(self._on_tracking)
        self.settings.hotkeys_changed.connect(self._on_hotkeys_changed)
        self.settings.open_unmatched_folder.connect(self._open_unmatched_folder)
        self.settings.clear_unmatched.connect(self._clear_unmatched)
        self.settings.reset_requested.connect(self._reset_settings)
        self.settings.sections_changed.connect(self._on_sections_changed)
        self.settings.history_toggled.connect(self._on_history_switch)
        self.settings.bad_reads_toggled.connect(self._on_bad_reads_switch)
        self.settings.open_history.connect(self._open_history)
        self.settings.open_bad_reads.connect(self._open_bad_reads)
        self.settings.detailed_log_toggled.connect(self._on_detailed_log)
        self.settings.open_log.connect(self._open_log)
        self.settings.view_log.connect(self._view_log)
        self.settings.export_diagnostics.connect(self._export_diagnostics)
        for panel_id, widget in self._panels().items():
            widget.pin_toggled.connect(
                lambda pinned, pid=panel_id: self._on_pin(pid, pinned))

        # Monitors plugged in, unplugged, or changed (resolution, scaling,
        # position): re-list them and keep the box on the signature. Debounced
        # because Windows reports one change as several events.
        self._display_timer = QTimer(self)
        self._display_timer.setSingleShot(True)
        self._display_timer.setInterval(800)
        self._display_timer.timeout.connect(self._on_displays_changed)
        self.app.screenAdded.connect(self._watch_screen)
        self.app.screenRemoved.connect(lambda _screen: self._display_timer.start())
        for screen in self.app.screens():
            self._watch_screen(screen, notify=False)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(_tray_icon(), self)
        self.tray.setToolTip(APP_TITLE)

        menu = QMenu()
        self.act_show = QAction("Show command bar", self)
        self.act_show.triggered.connect(self._show_bar)
        menu.addAction(self.act_show)

        act_panel = QAction("Mining scanner", self)
        act_panel.triggered.connect(lambda: self._toggle_panel("mining"))
        menu.addAction(act_panel)

        act_inventory = QAction("Inventory notes", self)
        act_inventory.triggered.connect(self._toggle_inventory)
        menu.addAction(act_inventory)

        act_combat = QAction("Combat feed", self)
        act_combat.triggered.connect(self._toggle_combat)
        menu.addAction(act_combat)

        menu.addSeparator()
        act_region = QAction("Draw capture region…", self)
        act_region.triggered.connect(self.select_region)
        menu.addAction(act_region)

        act_reload = QAction("Reload signature data", self)
        act_reload.triggered.connect(self._reload_data)
        menu.addAction(act_reload)

        act_folder = QAction("Open config folder", self)
        act_folder.triggered.connect(lambda: open_folder(config_dir()))
        menu.addAction(act_folder)

        menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        self.tray.activated.connect(
            lambda reason: self._show_bar()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    # ------------------------------------------------------------------
    def start(self) -> None:
        # Window styles must be applied *before* the windows are shown: on
        # macOS WA_MacAlwaysShowToolWindow only takes effect at that point,
        # otherwise Qt's tool windows hide whenever the app is deactivated.
        self._apply_window_tweaks()
        self._apply_opacity()

        self.nav.place()
        if self.cfg["nav_visible"] or self.demo:
            self.nav.slide_in()

        if not self._restore_pos(self.panel, "mining_panel_pos"):
            self.panel.place_default()
        fit_on_screen(self.panel)

        self.settings.set_reads(self._reads_per_second())
        self.settings.set_tracking(self._tracking_range())
        self.settings.set_tools(TOOLS)          # one hotkey row per tool
        self.cfg["settings_open"] = self._open_sections()
        self.settings.set_open_sections(self.cfg["settings_open"])
        self.settings.set_hotkeys(self._hotkey_config())
        self._load_pins()
        self._check_display()
        has_region = is_region_valid(self.cfg["region"])
        self.panel.set_track_state("fixed" if has_region else None)
        self.settings.set_region(self.cfg["region"] if has_region else None)
        self._show_data_version()
        self.settings.set_debug(bool(self.cfg["show_debug_preview"]))
        self.settings.set_outline(bool(self.cfg["show_region_outline"]))
        self._update_outline()
        self.voice.set_enabled(bool(self.cfg["voice_enabled"]))
        self.voice.set_volume(float(self.cfg["voice_volume"]))
        self.settings.set_voice(bool(self.cfg["voice_enabled"]))
        self.settings.set_volume(round(float(self.cfg["voice_volume"]) * 100))
        self.settings.set_opacity(round(self._opacity_level() * 100))
        self.settings.set_ui_scale(round(self._ui_scale_level() * 100))
        self.settings.set_capture_visible(self._capture_visible(),
                                          locked=self.capture_visible)
        self.settings.set_voice_hint(
            "" if self.voice.available else "No speech engine available")
        self._show_unmatched()
        self.settings.set_history(bool(self.cfg.get("debug_scan_history")))
        self.settings.set_bad_reads(bool(self.cfg.get("debug_save_bad_reads")))
        self.settings.set_detailed_log(bool(self.cfg.get("debug_detailed_log")))
        self._apply_debug()

        self.panel.show()
        # The other tools default to a spot beside the (now shown) scanner.
        for key, widget in self._windows().items():
            if widget is self.panel:
                continue
            if self._restore_pos(widget, key):
                if widget is self.settings:
                    self._settings_placed = True
            elif widget is not self.settings:     # Settings: placed on open
                widget.place_default(self.panel)
            # A saved position can belong to a monitor that is no longer
            # attached, which made a tool look like it opened nothing.
            fit_on_screen(widget)
        self.hauling.set_preferences(int(self.cfg["hauling_cargo"]),
                                     int(self.cfg["hauling_commodity"]))

        # Reopen whatever was on screen last time. A UI-scale restart used to
        # come back with every panel closed, which made the restart feel like a
        # crash instead of a settings change.
        for tool_id in self.cfg.get("open_tools") or []:
            if isinstance(tool_id, str):
                self.open_tool(tool_id)

        # macOS has no permission-free global hotkey API. Register application
        # shortcuts so F3/F4 still work whenever one of our windows has focus;
        # the tray menu is the always-available fallback.
        if not self.hotkeys.supported:
            self._shortcuts = []
            for target in (self.hauling, self.inventory):
                for key, slot in (("F3", self.nav.toggle), ("F4", self._hide_all)):
                    sc = QShortcut(QKeySequence(key), target)
                    sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
                    sc.activated.connect(slot)
                    self._shortcuts.append(sc)

        self.combat.start()
        self.blueprint_tracker.start()
        # Below the game's threads: a late scan is harmless, a late frame is not.
        self.scan.start(QThread.Priority.LowPriority)
        self._freshness.start()
        self._topmost.start()
        self.hotkeys.start()
        self.game_log.start()

        if not has_region and not self.demo:
            # No picker at start-up: it covered every monitor (the game too)
            # before the user had asked for it. DRAW REGION is in Settings.
            self.panel.set_scan_idle("No capture region — press DRAW REGION in Settings (⚙)")
        elif self.demo:
            self.panel.set_scan_idle("Demo mode")
        self._update_first_run_attention()
        # The windows are up: the scanner thread decodes the saved pin now,
        # and the signature data is refreshed from scmdb off the GUI thread.
        self._load_anchor()
        QTimer.singleShot(0, self, self._refresh_data)
        # Last: placing the windows above is not a user move to save.
        for widget in self._windows().values():
            widget.installEventFilter(self._window_watcher)

    def _apply_window_tweaks(self) -> None:
        for widget in (self.nav, self.panel, self.settings, self.orefinder,
                       self.combat_panel):
            try:
                win32.make_overlay_window(widget)
            except Exception as exc:
                log.warning("window style for %s failed (%s)", type(widget).__name__, exc)
        # HAULING, INVENTORY, UEX and NOTES have text controls, so they must be
        # able to take keyboard focus.
        for widget in (self.hauling, self.inventory, self.uex, self.notes):
            try:
                win32.make_focusable_window(widget)
            except Exception as exc:
                log.warning("window style for %s failed (%s)", type(widget).__name__, exc)
        self._apply_capture_visibility()
        self._assert_topmost()

    def _capture_visible(self) -> bool:
        """Whether the overlay should appear in screenshots and screen shares."""
        return bool(self.capture_visible
                    or not self.cfg.get("capture_exclude", False))

    def _apply_capture_visibility(self) -> None:
        show = self._capture_visible()
        widgets = [self.nav, self.panel, self.settings, self.orefinder,
                   self.hauling, self.inventory, self.uex, self.notes,
                   self.combat_panel]
        if getattr(self, "_log_viewer", None) is not None:
            widgets.append(self._log_viewer)
        for widget in widgets:
            try:
                if show:
                    win32.allow_capture(widget)
                else:
                    win32.exclude_from_capture(widget)
            except Exception as exc:
                log.warning("capture visibility for %s failed (%s)",
                            type(widget).__name__, exc)

    def _on_capture_visible(self, visible: bool) -> None:
        # --capture-visible is a development override: keep the toggle honest.
        if self.capture_visible:
            self.settings.set_capture_visible(True, locked=True)
            return
        self.cfg["capture_exclude"] = not bool(visible)
        self.cfg.save()
        self._apply_capture_visibility()

    def _assert_topmost(self) -> None:
        widgets = [self.nav, self.panel, self.orefinder, self.hauling,
                   self.settings, self.inventory, self.uex, self.notes,
                   self.combat_panel]
        if getattr(self, "_log_viewer", None) is not None:
            widgets.append(self._log_viewer)
        for widget in widgets:
            if not widget.isVisible():
                continue
            try:
                win32.keep_on_top(widget)
            except Exception as exc:
                _warn_once(("topmost", type(widget).__name__),
                           "keep on top for %s failed (%s)", type(widget).__name__, exc)
        try:
            self.outline.keep_on_top()
        except Exception as exc:
            _warn_once(("topmost", "outline"), "keep on top for the outline failed (%s)", exc)

    # ------------------------------------------------------------------
    def _on_hotkey(self, hotkey_id: int) -> None:
        if hotkey_id == 1:
            self.nav.toggle()
        elif hotkey_id == 2:
            self._hide_all()
        elif TOOL_HOTKEY_BASE <= hotkey_id < TOOL_HOTKEY_BASE + len(TOOLS):
            # Same as the tool's nav button: toggles it.
            self._on_tool(TOOLS[hotkey_id - TOOL_HOTKEY_BASE]["id"])

    # -- hotkeys (Settings → HOTKEYS) ------------------------------------
    def _hotkey_config(self) -> dict:
        """Hotkeys in the shape SettingsPanel.set_hotkeys / hotkeys_changed use."""
        tools = self.cfg.get("hotkey_tools")
        tools = tools if isinstance(tools, dict) else {}
        return {"toggle_nav": _vk(self.cfg.get("hotkey_toggle_nav")),
                "panic": _vk(self.cfg.get("hotkey_panic")),
                "tools": {str(k): _vk(v) for k, v in tools.items() if _vk(v)}}

    def _hotkey_bindings(self) -> dict[int, int]:
        """HotkeyThread ids: 1 = nav bar, 2 = hide all, 100+i = TOOLS[i]."""
        conf = self._hotkey_config()
        bindings = {}
        if conf["toggle_nav"]:
            bindings[1] = conf["toggle_nav"]
        if conf["panic"]:
            bindings[2] = conf["panic"]
        for i, tool in enumerate(TOOLS):
            vk = conf["tools"].get(tool["id"], 0)
            if vk:
                bindings[TOOL_HOTKEY_BASE + i] = vk
        return bindings

    def _on_hotkeys_changed(self, hotkeys: dict) -> None:
        hotkeys = hotkeys if isinstance(hotkeys, dict) else {}
        self.cfg["hotkey_toggle_nav"] = _vk(hotkeys.get("toggle_nav"))
        self.cfg["hotkey_panic"] = _vk(hotkeys.get("panic"))
        tools = hotkeys.get("tools")
        tool_ids = {tool["id"] for tool in TOOLS}
        self.cfg["hotkey_tools"] = {
            str(k): _vk(v) for k, v in (tools if isinstance(tools, dict) else {}).items()
            if str(k) in tool_ids and _vk(v)}
        self.cfg.save()
        self.hotkeys.set_bindings(self._hotkey_bindings())

    # -- window pins -----------------------------------------------------
    def _panels(self) -> dict:
        """Panel id -> window, for pins ("pinned_windows")."""
        return {"mining": self.panel, "orefinder": self.orefinder,
                "hauling": self.hauling, "inventory": self.inventory,
                "uex": self.uex, "notes": self.notes,
                "combat": self.combat_panel, "settings": self.settings}

    def _pinned_ids(self) -> set[str]:
        ids = self.cfg.get("pinned_windows")
        return {i for i in ids if isinstance(i, str)} if isinstance(ids, list) else set()

    def _load_pins(self) -> None:
        pinned = self._pinned_ids()
        for panel_id, widget in self._panels().items():
            widget.set_pinned(panel_id in pinned)

    def _on_pin(self, panel_id: str, pinned: bool) -> None:
        ids = self._pinned_ids()
        if pinned:
            ids.add(panel_id)
        else:
            ids.discard(panel_id)
        order = list(self._panels())
        self.cfg["pinned_windows"] = sorted(ids, key=lambda i: order.index(i)
                                            if i in order else len(order))
        self.cfg.save()

    def _show_bar(self) -> None:
        if not self.nav.shown:
            self.nav.slide_in()
        self._outline_hidden = False
        self._update_outline()

    def _hide_all(self) -> None:
        """F4 / the nav bar's ✕: hide everything except pinned panels."""
        if self.nav.shown:
            self.nav.slide_out()
        for widget in self._panels().values():
            if not widget.pinned:
                widget.hide()
        # A pinned scanner keeps reading, so its SHOW BOX outline stays;
        # otherwise it stays hidden until the bar is shown again.
        self._outline_hidden = not (self.panel.pinned and self.panel.isVisible())
        if self._outline_hidden:
            self._end_confirmation(redraw=False)
            self.outline.hide()
        self._sync_nav_active()

    def _on_tool(self, tool_id: str) -> None:
        if tool_id == "mining":
            self._toggle_panel("mining")
        elif tool_id == "orefinder":
            self._toggle_orefinder()
        elif tool_id == "hauling":
            self._toggle_hauling()
        elif tool_id == "inventory":
            self._toggle_inventory()
        elif tool_id == "uex":
            self._toggle_uex()
        elif tool_id == "notes":
            self._toggle_notes()
        elif tool_id == "combat":
            self._toggle_combat()

    def open_tool(self, tool_id: str) -> None:
        """Open a tool by id unless it is already visible."""
        if tool_id == "mining" and not self.panel.isVisible():
            self._toggle_panel("mining")
        elif tool_id == "orefinder" and not self.orefinder.isVisible():
            self._toggle_orefinder()
        elif tool_id == "hauling" and not self.hauling.isVisible():
            self._toggle_hauling()
        elif tool_id == "inventory" and not self.inventory.isVisible():
            self._toggle_inventory()
        elif tool_id == "uex" and not self.uex.isVisible():
            self._toggle_uex()
        elif tool_id == "notes" and not self.notes.isVisible():
            self._toggle_notes()
        elif tool_id == "combat" and not self.combat_panel.isVisible():
            self._toggle_combat()
        elif tool_id == "settings" and not self.settings.isVisible():
            self._toggle_settings()

    def _sync_nav_active(self) -> None:
        for tool_id, widget in (("hauling", self.hauling),
                                ("uex", self.uex),
                                ("inventory", self.inventory),
                                ("combat", self.combat_panel),
                                ("notes", self.notes),
                                ("orefinder", self.orefinder),
                                ("mining", self.panel)):
            if widget.isVisible():
                self.nav.set_active(tool_id)
                return
        self.nav.set_active(None)

    def _on_combat_event(self, event) -> None:
        """Forward tracker payloads without creating or touching a window."""
        self.combat_event.emit(event)

    def _on_game_log_event(self, event) -> None:
        """Runs on the log tailer's thread: re-emit, never touch widgets."""
        if event.kind == "pilot_seat" and event.seated is not None:
            self.pilot_seat.emit(bool(event.seated))

    def _on_pilot_seat(self, seated: bool) -> None:
        """Close the mining scanner when the player leaves the pilot seat."""
        if seated:
            return
        if not bool(self.cfg.get("close_scanner_on_seat_exit", True)):
            return
        if self.panel.isVisible():
            self.panel.hide()
            self._sync_nav_active()

    def _on_inventory_event(self, event) -> None:
        """Forward blueprint payloads to the host toast / shopping-list hook."""
        if event.is_blueprint:
            self.blueprint_unlocked_signal.emit(
                event.to_blueprint_dict())
        self.inventory_event_signal.emit(event.to_dict())

    def _toggle_panel(self, tool_id: str) -> None:
        if tool_id != "mining":
            return
        if self.panel.isVisible():
            self.panel.hide()
            self._sync_nav_active()
        else:
            self.panel.show()
            self.panel.raise_()
            self.nav.set_active("mining")
            self._assert_topmost()

    def _toggle_orefinder(self) -> None:
        if self.orefinder.isVisible():
            self.orefinder.hide()
            self._sync_nav_active()
            return

        self.orefinder.show()
        self.orefinder.raise_()
        self.nav.set_active("orefinder")
        self._assert_topmost()

        if self._last_match_name:
            self.orefinder.focus_ore(self._last_match_name)
        self.orefinder.refresh_if_stale()

    def _on_orefinder_close(self) -> None:
        self.orefinder.hide()
        self._sync_nav_active()

    def _toggle_hauling(self) -> None:
        if self.hauling.isVisible():
            self.hauling.hide()
            self._sync_nav_active()
            return
        self.hauling.show()
        self.hauling.raise_()
        self.nav.set_active("hauling")
        self._assert_topmost()
        self.hauling.refresh_if_stale()

    def _on_hauling_close(self) -> None:
        self.hauling.hide()
        self._sync_nav_active()

    def _toggle_inventory(self) -> None:
        if self.inventory.isVisible():
            self.inventory.hide()
            self._sync_nav_active()
            return
        self.inventory.focus_first()
        self.nav.set_active("inventory")
        self._assert_topmost()

    def _on_inventory_close(self) -> None:
        self.inventory.hide()
        self._sync_nav_active()

    def _toggle_uex(self) -> None:
        if self.uex.isVisible():
            self.uex.hide()
            self._sync_nav_active()
            return
        self.uex.clamp_to_screen()
        self.uex.show()
        self.uex.raise_()
        self.nav.set_active("uex")
        self._assert_topmost()

    def _on_uex_close(self) -> None:
        self.uex.hide()
        self._sync_nav_active()

    def _toggle_notes(self) -> None:
        if self.notes.isVisible():
            self.notes.hide()
            self._sync_nav_active()
            return
        self.notes.clamp_to_screen()
        self.notes.show()
        self.notes.raise_()
        self.nav.set_active("notes")
        self._assert_topmost()

    def _on_notes_close(self) -> None:
        self.notes.hide()
        self._sync_nav_active()

    def _toggle_combat(self) -> None:
        if self.combat_panel.isVisible():
            self.combat_panel.hide()
            self._sync_nav_active()
            return
        self.combat_panel.clamp_to_screen()
        self.combat_panel.show()
        self.combat_panel.raise_()
        self.combat_panel.scroll.verticalScrollBar().setValue(0)
        self.nav.set_active("combat")
        self._assert_topmost()

    def _on_combat_close(self) -> None:
        self.combat_panel.hide()
        self._sync_nav_active()

    def _toggle_settings(self) -> None:
        if self.settings.isVisible():
            self.settings.hide()
            return
        if not self._settings_placed:
            self.settings.place_default(self.panel)
            self._settings_placed = True
        fit_on_screen(self.settings)
        self.settings.show()
        self.settings.raise_()
        self._assert_topmost()
        self._show_preview()

    def _show_preview(self) -> None:
        """Settings preview: the whole signature window while locked with a
        saved plate, else the last crop read."""
        if self._plate_view is not None:
            self.settings.set_preview(*self._plate_view)
        elif self._last_res is not None:
            self.settings.set_preview(self._last_res.crop)

    def _on_plate_view(self, view) -> None:
        self._plate_view = view
        if view is not None:
            self.settings.set_preview(*view)

    def _on_panel_close(self) -> None:
        self.panel.hide()
        self._sync_nav_active()

    def _on_pause(self, paused: bool) -> None:
        self._paused = paused
        self.scan.set_enabled(not paused)
        if paused:
            # Nothing is tracked while paused: SHOW BOX goes back to the box.
            self._tracked_rect = None
            self._track_info = dict(self._track_info, digits=None, pin=None)
            self._last_locked = None
            self._update_outline()
        self.panel.set_state("paused" if paused else "reading")
        self._noread_since = None
        self._set_result(None)
        if paused and self._last_value is not None:
            self.panel.set_scan(self._last_value, 0.0, "lost",
                                self._last_matches, "paused")
        elif not paused:
            # Re-announce whatever is on screen when scanning resumes.
            self._spoken_key = None
            self._spoken_value = None

    def _on_debug(self, enabled: bool) -> None:
        self.cfg["show_debug_preview"] = enabled
        if enabled:
            self._show_preview()

    def _on_voice(self, enabled: bool) -> None:
        self.cfg["voice_enabled"] = bool(enabled)
        self.voice.set_enabled(enabled)
        if enabled:
            # Announce the rock that is already locked.
            self._spoken_key = None
            self._spoken_value = None
        self.settings.set_voice_hint(
            "" if self.voice.available or not enabled
            else "No speech engine available")

    def _on_volume(self, percent: int) -> None:
        level = max(0.0, min(1.0, int(percent) / 100.0))
        self.cfg["voice_volume"] = level
        self.voice.set_volume(level)

    def _on_opacity(self, percent: int) -> None:
        level = max(0.3, min(1.0, int(percent) / 100.0))
        self.cfg["overlay_opacity"] = level
        self._apply_opacity()

    def _opacity_level(self) -> float:
        try:
            return max(0.3, min(1.0,
                                float(self.cfg.get("overlay_opacity", 1.0))))
        except (TypeError, ValueError):
            return 1.0

    def _on_ui_scale(self, percent: int) -> None:
        level = max(0.75, min(1.5, int(percent) / 100.0))
        self.cfg["ui_scale"] = level
        # The panels bake the scale in when they are built, so persist it right
        # away: the RESTART button (or the next launch) reads it back.
        self.cfg.save()

    def _ui_scale_level(self) -> float:
        try:
            return max(0.75, min(1.5,
                                float(self.cfg.get("ui_scale", 1.0))))
        except (TypeError, ValueError):
            return 1.0

    def _apply_opacity(self) -> None:
        level = self._opacity_level()
        # Keep the nav bar and settings window fully visible while adjusting
        # the content panels.
        for widget in (self.panel, self.orefinder, self.hauling,
                       self.inventory, self.combat_panel):
            try:
                widget.setWindowOpacity(level)
            except Exception as exc:
                log.warning("opacity for %s failed (%s)", type(widget).__name__, exc)

    # -- scanner settings: reads per second, game monitor, outline -------
    def _reads_per_second(self) -> int:
        try:
            poll = max(1, int(self.cfg["poll_ms"]))
        except (TypeError, ValueError):
            poll = 250
        return max(1, min(8, round(1000 / poll)))

    def _on_reads(self, per_second: int) -> None:
        poll = round(1000 / max(1, min(8, int(per_second))))
        self.cfg["poll_ms"] = poll
        self.scan.configure(interval_ms=poll)
        self.cfg.save()

    def _watch_screen(self, screen, notify: bool = True) -> None:
        screen.geometryChanged.connect(lambda _geo: self._display_timer.start())
        screen.logicalDotsPerInchChanged.connect(lambda _dpi: self._display_timer.start())
        if notify:
            self._display_timer.start()

    def _on_displays_changed(self) -> None:
        self._check_display()
        self._update_outline()

    def _refresh_monitor_list(self, current: str | None = None) -> None:
        self.settings.set_monitors(display.monitor_choices(),
                                   current or self.cfg.get("game_monitor"))

    def _check_display(self) -> None:
        """Keep the box on the signature when the game monitor has changed.

        The monitor's physical rect is recorded when the box is drawn. If the
        game monitor now has a different resolution or position, the box is
        rescaled onto it (``display.rescale``) and Settings says so.
        """
        region = self.cfg["region"]
        name = self.cfg.get("game_monitor")
        screen = display.find_screen(name) if name else None
        if name and screen is None:
            self._refresh_monitor_list()
            self.settings.set_region_note(
                f"Game monitor {name} is not connected. Pick another monitor "
                "or reconnect it.")
            return
        screen = (screen or display.screen_of_region(region)
                  or QGuiApplication.primaryScreen())
        self._refresh_monitor_list(screen.name())
        if not is_region_valid(region):
            return
        now = display.physical_rect(screen)
        recorded = self.cfg.get("region_monitor")
        if not recorded:
            # Calibrated before monitors were tracked: adopt the current one.
            self.cfg["region_monitor"] = now
            self.cfg["game_monitor"] = screen.name()
            self.cfg.save()
            return
        if display.same_rect(recorded, now):
            return
        moved = display.rescale(region, recorded, now)
        dropped = self._drop_anchor_if_rescaled(recorded, now)
        self._apply_region(moved, now, screen.name())
        self.settings.set_region_note(
            f"Monitor changed ({recorded['width']}×{recorded['height']} → "
            f"{now['width']}×{now['height']}): box adjusted to match. Check "
            "SHOW PREVIEW or SHOW BOX; press DRAW REGION if it is off."
            + (_TRACKING_DROPPED if dropped else ""))

    def _on_game_monitor(self, name: str) -> None:
        screen = display.find_screen(name)
        if screen is None:
            return
        region = self.cfg["region"]
        recorded = self.cfg.get("region_monitor")
        now = display.physical_rect(screen)
        if is_region_valid(region) and recorded and not display.same_rect(recorded, now):
            dropped = self._drop_anchor_if_rescaled(recorded, now)
            self._apply_region(display.rescale(region, recorded, now), now, name)
            self.settings.set_region_note(
                f"Box moved to {display.screen_label(screen)}. Check SHOW "
                "PREVIEW or SHOW BOX; press DRAW REGION if it is off."
                + (_TRACKING_DROPPED if dropped else ""))
        else:
            self.cfg["game_monitor"] = name
            self.cfg.save()
            self.settings.set_region_note("")

    def _on_outline(self, enabled: bool) -> None:
        self.cfg["show_region_outline"] = bool(enabled)
        self.cfg.save()
        self._update_outline()

    # -- SHOW BOX and the scanner chip ------------------------------------
    def _init_tracking_state(self) -> None:
        # Digits rect the scanner is tracking now (physical).
        self._tracked_rect: dict | None = None
        # Last ScanThread.track_state; state None until the first read.
        self._track_info: dict = {"state": None, "digits": None, "pin": None}
        # (digits, pin) of the last locked read: SEARCHING is drawn there.
        self._last_locked: tuple | None = None
        self._lock_value: int | None = None   # value read since the plate locked
        self._outline_hidden = False         # F4 / ✕ hid it until the bar returns
        self._confirming = False             # DRAW REGION result on screen
        self._confirm_token = 0
        self._last_calibration_pin: dict | None = None
        # Pin learning from the fixed box (old box, or after a rescale): tried
        # once per box. _anchor_failed: the saved pin could not be loaded.
        self._learn_tried = False
        self._anchor_failed = False
        # ScanThread.plate_view: (plate crop, pin, digits) while locked, else None.
        self._plate_view: tuple | None = None
        self._draw_token = 0                 # the DRAW REGION frame grabs in flight

    def _track_marks(self) -> tuple:
        """(digits, pin, state, label) for SHOW BOX now."""
        region = self.cfg["region"]
        state = self._track_info.get("state")
        if state is None:
            state = "searching" if self.scan.tracking else "fixed"
        if state == "locked" and self._track_info.get("digits"):
            value = self._lock_value
            label = (f"TRACKING ✓  {value:,}" if value is not None
                     else "TRACKING ✓")
            return self._track_info["digits"], self._track_info.get("pin"), state, label
        if state in ("searching", "locked"):
            digits, pin = self._last_locked or (region, None)
            return digits, pin, "searching", "SEARCHING…"
        return region, None, "fixed", theme.TRACK_TEXT["fixed"]

    def _update_outline(self) -> None:
        if self._confirming:
            return          # the DRAW REGION result owns the outline for now
        region = self.cfg["region"]
        if (self.cfg.get("show_region_outline") and is_region_valid(region)
                and not self._outline_hidden):
            self.outline.show_marks(*self._track_marks())
        else:
            self.outline.hide()

    def _on_tracked(self, rect) -> None:
        """The scanner found the plate somewhere else (or lost it)."""
        self._tracked_rect = rect

    def _on_track_state(self, info) -> None:
        """ScanThread.track_state: the chip always, SHOW BOX when it is on."""
        if info.get("state") != self._track_info.get("state"):
            log.debug("tracking: %s -> %s (digits %s, pin %s)",
                      self._track_info.get("state"), info.get("state"),
                      info.get("digits"), info.get("pin"))
        self._track_info = dict(info)
        if info.get("state") != "locked":
            self._lock_value = None
            # Red means "plate on screen, number unreadable": no plate, no red.
            self._noread_since = None
            if self._result == "noread":
                self._set_result(None)
        if info.get("state") == "locked" and info.get("digits"):
            self._last_locked = (info["digits"], info.get("pin"))
        elif info.get("state") == "fixed":
            self._last_locked = None
        self.panel.set_track_state(info.get("state"))
        self._update_outline()

    def _confirm_calibration(self, found: bool, region: dict,
                             pin: dict | None) -> None:
        """DRAW REGION result for CONFIRM_MS, whether SHOW BOX is on or not."""
        self._confirming = True
        self._confirm_token += 1
        token = self._confirm_token
        if found:
            self.outline.show_marks(region, pin, "locked", "PIN FOUND — TRACKING ON")
        else:
            self.outline.show_marks(region, None, "searching", "NO PIN FOUND — FIXED BOX")
        QTimer.singleShot(CONFIRM_MS, self,
                          lambda: self._end_confirmation(token=token))

    def _end_confirmation(self, token: int | None = None, redraw: bool = True) -> None:
        if token is not None and token != self._confirm_token:
            return          # a newer confirmation is showing
        if not self._confirming:
            return
        self._confirming = False
        if redraw:
            self._update_outline()

    # -- HUD tracking ---------------------------------------------------
    def _tracking_range(self) -> int:
        return parse_tracking_range(self.cfg.get("tracking_range"))

    def _on_tracking(self, range_px: int) -> None:
        self.cfg["tracking_range"] = parse_tracking_range(range_px)
        self.cfg.save()
        self.scan.configure(tracking_range=self.cfg["tracking_range"])

    def _load_anchor(self) -> None:
        """Hand the pin saved at the last DRAW REGION to the scanner.

        The picture is decoded on the scanner thread (OpenCV is not imported
        on the GUI thread at start-up); _on_anchor_loaded takes the result.
        A missing anchor.png clears the stale metadata.
        """
        meta = self.cfg.get("anchor")
        if not meta or self.demo:
            return
        try:
            path = config_dir() / str(meta["file"])
        except (KeyError, TypeError):
            path = None
        if path is None or not path.is_file():
            self.cfg["anchor"] = None
            self.cfg["plate"] = None        # measured from that pin
            self.cfg.save()
            self._learn_tried = False
            self.settings.set_region_note(_PIN_MISSING_NOTE)
            return
        self.scan.request_anchor(config_dir(), meta)

    def _on_anchor_loaded(self, meta, result) -> None:
        if self.cfg.get("anchor") != meta:
            return          # a new box or pin since the request: stale
        if isinstance(result, str):
            self._anchor_failed = True
            self._learn_tried = False
            self.settings.set_region_note(_PIN_LOAD_FAILED_NOTE.format(result))
            return
        self._anchor_failed = False
        self.scan.configure(anchor=result, plate=self.cfg.get("plate"))

    def _drop_anchor_if_rescaled(self, recorded: dict, now: dict) -> bool:
        """The box moved to another monitor rect. The pin is a picture in
        physical pixels and the HUD scales with the monitor height, so only a
        height change makes it useless; a moved monitor (or a wider one at
        the same height) keeps it. Returns whether the pin was dropped."""
        if int(recorded.get("height", 0)) == int(now.get("height", 0)):
            return False
        return self._drop_anchor()

    def _drop_anchor(self) -> bool:
        """Turn tracking off: the saved pin is for another resolution.

        Returns whether there was an anchor to drop. The pin is learned again
        from the next confident signature the fixed box reads.
        """
        had = self.cfg.get("anchor") is not None
        self.cfg["anchor"] = None
        self.cfg["plate"] = None        # re-learned at the next DRAW REGION
        self.cfg.save()
        self.scan.configure(anchor=None, plate=None)
        self._learn_tried = False
        self._anchor_failed = False
        return had

    def _calibrate_anchor(self, region: dict, image=None, origin=None,
                          quiet: bool = False) -> bool:
        """Find the plate's pin icon left of the box.

        ``image``/``origin`` (the physical top-left of ``image``) are for
        tests; normally the screen around the box is grabbed. Returns whether
        tracking is on. ``quiet`` (pin learned while reading): a miss changes
        nothing; a find is saved and noted.
        """
        anchor = None
        error = ""
        self._last_calibration_pin = None
        try:
            from . import tracking

            if image is None:
                area = _calibration_area(region)
                from .capture import ScreenGrabber

                grabber = ScreenGrabber()
                try:
                    image = grabber.grab(area)
                finally:
                    grabber.close()
                origin = (area["left"], area["top"])
            box = (region["left"] - origin[0], region["top"] - origin[1],
                   region["width"], region["height"])
            anchor = tracking.find_anchor(image, box)
            if anchor is not None:
                self.cfg["anchor"] = anchor.save(config_dir())
                match = tracking.locate(image, anchor)
                if match is not None:
                    self._last_calibration_pin = pin_rect(match, anchor, *origin)
        except Exception as exc:
            anchor = None
            error = f"{type(exc).__name__}: {exc}"
        if quiet and anchor is None:
            return False
        if anchor is None:
            self.cfg["anchor"] = None
        # The window is only known from DRAW REGION on it, never from a
        # digits box (a newly cut pin may also sit a pixel off the old one).
        self.cfg["plate"] = None
        self.cfg.save()
        self._anchor_failed = False
        self.scan.configure(anchor=anchor, plate=None)
        if anchor is not None:
            self.settings.set_region_note(_PIN_LEARNED_NOTE if quiet else "")
        else:
            self.settings.set_region_note(
                _PIN_SEARCH_FAILED_NOTE.format(error) if error else _NO_PIN_NOTE)
        return anchor is not None

    def _maybe_learn_pin(self, top) -> None:
        """B / g: a box with no pin (drawn before pins existed, or rescaled
        to a new height) learns it from the first exact signature the fixed
        box shows (the panel's own rule: a fast single read or identical
        reads): the plate is on the box at that moment. Once per box."""
        if self._learn_tried or self.demo or self._paused:
            return
        if self.scan.has_anchor or (self.cfg.get("anchor") and not self._anchor_failed):
            return
        region = self.cfg["region"]
        if not is_region_valid(region) or top is None or not top.exact:
            return
        self._learn_tried = True
        self._calibrate_anchor(region, quiet=True)

    def _apply_region(self, region: dict, monitor: dict, monitor_name: str) -> None:
        """Store a new box (and its monitor) and point the scanner at it."""
        self.cfg["region"] = region
        self.cfg["region_monitor"] = monitor
        self.cfg["game_monitor"] = monitor_name
        self.cfg.save()

        self.scan.configure(region=region)
        self._tracked_rect = None
        self._last_locked = None
        self._recent.clear()
        self._last_value = None
        self._last_matches = []
        self._spoken_key = None
        self._spoken_value = None
        self._scan_sig_reset()

        self.settings.set_region(region)
        self._refresh_monitor_list(monitor_name)
        self._update_outline()
        self._update_first_run_attention()

    def _update_first_run_attention(self) -> None:
        """No box yet (first run): point at ⚙ and DRAW REGION until there is."""
        need = not self.demo and not is_region_valid(self.cfg["region"])
        self.nav.set_settings_attention(need)
        self.settings.set_draw_region_attention(need)
        # SCANNER stays open (its heading cannot close it) until a box is drawn.
        self.settings.set_force_open(
            None if is_region_valid(self.cfg["region"]) else "scanner")

    def _open_sections(self) -> list[str]:
        """The saved open Settings sections, unknown or repeated ids dropped."""
        saved = self.cfg.get("settings_open")
        if not isinstance(saved, list):
            return list(app_config.DEFAULTS["settings_open"])
        return [i for i in SECTION_IDS if i in saved]

    def _on_sections_changed(self, ids: list) -> None:
        self.cfg["settings_open"] = [i for i in SECTION_IDS if i in ids]
        log.debug("settings sections open: %s", self.cfg["settings_open"])
        self.cfg.save()

    # ------------------------------------------------------------------
    def select_region(self) -> None:
        if self._selector is not None:
            self._selector.raise_()
            return
        hint = ("Drag a box around the scan signature"
                if not self.demo else
                "Demo mode: no real region needed")
        # Open on the game monitor chosen in Settings; all monitors if none is
        # chosen yet (first run) or it is not connected.
        game = display.find_screen(self.cfg.get("game_monitor"))
        self._selector = RegionSelector(hint, screens=[game] if game else None)
        self._selector.selected.connect(self._on_region_selected)
        self._selector.cancelled.connect(self._on_region_cancelled)
        self._selector.show()

    def _on_region_cancelled(self) -> None:
        self._selector = None
        if not is_region_valid(self.cfg["region"]):
            self.panel.set_scan_idle("Region selection cancelled")

    def _on_region_selected(self, region: dict) -> None:
        self._selector = None
        screen = display.screen_of_region(region) or QGuiApplication.primaryScreen()
        # The old pin belongs to the old box; a new one is looked for below.
        self.scan.configure(anchor=None, plate=None)
        self._draw_token += 1           # stop grabs for an earlier box
        self._learn_tried = True        # DRAW REGION looks for it right away
        self._apply_region(region, display.physical_rect(screen), screen.name())
        self.settings.set_region_note("")
        self.panel.set_scan_idle(f"Scanning {region['width']} × {region['height']} px")
        self.panel.set_state("reading")
        if not self.demo:
            # Give Windows a moment to take the picker's dimming off the
            # screen before grabbing the pin around the box.
            QTimer.singleShot(150, self, lambda: self._calibrate_drawn(region))

    def _calibrate_drawn(self, region: dict, grab=None) -> None:
        """DRAW REGION: look for the pin inside the drawn box (the whole
        signature window, or the digits alone) on up to DRAW_FRAMES grabs
        DRAW_FRAME_MS apart; the first that shows it wins. Then the result
        for 3 s. ``grab(rect)`` (tests) returns the BGR screen of a rect."""
        if self.cfg["region"] != region:
            return          # another box was drawn meanwhile
        self._draw_token += 1
        grabber = None
        if grab is None:
            from .capture import ScreenGrabber

            grabber = ScreenGrabber()
            grab = grabber.grab
        self._draw_attempt(region, grab, grabber, DRAW_FRAMES, self._draw_token)

    def _draw_attempt(self, region: dict, grab, grabber, left: int, token: int) -> None:
        if token != self._draw_token or self.cfg["region"] != region:
            if grabber is not None:
                grabber.close()
            return          # another box was drawn meanwhile
        error = ""
        try:
            found = self._find_plate(region, grab)
        except Exception as exc:
            found, error = None, f"{type(exc).__name__}: {exc}"
        log.debug("DRAW REGION: frame %d of %d: %s", DRAW_FRAMES - left + 1, DRAW_FRAMES,
                  "pin found" if found is not None else (error or "no pin"))
        if found is None and left > 1:
            QTimer.singleShot(DRAW_FRAME_MS, self, lambda: self._draw_attempt(
                region, grab, grabber, left - 1, token))
            return
        if grabber is not None:
            grabber.close()
        self._finish_draw(region, found, error)

    @staticmethod
    def _find_plate(region: dict, grab) -> tuple | None:
        """(anchor, plate, digits, pin) from one grab around the drawn box,
        digits and pin as physical rects; None when no pin is found."""
        from . import tracking
        from .tracking import PIN_MARGIN

        area = _calibration_area(region)
        image = grab(area)
        box = (region["left"] - area["left"], region["top"] - area["top"],
               region["width"], region["height"])
        screen = display.screen_of_region(region)
        height = (display.physical_rect(screen)["height"]
                  if screen is not None else 0) or 2160
        found = tracking.find_anchor_in_box(image, box, height)
        if found is None:
            return None
        anchor, plate = found
        # The template's top-left: the drawn box less the plate offset.
        tx = area["left"] + box[0] - int(plate[0])
        ty = area["top"] + box[1] - int(plate[1])
        dx, dy, dw, dh = (int(v) for v in anchor.digits)
        th, tw = anchor.template.shape[:2]
        digits = {"left": tx + dx, "top": ty + dy, "width": dw, "height": dh}
        pin = {"left": tx + PIN_MARGIN, "top": ty + PIN_MARGIN,
               "width": int(tw - 2 * PIN_MARGIN), "height": int(th - 2 * PIN_MARGIN)}
        if not is_region_valid(digits):
            return None
        return anchor, tuple(int(v) for v in plate), digits, pin

    def _finish_draw(self, region: dict, found, error: str) -> None:
        """Save what DRAW REGION found and show the 3-second result."""
        if found is not None:
            anchor, plate, digits, pin = found
            try:
                self.cfg["anchor"] = anchor.save(config_dir())
            except OSError as exc:
                found, error = None, f"{type(exc).__name__}: {exc}"
        if error:
            log.warning("DRAW REGION: pin search failed (%s)", error)
        log.debug("DRAW REGION result for %s: %s", region,
                  "tracking on" if found is not None else "fixed box")
        if found is None:
            self.cfg["anchor"] = None
            self.cfg["plate"] = None
            self.cfg.save()
            self._anchor_failed = False
            self.scan.configure(anchor=None, plate=None)
            self.settings.set_region_note(
                _PIN_SEARCH_FAILED_NOTE.format(error) if error else _NO_PIN_NOTE)
            self._confirm_calibration(False, region, None)
            return
        dx, dy, w, h = plate
        self.cfg["plate"] = {"dx": dx, "dy": dy, "w": w, "h": h}
        # cfg["region"] is the digits box: scanning, tracking and the
        # rescale on a monitor change work on it as before.
        self._apply_region(digits, self.cfg.get("region_monitor") or {},
                           self.cfg.get("game_monitor") or "")
        self._anchor_failed = False
        self.scan.configure(anchor=anchor, plate=plate)
        self.settings.set_region_note("")
        self._confirm_calibration(True, digits, pin)

    def _scan_sig_reset(self) -> None:
        self.panel.reset_cache()

    # ------------------------------------------------------------------
    def _on_result(self, res, matches) -> None:
        confirmed = self._handle_result(res, matches)
        self._debug_read(res, matches, confirmed)

    def _handle_result(self, res, matches) -> bool:
        """Show one read; True when it passed confirmation (shown as stable)."""
        if res is not self._last_res:
            self._last_res = res
            if self._plate_view is None:    # else _on_plate_view shows the window
                self.settings.set_preview(res.crop)

        if not res.ok:
            self._recent.clear()
            self._on_unreadable(res)
            return False

        self._noread_since = None
        self.panel.set_scanned(res.value)
        self._recent.append(res.value)
        # Refresh the liveness timer on any readable number: "lost" means the
        # HUD left the screen, not that we are unsure which of two readings is
        # right.
        self._last_good_at = time.monotonic()
        needed = max(1, int(self.cfg["stability_reads"]))
        stable = (len(self._recent) >= needed
                  and len(set(self._recent)) == 1)
        top = matches[0] if matches else None
        value = res.value
        # A high-confidence exact signature is trustworthy enough to show on
        # the first read, but only while nothing is on screen. Replacing a
        # number that is already shown needs the same confirmation as a first
        # lock: OCR can alternate between two plausible readings (8,000, and
        # 28,000 when a stray leading digit joins the crop) and both are exact
        # matches, which used to flip the panel on every frame.
        changing = self._last_value is not None and value != self._last_value
        fast_lock = (
            bool(self.cfg.get("fast_single_read", True))
            and top is not None
            and top.exact
            and float(res.confidence) >= float(self.cfg["fast_confidence"])
            and not changing
        )
        if not stable and not fast_lock:
            self.panel.set_state("reading")
            self._set_result(None)          # only a confirmed result colours it
            return False

        self._last_value = value
        self._last_matches = matches
        if matches and not matches[0].is_ground:
            self._last_match_name = matches[0].name

        self.panel.set_state("stable")
        note = ""
        if not matches:
            near = self.data.nearest(value)
            if near:
                note = f"closest {near[0].name} ×{near[0].count} ({near[0].target:,})"
        self.panel.set_scan(value, res.confidence, "stable", matches, note)
        exact = top is not None and top.exact      # "~" near-guess: no match
        self._set_result("match" if exact else "nomatch")
        if not exact:
            self._record_unmatched(value, res.crop)

        if self._track_info.get("state") == "locked" and self._lock_value != value:
            self._lock_value = value
            self._update_outline()          # the label shows the value

        # Announce only exact signatures: a fuzzy match is usually an OCR
        # misread, and saying the wrong ore is worse than saying nothing.
        if top is not None and top.exact:
            self._announce_signature(value, top)
        # Here the value is shown (fast single read or identical reads).
        self._maybe_learn_pin(top)
        return True

    # -- Settings → DEBUG: scan history and bad-read pictures ------------
    def _init_debug_state(self) -> None:
        folder = config_dir()
        self._history: ScanHistory | None = None      # None while SCAN HISTORY is off
        self._history_path = folder / HISTORY_NAME
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(HISTORY_WRITE_MS)
        self._history_timer.timeout.connect(self._flush_history)
        self._bad_reads_folder = folder / BAD_READS_FOLDER
        self._bad_read_at: float | None = None       # monotonic time of the last picture
        self._bad_read_seq = 0
        self._log_viewer: LogViewer | None = None     # VIEW LOG, built on first use
        self._last_scan_error: str | None = None

    def _apply_debug(self) -> None:
        """Start or stop SCAN HISTORY from the settings."""
        if self.cfg.get("debug_scan_history") and not self._resetting:
            if self._history is None:
                self._history = ScanHistory(self._history_path)
                self._history.load()
        elif self._history is not None:
            self._flush_history()
            self._history = None

    def _on_history_switch(self, enabled: bool) -> None:
        self.cfg["debug_scan_history"] = bool(enabled)
        self.cfg.save()
        self._apply_debug()

    def _on_bad_reads_switch(self, enabled: bool) -> None:
        self.cfg["debug_save_bad_reads"] = bool(enabled)
        self.cfg.save()

    def _flush_history(self) -> None:
        self._history_timer.stop()
        if self._history is not None and not self._resetting:
            self._history.flush()

    def _open_history(self) -> None:
        """OPEN HISTORY: the file when there is one, else its folder."""
        self._flush_history()
        path = self._history_path
        app_config.open_folder(path if path.is_file() else path.parent)

    def _open_bad_reads(self) -> None:
        try:
            self._bad_reads_folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("bad reads: could not create %s (%s)", self._bad_reads_folder, exc)
        app_config.open_folder(self._bad_reads_folder)

    # -- Settings → DEBUG → Logs ------------------------------------------
    def _on_detailed_log(self, enabled: bool) -> None:
        """DETAILED LOG: saved, and the log level switches at once."""
        self.cfg["debug_detailed_log"] = bool(enabled)
        self.cfg.save()
        applog.set_detailed(bool(enabled))
        log.debug("detailed log on")

    def _open_log(self) -> None:
        """OPEN LOG: app.log in its default program (Notepad), else its folder."""
        path = applog.log_path()
        self._open_log_file(path if path.is_file() else path.parent)

    def _view_log(self) -> None:
        """VIEW LOG: the one log window, on app.log, where it was last."""
        viewer = self._log_viewer
        if viewer is None:
            viewer = self._log_viewer = LogViewer(applog.log_path())
            viewer.close_requested.connect(viewer.hide)
            viewer.open_file.connect(self._open_log_file)
            try:
                win32.make_overlay_window(viewer)
            except Exception as exc:
                log.warning("window style for the log viewer failed (%s)", exc)
            pos = _saved_pos(self.cfg.get("logviewer_pos"))
            if pos is not None:
                viewer.move(*pos)
            else:
                viewer.place_default(self.settings)
            viewer.clamp_to_screen()
            self._apply_capture_visibility()
            watcher = getattr(self, "_window_watcher", None)
            if watcher is not None:     # moves are saved like the other windows
                viewer.installEventFilter(watcher)
        elif viewer.path != applog.log_path():
            viewer.set_path(applog.log_path())
        viewer.show()
        viewer.raise_()
        self._assert_topmost()

    def _open_log_file(self, path) -> None:
        try:
            app_config.open_folder(path)
        except OSError as exc:
            log.warning("could not open %s (%s)", path, exc)

    def _close_log_viewer(self) -> None:
        if getattr(self, "_log_viewer", None) is not None:
            self._log_viewer.hide()

    def _export_diagnostics(self) -> None:
        """EXPORT DIAGNOSTICS: one zip on the Desktop (else the settings
        folder), then its folder is opened and the name shown."""
        target, where = diagnostics_target()
        extra = {"monitors": _monitor_lines(),
                 "game monitor": self.cfg.get("game_monitor"),
                 "region": self.cfg.get("region")}
        try:
            path = applog.export_diagnostics(target, config_dir(), extra)
        except Exception as exc:
            log.warning("EXPORT DIAGNOSTICS failed (%s)", exc)
            self.settings.set_log_note(f"Export failed: {exc}")
            return
        log.debug("diagnostics written to %s", path)
        self.settings.set_log_note(f"Saved to {where}: {path.name}")
        self._open_log_file(path.parent)

    def _debug_read(self, res, matches, confirmed: bool) -> None:
        """After each read (GUI thread): the history line and the bad-read
        picture. "no plate" is not a read (the reader did not run)."""
        if self._resetting or getattr(res, "raw", "") == "no plate":
            return
        state = self._track_info.get("state")
        if self._history is not None:
            value = getattr(res, "value", None)
            shown = value is not None and value == self._last_value
            self._history.add(history_line(time.time(), res, matches, confirmed,
                                           shown, self._result, state))
            if not self._history_timer.isActive():
                self._history_timer.start()
        if (self.cfg.get("debug_save_bad_reads") and not res.ok and state == "locked"
                and getattr(res, "crop", None) is not None):
            now = time.monotonic()
            if self._bad_read_at is not None and now - self._bad_read_at < BAD_READ_SECONDS:
                return
            self._bad_read_at = now
            self._bad_read_seq += 1
            save_bad_read(self._bad_reads_folder, res.crop, time.time(),
                          self._track_info, self._bad_read_seq)

    def _init_result_state(self) -> None:
        self._result: str | None = None          # what the border shows now
        # monotonic time the tracked plate became unreadable, None while read.
        self._noread_since: float | None = None
        # Unmatched value already offered to the recorder while it is shown.
        self._unmatched_value: int | None = None

    def _set_result(self, result: str | None) -> None:
        if result != self._result:
            self._result = result
            self.panel.set_result(result)

    def _on_unreadable(self, res) -> None:
        """A read with no number: "—" while a plate is there, red after
        NOREAD_SECONDS in a row of a tracked plate that cannot be read."""
        state = self._track_info.get("state")
        if getattr(res, "raw", "") == "no plate" or state == "searching":
            self._noread_since = None
            return                  # nothing on screen: nothing to report
        self.panel.set_scanned(None)
        if state != "locked":
            return                  # fixed box: no way to know a plate is there
        now = time.monotonic()
        if self._noread_since is None:
            self._noread_since = now
        elif now - self._noread_since >= NOREAD_SECONDS:
            self._set_result("noread")

    def _record_unmatched(self, value: int, crop) -> None:
        if value == self._unmatched_value:
            return                  # same reading still on screen
        self._unmatched_value = value
        try:
            if self.unmatched.record(value, "unknown", crop):
                self.settings.set_unmatched(self.unmatched.entries())
        except Exception as exc:    # a full disk must not stop the scanner
            log.warning("unmatched: could not record %s (%s)", value, exc)

    def _show_unmatched(self) -> None:
        try:
            entries = self.unmatched.entries()
        except Exception as exc:
            log.warning("unmatched: could not list the readings (%s)", exc)
            entries = []
        self.settings.set_unmatched(entries)

    def _open_unmatched_folder(self) -> None:
        try:
            self.unmatched.folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("unmatched: could not create %s (%s)", self.unmatched.folder, exc)
        app_config.open_folder(self.unmatched.folder)

    def _clear_unmatched(self) -> None:
        try:
            self.unmatched.clear()
        except Exception as exc:
            log.warning("unmatched: could not clear (%s)", exc)
        self._unmatched_value = None
        self.settings.set_unmatched([])

    def _reset_settings(self) -> None:
        """RESET SETTINGS: back up and remove the settings, then restart."""
        log.debug("RESET SETTINGS: starting")
        self.scan.stop()
        self.scan.wait(1500)
        try:
            app_config.reset_to_defaults()
        except Exception as exc:
            # Nothing was removed: keep working with the current settings.
            log.warning("RESET SETTINGS failed, nothing removed (%s)", exc)
            self.settings.set_reset_error(str(exc))
            self.scan.resume()
            return
        # The old Config must never be saved again (restart and quit save
        # state): a fresh default one replaces it and saving is turned off.
        self.cfg = Config()
        self._resetting = True
        # DETAILED LOG goes back to off (the app.log files are kept: they
        # are not settings) and the log window closes.
        applog.set_detailed(False)
        self._close_log_viewer()
        log.debug("RESET SETTINGS: done, restarting")
        self.restart()

    def save_config(self) -> None:
        """aboutToQuit: write the settings, unless they were just reset."""
        if not self._resetting:
            self.cfg.save()
            self._flush_history()

    def _announce_signature(self, value: int, top) -> None:
        """Speak a locked rock once, not on every read while flying at it.

        The scan HUD can drop and re-acquire the same rock, and OCR can jitter
        the signature by a digit.  Dedupe on the identified ore and treat a
        near-identical value as the same target, so approaching one rock does
        not repeat the announcement.  A genuinely different signature still
        speaks even when the ore type is the same.
        """
        key = (top.kind, top.name, top.count)
        same_target = (
            key == self._spoken_key
            and self._spoken_value is not None
            and abs(int(value) - int(self._spoken_value))
            <= max(2, int(round(abs(int(self._spoken_value)) * 0.02)))
        )
        if same_target:
            return
        self._spoken_key = key
        self._spoken_value = int(value)
        self.voice.say(spoken_text(top.label, top.count))

    def _on_scan_error(self, message: str) -> None:
        if message != self._last_scan_error:   # the loop repeats it every read
            self._last_scan_error = message
            log.warning("scanner: %s", message)
        self.panel.set_state("error")
        self.panel.set_scan_idle(f"Capture error: {message}")

    def _check_freshness(self) -> None:
        if self._paused:
            return
        if self._last_value is None:
            return
        idle = time.monotonic() - self._last_good_at
        if idle <= 2.0:
            return
        self.panel.set_state("idle")
        self.panel.set_scan(self._last_value, 0.0, "lost", self._last_matches)
        self._unmatched_value = None
        # Lost: back to the thin edge. Red stays while the tracked plate is
        # still on screen and unreadable (it went "lost" because of that).
        if self._result != "noread":
            self._set_result(None)
        # Keep the spoken signature through brief flicker; only forget it after
        # a real break so a new rock of the same type can announce again.
        try:
            reset_after = float(self.cfg.get("voice_idle_reset_seconds", 12.0))
        except (TypeError, ValueError):
            reset_after = 12.0
        if idle >= max(2.0, reset_after):
            self._spoken_key = None
            self._spoken_value = None

    # ------------------------------------------------------------------
    def _refresh_data(self) -> None:
        """Refresh the scmdb signature cache in the background (once a day);
        on_done runs on the worker thread, so it only emits a signal."""
        try:
            self.data.refresh_in_background(self.data_refreshed.emit)
        except Exception as exc:    # the bundled / cached data keeps working
            log.warning("signature data refresh could not start (%s)", exc)

    def _on_data_refreshed(self, changed: bool) -> None:
        if changed:
            self._reload_data()

    def _show_data_version(self) -> None:
        """Settings: where the signatures come from ("scmdb 4.10.2 live" /
        "bundled 4.10.2"), and why the bundled file is used when it fell back."""
        text = getattr(self.data, "source_text", "") or str(self.data.version)
        reason = getattr(self.data, "fallback_reason", "")
        if reason:
            text += f" (scmdb unavailable: {reason[:60]})"
        self.settings.set_version(text, len(self.data.ores))

    def _reload_data(self) -> None:
        try:
            self.data.reload()
            self._show_data_version()
            self.panel.reset_cache()
            self.panel.set_scan_idle(f"Signature data reloaded · {self.data.version}")
        except Exception as exc:
            log.warning("signature data reload failed (%s)", exc)
            self.panel.set_state("error")
            self.panel.set_scan_idle(f"Reload failed: {exc}")

    # ------------------------------------------------------------------
    def _save_state(self) -> None:
        if self._resetting:
            return          # the settings were reset: write nothing back
        try:
            self.cfg["mining_panel_pos"] = [self.panel.x(), self.panel.y()]
            self.cfg["orefinder_pos"] = [self.orefinder.x(), self.orefinder.y()]
            self.cfg["hauling_pos"] = [self.hauling.x(), self.hauling.y()]
            self.cfg["inventory_pos"] = [self.inventory.x(), self.inventory.y()]
            self.cfg["combat_pos"] = [self.combat_panel.x(),
                                      self.combat_panel.y()]
            self.cfg["uex_pos"] = [self.uex.x(), self.uex.y()]
            self.cfg["notes_pos"] = [self.notes.x(), self.notes.y()]
            if self._settings_placed:
                self.cfg["settings_pos"] = [self.settings.x(), self.settings.y()]
            viewer = getattr(self, "_log_viewer", None)
            if viewer is not None:
                self.cfg["logviewer_pos"] = [viewer.x(), viewer.y()]
            self.cfg["open_tools"] = [
                tool_id for tool_id, widget in (
                    ("mining", self.panel),
                    ("orefinder", self.orefinder),
                    ("hauling", self.hauling),
                    ("uex", self.uex),
                    ("inventory", self.inventory),
                    ("combat", self.combat_panel),
                    ("notes", self.notes),
                    ("settings", self.settings),
                ) if widget.isVisible()]
            self.cfg["hauling_cargo"] = self.hauling.capacity()
            self.cfg["hauling_commodity"] = self.hauling.current_commodity()
            self.cfg["nav_visible"] = self.nav.shown
            log.debug("window positions saved: %s",
                      {k: v for k, v in self.cfg.data.items() if k.endswith("_pos")})
            self.cfg.save()
        except Exception as exc:
            log.warning("could not save the window positions (%s)", exc)

    def restart(self) -> None:
        """Relaunch the overlay, e.g. to apply a new UI scale.

        The scale is baked into the widgets when they are built, so applying it
        needs a fresh process.  State is saved first so the new instance opens
        the panels exactly where they are now.
        """
        self._save_state()
        # The replacement is allowed to wait for this process's single-instance
        # mutex; drop any stale flag first so the list cannot grow.
        extra = [a for a in self._launch_args if a != "--restart"]
        if getattr(sys, "frozen", False):
            args = [sys.executable, *extra, "--restart"]
            root = Path(sys.executable).resolve().parent
        else:
            args = [sys.executable, "-m", "app", *extra, "--restart"]
            root = Path(__file__).resolve().parents[1]

        attempts: list[int] = [0]
        if sys.platform == "win32":
            # DETACHED_PROCESS | CREATE_NO_WINDOW: no console window, and the
            # new copy outlives this one.  CREATE_BREAKAWAY_FROM_JOB is tried
            # first so a launcher that runs us inside a job object (some
            # terminals and installers do) cannot kill the restarted overlay
            # when the old process exits; it is rejected by jobs that do not
            # allow breakaway, hence the plain retry.
            detached = 0x00000008 | 0x08000000
            attempts = [detached | 0x01000000, detached]

        started = False
        for flags in attempts:
            kwargs: dict = {"cwd": str(root), "close_fds": True}
            if flags:
                kwargs["creationflags"] = flags
            try:
                subprocess.Popen(args, **kwargs)
                started = True
                break
            except OSError as exc:
                log.warning("restart with flags %#x failed (%s)", flags, exc)
                continue
        log.debug("restart: %s", "new copy started" if started else "failed")
        if not started:
            self.panel.set_state("error")
            self.panel.set_scan_idle("Restart failed - quit and start again")
            return
        self.quit()

    def _install_update(self, setup_path: str) -> None:
        """Installed EXE: run the downloaded Setup once this copy has quit.

        Setup refuses while SC Assistant runs, so it is started by a
        helper that waits for this process to exit; Setup then replaces the
        files and starts the new version (/LAUNCH=1).
        """
        from . import updater

        log.debug("update: handing off to %s", setup_path)
        try:
            updater.run_installer(Path(setup_path))
        except Exception as exc:          # never quit without a hand-off
            log.warning("update hand-off failed (%s)", exc)
            self.settings.install_failed(f"Update failed: {exc}")
            return
        log.debug("update: installer started, quitting")
        self.quit()

    def quit(self) -> None:
        self._save_state()
        self._stop_saving()       # closing the windows below is not a change
        self.combat.close()
        self.blueprint_tracker.close()
        self.scan.stop()
        self.scan.wait(1500)
        self.hotkeys.stop()
        self.hotkeys.wait(800)
        self.hauling.shutdown()
        # Cancel an UPDATE download in progress and wait for its thread.
        self.settings.shutdown()
        self.voice.stop()
        self.settings.hide()
        self._close_log_viewer()
        self.tray.hide()
        self.app.quit()

    def dispose(self) -> None:
        """Delete the windows while the QApplication is still alive.

        Top-level widgets have no Qt parent, so they are owned by Python.  If
        the interpreter frees the QApplication first, Qt frees those widgets a
        second time in its exit handlers, which on Windows shows up as an
        intermittent access violation (0xC0000005) after a clean quit.
        """
        self._stop_saving()
        widgets = [self.nav, self.panel, self.settings, self.orefinder,
                   self.hauling, self.inventory, self.combat_panel]
        if self._log_viewer is not None:
            widgets.append(self._log_viewer)
        for widget in widgets:
            try:
                widget.hide()
                widget.deleteLater()
            except RuntimeError:
                pass          # already deleted by Qt
        try:
            self.tray.hide()
            self.tray.setContextMenu(None)
            self.tray.deleteLater()
            self._tray_menu.deleteLater()
        except RuntimeError:
            pass
        self.app.processEvents()


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    _install_crash_log()
    parser = argparse.ArgumentParser(prog="sc-assistant", description="Star Citizen overlay")
    parser.add_argument("--demo", action="store_true",
                        help="run the mining scanner against a synthetic signature")
    parser.add_argument("--capture-visible", action="store_true",
                        help="do not hide the overlay from screen capture (debugging/streaming)")
    parser.add_argument("--open", choices=("mining", "orefinder",
                                           "hauling", "inventory", "uex",
                                           "combat", "notes", "settings"),
                        help="open a tool at startup (debugging)")
    parser.add_argument("--restart", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version",
                        version=f"{APP_NAME} {version_label()}")
    args = parser.parse_args(argv)

    if not _acquire_single_instance(replacing=args.restart):
        _already_running_notice()
        return 0

    cfg = _startup_config()
    # The overlay scales itself (see ui/theme.py) instead of relying on
    # QT_SCALE_FACTOR: Qt only applies that variable to widget geometry on
    # Windows/Linux, so on macOS the slider appeared to do nothing.
    # The panels are built once, so a new scale needs a restart.
    theme.set_scale(cfg.get("ui_scale", 1.0))

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_TITLE)
    app.setWindowIcon(QIcon(str(ICON_PATH)) if ICON_PATH.exists()
                      else _tray_icon())
    app.setQuitOnLastWindowClosed(False)

    overlay = OverlayApp(app, cfg, demo=args.demo,
                         capture_visible=args.capture_visible,
                         launch_args=(list(argv) if argv is not None
                                      else sys.argv[1:]))
    # overlay.cfg via save_config: RESET SETTINGS replaces it and turns
    # saving off, so quitting cannot write the old settings back.
    app.aboutToQuit.connect(overlay.save_config)
    overlay.start()
    if args.open:
        QTimer.singleShot(350, lambda: overlay.open_tool(args.open))
    code = app.exec()
    overlay.dispose()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
