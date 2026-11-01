"""Settings → RESET SETTINGS and UNMATCHED READINGS.

    python -m tools.settings_extra_selftest

Drives the real SettingsPanel with real mouse clicks (QTest), off-screen:
the two-click RESET SETTINGS button (arms, reverts, emits once), its error
note, the UNMATCHED READINGS list (count, newest rows, OPEN FOLDER, two-click
CLEAR), and the layout at UI scale 1.0 and 1.5 (no widgets overlap, no text
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

    print("LAYOUT")
    for scale in (1.0, 1.5):
        theme.set_scale(scale)
        try:
            panel = _panel()
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


def main() -> int:
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    for test in (check_reset, check_unmatched, check_layout):
        try:
            test()
        except Exception:
            traceback.print_exc()
            check(f"{test.__name__} ran", False)
    print("OK" if FAILS == 0 else f"{FAILS} FAILED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
