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

from tools import _testguard

_testguard.install()        # first: no focus, no hotkeys

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Never the user's %APPDATA%\SC Assistant: the config folder is
# resolved when app.config is imported, so point it at a temp folder first.
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ca_scan_selftest_")

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
    # Whole 50-px steps on the slider (0-16 = 0-800 px); emitted on release only.
    failures += _check("tracking slider range is 0-800 px in steps of 50",
                       (s.minimum(), s.maximum(), s.singleStep(), s.pageStep()) == (0, 16, 1, 1)
                       and not s.hasTracking(), f"({s.minimum()}-{s.maximum()}, tracking {s.hasTracking()})")
    panel.set_tracking(400)
    failures += _check("tracking slider shows ±400 px", panel.tracking_label.text() == "±400 px"
                       and s.value() == 8 and emitted == [], f"(label {panel.tracking_label.text()!r})")
    s.setValue(12)
    failures += _check("slider released at 600 emits 600 once", emitted == [600], f"(emitted {emitted})")
    panel.set_tracking(230)
    failures += _check("a value between steps shows the nearest step, no emit",
                       panel.tracking_label.text() == "±250 px" and s.value() == 5 and emitted == [600],
                       f"(label {panel.tracking_label.text()!r}, value {s.value()}, emitted {emitted})")
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

    return _check("UPDATE pulls from swill008/sc-assistant",
                  updater.REPO == "swill008/sc-assistant", f"(REPO {updater.REPO})")



# ---------------------------------------------------------------------------
# OverlayApp wiring (wave 1): a real OverlayApp object with fake windows, so
# the checks drive main.py's own methods without opening anything on screen.
class _FakeWindow:
    """A panel / settings / nav stand-in: records what main.py asks of it."""

    def __init__(self, name="w", visible=True):
        self.name = name
        self.visible = visible
        self.pinned = False
        self.calls: list = []
        self.note = ""
        self.track_state = "unset"
        self.attention = None
        self.shown = True

    def __getattr__(self, attr):
        # Any other method main.py calls is recorded and returns None.
        if attr.startswith("__"):
            raise AttributeError(attr)

        def method(*args, **kwargs):
            self.calls.append((attr, args))
        return method

    def isVisible(self):  # noqa: N802
        return self.visible

    def hide(self):
        self.visible = False
        self.calls.append(("hide", ()))

    def show(self):
        self.visible = True

    def set_pinned(self, pinned):
        self.pinned = bool(pinned)

    def set_track_state(self, state):
        self.track_state = state

    def set_region_note(self, text):
        self.note = text

    def set_settings_attention(self, on):
        self.attention = bool(on)

    def set_draw_region_attention(self, on):
        self.attention = bool(on)

    def slide_out(self):
        self.shown = False


class _FakeOutline:
    def __init__(self):
        self.calls: list = []
        self.visible = False

    def show_marks(self, digits, pin, state, label=""):
        self.calls.append(("marks", digits, pin, state, label))
        self.visible = True

    def show_region(self, region):        # the old main.py (old-code proof)
        self.calls.append(("region", region))
        self.visible = True

    def hide(self):
        self.calls.append(("hide",))
        self.visible = False

    def isVisible(self):  # noqa: N802
        return self.visible

    def keep_on_top(self):
        pass


class _FakeScan2:
    def __init__(self):
        self.calls: list[dict] = []
        self.tracking = False
        self.has_anchor = False
        self.requests: list = []

    def configure(self, **kwargs):
        self.calls.append(kwargs)
        if "anchor" in kwargs:
            self.has_anchor = kwargs["anchor"] is not None

    def request_anchor(self, folder, meta):
        self.requests.append((folder, meta))

    def set_enabled(self, enabled):
        pass


class _FakeHotkeys:
    def __init__(self):
        self.bindings: list = []

    def set_bindings(self, bindings):
        self.bindings.append(dict(bindings))


def _test_cfg(**values):
    from app.config import Config

    cfg = Config()
    cfg.saves = 0

    def save():
        cfg.saves += 1                    # never write a real config file
    cfg.save = save
    for key, value in values.items():
        cfg[key] = value
    return cfg


def _bare_overlay(cfg):
    """OverlayApp without its windows, threads or tray: fakes instead."""
    from collections import deque
    from types import SimpleNamespace

    from PySide6.QtCore import QObject

    from app import main as main_mod

    o = main_mod.OverlayApp.__new__(main_mod.OverlayApp)
    QObject.__init__(o)
    o.app = QApplication.instance()
    o.cfg = cfg
    o.demo = False
    o.capture_visible = False
    o._paused = False
    o._recent = deque(maxlen=max(1, int(cfg["stability_reads"])))
    o._last_value = None
    o._last_matches = []
    o._last_res = None
    o._last_good_at = 0.0
    o._spoken_key = None
    o._spoken_value = None
    o._last_match_name = ""
    o._selector = None
    o._tracked_rect = None
    if hasattr(o, "_init_tracking_state"):       # missing in the old main.py
        o._init_tracking_state()
    o.scan = _FakeScan2()
    o.outline = _FakeOutline()
    o.hotkeys = _FakeHotkeys()
    o.voice = SimpleNamespace(say=lambda text: None)
    o.data = SimpleNamespace(nearest=lambda value: [], version="4.10.2", ores=[1, 2],
                             source_text="", fallback_reason="")
    o.nav = _FakeWindow("nav")
    o.panel = _FakeWindow("mining")
    o.settings = _FakeWindow("settings", visible=False)
    o.orefinder = _FakeWindow("orefinder")
    o.hauling = _FakeWindow("hauling")
    o.inventory = _FakeWindow("inventory")
    o.uex = _FakeWindow("uex")
    o.notes = _FakeWindow("notes", visible=False)
    o.combat_panel = _FakeWindow("combat")
    return o


def _secondary_region(width=57, height=25) -> tuple:
    """A box in the middle of a non-primary monitor (the primary when alone)."""
    from app import display

    primary = QGuiApplication.primaryScreen()
    screen = next((s for s in QGuiApplication.screens() if s is not primary), primary)
    mon = display.physical_rect(screen)
    region = {"left": mon["left"] + mon["width"] // 2, "top": mon["top"] + mon["height"] // 2,
              "width": width, "height": height}
    return screen, mon, region


def _read(value=42000, confidence=0.99, exact=True):
    from types import SimpleNamespace

    res = SimpleNamespace(ok=True, value=value, confidence=confidence, crop=None)
    match = SimpleNamespace(exact=exact, is_ground=False, name="Quantanium", kind="ship",
                            label="Quantanium", count=1)
    return res, [match]


def check_track_state() -> int:
    """ScanThread.track_state: fixed / searching / locked with the digits and
    the pin rect (template position + PIN_MARGIN, size - 2 * PIN_MARGIN)."""
    import numpy as np

    from app import main as main_mod
    from app import tracking

    failures = 0
    _screen, _mon, region = _secondary_region()
    cfg = _test_cfg(region=region)
    anchor = tracking.Anchor(template=np.zeros((32, 28, 3), np.uint8), digits=(35, 2, 90, 28))

    def grab(rect):
        return np.full((int(rect["height"]), int(rect["width"]), 3), 7, np.uint8)

    thread = main_mod.ScanThread(_FakeData(), cfg)
    states: list = []
    thread.track_state.connect(states.append)
    thread.scan_once(grab, _FakeOCR(), region)
    thread.scan_once(grab, _FakeOCR(), region)
    failures += _check("track_state: no pin -> fixed, once",
                       states == [{"state": "fixed", "digits": None, "pin": None}], f"(got {states})")

    real_locate = tracking.locate
    hits: list = []
    try:
        tracking.locate = lambda image, a, min_score=0.6: hits[0] if hits else None
        thread = main_mod.ScanThread(_FakeData(), cfg, anchor=anchor)
        states = []
        thread.track_state.connect(states.append)
        area = thread._track[1]
        thread.scan_once(grab, _FakeOCR(), region)
        failures += _check("track_state: tracking, no plate -> searching",
                           states == [{"state": "searching", "digits": None, "pin": None}],
                           f"(got {states})")
        hits.append(tracking.Match(x=100, y=60, score=0.95))
        thread.scan_once(grab, _FakeOCR(), region)
        m = tracking.PIN_MARGIN
        want_pin = {"left": area["left"] + 100 + m, "top": area["top"] + 60 + m,
                    "width": 28 - 2 * m, "height": 32 - 2 * m}
        dx, dy, dw, dh = tracking.digits_rect(hits[0], anchor)
        want_digits = {"left": area["left"] + dx, "top": area["top"] + dy, "width": dw, "height": dh}
        failures += _check("track_state: plate found -> locked with digits and pin rects",
                           states[-1] == {"state": "locked", "digits": want_digits, "pin": want_pin},
                           f"(want pin {want_pin}, got {states[-1]})")
        thread.scan_once(grab, _FakeOCR(), region)
        failures += _check("track_state: same plate again is not re-emitted", len(states) == 2,
                           f"({len(states)} emitted)")
        hits.clear()
        thread.scan_once(grab, _FakeOCR(), region)
        failures += _check("track_state: plate lost -> searching",
                           states[-1]["state"] == "searching" and len(states) == 3, f"(got {states})")
    finally:
        tracking.locate = real_locate
    return failures


def check_overlay_marks() -> int:
    """Chip on every change; SHOW BOX: TRACKING ✓ value / SEARCHING… at the
    last rects / FIXED BOX on the box; off -> hidden; pause clears the rect."""
    failures = 0
    _screen, _mon, region = _secondary_region()
    o = _bare_overlay(_test_cfg(region=region, show_region_outline=True))
    o.scan.has_anchor = True                     # a pin is saved: no learning
    digits = {"left": region["left"] + 5, "top": region["top"] + 3, "width": 60, "height": 26}
    pin = {"left": region["left"] - 30, "top": region["top"] + 3, "width": 24, "height": 28}

    o._on_track_state({"state": "locked", "digits": digits, "pin": pin})
    failures += _check("locked: chip set to locked", o.panel.track_state == "locked")
    failures += _check("locked, nothing read yet: TRACKING ✓ around digits and pin",
                       o.outline.calls[-1] == ("marks", digits, pin, "locked", "TRACKING ✓"),
                       f"(got {o.outline.calls[-1]})")
    o._on_result(*_read(42000))
    failures += _check("locked + read: label shows the value",
                       o.outline.calls[-1] == ("marks", digits, pin, "locked", "TRACKING ✓  42,000"),
                       f"(got {o.outline.calls[-1]})")
    o._on_track_state({"state": "searching", "digits": None, "pin": None})
    failures += _check("searching: amber SEARCHING… at the last rects, chip searching",
                       o.outline.calls[-1] == ("marks", digits, pin, "searching", "SEARCHING…")
                       and o.panel.track_state == "searching", f"(got {o.outline.calls[-1]})")
    o._on_track_state({"state": "fixed", "digits": None, "pin": None})
    failures += _check("fixed: FIXED BOX on the drawn box, chip fixed",
                       o.outline.calls[-1] == ("marks", region, None, "fixed", "FIXED BOX")
                       and o.panel.track_state == "fixed", f"(got {o.outline.calls[-1]})")
    o._on_track_state({"state": "searching", "digits": None, "pin": None})
    failures += _check("searching with no earlier lock: drawn on the box",
                       o.outline.calls[-1] == ("marks", region, None, "searching", "SEARCHING…"),
                       f"(got {o.outline.calls[-1]})")
    o._on_track_state({"state": "locked", "digits": digits, "pin": pin})
    o._on_pause(True)
    failures += _check("pause clears the tracked rect: outline back on the box",
                       o._tracked_rect is None and o.outline.calls[-1][1] == region,
                       f"(got {o.outline.calls[-1]})")
    o._on_pause(False)
    o._on_outline(False)
    failures += _check("SHOW BOX off: outline hidden, chip still updates",
                       o.outline.calls[-1] == ("hide",))
    o._on_track_state({"state": "locked", "digits": digits, "pin": pin})
    failures += _check("SHOW BOX off: locked updates the chip only",
                       o.outline.calls[-1] == ("hide",) and o.panel.track_state == "locked")
    return failures


def check_draw_confirmation() -> int:
    """DRAW REGION: 3-second result even with SHOW BOX off, then normal."""
    import tempfile

    import numpy as np

    from app import main as main_mod
    from app import tracking

    failures = 0
    _screen, _mon, region = _secondary_region()
    found = tracking.Anchor(template=np.zeros((32, 28, 3), np.uint8), digits=(35, 2, 90, 28))
    image = np.zeros((300, 400, 3), np.uint8)
    origin = (region["left"] - 100, region["top"] - 100)
    real = tracking.find_anchor, tracking.locate, main_mod.config_dir
    with tempfile.TemporaryDirectory() as tmp:
        try:
            main_mod.config_dir = lambda: Path(tmp)
            tracking.locate = lambda img, a, min_score=0.6: tracking.Match(x=60, y=95, score=0.9)
            for result in (found, None):
                tracking.find_anchor = lambda img, box, r=result: r
                o = _bare_overlay(_test_cfg(region=region, show_region_outline=False))
                o._calibrate_drawn(dict(region), image=image, origin=origin)
                m = tracking.PIN_MARGIN
                if result is not None:
                    pin = {"left": origin[0] + 60 + m, "top": origin[1] + 95 + m,
                           "width": 28 - 2 * m, "height": 32 - 2 * m}
                    want = ("marks", region, pin, "locked", "PIN FOUND — TRACKING ON")
                    label = "pin found"
                else:
                    want = ("marks", region, None, "searching", "NO PIN FOUND — FIXED BOX")
                    label = "no pin"
                failures += _check(f"DRAW REGION, {label}, SHOW BOX off: confirmation shown",
                                   o.outline.visible and o.outline.calls[-1] == want,
                                   f"(want {want}, got {o.outline.calls[-1:]})")
                o._on_track_state({"state": "fixed", "digits": None, "pin": None})
                failures += _check(f"DRAW REGION, {label}: a scan update does not cut it short",
                                   o.outline.visible and o.outline.calls[-1] == want)
                _pump(2.5)
                still = o.outline.visible
                _pump(0.8)
                failures += _check(f"DRAW REGION, {label}: cleared after 3 s (SHOW BOX off -> hidden)",
                                   still and not o.outline.visible and o.outline.calls[-1] == ("hide",),
                                   f"(at 2.5 s visible {still}, calls {o.outline.calls[-2:]})")
        finally:
            tracking.find_anchor, tracking.locate, main_mod.config_dir = real
    return failures


def check_pin_learning() -> int:
    """B / g: a box without a pin learns it from the first confident exact
    read, once; after a height change it is learned again."""
    import tempfile

    import numpy as np

    from app import capture
    from app import main as main_mod
    from app import tracking

    failures = 0
    _screen, mon, region = _secondary_region()
    found = tracking.Anchor(template=np.zeros((32, 28, 3), np.uint8), digits=(35, 2, 90, 28))
    calls: list = []
    grabs: list = []

    class _Grabber:
        def grab(self, rect):
            grabs.append(dict(rect))
            return np.zeros((int(rect["height"]), int(rect["width"]), 3), np.uint8)

        def close(self):
            pass

    real = tracking.find_anchor, tracking.locate, main_mod.config_dir, capture.ScreenGrabber
    with tempfile.TemporaryDirectory() as tmp:
        try:
            main_mod.config_dir = lambda: Path(tmp)
            capture.ScreenGrabber = _Grabber
            tracking.locate = lambda img, a, min_score=0.6: None
            result = [found]
            tracking.find_anchor = lambda img, box: calls.append(box) or result[0]

            o = _bare_overlay(_test_cfg(region=region, region_monitor=mon))
            for _ in range(3):
                o._on_result(*_read(43000, exact=False))
            failures += _check("inexact signature: never learned, even when stable", calls == [],
                               f"(calls {calls})")
            o = _bare_overlay(_test_cfg(region=region, region_monitor=mon))
            o._on_result(*_read(42000, confidence=0.83))
            failures += _check("one exact read at 0.83 (not shown yet): not learned yet", calls == [],
                               f"(calls {calls})")
            o._on_result(*_read(42000, confidence=0.83))
            box = (region["left"] - grabs[-1]["left"], region["top"] - grabs[-1]["top"],
                   region["width"], region["height"]) if grabs else None
            failures += _check("two identical exact reads at 0.83 (shown): pin looked for around the box",
                               len(calls) == 1 and calls[0] == box, f"(calls {calls}, want {box})")
            failures += _check("pin learned: saved, handed to the scanner, noted",
                               o.cfg["anchor"] == {"file": "anchor.png", "digits": [35, 2, 90, 28]}
                               and {"anchor": found} in o.scan.calls
                               and o.settings.note == main_mod._PIN_LEARNED_NOTE,
                               f"(anchor {o.cfg['anchor']}, note {o.settings.note!r})")
            o._recent.clear()
            o._last_value = None
            o._on_result(*_read(42000))
            failures += _check("learned once only", len(calls) == 1, f"({len(calls)} calls)")

            # Not found: tried once, the fixed box stays, the note is untouched.
            calls.clear()
            result[0] = None
            o = _bare_overlay(_test_cfg(region=region, region_monitor=mon))
            o.settings.note = "before"
            o._on_result(*_read(42000))
            o._last_value = None
            o._on_result(*_read(42000))
            failures += _check("no pin on the first read: tried once, quietly",
                               len(calls) == 1 and o.cfg["anchor"] is None and o.settings.note == "before",
                               f"(calls {len(calls)}, note {o.settings.note!r})")

            # g: a resolution change drops the pin; it is learned again.
            calls.clear()
            result[0] = found
            o = _bare_overlay(_test_cfg(region=region, region_monitor=mon,
                                        anchor={"file": "anchor.png", "digits": [35, 2, 90, 28]}))
            o.scan.has_anchor = True
            o._learn_tried = True
            o._on_result(*_read(42000))
            failures += _check("with a pin: nothing to learn", calls == [])
            taller = dict(mon, height=mon["height"] * 2, width=mon["width"] * 2)
            o.cfg["region_monitor"] = taller
            o._check_display()
            o._last_value = None
            o._recent.clear()
            o._on_result(*_read(42000))
            failures += _check("after a height change: pin dropped, then learned again",
                               len(calls) == 1 and o.cfg["anchor"] is not None and o.scan.has_anchor,
                               f"(calls {len(calls)}, anchor {o.cfg['anchor']})")
        finally:
            (tracking.find_anchor, tracking.locate, main_mod.config_dir,
             capture.ScreenGrabber) = real
    return failures


def check_pin_kept_on_move() -> int:
    """I / review 7: a monitor that only moves keeps the pin (the box follows
    it); a height change drops it. Both via the monitor watcher and MONITOR."""
    from app import display

    failures = 0
    screen, now, region = _secondary_region()
    meta = {"file": "anchor.png", "digits": [35, 2, 90, 28]}
    cases = (("monitor moved", dict(now, left=now["left"] - 700, top=now["top"] + 40), False),
             ("monitor height changed", dict(now, width=now["width"] * 2, height=now["height"] * 2), True))
    for label, recorded, drop in cases:
        for how in ("watcher", "MONITOR"):
            moved = display.rescale(region, recorded, now)
            old_region = {"left": region["left"] - (moved["left"] - region["left"]),
                          "top": region["top"] - (moved["top"] - region["top"]),
                          "width": region["width"], "height": region["height"]}
            if drop:
                old_region = dict(region)
            o = _bare_overlay(_test_cfg(region=old_region, region_monitor=recorded,
                                        game_monitor=screen.name(), anchor=dict(meta)))
            if how == "watcher":
                o._check_display()
            else:
                o._on_game_monitor(screen.name())
            if drop:
                ok = (o.cfg["anchor"] is None and {"anchor": None} in o.scan.calls
                      and "press DRAW REGION to turn it back on" in o.settings.note)
            else:
                ok = (o.cfg["anchor"] == meta and {"anchor": None} not in o.scan.calls
                      and o.cfg["region"] == display.rescale(old_region, recorded, now)
                      and "Tracking is off" not in o.settings.note)
            failures += _check(f"{label} ({how}): pin {'dropped' if drop else 'kept'}, box follows",
                               ok, f"(anchor {o.cfg['anchor']}, scan {o.scan.calls}, "
                                   f"note {o.settings.note!r})")
    return failures


def check_anchor_load() -> int:
    """I: the saved pin decodes on the scanner thread; a missing anchor.png
    clears the metadata; a broken one says "could not load", not "no pin"."""
    import subprocess
    import tempfile

    from app import main as main_mod

    failures = 0
    code = ("import sys; import app.main; "
            "print('cv2' in sys.modules, 'numpy' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True,
                         text=True, timeout=60).stdout.strip()
    failures += _check("importing app.main loads neither OpenCV nor numpy", out == "False False",
                       f"(cv2, numpy loaded: {out!r})")

    _screen, _mon, region = _secondary_region()
    meta = {"file": "anchor.png", "digits": [35, 2, 90, 28]}
    real_dir = main_mod.config_dir
    with tempfile.TemporaryDirectory() as tmp:
        try:
            main_mod.config_dir = lambda: Path(tmp)
            o = _bare_overlay(_test_cfg(region=region, anchor=dict(meta)))
            o._load_anchor()
            failures += _check("anchor.png missing: stale metadata cleared, note says missing",
                               o.cfg["anchor"] is None and o.scan.requests == []
                               and o.settings.note == main_mod._PIN_MISSING_NOTE,
                               f"(anchor {o.cfg['anchor']}, note {o.settings.note!r})")
            (Path(tmp) / "anchor.png").write_bytes(b"not a png")
            o = _bare_overlay(_test_cfg(region=region, anchor=dict(meta)))
            o._load_anchor()
            failures += _check("anchor.png present: decoded on the scanner thread, not here",
                               len(o.scan.requests) == 1 and o.scan.calls == [],
                               f"(requests {o.scan.requests}, configure {o.scan.calls})")
            thread = main_mod.ScanThread(_FakeData(), _test_cfg(region=region))
            got: list = []
            thread.anchor_loaded.connect(lambda m, r: got.append((m, r)))
            thread.request_anchor(Path(tmp), meta)
            thread._load_requested_anchor()
            failures += _check("broken anchor.png: the scanner reports an error text",
                               len(got) == 1 and isinstance(got[0][1], str), f"(got {got})")
            o._on_anchor_loaded(meta, got[0][1] if got else "x")
            failures += _check("broken anchor.png: note says could not load (not 'no pin')",
                               o.settings.note.startswith("Could not load the saved pin")
                               and not o.scan.has_anchor, f"(note {o.settings.note!r})")
            o.cfg["anchor"] = {"file": "other.png", "digits": [1, 1, 9, 9]}
            o._on_anchor_loaded(meta, object())
            failures += _check("a load for an older pin is ignored", o.scan.calls == [])
            sentinel = object()
            o.cfg["anchor"] = dict(meta)
            o._on_anchor_loaded(meta, sentinel)
            failures += _check("loaded pin handed to the scanner", o.scan.calls == [{"anchor": sentinel}])
        finally:
            main_mod.config_dir = real_dir
    return failures


def check_calibration_errors() -> int:
    """A failing pin search says so, instead of "No pin icon found"."""
    import numpy as np

    from app import main as main_mod
    from app import tracking

    _screen, _mon, region = _secondary_region()
    real = tracking.find_anchor

    def boom(img, box):
        raise MemoryError("out of memory")
    try:
        tracking.find_anchor = boom
        o = _bare_overlay(_test_cfg(region=region))
        on = o._calibrate_anchor(region, image=np.zeros((300, 400, 3), np.uint8),
                                 origin=(region["left"] - 100, region["top"] - 100))
    finally:
        tracking.find_anchor = real
    return _check("pin search error: note says it failed, with the reason",
                  not on and o.settings.note.startswith("Pin search failed (MemoryError: out of memory)")
                  and o.settings.note != main_mod._NO_PIN_NOTE, f"(note {o.settings.note!r})")


def check_tracking_range_parse() -> int:
    from app import main as main_mod

    cases = {None: 400, "": 400, "abc": 400, "250": 250, 300.4: 300, -5: 0, True: 400, 650: 650}
    got = {k: main_mod.parse_tracking_range(k) for k in cases}
    failures = _check("tracking_range parsed one way, broken values fall back to 400",
                      got == cases, f"(got {got})")
    thread = main_mod.ScanThread(_FakeData(), _test_cfg(tracking_range="oops"))
    o = _bare_overlay(_test_cfg(tracking_range="oops"))
    failures += _check("ScanThread and OverlayApp agree on a hand-edited range",
                       thread._tracking_range == o._tracking_range() == 400)
    return failures


def check_hotkeys_wiring() -> int:
    """J-b: Settings -> HOTKEYS saves config and rebinds; tool hotkeys toggle."""
    from app import main as main_mod

    failures = 0
    o = _bare_overlay(_test_cfg(hotkey_toggle_nav=0x72, hotkey_panic=0x73,
                                hotkey_tools={"notes": 0x70, "bad": "x"}))
    failures += _check("start-up hotkeys for Settings",
                       o._hotkey_config() == {"toggle_nav": 0x72, "panic": 0x73, "tools": {"notes": 0x70}},
                       f"(got {o._hotkey_config()})")
    ids = [t["id"] for t in main_mod.TOOLS]
    o._on_hotkeys_changed({"toggle_nav": 0x74, "panic": 0x77,
                           "tools": {"notes": 0x70, "mining": 0x71, "bogus": 0x45}})
    want = {1: 0x74, 2: 0x77, 100 + ids.index("mining"): 0x71, 100 + ids.index("notes"): 0x70}
    failures += _check("hotkeys_changed: config saved",
                       o.cfg["hotkey_toggle_nav"] == 0x74 and o.cfg["hotkey_panic"] == 0x77
                       and o.cfg["hotkey_tools"] == {"notes": 0x70, "mining": 0x71} and o.cfg.saves == 1,
                       f"(tools {o.cfg['hotkey_tools']}, saves {o.cfg.saves})")
    failures += _check("hotkeys_changed: set_bindings ids 1, 2, 100+TOOLS index",
                       o.hotkeys.bindings == [want], f"(got {o.hotkeys.bindings}, want {want})")
    o._on_hotkey(100 + ids.index("notes"))
    shown = o.notes.visible
    o._on_hotkey(100 + ids.index("notes"))
    failures += _check("a tool hotkey toggles that tool like its nav button",
                       shown and not o.notes.visible, f"(after 1st {shown}, after 2nd {o.notes.visible})")
    o._on_hotkeys_changed({"toggle_nav": 0x72, "panic": 0, "tools": {}})
    failures += _check("a cleared hotkey is not bound", o.hotkeys.bindings[-1] == {1: 0x72},
                       f"(got {o.hotkeys.bindings[-1]})")
    return failures


def check_pins_and_hide_all() -> int:
    """Pins load at start, save on pin_toggled; hide-all keeps pinned panels."""
    failures = 0
    _screen, _mon, region = _secondary_region()
    o = _bare_overlay(_test_cfg(region=region, show_region_outline=True,
                                pinned_windows=["notes", "mining", 7]))
    o._load_pins()
    failures += _check("pinned_windows loaded into the panels",
                       o.notes.pinned and o.panel.pinned and not o.hauling.pinned)
    o.notes.visible = True
    o.outline.visible = True
    o._hide_all()
    failures += _check("hide-all: pinned panels stay, the others hide",
                       o.notes.visible and o.panel.visible and not o.hauling.visible
                       and not o.orefinder.visible and not o.combat_panel.visible and not o.uex.visible
                       and not o.inventory.visible and not o.nav.shown)
    failures += _check("hide-all: a pinned scanner keeps its SHOW BOX outline", o.outline.visible)
    o._on_pin("mining", False)
    o.panel.pinned = False
    o._on_pin("hauling", True)
    failures += _check("pin_toggled saves pinned_windows",
                       o.cfg["pinned_windows"] == ["hauling", "notes"] and o.cfg.saves == 2,
                       f"(got {o.cfg['pinned_windows']}, saves {o.cfg.saves})")
    o._hide_all()
    failures += _check("hide-all: unpinned scanner and its outline hide",
                       not o.panel.visible and not o.outline.visible and o.notes.visible)
    o._on_track_state({"state": "fixed", "digits": None, "pin": None})
    failures += _check("hidden outline stays hidden on a scan update until the bar returns",
                       not o.outline.visible)
    o._show_bar()
    failures += _check("showing the bar brings SHOW BOX back", o.outline.visible)
    return failures


def check_first_run_attention() -> int:
    failures = 0
    screen, mon, region = _secondary_region()
    o = _bare_overlay(_test_cfg(region=None))
    o._update_first_run_attention()
    failures += _check("no box: ⚙ and DRAW REGION highlighted",
                       o.nav.attention is True and o.settings.attention is True)
    o._apply_region(region, mon, screen.name())
    failures += _check("box drawn: highlights off",
                       o.nav.attention is False and o.settings.attention is False)
    return failures


def check_update_handoff_failure() -> int:
    from app import updater

    o = _bare_overlay(_test_cfg())
    quits: list = []
    o.quit = lambda: quits.append(True)
    real = updater.run_installer

    def fail(path):
        raise OSError("helper did not start")
    try:
        updater.run_installer = fail
        o._install_update("C:/nowhere/Setup.exe")
    finally:
        updater.run_installer = real
    return _check("update hand-off failure: settings.install_failed(msg), no quit",
                  ("install_failed", ("Update failed: helper did not start",)) in o.settings.calls
                  and quits == [], f"(calls {o.settings.calls}, quits {quits})")


def check_signature_refresh() -> int:
    """scmdb refresh: on_done(True) on a worker thread reloads on the GUI thread."""
    import threading

    from PySide6.QtCore import QThread

    failures = 0
    o = _bare_overlay(_test_cfg())
    reloads: list = []
    o._reload_data = lambda: reloads.append(QThread.currentThread())

    class _Data:
        version = "4.10.2"
        ores = [1]
        source_text = "bundled 4.10.2"
        fallback_reason = "network down"

        def refresh_in_background(self, on_done=None, force=False):
            worker = threading.Thread(target=lambda: on_done(True))
            worker.start()
            worker.join()

    o.data = _Data()
    o.data_refreshed.connect(o._on_data_refreshed)
    o._refresh_data()
    _pump(0.2)
    failures += _check("refresh changed the data: reload runs once, on the GUI thread",
                       len(reloads) == 1 and reloads[0] is QApplication.instance().thread(),
                       f"({len(reloads)} reloads)")
    o._show_data_version()
    got = [c for c in o.settings.calls if c[0] == "set_version"]
    failures += _check("Settings shows the source and why it fell back",
                       got and got[-1][1][0].startswith("bundled 4.10.2 (scmdb unavailable: network down"),
                       f"(got {got})")
    return failures


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
    failures += check_calibration_anchor()
    failures += check_calibration_errors()
    print("-" * 78)
    failures += check_track_state()
    failures += check_overlay_marks()
    failures += check_draw_confirmation()
    failures += check_pin_learning()
    failures += check_pin_kept_on_move()
    failures += check_anchor_load()
    failures += check_tracking_range_parse()
    failures += check_hotkeys_wiring()
    failures += check_pins_and_hide_all()
    failures += check_first_run_attention()
    failures += check_update_handoff_failure()
    failures += check_signature_refresh()
    print("-" * 78)
    failures += check_outline()
    failures += check_quit_button()
    failures += check_updater_source()
    print("-" * 78)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
