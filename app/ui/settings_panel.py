"""Settings window: collapsible groups (scanner, scan data, hotkeys, look &
sound, voice, update & reset, debug)."""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import (QEvent, QObject, QPoint, QRectF, Qt, QThread, QTimer,
                            QUrl, Signal)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QGuiApplication,
                           QImage, QKeyEvent, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QSlider, QVBoxLayout,
                               QWidget)

from .. import tts, updater
from ..tts import phrases
from ..version import APP_NAME, VERSION
from ..version import label as build_label
from . import theme
from .pin_button import PinButton

PREVIEW_HEIGHT = 132      # design px: a whole signature window fits

WIDTH = 384


# Collapsible groups, top to bottom. The ids are saved in config
# ("settings_open"), so they never change.
SECTION_HEADINGS = (
    ("scanner", "SCANNER"),
    ("scan_data", "SCAN DATA"),
    ("hotkeys", "HOTKEYS"),
    ("look", "LOOK & SOUND"),
    ("voice", "VOICE"),
    ("update", "UPDATE & RESET"),
    ("debug", "DEBUG"),
)
SECTION_IDS = tuple(section_id for section_id, _ in SECTION_HEADINGS)


log = logging.getLogger(__name__)

def _section(text: str) -> QLabel:
    """Small sub-heading inside a group."""
    label = QLabel(text.upper())
    label.setFont(theme.font(8, QFont.Weight.Bold, spacing=1.4))
    label.setStyleSheet(theme.qss("color: rgba(136,152,170,0.98); background: transparent;"))
    return label


class _ClickFocus(QObject):
    """App-wide filter for the Settings window.

    - With "take focus" on (the tick box next to the pin; off by default), a
      mouse press on Settings or any of its controls activates the window
      before the control handles the press.
    - When one of its drop-downs closes, updates held back while it was open
      are applied (see _held_while_dropdown).
    """

    # Traced while a drop-down is open (DETAILED LOG): what happens to
    # Settings between a drop-down opening and closing.
    _TRACED = (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.WindowActivate,
               QEvent.Type.WindowDeactivate, QEvent.Type.LayoutRequest)

    def __init__(self, panel: QWidget) -> None:
        super().__init__(panel)
        self._panel = panel
        self.enabled = False
        self._opened_at: float | None = None

    def eventFilter(self, obj, event):  # noqa: N802
        kind = event.type()
        if (kind == QEvent.Type.MouseButtonPress and self.enabled
                and isinstance(obj, QWidget) and obj.window() is self._panel):
            self._panel.activateWindow()
            self._panel.raise_()
        elif kind in (QEvent.Type.Show, QEvent.Type.Hide) and isinstance(obj, QWidget) \
                and obj in self._panel._dropdown_popups():
            now = time.monotonic()
            if kind == QEvent.Type.Show:
                self._opened_at = now
                log.debug("settings drop-down opened (settings active: %s, app state: %s)",
                          self._panel.isActiveWindow(),
                          QApplication.instance().applicationState().name)
            else:
                open_for = now - self._opened_at if self._opened_at else -1.0
                self._opened_at = None
                log.debug("settings drop-down closed after %.2f s (settings active: %s, app state: %s)",
                          open_for, self._panel.isActiveWindow(),
                          QApplication.instance().applicationState().name)
                if self._panel._held:
                    QTimer.singleShot(0, self._panel._flush_held)
        elif (self._opened_at is not None and kind in self._TRACED
                and (obj is self._panel or kind == QEvent.Type.ApplicationStateChange)):
            log.debug("  while open: %s on Settings", kind.name)
        elif (self._opened_at is not None and isinstance(obj, QWidget) and obj.isWindow()
                and obj is not self._panel and obj not in self._panel._dropdown_popups()
                and kind in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.WindowActivate,
                             QEvent.Type.WindowDeactivate, QEvent.Type.Close)):
            log.debug("  while open: %s on another window %s (%r)", kind.name,
                      type(obj).__name__, obj.windowTitle() or obj.objectName())
        elif self._opened_at is not None and kind == QEvent.Type.ApplicationStateChange:
            log.debug("  while open: app state -> %s",
                      QApplication.instance().applicationState().name)
        return False


def _held_while_dropdown(method):
    """Hold back a Settings update while one of its drop-downs is open.

    A line that changes height moves the controls below it, and Qt closes an
    open drop-down whose box moves (measured 2026-11-01: a label growing one
    line closed it; focus and the stay-on-top timer did not). The newest call
    per setter is kept and applied when the drop-down closes.
    """
    name = method.__name__

    def wrapper(self, *args, **kwargs):
        if self._dropdown_open():
            self._held[name] = (args, kwargs)
            return None
        return method(self, *args, **kwargs)

    wrapper.__name__ = name
    wrapper.__doc__ = method.__doc__
    wrapper.__wrapped__ = method
    return wrapper


class _ProgressBar(QWidget):
    """Thin download bar under a progress line (user, 2026-11-01): full width,
    cyan fill on a dim track, the style of the scanner card's READ bar."""

    HEIGHT = 3          # design px

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fraction = 0.0
        self.setFixedHeight(theme.px(self.HEIGHT))
        self.hide()

    @property
    def fraction(self) -> float:
        return self._fraction

    def set_progress(self, got: int, total: int) -> None:
        """Show got/total (0..1); hidden when the total is unknown."""
        if total and total > 0:
            self._fraction = max(0.0, min(1.0, float(got) / float(total)))
            self.show()
            self.update()
        else:
            self.hide()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        r = self.rect()
        radius = r.height() / 2
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(r), radius, radius)
        if self._fraction > 0:
            p.setBrush(theme.ACCENT)
            p.drawRoundedRect(QRectF(0, 0, max(r.height(), r.width() * self._fraction), r.height()),
                              radius, radius)
        p.end()


class _SectionHeader(QWidget):
    """Clickable group heading: "▸ NAME" closed, "▾ NAME" open, and a grey
    summary on the right while closed."""

    clicked = Signal()

    def __init__(self, heading: str, parent=None):
        super().__init__(parent)
        self._heading = heading
        self._summary = ""
        self._open = False
        self._locked = False
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.px(0), theme.px(5), theme.px(0), theme.px(3))
        row.setSpacing(theme.px(10))
        self.title = QLabel()
        self.title.setFont(theme.font(9, QFont.Weight.Bold, spacing=1.6))
        self.summary = QLabel()
        self.summary.setFont(theme.font(7))
        self.summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.summary.setStyleSheet(theme.qss(
            "color: rgba(130,148,166,0.85); background: transparent;"))
        # Ignored: a long summary is elided instead of widening the window.
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.summary.setMinimumWidth(0)
        row.addWidget(self.title)
        row.addWidget(self.summary, 1)
        self._refresh()

    @property
    def summary_text(self) -> str:
        """The full summary (the label may show it elided)."""
        return self._summary

    def set_state(self, opened: bool, locked: bool) -> None:
        self._open, self._locked = bool(opened), bool(locked)
        self._refresh()

    def set_summary(self, text: str) -> None:
        self._summary = str(text or "")
        self._elide()

    def _refresh(self) -> None:
        self.title.setText(f"{'▾' if self._open else '▸'} {self._heading}")
        color = "#e6f7fa" if self._hover and not self._locked else "rgba(168,184,200,0.95)"
        self.title.setStyleSheet(theme.qss(f"color: {color}; background: transparent;"))
        self.summary.setVisible(not self._open)
        self.setToolTip("Open until a capture box is drawn" if self._locked else "")
        self._elide()

    def _elide(self) -> None:
        width = self.summary.width()
        text = self.summary.fontMetrics().elidedText(
            self._summary, Qt.TextElideMode.ElideRight, max(0, width))
        self.summary.setText(text)
        self.summary.setToolTip(self._summary if text != self._summary else "")

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self._refresh()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self._refresh()
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        # Accepted, so a press here never starts the window drag.
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        event.accept()
        if (event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()

    def paintEvent(self, event):  # noqa: N802
        # A faint divider above each heading.
        p = QPainter(self)
        p.setPen(QPen(QColor(79, 209, 224, 34), 1.0))
        p.drawLine(0, 0, self.width(), 0)
        p.end()


class _UpdateWorker(QThread):
    """Check or apply on a thread: both touch the network."""

    # mode, value, extra:
    #   check   -> published version, release notes ("" when none)
    #   install -> downloaded Setup.exe, the version it holds
    #   apply   -> installed version, ""
    done = Signal(str, str, str)
    failed = Signal(str)
    progress = Signal(int, int)       # install: bytes so far, total (0 = unknown)

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        self._mode = mode

    def run(self) -> None:  # noqa: D102
        try:
            if self._mode == "check":
                published, notes = updater.check()
                self.done.emit("check", published, notes)
            elif updater.is_frozen():
                # Installed EXE: fetch the release's Setup.exe; the app runs it.
                got = updater.download_setup(cancelled=self.isInterruptionRequested,
                                             progress=self.progress.emit)
                self.done.emit("install", str(got.path), str(got.version))
            else:
                self.done.emit("apply", updater.apply(), "")
        except Exception as exc:      # surface it, never take the app down
            self.failed.emit(str(exc))


def _mb(count: int) -> int:
    """Whole megabytes (1 MB = 1,048,576 bytes)."""
    return max(0, int(count)) // (1 << 20)


def _percent(got: int, total: int) -> int:
    return min(100, max(0, int(got)) * 100 // max(1, int(total)))


def download_text(version: str, got: int, total: int) -> str:
    """The UPDATE line while Setup.exe downloads; total 0 means unknown size."""
    if total > 0:
        return (f"Downloading v{version} · {_percent(got, total)}% · "
                f"{_mb(got)} of {_mb(total)} MB")
    return f"Downloading v{version} · {_mb(got)} MB"


def _slider() -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 100)
    slider.setFixedHeight(theme.px(20))
    slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    slider.setCursor(Qt.CursorShape.PointingHandCursor)
    slider.setStyleSheet(theme.qss("""
        QSlider::groove:horizontal {
            height: 4px; background: rgba(79,209,224,0.18);
            border-radius: 2px;
        }
        QSlider::sub-page:horizontal {
            background: rgba(79,209,224,0.75); border-radius: 2px;
        }
        QSlider::handle:horizontal {
            width: 12px; margin: -5px 0; border-radius: 6px;
            background: #4fd1e0;
        }
        QSlider::handle:horizontal:disabled {
            background: rgba(130,148,166,0.5);
        }
        QSlider::sub-page:horizontal:disabled {
            background: rgba(79,209,224,0.20);
        }
    """))
    return slider


def _combo() -> QComboBox:
    """A drop-down list for the VOICE rows: never wider than its row (long
    names are elided); the open list is as wide as its longest entry."""
    box = QComboBox()
    box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    box.setCursor(Qt.CursorShape.PointingHandCursor)
    box.setFixedHeight(theme.px(24))
    box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    box.setMinimumContentsLength(8)
    box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    box.setStyleSheet(theme.qss("""
        QComboBox {
            color: rgba(200,214,228,0.95); background: rgba(79,209,224,0.06);
            border: 1px solid rgba(79,209,224,0.18); border-radius: 6px;
            padding: 0 8px; font-size: 8px;
        }
        QComboBox:hover { background: rgba(79,209,224,0.12); }
        QComboBox:disabled { color: rgba(130,148,166,0.55); }
        QComboBox::drop-down { border: none; width: 16px; }
        QComboBox QAbstractItemView {
            color: rgba(200,214,228,0.95); background: rgb(14,20,28);
            selection-background-color: rgba(79,209,224,0.25);
            border: 1px solid rgba(79,209,224,0.25);
        }
    """))
    return box


def _fit_popup(box: QComboBox) -> None:
    """Let the open list show whole entries (it may be wider than the box)."""
    view = box.view()
    view.setTextElideMode(Qt.TextElideMode.ElideNone)
    view.setMinimumWidth(view.sizeHintForColumn(0) + theme.px(24))


# Short engine names for the closed VOICE heading, and the grey note under
# the menu per engine (licence, online).
ENGINE_SHORT = {"windows": "Windows", "piper": "Piper", "kokoro": "Kokoro",
                "edge": "Microsoft online"}
ENGINE_NOTES = {
    "windows": "",
    "piper": "Add-on, GPL-3.0: downloaded on demand, not part of SC Assistant. "
             "Voices: public domain, CC0 or CC-BY only.",
    "kokoro": "Add-on, GPL-3.0: downloaded on demand, not part of SC Assistant. "
              "Uses more CPU than the others.",
    "edge": "Online: sends the phrase to Microsoft. If it fails, a Windows "
            "voice speaks instead.",
}
VOICE_NAME_ROLE = Qt.ItemDataRole.UserRole + 1     # voice name, for the summary

SPEED_MIN, SPEED_MAX = 5, 20     # SPEED slider in tenths: 0.5× - 2.0×


def speed_text(speed: float) -> str:
    """1.0 -> '1.0×'."""
    return f"{float(speed):.1f}×"


def _size_mb(count: int) -> str:
    """MB with one decimal below 10 MB (Kokoro voices are under 1 MB)."""
    mb = max(0, int(count)) / (1 << 20)
    return f"{mb:.1f}" if mb < 10 else f"{int(mb)}"


def voice_download_text(got: int, total: int) -> str:
    """The VOICE download line: 'NN% · got of total MB' (total 0 = unknown)."""
    if total > 0:
        return f"{_percent(got, total)}% · {_size_mb(got)} of {_size_mb(total)} MB"
    return f"{_size_mb(got)} MB"


TRACKING_MAX = 800     # px each side at 2160 px high
TRACKING_STEP = 50


def _snap_tracking(value) -> int:
    value = max(0, min(TRACKING_MAX, int(value)))
    return int(round(value / TRACKING_STEP)) * TRACKING_STEP


def _tracking_text(value: int) -> str:
    return f"±{value} px" if value > 0 else "OFF"


# Hotkey rows: (key in the hotkeys dict, row label). Tool rows follow, from
# set_tools(); their keys go under "tools".
HOTKEY_ROWS = (("toggle_nav", "SHOW BAR"), ("panic", "HIDE ALL"))
VK_ESCAPE = 0x1B

_VK_NAMES = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "Caps Lock",
    0x20: "Space", 0x21: "Page Up", 0x22: "Page Down", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2C: "Print Screen",
    0x2D: "Insert", 0x2E: "Delete", 0x6A: "Num *", 0x6B: "Num +", 0x6D: "Num -",
    0x6E: "Num .", 0x6F: "Num /", 0x90: "Num Lock", 0x91: "Scroll Lock",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
    0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}
# Qt keys for when the platform gives no virtual-key code.
def _k(key) -> int:
    return int(getattr(key, "value", key))


_QT_TO_VK = {_k(key): vk for key, vk in (
    (Qt.Key.Key_Backspace, 0x08), (Qt.Key.Key_Tab, 0x09), (Qt.Key.Key_Return, 0x0D),
    (Qt.Key.Key_Enter, 0x0D), (Qt.Key.Key_Pause, 0x13), (Qt.Key.Key_Space, 0x20),
    (Qt.Key.Key_PageUp, 0x21), (Qt.Key.Key_PageDown, 0x22), (Qt.Key.Key_End, 0x23),
    (Qt.Key.Key_Home, 0x24), (Qt.Key.Key_Left, 0x25), (Qt.Key.Key_Up, 0x26),
    (Qt.Key.Key_Right, 0x27), (Qt.Key.Key_Down, 0x28), (Qt.Key.Key_Insert, 0x2D),
    (Qt.Key.Key_Delete, 0x2E), (Qt.Key.Key_ScrollLock, 0x91),
)}
# Modifiers alone are not hotkeys (RegisterHotKey is called with no modifier).
_MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


def vk_name(vk: int) -> str:
    """Short name of a Windows virtual-key code; "—" for none."""
    vk = int(vk or 0)
    if vk <= 0:
        return "—"
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return f"Num {vk - 0x60}"
    return _VK_NAMES.get(vk, f"Key {vk:#04x}")


def key_event_vk(event: QKeyEvent) -> int:
    """Windows virtual-key code of a key press (0 when unknown)."""
    vk = int(event.nativeVirtualKey() or 0)
    if vk:
        return vk
    key = _k(event.key())
    if _k(Qt.Key.Key_F1) <= key <= _k(Qt.Key.Key_F24):
        return 0x70 + key - _k(Qt.Key.Key_F1)
    if _k(Qt.Key.Key_0) <= key <= _k(Qt.Key.Key_9) or _k(Qt.Key.Key_A) <= key <= _k(Qt.Key.Key_Z):
        return key
    return _QT_TO_VK.get(key, 0)


class _KeyButton(QPushButton):
    """Shows a key; click, then press a key to choose it (Esc = none)."""

    captured = Signal(int)       # VK code, 0 = none

    def __init__(self, parent=None):
        super().__init__(parent)
        self._vk = 0
        self._capturing = False
        self.clicked.connect(self._toggle_capture)
        self._refresh()

    @property
    def vk(self) -> int:
        return self._vk

    @property
    def capturing(self) -> bool:
        return self._capturing

    def set_vk(self, vk: int) -> None:
        self._vk = max(0, int(vk or 0))
        self._refresh()

    def cancel_capture(self) -> None:
        if self._capturing:
            self._capturing = False
            self.releaseKeyboard()
            self._refresh()

    def _toggle_capture(self) -> None:
        if self._capturing:
            self.cancel_capture()
            return
        self._capturing = True
        self.setText("PRESS A KEY…")
        # The panel never takes focus by itself (it must not steal it from
        # the game), so take the keyboard only while a key is being chosen.
        window = self.window()
        if window.isVisible():
            window.activateWindow()
            self.grabKeyboard()

    def _refresh(self) -> None:
        self.setText(vk_name(self._vk))

    def keyPressEvent(self, event):  # noqa: N802
        if not self._capturing:
            super().keyPressEvent(event)
            return
        event.accept()
        if event.isAutoRepeat():
            return
        escape = _k(event.key()) == _k(Qt.Key.Key_Escape)
        vk = 0 if escape else key_event_vk(event)
        if vk == VK_ESCAPE:
            vk, escape = 0, True
        if vk in _MODIFIER_VKS:
            return                   # wait for a real key
        if not escape and vk == 0:
            return                   # a key Windows cannot register
        self.cancel_capture()
        self.captured.emit(vk)


def _button(text: str, checkable: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setCheckable(checkable)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setFixedHeight(theme.px(28))
    btn.setStyleSheet(_button_qss())
    return btn


def _button_qss() -> str:
    return theme.qss("""
        QPushButton {
            color: rgba(168,184,200,0.95); background: rgba(79,209,224,0.06);
            border: 1px solid rgba(79,209,224,0.18); border-radius: 7px;
            font-size: 8px; font-weight: 600;
            letter-spacing: 1.0px; padding: 0 10px;
        }
        QPushButton:hover { background: rgba(79,209,224,0.14); color: #e6f7fa; }
        QPushButton:checked {
            background: rgba(79,209,224,0.22); color: #4fd1e0;
            border-color: rgba(79,209,224,0.55);
        }
        QPushButton:disabled {
            color: rgba(130,148,166,0.55); background: rgba(79,209,224,0.03);
            border-color: rgba(79,209,224,0.10);
        }
    """)


class SettingsPanel(QWidget):
    region_requested = Signal()
    pause_toggled = Signal(bool)
    debug_toggled = Signal(bool)
    reload_requested = Signal()
    close_requested = Signal()
    voice_toggled = Signal(bool)
    volume_changed = Signal(int)
    opacity_changed = Signal(int)
    capture_toggled = Signal(bool)
    ui_scale_changed = Signal(int)
    restart_requested = Signal()
    install_requested = Signal(str)   # downloaded Setup.exe to run after quitting
    monitor_changed = Signal(str)     # Qt screen name of the game monitor
    reads_changed = Signal(int)       # scans per second, 1-8
    outline_toggled = Signal(bool)    # draw the capture box on screen
    tracking_changed = Signal(int)    # HUD tracking range in px, 0 = off;
                                      # once per change (on slider release)
    hotkeys_changed = Signal(dict)    # {"toggle_nav": vk, "panic": vk, "tools": {id: vk}}
    pin_toggled = Signal(bool)        # the header pin, user clicks only
    take_focus_toggled = Signal(bool)   # the FOCUS tick box next to the pin, user clicks only
    reset_requested = Signal()        # RESET SETTINGS, second click
    open_unmatched_folder = Signal()  # UNMATCHED READINGS -> OPEN FOLDER
    clear_unmatched = Signal()        # UNMATCHED READINGS -> CLEAR, second click
    sections_changed = Signal(list)   # open group ids (SECTION_IDS order), user clicks only
    history_toggled = Signal(bool)    # DEBUG -> SCAN HISTORY switch, user clicks only
    bad_reads_toggled = Signal(bool)  # DEBUG -> SAVE BAD READS switch, user clicks only
    open_history = Signal()           # DEBUG -> OPEN HISTORY
    open_bad_reads = Signal()         # DEBUG -> OPEN FOLDER
    detailed_log_toggled = Signal(bool)  # DEBUG -> DETAILED LOG switch, user clicks only
    open_log = Signal()               # DEBUG -> OPEN LOG
    view_log = Signal()               # DEBUG -> VIEW LOG
    export_diagnostics = Signal()     # DEBUG -> EXPORT DIAGNOSTICS
    # VOICE group, user choices only (the set_voice_* setters emit nothing).
    voice_engine_changed = Signal(str)   # ENGINE id (app.tts.ENGINE_IDS)
    voice_choice_changed = Signal(str)   # VOICE id within the engine
    voice_speed_changed = Signal(float)  # SPEED 0.5-2.0
    voice_style_changed = Signal(str)    # SAYS id (app.tts.phrases.STYLES)
    voice_download_requested = Signal()  # DOWNLOAD
    voice_download_cancelled = Signal()  # CANCEL while downloading
    voice_test_requested = Signal()      # TEST

    # Two-click buttons (like QUIT on the nav bar): the first click arms,
    # a second within ARM_MS acts; otherwise the button reverts.
    ARM_MS = 3000
    RESET_TEXT = "RESET SETTINGS"
    RESET_ARMED_TEXT = "CLICK AGAIN TO RESET"
    CLEAR_TEXT = "CLEAR"
    CLEAR_ARMED_TEXT = "CLEAR?"         # like QUIT? on the nav bar
    UNMATCHED_ROWS = 3                # newest rows listed
    VOICE_DOWNLOAD_TEXT = "DOWNLOAD"
    VOICE_CANCEL_TEXT = "CANCEL"

    def __init__(self, parent=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedWidth(theme.px(WIDTH))
        # Optional: Settings takes focus when clicked (tick box next to the
        # pin, off by default; never when shown). Also applies updates held
        # back while a drop-down was open.
        self._held: dict = {}
        self._click_focus = _ClickFocus(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._click_focus)

        self._drag_from = None
        self._pending_version = ""
        self._installing = False
        self._update_worker: _UpdateWorker | None = None
        self._download: tuple[int, int] | None = None   # (got, total) while downloading
        self._tools: list[tuple[str, str]] = []
        self._key_buttons: dict[str, _KeyButton] = {}   # "toggle_nav", "panic", "tool:<id>"
        self._attention = False
        self._attention_on = False
        self._attention_timer = QTimer(self)
        self._attention_timer.setInterval(600)
        self._attention_timer.timeout.connect(self._pulse_region_btn)
        self._unmatched: list[dict] = []
        # Collapsible groups: id -> (heading, body). _open is the user's
        # choice; _forced (and the DRAW REGION pulse, for "scanner") keeps a
        # group open whatever the user clicks.
        self._groups: dict[str, tuple[_SectionHeader, QWidget]] = {}
        self._open: set[str] = {"scanner"}
        self._forced: str | None = None
        self._ore_count: int | None = None
        self._has_region = False
        # VOICE: the status part of the note (errors, "downloaded"), the
        # bytes the chosen voice still needs, and (got, total) while downloading.
        self._voice_status = ""
        self._voice_need = 0
        self._voice_downloading: tuple[int, int] | None = None
        self._engine_notes: dict[str, str] = dict(ENGINE_NOTES)
        self._build()
        self.adjustSize()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.px(18), theme.px(14), theme.px(18), theme.px(16))
        root.setSpacing(theme.px(8))

        head = QHBoxLayout()
        head.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        head.setSpacing(theme.px(8))
        title = QLabel("SETTINGS")
        title.setFont(theme.font(9, QFont.Weight.Bold, spacing=1.8))
        title.setStyleSheet(theme.qss("color: rgba(168,184,200,0.95); background: transparent;"))
        head.addWidget(title)
        head.addStretch(1)

        build = QLabel(build_label())
        build.setFont(theme.font(7))
        build.setStyleSheet(theme.qss(
            "color: rgba(130,148,166,0.85); background: transparent;"))
        build.setToolTip(
            "Build of this folder. If it is older than the copy you just "
            "downloaded, an earlier install is still being launched.")
        head.addWidget(build)

        close = QPushButton("✕")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.setFixedSize(theme.px(20), theme.px(20))
        close.setStyleSheet(theme.qss("""
            QPushButton { color: rgba(150,164,180,0.8); background: transparent;
                          border: none; font-size: 12px; }
            QPushButton:hover { color: #ffd9d9; }
        """))
        close.clicked.connect(self.close_requested.emit)
        self.focus_btn = _button("FOCUS", checkable=True)
        self.focus_btn.setFixedWidth(theme.px(52))
        self.focus_btn.setToolTip(
            "On: clicking Settings makes it the active window (it takes the keyboard "
            "until you click the game). Off: Settings never takes focus.")
        self.focus_btn.toggled.connect(self._on_take_focus)
        head.addWidget(self.focus_btn)
        self.pin_btn = PinButton(self)
        self.pin_btn.pin_toggled.connect(self.pin_toggled.emit)
        head.addWidget(self.pin_btn)
        head.addWidget(close)
        root.addLayout(head)
        root.addSpacing(theme.px(4))

        # Collapsible groups, top to bottom (SECTION_IDS order).
        builders = {
            "scanner": self._build_scanner, "scan_data": self._build_scan_data,
            "hotkeys": self._build_hotkeys, "look": self._build_look,
            "voice": self._build_voice,
            "update": self._build_update, "debug": self._build_debug,
        }
        for section_id, heading in SECTION_HEADINGS:
            builders[section_id](self._add_group(root, section_id, heading))
        self._update_summaries()
        self._apply_sections(fit=False)

    # -- focus tick box and drop-down protection -------------------------
    def _on_take_focus(self, on: bool) -> None:
        self._click_focus.enabled = bool(on)
        self.take_focus_toggled.emit(bool(on))

    def set_take_focus(self, on: bool) -> None:
        """Show the saved FOCUS choice without emitting take_focus_toggled."""
        self.focus_btn.blockSignals(True)
        self.focus_btn.setChecked(bool(on))
        self.focus_btn.blockSignals(False)
        self._click_focus.enabled = bool(on)

    @property
    def take_focus(self) -> bool:
        return self._click_focus.enabled

    def _dropdown_popups(self) -> list:
        return [box.view().window() for box in self.findChildren(QComboBox)]

    def _dropdown_open(self) -> bool:
        return any(box.view().isVisible() for box in self.findChildren(QComboBox))

    def _flush_held(self) -> None:
        """Apply the updates held back while a drop-down was open."""
        if self._dropdown_open():
            return
        held, self._held = self._held, {}
        for name, (args, kwargs) in held.items():
            getattr(type(self), name).__wrapped__(self, *args, **kwargs)

    def _build_scanner(self, root: QVBoxLayout) -> None:
        """Signature capture region and Scanning (with the preview)."""
        # Capture region ----------------------------------------------
        root.addWidget(_section("Signature capture region"))

        # Resolution and scaling are read from Windows, not typed in: the
        # list shows each monitor's real size and scaling, and choosing one
        # tells DRAW REGION where the game is.
        monitor_row = QHBoxLayout()
        monitor_row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        monitor_row.setSpacing(theme.px(8))
        monitor_name = QLabel("MONITOR")
        monitor_name.setFixedWidth(theme.px(58))
        monitor_name.setFont(theme.font(8, QFont.Weight.DemiBold, spacing=0.8))
        monitor_name.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        self.monitor_box = QComboBox()
        self.monitor_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.monitor_box.setCursor(Qt.CursorShape.PointingHandCursor)
        self.monitor_box.setFixedHeight(theme.px(24))
        self.monitor_box.setToolTip(
            "The monitor Star Citizen runs on. Resolution and scaling are read "
            "from Windows; DRAW REGION opens on this monitor.")
        self.monitor_box.setStyleSheet(theme.qss("""
            QComboBox {
                color: rgba(200,214,228,0.95); background: rgba(79,209,224,0.06);
                border: 1px solid rgba(79,209,224,0.18); border-radius: 6px;
                padding: 0 8px; font-size: 8px;
            }
            QComboBox:hover { background: rgba(79,209,224,0.12); }
            QComboBox::drop-down { border: none; width: 16px; }
            QComboBox QAbstractItemView {
                color: rgba(200,214,228,0.95); background: rgb(14,20,28);
                selection-background-color: rgba(79,209,224,0.25);
                border: 1px solid rgba(79,209,224,0.25);
            }
        """))
        self.monitor_box.activated.connect(self._on_monitor)
        monitor_row.addWidget(monitor_name)
        monitor_row.addWidget(self.monitor_box, 1)
        root.addLayout(monitor_row)

        region_row = QHBoxLayout()
        region_row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        region_row.setSpacing(theme.px(8))
        self.region_label = QLabel("Not calibrated")
        self.region_label.setFont(theme.font(9))
        self.region_label.setStyleSheet(theme.qss("color: rgba(150,166,182,0.95); background: transparent;"))
        self.region_btn = _button("DRAW REGION")
        # Red, like QUIT on the nav bar: the one control here that changes
        # what the scanner reads (and saves the tracking pin).
        self._style_region_btn(False)
        self.region_btn.clicked.connect(self.region_requested.emit)
        region_row.addWidget(self.region_label, 1)
        region_row.addWidget(self.region_btn)
        root.addLayout(region_row)

        # Shown when the box was adjusted for a monitor change, or when the
        # game monitor is not connected.
        self.region_note = QLabel()
        self.region_note.setWordWrap(True)
        self.region_note.setFont(theme.font(7))
        self.region_note.setStyleSheet(theme.qss(
            "color: rgba(255,176,32,0.95); background: transparent;"))
        self.region_note.hide()
        root.addWidget(self.region_note)
        root.addSpacing(theme.px(8))

        # Scanning ----------------------------------------------------
        root.addWidget(_section("Scanning"))
        reads_row = QHBoxLayout()
        reads_row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        reads_row.setSpacing(theme.px(8))
        reads_name = QLabel("READS / S")
        reads_name.setFixedWidth(theme.px(58))
        reads_name.setFont(theme.font(8, QFont.Weight.DemiBold, spacing=0.8))
        reads_name.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        self.reads_slider = _slider()
        self.reads_slider.setRange(1, 8)
        self.reads_slider.setSingleStep(1)
        self.reads_slider.setPageStep(1)
        self.reads_slider.setValue(4)
        self.reads_slider.setToolTip(
            "How often the signature box is read. Fewer reads use less CPU; "
            "more reads lock onto a new rock sooner.")
        self.reads_slider.valueChanged.connect(self._on_reads)
        self.reads_label = QLabel("4 / s")
        self.reads_label.setFixedWidth(theme.px(34))
        self.reads_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.reads_label.setFont(theme.font(9))
        self.reads_label.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        reads_row.addWidget(reads_name)
        reads_row.addWidget(self.reads_slider, 1)
        reads_row.addWidget(self.reads_label)
        root.addLayout(reads_row)

        # How far the scanner follows the swaying HUD plate (at 2160 px high;
        # scaled to the game monitor). 0 reads the fixed box only.
        tracking_row = QHBoxLayout()
        tracking_row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        tracking_row.setSpacing(theme.px(8))
        tracking_name = QLabel("TRACKING")
        tracking_name.setFixedWidth(theme.px(58))
        tracking_name.setFont(theme.font(8, QFont.Weight.DemiBold, spacing=0.8))
        tracking_name.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        # The slider counts whole steps (0..16 x 50 px), so it cannot stop
        # between them. With tracking off, valueChanged comes once when a drag
        # is released (sliderMoved only updates the label meanwhile), so a
        # drag saves the setting once instead of on every pixel.
        self.tracking_slider = _slider()
        self.tracking_slider.setRange(0, TRACKING_MAX // TRACKING_STEP)
        self.tracking_slider.setSingleStep(1)
        self.tracking_slider.setPageStep(1)
        self.tracking_slider.setTracking(False)
        self.tracking_slider.setValue(400 // TRACKING_STEP)
        self.tracking_slider.setToolTip(
            "How far the scanner follows the signature when the HUD sways. "
            "OFF reads the fixed box only. Needs the pin icon left of the box "
            "when you press DRAW REGION.")
        self.tracking_slider.sliderMoved.connect(self._on_tracking_moved)
        self.tracking_slider.valueChanged.connect(self._on_tracking)
        self.tracking_label = QLabel(_tracking_text(400))
        self.tracking_label.setFixedWidth(theme.px(48))
        self.tracking_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.tracking_label.setFont(theme.font(9))
        self.tracking_label.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        tracking_row.addWidget(tracking_name)
        tracking_row.addWidget(self.tracking_slider, 1)
        tracking_row.addWidget(self.tracking_label)
        root.addLayout(tracking_row)

        scan_row = QHBoxLayout()
        scan_row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        scan_row.setSpacing(theme.px(8))
        self.pause_btn = _button("PAUSE", checkable=True)
        self.debug_btn = _button("SHOW PREVIEW", checkable=True)
        self.outline_btn = _button("SHOW BOX", checkable=True)
        self.outline_btn.setToolTip(
            "Draw the capture box on screen so you can see where the scanner "
            "reads. Hidden from screenshots and from the scanner itself.")
        self.pause_btn.toggled.connect(self._on_pause)
        self.debug_btn.toggled.connect(self._on_debug)
        self.outline_btn.toggled.connect(self.outline_toggled.emit)
        scan_row.addWidget(self.pause_btn, 1)
        scan_row.addWidget(self.debug_btn, 1)
        scan_row.addWidget(self.outline_btn, 1)
        root.addLayout(scan_row)

        # Tall enough for the whole signature window (about 2.2 : 1) across
        # the Settings width; a digits-only crop just sits in the middle.
        self.preview = QLabel()
        self.preview.setFixedHeight(theme.px(PREVIEW_HEIGHT))
        self.preview.setMinimumWidth(0)
        self.preview_rects: dict[str, QRectF] = {}   # last outlines, in pixmap pixels
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(theme.qss(
            "background: rgba(0,0,0,0.35); border: 1px dashed rgba(79,209,224,0.25);"
            "border-radius: 6px; color: rgba(130,148,166,0.7); font-size: 9px;"))
        self.preview.setText("Drag a box around the signature, then confirm the digits below")
        self.preview.hide()
        root.addWidget(self.preview)

    def _build_scan_data(self, root: QVBoxLayout) -> None:
        """Signature data and Unmatched readings."""
        # Signature data ----------------------------------------------
        root.addWidget(_section("Signature data"))
        data_row = QHBoxLayout()
        data_row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        data_row.setSpacing(theme.px(8))
        self.version_label = QLabel("—")
        self.version_label.setFont(theme.font(9))
        self.version_label.setStyleSheet(theme.qss("color: rgba(150,166,182,0.95); background: transparent;"))
        self.reload_btn = _button("RELOAD")
        self.reload_btn.clicked.connect(self.reload_requested.emit)
        data_row.addWidget(self.version_label, 1)
        data_row.addWidget(self.reload_btn)
        root.addLayout(data_row)
        root.addSpacing(theme.px(8))

        # Unmatched readings ------------------------------------------
        # Readings no signature matched, saved by the app (number, time and
        # a picture of the box) so missing scans can be added later.
        root.addWidget(_section("Unmatched readings"))
        unmatched_row = QHBoxLayout()
        unmatched_row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        unmatched_row.setSpacing(theme.px(8))
        self.unmatched_label = QLabel("None saved")
        self.unmatched_label.setFont(theme.font(9))
        self.unmatched_label.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        self.unmatched_open_btn = _button("OPEN FOLDER")
        self.unmatched_open_btn.setToolTip(
            "Open the folder with the saved readings (index.json and pictures)")
        self.unmatched_open_btn.clicked.connect(self.open_unmatched_folder.emit)
        self.unmatched_clear_btn = _button(self.CLEAR_TEXT)
        self.unmatched_clear_btn.setToolTip("Delete the saved readings (click twice)")
        self.unmatched_clear_btn.setProperty("armed", False)
        self.unmatched_clear_btn.setEnabled(False)
        self.unmatched_clear_btn.clicked.connect(self._on_clear_unmatched_clicked)
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.setInterval(self.ARM_MS)
        self._clear_timer.timeout.connect(self._disarm_clear)
        # Room for the armed text, so arming does not shift the row.
        self.unmatched_clear_btn.setText(self.CLEAR_ARMED_TEXT)
        self.unmatched_clear_btn.setMinimumWidth(self.unmatched_clear_btn.sizeHint().width())
        self.unmatched_clear_btn.setText(self.CLEAR_TEXT)
        unmatched_row.addWidget(self.unmatched_label, 1)
        unmatched_row.addWidget(self.unmatched_open_btn)
        unmatched_row.addWidget(self.unmatched_clear_btn)
        root.addLayout(unmatched_row)

        # Newest rows: value left, time right; hidden while the list is empty.
        self._unmatched_rows = QVBoxLayout()
        self._unmatched_rows.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        self._unmatched_rows.setSpacing(theme.px(2))
        self._unmatched_row_labels: list[tuple[QLabel, QLabel]] = []
        for _ in range(self.UNMATCHED_ROWS):
            row = QHBoxLayout()
            row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
            row.setSpacing(theme.px(8))
            value = QLabel()
            value.setFont(theme.font(8))
            value.setStyleSheet(theme.qss(
                "color: rgba(200,214,228,0.95); background: transparent;"))
            when = QLabel()
            when.setFont(theme.font(7))
            when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            when.setStyleSheet(theme.qss(
                "color: rgba(130,148,166,0.9); background: transparent;"))
            value.hide()
            when.hide()
            row.addWidget(value, 1)
            row.addWidget(when)
            self._unmatched_rows.addLayout(row)
            self._unmatched_row_labels.append((value, when))
        root.addLayout(self._unmatched_rows)

    def _build_hotkeys(self, root: QVBoxLayout) -> None:
        """One row per hotkey, then the hint."""
        self._hotkey_rows = QVBoxLayout()
        self._hotkey_rows.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        self._hotkey_rows.setSpacing(theme.px(4))
        root.addLayout(self._hotkey_rows)
        for key, label in HOTKEY_ROWS:
            self._add_hotkey_row(key, label)
        self.hotkey_hint = QLabel(
            "Click a key, then press the new one. Esc = no key.")
        self.hotkey_hint.setWordWrap(True)
        self.hotkey_hint.setFont(theme.font(7))
        self._hotkey_hint_style(False)
        root.addWidget(self.hotkey_hint)

    def _build_look(self, root: QVBoxLayout) -> None:
        """Appearance (UI scale, opacity, screenshots)."""
        # Appearance --------------------------------------------------
        root.addWidget(_section("Appearance"))

        ui_scale_row = QHBoxLayout()
        ui_scale_row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        ui_scale_row.setSpacing(theme.px(8))
        ui_scale_name = QLabel("UI SCALE")
        ui_scale_name.setFixedWidth(theme.px(58))
        ui_scale_name.setFont(theme.font(8, QFont.Weight.DemiBold, spacing=0.8))
        ui_scale_name.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        self.ui_scale_slider = _slider()
        self.ui_scale_slider.setRange(75, 150)
        self.ui_scale_slider.setSingleStep(5)
        self.ui_scale_slider.setPageStep(10)
        self.ui_scale_slider.setValue(100)
        self.ui_scale_slider.setToolTip(
            "Scale the entire overlay UI; takes effect after restart")
        self.ui_scale_slider.valueChanged.connect(self._on_ui_scale)
        self.ui_scale_label = QLabel("100%")
        self.ui_scale_label.setFixedWidth(theme.px(34))
        self.ui_scale_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.ui_scale_label.setFont(theme.font(9))
        self.ui_scale_label.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        ui_scale_row.addWidget(ui_scale_name)
        ui_scale_row.addWidget(self.ui_scale_slider, 1)
        ui_scale_row.addWidget(self.ui_scale_label)
        root.addLayout(ui_scale_row)

        ui_scale_hint_row = QHBoxLayout()
        ui_scale_hint_row.setContentsMargins(theme.px(0), theme.px(0),
                                             theme.px(0), theme.px(0))
        ui_scale_hint_row.setSpacing(theme.px(8))
        self.ui_scale_hint = QLabel("Applies after restart")
        self.ui_scale_hint.setFont(theme.font(7))
        self.ui_scale_hint.setStyleSheet(theme.qss(
            "color: rgba(130,148,166,0.9); background: transparent;"))
        self.ui_scale_restart = _button("RESTART")
        self.ui_scale_restart.setFixedHeight(theme.px(20))
        self.ui_scale_restart.setToolTip(
            "Restart the overlay now to apply the new UI scale")
        self.ui_scale_restart.clicked.connect(self.restart_requested.emit)
        ui_scale_hint_row.addWidget(self.ui_scale_hint)
        ui_scale_hint_row.addStretch(1)
        ui_scale_hint_row.addWidget(self.ui_scale_restart)
        root.addLayout(ui_scale_hint_row)
        root.addSpacing(theme.px(4))

        opacity_row = QHBoxLayout()
        opacity_row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        opacity_row.setSpacing(theme.px(8))
        opacity_name = QLabel("OPACITY")
        opacity_name.setFixedWidth(theme.px(58))
        opacity_name.setFont(theme.font(8, QFont.Weight.DemiBold, spacing=0.8))
        opacity_name.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        self.opacity_slider = _slider()
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setToolTip(
            "Opacity of the overlay panels (nav bar and settings stay fully visible)")
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        self.opacity_label = QLabel("100%")
        self.opacity_label.setFixedWidth(theme.px(34))
        self.opacity_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.opacity_label.setFont(theme.font(9))
        self.opacity_label.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        opacity_row.addWidget(opacity_name)
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity_label)
        root.addLayout(opacity_row)

        capture_row = QHBoxLayout()
        capture_row.setContentsMargins(theme.px(0), theme.px(0),
                                       theme.px(0), theme.px(0))
        capture_row.setSpacing(theme.px(8))
        self.capture_btn = _button("VISIBLE", checkable=True)
        self.capture_btn.setFixedWidth(theme.px(82))
        self.capture_btn.setChecked(True)
        self.capture_btn.setToolTip(
            "Include the overlay in screenshots and screen shares")
        self.capture_btn.toggled.connect(self._on_capture)
        # The sentence is the label now: it already says what the state means,
        # so the separate SCREENSHOTS caption is gone and the button sits to
        # its right.
        self.capture_hint = QLabel("Shown in screenshots and streams")
        self.capture_hint.setFont(theme.font(8))
        self.capture_hint.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        capture_row.addWidget(self.capture_hint, 1)
        capture_row.addWidget(self.capture_btn)
        root.addLayout(capture_row)

    @staticmethod
    def _row_name(text: str) -> QLabel:
        name = QLabel(text)
        name.setFixedWidth(theme.px(58))
        name.setFont(theme.font(8, QFont.Weight.DemiBold, spacing=0.8))
        name.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        return name

    @staticmethod
    def _row() -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        row.setSpacing(theme.px(8))
        return row

    def _build_voice(self, root: QVBoxLayout) -> None:
        """VOICE: on/off and volume, ENGINE, VOICE, DOWNLOAD (add-on voices),
        SPEED, SAYS with TEST, and the grey note (licence, online, errors)."""
        voice_row = self._row()
        self.voice_btn = _button("ON", checkable=True)
        self.voice_btn.setFixedWidth(theme.px(52))
        self.voice_btn.setChecked(True)
        self.voice_btn.setToolTip("Speak the ore name when a signature locks")
        self.voice_btn.toggled.connect(self._on_voice)

        self.volume_slider = _slider()
        self.volume_slider.setValue(80)
        self.volume_slider.setToolTip("Announcement volume")
        self.volume_slider.valueChanged.connect(self._on_volume)

        self.volume_label = QLabel("80%")
        self.volume_label.setFixedWidth(theme.px(34))
        self.volume_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.volume_label.setFont(theme.font(9))
        self.volume_label.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        voice_row.addWidget(self.voice_btn)
        voice_row.addWidget(self.volume_slider, 1)
        voice_row.addWidget(self.volume_label)
        root.addLayout(voice_row)

        engine_row = self._row()
        self.engine_box = _combo()
        self.engine_box.setToolTip(
            "How the voice is made. Every method is free; compare them with TEST.")
        for engine_id in tts.ENGINE_IDS:
            self.engine_box.addItem(tts.engine_label(engine_id), engine_id)
        _fit_popup(self.engine_box)
        self.engine_box.activated.connect(self._on_engine)
        engine_row.addWidget(self._row_name("ENGINE"))
        engine_row.addWidget(self.engine_box, 1)
        root.addLayout(engine_row)

        choice_row = self._row()
        self.voice_box = _combo()
        self.voice_box.setToolTip("The voice of the chosen engine")
        self.voice_box.activated.connect(self._on_voice_choice)
        choice_row.addWidget(self._row_name("VOICE"))
        choice_row.addWidget(self.voice_box, 1)
        root.addLayout(choice_row)

        # DOWNLOAD: shown only while the chosen voice needs files.
        self.voice_download_row = QWidget(self)
        dl_row = QHBoxLayout(self.voice_download_row)
        dl_row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        dl_row.setSpacing(theme.px(8))
        self.voice_download_label = QLabel()
        self.voice_download_label.setFont(theme.font(7))
        self.voice_download_label.setStyleSheet(theme.qss(
            "color: rgba(176,192,208,0.95); background: transparent;"))
        self.voice_download_btn = _button(self.VOICE_CANCEL_TEXT)
        self.voice_download_btn.setToolTip(
            "Download what this voice needs (once); CANCEL stops it")
        width = self.voice_download_btn.sizeHint().width()
        self.voice_download_btn.setText(self.VOICE_DOWNLOAD_TEXT)
        self.voice_download_btn.setMinimumWidth(
            max(width, self.voice_download_btn.sizeHint().width()))
        self.voice_download_btn.clicked.connect(self._on_voice_download)
        dl_row.addWidget(self.voice_download_label, 1)
        dl_row.addWidget(self.voice_download_btn)
        self.voice_download_row.hide()
        root.addWidget(self.voice_download_row)
        self.voice_download_bar = _ProgressBar(self)
        root.addWidget(self.voice_download_bar)

        speed_row = self._row()
        self.speed_slider = _slider()
        self.speed_slider.setRange(SPEED_MIN, SPEED_MAX)      # tenths: 0.5-2.0
        self.speed_slider.setSingleStep(1)
        self.speed_slider.setPageStep(1)
        self.speed_slider.setValue(10)
        self.speed_slider.setToolTip("How fast the voice speaks (1.0× = normal)")
        self.speed_slider.valueChanged.connect(self._on_speed)
        self.speed_label = QLabel(speed_text(1.0))
        self.speed_label.setFixedWidth(theme.px(34))
        self.speed_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.speed_label.setFont(theme.font(9))
        self.speed_label.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        speed_row.addWidget(self._row_name("SPEED"))
        speed_row.addWidget(self.speed_slider, 1)
        speed_row.addWidget(self.speed_label)
        root.addLayout(speed_row)

        says_row = self._row()
        self.style_box = _combo()
        self.style_box.setToolTip("What is said when a signature locks")
        for style_id in phrases.STYLES:
            self.style_box.addItem(phrases.STYLE_LABELS[style_id], style_id)
        _fit_popup(self.style_box)
        self.style_box.activated.connect(self._on_style)
        self.voice_test_btn = _button("TEST")
        self.voice_test_btn.setToolTip(
            "Say a sample reading (Feynmaline, 19 deposits, 57,000) in the chosen style")
        self.voice_test_btn.clicked.connect(self.voice_test_requested.emit)
        says_row.addWidget(self._row_name("SAYS"))
        says_row.addWidget(self.style_box, 1)
        says_row.addWidget(self.voice_test_btn)
        root.addLayout(says_row)

        self.voice_note = QLabel()
        self.voice_note.setWordWrap(True)
        self.voice_note.setFont(theme.font(7))
        self.voice_note.setStyleSheet(theme.qss(
            "color: rgba(130,148,166,0.9); background: transparent;"))
        root.addWidget(self.voice_note)
        self._refresh_voice_note()

    def _build_update(self, root: QVBoxLayout) -> None:
        """Update and Reset."""
        # Update ------------------------------------------------------
        # Last on purpose: it is a maintenance action, not something adjusted
        # mid-session, so it sits below the scan and voice controls.
        root.addWidget(_section("Update"))
        update_row = QHBoxLayout()
        update_row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        update_row.setSpacing(theme.px(8))
        self.update_hint = QLabel(f"Installed {build_label()}")
        self.update_hint.setFont(theme.font(7))
        self.update_hint.setWordWrap(True)
        self.update_hint.setStyleSheet(theme.qss(
            "color: rgba(130,148,166,0.9); background: transparent;"))
        self.update_btn = _button("CHECK")
        self.update_btn.setFixedWidth(theme.px(82))
        self.update_btn.setToolTip(
            "Compare this install with GitHub, then copy the newest files")
        self.update_btn.clicked.connect(self._on_update_clicked)
        update_row.addWidget(self.update_hint, 1)
        update_row.addWidget(self.update_btn)
        root.addLayout(update_row)
        self.update_bar = _ProgressBar(self)
        root.addWidget(self.update_bar)

        # "What's new in vX" from the release notes, plain text only.
        self.whats_new_label = QLabel()
        self.whats_new_label.setTextFormat(Qt.TextFormat.PlainText)
        self.whats_new_label.setWordWrap(True)
        self.whats_new_label.setFont(theme.font(7))
        self.whats_new_label.setStyleSheet(theme.qss(
            "color: rgba(176,192,208,0.95); background: rgba(79,209,224,0.05);"
            "border: 1px solid rgba(79,209,224,0.14); border-radius: 6px; padding: 6px;"))
        self.whats_new_label.hide()
        root.addWidget(self.whats_new_label)
        root.addSpacing(theme.px(8))

        # Reset -------------------------------------------------------
        root.addWidget(_section("Reset"))
        reset_row = QHBoxLayout()
        reset_row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        reset_row.setSpacing(theme.px(8))
        self.reset_hint = QLabel("Settings and downloads; notes, inventory and blueprints are kept")
        self.reset_hint.setWordWrap(True)
        self.reset_hint.setFont(theme.font(7))
        self.reset_hint.setStyleSheet(theme.qss(
            "color: rgba(130,148,166,0.9); background: transparent;"))
        self.reset_btn = _button(self.RESET_TEXT)
        self.reset_btn.setToolTip(
            "Back to the default settings (click twice). A dated backup of the "
            "settings folder is kept next to it; the app restarts.")
        self.reset_btn.setProperty("armed", False)
        self._style_red_btn(self.reset_btn, False)
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.setInterval(self.ARM_MS)
        self._reset_timer.timeout.connect(self._disarm_reset)
        # Room for the armed text, so arming does not shift the row.
        self.reset_btn.setText(self.RESET_ARMED_TEXT)
        self.reset_btn.setMinimumWidth(self.reset_btn.sizeHint().width())
        self.reset_btn.setText(self.RESET_TEXT)
        reset_row.addWidget(self.reset_hint, 1)
        reset_row.addWidget(self.reset_btn)
        root.addLayout(reset_row)

        self.reset_note = QLabel()
        self.reset_note.setWordWrap(True)
        self.reset_note.setFont(theme.font(7))
        self.reset_note.setStyleSheet(theme.qss(
            "color: rgba(232,106,106,0.95); background: transparent;"))
        self.reset_note.hide()
        root.addWidget(self.reset_note)

    def _build_debug(self, root: QVBoxLayout) -> None:
        """SCAN HISTORY and SAVE BAD READS: switch and open button each;
        Logs: DETAILED LOG, OPEN LOG, VIEW LOG and EXPORT DIAGNOSTICS."""
        root.addWidget(_section("Scan debugging"))
        self.history_btn, self.history_open_btn = self._debug_row(
            root, "SCAN HISTORY", "OPEN HISTORY",
            "Keep the last 50 reads in scan_history.txt in the settings folder",
            "Open scan_history.txt")
        self.history_btn.toggled.connect(self._on_history)
        self.history_open_btn.clicked.connect(self.open_history.emit)
        self.bad_reads_btn, self.bad_reads_open_btn = self._debug_row(
            root, "SAVE BAD READS", "OPEN FOLDER",
            "Save a picture (at most one a second, newest 200 kept) when the "
            "plate is on screen but its number cannot be read",
            "Open the bad_reads folder")
        self.bad_reads_btn.toggled.connect(self._on_bad_reads)
        self.bad_reads_open_btn.clicked.connect(self.open_bad_reads.emit)

        root.addWidget(_section("Logs"))
        self.detailed_log_btn, self.log_open_btn = self._debug_row(
            root, "DETAILED LOG", "OPEN LOG",
            "Also write the step-by-step trace to app.log (warnings and "
            "errors are always written)",
            "Open app.log")
        self.detailed_log_btn.toggled.connect(self._on_detailed_log)
        self.log_open_btn.clicked.connect(self.open_log.emit)
        row = QHBoxLayout()
        row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        row.setSpacing(theme.px(6))
        self.log_view_btn = _button("VIEW LOG")
        self.log_view_btn.setToolTip("Show app.log in a window that follows new lines")
        self.log_view_btn.clicked.connect(self.view_log.emit)
        self.log_export_btn = _button("EXPORT DIAGNOSTICS")
        self.log_export_btn.setToolTip(
            "Save the logs, settings and debug pictures in one zip on the Desktop "
            "(notes, inventory and blueprints are left out)")
        self.log_export_btn.clicked.connect(self.export_diagnostics.emit)
        row.addWidget(self.log_view_btn, 1)
        row.addWidget(self.log_export_btn, 1)
        root.addLayout(row)
        self.log_note = QLabel()
        self.log_note.setWordWrap(True)
        self.log_note.setFont(theme.font(7))
        self.log_note.setStyleSheet(theme.qss(
            "color: rgba(130,148,166,0.85); background: transparent;"))
        self.log_note.hide()
        root.addWidget(self.log_note)

    def _debug_row(self, root: QVBoxLayout, name: str, open_text: str,
                   tip: str, open_tip: str) -> tuple[QPushButton, QPushButton]:
        row = QHBoxLayout()
        row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        # Tighter than the other rows: SAVE BAD READS, the switch and OPEN
        # HISTORY only just fit the width.
        row.setSpacing(theme.px(6))
        label = QLabel(name)
        label.setFont(theme.font(8, QFont.Weight.DemiBold, spacing=0.4))
        label.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        label.setToolTip(tip)
        switch = _button("OFF", checkable=True)
        switch.setFixedWidth(theme.px(52))
        switch.setToolTip(tip)
        opener = _button(open_text)
        opener.setToolTip(open_tip)
        row.addWidget(label, 1)
        row.addWidget(switch)
        row.addWidget(opener)
        root.addLayout(row)
        return switch, opener

    def _on_history(self, checked: bool) -> None:
        self.history_btn.setText("ON" if checked else "OFF")
        self._update_summaries()
        self.history_toggled.emit(checked)

    def _on_detailed_log(self, checked: bool) -> None:
        self.detailed_log_btn.setText("ON" if checked else "OFF")
        self._update_summaries()
        self.detailed_log_toggled.emit(checked)

    def set_detailed_log(self, enabled: bool) -> None:
        """Show the DETAILED LOG switch; emits nothing."""
        self._set_switch(self.detailed_log_btn, bool(enabled))
        self._update_summaries()

    @_held_while_dropdown
    def set_log_note(self, text: str) -> None:
        """The grey line under the Logs buttons ("" hides it)."""
        self.log_note.setText(str(text or ""))
        self.log_note.setVisible(bool(text))
        self._fit()

    def _on_bad_reads(self, checked: bool) -> None:
        self.bad_reads_btn.setText("ON" if checked else "OFF")
        self._update_summaries()
        self.bad_reads_toggled.emit(checked)

    @staticmethod
    def _set_switch(button: QPushButton, on: bool) -> None:
        if button.isChecked() != on:
            button.blockSignals(True)
            button.setChecked(on)
            button.blockSignals(False)
        button.setText("ON" if on else "OFF")

    def set_history(self, enabled: bool) -> None:
        """Show the SCAN HISTORY switch; emits nothing."""
        self._set_switch(self.history_btn, bool(enabled))
        self._update_summaries()

    def set_bad_reads(self, enabled: bool) -> None:
        """Show the SAVE BAD READS switch; emits nothing."""
        self._set_switch(self.bad_reads_btn, bool(enabled))
        self._update_summaries()

    # -- collapsible groups ------------------------------------------------
    def _add_group(self, root: QVBoxLayout, section_id: str, heading: str) -> QVBoxLayout:
        """Heading row plus a body; returns the body's layout to fill."""
        header = _SectionHeader(heading, self)
        header.clicked.connect(lambda sid=section_id: self._on_header_clicked(sid))
        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(theme.px(0), theme.px(2), theme.px(0), theme.px(6))
        layout.setSpacing(theme.px(8))
        root.addWidget(header)
        root.addWidget(body)
        self._groups[section_id] = (header, body)
        return layout

    def _locked(self, section_id: str) -> bool:
        """Kept open: forced by main, or Scanner while DRAW REGION pulses."""
        return section_id == self._forced or (section_id == "scanner" and self._attention)

    def _is_open(self, section_id: str) -> bool:
        return section_id in self._open or self._locked(section_id)

    @property
    def open_sections(self) -> list[str]:
        """Group ids shown open, in SECTION_IDS order."""
        return [sid for sid in SECTION_IDS if self._is_open(sid)]

    def set_open_sections(self, ids) -> None:
        """Open exactly these groups (unknown ids dropped); emits nothing."""
        self._open = {str(sid) for sid in (ids or []) if str(sid) in SECTION_IDS}
        self._apply_sections()

    def set_force_open(self, section_id: str | None) -> None:
        """Keep one group open (its heading cannot close it); None releases.

        A released group stays open, so the window does not jump."""
        section_id = section_id if section_id in SECTION_IDS else None
        if self._forced and self._forced != section_id:
            self._open.add(self._forced)
        self._forced = section_id
        self._apply_sections()

    def section_header(self, section_id: str) -> _SectionHeader:
        """The heading row of a group (tests click it)."""
        return self._groups[section_id][0]

    def _on_header_clicked(self, section_id: str) -> None:
        if self._locked(section_id):
            return
        if section_id in self._open:
            self._open.discard(section_id)
        else:
            self._open.add(section_id)
        self._apply_sections()
        self.sections_changed.emit(self.open_sections)

    def _apply_sections(self, fit: bool = True) -> None:
        for section_id, (header, body) in self._groups.items():
            opened = self._is_open(section_id)
            header.set_state(opened, self._locked(section_id))
            body.setVisible(opened)
        if not self._is_open("hotkeys"):
            for button in self._key_buttons.values():
                button.cancel_capture()
        if fit:
            self._fit()

    def _fit(self) -> None:
        """Resize to the open groups, then keep the window on its screen."""
        self.adjustSize()
        if not self.isVisible():
            return
        # The screen under the heading row: the top stays put while the
        # bottom may already hang below the screen.
        screen = QGuiApplication.screenAt(
            self.geometry().topLeft() + QPoint(self.width() // 2, 10))
        if screen is None:              # off every screen (e.g. tests): leave it
            return
        geo = screen.availableGeometry()
        if self.geometry().bottom() > geo.bottom():
            self.move(self.x(), max(geo.top(), geo.bottom() - self.height() + 1))

    def _update_summaries(self) -> None:
        """Grey one-liners shown on closed headings."""
        if not self._groups:
            return
        monitor = self.monitor_box.currentData() or ""
        box = "box set" if self._has_region else "no box"
        unmatched = f"{len(self._unmatched)} unmatched"
        keys = " · ".join(f"{label} {vk_name(self._key_buttons[key].vk)}"
                          for key, label in HOTKEY_ROWS)
        summaries = {
            "scanner": " · ".join(p for p in (str(monitor), box) if p),
            "scan_data": (f"{self._ore_count} ores · {unmatched}"
                          if self._ore_count is not None else unmatched),
            "hotkeys": keys,
            "look": f"UI {self.ui_scale_slider.value()}%",
            "voice": self.voice_summary(),
            "update": (self._download_summary() if self._download is not None
                       else f"v{self._pending_version} available" if self._pending_version
                       else f"v{VERSION} installed"),
            "debug": (f"history {'on' if self.history_btn.isChecked() else 'off'} · "
                      f"saver {'on' if self.bad_reads_btn.isChecked() else 'off'}"
                      + (" · log detailed" if self.detailed_log_btn.isChecked() else "")),
        }
        for section_id, text in summaries.items():
            self._groups[section_id][0].set_summary(text)

    def voice_summary(self) -> str:
        """'<engine> · <voice> · <speed>×'; 'off · ' in front while the voice
        is off, ' · downloading NN%' after while a voice downloads."""
        engine = ENGINE_SHORT.get(self.voice_engine, self.voice_engine)
        name = self.voice_box.currentData(VOICE_NAME_ROLE) or "default voice"
        text = f"{engine} · {name} · {speed_text(self.voice_speed)}"
        if not self.voice_btn.isChecked():
            text = "off · " + text
        if self._voice_downloading is not None:
            got, total = self._voice_downloading
            text += (f" · downloading {_percent(got, total)}%" if total > 0
                     else " · downloading")
        return text

    def section_summary(self, section_id: str) -> str:
        """Full summary text of a group's heading (for tests)."""
        return self._groups[section_id][0].summary_text

    # ------------------------------------------------------------------
    def _on_pause(self, checked: bool) -> None:
        self.pause_btn.setText("RESUME" if checked else "PAUSE")
        self.pause_toggled.emit(checked)

    def _on_debug(self, checked: bool) -> None:
        self.preview.setVisible(checked)
        self.debug_toggled.emit(checked)
        self.adjustSize()

    def _on_reads(self, value: int) -> None:
        value = max(1, min(8, int(value)))
        self.reads_label.setText(f"{value} / s")
        self.reads_changed.emit(value)

    def _on_tracking_moved(self, steps: int) -> None:
        """While dragging: label only (nothing is saved until release)."""
        self.tracking_label.setText(_tracking_text(_snap_tracking(int(steps) * TRACKING_STEP)))

    def _on_tracking(self, steps: int) -> None:
        value = _snap_tracking(int(steps) * TRACKING_STEP)
        self.tracking_label.setText(_tracking_text(value))
        self.tracking_changed.emit(value)

    @property
    def tracking_value(self) -> int:
        """The TRACKING range shown, in px."""
        return _snap_tracking(self.tracking_slider.value() * TRACKING_STEP)

    def _on_monitor(self, index: int) -> None:
        name = self.monitor_box.itemData(index)
        self._update_summaries()
        if name:
            self.monitor_changed.emit(str(name))

    def _on_voice(self, checked: bool) -> None:
        self.voice_btn.setText("ON" if checked else "OFF")
        self.volume_slider.setEnabled(checked)
        self._update_summaries()
        self.voice_toggled.emit(checked)

    def _on_volume(self, value: int) -> None:
        self.volume_label.setText(f"{value}%")
        self.volume_changed.emit(int(value))

    # -- VOICE ---------------------------------------------------------
    def _on_engine(self, index: int) -> None:
        engine_id = self.engine_box.itemData(index)
        self._voice_status = ""
        self._refresh_voice_note()
        self._update_summaries()
        if engine_id:
            self.voice_engine_changed.emit(str(engine_id))

    def _on_voice_choice(self, index: int) -> None:
        voice_id = self.voice_box.itemData(index)
        self._voice_status = ""
        self._refresh_voice_note()
        self._update_summaries()
        if voice_id is not None:
            self.voice_choice_changed.emit(str(voice_id))

    def _on_speed(self, value: int) -> None:
        speed = max(SPEED_MIN, min(SPEED_MAX, int(value))) / 10.0
        self.speed_label.setText(speed_text(speed))
        self._update_summaries()
        self.voice_speed_changed.emit(speed)

    def _on_style(self, index: int) -> None:
        style_id = self.style_box.itemData(index)
        if style_id:
            self.voice_style_changed.emit(str(style_id))

    def _on_voice_download(self) -> None:
        if self._voice_downloading is not None:
            self.voice_download_btn.setEnabled(False)       # until main ends it
            self.voice_download_label.setText("Cancelling…")
            self.voice_download_cancelled.emit()
        elif self._voice_need > 0:
            self.set_voice_progress(0, self._voice_need)
            self.voice_download_requested.emit()

    def _refresh_voice_note(self) -> None:
        """Grey line: the engine's note (licence / online), then the status."""
        note = self._engine_notes.get(self.voice_engine, "")
        text = "\n".join(t for t in (note, self._voice_status) if t)
        self.voice_note.setText(text)
        self.voice_note.setVisible(bool(text))

    def _refresh_voice_download(self) -> None:
        if self._voice_downloading is not None:
            got, total = self._voice_downloading
            self.voice_download_label.setText(voice_download_text(got, total))
            self.voice_download_btn.setText(self.VOICE_CANCEL_TEXT)
            self.voice_download_row.show()
            self.voice_download_bar.set_progress(got, total)
        elif self._voice_need > 0:
            self.voice_download_label.setText(
                f"Needs a {_size_mb(self._voice_need)} MB download")
            self.voice_download_btn.setText(self.VOICE_DOWNLOAD_TEXT)
            self.voice_download_btn.setEnabled(True)
            self.voice_download_row.show()
        else:
            self.voice_download_row.hide()
        if self._voice_downloading is None:
            self.voice_download_bar.hide()
        self.voice_test_btn.setEnabled(
            self._voice_downloading is None and self._voice_need <= 0)
        self._update_summaries()
        if self.isVisible():
            self._fit()

    @property
    def voice_engine(self) -> str:
        return str(self.engine_box.currentData() or "windows")

    @property
    def voice_id(self) -> str:
        data = self.voice_box.currentData()
        return "" if data is None else str(data)

    @property
    def voice_speed(self) -> float:
        return self.speed_slider.value() / 10.0

    @property
    def voice_style(self) -> str:
        return str(self.style_box.currentData() or phrases.DEFAULT_STYLE)

    @property
    def voice_downloading(self) -> bool:
        return self._voice_downloading is not None

    @_held_while_dropdown
    def set_voice_engines(self, engines) -> None:
        """ENGINE entries as (id, label, note) from the engines themselves;
        ids not given keep their built-in label and note. Emits nothing."""
        for engine_id, label, note in engines or []:
            index = self.engine_box.findData(str(engine_id))
            if index < 0:
                continue
            if label:
                self.engine_box.setItemText(index, str(label))
            if note:
                self._engine_notes[str(engine_id)] = str(note)
        _fit_popup(self.engine_box)
        self._refresh_voice_note()

    def set_voice_engine(self, engine_id: str) -> None:
        """Show the ENGINE choice (unknown ids show Windows); emits nothing."""
        index = self.engine_box.findData(str(engine_id))
        self.engine_box.setCurrentIndex(index if index >= 0 else 0)
        self._refresh_voice_note()
        self._update_summaries()

    @_held_while_dropdown
    def set_voice_choices(self, voices, current: str = "") -> None:
        """Fill VOICE with the engine's voices (objects with id, name, detail,
        or (id, name, detail) tuples) and show ``current`` (else the first);
        emits nothing."""
        self.voice_box.blockSignals(True)
        self.voice_box.clear()
        for item in voices or []:
            if isinstance(item, (tuple, list)):
                vid, name, detail = (list(item) + ["", "", ""])[:3]
            else:
                vid = getattr(item, "id", "")
                name = getattr(item, "name", "") or vid
                detail = getattr(item, "detail", "")
            text = f"{name} · {detail}" if detail else str(name)
            row = self.voice_box.count()
            self.voice_box.addItem(text, str(vid))
            self.voice_box.setItemData(row, str(name), VOICE_NAME_ROLE)
            self.voice_box.setItemData(row, text, Qt.ItemDataRole.ToolTipRole)
        index = self.voice_box.findData(str(current or ""))
        if self.voice_box.count():
            self.voice_box.setCurrentIndex(index if index >= 0 else 0)
        self.voice_box.setEnabled(self.voice_box.count() > 0)
        _fit_popup(self.voice_box)
        self.voice_box.blockSignals(False)
        self._update_summaries()

    @_held_while_dropdown
    def set_voice_download(self, size: int) -> None:
        """Bytes the chosen voice still needs: >0 shows DOWNLOAD with the size,
        0 hides the row. Ends a download in progress; emits nothing."""
        self._voice_downloading = None
        self._voice_need = max(0, int(size or 0))
        self._refresh_voice_download()

    @_held_while_dropdown
    def set_voice_progress(self, got: int, total: int) -> None:
        """While downloading: 'NN% · got of total MB' and CANCEL."""
        self._voice_downloading = (max(0, int(got)), max(0, int(total)))
        self.voice_download_btn.setEnabled(True)
        self._refresh_voice_download()

    def set_voice_speed(self, speed: float) -> None:
        try:
            tenths = int(round(float(speed) * 10))
        except (TypeError, ValueError):
            tenths = 10
        tenths = max(SPEED_MIN, min(SPEED_MAX, tenths))
        if self.speed_slider.value() != tenths:
            self.speed_slider.blockSignals(True)
            self.speed_slider.setValue(tenths)
            self.speed_slider.blockSignals(False)
        self.speed_label.setText(speed_text(tenths / 10.0))
        self._update_summaries()

    def set_voice_style(self, style_id: str) -> None:
        index = self.style_box.findData(str(style_id))
        self.style_box.setCurrentIndex(index if index >= 0 else 0)

    @_held_while_dropdown
    def set_voice_note(self, text: str) -> None:
        """Status under the licence note (an error, "Downloaded"); "" clears."""
        self._voice_status = (text or "").strip()
        self._refresh_voice_note()
        if self.isVisible():
            self._fit()

    def _on_ui_scale(self, value: int) -> None:
        value = max(75, min(150, int(value)))
        self.ui_scale_label.setText(f"{value}%")
        self._refresh_scale_hint(value)
        self._update_summaries()
        self.ui_scale_changed.emit(value)

    def _refresh_scale_hint(self, value: int) -> None:
        """Highlight the restart hint while the chosen scale is not active."""
        pending = abs(value - round(theme.scale() * 100)) >= 1
        self.ui_scale_hint.setText(
            "Restart to apply" if pending else "Applies after restart")
        self.ui_scale_hint.setStyleSheet(theme.qss(
            "color: rgba(255,176,32,0.95); background: transparent;"
            if pending else
            "color: rgba(130,148,166,0.9); background: transparent;"))

    def _on_opacity(self, value: int) -> None:
        value = max(30, min(100, int(value)))
        self.opacity_label.setText(f"{value}%")
        self.opacity_changed.emit(value)

    def _on_capture(self, checked: bool) -> None:
        self.capture_btn.setText("VISIBLE" if checked else "HIDDEN")
        self.capture_hint.setText(
            "Shown in screenshots and streams" if checked
            else "Hidden from screenshots and streams")
        self.capture_toggled.emit(checked)

    # -- update --------------------------------------------------------
    def _on_update_clicked(self) -> None:
        if self._installing or (self._update_worker is not None
                                and self._update_worker.isRunning()):
            return
        mode = "apply" if self._pending_version else "check"
        if mode == "apply" and updater.standalone():
            # An unzipped copy: Setup would install a second one elsewhere.
            QDesktopServices.openUrl(QUrl(updater.RELEASES_PAGE))
            self.update_hint.setText(
                f"Standalone copy: download v{self._pending_version} from the "
                "Releases page (opened), or use the installer")
            return

        self.update_btn.setEnabled(False)
        self.update_btn.setText("…")
        if mode == "check":
            self.update_hint.setText("Checking GitHub…")
        elif updater.is_frozen():
            self.update_hint.setText(f"Downloading the v{self._pending_version} installer…")
        else:
            self.update_hint.setText("Copying the newest files…")

        worker = _UpdateWorker(mode, self)
        worker.done.connect(self._on_update_done)
        worker.progress.connect(self._on_update_progress)
        worker.failed.connect(self._on_update_failed)
        worker.finished.connect(self._on_update_finished)
        worker.finished.connect(worker.deleteLater)
        self._update_worker = worker
        worker.start()

    def _on_update_progress(self, got: int, total: int) -> None:
        """Setup.exe download progress: the UPDATE line and the folded summary."""
        if self._installing:
            return
        self._download = (max(0, int(got)), max(0, int(total)))
        self.update_hint.setText(download_text(self._pending_version, got, total))
        self.update_bar.set_progress(got, total)
        self._update_summaries()

    def _download_summary(self) -> str:
        got, total = self._download or (0, 0)
        if total > 0:
            return f"downloading {_percent(got, total)}%"
        return f"downloading {_mb(got)} MB"

    def _end_download(self) -> None:
        self.update_bar.hide()
        if self._download is not None:
            self._download = None
            self._update_summaries()

    def _set_whats_new(self, version: str, notes: str) -> None:
        text = updater.whats_new(notes, version) if notes and version else ""
        self.whats_new_label.setText(f"What's new in v{version}\n{text}" if text else "")
        self.whats_new_label.setVisible(bool(text))
        self.adjustSize()

    def _update_tooltip(self) -> None:
        """Say what the button does for this kind of install."""
        version = self._pending_version
        if not version:
            tip = ("Check GitHub for a newer release" if updater.is_frozen()
                   else "Compare this install with GitHub, then copy the newest files")
        elif updater.is_frozen() and updater.standalone():
            tip = (f"This copy was unzipped, not installed: opens the Releases page "
                   f"to download v{version}")
        elif updater.is_frozen():
            tip = (f"Download the v{version} installer; {APP_NAME} closes, "
                   "installs it and starts again")
        else:
            tip = f"Copy the v{version} files from GitHub over this folder and restart"
        self.update_btn.setToolTip(tip)

    def _on_update_done(self, mode: str, value: str, extra: str = "") -> None:
        self._download = None
        if mode == "check":
            if value and updater.is_newer(value):
                self._pending_version = value
                self.update_hint.setText(f"v{value} available")
                self.update_btn.setText("UPDATE")
                self._set_whats_new(value, extra)
            else:
                # Name both numbers: "nothing happened" usually just means the
                # installed and published versions are the same build.
                self.update_hint.setText(
                    f"Up to date · GitHub has v{value or '?'}")
                self.update_btn.setText("CHECK")
                self._set_whats_new("", "")
            self._update_tooltip()
            self._update_summaries()
            return

        if mode == "install":
            # value is the downloaded Setup.exe, extra the version inside it
            # (the latest release at download time, which can be newer than
            # what CHECK saw). The app hands it off and quits; the button
            # stays off unless the hand-off fails (install_failed).
            version = extra or self._pending_version
            self._pending_version = version
            self._installing = True
            self._update_summaries()
            self.update_btn.setEnabled(False)
            self.update_hint.setText(
                f"Installing v{version} · {APP_NAME} closes and starts again by itself")
            self.update_btn.setText("…")
            self.install_requested.emit(value)
            return

        self._pending_version = ""
        self._set_whats_new("", "")
        self.update_hint.setText(f"Updated to v{value} · restarting…")
        self._update_summaries()
        self.update_btn.setText("CHECK")
        self._update_tooltip()
        # The new files are already on disk; only a restart loads them.
        self.restart_requested.emit()

    def _on_update_failed(self, message: str) -> None:
        self._end_download()
        self.update_hint.setText(f"Update failed: {message}")
        self.update_btn.setText("UPDATE" if self._pending_version else "CHECK")

    def _on_update_finished(self) -> None:
        self._end_download()
        if not self._installing:
            self.update_btn.setEnabled(True)
        self._update_worker = None

    def install_failed(self, message: str) -> None:
        """The app could not hand the installer off: offer UPDATE again."""
        self._installing = False
        message = str(message or "unknown error")
        self.update_hint.setText(message if message.startswith("Update failed")
                                 else f"Update failed: {message}")
        self.update_btn.setText("UPDATE" if self._pending_version else "CHECK")
        self.update_btn.setEnabled(True)
        self._update_tooltip()

    @property
    def installing(self) -> bool:
        return self._installing

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Stop the update thread at quit: cancel a download, wait for it.

        Returns True when no thread is left running.
        """
        worker = self._update_worker
        if worker is None:
            return True
        try:
            if not worker.isRunning():
                return True
            worker.requestInterruption()
            for signal in (worker.done, worker.failed, worker.progress):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
            return bool(worker.wait(max(0, int(timeout_ms))))
        except RuntimeError:          # already deleted
            return True

    # -- hotkeys ---------------------------------------------------------
    def _hotkey_hint_style(self, warn: bool) -> None:
        self.hotkey_hint.setStyleSheet(theme.qss(
            "color: rgba(255,176,32,0.95); background: transparent;" if warn else
            "color: rgba(130,148,166,0.9); background: transparent;"))

    def _add_hotkey_row(self, key: str, label: str) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(theme.px(0), theme.px(0), theme.px(0), theme.px(0))
        row.setSpacing(theme.px(8))
        name = QLabel(label)
        name.setFont(theme.font(8, QFont.Weight.DemiBold, spacing=0.8))
        name.setStyleSheet(theme.qss(
            "color: rgba(150,166,182,0.95); background: transparent;"))
        button = _KeyButton()
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(theme.px(22))
        button.setFixedWidth(theme.px(96))
        button.setStyleSheet(_button_qss())
        button.setToolTip(f"Key for {label}: click, then press a key (Esc = no key)")
        button.captured.connect(lambda vk, k=key, n=label: self._on_key_captured(k, n, vk))
        row.addWidget(name, 1)
        row.addWidget(button)
        self._hotkey_rows.addLayout(row)
        self._key_buttons[key] = button

    def _row_label(self, key: str) -> str:
        if key.startswith("tool:"):
            tool_id = key[5:]
            return next((label for tid, label in self._tools if tid == tool_id), tool_id.upper())
        return dict(HOTKEY_ROWS).get(key, key)

    def _on_key_captured(self, key: str, label: str, vk: int) -> None:
        for other, button in self._key_buttons.items():
            if other != key and vk and button.vk == vk:
                self.hotkey_hint.setText(
                    f"{vk_name(vk)} is already {self._row_label(other)}; "
                    "choose another key or clear that one first (Esc).")
                self._hotkey_hint_style(True)
                return
        self._key_buttons[key].set_vk(vk)
        self.hotkey_hint.setText(
            f"{label}: {vk_name(vk)}" if vk else f"{label}: no key")
        self._hotkey_hint_style(False)
        self._update_summaries()
        self.hotkeys_changed.emit(self.hotkeys())

    def hotkeys(self) -> dict:
        """The keys shown: {"toggle_nav": vk, "panic": vk, "tools": {id: vk}}."""
        return {
            "toggle_nav": self._key_buttons["toggle_nav"].vk,
            "panic": self._key_buttons["panic"].vk,
            "tools": {tid: self._key_buttons[f"tool:{tid}"].vk for tid, _ in self._tools},
        }

    def set_tools(self, tools) -> None:
        """Add a hotkey row per tool: main.TOOLS dicts or (id, label) pairs."""
        for tool in tools:
            if isinstance(tool, dict):
                tool_id, label = str(tool.get("id", "")), str(tool.get("label", ""))
            else:
                tool_id, label = str(tool[0]), str(tool[1])
            if not tool_id or f"tool:{tool_id}" in self._key_buttons:
                continue
            self._tools.append((tool_id, label or tool_id.upper()))
            self._add_hotkey_row(f"tool:{tool_id}", label or tool_id.upper())
        self.adjustSize()

    def set_hotkeys(self, keys: dict) -> None:
        """Show saved keys (same shape as hotkeys_changed); emits nothing.

        Without an earlier ``set_tools`` the tool rows come from main.TOOLS
        (imported here, not at module level: main imports this module).
        """
        if not self._tools:
            try:
                from ..main import TOOLS
            except Exception:         # main unavailable: SHOW BAR / HIDE ALL only
                TOOLS = []
            self.set_tools(TOOLS)
        keys = dict(keys or {})
        for name in ("toggle_nav", "panic"):
            if name in keys:
                self._key_buttons[name].set_vk(int(keys.get(name) or 0))
        tools = keys.get("tools") or {}
        for tool_id, _label in self._tools:
            self._key_buttons[f"tool:{tool_id}"].set_vk(int(tools.get(tool_id) or 0))
        self._update_summaries()

    # -- first run: point at DRAW REGION ------------------------------------
    def _style_region_btn(self, bright: bool) -> None:
        border = ("2px solid rgba(255,140,140,1.0)" if bright
                  else "1px solid rgba(232,106,106,0.70)")
        fill = "rgba(232,106,106,0.45)" if bright else "rgba(232,106,106,0.22)"
        self.region_btn.setStyleSheet(theme.qss(f"""
            QPushButton {{
                color: #ffd9d9; background: {fill};
                border: {border}; border-radius: 7px;
                font-size: 8px; font-weight: 600;
                letter-spacing: 1.0px; padding: 0 10px;
            }}
            QPushButton:hover {{ background: rgba(232,106,106,0.40); color: #ffffff; }}
            QPushButton:disabled {{
                color: rgba(130,148,166,0.55); background: rgba(232,106,106,0.05);
                border-color: rgba(232,106,106,0.20);
            }}
        """))

    def _pulse_region_btn(self) -> None:
        self._attention_on = not self._attention_on
        self._style_region_btn(self._attention_on)

    def set_draw_region_attention(self, on: bool) -> None:
        """Pulse DRAW REGION (first run, no region yet) until turned off."""
        on = bool(on)
        if on == self._attention:
            return
        self._attention = on
        if not on:
            self._open.add("scanner")     # stays open: the window does not jump
        self._apply_sections()
        if on:
            self._attention_on = True
            self._style_region_btn(True)
            self.region_btn.setToolTip("Start here: draw a box around the scan signature")
            self._attention_timer.start()
        else:
            self._attention_timer.stop()
            self._attention_on = False
            self._style_region_btn(False)
            self.region_btn.setToolTip("")

    @property
    def draw_region_attention(self) -> bool:
        return self._attention

    # -- two-click buttons: RESET SETTINGS, CLEAR -------------------------
    def _style_red_btn(self, button: QPushButton, armed: bool) -> None:
        """Red like QUIT; brighter while armed."""
        fill = "rgba(232,106,106,0.40)" if armed else "rgba(232,106,106,0.22)"
        border = "rgba(232,106,106,0.85)" if armed else "rgba(232,106,106,0.70)"
        color = "#ffffff" if armed else "#ffd9d9"
        button.setStyleSheet(theme.qss(f"""
            QPushButton {{
                color: {color}; background: {fill};
                border: 1px solid {border}; border-radius: 7px;
                font-size: 8px; font-weight: 600;
                letter-spacing: 1.0px; padding: 0 10px;
            }}
            QPushButton:hover {{ background: rgba(232,106,106,0.40); color: #ffffff; }}
            QPushButton:disabled {{
                color: rgba(130,148,166,0.55); background: rgba(232,106,106,0.05);
                border-color: rgba(232,106,106,0.20);
            }}
        """))

    def _on_reset_clicked(self) -> None:
        if self.reset_armed:
            self._disarm_reset()
            self.set_reset_error("")
            self.reset_requested.emit()
            return
        self._set_reset_armed(True)
        self._reset_timer.start()

    def _disarm_reset(self) -> None:
        self._reset_timer.stop()
        self._set_reset_armed(False)

    def _set_reset_armed(self, armed: bool) -> None:
        self.reset_btn.setProperty("armed", armed)
        self.reset_btn.setText(self.RESET_ARMED_TEXT if armed else self.RESET_TEXT)
        self._style_red_btn(self.reset_btn, armed)

    @property
    def reset_armed(self) -> bool:
        return bool(self.reset_btn.property("armed"))

    @_held_while_dropdown
    def set_reset_error(self, message: str) -> None:
        """Say why the reset did not happen ("" hides the note)."""
        message = str(message or "")
        self.reset_note.setText(
            f"Reset failed, nothing was removed: {message}" if message else "")
        self.reset_note.setVisible(bool(message))
        self.adjustSize()

    def _on_clear_unmatched_clicked(self) -> None:
        if self.clear_armed:
            self._disarm_clear()
            self.clear_unmatched.emit()
            return
        self._set_clear_armed(True)
        self._clear_timer.start()

    def _disarm_clear(self) -> None:
        self._clear_timer.stop()
        self._set_clear_armed(False)

    def _set_clear_armed(self, armed: bool) -> None:
        button = self.unmatched_clear_btn
        button.setProperty("armed", armed)
        button.setText(self.CLEAR_ARMED_TEXT if armed else self.CLEAR_TEXT)
        if armed:
            self._style_red_btn(button, True)
        else:
            button.setStyleSheet(_button_qss())

    @property
    def clear_armed(self) -> bool:
        return bool(self.unmatched_clear_btn.property("armed"))

    # -- unmatched readings ------------------------------------------------
    @staticmethod
    def _unmatched_when(value) -> str:
        """Entry time as "01 Nov 14:32" (epoch seconds; a string is shown as is)."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return time.strftime("%d %b %H:%M", time.localtime(float(value)))
            except (OverflowError, OSError, ValueError):
                return ""
        return str(value or "")

    @_held_while_dropdown
    def set_unmatched(self, entries) -> None:
        """Show the saved unmatched readings (UnmatchedLog.entries(), newest first)."""
        self._unmatched = [dict(e) for e in (entries or []) if isinstance(e, dict)]
        count = len(self._unmatched)
        self.unmatched_label.setText("None saved" if count == 0 else f"{count} saved")
        for i, (value_label, when_label) in enumerate(self._unmatched_row_labels):
            entry = self._unmatched[i] if i < count else None
            if entry is None:
                value_label.hide()
                when_label.hide()
                continue
            try:
                value_text = f"{int(entry.get('value')):,}"
            except (TypeError, ValueError):
                value_text = str(entry.get("value", "?"))
            value_label.setText(value_text)
            when_label.setText(self._unmatched_when(entry.get("time")))
            value_label.show()
            when_label.show()
        if count == 0:
            self._disarm_clear()
        self.unmatched_clear_btn.setEnabled(count > 0)
        self._update_summaries()
        self.adjustSize()

    @property
    def unmatched_text(self) -> str:
        """Count line, then each listed row as "value  time" (for tests)."""
        lines = [self.unmatched_label.text()]
        for value_label, when_label in self._unmatched_row_labels:
            if not value_label.isHidden():
                lines.append(f"{value_label.text()}  {when_label.text()}")
        return "\n".join(lines)

    # -- pin ---------------------------------------------------------------
    def set_pinned(self, pinned: bool) -> None:
        """Start-up state of the header pin; emits nothing."""
        self.pin_btn.set_pinned(bool(pinned))

    @property
    def pinned(self) -> bool:
        return self.pin_btn.isChecked()

    # ------------------------------------------------------------------
    def set_region(self, region: dict | None) -> None:
        self._has_region = bool(region)
        if region:
            self.region_label.setText(
                f"{region['width']} × {region['height']} px  ·  "
                f"({region['left']}, {region['top']})")
            self.region_btn.setText("DRAW REGION")
        else:
            self.region_label.setText("Not calibrated")
            self.region_btn.setText("DRAW REGION")
        self._update_summaries()

    @_held_while_dropdown
    def set_region_note(self, text: str) -> None:
        self.region_note.setText(text)
        self.region_note.setVisible(bool(text))
        self.adjustSize()

    @_held_while_dropdown
    def set_monitors(self, choices: list[tuple[str, str]], current: str | None) -> None:
        """Fill the monitor list with (screen name, label) pairs."""
        self.monitor_box.blockSignals(True)
        self.monitor_box.clear()
        for name, label in choices:
            self.monitor_box.addItem(label, name)
        index = self.monitor_box.findData(current) if current else -1
        self.monitor_box.setCurrentIndex(max(0, index))
        self.monitor_box.blockSignals(False)
        self._update_summaries()

    def set_reads(self, per_second: int) -> None:
        value = max(1, min(8, int(per_second)))
        if self.reads_slider.value() != value:
            self.reads_slider.blockSignals(True)
            self.reads_slider.setValue(value)
            self.reads_slider.blockSignals(False)
        self.reads_label.setText(f"{value} / s")

    def set_tracking(self, range_px: int) -> None:
        value = _snap_tracking(range_px)
        steps = value // TRACKING_STEP
        if self.tracking_slider.value() != steps:
            self.tracking_slider.blockSignals(True)
            self.tracking_slider.setValue(steps)
            self.tracking_slider.blockSignals(False)
        self.tracking_label.setText(_tracking_text(value))

    def set_paused(self, paused: bool) -> None:
        paused = bool(paused)
        if self.pause_btn.isChecked() != paused:
            self.pause_btn.blockSignals(True)
            self.pause_btn.setChecked(paused)
            self.pause_btn.blockSignals(False)
        self.pause_btn.setText("RESUME" if paused else "PAUSE")

    def set_outline(self, enabled: bool) -> None:
        if self.outline_btn.isChecked() != enabled:
            self.outline_btn.blockSignals(True)
            self.outline_btn.setChecked(enabled)
            self.outline_btn.blockSignals(False)

    def set_debug(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self.debug_btn.isChecked() != enabled:
            self.debug_btn.blockSignals(True)
            self.debug_btn.setChecked(enabled)
            self.debug_btn.blockSignals(False)
        self.preview.setVisible(enabled)
        self.adjustSize()

    def set_voice(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self.voice_btn.isChecked() != enabled:
            self.voice_btn.blockSignals(True)
            self.voice_btn.setChecked(enabled)
            self.voice_btn.blockSignals(False)
        self.voice_btn.setText("ON" if enabled else "OFF")
        self.volume_slider.setEnabled(enabled)
        self._update_summaries()

    def set_volume(self, percent: int) -> None:
        value = max(0, min(100, int(percent)))
        if self.volume_slider.value() != value:
            self.volume_slider.blockSignals(True)
            self.volume_slider.setValue(value)
            self.volume_slider.blockSignals(False)
        self.volume_label.setText(f"{value}%")

    def set_opacity(self, percent: int) -> None:
        value = max(30, min(100, int(percent)))
        if self.opacity_slider.value() != value:
            self.opacity_slider.blockSignals(True)
            self.opacity_slider.setValue(value)
            self.opacity_slider.blockSignals(False)
        self.opacity_label.setText(f"{value}%")

    def set_capture_visible(self, visible: bool, locked: bool = False) -> None:
        if self.capture_btn.isChecked() != bool(visible):
            self.capture_btn.blockSignals(True)
            self.capture_btn.setChecked(bool(visible))
            self.capture_btn.blockSignals(False)
        self.capture_btn.setText("VISIBLE" if visible else "HIDDEN")
        self.capture_btn.setEnabled(not locked)
        if locked:
            self.capture_hint.setText("Forced by --capture-visible")
        else:
            self.capture_hint.setText(
                "Shown in screenshots and streams" if visible
                else "Hidden from screenshots and streams")

    def set_ui_scale(self, percent: int) -> None:
        value = max(75, min(150, int(percent)))
        if self.ui_scale_slider.value() != value:
            self.ui_scale_slider.blockSignals(True)
            self.ui_scale_slider.setValue(value)
            self.ui_scale_slider.blockSignals(False)
        self.ui_scale_label.setText(f"{value}%")
        self._refresh_scale_hint(value)
        self._update_summaries()

    def set_voice_hint(self, text: str) -> None:
        self.voice_btn.setToolTip(
            text or "Speak the ore name when a signature locks")

    def set_version(self, version: str, count: int) -> None:
        self.version_label.setText(f"Signatures: {version}  ·  {count} ores")
        try:
            self._ore_count = int(count)
        except (TypeError, ValueError):
            self._ore_count = None
        self._update_summaries()

    @_held_while_dropdown
    def set_preview(self, crop, pin=None, digits=None) -> None:
        """Show a scanner crop scaled to fit the preview box (aspect kept).

        ``pin`` and ``digits`` are optional (x, y, w, h) rects in crop
        pixels, outlined cyan and green on the whole signature window.
        """
        if crop is None or not self.preview.isVisible():
            return
        try:
            rgb = crop[:, :, ::-1].copy()
            h, w = rgb.shape[:2]
            image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
            box_w = max(1, self.preview.width() - 10)
            box_h = max(1, self.preview.height() - 10)
            pix = QPixmap.fromImage(image).scaled(
                box_w, box_h, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            sx, sy = pix.width() / w, pix.height() / h
            self.preview_rects = {}
            outlines = [(name, rect, color) for name, rect, color in
                        (("pin", pin, theme.ACCENT), ("digits", digits, theme.GOOD))
                        if rect is not None]
            if outlines:
                painter = QPainter(pix)
                for name, rect, color in outlines:
                    x, y, rw, rh = (float(v) for v in rect)
                    r = QRectF(x * sx, y * sy, rw * sx, rh * sy)
                    pen = QPen(color)
                    pen.setWidth(2)
                    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(r.adjusted(1, 1, -1, -1))
                    self.preview_rects[name] = r
                painter.end()
            self.preview.setPixmap(pix)
        except Exception:
            self.preview.setText("preview unavailable")

    # ------------------------------------------------------------------
    def place_default(self, anchor: QWidget | None = None) -> None:
        geo = QGuiApplication.primaryScreen().availableGeometry()
        if anchor is not None and anchor.isVisible():
            a = anchor.geometry()
            self.move(a.x(), a.bottom() + 12)
        else:
            self.move(geo.center().x() - self.width() // 2, geo.top() + 110)

    def clamp_to_screen(self) -> None:
        screen = QGuiApplication.screenAt(self.geometry().center()) \
            or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = min(max(self.x(), geo.left() - 20), geo.right() - self.width() + 20)
        y = min(max(self.y(), geo.top()), geo.bottom() - 60)
        self.move(x, y)

    # ------------------------------------------------------------------
    def adjustSize(self) -> None:  # noqa: N802
        """Also fit wrapped text: Qt sizes the window for the layout's wider
        natural width, so at the fixed width the wrapped hints need more
        height and the rows above them were squeezed into each other."""
        super().adjustSize()
        layout = self.layout()
        if layout is not None and layout.hasHeightForWidth():
            needed = layout.totalHeightForWidth(self.width())
            if needed > self.height():
                self.resize(self.width(), needed)

    def hideEvent(self, event):  # noqa: N802
        for button in self._key_buttons.values():
            button.cancel_capture()
        super().hideEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 40:
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
        theme.paint_card(p, QRectF(0, 0, w, h), radius=14,
                         fill=QColor(10, 14, 20, 250))
        p.setPen(QPen(QColor(79, 209, 224, 90), 1.0))
        p.drawLine(18, 1, w - 18, 1)
