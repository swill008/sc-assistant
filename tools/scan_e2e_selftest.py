"""End-to-end scanner check on the real screen, with a real 5K2K signature.

    python -m tools.scan_e2e_selftest            # on a secondary monitor
    python -m tools.scan_e2e_selftest --primary  # on the main (game) monitor

Needs a Windows desktop. For a few seconds it shows a 240 x 110 crop of a
5120 x 2160 Star Citizen screenshot (signature 42,000) at 1:1 physical pixels
on a secondary monitor, or the primary if there is only one, then:

1. drags a box around the digits with the real region picker (the cursor
   position is fed through its ``cursor_pos`` hook, so the mouse never moves);
   a right-click on a second (invisible) picker cancels it;
2. grabs that box with the app's capture code and reads it with the app's OCR;
3. turns on SHOW BOX and checks the capture is pixel-for-pixel unchanged, so
   the outline can never be read by the scanner;
4. builds the real OverlayApp against a temporary config folder (your own
   %APPDATA% settings are never touched) and checks the running scanner reads
   42,000, READS / S changes the live scan interval and the saved config, SHOW
   BOX shows and F4 hides the outline, a monitor resolution change rescales the
   box and says so, the monitor choice is saved, and QUIT stops the scanner;
5. HUD tracking, inside that app: DRAW REGION on the box saves the pin anchor;
   with the signature moved by a HUD-sized sway (+150, +100 px) the scanner
   still reads it, its ``tracked`` rect sits on the moved digits and the fixed
   box alone would not read it; SHOW BOX follows the digits; with the
   signature gone nothing is read and the OCR is never run (counted by
   wrapping SignatureOCR.read for calls off the GUI thread); TRACKING at 0
   goes back to the fixed box.
6. Tracking feedback (plan A): after DRAW REGION a 3-second confirmation
   "PIN FOUND — TRACKING ON" marks the fixture's real pin and digits even
   with SHOW BOX off; with SHOW BOX on the outline says "TRACKING ✓  42,000"
   (locked), SEARCHING when the plate is gone and FIXED BOX at TRACKING 0, and
   the scanner panel's chip (``panel.track_state``) agrees each time.
7. Upgrade (plan B): the app starts from a config with a box but no pin and
   learns the pin from the first exact read.
8. Pins: a pinned panel stays visible after hide-all, an unpinned one hides
   (both shown at opacity 0).
9. Result border (plan L): SCANNED SIGNATURE shows the read and the border
   is green on the confirmed exact read; never red with the plate gone or
   with TRACKING 0; back to None once the card is lost.
10. Whole signature window (plan R): DRAW REGION round the whole fixture
   finds the pin, saves the digits box, pin and plate, tracks 42,000, and the
   Settings preview gets the window with the pin and digits rects (on a
   2160-px-high monitor; skipped elsewhere).
11. First run (plan J-i): with no box the nav ⚙ and DRAW REGION ask for
   attention; both stop once a box exists.

Exit code = number of failed checks.
"""
from __future__ import annotations

from tools import _testguard

_testguard.install()        # first: no focus, no hotkeys

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Before anything imports app.config: keep the test's settings out of the
# user's real config folder.
_TMP = tempfile.TemporaryDirectory(prefix="ca-e2e-")
os.environ["APPDATA"] = _TMP.name

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

FIXTURE = ROOT / "tools" / "fixtures" / "signal_42000_5k2k.png"
DIGITS = {"left": 76, "top": 38, "width": 56, "height": 28}   # inside the fixture
EXPECTED = 42000
SWAY = (150, 100)        # physical px the HUD moves the plate (right, down)
NEAR = 3                 # px a tracked rect may be off the true digits
# The white ink of "42,000" in the fixture, measured from its pixels (x, y, w, h).
DIGITS_INK = (77, 47, 47, 16)
CONFIRM_TEXT = "PIN FOUND — TRACKING ON"
LOCKED_TEXT = f"TRACKING ✓  {EXPECTED:,}"
CONFIRM_SECONDS = 3.0

# SignatureOCR.read calls made by the scan thread (not the test's own reads).
_SCAN_OCR_CALLS = [0]


def _count_scan_ocr() -> None:
    from app.ocr import SignatureOCR

    real = SignatureOCR.read
    if getattr(real, "_e2e_counted", False):
        return

    def read(self, *args, **kwargs):
        if threading.current_thread() is not threading.main_thread():
            _SCAN_OCR_CALLS[0] += 1
        return real(self, *args, **kwargs)

    read._e2e_counted = True
    SignatureOCR.read = read


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


class _Fixture(QWidget):
    """Shows the screenshot crop with one image pixel per physical pixel."""

    def __init__(self, image: QImage):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._image = image

    def paintEvent(self, event):  # noqa: N802
        pix = QPixmap.fromImage(self._image)
        pix.setDevicePixelRatio(self.devicePixelRatio())
        QPainter(self).drawPixmap(0, 0, pix)


def _wait(cond, seconds: float = 8.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        _pump(0.05)
    return bool(cond())


def _move(widget, rect: dict) -> None:
    from app import win32

    win32.place_physical(widget, rect)
    _pump(0.2)
    win32.place_physical(widget, rect)
    _pump(0.2)


def _on_digits(rect, digits: dict) -> bool:
    """A tracked rect sits on the digits: same top-left and height (within
    NEAR), at least as wide (it may cover up to 6 digits)."""
    if not rect:
        return False
    return (abs(rect["left"] - digits["left"]) <= NEAR
            and abs(rect["top"] - digits["top"]) <= NEAR
            and abs(rect["height"] - digits["height"]) <= NEAR
            and rect["left"] + rect["width"] >= digits["left"] + digits["width"] - NEAR)


def _on_pin(rect, pin: dict) -> bool:
    """A pin mark covers the real pin: every edge within NEAR."""
    if not rect:
        return False
    return (abs(rect["left"] - pin["left"]) <= NEAR
            and abs(rect["top"] - pin["top"]) <= NEAR
            and abs(rect["left"] + rect["width"] - pin["left"] - pin["width"]) <= NEAR
            and abs(rect["top"] + rect["height"] - pin["top"] - pin["height"]) <= NEAR)


def _shift(rect: dict, dx: int, dy: int) -> dict:
    return dict(rect, left=rect["left"] + dx, top=rect["top"] + dy)


def _contains(outer, inner) -> bool:
    return bool(outer) and bool(inner) and (
        outer["left"] <= inner["left"] and outer["top"] <= inner["top"]
        and outer["left"] + outer["width"] >= inner["left"] + inner["width"]
        and outer["top"] + outer["height"] >= inner["top"] + inner["height"])


def _close_to(a, b, tol: int = 2) -> bool:
    return bool(a) and bool(b) and all(abs(a[k] - b[k]) <= tol
                                       for k in ("left", "top", "width", "height"))


def _inside(ring):
    """The box an outline window surrounds (inverse of outline_rect)."""
    from app.ui.region_outline import GAP, LINE

    if not ring:
        return None
    pad = GAP + LINE
    return {"left": ring["left"] + pad, "top": ring["top"] + pad,
            "width": ring["width"] - 2 * pad, "height": ring["height"] - 2 * pad}


def _show_fixture(screen):
    from app import display, win32

    image = QImage(str(FIXTURE))
    mon = display.physical_rect(screen)
    rect = {"left": mon["left"] + mon["width"] // 2 - image.width() // 2,
            "top": mon["top"] + mon["height"] // 2 - image.height() // 2,
            "width": image.width(), "height": image.height()}
    w = _Fixture(image)
    w.setScreen(screen)
    w.setGeometry(display.logical_geometry(rect, screen))
    w.show()
    win32.place_physical(w, rect)
    _pump(0.3)
    win32.place_physical(w, rect)
    _pump(0.5)
    return w, rect, image


def _image_bgr(image: QImage) -> np.ndarray:
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    arr = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
    return arr[:, :image.width() * 3].reshape(image.height(), image.width(), 3)[:, :, ::-1].copy()


def _fixture_pin(image: QImage) -> dict:
    """The orange pin icon's box inside the fixture, measured from its pixels
    (the most orange part of the strip left of the digits), independently of
    app.tracking."""
    bgr = _image_bgr(image).astype(int)
    orange = np.clip(bgr[:, :, 2] - bgr[:, :, 0], 0, 255)
    y0 = DIGITS["top"] - DIGITS["height"] // 2
    y1 = DIGITS["top"] + DIGITS["height"] + DIGITS["height"] // 2
    strip = orange[y0:y1, 0:DIGITS["left"]]
    ys, xs = np.nonzero(strip >= 0.75 * np.percentile(strip, 99.5))
    return {"left": int(xs.min()), "top": int(y0 + ys.min()),
            "width": int(xs.max() - xs.min() + 1), "height": int(ys.max() - ys.min() + 1)}


def part_screen_path(screen) -> tuple[int, dict | None]:
    from app.capture import ScreenGrabber
    from app.ocr import SignatureOCR
    from app.ui.region_outline import RegionOutline, outline_rect
    from app.ui.region_selector import RegionSelector

    failures = 0
    fixture, frect, image = _show_fixture(screen)
    grab = ScreenGrabber()
    shot = grab.grab(frect)
    diff = np.abs(shot.astype(int) - _image_bgr(image).astype(int)).max()
    failures += _check("signature shown 1:1 on screen", diff <= 2, f"(max pixel difference {diff})")

    # 1. Drag around the digits with the real picker on that monitor.
    want = {"left": frect["left"] + DIGITS["left"], "top": frect["top"] + DIGITS["top"],
            "width": DIGITS["width"], "height": DIGITS["height"]}
    cursor = [(want["left"], want["top"])]
    picked: list[dict] = []
    picker = RegionSelector("e2e", cursor_pos=lambda: cursor[0], screens=[screen])
    picker.selected.connect(picked.append)
    for w in picker.windows:
        w.setWindowOpacity(0.0)        # before show: never a visible frame
    picker.show()
    QApplication.processEvents()
    win = picker.windows[0]
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    cursor[0] = (want["left"] + want["width"], want["top"] + want["height"])
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, 30))
    _pump(0.3)
    region = picked[-1] if picked else None
    failures += _check("picker stores the dragged box", region == want, f"(want {want}, got {region})")

    # 1b. Right-click cancels the picker (J-f), on an invisible picker.
    cursor[0] = (want["left"], want["top"])
    cancelled: list[bool] = []
    picked2: list[dict] = []
    picker2 = RegionSelector("e2e", cursor_pos=lambda: cursor[0], screens=[screen])
    picker2.cancelled.connect(lambda: cancelled.append(True))
    picker2.selected.connect(picked2.append)
    windows2 = list(picker2.windows)
    for w in windows2:
        w.setWindowOpacity(0.0)
    picker2.show()
    QApplication.processEvents()
    QTest.mouseClick(windows2[0], Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(20, 20))
    _pump(0.3)
    failures += _check("picker: right-click cancels", bool(cancelled) and not picked2,
                       f"(cancelled {len(cancelled)}, selected {picked2})")
    still = [w for w in windows2 if _alive_visible(w)]
    failures += _check("picker: right-click closes its windows", not still,
                       f"({len(still)} picker window(s) still shown)")
    if still:
        picker2.close()

    if region is None:
        fixture.close()
        return failures + 1, None

    # 2. Capture + OCR exactly as the scanner does.
    ocr = SignatureOCR(threads=1)
    crop = grab.grab(region)
    res = ocr.read(crop)
    failures += _check(f"OCR reads {EXPECTED:,} from the box", res.value == EXPECTED,
                       f"(read {res.value}, confidence {res.confidence:.2f}, raw {res.raw!r})")

    # 3. SHOW BOX must not change what is captured.
    ring = outline_rect(region)
    before_box, before_ring = grab.grab(region), grab.grab(ring)
    outline = RegionOutline()
    outline.show_region(region)
    _pump(0.5)
    visible = outline.isVisible()
    after_box, after_ring = grab.grab(region), grab.grab(ring)
    failures += _check("outline is shown", visible)
    failures += _check("box capture unchanged with the outline on",
                       np.array_equal(before_box, after_box))
    failures += _check("outline invisible to capture (ring pixels unchanged)",
                       np.array_equal(before_ring, after_ring))
    res2 = ocr.read(after_box)
    failures += _check(f"OCR still reads {EXPECTED:,} with the outline on", res2.value == EXPECTED,
                       f"(read {res2.value})")
    outline.close()
    grab.close()
    pin = _shift(_fixture_pin(image), frect["left"], frect["top"])
    print(f"  (fixture pin measured at {pin})")
    return failures, {"fixture": fixture, "rect": frect, "region": region, "pin": pin}


def _alive_visible(widget) -> bool:
    try:
        return widget.isVisible()
    except RuntimeError:          # deleted by Qt: closed
        return False


def part_app(screen, shown: dict) -> int:
    from app import display
    from app.config import CONFIG_PATH, Config, config_dir
    from app.main import OverlayApp

    failures = 0
    region = shown["region"]
    mon = display.physical_rect(screen)
    # An old-style config (plan B): a box but no pin saved with it.
    cfg = Config()
    cfg["region"] = region
    cfg["region_monitor"] = mon
    cfg["game_monitor"] = screen.name()
    cfg["voice_enabled"] = False
    cfg["nav_visible"] = False            # keep the nav bar off the game screen
    cfg["anchor"] = None
    cfg.save()

    app = QApplication.instance()
    _count_scan_ocr()
    overlay = OverlayApp(app, Config.load())
    seen = {"results": [], "tracked": [], "states": []}
    overlay.scan.result.connect(
        lambda res, _m: seen["results"].append((time.monotonic(), getattr(res, "value", None))))
    has_tracked = hasattr(overlay.scan, "tracked")
    if has_tracked:
        overlay.scan.tracked.connect(
            lambda rect: seen["tracked"].append((time.monotonic(), rect)))
    has_states = hasattr(overlay.scan, "track_state")
    if has_states:
        overlay.scan.track_state.connect(
            lambda info: seen["states"].append((time.monotonic(), info)))
    overlay.start()
    overlay.panel.hide()                  # the scanner panel opens on the main screen
    chip_at_start = getattr(overlay.panel, "track_state", "<missing>")

    # The real scan thread (low priority, 1 OCR thread) reads the live box.
    end = time.monotonic() + 8
    while time.monotonic() < end and overlay._last_value != EXPECTED:
        _pump(0.1)
    failures += _check(f"running scanner reads {EXPECTED:,}", overlay._last_value == EXPECTED,
                       f"(last value {overlay._last_value})")
    panel = overlay.panel
    failures += _check(f"SCANNED SIGNATURE shows {EXPECTED:,}",
                       f"{EXPECTED:,}" in getattr(panel, "scanned_text", ""),
                       f"({getattr(panel, 'scanned_text', '<missing>')!r})")
    failures += _check("confirmed exact read: green result border",
                       getattr(panel, "result", "<missing>") == "match",
                       f"(panel.result {getattr(panel, 'result', '<missing>')!r})")
    failures += _check("scanner thread runs at low priority",
                       overlay.scan.priority() == overlay.scan.Priority.LowPriority,
                       f"(priority {overlay.scan.priority()})")

    print("  -- upgrade: box without a pin (plan B) --")
    failures += _check("ScanThread has the track_state signal", has_states)
    failures += _check("chip shows FIXED BOX at start (box, no pin yet)", chip_at_start == "fixed",
                       f"(panel.track_state {chip_at_start!r})")
    png = config_dir() / "anchor.png"
    ok = _wait(lambda: bool(overlay.cfg.get("anchor")) and png.is_file(), 6.0)
    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    failures += _check("first exact read learns the pin and saves it", ok and bool(saved.get("anchor")),
                       f"(anchor in memory {overlay.cfg.get('anchor')}, saved {saved.get('anchor')}, "
                       f"anchor.png {png.is_file()})")
    ok = _wait(lambda: getattr(overlay.panel, "track_state", None) == "locked", 6.0)
    states = [info.get("state") for _t, info in seen["states"] if isinstance(info, dict)]
    failures += _check("after learning: scanner tracks (state locked), chip TRACKING", ok
                       and "locked" in states,
                       f"(panel {getattr(overlay.panel, 'track_state', '<missing>')!r}, "
                       f"emitted {states})")
    failures += _check("the first state emitted was fixed (before the pin was learned)",
                       bool(states) and states[0] == "fixed", f"(emitted {states})")

    print("  -- HUD tracking --")
    failures += _check("ScanThread has the tracked signal", has_tracked)
    if has_tracked:
        failures += part_tracking(overlay, shown, seen)
    print("  -- settings --")

    # READS / S: live interval and saved config.
    overlay.settings.reads_slider.setValue(2)
    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    failures += _check("READS / S 2 sets a 500 ms scan interval", overlay.scan._interval == 500,
                       f"(interval {overlay.scan._interval})")
    failures += _check("READS / S is saved", saved.get("poll_ms") == 500, f"(saved {saved.get('poll_ms')})")

    # SHOW BOX on, F4 hides it.
    overlay.settings.outline_btn.setChecked(True)
    _pump(0.4)
    failures += _check("SHOW BOX shows the outline", overlay.outline.isVisible())
    overlay._on_hotkey(2)
    _pump(0.2)
    failures += _check("F4 hides the outline", not overlay.outline.isVisible())

    # Resolution change: pretend the box was drawn when this monitor was
    # twice the size, then let the app check the displays.
    bigger = {"left": mon["left"], "top": mon["top"], "width": mon["width"] * 2, "height": mon["height"] * 2}
    drawn = display.rescale(region, mon, bigger)
    overlay.cfg["region"] = drawn
    overlay.cfg["region_monitor"] = bigger
    overlay._check_display()
    want = display.rescale(drawn, bigger, mon)
    failures += _check("resolution change rescales the box", overlay.cfg["region"] == want,
                       f"(want {want}, got {overlay.cfg['region']})")
    failures += _check("scanner follows the rescaled box", overlay.scan._region == want)
    failures += _check("Settings says the box was adjusted",
                       overlay.settings.region_note.isVisibleTo(overlay.settings)
                       and "Monitor changed" in overlay.settings.region_note.text(),
                       f"(note {overlay.settings.region_note.text()!r})")

    # The monitor list holds every monitor; choosing another one is saved and
    # moves the box onto it (same rule as a resolution change).
    box = overlay.settings.monitor_box
    names = [box.itemData(i) for i in range(box.count())]
    failures += _check("MONITOR list has every monitor",
                       sorted(names) == sorted(s.name() for s in QGuiApplication.screens()),
                       f"({[box.itemText(i) for i in range(box.count())]})")
    failures += _check("MONITOR list shows the game monitor",
                       box.currentData() == screen.name(), f"(current {box.currentData()!r})")
    # Another side monitor if there is one, so the moved box stays off the game screen.
    primary = QGuiApplication.primaryScreen()
    others = [s for s in QGuiApplication.screens() if s is not screen]
    other = next((s for s in others if s is not primary), others[0] if others else None)
    if other is not None:
        before = dict(overlay.cfg["region"])
        box.setCurrentIndex(box.findData(other.name()))
        box.activated.emit(box.currentIndex())
        moved = display.rescale(before, mon, display.physical_rect(other))
        failures += _check("choosing another monitor is saved", overlay.cfg["game_monitor"] == other.name(),
                           f"(saved {overlay.cfg['game_monitor']!r})")
        failures += _check("choosing another monitor moves the box onto it",
                           overlay.cfg["region"] == moved and overlay.scan._region == moved,
                           f"(want {moved}, got {overlay.cfg['region']})")

    print("  -- pins --")
    failures += part_pins(overlay)

    # QUIT needs two clicks, then stops the scanner and saves.
    overlay.nav.quit_btn.click()
    _pump(0.1)
    failures += _check("one QUIT click keeps the app running", overlay.scan.isRunning())
    overlay.nav.quit_btn.click()
    _pump(0.3)
    failures += _check("second QUIT click stops the scanner", overlay.scan.isFinished())
    failures += _check("QUIT hides the tray icon", not overlay.tray.isVisible())
    overlay.outline.hide()
    for w in (overlay.nav, overlay.panel, overlay.settings):
        w.hide()
    return failures


def part_pins(overlay) -> int:
    """A pinned panel survives hide-all; an unpinned one hides. The panels are
    shown at opacity 0 (they open on the main screen)."""
    from app.config import CONFIG_PATH

    failures = 0
    panel, settings = overlay.panel, overlay.settings
    btn = getattr(panel, "pin_button", None)
    failures += _check("scanner panel has a pin button", btn is not None)
    if btn is None:
        return failures
    for w in (panel, settings):
        w.setWindowOpacity(0.0)           # before show: never visible on the game screen
        w.show()
    _pump(0.2)
    if btn.isChecked():
        btn.click()                       # start unpinned
    btn.click()                           # the user pins the scanner panel
    _pump(0.1)
    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    failures += _check("pinning is saved (pinned_windows has mining)",
                       "mining" in (saved.get("pinned_windows") or []) and panel.pinned,
                       f"(saved {saved.get('pinned_windows')}, panel.pinned {panel.pinned})")
    overlay._hide_all()
    _pump(0.2)
    failures += _check("hide-all keeps the pinned scanner panel visible", panel.isVisible())
    failures += _check("hide-all hides the unpinned Settings panel", not settings.isVisible())
    btn.click()                           # unpin
    _pump(0.1)
    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    failures += _check("unpinning is saved", "mining" not in (saved.get("pinned_windows") or []),
                       f"(saved {saved.get('pinned_windows')})")
    overlay._hide_all()
    _pump(0.2)
    failures += _check("hide-all hides the unpinned scanner panel", not panel.isVisible())
    return failures


def part_tracking(overlay, shown: dict, seen: dict) -> int:
    from app import win32
    from app.capture import ScreenGrabber
    from app.config import CONFIG_PATH, config_dir
    from app.ocr import SignatureOCR
    from app.ui.region_outline import outline_rect

    failures = 0
    fixture, frect, region, pin = shown["fixture"], shown["rect"], shown["region"], shown["pin"]
    dx, dy = SWAY
    moved_rect = dict(frect, left=frect["left"] + dx, top=frect["top"] + dy)
    moved_digits = dict(region, left=region["left"] + dx, top=region["top"] + dy)
    moved_pin = _shift(pin, dx, dy)
    outline = overlay.outline

    def last_tracked():
        return seen["tracked"][-1][1] if seen["tracked"] else None

    def values_since(t0):
        return [v for t, v in seen["results"] if t >= t0]

    def outline_now():
        return win32.physical_window_rect(outline) if outline.isVisible() else None

    def marks():
        return getattr(outline, "marks", None) or {}

    def outline_digits():
        """The digits box the outline is drawn around (marks or plain ring)."""
        m = marks()
        return m.get("digits") if m else _inside(outline_now())

    def chip():
        return getattr(overlay.panel, "track_state", "<missing>")

    def last_state():
        return seen["states"][-1][1].get("state") if seen["states"] else None

    def window_holds_marks() -> bool:
        m, got = marks(), outline_now()
        rects = [outline_rect(m["digits"])] + ([outline_rect(m["pin"])] if m.get("pin") else [])
        return all(_contains(got, r) for r in rects) if m else False

    def describe() -> str:
        return (f"(visible {outline.isVisible()}, state {getattr(outline, 'state', '<missing>')!r}, "
                f"label {getattr(outline, 'label', '<missing>')!r}, marks {marks()}, "
                f"window {outline_now()}, chip {chip()!r}, last emitted {last_state()!r})")

    # Every border change main.py asks of the panel, with its time.
    borders: list = []
    panel_set_result = getattr(overlay.panel, "set_result", None)
    if panel_set_result is not None:
        def set_result(result, _real=panel_set_result):
            borders.append((time.monotonic(), result))
            _real(result)
        overlay.panel.set_result = set_result

    def borders_since(t0):
        return [r for t, r in borders if t >= t0]

    # 1. DRAW REGION through the app with the plate on the drawn box: the app grabs
    #    the screen around it and saves the pin anchor. The pin learned at start
    #    (plan B) is removed first so this save is DRAW REGION's own.
    png = config_dir() / "anchor.png"
    png.unlink(missing_ok=True)
    failures += _check("SHOW BOX is off before DRAW REGION",
                       not overlay.cfg.get("show_region_outline") and not outline.isVisible())
    t_draw = time.monotonic()
    overlay._on_region_selected(dict(region))
    confirm = _wait(lambda: outline.isVisible()
                    and getattr(outline, "label", None) == CONFIRM_TEXT, 1.5)
    failures += _check(f"DRAW REGION shows '{CONFIRM_TEXT}' with SHOW BOX off", confirm, describe())
    failures += _check("confirmation is in the locked state", getattr(outline, "state", None) == "locked",
                       describe())
    failures += _check("confirmation marks the fixture's real pin (within 3 px)",
                       _on_pin(marks().get("pin"), pin), f"(want ~{pin}, got {marks().get('pin')})")
    failures += _check("confirmation marks the digits (within 3 px)",
                       _on_digits(marks().get("digits"), region),
                       f"(want ~{region}, got {marks().get('digits')})")
    failures += _check("confirmation window on screen holds both marks", window_holds_marks(),
                       f"(window {outline_now()}, marks {marks()})")
    meta = overlay.cfg.get("anchor")
    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    failures += _check("DRAW REGION saves the pin anchor in the config",
                       bool(meta) and saved.get("anchor") == meta, f"(anchor {meta})")
    failures += _check("DRAW REGION writes anchor.png in the config folder", png.is_file(), f"({png})")
    note = overlay.settings.region_note
    failures += _check("no 'No pin icon' note after DRAW REGION", "No pin icon" not in note.text(),
                       f"(note {note.text()!r})")
    _pump(max(0.0, t_draw + CONFIRM_SECONDS - 0.8 - time.monotonic()))
    failures += _check("confirmation still shown ~2 s after DRAW REGION", outline.isVisible(),
                       f"({time.monotonic() - t_draw:.1f} s) {describe()}")
    gone = _wait(lambda: not outline.isVisible(),
                 max(0.1, t_draw + CONFIRM_SECONDS + 1.5 - time.monotonic()))
    failures += _check("confirmation gone after ~3 s (SHOW BOX off)", gone,
                       f"({time.monotonic() - t_draw:.1f} s) {describe()}")
    ok = _wait(lambda: overlay._last_value == EXPECTED and _on_digits(last_tracked(), region))
    failures += _check(f"tracking reads {EXPECTED:,} on the calibrated box", ok,
                       f"(last value {overlay._last_value}, tracked {last_tracked()})")
    ok = _wait(lambda: chip() == "locked" and last_state() == "locked", 3.0)
    failures += _check("chip and scanner say locked on the calibrated box", ok, describe())

    # 2. HUD sway: the plate moves off the box.
    _move(fixture, moved_rect)
    overlay._last_value = None
    t_move = time.monotonic()
    _wait(lambda: overlay._last_value == EXPECTED and _on_digits(last_tracked(), moved_digits))
    failures += _check(f"plate moved {dx:+d},{dy:+d} px: scanner still reads {EXPECTED:,}",
                       overlay._last_value == EXPECTED and EXPECTED in values_since(t_move),
                       f"(last value {overlay._last_value}, took {time.monotonic() - t_move:.1f} s)")
    failures += _check("tracked rect sits on the moved digits", _on_digits(last_tracked(), moved_digits),
                       f"(want ~{moved_digits}, got {last_tracked()})")
    st = seen["states"][-1][1] if seen["states"] else {}
    failures += _check("track_state locked with digits and pin on the moved plate",
                       st.get("state") == "locked" and _on_digits(st.get("digits"), moved_digits)
                       and _on_pin(st.get("pin"), moved_pin),
                       f"(emitted {st}, want pin ~{moved_pin})")
    grab = ScreenGrabber()
    fixed = SignatureOCR(threads=1).read(grab.grab(region))
    grab.close()
    failures += _check(f"the fixed box alone does not read {EXPECTED:,} there", fixed.value != EXPECTED,
                       f"(fixed box read {fixed.value})")

    # 3. SHOW BOX follows the tracked digits, marks the pin, says TRACKING ✓ value.
    overlay.settings.outline_btn.setChecked(True)
    _wait(lambda: _on_digits(outline_digits(), moved_digits)
          and getattr(outline, "label", None) == LOCKED_TEXT, 3.0)
    failures += _check("SHOW BOX outline follows the tracked digits",
                       _on_digits(outline_digits(), moved_digits),
                       f"(outline {outline_now()}, digits {outline_digits()}, want around {moved_digits})")
    failures += _check("SHOW BOX: outline.state locked", getattr(outline, "state", None) == "locked",
                       describe())
    failures += _check(f"SHOW BOX: label '{LOCKED_TEXT}'", getattr(outline, "label", None) == LOCKED_TEXT,
                       describe())
    failures += _check("SHOW BOX: pin mark on the moved pin", _on_pin(marks().get("pin"), moved_pin),
                       f"(want ~{moved_pin}, got {marks().get('pin')})")
    failures += _check("SHOW BOX: window on screen holds both marks", window_holds_marks(),
                       f"(window {outline_now()}, marks {marks()})")
    failures += _check("SHOW BOX locked: chip TRACKING", chip() == "locked", describe())

    # 4. Plate gone: results with no value, and no OCR while no pin is found.
    fixture.hide()
    _pump(0.8)              # let a read already in flight finish
    t_gone, calls = time.monotonic(), _SCAN_OCR_CALLS[0]
    _pump(2.5)
    gone = values_since(t_gone)
    failures += _check("plate gone: scanner still reports (empty) results", len(gone) > 0,
                       f"({len(gone)} results)")
    failures += _check("plate gone: no value read", all(v is None for v in gone),
                       f"(values {sorted(set(map(str, gone)))})")
    failures += _check("plate gone: OCR never run", _SCAN_OCR_CALLS[0] == calls,
                       f"({_SCAN_OCR_CALLS[0] - calls} scan-thread OCR calls in 2.5 s)")
    failures += _check("plate gone: tracked reports None", last_tracked() is None,
                       f"(tracked {last_tracked()})")
    _wait(lambda: getattr(outline, "state", None) == "searching", 2.0)
    failures += _check("plate gone: track_state searching", last_state() == "searching", describe())
    failures += _check("plate gone: SHOW BOX outline.state searching",
                       outline.isVisible() and getattr(outline, "state", None) == "searching", describe())
    failures += _check("plate gone: chip SEARCHING", chip() == "searching", describe())
    failures += _check("plate gone: never a red border", "noread" not in borders_since(t_gone),
                       f"(borders {borders_since(t_gone)})")
    failures += _check("plate gone > 2 s: card lost, border back to None",
                       getattr(overlay.panel, "result", "<missing>") is None,
                       f"(panel.result {getattr(overlay.panel, 'result', '<missing>')!r})")

    fixture.show()
    _move(fixture, moved_rect)
    overlay._last_value = None
    ok = _wait(lambda: overlay._last_value == EXPECTED and _on_digits(last_tracked(), moved_digits))
    failures += _check(f"plate back: tracking reads {EXPECTED:,} again", ok,
                       f"(last value {overlay._last_value}, tracked {last_tracked()})")
    ok = _wait(lambda: getattr(outline, "state", None) == "locked" and chip() == "locked", 3.0)
    failures += _check("plate back: outline and chip locked again", ok, describe())

    # 5. TRACKING at 0: back to the fixed box. The slider is dragged (pressed,
    #    moved, released) because the setting is saved on release.
    slider = overlay.settings.tracking_slider
    slider.setSliderDown(True)
    slider.setValue(0)
    slider.setSliderDown(False)
    _pump(0.3)
    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    failures += _check("TRACKING 0 is saved", saved.get("tracking_range") == 0,
                       f"(saved {saved.get('tracking_range')})")
    failures += _check("TRACKING 0 shows OFF", overlay.settings.tracking_label.text() == "OFF",
                       f"({overlay.settings.tracking_label.text()!r})")
    overlay._last_value = None
    _pump(0.8)
    t_off = time.monotonic()
    _pump(2.5)
    off = values_since(t_off)
    failures += _check("TRACKING 0 (tracking off): never a red border",
                       "noread" not in borders_since(t_off), f"(borders {borders_since(t_off)})")
    failures += _check("TRACKING 0: the moved plate is not read",
                       EXPECTED not in off and overlay._last_value != EXPECTED and len(off) > 0,
                       f"({len(off)} results, values {sorted(set(map(str, off)))})")
    # DRAW REGION with a pin saves the digits box worked out from the pin
    # (plan R), which sits on the drawn digits.
    fixed_box = overlay.cfg["region"]
    _wait(lambda: _close_to(outline_digits(), fixed_box), 3.0)
    failures += _check("TRACKING 0: SHOW BOX outline back on the fixed (saved) box, on the digits",
                       _close_to(outline_digits(), fixed_box) and _on_digits(fixed_box, region),
                       f"(outline {outline_now()}, digits {outline_digits()}, want {fixed_box} ~ {region})")
    failures += _check("TRACKING 0: outline.state fixed, no pin mark",
                       getattr(outline, "state", None) == "fixed" and not marks().get("pin"), describe())
    failures += _check("TRACKING 0: track_state fixed, chip FIXED BOX",
                       last_state() == "fixed" and chip() == "fixed", describe())
    _move(fixture, frect)
    t_back = time.monotonic()
    ok = _wait(lambda: overlay._last_value == EXPECTED)
    failures += _check(f"TRACKING 0: plate back on the box reads {EXPECTED:,}", ok,
                       f"(last value {overlay._last_value}, took {time.monotonic() - t_back:.1f} s)")

    overlay.settings.outline_btn.setChecked(False)
    _pump(0.3)
    failures += part_whole_window(overlay, shown, seen)
    return failures


def part_whole_window(overlay, shown: dict, seen: dict) -> int:
    """DRAW REGION round the whole signature window (plan R): the app finds
    the pin inside it, saves the digits box, pin and plate, tracks and reads
    the digits, and the Settings preview gets the whole window with the pin
    and digits outlined."""
    from app import display
    from app.config import CONFIG_PATH, config_dir

    failures = 0
    fixture, frect, region, pin = shown["fixture"], shown["rect"], shown["region"], shown["pin"]
    screen = display.screen_of_region(frect)
    if screen is None or display.physical_rect(screen)["height"] != 2160:
        print("  SKIP  whole-window DRAW REGION: the fixture is a 2160-px-high HUD; "
              "this monitor is not 2160 px high")
        return 0
    print("  -- whole signature window (plan R) --")
    outline = overlay.outline
    previews: list = []
    real_preview = overlay.settings.set_preview

    def set_preview(crop, pin=None, digits=None, _real=real_preview):
        previews.append((None if crop is None else crop.shape[:2], pin, digits))
        _real(crop, pin, digits)
    overlay.settings.set_preview = set_preview
    overlay._on_tracking(400)
    _move(fixture, frect)
    (config_dir() / "anchor.png").unlink(missing_ok=True)
    overlay._on_region_selected(dict(frect))
    ok = _wait(lambda: outline.isVisible() and getattr(outline, "label", None) == CONFIRM_TEXT, 2.0)
    marks = getattr(outline, "marks", None) or {}
    failures += _check(f"whole window: DRAW REGION shows '{CONFIRM_TEXT}'", ok,
                       f"(label {getattr(outline, 'label', None)!r}, marks {marks})")
    failures += _check("whole window: confirmation marks the fixture's pin",
                       _on_pin(marks.get("pin"), pin), f"(want ~{pin}, got {marks.get('pin')})")
    failures += _check("whole window: confirmation marks the digits",
                       _on_digits(marks.get("digits"), region), f"(want ~{region}, got {marks.get('digits')})")
    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    plate = saved.get("plate") or {}
    failures += _check("whole window: the saved box is the digits box",
                       _on_digits(saved.get("region"), region) and saved.get("region") == overlay.cfg["region"],
                       f"(saved {saved.get('region')}, want ~{region})")
    failures += _check("whole window: pin and plate saved (plate = the drawn window)",
                       bool(saved.get("anchor")) and (config_dir() / "anchor.png").is_file()
                       and plate.get("w") == frect["width"] and plate.get("h") == frect["height"],
                       f"(anchor {saved.get('anchor')}, plate {plate})")
    overlay._last_value = None
    ok = _wait(lambda: overlay._last_value == EXPECTED and overlay._track_info.get("state") == "locked")
    failures += _check(f"whole window: tracking reads {EXPECTED:,}", ok,
                       f"(last value {overlay._last_value}, state {overlay._track_info.get('state')})")
    ok = _wait(lambda: any(p[1] is not None for p in previews), 3.0)
    view = next((p for p in reversed(previews) if p[1] is not None), None)
    failures += _check("whole window: Settings preview gets the window with pin and digits rects", ok,
                       f"(previews {previews[-3:]})")
    if view is not None:
        shape, vpin, vdigits = view
        want_pin = (pin["left"] - frect["left"], pin["top"] - frect["top"])
        # the green box hugs "42,000" as the reader trims it: centred on the
        # number (its centre within NEAR of the digits' own centre)
        want_digits = (DIGITS_INK[0] + DIGITS_INK[2] / 2, DIGITS_INK[1] + DIGITS_INK[3] / 2)
        vcentre = (vdigits[0] + vdigits[2] / 2, vdigits[1] + vdigits[3] / 2) if vdigits else (-99, -99)
        want_pin = want_pin
        failures += _check("whole window: preview is the whole window, pin and digits in place",
                           shape == (frect["height"], frect["width"])
                           and all(abs(a - b) <= NEAR for a, b in zip(vpin[:2], want_pin))
                           and all(abs(a - b) <= NEAR for a, b in zip(vcentre, want_digits)),
                           f"(crop {shape}, pin {vpin} want ~{want_pin}, digits {vdigits} centre {vcentre} want ~{want_digits})")
    _wait(lambda: not outline.isVisible(), 3.5)
    overlay.settings.set_preview = real_preview
    return failures


def part_first_run(screen, shown: dict) -> int:
    """No box saved: the nav ⚙ and DRAW REGION ask for attention until one is
    drawn. Calls to the two setters are recorded on the classes."""
    from app.config import Config, config_dir
    from app.main import OverlayApp
    from app.ui.navbar import NavBar
    from app.ui.settings_panel import SettingsPanel

    failures = 0
    calls: dict[str, list[bool]] = {"nav": [], "draw": []}
    for cls, name, key in ((NavBar, "set_settings_attention", "nav"),
                           (SettingsPanel, "set_draw_region_attention", "draw")):
        real = getattr(cls, name, None)
        failures += _check(f"{cls.__name__}.{name} exists", real is not None)
        if real is None:
            continue

        def wrapped(self, on, _real=real, _key=key):
            calls[_key].append(bool(on))
            return _real(self, on)

        setattr(cls, name, wrapped)

    for name in ("config.json", "anchor.png"):
        (config_dir() / name).unlink(missing_ok=True)
    cfg = Config()
    cfg["nav_visible"] = False
    cfg["voice_enabled"] = False
    cfg.save()
    app = QApplication.instance()
    fresh = OverlayApp(app, Config.load())
    fresh.start()
    fresh.panel.hide()
    _pump(0.8)
    failures += _check("first run: no region picker opened", fresh._selector is None)
    failures += _check("first run: nav ⚙ attention on", bool(calls["nav"]) and calls["nav"][-1],
                       f"(calls {calls['nav']})")
    failures += _check("first run: DRAW REGION attention on", bool(calls["draw"]) and calls["draw"][-1],
                       f"(calls {calls['draw']})")
    chip = getattr(fresh.panel, "track_state", "<missing>")
    failures += _check("first run: no tracking chip (no box)", chip is None, f"(panel.track_state {chip!r})")
    fresh._on_region_selected(dict(shown["region"]))
    _pump(0.5)
    failures += _check("box drawn: nav ⚙ attention off", bool(calls["nav"]) and not calls["nav"][-1],
                       f"(calls {calls['nav']})")
    failures += _check("box drawn: DRAW REGION attention off", bool(calls["draw"]) and not calls["draw"][-1],
                       f"(calls {calls['draw']})")
    _pump(CONFIRM_SECONDS)                # let the confirmation run out
    fresh.nav.quit_btn.click()
    fresh.nav.quit_btn.click()
    _pump(0.3)
    failures += _check("first run: QUIT stops the scanner", fresh.scan.isFinished())
    fresh.outline.hide()
    for w in (fresh.nav, fresh.panel, fresh.settings):
        w.hide()
    return failures


def main() -> int:
    if sys.platform != "win32":
        print("Windows only (physical-pixel capture); skipped.")
        return 0
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if QApplication.instance() is None:
        QApplication(sys.argv)
    primary = QGuiApplication.primaryScreen()
    others = [s for s in QGuiApplication.screens() if s is not primary]
    # --primary tests on the main monitor (usually the game monitor), which
    # covers the middle of that screen for a few seconds.
    # A 2160-px-high side monitor first: the fixture is a 2160-high HUD, so
    # the whole-window check (reference pin scaled by height) can run there.
    from app import display

    tall = [s for s in others if display.physical_rect(s)["height"] == 2160]
    screen = primary if ("--primary" in sys.argv or not others) else (tall or others)[0]
    print(f"Using {screen.name()} (scale {screen.devicePixelRatio():.2f}); "
          f"config in {_TMP.name}")
    print("-" * 78)
    failures, shown = part_screen_path(screen)
    print("-" * 78)
    if shown is not None:
        failures += part_app(screen, shown)
        print("-" * 78)
        print("  -- first run (no box) --")
        failures += part_first_run(screen, shown)
        shown["fixture"].close()
    print("-" * 78)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
