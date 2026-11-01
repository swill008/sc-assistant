"""Full-screen drag-to-select tool for calibrating the capture region.

One transparent window per monitor. A single window stretched across every
monitor gets one scale factor from Qt (whichever monitor it lands on), so on a
mixed-scale desk (e.g. a 150% 5K2K main screen beside a 300% TV) every box was
converted with the wrong scale and stored at the wrong size. Per-monitor
windows each get their own scale for drawing, and the stored region comes from
the physical cursor position, which has no scale at all.

Conveniences:
- Right-click or Esc cancels.
- Releasing the drag confirms at once, as it always has. Holding Ctrl while
  releasing keeps the box instead, for fine-tuning: arrow keys move it 1
  physical pixel (Shift: 10), Ctrl+arrows resize it from the right/bottom
  edge, Enter confirms, Esc or right-click cancels, a new drag starts over.
  (Chosen so a plain drag behaves exactly as before; nothing waits on a timer.)
- On monitors at 200% scale or more a magnifier follows the cursor, showing
  the screen as it was when the picker opened, 1 physical pixel per cell.
- Mouse moves repaint only the strips that changed (crosshair lines,
  selection, magnifier), not the whole monitor.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QPainter, QPen,
                           QPixmap, QRegion)
from PySide6.QtWidgets import QWidget

from .. import win32
from ..display import physical_rect
from . import theme

MIN_SIZE = 8            # physical px; smaller drags are ignored
LOUPE_SCALE = 2.0       # magnifier from this monitor scale up
LOUPE_SIZE = 132        # logical px, square
LOUPE_CELLS = 21        # physical px shown across (odd: centre cell = cursor)
LOUPE_OFFSET = 28       # logical px from the cursor


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
        self._screen_ref = screen
        self.physical = physical_rect(screen)
        self._hint = hint
        self._origin: QPoint | None = None
        self._rect = QRectF()           # selection, logical
        self._cursor: QPoint | None = None
        self.adjusting = False          # Ctrl-release: box kept for arrow keys
        self.magnifier = float(screen.devicePixelRatio() or 1.0) >= LOUPE_SCALE
        self.snapshot: QPixmap | None = None

    def take_snapshot(self) -> None:
        """Screen image for the magnifier; taken before the overlay shows."""
        if self.magnifier and self.snapshot is None:
            shot = self._screen_ref.grabWindow(0)
            self.snapshot = shot if not shot.isNull() else None

    # -- dirty areas (logical) -----------------------------------------
    def _scale(self) -> float:
        return float(self.devicePixelRatio() or 1.0)

    def _label_rect(self, r: QRectF) -> QRectF:
        h = theme.px(18)
        top = r.top() - h - 2 if r.top() - h - 2 >= 0 else r.bottom() + 4
        return QRectF(r.left(), top, theme.px(160), h)

    def _selection_area(self) -> QRect:
        if self._rect.isNull():
            return QRect()
        r = self._rect
        area = r.adjusted(-4, -4, 4, 4).united(self._label_rect(r).adjusted(-2, -2, 2, 2))
        return area.toAlignedRect()

    def _loupe_rect(self, c: QPoint) -> QRect:
        size = LOUPE_SIZE
        x = c.x() + LOUPE_OFFSET
        y = c.y() + LOUPE_OFFSET
        if x + size > self.width():
            x = c.x() - LOUPE_OFFSET - size
        if y + size > self.height():
            y = c.y() - LOUPE_OFFSET - size
        return QRect(x, y, size, size)

    def _cursor_area(self, c: QPoint | None) -> QRegion:
        if c is None:
            return QRegion()
        region = QRegion(QRect(0, c.y() - 2, self.width(), 5))
        region += QRegion(QRect(c.x() - 2, 0, 5, self.height()))
        if self.magnifier:
            region += QRegion(self._loupe_rect(c).adjusted(-3, -3, 3, 3))
        return region

    def dirty_for(self, old_cursor, old_sel: QRect) -> QRegion:
        """What a move from the old to the current state must repaint."""
        region = self._cursor_area(old_cursor) + self._cursor_area(self._cursor)
        sel = self._selection_area()
        if old_sel != sel:
            region += QRegion(old_sel) + QRegion(sel)
        return region

    def set_physical_selection(self, region: dict) -> None:
        """Show a physical-pixel box (after a nudge) in this window."""
        old = self._selection_area()
        s = self._scale()
        m = self.physical
        self._rect = QRectF((region["left"] - m["left"]) / s, (region["top"] - m["top"]) / s,
                            region["width"] / s, region["height"] / s)
        self.update(QRegion(old) + QRegion(self._selection_area()))

    # ------------------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._owner._cancel()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.adjusting = False
            self._origin = event.position().toPoint()
            self._rect = QRectF(QPointF(self._origin), QPointF(self._origin))
            self._owner._press(self)
            self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        old_cursor, old_sel = self._cursor, self._selection_area()
        self._cursor = event.position().toPoint()
        if self._origin is not None:
            self._rect = QRectF(QRect(self._origin, self._cursor).normalized())
        self.update(self.dirty_for(old_cursor, old_sel))

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        self._origin = None
        keep = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if not self._owner._release(self, keep=keep):
            self._rect = QRectF()
            self.update()

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._owner._cancel()
            return
        if self.adjusting and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._owner._confirm()
            return
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                  Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if self.adjusting and key in arrows:
            mods = event.modifiers()
            step = 10 if mods & Qt.KeyboardModifier.ShiftModifier else 1
            dx, dy = arrows[key]
            if mods & Qt.KeyboardModifier.ControlModifier:
                self._owner._resize(dx * step, dy * step)
            else:
                self._owner._nudge(dx * step, dy * step)
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setClipRegion(event.region())

        # Dim everything except the current selection.
        p.fillRect(self.rect(), QColor(4, 7, 11, 150))
        if not self._rect.isNull():
            r = self._rect
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(r, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            p.setPen(QPen(theme.ACCENT, 1.5))
            p.drawRect(r)

            # Corner ticks
            p.setPen(QPen(theme.ACCENT, 3.0))
            tick = min(16.0, r.width() / 3, r.height() / 3)
            for corner, sx, sy in ((r.topLeft(), 1, 1), (r.topRight(), -1, 1),
                                   (r.bottomLeft(), 1, -1), (r.bottomRight(), -1, -1)):
                p.drawLine(corner, corner + QPointF(sx * tick, 0))
                p.drawLine(corner, corner + QPointF(0, sy * tick))

            # Size in physical pixels: what is stored and what the README's
            # "about 200 x 50" guidance refers to.
            pending = self._owner.pending if self.adjusting else None
            if pending is not None:
                w_px, h_px = pending["width"], pending["height"]
            else:
                dpr = self._scale()
                w_px, h_px = round(r.width() * dpr), round(r.height() * dpr)
            p.setFont(theme.font(9, QFont.Weight.DemiBold))
            p.setPen(theme.TEXT)
            p.drawText(self._label_rect(r),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"{w_px} × {h_px} px")

        # Instructions
        p.setFont(theme.font(10, QFont.Weight.DemiBold, spacing=1.0))
        p.setPen(theme.TEXT)
        p.drawText(QRectF(0, theme.px(48), self.width(), theme.px(24)),
                   Qt.AlignmentFlag.AlignHCenter, self._hint.upper())

        p.setFont(theme.font(9))
        p.setPen(theme.MUTED)
        help_text = ("ARROWS move 1 px  ·  SHIFT 10 px  ·  CTRL+ARROWS resize  ·  "
                     "ENTER to confirm  ·  ESC or right-click to cancel"
                     if self.adjusting else
                     "ESC or right-click to cancel  ·  release to confirm  ·  "
                     "hold CTRL on release to fine-tune with the arrow keys")
        p.drawText(QRectF(0, theme.px(76), self.width(), theme.px(22)),
                   Qt.AlignmentFlag.AlignHCenter, help_text)

        # Crosshair
        c = self._cursor
        if c is not None:
            p.setPen(QPen(QColor(79, 209, 224, 170), 1.0, Qt.PenStyle.DashLine))
            p.drawLine(QPoint(0, c.y()), QPoint(self.width(), c.y()))
            p.drawLine(QPoint(c.x(), 0), QPoint(c.x(), self.height()))
            if self.magnifier:
                self._paint_loupe(p, c)

    def _paint_loupe(self, p: QPainter, c: QPoint) -> None:
        box = QRectF(self._loupe_rect(c))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(9, 13, 19, 235))
        p.drawRect(box)
        shot = self.snapshot
        if shot is not None:
            # Physical cursor -> snapshot pixel (the snapshot may come back
            # at a different size than the monitor; map proportionally).
            px_, py_ = self._owner._cursor_pos()
            m = self.physical
            kx = shot.width() / max(1, m["width"])
            ky = shot.height() / max(1, m["height"])
            half = LOUPE_CELLS // 2
            src = QRectF((px_ - m["left"] - half) * kx, (py_ - m["top"] - half) * ky,
                         LOUPE_CELLS * kx, LOUPE_CELLS * ky)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            p.drawPixmap(box, shot, src)
        # Centre cell = the pixel under the cursor.
        cell = box.width() / LOUPE_CELLS
        centre = QRectF(box.left() + cell * (LOUPE_CELLS // 2),
                        box.top() + cell * (LOUPE_CELLS // 2), cell, cell)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.ACCENT, 1.0))
        p.drawRect(centre)
        p.setPen(QPen(theme.BORDER_HI, 1.5))
        p.drawRect(box)


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
        self._pending: dict | None = None            # Ctrl-release box, physical
        self._pending_window: _ScreenOverlay | None = None
        self.windows = [_ScreenOverlay(self, screen, hint)
                        for screen in (screens or QGuiApplication.screens())]

    @property
    def pending(self) -> dict | None:
        """The box kept for fine-tuning (Ctrl-release), physical; else None."""
        return dict(self._pending) if self._pending is not None else None

    # ------------------------------------------------------------------
    def show(self) -> None:
        for w in self.windows:
            w.take_snapshot()        # before any overlay is on screen
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
        if self._pending_window is not None and self._pending_window is not window:
            old = self._pending_window
            old.adjusting = False
            old._rect = QRectF()
            old.update()
        self._pending = None
        self._pending_window = None

    def _release(self, window: _ScreenOverlay, keep: bool = False) -> bool:
        """Emit the region if it is big enough; False keeps the picker open.

        ``keep`` (Ctrl held): keep the box on screen for arrow-key tuning
        instead of emitting it; Enter emits it later."""
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
        if region["width"] < MIN_SIZE or region["height"] < MIN_SIZE:
            return False
        if keep:
            self._pending = region
            self._pending_window = window
            window.adjusting = True
            window.set_physical_selection(region)
            window.update()          # the help line changes
            window.activateWindow()
            window.setFocus(Qt.FocusReason.OtherFocusReason)
            return True
        self.close()
        self.selected.emit(region)
        return True

    def _clamped(self, region: dict) -> dict:
        m = self._pending_window.physical
        w = min(max(MIN_SIZE, region["width"]), m["width"])
        h = min(max(MIN_SIZE, region["height"]), m["height"])
        left = min(max(region["left"], m["left"]), m["left"] + m["width"] - w)
        top = min(max(region["top"], m["top"]), m["top"] + m["height"] - h)
        return {"left": left, "top": top, "width": w, "height": h}

    def _nudge(self, dx: int, dy: int) -> None:
        """Move the kept box by whole physical pixels (stays on its monitor)."""
        if self._pending is None or self._done:
            return
        r = dict(self._pending)
        r["left"] += dx
        r["top"] += dy
        self._pending = self._clamped(r)
        self._pending_window.set_physical_selection(self._pending)

    def _resize(self, dw: int, dh: int) -> None:
        """Grow/shrink the kept box from its right/bottom edge."""
        if self._pending is None or self._done:
            return
        r = dict(self._pending)
        r["width"] += dw
        r["height"] += dh
        self._pending = self._clamped(r)
        self._pending_window.set_physical_selection(self._pending)

    def _confirm(self) -> None:
        if self._pending is None or self._done:
            return
        region = dict(self._pending)
        self.close()
        self.selected.emit(region)

    def _cancel(self) -> None:
        if self._done:
            return
        self.close()
        self.cancelled.emit()
