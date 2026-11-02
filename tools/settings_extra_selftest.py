"""Settings → RESET SETTINGS and UNMATCHED READINGS.

    python -m tools.settings_extra_selftest

Drives the real SettingsPanel with real mouse clicks (QTest), off-screen:
the two-click RESET SETTINGS button (arms, reverts, emits once), its error
note, the UNMATCHED READINGS list (count, newest rows, OPEN FOLDER, two-click
CLEAR), the seven collapsible groups (VOICE after LOOK & SOUND; no Support group or donation text; DEBUG last) (heading clicks, summaries, remembered and
forced-open groups, the window fitting itself; DEBUG's Logs rows: DETAILED LOG
switch and summary, OPEN LOG / VIEW LOG / EXPORT DIAGNOSTICS signals, the note),
and the layout at UI scale 1.0
and 1.5 in every open/closed combination checked (no widgets overlap, no text
cut off, armed texts fit), and the scanner preview (whole signature window
scaled to fit, pin outlined cyan, digits green; one-argument calls as before).
VOICE: the four engines with their labels and notes, the voice list per
engine, DOWNLOAD (size, "NN% · got of total MB", CANCEL), SPEED, SAYS and
TEST signals, the summary, and the layout at UI 1.0 and 1.5 with VOICE open
in every download state.
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
os.environ["LOCALAPPDATA"] = _TMP.name     # voice add-ons (app.tts.addons)
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
            panel.set_detailed_log(True)
            panel.set_log_note("Saved to the settings folder: "
                               "SC Assistant diagnostics 2026-11-01 175002.zip")
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
                                          panel.unmatched_open_btn, panel.unmatched_label,
                                          panel.history_btn, panel.history_open_btn,
                                          panel.bad_reads_btn, panel.bad_reads_open_btn,
                                          panel.detailed_log_btn, panel.log_open_btn,
                                          panel.log_view_btn, panel.log_export_btn)
                       if w.width() < w.sizeHint().width()]
                cut += [w.text() for w in panel.findChildren(QLabel)
                        if w.text() in ("SCAN HISTORY", "SAVE BAD READS", "DETAILED LOG")
                        and w.width() < w.sizeHint().width()]
                cut += [v.text() for v, t in panel._unmatched_row_labels
                        if v.isVisible() and v.width() < v.sizeHint().width()]
                cut += [t.text() for v, t in panel._unmatched_row_labels
                        if t.isVisible() and t.width() < t.sizeHint().width()]
                check(f"UI {scale} {tag}: new buttons and rows not cut off", not cut, f"({cut})")
                note = panel.log_note
                check(f"UI {scale} {tag}: the Logs note fits (wrapped, not cut)",
                      note.isVisible() and note.width() <= panel.width()
                      and note.height() >= note.heightForWidth(note.width()),
                      f"({note.width()}x{note.height()}, needs {note.heightForWidth(note.width())})")
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
    check("seven group ids in order (VOICE after LOOK & SOUND, no Support, DEBUG last)",
          sp.SECTION_IDS == ("scanner", "scan_data", "hotkeys", "look", "voice",
                             "update", "debug"),
          f"({sp.SECTION_IDS})")
    panel = _panel()
    got: list[list] = []
    panel.sections_changed.connect(lambda ids: got.append(list(ids)))

    tops = [panel.section_header(s).y() for s in sp.SECTION_IDS]
    check("headings top to bottom in SECTION_IDS order (DEBUG last)",
          tops == sorted(tops) and len(set(tops)) == 7, f"({tops})")
    titles = [panel.section_header(s).title.text()[2:] for s in sp.SECTION_IDS]
    check("headings read SCANNER ... LOOK & SOUND, VOICE, UPDATE & RESET, DEBUG",
          titles == ["SCANNER", "SCAN DATA", "HOTKEYS", "LOOK & SOUND", "VOICE",
                     "UPDATE & RESET", "DEBUG"], f"({titles})")
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
          not panel.region_btn.isVisible() and panel.ui_scale_slider.isVisible()
          and not panel.voice_btn.isVisible())

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
    check("look summary (the voice moved to VOICE)", panel.section_summary("look") == "UI 125%",
          f"({panel.section_summary('look')!r})")
    check("voice summary: off · engine · voice · speed",
          panel.section_summary("voice") == "off · Windows · default voice · 1.0×",
          f"({panel.section_summary('voice')!r})")
    check("update summary: the installed version",
          panel.section_summary("update") == f"v{VERSION} installed",
          f"({panel.section_summary('update')!r})")
    panel._on_update_done("check", "999.0.0", "")
    check("update summary: vX available after CHECK found one",
          panel.section_summary("update") == "v999.0.0 available",
          f"({panel.section_summary('update')!r})")
    check("debug summary: history off · saver off",
          panel.section_summary("debug") == "history off · saver off",
          f"({panel.section_summary('debug')!r})")
    panel.set_history(True)
    check("debug summary follows set_history; switch reads ON",
          panel.section_summary("debug") == "history on · saver off"
          and panel.history_btn.isChecked() and panel.history_btn.text() == "ON",
          f"({panel.section_summary('debug')!r}, {panel.history_btn.text()!r})")
    panel.set_history(False)
    flips: list = []
    panel.history_toggled.connect(lambda on: flips.append(("history", on)))
    panel.bad_reads_toggled.connect(lambda on: flips.append(("saver", on)))
    opens: list = []
    panel.open_history.connect(lambda: opens.append("history"))
    panel.open_bad_reads.connect(lambda: opens.append("bad_reads"))
    panel.set_bad_reads(True)
    panel.set_bad_reads(False)
    check("set_history / set_bad_reads emit nothing", flips == [], f"({flips})")
    panel.bad_reads_btn.click()
    check("SAVE BAD READS click: ON, emits True, summary saver on",
          flips == [("saver", True)] and panel.bad_reads_btn.text() == "ON"
          and panel.section_summary("debug") == "history off · saver on",
          f"({flips}, {panel.section_summary('debug')!r})")
    panel.history_btn.click()
    panel.history_btn.click()
    panel.bad_reads_btn.click()
    check("switch clicks toggle and emit each change",
          flips == [("saver", True), ("history", True), ("history", False), ("saver", False)],
          f"({flips})")
    panel.history_open_btn.click()
    panel.bad_reads_open_btn.click()
    check("OPEN HISTORY and OPEN FOLDER emit their signals",
          opens == ["history", "bad_reads"], f"({opens})")
    # Logs: DETAILED LOG, OPEN LOG, VIEW LOG, EXPORT DIAGNOSTICS.
    logs: list = []
    panel.detailed_log_toggled.connect(lambda on: logs.append(("detailed", on)))
    for name in ("open_log", "view_log", "export_diagnostics"):
        getattr(panel, name).connect(lambda n=name: logs.append(n))
    panel.set_detailed_log(True)
    check("set_detailed_log: switch ON, summary adds log detailed, emits nothing",
          panel.detailed_log_btn.isChecked() and panel.detailed_log_btn.text() == "ON"
          and panel.section_summary("debug") == "history off · saver off · log detailed"
          and logs == [], f"({panel.section_summary('debug')!r}, {logs})")
    panel.detailed_log_btn.click()
    check("DETAILED LOG click: OFF, emits False, summary back",
          logs == [("detailed", False)] and panel.detailed_log_btn.text() == "OFF"
          and panel.section_summary("debug") == "history off · saver off",
          f"({logs}, {panel.section_summary('debug')!r})")
    logs.clear()
    for btn in (panel.log_open_btn, panel.log_view_btn, panel.log_export_btn):
        btn.click()
    check("OPEN LOG, VIEW LOG and EXPORT DIAGNOSTICS emit their signals",
          logs == ["open_log", "view_log", "export_diagnostics"], f"({logs})")
    panel.set_log_note("Saved to the Desktop: SC Assistant diagnostics 2026-11-01 175002.zip")
    check("set_log_note shows the note; \"\" hides it",
          not panel.log_note.isHidden() and "diagnostics" in panel.log_note.text())
    panel.set_log_note("")
    check("set_log_note(\"\") hides it", panel.log_note.isHidden())
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
        ["look", "voice"], ["voice", "update"],
        ["scanner", "look", "update"], ["update", "debug"], list(SECTION_IDS)]
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


FIXTURE = ROOT / "tools" / "fixtures" / "signal_42000_5k2k.png"
PIN = (43, 39, 25, 28)          # the pin in the fixture (x, y, w, h)
DIGITS = (76, 38, 56, 28)       # "42,000" in the fixture
READ_AREA = (74, 40, 86, 29)    # the read area the pin gives on the fixture (tracking)


def _near(c, ref, tol: int = 40) -> bool:
    return all(abs(a - b) <= tol for a, b in ((c.red(), ref.red()), (c.green(), ref.green()),
                                              (c.blue(), ref.blue())))


def _edge_hits(image, rect, color) -> float:
    """Share of points along the rect's edges that carry ``color``."""
    pts = []
    x0, y0 = int(rect.x()) + 1, int(rect.y()) + 1
    x1, y1 = int(rect.x() + rect.width()) - 2, int(rect.y() + rect.height()) - 2
    for i in range(1, 10):
        xs = x0 + (x1 - x0) * i // 10
        ys = y0 + (y1 - y0) * i // 10
        pts += [(xs, y0), (xs, y1), (x0, ys), (x1, ys)]
    good = sum(1 for x, y in pts if any(_near(image.pixelColor(x + dx, y + dy), color)
                                        for dx in (-1, 0, 1) for dy in (-1, 0, 1)))
    return good / len(pts)


def check_preview() -> None:
    import cv2

    from app.ui import theme
    from app.ui.settings_panel import WIDTH

    print("PREVIEW")
    crop = cv2.imread(str(FIXTURE))
    check("fixture loads", crop is not None)
    ch, cw = crop.shape[:2]
    for scale in (1.0, 1.5):
        theme.set_scale(scale)
        try:
            panel = _panel()
            panel.set_open_sections(["scanner"])
            panel.set_debug(True)
            QApplication.processEvents()
            panel.adjustSize()
            QApplication.processEvents()
            box = panel.preview
            panel.set_preview(crop, PIN, DIGITS)
            QApplication.processEvents()
            pix = box.pixmap()
            ok = pix is not None and not pix.isNull()
            check(f"UI {scale}: whole window shown", ok)
            if not ok:
                continue
            fits = pix.width() <= box.width() - 10 and pix.height() <= box.height() - 10
            check(f"UI {scale}: scaled to fit the box", fits,
                  f"({pix.width()}x{pix.height()} in {box.width()}x{box.height()})")
            aspect = abs(pix.width() / pix.height() - cw / ch)
            check(f"UI {scale}: aspect kept", aspect < 0.05,
                  f"({pix.width()}x{pix.height()} vs {cw}x{ch})")
            check(f"UI {scale}: large enough to read (at least the crop's size)",
                  pix.width() >= cw, f"({pix.width()} px wide)")
            img = pix.toImage()
            rects = panel.preview_rects
            sx = pix.width() / cw
            pin_r, dig_r = rects.get("pin"), rects.get("digits")
            check(f"UI {scale}: outline rects follow the scale",
                  pin_r is not None and dig_r is not None
                  and abs(pin_r.x() - PIN[0] * sx) < 1 and abs(dig_r.width() - DIGITS[2] * sx) < 1,
                  f"({pin_r}, {dig_r})")
            if pin_r is not None and dig_r is not None:
                cyan = _edge_hits(img, pin_r, theme.ACCENT)
                green = _edge_hits(img, dig_r, theme.GOOD)
                check(f"UI {scale}: cyan outline on the pin", cyan >= 0.9, f"({cyan:.0%})")
                check(f"UI {scale}: green outline on the digits", green >= 0.9, f"({green:.0%})")
                check(f"UI {scale}: pin not drawn green, digits not cyan",
                      _edge_hits(img, pin_r, theme.GOOD) < 0.2
                      and _edge_hits(img, dig_r, theme.ACCENT) < 0.2)
            # What the user sees: the green box from the reader's own trim of
            # the read area, then the rendered preview grabbed as on screen.
            from app.ocr import SignatureOCR

            ax, ay, aw, ah = READ_AREA
            gx, gy, gw, gh = SignatureOCR.digit_box(
                cv2.cvtColor(crop[ay:ay + ah, ax:ax + aw], cv2.COLOR_BGR2GRAY))
            panel.set_preview(crop, PIN, (ax + gx, ay + gy, gw, gh))
            QApplication.processEvents()
            shot = box.grab().toImage()
            dpr = shot.devicePixelRatio() or 1.0
            # The drawn green box, in the grabbed (device) pixels.
            pix = box.pixmap()
            pr = pix.devicePixelRatio() or 1.0
            pw, ph = pix.width() / pr, pix.height() / pr
            left, top = (box.width() - pw) / 2, (box.height() - ph) / 2
            r = panel.preview_rects.get("digits")
            green_pts = []
            if r is not None:
                gx0, gy0 = int(round((left + r.x()) * dpr)), int(round((top + r.y()) * dpr))
                gx1 = int(round((left + r.x() + r.width()) * dpr)) - 1
                gy1 = int(round((top + r.y() + r.height()) * dpr)) - 1
                green_pts = [(gx0, gy0)]
                # The digits as drawn: the brightest pixels inside the box
                # (luminance at least 80 % of the brightest), outline excluded.
                inset = int(3 * dpr)
                lum = {}
                for y in range(gy0 + inset, gy1 - inset + 1):
                    for x in range(gx0 + inset, gx1 - inset + 1):
                        c = shot.pixelColor(x, y)
                        lum[x, y] = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
                peak = max(lum.values()) if lum else 0
                ink = [xy for xy, v in lum.items() if v >= 0.8 * peak]
                ix = (min(p[0] for p in ink) + max(p[0] for p in ink)) / 2
                iy = (min(p[1] for p in ink) + max(p[1] for p in ink)) / 2
                bx, by = (gx0 + gx1) / 2, (gy0 + gy1) / 2
                tol = 2.5 * dpr
                check(f"UI {scale}: in the preview the digits sit centred in the green box",
                      abs(ix - bx) <= tol and abs(iy - by) <= tol,
                      f"(ink centre {ix:.1f},{iy:.1f}; box centre {bx:.1f},{by:.1f})")
                check(f"UI {scale}: the green outline is drawn there",
                      _edge_hits(box.pixmap().toImage(), r, theme.GOOD) >= 0.9)
            else:
                check(f"UI {scale}: in the preview the digits sit centred in the green box", False,
                      "(no digits rect drawn)")
            # The picture is centred in the preview box: the green box lands
            # where a centred picture puts it.
            want_x = (left + (ax + gx) * pw / cw) * dpr
            want_y = (top + (ay + gy) * ph / ch) * dpr
            check(f"UI {scale}: the window picture is centred in the preview box",
                  bool(green_pts) and abs(gx0 - want_x) <= 2 * dpr and abs(gy0 - want_y) <= 2 * dpr,
                  f"(green box at {gx0 if green_pts else None},{gy0 if green_pts else None}; "
                  f"centred picture puts it at {want_x:.1f},{want_y:.1f})")

            overlaps, outside = _overlaps(panel)
            check(f"UI {scale}: Scanner open with the preview: no overlap, nothing outside",
                  not overlaps and not outside, f"({overlaps[:3]}, {outside[:3]})")
            check(f"UI {scale}: Settings width unchanged", panel.width() == theme.px(WIDTH),
                  f"({panel.width()})")
            if scale == 1.0:
                out = os.environ.get("CA_PREVIEW_SHOT")
                if out:
                    panel.grab().save(out)
                    print(f"    saved {out}")

            # One-argument calls (digits crop as today): no outlines, fits.
            digits_only = crop[DIGITS[1]:DIGITS[1] + DIGITS[3], DIGITS[0]:DIGITS[0] + DIGITS[2]].copy()
            panel.set_preview(digits_only)
            QApplication.processEvents()
            pix = box.pixmap()
            check(f"UI {scale}: one-argument call still shows the crop, no outlines",
                  pix is not None and not pix.isNull() and panel.preview_rects == {}
                  and pix.height() <= box.height() - 10 and pix.width() <= box.width() - 10,
                  f"({panel.preview_rects})")
            panel.set_preview(crop, PIN)
            check(f"UI {scale}: pin only -> only the cyan outline",
                  list(panel.preview_rects) == ["pin"], f"({list(panel.preview_rects)})")
            panel.set_debug(False)
            QApplication.processEvents()
            before = box.pixmap().cacheKey()
            panel.set_preview(crop, PIN, DIGITS)
            check(f"UI {scale}: hidden preview is not redrawn", box.pixmap().cacheKey() == before)
            panel.close()
            panel.deleteLater()
        finally:
            theme.set_scale(1.0)


VOICES = {
    "windows": [("winrt:Zira", "Microsoft Zira", "winrt · en-US"),
                ("sapi:David", "Microsoft David Desktop", "sapi · en-US")],
    "piper": [("en_US-lessac-medium", "Lessac", "US · CC-BY 4.0 · 60 MB"),
              ("en_GB-alan-low", "Alan", "UK · CC0 · 20 MB")],
}


def check_voice() -> None:
    """The VOICE group on its own: engines, voices, DOWNLOAD, SPEED, SAYS,
    TEST, the note and the summary (main is faked by the test)."""
    from app import tts
    from app.tts import phrases
    from app.ui import settings_panel as sp

    print("VOICE")
    panel = _panel()
    panel.set_open_sections(["voice"])
    QApplication.processEvents()
    seen: list = []
    panel.voice_engine_changed.connect(lambda e: seen.append(("engine", e)))
    panel.voice_choice_changed.connect(lambda v: seen.append(("voice", v)))
    panel.voice_speed_changed.connect(lambda s: seen.append(("speed", s)))
    panel.voice_style_changed.connect(lambda s: seen.append(("style", s)))
    panel.voice_download_requested.connect(lambda: seen.append("download"))
    panel.voice_download_cancelled.connect(lambda: seen.append("cancel"))
    panel.voice_test_requested.connect(lambda: seen.append("test"))

    box = panel.engine_box
    engines = [(box.itemData(i), box.itemText(i)) for i in range(box.count())]
    want = [("windows", "Windows voices (built in, offline)"),
            ("piper", "Piper (offline, natural · add-on, GPL-3.0)"),
            ("kokoro", "Kokoro (offline, most natural · add-on, GPL-3.0, uses more CPU)"),
            ("edge", "Microsoft online voices (online: sends the phrase to Microsoft)")]
    check("ENGINE lists the four engines with their labels, in order",
          engines == want and list(tts.ENGINE_IDS) == [e for e, _ in want], f"({engines})")
    check("the voice switch and VOLUME moved into VOICE",
          panel.voice_btn.isVisible() and panel.volume_slider.isVisible())
    panel.set_open_sections(["look"])
    QApplication.processEvents()
    check("LOOK & SOUND no longer holds the voice switch or VOLUME",
          not panel.voice_btn.isVisible() and not panel.volume_slider.isVisible()
          and panel.ui_scale_slider.isVisible())
    panel.set_open_sections(["voice"])
    QApplication.processEvents()

    # Voices change with the engine (main answers the engine signal).
    panel.voice_engine_changed.connect(
        lambda e: panel.set_voice_choices(VOICES.get(e, []), ""))
    panel.set_voice_choices(VOICES["windows"], "sapi:David")
    check("set_voice_choices fills VOICE and shows the current one, emits nothing",
          panel.voice_box.count() == 2 and panel.voice_id == "sapi:David" and seen == []
          and panel.voice_box.currentText() == "Microsoft David Desktop · sapi · en-US",
          f"({panel.voice_id!r}, {seen})")
    box.setCurrentIndex(1)
    box.activated.emit(1)
    QApplication.processEvents()
    piper_ids = [panel.voice_box.itemData(i) for i in range(panel.voice_box.count())]
    check("choosing Piper emits its id and the VOICE list becomes Piper's voices",
          seen == [("engine", "piper")] and piper_ids == ["en_US-lessac-medium", "en_GB-alan-low"]
          and panel.voice_id == "en_US-lessac-medium", f"({seen}, {piper_ids})")
    check("the note says GPL-3.0 add-on for Piper",
          "GPL-3.0" in panel.voice_note.text() and panel.voice_note.isVisible(),
          f"({panel.voice_note.text()!r})")
    panel.voice_box.setCurrentIndex(1)
    panel.voice_box.activated.emit(1)
    check("choosing a voice emits its id", seen[-1] == ("voice", "en_GB-alan-low"), f"({seen})")
    for engine_id, words in (("kokoro", "GPL-3.0"), ("edge", "Microsoft")):
        panel.set_voice_engine(engine_id)
        check(f"{engine_id} note: {words}", words in panel.voice_note.text(),
              f"({panel.voice_note.text()!r})")
    panel.set_voice_engines([("edge", "", "Engine's own note about Microsoft")])
    check("set_voice_engines takes the engine's own note", panel.voice_note.text()
          == "Engine's own note about Microsoft", f"({panel.voice_note.text()!r})")
    panel.set_voice_engine("windows")
    check("Windows: no licence note, the note line hidden", panel.voice_note.isHidden())
    panel.set_voice_engine("no-such-engine")
    check("an unknown engine id shows Windows", panel.voice_engine == "windows")
    panel.set_voice_engine("piper")
    panel.set_voice_choices(VOICES["piper"], "en_GB-alan-low")

    # DOWNLOAD: size, progress, CANCEL.
    seen.clear()
    check("no download needed: no DOWNLOAD row", panel.voice_download_row.isHidden())
    panel.set_voice_download(63 * (1 << 20))
    QApplication.processEvents()
    check("DOWNLOAD row shows the size", panel.voice_download_row.isVisible()
          and panel.voice_download_label.text() == "Needs a 63 MB download"
          and panel.voice_download_btn.text() == "DOWNLOAD" and seen == [],
          f"({panel.voice_download_label.text()!r})")
    check("TEST waits for the download", not panel.voice_test_btn.isEnabled())
    _click(panel.voice_download_btn)
    check("DOWNLOAD click emits once and turns into CANCEL at 0%",
          seen == ["download"] and panel.voice_download_btn.text() == "CANCEL"
          and panel.voice_download_label.text() == "0% · 0.0 of 63 MB",
          f"({seen}, {panel.voice_download_label.text()!r})")
    panel.set_voice_progress(26 * (1 << 20) + 5, 63 * (1 << 20))
    check("progress reads 'NN% · got of total MB'",
          panel.voice_download_label.text() == "41% · 26 of 63 MB",
          f"({panel.voice_download_label.text()!r})")
    check("summary says downloading NN%",
          panel.section_summary("voice") == "Piper · Alan · 1.0× · downloading 41%",
          f"({panel.section_summary('voice')!r})")
    check("small files show one decimal",
          sp.voice_download_text(300_000, 900_000) == "33% · 0.3 of 0.9 MB"
          and sp.voice_download_text(5 << 20, 0) == "5.0 MB",
          f"({sp.voice_download_text(300_000, 900_000)!r})")
    _click(panel.voice_download_btn)
    check("CANCEL click emits cancel once (button waits for main)",
          seen == ["download", "cancel"] and not panel.voice_download_btn.isEnabled()
          and panel.voice_download_label.text() == "Cancelling…", f"({seen})")
    _click(panel.voice_download_btn)
    check("a second CANCEL click while cancelling does nothing", seen == ["download", "cancel"])
    panel.set_voice_download(63 * (1 << 20))
    check("cancelled: DOWNLOAD back with the size",
          panel.voice_download_btn.text() == "DOWNLOAD" and panel.voice_download_btn.isEnabled()
          and not panel.voice_downloading)
    panel.set_voice_download(0)
    QApplication.processEvents()
    check("done: the DOWNLOAD row hides and TEST is back",
          panel.voice_download_row.isHidden() and panel.voice_test_btn.isEnabled())

    # SPEED, SAYS, TEST.
    seen.clear()
    panel.speed_slider.setValue(13)
    check("SPEED emits 1.3 and shows 1.3×",
          seen == [("speed", 1.3)] and panel.speed_label.text() == "1.3×", f"({seen})")
    check("SPEED range 0.5-2.0 in 0.1 steps",
          (panel.speed_slider.minimum(), panel.speed_slider.maximum(),
           panel.speed_slider.singleStep()) == (5, 20, 1))
    panel.set_voice_speed(0.2)
    panel.set_voice_speed(1.75)
    check("set_voice_speed clamps and rounds, emits nothing",
          panel.voice_speed == 1.8 and seen == [("speed", 1.3)], f"({panel.voice_speed})")
    styles = [(panel.style_box.itemData(i), panel.style_box.itemText(i))
              for i in range(panel.style_box.count())]
    check("SAYS lists the three styles with examples",
          styles == [(s, phrases.STYLE_LABELS[s]) for s in phrases.STYLES]
          and [s for s, _ in styles] == ["count_after", "count_before", "with_signature"],
          f"({styles})")
    panel.style_box.setCurrentIndex(2)
    panel.style_box.activated.emit(2)
    check("SAYS emits the style id", seen[-1] == ("style", "with_signature"), f"({seen})")
    panel.set_voice_style("count_before")
    check("set_voice_style shows it", panel.voice_style == "count_before")
    _click(panel.voice_test_btn)
    check("TEST emits voice_test_requested", seen[-1] == "test", f"({seen})")
    panel.set_voice_note("Microsoft voice failed: timeout; using a Windows voice")
    check("set_voice_note adds the status under the licence note",
          panel.voice_note.text().endswith("using a Windows voice")
          and "GPL-3.0" in panel.voice_note.text())

    # Summary.
    panel.set_voice(True)
    check("voice summary: engine · voice · speed",
          panel.section_summary("voice") == "Piper · Alan · 1.8×",
          f"({panel.section_summary('voice')!r})")
    panel.set_voice_engine("edge")
    panel.set_voice_choices([("en-US-AriaNeural", "Aria", "US, female")], "")
    check("summary follows the engine and voice",
          panel.section_summary("voice") == "Microsoft online · Aria · 1.8×",
          f"({panel.section_summary('voice')!r})")
    panel.close()
    panel.deleteLater()


def check_voice_layout() -> None:
    """VOICE open at UI 1.0 and 1.5, with and without the download row, a
    long note and the longest names: nothing overlaps, sticks out or is cut."""
    from app.ui import theme

    print("VOICE LAYOUT")
    for scale in (1.0, 1.5):
        theme.set_scale(scale)
        try:
            panel = _panel()
            panel.set_open_sections(["look", "voice"])
            panel.set_voice_engine("kokoro")
            panel.set_voice_choices([("af_heart", "Heart, a very long voice name for the test",
                                      "American English, female, grade A")], "af_heart")
            panel.set_voice_note("Download failed: the connection to huggingface.co timed out "
                                 "after 30 seconds")
            bad = []
            for state in ("none", "needed", "progress"):
                if state == "none":
                    panel.set_voice_download(0)
                elif state == "needed":
                    panel.set_voice_download(330 << 20)
                else:
                    panel.set_voice_progress(123 << 20, 330 << 20)
                QApplication.processEvents()
                panel.adjustSize()
                QApplication.processEvents()
                overlaps, outside = _overlaps(panel)
                if overlaps or outside:
                    bad.append((state, overlaps[:3], outside[:3]))
                cut = [w.text() for w in (panel.voice_btn, panel.voice_test_btn,
                                          panel.voice_download_btn, panel.voice_download_label)
                       if w.isVisible() and w.width() < w.sizeHint().width()]
                # Fixed-width names and values (like UI SCALE): the offscreen
                # platform has no real fonts, so these are measured only on a
                # real screen (QT_QPA_PLATFORM=windows).
                if QApplication.platformName() != "offscreen":
                    cut += [w.text() for w in panel.findChildren(QLabel)
                            if w.text() in ("ENGINE", "VOICE", "SPEED", "SAYS")
                            and w.width() < w.sizeHint().width()]
                    cut += [w.text() for w in (panel.speed_label, panel.volume_label)
                            if w.width() < w.sizeHint().width()]
                note = panel.voice_note
                if note.height() < note.heightForWidth(note.width()):
                    cut.append("note")
                if cut:
                    bad.append((state, "cut", cut))
            check(f"UI {scale}: VOICE open (no download, DOWNLOAD, progress): "
                  "no overlap, nothing outside or cut", not bad, f"({bad[:3]})")
            check(f"UI {scale}: VOICE keeps the window width", panel.width() == theme.px(384),
                  f"({panel.width()})")
            popup = panel.engine_box.view()
            check(f"UI {scale}: the ENGINE list opens wide enough for whole labels",
                  popup.minimumWidth() >= popup.sizeHintForColumn(0), f"({popup.minimumWidth()})")
            panel.close()
            panel.deleteLater()
        finally:
            theme.set_scale(1.0)


def main() -> int:
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    for test in (check_reset, check_unmatched, check_layout, check_sections,
                 check_section_layouts, check_preview, check_voice, check_voice_layout):
        try:
            test()
        except Exception:
            traceback.print_exc()
            check(f"{test.__name__} ran", False)
    print("OK" if FAILS == 0 else f"{FAILS} FAILED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
