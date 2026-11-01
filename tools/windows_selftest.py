"""Window positions are saved while the app runs and come back on screen.

    python -m tools.windows_selftest

Runs the real OverlayApp against a temporary settings folder (your own
%APPDATA% is never touched). Every window is invisible (opacity 0) and placed
on a secondary monitor: the default spots and the clamp use the "primary"
screen, which this test points at a secondary one. Checks:

* a moved tool panel is in config.json about a second later, without QUIT;
* opening and closing a tool saves open_tools;
* the Settings position is saved and comes back after a restart, and opening
  Settings again keeps it there;
* saved positions far off every edge, or on a removed monitor, end fully
  inside the nearest screen for all eight windows (seven tools and Settings),
  and a window already fully on screen is not moved;
* after QUIT, and during RESET SETTINGS, nothing is written back.
"""
from __future__ import annotations

from tools import _testguard

_testguard.install()        # first: no focus, no hotkeys

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory(prefix="ca-windows-")
os.environ["APPDATA"] = _TMP.name          # before app.config is imported

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

TOOL_KEYS = ("mining_panel_pos", "orefinder_pos", "hauling_pos", "inventory_pos",
             "combat_pos", "uex_pos", "notes_pos")
ALL_KEYS = (*TOOL_KEYS, "settings_pos")


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def _saved() -> dict:
    from app.config import CONFIG_PATH

    if not CONFIG_PATH.is_file():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _all_windows(o) -> dict:
    return {"mining_panel_pos": o.panel, "orefinder_pos": o.orefinder,
            "hauling_pos": o.hauling, "inventory_pos": o.inventory,
            "combat_pos": o.combat_panel, "uex_pos": o.uex, "notes_pos": o.notes,
            "settings_pos": o.settings}


def _overlay(app):
    """A real OverlayApp from the saved file, every window invisible."""
    from app.config import Config
    from app.main import OverlayApp

    o = OverlayApp(app, Config.load())
    hidden = [o.nav, o.outline, *_all_windows(o).values()]

    def invisible() -> None:
        for widget in hidden:
            widget.setWindowOpacity(0.0)
    o._apply_opacity = invisible          # start() calls it before any show
    invisible()
    return o


def _close(o) -> None:
    o.quit()
    _pump(0.3)
    o.outline.hide()
    for widget in (o.nav, *_all_windows(o).values()):
        widget.hide()


def _fully_on_screen(widget) -> bool:
    frame = widget.frameGeometry()
    return any(s.availableGeometry().contains(frame) for s in QGuiApplication.screens())


def _off_screen_run(app, positions: dict, unmoved: bool = False) -> int:
    """Start from saved positions; every window must end fully on a screen
    (and, with unmoved, exactly where it was saved)."""
    from app.config import CONFIG_PATH

    data = _saved()
    data.update(positions)
    data["open_tools"] = []
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    o = _overlay(app)
    o.start()
    _pump(0.3)
    o._toggle_settings()
    _pump(0.2)
    failures = 0
    for key, widget in _all_windows(o).items():
        at = [widget.x(), widget.y()]
        if unmoved:
            failures += _check(f"{key}: fully on screen, not moved", at == positions[key],
                               f"(at {at}, saved {positions[key]})")
        else:
            failures += _check(f"{key}: comes back fully on a screen", _fully_on_screen(widget),
                               f"(at {at}, frame {widget.frameGeometry()})")
    _close(o)
    return failures


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)

    from app.config import CONFIG_PATH, Config, config_dir
    from app import main as main_mod

    real_primary_fn = QGuiApplication.primaryScreen
    real_primary = real_primary_fn()
    others = [s for s in QGuiApplication.screens() if s is not real_primary]
    if not others:
        print("  FAIL  no secondary monitor: these checks never use the main monitor")
        return 1
    side = max(others, key=lambda s: s.availableGeometry().width() * s.availableGeometry().height())
    QGuiApplication.primaryScreen = staticmethod(lambda: side)
    geo = side.availableGeometry()
    print(f"settings folder {config_dir()}, windows on {side.name()} {geo}")
    print("-" * 78)

    cfg = Config()
    cfg["nav_visible"] = False
    cfg["voice_enabled"] = False
    cfg.save()
    failures = 0

    # ---- first run: move, open and close without quitting ---------------
    print("First run: move and open/close windows, no QUIT")
    one = _overlay(app)
    one.start()
    _pump(0.5)
    one.open_tool("notes")
    _pump(1.5)
    failures += _check("opening NOTES saves open_tools", "notes" in (_saved().get("open_tools") or []),
                       f"({_saved().get('open_tools')})")
    target = (geo.left() + 60, geo.top() + 50)
    one.notes.move(*target)                       # what the header drag does
    _pump(0.3)
    early = _saved().get("notes_pos")
    _pump(1.2)
    failures += _check("a moved panel is in config.json within 1.5 s, without QUIT",
                       _saved().get("notes_pos") == list(target), f"(saved {_saved().get('notes_pos')}, want {target})")
    failures += _check("the save waits until the window stops moving", early != list(target), f"(at 0.3 s {early})")
    one.notes.close_requested.emit()
    _pump(1.5)
    failures += _check("closing NOTES saves open_tools", "notes" not in (_saved().get("open_tools") or []),
                       f"({_saved().get('open_tools')})")

    one._toggle_settings()
    _pump(0.2)
    settings_at = (geo.left() + 120, geo.top() + 40)
    one.settings.move(*settings_at)
    _pump(1.5)
    failures += _check("a moved Settings window is in config.json within 1.5 s",
                       _saved().get("settings_pos") == list(settings_at), f"({_saved().get('settings_pos')})")
    _close(one)
    before = CONFIG_PATH.read_text(encoding="utf-8")
    one.panel.show()
    one.panel.move(geo.left() + 5, geo.top() + 5)
    one.panel.hide()
    _pump(1.5)
    failures += _check("after QUIT, moving and hiding windows writes nothing",
                       CONFIG_PATH.read_text(encoding="utf-8") == before)

    # ---- second run: Settings comes back where it was --------------------
    print("Second run: restart")
    two = _overlay(app)
    two.start()
    _pump(0.5)
    if not two.settings.isVisible():
        two._toggle_settings()
        _pump(0.2)
    failures += _check("Settings position survives a restart",
                       (two.settings.x(), two.settings.y()) == settings_at,
                       f"(at {two.settings.x()}, {two.settings.y()}; want {settings_at})")
    two._toggle_settings()
    two._toggle_settings()
    _pump(0.2)
    failures += _check("opening Settings again keeps its position",
                       (two.settings.x(), two.settings.y()) == settings_at,
                       f"(at {two.settings.x()}, {two.settings.y()})")
    failures += _check("NOTES opens at its saved position",
                       (two.notes.x(), two.notes.y()) == target, f"(at {two.notes.x()}, {two.notes.y()})")
    _close(two)

    # ---- third run: every saved position far off every monitor -----------
    # Only the secondary monitors count as connected here, so the nearest
    # screen is never the main one; the main monitor's area stands in for a
    # monitor that was removed.
    real_screens = QGuiApplication.screens
    QGuiApplication.screens = staticmethod(lambda: list(others))
    gone = real_primary.geometry().center()
    cases = {"far left": [geo.left() - 60000, geo.center().y()],
             "far right": [geo.right() + 60000, geo.center().y()],
             "far above": [geo.center().x(), geo.top() - 60000],
             "far below": [geo.center().x(), geo.bottom() + 60000],
             "on a removed monitor": [gone.x(), gone.y()]}
    try:
        for case, pos in cases.items():
            print(f"Third run: saved positions {case}")
            failures += _off_screen_run(app, {key: pos for key in ALL_KEYS})
        print("Third run: saved positions fully on screen")
        inside = {key: [geo.left() + 10 + 4 * i, geo.top() + 10 + 3 * i] for i, key in enumerate(ALL_KEYS)}
        failures += _off_screen_run(app, inside, unmoved=True)
    finally:
        QGuiApplication.screens = real_screens

    # ---- fourth run: RESET SETTINGS writes nothing back -----------------
    print("Fourth run: RESET SETTINGS")
    four = _overlay(app)
    four.start()
    _pump(0.5)
    four.open_tool("uex")
    four.uex.move(geo.left() + 30, geo.top() + 30)
    launched: list = []
    real_popen = main_mod.subprocess.Popen
    main_mod.subprocess.Popen = lambda args, **kw: launched.append(list(args))
    try:
        four._reset_settings()
        four.uex.show()
        four.uex.move(geo.left() + 70, geo.top() + 70)
        four.uex.hide()
        _pump(1.5)
        four.save_config()                 # main()'s aboutToQuit hook
    finally:
        main_mod.subprocess.Popen = real_popen
    failures += _check("reset restarted the app", len(launched) == 1, f"({launched})")
    failures += _check("reset: nothing written back (no config.json)", not CONFIG_PATH.is_file(),
                       f"({CONFIG_PATH.read_text(encoding='utf-8')[:80] if CONFIG_PATH.is_file() else ''})")
    _close(four)

    QGuiApplication.primaryScreen = real_primary_fn
    print("-" * 78)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
