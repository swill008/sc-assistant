"""Compact mining scanner: one headline verdict, nothing else."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QGuiApplication,
                           QPainter, QPen)
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from ..mining import Match
from . import theme
from .pin_button import PinButton

PANEL_WIDTH = 372      # fits the header with the tracking chip and pin (was 330)
PANEL_HEIGHT = 172     # two signature rows, READ and the "or ..." line (was 158)
VERDICT_HEIGHT = PANEL_HEIGHT - 50   # margins, header and spacing take 50
RESULT_BORDER = 3.0    # result border width, design px
RESULTS = ("match", "nomatch", "noread")
NONE_TEXT = "—"


def ground_kind(match: Match) -> str:
    """HAND MINING (3,000-type readings) or ROC (4,000-type)."""
    return "HAND MINING" if match.kind == "fps" else "ROC"


def match_label(match: Match) -> str:
    """Upper-case label of a match; falls back to name / kind for a kind
    this panel does not know."""
    try:
        label = match.label
    except Exception:  # noqa: BLE001 - an unknown kind must not break painting
        label = ""
    return str(label or match.name or match.kind).upper()


def alt_match(matches: list[Match]) -> Match | None:
    """Second exact match of another kind than matches[0], or None."""
    if not matches:
        return None
    top = matches[0]
    return next((m for m in matches[1:] if m.exact and m.kind != top.kind), None)


class _Verdict(QWidget):
    """The mineral reading: scanned and matched signatures, name, count and
    read confidence."""

    # Layout, design px: one rect per text (rows()) so tests can check overlaps.
    CAPTION_Y, CAPTION_H = 0, 12
    VALUE_Y, VALUE_H = 12, 16
    READ_Y, READ_H = 28, 12
    HEAD_Y, HEAD_H = 40, 35
    DETAIL_Y, DETAIL_H = 76, 15
    ALT_Y, ALT_H = 91, 15
    METER_FROM_BOTTOM = 9
    NOTE_H = 12
    BAR_W = 88.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(theme.px(VERDICT_HEIGHT))
        self._scanned: int | None = None
        self._value: int | None = None
        self._confidence = 0.0
        self._state = "idle"
        self._match: Match | None = None
        self._alt: Match | None = None
        self._note = ""

    def set_scanned(self, value: int | None) -> None:
        if value == self._scanned:
            return
        self._scanned = value
        self.update()

    def set_scan(self, value: int | None, confidence: float, state: str,
                 match: Match | None, note: str = "",
                 alt: Match | None = None) -> None:
        self._value = value
        self._confidence = max(0.0, min(1.0, confidence))
        self._state = state
        self._match = match
        self._alt = alt
        self._note = note
        # Ground readings: the full candidate list, as the detail line is
        # elided to the panel width.
        if match is not None and match.is_ground and match.minerals:
            self.setToolTip(f"{ground_kind(match)}: could be\n" + "\n".join(match.minerals))
        else:
            self.setToolTip("")
        self.update()

    # ------------------------------------------------------------------
    # Texts (also read by the tests)
    def scanned_value_text(self) -> str:
        return NONE_TEXT if self._scanned is None else f"{self._scanned:,}"

    def matched_value_text(self) -> str:
        return NONE_TEXT if self._match is None else f"{self._match.target:,}"

    def read_text(self) -> str:
        return "" if self._value is None else f"READ {int(self._confidence * 100)}%"

    def alt_text(self) -> str:
        if self._alt is None:
            return ""
        return f"or {match_label(self._alt)} ×{self._alt.count}"

    @staticmethod
    def caption_font() -> QFont:
        return theme.pfont(7, QFont.Weight.Bold, spacing=1.4)

    @staticmethod
    def value_font() -> QFont:
        return theme.pfont(9, QFont.Weight.DemiBold, spacing=0.5)

    @staticmethod
    def read_font() -> QFont:
        return theme.pfont(7, QFont.Weight.Medium, spacing=0.7)

    @staticmethod
    def detail_font() -> QFont:
        return theme.pfont(8, QFont.Weight.Medium, spacing=0.2)

    def rows(self, w: int, h: int) -> dict[str, tuple[QRectF, QFont, Qt.AlignmentFlag]]:
        """name -> (rect, font, alignment) for every text the card draws."""
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        half = w / 2.0
        y = h - self.METER_FROM_BOTTOM
        return {
            "scanned_caption": (QRectF(0, self.CAPTION_Y, half, self.CAPTION_H),
                                self.caption_font(), left),
            "matched_caption": (QRectF(half, self.CAPTION_Y, half, self.CAPTION_H),
                                self.caption_font(), right),
            "scanned_value": (QRectF(0, self.VALUE_Y, half, self.VALUE_H),
                              self.value_font(), left),
            "matched_value": (QRectF(half, self.VALUE_Y, half, self.VALUE_H),
                              self.value_font(), right),
            "read": (QRectF(half, self.READ_Y, half, self.READ_H), self.read_font(), right),
            "headline": (QRectF(0, self.HEAD_Y, w - 48, self.HEAD_H), theme.phud_font(26), left),
            "count": (QRectF(w - 48, self.HEAD_Y, 48, self.HEAD_H), theme.phud_font(15), right),
            "detail": (QRectF(0, self.DETAIL_Y, w, self.DETAIL_H), self.detail_font(), left),
            "alt": (QRectF(0, self.ALT_Y, w, self.ALT_H), self.detail_font(), left),
            "note": (QRectF(self.BAR_W + 8, y - self.NOTE_H / 2, w - self.BAR_W - 8,
                            self.NOTE_H), theme.pfont(7, QFont.Weight.Medium), right),
        }

    # ------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        p, w, h = theme.paint(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        lost = self._state == "lost"
        rows = self.rows(w, h)
        value_pen = theme.MUTED if lost else theme.TEXT

        def text(name: str, colour: QColor, value: str, width: float | None = None) -> None:
            rect, font, align = rows[name]
            if width is not None:
                rect = QRectF(rect.x(), rect.y(), width, rect.height())
            p.setFont(font)
            p.setPen(colour)
            p.drawText(rect, align, QFontMetrics(font).elidedText(
                value, Qt.TextElideMode.ElideRight, int(rect.width())))

        # SCANNED SIGNATURE ............ MATCHED SIGNATURE
        # 7,200                                      7,200
        #                                         READ 82%
        text("scanned_caption", theme.DIM, "SCANNED SIGNATURE")
        text("matched_caption", theme.DIM, "MATCHED SIGNATURE")
        text("scanned_value", value_pen, self.scanned_value_text())
        text("matched_value", value_pen, self.matched_value_text())
        if self._value is not None:
            text("read", theme.DIM if lost else
                 (theme.GOOD if self._confidence >= 0.75 else theme.AMBER),
                 self.read_text())

        # Headline: the name takes the whole width when there is no count.
        name, color, count = self._headline(lost)
        text("headline", color, name, width=None if count else w)
        if count:
            text("count", theme.DIM if lost else theme.TEXT, count)

        # Detail, then a second exact match of another kind
        text("detail", theme.DIM if lost else theme.MUTED, self._detail())
        alt = self.alt_text()
        if alt:
            text("alt", theme.DIM if lost else theme.MUTED, alt)

        # Confidence meter
        y = h - self.METER_FROM_BOTTOM
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 16))
        p.drawRoundedRect(QRectF(0, y, self.BAR_W, 3), 1.5, 1.5)
        if self._value is not None and not lost:
            p.setBrush(theme.GOOD if self._confidence >= 0.75 else theme.AMBER)
            p.drawRoundedRect(
                QRectF(0, y, max(3.0, self.BAR_W * self._confidence), 3), 1.5, 1.5)

        if self._note:
            text("note", theme.DIM, self._note)

    # ------------------------------------------------------------------
    def _headline(self, lost: bool) -> tuple[str, QColor, str]:
        if self._match is not None:
            name = self._match.label if self._match.is_ground else self._match.name
            name = name or match_label(self._match)
            if not self._match.exact:
                # Not an exact multiple of this ore's signature: mark it so a
                # nearest-guess is never mistaken for a confirmation.
                name = f"~{name}"
            color = theme.DIM if lost else theme.rarity_color(self._match.rarity)
            return name.upper(), color, f"×{self._match.count}"
        if self._value is not None:
            return "UNKNOWN", theme.DIM if lost else theme.AMBER, ""
        return "— — —", QColor(72, 86, 102), ""

    def _detail(self) -> str:
        if self._match is not None:
            if self._match.kind == "debris":
                return self._match.secondary or "HULL PANELS / SCRAP METAL"
            if self._match.is_ground:
                minerals = self._match.minerals
                if not minerals:
                    return "SIZE ONLY · MINERAL DEPENDS ON LOCATION"
                return f"{ground_kind(self._match)} · {' / '.join(minerals)}"
            if self._match.kind != "ship":
                # Harvestables, or a kind this panel does not know yet.
                return (self._match.secondary or match_label(self._match)).upper()
            bits = [theme.RARITY_NAME.get(self._match.rarity, "")]
            if self._match.secondary:
                bits.append(self._match.secondary)
            if not self._match.exact:
                bits.append(f"off by {self._match.delta}")
            return "  ·  ".join(b for b in bits if b)
        if self._note:
            return self._note.upper()
        if self._value is not None:
            return "NO KNOWN MINERAL AT THIS SIGNATURE"
        return "WAITING FOR A SCAN"


class MiningPanel(QWidget):
    close_requested = Signal()
    pin_toggled = Signal(bool)      # forwarded from the header's PinButton

    def __init__(self, parent=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(theme.px(PANEL_WIDTH), theme.px(PANEL_HEIGHT))

        self._drag_from = None
        self._scan_sig: tuple | None = None
        self._state = ""
        self._track_state: str | None = None
        self._result: str | None = None
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.px(16), theme.px(12), theme.px(16), theme.px(12))
        root.setSpacing(theme.px(0))

        head = QHBoxLayout()
        head.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        head.setSpacing(theme.px(5))

        self._dot = QWidget()
        self._dot.setFixedSize(theme.px(7), theme.px(7))

        title = QLabel("MINING SCANNER")
        title.setFont(theme.font(8, QFont.Weight.Bold, spacing=1.6))
        title.setStyleSheet(theme.qss("color: rgba(168,184,200,0.95); background: transparent;"))

        self._state_label = QLabel("IDLE")
        self._state_label.setFont(theme.font(7, QFont.Weight.Bold, spacing=1.0))
        self._state_label.setStyleSheet(theme.qss(
            "color: rgba(130,148,166,0.9); background: rgba(255,255,255,0.04);"
            "border-radius: 5px; padding: 2px 5px;"))

        # HUD tracking chip: TRACKING / SEARCHING / FIXED BOX (hidden when
        # the scanner has not reported a tracking state).
        self._track_chip = QLabel("")
        self._track_chip.setFont(theme.font(7, QFont.Weight.Bold, spacing=0.8))
        self._track_chip.hide()

        head.addWidget(self._dot)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._track_chip)
        head.addWidget(self._state_label)
        head.addSpacing(theme.px(2))

        self.pin_button = PinButton()
        self.pin_button.pin_toggled.connect(self.pin_toggled.emit)
        head.addWidget(self.pin_button)

        close = QPushButton("✕")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.setFixedSize(theme.px(18), theme.px(18))
        close.setStyleSheet(theme.qss("""
            QPushButton { color: rgba(150,164,180,0.8); background: transparent;
                          border: none; font-size: 11px; }
            QPushButton:hover { color: #ffd9d9; }
        """))
        close.clicked.connect(self.close_requested.emit)
        head.addWidget(close)
        self._close = close
        root.addLayout(head)
        root.addSpacing(theme.px(6))

        self.verdict = _Verdict()
        root.addWidget(self.verdict)
        root.addStretch(1)

    # ------------------------------------------------------------------
    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        colors = {
            "idle": "rgba(130,148,166,0.9)",
            "reading": theme.AMBER.name(),
            "stable": theme.GOOD.name(),
            "paused": "rgba(130,148,166,0.9)",
            "error": theme.BAD.name(),
        }
        labels = {"idle": "IDLE", "reading": "READING", "stable": "LOCKED",
                  "paused": "PAUSED", "error": "ERROR"}
        self._state_label.setText(labels.get(state, state.upper()))
        self._state_label.setStyleSheet(theme.qss(
            f"color: {colors.get(state, '#8294a6')};"
            "background: rgba(255,255,255,0.04); border-radius: 5px; padding: 2px 5px;"))
        self._dot.setStyleSheet(theme.qss(
            f"background: {colors.get(state, '#8294a6')}; border-radius: 3px;"))

    def set_track_state(self, state: str | None) -> None:
        """Show the HUD tracking chip for ``state`` (theme.TRACK_STATES);
        None hides it."""
        if state is not None and state not in theme.TRACK_COLOR:
            raise ValueError(f"unknown tracking state {state!r}")
        if state == self._track_state:
            return
        self._track_state = state
        if state is None:
            self._track_chip.hide()
            return
        self._track_chip.setText(theme.TRACK_TEXT[state])
        colour = theme.TRACK_COLOR[state]
        self._track_chip.setStyleSheet(theme.qss(
            f"color: {colour.name()}; background: rgba(255,255,255,0.04);"
            f"border: 1px solid rgba({colour.red()},{colour.green()},{colour.blue()},0.45);"
            "border-radius: 5px; padding: 1px 5px;"))
        self._track_chip.show()

    @property
    def track_state(self) -> str | None:
        return self._track_state

    def set_pinned(self, pinned: bool) -> None:
        """Start-up state of the pin (no pin_toggled)."""
        self.pin_button.set_pinned(pinned)

    @property
    def pinned(self) -> bool:
        return self.pin_button.isChecked()

    def set_scan(self, value: int | None, confidence: float, state: str,
                 matches: list[Match], note: str = "") -> None:
        top = matches[0] if matches else None
        alt = alt_match(matches)
        key = (value, round(float(confidence), 2), state,
               (top.kind, top.name, top.count, top.target, top.delta, top.minerals)
               if top else None,
               (alt.kind, alt.name, alt.count) if alt else None, note)
        if key == self._scan_sig:
            return
        self._scan_sig = key
        self.verdict.set_scan(value, confidence, state, top, note, alt)

    def set_scanned(self, value: int | None) -> None:
        """Left label: the number from the latest read; None shows "—"."""
        self.verdict.set_scanned(value)

    def set_result(self, result: str | None) -> None:
        """Result border: "match" green, "nomatch" yellow, "noread" red;
        None is the plain thin edge."""
        if result is not None and result not in RESULTS:
            raise ValueError(f"unknown result {result!r}")
        if result == self._result:
            return
        self._result = result
        self.update()

    @property
    def result(self) -> str | None:
        return self._result

    def result_colour(self) -> QColor | None:
        return {"match": theme.GOOD, "nomatch": theme.AMBER,
                "noread": theme.BAD}.get(self._result or "")

    @property
    def scanned_text(self) -> str:
        return f"SCANNED SIGNATURE {self.verdict.scanned_value_text()}"

    @property
    def matched_text(self) -> str:
        return f"MATCHED SIGNATURE {self.verdict.matched_value_text()}"

    @property
    def read_text(self) -> str:
        return self.verdict.read_text()

    @property
    def alt_text(self) -> str:
        return self.verdict.alt_text()

    def set_scan_idle(self, note: str = "") -> None:
        self.set_scan(None, 0.0, "idle", [], note)

    def reset_cache(self) -> None:
        """Force the next update to repaint even if the value is identical."""
        self._scan_sig = None

    # ------------------------------------------------------------------
    def place_default(self) -> None:
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        self.move(geo.right() - self.width() - 40, geo.top() + 110)

    def clamp_to_screen(self) -> None:
        screen = QGuiApplication.screenAt(self.geometry().center()) \
            or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = min(max(self.x(), geo.left() - 20), geo.right() - self.width() + 20)
        y = min(max(self.y(), geo.top()), geo.bottom() - 60)
        self.move(x, y)

    # ------------------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < theme.px(40):
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_from is not None:
            self._drag_from = None
            self.clamp_to_screen()

    # ------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        p, w, h = theme.paint(self)
        theme.paint_card(p, QRectF(0, 0, w, h), radius=12)
        colour = self.result_colour()
        if colour is None:
            p.setPen(QPen(QColor(79, 209, 224, 90), 1.0))
            p.drawLine(16, 1, w - 16, 1)
            return
        # Thick result border just inside the card edge; the painter is
        # pre-scaled, so this is theme.px(RESULT_BORDER) on screen.
        half = RESULT_BORDER / 2.0
        p.setPen(QPen(colour, RESULT_BORDER))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(theme.card_path(QRectF(half, half, w - RESULT_BORDER, h - RESULT_BORDER),
                                   12 - half))
