"""Global hotkeys via RegisterHotKey, with a key-state fallback on Windows.

RegisterHotKey works everywhere except inside many games' exclusive fullscreen
mode: the system stops delivering ``WM_HOTKEY`` to a non-foreground thread, so
F3/F4 look dead until the user Alt-Tabs out.  Polling ``GetAsyncKeyState`` reads
the keyboard's global state instead, which keeps working while another window
owns the display, so both paths stay active and are de-duplicated: whichever
notices the press first wins, and the other is ignored for a moment.

Polling is edge-triggered (press, not hold), so a held key toggles once, the
same behaviour MOD_NOREPEAT gave the registered path.

RegisterHotKey needs a thread with a message pump, so the bindings run on a
dedicated QThread.  Emitting a Qt signal from there is safe - Qt queues the
delivery onto the GUI thread automatically.

``set_bindings`` replaces the keys while the thread runs (Settings → HOTKEYS):
the new map is handed over under a lock and the thread itself unregisters the
old keys and registers the new ones, since RegisterHotKey belongs to the
thread that called it. A VK code of 0 means "no key" and is skipped.

macOS has no permission-free equivalent (CGEventTap needs Accessibility
approval), so on macOS this class is a no-op and ``main`` installs application
shortcuts for F3/F4 instead. The tray menu always works.
"""
from __future__ import annotations

import sys
import threading
import time

from PySide6.QtCore import QThread, Signal

WINDOWS = sys.platform == "win32"

if WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    MOD_NOREPEAT = 0x4000
    WM_HOTKEY = 0x0312
    PM_REMOVE = 0x0001
    VK_DOWN = 0x8000

    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                    wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = wintypes.SHORT

# How often the key state is polled, and how long a press is ignored on the
# other path so one physical key press cannot toggle twice.
SCAN_MS = 25
DEBOUNCE_S = 0.15


class HotkeyThread(QThread):
    """One signal per registered hotkey id."""

    pressed = Signal(int)

    def __init__(self, bindings: dict[int, int], parent=None):
        super().__init__(parent)
        self._bindings = self._clean(bindings)   # id -> virtual key
        self._failed: list[int] = []
        self._stopping = False
        self._recent: dict[int, float] = {}
        self._down: dict[int, bool] = {}
        self._lock = threading.Lock()
        self._pending: dict[int, int] | None = None

    @staticmethod
    def _clean(bindings: dict[int, int]) -> dict[int, int]:
        return {int(k): int(v) for k, v in dict(bindings).items() if int(v or 0) > 0}

    @property
    def failed(self) -> list[int]:
        return list(self._failed)

    @property
    def bindings(self) -> dict[int, int]:
        """The keys in use (or about to be, after ``set_bindings``)."""
        with self._lock:
            return dict(self._pending if self._pending is not None else self._bindings)

    @property
    def supported(self) -> bool:
        return WINDOWS

    def set_bindings(self, bindings: dict[int, int]) -> None:
        """Replace every binding (id -> VK; 0 = none), also while running.

        The running thread applies the new map on its next loop pass (within
        ~SCAN_MS): old keys are unregistered and the new ones registered on
        that thread, and the key-state poll switches to the new keys.
        """
        new = self._clean(bindings)
        with self._lock:
            if self.isRunning():
                self._pending = new
            else:
                self._bindings = new
                self._pending = None

    def _fire(self, hk_id: int) -> None:
        """Emit once per press, whichever path saw it first."""
        now = time.monotonic()
        if now - self._recent.get(hk_id, 0.0) < DEBOUNCE_S:
            return
        self._recent[hk_id] = now
        self.pressed.emit(int(hk_id))

    def _register(self) -> list[int]:
        """Register the current bindings on this thread; returns the ids held."""
        registered: list[int] = []
        self._failed = []
        self._down = {}
        for hk_id, vk in self._bindings.items():
            if user32.RegisterHotKey(None, hk_id, MOD_NOREPEAT, vk):
                registered.append(hk_id)
            else:
                # Another application owns that key.  The poller below still
                # sees it, so the binding keeps working.
                self._failed.append(hk_id)
            # A key already held (the one just pressed to choose it in
            # Settings) is not a press.
            self._down[hk_id] = bool(user32.GetAsyncKeyState(int(vk)) & VK_DOWN)
        return registered

    def run(self) -> None:  # noqa: D102
        if not WINDOWS:
            return

        with self._lock:
            if self._pending is not None:
                self._bindings, self._pending = self._pending, None
        registered = self._register()

        msg = wintypes.MSG()
        last_scan = 0.0
        while not self._stopping:
            with self._lock:
                swap, self._pending = self._pending, None
            if swap is not None:
                for hk_id in registered:
                    user32.UnregisterHotKey(None, hk_id)
                # Drop WM_HOTKEYs queued for the old keys.
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    pass
                self._bindings = swap
                registered = self._register()

            # Drain posted hotkeys without blocking, so the same loop can poll.
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_HOTKEY and int(msg.wParam) in self._bindings:
                    self._fire(int(msg.wParam))

            now = time.monotonic()
            if now - last_scan >= SCAN_MS / 1000.0:
                last_scan = now
                for hk_id, vk in self._bindings.items():
                    down = bool(user32.GetAsyncKeyState(int(vk)) & VK_DOWN)
                    if down and not self._down.get(hk_id, False):
                        self._fire(hk_id)
                    self._down[hk_id] = down

            self.msleep(SCAN_MS)

        for hk_id in registered:
            user32.UnregisterHotKey(None, hk_id)

    def stop(self) -> None:
        self._stopping = True
