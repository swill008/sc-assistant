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

Logs: main()'s start-up order (crash hook, then app.log, then the settings)
puts a broken config.json, a scanner warning and an unhandled error in
app.log (the crash in error.log too); DETAILED LOG is saved and switches the
level at once; OPEN LOG / VIEW LOG (one window, position saved as
logviewer_pos) / EXPORT DIAGNOSTICS (zip on a temporary Desktop, else the
settings folder, without notes or inventory) through the real Settings
buttons; RESET SETTINGS turns DETAILED LOG off, keeps app.log and closes the
log window.
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


# ---------------------------------------------------------------------------
# Settings → DEBUG → Logs (app.log, DETAILED LOG, VIEW LOG, EXPORT DIAGNOSTICS)
def _app_log() -> str:
    import logging

    for handler in logging.getLogger().handlers:
        handler.flush()
    path = _folder() / "app.log"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def check_log_defaults() -> None:
    from app.config import DEFAULTS, RESET_KEEP, _listed

    print("LOGS: DEFAULTS")
    check("DETAILED LOG off by default", DEFAULTS.get("debug_detailed_log") is False,
          f"({DEFAULTS.get('debug_detailed_log')!r})")
    check("log window position key, unplaced by default",
          "logviewer_pos" in DEFAULTS and DEFAULTS["logviewer_pos"] is None)
    check("RESET SETTINGS keeps app.log and its rotated copies",
          all(_listed(n, RESET_KEEP) for n in ("app.log", "app.log.1", "app.log.3")),
          f"({RESET_KEEP})")


def check_startup_logging() -> None:
    """main()'s own order: the crash hook, then _startup_config (app.log,
    the settings, DETAILED LOG). A broken config.json, a scanner error and an
    unhandled error must all reach app.log; the crash also error.log."""
    import inspect
    import logging

    from app import config as app_config
    from app import main as main_mod

    print("LOGS: STARTUP")
    if not hasattr(main_mod, "_startup_config"):
        check("main.py starts app.log at start-up (_startup_config)", False)
        return
    src = inspect.getsource(main_mod.main)
    order = [src.find(s) for s in ("_install_crash_log()", "_startup_config()", "OverlayApp(")]
    check("main(): crash hook, then app.log + settings, then the windows",
          -1 not in order and order == sorted(order), f"({order})")
    folder = _folder()
    app_config.CONFIG_PATH.write_text("{ not json", encoding="utf-8")
    try:
        main_mod._install_crash_log()
        cfg = main_mod._startup_config()
    finally:
        app_config.CONFIG_PATH.unlink(missing_ok=True)
    text = _app_log()
    check("app.log is in the settings folder", (folder / "app.log").is_file())
    check("a broken config.json is logged, not swallowed",
          "WARNING app.config: Could not read" in text, f"({text[-200:]!r})")
    check("detailed off: no trace lines", " DEBUG " not in text)
    check("defaults used", cfg["debug_detailed_log"] is False)

    o = _overlay()
    o._on_scan_error("Capture failed: test warning 7731")
    o._on_scan_error("Capture failed: test warning 7731")      # repeated every read
    text = _app_log()
    check("a warning raised in the app lands in app.log",
          "WARNING app.main: scanner: Capture failed: test warning 7731" in text,
          f"({text[-200:]!r})")
    check("a repeated scanner error is written once", text.count("test warning 7731") == 1)

    try:
        raise ValueError("unhandled test error 4419")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    text = _app_log()
    err = (folder / "error.log").read_text(encoding="utf-8") if (folder / "error.log").is_file() else ""
    check("an unhandled error reaches error.log", "unhandled test error 4419" in err)
    check("an unhandled error reaches app.log", "unhandled test error 4419" in text
          and "CRITICAL" in text, f"({text[-200:]!r})")
    logging.getLogger("app.main").debug("trace before")       # not written


def check_detailed_switch() -> None:
    from app import applog
    from app import config as app_config

    print("LOGS: DETAILED LOG")
    o = _overlay()
    if not hasattr(o, "_on_detailed_log"):
        check("main.py has the DETAILED LOG switch", False)
        return
    o.cfg = app_config.Config()          # a real one: the switch must reach the file
    o._on_detailed_log(True)
    o._on_sections_changed(["debug"])    # a trace point
    check("DETAILED LOG on is saved", app_config.Config.load()["debug_detailed_log"] is True)
    check("DETAILED LOG on switches the level at once", applog.detailed())
    check("trace lines written while on", "DEBUG app.main: settings sections open: ['debug']"
          in _app_log(), f"({_app_log()[-200:]!r})")
    o._on_detailed_log(False)
    o._on_sections_changed(["scanner"])
    check("DETAILED LOG off is saved", app_config.Config.load()["debug_detailed_log"] is False)
    check("off: no more trace lines", not applog.detailed()
          and "settings sections open: ['scanner']" not in _app_log())
    app_config.CONFIG_PATH.unlink(missing_ok=True)


class _Opened(list):
    def __call__(self, path):
        self.append(Path(path))


def _logs_overlay():
    """Bare overlay with the real SettingsPanel wired as _wire wires it."""
    import inspect

    from app import main as main_mod
    from app.ui.settings_panel import SettingsPanel

    o = _overlay()
    panel = SettingsPanel()
    panel.setWindowOpacity(0.0)
    panel.move(-4000, -4000)
    o.settings = panel
    wiring = inspect.getsource(main_mod.OverlayApp._wire)
    pairs = (("detailed_log_toggled", o._on_detailed_log), ("open_log", o._open_log),
             ("view_log", o._view_log), ("export_diagnostics", o._export_diagnostics))
    for name, slot in pairs:
        check(f"_wire connects Settings {name}",
              f"self.settings.{name}.connect(self._{slot.__name__.lstrip('_')})" in wiring)
        getattr(panel, name).connect(slot)
    return o, panel


def check_log_buttons() -> None:
    import tempfile
    import zipfile

    from PySide6.QtWidgets import QApplication

    from app import applog
    from app import config as app_config
    from app import main as main_mod
    from app.ui.log_viewer import LogViewer

    print("LOGS: OPEN LOG, VIEW LOG, EXPORT DIAGNOSTICS")
    if not hasattr(main_mod, "diagnostics_target"):
        check("main.py has the Logs buttons", False)
        return
    folder = _folder()

    class _HiddenViewer(LogViewer):     # the real window, never seen
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.setWindowOpacity(0.0)

    opened = _Opened()
    real = (app_config.open_folder, main_mod.LogViewer, main_mod._desktop_dir)
    app_config.open_folder = opened
    main_mod.LogViewer = _HiddenViewer
    desktop = Path(tempfile.mkdtemp(prefix="ca_desktop_"))
    try:
        o, panel = _logs_overlay()
        panel.log_open_btn.click()
        check("OPEN LOG opens app.log", opened == [applog.log_path()], f"({opened})")

        # Off the main monitor when there is another (it is see-through anyway).
        others = [sc for sc in QApplication.screens() if sc is not QApplication.primaryScreen()]
        o.cfg["logviewer_pos"] = ([others[0].geometry().x() + 60, others[0].geometry().y() + 60]
                                  if others else None)
        panel.log_view_btn.click()
        viewer = o._log_viewer
        if others:
            check("VIEW LOG opens where it was saved",
                  [viewer.x(), viewer.y()] == o.cfg["logviewer_pos"],
                  f"({viewer.pos()} vs {o.cfg['logviewer_pos']})")
        check("VIEW LOG opens the log window on app.log",
              isinstance(viewer, LogViewer) and viewer.isVisible()
              and viewer.path == applog.log_path(), f"({viewer})")
        viewer.hide()
        panel.log_view_btn.click()
        check("VIEW LOG again: the same one window", o._log_viewer is viewer and viewer.isVisible())
        viewer.move(viewer.x() + 7, viewer.y() + 5)
        where = [viewer.x(), viewer.y()]
        o.nav.shown = False
        o.hauling.capacity = lambda: 32
        o.hauling.current_commodity = lambda: 0
        o._save_state()
        check("its position is saved as logviewer_pos", o.cfg["logviewer_pos"] == where,
              f"({o.cfg['logviewer_pos']} vs {where})")
        viewer.open_file.emit(applog.log_path())
        check("its OPEN FILE opens app.log", opened[-1] == applog.log_path())
        viewer.close_requested.emit()
        check("its ✕ hides it", not viewer.isVisible())

        # EXPORT DIAGNOSTICS: the user's records stay out of the zip.
        (folder / "config.json").write_text('{"poll_ms": 250}', encoding="utf-8")
        for name in ("notes.txt", "inventory.json", "unlocked_blueprints.json"):
            (folder / name).write_text("private", encoding="utf-8")
        main_mod.log.warning("before export 5512")
        main_mod._desktop_dir = lambda: desktop
        opened.clear()
        panel.log_export_btn.click()
        zips = list(desktop.glob("*.zip"))
        names = zipfile.ZipFile(zips[0]).namelist() if len(zips) == 1 else []
        check("EXPORT DIAGNOSTICS writes one zip on the Desktop, named by date",
              len(zips) == 1 and zips[0].name.startswith("SC Assistant diagnostics "),
              f"({zips})")
        check("the zip holds app.log, config.json and the system summary",
              {"app.log", "config.json", "system.txt"} <= set(names), f"({names})")
        check("the zip holds no notes, inventory or blueprints",
              not {"notes.txt", "inventory.json", "unlocked_blueprints.json"} & set(names),
              f"({names})")
        summary = zipfile.ZipFile(zips[0]).read("system.txt").decode("utf-8") if names else ""
        screen = QApplication.primaryScreen().name()
        check("the summary lists the monitors", "Monitors:" in summary and screen in summary)
        check("then its folder is opened", opened == [desktop], f"({opened})")
        check("the note shows where it went",
              not panel.log_note.isHidden() and "Desktop" in panel.log_note.text()
              and zips and zips[0].name in panel.log_note.text(), f"({panel.log_note.text()!r})")
        main_mod._desktop_dir = lambda: None
        opened.clear()
        panel.log_export_btn.click()
        here = list(folder.glob("SC Assistant diagnostics *.zip"))
        check("no Desktop: the zip goes in the settings folder",
              len(here) == 1 and opened == [folder]
              and "settings folder" in panel.log_note.text(), f"({here}, {opened})")
        for p in here:
            p.unlink()
        for name in ("notes.txt", "inventory.json", "unlocked_blueprints.json", "config.json"):
            (folder / name).unlink(missing_ok=True)
        panel.close()
    finally:
        app_config.open_folder, main_mod.LogViewer, main_mod._desktop_dir = real
        import shutil
        shutil.rmtree(desktop, ignore_errors=True)


def check_reset_logs() -> None:
    from types import SimpleNamespace

    from app import applog
    from app import config as app_config
    from app import main as main_mod
    from app.ui.log_viewer import LogViewer

    print("LOGS: RESET SETTINGS")
    folder = _folder()
    cfg = app_config.Config()
    cfg["debug_detailed_log"] = True
    cfg.save()
    applog.set_detailed(True)
    main_mod.log.warning("kept through the reset 9203")
    (folder / "app.log.1").write_text("older log\n", encoding="utf-8")
    o = _overlay()
    o.cfg = app_config.Config.load()
    o.scan = SimpleNamespace(stop=lambda: None, wait=lambda ms: True, resume=lambda: None)
    restarted: list = []
    o.restart = lambda: restarted.append(1)
    viewer = o._log_viewer = LogViewer(applog.log_path())
    viewer.setWindowOpacity(0.0)
    viewer.move(-4000, -4000)
    viewer.show()
    o._reset_settings()
    check("reset restarts", restarted == [1])
    check("reset: DETAILED LOG off now and in the settings",
          not applog.detailed() and o.cfg["debug_detailed_log"] is False
          and app_config.Config.load()["debug_detailed_log"] is False)
    check("reset keeps app.log and its rotated copy",
          "kept through the reset 9203" in _app_log() and (folder / "app.log.1").is_file(),
          f"({sorted(p.name for p in folder.iterdir())})")
    check("reset closes the log window", not viewer.isVisible())
    viewer.deleteLater()
    (folder / "app.log.1").unlink(missing_ok=True)


def main() -> int:
    if QApplication.instance() is None:
        QApplication(sys.argv)
    print(f"settings folder {_folder()}")
    for test in (check_defaults, check_off_writes_nothing, check_history,
                 check_bad_reads, check_reset, check_log_defaults, check_startup_logging,
                 check_detailed_switch, check_log_buttons, check_reset_logs):
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
