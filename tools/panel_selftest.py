"""Scanner card checks: SCANNED / MATCHED SIGNATURE labels, READ NN%, the
"or <LABEL> ×n" second line and the result border, plus the card layout at
UI scale 1.0 and 1.5 (nothing overlaps, nothing squeezed).

    python -m tools.panel_selftest            # PASS/FAIL lines, exit code = failures
    python tools/panel_selftest.py --root DIR # run against another copy of app/

Needs a desktop session. Every window is made invisible (opacity 0) before it
is shown and is placed on a secondary monitor, never on the main (game)
monitor. APPDATA points at a temporary folder.
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
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if "--root" in sys.argv:
    ROOT = Path(sys.argv[sys.argv.index("--root") + 1]).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="panel_selftest_")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

FAILURES = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global FAILURES
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}", flush=True)
    if not ok:
        FAILURES += 1
    return ok


def guarded(fn):
    """A check group that crashes (e.g. an API missing in old code) is a FAIL."""
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


def _close(a: QColor, b: QColor, tol: int = 40) -> bool:
    return (abs(a.red() - b.red()) <= tol and abs(a.green() - b.green()) <= tol
            and abs(a.blue() - b.blue()) <= tol)


def _has_colour(image, rect: QRect, colour: QColor, tol: int = 40) -> bool:
    """rect in widget pixels; the grab may be at the screen's pixel ratio."""
    r = image.devicePixelRatio()
    rect = QRect(int(rect.x() * r), int(rect.y() * r), max(1, int(rect.width() * r)),
                 max(1, int(rect.height() * r))).intersected(image.rect())
    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            c = image.pixelColor(x, y)
            if c.alpha() > 100 and _close(c, colour, tol):
                return True
    return False


def _on_secondary(widget, screen) -> None:
    widget.setWindowOpacity(0.0)        # before show
    geo = screen.availableGeometry()
    widget.move(geo.left() + 40, geo.top() + 40)
    widget.show()
    QApplication.processEvents()


def _panel(screen, scale: float = 1.0):
    from app.ui import theme
    theme.set_scale(scale)
    import app.ui.mining_panel as mp
    importlib.reload(mp)
    panel = mp.MiningPanel()
    _on_secondary(panel, screen)
    return mp, panel


def _done(panel) -> None:
    from app.ui import theme
    panel.close()
    panel.deleteLater()
    QApplication.processEvents()
    theme.set_scale(1.0)


def _data():
    from app.mining import MiningData
    return MiningData(source="bundled")


# ---------------------------------------------------------------------------
@guarded
def check_signature_labels(screen) -> None:
    _mp, panel = _panel(screen)
    try:
        check("start: SCANNED SIGNATURE —", panel.scanned_text == "SCANNED SIGNATURE —",
              f"({panel.scanned_text!r})")
        check("start: MATCHED SIGNATURE —", panel.matched_text == "MATCHED SIGNATURE —",
              f"({panel.matched_text!r})")
        panel.set_scanned(7200)
        check("set_scanned(7200) -> SCANNED SIGNATURE 7,200",
              panel.scanned_text == "SCANNED SIGNATURE 7,200", f"({panel.scanned_text!r})")
        panel.set_scanned(None)
        check("set_scanned(None) -> SCANNED SIGNATURE —",
              panel.scanned_text == "SCANNED SIGNATURE —", f"({panel.scanned_text!r})")

        data = _data()
        matches = data.lookup(7200)
        panel.set_scanned(7210)
        panel.set_scan(7210, 0.82, "stable", matches)
        QApplication.processEvents()
        want = f"MATCHED SIGNATURE {matches[0].target:,}"
        check("matched side shows matches[0].target, scanned side the read number",
              panel.matched_text == want and panel.scanned_text == "SCANNED SIGNATURE 7,210",
              f"({panel.matched_text!r}, {panel.scanned_text!r})")
        check("READ 82% replaces 82% MATCH", panel.read_text == "READ 82%",
              f"({panel.read_text!r})")
        panel.set_scan(1234567 % 99991, 0.5, "stable", [])
        check("no match -> MATCHED SIGNATURE —", panel.matched_text == "MATCHED SIGNATURE —",
              f"({panel.matched_text!r})")
        panel.set_scan_idle()
        check("idle: no READ text", panel.read_text == "", f"({panel.read_text!r})")
    finally:
        _done(panel)


@guarded
def check_read_colours(screen) -> None:
    """READ NN% keeps today's colours: green >= 75%, amber below."""
    from app.ui import theme
    mp, panel = _panel(screen)
    try:
        v = panel.verdict
        matches = _data().lookup(7200)
        for conf, colour, word in ((0.9, theme.GOOD, "green"), (0.5, theme.AMBER, "amber")):
            panel.set_scan(7200, conf, "stable", matches)
            QApplication.processEvents()
            img = v.grab().toImage()
            rect, _f, _a = v.rows(round(v.width() / theme.scale()),
                                  round(v.height() / theme.scale()))["read"]
            box = QRect(int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height()))
            check(f"READ {int(conf * 100)}% is {word}", _has_colour(img, box, colour, 30))
            # Scanned/matched numbers stay theme.TEXT (no green/yellow text).
            for name in ("scanned_value", "matched_value"):
                r, _f, _a = v.rows(v.width(), v.height())[name]   # UI 1.0: design = widget px
                box = QRect(int(r.x()), int(r.y()), int(r.width()), int(r.height()))
                check(f"{name} at {int(conf * 100)}%: no green/amber text",
                      not _has_colour(img, box, theme.GOOD, 30)
                      and not _has_colour(img, box, theme.AMBER, 30))
    finally:
        _done(panel)


@guarded
def check_alt_line(screen) -> None:
    from app.mining import Match
    data = _data()
    mp, panel = _panel(screen)
    try:
        cases = ((76000, "or DEBRIS ×38"), (10000, "or HARVESTABLES ×5"), (7200, ""))
        for value, want in cases:
            matches = data.lookup(value)
            panel.set_scan(value, 0.9, "stable", matches)
            QApplication.processEvents()
            check(f"lookup({value:,}): second line {want or 'empty'!r}",
                  panel.alt_text == want,
                  f"(got {panel.alt_text!r}; kinds {[m.kind for m in matches[:3]]})")

        def m(kind, name, count, delta=0, target=4000):
            return Match(kind=kind, name=name, count=count, target=target, delta=delta,
                         rarity=1, value=None, secondary=None)

        top = m("roc", "Ground deposit", 1)
        panel.set_scan(4000, 0.9, "stable", [top, m("roc", "Ground deposit", 2)])
        check("same kind second -> no second line", panel.alt_text == "", f"({panel.alt_text!r})")
        panel.set_scan(4000, 0.9, "stable", [top, m("debris", "Debris", 2, delta=5)])
        check("near (not exact) second -> no second line", panel.alt_text == "",
              f"({panel.alt_text!r})")
        odd = m("mystery", "Zorblite", 2)
        panel.set_scan(4000, 0.9, "stable", [top, odd])
        QApplication.processEvents()
        img = panel.grab().toImage()
        check("unknown kind as second: labelled, no error",
              panel.alt_text == f"or {mp.match_label(odd)} ×2" and not img.isNull(),
              f"({panel.alt_text!r})")
        panel.set_scan(4000, 0.9, "stable", [odd])
        QApplication.processEvents()
        img = panel.grab().toImage()
        check("unknown kind on top paints", not img.isNull() and panel.alt_text == ""
              and panel.verdict._detail() != "", f"(detail {panel.verdict._detail()!r})")
    finally:
        _done(panel)


@guarded
def check_result_border(screen) -> None:
    from app.ui import theme
    for scale in (1.0, 1.5):
        mp, panel = _panel(screen, scale)
        try:
            panel.set_scan(7200, 0.9, "stable", _data().lookup(7200))
            QApplication.processEvents()
            base = panel.verdict.grab().toImage()
            mid = panel.height() // 2
            for result, colour in (("match", theme.GOOD), ("nomatch", theme.AMBER),
                                   ("noread", theme.BAD)):
                panel.set_result(result)
                QApplication.processEvents()
                img = panel.grab().toImage()
                bw = theme.px(3)
                edge = QRect(0, mid - 5, bw + 1, 10)
                inner = QRect(bw + 3, mid - 5, 3, 10)
                check(f"UI {scale}: {result} -> ~{bw}px border in its colour",
                      panel.result == result and _has_colour(img, edge, colour, 30)
                      and not _has_colour(img, inner, colour, 30),
                      f"(result {panel.result!r})")
                check(f"UI {scale}: {result}: card content unchanged",
                      panel.verdict.grab().toImage() == base)
            panel.set_result(None)
            QApplication.processEvents()
            img = panel.grab().toImage()
            edge = QRect(0, mid - 5, theme.px(3) + 1, 10)
            check(f"UI {scale}: None -> thin edge only (no result colour)",
                  panel.result is None
                  and not any(_has_colour(img, edge, c, 30)
                              for c in (theme.GOOD, theme.AMBER, theme.BAD)))
            try:
                panel.set_result("green")
                bad = False
            except ValueError:
                bad = True
            check(f"UI {scale}: unknown result raises ValueError", bad)
        finally:
            _done(panel)


@guarded
def check_layout(screen) -> None:
    """Worst-case texts fit their rows at UI 1.0 and 1.5: no overlaps, nothing
    elided that must be read whole, all inside the card."""
    from app.mining import Match
    from app.ui import theme
    for scale in (1.0, 1.5):
        mp, panel = _panel(screen, scale)
        try:
            v = panel.verdict
            top = Match(kind="ship", name="Quantanium", count=10, target=100000, delta=7,
                        rarity=5, value=None, secondary="Inert")
            alt = Match(kind="harvest", name="Harvestables", count=10, target=100000,
                        delta=0, rarity=1, value=None, secondary=None)
            panel.set_scanned(100000)
            panel.set_scan(100000, 1.0, "stable", [top, alt], note="SCAN AREA MOVED")
            QApplication.processEvents()
            w = round(v.width() / theme.scale())
            h = round(v.height() / theme.scale())
            rows = v.rows(w, h)
            name, _c, count = v._headline(False)
            texts = {
                "scanned_caption": "SCANNED SIGNATURE", "matched_caption": "MATCHED SIGNATURE",
                "scanned_value": v.scanned_value_text(), "matched_value": v.matched_value_text(),
                "read": v.read_text(), "headline": name, "count": count,
                "detail": v._detail(), "alt": panel.alt_text, "note": "SCAN AREA MOVED",
            }
            boxes = {}
            squeezed = []
            for key, text in texts.items():
                rect, font, align = rows[key]
                fm = QFontMetrics(font)
                tw = min(fm.horizontalAdvance(text), rect.width())
                if fm.horizontalAdvance(text) > rect.width() and key not in ("detail",):
                    squeezed.append(key)
                x = rect.right() - tw if align & Qt.AlignmentFlag.AlignRight else rect.left()
                th = min(fm.height(), rect.height())
                boxes[key] = QRectF(x, rect.center().y() - th / 2, tw, th)
            overlaps = [f"{a}/{b}" for a, b in itertools.combinations(boxes, 2)
                        if boxes[a].intersected(boxes[b]).width() > 0.5
                        and boxes[a].intersected(boxes[b]).height() > 0.5]
            outside = [k for k, b in boxes.items()
                       if b.left() < 0 or b.top() < 0 or b.right() > w + 0.5
                       or b.bottom() > h + 0.5]
            bar_y = h - v.METER_FROM_BOTTOM
            meter_hit = [k for k, b in boxes.items() if k != "note"
                         and b.intersects(QRectF(0, bar_y, v.BAR_W, 3))]
            check(f"UI {scale}: card texts do not overlap", not overlaps, f"({overlaps})")
            check(f"UI {scale}: no squeezed text (worst case 100,000 / READ 100% / "
                  f"or HARVESTABLES ×10)", not squeezed, f"({squeezed})")
            check(f"UI {scale}: texts inside the card", not outside and not meter_hit,
                  f"(outside {outside}, on meter {meter_hit})")
            # Widget level: the verdict sits below the header, inside the margins
            # and clear of the 3 px border.
            vg = v.geometry()
            header = [wd.geometry() for wd in panel.findChildren(QLabel) if wd.isVisible()]
            header.append(panel._close.geometry())
            check(f"UI {scale}: card body below the header, inside the panel",
                  all(g.bottom() < vg.top() for g in header)
                  and vg.left() > theme.px(3) and vg.right() < panel.width() - theme.px(3)
                  and vg.bottom() < panel.height() - theme.px(3)
                  and panel.width() == theme.px(372),
                  f"(verdict {vg.getRect()}, panel {panel.width()}x{panel.height()})")
        finally:
            _done(panel)


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
    for fn in (check_signature_labels, check_read_colours, check_alt_line,
               check_result_border, check_layout):
        print(fn.__name__)
        fn(screens[0])
    print("-" * 78)
    print(f"{FAILURES} failure(s)")
    return FAILURES


if __name__ == "__main__":
    raise SystemExit(main())
