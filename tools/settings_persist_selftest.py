"""The scanner settings survive QUIT and a restart.

    python -m tools.settings_persist_selftest

Runs the real OverlayApp twice against a temporary settings folder (your own
%APPDATA% is never touched). The first run changes READS / S, TRACKING, SHOW
BOX and MONITOR through the Settings controls, saves a pin from the 5K2K test
image the way SELECT does, and quits with QUIT. The file on disk must hold
every change; the second run, started from that file, must show each one in
Settings and use it in the scanner.
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


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)

    from app import display
    from app.config import CONFIG_PATH, Config, config_dir
    from app.main import OverlayApp

    failures = 0
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()
    # Start on a secondary monitor so nothing covers the game; switch to
    # another monitor through the MONITOR list.
    start = next((s for s in screens if s is not primary), primary)
    other = next((s for s in screens if s is not start), None)
    mon = display.physical_rect(start)
    region = {"left": mon["left"] + mon["width"] // 2, "top": mon["top"] + mon["height"] // 2,
              "width": DIGITS[2], "height": DIGITS[3]}
    cfg = Config()
    cfg["region"] = region
    cfg["region_monitor"] = mon
    cfg["game_monitor"] = start.name()
    cfg["voice_enabled"] = False
    cfg.save()
    print(f"settings folder {config_dir()}")
    print("-" * 78)

    # ---- first run: change everything through the UI, then QUIT ----------
    print("First run: change the settings, then QUIT")
    one = OverlayApp(app, Config.load())
    one.start()
    _pump(0.5)
    s = one.settings
    want_monitor = other.name() if other is not None else start.name()
    if other is not None:
        s.monitor_box.setCurrentIndex(s.monitor_box.findData(other.name()))
        s.monitor_box.activated.emit(s.monitor_box.currentIndex())
    s.reads_slider.setValue(6)
    s.tracking_slider.setValue(250)
    s.outline_btn.setChecked(True)
    # Save a pin the way SELECT does, from the 5K2K image, on the new box.
    box = one.cfg["region"]
    image = cv2.imread(str(FIXTURE))
    origin = (box["left"] - DIGITS[0], box["top"] - DIGITS[1])
    pinned = one._calibrate_anchor(dict(box, width=DIGITS[2], height=DIGITS[3]), image=image, origin=origin)
    failures += _check("pin saved from the 5K2K image", pinned)
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
    one.outline.hide()
    for w in (one.nav, one.panel, one.settings):
        w.hide()

    # ---- second run: started from the saved file ------------------------
    print("Second run: start from the saved file")
    two = OverlayApp(app, Config.load())
    two.start()
    _pump(0.8)
    s = two.settings
    failures += _check("READS / S shows 6", s.reads_slider.value() == 6 and s.reads_label.text() == "6 / s",
                       f"(slider {s.reads_slider.value()}, label {s.reads_label.text()!r})")
    failures += _check("scanner reads 6 times a second", two.scan._interval == round(1000 / 6),
                       f"(interval {two.scan._interval} ms)")
    failures += _check("TRACKING shows ±250 px", s.tracking_slider.value() == 250 and s.tracking_label.text() == "±250 px",
                       f"(slider {s.tracking_slider.value()}, label {s.tracking_label.text()!r})")
    failures += _check("SHOW BOX shows on", s.outline_btn.isChecked())
    failures += _check("outline is shown", two.outline.isVisible())
    failures += _check("MONITOR shows the saved monitor", s.monitor_box.currentData() == want_monitor,
                       f"({s.monitor_box.currentData()!r})")
    failures += _check("scanner uses the saved box", two.scan._region == box_after, f"({two.scan._region})")
    failures += _check("saved pin loaded: tracking is on", two.scan.tracking)
    failures += _check("no amber note", not s.region_note.text(), f"({s.region_note.text()!r})")
    two.nav.quit_btn.click()
    two.nav.quit_btn.click()
    _pump(0.5)
    resaved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    failures += _check("quitting again keeps every setting",
                       all(resaved.get(k) == saved.get(k) for k in
                           ("poll_ms", "tracking_range", "show_region_outline", "game_monitor", "region", "anchor")))

    print("-" * 78)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
