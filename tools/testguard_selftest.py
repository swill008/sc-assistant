"""Checks tools/_testguard.py without ever taking focus or a real hotkey.

    python -m tools.testguard_selftest            # with the guard: all pass
    python -m tools.testguard_selftest --no-guard # shows what the guard stops

Nothing here activates a window for real: the "no guard" run only inspects
what would happen (real activateWindow, real user32, no show attribute).
"""
from __future__ import annotations

import sys

GUARD = "--no-guard" not in sys.argv
if GUARD:
    from tools import _testguard as guard
    guard.install()             # first: no focus, no hotkeys

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


def main() -> int:
    failures = 0
    app = QApplication.instance() or QApplication(sys.argv)
    from app import hotkeys

    print("Hotkeys")
    real = type(getattr(hotkeys, "user32", None)).__name__
    failures += _check("app.hotkeys cannot register real hotkeys", real == "_NoHotkeys", f"(user32 is {real})")
    if real == "_NoHotkeys":
        thread = hotkeys.HotkeyThread({1: 0x87})        # F24, never pressed
        thread.start()
        app.processEvents()
        thread.stop()
        failures += _check("a real HotkeyThread starts and stops on the fake", thread.wait(2000))

    print("Focus")
    failures += _check("activateWindow does nothing",
                       QWidget.activateWindow.__name__ == "_noop", f"({QWidget.activateWindow.__name__})")
    failures += _check("grabKeyboard does nothing",
                       QWidget.grabKeyboard.__name__ == "_noop", f"({QWidget.grabKeyboard.__name__})")
    w = QWidget()
    w.setWindowOpacity(0.0)
    w.resize(40, 40)
    if GUARD:                       # without the guard showing it could take focus
        w.show()
        app.processEvents()
    failures += _check("a shown window does not activate",
                       w.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
    failures += _check("the test never took the foreground window",
                       not guard._foreground_is_ours() if GUARD else True)
    w.close()

    print("Detector")
    if GUARD:
        before = list(guard._violations)
        original = type(app).applicationState, guard._foreground_is_ours
        type(app).applicationState = staticmethod(lambda: Qt.ApplicationState.ApplicationActive)
        try:
            guard._foreground_is_ours = lambda: False
            app._no_activate.eventFilter(app, QEvent(QEvent.Type.ApplicationStateChange))
            quiet = guard._violations[len(before):]
            guard._foreground_is_ours = lambda: True
            app._no_activate.eventFilter(app, QEvent(QEvent.Type.ApplicationStateChange))
        finally:
            type(app).applicationState, guard._foreground_is_ours = original
        caught = guard._violations[len(before):]
        failures += _check("Qt 'active' with the game still in front is not theft", quiet == [], f"({quiet})")
        failures += _check("taking the foreground window is recorded", bool(caught), f"({caught})")
        del guard._violations[len(before):]      # simulated: don't fail the run
    else:
        failures += _check("taking the foreground window is recorded", False, "(no guard)")

    print("Every window test loads the guard first")
    from pathlib import Path
    first = ("from __future__ import annotations\n\n"
             "from tools import _testguard\n\n_testguard.install()")
    for path in sorted(Path(__file__).parent.glob("*_selftest.py")):
        text = path.read_text(encoding="utf-8")
        if path.name == Path(__file__).name or not ("QApplication" in text or "OverlayApp" in text):
            continue
        failures += _check(f"{path.name} loads the guard first", first in text)

    print("ALL CHECKS PASSED" if not failures else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
