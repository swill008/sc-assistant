"""LOG: a small always-on-top window that shows the newest lines of a log
file and follows it while open."""
from __future__ import annotations

import html
import os
import re
from collections import deque
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette, QPen
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from . import theme

WIDTH = 640
HEIGHT = 420
MAX_LINES = 2000
POLL_MS = 1000
# The first read takes at most this much from the end of the file; 2,000
# lines of app.log are far smaller.
TAIL_BYTES = 1024 * 1024

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_RANK = {name: i for i, name in enumerate(LEVELS)}
# "2026-11-01 17:50:02.510 WARNING app.notes: message"
_LEVEL_RE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:[.,]\d+)? (DEBUG|INFO|WARNING|ERROR|CRITICAL)\b")

FILTERS = ("ALL", "WARNING+", "ERROR")
_FILTER_MIN = {"ALL": 0, "WARNING+": _RANK["WARNING"], "ERROR": _RANK["ERROR"]}

_LEVEL_COLOR = {
    "DEBUG": QColor(110, 126, 142),
    "INFO": QColor(200, 212, 224),
    "WARNING": theme.AMBER,
    "ERROR": theme.BAD,
    "CRITICAL": theme.BAD,
}


def line_level(text: str, previous: str = "INFO") -> str:
    """Level of one log line; a line without a stamp (a traceback line)
    belongs to the entry above it."""
    m = _LEVEL_RE.match(text)
    return m.group(1) if m else previous


def _chip(text: str, checkable: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setFixedHeight(theme.px(24))
    button.setStyleSheet(theme.qss("""
        QPushButton {
            color: rgba(130,148,166,0.9); background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.06); border-radius: 5px;
            font-size: 7px; font-weight: 600;
            letter-spacing: 0.8px; padding: 0 8px;
        }
        QPushButton:hover { color: #d6e2ee; border-color: rgba(79,209,224,0.35); }
        QPushButton:checked {
            color: #4fd1e0; background: rgba(79,209,224,0.13);
            border-color: rgba(79,209,224,0.5);
        }
    """))
    return button


class LogViewer(QWidget):
    close_requested = Signal()
    open_file = Signal(Path)

    def __init__(self, path: Path | None = None, parent=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(theme.px(WIDTH), theme.px(HEIGHT))

        self._path: Path | None = None
        self._lines: deque[tuple[str, str]] = deque(maxlen=MAX_LINES)  # (level, text)
        self._offset = 0              # bytes of the file already read
        self._file_id = None          # (st_ino, st_dev): changes on rotation
        self._partial = b""           # a line still being written
        self._filter = "ALL"
        self._follow = True
        self._drag_from = None

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)

        self._build()
        if path is not None:
            self.set_path(path)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.px(16), theme.px(12), theme.px(16), theme.px(10))
        root.setSpacing(theme.px(6))

        head = QHBoxLayout()
        head.setSpacing(theme.px(8))
        self.title = QLabel("LOG")
        self.title.setFont(theme.font(9, QFont.Weight.Bold, spacing=1.8))
        self.title.setStyleSheet(theme.qss(
            "color: rgba(168,184,200,0.95); background: transparent;"))

        self.status = QPushButton("LIVE")
        self.status.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.status.setFont(theme.font(7, QFont.Weight.Bold, spacing=1.0))
        self.status.setToolTip("Following new lines; scroll up to pause, click to jump to the end")
        self.status.clicked.connect(self.scroll_to_end)

        self._close = QPushButton("✕")
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._close.setFixedSize(theme.px(22), theme.px(22))
        self._close.setStyleSheet(theme.qss("""
            QPushButton { color: rgba(150,164,180,0.8); background: transparent;
                          border: none; font-size: 12px; }
            QPushButton:hover { color: #ffd9d9; }
        """))
        self._close.clicked.connect(self.close_requested.emit)

        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.status)
        head.addWidget(self._close)
        root.addLayout(head)

        tools = QHBoxLayout()
        tools.setSpacing(theme.px(6))
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.filter_buttons: dict[str, QPushButton] = {}
        for name in FILTERS:
            btn = _chip(name, checkable=True)
            btn.setChecked(name == self._filter)
            btn.clicked.connect(lambda _=False, n=name: self.set_level_filter(n))
            self._group.addButton(btn)
            self.filter_buttons[name] = btn
            tools.addWidget(btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter text…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedHeight(theme.px(24))
        self.search.setFont(theme.font(8))
        self.search.setStyleSheet(theme.qss("""
            QLineEdit {
                color: #e8f0f8; background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.10); border-radius: 5px;
                padding: 0 6px; font-size: 8px;
                selection-background-color: rgba(79,209,224,0.35);
            }
            QLineEdit:focus { border-color: rgba(79,209,224,0.65); }
        """))
        palette = self.search.palette()
        palette.setColor(QPalette.ColorRole.Text, theme.TEXT)
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(120, 137, 155))
        self.search.setPalette(palette)
        self.search.textChanged.connect(lambda _t: self._rebuild())
        tools.addWidget(self.search, 1)

        self.copy_btn = _chip("COPY")
        self.copy_btn.setToolTip("Copy the lines shown to the clipboard")
        self.copy_btn.clicked.connect(self.copy_visible)
        tools.addWidget(self.copy_btn)

        self.open_btn = _chip("OPEN FILE")
        self.open_btn.setToolTip("Open the log file in your text editor")
        self.open_btn.clicked.connect(self._on_open_file)
        tools.addWidget(self.open_btn)
        root.addLayout(tools)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.view.setFont(theme.font(8, family="Consolas" if theme.IS_WINDOWS else "Menlo"))
        self.view.setStyleSheet(theme.qss("""
            QPlainTextEdit {
                color: #c8d4e0; background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08); border-radius: 7px;
                padding: 4px 6px;
                selection-background-color: rgba(79,209,224,0.35);
            }
            QScrollBar:vertical, QScrollBar:horizontal { background: transparent; }
            QScrollBar:vertical { width: 7px; }
            QScrollBar:horizontal { height: 7px; }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background: rgba(79,209,224,0.22); border-radius: 3px; }
            QScrollBar::handle:vertical { min-height: 26px; }
            QScrollBar::handle:horizontal { min-width: 26px; }
            QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
            QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
        """))
        self.view.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.view.verticalScrollBar().rangeChanged.connect(self._on_range)
        root.addWidget(self.view, 1)

        self.footer = QLabel("")
        self.footer.setFont(theme.font(6, QFont.Weight.Medium, spacing=0.4))
        self.footer.setStyleSheet(theme.qss(
            "color: rgba(112,128,144,0.95); background: transparent;"))
        root.addWidget(self.footer)
        self._set_status()

    # -- file ------------------------------------------------------------
    @property
    def path(self) -> Path | None:
        return self._path

    def set_path(self, path: Path) -> None:
        """Show the newest lines of path and follow it from now on."""
        self._path = Path(path)
        self.footer.setToolTip(str(self._path))
        self.reload()

    def reload(self) -> None:
        """Read the file again from its last TAIL_BYTES (first open, rotation)."""
        self._lines.clear()
        self._offset = 0
        self._partial = b""
        self._file_id = None
        stat = self._stat()
        if stat is not None:
            self._file_id = (stat.st_ino, stat.st_dev)
            start = max(0, stat.st_size - TAIL_BYTES)
            data = self._read_from(start)
            if start and data is not None:
                # Drop the cut first line.
                cut = data.find(b"\n")
                data = data[cut + 1:] if cut >= 0 else b""
            self._take(data or b"")
        self._follow = True
        self._rebuild()

    def poll(self) -> None:
        """Reads only the bytes written since the last poll (timer, 1 s)."""
        if self._path is None:
            return
        stat = self._stat()
        if stat is None:
            if self._file_id is not None or self._lines:
                self.reload()           # the file went away
            return
        file_id = (stat.st_ino, stat.st_dev)
        if (self._file_id is None or file_id != self._file_id
                or stat.st_size < self._offset):
            self.reload()               # new file, rotated or truncated
            return
        if stat.st_size == self._offset:
            return
        data = self._read_from(self._offset)
        if not data:
            return
        added = self._take(data)
        self._append(added)

    def _stat(self) -> os.stat_result | None:
        try:
            return os.stat(self._path) if self._path is not None else None
        except OSError:
            return None

    def _read_from(self, offset: int) -> bytes | None:
        try:
            with open(self._path, "rb") as fh:
                fh.seek(offset)
                data = fh.read()
        except OSError:
            return None
        self._offset = offset + len(data)
        return data

    def _take(self, data: bytes) -> list[tuple[str, str]]:
        """Adds whole lines from data; keeps an unfinished last line back."""
        data = self._partial + data
        parts = data.split(b"\n")
        self._partial = parts.pop()
        previous = self._lines[-1][0] if self._lines else "INFO"
        added = []
        for raw in parts:
            text = raw.decode("utf-8", errors="replace").rstrip("\r")
            previous = line_level(text, previous)
            entry = (previous, text)
            self._lines.append(entry)
            added.append(entry)
        return added

    # -- filters ---------------------------------------------------------
    def set_level_filter(self, name: str) -> None:
        if name not in FILTERS:
            raise ValueError(f"unknown level filter {name!r}")
        self._filter = name
        self.filter_buttons[name].setChecked(True)
        self._rebuild()

    @property
    def level_filter(self) -> str:
        return self._filter

    def set_text_filter(self, text: str) -> None:
        self.search.setText(text)

    def _passes(self, entry: tuple[str, str]) -> bool:
        level, text = entry
        if _RANK.get(level, 1) < _FILTER_MIN[self._filter]:
            return False
        needle = self.search.text().strip().casefold()
        return not needle or needle in text.casefold()

    def visible_lines(self) -> list[str]:
        return [entry[1] for entry in self._lines if self._passes(entry)]

    # -- view ------------------------------------------------------------
    @staticmethod
    def _html(entry: tuple[str, str]) -> str:
        level, text = entry
        c = _LEVEL_COLOR.get(level, theme.TEXT)
        return (f'<span style="color: rgb({c.red()},{c.green()},{c.blue()}); '
                f'white-space: pre;">{html.escape(text) or "&nbsp;"}</span>')

    def _rebuild(self) -> None:
        bar = self.view.verticalScrollBar()
        keep = bar.value()
        follow = self._follow
        self.view.clear()
        shown = [e for e in self._lines if self._passes(e)]
        if shown:
            self.view.appendHtml("<br>".join(self._html(e) for e in shown))
        elif self._path is not None and self._stat() is None:
            self.view.setPlaceholderText(f"No log yet: {self._path}")
        else:
            self.view.setPlaceholderText("No lines match." if self._lines else "The log is empty.")
        self._follow = follow
        if follow:
            self.scroll_to_end()
        else:
            bar.setValue(min(keep, bar.maximum()))
        self._update_footer()

    def _append(self, added: list[tuple[str, str]]) -> None:
        if len(self._lines) == MAX_LINES and added:
            # Old lines fell off the front: redraw so the view matches.
            self._rebuild()
            return
        shown = [e for e in added if self._passes(e)]
        if shown:
            bar = self.view.verticalScrollBar()
            keep = bar.value()
            follow = self._follow
            for entry in shown:
                self.view.appendHtml(self._html(entry))
            self._follow = follow
            if follow:
                self.scroll_to_end()
            else:
                bar.setValue(keep)
        self._update_footer()

    def scroll_to_end(self) -> None:
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._follow = True
        self._set_status()

    @property
    def following(self) -> bool:
        return self._follow

    def _on_scrolled(self, value: int) -> None:
        bar = self.view.verticalScrollBar()
        self._follow = value >= bar.maximum() - 2
        self._set_status()

    def _on_range(self, _lo: int, hi: int) -> None:
        if self._follow:
            self.view.verticalScrollBar().setValue(hi)

    def _set_status(self) -> None:
        live = self._follow
        self.status.setText("LIVE" if live else "PAUSED")
        color = theme.GOOD if live else theme.AMBER
        self.status.setStyleSheet(theme.qss(
            f"QPushButton {{ color: rgba({color.red()},{color.green()},{color.blue()},0.95);"
            "background: rgba(255,255,255,0.04); border: none;"
            "border-radius: 5px; padding: 2px 6px; }"))

    def _update_footer(self) -> None:
        if self._path is None:
            self.footer.setText("NO FILE")
            return
        shown = len(self.visible_lines())
        total = len(self._lines)
        parts = [self._path.name, f"{total:,} LINES"]
        if shown != total:
            parts.append(f"{shown:,} SHOWN")
        parts.append("NEWEST 2,000" if total >= MAX_LINES else "FOLLOWS NEW LINES")
        self.footer.setText(" · ".join(parts))

    # -- actions ---------------------------------------------------------
    def copy_visible(self) -> str:
        text = "\n".join(self.visible_lines())
        QGuiApplication.clipboard().setText(text)
        return text

    def _on_open_file(self) -> None:
        if self._path is not None:
            self.open_file.emit(self._path)

    # ------------------------------------------------------------------
    def place_default(self, anchor: QWidget | None = None) -> None:
        geo = QGuiApplication.primaryScreen().availableGeometry()
        if anchor is not None and anchor.isVisible():
            x = anchor.x() + anchor.width() + 12
            y = anchor.y()
            if x + self.width() > geo.right() - 8:
                x = max(geo.left() + 8, geo.right() - self.width() - 8)
            if y + self.height() > geo.bottom() - 8:
                y = max(geo.top() + 8, geo.bottom() - self.height() - 8)
            self.move(max(geo.left() + 8, x), y)
        else:
            self.move(geo.center().x() - self.width() // 2, geo.top() + 90)

    def clamp_to_screen(self) -> None:
        screen = QGuiApplication.screenAt(self.geometry().center()) \
            or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = min(max(self.x(), geo.left() - 20), geo.right() - self.width() + 20)
        y = min(max(self.y(), geo.top()), geo.bottom() - 60)
        self.move(x, y)

    # ------------------------------------------------------------------
    def showEvent(self, event):  # noqa: N802
        if self._path is not None:
            self.poll()
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if (event.button() == Qt.MouseButton.LeftButton
                and event.position().y() < theme.px(34)):
            self._drag_from = (event.globalPosition().toPoint()
                               - self.frameGeometry().topLeft())
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if (self._drag_from is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_from)
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_from is not None:
            self._drag_from = None
            self.clamp_to_screen()

    def paintEvent(self, event):  # noqa: N802
        p, w, h = theme.paint(self)
        theme.paint_card(p, QRectF(0, 0, w, h), radius=14,
                         fill=QColor(10, 14, 20, 250))
        p.setPen(QPen(QColor(79, 209, 224, 90), 1.0))
        p.drawLine(16, 1, w - 16, 1)
