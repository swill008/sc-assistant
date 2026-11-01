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
   box and says so, the monitor choice is saved, and QUIT stops the scanner.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
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
    overlay = OverlayApp(app, Config.load())
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
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
