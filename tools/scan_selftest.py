"""Scanner plumbing checks: OCR thread cap, the per-monitor region picker,
keeping the box right when the monitor changes, the scanner settings and the
update source.

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
    picker.show()
    for w in picker.windows:
        w.setWindowOpacity(0.0)
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

    screen = QGuiApplication.primaryScreen()
    picker = RegionSelector("selftest", screens=[screen])
    picker.show()
    for w in picker.windows:
        w.setWindowOpacity(0.0)
    QApplication.processEvents()
    ok = len(picker.windows) == 1 and picker.windows[0].screen() is screen
    picker.close()
    return _check("SELECT opens only on the chosen game monitor", ok)


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
    failures += check_outline()
    failures += check_quit_button()
    failures += check_updater_source()
    print("-" * 78)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
