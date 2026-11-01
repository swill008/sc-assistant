"""Overlay widget checks: SHOW BOX tracking marks, the scanner panel's
tracking chip and pin, the DRAW REGION picker conveniences and the nav bar's
settings attention.

    python -m tools.overlay_selftest            # PASS/FAIL lines, exit code = failures
    python tools/overlay_selftest.py --root DIR # run against another copy of app/

Needs a desktop session. Every window is made invisible (opacity 0) before it
is shown and is placed on a secondary monitor, never on the main (game)
monitor. The picker is driven through its ``cursor_pos`` hook, so the real
mouse never moves. APPDATA points at a temporary folder.
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
if "--root" in sys.argv:
    ROOT = Path(sys.argv[sys.argv.index("--root") + 1]).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="overlay_selftest_")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import SIGNAL, QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FAILURES = 0


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def check(label: str, ok: bool, detail: str = "") -> bool:
    global FAILURES
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}", flush=True)
    if not ok:
        FAILURES += 1
    return ok


def guarded(fn):
    """A check group that crashes (e.g. an API missing in old code) is a FAIL."""
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            check(f"{fn.__name__} ran without errors", False,
                  f"({type(exc).__name__}: {exc})")
            traceback.print_exc(limit=3)
            return None
    return run


def secondary_screens():
    primary = QGuiApplication.primaryScreen()
    return [s for s in QGuiApplication.screens() if s is not primary]


def _close_colour(a: QColor, b: QColor, tol: int = 40) -> bool:
    return (abs(a.red() - b.red()) <= tol and abs(a.green() - b.green()) <= tol
            and abs(a.blue() - b.blue()) <= tol)


def _has_colour(image, rect: QRect, colour: QColor, tol: int = 40) -> bool:
    rect = rect.intersected(image.rect())
    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            c = image.pixelColor(x, y)
            if c.alpha() > 120 and _close_colour(c, colour, tol):
                return True
    return False


class PlaceCounter:
    """Counts win32.place_physical calls and Qt geometry calls on a widget."""

    def __init__(self, win32_module, widget):
        self.win32 = win32_module
        self.widget = widget
        self.places = 0
        self.geometry = 0
        self._orig = win32_module.place_physical

        def place(target, rect):
            if target is widget:
                self.places += 1
            return self._orig(target, rect)

        def wrap(name):
            orig = getattr(widget, name)

            def call(*a, **k):
                self.geometry += 1
                return orig(*a, **k)
            setattr(widget, name, call)

        win32_module.place_physical = place
        for name in ("setGeometry", "setScreen"):
            wrap(name)

    def reset(self):
        self.places = 0
        self.geometry = 0

    def restore(self):
        self.win32.place_physical = self._orig
        for name in ("setGeometry", "setScreen"):
            self.widget.__dict__.pop(name, None)


def _native(widget):
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = wintypes.HWND(int(widget.winId()))
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    rect = {"left": r.left, "top": r.top, "width": r.right - r.left, "height": r.bottom - r.top}
    ex = user32.GetWindowLongW(hwnd, -20)
    aff = wintypes.DWORD()
    user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(aff))
    return rect, ex, aff.value


# ---------------------------------------------------------------------------
# SHOW BOX marks
# ---------------------------------------------------------------------------
@guarded
def check_outline_marks(screen) -> None:
    from app import display
    from app.ui import region_outline, theme
    from app.ui.region_outline import RegionOutline, outline_rect

    name = screen.name()
    mon = display.physical_rect(screen)
    dpr = float(screen.devicePixelRatio())
    cx, cy = mon["left"] + mon["width"] // 2, mon["top"] + mon["height"] // 2
    digits = {"left": cx - 61, "top": cy - 17, "width": 123, "height": 35}
    pin = {"left": cx - 61 - 47, "top": cy - 15, "width": 31, "height": 31}

    outline = RegionOutline()
    outline.setWindowOpacity(0.0)        # before show: never a visible frame
    counter = PlaceCounter(region_outline.win32, outline)
    try:
        outline.show_marks(digits, pin, "locked")
        _pump(0.5)
        got, ex, aff = _native(outline)
        _pump(0.5)
        later, _, _ = _native(outline)
        want = outline.target_rect
        check(f"{name}: marks window placed exactly and stays", got == want and later == got,
              f"(want {want}, got {got}, later {later})")
        od, op = outline_rect(digits), outline_rect(pin)
        left = min(od["left"], op["left"])
        top = min(od["top"], op["top"])
        right = max(od["left"] + od["width"], op["left"] + op["width"])
        bottom = max(od["top"] + od["height"], op["top"] + op["height"])
        strip_max = round(40 * dpr)
        check(f"{name}: window covers both outlines with the label strip above",
              left - int(dpr) - 2 <= got["left"] <= left
              and bottom <= got["top"] + got["height"] <= bottom + int(dpr) + 2
              and got["left"] + got["width"] >= right
              and top - strip_max <= got["top"] < top,
              f"(outlines {left},{top}-{right},{bottom}; window {got})")
        check(f"{name}: marks window click-through", bool(ex & 0x20), f"(exstyle {ex:#x})")
        check(f"{name}: marks window excluded from capture", aff in (0x11, 0x1),
              f"(affinity {aff:#x})")
        check(f"{name}: properties state/label/marks",
              outline.state == "locked" and outline.label == theme.TRACK_TEXT["locked"]
              and outline.marks == {"digits": digits, "pin": pin},
              f"({outline.state!r}, {outline.label!r}, {outline.marks})")

        # Colour per state, read back from the rendered window.
        for state in theme.TRACK_STATES:
            outline.show_marks(digits, pin, state)
            _pump(0.1)
            got = outline.target_rect
            image = outline.grab().toImage()
            sx = image.width() / max(1, got["width"])
            sy = image.height() / max(1, got["height"])
            # Left edge of the digits outline, half way down.
            lx = round((od["left"] + 1 - got["left"]) * sx)
            ly = round((od["top"] + od["height"] // 2 - got["top"]) * sy)
            line_ok = _has_colour(image, QRect(lx - 1, ly - 1, 3, 3), theme.TRACK_COLOR[state], 30)
            strip = QRect(0, 0, image.width(), round((top - got["top"]) * sy))
            label_ok = _has_colour(image, strip, theme.TRACK_COLOR[state], 60)
            # Inside the digits must stay clear (never over the box).
            ix = round((digits["left"] + digits["width"] // 2 - got["left"]) * sx)
            iy = round((digits["top"] + digits["height"] // 2 - got["top"]) * sy)
            clear_ok = image.pixelColor(ix, iy).alpha() == 0
            check(f"{name}: {state} outline, label colour, box clear",
                  line_ok and label_ok and clear_ok and outline.label == theme.TRACK_TEXT[state],
                  f"(line {line_ok}, label {label_ok}, clear {clear_ok})")

        outline.show_marks(digits, pin, "locked", "TRACKING ✓  42,000")
        _pump(0.4)
        check(f"{name}: custom label", outline.label == "TRACKING ✓  42,000")

        # Repeat call: no-op.
        counter.reset()
        outline.show_marks(digits, pin, "locked", "TRACKING ✓  42,000")
        _pump(0.3)
        check(f"{name}: repeat show_marks is a no-op",
              counter.places == 0 and counter.geometry == 0,
              f"({counter.places} placements, {counter.geometry} Qt geometry calls)")

        # Same-monitor move: exactly one placement, no Qt geometry, no timers.
        for step in range(3):
            d2 = dict(digits, left=digits["left"] + 37 * (step + 1), top=digits["top"] + 11)
            p2 = dict(pin, left=pin["left"] + 37 * (step + 1), top=pin["top"] + 11)
            counter.reset()
            outline.show_marks(d2, p2, "searching")
            _pump(0.4)
            now, _, _ = _native(outline)
            check(f"{name}: same-monitor move {step + 1}: one placement, exact",
                  counter.places == 1 and counter.geometry == 0 and now == outline.target_rect,
                  f"({counter.places} placements, {counter.geometry} Qt geometry calls, "
                  f"want {outline.target_rect}, got {now})")

        # Pin dropped: outline only around the digits.
        counter.reset()
        outline.show_marks(digits, None, "searching")
        _pump(0.4)
        now, _, _ = _native(outline)
        check(f"{name}: digits-only marks exact", now == outline.target_rect
              and od["left"] - 4 <= now["left"] <= od["left"] and outline.marks["pin"] is None,
              f"(want {outline.target_rect}, got {now})")

        # keep_on_top with an exact rect does not re-place.
        counter.reset()
        outline.keep_on_top()
        check(f"{name}: keep_on_top leaves an exact window alone", counter.places == 0,
              f"({counter.places} placements)")

        # Back to the plain box.
        outline.show_region(digits)
        _pump(0.4)
        now, _, _ = _native(outline)
        check(f"{name}: show_region still exact after marks",
              now == outline_rect(digits) and outline.marks is None, f"(got {now})")

        # Hide, then show again: full placement still exact.
        outline.hide()
        outline.show_marks(digits, pin, "fixed")
        _pump(0.5)
        now, _, _ = _native(outline)
        check(f"{name}: show after hide exact", now == outline.target_rect and outline.isVisible(),
              f"(want {outline.target_rect}, got {now})")
    finally:
        counter.restore()
        outline.close()
        outline.deleteLater()


@guarded
def check_outline_region_move(screen) -> None:
    """show_region (old API too): a same-monitor move is one placement."""
    from app import display
    from app.ui import region_outline
    from app.ui.region_outline import RegionOutline, outline_rect

    name = screen.name()
    mon = display.physical_rect(screen)
    cx, cy = mon["left"] + mon["width"] // 2, mon["top"] + mon["height"] // 2
    box = {"left": cx - 41, "top": cy - 19, "width": 83, "height": 39}
    outline = RegionOutline()
    outline.setWindowOpacity(0.0)
    counter = PlaceCounter(region_outline.win32, outline)
    try:
        outline.show_region(box)
        _pump(0.5)
        worst = (0, 0)
        exact = True
        for step in range(4):
            moved = dict(box, left=box["left"] + 13 * (step + 1), top=box["top"] + 7 * (step + 1))
            counter.reset()
            outline.show_region(moved)
            _pump(0.4)
            now, _, _ = _native(outline)
            exact &= now == outline_rect(moved)
            worst = max(worst, (counter.places, counter.geometry))
        check(f"{name}: show_region same-monitor moves: one placement each, exact",
              worst == (1, 0) and exact,
              f"(worst {worst[0]} placements / {worst[1]} Qt geometry calls per move, exact {exact})")
    finally:
        counter.restore()
        outline.close()
        outline.deleteLater()


@guarded
def check_outline_enforce_bounded(screen) -> None:
    """Qt fighting the placement forever must not cause endless re-placing."""
    from app import display
    from app.ui import region_outline
    from app.ui.region_outline import RegionOutline

    mon = display.physical_rect(screen)
    box = {"left": mon["left"] + 100, "top": mon["top"] + 100, "width": 80, "height": 40}
    outline = RegionOutline()
    outline.setWindowOpacity(0.0)
    outline.show_region(box)
    _pump(0.4)
    counter = PlaceCounter(region_outline.win32, outline)
    real = region_outline.win32.physical_window_rect
    region_outline.win32.physical_window_rect = lambda w: {"left": -1, "top": -1, "width": 1, "height": 1}
    try:
        for _ in range(12):
            outline._enforce()
            QApplication.processEvents()
        _pump(0.3)
        check(f"{screen.name()}: _enforce bounded when Qt keeps moving the window",
              counter.places <= 3, f"({counter.places} re-placements for 12 mismatches)")
    finally:
        region_outline.win32.physical_window_rect = real
        counter.restore()
        outline.close()
        outline.deleteLater()


# ---------------------------------------------------------------------------
# Scanner panel
# ---------------------------------------------------------------------------
def _on_secondary(widget, screen) -> None:
    widget.setWindowOpacity(0.0)        # before show
    geo = screen.availableGeometry()
    widget.move(geo.left() + 40, geo.top() + 40)
    widget.show()
    QApplication.processEvents()


@guarded
def check_panel(screen) -> None:
    from PySide6.QtWidgets import QLabel, QPushButton

    from app.ui import theme
    from app.ui.pin_button import PinButton

    for scale in (1.0, 1.5):
        theme.set_scale(scale)
        try:
            import importlib

            import app.ui.mining_panel as mp
            importlib.reload(mp)
            panel = mp.MiningPanel()
            _on_secondary(panel, screen)
            panel.set_state("reading")
            labels = [w for w in panel.findChildren(QLabel)]
            title = next(w for w in labels if w.text() == "MINING SCANNER")
            state_label = next(w for w in labels if w.text() == "READING")
            pin = next(iter(panel.findChildren(PinButton)), None)
            close = next(w for w in panel.findChildren(QPushButton) if w.text() == "✕")

            for state in (None, *theme.TRACK_STATES, None):
                panel.set_track_state(state)
                QApplication.processEvents()
                chip = next((w for w in panel.findChildren(QLabel)
                             if w not in (title, state_label) and w.isVisible()), None)
                if state is None:
                    check(f"UI {scale}: chip hidden for None",
                          chip is None and panel.track_state is None)
                    continue
                ok_text = chip is not None and chip.text() == theme.TRACK_TEXT[state]
                img = chip.grab().toImage() if chip is not None else None
                ok_col = img is not None and _has_colour(img, img.rect(), theme.TRACK_COLOR[state], 25)
                check(f"UI {scale}: chip {state}: text and colour",
                      ok_text and ok_col and panel.track_state == state,
                      f"(text {chip.text() if chip else None!r}, colour {ok_col})")
                items = [title, chip, state_label] + ([pin] if pin else []) + [close]
                rects = [w.geometry() for w in items]
                overlap = any(rects[i].intersects(rects[j])
                              for i in range(len(rects)) for j in range(i + 1, len(rects)))
                squeezed = [w.text() for w in (title, chip, state_label)
                            if w.width() < w.sizeHint().width()]
                check(f"UI {scale}: header with {theme.TRACK_TEXT[state]}: no overlap, no clipped text",
                      not overlap and not squeezed,
                      f"(overlap {overlap}, squeezed {squeezed})")

            check(f"UI {scale}: pin button just left of ✕",
                  pin is not None and pin.geometry().right() < close.geometry().left()
                  and close.geometry().left() - pin.geometry().right() <= theme.px(12),
                  f"(pin {pin.geometry().getRect() if pin else None}, close {close.geometry().getRect()})")
            got: list[bool] = []
            panel.pin_toggled.connect(got.append)
            QTest.mouseClick(pin, Qt.MouseButton.LeftButton)
            QApplication.processEvents()
            check(f"UI {scale}: pin click emits pin_toggled(True)", got == [True] and panel.pinned,
                  f"(signals {got}, pinned {panel.pinned})")
            panel.set_pinned(False)
            check(f"UI {scale}: set_pinned(False) silent", got == [True] and not panel.pinned)

            # Drag strip follows the UI scale (40 design px).
            y = int(theme.px(40) - 2)
            QTest.mousePress(panel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             QPoint(panel.width() // 2, y))
            dragging = panel._drag_from is not None
            QTest.mouseRelease(panel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                               QPoint(panel.width() // 2, y))
            check(f"UI {scale}: header drag strip is theme.px(40) tall", dragging, f"(press at y={y})")
            panel.close()
            panel.deleteLater()
        finally:
            theme.set_scale(1.0)


@guarded
def check_panel_ground(screen) -> None:
    """Ground readings list the real candidate minerals (hand mining / ROC)."""
    from PySide6.QtGui import QFontMetrics

    from app.mining import MiningData
    from app.ui import theme
    from app.ui.mining_panel import MiningPanel

    data = MiningData(source="bundled")
    panel = MiningPanel()
    _on_secondary(panel, screen)
    for value, kind, word, pool in ((3000, "fps", "HAND MINING", data.fps_minerals),
                                    (4000, "roc", "ROC", data.roc_minerals)):
        matches = [m for m in data.lookup(value) if m.kind == kind]
        if not check(f"{word}: lookup({value:,}) gives a {kind} match", bool(matches)):
            continue
        panel.set_scan(value, 0.9, "stable", matches)
        QApplication.processEvents()
        detail = panel.verdict._detail()
        image = panel.verdict.grab().toImage()
        want = f"{word} · " + " / ".join(matches[0].minerals)
        tip = panel.verdict.toolTip()
        check(f"{word}: detail lists the {len(matches[0].minerals)} candidate minerals",
              detail == want and len(matches[0].minerals) == len(pool) > 0
              and all(m in tip for m in pool) and not image.isNull(),
              f"(detail {detail[:60]!r}..., tooltip {len(tip)} chars)")
        p = panel.verdict
        f = theme.pfont(8)
        shown = QFontMetrics(f).elidedText(detail, Qt.TextElideMode.ElideRight,
                                           round(p.width() / theme.scale()))
        check(f"{word}: long list elided to the panel width",
              shown.endswith("…") or shown == detail, f"(shown {shown!r})")
    # Ship ores keep their old detail line.
    value = data_ship_value(data)
    ship = [m for m in data.lookup(value) if m.kind == "ship"] if value else []
    if ship:
        panel.set_scan(ship[0].target, 0.9, "stable", ship)
        QApplication.processEvents()
        check("ship ore detail unchanged (no HAND MINING/ROC prefix)",
              not panel.verdict._detail().startswith(("HAND MINING", "ROC ·"))
              and panel.verdict.toolTip() == "", f"({panel.verdict._detail()!r})")
    panel.close()
    panel.deleteLater()


def data_ship_value(data) -> int | None:
    for value in range(1500, 20000, 5):
        if any(m.kind == "ship" and m.exact for m in data.lookup(value)):
            return value
    return None


# ---------------------------------------------------------------------------
# DRAW REGION picker
# ---------------------------------------------------------------------------
def _picker(screen, cursor, picked, cancelled):
    from app.ui.region_selector import RegionSelector

    picker = RegionSelector("selftest", cursor_pos=lambda: cursor[0], screens=[screen])
    picker.selected.connect(picked.append)
    picker.cancelled.connect(lambda: cancelled.append(True))
    for w in picker.windows:
        w.setWindowOpacity(0.0)        # before show: never a visible frame
    picker.show()
    QApplication.processEvents()
    return picker, picker.windows[0]


@guarded
def check_picker(screen) -> None:
    from app import display

    name = screen.name()
    mon = display.physical_rect(screen)
    cursor = [(mon["left"] + 50, mon["top"] + 50)]
    picked: list[dict] = []
    cancelled: list[bool] = []

    # Right-click cancels.
    picker, w = _picker(screen, cursor, picked, cancelled)
    QTest.mouseClick(w, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, QPoint(30, 30))
    QApplication.processEvents()
    check(f"{name}: right-click cancels", cancelled == [True] and not picked and not picker.windows)
    picker.close()

    # Ctrl-release keeps the box; arrows nudge in physical pixels; Enter confirms.
    x0, y0 = mon["left"] + mon["width"] // 2 - 150, mon["top"] + mon["height"] // 2 - 40
    picked.clear()
    cancelled.clear()
    picker, w = _picker(screen, cursor, picked, cancelled)
    cursor[0] = (x0, y0)
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 20))
    cursor[0] = (x0 + 300, y0 + 80)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(80, 50))
    QApplication.processEvents()
    kept = not picked and bool(picker.windows) and getattr(picker, "pending", None) == \
        {"left": x0, "top": y0, "width": 300, "height": 80}
    check(f"{name}: Ctrl-release keeps the box for nudging", kept,
          f"(picked {picked}, pending {getattr(picker, 'pending', None)})")
    if picker.windows:
        QTest.keyClick(w, Qt.Key.Key_Right)
        QTest.keyClick(w, Qt.Key.Key_Right)
        QTest.keyClick(w, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClick(w, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClick(w, Qt.Key.Key_Up)
        QTest.keyClick(w, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(w, Qt.Key.Key_Down,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClick(w, Qt.Key.Key_Return)
        QApplication.processEvents()
    want = {"left": x0 + 2 - 10, "top": y0 + 10 - 1, "width": 301, "height": 90}
    check(f"{name}: arrows nudge 1 px (Shift 10), Ctrl+arrows resize, Enter confirms",
          picked == [want], f"(want {want}, got {picked})")
    picker.close()

    # Plain release still confirms at once.
    picked.clear()
    picker, w = _picker(screen, cursor, picked, cancelled)
    cursor[0] = (x0, y0)
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 20))
    cursor[0] = (x0 + 300, y0 + 80)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(80, 50))
    QApplication.processEvents()
    check(f"{name}: plain release confirms at once",
          picked == [{"left": x0, "top": y0, "width": 300, "height": 80}], f"(got {picked})")
    picker.close()

    # Partial repaint: a mouse move asks for strips (crosshair lines,
    # selection, magnifier), not the whole monitor. Recorded at update().
    from PySide6.QtGui import QRegion

    picker, w = _picker(screen, cursor, picked, cancelled)
    _pump(0.3)
    full = w.width() * w.height()
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(200, 200))
    _pump(0.1)
    updates: list = []
    orig_update = w.update

    def record(*args):
        updates.append(args)
        return orig_update(*args)
    w.update = record
    for i in range(1, 4):
        QTest.mouseMove(w, QPoint(200 + 20 * i, 200 + 13 * i))
    _pump(0.05)
    w.__dict__.pop("update", None)
    painted = 0
    for args in updates:
        if args and isinstance(args[0], QRegion):
            painted += sum(r.width() * r.height() for r in args[0])
        elif args and isinstance(args[0], QRect):
            painted += args[0].width() * args[0].height()
        else:
            painted += full            # update() with no area: whole window
    share = painted / max(1, full * max(1, len(updates)))
    check(f"{name}: mouse move repaints only changed areas",
          bool(updates) and share < 0.25,
          f"({len(updates)} update calls, {share:.1%} of the window each)")
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(260, 240))
    picker.close()

    # Magnifier on screens at 200 % or more.
    picker, w = _picker(screen, cursor, picked, cancelled)
    big = screen.devicePixelRatio() >= 2
    has = bool(getattr(w, "magnifier", False))
    snap = getattr(w, "snapshot", None)
    ok = has == big and (not big or (snap is not None and not snap.isNull()))
    if ok and big:
        cursor[0] = (mon["left"] + 600, mon["top"] + 600)
        QTest.mouseMove(w, QPoint(200, 200))
        QApplication.processEvents()
        img = w.grab(QRect(200 + 28, 200 + 28, 132, 132)).toImage()
        ok = not img.isNull()
    check(f"{name}: magnifier {'on' if big else 'off'} at scale {screen.devicePixelRatio():g}",
          ok, f"(magnifier {has}, snapshot {None if snap is None else snap.size().toTuple()})")
    picker.close()


# ---------------------------------------------------------------------------
# Nav bar
# ---------------------------------------------------------------------------
@guarded
def check_navbar(screen) -> None:
    from app.ui.navbar import NavBar

    nav = NavBar([{"id": "mining", "label": "MINING"}])
    _on_secondary(nav, screen)
    # slide_out connects `finished` once, however often it runs.
    nav._shown = True
    nav.slide_out()
    nav._anim.stop()
    nav._shown = True
    nav.slide_out()
    nav._anim.stop()
    nav._shown = True
    nav.slide_out()
    count = nav._anim.receivers(SIGNAL("finished()"))
    check("nav: slide_out connects finished once", count == 1, f"({count} connections)")
    _pump(0.4)
    check("nav: hidden after slide_out", not nav.isVisible())
    _on_secondary(nav, screen)        # back on the secondary monitor, invisible
    gear = nav._gear if hasattr(nav, "_gear") else None
    nav.set_settings_attention(True)
    seen = set()
    end = time.monotonic() + 1.6
    while time.monotonic() < end:
        QApplication.processEvents()
        seen.add(gear.property("attention"))
        time.sleep(0.02)
    check("nav: ⚙ pulses while attention is on",
          nav.settings_attention and {"dim", "bright"} <= seen, f"(looks {sorted(map(str, seen))})")
    nav.set_settings_attention(False)
    _pump(0.8)
    check("nav: ⚙ back to normal when turned off",
          not nav.settings_attention and gear.property("attention") == "off")

    nav.close()
    nav.deleteLater()


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if QApplication.instance() is None:
        QApplication(sys.argv)

    print(f"Code under test: {ROOT}")
    screens = secondary_screens()
    for s in QGuiApplication.screens():
        print(f"  {s.name():<16} scale {s.devicePixelRatio():.2f}"
              f"{'  (main: not used)' if s not in screens else ''}")
    if not screens:
        print("  FAIL  no secondary monitor: these checks never use the main monitor")
        return 1
    print("-" * 78)
    for s in screens:
        check_outline_marks(s)
        check_outline_region_move(s)
    check_outline_enforce_bounded(screens[0])
    print("-" * 78)
    check_panel(screens[0])
    check_panel_ground(screens[0])
    print("-" * 78)
    for s in screens:
        check_picker(s)
    print("-" * 78)
    check_navbar(screens[0])
    print("-" * 78)
    print("ALL CHECKS PASSED" if FAILURES == 0 else f"{FAILURES} CHECK(S) FAILED")
    return FAILURES


if __name__ == "__main__":
    raise SystemExit(main())
