"""Scanner plumbing checks: OCR thread cap, the per-monitor region picker,
keeping the box right when the monitor changes, the scanner settings, HUD
tracking (search area, OCR only on a match, anchor at DRAW REGION and cleared on a
monitor change) and the update source.

    python -m tools.scan_selftest

Needs a desktop session (the picker opens real, fully transparent windows on
every monitor). The drag test feeds physical cursor positions through the
picker's ``cursor_pos`` hook, so it never moves the real mouse.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import win32  # noqa: E402
from app.ocr import SignatureOCR  # noqa: E402


def _pump(seconds: float) -> None:
    """Run the Qt event loop for a while, as the live app would."""
    import time

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


def check_ocr_threads() -> int:
    failures = 0
    for threads in (1, 2):
        ocr = SignatureOCR(threads=threads)
        session = ocr._ensure_engine().text_recognizer.session.session
        got = session.get_session_options().intra_op_num_threads
        failures += _check(f"OCR model runs on {threads} thread(s)", got == threads, f"(got {got})")
    return failures


def _open_picker(fake_cursor: list, picked: list):
    from app.ui.region_selector import RegionSelector

    picker = RegionSelector("selftest", cursor_pos=lambda: fake_cursor[0])
    picker.selected.connect(picked.append)
    for w in picker.windows:
        w.setWindowOpacity(0.0)        # before show: never a visible frame
    picker.show()
    QApplication.processEvents()
    return picker


def check_region_picker() -> int:
    failures = 0
    screens = QGuiApplication.screens()
    picked: list[dict] = []
    fake_cursor = [(0, 0)]

    picker = _open_picker(fake_cursor, picked)
    failures += _check("one picker window per monitor", len(picker.windows) == len(screens),
                       f"({len(picker.windows)} windows, {len(screens)} monitors)")
    for w in picker.windows:
        screen = w.screen()
        failures += _check(f"{screen.name()}: window scale matches monitor",
                           abs(w.devicePixelRatio() - screen.devicePixelRatio()) < 1e-6,
                           f"(window {w.devicePixelRatio()}, monitor {screen.devicePixelRatio()})")
        failures += _check(f"{screen.name()}: window no larger than monitor",
                           w.geometry().size() == screen.geometry().size(),
                           f"(window {w.geometry().width()}x{w.geometry().height()}, "
                           f"monitor {screen.geometry().width()}x{screen.geometry().height()})")
    picker.close()

    # Drag a 300x80 physical-pixel box in the middle of every monitor. The
    # stored region must be exactly the physical rectangle the cursor covered.
    for mon in win32.monitors():
        x0 = mon["left"] + mon["width"] // 2 - 150
        y0 = mon["top"] + mon["height"] // 2 - 40
        want = {"left": x0, "top": y0, "width": 300, "height": 80}
        picked.clear()
        picker = _open_picker(fake_cursor, picked)
        w = picker.window_for_physical(x0, y0)
        fake_cursor[0] = (x0, y0)
        QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 20))
        fake_cursor[0] = (x0 + 300, y0 + 80)
        QTest.mouseMove(w, QPoint(60, 50))
        QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 50))
        QApplication.processEvents()
        got = picked[-1] if picked else None
        failures += _check(f"{mon['name']}: drag stored exactly", got == want, f"(want {want}, got {got})")
        picker.close()
    return failures


def check_picker_on_one_monitor() -> int:
    from app.ui.region_selector import RegionSelector

    # A secondary monitor when there is one: keep tests off the game screen.
    primary = QGuiApplication.primaryScreen()
    screen = next((s for s in QGuiApplication.screens() if s is not primary), primary)
    picker = RegionSelector("selftest", screens=[screen])
    for w in picker.windows:
        w.setWindowOpacity(0.0)        # before show: never a visible frame
    picker.show()
    QApplication.processEvents()
    ok = len(picker.windows) == 1 and picker.windows[0].screen() is screen
    picker.close()
    return _check("DRAW REGION opens only on the chosen game monitor", ok)


def check_rescale() -> int:
    from app.display import rescale

    failures = 0
    wide = {"left": 0, "top": 0, "width": 5120, "height": 2160}
    box = {"left": 2556, "top": 768, "width": 80, "height": 40}
    # Same 21:9 shape, lower resolution: everything scales by 0.75.
    got = rescale(box, wide, {"left": 0, "top": 0, "width": 3840, "height": 1620})
    failures += _check("rescale 5120x2160 -> 3840x1620",
                       got == {"left": 1917, "top": 576, "width": 60, "height": 30}, f"(got {got})")
    # 21:9 -> 16:9 at the same height: the HUD scales with height and stays
    # centred, so only the distance from the centre changes, not the size.
    got = rescale(box, wide, {"left": 0, "top": 0, "width": 3840, "height": 2160})
    failures += _check("rescale 5120x2160 -> 3840x2160 (aspect change)",
                       got == {"left": 1916, "top": 768, "width": 80, "height": 40}, f"(got {got})")
    # Monitor moved in the desktop layout: the box follows it.
    got = rescale(box, wide, {"left": -5120, "top": 100, "width": 5120, "height": 2160})
    failures += _check("rescale follows a moved monitor",
                       got == {"left": -2564, "top": 868, "width": 80, "height": 40}, f"(got {got})")
    got = rescale(box, wide, dict(wide))
    failures += _check("rescale is a no-op on the same monitor", got == box, f"(got {got})")
    return failures


def check_config_migration() -> int:
    import json
    import tempfile

    from app import config as config_mod

    failures = 0
    failures += _check("new installs read 4 times a second",
                       config_mod.DEFAULTS["poll_ms"] == 250, f"(poll_ms {config_mod.DEFAULTS['poll_ms']})")
    original = config_mod.CONFIG_PATH
    with tempfile.TemporaryDirectory() as tmp:
        try:
            for stored, want in ((125, 250), (500, 500)):
                path = Path(tmp) / "config.json"
                path.write_text(json.dumps({"poll_ms": stored, "scan_tuning_version": 1}), encoding="utf-8")
                config_mod.CONFIG_PATH = path
                got = config_mod.Config.load()["poll_ms"]
                failures += _check(f"existing poll_ms {stored} migrates to {want}", got == want, f"(got {got})")
        finally:
            config_mod.CONFIG_PATH = original
    return failures


def check_settings_controls() -> int:
    from app.ui.settings_panel import SettingsPanel

    failures = 0
    panel = SettingsPanel()
    emitted: list[int] = []
    panel.reads_changed.connect(emitted.append)
    panel.set_reads(4)
    failures += _check("reads slider shows 4 / s", panel.reads_label.text() == "4 / s",
                       f"(label {panel.reads_label.text()!r})")
    panel.reads_slider.setValue(2)
    failures += _check("moving the slider to 2 emits 2 reads/s", emitted == [2], f"(emitted {emitted})")
    failures += _check("reads slider range is 1-8",
                       (panel.reads_slider.minimum(), panel.reads_slider.maximum()) == (1, 8))

    from app.display import monitor_choices

    choices = monitor_choices()
    panel.set_monitors(choices, choices[0][0])
    labels = [panel.monitor_box.itemText(i) for i in range(panel.monitor_box.count())]
    failures += _check("monitor list has every monitor", len(labels) == len(QGuiApplication.screens()),
                       f"({labels})")
    primary = QGuiApplication.primaryScreen()
    want = f"{round(primary.geometry().width() * primary.devicePixelRatio())}×" \
           f"{round(primary.geometry().height() * primary.devicePixelRatio())} · " \
           f"{round(primary.devicePixelRatio() * 100)}%"
    failures += _check("monitor label shows real resolution and scaling",
                       any(want in label for label in labels), f"(want {want!r} in {labels})")
    panel.deleteLater()
    return failures


def check_outline() -> int:
    """SHOW BOX: the outline lands exactly around the box on every monitor,
    lets clicks through, and is hidden from capture (so OCR never sees it)."""
    import ctypes
    from ctypes import wintypes

    from app.ui.region_outline import RegionOutline, outline_rect

    failures = 0
    user32 = ctypes.windll.user32
    for mon in win32.monitors():
        box = {"left": mon["left"] + mon["width"] // 2 - 40, "top": mon["top"] + mon["height"] // 2 - 20,
               "width": 80, "height": 40}
        outline = RegionOutline()
        outline.setWindowOpacity(0.0)
        outline.show_region(box)
        hwnd = wintypes.HWND(int(outline.winId()))

        def rect_now():
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            return {"left": r.left, "top": r.top, "width": r.right - r.left, "height": r.bottom - r.top}

        # Let the event loop settle as it does in the running app, then check
        # the rect is exact and stays exact.
        _pump(0.4)
        settled = rect_now()
        _pump(0.6)
        later = rect_now()
        failures += _check(f"{mon['name']}: outline sits exactly around the box",
                           settled == outline_rect(box) and later == settled,
                           f"(want {outline_rect(box)}, got {settled}, 0.6 s later {later})")
        ex = user32.GetWindowLongW(hwnd, -20)
        failures += _check(f"{mon['name']}: outline lets clicks through", bool(ex & 0x20))
        affinity = wintypes.DWORD()
        user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity))
        failures += _check(f"{mon['name']}: outline hidden from capture", affinity.value in (0x11, 0x1),
                           f"(affinity {affinity.value:#x})")
        outline.close()
        outline.deleteLater()
    return failures


def check_tracking_controls() -> int:
    from app import config as config_mod
    from app.ui.settings_panel import SettingsPanel

    failures = 0
    failures += _check("config: tracking_range defaults to 400, anchor to None, max_value 60000",
                       config_mod.DEFAULTS.get("tracking_range") == 400
                       and "anchor" in config_mod.DEFAULTS and config_mod.DEFAULTS["anchor"] is None
                       and config_mod.DEFAULTS["max_value"] == 60000)
    panel = SettingsPanel()
    emitted: list[int] = []
    panel.tracking_changed.connect(emitted.append)
    s = panel.tracking_slider
    failures += _check("tracking slider range is 0-800, step 50",
                       (s.minimum(), s.maximum(), s.singleStep(), s.pageStep()) == (0, 800, 50, 50))
    panel.set_tracking(400)
    failures += _check("tracking slider shows ±400 px", panel.tracking_label.text() == "±400 px"
                       and s.value() == 400 and emitted == [], f"(label {panel.tracking_label.text()!r})")
    s.setValue(600)
    failures += _check("moving the slider to 600 emits 600", emitted == [600], f"(emitted {emitted})")
    s.setValue(230)
    failures += _check("a value between steps snaps to 250", s.value() == 250 and emitted[-1] == 250,
                       f"(value {s.value()}, emitted {emitted})")
    s.setValue(0)
    failures += _check("0 shows OFF and emits 0", panel.tracking_label.text() == "OFF" and emitted[-1] == 0,
                       f"(label {panel.tracking_label.text()!r}, emitted {emitted})")
    panel.deleteLater()
    return failures


class _FakeOCR:
    def __init__(self):
        self.calls: list = []

    def read(self, crop):
        from app.ocr import OCRResult

        self.calls.append(crop.shape)
        return OCRResult(value=42000, confidence=0.99, crop=crop)


class _FakeData:
    def lookup(self, value, tolerance):
        return []


def check_scan_tracking() -> int:
    """ScanThread.scan_once: fixed box without an anchor or at range 0; with
    one, grab the search area and OCR only the digits when the pin is found."""
    import numpy as np

    from app import main as main_mod
    from app import tracking
    from app.config import Config

    failures = 0
    mon = win32.monitors()[0]
    region = {"left": mon["left"] + mon["width"] // 2 - 28, "top": mon["top"] + mon["height"] // 2 - 12,
              "width": 57, "height": 25}
    cfg = Config()
    cfg["region"] = region
    template = np.zeros((32, 28, 3), np.uint8)
    anchor = tracking.Anchor(template=template, digits=(35, 2, 90, 28))

    grabs: list[dict] = []

    def grab(rect):
        grabs.append(dict(rect))
        return np.full((int(rect["height"]), int(rect["width"]), 3), 7, np.uint8)

    def listen(thread):
        results, tracked = [], []
        thread.result.connect(lambda res, matches: results.append(res))
        thread.tracked.connect(tracked.append)
        return results, tracked

    # No anchor: today's fixed box.
    thread = main_mod.ScanThread(_FakeData(), cfg)
    ocr = _FakeOCR()
    results, tracked = listen(thread)
    grabs.clear()
    thread.scan_once(grab, ocr, region)
    failures += _check("no anchor: grabs the fixed box and OCRs it",
                       grabs == [region] and ocr.calls == [(25, 57, 3)] and tracked == [],
                       f"(grabs {grabs}, ocr {ocr.calls}, tracked {tracked})")

    # Anchor + default range: search area, OCR only the digits.
    real_locate = tracking.locate
    hits: list = []
    try:
        tracking.locate = lambda image, a, min_score=0.7: hits[0] if hits else None
        thread = main_mod.ScanThread(_FakeData(), cfg, anchor=anchor)
        ocr = _FakeOCR()
        results, tracked = listen(thread)
        screen = main_mod.display.screen_of_region(region)
        height = main_mod.display.physical_rect(screen)["height"]
        rx = round(400 * height / 2160)
        want = main_mod._clip(tracking.search_area(region, rx, round(0.75 * rx)),
                              main_mod.display.physical_rect(screen))
        failures += _check("anchor loaded: tracking is on", thread.tracking)

        grabs.clear()
        thread.scan_once(grab, ocr, region)
        failures += _check("plate not found: grabs the search area, no OCR, no value",
                           grabs == [want] and ocr.calls == [] and len(results) == 1
                           and not results[0].ok and tracked == [],
                           f"(want {want}, grabs {grabs}, ocr {ocr.calls}, tracked {tracked})")

        hits.append(tracking.Match(x=100, y=60, score=0.95))
        dx, dy, dw, dh = tracking.digits_rect(hits[0], anchor)
        thread.scan_once(grab, ocr, region)
        want_rect = {"left": want["left"] + dx, "top": want["top"] + dy, "width": dw, "height": dh}
        failures += _check("plate found: OCRs only the digits crop",
                           ocr.calls == [(dh, dw, 3)] and results[-1].ok,
                           f"(ocr {ocr.calls}, want {(dh, dw, 3)})")
        failures += _check("plate found: emits the physical digits rect",
                           tracked == [want_rect], f"(want {want_rect}, got {tracked})")
        thread.scan_once(grab, ocr, region)
        failures += _check("unchanged digits: OCR skipped, rect not re-emitted",
                           len(ocr.calls) == 1 and len(tracked) == 1 and results[-1].ok,
                           f"(ocr calls {len(ocr.calls)}, tracked {tracked})")

        hits.clear()
        thread.scan_once(grab, ocr, region)
        failures += _check("plate lost: no OCR, no value, rect cleared",
                           len(ocr.calls) == 1 and not results[-1].ok and tracked[-1] is None,
                           f"(ocr calls {len(ocr.calls)}, tracked {tracked})")

        hits.append(tracking.Match(x=100, y=60, score=0.95))
        thread.configure(tracking_range=0)
        grabs.clear()
        thread.scan_once(grab, ocr, region)
        failures += _check("TRACKING 0: back to the fixed box",
                           not thread.tracking and grabs == [region] and ocr.calls[-1] == (25, 57, 3),
                           f"(grabs {grabs}, ocr {ocr.calls})")
        thread.configure(tracking_range=400)
        failures += _check("TRACKING back on resumes tracking", thread.tracking)
        thread.configure(anchor=None)
        failures += _check("anchor cleared: tracking off", not thread.tracking)
    finally:
        tracking.locate = real_locate
    return failures


class _FakeScan:
    def __init__(self):
        self.calls: list[dict] = []

    def configure(self, **kwargs):
        self.calls.append(kwargs)


class _FakeSettings:
    note = ""

    def set_region_note(self, text):
        self.note = text


def check_anchor_dropped_on_rescale() -> int:
    """A monitor change rescales the box; the saved pin is for the old
    resolution, so tracking goes off and the note says to press DRAW REGION."""
    from app import main as main_mod
    from app.config import Config

    class _Fake:
        _check_display = main_mod.OverlayApp._check_display
        _on_game_monitor = main_mod.OverlayApp._on_game_monitor
        _drop_anchor = main_mod.OverlayApp._drop_anchor

        def __init__(self, cfg):
            self.cfg = cfg
            self.scan = _FakeScan()
            self.settings = _FakeSettings()
            self.applied: list = []

        def _apply_region(self, region, monitor, name):
            self.applied.append(region)
            self.cfg["region"] = region
            self.cfg["region_monitor"] = monitor

        def _refresh_monitor_list(self, current=None):
            pass

    failures = 0
    screen = QGuiApplication.primaryScreen()
    now = main_mod.display.physical_rect(screen)
    old = {"left": now["left"], "top": now["top"], "width": now["width"] * 2, "height": now["height"] * 2}
    region = {"left": now["left"] + now["width"] // 2, "top": now["top"] + now["height"] // 2,
              "width": 57, "height": 25}
    for label, call in (("monitor change", lambda f: f._check_display()),
                        ("MONITOR picked", lambda f: f._on_game_monitor(screen.name()))):
        cfg = Config()
        cfg.save = lambda: None           # never write the real config
        cfg["region"] = dict(region)
        cfg["region_monitor"] = dict(old)
        cfg["anchor"] = {"file": "anchor.png", "digits": [35, 2, 90, 28]}
        fake = _Fake(cfg)
        call(fake)
        failures += _check(f"{label}: box rescaled and anchor cleared",
                           len(fake.applied) == 1 and cfg["anchor"] is None
                           and {"anchor": None} in fake.scan.calls,
                           f"(applied {fake.applied}, anchor {cfg['anchor']}, scan {fake.scan.calls})")
        failures += _check(f"{label}: note says press DRAW REGION to turn tracking back on",
                           "press DRAW REGION to turn it back on" in fake.settings.note,
                           f"(note {fake.settings.note!r})")
    return failures


def check_calibration_anchor() -> int:
    """DRAW REGION looks for the pin around the new box: saved and handed to the
    scanner when found, otherwise the fixed box and the amber note."""
    import tempfile

    import numpy as np

    from app import main as main_mod
    from app import tracking
    from app.config import Config

    class _Fake:
        _calibrate_anchor = main_mod.OverlayApp._calibrate_anchor

        def __init__(self, cfg):
            self.cfg = cfg
            self.scan = _FakeScan()
            self.settings = _FakeSettings()

    failures = 0
    region = {"left": 1100, "top": 600, "width": 57, "height": 25}
    image = np.zeros((300, 400, 3), np.uint8)
    seen: list = []
    found = tracking.Anchor(template=np.zeros((32, 28, 3), np.uint8), digits=(35, 2, 90, 28))
    real_find, real_dir = tracking.find_anchor, main_mod.config_dir
    with tempfile.TemporaryDirectory() as tmp:
        try:
            main_mod.config_dir = lambda: Path(tmp)
            for result in (found, None):
                tracking.find_anchor = lambda img, box, r=result: seen.append(box) or r
                cfg = Config()
                cfg.save = lambda: None
                cfg["anchor"] = {"file": "old.png", "digits": [1, 1, 9, 9]}
                fake = _Fake(cfg)
                on = fake._calibrate_anchor(region, image=image, origin=(1000, 500))
                if result is not None:
                    failures += _check("pin found: box passed in image coordinates",
                                       seen[-1] == (100, 100, 57, 25), f"(got {seen[-1]})")
                    failures += _check("pin found: anchor saved and handed to the scanner",
                                       on and cfg["anchor"] == {"file": "anchor.png", "digits": [35, 2, 90, 28]}
                                       and (Path(tmp) / "anchor.png").is_file()
                                       and fake.scan.calls == [{"anchor": found}] and fake.settings.note == "",
                                       f"(anchor {cfg['anchor']}, scan {fake.scan.calls})")
                else:
                    failures += _check("no pin: fixed box, anchor cleared, amber note",
                                       not on and cfg["anchor"] is None and fake.scan.calls == [{"anchor": None}]
                                       and fake.settings.note == main_mod._NO_PIN_NOTE
                                       and fake.settings.note.startswith("No pin icon found left of the box"),
                                       f"(anchor {cfg['anchor']}, note {fake.settings.note!r})")
        finally:
            tracking.find_anchor, main_mod.config_dir = real_find, real_dir
    return failures


def check_quit_button() -> int:
    from app.ui.navbar import NavBar

    failures = 0
    nav = NavBar([])
    quits: list[bool] = []
    nav.quit_requested.connect(lambda: quits.append(True))
    nav.quit_btn.click()
    failures += _check("one QUIT click only arms it", quits == [] and nav.quit_btn.text() == "QUIT?",
                       f"(label {nav.quit_btn.text()!r})")
    nav.quit_btn.click()
    failures += _check("second QUIT click quits", quits == [True])
    nav.quit_btn.click()
    nav._quit_timer.timeout.emit()
    failures += _check("QUIT disarms by itself", nav.quit_btn.text() == "QUIT" and quits == [True])
    nav.deleteLater()
    return failures


def check_updater_source() -> int:
    from app import updater

    return _check("UPDATE pulls from swill008/citizen-assistant",
                  updater.REPO == "swill008/citizen-assistant", f"(REPO {updater.REPO})")


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if QApplication.instance() is None:
        QApplication(sys.argv)

    print("Monitors:")
    for s in QGuiApplication.screens():
        g = s.geometry()
        print(f"  {s.name():<16} {g.width()}x{g.height()} logical at ({g.x()},{g.y()}), "
              f"scale {s.devicePixelRatio():.2f}")
    print("-" * 78)
    failures = check_ocr_threads()
    print("-" * 78)
    failures += check_region_picker()
    failures += check_picker_on_one_monitor()
    print("-" * 78)
    failures += check_rescale()
    failures += check_config_migration()
    print("-" * 78)
    failures += check_settings_controls()
    failures += check_tracking_controls()
    failures += check_scan_tracking()
    failures += check_anchor_dropped_on_rescale()
    failures += check_calibration_anchor()
    failures += check_outline()
    failures += check_quit_button()
    failures += check_updater_source()
    print("-" * 78)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
