"""Rebindable hotkeys: HotkeyThread.set_bindings and Settings → HOTKEYS.

    python -m tools.hotkeys_selftest

No real global hotkey is registered (it could take a key from a running
SC Assistant or the game): user32 is replaced by a fake that records
RegisterHotKey / UnregisterHotKey calls and answers GetAsyncKeyState from a
set of "held" keys. The thread, its loop and the swap are the real ones.
"""
from __future__ import annotations

from tools import _testguard

_testguard.install()        # first: no focus, no hotkeys

import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory(prefix="ca-hotkeys-")
os.environ["APPDATA"] = _TMP.name          # before app.config is imported
# A capture button activates its window and grabs the keyboard; off-screen
# Qt keeps that away from the user's desktop (and the game).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import hotkeys  # noqa: E402

VK_F3, VK_F4, VK_F6, VK_F7, VK_F8 = 0x72, 0x73, 0x75, 0x76, 0x77


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


def _wait(cond, seconds: float = 3.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class FakeUser32:
    """Stands in for user32: records calls, never touches the real keyboard."""

    def __init__(self):
        self.lock = threading.Lock()
        self.registered: dict[int, int] = {}       # id -> vk, as Windows would hold
        self.calls: list[tuple] = []               # (name, id, vk, thread id)
        self.held: set[int] = set()
        self.taken: set[int] = set()               # keys "owned by another app"

    def RegisterHotKey(self, hwnd, hk_id, mods, vk):  # noqa: N802
        with self.lock:
            self.calls.append(("register", hk_id, vk, threading.get_ident()))
            if vk in self.taken:
                return False
            self.registered[hk_id] = vk
            return True

    def UnregisterHotKey(self, hwnd, hk_id):  # noqa: N802
        with self.lock:
            self.calls.append(("unregister", hk_id, None, threading.get_ident()))
            self.registered.pop(hk_id, None)
            return True

    def PeekMessageW(self, *args):  # noqa: N802
        return 0

    def GetAsyncKeyState(self, vk):  # noqa: N802
        return -0x8000 if vk in self.held else 0


def check_thread_swap() -> int:
    failures = 0
    fake = FakeUser32()
    saved = (hotkeys.user32 if hasattr(hotkeys, "user32") else None, hotkeys.WINDOWS)
    hotkeys.user32, hotkeys.WINDOWS = fake, True
    thread = hotkeys.HotkeyThread({1: VK_F3, 2: VK_F4})
    pressed: list[int] = []
    thread.pressed.connect(pressed.append)
    try:
        thread.start()
        _wait(lambda: fake.registered == {1: VK_F3, 2: VK_F4})
        failures += _check("start: F3/F4 registered", fake.registered == {1: VK_F3, 2: VK_F4},
                           f"({fake.registered})")
        reg_thread = {c[3] for c in fake.calls}
        failures += _check("registered on the hotkey thread, not the GUI thread",
                           threading.get_ident() not in reg_thread)

        fake.held.add(VK_F3)
        _wait(lambda: pressed == [1])
        fake.held.discard(VK_F3)
        failures += _check("F3 press (key-state poll) fires id 1", pressed == [1], f"({pressed})")
        time.sleep(hotkeys.DEBOUNCE_S + 0.05)

        # Swap while running. F6 is "held" at the moment of the swap (the key
        # just pressed in Settings to choose it): that must not count as a press.
        fake.held.add(VK_F6)
        fake.taken.add(VK_F7)
        before = len(fake.calls)
        thread.set_bindings({1: VK_F6, 2: VK_F7, 100: VK_F8, 101: 0})
        _wait(lambda: fake.registered.get(1) == VK_F6)
        time.sleep(0.15)
        new_calls = fake.calls[before:]
        failures += _check("set_bindings: old ids unregistered first",
                           [c[:2] for c in new_calls[:2]] == [("unregister", 1), ("unregister", 2)],
                           f"({[c[:3] for c in new_calls]})")
        failures += _check("new keys registered on the hotkey thread (0 = none skipped)",
                           {c[1]: c[2] for c in new_calls if c[0] == "register"} == {1: VK_F6, 2: VK_F7, 100: VK_F8}
                           and all(c[3] in reg_thread for c in new_calls), f"({fake.registered})")
        failures += _check("a key another app owns is reported as failed", thread.failed == [2],
                           f"({thread.failed})")
        failures += _check("bindings property shows the new map",
                           thread.bindings == {1: VK_F6, 2: VK_F7, 100: VK_F8})
        failures += _check("key held during the swap does not fire", pressed == [1], f"({pressed})")
        fake.held.discard(VK_F6)
        time.sleep(0.1)

        fake.held.add(VK_F3)
        time.sleep(0.2)
        fake.held.discard(VK_F3)
        failures += _check("old key F3 no longer fires", pressed == [1], f"({pressed})")
        fake.held.add(VK_F7)
        _wait(lambda: 2 in pressed)
        fake.held.discard(VK_F7)
        failures += _check("new key F7 fires id 2 through the poll (RegisterHotKey failed)",
                           pressed[-1:] == [2], f"({pressed})")
        time.sleep(hotkeys.DEBOUNCE_S + 0.05)
        fake.held.add(VK_F8)
        _wait(lambda: 100 in pressed)
        fake.held.discard(VK_F8)
        failures += _check("tool key F8 fires id 100", pressed[-1:] == [100], f"({pressed})")
    finally:
        thread.stop()
        thread.wait(2000)
        if saved[0] is not None:
            hotkeys.user32 = saved[0]
        hotkeys.WINDOWS = saved[1]
    failures += _check("stop: every key unregistered", fake.registered == {}, f"({fake.registered})")

    idle = hotkeys.HotkeyThread({1: VK_F3})
    idle.set_bindings({1: VK_F6, 2: 0})
    failures += _check("set_bindings before start just replaces the map", idle.bindings == {1: VK_F6})
    return failures


def _press(button, qt_key, vk: int) -> None:
    event = QKeyEvent(QEvent.Type.KeyPress, qt_key, Qt.KeyboardModifier.NoModifier, 0, vk, 0)
    QApplication.sendEvent(button, event)


TOOLS = [{"id": "mining", "label": "MINING"}, {"id": "notes", "label": "NOTES"}]


def check_capture_ui() -> int:
    from app.ui.settings_panel import SettingsPanel, vk_name

    failures = 0
    panel = SettingsPanel()
    panel.set_tools(TOOLS)
    changed: list[dict] = []
    panel.hotkeys_changed.connect(changed.append)

    panel.set_hotkeys({"toggle_nav": VK_F3, "panic": VK_F4, "tools": {"mining": VK_F6}})
    buttons = panel._key_buttons
    failures += _check("rows: SHOW BAR, HIDE ALL and one per tool",
                       list(buttons) == ["toggle_nav", "panic", "tool:mining", "tool:notes"], f"({list(buttons)})")
    failures += _check("set_hotkeys shows the key names and emits nothing",
                       [b.text() for b in buttons.values()] == ["F3", "F4", "F6", "—"] and changed == [],
                       f"({[b.text() for b in buttons.values()]})")

    notes = buttons["tool:notes"]
    notes.click()
    failures += _check("clicking a key asks for a key", notes.text().startswith("PRESS A KEY"), f"({notes.text()!r})")
    _press(notes, Qt.Key.Key_F7, VK_F7)
    want = {"toggle_nav": VK_F3, "panic": VK_F4, "tools": {"mining": VK_F6, "notes": VK_F7}}
    failures += _check("pressing F7 sets NOTES and emits the whole map", changed == [want], f"({changed})")
    failures += _check("the row shows F7", notes.text() == "F7")

    panic = buttons["panic"]
    panic.click()
    _press(panic, Qt.Key.Key_F3, VK_F3)
    failures += _check("a key already in use is refused", len(changed) == 1 and panic.vk == VK_F4,
                       f"({panic.vk:#x}, {len(changed)} emits)")
    failures += _check("with a short message", "F3 is already SHOW BAR" in panel.hotkey_hint.text(),
                       f"({panel.hotkey_hint.text()!r})")

    panic.click()
    _press(panic, Qt.Key.Key_Shift, 0x10)
    failures += _check("a modifier alone does not end the capture", panic.capturing and len(changed) == 1)
    _press(panic, Qt.Key.Key_Escape, 0x1B)
    failures += _check("Esc clears the key (none)", panic.vk == 0 and panic.text() == "—"
                       and changed[-1]["panic"] == 0, f"({changed[-1]})")

    buttons["toggle_nav"].click()
    _press(buttons["toggle_nav"], Qt.Key.Key_F9, 0)
    failures += _check("no native VK: the Qt key is mapped (F9)", buttons["toggle_nav"].vk == 0x78,
                       f"({buttons['toggle_nav'].vk:#x})")
    failures += _check("hotkeys() matches the last emit", panel.hotkeys() == changed[-1])
    failures += _check("key names", (vk_name(0x41), vk_name(0x61), vk_name(0x20), vk_name(0)) == ("A", "Num 1", "Space", "—"))

    panel.setWindowOpacity(0.0)          # invisible before it is shown
    panel.move(-10000, -10000)
    panel.show()
    QApplication.processEvents()
    buttons["tool:mining"].click()
    buttons["tool:mining"].releaseKeyboard()   # never hold the user's keyboard in a test
    panel.hide()
    failures += _check("hiding the panel ends a capture", not buttons["tool:mining"].capturing)
    panel.deleteLater()

    # main.TOOLS by default, when set_tools was not called first.
    from app.main import TOOLS as MAIN_TOOLS
    other = SettingsPanel()
    other.set_hotkeys({"toggle_nav": VK_F3, "panic": VK_F4, "tools": {}})
    failures += _check("set_hotkeys alone builds a row per main.TOOLS entry",
                       set(other.hotkeys()["tools"]) == {t["id"] for t in MAIN_TOOLS},
                       f"({sorted(other.hotkeys()['tools'])})")
    other.deleteLater()
    return failures


def _run(fn) -> int:
    try:
        return fn()
    except Exception:
        print(f"  FAIL  {fn.__name__} raised:")
        traceback.print_exc(limit=4, file=sys.stdout)
        return 1


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if QApplication.instance() is None:
        QApplication(sys.argv)
    failures = 0
    for fn in (check_thread_swap, check_capture_ui):
        failures += _run(fn)
        print("-" * 78)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
