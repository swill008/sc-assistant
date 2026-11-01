"""Honest data age and window pins on the Hauling, Ore Finder, Combat and
UEX panels.

    python -m tools.dataage_selftest            # checks the working tree
    python -m tools.dataage_selftest --root DIR # checks another copy of app/

Offline (network calls are replaced), uses a temporary %APPDATA%, and every
window is fully transparent before it is shown and placed on a secondary
monitor when there is one. Exit code = number of failures.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

_TMP = tempfile.TemporaryDirectory(prefix="ca-dataage-")
os.environ["APPDATA"] = _TMP.name          # before app.config is imported

ROOT = Path(__file__).resolve().parents[1]
if "--root" in sys.argv:
    ROOT = Path(sys.argv[sys.argv.index("--root") + 1]).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)

import app.hauling as hauling_mod  # noqa: E402
import app.orefinder as orefinder_mod  # noqa: E402


def _offline(*_args, **_kwargs):
    raise OSError("dataage_selftest: network disabled")


hauling_mod._get = _offline
hauling_mod._get_text = _offline
orefinder_mod._fetch = _offline

# A fixed "now" in the afternoon so day boundaries are predictable.
NOW = datetime(2026, 11, 1, 15, 0, 0).timestamp()


def _check(label: str, ok: bool, detail: str = "") -> int:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return 0 if ok else 1


def _show_hidden(widget) -> None:
    """Show a window without it ever being visible on the main monitor."""
    widget.setWindowOpacity(0.0)               # before show: never a visible frame
    primary = QGuiApplication.primaryScreen()
    others = [s for s in QGuiApplication.screens() if s is not primary]
    if others:
        geo = others[0].availableGeometry()
        widget.move(geo.left() + 20, geo.top() + 20)
    widget.show()
    QApplication.processEvents()


def _status_colour(label) -> str:
    return label.styleSheet().split("color:", 1)[-1].split(";", 1)[0].strip().lower()


def check_age_text() -> int:
    print("age formatter")
    try:
        from app.ui.data_age import age_text
    except ImportError as exc:
        return _check("age_text exists", False, str(exc))
    cases = [
        (NOW - 20, "just now"),
        (NOW - 5 * 60, "5 min ago"),
        (NOW - 59 * 60, "59 min ago"),
        (NOW - 2 * 3600, "2 h ago"),
        (datetime(2026, 10, 31, 14, 5).timestamp(), "yesterday 14:05"),
        (datetime(2026, 10, 29, 14, 5).timestamp(), "29 Oct 14:05"),
        (0, ""),
    ]
    failures = 0
    for stamp, want in cases:
        got = age_text(stamp, NOW)
        failures += _check(f"age_text -> {want!r}", got == want, f"(got {got!r})")
    return failures


def check_hauling() -> int:
    print("hauling")
    from app.hauling import Hauling, MissionBoard
    from app.ui import theme
    from app.ui.hauling_panel import HaulingPanel

    failures = 0
    panel = HaulingPanel(Hauling())
    panel._clock = lambda: NOW
    amber, good = theme.AMBER.name().lower(), theme.GOOD.name().lower()

    # Routes: fresh (5 min) = LIVE; past the 15 min lifetime = amber STALE.
    panel._tab = "routes"
    panel._commodity_id = 7
    panel._routes = [object()]
    panel.data._routes[7] = (NOW - 5 * 60, [])
    panel._update_footer()
    text = panel.footer.text()
    failures += _check("routes footer says UPDATED 5 MIN AGO",
                       "UPDATED 5 MIN AGO" in text, f"({text!r})")
    failures += _check("fresh routes: badge LIVE (green)",
                       panel.status.text() == "LIVE"
                       and _status_colour(panel.status) == good,
                       f"({panel.status.text()!r})")
    panel.data._routes[7] = (NOW - 20 * 60, [])
    panel._update_footer()
    failures += _check("routes past 15 min: badge STALE (amber)",
                       panel.status.text() == "STALE"
                       and _status_colour(panel.status) == amber,
                       f"({panel.status.text()!r} {_status_colour(panel.status)})")

    # Commodity list: 12 h lifetime.
    panel._commodity_id = None
    panel._routes = []
    panel.data._commodities_at = NOW - 13 * 3600
    panel._update_footer()
    text = panel.footer.text()
    failures += _check("commodity list age in footer", "LIST 13 H AGO" in text,
                       f"({text!r})")
    failures += _check("commodity list past 12 h: badge STALE (amber)",
                       panel.status.text() == "STALE"
                       and _status_colour(panel.status) == amber,
                       f"({panel.status.text()!r})")
    panel.data._commodities_at = NOW - 3600
    panel._update_footer()
    failures += _check("commodity list within 12 h: not STALE",
                       panel.status.text() == "IDLE", f"({panel.status.text()!r})")

    # Contracts: 24 h lifetime.
    panel._tab = "contracts"
    panel._missions = [object()]
    panel._mission_error = ""
    panel._board = MissionBoard(missions=[], captured="2026-10-20",
                                fetched_at=NOW - 2 * 3600)
    panel._update_footer()
    text = panel.footer.text()
    failures += _check("contracts footer says SYNCED 2 H AGO",
                       "SYNCED 2 H AGO" in text, f"({text!r})")
    failures += _check("contracts within 24 h: SNAPSHOT",
                       panel.status.text() == "SNAPSHOT", f"({panel.status.text()!r})")
    panel._board = MissionBoard(missions=[], captured="2026-10-20",
                                fetched_at=datetime(2026, 10, 30, 9, 0).timestamp())
    panel._update_footer()
    failures += _check("contracts past 24 h: badge STALE (amber)",
                       panel.status.text() == "STALE"
                       and _status_colour(panel.status) == amber,
                       f"({panel.status.text()!r})")
    failures += _check("old contracts show a date", "SYNCED 30 OCT 09:00" in panel.footer.text(),
                       f"({panel.footer.text()!r})")
    panel._tab = "routes"
    panel.shutdown(2000)
    panel.deleteLater()
    return failures


def check_orefinder() -> int:
    print("ore finder")
    from app.orefinder import INDEX_MAX_AGE, LiveData, Ore
    from app.ui import theme
    from app.ui.orefinder_panel import OreFinderPanel

    failures = 0
    data = LiveData(Path(_TMP.name) / "ore_cache.json")
    data.ores = [Ore(slug="quantanium", name="Quantanium", category="Ship")]
    data.index_at = NOW - 5 * 60
    panel = OreFinderPanel(data)
    panel._clock = lambda: NOW
    panel._update_footer()
    text = panel.footer.text()
    failures += _check("ore footer says SYNCED 5 MIN AGO", "SYNCED 5 MIN AGO" in text,
                       f"({text!r})")
    failures += _check("fresh ore list: LIVE", panel.status.text() == "LIVE",
                       f"({panel.status.text()!r})")
    data.index_at = NOW - INDEX_MAX_AGE - 60
    panel._update_footer()
    failures += _check(f"ore list past {INDEX_MAX_AGE // 60} min: badge STALE (amber)",
                       panel.status.text() == "STALE"
                       and _status_colour(panel.status) == theme.AMBER.name().lower(),
                       f"({panel.status.text()!r})")
    panel.deleteLater()
    return failures


class _FakeTracker:
    def __init__(self, path: Path):
        self.game_log_path = path
        self.error = ""
        self.stats = SimpleNamespace(kills=0, deaths=0, soft_dead_targets=0,
                                     destroyed_targets=0, last_event_at=None)


def check_combat() -> int:
    print("combat")
    from app.ui.combat_panel import CombatPanel

    failures = 0
    log = Path(_TMP.name) / "Game.log"
    log.write_text("<2026-11-01T14:00:00.000Z> hello\n", encoding="utf-8")
    tracker = _FakeTracker(log)
    panel = CombatPanel(tracker)
    panel._clock = lambda: NOW

    def run(mtime_age: float, event_age: float | None) -> str:
        os.utime(log, (NOW - mtime_age, NOW - mtime_age))
        tracker.stats.last_event_at = None if event_age is None else NOW - event_age
        panel._log_mtime = ("", 0.0, 0.0)
        panel._refresh_stats()
        return panel.status.text()

    got = run(10 * 60, None)
    failures += _check("Game.log quiet 10 min: IDLE · last event 10 min ago",
                       got == "IDLE · last event 10 min ago", f"({got!r})")
    got = run(10 * 60, 30)
    failures += _check("combat event 30 s ago: LIVE", got == "LIVE", f"({got!r})")
    got = run(15, None)
    failures += _check("Game.log written 15 s ago: LIVE", got == "LIVE", f"({got!r})")
    got = run(3 * 3600, 3 * 3600)
    failures += _check("both 3 h old: IDLE · last event 3 h ago",
                       got == "IDLE · last event 3 h ago", f"({got!r})")
    panel.deleteLater()
    return failures


def check_timers() -> int:
    print("timers only while visible")
    from app.hauling import Hauling
    from app.orefinder import LiveData
    from app.ui.combat_panel import CombatPanel
    from app.ui.hauling_panel import HaulingPanel
    from app.ui.orefinder_panel import OreFinderPanel

    failures = 0
    panels = [
        ("hauling", HaulingPanel(Hauling()), "_age_timer"),
        ("ore finder", OreFinderPanel(LiveData(Path(_TMP.name) / "ore2.json")), "_age_timer"),
        ("combat", CombatPanel(None), "_stats_timer"),
    ]
    for name, panel, attr in panels:
        timer = getattr(panel, attr, None)
        if timer is None:
            failures += _check(f"{name}: has {attr}", False)
            continue
        failures += _check(f"{name}: timer idle before show", not timer.isActive())
        if attr == "_age_timer":
            failures += _check(f"{name}: refresh every 30 s or less",
                               0 < timer.interval() <= 30_000, f"({timer.interval()} ms)")
        _show_hidden(panel)
        failures += _check(f"{name}: timer runs while visible", timer.isActive())
        panel.hide()
        QApplication.processEvents()
        failures += _check(f"{name}: timer stopped when hidden", not timer.isActive())
        if hasattr(panel, "shutdown"):
            panel.shutdown(2000)
        panel.deleteLater()
    return failures


def _head_layout_of(button):
    parent = button.parentWidget()
    stack = [parent.layout()]
    while stack:
        layout = stack.pop()
        if layout is None:
            continue
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget() is button:
                return layout, i
            if item.layout() is not None:
                stack.append(item.layout())
    return None, -1


def check_pins() -> int:
    print("window pins")
    from app.hauling import Hauling
    from app.orefinder import LiveData
    from app.ui.combat_panel import CombatPanel
    from app.ui.hauling_panel import HaulingPanel
    from app.ui.orefinder_panel import OreFinderPanel
    from app.ui.pin_button import PinButton
    from app.ui.uex_panel import UexPanel

    failures = 0
    panels = [
        ("hauling", lambda: HaulingPanel(Hauling())),
        ("ore finder", lambda: OreFinderPanel(LiveData(Path(_TMP.name) / "ore3.json"))),
        ("combat", lambda: CombatPanel(None)),
        ("uex", lambda: UexPanel()),
    ]
    for name, make in panels:
        panel = make()
        pins = panel.findChildren(PinButton)
        if len(pins) != 1 or not hasattr(panel, "pin_toggled"):
            failures += _check(f"{name}: one PinButton and pin_toggled", False,
                               f"({len(pins)} pins)")
            panel.deleteLater()
            continue
        pin = pins[0]
        layout, index = _head_layout_of(pin)
        right = layout.itemAt(index + 1).widget() if layout and index + 1 < layout.count() else None
        failures += _check(f"{name}: pin sits just left of ✕",
                           isinstance(right, QPushButton) and right.text() == "✕")
        seen: list[bool] = []
        panel.pin_toggled.connect(seen.append)
        panel.set_pinned(True)
        QApplication.processEvents()
        failures += _check(f"{name}: set_pinned(True) sets without echo",
                           panel.pinned is True and pin.isChecked() and seen == [],
                           f"(emitted {seen})")
        _show_hidden(panel)
        pin.click()
        QApplication.processEvents()
        failures += _check(f"{name}: click emits pin_toggled(False) once",
                           seen == [False] and panel.pinned is False, f"(emitted {seen})")
        pin.click()
        QApplication.processEvents()
        failures += _check(f"{name}: click again emits True",
                           seen == [False, True] and panel.pinned is True, f"(emitted {seen})")
        panel.hide()
        if hasattr(panel, "shutdown"):
            panel.shutdown(2000)
        panel.deleteLater()
    return failures


def main() -> int:
    print(f"app package: {ROOT / 'app'}")
    failures = 0
    for check in (check_age_text, check_hauling, check_orefinder, check_combat,
                  check_timers, check_pins):
        try:
            failures += check()
        except Exception as exc:  # report and keep going
            failures += _check(f"{check.__name__} ran", False,
                               f"({type(exc).__name__}: {exc})")
    QApplication.processEvents()
    print(f"\n{'ALL PASS' if not failures else f'{failures} FAILURE(S)'}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
