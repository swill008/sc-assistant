"""Settings → RESET SETTINGS and UNMATCHED READINGS.

    python -m tools.settings_extra_selftest

Drives the real SettingsPanel with real mouse clicks (QTest), off-screen:
the two-click RESET SETTINGS button (arms, reverts, emits once), its error
note, the UNMATCHED READINGS list (count, newest rows, OPEN FOLDER, two-click
CLEAR), the five collapsible groups (no Support group or donation text) (heading clicks, summaries, remembered and
forced-open groups, the window fitting itself), and the layout at UI scale 1.0
and 1.5 in every open/closed combination checked (no widgets overlap, no text
cut off, armed texts fit).
"""
from __future__ import annotations

from tools import _testguard

_testguard.install()        # first: no focus, no hotkeys

import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory(prefix="ca-settings-extra-")
os.environ["APPDATA"] = _TMP.name          # before app.config is imported
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QLabel,  # noqa: E402
                               QPushButton, QSlider, QWidget)

FAILS = 0
_APP = None                 # keeps the QApplication alive


def check(label: str, ok: bool, detail: str = "") -> None:
    global FAILS
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    if not ok:
        FAILS += 1


def _wait(cond, seconds: float = 3.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def _click(button: QPushButton) -> None:
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def _panel():
    from app.ui.settings_panel import SettingsPanel
    panel = SettingsPanel()
    panel.setWindowOpacity(0.0)
    panel.move(-4000, -4000)
    panel.show()
    QApplication.processEvents()
    return panel


def _entries(n: int, newest: float) -> list[dict]:
    """n entries, newest first, one minute apart."""
    return [{"value": 76000 + i * 1000, "kind": "unknown",
             "time": newest - 60 * i, "image": f"{i}.png"} for i in range(n)]


# ---------------------------------------------------------------------------
def check_reset() -> None:
    print("RESET SETTINGS")
    panel = _panel()
    btn = panel.reset_btn
    got: list[int] = []
    panel.reset_requested.connect(lambda: got.append(1))

    check("button reads RESET SETTINGS", btn.text() == "RESET SETTINGS", f"({btn.text()!r})")
    check("arms for about 3 s", 2500 <= panel._reset_timer.interval() <= 3500,
          f"({panel._reset_timer.interval()} ms)")

    _click(btn)
    check("first click: CLICK AGAIN TO RESET, nothing emitted",
          btn.text() == "CLICK AGAIN TO RESET" and panel.reset_armed and got == [],
          f"({btn.text()!r}, signals {got})")
    # Revert: shorten the wait so the test does not sit for 3 s.
    panel._reset_timer.start(150)
    reverted = _wait(lambda: not panel.reset_armed, 2.0)
    check("reverts by itself when not clicked again",
          reverted and btn.text() == "RESET SETTINGS" and got == [],
          f"({btn.text()!r}, signals {got})")

    _click(btn)
    _click(btn)
    check("second click emits reset_requested once and reverts",
          got == [1] and not panel.reset_armed and btn.text() == "RESET SETTINGS",
          f"(signals {got}, {btn.text()!r})")

    panel.set_reset_error("access denied")
    QApplication.processEvents()
    check("set_reset_error shows a note with the message",
          not panel.reset_note.isHidden() and "access denied" in panel.reset_note.text(),
          f"({panel.reset_note.text()!r})")
    panel.set_reset_error("")
    check("set_reset_error('') hides it", panel.reset_note.isHidden())
    panel.set_reset_error("busy")
    _click(btn)
    _click(btn)
    check("a new reset clears the old note", panel.reset_note.isHidden() and got == [1, 1])
    panel.close()
    panel.deleteLater()


def check_unmatched() -> None:
    print("UNMATCHED READINGS")
    panel = _panel()
    opened: list[int] = []
    cleared: list[int] = []
    panel.open_unmatched_folder.connect(lambda: opened.append(1))
    panel.clear_unmatched.connect(lambda: cleared.append(1))

    panel.set_unmatched([])
    check("empty: 'None saved', no rows, CLEAR off",
          panel.unmatched_text == "None saved" and not panel.unmatched_clear_btn.isEnabled(),
          f"({panel.unmatched_text!r})")

    newest = time.mktime((2026, 11, 1, 14, 32, 0, 0, 0, -1))
    panel.set_unmatched(_entries(5, newest))
    lines = panel.unmatched_text.split("\n")
    check("count of all entries", lines[0] == "5 saved", f"({lines[0]!r})")
    check("newest three rows, newest first",
          lines[1:] == ["76,000  01 Nov 14:32", "77,000  01 Nov 14:31", "78,000  01 Nov 14:30"],
          f"({lines[1:]})")
    panel.set_unmatched(_entries(1, newest))
    check("one entry: one row", panel.unmatched_text == "1 saved\n76,000  01 Nov 14:32",
          f"({panel.unmatched_text!r})")

    _click(panel.unmatched_open_btn)
    check("OPEN FOLDER emits open_unmatched_folder", opened == [1], f"({opened})")

    clear = panel.unmatched_clear_btn
    check("CLEAR on with entries", clear.isEnabled())
    _click(clear)
    check("CLEAR first click arms, nothing emitted",
          panel.clear_armed and clear.text() == "CLEAR?" and cleared == [],
          f"({clear.text()!r}, {cleared})")
    panel._clear_timer.start(150)
    check("CLEAR reverts by itself",
          _wait(lambda: not panel.clear_armed, 2.0) and clear.text() == "CLEAR" and cleared == [])
    _click(clear)
    _click(clear)
    check("CLEAR second click emits clear_unmatched once", cleared == [1] and not panel.clear_armed,
          f"({cleared})")
    panel.set_unmatched([])
    check("after clear the list is empty again",
          panel.unmatched_text == "None saved" and not clear.isEnabled())
    panel.close()
    panel.deleteLater()


def _visible_parts(panel: QWidget) -> list[QWidget]:
    kinds = (QLabel, QPushButton, QSlider, QComboBox)
    parts = []
    for w in panel.findChildren(QWidget):
        if not isinstance(w, kinds) or not w.isVisible():
            continue
        # Skip pieces inside another control (e.g. inside a combo box).
        parent = w.parentWidget()
        if parent is not panel and isinstance(parent, kinds):
            continue
        parts.append(w)
    return parts


def _rect(panel: QWidget, w: QWidget) -> QRect:
    return QRect(w.mapTo(panel, w.rect().topLeft()), w.size())


def check_layout() -> None:
    from app.ui import theme
    from app.ui.settings_panel import SECTION_IDS

    print("LAYOUT")
    for scale in (1.0, 1.5):
        theme.set_scale(scale)
        try:
            panel = _panel()
            panel.set_open_sections(SECTION_IDS)      # every widget on show
            panel.set_unmatched(_entries(5, time.time()))
            panel.set_reset_error("could not copy the settings folder: access denied")
            for armed in (False, True):
                panel._set_reset_armed(armed)
                panel._set_clear_armed(armed)
                QApplication.processEvents()
                panel.adjustSize()
                QApplication.processEvents()
                parts = _visible_parts(panel)
                rects = [(w, _rect(panel, w)) for w in parts]
                overlaps = [(a.text() if hasattr(a, "text") else type(a).__name__,
                             b.text() if hasattr(b, "text") else type(b).__name__)
                            for i, (a, ra) in enumerate(rects) for b, rb in rects[i + 1:]
                            if ra.intersects(rb)]
                inside = panel.rect()
                outside = [w.text() if hasattr(w, "text") else type(w).__name__
                           for w, r in rects if not inside.contains(r)]
                tag = "armed" if armed else "idle"
                check(f"UI {scale} {tag}: no widgets overlap", not overlaps, f"({overlaps[:4]})")
                check(f"UI {scale} {tag}: everything inside the window", not outside,
                      f"({outside[:4]})")
                cut = [w.text() for w in (panel.reset_btn, panel.unmatched_clear_btn,
                                          panel.unmatched_open_btn, panel.unmatched_label)
                       if w.width() < w.sizeHint().width()]
                cut += [v.text() for v, t in panel._unmatched_row_labels
                        if v.isVisible() and v.width() < v.sizeHint().width()]
                cut += [t.text() for v, t in panel._unmatched_row_labels
                        if t.isVisible() and t.width() < t.sizeHint().width()]
                check(f"UI {scale} {tag}: new buttons and rows not cut off", not cut, f"({cut})")
            check(f"UI {scale}: window keeps its width", panel.width() == theme.px(384),
                  f"({panel.width()} vs {theme.px(384)})")
            panel.close()
            panel.deleteLater()
        finally:
            theme.set_scale(1.0)


def _overlaps(panel: QWidget) -> tuple[list, list]:
    """(overlapping pairs, widgets outside the window) of what is on show."""
    rects = [(w, _rect(panel, w)) for w in _visible_parts(panel)]

    def name(w):
        return w.text() if hasattr(w, "text") else type(w).__name__
    overlaps = [(name(a), name(b)) for i, (a, ra) in enumerate(rects)
                for b, rb in rects[i + 1:] if ra.intersects(rb)]
    outside = [name(w) for w, r in rects if not panel.rect().contains(r)]
    return overlaps, outside


def _click_heading(panel, section_id: str, on_text: bool = False) -> None:
    header = panel.section_header(section_id)
    QTest.mouseClick(header.title if on_text else header, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def check_sections() -> None:
    from app.ui import settings_panel as sp
    from app.version import VERSION

    print("COLLAPSIBLE GROUPS")
    check("five group ids in order (no Support)",
          sp.SECTION_IDS == ("scanner", "scan_data", "hotkeys", "look", "update"),
          f"({sp.SECTION_IDS})")
    panel = _panel()
    got: list[list] = []
    panel.sections_changed.connect(lambda ids: got.append(list(ids)))

    tops = [panel.section_header(s).y() for s in sp.SECTION_IDS]
    check("headings top to bottom in SECTION_IDS order (Update & Reset last)",
          tops == sorted(tops) and len(set(tops)) == 5, f"({tops})")
    titles = [panel.section_header(s).title.text()[2:] for s in sp.SECTION_IDS]
    check("headings read SCANNER ... UPDATE & RESET",
          titles == ["SCANNER", "SCAN DATA", "HOTKEYS", "LOOK & SOUND",
                     "UPDATE & RESET"], f"({titles})")
    words = [w.text() for w in panel.findChildren(QLabel) + panel.findChildren(QPushButton)]
    donation = [t for t in words if any(k in t.lower() for k in
                                        ("coffee", "btc", "bitcoin", "bc1q", "donat", "support"))]
    check("no donation text, address or COPY button anywhere in Settings",
          not donation and "COPY" not in words
          and not any(hasattr(panel, n) for n in ("btc_label", "btc_copy", "_copy_btc"))
          and not hasattr(sp, "BTC_ADDRESS")
          and "bc1q" not in Path(sp.__file__).read_text(encoding="utf-8"),
          f"({donation})")
    check("new panel: only Scanner open", panel.open_sections == ["scanner"],
          f"({panel.open_sections})")
    check("headings never take focus",
          all(panel.section_header(s).focusPolicy() == Qt.FocusPolicy.NoFocus
              for s in sp.SECTION_IDS))

    panel.set_open_sections(["hotkeys", "bogus", "look"])
    QApplication.processEvents()
    check("set_open_sections opens exactly those (unknown dropped), no signal",
          panel.open_sections == ["hotkeys", "look"] and got == [],
          f"({panel.open_sections}, {got})")
    hot, scan = panel.section_header("hotkeys"), panel.section_header("scanner")
    check("open heading: ▾ and no summary; closed heading: ▸ with summary",
          hot.title.text().startswith("▾") and hot.summary.isHidden()
          and scan.title.text().startswith("▸") and not scan.summary.isHidden(),
          f"({hot.title.text()!r}, {scan.title.text()!r})")
    check("closed group's widgets hidden, open group's shown",
          not panel.region_btn.isVisible() and panel.voice_btn.isVisible())

    panel.set_open_sections([])
    QApplication.processEvents()
    closed_h = panel.height()
    _click_heading(panel, "scan_data")
    opened_h = panel.height()
    check("clicking a heading opens it and emits the open ids",
          panel.open_sections == ["scan_data"] and got == [["scan_data"]]
          and panel.reload_btn.isVisible(), f"({panel.open_sections}, {got})")
    check("window grows to fit an opened group", opened_h > closed_h,
          f"({closed_h} -> {opened_h})")
    _click_heading(panel, "update", on_text=True)
    check("a click on the heading text works too; several open at once",
          panel.open_sections == ["scan_data", "update"], f"({panel.open_sections})")
    _click_heading(panel, "scan_data")
    _click_heading(panel, "update")
    check("clicking again closes; the window shrinks back",
          panel.open_sections == [] and panel.height() == closed_h and got[-1] == [],
          f"({panel.height()} vs {closed_h}, {got[-1:]})")
    overlaps, outside = _overlaps(panel)
    check("all closed: nothing overlaps or sticks out", not overlaps and not outside,
          f"({overlaps[:3]}, {outside[:3]})")

    # Summaries come from the existing setters.
    panel.set_monitors([("DISP9", "DISP9 · 1920×1080 · 100%")], "DISP9")
    panel.set_region(None)
    check("scanner summary: monitor · no box",
          panel.section_summary("scanner") == "DISP9 · no box",
          f"({panel.section_summary('scanner')!r})")
    panel.set_region({"width": 300, "height": 40, "left": 10, "top": 20})
    check("scanner summary: monitor · box set",
          panel.section_summary("scanner") == "DISP9 · box set",
          f"({panel.section_summary('scanner')!r})")
    panel.set_version("4.3", 42)
    panel.set_unmatched(_entries(3, time.time()))
    check("scan data summary: ores · unmatched",
          panel.section_summary("scan_data") == "42 ores · 3 unmatched",
          f"({panel.section_summary('scan_data')!r})")
    panel.set_hotkeys({"toggle_nav": 0x72, "panic": 0x73})
    check("hotkeys summary", panel.section_summary("hotkeys") == "SHOW BAR F3 · HIDE ALL F4",
          f"({panel.section_summary('hotkeys')!r})")
    panel.set_ui_scale(125)
    panel.set_voice(False)
    check("look summary", panel.section_summary("look") == "UI 125% · voice off",
          f"({panel.section_summary('look')!r})")
    check("update summary: the installed version",
          panel.section_summary("update") == f"v{VERSION} installed",
          f"({panel.section_summary('update')!r})")
    panel._on_update_done("check", "999.0.0", "")
    check("update summary: vX available after CHECK found one",
          panel.section_summary("update") == "v999.0.0 available",
          f"({panel.section_summary('update')!r})")
    header = panel.section_header("scanner")
    panel.set_monitors([("X" * 120, "long")], "X" * 120)
    QApplication.processEvents()
    shown = header.summary.text()
    check("a long summary is elided inside the heading",
          shown != header.summary_text
          and header.summary.fontMetrics().horizontalAdvance(shown) <= header.summary.width(),
          f"({shown!r})")

    # Forced open: main keeps Scanner open while no box is drawn.
    got.clear()
    panel.set_force_open("scanner")
    _click_heading(panel, "scanner")
    check("forced group is open and its heading cannot close it",
          panel.open_sections == ["scanner"] and got == [], f"({panel.open_sections}, {got})")
    panel.set_force_open(None)
    check("released: it stays open", panel.open_sections == ["scanner"])
    _click_heading(panel, "scanner")
    check("released: the heading closes it again",
          panel.open_sections == [] and got == [[]], f"({panel.open_sections}, {got})")

    # First run: the DRAW REGION pulse opens Scanner.
    panel.set_draw_region_attention(True)
    _click_heading(panel, "scanner")
    check("DRAW REGION pulse forces Scanner open and keeps it open",
          panel.open_sections == ["scanner"] and panel.region_btn.isVisible(),
          f"({panel.open_sections})")
    panel.set_draw_region_attention(False)
    check("pulse off: Scanner stays open", panel.open_sections == ["scanner"])

    # Widgets in a closed group still exist and act (other tests click them).
    panel.set_open_sections([])
    resets: list[int] = []
    panel.reset_requested.connect(lambda: resets.append(1))
    panel.reset_btn.click()
    panel.reset_btn.click()
    check("a closed group's buttons still work", resets == [1], f"({resets})")

    # A key capture stops when Hotkeys closes.
    panel.set_open_sections(["hotkeys"])
    key = panel._key_buttons["panic"]
    key.click()
    capturing = key.capturing
    _click_heading(panel, "hotkeys")
    check("closing Hotkeys cancels a key capture", capturing and not key.capturing)
    panel.close()
    panel.deleteLater()


def check_section_layouts() -> None:
    """All closed, each group alone, some pairs, all open: at UI 1.0 and 1.5."""
    from app.ui import theme
    from app.ui.settings_panel import SECTION_IDS

    print("GROUP LAYOUTS")
    combos = [[]] + [[s] for s in SECTION_IDS] + [
        ["scanner", "scan_data"], ["hotkeys", "look"], ["look", "update"],
        ["scanner", "look", "update"], list(SECTION_IDS)]
    for scale in (1.0, 1.5):
        theme.set_scale(scale)
        try:
            panel = _panel()
            panel.set_monitors([("LG ULTRAGEAR+", "LG ULTRAGEAR+ · 5120×2160 · 150%")],
                               "LG ULTRAGEAR+")
            panel.set_version("4.3", 42)
            panel.set_unmatched(_entries(5, time.time()))
            panel.set_hotkeys({"toggle_nav": 0x72, "panic": 0x73})
            panel.set_debug(True)
            panel.set_region_note("The box was moved to fit the new monitor size.")
            heights: dict[str, int] = {}
            bad = []
            for ids in combos:
                panel.set_open_sections(ids)
                QApplication.processEvents()
                overlaps, outside = _overlaps(panel)
                if overlaps or outside:
                    bad.append((ids, overlaps[:2], outside[:2]))
                cut = [h.title.text() for h in (panel.section_header(s) for s in SECTION_IDS)
                       if h.title.width() < h.title.sizeHint().width()]
                if cut:
                    bad.append((ids, "heading cut", cut))
                heights["+".join(ids) or "none"] = panel.height()
            check(f"UI {scale}: {len(combos)} combinations, no overlap, nothing outside or cut",
                  not bad, f"({bad[:3]})")
            print(f"    UI {scale} heights: all closed {heights['none']} px, "
                  f"Scanner only {heights['scanner']} px, "
                  f"all open {heights['+'.join(SECTION_IDS)]} px")
            check(f"UI {scale}: all closed is the shortest",
                  heights["none"] == min(heights.values()))
            check(f"UI {scale}: width unchanged", panel.width() == theme.px(384),
                  f"({panel.width()})")
            # Opening near the screen bottom keeps the window on the screen.
            screen = QApplication.primaryScreen().availableGeometry()
            panel.set_open_sections([])
            panel.move(screen.left() + 10, screen.bottom() - panel.height() - 2)
            QApplication.processEvents()
            _click_heading(panel, "scanner")
            g = panel.geometry()
            fits = panel.height() <= screen.height()
            check(f"UI {scale}: opening near the bottom keeps the window on screen",
                  g.bottom() <= screen.bottom() if fits else g.top() == screen.top(),
                  f"({g.top()}..{g.bottom()} vs {screen.top()}..{screen.bottom()})")
            panel.close()
            panel.deleteLater()
        finally:
            theme.set_scale(1.0)


def main() -> int:
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    for test in (check_reset, check_unmatched, check_layout, check_sections,
                 check_section_layouts):
        try:
            test()
        except Exception:
            traceback.print_exc()
            check(f"{test.__name__} ran", False)
    print("OK" if FAILS == 0 else f"{FAILS} FAILED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
