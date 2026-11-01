"""Keeps self-tests from reaching the user's desktop while they play.

Install it before anything else in a test that creates windows:

    from tools import _testguard
    _testguard.install()        # first: no focus, no hotkeys

It does three things for the whole test process:

* Global hotkeys are faked. ``app.hotkeys`` gets a user32 stand-in, so a
  real ``HotkeyThread`` (e.g. from ``OverlayApp.start()``) never registers
  F3/F4 for the whole PC and never reads the real keyboard.
* Windows never take focus. ``activateWindow``, ``grabKeyboard`` and
  ``QWindow.requestActivate`` do nothing, and every top-level window shown
  from Python gets ``WA_ShowWithoutActivating`` first.
* Focus theft fails the test. If this process takes the Windows foreground
  window (checked whenever Qt says the app became active, and at exit), the
  guard prints a FAIL line and the process exits with code 1.
"""
from __future__ import annotations

import atexit
import os
import sys

from PySide6 import QtWidgets
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QWindow

WINDOWS = sys.platform == "win32"
_violations: list[str] = []


# ---- global hotkeys -------------------------------------------------------
class _NoHotkeys:
    """user32 stand-in for app.hotkeys: registers nothing, sees no keys."""

    def RegisterHotKey(self, hwnd, hk_id, mods, vk):  # noqa: N802
        return True

    def UnregisterHotKey(self, hwnd, hk_id):  # noqa: N802
        return True

    def PeekMessageW(self, *args):  # noqa: N802
        return False

    def GetAsyncKeyState(self, vk):  # noqa: N802
        return 0


def _fake_hotkeys() -> None:
    from app import hotkeys
    if getattr(hotkeys, "WINDOWS", False):
        hotkeys.user32 = _NoHotkeys()


# ---- focus ----------------------------------------------------------------
def _noop(self, *args, **kwargs) -> None:
    return None


def _quiet(show):
    """Wraps a QWidget show method: a top-level window gets
    WA_ShowWithoutActivating before it is shown (set during the Show event it
    is too late, measured 2026-11-01)."""
    def wrapper(self, *args, **kwargs):
        if self.isWindow() and not self.isVisible():
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            # A simulated mouse press makes Qt activate the window from C++
            # (QWindow::requestActivate), past the Python no-op above.
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        return show(self, *args, **kwargs)
    wrapper.__name__ = show.__name__
    return wrapper


class _NoActivate(QObject):
    """Shows every top-level window without activating it, and records any
    moment this process becomes the active application anyway."""

    def eventFilter(self, obj, event):  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.Polish and isinstance(obj, QtWidgets.QWidget) and obj.isWindow():
            obj.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        elif kind == QEvent.Type.ApplicationStateChange:
            app = QtWidgets.QApplication.instance()
            # Qt reports "active" for a shown tool window even when Windows
            # kept the game in front (measured 2026-11-01): only the real
            # foreground window counts.
            if (app is not None and app.applicationState() == Qt.ApplicationState.ApplicationActive
                    and _foreground_is_ours()):
                active = app.activeWindow()
                name = type(active).__name__ if active is not None else "a window"
                _violations.append(f"the test became the active app ({name})")
        return False


class GuardedApplication(QtWidgets.QApplication):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._no_activate = _NoActivate()
        self.installEventFilter(self._no_activate)


# ---- foreground check at exit --------------------------------------------
def _foreground_is_ours() -> bool:
    if not WINDOWS:
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32")
    hwnd = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return bool(hwnd) and pid.value == os.getpid()


def _report() -> None:
    if _foreground_is_ours():
        _violations.append("a test window is in front at exit")
    if not _violations:
        return
    for line in dict.fromkeys(_violations):
        print(f"  FAIL  focus guard: {line}", flush=True)
    sys.stdout.flush()
    os._exit(1)


_installed = False


def install() -> None:
    """Applies the guard to this process; safe to call more than once."""
    global _installed
    if _installed:
        return
    _installed = True
    QtWidgets.QWidget.activateWindow = _noop
    QtWidgets.QWidget.grabKeyboard = _noop
    QWindow.requestActivate = _noop
    for name in ("show", "showNormal", "showMaximized", "showFullScreen", "showMinimized"):
        setattr(QtWidgets.QWidget, name, _quiet(getattr(QtWidgets.QWidget, name)))
    QtWidgets.QApplication = GuardedApplication
    _fake_hotkeys()
    atexit.register(_report)
