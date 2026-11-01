"""The scanner settings survive QUIT and a restart.

    python -m tools.settings_persist_selftest

Runs the real OverlayApp twice against a temporary settings folder (your own
%APPDATA% is never touched). The first run changes READS / S, TRACKING, SHOW
BOX and MONITOR through the Settings controls, saves a pin and plate from the 5K2K test
image the way DRAW REGION does, and quits with QUIT. The file on disk must hold
every change; the second run, started from that file, must show each one in
Settings and use it in the scanner. The open Settings sections (headings
opened and closed in the first run) must come back the same, an unknown id in
the file is dropped, and SCANNER is forced open only while no box is drawn. A third run uses UNMATCHED READINGS (OPEN
FOLDER, CLEAR) and RESET SETTINGS: the restart is caught, the settings file
must stay gone after the restart and quit (nothing old written back), a dated
backup holds it, and a fourth run starts on the defaults.
"""
from __future__ import annotations

from tools import _testguard

_testguard.install()        # first: no focus, no hotkeys

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory(prefix="ca-persist-")
os.environ["APPDATA"] = _TMP.name          # before app.config is imported

import cv2  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FIXTURE = ROOT / "tools" / "fixtures" / "signal_42000_5k2k.png"
DIGITS = (76, 38, 56, 28)                   # the digits box inside the fixture


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


def _user_opens(s, ids: list) -> None:
    """Click the Settings headings whose open state differs from ids (a
    forced heading ignores the click, as it does for the user)."""
    from PySide6.QtTest import QTest

    from app.ui.settings_panel import SECTION_IDS

    for sid in SECTION_IDS:
        if (sid in ids) != (sid in s.open_sections):
            QTest.mouseClick(s.section_header(sid), Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def _reset_run(app, saved: dict) -> int:
    """Third run: UNMATCHED READINGS buttons, then RESET SETTINGS (two clicks).
    The restart is caught (no process is started); the settings file must be
    gone after the restart and quit, a dated backup must hold the old one, and
    the next start must use the defaults."""
    from app import config as app_config
    from app import main as main_mod
    from app.config import CONFIG_PATH, DEFAULTS, Config, config_dir
    from app.main import OverlayApp

    failures = 0
    print("Third run: UNMATCHED READINGS, then RESET SETTINGS")
    three = OverlayApp(app, Config.load())
    three.start()
    three.panel.hide()
    _pump(0.5)
    s = three.settings
    if not hasattr(s, "reset_btn") or not hasattr(three, "unmatched"):
        return _check("RESET SETTINGS and UNMATCHED READINGS are wired", False)

    opened: list = []
    real_open, real_popen = app_config.open_folder, main_mod.subprocess.Popen
    app_config.open_folder = opened.append
    launched: list = []
    main_mod.subprocess.Popen = lambda args, **kw: launched.append(list(args))
    try:
        three.unmatched.record(9999, "unknown", None)
        three._show_unmatched()
        s.unmatched_open_btn.click()
        failures += _check("OPEN FOLDER opens the unmatched folder",
                           opened == [config_dir() / "unmatched"], f"(opened {opened})")
        s.unmatched_clear_btn.click()
        s.unmatched_clear_btn.click()
        failures += _check("CLEAR (two clicks) empties the unmatched readings",
                           three.unmatched.entries() == [], f"({three.unmatched.entries()})")

        s.reset_btn.click()
        _pump(0.1)
        failures += _check("one RESET click keeps the settings", CONFIG_PATH.is_file() and not launched)
        s.reset_btn.click()
        _pump(0.5)
        three.save_config()                # what main()'s aboutToQuit hook runs
    finally:
        app_config.open_folder, main_mod.subprocess.Popen = real_open, real_popen
    failures += _check("second RESET click restarts the app",
                       len(launched) == 1 and "--restart" in launched[0], f"(launched {launched})")
    failures += _check("reset stopped the scanner", three.scan.isFinished())
    failures += _check("restart and quit wrote no settings back (no config.json)",
                       not CONFIG_PATH.is_file(),
                       f"({CONFIG_PATH.read_text(encoding='utf-8')[:80] if CONFIG_PATH.is_file() else ''})")
    failures += _check("pin removed", not (config_dir() / "anchor.png").is_file())
    folder = config_dir()
    backups = [p for p in folder.parent.iterdir() if p.name.startswith(f"{folder.name} backup ")]
    kept = [json.loads((b / "config.json").read_text(encoding="utf-8")) for b in backups
            if (b / "config.json").is_file()]
    failures += _check("a dated backup holds the old settings",
                       any(k.get("poll_ms") == saved.get("poll_ms") for k in kept), f"(backups {backups})")
    three.outline.hide()
    for w in (three.nav, three.panel, three.settings):
        w.hide()

    print("Fourth run: start after the reset")
    four = OverlayApp(app, Config.load())
    four.start()
    four.panel.hide()
    _pump(0.5)
    failures += _check("READS / S back to the default",
                       four.scan._interval == int(DEFAULTS["poll_ms"]), f"(interval {four.scan._interval})")
    failures += _check("no box and no pin after the reset",
                       four.cfg["region"] == DEFAULTS["region"] and not four.scan.tracking)
    failures += _check("open Settings sections back to SCANNER only",
                       four.cfg["settings_open"] == ["scanner"] and four.settings.open_sections == ["scanner"],
                       f"(cfg {four.cfg['settings_open']}, panel {four.settings.open_sections})")
    four.nav.quit_btn.click()
    four.nav.quit_btn.click()
    _pump(0.3)
    return failures


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)

    from app import display
    from app.config import CONFIG_PATH, Config, config_dir
    from app.main import OverlayApp
    from app.ui.settings_panel import TRACKING_STEP

    failures = 0
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()
    # Start on a secondary monitor so nothing covers the game; switch to
    # another monitor through the MONITOR list.
    start = next((s for s in screens if s is not primary), primary)
    others = [s for s in screens if s is not start]
    other = next((s for s in others if s is not primary), others[0] if others else None)
    mon = display.physical_rect(start)
    region = {"left": mon["left"] + mon["width"] // 2, "top": mon["top"] + mon["height"] // 2,
              "width": DIGITS[2], "height": DIGITS[3]}
    cfg = Config()
    cfg["region"] = region
    cfg["region_monitor"] = mon
    cfg["game_monitor"] = start.name()
    cfg["voice_enabled"] = False
    cfg["nav_visible"] = False            # keep the nav bar off the game screen
    cfg.save()
    print(f"settings folder {config_dir()}")
    print("-" * 78)

    # ---- first run: change everything through the UI, then QUIT ----------
    print("First run: change the settings, then QUIT")
    one = OverlayApp(app, Config.load())
    one.start()
    one.panel.hide()                      # the scanner panel opens on the main screen
    _pump(0.5)
    s = one.settings
    want_monitor = other.name() if other is not None else start.name()
    if other is not None:
        s.monitor_box.setCurrentIndex(s.monitor_box.findData(other.name()))
        s.monitor_box.activated.emit(s.monitor_box.currentIndex())
    s.reads_slider.setValue(6)
    s.tracking_slider.setValue(250 // TRACKING_STEP)  # the slider counts 50 px steps
    s.outline_btn.setChecked(True)
    want_open = ["scanner", "hotkeys", "look"]
    _user_opens(s, want_open)
    # DRAW REGION on the new box (the digits of the 5K2K image, which works on
    # any monitor height), its screen faked: the pin, digits box and plate.
    box = dict(one.cfg["region"], width=DIGITS[2], height=DIGITS[3])
    one.cfg["region"] = dict(box)
    image = cv2.imread(str(FIXTURE))
    origin = (box["left"] - DIGITS[0], box["top"] - DIGITS[1])

    def grab(rect):
        import numpy as np

        out = np.zeros((int(rect["height"]), int(rect["width"]), 3), np.uint8)
        x, y = origin[0] - rect["left"], origin[1] - rect["top"]
        ih, iw = image.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(out.shape[1], x + iw), min(out.shape[0], y + ih)
        out[y0:y1, x0:x1] = image[y0 - y:y1 - y, x0 - x:x1 - x]
        return out
    one._calibrate_drawn(dict(box), grab=grab)
    _pump(1.0)
    failures += _check("pin and plate saved from the 5K2K image by DRAW REGION",
                       bool(one.cfg["anchor"]) and bool(one.cfg.get("plate")),
                       f"(anchor {one.cfg['anchor']}, plate {one.cfg.get('plate')})")
    box_after = dict(one.cfg["region"])
    _pump(0.3)
    one.nav.quit_btn.click()
    one.nav.quit_btn.click()
    _pump(0.5)
    failures += _check("QUIT stopped the first run", one.scan.isFinished())

    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    print("Saved file after QUIT")
    failures += _check("READS / S 6 saved", saved.get("poll_ms") == round(1000 / 6), f"(poll_ms {saved.get('poll_ms')})")
    failures += _check("TRACKING ±250 saved", saved.get("tracking_range") == 250, f"({saved.get('tracking_range')})")
    failures += _check("SHOW BOX on saved", saved.get("show_region_outline") is True, f"({saved.get('show_region_outline')})")
    failures += _check("MONITOR choice saved", saved.get("game_monitor") == want_monitor, f"({saved.get('game_monitor')!r})")
    failures += _check("box saved", saved.get("region") == box_after, f"({saved.get('region')})")
    meta = saved.get("anchor")
    failures += _check("pin saved", bool(meta) and (config_dir() / meta.get("file", "")).is_file(), f"({meta})")
    failures += _check("plate saved", saved.get("plate") == one.cfg.get("plate") and bool(saved.get("plate")),
                       f"({saved.get('plate')})")
    failures += _check("open Settings sections saved", saved.get("settings_open") == want_open,
                       f"({saved.get('settings_open')})")
    # A hand-edited or older file may name a section that no longer exists.
    edited = dict(saved, settings_open=want_open + ["no_such_section"])
    CONFIG_PATH.write_text(json.dumps(edited, indent=2), encoding="utf-8")
    one.outline.hide()
    for w in (one.nav, one.panel, one.settings):
        w.hide()

    # ---- second run: started from the saved file ------------------------
    print("Second run: start from the saved file")
    two = OverlayApp(app, Config.load())
    two.start()
    two.panel.hide()
    _pump(0.8)
    s = two.settings
    failures += _check("READS / S shows 6", s.reads_slider.value() == 6 and s.reads_label.text() == "6 / s",
                       f"(slider {s.reads_slider.value()}, label {s.reads_label.text()!r})")
    failures += _check("scanner reads 6 times a second", two.scan._interval == round(1000 / 6),
                       f"(interval {two.scan._interval} ms)")
    failures += _check("TRACKING shows ±250 px", s.tracking_value == 250 and s.tracking_label.text() == "±250 px",
                       f"(value {s.tracking_value}, label {s.tracking_label.text()!r})")
    failures += _check("SHOW BOX shows on", s.outline_btn.isChecked())
    failures += _check("outline is shown", two.outline.isVisible())
    failures += _check("MONITOR shows the saved monitor", s.monitor_box.currentData() == want_monitor,
                       f"({s.monitor_box.currentData()!r})")
    failures += _check("scanner uses the saved box", two.scan._region == box_after, f"({two.scan._region})")
    failures += _check("saved pin loaded: tracking is on", two.scan.tracking)
    want_plate = tuple(saved.get("plate", {}).get(k) for k in ("dx", "dy", "w", "h"))
    failures += _check("saved plate handed to the scanner (preview of the whole window)",
                       getattr(two.scan, "_plate", None) == want_plate,
                       f"(scanner {getattr(two.scan, '_plate', '<missing>')}, saved {want_plate})")
    failures += _check("no amber note", not s.region_note.text(), f"({s.region_note.text()!r})")
    failures += _check("open Settings sections come back, unknown id dropped",
                       s.open_sections == want_open and two.cfg["settings_open"] == want_open,
                       f"(panel {s.open_sections}, cfg {two.cfg['settings_open']})")
    _user_opens(s, ["hotkeys", "look"])
    failures += _check("box drawn: SCANNER can be closed", s.open_sections == ["hotkeys", "look"],
                       f"({s.open_sections})")
    _user_opens(s, want_open)
    two.nav.quit_btn.click()
    two.nav.quit_btn.click()
    _pump(0.5)
    resaved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    failures += _check("quitting again keeps every setting",
                       all(resaved.get(k) == saved.get(k) for k in
                           ("poll_ms", "tracking_range", "show_region_outline", "game_monitor", "region", "anchor", "plate",
                            "settings_open")))

    # ---- RESET SETTINGS: defaults after the restart, nothing written back --
    failures += _reset_run(app, saved)

    # ---- fresh start with no region: no picker forced on screen ----------
    print("Fresh start, no region saved")
    for name in ("config.json", "anchor.png"):
        (config_dir() / name).unlink(missing_ok=True)
    fresh_cfg = Config()
    fresh_cfg["nav_visible"] = False
    fresh_cfg["voice_enabled"] = False
    fresh_cfg.save()
    three = OverlayApp(app, Config.load())
    notes: list[str] = []
    show_idle = three.panel.set_scan_idle
    three.panel.set_scan_idle = lambda note="": (notes.append(note), show_idle(note))
    three.start()
    three.panel.hide()
    _pump(1.5)                            # the old build opened the picker after 0.65 s
    failures += _check("no region picker opened at start-up", three._selector is None)
    failures += _check("panel says to press DRAW REGION", any("DRAW REGION" in n for n in notes), f"({notes})")
    s = three.settings
    _user_opens(s, ["hotkeys"])
    failures += _check("no box: SCANNER stays open when its heading is closed",
                       s.open_sections == ["scanner", "hotkeys"], f"({s.open_sections})")
    three._apply_region(region, mon, start.name())
    _user_opens(s, ["hotkeys"])
    failures += _check("box applied: SCANNER released and can be closed",
                       s.open_sections == ["hotkeys"], f"({s.open_sections})")
    three.nav.quit_btn.click()
    three.nav.quit_btn.click()
    _pump(0.3)

    print("-" * 78)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
