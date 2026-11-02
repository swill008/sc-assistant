"""LOG viewer checks: newest lines of a file, following new lines within
~1.5 s, reload on rotation, level and text filters, COPY, the auto-scroll
pause, and the layout at UI scale 1.0 and 1.5.

    python -m tools.logviewer_selftest              # PASS/FAIL lines, exit code = failures
    python tools/logviewer_selftest.py --root DIR   # run against another copy of app/
    python -m tools.logviewer_selftest --shot PNG   # also save a picture at UI 1.0

Needs a desktop session. Every window is made invisible (opacity 0) before it
is shown and is placed on a secondary monitor, never on the main (game)
monitor. APPDATA points at a temporary folder; log files are temporary too.
The clipboard text is put back after the COPY check.
"""
from __future__ import annotations

from tools import _testguard

_testguard.install()        # first: no focus, no hotkeys

import functools
import importlib
import itertools
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if "--root" in sys.argv:
    ROOT = Path(sys.argv[sys.argv.index("--root") + 1]).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "--root" in sys.argv:
    # The guard already imported this checkout's app package: drop it so app
    # comes from ROOT, and fake that copy's hotkeys too.
    for _name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        del sys.modules[_name]
    _testguard._fake_hotkeys()
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="logviewer_selftest_")
TMP = Path(tempfile.mkdtemp(prefix="logviewer_files_"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton  # noqa: E402

FAILURES = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global FAILURES
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}", flush=True)
    if not ok:
        FAILURES += 1
    return ok


def guarded(fn):
    """A check group that crashes (e.g. the module missing in old code) is a FAIL."""
    @functools.wraps(fn)
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            check(f"{fn.__name__} ran without errors", False,
                  f"({type(exc).__name__}: {exc})")
            traceback.print_exc(limit=3)
            return None
    return run


def stamp(level: str, msg: str, i: int = 0) -> str:
    return f"2026-11-01 17:50:{i % 60:02d}.{i % 1000:03d} {level} app.test: {msg}"


def write(path: Path, lines: list[str], mode: str = "a") -> None:
    with open(path, mode, encoding="utf-8", newline="\n") as fh:
        for line in lines:
            fh.write(line + "\n")


def spin(seconds: float, until=None) -> float:
    """Runs the event loop; returns the time taken when until() came true."""
    start = time.monotonic()
    while time.monotonic() - start < seconds:
        QApplication.processEvents()
        if until is not None and until():
            return time.monotonic() - start
        time.sleep(0.02)
    return -1.0


def _on_secondary(widget, screen) -> None:
    widget.setWindowOpacity(0.0)        # before show
    geo = screen.availableGeometry()
    widget.move(geo.left() + 40, geo.top() + 40)
    widget.show()
    QApplication.processEvents()


def _viewer(screen, path: Path, scale: float = 1.0):
    from app.ui import theme
    theme.set_scale(scale)
    import app.ui.log_viewer as lv
    importlib.reload(lv)
    viewer = lv.LogViewer()
    viewer.set_path(path)
    _on_secondary(viewer, screen)
    return lv, viewer


def _done(viewer) -> None:
    from app.ui import theme
    viewer.close()
    viewer.deleteLater()
    QApplication.processEvents()
    theme.set_scale(1.0)


def _new_log(name: str, lines: list[str]) -> Path:
    path = TMP / name
    write(path, lines, "w")
    return path


# ---------------------------------------------------------------------------
@guarded
def check_tail_and_follow(screen) -> None:
    path = _new_log("follow.log", [stamp("WARNING", f"old {i}", i) for i in range(2500)])
    lv, viewer = _viewer(screen, path)
    try:
        lines = viewer.visible_lines()
        check("shows the newest 2,000 lines of a 2,500-line file",
              len(lines) == lv.MAX_LINES and lines[-1].endswith("old 2499")
              and lines[0].endswith("old 500"), f"({len(lines)}; first {lines[:1]})")
        check("title LOG, size 640 x 420 design px",
              viewer.title.text() == "LOG"
              and (viewer.width(), viewer.height()) == (640, 420),
              f"({viewer.title.text()!r}, {viewer.width()}x{viewer.height()})")
        write(path, [stamp("ERROR", "new line 1")])
        took = spin(2.5, lambda: viewer.visible_lines()[-1].endswith("new line 1"))
        check("a new line appears within ~1.5 s (timer poll, no manual call)",
              0 <= took <= 1.5, f"(took {took:.2f} s)")
        # A line written in two pieces shows once it is whole.
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(stamp("ERROR", "half"))
        viewer.poll()
        check("an unfinished line is held back", not viewer.visible_lines()[-1].endswith("half"))
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(" done\n")
        viewer.poll()
        check("... and shown whole once finished",
              viewer.visible_lines()[-1].endswith("half done"),
              f"({viewer.visible_lines()[-1]!r})")
        check("follows: scrolled to the end", viewer.following
              and viewer.view.verticalScrollBar().value()
              == viewer.view.verticalScrollBar().maximum())
    finally:
        _done(viewer)


@guarded
def check_rotation(screen) -> None:
    path = _new_log("rot.log", [stamp("WARNING", f"before {i}", i) for i in range(50)])
    lv, viewer = _viewer(screen, path)
    try:
        # Like RotatingFileHandler: rename to .1, start a new, smaller file.
        os.replace(path, path.with_name("rot.log.1"))
        write(path, [stamp("WARNING", "after rotate")], "w")
        took = spin(2.5, lambda: viewer.visible_lines() == [stamp("WARNING", "after rotate")])
        check("rotation (file renamed, new file) reloads within ~1.5 s",
              0 <= took <= 1.5, f"(took {took:.2f} s; {viewer.visible_lines()[:3]})")
        # Truncated in place to fewer bytes than were read.
        write(path, [stamp("WARNING", f"grow {i}", i) for i in range(20)])
        viewer.poll()
        write(path, [stamp("ERROR", "truncated")], "w")
        viewer.poll()
        check("a file that shrank is read again from the start",
              viewer.visible_lines() == [stamp("ERROR", "truncated")],
              f"({viewer.visible_lines()[:3]})")
        missing = TMP / "missing.log"
        viewer.set_path(missing)
        check("a missing file: empty, no error", viewer.visible_lines() == []
              and "No log yet" in viewer.view.placeholderText())
        write(missing, [stamp("WARNING", "born")], "w")
        viewer.poll()
        check("... picked up once it is created",
              viewer.visible_lines() == [stamp("WARNING", "born")])
    finally:
        _done(viewer)


@guarded
def check_filters(screen) -> None:
    lines = [stamp("DEBUG", "trace step", 1), stamp("INFO", "info thing", 2),
             stamp("WARNING", "warn alpha", 3), stamp("ERROR", "boom beta", 4),
             "Traceback (most recent call last):", '  File "x.py", line 1',
             stamp("CRITICAL", "dead gamma", 5), stamp("WARNING", "warn delta", 6)]
    path = _new_log("filters.log", lines)
    lv, viewer = _viewer(screen, path)
    try:
        check("ALL shows every line", viewer.visible_lines() == lines)
        viewer.filter_buttons["WARNING+"].click()
        check("WARNING+ hides DEBUG and INFO, keeps the traceback with its ERROR",
              viewer.level_filter == "WARNING+" and viewer.visible_lines() == lines[2:],
              f"({viewer.visible_lines()})")
        viewer.filter_buttons["ERROR"].click()
        check("ERROR keeps ERROR, CRITICAL and the traceback lines",
              viewer.visible_lines() == lines[3:7], f"({viewer.visible_lines()})")
        check("level buttons are exclusive",
              [n for n, b in viewer.filter_buttons.items() if b.isChecked()] == ["ERROR"])
        viewer.filter_buttons["ALL"].click()
        viewer.set_text_filter("WARN")
        check("text filter (case-insensitive)",
              viewer.visible_lines() == [lines[2], lines[7]], f"({viewer.visible_lines()})")
        viewer.set_level_filter("ERROR")
        check("text + level filters combine", viewer.visible_lines() == [])
        viewer.set_text_filter("")
        viewer.set_level_filter("ALL")
        viewer.set_text_filter("beta")
        write(path, [stamp("ERROR", "late beta"), stamp("ERROR", "late other")])
        viewer.poll()
        check("new lines go through the filter",
              viewer.visible_lines() == [lines[3], stamp("ERROR", "late beta")],
              f"({viewer.visible_lines()})")
        shown = viewer.view.toPlainText().splitlines()
        check("the view shows exactly the filtered lines",
              shown == viewer.visible_lines(), f"({shown})")

        clip = QGuiApplication.clipboard()
        saved = clip.text()
        try:
            viewer.copy_btn.click()
            check("COPY puts the shown lines on the clipboard",
                  clip.text() == "\n".join([lines[3], stamp("ERROR", "late beta")]),
                  f"({clip.text()!r})")
        finally:
            clip.setText(saved)
        got = []
        viewer.open_file.connect(got.append)
        viewer.open_btn.click()
        check("OPEN FILE emits open_file(path)", got == [path], f"({got})")
        closed = []
        viewer.close_requested.connect(lambda: closed.append(True))
        viewer._close.click()
        check("✕ emits close_requested", closed == [True])
    finally:
        _done(viewer)


@guarded
def check_autoscroll_pause(screen) -> None:
    path = _new_log("scroll.log", [stamp("WARNING", f"line {i}", i) for i in range(300)])
    lv, viewer = _viewer(screen, path)
    try:
        bar = viewer.view.verticalScrollBar()
        check("starts at the end, LIVE", viewer.following and bar.value() == bar.maximum()
              and bar.maximum() > 0 and viewer.status.text() == "LIVE")
        bar.setValue(10)                    # the user scrolls up
        QApplication.processEvents()
        check("scrolling up pauses (PAUSED)", not viewer.following
              and viewer.status.text() == "PAUSED")
        write(path, [stamp("WARNING", f"more {i}", i) for i in range(50)])
        viewer.poll()
        QApplication.processEvents()
        check("while paused new lines do not move the view",
              bar.value() == 10 and viewer.visible_lines()[-1].endswith("more 49"),
              f"(value {bar.value()})")
        viewer.set_text_filter("line 1")
        check("a filter change while paused stays paused", not viewer.following)
        viewer.set_text_filter("")
        viewer.status.click()               # jump to the end
        check("clicking PAUSED jumps to the end and follows again",
              viewer.following and bar.value() == bar.maximum()
              and viewer.status.text() == "LIVE")
        bar.setValue(bar.maximum())
        write(path, [stamp("WARNING", "tail")])
        viewer.poll()
        QApplication.processEvents()
        check("at the end, new lines keep it at the end",
              viewer.following and bar.value() == bar.maximum())
    finally:
        _done(viewer)


@guarded
def check_layout(screen) -> None:
    """Header and tool row at UI 1.0 and 1.5: inside the window, no overlaps,
    no button text cut off."""
    from app.ui import theme
    path = _new_log("layout.log", [stamp("ERROR", "x" * 300, 1)])
    for scale in (1.0, 1.5):
        lv, viewer = _viewer(screen, path, scale)
        try:
            check(f"UI {scale}: size is theme.px(640 x 420)",
                  (viewer.width(), viewer.height()) == (theme.px(640), theme.px(420)))
            parts = [viewer.title, viewer.status, viewer._close, viewer.copy_btn,
                     viewer.open_btn, viewer.search, *viewer.filter_buttons.values()]
            boxes = {w.objectName() or w.text() or type(w).__name__: w.geometry()
                     for w in parts}
            boxes["view"] = viewer.view.geometry()
            boxes["footer"] = viewer.footer.geometry()
            overlaps = [f"{a}/{b}" for a, b in itertools.combinations(boxes, 2)
                        if boxes[a].intersects(boxes[b])]
            inside = viewer.rect().adjusted(theme.px(3), theme.px(3), -theme.px(3), -theme.px(3))
            outside = [k for k, g in boxes.items() if not inside.contains(g)]
            cut = []
            for w in parts:
                if isinstance(w, QPushButton) and w is not viewer._close:
                    if QFontMetrics(w.font()).horizontalAdvance(w.text()) > w.width():
                        cut.append(w.text())
            check(f"UI {scale}: nothing overlaps", not overlaps, f"({overlaps})")
            check(f"UI {scale}: everything inside the window", not outside, f"({outside})")
            check(f"UI {scale}: no button text cut off", not cut, f"({cut})")
            check(f"UI {scale}: filter box keeps a usable width",
                  viewer.search.width() >= theme.px(120), f"({viewer.search.width()})")
            check(f"UI {scale}: nothing takes focus on show",
                  QApplication.focusWidget() is None
                  or not isinstance(QApplication.focusWidget(), QLineEdit))
        finally:
            _done(viewer)


def save_shot(screen, target: Path) -> None:
    sample = [
        "2026-11-01 17:49:58.102 INFO app.main: started v1.0.37",
        "2026-11-01 17:50:01.044 DEBUG app.tracking: find_anchor_in_box: pin found by reference",
        "2026-11-01 17:50:02.510 WARNING app.notes: notes.txt is locked; retrying",
        "2026-11-01 17:50:03.877 DEBUG app.sigsource: using cached signatures (age 2 h)",
        "2026-11-01 17:50:05.212 ERROR app.updater: download failed: timed out",
        "Traceback (most recent call last):",
        '  File "app/updater.py", line 212, in download',
        "TimeoutError: timed out",
        "2026-11-01 17:50:07.930 DEBUG app.main: DRAW REGION frame 3: locked",
        "2026-11-01 17:50:09.401 WARNING app.uex: price list is 26 h old",
    ]
    path = _new_log("app.log", sample)
    _lv, viewer = _viewer(screen, path, 1.0)
    try:
        viewer.grab().save(str(target))
        print(f"  saved {target}")
    finally:
        _done(viewer)


# ---------------------------------------------------------------------------
def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if QApplication.instance() is None:
        QApplication(sys.argv)
    print(f"Code under test: {ROOT}")
    primary = QGuiApplication.primaryScreen()
    screens = [s for s in QGuiApplication.screens() if s is not primary]
    if not screens:
        print("  FAIL  no secondary monitor: these checks never use the main monitor")
        return 1
    print("-" * 78)
    for fn in (check_tail_and_follow, check_rotation, check_filters,
               check_autoscroll_pause, check_layout):
        print(fn.__name__)
        fn(screens[0])
    if "--shot" in sys.argv:
        save_shot(screens[0], Path(sys.argv[sys.argv.index("--shot") + 1]))
    print("-" * 78)
    print(f"{FAILURES} failure(s)")
    return FAILURES


if __name__ == "__main__":
    raise SystemExit(main())
