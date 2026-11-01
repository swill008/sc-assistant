"""On-screen outline of the capture box (Settings → SHOW BOX).

Shows exactly where the OCR reads. Two modes in one window:

- ``show_region(box)``: one cyan line just outside the box.
- ``show_marks(digits, pin, state, label)``: HUD tracking feedback, an
  outline just outside the digits and (when given) the pin icon, in the
  tracking state's colour, with a small bold label strip just above.

The lines sit just outside the rects, never over them. The window is
click-through and always hidden from screen capture, so the scanner and
screenshots never see it. It is placed in physical pixels through
``win32.place_physical`` because Qt's per-monitor logical coordinates do not
line up with the captured rect when monitors use different scaling.

Placement cost: a move on the same monitor is one ``place_physical``. Only a
first show or a move to another monitor tells Qt the screen and logical size
first and then re-checks the rect a few times; ``_enforce`` corrects at most
``MAX_CORRECTIONS`` times per placement so it can never ping-pong with Qt.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import display, win32
from . import theme

GAP = 2        # physical pixels between the box and the line
LINE = 2       # physical line width
MAX_CORRECTIONS = 3   # _enforce re-placements allowed per placement

# Label strip, in logical pixels of the monitor (times its scale = physical).
LABEL_FONT_PX = 10
LABEL_HEIGHT = 15
LABEL_PAD_X = 5
LABEL_GAP = 2

REGION_COLOR = QColor(79, 209, 224, 235)


def outline_rect(region: dict) -> dict:
    """Physical rect of the outline window around a capture box."""
    pad = GAP + LINE
    return {"left": region["left"] - pad, "top": region["top"] - pad,
            "width": region["width"] + 2 * pad, "height": region["height"] + 2 * pad}


def _union(rects: list[dict]) -> dict:
    left = min(r["left"] for r in rects)
    top = min(r["top"] for r in rects)
    right = max(r["left"] + r["width"] for r in rects)
    bottom = max(r["top"] + r["height"] for r in rects)
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def _label_font(scale: float) -> QFont:
    f = QFont(theme.UI_FAMILY)
    f.setPixelSize(max(6, round(LABEL_FONT_PX * scale)))
    f.setWeight(QFont.Weight.Bold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, round(1.0 * scale, 2))
    return f


def marks_layout(digits: dict, pin: dict | None, label: str, scale: float,
                 monitor: dict | None = None) -> dict:
    """Physical layout of the marks window.

    Returns {"window": rect, "outlines": [rects], "strip": rect}, all
    physical and absolute. The strip sits just above the outlines, or just
    below them when there is no room above on the monitor.
    """
    outlines = [outline_rect(digits)] + ([outline_rect(pin)] if pin else [])
    box = _union(outlines)
    fm = QFontMetricsF(_label_font(scale))
    strip_w = int(fm.horizontalAdvance(label) + 2 * LABEL_PAD_X * scale + 2)
    strip_h = max(int(fm.height()) + 2, round(LABEL_HEIGHT * scale))
    gap = round(LABEL_GAP * scale)
    top = box["top"] - gap - strip_h
    if monitor is not None and top < monitor["top"]:
        top = box["top"] + box["height"] + gap         # no room above
    strip = {"left": box["left"], "top": top, "width": strip_w, "height": strip_h}
    window = _union([box, strip])
    # Grow the window (transparent margin) to a position and size that Qt's
    # whole-logical-pixel geometry maps back exactly. Otherwise every repaint
    # flushes the layered window at Qt's rounded rect (measured on a 300%
    # monitor: 1 px left/up and 94 -> 93 px tall), which needs a correction.
    if monitor is not None:
        for axis, size, origin in (("left", "width", monitor["left"]),
                                   ("top", "height", monitor["top"])):
            start = stable_start(window[axis] - origin, scale) + origin
            window[size] += window[axis] - start
            window[axis] = start
    window["width"] = stable_size(window["width"], scale)
    window["height"] = stable_size(window["height"], scale)
    return {"window": window, "outlines": outlines, "strip": strip}


def _qround(x: float) -> int:
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def stable_start(offset: int, scale: float) -> int:
    """Largest monitor offset <= offset that survives Qt's logical rounding."""
    for value in range(offset, offset - int(scale) - 3, -1):
        if _qround(_qround(value / scale) * scale) == value:
            return value
    return offset


def stable_size(n: int, scale: float) -> int:
    """Smallest physical size >= n that survives Qt's logical rounding."""
    for size in range(n, n + int(scale) + 3):
        if _qround(_qround(size / scale) * scale) == size:
            return size
    return n


def _relative(layout: dict | None) -> list | None:
    """The marks layout relative to its window: equal means same picture."""
    if layout is None:
        return None
    ox, oy = layout["window"]["left"], layout["window"]["top"]
    return [(r["left"] - ox, r["top"] - oy, r["width"], r["height"])
            for r in (*layout["outlines"], layout["strip"], layout["window"])]


class RegionOutline(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._region: dict | None = None
        self._marks: dict | None = None        # {"digits", "pin"}
        self._state = ""
        self._label = ""
        self._layout: dict | None = None       # marks_layout() of the current marks
        self._target: dict | None = None       # physical window rect we want
        self._screen: str | None = None        # monitor name of the last placement
        self._corrections = 0
        self._enforce_pending = False

    # -- properties (tests and main) --------------------------------------
    @property
    def region(self) -> dict | None:
        """The box the outline is drawn around (None before the first show)."""
        return dict(self._region) if self._region is not None else None

    @property
    def state(self) -> str:
        """Tracking state of the marks ("" in plain region mode)."""
        return self._state

    @property
    def label(self) -> str:
        """Label text above the marks ("" in plain region mode)."""
        return self._label

    @property
    def marks(self) -> dict | None:
        """{"digits": rect, "pin": rect | None}, or None in region mode."""
        if self._marks is None:
            return None
        return {"digits": dict(self._marks["digits"]),
                "pin": dict(self._marks["pin"]) if self._marks["pin"] else None}

    @property
    def target_rect(self) -> dict | None:
        """The physical window rect the outline is kept at."""
        return dict(self._target) if self._target is not None else None

    # -- showing ----------------------------------------------------------
    def show_region(self, region: dict) -> None:
        region = dict(region)
        if (self._marks is None and region == self._region
                and self.isVisible() and self._target is not None):
            return
        repaint = self._layout is not None       # marks -> plain box
        self._region = region
        self._marks = None
        self._layout = None
        self._state = ""
        self._label = ""
        self._place(outline_rect(region), display.screen_of_region(region), repaint=repaint)

    def show_marks(self, digits: dict, pin: dict | None, state: str,
                   label: str = "") -> None:
        """Outline the digits and the pin in the tracking state's colour,
        with ``label`` (default TRACK_TEXT[state]) in a strip just above."""
        if state not in theme.TRACK_COLOR:
            raise ValueError(f"unknown tracking state {state!r}")
        digits = dict(digits)
        pin = dict(pin) if pin else None
        label = label or theme.TRACK_TEXT[state]
        marks = {"digits": digits, "pin": pin}
        if (marks == self._marks and state == self._state and label == self._label
                and self.isVisible() and self._target is not None):
            return
        screen = display.screen_of_region(digits)
        scale = float(screen.devicePixelRatio() or 1.0) if screen is not None else 1.0
        monitor = display.physical_rect(screen) if screen is not None else None
        layout = marks_layout(digits, pin, label, scale, monitor)
        repaint = (state != self._state or label != self._label
                   or _relative(layout) != _relative(self._layout))
        self._marks = marks
        self._region = digits
        self._state = state
        self._label = label
        self._layout = layout
        self._place(layout["window"], screen, repaint=repaint)

    def _place(self, rect: dict, screen, repaint: bool = False) -> None:
        rect = dict(rect)
        name = screen.name() if screen is not None else None
        same = (self.isVisible() and name is not None and name == self._screen
                and self._target is not None)
        resized = self._target is None or (rect["width"], rect["height"]) != (
            self._target["width"], self._target["height"])
        self._target = rect
        self._corrections = 0
        if same:
            # Same monitor: one physical placement is exact; no Qt geometry,
            # no timers. A pure move needs no repaint either (the content is
            # drawn relative to the window): a repaint makes Qt flush its
            # layered backing store at its own rounded size, which resizes
            # the window and needs a correction.
            win32.place_physical(self, rect)
            if resized or repaint:
                self.update()
            return
        # First show or another monitor. Give Qt the right monitor and
        # logical size first. Otherwise Qt keeps its default size and
        # re-applies it at the new scale when Windows reports the DPI change
        # after the physical move (measured: 960x720 instead of 88x48 on a
        # 150% monitor).
        self._screen = name
        if screen is not None:
            self.setScreen(screen)
            self.setGeometry(display.logical_geometry(rect, screen))
        if not self.isVisible():
            self.show()
            win32.make_overlay_window(self, click_through=True)
            win32.exclude_from_capture(self)
        win32.place_physical(self, rect)
        # Qt applies its own (rounded) geometry from a queued event after the
        # window is shown, without a Move/Resize event when its logical size
        # is unchanged. Traced: 88 px right after show, 89 px once events ran,
        # 88 px again after one more SetWindowPos, and then stable.
        for delay in (0, 50, 250):
            QTimer.singleShot(delay, self._enforce)
        self.update()

    def hideEvent(self, event):  # noqa: N802
        self._screen = None     # the next show places it in full again
        super().hideEvent(event)

    def event(self, ev):  # noqa: D102
        # Qt re-applies its own logical geometry after a move to a monitor
        # with another scale, rounded to whole logical pixels (88 px became
        # 89 at 150%). Put the exact physical rect back whenever that happens,
        # one check per burst of events.
        if (ev.type() in (QEvent.Type.Move, QEvent.Type.Resize)
                and self._target is not None and not self._enforce_pending):
            self._enforce_pending = True
            QTimer.singleShot(0, self._enforce_queued)
        return super().event(ev)

    def _enforce_queued(self) -> None:
        self._enforce_pending = False
        self._enforce()

    def _enforce(self) -> None:
        if self._target is None or not self.isVisible():
            return
        got = win32.physical_window_rect(self)
        if got is None or got == self._target:
            return
        if self._corrections >= MAX_CORRECTIONS:
            return      # Qt keeps fighting: stop rather than ping-pong
        self._corrections += 1
        win32.place_physical(self, self._target)

    def keep_on_top(self) -> None:
        # Re-place only when Windows moved or resized it (a window that
        # crossed monitors with different scaling); otherwise just re-assert
        # topmost.
        if self._target is None or not self.isVisible():
            return
        if win32.physical_window_rect(self) != self._target:
            win32.place_physical(self, self._target)
        else:
            win32.keep_on_top(self)

    # -- painting ---------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        dpr = self.devicePixelRatio() or 1.0
        if self._layout is None:
            line = LINE / dpr
            pen = QPen(REGION_COLOR, line)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            p.setPen(pen)
            half = line / 2
            p.drawRect(QRectF(half, half, self.width() - line, self.height() - line))
            return

        # Paint in physical pixels relative to the window's physical origin.
        p.scale(1.0 / dpr, 1.0 / dpr)
        ox, oy = self._target["left"], self._target["top"]
        colour = theme.TRACK_COLOR[self._state]
        pen = QPen(colour, LINE)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        half = LINE / 2
        for r in self._layout["outlines"]:
            p.drawRect(QRectF(r["left"] - ox + half, r["top"] - oy + half,
                              r["width"] - LINE, r["height"] - LINE))

        s = self._layout["strip"]
        strip = QRectF(s["left"] - ox, s["top"] - oy, s["width"], s["height"])
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(9, 13, 19, 210))
        radius = min(3.0 * dpr, s["height"] / 2)
        p.drawRoundedRect(strip, radius, radius)
        p.setFont(_label_font(dpr))
        p.setPen(colour)
        p.drawText(strip, Qt.AlignmentFlag.AlignCenter, self._label)
