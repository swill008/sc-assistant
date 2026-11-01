"""Pin toggle for a panel header: a pinned panel stays on screen when the
overlay is hidden (F4 / the nav bar's ✕). Placed next to the panel's ✕.

The owner keeps the pinned state in config "pinned_windows" (list of panel
ids); this widget only draws itself and reports clicks.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton

from . import theme


class PinButton(QPushButton):
    """Checkable pin icon; ``pin_toggled(bool)`` on user clicks only."""

    pin_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(theme.px(20), theme.px(20))
        self.setFlat(True)
        self._refresh_tip()
        self.clicked.connect(self._on_clicked)

    def set_pinned(self, pinned: bool) -> None:
        """Programmatic set (start-up); does not emit pin_toggled."""
        self.setChecked(bool(pinned))
        self._refresh_tip()
        self.update()

    def _on_clicked(self, checked: bool) -> None:
        self._refresh_tip()
        self.pin_toggled.emit(bool(checked))

    def _refresh_tip(self) -> None:
        self.setToolTip("Pinned: stays on screen when the overlay is hidden (click to unpin)"
                        if self.isChecked() else
                        "Pin: keep this window on screen when the overlay is hidden")

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        if self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(79, 209, 224, 36))
            p.drawRoundedRect(QRectF(0, 0, w, h), w / 2, h / 2)
        colour = theme.ACCENT if self.isChecked() else QColor(150, 164, 180, 205)
        # A push-pin: round head, short neck, needle; tilted when unpinned.
        p.translate(w / 2, h / 2)
        if not self.isChecked():
            p.rotate(35)
        s = min(w, h) / 20.0
        p.setPen(QPen(colour, 1.4 * s))
        p.setBrush(colour if self.isChecked() else Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, -4.5 * s), 3.6 * s, 3.6 * s)
        body = QPainterPath()
        body.moveTo(-2.2 * s, -1.5 * s)
        body.lineTo(2.2 * s, -1.5 * s)
        body.lineTo(1.2 * s, 2.0 * s)
        body.lineTo(-1.2 * s, 2.0 * s)
        body.closeSubpath()
        p.drawPath(body)
        p.drawLine(QPointF(0, 2.0 * s), QPointF(0, 7.0 * s))
