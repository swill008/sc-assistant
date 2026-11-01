"""Settings → DEBUG: SCAN HISTORY and SAVE BAD READS.

    python -m tools.debug_selftest

Drives main.py's real read handler (OverlayApp._on_result, the overlay built
without its windows as tools/scan_selftest.py does) against a temporary
settings folder; your own %APPDATA% is never touched. Checks: with both
switches off nothing is written; SCAN HISTORY keeps exactly the last 50 reads,
newest last, with the right fields for match / nomatch / noread / waiting
reads (real 76,000 matches: ROC ×19 and DEBRIS ×38), and writes the file at
most about once a second; SAVE BAD READS saves only failed reads of a locked
plate, at most one a second, the newest 200 kept; OPEN HISTORY / OPEN FOLDER
open the file and the folder; RESET SETTINGS removes both.
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
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ca_debug_selftest_")  # before app.config
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools import scan_selftest as st  # noqa: E402  (its helpers; APPDATA is temp)

FAILS = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global FAILS
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    if not ok:
        FAILS += 1


def _crop():
    return np.full((20, 50, 3), 80, np.uint8)


def _bad(raw="4?,0"):
    from types import SimpleNamespace

    return SimpleNamespace(ok=False, value=None, confidence=0.31, crop=_crop(), raw=raw), []


def _real_76000():
    """Real OCRResult and matcher output for 76,000 (ROC ×19, DEBRIS ×38)."""
    from app.mining import MiningData
    from app.ocr import OCRResult

    res = OCRResult(value=76000, confidence=0.99, crop=_crop(), raw="76,000")
    return res, MiningData().lookup(76000, 0.08)


def _folder():
    from app.config import config_dir
    return config_dir()


def _clean():
    import shutil
    folder = _folder()
    (folder / "scan_history.txt").unlink(missing_ok=True)
    shutil.rmtree(folder / "bad_reads", ignore_errors=True)


def _overlay(**cfg):
    o = st._bare_overlay(st._test_cfg(**cfg))
    if not hasattr(o, "_apply_debug"):
        return None
    o._apply_debug()
    return o


def _lines():
    path = _folder() / "scan_history.txt"
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


# ---------------------------------------------------------------------------
def check_defaults() -> None:
    from app.config import DEFAULTS, RESET_REMOVE

    print("DEFAULTS")
    check("both switches off by default",
          DEFAULTS.get("debug_scan_history") is False and DEFAULTS.get("debug_save_bad_reads") is False,
          f"({DEFAULTS.get('debug_scan_history')!r}, {DEFAULTS.get('debug_save_bad_reads')!r})")
    check("RESET SETTINGS removes scan_history.txt and bad_reads",
          "scan_history.txt" in RESET_REMOVE and "bad_reads" in RESET_REMOVE, f"({RESET_REMOVE})")


def check_off_writes_nothing() -> None:
    print("SWITCHES OFF")
    _clean()
    o = _overlay()
    if o is None:
        check("main.py has the DEBUG recorders", False)
        return
    st._locked(o)
    clock = st._Clock()
    from app import main as main_mod
    real_time = main_mod.time
    main_mod.time = clock
    try:
        for i in range(12):
            o._on_result(*(_bad() if i % 2 else _real_76000()))
            clock.now += 1.5
    finally:
        main_mod.time = real_time
    o._flush_history()
    o.save_config()
    QApplication.processEvents()
    folder = _folder()
    check("no scan_history.txt", not (folder / "scan_history.txt").exists())
    check("no bad_reads folder", not (folder / "bad_reads").exists())


def check_history() -> None:
    from app import main as main_mod

    print("SCAN HISTORY")
    _clean()
    o = _overlay(debug_scan_history=True, stability_reads=2)
    if o is None:
        check("main.py has the DEBUG recorders", False)
        return
    clock = st._Clock()
    real_time = main_mod.time
    main_mod.time = clock
    try:
        o._on_track_state({"state": "fixed", "digits": None, "pin": None})
        # Waiting: a new value at low confidence needs two identical reads.
        o._on_result(*st._read(42000, confidence=0.5))
        # Match: 76,000 (real matches) fast-locks at 0.99, though tracking is off.
        st._locked(o)
        o._on_result(*_real_76000())
        # Nomatch: a near-guess, twice (confirmed by identical reads).
        o._on_result(*st._read(43000, confidence=0.5, exact=False))
        o._on_result(*st._read(43000, confidence=0.5, exact=False))
        # Noread: tracked plate unreadable for over a second.
        for _ in range(5):
            o._on_result(*_bad())
            clock.now += 0.3
        # Not a read: the plate left the screen ("no plate").
        o._on_track_state({"state": "searching", "digits": None, "pin": None})
        o._on_result(*st._failed("no plate"))
    finally:
        main_mod.time = real_time
    lines = list(o._history.lines)
    check("9 reads recorded ('no plate' is not a read)", len(lines) == 9, f"({len(lines)})")
    for i, line in enumerate(lines):
        print(f"      {i}: {line}")
    waiting, match, nm1, nm2 = lines[0], lines[1], lines[2], lines[3]
    noread = lines[-1]

    def has(line, *parts):
        return all(p in line for p in parts)
    check("waiting read: value, conf, top exact, not confirmed, not shown, border none, fixed",
          has(waiting, "| read 42,000 |", "| conf 0.50 |", "| top Quantanium ×1 exact |",
              "| 2nd none |", "| confirmed no |", "| shown no |", "| border none |", "| track fixed"),
          f"({waiting})")
    check("match read: ROC deposit ×19 exact, 2nd Debris ×38, confirmed, shown, match, locked",
          has(match, "| read 76,000 |", "| conf 0.99 |", "| top ROC deposit ×19 exact |",
              "| 2nd Debris ×38 |", "| confirmed yes |", "| shown yes |", "| border match |",
              "| track locked"), f"({match})")
    check("nomatch: first near-guess waits, second confirms with border nomatch",
          has(nm1, "| read 43,000 |", "| top Quantanium ×1 ~ |", "| confirmed no |", "| shown no |")
          and has(nm2, "| confirmed yes |", "| shown yes |", "| border nomatch |"),
          f"({nm1} / {nm2})")
    check("noread: value —, not confirmed, border noread after a second, locked",
          has(noread, "| read — |", "| top none |", "| confirmed no |", "| shown no |",
              "| border noread |", "| track locked")
          and "| border noread |" not in lines[4], f"({lines[4]} / {noread})")
    check("each line starts with the time", all(line[:4].isdigit() and line[10] == " " for line in lines))

    # Writes: at most one per HISTORY_WRITE_MS, the last lines written soon after.
    check("nothing written straight away (timer pending)",
          not (_folder() / "scan_history.txt").exists() and o._history_timer.isActive()
          and o._history_timer.interval() <= 1000, f"(interval {o._history_timer.interval()})")
    st._pump(1.3)
    check("written within about a second, newest last", _lines() == lines, f"({len(_lines())} lines)")

    writes: list = []
    real_flush = o._history.flush
    o._history.flush = lambda: (writes.append(1), real_flush())
    for i in range(120):
        o._on_result(*st._read(10000 + i, confidence=0.5))
    st._pump(1.3)
    check("120 reads in a burst: one file write", len(writes) == 1, f"({len(writes)} writes)")
    saved = _lines()
    check("the file keeps exactly the last 50, newest last",
          len(saved) == 50 and "| read 10,070 |" in saved[0] and "| read 10,119 |" in saved[-1],
          f"({len(saved)} lines, first {saved[:1]}, last {saved[-1:]})")

    # Off again: nothing more is added; on again carries on from the file.
    o._on_history_switch(False)
    o._on_result(*st._read(9000, confidence=0.5))
    st._pump(1.2)
    check("switched off: nothing added", _lines() == saved and o._history is None)
    o._on_history_switch(True)
    o._on_result(*st._read(9100, confidence=0.5))
    from app import config as app_config
    opened: list = []
    real_open = app_config.open_folder
    app_config.open_folder = opened.append
    try:
        o._open_history()
    finally:
        app_config.open_folder = real_open
    after = _lines()
    check("on again: carries on from the file (still 50, newest last)",
          len(after) == 50 and "| read 9,100 |" in after[-1] and after[:-1] == saved[1:],
          f"({len(after)}, {after[-1:]})")
    check("OPEN HISTORY writes pending lines and opens scan_history.txt",
          opened == [_folder() / "scan_history.txt"], f"({opened})")
    check("switch saved in the settings", o.cfg["debug_scan_history"] is True and o.cfg.saves >= 2)


def check_bad_reads() -> None:
    from app import config as app_config
    from app import main as main_mod

    print("SAVE BAD READS")
    _clean()
    o = _overlay(debug_save_bad_reads=True)
    if o is None:
        check("main.py has the DEBUG recorders", False)
        return
    folder = _folder() / "bad_reads"
    clock = st._Clock()
    real_time = main_mod.time
    main_mod.time = clock
    try:
        # Fixed box (no tracking): a failed read is not saved.
        for _ in range(4):
            o._on_result(*_bad())
            clock.now += 1.1
        check("fixed box: failed reads not saved", not folder.exists())
        # Searching: no plate on screen.
        o._on_track_state({"state": "searching", "digits": None, "pin": None})
        for _ in range(4):
            o._on_result(*_bad())
            o._on_result(*st._failed("no plate"))
            clock.now += 1.1
        check("plate not on screen: nothing saved", not folder.exists())
        # Locked: a good read is never saved; failed reads at most one a second.
        o._on_track_state({"state": "locked", "pin": None,
                           "digits": {"left": 1200, "top": 800, "width": 90, "height": 28}})
        o._on_result(*_real_76000())
        clock.now += 1.1
        check("locked good read: not saved", not folder.exists())
        clock.now = 2000.0
        for _ in range(13):                 # 3 s at 4 reads a second
            o._on_result(*_bad())
            clock.now += 0.25
        pics = sorted(folder.glob("*.png"))
        check("locked failed reads: one picture a second (4 in 3 s)", len(pics) == 4,
              f"({len(pics)}: {[p.name for p in pics]})")
        name = pics[0].name if pics else ""
        check("the name holds the time and the track info",
              name[:8].isdigit() and "locked-x1200-y800-90x28" in name, f"({name})")
        import cv2
        img = cv2.imread(str(pics[0])) if pics else None
        check("the picture is the crop", img is not None and img.shape == (20, 50, 3)
              and int(img[0, 0, 0]) == 80)
        # Cap: the newest 200 are kept.
        clock.now += 1.0
        for _ in range(205):
            o._on_result(*_bad())
            clock.now += 1.0
        pics = sorted(folder.glob("*.png"))
        seqs = [int(p.name.split("-")[3]) for p in pics]
        check("at most 200 pictures, the newest kept", len(pics) == 200
              and seqs == list(range(10, 210)), f"({len(pics)}, {seqs[:2]}..{seqs[-2:]})")
    finally:
        main_mod.time = real_time
    check("SAVE BAD READS never writes the history", not (_folder() / "scan_history.txt").exists())
    opened: list = []
    real_open = app_config.open_folder
    app_config.open_folder = opened.append
    try:
        o._open_bad_reads()
    finally:
        app_config.open_folder = real_open
    check("OPEN FOLDER opens bad_reads", opened == [folder], f"({opened})")
    o._on_bad_reads_switch(False)
    n = len(list(folder.glob("*.png")))
    o._on_track_state({"state": "locked", "pin": None,
                       "digits": {"left": 1, "top": 1, "width": 9, "height": 9}})
    o._on_result(*_bad())
    check("switched off: nothing more saved", len(list(folder.glob("*.png"))) == n
          and o.cfg["debug_save_bad_reads"] is False)


def check_reset() -> None:
    from app import config as app_config
    from app import main as main_mod

    print("RESET SETTINGS")
    folder = _folder()
    cfg = app_config.Config()
    cfg["debug_scan_history"] = True
    cfg["debug_save_bad_reads"] = True
    cfg.save()
    (folder / "scan_history.txt").write_text("x\n", encoding="utf-8")
    main_mod.save_bad_read(folder / "bad_reads", _crop(), 0.0, None, 1)
    app_config.reset_to_defaults(folder)
    check("reset removed scan_history.txt and bad_reads/",
          not (folder / "scan_history.txt").exists() and not (folder / "bad_reads").exists(),
          f"({sorted(p.name for p in folder.iterdir())})")
    fresh = app_config.Config.load()
    check("both switches back to off", fresh["debug_scan_history"] is False
          and fresh["debug_save_bad_reads"] is False)


def main() -> int:
    if QApplication.instance() is None:
        QApplication(sys.argv)
    print(f"settings folder {_folder()}")
    for test in (check_defaults, check_off_writes_nothing, check_history,
                 check_bad_reads, check_reset):
        try:
            test()
        except Exception:
            import traceback
            traceback.print_exc()
            check(f"{test.__name__} ran", False)
    print("-" * 78)
    print("ALL CHECKS PASSED" if FAILS == 0 else f"{FAILS} CHECK(S) FAILED")
    return 0 if FAILS == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
