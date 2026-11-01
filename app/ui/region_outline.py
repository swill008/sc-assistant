"""On-screen outline of the capture box (Settings → SHOW BOX).

Shows exactly where the OCR reads. The window sits just outside the box,
never over it, is click-through, and is always hidden from screen capture, so
the scanner and screenshots never see it. It is placed in physical pixels
through ``win32.place_physical`` because Qt's per-monitor logical coordinates
do not line up with the captured rect when monitors use different scaling.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import display, win32

GAP = 2       # physical pixels between the box and the line
LINE = 2       # physical line width


def outline_rect(region: dict) -> dict:
    """Physical rect of the outline window around a capture box."""
    pad = GAP + LINE
    return {"left": region["left"] - pad, "top": region["top"] - pad,
            "width": region["width"] + 2 * pad, "height": region["height"] + 2 * pad}


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

    @property
    def region(self) -> dict | None:
        """The box the outline is drawn around (None before the first show)."""
        return dict(self._region) if self._region is not None else None

    def show_region(self, region: dict) -> None:
        self._region = dict(region)
        rect = outline_rect(region)
        # Give Qt the right monitor and logical size first. Otherwise Qt keeps
        # its default size and re-applies it at the new scale when Windows
        # reports the DPI change after the physical move (measured: 960x720
        # instead of 88x48 on a 150% monitor).
        screen = display.screen_of_region(region)
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

    def event(self, ev):  # noqa: D102
        # Qt re-applies its own logical geometry after a move to a monitor
        # with another scale, rounded to whole logical pixels (88 px became
        # 89 at 150%). Put the exact physical rect back whenever that happens.
        if ev.type() in (QEvent.Type.Move, QEvent.Type.Resize) and self._region is not None:
            QTimer.singleShot(0, self._enforce)
        return super().event(ev)

    def _enforce(self) -> None:
        if self._region is None or not self.isVisible():
            return
        want = outline_rect(self._region)
        got = win32.physical_window_rect(self)
        if got is not None and got != want:
            win32.place_physical(self, want)

    def keep_on_top(self) -> None:
        # Re-place too: Windows can resize a window that crossed monitors
        # with different scaling.
        if self._region is not None and self.isVisible():
            win32.place_physical(self, outline_rect(self._region))

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        dpr = self.devicePixelRatio() or 1.0
        line = LINE / dpr
        pen = QPen(QColor(79, 209, 224, 235), line)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        half = line / 2
        p.drawRect(QRectF(half, half, self.width() - line, self.height() - line))
