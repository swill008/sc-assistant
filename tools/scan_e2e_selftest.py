"""End-to-end scanner check on the real screen, with a real 5K2K signature.

    python -m tools.scan_e2e_selftest            # on a secondary monitor
    python -m tools.scan_e2e_selftest --primary  # on the main (game) monitor

Needs a Windows desktop. For a few seconds it shows a 240 x 110 crop of a
5120 x 2160 Star Citizen screenshot (signature 42,000) at 1:1 physical pixels
on a secondary monitor, or the primary if there is only one, then:

1. drags a box around the digits with the real region picker (the cursor
   position is fed through its ``cursor_pos`` hook, so the mouse never moves);
2. grabs that box with the app's capture code and reads it with the app's OCR;
3. turns on SHOW BOX and checks the capture is pixel-for-pixel unchanged, so
   the outline can never be read by the scanner;
4. builds the real OverlayApp against a temporary config folder (your own
   %APPDATA% settings are never touched) and checks the running scanner reads
   42,000, READS / S changes the live scan interval and the saved config, SHOW
   BOX shows and F4 hides the outline, a monitor resolution change rescales the
   box and says so, the monitor choice is saved, and QUIT stops the scanner;
5. HUD tracking, inside that app: SELECT on the box saves the pin anchor;
   with the signature moved by a HUD-sized sway (+150, +100 px) the scanner
   still reads it, its ``tracked`` rect sits on the moved digits and the fixed
   box alone would not read it; SHOW BOX follows the digits; with the
   signature gone nothing is read and the OCR is never run (counted by
   wrapping SignatureOCR.read for calls off the GUI thread); TRACKING at 0
   goes back to the fixed box.

Exit code = number of failed checks.
"""
from __future__ import annotations

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
    picker.show()
    for w in picker.windows:
        w.setWindowOpacity(0.0)
    QApplication.processEvents()
    win = picker.windows[0]
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    cursor[0] = (want["left"] + want["width"], want["top"] + want["height"])
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, 30))
    _pump(0.3)
    region = picked[-1] if picked else None
    failures += _check("picker stores the dragged box", region == want, f"(want {want}, got {region})")
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
    return failures, {"fixture": fixture, "rect": frect, "region": region}


def part_app(screen, shown: dict) -> int:
    from app import display
    from app.config import CONFIG_PATH, Config
    from app.main import OverlayApp

    failures = 0
    region = shown["region"]
    mon = display.physical_rect(screen)
    cfg = Config()
    cfg["region"] = region
    cfg["region_monitor"] = mon
    cfg["game_monitor"] = screen.name()
    cfg["voice_enabled"] = False
    cfg.save()

    app = QApplication.instance()
    _count_scan_ocr()
    overlay = OverlayApp(app, Config.load())
    seen = {"results": [], "tracked": []}
    overlay.scan.result.connect(
        lambda res, _m: seen["results"].append((time.monotonic(), getattr(res, "value", None))))
    has_tracked = hasattr(overlay.scan, "tracked")
    if has_tracked:
        overlay.scan.tracked.connect(
            lambda rect: seen["tracked"].append((time.monotonic(), rect)))
    overlay.start()

    # The real scan thread (low priority, 1 OCR thread) reads the live box.
    end = time.monotonic() + 8
    while time.monotonic() < end and overlay._last_value != EXPECTED:
        _pump(0.1)
    failures += _check(f"running scanner reads {EXPECTED:,}", overlay._last_value == EXPECTED,
                       f"(last value {overlay._last_value})")
    failures += _check("scanner thread runs at low priority",
                       overlay.scan.priority() == overlay.scan.Priority.LowPriority,
                       f"(priority {overlay.scan.priority()})")

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
    other = next((s for s in QGuiApplication.screens() if s is not screen), None)
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

    # QUIT needs two clicks, then stops the scanner and saves.
    overlay.nav.quit_btn.click()
    _pump(0.1)
    failures += _check("one QUIT click keeps the app running", overlay.scan.isRunning())
    overlay.nav.quit_btn.click()
    _pump(0.3)
    failures += _check("second QUIT click stops the scanner", overlay.scan.isFinished())
    failures += _check("QUIT hides the tray icon", not overlay.tray.isVisible())
    return failures


def part_tracking(overlay, shown: dict, seen: dict) -> int:
    from app import win32
    from app.capture import ScreenGrabber
    from app.config import CONFIG_PATH, config_dir
    from app.ocr import SignatureOCR
    from app.ui.region_outline import outline_rect

    failures = 0
    fixture, frect, region = shown["fixture"], shown["rect"], shown["region"]
    dx, dy = SWAY
    moved_rect = dict(frect, left=frect["left"] + dx, top=frect["top"] + dy)
    moved_digits = dict(region, left=region["left"] + dx, top=region["top"] + dy)

    def last_tracked():
        return seen["tracked"][-1][1] if seen["tracked"] else None

    def values_since(t0):
        return [v for t, v in seen["results"] if t >= t0]

    def outline_now():
        return win32.physical_window_rect(overlay.outline) if overlay.outline.isVisible() else None

    # 1. SELECT through the app with the plate on the drawn box: the app grabs
    #    the screen around it and saves the pin anchor.
    overlay._on_region_selected(dict(region))
    _pump(0.3)
    meta = overlay.cfg.get("anchor")
    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    failures += _check("SELECT saves the pin anchor in the config",
                       bool(meta) and saved.get("anchor") == meta, f"(anchor {meta})")
    png = config_dir() / "anchor.png"
    failures += _check("SELECT writes anchor.png in the config folder", png.is_file(), f"({png})")
    note = overlay.settings.region_note
    failures += _check("no 'No pin icon' note after SELECT", "No pin icon" not in note.text(),
                       f"(note {note.text()!r})")
    ok = _wait(lambda: overlay._last_value == EXPECTED and _on_digits(last_tracked(), region))
    failures += _check(f"tracking reads {EXPECTED:,} on the calibrated box", ok,
                       f"(last value {overlay._last_value}, tracked {last_tracked()})")

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
    grab = ScreenGrabber()
    fixed = SignatureOCR(threads=1).read(grab.grab(region))
    grab.close()
    failures += _check(f"the fixed box alone does not read {EXPECTED:,} there", fixed.value != EXPECTED,
                       f"(fixed box read {fixed.value})")

    # 3. SHOW BOX follows the tracked digits.
    overlay.settings.outline_btn.setChecked(True)
    _wait(lambda: _on_digits(_inside(outline_now()), moved_digits), 3.0)
    got = outline_now()
    failures += _check("SHOW BOX outline follows the tracked digits",
                       _on_digits(_inside(got), moved_digits),
                       f"(outline {got}, want around {moved_digits})")

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

    fixture.show()
    _move(fixture, moved_rect)
    overlay._last_value = None
    ok = _wait(lambda: overlay._last_value == EXPECTED and _on_digits(last_tracked(), moved_digits))
    failures += _check(f"plate back: tracking reads {EXPECTED:,} again", ok,
                       f"(last value {overlay._last_value}, tracked {last_tracked()})")

    # 5. TRACKING at 0: back to the fixed box.
    overlay.settings.tracking_slider.setValue(0)
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
    failures += _check("TRACKING 0: the moved plate is not read",
                       EXPECTED not in off and overlay._last_value != EXPECTED and len(off) > 0,
                       f"({len(off)} results, values {sorted(set(map(str, off)))})")
    _wait(lambda: _close_to(outline_now(), outline_rect(region)), 3.0)
    failures += _check("TRACKING 0: SHOW BOX outline back on the fixed box",
                       _close_to(outline_now(), outline_rect(region)),
                       f"(outline {outline_now()}, want {outline_rect(region)})")
    _move(fixture, frect)
    t_back = time.monotonic()
    ok = _wait(lambda: overlay._last_value == EXPECTED)
    failures += _check(f"TRACKING 0: plate back on the box reads {EXPECTED:,}", ok,
                       f"(last value {overlay._last_value}, took {time.monotonic() - t_back:.1f} s)")

    overlay.settings.outline_btn.setChecked(False)
    _pump(0.3)
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
    screen = primary if ("--primary" in sys.argv or not others) else others[0]
    print(f"Using {screen.name()} (scale {screen.devicePixelRatio():.2f}); "
          f"config in {_TMP.name}")
    print("-" * 78)
    failures, shown = part_screen_path(screen)
    print("-" * 78)
    if shown is not None:
        failures += part_app(screen, shown)
        shown["fixture"].close()
    print("-" * 78)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
