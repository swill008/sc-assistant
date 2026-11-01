"""Full-screen drag-to-select tool for calibrating the capture region.

One transparent window per monitor. A single window stretched across every
monitor gets one scale factor from Qt (whichever monitor it lands on), so on a
mixed-scale desk (e.g. a 150% 5K2K main screen beside a 300% TV) every box was
converted with the wrong scale and stored at the wrong size. Per-monitor
windows each get their own scale for drawing, and the stored region comes from
the physical cursor position, which has no scale at all.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import win32
from ..display import physical_rect
from . import theme


class _ScreenOverlay(QWidget):
    """The dimmed drag surface for one monitor."""

    def __init__(self, owner: "RegionSelector", screen, hint: str):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())

        self._owner = owner
        self.physical = physical_rect(screen)
        self._hint = hint
        self._origin: QPoint | None = None
        self._rect = QRect()
        self._cursor = QPoint()

    # ------------------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._rect = QRect(self._origin, self._origin)
            self._owner._press(self)
            self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        self._cursor = event.position().toPoint()
        if self._origin is not None:
            self._rect = QRect(self._origin, self._cursor).normalized()
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        self._origin = None
        if not self._owner._release(self):
            self._rect = QRect()
            self.update()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._owner._cancel()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Dim everything except the current selection.
        p.fillRect(self.rect(), QColor(4, 7, 11, 150))
        if not self._rect.isNull():
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(self._rect, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            p.setPen(QPen(theme.ACCENT, 1.5))
            p.drawRect(self._rect)

            # Corner ticks
            p.setPen(QPen(theme.ACCENT, 3.0))
            r = self._rect
            tick = min(16, r.width() // 3, r.height() // 3)
            for start, end in (
                (r.topLeft(), r.topLeft() + QPoint(tick, 0)),
                (r.topLeft(), r.topLeft() + QPoint(0, tick)),
                (r.topRight(), r.topRight() + QPoint(-tick, 0)),
                (r.topRight(), r.topRight() + QPoint(0, tick)),
                (r.bottomLeft(), r.bottomLeft() + QPoint(tick, 0)),
                (r.bottomLeft(), r.bottomLeft() + QPoint(0, -tick)),
                (r.bottomRight(), r.bottomRight() + QPoint(-tick, 0)),
                (r.bottomRight(), r.bottomRight() + QPoint(0, -tick)),
            ):
                p.drawLine(start, end)

            # Size in physical pixels: what is stored and what the README's
            # "about 200 x 50" guidance refers to.
            dpr = self.devicePixelRatio()
            label = f"{round(r.width() * dpr)} × {round(r.height() * dpr)} px"
            p.setFont(theme.pfont(9, QFont.Weight.DemiBold))
            p.setPen(theme.TEXT)
            p.drawText(r.adjusted(0, 0, 0, -6).translated(0, -18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, label)

        # Instructions
        p.setFont(theme.pfont(10, QFont.Weight.DemiBold, spacing=1.0))
        p.setPen(theme.TEXT)
        title_rect = QRectF(0, 48, self.width(), 24)
        p.drawText(title_rect, Qt.AlignmentFlag.AlignHCenter, self._hint.upper())

        p.setFont(theme.pfont(9))
        p.setPen(theme.MUTED)
        p.drawText(QRectF(0, 74, self.width(), 20), Qt.AlignmentFlag.AlignHCenter,
                   "ESC to cancel  ·  release to confirm  ·  region is stored in physical pixels")

        # Crosshair
        if self._cursor:
            p.setPen(QPen(QColor(79, 209, 224, 170), 1.0, Qt.PenStyle.DashLine))
            c = self._cursor
            p.drawLine(QPoint(0, c.y()), QPoint(self.width(), c.y()))
            p.drawLine(QPoint(c.x(), 0), QPoint(c.x(), self.height()))


class RegionSelector(QObject):
    """Shows a drag surface on every monitor and emits one physical region."""

    selected = Signal(dict)      # {"left", "top", "width", "height"}, physical pixels
    cancelled = Signal()

    def __init__(self, hint: str = "Drag a box around the scan signature",
                 cursor_pos=None, screens=None):
        """``screens`` limits the picker to those monitors (the game monitor
        chosen in Settings); by default it covers every monitor."""
        super().__init__()
        self._cursor_pos = cursor_pos or win32.cursor_pos
        self._start: tuple[int, int] | None = None
        self._done = False
        self.windows = [_ScreenOverlay(self, screen, hint)
                        for screen in (screens or QGuiApplication.screens())]

    # ------------------------------------------------------------------
    def show(self) -> None:
        for w in self.windows:
            w.show()
        self.raise_()

    def raise_(self) -> None:
        for w in self.windows:
            w.raise_()
        x, y = self._cursor_pos()
        target = self.window_for_physical(x, y)
        target.activateWindow()
        target.setFocus(Qt.FocusReason.OtherFocusReason)

    def close(self) -> None:
        self._done = True
        for w in self.windows:
            w.close()
        self.windows = []

    def window_for_physical(self, x: int, y: int) -> _ScreenOverlay:
        """The drag surface on the monitor containing a physical point."""
        for w in self.windows:
            m = w.physical
            if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
                return w
        return self.windows[0]

    # -- called by the per-monitor windows -------------------------------
    def _press(self, window: _ScreenOverlay) -> None:
        self._start = self._cursor_pos()

    def _release(self, window: _ScreenOverlay) -> bool:
        """Emit the region if it is big enough; False keeps the picker open."""
        if self._start is None or self._done:
            return False
        m = window.physical
        right, bottom = m["left"] + m["width"], m["top"] + m["height"]

        def clamp(x, y):   # a drag stays on the monitor it started on
            return (min(max(x, m["left"]), right), min(max(y, m["top"]), bottom))

        (x0, y0), (x1, y1) = clamp(*self._start), clamp(*self._cursor_pos())
        self._start = None
        region = {"left": min(x0, x1), "top": min(y0, y1),
                  "width": abs(x1 - x0), "height": abs(y1 - y0)}
        if region["width"] < 8 or region["height"] < 8:
            return False
        self.close()
        self.selected.emit(region)
        return True

    def _cancel(self) -> None:
        if self._done:
            return
        self.close()
        self.cancelled.emit()
